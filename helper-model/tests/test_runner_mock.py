"""The runner end to end against runner/mock_ollama.py: what it sends, and what it writes."""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from tests import _paths  # noqa: F401
from helper import evalset, prompts
from runner import mock_ollama, report, run_eval


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hm-runner-")
        self.log = os.path.join(self.tmp, "requests.jsonl")
        self.srv, self.url = mock_ollama.serve(0, self.log)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_eval(self, *extra):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = run_eval.main(["--model", "mock:latest", "--host", self.url, "--out", os.path.join(self.tmp, "runs"), *extra])
        return code, err.getvalue()

    def requests(self, path="/api/chat"):
        with open(self.log, encoding="utf-8") as f:
            return [json.loads(l)["body"] for l in f if json.loads(l)["path"] == path]

    def run_dir(self):
        runs = os.listdir(os.path.join(self.tmp, "runs"))
        self.assertEqual(len(runs), 1)
        return os.path.join(self.tmp, "runs", runs[0])

    def test_full_run_writes_results_and_sends_chimeras_requests(self):
        code, err = self.run_eval("--jobs", "planner,reviewer,gate,embed")
        self.assertEqual(code, 0, err)
        d = self.run_dir()
        for name in ("meta.json", "raw.jsonl", "summary.json", "summary.md"):
            self.assertTrue(os.path.exists(os.path.join(d, name)), name)
        with open(os.path.join(d, "summary.json"), encoding="utf-8") as f:
            s = json.load(f)["summary"]
        es = evalset.load()
        want = {"planner": len(es.planner_cases()), "reviewer": len(es.reviews), "gate": len(es.gate_pairs())}
        self.assertEqual({j: s[j]["n"] for j in want}, want)
        self.assertLess(s["reviewer"]["chimera_ok"], 1.0)  # the mock's float scores are rejected
        self.assertGreater(s["gate"]["chimera_ok"], 0.5)
        self.assertIsNotNone(s["embed"]["gate_auc"])
        bodies = self.requests()
        by = {"planner": [], "reviewer": [], "gate": []}
        for b in bodies:
            sysmsg = b["messages"][0]["content"]
            for job, p in (("planner", prompts.HYDRA_PLANNER_PROMPT), ("reviewer", prompts.HYDRA_REVIEW_PROMPT), ("gate", prompts.HEAD_GATE_PROMPT)):
                if sysmsg == p:
                    by[job].append(b)
        self.assertEqual({k: len(v) for k, v in by.items()}, want)
        for job, bs in by.items():
            for b in bs:
                self.assertTrue(b["stream"])
                self.assertEqual(b["keep_alive"], "15m")
                self.assertNotIn("think", b)
                self.assertEqual(b["options"]["seed"], 7)
                self.assertEqual(b["options"]["num_ctx"], 8192)
                self.assertEqual([m["role"] for m in b["messages"]], ["system", "user"])
                if job == "gate":
                    self.assertEqual(b["options"]["temperature"], 0)
                    self.assertEqual(b["format"], json.loads(prompts.HEAD_GATE_SCHEMA))
                else:
                    self.assertNotIn("temperature", b["options"])
                    self.assertEqual(b["format"], "json")
        replan = [b for b in by["planner"] if "The previous attempt produced this result:" in b["messages"][1]["content"]]
        self.assertEqual(len(replan), sum(1 for p in es.planner_cases() if p.get("prior")))
        with_history = [b for b in by["planner"] if b["messages"][1]["content"].startswith("Earlier in this chat")]
        self.assertEqual(len(with_history), sum(1 for p in es.planner_cases() if p.get("history")))
        self.assertEqual(len(self.requests("/api/generate")), 1)  # unloaded afterwards
        with open(os.path.join(d, "summary.md"), encoding="utf-8") as f:
            md = f.read()
        for heading in ("## Planner", "## Reviewer", "## Head gate", "## Zero-shot embedding check"):
            self.assertIn(heading, md)

    def test_seed_and_think_switches(self):
        code, err = self.run_eval("--jobs", "gate", "--limit", "2", "--seed", "none", "--think", "false")
        self.assertEqual(code, 0, err)
        for b in self.requests():
            if b["messages"][0]["content"] == prompts.HEAD_GATE_PROMPT:
                self.assertNotIn("seed", b["options"])
                self.assertIs(b["think"], False)

    def test_temperature_switch(self):
        code, err = self.run_eval("--jobs", "planner,reviewer,gate", "--limit", "2", "--temperature", "0.2")
        self.assertEqual(code, 0, err)
        temps = {}
        for b in self.requests():
            job = {prompts.HYDRA_PLANNER_PROMPT: "planner", prompts.HYDRA_REVIEW_PROMPT: "reviewer",
                   prompts.HEAD_GATE_PROMPT: "gate"}.get(b["messages"][0]["content"])
            if job:
                temps.setdefault(job, set()).add(b["options"].get("temperature"))
        self.assertEqual(temps, {"planner": {0.2}, "reviewer": {0.2}, "gate": {0}})  # the gate keeps Chimera's 0
        d = self.run_dir()
        self.assertTrue(os.path.basename(d).endswith("-t0.2"), d)
        with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["temperature"], "0.2")
        self.assertIn("temperature=0.2 (planner, reviewer)", meta["differences_from_chimera"])
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_eval("--jobs", "gate", "--temperature", "hot")

    def test_missing_model_is_a_clear_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = run_eval.main(["--model", "nope:1b", "--host", self.url, "--out", os.path.join(self.tmp, "runs")])
        self.assertEqual(code, 2)
        self.assertIn("ollama pull nope:1b", err.getvalue())

    def test_report_collects_runs(self):
        self.assertEqual(self.run_eval("--jobs", "planner,gate")[0], 0)
        out = os.path.join(self.tmp, "BASELINES.md")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(report.main(["--runs", os.path.join(self.tmp, "runs"), "--out", out]), 0)
        with open(out, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("| mock:latest |", text)
        self.assertIn("word rule only (no model)", text)

    def test_rescore_reproduces_the_summary(self):
        from runner import rescore
        self.assertEqual(self.run_eval("--jobs", "planner,reviewer,gate")[0], 0)
        d = self.run_dir()
        with open(os.path.join(d, "summary.json"), encoding="utf-8") as f:
            before = json.load(f)["summary"]
        rescore.rescore(d)
        with open(os.path.join(d, "summary.json"), encoding="utf-8") as f:
            after = json.load(f)["summary"]
        self.assertEqual(before, after)

    def test_rescore_to_current_only_when_requests_match(self):
        from runner import rescore
        old_dir, new_dir = os.path.join(self.tmp, "eval-old"), os.path.join(self.tmp, "eval-new")
        shutil.copytree(evalset.EVAL_DIR, old_dir, ignore=shutil.ignore_patterns("archive", "README.md"))
        self.assertEqual(self.run_eval("--jobs", "planner,gate", "--eval-dir", old_dir)[0], 0)
        d = self.run_dir()
        old_version = evalset.load(old_dir).version
        # A new version that changes only a label: the run moves over.
        shutil.copytree(old_dir, os.path.join(new_dir, "archive", old_version))
        for name in evalset.FILES:
            with open(os.path.join(old_dir, name), encoding="utf-8") as f:
                doc = json.load(f)
            doc["version"] = old_version + "-test"
            if name == "prompts.json":
                doc["items"][0]["planner"]["steps"] = [1, 8]
            with open(os.path.join(new_dir, name), "w", encoding="utf-8") as f:
                json.dump(doc, f)
        rescore.rescore(d, new_dir, to_current=True)
        with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["eval_version"], old_version + "-test")
        self.assertEqual(meta["rescored_from"], old_version)
        # A version that changes a prompt: refused.
        newer = os.path.join(self.tmp, "eval-newer")
        shutil.copytree(new_dir, newer)
        shutil.copytree(new_dir, os.path.join(newer, "archive", old_version + "-test"), ignore=shutil.ignore_patterns("archive"))
        for name in evalset.FILES:
            path = os.path.join(newer, name)
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
            doc["version"] = old_version + "-test2"
            if name == "prompts.json":
                doc["items"][0]["prompt"] += " Also add a README."
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f)
        with self.assertRaises(SystemExit):
            rescore.rescore(d, newer, to_current=True)

    def test_check_first_variant(self):
        def check_first(system, user, msgs, body, n):
            if system == prompts.HYDRA_REVIEW_PROMPT + run_eval.CHECK_FIRST_NOTE:
                if n % 2:
                    return json.dumps({"check": "Asked for X: done.", "done": True, "score": 90, "critique": ""})
                return json.dumps({"done": False, "check": "Asked for X: missing.", "score": 40, "critique": "Add X, which is missing."})
            return None
        mock_ollama.Handler.extra = [check_first]
        self.addCleanup(setattr, mock_ollama.Handler, "extra", [])
        code, err = self.run_eval("--jobs", "reviewer,gate", "--limit", "4", "--variant", "check-first")
        self.assertEqual(code, 0, err)
        d = self.run_dir()
        self.assertTrue(os.path.basename(d).endswith("-mock-latest-check-first"))
        bodies = self.requests()
        rev = [b for b in bodies if b["messages"][0]["content"].startswith(prompts.HYDRA_REVIEW_PROMPT)]
        gate = [b for b in bodies if b["messages"][0]["content"] == prompts.HEAD_GATE_PROMPT]
        self.assertEqual((len(rev), len(gate)), (4, 4))
        for b in rev:
            self.assertEqual(b["messages"][0]["content"], prompts.HYDRA_REVIEW_PROMPT + run_eval.CHECK_FIRST_NOTE)
            self.assertEqual(b["format"], run_eval.CHECK_FIRST_SCHEMA)
            self.assertEqual(list(b["format"]["properties"])[0], "check")
        for b in gate:  # only the reviewer is changed
            self.assertEqual(b["format"], json.loads(prompts.HEAD_GATE_SCHEMA))
        with open(os.path.join(d, "summary.json"), encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["meta"]["variant"], "check-first")
        self.assertTrue(any(x.startswith("variant=check-first") for x in doc["meta"]["differences_from_chimera"]))
        r = doc["summary"]["reviewer"]
        self.assertEqual(r["check_first"], 0.5)  # half the mock's replies put it second...
        self.assertEqual(r["valid"], 0.5)  # ...which the experiment counts as not strictly valid
        self.assertEqual(r["chimera_ok"], 1.0)  # though Chimera reads them all
        self.assertIsNotNone(r["check_chars_median"])
        with open(os.path.join(d, "summary.md"), encoding="utf-8") as f:
            self.assertIn("experiment: check-first", f.read())
        from runner import rescore
        rescore.rescore(d)  # re-scoring keeps the variant's rules
        with open(os.path.join(d, "summary.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["summary"]["reviewer"], r)
        # in the baselines it's a row of its own next to the model's normal run (smoke runs with --limit never count)
        self.assertEqual(self.run_eval("--jobs", "reviewer", "--variant", "check-first")[0], 0)
        self.assertEqual(self.run_eval("--jobs", "reviewer")[0], 0)
        out = os.path.join(self.tmp, "BASELINES.md")
        with contextlib.redirect_stdout(io.StringIO()):
            report.main(["--runs", os.path.join(self.tmp, "runs"), "--out", out])
        with open(out, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("| mock:latest [check-first] |", text)
        self.assertIn("| mock:latest |", text)

    def test_check_working_variant_sends_v3s_note(self):
        from datagen import teacher_prompts as tp
        code, err = self.run_eval("--jobs", "reviewer", "--limit", "2", "--variant", "check-working")
        self.assertEqual(code, 0, err)
        rev = [b for b in self.requests() if b["messages"][0]["content"].startswith(prompts.HYDRA_REVIEW_PROMPT)]
        self.assertEqual(len(rev), 2)
        for b in rev:
            self.assertEqual(b["messages"][0]["content"], prompts.HYDRA_REVIEW_PROMPT + tp.CHECK_NOTE3)
            self.assertEqual(b["format"], run_eval.CHECK_FIRST_SCHEMA)
        self.assertTrue(self.run_dir().endswith("-check-working"))

    def test_check_field_rules(self):
        from helper.validate import validate_review
        reply = json.dumps({"check": "fine", "done": True, "score": 90, "critique": ""})
        r = validate_review(reply)
        self.assertTrue(r.valid)  # allowed: Chimera ignores it
        self.assertTrue(r.chimera_ok)
        self.assertEqual(r.metrics, {"check_chars": 4, "check_first": True})
        self.assertTrue(validate_review(reply, require=("check",)).valid)
        plain = json.dumps({"done": True, "score": 90, "critique": ""})
        self.assertTrue(validate_review(plain).valid)
        self.assertFalse(validate_review(plain, require=("check",)).valid)
        self.assertFalse(validate_review(json.dumps({"check": 3, "done": True, "score": 90, "critique": ""})).valid)
        self.assertFalse(validate_review(json.dumps({"check": " ", "done": True, "score": 90, "critique": ""}), require=("check",)).valid)
        late = json.dumps({"done": True, "check": "fine", "score": 90, "critique": ""})
        self.assertTrue(validate_review(late).valid)
        self.assertFalse(validate_review(late, require=("check",)).valid)
        self.assertFalse(validate_review(json.dumps({"check": "x", "verdict": 1, "done": True, "score": 90, "critique": ""})).valid)

    def test_compare_puts_runs_side_by_side(self):
        from runner import compare
        self.assertEqual(self.run_eval("--jobs", "reviewer,gate", "--limit", "3")[0], 0)
        self.assertEqual(self.run_eval("--jobs", "reviewer,gate", "--limit", "3", "--seed", "none")[0], 0)
        runs = sorted(os.path.join(self.tmp, "runs", r) for r in os.listdir(os.path.join(self.tmp, "runs")))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(compare.main(runs), 0)
        text = out.getvalue()
        self.assertIn("## reviewer", text)
        self.assertIn("## gate", text)
        self.assertEqual(text.count("| **right** |"), 2)
        self.assertIn("| mock:latest | mock:latest |", text)

    def test_dry_run_calls_nothing(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_eval.main(["--model", "x", "--host", self.url, "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn('"keep_alive": "15m"', out.getvalue())
        self.assertFalse(os.path.exists(self.log))


if __name__ == "__main__":
    unittest.main()
