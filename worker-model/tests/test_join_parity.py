"""Go and the prototype agree on every verdict and join (tools/check_join_parity.py).

The tool's own parts always run. The comparison needs a Chimera binary: skipped unless CHIMERA_BIN names one (build it
with `cd app && PATH=/opt/homebrew/bin:$PATH go build -o <path> .`, removing the old file first). The whole corpus takes
over a minute, so this runs a sample, about 20 s. Run the tool itself for all of it.
"""
import ast
import collections
import os
import subprocess
import sys
import unittest

from tests import _paths
from tools import check_join_parity as parity

CHIMERA = os.environ.get("CHIMERA_BIN", "")
TOOL = os.path.join(_paths.HERE, "tools", "check_join_parity.py")


class ToolTests(unittest.TestCase):
    def test_a_difference_is_found_and_placed(self):
        a = {"issues": [{"code": "x", "line": 1}], "script": "abc"}
        self.assertEqual(parity.first_difference(a, a), "")
        self.assertIn(".issues[0].line", parity.first_difference(a, {"issues": [{"code": "x", "line": 2}], "script": "abc"}))
        self.assertIn(".script differs at 2", parity.first_difference(a, dict(a, script="abd")))
        self.assertIn("1 items in Python, 0 in Go", parity.first_difference(a, dict(a, issues=[])))

    def test_canon_keeps_what_the_checks_read(self):
        got = parity.canon(ast.parse("x = f(a)[1]\n"))
        self.assertEqual(got, "(Module 0 (Assign 1-1 (Name 1 x store) (Subscript 1 (Call 1 (Name 1 f) (Name 1 a)) (Constant 1 int))))")

    def test_every_code_is_known(self):
        codes = parity.known_codes()
        for code in ("syntax_error", "top_level_code", "handoff_twice", "deletes_scene", "uses_unmatched", "join_syntax"):
            self.assertIn(code, codes)
        self.assertGreater(len(codes), 55)

    def test_the_damage_is_seeded(self):
        self.assertEqual(parity.fuzz_sources(["x = 1\n"], 5), parity.fuzz_sources(["x = 1\n"], 5))
        self.assertEqual(parity.random_replies(5), parity.random_replies(5))

    def test_a_rejected_valid_script_fails_and_an_unseen_error_does_not(self):
        seen = collections.Counter()
        self.assertIn("Python accepts", parity.compare_scan("x = 1\n", {"ok": False, "line": 1, "msg": "no"}, seen))
        self.assertEqual(parity.compare_scan("x = (\n", {"ok": True, "tree": ""}, seen), "")
        self.assertEqual(seen["a syntax error Go doesn't see"], 1)
        self.assertEqual(seen["go rejected what Python accepts"], 1)

    def test_a_different_tree_fails(self):
        self.assertTrue(parity.compare_scan("x = 1\n", {"ok": True, "tree": "(Module 0)"}, collections.Counter()))


@unittest.skipUnless(CHIMERA, "needs CHIMERA_BIN")
class JoinTests(unittest.TestCase):
    def test_go_and_python_read_and_join_the_same(self):
        p = subprocess.run([sys.executable, "-W", "ignore", TOOL, "--chimera", CHIMERA, "--sample", "150", "--fuzz", "2000", "--random", "2000"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout[-6000:] + p.stderr[-2000:])
        self.assertIn("No differences. 0 differ.", p.stdout)
        self.assertRegex(p.stdout, r"task joins +150 cases, 0 differ\.")


if __name__ == "__main__":
    unittest.main()
