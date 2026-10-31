"""The check wrapper, without Blender: a fake chimera and fake Blenders stand in."""
import os
import shutil
import sys
import tempfile
import unittest

from tests import _paths  # noqa: F401
from tools import blender_check as bc
from tools import blenders, scene_probe

# Stands in for `chimera --check-result`: finds `blender` on PATH the way Chimera does (a launcher
# script whose quoted .app path it follows), asks it for its version, and records its data dir.
FAKE_CHIMERA = r'''#!%(py)s
import json, os, re, shutil, subprocess, sys
a = sys.argv[1:]
data, target = a[a.index("--data-dir") + 1], a[a.index("--check-result") + 1]
launcher = shutil.which("blender")
src = open(launcher).read()
m = re.search(r'exec "([^"]+)"', src)
real = m.group(1) if m else launcher
v = subprocess.run([real, "--version"], capture_output=True, text=True).stdout.split()[1]
script = open(target).read()
out = "hello\n"
if "BAD_REPORT" in script:
    out += "Error: something Blender reported\n"
if "chimera scene probe" in script:
    out += 'chimera-probe: {"v":1,"objects":[["chimera_box","MESH","m",1]],"materials":[],"collections":[]}\n'
out += "data dir entries: %%d\n" %% len(os.listdir(data))
crash = "CRASH" in script
check = {"outcome": "failed" if crash else "passed", "runner": "Blender " + v, "summary": "s", "seconds": 0.1,
         "output": out + "launcher: " + launcher + "\n" + "data: " + data + "\n"}
if crash:
    check.update(error="AttributeError: nope", line=3)
sys.stderr.write("running it in Blender %%s, sandboxed…\n" %% v)
print(json.dumps({"check": check, "critique": ""}, indent=2))
sys.exit(1 if crash else 0)
'''

FAKE_BLENDER = '#!/bin/sh\necho "Blender %s LTS"\n'


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wm-check-")
        self.chimera = self.exe("chimera", FAKE_CHIMERA % {"py": sys.executable})
        self.b522 = self.exe("b522/Blender", FAKE_BLENDER % "5.2.2")
        self.b501 = self.exe("b501/Blender", FAKE_BLENDER % "5.0.1")
        self.paths = {"5.2.2": self.b522, "5.0.1": self.b501}
        self.root = os.path.join(self.tmp, "runs")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def exe(self, rel, text):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, 0o755)
        return path

    def script(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_launcher_execs_the_quoted_app_binary(self):
        t = bc.launcher_text("/Applications/Blender 3.app/Contents/MacOS/Blender")
        self.assertTrue(t.startswith("#!/bin/bash\n"))
        self.assertIn('exec "/Applications/Blender 3.app/Contents/MacOS/Blender" "$@"', t)
        with self.assertRaises(ValueError):
            bc.launcher_text('/x/"evil.app/Contents/MacOS/Blender')

    def test_stated_runner(self):
        self.assertEqual(bc.stated_runner("running it in Blender 5.2.2, sandboxed…\n"), ("Blender 5.2.2", "5.2.2"))
        self.assertEqual(bc.stated_runner("x\nrunning it in Python 3.13.12, sandboxed…"), ("Python 3.13.12", None))
        self.assertEqual(bc.stated_runner("check result: no script"), (None, None))

    def test_bad_lines_and_strict(self):
        out = ("ok\nError: Blender said no\n  Traceback (most recent call last):\n"
               'chimera-probe: {"objects":[["Error: in a name","MESH",null,1]]}\n')
        self.assertEqual(len(bc.bad_lines(out)), 2)  # the probe line doesn't count
        passed = {"outcome": "passed", "output": "fine\nBlender quit\n"}
        self.assertEqual(bc.strict_verdict(0, passed, True), (True, ""))
        self.assertFalse(bc.strict_verdict(0, passed, False)[0])
        self.assertFalse(bc.strict_verdict(0, dict(passed, output="Error: x"), True)[0])
        ok, why = bc.strict_verdict(1, {"outcome": "failed", "error": "KeyError: 'Transmission'"}, True)
        self.assertFalse(ok)
        self.assertIn("Transmission", why)
        self.assertFalse(bc.strict_verdict(2, {"outcome": "unsure"}, True)[0])
        self.assertFalse(bc.strict_verdict(0, {}, True)[0])

    def test_parse_json_tolerates_noise(self):
        self.assertEqual(bc.parse_json('{"check": {"outcome": "passed"}}'), {"check": {"outcome": "passed"}})
        self.assertEqual(bc.parse_json('warning\n{"check": {}}\n'), {"check": {}})
        self.assertIsNone(bc.parse_json("not json"))

    def test_each_version_gets_its_own_launcher_and_a_fresh_data_dir(self):
        s = self.script("ok.py", "import bpy\n")
        rs = bc.check_all([s], paths=self.paths, chimera=self.chimera, root=self.root)
        self.assertEqual([r["version"] for r in rs], ["5.2.2", "5.0.1"])
        for r in rs:
            self.assertTrue(r["version_ok"], r)
            self.assertTrue(r["strict"], r)
            self.assertEqual(r["outcome"], "passed")
            self.assertIn("data dir entries: 0", r["output"])
        launchers = [l for r in rs for l in r["output"].splitlines() if l.startswith("launcher: ")]
        datas = [l for r in rs for l in r["output"].splitlines() if l.startswith("data: ")]
        self.assertEqual(len(set(launchers)), 2)
        self.assertEqual(len(set(datas)), 2)
        self.assertEqual(os.listdir(self.root), [])  # run folders are removed unless --keep
        self.assertEqual(bc.exit_status(rs), 0)

    def test_crash_and_a_blender_report(self):
        rs = bc.check_all([self.script("c.py", "CRASH\n"), self.script("r.py", "BAD_REPORT\n")], wanted="5.2.2",
                          paths=self.paths, chimera=self.chimera, root=self.root)
        crash, report = rs
        self.assertEqual((crash["outcome"], crash["strict"], crash["line"]), ("failed", False, 3))
        self.assertEqual((report["outcome"], report["strict"]), ("passed", False))
        self.assertIn("Error: something Blender reported", report["strict_why"])
        self.assertEqual(bc.exit_status(rs), 1)
        self.assertIn("line 3: AttributeError: nope", bc.report(rs))

    def test_wrong_blender_is_an_error_not_a_result(self):
        paths = {"5.2.2": self.b501}  # says 5.0.1
        rs = bc.check_all([self.script("ok.py", "x\n")], paths=paths, chimera=self.chimera, root=self.root)
        self.assertFalse(rs[0]["version_ok"])
        self.assertFalse(rs[0]["strict"])
        self.assertIn("asked for Blender 5.2.2", rs[0]["problem"])
        self.assertEqual(bc.exit_status(rs), 2)

    def test_probe_is_appended_and_parsed(self):
        s = self.script("p.py", "import bpy\n")
        rs = bc.check_all([s], wanted=["5.0.1"], paths=self.paths, chimera=self.chimera, root=self.root, probe=True)
        self.assertEqual(rs[0]["probe"]["objects"][0]["name"], "chimera_box")
        self.assertTrue(rs[0]["strict"])
        with open(s) as f:
            self.assertEqual(f.read(), "import bpy\n")  # the original is left alone

    def test_keep_leaves_the_run_folder(self):
        rs = bc.check_all([self.script("ok.py", "x\n")], wanted="5.2.2", paths=self.paths, chimera=self.chimera,
                          root=self.root, keep=True)
        self.assertTrue(os.path.isfile(os.path.join(rs[0]["run_dir"], "bin", "blender")))

    def test_scratch_defaults_to_the_gitignored_data_folder(self):
        old = os.environ.pop("WM_SCRATCH", None)
        try:
            self.assertEqual(bc.SCRATCH_DEFAULT, os.path.join(_paths.HERE, "data", "scratch"))
            self.assertEqual(bc.scratch_root(), bc.SCRATCH_DEFAULT)  # never the system temp folder
            self.assertFalse(bc.SCRATCH_DEFAULT.startswith(tempfile.gettempdir()))
            self.assertEqual(bc.scratch_root(self.root), self.root)
            os.environ["WM_SCRATCH"] = self.root
            self.assertEqual(bc.scratch_root(), self.root)
        finally:
            os.environ.pop("WM_SCRATCH", None)
            if old is not None:
                os.environ["WM_SCRATCH"] = old
        with open(os.path.join(_paths.HERE, ".gitignore"), encoding="utf-8") as f:
            self.assertIn("\ndata/\n", "\n" + f.read())

    def test_missing_binary(self):
        old = os.environ.pop("CHIMERA_BIN", None)
        try:
            with self.assertRaises(RuntimeError):
                bc.chimera_bin(None)
        finally:
            if old is not None:
                os.environ["CHIMERA_BIN"] = old


class BlendersTests(unittest.TestCase):
    def test_overrides_and_pick(self):
        v = blenders.parse_overrides(["4.2.0=/x/Blender"])
        self.assertEqual(v["4.2.0"], "/x/Blender")
        self.assertEqual([p[0] for p in blenders.pick(v, "5.0.1,4.2.0")], ["5.0.1", "4.2.0"])
        with self.assertRaises(ValueError):
            blenders.pick(v, "9.9")
        with self.assertRaises(ValueError):
            blenders.parse_overrides(["nopath"])

    def test_symlinks_are_refused(self):
        tmp = tempfile.mkdtemp(prefix="wm-bl-")
        try:
            real = os.path.join(tmp, "Blender")
            with open(real, "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(real, 0o755)
            os.symlink(real, os.path.join(tmp, "to-blender"))  # not "blender": the Mac's disk ignores case
            self.assertEqual(blenders.check_path(real), "")
            self.assertIn("symlink", blenders.check_path(os.path.join(tmp, "to-blender")))
            self.assertIn("isn't there", blenders.check_path(os.path.join(tmp, "nope")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_probe_lines_are_recognised(self):
        self.assertTrue(scene_probe.is_probe_line('chimera-probe: {"v":1}'))
        self.assertTrue(scene_probe.is_probe_line('…chimera-probe: {"v":1}'))
        self.assertFalse(scene_probe.is_probe_line("Error: chimera-probe: x"))


if __name__ == "__main__":
    unittest.main()
