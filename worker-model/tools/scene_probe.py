#!/usr/bin/env python3
"""The scene probe: an epilogue appended to a Blender script that prints what the scene holds.

    python3 tools/scene_probe.py script.py            # append it, run the check in both versions, print the probes
    python3 tools/scene_probe.py script.py --print    # just print the script with the epilogue appended

At the end of the script, the epilogue prints one line, "chimera-probe: {json}", listing every object
(name, type, data name, whether it's in the scene), material and collection, the scene's world and
render engine, and the keys of ctx["objects"] if the script left a dict named ctx (or another global
dict with "scene" and "objects") at the top level. It only reads and prints, so it runs as it is in
Chimera's check sandbox. `parse` reads the line back from a run's output.

The line is kept under BUDGET characters, because `chimera --check-result` prints only the last
1,500 characters of a run's output: when the scene is bigger, lists are cut (chimera_ names and
ctx-registered objects kept first) and "cut" says how many of each were left out. The probe never
runs when the script stops before its end: an error, a quit, or a render (the check stops there).
"""
from __future__ import annotations

import json
import os
import re
import sys

PREFIX = "chimera-probe:"
BUDGET = 1100  # characters of the whole line, prefix included

EPILOGUE = r'''

# ---- chimera scene probe (worker-model/tools/scene_probe.py): reads the scene, prints one line ----
def _chimera_probe(_g, _budget=%(budget)d):
    import json
    out = {"v": 1}
    try:
        import bpy
        out["blender"] = "%%d.%%d.%%d" %% tuple(bpy.app.version[:3])
        ctx, ctx_name = None, None
        if isinstance(_g.get("ctx"), dict):
            ctx, ctx_name = _g["ctx"], "ctx"
        else:
            for k, v in list(_g.items()):
                if isinstance(v, dict) and "scene" in v and isinstance(v.get("objects"), dict):
                    ctx, ctx_name = v, k
                    break
        scene = bpy.context.scene
        if ctx is not None and getattr(ctx.get("scene"), "bl_rna", None) is not None:
            scene = ctx["scene"]
        in_scene = set(o.name for o in scene.objects)
        cut = lambda s: s if s is None or len(s) <= 64 else s[:61] + "..."
        objs = [[cut(o.name), o.type, cut(o.data.name) if o.data is not None else None, 1 if o.name in in_scene else 0]
                for o in bpy.data.objects]
        out["scene"] = cut(scene.name)
        out["engine"] = scene.render.engine
        out["world"] = cut(scene.world.name) if scene.world is not None else None
        out["objects"] = objs
        out["materials"] = [cut(m.name) for m in bpy.data.materials]
        out["collections"] = [cut(c.name) for c in bpy.data.collections]
        keep = set()
        if ctx is not None:
            reg = ctx.get("objects") if isinstance(ctx.get("objects"), dict) else {}
            col = ctx.get("collection")
            out["ctx"] = {"name": ctx_name, "keys": sorted(cut(str(k)) for k in reg),
                          "collection": cut(getattr(col, "name", None)) if col is not None else None}
            keep = set(getattr(v, "name", None) for v in reg.values())
        # Over budget: cut the longest list from its end; chimera_ names and ctx-registered objects go first.
        def rank(x):
            name = x[0] if isinstance(x, list) else x
            return 0 if (str(name).startswith("chimera_") or name in keep) else 1
        lists = [("objects", out), ("materials", out), ("collections", out)]
        if "ctx" in out:
            lists.append(("keys", out["ctx"]))
        total = {name: len(owner[name]) for name, owner in lists}
        for name, owner in lists:
            owner[name] = sorted(owner[name], key=rank)[:200]

        def size():  # the whole line, with "cut" saying how many of each list were left out
            dropped = {name: total[name] - len(owner[name]) for name, owner in lists if total[name] > len(owner[name])}
            if dropped:
                out["cut"] = dropped
            return len(json.dumps(out, separators=(",", ":"))) + %(prefix_len)d
        while size() > _budget:
            name, owner = max(lists, key=lambda l: len(json.dumps(l[1][l[0]])))
            if not owner[name]:
                break
            owner[name].pop()
    except Exception as e:  # never break the script it's appended to
        out = {"v": 1, "probe_failed": (type(e).__name__ + " " + str(e))[:300]}
    print("%(prefix)s " + json.dumps(out, separators=(",", ":"), ensure_ascii=True), flush=True)


_chimera_probe(globals())
del _chimera_probe
''' % {"budget": BUDGET, "prefix": PREFIX, "prefix_len": len(PREFIX) + 1}


def append(script: str, budget: int = BUDGET) -> str:
    """The script with the probe at its end."""
    ep = EPILOGUE if budget == BUDGET else EPILOGUE.replace(f"_budget={BUDGET}", f"_budget={int(budget)}", 1)
    return script.rstrip("\n") + "\n" + ep


def is_probe_line(line: str) -> bool:
    return line.lstrip("…").lstrip().startswith(PREFIX)


def without_probe(output: str) -> str:
    """The output minus probe lines (so the strict check doesn't read object names as errors)."""
    return "\n".join(l for l in output.splitlines() if not is_probe_line(l))


DUPE = re.compile(r"\.\d{3}$")


def parse(output: str):
    """The last probe in a run's output as a dict, or None (no probe line, or it was cut off).
    Objects come back as dicts; "dupes" lists names Blender suffixed with .001 and the like."""
    if not output:
        return None
    i = output.rfind(PREFIX)
    if i < 0:
        return None
    line = output[i + len(PREFIX):].split("\n", 1)[0].strip()
    try:
        d = json.loads(line)
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    if "objects" in d:
        d["objects"] = [{"name": o[0], "type": o[1], "data": o[2], "in_scene": bool(o[3])} for o in d["objects"]]
        names = [o["name"] for o in d["objects"]] + list(d.get("materials") or []) + list(d.get("collections") or [])
        d["dupes"] = sorted(n for n in names if isinstance(n, str) and DUPE.search(n))
    return d


def summary(p) -> str:
    """One short line for a report."""
    if p is None:
        return "no probe (the script stopped before its end, or the line was cut)"
    if "probe_failed" in p:
        return "probe failed: " + p["probe_failed"]
    objs = ", ".join(f"{o['name']} ({o['type'].lower()})" + ("" if o["in_scene"] else " not in scene") for o in p["objects"])
    parts = [f"{p.get('engine')}", f"world {p.get('world')}", f"objects: {objs or 'none'}",
             f"materials: {', '.join(p.get('materials') or []) or 'none'}"]
    if p.get("ctx"):
        parts.append(f"ctx[\"objects\"] keys: {', '.join(p['ctx']['keys']) or 'none'}")
    if p.get("cut"):
        parts.append("cut: " + ", ".join(f"{v} {k}" for k, v in p["cut"].items()))
    if p.get("dupes"):
        parts.append("duplicates: " + ", ".join(p["dupes"]))
    return "; ".join(parts)


def main(argv=None):
    import argparse
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.dirname(here) not in sys.path:
        sys.path.insert(0, os.path.dirname(here))
    from tools import blender_check
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script")
    ap.add_argument("--print", action="store_true", help="print the script with the probe appended, run nothing")
    ap.add_argument("--json", action="store_true")
    blender_check.add_run_args(ap)
    a = ap.parse_args(argv)
    if a.print:
        with open(a.script, encoding="utf-8") as f:
            print(append(f.read()))
        return 0
    results = blender_check.run_from_args(a, [a.script], probe=True)
    if a.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            print(f"Blender {r['version']}: {r['outcome']}, strict {'pass' if r['strict'] else 'FAIL'}: {summary(r.get('probe'))}")
    return 0 if all(r.get("probe") and "probe_failed" not in r["probe"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
