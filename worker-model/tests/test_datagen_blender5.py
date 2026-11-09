"""After the fourth smoke (Nov 5): what the teacher's new Blender notes say (datagen/hints.BLENDER5's facts and
CAMERA_NOTE), each claim checked in real Blender 5.2.2 and 5.0.1, sandboxed as the data generator runs a tool
(pysandbox.run_tool, --factory-startup), so a note never tells the teacher something either Blender doesn't do. The
probe is Claude-written test text and carries the fixture mark; nothing of it is training data. About 2 s; skipped
without the Blenders or sandbox-exec."""
import os
import re
import unittest

from tests import _paths  # noqa: F401
from datagen import hints as H
from datagen import pysandbox
from runner.mock_ollama import MARK
from tools import blenders

HAVE_BLENDER = all(not blenders.check_path(p) for p in blenders.VERSIONS.values())

# Each claim: (the fact or note it backs, its name), then the code that makes check(...) true or false
PROBE = MARK + '''
import bpy, os
s = bpy.context.scene
def check(fact, name, cond, info=""):
    print("PROBE", "PASS" if cond else "FAIL", fact, "|", name, "|", info, flush=True)
check("compositor", "a fresh scene's PNG is RGBA", (s.render.image_settings.file_format, s.render.image_settings.color_mode) == ("PNG", "RGBA"))
# keyframes
ob = bpy.data.objects.new("chimera_k", None); s.collection.objects.link(ob)
check("keyframes", "no action_slot before the first key", ob.animation_data is None or ob.animation_data.action_slot is None)
ob.keyframe_insert("rotation_euler", frame=1); ob.rotation_euler[2] = 6.283185; ob.keyframe_insert("rotation_euler", frame=121)
act = ob.animation_data.action
check("keyframes", "an Action has no fcurves", not hasattr(act, "fcurves"))
from bpy_extras import anim_utils
cb = anim_utils.action_get_channelbag_for_slot(act, ob.animation_data.action_slot)
check("keyframes", "the channelbag holds keyframe_insert's curves", cb is not None and len(cb.fcurves) == 3)
check("keyframes", "a slot of None gives no channelbag", anim_utils.action_get_channelbag_for_slot(act, None) is None)
for fc in cb.fcurves:
    for kp in fc.keyframe_points:
        kp.interpolation = "LINEAR"
s.frame_set(61)
check("keyframes", "its keyframe_points' interpolation is what plays", abs(ob.rotation_euler[2] - 3.14159) < 1e-3, round(ob.rotation_euler[2], 4))
# video
im = s.render.image_settings
try:
    im.file_format = "FFMPEG"
    check("video", "file_format FFMPEG alone raises TypeError", False)
except TypeError:
    check("video", "file_format FFMPEG alone raises TypeError", True)
im.media_type = "VIDEO"
check("video", "media_type VIDEO turns file_format to FFMPEG", im.file_format == "FFMPEG")
s.render.ffmpeg.format = "MPEG4"; s.render.ffmpeg.codec = "H264"
check("video", "the container is ffmpeg.format, the codec ffmpeg.codec", (s.render.ffmpeg.format, s.render.ffmpeg.codec) == ("MPEG4", "H264"))
check("video", "there is no ffmpeg.container", not hasattr(s.render.ffmpeg, "container"))
im.media_type = "IMAGE"; im.file_format = "PNG"
# compositor
check("compositor", "a scene has no node_tree", not hasattr(s, "node_tree"))
check("compositor", "there is no Composite node", not hasattr(bpy.types, "CompositorNodeComposite"))
ng = bpy.data.node_groups.new("chimera_comp", "CompositorNodeTree")
ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
go = ng.nodes.new("NodeGroupOutput")
rl = ng.nodes.new("CompositorNodeRLayers")
inv = ng.nodes.new("CompositorNodeInvert")
ng.links.new(rl.outputs["Image"], inv.inputs["Color"])
ng.links.new(inv.outputs[0], go.inputs["Image"])
s.compositing_node_group = ng
check("compositor", "scene.compositing_node_group takes the group", s.compositing_node_group == ng)
# svg
svg = os.path.join(os.getcwd(), "chimera_logo.svg")
open(svg, "w").write('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><path d="M10 10 L90 10 L90 90 L10 90 Z"/></svg>')
before = set(bpy.data.objects.keys())
r = bpy.ops.import_curve.svg(filepath=svg)
new = [bpy.data.objects[n] for n in set(bpy.data.objects.keys()) - before]
check("svg", "import_curve.svg adds curve objects", r == {"FINISHED"} and new and all(o.type == "CURVE" for o in new))
check("svg", "in a new collection named after the file", all("chimera_logo.svg" in [c.name for c in o.users_collection] for o in new))
check("svg", "about 0.28 mm per SVG pixel", all(abs(o.dimensions.x / 80 - 0.00028) < 0.00001 for o in new), [o.dimensions.x for o in new])
check("svg", "there is no wm operator for it", "svg_import" not in dir(bpy.ops.wm))
# extrude
def zr(o):
    dg = bpy.context.evaluated_depsgraph_get(); e = o.evaluated_get(dg); m = e.to_mesh()
    z = [(o.matrix_world @ v.co).z for v in m.vertices]; e.to_mesh_clear()
    return (round(min(z), 4), round(max(z), 4)) if z else None
for kind in ("CURVE", "FONT"):
    cu = bpy.data.curves.new("chimera_" + kind, kind)
    if kind == "CURVE":
        cu.dimensions = "2D"; cu.fill_mode = "BOTH"
        sp = cu.splines.new("POLY"); sp.points.add(3)
        for k, (x, y) in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
            sp.points[k].co = (x, y, 0, 1)
        sp.use_cyclic_u = True
    else:
        cu.body = "Hi"
    o = bpy.data.objects.new("chimera_" + kind, cu); s.collection.objects.link(o)
    cu.extrude = 0.08
    check("extrude", kind + ": extrude 0.08 spans -0.08 to 0.08", zr(o) == (-0.08, 0.08), zr(o))
    cu.extrude = -0.08
    check("extrude", kind + ": a negative extrude is taken as 0", cu.extrude == 0.0)
    cu.extrude = 0.04; o.location.z = -0.04
    check("extrude", kind + ": extrude d/2 moved d/2 that way spans -d to 0", zr(o) == (-0.08, 0.0), zr(o))
    cu.extrude = 0.0; o.location.z = 0
    if kind == "CURVE":
        md = o.modifiers.new("chimera_depth", "SOLIDIFY"); md.thickness = 0.08; md.offset = -1
        check("extrude", "a Solidify of d at offset -1 on a flat filled curve spans -d to 0", zr(o) == (-0.08, 0.0), zr(o))
        o.modifiers.remove(md)
for o in new:  # the imported SVG curve, either winding: the Solidify goes below too
    md = o.modifiers.new("chimera_depth", "SOLIDIFY"); md.thickness = 0.08; md.offset = -1
    check("extrude", "a Solidify at offset -1 on an imported SVG curve spans -d to 0", zr(o) == (-0.08, 0.0), zr(o))
# subsurface
m = bpy.data.materials.new("chimera_wax")
try:
    m.use_nodes = True
except Exception:
    pass
n = m.node_tree.nodes.new("ShaderNodeSubsurfaceScattering")
try:
    n.inputs["Weight"]
    check("subsurface", "the Subsurface Scattering node's inputs['Weight'] raises KeyError", False)
except KeyError:
    check("subsurface", "the Subsurface Scattering node's inputs['Weight'] raises KeyError", True)
p = m.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
check("subsurface", "a Principled BSDF has Subsurface Weight", "Subsurface Weight" in p.inputs)
# camera: a render uses scene.camera, and the start-up scene has its own there
check("camera", "the start-up scene's camera is scene.camera", s.camera is not None and s.camera.name == "Camera")
cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera")); s.collection.objects.link(cam)
check("camera", "a new camera named like it becomes Camera.001", cam.name == "Camera.001")
check("camera", "and isn't the scene's until it is made so", s.camera != cam)
# transparent PNG: film_transparent with the PNG at RGBA, and the compositor group above inverts
s.render.engine = "CYCLES"; s.cycles.device = "CPU"; s.cycles.samples = 1
s.render.resolution_x = s.render.resolution_y = 8; s.render.resolution_percentage = 100
if hasattr(s.render, "compositor_device"):
    s.render.compositor_device = "CPU"  # the sandbox has no GPU for the compositor
s.camera = bpy.data.objects["Camera"]
s.render.image_settings.color_mode = "RGBA"
def render(name, transparent, group):
    s.render.film_transparent = transparent
    s.compositing_node_group = group
    out = os.path.join(os.getcwd(), name); s.render.filepath = out
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(out)
    px = list(img.pixels)
    return img.channels, px
ch, px = render("t.png", True, None)
ch0, px0 = render("o.png", False, None)
check("compositor", "film_transparent alone gives a transparent PNG", ch == 4 and min(px[3::4]) == 0.0 and min(px0[3::4]) == 1.0)
_, inverted = render("i.png", False, ng)
check("compositor", "a render gets what reaches the group's Group Output", abs(inverted[0] - px0[0]) > 0.1, (px0[0], inverted[0]))
'''


@unittest.skipUnless(HAVE_BLENDER and pysandbox.can_sandbox(), "needs Blender 5.2.2, 5.0.1 and sandbox-exec")
class NotesHoldInBlenderTests(unittest.TestCase):
    def test_every_claim_holds_in_both_blenders(self):
        names = {f["name"] for f in H.BLENDER5}
        self.assertEqual(names, {"keyframes", "video", "compositor", "svg", "extrude", "subsurface"})
        self.assertIn("scene.camera", H.CAMERA_NOTE)
        for v, binary in blenders.VERSIONS.items():
            r = pysandbox.run_tool({"main.py": PROBE}, binary,
                                   ["-b", "--factory-startup", "--python-exit-code", "1", "--python", "main.py"],
                                   timeout=180, work=os.environ.get("WM_SCRATCH"))
            self.assertEqual(r["exit"], 0, r["output"][-1500:])
            self.assertTrue(r["sandboxed"])
            got = re.findall(r"^PROBE (PASS|FAIL) (\w+) \| ([^|]*) \|", r["output"], re.M)
            self.assertEqual([(f, n.strip()) for ok, f, n in got if ok != "PASS"], [], v)
            self.assertEqual({f for _, f, _ in got}, names | {"camera"}, v)  # every fact is checked
            self.assertGreaterEqual(len(got), 30, v)


# Since the fifth smoke (Nov 6): the keyframes fact and fix name the slot. The fix's own expression (CALL, filled in
# from hints.KEYFRAMES_FIX) is run as written, with obj the animated ID and action its action.
SLOT_PROBE = MARK + '''
import bpy
import bpy_extras
try:  # a plain import loads no anim_utils (the checks of Nov 6): the fact's dotted name fails after it
    print("PLAIN", bpy_extras.anim_utils.__name__, flush=True)
except AttributeError as e:
    print("PLAIN AttributeError:", e, flush=True)
from bpy_extras import anim_utils
s = bpy.context.scene
def check(name, cond, info=""):
    print("PROBE", "PASS" if cond else "FAIL", name, "|", info, flush=True)
def fix(obj, action):
    return CALL
ob = bpy.data.objects.new("chimera_k", None); s.collection.objects.link(ob)
check("an object has no animation_data before its first key", ob.animation_data is None)
ob.keyframe_insert("rotation_euler", frame=1)
check("the first keyframe_insert sets the slot", ob.animation_data.action_slot is not None)
ob.rotation_euler[2] = 6.283185; ob.keyframe_insert("rotation_euler", frame=121)
curves = fix(ob, ob.animation_data.action)
check("the fix's expression gives keyframe_insert's F-curves", sorted(fc.data_path for fc in curves) ==
      ["rotation_euler"] * 3, len(curves))
for fc in curves:
    for kp in fc.keyframe_points:
        kp.interpolation = "LINEAR"
s.frame_set(61)
check("LINEAR set there is what plays", abs(ob.rotation_euler[2] - 3.14159) < 1e-3, round(ob.rotation_euler[2], 4))
cam = bpy.data.objects.new("chimera_cam", bpy.data.cameras.new("chimera_cam")); s.collection.objects.link(cam)
cam.data.keyframe_insert("lens", frame=1)
check("a camera data's keys: the animated ID is the data", [fc.data_path for fc in
      fix(cam.data, cam.data.animation_data.action)] == ["lens"] and cam.animation_data is None)
ob3 = bpy.data.objects.new("chimera_k3", None); s.collection.objects.link(ob3)
ob3.animation_data_create(); ob3.animation_data.action = bpy.data.actions.new("chimera_act")
check("an action assigned by hand has no slot before a key", ob3.animation_data.action_slot is None)
ob3.keyframe_insert("location", frame=1)
check("its first keyframe_insert sets it", len(fix(ob3, ob3.animation_data.action)) == 3)
'''


@unittest.skipUnless(HAVE_BLENDER and pysandbox.can_sandbox(), "needs Blender 5.2.2, 5.0.1 and sandbox-exec")
class TheSlotHoldsInBlenderTests(unittest.TestCase):
    def test_the_slot_the_keyframes_note_and_fix_name(self):
        note = next(f["note"] for f in H.BLENDER5 if f["name"] == "keyframes")
        self.assertIn("obj.animation_data.action_slot", note)
        call = re.fullmatch(r"use (anim_utils\.action_get_channelbag_for_slot\(action, "
                            r"obj\.animation_data\.action_slot\)\.fcurves)", H.KEYFRAMES_FIX).group(1)
        for v, binary in blenders.VERSIONS.items():
            r = pysandbox.run_tool({"main.py": SLOT_PROBE.replace("CALL", call)}, binary,
                                   ["-b", "--factory-startup", "--python-exit-code", "1", "--python", "main.py"],
                                   timeout=180, work=os.environ.get("WM_SCRATCH"))
            self.assertEqual(r["exit"], 0, r["output"][-1500:])
            self.assertTrue(r["sandboxed"])
            got = re.findall(r"^PROBE (PASS|FAIL) ([^|]*) \|", r["output"], re.M)
            self.assertEqual(len(got), 7, v)
            self.assertEqual([n.strip() for ok, n in got if ok != "PASS"], [], v)
            # Blender's own message after a plain import bpy_extras ends with the import fix
            (plain,) = re.findall(r"^PLAIN (.*)$", r["output"], re.M)
            self.assertEqual(H.fix_for({"line": 8, "source": "bpy_extras.anim_utils", "error": plain}),
                             H.ANIM_UTILS_FIX, (v, plain))


if __name__ == "__main__":
    unittest.main()
