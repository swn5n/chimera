"""The data generator end to end against the mock Ollama, plus its pieces."""
import contextlib
import io
import json
import os
import random
import shutil
import tempfile
import unittest

from tests import _paths  # noqa: F401
from tests import datagen_mock
from datagen import run as dg_run
from datagen.common import Store
from datagen.plans import judge_plan
from datagen.results import drop_section, truncate
from helper.validate import VALIDATORS
from runner import mock_ollama
from tools import check_overlap

ARGS = ["--size", "tiny", "--teacher", "mock:teacher", "--workers", "mock:w1,mock:w2"]


class DatagenRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hm-datagen-")
        self.log = os.path.join(self.tmp, "requests.jsonl")
        self.srv, self.url = mock_ollama.serve(0, self.log)
        mock_ollama.Handler.extra = [datagen_mock.respond]
        self.data = os.path.join(self.tmp, "data")

    def tearDown(self):
        mock_ollama.Handler.extra = []
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_dg(self, *extra):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = dg_run.main(ARGS + ["--host", self.url, "--data-dir", self.data, *extra])
        return code, err.getvalue()

    def chat_calls(self):
        if not os.path.exists(self.log):
            return 0
        with open(self.log, encoding="utf-8") as f:
            return sum(1 for l in f if json.loads(l)["path"] == "/api/chat")

    def test_full_run_writes_valid_training_files_and_resumes(self):
        code, err = self.run_dg()
        self.assertEqual(code, 0, err)
        for name in ("seeds.jsonl", "sft/train.jsonl", "sft/valid.jsonl", "STATS.md", "classifier/gate.jsonl",
                     "classifier/kinds.jsonl", "review_items.jsonl", "RUN.json"):
            self.assertTrue(os.path.exists(os.path.join(self.data, name)), name)
        rows, metas = [], []
        for split in ("train", "valid"):
            with open(os.path.join(self.data, "sft", split + ".jsonl"), encoding="utf-8") as f:
                rows += [json.loads(l) for l in f]
            with open(os.path.join(self.data, "sft", split + ".meta.jsonl"), encoding="utf-8") as f:
                metas += [json.loads(l) for l in f]
        self.assertEqual(len(rows), len(metas))
        self.assertEqual({m["job"] for m in metas}, {"planner", "reviewer", "gate"})
        for r, m in zip(rows, metas):
            self.assertEqual(set(r), {"messages"})
            self.assertEqual([x["role"] for x in r["messages"]], ["system", "user", "assistant"])
            self.assertTrue(VALIDATORS[m["job"]](r["messages"][-1]["content"]).valid, r["messages"][-1]["content"])
        with open(os.path.join(self.data, "sft", "train.jsonl"), encoding="utf-8") as f:
            n_train = sum(1 for _ in f)
        groups_train = {m["group"] for m in metas[:n_train]}
        with open(os.path.join(self.data, "sft", "valid.meta.jsonl"), encoding="utf-8") as f:
            groups_valid = {json.loads(l)["group"] for l in f}
        self.assertFalse(groups_train & groups_valid)  # no seed or Head on both sides
        self.assertTrue(any(m.get("source") == "replan" for m in metas))
        self.assertEqual({m["use"] for m in metas if m["job"] == "gate"}, {True, False})
        self.assertEqual({m["done"] for m in metas if m["job"] == "reviewer"}, {True, False})
        self.assertTrue(any(m.get("variant") in ("truncated", "dropped_section", "teacher_flaw", "natural_cut") for m in metas))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_overlap.main([os.path.join(self.data, "sft", "train.jsonl")]), 0)
        calls = self.chat_calls()
        code, err = self.run_dg()  # resuming a finished run calls no model
        self.assertEqual(code, 0, err)
        self.assertEqual(self.chat_calls(), calls)

    def test_v2_stages_on_top_of_v1(self):
        from helper import prompts
        from helper.validate import validate_review
        from datagen import teacher_prompts as tp
        self.assertEqual(self.run_dg()[0], 0)  # v1 first
        with open(os.path.join(self.data, "sft", "train.jsonl"), encoding="utf-8") as f:
            v1_train = f.read()
        with open(os.path.join(self.data, "RUN.json"), encoding="utf-8") as f:
            v1_run = f.read()
        first = self.chat_calls()
        code, err = self.run_dg("--stages", "v2")
        self.assertEqual(code, 0, err)
        for name in ("seeds2.jsonl", "review_items2.jsonl", "sft-v2/train.jsonl", "sft-v2/valid.jsonl", "STATS-v2.md", "RUN-v2.json"):
            self.assertTrue(os.path.exists(os.path.join(self.data, name)), name)
        with open(os.path.join(self.data, "sft", "train.jsonl"), encoding="utf-8") as f:
            self.assertEqual(f.read(), v1_train)  # v1's files are left alone
        with open(os.path.join(self.data, "RUN.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), v1_run)
        rows, metas = [], []
        for split in ("train", "valid"):
            with open(os.path.join(self.data, "sft-v2", split + ".jsonl"), encoding="utf-8") as f:
                rows += [json.loads(l) for l in f]
            with open(os.path.join(self.data, "sft-v2", split + ".meta.jsonl"), encoding="utf-8") as f:
                metas += [json.loads(l) for l in f]
        self.assertEqual(len(rows), len(metas))
        self.assertEqual({m["job"] for m in metas}, {"planner", "reviewer", "gate"})
        for r, m in zip(rows, metas):
            sysmsg, target = r["messages"][0]["content"], r["messages"][-1]["content"]
            if m["job"] == "reviewer":
                self.assertEqual(sysmsg, prompts.HYDRA_REVIEW_PROMPT)  # Chimera's exact request, no check note
                self.assertEqual(m["source"], "review2")
                res = validate_review(target, require=("check",))
                self.assertTrue(res.valid, target)
                self.assertEqual(next(iter(json.loads(target))), "check")
                self.assertIsInstance(json.loads(target)["check"], str)
            elif m["job"] == "planner":
                self.assertEqual(sysmsg, prompts.HYDRA_PLANNER_PROMPT)  # no hint in the training example
                self.assertTrue(VALIDATORS["planner"](target).valid, target)
        self.assertTrue(any(m.get("source") == "plan2" and m.get("hinted") for m in metas))
        self.assertTrue(any(m.get("source") == "plan2" and m.get("new_seed") for m in metas))
        self.assertTrue(any(m.get("variant") == "teacher" for m in metas))
        self.assertTrue(any(str(m.get("variant", "")).startswith("flaw2_") for m in metas))
        self.assertEqual({m["done"] for m in metas if m["job"] == "reviewer"}, {True, False})
        with open(self.log, encoding="utf-8") as f:
            later = [json.loads(l)["body"] for l in f if json.loads(l)["path"] == "/api/chat"][first:]
        rv = [b for b in later if b["messages"][0]["content"].startswith(prompts.HYDRA_REVIEW_PROMPT)]
        self.assertTrue(rv)
        for b in rv:  # the teacher's copy: the check note and the key order
            self.assertEqual(b["messages"][0]["content"], prompts.HYDRA_REVIEW_PROMPT + tp.CHECK_NOTE)
            self.assertEqual(list(b["format"]["properties"]), ["check", "done", "score", "critique"])
        hinted = [b for b in later if b["messages"][0]["content"].startswith(prompts.HYDRA_PLANNER_PROMPT + tp.PLAN_HINT_INTRO)]
        self.assertTrue(hinted)
        workers = [b for b in later if b["model"] != "mock:teacher"]
        self.assertEqual(workers, [])  # v2 only asks the teacher
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_overlap.main([os.path.join(self.data, "sft-v2", "train.jsonl")]), 0)
        calls = self.chat_calls()
        code, err = self.run_dg("--stages", "v2")  # resuming a finished v2 run calls no model
        self.assertEqual(code, 0, err)
        self.assertEqual(self.chat_calls(), calls)
        code, err = self.run_dg("--stages", "build2")
        self.assertEqual(code, 0, err)

    def test_v3_stages_on_top_of_v2(self):
        from helper import prompts
        from helper.validate import validate_review
        from datagen import teacher_prompts as tp
        self.assertEqual(self.run_dg()[0], 0)
        self.assertEqual(self.run_dg("--stages", "v2")[0], 0)
        with open(os.path.join(self.data, "sft-v2", "train.jsonl"), encoding="utf-8") as f:
            v2_train = f.read()
        first = self.chat_calls()
        code, err = self.run_dg("--stages", "v3")
        self.assertEqual(code, 0, err)
        for name in ("seeds3.jsonl", "review_items3.jsonl", "sft-v3/train.jsonl", "sft-v3/valid.jsonl", "STATS-v3.md", "RUN-v3.json"):
            self.assertTrue(os.path.exists(os.path.join(self.data, name)), name)
        with open(os.path.join(self.data, "sft-v2", "train.jsonl"), encoding="utf-8") as f:
            self.assertEqual(f.read(), v2_train)  # v2's files are left alone
        rows, metas = [], []
        for split in ("train", "valid"):
            with open(os.path.join(self.data, "sft-v3", split + ".jsonl"), encoding="utf-8") as f:
                rows += [json.loads(l) for l in f]
            with open(os.path.join(self.data, "sft-v3", split + ".meta.jsonl"), encoding="utf-8") as f:
                metas += [json.loads(l) for l in f]
        self.assertEqual({m["job"] for m in metas}, {"planner", "reviewer", "gate"})
        for r, m in zip(rows, metas):
            sysmsg, target = r["messages"][0]["content"], r["messages"][-1]["content"]
            if m["job"] == "reviewer":
                self.assertEqual(sysmsg, prompts.HYDRA_REVIEW_PROMPT)
                self.assertEqual(m["source"], "review3")
                self.assertTrue(validate_review(target, require=("check",)).valid, target)
            elif m["job"] == "planner":
                self.assertEqual(sysmsg, prompts.HYDRA_PLANNER_PROMPT)
                if m["source"] == "plan3":
                    self.assertTrue(3 <= len(json.loads(target)["steps"]) <= 5)
        self.assertTrue(any(m["source"] == "plan3" for m in metas))
        self.assertTrue(any(m["source"] == "plan2" for m in metas))
        self.assertTrue(any(m.get("variant") == "teacher3" for m in metas))
        self.assertTrue(any(str(m.get("variant", "")).startswith("flaw3_") for m in metas))
        with open(self.log, encoding="utf-8") as f:
            later = [json.loads(l)["body"] for l in f if json.loads(l)["path"] == "/api/chat"][first:]
        rv = [b for b in later if b["messages"][0]["content"].startswith(prompts.HYDRA_REVIEW_PROMPT)]
        self.assertTrue(rv)
        for b in rv:
            self.assertEqual(b["messages"][0]["content"], prompts.HYDRA_REVIEW_PROMPT + tp.CHECK_NOTE3)
        with open(os.path.join(self.data, "review_items3.jsonl"), encoding="utf-8") as f:
            items = [json.loads(l) for l in f]
        broken = sum(1 for it in items if it["expected_done"] is False)
        self.assertEqual(len(rv), 2 * len(items) - broken)  # known-broken results get one pass
        grouped = [b for b in later if b["messages"][0]["content"].startswith(prompts.HYDRA_PLANNER_PROMPT + tp.PLAN_HINT_INTRO + tp.PLAN_HINTS["group"])]
        self.assertTrue(grouped)
        calls = self.chat_calls()
        self.assertEqual(self.run_dg("--stages", "v3")[0], 0)  # resuming calls no model
        self.assertEqual(self.chat_calls(), calls)

    def test_v2_needs_v1(self):
        with self.assertRaises(SystemExit):
            self.run_dg("--stages", "v2")

    def test_interrupted_run_continues_without_repeating(self):
        code, _ = self.run_dg("--stages", "seeds,plans")
        self.assertEqual(code, 0)
        first = self.chat_calls()
        plans = Store(os.path.join(self.data, "raw", "plans.jsonl")).all()
        self.assertTrue(plans)
        code, err = self.run_dg()
        self.assertEqual(code, 0, err)
        with open(self.log, encoding="utf-8") as f:
            later = [json.loads(l)["body"] for l in f if json.loads(l)["path"] == "/api/chat"][first:]
        from helper import prompts
        replans = [b for b in later if b["messages"][0]["content"] == prompts.HYDRA_PLANNER_PROMPT
                   and "The previous attempt produced this result" not in b["messages"][1]["content"]]
        self.assertEqual(replans, [])  # first-round plans weren't asked for again

    def test_teacher_requests_match_chimera(self):
        self.assertEqual(self.run_dg()[0], 0)
        from helper import chimera_port as cp, prompts
        with open(self.log, encoding="utf-8") as f:
            bodies = [json.loads(l)["body"] for l in f if json.loads(l)["path"] == "/api/chat"]
        gates = [b for b in bodies if b["messages"][0]["content"] == prompts.HEAD_GATE_PROMPT]
        self.assertTrue(gates)
        for b in gates:
            self.assertEqual(b["format"], json.loads(prompts.HEAD_GATE_SCHEMA))
            self.assertEqual(b["options"]["temperature"], 0)
        planners = [b for b in bodies if b["messages"][0]["content"] == prompts.HYDRA_PLANNER_PROMPT]
        self.assertTrue(planners)
        for b in planners:
            self.assertEqual(b["format"], "json")
            self.assertEqual(b["options"]["num_ctx"], cp.ctx_bucket(cp.history_tokens(b["messages"]) + 2048))

    def test_smoke_checks_allow_resume_and_empty_optional_stages(self):
        from datagen import sizes
        old = dict(sizes.SIZES["tiny"])
        sizes.SIZES["tiny"].update(final_checks=True, sanity=True, check_after=50, flaw_frac=0.0, min_flaws=0)
        try:
            code, err = self.run_dg()
            self.assertEqual(code, 0, err)  # no flawed copies picked: not a failure
            code, err = self.run_dg()
            self.assertEqual(code, 0, err)  # every stage already done: not a failure either
        finally:
            sizes.SIZES["tiny"].clear()
            sizes.SIZES["tiny"].update(old)

    def test_sanity_stop_writes_a_report(self):
        mock_ollama.Handler.extra = [lambda s, u, m, b, n: "not json at all" if s == datagen_mock.tp.SEED_SYSTEM else None,
                                     datagen_mock.respond]
        from datagen import sizes
        old = dict(sizes.SIZES["tiny"])
        sizes.SIZES["tiny"].update(sanity=True, check_after=2)
        try:
            code, err = self.run_dg("--stages", "seeds")
        finally:
            sizes.SIZES["tiny"].clear()
            sizes.SIZES["tiny"].update(old)
        self.assertEqual(code, 3)
        self.assertTrue(os.path.exists(os.path.join(self.data, "STOPPED.md")))


def plan_text(kind="code", steps=None, **kw):
    steps = steps or [{"id": "s1", "title": "Write the parser module", "kind": kind, "instructions": "Write parse.py with parse() in full.", "depends_on": []},
                      {"id": "s2", "title": "Write the command line", "kind": kind, "instructions": "Write cli.py that calls parse() and prints rows.", "depends_on": []}]
    p = {"title": "Tool", "kind": kind, "summary": "A tool. It parses things.", "steps": steps}
    p.update(kw)
    return json.dumps(p)


class PieceTests(unittest.TestCase):
    def test_plan_hints(self):
        from datagen.plans import plan_hints
        from datagen import teacher_prompts as tp
        self.assertEqual(plan_hints("batch", ["batch_not_parallel", "schema:minItems", "step_count"], 1),
                         [tp.PLAN_HINTS["one_step"], tp.PLAN_HINTS["not_parallel"]])
        self.assertEqual(plan_hints("batch", ["step_count"], 10), [tp.PLAN_HINTS["too_many"]])
        self.assertEqual(plan_hints("coding", ["kind:code"]), [])  # only a Blender plan has the wrong label
        self.assertEqual(plan_hints("blender", ["kind:code", "meta_step"]), [tp.PLAN_HINTS["meta_step"], tp.PLAN_HINTS["blender_kind"]])

    def test_checked_targets(self):
        from datagen.reviews import checked_target
        self.assertEqual(checked_target({"done": True, "check": ["a: met", " b: met "], "score": 95, "critique": "tiny nit"}),
                         {"check": "a: met\nb: met", "done": True, "score": 95, "critique": ""})
        self.assertIsNone(checked_target({"done": True, "score": 95, "critique": ""}))
        self.assertIsNone(checked_target({"check": [1, 2], "done": False, "score": 5, "critique": "y"}))
        self.assertEqual(checked_target({"check": [{"requirement": "5 taglines", "status": "4 given"}], "done": False,
                                         "score": 60.0, "critique": "Add the fifth."})["check"], "5 taglines — 4 given")
        self.assertEqual(checked_target({"check": {"length": "190 words, 60 asked"}, "done": False, "score": 30,
                                         "critique": "Trim it."})["check"], "length: 190 words, 60 asked")
        self.assertEqual(checked_target({"check": "ok", "done": True, "score": 95.0, "critique": ""})["score"], 95)
        self.assertIsNone(checked_target({"check": "ok", "done": True, "score": 95.5, "critique": ""}))

    def test_done_repeat(self):
        from datagen.build import done_repeat
        rv = lambda done: {"meta": {"job": "reviewer", "done": done}}  # noqa: E731
        self.assertEqual(done_repeat([rv(True)] * 87 + [rv(False)] * 319), 2)
        self.assertEqual(done_repeat([rv(True)] * 200 + [rv(False)] * 300), 1)
        self.assertEqual(done_repeat([rv(True)] * 10 + [rv(False)] * 300), 3)
        self.assertEqual(done_repeat([rv(False)] * 3), 1)

    def test_judge_plan(self):
        self.assertTrue(judge_plan("coding", plan_text())[0])
        ok, why, _, _ = judge_plan("blender", plan_text())
        self.assertFalse(ok)
        self.assertIn("kind:code", why)
        ok, _, target, _ = judge_plan("coding", "```json\n" + plan_text().replace('"s1"', '"step1"').replace('"s2"', '"step2"') + "\n```")
        self.assertTrue(ok)
        self.assertEqual([s["id"] for s in json.loads(target)["steps"]], ["s1", "s2"])
        meta = json.loads(plan_text())
        meta["steps"][1]["title"] = "Review and combine everything"
        self.assertIn("meta_step", judge_plan("coding", json.dumps(meta))[1])
        serial = json.loads(plan_text(kind="writing"))
        serial["steps"][1]["depends_on"] = ["s1"]
        self.assertIn("batch_not_parallel", judge_plan("batch", json.dumps(serial))[1])
        fwd = json.loads(plan_text())
        fwd["steps"][0]["depends_on"] = ["s2"]
        self.assertFalse(judge_plan("coding", json.dumps(fwd))[0])

    def test_truncate_and_drop(self):
        text = "\n\n".join(f"## Part {i}\n\n" + "word " * 40 for i in range(1, 6))
        r = random.Random(1)
        t = truncate(text, r)
        self.assertTrue(t and len(t) < 0.85 * len(text) and text.startswith(t))
        d = drop_section(text, random.Random(2))
        self.assertTrue(d and d.count("## Part") == 4)
        self.assertIsNone(drop_section("just one paragraph", random.Random(3)))

    def test_store_survives_a_cut_line(self):
        tmp = tempfile.mkdtemp(prefix="hm-store-")
        try:
            path = os.path.join(tmp, "s.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"key": "a", "v": 1}\n{"key": "b", "v"')
            s = Store(path)
            self.assertEqual(set(s.rows), {"a"})
            s.add({"key": "c", "v": 3})
            self.assertEqual(set(Store(path).rows), {"a", "c"})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


class BuildRuleTests(unittest.TestCase):
    def test_file_making_steps(self):
        from datagen.build import file_making_steps
        plan = {"steps": [{"title": "Write the guide", "instructions": "x"}, {"title": "Convert guide to PDF", "instructions": "x"},
                          {"title": "Create Dockerfile for the app", "instructions": "x"}, {"title": "Generate Word document Plan.docx", "instructions": "x"}]}
        self.assertEqual(file_making_steps(plan), ["Convert guide to PDF", "Generate Word document Plan.docx"])

    def test_relabel_blender(self):
        from datagen.build import relabel_blender
        plan = {"kind": "code", "steps": [{"kind": "code", "title": "Build the ring of cubes", "instructions": "Use bpy to add 32 cubes."},
                                          {"kind": "code", "title": "Parse drum_hits.log", "instructions": "Read the log into a list."},
                                          {"kind": "writing", "title": "Notes", "instructions": "Explain the scene."}]}
        q = relabel_blender(plan)
        self.assertEqual(q["kind"], "blender")
        self.assertEqual([s["kind"] for s in q["steps"]], ["blender", "code", "writing"])
        self.assertEqual(plan["kind"], "code")  # the original is untouched

    def test_split_gives_every_job_valid_groups(self):
        from datagen.build import split_groups
        kept = [{"meta": {"job": "gate", "group": f"head:{i}"}} for i in range(20)] + \
               [{"meta": {"job": "planner", "group": f"seed{i}"}} for i in range(100)]
        valid = split_groups(kept)
        self.assertGreaterEqual(sum(1 for g in valid if g.startswith("head:")), 2)
        self.assertGreaterEqual(sum(1 for g in valid if g.startswith("seed")), 5)
