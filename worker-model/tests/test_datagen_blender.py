"""datagen/blender_gate.py in real Blender (5.2.2 and 5.0.1, tools/blenders.VERSIONS), sandboxed, with a Chimera binary
built from app/ once per run into a scratch folder ($WM_SCRATCH, else data/scratch/; $CHIMERA_BIN's, copied there,
when it names one) and removed afterwards. Skipped without Go (or CHIMERA_BIN) or either Blender. Chimera's Ollama is
a stand-in (runner/mock_ollama), so the real one is never asked.

Every piece here is a hand-written test fixture (its code starts with the mark), never training data: a floor and a
box that pass alone, joined and as a plan; a box with a lint error (the Principled BSDF's old "Transmission"
input), whose real crash is still found for a repair; a box that crashes in its build function alone, and one that
crashes only when joined (the floor it's given lacks a property its own stand-in has), each located in the piece's
own lines and taken by --hydra-worker-request as a repair's crash, from the version asked for first; a box whose
handoff provides a name it never makes; a rug that deletes the floor (removes_earlier in its own check, the plan
check's provides_lost); a box that prints a stand-in although its dependency is there (fails), one whose dependency
was dropped (allowed), and one after a floor whose own dependency was dropped that prints a stand-in for that floor
(fails); a plan whose join renders, still probed at its end, and one whose output paths are absolute, saved in the
run folder instead. The direct run: a hung one stops at its timeout and dies with the process that started it even
by kill -9; one that never got to Blender's Python is a problem, not cached, and one that ends by os._exit (losing
Blender's header) is a verdict. A second identical check runs no Blender. Stand-in runs (no Blender) check the
semaphore, one run per script at a time, and that a run with no verdict isn't cached.

The measuring and the measured checks: an island the size its step gives passes, turned too, and one half that size
fails alone with the measured numbers to tell (no repair: nothing crashed); a ceiling light turned over fails, and
one turned over but aimed down by a Track To constraint passes (the scene is evaluated); a piece that sets an output
path for a step that asks for none fails; a bench sized by a values step measures its fallback alone and is held to
those values only joined after that step (a half-size one fails there, at stage "joined"; a variant, or a join
without the values step, isn't held to them), and a right bench is left unjudged, not failed, when the joined
measure is cut before it (45 posts whose names sort first) or the values piece sets other numbers than its words (as
is one that writes the words in); the scene a judge sees lists sizes, locations at the current frame,
modifiers, animation, lights, a camera and a node group, and says the engine and the world are the factory's; a box
its weld modifier empties is listed with its size before the modifier, beside an engine the piece's code set; a
script's own handlers can't print into the verdict while the scene is measured; and a stand-in marker written with
U+2011 is seen. The readers (sizes and what each is the size of, read past "is about" or "which measures"; whose
step makes a thing, so a size no other step makes is asked whatever the verb; sides by name, and those a values
piece's settings set; aims and an angle given with "down", from vertical, or anywhere else in the clause, which then
asks nothing; output paths), the faults on hand-made measuring lines (a size line names the thing and its source,
never the step's phrase; a size the measuring left out is unmeasured), the rule that a fault counts only when every
version shows it, sizes from a values step held to the joined measure and to what the values piece sets, the
listing's notes and engine labels, and the tell lines are checked without Blender.

The scene's camera and the outputs (the second smoke's audit): the measuring records the camera a render uses (the
factory's, one a script made and set, none); a camera the step asks for by the factory camera's own name ("Camera",
so Blender makes Camera.001) passes alone, joined and in the plan check while it is the scene's camera, and is a
duplicate when the factory camera still renders; a camera the step adds that never becomes the scene's fails
camera_not_active alone (a variant too), with no repair; a render the step asks for that the piece never hands to
Chimera fails output_missing alone, told the step's own file name. Without Blender: what a step asks Chimera to make
(a named .blend, a render as a verb, not when optional, negated or left to another step) and what a piece's
SETTINGS_sN["output"] hands over, the tell's length and names, a camera of the step's own and the scene camera's
facts, the factory copy's rules, and the ctx keys and SETTINGS keys Chimera never reads.

A module-level helper that reads a ctx it is never given (global_ctx, after the fifth smoke; its readings are
tests/test_datagen_global_ctx.py's) passes alone, fails global_ctx and still joins, where Chimera's own join crashes in
the helper for a repair; a variant fails alone.

ctx["values"] (the contract's channel for plain values since Nov 4) and ctx_channel as a gate reason: a box that
reads ctx["settings"] fails ctx_channel alone and still gets its joined check (soft only on a step a later one
depends on), one that crashes joined is no soft keep, a variant fails on it, and one that crashes alone is told its
key; tests/contract_fixtures.py's values pair lists its ctx["values"] keys on the names line (sandboxed through
pysandbox.run_tool), and passes alone (its provides found), joined (no stand-in, nothing of s1's lost) and as a plan.
Without Blender: ctx_channel_parts, ctx_tell's forms and length, and its wording against Chimera's own rule text and
a reply that follows the contract. The bench's values step hands its sizes on in ctx["values"].

What the build drops, told at the gate (after the fourth smoke, build_facts; its rules and wordings are
tests/test_datagen_stand_ins.py's): a box with an output path no step asked for fails dead_output_key alone, a floor
that registers a key its provides line leaves out fails Chimera's provides_missing, one that prints the stand-in line
for a GPU fallback fails marker_misused, a bench that reads s1's sizes with a silent default fails silent_default
(the bench fixture marks its stand-ins since), each told and still joined cleanly; a values step with a list of 30
names under provides passes as before, plain, behind a lead or with a note (decided Nov 6), even with a misused marker
(waived), and fails on the marker without it.

Step 6a's hidden errors (datagen/silent.py; its own rules and the refuter's fixtures are tests/test_datagen_silent.py):
a box that sets a Principled BSDF input by its pre-4.0 name inside a try that swallows the KeyError fails swallowed
alone and still joins cleanly (soft), a variant fails alone, one that looks an input up by a wrong name behind a guard
fails skipped_input, each is told what it hid, and the joined run's report finds the same line through the line map,
recorded only; a clean box's report is watched and empty. Without Blender: they count only when every version's
report watched the piece and shows them, and joined they are recorded only.

Step 6b's geometry (datagen/geometry.py; its readers, faults and the geometry line are tests/test_datagen_geometry.py):
a box its step puts at a point that the piece leaves on its floor's origin fails place_mismatch on its joined run
(alone it stands on the floor's stand-in, so its place is recorded there), soft, and is told where its box is, and
one placed there passes, its exact box on the geometry line; a curve
its step asks to extrude that the piece leaves flat fails flat_extrusion, and an extruded one passes, measured 0.08 m
deep from its evaluated mesh. Without Blender: they need every version's geometry line and measuring and the fault in
each, a relation is the joined run's (a variant's: its alone run's), recorded only while nested's reader is out of
geometry.GATED, and skipped where the run printed a stand-in; a place on an alone run with a stand-in is recorded and
judged on the joined run. About 185 s in all.
"""
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from tests import _paths
from tests import contract_fixtures as CF
from datagen import blender_gate as G
from datagen import chimera as C
from datagen import silent
from datagen import task as T
from datagen.common import Cache
from runner import mock_ollama
from runner.blender_run import counted_strict
from tools import blender_check, blenders

MARK = mock_ollama.MARK
GO = shutil.which("go") or next((p for p in ("/opt/homebrew/bin/go", "/usr/local/go/bin/go") if os.path.exists(p)),
                                None)
HAVE_BLENDER = all(not blenders.check_path(p) for p in blenders.VERSIONS.values())
GUARD = 'if __name__ == "__main__":\n    build_{sid}({{"scene": bpy.context.scene, ' \
        '"collection": bpy.context.scene.collection, "objects": {{}}}})\n'

GOAL = "Build a small room in Blender from nothing: a floor with a box standing on it. " + MARK
PLAN = {"title": "Small room", "kind": "blender", "summary": "A floor and a box on it. " + MARK, "steps": [
    {"id": "s1", "title": "Floor", "kind": "blender", "depends_on": [],
     "instructions": "Make a 4 m floor plane chimera_floor with a brown material; register it as "
                     "ctx['objects']['floor']. " + MARK},
    {"id": "s2", "title": "Box", "kind": "blender", "depends_on": ["s1"],
     "instructions": "Put a 0.5 m box chimera_box on s1's floor; register it as ctx['objects']['box']. " + MARK}]}
RUG_PLAN = {"title": "Rug room", "kind": "blender", "summary": "A floor, then a rug. " + MARK, "steps": [
    PLAN["steps"][0],
    {"id": "s2", "title": "Rug", "kind": "blender", "depends_on": ["s1"],
     "instructions": "Lay a rug chimera_rug where s1's floor is; register it as ctx['objects']['rug']. " + MARK}]}


def reply(sid, code, provides, uses="none", assumed="none"):
    return (f"My piece for {sid}.\n\n```python\n{code}\n{GUARD.format(sid=sid)}```\n\n"
            f"```handoff\nprovides: {provides}\nuses: {uses}\nassumed: {assumed}\n```\n")


FLOOR_CODE = MARK + '''
import bpy

SETTINGS_s1 = {"size": 4.0, "color": (0.35, 0.22, 0.12, 1.0)}


def build_s1(ctx):
    s = SETTINGS_s1
    h = s["size"] / 2
    mesh = bpy.data.meshes.new("chimera_floor")
    mesh.from_pydata([(-h, -h, 0), (h, -h, 0), (h, h, 0), (-h, h, 0)], [], [(0, 1, 2, 3)])
    floor = bpy.data.objects.new("chimera_floor", mesh)
    ctx["collection"].objects.link(floor)
    mat = bpy.data.materials.new("chimera_floor_mat")
    mat.diffuse_color = s["color"]
    mesh.materials.append(mat)
    ctx["objects"]["floor"] = floor

'''
FLOOR = reply("s1", FLOOR_CODE, 'chimera_floor as ctx["objects"]["floor"]; material chimera_floor_mat',
              assumed="the floor lies at z = 0")

BOX_CODE = MARK + '''
import bpy

SETTINGS_s2 = {"size": 0.5}


def _s2_standin(ctx, key):
    print("chimera: stand-in", key)
    obj = bpy.data.objects.new("chimera_" + key + "_standin", None)
    obj["chimera_top"] = 0.0
    ctx["collection"].objects.link(obj)
    return obj


def build_s2(ctx):
    s = SETTINGS_s2
    floor = ctx["objects"].get("floor")
    if floor is None:
        floor = _s2_standin(ctx, "floor")
    h = s["size"] / 2
    mesh = bpy.data.meshes.new("chimera_box")
    verts = [(x, y, z) for x in (-h, h) for y in (-h, h) for z in (0.0, 2 * h)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh.from_pydata(verts, [], faces)
    box = bpy.data.objects.new("chimera_box", mesh)
    box.location = (floor.location.x, floor.location.y, floor.location.z)
    ctx["collection"].objects.link(box)
    ctx["objects"]["box"] = box

'''
BOX_PROVIDES = 'chimera_box as ctx["objects"]["box"]'
# The values pair's s1 (tests/contract_fixtures.py, K4): its provides line
VALUES_PROVIDES = 'ctx["values"]["sofa_width"], ctx["values"]["sofa_depth"]'
BOX_USES = 's1\'s ctx["objects"]["floor"]'
BOX = reply("s2", BOX_CODE, BOX_PROVIDES, BOX_USES)
LOCATION = "    box.location = (floor.location.x, floor.location.y, floor.location.z)\n"
# The Principled BSDF's input has been "Transmission Weight" since 4.0: a lint error, and a KeyError in Blender.
LINT_LINE = '    bsdf.inputs["Transmission"].default_value = 0.5'
BOX_LINT_CODE = BOX_CODE.replace('    ctx["objects"]["box"] = box\n',
                                 '    mat = bpy.data.materials.new("chimera_box_mat")\n'
                                 '    bsdf = mat.node_tree.nodes["Principled BSDF"]\n' + LINT_LINE + "\n"
                                 '    ctx["objects"]["box"] = box\n')
# Two numbers for a location: a ValueError in build_s2 that no lint sees.
CRASH_LINE = "    box.location = (floor.location.x, floor.location.y)"
BOX_CRASH_CODE = BOX_CODE.replace(LOCATION, CRASH_LINE + "\n")
# Only its own stand-in has "chimera_top": alone it runs, after s1's floor it's a KeyError in build_s2.
JOINED_LINE = '    box.location = (floor.location.x, floor.location.y, floor["chimera_top"])'
BOX_JOINED_CODE = BOX_CODE.replace(LOCATION, JOINED_LINE + "\n")
# It reads a ctx key the contract doesn't have, with a default (ctx_channel: the values steps' readers before Nov 4),
# so it runs alone and joined; as the box above, as the one that crashes alone and as the one that crashes joined.
CTX_LINE = '    count = ctx.get("settings", {}).get("count", 1)\n'
BOX_CTX_CODE = BOX_CODE.replace("    s = SETTINGS_s2\n", "    s = SETTINGS_s2\n" + CTX_LINE)
BOX_CTX_CRASH_CODE = BOX_CRASH_CODE.replace("    s = SETTINGS_s2\n", "    s = SETTINGS_s2\n" + CTX_LINE)
BOX_CTX_JOINED_CODE = BOX_JOINED_CODE.replace("    s = SETTINGS_s2\n", "    s = SETTINGS_s2\n" + CTX_LINE)
VALUES_GOAL = "Build a sofa in Blender from nothing, its width and depth set where a person can change them. " + MARK
# After the fifth smoke: the box links itself through a module-level helper that reads a ctx it is never given
# (global_ctx). Alone, the gate's tail binds ctx at module level, so it runs; in Chimera's join main() holds ctx.
_LINK = '    ctx["collection"].objects.link(box)\n'
GLOBAL_HELPER = '\n\ndef _s2_link(obj):\n    ctx["collection"].objects.link(obj)\n'
BOX_GLOBAL_CODE = BOX_CODE.replace("\n\ndef build_s2(ctx):", GLOBAL_HELPER + "\n\ndef build_s2(ctx):").replace(
    _LINK, "    _s2_link(box)\n")
# Step 6a's hidden errors, which no lint sees (the names come from SETTINGS_s2 and a loop): a Principled BSDF input
# set by its pre-4.0 name inside a try that swallows the KeyError, and one looked up by a wrong name behind a guard
HIDDEN_SET = '        bsdf.inputs[s["input"]].default_value = 0.5\n'
HIDDEN_GUARD = "        if key in bsdf.inputs:\n"
_MAT = ('    mat = bpy.data.materials.new("chimera_box_mat")\n'
        '    bsdf = mat.node_tree.nodes["Principled BSDF"]\n')
_REGISTER = '    ctx["objects"]["box"] = box\n'
BOX_SWALLOWED_CODE = BOX_CODE.replace('SETTINGS_s2 = {"size": 0.5}',
                                      'SETTINGS_s2 = {"size": 0.5, "input": "Transmission"}').replace(
    _REGISTER, _MAT + "    try:\n" + HIDDEN_SET + "    except KeyError:\n        pass\n" + _REGISTER)
BOX_SKIPPED_CODE = BOX_CODE.replace(_REGISTER, _MAT + '    for key, value in (("Base_Color", (0.6, 0.3, 0.1, 1.0)), '
                                    '("Roughness", 0.4)):\n' + HIDDEN_GUARD +
                                    "            bsdf.inputs[key].default_value = value\n" + _REGISTER)
# It reads a key no step registers, built so the joiner can't see it: a stand-in although s1 is there.
BOX_WRONG_KEY_CODE = BOX_CODE.replace('ctx["objects"].get("floor")', 'ctx["objects"].get("".join(["flo", "or_top"]))')
RUG_CODE = MARK + '''
import bpy

SETTINGS_s2 = {"size": 1.5}


def build_s2(ctx):
    floor = ctx["objects"].get("floor")
    if floor is None:
        print("chimera: stand-in", "floor")
    else:
        bpy.data.objects.remove(floor, do_unlink=True)
    h = SETTINGS_s2["size"] / 2
    mesh = bpy.data.meshes.new("chimera_rug")
    mesh.from_pydata([(-h, -h, 0.01), (h, -h, 0.01), (h, h, 0.01), (-h, h, 0.01)], [], [(0, 1, 2, 3)])
    rug = bpy.data.objects.new("chimera_rug", mesh)
    ctx["collection"].objects.link(rug)
    ctx["objects"]["rug"] = rug

'''
# s1 makes a rug, s2 a floor over it, s3 a box on the floor. With s1 dropped, s2's stand-in for the rug is allowed,
# and every join after it has a step with a dependency missing; s3's stand-in for s2's floor still isn't.
ROOM_PLAN = {"title": "Rug room", "kind": "blender", "summary": "A rug, a floor around it, a box on the floor. " + MARK,
             "steps": [
                 {"id": "s1", "title": "Rug", "kind": "blender", "depends_on": [],
                  "instructions": "Lay a rug chimera_rug; register it as ctx['objects']['rug']. " + MARK},
                 {"id": "s2", "title": "Floor", "kind": "blender", "depends_on": ["s1"],
                  "instructions": "Make a 4 m floor plane chimera_floor around s1's rug; register it as "
                                  "ctx['objects']['floor']. " + MARK},
                 {"id": "s3", "title": "Box", "kind": "blender", "depends_on": ["s2"],
                  "instructions": "Put a 0.5 m box chimera_box on s2's floor; register it as "
                                  "ctx['objects']['box']. " + MARK}]}
FLOOR_ON_RUG = reply("s2", FLOOR_CODE.replace("s1", "s2").replace(
    '    h = s["size"] / 2\n',
    '    h = s["size"] / 2\n    if ctx["objects"].get("rug") is None:\n        print("chimera: stand-in", "rug")\n'),
    'chimera_floor as ctx["objects"]["floor"]; material chimera_floor_mat', 's1\'s ctx["objects"]["rug"]')
BOX3 = reply("s3", BOX_CODE.replace("s2", "s3"), BOX_PROVIDES, 's2\'s ctx["objects"]["floor"]')
BOX3_WRONG_KEY = reply("s3", BOX_WRONG_KEY_CODE.replace("s2", "s3"), BOX_PROVIDES, 's2\'s ctx["objects"]["floor"]')
OUTSIDE = "/tmp/wm-datagen-test-never-written"  # outside every run folder: the sandbox refuses writes there
# The same floor plan, its first step asking for a save and a render (so its piece may set an output)
OUTPUT_PLAN = dict(PLAN, steps=[dict(PLAN["steps"][0], instructions=PLAN["steps"][0]["instructions"] +
                                     " Save the scene to room.blend and render it. " + MARK), PLAN["steps"][1]])
# The marker as gpt-oss writes it, with U+2011 for its hyphen
BOX_WRONG_KEY_NB_CODE = BOX_WRONG_KEY_CODE.replace('print("chimera: stand-in", key)',
                                                   'print("chimera: stand\u2011in", key)')

# Sizes and directions the step gives in numbers, measured in the alone run
KITCHEN_PLAN = {"title": "Kitchen corner", "kind": "blender", "summary": "An island and a light over it. " + MARK,
                "steps": [
                    {"id": "s1", "title": "Island", "kind": "blender", "depends_on": [],
                     "instructions": "Make a kitchen island chimera_island (2.4 m × 0.9 m × 0.92 m) standing on the "
                                     "floor; register it as ctx['objects']['island']. " + MARK},
                    {"id": "s2", "title": "Ceiling light", "kind": "blender", "depends_on": ["s1"],
                     "instructions": "Hang a ceiling area light chimera_ceiling_light 2.5 m above s1's island; "
                                     "register it as ctx['objects']['ceiling_light']. " + MARK}]}
ISLAND_CODE = MARK + '''
import bpy

SETTINGS_s1 = {"size": (2.4, 0.9, 0.92)}


def build_s1(ctx):
    sx, sy, sz = SETTINGS_s1["size"]
    mesh = bpy.data.meshes.new("chimera_island")
    verts = [(x, y, z) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (0.0, 1.0)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh.from_pydata(verts, [], faces)
    island = bpy.data.objects.new("chimera_island", mesh)
    island.scale = (sx, sy, sz)
    ctx["collection"].objects.link(island)
    ctx["objects"]["island"] = island

'''
ISLAND_SCALE = "    island.scale = (sx, sy, sz)\n"
ISLAND_PROVIDES = 'chimera_island as ctx["objects"]["island"]'
ISLAND = reply("s1", ISLAND_CODE, ISLAND_PROVIDES)
# The smoke's mistake: a unit cube scaled by half of each side, so every side is half what was asked
ISLAND_HALF = reply("s1", ISLAND_CODE.replace(ISLAND_SCALE, "    island.scale = (sx / 2, sy / 2, sz / 2)\n"),
                    ISLAND_PROVIDES)
# Turned a quarter about z: its sides are the same
ISLAND_TURNED = reply("s1", ISLAND_CODE.replace(ISLAND_SCALE, ISLAND_SCALE + "    island.rotation_euler.z = 1.5708\n"),
                      ISLAND_PROVIDES)
# An output path, though the step asks for no saving or rendering
ISLAND_OUTPUT = reply("s1", ISLAND_CODE.replace('"size": (2.4, 0.9, 0.92)}',
                                                '"size": (2.4, 0.9, 0.92), "output": {"render": "//island.png"}}'),
                      ISLAND_PROVIDES)
LIGHT_CODE = MARK + '''
import bpy
import math

SETTINGS_s2 = {"height": 2.5, "power": 800.0}


def build_s2(ctx):
    island = ctx["objects"].get("island")
    if island is None:
        print("chimera: stand-in", "island")
        island = bpy.data.objects.new("chimera_island_standin", None)
        ctx["collection"].objects.link(island)
    data = bpy.data.lights.new("chimera_ceiling_light", type="AREA")
    data.energy = SETTINGS_s2["power"]
    light = bpy.data.objects.new("chimera_ceiling_light", data)
    light.location = (island.location.x, island.location.y, SETTINGS_s2["height"])
    ctx["collection"].objects.link(light)
    ctx["objects"]["ceiling_light"] = light

'''
LIGHT_LINK = '    ctx["collection"].objects.link(light)\n'
LIGHT_PROVIDES = 'chimera_ceiling_light as ctx["objects"]["ceiling_light"]'
LIGHT_USES = 's1\'s ctx["objects"]["island"]'
LIGHT = reply("s2", LIGHT_CODE, LIGHT_PROVIDES, LIGHT_USES)
# Turned over, so it emits up: the smoke's 180-degree area light
LIGHT_UP = reply("s2", LIGHT_CODE.replace(LIGHT_LINK, "    light.rotation_euler = (math.pi, 0.0, 0.0)\n" + LIGHT_LINK),
                 LIGHT_PROVIDES, LIGHT_USES)
# Turned over too, but a Track To constraint aims it at the island below: only the evaluated scene shows that
LIGHT_TRACKED = reply("s2", LIGHT_CODE.replace(LIGHT_LINK, (
    "    light.rotation_euler = (math.pi, 0.0, 0.0)\n"
    "    aim = light.constraints.new('TRACK_TO')\n"
    "    aim.target = island\n"
    "    aim.track_axis = 'TRACK_NEGATIVE_Z'\n"
    "    aim.up_axis = 'UP_Y'\n") + LIGHT_LINK), LIGHT_PROVIDES, LIGHT_USES)
# What the scene a judge sees lists beyond names: sizes, a modifier, animation, lights, a camera, a node group
SHOW_PLAN = {"title": "Crate shot", "kind": "blender", "summary": "A crate, its lights and a camera. " + MARK,
             "steps": [{"id": "s1", "title": "Crate shot", "kind": "blender", "depends_on": [],
                        "instructions": "Make a bevelled crate chimera_crate that rises from z 0 to 3 over 24 frames, "
                                        "a sun, a bulb and a camera above it, and a node group chimera_scatter; "
                                        "register the crate as ctx['objects']['crate']. " + MARK}]}
SHOW_CODE = MARK + '''
import bpy

SETTINGS_s1 = {"lens": 35.0}


def build_s1(ctx):
    mesh = bpy.data.meshes.new("chimera_crate")
    verts = [(x, y, z) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (0.0, 1.0)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh.from_pydata(verts, [], faces)
    crate = bpy.data.objects.new("chimera_crate", mesh)
    ctx["collection"].objects.link(crate)
    crate.modifiers.new("chimera_bevel", "BEVEL")
    crate.location = (1.0, 2.0, 0.0)
    crate.keyframe_insert("location", frame=1)
    crate.location = (1.0, 2.0, 3.0)
    crate.keyframe_insert("location", frame=24)
    cam = bpy.data.objects.new("chimera_cam", bpy.data.cameras.new("chimera_cam"))
    cam.data.lens = SETTINGS_s1["lens"]
    cam.location = (0.0, 0.0, 10.0)
    ctx["collection"].objects.link(cam)
    sun = bpy.data.objects.new("chimera_sun", bpy.data.lights.new("chimera_sun", type="SUN"))
    sun.data.energy = 3.0
    ctx["collection"].objects.link(sun)
    bulb = bpy.data.objects.new("chimera_bulb", bpy.data.lights.new("chimera_bulb", type="POINT"))
    ctx["collection"].objects.link(bulb)
    bpy.data.node_groups.new("chimera_scatter", "GeometryNodeTree")
    ctx["objects"]["crate"] = crate

'''
SHOW = reply("s1", SHOW_CODE, 'chimera_crate as ctx["objects"]["crate"]')
# smoke4's n-blender-0000-00 r1 s2, cut down: a cube moved to its place and then transform_apply'd (which applies the
# location too), so its origin is the world origin and its geometry where the step puts it (Nov 5)
APPLIED_PLAN = {"title": "Kitchen", "kind": "blender", "summary": "A fridge. " + MARK,
                "steps": [{"id": "s1", "title": "Fridge", "kind": "blender", "depends_on": [],
                           "instructions": "Adds a built-in fridge chimera_fridge (0.8 m x 0.7 m x 1.8 m) and "
                                           "positions it at (1.2, -0.3, 0); register it as ctx['objects']['fridge']. "
                                           + MARK}]}
APPLIED_CODE = MARK + '''
import bpy

SETTINGS_s1 = {"size": (0.8, 0.7, 1.8), "at": (1.2, -0.3, 0.0)}


def build_s1(ctx):
    s = SETTINGS_s1
    bpy.ops.mesh.primitive_cube_add(size=1, location=(s["at"][0], s["at"][1], s["at"][2] + s["size"][2] / 2))
    fridge = bpy.context.active_object
    fridge.name = "chimera_fridge"
    fridge.scale = s["size"]
    bpy.ops.object.transform_apply(scale=True)
    for c in fridge.users_collection:
        c.objects.unlink(fridge)
    ctx["collection"].objects.link(fridge)
    ctx["objects"]["fridge"] = fridge

'''
APPLIED = reply("s1", APPLIED_CODE, 'chimera_fridge as ctx["objects"]["fridge"]')
# A box its own modifier welds to one point, in a piece that sets the factory engine itself: the listing shows its
# size before the modifier, and the engine as set by the piece
WELD_PLAN = {"title": "Welded box", "kind": "blender", "summary": "A box and the render engine. " + MARK,
             "steps": [{"id": "s1", "title": "Welded box", "kind": "blender", "depends_on": [],
                        "instructions": "Make a 2 m box chimera_weld with a weld modifier, and set the render engine "
                                        "to EEVEE; register the box as ctx['objects']['weld']. " + MARK}]}
WELD_CODE = MARK + '''
import bpy

SETTINGS_s1 = {"engine": "BLENDER_EEVEE"}


def build_s1(ctx):
    mesh = bpy.data.meshes.new("chimera_weld")
    verts = [(x, y, z) for x in (-1.0, 1.0) for y in (-0.5, 0.5) for z in (0.0, 1.0)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh.from_pydata(verts, [], faces)
    box = bpy.data.objects.new("chimera_weld", mesh)
    ctx["collection"].objects.link(box)
    weld = box.modifiers.new("chimera_weld", "WELD")
    weld.merge_threshold = 10.0
    ctx["scene"].render.engine = SETTINGS_s1["engine"]
    ctx["objects"]["weld"] = box

'''
WELD = reply("s1", WELD_CODE, 'chimera_weld as ctx["objects"]["weld"]')
# Sizes a values step gives by name: alone the bench reads none and measures its fallback, joined after s1 its own.
# s1 hands them on in ctx["values"], the contract's channel since Nov 4 (ctx["settings"] before it, which
# ctx_channel now fails)
BENCH_PLAN = {"title": "Bench", "kind": "blender", "summary": "A bench sized by a values step. " + MARK, "steps": [
    {"id": "s1", "title": "Define dimensions", "kind": "blender", "depends_on": [],
     "instructions": "Dimensions in metres: bench_length=1.8, bench_width=0.45, bench_height=0.5; store them in "
                     "ctx['values']. " + MARK},
    {"id": "s2", "title": "Bench", "kind": "blender", "depends_on": ["s1"],
     "instructions": "Create the bench chimera_bench with s1's dimensions; register it as ctx['objects']['bench']. "
                     + MARK}]}
VALUES_CODE = MARK + '''
import bpy

SETTINGS_s1 = {"bench_length": 1.8, "bench_width": 0.45, "bench_height": 0.5}


def build_s1(ctx):
    ctx["values"].update(SETTINGS_s1)

'''
VALUES = reply("s1", VALUES_CODE, "none")
BENCH_CODE = MARK + '''
import bpy

SETTINGS_s2 = {"fallback": 1.0}


def build_s2(ctx):
    values = ctx["values"]
    for k in ("length", "width", "height"):
        if "bench_" + k not in values:
            print("chimera: stand-in", "bench_" + k)
    sides = [values.get("bench_" + k, SETTINGS_s2["fallback"]) for k in ("length", "width", "height")]
    mesh = bpy.data.meshes.new("chimera_bench")
    verts = [(x, y, z) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (0.0, 1.0)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh.from_pydata(verts, [], faces)
    bench = bpy.data.objects.new("chimera_bench", mesh)
    bench.scale = sides
    ctx["collection"].objects.link(bench)
    ctx["objects"]["bench"] = bench

'''
BENCH_SCALE = "    bench.scale = sides\n"
BENCH_PROVIDES = 'chimera_bench as ctx["objects"]["bench"]'
BENCH = reply("s2", BENCH_CODE, BENCH_PROVIDES)
# The smoke's half-size mistake, which only the joined run can show here
BENCH_HALF = reply("s2", BENCH_CODE.replace(BENCH_SCALE, "    bench.scale = [s / 2 for s in sides]\n"), BENCH_PROVIDES)
# r2-blender-0: a row of 45 posts whose names sort before the bench's, so the joined measure keeps 40 objects and
# leaves the bench out; and a values piece that stores another bench length than its step's words
ARCADE_PLAN = {"title": "Arcade", "kind": "blender", "summary": "Posts and a bench sized by a values step. " + MARK,
               "steps": [BENCH_PLAN["steps"][0],
                         {"id": "s2", "title": "Posts", "kind": "blender", "depends_on": [],
                          "instructions": "Create a row of small posts chimera_arch_00, chimera_arch_01, ...; register "
                                          "them as ctx['objects']['posts']. " + MARK},
                         dict(BENCH_PLAN["steps"][1], id="s3")]}
POSTS = reply("s2", MARK + '''
import bpy

SETTINGS_s2 = {"count": 45, "side": 0.3}


def build_s2(ctx):
    h = SETTINGS_s2["side"] / 2
    verts = [(x, y, z) for x in (-h, h) for y in (-h, h) for z in (0.0, 2 * h)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    made = []
    for k in range(SETTINGS_s2["count"]):
        mesh = bpy.data.meshes.new("chimera_arch_%02d" % k)
        mesh.from_pydata(verts, [], faces)
        post = bpy.data.objects.new("chimera_arch_%02d" % k, mesh)
        post.location = (k * 0.5, 3.0, 0.0)
        ctx["collection"].objects.link(post)
        made.append(post)
    ctx["objects"]["posts"] = made
''', 'chimera_arch_00 as ctx["objects"]["posts"]')
BENCH3 = reply("s3", BENCH_CODE.replace("_s2", "_s3"), BENCH_PROVIDES)
# The bench with the step's numbers written in, s1's values left unread
BENCH3_WORDS = reply("s3", BENCH_CODE.replace("_s2", "_s3").replace(
    'values.get("bench_" + k, SETTINGS_s3["fallback"]) for k in ("length", "width", "height")', "v for v in (1.8, 0.45, 0.5)"),
    BENCH_PROVIDES)
VALUES_OTHER = VALUES.replace('"bench_length": 1.8', '"bench_length": 2.4')
# A camera the step asks for by the factory camera's own name, so Blender calls it Camera.001: excused only while it
# is the scene's camera; and a camera of another name that never becomes it (smoke2's X47: the factory camera renders)
CAMERA_PLAN = {"title": "Shot", "kind": "blender", "summary": "A camera. " + MARK, "steps": [
    {"id": "s1", "title": "Camera", "kind": "blender", "depends_on": [],
     "instructions": 'Creates a camera named "Camera" at (0, -6, 2) aimed at the origin with a 35 mm lens; register '
                     'it as ctx["objects"]["camera"]. ' + MARK}]}
CAM_CODE = MARK + '''
import bpy

SETTINGS_s1 = {"lens": 35.0, "location": (0.0, -6.0, 2.0)}


def build_s1(ctx):
    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    cam.data.lens = SETTINGS_s1["lens"]
    cam.location = SETTINGS_s1["location"]
    cam.rotation_euler = (1.25, 0.0, 0.0)
    ctx["collection"].objects.link(cam)
    ctx["scene"].camera = cam
    ctx["objects"]["camera"] = cam

'''
CAM_ACTIVE = '    ctx["scene"].camera = cam\n'
CAM = reply("s1", CAM_CODE, 'Camera as ctx["objects"]["camera"]')
CAM_LEFT = reply("s1", CAM_CODE.replace(CAM_ACTIVE, ""), 'Camera as ctx["objects"]["camera"]')
DOLLY_PLAN = {"title": "Dolly", "kind": "blender", "summary": "A dolly camera. " + MARK, "steps": [
    {"id": "s1", "title": "Camera", "kind": "blender", "depends_on": [],
     "instructions": "Adds a camera chimera_cam at (0, -6, 2) pointing at the origin with a 35 mm lens; register it "
                     "as ctx['objects']['camera']. " + MARK}]}
DOLLY_CODE = CAM_CODE.replace('"Camera"', '"chimera_cam"')
DOLLY = reply("s1", DOLLY_CODE, 'chimera_cam as ctx["objects"]["camera"]')
DOLLY_LEFT = reply("s1", DOLLY_CODE.replace(CAM_ACTIVE, ""), 'chimera_cam as ctx["objects"]["camera"]')
# A floor whose step asks for a render it never hands over (smoke2's X05, X20, X58); the mark comes after the ask,
# since its "never" before one reads as a negation
RENDER_PLAN = dict(PLAN, steps=[dict(PLAN["steps"][0], instructions="Make a 4 m floor plane chimera_floor with a "
                                     "brown material, register it as ctx['objects']['floor'] and render the image to "
                                     "//room.png. " + MARK), PLAN["steps"][1]])
FLOOR_RENDERED = FLOOR.replace('"color": (0.35, 0.22, 0.12, 1.0)}',
                               '"color": (0.35, 0.22, 0.12, 1.0), "output": {"render": "//room.png"}}')
# A handler that prints an error line whenever the scene is evaluated: the measuring must not set it off
HANDLER = MARK + '''
import bpy

@bpy.app.handlers.persistent
def _dg_test_loud(*args):
    print("Error: dg-test handler ran", flush=True)

bpy.context.scene.collection.objects.link(bpy.data.objects.new("chimera_dg_test_empty", None))
bpy.app.handlers.depsgraph_update_post.append(_dg_test_loud)
bpy.app.handlers.frame_change_pre.append(_dg_test_loud)
'''
# It says where it runs, then never ends.
HANG = MARK + '''
import bpy, os, time
print("dg-test pid", os.getpid(), flush=True)
with open(os.path.join(os.environ["HOME"], "pid.txt"), "w") as f:
    f.write(str(os.getpid()))
while True:
    time.sleep(0.2)
'''

_bin = _tmp = _srv = None
_url = ""
_gate = None


def setUpModule():
    global _bin, _tmp, _srv, _url, _gate
    given = os.environ.get("CHIMERA_BIN")
    given = given if given and os.access(given, os.X_OK) else None
    if not GO and not given:
        raise unittest.SkipTest("needs Go to build Chimera (or CHIMERA_BIN)")
    if not HAVE_BLENDER:
        raise unittest.SkipTest("needs Blender " + " and ".join(blenders.VERSIONS))
    _tmp = tempfile.mkdtemp(prefix="test-datagen-blender-", dir=blender_check.scratch_root())
    _bin = os.path.join(_tmp, "chimera")
    if given:  # a fresh copy: a signed binary is never run in place
        shutil.copy2(given, _bin)
    else:
        env = dict(os.environ, PATH=os.path.dirname(GO) + os.pathsep + os.environ.get("PATH", ""))
        p = subprocess.run([GO, "build", "-o", _bin, "."], cwd=_paths.APP, capture_output=True, text=True, env=env,
                           timeout=900)
        if p.returncode:
            shutil.rmtree(_tmp, ignore_errors=True)
            raise RuntimeError("go build failed: " + p.stderr[-3000:])
    _srv, _url = mock_ollama.serve(0, os.path.join(_tmp, "ollama.jsonl"))
    _gate = make_gate(os.path.join(_tmp, "runs.jsonl"))


def tearDownModule():
    if _srv:
        _srv.shutdown()
        _srv.server_close()
    if _tmp:
        shutil.rmtree(_tmp, ignore_errors=True)


def chimera():
    return C.Chimera(_bin, env={"OLLAMA_HOST": _url})


def make_gate(cache_path, **kw):
    work = os.path.join(_tmp, "work")
    return G.BlenderGate(chimera(), Cache(cache_path), work=work, **kw)


def verdict(plan, i, text):
    st = plan["steps"][i]
    deps = ["s%d" % (plan["steps"].index(s) + 1) for s in plan["steps"] if s["id"] in (st.get("depends_on") or [])]
    return chimera().validate([{"text": text, "mode": "blender", "sid": "s%d" % (i + 1), "deps": deps,
                                "lone": len(plan["steps"]) == 1, "step": st}])[0]


def line_of(code, text):
    """The 1-based line of text in a piece's code block (Go's code, as the validator gives it)."""
    return code.split("\n").index(text) + 1


class ReadersTests(unittest.TestCase):
    """The pure parts, no Blender."""

    def test_the_gates_lint_has_the_guarded_read_rule(self):
        """Decided Nov 6: the lint's guarded-read rule (tools/rna_lint.guards) is the data generator's only, so the
        gate's own linter is made with guards=True (as datagen/run.py's is), while the default Linter, the eval's,
        lints a guarded read as before Nov 5."""
        from tools import rna_lint
        g = make_gate(os.path.join(_tmp, "guards.jsonl"))
        self.assertTrue(g.linter.use_guards)
        src = ("import bpy\n" + MARK + "\nact = bpy.data.actions.new('a')\nif hasattr(act, 'fcurves'):\n"
               "    for fc in act.fcurves:\n        pass\n")
        self.assertEqual(g.lint(src), [])
        plain = rna_lint.Linter(g.linter.f).lint(src)
        self.assertEqual([(x["kind"], x["name"]) for x in plain if x["level"] == "error"], [("attr", "fcurves")])

    def test_part_of_names_parts_as_the_line_map_does(self):
        code = verdict(PLAN, 1, BOX)["code"]
        self.assertEqual(G.part_of(code, 2, "s2"), ("import", ""))
        self.assertEqual(G.part_of(code, line_of(code, 'SETTINGS_s2 = {"size": 0.5}'), "s2"),
                         ("settings", "SETTINGS_s2"))
        self.assertEqual(G.part_of(code, line_of(code, '    print("chimera: stand-in", key)'), "s2"),
                         ("helper", "_s2_standin"))
        self.assertEqual(G.part_of(code, line_of(code, LOCATION.rstrip("\n")), "s2"), ("build", "build_s2"))
        self.assertEqual(G.part_of(code, 1, "s2"), ("", ""))  # the mark, a comment: no statement holds it
        self.assertEqual(G.part_of("x = (", 1, "s1"), ("", ""))

    def test_skip_render_keeps_the_line_count_and_only_chimeras_render(self):
        ch = chimera()
        with_output = FLOOR.replace('"color": (0.35, 0.22, 0.12, 1.0)}',
                                    '"color": (0.35, 0.22, 0.12, 1.0), "output": {"render": "room.png"}}')
        j = ch.join(PLAN, {"s1": with_output}, goal=GOAL)
        self.assertIn(G.RENDER_LINE, j["script"])
        self.assertIn("        " + G.PATH_LINE + "\n", j["script"])  # Go's path() helper, as it really prints it
        out = G.skip_render(j["script"], j["linemap"])
        self.assertEqual(len(out.split("\n")), len(j["script"].split("\n")))
        self.assertNotIn(G.RENDER_LINE, out)
        self.assertIn(G.RENDER_SKIPPED, out)
        self.assertNotIn(G.PATH_LINE, out)
        self.assertIn("        " + G.PATH_KEPT + "\n", out)  # at the same indent
        self.assertEqual([l for l in out.split("\n") if "wm_out" in l or G.RENDER_SKIPPED in l],
                         ["        " + G.PATH_KEPT, "        " + G.RENDER_SKIPPED])  # those two lines only
        mine = "import bpy\n" + "        " + G.RENDER_LINE + "\n"  # not the line map's output part: left alone
        self.assertEqual(G.skip_render(mine, {"origins": [None, ["s1", "build", "build_s1", 3]]}), mine)

    def test_stand_in_keys_are_read_from_the_printed_lines(self):
        out = ("chimera: stand-in floor\nInfo: something\nchimera: stand-in: 'rug'\n  chimera: stand-in for lamp\n"
               "chimera: stand-in floor\n"
               '    print("chimera: stand-in", key)\n')  # a traceback's source line names no key
        self.assertEqual(G.stand_in_keys(out), ["floor", "rug", "lamp"])
        self.assertEqual(G.stand_in_keys(""), [])

    def test_the_preferred_version_comes_first(self):
        first, second = list(blenders.VERSIONS)
        self.assertEqual(_gate._order(second), [second, first])
        self.assertEqual(_gate._order(first), [first, second])
        self.assertEqual(_gate._order(None), [first, second])
        self.assertEqual(_gate._order("4.2.0"), [first, second])  # not one of the versions checked

    def test_ids_and_worker_names_both_name_steps(self):
        plan = {"steps": [{"id": "a"}, {"id": "b"}, {"id": "s1"}]}
        self.assertEqual(G.step_index(plan, "b"), 1)
        self.assertEqual(G.step_index(plan, "s2"), 1)
        self.assertEqual(G.step_index(plan, "s1"), 2)  # a plan id wins over a worker name
        self.assertIsNone(G.step_index(plan, "s9"))
        self.assertEqual(G.by_id(plan, {"s2": "x", "a": "y", "zz": "w", "s3": ""}), {"b": "x", "a": "y"})

    def test_the_stand_in_marker_counts_with_any_hyphen(self):
        for dash in "-\u2010\u2011\u2012\u2212":
            out = "Info: x\nchimera: stand%sin floor\n" % dash
            self.assertTrue(G.has_stand_in(out), repr(dash))
            self.assertEqual(G.stand_in_keys(out), ["floor"])
        # U+2013 is the dash after the marker ("stand\u2011in \u2013 SVG not found"), not its hyphen
        self.assertTrue(G.has_stand_in("chimera: stand\u2011in \u2013 SVG not found\n"))
        self.assertEqual(G.stand_in_keys("chimera: stand\u2011in \u2013 SVG not found\n"), [])
        self.assertFalse(G.has_stand_in("chimera: stand\u2013in floor\n"))
        self.assertFalse(G.has_stand_in(None))

    def test_seams_from_a_dropped_step_are_excused(self):
        drop = G.BlenderGate._seam_excused
        missing = {"code": "ctx_key_missing", "step": "s2", "message": "s2 reads ctx[\"objects\"]['floor'], which no "
                   "earlier step registers (the step that should have made it failed)"}
        self.assertTrue(drop(PLAN, missing, {"s2"}))   # s1 was dropped: s2 makes a stand-in
        self.assertFalse(drop(PLAN, missing, {"s1", "s2"}))
        dup = {"code": "duplicate_name", "step": "s2", "message": "_box is defined by s1 and s2"}
        self.assertFalse(drop(PLAN, dup, {"s1", "s2"}))
        later = {"code": "uses_unmatched", "step": "s2", "message": "s2 uses 'x' from s3"}
        self.assertTrue(drop(PLAN, later, {"s1", "s2"}))


def step(instructions, title="Step", depends_on=()):
    return {"id": "s%d" % (len(depends_on) + 1), "title": title, "kind": "blender", "depends_on": list(depends_on),
            "instructions": instructions + " " + MARK}


def row(name, kind="MESH", **kw):
    """One object of a measuring line, as MEASURE_EPILOGUE prints it."""
    return dict({"n": name, "t": kind, "loc": [0.0, 0.0, 0.0]}, **kw)


def plan_of(*steps):
    """A plan of (title, instructions, depends_on) steps, each marked."""
    return {"steps": [{"id": "s%d" % (k + 1), "title": t, "kind": "blender", "depends_on": list(d),
                       "instructions": text + " " + MARK} for k, (t, text, d) in enumerate(steps)]}


FACTORY_ROWS = [row("Cube", f=1, size=[2.0, 2.0, 2.0]),
                row("Light", "LIGHT", f=1, loc=[4.08, 1.01, 5.9], dir=[-0.57, -0.22, -0.79], light="POINT",
                    power=1000.0),
                row("Camera", "CAMERA", f=1, loc=[7.36, -6.93, 4.96], dir=[-0.65, 0.61, -0.45], lens=50.0)]


class MeasuredReadersTests(unittest.TestCase):
    """What a step asks for in numbers and the measured checks against a measuring line: pure, no Blender."""

    def test_size_triples_are_read_the_ways_steps_write_them(self):
        def sides(text):
            return [t["sides"] for t in G.size_triples(text + " " + MARK)]
        self.assertEqual(sides("a rectangular island countertop (2.4 m × 0.9 m × 0.92 m) using a plane"),
                         [[2.4, 0.9, 0.92]])
        self.assertEqual(sides("a 2.4 x 0.9 x 0.92 m island, a 2.4 by 0.9 by 0.92 metres one, a 2.4m*0.9m*0.92m one"),
                         [[2.4, 0.9, 0.92]] * 3)
        self.assertEqual(sides("a 40 cm × 40 cm × 45 cm stool and a 1200 x 600 x 400 mm box"),
                         [[0.4, 0.4, 0.45], [1.2, 0.6, 0.4]])
        # a side the step names by a variable
        self.assertEqual(sides("Sofa: a box with dimensions sofa_dim (length) × 0.9 m (width) × 0.8 m (height)."),
                         [[None, 0.9, 0.8]])
        self.assertEqual(G.size_triples("a 2 × 1 × 0.75 m oak table")[0]["words"], ["oak", "table"])
        # the numbers after variables are still read; a pair, a resolution, a time and another step's thing aren't
        self.assertEqual(sides("`building_size_x` × `building_size_y` × `building_size_z` (4×6×12 m)"),
                         [[4.0, 6.0, 12.0]])
        for text in ("a floor (10×10 m)", "a resolution of 1920×1080", "150 frames (5 s × 30 fps)",
                     "scale it to ground_size x ground_size x ground_size", "a vase on s1's 2 x 1 x 0.75 m table",
                     "a 2 x 1 x 0.75 table"):
            self.assertEqual(sides(text), [], text)
        # A clause that says its thing comes from another step, before the numbers or right after them
        for text in ("Frame the island from s1, with its stools and the lamp above it, all of it "
                     "(2.4 m × 0.9 m × 0.92 m)",
                     "Aim the light at the island that was built in s2 by the cabinet maker, 2.4 m × 0.9 m × 0.92 m",
                     "Frame the island (2.4 m × 0.9 m × 0.92 m) built in s1"):
            self.assertEqual(sides(text), [], text)
        self.assertEqual(sides("The camera comes from s1 and stays exactly where it is now. Then add a "
                               "2 × 1 × 0.75 m table"), [[2.0, 1.0, 0.75]])  # another clause

    def test_a_triple_says_what_it_is_the_size_of(self):
        def things(text):
            return [t["thing"] for t in G.size_triples(text + " " + MARK)]
        self.assertEqual(things("Creates a rectangular island countertop (2.4 m × 0.9 m × 0.92 m) using a plane"),
                         ["island countertop"])
        self.assertEqual(things("Make a kitchen island chimera_island (2.4 m × 0.9 m × 0.92 m)"), ["kitchen island"])
        self.assertEqual(things("Adds a built\u2011in fridge (0.8 m × 0.7 m × 1.8 m)"), ["fridge"])
        self.assertEqual(things("a 2 × 1 × 0.75 m oak table"), ["oak table"])
        self.assertEqual(things("a 40 cm × 40 cm × 45 cm stool and a 1200 x 600 x 400 mm box"), ["stool", ""])
        # a variable's stem, kept with the variable each "?" side stands for
        got, = G.size_triples("Sofa: a box with dimensions sofa_dim (length) × 0.9 m (width) × 0.8 m (height). " + MARK)
        self.assertEqual((got["thing"], got["vars"]), ("sofa", ["sofa_dim", None, None]))
        self.assertNotIn("vars", G.size_triples("a 2 × 1 × 0.75 m oak table " + MARK)[0])

    def test_a_size_is_asked_only_of_the_step_that_makes_its_thing(self):
        island = ("Island", "Build the kitchen island chimera_island (2.4 m × 0.9 m × 0.92 m) on the floor.", ())
        self.assertEqual([t["thing"] for t in G.asked_sizes(plan_of(island), 0)], ["kitchen island"])
        # The defect's floor-and-lights and camera steps: the island is s1's, so nothing is asked of them
        for text, deps in (("Add a 10 m × 10 m floor plane under the island (2.4 m × 0.9 m × 0.92 m) and a key area "
                            "light.", ("s1",)),
                           ("Frame the island (2.4 m × 0.9 m × 0.92 m) with a 35 mm camera.", ("s1",)),
                           ("Add a camera that frames the island built in s1 (2.4 m × 0.9 m × 0.92 m).", ("s1",)),
                           ("Hang a pendant lamp over the island (2.4 × 0.9 × 0.92 m).", ("s1",))):
            self.assertEqual(G.asked_sizes(plan_of(island, ("Next", text, deps)), 1), [], text)
        # A dependency's dependency makes it too; and with no other step, a lamp "above the island" still doesn't
        stools = ("Stools", "Add four stools around the island.", ("s1",))
        lamp = ("Lamp", "Place a lamp 2 m above the kitchen island (2.4 × 0.9 × 0.92 m).", ("s2",))
        self.assertEqual(G.asked_sizes(plan_of(island, stools, lamp), 2), [])
        self.assertEqual(G.asked_sizes(plan_of(("Lamp", lamp[1], ())), 0), [])
        # What the step makes is asked, beside a dependency's thing; and list items under "add the following:"
        rug = ("Rug", "Add a rug (2 m × 3 m × 0.01 m) next to the island (2.4 m × 0.9 m × 0.92 m).", ("s1",))
        self.assertEqual([(t["thing"], t["sides"]) for t in G.asked_sizes(plan_of(island, rug), 1)],
                         [("rug", [2.0, 3.0, 0.01])])
        listed = ("Add objects", "Add the following objects to the scene:\n1. Sofa: a box with dimensions sofa_dim "
                  "(length) × 0.9 m (width) × 0.8 m (height).\n2. A cube named \"building_a\" (4×6×12 m)\n"
                  "- Kitchen island (2.4 × 0.9 × 0.92 m)\n- Frame the bench (1.8 × 0.45 × 0.5 m)", ())
        # No other step makes the bench, so a one-step plan's "Frame the bench (...)" is its own
        self.assertEqual([t["thing"] for t in G.asked_sizes(plan_of(listed), 0)],
                         ["sofa", "building", "kitchen island", "bench"])
        # A dependency that only defines values makes nothing
        values = ("Define dimensions and colours", "Dimensions: island_length=2.4, island_width=0.9, "
                  "island_height=0.92, for the island to be built later.", ())
        self.assertEqual([t["sides"] for t in G.asked_sizes(plan_of(values, ("Island", "Create the island.", ("s1",))),
                                                            1)], [[2.4, 0.9, 0.92]])
        # Named sides from a values step aren't asked of a later step that only places what another made
        sofa = ("Sofa", "Create the sofa from s1's values.", ("s1",))
        values = ("Define dimensions", "sofa_length=2.2, sofa_width=0.9, sofa_height=0.8", ())
        self.assertEqual([t["thing"] for t in G.asked_sizes(plan_of(values, sofa), 1)], ["sofa"])
        self.assertEqual(G.asked_sizes(plan_of(values, sofa, ("Lamp", "Place the lamp beside the sofa.", ("s1", "s2"))),
                                       2), [])

    def test_a_size_no_other_step_makes_is_asked_whatever_the_verb(self):
        """r2-blender-1 and blender-3: a step's own thing is asked though no making verb says so; another step's
        isn't, also in a "which measures" clause."""
        def asked(*steps, i=0):
            return [(t["thing"], t["sides"]) for t in G.asked_sizes(plan_of(*steps), i)]
        for text, thing in (("The scene needs a kitchen island (2.4 × 0.9 × 0.92 m) at the origin.", "kitchen island"),
                            ("Floor: 10 m × 10 m × 0.1 m slab at z = 0.", "floor"),
                            ("Create a wooden table. The table is about 2 × 1 × 0.75 m.", "table"),
                            ("Create the island. It should measure 2.4 × 0.9 × 0.92 m.", ""),
                            ("A 2 × 1 × 0.75 m oak table stands in the middle of the room.", "oak table"),
                            ("Walls: 5 m × 0.2 m × 3 m each, four of them around the floor.", "walls"),
                            ("Block out a car body 4.5 × 1.8 × 1.4 m from a scaled cube.", "car body"),
                            ("Build a shelf unit measuring 1.2 m × 0.4 m × 1.8 m.", "shelf unit"),
                            ("The sofa should be 2.2 × 0.9 × 0.8 m; give it a teal material.", "sofa")):
            got = asked(("Step", text, ()))
            self.assertEqual([t for t, _ in got], [thing], text)
        island = ("Island", "Build the kitchen island chimera_island (2.4 m × 0.9 m × 0.92 m) on the floor.", ())
        frames = "Add a camera that frames the island, which measures 2.4 m × 0.9 m × 0.92 m."
        for deps in (("s1",), ()):  # another step builds the island, a dependency or not
            self.assertEqual(asked(island, ("Camera", frames, deps), i=1), [], deps)
        self.assertEqual(asked(("Camera", frames, ())), [("island", [2.4, 0.9, 0.92])])  # one step: its own
        # An earlier step whose title names the thing makes it, with no making verb; a later one's title doesn't
        titled = ("Kitchen island", "A white box 2.4 × 0.9 × 0.92 m with a marble top.", ())
        camera = ("Camera framing the island", "The camera frames the island (2.4 × 0.9 × 0.92 m).", ("s1",))
        self.assertEqual(asked(titled, camera, i=1), [])
        self.assertEqual(asked(titled, camera, i=0), [("", [2.4, 0.9, 0.92])])
        needs = ("Island", "The scene needs a kitchen island (2.4 × 0.9 × 0.92 m) at the origin.", ())
        self.assertEqual(asked(needs, camera, i=0), [("kitchen island", [2.4, 0.9, 0.92])])
        self.assertEqual(asked(needs, camera, i=1), [])  # its size comes from the earlier step's
        # A later step that makes it takes it away from a step that only mentions it
        self.assertEqual(asked(("Floor", "The island (2.4 × 0.9 × 0.92 m) needs a floor around it.", ()),
                               ("Island", "Build the island.", ("s1",))), [])
        # A thing that can't be read: asked unless another step makes something its words name
        rug = "Add a rug next to the island, with dimensions 2 × 3 × 0.01 m."
        self.assertEqual(asked(island, ("Rug", rug, ("s1",)), i=1), [])
        self.assertEqual(asked(("Rug", rug, ())), [("", [2.0, 3.0, 0.01])])

    def test_the_thing_a_size_is_of_is_read_past_the_words_about_its_size(self):
        def thing(text):
            return [t["thing"] for t in G.size_triples(text + " " + MARK)]
        self.assertEqual(thing("The table is about 2 × 1 × 0.75 m."), ["table"])
        self.assertEqual(thing("Frame the island, which measures 2.4 m × 0.9 m × 0.92 m."), ["island"])
        self.assertEqual(thing("It should measure 2.4 × 0.9 × 0.92 m."), [""])  # a pronoun names nothing
        self.assertEqual(thing("Create a kitchen island chimera_island, 2.4 m long, 0.9 m deep and 0.92 m tall "
                               "(2.4 × 0.9 × 0.92 m)."), ["kitchen island"])  # not "tall"
        self.assertEqual(thing("the island chimera_island, 0.9m deep and 0.92m tall (2.4 × 0.9 × 0.92 m)"), ["island"])
        self.assertEqual(thing("Model a desk whose top is 1.4 × 0.7 × 0.04 m."), ["top"])
        self.assertEqual(thing("Build a shelf unit measuring 1.2 m × 0.4 m × 1.8 m."), ["shelf unit"])
        self.assertEqual(thing("a box roughly 1 × 1 × 1 m"), [""])  # a plain word ends it as before

    def test_named_sides_count_from_a_step_that_only_defines_values(self):
        values = step("Dimensions in meters: sofa_length=2.2, sofa_width=0.9, sofa_height=0.8, "
                      "coffee_table_length=1.2, coffee_table_width=0.6, coffee_table_height=0.4, lamp_height=2.0.",
                      title="Define dimensions, colours, and scene settings")
        plan = {"steps": [values, step("Create the sofa and the coffee table with the variables from s1.",
                                       title="Create furniture", depends_on=["s1"])]}
        got = G.asked_sizes(plan, 1)
        self.assertEqual([(t["thing"], t["sides"], t["source"]) for t in got],
                         [("sofa", [2.2, 0.9, 0.8], "s1"), ("coffee_table", [1.2, 0.6, 0.4], "s1")])
        self.assertEqual(G.asked_sizes(plan, 0), [])  # the values step itself makes nothing of that size
        # Not for a thing the step doesn't name, nor from a dependency that builds things itself
        plan["steps"][1]["instructions"] = "Put cushions on it. " + MARK
        self.assertEqual(G.asked_sizes(plan, 1), [])
        plan["steps"][0]["title"] = "Build the sofa"
        plan["steps"][1]["instructions"] = "Create the sofa's cushions. " + MARK
        self.assertEqual(G.asked_sizes(plan, 1), [])

    def test_aims_are_read_from_the_steps_words(self):
        def aims(text):
            return [(a["what"], a["type"], a["word"]) for a in G.asked_aims({"steps": [step(text)]}, 0)]
        self.assertEqual(aims("Add a sun lamp pointing down."), [("light", "SUN", None)])
        self.assertEqual(aims("Add a ceiling area light (800 W) and two side spotlights."),
                         [("light", "AREA", "ceiling")])
        self.assertEqual([(a["what"], a["type"], a["word"]) for a in G.asked_aims(KITCHEN_PLAN, 1)],
                         [("light", "AREA", "ceiling")])  # the title's "Ceiling light" is the same light
        self.assertEqual(aims("Create a soft area light at (0, -5, 8) and pointing downwards"),
                         [("light", "AREA", None)])
        self.assertEqual(aims("an area light aimed at the floor"), [("light", "AREA", None)])
        self.assertEqual(aims("Point the camera straight down"), [("camera", None, None)])
        self.assertEqual(aims("a top-down camera"), [("camera", None, None)])
        self.assertEqual(aims("a downward-facing spot light"), [("light", "SPOT", None)])
        for text in ("a spotlight pointing down the corridor", "a camera pointing down at the sofa",
                     "spotlights aimed down at a slight angle", "a ceiling point light", "a point light pointing down",
                     "a camera at (0, 0, 3) pointing at the origin", "Add floor plane, building, sun lamp, camera",
                     "a key light shining straight down the corridor", "a camera looking directly down the hall",
                     "a spot light rotated down 180 degrees"):
            self.assertEqual(aims(text), [], text)

    def test_an_angle_with_down_says_how_far_down(self):
        def aims(text):
            return [(a["what"], a["angle"], G.aim_z(a)) for a in G.asked_aims({"steps": [step(text)]}, 0)]
        self.assertEqual(aims("a camera tilted down 15 degrees toward the table"), [("camera", 15.0, -0.16)])
        self.assertEqual(aims("a sun light angled down 20 degrees"), [("light", 20.0, -0.24)])
        self.assertEqual(aims("a sun angled down at 30 degrees"), [("light", 30.0, -0.4)])
        self.assertEqual(aims("a camera tilted 15° down"), [("camera", 15.0, -0.16)])
        self.assertEqual(aims("a spot light aimed down by 0.5 rad"), [("light", 28.65, -0.38)])
        # An angle not said of "down" is no tilt; without one, "down" is AIM_DOWN_Z
        self.assertEqual(aims("a spotlight pointing down with a 45° cone"), [("light", None, G.AIM_DOWN_Z)])
        # A ceiling light takes the angle its clause gives with "down"; over 90 degrees the clause says nothing
        self.assertEqual([(a["word"], a["angle"]) for a in G.asked_aims(
            {"steps": [step("Add a ceiling area light angled down 30 degrees")]}, 0)], [(None, 30.0), ("ceiling", 30.0)])
        self.assertEqual(aims("a ceiling spot light pointing down 200 degrees"), [])
        # The same camera twice keeps its most lenient reading
        self.assertEqual(aims("Point the camera straight down. Tilt the camera down 20 degrees."),
                         [("camera", 20.0, -0.24)])

    def test_an_angle_from_vertical_a_rotation_or_one_elsewhere_in_the_clause(self):
        """r2-blender-2: "N degrees from vertical" is 90 - N below level; "down to N degrees" and an angle that isn't
        "down"'s say nothing certain, so nothing is asked rather than AIM_DOWN_Z."""
        def aims(text):
            return [(a["what"], a["angle"]) for a in G.asked_aims({"steps": [step(text)]}, 0)]
        self.assertEqual(aims("a sun lamp angled down 60 degrees from vertical"), [("light", 30.0)])
        for text in ("Tilt the camera down to 70 degrees on its X axis",
                     "a camera pointing down toward the floor at a 25 degree angle",
                     "a downward-facing camera tilted 20 degrees",
                     "a camera pointing straight down and a sun at 45 degrees",
                     "a camera pointing straight down, rotation (0, 0, 90)",
                     "a spot light pointing down 95 degrees from vertical",
                     "a camera tilted down 15° (0.26 rad)"):
            self.assertEqual(aims(text), [], text)
        self.assertEqual(aims("a spot light angled 20 degrees from straight down"), [("light", 70.0)])
        self.assertEqual(aims("a camera tilted down 10 degrees off the nadir"), [("camera", 80.0)])
        self.assertEqual(aims("a camera tilted down 15 degrees below horizontal"), [("camera", 15.0)])
        # Given outright anywhere in the clause, from vertical or the zenith; a ceiling light takes it too
        self.assertEqual(aims("a sun pointing down, 30 degrees from the zenith"), [("light", 60.0)])
        self.assertEqual(aims("a ceiling light, 30 degrees from vertical"), [("light", 60.0)])
        # A cone's or a field of view's angle is no tilt: "down" is AIM_DOWN_Z as before, whatever its hyphen
        for text, what in (("a spotlight pointing down with a 45-degree cone", "light"),
                           ("a spotlight pointing down with a cone angle of 45 degrees", "light"),
                           ("a camera pointing straight down with a field of view of 60°", "camera")):
            self.assertEqual(aims(text), [(what, None)], text)
        # Another clause's angle leaves this one alone
        self.assertEqual(aims("Point the camera straight down; rotate the table 45 degrees"), [("camera", None)])
        # A sun that does what "60 degrees from vertical" says (30 below level) passes; one 10 below doesn't
        sun = G.asked_aims({"steps": [step("a sun lamp angled down 60 degrees from vertical")]}, 0)
        self.assertEqual(G.aim_faults(sun, {"objects": [row("chimera_sun", "LIGHT", light="SUN",
                                                              dir=[0.0, 0.87, -0.5])]}), [])
        self.assertEqual(len(G.aim_faults(sun, {"objects": [row("chimera_sun", "LIGHT", light="SUN",
                                                                  dir=[0.0, 0.98, -0.17])]})), 1)

    def test_output_paths_and_what_asks_for_one(self):
        def paths(settings):
            return G.output_paths(MARK + "\nimport bpy\nSETTINGS_s2 = " + settings + "\n", "s2")
        self.assertEqual(paths('{"size": 1, "output": "//"}'), ["//"])
        self.assertEqual(paths('{"output": {"render": "//room.png", "resolution": [64, 48], "fps": 24}}'),
                         ["//room.png"])
        self.assertEqual(paths('{"output": {"render": {"filepath": f"//{NAME}.png"}}}'), ["f'//{NAME}.png'"])
        self.assertEqual(paths('{"output": {"blend": BLEND_PATH}}'), ["BLEND_PATH"])
        self.assertEqual(paths('{"output": {"resolution": [64, 48], "engine": "CYCLES"}}'), [])
        self.assertEqual(paths('{"output": None, "size": 2}'), [])
        self.assertEqual(paths('{"size": 2}'), [])
        self.assertEqual(G.output_paths("SETTINGS_s1 = {'output': '//x.png'}", "s2"), [])  # another step's
        plan = {"steps": [step("Make a box chimera_box.")]}
        self.assertFalse(G.asks_output(plan, 0))
        for text in ("Save the file.", "Render a still.", "Set the render engine to Cycles.", "Export it as GLB.",
                     "Set the output path to //frames/.", "Write it to box.blend."):
            self.assertTrue(G.asks_output({"steps": [step(text)]}, 0), text)
        self.assertFalse(G.asks_output({"steps": [step("Use the defined `render_engine`.")]}, 0))

    def test_what_a_step_asks_chimera_to_make_and_what_a_piece_hands_over(self):
        def asked(text, title="Step"):
            a = G.asked_outputs({"steps": [step(text, title)]}, 0)
            return "".join(k[0] for k in ("blend", "render") if a[k])
        # Asks: a .blend save with its name, a render as a verb with what it makes, the menu, render.render(), F12
        for text, want in (("Save the file as `Acme_Logo.blend` in the working directory.", "b"),
                           ('Save the current scene to a temporary file named "pulse_logo.blend".', "b"),
                           ("Enable `File > Save As` to keep the latest `.blend` file.", "b"),
                           ("Saves the .blend file.", "b"),
                           ("Finally, render the animation to //gate_opening.png.", "r"),
                           ("Run `Render > Render Animation` (Ctrl+F12) to produce the video file.", "r"),
                           ("Calls `bpy.ops.render.render(animation=True)` to render the animation.", "r"),
                           ("Render a single frame and save it as room.png.", "r"),
                           ("Render the animation and save the .blend as room.blend.", "br")):
            self.assertEqual(asked(text), want, text)
        self.assertEqual(asked("Set the resolution.", title="Render 4K PNG Image"), "r")
        # Asks nothing: a script's or an image's save, a nameless save, settings, a path, a negation, a deferral, an
        # option ("(optional)", "optionally", "if desired" in its sentence)
        for text in ("Save the script as `corridor_builder.py`.", "Save the file.", "Save the changes.",
                     "Save each baked normal map to the same directory as the .blend file.",
                     "The script must be saved as a .py file and run via blender -b scene.blend --python s.py.",
                     "Set render engine to Cycles and set output path to //gate_opening.png.",
                     "Set render resolution to 1920x1080.", "Add a Render Layers node.",
                     "Ensure the script runs in background mode (no need to call bpy.ops.wm.save_mainfile).",
                     "Save the file as walk.fbx; do not render yet.",
                     'Set the output path to "./render/" and name files "frame_####.png".',
                     "Output a script that saves the ready‑to‑render scene settings.",
                     "Set up the camera for the final render of the animation.",
                     "Place the camera so it renders the scene from above.",
                     "Prepare the scene so that s6 can render the animation.",
                     "Use Eevee to render the scene quickly in later steps.",
                     "Keep the file ready to save as final.blend in s6.",
                     'After the loop, saves the blend again (optional) as "forest_final.blend".',
                     "Optionally save the scene as forest.blend.", "Render the animation to //a.mp4 if desired.",
                     "Optional: render a preview to //p.png.", "Render the image to //a.png if you like.",
                     "If needed, render the scene to //a.png."):
            self.assertEqual(asked(text), "", text)

        def handed(settings):
            return G.handed_outputs(MARK + "\nimport bpy\nSETTINGS_s1 = " + settings + "\n", "s1")
        self.assertEqual(handed('{"output": "x.blend"}')["blend"], "x.blend")
        self.assertEqual(handed('{"output": {"blend": "//a.blend", "render": "//a.mp4"}}'),
                         {"has": True, "blend": "//a.blend", "render": "//a.mp4", "video": True, "unread": False})
        self.assertEqual(handed('{"output": {"render": {"filepath": "//a.png"}}}')["render"], "//a.png")
        self.assertIsNone(handed('{"output": "//render/"}')["render"])  # no extension: _chimera_output renders nothing
        self.assertFalse(handed('{"output_path": "a.mp4"}')["has"])  # not the key Go's hasOutput reads
        self.assertTrue(handed('{"output": {"render": f"//{NAME}.png"}}')["unread"])
        self.assertFalse(G.handed_outputs("SETTINGS_s1 = {'output': 'x.blend'}", "s2")["has"])  # another step's

        plan = {"steps": [step("Set the resolution to 64x48. Render the image to //room.png and save the scene as "
                               "room.blend.")]}
        code = MARK + "\nimport bpy\nSETTINGS_s1 = {\"output_path\": \"room.png\"}\n"
        self.assertEqual(G.output_missing(plan, 0, code)[0], ["blend", "render"])
        reasons, det = _gate.measured_check(plan, 0, code, {"probe": {}})
        self.assertEqual(reasons, ["output_missing"])
        self.assertEqual(det["output_missing"]["missing"], ["blend", "render"])
        # The tell names the step's own files, never a placeholder a next try could copy; and the key the piece kept
        # its path under, which a retry that only adds "output" would keep (the build drops that: X58's told form)
        self.assertEqual(det["faults"], ['the step asks Chimera to save a .blend and to render, but SETTINGS_s1 has no '
                                         '"output": put the path or render settings in SETTINGS_s1["output"] '
                                         '("room.blend" and "//room.png") and Chimera does it once, after the last '
                                         'step',
                                         '"output_path" in SETTINGS_s1 is a key Chimera never reads (it reads only '
                                         '"output"): keep the path in "output" alone and leave the key out'])
        self.assertEqual(det["dead_output"], ["output_path"])
        self.assertNotIn("x.blend", det["faults"][0])
        self.assertEqual(T._blender_stage(reasons), "alone")
        # Handed over, with the old key kept: no reason (the build's to drop), but the line goes with any other fault
        kept = MARK + ('\nimport bpy\nSETTINGS_s1 = {"output": {"render": "//room.png", "blend": "room.blend"}, '
                       '"output_path": "room.png"}\n')
        reasons, det = _gate.measured_check(plan, 0, kept, {"probe": {}})
        self.assertEqual((reasons, det["dead_output"]), ([], ["output_path"]))
        self.assertEqual(G.tell_lines({"ok": False, "reasons": ["size_mismatch"], "measured": det}),
                         [G.dead_tell("s1", ["output_path"])])
        self.assertEqual(G.tell_lines({"ok": True, "reasons": [], "measured": det}), [])
        # A step that asks Chimera for nothing hears nothing of it: "output" there would be output_not_asked
        quiet = {"steps": [step("Define the room's sizes. No other code should be generated here.")]}
        self.assertEqual(_gate.measured_check(quiet, 0, code, {"probe": {}}), ([], {}))
        good = MARK + '\nimport bpy\nSETTINGS_s1 = {"output": {"render": "//room.png", "blend": "room.blend"}}\n'
        self.assertEqual(_gate.measured_check(plan, 0, good, {"probe": {}}), ([], {}))
        half = MARK + '\nimport bpy\nSETTINGS_s1 = {"output": "//room.png"}\n'
        reasons, det = _gate.measured_check(plan, 0, half, {"probe": {}})
        self.assertEqual((reasons, det["output_missing"]["missing"]), (["output_missing"], ["blend"]))
        self.assertIn('SETTINGS_s1["output"] has no .blend path', det["faults"][0])
        # A step that names no file gets what the path must end in
        bare = {"steps": [step("Render the animation and save the .blend file.")]}
        self.assertIn('(a .blend path and a .png or .mp4 path)', G.missing_tell(
            bare, 0, ["blend", "render"], {"has": False}, G.asked_outputs(bare, 0)))
        # A value that isn't a literal can't be read here: nothing is said
        unread = MARK + '\nimport bpy\nSETTINGS_s1 = {"output": {"render": PATH}}\n'
        self.assertEqual(G.output_missing(plan, 0, unread)[0], [])
        # The line stays inside what the notes keep of a line, with a long name the step gives too
        from datagen import hints as H
        long_name = {"steps": [step("Render the image to //" + "very_long_folder_name/" * 12 + "room.png.")]}
        for p in (plan, long_name):
            a = G.asked_outputs(p, 0)
            for m in (["blend"], ["render"], ["blend", "render"]):
                for h in ({"has": False}, {"has": True}):
                    self.assertLessEqual(len(G.missing_tell(p, 0, m, h, a)), H.FAILURE_CHARS)

    def test_a_step_that_adds_a_camera_of_its_own(self):
        def asks(text, title="Step", others=()):
            p = plan_of(*((title, text, ()),) + tuple(("Other", o, ()) for o in others))
            return G.asks_camera(p, 0) is not None
        # Asks: a making verb, an article at most and a few words that describe it, then "camera"
        for text in ('Creates a camera named "Camera" with a 35 mm focal length.',
                     "4. Adds a camera at (0, 0, 3) pointing at the origin, with a 35 mm lens.",
                     "Create a Camera named `Cam_Main` positioned at (0, -4, 2).", "Add area light and camera with DOF.",
                     "Place low‑angle camera.", "Add a Camera object at height 1.8 m.",
                     "Set up a camera named OrbitCam."):
            self.assertTrue(asks(text), text)
        self.assertTrue(asks("Lights only.", title="Set up three‑point lighting and camera"))
        # Asks nothing: words about a camera, the camera another step may have made, more than one or a second,
        # negated, optional, an existing one allowed, a camera-facing thing, a name
        for text in ("Also set up the camera settings (aperture, sensor size).", "Create camera animation.",
                     "Create a camera tracking path from the start to the end.", "Place the camera at (0, -5, 2).",
                     "Set up the camera with a suitable focal length.", "Creates three cameras for the views.",
                     "Add a second camera for a close-up.", "Do not add a camera.", "Optionally add a camera.",
                     "Creates a new camera (or uses an existing one named 'Camera') at the entrance.",
                     "Add a camera-facing plane.", "Add a mesh circle centered on the camera location.",
                     "Animate the camera along the path.", "Set camera_name = 'Camera'.",
                     "Add a small light behind the leaf relative to the camera."):
            self.assertFalse(asks(text), text)
        # Another step says which camera renders: the step adding it isn't held to it
        self.assertTrue(asks("Add a camera at (0, -5, 2).", others=("Render the image.",)))
        self.assertFalse(asks("Add a camera at (0, -5, 2).", others=("Sets the camera as the active camera.",)))
        self.assertFalse(asks("Add a camera at (0, -5, 2).", others=("Set bpy.context.scene.camera to it.",)))

        # The fact: the scene's camera after the run, as the measuring records it
        factory = dict(row("Camera", "CAMERA", f=1, loc=[7.36, -6.93, 4.96], dir=[-0.65, 0.61, -0.45], lens=50.0))
        mine = dict(row("chimera_cam", "CAMERA", f=0, loc=[0.0, -5.0, 2.0], dir=[0.0, 1.0, 0.0], lens=35.0))
        moved = dict(factory, loc=[0.0, -5.0, 2.0])
        self.assertEqual([G.camera_made(x) for x in (mine, moved, factory, None)], [True, True, False, False])
        self.assertIsNone(G.camera_fault([{"scene_camera": mine}, {"scene_camera": mine}]))
        self.assertIsNone(G.camera_fault([{"scene_camera": factory}, {"scene_camera": mine}]))  # every version shows it
        self.assertEqual(G.camera_fault([{"scene_camera": factory}, {"scene_camera": factory}]), "factory")
        self.assertEqual(G.camera_fault([{"scene_camera": None}, {"scene_camera": None}]), "none")
        self.assertIsNone(G.camera_fault([{"objects": []}, {"objects": []}]))  # an older run recorded no camera
        self.assertEqual(G.camera_fault([{"objects": []}, {"scene_camera": factory}]), "factory")

        plan = plan_of(("Camera", "Add a camera chimera_cam at (0, -5, 2) looking at the origin.", ()))
        code = MARK + "\nimport bpy\nSETTINGS_s1 = {\"lens\": 35.0}\n"
        first, second = list(blenders.VERSIONS)

        def check(*cams):
            return _gate.measured_check(plan, 0, code, {"probe": {v: {"measure": {"objects": [], "scene_camera": c}}
                                                                  for v, c in zip((first, second), cams)}})
        reasons, det = check(factory, factory)
        self.assertEqual(reasons, ["camera_not_active"])
        self.assertEqual(det["faults"], [G.CAMERA_TELL["factory"]])
        self.assertEqual((det["camera"]["fits"], T._blender_stage(reasons)), (False, "alone"))
        self.assertEqual(check(None, None)[1]["faults"], [G.CAMERA_TELL["none"]])
        reasons, det = check(mine, mine)
        self.assertEqual((reasons, det["camera"]["fits"]), ([], True))
        reasons, det = _gate.measured_check(plan, 0, code, {"probe": {first: {"measure": {"objects": []}}}})
        self.assertEqual((reasons, det["camera"]["fits"]), ([], None))  # nothing recorded: nothing said
        # Joined, the camera isn't checked again: the alone run was
        self.assertEqual(_gate.measured_check(plan, 0, code, {"probe": {first: {"measure": {"scene_camera": factory}}}},
                                              joined={"s1"}, codes={}), ([], {}))

    def test_a_copy_of_the_factory_camera_the_step_asks_for_by_name(self):
        fac = [{"name": "Camera", "type": "CAMERA", "data": "Camera"}, {"name": "Cube", "type": "MESH", "data": "Cube"},
               {"name": "Light", "type": "LIGHT", "data": "Light"}]
        ask = 'Creates a camera named "Camera" with a 35 mm lens ' + MARK
        copy = {"name": "Camera.001", "type": "CAMERA", "data": "Camera.001"}

        def rec(objs, dupes, cam):
            return {"scene": {"objects": fac + objs}, "dupes": dupes, "measure": {"scene_camera": cam}}
        made_active = rec([copy], ["Camera.001"], {"n": "Camera.001", "f": 0})
        self.assertEqual(G.factory_copies(made_active, ask), ["Camera.001"])
        # The factory camera still renders (smoke2's n-blender-0000-01 round-1 tries): a real duplicate
        self.assertEqual(G.factory_copies(rec([copy], ["Camera.001"], {"n": "Camera", "f": 1}), ask), [])
        self.assertEqual(G.factory_copies(made_active, "Add a camera at 35 mm " + MARK), [])  # not asked by name
        self.assertEqual(G.factory_copies(made_active, ask, later='Make the camera "Camera" orbit ' + MARK), [])
        two = rec([copy, {"name": "Camera.002", "type": "CAMERA", "data": "b"}], ["Camera.001", "Camera.002"],
                  {"n": "Camera.002", "f": 0})
        self.assertEqual(G.factory_copies(two, ask), [])  # two steps made "Camera"
        self.assertEqual(G.factory_copies(rec([dict(copy, type="MESH")], ["Camera.001"], {"n": "Camera", "f": 1}),
                                          ask), [])
        cube = rec([{"name": "Cube.001", "type": "MESH", "data": "Cube.001"}], ["Cube.001"], {"n": "Camera", "f": 1})
        self.assertEqual(G.factory_copies(cube, 'A cube named "Cube" ' + MARK), [])  # never a cube's copy
        self.assertEqual(G.factory_copies({"scene": {"objects": fac + [copy]}, "dupes": ["Camera.001"]}, ask), [])
        self.assertEqual(G.real_dupes({"probe": {"a": made_active, "b": made_active}}, ["a", "b"], ask),
                         ([], ["Camera.001"]))
        still = rec([copy], ["Camera.001"], {"n": "Camera", "f": 1})
        self.assertEqual(G.real_dupes({"probe": {"a": made_active, "b": still}}, ["a", "b"], ask),
                         (["Camera.001"], []))  # every version has to explain it
        sofa = rec([{"name": "chimera_sofa", "type": "MESH", "data": "x"},
                    {"name": "chimera_sofa.001", "type": "MESH", "data": "y"}], ["chimera_sofa.001"],
                   {"n": "Camera", "f": 1})
        self.assertEqual(G.real_dupes({"probe": {"a": sofa}}, ["a"], ask), (["chimera_sofa.001"], []))

    def test_this_rounds_tell_wordings_are_known_to_the_echo_check(self):
        from datagen import hints as H
        plan = {"steps": [step("Render the animation to //a.mp4 and save the scene as a.blend.")]}
        a = G.asked_outputs(plan, 0)
        lines = [G.missing_tell(plan, 0, m, {"has": False}, a) for m in (["blend"], ["render"], ["blend", "render"])]
        lines += list(G.CAMERA_TELL.values())
        lines += [G.dead_tell("s1", ["output_path"]), G.dead_tell("s1", ["output_dir", "output_pattern"])]
        # ctx_tell's: its head, the write advice's two runs (either side of SETTINGS_s1), the read advice whole
        lines += [G.ctx_tell("s1", ["variables"], [])] * 3 + [G.ctx_tell("s2", [], ["settings"])]
        # build_facts' (after the fourth smoke): the unasked dead keys' two forms, then the warnings' lines (the
        # provides line's two runs, its own-stand-in form, both uses forms) and the four long lines' advice
        lines += [G.dead_tell("s1", ["output_path"], asked=False), G.dead_tell("s1", ["a_dir", "a_path"], asked=False)]
        from tests.test_datagen_stand_ins import warning_rows
        lines += [x["tell"] for x in warning_rows()]
        # the stand-in marker's (stand_ins.TELL_FORMS): the marker, the silent literal keys, the silent helper
        from datagen import stand_ins
        lines += stand_ins.tell({"marker": ["render_device"], "silent": [{"key": "fps", "line": 3, "function": None},
                                                                         {"key": None, "line": 9, "function": "get"}]})
        # ... and, since the fifth smoke (Nov 6), the marker's for a missing input file
        lines += stand_ins.tell({"marker": ["svg_path"], "files": ["svg_path"], "silent": []})
        # the hidden errors' (silent.TELL_FORMS): both swallowed forms, and the skipped input's three runs
        lines += silent.tell([{"line": 9, "source": "curves = list(action.fcurves)",
                               "error": "AttributeError: 'Action' object has no attribute 'fcurves'"},
                              {"line": 4, "source": 'im.file_format = "FFMPEG"', "error": "TypeError: enum not found"}],
                             [])
        lines += silent.tell([], [{"line": 6, "key": "Base_Color", "owner": "glass", "node": "Principled BSDF",
                                   "close": ["Base Color"]}]) * 3
        # global_ctx's (after the fifth smoke): its line's two runs, either side of build_s2
        lines += [G.global_ctx_tell("s2", [{"function": "_s2_link", "line": 9}])] * 2
        # the geometry's (geometry.TELL_FORMS): the place line's end and the depth line's start (nested's has none)
        from datagen import geometry
        geo = plan_of(("Sign", 'Add a sign named "chimera_sign" at (1, 0, 0). Extrude the curve by 0.08 m.', ()))
        rec = {"geom": {"objects": [{"n": "chimera_sign", "t": "MESH", "lo": [0, 0, 0], "hi": [1, 1, 1], "faces": 6},
                                    {"n": "chimera_wave", "t": "CURVE", "lo": [0, 0, 0], "hi": [2, 1, 0], "faces": 0}]},
               "measure": {"objects": []}}
        lines += [geometry.place_faults(geometry.asked_places(geo, 0), rec)[0][1],
                  geometry.depth_faults(geometry.asked_depths(geo, 0), rec)[0][1]]
        # doubled_depth's (Nov 5): its run after the depth (its start is the depth line's, registered once)
        down = plan_of(("Sign", 'Add a text named "chimera_wave". Extrude the curve by 0.08 m in the negative Z '
                                'direction.', ()))
        thick = {"geom": {"objects": [{"n": "chimera_wave", "t": "FONT", "lo": [0, 0, -0.08], "hi": [2, 1, 0.08],
                                       "faces": 900}]}, "measure": {"objects": []}}
        lines += [geometry.doubled_states(geometry.asked_doubled(down, 0), thick)[0][1]]
        # ... and its line for a thing that is no curve or text (Nov 6)
        thick["geom"]["objects"][0]["t"] = "MESH"
        lines += [geometry.doubled_states(geometry.asked_doubled(down, 0), thick)[0][1]]
        self.assertEqual(len(G.TELL_FORMS), len(lines))
        for form, line in zip(G.TELL_FORMS, lines):
            self.assertIn(form, line)
            self.assertGreaterEqual(len(H._WORD.findall(form)), H.NOTE_MIN)
            self.assertFalse(any(v in form for v in blenders.VERSIONS))
            self.assertTrue(H.echoed_note("# " + form + "\nimport bpy\n"), form)  # a reply that repeats it is ours
        # output_missing's advice is Chimera's own words: a reply that says them isn't an echo of the notes
        self.assertIsNone(H.echoed_note('assumed: Chimera does it once, after the last step, from SETTINGS_s1["output"]'))
        # ... and so is ctx_tell's output advice, which TELL_FORMS leaves out
        self.assertFalse(any(G.CTX_ADVICE["output"].split("{sid}")[0].strip() in f for f in G.TELL_FORMS))

    def test_the_ctx_forms_are_never_chimeras_words_nor_a_right_retrys(self):
        """The fixed notes and forms aren't request-excluded in echoed_note: none of ctx_tell's may share a run with
        Chimera's Blender rule (its Nov 4 sentence about ctx["values"] included), or a reply that quotes Chimera
        would be refused; and a piece that hands its values on as the contract says repeats none of them."""
        from datagen import hints as H
        from contract import texts
        ours = [f for f in G.TELL_FORMS
                if f.startswith(("Chimera's ctx", "put each value", "key and list", "take what"))]
        self.assertEqual(len(ours), 4)
        rule = texts.fill(texts.MODE_BLENDER, sid="s1")
        self.assertIn('ctx["values"] is the same for plain values other steps use', rule)  # the Nov 4 rule text
        for form in ours:
            n = min(H.NOTE_N, len(H._WORD.findall(form)))
            self.assertFalse(H.runs(form, n) & H.runs(rule, n), form)
        self.assertIsNone(H.echoed_note(rule))
        for text in (CF.VALUES_S1, CF.VALUES_S2):  # a values step and its reader, written as the contract says
            self.assertIsNone(H.echoed_note(text))

    def test_ctx_channel_parts_split_what_a_piece_writes_from_what_it_reads(self):
        def parts(body):
            code = MARK + "\nimport bpy\nSETTINGS_s1 = {}\n\n\ndef build_s1(ctx):\n" + body
            p = G.ctx_channel_parts(code)
            self.assertEqual(sorted(p["written"] + p["read"]), G.ctx_channel(code), body)  # the same keys, split
            return p
        self.assertEqual(parts('    ctx["variables"] = SETTINGS_s1\n'), {"written": ["variables"], "read": []})
        self.assertEqual(parts('    s = ctx.get("settings", {})\n'), {"written": [], "read": ["settings"]})
        # ctx["values"] is the contract's since Nov 4: neither, written or read, like ctx["objects"]
        self.assertEqual(parts('    ctx["values"]["width"] = SETTINGS_s1["width"]\n'
                               '    w = ctx["values"].get("depth")\n    ctx.setdefault("values", {})["x"] = 1\n'
                               '    v = ctx.get("values") or ctx["values"]\n'),
                         {"written": [], "read": []})
        # a key written and read is written only; every way of writing and reading ctx_channel reads
        self.assertEqual(parts('    ctx["variables"] = {}\n    n = ctx["variables"]["n"]\n    m = ctx.get("mode")\n'
                               '    ctx.update({"a": 1}, b=2)\n    ctx |= {"c": 3}\n    ctx.setdefault("d", 0)\n'),
                         {"written": ["a", "b", "c", "d", "variables"], "read": ["mode"]})
        self.assertEqual(G.ctx_channel_parts("def build_s1(ctx:\n"), {"written": [], "read": []})
        self.assertEqual(G.ctx_channel_parts(None), {"written": [], "read": []})

    def test_the_ctx_tell_picks_its_form_and_stays_short(self):
        head = 'Chimera\'s ctx has only "scene", "collection", "objects" and "values", not '
        self.assertIsNone(G.ctx_tell("s1", [], []))
        self.assertEqual(G.ctx_tell("s1", ["variables"], []),
                         head + 'ctx["variables"]: put each value a later step uses in ctx["values"] under its '
                         'SETTINGS_s1 key and list the keys under provides')
        self.assertEqual(G.ctx_tell("s2", [], ["settings"]),
                         head + 'ctx["settings"]: take what a dependency lists under provides from ctx["values"] or '
                         'ctx["objects"], with a stand-in if it is missing')
        # every key it writes names an output: Chimera's own words about "output"
        out = G.ctx_tell("s5", ["blend_save_path"], ["variables"])
        self.assertEqual(out, head + 'ctx["blend_save_path"], ctx["variables"]: put the path or render settings in '
                         'SETTINGS_s5["output"] and Chimera does it once, after the last step')
        for k in ("output", "outputs", "output_path", "render_dir", "save_folder"):
            self.assertIn('SETTINGS_s1["output"]', G.ctx_tell("s1", [k], []), k)
        # one value among them: the write form
        self.assertIn("put each value", G.ctx_tell("s1", ["output", "panel_spacing"], []))
        # the first three keys, writes first, then " and more"
        self.assertIn('not ctx["x"], ctx["a"], ctx["b"] and more: ', G.ctx_tell("s1", ["x"], ["a", "b", "c"]))
        self.assertIn('not ctx["x"], ctx["a"], ctx["b"]: ', G.ctx_tell("s1", ["x"], ["a", "b"]))
        # long keys: only the first is quoted, and the line is cut at FAILURE_CHARS
        from datagen.hints import FAILURE_CHARS
        long = G.ctx_tell("s1", ["k" * 90, "j" * 90], ["i" * 90])
        self.assertTrue(long.startswith(head + 'ctx["' + "k" * 90 + '"] and more: put each value'), long)
        self.assertLessEqual(len(long), FAILURE_CHARS)
        self.assertLessEqual(len(G.ctx_tell("s1", ["k" * 400], [])), FAILURE_CHARS)
        # the advice names only the contract's own names, never a key to copy
        for kind in ("write", "read"):
            line = G.ctx_tell("s3", ["variables"] if kind == "write" else [], ["settings"])
            self.assertNotIn("table_height", line)
            self.assertFalse(any(v in line for v in blenders.VERSIONS))

    def test_ctx_keys_and_settings_keys_chimera_never_reads(self):
        def channel(body):
            return G.ctx_channel(MARK + "\nimport bpy\nSETTINGS_s1 = {}\n\n\ndef build_s1(ctx):\n" + body)
        self.assertEqual(channel('    ctx["variables"] = SETTINGS_s1\n    ctx["objects"]["box"] = None\n'),
                         ["variables"])
        self.assertEqual(channel('    ctx.setdefault("settings", {})["x"] = 1\n    ctx.update({"a": 1}, b=2)\n'
                                 '    ctx |= {"c": 3}\n    ctx["n"] += 1\n'), ["a", "b", "c", "n", "settings"])
        self.assertEqual(channel('    ctx["scene"].frame_end = 9\n    ctx["collection"] = ctx["scene"].collection\n'
                                 '    if "mode" in ctx or ctx.get("objects", {}).get("box"):\n        pass\n'
                                 '    ctx["objects"]["lamp"] = ctx["objects"].get("table")\n'), [])
        # ctx["values"] is the contract's since Nov 4 (the user's decision on contract question 1)
        self.assertEqual(G.CTX_CONTRACT, ("scene", "collection", "objects", "values"))
        self.assertEqual(channel('    ctx["values"]["height"] = SETTINGS_s1["height"]\n'
                                 '    ctx.setdefault("values", {}).update(SETTINGS_s1)\n'
                                 '    w = ctx["values"].get("width", 1.0)\n    v = ctx.get("values", {})\n'), [])
        # The reading side of the same channel (smoke2's X27 and X18: s1 handed its values on in ctx["variables"])
        self.assertEqual(channel('    vars_ = ctx.get("variables", {})\n    if ctx["mode"] == "x":\n        pass\n'
                                 '    n = ctx["settings"]["count"]\n'), ["mode", "settings", "variables"])
        self.assertEqual(G.ctx_channel(MARK + "\ndef build_s2(c):\n    c['materials'] = {}\n"), ["materials"])
        self.assertEqual(G.ctx_channel('s = """\ndef build_s1(ctx):\n    ctx["settings"] = 1\n"""\n'), [])  # a string
        self.assertEqual(G.ctx_channel("def build_s1(ctx:\n"), [])

        def dead(settings, sid="s1"):
            return G.dead_output_key(MARK + "\nimport bpy\nSETTINGS_s1 = " + settings + "\n", sid)
        self.assertEqual(dead('{"output_path": "//a.mp4", "output_format": "FFMPEG", "size": 2}'),
                         ["output_format", "output_path"])
        self.assertEqual(dead('{"render_filepath": "//a.png", "output_fileformat": "PNG"}'),
                         ["output_fileformat", "render_filepath"])
        self.assertEqual(dead('{"output": {"filepath": "//a.png", "file_format": "PNG"}}'), [])  # Chimera's to read
        self.assertEqual(dead('{"output": "//a.png", "lens": 35}'), [])
        self.assertEqual(dead('{"output_path": "//a.png"}', sid="s2"), [])  # another step's

        # A key the piece reads itself: a place is still dead (X58: the path set on scene.render, no render asked of
        # Chimera), a format or colour mode is a setting it applies, and a file of its own (a script) is its own
        def reads(settings, step_=None):
            return G.dead_output_key(MARK + "\nimport bpy\nSETTINGS_s5 = " + settings + "\n\n\ndef build_s5(ctx):\n"
                                     "    s = SETTINGS_s5\n    r = ctx['scene'].render\n"
                                     "    r.filepath = s['output_path']\n"
                                     "    r.image_settings.file_format = s.get('output_format', 'PNG')\n", "s5", step_)
        self.assertEqual(reads('{"output_path": "//forest_clearing", "output_format": "PNG"}'), ["output_path"])
        self.assertEqual(reads('{"output_path": "//forest_clearing", "output_format": "PNG", "output_dir": "x"}'),
                         ["output_dir", "output_path"])  # output_dir isn't read
        self.assertEqual(reads('{"output_path": "//room.py"}'), [])
        # A step that asks to set the output path and format itself, and no render or save of Chimera (the first
        # run's n-blender-0002-02 s5): applying them is what it says
        sets = step('Set the engine to EEVEE. Finally, set the output filepath to "//forest_clearing" and image '
                    'format to PNG.', title="Add Light, Camera, and Render Settings")
        self.assertTrue(G.sets_output(sets))
        self.assertEqual(reads('{"output_path": "//forest_clearing", "output_format": "PNG"}', sets), [])
        self.assertEqual(reads('{"output_path": "//forest_clearing", "output_dir": "x"}', sets), ["output_dir"])
        # ... but not one that asks Chimera to render, nor one whose words say nothing of the output (X23: a values
        # step with an unasked placeholder path it applies)
        for words in ("Set the output filepath to //forest_clearing and render the image.",
                      "Define the room's sizes and colours. No other code should be generated here."):
            self.assertFalse(G.sets_output(step(words)), words)
            self.assertEqual(reads('{"output_path": "//render", "output_format": "PNG"}', step(words)),
                             ["output_path"], words)

    def test_size_faults_against_measured_rows(self):
        asked = G.size_triples("a kitchen island (2.4 m × 0.9 m × 0.92 m) " + MARK)

        def faults(rows, **kw):
            return G.size_faults(asked, dict({"objects": FACTORY_ROWS + rows, "groups": []}, **kw))
        self.assertEqual(faults([row("chimera_island", size=[2.4, 0.9, 0.92])]), [])
        self.assertEqual(faults([row("chimera_island", size=[0.92, 2.3, 0.86])]), [])  # turned, and within 10%
        (k, line), = faults([row("chimera_island", size=[1.2, 0.45, 0.46]), row("chimera_lamp", size=[2.0, 1.0, 1.0])])
        self.assertEqual(k, 0)
        self.assertEqual(line, "no object measures 2.4 × 0.9 × 0.92 m for the kitchen island (its size from the "
                               "step); the nearest is chimera_island at 1.2 × 0.45 × 0.46 m, half the size asked on "
                               "every side")
        # Parts that make one thing count: an object with its children, objects named after one word
        parts = [row("chimera_island_top", size=[2.4, 0.9, 0.05]), row("chimera_island_base", size=[2.3, 0.8, 0.87])]
        self.assertEqual(faults(parts, groups=[{"g": "named", "n": "island", "of": 2, "size": [2.4, 0.9, 0.92]}]), [])
        # So does an object's own mesh, before a modifier (a dependency's stand-in node group) empties it
        self.assertEqual(faults([row("chimera_island", size=[0.0, 0.0, 0.0], mods=["NODES"], base=[2.4, 0.9, 0.92])]),
                         [])
        # Nothing measured, or other units: nothing to say
        self.assertEqual(faults([]), [])
        self.assertEqual(faults([row("chimera_island", size=[1.2, 0.45, 0.46])], unit_scale=0.01), [])
        # The factory cube counts only once the piece has changed it
        self.assertEqual(len(faults([row("chimera_rug", size=[1.0, 1.0, 0.01])])), 1)
        moved = [dict(FACTORY_ROWS[0], size=[2.4, 0.9, 0.92])]
        self.assertEqual(G.size_faults(asked, {"objects": moved + FACTORY_ROWS[1:], "groups": []}), [])
        # A side named by a variable: the given ones must fit
        partial = G.size_triples("Sofa: sofa_dim (length) × 0.9 m (width) × 0.8 m (height) " + MARK)
        self.assertEqual(G.size_faults(partial, {"objects": [row("chimera_sofa", size=[2.2, 0.9, 0.8])]}), [])
        (_, line), = G.size_faults(partial, {"objects": [row("chimera_sofa", size=[1.1, 0.45, 0.4])]})
        self.assertEqual(line, "no object measures ? × 0.9 × 0.8 m for the sofa (its size from the step, ? being "
                               "sofa_dim); the nearest is chimera_sofa at 1.1 × 0.45 × 0.4 m")

    def test_a_size_tell_names_the_thing_and_never_quotes_the_step(self):
        values = step("Dimensions in meters: sofa_length=2.2, sofa_width=0.9, sofa_height=0.8, "
                      "coffee_table_length=1.2, coffee_table_width=0.6, coffee_table_height=0.4.",
                      title="Define dimensions, colours, and scene settings")
        plan = {"steps": [values, step("Create the sofa and the coffee table.", title="Furniture", depends_on=["s1"])]}
        asked = G.asked_sizes(plan, 1)
        got = G.size_faults(asked, {"objects": [row("chimera_Sofa", size=[1.0, 1.0, 1.0]),
                                                row("chimera_CoffeeTable", size=[1.2, 0.6, 0.4])]})
        self.assertEqual(got, [(0, "no object measures 2.2 × 0.9 × 0.8 m for the sofa (its size from s1); the nearest "
                                   "is chimera_Sofa at 1 × 1 × 1 m")])
        # The step's own words (the values step's assignments, its phrase) are never in the line
        for a in asked:
            self.assertNotIn(a["phrase"], got[0][1])
        self.assertNotIn("sofa_length", got[0][1])
        kitchen = {"steps": [step("Creates a rectangular island countertop (2.4 m × 0.9 m × 0.92 m) using a plane.")]}
        unit = {"objects": [row("chimera_island", size=[1.0, 1.0, 1.0])]}
        (_, line), = G.size_faults(G.asked_sizes(kitchen, 0), unit)
        self.assertNotIn("countertop (2.4", line)
        self.assertTrue(line.startswith("no object measures 2.4 × 0.9 × 0.92 m for the island countertop (its size "
                                        "from the step)"), line)

    def test_aim_faults_against_measured_rows(self):
        ceiling = G.asked_aims({"steps": [step("Add a ceiling area light and a side spotlight.")]}, 0)

        def faults(rows):
            return G.aim_faults(ceiling, {"objects": FACTORY_ROWS + rows})
        down = row("chimera_ceiling_light", "LIGHT", light="AREA", dir=[0.0, 0.0, -1.0], power=800.0)
        up = dict(down, dir=[0.0, 0.0, 1.0])
        spot = row("chimera_spot", "LIGHT", light="SPOT", dir=[0.6, 0.0, -0.8])
        self.assertEqual(faults([down, spot]), [])
        (k, line), = faults([up, spot])
        self.assertEqual(line, "the step says the ceiling area light points down, but chimera_ceiling_light emits "
                               "along (0, 0, 1), upward")
        # Its name says which one when several are there; another area light pointing down doesn't excuse it
        self.assertEqual(len(faults([up, row("chimera_fill", "LIGHT", light="AREA", dir=[0.0, 0.0, -1.0])])), 1)
        self.assertEqual(faults([row("chimera_fill", "LIGHT", light="AREA", dir=[0.0, 0.3, -0.95])]), [])
        sideways = dict(down, dir=[0.9, 0.0, -0.44])
        self.assertIn("not down (z should be at most -0.5)", faults([sideways])[0][1])
        # Exactly at the limit is down enough (30 degrees below level)
        self.assertEqual(faults([dict(down, dir=[0.87, 0.0, -0.5])]), [])
        # None of that kind: nothing to say (a point light has no direction; the factory light isn't the piece's)
        self.assertEqual(faults([row("chimera_bulb", "LIGHT", light="POINT", dir=[0.0, 0.0, 1.0])]), [])
        self.assertEqual(faults([]), [])
        camera = G.asked_aims({"steps": [step("Point the camera straight down at the floor.")]}, 0)
        self.assertEqual(G.aim_faults(camera, {"objects": [row("chimera_cam", "CAMERA", dir=[0.0, 0.0, -1.0])]}), [])
        (_, line), = G.aim_faults(camera, {"objects": [row("chimera_cam", "CAMERA", dir=[0.0, 1.0, 0.0])]})
        self.assertIn("chimera_cam looks along (0, 1, 0)", line)
        # An angle the step gives: a camera tilted 15 degrees down passes, one barely tilted doesn't
        tilted = G.asked_aims({"steps": [step("a camera tilted down 15 degrees toward the table")]}, 0)
        self.assertEqual(G.aim_faults(tilted, {"objects": [row("chimera_cam", "CAMERA", dir=[0.0, 0.97, -0.26])]}), [])
        (_, line), = G.aim_faults(tilted, {"objects": [row("chimera_cam", "CAMERA", dir=[0.0, 1.0, -0.05])]})
        self.assertEqual(line, "the step says the camera points 15 degrees down, but chimera_cam looks along "
                               "(0, 1, -0.05), not that far down (z should be at most -0.16)")
        exact = G.asked_aims({"steps": [step("a sun angled down at 30 degrees")]}, 0)
        self.assertEqual(G.aim_faults(exact, {"objects": [row("chimera_sun", "LIGHT", light="SUN",
                                                                dir=[0.87, 0.0, -0.5])]}), [])

    def test_a_size_from_a_values_step_is_measured_joined(self):
        """Pure: measured_check on hand-made measuring lines, the alone run's and the joined run's."""
        values = step("Dimensions in meters: bench_length=1.8, bench_width=0.45, bench_height=0.5.",
                      title="Define dimensions")
        plan = {"steps": [values, step("Create the bench chimera_bench.", title="Bench", depends_on=["s1"])]}
        stand_in = {"objects": [row("chimera_bench", size=[1.0, 1.0, 1.0])]}  # alone: its stand-in defaults
        right = {"objects": [row("chimera_bench", size=[1.8, 0.45, 0.5])]}
        half = {"objects": [row("chimera_bench", size=[0.9, 0.23, 0.25])]}

        def run(m):
            return {"probe": {v: {"measure": m} for v in blenders.VERSIONS}}
        code = MARK + "\nimport bpy\n"
        self.assertEqual(_gate.measured_check(plan, 1, code, run(stand_in)), ([], {}))  # not asked alone
        self.assertEqual(_gate.measured_check(plan, 1, code, run(right), joined={"s1", "s2"})[0], [])
        reasons, det = _gate.measured_check(plan, 1, code, run(half), joined={"s1", "s2"})
        self.assertEqual(reasons, ["size_mismatch"])
        self.assertEqual([(a["source"], a["fits"]) for a in det["joined_sizes"]], [("s1", False)])
        self.assertEqual(det["faults"], ["no object measures 1.8 × 0.45 × 0.5 m for the bench (its size from s1); "
                                         "the nearest is chimera_bench at 0.9 × 0.23 × 0.25 m, half the size asked on "
                                         "every side"])
        # The values step isn't in the join (it was dropped): nothing to hold it to
        self.assertEqual(_gate.measured_check(plan, 1, code, run(half), joined={"s2"}), ([], {}))
        # A size from the step's own words is the alone run's, never the joined one's
        own = {"steps": [step("Create a 1.8 × 0.45 × 0.5 m bench chimera_bench.", title="Bench")]}
        self.assertEqual(_gate.measured_check(own, 0, code, run(half))[0], ["size_mismatch"])
        self.assertEqual(_gate.measured_check(own, 0, code, run(half), joined={"s1"}), ([], {}))

    def test_a_size_the_measuring_left_out_is_unmeasured_not_wrong(self):
        """r2-blender-0 (a): the measuring keeps MEASURE_KEEP objects; a thing none of the kept is named after may be
        among the others."""
        asked = [{"thing": "bench", "sides": [1.8, 0.45, 0.5], "words": ["bench"], "source": "s1"}]
        arches = [row("chimera_arch_%02d" % k, size=[0.3, 0.3, 0.3]) for k in range(40)]
        cut = {"objects": arches, "groups": [], "cut": {"objects": 7}}
        self.assertEqual(G.size_states(asked, cut), [("unmeasured", "cut")])
        self.assertEqual(G.size_faults(asked, cut), [])
        # The bench measured, at half its size: a fault, cut or not; nothing cut and nothing named: a fault as before
        half = dict(cut, objects=arches + [row("chimera_bench", size=[0.9, 0.23, 0.25])])
        self.assertEqual([x for x, _ in G.size_states(asked, half)], ["fault"])
        self.assertEqual([x for x, _ in G.size_states(asked, dict(cut, cut={}))], ["fault"])
        # Groups of parts left out, none kept named after it: one of them may have been the bench
        legs = [row("chimera_bench_leg_%d" % k, size=[0.05, 0.05, 0.45]) for k in range(4)]
        self.assertEqual(G.size_states(asked, {"objects": legs, "groups": [], "cut": {"groups": 3}}),
                         [("unmeasured", "cut")])
        self.assertEqual(G.size_states(asked, {"objects": [], "groups": []}), [("unmeasured", "nothing")])

    def test_settings_sides_read_what_a_values_piece_sets(self):
        def sides(settings, sid="s1"):
            return G.settings_sides(MARK + "\nimport bpy, math\nSETTINGS_s1 = " + settings + "\n", sid)
        self.assertEqual(sides('{"bench_length": 1.8, "bench_depth": 0.45, "bench_height": 0.5, "count": 3}'),
                         {"bench": [1.8, 0.45, 0.5]})
        self.assertEqual(sides('{"bench": {"length": 2, "width": 0.45}, "lamp_height": 2.0}'),
                         {"bench": [2.0, 0.45, None], "lamp": [None, None, 2.0]})
        self.assertEqual(sides('{"dims": {"coffee_table_size_x": 1.2, "coffee_table_size_y": 0.6, '
                               '"coffee_table_size_z": 0.4}}'), {"coffee_table": [1.2, 0.6, 0.4]})
        self.assertEqual(sides('{"bench_size": (1.8, 0.45, 0.5), "bench_location": (0, 0, 1)}'),
                         {"bench": [1.8, 0.45, 0.5]})
        # Only literal numbers count; another step's settings, none, or code that doesn't parse: nothing
        self.assertEqual(sides('{"room_length": 20, "panel_tilt_rad": math.radians(15), "room_height": WALL, '
                               '"use_floor_length": True}'), {"room": [20.0, None, None]})
        self.assertEqual(sides('{"bench_length": 1.8}', sid="s2"), {})
        self.assertEqual(G.settings_sides(MARK + "\nimport bpy\n", "s1"), {})
        self.assertEqual(G.settings_sides(MARK + "\nSETTINGS_s1 = {\n", "s1"), {})

    def test_a_size_from_a_values_step_is_held_to_what_its_piece_sets(self):
        """r2-blender-0 (b), pure: measured_check joined, with the join's code by worker name."""
        values = step("Dimensions in meters: bench_length=1.8, bench_width=0.45, bench_height=0.5.",
                      title="Define dimensions")
        plan = {"steps": [values, step("Create the bench chimera_bench.", title="Bench", depends_on=["s1"])]}
        code = MARK + "\nimport bpy\n"

        def piece(settings):
            return MARK + "\nimport bpy\n\nSETTINGS_s1 = " + settings + "\n\n\ndef build_s1(ctx):\n    pass\n"

        def check(size, settings):
            m = {"objects": [row("chimera_bench", size=size)]}
            run = {"probe": {v: {"measure": m} for v in blenders.VERSIONS}}
            return _gate.measured_check(plan, 1, code, run, joined={"s1", "s2"}, codes={"s1": piece(settings)})
        same = '{"bench_length": 1.8, "bench_width": 0.45, "bench_height": 0.5}'
        reasons, det = check([1.8, 0.45, 0.5], same)
        self.assertEqual((reasons, det["joined_sizes"][0]["fits"], det["joined_sizes"][0]["piece_sides"]),
                         ([], True, [1.8, 0.45, 0.5]))
        reasons, det = check([0.9, 0.23, 0.25], same)
        self.assertEqual(reasons, ["size_mismatch"])
        # Close to the words: held to the piece's own numbers, which the line then gives
        reasons, det = check([0.9, 0.23, 0.25], '{"bench_length": 1.85, "bench_width": 0.45, "bench_height": 0.5}')
        self.assertTrue(det["faults"][0].startswith("no object measures 1.85 × 0.45 × 0.5 m for the bench"),
                        det["faults"])
        # Other values than its words: a dependent that reads them (2.4) and one that writes the words in (1.8)
        # are both left unjudged, so neither is the better example
        other = '{"bench_length": 2.4, "bench_width": 0.45, "bench_height": 0.5}'
        for size in ([2.4, 0.45, 0.5], [1.8, 0.45, 0.5]):
            reasons, det = check(size, other)
            got = det["joined_sizes"][0]
            self.assertEqual((reasons, got["fits"], got["unmeasured"], got["piece_sides"]),
                             ([], None, "other_values", [2.4, 0.45, 0.5]), size)
        self.assertEqual(check([1.8, 0.45, 0.5], '{"bench_length": 2.4}')[1]["joined_sizes"][0]["unmeasured"],
                         "other_values")  # one side it sets is enough to differ
        # Values it doesn't set, or some that agree: held to the words, as before
        for settings in ('{"count": 3}', '{"bench_length": 1.8}'):
            self.assertEqual(check([0.9, 0.23, 0.25], settings)[0], ["size_mismatch"], settings)
        reasons, det = _gate.measured_check(plan, 1, code, {"probe": {v: {"measure": {"objects": [
            row("chimera_bench", size=[0.9, 0.23, 0.25])]}} for v in blenders.VERSIONS}}, joined={"s1", "s2"})
        self.assertEqual(reasons, ["size_mismatch"])  # no codes: the words
        # The joined measure cut before the bench: unmeasured
        cut = {"objects": [row("chimera_arch_%02d" % k, size=[0.3, 0.3, 0.3]) for k in range(40)],
               "cut": {"objects": 7}}
        reasons, det = _gate.measured_check(plan, 1, code, {"probe": {v: {"measure": cut} for v in blenders.VERSIONS}},
                                            joined={"s1", "s2"}, codes={"s1": piece(same)})
        self.assertEqual((reasons, det["joined_sizes"][0]["fits"], det["joined_sizes"][0]["unmeasured"]),
                         ([], None, "cut"))

    def test_a_measured_fault_counts_only_when_every_version_shows_it(self):
        first, second = list(blenders.VERSIONS)
        good = {"objects": [row("chimera_island", size=[2.4, 0.9, 0.92])]}
        half = {"objects": [row("chimera_island", size=[1.2, 0.45, 0.46])]}
        code = verdict(KITCHEN_PLAN, 0, ISLAND)["code"]
        reasons, det = _gate.measured_check(KITCHEN_PLAN, 0, code, {"probe": {first: {"measure": half},
                                                                             second: {"measure": good}}})
        self.assertEqual((reasons, [s["fits"] for s in det["sizes"]]), ([], [True]))
        reasons, det = _gate.measured_check(KITCHEN_PLAN, 0, code, {"probe": {first: {"measure": half},
                                                                             second: {"measure": half}}})
        self.assertEqual(reasons, ["size_mismatch"])
        self.assertEqual(len(det["faults"]), 1)
        # No measuring (the probes never ran): nothing measured to hold it to
        self.assertEqual(_gate.measured_check(KITCHEN_PLAN, 0, code, {"probe": {}}), ([], {}))
        out_code = verdict(KITCHEN_PLAN, 0, ISLAND_OUTPUT)["code"]
        reasons, det = _gate.measured_check(KITCHEN_PLAN, 0, out_code, {"probe": {}})
        self.assertEqual((reasons, det["output"]), (["output_not_asked"], ["//island.png"]))
        self.assertEqual(det["faults"], ['SETTINGS_s1["output"] sets "//island.png", but the step says nothing about '
                                         'saving, rendering or exporting: leave "output" out'])

    def test_hidden_errors_count_when_every_versions_report_shows_them(self):
        """Step 6a (datagen/silent.py) on hand-made reports: swallowed and skipped_input are measured faults that need
        every version's report watching (a version that printed none judges nothing), told with the rest; joined they
        go through the line map and are recorded only."""
        first, second = list(blenders.VERSIONS)
        plan = plan_of(("Render settings", "Set the render up.", ()))
        code = MARK + "\nimport bpy\n\nSETTINGS_s1 = {}\n\n\ndef build_s1(ctx):\n    im = ctx['scene'].render." \
            "image_settings\n    try:\n        im.file_format = 'FFMPEG'\n    except TypeError:\n        pass\n"
        line = line_of(code, "        im.file_format = 'FFMPEG'")
        e = {"type": "TypeError", "msg": 'bpy_struct: item.attr = val: enum "FFMPEG" not found in (\'PNG\')',
             "line": line, "origin": "<script>", "op": "STORE_ATTR", "handled": "build_s1", "meant": "'FFMPEG'",
             "landed": False}
        miss = {"line": line, "key": "Base_Color", "node": "ShaderNodeBsdfPrincipled", "node_name": "Principled BSDF",
                "ptr": 1, "side": "inputs", "close": ["Base Color"], "close_state": {"Base Color": "default"},
                "owner": "chimera_box_mat"}
        report = {"how": "monitoring", "cut": 0, "ev": [e], "miss": [miss], "attr_miss": [], "hit": []}
        run = {"probe": {first: {"silent": report}, second: {"silent": dict(report, how="settrace")}}}
        reasons, det = _gate.measured_check(plan, 0, code, run)
        self.assertEqual(reasons, ["swallowed", "skipped_input"])
        self.assertEqual(([f["line"] for f in det["silent"]["swallowed"]], det["silent"]["skipped"][0]["key"]),
                         ([line], "Base_Color"))
        self.assertEqual((det["silent"]["attr_miss"], det["silent"]["excused"]), ([], []))
        self.assertEqual(det["faults"], silent.tell(det["silent"]["swallowed"], det["silent"]["skipped"]))
        self.assertTrue(T.soft(reasons))  # Chimera passes such a piece: kept for the later steps, no example
        self.assertEqual(G._hard(reasons), [])  # ... so it still gets its joined check
        self.assertEqual(T._blender_stage(reasons), "alone")
        for half in ({first: {"silent": report}},
                     {first: {"silent": report}, second: {"silent": dict(report, how="none")}},
                     {first: {"silent": report}, second: {"measure": {"objects": []}}}):
            self.assertEqual(_gate.measured_check(plan, 0, code, {"probe": half}), ([], {}))
        clean = {"how": "monitoring", "cut": 0, "ev": [], "miss": [], "attr_miss": [], "hit": []}
        self.assertEqual(_gate.measured_check(plan, 0, code, {"probe": {first: {"silent": clean},
                                                                        second: {"silent": clean}}}),
                         ([], {"silent": {"swallowed": [], "skipped": [], "attr_miss": [], "excused": []}}))
        # joined: the joined script's line 20 is this piece's line, through the line map; recorded, never a reason
        lm = {"origins": [None] * 19 + [["s1", "build", "build_s1", line]]}
        jrun = {"probe": {v: {"silent": dict(report, ev=[dict(e, line=20)], miss=[])} for v in blenders.VERSIONS}}
        reasons, det = _gate.measured_check(plan, 0, code, jrun, joined={"s1"}, codes={}, linemap=lm)
        self.assertEqual(reasons, [])
        self.assertEqual([f["line"] for f in det["joined_silent"]["swallowed"]], [line])
        self.assertNotIn("faults", det)
        self.assertNotIn("joined_silent", _gate.measured_check(plan, 0, code, jrun, joined={"s1"}, codes={})[1])

    def test_geometry_counts_when_every_versions_geometry_line_shows_it(self):
        """Step 6b (datagen/geometry.py) on hand-made geometry lines: place_mismatch and flat_extrusion are the alone
        run's soft measured faults, needing every version's geometry line and measuring and the fault in each, told
        with the rest; a relation is the joined run's (a variant's: its alone run's), recorded only this round since
        its reader failed the held-out check (geometry.GATED), with the run's stand-ins skipped."""
        first, second = list(blenders.VERSIONS)
        plan = plan_of(("Sign", 'Add a sign named "chimera_sign" at (1, 0, 0). Extrude the curve named "chimera_wave" '
                                'by 0.08 m. Add a plate named "chimera_plate" behind the sign.', ()))
        code = MARK + "\nimport bpy\n"
        sign = {"n": "chimera_sign", "t": "MESH", "loc": [0.0, 0.0, 0.0], "lo": [-0.5, -0.1, 0.0],
                "hi": [0.5, 0.1, 1.0], "verts": 8, "faces": 6, "mats": 0}
        wave = {"n": "chimera_wave", "t": "CURVE", "loc": [0.0, 0.0, 0.0], "lo": [0.0, 0.0, 0.0], "hi": [2.0, 0.7, 0.0],
                "verts": 13, "faces": 0, "mats": 0}
        plate = {"n": "chimera_plate", "t": "MESH", "loc": [0.0, 0.0, 0.5], "lo": [-0.4, 0.0, 0.1],
                 "hi": [0.4, 0.0, 0.9], "verts": 4, "faces": 1, "mats": 0}
        rec = {"geom": {"v": 1, "objects": [sign, wave, plate]}, "measure": {"v": 1, "objects": []}}
        run = {"probe": {v: rec for v in blenders.VERSIONS}}
        reasons, det = _gate.measured_check(plan, 0, code, run)
        self.assertEqual(reasons, ["place_mismatch", "flat_extrusion"])
        self.assertEqual([r["fits"] for r in det["places"]], [False])
        self.assertEqual(det["depths"][0]["fault"], "the step asks for a depth of 0.08 m, but chimera_wave has 0 faces "
                                                    "and is 0 m at its thinnest")
        self.assertNotIn("relations", det)  # a relation is the joined run's
        self.assertEqual(det["faults"], [det["places"][0]["fault"], det["depths"][0]["fault"]])
        self.assertTrue(T.soft(reasons))  # Chimera passes such a piece: kept for the later steps, no example
        self.assertEqual(G._hard(reasons), [])  # ... so it still gets its joined check
        self.assertEqual(T._blender_stage(reasons), "alone")
        # a fault in one version only, or a version without its geometry line, its measuring, or one that failed
        moved = dict(rec, geom={"v": 1, "objects": [dict(sign, lo=[0.5, -0.1, 0.0], hi=[1.5, 0.1, 1.0]),
                                                     dict(wave, faces=30, lo=[0, 0, -0.04], hi=[2, 0.7, 0.04]), plate]})
        self.assertEqual(_gate.measured_check(plan, 0, code, {"probe": {first: rec, second: moved}})[0], [])
        for other in ({"measure": rec["measure"]}, {"geom": rec["geom"]}, dict(rec, geom={"v": 1, "failed": "x"})):
            self.assertEqual(_gate.measured_check(plan, 0, code, {"probe": {first: rec, second: other}}), ([], {}))
        # joined: the plate buried in the sign is found and recorded, never a reason this round
        reasons, det = _gate.measured_check(plan, 0, code, run, joined={"s1"}, codes={})
        self.assertEqual(reasons, [])
        self.assertEqual(det["relations"][0]["fits"], False)
        self.assertTrue(det["relations"][0]["fault"].startswith("the step puts the chimera_plate behind the sign, but "
                                                                "chimera_plate (box -0.4, 0, 0.1 to 0.4, 0, 0.9) lies"))
        self.assertNotIn("faults", det)
        self.assertNotIn("places", det)  # places and depths are the alone run's
        real = G.geometry.GATED
        G.geometry.GATED = real | {"nested"}  # were its reader gated, it would fail the piece joined
        try:
            reasons, det = _gate.measured_check(plan, 0, code, run, joined={"s1"}, codes={})
            self.assertEqual((reasons, det["faults"]), (["nested"], [det["relations"][0]["fault"]]))
            self.assertEqual(T._blender_stage(reasons), "joined")
            stood = {"probe": {v: dict(rec, stand_in_keys=["sign"]) for v in blenders.VERSIONS}}
            reasons, det = _gate.measured_check(plan, 0, code, stood, joined={"s1"}, codes={})
            self.assertEqual((reasons, det["relations"][0]["unmeasured"]), ([], "stand_in"))
        finally:
            G.geometry.GATED = real
        # an alone run that printed a stand-in (in any version) judges no place: a thing stood on its dependency's
        # object stands on the stand-in alone; the line it would have told is kept, and the depth is still judged
        for mark in ({"stand_in": True}, {"stand_in_keys": ["table_top"]}):
            stood = {"probe": {first: dict(rec, **mark), second: rec}}
            reasons, det = _gate.measured_check(plan, 0, code, stood)
            self.assertEqual(reasons, ["flat_extrusion"])
            self.assertEqual((det["places"][0]["fits"], det["places"][0]["unmeasured"]), (None, "stand_in"))
            self.assertTrue(det["places"][0]["stand_in_fault"].startswith("the step puts the chimera_sign at (1, 0, 0)"))
            self.assertNotIn("fault", det["places"][0])
        # ... and judged on the joined run instead (piece_check passes places=True), where the dependencies are real
        reasons, det = _gate.measured_check(plan, 0, code, run, joined={"s1"}, codes={}, places=True)
        self.assertEqual((reasons, [r["fits"] for r in det["joined_places"]]), (["place_mismatch"], [False]))
        self.assertEqual(det["faults"], [det["joined_places"][0]["fault"]])
        self.assertNotIn("joined_places", _gate.measured_check(plan, 0, code, run, joined={"s1"}, codes={})[1])
        stood = {"probe": {v: dict(rec, stand_in=True) for v in blenders.VERSIONS}}  # a dependency missing joined too
        reasons, det = _gate.measured_check(plan, 0, code, stood, joined={"s1"}, codes={}, places=True)
        self.assertEqual((reasons, det["joined_places"][0]["unmeasured"]), ([], "stand_in"))
        # a piece that won't be joined (a variant) has its relations judged on its alone run
        reasons, det = _gate.measured_check(plan, 0, code, run, unjoined=True)
        self.assertEqual((reasons, [r["fits"] for r in det["relations"]]), (["place_mismatch", "flat_extrusion"],
                                                                            [False]))

    def test_the_scene_a_judge_sees_says_what_is_the_factorys(self):
        rec = {"scene": {"objects": [{"name": "Cube", "type": "MESH", "data": "Cube"},
                                     {"name": "chimera_box", "type": "MESH", "data": "chimera_box"}],
                         "materials": ["Material"], "collections": [], "world": "World", "engine": "BLENDER_EEVEE"},
               "ctx_live": ["box"],
               "measure": {"objects": FACTORY_ROWS + [row("chimera_box", size=[1.0, 1.0, 1.0], loc=[0.0, 0.0, 0.5])],
                           "groups": [], "node_groups": [], "actions": []}}
        s = G._scene(rec)
        self.assertEqual(s["engine"], "BLENDER_EEVEE (the factory default: the listing can't tell whether the piece "
                                      "set it)")
        self.assertEqual(s["engine"], G.ENGINE_UNCHANGED)
        # The piece's own code assigning an engine (the smoke's EEVEE step, from its settings too)
        for code in ("import bpy\nbpy.context.scene.render.engine = 'BLENDER_EEVEE'\n",
                     "import bpy\nr = bpy.context.scene.render\nr.engine = SETTINGS_s5['render_engine']\n",
                     "import bpy\nsetattr(bpy.context.scene.render, 'engine', 'BLENDER_EEVEE')\n"):
            self.assertEqual(G._scene(rec, MARK + "\n" + code)["engine"], "BLENDER_EEVEE (set by the piece)", code)
        for code in (None, MARK + "\nimport bpy\nprint(bpy.context.scene.render.engine)\n",
                     MARK + "\ndef broken(:\n    x.engin = 1\n"):
            self.assertEqual(G._scene(rec, code)["engine"], G.ENGINE_UNCHANGED, code)
        self.assertEqual(s["world"], "World (factory world; its settings may have been changed)")
        self.assertEqual(s["sizes"], {"chimera_box": [1.0, 1.0, 1.0]})
        self.assertEqual(s["locations"], {"chimera_box": {"origin": [0.0, 0.0, 0.5]}})  # no geometry line: the origin
        for k in ("modifiers", "animated", "lights", "cameras", "node_groups", "actions"):
            self.assertNotIn(k, s)  # only when there is something
        rec["scene"].update(world="chimera_sky", engine="CYCLES")
        self.assertEqual((G._scene(rec)["world"], G._scene(rec)["engine"]), ("chimera_sky", "CYCLES"))
        rec["scene"]["world"] = None
        self.assertEqual(G._scene(rec)["world"], "none")
        del rec["measure"]
        self.assertEqual(set(G._scene(rec)), {"objects", "materials", "collections", "ctx_keys", "world", "engine"})
        # the ctx["values"] keys a piece handed on, only when there are some: a listing without them is as before
        self.assertNotIn("ctx_values", G._scene(dict(rec, ctx_values=[])))
        self.assertEqual(G._scene(dict(rec, ctx_values=["sofa_depth", "sofa_width"]))["ctx_values"],
                         ["sofa_depth", "sofa_width"])

    def test_a_location_says_where_the_geometry_is_beside_the_origin(self):
        """K (Nov 5): smoke4's n-blender-0000-00 r1 s2 applied its cubes' transforms, so every origin was (0, 0, 0)
        while each box was where its step puts it, and the scene judge failed it for "all placed at the origin". The
        listing labels a location: the centre of the geometry's world box and the middle of its bottom (the geometry
        line's, GEOM_EPILOGUE), then the origin; an object the geometry line has no box for (a light, a cut name that
        isn't the one box's, a run from before RUN_FORMAT 5) gives its origin alone."""
        long_name = "chimera_" + "x" * 50  # 58 characters: the measuring writes 45 and "...", the geometry line 58
        rows = [row("chimera_fridge", size=[0.8, 0.7, 1.8]), row("chimera_sun", "LIGHT", loc=[0.0, 0.0, 5.0]),
                row(long_name[:45] + "...", size=[1.0, 1.0, 1.0], loc=[3.0, 0.0, 0.0])]
        geom = {"v": 1, "objects": [{"n": "chimera_fridge", "t": "MESH", "loc": [0.0, 0.0, 0.0], "faces": 6,
                                     "lo": [0.8, -0.65, 0.0], "hi": [1.6, 0.05, 1.8]},
                                    {"n": long_name, "t": "MESH", "loc": [3.0, 0.0, 0.0], "faces": 6,
                                     "lo": [2.5, -0.5, -0.5], "hi": [3.5, 0.5, 0.5]},
                                    {"n": "Cube", "t": "MESH", "loc": [0.0, 0.0, 0.0], "faces": 6,
                                     "lo": [-1.0, -1.0, -1.0], "hi": [1.0, 1.0, 1.0]}]}
        got = G._listed({"objects": FACTORY_ROWS + rows}, geom)["locations"]
        self.assertEqual(got["chimera_fridge"], {"geometry_centre": [1.2, -0.3, 0.9],
                                                 "geometry_bottom": [1.2, -0.3, 0.0], "origin": [0.0, 0.0, 0.0]})
        self.assertEqual(list(got["chimera_fridge"]), [G.WHERE_CENTRE, G.WHERE_BOTTOM, G.WHERE_ORIGIN])
        self.assertEqual(got["chimera_sun"], {"origin": [0.0, 0.0, 5.0]})
        self.assertEqual(got[long_name[:45] + "..."]["geometry_centre"], [3.0, 0.0, 0.0])
        self.assertNotIn("Cube", got)  # the factory's, as before
        # no geometry line, or a failed one: origins alone
        for g in (None, {"v": 1, "failed": "RuntimeError " + MARK}):
            self.assertEqual(G._listed({"objects": rows}, g)["locations"]["chimera_fridge"],
                             {"origin": [0.0, 0.0, 0.0]})
        # a cut name two boxes start with is no one's
        twins = dict(geom, objects=geom["objects"] + [dict(geom["objects"][1], n=long_name + "2")])
        self.assertEqual(G._listed({"objects": rows}, twins)["locations"][long_name[:45] + "..."],
                         {"origin": [3.0, 0.0, 0.0]})
        # _scene reads the probe's own geometry line
        rec = {"scene": {"objects": [], "materials": [], "collections": [], "world": "World", "engine": "CYCLES"},
               "ctx_live": [], "measure": {"objects": rows}, "geom": geom}
        self.assertEqual(G._scene(rec)["locations"]["chimera_fridge"]["geometry_bottom"], [1.2, -0.3, 0.0])

    def test_a_handoff_may_name_the_values_it_put_in_ctx_values(self):
        """_have counts a run's ctx["values"] keys with its live ctx["objects"] keys and names, and provided_names
        (runner.score, K5) leaves the channel's name out, so a values step's provides line is all found."""
        from runner.score import provided_names
        self.assertIn("provides: " + VALUES_PROVIDES + "\n", CF.VALUES_S1)
        named = provided_names(VALUES_PROVIDES)
        self.assertEqual(named, ["sofa_width", "sofa_depth"])
        rec = {"ids": ["Camera", "Cube", "Light"], "ctx_live": [], "ctx_values": ["sofa_depth", "sofa_width"]}
        self.assertEqual([n for n in named if n not in G._have(rec)], [])
        # a record from before Nov 4 (no ctx_values) misses them, as the gate did
        old = {k: v for k, v in rec.items() if k != "ctx_values"}
        self.assertEqual([n for n in named if n not in G._have(old)], named)
        self.assertIsNone(G._have({"ctx_values": ["sofa_width"]}))  # no names: the probes never ran

    def test_the_listing_shows_a_size_before_modifiers_and_what_it_leaves_out(self):
        rows = [row("chimera_room", size=[0.0, 0.0, 0.0], mods=["NODES"], base=[20.0, 3.0, 4.0]),
                row("chimera_crate", size=[1.0, 1.0, 1.0], mods=["BEVEL"])]  # a bevel leaves its size: no base
        got = G._listed({"objects": FACTORY_ROWS + rows, "node_groups": [["chimera_panels", "GeometryNodeTree"]]})
        self.assertEqual(got["sizes"], {"chimera_room": {"size": [0.0, 0.0, 0.0], "base_size": [20.0, 3.0, 4.0]},
                                        "chimera_crate": [1.0, 1.0, 1.0]})
        self.assertEqual(got["modifiers"], {"chimera_room": ["NODES"], "chimera_crate": ["BEVEL"]})
        self.assertNotIn("...", got["locations"])  # nothing left out, no note
        # Over LISTING_KEEP: the field says how many it leaves out, a dict by its "..." key, a list by its last item
        many = [row("chimera_p%02d" % k, size=[1.0, 1.0, 1.0], anim=1) for k in range(G.LISTING_KEEP + 5)]
        got = G._listed({"objects": many})
        self.assertEqual(len(got["sizes"]), G.LISTING_KEEP + 1)
        self.assertEqual(got["sizes"]["..."], "(5 more not listed)")
        self.assertEqual(got["animated"][-1], "(5 more not listed)")
        # The measuring's own cut: objects it left out count on every per-object field, a field's own on its own
        got = G._listed({"objects": rows, "node_groups": [], "actions": [["chimera_a", "OBJECT", 1, 24]],
                         "cut": {"objects": 3, "node_groups": 2, "actions": 1}})
        self.assertEqual((got["sizes"]["..."], got["locations"]["..."]), ("(3 more not listed)",) * 2)
        self.assertEqual(got["node_groups"], {"...": "(2 more not listed)"})  # all cut, still said
        self.assertEqual(got["actions"]["..."], "(1 more not listed)")
        self.assertNotIn("lights", got)  # none measured: nothing to say of a field it never had

    def test_tell_lines_say_why_a_piece_failed(self):
        self.assertEqual(G.tell_lines({"ok": True, "reasons": []}), [])
        first = next(iter(blenders.VERSIONS))
        out = {"ok": False, "reasons": ["alone_strict:" + first, "provides_missing", "stand_in"], "crash": None,
               "alone": {first: {"error": "RuntimeError: Error in Blender %s: no such thing" % first}},
               "provides_missing": ["chimera_box", "box"], "stand_in_keys": ["floor"],
               "measured": {"faults": ["no object measures 2 × 1 × 1 m; the nearest is chimera_box at "
                                       "1 × 1 × 1 m"]}}
        lines = G.tell_lines(out)
        self.assertEqual(lines[0], "run alone, it failed: RuntimeError: Error in the newer Blender: no such thing")
        self.assertEqual(lines[1], "the handoff's provides names chimera_box, box, but the run made nothing by those "
                                   "names (no object, material, collection, node group, ctx[\"objects\"] or "
                                   "ctx[\"values\"] key)")
        # a dependency's missing value gets the marker too since Nov 4: only a missing file gets none
        self.assertEqual(lines[2], "joined, it printed the stand-in line (floor) where no stand-in is due: that line "
                                   "is only for a dependency's ctx[\"objects\"] or ctx[\"values\"] key that is "
                                   "missing; a missing file gets a fallback without it")
        self.assertEqual(lines[3], out["measured"]["faults"][0])
        self.assertFalse(any(v in l for l in lines for v in blenders.VERSIONS))  # the notes never name a version
        # A crash in the piece goes to the notes as it is: no line repeats it
        self.assertEqual(G.tell_lines(dict(out, reasons=["alone_strict:" + first], crash={"error": "x"}, measured={})),
                         [])
        # ctx_tell's line is told whatever else failed (a crash too), after the reasons' lines, before the measured
        tell = G.ctx_tell("s2", [], ["settings"])
        self.assertEqual(G.tell_lines(dict(out, reasons=["alone_strict:" + first], crash={"error": "x"}, measured={},
                                           ctx_tell=tell)), [tell])
        self.assertEqual(G.tell_lines(dict(out, reasons=["output_missing", "ctx_channel"], ctx_tell=tell)),
                         [tell, out["measured"]["faults"][0]])
        self.assertEqual(G.tell_lines(dict(out, ok=True, ctx_tell=tell)), [])


class SchedulingTests(unittest.TestCase):
    """The semaphore, one run per script at a time, and what isn't cached: with stand-in runs, no Blender."""

    def fake(self, jobs, fail_check=False):
        g = make_gate(os.path.join(tempfile.mkdtemp(dir=_tmp), "runs.jsonl"), jobs=jobs)
        state = {"now": 0, "most": 0, "direct": 0, "lock": threading.Lock()}

        def busy():
            with state["lock"]:
                state["now"] += 1
                state["most"] = max(state["most"], state["now"])
            time.sleep(0.05)
            with state["lock"]:
                state["now"] -= 1

        def check_result(path, *, goal=None, work_dir, blender=None, timeout=None):
            busy()
            if fail_check:
                raise C.ChimeraError("chimera --check-result: no verdict (a stand-in) " + MARK)
            v = next(k for k, b in blenders.VERSIONS.items() if b == blender)
            return {"check": {"outcome": "passed", "runner": "Blender " + v, "output": ""}, "critique": "", "exit": 0,
                    "stated": "Blender " + v}

        def direct(script, binary, version):
            busy()
            with state["lock"]:
                state["direct"] += 1
            return {"exit": 0, "strict_full": True, "bad_lines": [], "version_ok": True, "ids": [], "dupes": []}
        g.chimera.check_result = check_result
        g.blender.ch = g.chimera
        g.blender._direct = direct
        return g, state

    def test_at_most_jobs_blender_processes_and_one_run_per_script(self):
        g, state = self.fake(jobs=2)
        scripts = ["# %d %s\nimport bpy\n" % (k, MARK) for k in range(3)] + ["# same %s\nimport bpy\n" % MARK] * 4
        threads = [threading.Thread(target=g.run, args=(s,)) for s in scripts]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(state["most"], 2)
        self.assertEqual(state["direct"], 4 * len(blenders.VERSIONS))  # the same script four times: run once
        self.assertEqual(g.stats()["runs"], 4)
        self.assertEqual(g.stats()["cached"], 3)
        self.assertEqual(len(g.cache), 4)

    def test_a_run_whose_check_could_not_be_done_is_not_cached(self):
        g, state = self.fake(jobs=4, fail_check=True)
        script = "# no verdict %s\nimport bpy\n" % MARK
        r = g.run(script)
        self.assertFalse(r["cached"])
        self.assertIn("no verdict", r["check"]["5.2.2"]["problem"])
        self.assertFalse(blender_check_strict(r))
        g.run(script)
        self.assertEqual(g.stats()["runs"], 2)  # asked again: a resumed run would try it again too
        self.assertEqual(g.stats()["not_cached"], 2)
        self.assertEqual(len(g.cache), 0)


def blender_check_strict(run):
    return any(counted_strict(run["check"][v], run["probe"][v]) for v in blenders.VERSIONS)


class PassingPlanTests(unittest.TestCase):
    def test_a_floor_and_a_box_pass_alone_joined_and_as_a_plan(self):
        r1 = _gate.piece_check(PLAN, 0, FLOOR, verdict(PLAN, 0, FLOOR), {}, GOAL)
        self.assertTrue(r1["ok"], r1["reasons"])
        self.assertEqual(set(r1["alone"]), set(blenders.VERSIONS))
        self.assertTrue(all(x["strict"] for x in r1["alone"].values()))
        self.assertTrue(all(x["strict"] for x in r1["joined"].values()))
        self.assertIsNone(r1["crash"])
        # The scene a judge sees: what the piece made, without the factory cube, camera and light
        self.assertEqual(r1["scene"]["objects"], [["chimera_floor", "MESH"]])
        self.assertEqual(r1["scene"]["materials"], ["chimera_floor_mat"])
        self.assertEqual(r1["scene"]["ctx_keys"], ["floor"])
        r2 = _gate.piece_check(PLAN, 1, BOX, verdict(PLAN, 1, BOX), {"s1": FLOOR}, GOAL)
        self.assertTrue(r2["ok"], r2["reasons"])
        self.assertTrue(all(x["stand_in"] for x in r2["alone"].values()))  # alone, s2 makes its stand-in
        self.assertFalse(r2["stand_in"])  # joined after s1, it doesn't
        self.assertEqual(sorted(r2["joined"]["5.2.2"]["ctx_keys"]), ["box", "floor"])
        self.assertEqual(r2["provides_missing"], [])
        p = _gate.plan_check(PLAN, {"s1": FLOOR, "s2": BOX}, GOAL)
        self.assertTrue(p["ok"], p["reasons"])
        self.assertEqual(p["provides_lost"], [])
        self.assertIsNone(p["culprit"])
        self.assertEqual(p["runs"]["joined"], r2["runs"]["joined"])  # the same joined script: one run
        self.assertIn(p["scene_outcome"], ("passed", "wrong_scene", "unsure"))  # recorded, not gated on
        self.assertEqual(p["scene_check"]["runner"], "Blender " + next(iter(blenders.VERSIONS)))

    def test_a_second_identical_check_runs_no_blender(self):
        args = (PLAN, 1, BOX, verdict(PLAN, 1, BOX), {"s1": FLOOR}, GOAL)
        first = _gate.piece_check(*args)
        before = _gate.stats()
        again = _gate.piece_check(*args)
        after = _gate.stats()
        self.assertEqual(after["processes"], before["processes"])
        self.assertEqual(after["runs"], before["runs"])
        self.assertEqual(after["cached"], before["cached"] + 2)  # alone and joined
        self.assertEqual({k: v for k, v in again.items() if k != "seconds"},
                         {k: v for k, v in first.items() if k != "seconds"})
        # A resumed run: a new gate on the same cache file replays the verdicts without Blender
        fresh = make_gate(_gate.cache.path)
        self.assertEqual(fresh.piece_check(*args)["reasons"], first["reasons"])
        self.assertEqual(fresh.stats()["processes"], 0)
        with open(_gate.cache.path, encoding="utf-8") as f:
            keys = [json.loads(l)["key"] for l in f if l.strip()]
        self.assertEqual(len(keys), len(set(keys)))  # each run written once


class FailingPieceTests(unittest.TestCase):
    def test_a_lint_error_fails_but_its_real_crash_is_found_for_a_repair(self):
        text = reply("s2", BOX_LINT_CODE, BOX_PROVIDES, BOX_USES)
        v = verdict(PLAN, 1, text)
        r = _gate.piece_check(PLAN, 1, text, v, {"s1": FLOOR}, GOAL)
        self.assertFalse(r["ok"])
        self.assertIn("lint:socket", r["reasons"])
        self.assertTrue(any("Transmission" in x["message"] for x in r["lint"] if x["level"] == "error"))
        self.assertEqual(r["joined"], {})  # stopped before the join
        want = line_of(v["code"], LINT_LINE)
        self.assertEqual(r["crash"]["piece_line"], want)
        self.assertEqual((r["crash"]["step"], r["crash"]["part"], r["crash"]["function"]), ("s2", "build", "build_s2"))
        self.assertIn("KeyError", r["crash"]["error"])
        self.assertEqual(r["crash"]["source"], LINT_LINE.strip())
        # Without run_on_lint, a lint error runs no Blender at all
        g = make_gate(os.path.join(_tmp, "lint-only.jsonl"))
        r2 = g.piece_check(PLAN, 1, text, v, {"s1": FLOOR}, GOAL, run_on_lint=False)
        self.assertEqual(r2["reasons"], ["lint:socket"])
        self.assertIsNone(r2["crash"])
        self.assertEqual(g.stats()["processes"], 0)
        self.assertRepairNames(text, r["crash"], want, "build_s2", LINT_LINE.strip())

    def test_a_crash_in_its_build_function_alone_is_located_in_the_piece(self):
        text = reply("s2", BOX_CRASH_CODE, BOX_PROVIDES, BOX_USES)
        v = verdict(PLAN, 1, text)
        r = _gate.piece_check(PLAN, 1, text, v, {"s1": FLOOR}, GOAL)
        self.assertEqual(r["lint"], [])  # nothing a lint can see
        self.assertEqual(r["reasons"], ["alone_strict:" + x for x in blenders.VERSIONS])
        c = r["crash"]
        self.assertEqual((c["step"], c["part"], c["function"]), ("s2", "build", "build_s2"))
        self.assertEqual(c["piece_line"], line_of(v["code"], CRASH_LINE))
        self.assertEqual(c["line"], c["piece_line"])  # the alone script keeps the piece's own numbers
        self.assertIn("ValueError", c["error"])
        self.assertEqual(c["runner"], "Blender " + next(iter(blenders.VERSIONS)))
        self.assertRepairNames(text, c, c["piece_line"], "build_s2", CRASH_LINE.strip())

    def test_a_crash_only_when_joined_is_located_through_the_line_map(self):
        text = reply("s2", BOX_JOINED_CODE, BOX_PROVIDES, BOX_USES)
        v = verdict(PLAN, 1, text)
        r = _gate.piece_check(PLAN, 1, text, v, {"s1": FLOOR}, GOAL)
        self.assertTrue(all(x["strict"] for x in r["alone"].values()), r["alone"])
        self.assertEqual(r["reasons"], ["joined_strict:" + x for x in blenders.VERSIONS])
        c = r["crash"]
        want = line_of(v["code"], JOINED_LINE)
        self.assertEqual((c["step"], c["part"], c["function"], c["piece_line"]), ("s2", "build", "build_s2", want))
        self.assertNotEqual(c["line"], want)  # the joined script's own line is another
        self.assertIn('KeyError', c["error"])
        self.assertIn("chimera_top", c["error"])
        self.assertRepairNames(text, c, want, "build_s2", JOINED_LINE.strip())
        # The plan check names s2 from the same line map
        p = _gate.plan_check(PLAN, {"s1": FLOOR, "s2": text}, GOAL)
        self.assertFalse(p["ok"])
        self.assertEqual((p["culprit"], p["culprit_id"]), ("s2", "s2"))
        self.assertEqual(p["crash"]["piece_line"], want)

    def test_the_crash_comes_from_the_version_asked_for_first(self):
        # Both pieces crash in every version: the crash (and the Blender a repair names) is prefer's, so a repair
        # never pairs one Blender's names sheet with the other's crash.
        first, second = list(blenders.VERSIONS)
        for code, line, joined in ((BOX_CRASH_CODE, CRASH_LINE, False), (BOX_JOINED_CODE, JOINED_LINE, True)):
            text = reply("s2", code, BOX_PROVIDES, BOX_USES)
            v = verdict(PLAN, 1, text)
            want = line_of(v["code"], line)
            for prefer, runner in (("4.2.0", first), (None, first), (first, first), (second, second)):
                r = _gate.piece_check(PLAN, 1, text, v, {"s1": FLOOR}, GOAL, prefer=prefer)
                self.assertEqual(bool(r["joined"]), joined)
                c = r["crash"]
                self.assertEqual((c["step"], c["function"], c["piece_line"], c["runner"]),
                                 ("s2", "build_s2", want, "Blender " + runner), (code, prefer))
            self.assertRepairNames(text, c, want, "build_s2", line.strip())  # "… in Blender <second>:"

    def assertRepairNames(self, text, crash, line, function, source):
        """Chimera's own repair message is built from the crash, naming the piece's line and function."""
        req = chimera().worker_request(PLAN, 1, {"s1": FLOOR}, goal=GOAL, piece=text, crash=crash)
        user = req["messages"][1]["content"]
        self.assertIn(f"line {line} in {function}: {source}\n", user)
        self.assertIn(crash["error"], user)
        self.assertIn(f"in {crash['runner']}:", user)

    def test_a_handoff_that_provides_what_the_piece_never_makes(self):
        code = BOX_CODE.replace("chimera_box", "chimera_crate").replace('ctx["objects"]["box"]',
                                                                        'ctx["objects"]["crate"]')
        text = reply("s2", code, BOX_PROVIDES, BOX_USES)
        r = _gate.piece_check(PLAN, 1, text, verdict(PLAN, 1, text), {"s1": FLOOR}, GOAL)
        # ... and Chimera's own warning for the crate it registers instead, which the build drops (told since the
        # fourth smoke: build_facts)
        self.assertEqual(r["reasons"], ["provides_missing", "validator_warning:provides_missing"])
        self.assertEqual(r["provides_missing"], ["chimera_box", "box"])
        self.assertEqual(r["joined"], {})

    def test_a_stand_in_fails_when_its_dependency_is_there_and_is_allowed_when_it_was_dropped(self):
        wrong = reply("s2", BOX_WRONG_KEY_CODE, BOX_PROVIDES, BOX_USES)
        r = _gate.piece_check(PLAN, 1, wrong, verdict(PLAN, 1, wrong), {"s1": FLOOR}, GOAL)
        self.assertEqual(r["reasons"], ["stand_in"])
        self.assertTrue(r["stand_in"])
        self.assertFalse(r["stand_in_allowed"])
        dropped = _gate.piece_check(PLAN, 1, BOX, verdict(PLAN, 1, BOX), {}, GOAL)  # s1 was dropped
        self.assertTrue(dropped["ok"], dropped["reasons"])
        self.assertTrue(dropped["stand_in"])
        self.assertEqual(dropped["stand_in_keys"], ["floor"])
        self.assertTrue(dropped["stand_in_allowed"])
        p = _gate.plan_check(PLAN, {"s2": BOX}, GOAL)  # the plan check allows it too: a step was dropped
        self.assertTrue(p["ok"], p["reasons"])
        p = _gate.plan_check(PLAN, {"s1": FLOOR, "s2": wrong}, GOAL)
        self.assertEqual(p["reasons"], ["stand_in"])
        self.assertIsNone(p["culprit"])

    def test_a_stand_in_written_with_a_non_ascii_hyphen_is_seen(self):
        # gpt-oss writes the marker with U+2011 for its hyphen: the same rules hold as for the plain one
        wrong = reply("s2", BOX_WRONG_KEY_NB_CODE, BOX_PROVIDES, BOX_USES)
        r = _gate.piece_check(PLAN, 1, wrong, verdict(PLAN, 1, wrong), {"s1": FLOOR}, GOAL)
        self.assertEqual(r["reasons"], ["stand_in"])
        self.assertEqual(r["stand_in_keys"], ["floor"])
        self.assertTrue(all(x["stand_in"] for x in r["alone"].values()))
        self.assertIn("stand-in line (floor)", r["tell"][0])
        p = _gate.plan_check(PLAN, {"s1": FLOOR, "s2": wrong}, GOAL)
        self.assertEqual((p["reasons"], p["stand_in_keys"]), (["stand_in"], ["floor"]))

    def test_a_stand_in_for_what_a_present_step_provides_fails_though_another_dependency_was_dropped(self):
        # s1 (the rug) was dropped: s2's stand-in for it is allowed, and so is every join after s2 that prints it.
        floor = _gate.piece_check(ROOM_PLAN, 1, FLOOR_ON_RUG, verdict(ROOM_PLAN, 1, FLOOR_ON_RUG), {}, GOAL)
        self.assertTrue(floor["ok"], floor["reasons"])
        self.assertEqual((floor["stand_in_keys"], floor["stand_in_allowed"]), (["rug"], True))
        box = _gate.piece_check(ROOM_PLAN, 2, BOX3, verdict(ROOM_PLAN, 2, BOX3), {"s2": FLOOR_ON_RUG}, GOAL)
        self.assertTrue(box["ok"], box["reasons"])
        self.assertEqual((box["stand_in_keys"], box["stand_in_allowed"]), (["rug"], True))  # s2's, joined
        # s3 finds nothing where s2's floor is and makes a stand-in for it, though s2 is there
        wrong = _gate.piece_check(ROOM_PLAN, 2, BOX3_WRONG_KEY, verdict(ROOM_PLAN, 2, BOX3_WRONG_KEY),
                                  {"s2": FLOOR_ON_RUG}, GOAL)
        self.assertEqual(wrong["reasons"], ["stand_in"])
        self.assertEqual((wrong["stand_in_keys"], wrong["stand_in_allowed"]), (["rug", "floor"], False))
        p = _gate.plan_check(ROOM_PLAN, {"s2": FLOOR_ON_RUG, "s3": BOX3_WRONG_KEY}, GOAL)
        self.assertEqual(p["reasons"], ["stand_in"])
        self.assertEqual(p["stand_in_keys"], ["rug", "floor"])
        p = _gate.plan_check(ROOM_PLAN, {"s2": FLOOR_ON_RUG, "s3": BOX3}, GOAL)
        self.assertTrue(p["ok"], p["reasons"])


class PlanCheckTests(unittest.TestCase):
    def test_a_later_step_deleting_an_earlier_steps_object_loses_its_provides(self):
        rug = reply("s2", RUG_CODE, 'chimera_rug as ctx["objects"]["rug"]', BOX_USES)
        r = _gate.piece_check(RUG_PLAN, 1, rug, verdict(RUG_PLAN, 1, rug), {"s1": FLOOR}, GOAL)
        self.assertTrue(all(x["strict"] for x in r["joined"].values()), r["joined"])  # it runs, joined too
        self.assertEqual(r["joined"]["5.2.2"]["ctx_dead"], ["floor"])
        # ... but s1's floor is gone after it: the piece fails on its own, before it can sink the plan
        self.assertEqual(r["reasons"], ["removes_earlier"])
        self.assertEqual(r["removed"], ["s1"])
        self.assertIsNone(r["crash"])
        p = _gate.plan_check(RUG_PLAN, {"s1": FLOOR, "s2": rug}, GOAL)
        self.assertFalse(p["ok"])
        self.assertEqual(p["reasons"], ["provides_lost"])
        self.assertEqual(p["provides_lost"], ["s1"])
        self.assertIsNone(p["culprit"])  # which step removed it can't be told

    def test_absolute_output_paths_are_saved_in_the_run_folder(self):
        # The contract puts a path from the task in SETTINGS_sN["output"]; the sandbox refuses a save or a render
        # path outside the run folder, which isn't the piece's fault, so the joined runs put them in wm_out/.
        floor = FLOOR.replace('"color": (0.35, 0.22, 0.12, 1.0)}',
                              '"color": (0.35, 0.22, 0.12, 1.0), "output": {"blend": "%s/room.blend", '
                              '"render": "%s/renders/room.png", "resolution": [64, 48]}}' % (OUTSIDE, OUTSIDE))
        r = _gate.piece_check(OUTPUT_PLAN, 0, floor, verdict(OUTPUT_PLAN, 0, floor), {}, GOAL)
        self.assertTrue(r["ok"], r["reasons"])
        p = _gate.plan_check(OUTPUT_PLAN, {"s1": floor, "s2": BOX}, GOAL)
        self.assertTrue(p["ok"], p["reasons"])
        self.assertEqual(sorted(p["joined"]["5.0.1"]["ctx_keys"]), ["box", "floor"])  # probed after the save
        self.assertFalse(os.path.exists(OUTSIDE))
        # The same piece for a step that asks for no save or render sets an output nobody wants: it fails alone
        r = _gate.piece_check(PLAN, 0, floor, verdict(PLAN, 0, floor), {}, GOAL)
        self.assertEqual((r["reasons"], r["joined"], r["crash"]), (["output_not_asked"], {}, None))
        self.assertEqual(r["measured"]["output"], [OUTSIDE + "/room.blend", OUTSIDE + "/renders/room.png"])
        self.assertTrue(r["tell"][0].startswith('SETTINGS_s1["output"] sets "%s/room.blend", ' % OUTSIDE), r["tell"])

    def test_a_plan_that_renders_is_still_probed_at_its_end(self):
        # Chimera's _chimera_output renders, and a render ends a check: without its render skipped, the probes
        # would never run and nothing provided could be checked (no_probe).
        floor = FLOOR.replace('"color": (0.35, 0.22, 0.12, 1.0)}',
                              '"color": (0.35, 0.22, 0.12, 1.0), "output": {"render": "room.png", '
                              '"resolution": [64, 48]}}')
        p = _gate.plan_check(PLAN, {"s1": floor, "s2": BOX}, GOAL)
        self.assertTrue(p["ok"], p["reasons"])
        self.assertEqual(sorted(p["joined"]["5.0.1"]["ctx_keys"]), ["box", "floor"])
        self.assertEqual(p["scene_check"]["runner"], "Blender " + next(iter(blenders.VERSIONS)))


class MeasuredCheckTests(unittest.TestCase):
    """The measured checks in real Blender: what the alone run measured against the numbers the step gives."""

    def test_an_island_of_the_size_asked_passes_and_a_half_size_one_fails_alone(self):
        r = _gate.piece_check(KITCHEN_PLAN, 0, ISLAND, verdict(KITCHEN_PLAN, 0, ISLAND), {}, GOAL)
        self.assertTrue(r["ok"], r["reasons"])
        self.assertEqual(r["tell"], [])
        self.assertEqual(r["scene"]["sizes"], {"chimera_island": [2.4, 0.9, 0.92]})
        self.assertEqual([s["fits"] for s in r["measured"]["sizes"]], [True])
        turned = _gate.piece_check(KITCHEN_PLAN, 0, ISLAND_TURNED, verdict(KITCHEN_PLAN, 0, ISLAND_TURNED), {}, GOAL)
        self.assertTrue(turned["ok"], turned["reasons"])  # turned a quarter: its sides are still the ones asked
        half = _gate.piece_check(KITCHEN_PLAN, 0, ISLAND_HALF, verdict(KITCHEN_PLAN, 0, ISLAND_HALF), {}, GOAL)
        self.assertEqual(half["reasons"], ["size_mismatch"])
        self.assertEqual(T._blender_stage(half["reasons"]), "alone")  # where task.py says it stopped
        self.assertEqual((half["joined"], half["crash"]), ({}, None))  # stopped before the join; nothing to repair
        self.assertTrue(all(x["strict"] for x in half["alone"].values()))
        self.assertEqual(half["tell"], ["no object measures 2.4 × 0.9 × 0.92 m for the kitchen island (its size from "
                                        "the step); the nearest is chimera_island at 1.2 × 0.45 × 0.46 m, half the "
                                        "size asked on every side"])
        out = _gate.piece_check(KITCHEN_PLAN, 0, ISLAND_OUTPUT, verdict(KITCHEN_PLAN, 0, ISLAND_OUTPUT), {}, GOAL)
        self.assertEqual(out["reasons"], ["output_not_asked"])

    def test_sizes_from_a_values_step_are_held_to_the_joined_run(self):
        def check(text, earlier, **kw):
            return _gate.piece_check(BENCH_PLAN, 1, text, verdict(BENCH_PLAN, 1, text), earlier, GOAL, **kw)
        r = check(BENCH, {"s1": VALUES})
        self.assertTrue(r["ok"], (r["reasons"], r["tell"]))
        self.assertNotIn("sizes", r["measured"])  # alone it measured its fallback, which isn't held to s1's values
        self.assertEqual([(a["source"], a["fits"]) for a in r["measured"]["joined_sizes"]], [("s1", True)])
        half = check(BENCH_HALF, {"s1": VALUES})
        self.assertEqual(half["reasons"], ["size_mismatch"])
        self.assertEqual(half["stage"], "joined")  # what task.py records, not _blender_stage's "alone"
        self.assertTrue(all(x["strict"] for x in half["joined"].values()))
        self.assertEqual(half["tell"], ["no object measures 1.8 × 0.45 × 0.5 m for the bench (its size from s1); the "
                                        "nearest is chimera_bench at 0.9 × 0.22 × 0.25 m, half the size asked on "
                                        "every side"])
        # A variant is checked alone only, and with s1 dropped from the join there are no values to hold it to
        self.assertTrue(check(BENCH_HALF, {}, joined=False)["ok"])
        dropped = check(BENCH_HALF, {})
        self.assertTrue(dropped["ok"], dropped["reasons"])
        self.assertNotIn("joined_sizes", dropped["measured"])

    def test_a_values_size_the_join_cannot_judge_fails_no_piece(self):
        """r2-blender-0 in real Blender: the joined measure cut before the bench, and a values piece whose numbers
        aren't its words, leave a right bench unjudged instead of failing it; and a bench that writes the words in
        is no better than one that reads s1's values."""
        def check(text, earlier):
            return _gate.piece_check(ARCADE_PLAN, 2, text, verdict(ARCADE_PLAN, 2, text), earlier, GOAL)
        self.assertNotEqual(BENCH3_WORDS, BENCH3)
        r = check(BENCH3, {"s1": VALUES, "s2": POSTS})
        self.assertTrue(r["ok"], (r["reasons"], r["tell"]))
        run = _gate._cached(r["runs"]["joined"], lambda: None)
        for v, probe in run["probe"].items():
            names = [o["n"] for o in probe["measure"]["objects"]]
            self.assertNotIn("chimera_bench", names, v)
            self.assertTrue(probe["measure"]["cut"]["objects"], v)
        self.assertEqual([(a["fits"], a["unmeasured"]) for a in r["measured"]["joined_sizes"]], [(None, "cut")])
        for text in (BENCH3, BENCH3_WORDS):
            r = check(text, {"s1": VALUES_OTHER})
            self.assertTrue(r["ok"], (r["reasons"], r["tell"]))
            got, = r["measured"]["joined_sizes"]
            self.assertEqual((got["fits"], got["unmeasured"], got["piece_sides"]),
                             (None, "other_values", [2.4, 0.45, 0.5]))
        # With s1's piece setting its words' values, the one that writes them in passes as the reader does
        self.assertTrue(check(BENCH3_WORDS, {"s1": VALUES})["ok"])

    def test_a_ceiling_light_has_to_point_down_in_the_evaluated_scene(self):
        def check(text):
            return _gate.piece_check(KITCHEN_PLAN, 1, text, verdict(KITCHEN_PLAN, 1, text), {"s1": ISLAND}, GOAL)
        r = check(LIGHT)
        self.assertTrue(r["ok"], r["reasons"])
        self.assertEqual(r["scene"]["lights"], {"chimera_ceiling_light": {"type": "AREA", "power": 800.0,
                                                                          "emits_along": [0.0, 0.0, -1.0]}})
        up = check(LIGHT_UP)
        self.assertEqual(up["reasons"], ["aim_mismatch"])
        self.assertEqual(up["tell"], ["the step says the ceiling area light points down, but chimera_ceiling_light "
                                      "emits along (0, 0, 1), upward"])
        # Turned over as well, but a Track To constraint aims it at the island: the constraint is what counts
        tracked = check(LIGHT_TRACKED)
        self.assertTrue(tracked["ok"], tracked["reasons"])
        self.assertEqual(tracked["scene"]["lights"]["chimera_ceiling_light"]["emits_along"], [0.0, 0.0, -1.0])

    def test_the_scene_a_judge_sees_where_an_applied_transform_left_the_geometry(self):
        """Real Blender, both versions: transform_apply leaves the fridge's origin at (0, 0, 0) and its geometry at
        the step's point, which place_mismatch measures by its bottom, and the listing says both, labelled."""
        r = _gate.piece_check(APPLIED_PLAN, 0, APPLIED, verdict(APPLIED_PLAN, 0, APPLIED), {}, GOAL)
        self.assertTrue(r["ok"], r["reasons"])
        self.assertEqual([p["fits"] for p in r["measured"]["places"]], [True])
        self.assertEqual(r["scene"]["locations"]["chimera_fridge"], {"geometry_centre": [1.2, -0.3, 0.9],
                                                                     "geometry_bottom": [1.2, -0.3, 0.0],
                                                                     "origin": [0.0, 0.0, 0.0]})
        self.assertEqual(r["scene"]["sizes"]["chimera_fridge"], [0.8, 0.7, 1.8])

    def test_the_scene_a_judge_sees_lists_what_the_measuring_found(self):
        r = _gate.piece_check(SHOW_PLAN, 0, SHOW, verdict(SHOW_PLAN, 0, SHOW), {}, GOAL)
        self.assertTrue(r["ok"], r["reasons"])
        s = r["scene"]
        self.assertEqual((s["engine"], s["world"]), (G.ENGINE_UNCHANGED, G.WORLD_UNCHANGED))
        self.assertEqual(s["sizes"], {"chimera_crate": [1.0, 1.0, 1.0]})
        self.assertEqual(s["locations"]["chimera_crate"], {"geometry_centre": [1.0, 2.0, 0.5], "geometry_bottom":
                                                          [1.0, 2.0, 0.0], "origin": [1.0, 2.0, 0.0]})  # at frame 1,
        # where its animation starts
        self.assertEqual(s["locations"]["chimera_sun"], {"origin": s["locations"]["chimera_sun"]["origin"]})
        self.assertEqual(s["modifiers"], {"chimera_crate": ["BEVEL"]})
        self.assertEqual(s["animated"], ["chimera_crate"])
        self.assertEqual(s["actions"], {"chimera_crateAction": "OBJECT, frames 1-24"})
        self.assertEqual(s["cameras"], {"chimera_cam": {"lens": 35.0, "looks_along": [0.0, 0.0, -1.0]}})
        self.assertEqual(s["lights"]["chimera_sun"], {"type": "SUN", "power": 3.0, "emits_along": [0.0, 0.0, -1.0]})
        self.assertEqual(set(s["lights"]["chimera_bulb"]), {"type", "power"})  # a point light has no direction
        self.assertEqual(s["node_groups"], {"chimera_scatter": "GeometryNodeTree"})
        self.assertNotIn("Cube", s["sizes"])  # the factory's untouched objects aren't listed

    def test_the_listing_says_the_piece_set_the_engine_and_a_size_before_its_modifier(self):
        r = _gate.piece_check(WELD_PLAN, 0, WELD, verdict(WELD_PLAN, 0, WELD), {}, GOAL)
        self.assertTrue(r["ok"], r["reasons"])
        s = r["scene"]
        self.assertEqual(s["engine"], G.ENGINE_SET)
        self.assertEqual(s["sizes"], {"chimera_weld": {"size": [0.0, 0.0, 0.0], "base_size": [2.0, 1.0, 1.0]}})
        self.assertEqual(s["modifiers"], {"chimera_weld": ["WELD"]})


class CameraAndOutputTests(unittest.TestCase):
    """The scene's camera the measuring records, and the checks that read it or the piece's output, in real
    Blender."""

    def test_the_measuring_records_the_camera_a_render_uses(self):
        first, second = list(blenders.VERSIONS)
        script = MARK + "\nimport bpy\n"
        made = script + ("c = bpy.data.objects.new('chimera_cam', bpy.data.cameras.new('chimera_cam'))\n"
                         "c.location = (1.0, 2.0, 3.0)\nbpy.context.scene.collection.objects.link(c)\n"
                         "bpy.context.scene.camera = c\n")
        gone = script + "bpy.data.objects.remove(bpy.data.objects['Camera'])\n"
        for v in (first, second):
            factory = _gate.run(script)["probe"][v]["measure"]["scene_camera"]
            self.assertEqual(factory, {"n": "Camera", "t": "CAMERA", "loc": [7.36, -6.93, 4.96],
                                       "dir": [-0.65, 0.61, -0.45], "f": 1, "lens": 50.0})  # FACTORY_MEASURE's
            self.assertFalse(G.camera_made(factory))
            ours = _gate.run(made)["probe"][v]["measure"]["scene_camera"]
            self.assertEqual((ours["n"], ours["f"], ours["loc"], ours["dir"]),
                             ("chimera_cam", 0, [1.0, 2.0, 3.0], [0.0, 0.0, -1.0]))
            self.assertIsNone(_gate.run(gone)["probe"][v]["measure"]["scene_camera"])

    def test_a_copy_of_the_factory_camera_asked_for_by_name_passes_while_it_is_the_scenes(self):
        r = _gate.piece_check(CAMERA_PLAN, 0, CAM, verdict(CAMERA_PLAN, 0, CAM), {}, GOAL)
        self.assertTrue(r["ok"], (r["reasons"], r["tell"]))
        self.assertEqual((r["dupes"], r["factory_copies"]), ([], ["Camera.001"]))  # alone and joined
        self.assertTrue(r["measured"]["camera"]["fits"])
        p = _gate.plan_check(CAMERA_PLAN, {"s1": CAM}, GOAL)
        self.assertTrue(p["ok"], p["reasons"])
        self.assertEqual((p["dupes"], p["factory_copies"]), ([], ["Camera.001"]))
        # Left behind the factory camera, which still renders (smoke2's D12): Camera.001 is a duplicate
        left = _gate.piece_check(CAMERA_PLAN, 0, CAM_LEFT, verdict(CAMERA_PLAN, 0, CAM_LEFT), {}, GOAL)
        self.assertEqual((left["reasons"], left["dupes"], left["factory_copies"]), (["dupes"], ["Camera.001"], []))

    def test_a_camera_the_step_adds_has_to_be_the_scenes(self):
        r = _gate.piece_check(DOLLY_PLAN, 0, DOLLY, verdict(DOLLY_PLAN, 0, DOLLY), {}, GOAL)
        self.assertTrue(r["ok"], (r["reasons"], r["tell"]))
        left = _gate.piece_check(DOLLY_PLAN, 0, DOLLY_LEFT, verdict(DOLLY_PLAN, 0, DOLLY_LEFT), {}, GOAL)
        self.assertEqual(left["reasons"], ["camera_not_active"])
        # a soft fault (SOFT_MEASURED): it still gets its joined check, which passes, since task.py may keep such a
        # piece for the later steps; nothing to repair
        self.assertEqual((sorted(left["joined"]), left["crash"]), (sorted(blenders.VERSIONS), None))
        self.assertTrue(all(s["strict"] for s in left["joined"].values()))
        self.assertEqual(left["tell"], [G.CAMERA_TELL["factory"]])
        self.assertEqual([c["n"] for c in left["measured"]["camera"]["scene_camera"]], ["Camera", "Camera"])
        # A variant is checked alone: it fails the same way
        self.assertEqual(_gate.piece_check(DOLLY_PLAN, 0, DOLLY_LEFT, None, {}, GOAL, joined=False)["reasons"],
                         ["camera_not_active"])

    def test_a_render_the_step_asks_for_has_to_be_handed_to_chimera(self):
        r = _gate.piece_check(RENDER_PLAN, 0, FLOOR, verdict(RENDER_PLAN, 0, FLOOR), {}, GOAL)
        self.assertEqual(r["reasons"], ["output_missing"])
        self.assertEqual((sorted(r["joined"]), r["crash"], T._blender_stage(r["reasons"])),
                         (sorted(blenders.VERSIONS), None, "alone"))  # joined as well, cleanly (SOFT_MEASURED)
        self.assertEqual(r["measured"]["output_missing"]["missing"], ["render"])
        self.assertEqual(r["tell"], ['the step asks Chimera for a render, but SETTINGS_s1 has no "output": put the '
                                     'path or render settings in SETTINGS_s1["output"] ("//room.png") and Chimera '
                                     'does it once, after the last step'])
        handed = _gate.piece_check(RENDER_PLAN, 0, FLOOR_RENDERED, verdict(RENDER_PLAN, 0, FLOOR_RENDERED), {}, GOAL)
        self.assertTrue(handed["ok"], (handed["reasons"], handed["tell"]))

    def test_a_soft_fault_still_gets_the_joined_check(self):
        """output_missing leaves a piece usable by the later steps (task.SOFT_REASONS), so piece_check goes on to the
        joined step after it (SOFT_MEASURED): a box that joins cleanly fails only softly, so task may keep it as a
        dependency; one that crashes after s1's floor is no soft keep, and its crash is its own, for a repair."""
        plan = dict(PLAN, steps=[PLAN["steps"][0], dict(PLAN["steps"][1], instructions=(
            "Put a 0.5 m box chimera_box on s1's floor, register it as ctx['objects']['box'] and render the image to "
            "//box.png. " + MARK))])
        clean = _gate.piece_check(plan, 1, BOX, verdict(plan, 1, BOX), {"s1": FLOOR}, GOAL)
        self.assertEqual(clean["reasons"], ["output_missing"])
        self.assertTrue(clean["joined"] and all(s["strict"] for s in clean["joined"].values()))
        self.assertTrue(T.soft(clean["reasons"]))
        text = reply("s2", BOX_JOINED_CODE, BOX_PROVIDES, BOX_USES)
        crashed = _gate.piece_check(plan, 1, text, verdict(plan, 1, text), {"s1": FLOOR}, GOAL)
        self.assertEqual(crashed["reasons"][0], "output_missing")
        self.assertIn("joined_strict:" + list(blenders.VERSIONS)[0], crashed["reasons"])
        self.assertFalse(T.soft(crashed["reasons"]))
        self.assertIn("chimera_top", crashed["crash"]["error"])
        self.assertEqual(crashed["crash"]["function"], "build_s2")


class CtxChannelTests(unittest.TestCase):
    """ctx_channel as a gate reason (DATAGEN_FORMAT 4), and ctx["values"] (the contract's channel for plain values
    since Nov 4) through the names line and the gate, in real Blender: tests/contract_fixtures.py's values pair, s1
    handing the sofa's sizes on and s2 building with them."""

    def test_a_ctx_channel_try_still_gets_the_joined_check(self):
        """Twin of test_a_soft_fault_still_gets_the_joined_check: a box that reads ctx["settings"] fails ctx_channel
        alone and still joins (SOFT_GATE), so task may keep it on a step a later one depends on (task.soft with
        used) and drops it on one with none; one that crashes after s1's floor is no soft keep either way, and its
        crash is its own, for a repair that is told its ctx key too."""
        first = next(iter(blenders.VERSIONS))
        tell = G.ctx_tell("s2", [], ["settings"])
        text = reply("s2", BOX_CTX_CODE, BOX_PROVIDES, BOX_USES)
        clean = _gate.piece_check(PLAN, 1, text, verdict(PLAN, 1, text), {"s1": FLOOR}, GOAL)
        self.assertEqual(clean["reasons"], ["ctx_channel"])
        self.assertEqual((clean["ctx_channel"], clean["ctx_tell"]), ({"written": [], "read": ["settings"]}, tell))
        self.assertEqual(clean["tell"], [tell])
        self.assertEqual((sorted(clean["joined"]), clean["crash"], T._blender_stage(clean["reasons"])),
                         (sorted(blenders.VERSIONS), None, "alone"))
        self.assertTrue(all(s["strict"] for s in clean["joined"].values()))
        self.assertTrue(T.soft(clean["reasons"], used=True))
        self.assertFalse(T.soft(clean["reasons"]))
        text = reply("s2", BOX_CTX_JOINED_CODE, BOX_PROVIDES, BOX_USES)
        crashed = _gate.piece_check(PLAN, 1, text, verdict(PLAN, 1, text), {"s1": FLOOR}, GOAL)
        self.assertEqual(crashed["reasons"][0], "ctx_channel")
        self.assertIn("joined_strict:" + first, crashed["reasons"])
        self.assertFalse(T.soft(crashed["reasons"], used=True))
        self.assertIn("chimera_top", crashed["crash"]["error"])
        self.assertEqual(crashed["crash"]["function"], "build_s2")
        self.assertEqual(crashed["tell"], [tell])  # the crash goes to the notes as it is

    def test_a_variant_fails_on_ctx_channel(self):
        text = reply("s2", BOX_CTX_CODE, BOX_PROVIDES, BOX_USES)
        r = _gate.piece_check(PLAN, 1, text, None, {"s1": FLOOR}, GOAL, joined=False)
        self.assertEqual((r["reasons"], r["joined"]), (["ctx_channel"], {}))
        self.assertFalse(T.soft(r["reasons"]))  # a variant is never used (task.Round.used)

    def test_a_try_that_crashes_alone_is_told_its_ctx_key_too(self):
        """The key is read from the code, so a try that stops alone (before the reason is reached) is told it, and a
        repair can fix both."""
        text = reply("s2", BOX_CTX_CRASH_CODE, BOX_PROVIDES, BOX_USES)
        r = _gate.piece_check(PLAN, 1, text, verdict(PLAN, 1, text), {"s1": FLOOR}, GOAL)
        self.assertEqual(r["reasons"], ["alone_strict:" + x for x in blenders.VERSIONS])
        self.assertEqual(r["crash"]["function"], "build_s2")
        self.assertEqual(r["ctx_channel"], {"written": [], "read": ["settings"]})
        self.assertEqual(r["tell"], [G.ctx_tell("s2", [], ["settings"])])
        # a piece with no such key has neither field
        ok = _gate.piece_check(PLAN, 1, BOX, verdict(PLAN, 1, BOX), {"s1": FLOOR}, GOAL)
        self.assertTrue(ok["ok"], ok["reasons"])
        self.assertNotIn("ctx_channel", ok)
        self.assertNotIn("ctx_tell", ok)

    def names_line(self, script, binary):
        """The names line of script run with NAMES_EPILOGUE, sandboxed as the data generator runs a tool."""
        from datagen import pysandbox
        r = pysandbox.run_tool({"script.py": script.rstrip("\n") + "\n" + G.NAMES_EPILOGUE}, binary,
                               ["-b", "--factory-startup", "--python-exit-code", "1", "--python", "script.py"],
                               timeout=180, work=os.environ.get("WM_SCRATCH"))
        self.assertEqual(r["exit"], 0, r["output"][-1500:])
        self.assertTrue(r["sandboxed"])
        return G._names_line(r["output"]), r["output"]

    def test_the_names_line_lists_the_values_keys(self):
        ch = chimera()
        j = ch.join(CF.VALUES_PLAN, CF.VALUES_OUTPUTS, goal=VALUES_GOAL)
        self.assertFalse(j.get("fallback"), j.get("reasons"))
        s2 = CF.VALUES_PLAN["steps"][1]
        alone = ch.alone([{"text": CF.VALUES_S2, "mode": "blender", "sid": "s2", "deps": ["s1"], "lone": False,
                           "step": s2, "keep_ctx": True, "ctx_name": "ctx"}])[0]
        for v, binary in blenders.VERSIONS.items():
            with self.subTest(v):
                names, out = self.names_line(j["script"], binary)
                self.assertEqual(names["ctx"]["values"], ["sofa_depth", "sofa_width"])
                self.assertEqual(names["ctx"]["live"], ["sofa"])
                self.assertIn("sofa: 2.2 x 0.9", out)
                self.assertNotIn("chimera: stand-in", out)
                names, out = self.names_line(alone, binary)  # s2 with no s1: an empty ctx["values"]
                self.assertEqual(names["ctx"]["values"], [])
                self.assertIn("chimera: stand-in sofa_width", out)
                # a ctx with no values dict (a guard from before Nov 4) prints no "values" field at all
                names, _ = self.names_line(MARK + "\nimport bpy\nctx = {\"scene\": bpy.context.scene, \"objects\": "
                                           "{}}\n", binary)
                self.assertEqual(names["ctx"], {"live": [], "dead": []})

    def test_the_values_pair_passes_alone_joined_and_as_a_plan(self):
        """s1's provides lists its ctx["values"] keys, which the names line has (provides_missing passes), and s2
        joined after it neither prints a stand-in nor loses what s1 provides (stand_in, removes_earlier)."""
        plan = CF.VALUES_PLAN
        s1 = _gate.piece_check(plan, 0, CF.VALUES_S1, verdict(plan, 0, CF.VALUES_S1), {}, VALUES_GOAL)
        self.assertTrue(s1["ok"], (s1["reasons"], s1["tell"]))
        self.assertEqual(s1["provides_missing"], [])
        self.assertEqual(s1["scene"]["ctx_values"], ["sofa_depth", "sofa_width"])
        run = _gate.run(_gate.chimera.alone([{"text": CF.VALUES_S1, "mode": "blender", "sid": "s1", "deps": [],
                                               "lone": False, "step": plan["steps"][0], "keep_ctx": True,
                                               "ctx_name": "ctx"}])[0])
        for v in blenders.VERSIONS:
            self.assertEqual(run["probe"][v]["ctx_values"], ["sofa_depth", "sofa_width"])
            self.assertTrue({"sofa_width", "sofa_depth"} <= G._have(run["probe"][v]))
        s2 = _gate.piece_check(plan, 1, CF.VALUES_S2, verdict(plan, 1, CF.VALUES_S2), {"s1": CF.VALUES_S1},
                               VALUES_GOAL)
        self.assertTrue(s2["ok"], (s2["reasons"], s2["tell"]))
        self.assertEqual((s2["stand_in"], s2["stand_in_keys"], s2["removed"]), (False, [], []))
        self.assertTrue(all(s["strict"] for s in s2["joined"].values()))
        p = _gate.plan_check(plan, {"s1": CF.VALUES_S1, "s2": CF.VALUES_S2}, VALUES_GOAL)
        self.assertTrue(p["ok"], p["reasons"])
        self.assertEqual((p["provides_lost"], p["stand_in"]), ([], False))


class GlobalCtxTests(unittest.TestCase):
    """After the fifth smoke (Nov 6), in real Blender: a box whose module-level helper reads a ctx it is never given
    passes alone (the gate's tail binds ctx at module level), fails global_ctx there and still goes on to the joined
    run, Chimera's own join, where the read raises NameError in the helper: a crash in the piece, for a repair, as
    Chimera would send it. A variant (alone only) fails on global_ctx, and the line is told whatever else fails."""

    def test_the_joined_run_shows_the_crash_and_a_variant_fails_alone(self):
        tell = G.global_ctx_tell("s2", [{"function": "_s2_link", "line": 9}])
        text = reply("s2", BOX_GLOBAL_CODE, BOX_PROVIDES, BOX_USES)
        code = verdict(PLAN, 1, text)["code"]
        self.assertEqual(G.global_ctx(code), [{"function": "_s2_link", "line": line_of(code, "def _s2_link(obj):")}])
        r = _gate.piece_check(PLAN, 1, text, verdict(PLAN, 1, text), {"s1": FLOOR}, GOAL)
        self.assertTrue(all(s["strict"] for s in r["alone"].values()))  # alone it runs: the gap
        self.assertEqual(r["reasons"], ["global_ctx"] + ["joined_strict:" + v for v in blenders.VERSIONS])
        self.assertEqual((r["crash"]["function"], r["crash"]["step"]), ("_s2_link", "s2"))
        self.assertEqual(r["crash"]["error"], "NameError: name 'ctx' is not defined")
        self.assertEqual(r["global_ctx_tell"], tell)
        self.assertEqual(r["tell"], [tell])  # the crash goes to the notes as it is
        self.assertEqual(T._blender_stage(r["reasons"]), "joined")
        self.assertFalse(T.soft(r["reasons"], used=True))
        alone = _gate.piece_check(PLAN, 1, text, None, {"s1": FLOOR}, GOAL, joined=False)
        self.assertEqual((alone["reasons"], alone["joined"], alone["crash"]), (["global_ctx"], {}, None))
        self.assertEqual(alone["tell"], [tell])
        # the same box with the helper given ctx passes
        fixed = BOX_GLOBAL_CODE.replace("def _s2_link(obj):", "def _s2_link(ctx, obj):").replace(
            "    _s2_link(box)\n", "    _s2_link(ctx, box)\n")
        text = reply("s2", fixed, BOX_PROVIDES, BOX_USES)
        ok = _gate.piece_check(PLAN, 1, text, verdict(PLAN, 1, text), {"s1": FLOOR}, GOAL)
        self.assertTrue(ok["ok"], (ok["reasons"], ok["tell"]))
        self.assertNotIn("global_ctx", ok)


class BuildFactsGateTests(unittest.TestCase):
    """After the fourth smoke (Nov 5), in real Blender through piece_check: what the build drops (a dead output key,
    Chimera's validator warnings) and the stand-in marker's faults fail a piece that passes everything else, at the
    alone stage, told, and it still gets its joined check (soft on a step a later step depends on, as ctx_channel);
    a values step's long list of names passes as before (the open contract question), in any form since Nov 6, and
    nothing else fails it. Their rules and wordings are tests/test_datagen_stand_ins.py's, without Blender."""

    def assertSoftAlone(self, r, reasons):
        self.assertEqual(r["reasons"], reasons)
        self.assertEqual((T._blender_stage(r["reasons"]), r["crash"]), ("alone", None))
        self.assertEqual(sorted(r["joined"]), sorted(blenders.VERSIONS))
        self.assertTrue(all(s["strict"] for s in r["joined"].values()), r["joined"])
        self.assertTrue(T.soft(r["reasons"], used=True))
        self.assertFalse(T.soft(r["reasons"]))

    def test_a_dead_output_key_on_a_step_that_asks_for_none(self):
        """The fourth smoke's values step and combine step kept an output_path no step asked for: the build dropped
        both after sampling had stopped, and no try was told."""
        code = BOX_CODE.replace('SETTINGS_s2 = {"size": 0.5}',
                                'SETTINGS_s2 = {"size": 0.5, "output_path": "//box.png"}')
        text = reply("s2", code, BOX_PROVIDES, BOX_USES)
        r = _gate.piece_check(PLAN, 1, text, verdict(PLAN, 1, text), {"s1": FLOOR}, GOAL)
        self.assertSoftAlone(r, ["dead_output_key"])
        self.assertEqual(r["facts"]["dead_output"], ["output_path"])
        self.assertEqual(r["tell"], [G.dead_tell("s2", ["output_path"], asked=False)])
        clean = _gate.piece_check(PLAN, 1, BOX, verdict(PLAN, 1, BOX), {"s1": FLOOR}, GOAL)
        self.assertTrue(clean["ok"], clean["reasons"])
        self.assertNotIn("facts", clean)

    def test_chimeras_warning_and_a_misused_marker(self):
        """A floor that registers a key its provides line doesn't name, and one that prints the stand-in line for a
        GPU fallback on a step with no dependency (the fourth smoke's values steps): each fails alone, told."""
        extra = FLOOR_CODE.replace('    ctx["objects"]["floor"] = floor\n',
                                   '    ctx["objects"]["floor"] = floor\n    ctx["objects"]["floor_mat"] = mat\n')
        text = reply("s1", extra, 'chimera_floor as ctx["objects"]["floor"]')
        r = _gate.piece_check(PLAN, 0, text, verdict(PLAN, 0, text), {}, GOAL)
        self.assertSoftAlone(r, ["validator_warning:provides_missing"])
        self.assertEqual(r["tell"], ['ctx["objects"] gets "floor_mat" from the piece, but its provides line doesn\'t '
                                     'name it: list under provides each key a later step reads, and leave out of '
                                     'ctx["objects"] the ones none does'])
        gpu = FLOOR_CODE.replace('    s = SETTINGS_s1\n', '    s = SETTINGS_s1\n    if "gpu" in s:\n'
                                 '        print("chimera: stand-in render_device (fallback to CPU)")\n')
        text = reply("s1", gpu, 'chimera_floor as ctx["objects"]["floor"]; material chimera_floor_mat')
        r = _gate.piece_check(PLAN, 0, text, verdict(PLAN, 0, text), {}, GOAL)
        self.assertSoftAlone(r, ["marker_misused"])
        self.assertEqual(r["facts"]["stand_ins"]["marker"], ["render_device"])
        self.assertTrue(r["tell"][0].startswith('"render_device": the piece prints the stand-in line for no key'))

    def test_a_silent_default_and_the_values_steps_list(self):
        """The bench before its marker loop read s1's sizes with a silent default (the valid example's habit): it
        fails alone, told, joined cleanly after s1; and s1 with a plain list of 30 names under provides (Chimera's
        handoff_long) passes as before, whatever else the build would drop it for."""
        silent_code = BENCH_CODE.replace('    for k in ("length", "width", "height"):\n'
                                         '        if "bench_" + k not in values:\n'
                                         '            print("chimera: stand-in", "bench_" + k)\n', "")
        self.assertNotEqual(silent_code, BENCH_CODE)
        text = reply("s2", silent_code, BENCH_PROVIDES)
        r = _gate.piece_check(BENCH_PLAN, 1, text, verdict(BENCH_PLAN, 1, text), {"s1": VALUES}, GOAL)
        self.assertSoftAlone(r, ["silent_default"])
        self.assertEqual(r["tell"], [G.stand_ins.SILENT_HELPER_TELL.format(where="build_s2()",
                                                                           marker=G.stand_ins.MARKER_CALL)])
        names = "bench_length, bench_width, bench_height, " + ", ".join("bench_extra_%02d" % k for k in range(27))
        self.assertGreater(len(names), G.HANDOFF_MAX)
        marked = VALUES_CODE.replace("    ctx[\"values\"].update(SETTINGS_s1)\n",
                                     "    ctx[\"values\"].update(SETTINGS_s1)\n    if \"gpu\" in SETTINGS_s1:\n"
                                     "        print(\"chimera: stand-in render_device\")\n")
        text = reply("s1", marked, names)
        v = verdict(BENCH_PLAN, 0, text)
        self.assertIn("handoff_long", [x["code"] for x in v["issues"]])
        r = _gate.piece_check(BENCH_PLAN, 0, text, v, {}, GOAL)
        self.assertTrue(r["ok"], r["reasons"])
        self.assertTrue(r["facts"]["waived"])
        self.assertEqual(r["facts"]["stand_ins"]["marker"], ["render_device"])  # recorded, no reason
        for line in ('ctx["values"]: ' + names, names + ' (all in ctx["values"]).'):  # in any form (decided Nov 6)
            text = reply("s1", marked, line)
            v = verdict(BENCH_PLAN, 0, text)
            self.assertIn("handoff_long", [x["code"] for x in v["issues"]])
            r = _gate.piece_check(BENCH_PLAN, 0, text, v, {}, GOAL)
            self.assertEqual((r["ok"], r["reasons"], r["facts"]["waived"]), (True, [], True), line)
        short = reply("s1", marked, "bench_length, bench_width, bench_height")
        r = _gate.piece_check(BENCH_PLAN, 0, short, verdict(BENCH_PLAN, 0, short), {}, GOAL)
        self.assertSoftAlone(r, ["marker_misused"])  # without the open question's warning it is a fault


class HiddenErrorTests(unittest.TestCase):
    """Step 6a in real Blender, through piece_check: a box that sets a Principled BSDF input by its old name inside a
    try that swallows the KeyError fails swallowed alone, and one that looks an input up by a wrong name behind a
    guard fails skipped_input; both still join cleanly (soft, as Chimera passes them), are told what they hid, and the
    joined run's report finds the same line through the line map, recorded only; a variant fails alone."""

    def test_a_swallowed_error_fails_alone_and_still_gets_the_joined_check(self):
        text = reply("s2", BOX_SWALLOWED_CODE, BOX_PROVIDES, BOX_USES)
        v = verdict(PLAN, 1, text)
        r = _gate.piece_check(PLAN, 1, text, v, {"s1": FLOOR}, GOAL)
        line = line_of(v["code"], HIDDEN_SET.rstrip("\n"))
        self.assertEqual((r["lint"], r["reasons"], r["crash"]), ([], ["swallowed"], None))
        self.assertTrue(all(s["strict"] for s in r["alone"].values()))  # Chimera's check passes it
        self.assertTrue(all(s["strict"] for s in r["joined"].values()))
        found = r["measured"]["silent"]["swallowed"]
        self.assertEqual([(f["line"], f["versions"]) for f in found], [(line, sorted(blenders.VERSIONS))])
        self.assertIn('key "Transmission" not found', found[0]["error"])
        self.assertEqual(r["tell"], silent.tell(found, []))
        self.assertTrue(r["tell"][0].startswith("line %d `bsdf.inputs[s[\"input\"]]" % line), r["tell"])
        self.assertEqual([f["line"] for f in r["measured"]["joined_silent"]["swallowed"]], [line])
        self.assertTrue(T.soft(r["reasons"]))
        self.assertEqual(T._blender_stage(r["reasons"]), "alone")
        variant = _gate.piece_check(PLAN, 1, text, v, {"s1": FLOOR}, GOAL, joined=False)
        self.assertEqual((variant["reasons"], variant["joined"]), (["swallowed"], {}))

    def test_an_input_skipped_behind_a_guard_fails_alone(self):
        text = reply("s2", BOX_SKIPPED_CODE, BOX_PROVIDES, BOX_USES)
        v = verdict(PLAN, 1, text)
        r = _gate.piece_check(PLAN, 1, text, v, {"s1": FLOOR}, GOAL)
        line = line_of(v["code"], HIDDEN_GUARD.rstrip("\n"))
        self.assertEqual((r["lint"], r["reasons"]), ([], ["skipped_input"]))
        skipped = r["measured"]["silent"]["skipped"]
        self.assertEqual([(f["line"], f["key"], f["owner"], f["close"]) for f in skipped],
                         [(line, "Base_Color", "chimera_box_mat", ["Base Color"])])
        self.assertEqual(r["tell"], ["line %d looked up the input 'Base_Color' on chimera_box_mat's Principled BSDF, "
                                     "which has no input of that name (it has 'Base Color'), so the lookup was skipped "
                                     "and Base Color stayed at its default: use the input's real name" % line])
        self.assertEqual([f["key"] for f in r["measured"]["joined_silent"]["skipped"]], ["Base_Color"])
        self.assertTrue(all(s["strict"] for s in r["joined"].values()))
        # the box without either passes, its report watched and empty
        ok = _gate.piece_check(PLAN, 1, BOX, verdict(PLAN, 1, BOX), {"s1": FLOOR}, GOAL)
        self.assertTrue(ok["ok"], ok["reasons"])
        self.assertEqual(ok["measured"].get("silent"), {"swallowed": [], "skipped": [], "attr_miss": [],
                                                        "excused": []})
        run = _gate.run(_gate.chimera.alone([{"text": BOX, "mode": "blender", "sid": "s2", "deps": ["s1"],
                                              "lone": False, "step": PLAN["steps"][1], "keep_ctx": True,
                                              "ctx_name": "ctx"}])[0])
        self.assertEqual({v: run["probe"][v]["silent"]["how"] for v in blenders.VERSIONS},
                         {v: "monitoring" if v.startswith("5.2") else "settrace" for v in blenders.VERSIONS})


# Step 6b's fixtures: the box asked at a point of its own, and a curve asked to be extruded
PLACED_PLAN = dict(PLAN, steps=[PLAN["steps"][0], dict(PLAN["steps"][1], instructions=(
    'Put a 0.5 m box named "chimera_box" at (1, 1, 0) on s1\'s floor; register it as ctx[\'objects\'][\'box\']. ' + MARK))])
BOX_AT = reply("s2", BOX_CODE.replace(LOCATION, "    box.location = (1.0, 1.0, floor.location.z)\n"), BOX_PROVIDES,
               BOX_USES)
WAVE_PLAN = {"title": "Wave", "kind": "blender", "summary": "A wave curve. " + MARK, "steps": [
    {"id": "s1", "title": "Wave", "kind": "blender", "depends_on": [],
     "instructions": 'Add a curve named "chimera_wave" and extrude it by 0.08 m; register it as '
                     'ctx[\'objects\'][\'wave\']. ' + MARK}]}
WAVE_GOAL = "Make a wave-shaped curve in Blender, extruded into a ribbon. " + MARK
WAVE_CODE = MARK + '''
import bpy

SETTINGS_s1 = {"extrude": 0.04}


def build_s1(ctx):
    s = SETTINGS_s1
    curve = bpy.data.curves.new("chimera_wave", "CURVE")
    curve.dimensions = "2D"
    spline = curve.splines.new("BEZIER")
    spline.bezier_points.add(1)
    spline.bezier_points[0].co = (0.0, 0.0, 0.0)
    spline.bezier_points[1].co = (2.0, 0.7, 0.0)
    for p in spline.bezier_points:
        p.handle_left_type = p.handle_right_type = "AUTO"
    curve.extrude = s["extrude"]
    wave = bpy.data.objects.new("chimera_wave", curve)
    ctx["collection"].objects.link(wave)
    ctx["objects"]["wave"] = wave

'''
WAVE_PROVIDES = 'chimera_wave as ctx["objects"]["wave"]'
WAVE = reply("s1", WAVE_CODE, WAVE_PROVIDES)
WAVE_FLAT = reply("s1", WAVE_CODE.replace('{"extrude": 0.04}', '{"extrude": 0.0}'), WAVE_PROVIDES)
# The fourth smoke's bad example's step (Nov 5): a side given, so its 0.08 m is the whole depth one way
WAVE_DOWN_PLAN = {"title": "Wave", "kind": "blender", "summary": "A wave curve. " + MARK, "steps": [
    {"id": "s1", "title": "Wave", "kind": "blender", "depends_on": [],
     "instructions": 'Add a curve named "chimera_wave" and extrude it by 0.08 m in the negative Z direction; register '
                     'it as ctx[\'objects\'][\'wave\']. ' + MARK}]}
WAVE_DOUBLED = reply("s1", WAVE_CODE.replace('{"extrude": 0.04}', '{"extrude": 0.08}'), WAVE_PROVIDES)


class GeometryTests(unittest.TestCase):
    """Step 6b in real Blender, through piece_check: a box its step puts at (1, 1, 0) that the piece leaves on its
    floor's origin fails place_mismatch on its joined run (alone it stands on the floor's stand-in, so its place is
    recorded there), soft, and is told where its box is; one placed there passes. A curve its step asks to extrude by 0.08 m that the piece leaves flat fails flat_extrusion, and one
    extruded passes, its size measured from its evaluated mesh."""

    def test_a_box_left_off_its_point_fails_alone_and_still_gets_the_joined_check(self):
        r = _gate.piece_check(PLACED_PLAN, 1, BOX, verdict(PLACED_PLAN, 1, BOX), {"s1": FLOOR}, GOAL)
        self.assertEqual((r["lint"], r["reasons"], r["crash"]), ([], ["place_mismatch"], None))
        self.assertTrue(all(s["strict"] for s in r["alone"].values()))  # Chimera's check passes it
        self.assertTrue(all(s["strict"] for s in r["joined"].values()))
        self.assertEqual(r["tell"], ["the step puts the chimera_box at (1, 1, 0), but chimera_box's box runs from "
                                     "(-0.25, -0.25, 0) to (0.25, 0.25, 0.5): neither its centre, the middle of its "
                                     "bottom nor its origin is there"])
        # alone it stood on the floor's stand-in, so the place is the joined run's, where the real floor is
        self.assertEqual([(p["fits"], p["unmeasured"]) for p in r["measured"]["places"]], [(None, "stand_in")])
        self.assertEqual([p["fits"] for p in r["measured"]["joined_places"]], [False])
        self.assertTrue(T.soft(r["reasons"]))
        self.assertEqual(r["stage"], "joined")
        ok = _gate.piece_check(PLACED_PLAN, 1, BOX_AT, verdict(PLACED_PLAN, 1, BOX_AT), {"s1": FLOOR}, GOAL)
        self.assertTrue(ok["ok"], (ok["reasons"], ok["tell"]))
        self.assertEqual([p["fits"] for p in ok["measured"]["places"]], [True])
        run = _gate.run(_gate.chimera.alone([{"text": BOX_AT, "mode": "blender", "sid": "s2", "deps": ["s1"],
                                              "lone": False, "step": PLACED_PLAN["steps"][1], "keep_ctx": True,
                                              "ctx_name": "ctx"}])[0])
        for v in blenders.VERSIONS:
            box = next(o for o in run["probe"][v]["geom"]["objects"] if o["n"] == "chimera_box")
            self.assertEqual((box["lo"], box["hi"], box["faces"]), ([0.75, 0.75, 0.0], [1.25, 1.25, 0.5], 6))

    def test_a_curve_left_flat_fails_flat_extrusion_and_one_extruded_passes(self):
        flat = _gate.piece_check(WAVE_PLAN, 0, WAVE_FLAT, verdict(WAVE_PLAN, 0, WAVE_FLAT), {}, WAVE_GOAL)
        self.assertEqual((flat["lint"], flat["reasons"]), ([], ["flat_extrusion"]))
        self.assertEqual(flat["tell"], ["the step asks for a depth of 0.08 m, but chimera_wave has 0 faces and is 0 m "
                                        "at its thinnest"])
        self.assertTrue(all(s["strict"] for s in flat["joined"].values()))  # soft: still joined
        ok = _gate.piece_check(WAVE_PLAN, 0, WAVE, verdict(WAVE_PLAN, 0, WAVE), {}, WAVE_GOAL)
        self.assertTrue(ok["ok"], (ok["reasons"], ok["tell"]))
        self.assertEqual([d["fits"] for d in ok["measured"]["depths"]], [True])
        # the measuring sizes it from its evaluated mesh: 0.08 m deep, not its bound box's
        self.assertEqual(ok["scene"]["sizes"]["chimera_wave"][2], 0.08)

    def test_a_curve_extruded_both_ways_fails_doubled_depth(self):
        """Real Blender, both versions (Nov 5): asked 0.08 m in the negative Z, a curve given extrude 0.08 is 0.16 m
        thick (Blender extrudes both ways) and fails doubled_depth, soft (still joined), with its tell; extrude 0.04
        is the 0.08 m asked and passes (its side isn't judged: nothing here measures a curve's plane)."""
        bad = _gate.piece_check(WAVE_DOWN_PLAN, 0, WAVE_DOUBLED, verdict(WAVE_DOWN_PLAN, 0, WAVE_DOUBLED), {},
                                WAVE_GOAL)
        self.assertEqual((bad["lint"], bad["reasons"]), ([], ["doubled_depth"]))
        self.assertEqual(bad["tell"], ["the step asks for a depth of 0.08 m, but chimera_wave is 0.16 m at its "
                                       "thinnest, twice that: a curve's or a text's extrude value goes both ways from "
                                       "it, so the depth is twice the value"])
        self.assertEqual([d["fits"] for d in bad["measured"]["doubled"]], [False])
        self.assertTrue(all(s["strict"] for s in bad["joined"].values()))  # soft: still joined
        self.assertTrue(T.soft(bad["reasons"]))
        self.assertEqual(T._blender_stage(bad["reasons"]), "alone")
        ok = _gate.piece_check(WAVE_DOWN_PLAN, 0, WAVE, verdict(WAVE_DOWN_PLAN, 0, WAVE), {}, WAVE_GOAL)
        self.assertTrue(ok["ok"], (ok["reasons"], ok["tell"]))
        self.assertEqual([d["fits"] for d in ok["measured"]["doubled"]], [True])
        # the same piece under a step without a side: an extrude value may be what it asks, so nothing is read
        plain = _gate.piece_check(WAVE_PLAN, 0, WAVE_DOUBLED, verdict(WAVE_PLAN, 0, WAVE_DOUBLED), {}, WAVE_GOAL)
        self.assertTrue(plain["ok"], plain["reasons"])
        self.assertNotIn("doubled", plain["measured"])


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _gone(pid, seconds):
    end = time.monotonic() + seconds
    while _alive(pid):
        if time.monotonic() > end:
            return False
        time.sleep(0.1)
    return True


def _ours(pid, work):
    """Whether pid is a Blender this test started (its script is under work), so a cleanup kills nothing else."""
    p = subprocess.run(["ps", "-ww", "-o", "args=", "-p", str(pid)], capture_output=True, text=True)
    return "--python-exit-code" in p.stdout and work in p.stdout


class DirectRunTests(unittest.TestCase):
    """The direct run itself, in real Blender; Chimera's check is a stand-in that passes where a gate is used."""

    def gate(self, **kw):
        g = make_gate(os.path.join(tempfile.mkdtemp(dir=_tmp), "runs.jsonl"), **kw)

        def check_result(path, *, goal=None, work_dir, blender=None, timeout=None):
            v = next(k for k, b in blenders.VERSIONS.items() if b == blender)
            return {"check": {"outcome": "passed", "runner": "Blender " + v, "output": ""}, "critique": "", "exit": 0,
                    "stated": "Blender " + v}
        g.chimera.check_result = check_result
        g.blender.ch = g.chimera
        return g

    def test_a_run_that_never_got_to_blenders_python_is_a_problem_not_a_verdict(self):
        g = self.gate()
        real = G.blender_run.sandbox_profile
        G.blender_run.sandbox_profile = lambda d, binary: "(version 1)\n(deny default)"  # sandbox-exec can't start it
        try:
            r = g.run("# never started %s\nimport bpy\n" % MARK)
        finally:
            G.blender_run.sandbox_profile = real
        for v in blenders.VERSIONS:
            self.assertIn("never got to Blender's Python", r["probe"][v]["problem"])
            self.assertIn("sandbox-exec", r["probe"][v]["problem"])
            self.assertFalse(counted_strict(r["check"][v], r["probe"][v]))
        self.assertFalse(r["cached"])
        self.assertEqual(len(g.cache), 0)  # a resumed run tries it again
        # A script that ends by os._exit loses Blender's header, but it did run: a verdict, cached, version known
        r = g.run("# ends by os._exit %s\nimport bpy, os\nos._exit(0)\n" % MARK)
        for v in blenders.VERSIONS:
            self.assertNotIn("problem", r["probe"][v])
            self.assertEqual((r["probe"][v]["blender"], r["probe"][v]["version_ok"]), (v, True))
        self.assertEqual(len(g.cache), 1)

    def test_the_measuring_leaves_the_verdict_alone(self):
        # The script's own handlers would print an error line when the scene is evaluated: the measuring holds them
        # off and shuts the output meanwhile, so the run's verdict is what it was without the measuring.
        g = self.gate()
        for v, b in blenders.VERSIONS.items():
            out = g.blender._direct(HANDLER, b, v)
            self.assertEqual((out["exit"], out["strict_full"], out["bad_lines"]), (0, True, []), out["output_tail"])
            self.assertIn("chimera_dg_test_empty", [r["n"] for r in out["measure"]["objects"]])
        # ... whereas an update of the script's own sets them off (the handlers work)
        v, b = next(iter(blenders.VERSIONS.items()))
        out = g.blender._direct(HANDLER + "bpy.context.scene.collection.objects.link(bpy.data.objects.new("
                                          "'chimera_dg_test_two', None))\nbpy.context.view_layer.update()\n", b, v)
        self.assertFalse(out["strict_full"])
        self.assertTrue(any("dg-test handler ran" in l for l in out["bad_lines"]), out["bad_lines"])

    def test_a_hung_run_stops_at_its_timeout_with_its_blender(self):
        g = self.gate(timeout=6.0)
        v, b = next(iter(blenders.VERSIONS.items()))
        out = g.blender._direct(HANG, b, v)
        self.assertIsNone(out["exit"])
        self.assertTrue(out["output_tail"].endswith("(timed out after 6 s)"), out["output_tail"])
        self.assertNotIn("problem", out)  # it ran: a timeout is the script's verdict
        pid = int(out["output_tail"].split("dg-test pid ")[1].split()[0])
        self.assertTrue(_gone(pid, 5))

    def test_the_runs_blender_dies_with_the_process_that_started_it_even_by_kill_9(self):
        v, b = next(iter(blenders.VERSIONS.items()))
        work = tempfile.mkdtemp(dir=_tmp)
        code = ("import sys, threading\n"
                "from datagen import blender_gate as G\n"
                "class Ch:\n    binary = %r\n"
                "g = G.GateBlender(Ch(), {%r: %r}, %r, 300.0, 300.0, threading.BoundedSemaphore(1))\n"
                "g._direct(sys.stdin.read(), %r, %r)\n") % (_bin, v, b, work, b, v)
        child = subprocess.Popen([sys.executable, "-c", code], cwd=_paths.HERE, stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        child.stdin.write(HANG.encode())
        child.stdin.close()
        pid, end = None, time.monotonic() + 90
        try:
            while pid is None and time.monotonic() < end and child.poll() is None:
                for f in glob.glob(os.path.join(work, "dg-probe-*", "pid.txt")):
                    with open(f, encoding="utf-8") as fh:
                        pid = int(fh.read().strip() or 0) or None
                time.sleep(0.1)
            self.assertIsNotNone(pid, "the direct run never started")
            self.assertTrue(_ours(pid, work))
            child.kill()  # SIGKILL: no finally, no atexit runs in it
            child.wait()
            self.assertTrue(_gone(pid, 10), "the direct run's Blender outlived the process that started it")
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            if pid and _alive(pid) and _ours(pid, work):
                os.kill(pid, signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
