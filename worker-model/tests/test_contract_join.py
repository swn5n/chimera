"""The joiner and the line map on hand-made pieces (tests/contract_fixtures.py: test fixtures, never training data)."""
import ast
import copy
import os
import subprocess
import sys
import tempfile
import unittest

from tests import _paths  # noqa: F401
from tests import contract_fixtures as F
from contract import prompt
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
        self.assertIn('ctx = {"scene": scene, "collection": collection, "objects": {}}', main)
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
                                       '"objects": {}}\nbuild_s3(ctx)\n'))

    def test_slug(self):
        self.assertEqual(slug("Reading corner: v2!"), "reading_corner_v2")
        self.assertEqual(slug("???"), "project")


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


if __name__ == "__main__":
    unittest.main()
