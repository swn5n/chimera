"""End to end: join hand-made Blender pieces (test fixtures, never training data), run the joined script through
`chimera --check-result` in real Blender, and check that the line map places a broken piece's crash in its step.

Skipped unless CHIMERA_BIN names a Chimera binary (build it with
`cd app && PATH=/opt/homebrew/bin:$PATH go build -o <path> .`, removing the old file first) and Blender 5.2.2 is
installed. BLENDER_522 / BLENDER_501 override the app paths; CONTRACT_SCRATCH is where the runs' folders go
(default: the system temp folder). Each run gets its own --data-dir and a PATH shim (a bash launcher that execs
the app: Blender crashes when started through a symlink). About 10 s in all.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from tests import _paths  # noqa: F401
from tests import contract_fixtures as F
from contract.join import alone_script, join
from contract.linemap import locate_check
from contract import prompt
from contract.validate import validate_piece

CHIMERA = os.environ.get("CHIMERA_BIN", "")
BLENDER = {"5.2.2": os.environ.get("BLENDER_522", "/Applications/Blender 3.app/Contents/MacOS/Blender"),
           "5.0.1": os.environ.get("BLENDER_501", "/Applications/Blender.app/Contents/MacOS/Blender")}
SCRATCH = os.environ.get("CONTRACT_SCRATCH") or None


def check(script, version):
    """(exit code, verdict JSON, stderr) of `chimera --check-result script.py` with that Blender first on PATH."""
    d = tempfile.mkdtemp(prefix="contract-check-", dir=SCRATCH)
    try:
        shim = os.path.join(d, "shim")
        os.makedirs(shim)
        launcher = os.path.join(shim, "blender")
        with open(launcher, "w") as f:
            f.write('#!/bin/bash\nexec "%s" "$@"\n' % BLENDER[version])
        os.chmod(launcher, 0o755)
        path = os.path.join(d, "script.py")
        with open(path, "w") as f:
            f.write(script)
        env = dict(os.environ, PATH=shim + os.pathsep + os.environ.get("PATH", ""))
        p = subprocess.run([CHIMERA, "--data-dir", os.path.join(d, "data"), "--check-result", path], env=env, cwd=d,
                           capture_output=True, text=True, timeout=300)
        return p.returncode, json.loads(p.stdout), p.stderr
    finally:
        shutil.rmtree(d, ignore_errors=True)


@unittest.skipUnless(CHIMERA and os.access(CHIMERA, os.X_OK), "set CHIMERA_BIN to a Chimera binary")
@unittest.skipUnless(os.path.exists(BLENDER["5.2.2"]), "Blender 5.2.2 not installed")
class JoinedScriptInBlenderTests(unittest.TestCase):
    def run_check(self, script, version="5.2.2"):
        code, verdict, err = check(script, version)
        self.assertIn("running it in Blender %s" % version, err)  # the shim picked the version asked for
        return code, verdict

    def test_well_formed_pieces_pass_joined(self):
        j = join(F.BLENDER_PLAN, F.BLENDER_OUTPUTS)
        self.assertFalse(j.fallback, j.reasons)
        for version in [v for v in BLENDER if os.path.exists(BLENDER[v])]:
            with self.subTest(version=version):
                code, verdict = self.run_check(j.script, version)
                c = verdict["check"]
                self.assertEqual((code, c["outcome"]), (0, "passed"), c)
                self.assertIn("up to its render", c["summary"])  # _chimera_output saved, then rendered once
                self.assertIn("chimera: saved reading_corner.blend", c["output"])
                self.assertNotIn("chimera: stand-in", c["output"])
                self.assertNotIn("Traceback", c["output"])

    def test_a_piece_alone_makes_its_stand_in(self):
        p = validate_piece(F.S3, "blender", sid="s3", deps=["s2"])
        for how, script in (("its own main guard", p.code), ("alone_script", alone_script(p))):
            with self.subTest(how):
                code, verdict = self.run_check(script)
                self.assertEqual((code, verdict["check"]["outcome"]), (0, "passed"), verdict)
                self.assertIn("chimera: stand-in table", verdict["check"]["output"])

    def test_crash_in_a_build_function_maps_to_its_step(self):
        outputs = dict(F.BLENDER_OUTPUTS, s3=F.S3_BROKEN)
        j = join(F.BLENDER_PLAN, outputs)
        self.assertFalse(j.fallback, j.reasons)
        code, verdict = self.run_check(j.script)
        self.assertEqual((code, verdict["check"]["outcome"]), (1, "failed"), verdict)
        loc = locate_check(verdict, j.linemap, j.script)
        self.assertEqual((loc["step"], loc["part"], loc["function"], loc["repair"]), ("s3", "build", "build_s3", "s3"))
        self.assertTrue(loc["source_matches"], loc)
        self.assertIn("Transmission", loc["error"])
        piece_lines = j.pieces["s3"].code.split("\n")
        self.assertEqual(piece_lines[loc["piece_line"] - 1], F.BROKEN_LINE_S3)  # the line the worker wrote
        # and the repair request names it the way the worker numbered it
        req = prompt.repair_request(F.BLENDER_PLAN, 2, outputs, F.S3_BROKEN, loc)
        self.assertIn("in Blender 5.2.2:\nline %d in build_s3: %s\nKeyError:" % (loc["piece_line"], F.BROKEN_LINE_S3.strip()),
                      req.messages[1]["content"])

    def test_crash_in_a_helper_maps_to_its_step(self):
        j = join(F.BLENDER_PLAN, dict(F.BLENDER_OUTPUTS, s2=F.S2_BROKEN))
        code, verdict = self.run_check(j.script)
        self.assertEqual((code, verdict["check"]["outcome"]), (1, "failed"), verdict)
        loc = locate_check(verdict, j.linemap, j.script)
        self.assertEqual((loc["step"], loc["part"], loc["function"], loc["repair"]), ("s2", "helper", "_s2_box", "s2"))
        self.assertIn("use_auto_smooth", loc["error"])
        self.assertEqual(j.pieces["s2"].code.split("\n")[loc["piece_line"] - 1], F.BROKEN_LINE_S2)

    def test_settings_using_the_steps_own_constant_pass_joined(self):
        # Review, Oct 29: hoisting SETTINGS_s2 above _s2_LEG made this NameError joined, though it passes alone.
        s2 = F.S2.replace('SETTINGS_s2 = {"top_size": 0.6, "height": 0.55, "leg": 0.04}',
                          '_s2_LEG = 0.04\nSETTINGS_s2 = {"top_size": 0.6, "height": 0.55, "leg": _s2_LEG}')
        self.assertNotEqual(s2, F.S2)
        j = join(F.BLENDER_PLAN, dict(F.BLENDER_OUTPUTS, s2=s2))
        self.assertFalse(j.fallback, j.reasons)
        for version in [v for v in BLENDER if os.path.exists(BLENDER[v])]:
            with self.subTest(version=version):
                code, verdict = self.run_check(j.script, version)
                self.assertEqual((code, verdict["check"]["outcome"]), (0, "passed"), verdict["check"])
                self.assertNotIn("NameError", verdict["check"]["output"])

    def test_bad_import_maps_to_the_step_that_wrote_it(self):
        # Review, Oct 29: "from mathutils import Vector, radians" was merged with s2's Vector and blamed on s2.
        s3 = F.S3.replace("import bmesh\n", "import bmesh\nfrom mathutils import Vector, radians\n", 1)
        outputs = dict(F.BLENDER_OUTPUTS, s3=s3)
        j = join(F.BLENDER_PLAN, outputs)
        self.assertFalse(j.fallback, j.reasons)
        code, verdict = self.run_check(j.script)
        self.assertEqual((code, verdict["check"]["outcome"]), (1, "failed"), verdict)
        loc = locate_check(verdict, j.linemap, j.script)
        self.assertEqual((loc["step"], loc["part"], loc["repair"], loc["definite"]), ("s3", "import", "s3", True))
        self.assertTrue(loc["source_matches"], loc)
        self.assertIn("radians", loc["error"])
        req = prompt.repair_request(F.BLENDER_PLAN, 2, outputs, s3, loc)
        self.assertIn("line %d in the imports: from mathutils import radians" % loc["piece_line"],
                      req.messages[1]["content"])



if __name__ == "__main__":
    unittest.main()
