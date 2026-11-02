"""The names sheet in the eval (runner/common.py) and measured handoffs (runner/measured.py)."""
import os
import re
import tempfile
import unittest

from runner import common, measured

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NamesTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(os.environ.pop, "WM_NAMES_FILE", None)

    def use(self, text):
        f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        f.write(text)
        f.close()
        self.addCleanup(os.remove, f.name)
        os.environ["WM_NAMES_FILE"] = f.name

    def test_nothing_changes_unless_asked(self):
        msgs = [{"role": "system", "content": "A Blender step."}, {"role": "user", "content": "go"}]
        self.assertEqual(common.with_names(msgs, 100), (msgs, 100))

    def test_blender_requests_get_the_sheet_and_room_for_it(self):
        self.use("ShaderNodeEmission inputs: Color, Strength\n")
        msgs = [{"role": "system", "content": "A Blender step."}, {"role": "user", "content": "go"}]
        out, need = common.with_names(msgs, 100)
        self.assertTrue(out[0]["content"].endswith("ShaderNodeEmission inputs: Color, Strength"))
        self.assertGreater(need, 100)
        self.assertEqual(msgs[0]["content"], "A Blender step.")

    def test_other_requests_dont(self):
        self.use("names")
        msgs = [{"role": "system", "content": "A web shop."}, {"role": "user", "content": "go"}]
        self.assertEqual(common.with_names(msgs, 100), (msgs, 100))

    def test_same_words_as_chimera(self):
        with open(os.path.join(HERE, "..", "app", "blender_names.go"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn(common.NAMES_HEAD.replace("\n", "\\n"), src)


class MeasuredTests(unittest.TestCase):
    def test_text(self):
        t = measured.facts_text([{"name": "chimera_table", "lo": [-1, -1, 0.7], "hi": [1, 1, 0.8]}])
        self.assertIn("chimera_table: centre (0.0, 0.0, 0.75), size 2 x 2 x 0.1", re.sub(r"\.0\b(?= x|,)", "", t).replace("(0, 0,", "(0.0, 0.0,"))
        self.assertIn("top z 0.8", t)

    def test_nothing_built_nothing_said(self):
        self.assertEqual(measured.facts_text([]), "")

    def test_long_lists_are_cut(self):
        rows = [{"name": "o%d" % i, "lo": [0, 0, 0], "hi": [1, 1, 1]} for i in range(measured.MAX_ROWS + 5)]
        self.assertIn("and 5 more", measured.facts_text(rows))


if __name__ == "__main__":
    unittest.main()
