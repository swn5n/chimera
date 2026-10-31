#!/usr/bin/env python3
"""Dump Blender's own API facts from each Blender version, and lint scripts against them.

    python3 tools/rna_dump.py dump                     # 5.2.2 and 5.0.1 into data/rna/<version>.json
    python3 tools/rna_dump.py dump --versions 5.0.1 --blender 5.0.1=/path/to/Blender
    python3 tools/rna_dump.py lint script.py [...]     # names neither version has (exit 1 on any error)
    python3 tools/rna_dump.py show ShaderNodeBsdfPrincipled BevelModifier RenderSettings.engine
    python3 tools/rna_dump.py diff                     # what one version has and the other doesn't

`dump` runs each Blender directly, headless (-b --factory-startup), on tools/rna_dump_blender.py, our
own fixed script, so it needs no sandbox. A dump holds: every RNA class's own properties (type,
pointer target, enum items), functions and Python attributes with its base class; the input and
output sockets (name, identifier, socket type) of every node type Blender lets it make in a shader,
geometry, compositor and texture node tree; enum values measured on live instances; the modifier,
constraint, light, texture and curve type-to-class maps; mathutils/bmesh/bpy module names and
bpy.ops operators. About 1 MB per version, under a second each.

Facts made by Blender itself, for the teacher's hints and as a data filter: never training text,
and not shipped with Chimera. The lint is tools/rna_lint.py.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # worker-model/
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from tools import blenders, rna_lint  # noqa: E402

BLENDER_SCRIPT = os.path.join(HERE, "tools", "rna_dump_blender.py")
RNA_DIR = rna_lint.RNA_DIR


def work_root(out_dir):
    """Where Blender runs: $WM_SCRATCH when it is set, else the dumps' own (gitignored) folder."""
    root = os.environ.get("WM_SCRATCH") or out_dir
    os.makedirs(root, exist_ok=True)
    return root


def dump_one(version, blender, out_dir=RNA_DIR, timeout=300):
    """Run one Blender on the dump script; returns a record (path, size, seconds, counts or error).
    Blender runs in a fresh folder (its cwd and TMPDIR) that is removed afterwards."""
    rec = {"version": version, "blender": blender}
    why = blenders.check_path(blender)
    if why:
        rec["error"] = why
        return rec
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f"rna-{version}-", suffix=".json", dir=out_dir)
    os.close(fd)
    work = tempfile.mkdtemp(prefix=f".rna-run-{version}-", dir=work_root(out_dir))
    t0 = time.monotonic()
    try:
        p = subprocess.run([blender, "-b", "--factory-startup", "--python-exit-code", "1", "--python", BLENDER_SCRIPT,
                            "--", tmp], capture_output=True, text=True, timeout=timeout, cwd=work,
                           env=dict(os.environ, TMPDIR=work))
        rec["seconds"] = round(time.monotonic() - t0, 2)
        if p.returncode != 0:
            rec["error"] = f"Blender exited {p.returncode}: " + (p.stderr or p.stdout).strip()[-400:]
            return rec
        with open(tmp, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("blender") != version:
            rec["error"] = f"asked for {version} but {blender} is Blender {d.get('blender')}"
            return rec
        path = os.path.join(out_dir, f"{version}.json")
        os.replace(tmp, path)
        os.chmod(path, 0o644)
        rec.update(path=path, bytes=os.path.getsize(path), classes=len(d["classes"]),
                   nodes={k: len(v) for k, v in d["nodes"].items()}, live_enums=len(d.get("live_enums", {})),
                   ops=sum(len(v) for v in d["ops"].values()), version_string=d["version_string"])
        return rec
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        rec["error"] = f"{type(e).__name__}: {e}"
        return rec
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
        shutil.rmtree(work, ignore_errors=True)


def cmd_dump(a):
    pairs = blenders.pick(blenders.parse_overrides(a.blender), a.versions)
    bad = 0
    for v, path in pairs:
        r = dump_one(v, path, a.out)
        if r.get("error"):
            bad += 1
            print(f"Blender {v}: FAILED: {r['error']}")
            continue
        nodes = ", ".join(f"{k.replace('NodeTree', '').lower()} {n}" for k, n in r["nodes"].items())
        print(f"Blender {v} ({r['version_string']}): {r['path']}, {r['bytes'] / 1e6:.1f} MB in {r['seconds']} s: "
              f"{r['classes']} classes; nodes {nodes}; {r['live_enums']} live enums; {r['ops']} operators")
    return 1 if bad else 0


def cmd_lint(a):
    facts = rna_lint.Facts.load(a.rna)
    linter = rna_lint.Linter(facts)
    results, errors = {}, 0
    for path in a.scripts:
        with open(path, encoding="utf-8") as f:
            found = linter.lint(f.read(), path)
        results[path] = found
        errors += sum(1 for x in found if x["level"] == "error")
    if a.json:
        print(json.dumps({"versions": facts.versions, "results": results}, indent=2))
    else:
        for path, found in results.items():
            if found:
                print(rna_lint.format_findings(found, path))
            else:
                print(f"{path}: nothing flagged (Blender {', '.join(facts.versions)})")
    return 1 if errors else 0


def cmd_show(a):
    facts = rna_lint.Facts.load(a.rna)
    for name in a.names:
        cls, _, attr = name.partition(".")
        print(f"== {name}")
        for v in facts.versions:
            node = facts.node(cls, v)
            if attr:
                p = facts.prop(cls, attr, v)
                items = facts.enum_items(cls, attr, v)
                print(f"  {v}: {p}" + (f" values: {sorted(items)}" if items else ""))
            elif node:
                ins = ", ".join(s[0] for s in node["inputs"])
                outs = ", ".join(s[0] for s in node["outputs"])
                print(f"  {v}: \"{node['label']}\" in: {ins} | out: {outs}" + (" (dynamic sockets)" if node["dynamic"] else ""))
            elif facts.has_class(cls, v):
                k = facts.dumps[v]["classes"][cls]
                print(f"  {v}: base {k['base']}; props: {', '.join(sorted(k['props']))}; funcs: {', '.join(k['funcs'])}")
            else:
                print(f"  {v}: not there")
    return 0


def cmd_diff(a):
    facts = rna_lint.Facts.load(a.rna)
    if len(facts.versions) < 2:
        print("need two dumps")
        return 1
    new, old = facts.versions[0], facts.versions[1]
    dn, do = facts.dumps[new], facts.dumps[old]
    nn = {i for t in dn["nodes"].values() for i in t}
    no = {i for t in do["nodes"].values() for i in t}
    print(f"node types only in {new}: {len(nn - no)}: {', '.join(sorted(nn - no))}")
    print(f"node types only in {old}: {len(no - nn)}: {', '.join(sorted(no - nn))}")
    socket_changes = []
    for i in sorted(nn & no):
        a_, b_ = facts.node(i, new), facts.node(i, old)
        for side in ("inputs", "outputs"):
            sa, sb = {s[0] for s in a_[side]}, {s[0] for s in b_[side]}
            if sa != sb:
                socket_changes.append(f"{i}.{side}: +{sorted(sa - sb)} -{sorted(sb - sa)}")
    print(f"node types whose socket names differ: {len(socket_changes)}")
    for line in socket_changes[:a.limit]:
        print("  " + line)
    cn, co = set(dn["classes"]), set(do["classes"])
    print(f"classes only in {new}: {len(cn - co)}; only in {old}: {len(co - cn)}: {', '.join(sorted(co - cn)[:a.limit])}")
    prop_changes = []
    for c in sorted(cn & co):
        pa, pb = set(dn["classes"][c]["props"]), set(do["classes"][c]["props"])
        if pb - pa:
            prop_changes.append(f"{c}: gone in {new}: {sorted(pb - pa)}")
    print(f"classes that lost properties in {new}: {len(prop_changes)}")
    for line in prop_changes[:a.limit]:
        print("  " + line)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump", help="dump each Blender's API facts")
    d.add_argument("--versions", help="comma-separated, default every version in tools/blenders.py")
    d.add_argument("--blender", action="append", metavar="VERSION=PATH")
    d.add_argument("--out", default=RNA_DIR, help=f"default {RNA_DIR}")
    l = sub.add_parser("lint", help="flag names neither version has")
    l.add_argument("scripts", nargs="+")
    l.add_argument("--json", action="store_true")
    s = sub.add_parser("show", help="print what the dumps say about classes, node types or Class.prop")
    s.add_argument("names", nargs="+")
    df = sub.add_parser("diff", help="differences between the two versions' dumps")
    df.add_argument("--limit", type=int, default=40)
    for p in (l, s, df):
        p.add_argument("--rna", default=RNA_DIR, help=f"the dumps' folder (default {RNA_DIR})")
    a = ap.parse_args(argv)
    try:
        return {"dump": cmd_dump, "lint": cmd_lint, "show": cmd_show, "diff": cmd_diff}[a.cmd](a)
    except ValueError as e:
        print(f"rna_dump: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
