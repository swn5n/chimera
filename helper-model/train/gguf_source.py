#!/usr/bin/env python3
"""Make the folder llama.cpp's converter reads: the merged model's weights and config (linked, not copied) with
the base model's own tokenizer files. The merged folder itself isn't changed.

    python train/gguf_source.py --base Qwen/Qwen3-4B-Instruct-2507 --fused RUN/fused --out RUN/gguf-src

LoRA training doesn't change the tokenizer, but MLX-LM saves the tokenizer files with a newer transformers (5.x)
than llama.cpp's converter uses (4.57), and 4.57 can't read them ("'list' object has no attribute 'keys'").
The base model's files in the Hugging Face cache (downloaded only if they aren't there) say the same thing in
the older format, and they're used only if their vocabulary matches the merged model's exactly; failing that,
the merged model's own files are used. Either way tokenizer_config.json is then put in the 4.x form, in case
it was written by 5.x (the merged model's always is; the base model's could be, if its repo was updated).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys

EXTRA = ("vocab.json", "merges.txt", "special_tokens_map.json", "added_tokens.json")


def is_tokenizer_file(name):
    return name.startswith("tokenizer") or name in EXTRA


def hub_caches():
    env = os.environ
    out = [env[k] for k in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE") if env.get(k)]
    if env.get("HF_HOME"):
        out.append(os.path.join(env["HF_HOME"], "hub"))
    out.append(os.path.join(env.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "huggingface", "hub"))
    return out


def cached_snapshot(repo):
    """The cached snapshot of repo with its tokenizer files (the one refs/main names first, then newest), or None."""
    for cache in hub_caches():
        root = os.path.join(cache, "models--" + repo.replace("/", "--"))
        snaps = sorted(glob.glob(os.path.join(root, "snapshots", "*")), key=os.path.getmtime, reverse=True)
        try:
            with open(os.path.join(root, "refs", "main"), encoding="utf-8") as f:
                snaps.insert(0, os.path.join(root, "snapshots", f.read().strip()))
        except OSError:
            pass
        for s in snaps:
            if all(os.path.isfile(os.path.join(s, n)) for n in ("tokenizer.json", "tokenizer_config.json")):
                return s
    return None


def downloaded_snapshot(repo):
    try:
        from huggingface_hub import snapshot_download
        return snapshot_download(repo, allow_patterns=["tokenizer*", *EXTRA])
    except Exception as e:  # offline, or no huggingface_hub
        print(f"couldn't download {repo}'s tokenizer files: {e}", file=sys.stderr)
        return None


def vocabulary(folder):
    """What a tokenizer.json maps: its model type, tokens -> ids, merges, and added tokens -> (id, special)."""
    with open(os.path.join(folder, "tokenizer.json"), encoding="utf-8") as f:
        t = json.load(f)
    m = t.get("model") or {}
    merges = [x if isinstance(x, str) else " ".join(x) for x in m.get("merges") or []]
    added = {a["content"]: (a["id"], bool(a.get("special"))) for a in t.get("added_tokens") or []}
    return m.get("type"), m.get("vocab"), merges, added


def as_4x(cfg):
    """A transformers 5.x tokenizer_config.json in the 4.x form. 5.x saves the extra special tokens as a list named
    extra_special_tokens; 4.x calls that list additional_special_tokens and reads extra_special_tokens as a dict
    of named tokens. The other keys dropped are 5.x's own bookkeeping."""
    cfg = dict(cfg)
    extra = cfg.pop("extra_special_tokens", None)
    if isinstance(extra, dict):
        cfg["extra_special_tokens"] = extra
    elif extra:
        cfg.setdefault("additional_special_tokens", list(extra))
    for k in ("backend", "is_local", "local_files_only"):
        cfg.pop(k, None)
    return cfg


def copy_tokenizer(src, out, skip=()):
    names = []
    for name in sorted(os.listdir(src)):
        p = os.path.join(src, name)
        if os.path.isfile(p) and is_tokenizer_file(name) and name not in skip:
            shutil.copyfile(p, os.path.join(out, name))  # follows the cache's links to its blobs
            names.append(name)
    return names


def build(base, fused, out):
    """Make out/; returns where its tokenizer files came from."""
    if not os.path.isfile(os.path.join(fused, "config.json")) or not os.path.isfile(os.path.join(fused, "tokenizer.json")):
        raise SystemExit(f"no merged model (config.json and tokenizer.json) in {fused}")
    if os.path.lexists(out):
        shutil.rmtree(out)  # only ever made by this script: links and small copies
    os.makedirs(out)
    for name in sorted(os.listdir(fused)):
        p = os.path.join(fused, name)
        if os.path.isfile(p) and not is_tokenizer_file(name):
            os.symlink(os.path.abspath(p), os.path.join(out, name))
    src = cached_snapshot(base) or downloaded_snapshot(base)
    if src and vocabulary(src) != vocabulary(fused):
        print("The base model's tokenizer doesn't match the merged model's, so the merged model's is used.", file=sys.stderr)
        src = None
    if src:
        how = f"the base model's, from {src} (same vocabulary as the merged model's):"
    else:
        src, how = fused, "the merged model's:"
    names = copy_tokenizer(src, out)
    cfg_path = os.path.join(out, "tokenizer_config.json")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    if as_4x(cfg) != cfg:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(as_4x(cfg), f, indent=2, ensure_ascii=False)
            f.write("\n")
        names[names.index("tokenizer_config.json")] += " (put in the transformers 4.x form)"
    return f"{how} {', '.join(names)}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="the base model's Hugging Face name")
    ap.add_argument("--fused", required=True, help="the merged model folder MLX-LM wrote")
    ap.add_argument("--out", required=True, help="the folder to make (replaced if it exists)")
    a = ap.parse_args(argv)
    print("Tokenizer files for the conversion:", build(a.base, a.fused, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
