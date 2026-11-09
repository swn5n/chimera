"""datagen/silent.py, step 6a's hidden errors: what a Blender piece's own try/except or guard kept Chimera from seeing.

Without Blender: where an error came from (Blender's own Python, Blender's wording on the piece's line, never a raise
statement of the piece's own, None or a class it defines), what is excused and why (another computer's GPU, an add-on,
a mode switch with nothing to switch, a get-or-create or exists probe, a missing file, never a missing operator, a set
that landed after all, a handler that does the same another way), that a verdict needs every version, that a guard
miss counts only on a node's inputs, with a close input left at its default and no hit on the same guard line and
node, in a version whose hits weren't capped; the joined line map, what a record must hold to be judged, and the tell
lines: their forms, length, the versions in words, and that hints.echoed_note refuses a reply that repeats them.

In real Blender (5.2.2 and 5.0.1, tools/blenders.VERSIONS; skipped without them), through the gate's own direct run
(GateBlender._direct, sandboxed under pysandbox's watchdog as every gate run is; no Chimera call, so no Go binary): the
refuter's 22 fixtures (round 6's mapper's runs) get the verdicts the mapper measured under the rules as designed, and
seven more of ours: a guard that looks inputs up by wrong names skips them (and one that sets the input it missed
some other way doesn't), an error raised in one function and handled in another (5.2.2's EXCEPTION_HANDLED offset maps
to no line: the handler is the code object), an error caught by C code outside the piece (hasattr) that isn't the
piece's except, a missing file excused beside a missing operator that isn't, and a ctx["values"] stand-in's dict
KeyError that isn't Blender's. With the report and without it the run's verdict, output lines, probes and measuring
are the same on 24 of them in both versions; the report stays within its budget with 400 handled errors; a run that
quits or crashes prints none, and nothing is judged.

Every piece here is Claude-written test text and starts with the fixture mark (its lines are numbered from it), never
training data. About 30 s.
"""
import json
import os
import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from tests import _paths  # noqa: F401
from datagen import blender_gate as G
from datagen import hints as H
from datagen import silent as S
from runner import blender_run
from runner.mock_ollama import MARK
from tools import blender_check, blenders

HAVE_BLENDER = all(not blenders.check_path(p) for p in blenders.VERSIONS.values())
V1, V2 = list(blenders.VERSIONS)
BOTH = sorted(blenders.VERSIONS)

REFUTER = {
    'r1_x07_slot_fixed': MARK + '''
# s4 – Animate 360° Rotation
import bpy
import bmesh
import math

# ------------------------------------------------------------------
# User-tweakable settings
# ------------------------------------------------------------------
SETTINGS_s4 = {
    "object_name": "Acme_Logo",
    "start_frame": 1,
    "end_frame": 150,          # 5 s × 30 fps
    "fps": 30,
    "rotation_degrees": 360.0, # full turn around Z
    "interpolation": "LINEAR",
}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _s4_set_linear_interpolation(obj, mode):
    """Force every key-frame on *obj* to the requested interpolation mode.

    Works with both the legacy ``action.fcurves`` layout (≤ 4.x) and the
    new layered-action layout (5.0+) where ``fcurves`` lives inside
    layer → strip → channelbag.
    """
    if obj.animation_data is None or obj.animation_data.action is None:
        return

    action = obj.animation_data.action
    fcurves = []

    # ---- legacy path (Blender ≤ 4.x) ----
    try:
        fcurves = list(action.fcurves)
    except (AttributeError, TypeError):
        pass

    # ---- new layered-action path (Blender 5.0+) ----
    if not fcurves:
        try:
            for layer in action.layers:
                for strip in layer.strips:
                    # strip may expose fcurves directly …
                    if hasattr(strip, 'fcurves'):
                        fcurves.extend(list(strip.fcurves))
                    # … or through a channelbag
                    elif hasattr(strip, 'channelbag'):
                        for _try_arg in (obj.animation_data.action_slot,):
                            try:
                                cb = strip.channelbag(_try_arg)
                                if hasattr(cb, 'fcurves'):
                                    fcurves.extend(list(cb.fcurves))
                                break
                            except Exception:
                                continue
        except (AttributeError, TypeError):
            pass

    for fc in fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = mode
            kp.handle_left_type = 'VECTOR'
            kp.handle_right_type = 'VECTOR'


# ------------------------------------------------------------------
# Main build
# ------------------------------------------------------------------
def build_s4(ctx):
    scene = ctx["scene"]
    collection = ctx["collection"]

    obj_name = SETTINGS_s4["object_name"]
    start = SETTINGS_s4["start_frame"]
    end = SETTINGS_s4["end_frame"]
    rot_rad = math.radians(SETTINGS_s4["rotation_degrees"])

    # ---- locate the logo object (provided by s1) ----
    logo_obj = ctx.get("objects", {}).get(obj_name)

    if logo_obj is None:
        # search the scene by name
        logo_obj = bpy.data.objects.get(obj_name)

    if logo_obj is None:
        # stand-in so the rest of the pipeline can proceed
        print("chimera: stand-in", obj_name)
        mesh = bpy.data.meshes.new(f"chimera_{obj_name}")
        logo_obj = bpy.data.objects.new(f"chimera_{obj_name}", mesh)
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bm.to_mesh(mesh)
        bm.free()
        collection.objects.link(logo_obj)
        ctx["objects"][obj_name] = logo_obj

    # ---- make sure rotation starts clean ----
    logo_obj.rotation_euler = (0.0, 0.0, 0.0)

    # ---- scene frame range (5 s @ 30 fps = 150 frames) ----
    scene.frame_start = start
    scene.frame_end = end
    scene.render.fps = SETTINGS_s4["fps"]

    # ---- keyframe 1 : rotation (0, 0, 0) ----
    logo_obj.rotation_euler = (0.0, 0.0, 0.0)
    logo_obj.keyframe_insert(data_path="rotation_euler", frame=start)

    # ---- keyframe 2 : rotation (0, 0, 360°) ----
    logo_obj.rotation_euler = (0.0, 0.0, rot_rad)
    logo_obj.keyframe_insert(data_path="rotation_euler", frame=end)

    # ---- force linear interpolation ----
    _s4_set_linear_interpolation(logo_obj, SETTINGS_s4["interpolation"])

    # restore object to start pose so other steps see a neutral state
    scene.frame_set(start)
    bpy.context.view_layer.update()


# ------------------------------------------------------------------
# Standalone entry-point
# ------------------------------------------------------------------
if __name__ == "__main__":
    build_s4({
        "scene": bpy.context.scene,
        "collection": bpy.context.scene.collection,
        "objects": {},
    })
''',
    'r2_fcurves_legacy_first': MARK + '''
import bpy
bpy.ops.mesh.primitive_cube_add()
o = bpy.context.active_object
o.keyframe_insert("rotation_euler", frame=1)
o.rotation_euler.z = 6.283
o.keyframe_insert("rotation_euler", frame=150)
action = o.animation_data.action
try:
    curves = list(action.fcurves)
except AttributeError:
    slot = o.animation_data.action_slot
    curves = []
    for layer in action.layers:
        for strip in layer.strips:
            curves.extend(strip.channelbag(slot).fcurves)
for fc in curves:
    for k in fc.keyframe_points:
        k.interpolation = "LINEAR"
''',
    'r3_auto_smooth_legacy_first': MARK + '''
import bpy
bpy.ops.mesh.primitive_uv_sphere_add()
o = bpy.context.active_object
bpy.ops.object.shade_smooth()
try:
    o.data.use_auto_smooth = True
    o.data.auto_smooth_angle = 0.5236
except AttributeError:
    bpy.ops.object.shade_smooth_by_angle(angle=0.5236)
print("MODS", [m.type for m in o.modifiers])
''',
    'r4_media_type_other_target_expr': MARK + '''
import bpy
im = bpy.context.scene.render.image_settings
try:
    im.file_format = "FFMPEG"
except TypeError:
    im.media_type = "VIDEO"
    bpy.context.scene.render.image_settings.file_format = "FFMPEG"
print("FMT", im.file_format)
''',
    'r5_media_type_value_from_settings': MARK + '''
import bpy
SETTINGS = {"file_format": "FFMPEG"}
im = bpy.context.scene.render.image_settings
try:
    im.file_format = "FFMPEG"
except TypeError:
    im.media_type = "VIDEO"
    im.file_format = SETTINGS["file_format"]
print("FMT", im.file_format)
''',
    'r6_media_type_via_helper': MARK + '''
import bpy
def _set_video(im):
    im.media_type = "VIDEO"
    im.file_format = "FFMPEG"
im = bpy.context.scene.render.image_settings
try:
    im.file_format = "FFMPEG"
except TypeError:
    _set_video(im)
print("FMT", im.file_format)
''',
    'r7_socket_old_then_new_default_value': MARK + '''
import bpy
mat = bpy.data.materials.new("chimera_gold")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
for name in ("Specular", "Specular IOR Level"):
    if name in bsdf.inputs:
        bsdf.inputs[name].default_value = 0.5
        break
bsdf.inputs["Base Color"].default_value = (1.0, 0.8, 0.2, 1.0)
''',
    'r8_emission_old_then_new_white': MARK + '''
import bpy
mat = bpy.data.materials.new("chimera_glow")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
for name in ("Emission", "Emission Color"):
    if name in bsdf.inputs:
        bsdf.inputs[name].default_value = (1.0, 1.0, 1.0, 1.0)
        break
bsdf.inputs["Emission Strength"].default_value = 5.0
''',
    'a_f1_reverse_fallback': MARK + '''
import bpy
mat = bpy.data.materials.new("chimera_glass")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
v = 1.0
try:
    bsdf.inputs["Transmission"].default_value = v
except KeyError:
    bsdf.inputs["Transmission Weight"].default_value = v
''',
    'a_f2_media_type_fallback': MARK + '''
import bpy
im = bpy.context.scene.render.image_settings
try:
    im.file_format = "FFMPEG"
except TypeError:
    im.media_type = "VIDEO"
    im.file_format = "FFMPEG"
''',
    'a_f3_x20_like': MARK + '''
import bpy
im = bpy.context.scene.render.image_settings
try:
    im.file_format = "FFMPEG"
except Exception:
    im.file_format = "OPEN_EXR"
''',
    'a_f4_one_version': MARK + '''
import bpy
im = bpy.context.scene.render.image_settings
try:
    im.file_format = "AVIF"
except TypeError:
    im.file_format = "PNG"
''',
    'a_f5_mode_set_no_active': MARK + '''
import bpy
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
try:
    bpy.ops.object.mode_set(mode="OBJECT")
except RuntimeError:
    pass
''',
    'a_f6_get_or_create': MARK + '''
import bpy
try:
    obj = bpy.data.objects["chimera_floor"]
except KeyError:
    mesh = bpy.data.meshes.new("chimera_floor")
    obj = bpy.data.objects.new("chimera_floor", mesh)
    bpy.context.scene.collection.objects.link(obj)
''',
    'a_f7_addon_probe': MARK + '''
import bpy
try:
    bpy.ops.preferences.addon_enable(module="chimera_missing_addon")
except Exception as e:
    print("no add-on", e)
''',
    'a_f8_hasattr_guard': MARK + '''
import bpy
bpy.ops.mesh.primitive_cube_add()
o = bpy.context.active_object
o.keyframe_insert("location", frame=1)
o.location.x = 2
o.keyframe_insert("location", frame=20)
action = o.animation_data.action
if hasattr(action, "fcurves"):
    for fc in action.fcurves:
        for k in fc.keyframe_points:
            k.interpolation = "LINEAR"
''',
    'a_f9_socket_new_then_old': MARK + '''
import bpy
mat = bpy.data.materials.new("chimera_m")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
for name in ("Transmission", "Transmission Weight"):
    if name in bsdf.inputs:
        bsdf.inputs[name].default_value = 1.0
        break
''',
    'a_f10_suppress': MARK + '''
import bpy, contextlib
im = bpy.context.scene.render.image_settings
with contextlib.suppress(TypeError):
    im.file_format = "FFMPEG"
''',
    'a_f11_raise_own': MARK + '''
import bpy
def check(n):
    if n < 0:
        raise ValueError("negative")
    return n
try:
    check(-1)
except ValueError:
    pass
d = {}
try:
    d["x"]
except KeyError:
    pass
''',
    'a_f12_quiet_get_or_create': MARK + '''
import bpy
obj = None
try:
    obj = bpy.data.objects["chimera_floor"]
except KeyError:
    pass
if obj is None:
    obj = bpy.data.objects.new("chimera_floor", bpy.data.meshes.new("chimera_floor"))
    bpy.context.scene.collection.objects.link(obj)
''',
    'a_f13_node_probe': MARK + '''
import bpy
mat = bpy.data.materials.new("chimera_m")
mat.use_nodes = True
nodes = mat.node_tree.nodes
bsdf = None
try:
    bsdf = nodes["Principled"]
except KeyError:
    pass
if bsdf is None:
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
''',
    'a_f14_socket_keyerror_swallowed': MARK + '''
import bpy
mat = bpy.data.materials.new("chimera_m")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
try:
    bsdf.inputs["Base_Color"].default_value = (1, 0.8, 0, 1)
except KeyError:
    pass
''',
}
# The refuter's verdicts (round 6's mapper's runs of these 22 under the rules as designed: rule B and the file
# excuse), at the refuter's line numbers: one more here, for the mark's line. Every other one is neither.
REFUTER_SWALLOWED = {"r1_x07_slot_fixed": [37], "r2_fcurves_legacy_first": [9], "r3_auto_smooth_legacy_first": [6],
                     "a_f3_x20_like": [4], "a_f10_suppress": [4], "a_f14_socket_keyerror_swallowed": [6]}
# ... and why each handled error the others hit isn't counted (excused_events, at the refuter's lines)
REFUTER_EXCUSED = {"r4_media_type_other_target_expr": [(4, "landed")],
                   "r5_media_type_value_from_settings": [(5, "landed")], "r6_media_type_via_helper": [(7, "landed")],
                   "a_f1_reverse_fallback": [(7, "get_or_create")],
                   "a_f2_media_type_fallback": [(4, "landed")], "a_f4_one_version": [(4, "not_every_version")],
                   "a_f5_mode_set_no_active": [(5, "mode_set")], "a_f6_get_or_create": [(3, "get_or_create")],
                   "a_f7_addon_probe": [(3, "gpu")],  # GPU_LINE comes first: `.preferences` is on the line
                   "a_f11_raise_own": [(4, "not_blender"), (12, "not_blender")],
                   "a_f12_quiet_get_or_create": [(4, "exists_probe")], "a_f13_node_probe": [(7, "exists_probe")]}

OURS = {
    # X06's way: wrong names behind a guard, so the glass stays opaque (Base Color and Transmission Weight)
    "skipped_wrong_names": MARK + '''
import bpy
mat = bpy.data.materials.new("chimera_glass")
bsdf = mat.node_tree.nodes["Principled BSDF"]
for key, value in (("Base_Color", (0.8, 0.9, 1.0, 1.0)), ("Transmission", 1.0), ("Roughness", 0.05)):
    if key in bsdf.inputs:
        bsdf.inputs[key].default_value = value
''',
    # the same miss, but the input it meant is set on the next line: nothing stayed at its default
    "skipped_then_set": MARK + '''
import bpy
mat = bpy.data.materials.new("chimera_glass")
bsdf = mat.node_tree.nodes["Principled BSDF"]
if "Base_Color" in bsdf.inputs:
    bsdf.inputs["Base_Color"].default_value = (0.8, 0.9, 1.0, 1.0)
bsdf.inputs["Base Color"].default_value = (0.8, 0.9, 1.0, 1.0)
''',
    # raised in one function, handled in another: the handler is setup, whose first line is 6
    "handled_outer": MARK + '''
import bpy
def set_video(im):
    im.file_format = "FFMPEG"

def setup():
    im = bpy.context.scene.render.image_settings
    try:
        set_video(im)
    except TypeError:
        pass

setup()
''',
    # Blender's AttributeError inside a property of the piece's, caught by hasattr (C): not the piece's except
    "caught_by_c": MARK + '''
import bpy
class Probe:
    @property
    def depth(self):
        return bpy.context.scene.chimera_no_such_setting
found = hasattr(Probe(), "depth")
''',
    # a file the computer doesn't have is excused, an operator Blender doesn't have isn't
    "file_and_operator": MARK + '''
import bpy, os
try:
    bpy.data.images.load(os.path.join(os.getcwd(), "chimera_missing.png"))
except RuntimeError:
    pass
try:
    open(os.path.join(os.getcwd(), "chimera_missing.txt")).read()
except OSError:
    pass
try:
    bpy.ops.object.chimera_no_such_operator()
except AttributeError:
    pass
''',
    # a ctx["values"] stand-in: its KeyError is the dict's, not Blender's
    "values_stand_in": MARK + '''
import bpy
ctx = {"scene": bpy.context.scene, "collection": bpy.context.scene.collection, "objects": {}, "values": {}}
try:
    width = ctx["values"]["sofa_width"]
except KeyError:
    print("chimera: stand-in sofa_width")
    width = 2.0
''',
    # 400 refused sets, each with a long message: the report keeps within its budget
    "many": MARK + '''
import bpy
im = bpy.context.scene.render.image_settings
for k in range(400):
    try:
        im.file_format = "CHIMERA_NO_SUCH_FORMAT_%03d_" % k + "x" * 200
    except TypeError:
        pass
''',
}
OURS_SWALLOWED = {"handled_outer": [4], "file_and_operator": [12], "many": [6]}
OURS_SKIPPED = {"skipped_wrong_names": [(6, "Base_Color"), (6, "Transmission")]}
# After the fourth smoke (Nov 5): attr_miss as a reason. The fourth smoke's kept blender-0008-00 s4 (qwen3.8 c4), its
# shape: hasattr fallbacks on the way to the keys, each missing in Blender 5, so the keys stay BEZIER; and the third
# smoke's kept c5's way: the old guard misses too, but the channelbag path sets LINEAR.
KEYS = {
    "keys_guard_missed": MARK + '''
import bpy
ob = bpy.data.objects.new("chimera_logo", None)
bpy.context.scene.collection.objects.link(ob)
ob.keyframe_insert("rotation_euler", frame=1)
ob.rotation_euler[2] = 6.283185
ob.keyframe_insert("rotation_euler", frame=150)
act = ob.animation_data.action
slot = ob.animation_data.action_slot
if hasattr(slot, "fcurves"):
    for fc in slot.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
elif hasattr(act, "fcurves"):
    for fc in act.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
''',
    "keys_channelbag": MARK + '''
import bpy
from bpy_extras import anim_utils
ob = bpy.data.objects.new("chimera_logo", None)
bpy.context.scene.collection.objects.link(ob)
ob.keyframe_insert("rotation_euler", frame=1)
ob.rotation_euler[2] = 6.283185
ob.keyframe_insert("rotation_euler", frame=150)
act = ob.animation_data.action
if hasattr(act, "fcurves"):
    curves = act.fcurves
else:
    curves = anim_utils.action_get_channelbag_for_slot(act, ob.animation_data.action_slot).fcurves
for fc in curves:
    for kp in fc.keyframe_points:
        kp.interpolation = "LINEAR"
'''}
LINEAR_STEP = {"title": "Fixture", "kind": "blender", "summary": MARK, "steps": [
    {"id": "s1", "title": "Animate 360° Rotation", "kind": "blender", "depends_on": [],
     "instructions": "Insert a rotation keyframe at frame 1 and at frame 150. Ensure interpolation mode is Linear. " +
     MARK}]}
QUITS = MARK + "\nimport bpy, os\nos._exit(0)\n"
CRASHES = MARK + "\nimport bpy\nbpy.context.scene.render.image_settings.file_format = 'FFMPEG'\n"
# The direct run's fields the report must leave alone (its verdict, output lines, probes and measuring)
SAME = ("exit", "strict_full", "bad_lines", "blender", "version_ok", "stand_in", "stand_in_keys", "exception",
        "stopped_at_render", "ctx_keys", "names", "dupes", "scene", "ids", "ids_cut", "ctx_live", "ctx_dead",
        "ctx_values", "measure", "measure_failed", "probe_failed")


def ev(line, msg, type_="TypeError", origin="<script>", op="STORE_ATTR", handled="build_s1", **kw):
    """One handled-error event as the prelude records it."""
    return dict({"type": type_, "msg": msg, "line": line, "origin": origin, "op": op, "handled": handled}, **kw)


def rec(*events, **kw):
    return dict({"how": "monitoring", "cut": 0, "ev": list(events), "miss": [], "attr_miss": [], "hit": []}, **kw)


ENUM = 'bpy_struct: item.attr = val: enum "FFMPEG" not found in (\'JPEG\', \'OPEN_EXR\', \'PNG\')'
OPS = "/Applications/Blender.app/Contents/Resources/5.0/scripts/modules/bpy/ops.py"
STDLIB = "/Applications/Blender.app/Contents/Resources/5.0/python/lib/python3.11/json/decoder.py"
PIECE = MARK + '''
import bpy

SETTINGS_s1 = {"format": "FFMPEG"}


class Holder:
    pass


def build_s1(ctx):
    im = ctx["scene"].render.image_settings
    try:
        im.file_format = SETTINGS_s1["format"]
    except TypeError:
        pass
    try:
        im.file_format = "FFMPEG"
    except TypeError:
        im.media_type = "VIDEO"
        im.file_format = "FFMPEG"
    gpu = bpy.context.preferences.addons["cycles"].preferences
'''


def pl(text, code=PIECE):
    """The 1-based line of code that holds text."""
    return next(k for k, line in enumerate(code.split("\n"), 1) if text in line)


class ReadingTests(unittest.TestCase):
    """The rules on records shaped as the prelude writes them, no Blender."""

    def test_the_report_is_the_runners_own_line_and_its_code_compiles(self):
        self.assertTrue(S.SILENT_MARK.startswith(blender_run.WM_MARK))
        line = S.SILENT_MARK + json.dumps(rec(ev(3, "Error: Traceback (most recent call last):")))
        self.assertEqual(blender_check.bad_lines(blender_run.own_output("ok\n" + line + "\n")), [])
        compile(S.PRELUDE % {"path": "/run/script.py", "maxline": 40}, "<prelude>", "exec")
        compile(S.EPILOGUE, "<epilogue>", "exec")  # formatted once: no % left to format
        self.assertIn(repr(S.SILENT_MARK), S.EPILOGUE)
        self.assertEqual(G._marked_line("x\n" + line, S.SILENT_MARK)["ev"][0]["line"], 3)

    def test_what_is_watched(self):
        self.assertTrue(S.watched(rec()))
        self.assertTrue(S.watched(rec(how="settrace")))
        for r in (None, rec(how="none"), rec(how="missing"), {"how": "monitoring", "failed": "x"}, "x"):
            self.assertFalse(S.watched(r), r)

    def test_where_an_error_came_from(self):
        self.assertTrue(S.from_blender(ev(3, "x", origin=OPS, op=None)))  # Blender's own Python
        self.assertFalse(S.from_blender(ev(3, "x", origin=STDLIB, op=None)))  # its python/lib is Python's
        self.assertFalse(S.from_blender(ev(3, "x", origin="/Users/me/addon.py", op=None)))
        self.assertTrue(S.from_blender(ev(3, ENUM)))  # Blender's wording on the piece's own line
        self.assertTrue(S.from_blender(ev(3, "'Action' object has no attribute 'fcurves'", "AttributeError",
                                          op="LOAD_ATTR")))
        self.assertTrue(S.from_blender(ev(3, 'bpy_prop_collection[key]: key "Base_Color" not found', "KeyError",
                                          op="BINARY_SUBSCR")))
        self.assertFalse(S.from_blender(ev(3, ENUM, op="RAISE_VARARGS")))  # a raise of the piece's own
        self.assertFalse(S.from_blender(ev(3, ENUM, op="RERAISE")))
        self.assertFalse(S.from_blender(ev(3, "'sofa_width'", "KeyError", op="BINARY_SUBSCR")))  # a dict's
        self.assertFalse(S.from_blender(ev(3, "division by zero", "ZeroDivisionError", op="BINARY_OP")))
        none = ev(3, "'NoneType' object has no attribute 'inputs'", "AttributeError", op="LOAD_ATTR")
        self.assertFalse(S.from_blender(none))  # Python's own, though it's capitalised
        own = ev(3, "'Holder' object has no attribute 'size'", "AttributeError", op="LOAD_ATTR")
        self.assertTrue(S.from_blender(own))
        self.assertFalse(S.from_blender(own, {"Holder"}))  # a class the piece defines
        self.assertFalse(S.swallowed(PIECE, {V1: rec(own), V2: rec(own)}))

    def test_what_is_excused_and_why(self):
        quiet, fallback, gpu = pl('SETTINGS_s1["format"]'), pl('= "FFMPEG"'), pl(".preferences")
        cases = [
            (ev(gpu, "x"), "gpu"),  # another computer's GPU: `.preferences` on the source line
            (ev(quiet, "Add-on not loaded: cycles"), "addon"),
            (ev(quiet, "Operator bpy.ops.object.mode_set.poll() failed, context is incorrect", "RuntimeError"),
             "mode_set"),
            (ev(fallback, 'bpy_prop_collection[key]: key "x" not found', "KeyError",
                coll=[["BlendDataObjects", "id"]]), "get_or_create"),  # its handler does something: a fallback
            (ev(fallback, "bpy_prop_collection[index] = value: index 0 out of range, size 0", "IndexError"),
             "get_or_create"),  # an empty material slot list, filled in the handler (the step-6 checker's pieces)
            (ev(quiet, "bpy_prop_collection[index]: index 0 out of range, size 0", "IndexError"), ""),  # swallowed
            (ev(quiet, 'bpy_prop_collection[key]: key "x" not found', "KeyError",
                coll=[["BlendDataObjects", "id"]]), "exists_probe"),  # a quiet handler, bpy.data by name
            (ev(quiet, 'bpy_prop_collection[key]: key "x" not found', "KeyError", coll=[["Nodes", "node"]]),
             "exists_probe"),
            (ev(quiet, "[Errno 2] No such file or directory: 'a.png'", "FileNotFoundError"), "file"),
            (ev(quiet, 'Error: Cannot read file "/x/a.png": No such file or directory', "RuntimeError"), "file"),
            (ev(quiet, "Permission denied", "RuntimeError"), "file"),
            (ev(quiet, 'Calling operator "bpy.ops.object.x" error, could not be found', "AttributeError", origin=OPS,
                op=None), ""),  # a missing operator is the script's, as in Chimera (noOperator)
            (ev(quiet, ENUM), ""),
            (ev(quiet, 'bpy_prop_collection[key]: key "Base_Color" not found', "KeyError",
                coll=[["NodeInputs", "socket"]]), ""),  # a socket's name: the X06 kind of mistake, not a probe
        ]
        for e, why in cases:
            src = PIECE.split("\n")[e["line"] - 1].strip()
            self.assertEqual(S.excused(PIECE, e["line"], src, e), why, e["msg"])
        self.assertLessEqual({w for _, w in cases if w}, set(S.WHY))

    def test_swallowed_needs_every_version_and_counts_what_isnt_excused(self):
        quiet, fallback, again = pl('SETTINGS_s1["format"]'), pl('= "FFMPEG"'), pl('media_type') + 1
        e = ev(quiet, ENUM, meant="'FFMPEG'", landed=False)
        both = {V1: rec(e), V2: rec(e)}
        self.assertEqual(S.swallowed(PIECE, both), [{"line": quiet, "source": 'im.file_format = SETTINGS_s1["format"]',
                                                     "error": "TypeError: " + ENUM, "op": "STORE_ATTR",
                                                     "versions": BOTH}])
        self.assertEqual(S.swallowed(PIECE, {V1: rec(e), V2: rec()}), [])  # one version: a path it alone takes
        self.assertEqual(S.excused_events(PIECE, {V1: rec(e), V2: rec()}),
                         [{"line": quiet, "error": ("TypeError: " + ENUM)[:120], "why": "not_every_version",
                           "versions": [V1]}])
        unhandled = dict(e, handled=None)  # never handled in the piece (it crashed, or Blender's own code caught it)
        self.assertEqual(S.swallowed(PIECE, {V1: rec(unhandled), V2: rec(unhandled)}), [])
        self.assertEqual(S.excused_events(PIECE, {V1: rec(unhandled), V2: rec(unhandled)}), [])
        landed = dict(e, line=fallback, landed=True)  # the handler set the same target to the same value: it holds it
        self.assertEqual(S.swallowed(PIECE, {V1: rec(landed), V2: rec(landed)}), [])
        self.assertEqual([x["why"] for x in S.excused_events(PIECE, {V1: rec(landed), V2: rec(landed)})], ["landed"])
        other = dict(e, line=fallback, op="CALL")  # the same value assigned again in the handler: another way
        self.assertEqual([x["why"] for x in S.excused_events(PIECE, {V1: rec(other), V2: rec(other)})], ["another_way"])
        failed_too = rec(other, ev(again, ENUM, handled=None))  # ... unless the handler failed too
        self.assertEqual(len(S.swallowed(PIECE, {V1: failed_too, V2: failed_too})), 1)
        lone = {V1: rec(e)}  # judged over the versions given
        self.assertEqual(S.swallowed(PIECE, lone)[0]["versions"], [V1])
        mapped = S.swallowed(PIECE, both, lambda n: None if n == quiet else n)  # not the piece's line: not judged
        self.assertEqual(mapped, [])

    def test_a_dict_keyerror_isnt_blenders(self):
        e = ev(5, "'sofa_width'", "KeyError", op="BINARY_SUBSCR")
        code = MARK + '\nctx = {"values": {}}\ntry:\n    w = ctx["values"]["sofa_width"]\nexcept KeyError:\n    w = 2\n'
        e = dict(e, line=4)
        self.assertEqual(S.swallowed(code, {V1: rec(e), V2: rec(e)}), [])
        self.assertEqual([x["why"] for x in S.excused_events(code, {V1: rec(e), V2: rec(e)})], ["not_blender"])

    def test_a_skipped_input_needs_a_close_input_left_at_its_default_and_no_hit(self):
        miss = {"line": 6, "key": "Base_Color", "node": "ShaderNodeBsdfPrincipled", "node_name": "Principled BSDF",
                "ptr": 11, "side": "inputs", "close": ["Base Color"], "close_state": {"Base Color": "default"},
                "owner": "chimera_glass"}
        found = [{"line": 6, "key": "Base_Color", "owner": "chimera_glass", "node": "Principled BSDF",
                  "type": "ShaderNodeBsdfPrincipled", "close": ["Base Color"]}]
        self.assertEqual(S.skipped_sockets({V1: rec(miss=[miss]), V2: rec(miss=[dict(miss, ptr=22)])}), found)
        self.assertEqual(S.skipped_sockets({V1: rec(miss=[miss]), V2: rec()}), [])  # every version
        for state in ("set", "linked"):  # the input it meant was set another way
            m = dict(miss, close_state={"Base Color": state})
            self.assertEqual(S.skipped_sockets({V1: rec(miss=[m]), V2: rec(miss=[m])}), [], state)
        m = dict(miss, close=["Base Color", "Base Weight"], close_state={"Base Color": "default", "Base Weight": "set"})
        self.assertEqual(S.skipped_sockets({V1: rec(miss=[m]), V2: rec(miss=[m])}), [])
        hit = {"line": 6, "key": "Base Color", "node": 11}  # the same guard line found the real name on that node
        self.assertEqual(S.skipped_sockets({V1: rec(miss=[miss], hit=[hit]), V2: rec(miss=[miss], hit=[hit])}), [])
        other_node = dict(hit, node=99)
        self.assertEqual(len(S.skipped_sockets({V1: rec(miss=[miss], hit=[other_node]), V2: rec(miss=[miss])})), 1)
        out = dict(miss, side="outputs")  # an output is never judged
        self.assertEqual(S.skipped_sockets({V1: rec(miss=[out]), V2: rec(miss=[out])}), [])
        no_close = dict(miss, close=[], close_state={})
        self.assertEqual(S.skipped_sockets({V1: rec(miss=[no_close]), V2: rec(miss=[no_close])}), [])
        for capped in (rec(miss=[miss], hit_cut=True), rec(miss=[miss], trimmed={"hit": 3})):  # hits it may have lost
            self.assertEqual(S.skipped_sockets({V1: capped, V2: rec(miss=[miss])}), [])
        self.assertEqual(S.skipped_sockets({V1: rec(miss=[miss]), V2: rec(miss=[miss])}, lambda n: None), [])
        # a close input the piece's code names as a string was set on another path (to its default, here): the
        # step-6 checker's gold material, "Specular IOR Level" 0.5 through a one-line legacy-first conditional
        both = {V1: rec(miss=[miss]), V2: rec(miss=[miss])}
        named = MARK + '\nkey = "Base_Color" if OLD else "Base Color"\n'
        self.assertEqual(S.skipped_sockets(both, None, named), [])
        self.assertEqual(S.skipped_sockets(both, None, MARK + '\nkey = "Base_Color"\n# Base Color\n'), found)
        self.assertEqual(S.skipped_sockets(both, None, "def broken(:\n"), found)  # code that doesn't parse names none

    def test_attribute_misses_are_facts_in_every_version(self):
        a = {"line": 8, "attr": "fcurves", "on": "Action"}
        self.assertEqual(S.attr_misses({V1: rec(attr_miss=[a]), V2: rec(attr_miss=[a])}), [a])
        self.assertEqual(S.attr_misses({V1: rec(attr_miss=[a]), V2: rec()}), [])

    def test_the_words_that_ask_for_linear_keys(self):
        """asks_linear: the smoke runs' and the helper's raw plans' wordings (fixture text around them), never an image
        texture's, a shape key's or a colour ramp's interpolation, a linear mapping or a gradient."""
        for text in ("Ensure interpolation mode is Linear (Graph Editor > Key > Interpolation Mode > Linear).",
                     "3. Sets interpolation mode to Linear for constant speed.", "Ensure interpolation is linear.",
                     "Ensure linear interpolation for all keyframes.", "using interpolation \"LINEAR\" for rotation",
                     "set `keyframe.interpolation = 'LINEAR'`", "Use keyframe interpolation set to LINEAR.",
                     "frame 120 (Z=0.2), using linear interpolation."):
            self.assertTrue(S.asks_linear(text + " " + MARK), text)
        for text in ("Set texture interpolation to `Linear` and enable sRGB.", "a ColorRamp that interpolates",
                     "Sets the shape‑key interpolation mode to `LINEAR` for smooth opening.",
                     "Use a simple linear mapping: rate = strength * 10.", "a Gradient Texture (Linear)",
                     "Rotate it 360° over 150 frames.", ""):
            self.assertIsNone(S.asks_linear(text + " " + MARK), text)

    def test_a_guard_that_skipped_the_linear_keys_the_step_asks_for(self):
        """missed_keys (attr_miss's reason): a guard miss on the way to the keys in every version, the step asking
        for linear keys, and every version's keys present and none LINEAR; else nothing."""
        words = LINEAR_STEP["steps"][0]["instructions"]
        miss = {"line": 74, "attr": "fcurves", "on": "ActionSlot"}
        bezier = [{"name": "chimera_logoAction", "curves": 3, "interp": {"BEZIER": 6}}]
        both = {V1: rec(attr_miss=[miss], actions=bezier), V2: rec(attr_miss=[miss], actions=bezier)}
        self.assertEqual(S.missed_keys(both, None, words), [dict(miss, keys={"BEZIER": 6})])
        layer = {"line": 67, "attr": "slot", "on": "ActionLayer"}  # anything on an Action* struct counts
        self.assertEqual(len(S.missed_keys({v: rec(attr_miss=[layer], actions=bezier) for v in (V1, V2)}, None,
                                           words)), 1)
        self.assertEqual(S.missed_keys(both, lambda n: n - 70, words)[0]["line"], 4)  # through the line map
        linear = [{"name": "a", "curves": 3, "interp": {"LINEAR": 6}}]
        mixed = [{"name": "a", "curves": 3, "interp": {"BEZIER": 3, "LINEAR": 3}}]
        world = {"line": 3, "attr": "use_nodes", "on": "World"}
        for name, recs_, w in (
                ("the keys are linear", {v: rec(attr_miss=[miss], actions=linear) for v in (V1, V2)}, words),
                ("some keys are linear", {v: rec(attr_miss=[miss], actions=mixed) for v in (V1, V2)}, words),
                ("the step asks no linear keys", both, "Rotate the logo 360° over 150 frames. " + MARK),
                ("one version missed", {V1: rec(attr_miss=[miss], actions=bezier), V2: rec(actions=bezier)}, words),
                ("a guard off the keys' way", {v: rec(attr_miss=[world], actions=bezier) for v in (V1, V2)}, words),
                ("no keys", {v: rec(attr_miss=[miss], actions=[]) for v in (V1, V2)}, words),
                ("no action facts", {v: rec(attr_miss=[miss]) for v in (V1, V2)}, words)):
            self.assertEqual(S.missed_keys(recs_, None, w), [], name)

    def test_the_gate_makes_it_a_reason_and_tells_it(self):
        """measured_check on reports shaped as the prelude writes them: attr_miss alone, with its one line told; a
        joined run's is recorded only."""
        miss = {"line": 9, "attr": "fcurves", "on": "Action"}
        bezier = [{"name": "chimera_logoAction", "curves": 3, "interp": {"BEZIER": 6}}]
        run = {"probe": {v: {"silent": rec(attr_miss=[miss], actions=bezier)} for v in blenders.VERSIONS}}
        g = minimal_gate()
        code = KEYS["keys_guard_missed"]
        reasons, details = g.measured_check(LINEAR_STEP, 0, code, run)
        self.assertEqual(reasons, ["attr_miss"])
        self.assertEqual(details["silent"]["missed"], [dict(miss, keys={"BEZIER": 6})])
        self.assertEqual(details["faults"], S.missed_tell(details["silent"]["missed"]))
        self.assertIn("attr_miss", G.SOFT_GATE)  # it goes on to the joined check, as ctx_channel does
        self.assertEqual(G._hard(["attr_miss"]), [])
        self.assertEqual(g.measured_check(ONE_STEP, 0, code, run)[0], [])  # a step that asks no linear keys
        lm = {"origins": [None] + [["s1", "build", "build_s1", n] for n in range(1, 30)]}
        reasons, details = g.measured_check(LINEAR_STEP, 0, code, run, joined={"s1": "s1"}, codes={}, linemap=lm)
        self.assertEqual(reasons, [])
        self.assertEqual(len(details["joined_silent"]["missed"]), 1)  # recorded

    def test_the_missed_line_names_the_curves_and_is_ours(self):
        found = [{"line": 84, "attr": "fcurves", "on": "ActionKeyframeStrip", "keys": {"BEZIER": 6}}]
        (line,) = S.missed_tell(found)
        self.assertEqual(line, "line 84 looked for fcurves on ActionKeyframeStrip, which isn't there, so what it "
                               "guards never ran and the keys stayed BEZIER where the step asks for linear ones: set "
                               "interpolation on the keyframe_points of "
                               "anim_utils.action_get_channelbag_for_slot(action, slot).fcurves")
        self.assertLessEqual(len(line), S.TELL_CHARS)
        self.assertEqual(S.missed_tell([]), [])
        self.assertEqual(len(S.MISSED_FORMS), 2)
        for form in S.MISSED_FORMS:
            self.assertIn(form, line)
            self.assertIsNone(H.notes_leak(form, ""), form)
            w = H._WORD.findall(form)
            for k in range(len(w) - H.NOTE_N + 1):
                run = " ".join(w[k:k + H.NOTE_N])
                self.assertEqual(H.echoed_note("```python\n" + MARK + "\n# " + run + "\nimport bpy\n```"),
                                 "failure_line", run)
        # a piece that does what the line says repeats none of it
        self.assertIsNone(H.echoed_note("```python\n" + MARK + "\n" + KEYS["keys_channelbag"] + "```"))

    def test_a_joined_run_is_read_through_the_line_map(self):
        lm = {"origins": [None, ["s1", "build", "build_s1", 3], ["s2", "build", "build_s2", 7], ["", "output", "", 0]]}
        lo = S.joined_line_of(lm, "s2")
        self.assertEqual([lo(n) for n in (0, 1, 2, 3, 4, 5, None)], [None, None, None, 7, None, None, None])
        self.assertIsNone(S.joined_line_of(None, "s1")(1))

    def test_the_tells_say_what_was_hidden_within_their_length(self):
        long_src = "bpy.context.scene.render.image_settings.file_format = SETTINGS_s1['render_output_format_name']"
        long_err = "TypeError: " + ENUM + " and on and on " * 20
        lines = S.tell([{"line": 14, "source": long_src, "error": long_err},
                        {"line": 9, "source": "curves = list(action.fcurves)",
                         "error": "AttributeError: 'Action' object has no attribute 'fcurves'"},
                        {"line": 11, "source": "x.y = 1", "error": "AttributeError: bpy_struct: attribute \"y\" from "
                                                                  "\"Thing\" is read-only"},
                        {"line": 30, "source": "never told", "error": "TypeError: a fourth"}],
                       [{"line": 6, "key": "Base_Color", "owner": "chimera_glass", "node": "Principled BSDF",
                         "close": ["Base Color"]},
                        {"line": 6, "key": "Base_Color", "owner": "chimera_gold", "node": "Principled BSDF",
                         "close": ["Base Color"]},  # the same lookup on another material: told once
                        {"line": 6, "key": "Specular_" + "x" * 80, "owner": "m" * 70, "node": "n" * 70,
                         "close": ["Specular IOR Level", "Specular Tint", "Specular Anisotropy"]}])
        self.assertEqual(len(lines), 5)  # 3 of the swallowed (TELL_EACH), 2 lookups
        self.assertTrue(all(len(l) < 300 for l in lines), [len(l) for l in lines])
        self.assertTrue(lines[0].startswith("line 14 `bpy.context.scene.render"), lines[0])
        self.assertIn("raised TypeError: bpy_struct: item.attr = val: enum \"FFMPEG\" not found", lines[0])
        self.assertTrue(lines[0].endswith("so that line did nothing: fix the call itself instead of catching its "
                                          "error"))
        self.assertEqual(lines[1], "line 9 `curves = list(action.fcurves)`: AttributeError: 'Action' object has no "
                                   "attribute 'fcurves', and the piece's own except caught it: that name isn't in the "
                                   "Blender the piece runs in, so write only the code that works there, with no try "
                                   "around it")
        self.assertIn("` raised AttributeError: bpy_struct", lines[2])  # read-only: no missing name to blame
        self.assertEqual(lines[3], "line 6 looked up the input 'Base_Color' on chimera_glass's Principled BSDF, which "
                                   "has no input of that name (it has 'Base Color'), so the lookup was skipped and "
                                   "Base Color stayed at its default: use the input's real name")
        self.assertIn("(it has 'Specular IOR Level'", lines[4])
        versioned = S.tell([{"line": 2, "source": "x = 1", "error": "RuntimeError: Error: only in Blender 5.2.2"}], [])
        self.assertIn("only in the newer Blender", versioned[0])
        self.assertFalse(any(v in l for l in lines + versioned for v in blenders.VERSIONS))

    def test_the_tell_wording_is_ours_and_a_reply_repeating_it_is_refused(self):
        self.assertEqual(S.TELL_FORMS, (
            "and the piece's own except caught it: that name isn't in the Blender the piece runs in, so write only "
            "the code that works there, with no try around it",
            "and the piece's own except caught it, so that line did nothing: fix the call itself instead of catching "
            "its error",
            "which has no input of that name (it has", "so the lookup was skipped and",
            "stayed at its default: use the input's real name"))
        k = G.TELL_FORMS.index(S.TELL_FORMS[0])  # the gate's, which echoed_note reads; geometry's forms follow
        self.assertEqual(G.TELL_FORMS[k:k + len(S.TELL_FORMS)], S.TELL_FORMS)
        lines = S.tell([{"line": 9, "source": "a = b.c", "error": "AttributeError: 'X' object has no attribute 'c'"},
                        {"line": 4, "source": "im.file_format = 'FFMPEG'", "error": "TypeError: " + ENUM}],
                       [{"line": 6, "key": "Base_Color", "owner": "glass", "node": "Principled BSDF",
                         "close": ["Base Color"]}])
        for form in S.TELL_FORMS:
            self.assertTrue(any(form in l for l in lines), form)
            self.assertGreaterEqual(len(H._WORD.findall(form)), H.NOTE_MIN)
            self.assertIsNone(H.notes_leak(form, ""), form)
            self.assertEqual(H.echoed_note("```python\n" + MARK + "\n# " + form + "\nimport bpy\n```"), "failure_line",
                             form)
        # a reply that does what the lines say, in its own words, repeats none of them
        self.assertIsNone(H.echoed_note("```python\n" + MARK + "\nimport bpy\nbsdf.inputs['Base Color']"
                                        ".default_value = (1, 1, 1, 1)\n```\nassumed: the glass uses the real input "
                                        "names, set without a try"))


_tmp = None
_with = {}  # name: {version: direct run record}, with the prelude and the report
_without = {}  # the same 24 pieces with neither (the gate before step 6a)
SAME_ON = list(REFUTER) + ["skipped_wrong_names", "handled_outer"]


class _Chimera:
    binary = "/nonexistent/chimera"  # the direct run never calls Chimera


def setUpModule():
    global _tmp
    if not HAVE_BLENDER:
        return
    _tmp = tempfile.mkdtemp(prefix="test-datagen-silent-", dir=blender_check.scratch_root())
    gb = G.GateBlender(_Chimera(), blenders.VERSIONS, os.path.join(_tmp, "work"), 180.0, 120.0,
                       threading.BoundedSemaphore(4))
    os.makedirs(gb.work, exist_ok=True)

    def run_all(names, into):
        jobs = [(k, v, b) for k in names for v, b in blenders.VERSIONS.items()]
        with ThreadPoolExecutor(4) as pool:
            for k, v, out in pool.map(lambda j: (j[0], j[1], gb._probe_one(PIECES[j[0]], j[2], j[1])), jobs):
                into.setdefault(k, {})[v] = out
    run_all(list(PIECES), _with)
    prelude, epilogue = S.PRELUDE, S.EPILOGUE
    S.PRELUDE, S.EPILOGUE = "pass\n", ""  # what the direct run was before the report: the same script, no watching
    try:
        run_all(SAME_ON, _without)
    finally:
        S.PRELUDE, S.EPILOGUE = prelude, epilogue


def tearDownModule():
    if _tmp:
        shutil.rmtree(_tmp, ignore_errors=True)


PIECES = dict(REFUTER, **OURS, **KEYS, quits=QUITS, crashes=CRASHES)


def recs(name):
    return {v: r.get("silent") for v, r in _with[name].items()}


def minimal_gate():
    """A BlenderGate for measured_check alone, which reads only its versions (no Chimera, no cache, no lint)."""
    g = G.BlenderGate.__new__(G.BlenderGate)
    g.versions = dict(blenders.VERSIONS)
    return g


ONE_STEP = {"title": "Fixture", "kind": "blender", "summary": MARK, "steps": [
    {"id": "s1", "title": "Settings", "kind": "blender", "instructions": "Set the scene up. " + MARK,
     "depends_on": []}]}


@unittest.skipUnless(HAVE_BLENDER, "needs Blender " + " and ".join(blenders.VERSIONS))
class BlenderTests(unittest.TestCase):
    """The prelude and the report in real Blender, through the gate's own direct run."""

    def test_every_run_was_watched_the_way_its_python_allows(self):
        for name in list(REFUTER) + list(OURS):
            for v, r in recs(name).items():
                self.assertTrue(S.watched(r), (name, v, _with[name][v].get("output_tail")))
                self.assertEqual(_with[name][v]["exit"], 0, (name, v))
        if "5.2.2" in blenders.VERSIONS:  # Python 3.13: sys.monitoring
            self.assertEqual(recs("handled_outer")["5.2.2"]["how"], "monitoring")
        if "5.0.1" in blenders.VERSIONS:  # Python 3.11: sys.settrace
            self.assertEqual(recs("handled_outer")["5.0.1"]["how"], "settrace")

    def test_the_refuters_fixtures_get_the_verdicts_measured(self):
        for name, code in REFUTER.items():
            with self.subTest(name):
                r = recs(name)
                self.assertEqual([f["line"] for f in S.swallowed(code, r)],
                                 [n + 1 for n in REFUTER_SWALLOWED.get(name, [])])
                self.assertEqual(S.skipped_sockets(r), [])
                self.assertEqual([(e["line"], e["why"]) for e in S.excused_events(code, r)],
                                 [(n + 1, why) for n, why in REFUTER_EXCUSED.get(name, [])])
        # X07 with its slot fixed still reads the removed fcurves in a try (policy B), and its hasattr probe is a fact
        r = recs("r1_x07_slot_fixed")
        self.assertEqual(S.attr_misses(r), [{"line": 48, "attr": "fcurves", "on": "ActionKeyframeStrip"}])

    def test_our_pieces_get_theirs(self):
        for name, code in OURS.items():
            with self.subTest(name):
                r = recs(name)
                self.assertEqual([f["line"] for f in S.swallowed(code, r)], OURS_SWALLOWED.get(name, []))
                self.assertEqual([(f["line"], f["key"]) for f in S.skipped_sockets(r)], OURS_SKIPPED.get(name, []))
        found = S.skipped_sockets(recs("skipped_wrong_names"))
        self.assertEqual([(f["owner"], f["node"], f["type"], f["close"]) for f in found],
                         [("chimera_glass", "Principled BSDF", "ShaderNodeBsdfPrincipled", ["Base Color"]),
                          ("chimera_glass", "Principled BSDF", "ShaderNodeBsdfPrincipled", ["Transmission Weight"])])
        for v, rec_ in recs("skipped_wrong_names").items():  # Roughness was found: a hit, not a miss
            self.assertIn("Roughness", [h["key"] for h in rec_["hit"]], v)

    def test_an_error_handled_in_an_outer_function_is_handled_by_that_code(self):
        """5.2.2's EXCEPTION_HANDLED offset maps to no line and its f_lineno is still the raising line, so the
        handler is the code object: setup's, whose first line is in the piece."""
        for v, r in recs("handled_outer").items():
            with self.subTest(v):
                e = next(x for x in r["ev"] if x["line"] == 4)
                self.assertEqual((e["handled"], e["handled_in"], e["op"], e["meant"], e["landed"]),
                                 ("setup", 6, "STORE_ATTR", "'FFMPEG'", False))
                self.assertNotIn("handled_line", e)
        f = S.swallowed(OURS["handled_outer"], recs("handled_outer"))[0]
        self.assertEqual((f["source"], f["versions"]), ('im.file_format = "FFMPEG"', BOTH))

    def test_an_error_caught_outside_the_pieces_own_code_isnt_its_except(self):
        for v, r in recs("caught_by_c").items():
            e = next(x for x in r["ev"] if x["line"] == 6)
            self.assertIsNone(e["handled"], v)  # hasattr (C) caught it: no handler of the piece's ran
        self.assertEqual(S.excused_events(OURS["caught_by_c"], recs("caught_by_c")), [])

    def test_a_missing_file_is_excused_and_a_missing_operator_isnt(self):
        code, r = OURS["file_and_operator"], recs("file_and_operator")
        self.assertEqual([(e["line"], e["why"]) for e in S.excused_events(code, r)], [(4, "file"), (8, "not_blender")])
        f = S.swallowed(code, r)[0]
        self.assertIn("could not be found", f["error"])
        tell = S.tell([f], [])[0]
        self.assertIn("that name isn't in the Blender the piece runs in", tell)

    def test_a_handled_dict_keyerror_a_stand_in_isnt_counted(self):
        code, r = OURS["values_stand_in"], recs("values_stand_in")
        self.assertEqual(S.swallowed(code, r), [])
        self.assertEqual([(e["line"], e["why"]) for e in S.excused_events(code, r)], [(5, "not_blender")])

    def test_the_report_stays_within_its_budget(self):
        for v, r in recs("many").items():
            with self.subTest(v):
                self.assertLessEqual(len(json.dumps(r, separators=(",", ":"))), S.SILENT_BUDGET)
                self.assertEqual(r["cut"], 100)  # 400 errors, 300 recorded
                self.assertGreater(r["trimmed"]["ev"], 200)
                self.assertEqual(r["dropped"], ["materials", "actions", "render"])  # the facts go first
                self.assertTrue(r["ev"])
        self.assertEqual([f["line"] for f in S.swallowed(OURS["many"], recs("many"))], [6])

    def test_the_report_leaves_the_verdict_alone(self):
        for name in SAME_ON:
            for v in blenders.VERSIONS:
                with self.subTest((name, v)):
                    a, b = _without[name][v], _with[name][v]
                    self.assertEqual({k: a.get(k) for k in SAME}, {k: b.get(k) for k in SAME})
                    self.assertNotIn("silent", a)
                    self.assertTrue(S.watched(b.get("silent")))

    def test_a_run_that_stops_first_prints_no_report_and_nothing_is_judged(self):
        g = minimal_gate()
        for name in ("quits", "crashes"):
            for v, r in _with[name].items():
                self.assertNotIn("silent", r, (name, v))
            self.assertNotEqual(_with["crashes"][next(iter(blenders.VERSIONS))]["exit"], 0)
            reasons, details = g.measured_check(ONE_STEP, 0, PIECES[name], {"probe": _with[name]})
            self.assertEqual((reasons, details), ([], {}), name)
        # ... and one version without it is enough to judge nothing
        half = {"probe": dict(_with["handled_outer"], **{V2: _with["quits"][V2]})}
        self.assertEqual(g.measured_check(ONE_STEP, 0, OURS["handled_outer"], half), ([], {}))
        reasons, details = g.measured_check(ONE_STEP, 0, OURS["handled_outer"], {"probe": _with["handled_outer"]})
        self.assertEqual(reasons, ["swallowed"])
        self.assertEqual([f["line"] for f in details["silent"]["swallowed"]], [4])
        self.assertEqual(details["faults"], S.tell(details["silent"]["swallowed"], []))

    def test_real_keys_left_bezier_behind_a_guard(self):
        """In both Blenders: the hasattr fallbacks find no fcurves on the slot or the Action, so the keys stay BEZIER
        and the step's linear keys are missed (attr_miss); the channelbag path, behind the same kind of miss, sets
        LINEAR, and nothing is missed."""
        g = minimal_gate()
        missed = recs("keys_guard_missed")
        for v, r in missed.items():
            self.assertEqual([a["interp"] for a in r["actions"]], [{"BEZIER": 6}], v)
        self.assertEqual([(m["line"], m["attr"], m["on"]) for m in S.attr_misses(missed)],
                         [(10, "fcurves", "ActionSlot"), (14, "fcurves", "Action")])
        reasons, details = g.measured_check(LINEAR_STEP, 0, KEYS["keys_guard_missed"],
                                            {"probe": _with["keys_guard_missed"]})
        self.assertEqual(reasons, ["attr_miss"])
        self.assertEqual(details["silent"]["missed"][0]["keys"], {"BEZIER": 6})
        right = recs("keys_channelbag")
        for v, r in right.items():
            self.assertEqual([a["interp"] for a in r["actions"]], [{"LINEAR": 6}], v)
        self.assertEqual([m["attr"] for m in S.attr_misses(right)], ["fcurves"])  # the old guard missed here too
        right_run = {"probe": _with["keys_channelbag"]}
        self.assertEqual(g.measured_check(LINEAR_STEP, 0, KEYS["keys_channelbag"], right_run)[0], [])

    def test_the_tells_of_real_records_fit_and_are_refused_when_repeated(self):
        lines = []
        for name in OURS:
            code, r = OURS[name], recs(name)
            lines += S.tell(S.swallowed(code, r), S.skipped_sockets(r))
        self.assertEqual(len(lines), 5)  # handled_outer, the operator, many; the two skipped lookups
        for line in lines:
            self.assertLess(len(line), 300, line)
            self.assertEqual(H.echoed_note("```python\n" + MARK + "\nimport bpy\n```\nassumed: " + line),
                             "failure_line", line)


if __name__ == "__main__":
    unittest.main()
