"""datagen/chimera.py against a real Chimera binary, built from app/ once per run into a scratch folder ($WM_SCRATCH,
else data/scratch/; $CHIMERA_BIN's, copied there, when it names one), and removed afterwards. Skipped without Go or
CHIMERA_BIN.

Every method runs the binary for real: the request modes, the reply reader, the assemble jobs and the join, a result
check of a tiny Python file (and one in Blender 5.0.1), and the names sheets of Blender 5.2.2 and 5.0.1, which differ
(5.0.1's Principled BSDF has no "Thin Wall"). Chimera's Ollama is a stand-in (runner/mock_ollama), so the real one is
never asked. A stand-in binary (a shell script) shows what check_result passes: the fresh data folder, the goal, the
look turned off, the Blender launcher first on PATH.
"""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from tests import _paths
from tests import datagen_fakes as F
from datagen import chimera as C
from datagen.common import msgs_tokens
from runner import mock_ollama
from tools import blender_check, blenders

MARK = mock_ollama.MARK

GOAL = "Build a reading corner in Blender: a table with a lamp on it. " + MARK
PLAN = {"title": "Reading corner", "kind": "blender", "summary": "A table with a lamp on it. " + MARK, "steps": [
    {"id": "a", "title": "Table", "kind": "blender", "instructions": "Build a table."},
    {"id": "b", "title": "Lamp", "kind": "blender", "instructions": "Put a lamp on the table.", "depends_on": ["a"]}]}
CODE_PLAN = {"title": "Word counter", "kind": "code", "summary": "A command-line word counter. " + MARK, "steps": [
    {"id": "s1", "title": "Counting", "kind": "code", "instructions": "Write count_words(text)."},
    {"id": "s2", "title": "README", "kind": "writing", "instructions": "Explain the tool.", "depends_on": ["s1"]}]}
SHEET = "ShaderNodeEmission inputs: Color, Strength"
NAMES_HEAD = "printed by that Blender. Use these, not ones you remember from other versions:\n"
PYTHON_OK = MARK + "\nimport sys\n\n\ndef total(xs):\n    return sum(xs)\n\n\nif __name__ == \"__main__\":\n" \
            "    print(\"total\", total([1, 2, 3]))\n    sys.exit(0)\n"
PYTHON_CRASH = PYTHON_OK.replace("total([1, 2, 3])", "totl([1, 2, 3])")
BLENDER_OK = MARK + "\nimport bpy\n\nfor o in list(bpy.data.objects):\n    bpy.data.objects.remove(o)\n" \
             "bpy.ops.mesh.primitive_cube_add(size=1)\nbpy.context.object.name = \"chimera_box\"\n" \
             "print(\"objects\", len(bpy.data.objects))\n"

_bin = _tmp = _srv = None
_url = ""


def setUpModule():
    global _bin, _tmp, _srv, _url
    if not F.HAVE_CHIMERA:
        raise unittest.SkipTest("needs Go to build Chimera, or CHIMERA_BIN")
    _tmp = tempfile.mkdtemp(prefix="test-datagen-chimera-", dir=blender_check.scratch_root())
    try:
        _bin = F.build_chimera(_tmp)  # a fresh copy of $CHIMERA_BIN, else built from app/
    except RuntimeError:
        shutil.rmtree(_tmp, ignore_errors=True)
        raise
    _srv, _url = mock_ollama.serve(0, os.path.join(_tmp, "ollama.jsonl"))


def tearDownModule():
    if _srv:
        _srv.shutdown()
        _srv.server_close()
    if _tmp:
        shutil.rmtree(_tmp, ignore_errors=True)


def chimera(**kw):
    return C.Chimera(_bin, env={"OLLAMA_HOST": _url}, **kw)


def asked_ollama():
    """The paths Chimera asked the stand-in Ollama for."""
    path = os.path.join(_tmp, "ollama.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l)["path"] for l in f if l.strip()]


def piece(sid, deps=()):
    return mock_ollama.contract_piece(sid, list(deps))


class WorkTree(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="work-", dir=_tmp)
        self.addCleanup(shutil.rmtree, self.work, True)


class BinaryTests(WorkTree):
    def test_version_is_the_apps(self):
        with open(os.path.join(_paths.APP, "main.go"), encoding="utf-8") as f:
            want = re.search(r'const Version = "([^"]+)"', f.read()).group(1)
        self.assertEqual(chimera().version(), want)

    def test_sha256_is_the_files_and_follows_it(self):
        copy = os.path.join(self.work, "chimera-copy")
        shutil.copyfile(_bin, copy)
        ch = C.Chimera(copy)
        with open(copy, "rb") as f:
            self.assertEqual(ch.sha256(), hashlib.sha256(f.read()).hexdigest())
        before = ch.sha256()
        with open(copy, "ab") as f:
            f.write(b"\0")
        self.assertNotEqual(ch.sha256(), before)

    def test_failures_raise_chimera_error(self):
        with self.assertRaisesRegex(C.ChimeraError, r"worker request: no step 5: the plan has 2"):
            chimera().worker_request(PLAN, 5, {})
        with self.assertRaisesRegex(C.ChimeraError, r'assemble: unknown mode "nonsense"'):
            chimera().validate([{"text": "x", "mode": "nonsense"}])
        with self.assertRaisesRegex(C.ChimeraError, "couldn't run"):
            C.Chimera(os.path.join(self.work, "no-such-chimera")).version()
        with self.assertRaisesRegex(C.ChimeraError, "not one JSON object"):
            C.Chimera("/bin/echo").plan_request("g")


class RequestTests(unittest.TestCase):
    def test_a_worker_request_is_the_binarys_own(self):
        outputs = {"a": piece("s1")}
        got = chimera().worker_request(PLAN, 1, outputs, goal=GOAL, names=SHEET)
        payload = {"plan": PLAN, "index": 1, "outputs": outputs, "goal": GOAL, "names": SHEET, "names_gate": True,
                   "critique": ""}
        p = subprocess.run([_bin, "--hydra-worker-request"], input=json.dumps(payload, ensure_ascii=False).encode(),
                           capture_output=True, check=True)
        self.assertEqual(got, json.loads(p.stdout))
        self.assertEqual(set(got), {"messages", "need_ctx", "mode", "sid", "n", "lone", "deps", "round2_matched"})
        self.assertEqual((got["sid"], got["n"], got["deps"], got["mode"], got["lone"]),
                         ("s2", 2, ["s1"], "blender", False))
        self.assertTrue(got["messages"][0]["content"].endswith(NAMES_HEAD + SHEET))
        self.assertIn("provides: chimera_s1", got["messages"][1]["content"])
        self.assertEqual(got["need_ctx"], msgs_tokens(got["messages"]) + 4096)

    def test_the_names_gate(self):
        ch = chimera()
        gated = ch.worker_request(CODE_PLAN, 0, {}, goal="Write a word counter. " + MARK, names=SHEET)
        ungated = ch.worker_request(CODE_PLAN, 0, {}, goal="Write a word counter. " + MARK, names=SHEET, names_gate=False)
        bare = ch.worker_request(CODE_PLAN, 0, {}, goal="Write a word counter. " + MARK)
        self.assertEqual(gated, bare)
        self.assertEqual(ungated["messages"][0]["content"], bare["messages"][0]["content"] + "\n\nThe exact names in the "
                         "Blender this will run on, " + NAMES_HEAD + SHEET)
        said = ch.worker_request(CODE_PLAN, 0, {}, goal="Write a word counter as a bpy script. " + MARK, names=SHEET)
        self.assertTrue(said["messages"][0]["content"].endswith(SHEET))
        self.assertTrue(ch.worker_request(PLAN, 0, {}, names=SHEET)["messages"][0]["content"].endswith(SHEET))

    def test_outputs_a_failed_step_and_round_2(self):
        ch = chimera()
        left_out = ch.worker_request(PLAN, 1, {})
        self.assertEqual(ch.worker_request(PLAN, 1, {"a": None}), left_out)
        self.assertEqual(ch.worker_request(PLAN, 1, {"a": {"output": piece("s1"), "status": "failed"}}), left_out)
        self.assertEqual(ch.worker_request(PLAN, 1, {"a": {"output": piece("s1")}}),
                         ch.worker_request(PLAN, 1, {"a": piece("s1")}))
        r2 = ch.worker_request(PLAN, 0, {}, prev_result="```python\n" + MARK + "\nprint(1)\n```", critique="Too small.",
                               room=9000)
        self.assertIn("Too small.", r2["messages"][1]["content"])
        self.assertEqual(r2["need_ctx"], msgs_tokens(r2["messages"]) + 9000)

    def test_a_repair_request(self):
        ch = chimera()
        crash = {"step": "s1", "line": 7, "piece_line": 7, "function": "build_s1",
                 "source": "obj = bpy.data.objects.new()", "error": "TypeError: missing argument",
                 "runner": "Blender 5.2.2"}
        got = ch.worker_request(PLAN, 0, {}, prev_result="last round", critique="c", piece=piece("s1"), crash=crash)
        user = got["messages"][1]["content"]
        self.assertIn("TypeError: missing argument", user)
        self.assertIn(MARK, user)  # the piece is in it
        self.assertNotIn("last round", user)
        with self.assertRaises(ValueError):
            ch.worker_request(PLAN, 0, {}, crash=crash)

    def test_a_plan_request(self):
        ch = chimera()
        refs = [{"title": "Oak", "kind": "blender", "summary": "A wood material.", "content": MARK, "score": 0.5},
                {"title": "Unrelated", "kind": "snippet", "summary": "No.", "content": MARK, "score": 0.2}]
        history = [{"role": "user", "content": "a table first " + MARK},
                   {"role": "assistant", "content": "Done. " + MARK}]
        got = ch.plan_request(GOAL, history=history, refs=refs)
        self.assertEqual(set(got), {"messages", "need_ctx", "format", "helper_fits"})
        system, user = got["messages"][0]["content"], got["messages"][1]["content"]
        self.assertTrue(system.startswith(mock_ollama.PLANNER_OPENING))
        self.assertTrue(user.startswith("Earlier in this chat (for context only):"))
        self.assertIn("The task:\n" + GOAL, user)
        self.assertIn("--- Oak (blender) ---", user)
        self.assertNotIn("Unrelated", user)
        self.assertEqual((got["format"], got["helper_fits"]), ("json", True))
        self.assertEqual(got["need_ctx"], msgs_tokens(got["messages"]) + 2048)
        later = ch.plan_request(GOAL, prior="the result " + MARK, critique="The lamp floats.")
        self.assertIn("The previous attempt produced this result:\nthe result", later["messages"][1]["content"])
        self.assertIn("What still needs work:\nThe lamp floats.", later["messages"][1]["content"])
        empty = ch.plan_request(GOAL, critique="It wrote nothing.")
        self.assertIn("(nothing: the last round's result was empty)", empty["messages"][1]["content"])
        self.assertFalse(ch.plan_request("x" * 30000 + MARK)["helper_fits"])

    def test_a_review_request(self):
        ch = chimera()
        got = ch.review_request(GOAL, "```python\n" + MARK + "\n```")
        self.assertTrue(got["messages"][0]["content"].startswith(mock_ollama.REVIEW_OPENING))
        self.assertEqual(got["messages"][1]["content"],
                         "The task:\n" + GOAL + "\n\nThe result so far:\n```python\n" + MARK + "\n```")
        self.assertEqual((got["format"], got["helper_fits"], got["need_ctx"]),
                         ("json", True, msgs_tokens(got["messages"]) + 1024))
        self.assertFalse(ch.review_request(GOAL, "y" * 12000 + MARK)["helper_fits"])


class ReplyTests(unittest.TestCase):
    def test_a_plan_is_read_and_cleaned(self):
        ch = chimera()
        reply = MARK + "\nHere is the plan:\n" + json.dumps({"title": "", "kind": "odd", "steps": [
            {"title": "Seat", "kind": "blender"}, {"id": "x", "title": "Legs", "depends_on": ["s1", "later"]}]})
        got = ch.read_plan(reply)
        self.assertEqual(got, {"ok": True, "plan": {"title": "Long task", "kind": "general", "summary": "", "steps": [
            {"id": "s1", "title": "Seat", "kind": "blender", "instructions": "Seat", "depends_on": []},
            {"id": "x", "title": "Legs", "kind": "general", "instructions": "Legs", "depends_on": ["s1"]}]}})
        req = ch.worker_request(got["plan"], 1, {"s1": piece("s1")})
        self.assertEqual(req["deps"], ["s1"])
        for bad in ("I can't plan that. " + MARK, '{"title": "None", "steps": []} ' + MARK, ""):
            self.assertEqual(ch.read_plan(bad), {"ok": False, "plan": None})

    def test_a_review_is_read(self):
        ch = chimera()
        reply = 'Verdict: {"done": false, "score": 40, "critique": "The lamp floats. %s"}' % MARK
        self.assertEqual(ch.read_review(reply),
                         {"ok": True, "done": False, "score": 40, "critique": "The lamp floats. " + MARK})
        self.assertEqual(ch.read_review('{"done": true, "score": 72.5, "critique": "%s"}' % MARK),
                         {"ok": False, "done": False, "score": 0, "critique": ""})
        self.assertFalse(ch.read_review("Looks fine. " + MARK)["ok"])


class AssembleTests(unittest.TestCase):
    def test_validate_alone_scan_and_slug(self):
        ch = chimera()
        verdicts = ch.validate([{"text": piece("s1"), "mode": "blender", "sid": "s1"},
                                {"text": "No code here. " + MARK, "mode": "blender", "sid": "s2", "deps": ["s1"]}])
        self.assertEqual([v["sid"] for v in verdicts], ["s1", "s2"])
        self.assertTrue(verdicts[0]["ok"], verdicts[0]["issues"])
        self.assertFalse(verdicts[1]["ok"])
        self.assertEqual(verdicts[0]["handoff"]["provides"], 'chimera_s1 as ctx["objects"]["s1"]')
        alone = ch.alone([{"text": piece("s1"), "mode": "blender", "sid": "s1"}, {"text": MARK, "mode": "blender"}])
        self.assertIn("build_s1(ctx)", alone[0])
        self.assertIsNone(alone[1])
        scans = ch.scan(["x = 1\n", "def broken(:\n    pass\n"])
        self.assertTrue(scans[0]["ok"])
        self.assertEqual((scans[1]["ok"], scans[1]["line"]), (False, 1))
        self.assertEqual(ch.slug(["Reading corner!"]), ["reading_corner"])
        self.assertEqual(ch.validate([]), [])

    def test_join_and_locate(self):
        ch = chimera()
        joined = ch.join(PLAN, {"a": piece("s1"), "b": piece("s2", ["s1"])}, goal=GOAL)
        self.assertFalse(joined["fallback"], joined["reasons"])
        self.assertEqual(joined["script_kind"], "run_blender")
        script = joined["script"].split("\n")
        line = next(n for n, l in enumerate(script, 1) if "chimera_s2_mesh" in l)
        spot = ch.locate([{"linemap": joined["linemap"], "check": {"outcome": "failed", "line": line, "error": "E",
                                                                    "runner": "Blender 5.2.2"}}])[0]
        self.assertEqual((spot["step"], spot["function"], spot["repair"]), ("s2", "build_s2", "s2"))
        failed = ch.join(PLAN, {"a": piece("s1")}, goal=GOAL)
        self.assertEqual(failed["failed"], ["s2"])


class MemoTests(unittest.TestCase):
    def test_a_repeat_runs_nothing_and_gets_its_own_copy(self):
        ch = chimera()
        with mock.patch.object(C.subprocess, "run", wraps=subprocess.run) as run:
            first = ch.plan_request(GOAL)
            first["messages"].clear()
            again = ch.plan_request(GOAL)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(len(again["messages"]), 2)
            ch.plan_request(GOAL + " ")
            self.assertEqual(run.call_count, 2)

    def test_the_memo_is_bounded(self):
        ch = chimera(memo_bytes=1)
        ch.slug(["a"])
        ch.slug(["b"])
        self.assertEqual(len(ch._memo), 1)
        with mock.patch.object(C.subprocess, "run", wraps=subprocess.run) as run:
            ch.slug(["b"])
            ch.slug(["a"])
            self.assertEqual(run.call_count, 1)


class CheckTests(WorkTree):
    def write(self, name, text):
        path = os.path.join(self.work, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_a_python_check(self):
        checks = os.path.join(self.work, "checks")
        ok = chimera().check_result(self.write("ok.py", PYTHON_OK), work_dir=checks)
        self.assertEqual((ok["exit"], ok["check"]["outcome"]), (0, "passed"), ok)
        self.assertTrue(ok["stated"].startswith("Python"), ok["stated"])
        self.assertIn("total 6", ok["check"]["output"])
        bad = chimera().check_result(self.write("bad.py", PYTHON_CRASH), work_dir=checks,
                                     goal="Sum some numbers. " + MARK)
        self.assertEqual((bad["exit"], bad["check"]["outcome"]), (1, "failed"), bad)
        self.assertIn("NameError", bad["check"]["error"])
        self.assertIn("NameError", bad["critique"])
        self.assertEqual(os.listdir(checks), [])
        self.assertNotIn("/api/chat", asked_ollama())

    def test_no_verdict_raises(self):
        with self.assertRaisesRegex(C.ChimeraError, "no verdict"):
            chimera().check_result(self.write("reply.md", "No script here. " + MARK), work_dir=self.work)

    def test_what_the_check_is_given(self):
        fake = self.write("fake-chimera", "#!/bin/bash\n# " + MARK + "\n"
                          "printf '%s\\n' \"$@\" > \"$CHECK_ARGS\"\n"
                          "ls -A \"$2\" > \"$CHECK_ARGS.data\"\n"
                          "echo \"$PATH\" > \"$CHECK_ARGS.path\"\n"
                          "echo 'running it in Python 3.0, sandboxed' >&2\n"
                          "printf '{\"check\": {\"outcome\": \"skipped\"}, \"look\": \"%s\"}\\n' \"$CHIMERA_LOOK_MODEL\"\n"
                          "exit 2\n")
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
        args = os.path.join(self.work, "args.txt")
        checks = os.path.join(self.work, "checks")
        ch = C.Chimera(fake, env={"CHECK_ARGS": args})
        got = ch.check_result("script.py", goal="the goal", work_dir=checks, blender="/bin/ls")
        self.assertEqual(got, {"check": {"outcome": "skipped"}, "look": C.NO_LOOK, "exit": 2, "stated": "Python 3.0"})
        with open(args, encoding="utf-8") as f:
            argv = f.read().split("\n")
        self.assertEqual(argv[0], "--data-dir")
        self.assertTrue(argv[1].startswith(os.path.join(checks, "check-")) and argv[1].endswith("/data"), argv[1])
        self.assertEqual(argv[2:6], ["--check-result", os.path.abspath("script.py"), "--check-goal", "the goal"])
        with open(args + ".data", encoding="utf-8") as f:
            self.assertEqual(f.read(), "")  # a fresh data folder
        with open(args + ".path", encoding="utf-8") as f:
            self.assertEqual(f.read().split(os.pathsep)[0], os.path.join(os.path.dirname(argv[1]), "bin"))
        self.assertEqual(os.listdir(checks), [])
        with self.assertRaisesRegex(C.ChimeraError, "isn't there"):
            ch.check_result("script.py", work_dir=checks, blender=os.path.join(self.work, "no-blender"))

    @unittest.skipIf(blenders.check_path(blenders.VERSIONS["5.0.1"]), "needs Blender 5.0.1")
    def test_a_blender_check_in_the_version_asked(self):
        got = chimera().check_result(self.write("box.py", BLENDER_OK), work_dir=self.work,
                                     blender=blenders.VERSIONS["5.0.1"])
        self.assertEqual((got["stated"], got["check"]["runner"]), ("Blender 5.0.1", "Blender 5.0.1"), got)
        self.assertEqual(got["check"]["outcome"], "passed", got)
        self.assertNotIn("/api/chat", asked_ollama())


class NamesTests(WorkTree):
    def sheet(self, version):
        path = blenders.VERSIONS[version]
        if blenders.check_path(path):
            self.skipTest(f"needs Blender {version} at {path}")
        return chimera().blender_names(path, self.work), path

    def test_each_blender_prints_its_own_sheet(self):
        new, _ = self.sheet("5.2.2")
        old, _ = self.sheet("5.0.1")
        for s in (new, old):
            self.assertTrue(s.startswith("ShaderNodeBsdfPrincipled inputs: Base Color"), s[:200])
            self.assertIn("bmesh.ops.create_cone:", s)
            self.assertEqual(s, s.strip())
        self.assertIn("Thin Wall", new.split("\n")[0])
        self.assertNotIn("Thin Wall", old.split("\n")[0])
        self.assertEqual(os.listdir(self.work), [])

    def test_a_sheet_is_asked_for_once(self):
        path = blenders.VERSIONS["5.2.2"]
        if blenders.check_path(path):
            self.skipTest(f"needs Blender 5.2.2 at {path}")
        ch = chimera()
        first = ch.blender_names(path, self.work)
        with mock.patch.object(C.subprocess, "run", wraps=subprocess.run) as run:
            self.assertEqual(ch.blender_names(path, self.work), first)
            self.assertEqual(run.call_count, 0)
        req = ch.worker_request(PLAN, 0, {}, names=first)
        self.assertTrue(req["messages"][0]["content"].endswith(NAMES_HEAD + first))

    def test_no_blender_no_sheet(self):
        with self.assertRaisesRegex(C.ChimeraError, "isn't there"):
            chimera().blender_names(os.path.join(self.work, "Blender"), self.work)


if __name__ == "__main__":
    unittest.main()
