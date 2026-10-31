"""runner/task_eval.py against the mock Ollama: onePass's order and requests, joining, the fallback, the lone step."""
import json
import os
import unittest

from tests import _paths  # noqa: F401
from tests.runner_fakes import FakeBlender, MockOllamaCase
from runner import common, mock_ollama, task_eval

import evalset
from contract import prompt as cprompt, texts as T, today
from contract.goport import clean_plan

ES = evalset.load()


class TaskEvalTests(MockOllamaCase):
    def run_tasks(self, *extra, blender=None):
        argv = ["--host", self.url, "--workers", "mock:latest", "--combine-model", "mock:combine",
                "--out", os.path.join(self.tmp, "tasks"), "--case", "w2-01"]
        return self.quiet(task_eval.main, argv + list(extra), blender=blender or FakeBlender())

    def chat(self):
        return [b for b in self.requests() if b["messages"][-1]["content"] != "Reply with OK."]

    def test_arms_a_and_b_order_requests_and_results(self):
        fake = FakeBlender()
        code, err = self.run_tasks("--arm", "A,B", blender=fake)
        self.assertEqual(code, 0, err)
        bodies = self.chat()
        a, b = bodies[:4], bodies[4:]
        plan = clean_plan(ES.by_id("w2-01")["plan"])
        # arm A: three of today's worker requests in plan order, then the combine on the combine model
        self.assertEqual([x["model"] for x in a], ["mock:latest"] * 3 + ["mock:combine"])
        self.assertTrue(a[3]["messages"][0]["content"].startswith(T.TODAY_SYNTH_HEAD))
        self.assertEqual(a[0]["messages"], today.worker_messages(plan, 0, {})["messages"])
        self.assertIn('Output from the step "Glass and gold materials":', a[1]["messages"][1]["content"])
        # arm B: three contract requests, s2 gets s1's piece and handoff, and no combine
        self.assertEqual(len(b), 3)
        goal = f"{plan['title']}: {plan['summary']}"
        self.assertEqual(b[0]["messages"], cprompt.worker_request(plan, 0, {}, goal=goal).messages)
        self.assertIn('From s1, "Glass and gold materials" (you use it):\nIts handoff:', b[1]["messages"][1]["content"])
        for x in bodies:
            self.assertTrue(x["stream"])
            self.assertEqual(x["keep_alive"], "15m")
            self.assertNotIn("format", x)
            self.assertEqual(set(x["options"]), {"num_ctx"})
            self.assertEqual(x["options"]["num_ctx"], 8192)
        dirs = {d.split("-")[-3]: d for d in self.run_dirs("tasks")}  # <time>-<arm>-mock-latest
        self.assertEqual(sorted(dirs), ["A", "B"])
        ra = self.read_jsonl(os.path.join(dirs["A"], "raw.jsonl"))[0]
        rb = self.read_jsonl(os.path.join(dirs["B"], "raw.jsonl"))[0]
        self.assertEqual((ra["how"], rb["how"]), ("combine", "joined"))
        self.assertIn("def main():", rb["result"])
        self.assertIn("build_s3(ctx)", rb["result"])
        self.assertNotIn("```handoff", rb["result"])
        self.assertEqual(rb["check"]["outcome"], "checked")
        self.assertTrue(rb["check"]["check"]["5.2.2"]["strict"])
        self.assertEqual(rb["check"]["strict"], {"5.2.2": True, "5.0.1": True})
        self.assertEqual([n for k, n, _ in fake.calls if k == "check"], ["result.md", "result.md"])
        self.assertEqual([k for k, _, _ in fake.calls].count("probe"), 2)  # the direct run, for the whole output
        for d in dirs.values():
            with open(os.path.join(d, "summary.json"), encoding="utf-8") as f:
                s = json.load(f)["summary"]
            self.assertEqual((s["n"], s["pass_both"]), (1, 100.0))
            self.assertTrue(os.path.exists(os.path.join(d, "summary.md")))
        self.assertEqual(len(self.requests("/api/generate")), 2)  # both models unloaded afterwards

    def test_a_broken_piece_falls_back_to_the_combine(self):
        def broken_s2(system, user, body):
            if system.startswith(mock_ollama.CONTRACT_OPENING) and "You do step s2 of" in system:
                return "```python\nimport bpy\nprint('no contract here')\n```"
            return None
        mock_ollama.Handler.extra = [broken_s2]
        code, err = self.run_tasks("--arm", "B")
        self.assertEqual(code, 0, err)
        bodies = self.chat()
        self.assertEqual([x["model"] for x in bodies], ["mock:latest"] * 3 + ["mock:combine"])
        combine = bodies[3]["messages"][1]["content"]
        self.assertIn("```handoff", combine)  # the pieces as written, handoffs included
        rec = self.read_jsonl(os.path.join(self.run_dirs("tasks")[0], "raw.jsonl"))[0]
        self.assertEqual(rec["how"], "fallback")
        self.assertTrue(rec["join"]["fallback"])
        self.assertTrue(any(r.startswith("s2:") for r in rec["join"]["reasons"]))

    def test_lone_step_and_failed_steps(self):
        client = common.Ollama(self.url, 30)
        plan = clean_plan({"title": "One box", "kind": "blender", "summary": "A box.",
                           "steps": [{"id": "s1", "title": "Box", "kind": "blender", "instructions": "Make a box."}]})
        t = task_eval.Task("lone", plan, "A box.", "test")
        rec = task_eval.run_task(t, "B", client, "mock:latest", "mock:combine", {}, 30)
        self.assertEqual(rec["how"], "joined")
        self.assertEqual(len(self.requests()), 1)  # no combine for a lone step
        self.assertTrue(self.requests()[0]["messages"][0]["content"].startswith(T.CONTRACT_LONE_OPENING))
        rec = task_eval.run_task(t, "A", client, "mock:latest", "mock:combine", {}, 30)
        self.assertEqual(rec["how"], "lone")
        rec = task_eval.run_task(t, "A", client, "missing:x", "mock:combine", {}, 30)
        self.assertEqual((rec["how"], rec["result"]), ("none", None))
        self.assertEqual(rec["steps"][0]["attempts"], 2)  # runStep tries twice when the call fails

    def test_result_check_paths(self):
        t = task_eval.Task("t", clean_plan(ES.by_id("w2-01")["plan"]), "goal", "test", assertions=[{"value": "scene", "not_null": True}])
        fake = FakeBlender()
        out = task_eval.check_result(t, {"result": "text", "cut": True}, fake, None)
        self.assertEqual(out["outcome"], "cut_off")
        out = task_eval.check_result(t, {"result": "no code here"}, fake, None)
        self.assertEqual(out["outcome"], "nothing_to_check")
        two = mock_ollama.today_script("a") + "\n\n" + mock_ollama.today_script("b")
        out = task_eval.check_result(t, {"result": two}, fake, None)
        self.assertEqual(out["outcome"], "skipped")
        out = task_eval.check_result(t, {"result": mock_ollama.today_script("a")}, fake, None)
        self.assertEqual(out["outcome"], "checked")
        self.assertEqual(out["assertions"], {"5.2.2": [], "5.0.1": []})

    def test_result_with_an_error_before_the_tail_fails(self):
        code, err = self.run_tasks("--arm", "B", blender=FakeBlender(strict_full=False))
        self.assertEqual(code, 0, err)
        d = self.run_dirs("tasks")[0]
        rec = self.read_jsonl(os.path.join(d, "raw.jsonl"))[0]
        self.assertTrue(rec["check"]["check"]["5.2.2"]["strict"])  # the check's tail is clean
        self.assertFalse(task_eval.passes(rec, "5.2.2"))
        with open(os.path.join(d, "summary.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["summary"]["pass_both"], 0.0)
        with open(os.path.join(d, "summary.md"), encoding="utf-8") as f:
            self.assertIn("the direct run printed Error: fake", f.read())

    def test_reply_cap_cuts_steps_and_a_lone_step_is_a_runaway(self):
        client = common.Ollama(self.url, 30)
        client.reply_cap = 2
        plan = clean_plan(ES.by_id("w2-01")["plan"])
        t = task_eval.Task("t", plan, "goal", "test")
        rec = task_eval.run_task(t, "B", client, "mock:latest", "mock:combine", {}, 30)
        self.assertEqual(rec["runaway_steps"], ["s1", "s2", "s3"])  # every mock reply is 3+ chunks: all cut at 2
        client.reply_cap = 6144
        rec = task_eval.run_task(t, "B", client, "mock:latest", "mock:combine", {}, 30)
        self.assertEqual(rec["runaway_steps"], [])
        client.reply_cap = 2
        lone = task_eval.Task("lone", clean_plan({"title": "One box", "kind": "blender", "summary": "A box.",
                                                  "steps": [{"id": "s1", "title": "Box", "kind": "blender",
                                                             "instructions": "Make a box."}]}), "A box.", "test")
        rec = task_eval.run_task(lone, "A", client, "mock:latest", "mock:combine", {}, 30)
        self.assertTrue(rec["cut"] and rec["result_runaway"])
        self.assertEqual(task_eval.check_result(lone, rec, FakeBlender(), None)["outcome"], "runaway")

    def test_summary_counts_unchecked_tasks_as_fails(self):
        # the review's case: 1 checked pass, 2 cut off, 1 skipped (two scripts): 25%, not 100%
        def rec(outcome, scripts=1, mode="blender", runaway=False):
            ck = {"outcome": outcome, "scripts": {"blender": scripts, "python": 0}}
            if outcome == "checked":
                ck["check"] = {v: {"strict": True, "outcome": "passed"} for v in task_eval.VERSIONS}
                ck["strict"] = {v: True for v in task_eval.VERSIONS}
            return {"task": "t", "how": "combine", "cut": outcome in ("cut_off", "runaway"), "result_runaway": runaway,
                    "steps": [{"sid": "s1", "mode": mode, "contract_ok": True, "runaway": runaway, "stats": {}}],
                    "check": ck}
        recs = [rec("checked"), rec("cut_off", 0), rec("cut_off", 0), rec("skipped", 2)]
        s = task_eval.summarize(recs)
        self.assertEqual((s["blender_n"], s["blender_checked"], s["pass_5.2.2"], s["pass_both"]), (4, 1, 25.0, 25.0))
        self.assertEqual(s["one_script"], 25.0)  # of the same four tasks, never over 100
        self.assertEqual({k: v for k, v in s["unchecked"]["blender"].items() if v}, {"cut_off": 2, "skipped": 1})
        s = task_eval.summarize(recs + [rec("runaway", 0, runaway=True), rec("no_result", 0, mode="python-script"),
                                        rec("nothing_to_check", 0, mode="files")])
        self.assertEqual((s["blender_n"], s["pass_both"], s["runaway"], s["runaway_steps"]), (5, 20.0, 14.3, 1))
        self.assertEqual((s["python_n"], s["python_pass"], s["files_n"]), (1, 0.0, 1))
        self.assertEqual(s["unchecked"]["python"]["no_result"], 1)
        self.assertIsNone(task_eval.summarize([rec("not_run")])["pass_both"])

    def test_joined_python_with_no_entry_point_is_not_a_pass(self):
        # The verifier's case: a 2-step python-script plan whose pieces only define functions. Chimera's check passes
        # the joined file in no time without running a line of it; it must count as a fail, listed as unchecked.
        def py_piece(with_main):
            def fn(system, user, body):
                if not system.startswith(mock_ollama.CONTRACT_OPENING):
                    return None
                sid = "s2" if "You do step s2 of" in system else "s1"
                main = ("\n\ndef main():\n    print(%s_double(2))\n" % sid) if with_main and sid == "s2" else ""
                return ("```python\n" + mock_ollama.MARK + "\n\n\ndef %s_double(x):\n    y = x * 2\n    z = y + 0\n"
                        "    w = z - 0\n    return w\n%s```\n\n```handoff\nprovides: %s_double(x)\nuses: none\n"
                        "assumed: none\n```\n") % (sid, main, sid)
            return fn
        plan = clean_plan({"title": "Number tool", "kind": "code", "summary": "A small number tool in two steps.",
                           "steps": [{"id": "s1", "title": "Doubling", "kind": "code", "instructions": "Double a number."},
                                     {"id": "s2", "title": "More doubling", "kind": "code",
                                      "instructions": "Double another number."}]})
        t = task_eval.Task("py", plan, "A small number tool.", "test")
        client = common.Ollama(self.url, 30)
        recs = []
        for with_main in (False, True):
            mock_ollama.Handler.extra = [py_piece(with_main)]
            rec = task_eval.run_task(t, "B", client, "mock:latest", "mock:combine", {}, 30)
            self.assertEqual(rec["how"], "joined")
            rec["check"] = task_eval.check_result(t, rec, FakeBlender(), None)
            recs.append(rec)
        no_main, with_main = recs
        self.assertIn("missing_entry_point", [s["code"] for s in no_main["join"]["seams"]])
        self.assertEqual(no_main["check"]["outcome"], "no_entry_point")
        self.assertNotIn("check", no_main["check"])  # not run: the check would pass without running anything
        self.assertFalse(task_eval.py_passes(no_main))
        self.assertEqual(with_main["check"]["outcome"], "checked")
        self.assertTrue(task_eval.py_passes(with_main))
        s = task_eval.summarize([no_main])
        self.assertEqual((s["python_n"], s["python_checked"], s["python_pass"]), (1, 0, 0.0))
        self.assertEqual(s["unchecked"]["python"]["no_entry_point"], 1)
        self.assertEqual(task_eval.summarize(recs)["python_pass"], 50.0)
        md = task_eval.render_md({"arm": "B", "prompt": "contract", "joining": "join", "workers": "w", "started": "t",
                                  "combine_model": "c", "seam": "none"}, task_eval.summarize(recs), recs)
        self.assertIn("no_entry_point: no step defines main()", md)

    def test_steps_form_ok_next_to_contract_kept(self):
        def unfenced(system, user, body):  # a near-miss handoff: the three lines at the end, under a bare label
            if system.startswith(mock_ollama.CONTRACT_OPENING) and "You do step s2 of" in system:
                m = __import__("re").search(r"You do step (s\d+)", system)
                return mock_ollama.contract_piece(m.group(1), ["s1"]).replace("```handoff\n", "handoff\n").rstrip()[:-3]
            return None
        mock_ollama.Handler.extra = [unfenced]
        client = common.Ollama(self.url, 30)
        t = task_eval.Task("t", clean_plan(ES.by_id("w2-01")["plan"]), "goal", "test")
        rec = task_eval.run_task(t, "B", client, "mock:latest", "mock:combine", {}, 30)
        self.assertEqual([(x["contract_ok"], x["form_ok"]) for x in rec["steps"]], [(True, True), (True, False), (True, True)])
        s = task_eval.summarize([rec])
        self.assertEqual((s["steps_contract_ok"], s["steps_form_ok"]), (100.0, 66.7))
        md = task_eval.render_md({"arm": "B", "prompt": "contract", "joining": "join", "workers": "w", "started": "t",
                                  "combine_model": "c", "seam": "none"}, s, [rec])
        self.assertIn("steps in exact form", md)
        self.assertIn("s2 ", md)
        self.assertIn("near", md)

    def test_dry_run_and_unknown_arm(self):
        code, out = self.quiet(task_eval.main, ["--arm", "B", "--case", "w2-01", "--dry-run", "--host", "127.0.0.1:9"])
        self.assertEqual(code, 0)
        with self.assertRaises(SystemExit):
            self.quiet(task_eval.main, ["--arm", "Z", "--case", "w2-01", "--dry-run"])

    def test_frozen_tasks_need_freezing_first(self):
        code, err = self.quiet(task_eval.main, ["--tasks", "bw-01", "--frozen", os.path.join(self.tmp, "none"),
                                                "--host", self.url, "--no-blender"])
        self.assertEqual(code, 2)
        self.assertIn("freeze", err)


if __name__ == "__main__":
    unittest.main()
