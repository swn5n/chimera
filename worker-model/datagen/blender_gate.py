"""The Blender gate: whether a teacher's Blender piece works, alone and joined after the pieces kept before it, and
whether a whole plan's kept pieces work together (DESIGN.md, "blender_gate.py").

    gate = BlenderGate(chimera, Cache(data_dir + "/cache/runs.jsonl"))
    r = gate.piece_check(plan, i, reply, verdict, earlier, goal)   # {"ok", "reasons", ..., "crash"}
    p = gate.plan_check(plan, kept, goal)                           # {"ok", "reasons", "culprit", ...}

A piece goes through three steps, stopping at the first that fails: the removed-API lint (tools/rna_lint), a run of
the piece alone (Go's alone script: its own code, guard blanked, so every line keeps the piece's own number, then a
fresh ctx and build_sN(ctx)), and a run of the join (Chimera's --hydra-assemble) of the earlier kept pieces and this
one. After a lint error the piece still runs alone, only so a repair gets the real crash. Every run is both of
runner.blender_run.Blender's runs in every Blender version: Chimera's own result check (through chimera.check_result,
so the look is off and Chimera asks the Ollama its env names) and the direct sandboxed run whose whole output is
read. The strict verdict that counts needs both (blender_run.counted_strict).

The direct run keeps only tools/scene_probe's epilogue (ctx keys, names, .001 duplicates; the eval's probe is replaced
by a no-op, so nothing of eval/ runs or is read) plus three lines of this module's own and datagen/silent.py's (its
prelude, a third --python-expr, watches the script's own frames; its report, right after the script and before every
other epilogue, stops watching first, so nothing after the script is watched). The names line: the ctx["objects"] keys
whose objects still exist, the ctx["values"] keys (the contract's channel for plain values since Nov 4: keys only, never
the values), and the names of the objects, materials, collections, node groups, worlds and other non-object-data blocks,
so a handoff that provides a node group, a world or a value is found, and a deleted object isn't. The measuring line
(MEASURE_EPILOGUE, data generation's only: tools/scene_probe and its budget are the eval's too): the scene evaluated at
its current frame, with the script's update and frame handlers held off and stdout and stderr shut meanwhile, so the
run's verdict is what it was without it; then per object its size in world units (its bounds times its world scale, so a
turned box keeps its sides; a curve's, a text's and a surface's from its evaluated mesh, whose bound_box isn't its
shape's: 12 of 12 stored curve rows with geometry were wrong; with modifiers also its own mesh's), location, modifier
types and whether it is animated, per light its type, power and the direction it emits along (local -Z), per camera its
lens and the direction it looks along, the parts that make one thing (an object with its children, objects named after
one word: their joined box), node groups and actions, capped (MEASURE_KEEP, MEASURE_BUDGET), and apart from those, after
the cap, the scene's camera (scene_camera: the one a render uses, None for none, with "f" for the factory's), so the
cap, which cuts cameras first, never takes it and the rows are what they were before it. The scene a judge sees (_scene)
gets those as sizes (with "base_size" where modifiers change one), locations, modifiers, animated, lights, cameras,
node_groups and actions, each noting how many it leaves out ("(N more not listed)"), and says so when the engine and the
world are still the factory's: the factory engine as one the listing can't tell was set, or as set by the piece when its
code assigns one. The geometry line (GEOM_EPILOGUE, on a line of its own after the measuring, so the measuring's line
stayed what it was): per object of a GEOMETRY type its exact world box from its evaluated mesh,
faces and vertices, curve and text settings, depsgraph instances, animation, parent, hide_render, display and material
slots, and the objects whose place at this frame comes from an animated parent or a constraint that moves them;
datagen/geometry.py reads it, and since Nov 5 the judge's listing does too: a location there is where the object's
geometry is (its box's centre and the middle of its bottom) beside its origin (_where).
It runs under pysandbox's watchdog (Chimera's), in a session of its own, so its Blender dies with this process even
by kill -9, and a --python-expr first prints a flushed line with the version: a run without it never got as far as
Blender's Python (the sandbox refused, Blender died starting), a tool problem that isn't cached. Blender's own header
can't tell that: it's lost whenever a script ends by os._exit or is killed.
In a joined run Chimera's own render line in _chimera_output is replaced by `pass` (same line count, so the line map
holds): the check would stop there, and the probes, which run at the end, would never see the finished scene. Its
path() helper's first line is replaced too, so a save or a render path is put in wm_out/ in the run folder: an
absolute path elsewhere is the sandbox's to refuse, not the piece's fault, and the settings are still applied.
A stand-in marker counts whatever hyphen it was written with (U+2010, U+2011, U+2012 and U+2212 read as "-",
marker_text): gpt-oss writes it with U+2011. runner/blender_run and runner/score, the eval's, still read only the
plain hyphen.

After the alone run passes, the measured checks (measured_check) hold the piece to what its step says in numbers: a size
triple ("2.4 m × 0.9 m × 0.92 m", or three sides given by name in a dependency that only defines values) that no object
or group of parts measures within 10% (size_mismatch), a light or camera said to point down (as far down as an angle it
gives) that points elsewhere (aim_mismatch), an output path in SETTINGS_sN when the step never speaks of saving,
rendering or exporting (output_not_asked), and the reverse: a save or render the step's own words ask for that
SETTINGS_sN["output"] never hands to Chimera (output_missing, read from the code: smoke2's X05, X20, X58 and the first
run's X43, all bad), and a camera the step adds that isn't the scene's after the run, so the factory camera renders or
none does (camera_not_active: X47), and step 6a's hidden errors (datagen/silent.py, from the direct run's silent
report): an error from Blender the piece's own except caught at one of its lines in every version (swallowed: X07, X20,
X58), or a node input looked up behind a guard by a name the node doesn't have, so the input it meant stayed at its
default (skipped_input: X06, D29), or (Nov 5) a hasattr or getattr on its way to the keys that found nothing, where the
step asks for linear keys and they stayed otherwise (attr_miss: X07, the fourth smoke's blender-0008-00 s4 c4; soft only
on a step a later one depends on, as ctx_channel); a joined run's are recorded only. And step 6b's geometry
(datagen/geometry.py, from the geometry line and the measuring, a fault only when every version shows it): a thing the
step puts at a point or the origin that no object of its name stands at, by its box's centre, bottom or own origin
(place_mismatch: X01, X27), and a depth it asks to extrude, solidify or bevel that every object it can be left with no
faces or under 1 mm (flat_extrusion: X39); on the joined run, a flat thing buried inside the solid one the step puts it
behind, in front of, beside or next to (nested: X06), recorded only this round (its reader failed the held-out check:
geometry.GATED). A size is asked of a step unless another step of the plan makes its thing (asked_sizes: a one-step
plan's sizes are all its own, a camera step's "frame the island (...)" asks nothing of it), and a size from a values
step is measured on the joined run, where its values are there, held to the values that step's piece really sets
(settings_sides), and not at all when they aren't its words. A size the measuring may have left out (it keeps
MEASURE_KEEP objects) is unmeasured, not wrong (size_states). An angle is read only when it is certain ("60 degrees from
vertical" is 30 below level); a clause with any other angle or a rotation in numbers asks nothing. They fail the piece
without a repair: Chimera repairs crashes only (task.py keeps a piece that failed only on output_missing,
camera_not_active, swallowed, skipped_input, place_mismatch, flat_extrusion or nested as a dependency with no example,
SOFT_REASONS). Every failed piece gets "tell": plain lines (tell_lines) for the next try's teacher, with the measured
numbers, naming the thing and where its size comes from rather than quoting the step; TELL_FORMS is this round's new
lines' fixed wording, ours, for hints.echoed_note.

A .001 copy is a name made twice (dupes, joined_dupes, the plan check's dupes), but for one: --factory-startup's own
camera is called "Camera", so a step that asks in quotes for a camera named "Camera" gets Camera.001, and that copy is
excused when it is the scene's camera and no later step asks for the name (factory_copies; smoke2's D15 comes back,
D12, whose factory camera still renders, stays dropped). A ctx key the contract doesn't have (ctx["variables"],
written or read: ctx_channel, the values-only first steps' way of handing values on before the contract gave them
ctx["values"]) fails the piece at the alone stage since DATAGEN_FORMAT 4 (reason ctx_channel, after the alone run's
own and measured checks, so the piece still gets its joined check: task.py keeps it as a dependency with no example
on a step a later one depends on, and drops it otherwise), and is told whatever else fails the piece (ctx_tell, read
from the code, so a try that crashes alone or fails the lint is told too). Since the fourth smoke the same holds for
what the build would drop the piece for (build_facts, read from the code and the verdict): Chimera's validator
warnings (validator_warning:<code>: provides_missing, uses_undeclared, handoff_long) and an output path under a
SETTINGS_sN key Chimera never reads (dead_output_key; told DEAD_TELL when the step asks Chimera for a render or a save,
DEAD_UNASKED when it asks for neither), and for the stand-in marker's two faults the build never read (marker_misused,
silent_default: datagen/stand_ins.py); handoff_long on a values-only step's provides line, the user's open contract
question, is left as it was, whatever the line's form (no reason, no tell, and nothing else fails such a piece:
waived; decided Nov 6). The build's filters stay as the backstop.

Where a piece crashed comes from the run that failed: alone, the check's line is the piece's own code line and the
function or part is read from the piece's code (as Go's partOf names it); joined, it is Go's locate with the join's
line map. Either way it is Go's workerCrash, so it goes straight back into --hydra-worker-request as "crash" for
Chimera's own repair message.

Every run is cached in cache/runs.jsonl under key_of("blender", script, versions, chimera.sha256(), RUN_FORMAT):
a second identical check runs no Blender, and a resumed run replays the verdicts. A run whose check couldn't be
done (no verdict, the wrong Blender, a direct run that never got to Blender's Python) isn't cached, so a resumed run
tries again. A semaphore keeps at most `jobs`
Blender processes running at once; within a run the four processes (two versions, two runs) go in parallel.
"""
from __future__ import annotations

import ast
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import symtable
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from contract import validate as V
from datagen import geometry, pysandbox, silent, stand_ins  # geometry imports this module back, after its TELL_FORMS
from datagen.hints import FAILURE_CHARS, unversioned, values_step
from datagen.chimera import ChimeraError
from datagen.common import key_of, now_iso
from runner import blender_run
from runner.score import provided_names
from tools import blender_check, blenders, rna_lint, scene_probe

RUN_FORMAT = 5  # bump when what a run measures changes (the epilogues below), so old cached runs aren't reused
# (4: the measuring records the scene's camera, for factory_copies and camera_not_active; 5: the names line lists
# ctx["values"] keys; step 6's silent prelude and report, the geometry line, and curve, text and surface sizes from
# the evaluated mesh). Still 5 after the fourth smoke: attr_miss, doubled_depth and the judge's labelled locations
# read what format-5 runs already print (the silent report, the geometry line), and build_facts reads the code.
NO_PROBE = "# data generation: the eval's probe never runs here\n"
NAMES_MARK = blender_run.WM_MARK + " dg-names "  # starts with the runner's own mark: the strict rule never reads it
MEASURE_MARK = blender_run.WM_MARK + " dg-measure "  # the same
GEOM_MARK = blender_run.WM_MARK + " dg-geom "  # the same: the geometry line (GEOM_EPILOGUE, datagen/geometry.py)
STARTED_MARK = blender_run.WM_MARK + " dg-started "  # the same: the direct run's Blender got to its Python
STARTED_EXPR = "import bpy\nprint(%r + '.'.join(map(str, bpy.app.version[:3])), flush=True)\n" % STARTED_MARK
SEAMS_FAIL = ("duplicate_name", "ctx_key_missing", "uses_unmatched", "join_syntax")
# The measured faults that leave a piece usable by the later steps (task.SOFT_REASONS has them): piece_check goes on
# to the joined step after them, so a piece task keeps only as a dependency has had its joined check. Step 6a's hidden
# errors (swallowed, skipped_input) and step 6b's geometry (place_mismatch, flat_extrusion, nested) are among them:
# Chimera's own check passes such a piece and its real flow hands it on, as with output_missing, and dropping one
# cascades (X07, a last resort, would have made s5 a failed-dependency request; X39 is the s1 that both ok Blender
# examples of the second run build on)
SOFT_MEASURED = ("output_missing", "camera_not_active", "swallowed", "skipped_input", "place_mismatch",
                 "flat_extrusion", "nested", "doubled_depth")
# build_facts' reasons (since the fourth smoke): what the build drops (Chimera's validator warnings, a dead output key)
# and the stand-in marker's two faults, by prefix (validator_warning:<code>)
FACT_REASONS = ("validator_warning", "dead_output_key", "marker_misused", "silent_default")
# The alone stage's reasons that go on to the joined step (_hard): SOFT_MEASURED, ctx_channel, attr_miss (a guard on
# the way to the keys that left them unlike the step's words, datagen/silent.missed_keys: Nov 5) and FACT_REASONS
# (since the fourth smoke, the same way), which task.py keeps
# as a dependency on a step a later one depends on (task.SOFT_IF_USED) and drops otherwise. The gate joins such a try
# either way and leaves softness to task.soft(reasons, used): a soft keep must join cleanly, and the extra joined run on
# a step with no dependents is seconds (3 such kept tries in the stored runs).
SOFT_GATE = SOFT_MEASURED + ("ctx_channel", "attr_miss") + FACT_REASONS
# A fault Chimera's own join shows for itself (after the fifth smoke, Nov 6): global_ctx, a function of the piece that
# reads a ctx it is never given. The alone run's tail (Chimera's aloneScript) binds ctx at module level before it calls
# build_sN, so there the read works; Chimera's join calls build_sN(ctx) inside its main(), where ctx is main's own, so
# it raises NameError in the person's script. Read from the code, a reason at the alone stage that still goes on to
# the joined run (_hard), which is Chimera's join: its NameError is the crash a repair is sent, as Chimera would send
# it (smoke4's n-blender-0000-01 r2 s2 c0 crashed so and its repair was kept). Not soft in task.py: such a piece
# breaks the joined script.
JOINED_SHOWS = ("global_ctx",)
RENDER_LINE = "bpy.ops.render.render(animation=video, write_still=not video)"  # chimeraOutputFn's last line (Go)
RENDER_SKIPPED = "pass  # data generation: Chimera's render is skipped, so the probes see the finished scene"
PATH_LINE = 'p = bpy.path.abspath(p) if p.startswith("//") else os.path.abspath(os.path.expanduser(p))'  # path()'s
PATH_KEPT = 'p = os.path.join(os.getcwd(), "wm_out", os.path.basename(p))  # data generation: in the run folder'
_STAND_IN_KEY = re.compile(r"chimera: stand-in[\s:]+(?:for\s+)?[\"']?([\w.-]+)")
# gpt-oss writes the marker's hyphen as U+2011 (and its kin): read as "-" wherever a run's output is searched for it.
# U+2013 isn't among them: it's the dash replies put after the marker ("stand-in – SVG not found").
_MARKER_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2212"), "-")
LINT_KEEP = 20  # findings kept in a record
IDS_KEEP = (3000, 500)  # chimera_ names and other names kept per run
VALUES_KEEP = 500  # ctx["values"] keys kept per run
# The factory scene of --factory-startup in 5.2.2 and 5.0.1 (measured): left out of the scene a judge sees.
FACTORY_OBJECTS = {("Camera", "CAMERA", "Camera"), ("Cube", "MESH", "Cube"), ("Light", "LIGHT", "Light")}
FACTORY_MATERIALS = {"Material", "Dots Stroke"}
FACTORY_COLLECTIONS = {"Collection"}
FACTORY_WORLD = "World"
FACTORY_ENGINE = "BLENDER_EEVEE"
# The factory engine as the judge reads it: the listing can't tell a piece that set it from one that left it, unless
# the piece's own code assigns an engine (a step that asks for EEVEE and gets it was told otherwise in the smoke).
ENGINE_UNCHANGED = FACTORY_ENGINE + " (the factory default: the listing can't tell whether the piece set it)"
ENGINE_SET = FACTORY_ENGINE + " (set by the piece)"
WORLD_UNCHANGED = FACTORY_WORLD + " (factory world; its settings may have been changed)"
# Where the factory objects stand, as the measuring reads them in both versions: one still there is the piece's
# own only when it was moved, resized or turned.
FACTORY_MEASURE = {"Cube": {"loc": [0.0, 0.0, 0.0], "size": [2.0, 2.0, 2.0]},
                   "Light": {"loc": [4.08, 1.01, 5.9], "dir": [-0.57, -0.22, -0.79], "light": "POINT", "power": 1000.0},
                   "Camera": {"loc": [7.36, -6.93, 4.96], "dir": [-0.65, 0.61, -0.45], "lens": 50.0}}
_FACTORY_KEYS = ("loc", "size", "dir", "light", "power", "lens", "cam", "mods")
GEOMETRY = ("MESH", "CURVE", "CURVES", "SURFACE", "META", "FONT", "VOLUME", "POINTCLOUD", "GREASEPENCIL", "GPENCIL")
# Rows the measuring prints per run (the cap on what a record holds) and its line's length; entries per field in the
# scene a judge sees.
MEASURE_KEEP = {"objects": 40, "lights": 12, "cameras": 6, "groups": 20, "node_groups": 30, "actions": 30}
MEASURE_BUDGET = 6000
# The geometry line's rows (objects of a GEOMETRY type), its length, the vertices a world box is read from one by one
# (more: the box of its local box's corners, "approx"), the instances counted, the moving objects named
GEOM_KEEP, GEOM_BUDGET, GEOM_VERTS, GEOM_INSTANCES, GEOM_MOVING = 60, 9000, 4_000_000, 200_000, 60
LISTING_KEEP = 30
SIZE_TOLERANCE = (0.10, 0.01)  # a side matches within 10% of the size asked, or 1 cm (the measure is rounded)
AIM_DOWN_Z = -0.5  # pointing down: the direction's z below this
_STEP_WORD = re.compile(r"\bs\d+\b")

NAMES_EPILOGUE = r'''

# ---- datagen names probe (worker-model/datagen/blender_gate.py): ctx keys and every datablock's name ----
def _dg_names(_g):
    import json
    out = {"v": 1}
    try:
        import bpy
        ctx = _g.get("ctx") if isinstance(_g.get("ctx"), dict) else None
        if ctx is None:
            for _k, _v in list(_g.items()):
                if isinstance(_v, dict) and "scene" in _v and isinstance(_v.get("objects"), dict):
                    ctx = _v
                    break
        if ctx is not None and isinstance(ctx.get("objects"), dict):
            live, dead = [], []
            for k, v in ctx["objects"].items():
                try:
                    getattr(v, "name", None)
                    live.append(str(k))
                except ReferenceError:  # its object was removed after it was registered
                    dead.append(str(k))
            out["ctx"] = {"live": sorted(live), "dead": sorted(dead)}
            if isinstance(ctx.get("values"), dict):
                out["ctx"]["values"] = sorted(str(k) for k in ctx["values"])
        ids = []
        # Not object data (meshes, lights, ...): a removed object's mesh stays until a purge, and would still count.
        for attr in ("objects", "materials", "collections", "node_groups", "images", "textures", "worlds", "actions",
                     "scenes", "particles", "texts", "fonts"):
            coll = getattr(bpy.data, attr, None)
            if coll is not None:
                ids.extend(i.name for i in coll)
        out["ids"] = ids
    except Exception as e:  # never break the script it's appended to
        out = {"v": 1, "failed": (type(e).__name__ + " " + str(e))[:300]}
    print("%s" + json.dumps(out, ensure_ascii=True), flush=True)


_dg_names(globals())
del _dg_names
''' % NAMES_MARK

MEASURE_EPILOGUE = r'''

# ---- datagen measuring (worker-model/datagen/blender_gate.py): sizes, places, lights, cameras, animation ----
def _dg_measure(_g, _keep=%(keep)r, _budget=%(budget)d, _geometry=%(geometry)r, _factory=%(factory)r):
    import json, os, re, sys
    out = {"v": 1}
    try:
        import bpy
        from mathutils import Vector
        ctx = _g.get("ctx") if isinstance(_g.get("ctx"), dict) else None
        scene = bpy.context.scene
        if ctx is not None and getattr(ctx.get("scene"), "bl_rna", None) is not None:
            scene = ctx["scene"]
        # The scene as a render would see it (modifiers, constraints, animation at the current frame), evaluated with
        # the script's handlers off and stdout and stderr shut meanwhile, so nothing of this reaches the run's verdict.
        held = {}
        for h in ("depsgraph_update_pre", "depsgraph_update_post", "frame_change_pre", "frame_change_post"):
            hs = getattr(bpy.app.handlers, h, None)
            if hs is not None:
                held[h] = list(hs)
                hs.clear()
        sys.stdout.flush()
        sys.stderr.flush()
        fds, null = [os.dup(1), os.dup(2)], os.open(os.devnull, os.O_WRONLY)
        shapes = {}
        try:
            os.dup2(null, 1)
            os.dup2(null, 2)
            bpy.context.scene.frame_set(bpy.context.scene.frame_current)  # animation too, at the frame a still shows
            dg = bpy.context.evaluated_depsgraph_get()
            dg.update()
            # A curve's, a text's and a surface's box from its evaluated mesh, whose bound_box isn't its shape's in
            # 5.2.2 and 5.0.1 (a bevelled bezier's is 4 x 2 x 2 for 2.035 x 0.322 x 0.1, a text's depth 0 for 0.1); the
            # bound_box when the mesh has no vertices or can't be made. A mesh's bound_box is right and stays.
            for o in scene.objects:
                if o.type not in ("CURVE", "FONT", "SURFACE"):
                    continue
                try:
                    ev = o.evaluated_get(dg)
                    me = ev.to_mesh()
                except Exception:
                    continue
                try:
                    if me is not None and len(me.vertices):
                        co = [0.0] * (3 * len(me.vertices))
                        me.vertices.foreach_get("co", co)
                        lo = [min(co[k::3]) for k in range(3)]
                        hi = [max(co[k::3]) for k in range(3)]
                        shapes[o.as_pointer()] = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1])
                                                  for z in (lo[2], hi[2])]
                except Exception:
                    pass
                try:
                    ev.to_mesh_clear()
                except Exception:
                    pass
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(fds[0], 1)
            os.dup2(fds[1], 2)
            for fd in fds + [null]:
                os.close(fd)
            for h, hs in held.items():
                getattr(bpy.app.handlers, h).extend(hs)
        r2 = lambda v: [round(float(x), 2) + 0.0 for x in v]
        cut = lambda s: s if len(s) <= 48 else s[:45] + "..."

        def stem(name):
            split = r"[\W_]+|(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
            words = [w.lower() for w in re.split(split, re.sub(r"\.\d{3}$", "", name)) if w]
            words = [w for w in words if w != "chimera" and not w.isdigit()]
            return words[0] if words else ""
        rows, boxes, kids = [], {}, {}
        for o in sorted(scene.objects, key=lambda o: (not o.name.startswith("chimera_"), o.name)):
            try:
                ev = o.evaluated_get(dg)
            except Exception:
                ev = o
            mw = ev.matrix_world
            e = {"n": cut(o.name), "t": o.type, "loc": r2(mw.translation)}
            if [o.name, o.type, o.data.name if o.data is not None else None] in _factory:
                e["f"] = 1
            if o.type in _geometry:
                cs = [Vector(c) for c in shapes.get(o.as_pointer(), ev.bound_box)]
                lo = [min(c[k] for c in cs) for k in range(3)]
                hi = [max(c[k] for c in cs) for k in range(3)]
                sc = mw.to_scale()
                e["size"] = r2(abs((hi[k] - lo[k]) * sc[k]) for k in range(3))
                w = [mw @ c for c in cs]
                boxes[o.name] = ([min(p[k] for p in w) for k in range(3)], [max(p[k] for p in w) for k in range(3)])
            if len(o.modifiers):
                e["mods"] = [m.type for m in o.modifiers][:8]
                if o.type == "MESH" and len(o.data.vertices):  # its own mesh too: a stand-in's modifier may empty it
                    co = [0.0] * (3 * len(o.data.vertices))
                    o.data.vertices.foreach_get("co", co)
                    base = r2(abs((max(co[k::3]) - min(co[k::3])) * sc[k]) for k in range(3))
                    if base != e["size"]:
                        e["base"] = base
            ads = [o.animation_data, getattr(o.data, "animation_data", None) if o.data is not None else None]
            if any(a is not None and (a.action is not None or len(a.drivers)) for a in ads):
                e["anim"] = 1
            if o.type in ("LIGHT", "CAMERA"):
                d = mw.to_3x3() @ Vector((0.0, 0.0, -1.0))
                e["dir"] = r2(d.normalized() if d.length else d)
                if o.type == "LIGHT":
                    e["light"] = o.data.type
                    if getattr(o.data, "energy", None) is not None:
                        e["power"] = round(float(o.data.energy), 1)
                else:
                    e["lens"] = round(float(o.data.lens), 1)
                    if o.data.type != "PERSP":
                        e["cam"] = o.data.type
            p = o.parent
            while p is not None:  # every ancestor holds it
                kids.setdefault(p.name, []).append(o.name)
                p = p.parent
            rows.append(e)
        # Parts that make one thing: an object with its children, and objects that share a name's first word
        groups, seen = [], set()
        stems = {}
        for n in boxes:
            stems.setdefault(stem(n), []).append(n)
        for kind, name, members in ([("under", k, [k] + v) for k, v in kids.items()] +
                                    [("named", s, v) for s, v in stems.items() if s]):
            members = [m for m in members if m in boxes]
            if len(members) < 2 or tuple(sorted(members)) in seen:
                continue
            seen.add(tuple(sorted(members)))
            lo = [min(boxes[m][0][k] for m in members) for k in range(3)]
            hi = [max(boxes[m][1][k] for m in members) for k in range(3)]
            groups.append({"g": kind, "n": cut(name), "of": len(members), "size": r2(hi[k] - lo[k] for k in range(3))})
        lights = [e for e in rows if e["t"] == "LIGHT"]
        cams = [e for e in rows if e["t"] == "CAMERA"]
        rest = [e for e in rows if e["t"] not in ("LIGHT", "CAMERA")]
        out["objects"] = rest[:_keep["objects"]] + lights[:_keep["lights"]] + cams[:_keep["cameras"]]
        out["groups"] = groups[:_keep["groups"]]
        out["node_groups"] = [[cut(g.name), g.bl_idname] for g in bpy.data.node_groups][:_keep["node_groups"]]
        acts = []
        for a in list(bpy.data.actions)[:_keep["actions"]]:
            kinds = sorted({s.target_id_type for s in getattr(a, "slots", [])})
            acts.append([cut(a.name), ",".join(kinds)] + r2(a.frame_range))
        out["actions"] = acts
        if abs(scene.unit_settings.scale_length - 1.0) > 1e-6:
            out["unit_scale"] = round(float(scene.unit_settings.scale_length), 4)
        total = {"objects": len(rows), "groups": len(groups), "node_groups": len(bpy.data.node_groups),
                 "actions": len(bpy.data.actions)}
        while len(json.dumps(out, separators=(",", ":"))) > _budget:
            name = max(("objects", "groups", "node_groups", "actions"), key=lambda k: len(json.dumps(out[k])))
            if not out[name]:
                break
            out[name].pop()
        cutn = {k: total[k] - len(out[k]) for k in total if total[k] > len(out[k])}
        if cutn:
            out["cut"] = cutn
        # The camera a render uses (Chimera's _chimera_output renders bpy.context.scene), kept apart from the rows
        # and after the budget's cut, so the rows a judge's listing shows are what they were and the cut (cameras
        # go first) never takes it
        cam = bpy.context.scene.camera
        sc = None
        if cam is not None:
            try:
                ev = cam.evaluated_get(dg)
            except Exception:
                ev = cam
            mw = ev.matrix_world
            d = mw.to_3x3() @ Vector((0.0, 0.0, -1.0))
            sc = {"n": cut(cam.name), "t": cam.type, "loc": r2(mw.translation),
                  "dir": r2(d.normalized() if d.length else d),
                  "f": 1 if [cam.name, cam.type, cam.data.name if cam.data is not None else None] in _factory else 0}
            if cam.type == "CAMERA":
                sc["lens"] = round(float(cam.data.lens), 1)
                if cam.data.type != "PERSP":
                    sc["cam"] = cam.data.type
        out["scene_camera"] = sc
    except Exception as e:  # never break the script it's appended to
        out = {"v": 1, "failed": (type(e).__name__ + " " + str(e))[:300]}
    print("%(mark)s" + json.dumps(out, separators=(",", ":"), ensure_ascii=True), flush=True)


_dg_measure(globals())
del _dg_measure
''' % {"keep": MEASURE_KEEP, "budget": MEASURE_BUDGET, "geometry": GEOMETRY, "mark": MEASURE_MARK,
       "factory": sorted([list(f) for f in FACTORY_OBJECTS])}

# The geometry line (step 6b, datagen/geometry.py reads it), after the measuring and on a line of its own, so the
# measuring's line is what it was (the listing a judge sees reads its boxes since Nov 5: _where). Per object of a
# GEOMETRY type, from
# its evaluated mesh: the exact world box (every vertex through its world matrix, with numpy, which Blender ships; the
# box of its local box's corners, "approx", without numpy or past GEOM_VERTS), its vertices and faces, and for a curve
# or a text its extrude, bevel depth, dimensions, fill mode, bevel object and splines; a type with no mesh its
# evaluated bound box ("bb"). Per object too: its depsgraph instances ("inst"), whether it is animated, its parent,
# hide_render, a wire or bounds display and its material slots with a material. "moving": every object (any type)
# whose place at this frame comes from animation it doesn't own or from a constraint that moves it (an animated
# ancestor; any constraint but the aiming ones, on it or an ancestor), so a place asked of it is never judged.
# A curve's, a text's or a surface's own evaluated mesh, which the depsgraph lists as an instance of itself (5.2.2 and
# 5.0.1), isn't counted among its instances. Evaluated with the script's handlers held off and stdout and stderr
# shut, as the measuring is. Measured on the 191 stored alone scripts: printed in every run, at most 1,050 characters.
GEOM_EPILOGUE = r'''

# ---- datagen geometry (worker-model/datagen/blender_gate.py): world boxes, faces, curve settings ----
def _dg_geom(_g, _geometry=%(geometry)r, _keep=%(keep)d, _budget=%(budget)d, _verts=%(verts)d, _inst=%(inst)d,
             _moving=%(moving)d):
    import json, os, sys
    out = {"v": 1}
    try:
        import bpy
        from mathutils import Vector
        try:
            import numpy as np
        except Exception:
            np = None
        ctx = _g.get("ctx") if isinstance(_g.get("ctx"), dict) else None
        scene = bpy.context.scene
        if ctx is not None and getattr(ctx.get("scene"), "bl_rna", None) is not None:
            scene = ctx["scene"]
        aims = {"TRACK_TO", "DAMPED_TRACK", "LOCKED_TRACK", "COPY_ROTATION", "LIMIT_ROTATION", "LIMIT_SCALE",
                "COPY_SCALE", "MAINTAIN_VOLUME"}
        r3 = lambda v: [round(float(x), 3) + 0.0 for x in v]

        def animated(o):
            ads = [o.animation_data, getattr(o.data, "animation_data", None) if o.data is not None else None]
            return any(a is not None and (a.action is not None or len(a.drivers)) for a in ads)

        def moves(o):
            return any(c.type not in aims for c in o.constraints)
        held = {}
        for h in ("depsgraph_update_pre", "depsgraph_update_post", "frame_change_pre", "frame_change_post"):
            hs = getattr(bpy.app.handlers, h, None)
            if hs is not None:
                held[h] = list(hs)
                hs.clear()
        sys.stdout.flush()
        sys.stderr.flush()
        fds, null = [os.dup(1), os.dup(2)], os.open(os.devnull, os.O_WRONLY)
        rows, moving = [], []
        try:
            os.dup2(null, 1)
            os.dup2(null, 2)
            dg = bpy.context.evaluated_depsgraph_get()
            inst = {}
            try:
                for k, d in enumerate(dg.object_instances):
                    if k >= _inst:
                        out["inst_cut"] = 1
                        break
                    if not d.is_instance or d.parent is None:
                        continue
                    # a curve's, a text's or a surface's own mesh is listed as an instance of itself (5.2.2 and
                    # 5.0.1): not counted
                    top, ob = d.parent.original, d.object
                    if ob.original == top and top.data is not None and \
                            getattr(ob.data, "name", None) == top.data.name:
                        continue
                    inst[top.name] = inst.get(top.name, 0) + 1
            except Exception:
                pass
            for o in sorted(scene.objects, key=lambda o: (not o.name.startswith("chimera_"), o.name)):
                p, up = o.parent, moves(o)
                while p is not None and not up:
                    up = animated(p) or moves(p)
                    p = p.parent
                if up:
                    moving.append(o.name[:60])
                if o.type not in _geometry:
                    continue
                try:
                    ev = o.evaluated_get(dg)
                except Exception:
                    ev = o
                mw = ev.matrix_world
                e = {"n": o.name[:60], "t": o.type, "loc": r3(mw.translation)}
                me = None
                try:
                    if o.type in ("MESH", "CURVE", "FONT", "SURFACE", "META"):
                        me = ev.to_mesh()
                except Exception:
                    me = None
                if me is not None:
                    try:
                        n = len(me.vertices)
                        e["verts"], e["faces"] = n, len(me.polygons)
                        if n and np is not None and n <= _verts:
                            co = np.empty(3 * n, dtype=np.float32)
                            me.vertices.foreach_get("co", co)
                            M = np.array(mw, dtype=np.float64)
                            w = co.reshape(-1, 3).astype(np.float64) @ M[:3, :3].T + M[:3, 3]
                            e["lo"], e["hi"] = r3(w.min(axis=0)), r3(w.max(axis=0))
                        elif n:
                            co = [0.0] * (3 * n)
                            me.vertices.foreach_get("co", co)
                            lo = [min(co[k::3]) for k in range(3)]
                            hi = [max(co[k::3]) for k in range(3)]
                            w = [mw @ Vector((x, y, z)) for x in (lo[0], hi[0]) for y in (lo[1], hi[1])
                                 for z in (lo[2], hi[2])]
                            e["lo"] = r3(min(p[k] for p in w) for k in range(3))
                            e["hi"] = r3(max(p[k] for p in w) for k in range(3))
                            e["approx"] = 1
                    except Exception:
                        pass
                    try:
                        ev.to_mesh_clear()
                    except Exception:
                        pass
                if "lo" not in e:
                    w = [mw @ Vector(c) for c in ev.bound_box]
                    e["lo"] = r3(min(p[k] for p in w) for k in range(3))
                    e["hi"] = r3(max(p[k] for p in w) for k in range(3))
                    e["bb"] = 1
                if inst.get(o.name):
                    e["inst"] = inst[o.name]
                if o.type in ("CURVE", "FONT"):
                    c = o.data
                    e["curve"] = {"extrude": round(float(c.extrude), 4), "bevel": round(float(c.bevel_depth), 4),
                                  "dim": c.dimensions, "fill": getattr(c, "fill_mode", None),
                                  "bevel_obj": c.bevel_object is not None,
                                  "splines": len(getattr(c, "splines", None) or [])}
                if animated(o):
                    e["anim"] = 1
                if o.parent is not None:
                    e["parent"] = o.parent.name[:60]
                if o.hide_render:
                    e["hide_render"] = 1
                if o.display_type in ("WIRE", "BOUNDS"):
                    e["display"] = o.display_type
                e["mats"] = len([s for s in o.material_slots if s.material is not None])
                rows.append(e)
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(fds[0], 1)
            os.dup2(fds[1], 2)
            for fd in fds + [null]:
                os.close(fd)
            for h, hs in held.items():
                getattr(bpy.app.handlers, h).extend(hs)
        out["objects"] = rows[:_keep]
        if moving:
            out["moving"] = moving[:_moving]
            if len(moving) > _moving:
                out["moving_cut"] = len(moving) - _moving
        while len(json.dumps(out, separators=(",", ":"))) > _budget and out["objects"]:
            out["objects"].pop()
        if len(rows) > len(out["objects"]):
            out["cut"] = len(rows) - len(out["objects"])
    except Exception as e:  # never break the script it's appended to
        out = {"v": 1, "failed": (type(e).__name__ + " " + str(e))[:300]}
    print("%(mark)s" + json.dumps(out, separators=(",", ":"), ensure_ascii=True), flush=True)


_dg_geom(globals())
del _dg_geom
''' % {"geometry": GEOMETRY, "keep": GEOM_KEEP, "budget": GEOM_BUDGET, "verts": GEOM_VERTS, "inst": GEOM_INSTANCES,
       "moving": GEOM_MOVING, "mark": GEOM_MARK}


# ---------------------------------------------------------------- small readers

def dep_indexes(plan, i):
    """depIndexes (app/hydra_contract.go): the earlier steps step i depends on, in its depends_on order, once each;
    an id that appears twice means its first step."""
    first = {}
    for j in range(len(plan["steps"]) - 1, -1, -1):
        first[plan["steps"][j]["id"]] = j
    out = []
    for d in plan["steps"][i].get("depends_on") or []:
        j = first.get(d)
        if j is not None and j < i and j not in out:
            out.append(j)
    return out


def step_index(plan, key):
    """The index of the step a key names: its cleaned plan id, else its worker name ("s3"), else None."""
    ids = [s["id"] for s in plan["steps"]]
    if key in ids:
        return ids.index(key)
    m = re.fullmatch(r"s(\d+)", str(key))
    if m and 1 <= int(m.group(1)) <= len(ids):
        return int(m.group(1)) - 1
    return None


def by_id(plan, pieces):
    """{plan id: text} from a dict keyed by plan ids or worker names; unknown keys and empty texts are dropped."""
    out = {}
    for k, text in (pieces or {}).items():
        j = step_index(plan, k)
        if j is not None and text:
            out[plan["steps"][j]["id"]] = text
    return out


def _assigned(n):
    """assignedNames (app/hydra_piece.go): the plain names an assignment binds, [] if a target isn't one."""
    targets = [n.target] if isinstance(n, ast.AnnAssign) else n.targets
    out = []
    for t in targets:
        for x in (t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t]):
            if not isinstance(x, ast.Name):
                return []
            out.append(x.id)
    return out


def part_of(code, line, sid):
    """(part, function) of line in a Blender piece's code, as Go's partOf names the line map's parts: "import", or
    "settings" (SETTINGS_sN), "build" (build_sN) or "helper" with the def's, class's or first assigned name.
    ("", "") when no top-level statement holds the line or the code doesn't parse."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return "", ""
    for n in tree.body:
        start = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])])
        if not start <= line <= (n.end_lineno or n.lineno):
            continue
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            return "import", ""
        name = ""
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = n.name
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            names = _assigned(n)
            if len(names) == 1 and names[0] == "SETTINGS_" + sid:
                return "settings", names[0]
            name = names[0] if names else ""
        return ("build" if name == "build_" + sid else "helper"), name
    return "", ""


def skip_render(script, linemap):
    """The joined script with Chimera's own render line (in _chimera_output, part "output" of the line map)
    replaced by pass, and its path() helper's path put in wm_out/ in the run folder, each at the same indent, keeping
    the line count; the script as it is when there is no output part."""
    lines = script.split("\n")
    origins = (linemap or {}).get("origins") or []
    for k, line in enumerate(lines):
        o = origins[k] if k < len(origins) else None
        if o and o[1] == "output" and line.strip() in (RENDER_LINE, PATH_LINE):
            new = RENDER_SKIPPED if line.strip() == RENDER_LINE else PATH_KEPT
            lines[k] = line[:len(line) - len(line.lstrip())] + new
    return "\n".join(lines)


def marker_text(output):
    """A run's output with the stand-in marker's hyphen read as "-" whatever dash a reply wrote it with (U+2010,
    U+2011, U+2012, U+2212): what the stand-in checks search."""
    return (output or "").translate(_MARKER_DASHES)


def has_stand_in(output):
    """Whether a run printed the stand-in marker (blender_run.STAND_IN), with any of those hyphens."""
    return blender_run.STAND_IN in marker_text(output)


def stand_in_keys(output):
    """The keys a run's `print("chimera: stand-in", key)` lines name (with any of marker_text's hyphens), in order,
    once each."""
    out = []
    for k in _STAND_IN_KEY.findall(marker_text(output)):
        if k not in out:
            out.append(k)
    return out


def _named(plan, pieces):
    """{worker name: the names its handoff provides, its dependencies' left out} for the join's Blender pieces with
    a handoff, in plan order: what each present step is answerable for (what the plan check holds it to)."""
    by = {p.get("sid"): p for p in pieces or []}
    out = {}
    for k in range(len(plan["steps"])):
        p = by.get("s%d" % (k + 1))
        if not p or p.get("mode") != "blender" or not p.get("handoff"):
            continue
        theirs = set()
        for d in dep_indexes(plan, k):
            dp = by.get("s%d" % (d + 1))
            if dp and dp.get("handoff"):
                theirs.update(provided_names(dp["handoff"].get("provides")))
        out["s%d" % (k + 1)] = [n for n in provided_names(p["handoff"].get("provides")) if n not in theirs]
    return out


def _have(rec):
    """What one version's direct run has for a handoff to name: live ctx["objects"] keys, ctx["values"] keys and
    datablock names; None when its probes didn't run (the script stopped first). runner.score.provided_names leaves
    the channel's own name out of 'ctx["values"]["sofa_width"]' (it gives "sofa_width"), so a values step that hands
    on what its provides lists passes provides_missing, and the step after it doesn't fail removes_earlier."""
    if rec.get("ids") is None and rec.get("names") is None:
        return None
    have = set(rec.get("ids") or rec.get("names") or [])
    keys = rec.get("ctx_live")
    have |= set(keys if keys is not None else rec.get("ctx_keys") or [])
    have |= set(rec.get("ctx_values") or [])
    return have


def _scene(rec, code=None):
    """What the alone run built, factory scene left out: objects (name, type), materials, collections, world,
    engine, ctx keys, the ctx["values"] keys it handed on ("ctx_values", keys only, only when there are some, so a
    listing without them reads as it did before Nov 4), and from the measuring (when it ran, each only when it has
    something): sizes and locations (metres, world space; with modifiers that change it, also the size without them,
    "base_size"; a location is the object's origin and, from the geometry line, where its geometry is: _where),
    modifiers (types), animated (objects with an action or drivers), lights (type, power, the
    direction it emits along), cameras (lens, the direction it looks along), node groups (type) and actions (what
    they animate, frames). The factory engine is said to be the factory's (ENGINE_UNCHANGED), or set by the piece
    when its code (the piece's own, code) assigns an engine (ENGINE_SET); the factory world is said to be the
    factory's. None when the probe didn't run."""
    s = rec.get("scene")
    if not s:
        return None
    objects = [[o["name"], o["type"]] for o in s.get("objects") or []
               if (o["name"], o["type"], o.get("data")) not in FACTORY_OBJECTS]
    world, engine = s.get("world"), s.get("engine")
    if engine == FACTORY_ENGINE:
        engine = ENGINE_SET if sets_engine(code) else ENGINE_UNCHANGED
    out = {"objects": objects,
           "materials": [m for m in s.get("materials") or [] if m not in FACTORY_MATERIALS],
           "collections": [c for c in s.get("collections") or [] if c not in FACTORY_COLLECTIONS],
           "ctx_keys": rec.get("ctx_live") if rec.get("ctx_live") is not None else rec.get("ctx_keys") or [],
           "world": WORLD_UNCHANGED if world == FACTORY_WORLD else world if world is not None else "none",
           "engine": engine}
    if rec.get("ctx_values"):
        out["ctx_values"] = list(rec["ctx_values"])
    out.update(_listed(rec.get("measure"), rec.get("geom")))
    return out


def sets_engine(code):
    """Whether a piece's code assigns a render engine: `….engine = …` (scene.render.engine, r.engine after
    r = scene.render, SETTINGS-driven or not) or setattr(…, "engine", …). A plain text search for ".engine =" when the
    code doesn't parse; False for no code."""
    if not code:
        return False
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return re.search(r"\.engine\s*=(?!=)", code) is not None
    for n in ast.walk(tree):
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(
            n, (ast.AnnAssign, ast.AugAssign)) else []
        for t in targets:
            for x in (t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t]):
                if isinstance(x, ast.Attribute) and x.attr == "engine":
                    return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "setattr" and len(n.args) >= 2 \
                and isinstance(n.args[1], ast.Constant) and n.args[1].value == "engine":
            return True
    return False


LISTING_MORE = "(%d more not listed)"  # the note on a field the listing caps or the measuring cut
_PER_OBJECT = ("sizes", "locations", "modifiers", "animated", "lights", "cameras")
# A location's labels in the judge's listing (_where; judges.SCENE_SYSTEM says what each is)
WHERE_CENTRE, WHERE_BOTTOM, WHERE_ORIGIN = "geometry_centre", "geometry_bottom", "origin"


def _boxes(geom):
    """{name: (lo, hi)}: the world boxes of the geometry line (GEOM_EPILOGUE, the one datagen/geometry.py reads),
    by object name (cut there to 60 characters); {} without one, or when it failed."""
    return {r["n"]: (r["lo"], r["hi"]) for r in (geom or {}).get("objects") or []
            if isinstance(r, dict) and isinstance(r.get("n"), str) and r.get("lo") and r.get("hi")}


def _box_of(name, boxes):
    """The geometry line's box for a measuring row's name (cut to 48 characters there, "..." after 45: the one box
    whose name starts so), or None."""
    if name in boxes:
        return boxes[name]
    if name.endswith("...") and len(name) == 48:
        hits = [b for n, b in boxes.items() if n.startswith(name[:-3])]
        return hits[0] if len(hits) == 1 else None
    return None


def _where(row, boxes):
    """One object's location as a judge reads it: {"geometry_centre", "geometry_bottom"} (the centre of its
    geometry's world box and the middle of that box's bottom, from the geometry line, for an object it boxes) and
    "origin" (the object's own origin, the measuring's). An origin says nothing of where the geometry is once a
    transform is applied: smoke4's n-blender-0000-00 r1 s2 applied its cubes' transforms, so every origin was
    (0, 0, 0) while each box sat where the step puts it, and the scene judge failed it for "all placed at the origin";
    so did smoke2's same step, whose objects took their applied meshes over. A run without the geometry line (a
    record from before RUN_FORMAT 5) gives the origin alone."""
    box = _box_of(row["n"], boxes)
    out = {}
    if box is not None:
        lo, hi = box
        centre = [round((float(lo[k]) + float(hi[k])) / 2, 2) + 0.0 for k in range(3)]
        out[WHERE_CENTRE] = centre
        out[WHERE_BOTTOM] = centre[:2] + [round(float(lo[2]), 2) + 0.0]
    out[WHERE_ORIGIN] = row["loc"]
    return out


def _listed(m, geom=None):
    """The measuring's part of a judge's scene: the fields _scene names, factory objects left out, each only when it
    has something and at most LISTING_KEEP entries. A field with more than that, or that the measuring itself cut
    (its "cut": a field's own count for node groups and actions; for the per-object fields, the objects it left out,
    any of which may have been one, so the count is at most), ends with LISTING_MORE: a list's last item, a dict's
    "..." key. A size that modifiers change is {"size", "base_size"}: the stand-in for a dependency's node group can
    leave an object with nothing to show (0 × 0 × 0) though its own mesh has the size its step gives. A location
    is labelled (_where): where the object's geometry is, from the geometry line (geom), and its origin."""
    if not m:
        return {}
    rows = [r for r in m.get("objects") or [] if not r.get("f")]
    boxes = _boxes(geom)
    fields = {
        "sizes": {r["n"]: {"size": r["size"], "base_size": r["base"]} if r.get("base") else r["size"]
                  for r in rows if "size" in r},
        "locations": {r["n"]: _where(r, boxes) for r in rows},
        "modifiers": {r["n"]: r["mods"] for r in rows if r.get("mods")},
        "animated": [r["n"] for r in rows if r.get("anim")],
        "lights": {r["n"]: dict({"type": r.get("light"), "power": r.get("power")},
                                **({"emits_along": r.get("dir")} if r.get("light") in AIMED else {}))
                   for r in rows if r["t"] == "LIGHT"},
        "cameras": {r["n"]: dict({"lens": r.get("lens"), "looks_along": r.get("dir")},
                                 **({"type": r["cam"]} if r.get("cam") else {}))
                    for r in rows if r["t"] == "CAMERA"},
        "node_groups": {g[0]: g[1] for g in m.get("node_groups") or []},
        "actions": {a[0]: "%s, frames %s-%s" % (a[1] or "no slot", _num(a[2]), _num(a[3]))
                    for a in m.get("actions") or [] if len(a) >= 4}}
    cut = m.get("cut") or {}
    out = {}
    for k, v in fields.items():
        more = max(0, len(v) - LISTING_KEEP) + int(cut.get("objects" if k in _PER_OBJECT else k) or 0)
        if not v and (k in _PER_OBJECT or not more):
            continue
        if isinstance(v, dict):
            out[k] = dict(list(v.items())[:LISTING_KEEP], **({"...": LISTING_MORE % more} if more else {}))
        else:
            out[k] = v[:LISTING_KEEP] + ([LISTING_MORE % more] if more else [])
    return out


# ---------------------------------------------------------------- what the run measured, against the step

# A size triple as a step writes it: "2.4 m × 0.9 m × 0.92 m", "2.4 x 0.9 x 0.92 m", "2.4 by 0.9 by 0.92 metres";
# a side may be a variable the step names instead of a number ("sofa_dim (length) × 0.9 m (width) × 0.8 m").
_NUM = r"\d+(?:\.\d+)?"
_UNIT = r"(?:mm|cm|m|millimet(?:er|re)s?|centimet(?:er|re)s?|met(?:er|re)s?)(?![A-Za-z])"
_SIDE = (r"(?:(%s)\s*(%s)?|`([A-Za-z_]\w*)`|([A-Za-z]\w*_\w*))(?:\s*\(\s*[A-Za-z][A-Za-z ]{0,20}\))?" % (_NUM, _UNIT))
_BY = r"\s*(?:\u00d7|\u2715|\*|\bx\b|\bX\b|\bby\b)\s*"  # ×, ✕, *, x, by
_TRIPLE = re.compile(r"(?<![\w.`])%s%s%s%s%s(?:\s*(%s))?" % (_SIDE, _BY, _SIDE, _BY, _SIDE, _UNIT))
# Sizes a step gives by name, three sides of one thing: sofa_length=2.2, sofa_width=0.9, sofa_height=0.8
_NAMED_SIDE = re.compile(r"\b([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*?)_(length|width|depth|height|"
                         r"(?:size|dim|dims|dimension|dimensions)_[xyz])\s*[=:]\s*(%s)\s*(%s)?" % (_NUM, _UNIT))
_VARIABLES_STEP = re.compile(r"^\W*(?:define|declare|set|list|specify|store|collect)\b[^\n]{0,80}?\b(?:variables?|"
                             r"dimensions?|parameters?|constants?|measurements?|sizes?|settings|values)\b", re.I)
# A light or camera the step says points down
_CLAUSE = re.compile(r"(?<!\d)[.;!?](?!\d)|\n")
_SUBJECT = re.compile(r"\b(?:(?P<kind>area|spot|sun|point)[\s-]*)?(?:lights?|lamps?)\b|\b(?P<spot>spot)lights?\b|"
                      r"\b(?P<sun>sun)(?:light)?s?\b|\b(?P<cam>cam(?:era)?s?)\b", re.I)
# "down" ends the phrase, unless it runs on to a place or a target ("down the corridor", "down at the sofa"): then
# the direction comes from that, not from "down". The floor and the ground are down.
_DOWN_END = (r"down(?:wards?)?\b(?!\s+(?:(?:at|on|onto|to|toward|towards)\s+)?(?:the|a|an|this|that|its|their|it|them)"
             r"\b(?!\s+(?:floor|ground)\b))")
_DOWN = [re.compile(p, re.I) for p in (
    r"\b(?:point|aim|fac|direct|shin|orient|angl|tilt)\w*\s+(?:[\w\"'°º-]+\s+){0,3}?(?:straight\s+|directly\s+)?"
    + _DOWN_END,
    r"\bdown(?:wards?)?[\s-]+(?:point|aim|fac|shin|direct)\w*",
    r"\b(?:point|aim|fac|direct|shin)\w*\s+(?:[\w\"'-]+\s+){0,3}?(?:(?:at|to|toward|towards|onto)\s+)?the\s+"
    r"(?:floor|ground)\b",
    r"\b(?:straight|directly)\s+" + _DOWN_END,
    r"\btop[\s-]?down\b")]
# An angle the step gives with "down" ("tilted down 15 degrees", "angled 20° down", "down at 30 degrees", "down by
# 0.3 rad", "a 20-degree"): how far below level, so the direction needed comes from it (aim_faults), not from "down".
# Never after "to": "down to 70 degrees" is a rotation to set, not a tilt.
_ANGLE = r"(\d+(?:\.\d+)?)\s*[-\u2010\u2011]?\s*(°|º|degrees?\b|degs?\b|rad(?:ians?)?\b)"
_ANGLE_IN = re.compile(_ANGLE, re.I)
_ANGLE_AFTER = re.compile(r"\s*(?:by\s+|at\s+)?(?:an?\s+angle\s+of\s+|about\s+|around\s+|roughly\s+|"
                          r"approximately\s+|some\s+)?" + _ANGLE, re.I)
# What an angle is measured from, said right after it: vertical, straight down, the zenith or the nadir (the tilt
# below level is 90 - N: "angled down 60 degrees from vertical" is 30 below level), or level (N)
_FROM_VERTICAL = re.compile(r"\s*(?:from|off)\s+(?:the\s+)?(?:vertical|straight\s+down|zenith|nadir|plumb)\b", re.I)
_FROM_LEVEL = re.compile(r"\s*(?:below|under|beneath|from|off)\s+(?:the\s+)?(?:horizontal|horizon|level)\b", re.I)
# An angle that isn't a tilt: a spot's cone or beam, a sun's disc, a camera's field of view ("a 45° cone", "spot
# size 45 degrees", "a field of view of 60°")
_NOT_TILT_AFTER = re.compile(r"\s*(?:wide\s+)?(?:cone|beam|spread|spot[\s_]*size|field\s+of\s+view|fov|"
                             r"angle\s+of\s+view|view\s+angle|blend|disc|disk)\b", re.I)
_NOT_TILT_BEFORE = re.compile(r"\b(?:cone|beam|spread|spot[\s_]*size|spot\s+angle|field\s+of\s+view|fov|"
                              r"angle\s+of\s+view|view\s+angle|blend|disc|disk|angular\s+(?:size|diameter))"
                              r"(?:\s+angle)?\s*(?:of|at|to|=|:|is|set\s+to)?\s*(?:an?\s+)?"
                              r"(?:about\s+|around\s+|roughly\s+|approximately\s+)?$", re.I)
# A unit of angle anywhere in a clause (every one must belong to an angle read), and a rotation given in numbers:
# either says the direction some other way than "down", so the clause says nothing certain
_ANGLE_UNIT = re.compile(r"°|º|\bdeg(?:ree)?s?\b|\brad(?:ian)?s?\b", re.I)
_ROTATION = re.compile(r"\b(?:rotat\w*|euler|orientation)\b[^.;\n]{0,40}?\d", re.I)
_OVERHEAD = re.compile(r"\b(?P<word>ceiling|overhead)(?:[\s-]+(?:mounted|area|spot|soft|key|main|panel|strip))*"
                       r"[\s-]+(?:lights?|lamps?)\b", re.I)
_HEDGED = re.compile(r"\bslight(?:ly)?\b|\ba (?:bit|little)\b|\bgentl\w*|\bpartly\b", re.I)
_LIGHT_TYPES = {"area": "AREA", "spot": "SPOT", "sun": "SUN", "point": "POINT"}
AIMED = ("SUN", "SPOT", "AREA")  # a point light shines every way
# What a step says that allows a piece to set an output: saving, rendering, exporting, an output or a file to write
_ASKS_OUTPUT = re.compile(r"\b(?:sav(?:e|es|ed|ing)|render(?:s|ed|ing)?|export(?:s|ed|ing)?|outputs?|filepaths?|"
                          r"file\s*paths?|write\s+(?:it\s+|them\s+)?(?:out|to)|blend\s*file)\b|"
                          r"\.(?:blend|png|jpe?g|exr|tiff?|bmp|webp|mp4|mkv|mov|avi|glb|gltf|fbx|obj|stl|usdz?|abc)\b",
                          re.I)
# SETTINGS_sN["output"] keys that set something other than where a file goes (_chimera_output's own names)
_NOT_PATH_KEYS = {"resolution", "resolution_x", "resolution_y", "resolution_percentage", "width", "height",
                  "render_width", "render_height", "fps", "frame_start", "frame_end", "engine", "render_engine",
                  "samples", "render_samples", "file_format", "format", "color_mode", "color_depth", "codec",
                  "container", "quality", "compression", "device", "use_denoising", "denoise"}
_PATH_KEYS = re.compile(r"render|blend|file|path|save|output|dir|folder|export|image|video|movie|still", re.I)
# What a step's own words ask Chimera to make (output_missing): a saved .blend and a render. Strict on purpose, the
# reverse of _ASKS_OUTPUT (which only has to allow an output): a save counts only when the words after its verb name a
# .blend before any other file, script or image ("Save the script as x.py", "Save each baked map next to the .blend"
# don't), a render only as a verb with what it makes ("render the animation", "Render 4K PNG Image", "render ... to
# //x.png"), the Render menu, render.render() or F12, and neither after a negation in its sentence ("no need to call
# bpy.ops.wm.save_mainfile", "do not render yet") nor in a sentence that makes it optional ("saves the blend again
# (optional) as ..."). A nameless "Save the file." asks nothing: there is no path to hand over.
_ASK_SENT = re.compile(r"\n+|(?<=[.!?])\s+(?=[A-Z0-9`\"'(*-])")
_ASK_NEG = re.compile(r"\b(?:don'?t|do not|does not|doesn'?t|no need to|never|not|without|instead of|rather than|"
                      r"avoid|skip|no)\b(?:\W+\w+){0,4}?\W+$", re.I)
# "Optional: render ...", "... if you like", "If needed, render ..." too (the integration check's forms; none is in
# the corpus of 301 steps, whose asks they leave as they were)
_ASK_OPTIONAL = re.compile(r"\(\s*optional\s*\)|\boptional(?:ly)?\s*:|\boptionally\b|\bif desired\b|"
                           r"\bif (?:you (?:like|want|wish|prefer)|needed|necessary|wanted)\b", re.I)
# A save or render this step only prepares, or leaves to another: a modal or purpose before the verb ("so the camera
# renders", "so that s6 can render", "will have saved", "ready to save"), another step as its doer ("s5 will
# render"), or a later step after it ("render the scene quickly in later steps", "save as final.blend in s6")
_ASK_DEFER_BEFORE = re.compile(r"(?:\b(?:so|can|could|will|would|may|might|ready to|able to|lets?|allows?|"
                               r"in order for)\b|\bs\d+\b)(?:\W+\w+){0,3}?\W+$", re.I)
_ASK_DEFER_AFTER = re.compile(r"\blater\b|\b(?:in|by|for) (?:a |the )?(?:later|next|following|final|another|"
                              r"subsequent) steps?\b|\b(?:in|by) s\d+\b", re.I)
_ASK_SAVE = re.compile(r"\b(?:save|saves|saving|saved|save_as_mainfile|save_mainfile)\b|File\s*>\s*Save", re.I)
_ASK_OBJ_WORDS = 14
_ASK_BLEND = re.compile(r"\.blend\b|\bblend(?:er)?[\s-]+(?:files?|project|scene)\b", re.I)
_ASK_OTHER = re.compile(r"\.(?:py|json|txt|csv|md|glb|gltf|fbx|obj|stl|usdz?|abc|svg|png|jpe?g|exr|tiff?|bmp|webp|"
                        r"mp4|mkv|mov|avi|gif|hdr|wav|mp3)\b|\b(?:script|scripts|code|image|images|render|renders|"
                        r"pictures?|maps?|textures?|frames?|video|movie|animation|stills?|png|jpe?g|exr|csv|json|"
                        r"report|log|manifest|readme|zip|archive|screenshot|preview|thumbnail|bake|baked)\b", re.I)
_ASK_RENDER_MENU = re.compile(r"Render\s*>\s*Render|render\.render\s*\(|\b(?:Ctrl\s*\+\s*)?F12\b", re.I)
# "render" as a word, not inside a path, a name or a hyphened compound ("//render/", "render_engine",
# "ready‑to‑render" with U+2011)
_ASK_RENDER = re.compile(r"(?<![/\\.\-_`'\"‐-—])\brender(?:s|ing)?\b(?![/\\_.\-‐-—])", re.I)
_ASK_RENDER_NOUN = re.compile(r"\s+(?:settings?|engines?|resolution|samples?|output|layers?|device|properties|"
                              r"passes|pass|region|border|format|size|time|percentage|panel|tab|range|fps|quality|"
                              r"preview|visibility|options?|frame\s+range|slots?|view|views|result\s+node|nodes?|"
                              r"farm|budget|speed|path|filepath|directory|folder)\b", re.I)
_ASK_RENDER_WHAT = re.compile(r"^(?:\s+(?:out|the|a|an|it|this|that|one|each|every|all|final|full|whole|complete|"
                              r"entire|single|first|last|current|scene's|[\w×x-]*\d[\w×x-]*|"
                              r"\d+\s*(?:px|frames?|seconds?|s)|\w+-frame|turntable|preview|test|quick|high-quality|"
                              r"cycles|eevee)){0,4}\s+(?:animation|animations|image|images|still|stills|frames?|video|"
                              r"movie|clip|sequence|scene|shot|turntable|result|picture|it|mp4|png|jpe?g|exr)\b", re.I)
_ASK_RENDER_TO = re.compile(r"^[^.;\n]{0,60}?\b(?:to|as|into)\s+[`\"']?[^\s`\"']*\.(?:png|jpe?g|exr|tiff?|bmp|webp|"
                            r"mp4|mkv|mov|avi)\b", re.I)
_ASK_NOUN_USE = re.compile(r"\b(?:the|a|an|final|test|for|before|after|of|your|its|this|their|each|every)\s*$", re.I)
# What _chimera_output (app/hydra_assemble.go, chimeraOutputFn) renders: a path with one of these extensions; a video
# for the last four (or any of them with a truthy "animation")
OUTPUT_MEDIA = (".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff", ".bmp", ".webp", ".mp4", ".mkv", ".mov", ".avi")
OUTPUT_VIDEO = (".mp4", ".mkv", ".mov", ".avi")
# A file a step names for output_missing's tell line: its own name for the path, so nothing in the line is a
# placeholder a next try could copy ('{"blend": "x.blend"}' passed the echo check and would save x.blend)
_OUTPUT_FILE = re.compile(r"(?<![\w.])(?:/{2})?[\w.\-/]*\w\.(blend|png|jpe?g|exr|tiff?|bmp|webp|mp4|mkv|mov|avi)\b",
                          re.I)


def _num(x):
    """A measured or asked number as a tell line writes it: 2.4, 0.45, 5."""
    try:
        return ("%.2f" % float(x)).rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(x)


def _sides(sides, unit="m"):
    return " × ".join("?" if s is None else _num(s) for s in sides) + " " + unit


def size_triples(text):
    """The size triples a text gives: [{"phrase", "sides": [metres, or None for a side named by a variable], "words":
    the words around it that may say what it is, "thing": what it is the size of, as the text words it (_thing_of;
    "" when it can't tell), and "vars" (the variable naming each side, None for a number) when a side is a
    variable}], each with at least two numbers and a length unit (a triple without one, a resolution or a time, isn't
    a size). Another step's thing is left out: one just after a step's name ("s1's"), one in a clause that names a
    step it comes from before it ("the island from s1", "built in s2") and one with such words right after it."""
    out = []
    text = text or ""
    for m in _TRIPLE.finditer(text):
        if _STEP_WORD.search(text[max(0, m.start() - 40):m.start()]):  # another step's ("on s1's 2 x 1 x 1 m table")
            continue
        if _FROM_STEP.search(text, _clause_start(text, m.start()), m.start()) or \
                _FROM_STEP.match(re.sub(r"^[\s)]+", "", text[m.end():m.end() + 40])):
            continue
        g = m.groups()
        sides = [(g[k], g[k + 1], g[k + 2] or g[k + 3]) for k in (0, 4, 8)]
        units = [u for _, u, _ in sides] + [g[12]]
        if sum(1 for n, _, _ in sides if n) < 2 or not any(units):
            continue
        vals = []
        for k, (n, u, _) in enumerate(sides):
            unit = u or next((x for x in units[k + 1:] if x), None) or next((x for x in reversed(units[:k]) if x), "m")
            vals.append(_metres(n, unit) if n else None)
        before = re.split(r"[\n.;:]", text[max(0, m.start() - 80):m.start()])[-1].split()[-6:]
        after = re.split(r"[\n.;:,(]", text[m.end():m.end() + 60])[0].split()[:3]
        named = [re.sub(r"_(?:dims?|size|length)$", "", x) for _, _, x in sides if x]
        t = {"phrase": m.group(0).strip(), "sides": vals, "words": sorted(_words(" ".join(before + after + named))),
             "thing": _thing_of(text, m, named)}
        if named:
            t["vars"] = [x or None for _, _, x in sides]
        out.append(t)
    return out


# A step a clause says its thing comes from: "the island from s1", "the room built in s2", "made by step s3"
_FROM_STEP = re.compile(r"\b(?:from|(?:built|made|created|modell?ed|added|defined|placed|given)\s+(?:in|by))\s+"
                        r"(?:step\s+)?s\d+\b", re.I)


def _clause_start(text, pos):
    """Where the clause holding pos starts (after the last sentence end or newline before it, _CLAUSE)."""
    start = 0
    for c in _CLAUSE.finditer(text, 0, pos):
        start = c.end()
    return start


def _name_words(token):
    """A token's words that can tell one thing from another, in order ("chimera_island": ["island"])."""
    parts = re.split(r"[\W_]+|(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", token)
    return [w.lower() for w in parts if len(w) >= 3 and not w.isdigit() and w.lower() not in _PLAIN_WORDS]


# Words between a thing and its size that say nothing of what it is, passed over before the thing's own words: "the
# table is about 2 × 1 × 0.75 m", "the island, which measures ...", "a shelf unit measuring ...", "0.9 m deep and 0.92 m
# tall (2.4 × ...)". Once a thing's word is read, a relative word ends it ("a desk whose top is ...": "top").
_THING_SKIP = {"about", "roughly", "approximately", "approx", "around", "nearly", "almost", "exactly", "precisely",
               "just", "some", "overall", "total", "should", "must", "will", "would", "shall", "can", "could", "may",
               "might", "is", "are", "be", "being", "been", "was", "were", "measure", "measures", "measuring",
               "measured", "sized", "which", "that", "tall", "high", "wide", "long", "deep", "thick", "and"}
_THING_END = {"which", "that", "whose", "who", "where"}
_UNIT_TOKEN = re.compile(r"(?:%s)?%s$" % (_NUM, _UNIT), re.I)  # "m", "cm", "0.92m"


def _thing_of(text, m, named):
    """What the size triple m is the size of, in the text's own words: the stem of a variable it names a side by
    ("sofa_dim": "sofa"), else the last one or two telling words just before it in its clause ("a rectangular island
    countertop (2.4 m × ...": "island countertop"; "chimera_island" gives "island"), past the words that only speak
    of the size (_THING_SKIP, numbers and units: "the table is about ...": "table"; "the island, which measures ...":
    "island"), else the first ones after it ("a 2 × 1 × 0.75 m oak table": "oak table"); "" when there are none
    ("with dimensions 2 × 1 × 1 m", "It should measure ...")."""
    if named:
        return named[0]
    toks = text[_clause_start(text, m.start()):m.start()].split()
    name = []
    for t in reversed(toks):
        bare = t.strip("()[]{},;:\"'").lower()
        if not name and (not re.search(r"[A-Za-z]", t) or bare in _THING_SKIP or _UNIT_TOKEN.match(bare)):
            continue  # the "(" before the numbers, "is about", "0.92 m tall"
        w = _name_words(t)
        if not w or len(name) >= 2 or bare in _THING_END:
            break
        name = [x for x in w if x not in name] + name
    if name:
        return " ".join(name[-2:])
    for t in re.split(r"[\n.;:,(]", text[m.end():m.end() + 60])[0].split():
        w = _name_words(t)
        if not w or len(name) >= 2:
            break
        name += [x for x in w if x not in name]
    return " ".join(name[:2])


def _metres(n, unit):
    u = (unit or "m").lower()
    return float(n) * (0.001 if u.startswith(("mm", "milli")) else 0.01 if u.startswith(("cm", "centi")) else 1.0)


def named_triples(text):
    """Three sides of one thing given by name (sofa_length=2.2, sofa_width=0.9, sofa_height=0.8): [{"thing":
    "sofa", "phrase", "sides": [metres]}], for each thing with a length (or x), a width or depth (or y) and a
    height (or z)."""
    by = {}
    for m in _NAMED_SIDE.finditer(text or ""):
        thing, side, n, unit = m.groups()
        axis = {"length": 0, "width": 1, "depth": 1, "height": 2}.get(side, "xyz".find(side[-1]))
        by.setdefault(thing.lower(), {}).setdefault(axis, (_metres(n, unit), m.group(0).strip()))
    return [{"thing": t, "phrase": ", ".join(s[k][1] for k in range(3)), "sides": [s[k][0] for k in range(3)],
             "words": sorted(_words(t))} for t, s in by.items() if len(s) == 3]


# Words that make something ("create", "adds", "building", "set up"), and the place words that end what a making
# verb makes ("add a floor under the island" makes the floor, not the island). Past forms aren't makers: "the island
# built in s1" is another step's.
_MAKES = re.compile(r"\b(?:creat(?:e|es|ing)|add(?:s|ing)?|build(?:s|ing)?|model(?:s|ing|ling)?|mak(?:e|es|ing)|"
                    r"construct(?:s|ing)?|plac(?:e|es|ing)|put(?:s|ting)?|insert(?:s|ing)?|generat(?:e|es|ing)|"
                    r"spawn(?:s|ing)?|lay(?:s|ing)?|hang(?:s|ing)?|mount(?:s|ing)?|draw(?:s|ing)?|sculpt(?:s|ing)?|"
                    r"instantiat(?:e|es|ing)|set(?:s|ting)?\s+up)\b", re.I)
# "built-in" isn't a place word, whatever its hyphen
_PLACES = (r"(?:under|on|onto|upon|above|over|below|beneath|beside|behind|near|next|around|inside|within|along|across|"
           r"against|at|toward|towards|facing|between|among|from|to|for|in|into|through|via|after)")
_PLACE_WORD = re.compile(r"(?<![\w\u2010-\u2015-])%s(?![\w\u2010-\u2015-])" % _PLACES, re.I)
# What else ends what a making verb makes: a relative word, or a verb of looking or aiming at something ("add a camera
# that frames the island", "create a spotlight aiming at the stage")
_MADE_END = re.compile(r"(?<![\w\u2010-\u2015-])(?:that|which|who|whose|where|framing|frames|faces|looking|looks|"
                       r"aiming|aims|pointing|points|overlooking|overlooks|targeting|targets|illuminating|"
                       r"illuminates|lighting)(?![\w\u2010-\u2015-])", re.I)
# A mention of a thing as a place or a target: a place word, at most three words, then the thing ("above the kitchen
# island", "next to the sofa")
_AFTER_PLACE = re.compile(r"(?<![\w\u2010-\u2015-])%s\s+(?:\S+\s+){0,3}$" % _PLACES, re.I)
_ITEM = re.compile(r"\s*(?:[-*\u2022\u2013]|\d+[.)]|\(?[a-z]\))?\s*")  # a list item's bullet or number
_ARTICLE = r"(?:a|an|the|one|two|three|four|five|six|\d+)"


def _thing_re(thing):
    """A pattern for a thing as text may write it: its words in order with spaces, underscores or hyphens between
    ("coffee_table": "coffee table", "Coffee-Table"), the last one singular or plural."""
    words = [w for w in re.split(r"[\s_-]+", thing.lower()) if w]
    last = words[-1]
    last = last[:-2] if last.endswith("es") and last[-3:-2] in ("s", "x", "z") else \
        last[:-1] if last.endswith("s") and not last.endswith("ss") else last
    body = r"[\s_\-\u2010-\u2015]*".join(re.escape(w) for w in words[:-1] + [last])
    return re.compile(r"(?<![A-Za-z0-9])%s(?:s|es)?(?![A-Za-z0-9])" % body, re.I)


def _makes(text, thing):
    """Whether text makes the thing: a making verb with the thing after it in its clause and no place word or
    relative word between (_PLACE_WORD, _MADE_END: "Creates a rectangular island countertop", "Create the sofa, coffee
    table, TV stand"; not "add a camera that frames the island"), or, in a text that has a
    making verb somewhere ("add the following:"), a list item or label that is the thing ("1. Sofa: a box with ...",
    "2. A cube named building_a ...", "- Kitchen island (2.4 × 0.9 × 0.92 m)")."""
    if not (thing or "").strip(" _-"):
        return False
    pat = _thing_re(thing)
    any_maker = _MAKES.search(text or "") is not None
    for clause in _CLAUSE.split(text or ""):
        for v in _MAKES.finditer(clause):
            rest = clause[v.end():v.end() + 160]
            stops = [x.start() for x in (_PLACE_WORD.search(rest), _MADE_END.search(rest)) if x]
            if pat.search(rest[:min(stops)] if stops else rest):
                return True
        if not any_maker:
            continue
        bullet = _ITEM.match(clause)
        item = clause[bullet.end():]
        label = re.match(r"([^:\n]{1,40}):", item)
        if label and pat.search(label.group(1)):
            return True
        if bullet.group().strip() and re.match(r"(?:%s\s+(?:\S+\s+){0,3}?|(?:\S+\s+)?)[^\w\s]*%s" % (
                _ARTICLE, pat.pattern), item, re.I):
            return True
    return False


def _ancestors(plan, i):
    """Every step step i depends on, directly or through another, in plan order."""
    out, todo = set(), list(dep_indexes(plan, i))
    while todo:
        j = todo.pop()
        if j not in out:
            out.add(j)
            todo.extend(dep_indexes(plan, j))
    return sorted(out)


def _step_text(st):
    return (st.get("title") or "") + "\n" + (st.get("instructions") or "")


_COPY = re.compile(r"^(?P<base>.+)\.(?P<n>\d{3})$")
_QUOTE_CHARS = re.escape("\"'`“”‘’")
FACTORY_CAMERA = ("Camera", "CAMERA", "Camera")


def asks_name(words, name):
    """Whether the words give name in quotes ("Camera", 'Camera', `Camera`, “Camera”): a name a step asks for
    exactly."""
    return bool(re.search("[%s]%s[%s]" % (_QUOTE_CHARS, re.escape(name), _QUOTE_CHARS), words or ""))


def factory_copies(rec, words, later=""):
    """The duplicates of one version's direct run (rec: its record) that only the factory scene explains, so no step
    made a name twice: the factory camera's name taken again because a step (words: the title and instructions of the
    steps in the run) asks in quotes for a camera named "Camera" (smoke2's n-blender-0000-01 s3: 'Creates a camera
    named "Camera"', which --factory-startup's own Camera turns into Camera.001). Measured, not read: the copy is the
    only other object of that name, it is a camera, the factory camera is still there as the factory made it, and the
    scene's camera (the one a render uses, the measuring's scene_camera) is the copy, so the factory camera left
    behind changes nothing a render shows. A piece that leaves the factory camera as the scene's camera (that step's
    round-1 tries) still fails. Only the camera: a copy of the factory cube leaves a 2 m cube in the render, and the
    factory light still lights it. later: the words of the steps after this one; when one of them asks for the name
    too, that step makes it, and this copy is the duplicate its join will show (the first smoke's n-blender-0000-01:
    s1 has 'camera_name = "Camera"', s3 makes it)."""
    scene, measure = rec.get("scene") or {}, rec.get("measure") or {}
    objs = scene.get("objects") or []
    if FACTORY_CAMERA not in {(o["name"], o["type"], o.get("data")) for o in objs}:
        return []
    cam = measure.get("scene_camera")
    out = []
    for d in rec.get("dupes") or []:
        m = _COPY.match(d)
        if not m or m.group("base") != FACTORY_CAMERA[0] or not asks_name(words, FACTORY_CAMERA[0]) or \
                asks_name(later, FACTORY_CAMERA[0]):
            continue
        same = [o for o in objs if o["name"] == m.group("base") or
                (_COPY.match(o["name"]) and _COPY.match(o["name"]).group("base") == m.group("base"))]
        mine = [o for o in same if o["name"] == d]
        if len(same) == 2 and len(mine) == 1 and mine[0]["type"] == "CAMERA" and isinstance(cam, dict) and \
                cam.get("n") == d and not cam.get("f"):
            out.append(d)
    return out


def real_dupes(run, versions, words, later=""):
    """(the duplicates of a run, in any version, that factory_copies doesn't explain; those it does). A copy is
    excused only when every version whose direct run lists it explains it."""
    listed = {}
    for v in versions:
        rec = run["probe"].get(v) or {}
        ok = set(factory_copies(rec, words, later))
        for d in rec.get("dupes") or []:
            listed.setdefault(d, []).append(d in ok)
    return (sorted(d for d, oks in listed.items() if not all(oks)),
            sorted(d for d, oks in listed.items() if all(oks)))


def _title_head(title):
    """A title up to its first place word or relative word: what the step is about ("Lights over the island":
    "Lights")."""
    stops = [x.start() for x in (_PLACE_WORD.search(title or ""), _MADE_END.search(title or "")) if x]
    return (title or "")[:min(stops)] if stops else (title or "")


def _referred(text, thing):
    """Whether text names the thing only as a place or a target, every mention a place word and at most three words
    after (_AFTER_PLACE: "Place a lamp above the kitchen island", "Put a vase on the table"); False when it never
    names it."""
    found = False
    for m in _thing_re(thing).finditer(text or ""):
        if not _AFTER_PLACE.search(text[max(0, m.start() - 60):m.start()]):
            return False
        found = True
    return found


def _same_thing(a, b):
    """Whether two things as steps word them are one: either's words are in the other ("island", "kitchen island")."""
    return bool(a and b) and (_thing_re(a).search(b) is not None or _thing_re(b).search(a) is not None)


def _made_elsewhere(plan, i, thing):
    """Whether a step of the plan other than step i makes the thing, a step that only defines values aside: its own
    words make it (_makes), or, for a step before i, its title's head names it ("Kitchen island") or it gives a size
    for the thing itself. A later step's title or size doesn't count: "Camera framing the island" in s3 doesn't make
    s1's island, and a later step that frames the island with its size refers to the earlier one's."""
    pat = _thing_re(thing)
    for j, d in enumerate(plan["steps"]):
        if j == i or _VARIABLES_STEP.search(d.get("title") or ""):
            continue
        text = _step_text(d)
        if _makes(text, thing):
            return True
        if j < i and (pat.search(_title_head(d.get("title") or "")) or
                      any(_same_thing(t["thing"], thing) for t in size_triples(text))):
            return True
    return False


def asked_sizes(plan, i):
    """The sizes step i asks for: triples in its own title and instructions, and three sides of a thing given by
    name in them or in a dependency that only defines values (its title says so: "Define dimensions, colours, ..."),
    when the step's own words name that thing outside the variables.
    A size is asked unless another step makes its thing (steps that only define values make nothing). When the
    step's own words make it (_makes: "Create the sofa, coffee table, ..."), only a step it depends on, directly or
    not, that makes it too takes it away. Otherwise (no making verb: "The scene needs a kitchen island (2.4 × 0.9 ×
    0.92 m)", "Walls: 5 m × 0.2 m × 3 m each", "The table is about 2 × 1 × 0.75 m") it is asked unless any other step
    makes it (_made_elsewhere), or the step names it only as a place or a target (_referred: "Place a lamp above the
    kitchen island (...)"). So a one-step plan's sizes are its own, and a floor step's "under the island (2.4 m × 0.9
    m × 0.92 m)" or a camera step's "frame the island (...)" or "frames the island, which measures ..." asks nothing
    of it when another step builds the island. A triple whose thing can't be told (_thing_of gives "") is asked
    unless another step makes something its words name."""
    st = plan["steps"][i]
    own = _step_text(st)
    plain = _NAMED_SIDE.sub(" ", own)
    makers = [_step_text(plan["steps"][j]) for j in _ancestors(plan, i)
              if not _VARIABLES_STEP.search(plan["steps"][j].get("title") or "")]

    def mine(thing, words=()):
        if not thing:
            return not any(_made_elsewhere(plan, i, w) for w in words)
        if _makes(plain, thing):
            return not any(_makes(t, thing) for t in makers)
        return not _referred(plain, thing) and not _made_elsewhere(plan, i, thing)
    out = [dict(t, source="step") for t in size_triples(own) if mine(t["thing"], t["words"])]
    texts = [] if _VARIABLES_STEP.search(st.get("title") or "") else [(own, "step")]
    for j in dep_indexes(plan, i):
        d = plan["steps"][j]
        if _VARIABLES_STEP.search(d.get("title") or ""):
            texts.append((_step_text(d), "s%d" % (j + 1)))
    seen = {tuple(t["sides"]) for t in out}
    for text, source in texts:
        for t in named_triples(text):
            if _thing_re(t["thing"]).search(plain) and mine(t["thing"]) and tuple(t["sides"]) not in seen:
                seen.add(tuple(t["sides"]))
                out.append(dict(t, source=source))
    return out


def _tilt(clause, a):
    """The tilt below level, in degrees, that angle match a in its clause says: N, or 90 - N when measured from
    vertical, straight down, the zenith or the nadir (_FROM_VERTICAL); -1 for one over 90 degrees, which can't be read
    as a tilt."""
    n = float(a.group(1))
    n = math.degrees(n) if a.group(2).lower().startswith("rad") else n
    if n > 90:
        return -1
    return round(90 - n if _FROM_VERTICAL.match(clause, a.end()) else n, 2)


def _not_tilt(clause, a):
    """Whether angle match a says something other than a tilt: a cone, a beam, a sun's disc, a field of view."""
    return _NOT_TILT_AFTER.match(clause, a.end()) is not None or \
        _NOT_TILT_BEFORE.search(clause[max(0, a.start() - 40):a.start()]) is not None


def _down_angle(clause, m):
    """(the tilt below level a "down" phrase m gives, in degrees, the angle match it comes from): one inside the
    phrase ("tilted 15 degrees down", "angled 20 degrees from straight down": 70) or right after it ("angled down 20°",
    "down at 30 degrees", "down by 0.3 rad", "down 60 degrees from vertical": 30), as _tilt reads it; (None, None)
    when it gives none, and (None, match) for an angle there that is no tilt (_not_tilt)."""
    a = _ANGLE_IN.search(clause, m.start(), m.end()) or _ANGLE_AFTER.match(clause, m.end())
    if a is None:
        return None, None
    return (None if _not_tilt(clause, a) else _tilt(clause, a)), a


def _clause_angles(clause, found):
    """How the angles of a clause read, given its "down" phrases (found: [(match, word)]): ({phrase span: tilt or
    None} for the "down" phrases, a tilt the clause gives outright or None), where a tilt given outright is one
    measured from vertical or level anywhere in the clause ("30 degrees from the zenith", "15 degrees below
    horizontal"). None in place of the whole when an angle in it is none of those, a phrase's own, outright or no
    tilt at all ("down to 70 degrees", "pointing down toward the floor at a 25 degree angle", "a downward-facing camera
    tilted 20 degrees"), or the clause gives a rotation in numbers: the clause says nothing certain then."""
    own, read = {}, set()
    for m, word in found:
        if word is None:
            tilt, a = _down_angle(clause, m)
            own[m.span()] = tilt
            if a is not None:
                read.add(a.start(1))
    outright = None
    for a in _ANGLE_IN.finditer(clause):
        if a.start(1) in read or _not_tilt(clause, a):
            continue
        if not (_FROM_VERTICAL.match(clause, a.end()) or _FROM_LEVEL.match(clause, a.end())):
            return None
        if outright is None:
            outright = _tilt(clause, a)
    spans = [a.span() for a in _ANGLE_IN.finditer(clause)]
    if any(not any(lo <= u.start() < hi for lo, hi in spans) for u in _ANGLE_UNIT.finditer(clause)) or \
            _ROTATION.search(clause):
        return None
    return own, outright


def aim_z(want):
    """The highest z the direction of a light or camera a step says points down may have: AIM_DOWN_Z, or for an
    angle the step gives, its sine below level with 0.1 to spare (15 degrees: -0.16)."""
    if want.get("angle") is None:
        return AIM_DOWN_Z
    return round(-math.sin(math.radians(want["angle"])) + 0.1, 2)


def asked_aims(plan, i):
    """What step i says points down: [{"what": "light"|"camera", "type": "AREA"|"SPOT"|"SUN"|None, "word":
    "ceiling"|"overhead"|None, "angle": degrees below level or None, "phrase"}] from its title and instructions, a
    clause at a time: a light or camera pointed, aimed or facing down (or downward, straight down, at the floor or the
    ground, top-down), and a ceiling or overhead light. A hedged clause ("aimed down at a slight angle") says nothing
    certain, a point light has no direction, and "down" that runs on to a place ("straight down the corridor") or a
    target is no direction. An angle with "down" ("tilted down 15 degrees") is how far down it must point (aim_z),
    measured from level, or from vertical when it says so ("60 degrees from vertical" is 30 below level), and so is
    one the clause gives outright from vertical or level; over 90 degrees, the clause says nothing certain. So does
    a clause with any other angle (_clause_angles: "down to 70 degrees", an absolute rotation; "pointing down toward
    the floor at a 25 degree angle"; "a downward-facing camera tilted 20 degrees") or a rotation in numbers, rather
    than hold it to AIM_DOWN_Z; a cone's or a field of view's angle is no tilt and leaves "down" as it is. The same
    light or camera said twice keeps its most lenient reading."""
    st = plan["steps"][i]
    out = []
    for clause in _CLAUSE.split((st.get("title") or "") + "\n" + (st.get("instructions") or "")):
        if _HEDGED.search(clause):
            continue
        downs = [m for p in _DOWN for m in p.finditer(clause)]
        # one phrase inside another is that one ("angled 20 degrees from straight down" holds "straight down")
        downs = [m for m in downs if not any(o.start() <= m.start() and m.end() <= o.end() and o.span() != m.span()
                                             for o in downs)]
        found = [(m, None) for m in downs] + [(m, m.group("word").lower()) for m in _OVERHEAD.finditer(clause)]
        if not found:
            continue
        angles = _clause_angles(clause, found)
        if angles is None:
            continue
        own, outright = angles
        # A ceiling light "angled down 30 degrees" takes the angle its clause gives with "down", else one given
        # outright; a "down" phrase with none of its own takes the one given outright
        given = next((a for a in own.values() if a is not None), outright)
        for m, word in found:
            subjects = list(_SUBJECT.finditer(clause))
            inside = [s for s in subjects if m.start() <= s.start() < m.end()]
            before = [s for s in subjects if s.end() <= m.start()]
            after = [s for s in subjects if s.start() >= m.end()]
            s = (inside or before[-1:] or after[:1] or [None])[0]
            if s is None:
                continue
            if s.group("cam"):
                want = {"what": "camera", "type": None}
            else:
                kind = (s.group("kind") or s.group("spot") or s.group("sun") or "").lower()
                want = {"what": "light", "type": _LIGHT_TYPES.get(kind)}
                if want["type"] == "POINT":
                    continue
            angle = given if word is not None else own[m.span()] if own[m.span()] is not None else outright
            if angle == -1:
                continue
            want.update(word=word, angle=angle, phrase=clause.strip()[:160])
            same = [w for w in out if (w["what"], w["type"], w["word"]) == (want["what"], want["type"], want["word"])]
            if not same:
                out.append(want)
            elif aim_z(want) > aim_z(same[0]):
                same[0].update(angle=angle, phrase=want["phrase"])
    # "Ceiling light" in the title and "a ceiling area light" in the instructions are one light: the one with a type
    return [w for w in out if w["type"] is not None or not any(
        x["type"] is not None and (x["what"], x["word"]) == (w["what"], w["word"]) for x in out)]


def asks_output(plan, i):
    """Whether step i's title or instructions speak of saving, rendering, exporting or an output file."""
    st = plan["steps"][i]
    return _ASKS_OUTPUT.search((st.get("title") or "") + "\n" + (st.get("instructions") or "")) is not None


def output_paths(code, sid):
    """The paths a piece's SETTINGS_sN["output"] sets, as written (a path made in code as its source): every string
    under it but those of keys that set something else (resolution, fps, engine, ...), as Go's hasOutput reads the
    first SETTINGS_sN. [] when it sets none."""
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return []
    for n in tree.body:
        if not isinstance(n, (ast.Assign, ast.AnnAssign)) or _assigned(n) != ["SETTINGS_" + sid]:
            continue
        if not isinstance(n.value, ast.Dict):
            return []
        for k, v in zip(n.value.keys, n.value.values):
            if isinstance(k, ast.Constant) and k.value == "output":
                return list(dict.fromkeys(_paths(v, "output")))
        return []
    return []


def _paths(node, key):
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values):
            name = k.value if isinstance(k, ast.Constant) and isinstance(k.value, str) else None
            if k is not None and (name or "").lower() not in _NOT_PATH_KEYS:
                yield from _paths(v, name or key)
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for e in node.elts:
            yield from _paths(e, key)
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, str) and node.value.strip():
            yield node.value
    elif isinstance(node, (ast.JoinedStr, ast.Call)) or \
            (isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod))) or \
            (isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)) and _PATH_KEYS.search(key or "")):
        yield ast.unparse(node)[:80]


def _saves_blend(after):
    """Whether the words after a save verb say a .blend is saved: a .blend (or a Blender file) within
    _ASK_OBJ_WORDS words, with no other file, script or image before it."""
    window = "".join(re.split(r"(\s+)", after)[:2 * _ASK_OBJ_WORDS])
    b = _ASK_BLEND.search(window)
    return b is not None and _ASK_OTHER.search(window[:b.start()]) is None


def asked_outputs(plan, i):
    """What step i's own title and instructions ask Chimera to make: {"blend": the sentence asking to save a .blend,
    "render": the one asking for a render}, each None when they don't (the rules above _ASK_SENT). Read on 301
    distinct Blender steps (both smoke runs' plans and the helper's stored plans): 123 ask (85 a .blend, 56 a render),
    every firing sentence read; the false ones found, "ready‑to‑render" (U+2011) and a save made "(optional)", are
    fixed; borderline: "Save the material in the same .blend file", a .gif (_chimera_output renders none). Missed on
    purpose: "will have saved", nameless saves; missed: "Export only the .blend", "Saves both EXR and PNG renders". In
    the runs only the helper's seeds ask much (4 of their 9 distinct Blender steps, 2 of the new seeds' 30)."""
    st = plan["steps"][i]
    out = {"blend": None, "render": None}
    text = (st.get("title") or "") + ".\n" + (st.get("instructions") or "")
    for sent in (x for x in _ASK_SENT.split(text) if x.strip()):
        if _ASK_OPTIONAL.search(sent):
            continue

        def negated(at):  # turned round, or only prepared for another step (_ASK_DEFER_BEFORE, _ASK_DEFER_AFTER)
            return _ASK_NEG.search(sent[:at]) is not None or _ASK_DEFER_BEFORE.search(sent[:at]) is not None or \
                _ASK_DEFER_AFTER.search(sent[at:]) is not None
        if out["blend"] is None and any(not negated(m.start()) and _saves_blend(sent[m.end():])
                                        for m in _ASK_SAVE.finditer(sent)):
            out["blend"] = sent.strip()
        if out["render"] is None and (
                any(not negated(m.start()) for m in _ASK_RENDER_MENU.finditer(sent)) or
                any(not negated(m.start()) and not _ASK_RENDER_NOUN.match(sent[m.end():]) and
                    not _ASK_NOUN_USE.search(sent[:m.start()]) and
                    (_ASK_RENDER_WHAT.match(sent[m.end():]) or _ASK_RENDER_TO.match(sent[m.end():]))
                    for m in _ASK_RENDER.finditer(sent))):
            out["render"] = sent.strip()
    return out


_UNREAD = object()  # a value in SETTINGS_sN["output"] that isn't a literal: a name, a call, an f-string


def _literal(node):
    """A literal's value (str, number, dict, list), _UNREAD for anything else or a dict that holds one as a key."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Dict):
        if any(k is None for k in node.keys):
            return _UNREAD
        keys = [_literal(k) for k in node.keys]
        if any(k is _UNREAD for k in keys):
            return _UNREAD
        return {k: _literal(v) for k, v in zip(keys, node.values)}
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_literal(e) for e in node.elts]
    return _UNREAD


def handed_outputs(code, sid):
    """What Chimera does with a piece's output: Go's hasOutput (the first top-level SETTINGS_sN = {...} has a constant
    "output" key; only then does the join pass SETTINGS_sN to _chimera_output) and, for that key's value, what
    _chimera_output (chimeraOutputFn) makes of it: {"has", "blend": the path it saves, "render": the path it renders (a
    string with an OUTPUT_MEDIA extension), "video", "unread"}. "unread" when the value holds something that isn't a
    literal where a path could be: then nobody can say here what Chimera would do. Parity, measured: the hasOutput half
    against the binary's --hydra-assemble on 290 joined candidates, the path half against _chimera_output's own text run
    with a stub bpy on 33 stored values and 22 made-up edge cases (.gif, upper-case extensions, nested dicts,
    "animation", lists, non-strings): 0 differ."""
    out = {"has": False, "blend": None, "render": None, "video": False, "unread": False}
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return out
    value = None
    for n in tree.body:
        if not isinstance(n, (ast.Assign, ast.AnnAssign)) or _assigned(n) != ["SETTINGS_" + sid] or \
                not isinstance(n.value, ast.Dict):
            continue
        for k, v in zip(n.value.keys, n.value.values):
            if isinstance(k, ast.Constant) and k.value == "output":
                out["has"], value = True, _literal(v)
        break
    if not out["has"]:
        return out
    o = value
    if isinstance(o, str):
        o = {"blend" if o.lower().endswith(".blend") else "render": o}
    if o is _UNREAD:
        out["unread"] = True
        return out
    merged = {}
    for k, v in (o.items() if isinstance(o, dict) else ()):
        if isinstance(v, dict):
            merged.update(v)
        else:
            merged[k] = v
    out["unread"] = any(v is _UNREAD for v in merged.values())
    strs = [v for v in merged.values() if isinstance(v, str)]
    out["blend"] = next((v for v in strs if v.lower().endswith(".blend")), None)
    out["render"] = next((v for v in strs if os.path.splitext(v)[1].lower() in OUTPUT_MEDIA), None)
    out["video"] = bool(out["render"]) and (os.path.splitext(out["render"])[1].lower() in OUTPUT_VIDEO or
                                            bool(merged.get("animation")))
    return out


def output_missing(plan, i, code):
    """(missing, asked, handed): what step i's words ask Chimera to make (asked_outputs) that the piece doesn't hand
    over (handed_outputs): ["blend"], ["render"] or both; [] when it asks nothing, hands it all over, or hands over
    something that can't be read here. Exports (GLB, FBX) aren't asked: _chimera_output makes none, and the contract
    lets a piece export itself."""
    asked = asked_outputs(plan, i)
    if not asked["blend"] and not asked["render"]:
        return [], asked, None
    handed = handed_outputs(code, "s%d" % (i + 1))
    if handed["unread"]:
        return [], asked, handed
    return [k for k in ("blend", "render") if asked[k] and not handed[k]], asked, handed


# output_missing's tell line. Ours (TELL_FORMS) only up to "but": its advice is Chimera's own words from the request
# ("put the path or render settings in SETTINGS_sN["output"] and Chimera does it once, after the last step"), so a
# next try that repeats them repeats Chimera, not us; the paths are the step's own file names, else what a path must
# end in.
MISSING_WHAT = {("blend",): "to save a .blend", ("render",): "for a render",
                ("blend", "render"): "to save a .blend and to render"}
MISSING_HEAD = "the step asks Chimera %s, but "
MISSING_WHY = {("blend",): "no .blend path", ("render",): "no image or video path", ("blend", "render"): "neither path"}
MISSING_TELL = ('%s: put the path or render settings in SETTINGS_%s["output"] (%s) and Chimera does it once, after '
                'the last step')
MISSING_GENERIC = {"blend": "a .blend path", "render": "a .png or .mp4 path"}


def _named_outputs(text, kind):
    """The files of kind ("blend", or "render": an image or a video) a text names, in order, once each."""
    out = []
    for m in _OUTPUT_FILE.finditer(text or ""):
        if (kind == "blend") == (m.group(1).lower() == "blend") and m.group(0) not in out:
            out.append(m.group(0))
    return out


def missing_tell(plan, i, missing, handed, asked):
    """The tell line for output_missing (teacher-only), at most FAILURE_CHARS (240) long: what the step asks and
    what SETTINGS_sN lacks, then Chimera's own advice with, for each kind missing, the name the asked sentence gives
    (for a render, else the step's last image or video name), else what the path must end in; a line that would run
    long says only that. On the 246 tells of the corpus' asking steps the longest is 239; with it as extra, the echo
    check flags none of the 100 stored tries of those steps, and a right next try passes in either key order."""
    sid = "s%d" % (i + 1)
    st = plan["steps"][i]
    whole = (st.get("title") or "") + ".\n" + (st.get("instructions") or "")
    why = ('SETTINGS_%s has no "output"' % sid if not handed or not handed.get("has") else
           'SETTINGS_%s["output"] has %s' % (sid, MISSING_WHY[tuple(missing)]))
    head = MISSING_HEAD % MISSING_WHAT[tuple(missing)] + why
    picks = []
    for k in missing:
        names = _named_outputs(asked.get(k), k) or (_named_outputs(whole, k)[-1:] if k == "render" else [])
        picks.append(json.dumps(names[0]) if names else MISSING_GENERIC[k])
    line = MISSING_TELL % (head, sid, " and ".join(picks))
    if len(line) > FAILURE_CHARS:  # a long path the step names: say only what it must end in
        line = MISSING_TELL % (head, sid, " and ".join(MISSING_GENERIC[k] for k in missing))
    return line


# The line for SETTINGS_sN keys dead_output_key names, told with a step that asks Chimera for a render or a save
# (dead_tell), whatever else failed: most tries that missed "output" kept their path under a key of their own (25 of
# the 39 distinct output_missing tries: "output_path", "output_filepath", "output_dir"), and a retry that only adds
# "output" passes every gate, then the build drops it (dead_output_key: X58's and X20's told forms). {quotes} are the
# piece's own keys; one key or several. On those 25 the longest line is 157 characters, and none of the 737 distinct
# stored replies holds a run of its wording.
DEAD_TELL = {1: '{quotes} in SETTINGS_{sid} is a key Chimera never reads (it reads only "output"): keep the path in '
                '"output" alone and leave the key out',
             2: '{quotes} in SETTINGS_{sid} are keys Chimera never reads (it reads only "output"): keep the path in '
                '"output" alone and leave those keys out'}
DEAD_QUOTES = 3


def dead_tell(sid, keys, asked=True):
    """The tell line for a piece's dead output keys (keys: dead_output_key's), at most FAILURE_CHARS long: DEAD_TELL
    for a step that asks Chimera for a render or a save (asked), DEAD_UNASKED for one that asks for neither."""
    quotes = ", ".join(json.dumps(k) for k in keys[:DEAD_QUOTES]) + (" and more" if len(keys) > DEAD_QUOTES else "")
    return (DEAD_TELL if asked else DEAD_UNASKED)[min(len(keys), 2)].format(quotes=quotes, sid=sid)[:FAILURE_CHARS]


# What the build drops, told at the gate (since the fourth smoke, Nov 5; build_facts): Chimera's validator warnings
# (build.WARNINGS: handoff_long, uses_undeclared, provides_missing) and dead_output_key reached no tell before, so 5
# kept pieces of the fourth smoke fell to the build after sampling had stopped, and 28 of its 123 Blender tries carried
# a dead key that only a step asking for an output was told of. Each is now a gate reason with a tell (validator_
# warning:<code>, dead_output_key), soft only on a step a later step depends on (task.SOFT_IF_USED), as ctx_channel is;
# the build's filters stay as the backstop. One case stays as it was: handoff_long on a values-only step's provides
# line (hints.values_step), whatever the line's form, the user's open contract question (handoffLineMax 300 against
# the 19-20 keys hydra:1.0's values steps name): no reason, no tell, the build drops it, as before the fourth smoke's
# round for every values step (decided Nov 6: from Nov 5 only a plain list of names was, plain_names, so the same keys
# behind a 'ctx["values"]:' lead, grouped or followed by a note got the reason and a tell). No tell asks a values step
# to shorten that list, so none can loop on it. The words are ours (teacher-only); the quoted keys and step ids are
# the piece's own.
DEAD_UNASKED = {1: '{quotes} in SETTINGS_{sid} names an output, but the step asks for no saved file or render: leave '
                   'that key out, since Chimera reads only "output", and only for a step that asks for one',
                2: '{quotes} in SETTINGS_{sid} name outputs, but the step asks for no saved file or render: leave '
                   'those keys out, since Chimera reads only "output", and only for a step that asks for one'}
HANDOFF_MAX = 300  # Chimera's handoffLineMax (app/hydra_piece.go; contract.validate.HANDOFF_LINE_MAX)
PROVIDES_TELL = ('{channel} gets {quotes} from the piece, but its provides line doesn\'t name {them}: list under '
                 'provides each key a later step reads, and leave out of {channel} the ones none does')
PROVIDES_OWN_TELL = ('{quotes} in {channel}: the piece registers its own stand-in for a dependency\'s key, which its '
                     'provides line can\'t claim; keep a stand-in under a name of the piece\'s own, and register only '
                     'what this step makes')
USES_TELL = ('take nothing from a step this one doesn\'t depend on, and keep any value it needs in its own SETTINGS '
             '(the uses line names {steps}; it depends on {deps})')
USES_NONE_TELL = ('take nothing from earlier steps, since this one depends on none, and keep any value it needs in its '
                  'own SETTINGS, with none under uses (the uses line names {steps})')
LONG_TELL = 'the {line} line has {n} characters, past the {limit} Chimera warns at: '
LONG_ADVICE = {"provides": 'give only the exact names, comma-separated, with no sizes or notes',
               "provides_list": 'name only what a later step or the result uses, and register only that in ctx',
               "uses": 'give each step and only the main names taken from it, with no notes',
               "assumed": 'give each guess in a few words, and leave out what the request gave'}
_PROVIDES_WARNED = re.compile(r'^registers ctx\["(\w+)"\] key\(s\) (.+) that provides doesn\'t list$')
_CHANNEL_WARNED = re.compile(r'^registers ctx\["(\w+)"\]')
_UNDECLARED = re.compile(r"^uses names (.+?), earlier steps? it doesn't depend on \(it depends on (.+)\)$")
_LONG_WARNED = re.compile(r"^the (\w+) line has (\d+) characters")
# One item of a plain list of names: a name (dotted, quoted, backticked or ctx["values"]["k"]), maybe with one note in
# brackets after it ("collection (via ctx["collection"])", n-blender-0000-01 r2 s1's kept list)
_LIST_ITEM = re.compile(r"""[`"']?[A-Za-z_][\w.]*(?:\[[^\]]*\])*[`"']?(?:\s*\([^()]*\))?""")


def plain_names(line):
    """Whether a handoff line is a plain list of names: items cut at commas, semicolons and "and" outside brackets,
    each a name with at most one note in brackets after it (_LIST_ITEM). On the stored values steps' long provides
    lines, all 6 distinct ones of the smoke runs (331-420 characters) are; of the other 21 distinct long provides
    lines, 1 is (n-blender-0000-01 r1 s2's 21 names, 320 characters). It picks the long-line advice for a step that
    isn't a values step (LONG_ADVICE's "provides_list"); since Nov 6 it no longer decides the values steps' waiver,
    which every values step's long provides line gets (warning_faults)."""
    items, depth, cur = [], 0, ""
    for ch in line or "":
        depth += ch in "([{"
        depth -= ch in ")]}"
        if ch in ",;" and depth <= 0:
            items.append(cur)
            cur = ""
        else:
            cur += ch
    items.append(cur)
    items = [p.strip() for x in items for p in re.split(r"\s+and\s+", x) if p.strip()]
    return bool(items) and all(_LIST_ITEM.fullmatch(x) for x in items)


def _read_or_tested(tree, channel):
    """The literal keys a piece reads from ctx[channel] (contract.validate.ctx_keys' reads) or tests with in or not
    in against it (report._tested's reading): a key it reads that way and also registers is its own stand-in."""
    def channel_sub(n):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "keys" and not n.args:
            n = n.func.value
        return isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == "ctx" and \
            isinstance(n.slice, ast.Constant) and n.slice.value == channel
    tested = {n.left.value for n in ast.walk(tree) if isinstance(n, ast.Compare) and isinstance(n.left, ast.Constant)
              and isinstance(n.left.value, str) and any(isinstance(op, (ast.In, ast.NotIn)) and channel_sub(x)
                                                        for op, x in zip(n.ops, n.comparators))}
    return set(V.ctx_keys(tree, channel)[1]) | tested


def warning_faults(verdict, plan, i, code, earlier=None):
    """Chimera's validator warnings the build drops (build.WARNINGS) on a piece's verdict, as rows {"code", ...,
    "exempt", "tell"}: provides_missing ("channel", "keys", "own": every key one the piece reads or tests too, its own
    stand-in for a dependency's key, told PROVIDES_OWN_TELL), uses_undeclared ("steps", "deps"), handoff_long ("line",
    "chars"; "exempt" for a values-only step's provides line, whatever its form, the user's open question: no tell;
    decided Nov 6, where from Nov 5 only a plain list of names was exempt). The keys of a provides_missing message
    the record cut are worked out again from the code, as the validator does (a substring test on provides).
    earlier: {"sN": text} of the earlier steps' kept pieces, as the gate joins them; given, a key the piece reads and
    registers is its stand-in only when a dependency hands it on (stand_ins.dep_names) or a dependency is missing,
    else it is what this step makes (a get-or-create of its own object, which the plain tell lists: the independent
    checks, Nov 6). [] when the verdict has none."""
    sid = "s%d" % (i + 1)
    out, tree = [], None
    handoff = (verdict or {}).get("handoff") or {}
    for x in (verdict or {}).get("issues") or []:
        code_, msg = x.get("code"), x.get("message") or ""
        if x.get("level") != "warn" or code_ not in ("provides_missing", "uses_undeclared", "handoff_long"):
            continue
        row = {"code": code_, "exempt": False, "tell": None}
        if code_ == "provides_missing":
            ch = _CHANNEL_WARNED.match(msg)
            if ch is None:
                continue
            channel = ch.group(1)
            if tree is None:
                try:
                    tree = ast.parse(code or "")
                except SyntaxError:
                    tree = ast.Module(body=[], type_ignores=[])
            m = _PROVIDES_WARNED.match(msg)
            keys = m.group(2).split(", ") if m else \
                [k for k in V.ctx_keys(tree, channel)[0] if k not in (handoff.get("provides") or "")]
            own = bool(keys) and all(k in _read_or_tested(tree, channel) for k in keys)
            if own and earlier is not None:
                deps = ["s%d" % (j + 1) for j in dep_indexes(plan, i)]
                if not any(d not in earlier for d in deps):
                    names = stand_ins.dep_names([earlier[d] for d in deps if d in earlier])
                    own = all(k in names for k in keys)
            row.update(channel=channel, keys=keys, own=own,
                       tell=stand_ins.fitted(PROVIDES_OWN_TELL if own else PROVIDES_TELL, keys,
                                             channel='ctx["%s"]' % channel, them="it" if len(keys) == 1 else "them"))
        elif code_ == "uses_undeclared":
            m = _UNDECLARED.match(msg)
            if m is None:
                continue
            steps, deps = m.group(1), m.group(2)
            row.update(steps=steps.split(", "), deps=[] if deps == "nothing" else deps.split(", "))
            row["tell"] = (USES_NONE_TELL.format(steps=steps) if deps == "nothing" else
                           USES_TELL.format(steps=steps, deps=deps))
        else:
            m = _LONG_WARNED.match(msg)
            if m is None:
                continue
            line, n = m.group(1), int(m.group(2))
            value = handoff.get(line) or ""
            row.update(line=line, chars=n)
            if line == "provides" and values_step(plan, i):
                row["exempt"] = True  # the user's open question: as before the round, no reason and no tell
            else:
                advice = "provides_list" if line == "provides" and plain_names(value) else line
                row["tell"] = LONG_TELL.format(line=line, n=n, limit=HANDOFF_MAX) + \
                    LONG_ADVICE.get(advice, LONG_ADVICE["assumed"])
        if row["tell"]:
            row["tell"] = row["tell"][:FAILURE_CHARS]
        out.append(row)
    return out


def build_facts(plan, i, code, verdict, earlier=None):
    """What the build would drop step i's piece for, read from its code and verdict before any run (piece_check
    tells it whatever else fails the piece, and its reasons come last at the alone stage, after ctx_channel):
    Chimera's validator warnings (warning_faults), the dead output keys (dead_output_key with the plan step, as the
    build reads it, told DEAD_TELL when the step asks Chimera for a render or a save and DEAD_UNASKED otherwise), and
    the stand-in marker's two faults (stand_ins.check: marker_misused, silent_default), which the build never read.
    earlier: {"sN": text} of the earlier steps' kept pieces. Returns {"warnings", "dead_output", "stand_ins":
    {"marker", "silent", "missing"}, "reasons", "tell", "waived"}: reasons validator_warning:<code> (each code a
    non-exempt warning has, once), dead_output_key, marker_misused, silent_default; none at all when the piece carries
    the exempt handoff_long, a values-only step's long provides line in any form ("waived": the build drops such a
    piece whatever else, until the user decides the open question, so failing it would only cost told batches that
    can't win its example: the fourth smoke's two values steps, whose kept pieces also print the marker for
    render_device), its lines still told if something else fails it."""
    st, sid = plan["steps"][i], "s%d" % (i + 1)
    warnings = warning_faults(verdict, plan, i, code, earlier or {})
    dead = dead_output_key(code, sid, st)
    asked = asked_outputs(plan, i)
    deps = ["s%d" % (j + 1) for j in dep_indexes(plan, i)]
    found = stand_ins.check(code, deps, earlier or {}, sid=sid)
    reasons = sorted({"validator_warning:" + w["code"] for w in warnings if not w["exempt"]})
    tell = [w["tell"] for w in warnings if w["tell"]]
    if dead:
        reasons.append("dead_output_key")
        tell.append(dead_tell(sid, dead, asked=bool(asked["blend"] or asked["render"])))
    if found["marker"]:
        reasons.append("marker_misused")
    if found["silent"]:
        reasons.append("silent_default")
    tell += stand_ins.tell(found)
    waived = any(w["exempt"] for w in warnings)
    if waived:  # the build drops it for the open question's handoff_long whatever else: a told batch can't win it
        reasons = []
    return {"warnings": warnings, "dead_output": dead,
            "stand_ins": {"marker": found["marker"], "silent": found["silent"], "missing": found["missing"]},
            "reasons": reasons, "tell": list(dict.fromkeys(tell)), "waived": waived}


# A step that adds a camera of its own (camera_not_active): a making verb, at most an article and "new", up to four
# words that only describe it ("Add a perspective camera", "Add area light and camera", "Place low-angle camera"),
# then "camera" as the thing made: not "cameras", not a name or a compound ("camera_name", "camera-facing", "the
# camera's"), not a word about the camera ("camera settings", "camera track", "camera animation"). "the camera" is
# left out (it may be one another step made: "Place the camera at ..."), and so is a second or another camera, which
# needn't be the one a render uses.
_CAMERA_MAKER = (r"\b(?:add|adds|adding|create|creates|creating|insert|inserts|inserting|place|places|placing|make|"
                 r"makes|making|spawn|spawns|spawning|set\s+up|sets\s+up|setting\s+up)\s+(?:(?:a|an|one)\s+)?"
                 r"(?:new\s+)?")
_CAMERA_ASK = re.compile(_CAMERA_MAKER + r"(?P<mods>(?:[\w‐-―'-]+\s+){0,4}?)camera\b"
                         r"(?![\w‐-―'’-])", re.I)
_CAMERA_MOD_NOT = re.compile(r"^(?:the|this|that|these|those|its|their|his|her|your|our|existing|default|current|"
                             r"second|another|additional|extra|secondary|backup|alternate|alternative|other|each|every|"
                             r"all|both|two|three|four|several|multiple|%s)$" % _PLACES, re.I)
_CAMERA_NOUN = re.compile(r"\s+(?:settings?|setup|properties|property|parameters?|params?|lens(?:es)?|focal|sensor|"
                          r"positions?|locations?|rotations?|angles?|animations?|animated|paths?|tracks?|tracking|"
                          r"constraints?|rigs?|movements?|moves?|motions?|views?|data|targets?|shake|keyframes?|"
                          r"orbits?|orbiting|dolly|distance|clip(?:ping)?|type|height|fly\w*|cuts?|switch\w*|"
                          r"frames?|shots?|controls?|options?|configuration|config|presets?)\b", re.I)
# Another step that says which camera a render uses ("Makes the camera the active scene camera", "set
# scene.camera"): then the step adding the camera may leave that to it, and isn't held to it
_CAMERA_SET = re.compile(r"\b(?:active|scene(?:'s)?|render(?:ing)?)\s+camera\b|\bscene\.camera\b|"
                         r"\bcamera\s+(?:as\s+)?(?:the\s+)?active\b", re.I)
CAMERA_TELL = {
    "factory": "the step adds a camera, but after the run the scene's camera is still the one the empty start-up "
               "scene has, so a render shows that view: make the camera the piece adds the scene's camera",
    "none": "the step adds a camera, but after the run the scene has no camera set, so nothing can be rendered: make "
            "the camera the piece adds the scene's camera"}
# ctx_channel's tell line (ctx_tell): ours up to the colon, quoting the piece's own wrong keys as the thing to stop
# doing, then advice by what the piece does with them, which names only the contract's own (ctx["values"],
# ctx["objects"], SETTINGS_sN, "output"), never a key to copy. Our own words, not Chimera's Nov 4 sentence about
# ctx["values"]: a right retry that repeats the advice then repeats us, which echoed_note refuses, but none of the
# fourth smoke's would need to (measured: 63 of 63 stored variables/settings tries rewritten to ctx["values"] hold no
# run of it), and no run is shared with MODE_BLENDER. The output advice is Chimera's words (MODE_BLENDER), as
# MISSING_TELL's is.
CTX_HEAD = 'Chimera\'s ctx has only "scene", "collection", "objects" and "values", not {quotes}'
CTX_ADVICE = {"write": 'put each value a later step uses in ctx["values"] under its SETTINGS_{sid} key and list the '
                       'keys under provides',
              "read": 'take what a dependency lists under provides from ctx["values"] or ctx["objects"], with a '
                      'stand-in if it is missing',
              "output": 'put the path or render settings in SETTINGS_{sid}["output"] and Chimera does it once, after '
                        'the last step'}
CTX_QUOTES = 3
# global_ctx's line (after the fifth smoke): a function of the piece that reads a ctx it is never given; ours, sharing
# no run of 8 words with Chimera's Blender rule, whose helpers "go inside it or are named _{sid}_"
GLOBAL_CTX_TELL = ("{quotes} {verb} ctx without being given it: pass ctx in as an argument, since Chimera's join "
                   "calls build_{sid}(ctx) inside a function and the piece has no ctx outside it")
GLOBAL_CTX_QUOTES = 3
GLOBAL_CTX_FORMS = tuple(p.strip(" :,") for p in re.split(r"build_\{sid\}|\{(?:quotes|verb|sid)\}", GLOBAL_CTX_TELL)
                         if len(re.findall(r"\w+", p)) >= 5)
# The fixed wording of this round's tell lines (ours, teacher-only) for hints.echoed_note: output_missing's own part,
# up to its "but" (its advice is Chimera's words, which a reply may repeat), camera_not_active's lines whole,
# dead_tell's runs of 5 words or more between the piece's keys and the step id, and ctx_tell's: its head whole and the
# write and read advice's runs of 5 words or more between the step's SETTINGS_ and build_ names (split there, so no
# part ends in a bare "SETTINGS_" that a reply's "SETTINGS_s1" can't match), the output advice left out (Chimera's),
# then build_facts' (BUILD_TELL_FORMS: the dead keys' unasked form, the warnings' lines and the long lines' advice,
# their runs of 5 words or more between the slots and the step's SETTINGS_ name; the stand-in marker's,
# stand_ins.TELL_FORMS), then the hidden errors', global_ctx's (GLOBAL_CTX_FORMS, since the fifth smoke) and the
# geometry's (silent.TELL_FORMS, geometry.TELL_FORMS: the runs of 5 words or more between their slots), the geometry's
# last
BUILD_TELL_FORMS = tuple(p.strip(" :,.()") for t in (*DEAD_UNASKED.values(), PROVIDES_TELL, PROVIDES_OWN_TELL,
                                                     USES_TELL, USES_NONE_TELL, LONG_TELL, *LONG_ADVICE.values())
                         for p in re.split(r"SETTINGS_\{sid\}|\{\w+\}", t) if len(re.findall(r"\w+", p)) >= 5)
TELL_FORMS = tuple(MISSING_HEAD.rstrip() % w for w in MISSING_WHAT.values()) + tuple(CAMERA_TELL.values()) + \
    tuple(p.strip(" :,") for t in DEAD_TELL.values() for p in re.split(r"\{(?:quotes|sid)\}", t)
          if len(re.findall(r"\w+", p)) >= 5) + \
    tuple(p.strip(" :,") for t in (CTX_HEAD, CTX_ADVICE["write"], CTX_ADVICE["read"])
          for p in re.split(r"SETTINGS_\{sid\}|build_\{sid\}|\{(?:quotes|sid)\}", t)
          if len(re.findall(r"\w+", p)) >= 5) + BUILD_TELL_FORMS + stand_ins.TELL_FORMS + silent.TELL_FORMS + \
    GLOBAL_CTX_FORMS + geometry.TELL_FORMS


def asks_camera(plan, i):
    """The clause of step i's own title and instructions that asks it to add a camera of its own (_CAMERA_ASK), or
    None: not after a negation, an option or a deferral in its sentence (as asked_outputs reads them), not where the
    sentence lets an existing camera do ("creates a new camera (or uses an existing one named 'Camera')"), and None for
    every clause when another step's words say which camera a render uses (_CAMERA_SET). On the corpus' 301 distinct
    Blender steps it fires on 26, every clause read; the 20 clauses with "camera" and a making verb it passes over
    speak of the camera ("camera settings", "the camera", "camera tracking path"), of several or ten in a loop, of an
    existing one or a file, or are in a plan where another step sets the active camera (3 steps); "Create a new camera
    data block and object" is missed. Over the 108 stored tries that passed their gate,
    camera_not_active fires on 8, each a camera the piece made and never made the scene's (one sets it only "if
    scene.camera is None", which the factory camera never is): X47 and 7 the judge had turned down."""
    st = plan["steps"][i]
    if any(_CAMERA_SET.search(_step_text(d)) for j, d in enumerate(plan["steps"]) if j != i):
        return None
    text = (st.get("title") or "") + ".\n" + (st.get("instructions") or "")
    for sent in (x for x in _ASK_SENT.split(text) if x.strip()):
        if _ASK_OPTIONAL.search(sent) or re.search(r"\bexisting\b", sent, re.I):
            continue
        ends = [c.span() for c in _CLAUSE.finditer(sent)] + [(len(sent), len(sent))]
        start = 0
        for end, after in ends:
            clause = sent[start:end]
            for m in _CAMERA_ASK.finditer(clause):
                at = start + m.start()
                if any(_CAMERA_MOD_NOT.match(w) for w in m.group("mods").split()) or \
                        _CAMERA_NOUN.match(clause, m.end()) or _ASK_NEG.search(sent[:at]) or \
                        _ASK_DEFER_BEFORE.search(sent[:at]) or _ASK_DEFER_AFTER.search(clause[m.end():]):
                    continue
                return clause.strip()
            start = after
    return None


def camera_made(sc):
    """Whether the scene camera the measuring recorded (its "scene_camera") is one the piece made: True for any
    object but the factory camera as the factory left it (one the piece moved, turned or changed the lens of is its
    own, as own_rows reads the factory's), False for that or no camera at all, None when the run recorded none
    (an older run, or the measuring failed)."""
    if sc is _UNREAD:
        return None
    if sc is None:
        return False
    ref = FACTORY_MEASURE["Camera"]
    return not (sc.get("f") and not sc.get("cam") and all(_close(sc.get(k), ref[k]) for k in ("loc", "dir", "lens")))


def camera_fault(measures):
    """camera_not_active's fault from every version's measure: "factory" or "none" when every version that recorded
    the scene's camera shows the piece's isn't it, else None (also when none recorded it)."""
    got = [m.get("scene_camera", _UNREAD) for m in measures if m]
    made = [camera_made(sc) for sc in got]
    if not any(x is not None for x in made) or any(x for x in made):
        return None
    return "none" if all(sc is None for sc, x in zip(got, made) if x is not None) else "factory"


# ---------------------------------------------------------------- ctx keys and SETTINGS keys Chimera never reads
#
# Two ways a piece hands values on that Chimera never reads, found by the audit of the second smoke on values-only
# first steps ("Define variables and render settings", which hydra:1.0 opened 3 of its 4 new Blender seeds with, when
# the contract gave plain values no channel). Since Nov 4 it does: ctx["values"] (the user's decision on contract
# question 1). ctx_channel, a ctx key the contract doesn't have, is a gate reason since DATAGEN_FORMAT 4 (piece_check's
# alone stage, told by ctx_tell): soft on a step some later step depends on (task.SOFT_IF_USED: kept so its
# dependents keep it, with no example), hard otherwise. The build's ctx_channel filter stays as a backstop that should
# fire on no format-4 example. dead_output_key is build_facts' reason since the fourth smoke, the same way, and the
# build's filter its backstop.
CTX_CONTRACT = ("scene", "collection", "objects", "values")  # the ctx keys Chimera's join makes (hydra_assemble.go)
# A SETTINGS_sN key that names where a file goes or its format, which only SETTINGS_sN["output"] hands to Chimera
_DEAD_OUTPUT = re.compile(r"output|filepath|file_path|render_path|file_format", re.I)
# A ctx key that names an output (ctx["blend_save_path"], ctx["output"], ctx["render_dir"]): ctx_tell's output form
_CTX_OUTPUT = re.compile(_DEAD_OUTPUT.pattern + r"|path|dir|folder", re.I)
# Of those, the ones that name a place (a path, a folder, a file name's pattern), not a format or a colour mode
_DEAD_PLACE = re.compile(r"path|dir|folder|pattern|file(?!_?format)", re.I)
# A step whose own words ask to set where the render goes or in what format (dead_output_key's excuse, with no render
# or save asked of Chimera): "Set the output path to //renders/", "the output file format to OpenEXR"
_SETS_OUTPUT = re.compile(r"\b(?:output\s*(?:file\s*)?path|filepath|file\s*path|output\s+(?:image\s+)?format|"
                          r"image\s+format|file\s+format|output\s+folder|output\s+directory|output\s+to\s+\S*//)", re.I)
# A file a piece writes itself, which the contract allows (an export, a script, a table): not a render or a .blend
OWN_FILES = (".py", ".json", ".txt", ".csv", ".md", ".glb", ".gltf", ".fbx", ".obj", ".stl", ".usd", ".usda", ".usdc",
             ".usdz", ".abc", ".ply", ".dae", ".svg")
# A file that is only ever an input to a Blender script (a font, a sound): never an output's path (an image, an .exr,
# an .hdr or a .blend may be either, so only what the piece does with them tells: _loaded)
INPUT_FILES = (".ttf", ".otf", ".woff", ".woff2", ".pfb", ".wav", ".mp3", ".ogg", ".flac", ".aif", ".aiff", ".m4a")
# What loads a file into the scene: bpy.data's load()s and the import, open, append and link operators
_LOADS = ("images", "fonts", "sounds", "movieclips", "libraries", "volumes")


def _ctx_names(tree):
    """The names a piece's ctx goes by: ctx, and the first parameter of each top-level build_sN function."""
    names = {"ctx"}
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and re.fullmatch(r"build_s\d+", n.name):
            params = n.args.posonlyargs + n.args.args
            if params:
                names.add(params[0].arg)
    return names


def _ctx_uses(code):
    """(written, read): the sets of top-level ctx keys a Blender piece's code writes and reads other than
    CTX_CONTRACT's, as ctx_channel describes them (a key both written and read is in both); two empty sets when the
    code doesn't parse."""
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return set(), set()
    names, written, read = _ctx_names(tree), set(), set()

    def is_ctx(node):
        return isinstance(node, ast.Name) and node.id in names

    def key(node):
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    def dict_keys(node):
        return [key(k) for k in node.keys if k is not None] if isinstance(node, ast.Dict) else []
    for n in ast.walk(tree):
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(
            n, (ast.AnnAssign, ast.AugAssign)) else []
        for t in targets:
            for x in (t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t]):
                if isinstance(x, ast.Subscript) and is_ctx(x.value):
                    written.add(key(x.slice))
        if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load) and is_ctx(n.value):
            read.add(key(n.slice))
        if isinstance(n, ast.AugAssign) and isinstance(n.op, ast.BitOr) and is_ctx(n.target):
            written.update(dict_keys(n.value))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and is_ctx(n.func.value):
            if n.func.attr in ("setdefault", "__setitem__") and n.args:
                written.add(key(n.args[0]))
            elif n.func.attr == "get" and n.args:
                read.add(key(n.args[0]))
            elif n.func.attr == "update":
                for a in n.args:
                    written.update(dict_keys(a))
                written.update(k.arg for k in n.keywords if k.arg)
    own = set(CTX_CONTRACT) | {None}
    return written - own, read - own


def ctx_channel(code):
    """The top-level ctx keys a Blender piece's code writes or reads other than CTX_CONTRACT's (ctx["values"] is the
    contract's since Nov 4), sorted. Writes: ctx["variables"] = ..., ctx["k"] += ..., ctx.setdefault("k", ...),
    ctx.update({"k": ...}) or ctx.update(k=...), ctx |= {"k": ...}; reads: ctx["k"] as a value and ctx.get("k") (ctx
    by any name _ctx_names gives). Read, never run; a key under ctx["objects"] or ctx["values"] is the contract's, and
    "k" in ctx counts as neither. [] when the code doesn't parse. A reader teaches the other side of the same channel:
    in the values-step seeds s1 hands its values on in ctx["variables"] or ctx["settings"] (dropped here) and s2 reads
    them back (vars_ = ctx.get("variables", {})), which a contract-following s1 never fills. On the 51 Blender pieces
    of both smoke runs that passed every check, writes alone named 5 (X42 bad; X13, X38, X77, X79 weak) and reads add
    6 (X64, X27, X18 bad; X19, X67 weak; one not graded); of the 108 mechanically passing tries 9 read such a key, all
    in n-blender-0000-00, -0000-01 and -0002-00. None is graded ok; of the examples the build kept, reads drop X64,
    X27 and X18 (the others fall to earlier filters). With "values" in CTX_CONTRACT it names the same keys on every
    stored try of the three smoke runs (none used ctx["values"]): 77 of the 437 distinct ones, 37 writing and 40 only
    reading."""
    written, read = _ctx_uses(code)
    return sorted(written | read)


def ctx_channel_parts(code):
    """ctx_channel's keys split by what the piece does with them: {"written": sorted, "read": sorted, those it
    doesn't also write}, read the same way (written and read together are ctx_channel(code)): ctx_tell's input."""
    written, read = _ctx_uses(code)
    return {"written": sorted(written), "read": sorted(read - written)}


def ctx_tell(sid, written, read):
    """ctx_channel's tell line (teacher-only) for step sid's piece, from ctx_channel_parts' written and read keys, at
    most FAILURE_CHARS (240) long; None for no key. The write form when the piece writes a key that doesn't name an
    output, the output form when every key it writes does (_CTX_OUTPUT: ctx["blend_save_path"], ctx["output"]), else
    (it only reads) the read form; its first CTX_QUOTES keys are quoted, writes first, with " and more" when there are
    more. A line that would run long quotes only the first. On the 77 stored tries that fire (28 write form, 40 read,
    9 output) it is 191-227 characters."""
    keys = list(written) + [k for k in read if k not in written]
    if not keys:
        return None
    kind = ("write" if any(not _CTX_OUTPUT.search(k) for k in written) else "output") if written else "read"
    advice = CTX_ADVICE[kind].format(sid=sid)
    quotes = ", ".join("ctx[%s]" % json.dumps(k) for k in keys[:CTX_QUOTES]) + \
        (" and more" if len(keys) > CTX_QUOTES else "")
    line = CTX_HEAD.format(quotes=quotes) + ": " + advice
    if len(line) > FAILURE_CHARS:  # long keys: the first one only
        quotes = "ctx[%s]" % json.dumps(keys[0]) + (" and more" if len(keys) > 1 else "")
        line = CTX_HEAD.format(quotes=quotes) + ": " + advice
    return line[:FAILURE_CHARS]


_SCOPES = {"lambda": "a lambda", "listcomp": "a comprehension", "setcomp": "a comprehension",
           "dictcomp": "a comprehension", "genexpr": "a generator expression"}


def global_ctx(code):
    """The functions of a Blender piece that read the name ctx with no binding of their own or of a function around
    them, so Python looks for a module-level ctx: [{"function", "line"}] in source order, function the def's name with
    its class or function around it ("_s3_light", "_S3Rig.make", "build_s3.inner"; a lambda or a comprehension by
    what it is), line its def's line in the code. The alone run's tail binds ctx at module level, so the read runs
    there; in Chimera's join, where main() holds ctx, it raises NameError (JOINED_SHOWS). Python's own scopes decide
    (symtable, on the code with its main guards blanked, as Chimera drops them): a parameter, an assignment, a for,
    with, except, import or walrus target is the function's own, a name of an enclosing function's (build_sN's ctx)
    is a closure's, and a global declared and assigned in some function, or a module-level ctx outside a main guard
    (the validator's top_level_code refuses it anyway), binds it, and then nothing is reported. [] for code that
    doesn't parse (the lint says so). Measured (Nov 6) on every stored Blender try of the five smoke runs: 9 tries of
    5 steps (smoke4 4, smoke5 5, among them the 4 the fifth smoke's audit named), none kept, every one confirmed by a
    main()-style join in both Blenders; on the eval's 990 distinct stored Blender reply blocks and its own pieces,
    none."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    lines = code.split("\n")
    for n in tree.body:
        if V.is_main_guard(n):
            for k in range(n.lineno - 1, min(n.end_lineno, len(lines))):
                lines[k] = ""
    try:
        top = symtable.symtable("\n".join(lines), "piece.py", "exec")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    if "ctx" in top.get_identifiers() and (top.lookup("ctx").is_assigned() or top.lookup("ctx").is_imported()):
        return []
    found, todo = [], [(t, ()) for t in top.get_children()]
    while todo:
        t, path = todo.pop(0)
        name = _SCOPES.get(t.get_name(), t.get_name())
        here = path + (name,)
        if "ctx" in t.get_identifiers():
            sym = t.lookup("ctx")
            if sym.is_declared_global() and sym.is_assigned():
                return []
            if sym.is_referenced() and sym.is_global() and t.get_type() != "module":
                found.append({"function": ".".join(here), "line": t.get_lineno()})
        todo.extend((c, here) for c in t.get_children())
    return sorted(found, key=lambda f: (f["line"], f["function"]))


def global_ctx_tell(sid, reads):
    """global_ctx's tell line (teacher-only) for step sid's piece: the first GLOBAL_CTX_QUOTES functions it names
    (their outermost def's name, each once), with " and more" when there are more; None for no read."""
    names = list(dict.fromkeys(r["function"].split(".")[0] for r in reads or ()))
    if not names:
        return None
    quotes = ", ".join(names[:GLOBAL_CTX_QUOTES]) + (" and more" if len(names) > GLOBAL_CTX_QUOTES else "")
    return GLOBAL_CTX_TELL.format(quotes=quotes, verb="reads" if len(names) == 1 else "read", sid=sid)[:TELL_KEEP[1]]


def _reads_key(tree, key):
    """The code reads key from a dict itself: d["key"] as a value or d.get("key"), d by any name (a piece often reads
    its settings as s = SETTINGS_s5)."""
    for n in ast.walk(tree):
        if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load) and isinstance(n.slice, ast.Constant) and \
                n.slice.value == key:
            return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args and \
                isinstance(n.args[0], ast.Constant) and n.args[0].value == key:
            return True
    return False


def _dotted(node):
    """"bpy.data.images.load" for that attribute chain on a name, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return ".".join([node.id] + parts[::-1]) if isinstance(node, ast.Name) else None


def _loader(call):
    """Whether call loads a file into the scene (_LOADS' load(), an import, open, append or link operator)."""
    name = (_dotted(call.func) or "").split(".")
    if len(name) >= 3 and name[-1] == "load" and name[-2] in _LOADS:
        return True
    if len(name) == 4 and name[:2] == ["bpy", "ops"]:
        group, op = name[2], name[3]
        return group.startswith("import") or op.startswith("import") or op.endswith("_import") or \
            (group == "image" and op == "open") or (group == "wm" and op in ("append", "link"))
    return False


def _bound_from(scope, has):
    """The names scope binds (an assignment anywhere in it) to an expression of which has(node) holds."""
    return {t.id for a in ast.walk(scope) if isinstance(a, (ast.Assign, ast.AnnAssign)) and a.value is not None and
            has(a.value) for t in (a.targets if isinstance(a, ast.Assign) else [a.target]) if isinstance(t, ast.Name)}


def _reaches_loader(scope, has):
    """Whether a loader call (_loader) in scope gets an argument of which has(node) holds, or a name scope binds to
    one."""
    names = _bound_from(scope, has)
    for n in ast.walk(scope):
        if isinstance(n, ast.Call) and _loader(n):
            for a in list(n.args) + [k.value for k in n.keywords]:
                if has(a) or any(isinstance(x, ast.Name) and x.id in names for x in ast.walk(a)):
                    return True
    return False


def _loaded(tree, key):
    """Whether the piece hands the value it keeps under key (d["key"] or d.get("key"), or a name bound to an
    expression of one) to a loader (_loader): then the key is a file it reads in, such as a texture, an HDRI or a font,
    not an output's path (the independent checks, Nov 6: "shade_texture_filepath" put in bpy.data.images.load). Also
    through a function of the piece whose parameter reaches a loader (the second checks, Nov 6: def _s3_image(key):
    ... images.load(bpy.path.abspath(SETTINGS_s3[key])), called with the key, or with the value it keeps there)."""
    def reads(n):
        return any(isinstance(x, ast.Subscript) and isinstance(x.slice, ast.Constant) and x.slice.value == key or
                   isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr == "get" and x.args
                   and isinstance(x.args[0], ast.Constant) and x.args[0].value == key for x in ast.walk(n))
    if _reaches_loader(tree, reads):
        return True
    names = _bound_from(tree, reads)
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = [a.arg for a in fn.args.posonlyargs + fn.args.args]
        for k, p in enumerate(params):
            if not _reaches_loader(fn, lambda n, p=p: any(isinstance(x, ast.Name) and x.id == p for x in ast.walk(n))):
                continue
            for c in ast.walk(tree):
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == fn.name:
                    v = c.args[k] if k < len(c.args) else next((w.value for w in c.keywords if w.arg == p), None)
                    if v is not None and (isinstance(v, ast.Constant) and v.value == key or reads(v) or
                                          any(isinstance(x, ast.Name) and x.id in names for x in ast.walk(v))):
                        return True
    return False


def sets_output(step):
    """Whether a step asks Chimera for no render and no save (asked_outputs) but its own words ask to set where the
    render goes or its format (_SETS_OUTPUT): "Set the output filepath to //forest_clearing and image format to PNG"."""
    asked = asked_outputs({"steps": [step]}, 0)
    return not asked["blend"] and not asked["render"] and \
        _SETS_OUTPUT.search((step.get("title") or "") + "\n" + (step.get("instructions") or "")) is not None


def dead_output_key(code, sid, step=None):
    """The keys of a piece's SETTINGS_<sid> (the first top-level SETTINGS_<sid> = {...}, as Go's hasOutput reads it)
    that name an output's path or format (_DEAD_OUTPUT: "output_path", "output_format", "render_filepath") other than
    "output" and that nothing uses, sorted: Chimera hands only SETTINGS_<sid>["output"] to _chimera_output, so a path
    kept under another key is saved and rendered by nobody. Its top-level keys only (inside "output" a "filepath" is
    Chimera's to read). A key the piece reads itself is still dead when it names a place (_DEAD_PLACE: a path, a
    folder, a pattern), unless its literal value is a file of another kind than a render or a .blend (the piece's own
    export or script, which the contract allows: "//room.py"), or step (the plan step, when given) asks Chimera for
    nothing and its words ask to set the output path or format (sets_output): then applying it to scene.render is what
    the step says. A format or colour mode the piece reads ("output_format": "PNG" put in image_settings) is a setting
    it applies, not a dead key; unread, it is. Nor is an input file: a key whose literal value is a font or a sound
    (INPUT_FILES), or one the piece hands to a loader (_loaded: images.load, an import operator; also through a helper
    of its own the key or its value is passed to, since the second checks), which the step may well ask for ("the
    linen texture at //textures/linen.png"; the independent checks, Nov 6). [] when there is no such literal or the
    code doesn't parse.

    Of both smoke runs' 355 distinct Blender tries it names 50 (80 when every such key counted, 61 of those the
    piece's own reads), of the 51 that passed every check 6, each graded firing as before (X20, X40, X58 bad: a render
    asked, or unasked placeholders; X23, X65, X77 weak), none graded ok. The step excuse spares the four steps that say
    "set the output path to ..." with no render asked (n-blender-0001-00 s6, n-blender-0002-02 s5, n-blender-0000-01
    r1 s3 in both runs), of whose tries one passed: n-blender-0002-02 s5's kept candidate 5 (judged ok; the first
    run's version_leak drops it anyway); the format and export rules spare only tries that also hold a dead path, or
    never passed (output_script_path, "//modern_living_room.py", in a step that saves a script)."""
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return []
    for n in tree.body:
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and _assigned(n) == ["SETTINGS_" + sid] and \
                isinstance(n.value, ast.Dict):
            excused = step is not None and sets_output(step)
            out = set()
            for k, v in zip(n.value.keys, n.value.values):
                if not isinstance(k, ast.Constant) or not isinstance(k.value, str) or k.value == "output" or \
                        not _DEAD_OUTPUT.search(k.value):
                    continue
                if isinstance(v, ast.Constant) and isinstance(v.value, str) and \
                        os.path.splitext(v.value)[1].lower() in INPUT_FILES or _loaded(tree, k.value):
                    continue
                if _reads_key(tree, k.value):
                    other = isinstance(v, ast.Constant) and isinstance(v.value, str) and \
                        os.path.splitext(v.value)[1].lower() in OWN_FILES
                    if not _DEAD_PLACE.search(k.value) or other or excused:
                        continue
                out.add(k.value)
            return sorted(out)
    return []


def _close(a, b, tol=0.011):
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= max(tol, 0.001 * abs(b))
    return a == b


def own_rows(measure):
    """The measured objects that are the piece's: all but the factory's untouched ones (a factory object it moved,
    resized, turned or changed the light of counts as its own)."""
    out = []
    for r in (measure or {}).get("objects") or []:
        ref = FACTORY_MEASURE.get(r.get("n")) if r.get("f") else None
        if ref is None or any(k in r and not _close(r[k], ref.get(k)) for k in _FACTORY_KEYS):
            out.append(r)
    return out


def _fits(sides, size):
    """Whether a measured size fits the sides asked (None: a side the step names but doesn't give): some way of
    pairing the given sides with distinct measured ones, each within SIZE_TOLERANCE."""
    given = [s for s in sides if s is not None]
    return any(all(abs(m - w) <= max(SIZE_TOLERANCE[0] * w, SIZE_TOLERANCE[1]) for m, w in zip(p, given))
               for p in itertools.permutations(size, len(given)))


def _off(sides, size):
    """How far a measured size is from the sides asked: the closest pairing's sum of |log(measured / asked)|, and
    its ratios."""
    given = [s for s in sides if s is not None]
    best = (math.inf, [])
    for p in itertools.permutations(size, len(given)):
        ratios = [max(m, 1e-4) / max(w, 1e-4) for m, w in zip(p, given)]
        d = sum(abs(math.log(r)) for r in ratios)
        if d < best[0]:
            best = (d, ratios)
    return best


def _candidates(measure):
    """What can stand for one sized thing: each of the piece's objects with a size (and, with modifiers, its own
    mesh's: in the alone run a stand-in for a dependency's node group can leave nothing to measure), and the parts
    that make one thing (an object with its children, objects named after one word): [(label, size, words)]."""
    out = []
    for r in own_rows(measure):
        if r.get("size"):
            out.append((r["n"], r["size"], _words(r["n"])))
        if r.get("base"):
            out.append((r["n"] + " without its modifiers", r["base"], _words(r["n"])))
    for g in (measure or {}).get("groups") or []:
        label = "%s with its children" % g["n"] if g.get("g") == "under" else \
            "the %d objects named after %s" % (g.get("of") or 0, g["n"])
        out.append((label, g["size"], _words(g["n"])))
    return out


_PLAIN_WORDS = {"a", "an", "the", "with", "and", "of", "in", "on", "at", "by", "for", "to", "its", "each", "one",
                "two", "three", "four", "new", "box", "cube", "plane", "mesh", "object", "objects", "dim", "dims",
                "dimension", "dimensions", "size", "sized", "length", "width", "depth", "height", "create", "creates",
                "add", "adds", "make", "makes", "build", "builds", "using", "named", "rectangular", "simple", "built",
                "chimera", "set", "sets", "measuring", "measures"}


def _words(text):
    """The words of a name or phrase that can tell one thing from another (CamelCase and snake_case split, lower case,
    plain words left out)."""
    parts = re.split(r"[\W_]+|(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", text or "")
    return {w.lower() for w in parts if len(w) >= 3 and not w.isdigit() and w.lower() not in _PLAIN_WORDS}


def size_states(asked, measure):
    """For each size asked, in order: ("fits", None) when an object or group of parts measures it within
    SIZE_TOLERANCE, ("fault", tell line) when none does, or ("unmeasured", why) when this measure can't say:
    "other_values" (marked so before: the values step's piece sets other values than its words, settings_sides), or
    "cut" (the measuring left objects out, MEASURE_KEEP or its budget, and none it kept is named like the thing: the
    thing may be among those left out; or it left groups of parts out and none it kept is named like the thing). All
    "unmeasured" ("nothing") when the run built nothing with a size or works in other units than metres. The line
    names the thing and where its size comes from ("no object measures 2.2 × 0.9 × 0.8 m for the sofa (its size from
    s1)"), with the variable a "?" side stands for, then the nearest measured: never the step's own phrase, which the
    echo check (hints) would then find in a next try that does the step right."""
    cands = _candidates(measure)
    if not cands or (measure or {}).get("unit_scale"):
        return [("unmeasured", "nothing")] * len(asked)
    cut = (measure or {}).get("cut") or {}
    groups = [_words(g["n"]) for g in (measure or {}).get("groups") or []]
    out = []
    for a in asked:
        if a.get("unmeasured"):
            out.append(("unmeasured", a["unmeasured"]))
            continue
        if any(_fits(a["sides"], size) for _, size, _ in cands):
            out.append(("fits", None))
            continue
        want = _words(a.get("thing") or "") or set(a.get("words") or ())
        if (cut.get("objects") and not any(c[2] & want for c in cands)) or \
                (cut.get("groups") and not any(g & want for g in groups)):
            out.append(("unmeasured", "cut"))
            continue
        named = [c for c in cands if c[2] & set(a.get("words") or ())] or cands  # the nearest of those named for it
        _, ratios, name, size = min(_off(a["sides"], s) + (n, s) for n, s, _ in named)
        line = "no object measures %s" % _sides(a["sides"])
        if a.get("thing"):
            line += " for the " + a["thing"].replace("_", " ")
        line += " (its size from %s" % ("the step" if a.get("source", "step") == "step" else a["source"])
        given = [v for v in a.get("vars") or [] if v]
        if None in a["sides"] and given:
            line += ", ? being %s" % ", ".join(given)
        line += "); the nearest is %s at %s" % (name, _sides(size))
        if ratios and all(0.45 <= r <= 0.55 for r in ratios):
            line += ", half the size asked on every side"
        elif ratios and all(1.8 <= r <= 2.2 for r in ratios):
            line += ", twice the size asked on every side"
        out.append(("fault", line))
    return out


def size_faults(asked, measure):
    """[(index into asked, tell line)] for each size asked that no object or group of parts measures within
    SIZE_TOLERANCE, of those this measure can measure (size_states): [] when the run built nothing with a size or
    works in other units than metres."""
    return [(k, line) for k, (state, line) in enumerate(size_states(asked, measure)) if state == "fault"]


# A thing's three sides in one value of a values piece's settings: "bench_size": (1.8, 0.45, 0.5)
_SIZE_KEY = re.compile(r"([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*?)_(?:size|sizes|dim|dims|dimension|dimensions)$")
_SIDE_NAME = re.compile(r"([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*?)_(length|width|depth|height|"
                        r"(?:size|dim|dims|dimension|dimensions)_[xyz])$")
_BARE_SIDE = re.compile(r"(?:length|width|depth|height|(?:size|dim|dims|dimension|dimensions)_[xyz]|size|sizes|dims?|"
                        r"dimensions?)$")


def _number(node):
    """A literal int or float (a bool isn't one), or None."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        n = _number(node.operand)
        return None if n is None else (-n if isinstance(node.op, ast.USub) else n)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    return None


def settings_sides(code, sid):
    """The sizes a values step's piece really sets, read from its SETTINGS_<sid> literal (parsed, never run): {thing:
    [x, y, z] in metres, None for a side it doesn't set}, from three sides by name ("bench_length": 1.8, ...;
    "bench": {"length": 1.8, ...}; depth or size_y is the second side, as named_triples reads them) or three numbers
    in one ("bench_size": (1.8, 0.45, 0.5)). Only literal numbers count (math.radians(15) is no value); a nested dict
    names a side by its key with the key above it. {} when the literal isn't there or doesn't parse."""
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return {}
    node = next((n.value for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign))
                 and _assigned(n) == ["SETTINGS_" + sid] and isinstance(n.value, ast.Dict)), None)
    out = {}

    def put(thing, axis, value):
        out.setdefault(thing.lower(), [None, None, None])
        if out[thing.lower()][axis] is None:
            out[thing.lower()][axis] = value

    def walk(d, above):
        for k, v in zip(d.keys, d.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            key = k.value.strip()
            name = above + "_" + key if above and _BARE_SIDE.fullmatch(key.lower()) else key
            if isinstance(v, ast.Dict):
                walk(v, key)
                continue
            n = _number(v)
            m = _SIDE_NAME.fullmatch(name.lower())
            if n is not None and m:
                side = m.group(2)
                put(m.group(1), {"length": 0, "width": 1, "depth": 1, "height": 2}.get(side, "xyz".find(side[-1])), n)
                continue
            m = _SIZE_KEY.fullmatch(name.lower())
            if m and isinstance(v, (ast.Tuple, ast.List)) and len(v.elts) == 3:
                ns = [_number(e) for e in v.elts]
                if None not in ns:
                    for axis, x in enumerate(ns):
                        put(m.group(1), axis, x)
    if node is not None:
        walk(node, "")
    return out


def _held(a, codes):
    """Size a from a values step (source "sN"), held to what that step's piece in the join really sets
    (settings_sides of codes[sN], the join's code by worker name): its sides when it sets all three and they fit the
    words within SIZE_TOLERANCE, the words' when it sets some that fit and none that don't, or the words' when it sets
    none (nothing says otherwise). When a side it sets is further from the words, the size is "unmeasured":
    "other_values", with the piece's as "piece_sides": a dependent that reads them and one that writes the words in
    can't be told apart, so neither is failed."""
    code = (codes or {}).get(a.get("source"))
    if code is None or a.get("source") == "step":
        return a
    got = settings_sides(code, a["source"]).get((a.get("thing") or "").lower())
    if not got:
        return a
    want = a["sides"]
    if None not in got:
        if _fits(want, got):
            return dict(a, sides=got, piece_sides=got)
    elif all(g is None or w is None or abs(g - w) <= max(SIZE_TOLERANCE[0] * w, SIZE_TOLERANCE[1])
             for g, w in zip(got, want)):
        return dict(a, piece_sides=got)
    return dict(a, piece_sides=got, unmeasured="other_values")


def aim_faults(asked, measure):
    """[(index into asked, tell line)] for each light or camera the step says points down when none of the piece's
    of that kind does (its direction's z is above aim_z: AIM_DOWN_Z, or what an angle the step gives needs): a light
    emits, and a camera looks, along its local -Z. Only those with the word the step uses (ceiling, overhead) in their
    names when some have it; nothing when the piece made none of that kind."""
    rows = own_rows(measure)
    out = []
    for k, a in enumerate(asked):
        if a["what"] == "camera":
            pool = [r for r in rows if r["t"] == "CAMERA" and r.get("dir")]
        else:
            pool = [r for r in rows if r["t"] == "LIGHT" and r.get("dir") and r.get("light") in AIMED
                    and (a["type"] is None or r.get("light") == a["type"])]
        if a.get("word") and any(a["word"] in r["n"].lower() for r in pool):
            pool = [r for r in pool if a["word"] in r["n"].lower()]
        z = aim_z(a)
        if not pool or any(r["dir"][2] <= z for r in pool):
            continue
        r = max(pool, key=lambda r: r["dir"][2])
        what = " ".join(x for x in (a.get("word"), (a["type"] or "").lower(), a["what"]) if x)
        verb = "looks" if a["what"] == "camera" else "emits"
        down = "down" if a.get("angle") is None else "%s degrees down" % _num(a["angle"])
        line = "the step says the %s points %s, but %s %s along (%s)%s" % (
            what, down, r["n"], verb, ", ".join(_num(x) for x in r["dir"]),
            ", upward" if r["dir"][2] > 0.5 else ", not %s (z should be at most %s)" % (
                "down" if a.get("angle") is None else "that far down", _num(z)))
        out.append((k, line))
    return out


TELL_KEEP = (8, 300)  # tell lines per piece, characters per line


def _hard(reasons):
    """The reasons that stop piece_check before the join: all but SOFT_GATE's (SOFT_MEASURED, ctx_channel,
    attr_miss and FACT_REASONS, validator_warning:<code> by its prefix) and JOINED_SHOWS' (global_ctx, which the
    joined run shows as a crash)."""
    return [r for r in reasons if r not in SOFT_GATE and r not in JOINED_SHOWS and r.split(":")[0] not in FACT_REASONS]


def tell_lines(out):
    """What the next try's teacher is told about why a checked piece failed (teacher-only, never in a stored request
    or a target): a plain line for each reason where one helps, [] when it passed. Lint findings and the crash
    aren't repeated here (the notes get them as they are); a run that failed without a crash in this piece says
    what Blender said. ctx_tell's line (a ctx key the contract doesn't have) is told whatever else failed, after the
    reasons' lines and before the measured faults, and so are global_ctx's (a ctx the piece is never given, since the
    fifth smoke) and build_facts' lines after it (facts_tell: what the build drops, the stand-in marker's faults).
    Text quoted from Blender or Chimera has its Blender versions in words (hints.unversioned): the teacher's notes
    never carry them, and a reply that repeats one is a leak (hints.version_leak)."""
    if out.get("ok"):
        return []
    lines = []
    for r in out.get("reasons") or []:
        if r.startswith(("alone_strict:", "joined_strict:")) and not out.get("crash"):
            alone = r.startswith("alone")
            s = (out.get("alone" if alone else "joined") or {}).get(r.split(":", 1)[1]) or {}
            why = unversioned(s.get("error") or s.get("exception") or s.get("why") or "")
            lines.append(("run alone" if alone else "joined after the earlier steps' pieces") +
                         (", it failed: " + why if why else ", it didn't run cleanly"))
        elif r == "no_code":
            lines.append("the reply has no Blender code block Chimera can run")
        elif r == "provides_missing":
            lines.append("the handoff's provides names %s, but the run made nothing by those names (no object, "
                         "material, collection, node group, ctx[\"objects\"] or ctx[\"values\"] key)" %
                         ", ".join(out.get("provides_missing") or []))
        elif r in ("no_probe", "joined_no_probe"):
            lines.append("the script stopped before its end (a render, a quit or an exit), so what it built "
                         "couldn't be checked")
        elif r in ("dupes", "joined_dupes"):
            lines.append("Blender renamed %s: a name was made twice, or was already taken" %
                         ", ".join(out.get("dupes") or []))
        elif r == "join_fallback":
            why = "; ".join(unversioned(str(x)) for x in out.get("join_reasons") or [])
            lines.append("Chimera couldn't join it with the earlier steps' pieces" + (": " + why if why else ""))
        elif r == "join_no_script":
            lines.append("joined with the earlier steps' pieces, it gave no Blender script")
        elif r.startswith("seam:"):
            for sm in out.get("seams") or []:
                if sm.get("code") == r[5:] and sm.get("message"):
                    lines.append("joined with the earlier steps' pieces: " + unversioned(sm["message"]))
        elif r == "stand_in":
            keys = ", ".join(out.get("stand_in_keys") or []) or "no key"
            lines.append("joined, it printed the stand-in line (%s) where no stand-in is due: that line is only for "
                         "a dependency's ctx[\"objects\"] or ctx[\"values\"] key that is missing; a missing file gets "
                         "a fallback without it" % keys)
        elif r == "removes_earlier":
            lines.append("after it ran, what %s provides was gone: it removed or renamed something it didn't "
                         "create" % ", ".join(out.get("removed") or []))
    if out.get("ctx_tell"):
        lines.append(out["ctx_tell"])
    if out.get("global_ctx_tell"):
        lines.append(out["global_ctx_tell"])
    lines += out.get("facts_tell") or []
    lines += (out.get("measured") or {}).get("faults") or []
    return [l[:TELL_KEEP[1]] for l in dict.fromkeys(lines)][:TELL_KEEP[0]]


def _summary(run, v):
    """One version of a run, briefly: the strict verdict that counts and why not."""
    c, p = run["check"].get(v) or {}, run["probe"].get(v) or {}
    strict = blender_run.counted_strict(c, p)
    why = ""
    if not strict:
        why = c.get("problem") or p.get("problem") or c.get("strict_why") or \
            ("the direct run printed: " + p["bad_lines"][0][:200] if p.get("bad_lines") else
             "the direct run exited %s" % p.get("exit") if p.get("exit") != 0 else
             "the direct run was in Blender %s" % p.get("blender") if p.get("version_ok") is False else "")
    return {"strict": strict, "why": why, "outcome": c.get("outcome"), "line": c.get("line"),
            "source": c.get("source"), "error": c.get("error"), "exit": p.get("exit"),
            "exception": p.get("exception") or "", "stand_in": bool(p.get("stand_in")), "dupes": p.get("dupes") or [],
            "ctx_keys": p.get("ctx_live") if p.get("ctx_live") is not None else p.get("ctx_keys"),
            "ctx_dead": p.get("ctx_dead") or [], "seconds": round((c.get("wall_s") or 0) + (p.get("seconds") or 0), 2)}


# ---------------------------------------------------------------- the runs

class GateBlender(blender_run.Blender):
    """runner.blender_run.Blender for data generation: Chimera's check goes through datagen.chimera (look off, its
    env), the eval's probe is a no-op (eval/ is never read), the direct run adds the names epilogue and keeps the
    scene the tools probe saw and the stand-ins' keys, runs under the watchdog (_watched), and every Blender process
    waits for the semaphore."""

    def __init__(self, chimera, versions, work, timeout, check_timeout, sem):
        # Not Blender.__init__: it reads eval/scene_probe.py, which data generation never touches.
        self.chimera = chimera.binary
        self.ch = chimera
        self.versions = dict(versions)
        for v, path in self.versions.items():
            why = blenders.check_path(path)
            if why:
                raise RuntimeError(f"Blender {v}: {why}")
        self.work = work
        self.timeout = timeout
        self.check_timeout = check_timeout
        self.sandbox = shutil.which("sandbox-exec") is not None
        self.probe_src = NO_PROBE
        self.sem = sem
        self.processes = 0
        self._count_lock = threading.Lock()

    def _started(self):
        with self._count_lock:
            self.processes += 1

    def check(self, text, name="script.py", goal=None):
        """Chimera's check of a script in every version (one after another; run() does them in parallel)."""
        return {v: self.check_one(text, v, b, goal=goal, name=name) for v, b in self.versions.items()}

    def check_one(self, text, version, binary, goal=None, name="script.py"):
        """Chimera's check of text in one Blender version, in blender_run.Blender.check's record shape plus the
        check's critique, exit and stated runner. Never raises for the run itself (a failure is a "problem")."""
        with self.sem:
            self._started()
            t0 = time.monotonic()
            d = tempfile.mkdtemp(prefix=f"dg-check-{version}-", dir=self.work)
            try:
                path = os.path.join(d, name)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                rec = self.ch.check_result(path, goal=goal, work_dir=d, blender=binary, timeout=self.check_timeout)
            except ChimeraError as e:
                return {"outcome": None, "strict": False, "strict_why": "", "version_ok": False,
                        "problem": str(e)[:300],
                        "wall_s": round(time.monotonic() - t0, 2), "bad_lines": [], "output_tail": "",
                        "stand_in_tail": False}
            finally:
                shutil.rmtree(d, ignore_errors=True)
        check = rec.get("check") or {}
        stated = rec.get("stated")
        version_ok = stated == f"Blender {version}" and check.get("runner") == f"Blender {version}"
        strict, why = blender_check.strict_verdict(rec.get("exit"), check, version_ok)
        out = {k: check.get(k) for k in ("outcome", "line", "source", "error", "seconds", "runner", "summary")}
        out.update(strict=strict, strict_why=why, version_ok=version_ok, wall_s=round(time.monotonic() - t0, 2),
                   bad_lines=blender_check.bad_lines(check.get("output")), exit=rec.get("exit"), stated=stated,
                   critique=rec.get("critique") or "", output_tail=(check.get("output") or "")[-600:],
                   stand_in_tail=has_stand_in(check.get("output")))
        if not version_ok:
            out["problem"] = (f"asked for Blender {version}, but Chimera said {stated or 'nothing'} "
                              f"and its JSON says {check.get('runner') or 'nothing'}")
        return out

    def _probe_one(self, script, binary, version=None):
        """blender_run.Blender._probe_one with the names epilogue, the silent prelude and report (datagen/silent.py:
        "silent", absent when the script stopped before its end), the tools probe's scene kept, and the semaphore."""
        with self.sem:
            self._started()
            return self._direct(script, binary, version)

    def _direct(self, script, binary, version):
        d = tempfile.mkdtemp(prefix="dg-probe-", dir=self.work)
        t0 = time.monotonic()
        try:
            path, probe_path = os.path.join(d, "script.py"), os.path.join(d, "scene_probe.py")
            with open(probe_path, "w", encoding="utf-8") as f:
                f.write(self.probe_src)
            # The silent report right after the script, so nothing after it is watched; its prelude watches only code
            # in path (the same string --python gets: Python's co_filename) whose first line is the script's own
            with open(path, "w", encoding="utf-8") as f:
                probed = blender_run.probe_script(script.rstrip("\n") + "\n" + silent.EPILOGUE,
                                                  os.path.realpath(probe_path))
                f.write(probed.rstrip("\n") + "\n" + NAMES_EPILOGUE + MEASURE_EPILOGUE + GEOM_EPILOGUE)
            cmd = [binary, "-b", "--factory-startup", "--python-exit-code", "1", "--python-expr", STARTED_EXPR,
                   "--python-expr", blender_run.stop_at_render(os.path.realpath(probe_path)),
                   "--python-expr", silent.PRELUDE % {"path": path, "maxline": len(script.split("\n"))},
                   "--python", path, "--"]
            if self.sandbox:
                cmd = ["sandbox-exec", "-p", blender_run.sandbox_profile(d, binary)] + cmd
            env = {"HOME": d, "TMPDIR": d, "TMP": d, "TEMP": d, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                   "LANG": "en_US.UTF-8", "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
            code, output = _watched(cmd, d, env, self.timeout)
            if code is None:
                output += f"\n(timed out after {self.timeout:.0f} s)"
            tools = scene_probe.parse(output)
            bad = blender_check.bad_lines(blender_run.own_output(output))
            started = _started(output)
            ran = blender_run.blender_version(output) or started or (tools or {}).get("blender")
            out = {"exit": code, "strict_full": code == 0 and not bad, "bad_lines": bad[:5], "probe": None,
                   "blender": ran, "version_ok": None if (version is None or ran is None) else ran == version,
                   "stand_in": has_stand_in(output), "stand_in_keys": stand_in_keys(output),
                   "exception": blender_run._last_exception(output),
                   "stopped_at_render": blender_run.WM_MARK + " stopped at the render" in output,
                   "sandboxed": self.sandbox, "seconds": round(time.monotonic() - t0, 2), "output_tail": output[-600:]}
            if started is None:  # not the script's doing: never cached (_problems), never a pass
                first = next((l.strip() for l in output.split("\n") if l.strip()), "no output")
                out["strict_full"] = False
                out["problem"] = (f"the direct run never got to Blender's Python (exit {code}"
                                  f"{', no Blender header' if ran is None else ''}): {first}")[:300]
            if tools is not None and "probe_failed" not in tools:
                out["ctx_keys"] = (tools.get("ctx") or {}).get("keys")
                out["names"] = [o["name"] for o in tools.get("objects") or []] + list(tools.get("materials") or []) + \
                    list(tools.get("collections") or [])
                out["dupes"] = tools.get("dupes") or []
                out["scene"] = {"objects": [{"name": o["name"], "type": o["type"], "data": o["data"]}
                                            for o in tools.get("objects") or []],
                                "materials": list(tools.get("materials") or []),
                                "collections": list(tools.get("collections") or []),
                                "world": tools.get("world"), "engine": tools.get("engine")}
            elif tools is not None:
                out["probe_failed"] = tools["probe_failed"]
            names = _names_line(output)
            if names is not None and "failed" not in names:
                ids = [str(x) for x in names.get("ids") or []]
                ours = [x for x in ids if x.startswith("chimera_")]
                rest = [x for x in ids if not x.startswith("chimera_")]
                out["ids"] = sorted(set(ours[:IDS_KEEP[0]] + rest[:IDS_KEEP[1]]))
                if len(ours) > IDS_KEEP[0] or len(rest) > IDS_KEEP[1]:
                    out["ids_cut"] = max(0, len(ours) - IDS_KEEP[0]) + max(0, len(rest) - IDS_KEEP[1])
                if names.get("ctx") is not None:
                    out["ctx_live"] = names["ctx"].get("live") or []
                    out["ctx_dead"] = names["ctx"].get("dead") or []
                    out["ctx_values"] = (names["ctx"].get("values") or [])[:VALUES_KEEP]
            measure = _marked_line(output, MEASURE_MARK)
            if measure is not None and "failed" in measure:
                out["measure_failed"] = str(measure["failed"])[:300]
            elif measure is not None:
                out["measure"] = measure
            hidden = _marked_line(output, silent.SILENT_MARK)
            if hidden is not None:  # none when the script stopped first (a render, a quit, a crash): nothing judged
                out["silent"] = hidden
            geom = _marked_line(output, GEOM_MARK)
            if geom is not None:  # the same; "failed" in it when it couldn't measure (geometry judges neither)
                out["geom"] = geom
            return out
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def run(self, script):
        """Both runs in every version, the four Blender processes in parallel (each waits for the semaphore):
        {"check": {v: check record}, "probe": {v: direct run record}}."""
        jobs = [("check", v, b) for v, b in self.versions.items()] + [("probe", v, b) for v, b in self.versions.items()]

        def one(job):
            kind, v, b = job
            try:
                return self.check_one(script, v, b) if kind == "check" else self._probe_one(script, b, v)
            except Exception as e:  # noqa: BLE001  (a tool problem, recorded, never cached)
                return {"problem": f"{type(e).__name__}: {e}"[:300], "strict": False, "strict_full": False,
                        "version_ok": False}
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            results = list(pool.map(one, jobs))
        out = {"check": {}, "probe": {}}
        for (kind, v, _), r in zip(jobs, results):
            out[kind][v] = r
        return out


def _watched(cmd, cwd, env, timeout):
    """cmd under pysandbox's watchdog (Chimera's), in a session of its own, its whole output read (the probes' lines
    come last, so none is cut): (exit, output), exit None when it timed out. The watchdog's standard input is the
    read end of a pipe only this process holds: when this process goes away, even by kill -9, or the run times out,
    the watchdog kills Blender by its pid (a script that left the group too), then the group; the group is killed
    here as well, as a backstop."""
    alive_r, alive_w = os.pipe()  # not inheritable: only this process holds alive_w
    rd, wr = os.pipe()
    try:
        p = subprocess.Popen(["/bin/sh", "-c", pysandbox.WATCHDOG, "wm-blender", os.devnull] + cmd, cwd=cwd, env=env,
                             stdin=alive_r, stdout=wr, stderr=wr, start_new_session=True)
    except OSError:
        for fd in (alive_w, rd):
            os.close(fd)
        raise
    finally:
        os.close(alive_r)
        os.close(wr)
    chunks = []

    def read():
        try:
            while True:
                b = os.read(rd, 65536)
                if not b:
                    break
                chunks.append(b)
        except OSError:
            pass
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    code = None
    try:
        try:
            code = p.wait(timeout)
        except subprocess.TimeoutExpired:
            os.close(alive_w)  # the watchdog kills Blender by its pid, then the group
            alive_w = None
            try:
                p.wait(pysandbox._GRACE_S)
            except subprocess.TimeoutExpired:
                pass
    finally:
        if alive_w is not None:
            os.close(alive_w)
        pysandbox._kill_group(p.pid)  # anything left behind, after a timeout or an exception alike
        p.wait()
        reader.join(5)
        try:
            os.close(rd)
        except OSError:
            pass
    # As text=True read it before: undecodable bytes replaced, \r\n and \r as \n
    return code, b"".join(chunks).decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")


def _started(output):
    """The version STARTED_EXPR printed, or None when the direct run never got to Blender's Python."""
    for l in (output or "").split("\n"):
        if l.startswith(STARTED_MARK):
            return l[len(STARTED_MARK):].strip() or None
    return None


def _names_line(output):
    return _marked_line(output, NAMES_MARK)


def _marked_line(output, mark):
    """The JSON object on the last line that starts with mark, or None."""
    lines = [l[len(mark):] for l in (output or "").split("\n") if l.startswith(mark)]
    if not lines:
        return None
    try:
        d = json.loads(lines[-1])
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


# ---------------------------------------------------------------- the gate

class BlenderGate:
    """Checks Blender pieces and plans in real Blender, every run cached. chimera: a datagen.chimera.Chimera; cache: a
    common.Cache (cache/runs.jsonl); versions: {"5.2.2": binary, ...}; jobs: Blender processes at once; linter: an
    rna_lint.Linter (made from data/rna/ when None, with the guarded-read rule on, guards=True: data generation's
    own, decided Nov 6; a caller's linter should be made so too); work: where run folders go
    (blender_check.scratch_root)."""

    def __init__(self, chimera, cache, versions=None, jobs=4, linter=None, work=None, *, timeout=180.0,
                 check_timeout=blender_check.TIMEOUT):
        self.chimera = chimera
        self.cache = cache
        self.versions = dict(versions or blenders.VERSIONS)
        self.linter = linter if linter is not None else rna_lint.Linter(rna_lint.Facts.load(), guards=True)
        self.work = blender_check.scratch_root(work)
        self.blender = GateBlender(chimera, self.versions, self.work, timeout, check_timeout,
                                   threading.BoundedSemaphore(max(1, int(jobs))))
        self._lint_lock = threading.Lock()  # rna_lint.Linter keeps a script's state on itself while it lints
        self._lock = threading.Lock()
        self._inflight = {}
        self._stats = {"runs": 0, "cached": 0, "blender_s": 0.0, "not_cached": 0}

    # ------------------------------------------------------------ runs

    def run_key(self, script):
        return key_of("blender", script, self.versions, self.chimera.sha256(), RUN_FORMAT)

    def run(self, script) -> dict:
        """Both runs of a script in every version, from the cache when it has them: {"check": {v: ...}, "probe":
        {v: ...}, "seconds", "key", "cached"}. Identical scripts asked for at once run once."""
        return self._cached(self.run_key(script), lambda: self.blender.run(script))

    def _cached(self, key, make):
        """make()'s value, cached under key ({"kind": "blender", ..., "seconds", "t"}); one thread makes it."""
        while True:
            hit = self.cache.get(key)
            if hit is not None:
                with self._lock:
                    self._stats["cached"] += 1
                return dict(hit, key=key, cached=True)
            with self._lock:
                ev = self._inflight.get(key)
                if ev is None:
                    if self.cache.get(key) is not None:  # another thread put it there just now
                        continue
                    ev = self._inflight[key] = threading.Event()
                    break
            ev.wait()  # the same run in another thread; then it's cached, or (a tool problem) this thread runs it
        try:
            t0 = time.monotonic()
            value = dict(kind="blender", **make())
            value["seconds"] = round(time.monotonic() - t0, 2)
            value["t"] = now_iso()
            ok = not _problems(value)
            with self._lock:
                self._stats["runs"] += 1
                self._stats["blender_s"] += value["seconds"]
                if not ok:
                    self._stats["not_cached"] += 1
            if ok:
                self.cache.put(key, value)
            return dict(value, key=key, cached=False)
        finally:
            with self._lock:
                self._inflight.pop(key, None)
            ev.set()

    def stats(self) -> dict:
        """{"runs" (made, not from the cache), "cached", "not_cached" (a tool problem), "blender_s",
        "processes" (Blender launches)}."""
        with self._lock:
            out = dict(self._stats)
        out["blender_s"] = round(out["blender_s"], 2)
        out["processes"] = self.blender.processes
        return out

    def lint(self, code):
        with self._lint_lock:
            return self.linter.lint(code)

    # ------------------------------------------------------------ one piece

    def piece_check(self, plan, i, text, verdict, earlier, goal="", *, run_on_lint=True, joined=True,
                    prefer=None) -> dict:
        """Check step i's Blender piece `text`. verdict: the Go validator's for it (None: asked here). earlier:
        {step: text} of the kept pieces of earlier steps (cleaned plan ids, or worker names), a dropped step left
        out. Steps, stopping at the first that fails: lint, alone (strict in every version, the handoff's provides
        there, no .001 duplicates), joined (no fallback, no failing seam, strict in every version, no stand-in
        unless a dependency is missing and no stand-in is for a key a present step provides, no duplicates, every
        earlier piece's provides still there, probed). A copy of the factory camera that the step asks for by name
        and makes the scene's camera isn't a duplicate (factory_copies: alone with the step's words, joined with those
        of the steps in the join; "factory_copies" lists it). run_on_lint: after a lint error the piece still runs alone,
        only to find the real crash a repair needs (the piece fails either way). joined=False stops after the
        alone step (a variant of a step is checked alone only). prefer: a Blender version ("5.2.2", the one whose
        names sheet the step's request carries) whose crash is taken first, then the others' in order; None (or a
        version not checked here) keeps the order of versions.

        After the alone run's own checks come the measured ones (measured_check), still before the join: sizes and
        directions the step gives against what the alone run measured, an output the step never asked for or one it asks
        for that the piece never hands over, a camera it adds that isn't the scene's, what its own except or guard hid
        (swallowed, skipped_input: datagen/silent.py), and the places and depths its step gives (place_mismatch,
        flat_extrusion: datagen/geometry.py; relations, nested, are the joined run's, or the alone run's for a piece
        that won't be joined, joined=False). They fail the piece outright: Chimera sends a repair only for a crash, so
        a repair example can't come of them. A piece whose only faults are the soft ones (SOFT_MEASURED:
        output_missing, camera_not_active, swallowed, skipped_input, place_mismatch, flat_extrusion, nested) still goes
        on to the joined step, whose reasons
        join them: task.py keeps such a piece for the later steps when no try passes (SOFT_REASONS), and they join it,
        so it must join cleanly too (a joined crash in it is then repaired, as Chimera would; the 9 tries of the smoke
        runs' steps that fail only softly all join cleanly). A size from another step (a values step's named sides) is
        measured on the joined run instead, after its own checks, when that step is in the join; failing there, the
        result says "stage": "joined".

        Last at the alone stage, after the measured checks: ctx_channel, a top-level ctx key the contract doesn't
        have, written or read (ctx_channel_parts, read from the code), then build_facts' reasons (since the fourth
        smoke: validator_warning:<code>, dead_output_key, marker_misused, silent_default; its lines are "facts_tell",
        its record "facts", told whatever else fails the piece, as ctx_tell is). Each goes on to the joined step too
        (SOFT_GATE):
        task.py keeps such a piece as a dependency on a step a later one depends on (task.SOFT_IF_USED) and drops it
        otherwise, which is task.soft's to decide; a variant (joined=False) fails on it. Its line (ctx_tell) is told
        whatever else fails the piece, a crash or a lint error included, since it is read from the code. After them,
        since the fifth smoke, global_ctx (a function of the piece reads a ctx it is never given: global_ctx, its
        record "global_ctx", its line "global_ctx_tell", told the same way): hard, but it goes on to the joined step
        (JOINED_SHOWS), Chimera's own join, where the read raises NameError, the crash a repair is sent.

        Reasons: no_code, lint:<kind>, alone_strict:<v>, provides_missing, no_probe (a version passed but its probes
        never ran: the piece rendered or quit), dupes, output_not_asked, output_missing, camera_not_active,
        swallowed, skipped_input, attr_miss (a hasattr or getattr on the way to the keys found nothing and they
        stayed unlike the linear ones the step asks for: silent.missed_keys; soft as ctx_channel is, SOFT_GATE),
        size_mismatch, aim_mismatch, place_mismatch, flat_extrusion, doubled_depth, nested (a variant's),
        ctx_channel, validator_warning:<code>, dead_output_key, marker_misused, silent_default, global_ctx,
        join_fallback, join_no_script, seam:<code>, joined_strict:<v>, stand_in, joined_dupes,
        removes_earlier (an earlier piece's provided name is gone after this one ran: "removed" lists those steps'
        worker names), joined_no_probe, then the joined measured ones (size_mismatch, nested). A geometry reason only
        while its reader is in geometry.GATED (nested isn't, this round: it is recorded only).

        Returns {"ok", "reasons", "tell", "lint", "alone": {v: summary}, "joined": {v: summary}, "stand_in",
        "stand_in_keys", "stand_in_allowed", "dupes", "factory_copies", "provides_missing", "removed", "measured",
        "scene", "crash", "seams", "runs": {"alone", "joined"}, "seconds"}, "stage" ("joined") for a size failed
        joined, "ctx_channel" (ctx_channel_parts' {"written", "read"}) with "ctx_tell" (its line) when the code
        has such a key, and "global_ctx" (global_ctx's) with "global_ctx_tell" when it has such a read; crash is
        Go's workerCrash {step, part, function, piece_line, line, source, error, runner ("Blender <version>")}, in
        this piece, or None. tell: plain lines for the next try's teacher on why it failed (tell_lines), [] when it
        passed."""
        t0 = time.monotonic()
        steps = plan["steps"]
        st, sid = steps[i], "s%d" % (i + 1)
        out = {"ok": False, "reasons": [], "tell": [], "lint": [], "alone": {}, "joined": {}, "stand_in": False,
               "stand_in_keys": [], "stand_in_allowed": False, "dupes": [], "factory_copies": [], "provides_missing": [],
               "removed": [], "measured": {}, "scene": None, "crash": None, "seams": [], "runs": {}, "seconds": 0.0}
        reasons = out["reasons"]

        def done():
            out["ok"] = not reasons
            out["tell"] = tell_lines(out)
            out["seconds"] = round(time.monotonic() - t0, 2)
            return out
        deps = ["s%d" % (j + 1) for j in dep_indexes(plan, i)]
        job = {"text": text or "", "mode": "blender", "sid": sid, "deps": deps, "lone": len(steps) == 1, "step": st}
        if verdict is None:
            verdict = self.chimera.validate([job])[0]
        code = verdict.get("code") or ""
        if verdict.get("mode") != "blender" or not code.strip():
            reasons.append("no_code")
            return done()
        parts = ctx_channel_parts(code)  # read from the code: told whatever else fails, the reason comes last
        if parts["written"] or parts["read"]:
            out["ctx_channel"] = parts
            out["ctx_tell"] = ctx_tell(sid, parts["written"], parts["read"])
        reads = global_ctx(code)  # the same: a ctx only the alone run's tail gives (JOINED_SHOWS)
        if reads:
            out["global_ctx"] = reads
            out["global_ctx_tell"] = global_ctx_tell(sid, reads)
        mine = {"s%d" % (step_index(plan, k) + 1): t for k, t in by_id(plan, earlier).items()
                if step_index(plan, k) < i}
        facts = build_facts(plan, i, code, verdict, mine)  # the same: what the build drops, and the stand-in marker
        if facts["reasons"] or facts["warnings"]:
            out["facts"] = {k: facts[k] for k in ("warnings", "dead_output", "stand_ins", "reasons", "waived")}
            out["facts_tell"] = facts["tell"]

        # 1. lint
        found = self.lint(code)
        out["lint"] = found[:LINT_KEEP]
        lint_errors = sorted({"lint:" + x["kind"] for x in found if x["level"] == "error"})
        reasons.extend(lint_errors)
        if lint_errors and not run_on_lint:
            return done()

        # 2. alone
        script = self.chimera.alone([dict(job, keep_ctx=True, ctx_name="ctx")])[0]
        if script is None:  # it doesn't parse (the lint has said so) or has no code
            if not lint_errors:
                reasons.append("no_code")
            return done()
        run = self.run(script)
        out["runs"]["alone"] = run["key"]
        out["alone"] = {v: _summary(run, v) for v in self.versions}
        reasons.extend("alone_strict:" + v for v in self.versions if not out["alone"][v]["strict"])
        out["crash"] = self._alone_crash(run, code, sid, prefer)
        out["scene"] = next((s for s in (_scene(run["probe"].get(v) or {}, code) for v in self.versions) if s), None)
        if reasons:
            return done()
        earlier = {k: t for k, t in by_id(plan, earlier).items() if step_index(plan, k) < i}
        j = self.chimera.join(plan, dict(earlier, **{st["id"]: text}), goal=goal)
        theirs = set()
        for p in j.get("pieces") or []:  # what the dependencies provide isn't this piece's to provide
            if p.get("sid") in deps and p.get("handoff"):
                theirs.update(provided_names(p["handoff"].get("provides")))
        named = [n for n in provided_names((verdict.get("handoff") or {}).get("provides")) if n not in theirs]
        missing, no_probe = [], False
        for v in self.versions:
            have = _have(run["probe"].get(v) or {})
            if have is None:
                no_probe = True
                continue
            missing.extend(n for n in named if n not in have and n not in missing)
        out["provides_missing"] = missing
        if missing:
            reasons.append("provides_missing")
        if no_probe:
            reasons.append("no_probe")
        later = "\n".join(_step_text(s) for s in steps[i + 1:])
        dupes, out["factory_copies"] = real_dupes(run, self.versions, _step_text(st), later)
        out["dupes"] = dupes
        if dupes:
            reasons.append("dupes")
        if not reasons:
            found, out["measured"] = self.measured_check(plan, i, code, run, unjoined=not joined)
            reasons.extend(found)
        if out.get("ctx_channel"):
            reasons.append("ctx_channel")
        reasons.extend(facts["reasons"])  # what the build drops and the marker's faults, soft as ctx_channel is
        if out.get("global_ctx"):  # hard, but the joined run (Chimera's join) shows its crash: JOINED_SHOWS
            reasons.append("global_ctx")
        if _hard(reasons) or not joined:
            return done()

        # 3. joined
        if j.get("fallback"):
            reasons.append("join_fallback")
            out["join_reasons"] = (j.get("reasons") or [])[:3]
            return done()
        if not j.get("script") or j.get("script_kind") != "run_blender":
            reasons.append("join_no_script")
            return done()
        in_join = {"s%d" % (step_index(plan, k) + 1) for k in earlier} | {sid}
        out["seams"] = j.get("seams") or []
        bad = sorted({s["code"] for s in out["seams"] if s.get("code") in SEAMS_FAIL
                      and not self._seam_excused(plan, s, in_join)})
        reasons.extend("seam:" + c for c in bad)
        if bad:
            return done()
        script = skip_render(j["script"], j.get("linemap"))
        run = self.run(script)
        out["runs"]["joined"] = run["key"]
        out["joined"] = {v: _summary(run, v) for v in self.versions}
        reasons.extend("joined_strict:" + v for v in self.versions if not out["joined"][v]["strict"])
        out["crash"] = self._joined_crash(run, j.get("linemap"), script, want=sid, prefer=prefer)[1]
        named = _named(plan, [p for p in j.get("pieces") or [] if p.get("sid") in in_join])
        out["stand_in"] = any((run["probe"].get(v) or {}).get("stand_in") for v in self.versions)
        out["stand_in_keys"], provided = self._stand_ins(run, named)
        out["stand_in_allowed"] = self._missing_deps(plan, in_join) and not provided
        if out["stand_in"] and not out["stand_in_allowed"]:
            reasons.append("stand_in")
        jd, fc = real_dupes(run, self.versions, "\n".join(
            _step_text(steps[step_index(plan, s)]) for s in sorted(in_join)), later)
        out["factory_copies"] = sorted(set(out["factory_copies"]) | set(fc))
        out["dupes"] = sorted(set(out["dupes"]) | set(jd))
        if jd:
            reasons.append("joined_dupes")
        haves = [h for h in (_have(run["probe"].get(v) or {}) for v in self.versions) if h is not None]
        out["removed"] = [s for s, names in named.items()
                          if s != sid and any(n not in h for h in haves for n in names)]
        if out["removed"]:
            reasons.append("removes_earlier")
        if self._unprobed(run):
            reasons.append("joined_no_probe")
        if not _hard(reasons):  # the alone run's measured checks passed (or failed only soft): no size fault yet
            codes = {p.get("sid"): p.get("code") or "" for p in j.get("pieces") or [] if p.get("sid") in in_join}
            stood = any(r.get("unmeasured") == "stand_in" for r in out["measured"].get("places") or [])
            found, more = self.measured_check(plan, i, code, run, joined=in_join, codes=codes,
                                              linemap=j.get("linemap"), places=stood)
            told = (out["measured"].get("faults") or []) + (more.get("faults") or [])
            out["measured"].update(more)
            if told:  # the alone run's lines too: a soft fault's tell isn't lost to a joined size fault
                out["measured"]["faults"] = list(dict.fromkeys(told))
            if found:
                reasons.extend(found)
                out["stage"] = "joined"  # task's stage for it: _blender_stage would read size_mismatch as alone's
        return done()

    def measured_check(self, plan, i, code, run, joined=None, codes=None, linemap=None, unjoined=False,
                       places=False):
        """The measured checks of step i's piece (its code, and run: the alone run, or with joined the joined one):
        (reasons, details). output_not_asked: its SETTINGS_sN["output"] sets a path though the step speaks of no
        saving, rendering, export or output file (asks_output). output_missing: the reverse, read from the code
        alone: the step's words ask to save a .blend or to render (asked_outputs), and what the piece's
        SETTINGS_sN["output"] holds makes Chimera do neither, or not that one (handed_outputs: no "output" key, or no
        path of that kind under it). camera_not_active: the step's words add a camera of its own (asks_camera), and
        the scene's camera after the run isn't one the piece made: none, or the factory camera untouched
        (camera_fault). size_mismatch: a size the step gives (asked_sizes) that nothing measures. aim_mismatch: a light
        or camera the step says points down (asked_aims) that none of the piece's does. swallowed and skipped_input
        (step 6a, datagen/silent.py, read from the direct run's silent report, not the step's words): an error from
        Blender that the piece's own except caught at one of its lines, or a node input it looked up by a name the node
        doesn't have, behind a guard that skipped it and left the input it meant at its default, and attr_miss (Nov 5):
        a hasattr or getattr on the piece's way to the keys that found nothing in every version, where the step's
        words ask for linear keys and every version's keys stayed otherwise (silent.missed_keys). place_mismatch,
        flat_extrusion and nested (step 6b, datagen/geometry.py, the step's words against the direct run's geometry
        line and measuring, _geometry; doubled_depth since Nov 5, a depth asked one way that every object it can be
        has twice over, as Blender's both-ways extrude of a curve or a text makes it): a thing the step puts at a
        point that no object of its name stands at (nor
        two or more of them together; when the alone run printed a stand-in, judged on the joined run instead: places
        True there), a depth
        it asks for that every object it can be left flat, a flat thing buried in the solid one it is to stand behind,
        in front of or beside (the joined run's, or with unjoined, a piece that won't be joined, the alone run's). A
        measured fault (camera, size, aim, geometry) and a hidden one count only when every version shows it, a
        hidden one only when every version's report watched the piece (silent.watched; a version that rendered, quit
        or crashed has none), a geometry one only when every version printed its geometry line and measuring, and
        only while its reader is in geometry.GATED (nested isn't this round: its rows still say what it found).

        Alone (joined None): the outputs, the camera, the aims and the sizes from the step's own words. A size from
        another step
        (named sides in a values step, source "s1") is checked only joined (joined: the worker names in the join),
        on the joined run's measure, and only when that step is in the join: alone, the values a piece reads from it
        are missing by design and its stand-in defaults measure instead. There it is held to what that step's piece
        really sets (codes: the join's code by worker name; _held), and not at all when that piece sets other values
        than its words. A variant, checked alone only, has those checked never. Joined (linemap: the join's line
        map), the hidden errors at the piece's own lines are recorded only ("joined_silent"): 0 of 133 stored joined
        runs found one the piece's alone run didn't. details: {"output": [paths],
        "output_missing": {"missing", "asked": {kind: sentence}, "handed"}, "dead_output": [keys] (dead_output_key's,
        when the step asks Chimera for a render or a save: no reason here, build_facts gives it, but its line,
        dead_tell, is told with whatever else fails the piece), "camera": {"asked": clause,
        "scene_camera": [each version's record], "fits": None when no version recorded it}, "sizes" (alone) or
        "joined_sizes": [{"phrase", "sides", "thing", "source", "fits", ...}], "aims": [{"what", "type", "word",
        "angle", "phrase", "fits"}], "silent" (alone) or "joined_silent": {"swallowed", "skipped", "attr_miss",
        "excused", and "missed" when attr_miss fires} (silent's verdicts and facts, whenever every version watched),
        "places", "depths", "doubled" (alone) and "relations" (joined, or unjoined), "joined_places" (joined, with
        places)
        (_geometry's rows: each asked item with "fits", "fault", "unmeasured" and
        what is recorded only, "floor" or "holds"), "faults": [tell lines]}, each other one only when there is
        something. A size's
        "fits" is True when a version measures it, False when every version shows the fault, and None when no
        version could measure it (size_states), with "unmeasured" saying why ("cut", "other_values", "nothing");
        "piece_sides" is what the values step's piece sets."""
        sid = "s%d" % (i + 1)
        reasons, details, faults = [], {}, []
        sizes = [a for a in asked_sizes(plan, i) if (a["source"] == "step") == (joined is None)
                 and (joined is None or a["source"] in joined)]
        if joined is None:
            checks = (("sizes", sizes, size_faults, "size_mismatch"),
                      ("aims", asked_aims(plan, i), aim_faults, "aim_mismatch"))
        else:
            sizes = [_held(a, codes) for a in sizes]
            checks = (("joined_sizes", sizes, size_faults, "size_mismatch"),)
        paths = output_paths(code, sid) if joined is None else []
        if paths and not asks_output(plan, i):
            reasons.append("output_not_asked")
            details["output"] = paths[:5]
            faults.append('SETTINGS_%s["output"] sets %s, but the step says nothing about saving, rendering or '
                          'exporting: leave "output" out' % (sid, ", ".join(json.dumps(p) for p in paths[:3])))
        if joined is None:
            missing, asked, handed = output_missing(plan, i, code)
            if missing:
                reasons.append("output_missing")
                details["output_missing"] = {"missing": missing, "asked": {k: asked[k] for k in missing},
                                             "handed": handed}
                faults.append(missing_tell(plan, i, missing, handed, asked))
            dead = dead_output_key(code, sid) if asked["blend"] or asked["render"] else []
            if dead:  # no reason here (build_facts' dead_output_key, since the fourth smoke), but its line is told
                details["dead_output"] = dead  # with whatever fails the piece (tell_lines says it once)
                faults.append(dead_tell(sid, dead))
        measures = [m for m in ((run["probe"].get(v) or {}).get("measure") for v in self.versions) if m]
        camera = asks_camera(plan, i) if joined is None and measures else None
        if camera:
            fault = camera_fault(measures)
            known = any("scene_camera" in m for m in measures)
            details["camera"] = {"asked": camera, "scene_camera": [m.get("scene_camera", "not recorded")
                                                                    for m in measures],
                                 "fits": None if not known else fault is None}
            if fault:
                reasons.append("camera_not_active")
                faults.append(CAMERA_TELL[fault])
        if joined is None:
            n = len(code.split("\n"))
            found = self._silent(run, code, lambda x: x if isinstance(x, int) and 1 <= x <= n else None,
                                 _step_text(plan["steps"][i]))
            if found is not None:
                details["silent"] = found
                if found["swallowed"]:
                    reasons.append("swallowed")
                if found["skipped"]:
                    reasons.append("skipped_input")
                if found.get("missed"):
                    reasons.append("attr_miss")
                faults.extend(silent.tell(found["swallowed"], found["skipped"]))
                faults.extend(silent.missed_tell(found.get("missed")))
        elif linemap:
            found = self._silent(run, code, silent.joined_line_of(linemap, sid), _step_text(plan["steps"][i]))
            if found is not None:  # recorded only: no reason, nothing told
                details["joined_silent"] = found
        for name, asked, check, reason in checks:
            if not asked or not measures:
                continue
            if check is size_faults:
                states = [size_states(asked, m) for m in measures]
                bad = [k for k in range(len(asked)) if all(st[k][0] == "fault" for st in states)]
                rows = []
                for k, a in enumerate(asked):
                    got = [st[k] for st in states]
                    fits = False if k in bad else True if any(x == "fits" for x, _ in got) else None
                    rows.append(dict(a, fits=fits) if fits is not None else
                                dict(a, fits=None, unmeasured=next(why for x, why in got if x == "unmeasured")))
                details[name] = rows
                lines = [states[0][k][1] for k in bad]
            else:
                each = [dict(check(asked, m)) for m in measures]
                bad = [k for k in each[0] if all(k in e for e in each)]
                details[name] = [dict(a, fits=k not in bad) for k, a in enumerate(asked)]
                lines = [each[0][k] for k in bad]
            if bad:
                reasons.append(reason)
                faults.extend(lines)
        if joined is None:
            geo = [("places", geometry.asked_places(plan, i), geometry.place_states, "place_mismatch"),
                   ("depths", geometry.asked_depths(plan, i), geometry.depth_states, "flat_extrusion"),
                   ("doubled", geometry.asked_doubled(plan, i), geometry.doubled_states, "doubled_depth")]
            if unjoined:
                geo.append(("relations", geometry.asked_relations(plan, i), geometry.relation_states, "nested"))
        else:
            geo = [("relations", geometry.asked_relations(plan, i), geometry.relation_states, "nested")]
            if places:  # the alone run stood the thing on a stand-in: where it really goes is the joined run's
                geo.append(("joined_places", geometry.asked_places(plan, i), geometry.place_states, "place_mismatch"))
        for name, found, lines in self._geometry(run, geo):
            details[name] = found
            if lines:
                reasons.append(dict((n, r) for n, _, _, r in geo)[name])
                faults.extend(lines)
        if faults:
            details["faults"] = faults
        return reasons, details

    def _geometry(self, run, checks):
        """Step 6b on a run (datagen/geometry.py): [(name, rows, tell lines)] for each of checks ((name, asked,
        states_of, reason)) that asks something, when every version's direct run printed its geometry line and its
        measuring ([] otherwise: nothing judged). A fault counts only when every version shows it, and gives lines only
        when its reason is in geometry.GATED (a reader that failed the held-out check is recorded, never a reason).
        Relations get the run's stand-in keys (any version's), and places whether any version printed a stand-in
        (geometry.place_states' stood_in: a thing stood on its dependency's object stands on the stand-in alone, so
        its place is recorded there, never a fault, "stand_in_fault" keeping the line it would have told, and judged
        on the joined run, piece_check's "joined_places"). rows: each asked
        item with "fits" (True when a version finds it right, False when every version shows the fault, None
        otherwise, with "unmeasured": "unmatched" (no object named like the thing), "stand_in" or "recorded"),
        "fault" (the line, gated or not), and for what is recorded only, "floor" (on the floor or not) or "holds"
        (above or below), one per version."""
        probes = [run["probe"].get(v) or {} for v in self.versions]
        if not all(isinstance(p.get("geom"), dict) and "failed" not in p["geom"] and p.get("measure")
                   for p in probes):
            return []
        keys = sorted({k for p in probes for k in p.get("stand_in_keys") or []})
        stood = any(p.get("stand_in") or p.get("stand_in_keys") for p in probes)
        out = []
        for name, asked, states_of, reason in checks:
            if not asked:
                continue
            states = [states_of(asked, p, keys) if states_of is geometry.relation_states else
                      states_of(asked, p, stood) if states_of is geometry.place_states else states_of(asked, p)
                      for p in probes]
            bad = [k for k in range(len(asked)) if all(st[k][0] == "fault" for st in states)]
            rows = []
            for k, a in enumerate(asked):
                got = [st[k] for st in states]
                row = dict(a, fits=False if k in bad else True if any(s == "fits" for s, _ in got) else None)
                if k in bad:
                    row["fault"] = got[0][1]
                elif row["fits"] is None:
                    row["unmeasured"] = next((s for s, _ in got if s in ("unmatched", "stand_in")), "recorded")
                    if all(s == "stand_in" and x for s, x in got):
                        row["stand_in_fault"] = got[0][1]
                if got[0][0] in ("floor", "recorded"):
                    row["floor" if got[0][0] == "floor" else "holds"] = [x for _, x in got]
                rows.append(row)
            out.append((name, rows, [states[0][k][1] for k in bad] if reason in geometry.GATED else []))
        return out

    def _silent(self, run, code, line_of, words=""):
        """silent's verdicts and facts on a run's reports at the piece's own lines (line_of maps a script line to
        one), or None when some version's report didn't watch the piece (silent.watched: none printed, or no way to
        watch): {"swallowed", "skipped", "attr_miss", "excused"}, and "missed" when a guard on the way to the keys
        skipped the linear keys the step's words ask for (silent.missed_keys, attr_miss's reason; words: the step's
        title and instructions)."""
        recs = {v: (run["probe"].get(v) or {}).get("silent") for v in self.versions}
        if not all(silent.watched(r) for r in recs.values()):
            return None
        out = {"swallowed": silent.swallowed(code, recs, line_of),
               "skipped": silent.skipped_sockets(recs, line_of, code),
               "attr_miss": silent.attr_misses(recs, line_of), "excused": silent.excused_events(code, recs, line_of)}
        missed = silent.missed_keys(recs, line_of, words)
        if missed:
            out["missed"] = missed
        return out

    def _stand_ins(self, run, named):
        """(the stand-in keys a run printed in any version, those of them a present step provides: named, from
        _named). A stand-in for one of those found nothing where the step that makes it is there."""
        keys = []
        for v in self.versions:
            keys.extend(k for k in (run["probe"].get(v) or {}).get("stand_in_keys") or [] if k not in keys)
        mine = {n for names in named.values() for n in names}
        return keys, [k for k in keys if k in mine]

    def _order(self, prefer):
        """The versions, prefer first when it's one of them."""
        if not isinstance(prefer, str) or prefer not in self.versions:
            return list(self.versions)
        return [prefer] + [v for v in self.versions if v != prefer]

    def _unprobed(self, run):
        """Some version passed strict but its probes never ran: the script stopped early on its own (a render, a
        quit), so its scene can't be checked."""
        return any(blender_run.counted_strict(run["check"].get(v), run["probe"].get(v))
                   and _have(run["probe"].get(v) or {}) is None for v in self.versions)

    def _alone_crash(self, run, code, sid, prefer=None):
        """The first definite crash of the alone run in the piece's own code (the alone script keeps its line
        numbers), prefer's version first, as Go's workerCrash; None if there is none."""
        n = len(code.split("\n"))
        for v in self._order(prefer):
            c = run["check"].get(v) or {}
            line = c.get("line") or 0
            if c.get("outcome") != "failed" or not 1 <= line <= n:
                continue
            part, function = part_of(code, line, sid)
            if not part:
                continue
            return {"step": sid, "part": part, "function": function, "piece_line": line, "line": line,
                    "source": c.get("source") or "", "error": c.get("error") or "",
                    "runner": c.get("runner") or "Blender " + v}
        return None

    def _joined_crash(self, run, linemap, script, want=None, prefer=None):
        """(spot, crash) of a joined run: Go's locate of the first version's check that has a line (definite first,
        then prefer's version first), and the workerCrash when that crash is definite and in a step's own code
        (want: only in that step)."""
        checks = [(v, run["check"].get(v) or {}) for v in self._order(prefer)]
        checks = [(v, c) for v, c in checks if c.get("line") and c.get("outcome") in ("failed", "unsure")]
        checks.sort(key=lambda vc: vc[1].get("outcome") != "failed")
        if not checks or not linemap:
            return None, None
        jobs = [{"linemap": linemap, "check": {k: c.get(k) or ("" if k != "line" else 0) for k in
                                               ("outcome", "line", "error", "source", "runner")}, "script": script}
                for _, c in checks]
        spots = self.chimera.locate(jobs)
        for (v, c), spot in zip(checks, spots):
            if spot.get("source_matches") is False:
                continue
            crash = None
            if spot.get("definite") and spot.get("repair") and (want is None or spot["repair"] == want):
                crash = {"step": spot["repair"], "part": spot.get("part") or "", "function": spot.get("function") or "",
                         "piece_line": spot.get("piece_line") or 0, "line": spot.get("line") or 0,
                         "source": spot.get("source") or "", "error": spot.get("error") or "",
                         "runner": spot.get("runner") or "Blender " + v}
            return spot, crash
        return None, None

    @staticmethod
    def _missing_deps(plan, in_join):
        """Whether some step in the join depends on a step that isn't in it (so a stand-in is expected)."""
        for k, s in enumerate(plan["steps"]):
            if "s%d" % (k + 1) in in_join and any("s%d" % (d + 1) not in in_join for d in dep_indexes(plan, k)):
                return True
        return False

    @staticmethod
    def _seam_excused(plan, seam, in_join):
        """A seam doesn't fail a piece when it comes from a step that isn't in the join: its message names one, or
        it's a ctx key read by a step whose dependency was dropped (that step makes a stand-in instead)."""
        if any(w not in in_join for w in _STEP_WORD.findall(seam.get("message") or "")):
            return True
        k = step_index(plan, seam.get("step") or "")
        if seam.get("code") == "ctx_key_missing" and k is not None:
            return any("s%d" % (d + 1) not in in_join for d in dep_indexes(plan, k))
        return False

    # ------------------------------------------------------------ the whole plan

    def plan_check(self, plan, kept, goal="") -> dict:
        """The join of every kept Blender piece (kept: {step: text}, a dropped step left out), run in every version:
        strict in all, no duplicates (a copy of the factory camera excused as factory_copies says, with every kept
        step's words), a stand-in only if a step some step depends on was dropped and none for a key
        a kept step provides (stand_in_keys: the keys the stand-ins printed), and every step's provides still there
        at the end (provides_lost: the worker names of the steps whose names are gone: a later step deleted or
        renamed them), and probed (no_probe otherwise). culprit: the step the line map names for a
        crash (worker name, culprit_id the plan id), None for anything else. Also Chimera's check of the joined
        script with the goal (look off), recorded as scene_outcome and scene_critique, not gated on.

        Returns {"ok", "reasons", "fallback", "seams", "joined": {v: summary}, "stand_in", "stand_in_keys", "dupes",
        "factory_copies", "provides_lost", "culprit", "culprit_id", "crash", "spot", "scene_outcome", "scene_critique",
        "scene_check", "runs", "seconds"}."""
        t0 = time.monotonic()
        steps = plan["steps"]
        kept = by_id(plan, kept)
        out = {"ok": False, "reasons": [], "fallback": False, "seams": [], "joined": {}, "stand_in": False,
               "stand_in_keys": [], "dupes": [], "factory_copies": [], "provides_lost": [], "culprit": None,
               "culprit_id": None, "crash": None, "spot": None, "scene_outcome": None, "scene_critique": "",
               "scene_check": None, "runs": {}, "seconds": 0.0}
        reasons = out["reasons"]

        def done():
            out["ok"] = not reasons
            out["seconds"] = round(time.monotonic() - t0, 2)
            return out
        j = self.chimera.join(plan, kept, goal=goal)
        out["fallback"], out["seams"] = bool(j.get("fallback")), j.get("seams") or []
        if j.get("fallback"):
            reasons.append("join_fallback")
            out["join_reasons"] = (j.get("reasons") or [])[:3]
            return done()
        if not j.get("script") or j.get("script_kind") != "run_blender":
            reasons.append("join_no_script")
            return done()
        script = skip_render(j["script"], j.get("linemap"))
        run = self.run(script)
        out["runs"]["joined"] = run["key"]
        out["joined"] = {v: _summary(run, v) for v in self.versions}
        reasons.extend("joined_strict:" + v for v in self.versions if not out["joined"][v]["strict"])
        spot, crash = self._joined_crash(run, j.get("linemap"), script)
        out["spot"], out["crash"] = spot, crash
        if reasons and spot and spot.get("step"):
            out["culprit"] = spot["step"]
            k = step_index(plan, spot["step"])
            out["culprit_id"] = steps[k]["id"] if k is not None else None
        in_join = {"s%d" % (step_index(plan, k) + 1) for k in kept}
        named = _named(plan, j.get("pieces"))
        out["stand_in"] = any((run["probe"].get(v) or {}).get("stand_in") for v in self.versions)
        out["stand_in_keys"], provided = self._stand_ins(run, named)
        if out["stand_in"] and (provided or not self._missing_deps(plan, in_join)):
            reasons.append("stand_in")
        out["dupes"], out["factory_copies"] = real_dupes(run, self.versions, "\n".join(
            _step_text(steps[step_index(plan, k)]) for k in kept))
        if out["dupes"]:
            reasons.append("dupes")
        haves = [h for h in (_have(run["probe"].get(v) or {}) for v in self.versions) if h is not None]
        out["provides_lost"] = [s for s, names in named.items() if any(n not in h for h in haves for n in names)]
        if out["provides_lost"]:
            reasons.append("provides_lost")
        if self._unprobed(run):
            reasons.append("no_probe")
        sc = self.scene_check(j["script"], goal)
        out["scene_check"] = sc
        out["scene_outcome"], out["scene_critique"] = sc.get("outcome"), sc.get("critique") or ""
        return done()

    def scene_check(self, script, goal) -> dict:
        """Chimera's check of a joined script with the goal, in the first Blender version, look off, cached:
        {outcome, summary, error, line, critique, runner, exit} or {"problem"}."""
        v, binary = next(iter(self.versions.items()))
        key = key_of("blender-goal", script, goal or "", v, binary, self.chimera.sha256(), RUN_FORMAT)

        def make():
            rec = self.blender.check_one(script, v, binary, goal=goal or None)
            return {"check": {v: rec}, "probe": {}}
        r = self._cached(key, make)
        c = r["check"][v]
        out = {k: c.get(k) for k in ("outcome", "summary", "error", "line", "critique", "runner", "exit")}
        if c.get("problem"):
            out["problem"] = c["problem"]
        out.update(key=r["key"], cached=r["cached"], version=v)
        return out


def _problems(value):
    """A run's tool problems (no verdict, the wrong Blender): such a run is never cached."""
    out = []
    for kind in ("check", "probe"):
        for v, r in (value.get(kind) or {}).items():
            if r.get("problem") or (kind == "check" and not r.get("version_ok")):
                out.append(f"{kind} {v}: {r.get('problem') or 'not the Blender asked for'}")
    return out
