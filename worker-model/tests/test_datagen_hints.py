"""datagen/hints.py against the real API dumps (data/rna/5.2.2.json and 5.0.1.json, made by those Blenders): the facts
for step texts that name nodes and classes come out per version with the differences marked "[newer only]" or
"[older only]" (checked against the dumps themselves, not against hand-copied lists), the 6,000-character cap holds
with the most-mentioned first, what earlier failures name comes first, failures are listed in every mode, no note
names a Blender version, the notes go only into the teacher's copy, and a reply that repeats them (or a failure line
only the teacher saw, less what Chimera's request says too and runs of numbers, or a version only the notes named, or
the notes' words for the Blenders and the sandbox) is told apart from ordinary code; after the third round of checks
(Nov 4), the Blender note no longer says the notes' words for the checks, and a tell line paired with the failed
candidate it quotes (Tell) leaves that candidate's own words out of the echo check; after the second smoke run's
audit, the newest failure lines are listed (and the newest failure's names get the facts first), and the gates' new
tell lines' fixed wording is ours to the echo check. After the third smoke run (Nov 4): a Blender step whose values
later steps use gets a note on ctx["values"] (by its title, and only with dependents), which is ours to the echo check
and shares no run with Chimera's Blender rule; and the facts leave out the sockets no script can reach (the shaders'
Weight) and mark the settings that show a hidden one, from a hand-made pair of dumps and, once data/rna has socket
availability, the real ones. No Blender runs here.

The step texts are hand-written test fixtures (each carries the mark), never training data; the values steps' titles
are the smoke runs' and the helper's plans' (training plans, not eval), with fixture instructions.
"""
import copy
import json
import re
import unittest
from unittest import mock

from tests import _paths  # noqa: F401
from datagen import hints as H
from runner import mock_ollama
from tools import rna_lint

MARK = mock_ollama.MARK
FACTS = rna_lint.Facts.load()
NEW, OLD = FACTS.versions[0], FACTS.versions[1]
# data/rna made by tools/rna_dump.py since Nov 4: every socket says whether a fresh node has it (a fourth field)
AVAILABILITY = all(len(s) > 3 for v in FACTS.versions for side in rna_lint.SIDES
                   for s in FACTS.node("ShaderNodeBsdfPrincipled", v)[side])

GLASS = ("Glass vase material", "Give chimera_vase a glass material with a Principled BSDF: Transmission Weight 1.0, "
         "Roughness 0.05, IOR 1.45. Drive its Base Color from a Noise Texture (scale 8) through a Color Ramp. " + MARK)
BEVEL = ("Soften the table", "Add a Bevel modifier to chimera_table (width 0.02 m, 3 segments, limit by angle) and a "
         "Subdivision Surface modifier at level 2 above it. " + MARK)
GLOW = ("Glow in the compositor", "Use the compositor: after the Render Layers node add a compositor glare (Fog Glow, "
        "threshold 0.8) and connect it to the Composite output. Set the view transform to AgX. " + MARK)


def plan(*steps):
    return {"title": "Fixture plan " + MARK, "kind": "blender", "summary": MARK,
            "steps": [{"id": "s%d" % (k + 1), "title": t, "kind": "blender", "instructions": ins, "depends_on": []}
                      for k, (t, ins) in enumerate(steps)]}


def facts_for(step, failures=()):
    return H.blender_facts(step[0] + "\n" + step[1], FACTS, failures)


def line(block, start):
    hits = [l for l in block.split("\n") if l.startswith(start)]
    if len(hits) != 1:
        raise AssertionError(f"{len(hits)} lines start with {start!r} in:\n{block}")
    return hits[0]


def top_items(s):
    """s split on ", " outside brackets and parentheses."""
    out, depth, cur = [], 0, ""
    k = 0
    while k < len(s):
        ch = s[k]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if depth == 0 and s.startswith(", ", k):
            out.append(cur)
            cur = ""
            k += 2
            continue
        cur += ch
        k += 1
    return out + ([cur] if cur else [])


def segment(entry, name):
    """The "inputs: ..." part of a node line, up to the next "; <name>:"."""
    m = re.search(r"(?:^|[;:] )" + name + r": (.*?)(?:; (?:inputs|outputs|properties): |$)", entry)
    return m.group(1) if m else ""


def versions_with(idname, side, socket, ident=None):
    """The versions with a socket of that name a script can reach (rna_lint.usable); with ident, that socket only
    (an identifier the facts don't show is the name, or none)."""
    def same(s):
        return s[0] == socket and (ident is None or s[1] == ident or ident == socket and s[1] == "")
    return {v for v in FACTS.versions if any(same(s) and rna_lint.usable(FACTS.node(idname, v), side, s)
                                             for s in (FACTS.node(idname, v) or {}).get(side, ()))}


def revealed(facts, idname, side, name, ident):
    """The settings that show socket (name, ident) where a fresh node hides it, from the first version whose dump
    names them (the node's "reveal"), or None."""
    for v in facts.versions:
        n = facts.node(idname, v) or {}
        for s in n.get(side, ()):
            if (s[0], s[1]) == (name, ident) and len(s) > 3 and not s[3] and name in n["reveal"][side]:
                return n["reveal"][side][name]
    return None


WORD = {NEW: "newer", OLD: "older"}


def mark_for(have):
    return "" if have == set(FACTS.versions) else " [" + ", ".join(WORD[v] for v in FACTS.versions if v in have) + \
        " only]"


class FactsPerVersionTests(unittest.TestCase):
    def assertSocketsMarked(self, entry, idname, side):
        """Every socket a script can reach is listed, none it can't (the shaders' Weight), each with its versions'
        mark and, where a fresh node hides it, the settings the dump says show it."""
        items = top_items(segment(entry, side))
        names = {s[0] for v in FACTS.versions for s in (FACTS.node(idname, v) or {}).get(side, ())
                 if rna_lint.usable(FACTS.node(idname, v), side, s)}
        seen = set()
        for it in items:
            m = re.match(r'(.*?)(?: \(or "([^"]*)"\))? \[', it)
            name, ident = m.group(1), m.group(2) or m.group(1)
            seen.add(name)
            want = mark_for(versions_with(idname, side, name, ident))
            if want:
                self.assertTrue(it.endswith(want), f"{it!r} should end with {want!r}")
            else:
                self.assertNotIn(" only]", it)
            shows = revealed(FACTS, idname, side, name, ident)
            if shows:
                mark = it[it.index(" (with "):]
                for setting in shows:
                    for prop, _, value in (p.partition("=") for p in setting.split("&")):
                        self.assertRegex(mark, r"\b%s (?:\S+ or )*%s\b" % (re.escape(prop), re.escape(value)), it)
            else:
                self.assertNotIn(" (with ", it)
        self.assertEqual(seen, names)
        return items

    def test_principled_bsdf_and_noise_texture(self):
        block = facts_for(GLASS)
        p = line(block, "- node Principled BSDF (ShaderNodeBsdfPrincipled): ")
        items = self.assertSocketsMarked(p, "ShaderNodeBsdfPrincipled", "inputs")
        self.assertIn("Thin Wall [bool] [newer only]", items)  # new in 5.2: 5.0.1 has no such input
        self.assertIn("Transmission Weight [float factor]", items)
        self.assertFalse(any(re.match(r"(Transmission|Specular) \[", it) for it in items))  # the old names
        self.assertIn("RANDOM_WALK_LEGACY [newer only]", segment(p, "properties"))
        n = line(block, "- node Noise Texture (ShaderNodeTexNoise): ")
        noise = self.assertSocketsMarked(n, "ShaderNodeTexNoise", "inputs")
        if AVAILABILITY:  # the dumps say which sockets a fresh node hides, and what shows them
            self.assertFalse(any(it.startswith("Weight [") for it in items))  # inputs["Weight"] is never there
            self.assertIn("Coat Weight [float factor]", items)
            self.assertIn("W [float] (with noise_dimensions 1D or 4D)", noise)
        else:  # an older dump can't tell: every socket, unmarked, as before
            self.assertIn("Weight [float]", items)
            self.assertIn("W [float]", noise)
        self.assertIn('Factor (or "Fac") [float]', top_items(segment(n, "outputs")))
        self.assertNotIn("noise_scale", block)  # the old texture class's property, a classic wrong guess
        self.assertIn("noise_type (MULTIFRACTAL, RIDGED_MULTIFRACTAL, HYBRID_MULTIFRACTAL, FBM, HETERO_TERRAIN)", n)
        line(block, "- node Color Ramp (ShaderNodeValToRGB): ")
        self.assertIn("interpolation (EASE, CARDINAL, LINEAR, B_SPLINE, CONSTANT)", line(block, "- ColorRamp: "))

    def test_bevel_and_subdivision_surface_modifiers(self):
        block = facts_for(BEVEL)
        b = line(block, "- BevelModifier: ")
        props = [re.match(r"[a-z_]+", it).group(0) for it in top_items(b[len("- BevelModifier: "):])]
        want = sorted({a for v in FACTS.versions for a in FACTS.dumps[v]["classes"]["BevelModifier"]["props"]})
        self.assertEqual(props, want)
        self.assertNotIn("offset", props)  # BevelModifier has width and offset_type, never offset or depth
        self.assertNotIn("depth", props)
        self.assertIn("limit_method (NONE, ANGLE, WEIGHT, VGROUP)", b)
        line(block, "- SubsurfModifier: ")  # "Subdivision Surface modifier" is the modifier...
        self.assertNotIn("GeometryNodeSubdivisionSurface", block)  # ...not the geometry node of that label
        self.assertNotIn("- SurfaceModifier", block)  # and "Surface modifier" inside it names nothing

    def test_compositor_glare(self):
        block = facts_for(GLOW)
        g = line(block, "- node Glare (CompositorNodeGlare): ")
        items = self.assertSocketsMarked(g, "CompositorNodeGlare", "inputs")
        self.assertIn("Type [menu]", items)  # the glare type is an input in 5.x, not a property
        self.assertIn('Threshold (or "Highlights Threshold") [float]', items)
        r = line(block, "- node Render Layers (CompositorNodeRLayers): ")
        outs = self.assertSocketsMarked(r, "CompositorNodeRLayers", "outputs")
        old_only = sorted(versions_with("CompositorNodeRLayers", "outputs", s[0]) == {OLD}
                          for s in FACTS.node("CompositorNodeRLayers", OLD)["outputs"])
        self.assertTrue(any(old_only), "the dumps differ in Render Layers' outputs")
        self.assertTrue(any(it.endswith("[older only]") for it in outs))
        self.assertIn("- Scene.compositing_node_group: a NodeTree", block)  # 5.x's compositor, from "compositor"
        self.assertIn("view_transform (", line(block, "- ColorManagedViewSettings: "))
        self.assertNotIn("CompositorNodeMixRGB", block)  # nothing the step doesn't name

    def test_engine_and_file_format_values_are_always_there(self):
        block = facts_for(("Wood floor", "Make a plain wooden floor. " + MARK))
        e = line(block, "- RenderSettings.engine (")
        live = FACTS.dumps[NEW]["dynamic_enums"]["RenderSettings.engine"]
        self.assertEqual(e, "- RenderSettings.engine (" + ", ".join(live) + ")")
        f = line(block, "- ImageFormatSettings.file_format (")
        new_only = [x for x in FACTS.dumps[NEW]["live_enums"]["ImageFormatSettings.file_format"]
                    if x not in FACTS.dumps[OLD]["live_enums"]["ImageFormatSettings.file_format"]]
        self.assertTrue(new_only)
        for x in new_only:
            self.assertIn(f"{x} [newer only]", f)
        self.assertIn("in another state also", f)  # FFMPEG and the like need another media_type first
        self.assertIn("media_type (IMAGE, MULTI_LAYER_IMAGE, VIDEO)", f)
        self.assertEqual(len(block.split("\n")), 3)  # the head and these two: the step named nothing

    def test_the_notes_for_a_blender_step(self):
        text = H.hints_for(plan(GLASS), 0, "blender", FACTS)
        lines = text.split("\n")
        notes = [H.FORMAT_NOTE, H.BLENDER_NOTE, *H.BLENDER_HABITS, H.VERSIONS_NOTE]
        self.assertEqual(lines[:len(notes)], notes)
        self.assertEqual(lines[len(notes)], H.facts_head(FACTS.versions))
        self.assertEqual(H.hints_for(plan(GLASS), 0, "blender", FACTS), text)  # the same every time
        self.assertEqual(H.hints_for(plan(GLASS), 0, "blender", None), "\n".join(notes))
        self.assertEqual(H.hints_for(plan(GLASS), 0, "python-script", FACTS), H.FORMAT_NOTE)
        self.assertEqual(H.hints_for(plan(GLASS), 0, "files", FACTS), H.FORMAT_NOTE + "\n" + H.FILES_NOTE)

    def test_the_blender_notes_say_what_the_gate_and_the_smoke_run_found(self):
        note = H.BLENDER_NOTE
        self.assertIn("no files outside its folder exist", note)
        self.assertIn('print("chimera: stand-in", key) is only for a key a missing dependency', note)
        self.assertIn("without the stand-in marker", note)  # a missing input file falls back without it
        cube, light, path = H.BLENDER_HABITS
        self.assertIn("size=1) makes a 1 m cube", cube)
        self.assertIn("size=2, makes a 2 m cube", cube)
        self.assertIn("local -Z", light)
        self.assertIn("180° about X points it up", light)
        self.assertIn("Follow Path", path)
        self.assertIn("own location", path)

    def test_no_note_names_a_blender_version(self):
        """Chimera's request names none of the checks' versions, so the teacher's copy doesn't either: the facts'
        marks, their header, the notes and the failure lines a version would be in."""
        # Thin Wall is only the newer's, a Render Layers output only the older's
        step = ("Glass and glow", GLASS[1] + " " + GLOW[1])
        fails = [FailuresTests.LINT, FailuresTests.CRASH,
                 dict(FailuresTests.LINT, message="Scene has no attribute 'x' in Blender 5.0.1 (Blender 5.2.2 has "
                                                  "no 'x') " + MARK)]
        text = H.hints_for(plan(step), 0, "blender", FACTS, fails)
        self.assertEqual(H.versions_named(text), set())
        for v in FACTS.versions:
            self.assertNotIn(v, text)
        self.assertIn("[newer only]", text)
        self.assertIn("[older only]", text)
        self.assertIn("in either Blender", text)  # the lint's "in Blender 5.2.2 or 5.0.1"
        self.assertIn("(the newer Blender)", text)  # the crash's runner
        self.assertIn("in the older Blender (the newer Blender has no 'x')", text)

    def test_failures_are_listed_in_every_mode(self):
        crash = dict(FailuresTests.CRASH, function="main", source="data = load()  " + MARK,
                     error="FileNotFoundError: [Errno 2] No such file or directory: 'cfg.json'",
                     runner="Python 3.13.1")
        tell = "File lines must be plain: File: src/app.py, not **File: src/app.py** " + MARK
        for mode, notes in (("python-script", [H.FORMAT_NOTE]), ("files", [H.FORMAT_NOTE, H.FILES_NOTE])):
            lines = H.hints_for(plan(GLASS), 0, mode, FACTS, [crash, tell, tell]).split("\n")
            self.assertEqual(lines[:len(notes) + 1], notes + [H.FAILED_ON], mode)
            self.assertTrue(lines[len(notes) + 1].startswith("- line 14 in main: data = load()"), mode)
            self.assertTrue(lines[len(notes) + 1].endswith("'cfg.json' (Python 3.13.1)"), mode)
            self.assertEqual(lines[len(notes) + 2:], ["- " + " ".join(tell.split())], mode)  # once
        # a Blender step lists a gate's plain line too, before the facts
        text = H.hints_for(plan(GLASS), 0, "blender", FACTS, ["size_mismatch: the table is 2 m long, not 1 m " + MARK])
        lines = text.split("\n")
        k = lines.index(H.FAILED_ON)
        self.assertTrue(lines[k + 1].startswith("- size_mismatch: the table is 2 m long"))
        self.assertEqual(lines[k + 2], H.facts_head(FACTS.versions))

    def test_the_notes_for_a_section_step(self):
        doc = {"title": "Fixture memo " + MARK, "kind": "writing", "summary": MARK, "steps": [
            {"id": "s1", "title": "Write Current workflow audit (≈600 words)", "kind": "writing", "depends_on": [],
             "instructions": "Describe the pipeline. " + MARK},
            {"id": "s2", "title": "Conclusion", "kind": "writing", "depends_on": ["s1"],
             "instructions": 'Write the "Next steps" section in under 150 words. ' + MARK}]}
        self.assertEqual(H.hints_for(doc, 0, "section", FACTS).split("\n"), [
            H.FORMAT_NOTE, H.SECTION_NOTE, "## Current workflow audit", H.LENGTH_NOTE.format(low=450, high=540),
            H.FRAMING_OTHERS_NOTE.format(ends="open or close")])  # s2 is the conclusion
        failed = ["length: 862 words, too long (the step asks for ≈600 words): cut it to about 495 words"]
        self.assertEqual(H.hints_for(doc, 1, "section", None, failed).split("\n"), [
            H.FORMAT_NOTE, H.SECTION_NOTE, "## Next steps", H.LENGTH_MAX_NOTE.format(high=128),
            H.FRAMING_NOTE.format(ends="open"), H.FAILED_ON, "- " + failed[0]])  # no step is the introduction
        lone = {"title": "Fixture note", "kind": "writing", "summary": MARK, "steps": [doc["steps"][0]]}
        self.assertEqual(H.hints_for(lone, 0, "section", None).split("\n")[-1],
                         H.LENGTH_NOTE.format(low=450, high=540))  # a lone section may frame the whole result
        # A section's failure lines quote the model's own words and the judge's; their fixed wording is among
        # echoed_note's own notes: no extra for the echo check.
        self.assertEqual(H.teacher_lines("section", failed), [])

    def test_section_notes_follow_what_the_step_gives(self):
        def doc(*steps):
            return {"title": "Fixture guide " + MARK, "kind": "writing", "summary": MARK, "steps": [
                {"id": f"s{k + 1}", "title": t, "kind": "writing", "depends_on": [], "instructions": ins + " " + MARK}
                for k, (t, ins) in enumerate(steps)]}
        # real: a heading given as 'section titled "X"', a part's length beside the section's (none told)
        given = doc(("Research soil", "List the soil types as JSON."),
                    ("Social Tactics (Part 1)", 'Write a section titled "Social Promotion" in about 600 words. End '
                                                "with a paragraph (≈100‑150 words)."))
        lines = H.hints_for(given, 1, "section", None).split("\n")
        self.assertEqual(lines[:3], [H.FORMAT_NOTE, H.SECTION_NOTE, "## Social Promotion"])
        self.assertFalse(any(H.LENGTH_TAIL in l for l in lines))
        # real: a heading cue prose_gate can't read: their heading, else the bare title, which the gate takes too
        cue = doc(("Research soil", "List the soil types as JSON."),
                  ("Write Introduction (≈600 words)", "Format as a Markdown heading (## Introduction) and the text."))
        lines = H.hints_for(cue, 1, "section", None).split("\n")
        self.assertEqual(lines[:4], [H.FORMAT_NOTE, H.SECTION_GIVEN_NOTE, "## Introduction",
                                     H.LENGTH_NOTE.format(low=450, high=540)])
        # real: a cue that gives the piece no heading of its own ("Craft Tagline") still gets a line to fall back on
        tag = doc(("Research the bundle", "List its features as JSON."),
                  ("Craft Tagline", "Write a tagline (max 8 words). Also return it as a markdown heading (e.g., "
                                    "`# <tagline>`)."))
        self.assertEqual(H.hints_for(tag, 1, "section", None).split("\n")[1:3], [H.SECTION_GIVEN_NOTE, "## Tagline"])
        # real: a full-article step that asks for an introduction and a conclusion gets no framing note
        article = doc(("Research cameras", "List the specs as JSON."),
                      ("Write the full explainer article", "Compose an article (≈800‑1000 words) that:\n1. "
                                                           "Introduces the topic.\n2. Concludes with a tip."))
        notes = H.hints_for(article, 1, "section", None)
        self.assertNotIn(H.FRAMING_NOTE.format(ends="open or close")[:40], notes)
        self.assertNotIn("other steps do that", notes)


class CapAndOrderTests(unittest.TestCase):
    def test_the_6000_character_cap(self):
        labels = sorted({n["label"] for n in FACTS.dumps[NEW]["nodes"]["GeometryNodeTree"].values()
                         if len(n["label"].split()) >= 2})
        step = ("Scatter everything", "With geometry nodes, use " + ", ".join(labels) + ". " + MARK)
        block = facts_for(step)
        self.assertGreater(len(labels), 40)
        self.assertLessEqual(len(block), H.FACTS_CAP)
        self.assertGreater(len(block), H.FACTS_CAP - 1500)  # it fills the room, not stops early
        last = block.split("\n")[-1]
        self.assertRegex(last, r"^\(\d+ more named in the step, left out for room\)$")
        line(block, "- RenderSettings.engine (")  # the values that are always there still fit
        line(block, "- ImageFormatSettings.file_format (")
        whole = H.hints_for(plan(step), 0, "blender", FACTS)
        self.assertTrue(whole.endswith(block))

    def test_most_mentioned_first_then_first_named(self):
        step = ("Two textures", "A Principled BSDF whose colour is a Noise Texture; a second Noise Texture for the "
                "roughness, a third Noise Texture for the bump, then a Color Ramp. " + MARK)
        block = facts_for(step)
        entries = [l for l in block.split("\n") if l.startswith("- node ")]
        self.assertTrue(entries[0].startswith("- node Noise Texture "))  # named three times
        self.assertTrue(entries[1].startswith("- node Principled BSDF "))  # once, but before the Color Ramp
        self.assertTrue(entries[2].startswith("- node Color Ramp "))

    def test_precision(self):
        def named(text):
            return set(H.mentions(text + " " + MARK, FACTS))
        self.assertEqual(named("Mix the paint colours and set the value to 2."), set())
        self.assertEqual(named("Blend them with a Mix node in the material."), {("node", "ShaderNodeMix")})
        self.assertEqual(named("Scatter rocks with Geometry Nodes."), set())  # the tree, not the Geometry node
        self.assertEqual(named("Feed a Random Value node into the scale."), {("node", "FunctionNodeRandomValue")})
        self.assertEqual(named("a noise texture"), {("node", "ShaderNodeTexNoise")})  # any case, never NoiseTexture
        self.assertEqual(named("Add a compositor glare."), {("node", "CompositorNodeGlare")} |
                         {("prop", "Scene.compositing_node_group"), ("prop", "Scene.use_nodes")})
        self.assertEqual(named("Add a sun light and a BevelModifier."),
                         {("class", "SunLight"), ("class", "BevelModifier")})


class FailuresTests(unittest.TestCase):
    LINT = {"level": "error", "kind": "attr", "line": 9, "name": "use_auto_smooth",
            "message": "Mesh has no attribute 'use_auto_smooth' in Blender 5.2.2 or 5.0.1 (has: 'use_auto_texspace')"}
    CRASH = {"step": "s1", "part": "build", "function": "build_s1", "piece_line": 14, "line": 14,
             "source": 'mat.node_tree.nodes["Principled BSDF"].inputs["Specular"].default_value = 0.5  ' + MARK,
             "error": "KeyError: 'bpy_prop_collection[key]: key \"Specular\" not found'", "runner": "Blender 5.2.2"}

    def test_what_failures_name_comes_first(self):
        # The step names the Bevel modifier and a Noise Texture (twice); the failures name Mesh, then the BSDF: the
        # newest failure's names come first (a repair passes its own crash last).
        step = ("Table", "Bevel modifier on chimera_table, then a Noise Texture and another Noise Texture. " + MARK)
        block = facts_for(step, [self.LINT, self.CRASH])
        entries = [l for l in block.split("\n")[1:] if l.startswith("- ")]
        self.assertTrue(entries[0].startswith("- node Principled BSDF (ShaderNodeBsdfPrincipled): "), entries[0][:80])
        self.assertTrue(entries[1].startswith("- Mesh: "), entries[1][:80])
        self.assertTrue(entries[2].startswith("- node Noise Texture "))  # then the step's own, most-mentioned first
        self.assertTrue(entries[3].startswith("- BevelModifier: "))
        self.assertNotIn("use_auto_smooth", entries[1])  # Mesh's real properties: it has none of that name
        self.assertEqual(block, facts_for(step, [self.LINT, self.CRASH]))
        swapped = [l for l in facts_for(step, [self.CRASH, self.LINT]).split("\n")[1:] if l.startswith("- ")]
        self.assertEqual(swapped[:2], [entries[1], entries[0]])
        before = facts_for(step)
        self.assertTrue([l for l in before.split("\n") if l.startswith("- ")][0].startswith("- node Noise Texture "))

    def test_failures_are_listed_in_the_notes(self):
        text = H.hints_for(plan(GLASS), 0, "blender", FACTS, [self.LINT, self.CRASH, self.LINT])
        lines = text.split("\n")
        k = lines.index("Earlier tries of this step failed on:")
        # the lint said again comes where it was said last, after the crash
        self.assertTrue(lines[k + 1].startswith('- line 14 in build_s1: mat.node_tree.nodes["Principled BSDF"]'))
        self.assertTrue(lines[k + 1].endswith("not found' (the newer Blender)"))
        self.assertEqual(lines[k + 2], "- line 9: error: " + self.LINT["message"].replace("in Blender 5.2.2 or 5.0.1",
                                                                                          "in either Blender"))
        self.assertTrue(lines[k + 3].startswith("Blender's own API facts"))  # the repeat is listed once
        many = [dict(self.LINT, line=n) for n in range(20)]
        self.assertEqual(len(H.failure_lines(many)), H.FAILURES_KEEP)
        self.assertTrue(all(len(x) <= H.FAILURE_CHARS for x in H.failure_lines([{"message": "x" * 900}])))

    def test_python_errors_and_operator_keywords(self):
        fails = ["AttributeError: 'ShaderNodeTexNoise' object has no attribute 'noise_scale'",
                 'TypeError: Converting py args to operator properties: bpy.ops.mesh.primitive_cube_add: keyword '
                 '"radius" unrecognized']
        block = facts_for(BEVEL, fails)
        entries = [l for l in block.split("\n")[1:] if l.startswith("- ")]
        keys = sorted(FACTS.op_props("mesh.primitive_cube_add", NEW))
        self.assertEqual(entries[0], "- bpy.ops.mesh.primitive_cube_add keywords: " + ", ".join(keys))  # the newest
        self.assertNotIn("radius", entries[0])
        self.assertTrue(entries[1].startswith("- node Noise Texture (ShaderNodeTexNoise): "))
        self.assertNotIn("OperatorProperties", block)  # words in an error message aren't a class


class EchoTests(unittest.TestCase):
    """echoed_note: a reply that repeats a teacher-only note (ours, never in Chimera's request) can't be a target."""

    def test_every_note_in_any_case_and_punctuation(self):
        head = facts_for(GLASS).split("\n")[0]
        self.assertEqual(head, H.facts_head(FACTS.versions))
        notes = [("head", H.HEAD), ("format_note", H.FORMAT_NOTE), ("files_note", H.FILES_NOTE),
                 ("blender_note", H.BLENDER_NOTE), ("versions_note", H.VERSIONS_NOTE), ("facts_head", head),
                 ("failed_on", H.FAILED_ON)] + [("blender_habit", h) for h in H.BLENDER_HABITS] + list(H.RETIRED)
        for label, note in notes:
            text = "x = 1\n# " + note.upper().replace(",", " ;").replace(":", "") + "\n" + MARK
            self.assertEqual(H.echoed_note(text), label, note)
        for label, note in (("section_note", H.SECTION_NOTE), ("section_note", H.SECTION_GIVEN_NOTE),
                            ("length_note", H.LENGTH_NOTE.format(low=1, high=2)),
                            ("length_note", H.LENGTH_MAX_NOTE.format(high=2)),
                            ("framing_note", H.FRAMING_NOTE.format(ends="close")),
                            ("framing_note", H.FRAMING_OTHERS_NOTE.format(ends="open or close"))):
            self.assertEqual(H.echoed_note("## Soil\n\n" + note.lower() + "\n" + MARK), label, note)
        self.assertEqual(H.echoed_note("## Soil\n\nsuch drafts: other steps do that, as a paragraph about the whole "
                                       "plan would. " + MARK), None)  # our words, but not eight in a row
        # the fixed wording of a dropped section's lines is ours too (task.py's), and so are the prose judge's lines
        # about the format, which a grader's problem can carry into the notes
        # (prose_gate's tell lines' fixed wording, and the line the judges see the goal under, too)
        from datagen import judges, prose_gate, task
        self.assertTrue(prose_gate.TELL_NOTES)
        for label, line in ([("failure_line", task.HEADING_FAILED), ("failure_line", task.FRAMING_FAILED)] +
                            [("failure_line", why) for why in task._SECTION_WHY.values()] +
                            [("failure_line", note) for note in prose_gate.TELL_NOTES] +
                            [("judge_line", judges.HEADING_LINE), ("judge_line", judges.HANDOFF_HEAD),
                             ("judge_line", judges.GOAL_HEAD), ("judge_line", judges.TESTS_GOAL_HEAD)]):
            self.assertEqual(H.echoed_note("## Soil\n\nWe checked: " + line.upper() + ". " + MARK), label, line)
        self.assertIsNone(H.echoed_note("## Soil\n\nIn summary, the soil wants compost and a loose crumb. " + MARK))
        # a note earlier runs gave (RETIRED)
        self.assertEqual(H.echoed_note("assumed: it runs in Blender 5.2.2 and 5.0.1 " + MARK), "blender_note")
        # the habits' facts said in a target's own words aren't an echo
        self.assertIsNone(H.echoed_note("bpy.ops.mesh.primitive_cube_add(size=1)  # 1 m cube, scaled to the table\n"
                                        "lamp.rotation_euler = (0, 0, 0)  # points down at the table\n" + MARK))
        # Eight words in a row of one is enough; seven ordinary ones are not.
        self.assertEqual(H.echoed_note("assumed: no files outside its folder exist, so guard any file. " + MARK),
                         "blender_note")
        self.assertIsNone(H.echoed_note("# else fall back to something built in code " + MARK))
        self.assertIsNone(H.echoed_note("if os.path.exists(path):\n    img = bpy.data.images.load(path)  " + MARK))

    def test_the_failures_only_the_teacher_saw(self):
        lint, crash = FailuresTests.LINT, FailuresTests.CRASH
        said = H.unversioned(lint["message"])  # as the notes word it: "in either Blender"
        self.assertNotEqual(said, lint["message"])
        self.assertEqual(H.teacher_lines("blender", [lint, crash, lint]), [crash["error"], said])  # as listed
        self.assertEqual(H.teacher_lines("blender", [lint, crash], sent=[dict(crash)]), [said])
        # another try's crash with the same error on another line: the repair request shows that error too
        elsewhere = dict(crash, line=crash.get("line", 1) + 7, source="other = line()")
        self.assertEqual(H.teacher_lines("blender", [lint, elsewhere], sent=[dict(crash)]), [said])
        # code steps list their failures too (crashes and the gates' plain lines); a section's give none
        tell = "seam:part_not_mergeable: package.json's (part) block doesn't merge with s1's " + MARK
        self.assertEqual(H.teacher_lines("files", [crash, tell]), [crash["error"], tell])
        self.assertEqual(H.teacher_lines("python-script", [crash], sent=[dict(crash)]), [])
        self.assertEqual(H.teacher_lines("section", [tell]), [])
        many = [dict(lint, line=n, message=f"{lint['message']} {n}") for n in range(20)]
        self.assertEqual(len(H.teacher_lines("blender", many)), H.FAILURES_KEEP)
        told = H.teacher_lines("blender", [lint, crash])
        reply = "# Mesh has no attribute 'use_auto_smooth' in either Blender, so it is left out\n" + MARK
        self.assertEqual(H.echoed_note(reply, told), "extra")
        self.assertIsNone(H.echoed_note(reply))
        self.assertEqual(H.echoed_note("# " + tell, H.teacher_lines("files", [tell])), "extra")
        # The crash's source line is the model's own code: a piece that keeps that line repeats no note.
        self.assertIsNone(H.echoed_note(crash["source"], told))

    def test_what_the_request_says_too_isnt_ours(self):
        """An extra line's runs that Chimera's request holds too, or that are mostly numbers (a size), don't count:
        the next try was asked to fit the step's own sizes and names (real: 1 of the 6 tries of the three steps whose
        size check fired on the smoke's replies was dropped for repeating them)."""
        size = ("no object measures 2.4 × 0.9 × 0.92 m; the nearest is chimera_island at 1.2 × 0.45 × 0.46 m, half "
                "the size asked on every side " + MARK)
        told = H.teacher_lines("blender", [size])
        for reply in ("# The island measures 2.4 × 0.9 × 0.92 m", "# chimera_island at 1.2 × 0.45 × 0.46 m, doubled"):
            self.assertIsNone(H.echoed_note(reply + "\n" + MARK, told), reply)
            with mock.patch.object(H, "NUMERIC_RUN", 99):  # counting runs of numbers, it would be one
                self.assertEqual(H.echoed_note(reply + "\n" + MARK, told), "extra", reply)
        # our own wording around the numbers still counts
        self.assertEqual(H.echoed_note("# was 0.46 m, half the size asked on every side\n" + MARK, told), "extra")
        # a run the request holds too: the names the step itself gives, which a fixed handoff repeats
        names = "Floor, Back Wall, Left Wall, Right Wall, Ceiling Light"
        provides = (f"the handoff's provides names {names}, but the run made nothing by those names (no object, "
                    "collection or ctx key) " + MARK)
        request = f"Your step, s1: Room shell\nBuild the room and register {names} in ctx['objects']. {MARK}"
        told = H.teacher_lines("blender", [provides])
        fixed = f"```handoff\nprovides: {names}\nuses: none\nassumed: none\n```\n{MARK}"
        self.assertEqual(H.echoed_note(fixed, told), "extra")
        self.assertIsNone(H.echoed_note(fixed, told, request=request))
        self.assertEqual(H.echoed_note("# but the run made nothing by those names, so they are added\n" + MARK, told,
                                       request=request), "extra")  # ours, which the request doesn't say
        # the fixed notes are ours whatever the request says
        self.assertEqual(H.echoed_note("# " + H.FORMAT_NOTE + "\n" + MARK, (), request=H.FORMAT_NOTE + MARK),
                         "format_note")

    def test_the_words_are_check_overlaps(self):
        from tools import check_overlap
        hc, _ = check_overlap.helper_modules()
        for s in (H.HEAD, H.BLENDER_NOTE, "Ünïcode wörds_and-dashes, 5.2.2 (x) " + MARK):
            self.assertEqual(H._WORD.findall(s.lower()), hc.words(s))


class VersionTests(unittest.TestCase):
    """version_leak: a reply that names a version of the checks its request doesn't (only our notes ever did)."""
    REQUEST = ("Write one python code block for Blender 5.0 or newer, run headless with blender -b --python. "
               + MARK)  # the contract's own words, as Chimera's request carries them
    REPAIR = REQUEST + "\nYour piece crashed when Chimera ran the joined script in Blender 5.2.2: ... " + MARK

    def test_the_smoke_runs_leaks(self):
        """The forms qwen3.8's and gpt-oss's Blender drafts took (written out again here, not copied)."""
        for text in ("# safe for Blender 5.0.1 & 5.2.2", "# Blender 5.0 / 5.2 renamed the Transmission input",
                     "assumed: works across Blender 5.0/5.2", "# guard for API differences between 5.0.1 and 5.2.2",
                     "# the API changed between 5.0‑5.2 (a non-breaking hyphen)", "# safe on both 5.0 and 5.2",
                     "assumed: these nodes are in Blender 5.0+/5.2+", '"shape": "PLANE",  # [5.2.2] also DISK',
                     "# use_file_extension is Blender 5.2.2-only", "# Blender v5.2: the new name",
                     "# a path known to exist in Blender 4.x → 5.2.2"):
            self.assertEqual(H.version_leak(text + "  " + MARK, self.REQUEST), "version_leak", text)

    def test_what_isnt_a_leak(self):
        for text in ("# works in Blender 5.0 and newer",  # the request's own 5.0
                     "light.energy = 5.2", "loc = (0, 0, 5.0)", "size = (5.0, 5.2, 1.0)", "gap = 5.2 - 5.0",
                     "ratio = 5.0/5.2", '"   5.2. Justification",', "# 5.2  Distribute Points on Faces",
                     "requires Python 3.5.2", "version = 15.2.2", "x = 5.2.21", "if bpy.app.version >= (5, 2, 0):",
                     "# Blender 5.x", "blender_version = 5.0"):
            self.assertIsNone(H.version_leak(text + "  " + MARK, self.REQUEST), text)
        # a repair's request names the Blender that crashed: its version and its major.minor may be named
        self.assertIsNone(H.version_leak("# Blender 5.2.2 has no such input: Blender 5.2 renamed it " + MARK,
                                         self.REPAIR))
        self.assertEqual(H.version_leak("# in Blender 5.0.1 too " + MARK, self.REPAIR), "version_leak")
        self.assertIsNone(H.version_leak("", self.REQUEST))
        self.assertEqual(H.versions_named("Blender 5.0 / 5.2 and 5.0.1 " + MARK), {"5.0", "5.2", "5.0.1"})

    def test_the_notes_words_for_the_blenders(self):
        """notes_leak: the notes' own words for the two Blenders and the sandbox, which no request of Chimera's says
        (the forms the smoke's replies took with the notes of then, written out again here with today's words)."""
        for text in ("# Thin Wall [newer only]: guard it", '"softbox_shape": "PLANE",  # [older, newer only]',
                     "# the newer Blender renamed it", "# The older Blender has no such input",
                     "# works in both Blenders", "# present in either Blender",
                     "# The script is checked in two Blender versions",
                     "assumed: forest.blend is absent in the sandbox, so a stand-in is built",
                     "# sandboxed: no files outside the folder"):
            self.assertEqual(H.notes_leak(text + "  " + MARK, VersionTests.REQUEST), "notes_leak", text)
        for text in ("# newer Blender versions renamed it", "# the newer Blender versions call it Thin Wall",
                     "# works in Blender 5.0 and newer", "# [only] in the shader editor", "# Blenders' defaults",
                     "x = 1"):
            self.assertIsNone(H.notes_leak(text + "  " + MARK, VersionTests.REQUEST), text)
        # a request that says it (a sandbox game the person asks for) may be answered in its words
        self.assertIsNone(H.notes_leak("# the sandbox floor " + MARK, "Build the sandbox game's floor. " + MARK))
        self.assertIsNone(H.notes_leak("", VersionTests.REQUEST))

    def test_failure_lines_name_no_version(self):
        for text, want in (("x in Blender 5.2.2 or 5.0.1 (has: 'y')", "x in either Blender (has: 'y')"),
                           ("x in Blender 5.0.1 (Blender 5.2.2 has no y)", "x in the older Blender (the newer "
                                                                           "Blender has no y)"),
                           ("x in Blender 5.2.2 (only in 5.0.1)", "x in the newer Blender (only in the older Blender)"),
                           ("in both Blender 5.2.2 and 5.0.1", "in both Blenders"),
                           ("KeyError: 'x' (Blender 5.2.2)", "KeyError: 'x' (the newer Blender)"),
                           ("renamed in Blender 5.2; a value of 5.0 stays", "renamed in the newer Blender; a value "
                                                                           "of 5.0 stays"),
                           ("15.2.2 and 5.2.21 stay", "15.2.2 and 5.2.21 stay")):
            self.assertEqual(H.unversioned(text), want, text)
            self.assertEqual(H.versions_named(H.unversioned(text)), set(), text)


class ThirdCheckTests(unittest.TestCase):
    """After the third round of checks (Nov 4): the Blender note without the notes' words for the checks, and tell
    lines that keep their own candidate."""

    NAMES = "Floor, Back Wall, Left Wall, Right Wall, Ceiling Light"
    LINE = (f"the handoff's provides names {NAMES}, but the run made nothing by those names (no object, collection "
            "or ctx key) " + MARK)
    TRY = f"```python\n{MARK}\nimport bpy\n```\n\n```handoff\nprovides: {NAMES}\nuses: none\nassumed: none\n```\n"

    def test_no_fixed_note_says_the_notes_words(self):
        """notes_leak drops a Blender reply that says "sandbox" or "two Blender versions", so no note opens every
        Blender teacher copy with them (real: 9 of qwen3.8's 58 Blender replies in the smoke said "sandbox"); the
        older wording is still ours, in RETIRED."""
        for note in (H.HEAD, H.FORMAT_NOTE, H.FILES_NOTE, H.BLENDER_NOTE, *H.BLENDER_HABITS, H.VERSIONS_NOTE,
                     H.FAILED_ON):  # the facts' marks ("[newer only]") are the notes' words on purpose
            self.assertIsNone(H.notes_leak(note, ""), note)
        self.assertIsNone(H.notes_leak(H.hints_for(plan(GLASS), 0, "blender", None), ""))
        olds = [note for label, note in H.RETIRED if label == "blender_note"]
        self.assertTrue(any("two Blender versions, sandboxed" in note for note in olds), olds)
        for note in olds:
            self.assertEqual(H.echoed_note("# " + note + "\n" + MARK), "blender_note", note)
        self.assertEqual(H.echoed_note("# The script is checked in two Blender versions, sandboxed: no files outside "
                                       "its folder\n" + MARK), "blender_note")

    def test_a_tell_line_keeps_its_own_candidate(self):
        """The provides line of the try a tell line describes shares an 8-word run with it: a later try that keeps
        that handoff (the model's own words) repeats no note of ours. Our wording around the names still counts, and
        so does the line for a try that didn't write those names."""
        tell = H.Tell(self.LINE, self.TRY)
        self.assertEqual(tell, self.LINE)
        self.assertIsInstance(tell, str)
        self.assertEqual(H.failure_lines([tell, tell]), [" ".join(self.LINE.split())])
        (told,) = H.teacher_lines("blender", [tell])
        self.assertIsInstance(told, H.Tell)
        self.assertEqual((str(told), told.own), (self.LINE, self.TRY))
        self.assertEqual(H.echoed_note(self.TRY, [self.LINE]), "extra")  # unpaired: the names' run counts as ours
        self.assertIsNone(H.echoed_note(self.TRY, [told]))
        self.assertIsNone(H.echoed_note(self.TRY, [told], request="Your step, s1: Room. " + MARK))
        self.assertEqual(H.echoed_note("# the run made nothing by those names (no object, collection or ctx key), so "
                                       "they are added\n" + MARK, [told]), "extra")
        other = H.Tell(self.LINE, "```python\nimport bpy\n```\n" + MARK)
        self.assertEqual(H.echoed_note(self.TRY, [other]), "extra")
        # a version in the line is put in words, and the pairing stays
        versioned = H.Tell("the floor is 8 m wide in Blender 5.2.2; the handoff names " + self.NAMES + " " + MARK,
                           self.TRY)
        (told,) = H.teacher_lines("blender", [versioned])
        self.assertIn("the newer Blender", told)
        self.assertEqual(told.own, self.TRY)
        self.assertIsNone(H.echoed_note(self.TRY, [told]))


class AfterTheAuditTests(unittest.TestCase):
    """After the second smoke run's audit (Nov 4): the notes list the newest failure lines (FAILURES_KEEP kept the
    first six, so the tell lines later tries added were the ones cut), and the gates' new tell lines' fixed wording
    (dep_honesty, layout, blender_gate) is ours to the echo check."""

    LINES = [" ".join(f"w{k}x{j}" for j in range(9)) + " " + MARK for k in range(10)]  # no run of words shared

    def test_the_newest_lines_are_kept(self):
        got = H.failure_lines(self.LINES)
        self.assertEqual(got, [" ".join(x.split()) for x in self.LINES[-H.FAILURES_KEEP:]])
        # a line said again is as new as its last time: the first one, repeated last, stays (and comes last)
        again = H.failure_lines(self.LINES + [self.LINES[0]])
        self.assertEqual(again[-1], " ".join(self.LINES[0].split()))
        self.assertNotIn(" ".join(self.LINES[-H.FAILURES_KEEP].split()), again)
        self.assertEqual(len(again), H.FAILURES_KEEP)
        # the notes list those, and the echo check's extra is the same lines, each paired with its own candidate
        notes = H.hints_for(plan(GLASS), 0, "files", None, self.LINES).split("\n")
        k = notes.index(H.FAILED_ON)
        self.assertEqual(notes[k + 1:], ["- " + x for x in got])
        tells = [H.Tell(x, f"candidate {n} " + MARK) for n, x in enumerate(self.LINES)]
        told = H.teacher_lines("files", tells + [H.Tell(self.LINES[-1], "the last again " + MARK)])
        self.assertEqual([str(x) for x in told], self.LINES[-H.FAILURES_KEEP:])
        self.assertEqual([x.own for x in told[:-1]], [f"candidate {n} " + MARK for n in range(4, 9)])
        self.assertEqual(told[-1].own, "the last again " + MARK)  # where it was said last
        self.assertIsNone(H.echoed_note("# " + self.LINES[0], told))  # cut from the notes: not what the teacher saw
        self.assertEqual(H.echoed_note("# " + self.LINES[9], told), "extra")

    def test_a_repairs_own_crash_last_is_listed_and_named_first(self):
        lint, crash = FailuresTests.LINT, FailuresTests.CRASH
        older = self.LINES[:8]
        text = H.hints_for(plan(GLASS), 0, "blender", FACTS, older + [crash, lint])
        lines = text.split("\n")
        k = lines.index(H.FAILED_ON)
        listed = lines[k + 1:k + 1 + H.FAILURES_KEEP]
        self.assertTrue(listed[-2].startswith("- line 14 in build_s1: "), listed[-2])
        self.assertTrue(listed[-1].startswith("- line 9: error: Mesh has no attribute"), listed[-1])
        facts = [l for l in lines[k + 1 + H.FAILURES_KEEP:] if l.startswith("- ")]
        self.assertTrue(facts[0].startswith("- Mesh: "), facts[0][:60])  # the newest failure's names first
        self.assertTrue(facts[1].startswith("- node Principled BSDF "), facts[1][:60])

    def test_the_gates_new_tell_wordings_are_ours(self):
        from datagen import blender_gate, dep_honesty, layout
        for mod in (dep_honesty, layout, blender_gate):
            self.assertTrue(mod.TELL_FORMS, mod.__name__)
            for form in mod.TELL_FORMS:
                self.assertEqual(H.echoed_note("## Notes\n\nassumed: " + form.upper() + ". " + MARK), "failure_line",
                                 (mod.__name__, form))
                self.assertIsNone(H.notes_leak(form, ""), form)  # no wording of the Blenders or the sandbox
        self.assertIsNone(H.echoed_note("uses: s2: rows (failed)\nassumed: s2 failed: three rows made in place\n" +
                                        MARK))  # the handoff the dependency tell asks for is no echo

    def test_every_run_of_a_new_tell_wording_is_refused(self):
        """A reply that repeats any NOTE_N-word run of a gate's tell wording (the whole of one shorter than that),
        in the middle of its own words, is refused as the notes' (failure_line), however it is cased."""
        from datagen import blender_gate, dep_honesty, layout
        for mod in (dep_honesty, layout, blender_gate):
            for form in mod.TELL_FORMS:
                w = H._WORD.findall(form)
                n = min(H.NOTE_N, len(w))
                for k in range(len(w) - n + 1):
                    run = " ".join(w[k:k + n])
                    for text in (f"The lamp is warm. {run} and so on.\n{MARK}", f"# {run.title()}\n{MARK}"):
                        self.assertEqual(H.echoed_note(text), "failure_line", (mod.__name__, run))


def chain(title, used=True, kind="blender"):
    """A two-step fixture plan whose s1 has that title; s2 depends on it when used."""
    return {"title": "Fixture plan " + MARK, "kind": "blender", "summary": MARK, "steps": [
        {"id": "s1", "title": title, "kind": kind, "instructions": "Keep the sofa's width and depth editable. " + MARK,
         "depends_on": []},
        {"id": "s2", "title": "Sofa", "kind": "blender", "instructions": "Build the sofa from s1's sizes. " + MARK,
         "depends_on": ["s1"] if used else []}]}


class ValuesNoteTests(unittest.TestCase):
    """After the third smoke run (Nov 4): a Blender step whose values later steps use is told they go in ctx["values"]
    (VALUES_NOTE, teacher-only), found by its title (values_step), and a reply that repeats the note is refused."""

    VALUES = ("Define variables and setup", "Define variables and render settings",
              "Define Adjustable Variables and Imports", "Define variables and create new file",
              "Define dimensions, colours, and scene settings", "Define global variables and render settings",
              "Define constants, import bpy and set render settings", "Script Header & Imports",
              "Create script header and imports")
    OTHERS = ("Set up render settings", "Set render settings and output", "Create the sofa", "Define the sofa's legs")

    def test_which_steps_are_values_steps(self):
        """The corpus' 10 values-first steps' titles (all with dependents there), with and without a dependent; the
        "Set ... render settings" steps blender_gate's broader title test takes, and other steps, never."""
        for title in self.VALUES:
            self.assertTrue(H.values_step(chain(title), 0), title)
            self.assertFalse(H.values_step(chain(title, used=False), 0), title)  # nothing later uses it
        for title in self.OTHERS:
            self.assertFalse(H.values_step(chain(title), 0), title)
        self.assertFalse(H.values_step(chain(self.VALUES[0]), 1))  # the step that uses it
        # the title only: a values step that doesn't say define is not found (it claims little)
        self.assertFalse(H.values_step(chain("Sofa sizes"), 0))
        self.assertTrue(H.values_step(chain("  define the PARAMETERS for the room"), 0))  # any case
        self.assertFalse(H.values_step(chain("Build the room, then define its parameters"), 0))  # it opens the title

    def test_the_note_for_a_values_step(self):
        note = H.VALUES_NOTE.format(sid="s1")
        p = chain("Define variables and render settings")
        notes = [H.FORMAT_NOTE, H.BLENDER_NOTE, *H.BLENDER_HABITS, H.VERSIONS_NOTE]
        self.assertEqual(H.hints_for(p, 0, "blender", None).split("\n"), notes + [note])
        lines = H.hints_for(p, 0, "blender", FACTS, ["size_mismatch: the sofa is 3 m wide " + MARK]).split("\n")
        self.assertEqual(lines[len(notes)], note)  # after the Blender notes, before the failures and the facts
        self.assertEqual(lines[len(notes) + 1], H.FAILED_ON)
        self.assertGreater(lines.index(H.facts_head(FACTS.versions)), len(notes) + 1)
        # the step that uses it, and a step nothing uses, are told the handoff lines' form instead (since the fifth
        # smoke, Nov 6: HANDOFF_NOTE, for a Blender step that isn't a values step in a plan of more than one step)
        self.assertEqual(H.hints_for(p, 1, "blender", None).split("\n"), notes + [H.HANDOFF_NOTE])
        self.assertEqual(H.hints_for(chain(p["steps"][0]["title"], used=False), 0, "blender", None).split("\n"),
                         notes + [H.HANDOFF_NOTE])
        code = chain("Define variables and render settings", kind="code")
        self.assertEqual(H.hints_for(code, 0, "python-script", None), H.FORMAT_NOTE)  # a Blender step's note only
        # a later step's own names
        three = chain("Build the room")
        three["steps"].insert(1, dict(three["steps"][0], id="s9", title="Define dimensions, colours, and scene "
                                                                         "settings", depends_on=["s1"]))
        three["steps"][2]["depends_on"] = ["s9"]
        got = H.hints_for(three, 1, "blender", None).split("\n")[-1]
        self.assertEqual(got, H.VALUES_NOTE.format(sid="s2"))
        self.assertIn("keep them in SETTINGS_s2 and, in build_s2, put each one", got)
        self.assertEqual(H.hints_for(three, 0, "blender", None).split("\n"), notes + [H.HANDOFF_NOTE])

    def test_the_note_is_ours_and_chimeras_rule_isnt(self):
        """The note says what the contract's rule says in other words: no run of NOTE_N words (or a whole shorter
        note) is shared with Chimera's Blender rule for any step, with a gate's tell wording or with another note,
        so the echo check can't take Chimera's words for it or label it as another note."""
        from contract import texts as T
        from datagen import blender_gate, dep_honesty, layout
        note = H.VALUES_NOTE.format(sid="s1")
        self.assertEqual(len(note), 210)
        self.assertIn('put each one they use in ctx["values"] under the same key; list those keys under provides', note)
        self.assertEqual(H.VALUES_FORMS, ("Later steps use the values this step defines: keep them in",
                                          'put each one they use in ctx["values"] under the same key; list those keys '
                                          "under provides. ctx has no other key for them"))
        self.assertIn('ctx["values"]', T.MODE_BLENDER)  # the contract with the channel (Nov 4)
        for k in range(1, 9):
            sid = "s%d" % k
            self.assertFalse(H.runs(H.VALUES_NOTE.format(sid=sid)) & H.runs(T.fill(T.MODE_BLENDER, sid=sid)), sid)
        others = [H.HEAD, H.FORMAT_NOTE, H.FILES_NOTE, H.BLENDER_NOTE, *H.BLENDER_HABITS, H.VERSIONS_NOTE,
                  H.FAILED_ON, H.facts_head(FACTS.versions)] + [n for _, n in H.RETIRED] + \
            [*blender_gate.TELL_FORMS, *dep_honesty.TELL_FORMS, *layout.TELL_FORMS]
        for other in others:
            n, sh = H._shingles(other)
            self.assertFalse(H.runs(note, n) & sh, other)
            for part in H.VALUES_FORMS:
                n, sh = H._shingles(part)
                self.assertFalse(H.runs(other, n) & sh, (part, other))
        self.assertIsNone(H.notes_leak(note, ""))
        self.assertEqual(H.versions_named(note), set())

    def test_a_reply_that_repeats_it_is_refused(self):
        """Every run of NOTE_N words of the note, in any case: inside its fixed parts (VALUES_FORMS) and across the
        step's own names (SETTINGS_s3, build_s3: VALUES_FILLED; the parts alone left 11 of the 32 runs to nothing,
        the integrity check found); a values piece that does what the note says, in its own words, repeats
        nothing."""
        from tests import contract_fixtures as F
        note = H.VALUES_NOTE.format(sid="s3")
        w = H._WORD.findall(note.lower())
        ours = set().union(*(H.runs(part) for part in H.VALUES_FORMS))
        told = parts = 0
        for k in range(len(w) - H.NOTE_N + 1):
            run = tuple(w[k:k + H.NOTE_N])
            said = " ".join(run)
            for text in (f"# {said.upper()}\n{MARK}", f"The sofa is ready. {said}, as asked.\n{MARK}"):
                self.assertEqual(H.echoed_note(text), "values_note", run)
            told += 1
            parts += run in ours
        self.assertEqual((told, parts), (32, 4 + 17))  # the two parts' runs (11 and 24 words) and the 11 across
        self.assertEqual(H.VALUES_FILLED[0], H.VALUES_NOTE.format(sid="s1"))
        self.assertEqual(len(H.VALUES_FILLED), 8)  # Chimera's cleanPlan keeps up to 8 steps (H.PLAN_STEPS)
        self.assertEqual(H.echoed_note("# " + note + "\n" + MARK), "values_note")
        self.assertEqual(H.echoed_note("assumed: later steps use the values this step defines\n" + MARK), "values_note")
        self.assertIsNone(H.echoed_note(F.VALUES_S1))  # ctx["values"]["sofa_width"] = SETTINGS_s1["sofa_width"]
        self.assertIsNone(H.echoed_note("# hand the sizes on in ctx[\"values\"] for s2\n" + MARK))

    def test_the_note_goes_only_into_the_teachers_copy(self):
        """The request is Chimera's (the contract's Python mirror, byte for byte Go's): it holds no run of the note,
        nor of any other fixed note; the teacher's copy has the note under the head."""
        from contract import goport, prompt
        p = goport.clean_plan(chain("Define variables and render settings"))
        req = prompt.worker_request(p, 0, {})
        self.assertEqual(req.mode, "blender")
        kept = copy.deepcopy(req.messages)
        out = H.teacher_copy(req.messages, H.hints_for(p, 0, "blender", FACTS))
        self.assertEqual(req.messages, kept)
        note = H.VALUES_NOTE.format(sid="s1")
        self.assertIn("\n" + note + "\n", out[0]["content"])
        whole = "\n".join(m["content"] for m in req.messages)
        self.assertIn('ctx["values"]', whole)  # the rule's own sentence about the channel
        self.assertNotIn(note, whole)
        self.assertIsNone(H.echoed_note(whole))
        self.assertEqual(H.echoed_note("\n".join(m["content"] for m in out)), "head")


class AfterTheFourthSmokeTests(unittest.TestCase):
    """After the fourth smoke (Nov 5): a Blender step whose words add a camera, ask Chimera to render or save, or name
    one of Blender 5's API traps the fourth smoke hit (keyframes, video, the compositor, SVG import, a curve's extrude,
    the Subsurface Scattering node's Weight) gets a note on it, teacher-only, and so does a step whose earlier try
    failed on one; a failure line on such a name ends with its replacement. Every new wording is ours to the echo
    check, shares no run with Chimera's Blender rule, names no version, and a piece that does what it says, in code,
    repeats none of it. The step texts are fixtures (each carries the mark)."""

    STEPS = {
        "camera": ("Camera", "Add a camera at (0, -4, 2) looking at the origin, 35 mm lens. " + MARK),
        "output": ("Render", "Set the resolution to 1920x1080 and render the scene to //logo.png. " + MARK),
        "keyframes": ("Spin", "Insert a rotation keyframe at frame 1 and at frame 120 on chimera_logo. " + MARK),
        "video": ("Movie", "Use 30 fps, FFmpeg with H.264 in an MP4 container. " + MARK),
        "compositor": ("Glow", "Enable the compositor and add a glare after the Render Layers node. " + MARK),
        "svg": ("Logo", "Import logo.svg as curves, guarded when the file is missing. " + MARK),
        "extrude": ("Sign", "Extrude the text curve by 0.08 m in the negative Z direction. " + MARK),
        "subsurface": ("Wax", "Add a Subsurface Scattering node with a low scale to the material. " + MARK),
    }
    LINT_FC = {"level": "error", "kind": "attr", "line": 124, "name": "fcurves",
               "message": "Action has no attribute 'fcurves' in Blender 5.2.2 or 5.0.1"}
    CRASH_FC = {"step": "s1", "part": "build", "function": "build_s1", "piece_line": 30, "line": 30,
                "source": "for fcurve in logo_obj.animation_data.action.fcurves:  " + MARK,
                "error": "AttributeError: 'Action' object has no attribute 'fcurves'", "runner": "Blender 5.0.1"}

    def notes(self, step, failures=(), sid_count=1):
        return H.hints_for(plan(step), 0, "blender", None, failures).split("\n")

    def test_each_note_where_the_steps_words_call_for_it(self):
        fact = {f["name"]: f["note"] for f in H.BLENDER5}
        want = dict(fact, camera=H.CAMERA_NOTE, output=H.OUTPUT_NOTE.format(sid="s1"))
        for name, step in self.STEPS.items():
            lines = self.notes(step)
            base = [H.FORMAT_NOTE, H.BLENDER_NOTE, *H.BLENDER_HABITS, H.VERSIONS_NOTE]
            self.assertEqual(lines[:len(base)], base, name)
            self.assertEqual(lines[len(base):], [want[name]], name)  # that note alone, after the versions note
        self.assertEqual(H.hints_for(plan(GLASS), 0, "blender", None).split("\n")[-1], H.VERSIONS_NOTE)  # none
        self.assertEqual(H.hints_for(plan(self.STEPS["keyframes"]), 0, "python-script", None), H.FORMAT_NOTE)
        # a curve word is needed for the extrude fact: a mesh's extrude is another operation
        self.assertNotIn(fact["extrude"], self.notes(("Walls", "Extrude the floor's edges up by 2.5 m. " + MARK)))
        # the camera note follows camera_not_active's own reading: none where another step says which camera renders
        two = {"title": "Fixture plan " + MARK, "kind": "blender", "summary": MARK, "steps": [
            {"id": "s1", "title": "Camera", "kind": "blender", "instructions": self.STEPS["camera"][1],
             "depends_on": []},
            {"id": "s2", "title": "Shot", "kind": "blender", "depends_on": ["s1"],
             "instructions": "Make s1's camera the active scene camera. " + MARK}]}
        self.assertNotIn(H.CAMERA_NOTE, H.hints_for(two, 0, "blender", None))
        # the output note carries the step's own SETTINGS_ name
        three = {"title": "Fixture plan " + MARK, "kind": "blender", "summary": MARK, "steps": [
            {"id": "s%d" % k, "title": "Part", "kind": "blender", "instructions": "Model a part. " + MARK,
             "depends_on": []} for k in (1, 2)] + [
            {"id": "s3", "title": "Render", "kind": "blender", "instructions": self.STEPS["output"][1],
             "depends_on": []}]}
        self.assertIn('SETTINGS_s3["output"]', H.hints_for(three, 2, "blender", None))

    def test_a_failure_calls_for_its_fact_and_its_line_names_the_replacement(self):
        quiet = ("Spin", "Turn chimera_logo once round its Z axis. " + MARK)  # no word for the keyframes fact
        fact = next(f["note"] for f in H.BLENDER5 if f["name"] == "keyframes")
        self.assertNotIn(fact, self.notes(quiet))
        for fail in (self.LINT_FC, self.CRASH_FC, H.Tell("line 9 `curves = list(action.fcurves)`: AttributeError: "
                                                         "'Action' object has no attribute 'fcurves', and the piece's "
                                                         "own except caught it " + MARK, "a candidate " + MARK)):
            lines = self.notes(quiet, [fail])
            self.assertIn(fact, lines)
            (told,) = [l for l in lines if l.startswith("- ")]
            # since the fifth smoke (Nov 6) the fix names the slot
            self.assertTrue(told.endswith("; use anim_utils.action_get_channelbag_for_slot(action, "
                                          "obj.animation_data.action_slot).fcurves"), told)
            self.assertLessEqual(len(told) - 2, H.FAILURE_CHARS)
        self.assertEqual(H.failure_lines([self.LINT_FC]),
                         ["line 124: error: Action has no attribute 'fcurves' in either Blender; use "
                          "anim_utils.action_get_channelbag_for_slot(action, obj.animation_data.action_slot).fcurves"])
        # the fourth smoke's other faults, each with its fix: video, the container, the compositor, its node, SVG,
        # Weight; a line too long for its fix is cut before it, so the fix stays
        cases = [
            ({"line": 112, "source": "im.file_format = 'FFMPEG'  " + MARK, "error": 'TypeError: bpy_struct: item.attr '
              '= val: enum "FFMPEG" not found in (' + "'PNG', " * 40 + ")", "runner": "Blender 5.2.2"},
             "set image_settings.media_type to 'VIDEO' first, which makes file_format FFMPEG", "video"),
            ({"line": 48, "source": "scene.render.ffmpeg.container = 'MPEG4'  " + MARK,
              "error": "AttributeError: 'FFmpegSettings' object has no attribute 'container'"},
             "the container is ffmpeg.format ('MPEG4' for an .mp4)", "video"),
            ({"level": "error", "kind": "attr", "line": 82, "name": "node_tree",
              "message": "Scene has no attribute 'node_tree' in Blender 5.2.2 or 5.0.1"},
             "the compositor is scene.compositing_node_group, a 'CompositorNodeTree' node group", "compositor"),
            ({"level": "error", "kind": "node_type", "line": 91, "name": "CompositorNodeComposite",
              "message": "no node type 'CompositorNodeComposite' in Blender 5.2.2 or 5.0.1 (has: 'CompositorNodeCrop', "
                         "'CompositorNodeSplit', 'CompositorNodeColorMatte')"},
             "there is no Composite node: a compositor group's result goes to its Group Output node", "compositor"),
            ({"level": "error", "kind": "op", "line": 42, "name": "bpy.ops.wm.svg_import",
              "message": "no operator bpy.ops.wm.svg_import in Blender 5.2.2 or 5.0.1 (has: 'usd_import')"},
             "SVG import is bpy.ops.import_curve.svg(filepath=...)", "svg"),
            ({"line": 73, "source": 'sss.inputs["Weight"].default_value = 0.1  ' + MARK,
              "error": "KeyError: 'bpy_prop_collection[key]: key \"Weight\" not found'", "runner": "Blender 5.2.2"},
             "no shader node's Weight input can be looked up by a script: leave it out", "subsurface")]
        for fail, fix, name in cases:
            (line,) = H.failure_lines([fail])
            self.assertTrue(line.endswith("; " + fix), line)
            self.assertLessEqual(len(line), H.FAILURE_CHARS)
            note = next(f["note"] for f in H.BLENDER5 if f["name"] == name)
            self.assertIn(note, self.notes(quiet, [fail]), name)
            # the echo check's extra is the failure as the request or the gate said it, without our fix
            self.assertFalse(any(fix in str(t) for t in H.teacher_lines("blender", [fail])), name)
        # a failure on none of them is listed as before
        self.assertEqual(H.failure_lines([FailuresTests.LINT]),
                         ["line 9: error: " + H.unversioned(FailuresTests.LINT["message"])])

    def test_a_repair_hears_the_fix_only_in_the_teachers_copy(self):
        """A repair's request is Chimera's own (contract.prompt.repair_request, the Go request's mirror): it says the
        crash as Blender did, and holds no note or fix of ours; the teacher's copy of it carries the keyframes fact
        and the crash's line with the fix, as task.Round.repair passes its own crash last."""
        from contract import goport, prompt
        p = goport.clean_plan(plan(self.STEPS["keyframes"]))
        piece = "```python\n" + MARK + "\nimport bpy\n```\n"
        req = prompt.repair_request(p, 0, {}, piece, self.CRASH_FC)
        whole = "\n".join(m["content"] for m in req.messages)
        self.assertIn("'Action' object has no attribute 'fcurves'", whole)
        fact = next(f for f in H.BLENDER5 if f["name"] == "keyframes")
        self.assertNotIn(fact["note"], whole)
        self.assertNotIn(fact["fixes"][0][1], whole)
        self.assertIsNone(H.echoed_note(whole))
        kept = copy.deepcopy(req.messages)
        out = H.teacher_copy(req.messages, H.hints_for(p, 0, "blender", None, [self.CRASH_FC]))
        self.assertEqual(req.messages, kept)
        self.assertIn(fact["note"], out[0]["content"])
        self.assertIn("; " + fact["fixes"][0][1], out[0]["content"])

    def test_no_new_note_names_a_version_or_the_notes_words_for_the_checks(self):
        news = [H.CAMERA_NOTE, *H.OUTPUT_FILLED] + [f["note"] for f in H.BLENDER5] + \
            [x for f in H.BLENDER5 for _, x in f["fixes"]]
        for note in news:
            self.assertEqual(H.versions_named(note), set(), note)
            self.assertFalse(any(v in note for v in FACTS.versions), note)
            self.assertIsNone(H.notes_leak(note, ""), note)
            self.assertIsNone(H.version_leak(note, ""), note)

    def test_every_new_wording_is_ours_to_the_echo_check(self):
        """Any NOTE_N-word run of a new note, a fix or the output note's fixed parts (or the note filled for s1 to s7,
        whose runs cross the step's name), in any case, is refused under its label."""
        from datagen import silent
        cases = [("blender_habit", H.CAMERA_NOTE)] + [("output_note", n) for n in H.OUTPUT_FILLED] + \
            [("blender_fact", f["note"]) for f in H.BLENDER5] + \
            [("blender_fact", x) for f in H.BLENDER5 for _, x in f["fixes"]] + \
            [("failure_line", form) for form in silent.MISSED_FORMS]
        for label, note in cases:
            w = H._WORD.findall(note)
            n = min(H.NOTE_N, len(w))
            self.assertGreaterEqual(len(w), H.NOTE_MIN, note)
            for k in range(len(w) - n + 1):
                run = " ".join(w[k:k + n])
                for text in (f"x = 1\n# {run.upper()}\n{MARK}", f"assumed: {run}, as asked.\n{MARK}"):
                    self.assertIsNotNone(H.echoed_note(text), (label, run))
            self.assertEqual(H.echoed_note("# " + note + "\n" + MARK), label, note)

    def test_the_new_wording_shares_no_run_with_chimeras_rule(self):
        """echoed_note's fixed notes aren't request-excluded, so none may share a run with Chimera's Blender rule (a
        reply that quotes it would be refused), nor with each other's labels in a way that hides one."""
        from contract import texts as T
        news = [H.CAMERA_NOTE, *H.OUTPUT_FORMS, *H.OUTPUT_FILLED] + [f["note"] for f in H.BLENDER5] + \
            [x for f in H.BLENDER5 for _, x in f["fixes"]]
        for k in range(1, 9):
            rule = T.fill(T.MODE_BLENDER, sid="s%d" % k)
            self.assertIsNone(H.echoed_note(rule))
            for note in news:
                n, sh = H._shingles(note)
                self.assertFalse(H.runs(rule, n) & sh, (k, note))

    def test_a_piece_that_does_what_the_facts_say_repeats_none_of_them(self):
        """Code that follows each fact and note, as a teacher would write it: no echo."""
        pieces = {
            "keyframes": "from bpy_extras import anim_utils\nad = ob.animation_data\n"
            "cb = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)\n"
            "for fc in cb.fcurves:\n    for kp in fc.keyframe_points:\n        kp.interpolation = 'LINEAR'\n"
            "fcurves = anim_utils.action_get_channelbag_for_slot(action, slot).fcurves\n",
            "video": "r = scene.render\nr.image_settings.media_type = 'VIDEO'\nr.ffmpeg.format = 'MPEG4'\n"
            "r.ffmpeg.codec = 'H264'\n",
            "compositor": "tree = bpy.data.node_groups.new(name, 'CompositorNodeTree')\n"
            "tree.interface.new_socket('Image', in_out='OUTPUT', socket_type='NodeSocketColor')\n"
            "out = tree.nodes.new('NodeGroupOutput')\nscene.compositing_node_group = tree\n"
            "scene.render.film_transparent = True\n",
            "svg": "if os.path.exists(path):\n    bpy.ops.import_curve.svg(filepath=path)\n",
            "extrude": "curve.extrude = SETTINGS_s1['depth'] / 2  # both ways, so half\n"
            "obj.location.z -= SETTINGS_s1['depth'] / 2\n"
            "mod = obj.modifiers.new('chimera_depth', 'SOLIDIFY')\nmod.thickness = 0.08\nmod.offset = -1\n",
            "subsurface": "sss = nodes.new('ShaderNodeSubsurfaceScattering')\n"
            "sss.inputs['Scale'].default_value = 0.05\n"
            "bsdf.inputs['Subsurface Weight'].default_value = 0.2\n",
            "camera": "cam = bpy.data.objects.new('chimera_camera', bpy.data.cameras.new('chimera_camera'))\n"
            "ctx['scene'].camera = cam\n",
            "output": 'SETTINGS_s3 = {"output": {"render": "//logo.png", "resolution": [1920, 1080]}}\n'}
        self.assertEqual(set(pieces), {f["name"] for f in H.BLENDER5} | {"camera", "output"})
        for code in pieces.values():
            self.assertIsNone(H.echoed_note("```python\n" + MARK + "\nimport bpy\n" + code + "```\n"), code)


class AfterTheIndependentChecksTests(unittest.TestCase):
    """The independent checks of the fourth smoke's round (Nov 6): a fix is a Blender step's only (a code step whose
    own import_svg crashed heard the SVG operator); a hidden-error tell line keeps its instruction when a fix is made
    room for (its quoted error and source are cut instead); the notes' fills reach s8, as Chimera keeps 8 steps; and
    the camera and SVG facts say what the start-up scene and the wm operators hold."""

    SVG_CRASH = {"step": "s2", "part": "build", "function": "test_convert", "piece_line": 14, "line": 14,
                 "source": "shapes = import_svg('logo.svg')  " + MARK,
                 "error": "NameError: name 'import_svg' is not defined"}

    def test_a_fix_is_for_blender_steps_only(self):
        fix = "SVG import is bpy.ops.import_curve.svg(filepath=...)"
        step = ("Convert", "Write convert.py that parses logo.svg into point lists. " + MARK)
        for mode in ("python-script", "files", "section"):
            notes = H.hints_for(plan(step), 0, mode, None, [self.SVG_CRASH])
            self.assertIn("NameError: name 'import_svg' is not defined", notes, mode)
            self.assertNotIn(fix, notes, mode)
            self.assertNotIn("import_curve", notes, mode)
            self.assertFalse(any(fix in t for t in H.failure_lines([self.SVG_CRASH], mode)), mode)
        self.assertIn("; " + fix, H.hints_for(plan(step), 0, "blender", None, [self.SVG_CRASH]))
        self.assertTrue(H.failure_lines([self.SVG_CRASH])[0].endswith("; " + fix))  # Blender's, by default

    def test_a_hidden_error_tell_keeps_its_instruction_beside_its_fix(self):
        from datagen import silent
        fc = silent.tell([{"line": 41, "source": "for fc in act.fcurves:",
                           "error": "AttributeError: 'Action' object has no attribute 'fcurves'"}], [])[0]
        ff = silent.tell([{"line": 117, "source": "scene.render.image_settings.file_format = 'FFMPEG'",
                           "error": 'TypeError: bpy_struct: item.attr = val: enum "FFMPEG" not found in (' +
                                    ", ".join(repr(x) for x in ("JPEG", "OPEN_EXR", "PNG", "WEBP", "BMP", "CINEON",
                                                                "DPX", "IRIS", "JPEG2000", "HDR", "TARGA", "TIFF")) +
                                    ")"}], [])[0]
        for tell, form in ((fc, silent.SWALLOWED_ATTR), (ff, silent.SWALLOWED)):
            (line,) = H.failure_lines([tell])
            fix = H.fix_for(tell)
            self.assertTrue(fix, tell)
            self.assertTrue(line.endswith("; " + fix), line)
            self.assertIn(form.split("%s")[-1] + "; " + fix, line)  # the except and what to do, whole
            self.assertLessEqual(len(line), silent.TELL_CHARS)
            self.assertTrue(line.startswith(tell[:tell.index("`") + 12]), line)  # where: its line and source
        # a lint or crash line, or a plain line of another form, is cut before its fix as before
        crash = {"line": 112, "source": "im.file_format = 'FFMPEG'  " + MARK, "error": 'TypeError: bpy_struct: '
                 'item.attr = val: enum "FFMPEG" not found in (' + "'PNG', " * 40 + ")", "runner": "Blender 5.2.2"}
        for f in (crash, "line 3: " + crash["error"]):
            (line,) = H.failure_lines([f])
            self.assertLessEqual(len(line), H.FAILURE_CHARS)
            self.assertTrue(line.endswith("…; set image_settings.media_type to 'VIDEO' first, which makes "
                                          "file_format FFMPEG"), line)
        self.assertIsNone(silent.refit("line 3 `x = 1`: something else entirely " + MARK, 100))
        self.assertEqual(silent.refit(fc, 400), fc)  # it fits: unchanged

    def test_the_fills_reach_the_eighth_step(self):
        """cleanPlan keeps 8 steps; the runs across SETTINGS_s8 were refused by nothing (the s7 one was)."""
        for k in (7, 8):
            text = (f"# a step that says to render hands its path and settings over in SETTINGS_s{k}[\"output\"] "
                    f"and the piece itself never calls\n{MARK}")
            self.assertEqual(H.echoed_note(text), "output_note", k)
            text = f"# keep them in SETTINGS_s{k} and, in build_s{k}, put each one\n{MARK}"
            self.assertEqual(H.echoed_note(text), "values_note", k)
        self.assertEqual(len(H.OUTPUT_FILLED), 8)
        self.assertEqual(H.PLAN_STEPS, 8)

    def test_the_camera_and_svg_facts(self):
        """The start-up scene holds a cube, a light and the camera (tests/test_datagen_blender5.py's probe); a wm
        operator imports SVG as Grease Pencil, not as curves."""
        self.assertNotIn("empty", H.CAMERA_NOTE)
        self.assertIn("start-up scene already has a camera there", H.CAMERA_NOTE)
        svg = next(f["note"] for f in H.BLENDER5 if f["name"] == "svg")
        self.assertTrue(svg.startswith("SVG import as curves is bpy.ops.import_curve.svg(filepath=...), not a wm "
                                       "operator"), svg)


def fixture_facts():
    """Two versions' dumps of one hand-made shader node, as tools/rna_dump_blender.py writes them since Nov 4
    ([name, identifier, type, available] and the settings that show a hidden name): W shown by one property's two
    values (the older names only one), Weight by nothing (never reachable), Steps by values of two properties,
    Resolution by a pair, Mix's second A only by its data type (another A is there), Height hidden only in the older,
    Angle only in the older and by a pair; outputs: Radius shown by a setting, Pass by none (an output is read to
    link it, so it stays)."""
    def sock(name, ident=None, t="NodeSocketFloat", on=True):
        return [name, ident or name, t, on]
    shown = {"W": ["noise_dimensions=1D", "noise_dimensions=4D"],
             "Steps": ["interpolation_type=STEPPED", "use_clamp=False", "interpolation_type=SMOOTHSTEP"],
             "Resolution": ["mode=END_POINTS&count_mode=RESOLUTION"]}
    inputs = [sock("Vector", t="NodeSocketVector"), sock("W", on=False), sock("Weight", on=False),
              sock("Steps", on=False), sock("Resolution", on=False), sock("A", "A_Float"),
              sock("A", "A_Color", "NodeSocketColor", on=False), sock("Height")]
    outputs = [sock("Color", t="NodeSocketColor"), sock("Radius", on=False), sock("Pass", on=False)]
    dumps = {}
    for v in (NEW, OLD):
        ins, rev = json.loads(json.dumps(inputs)), dict(shown)
        if v == OLD:
            ins[-1][3] = False
            ins.append(sock("Angle", on=False))
            rev.update(W=["noise_dimensions=4D"], Height=["overflow=SCALE_TO_FIT", "overflow=TRUNCATE"],
                       Angle=["data_type=VECTOR&mode=DIRECTION"])
        node = {"label": "Fixture Texture " + MARK, "inputs": ins, "outputs": json.loads(json.dumps(outputs)),
                "reveal": {"inputs": rev, "outputs": {"Radius": ["feature=N_SPHERE_RADIUS"]}}}
        dumps[v] = {"blender": v, "nodes": {"ShaderNodeTree": {"ShaderNodeFixture": node}}, "classes": {}}
    return dumps


def old_dump(d):
    """d as a dump from before socket availability: three-field sockets, no reveal."""
    d = json.loads(json.dumps(d))
    for tree in d["nodes"].values():
        for n in tree.values():
            n.pop("reveal", None)
            for side in rna_lint.SIDES:
                n[side] = [s[:3] for s in n[side]]
    return d


class SocketsTests(unittest.TestCase):
    """The facts' sockets: none a script can't reach (tools.rna_lint.usable, the lint's rule), and the settings that
    show one a fresh node hides; a dump from before availability gives what it gave."""

    def test_the_marks(self):
        facts = rna_lint.Facts(fixture_facts())
        got = H.entry(facts, ("node", "ShaderNodeFixture"))
        self.assertEqual(got, "- node Fixture Texture " + MARK + " (ShaderNodeFixture): inputs: " + ", ".join([
            "Vector [vector]",
            "W [float] (with noise_dimensions 1D or 4D)",  # the newer's settings, the first version that hides it
            "Steps [float] (with interpolation_type STEPPED or SMOOTHSTEP or use_clamp False)",
            "Resolution [float] (with mode END_POINTS and count_mode RESOLUTION)",
            'A (or "A_Float") [float]',
            'A (or "A_Color") [color]',  # inputs["A"] is there on a fresh node: nothing to show
            "Height [float] (with overflow SCALE_TO_FIT or TRUNCATE in the older)",  # the newer shows it as it is
            "Angle [float] (with data_type VECTOR and mode DIRECTION) [older only]"]) +
            "; outputs: Color [color], Radius [float] (with feature N_SPHERE_RADIUS), Pass [float]")
        self.assertNotIn("Weight", got)
        height = next(it for it in top_items(segment(got, "inputs")) if it.startswith("Height "))
        self.assertIsNone(H.notes_leak(height, ""))  # "in the older" isn't the notes' "the older Blender"

    def test_a_dump_from_before_availability(self):
        facts = rna_lint.Facts({v: old_dump(d) for v, d in fixture_facts().items()})
        got = H.entry(facts, ("node", "ShaderNodeFixture"))
        self.assertEqual(segment(got, "inputs"), 'Vector [vector], W [float], Weight [float], Steps [float], '
                                                 'Resolution [float], A (or "A_Float") [float], A (or "A_Color") '
                                                 '[color], Height [float], Angle [float] [older only]')
        self.assertNotIn("(with ", got)

    def test_a_socket_reachable_in_one_version_only(self):
        dumps = fixture_facts()
        dumps[OLD]["nodes"]["ShaderNodeTree"]["ShaderNodeFixture"]["inputs"][0][3] = False  # Vector: shown by nothing
        got = segment(H.entry(rna_lint.Facts(dumps), ("node", "ShaderNodeFixture")), "inputs")
        self.assertTrue(got.startswith("Vector [vector] [newer only], W [float] "), got)
        for v in (NEW, OLD):
            dumps[v]["nodes"]["ShaderNodeTree"]["ShaderNodeFixture"]["inputs"][0][3] = False
        self.assertTrue(segment(H.entry(rna_lint.Facts(dumps), ("node", "ShaderNodeFixture")), "inputs")
                        .startswith("W [float] "))  # in neither: left out


@unittest.skipUnless(AVAILABILITY, "data/rna has no socket availability yet (python3 tools/rna_dump.py dump)")
class RealSocketsTests(unittest.TestCase):
    """The real dumps' sockets as the facts give them (Blender 5.2.2 and 5.0.1 measured these on fresh nodes, Nov 4)."""

    def inputs(self, idname):
        return top_items(segment(H.entry(FACTS, ("node", idname)), "inputs"))

    def test_the_weight_no_script_can_reach(self):
        for idname in ("ShaderNodeBsdfPrincipled", "ShaderNodeEmission", "ShaderNodeBsdfGlass"):
            items = self.inputs(idname)
            self.assertFalse(any(it.startswith("Weight [") for it in items), idname)
            self.assertTrue(items, idname)
        self.assertTrue(any(it.startswith("Weight [") for it in self.inputs("GeometryNodeBlurAttribute")))
        self.assertIn("Strength [float]", self.inputs("ShaderNodeEmission"))

    def test_the_settings_that_show_a_socket(self):
        self.assertIn("W [float] (with noise_dimensions 1D or 4D)", self.inputs("ShaderNodeTexNoise"))
        self.assertIn("Steps [float] (with interpolation_type STEPPED)", self.inputs("ShaderNodeMapRange"))
        self.assertIn("Resolution [float distance] (with mode END_POINTS and count_mode RESOLUTION)",
                      self.inputs("GeometryNodeMeshLine"))
        self.assertIn('A (or "A_Color") [color]', self.inputs("ShaderNodeMix"))
        for idname in ("ShaderNodeTexNoise", "ShaderNodeMapRange", "GeometryNodeMeshLine", "ShaderNodeTexSky",
                       "FunctionNodeCompare", "GeometryNodeStringToCurves", "ShaderNodeTexVoronoi"):
            entry = H.entry(FACTS, ("node", idname))
            for side in rna_lint.SIDES:
                FactsPerVersionTests.assertSocketsMarked(self, entry, idname, side)

    def test_a_long_step_stays_within_the_cap(self):
        """The marks make some entries longer (Noise Texture's by 173 characters); the cap still holds, the nodes
        named most come first, and those left out are counted."""
        nodes = FACTS.dumps[NEW]["nodes"]["ShaderNodeTree"]
        marked = ["Noise Texture", "Voronoi Texture", "Map Range", "Sky Texture"]
        labels = marked + sorted({n["label"] for n in nodes.values() if len(n["label"].split()) >= 2} - set(marked))
        block = facts_for(("Every shader", "In the material, use " + ", ".join(labels) + ". " + MARK))
        self.assertLessEqual(len(block), H.FACTS_CAP)
        entries = [l for l in block.split("\n") if l.startswith("- node ")]
        self.assertTrue(all(" (with " in e for e in entries[:4]), entries[:4])
        self.assertRegex(block.split("\n")[-1], r"^\(\d+ more named in the step, left out for room\)$")


class AfterTheFifthSmokeTests(unittest.TestCase):
    """After the fifth smoke (Nov 6, the round the user approved): the keyframes fact and its fix name the slot (the
    animated ID's animation_data.action_slot, after its first keyframe_insert) and no longer say "None", and the fix
    also ends a line where the slot was wrong; every sampler of a Blender step that isn't a values step, in a plan of
    more than one step, is told the handoff lines' form (HANDOFF_NOTE), and a values step hears nothing of it; the
    Blender note says what to print for a missing input file. Each wording is ours to the echo check, shares no run
    with Chimera's texts and names no version, and code that does what it says repeats none of it. The steps and
    pieces are hand-written fixtures (each carries the mark)."""

    KEYS = ("Spin", "Keyframe chimera_logo's Z rotation from 0 to 360 degrees over frames 1-120, linear. " + MARK)
    QUIET = ("Spin", "Turn chimera_logo once round its Z axis. " + MARK)  # no word for the keyframes fact
    NONE_SLOT = {"step": "s4", "part": "build", "function": "build_s4", "piece_line": 80, "line": 80,
                 "source": "for fcurve in bag.fcurves:  " + MARK,
                 "error": "AttributeError: 'NoneType' object has no attribute 'fcurves'", "runner": "Blender 5.2.2"}
    ACTION_SLOT = {"step": "s4", "part": "build", "function": "build_s4", "piece_line": 77, "line": 77,
                   "source": "channelbag = anim_utils.action_get_channelbag_for_slot(action, action)  " + MARK,
                   "error": 'TypeError: ActionKeyframeStrip.channelbag(): error with argument 1, "slot" -  '
                            'Function.slot expected a ActionSlot type, not Action', "runner": "Blender 5.2.2"}
    MADE_UP = {"level": "error", "kind": "module", "line": 75, "name": "action_get_channelbag_for_action",
               "message": "module 'bpy_extras.anim_utils' has no 'action_get_channelbag_for_action' in Blender 5.2.2 "
                          "or 5.0.1 (has: 'action_get_channelbag_for_slot', 'action_ensure_channelbag_for_slot')"}

    @staticmethod
    def two(first="Table", second="Lamp", values=False):
        """A two-step Blender plan whose s2 depends on s1 (s1 a values step when values)."""
        return {"title": "Fixture plan " + MARK, "kind": "blender", "summary": MARK, "steps": [
            {"id": "s1", "title": "Define variables and render settings" if values else first, "kind": "blender",
             "instructions": "Make the table. " + MARK, "depends_on": []},
            {"id": "s2", "title": second, "kind": "blender", "instructions": "Put a lamp on s1's table. " + MARK,
             "depends_on": ["s1"]}]}

    def test_the_keyframes_fact_names_the_slot_and_when_to_read_it(self):
        fact = next(f for f in H.BLENDER5 if f["name"] == "keyframes")
        note = fact["note"]
        self.assertIn("animation_data.action_slot", note)
        self.assertIn("obj.animation_data.action_slot for an object obj", note)  # the slot named, not just "slot"
        self.assertIn("After an ID's first keyframe_insert", note)  # read after the first key, which sets it
        self.assertIn("which that first key sets", note)
        self.assertNotIn("None", note)  # "(None before its first key)" was read as "pass None"
        self.assertIn(note, H.hints_for(plan(self.KEYS), 0, "blender", None).split("\n"))
        self.assertEqual(fact["fixes"][0][1], H.KEYFRAMES_FIX)
        self.assertIn("obj.animation_data.action_slot", H.KEYFRAMES_FIX)
        self.assertNotIn("(action, slot)", H.KEYFRAMES_FIX)

    def test_the_fix_ends_a_line_where_the_slot_was_wrong(self):
        """smoke5's channelbag tries: a slot of None (4 tries), the action passed as the slot (1), a function that
        doesn't exist (1), whose lines ended with no fix before. Now each line ends with the fix, the fact comes with it
        on a step whose words don't name keyframes, and the line stays within FAILURE_CHARS."""
        fact = next(f["note"] for f in H.BLENDER5 if f["name"] == "keyframes")
        for fail in (AfterTheFourthSmokeTests.LINT_FC, self.NONE_SLOT, self.ACTION_SLOT, self.MADE_UP):
            (line,) = H.failure_lines([fail])
            self.assertTrue(line.endswith("; " + H.KEYFRAMES_FIX), line)
            self.assertLessEqual(len(line), H.FAILURE_CHARS)
            self.assertIn(fact, H.hints_for(plan(self.QUIET), 0, "blender", None, [fail]).split("\n"))
            self.assertFalse(any(H.KEYFRAMES_FIX in str(t) for t in H.teacher_lines("blender", [fail])))
        # another None's error isn't the keyframes'
        other = dict(self.NONE_SLOT, error="AttributeError: 'NoneType' object has no attribute 'location'")
        self.assertEqual(H.fix_for(other), "")
        # a hidden-error tell of silent's keeps its end beside the fix (in silent.TELL_CHARS)
        from datagen import silent
        tell = silent.tell([{"line": 1041, "source": "for fc in act.fcurves:",
                             "error": "AttributeError: 'Action' object has no attribute 'fcurves'"}], [])[0]
        (line,) = H.failure_lines([tell])
        self.assertTrue(line.endswith(silent.SWALLOWED_ATTR.split("%s")[-1] + "; " + H.KEYFRAMES_FIX), line)
        self.assertLessEqual(len(line), silent.TELL_CHARS)

    def test_a_plain_import_of_bpy_extras_gets_the_import(self):
        """The checks of Nov 6: the fact names bpy_extras.anim_utils by its dotted path, and after a plain import
        bpy_extras Blender has no anim_utils there (TheSlotHoldsInBlenderTests prints its message in both); that
        crash's line now ends with how to import it, and the fact comes with it."""
        fact = next(f["note"] for f in H.BLENDER5 if f["name"] == "keyframes")
        crash = dict(self.NONE_SLOT, source="bag = bpy_extras.anim_utils.action_get_channelbag_for_slot(act, slot)  "
                     + MARK, error="AttributeError: module 'bpy_extras' has no attribute 'anim_utils'")
        (line,) = H.failure_lines([crash])
        self.assertTrue(line.endswith("; " + H.ANIM_UTILS_FIX), line)
        self.assertIn("from bpy_extras import anim_utils", H.ANIM_UTILS_FIX)
        self.assertLessEqual(len(line), H.FAILURE_CHARS)
        self.assertIn(fact, H.hints_for(plan(self.QUIET), 0, "blender", None, [crash]).split("\n"))
        self.assertFalse(any(H.ANIM_UTILS_FIX in str(t) for t in H.teacher_lines("blender", [crash])))
        self.assertEqual(H.echoed_note("# " + H.ANIM_UTILS_FIX + "\n" + MARK), "blender_fact")
        self.assertIsNone(H.echoed_note("import bpy\nfrom bpy_extras import anim_utils\n" + MARK))
        # another module's missing attribute isn't this one
        self.assertEqual(H.fix_for(dict(crash, error="AttributeError: module 'bpy' has no attribute 'anim_utils'")),
                         "")

    def test_the_handoff_note_goes_to_every_blender_step_but_a_values_step(self):
        from contract import validate
        note = H.HANDOFF_NOTE
        self.assertIn("provides and uses as exact names only, comma-separated", note)
        self.assertIn('a ctx key bare (sofa, not ctx["objects"]["sofa"]) with no note or size in brackets', note)
        self.assertIn("on uses the step each came from (sofa from s2)", note)
        self.assertIn("each of the three lines within %d characters" % validate.HANDOFF_LINE_MAX, note)
        self.assertEqual(validate.HANDOFF_LINE_MAX, 300)  # Chimera's handoffLineMax
        self.assertNotIn("assumed", note)  # the assumed line is held to the length only
        base = [H.FORMAT_NOTE, H.BLENDER_NOTE, *H.BLENDER_HABITS, H.VERSIONS_NOTE]
        p = self.two()
        for i in (0, 1):  # used by a later step or not
            self.assertEqual(H.hints_for(p, i, "blender", None).split("\n"), base + [note], i)
        # after the versions note, before the step's own notes, the failures and the facts
        lines = H.hints_for(self.two(second="Spin"), 1, "blender", FACTS,
                            [AfterTheFourthSmokeTests.LINT_FC]).split("\n")
        self.assertEqual(lines[len(base)], note)
        self.assertLess(lines.index(note), lines.index(H.FAILED_ON))
        # a values step: its VALUES_NOTE and nothing of this (its provides line is the user's open question)
        v = self.two(values=True)
        self.assertTrue(H.values_step(v, 0))
        got = H.hints_for(v, 0, "blender", FACTS, ["the provides line has 344 characters " + MARK])
        self.assertIn(H.VALUES_NOTE.format(sid="s1"), got)
        self.assertNotIn(note, got)
        self.assertNotIn("characters, past", got.split(H.FAILED_ON)[0])
        self.assertIn(note, H.hints_for(v, 1, "blender", None))  # the step that uses it isn't one
        # a lone step has no handoff; the other modes have their own rules
        self.assertNotIn(note, H.hints_for(plan(GLASS), 0, "blender", None))
        for mode in ("python-script", "files", "section"):
            self.assertNotIn(note, H.hints_for(p, 1, mode, None), mode)

    def test_every_sampler_of_the_step_hears_the_handoff_note(self):
        """task.Round.solve on a Blender step whose tries all fail with a crash: the first batch, the told batches,
        the repair and qwen3.8 (the second sampler, which no tell reached in smoke5) each get the note in the
        teacher's copy, and the stored request none; on a values step none of them gets it."""
        from types import SimpleNamespace
        from datagen import task as T
        for values in (False, True):
            p = self.two(values=values)
            i = 0 if values else 1
            calls = []

            def call(model, messages, purpose, **kw):
                calls.append((model, purpose, messages[0]["content"]))
                return SimpleNamespace(model=model, key="k%d" % len(calls), sample=kw.get("sample"), wall_s=0.1,
                                       cached=False, done_reason="stop", content="```python\nimport bpy\n```\n" + MARK,
                                       stats={}, thinking_chars=0, runaway=False, error=None)
            env = SimpleNamespace(llm=SimpleNamespace(call=call), facts=None, names={},
                                  models={"teacher": "gpt-oss:120b", "second": "qwen3.8:27b"})
            r = T.Round(env, {"text": "A table and a lamp. " + MARK, "seed_id": "fixture-0000-00"}, 1, p, "hydra:1.0")
            req = {"messages": [{"role": "system", "content": "Chimera's request " + MARK},
                                {"role": "user", "content": "Your step " + MARK}], "need_ctx": 8192}
            step = {"sid": "s%d" % (i + 1), "index": i, "mode": "blender", "variant": None, "request": req,
                    "inputs": {"index": i, "outputs": {}, "names": None}, "candidates": [], "repairs": [],
                    "kept": None, "drop": None, "seconds": {"teacher": 0.0, "judge": 0.0, "tests": 0.0, "checks": 0.0}}

            def failed(c, k):
                c.update(reasons=["alone_strict:5.2.2"], stage="gate:alone", mech=False, gate={"lint": [], "tell": []},
                         crash={"step": step["sid"], "part": "build", "function": "build_" + step["sid"],
                                "piece_line": k, "line": k, "source": "x = 1  " + MARK,
                                "error": "ValueError: fixture %d" % k, "runner": "Blender 5.2.2"})

            def check_batch(self, st, new, rq, told, alone):
                for c in new:
                    failed(c, len(calls))

            def precheck(self, st, c, rq, told=()):
                failed(c, len(calls))
                return False
            with mock.patch.object(T.Round, "check_batch", check_batch), \
                    mock.patch.object(T.Round, "precheck", precheck), \
                    mock.patch.object(T.Round, "pick", lambda self, st, new, source: False), \
                    mock.patch.object(T.Round, "request", lambda self, inputs: req), \
                    mock.patch.object(T.Round, "soft_keep", lambda self, st, groups: False):
                r.solve(step)
            purposes = {pu for _, pu, _ in calls}
            self.assertTrue({"worker", "repair", "second"} <= purposes, (values, purposes))
            self.assertIn("qwen3.8:27b", {m for m, _, _ in calls})
            for model, purpose, system in calls:
                self.assertIn(H.HEAD, system)
                self.assertEqual(H.HANDOFF_NOTE in system, not values, (values, model, purpose))
            self.assertNotIn(H.HEAD, json.dumps(req))  # Chimera's own request is untouched

    def test_the_blender_note_says_what_to_print_for_a_missing_file(self):
        note = H.BLENDER_NOTE
        self.assertIn("print a plain line of the piece's own that names the missing file instead", note)
        self.assertIn("without the stand-in marker", note)
        self.assertIn('print("chimera: stand-in", key) is only for a key a missing dependency was to provide', note)
        old = [n for label, n in H.RETIRED if label == "blender_note"]
        self.assertNotIn(note, old)
        self.assertEqual(H.echoed_note("# " + old[-1] + "\n" + MARK), "blender_note")  # the old one is still ours

    def test_the_new_wordings_are_ours_and_not_chimeras(self):
        """Every NOTE_N-word run of each new wording, in any case, is refused under its label; none shares such a run
        with any of Chimera's texts (contract.texts, its Blender rule filled for s1 to s8) or names a version; the
        retired fact and fix stay ours; and code and a handoff that do what the notes say (the channelbag with the
        named slot, a plain print for a missing file, names-only lines) repeat none of them."""
        from contract import texts
        news = [("handoff_note", H.HANDOFF_NOTE), ("blender_note", H.BLENDER_NOTE),
                ("blender_fact", next(f["note"] for f in H.BLENDER5 if f["name"] == "keyframes")),
                ("blender_fact", H.KEYFRAMES_FIX)]
        chimeras = [v for v in vars(texts).values() if isinstance(v, str) and len(v) > 40]
        chimeras += [texts.fill(texts.MODE_BLENDER, sid="s%d" % k) for k in range(1, 9)]
        for label, note in news:
            w = H._WORD.findall(note)
            n = min(H.NOTE_N, len(w))
            self.assertGreaterEqual(len(w), H.NOTE_N, note)
            for k in range(len(w) - n + 1):
                run = " ".join(w[k:k + n])
                for text in (f"x = 1\n# {run.upper()}\n{MARK}", f"assumed: {run}, as asked.\n{MARK}"):
                    self.assertEqual(H.echoed_note(text), label, (label, run))
            self.assertEqual(H.echoed_note("# " + note + "\n" + MARK), label, note)
            n, sh = H._shingles(note)
            for text in chimeras:
                self.assertFalse(H.runs(text, n) & sh, (note[:40], text[:60]))
                self.assertIsNone(H.echoed_note(text))
            self.assertEqual(H.versions_named(note), set(), note)
            self.assertIsNone(H.notes_leak(note, ""), note)
        for label, note in H.RETIRED[-2:]:
            self.assertEqual(H.echoed_note("# " + note + "\n" + MARK), label, note)
        # code and handoffs that do what the notes say repeat none of them
        pieces = [
            "from bpy_extras import anim_utils\nobj.keyframe_insert('rotation_euler', frame=1)\n"
            "action = obj.animation_data.action\n"
            "cb = anim_utils.action_get_channelbag_for_slot(action, obj.animation_data.action_slot)\n"
            "for fc in anim_utils.action_get_channelbag_for_slot(action, obj.animation_data.action_slot).fcurves:\n"
            "    for kp in fc.keyframe_points:\n        kp.interpolation = 'LINEAR'\n"
            "curves = anim_utils.action_get_channelbag_for_slot(action, obj.animation_data.action_slot).fcurves\n"
            "fcurves = anim_utils.action_get_channelbag_for_slot(obj.animation_data.action, "
            "obj.animation_data.action_slot).fcurves\n"
            "slot = cam.data.animation_data.action_slot  # set by the first keyframe_insert\n"
            "bag = bpy_extras.anim_utils.action_get_channelbag_for_slot(cam.data.animation_data.action, slot)\n",
            "if os.path.exists(svg_path):\n    bpy.ops.import_curve.svg(filepath=svg_path)\nelse:\n"
            "    print('no SVG at', svg_path, '- using a built-in shape')\n"
            "    print(f'logo file {svg_path} not found, building a plain triangle instead')\n",
            "```handoff\nprovides: lamp, shade, lamp_height\n"
            "uses: table from s1, table_height from s1\n"
            "assumed: the shade sits 0.1 m below the lamp's top, and the lamp is 0.5 m tall\n```\n"]
        for text in pieces:
            self.assertIsNone(H.echoed_note(text + MARK), text)


class TeacherCopyTests(unittest.TestCase):
    def test_the_notes_go_only_into_the_teachers_copy(self):
        msgs = [{"role": "system", "content": "You are one worker in Chimera. " + MARK},
                {"role": "user", "content": "Your step, s1: Glass " + MARK}]
        kept = copy.deepcopy(msgs)
        notes = H.hints_for(plan(GLASS), 0, "blender", FACTS)
        out = H.teacher_copy(msgs, notes)
        self.assertEqual(msgs, kept)  # the stored training request is untouched
        self.assertEqual(out[0]["content"], kept[0]["content"] + "\n\n" + H.HEAD + "\n" + notes)
        self.assertEqual(out[1], kept[1])
        self.assertEqual(H.teacher_copy(msgs, ""), kept)
        lone = H.teacher_copy(msgs[1:], notes)
        self.assertEqual(lone[0], {"role": "system", "content": H.HEAD + "\n" + notes})
        self.assertEqual(lone[1:], kept[1:])


if __name__ == "__main__":
    unittest.main()
