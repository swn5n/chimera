"""The piece validator on hand-made pieces (tests/contract_fixtures.py: test fixtures only, never training data)."""
import unittest

from tests import _paths  # noqa: F401
from tests import contract_fixtures as F
from contract.validate import parse_handoff, strip_handoff, validate_piece

HANDOFF = "```handoff\nprovides: x\nuses: none\nassumed: none\n```\n"


def codes(p, level=None):
    return [i.code for i in p.issues if level is None or i.level == level]


def blender(code, sid="s2", handoff=HANDOFF, **kw):
    return validate_piece("```python\n" + code + "\n```\n\n" + handoff, "blender", sid=sid, **kw)


GOOD_S2 = '''import bpy

SETTINGS_s2 = {"size": 1.0}


def _s2_helper():
    return 1


def build_s2(ctx):
    ctx["objects"]["thing"] = None


if __name__ == "__main__":
    build_s2({"scene": bpy.context.scene, "collection": bpy.context.scene.collection, "objects": {}})'''


class HandoffTests(unittest.TestCase):
    def test_reads_the_three_lines(self):
        h, blocks, issues = parse_handoff("text\n```handoff\nprovides: a, b\nuses: s1's c\nassumed: None.\n```\n")
        self.assertEqual((h.provides, h.uses, h.assumed), ("a, b", "s1's c", ""))
        self.assertEqual(issues, [])
        self.assertEqual(strip_handoff("text\n```handoff\nprovides: a\nuses: b\nassumed: c\n```\n", blocks), "text")

    def test_shape_errors(self):
        cases = {
            "```handoff\nprovides: a\nuses: b\n```": "handoff_shape",                         # no assumed
            "```handoff\nprovides: a\nuses: b\nassumed: c\nnotes: d\n```": "handoff_shape",   # an extra line
            "```handoff\nprovides: a\nprovides: b\nuses: c\nassumed: d\n```": "handoff_shape",
            "```handoff\nprovides: a\nuses: b\nassumed: c\n```\nThanks!": "handoff_not_last",
            HANDOFF + HANDOFF: "handoff_many",
            "```handoff\nprovides: a\nuses: b\nassumed: c\nand then more": "handoff_unclosed",
            "```handoff\nprovides: a\nuses: b": "handoff_unclosed",
        }
        for text, code in cases.items():
            with self.subTest(code=code):
                _, _, issues = parse_handoff(text)
                self.assertIn(code, [i.code for i in issues])

    def test_missing_handoff_and_lone_steps(self):
        code = GOOD_S2
        p = validate_piece("```python\n" + code + "\n```\n", "blender", sid="s2")
        self.assertIn("handoff_missing", codes(p, "error"))
        lone = validate_piece("```python\n" + code + "\n```\n", "blender", sid="s2", lone=True)
        self.assertNotIn("handoff_missing", codes(lone))
        self.assertTrue(lone.ok, lone.reasons())
        lone2 = validate_piece("```python\n" + code + "\n```\n\n" + HANDOFF, "blender", sid="s2", lone=True)
        self.assertIn("handoff_in_lone", codes(lone2, "warn"))
        self.assertTrue(lone2.ok)

    def test_near_miss_forms_are_read_with_a_warning(self):
        # Oct 29 smoke runs: 5 of 6 contract replies (qwen3:8b, qwen3:4b-instruct) wrote the three lines under a bare
        # "handoff" line or in a plain ``` block; the strict rule sent the whole task to the combine for it.
        lines = "provides: chimera_thing as ctx[\"objects\"][\"thing\"]\nuses: none\nassumed: none"
        code = "```python\n" + GOOD_S2 + "\n```\n\n"
        forms = {
            "a bare handoff line": ("handoff\n" + lines + "\n", "handoff_unfenced"),
            "a decorated label": ("**Handoff:**\n\n" + lines + "\n\n", "handoff_unfenced"),
            "no label at all": (lines + "\n", "handoff_unfenced"),
            "blank lines between": (lines.replace("\n", "\n\n") + "\n", "handoff_unfenced"),
            "a plain fence": ("```\n" + lines + "\n```\n", "handoff_unlabelled"),
            "a text fence": ("```text\n" + lines + "\n```", "handoff_unlabelled"),
        }
        for what, (tail, warn) in forms.items():
            with self.subTest(what):
                p = validate_piece(code + tail, "blender", sid="s2")
                self.assertTrue(p.ok and p.contract_ok, p.reasons())
                self.assertFalse(p.form_ok)  # joined, but never a training target as it stands
                self.assertIn(warn, codes(p, "warn"))
                self.assertNotIn("extra_block", codes(p))
                self.assertEqual((p.handoff.provides, p.handoff.uses), ('chimera_thing as ctx["objects"]["thing"]', ""))
                self.assertEqual(p.body, code.strip())  # stripped, label and all
                h, blocks, _ = parse_handoff(code + tail)
                self.assertEqual(strip_handoff(code + tail, blocks), code.strip())
                self.assertEqual(strip_handoff(code + tail), code.strip())
        exact = validate_piece(code + "```handoff\n" + lines + "\n```\n", "blender", sid="s2")
        self.assertTrue(exact.form_ok, exact.issues)
        self.assertTrue(exact.to_dict()["form_ok"])

    def test_unclosed_and_doubled_handoffs_are_near_misses(self):
        # Oct 30: qwen3:14b ended a reply with the three lines and no closing fence; Gemma 4's files replies wrote
        # the lines unfenced just before the ```handoff block. Both are read; neither is a training target.
        lines = "provides: chimera_thing as ctx[\"objects\"][\"thing\"]\nuses: none\nassumed: none"
        code = "```python\n" + GOOD_S2 + "\n```\n\n"
        for what, tail, warn in (("unclosed at the end", "```handoff\n" + lines + "\n", "handoff_unclosed_end"),
                                 ("written twice", lines + "\n\n```handoff\n" + lines + "\n```\n", "handoff_twice")):
            with self.subTest(what):
                p = validate_piece(code + tail, "blender", sid="s2")
                self.assertTrue(p.ok and p.contract_ok, p.reasons())
                self.assertFalse(p.form_ok)
                self.assertIn(warn, codes(p, "warn"))
                self.assertEqual(p.handoff.provides, 'chimera_thing as ctx["objects"]["thing"]')
        once = validate_piece(code + "```handoff\n" + lines + "\n```\n", "blender", sid="s2")
        self.assertNotIn("handoff_twice", codes(once))
        # key lines inside the code block (a string in the code) aren't a second handoff
        doc = code.replace("import bpy", 'import bpy\nNOTE = """\nprovides: x\nuses: y\nassumed: z\n"""', 1)
        self.assertIn("\nprovides: x\nuses: y\nassumed: z\n", doc)
        inside = validate_piece(doc + "```handoff\n" + lines + "\n```\n", "blender", sid="s2")
        self.assertNotIn("handoff_twice", codes(inside))
        # prose that talks about the handoff isn't a copy of it; a real copy in a section is stripped from it
        step = {"title": "Notes", "instructions": "Write the notes."}
        prose = ("## Notes\n\nWhat this step provides: a list.\nWhat it uses: nothing.\nWhat it assumed: very "
                 "little.\n\nMore text.\n\n```handoff\n" + lines + "\n```\n")
        self.assertNotIn("handoff_twice", codes(validate_piece(prose, "section", sid="s2", step=step)))
        other = ("## API\n\nThe module:\nProvides: a cache\nUses: redis\nAssumed: one process\n\n```handoff\n"
                 + lines + "\n```\n")  # three lines just above, but other values: the section's own text
        po = validate_piece(other, "section", sid="s2", step={"title": "API", "instructions": "x"})
        self.assertIn("handoff_twice", codes(po, "warn"))  # still not the exact form: never a training target
        self.assertIn("Provides: a cache", po.section)  # but not stripped: the values aren't the block's
        dup = "## Notes\n\nThe notes.\n\n" + lines + "\n\n```handoff\n" + lines + "\n```\n"
        p = validate_piece(dup, "section", sid="s2", step=step)
        self.assertIn("handoff_twice", codes(p, "warn"))
        self.assertNotIn("provides:", p.section)
        self.assertEqual(p.section, "## Notes\n\nThe notes.")
        # a plain block left open at the end, holding just the three lines, reads like an open ```handoff one
        plain_open = validate_piece(code + "```\n" + lines + "\n", "blender", sid="s2")
        self.assertTrue(plain_open.contract_ok, plain_open.reasons())
        self.assertIn("handoff_unclosed_end", codes(plain_open, "warn"))
        self.assertIn("handoff_unlabelled", codes(plain_open, "warn"))
        broken = validate_piece(code + "```handoff\n" + lines + "\nmore words\n", "blender", sid="s2")
        self.assertIn("handoff_unclosed", codes(broken, "error"))
        self.assertFalse(broken.contract_ok)

    def test_near_miss_forms_in_the_other_modes(self):
        lines = "provides: f()\nuses: none\nassumed: none"
        plain = "```\n" + lines + "\n```\n"
        # python-script: a plain block would otherwise count as a second python block
        p = validate_piece("```python\ndef f():\n    return 1\n```\n\n" + plain, "python-script", sid="s1")
        self.assertTrue(p.ok, p.reasons())
        self.assertEqual(p.code, "def f():\n    return 1")
        # files: a plain block would otherwise be a file block with no File: line
        p = validate_piece("File: a.py\n```python\ndef f():\n    return 1\n```\n\n" + plain, "files", sid="s1")
        self.assertTrue(p.ok, p.reasons())
        self.assertEqual([f.path for f in p.files], ["a.py"])
        # section: the lines don't end up in the section
        st = {"title": "Green tea", "kind": "writing", "instructions": "Two paragraphs."}
        p = validate_piece("## Green tea\n\nText. (fixture text)\n\nHandoff\n" + lines + "\n", "section", sid="s1", step=st)
        self.assertTrue(p.ok, p.reasons())
        self.assertEqual(p.section, "## Green tea\n\nText. (fixture text)")
        # a lone step: stripped, with the lone warning
        p = validate_piece("## Green tea\n\nText.\n\nhandoff\n" + lines, "section", sid="s1", step=st, lone=True)
        self.assertIn("handoff_in_lone", codes(p, "warn"))
        self.assertEqual(p.section, "## Green tea\n\nText.")

    def test_what_is_not_read_as_a_handoff(self):
        code = "```python\n" + GOOD_S2 + "\n```\n\n"
        cases = {
            "only two keys": "handoff\nprovides: x\nuses: none\n",
            "text after the lines": "handoff\nprovides: x\nuses: none\nassumed: none\nHope this helps!\n",
            "a plain block with other lines": "```\nprovides: x\nuses: none\nassumed: none\nnotes: y\n```\n",
            "a python block": "```python\nprovides: x\nuses: none\nassumed: none\n```\n",
        }
        for what, tail in cases.items():
            with self.subTest(what):
                p = validate_piece(code + tail, "blender", sid="s2")
                self.assertIn("handoff_missing", codes(p, "error"))
                self.assertIsNone(p.handoff)
        # the lines inside the python block (as comments or not) are code, not a handoff
        inside = "```python\n" + GOOD_S2 + "\n# provides: x\n# uses: none\n# assumed: none\n```\n"
        self.assertIn("handoff_missing", codes(validate_piece(inside, "blender", sid="s2"), "error"))
        # with a ```handoff block, a stray plain one isn't a second handoff: the strict rules apply
        both = code + "```\nprovides: y\nuses: none\nassumed: none\n```\n\n" + HANDOFF
        p = validate_piece(both, "blender", sid="s2")
        self.assertEqual(p.handoff.provides, "x")
        self.assertNotIn("handoff_unlabelled", codes(p))
        # a near-miss form keeps the strict shape rules: two uses lines
        dup = validate_piece(code + "handoff\nprovides: x\nuses: none\nuses: s1\nassumed: none\n", "blender", sid="s2",
                             deps=["s1"])
        self.assertIn("handoff_shape", codes(dup, "error"))

    def test_uses_only_from_dependencies(self):
        h = "```handoff\nprovides: x\nuses: s1's table and s3's lamp\nassumed: none\n```\n"
        p = blender(GOOD_S2, handoff=h, deps=["s1"])
        self.assertIn("uses_not_dependency", codes(p, "error"))
        self.assertIn("s3", p.reasons()[0])
        self.assertTrue(blender(GOOD_S2, handoff=h.replace(" and s3's lamp", ""), deps=["s1"]).ok)

    def test_negated_uses_and_own_name_are_not_dependencies(self):
        # Seen from qwen3.8:27b on Oct 29: "uses: nothing from s1 (s2 is independent of the floor)".
        h = "```handoff\nprovides: x\nuses: nothing from s1 (s2 is independent of the floor)\nassumed: none\n```\n"
        p = blender(GOOD_S2, handoff=h)
        self.assertTrue(p.ok, p.reasons())
        self.assertIn("handoff_wordy", codes(p, "warn"))
        self.assertEqual(p.handoff.uses, "")
        own = "```handoff\nprovides: x\nuses: s1's floor, placed next to s2's own table\nassumed: none\n```\n"
        self.assertTrue(blender(GOOD_S2, handoff=own, deps=["s1"]).ok)
        long = "```handoff\nprovides: x\nuses: none\nassumed: " + "y" * 301 + "\n```\n"
        self.assertIn("handoff_long", codes(blender(GOOD_S2, handoff=long), "warn"))


class BlenderPieceTests(unittest.TestCase):
    def test_fixtures_are_well_formed(self):
        for sid, text, deps in (("s1", F.S1, []), ("s2", F.S2, []), ("s3", F.S3, ["s2"])):
            with self.subTest(sid=sid):
                p = validate_piece(text, "blender", sid=sid, deps=deps)
                self.assertTrue(p.ok, p.reasons())
                self.assertEqual(codes(p), [])
                self.assertIsNotNone(p.tree)

    def test_good_piece(self):
        p = blender(GOOD_S2)
        self.assertTrue(p.ok and p.contract_ok, p.reasons())
        self.assertEqual(p.code_line, 2)
        self.assertIn("provides_missing", codes(p, "warn"))  # registers "thing", provides says x

    def test_top_level_rules(self):
        cases = [
            ("top-level code", GOOD_S2.replace("SETTINGS_s2 = ", "print('hi')\nSETTINGS_s2 = "), "top_level_code"),
            ("an unprefixed helper", GOOD_S2.replace("def _s2_helper", "def helper"), "top_level_code"),
            ("a top-level loop", GOOD_S2 + "\nfor i in range(3):\n    pass", "top_level_code"),
            ("another step's names", GOOD_S2.replace("_s2_helper", "_s3_helper"), "wrong_step_names"),
            ("no settings", GOOD_S2.replace('SETTINGS_s2 = {"size": 1.0}', ""), "no_settings"),
            ("settings twice", GOOD_S2.replace('SETTINGS_s2 = {"size": 1.0}', 'SETTINGS_s2 = {}\nSETTINGS_s2 = {}'),
             "many_settings"),
            ("settings not a dict", GOOD_S2.replace('{"size": 1.0}', 'dict(size=1.0)'), "settings_not_dict"),
            ("no build", GOOD_S2.replace("def build_s2(ctx):", "def _s2_build(ctx):").replace(
                "    build_s2(", "    _s2_build("), "no_build"),
            ("build twice", GOOD_S2 + "\n\ndef build_s2(ctx):\n    pass", "many_build"),
            ("no main guard", GOOD_S2.split("\n\nif __name__")[0], "no_main_guard"),
            ("guard calls something else", GOOD_S2.replace("    build_s2({", "    _s2_helper({"), "guard_not_build"),
            ("saves the file", GOOD_S2.replace("    ctx[\"objects\"]", "    bpy.ops.wm.save_as_mainfile(filepath='x.blend')\n"
                                               "    ctx[\"objects\"]"), "saves_or_renders"),
            ("renders", GOOD_S2.replace("    ctx[\"objects\"]", "    bpy.ops.render.render(write_still=True)\n"
                                        "    ctx[\"objects\"]"), "saves_or_renders"),
            ("opens a file", GOOD_S2.replace("    ctx[\"objects\"]", "    bpy.ops.wm.open_mainfile(filepath='a.blend')\n"
                                             "    ctx[\"objects\"]"), "saves_or_renders"),
            ("quits", GOOD_S2.replace("    ctx[\"objects\"]", "    sys.exit(0)\n    ctx[\"objects\"]"), "saves_or_renders"),
            ("wipes the scene", GOOD_S2.replace("    ctx[\"objects\"]", "    bpy.ops.object.select_all(action='SELECT')\n"
                                                "    bpy.ops.object.delete()\n    ctx[\"objects\"]"), "deletes_scene"),
            ("removes every object", GOOD_S2.replace("    ctx[\"objects\"]", "    for o in bpy.data.objects:\n"
                                                     "        bpy.data.objects.remove(o)\n    ctx[\"objects\"]"),
             "deletes_scene"),
            ("removes every object from a list", GOOD_S2.replace(
                "    ctx[\"objects\"]", "    for o in list(bpy.context.scene.objects):\n"
                "        bpy.data.objects.remove(o, do_unlink=True)\n    ctx[\"objects\"]"), "deletes_scene"),
            ("clears the objects (Gemma 4, Oct 30)", GOOD_S2.replace(
                "    ctx[\"objects\"]", "    bpy.data.objects.clear()\n    ctx[\"objects\"]"), "deletes_scene"),
            ("removes all but one", GOOD_S2.replace("    ctx[\"objects\"]", "    for o in bpy.data.objects.values():\n"
                                                    "        if o.name != 'Camera':\n"
                                                    "            bpy.data.objects.remove(o)\n    ctx[\"objects\"]"),
             "deletes_scene"),
        ]
        for what, code, expected in cases:
            with self.subTest(what):
                p = blender(code)
                self.assertIn(expected, codes(p, "error"), [i.to_dict() for i in p.issues])
                self.assertFalse(p.contract_ok)

    def test_loops_that_remove_only_their_own_things(self):
        # Oct 30 review: the loop rule flagged any .remove() in a loop over bpy.data.objects
        picked = GOOD_S2.replace("    ctx[\"objects\"]", "    for o in list(bpy.data.objects):\n"
                                 "        if o.name.startswith('chimera_old'):\n"
                                 "            bpy.data.objects.remove(o)\n    ctx[\"objects\"]")
        p = blender(picked)
        self.assertNotIn("deletes_scene", codes(p))
        self.assertIn("removes_in_loop", codes(p, "warn"))
        self.assertTrue(p.contract_ok, p.reasons())
        other = GOOD_S2.replace("    ctx[\"objects\"]", "    for o in bpy.data.objects:\n"
                                "        o.data.materials.remove(o.data.materials[0])\n    ctx[\"objects\"]")
        self.assertNotIn("deletes_scene", codes(blender(other)))
        self.assertNotIn("removes_in_loop", codes(blender(other)))
        # the final check's cases (Oct 30): the continue idiom picks too; `not m.users` picks the unused ones
        def loop(body):
            return GOOD_S2.replace("    ctx[\"objects\"]", body + "    ctx[\"objects\"]")
        picks = {
            "continue": "    for o in list(bpy.data.objects):\n        if not o.name.startswith('chimera_old'):\n"
                        "            continue\n        bpy.data.objects.remove(o)\n",
            "unused": "    for m in bpy.data.meshes:\n        if not m.users:\n            bpy.data.meshes.remove(m)\n",
        }
        for what, body in picks.items():
            with self.subTest(what):
                p = blender(loop(body))
                self.assertNotIn("deletes_scene", codes(p), p.issues)
                self.assertIn("removes_in_loop", codes(p, "warn"))
        wipes = {
            "enumerate": "    for i, o in enumerate(list(bpy.data.objects)):\n        bpy.data.objects.remove(o)\n",
            "the project's collection": "    col = ctx[\"collection\"]\n    for o in col.objects:\n"
                                        "        bpy.data.objects.remove(o)\n",
            "ctx's scene": "    for o in list(ctx[\"scene\"].objects):\n        bpy.data.objects.remove(o)\n",
            "skips but removes the rest": "    for o in bpy.data.objects:\n        if o.name == 'Camera':\n"
                                          "            continue\n        bpy.data.objects.remove(o)\n",
            "picks one, then removes all": "    for o in bpy.data.objects:\n        if o.type == 'CAMERA':\n"
                                           "            bpy.data.objects.remove(o)\n        else:\n"
                                           "            bpy.data.objects.remove(o)\n",
            "clear through a name": "    objs = bpy.data.objects\n    objs.clear()\n",
        }
        for what, body in wipes.items():
            with self.subTest(what):
                self.assertIn("deletes_scene", codes(blender(loop(body)), "error"))

    def test_continuation_lines_and_docstrings_are_fine(self):
        code = '"""Module docstring."""\n# a comment\n' + GOOD_S2.replace(
            'SETTINGS_s2 = {"size": 1.0}', 'SETTINGS_s2 = {\n    "size": 1.0,\n}') + "\n_s2_LIMIT = 4"
        p = blender(code)
        self.assertTrue(p.ok, p.reasons())

    def test_block_rules(self):
        self.assertIn("no_python_block", codes(validate_piece("Just words.\n\n" + HANDOFF, "blender", sid="s2")))
        two = "```python\n" + GOOD_S2 + "\n```\n\n```python\nimport bpy\n```\n\n" + HANDOFF
        self.assertIn("many_python_blocks", codes(validate_piece(two, "blender", sid="s2")))
        cut = "```python\n" + GOOD_S2
        p = validate_piece(cut, "blender", sid="s2", lone=True)
        self.assertIn("unclosed_block", codes(p, "error"))
        bash = "```python\n" + GOOD_S2 + "\n```\n\nRun:\n```bash\nblender -b --python x.py\n```\n\n" + HANDOFF
        p = validate_piece(bash, "blender", sid="s2")
        self.assertIn("extra_block", codes(p, "warn"))
        self.assertTrue(p.ok)

    def test_syntax_error_is_an_error_but_not_a_shape_one(self):
        p = blender(GOOD_S2.replace("def build_s2(ctx):", "def build_s2(ctx)"))
        self.assertIn("syntax_error", codes(p, "error"))
        self.assertFalse(p.ok)
        self.assertTrue(p.contract_ok)
        self.assertEqual(p.issues[0].line, 2 + GOOD_S2.split("\n").index("def build_s2(ctx):"))

    def test_cut_off_too_long_and_harmony(self):
        self.assertIn("cut_off", codes(blender(GOOD_S2, done_reason="length")))
        self.assertNotIn("cut_off", codes(blender(GOOD_S2, done_reason="length", reject_cut=False)))
        self.assertIn("too_long", codes(blender(GOOD_S2 + "\n# " + "x" * 11000)))
        self.assertNotIn("too_long", codes(blender(GOOD_S2 + "\n# " + "x" * 11000, max_tokens=None)))
        self.assertIn("harmony_leftover", codes(validate_piece("<|channel|>final<|message|>" + F.S2, "blender", sid="s2")))
        self.assertIn("empty", codes(validate_piece("  \n", "blender", sid="s2")))


class ScriptPieceTests(unittest.TestCase):
    def test_fixtures(self):
        a = validate_piece(F.SCRIPT_A, "python-script", sid="s1")
        b = validate_piece(F.SCRIPT_B, "python-script", sid="s2", deps=["s1"])
        self.assertTrue(a.ok and b.ok, a.reasons() + b.reasons())
        self.assertIn("main_guard", codes(b, "warn"))

    def test_code_that_runs_on_import(self):
        for what, code, level in (("a call", "print('x')", "error"), ("a loop", "for i in []:\n    pass", "error"),
                                  ("a computed constant", "import os\nHOME = os.getcwd()", "warn")):
            with self.subTest(what):
                p = validate_piece("```python\n" + code + "\n```\n\n" + HANDOFF, "python-script", sid="s1")
                self.assertIn("runs_on_import" if level == "error" else "top_level_assign", codes(p, level))
        ok = "try:\n    import numpy\nexcept ImportError:\n    numpy = None\n\nLIMIT = 3\n\ndef f():\n    return LIMIT"
        self.assertTrue(validate_piece("```python\n" + ok + "\n```\n\n" + HANDOFF, "python-script", sid="s1").ok)


class FilesPieceTests(unittest.TestCase):
    def test_fixtures(self):
        for sid, text, deps in (("s1", F.FILES_1, []), ("s2", F.FILES_2, ["s1"]), ("s3", F.FILES_3, ["s1", "s2"])):
            with self.subTest(sid=sid):
                p = validate_piece(text, "files", sid=sid, deps=deps)
                self.assertTrue(p.ok, p.reasons())
        p = validate_piece(F.FILES_2, "files", sid="s2", deps=["s1"])
        self.assertEqual([(f.path, f.part) for f in p.files], [("notes/store.py", True)])

    def test_file_lines(self):
        no_line = "Here:\n```python\nx = 1\n```\n\n" + HANDOFF
        self.assertIn("no_file_line", codes(validate_piece(no_line, "files", sid="s1"), "error"))
        bold = "**File:** `app/main.py`\n```python\nx = 1\n```\n\n" + HANDOFF
        p = validate_piece(bold, "files", sid="s1")
        self.assertTrue(p.ok)
        self.assertIn("file_line_decorated", codes(p, "warn"))
        self.assertEqual(p.files[0].path, "app/main.py")
        wrapped = "**File: src/notes.py**\n```python\nx = 1\n```\n\n" + HANDOFF  # gpt-oss:120b's form
        p = validate_piece(wrapped, "files", sid="s1")
        self.assertTrue(p.ok)
        self.assertIn("file_line_decorated", codes(p, "warn"))
        self.assertEqual([(f.path, f.part) for f in p.files], [("src/notes.py", False)])
        p = validate_piece("**File: src/store.py** (part)\n```python\nx = 1\n```\n\n" + HANDOFF, "files", sid="s1")
        self.assertEqual([(f.path, f.part) for f in p.files], [("src/store.py", True)])
        bad_py = "File: a.py\n```python\ndef f(:\n```\n\n" + HANDOFF
        self.assertIn("syntax_error", codes(validate_piece(bad_py, "files", sid="s1"), "error"))
        js = "File: web/app.js\n```javascript\n// TODO: wire up\n```\n\n" + HANDOFF
        p = validate_piece(js, "files", sid="s1")
        self.assertTrue(p.ok)
        self.assertIn("placeholder", codes(p, "warn"))
        self.assertIn("no_file_blocks", codes(validate_piece("words\n\n" + HANDOFF, "files", sid="s1")))


class SectionPieceTests(unittest.TestCase):
    def test_fixtures(self):
        for text, st in ((F.SECTION_1, F.SECTION_PLAN["steps"][0]), (F.SECTION_2, F.SECTION_PLAN["steps"][1])):
            p = validate_piece(text, "section", sid="s1", step=st)
            self.assertTrue(p.ok, p.reasons())
            self.assertEqual(codes(p), [])
            self.assertNotIn("handoff", p.section)

    def test_heading_rules(self):
        st = {"title": "Green tea", "kind": "writing", "instructions": "Two paragraphs."}
        for text, code, level in (("Green tea is nice.\n\n" + HANDOFF, "no_heading", "error"),
                                  ("# Green tea\n\nText.\n\n" + HANDOFF, "no_heading", "error"),
                                  ("## Brewing\n\nText.\n\n" + HANDOFF, "heading_not_title", "warn"),
                                  ("## Green tea\n\nAs an AI, I think other workers cover this.\n\n" + HANDOFF,
                                   "ai_talk", "warn")):
            with self.subTest(code=code):
                self.assertIn(code, codes(validate_piece(text, "section", sid="s1", step=st), level))

    def test_research_links_must_be_marked(self):
        st = {"title": "Sources", "kind": "research", "instructions": "List sources."}
        text = "## Sources\n\n- https://example.org/a\n- https://example.org/b (unverified)\n\n" + HANDOFF
        p = validate_piece(text, "section", sid="s1", step=st)
        self.assertEqual([i.message for i in p.issues if i.code == "unmarked_link"],
                         ["https://example.org/a isn't marked (unverified)"])


if __name__ == "__main__":
    unittest.main()
