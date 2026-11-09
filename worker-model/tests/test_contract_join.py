"""The joiner and the line map on hand-made pieces (tests/contract_fixtures.py: test fixtures, never training data)."""
import ast
import copy
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest

from tests import _paths  # noqa: F401
from tests import contract_fixtures as F
from contract import prompt
from contract import texts as T
from contract.goport import clean_plan
from contract.join import alone_script, find_part, join, merge_python, slug, uses_names
from contract.validate import validate_piece
from contract.linemap import LineMap, locate_check


def seam_codes(j):
    return [s.code for s in j.seams]


def script_line(script, text):
    """1-based line number of the first script line that is exactly `text`."""
    return script.split("\n").index(text) + 1


def import_lines(script):
    return [l for l in script.split("\n") if l.startswith(("import ", "from "))]


def module_level_unbound(script):
    """Names a module-level statement reads before anything at the top binds them (a NameError on import),
    builtins aside. Function bodies run later, from main(), so only their decorators and defaults count."""
    import builtins
    bound, out = set(dir(builtins)), []
    for node in ast.parse(script).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            read = node.decorator_list + (node.args.defaults if hasattr(node, "args") else [])
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            read = [node.value] if node.value is not None else []
        else:
            read = [] if isinstance(node, (ast.Import, ast.ImportFrom, ast.If)) else [node]
        for r in read:
            out += [n.id for n in ast.walk(r) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                    and n.id not in bound]
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bound.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                bound.update(n.id for n in ast.walk(t) if isinstance(n, ast.Name))
    return out


class LoneCarriageReturnTests(unittest.TestCase):
    def test_it_ends_a_line_as_it_does_for_ast(self):
        # Found porting to Go: ast counts it as a line end and split("\\n") doesn't, so the joiner took the wrong lines
        # or ran off the end of them.
        plan = clean_plan({"title": "T", "kind": "code", "steps": [
            {"id": "a", "title": "A", "kind": "code", "instructions": "Do it."},
            {"id": "b", "title": "B", "kind": "code", "instructions": "Then this."}]})
        piece = "```python\ndef main():\n    a = 1\r    b = 2\n```\n\n```handoff\nprovides: x\nuses: none\nassumed: none\n```\n"
        j = join(plan, {"a": piece, "b": None})
        self.assertFalse(j.fallback, j.reasons)
        self.assertIn("    a = 1\n    b = 2\n", j.script)


class LibraryEntryThatWontWrapTests(unittest.TestCase):
    def test_it_is_a_seam_and_a_fallback_not_a_crash(self):
        # Found porting to Go: hoisting an import cuts a statement that shares its line in two.
        j = join(F.BLENDER_PLAN, dict(F.BLENDER_OUTPUTS, **{F.BLENDER_PLAN["steps"][0]["id"]: {
            "output": "```python\nimport os; x = (1,\n 2)\n```", "status": "library"}}))
        self.assertTrue(j.fallback)
        self.assertIn("library_seam", seam_codes(j))
        self.assertEqual(j.reasons[0], "s1: the library entry can't be joined")


class BlenderJoinTests(unittest.TestCase):
    def setUp(self):
        self.j = join(F.BLENDER_PLAN, F.BLENDER_OUTPUTS)

    def test_joins_without_fallback_or_seams(self):
        self.assertFalse(self.j.fallback, self.j.reasons)
        self.assertEqual(seam_codes(self.j), [])
        self.assertEqual(self.j.script_kind, "run_blender")
        ast.parse(self.j.script)

    def test_layout(self):
        s = self.j.script
        lines = s.split("\n")
        # imports deduplicated (all three pieces import bpy), at the top
        self.assertEqual([l for l in lines if l.startswith(("import ", "from "))],
                         ["import bpy", "import bmesh", "from mathutils import Vector"])
        # each step's part in plan order, after its header, in the piece's own order: settings, helpers, build
        order = [s.index(x) for x in ("from mathutils import Vector", "# --- s1: Floor and material ---",
                                      "SETTINGS_s1 = {", "def build_s1", "# --- s2: Side table ---", "SETTINGS_s2 = {",
                                      "def _s2_box", "def build_s2", "# --- s3: Lamp on the table ---",
                                      "SETTINGS_s3 = {", "def build_s3", "def main():")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn("# Settings", s)
        self.assertIn("# --- s1: Floor and material ---\nSETTINGS_s1 = {\n", s)
        self.assertIn('SETTINGS_s2 = {"top_size": 0.6, "height": 0.55, "leg": 0.04}\n\n\ndef _s2_box(', s)
        # main(): a chimera_<slug> collection, every build in plan order, the output once
        main = s[s.index("def main():"):s.index("def _chimera_output")]
        self.assertIn('collection = bpy.data.collections.new("chimera_reading_corner")', main)
        self.assertIn('ctx = {"scene": scene, "collection": collection, "objects": {}, "values": {}}', main)
        self.assertLess(main.index("build_s1(ctx)"), main.index("build_s2(ctx)"))
        self.assertLess(main.index("build_s3(ctx)"), main.index("_chimera_output([SETTINGS_s1])"))
        # the pieces' own run-alone guards and handoffs are gone; one guard at the end calls main()
        self.assertEqual(s.count('if __name__ == "__main__":'), 1)
        self.assertTrue(s.rstrip().endswith('if __name__ == "__main__":\n    ctx = main()'))  # ctx for a probe
        self.assertIn("    return ctx\n", main)
        self.assertNotIn("```handoff", self.j.text)
        self.assertNotIn("provides:", self.j.text)
        self.assertNotIn("build_s1({", s)

    def test_result_text_and_assumptions(self):
        self.assertTrue(self.j.text.startswith("# Reading corner\n\n```python\n"))
        self.assertIn("Run it with: blender -b --python script.py", self.j.text)
        self.assertEqual(self.j.assumptions, [("s1", "the floor lies at z = 0"), ("s2", "the table stands at x = 1, y = 1")])
        self.assertEqual(self.j.assumptions_note(),
                         "Assumptions: s1: the floor lies at z = 0; s2: the table stands at x = 1, y = 1")

    def test_line_map(self):
        s, lm = self.j.script, self.j.linemap
        self.assertEqual(len(lm), len(s.rstrip("\n").split("\n")))
        lines = s.split("\n")
        n = script_line(s, "    top = _s2_box(ctx, \"chimera_table\", (t, t, 0.03), Vector((1.0, 1.0, s[\"height\"])))")
        loc = lm.locate(n)
        self.assertEqual((loc["step"], loc["part"], loc["function"], loc["repair"]), ("s2", "build", "build_s2", "s2"))
        piece_code = F.S2_CODE.split("\n")
        self.assertEqual(piece_code[loc["piece_line"] - 1], lines[n - 1])  # piece_line counts in the piece's block
        loc = lm.locate(script_line(s, "    mesh.from_pydata(verts, [], faces)"))
        self.assertEqual((loc["step"], loc["part"], loc["function"]), ("s2", "helper", "_s2_box"))
        loc = lm.locate(script_line(s, '    "size": 4.0,'))
        self.assertEqual((loc["step"], loc["part"], loc["function"], loc["repair"]), ("s1", "settings", "SETTINGS_s1", "s1"))
        loc = lm.locate(script_line(s, "import bmesh"))
        self.assertEqual((loc["step"], loc["part"], loc["repair"]), ("s3", "import", "s3"))
        self.assertEqual(lm.locate(script_line(s, "import bpy"))["step"], "s1")  # all three import it: the first
        for text, part in (("    build_s2(ctx)", "main"), ("    r = scene.render", "output"),
                           ("# --- s2: Side table ---", "chimera")):
            loc = lm.locate(script_line(s, text))
            self.assertEqual((loc["step"], loc["part"], loc["repair"]), (None, part, None), text)
        self.assertEqual(lm.locate(10 ** 6)["part"], "outside")
        self.assertEqual(lm.lines_of("s3")[0], script_line(s, "import bmesh"))

    def test_line_map_round_trip_and_check_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "linemap.json")
            self.j.linemap.save(path)
            lm = LineMap.load(path)
        s = self.j.script
        n = script_line(s, "    light_data.energy = s[\"power\"]")
        check = {"check": {"outcome": "failed", "runner": "Blender 5.2.2", "line": n,
                           "source": "light_data.energy = s[\"power\"]", "error": "TypeError: x"}}
        loc = locate_check(check, lm, s)
        self.assertEqual((loc["step"], loc["function"], loc["repair"], loc["definite"], loc["source_matches"]),
                         ("s3", "build_s3", "s3", True, True))
        unsure = copy.deepcopy(check)
        unsure["check"]["outcome"] = "unsure"
        self.assertIsNone(locate_check(unsure, lm, s)["repair"])
        self.assertFalse(locate_check(dict(check["check"], line=1), lm, s)["source_matches"])
        self.assertIsNone(locate_check({"check": {"outcome": "passed"}}, lm)["step"])

    def test_each_step_keeps_its_own_top_level_order(self):
        # Review, Oct 29: the joiner hoisted every SETTINGS_ dict into one part above all the steps' code, so a
        # dict that uses the step's own _s2_ constant (valid, and fine alone) raised NameError joined, and the line
        # map then asked s2 to repair a piece with no bug.
        s2 = F.S2.replace('SETTINGS_s2 = {"top_size": 0.6, "height": 0.55, "leg": 0.04}',
                          '_s2_LEG = 0.04\nSETTINGS_s2 = {"top_size": 0.6, "height": 0.55, "leg": _s2_LEG}')
        self.assertNotEqual(s2, F.S2)
        piece = validate_piece(s2, "blender", sid="s2")
        self.assertTrue(piece.ok, piece.reasons())
        self.assertEqual(module_level_unbound(alone_script(piece)), [])  # fine alone
        j = join(F.BLENDER_PLAN, dict(F.BLENDER_OUTPUTS, s2=s2))
        self.assertFalse(j.fallback, j.reasons)
        self.assertEqual(seam_codes(j), [])
        self.assertEqual(module_level_unbound(j.script), [])  # and joined
        self.assertIn("# --- s2: Side table ---\n_s2_LEG = 0.04\nSETTINGS_s2 = {", j.script)
        loc = j.linemap.locate(script_line(j.script, "_s2_LEG = 0.04"))
        self.assertEqual((loc["step"], loc["part"], loc["function"]), ("s2", "helper", "_s2_LEG"))
        self.assertEqual(piece.code.split("\n")[loc["piece_line"] - 1], "_s2_LEG = 0.04")
        # a constant computed by one of the step's own helpers, above the dict, keeps working too
        s2b = s2.replace("_s2_LEG = 0.04\n", "def _s2_leg():\n    return 0.04\n\n\n_s2_LEG = _s2_leg()\n")
        piece = validate_piece(s2b, "blender", sid="s2")
        self.assertTrue(piece.ok, piece.reasons())
        self.assertEqual(module_level_unbound(alone_script(piece)), [])
        j = join(F.BLENDER_PLAN, dict(F.BLENDER_OUTPUTS, s2=s2b))
        self.assertFalse(j.fallback, j.reasons)
        self.assertEqual(module_level_unbound(j.script), [])
        self.assertIn("def _s2_leg():\n    return 0.04\n\n\n_s2_LEG = _s2_leg()\nSETTINGS_s2 = {", j.script)

    def test_each_import_line_belongs_to_the_step_that_wrote_its_names(self):
        # Review, Oct 29: from-imports of one module were merged into one line blamed on the first step that used
        # the module, and an ImportError never got a step repair. mathutils.radians doesn't exist.
        s3 = F.S3.replace("import bmesh\n", "import bmesh\nfrom mathutils import Vector, radians\n", 1)
        self.assertNotEqual(s3, F.S3)
        outputs = dict(F.BLENDER_OUTPUTS, s3=s3)
        j = join(F.BLENDER_PLAN, outputs)
        self.assertFalse(j.fallback, j.reasons)
        self.assertEqual(import_lines(j.script),
                         ["import bpy", "import bmesh", "from mathutils import Vector", "from mathutils import radians"])
        self.assertEqual(j.linemap.locate(script_line(j.script, "from mathutils import Vector"))["step"], "s2")
        n = script_line(j.script, "from mathutils import radians")  # s3's line, less the Vector s2 already imported
        loc = j.linemap.locate(n)
        self.assertEqual((loc["step"], loc["part"], loc["repair"]), ("s3", "import", "s3"))
        self.assertEqual(j.pieces["s3"].code.split("\n")[loc["piece_line"] - 1], "from mathutils import Vector, radians")
        check = {"check": {"outcome": "failed", "runner": "Blender 5.2.2", "line": n,
                           "source": "from mathutils import radians",
                           "error": "ImportError: cannot import name 'radians' from 'mathutils'"}}
        crash = locate_check(check, j.linemap, j.script)
        self.assertEqual((crash["repair"], crash["source_matches"]), ("s3", True))
        req = prompt.repair_request(F.BLENDER_PLAN, 2, outputs, s3, crash)
        self.assertIn("in Blender 5.2.2:\nline %d in the imports: from mathutils import radians\nImportError:"
                      % loc["piece_line"], req.messages[1]["content"])

    def test_import_lines_follow_the_pieces_statements(self):
        future = "```python\nfrom __future__ import annotations\n"
        s2 = F.S2.replace("```python\n", future, 1).replace(
            "from mathutils import Vector\n", "from mathutils import Vector\nfrom mathutils import Matrix\n", 1)
        s3 = F.S3.replace("```python\n", future, 1).replace(
            "import bmesh\n", "import bmesh\nfrom mathutils import Matrix as M, Euler\n", 1)
        j = join(F.BLENDER_PLAN, dict(F.BLENDER_OUTPUTS, s2=s2, s3=s3))
        self.assertFalse(j.fallback, j.reasons)
        self.assertEqual(import_lines(j.script), [
            "from __future__ import annotations", "import bpy", "import bmesh", "from mathutils import Vector",
            "from mathutils import Matrix", "from mathutils import Matrix as M, Euler"])
        ast.parse(j.script)
        self.assertEqual([j.linemap.locate(script_line(j.script, l))["step"] for l in import_lines(j.script)],
                         ["s2", "s1", "s3", "s2", "s2", "s3"])

    def test_failed_step_is_left_out(self):
        j = join(F.BLENDER_PLAN, dict(F.BLENDER_OUTPUTS, s2=None))
        self.assertFalse(j.fallback)
        self.assertEqual(j.failed, ["s2"])
        self.assertNotIn("def build_s2", j.script)
        self.assertNotIn("build_s2(ctx)", j.script)
        self.assertIn("ctx_key_missing", seam_codes(j))  # s3 reads ctx["objects"]["table"], which nobody made
        self.assertIn("s2 (Side table) failed", j.notes[0])

    def test_a_broken_piece_falls_back(self):
        bad = F.S2.replace("SETTINGS_s2 = ", "print('loading')\nSETTINGS_s2 = ")
        j = join(F.BLENDER_PLAN, dict(F.BLENDER_OUTPUTS, s2=bad))
        self.assertTrue(j.fallback)
        self.assertEqual(len(j.reasons), 1)
        self.assertTrue(j.reasons[0].startswith("s2: top_level_code:"), j.reasons)
        self.assertEqual(j.text, "")
        no_handoff = F.S3.split("```handoff")[0]
        self.assertIn("s3: handoff_missing", " ".join(join(F.BLENDER_PLAN, dict(F.BLENDER_OUTPUTS, s3=no_handoff)).reasons))

    def test_library_piece_is_wrapped_into_build(self):
        lib = {"output": "```python\nimport bpy\nfrom math import radians\nm = bpy.data.meshes.new('chimera_lib')\n"
                         "o = bpy.data.objects.new('chimera_lib', m)\no.rotation_euler.z = radians(45)\n"
                         "bpy.context.scene.collection.objects.link(o)\n```", "status": "library"}
        j = join(F.BLENDER_PLAN, dict(F.BLENDER_OUTPUTS, s1=lib))
        self.assertFalse(j.fallback, j.reasons)
        self.assertIn("SETTINGS_s1 = {}", j.script)
        self.assertIn("def build_s1(ctx):\n    m = bpy.data.meshes.new('chimera_lib')", j.script)
        self.assertIn("from math import radians", j.script.split("# --- s1:")[0])  # hoisted with the imports
        guarded = dict(lib, output=lib["output"].replace("\n```", "\nif __name__ == '__main__':\n    pass\n```"))
        self.assertIn("library_seam", seam_codes(join(F.BLENDER_PLAN, dict(F.BLENDER_OUTPUTS, s1=guarded))))

    def test_uses_with_no_matching_provides(self):
        h = 'uses: s2\'s ctx["objects"]["table"]'
        wrong = F.S3.replace(h, 'uses: s2\'s ctx["objects"]["desk"] and `make_desk()`')
        j = join(F.BLENDER_PLAN, dict(F.BLENDER_OUTPUTS, s3=wrong))
        msgs = [s.message for s in j.seams if s.code == "uses_unmatched"]
        self.assertEqual(len(msgs), 2, msgs)
        self.assertIn("'desk'", msgs[0])

    def test_round2_finds_the_steps_part_by_title(self):
        prev = self.j.text
        part, matched = find_part(prev, F.BLENDER_PLAN, 1, "blender")
        self.assertTrue(matched)
        self.assertTrue(part.startswith('SETTINGS_s2 = {"top_size": 0.6'))  # its settings, once, and no header
        self.assertEqual(part.count("SETTINGS_s2 = "), 1)
        self.assertNotIn("# --- s2", part)
        self.assertIn("def build_s2(ctx):", part)
        self.assertNotIn("def build_s3", part)
        self.assertNotIn("def main", part)
        # a result joined the old way (every SETTINGS_ dict in one part at the top) still gives the step's settings
        old = "```python\nimport bpy\n\n# Settings\nSETTINGS_s1 = {}\nSETTINGS_s2 = {\"top_size\": 0.6}\n\n\n" \
              "# --- s1: Floor and material ---\ndef build_s1(ctx):\n    pass\n\n\n# --- s2: Side table ---\n" \
              "def build_s2(ctx):\n    pass\n\n\ndef main():\n    pass\n```\n"
        part, matched = find_part(old, F.BLENDER_PLAN, 1, "blender")
        self.assertTrue(matched)
        self.assertEqual(part, 'SETTINGS_s2 = {"top_size": 0.6}\n\n\ndef build_s2(ctx):\n    pass')
        # the step moved to another position in the new plan: the names follow it
        plan = copy.deepcopy(F.BLENDER_PLAN)
        plan["steps"] = [plan["steps"][1], plan["steps"][0]]
        part, matched = find_part(prev, plan, 0, "blender")
        self.assertTrue(matched)
        self.assertIn("def build_s1(ctx):", part)
        self.assertIn("def _s1_box(", part)
        self.assertIn("SETTINGS_s1 = {\"top_size\"", part)
        self.assertNotIn("_s2_", part)
        # no step with that title: the result, cut to 6,000 bytes
        plan["steps"][0]["title"] = "Something new"
        part, matched = find_part(prev, plan, 0, "blender")
        self.assertFalse(matched)
        self.assertTrue(part.endswith("\n…(cut)"))

    def test_lone_step_joins_without_a_handoff(self):
        plan = copy.deepcopy(F.BLENDER_PLAN)
        plan["steps"] = plan["steps"][1:2]
        piece = F.S2.split("```handoff")[0]
        j = join(plan, {"s2": piece.replace("_s2_", "_s1_").replace("SETTINGS_s2", "SETTINGS_s1").replace(
            "build_s2", "build_s1")})
        self.assertFalse(j.fallback, j.reasons)
        self.assertIn("    build_s1(ctx)\n", j.script)
        self.assertEqual(j.assumptions, [])

    def test_alone_script_keeps_the_pieces_line_numbers(self):
        p = validate_piece(F.S3, "blender", sid="s3", deps=["s2"])
        alone = alone_script(p)
        ast.parse(alone)
        code = p.code.split("\n")
        guard = code.index('if __name__ == "__main__":')
        self.assertEqual(alone.split("\n")[:guard], code[:guard])  # a crash line there is the piece's own line
        self.assertNotIn("__main__", alone)
        self.assertTrue(alone.endswith('ctx = {"scene": bpy.context.scene, "collection": bpy.context.scene.collection, '
                                       '"objects": {}, "values": {}}\nbuild_s3(ctx)\n'))
        # after its dependencies' script: exactly one more line, in the tail, for a ctx from before ctx["values"]
        kept = alone_script(p, True)
        ast.parse(kept)
        self.assertEqual(kept.split("\n")[:guard], code[:guard])
        self.assertEqual(len(kept.split("\n")), len(alone.split("\n")) + 1)
        self.assertTrue(kept.endswith(' else {"scene": bpy.context.scene, "collection": bpy.context.scene.collection, '
                                      '"objects": {}, "values": {}}\nctx.setdefault("values", {})\nbuild_s3(ctx)\n'),
                        kept[-300:])
        named = alone_script(p, True, "ctx1", ["s9"])
        self.assertIn('\nctx = ctx1 if isinstance(globals().get("ctx1"), dict) and '
                      'isinstance(ctx1.get("objects"), dict) and "collection" in ctx1 else {', named)
        self.assertTrue(named.endswith('\nctx.setdefault("values", {})\nbuild_s3(ctx)\nbuild_s9(ctx)\n'), named[-200:])

    def test_slug(self):
        self.assertEqual(slug("Reading corner: v2!"), "reading_corner_v2")
        self.assertEqual(slug("???"), "project")


def values_piece(sid, body, provides="x", uses="none"):
    """A blender piece (a test fixture, never training data) whose build function is `body`."""
    return ("```python\n%s\nimport bpy\n\nSETTINGS_%s = {\"sofa_width\": 2.2, \"sofa_depth\": 0.9}\n\n\n"
            "def build_%s(ctx):\n%s\n\n\nif __name__ == \"__main__\":\n    build_%s({\"scene\": bpy.context.scene, "
            "\"collection\": bpy.context.scene.collection, \"objects\": {}, \"values\": {}})\n```\n\n"
            "```handoff\nprovides: %s\nuses: %s\nassumed: none\n```\n" % (F.MARK, sid, sid, body, sid, provides, uses))


READ = '    print(ctx["values"]["sofa_width"])'


def key_seams(first, second):
    """The ctx_key_missing seams of F.VALUES_PLAN joined, s1's build doing `first` and s2's doing `second`."""
    j = join(F.VALUES_PLAN, {"s1": values_piece("s1", first), "s2": values_piece("s2", second)})
    return [(s.message, s.sid) for s in j.seams if s.code == "ctx_key_missing"]


class ValuesJoinTests(unittest.TestCase):
    """ctx["values"] (contract question 1, decided Nov 4) is judged as ctx["objects"] is, each channel on its own,
    up to a write whose keys can't be read."""

    def test_the_values_pair_joins(self):
        j = join(F.VALUES_PLAN, F.VALUES_OUTPUTS)
        self.assertFalse(j.fallback, j.reasons)
        self.assertEqual(seam_codes(j), [])
        self.assertEqual({sid: p.issues for sid, p in j.pieces.items()}, {"s1": [], "s2": []})
        self.assertIn('\n    ctx = {"scene": scene, "collection": collection, "objects": {}, "values": {}}\n'
                      '    build_s1(ctx)\n    build_s2(ctx)\n    return ctx\n', j.script)
        ast.parse(j.script)

    def test_a_value_no_earlier_step_registers(self):
        self.assertEqual(key_seams("    pass", READ.replace("sofa_width", "sofa_colour")),
                         [("s2 reads ctx[\"values\"]['sofa_colour'], which no earlier step registers", "s2")])
        self.assertEqual(len(key_seams("    pass", '    print(ctx["values"].get("sofa_width", 1))')), 1)
        failed = join(F.VALUES_PLAN, {"s1": None, "s2": F.VALUES_S2})
        why = ", which no earlier step registers (the step that should have made it failed)"
        self.assertEqual([s.message for s in failed.seams if s.code == "ctx_key_missing"],
                         ["s2 reads ctx[\"values\"]['sofa_width']" + why,
                          "s2 reads ctx[\"values\"]['sofa_depth']" + why])

    def test_writes_that_register_or_hold_the_channel_back(self):
        # Contract mapper, Nov 4: with literal keys only, the natural update(SETTINGS_s1) writer before a literal
        # reader gave 2 false seams, and the gate fails a seam (SEAMS_FAIL).
        cases = {
            "a literal key": ('    ctx["values"]["sofa_width"] = SETTINGS_s1["sofa_width"]', READ),
            "a literal setdefault": ('    ctx["values"].setdefault("sofa_width", 2.0)', READ),
            "update() before": ("    ctx[\"values\"].update(SETTINGS_s1)", READ),
            "the whole dict": ("    ctx[\"values\"] = dict(SETTINGS_s1)", READ),
            "|=": ("    ctx[\"values\"] |= SETTINGS_s1", READ),
            "a computed key": ("    for k, v in SETTINGS_s1.items():\n        ctx[\"values\"][k] = v", READ),
            "a computed setdefault": ("    for k in SETTINGS_s1:\n        ctx[\"values\"].setdefault(k, 1.0)", READ),
            "its own update() first": ("    pass", "    ctx[\"values\"].update(SETTINGS_s2)\n" + READ),
            "its own update() after": ("    pass", READ + "\n    ctx[\"values\"].update(SETTINGS_s2)"),
            "its own literal write": ("    pass", '    ctx["values"]["sofa_width"] = 1\n' + READ),
        }
        for what, (first, second) in cases.items():
            with self.subTest(what):
                self.assertEqual(key_seams(first, second), [])

    def test_writes_through_a_bound_name(self):
        # Checkers, Nov 4: each of these writers gave its literal reader a false seam in the real gate (5.2.2 and
        # 5.0.1), which fails the reader though the joined script runs. A bound name isn't opaque by itself (that
        # would silence the channel behind every alias): only a computed key, update() or |= through it is.
        writes = {
            "an alias": '    v = ctx["values"]\n    v["sofa_width"] = 1',
            "a setdefault alias": '    vals = ctx.setdefault("values", {})\n    vals["sofa_width"] = 1',
            "a get alias": '    vals = ctx.get("values", {})\n    vals["sofa_width"] = 1',
            "an annotated alias": '    vals: dict = ctx["values"]\n    vals["sofa_width"] = 1',
            "an alias's setdefault": '    v = ctx["values"]\n    v.setdefault("sofa_width", 1)',
            "a store into setdefault()": '    ctx.setdefault("values", {})["sofa_width"] = 1',
            "a store into get()": '    ctx.get("values")["sofa_width"] = 1',
            "an alias bound twice": ('    v = ctx["values"]\n    v["x"] = 1\n    v = ctx.setdefault("values", {})\n'
                                     '    v["sofa_width"] = 1'),
            "an alias's update()": '    v = ctx["values"]\n    v.update(SETTINGS_s1)',
            "update() on setdefault()": '    ctx.setdefault("values", {}).update(SETTINGS_s1)',
            "an alias's computed key": '    v = ctx["values"]\n    for k in SETTINGS_s1:\n        v[k] = SETTINGS_s1[k]',
            "|= on an alias": '    v = ctx["values"]\n    v |= SETTINGS_s1',
        }
        for what, first in writes.items():
            with self.subTest(what):
                self.assertEqual(key_seams(first, READ), [])
        # ... and nothing more: another key, a name also bound to something else, a copy, another channel and a
        # read through an alias leave the seam where it was
        same = {
            "another key": '    v = ctx["values"]\n    v["sofa_depth"] = 1',
            "a name bound twice": '    v = ctx["values"]\n    v = {}\n    v["sofa_width"] = 1',
            "a copy": '    v = dict(ctx["values"])\n    v["sofa_width"] = 1',
            "another channel": '    v = ctx["objects"]\n    v["sofa_width"] = 1',
            "a read through an alias": '    v = ctx["values"]\n    print(v["sofa_width"])',
        }
        for what, first in same.items():
            with self.subTest(what):
                self.assertEqual(len(key_seams(first, READ)), 1)
        # a step's own write through one covers its own read, on either channel
        self.assertEqual(key_seams("    pass", '    objs = ctx["objects"]\n    objs["lamp"] = 1\n'
                                   '    print(ctx["objects"]["lamp"])'), [])

    def test_a_bound_name_write_is_not_asked_of_provides(self):
        # the seams only: provides_missing reads ctx_keys alone, so alias writers' unlisted keys draw no new
        # validator_warning drop
        p = validate_piece(values_piece("s1", '    v = ctx["values"]\n    v["sofa_width"] = 1', provides="chimera_sofa"),
                           "blender", sid="s1")
        self.assertEqual([i.code for i in p.issues if i.code == "provides_missing"], [])

    def test_each_channel_is_judged_on_its_own(self):
        self.assertEqual(key_seams("    ctx[\"values\"].update(SETTINGS_s1)", '    print(ctx["objects"]["lamp"])'),
                         [("s2 reads ctx[\"objects\"]['lamp'], which no earlier step registers", "s2")])
        self.assertEqual(key_seams("    ctx[\"objects\"].update({})", READ),
                         [("s2 reads ctx[\"values\"]['sofa_width'], which no earlier step registers", "s2")])
        # every objects seam in plan order, then the values ones
        self.assertEqual(key_seams('    ctx["objects"]["floor"] = ctx["values"]["rug"]',
                                   '    print(ctx["objects"]["lamp"])'),
                         [("s2 reads ctx[\"objects\"]['lamp'], which no earlier step registers", "s2"),
                          ("s1 reads ctx[\"values\"]['rug'], which no earlier step registers", "s1")])

    def test_alone_the_reader_gets_an_empty_values_dict(self):
        p = validate_piece(F.VALUES_S2, "blender", sid="s2", deps=["s1"])
        alone = alone_script(p)
        self.assertTrue(alone.endswith('\n\nctx = {"scene": bpy.context.scene, "collection": '
                                       'bpy.context.scene.collection, "objects": {}, "values": {}}\nbuild_s2(ctx)\n'),
                        alone[-200:])
        # the harness builds ctx just as the mode rule's guard tells the worker to
        guard = re.search(r"build_\{sid\}\((\{.*?\})\)\. Chimera", T.MODE_BLENDER).group(1)
        self.assertIn("\nctx = " + guard + "\n", alone)

    def test_a_ctx_from_before_values_gets_one_in_the_tail(self):
        # The eval runner's after_deps can put a dependency's older script first; its ctx has no "values", and the
        # reader died on KeyError 'values' instead of making its stand-ins (real Blender, Nov 4).
        p = validate_piece(F.VALUES_S2, "blender", sid="s2", deps=["s1"])
        kept = alone_script(p, True)
        tail = kept.split("\n\n\n")[-1]
        older = {"scene": "scene", "collection": "collection", "objects": {"floor": "floor"}}
        seen = []
        exec(tail, {"ctx": older, "bpy": types.SimpleNamespace(context=None), "build_s2": seen.append})
        self.assertEqual(len(seen), 1)
        self.assertIs(seen[0], older)  # passed on, with what the dependencies registered
        self.assertEqual(older, {"scene": "scene", "collection": "collection", "objects": {"floor": "floor"},
                                 "values": {}})
        given = {"scene": "scene", "collection": "collection", "objects": {}, "values": {"sofa_width": 2.2}}
        exec(tail, {"ctx": given, "bpy": None, "build_s2": seen.append})
        self.assertEqual(seen[1]["values"], {"sofa_width": 2.2})  # a ctx that has one keeps it


class ScriptJoinTests(unittest.TestCase):
    def test_joined_script_runs_and_main_is_called_at_the_end(self):
        j = join(F.SCRIPT_PLAN, {"a": F.SCRIPT_A, "b": F.SCRIPT_B})
        self.assertFalse(j.fallback, j.reasons)
        self.assertEqual(j.script_kind, "run_python")
        self.assertEqual(seam_codes(j), [])
        self.assertEqual(j.script.count("from collections import Counter"), 1)
        self.assertTrue(j.script.rstrip().endswith('if __name__ == "__main__":\n    main()'))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "script.py")
            with open(path, "w") as f:
                f.write(j.script)
            out = subprocess.run([sys.executable, "-I", path], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.split(), ["the", "3", "and", "2", "cat", "1"])
        loc = j.linemap.locate(script_line(j.script, "def top_words(counts, n):"))
        self.assertEqual((loc["step"], loc["part"], loc["function"], loc["repair"]), ("s2", "code", "top_words", "s2"))

    def test_two_mains_and_duplicate_names_are_seams(self):
        a = F.SCRIPT_A.replace("def count_words(text):", "def main():\n    pass\n\n\ndef count_words(text):")
        j = join(F.SCRIPT_PLAN, {"a": a, "b": F.SCRIPT_B})
        self.assertIn("duplicate_name", seam_codes(j))

    def test_no_main_is_a_seam(self):
        # Review, Oct 29: with no main() the joined file only defined functions, Chimera's check passed it in 0.0 s,
        # and nothing said so.
        b = F.SCRIPT_B.replace("def main():", "def report():").replace('if __name__ == "__main__":\n    main()\n', "")
        self.assertNotIn("def main", b)
        j = join(F.SCRIPT_PLAN, {"a": F.SCRIPT_A, "b": b})
        self.assertFalse(j.fallback, j.reasons)
        self.assertEqual(seam_codes(j), ["missing_entry_point"])
        self.assertNotIn("__main__", j.script)
        with tempfile.TemporaryDirectory() as d:  # what the check would see: it runs, and prints nothing
            path = os.path.join(d, "script.py")
            with open(path, "w") as f:
                f.write(j.script)
            out = subprocess.run([sys.executable, "-I", path], capture_output=True, text=True, timeout=30)
        self.assertEqual((out.returncode, out.stdout), (0, ""))
        # a step's own main() stays in its part for round 2 (only the main guard ends a python-script part)
        good = join(F.SCRIPT_PLAN, {"a": F.SCRIPT_A, "b": F.SCRIPT_B})
        part, matched = find_part(good.text, F.SCRIPT_PLAN, 1, "python-script")
        self.assertTrue(matched)
        self.assertIn("def main():", part)
        self.assertNotIn("__main__", part)


class FilesJoinTests(unittest.TestCase):
    def test_merge_by_path_with_parts(self):
        j = join(F.FILES_PLAN, {"s1": F.FILES_1, "s2": F.FILES_2, "s3": F.FILES_3})
        self.assertFalse(j.fallback, j.reasons)
        self.assertEqual(seam_codes(j), [])
        self.assertEqual([(f["path"], f["steps"]) for f in j.files],
                         [("notes/store.py", ["s1", "s2"]), ("notes/cli.py", ["s3"])])
        store = j.files[0]["body"]
        self.assertLess(store.index("import re"), store.index("class Store"))
        self.assertLess(store.index("class Store"), store.index("def search"))
        self.assertIn("File: notes/store.py\n```python\n", j.text)
        with tempfile.TemporaryDirectory() as d:  # the merged project runs
            for f in j.files:
                os.makedirs(os.path.join(d, os.path.dirname(f["path"])), exist_ok=True)
                with open(os.path.join(d, f["path"]), "w") as fh:
                    fh.write(f["body"] + "\n")
            out = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.'); from notes.cli import main; main()"], cwd=d,
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(out.stdout.strip(), "['buy milk']", out.stderr)

    def test_unresolved_import_and_conflicts(self):
        bad_cli = F.FILES_3.replace("from notes.store import Store, search", "from notes.store import Store, find")
        j = join(F.FILES_PLAN, {"s1": F.FILES_1, "s2": F.FILES_2, "s3": bad_cli})
        self.assertIn("import_unresolved", seam_codes(j))
        self.assertIn("doesn't define find", " ".join(s.message for s in j.seams))
        full_again = F.FILES_2.replace("File: notes/store.py (part)", "File: notes/store.py")
        self.assertIn("file_conflict", seam_codes(join(F.FILES_PLAN, {"s1": F.FILES_1, "s2": full_again, "s3": F.FILES_3})))
        code_part = F.FILES_2.replace("import re\n", "import re\nprint('loaded')\n")
        self.assertIn("part_not_mergeable", seam_codes(join(F.FILES_PLAN, {"s1": F.FILES_1, "s2": code_part, "s3": F.FILES_3})))

    def test_merge_python_keeps_the_full_file_and_its_guard_last(self):
        base = "import os\n\n\ndef a():\n    return 1\n\n\nif __name__ == '__main__':\n    a()\n"
        out = merge_python(base, [("s2", "import os\nimport sys\n\n\ndef b():\n    return 2\n")])
        self.assertEqual(out, "import os\nimport sys\n\n\ndef a():\n    return 1\n\n\ndef b():\n    return 2\n\n\n"
                              "if __name__ == '__main__':\n    a()\n")
        self.assertIsNone(merge_python(base, [("s2", "x = compute()\nprint(x)\n")]))


class SectionJoinTests(unittest.TestCase):
    def test_sections_in_plan_order(self):
        j = join(F.SECTION_PLAN, {"s1": F.SECTION_1, "s2": F.SECTION_2})
        self.assertFalse(j.fallback, j.reasons)
        self.assertEqual(j.text.split("\n\n")[0], "# Tea guide")
        self.assertLess(j.text.index("## Green tea"), j.text.index("## Black tea"))
        self.assertNotIn("handoff", j.text)
        self.assertIsNone(j.script)
        self.assertEqual(j.assumptions, [("s2", "the reader knows what oxidation is")])
        part, matched = find_part(j.text, F.SECTION_PLAN, 1, "section")
        self.assertTrue(matched)
        self.assertEqual(part, "## Black tea\n\nBlack tea is fully oxidised before it is dried. (fixture text)")

    def test_editor_hook(self):
        # The plan's "then the editor joins them" isn't written (a new frozen prompt); join exposes the hook.
        outputs = {"s1": F.SECTION_1, "s2": F.SECTION_2}
        j = join(F.SECTION_PLAN, outputs)
        self.assertTrue(j.editor_wanted)
        self.assertFalse(j.edited)
        self.assertEqual([(x["mode"], x["steps"]) for x in j.parts], [("section", ["s1"]), ("section", ["s2"])])
        self.assertEqual(j.text, "\n\n".join(["# Tea guide"] + [x["text"] for x in j.parts]) + "\n")
        seen = []

        def editor(joined):
            seen.append(joined)
            return "# Tea guide\n\nEdited. (fixture text)\n\n\n"

        e = join(F.SECTION_PLAN, outputs, editor=editor)
        self.assertEqual(len(seen), 1)
        self.assertEqual((e.text, e.edited, e.raw_text), ("# Tea guide\n\nEdited. (fixture text)\n", True, j.text))
        self.assertTrue(e.to_dict()["edited"])
        kept = join(F.SECTION_PLAN, outputs, editor=lambda joined: None)  # no answer: the concatenation stays
        self.assertEqual((kept.text, kept.edited), (j.text, False))
        # not called for one section, a code plan, or a fallback
        lone = copy.deepcopy(F.SECTION_PLAN)
        lone["steps"] = lone["steps"][:1]
        for plan, outs in ((lone, {"s1": F.SECTION_1.split("```handoff")[0]}), (F.BLENDER_PLAN, F.BLENDER_OUTPUTS),
                           (F.SECTION_PLAN, {"s1": F.SECTION_1, "s2": "No heading. (fixture text)"})):
            r = join(plan, outs, editor=editor)
            self.assertFalse(r.editor_wanted or r.edited)
        self.assertEqual(len(seen), 1)


class UsesNamesTests(unittest.TestCase):
    def test_code_like_names_only(self):
        self.assertEqual(uses_names("s1's Store class (notes/store.py) and its add() method, e.g. as told"),
                         ["notes/store.py", "add"])
        self.assertEqual(uses_names('s2\'s ctx["objects"]["table"] and `make_leg`'), ["objects", "table", "make_leg"])
        self.assertEqual(uses_names("the floor height from s1, version 5.0"), [])

    def test_only_a_decimal_digit_first_rules_a_word_out(self):
        # Go's unicode.IsDigit leaves superscripts out and str.isdigit doesn't: the Nov 4 parity run's reseeded uses
        # lines reached this one, a path that Go read as a name and the prototype didn't.
        self.assertEqual(uses_names("²x_y10.123/abcStore.alla/b.py"), ["²x_y10.123/abcStore.alla/b.py"])
        self.assertEqual(uses_names("2x_y10.123/abcStore.alla/b.py"), [])
        self.assertEqual(uses_names('s1\'s ctx["values"]["sofa_width"]'), ["values", "sofa_width"])  # as objects


# Hand-made uses lines and the chunks the uses reader gives them (contract question 4, Nov 5): test fixtures, never
# training data. app/hydra_assemble_test.go's TestUsesChunksGiveEachItemToTheStepAfterIt holds the same table.
USES_LINES = [
    ("table_top from s1, lamp_shade from s2", [[["s1"], "table_top from "], [["s1"], "s1"], [["s2"], " lamp_shade from "], [["s2"], "s2"]]),
    ("s1: table_top; s2: lamp_shade", [[["s1"], "s1: table_top"], [["s2"], " "], [["s2"], "s2: lamp_shade"]]),
    ("table_top (s1), lamp_shade (s2)", [[["s1"], "table_top ("], [["s1"], "s1)"], [["s2"], " lamp_shade ("], [["s2"], "s2)"]]),
    ("table_top (from s1, for the height), lamp_shade (from s2, aimed later)", [[["s1"], "table_top (from "], [["s1"], "s1, for the height)"], [["s2"], " lamp_shade (from "], [["s2"], "s2, aimed later)"]]),
    ("ctx[\"values\"][\"sofa_width\"] from s1, ctx[\"objects\"][\"sofa\"] from s2", [[["s1"], "ctx[\"values\"][\"sofa_width\"] from "], [["s1"], "s1"], [["s2"], " ctx[\"objects\"][\"sofa\"] from "], [["s2"], "s2"]]),
    ("s1: ctx[\"values\"][\"sofa_width\"]; s2: ctx[\"objects\"][\"sofa\"]", [[["s1"], "s1: ctx[\"values\"][\"sofa_width\"]"], [["s2"], " "], [["s2"], "s2: ctx[\"objects\"][\"sofa\"]"]]),
    ("s1: table_top, lamp_shade from s2", [[["s1"], "s1: table_top"], [["s2"], " lamp_shade from "], [["s2"], "s2"]]),
    ("s1: table_top, leg_height", [[["s1"], "s1: table_top"], [["s1"], " leg_height"]]),
    ("sofa, coffee_table from s2", [[["s2"], "sofa"], [["s2"], " coffee_table from "], [["s2"], "s2"]]),
    ("table_top from s1, lamp_shade from s2 (failed)", [[["s1"], "table_top from "], [["s1"], "s1"], [["s2"], " lamp_shade from "], [["s2"], "s2 (failed)"]]),
    ("table_top from s1; s2: lamp_shade (failed)", [[["s1"], "table_top from "], [["s1"], "s1"], [["s2"], " "], [["s2"], "s2: lamp_shade (failed)"]]),
    ("s2: lamp_shade (failed), table_top from s1", [[["s2"], "s2: lamp_shade (failed)"], [["s1"], " table_top from "], [["s1"], "s1"]]),
    ("table_top from s1, s2: lamp_shade (failed)", [[["s1"], "table_top from "], [["s1"], "s1"], [["s2"], " "], [["s2"], "s2: lamp_shade (failed)"]]),
    ("table_top from s1 and lamp_shade from s2", [[["s1"], "table_top from "], [["s1"], "s1 "], [["s2"], "and lamp_shade from "], [["s2"], "s2"]]),
    ("s1: table_top and lamp_shade from s2", [[["s1"], "s1: table_top "], [["s2"], "and lamp_shade from "], [["s2"], "s2"]]),
    ("frame_obj from s1 with its leg_objs and slat_objs from s2", [[["s1"], "frame_obj from "], [["s1"], "s1 with its leg_objs "], [["s2"], "and slat_objs from "], [["s2"], "s2"]]),
    ("frame_obj from s1 plus slat_objs from s2", [[["s1"], "frame_obj from "], [["s1"], "s1"], [["s2"], " plus slat_objs from "], [["s2"], "s2"]]),
    ("load_rows() (s1) feeds totals() (s2)", [[["s1"], "load_rows() ("], [["s1"], "s1"], [["s2"], ") feeds totals() ("], [["s2"], "s2)"]]),
    ("table_top \u2014 s1, lamp_shade \u2014 s2", [[["s1"], "table_top \u2014 "], [["s1"], "s1"], [["s2"], " lamp_shade \u2014 "], [["s2"], "s2"]]),
    ("s2 \u2014 make_leg(), leg_count; s1 \u2014 table_top", [[["s2"], "s2 \u2014 make_leg()"], [["s2"], " leg_count"], [["s1"], " "], [["s1"], "s1 \u2014 table_top"]]),
    ("the lamp (s2) \u2014 lamp_shade, lamp_cord; the table (s1) \u2014 table_top", [[["s2"], "the lamp ("], [["s2"], "s2) \u2014 lamp_shade"], [["s2"], " lamp_cord"], [["s1"], " the table ("], [["s1"], "s1) \u2014 table_top"]]),
    ("keys table_top/leg_height (s1) \u2014 lamp_shade (s2)", [[["s1"], "keys table_top/leg_height ("], [["s1"], "s1) "], [["s2"], "\u2014 lamp_shade ("], [["s2"], "s2)"]]),
    ("the outputs of s1 and s2: table_top, lamp_shade", [[["s1", "s2"], "the outputs of "], [["s1", "s2"], "s1 and "], [["s1", "s2"], "s2: table_top"], [["s1", "s2"], " lamp_shade"]]),
    ("sofa_body, floor_lamp from s2 and s3", [[["s2", "s3"], "sofa_body"], [["s2", "s3"], " floor_lamp from "], [["s2", "s3"], "s2 and "], [["s2", "s3"], "s3"]]),
    ("Acme_Logo from s1/s4", [[["s1", "s4"], "Acme_Logo from "], [["s1", "s4"], "s1/s4"]]),
    ("render_engine from s1, s2, s3 (merged)", [[["s1", "s2", "s3"], "render_engine from "], [["s1", "s2", "s3"], "s1"], [["s1", "s2", "s3"], " "], [["s1", "s2", "s3"], "s2"], [["s1", "s2", "s3"], " "], [["s1", "s2", "s3"], "s3 (merged)"]]),
    ("key_light_obj, product_camera from s2\u2013s6", [[["s2", "s3", "s4", "s5", "s6"], "key_light_obj"], [["s2", "s3", "s4", "s5", "s6"], " product_camera from "], [["s2", "s3", "s4", "s5", "s6"], "s2\u2013"], [["s2", "s3", "s4", "s5", "s6"], "s6"]]),
    ("frame_start from s1-s3", [[["s1", "s2", "s3"], "frame_start from "], [["s1", "s2", "s3"], "s1-"], [["s1", "s2", "s3"], "s3"]]),
    ("x from s1\u2013s99", [[["s1", "s99"], "x from "], [["s1", "s99"], "s1\u2013"], [["s1", "s99"], "s99"]]),
    ("app.py/db.py (s2, s3), todo.py (s1)", [[["s2", "s3"], "app.py/db.py ("], [["s2", "s3"], "s2, "], [["s2", "s3"], "s3)"], [["s1"], " todo.py ("], [["s1"], "s1)"]]),
    ("table_top (s2 reads it) from s1", [[["s1"], "table_top "], [["s2"], "("], [["s2"], "s2 reads it)"], [["s1"], " from "], [["s1"], "s1"]]),
    ("base_plate from s1 (s2 failed, so bolt_holes is a stand-in)", [[["s1"], "base_plate from "], [["s1"], "s1 "], [["s2"], "("], [["s2"], "s2 failed, so bolt_holes is a stand-in)"]]),
    ("scene_root; s1: table_top", [[["s1"], " "], [["s1"], "s1: table_top"]]),
    ("table_top, leg_height; lamp_shade from s2", [[["s2"], " lamp_shade from "], [["s2"], "s2"]]),
    ("camera from s4, island, rocks", [[["s4"], "camera from "], [["s4"], "s4"]]),
    ("Priya Shah's email from s3's guide", [[["s3"], "Priya Shah's email from "], [["s3"], "s3's guide"]]),
    ("src/s2/legs.py from s2, top.py from s1", [[["s2"], "src/s2/legs.py from "], [["s2"], "s2"], [["s1"], " top.py from "], [["s1"], "s1"]]),
    ("s1.variables, s2.furniture", [[["s1"], "s1.variables"], [["s2"], " "], [["s2"], "s2.furniture"]]),
    ("{\"s1\": [\"table_top\"], \"s2\": [\"lamp_shade\"]}", [[["s1"], "{"], [["s1"], "\"s1\": [\"table_top\"], "], [["s2"], "\"s2\": [\"lamp_shade\"]}"]]),
    ("s1's Store, s2's search()", [[["s1"], "s1's Store"], [["s2"], " "], [["s2"], "s2's search()"]]),
    ("table_top from s1\u0662", [[["s1\u0662"], "table_top from "], [["s1\u0662"], "s1\u0662"]]),
    ("s1:\u00a0table_top; s2\uff1alamp_shade", [[["s1"], "s1:\u00a0table_top"], [["s2"], " "], [["s2"], "s2\uff1alamp_shade"]]),
    ("table_top from step s1 and lamp_shade from step s2", [[["s1"], "table_top from step "], [["s1"], "s1 "], [["s2"], "and lamp_shade from step "], [["s2"], "s2"]]),
    ("none", []),
    ("", []),
    # forms seen on the stored records
    ("settings from s1; island, fridge from s2; key_light from s3", [[["s1"], "settings from "], [["s1"], "s1"], [["s2"], " island"], [["s2"], " fridge from "], [["s2"], "s2"], [["s3"], " key_light from "], [["s3"], "s3"]]),
    ("keys table_top, leg_height, lamp_shade from s2 and s3", [[["s2", "s3"], "keys table_top"], [["s2", "s3"], " leg_height"], [["s2", "s3"], " lamp_shade from "], [["s2", "s3"], "s2 and "], [["s2", "s3"], "s3"]]),
    ("variables (sofa_width, sofa_depth from s1); objects sofa_body, sofa_legs from s2", [[["s1"], "variables (sofa_width, sofa_depth from "], [["s1"], "s1)"], [["s2"], " objects sofa_body"], [["s2"], " sofa_legs from "], [["s2"], "s2"]]),
    ("table_top (from s1, for aiming the camera), lamp_shade (from s2, for the light)", [[["s1"], "table_top (from "], [["s1"], "s1, for aiming the camera)"], [["s2"], " lamp_shade (from "], [["s2"], "s2, for the light)"]]),
    ("base_plate, bolt_holes from s1 and s2 (s2 failed)", [[["s1", "s2"], "base_plate"], [["s1", "s2"], " bolt_holes from "], [["s1", "s2"], "s1 and "], [["s1", "s2"], "s2 "], [["s2"], "("], [["s2"], "s2 failed)"]]),
    # known misses, pinned as they read: made_here goes to s2, SETTINGS_s1 is no id (round 8's seams judge it against
    # s1 all the same), "s2's" joins the group, leg_height stays with s1, table_top is s2's, and an id in a path is
    # still an id (round 8 reads "frame_obj from s1 with its leg_objs plus slat_objs from s2" right)
    ("table_top from s1, made_here (own), lamp_shade from s2", [[["s1"], "table_top from "], [["s1"], "s1"], [["s2"], " made_here (own)"], [["s2"], " lamp_shade from "], [["s2"], "s2"]]),
    ("SETTINGS_s1 values, lamp_shade from s2", [[["s2"], "SETTINGS_s1 values"], [["s2"], " lamp_shade from "], [["s2"], "s2"]]),
    ("table_top from s1 and s2's lamp_shade", [[["s1", "s2"], "table_top from "], [["s1", "s2"], "s1 and "], [["s1", "s2"], "s2's lamp_shade"]]),
    ("s1: table_top, leg_height, lamp_shade from s2", [[["s1"], "s1: table_top"], [["s1"], " leg_height"], [["s2"], " lamp_shade from "], [["s2"], "s2"]]),
    ("s1, s2: table_top", [[["s1"], "s1"], [["s2"], " "], [["s2"], "s2: table_top"]]),
    ("src/s2/legs.py from s1", [[["s2"], "src/s2"], [["s1"], "/legs.py from "], [["s1"], "s1"]]),
    # more forms: open ids, arrows, leads, marks, quoted and bracketed ids, ranges past _USES_RANGE_MAX
    ("s2's slat_objs and frame_obj from s1", [[["s2"], "s2's slat_objs "], [["s1"], "and frame_obj from "], [["s1"], "s1"]]),
    ("table_top from s1 (see s2 for lamp_shade)", [[["s1"], "table_top from "], [["s1"], "s1 "], [["s2"], "(see "], [["s2"], "s2 for lamp_shade)"]]),
    ("Acme_Logo (s1) -> logo_mat", [[["s1"], "Acme_Logo ("], [["s1"], "s1) -> logo_mat"]]),
    ("s1 => table_top, s2 -> lamp_shade", [[["s1"], "s1 => table_top"], [["s2"], " "], [["s2"], "s2 -> lamp_shade"]]),
    ("from s1: table_top; from s2: lamp_shade", [[["s1"], "from "], [["s1"], "s1: table_top"], [["s2"], " from "], [["s2"], "s2: lamp_shade"]]),
    ("Steps s1 and s2: table_top, lamp_shade", [[["s1", "s2"], "Steps "], [["s1", "s2"], "s1 and "], [["s1", "s2"], "s2: table_top"], [["s1", "s2"], " lamp_shade"]]),
    ("**s1**: table_top; **s2**: lamp_shade", [[["s1"], "**"], [["s1"], "s1**: table_top"], [["s2"], " **"], [["s2"], "s2**: lamp_shade"]]),
    ("table_top from s1, s2: lamp_shade (failed), leg_height from s3", [[["s1"], "table_top from "], [["s1"], "s1"], [["s2"], " "], [["s2"], "s2: lamp_shade (failed)"], [["s3"], " leg_height from "], [["s3"], "s3"]]),
    ("s4 (failed): lamp_shade", [[["s4"], "s4 (failed): lamp_shade"]]),
    ("table_top from s1, s2, s3 (merged), lamp_shade from s4", [[["s1", "s2", "s3"], "table_top from "], [["s1", "s2", "s3"], "s1"], [["s1", "s2", "s3"], " "], [["s1", "s2", "s3"], "s2"], [["s1", "s2", "s3"], " "], [["s1", "s2", "s3"], "s3 (merged)"], [["s4"], " lamp_shade from "], [["s4"], "s4"]]),
    ("x from s1\u2013s12", [[["s1", "s12"], "x from "], [["s1", "s12"], "s1\u2013"], [["s1", "s12"], "s12"]]),
    ("x from s3-s1", [[["s3", "s1"], "x from "], [["s3", "s1"], "s3-"], [["s3", "s1"], "s1"]]),
    # round 8 (Nov 5, the user's yes): "<id>'s name" and "<id> name" pairs after a lead with no name read forward
    # (rule 5b), not after "from", not when a run isn't a pair, and not with a name between a pair and the next id
    # (there lamp_obj, and shade_obj, go to s2); the items around a pair item read as round 7 reads them (rug_mesh is
    # no step's, sofa_obj is s3's and then s1's)
    ("Uses s1's table_top with s2's lamp_shade", [[["s1"], "Uses "], [["s1"], "s1's table_top with "], [["s2"], "s2's lamp_shade"]]),
    ("the s1 table_top with the s2 lamp_shade", [[["s1"], "the "], [["s1"], "s1 table_top with the "], [["s2"], "s2 lamp_shade"]]),
    ("Combines s1 table_top & s2 lamp_shade", [[["s1"], "Combines "], [["s1"], "s1 table_top & "], [["s2"], "s2 lamp_shade"]]),
    ("uses s1's table_top as the base for s2's lamp_shade", [[["s1"], "uses "], [["s1"], "s1's table_top as the base for "], [["s2"], "s2's lamp_shade"]]),
    ("Uses s1's table_top with s2's lamp_shade, rug_mesh", [[["s1"], "Uses "], [["s1"], "s1's table_top with "], [["s2"], "s2's lamp_shade"]]),
    ("chair from s2 table_obj from s1 rug_obj", [[["s2"], "chair from "], [["s2"], "s2"], [["s1"], " table_obj from "], [["s1"], "s1 rug_obj"]]),
    ("Combines s1 table_top & lamp_shade from s2", [[["s1"], "Combines "], [["s1"], "s1"], [["s2"], " table_top & lamp_shade from "], [["s2"], "s2"]]),
    ("Extends s1's scene with lamp_obj from s2's output", [[["s1"], "Extends "], [["s1"], "s1"], [["s2"], "'s scene with lamp_obj from "], [["s2"], "s2's output"]]),
    ("Uses s1 table_obj with lamp_obj plus shade_obj made in s2 lamp.py", [[["s1"], "Uses "], [["s1"], "s1"], [["s2"], " table_obj with lamp_obj plus shade_obj made in "], [["s2"], "s2 lamp.py"]]),
    ("Uses s1's table_top and s2's lamp_shade, sofa_obj, rug_mesh from s3", [[["s1"], "Uses "], [["s1"], "s1's table_top "], [["s2"], "and "], [["s2"], "s2's lamp_shade"], [["s3"], " sofa_obj"], [["s3"], " rug_mesh from "], [["s3"], "s3"]]),
    ("sofa_obj, Uses s1's table_top with s2's lamp_shade", [[["s1"], "sofa_obj"], [["s1"], " Uses "], [["s1"], "s1's table_top with "], [["s2"], "s2's lamp_shade"]]),
    # a list broken by plus after "with its" or "with their" (rules 6b and 7): what stands between "with" and the
    # break stays with the id before it; not past a mark, not after a bare "with" (totals_df and lamp_obj are s2's),
    # not without "with" right after the id, and not before a word with no name
    ("frame_obj from s1 with its leg_objs plus slat_objs from s2", [[["s1"], "frame_obj from "], [["s1"], "s1 with its leg_objs "], [["s2"], "plus slat_objs from "], [["s2"], "s2"]]),
    ("frame_obj from s1 with its leg_objs plus its seat_rail plus slat_objs from s2", [[["s1"], "frame_obj from "], [["s1"], "s1 with its leg_objs plus its seat_rail "], [["s2"], "plus slat_objs from "], [["s2"], "s2"]]),
    ("frame_obj from s1 with its leg_objs PLUS slat_objs from s2", [[["s1"], "frame_obj from "], [["s1"], "s1 with its leg_objs "], [["s2"], "PLUS slat_objs from "], [["s2"], "s2"]]),
    ("frame_obj (s1) With its leg_objs plus the slat_objs (s2)", [[["s1"], "frame_obj ("], [["s1"], "s1) With its leg_objs "], [["s2"], "plus the slat_objs ("], [["s2"], "s2)"]]),
    ("frame_objs from s1 with their leg_objs plus slat_objs from s2", [[["s1"], "frame_objs from "], [["s1"], "s1 with their leg_objs "], [["s2"], "plus slat_objs from "], [["s2"], "s2"]]),
    ("Joins rows_df from s1 with totals_df plus summary_df from s2", [[["s1"], "Joins rows_df from "], [["s1"], "s1"], [["s2"], " with totals_df plus summary_df from "], [["s2"], "s2"]]),
    ("table_obj from s1 with lamp_obj plus rug_obj from s2", [[["s1"], "table_obj from "], [["s1"], "s1"], [["s2"], " with lamp_obj plus rug_obj from "], [["s2"], "s2"]]),
    ("load_rows() (s1) feeds totals() plus save_rows() (s2)", [[["s1"], "load_rows() ("], [["s1"], "s1"], [["s2"], ") feeds totals() plus save_rows() ("], [["s2"], "s2)"]]),
    ("table_top from s1 with its leg_mesh and seat_mesh plus lamp_shade from s2", [[["s1"], "table_top from "], [["s1"], "s1 with its leg_mesh "], [["s2"], "and seat_mesh plus lamp_shade from "], [["s2"], "s2"]]),
    ("frame_obj from s1 with its leg_objs plus, from s2, slat_objs", [[["s1"], "frame_obj from "], [["s1"], "s1 with its leg_objs plus"], [["s2"], " from "], [["s2"], "s2"], [["s2"], " slat_objs"]]),
    ("table_top from s1 then its leg_mesh, lamp_shade from s2", [[["s1"], "table_top from "], [["s1"], "s1 then its leg_mesh"], [["s2"], " lamp_shade from "], [["s2"], "s2"]]),
    # round 8's known misses, pinned as round 7 reads them (its other rules were taken out): an arrow after a suffix
    # id gives it the names after the arrow (lamp_obj is s1's); a second list after a full stop, "|" or then stays
    # with the id before (lamp_shade is s1's); a bare item that says failed is merged (table_top is s1/s2's); an item
    # after a lead that says failed stays with it (table_top is s2's); a forward id's list broken by plus (lamp_shade
    # is s1's), a purpose clause (sofa_obj is s1's), a break before a colon (lamp_shade is s1's), and a list broken by
    # then or also after "with" (leg_mesh is s2's)
    ("table_obj (s1) -> lamp_obj (s2)", [[["s1"], "table_obj ("], [["s1"], "s1) -> lamp_obj ("], [["s2"], "s2)"]]),
    ("table_top from s1. Also lamp_shade, rug_mesh from s2", [[["s1"], "table_top from "], [["s1"], "s1. Also lamp_shade"], [["s2"], " rug_mesh from "], [["s2"], "s2"]]),
    ("table_top from s1 | lamp_shade, rug_mesh from s2", [[["s1"], "table_top from "], [["s1"], "s1 | lamp_shade"], [["s2"], " rug_mesh from "], [["s2"], "s2"]]),
    ("table_top from s1 then lamp_shade, rug_mesh from s2", [[["s1"], "table_top from "], [["s1"], "s1 then lamp_shade"], [["s2"], " rug_mesh from "], [["s2"], "s2"]]),
    ("table_top from s1, s2 (failed)", [[["s1", "s2"], "table_top from "], [["s1", "s2"], "s1"], [["s1", "s2"], " "], [["s1", "s2"], "s2 (failed)"]]),
    ("s2: lamp_shade (failed), table_top, table_legs from s1", [[["s2"], "s2: lamp_shade (failed)"], [["s2"], " table_top"], [["s1"], " table_legs from "], [["s1"], "s1"]]),
    ("From s1 table_top plus lamp_shade from s2", [[["s1"], "From "], [["s1"], "s1 table_top plus lamp_shade from "], [["s2"], "s2"]]),
    ("sofa_width, sofa_depth from s1 for placing sofa_obj, rug_obj from s2", [[["s1"], "sofa_width"], [["s1"], " sofa_depth from "], [["s1"], "s1 for placing sofa_obj"], [["s2"], " rug_obj from "], [["s2"], "s2"]]),
    ("table_top from s1. Then: lamp_shade, rug_mesh from s2", [[["s1"], "table_top from "], [["s1"], "s1. Then: lamp_shade"], [["s2"], " rug_mesh from "], [["s2"], "s2"]]),
    ("table_top from s1 with its leg_mesh then lamp_shade from s2", [[["s1"], "table_top from "], [["s1"], "s1"], [["s2"], " with its leg_mesh then lamp_shade from "], [["s2"], "s2"]]),
    ("table_top from s1 with leg_mesh also lamp_shade from s2", [[["s1"], "table_top from "], [["s1"], "s1"], [["s2"], " with leg_mesh also lamp_shade from "], [["s2"], "s2"]]),
    # round 7's reading of forms round 8's other rules read worse, kept: arrows after a lead word, an abbreviation, a
    # continuation and a failure word that doesn't say a step failed
    ("Uses s1 -> table_top s2: lamp_shade", [[["s1"], "Uses "], [["s1"], "s1 -> table_top "], [["s2"], "s2: lamp_shade"]]),
    ("Uses s1 -> table_top s2 -> lamp_shade", [[["s1"], "Uses "], [["s1"], "s1 -> table_top "], [["s2"], "s2 -> lamp_shade"]]),
    ("table_top from s1 incl. leg_mesh, lamp_shade from s2", [[["s1"], "table_top from "], [["s1"], "s1 incl. leg_mesh"], [["s2"], " lamp_shade from "], [["s2"], "s2"]]),
    ("table_top from s1. leg_mesh too, lamp_shade from s2", [[["s1"], "table_top from "], [["s1"], "s1. leg_mesh too"], [["s2"], " lamp_shade from "], [["s2"], "s2"]]),
    ("table_top from s1, s2 (no failures)", [[["s1", "s2"], "table_top from "], [["s1", "s2"], "s1"], [["s1", "s2"], " "], [["s1", "s2"], "s2 (no failures)"]]),
]

# Round 8 (Nov 5): uses lines on hand-made pieces that hold SETTINGS dicts (test fixtures, never training data): s1
# makes table_top and SETTINGS_s1 {"lamp_h"}, s2 lamp_shade, s3 is the piece; (uses, failed steps, seams). The same
# table is in app/hydra_assemble_test.go's TestUsesSeamsReadGroups.
USES_SEAMS_ROUND8 = [
    # its own SETTINGS, in an aside
    ("Plank from s1 (parameters taken from own SETTINGS_s3)", [], []),
    # a key s1's SETTINGS holds
    ("lamp_shade from s2 sized by SETTINGS_s1[\"lamp_h\"]", [], []),
    # one it lacks: a seam from s1, though s2 failed
    ("lamp_shade from s2 sized by SETTINGS_s1[\"lamp_w\"]", ["s2"], ["s3 uses 'lamp_w' from s1, which s1 doesn't provide"]),
    # s1 failed: nothing
    ("lamp_shade from s2 sized by SETTINGS_s1[\"lamp_w\"]", ["s1"], []),
    # SETTINGS_s4 isn't in the join
    ("lamp_shade from s2 (falls back to SETTINGS_s4 defaults)", [], []),
    # SETTINGS_s2 is s2's, whatever item it is in
    ("SETTINGS_s2 from s1", [], []),
    # a key that also stands outside its chain stays with its item
    ("width_m from s2 (overrides SETTINGS_s1[\"width_m\"])", [], ["s3 uses 'width_m' from s2, which s2 doesn't provide"]),
    # a line with no step id: SETTINGS_s1's key is still s1's
    ("SETTINGS_s1[\"lamp_w\"]", [], ["s3 uses 'lamp_w' from s1, which s1 doesn't provide"]),
    ("SETTINGS_s1[\"lamp_h\"], panel_array", [], []),
    # text no step reads
    ("lamp_shade from s2, SETTINGS_s1[\"lamp_w\"] for its height", [], ["s3 uses 'lamp_w' from s1, which s1 doesn't provide"]),
    # s1 failed: nothing
    ("SETTINGS_s1[\"lamp_w\"]", ["s1"], []),
    # SETTINGS_s4 in a ;-group with no id, not in the join
    ("table_top from s1; SETTINGS_s4", [], []),
    # pairs
    ("Uses s1's table_top with s2's lamp_shade", [], []),
    # a list broken by plus after "with": frame_obj is s1's
    ("frame_obj from s1 with its table_top plus lamp_shade from s2", [], ["s3 uses 'frame_obj' from s1, which s1 doesn't provide"]),
    # and after "With their"
    ("frame_obj from s1 With their table_top plus lamp_shade from s2", [], ["s3 uses 'frame_obj' from s1, which s1 doesn't provide"]),
    # no "with": lamp_shade stays with s2
    ("table_top (s1) feeds lamp_shade plus not_made (s2)", [], ["s3 uses 'not_made' from s2, which s2 doesn't provide"]),
    # an item after a pair item reads as round 7 reads it: not_made is no step's
    ("Uses s1's table_top and s2's lamp_shade, not_made", [], []),
    # a key the line also uses plainly, in a quote span of the whole line, stays with its chunk: lamp_h is s2's, which
    # lacks it, though SETTINGS_s1 holds the key (round 8's re-check, Nov 5: KQ01-KQ04 and the controls KC01-KC03 of
    # its keys_quote.py, with seat_h as these fixtures' lamp_h; test fixtures, never training data)
    ("Uses s2's lamp_h; SETTINGS_s1['lamp_h'] is s1's default", [], ["s3 uses 'lamp_h' from s2, which s2 doesn't provide"]),
    # (the quoted "s SETTINGS_s1[" is read as round 7 reads it)
    ("s2's lamp_h plus s1's SETTINGS_s1['lamp_h']", [], ["s3 uses 'lamp_h' from s2, which s2 doesn't provide", "s3 uses 's SETTINGS_s1[' from s1, which s1 doesn't provide"]),
    ("SETTINGS_s1['lamp_h'] for s1's chair; lamp_h from s2's helper", [], ["s3 uses 'lamp_h' from s2, which s2 doesn't provide"]),
    ("`lamp_h from s2` and SETTINGS_s1['lamp_h']", [], ["s3 uses 'lamp_h' from s2, which s2 doesn't provide"]),
    # the controls: the plain use outside any quote span, as before the re-check
    ("lamp_h from s2, SETTINGS_s1['lamp_h'] from s1", [], ["s3 uses 'lamp_h' from s2, which s2 doesn't provide"]),
    ("Uses s2 lamp_h; SETTINGS_s1['lamp_h'] (s1) as the default", [], ["s3 uses 'lamp_h' from s2, which s2 doesn't provide"]),
    ("lamp_h from s2's helper, SETTINGS_s1['lamp_h'] from s1", [], ["s3 uses 'lamp_h' from s2, which s2 doesn't provide"]),
]


class UsesReaderTests(unittest.TestCase):
    def test_each_item_goes_to_the_step_after_it(self):
        from contract.join import _uses_chunks
        for uses, want in USES_LINES:
            self.assertEqual([[list(s), t] for s, t in _uses_chunks(uses)], want, uses)

    def test_a_group_is_judged_as_one(self):
        # hand-made pieces (test fixtures): the same seams as Go's TestUsesSeamsReadGroups
        from contract.join import uses_seams
        from types import SimpleNamespace as NS

        def piece(provides, uses):
            return NS(handoff=NS(provides=provides, uses=uses), code="", files=[], section="", body="")
        base = {"s1": piece("table_top", "none"), "s2": piece("lamp_shade", "none")}

        def msgs(uses, failed=(), pieces=base):
            return [x.message for x in uses_seams(dict(pieces, s3=piece("x", uses)), list(failed))]
        for uses in ("table_top from s1, lamp_shade from s2", "table_top (s1), lamp_shade (s2)", "s1: table_top; s2: lamp_shade",
                     "table_top (from s1, for the height), lamp_shade (from s2, aimed later)",
                     "table_top from s1 and lamp_shade from s2", '{"s1": ["table_top"], "s2": ["lamp_shade"]}',
                     "scene_root; s1: table_top", "table_top from s1, s2 (merged)"):
            self.assertEqual(msgs(uses), [], uses)
        self.assertEqual(msgs("table_top from s1, lamp_shade from s1"), ["s3 uses 'lamp_shade' from s1, which s1 doesn't provide"])
        self.assertEqual(msgs("lamp_shade from s1, table_top from s2"),  # each to the id after it
                         ["s3 uses 'lamp_shade' from s1, which s1 doesn't provide",
                          "s3 uses 'table_top' from s2, which s2 doesn't provide"])
        for uses in ("desk_top from s1 and s2", "desk_top from s1-s2", "desk_top from s1/s2"):
            self.assertEqual(msgs(uses), ["s3 uses 'desk_top' from s1/s2, which s1/s2 doesn't provide"], uses)
            self.assertEqual(msgs(uses, ["s2"]), [], uses)  # s2 may have made it
        self.assertEqual(msgs("desk_top from s1 and s2", pieces={"s1": base["s1"]}), [])  # s2 isn't in the join
        for uses in ("table_top from s1, lamp_shade from s2 (failed)", "table_top from s1, s2: lamp_shade (failed)",
                     "table_top from s1 (s2 failed, so lamp_shade is a stand-in)", "table_top (s1), lamp_shade (s2, failed)"):
            self.assertEqual(msgs(uses, ["s2"]), [], uses)
        self.assertEqual(msgs("lamp_shade from s2 (failed), not_made from s1", ["s2"]),  # s1's item is still checked
                         ["s3 uses 'not_made' from s1, which s1 doesn't provide"])
        got = msgs("x_y from s1 (x_y again)")
        self.assertEqual(len(got), 1)  # one seam per piece, steps and name
        self.assertIn("'x_y' from s1", got[0])

        # round 8 (Nov 5): a SETTINGS_sN name, and a key the line has only in SETTINGS_sN subscripts, is judged against
        # sN alone, wherever it is in the line, and the pairs and breaks as they read, on pieces that hold SETTINGS dicts
        # (a failed step's piece is left out, as in a join)
        def coded(code, provides, uses="none"):
            return NS(handoff=NS(provides=provides, uses=uses), code=code, files=[], section="", body="")
        made = {"s1": coded("table_top = 1\nSETTINGS_s1 = {'lamp_h': 1}", "table_top"),
                "s2": coded("lamp_shade = 1\nSETTINGS_s2 = {}", "lamp_shade")}
        for uses, failed, want in USES_SEAMS_ROUND8:
            pieces = {s: p for s, p in made.items() if s not in failed}
            pieces["s3"] = coded("SETTINGS_s3 = {}\ndef main():\n    pass", "main", uses)
            self.assertEqual([x.message for x in uses_seams(pieces, list(failed))], want, (uses, failed))


if __name__ == "__main__":
    unittest.main()
