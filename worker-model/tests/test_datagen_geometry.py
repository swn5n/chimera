"""datagen/geometry.py, step 6b: the places, depths and relations a Blender step gives in numbers, against what its
piece built (blender_gate's geometry line and measuring).

Without Blender: the readers on step texts (a point after "at", "positioned", "placed" or the origin, for the thing
the clause names, in quotes or by its words; never a target, an example, a hedged or an animated one, nor a thing
another step makes; a depth to extrude, solidify or bevel; behind, in front of and the recorded above and below), and
the faults on hand-made geometry lines: a box lifted off its point fails and one centred, standing on it or placed by
its own origin passes, an origin left outside its box doesn't count, a light by its location, an animated or moving
object is never matched, a flat curve fails a depth and an instanced one doesn't, a plate buried in its logo fails and
one behind or below it passes, a light is never buried, a relation whose object the run made a stand-in for is
skipped (the third smoke's D29); the tell lines (numbers and names, never the step's phrase, short, their fixed forms
refused by the echo check and none of Chimera's words); which readers gate (the held-out check's counts), and that
the readers still read what the held-out check read on the helper's stored plans (when they are here).

In real Blender (5.2.2 and 5.0.1, tools/blenders.VERSIONS; skipped without them), sandboxed: through pysandbox.run_tool,
the measuring sizes a bevelled bezier 2.035 x 0.322 x 0.1 and a text's depth 0.1 from their evaluated meshes, and a
plain bezier, a NURBS path and a NURBS surface as before, while a piece of meshes only measures and lists byte for
byte as the measuring did before; through the gate's own direct run (GateBlender._direct; no Chimera call, so no Go
binary): the geometry line's boxes, faces, curve settings, instances (a curve's own mesh isn't one) and moving objects,
its cut with 61 objects within its budget, and the refuter's 9 correct pieces (a text before a curved backdrop, an
off-centre logo and a text placed by their origins, a corner-origin panel, a lamp on the floor, a rug on a slab,
bevelled text, a backplate behind an upright logo) with no fault from any reader.

Every piece and step here is Claude-written test text and carries the fixture mark, never training data. About 15 s.
"""
# test fixture, never training data
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from tests import _paths
from datagen import blender_gate as BG
from datagen import geometry as G
from datagen import hints as H
from datagen import pysandbox
from runner.mock_ollama import MARK
from tools import blender_check, blenders

HAVE_BLENDER = all(not blenders.check_path(p) for p in blenders.VERSIONS.values())


def plan(*instructions, titles=None):
    steps = []
    for k, ins in enumerate(instructions):
        steps.append({"id": "s%d" % (k + 1), "title": (titles or [""] * len(instructions))[k] or "Step %d" % (k + 1),
                      "kind": "blender", "instructions": ins + " " + MARK, "depends_on": ["s%d" % k] if k else []})
    return {"title": "t", "kind": "blender", "summary": MARK, "steps": steps}


def box(n, lo, hi, t="MESH", faces=6, **kw):
    return dict(dict(n=n, t=t, lo=list(lo), hi=list(hi), faces=faces, verts=8, loc=[0.0, 0.0, 0.0]), **kw)


def probe(rows, points=(), moving=()):
    g = {"v": 1, "objects": rows}
    if moving:
        g["moving"] = list(moving)
    return {"geom": g, "measure": {"v": 1, "objects": [dict(n=n, t=t, loc=list(loc)) for n, t, loc in points]}}


KITCHEN = plan("Write Blender Python code that:\n2. Creates a rectangular island countertop (2.4 m x 0.9 m x 0.92 m), "
               "applies a light oak material, and places it at the origin.\n3. Adds a fridge (0.8 m x 0.7 m x 1.8 m) "
               "with a white material and positions it at (1.2, -0.3, 0).\n4. Creates a key area light at (0, 0, 5) "
               "with 1500 W power.\n5. Adds a camera at (0, 0, 3) looking at the origin (0, 0, 0).")
LOGO = plan("Add a plane behind the logo, name it `Backplate`.")


class ReaderTests(unittest.TestCase):
    """The prototype's readers, as this round reads them."""

    def test_places_name_the_thing_and_skip_targets(self):
        got = [(a["kind"], a["point"], a["words"]) for a in G.asked_places(KITCHEN, 0)]
        self.assertIn(("origin", [0.0, 0.0, 0.0], ["island", "countertop"]), got)
        self.assertIn(("point", [1.2, -0.3, 0.0], ["fridge"]), got)
        self.assertIn(("point", [0.0, 0.0, 5.0], ["key", "area"]), got)
        self.assertIn(("point", [0.0, 0.0, 3.0], ["camera"]), got)
        self.assertEqual(len(got), 4)  # "looking at the origin (0, 0, 0)" is a target

    def test_examples_keyframes_and_rotations_ask_nothing(self):
        p = plan("Add a rim light (e.g., at (-1.5, 0, 0)). Set the keyframe at frame 1 to (0, 0, 3). "
                 "Set rotation = (0, 0, 90).")
        self.assertEqual(G.asked_places(p, 0), [])

    def test_a_hedged_point_is_not_read(self):
        for hedged in ("at about (1, 0, 0)", "near (1, 0, 0)", "roughly at (1, 0, 0)", "for example at (1, 0, 0)",
                       "placed somewhere at (1, 0, 0)"):
            self.assertEqual(G.asked_places(plan('Add a sphere named "Ball" %s.' % hedged), 0), [], hedged)
        self.assertEqual([a["point"] for a in G.asked_places(plan('Add a sphere named "Ball" at (1, 0, 0).'), 0)],
                         [[1.0, 0.0, 0.0]])
        # nor anything in a clause that animates, nor a place in a relation's clause that keyframes
        self.assertEqual(G.asked_places(plan('Move the sphere named "Ball" to (1, 0, 0) and animate it.'), 0), [])
        self.assertEqual(G.asked_relations(plan('At frame 1 the camera named "Cam" is in front of the logo.'), 0), [])

    def test_a_name_wins(self):
        p = plan('Add a Sun lamp named "Sun_Lamp" at location (10, 10, 10).')
        self.assertEqual(G.asked_places(p, 0)[0]["words"], ["Sun_Lamp"])

    def test_a_type_in_parentheses_is_part_of_the_thing_and_ordinals_name_nothing(self):
        p = plan("Create three lights: Key (Spot) at (2, -2, 3), Fill (Area) at (-2, -2, 2).")
        self.assertEqual([a["words"] for a in G.asked_places(p, 0)], [["key", "spot"], ["fill", "area"]])
        self.assertEqual(G.asked_places(plan("Position the first lamp at (5, -3, 8)."), 0), [])

    def test_depth_and_relation(self):
        p = plan("Create a curve. Extrude the curve by 0.08 m. Add a plane behind the logo, size 2 m, name it "
                 "`Backplate`.")
        d = G.asked_depths(p, 0)
        self.assertEqual((d[0]["depth"], d[0]["words"][-1]), (0.08, "curve"))
        r = G.asked_relations(p, 0)
        self.assertEqual((r[0]["rel"], r[0]["a"], r[0]["b"]), ("behind", ["Backplate"], ["logo"]))
        self.assertEqual(G.asked_depths(plan("Extrude it by 0 m."), 0), [])  # nothing asked
        self.assertEqual(G.asked_depths(plan("Extrude the curve by -0.08 m."), 0)[0]["depth"], 0.08)

    def test_a_one_way_depth_and_an_extrude_value(self):
        """doubled_depth's reading (Nov 5): a depth is the thing's whole depth one way when the step gives a side, when
        a mesh, its faces or a plane is extruded, or when it asks a whole depth or thickness of anything but a curve or
        a text; never Blender's extrude value of a curve or a text, which goes both ways, a range, a random depth, a
        value to record or a bevel depth. The held-out steps' and the stored ones' wordings."""
        for words, why in (("Create a curve. Extrude the curve by 0.08 m in the negative Z direction (or use a simple "
                            "extrusion modifier).", "side"),
                           ("Extrude the text by 0.1 m downward.", "side"),
                           ("Extrude the mesh to a depth of 0.15 m (set the solidify modifier thickness to 0.15).",
                            "mesh"),
                           ("Convert the imported curve to a mesh and extrude it by 0.12 meters.", "mesh"),
                           ("Select all faces, and extrude along the local Z axis by 0.12 meters.", "mesh"),
                           ("Extrudes the plane to a cabinet height of 0.9 m.", "mesh"),
                           ('Give the slab named "Base" a thickness of 0.05 m.', "whole"),
                           ("Extrude the curve by 0.08 m.", None),
                           ("Set the Text curve's extrude to 0.1 m and bevel depth to 0.015 m.", None),
                           ("Adds a 3D Text object with font Lato Light and extrusion 0.1 m.", None),
                           ("Creates a Text object, sets its font, extrusion to 0.12 meters.", None),
                           ("Randomizes extrusion depth per character between 0.05 m and 0.2 m.", None),
                           ("Record its font file path and its extrusion value (0.1 m).", None),
                           ("Converts the curve objects to mesh and then to 3D text objects with a bevel depth of 0.1 "
                            "meters.", None),
                           ("Add a plane named Floor and a text extruded by 0.1 m.", None)):
            with self.subTest(words):
                d = G.asked_depths(plan(words), 0)
                self.assertEqual(len(d), 1)
                self.assertEqual(d[0]["one_way"], why)
                self.assertEqual(G.asked_doubled(plan(words), 0), d if why else [])

    def test_what_the_independent_checks_read_as_one_way_is_not(self):
        """Nov 6: a rotation's axis or a later move after the length said no side, a plane a text stands on or a facing
        verb said no mesh, and "both directions" is no one way; every one of these 8 correct pieces failed
        doubled_depth in both Blenders. The side right after the length still counts, and so do the held-out
        readings (test_only_the_readers_that_passed_the_held_out_check_gate)."""
        for words in ('Add a 3D text named "Sign" reading "OPEN". Extrude the text 0.05 m and rotate it 90 degrees '
                      'about +X so it stands upright.',
                      'Add a text named "Title" reading "HELLO", extrude it 0.02 m and move it down to z = 0.5.',
                      'Add a text named "Logo" reading "ACME", rotate it to face the camera and extrude it 0.03 m.',
                      'Place a text named "Menu" on the board plane and extrude it 0.01 m.',
                      'Add a 3D text named "Title" reading "Hi" on a floor plane, extruded by 0.1 m.',
                      'Create a text object named "Title" above the ground plane and extrude it 0.05 m.',
                      'Add a curve named "Ribbon" lying on the plane and extrude it 0.04 m.',
                      'Extrude the plane named "Slab" 0.05 m in both directions to make a 0.1 m thick slab.'):
            with self.subTest(words):
                d = G.asked_depths(plan(words + " " + MARK), 0)
                self.assertEqual(len(d), 1)
                self.assertIsNone(d[0]["one_way"])
        for words, why in (("Extrude the curve by 0.08 m in the negative Z direction.", "side"),
                           ("Extrude the text by 0.1 m, downward.", "side"),
                           ("Extrude the text 0.05 m along -Z.", "side"),
                           ("Select the faces and extrude them by 0.1 m.", "mesh"),
                           ("Place the box on the floor, then extrude the plane by 0.2 m.", "mesh")):
            with self.subTest(words):
                self.assertEqual(G.asked_depths(plan(words + " " + MARK), 0)[0]["one_way"], why)

    def test_a_side_after_a_comma_a_bracket_or_an_adverb(self):
        """The second checks (Nov 6): a side given after a comma, a bracket or a word that is no verb of its own still
        says one way (the round's reader read these six; the independent checks' repair had dropped them), and a later
        bevel's "each side" is no both ways; "and" or "then" before the side still says none."""
        for words in ("Extrude the logo curve by 0.08 m, only in the negative Z direction.",
                      "Extrude the logo curve by 0.08 m, pointing in the negative Z direction.",
                      "Extrude the logo curve 0.08 m straight down.",
                      "Extrude the logo curve by 0.08 m (in the negative Z direction).",
                      "Extrude the logo curve by 0.08 m going downward.",
                      "Extrude the text 0.1 m downward, then bevel each side by 2 mm."):
            with self.subTest(words):
                self.assertEqual([d["one_way"] for d in G.asked_depths(plan(words + " " + MARK), 0)], ["side"])
        for words in ("Extrude the text 0.05 m, then move it down to z = 0.5.",
                      "Extrude the text 0.05 m and turn it to face -Z.",
                      "Extrude the plane named \"Slab\" 0.05 m, equally in both directions.",
                      "Extrude the plane named \"Slab\" 0.05 m (both ways)."):
            with self.subTest(words):
                self.assertEqual([d["one_way"] for d in G.asked_depths(plan(words + " " + MARK), 0)], [None])

    def test_a_doubled_mesh_is_told_without_the_curves_fact(self):
        down = plan('Extrude the plane named "chimera_slab" by 0.1 m downward. ' + MARK)
        for t, form in (("MESH", G.DOUBLED_MESH_TELL), ("FONT", G.DOUBLED_TELL), ("CURVE", G.DOUBLED_TELL)):
            rec = {"geom": {"objects": [{"n": "chimera_slab", "t": t, "lo": [0, 0, -0.1], "hi": [1, 1, 0.1],
                                         "faces": 6}]}, "measure": {"objects": []}}
            (state, line), = G.doubled_states(G.asked_doubled(down, 0), rec)
            self.assertEqual(state, "fault")
            self.assertTrue(line.endswith(form.rsplit("%s", 1)[-1].split("m at its thinnest")[-1]), (t, line))
            self.assertEqual("curve's or a text's" in line, t != "MESH", line)

    def test_a_row_start_a_plain_bevel_and_a_thin_depth_ask_nothing(self):
        # the step-6 checker's correct pieces that failed: an Array fence "starting at" a point, a card's "vertex
        # bevel of 0.004 m" and a 0.76 mm credit card, which the geometry line's 1 mm can't tell from flat
        fence = plan('Add a fence named "Fence" of 10 posts, 0.5 m apart along X, starting at (0, 0, 0).')
        self.assertEqual(G.asked_places(fence, 0), [])
        for words in ("beginning at", "ending at", "starts from"):
            self.assertEqual(G.asked_places(plan('Add a row of posts named "Posts" %s (2, 0, 0).' % words), 0), [])
        self.assertEqual(len(G.asked_places(plan('Add a post named "Post" placed at (2, 0, 0).'), 0)), 1)
        card = plan('Make a flat plane named "Card" and round its corners with a vertex bevel of 0.004 m.')
        self.assertEqual(G.asked_depths(card, 0), [])
        cable = G.asked_depths(plan('Give the curve named "Cable" a bevel depth of 0.01 m.'), 0)
        self.assertEqual([a["depth"] for a in cable], [0.01])  # a curve's bevel depth is one
        thin = plan('Add a credit card named "Card", with a thickness of 0.76 mm.')
        self.assertEqual(G.asked_depths(thin, 0), [])
        self.assertEqual(G.asked_depths(plan('Solidify the plane named "Sheet" by -1 mm.'), 0), [])  # either way
        self.assertEqual([a["depth"] for a in G.asked_depths(plan('Give "Sheet" a thickness of 2 mm.'), 0)], [0.002])
        # a tell writes a small depth to the millimetre, not as 0 m
        sheet = G.asked_depths(plan('Give the plane named "Sheet" a thickness of 4 mm.'), 0)
        (state, line), = G.depth_states(sheet, probe([box("Sheet", (-1, -1, 0), (1, 1, 0), faces=1)]))
        self.assertEqual((state, line), ("fault", "the step asks for a depth of 0.004 m, but Sheet has 1 faces and is 0 m "
                                                  "at its thinnest"))

    def test_a_thing_another_step_makes_is_not_asked_of_this_one(self):
        p = plan("Create a sofa (2 m x 0.9 m x 0.8 m) named \"Sofa\".",
                 "Move the sofa to (1, 0, 0). Place a lamp named \"Lamp\" at (2, 0, 0). Set the sofa named \"Sofa\" "
                 "at (3, 0, 0).", titles=["Sofa", "Lamp"])
        self.assertEqual([a["words"] for a in G.asked_places(p, 1)], [["Lamp"]])  # quoted or not, s1's sofa isn't


class FaultTests(unittest.TestCase):
    """The faults on hand-made geometry lines (probe: one version's direct run)."""

    def test_a_box_on_the_floor_or_centred_passes_and_a_lifted_one_fails(self):
        asked = G.asked_places(KITCHEN, 0)
        ok = probe([box("chimera_island", (-1.2, -0.45, 0), (1.2, 0.45, 0.92)),
                    box("chimera_fridge", (0.8, -0.65, -0.9), (1.6, 0.05, 0.9))],
                   [("chimera_key_light", "LIGHT", (0, 0, 5))])
        self.assertEqual(G.place_faults(asked, ok), [])
        lifted = probe([box("chimera_island", (-1.2, -0.45, 0.46), (1.2, 0.45, 1.38)),
                        box("chimera_fridge", (0.8, -0.65, 0), (1.6, 0.05, 1.8))],
                       [("chimera_key_light", "LIGHT", (0, 0, 4))])
        bad = dict(G.place_faults(asked, lifted))
        self.assertEqual(sorted(bad), [0, 2])  # the island (raised by half its height) and the light
        self.assertNotIn("places it at", bad[0])  # never the step's own phrase
        self.assertEqual(bad[0], "the step puts the island countertop at (0, 0, 0), but chimera_island's box runs "
                                 "from (-1.2, -0.45, 0.46) to (1.2, 0.45, 1.38): neither its centre, the middle of its "
                                 "bottom nor its origin is there")
        self.assertEqual([s for s, _ in G.place_states(asked, lifted)], ["fault", "fits", "fault", "unmatched"])

    def test_an_origin_counts_only_inside_its_own_box(self):
        asked = G.asked_places(plan('Add a panel named "Panel" and position it at (2, 0, 0).'), 0)
        corner = box("Panel", (2, 0, 0), (3, 0.1, 2), loc=[2.0, 0.0, 0.0])  # placed by a corner origin
        self.assertEqual(G.place_faults(asked, probe([corner])), [])
        applied = box("Panel", (2, 0, 3), (3, 0.1, 5), loc=[2.0, 0.0, 0.0])  # X27's: a transform applied after it
        self.assertEqual(len(G.place_faults(asked, probe([applied]))), 1)

    def test_unnamed_animated_or_moving_things_are_not_judged(self):
        asked = G.asked_places(KITCHEN, 0)
        self.assertEqual(G.place_faults(asked, probe([box("Cube.001", (5, 5, 5), (6, 6, 6))])), [])
        self.assertEqual(G.place_faults(asked, probe([box("chimera_island", (5, 5, 5), (6, 6, 6), anim=1)])), [])
        self.assertEqual(G.place_faults(asked, probe([box("chimera_island", (5, 5, 5), (6, 6, 6))],
                                                     moving=["chimera_island"])), [])
        # a light parented to a turning empty: its place at this frame says nothing either
        self.assertEqual(G.place_faults(asked, probe([], [("chimera_key_light", "LIGHT", (3, 0, 0))],
                                                     moving=["chimera_key_light"])), [])
        self.assertEqual(len(G.place_faults(asked, probe([], [("chimera_key_light", "LIGHT", (3, 0, 0))]))), 1)

    def test_on_the_floor_is_recorded_never_a_fault(self):
        asked = G.asked_places(plan('Add a lamp pole named "Pole". Place the pole on the floor.'), 0)
        self.assertEqual([a["kind"] for a in asked], ["floor"])
        self.assertEqual(G.place_states(asked, probe([box("Pole", (0, 0, 0.5), (0.1, 0.1, 2))])), [("floor", False)])
        self.assertEqual(G.place_states(asked, probe([box("Pole", (0, 0, 0), (0.1, 0.1, 2))])), [("floor", True)])
        self.assertEqual(G.place_faults(asked, probe([box("Pole", (0, 0, 0.5), (0.1, 0.1, 2))])), [])

    def test_a_flat_curve_fails_and_one_with_faces_or_instances_passes(self):
        asked = G.asked_depths(plan("Extrude the curve by 0.08 m."), 0)
        flat = probe([box("Pulse_Curve", (0, 0, 0), (2, 0.7, 0), t="CURVE", faces=0)])
        deep = probe([box("Pulse_Curve", (0, 0, -0.08), (2, 0.7, 0.08), t="CURVE", faces=900)])
        placer = probe([box("Pulse_Curve", (0, 0, 0), (2, 0.7, 0), t="CURVE", faces=0, inst=40)])
        self.assertEqual(G.depth_faults(asked, flat), [(0, "the step asks for a depth of 0.08 m, but Pulse_Curve has "
                                                           "0 faces and is 0 m at its thinnest")])
        self.assertEqual(G.depth_faults(asked, deep), [])
        self.assertEqual(G.depth_faults(asked, placer), [])  # a curve that places instances is no flat extrusion
        # an animated text still has a depth (a depth is frame-independent)
        spun = probe([box("Pulse_Curve", (0, 0, 0), (2, 0.7, 0), t="CURVE", faces=0, anim=1)])
        self.assertEqual(len(G.depth_faults(asked, spun)), 1)

    def test_a_depth_extruded_both_ways_fails_doubled_depth_and_one_way_passes(self):
        """The fourth smoke's bad example: "Extrude the curve by 0.08 m in the negative Z direction" and a text with
        extrude 0.08, z -0.08..0.08 (0.16 m thick). Extruded 0.04 and moved down, solidified 0.08 one way, or any
        other thickness (a 1 m stand-in) passes; a flat one is flat_extrusion's, an instancer no extrusion; a curve's
        bevel counts on both sides."""
        asked = G.asked_doubled(plan('Create a text named "Pulse_Curve". Extrude the curve by 0.08 m in the negative '
                                     'Z direction.'), 0)
        self.assertEqual([a["depth"] for a in asked], [0.08])

        def text(lo, hi, faces=1035, **kw):
            return probe([box("Pulse_Curve", (0, 0, lo), (2, 0.7, hi), t="FONT", faces=faces, **kw)])
        self.assertEqual(G.doubled_states(asked, text(-0.08, 0.08)), [(
            "fault", "the step asks for a depth of 0.08 m, but Pulse_Curve is 0.16 m at its thinnest, twice that: a "
                     "curve's or a text's extrude value goes both ways from it, so the depth is twice the value")])
        for lo, hi, kw in ((-0.08, 0.0, {}), (-0.04, 0.04, {}), (-0.5, 0.5, {}), (0.0, 0.0, {"faces": 0}),
                           (-0.08, 0.08, {"inst": 12}), (-0.09, 0.09, {"curve": {"extrude": 0.08, "bevel": 0.05}})):
            with self.subTest(lo=lo, hi=hi, kw=kw):
                self.assertEqual(G.doubled_states(asked, text(lo, hi, **kw)), [("fits", None)])
        bevelled = text(-0.09, 0.09, curve={"extrude": 0.08, "bevel": 0.01})  # 0.18 less 2 x 0.01
        self.assertEqual(G.doubled_states(asked, bevelled)[0][0], "fault")
        self.assertEqual(G.doubled_states(asked, probe([])), [("unmatched", None)])
        # a mesh asked a whole depth: twice it fails, the depth passes
        mesh = G.asked_doubled(plan("Rename it Acme_Logo. Extrude the mesh to a depth of 0.15 m."), 0)
        self.assertEqual(G.doubled_states(mesh, probe([box("Acme_Logo", (-1, -1, -0.15), (1, 1, 0.15))]))[0][0],
                         "fault")
        self.assertEqual(G.doubled_states(mesh, probe([box("Acme_Logo", (-1, -1, -0.15), (1, 1, 0))])),
                         [("fits", None)])

    def test_a_plane_inside_the_logo_fails_and_one_behind_or_below_passes(self):
        asked = G.asked_relations(LOGO, 0)
        logo = box("Acme_Logo", (-1, -1, -0.15), (1, 1, 0))
        inside = probe([logo, box("Backplate", (-1, -1, -0.01), (1, 1, -0.01))])
        below = probe([logo, box("Backplate", (-1, -1, -0.16), (1, 1, -0.16))])
        behind = probe([logo, box("Backplate", (-1, 1.1, -1), (1, 1.1, 1))])
        through = probe([logo, box("Backplate", (-1, 0.1, -1), (1, 0.1, 1))])  # cuts through the flat logo
        self.assertEqual(G.relation_faults(asked, inside), [(0, (
            "the step puts the Backplate behind the logo, but Backplate (box -1, -1, -0.01 to 1, 1, -0.01) lies "
            "inside Acme_Logo's box (-1, -1, -0.15 to 1, 1, 0)"))])
        self.assertEqual(G.relation_faults(asked, below), [])
        self.assertEqual(G.relation_faults(asked, behind), [])
        self.assertEqual(len(G.relation_faults(asked, through)), 1)
        # two solids never nest (a thing in front of a curved backdrop is inside its box), nor does a light
        solid = probe([logo, box("Backplate", (-0.5, -0.5, -0.1), (0.5, 0.5, 0.1))])
        self.assertEqual(G.relation_faults(asked, solid), [])
        lit = G.asked_relations(plan('Add a light named "Rim" behind the logo.'), 0)
        self.assertEqual(G.relation_states(lit, probe([logo], [("Rim", "LIGHT", (0, 0, -0.05))])), [("fits", None)])

    def test_above_and_below_are_recorded_never_a_fault(self):
        asked = G.asked_relations(plan('Add a camera named "Cam" above the table.'), 0)
        table = box("Table", (-1, -1, 0), (1, 1, 0.8))
        self.assertEqual(G.relation_states(asked, probe([table], [("Cam", "CAMERA", (0, 0, 0.4))])),
                         [("recorded", False)])
        self.assertEqual(G.relation_states(asked, probe([table], [("Cam", "CAMERA", (0, 0, 3))])), [("recorded", True)])

    def test_a_relation_with_a_stand_in_is_skipped(self):
        # the third smoke's D29: s1 (the logo) was dropped, so s2's join printed a stand-in for it, and the plate
        # it is to stand behind sits inside the stand-in's cube
        asked = G.asked_relations(LOGO, 0)
        run = probe([box("chimera_logo_standin", (-1, -1, -1), (1, 1, 1)), box("Backplate", (-1, -1, 0), (1, 1, 0))])
        self.assertEqual(G.relation_states(asked, run, ["logo"]), [("stand_in", None)])
        self.assertEqual(G.relation_states(asked, run, ["chimera_logo_standin"]), [("stand_in", None)])
        self.assertEqual(G.relation_states(asked, run, ["floor"])[0][0], "fault")  # another key's stand-in
        self.assertEqual(G.relation_faults(asked, run, ["logo"]), [])

    def test_a_thing_of_parts_is_judged_as_a_whole(self):
        # the step-6 checker's fixtures: a table of a top and four unparented legs at (1, 0, 0), letters centred as a
        # word, each part away from the point on its own
        asked = G.asked_places(plan("Build a simple table at (1, 0, 0): a top 1.2 x 0.7 m on four legs."), 0)
        legs = [box("chimera_table_leg_%d" % (k + 1), (x - 0.025, y - 0.025, 0), (x + 0.025, y + 0.025, 0.71))
                for k, (x, y) in enumerate(((1.55, 0.3), (1.55, -0.3), (0.45, 0.3), (0.45, -0.3)))]
        top = box("chimera_table_top", (0.4, -0.35, 0.71), (1.6, 0.35, 0.75))
        self.assertEqual(G.place_states(asked, probe([top] + legs)), [("fits", None)])
        word = G.asked_places(plan('Spell "ECHO" with letters named "Word_E", "Word_C", "Word_H" and "Word_O", the '
                                   "whole word centred at the origin."), 0)
        letters = [box("chimera_Word_%s" % ch, (x - 0.3, -0.05, -0.35), (x + 0.3, 0.05, 0.35), t="FONT")
                   for ch, x in zip("ECHO", (-1.2, -0.4, 0.4, 1.2))]
        self.assertEqual([s for s, _ in G.place_states(word, probe(letters))], ["fits"])
        # the parts moved off the point still fail, and the tell names the part nearest it, not the first one
        moved = [dict(r, lo=[r["lo"][0] + 3, *r["lo"][1:]], hi=[r["hi"][0] + 3, *r["hi"][1:]]) for r in legs + [top]]
        (state, line), = G.place_states(asked, probe(moved))
        self.assertEqual(state, "fault")
        self.assertIn("chimera_table_leg_3's box", line)
        # a light, a camera or an empty is never part of the whole: lights round a point don't put one there
        lamps = G.asked_places(plan('Add a key light named "Key" at (0, 0, 3).'), 0)
        self.assertEqual([s for s, _ in G.place_states(lamps, probe([], [("Key", "LIGHT", (2, 0, 3)),
                                                                         ("Key.001", "LIGHT", (-2, 0, 3))]))],
                         ["fault"])

    def test_a_place_on_a_run_with_a_stand_in_is_recorded(self):
        # a vase stood on its dependency's table top: alone, the top is the stand-in's cube at the origin
        asked = G.asked_places(plan("Make a table.", 'Put a vase named "Vase" on the table top at (1, 0, 0.75).'), 1)
        run = probe([box("chimera_Vase", (-0.05, -0.05, 1), (0.05, 0.05, 1.3))])
        (state, line), = G.place_states(asked, run, stood_in=True)
        self.assertEqual(state, "stand_in")
        self.assertIn("chimera_Vase's box", line)
        self.assertEqual(G.place_faults(asked, run, stood_in=True), [])
        self.assertEqual(len(G.place_faults(asked, run)), 1)  # without a stand-in it is a fault
        fits = probe([box("chimera_Vase", (0.95, -0.05, 0.75), (1.05, 0.05, 1.05))])
        self.assertEqual(G.place_states(asked, fits, stood_in=True), [("fits", None)])

    def test_the_factory_cube_is_not_the_pieces(self):
        asked = G.asked_places(plan('Add a cube named "Cube" at (3, 0, 0).'), 0)
        p = probe([box("Cube", (-1, -1, -1), (1, 1, 1))])
        p["measure"]["objects"] = [{"n": "Cube", "t": "MESH", "f": 1, "loc": [0.0, 0.0, 0.0], "size": [2.0, 2.0, 2.0]}]
        self.assertEqual(G.place_states(asked, p), [("unmatched", None)])

    def test_tell_lines_are_short_and_name_only_numbers_and_names(self):
        long = "chimera_" + "very_long_name_" * 4  # 68 characters
        asked = G.asked_places(plan('Add a box named "%s" at (1, 2, 3).' % long), 0)
        line = G.place_faults(asked, probe([box(long, (10.123, -20.456, 30.789), (11, -19, 31.5))]))[0][1]
        self.assertLessEqual(len(line), G.TELL_CHARS)
        self.assertIn("(10.12, -20.46, 30.79)", line)
        self.assertFalse(any(v in line for v in blenders.VERSIONS))
        a, b = "chimera_backplate_for_the_studio_logo", "chimera_studio_logo_with_bevelled_edges"  # quoted: 41 at most
        rel = G.asked_relations(plan('Add a plate named "%s" behind the "%s".' % (a, b)), 0)
        rows = [box(a, (-1234.5, -1234.5, -0.01), (1234.5, 1234.5, -0.01)),
                box(b, (-1234.5, -1234.5, -1000.25), (1234.5, 1234.5, 1000.25))]
        nested = G.relation_faults(rel, probe(rows))[0][1]
        self.assertLessEqual(len(nested), G.TELL_CHARS)
        self.assertIn("…", nested)  # the names cut to fit


class FormTests(unittest.TestCase):
    """The tell lines' fixed wording, the gated readers and the module's import."""

    def test_the_forms_are_ours_and_known_to_the_echo_check(self):
        self.assertEqual(G.TELL_FORMS, ("neither its centre, the middle of its bottom nor its origin is there",
                                        "the step asks for a depth of",
                                        "m at its thinnest, twice that: a curve's or a text's extrude value goes both "
                                        "ways from it, so the depth is twice the value",  # doubled_depth's (Nov 5)
                                        "m at its thinnest, twice that: its whole depth, from one side to the other, "
                                        "is to be the step's value"))  # ... for a mesh (Nov 6)
        self.assertEqual(BG.TELL_FORMS[-len(G.TELL_FORMS):], G.TELL_FORMS)  # the gate's, which echoed_note reads
        for form in G.TELL_FORMS:
            self.assertGreaterEqual(len(H._WORD.findall(form)), H.NOTE_MIN)
            self.assertEqual(H.echoed_note("## Notes\n\nassumed: " + form + ".\n" + MARK), "failure_line", form)
        # never Chimera's own words, which a reply may quote
        from contract import texts
        rule = texts.fill(texts.MODE_BLENDER, sid="s1")
        for form in G.TELL_FORMS:
            n = min(H.NOTE_N, len(H._WORD.findall(form)))
            self.assertFalse(H.runs(form, n) & H.runs(rule, n), form)
        # a piece that just does the step repeats none of them
        self.assertIsNone(H.echoed_note(MARK + "\nimport bpy\nlogo.location = (0, 0, 0)  # at the origin\n"
                                               "curve.data.extrude = 0.04  # 0.08 m deep\n"))

    def test_only_the_readers_that_passed_the_held_out_check_gate(self):
        self.assertEqual(G.GATED, frozenset(r for r, c in G.HELD_OUT.items() if c["misread"] <= G.MISREADS))
        # nested: 8 misreads of 15; doubled_depth (Nov 5): 1 of 9, s2 extruding s1's "Leaf" (flat_extrusion's too)
        self.assertEqual(G.GATED, {"place_mismatch", "flat_extrusion", "doubled_depth"})
        self.assertEqual(set(G.HELD_OUT), {"place_mismatch", "flat_extrusion", "nested", "doubled_depth"})
        self.assertTrue(set(G.HELD_OUT) <= set(BG.SOFT_MEASURED))

    def test_the_readers_still_read_what_the_held_out_check_read(self):
        """The readers over every Blender step of the helper's stored plans outside the smoke runs' seeds: as many
        readings as the held-out check read and judged (HELD_OUT), so a change to a reader means reading them
        again. Skipped where those files aren't (helper-model/data and the smoke runs aren't published)."""
        raw = sorted(glob.glob(os.path.join(_paths.REPO, "helper-model", "data", "raw", "*plans*.jsonl")))
        gen = [os.path.join(_paths.HERE, "data", "gen", r, "tasks.jsonl") for r in ("smoke", "smoke2", "smoke3")]
        if not raw or not all(os.path.exists(p) for p in gen):
            self.skipTest("the helper's stored plans or the smoke runs aren't here")
        smoke = set()
        for p in gen:
            with open(p, encoding="utf-8") as f:
                smoke.update(json.loads(line)["key"] for line in f if line.strip())
        steps, seen = [], set()
        for path in raw:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line)
                    p = _plan(r.get("target")) or _plan(r.get("reply"))
                    if not p or r["seed_id"] in smoke:
                        continue
                    for i, s in enumerate(p["steps"]):
                        if s.get("kind") == "blender" and (s.get("title"), s.get("instructions")) not in seen:
                            seen.add((s.get("title"), s.get("instructions")))
                            steps.append((p, i))
        self.assertEqual(len(steps), 261)
        got = {"place_mismatch": sum(len(G.asked_places(p, i)) for p, i in steps),
               "flat_extrusion": sum(len(G.asked_depths(p, i)) for p, i in steps),
               "nested": sum(len(G.asked_relations(p, i)) for p, i in steps),
               "doubled_depth": sum(len(G.asked_doubled(p, i)) for p, i in steps)}
        self.assertEqual(got, {r: c["read"] for r, c in G.HELD_OUT.items()})

    def test_either_module_can_be_imported_first(self):
        for first in ("geometry", "blender_gate"):
            code = ("import sys; sys.path.insert(0, %r)\nfrom datagen import %s\nfrom datagen import blender_gate, "
                    "geometry\nn = len(geometry.TELL_FORMS)\nassert n == 4 and blender_gate.TELL_FORMS[-n:] == "
                    "geometry.TELL_FORMS\n") % (_paths.HERE, first)
            p = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=60,
                               env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(p.returncode, 0, p.stderr[-2000:])


def _plan(text):
    """A helper plan's JSON (its "target", else its "reply"), or None."""
    if not text:
        return None
    try:
        p = json.loads(text)
    except ValueError:
        a, b = text.find("{"), text.rfind("}")
        try:
            p = json.loads(text[a:b + 1]) if 0 <= a < b else None
        except ValueError:
            return None
    ok = isinstance(p, dict) and isinstance(p.get("steps"), list) and all(isinstance(s, dict) for s in p["steps"])
    return p if ok else None


# ---------------------------------------------------------------- real Blender

CURVES = MARK + '''
import bpy
bpy.ops.curve.primitive_bezier_curve_add(location=(0, 0, 0))
bpy.context.active_object.name = "bevelled"
bpy.context.active_object.data.bevel_depth = 0.05
bpy.ops.object.text_add(location=(3, 0, 0))
bpy.context.active_object.name = "text"
bpy.context.active_object.data.extrude = 0.05
bpy.ops.curve.primitive_bezier_curve_add(location=(0, 3, 0))
bpy.context.active_object.name = "plain"
bpy.ops.curve.primitive_nurbs_path_add(location=(0, 6, 0))
bpy.context.active_object.name = "path"
bpy.ops.surface.primitive_nurbs_surface_surface_add(location=(0, 9, 0))
bpy.context.active_object.name = "surface"
'''
MESHES = MARK + '''
import bpy
bpy.ops.mesh.primitive_cube_add(size=1, location=(1, 2, 0.5))
bpy.context.active_object.name = "chimera_box"
bpy.context.active_object.rotation_euler.z = 0.4
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.3, location=(-1, 0, 0.3))
s = bpy.context.active_object
s.name = "chimera_ball"
s.modifiers.new("sub", "SUBSURF")
bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=2, location=(0, -1, 1))
bpy.context.active_object.name = "chimera_leg"
bpy.context.active_object.parent = s
bpy.ops.object.light_add(type="AREA", location=(0, 0, 4))
bpy.ops.object.camera_add(location=(0, -6, 2))
bpy.context.scene.camera = bpy.context.active_object
'''
# The curve block the measuring gained in round 6 and the one call it changed: taken out again, the measuring as it was
_CURVE_BLOCK = BG.MEASURE_EPILOGUE[BG.MEASURE_EPILOGUE.index("            # A curve's, a text's and a surface's box"):
                                   BG.MEASURE_EPILOGUE.index("        finally:\n            sys.stdout.flush()")]
TODAY = BG.MEASURE_EPILOGUE.replace(_CURVE_BLOCK, "").replace("        shapes = {}\n", "").replace(
    "shapes.get(o.as_pointer(), ev.bound_box)", "ev.bound_box")
INSTANCES = MARK + '''
import bpy
bpy.ops.curve.primitive_bezier_curve_add(location=(0, 0, 0))
bpy.context.active_object.name = "bevelled"
bpy.context.active_object.data.bevel_depth = 0.05
bpy.ops.mesh.primitive_plane_add(location=(0, -5, 0))
host = bpy.context.active_object
host.name = "host"
bpy.ops.mesh.primitive_cube_add(size=0.2, location=(9, 9, 9))
leaf = bpy.context.active_object
leaf.name = "leaf"
host.instance_type = "VERTS"
leaf.parent = host
bpy.ops.object.empty_add(location=(0, 0, 5))
spinner = bpy.context.active_object
spinner.name = "spinner"
spinner.keyframe_insert("rotation_euler", frame=1)
bpy.ops.mesh.primitive_cube_add(size=0.5, location=(3, 0, 0))
rider = bpy.context.active_object
rider.name = "rider"
rider.parent = spinner
bpy.ops.mesh.primitive_cube_add(size=0.5, location=(0, 3, 0))
aimed = bpy.context.active_object
aimed.name = "aimed"
aimed.constraints.new("TRACK_TO").target = spinner
bpy.ops.curve.primitive_bezier_circle_add(radius=2, location=(0, 0, 0))
bpy.context.active_object.name = "track"
bpy.ops.object.light_add(type="POINT", location=(0, 0, 0))
lamp = bpy.context.active_object
lamp.name = "follower"
lamp.constraints.new("FOLLOW_PATH").target = bpy.data.objects["track"]
'''
MANY = MARK + '''
import bpy
bpy.data.objects.remove(bpy.data.objects["Cube"])
for k in range(61):
    bpy.ops.mesh.primitive_cube_add(size=0.1, location=(k * 0.2, 0, 0))
    bpy.context.active_object.name = "chimera_part_%02d" % k
'''
# The refuter's synthetic correct pieces (round 5's geometry refuter): a right piece passes every reader
SYNTH = [
    ("text in front of a curved studio backdrop",
     'Add a curved studio backdrop named "Backdrop" and a 3D text named "Title" in front of the backdrop.',
     '''import bpy, math
verts, faces = [], []
pts = [(0, -3, 0), (0, 0, 0)] + [(0, 0.5 * math.sin(a), 0.5 - 0.5 * math.cos(a))
                                 for a in [math.radians(15 * k) for k in range(1, 7)]] + [(0, 0.5, 3)]
for x in (-3, 3):
    for (_, y, z) in pts:
        verts.append((x, y, z))
n = len(pts)
for k in range(n - 1):
    faces.append((k, k + 1, n + k + 1, n + k))
me = bpy.data.meshes.new("Backdrop")
me.from_pydata(verts, [], faces)
o = bpy.data.objects.new("Backdrop", me)
bpy.context.scene.collection.objects.link(o)
c = bpy.data.curves.new("Title", "FONT")
c.body = "Hi"
c.extrude = 0.05
c.align_x = "CENTER"
t = bpy.data.objects.new("Title", c)
bpy.context.scene.collection.objects.link(t)
t.location = (0, -1.0, 0.0)
t.rotation_euler = (math.radians(90), 0, 0)
'''),
    ("an off-centre logo placed at the origin by its origin",
     'Import the logo, name it "Acme_Logo" and place it at the world origin.',
     '''import bpy
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
o = bpy.context.active_object
o.name = "Acme_Logo"
for v in o.data.vertices:
    v.co.x = v.co.x * 0.3 + 0.2
    v.co.y = v.co.y * 0.2 - 0.15
    v.co.z = v.co.z * 0.0
o.location = (0, 0, 0)
'''),
    ("a text at the origin, left and baseline aligned",
     'Add a text object named "Pulse_Text" with the body "Pulse" and place it at the world origin. Extrude it by '
     '0.1 m.',
     '''import bpy
c = bpy.data.curves.new("Pulse_Text", "FONT")
c.body = "Pulse"
c.extrude = 0.1
o = bpy.data.objects.new("Pulse_Text", c)
bpy.context.scene.collection.objects.link(o)
o.location = (0, 0, 0)
'''),
    ("a text at the origin, centred",
     'Add a text object named "Pulse_Text" with the body "Pulse" and place it at the world origin. Extrude it by '
     '0.1 m.',
     '''import bpy
c = bpy.data.curves.new("Pulse_Text", "FONT")
c.body = "Pulse"
c.extrude = 0.1
c.align_x = "CENTER"
c.align_y = "CENTER"
o = bpy.data.objects.new("Pulse_Text", c)
bpy.context.scene.collection.objects.link(o)
'''),
    ("a mesh with its origin at a corner, placed at the point",
     'Add a wall panel named "Panel" and position it at (2, 0, 0).',
     '''import bpy
me = bpy.data.meshes.new("Panel")
me.from_pydata([(0, 0, 0), (1, 0, 0), (1, 0, 2), (0, 0, 2), (0, 0.1, 0), (1, 0.1, 0), (1, 0.1, 2), (0, 0.1, 2)], [],
               [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (3, 2, 6, 7), (0, 3, 7, 4), (1, 2, 6, 5)])
o = bpy.data.objects.new("Panel", me)
bpy.context.scene.collection.objects.link(o)
o.location = (2, 0, 0)
'''),
    ("a lamp on the floor: the pole stands, the shade on top",
     'Add a floor lamp: a pole named "Lamp_Pole" and a shade named "Lamp_Shade". Place the lamp on the floor.',
     '''import bpy
bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=1.6, location=(0, 0, 0.8))
bpy.context.active_object.name = "Lamp_Pole"
bpy.ops.mesh.primitive_cone_add(radius1=0.25, radius2=0.15, depth=0.3, location=(0, 0, 1.75))
bpy.context.active_object.name = "Lamp_Shade"
'''),
    ("a rug on a thick floor slab",
     'Add a floor slab named "Floor" 0.2 m thick with its top at z = 0, then a rug named "Rug" on the floor.',
     '''import bpy
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, -0.1))
f = bpy.context.active_object
f.name = "Floor"
f.scale = (5, 5, 0.2)
bpy.ops.mesh.primitive_plane_add(size=2, location=(0, 0, 0.002))
bpy.context.active_object.name = "Rug"
'''),
    ("bevelled text, its bevel depth given",
     'Add a 3D text named "Title" reading "Hi" with a bevel depth of 0.02 m.',
     '''import bpy
c = bpy.data.curves.new("Title", "FONT")
c.body = "Hi"
c.bevel_depth = 0.02
o = bpy.data.objects.new("Title", c)
bpy.context.scene.collection.objects.link(o)
'''),
    ("a backplate behind an upright logo",
     'Add a logo named "Logo" standing upright, 0.15 m thick, and a plane named "Backplate" behind the logo.',
     '''import bpy, math
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 1))
l = bpy.context.active_object
l.name = "Logo"
l.scale = (2, 0.15, 1)
bpy.ops.mesh.primitive_plane_add(size=3, location=(0, 0.3, 1), rotation=(math.radians(90), 0, 0))
bpy.context.active_object.name = "Backplate"
'''),
]

# doubled_depth's (Nov 5): the fourth smoke's bad example (a text extruded 0.08, both ways) and two ways to extrude 0.08
# one way, in the negative Z: half of it moved down, and a flat curve with a Solidify one way
EXTRUDED = {
    "doubled": MARK + '''
import bpy
c = bpy.data.curves.new("Pulse_Curve", "FONT")
c.body = "Pulse"
c.extrude = 0.08
bpy.context.scene.collection.objects.link(bpy.data.objects.new("Pulse_Curve", c))
''',
    "moved": MARK + '''
import bpy
c = bpy.data.curves.new("Pulse_Curve", "FONT")
c.body = "Pulse"
c.extrude = 0.04
o = bpy.data.objects.new("Pulse_Curve", c)
o.location = (0, 0, -0.04)
bpy.context.scene.collection.objects.link(o)
''',
    "solidified": MARK + '''
import bpy
cu = bpy.data.curves.new("Pulse_Curve", "CURVE")
cu.dimensions = "2D"
cu.fill_mode = "BOTH"
sp = cu.splines.new("BEZIER")
sp.bezier_points.add(3)
for p, co in zip(sp.bezier_points, [(-1, -0.5, 0), (1, -0.5, 0), (1, 0.5, 0), (-1, 0.5, 0)]):
    p.co = co
    p.handle_left_type = p.handle_right_type = "VECTOR"
sp.use_cyclic_u = True
o = bpy.data.objects.new("Pulse_Curve", cu)
bpy.context.scene.collection.objects.link(o)
m = o.modifiers.new("chimera_depth", "SOLIDIFY")
m.thickness, m.offset = 0.08, -1.0
'''}
EXTRUDE_STEP = 'Create a text named "Pulse_Curve". Extrude the curve by 0.08 m in the negative Z direction.'

_tmp = None
_runs = {}  # name: {version: direct run record}


class _Chimera:
    binary = "/nonexistent/chimera"  # the direct run never calls Chimera


def _tool(script, binary, epilogue):
    """script with epilogue through pysandbox.run_tool (sandboxed, as the data generator runs a tool)."""
    r = pysandbox.run_tool({"script.py": script.rstrip("\n") + "\n" + epilogue}, binary,
                           ["-b", "--factory-startup", "--python-exit-code", "1", "--python", "script.py"],
                           timeout=180, work=os.environ.get("WM_SCRATCH"))
    return r


def setUpModule():
    global _tmp
    if not HAVE_BLENDER:
        return
    _tmp = tempfile.mkdtemp(prefix="test-datagen-geometry-", dir=blender_check.scratch_root())
    gb = BG.GateBlender(_Chimera(), blenders.VERSIONS, os.path.join(_tmp, "work"), 180.0, 120.0,
                        threading.BoundedSemaphore(4))
    os.makedirs(gb.work, exist_ok=True)
    pieces = dict({"synth%d" % k: MARK + "\n" + code for k, (_, _, code) in enumerate(SYNTH)},
                  instances=INSTANCES, many=MANY, **{"extruded_" + k: v for k, v in EXTRUDED.items()})
    jobs = [(k, v, b) for k in pieces for v, b in blenders.VERSIONS.items()]
    with ThreadPoolExecutor(4) as pool:
        for k, v, out in pool.map(lambda j: (j[0], j[1], gb._probe_one(pieces[j[0]], j[2], j[1])), jobs):
            _runs.setdefault(k, {})[v] = out


def tearDownModule():
    if _tmp:
        shutil.rmtree(_tmp, ignore_errors=True)


@unittest.skipUnless(HAVE_BLENDER, "needs Blender " + " and ".join(blenders.VERSIONS))
class BlenderTests(unittest.TestCase):
    """The measuring's curve sizes and the geometry line in real Blender."""

    def test_curves_texts_and_surfaces_are_sized_from_their_evaluated_mesh(self):
        for v, binary in blenders.VERSIONS.items():
            with self.subTest(v):
                now, before = (BG._marked_line(_tool(CURVES, binary, e)["output"], BG.MEASURE_MARK)
                               for e in (BG.MEASURE_EPILOGUE, TODAY))
                size = {r["n"]: r.get("size") for r in now["objects"]}
                old = {r["n"]: r.get("size") for r in before["objects"]}
                self.assertEqual(size["bevelled"], [2.04, 0.32, 0.1])  # 2.035 x 0.322 x 0.1, rounded
                self.assertEqual(old["bevelled"], [4.0, 2.0, 2.0])  # its bound_box
                self.assertEqual((size["text"][2], old["text"][2]), (0.1, 0.0))  # a text's depth
                for n in ("plain", "path", "surface", "Cube"):
                    self.assertEqual(size[n], old[n], n)

    def test_a_piece_of_meshes_measures_and_lists_as_it_did(self):
        self.assertNotIn("to_mesh", TODAY)
        self.assertNotEqual(TODAY, BG.MEASURE_EPILOGUE)
        for v, binary in blenders.VERSIONS.items():
            with self.subTest(v):
                lines = []
                for e in (BG.MEASURE_EPILOGUE, TODAY):
                    out = _tool(MESHES, binary, e)
                    self.assertEqual(out["exit"], 0, out["output"][-1500:])
                    lines.append([l for l in out["output"].split("\n") if l.startswith(BG.MEASURE_MARK)])
                self.assertEqual(len(lines[0]), 1)
                self.assertEqual(lines[0], lines[1])  # byte for byte
                m = BG._marked_line(lines[0][0], BG.MEASURE_MARK)
                self.assertEqual(json.dumps(BG._listed(m)), json.dumps(BG._listed(BG._marked_line(
                    lines[1][0], BG.MEASURE_MARK))))  # so the listing, and every judge's cache key, too
                self.assertTrue(m["groups"])  # the ball with its leg: a group, its box from the bound boxes

    def test_the_geometry_line_has_exact_boxes_curve_settings_and_instances(self):
        for v in blenders.VERSIONS:
            with self.subTest(v):
                g = _runs["instances"][v]["geom"]
                rows = {r["n"]: r for r in g["objects"]}
                b = rows["bevelled"]
                self.assertEqual([round(b["hi"][k] - b["lo"][k], 3) for k in range(3)], [2.035, 0.322, 0.1])
                self.assertEqual(b["curve"], {"extrude": 0.0, "bevel": 0.05, "dim": "3D", "fill": "FULL",
                                              "bevel_obj": False, "splines": 1})
                self.assertGreater(b["faces"], 0)
                self.assertNotIn("inst", b)  # its own mesh, listed as an instance of itself, isn't one
                self.assertEqual(rows["host"]["inst"], 4)  # a plane's four vertices instance the leaf
                self.assertEqual(rows["rider"]["parent"], "spinner")
                self.assertNotIn("anim", rows["rider"])  # its parent is animated, not it...
                self.assertEqual(sorted(g["moving"]), ["follower", "rider"])  # ...so it moves, as a path's follower
                self.assertNotIn("aimed", g["moving"])  # a Track To only turns it
                self.assertNotIn("spinner", rows)  # an empty: the measuring's
                self.assertEqual(rows["leaf"]["mats"], 0)

    def test_a_text_extruded_both_ways_fails_doubled_depth_and_one_way_passes(self):
        """Blender's extrude of a curve or a text goes both ways (the fourth smoke's bad example: 0.08 gives z -0.08 to
        0.08), so a step's 0.08 m in the negative Z made that way is 0.16 m thick in both versions; extruded 0.04 and
        moved down 0.04, or a flat curve with a Solidify of 0.08 one way, is 0.08 m from z -0.08 to 0, and passes."""
        asked = G.asked_doubled(plan(EXTRUDE_STEP), 0)
        for v in blenders.VERSIONS:
            with self.subTest(v):
                rows = {k: G.geom_rows(_runs["extruded_" + k][v]) for k in EXTRUDED}
                self.assertEqual([(r["lo"][2], r["hi"][2]) for r in rows["doubled"]], [(-0.08, 0.08)])
                self.assertEqual([(r["lo"][2], r["hi"][2]) for r in rows["moved"]], [(-0.08, 0.0)])
                self.assertEqual([(r["lo"][2], r["hi"][2]) for r in rows["solidified"]], [(-0.08, 0.0)])
                self.assertEqual(G.doubled_states(asked, _runs["extruded_doubled"][v])[0][0], "fault")
                for k in ("moved", "solidified"):
                    self.assertEqual(G.doubled_states(asked, _runs["extruded_" + k][v]), [("fits", None)], k)
                    self.assertFalse(G.depth_faults(G.asked_depths(plan(EXTRUDE_STEP), 0), _runs["extruded_" + k][v]))

    def test_the_geometry_line_is_cut_within_its_budget(self):
        for v in blenders.VERSIONS:
            with self.subTest(v):
                g = _runs["many"][v]["geom"]
                self.assertLessEqual(len(json.dumps(g, separators=(",", ":"), ensure_ascii=True)), BG.GEOM_BUDGET)
                self.assertLessEqual(len(g["objects"]), BG.GEOM_KEEP)
                self.assertEqual(g["cut"] + len(g["objects"]), 61)
                self.assertGreaterEqual(g["cut"], 1)
                self.assertEqual(g["objects"][0]["n"], "chimera_part_00")  # the chimera_ ones first, by name

    def test_the_refuters_correct_pieces_have_no_fault(self):
        for k, (title, words, _) in enumerate(SYNTH):
            p = plan(words)
            for v, run in _runs["synth%d" % k].items():
                with self.subTest(title=title, version=v):
                    self.assertEqual(run["exit"], 0, run.get("output_tail"))
                    states = (G.place_states(G.asked_places(p, 0), run) + G.depth_states(G.asked_depths(p, 0), run) +
                              G.relation_states(G.asked_relations(p, 0), run, run.get("stand_in_keys") or []))
                    self.assertNotIn("fault", [s for s, _ in states], states)
        # what they ask: the readers did read them
        asked = [(len(G.asked_places(plan(w), 0)), len(G.asked_depths(plan(w), 0)), len(G.asked_relations(plan(w), 0)))
                 for _, w, _ in SYNTH]
        self.assertEqual(asked, [(0, 0, 1), (1, 0, 0), (1, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0), (1, 0, 0),
                                 (0, 1, 0), (0, 0, 1)])  # "the lamp" names nothing: "lamp" tells no lamp apart
        states = G.place_states(G.asked_places(plan(SYNTH[4][1]), 0), _runs["synth4"]["5.2.2"])
        self.assertEqual(states, [("fits", None)])  # the panel by its corner origin


if __name__ == "__main__":
    unittest.main()
