"""The training-data filter and the eval-leak check."""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from tests import _paths  # noqa: F401
from helper import evalset
from tools import check_overlap, validate_file


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hm-tools-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, rows):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write((r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)) + "\n")
        return path

    def quiet(self, fn, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = fn(argv)
        return code, out.getvalue()

    def test_overlap_flags_copies_and_the_canary_only(self):
        es = evalset.load()
        long_prompt = max((p["prompt"] for p in es.prompts), key=len)
        path = self.write("train.jsonl", [
            {"prompt": es.prompts[0]["prompt"]},                                      # verbatim
            {"prompt": "Please help: " + long_prompt + " Thanks a lot!"},            # wrapped copy
            {"prompt": "Write a haiku about autumn leaves falling on a quiet pond."},  # unrelated
            {"prompt": "x " + es.canary},                                             # canary
            {"prompt": "make one"},                                                   # a short eval prompt, exactly
        ])
        code, out = self.quiet(check_overlap.main, [path, "--field", "prompt"])
        self.assertEqual(code, 1)
        flagged = {int(l.split()[1].rstrip(":")) for l in out.splitlines() if l.startswith("line ")}
        self.assertEqual(flagged, {1, 2, 4, 5})

    def test_overlap_passes_clean_data(self):
        path = self.write("clean.jsonl", [{"prompt": "Plan a birthday party for twelve kids with a dinosaur theme."}])
        self.assertEqual(self.quiet(check_overlap.main, [path])[0], 0)

    def test_validate_file_keeps_valid_and_tidies(self):
        good = {"title": "T", "kind": "code", "summary": "Do it.", "steps": [
            {"id": "a", "title": "First part", "kind": "code", "instructions": "Write the first module in full."},
            {"id": "b", "title": "Second part", "kind": "code", "instructions": "Write the second module in full.", "depends_on": ["a"]}]}
        bad = dict(good, steps=good["steps"][:1])
        path = self.write("plans.jsonl", [{"output": good}, {"output": json.dumps(bad)}, {"output": "not json"}])
        keep, reject = os.path.join(self.tmp, "keep.jsonl"), os.path.join(self.tmp, "reject.jsonl")
        code, out = self.quiet(validate_file.main, [path, "--job", "planner", "--tidy", "--keep", keep, "--reject", reject])
        self.assertEqual(code, 0)
        self.assertIn("kept 1 of 3", out)
        with open(keep, encoding="utf-8") as f:
            kept = [json.loads(l) for l in f]
        self.assertEqual([s["id"] for s in kept[0]["output"]["steps"]], ["s1", "s2"])
        self.assertEqual(kept[0]["output"]["steps"][1]["depends_on"], ["s1"])
        with open(reject, encoding="utf-8") as f:
            rej = [json.loads(l)["_rejected"] for l in f]
        self.assertIn("step_count", rej[0])
        self.assertIn("not_json", rej[1])


if __name__ == "__main__":
    unittest.main()
