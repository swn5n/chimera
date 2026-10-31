#!/usr/bin/env python3
"""Report disk space for the worker model's plan. It never deletes anything.

    python3 tools/disk_ledger.py            # the table, in GB (10^9 bytes)
    python3 tools/disk_ledger.py --json     # the same numbers as JSON

Shows the free space, the size of every entry in ~/chimera-tools/helper-train (with v3 split into
what the plan keeps and its optional leftovers), the Ollama models folder (each model's own and
shared blobs, read from the manifests on disk, no Ollama call), and what the plan's training needs
at its peak, for each base model (docs/hydra-worker-plan.md, "5. TRAINING", Disk). Sizes are disk
usage like du: allocated blocks, hard links counted once, symlinks not followed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

GB = 1e9
GIB = 1024 ** 3
HELPER_TRAIN = os.path.expanduser("~/chimera-tools/helper-train")
SHARE_MIN = 1e6  # bytes two models must share before the table says so

# v3 files the plan keeps when slimming it (decision 4): the release GGUF, the adapters, the Modelfiles.
V3_KEEP = ("helper-q5_k_m.gguf", "adapters")
V3_KEEP_PREFIX = ("Modelfile", "base.Modelfile")

# The plan's estimates (GB, Oct 29). Baselines: gemma4:12b-it-q4_K_M 8.0 + qwen3:14b 9.3, kept in
# Ollama. The Hugging Face base, the fused model and the bf16 GGUF are each about the base's bf16
# size and all three exist at once while the GGUF is written (the fused model goes after it).
PLAN = {
    "baselines": 17.3,
    "baselines_optional": 20.6,   # gpt-oss:20b 14 + qwen3.5:9b 6.6, recommended skip
    "bases": {
        "gemma-4-12b": {"hf": 24.0, "q5_k_m": 8.5, "plan_peak": 90.0},
        "qwen3-14b": {"hf": 29.5, "q5_k_m": 10.5, "plan_peak": 110.0},
    },
    "train_free_check": 90.0,     # run_train_worker.sh's free-disk check
}


def tree_size(path, seen=None):
    """(bytes on disk, files, unreadable entries) under path, like du: lstat, blocks, hard links once."""
    seen = set() if seen is None else seen
    total = files = errors = 0
    stack = [path]
    while stack:
        p = stack.pop()
        try:
            st = os.lstat(p)
        except OSError:
            errors += 1
            continue
        key = (st.st_dev, st.st_ino)
        if key in seen:
            continue
        seen.add(key)
        total += getattr(st, "st_blocks", 0) * 512 or st.st_size
        if os.path.isdir(p) and not os.path.islink(p):
            try:
                with os.scandir(p) as it:
                    stack.extend(e.path for e in it)
            except OSError:
                errors += 1
        else:
            files += 1
    return total, files, errors


def disk_free(path):
    u = shutil.disk_usage(path)
    return {"path": path, "free": u.free, "total": u.total}


def helper_train(root=HELPER_TRAIN):
    """Each top-level entry's size, plus v3 split into kept and leftover parts."""
    out = {"root": root, "entries": [], "v3": None}
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        size, files, errors = tree_size(os.path.join(root, name))
        out["entries"].append({"name": name, "bytes": size, "files": files, "errors": errors})
    v3 = os.path.join(root, "v3")
    if os.path.isdir(v3):
        keep = left = 0
        leftovers = []
        for name in sorted(os.listdir(v3)):
            size = tree_size(os.path.join(v3, name))[0]
            if name in V3_KEEP or name.startswith(V3_KEEP_PREFIX) or size < 1e6:
                keep += size  # small files (logs, markers, configs) stay too
            else:
                left += size
                leftovers.append({"name": name, "bytes": size})
        out["v3"] = {"keep": keep, "leftovers": left, "leftover_items": leftovers}
    return out


def ollama_dir():
    return os.environ.get("OLLAMA_MODELS") or os.path.expanduser("~/.ollama/models")


def manifest_name(rel):
    """manifests path to a model name: registry.ollama.ai/library/qwen3/8b -> qwen3:8b."""
    parts = rel.replace(os.sep, "/").split("/")
    if len(parts) < 3:
        return rel
    host, tag = parts[0], parts[-1]
    repo = parts[1:-1]
    if host in ("registry.ollama.ai", "ollama.com"):
        if repo and repo[0] == "library":
            repo = repo[1:]
        return "/".join(repo) + ":" + tag
    return host + "/" + "/".join(repo) + ":" + tag


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _layers(m, models_dir, depth=0):
    """A manifest's {digest: size}; a manifest list (one model in several runner formats) adds up its parts."""
    if not isinstance(m, dict):
        return {}
    out = {l["digest"]: int(l.get("size") or 0) for l in list(m.get("layers") or []) + [m.get("config") or {}] if l.get("digest")}
    if depth < 2:
        for sub in m.get("manifests") or []:
            d = sub.get("digest", "")
            out.update(_layers(_load_json(os.path.join(models_dir, "blobs", d.replace(":", "-"))), models_dir, depth + 1))
    return out


def read_manifests(models_dir):
    """{model name: {digest: size}} from manifests/ and manifests-v2/ (whose files are symlinks to blobs)."""
    models = {}
    for sub in ("manifests", "manifests-v2"):
        base = os.path.join(models_dir, sub)
        for dirpath, _dirs, names in os.walk(base):
            for n in names:
                path = os.path.join(dirpath, n)
                m = _load_json(path)
                if m is None:
                    continue
                name = manifest_name(os.path.relpath(path, base))
                models.setdefault(name, {}).update(_layers(m, models_dir))
    return models


def ollama_models(models_dir=None):
    models_dir = models_dir or ollama_dir()
    out = {"dir": models_dir, "bytes": 0, "models": []}
    if not os.path.isdir(models_dir):
        return out
    out["bytes"] = tree_size(models_dir)[0]
    models = read_manifests(models_dir)
    users = {}
    for name, layers in models.items():
        for d in layers:
            users.setdefault(d, set()).add(name)
    for name, layers in sorted(models.items(), key=lambda kv: -sum(kv[1].values())):
        own = sum(s for d, s in layers.items() if len(users[d]) == 1)
        shared = {}
        for d, s in layers.items():
            for u in users[d] - {name}:
                shared[u] = shared.get(u, 0) + s
        # Only sharing that matters for space: a common licence or template file is a few KB.
        shared_with = sorted(u for u, s in shared.items() if s >= SHARE_MIN)
        out["models"].append({"name": name, "bytes": sum(layers.values()), "own": own, "shared_with": shared_with})
    return out


def plan_needs(free, v1v2=0.0, v3_left=0.0):
    """Peak need per base and the headroom now, after deleting v1 and v2, and after slimming v3 too (GB)."""
    rows = []
    for base, b in PLAN["bases"].items():
        # Baselines stay in Ollama; HF base + fused + bf16 GGUF exist together while the GGUF is written.
        peak = PLAN["baselines"] + 3 * b["hf"]
        rows.append({"base": base, "hf": b["hf"], "q5_k_m": b["q5_k_m"], "peak": round(peak, 1), "plan_peak": b["plan_peak"],
                     "headroom_now": round(free - peak, 1),
                     "headroom_without_v1_v2": round(free + v1v2 - peak, 1),
                     "headroom_also_slim_v3": round(free + v1v2 + v3_left - peak, 1)})
    return rows


def ledger():
    home = os.path.expanduser("~")
    d = disk_free(home)
    ht = helper_train()
    ol = ollama_models()
    sizes = {e["name"]: e["bytes"] for e in ht["entries"]}
    v1v2 = (sizes.get("v1", 0) + sizes.get("v2", 0)) / GB
    v3_left = (ht["v3"] or {}).get("leftovers", 0) / GB
    return {"disk": d, "helper_train": ht, "ollama": ol,
            "plan": {"estimates": PLAN, "needs": plan_needs(d["free"] / GB, v1v2, v3_left)}}


def gb(n):
    return f"{n / GB:.1f}"


def table(rows, head):
    widths = [max(len(str(r[i])) for r in [head] + rows) for i in range(len(head))]
    line = lambda r: "| " + " | ".join(str(c).ljust(w) for c, w in zip(r, widths)) + " |"  # noqa: E731
    return "\n".join([line(head), "|" + "|".join("-" * (w + 2) for w in widths) + "|"] + [line(r) for r in rows])


def render(L):
    d = L["disk"]
    out = [f"Disk: {gb(d['free'])} GB free ({d['free'] / GIB:.1f} GiB) of {gb(d['total'])} GB, on the volume holding {d['path']}.",
           "Nothing here deletes anything; sizes are disk usage in GB (10^9 bytes).", ""]
    ht = L["helper_train"]
    out.append(f"## {ht['root']}")
    if ht["entries"]:
        rows = [[e["name"], gb(e["bytes"]), e["files"]] + ([f"{e['errors']} unreadable"] if e["errors"] else [""]) for e in ht["entries"]]
        rows.append(["total", gb(sum(e["bytes"] for e in ht["entries"])), sum(e["files"] for e in ht["entries"]), ""])
        out.append(table(rows, ["entry", "GB", "files", "note"]))
        if ht["v3"]:
            v = ht["v3"]
            items = ", ".join(f"{i['name']} {gb(i['bytes'])}" for i in v["leftover_items"])
            out += ["", f"v3 split (plan decision 4): keep {gb(v['keep'])} GB (helper-q5_k_m.gguf, adapters, Modelfiles, small files); "
                        f"optional leftovers {gb(v['leftovers'])} GB: {items}."]
    else:
        out.append("(not there)")
    ol = L["ollama"]
    out += ["", f"## Ollama models: {ol['dir']}, {gb(ol['bytes'])} GB on disk"]
    if ol["models"]:
        rows = [[m["name"], gb(m["bytes"]), gb(m["own"]), ", ".join(m["shared_with"]) or ""] for m in ol["models"]]
        out.append(table(rows, ["model", "GB", "own GB", "shares blobs with"]))
    pl = L["plan"]
    est = pl["estimates"]
    out += ["", "## What the plan's training needs (GB, docs/hydra-worker-plan.md)",
            f"Baselines in Ollama {est['baselines']} (+{est['baselines_optional']} optional). Peak = baselines + Hugging Face base "
            "+ fused model + bf16 GGUF, all there while the GGUF is written. run_train_worker.sh is to check for "
            f"{est['train_free_check']:.0f} GB free.", ""]
    rows = [[n["base"], n["hf"], n["q5_k_m"], n["peak"], n["plan_peak"], n["headroom_now"], n["headroom_without_v1_v2"],
             n["headroom_also_slim_v3"]] for n in pl["needs"]]
    out.append(table(rows, ["base", "HF bf16", "Q5_K_M", "peak", "plan says", "headroom now", "without v1+v2", "also slim v3"]))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="print JSON instead of the table")
    a = ap.parse_args(argv)
    L = ledger()
    print(json.dumps(L, indent=2) if a.json else render(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
