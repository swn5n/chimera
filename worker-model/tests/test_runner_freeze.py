"""runner/freeze.py against the mock Ollama and a fake Blender: plans, the fallback planner, resuming, verified
dependency outputs, and the W1 cases built from what it froze."""
import json
import os
import unittest

from tests import _paths  # noqa: F401
from tests.runner_fakes import FakeBlender, MockOllamaCase
from runner import cases as C
from runner import common, freeze, mock_ollama

import evalset

ES = evalset.load()


class PickTests(unittest.TestCase):
    def test_gpt_oss_tasks_are_fixed_and_spread(self):
        order = [c["id"] for c in ES.cases("w1")] + ES.helper_prompt_ids()
        a = freeze.gpt_oss_tasks(order, {}, 10)
        self.assertEqual(a, freeze.gpt_oss_tasks(list(reversed(order)), {}, 10))  # order doesn't matter
        self.assertEqual(len(a), 10)
        self.assertEqual({freeze.group(t) for t in a}, {"bw", "code", "res", "bl", "batch"})
        b = freeze.gpt_oss_tasks(order, {"bw-04": "gpt-oss:120b", "bw-05": "hydra:1.0"}, 10)
        self.assertEqual(b[0], "bw-04")
        self.assertNotIn("bw-05", b)


class FreezeTests(MockOllamaCase):
    def freeze(self, *extra, blender=None):
        argv = ["--host", self.url, "--frozen", os.path.join(self.tmp, "frozen"), "--planner", "mock:latest",
                "--fallback-planner", "mock:big", "--gpt-oss-plans", "0", "--teacher", "mock:latest",
                "--today-model", "mock:today"]
        return self.quiet(freeze.main, argv + list(extra), blender=blender)

    def frozen(self, name):
        with open(os.path.join(self.tmp, "frozen", name), encoding="utf-8") as f:
            return json.load(f)

    def test_plans_requests_files_and_resume(self):
        code, err = self.freeze("--what", "plans", "--tasks", "bw-01,code-04")
        self.assertEqual(code, 0, err)
        bodies = self.requests()
        self.assertEqual(len(bodies), 2)
        cp = common.helper_port()
        goals = C.task_goals(ES)
        for b, tid in zip(bodies, ("bw-01", "code-04")):
            g, h, prior, crit = goals[tid]
            self.assertEqual(b["messages"], cp.planner_messages(g, h, prior, crit))
            self.assertEqual((b["format"], b["keep_alive"], b["stream"]), ("json", "15m", True))
            self.assertEqual(b["options"], {"num_ctx": cp.ctx_bucket(cp.history_tokens(b["messages"]) + 2048, 0)})
        self.assertIn("The previous attempt produced this result:", bodies[1]["messages"][1]["content"])  # a re-plan
        doc = self.frozen("plans.json")
        self.assertEqual(doc["canary"], evalset.CANARY)
        self.assertIn("EVAL ONLY", doc["note"])
        self.assertEqual([p["id"] for p in doc["items"]], ["bw-01", "code-04"])
        p = doc["items"][0]
        self.assertEqual(p["planner_model"], "mock:latest")
        self.assertEqual(p["plan"]["steps"][1], {"id": "s2", "title": "Box on the floor", "kind": "blender",
                                                 "instructions": "Put a box on s1's floor.", "depends_on": ["s1"]})
        code, err = self.freeze("--what", "plans", "--tasks", "bw-01,code-04")
        self.assertEqual(len(self.requests()), 2)  # resumed: nothing asked again

    def test_unreadable_plan_goes_to_the_fallback_planner(self):
        mock_ollama.Handler.extra = [lambda s, u, b: "not a plan" if b["model"] == "mock:latest" else None]
        code, err = self.freeze("--what", "plans", "--tasks", "bw-02")
        self.assertEqual(code, 0, err)
        self.assertEqual([b["model"] for b in self.requests()], ["mock:latest", "mock:big"])
        item = self.frozen("plans.json")["items"][0]
        self.assertEqual((item["planner_model"], len(item["tries"])), ("mock:big", 2))

    def test_deps_are_verified_and_become_w1_cases(self):
        self.freeze("--what", "plans", "--tasks", "bw-01")
        fake = FakeBlender()
        code, err = self.freeze("--what", "deps", "--tasks", "bw-01", "--today-deps", "1", blender=fake)
        self.assertEqual(code, 0, err)
        doc = self.frozen("deps.json")
        self.assertEqual(doc["canary"], evalset.CANARY)
        steps = doc["items"][0]["steps"]
        self.assertEqual(list(steps), ["s1"])  # only steps another step depends on
        self.assertEqual(steps["s1"]["status"], "verified")
        self.assertIn("```handoff", steps["s1"]["reply"])
        self.assertEqual(steps["s1"]["today"]["status"], "verified")
        worker = [b for b in self.requests() if b["messages"][0]["content"].startswith(mock_ollama.CONTRACT_OPENING)]
        self.assertEqual([(b["model"], b.get("format")) for b in worker], [("mock:latest", None)])
        today_req = [b for b in self.requests() if b["model"] == "mock:today"]
        self.assertTrue(today_req[0]["messages"][0]["content"].startswith(mock_ollama.TODAY_OPENING))
        self.assertEqual([k for k, _, _ in fake.calls].count("check"), 3)  # alone and joined, then today's
        self.assertEqual([k for k, _, _ in fake.calls].count("probe"), 3)  # each with its direct run (whole output)
        cs = C.w1_cases(ES, os.path.join(self.tmp, "frozen"))
        self.assertEqual([c.id for c in cs], ["bw-01/s1", "bw-01/s2", "bw-01/s2-today"])
        self.assertEqual(cs[1].outputs["s1"], steps["s1"]["reply"])
        self.assertNotIn("```handoff", cs[1].outputs_today["s1"])
        self.assertEqual(cs[2].outputs["s1"], steps["s1"]["today"]["reply"])
        self.assertTrue(cs[1].goal.startswith("Blender 5 script: a product shot"))

    def test_rejected_deps_skip_their_dependents(self):
        self.freeze("--what", "plans", "--tasks", "bw-01")
        code, err = self.freeze("--what", "deps", "--tasks", "bw-01", "--today-deps", "0", "--tries-blender", "2",
                                blender=FakeBlender(strict=False))
        self.assertEqual(code, 0, err)
        s1 = self.frozen("deps.json")["items"][0]["steps"]["s1"]
        self.assertEqual((s1["status"], s1["tries"]), ("rejected", 2))
        skipped = []
        cs = C.w1_cases(ES, os.path.join(self.tmp, "frozen"), skipped=skipped)
        self.assertEqual([c.id for c in cs], ["bw-01/s1"])
        self.assertTrue(skipped and "s1" in skipped[0])

    def reject(self, blender, *extra):
        self.freeze("--what", "plans", "--tasks", "bw-01")
        code, err = self.freeze("--what", "deps", "--tasks", "bw-01", "--today-deps", "0", "--tries-blender", "1",
                                *extra, blender=blender)
        self.assertEqual(code, 0, err)
        return self.frozen("deps.json")["items"][0]["steps"]["s1"]

    def test_a_stand_in_only_the_whole_output_shows_is_rejected(self):
        # the check's 1,500-character tail no longer shows the stand-in line; the direct run's whole output does
        s1 = self.reject(FakeBlender(stand_in=True, stand_in_tail=False))
        self.assertEqual(s1["status"], "rejected")
        self.assertTrue(s1["attempts"][0]["verdict"]["joined_stand_in"])

    def test_an_error_line_before_the_tail_is_rejected(self):
        s1 = self.reject(FakeBlender(strict_full=False))
        self.assertEqual(s1["status"], "rejected")
        self.assertEqual(s1["attempts"][0]["verdict"]["alone"], {"5.2.2": False, "5.0.1": False})

    def test_a_runaway_teacher_reply_is_a_rejected_try(self):
        fake = FakeBlender()
        s1 = self.reject(fake, "--reply-cap", "2")
        self.assertEqual((s1["status"], s1["tries"]), ("rejected", 1))
        self.assertEqual(s1["attempts"][0]["verdict"]["runaway"], 2)
        self.assertEqual(fake.calls, [])  # never verified
        self.assertEqual(self.frozen("plans.json")["items"][0]["planner_model"], "mock:latest")  # plans aren't capped

    def test_dry_run_calls_nothing(self):
        code, _ = self.quiet(freeze.main, ["--dry-run", "--host", "127.0.0.1:9", "--frozen", os.path.join(self.tmp, "f")])
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "f")))


if __name__ == "__main__":
    unittest.main()
