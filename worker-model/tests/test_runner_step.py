"""runner/step_eval.py against the mock Ollama: the requests it sends (Chimera's shape) and what it writes."""
import json
import os
import unittest

from tests import _paths  # noqa: F401
from tests.runner_fakes import FakeBlender, MockOllamaCase
from runner import cases as C
from runner import common, mock_ollama, step_eval

import evalset

ES = evalset.load()


class CtxBucketTests(unittest.TestCase):
    def test_matches_helper_port_and_go(self):
        cp = common.helper_port()
        for need in (0, 4096, 7000, 7001, 30000, 30001, 65536, 65537, 200000):
            for cap in (0, 16384, 40960, 262144):
                self.assertEqual(common.ctx_bucket(need, cap), cp.ctx_bucket(need, cap), (need, cap))
        with open(os.path.join(_paths.APP, "hub.go"), encoding="utf-8") as f:
            go = f.read()
        for line in ("case need > 65536:", "b = 131072", "case need > 30000:", "b = 65536", "case need > 7000:",
                     "b = 32768", "b := 8192"):
            self.assertIn(line, go)

    def test_chat_body_is_chimeras(self):
        msgs = [{"role": "system", "content": "a", "extra": 1}, {"role": "user", "content": "b"}]
        b = common.chat_body("m", msgs, 9000, 16384)
        self.assertEqual(b, {"model": "m", "messages": [{"role": "system", "content": "a"}, {"role": "user", "content": "b"}],
                             "stream": True, "keep_alive": "15m", "options": {"num_ctx": 16384}})
        with open(os.path.join(_paths.APP, "ollama.go"), encoding="utf-8") as f:
            go = f.read()
        self.assertIn('"stream": true, "keep_alive": keepAlive', go)
        self.assertIn('ChatStreamKeep(ctx, model, msgs, options, format, "15m", onDelta)', go)


class StepEvalTests(MockOllamaCase):
    CASES = ["w2-01", "w3-05", "w4l-04", "w4f-08"]

    def run_step(self, *extra, blender=None):
        argv = ["--model", "mock:latest", "--host", self.url, "--out", os.path.join(self.tmp, "runs")]
        for c in self.CASES:
            argv += ["--case", c]
        return self.quiet(step_eval.main, argv + list(extra), blender=blender)

    def test_requests_are_chimeras_and_folders_are_written(self):
        fake = FakeBlender()
        code, err = self.run_step("--samples", "2", blender=fake)
        self.assertEqual(code, 0, err)
        bodies = self.requests()
        warm, steps = bodies[0], bodies[1:]
        self.assertEqual(warm["messages"][0]["content"], "Reply with OK.")
        # 3 Blender cases x 2 samples + 1 prose case x 1 sample, per prompt
        self.assertEqual(len(steps), 2 * (3 * 2 + 1))
        for b in steps:
            self.assertTrue(b["stream"])
            self.assertEqual(b["keep_alive"], "15m")
            for k in ("format", "think"):
                self.assertNotIn(k, b)
            self.assertEqual(set(b["options"]), {"num_ctx"})  # no seed, temperature or num_predict
            self.assertEqual([m["role"] for m in b["messages"]], ["system", "user"])
        expected = []
        for pn in ("today", "contract"):
            for c in C.load_cases(ES, ids=self.CASES):  # by part, then file order
                req = C.request(c, pn)
                n = 1 if c.prose else 2
                expected += [(req["messages"], common.ctx_bucket(req["need_ctx"], 40960))] * n
        self.assertEqual([(b["messages"], b["options"]["num_ctx"]) for b in steps], expected)
        self.assertIn(32768, {b["options"]["num_ctx"] for b in steps})  # the long input needs the 32K bucket
        by = {d.rsplit("-", 1)[-1]: d for d in self.run_dirs("runs")}
        self.assertEqual(sorted(by), ["contract", "today"])
        dirs = [by["today"], by["contract"]]
        for d in dirs:
            for name in ("meta.json", "raw.jsonl", "summary.json", "summary.md"):
                self.assertTrue(os.path.exists(os.path.join(d, name)), name)
            recs = self.read_jsonl(os.path.join(d, "raw.jsonl"))
            self.assertEqual(len(recs), 7)
            with open(os.path.join(d, "summary.json"), encoding="utf-8") as f:
                s = json.load(f)
            self.assertEqual(s["summary"]["all"]["n"], 7)
            self.assertIn("EVAL ONLY", s["meta"]["eval_only"])
        contract = self.read_jsonl(os.path.join(dirs[1], "raw.jsonl"))
        self.assertTrue(all(r["score"]["contract"]["contract_ok"] for r in contract if r["mode"] == "blender"))
        runs = {r["id"]: r["score"]["blender"]["run"] for r in contract if r["mode"] == "blender"}
        # w4l-04's inputs are plain scripts (rebuilt from W1 references), so they run before the piece, unjoined
        self.assertEqual(runs, {"w2-01": "joined", "w3-05": "joined", "w4l-04": "after_deps"})
        today = self.read_jsonl(os.path.join(dirs[0], "raw.jsonl"))
        self.assertFalse(any(r["score"]["contract"]["contract_ok"] for r in today if r["mode"] == "blender"))
        self.assertTrue(any("repair" in n for r in today for n in r["notes"]))  # W3 under today's prompt is marked
        # the fake Blender saw the joined script for the contract's Blender replies, both runs per sample
        kinds = [k for k, _, _ in fake.calls]
        self.assertEqual(kinds.count("check"), kinds.count("probe"))
        self.assertEqual(len(self.requests("/api/generate")), 1)  # unloaded afterwards: it wasn't loaded before

    def test_contract_request_carries_the_dependency_and_round2(self):
        self.CASES = ["w4l-04"]
        code, err = self.run_step("--prompt", "contract", "--no-blender", "--samples", "1")
        self.assertEqual(code, 0, err)
        b = self.requests()[1]
        user = b["messages"][1]["content"]
        self.assertTrue(user.startswith("Your step, s8:"))
        self.assertIn("Last round's result for your part:", user)
        self.assertIn("What still needs work:", user)
        self.assertIn("Its handoff:\nprovides:", user)
        self.assertTrue(b["messages"][0]["content"].startswith(mock_ollama.CONTRACT_OPENING))

    def test_loaded_model_stays_loaded_and_ctx_max_caps(self):
        mock_ollama.Handler.loaded = ["mock:latest"]
        self.CASES = ["w4l-04"]
        code, err = self.run_step("--prompt", "today", "--no-blender", "--samples", "1", "--ctx-max", "16384")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.requests()[1]["options"]["num_ctx"], 16384)
        self.assertEqual(self.requests("/api/generate"), [])

    def test_reply_cap_cuts_worker_replies_as_runaways(self):
        self.CASES = ["w2-01"]
        mock_ollama.Handler.extra = [lambda s, u, b: None if u == "Reply with OK." else "x" * 4000]
        fake = FakeBlender()
        # the cap is 2 tokens: the warm-up ("OK", two chunks) isn't a worker reply, so only the guard applies to it
        code, err = self.run_step("--prompt", "contract", "--samples", "1", "--reply-cap", "2", blender=fake)
        self.assertEqual(code, 0, err)
        d = self.run_dirs("runs")[0]
        rec = self.read_jsonl(os.path.join(d, "raw.jsonl"))[0]
        self.assertTrue(rec["runaway"])
        self.assertIsNone(rec["error"])
        self.assertIn("reply cap", rec["runaway_error"])
        self.assertEqual(rec["done_reason"], common.RUNNER_CUT)
        self.assertEqual((rec["stats"]["runner_limit"], rec["stats"]["runner_limit_kind"]), (2, "cap"))
        self.assertEqual(self.requests()[1]["options"], {"num_ctx": 8192})  # the request itself is unchanged
        sc = rec["score"]
        self.assertTrue(sc["runaway"])
        self.assertFalse(sc["cut_off"])  # a failure of its own, apart from Ollama's own length stop
        self.assertIn("cut_off", sc["contract"]["errors"])  # to the validator it is a piece cut off
        self.assertEqual(sc["blender"]["run"], "none")
        self.assertEqual(len(self.requests()), 2)  # warm-up and the one case: a runaway isn't asked again
        with open(os.path.join(d, "summary.json"), encoding="utf-8") as f:
            s = json.load(f)
        a = s["summary"]["all"]
        self.assertEqual((a["runaway"], a["runaway_n"], a["cut_off"], a["blender_n"], a["strict_5.2.2"]),
                         (100.0, 1, 0.0, 1, 0.0))  # counted, as a fail
        self.assertEqual(a["unchecked"], {"no_script": 0, "runaway": 1})
        self.assertEqual(s["meta"]["reply_cap"], 2)
        self.assertTrue(any("cut after 2 tokens" in x for x in s["meta"]["differences_from_chimera"]))

    def test_runaway_guard_still_applies_below_the_cap(self):
        self.CASES = ["w2-01"]
        mock_ollama.Handler.extra = [lambda s, u, b: None if u == "Reply with OK." else "x" * 4000]
        code, err = self.run_step("--prompt", "contract", "--no-blender", "--samples", "1", "--max-reply-tokens", "2")
        self.assertEqual(code, 0, err)
        rec = self.read_jsonl(os.path.join(self.run_dirs("runs")[0], "raw.jsonl"))[0]
        self.assertTrue(rec["runaway"] and rec["score"]["runaway"])
        self.assertEqual(rec["stats"]["runner_limit_kind"], "guard")

    def test_client_limits(self):
        client = common.Ollama(self.url, 30)
        mock_ollama.Handler.extra = [lambda s, u, b: "y" * 300]
        body = common.chat_body("mock:latest", [{"role": "user", "content": "hi"}], 100)
        self.assertIsNone(common.ask(client, body, 30)["error"])  # not a worker reply: the guard only
        call = common.ask(client, body, 30, worker=True)
        self.assertIsNone(call["error"])  # 3 chunks, under the default cap
        client.reply_cap = 2
        call = common.ask(client, body, 30, worker=True)
        self.assertTrue(common.runaway(call))
        self.assertEqual((call["attempts"], call["stats"]["eval_count"]), (1, 2))
        self.assertEqual(common.REPLY_CAP, 6144)  # Hydra Worker's num_predict (docs/hydra-worker-plan.md, Modelfile)
        with open(os.path.join(_paths.REPO, "docs", "hydra-worker-plan.md"), encoding="utf-8") as f:
            self.assertIn("num_predict 6144, as a guard against runaways", f.read())

    def test_thinking_runs_to_the_guard_and_content_to_the_cap(self):
        client = common.Ollama(self.url, 30)
        body = common.chat_body("mock:latest", [{"role": "user", "content": "hi"}], 100)

        def reply(thinking, content):
            mock_ollama.Handler.extra = [lambda s, u, b: {"thinking": "t" * thinking, "content": "c" * content, "chunk": 1}]
            return common.ask(client, body, 30, worker=True)
        client.reply_cap, client.max_tokens = 5, 100
        call = reply(20, 3)  # 20 thinking tokens and 3 of content: thinking doesn't count toward the cap of 5
        self.assertIsNone(call["error"])
        self.assertFalse(common.runaway(call))
        self.assertEqual((call["stats"]["content_tokens"], call["stats"]["thinking_tokens"]), (3, 20))
        self.assertEqual((len(call["thinking"]), call["content"]), (20, "ccc"))
        call = reply(20, 10)  # content over the cap: a runaway in content
        self.assertTrue(common.runaway(call))
        st = call["stats"]
        self.assertEqual((st["runner_limit_kind"], st["runaway_in"], st["runner_limit"]), ("cap", "content", 5))
        self.assertEqual((st["content_tokens"], st["thinking_tokens"], st["eval_count"]), (5, 20, 25))
        self.assertEqual(common.runaway_in(call), "content")
        client.max_tokens = 30
        call = reply(50, 3)  # still thinking at the guard: a runaway in thinking, with no content at all
        st = call["stats"]
        self.assertEqual((st["runner_limit_kind"], st["runaway_in"], st["content_tokens"], st["eval_count"]),
                         ("guard", "thinking", 0, 30))
        self.assertIn("while thinking", call["error"])
        self.assertEqual(common.call_fields(call)["runaway_in"], "thinking")
        client.reply_cap = 50
        call = reply(25, 10)  # the guard hit while it wrote content (under the cap): a runaway in content
        self.assertEqual((call["stats"]["runner_limit_kind"], call["stats"]["runaway_in"]), ("guard", "content"))
        call = common.ask(client, body, 30)  # not a worker reply: the guard only, thinking included
        self.assertEqual(call["stats"]["runner_limit_kind"], "guard")
        self.assertIsNone(common.runaway_in({"stats": {"done_reason": "stop"}}))

    def test_runaway_in_thinking_is_recorded_and_summarised(self):
        self.CASES = ["w2-01"]
        mock_ollama.Handler.extra = [lambda s, u, b: None if u == "Reply with OK." else
                                     {"thinking": "t" * 40, "content": "c" * 40, "chunk": 1}]
        code, err = self.run_step("--prompt", "contract", "--no-blender", "--samples", "2", "--reply-cap", "50",
                                  "--max-reply-tokens", "30")
        self.assertEqual(code, 0, err)
        d = self.run_dirs("runs")[0]
        recs = self.read_jsonl(os.path.join(d, "raw.jsonl"))
        self.assertEqual([(r["runaway"], r["runaway_in"], r["score"]["runaway_in"]) for r in recs],
                         [(True, "thinking", "thinking")] * 2)
        with open(os.path.join(d, "summary.json"), encoding="utf-8") as f:
            s = json.load(f)
        a = s["summary"]["all"]
        self.assertEqual((a["runaway_n"], a["runaway_thinking_n"], a["runaway_content_n"]), (2, 2, 0))
        diffs = " ".join(s["meta"]["differences_from_chimera"])
        self.assertIn("thinking doesn't count toward it", diffs)
        self.assertIn("no num_predict and no think field", diffs)
        self.assertIn("runaway in thinking", diffs)
        with open(os.path.join(d, "summary.md"), encoding="utf-8") as f:
            md = f.read()
        self.assertIn("(2 thinking, 0 content)", md)
        self.assertIn("RUNAWAY in thinking", err)
        for b in self.requests()[1:]:
            self.assertEqual(set(b["options"]), {"num_ctx"})  # still nothing sent: no num_predict, no think
            self.assertNotIn("think", b)

    def test_missing_model_and_dry_run(self):
        code, _ = self.quiet(step_eval.main, ["--model", "missing:x", "--host", self.url, "--case", "w2-01",
                                              "--no-blender", "--out", os.path.join(self.tmp, "runs")])
        self.assertEqual(code, 2)
        code, _ = self.quiet(step_eval.main, ["--model", "m", "--host", "127.0.0.1:9", "--case", "w2-01", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(self.requests(), [])


class CaseTests(unittest.TestCase):
    def test_inputs_become_replies_with_and_without_handoff(self):
        c = C.load_cases(ES, ids=["w4f-04"])[0]
        self.assertIsNone(c.outputs["s2"])  # failed
        self.assertIn("```handoff\nprovides: ctx['objects']['product']", c.outputs["s1"])
        self.assertNotIn("```handoff", c.outputs_today["s1"])
        self.assertTrue(c.outputs_today["s1"].startswith("```python"))
        self.assertEqual((c.sid, c.deps, c.mode), ("s3", ["s1", "s2"], "blender"))

    def test_round2_and_repair_cases(self):
        c = C.load_cases(ES, ids=["w4l-04"])[0]
        self.assertTrue(c.prev_result and c.critique)
        r = C.request(c, "today")
        self.assertNotIn("Last round's result", r["messages"][1]["content"])
        self.assertTrue(any("never see the last round's result" in n for n in r["notes"]))
        w3 = C.load_cases(ES, ids=["w3-01"])[0]
        crash = w3.repair["crash"]
        self.assertEqual((crash["piece_line"], crash["function"], crash["runner"]), (22, "build_s1", "Blender 5.2.2"))
        req = C.request(w3, "contract")
        self.assertIn("Your piece crashed when Chimera ran the joined script in Blender 5.2.2:\nline 22 in build_s1:",
                      req["messages"][1]["content"])
        self.assertIn("Your piece was:\n```python", req["messages"][1]["content"])

    def test_quick_subset_and_limits(self):
        cs = C.load_cases(ES, quick=True, frozen_dir=os.path.join(_paths.HERE, "no-such-frozen"))
        self.assertEqual(len(cs), len(ES.quick["cases"]))  # W1 adds nothing until plans are frozen
        self.assertEqual(len(C.load_cases(ES, parts=["w2", "w3"], limit=2)), 4)
        # The runners use the mode the contract's rule reads off the plan (what Chimera would do). One case states
        # another: w4l-10 is a writing step that writes README.md, "files" in the eval but "section" by the rule.
        odd = {c.id: (c.mode, c.eval_mode) for c in C.load_cases(ES, parts=["w2", "w3", "w4f", "w4l"]) if c.mode != c.eval_mode}
        self.assertEqual(odd, {"w4l-10": ("section", "files")})


if __name__ == "__main__":
    unittest.main()
