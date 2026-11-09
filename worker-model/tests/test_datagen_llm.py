"""datagen/llm.py: the Gate under threads (groups, waiters on both sides, late waiters and the idle switch,
starvation, a switch waiting for the calls in flight, parallel slots, STOP while waiting), and the LLM against
runner/mock_ollama (Chimera's body, the cache and its key, the seed, stats, unloading, errors and runaways).

Every canned reply and message here carries runner/mock_ollama.MARK: test text, never training data."""
import json
import os
import random
import shutil
import tempfile
import threading
import time
import unittest

from tests import _paths  # noqa: F401
from datagen import common as C
from datagen import llm as L
from runner import common as rc
from runner import mock_ollama
from runner.mock_ollama import MARK

TOL = 0.15  # seconds of slack for a busy machine


class Calls:
    """Runs fake calls through a gate in threads and records when each held its slot."""

    def __init__(self, gate):
        self.gate = gate
        self.lock = threading.Lock()
        self.done = []  # (model, start, end, waited_s), in the order calls ended
        self.raised = []  # (model, exception type, time)
        self.threads = []
        self.t0 = time.monotonic()

    def one(self, model, dur, purpose="test"):
        try:
            with self.gate.slot(model, purpose) as t:
                s = time.monotonic()
                time.sleep(dur)
                e = time.monotonic()
        except BaseException as ex:  # noqa: BLE001
            with self.lock:
                self.raised.append((model, type(ex), time.monotonic() - self.t0))
            return
        with self.lock:
            self.done.append((model, s - self.t0, e - self.t0, t.waited_s))

    def at(self, delay, fn, *a):
        """Start fn(*a) in a thread delay seconds after t0."""
        def run():
            time.sleep(max(0.0, self.t0 + delay - time.monotonic()))
            fn(*a)
        th = threading.Thread(target=run, daemon=True)
        th.start()
        self.threads.append(th)
        return th

    def call_at(self, delay, model, dur):
        return self.at(delay, self.one, model, dur)

    def join(self, test, timeout=30):
        end = time.monotonic() + timeout
        for th in self.threads:
            th.join(max(0.0, end - time.monotonic()))
        test.assertFalse(any(th.is_alive() for th in self.threads), "a thread never got its slot")

    def order(self):
        return [m for m, s, e, w in sorted(self.done, key=lambda x: x[1])]

    def starts(self, model):
        return sorted(s for m, s, e, w in self.done if m == model)

    def ends(self, model):
        return sorted(e for m, s, e, w in self.done if m == model)


def check_invariants(test, gate, done, parallel):
    """Calls of two groups never overlap, and no more than `parallel` calls of a group run at once."""
    for i, (m1, s1, e1, _) in enumerate(done):
        for m2, s2, e2, _ in done[i + 1:]:
            if gate.group_of(m1) != gate.group_of(m2):
                test.assertFalse(max(s1, s2) < min(e1, e2), f"{m1} {s1:.3f}-{e1:.3f} overlaps {m2} {s2:.3f}-{e2:.3f}")
    points = sorted([(s, 1) for _, s, _, _ in done] + [(e, -1) for _, _, e, _ in done], key=lambda p: (p[0], p[1]))
    n = peak = 0
    for _, d in points:
        n += d
        peak = max(peak, n)
    test.assertLessEqual(peak, parallel)
    return peak


class GateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wm-dg-gate-")
        self.log = os.path.join(self.tmp, "gate.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def switches(self):
        return [r for r in C.read_jsonl(self.log) if r.get("event") == "switch"]

    def settled(self, gate):
        st = gate.stats()
        self.assertEqual(st["in_flight"], 0)
        self.assertEqual(st["waiting"], {})
        self.assertIsNone(st["pending"])
        return st


class GateGroupTests(GateCase):
    def test_groups_and_labels(self):
        g = L.Gate([{"a1", "a2"}, {"b"}])
        self.assertEqual(g.group_of("a2"), "a1+a2")
        self.assertEqual(g.group_of("b"), "b")
        self.assertEqual(g.group_of("new:1b"), "new:1b")  # a model in no group is its own group
        d = L.Gate(None)
        self.assertEqual(d.group_of("hydra:1.0"), d.group_of("gpt-oss:120b"))
        self.assertNotEqual(d.group_of("qwen3.8:27b"), d.group_of("gpt-oss:120b"))
        self.assertNotEqual(d.group_of("qwen3.8:27b"), d.group_of("qwen3:8b"))
        with self.assertRaises(ValueError):
            L.Gate([{"a", "b"}, {"b"}])
        with self.assertRaises(ValueError):
            L.Gate(None, parallel=0)

    def test_one_group_runs_one_at_a_time(self):
        gate = L.Gate([{"a"}], parallel=1, log_path=self.log)
        c = Calls(gate)
        for i in range(5):
            c.call_at(0.0, "a", 0.03)
        c.join(self)
        self.assertEqual(len(c.done), 5)
        self.assertEqual(check_invariants(self, gate, c.done, 1), 1)
        st = self.settled(gate)
        self.assertEqual(st["groups"]["a"]["calls"], 5)
        self.assertEqual(st["switches_by_why"], {"start": 1, "idle": 0, "starve": 0})
        self.assertEqual([(s["from"], s["to"], s["why"]) for s in self.switches()], [(None, "a", "start")])

    def test_parallel_slots(self):
        gate = L.Gate([{"a1", "a2"}], parallel=2)
        c = Calls(gate)
        t = time.monotonic()
        for i in range(6):
            c.call_at(0.0, "a1" if i % 2 else "a2", 0.15)
        c.join(self)
        took = time.monotonic() - t
        self.assertEqual(check_invariants(self, gate, c.done, 2), 2)  # two at once, never three
        self.assertGreater(took, 0.44)
        self.assertLess(took, 0.45 + 3 * TOL)

    def test_an_exception_in_the_slot_gives_it_back(self):
        gate = L.Gate([{"a"}, {"b"}], idle_switch_s=0.01)
        with self.assertRaises(RuntimeError):
            with gate.slot("a"):
                raise RuntimeError("boom")
        with self.assertRaises(KeyboardInterrupt):
            with gate.slot("a"):
                raise KeyboardInterrupt
        self.settled(gate)
        time.sleep(0.03)
        with gate.slot("b") as t:  # nothing left holding "a"
            self.assertLess(t.waited_s, 0.5)
        self.settled(gate)


class GatePolicyTests(GateCase):
    def test_waiters_on_both_groups_active_first(self):
        gate = L.Gate([{"a1", "a2"}, {"b"}], parallel=1, idle_switch_s=0.2, starve_s=100, log_path=self.log)
        c = Calls(gate)
        c.call_at(0.0, "a1", 0.4)  # makes a1+a2 the active group
        c.call_at(0.05, "b", 0.05)  # b's waiters come first...
        c.call_at(0.06, "b", 0.05)
        for d in (0.1, 0.11, 0.12):  # ...but the active group's are served first
            c.call_at(d, "a2", 0.05)
        c.join(self)
        check_invariants(self, gate, c.done, 1)
        self.assertEqual(c.order(), ["a1", "a2", "a2", "a2", "b", "b"])
        last_a = max(c.ends("a1") + c.ends("a2"))
        self.assertGreaterEqual(c.starts("b")[0], last_a + 0.2 - 0.02)  # the idle wait
        self.assertLess(c.starts("b")[0], last_a + 0.2 + TOL)
        st = self.settled(gate)
        self.assertEqual(st["switches_by_why"], {"start": 1, "idle": 1, "starve": 0})
        sw = self.switches()
        self.assertEqual([(s["from"], s["to"], s["why"]) for s in sw], [(None, "a1+a2", "start"), ("a1+a2", "b", "idle")])
        self.assertEqual(sw[1]["waiters"], {"b": 2})
        self.assertGreater(sw[1]["waited_s"], 0.6)
        for s in sw:
            self.assertTrue({"t", "from", "to", "waiters", "waited_s"} <= set(s))
        self.assertEqual(st["groups"]["b"]["calls"], 2)
        self.assertEqual(st["groups"]["a1+a2"]["calls"], 4)
        self.assertEqual(st["models"]["a2"]["calls"], 3)
        self.assertGreater(st["groups"]["b"]["max_wait_s"], 0.6)
        self.assertGreater(st["groups"]["a1+a2"]["busy_s"], 0.5)
        self.assertGreater(st["groups"]["a1+a2"]["active_s"], 0.7)

    def test_switch_goes_to_the_group_with_most_waiters(self):
        gate = L.Gate([{"a"}, {"b"}, {"c"}], idle_switch_s=0.1, starve_s=100, log_path=self.log)
        c = Calls(gate)
        c.call_at(0.0, "a", 0.3)
        c.call_at(0.05, "b", 0.03)  # waited longest, but alone
        for d in (0.1, 0.11, 0.12):
            c.call_at(d, "c", 0.03)
        c.join(self)
        self.assertEqual(c.order(), ["a", "c", "c", "c", "b"])
        self.assertEqual([s["to"] for s in self.switches()], ["a", "c", "b"])
        self.settled(gate)

    def test_a_tie_goes_to_the_longest_wait(self):
        gate = L.Gate([{"a"}, {"b"}, {"c"}], idle_switch_s=0.1, starve_s=100)
        c = Calls(gate)
        c.call_at(0.0, "a", 0.3)
        c.call_at(0.1, "c", 0.03)
        c.call_at(0.11, "c", 0.03)
        c.call_at(0.05, "b", 0.03)
        c.call_at(0.12, "b", 0.03)
        c.join(self)
        self.assertEqual(c.order(), ["a", "b", "b", "c", "c"])

    def a_loop_with_gaps(self, c, gap, n=3):
        def loop():
            for _ in range(n):
                c.one("a", 0.05)
                time.sleep(gap)  # a Blender check between two calls
        return c.at(0.0, loop)

    def test_late_waiters_inside_the_idle_time_keep_the_group(self):
        gate = L.Gate([{"a"}, {"b"}], idle_switch_s=0.5, starve_s=100, log_path=self.log)
        c = Calls(gate)
        self.a_loop_with_gaps(c, 0.15)
        c.call_at(0.02, "b", 0.03)
        c.join(self)
        self.assertEqual(c.order(), ["a", "a", "a", "b"])
        last_a = c.ends("a")[-1]
        self.assertGreaterEqual(c.starts("b")[0], last_a + 0.5 - 0.02)
        self.assertEqual([s["why"] for s in self.switches()], ["start", "idle"])

    def test_late_waiters_after_the_idle_time_lose_the_group(self):
        gate = L.Gate([{"a"}, {"b"}], idle_switch_s=0.05, starve_s=100, log_path=self.log)
        c = Calls(gate)
        self.a_loop_with_gaps(c, 0.2)
        c.call_at(0.02, "b", 0.03)
        c.join(self)
        check_invariants(self, gate, c.done, 1)
        self.assertEqual(c.order(), ["a", "b", "a", "a"])  # b ran in a's first gap
        a_starts = c.starts("a")
        self.assertGreaterEqual(c.starts("b")[0], c.ends("a")[0] + 0.05 - 0.02)
        self.assertLess(c.starts("b")[0], a_starts[1])
        self.assertEqual([s["why"] for s in self.switches()], ["start", "idle", "idle"])
        self.assertEqual([s["to"] for s in self.switches()], ["a", "b", "a"])

    def a_stream(self, c, until, threads=2):
        """Keeps a's queue busy: each thread asks again as soon as its call ends."""
        def loop():
            while time.monotonic() - c.t0 < until:
                c.one("a", 0.05)
        for _ in range(threads):
            c.at(0.0, loop)

    def test_starvation_switch(self):
        gate = L.Gate([{"a"}, {"b"}], idle_switch_s=5.0, starve_s=0.3, log_path=self.log)
        c = Calls(gate)
        self.a_stream(c, 1.2)
        c.call_at(0.05, "b", 0.05)
        c.join(self)
        check_invariants(self, gate, c.done, 1)
        b = c.starts("b")[0]
        self.assertGreaterEqual(b, 0.05 + 0.3 - 0.02)  # it waited its starve_s...
        self.assertLess(b, 0.05 + 0.3 + 0.05 + TOL)  # ...plus at most the call in flight
        self.assertLess(b, c.ends("a")[-1])  # while a still had waiters
        a_after = [s for s in c.starts("a") if s > b]
        self.assertTrue(a_after, "a never got the gate back")
        st = self.settled(gate)
        self.assertGreaterEqual(st["switches_by_why"]["starve"], 2)  # to b, and back to a's waiters
        self.assertEqual(st["switches_by_why"]["idle"], 0)
        starve = [s for s in self.switches() if s["why"] == "starve"]
        self.assertEqual(starve[0]["to"], "b")
        self.assertGreaterEqual(starve[0]["waited_s"], 0.28)

    def test_without_starvation_the_active_group_keeps_going(self):
        gate = L.Gate([{"a"}, {"b"}], idle_switch_s=0.1, starve_s=100)
        c = Calls(gate)
        self.a_stream(c, 0.8)
        c.call_at(0.05, "b", 0.05)
        c.join(self)
        self.assertGreaterEqual(c.starts("b")[0], c.ends("a")[-1] + 0.1 - 0.02)  # only once a went quiet

    def test_two_busy_groups_take_turns(self):
        gate = L.Gate([{"a"}, {"b"}], idle_switch_s=5.0, starve_s=0.25, log_path=self.log)
        c = Calls(gate)

        def loop(model):
            while time.monotonic() - c.t0 < 1.6:
                c.one(model, 0.02)

        for m in ("a", "a", "b", "b"):
            c.at(0.0, loop, m)
        c.join(self)
        check_invariants(self, gate, c.done, 1)
        turns = []
        for m in c.order():
            if turns and turns[-1][0] == m:
                turns[-1][1] += 1
            else:
                turns.append([m, 1])
        self.assertGreaterEqual(len(turns), 3)
        self.assertLessEqual(len(turns), 1.6 / 0.25 + 2)
        # turns of starve_s, not one call each (the last two are cut short as the loops stop asking)
        self.assertTrue(all(n >= 4 for _, n in turns[:-2]), turns)
        self.assertEqual(gate.stats()["switches_by_why"]["idle"], 0)

    def test_a_switch_waits_for_the_calls_in_flight(self):
        gate = L.Gate([{"a"}, {"b"}], parallel=2, idle_switch_s=5.0, starve_s=0.1, log_path=self.log)
        c = Calls(gate)
        c.call_at(0.0, "a", 0.5)
        c.call_at(0.0, "a", 0.5)
        c.call_at(0.02, "b", 0.05)
        c.call_at(0.2, "a", 0.05)  # asks during the drain: not let in
        c.join(self)
        check_invariants(self, gate, c.done, 2)
        b = c.starts("b")[0]
        self.assertGreaterEqual(b, max(c.ends("a")[:2]))
        self.assertGreaterEqual(c.starts("a")[2], c.ends("b")[0])
        sw = [s for s in self.switches() if s["to"] == "b"][0]
        self.assertEqual(sw["why"], "starve")
        self.assertGreater(sw["drain_s"], 0.25)  # decided at about 0.12, made at about 0.5

    def test_many_threads_never_deadlock(self):
        gate = L.Gate([{"a1", "a2"}, {"b"}, {"c"}], parallel=2, idle_switch_s=0.03, starve_s=0.25, log_path=self.log)
        c = Calls(gate)
        models = ["a1", "a2", "b", "c"]

        def worker(seed):
            r = random.Random(seed)
            for _ in range(6):
                c.one(r.choice(models), r.random() * 0.02)
                time.sleep(r.random() * 0.03)

        for i in range(24):
            c.at((i % 6) * 0.01, worker, i)
        c.join(self, timeout=60)
        self.assertEqual(c.raised, [])
        self.assertEqual(len(c.done), 24 * 6)
        check_invariants(self, gate, c.done, 2)
        st = self.settled(gate)
        self.assertEqual(sum(g["calls"] for g in st["groups"].values()), 144)
        self.assertEqual(sum(m["calls"] for m in st["models"].values()), 144)
        self.assertEqual(st["switches"], len(self.switches()))


class GateStopTests(GateCase):
    def test_stop_while_threads_wait(self):
        gate = L.Gate([{"a"}, {"b"}], idle_switch_s=0.1, starve_s=100, log_path=self.log,
                      stop=lambda: C.check_stop(self.tmp))
        gate.poll_s = 0.05
        c = Calls(gate)
        c.call_at(0.0, "a", 0.6)  # in flight when STOP comes: finishes
        for d in (0.05, 0.06, 0.07):
            c.call_at(d, "b", 0.05)
        c.call_at(0.08, "a", 0.05)
        c.call_at(0.09, "a", 0.05)
        c.at(0.2, lambda: open(os.path.join(self.tmp, "STOP"), "w").close())
        c.join(self)
        self.assertEqual([(m, round(e - s, 1)) for m, s, e, w in c.done], [("a", 0.6)])
        self.assertEqual(sorted(m for m, _, _ in c.raised), ["a", "a", "b", "b", "b"])
        self.assertTrue(all(t is C.StopRequested for _, t, _ in c.raised))
        self.assertTrue(all(0.2 <= when < 0.2 + 0.05 + TOL for _, _, when in c.raised), c.raised)
        self.settled(gate)
        with self.assertRaises(C.StopRequested):  # asked while STOP is there: never queued
            with gate.slot("b"):
                pass
        self.settled(gate)
        os.remove(os.path.join(self.tmp, "STOP"))
        time.sleep(0.12)
        with gate.slot("b") as t:  # a is idle by now: b gets the gate at once
            self.assertLess(t.waited_s, TOL)
        self.assertEqual(self.settled(gate)["active"], "b")

    def test_stopping_the_last_waiter_of_a_pending_switch_cancels_it(self):
        flag = {"stop": False}

        def stop():
            if flag["stop"]:
                raise C.StopRequested("test")

        gate = L.Gate([{"a"}, {"b"}], idle_switch_s=5.0, starve_s=0.05, stop=stop)
        gate.poll_s = 0.02
        c = Calls(gate)
        c.call_at(0.0, "a", 0.4)
        c.call_at(0.01, "b", 0.05)  # starves at 0.06: a switch is pending until a's call ends

        def stop_b_then_ask_a():
            flag["stop"] = True
            time.sleep(0.06)
            flag["stop"] = False
            c.one("a", 0.05)

        c.at(0.15, stop_b_then_ask_a)
        c.join(self)
        self.assertEqual([m for m, _, _ in c.raised], ["b"])
        self.assertEqual(c.order(), ["a", "a"])
        st = self.settled(gate)
        self.assertEqual(st["active"], "a")
        self.assertEqual(st["switches"], 1)

    def test_long_waits_are_logged(self):
        gate = L.Gate([{"a"}], log_path=self.log)
        gate.wait_log_s = 0.1
        c = Calls(gate)
        c.call_at(0.0, "a", 0.3)
        c.call_at(0.05, "a", 0.01)
        c.join(self)
        waits = [r for r in C.read_jsonl(self.log) if r.get("event") == "wait"]
        self.assertEqual(len(waits), 1)
        self.assertEqual((waits[0]["model"], waits[0]["purpose"], waits[0]["to"]), ("a", "test", "a"))
        self.assertGreaterEqual(waits[0]["waited_s"], 0.2)
        self.assertTrue({"t", "from", "to", "waiters", "waited_s"} <= set(waits[0]))
        self.assertEqual(gate.stats()["waits_over_60"], 1)


class NoSlotGate(L.Gate):
    def slot(self, model, purpose=""):
        raise AssertionError("a cached reply asked the gate for a slot")


class LLMCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wm-dg-llm-")
        self.req_log = os.path.join(self.tmp, "requests.jsonl")
        self.srv, self.url = mock_ollama.serve(0, self.req_log)
        mock_ollama.Handler.extra.append(self.respond)
        self.replies = {}  # user text -> what the mock streams back
        self.delay = 0.0
        self.cache_path = os.path.join(self.tmp, "cache", "calls.jsonl")
        self.cache = C.Cache(self.cache_path)
        self.gate = L.Gate(None, idle_switch_s=0.01, log_path=os.path.join(self.tmp, "gate.jsonl"))
        self.llm = L.LLM(self.url, self.gate, self.cache, timeout=30)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def respond(self, system, user, body):
        if self.delay:
            time.sleep(self.delay)
        return self.replies.get(user, f"{MARK}\nA canned reply to {len(user)} characters.")

    def requests(self, path="/api/chat"):
        if not os.path.exists(self.req_log):
            return []
        with open(self.req_log, encoding="utf-8") as f:
            return [r["body"] for r in map(json.loads, f) if r["path"] == path]

    @staticmethod
    def msgs(user=f"{MARK}\nMake a thing.", system=f"{MARK}\nYou are a test."):
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]


class LLMBodyTests(LLMCase):
    def test_the_body_is_chimeras(self):
        msgs = [dict(m, images=["x"], name="n") for m in self.msgs()]
        r = self.llm.call("gpt-oss:120b", msgs, purpose="seed")
        self.assertEqual(self.requests(), [{
            "model": "gpt-oss:120b", "messages": self.msgs(), "stream": True, "keep_alive": "15m",
            "options": {"num_ctx": 32768, "seed": C.stable_int(r.key)}}])
        self.assertTrue(r.ok and not r.cached and not r.runaway)
        self.assertTrue(r.content.startswith(MARK))
        self.assertEqual((r.model, r.purpose, r.sample, r.seed, r.num_ctx, r.attempts),
                         ("gpt-oss:120b", "seed", 0, C.stable_int(r.key), 32768, 1))
        self.assertEqual(r.done_reason, "stop")
        json.dumps(r.record())

    def test_format_and_think_only_when_given(self):
        self.llm.call("hydra:1.0", self.msgs(), purpose="plan", fmt="json", think=False)
        self.llm.call("gpt-oss:120b", self.msgs(), purpose="judge", fmt={"type": "object"}, think="low",
                      options={"temperature": 0})
        a, b = self.requests()
        self.assertEqual((a["format"], a["think"]), ("json", False))
        self.assertEqual(a["options"]["num_ctx"], 8192)  # hydra:1.0: the bucket
        self.assertEqual((b["format"], b["think"]), ({"type": "object"}, "low"))
        self.assertEqual(set(b["options"]), {"num_ctx", "temperature", "seed"})
        self.assertEqual(b["options"]["temperature"], 0)

    def test_num_ctx(self):
        self.assertEqual(L.FIXED_CTX, {"gpt-oss:120b": 32768, "qwen3.8:27b": 32768, "qwen3:8b": 32768})
        cases = [
            ("hydra:1.0", "x" * 100, None, None, 8192),
            ("hydra:1.0", "x" * 30000, None, None, 32768),  # 10,064 + 4,096 tokens: the 32K bucket
            ("hydra:1.0", "x" * 100000, None, None, 65536),
            ("qwen3:8b", "x" * 100, None, None, 32768),  # fixed
            ("gpt-oss:120b", "x" * 100000, None, None, 65536),  # fixed, unless the prompt needs more
            ("gpt-oss:120b", "x" * 100, 16384, None, 16384),  # the argument wins
            ("hydra:1.0", "x" * 100, None, {"num_ctx": 12288}, 12288),  # so does options' num_ctx
        ]
        for model, text, n, opts, want in cases:
            key, body = self.llm.request(model, self.msgs(MARK + text), options=opts, num_ctx=n)
            self.assertEqual(body["options"]["num_ctx"], want, (model, len(text), n, opts))
            self.assertEqual(L.ctx_for(model, self.msgs(MARK + text), n or (opts or {}).get("num_ctx")), want)
        self.assertEqual(rc.ctx_bucket(C.msgs_tokens(self.msgs()) + 4096), 8192)

    def test_worker_calls_hold_the_content_cap(self):
        self.llm.client.reply_cap = 5  # instead of 6,144, so the mock needn't stream thousands of chunks
        long = {"content": MARK + " " + "word " * 40, "chunk": 4}
        u = f"{MARK}\nA long one."
        self.replies[u] = long
        r = self.llm.call("qwen3:8b", self.msgs(u), purpose="piece", worker=True)
        self.assertTrue(r.runaway)
        self.assertEqual(r.done_reason, rc.RUNNER_CUT)
        self.assertTrue(r.error.startswith("runaway"))
        self.assertFalse(r.ok)
        self.assertIsNotNone(self.cache.get(r.key))  # a runaway is the reply's own property: cached
        again = self.llm.call("qwen3:8b", self.msgs(u), purpose="piece", worker=True)
        self.assertTrue(again.cached and again.runaway)
        self.assertEqual(again.content, r.content)
        free = self.llm.call("qwen3:8b", self.msgs(u), purpose="piece")  # not a worker: no cap, another key
        self.assertNotEqual(free.key, r.key)
        self.assertTrue(free.ok and not free.runaway)
        self.assertEqual(free.content, long["content"])
        self.assertEqual(len(self.requests()), 2)
        st = self.llm.stats()["qwen3:8b"]["piece"]
        self.assertEqual((st["calls"], st["cached"], st["runaways"], st["errors"]), (2, 1, 1, 0))

    def test_thinking_is_counted_not_kept(self):
        u = f"{MARK}\nThink first."
        self.replies[u] = {"thinking": "t" * 120, "content": MARK + " done"}
        r = self.llm.call("gpt-oss:120b", self.msgs(u), purpose="seed")
        self.assertEqual(r.thinking_chars, 120)
        self.assertEqual(r.content, MARK + " done")
        self.assertNotIn("t" * 120, json.dumps(self.cache.get(r.key)))


class LLMCacheTests(LLMCase):
    def test_a_cached_reply_needs_no_slot(self):
        r1 = self.llm.call("gpt-oss:120b", self.msgs(), purpose="seed")
        self.assertEqual(len(self.requests()), 1)
        r2 = self.llm.call("gpt-oss:120b", self.msgs(), purpose="other")  # purpose isn't part of the request
        self.assertTrue(r2.cached)
        self.assertEqual((r2.key, r2.content, r2.seed, r2.wall_s), (r1.key, r1.content, r1.seed, r1.wall_s))
        self.assertEqual(len(self.requests()), 1)
        resumed = L.LLM(self.url, NoSlotGate(None), C.Cache(self.cache_path))  # a resumed run, from the file
        r3 = resumed.call("gpt-oss:120b", self.msgs(), purpose="seed")
        self.assertTrue(r3.cached)
        self.assertEqual(r3.content, r1.content)
        self.assertEqual(len(self.requests()), 1)
        value = self.cache.get(r1.key)
        for k in ("model", "purpose", "sample", "seed", "num_ctx", "content", "thinking_chars", "stats",
                  "done_reason", "error", "wall_s", "attempts", "t"):
            self.assertIn(k, value)
        with open(self.cache_path, encoding="utf-8") as f:
            self.assertEqual([set(json.loads(l)) for l in f], [{"key", "value"}])

    def test_an_error_is_not_cached(self):
        r = self.llm.call("missing-model", self.msgs(), purpose="seed")
        self.assertIsNotNone(r.error)
        self.assertIn("not found", r.error)
        self.assertFalse(r.runaway or r.cached)
        self.assertEqual(r.attempts, 2)  # runner.common.ask's second try
        self.assertIsNone(self.cache.get(r.key))
        self.assertEqual(len(self.requests()), 2)
        r2 = self.llm.call("missing-model", self.msgs(), purpose="seed")
        self.assertFalse(r2.cached)
        self.assertEqual(len(self.requests()), 4)  # asked again
        self.assertEqual(len(self.cache), 0)
        st = self.llm.stats()["missing-model"]["seed"]
        self.assertEqual((st["calls"], st["errors"], st["cached"]), (2, 2, 0))

    def test_what_changes_the_key(self):
        def key(**kw):
            model = kw.pop("model", "gpt-oss:120b")
            msgs = kw.pop("msgs", self.msgs())
            return self.llm.request(model, msgs, **kw)

        base, body = key()
        self.assertEqual(key(), (base, body))  # the same request, the same key and seed
        self.assertEqual(key(msgs=[dict(m, images=["i"]) for m in self.msgs()])[0], base)  # only what is sent
        variants = {
            "model": key(model="qwen3:8b")[0],
            "messages": key(msgs=self.msgs(MARK + " other"))[0],
            "system": key(msgs=self.msgs(system=MARK + " other"))[0],
            "options": key(options={"temperature": 0})[0],
            "num_predict": key(options={"num_predict": 7000})[0],
            "num_ctx": key(num_ctx=65536)[0],
            "fmt": key(fmt="json")[0],
            "think": key(think=False)[0],
            "think_low": key(think="low")[0],
            "worker": key(worker=True)[0],
            "sample": key(sample=1)[0],
        }
        self.assertNotIn(base, variants.values())
        self.assertEqual(len(set(variants.values())), len(variants))
        seeds = [key(sample=i)[1]["options"]["seed"] for i in range(5)]
        self.assertEqual(len(set(seeds)), 5)  # samples differ...
        self.assertEqual(seeds, [key(sample=i)[1]["options"]["seed"] for i in range(5)])  # ...and replay the same
        for i in range(5):
            k, b = key(sample=i)
            self.assertEqual(b["options"]["seed"], C.stable_int(k))
        self.assertEqual(base, C.key_of("gpt-oss:120b", self.msgs(), {"num_ctx": 32768}, None, None, False, 0))
        k5, b5 = key(options={"seed": 5})  # a seed the caller gives is sent as it is, and counts in the key
        self.assertEqual(b5["options"]["seed"], 5)
        self.assertNotEqual(k5, base)
        self.assertNotEqual(k5, key(options={"seed": 6})[0])

    def test_identical_calls_from_two_threads_run_once(self):
        self.delay = 0.3
        gate = L.Gate(None, parallel=4)
        llm = L.LLM(self.url, gate, self.cache, timeout=30)
        out = []
        threads = [threading.Thread(target=lambda: out.append(llm.call("qwen3:8b", self.msgs(), purpose="p")))
                   for _ in range(4)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(30)
        self.assertEqual(len(out), 4)
        self.assertEqual(len(self.requests()), 1)
        self.assertEqual(sorted(r.cached for r in out), [False, True, True, True])
        self.assertEqual(len({r.content for r in out}), 1)
        self.assertEqual(llm._key_locks, {})

    def test_stats(self):
        self.replies[MARK + " one"] = MARK + " " + "a" * 400
        self.replies[MARK + " two"] = MARK + " " + "b" * 80
        msgs1, msgs2 = self.msgs(MARK + " one"), self.msgs(MARK + " two")
        self.llm.call("gpt-oss:120b", msgs1, purpose="seed")
        self.llm.call("gpt-oss:120b", msgs2, purpose="seed")
        self.llm.call("gpt-oss:120b", msgs1, purpose="seed")  # cached
        self.llm.call("hydra:1.0", msgs1, purpose="plan")
        st = self.llm.stats()
        s = st["gpt-oss:120b"]["seed"]
        text1, text2 = self.replies[MARK + " one"], self.replies[MARK + " two"]
        prompt = lambda m: sum(len(x["content"]) for x in m) // 4  # the mock's counters  # noqa: E731
        self.assertEqual((s["calls"], s["cached"], s["errors"], s["runaways"]), (2, 1, 0, 0))
        self.assertEqual(s["eval_tokens"], (len(text1) // 4 + 3) + (len(text2) // 4 + 3))
        self.assertEqual(s["prompt_tokens"], prompt(msgs1) + prompt(msgs2))
        self.assertGreater(s["wall_s"], 0)
        self.assertGreater(s["cached_wall_s"], 0)
        self.assertEqual(st["hydra:1.0"]["plan"]["calls"], 1)
        json.dumps(st)
        g = self.gate.stats()
        self.assertEqual(g["groups"]["gpt-oss:120b+hydra:1.0"]["calls"], 3)  # the cached one took no slot


class LLMUnloadTests(LLMCase):
    def test_a_switch_unloads_only_what_this_llm_loaded(self):
        mock_ollama.Handler.loaded = ["qwen3.8:27b"]  # loaded by someone else
        self.llm.call("gpt-oss:120b", self.msgs(), purpose="seed")
        self.llm.call("hydra:1.0", self.msgs(), purpose="plan")  # same group: nothing unloaded
        self.assertEqual(self.requests("/api/generate"), [])
        self.llm.call("qwen3:8b", self.msgs(), purpose="mixed")
        self.assertEqual(self.requests("/api/generate"),
                         [{"model": "gpt-oss:120b", "keep_alive": 0, "stream": False},
                          {"model": "hydra:1.0", "keep_alive": 0, "stream": False}])
        self.llm.call("gpt-oss:120b", self.msgs(MARK + " again"), purpose="seed")
        self.assertEqual(self.requests("/api/generate")[-1]["model"], "qwen3:8b")
        self.llm.close()
        unloaded = [b["model"] for b in self.requests("/api/generate")]
        self.assertEqual(unloaded[-1], "gpt-oss:120b")
        self.assertNotIn("qwen3.8:27b", unloaded)

    def test_unload_off(self):
        llm = L.LLM(self.url, self.gate, self.cache, unload=False)
        llm.call("gpt-oss:120b", self.msgs(), purpose="seed")
        llm.call("qwen3:8b", self.msgs(), purpose="mixed")
        llm.close()
        self.assertEqual(self.requests("/api/generate"), [])


class LLMForeignTests(LLMCase):
    """Models someone else loaded (/api/ps) go to gate.jsonl as "foreign", at most once a minute, never failing a
    call."""

    def foreign(self):
        return [g for g in C.read_jsonl(os.path.join(self.tmp, "gate.jsonl")) if g.get("event") == "foreign"]

    def test_a_model_this_llm_never_called_is_logged(self):
        mock_ollama.Handler.loaded = ["gpt-oss:120b", "qwen3.8:27b"]  # gpt-oss from a start before, qwen3.8 not ours
        self.llm.call("gpt-oss:120b", self.msgs(), purpose="seed")
        got = self.foreign()
        self.assertEqual([g["models"] for g in got], [["qwen3.8:27b"]])
        self.assertIsInstance(got[0]["t"], float)
        mock_ollama.Handler.loaded = ["gpt-oss:120b", "llama3.1:70b"]
        self.llm.call("gpt-oss:120b", self.msgs(MARK + " two"), purpose="seed")  # within the minute: not asked
        self.llm.call("gpt-oss:120b", self.msgs(), purpose="seed")  # cached: no call, no look
        self.assertEqual(len(self.foreign()), 1)
        self.llm._ps_t -= L.PS_EVERY_S + 1  # a minute later
        self.llm.call("qwen3.8:27b", self.msgs(MARK + " three"), purpose="second")
        self.assertEqual([g["models"] for g in self.foreign()], [["qwen3.8:27b"], ["llama3.1:70b"]])
        self.llm._ps_t -= L.PS_EVERY_S + 1
        mock_ollama.Handler.loaded = ["gpt-oss:120b", "qwen3.8:27b"]  # both called by now (and since unloaded)
        self.llm.call("gpt-oss:120b", self.msgs(MARK + " four"), purpose="seed")
        self.assertEqual(len(self.foreign()), 2)

    def test_a_failed_look_doesnt_fail_the_call(self):
        def broken(method, path, body=None, timeout=30.0):
            if path == "/api/ps":
                raise ValueError("not JSON")
            return {}
        self.llm.client._json = broken
        r = self.llm.call("gpt-oss:120b", self.msgs(), purpose="seed")
        self.assertTrue(r.ok, r.error)
        self.assertEqual(self.foreign(), [])
        gate = L.Gate(None)  # no log path: nothing to write to
        llm = L.LLM(self.url, gate, self.cache, timeout=30)
        mock_ollama.Handler.loaded = ["llama3.1:70b"]
        self.assertTrue(llm.call("qwen3:8b", self.msgs(), purpose="mixed").ok)


class LLMStopTests(LLMCase):
    def test_stop_before_a_call(self):
        cached = self.llm.call("gpt-oss:120b", self.msgs(), purpose="seed")
        gate = L.Gate(None, stop=lambda: C.check_stop(self.tmp))
        llm = L.LLM(self.url, gate, self.cache)
        open(os.path.join(self.tmp, "STOP"), "w").close()
        with self.assertRaises(C.StopRequested):
            llm.call("gpt-oss:120b", self.msgs(MARK + " new"), purpose="seed")
        self.assertEqual(len(self.requests()), 1)
        self.assertEqual(len(self.cache), 1)
        again = llm.call("gpt-oss:120b", self.msgs(), purpose="seed")  # a cached reply needs no model
        self.assertTrue(again.cached)
        self.assertEqual(again.content, cached.content)


if __name__ == "__main__":
    unittest.main()
