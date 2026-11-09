"""datagen/build.py and run.py (and report.py end to end): the tiny size for real, end to end, and build's filters on
their own (report.py's own tests are in tests/test_datagen_report.py).

End to end: `python3 -m datagen.run --size tiny` (through run.main) against the stand-in Ollama of
tests/datagen_fakes.py, a Chimera binary built from app/ into the scratch folder ($WM_SCRATCH, else data/scratch/,
removed afterwards; $CHIMERA_BIN's, copied there, when it names one) and real Blender 5.2.2 and 5.0.1 (about 15 s of
it): the seeds, every seed's task, the build and
the report. Every canned reply is a test fixture carrying the mark, never training data, so the seeds and build
stages run with datagen_fakes.FixtureIndex (the eval index minus the mark) to follow them through, and the last
check, tools/check_overlap.py with its own index, must flag every built line by the mark and nothing else: the guard
works, and with the mark taken out the lines are clean. Checked: every training request is byte for byte what
--hydra-worker-request prints for that step (run directly), with no teacher notes, which only the teacher's copies
carry; the examples' meta and the split by seed group; a second run from the caches makes no model call, no
Blender, Python or Chimera check run, and writes the same tasks.jsonl content; STOP, the early stop, errors in a
row, and the exit codes for a missing model, binary or Blender. Skipped without Go or either Blender.

Build's filters on their own run on hand-made records (fixtures, with the mark): the token limit, eval overlap (the
system prompt too), teacher notes and, in a Blender target only, Blender versions and the notes' words for them,
unconfirmed, third-party and refused tests, files with no Python, pieces nothing ran on and tests that couldn't reach
the code marked unverified, the meta's format, records of another data generator format, old fingerprints,
duplicates, the failed-dependency share (and its line in STATS.md), the repair cap, plan_failed, the split (every mode
in valid), and publishing only after the last check; and the facts filters after the second smoke's audit (steps
kept only as a dependency, no_example; a handoff claiming a failed dependency, dep_claimed, through the real
dep_honesty.check on the stored request and the target; Chimera's own validator warnings on the kept candidate's or
repair's stored verdict; code in a language nothing here parsed, through the real lang_check, the kept gate's parse
results counting; a Blender piece's ctx channel or dead output key, through blender_gate's facts; the first that
fires drops, every one is counted), and since format 4 ctx["values"] as the contract's (the contract fixtures' values
pair kept) with ctx_channel a backstop for a hole in the gate.
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

import evalset

from tests import _paths  # noqa: F401
from tests import contract_fixtures as CF
from tests import datagen_fakes as F
from datagen import build as B
from datagen import blender_gate as BG
from datagen import common as C
from datagen import dep_honesty as DH
from datagen import hints as H
from datagen import lang_check as LC
from datagen import report as RP
from datagen import run as R
from datagen import seeds as SD
from datagen import sizes, task as T
from tools import blender_check, blenders
from tools.check_overlap import EvalIndex

MARK = F.MARK
HAVE_BLENDER = all(not blenders.check_path(p) for p in blenders.VERSIONS.values())
GATE = {"idle_switch_s": 0.05}  # the stand-in answers at once; the real 15 s would only add waiting

_tmp = _bin = _fake = _index = None


def setUpModule():
    global _tmp, _bin, _fake, _index
    _tmp = tempfile.mkdtemp(prefix="test-datagen-build-", dir=blender_check.scratch_root())
    _index = EvalIndex(8)
    if F.HAVE_CHIMERA:
        try:
            _bin = F.build_chimera(_tmp)  # a fresh copy of $CHIMERA_BIN, else built from app/
        except RuntimeError:
            shutil.rmtree(_tmp, ignore_errors=True)
            raise
    _fake = F.FakeOllama(os.path.join(_tmp, "fake.jsonl"))


def tearDownModule():
    if _fake:
        _fake.stop()
    if _tmp:
        shutil.rmtree(_tmp, ignore_errors=True)


def main(argv, **kw):
    """run.main with its progress lines kept off the test's output."""
    with contextlib.redirect_stderr(io.StringIO()):
        return R.main(argv, **kw)


def args(data, *more):
    return ["--size", "tiny", "--data-dir", data, "--host", _fake.url, "--chimera", _bin] + list(more)


def records(data):
    return {r["key"]: r for r in C.read_jsonl(os.path.join(data, "tasks.jsonl"))}


def items(rec):
    """(round, step or variant, repair or None) for every stored request of a record."""
    for rnd in rec["rounds"]:
        for st in rnd.get("steps", []) + rnd.get("variants", []):
            if st.get("request"):
                yield rnd, st, None
                for rp in st["repairs"]:
                    yield rnd, st, rp


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def chat_calls():
    with _fake.lock:
        return len(_fake.calls)


HAVE_CHIMERA = F.HAVE_CHIMERA


@unittest.skipUnless(HAVE_CHIMERA and HAVE_BLENDER, "needs Go (or CHIMERA_BIN) and Blender " +
                     " and ".join(blenders.VERSIONS))
class EndToEndTests(unittest.TestCase):
    """One tiny run in setUpClass; the tests read what it left."""

    @classmethod
    def setUpClass(cls):
        cls.data = os.path.join(_tmp, "tiny")
        _fake.plans.update({"for Blender 5.x": F.BLENDER_PLAN, "a working Python program": F.FILES_PLAN})
        cls.fixture_index = F.FixtureIndex(_index)
        assert main(args(cls.data, "--stages", "seeds"), index=cls.fixture_index, gate=GATE) == 0
        cls.seeds = C.read_jsonl(os.path.join(cls.data, "seeds.jsonl"))
        _fake.bad_plans.update(s["text"] for s in cls.seeds if s["source"] == "helper")
        cls.tasks_exit = main(args(cls.data, "--stages", "tasks"), index=cls.fixture_index, gate=GATE)
        cls.build_exit = main(args(cls.data, "--stages", "build"), index=cls.fixture_index)
        cls.report_exit = main(args(cls.data, "--stages", "report"))
        cls.recs = records(cls.data)
        cls.sft = os.path.join(cls.data, "sft")
        cls.train = C.read_jsonl(os.path.join(cls.sft, "flagged", "train.jsonl"))
        cls.meta = C.read_jsonl(os.path.join(cls.sft, "flagged", "train.meta.jsonl"))

    def copy_without_tasks(self, name):
        """The data folder, caches and all, without tasks.jsonl (a fresh start that has every cache)."""
        d = os.path.join(_tmp, name)
        shutil.rmtree(d, ignore_errors=True)
        shutil.copytree(self.data, d, ignore=shutil.ignore_patterns("tasks.jsonl", "sft", "REPORT.md"))
        return d

    def test_the_run(self):
        self.assertEqual((self.tasks_exit, self.build_exit, self.report_exit), (0, 1, 0))
        self.assertEqual(sorted(s["category"] for s in self.seeds), ["blender", "python", "small_task"])
        self.assertEqual({r["status"] for r in self.recs.values()}, {"done"})
        by = {r["seed"]["category"]: r for r in self.recs.values()}
        self.assertEqual(by["blender"]["round2"], "ran")
        self.assertEqual(by["small_task"]["round2"], "one_step")
        b1 = by["blender"]["rounds"][0]
        self.assertEqual([s["mode"] for s in b1["steps"]], ["blender", "blender", "section"])
        lamp = b1["steps"][1]
        self.assertEqual(lamp["kept"]["from"], "repair")
        self.assertTrue(lamp["repairs"][0]["example"])
        self.assertTrue(lamp["candidates"][0]["crash"]["error"].startswith("TypeError"))
        self.assertTrue(b1["plan_check"]["blender"]["ok"])
        self.assertEqual(by["small_task"]["rounds"][0]["planner"]["fell_back"], True)
        f1 = by["python"]["rounds"][0]
        self.assertEqual(f1["steps"][1]["kept"]["from"], "second")
        self.assertIsNone(f1["steps"][2]["kept"])
        self.assertEqual(f1["steps"][3]["missing_deps"], ["s3"])
        variants = {(v["sid"], v["variant"]): bool(v["kept"]) for v in b1["variants"]}
        self.assertEqual(variants, {("s2", "failed_dep"): False, ("s2", "mixed_pool"): False,
                                    ("s3", "failed_dep"): True, ("s3", "mixed_pool"): True})
        for name in ("RUN.json", "seeds.jsonl", "seed_calls.jsonl", "tasks.jsonl", "gate.jsonl", "progress.log",
                     "REPORT.md", "report.json"):
            self.assertTrue(os.path.exists(os.path.join(self.data, name)), name)
        self.assertEqual(sorted(os.listdir(os.path.join(self.data, "names"))), ["5.0.1.txt", "5.2.2.txt"])
        run = C.read_json(os.path.join(self.data, "RUN.json"))
        self.assertEqual(run["chimera"]["version"], "0.8.0")
        self.assertEqual(len(run["starts"]), 3)  # four starts: seeds, tasks, build, report

    def test_the_seed_stage_and_its_eval_guard(self):
        """With the eval index as it is, the stand-in's seeds are dropped by the mark; the helper's isn't."""
        d = os.path.join(_tmp, "seeds-guard")
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        shutil.copy(os.path.join(self.data, SD.CALLS_FILE), d)
        from datagen import llm as L
        llm = L.LLM(_fake.url, L.Gate(), C.Cache(os.path.join(self.data, "cache", "calls.jsonl")), unload=False)
        before = chat_calls()
        got = SD.make_seeds(llm, d, sizes.get("tiny"), index=_index)
        self.assertEqual(chat_calls(), before)  # the calls' records are reused
        self.assertEqual([s["source"] for s in got], ["helper"])
        dropped = C.read_jsonl(os.path.join(d, SD.DROPPED_FILE))
        new = [x for x in dropped if x["source"] == "new"]
        self.assertEqual(len(new), 2)
        self.assertTrue(all(x["reason"] == "eval_overlap" and x["detail"] == ["mark:test-fixture"] for x in new))

    def test_every_training_request_is_chimeras_own(self):
        names = {v: read(os.path.join(self.data, "names", v + ".txt")).strip()
                 for v in blenders.VERSIONS}
        n = 0
        for rec in self.recs.values():
            for rnd, st, rp in items(rec):
                item = rp or st
                got = F.binary_request(_bin, rnd["plan"], rec["seed"]["text"], item["inputs"], names)
                self.assertEqual(json.dumps(item["request"]["messages"], ensure_ascii=False),
                                 json.dumps(got["messages"], ensure_ascii=False))
                n += 1
        self.assertGreater(n, 20)
        # and each example's request is the record's, untouched
        self.assertEqual(len(self.train), len(self.meta))
        for ex, m in zip(self.train, self.meta):
            rec = self.recs[m["seed_id"]]
            rnd = rec["rounds"][m["round"] - 1]
            st = next(s for s in rnd["steps"] + rnd["variants"]
                      if s["sid"] == m["sid"] and s["variant"] == m["variant"])
            want = next(r for r in st["repairs"] if r["turn"] == m["turn"])["request"] if m["repaired"] \
                else st["request"]
            self.assertEqual(ex["messages"][:-1], want["messages"])
            self.assertEqual(ex["messages"][-1]["role"], "assistant")
            self.assertNotIn(H.HEAD, json.dumps(ex, ensure_ascii=False))
        blender_ex = [m for m in self.meta if m["mode"] == "blender"]
        self.assertTrue(blender_ex and all(m["names"] in ("5.2.2", "5.0.1", None) for m in blender_ex))

    def test_the_notes_are_in_the_teachers_copies_only(self):
        lines = C.read_jsonl(os.path.join(_tmp, "fake.jsonl"))
        workers = [x["body"] for x in lines if x["job"] == "worker"]
        self.assertTrue(workers)
        blender = 0
        for b in workers:
            system = b["messages"][0]["content"]
            self.assertIn("\n\n" + H.HEAD + "\n" + H.FORMAT_NOTE, system)
            if "Write one python code block for Blender" in system:
                blender += 1
                self.assertIn(H.BLENDER_NOTE, system.split(H.HEAD)[1])
        self.assertGreater(blender, 0)
        for rec in self.recs.values():
            for _, st, rp in items(rec):
                self.assertNotIn(H.HEAD, json.dumps((rp or st)["request"], ensure_ascii=False))

    def test_the_overlap_guard(self):
        self.assertFalse(os.path.exists(os.path.join(self.sft, "train.jsonl")))  # nothing published
        stats = C.read_json(os.path.join(self.sft, "stats.json"))
        self.assertFalse(stats["published"])
        self.assertNotIn("eval_overlap", stats["dropped"])  # nothing but the mark matched an eval text
        self.assertGreater(stats["dropped"].get("duplicate", 0), 0)  # round 2's repair request repeats round 1's
        report = read(os.path.join(self.sft, "flagged", "OVERLAP.txt"))
        flagged = [l for l in report.splitlines() if l.startswith("line ")]
        self.assertEqual(len(flagged), len(self.train))
        self.assertTrue(all(l.split(": ", 1)[1] == "mark:test-fixture (100%)" for l in flagged))
        # with the mark taken out, the same lines are clean
        clean = os.path.join(_tmp, "unmarked.jsonl")
        with open(os.path.join(self.sft, "flagged", "train.jsonl"), encoding="utf-8") as f, \
                open(clean, "w", encoding="utf-8") as out:
            for line in f:
                out.write(json.dumps(json.loads(line), ensure_ascii=False).replace(MARK, "") + "\n")
        code, text = B.check_file(clean)
        self.assertEqual(code, 0, text)
        # and with the eval index as it is, build drops every example by the mark
        d = os.path.join(_tmp, "real-index")
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        shutil.copy(os.path.join(self.data, "tasks.jsonl"), d)
        st = B.build(d, sizes.get("tiny"), index=_index)
        # the eval check comes after the token one and the steps kept only as a dependency
        before = {k: stats["dropped"][k] for k in ("too_long", "no_example") if stats["dropped"].get(k)}
        every = stats["examples"] - sum(before.values())
        self.assertEqual((st["kept"], st["dropped"]), (0, dict(before, eval_overlap=every)))
        self.assertEqual(st["eval_hits"], {"mark:test-fixture": every})
        self.assertTrue(st["published"])
        self.assertEqual(C.read_jsonl(os.path.join(d, "sft", "train.jsonl")), [])

    def test_meta_and_the_split(self):
        self.assertGreater(len(self.meta), 15)
        for m in self.meta:
            self.assertEqual(set(B.META_KEYS) - set(m), set())
            self.assertEqual(m["format"], T.DATAGEN_FORMAT)  # which generator format made it
            self.assertEqual(m["group"], T.group_of(m["seed_id"]))
            self.assertIn(m["model"], ("gpt-oss:120b", "qwen3.8:27b"))
            self.assertGreater(m["request_tokens"], 0)
        kinds = {(m["variant"], m["repaired"], m["source"], m["round"], m["lone"]) for m in self.meta}
        self.assertTrue(any(k[0] == "failed_dep" for k in kinds) and any(k[0] == "mixed_pool" for k in kinds))
        self.assertTrue(any(k[1] for k in kinds) and any(k[2] == "second" for k in kinds))
        self.assertTrue(any(k[3] == 2 for k in kinds) and any(k[4] for k in kinds))
        # the Python seed's s4 was written with s3 failed: a natural failed-dependency example, kept only within
        # 10% of its mode's
        stats = C.read_json(os.path.join(self.sft, "stats.json"))
        natural = [m for m in self.meta if B.natural_failed_dep(m)]
        # (or, since the second smoke's audit, it was refused for claiming s3's output or kept only as a dependency)
        self.assertTrue(natural or any(stats["dropped"].get(k) for k in ("failed_dep_share", "dep_claimed",
                                                                          "no_example")))
        for mode in {m["mode"] for m in self.meta}:
            mine = [m for m in self.meta if m["mode"] == mode]
            self.assertLessEqual(sum(B.natural_failed_dep(m) for m in mine), B.FAILED_DEP_CAP * len(mine) + 1e-9)
        # three seed groups: fewer than four, so none goes to valid
        self.assertEqual(C.read_jsonl(os.path.join(self.sft, "flagged", "valid.jsonl")), [])
        self.assertEqual(len({m["group"] for m in self.meta}), 3)

    def test_a_second_run_replays_from_the_caches(self):
        d = self.copy_without_tasks("replay")
        before = chat_calls()
        boom = AssertionError("ran something a cache holds")
        from datagen import blender_gate, pysandbox
        from datagen.chimera import Chimera
        real_run, real_names, sheets = pysandbox.run, Chimera.blender_names, []

        def run(files, entry, *a, **kw):  # only run.py's start-up check that python3 runs in the sandbox
            if entry != "canary.py":
                raise boom
            return real_run(files, entry, *a, **kw)

        def names(self, *a, **kw):  # printed at every start, for the fingerprint, never read back
            sheets.append(a)
            return real_names(self, *a, **kw)
        with mock.patch.object(blender_gate.GateBlender, "check_one", side_effect=boom), \
                mock.patch.object(blender_gate.GateBlender, "_probe_one", side_effect=boom), \
                mock.patch.object(pysandbox, "run", side_effect=run), \
                mock.patch.object(Chimera, "check_result", side_effect=boom), \
                mock.patch.object(Chimera, "blender_names", names):
            self.assertEqual(main(args(d, "--stages", "tasks"), index=self.fixture_index, gate=GATE), 0)
        self.assertEqual(len(sheets), len(blenders.VERSIONS))
        self.assertEqual(chat_calls(), before)
        again = records(d)
        self.assertEqual(sorted(again), sorted(self.recs))
        for k, rec in self.recs.items():
            self.assertEqual(T.stable(again[k]), T.stable(rec), k)
        # finished seeds are skipped outright
        self.assertEqual(main(args(d, "--stages", "tasks"), gate=GATE), 0)
        self.assertEqual(records(d), again)

    def test_stop_then_carry_on(self):
        d = self.copy_without_tasks("stop")
        real = T.run_seed

        def first_touches_stop(env, seed):
            open(os.path.join(d, C.STOP_FILE), "w").close()
            return real(env, seed)
        with mock.patch.object(T, "run_seed", side_effect=first_touches_stop):
            self.assertEqual(main(args(d, "--stages", "tasks"), gate=GATE), 3)
        self.assertIn("STOP", read(os.path.join(d, C.STOPPED_FILE)))
        self.assertLess(len(records(d)), 3)
        self.assertEqual(main(args(d, "--stages", "tasks"), gate=GATE), 0)
        self.assertFalse(os.path.exists(os.path.join(d, C.STOPPED_FILE)))
        self.assertFalse(os.path.exists(os.path.join(d, C.STOP_FILE)))
        self.assertEqual(len(records(d)), 3)

    def test_the_report(self):
        rep = C.read_json(os.path.join(self.data, RP.JSON_FILE))
        text = read(os.path.join(self.data, RP.REPORT_FILE))
        for head in ("## Seeds", "## Plans", "## Steps", "## Variants", "## Plan checks and round 2", "## Model time",
                     "## Projection"):
            self.assertIn(head, text)
        self.assertEqual((rep["status"], rep["errored"]), ({"done": 3}, 0))
        self.assertEqual(rep["steps"]["files"]["second sampler"], 2)  # Totals, in both rounds of the Python seed
        kept_code = [s for r in self.recs.values() for rnd in r["rounds"] for s in rnd["steps"]
                     if s["kept"] and not s.get("no_example") and s["mode"] in RP.CODE_MODES]  # soft keeps apart
        self.assertEqual(sum(sum(c.values()) for c in rep["tests"].values()), len(kept_code))
        for c in rep["tests"].values():  # every kept code step's tests_status (task.py) is one of the three kinds
            self.assertTrue(all(k in ("valid", "unconfirmed") or k.startswith("none:") for k in c), c)
        # steps kept only as a dependency: their own column, the audit's line, and the build's no_example drops (one
        # each, unless it was kept from a failed repair, which gives no example anyway)
        soft = [s for r in self.recs.values() for rnd in r["rounds"] for s in rnd["steps"] if s.get("no_example")]
        self.assertEqual(sum(c.get("dependency only", 0) for c in rep["steps"].values()), len(soft))
        self.assertEqual(sum(rep["after_audit"]["no_example"].values()), len(soft))
        self.assertEqual(rep["build"]["dropped"].get("no_example", 0),
                         sum(1 for s in soft if s["kept"]["from"] != "repair"))
        self.assertGreater(rep["steps"]["blender"]["repairs"], 0)
        self.assertEqual(rep["round2"], {"ran": 2, "one_step": 1})
        per = rep["projection"]["per_kind"]
        for k in ("blender", "code", "writing"):
            self.assertGreater(per[k]["examples"], 0, k)
            self.assertIsNotNone(per[k]["s_per_example"], k)
        self.assertIsNotNone(rep["projection"]["hours_to_plan_mix"])
        self.assertGreater(rep["runs"].get("blender", 0), 0)


@unittest.skipUnless(HAVE_CHIMERA, "needs Go or CHIMERA_BIN")
class ExitCodeTests(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="exits-", dir=_tmp)
        self.addCleanup(shutil.rmtree, self.data, True)

    def test_a_missing_model(self):
        _fake.models.discard("qwen3:8b")
        self.addCleanup(_fake.models.add, "qwen3:8b")
        self.assertEqual(main(args(self.data, "--stages", "tasks")), 2)
        self.assertEqual(main(args(self.data, "--stages", "seeds"), gate=GATE), 0)  # it needs only the teacher

    def test_a_missing_binary_or_blender(self):
        a = ["--size", "tiny", "--data-dir", self.data, "--host", _fake.url, "--chimera",
             os.path.join(self.data, "no-chimera"), "--stages", "tasks"]
        self.assertEqual(main(a), 2)
        with mock.patch.dict(blenders.VERSIONS, {"5.0.1": os.path.join(self.data, "no-blender")}):
            self.assertEqual(main(args(self.data, "--stages", "tasks")), 2)

    def test_ollama_not_answering(self):
        a = ["--size", "tiny", "--data-dir", self.data, "--host", "127.0.0.1:9", "--chimera", _bin]
        self.assertEqual(main(a + ["--stages", "seeds"]), 2)


class RunTasksTests(unittest.TestCase):
    """run.run_tasks with a stand-in run_seed: the early stop and errors in a row."""

    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="runtasks-", dir=_tmp)
        self.addCleanup(shutil.rmtree, self.data, True)
        self.seeds = [{"seed_id": f"n-python-{k:04d}-00", "key": f"n-python-{k:04d}-00"} for k in range(8)]

    def go(self, fn, size):
        store = C.Store(os.path.join(self.data, "tasks.jsonl"))
        with mock.patch.object(T, "run_seed", side_effect=fn):
            with contextlib.redirect_stderr(io.StringIO()):
                return R.run_tasks(None, self.seeds, store, R.Stopper(self.data), size), store

    def test_the_early_stop(self):
        def nothing_kept(env, seed):
            time.sleep(0.05)
            return {"key": seed["seed_id"], "seed": seed, "status": "done", "error": None, "round2": None,
                    "rounds": [{"steps": [{"kept": None}, {"kept": None}]}]}
        with self.assertRaises(C.StopRequested) as cm:
            self.go(nothing_kept, {"seeds_parallel": 1, "early_stop": {"after": 3, "min_kept": 0.3}})
        self.assertIn("early stop: after 3 seeds only 0 of 6", str(cm.exception))
        self.assertIn(len(C.Store(os.path.join(self.data, "tasks.jsonl"))), (3, 4))  # and the one in flight

    def test_errors_in_a_row_stop_the_run_and_run_again(self):
        def fails(env, seed):
            time.sleep(0.02)
            return {"key": seed["seed_id"], "seed": seed, "status": "error", "error": "CallFailed: gone",
                    "rounds": [], "round2": None}
        with self.assertRaises(C.StopRequested) as cm:
            self.go(fails, {"seeds_parallel": 1})
        self.assertIn("in a row ended in an error", str(cm.exception))

        def works(env, seed):
            return {"key": seed["seed_id"], "seed": seed, "status": "done", "error": None, "round2": None,
                    "rounds": [{"steps": [{"kept": {"from": "cand", "index": 0}}]}]}
        out, store = self.go(works, {"seeds_parallel": 3})
        self.assertEqual((out["done"], out["skipped"]), (8, 0))  # the errors were run again
        self.assertEqual({r["status"] for r in store.all()}, {"done"})
        out, _ = self.go(works, {"seeds_parallel": 3})
        self.assertEqual((out["done"], out["skipped"]), (0, 8))


# ---------------------------------------------------------------- build's filters, on hand-made records

def piece(sid, n=1, extra=""):
    return f"```python\n{MARK}\ndef f_{sid}_{n}():\n    return {n}\n```\n{extra}"


def step(sid, mode="blender", kind="blender", content=None, repair=None, variant=None, plan_failed=False,
         request=None):
    content = content or piece(sid)
    st = {"sid": sid, "index": int(sid[1:]) - 1, "kind": kind, "mode": mode, "variant": variant, "lone": False,
          "missing_deps": [], "names": None, "request": request or {"messages": [
              {"role": "system", "content": f"System for {sid}. {MARK}"},
              {"role": "user", "content": f"Your step, {sid}. {MARK}"}], "need_ctx": 4200},
          "request_tokens": 120, "candidates": [{"model": "gpt-oss:120b", "content": content}], "repairs": [],
          "kept": {"from": "cand", "index": 0}, "plan_failed": plan_failed}
    if repair:
        st["repairs"] = [{"model": "gpt-oss:120b", "content": content, "turn": 1, "example": True,
                          "request": {"messages": st["request"]["messages"][:1] + [
                              {"role": "user", "content": f"Repair {sid}: {repair}. {MARK}"}]},
                          "request_tokens": 140}]
        st["kept"] = {"from": "repair", "index": 0}
    return st


def record(seed_id, steps, variants=(), plan=None):
    return {"key": seed_id, "format": T.DATAGEN_FORMAT, "status": "done",
            "seed": {"seed_id": seed_id, "category": "blender", "source": "new"},
            "rounds": [{"round": 1, "plan": plan, "steps": list(steps), "variants": list(variants)}]}


def handoff(provides="f_s2", uses="none", assumed="none"):
    return f"```handoff\nprovides: {provides}\nuses: {uses}\nassumed: {assumed}\n```\n"


def with_dep(sid, dep, failed=True):
    """A request the way Chimera writes one with a dependency under its header: failed (dep_honesty.FAILED_LINE, the
    contract's own line) or received (its piece)."""
    body = DH.FAILED_LINE if failed else f"```python\n{MARK}\ndef load():\n    return []\n```"
    return {"messages": [{"role": "system", "content": f"System for {sid}. {MARK}"},
                         {"role": "user", "content": f"Your step, {sid}: Use the rows. {MARK}\n\nFrom {dep}, "
                                                     f"\"Load the rows\" (you use it):\n{body}"}], "need_ctx": 4200}


class BuildFilterTests(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="build-", dir=_tmp)
        self.addCleanup(shutil.rmtree, self.data, True)
        self.index = F.FixtureIndex(_index)

    def build(self, recs, **kw):
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), recs)
        return B.build(self.data, {"name": "test"}, index=self.index, check=False, **kw)

    def meta(self, name="train"):
        return C.read_jsonl(os.path.join(self.data, "sft", "staging", name + ".meta.jsonl")) or \
            C.read_jsonl(os.path.join(self.data, "sft", name + ".meta.jsonl"))

    def test_the_repair_cap(self):
        recs = [record(f"n-blender-{k:04d}-00", [step("s1", content=piece("s1", k)),
                                                 step("s2", content=piece("s2", k), repair=f"fix {k}"),
                                                 step("s3", content=piece("s3", k))])
                for k in range(10)]
        st = self.build(recs)
        # 20 build examples (two per seed: s1 and s3; s2, kept from its repair, gives only the repair example) allow
        # int(0.15 * 20 / 0.85) = 3 repairs
        self.assertEqual(st["repairs"], 3)
        self.assertEqual(st["dropped"], {"repair_cap": 7})
        again = self.build(recs)
        self.assertEqual(sorted(again["by_source"].items()), sorted(st["by_source"].items()))
        self.assertEqual(self.meta(), C.read_jsonl(os.path.join(self.data, "sft", "train.meta.jsonl")))

    def test_too_long_eval_overlap_duplicates_and_plan_failed(self):
        long = step("s1", content=piece("s1", extra="word " * 40000))
        canary = step("s2", content=piece("s2", extra=evalset.CANARY))
        same = step("s1", content=piece("s1", 7))
        recs = [record("n-blender-0001-00", [long, canary]), record("n-blender-0002-00", [same]),
                record("n-blender-0003-00", [same]), record("n-blender-0004-00", [step("s1", plan_failed=True)])]
        st = self.build(recs)
        self.assertEqual(st["dropped"], {"too_long": 1, "eval_overlap": 1, "duplicate": 1})
        self.assertEqual(st["left_out"], {"plan_failed": 1})
        self.assertEqual(st["eval_hits"], {"canary": 1})
        self.assertEqual(st["kept"], 1)
        st = self.build(recs, keep_plan_failed=True)
        self.assertEqual(st["kept"], 2)

    def test_the_system_prompt_is_checked_for_eval_text(self):
        """An eval plan's head in the system prompt (where the contract puts the project) drops that one example;
        the build doesn't wait for the last check to flag the whole file."""
        plan = evalset.load().by_id("w3-20")["plan"]
        system = f"System for s1. {MARK}\n\nProject: {plan['title']}\n{plan['summary']}"
        hit = step("s1", request={"messages": [{"role": "system", "content": system},
                                               {"role": "user", "content": f"Your step, s1. {MARK}"}]})
        recs = [record("n-blender-0001-00", [hit]), record("n-blender-0002-00", [step("s1", content=piece("s1", 2))])]
        st = self.build(recs)
        self.assertEqual((st["kept"], st["dropped"]), (1, {"eval_overlap": 1}))
        self.assertTrue(all("w3-20" in h for h in st["eval_hits"]), st["eval_hits"])

    def test_a_target_echoing_a_teacher_note(self):
        """hints.echoed_note on the target (the assistant message) only: the request may say anything Chimera's
        does. Stubbed here, so the test is build's own; the real one is tested with hints."""
        def echoed(text, extra=()):
            return "FORMAT_NOTE" if H.FORMAT_NOTE in text else None
        echo = step("s1", content=piece("s1", extra="assumed: " + H.FORMAT_NOTE))
        in_request = step("s2", content=piece("s2"), request={"messages": [
            {"role": "system", "content": f"System for s2. {MARK}"},
            {"role": "user", "content": f"Your step, s2. {H.FORMAT_NOTE} {MARK}"}]})
        with mock.patch.object(H, "echoed_note", side_effect=echoed):
            st = self.build([record("n-blender-0001-00", [echo, in_request])])
        self.assertEqual((st["kept"], st["dropped"]), (1, {"teacher_note": 1}))
        self.assertEqual(st["teacher_notes"], {"FORMAT_NOTE": 1})
        self.assertEqual([m["sid"] for m in self.meta()], ["s2"])
        self.assertIn("## Teacher-note drops", read(os.path.join(self.data, "sft", "STATS.md")))

    def test_a_target_echoing_a_teacher_note_for_real(self):
        echo = step("s1", content=piece("s1", extra="assumed: " + H.BLENDER_NOTE))
        st = self.build([record("n-blender-0001-00", [echo, step("s2")])])
        self.assertEqual((st["kept"], st["dropped"]), (1, {"teacher_note": 1}))

    def test_the_teacher_notes_head_is_a_mark_of_the_last_check(self):
        """Two parts of hints.HEAD, which no real reply or request has, flag a line in tools/check_overlap.py."""
        from tools import check_overlap
        new = {m: n for m, n in check_overlap.MARKS.items() if n.startswith("mark:teacher-notes")}
        self.assertEqual(len(new), 2)
        for mark, name in new.items():
            self.assertIn(mark, H.HEAD)
            self.assertIn((name, 1.0), _index.check("an assistant reply that says " + mark))
        self.assertEqual(_index.check("Notes for you, the reader, and Chimera sends these."), [])
        line = os.path.join(self.data, "notes.jsonl")
        C.write_jsonl(line, [{"messages": [{"role": "user", "content": "add a cube"},
                                           {"role": "assistant", "content": "import bpy\n# " + H.HEAD}]}])
        code, out = B.check_file(line)
        self.assertEqual(code, 1, out)
        self.assertIn("mark:teacher-notes (100%), mark:teacher-notes-aside (100%)", out)

    def test_code_examples_whose_tests_were_never_confirmed(self):
        """info["tests"], the step's tests_status as task.examples gives it: "unconfirmed" is left out unless
        keep_untested."""
        steps = [step(f"s{k}", mode="python-script", kind="code", content=piece(f"s{k}", k)) for k in (1, 2, 3)]
        for st, status in zip(steps, ("valid", "unconfirmed", "none:no_tests")):
            st["tests_status"] = status
        st = self.build([record("n-python-0001-00", steps)])
        self.assertEqual((st["kept"], st["dropped"]), (2, {"tests_unconfirmed": 1}))
        self.assertEqual({m["sid"]: m["tests"] for m in self.meta()}, {"s1": "valid", "s3": "none:no_tests"})
        st = self.build([record("n-python-0001-00", steps)], keep_untested=True)
        self.assertEqual((st["kept"], st["dropped"], st["keep_untested"]), (3, {}, True))

    def test_tests_that_couldnt_run_for_a_third_party_package(self):
        """none:third_party is dropped as third_party unless keep_untested; none:no_python (a project with no .py
        file) and none:tests_unreachable (tests that can't reach the step's code) are kept, as other none:* are."""
        statuses = ("none:third_party", "none:no_python", "none:tests_unreachable", "unconfirmed", "valid")
        steps = [step(f"s{k}", mode="files", kind="code", content=piece(f"s{k}", k)) for k in range(1, 6)]
        for st, status in zip(steps, statuses):
            st["tests_status"] = status
        st = self.build([record("n-python-0001-00", steps)])
        self.assertEqual((st["kept"], st["dropped"]), (3, {"third_party": 1, "tests_unconfirmed": 1}))
        # tests that couldn't reach the code confirmed nothing: kept, marked unverified (the false-drops audit's
        # D17-D19), as none:no_python is
        self.assertEqual(sorted((m["tests"], m["unverified"]) for m in self.meta()),
                         [("none:no_python", True), ("none:tests_unreachable", True), ("valid", False)])
        self.assertEqual(st["by_tests"], {"none:no_python": 1, "none:tests_unreachable": 1, "valid": 1})
        self.assertEqual(st["unverified_by_why"], {"none:no_python": 1, "none:tests_unreachable": 1})
        st = self.build([record("n-python-0001-00", steps)], keep_untested=True)
        self.assertEqual((st["kept"], st["dropped"]), (5, {}))

    def test_records_of_another_data_generator(self):
        """A record of another DATAGEN_FORMAT (the first smoke run's carry none: format 1) is dropped whole as
        old_format, whatever else is kept, and before the fingerprint is compared."""
        recs = [record(f"n-blender-{k:04d}-00", [step(s, content=piece(s, k)) for s in ("s1", "s2")])
                for k in range(3)]
        del recs[0]["format"]
        recs[1]["format"] = 1
        st = self.build(recs, keep_untested=True, keep_plan_failed=True)
        self.assertEqual((st["kept"], st["dropped"]), (2, {"old_format": 4}))
        self.assertEqual({m["seed_id"] for m in self.meta()}, {"n-blender-0002-00"})
        self.assertIn(f"4 examples were dropped as old_format: their seeds were made by another version of the data "
                      f"generator than this one (format {T.DATAGEN_FORMAT})", read(os.path.join(self.data, "sft",
                                                                                                 "STATS.md")))
        recs[2]["fingerprint"] = "fp-before"
        self.assertEqual(self.build(recs, fingerprint="fp-now")["dropped"], {"old_format": 4, "old_fingerprint": 2})

    def test_tests_still_refused_and_files_with_no_python(self):
        """none:tests_refused (the tests writer's replies broke the reader's rules, its retry too) is dropped as
        tests_refused unless keep_untested; none:no_python is kept, its meta marked unverified, and STATS.md counts
        those by mode."""
        statuses = ("none:tests_refused", "none:no_python", "none:no_tests", "valid")
        steps = [step(f"s{k}", mode="files", kind="code", content=piece(f"s{k}", k)) for k in range(1, 5)]
        for st, status in zip(steps, statuses):
            st["tests_status"] = status
        script = step("s5", mode="python-script", kind="code", content=piece("s5", 5))
        script["tests_status"] = "none:tests_refused"
        st = self.build([record("n-python-0001-00", steps + [script])])
        self.assertEqual((st["kept"], st["dropped"]), (3, {"tests_refused": 2}))
        self.assertEqual({m["sid"]: (m["tests"], m["unverified"]) for m in self.meta()},
                         {"s2": ("none:no_python", True), "s3": ("none:no_tests", False), "s4": ("valid", False)})
        self.assertEqual(st["unverified_by_mode"], {"files": 1})
        self.assertIn("## By mode, unverified (only compiled and parse-checked, or tests that couldn't reach the "
                      "code)",
                      read(os.path.join(self.data, "sft", "STATS.md")))
        st = self.build([record("n-python-0001-00", steps + [script])], keep_untested=True)
        self.assertEqual((st["kept"], st["dropped"]), (5, {}))

    def test_pieces_nothing_ran_on_and_the_metas_format(self):
        """A kept code piece whose gate ran neither tests nor an import run (task.settle_tests' nothing_ran: a Python
        project's docs page given empty tests, a script that does things when imported) is kept, its meta marked
        unverified and counted in STATS.md, as none:no_python is; a piece whose import run ran isn't. Every meta
        line says the generator format that made it."""
        statuses = (("none:no_tests", True), ("none:no_tests", False), ("valid", False), ("none:no_python", True))
        steps = [step(f"s{k}", mode="files", kind="code", content=piece(f"s{k}", k)) for k in range(1, 5)]
        for st, (status, ran_nothing) in zip(steps, statuses):
            st.update(tests_status=status, nothing_ran=ran_nothing)
        script = step("s5", mode="python-script", kind="code", content=piece("s5", 5))
        script.update(tests_status="none:no_tests", nothing_ran=True)
        old = step("s6", mode="files", kind="code", content=piece("s6", 6))
        old["tests_status"] = "none:no_python"  # a record from before nothing_ran
        st = self.build([record("n-python-0001-00", steps + [script, old])])
        self.assertEqual(st["kept"], 6)
        self.assertEqual({m["sid"]: (m["tests"], m["unverified"]) for m in self.meta()},
                         {"s1": ("none:no_tests", True), "s2": ("none:no_tests", False), "s3": ("valid", False),
                          "s4": ("none:no_python", True), "s5": ("none:no_tests", True),
                          "s6": ("none:no_python", True)})
        self.assertEqual(st["unverified_by_mode"], {"files": 3, "python-script": 1})
        self.assertEqual({m["format"] for m in self.meta()}, {T.DATAGEN_FORMAT})
        self.assertNotIn("nothing_ran", self.meta()[0])  # the meta says unverified; the record says why

    def test_a_target_naming_a_version_its_request_doesnt(self):
        """hints.version_leak against the example's own request: a first-turn target that names the checks'
        versions is dropped (teacher_note, "version_leak"); a repair whose request names the Blender that crashed
        may name it."""
        leak = step("s1", content=piece("s1", extra="assumed: safe for Blender 5.0.1 & 5.2.2"))
        fine = step("s2", content=piece("s2", extra="assumed: works in Blender 5.0 or newer"), request={"messages": [
            {"role": "system", "content": f"System for s2, for Blender 5.0 or newer. {MARK}"},
            {"role": "user", "content": f"Your step, s2. {MARK}"}]})
        repaired = step("s3", content=piece("s3", extra="assumed: Blender 5.2.2 has no such input"),
                        repair="your piece crashed in Blender 5.2.2")
        more = [step(f"s{k}", content=piece(f"s{k}", k)) for k in range(4, 10)]  # room for one repair under its cap
        st = self.build([record("n-blender-0001-00", [leak, fine, repaired] + more)])
        self.assertEqual((st["kept"], st["dropped"], st["teacher_notes"]), (8, {"teacher_note": 1},
                                                                            {"version_leak": 1}))
        self.assertEqual(sorted((m["sid"], m["repaired"]) for m in self.meta())[:2], [("s2", False), ("s3", True)])
        # the notes' words for the Blenders and the sandbox (hints.notes_leak), in a Blender target only; another
        # mode's target may name 5.0.1 or a sandbox, which its notes never did
        words = step("s1", content=piece("s1", extra="assumed: forest.blend is absent in the sandbox"))
        mark = step("s2", content=piece("s2", extra="# Thin Wall [newer only]: guarded"))
        pinned = step("s3", mode="files", kind="code", content=piece("s3", extra="File: requirements.txt\n"
                                                                               "sphinx==5.0.1  # in the sandbox"))
        prose = step("s4", mode="section", kind="writing", content=f"## Wi-Fi\n\nBoth 5.0 and 5.2 GHz work. {MARK}\n")
        st = self.build([record("n-mixed-0001-00", [words, mark, pinned, prose])])
        self.assertEqual((st["kept"], st["dropped"], st["teacher_notes"]), (2, {"teacher_note": 2},
                                                                            {"notes_leak": 2}))
        self.assertEqual({m["sid"] for m in self.meta()}, {"s3", "s4"})

    def test_the_failed_dependency_share(self):
        """Natural failed-dependency examples (missing_deps, not a failed_dep variant) are capped at 10% of their
        mode's, the rest dropped as failed_dep_share in stable_int order; failed_dep variants are left as they are."""
        recs = []
        for k in range(9):
            normal = [step(f"s{j}", content=piece(f"s{j}", k)) for j in (1, 2)]
            natural = step("s3", content=piece("s3", k))
            natural["missing_deps"] = ["s2"]
            prose = step("s4", mode="section", kind="writing", content=f"## Part {k}\n\n{MARK}\n")
            if k < 2:
                prose["missing_deps"] = ["s3"]
            variant = step("s3", content=piece("s3", 100 + k), variant="failed_dep")
            variant["missing_deps"] = ["s1"]
            recs.append(record(f"n-blender-{k:04d}-00", normal + [natural, prose], [variant] if k < 2 else []))
        st = self.build(recs)
        # blender: 18 normal and 2 failed_dep variants allow int(0.1 * 20 / 0.9) = 2 of the 9 natural ones;
        # section: 7 normal allow none of the 2
        self.assertEqual(st["dropped"], {"failed_dep_share": 7 + 2})
        meta = self.meta()
        self.assertEqual(st["failed_dep_natural"], 2)
        self.assertEqual(sum(1 for m in meta if m["variant"] == "failed_dep"), 2)
        self.assertEqual({m["mode"] for m in meta if B.natural_failed_dep(m)}, {"blender"})
        kept_natural = sorted(m["seed_id"] for m in meta if B.natural_failed_dep(m))
        again = self.build(recs)  # the same ones every time
        self.assertEqual(sorted(m["seed_id"] for m in self.meta() if B.natural_failed_dep(m)), kept_natural)
        self.assertEqual(again["dropped"], st["dropped"])
        # the ones kept come first in stable_int("failed-dep", seed, round, sid, variant, turn) order
        want = sorted((f"n-blender-{k:04d}-00" for k in range(9)),
                      key=lambda s: C.stable_int("failed-dep", s, 1, "s3", "", 0))[:2]
        self.assertEqual(kept_natural, sorted(want))
        # both shares by mode, for the plan's ~10%: 18 normal, 2 natural and 2 variants kept in blender
        self.assertEqual(st["failed_dep_share"], {"blender": {"natural": 2, "variants": 2, "of": 22}})
        self.assertIn("blender 2 natural and 2 failed_dep variants of 22 (18%)",
                      read(os.path.join(self.data, "sft", "STATS.md")))

    def test_the_caps_drops_are_listed_for_the_projection(self):
        """sft/stats.json lists each example the failed-dependency cap dropped with its mode and kind
        (failed_dep_capped), which report.projection counts back at a night's share (report.night_failed_deps): the
        fourth smoke's 4 Blender examples allowed none of its 2 natural ones."""
        recs = []
        for k in range(2):
            normal = [step(f"s{j}", content=piece(f"s{j}", k)) for j in (1, 2)]
            natural = step("s3", content=piece("s3", k))
            natural["missing_deps"] = ["s2"]
            recs.append(record(f"n-blender-{k:04d}-00", normal + [natural]))
        st = self.build(recs)
        self.assertEqual((st["kept"], st["dropped"]), (4, {"failed_dep_share": 2}))
        self.assertEqual(sorted(st["failed_dep_capped"], key=lambda d: d["example"]),
                         [{"mode": "blender", "kind": "blender", "example": f"n-blender-{k:04d}-00 r1 s3"}
                          for k in range(2)])
        self.assertEqual(self.build(recs[:1] + [record("n-blender-0009-00", [step("s1")])])["failed_dep_capped"],
                         [{"mode": "blender", "kind": "blender", "example": "n-blender-0000-00 r1 s3"}])

    def test_every_mode_has_a_group_in_valid(self):
        """5% of the groups by stable_int, then the first group of every mode with two or more and none in valid
        yet, if moving it leaves every mode a group in train; a mode with one group stays in train."""
        groups = [f"n-blender-{g:04d}" for g in range(40)]
        order = sorted(groups, key=lambda g: (C.stable_int("split", g), g))
        self.assertEqual(B.split_groups(groups), set(order[:2]))
        modes = {g: {"blender"} for g in groups}
        modes[order[0]] = {"blender", "files"}
        modes[order[5]] = {"files", "section"}
        modes[order[6]] = {"section"}
        modes[order[9]] = {"python-script"}
        modes[order[20]] = {"python-script"}
        modes[order[30]] = {"blender", "writing-only"}
        # files is in valid already (order[0]); section's first group order[5] would take files' last train group
        # away, so order[6]; python-script gets order[9]; writing-only has one group, which stays in train
        self.assertEqual(B.split_groups(groups, modes), {order[0], order[1], order[6], order[9]})
        self.assertEqual(B.split_groups(groups[:3], modes), set())  # fewer than four groups: none
        # through the build: every mode with two groups or more has examples in both files
        recs = []
        for g in range(40):
            mode, kind = (("files", "code") if g in (3, 17) else ("section", "writing") if g in (8, 25) else
                          ("blender", "blender"))
            content = f"## Part {g}\n\n{MARK}\n" if mode == "section" else piece("s1", g)
            recs.append(record(f"n-blender-{g:04d}-00", [step("s1", mode=mode, kind=kind, content=content)]))
        st = self.build(recs)
        train, valid = self.meta("train"), self.meta("valid")
        self.assertEqual({m["mode"] for m in valid}, {"blender", "files", "section"})
        self.assertEqual({m["mode"] for m in train}, {"blender", "files", "section"})
        self.assertFalse({m["group"] for m in train} & {m["group"] for m in valid})
        self.assertEqual(set(st["valid_by_mode"]), {"blender", "files", "section"})
        self.assertIn("## By mode, in valid", read(os.path.join(self.data, "sft", "STATS.md")))

    def test_seeds_made_with_other_requests(self):
        """With a fingerprint (run.py's, this start's), a record with another one, or none, is dropped whole."""
        recs = [record(f"n-blender-{k:04d}-00", [step(s, content=piece(s, k)) for s in ("s1", "s2")])
                for k in range(3)]
        recs[0]["fingerprint"], recs[1]["fingerprint"] = "fp-now", "fp-before"
        st = self.build(recs, fingerprint="fp-now")
        self.assertEqual((st["kept"], st["dropped"], st["fingerprint"]), (2, {"old_fingerprint": 4}, "fp-now"))
        self.assertEqual({m["seed_id"] for m in self.meta()}, {"n-blender-0000-00"})
        text = read(os.path.join(self.data, "sft", "STATS.md"))
        self.assertIn("old_fingerprint 4", text)
        self.assertIn("4 examples were dropped as old_fingerprint", text)
        self.assertEqual(self.build(recs)["kept"], 6)  # no fingerprint given: nothing to compare

    def test_the_split_is_by_seed_group(self):
        recs = [record(f"n-blender-{g:04d}-{j:02d}", [step("s1", content=piece("s1", g * 10 + j))])
                for g in range(40) for j in range(2)]
        st = self.build(recs)
        self.assertEqual(len(st["valid_groups"]), 2)  # 5% of 40 groups
        train, valid = self.meta("train"), self.meta("valid")
        self.assertEqual(len(valid), 4)
        self.assertFalse({m["group"] for m in train} & {m["group"] for m in valid})
        self.assertEqual({m["group"] for m in valid}, set(st["valid_groups"]))
        self.assertEqual(B.split_groups(["a", "b", "c"]), set())
        self.assertEqual(len(B.split_groups(["a", "b", "c", "d"])), 1)

    def test_a_step_kept_only_as_a_dependency(self):
        """step["no_example"] (task.Round.soft_keep: its best try failed only on task.SOFT_REASONS): task.examples
        leaves it out, its piece having fed the later steps, and the build counts it as dropped no_example, before
        every other filter, its reasons and modes in STATS.md. A record without one is read as it is."""
        soft = step("s1", content=piece("s1", 1) + handoff(uses="rows from s9"))
        soft["no_example"] = ["output_missing"]
        later = step("s2", content=piece("s2", 2))
        camera = step("s3", content=piece("s3", 3))
        camera["no_example"] = ["camera_not_active", "output_missing"]
        rec = record("n-blender-0001-00", [soft, later, camera])
        self.assertEqual([i["sid"] for _, i in T.examples(rec)], ["s2"])  # task's side of the interface
        st = self.build([rec])
        self.assertEqual((st["kept"], st["examples"], st["dropped"]), (1, 3, {"no_example": 2}))
        self.assertEqual((st["no_example"], st["no_example_by_mode"]),
                         ({"camera_not_active": 1, "output_missing": 2}, {"blender": 2}))
        self.assertEqual([m["sid"] for m in self.meta()], ["s2"])
        self.assertIn("2 steps were kept only as a dependency (no_example: their pieces fed the later steps and the "
                      "join, but their best try failed on camera_not_active 1, output_missing 2), by mode: blender 2.",
                      read(os.path.join(self.data, "sft", "STATS.md")))
        plain = record("n-blender-0002-00", [step("s1")])
        self.assertIs(B._without_no_example(plain)[0], plain)
        self.assertNotIn("no_example", B._without_no_example(rec)[0]["rounds"][0]["steps"][0])
        self.assertEqual(soft["no_example"], ["output_missing"])  # the record itself is left as it is

    def test_a_handoff_claiming_a_failed_dependency(self):
        """dep_honesty.check (the real one) on the stored request and the target: a uses line naming a dependency the
        request says failed (dep_claimed:s1) or an assumed line of none with one failed (dep_unlisted) is dropped as
        dep_claimed; an honest handoff, and one that names a dependency it really got, are kept. A repair example is
        read against its own request."""
        claims = step("s2", content=piece("s2", 1) + handoff(uses="rows from s1", assumed="rows are dicts"),
                      request=with_dep("s2", "s1"))
        unlisted = step("s3", content=piece("s3", 2) + handoff(), request=with_dep("s3", "s1"))
        honest = step("s4", content=piece("s4", 3) + handoff(assumed="s1 failed: the rows are guessed as dicts"),
                      request=with_dep("s4", "s1"))
        got = step("s5", content=piece("s5", 4) + handoff(uses="load from s1", assumed="none"),
                   request=with_dep("s5", "s1", failed=False))
        rep = step("s6", content=piece("s6", 5) + handoff(uses="rows (from s1)", assumed="s1's rows"),
                   repair="NameError: rows", request=with_dep("s6", "s1"))
        rep["repairs"][0]["request"] = with_dep("s6", "s1")
        st = self.build([record("n-blender-0001-00", [claims, unlisted, honest, got, rep])])
        self.assertEqual(st["dropped"], {"dep_claimed": 3})
        self.assertEqual(st["facts"]["dep_claimed"], {"dropped": 3, "fired": 3, "by_mode": {"blender": 3},
                                                      "found": {"dep_claimed": 2, "dep_unlisted": 1}})
        self.assertEqual({m["sid"] for m in self.meta()}, {"s4", "s5"})
        text = read(os.path.join(self.data, "sft", "STATS.md"))
        self.assertIn("## The facts filters", text)
        self.assertIn("| dep_claimed | 3 | 3 | blender 3 | dep_claimed 2, dep_unlisted 1 |", text)
        # stats.json names each example a filter fired on, for reading a night's firings one by one
        self.assertEqual(st["facts_examples"], {"dep_claimed": ["n-blender-0001-00 r1 s2", "n-blender-0001-00 r1 s3",
                                                                "n-blender-0001-00 r1 s6 repair 1"]})
        # nothing kept was written with a dependency missing: STATS.md says so rather than leaving the line out
        self.assertIn("Written with a dependency missing: none of the 2 kept (the plan wants about 10%).", text)
        # what a filter found is counted once per example: claimed from two failed steps is one dep_claimed
        two = step("s3", content=piece("s3", 6) + handoff(uses="rows from s1, cols from s2", assumed="guessed"),
                   request={"messages": [{"role": "system", "content": f"System for s3. {MARK}"},
                                         {"role": "user", "content": f"Your step, s3: Use both. {MARK}\n\nFrom s1, "
                                          f"\"Load the rows\" (you use it):\n{DH.FAILED_LINE}\n\nFrom s2, \"Load "
                                          f"the cols\" (you use it):\n{DH.FAILED_LINE}"}], "need_ctx": 4200})
        st = self.build([record("n-blender-0001-00", [two])])
        self.assertEqual(st["facts"]["dep_claimed"]["found"], {"dep_claimed": 1})

    def test_chimeras_own_validator_warnings(self):
        """The kept item's stored verdict: handoff_long, uses_undeclared or provides_missing drops the example as
        validator_warning (any other warning doesn't); the item is the kept candidate by its index, or for a repair
        example the repair, never another try of the step."""
        def warn(*codes):
            return {"ok": True, "issues": [{"level": "warn", "code": c, "message": MARK} for c in codes]}
        long_ = step("s1", content=piece("s1", 1))
        long_["candidates"][0]["verdict"] = warn("handoff_long", "main_guard")
        guard = step("s2", content=piece("s2", 2))
        guard["candidates"][0]["verdict"] = warn("main_guard")
        second = step("s3", content=piece("s3", 3))
        second["candidates"] = [{"model": "gpt-oss:120b", "content": MARK, "verdict": warn("provides_missing")},
                                {"model": "qwen3.8:27b", "content": piece("s3", 3), "verdict": warn()}]
        second["kept"] = {"from": "second", "index": 1}
        rep = step("s4", content=piece("s4", 4), repair="TypeError: f()")
        rep["candidates"][0]["verdict"] = warn("handoff_long")  # the crashed try: not the example's target
        rep["repairs"][0]["verdict"] = warn("uses_undeclared")
        clean_rep = step("s5", content=piece("s5", 5), repair="TypeError: g()")
        clean_rep["candidates"][0]["verdict"] = warn("handoff_long")
        more = [step(f"s{k}", content=piece(f"s{k}", k)) for k in range(6, 16)]
        st = self.build([record("n-blender-0001-00", [long_, guard, second, rep, clean_rep] + more)])
        self.assertEqual(st["dropped"], {"validator_warning": 2})
        self.assertEqual(st["facts"]["validator_warning"]["found"], {"handoff_long": 1, "uses_undeclared": 1})
        kept = {(m["sid"], m["repaired"]) for m in self.meta()}
        self.assertTrue({("s2", False), ("s3", False), ("s5", True)} <= kept, kept)
        self.assertFalse({("s1", False), ("s4", True)} & kept)

    def test_code_in_a_language_nothing_here_reads(self):
        """lang_check.build_drop (the real one) on an unverified files example: a code file by its File: extension
        that no parser here read and passed (PowerShell, or JavaScript the kept gate's "parse" has no pass for) drops
        it as unchecked_code; JavaScript node passed, a page, and a verified example are kept."""
        def files(sid, path, lang, body, tests="none:no_python", parse=None):
            st = step(sid, mode="files", kind="code",
                      content=f"File: {path}\n```{lang}\n{body}\n```\n\n" + handoff(provides=path))
            st.update(tests_status=tests, nothing_ran=tests != "valid")
            if parse is not None:
                st["candidates"][0]["gate"] = {"parse": parse}
            return st
        ps = files("s1", "tools/sync.ps1", "powershell", f"# {MARK}\nWrite-Output 'synced'")
        js_read = files("s2", "web/app.js", "javascript", f"// {MARK}\nconsole.log(1);",
                        parse=[{"path": "web/app.js", "kind": "js", "ok": True}])
        js_unread = files("s3", "web/main.js", "javascript", f"// {MARK}\nconsole.log(2);")
        page = files("s4", "README.md", "markdown", f"# Sync\n\n{MARK}")
        tested = files("s5", "tools/run.ps1", "powershell", f"# {MARK}\nWrite-Output 'ran'", tests="valid")
        st = self.build([record("coding-0001-00", [ps, js_read, js_unread, page, tested])])
        self.assertEqual(st["dropped"], {"unchecked_code": 2})
        self.assertEqual(st["facts"]["unchecked_code"]["found"], {"JavaScript": 1, "PowerShell": 1})
        self.assertEqual({m["sid"] for m in self.meta()}, {"s2", "s4", "s5"})

    def test_a_blender_piece_with_a_channel_or_key_chimera_never_reads(self):
        """blender_gate.ctx_channel and dead_output_key on a Blender example's code: a top-level ctx key other than
        scene, collection and objects, and an output-like SETTINGS_sN key other than "output", drop it (ctx_channel
        first, both counted); a piece that uses the contract's own channels, or a python-script piece, is kept."""
        values = step("s1", content=f"```python\n{MARK}\nSETTINGS_s1 = {{\"size\": 2.0, \"output_path\": "
                                    f"\"//out.png\"}}\n\n\ndef build_s1(ctx):\n    ctx[\"variables\"] = "
                                    f"dict(SETTINGS_s1)\n```\n" + handoff(provides="variables"))
        dead = step("s2", content=f"```python\n{MARK}\nSETTINGS_s2 = {{\"output_format\": \"PNG\"}}\n\n\n"
                                  f"def build_s2(ctx):\n    return None\n```\n")
        fine = step("s3", content=f"```python\n{MARK}\nSETTINGS_s3 = {{\"output\": \"//render.png\"}}\n\n\n"
                                  f"def build_s3(ctx):\n    ctx[\"objects\"][\"lamp\"] = None\n```\n")
        script = step("s4", mode="python-script", kind="code",
                      content=f"```python\n{MARK}\ndef run(ctx):\n    ctx[\"variables\"] = 1\n```\n")
        script["tests_status"] = "valid"
        self.assertEqual(BG.ctx_channel(T.piece_code(values["candidates"][0]["content"])), ["variables"])
        st = self.build([record("n-blender-0001-00", [values, dead, fine, script])])
        self.assertEqual(st["dropped"], {"ctx_channel": 1, "dead_output_key": 1})
        self.assertEqual(st["facts"]["ctx_channel"], {"dropped": 1, "fired": 1, "by_mode": {"blender": 1},
                                                      "found": {"variables": 1}})
        self.assertEqual(st["facts"]["dead_output_key"], {"dropped": 1, "fired": 2, "by_mode": {"blender": 1},
                                                          "found": {"output_format": 1, "output_path": 1}})
        self.assertEqual({m["sid"] for m in self.meta()}, {"s3", "s4"})

    def test_a_piece_handing_values_on_in_ctx_values_is_kept(self):
        """ctx["values"] is the contract's since Nov 4 (blender_gate.CTX_CONTRACT): the contract fixtures' values pair
        (s1 hands its SETTINGS_s1 sizes on there, s2 reads them with a stand-in) gives two examples, and so does a
        piece that writes it through update() or setdefault; in the same record a piece that writes ctx["variables"]
        is still dropped by the backstop (ctx_channel, FACT_DROPS' order unchanged), which on a format-4 record is a
        hole in the gate, named in stats.json's facts_examples."""
        update = step("s3", content=f"```python\n{MARK}\nSETTINGS_s3 = {{\"lamp_height\": 2.5}}\n\n\n"
                                    f"def build_s3(ctx):\n    ctx[\"values\"].update(SETTINGS_s3)\n"
                                    f"    ctx[\"values\"].setdefault(\"lamp_energy\", 500.0)\n```\n" +
                                    handoff(provides='ctx["values"]["lamp_height"], ctx["values"]["lamp_energy"]'))
        variables = step("s4", content=f"```python\n{MARK}\nSETTINGS_s4 = {{\"rug_size\": 2.0}}\n\n\n"
                                       f"def build_s4(ctx):\n    ctx[\"variables\"] = dict(SETTINGS_s4)\n```\n" +
                                       handoff(provides="the rug's size"))
        recs = [record("n-blender-0001-00", [step("s1", content=CF.VALUES_S1), step("s2", content=CF.VALUES_S2),
                                             update, variables])]
        for st in recs[0]["rounds"][0]["steps"][:3]:
            self.assertEqual(BG.ctx_channel(T.piece_code(st["candidates"][0]["content"])), [], st["sid"])
        self.assertEqual(B.FACT_DROPS, ("dep_claimed", "validator_warning", "unchecked_code", "ctx_channel",
                                        "dead_output_key"))
        st = self.build(recs)
        self.assertEqual((st["kept"], st["dropped"]), (3, {"ctx_channel": 1}))
        self.assertEqual({m["sid"] for m in self.meta()}, {"s1", "s2", "s3"})
        self.assertEqual({m["format"] for m in self.meta()}, {T.DATAGEN_FORMAT})  # 6 since the fifth smoke
        self.assertEqual(st["facts"]["ctx_channel"]["found"], {"variables": 1})
        self.assertEqual(st["facts_examples"], {"ctx_channel": ["n-blender-0001-00 r1 s4"]})

    def test_a_step_that_sets_the_output_path_itself_keeps_its_piece(self):
        """dead_output_key gets the round's plan step from the build (plan_step): a step that asks to set the output
        path and format, and no render or save of Chimera, keeps a piece that keeps them in SETTINGS_sN and applies
        them (the first run's n-blender-0002-02 s5); the same piece for a step that asks Chimera to render, or one
        whose words never speak of the output, is dropped; and reading a ctx key the contract doesn't have drops
        the reader (X27's ctx.get("variables"))."""
        def code(sid, more=""):
            return (f"```python\n{MARK}\nSETTINGS_{sid} = {{\"output_path\": \"//forest_clearing\", "
                    f"\"output_format\": \"PNG\"}}\n\n\ndef build_{sid}(ctx):\n    s = SETTINGS_{sid}\n"
                    f"    ctx[\"scene\"].render.filepath = s[\"output_path\"]\n"
                    f"    ctx[\"scene\"].render.image_settings.file_format = s[\"output_format\"]\n{more}```\n")
        words = {"s1": "Finally, set the output filepath to \"//forest_clearing\" and image format to PNG.",
                 "s2": "Set the output filepath to //forest_clearing and render the image to //forest.png.",
                 "s3": "Add the light and the camera. No other code should be generated here.",
                 "s4": "Set the output filepath to //forest_clearing and image format to PNG."}
        plan = {"steps": [{"id": sid, "title": "Render settings", "kind": "blender", "depends_on": [],
                           "instructions": text + " " + MARK} for sid, text in words.items()]}
        steps = [step(sid, content=code(sid)) for sid in ("s1", "s2", "s3")]
        steps.append(step("s4", content=code("s4", '    n = ctx.get("variables", {}).get("n", 1)\n')))
        st = self.build([record("n-blender-0002-02", steps, plan=plan)])
        self.assertEqual({m["sid"] for m in self.meta()}, {"s1"})
        self.assertEqual(st["dropped"], {"dead_output_key": 2, "ctx_channel": 1})
        self.assertEqual(st["facts"]["dead_output_key"]["found"], {"output_path": 2})  # a format it applies isn't dead
        self.assertEqual(st["facts"]["ctx_channel"]["found"], {"variables": 1})
        self.assertIsNone(B.plan_step(record("n-blender-0002-02", steps), {"round": 1, "sid": "s1", "variant": None}))

    def test_the_facts_filters_order(self):
        """fact_drops gives every filter that fires, in FACT_DROPS' order, each with what it found; the build drops by
        the first. Stubbed here, so the order is build's own; the filters' rules are tested in their modules."""
        msgs = [{"role": "user", "content": MARK}, {"role": "assistant", "content": piece("s1")}]
        item = {"verdict": {"issues": [{"code": "uses_undeclared"}]}, "gate": {"parse": [{"path": "a.ps1"}]}}
        with mock.patch.object(DH, "check", return_value={"reasons": ["dep_unlisted", "dep_claimed:s2"]}), \
                mock.patch.object(LC, "build_drop", return_value="unchecked_code") as drop, \
                mock.patch.object(LC, "unchecked_code", return_value=[("a.ps1", "PowerShell")]), \
                mock.patch.object(BG, "ctx_channel", return_value=["settings"]), \
                mock.patch.object(BG, "dead_output_key", return_value=["output_path"]):
            got = B.fact_drops(msgs, {"mode": "blender", "sid": "s1", "unverified": True}, item)
            self.assertEqual(drop.call_args.args[2:], ([{"path": "a.ps1"}],))  # the kept gate's parse
            self.assertEqual([r for r, _ in B.fact_drops(msgs, {"mode": "files", "sid": "s1"}, None)],
                             ["dep_claimed", "unchecked_code"])  # Blender's facts for Blender only; no item: no verdict
        self.assertEqual(got, [("dep_claimed", ["dep_claimed:s2", "dep_unlisted"]),
                               ("validator_warning", ["uses_undeclared"]),
                               ("unchecked_code", [("a.ps1", "PowerShell")]), ("ctx_channel", ["settings"]),
                               ("dead_output_key", ["output_path"])])
        self.assertEqual([r for r, _ in got], list(B.FACT_DROPS))

    def test_published_only_after_the_last_check(self):
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [record("n-blender-0001-00", [step("s1")])])
        with mock.patch.object(B, "check_file", return_value=(0, "no overlap with the eval sets in 1 lines")):
            st = B.build(self.data, {"name": "test"}, index=self.index)
        self.assertTrue(st["published"])
        self.assertEqual(len(C.read_jsonl(os.path.join(self.data, "sft", "train.jsonl"))), 1)
        self.assertFalse(os.path.exists(os.path.join(self.data, "sft", "staging")))
        with mock.patch.object(B, "check_file", return_value=(1, "line 1: mark:test-fixture (100%)")):
            with self.assertRaises(B.OverlapFound):
                B.build(self.data, {"name": "test"}, index=self.index)
        self.assertFalse(os.path.exists(os.path.join(self.data, "sft", "train.jsonl")))
        self.assertTrue(os.path.exists(os.path.join(self.data, "sft", "flagged", "OVERLAP.txt")))
        self.assertIn("Not published", read(os.path.join(self.data, "sft", "STATS.md")))


if __name__ == "__main__":
    unittest.main()
