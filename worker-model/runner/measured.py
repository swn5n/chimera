#!/usr/bin/env python3
"""Measured handoffs: what the Blender pieces so far really built, for the next worker. EVAL ONLY for now.

A worker that puts a lamp on a table has to guess where the table's top is, because it can't see the step that built
it. So after each Blender piece the pieces so far are joined and run, and Blender says where everything ended up.
This is the text a later step gets. Every number in it is printed by Blender; nothing is written by a model.
"""
from __future__ import annotations

import json

from runner import blender_run

MEASURE_SRC = r'''
import bpy, json
from mathutils import Vector
rows = []
for o in bpy.context.scene.objects:
    if o.type not in ("MESH", "CURVE", "SURFACE", "FONT", "META"):
        continue
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    rows.append({"name": o.name[:40], "lo": [round(x, 3) for x in lo], "hi": [round(x, 3) for x in hi]})
print("CHIMERA_PROBE " + json.dumps({"measured": rows}))
'''

HEAD = "Measured in Blender after the steps so far ran. Build on these real positions; z is up:"
MAX_ROWS = 30


def facts_text(rows):
    """The text for a later step, or "" if nothing was built."""
    lines = []
    for r in rows[:MAX_ROWS]:
        lo, hi = r["lo"], r["hi"]
        mid = [round((a + b) / 2, 2) for a, b in zip(lo, hi)]
        size = [round(b - a, 2) for a, b in zip(lo, hi)]
        lines.append(f"{r['name']}: centre ({mid[0]}, {mid[1]}, {mid[2]}), size {size[0]} x {size[1]} x {size[2]}, "
                     f"bottom z {round(lo[2], 2)}, top z {round(hi[2], 2)}")
    if not lines:
        return ""
    if len(rows) > MAX_ROWS:
        lines.append(f"… and {len(rows) - MAX_ROWS} more.")
    return HEAD + "\n" + "\n".join(lines)


class Measure:
    """measure(script) -> the text for the next step ("" if it can't run)."""

    def __init__(self, chimera=None, version="5.2.2", versions=None):
        self.b = blender_run.Blender(chimera=chimera, versions=versions)
        self.version = version if version in self.b.versions else next(iter(self.b.versions))
        self.b.probe_src = MEASURE_SRC

    def __call__(self, script):
        r = self.b._probe_one(script, self.b.versions[self.version], self.version)
        rows = (r.get("probe") or {}).get("measured")
        return facts_text(rows) if rows else ""
