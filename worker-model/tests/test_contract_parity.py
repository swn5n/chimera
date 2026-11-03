"""Go and the prototype agree on the contract (tools/check_contract_parity.py).

The frozen texts are read from the Go source, so that check always runs. Whole requests need a Chimera binary:
skipped unless CHIMERA_BIN names one (build it with `cd app && PATH=/opt/homebrew/bin:$PATH go build -o <path> .`,
removing the old file first). About 20 s.
"""
import os
import subprocess
import sys
import unittest

from tests import _paths
from tools import check_contract_parity as parity

CHIMERA = os.environ.get("CHIMERA_BIN", "")
TOOL = os.path.join(_paths.HERE, "tools", "check_contract_parity.py")


class TextTests(unittest.TestCase):
    def test_frozen_texts_are_byte_identical_in_go(self):
        bad, n = parity.check_texts()
        self.assertEqual(bad, [])
        self.assertGreater(n, 30)

    def test_go_const_reads_what_go_writes(self):
        src = 'const (\n\ta = `raw\nline "q"`\n\tb = "one\\n\\"two\\"" +\n\t\t"three"\n\tc = 300 // cut\n\td   = ""\n)\n'
        self.assertEqual(parity.go_const(src, "a"), 'raw\nline "q"')
        self.assertEqual(parity.go_const(src, "b"), 'one\n"two"three')
        self.assertEqual(parity.go_const(src, "c"), 300)
        self.assertEqual(parity.go_const(src, "d"), "")
        self.assertIsNone(parity.go_const(src, "e"))


class ReportTests(unittest.TestCase):
    def test_a_difference_is_found_and_placed(self):
        a = {"messages": [{"role": "system", "content": "same"}, {"role": "user", "content": "abc"}], "mode": "section"}
        b = {"messages": [{"role": "system", "content": "same"}, {"role": "user", "content": "abd"}], "mode": "section"}
        self.assertEqual(parity.first_difference(a, a), "")
        self.assertIn("message 1 differs at 2", parity.first_difference(a, b))
        self.assertIn("mode", parity.first_difference(a, dict(a, mode="files")))
        self.assertIn("deps", parity.first_difference(dict(a, deps=[]), dict(a, deps=["s1"])))


@unittest.skipUnless(CHIMERA, "needs CHIMERA_BIN")
class RequestTests(unittest.TestCase):
    def test_go_and_python_build_the_same_requests(self):
        p = subprocess.run([sys.executable, TOOL, "--chimera", CHIMERA], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout[-6000:] + p.stderr[-2000:])
        self.assertIn(", 0 differ.", p.stdout)


if __name__ == "__main__":
    unittest.main()
