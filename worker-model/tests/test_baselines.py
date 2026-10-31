"""run_baselines.sh, runner/baselines.py and runner/report.py, against the mock Ollama and a fake Blender.

TEST FIXTURES ONLY, NEVER TRAINING DATA: the plans below are Claude-written test text (each summary carries the mark).
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import types
import unittest

from tests import _paths  # noqa: F401
from tests import contract_fixtures as F
from tests.runner_fakes import FakeBlender, MockOllamaCase
from runner import baselines, common, mock_ollama, report, step_eval, task_eval

import evalset
from contract.goport import clean_plan

ES = evalset.load()
MARK = F.MARK


def plan(title, kind, steps):
    return clean_plan({"title": title, "kind": kind, "summary": f"{title} in {len(steps)} steps. {MARK}",
                       "steps": [{"id": "s%d" % (i + 1), "title": t, "kind": k, "instructions": ins}
                                 for i, (t, k, ins) in enumerate(steps)]})


PY_PLAN = plan("Number tool", "code", [("Parse", "code", "Parse numbers from a string."),
                                       ("Sum", "code", "Sum the parsed numbers.")])
FILES_PLAN = plan("Web server", "code", [("Server", "code", "Write src/server.js, a small Node.js server.")])
PROSE_PLAN = plan("Tea notes", "research", [("Sources", "research", "List what is known."),
                                            ("Write-up", "writing", "Write the notes up.")])


def write_frozen(d, plans):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "plans.json"), "w", encoding="utf-8") as f:
        json.dump({"version": ES.version, "canary": evalset.CANARY, "note": "EVAL ONLY (test)",
                   "items": [{"id": t, "planner_model": "mock:latest", "plan": p} for t, p in plans.items()]}, f)


class T1Tests(MockOllamaCase):
    def test_t1_tasks_alternate_kinds_quick_first(self):
        d = os.path.join(self.tmp, "frozen")
        write_frozen(d, {"bw-02": F.BLENDER_PLAN, "bl-03": F.BLENDER_PLAN, "bw-01": F.BLENDER_PLAN,
                         "code-02": PY_PLAN, "code-01": PY_PLAN, "code-03": FILES_PLAN, "res-01": PROSE_PLAN})
        self.assertEqual([baselines.task_kind(p) for p in (F.BLENDER_PLAN, PY_PLAN, FILES_PLAN, PROSE_PLAN)],
                         ["blender", "python", "files", None])
        # the quick subset's tasks first within each kind (bw-01, bl-03; code-01), the kinds alternated; multi-file
        # and prose plans left out
        self.assertEqual(baselines.t1_tasks(ES, d), ["bw-01", "code-01", "bl-03", "code-02", "bw-02"])
        self.assertEqual(baselines.t1_tasks(ES, d, max_blender=1, max_code=1), ["bw-01", "code-01"])
        self.assertEqual(baselines.t1_tasks(ES, os.path.join(self.tmp, "none")), [])

    def test_unload_except_keeps_what_it_is_told(self):
        mock_ollama.Handler.loaded = ["gpt-oss:120b", "qwen3.8:27b", "hydra:1.0"]
        client = common.Ollama(self.url, 30)
        gone = baselines.unload_except(client, ["qwen3.8:27b"], wait=5)
        self.assertEqual(gone, ["gpt-oss:120b", "hydra:1.0"])
        self.assertEqual(sorted(b["model"] for b in self.requests("/api/generate")), ["gpt-oss:120b", "hydra:1.0"])
        self.assertTrue(all(b["keep_alive"] == 0 for b in self.requests("/api/generate")))
        self.assertEqual(mock_ollama.Handler.loaded, ["qwen3.8:27b"])
        self.assertEqual(baselines.unload_except(client, ["qwen3.8"], wait=1), ["qwen3.8:27b"])  # ":latest" assumed


class ReportTests(MockOllamaCase):
    def step(self, model, samples, tag="baseline", cases=("w2-01", "w4f-08"), think="unset"):
        argv = ["--model", model, "--host", self.url, "--out", os.path.join(self.tmp, "runs"), "--prompt", "contract",
                "--samples", str(samples), "--tag", tag, "--think", think]
        for c in cases:
            argv += ["--case", c]
        code, err = self.quiet(step_eval.main, argv, blender=FakeBlender())
        self.assertEqual(code, 0, err)

    def test_report_collects_step_runs_the_base_rule_and_t1(self):
        self.step("qwen3:14b", 2)
        self.step("gemma4:12b-it-q4_K_M", 1)
        self.step("qwen3:8b", 1, tag="smoke")  # another tag: not counted
        for arm in ("A", "B"):
            code, err = self.quiet(task_eval.main, ["--arm", arm, "--case", "w2-01", "--workers", "mock:latest",
                                                    "--combine-model", "mock:combine", "--host", self.url, "--tag",
                                                    "baseline-t1-c1", "--out", os.path.join(self.tmp, "tasks")],
                                   blender=FakeBlender())
            self.assertEqual(code, 0, err)
        out = os.path.join(self.tmp, "BASELINES.md")
        code, err = self.quiet(report.main, ["--runs", os.path.join(self.tmp, "runs"), "--task-runs",
                                             os.path.join(self.tmp, "tasks"), "--frozen", os.path.join(self.tmp, "fz"),
                                             "--out", out])
        self.assertEqual(code, 0, err)
        with open(out, encoding="utf-8") as f:
            md = f.read()
        self.assertIn("EVAL ONLY", md)
        rows = [l for l in md.split("\n") if l.startswith("| qwen3:14b | contract") or l.startswith("| gemma4")]
        self.assertEqual(len(rows), 2, md)
        self.assertIn("| 2 (prose 1) |", rows[0])
        self.assertNotIn("| qwen3:8b |", md)  # the smoke run
        self.assertIn("Not run yet: qwen3:14b today", md)
        # the base-model rule: paired on the samples both have (w2-01 sample 0 and the prose case), probes flagged
        self.assertIn("PROBES STILL NEEDED", md)
        self.assertIn("**Probes still needed: the rule can't pick the base yet.**", md)
        base = md.split("## The base-model rule's inputs")[1].split("## T1")[0]
        self.assertIn("| W2-W4 | qwen3:14b | 2 |", base)
        self.assertIn("| W2-W4 | gemma4:12b-it-q4_K_M | 2 |", base)
        self.assertIn("W2-W4 strict 5.2.2: Gemma 1/1, qwen3:14b 1/1: +0.0 points (Gemma ahead or level)", base)
        self.assertIn("| W1 | not both run yet |", base)
        # T1, merged per arm, and the paired gate line
        t1 = md.split("## T1")[1]
        self.assertIn("| A | today, mock:latest, combine | 1 |", t1)
        self.assertIn("| B | contract, mock:latest, join | 1 |", t1)
        self.assertIn("B against A on the 1 tasks both ran", t1)
        self.assertIn("Nothing frozen yet", md)

    def test_thinking_off_runs_are_kept_apart(self):
        self.step("qwen3:14b", 1)
        self.step("gemma4:12b-it-q4_K_M", 1)
        self.step("qwen3:14b", 1, tag="baseline-nothink", think="false")
        self.step("gemma4:12b-it-q4_K_M", 2, tag="baseline-nothink", think="false")
        sent = [b for b in self.requests() if b["messages"][-1]["content"] != "Reply with OK."]
        self.assertEqual(sorted(str(b.get("think", "unset")) for b in sent).count("False"), 2 + 3)
        out = os.path.join(self.tmp, "BASELINES.md")
        code, err = self.quiet(report.main, ["--runs", os.path.join(self.tmp, "runs"), "--task-runs",
                                             os.path.join(self.tmp, "tasks"), "--frozen", os.path.join(self.tmp, "fz"),
                                             "--out", out])
        self.assertEqual(code, 0, err)
        with open(out, encoding="utf-8") as f:
            md = f.read()
        # the thinking-off runs didn't replace the think-unset rows (the latest run per key, now with the setting)
        stage_a = md.split("## Step level: the quick subset's W2, W3 and W4 cases (stage a)")[1].split("## ")[0]
        self.assertIn("| qwen3:14b | contract | 1 (prose 1) |", stage_a)
        self.assertIn("| gemma4:12b-it-q4_K_M | contract | 1 (prose 1) |", stage_a)
        stage_g = md.split("## Step level: the base candidates with thinking off, W2-W4 (stage g)")[1].split("## ")[0]
        self.assertIn("| gemma4:12b-it-q4_K_M | contract | 2 (prose 1) |", stage_g)
        self.assertNotIn("Not run yet", stage_g)
        base = md.split("## The base-model rule's inputs")[1].split("## T1")[0]
        off = base.split("### Thinking off")[1].split("### Think unset")[0]
        unset = base.split("### Think unset")[1]
        self.assertIn("| W2-W4 | qwen3:14b | 2 |", off)  # paired: w2-01 sample 0 and the prose case
        self.assertIn("W2-W4 strict 5.2.2: Gemma 1/1, qwen3:14b 1/1: +0.0 points (Gemma ahead or level)", off)
        self.assertIn("W2-W4 strict + scene 5.2.2: Gemma 0/1, qwen3:14b 0/1:", off)
        self.assertIn("| W2-W4 | qwen3:14b | 2 |", unset)
        self.assertEqual(report.think_key({"think": False}), "off")
        self.assertEqual(report.think_key({"think": "unset"}), "unset")
        self.assertEqual(report.think_key({}), "unset")
        with open(glob.glob(os.path.join(self.tmp, "runs", "*nothink", "meta.json"))[0], encoding="utf-8") as f:
            meta = json.load(f)
        self.assertIs(meta["think"], False)
        self.assertTrue(any('"think": false' in d for d in meta["differences_from_chimera"]))

    def test_paired_and_tags(self):
        a = [{"id": "x", "sample": 0}, {"id": "x", "sample": 1}, {"id": "y", "sample": 0}]
        b = [{"id": "x", "sample": 0}, {"id": "y", "sample": 0}, {"id": "z", "sample": 0}]
        pa, pb = report.paired(a, b)
        self.assertEqual(([(r["id"], r["sample"]) for r in pa], [(r["id"], r["sample"]) for r in pb]),
                         ([("x", 0), ("y", 0)], [("x", 0), ("y", 0)]))
        self.assertEqual(report.run_tag("/r/20261029-230415-qwen3-4b-today-smoke", {"prompt": "today"}), "smoke")
        self.assertEqual(report.run_tag("/r/20261029-230529-A-qwen3-8b-smoke", {"workers": "qwen3:8b"}), "smoke")
        self.assertEqual(report.run_tag("/r/x", {"tag": "baseline"}), "baseline")
        self.assertEqual(report.part_group({"parts": ["w2", "w3"]}), "W2-W4")
        self.assertEqual(report.part_group({"cases": ["bw-01/s1", "bw-01/s3"]}), "W1")


SCRIPT = os.path.join(_paths.HERE, "run_baselines.sh")
SCRIPT_SETTINGS = {"DRY_RUN", "STAGES", "MODELS", "SAMPLES", "CASES", "TAG", "BASE", "RUNS", "TASK_RUNS", "FROZEN",
                   "REPORT", "T1_CHUNK", "T1_BLENDER", "T1_CODE", "ARMS", "COMBINE", "REVIEW", "STOP_AT", "NO_BLENDER",
                   "SKIP_TESTS", "BASES", "NOTHINK_SAMPLES"}


@unittest.skipUnless(shutil.which("bash") and shutil.which("curl"), "needs bash and curl")
class ScriptTests(MockOllamaCase):
    """The script itself, against the mock (NO_BLENDER, SKIP_TESTS): runs, the done list, STOP, unloading."""

    def script(self, **env):
        exe = os.path.join(self.tmp, "chimera")
        with open(exe, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(exe, 0o755)
        # the script's own settings from the environment (the script runs these tests itself) don't reach it
        e = {k: v for k, v in os.environ.items() if k not in SCRIPT_SETTINGS}
        e.update(OLLAMA_HOST=self.url, MODELS="mock:latest", CASES="w2-01", STAGES="a", TAG="t",
                 BASE=os.path.join(self.tmp, "bl"), RUNS=os.path.join(self.tmp, "runs"),
                 REPORT=os.path.join(self.tmp, "B.md"), SKIP_TESTS="1", NO_BLENDER="1", CHIMERA_BIN=exe,
                 SAMPLES="mock:latest=1", FROZEN=os.path.join(self.tmp, "frozen-none"))
        e.update(env)
        p = subprocess.run(["bash", SCRIPT], env=e, capture_output=True, text=True, timeout=300)
        return p.returncode, p.stdout + p.stderr

    def done(self):
        with open(os.path.join(self.tmp, "bl", "done.txt"), encoding="utf-8") as f:
            return [l.split("\t") for l in f.read().splitlines()]

    def chats(self):
        return [b for b in self.requests() if b["messages"][-1]["content"] != "Reply with OK."]

    def test_runs_resume_and_stop(self):
        stop = os.path.join(self.tmp, "bl", "STOP")
        mock_ollama.Handler.loaded = ["other:1"]

        def touch_stop(system, user, body):  # someone touches STOP while the first run is going
            if user != "Reply with OK.":
                open(stop, "w").close()
            return None
        mock_ollama.Handler.extra = [touch_stop]
        code, out = self.script()
        self.assertEqual(code, 0, out)
        self.assertIn('STOP file found: stopping before "a|step|w2-w4|w2-01|mock:latest|contract', out)
        self.assertFalse(os.path.exists(stop))  # removed, so a rerun carries on
        d = self.done()
        self.assertEqual([x[0] for x in d], ["a|step|w2-w4|w2-01|mock:latest|today|samples=1|t"])
        self.assertTrue(d[0][4].endswith("-mock-latest-today-t"), d[0])
        self.assertIn({"model": "other:1", "keep_alive": 0, "stream": False}, self.requests("/api/generate"))
        self.assertEqual(len(self.chats()), 1)
        mock_ollama.Handler.extra = []
        code, out = self.script()
        self.assertEqual(code, 0, out)
        self.assertIn("skip (done before): a|step|w2-w4|w2-01|mock:latest|today", out)
        self.assertEqual(len(self.done()), 2)
        self.assertEqual(len(self.chats()), 2)  # only the contract run asked anything
        self.assertRegex(out, r"done: a\|step\|w2-w4\|w2-01\|mock:latest\|contract\|samples=1\|t in \d+ s \(estimate")
        code, out = self.script()  # everything done: nothing asked
        self.assertEqual((code, len(self.chats())), (0, 2), out)
        with open(os.path.join(self.tmp, "bl", "baselines.log"), encoding="utf-8") as f:
            log = f.read()
        self.assertIn("== stage a: step_eval", log)
        self.assertIn("== stage a finished in", log)
        with open(os.path.join(self.tmp, "B.md"), encoding="utf-8") as f:
            self.assertIn("| mock:latest | contract |", f.read())

    def test_stage_g_sends_think_false_for_the_bases(self):
        code, out = self.script(STAGES="g", BASES="mock:latest", NOTHINK_SAMPLES="1")
        self.assertEqual(code, 0, out)
        self.assertEqual([x[0] for x in self.done()],
                         ["g|step|w2-w4|w2-01|mock:latest|contract|think=false|samples=1|t"])
        self.assertTrue(self.done()[0][4].endswith("-mock-latest-contract-t-nothink"), self.done()[0])
        self.assertIn("stage g: no W1 steps", out)
        chats = self.chats()
        self.assertEqual([b.get("think") for b in chats], [False])
        with open(os.path.join(self.tmp, "B.md"), encoding="utf-8") as f:
            md = f.read()
        self.assertIn("| mock:latest | contract |", md.split("thinking off, W2-W4 (stage g)")[1].split("## ")[0])

    def test_settings_list_matches_the_script(self):
        import re
        with open(SCRIPT, encoding="utf-8") as f:
            names = set(re.findall(r"(?m)^([A-Z_0-9]+)=\$\{\1:", f.read()))
        self.assertTrue(names and names <= SCRIPT_SETTINGS, names - SCRIPT_SETTINGS)

    def test_dry_run_calls_no_model(self):
        code, out = self.script(DRY_RUN="1", STAGES="a,b,c,d,e,f")
        self.assertEqual(code, 0, out)
        self.assertIn("(dry run) a|step|w2-w4|w2-01|mock:latest|today", out)
        self.assertIn("(dry run) b|freeze|plans", out)
        self.assertIn("stage d skipped", out)
        self.assertEqual(self.requests(), [])
        self.assertEqual(self.requests("/api/generate"), [])
        self.assertEqual(self.done(), [])


class RescoreTests(MockOllamaCase):
    step = ReportTests.step

    def test_rescore_keeps_blender_results_for_unchanged_scripts(self):
        from runner import rescore
        self.step("qwen3:14b", 2)
        run = glob.glob(os.path.join(self.tmp, "runs", "*"))[0]
        with open(os.path.join(run, "raw.jsonl"), encoding="utf-8") as f:
            before = [json.loads(l) for l in f]
        self.assertTrue(before[0]["score"]["blender"]["script_sha"])
        # one record's stored results are for another script: that one runs again; an older record with no sha is
        # rebuilt and matched on its run kind, lines and notes
        before[0]["score"]["blender"]["script_sha"] = "0" * 20
        del before[1]["score"]["blender"]["script_sha"]
        with open(os.path.join(run, "raw.jsonl"), "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r) + "\n" for r in before)
        fake = FakeBlender()
        old_backup, rescore.BACKUP = rescore.BACKUP, os.path.join(self.tmp, "backup")
        a = types.SimpleNamespace(frozen=os.path.join(self.tmp, "fz"), dry_run=False, note="a test")
        try:
            self.quiet(rescore.rescore_run, run, ES, a, fake, None, "20261030-000000")
            self.assertEqual(len([c for c in fake.calls if c[0] == "check"]), 1)  # only the record with another sha
            # again: everything has its sha now, so nothing runs; and a backup that exists is never overwritten
            again = FakeBlender()
            self.quiet(rescore.rescore_run, run, ES, a, again, None, "20261030-000001")
            self.assertEqual(again.calls, [])
            # the dry run agrees: nothing to run again (it counted every record with a sha as a re-run, Oct 30)
            dry = types.SimpleNamespace(frozen=a.frozen, dry_run=True, note="")
            _, err = self.quiet(rescore.rescore_run, run, ES, dry, None, None, "20261030-000009")
            self.assertIn("Blender would run again for 0, kept for 2; 0 changed", err)
            with self.assertRaises(SystemExit):
                self.quiet(rescore.rescore_run, run + os.sep, ES, a, again, None, "20261030-000001")
        finally:
            rescore.BACKUP = old_backup
        with open(os.path.join(run, "raw.jsonl"), encoding="utf-8") as f:
            after = [json.loads(l) for l in f]
        self.assertEqual([(r["id"], r["sample"], r["reply"]) for r in after],
                         [(r["id"], r["sample"], r["reply"]) for r in before])
        self.assertEqual([r["score"]["contract"] for r in after], [r["score"]["contract"] for r in before])
        self.assertEqual(after[1]["score"]["blender"]["check"], before[1]["score"]["blender"]["check"])
        with open(os.path.join(run, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(len(meta["rescored"]), 2)
        self.assertIn("rescored by runner/rescore.py (a test)", meta["rescored"][0])
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "backup", "20261030-000000", os.path.basename(run),
                                                    "raw.jsonl")))
        with open(os.path.join(run, "summary.json"), encoding="utf-8") as f:
            self.assertIn("strict_scene_5.2.2", json.load(f)["summary"]["all"])
        self.assertEqual(rescore.changes(before[0]["score"], before[0]["score"]), [])
        worse = json.loads(json.dumps(before[0]["score"]))
        worse["blender"]["check"]["5.2.2"]["outcome"] = "failed"
        self.assertIn("outcome 5.2.2 passed->failed", rescore.changes(before[0]["score"], worse))


class GapWordsTests(unittest.TestCase):
    def test_the_verdict_follows_the_exact_gap(self):
        # before Oct 30 every gap of -5 or more said "(within 5)", +40.5 included, and gaps came from rounded rates
        self.assertEqual(report.gap_words(40.48), "+40.5 points (Gemma ahead or level)")
        self.assertEqual(report.gap_words(0.0), "+0.0 points (Gemma ahead or level)")
        self.assertEqual(report.gap_words(-3.333), "-3.3 points (Gemma behind, by no more than 5)")
        self.assertEqual(report.gap_words(-5.0), "-5.0 points (Gemma behind, by no more than 5)")
        self.assertEqual(report.gap_words(-6.7), "-6.7 points (Gemma more than 5 points behind)")
        self.assertEqual(report.exact_rate([{"x": True}, {"x": False}, {"x": None}], lambda r: r["x"]), (1, 2))
        self.assertIsNone(report.exact_rate([{"x": None}], lambda r: r["x"]))
        # exactly 5 points behind is within the rule (in floats, 700/60 - 1000/60 came out below -5)
        from fractions import Fraction
        self.assertEqual(report.gap_words(Fraction(100 * 7, 60) - Fraction(100 * 10, 60)),
                         "-5.0 points (Gemma behind, by no more than 5)")
        # just past -5, it shows enough decimals to see why the verdict says so
        self.assertEqual(report.gap_words(Fraction(-600, 119)), "-5.04 points (Gemma more than 5 points behind)")
        self.assertEqual(report.gap_words(Fraction(-499, 100)), "-4.99 points (Gemma behind, by no more than 5)")

    def test_pairs_mcnemar_and_the_case_bootstrap(self):
        a = [{"id": "c1", "sample": 0, "x": True}, {"id": "c1", "sample": 1, "x": True},
             {"id": "c2", "sample": 0, "x": False}, {"id": "c3", "sample": 0, "x": None}]
        b = [{"id": "c1", "sample": 0, "x": False}, {"id": "c1", "sample": 1, "x": True},
             {"id": "c2", "sample": 0, "x": None}, {"id": "c3", "sample": 0, "x": True}]
        # a pair counts only where the rate counts both sides: c2 and c3 drop out
        ra, rb, n, pairs = report.pair_rate(a, b, lambda r: r["x"])
        self.assertEqual((ra, rb, n), ((2, 2), (1, 2), 2))
        self.assertEqual(pairs, [("c1", True, False), ("c1", True, True)])
        self.assertEqual(report.mcnemar_p(0, 0), 1.0)
        self.assertAlmostEqual(report.mcnemar_p(5, 0), 0.0625)
        self.assertAlmostEqual(report.mcnemar_p(3, 3), 1.0)
        level = [("c%d" % i, i % 2 == 0, i % 2 == 0) for i in range(10)]
        self.assertEqual(report.case_bootstrap(level, rounds=200), (0.0, 0.0, 1.0))
        worse = [("c%d" % i, False, True) for i in range(10)]  # Gemma loses every pair: always -100
        self.assertEqual(report.case_bootstrap(worse, rounds=200), (-100.0, -100.0, 0.0))
        mixed = [("c%d" % i, i < 3, i < 5) for i in range(20)]
        self.assertEqual(report.case_bootstrap(mixed, rounds=500), report.case_bootstrap(mixed, rounds=500))  # seeded
        lo, hi, p = report.case_bootstrap(mixed, rounds=2000)
        self.assertTrue(lo < -10 < hi <= 0, (lo, hi))
        line = report.gap_line("W2-W4", "strict 5.2.2", a, b, lambda r: r["x"])
        self.assertTrue(line.startswith("W2-W4 strict 5.2.2: Gemma 2/2, qwen3:14b 1/2: +50.0 points (Gemma ahead or "
                                        "level); one-sided pairs 1 Gemma, 0 qwen3:14b (McNemar p 1.00); 90% interval"),
                        line)


if __name__ == "__main__":
    unittest.main()
