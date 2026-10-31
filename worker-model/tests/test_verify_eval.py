"""tools/verify_eval.py's pure parts: reading Blender's output, per-version expectations, the facts checks, which
Blenders a run needs and where it works (no real Blender run: a fake one that only says its version)."""
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

from tests import _paths  # noqa: F401
import evalset
from tools import verify_eval as V

OUTPUT = """script.py:83: DeprecationWarning: 'Material.use_nodes' is expected to be removed in Blender 6.0
  rock_mat.use_nodes = True
Traceback (most recent call last):
  File "/private/tmp/run-x/script.py", line 52, in <module>
    build_s2({"scene": bpy.context.scene})
    ~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/private/tmp/run-x/script.py", line 13, in _s2_surface_z
    return location.z if location else 0.0
           ^^^^^^^^^^
AttributeError: 'bool' object has no attribute 'z'

Error: script failed, file: 'script.py', exiting.
Blender 5.2.2 LTS (hash d13f752e3b9c built 2026-09-15 01:49:19)
"""


class ParseTests(unittest.TestCase):
    def test_deepest_frame_in_the_script(self):
        r = V.parse_run(OUTPUT)
        self.assertEqual(r["exception"], "AttributeError: 'bool' object has no attribute 'z'")
        self.assertEqual((r["line"], r["function"]), (13, "_s2_surface_z"))
        self.assertEqual(r["source"], "return location.z if location else 0.0")
        self.assertTrue(r["traceback"].startswith("Traceback"))
        self.assertTrue(r["traceback"].rstrip().endswith("attribute 'z'"))

    def test_no_traceback(self):
        self.assertEqual(V.parse_run("Blender quit\n"), {})

    def test_per_version(self):
        self.assertEqual(V.per_version("KeyError", "5.0.1"), "KeyError")
        self.assertEqual(V.per_version({"5.2.2": "TypeError", "5.0.1": "ValueError"}, "5.0.1"), "ValueError")
        self.assertIsNone(V.per_version({"5.2.2": "TypeError"}, "5.0.1"))  # nothing recorded: no failure may match

    def test_trap_expectations(self):
        self.assertTrue(V._trap_expect({"api": "x"}, "5.0.1"))
        self.assertFalse(V._trap_expect({"api": "x", "only_in": ["5.2.2"]}, "5.0.1"))

    def test_probe_epilogue_is_appended(self):
        s = V.with_probe("import bpy")
        self.assertTrue(s.startswith("import bpy"))
        self.assertIn("CHIMERA_PROBE", s)


class FakeChecker:
    """Every script fails in both versions with the same TypeError."""

    def __init__(self):
        self.blenders = [("5.2.2", "a"), ("5.0.1", "b")]
        self.failures = []
        self.scripts = []

    def run_all(self, script):
        self.scripts.append(script)
        return {v: {"strict": False, "exit": 1, "output": "", "exception": "TypeError: boom"} for v, _ in self.blenders}

    def fail(self, cid, msg):
        self.failures.append(msg)


CASE = {"id": "w2-x", "right": ["pass"], "expect": {"assertions": []}, "facts_check": ["assert True"],
        "traps": [{"api": "t", "code": ["x"], "error": {"5.2.2": "TypeError"}, "message": "boom"}]}


class W2Tests(unittest.TestCase):
    def test_a_version_missing_from_a_per_version_error_fails(self):
        ck = FakeChecker()
        V.check_w2(ck, CASE, ["import bpy"])
        self.assertIn("trap 't' records no error or message for 5.0.1, where it should fail", ck.failures)
        self.assertFalse([f for f in ck.failures if "trap 't' in 5.2.2" in f], "5.2.2's TypeError: boom matches")

    def test_the_facts_check_runs_after_the_prelude_and_must_pass(self):
        ck = FakeChecker()
        rec = V.check_w2(ck, CASE, ["import bpy", "def raises(): pass"])
        facts = [x for x in ck.scripts if V.FACTS_OK in x]
        self.assertEqual(len(facts), 1)
        self.assertTrue(facts[0].index("def raises") < facts[0].index("assert True") < facts[0].index(V.FACTS_OK))
        self.assertTrue(any(f.startswith("facts_check fails in 5.2.2") for f in ck.failures))
        self.assertTrue(rec["5.0.1"]["facts"].startswith("TypeError: boom"))
        ck = FakeChecker()
        V.check_w2(ck, dict(CASE, facts_check=[]), [])
        self.assertIn("no facts_check: its facts aren't checked", ck.failures)

    def test_every_w2_case_has_a_facts_check(self):
        es = evalset.load()
        self.assertTrue(evalset.code(es.docs["w2"]["facts_prelude"]).strip())
        for c in es.cases("w2"):
            self.assertTrue(evalset.code(c["facts_check"]).strip(), c["id"])
            compile(V.facts_script(c, es.docs["w2"]["facts_prelude"]), c["id"], "exec")


class BlenderSetTests(unittest.TestCase):
    def test_version_problems(self):
        self.assertEqual(V.version_problems(["5.2.2", "5.0.1"]), [])
        self.assertEqual(V.version_problems(["5.2.2"]), ["no Blender 5.0.1: every fact must be checked in 5.2.2 and 5.0.1"])
        self.assertEqual(V.version_problems(["5.2.2", "5.2.2", "5.0.1"]), ["Blender 5.2.2 given twice"])
        self.assertEqual(V.version_problems(["5.2.2", "5.0.1", "?"]), ["Blender ? isn't one of the eval's versions (5.2.2, 5.0.1)"])

    def test_defaults_are_the_studios_blenders(self):
        from tools import blenders
        self.assertEqual(V.DEFAULT_BLENDERS, list(blenders.VERSIONS.values()))

    def test_one_blender_is_a_failure_not_a_pass(self):
        with tempfile.TemporaryDirectory(prefix="wm-verify-") as d:
            fake = os.path.join(d, "Blender")
            with open(fake, "w") as f:
                f.write(f"#!{sys.executable}\nimport sys\nif '--version' in sys.argv:\n    print('Blender 5.2.2 (fake)')\n"
                        "    sys.exit(0)\nprint('WM_RIGHT_OK')\nprint('WM_FACTS_OK')\n")
            os.chmod(fake, 0o755)
            work = os.path.join(d, "work")
            out = io.StringIO()
            with redirect_stdout(out):
                code = V.main(["--part", "w2", "--case", "w2-25", "--blender", fake, "--blender", os.path.join(d, "nope"),
                               "--work", work])
            self.assertEqual(code, 1)
            self.assertIn("no Blender 5.0.1: every fact must be checked", out.getvalue())
            self.assertIn("nope isn't there", out.getvalue())
            self.assertFalse(os.path.exists(work), "the work folder this run made is removed again")

    def test_one_blender_is_never_written_not_even_forced(self):
        """--force-write records failed checks, but never a run that lacks a version. Run on a copy of eval/, so the
        real files are never at risk."""
        with tempfile.TemporaryDirectory(prefix="wm-verify-") as d:
            fake = os.path.join(d, "Blender")
            with open(fake, "w") as f:
                f.write(f"#!{sys.executable}\nimport sys\nprint('Blender 5.2.2 (fake)')\n")
            os.chmod(fake, 0o755)
            copy = os.path.join(d, "eval")
            shutil.copytree(evalset.EVAL_DIR, copy)
            path = os.path.join(copy, evalset.FILES["w2"])
            with open(path, encoding="utf-8") as f:
                before = f.read()
            real = evalset.EVAL_DIR
            evalset.EVAL_DIR = copy
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    code = V.main(["--part", "w2", "--case", "w2-25", "--blender", fake, "--work", os.path.join(d, "w"),
                                   "--write", "--force-write"])
            finally:
                evalset.EVAL_DIR = real
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), before)
            self.assertEqual(code, 1)
            self.assertIn("not written: every result is recorded for Blender 5.2.2 and 5.0.1", out.getvalue())


class WorkFolderTests(unittest.TestCase):
    def test_default_work_folder(self):
        old = os.environ.pop("WM_SCRATCH", None)
        try:
            self.assertEqual(V.default_work(), os.path.join(_paths.HERE, "data", "verify-eval"))
            os.environ["WM_SCRATCH"] = "/somewhere/scratch"
            self.assertEqual(V.default_work(), "/somewhere/scratch/verify-eval")
        finally:
            os.environ.pop("WM_SCRATCH", None)
            if old is not None:
                os.environ["WM_SCRATCH"] = old


if __name__ == "__main__":
    unittest.main()
