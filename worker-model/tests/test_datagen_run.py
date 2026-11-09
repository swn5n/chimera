"""datagen/run.py and run_datagen.sh: the seed errors a resumed start replays, the early stop once per data folder,
Chimera's fingerprint (every record carries it, a changed one stops a start until --new-binary-ok, the build gets
it, the names sheets are printed again at every start), the exit code for seeds that ended in an error, the Python
sandbox check, the run's EvalIndex in task.Env, the data generator's format (records of another are made again and
refused by a build-only start), main's refusal to touch a finished smoke of another format in the default folder, and
run_datagen.sh's lending check, arguments, exit codes, its log in the data folder in use, its refusal to run a
finished smoke again in the default folder and its run folders outside the home folder (WM_SCRATCH). The format is 6
since the fifth smoke run (Nov 6), so the five smoke runs' records (1, 2, 3, 4 and 5) are another format's, and a new
run is told to go into data/gen/smoke6.

run_tasks runs with a stand-in run_seed. main runs against the stand-in Ollama of tests/datagen_fakes.py, a Chimera
binary built from app/ into the scratch folder and real Blender 5.2.2 and 5.0.1 (for the names sheets), with
run_seed, build and report standing in where a test only looks at main; and once for real, the tasks stage of three
values-step seeds through main, then the build and the report (ValuesRunTests, format 6): ctx["values"] in the
contract, ctx_channel a gate with a tell that the stand-in teacher follows once told, soft on a step with a dependent
and hard on one without, the values-step note in the teacher's copies only, every stored request the binary's, and no
teacher text in a request or a kept target. run_datagen.sh runs from a copy in a scratch
tree whose app/ is a tiny Go program and whose datagen.run only records its arguments, against a stand-in of
Chimera's /api/state on a free port (CHIMERA_UI_PORTS): never the real Chimera or Ollama. Every seed text here is a
test fixture with the mark, never training data.
"""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from tests import _paths
from tests import datagen_fakes as F
from contract import texts as CT
from datagen import blender_gate as BG
from datagen import build as B
from datagen import common as C
from datagen import hints as H
from datagen import pysandbox
from datagen import report as RP
from datagen import run as R
from datagen import sizes
from datagen import task as T
from datagen.chimera import Chimera
from tools import blender_check, blenders
from tools.check_overlap import EvalIndex

MARK = F.MARK
HAVE_BLENDER = all(not blenders.check_path(p) for p in blenders.VERSIONS.values())
GATE = {"idle_switch_s": 0.05}
SCRIPT = os.path.join(_paths.HERE, "run_datagen.sh")

_tmp = _bin = _fake = None


def setUpModule():
    global _tmp, _bin, _fake
    _tmp = tempfile.mkdtemp(prefix="test-datagen-run-", dir=blender_check.scratch_root())
    if F.HAVE_CHIMERA:
        try:
            _bin = F.build_chimera(os.path.join(_tmp, "bin"))  # a fresh copy of $CHIMERA_BIN, else built from app/
        except RuntimeError:
            shutil.rmtree(_tmp, ignore_errors=True)
            raise
    _fake = F.FakeOllama()


def tearDownModule():
    if _fake:
        _fake.stop()
    if _tmp:
        shutil.rmtree(_tmp, ignore_errors=True)


def seed(k, category="python"):
    sid = f"n-{category}-{k:04d}-00"
    return {"seed_id": sid, "key": sid, "category": category, "source": "new",
            "text": f"Please make the mock thing number {k}. {MARK}"}


def done(s, kept=1, tried=1):
    return {"key": s["seed_id"], "seed": s, "status": "done", "error": None, "round2": None,
            "rounds": [{"steps": [{"kept": {"from": "cand", "index": 0} if j < kept else None}
                                  for j in range(tried)]}]}


def error(s, why):
    return {"key": s["seed_id"], "seed": s, "status": "error", "error": why, "rounds": [], "round2": None}


class Env:
    """What run_tasks reads of a task.Env."""

    def __init__(self, fingerprint=None):
        self.fingerprint = fingerprint


# ---------------------------------------------------------------- run_tasks

class RunTasksCase(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="runtasks-", dir=_tmp)
        self.addCleanup(shutil.rmtree, self.data, True)
        self.log = os.path.join(self.data, "progress.log")

    def store(self):
        return C.Store(os.path.join(self.data, "tasks.jsonl"))

    def go(self, fn, seeds, size, env=None, **kw):
        with mock.patch.object(T, "run_seed", side_effect=fn):
            with contextlib.redirect_stderr(io.StringIO()):
                return R.run_tasks(env, seeds, self.store(), R.Stopper(self.data), size, log=self.log, **kw)

    def logged(self):
        with open(self.log, encoding="utf-8") as f:
            return f.read()


class SameErrorTests(RunTasksCase):
    """A1: seeds whose error replays in seconds from the caches mustn't stop every later start."""

    def test_the_same_error_as_the_last_start_doesnt_stop_the_run(self):
        seeds = [seed(k) for k in range(20)]
        bad = {s["seed_id"] for s in seeds[:7]}
        store = self.store()
        for s in seeds[:7]:
            store.add(error(s, "ChimeraError: worker request: the same every time"))

        def replay(env, s):
            if s["seed_id"] in bad:  # from the caches: at once, and the same error again
                return error(s, "ChimeraError: worker request: the same every time")
            time.sleep(0.2)
            return done(s)
        out = self.go(replay, seeds, {"seeds_parallel": 6})
        self.assertEqual((out["done"], out["errors"], out["stopped"]), (20, 7, None))
        recs = self.store()
        self.assertEqual(sum(1 for r in recs.all() if r["status"] == "error"), 7)  # still stored
        self.assertEqual(self.logged().count("(same error as the last start)"), 7)

    def test_new_errors_still_stop_the_run(self):
        seeds = [seed(k) for k in range(10)]
        store = self.store()
        for s in seeds:
            store.add(error(s, "CallFailed: an earlier error"))

        def other(env, s):
            time.sleep(0.01)
            return error(s, "CallFailed: can't reach Ollama")
        with self.assertRaises(C.StopRequested) as cm:
            self.go(other, seeds, {"seeds_parallel": 1})
        self.assertIn("6 seeds in a row ended in an error", str(cm.exception))
        self.assertNotIn("same error", self.logged())


class EarlyStopTests(RunTasksCase):
    """A7: the early stop is checked once per data folder."""

    SIZE = {"seeds_parallel": 1, "early_stop": {"after": 3, "min_kept": 0.5}}

    def early(self):
        return C.read_json(os.path.join(self.data, R.EARLY_FILE))

    def test_a_step_kept_only_as_a_dependency_doesnt_count(self):
        """A soft keep (task.SOFT_REASONS: no_example) feeds the later steps but gives no example, so the early stop's
        share and the progress line don't count it as kept."""
        rec = done(seed(1), kept=2, tried=3)
        rec["rounds"][0]["steps"][1]["no_example"] = ["dep_claimed:s1"]
        self.assertEqual(R.kept_share([rec]), (1, 3, 1))
        self.assertEqual(R._summary(rec), "1/3 steps kept (1 more only as a dependency), 1 round(s)")
        self.assertEqual(R._summary(done(seed(2), kept=1, tried=2)), "1/2 steps kept, 1 round(s)")

    def test_once_it_has_passed_it_is_never_checked_again(self):
        seeds = [seed(k) for k in range(8)]

        def kept_first(env, s):
            time.sleep(0.01)
            return done(s, kept=1 if int(s["seed_id"].split("-")[2]) < 3 else 0)
        out = self.go(kept_first, seeds, self.SIZE)  # 3 of 3 at the check, 3 of 8 at the end: no stop
        self.assertEqual((out["done"], out["stopped"]), (8, None))
        self.assertEqual({k: self.early()[k] for k in ("early_stop", "seeds", "tried", "kept")},
                         {"early_stop": "passed", "seeds": 3, "tried": 3, "kept": 3})
        more = [seed(k) for k in range(8, 12)]
        out = self.go(lambda env, s: done(s, kept=0), seeds + more, self.SIZE)  # a later start
        self.assertEqual((out["done"], out["skipped"]), (4, 8))

    def test_a_failed_check_holds_until_no_early_stop(self):
        seeds = [seed(k) for k in range(8)]

        def nothing(env, s):
            time.sleep(0.01)
            return done(s, kept=0)
        with self.assertRaises(C.StopRequested) as cm:
            self.go(nothing, seeds, self.SIZE)
        self.assertIn("early stop: after 3 seeds only 0 of 3", str(cm.exception))
        self.assertIsNone(self.early())
        with self.assertRaises(C.StopRequested):  # the next start stops again
            self.go(nothing, seeds, self.SIZE)
        out = self.go(nothing, seeds, self.SIZE, early_stop=False)  # --no-early-stop
        self.assertIsNone(out["stopped"])
        self.assertEqual(self.early()["early_stop"], "off")
        out = self.go(nothing, seeds + [seed(9)], self.SIZE)  # and later starts don't check again
        self.assertEqual((out["done"], out["stopped"]), (1, None))


class RecordFingerprintTests(RunTasksCase):
    """A4: every record carries env's fingerprint, and a finished record with another one is made again."""

    def test_records_carry_it_and_old_ones_are_made_again(self):
        seeds = [seed(k) for k in range(4)]
        out = self.go(lambda env, s: done(s), seeds[:2], {"seeds_parallel": 2}, env=Env("old"))
        self.assertEqual({r["fingerprint"] for r in self.store().all()}, {"old"})
        made = []

        def again(env, s):
            made.append(s["seed_id"])
            return done(s)
        out = self.go(again, seeds, {"seeds_parallel": 2}, env=Env("new"))
        self.assertEqual((out["done"], out["skipped"]), (4, 0))
        self.assertEqual(sorted(made), sorted(s["seed_id"] for s in seeds))
        self.assertEqual({r["fingerprint"] for r in self.store().all()}, {"new"})
        out = self.go(again, seeds, {"seeds_parallel": 2}, env=Env("new"))
        self.assertEqual((out["done"], out["skipped"]), (0, 4))
        out = self.go(again, seeds, {"seeds_parallel": 2})  # no fingerprint known: finished is finished
        self.assertEqual((out["done"], out["skipped"]), (0, 4))


class RecordFormatTests(RunTasksCase):
    """K9: every record carries the data generator's DATAGEN_FORMAT, and a finished record of another (the first
    smoke run's carry none: format 1) is made again, as one of another fingerprint is."""

    def test_records_carry_it_and_older_ones_are_made_again(self):
        seeds = [seed(k) for k in range(3)]
        store = self.store()
        store.add(done(seeds[0]))  # the first smoke run's: no format
        store.add(dict(done(seeds[1]), format=1))
        store.add(dict(done(seeds[2]), format=R.DATAGEN_FORMAT))
        made = []

        def again(env, s):
            made.append(s["seed_id"])
            return done(s)
        out = self.go(again, seeds, {"seeds_parallel": 2}, env=Env(None))
        self.assertEqual((out["done"], out["skipped"]), (2, 1))
        self.assertEqual(sorted(made), [seeds[0]["seed_id"], seeds[1]["seed_id"]])
        self.assertEqual([r["format"] for r in self.store().all()], [R.DATAGEN_FORMAT] * 3)
        self.assertEqual((R.DATAGEN_FORMAT, T.DATAGEN_FORMAT), (6, 6))
        out = self.go(again, seeds, {"seeds_parallel": 2}, env=Env(None))
        self.assertEqual((out["done"], out["skipped"]), (0, 3))
        self.assertEqual(R.other_formats([done(seeds[0]), dict(done(seeds[1]), format=3),
                                          dict(error(seeds[2], "CallFailed: gone"), format=1)]), [1, 3])
        # the second to the fifth smoke runs' records (formats 2 to 5) are another format's now
        self.assertEqual(R.other_formats([dict(done(seeds[0]), format=2), dict(done(seeds[1]), format=3),
                                          dict(done(seeds[2]), format=4), dict(done(seeds[0]), format=5)]),
                         [2, 3, 4, 5])
        self.assertEqual(R.other_formats([dict(done(seeds[0]), format=6)]), [])


# ---------------------------------------------------------------- the fingerprint, the sheets, the canary

class StandInChimera:
    """The requests fingerprint() asks for, from a table a test can change; and names sheets by Blender path."""

    def __init__(self):
        self.worker = "worker {index}"
        self.repair = "repair"
        self.round2 = "round 2"
        self.plan = "plan"
        self.review = "review"
        self.failed = "failed"
        self.sheets = {}
        self.asked = []

    def worker_request(self, plan, index, outputs, *, goal="", names="", names_gate=True, piece=None, crash=None,
                       prev_result=None, critique="", **kw):
        self.asked.append(("worker", plan["kind"], index, sorted(outputs), names, names_gate))
        text = self.worker.format(index=index) + goal
        if any(d not in outputs for d in plan["steps"][index]["depends_on"]):
            text += self.failed
        if crash is not None:
            text += self.repair + piece + crash["error"] + crash["runner"]
        elif prev_result is not None:
            text += self.round2 + prev_result + critique
        return {"messages": [{"role": "user", "content": text}]}

    def plan_request(self, goal, *, prior="", critique="", **kw):
        return {"messages": [{"role": "user", "content": self.plan + goal + (self.round2 + prior + critique
                                                                             if prior else "")}]}

    def review_request(self, goal, result):
        return {"messages": [{"role": "user", "content": self.review + goal + result}]}

    def blender_names(self, path, scratch):
        self.asked.append(("names", path))
        return self.sheets[path]


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="fingerprint-", dir=_tmp)
        self.addCleanup(shutil.rmtree, self.data, True)

    def test_it_follows_every_request_and_the_sheets(self):
        ch = StandInChimera()
        names = {"5.2.2": "sheet a", "5.0.1": "sheet b"}
        base = R.fingerprint(ch, names)
        self.assertEqual(R.fingerprint(ch, dict(reversed(list(names.items())))), base)
        workers = [a for a in ch.asked if a[0] == "worker"]
        # every step, then the last step with its dependency failed, its repair (not for writing) and round 2
        two = lambda kind, repair=True: [(kind, 0, []), (kind, 1, ["s1"]), (kind, 1, [])] + \
            [(kind, 1, ["s1"])] * (2 if repair else 1)
        self.assertEqual([a[1:4] for a in workers], (two("blender") + two("code") + two("code") +
                                                     two("writing", repair=False) + [("writing", 0, [])] * 2) * 2)
        self.assertEqual(len(R.FP_PLANS), 5)
        self.assertTrue(all(a[4] == R.FP_NAMES and a[5] is True for a in workers))
        seen = {base}
        for what, value in (("worker", "worker {index}!"), ("repair", "repair!"), ("round2", "round 2!"),
                            ("plan", "plan!"), ("review", "review!"), ("failed", "failed!")):
            old = getattr(ch, what)
            setattr(ch, what, value)
            seen.add(R.fingerprint(ch, names))
            setattr(ch, what, old)
        seen.add(R.fingerprint(ch, dict(names, **{"5.0.1": "sheet b, printed by an updated Blender"})))
        self.assertEqual(len(seen), 8)
        self.assertEqual(R.fingerprint(ch, names), base)

    def test_the_names_sheets_are_printed_again_every_start(self):
        ch = StandInChimera()
        ch.sheets = {"/b/5.2.2": "new sheet 5.2.2", "/b/5.0.1": "new sheet 5.0.1"}
        f = os.path.join(self.data, "names", "5.2.2.txt")
        os.makedirs(os.path.dirname(f))
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("a stale sheet from an older Chimera\n")
        got = R.names_sheets(ch, {"5.2.2": "/b/5.2.2", "5.0.1": "/b/5.0.1"}, self.data, _tmp)
        self.assertEqual(got, {"5.2.2": "new sheet 5.2.2", "5.0.1": "new sheet 5.0.1"})
        self.assertEqual([a for a in ch.asked if a[0] == "names"], [("names", "/b/5.2.2"), ("names", "/b/5.0.1")])
        for v in ("5.2.2", "5.0.1"):
            with open(os.path.join(self.data, "names", v + ".txt"), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), f"new sheet {v}\n")
        self.assertEqual(sorted(os.listdir(os.path.join(self.data, "names"))), ["5.0.1.txt", "5.2.2.txt"])

    def test_the_last_tasks_start_decides(self):
        store = C.Store(os.path.join(self.data, "tasks.jsonl"))
        self.assertIsNone(R.changed_requests(self.data, store, "fp1"))  # no records yet
        store.add(dict(done(seed(1)), fingerprint="fp1"))
        self.assertIn("not recorded", R.changed_requests(self.data, store, "fp1"))  # records, but no start says
        C.run_record(self.data, stages=["seeds"], fingerprint=None)
        C.run_record(self.data, stages=["tasks"], fingerprint="fp1")
        C.run_record(self.data, stages=["build", "report"], fingerprint="fp2")  # a build-only start doesn't count
        self.assertEqual(R.last_fingerprint(self.data), "fp1")
        self.assertIsNone(R.changed_requests(self.data, store, "fp1"))
        why = R.changed_requests(self.data, store, "fp2")
        self.assertIn("fingerprint fp1 then, fp2 now): 1 of the 1 seeds", why)
        self.assertIn("--new-binary-ok", why)


class SandboxCanaryTests(unittest.TestCase):
    """G10: a python3 that can't start in the sandbox stops the run before any Python run is cached."""

    def test_the_canary_runs(self):
        self.assertIsNone(R.sandbox_canary(_tmp))

    def test_an_interpreter_that_cant_start(self):
        shim = {"exit": 71, "output": "xcrun: error: couldn't spawn xcodebuild", "timed_out": False,
                "seconds": 0.1, "sandboxed": True, "cut": 0}
        with mock.patch.object(pysandbox, "run", return_value=shim):
            why = R.sandbox_canary(_tmp)
        self.assertIn("exit 71, xcrun: error: couldn't spawn xcodebuild", why)
        self.assertIn("python3 doesn't run in the sandbox", why)
        echoed = dict(shim, exit=1, output=f"  File \"canary.py\", line 2\n    print({R.CANARY!r})\nSyntaxError: x")
        with mock.patch.object(pysandbox, "run", return_value=echoed):
            self.assertIsNotNone(R.sandbox_canary(_tmp))


# ---------------------------------------------------------------- main

@unittest.skipUnless(F.HAVE_CHIMERA and HAVE_BLENDER, "needs Go (or CHIMERA_BIN) and Blender " +
                     " and ".join(blenders.VERSIONS))
class MainTests(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="main-", dir=_tmp)
        self.addCleanup(shutil.rmtree, self.data, True)
        self.seeds = [seed(1), seed(2, "blender")]
        C.write_jsonl(os.path.join(self.data, "seeds.jsonl"), self.seeds)
        self.envs = []

    def main(self, *more, index=None, run_seed=None):
        argv = ["--size", "tiny", "--data-dir", self.data, "--host", _fake.url, "--chimera", _bin] + list(more)

        def stand_in(env, s):
            self.envs.append(env)
            return (run_seed or done)(s)
        err = io.StringIO()
        with mock.patch.object(T, "run_seed", side_effect=stand_in), contextlib.redirect_stderr(err):
            code = R.main(argv, index=index, gate=GATE)
        self.err = err.getvalue()
        return code

    def records(self):
        """Each seed's record (a later line replaces an earlier one), in the order their seeds first came."""
        return C.Store(os.path.join(self.data, "tasks.jsonl")).all()

    def current(self):
        """The fingerprint this binary and these Blenders give, worked out here."""
        ch = Chimera(_bin, env={"OLLAMA_HOST": _fake.url})
        return R.fingerprint(ch, {v: ch.blender_names(p, _tmp) for v, p in blenders.VERSIONS.items()})

    def test_the_env_has_the_runs_index_and_the_fingerprint(self):
        stale = os.path.join(self.data, "names", "5.2.2.txt")
        os.makedirs(os.path.dirname(stale))
        with open(stale, "w", encoding="utf-8") as f:
            f.write("a stale sheet\n")
        index = object()
        self.assertEqual(self.main("--stages", "tasks", index=index), 0)
        fp = self.current()
        self.assertTrue(self.envs and all(e.eval_index is index and e.fingerprint == fp for e in self.envs))
        self.assertEqual([r["fingerprint"] for r in self.records()], [fp, fp])
        self.assertEqual(C.read_json(os.path.join(self.data, "RUN.json"))["fingerprint"], fp)
        with open(stale, encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), self.envs[0].names["5.2.2"])
        self.envs.clear()
        self.assertEqual(self.main("--stages", "tasks"), 0)
        self.assertEqual(self.envs, [])  # finished seeds are skipped
        os.remove(os.path.join(self.data, "tasks.jsonl"))
        self.assertEqual(self.main("--stages", "tasks"), 0)
        self.assertIsInstance(self.envs[0].eval_index, EvalIndex)  # the real one when main is given none

    def test_changed_requests_stop_a_start_until_new_binary_ok(self):
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [dict(done(self.seeds[0]), fingerprint="old")])
        C.run_record(self.data, stages=["seeds", "tasks", "build", "report"], fingerprint="old")
        before = C.read_json(os.path.join(self.data, "RUN.json"))
        self.assertEqual(self.main("--stages", "tasks"), 2)
        self.assertIn("Chimera's requests have changed since the last start here (fingerprint old then", self.err)
        self.assertIn("1 of the 1 seeds", self.err)
        self.assertEqual(self.envs, [])
        self.assertEqual(C.read_json(os.path.join(self.data, "RUN.json")), before)  # a refused start isn't one
        self.assertEqual(self.main("--stages", "tasks"), 2)  # and stays refused
        self.assertEqual(self.main("--stages", "tasks", "--new-binary-ok"), 0)
        self.assertEqual(len(self.envs), 2)  # the old record's seed is made again, with the other
        fp = self.envs[0].fingerprint
        self.assertEqual({r["fingerprint"] for r in self.records()}, {fp})
        self.envs.clear()
        self.assertEqual(self.main("--stages", "tasks"), 0)  # the decision holds for later starts
        self.assertEqual(self.envs, [])

    def test_seeds_that_ended_in_an_error_exit_4_after_build_and_report(self):
        ran = []

        def build(data, size=None, keep_plan_failed=False, **kw):
            ran.append(("build", kw))
            return {"train": 0, "valid": 0, "dropped": {}}

        def report(data):
            ran.append(("report", None))
            return {}
        flaky = lambda s: error(s, "CallFailed: gone") if s["category"] == "blender" else done(s)  # noqa: E731
        with mock.patch.object(B, "build", side_effect=build), mock.patch.object(RP, "report", side_effect=report):
            self.assertEqual(self.main("--stages", "tasks,build,report", "--keep-untested", run_seed=flaky),
                             R.ERRORED)
            self.assertEqual([r[0] for r in ran], ["build", "report"])
            self.assertIn("Every stage ran, but 1 seed(s) ended in an error", self.err)
            self.assertNotIn("All done", self.err)
            self.assertEqual(ran[0][1]["fingerprint"], self.envs[0].fingerprint)
            self.assertIs(ran[0][1]["keep_untested"], True)
            ran.clear()
            self.assertEqual(self.main("--stages", "tasks,build,report"), 0)  # the error seed runs again, and works
            self.assertIs(ran[0][1]["keep_untested"], False)
        self.assertIn("All done", self.err)

    def test_a_build_only_start_takes_the_fingerprint_too(self):
        got = []
        with mock.patch.object(B, "build", side_effect=lambda *a, **kw: got.append(kw) or {}):
            self.assertEqual(self.main("--stages", "build"), 0)
        self.assertEqual(got[0]["fingerprint"], self.current())
        self.assertIsInstance(got[0]["index"], EvalIndex)
        self.assertEqual(C.read_json(os.path.join(self.data, "RUN.json"))["fingerprint"], self.current())

    def test_a_build_only_start_refuses_records_of_other_requests(self):
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [dict(done(self.seeds[0]), fingerprint="old"),
                                                                dict(done(self.seeds[1]), fingerprint=self.current())])
        got = []
        with mock.patch.object(B, "build", side_effect=lambda *a, **kw: got.append(kw) or {}):
            self.assertEqual(self.main("--stages", "build,report"), 2)
            self.assertIn("1 seeds in tasks.jsonl were made with requests this Chimera doesn't send", self.err)
            self.assertEqual(got, [])
            self.assertFalse(os.path.exists(os.path.join(self.data, "RUN.json")))  # a refused start isn't one
            self.assertEqual(self.main("--stages", "build", "--new-binary-ok"), 0)
        self.assertEqual(len(got), 1)

    def test_records_of_another_data_generator(self):
        """A tasks start says how many finished seeds an older data generator made and makes them again; a build-only
        start refuses them (the build would drop them all as old_format and replace sft/) until --new-binary-ok."""
        fp = self.current()
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"),
                      [dict(done(self.seeds[0]), fingerprint=fp),
                       dict(done(self.seeds[1]), fingerprint=fp, format=T.DATAGEN_FORMAT)])
        C.run_record(self.data, stages=["seeds", "tasks"], fingerprint=fp)
        got = []
        with mock.patch.object(B, "build", side_effect=lambda *a, **kw: got.append(kw) or {}):
            self.assertEqual(self.main("--stages", "build,report"), 2)
            self.assertIn("1 finished seeds in tasks.jsonl were made by another version of the data generator "
                          f"(format 1, {T.DATAGEN_FORMAT} now), so the build would drop their examples (old_format)",
                          self.err)
            self.assertEqual(got, [])
            self.assertEqual(self.main("--stages", "build", "--new-binary-ok"), 0)
            self.assertEqual(len(got), 1)
        self.assertEqual(self.main("--stages", "tasks"), 0)
        self.assertIn("1 finished seeds in tasks.jsonl were made by another version of the data generator (format 1, "
                      f"{T.DATAGEN_FORMAT} now): they are made again.", self.err)
        self.assertEqual(len(self.envs), 1)  # only the older one's seed
        self.assertEqual([r.get("format") for r in self.records()], [T.DATAGEN_FORMAT] * 2)
        with mock.patch.object(B, "build", side_effect=lambda *a, **kw: got.append(kw) or {}):
            self.assertEqual(self.main("--stages", "build"), 0)  # nothing of another format left to refuse
        self.assertEqual(len(got), 2)

    def test_python_that_cant_start_in_the_sandbox_is_exit_2(self):
        shim = {"exit": 71, "output": "xcrun: error: couldn't spawn xcodebuild", "timed_out": False,
                "seconds": 0.1, "sandboxed": True, "cut": 0}
        with mock.patch.object(pysandbox, "run", return_value=shim):
            self.assertEqual(self.main("--stages", "tasks"), 2)
        self.assertIn("python3 doesn't run in the sandbox", self.err)
        self.assertEqual(self.envs, [])
        self.assertFalse(os.path.exists(os.path.join(self.data, "tasks.jsonl")))


@unittest.skipUnless(F.HAVE_CHIMERA and HAVE_BLENDER, "needs Go (or CHIMERA_BIN) and Blender " +
                     " and ".join(blenders.VERSIONS))
class ValuesRunTests(unittest.TestCase):
    """A tiny run for real, format 6 (since the fifth smoke): main's tasks stage on three values-step seeds of the
    stand-in (datagen_fakes' values pair), through the binary's own requests and real Blender 5.2.2 and 5.0.1, then
    the build (FixtureIndex lets the marked fixtures through to its filters; check=False, as the last check would flag
    every line by the mark) and the report. told: gpt-oss writes ctx["variables"] until its notes carry the ctx tell,
    then ctx["values"]; stubborn: every try on every model writes ctx["variables"] (STUBBORN_CTX), and s2 depends on
    it; lone: the same stubborn step with nothing depending on it. tiny's variants run as it draws them; its round 2
    is left out (round2 0.0 here), which would only run the same steps again, slower, after the result check."""

    PLANS = {"told": F.VALUES_PLAN, "stubborn": F.VALUES_STUBBORN_PLAN, "lone": F.VALUES_LONE_PLAN}

    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.mkdtemp(prefix="values-run-", dir=_tmp)
        cls.goals = {name: f"Please make the {name} lamp for this test. {MARK}" for name in cls.PLANS}
        seeds = [dict(seed(k, "blender"), text=cls.goals[name]) for k, name in enumerate(cls.PLANS, 31)]
        C.write_jsonl(os.path.join(cls.data, "seeds.jsonl"), seeds)
        _fake.plans.update({cls.goals[name]: plan for name, plan in cls.PLANS.items()})
        cls.index = F.FixtureIndex(EvalIndex(8))
        F.STUBBORN_CTX.add(F.STUBBORN_VALUES_STEP["title"])
        err = io.StringIO()
        try:
            with mock.patch.dict(sizes.SIZES["tiny"], {"round2": 0.0}), contextlib.redirect_stderr(err):
                cls.exit = R.main(["--size", "tiny", "--data-dir", cls.data, "--host", _fake.url, "--chimera", _bin,
                                   "--stages", "tasks"], index=cls.index, gate=GATE)
        finally:
            F.STUBBORN_CTX.discard(F.STUBBORN_VALUES_STEP["title"])
        cls.err = err.getvalue()
        recs = C.Store(os.path.join(cls.data, "tasks.jsonl")).all()
        cls.recs = {name: next(r for r in recs if r["seed"]["text"] == cls.goals[name]) for name in cls.PLANS}
        cls.fp = C.read_json(os.path.join(cls.data, "RUN.json"))["fingerprint"]
        cls.names = {}
        for v in blenders.VERSIONS:
            with open(os.path.join(cls.data, "names", v + ".txt"), encoding="utf-8") as f:
                cls.names[v] = f.read().strip()
        cls.stats = B.build(cls.data, sizes.get("tiny"), index=cls.index, check=False, fingerprint=cls.fp)
        cls.examples = list(zip(C.read_jsonl(os.path.join(cls.data, "sft", "train.jsonl")) +
                                C.read_jsonl(os.path.join(cls.data, "sft", "valid.jsonl")),
                                C.read_jsonl(os.path.join(cls.data, "sft", "train.meta.jsonl")) +
                                C.read_jsonl(os.path.join(cls.data, "sft", "valid.meta.jsonl"))))
        cls.rep = RP.report(cls.data)

    @classmethod
    def tearDownClass(cls):
        for goal in cls.goals.values():
            _fake.plans.pop(goal, None)

    def steps(self, name):
        return {s["sid"]: s for s in self.recs[name]["rounds"][0]["steps"]}

    def bodies(self, name, sid):
        """The system messages of the worker calls the stand-in got for a seed's step (its plan's title and the step's
        line say which): the teacher's copies."""
        head = f"Project: {self.PLANS[name]['title']}\n"
        return [b["messages"][0]["content"] for b in _fake.bodies("worker")
                if head in b["messages"][0]["content"]
                and re.search(rf"^Your step, {sid}:", b["messages"][-1]["content"], re.M)]

    def stored(self):
        """(plan, goal, item) for every stored request of the three seeds: steps, variants, repairs."""
        for name, rec in self.recs.items():
            for rnd in rec["rounds"]:
                for st in rnd["steps"] + rnd["variants"]:
                    if st.get("request"):
                        for item in [st] + st["repairs"]:
                            yield rnd["plan"], self.goals[name], item

    def teacher_text(self, text):
        """The teacher-only wording text holds: the notes' head, the values note's fixed parts, a ctx tell run, or
        anything else hints.echoed_note knows as ours."""
        return [x for x in (H.HEAD,) + H.VALUES_FORMS + F.CTX_FORMS if x in text] + \
            [n for n in (H.echoed_note(text),) if n]

    def test_the_run_is_format_6(self):
        self.assertEqual(self.exit, 0, self.err[-2000:])
        self.assertEqual((R.DATAGEN_FORMAT, T.DATAGEN_FORMAT), (6, 6))
        for rec in self.recs.values():
            self.assertEqual((rec["status"], rec["format"], rec["fingerprint"]), ("done", 6, self.fp))
            self.assertEqual(len(rec["rounds"]), 1)
        self.assertEqual(R.other_formats(self.recs.values()), [])

    def test_every_stored_request_is_the_binarys_with_no_teacher_text(self):
        n = 0
        for plan, goal, item in self.stored():
            got = F.binary_request(_bin, plan, goal, item["inputs"], self.names)
            self.assertEqual(json.dumps(item["request"]["messages"], ensure_ascii=False),
                             json.dumps(got["messages"], ensure_ascii=False))
            self.assertEqual(item["request"]["need_ctx"], got["need_ctx"])
            self.assertEqual(self.teacher_text("\n".join(m["content"] for m in item["request"]["messages"])), [])
            n += 1
        self.assertGreaterEqual(n, 6)
        # the values steps' requests carry the contract's ctx["values"] rule and its guard: Chimera's own words
        for name in ("told", "stubborn", "lone"):
            system = self.steps(name)["s1"]["request"]["messages"][0]["content"]
            self.assertIn(CT.fill(CT.MODE_BLENDER, sid="s1"), system)
            self.assertIn('"objects": {}, "values": {}})', system)

    def test_the_values_note_is_in_the_teachers_copies_only(self):
        note = H.VALUES_NOTE.format(sid="s1")
        for name in ("told", "stubborn"):  # a values step with a dependent: every try's copy has it
            copies = self.bodies(name, "s1")
            self.assertEqual(len(copies), len(self.steps(name)["s1"]["candidates"]))
            self.assertTrue(all(note in c.split(H.HEAD, 1)[1] for c in copies), name)
            self.assertFalse(any(note in c for c in self.bodies(name, "s2")), name)
        self.assertTrue(self.bodies("lone", "s1"))
        self.assertFalse(any(note in c for c in self.bodies("lone", "s1")))  # nothing depends on it: no note
        for _, _, item in self.stored():
            self.assertNotIn(note, json.dumps(item["request"], ensure_ascii=False))

    def test_the_told_values_step_passes(self):
        s1, s2 = self.steps("told")["s1"], self.steps("told")["s2"]
        first, told = s1["candidates"][:2], s1["candidates"][2:]
        self.assertTrue(all(c["reasons"] == ["ctx_channel"] for c in first), [c["reasons"] for c in first])
        self.assertEqual(first[0]["gate"]["ctx_channel"], {"written": ["variables"], "read": []})
        tell = first[0]["gate"]["ctx_tell"]
        self.assertTrue(tell.startswith("Chimera's ctx has only \"scene\", \"collection\", \"objects\" and "
                                        "\"values\", not ctx[\"variables\"]: "), tell)
        copies = self.bodies("told", "s1")
        self.assertFalse(any(tell in c for c in copies[:2]))
        self.assertTrue(copies[2:] and all(tell in c for c in copies[2:]))  # the told batch heard it
        self.assertEqual((s1["kept"], s1.get("no_example")), ({"from": "cand", "index": 2}, None))
        self.assertEqual(told[0]["content"], F.VALUES_OK)
        guard = 'build_s1({"scene": bpy.context.scene, "collection": bpy.context.scene.collection, "objects": {}, ' \
                '"values": {}})'
        self.assertIn(guard, CT.fill(CT.MODE_BLENDER, sid="s1"))  # the contract's guard, as the fake writes it
        self.assertIn(guard, F.VALUES_OK)
        self.assertNotIn("ctx_channel", told[0]["gate"])
        self.assertEqual(told[0]["gate"]["scene"]["ctx_values"], ["lamp_height"])  # handed on, the run says
        self.assertEqual(told[0]["gate"]["provides_missing"], [])
        self.assertTrue(s2["kept"] and not s2.get("no_example"))
        c = s2["candidates"][s2["kept"]["index"]]
        self.assertEqual((c["gate"]["stand_in"], c["gate"]["seams"]), (False, []))
        self.assertEqual(s2["inputs"]["outputs"]["s1"], F.VALUES_OK)
        # both reach the training file, their targets free of teacher text
        kept = {(m["sid"], m["variant"]): ex for ex, m in self.examples if m["seed_id"] == self.recs["told"]["key"]}
        self.assertIn(("s1", None), kept)
        self.assertIn(("s2", None), kept)
        self.assertEqual(kept[("s1", None)]["messages"][-1]["content"], F.VALUES_OK)
        self.assertEqual(kept[("s1", None)]["messages"][:-1], s1["request"]["messages"])

    def test_a_stubborn_values_step_is_kept_only_with_a_dependent(self):
        s1, s2 = self.steps("stubborn")["s1"], self.steps("stubborn")["s2"]
        self.assertEqual([c["model"] for c in s1["candidates"]], [F.TEACHER] * 4 + [F.SECOND] * 2)
        self.assertTrue(all(c["reasons"] == ["ctx_channel"] for c in s1["candidates"]))
        self.assertTrue(s1["kept"])
        self.assertEqual(s1["no_example"], ["ctx_channel"])
        # its reader finds no lamp_height: Chimera's own join says so (ctx_key_missing), and the step is dropped
        self.assertIsNone(s2["kept"])
        self.assertEqual(s2["drop"], ["seam:ctx_key_missing"])
        lone = self.steps("lone")
        self.assertIsNone(lone["s1"]["kept"])
        self.assertEqual(lone["s1"]["drop"], ["ctx_channel"])
        self.assertTrue(all(c["reasons"] == ["ctx_channel"] for c in lone["s1"]["candidates"]))
        self.assertTrue(lone["s2"]["kept"])
        mine = {(m["seed_id"], m["sid"]) for _, m in self.examples}
        self.assertNotIn((self.recs["stubborn"]["key"], "s1"), mine)
        self.assertIn((self.recs["lone"]["key"], "s2"), mine)

    def test_the_build_keeps_no_teacher_text_and_its_backstop_fires_on_none(self):
        st = self.stats
        self.assertEqual(st["dropped"].get("no_example"), 1)  # the stubborn soft keep
        self.assertNotIn("old_format", st["dropped"])
        self.assertNotIn("old_fingerprint", st["dropped"])
        self.assertNotIn("ctx_channel", st["facts"])  # the gate got there first on every try (since format 4)
        self.assertNotIn("teacher_note", st["dropped"])
        self.assertGreaterEqual(len(self.examples), 3)
        for ex, m in self.examples:
            self.assertEqual(m["format"], 6)
            self.assertEqual(self.teacher_text(ex["messages"][-1]["content"]), [], m)
            self.assertEqual(BG.ctx_channel(T.piece_code(ex["messages"][-1]["content"])), [], m)

    def test_the_report_counts_the_values_steps(self):
        a = self.rep["after_audit"]
        self.assertEqual(a["ctx_channel"], {"used": {"tries": 2 + 6, "kept": 1, "dependency only": 1},
                                            "unused": {"tries": 6, "dropped": 1}})
        self.assertEqual(a["gates"]["ctx_channel"], {"blender": 14})
        self.assertEqual(a["soft_keeps"], {"ctx_channel": {"used": 1}})
        self.assertEqual(a["no_example_why"], {"ctx_channel": 1})
        self.assertEqual(a["values_steps"], {"steps": 2, "kept": 1, "dependency only": 1, "writes_values": 1,
                                             "hands_on": 1})
        with open(os.path.join(self.data, RP.REPORT_FILE), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("ctx_channel (a ctx key Chimera's join doesn't make; a gate since format 4): on steps a later "
                      "step depends on (soft there), 8 tries of 2 steps (dependency only 1, kept 1); on the others, "
                      "variants among them (hard), 6 tries of 1 step (dropped 1).", text)
        self.assertIn("Values-only steps (hints.values_step: their notes carry the values note): 2 (dependency only "
                      "1, kept 1); of their kept pieces, 1 write ctx[\"values\"] and 1 handed ctx[\"values\"] keys on "
                      "when run alone.", text)


class FinishedSmokeTests(unittest.TestCase):
    """main in data/gen/smoke/ (DATA_ROOT points at a scratch root here) or a folder given as --data-dir: a finished
    run there that another data generator format made, the first two smoke runs', is never touched unless
    --new-binary-ok; the refusal comes before Ollama, the binary or a Blender is asked for, and writes nothing there."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="smoke-root-", dir=_tmp)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.data = os.path.join(self.root, "smoke")
        os.makedirs(self.data)
        self.seeds = [seed(1), seed(2, "blender")]
        C.write_jsonl(os.path.join(self.data, "seeds.jsonl"), self.seeds)

    def finished(self, fmt=None, last_error=False):
        """The folder of a smoke run that has finished (fixtures): REPORT.md and every seed done, an error line of the
        second seed before its finished one (a seed's last line wins), or after it (last_error: not finished); fmt
        None is the first smoke's, whose records carry none."""
        recs = [done(self.seeds[0]), error(self.seeds[1], "CallFailed: gone " + MARK), done(self.seeds[1])]
        if last_error:
            recs.append(error(self.seeds[1], "CallFailed: gone again " + MARK))
        if fmt is not None:
            recs = [dict(r, format=fmt) for r in recs]
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), recs)
        with open(os.path.join(self.data, "REPORT.md"), "w", encoding="utf-8") as f:
            f.write("# fixture report\n" + MARK + "\n")

    def snapshot(self):
        out = {}
        for name in sorted(os.listdir(self.data)):
            with open(os.path.join(self.data, name), "rb") as f:
                out[name] = f.read()
        return out

    def main(self, *argv):
        err = io.StringIO()
        with mock.patch.object(R, "DATA_ROOT", self.root), contextlib.redirect_stderr(err), \
                mock.patch.object(RP, "report", return_value={}) as rep:
            code = R.main(["--size", "smoke", "--host", "127.0.0.1:9", "--chimera", "/nowhere/chimera"] + list(argv))
        self.err, self.reported = err.getvalue(), rep.call_count
        return code

    def test_the_first_smokes_folder_is_refused(self):
        self.finished()
        before = self.snapshot()
        for stages in ("seeds,tasks,build,report", "tasks", "build,report", "report"):
            self.assertEqual(self.main("--stages", stages), 2, stages)
            self.assertIn(f"{self.data} holds a run that has finished, made by another version of the data "
                          f"generator (format 1, {T.DATAGEN_FORMAT} now)", self.err)
            self.assertIn("This generator can't rebuild that folder's files", self.err)
            self.assertIn("--data-dir data/gen/smoke6", self.err)  # smoke2-smoke5 hold the second to the fifth
            self.assertNotIn("Ollama", self.err)  # refused before anything is asked for
            self.assertEqual(self.snapshot(), before)  # no RUN.json, no progress.log, tasks.jsonl as it was
            self.assertEqual(self.reported, 0)
        # a finished smoke of format 2 to 5 (the second to the fifth smoke runs') is another format's now too
        for fmt in (2, 3, 4, 5):
            self.finished(fmt)
            self.assertEqual(self.main("--stages", "report"), 2, fmt)
            self.assertIn(f"(format {fmt}, {T.DATAGEN_FORMAT} now)", self.err)
            self.assertIn("--data-dir data/gen/smoke6", self.err)
        self.finished()
        # on purpose: --new-binary-ok goes ahead (here only the report, standing in)
        self.assertEqual(self.main("--stages", "report", "--new-binary-ok"), 0)
        self.assertEqual(self.reported, 1)
        self.assertTrue(os.path.exists(os.path.join(self.data, "RUN.json")))

    def test_a_folder_given_as_data_dir_is_refused_too(self):
        """Re-running the second smoke's own command (--data-dir data/gen/smoke2) after the bump to format 3 made its
        seeds again in place and replaced its sft/ (the integration check's scratch copy): an explicit folder, of any
        size, is refused as the default one is."""
        self.finished(2)
        before = self.snapshot()
        for size in ("smoke", "night"):
            err = io.StringIO()
            with mock.patch.object(RP, "report", return_value={}) as rep, contextlib.redirect_stderr(err):
                self.assertEqual(R.main(["--size", size, "--data-dir", self.data, "--stages", "tasks,build,report",
                                         "--host", "127.0.0.1:9", "--chimera", "/nowhere/chimera"]), 2, size)
            self.assertIn(f"{self.data} holds a run that has finished, made by another version of the data generator "
                          f"(format 2, {T.DATAGEN_FORMAT} now)", err.getvalue())
            self.assertNotIn("Ollama", err.getvalue())
            self.assertEqual((self.snapshot(), rep.call_count), (before, 0))
        with mock.patch.object(RP, "report", return_value={}) as rep, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(R.main(["--size", "smoke", "--data-dir", self.data, "--stages", "report",
                                     "--new-binary-ok"]), 0)  # on purpose
        self.assertEqual(rep.call_count, 1)

    def test_what_isnt_refused(self):
        # a finished run of this format (run_datagen.sh still refuses a smoke's in its default folder), one not
        # finished, one with no report; in the default folder and as --data-dir
        for fmt, last_error, report in ((T.DATAGEN_FORMAT, False, True), (None, True, True), (None, False, False)):
            self.finished(fmt, last_error)
            if not report:
                os.remove(os.path.join(self.data, "REPORT.md"))
            self.assertEqual(self.main("--stages", "report"), 0, (fmt, last_error, report))
            self.assertNotIn("holds a run that has finished", self.err)
            self.assertEqual(self.main("--stages", "report", "--data-dir", self.data), 0, (fmt, last_error, report))
            self.assertNotIn("holds a run that has finished", self.err)
            self.assertIsNone(R.finished_run(self.data))
        self.finished()
        self.assertIsNotNone(R.finished_run(self.data))
        self.finished(T.DATAGEN_FORMAT - 1)
        recs = C.read_jsonl(os.path.join(self.data, "tasks.jsonl"))
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), recs[:-1] + [dict(recs[-1], format=T.DATAGEN_FORMAT)])
        self.assertIsNone(R.finished_run(self.data))  # one seed made again by this format: a run carrying on
        C.write_jsonl(os.path.join(self.data, "seeds.jsonl"), [])  # no seeds chosen: nothing finished
        self.assertIsNone(R.finished_run(self.data))
        self.assertIsNone(R.finished_run(os.path.join(self.root, "smoke3")))  # a new folder


class ScratchDefaultTests(unittest.TestCase):
    def test_a_direct_start_puts_its_run_folders_outside_the_home_folder(self):
        """run.scratch_default: WM_SCRATCH unset gets run_datagen.sh's folder in $TMPDIR (or /tmp), not
        tools/blender_check's data/scratch under /Users, where node can't check a .js file; one that is set stays,
        with a warning when it is under /Users or /Volumes."""
        for tmp, want in (("/private/var/folders/x/T/", "/private/var/folders/x/T"), ("", "/tmp"),
                          ("/Users/someone/T", "/tmp"), ("/Volumes/Disk/T", "/tmp")):
            env = {"TMPDIR": tmp}
            self.assertIsNone(R.scratch_default(env), tmp)
            self.assertEqual(env["WM_SCRATCH"], os.path.join(want, R.SCRATCH_NAME), tmp)
        env = {"WM_SCRATCH": "/Users/someone/chimera/worker-model/data/scratch"}
        self.assertIn("which the sandbox can't read", R.scratch_default(env))
        self.assertEqual(env["WM_SCRATCH"], "/Users/someone/chimera/worker-model/data/scratch")  # kept as given
        env = {"WM_SCRATCH": _tmp}
        self.assertIsNone(R.scratch_default(env))
        self.assertEqual(env, {"WM_SCRATCH": _tmp})


# ---------------------------------------------------------------- run_datagen.sh

STUB_RUN = '''# test fixture, never training data: stands in for datagen.run, records its arguments and WM_SCRATCH
import json, os, sys
with open(os.environ["STUB_ARGS"], "w") as f:
    json.dump(sys.argv[1:], f)
with open(os.environ["STUB_ARGS"] + ".scratch", "w") as f:
    f.write(os.environ.get("WM_SCRATCH", ""))
print("stub datagen.run")
sys.exit(int(os.environ.get("STUB_EXIT", "0")))
'''
STUB_APP = 'package main\n\nimport "fmt"\n\nfunc main() { fmt.Println("chimera stand-in 0.0.0") }\n'


class FakeChimeraUI:
    """Chimera's GET /api/state, on 127.0.0.1 at a free port: {"lending": {"state": state}}, or junk."""

    def __init__(self):
        self.state = "connected"
        self.asked = []
        ui = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                ui.asked.append(self.path)
                body = (b"<html>not Chimera</html>" if ui.state is None
                        else json.dumps({"lending": {"state": ui.state, "running": []}}).encode())
                self.send_response(200 if self.path == "/api/state" else 404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()


def free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(F.GO, "needs Go")
class ScriptTests(unittest.TestCase):
    """run_datagen.sh, copied into root/wm/ beside a root/app/ it can build in a second, with a datagen.run that
    only records what it was given; SKIP_TESTS is set and Ollama is the stand-in."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="script-", dir=_tmp)
        self.addCleanup(shutil.rmtree, self.root, True)
        wm, app = os.path.join(self.root, "wm"), os.path.join(self.root, "app")
        os.makedirs(os.path.join(wm, "datagen"))
        os.makedirs(app)
        shutil.copy(SCRIPT, wm)
        for name, text in (("wm/datagen/__init__.py", ""), ("wm/datagen/run.py", STUB_RUN),
                           ("wm/datagen/task.py", f"# test fixture, never training data\nDATAGEN_FORMAT = "
                                                  f"{T.DATAGEN_FORMAT}\n"),
                           ("app/go.mod", "module chimerastandin\n\ngo 1.21\n"), ("app/main.go", STUB_APP)):
            with open(os.path.join(self.root, name), "w", encoding="utf-8") as f:
                f.write(text)
        self.ui = FakeChimeraUI()
        self.addCleanup(self.ui.stop)
        self.args = os.path.join(self.root, "args.json")

    def run_script(self, *args, ports=None, **env):
        e = {k: v for k, v in os.environ.items() if k not in ("FORCE", "SIZE", "PARALLEL", "WM_SCRATCH")}
        e.update(PATH=os.path.dirname(F.GO) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
                 CHIMERA_UI_PORTS=ports or f"{free_port()} {self.ui.port}", OLLAMA_HOST=_fake.url, SKIP_TESTS="1",
                 STUB_ARGS=self.args, PYTHONDONTWRITEBYTECODE="1")
        e.update(env)
        p = subprocess.run(["/bin/bash", os.path.join(self.root, "wm", "run_datagen.sh")] + list(args), env=e,
                           capture_output=True, text=True, timeout=300)
        return p.returncode, p.stdout + p.stderr

    def ran(self):
        return C.read_json(self.args)

    def test_lending_stops_it_unless_force(self):
        for state in ("connected", "connecting", "draining", "paused"):
            self.ui.state = state
            code, out = self.run_script()
            self.assertEqual(code, 1, out)
            self.assertIn(f'Chimera is lending this Mac to the pool (lending state "{state}", on port '
                          f'{self.ui.port})', out)
            self.assertIn("Disconnected", out)
            self.assertIn("auto-help", out)
            self.assertIn("FORCE=1", out)
            self.assertNotIn("Building Chimera", out)
            self.assertIsNone(self.ran())
        self.assertEqual(set(self.ui.asked), {"/api/state"})
        code, out = self.run_script(FORCE="1")
        self.assertEqual(code, 0, out)
        self.assertIn("FORCE is set: going on anyway", out)
        self.assertIn("Done.", out)
        self.assertIsNotNone(self.ran())

    def test_disconnected_or_no_chimera_goes_on(self):
        for state, ports in (("disconnected", None), (None, None), ("connected", str(free_port()))):
            self.ui.state = state
            if os.path.exists(self.args):
                os.remove(self.args)
            code, out = self.run_script(ports=ports)
            self.assertEqual(code, 0, out)
            self.assertNotIn("lending", out)
            self.assertIn("Done.", out)
            self.assertIsNotNone(self.ran())

    def smoke_folder(self, finished=True, name="data/gen/smoke", fmt=None):
        """A smoke run's folder in the copy's tree (fixtures): two seeds, one finished, the other finished too or
        ended in an error, and its REPORT.md; fmt the records' format (None: the first smoke's, which carry none)."""
        d = os.path.join(self.root, "wm", name)
        os.makedirs(d, exist_ok=True)
        seeds = [seed(1), seed(2)]
        C.write_jsonl(os.path.join(d, "seeds.jsonl"), seeds)
        recs = [error(seeds[1], "CallFailed: gone"), done(seeds[0])] + ([done(seeds[1])] if finished else [])
        C.write_jsonl(os.path.join(d, "tasks.jsonl"), [dict(r, format=fmt) if fmt else r for r in recs])
        with open(os.path.join(d, "REPORT.md"), "w", encoding="utf-8") as f:
            f.write("# fixture report\n" + MARK + "\n")
        return d

    def test_a_finished_smoke_isnt_run_again_in_its_folder(self):
        self.ui.state = "disconnected"
        d = self.smoke_folder()
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        self.assertIn("data/gen/smoke/ holds a smoke run that has finished", out)
        self.assertIn("--data-dir data/gen/smoke6", out)  # data/gen/smoke2-smoke5 hold the second to the fifth
        self.assertNotIn("--stages build,report", out)  # that command replaced the first smoke's sft/ with nothing
        self.assertIn("copy its folder and build the copy with its own --data-dir", out)
        self.assertIn("can't be rebuilt: the build drops its records as old_format", out)
        self.assertNotIn("Building Chimera", out)
        self.assertIsNone(self.ran())
        self.assertFalse(os.path.exists(os.path.join(d, "run.log")))
        # its own folder: the run goes on, and its log is there
        code, out = self.run_script("--data-dir", "data/gen/smoke6", "--limit", "8")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.ran()[-4:], ["--data-dir", "data/gen/smoke6", "--limit", "8"])
        self.assertIn("into data/gen/smoke6/ (log: data/gen/smoke6/run.log)", out)
        self.assertIn("Done. Report: data/gen/smoke6/REPORT.md", out)
        with open(os.path.join(self.root, "wm", "data", "gen", "smoke6", "run.log"), encoding="utf-8") as f:
            self.assertIn("stub datagen.run", f.read())
        code, out = self.run_script("--data-dir=data/gen/smoke7")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(os.path.join(self.root, "wm", "data", "gen", "smoke7", "run.log")))
        code, out = self.run_script(SIZE="night")  # another size's folder
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.root, "wm", "data", "gen", "smoke.log")))

    def test_a_finished_run_of_another_format_isnt_run_again_in_any_folder(self):
        """--data-dir data/gen/smoke2 (the second smoke run's own command): refused before the build, the tests or a
        log in that folder, as datagen.run would refuse it; with --new-binary-ok it goes on. A finished run of this
        format given by --data-dir, or another size's, carries on."""
        self.ui.state = "disconnected"
        d = self.smoke_folder(name="data/gen/smoke2", fmt=2)
        for args in (("--data-dir", "data/gen/smoke2"), ("--data-dir=data/gen/smoke2", "--limit", "8")):
            code, out = self.run_script(*args)
            self.assertEqual(code, 1, out)
            self.assertIn(f"data/gen/smoke2/ holds a run that has finished, made by another version of the data "
                          f"generator (format 2, {T.DATAGEN_FORMAT} now)", out)
            self.assertIn("--data-dir data/gen/smoke6", out)
            self.assertIn("--new-binary-ok", out)
            self.assertNotIn("Building Chimera", out)
            self.assertIsNone(self.ran())
            self.assertFalse(os.path.exists(os.path.join(d, "run.log")))
        code, out = self.run_script("--data-dir", "data/gen/smoke2", "--new-binary-ok")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.ran()[-3:], ["--data-dir", "data/gen/smoke2", "--new-binary-ok"])
        os.remove(self.args)
        # the third to the fifth smoke runs': formats 3 to 5 (4 since Nov 4, 5 since Nov 5, 6 since Nov 6)
        for k in (3, 4, 5):
            dk = self.smoke_folder(name=f"data/gen/smoke{k}", fmt=k)
            code, out = self.run_script("--data-dir", f"data/gen/smoke{k}")
            self.assertEqual(code, 1, out)
            self.assertIn(f"data/gen/smoke{k}/ holds a run that has finished, made by another version of the data "
                          f"generator (format {k}, {T.DATAGEN_FORMAT} now)", out)
            self.assertIn("--data-dir data/gen/smoke6", out)
            self.assertIsNone(self.ran())
            self.assertFalse(os.path.exists(os.path.join(dk, "run.log")))
        self.smoke_folder(name="data/gen/night", fmt=2)
        code, out = self.run_script(SIZE="night")  # its default folder, another size
        self.assertEqual(code, 1, out)
        self.assertIn("data/gen/night/ holds a run that has finished", out)
        self.smoke_folder(name="data/gen/smoke9", fmt=T.DATAGEN_FORMAT)
        code, out = self.run_script("--data-dir", "data/gen/smoke9")
        self.assertEqual(code, 0, out)
        self.assertNotIn("holds a run that has finished", out)

    def test_the_run_folders_go_outside_the_home_folder(self):
        """WM_SCRATCH defaults to a folder in $TMPDIR, not data/scratch: the sandbox denies reading /Users, so node
        can't start in a run folder there. One that is set stays; a $TMPDIR under /Users or /Volumes gives /tmp."""
        self.ui.state = "disconnected"
        tmp = os.path.join(self.root, "tmpdir")
        os.makedirs(tmp)
        code, out = self.run_script(TMPDIR=tmp + "/")
        self.assertEqual(code, 0, out)
        with open(self.args + ".scratch", encoding="utf-8") as f:
            got = f.read()
        self.assertEqual(got, os.path.join(tmp, "chimera-wm-scratch"))
        self.assertTrue(os.path.isdir(got))
        self.assertFalse(os.path.exists(os.path.join(self.root, "wm", "data", "scratch")))
        mine = os.path.join(self.root, "given-scratch")
        code, out = self.run_script(TMPDIR=tmp, WM_SCRATCH=mine)
        self.assertEqual(code, 0, out)
        with open(self.args + ".scratch", encoding="utf-8") as f:
            self.assertEqual(f.read(), mine)
        # the rule alone (no folder is made): a $TMPDIR in the home folder or on another volume isn't used
        with open(SCRIPT, encoding="utf-8") as f:
            (rule,) = [line for line in f if line.startswith('case "${TMPDIR:-}" in')]
        for given, base in (("/Users/someone/T/", "/tmp"), ("/Volumes/Disk/T", "/tmp"), ("", "/tmp"),
                            ("/private/var/folders/x/T/", "/private/var/folders/x/T")):
            p = subprocess.run(["/bin/bash", "-c", rule + 'printf %s "$SCRATCH_BASE"'], capture_output=True,
                               text=True, env={"TMPDIR": given, "PATH": "/usr/bin:/bin"}, timeout=10)
            self.assertEqual(p.stdout, base, given)

    def test_an_unfinished_smoke_carries_on_in_its_folder(self):
        self.ui.state = "disconnected"
        d = self.smoke_folder(finished=False)  # a seed ended in an error: "run this again to retry them"
        code, out = self.run_script()
        self.assertEqual(code, 0, out)
        self.assertIn("into data/gen/smoke/ (log: data/gen/smoke/run.log)", out)
        with open(os.path.join(d, "run.log"), encoding="utf-8") as f:
            self.assertIn("stub datagen.run", f.read())
        os.remove(os.path.join(d, "REPORT.md"))
        C.write_jsonl(os.path.join(d, "tasks.jsonl"), [done(seed(1)), done(seed(2))])  # finished, no report yet
        self.assertEqual(self.run_script()[0], 0)

    def test_arguments_go_through_and_the_exit_codes(self):
        self.ui.state = "disconnected"
        code, out = self.run_script("--no-early-stop", "--new-binary-ok", SIZE="night")
        self.assertEqual(code, 0, out)
        argv = self.ran()
        self.assertEqual(argv[:2], ["--size", "night"])
        self.assertEqual(argv[-2:], ["--no-early-stop", "--new-binary-ok"])
        self.assertIn("Done. Report: data/gen/night/REPORT.md", out)
        code, out = self.run_script(STUB_EXIT="4")
        self.assertEqual(code, 4, out)
        self.assertIn("Every stage ran, but some seeds ended in an error", out)
        self.assertIn("Run this again to retry them", out)
        self.assertNotIn("Done.", out)
        for stopped in ("3", "2", "1"):
            code, out = self.run_script(STUB_EXIT=stopped)
            self.assertEqual(code, 1, out)
            self.assertIn("The run stopped.", out)
            self.assertNotIn("Done.", out)


if __name__ == "__main__":
    unittest.main()
