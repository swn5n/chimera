"""datagen/common.py: keys and stable randomness, Chimera's token estimate, the stores under many threads, a killed
run's half-written last line, atomic writes, progress, stopping and RUN.json."""
import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import threading
import unittest

from tests import _paths  # noqa: F401
from datagen import common as C


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wm-dg-common-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def lines(self, path):
        with open(path, "rb") as f:
            return f.read().decode("utf-8").splitlines()


class KeyTests(unittest.TestCase):
    def test_key_of_is_sha256_of_sorted_json(self):
        parts = ("gpt-oss:120b", [{"role": "user", "content": "é ü"}], {"b": 1, "a": 2}, None, 0)
        want = hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]
        self.assertEqual(C.key_of(*parts), want)
        self.assertEqual(len(want), 24)
        self.assertEqual(C.key_of("m", {"a": 2, "b": 1}), C.key_of("m", {"b": 1, "a": 2}))  # dict order doesn't count
        self.assertNotEqual(C.key_of("m", 1), C.key_of("m", 2))
        self.assertNotEqual(C.key_of("m", None), C.key_of("m", ""))
        self.assertEqual(C.key_of(("a", 1)), C.key_of(["a", 1]))  # JSON has no tuples

    def test_key_of_refuses_what_json_cant_write(self):
        with self.assertRaises(TypeError):
            C.key_of({"a", "b"})  # a set's order would make the key unstable

    def test_stable_int_is_helper_models(self):
        # helper-model/datagen/common.py's formula (not imported: it puts helper-model on sys.path)
        for parts in [("a",), ("names", "n-blender-0001-02", "s1"), (1, 2.5, None)]:
            want = int(hashlib.sha256("\x1f".join(map(str, parts)).encode("utf-8")).hexdigest()[:8], 16)
            self.assertEqual(C.stable_int(*parts), want)
        with open(os.path.join(os.path.dirname(_paths.HERE), "helper-model", "datagen", "common.py"),
                  encoding="utf-8") as f:
            self.assertIn('hashlib.sha256("\\x1f".join(map(str, parts)).encode("utf-8")).hexdigest()[:8], 16)', f.read())

    def test_rng_and_chance_are_stable(self):
        self.assertEqual(C.rng("pick", "smoke", "blender").random(), C.rng("pick", "smoke", "blender").random())
        self.assertNotEqual(C.rng("pick", "smoke", "blender").random(), C.rng("pick", "night", "blender").random())
        self.assertEqual([C.chance(0.3, "planner", i) for i in range(50)],
                         [C.chance(0.3, "planner", i) for i in range(50)])
        share = sum(C.chance(0.3, "planner", i) for i in range(20000)) / 20000
        self.assertAlmostEqual(share, 0.3, delta=0.02)
        self.assertFalse(any(C.chance(0, "x", i) for i in range(500)))
        self.assertTrue(all(C.chance(1, "x", i) for i in range(500)))
        for i in range(200):  # the rule itself: stable_int % 10000 < p * 10000
            self.assertEqual(C.chance(0.25, "r", i), C.stable_int("r", i) % 10000 < 2500)


class TokenTests(unittest.TestCase):
    def test_est_tokens_is_chimeras(self):
        self.assertEqual(C.est_tokens(""), 64)
        self.assertEqual(C.est_tokens(None), 64)
        self.assertEqual(C.est_tokens("abc"), 65)
        self.assertEqual(C.est_tokens("é" * 3), 66)  # Go's len counts bytes: 6 // 3
        self.assertEqual(C.est_tokens("x" * 3000), 1064)
        with open(os.path.join(_paths.APP, "library.go"), encoding="utf-8") as f:
            self.assertIn("func estimateTokens(s string) int { return len(s)/3 + 64 }", f.read())

    def test_msgs_tokens_is_history_tokens(self):
        msgs = [{"role": "system", "content": "a" * 300}, {"role": "user", "content": "b" * 30}]
        self.assertEqual(C.msgs_tokens(msgs), (100 + 64) + (10 + 64))
        self.assertEqual(C.msgs_tokens([]), 0)
        with open(os.path.join(_paths.APP, "runprompt.go"), encoding="utf-8") as f:
            self.assertIn("n += estimateTokens(m.Content)", f.read())


class StoreTests(TmpCase):
    def test_add_get_has_len_all_and_reload(self):
        p = self.path("sub", "tasks.jsonl")
        s = C.Store(p)  # makes the folder
        self.assertEqual(len(s), 0)
        s.add({"key": "a", "n": 1})
        s.add({"key": "b", "n": 2, "text": "ünï"})
        s.add({"key": "a", "n": 3})  # the later line wins
        self.assertTrue(s.has("a") and "b" in s and not s.has("c"))
        self.assertEqual(s.get("a"), {"key": "a", "n": 3})
        self.assertIsNone(s.get("c"))
        self.assertEqual(len(s), 2)
        self.assertEqual([r["key"] for r in s.all()], ["a", "b"])
        self.assertEqual(len(self.lines(p)), 3)
        self.assertIn("ünï", self.lines(p)[1])  # ensure_ascii off
        s2 = C.Store(p)
        self.assertEqual(s2.get("a"), {"key": "a", "n": 3})
        self.assertEqual(s2.get("b")["text"], "ünï")
        self.assertEqual(sorted(s2.keys()), ["a", "b"])

    def test_a_record_json_cant_write_leaves_the_file_alone(self):
        p = self.path("s.jsonl")
        s = C.Store(p)
        s.add({"key": "a"})
        with self.assertRaises(TypeError):
            s.add({"key": "b", "bad": {1, 2}})
        self.assertEqual(self.lines(p), ['{"key": "a"}'])
        self.assertFalse(s.has("b"))

    def test_half_written_last_line_is_skipped_and_mended(self):
        p = self.path("calls.jsonl")
        good = json.dumps({"key": "a", "value": 1})
        with open(p, "w", encoding="utf-8") as f:
            f.write(good + "\n" + '{"key": "b", "value": "cut sho')  # a run killed mid-write
        s = C.Store(p)
        self.assertEqual(s.keys(), ["a"])
        with open(p, "rb") as f:
            self.assertTrue(f.read().endswith(b"\n"))  # the next line starts fresh
        s.add({"key": "c", "value": 3})
        s2 = C.Store(p)
        self.assertEqual(sorted(s2.keys()), ["a", "c"])
        self.assertEqual(self.lines(p)[-1], json.dumps({"key": "c", "value": 3}))
        C.Store(p)  # a file that already ends in a newline isn't touched again
        self.assertEqual(len(self.lines(p)), 3)

    def test_a_complete_last_line_without_its_newline_is_kept(self):
        p = self.path("s.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"key": "a"}) + "\n" + json.dumps({"key": "b"}))
        s = C.Store(p)
        self.assertEqual(s.keys(), ["a", "b"])
        s.add({"key": "c"})
        self.assertEqual(C.Store(p).keys(), ["a", "b", "c"])

    def test_cut_multibyte_and_junk_lines_are_skipped(self):
        p = self.path("s.jsonl")
        with open(p, "wb") as f:
            f.write(b'{"key": "a"}\n\n[1, 2]\n{"no_key": 1}\nnot json\n' + '{"key": "é'.encode("utf-8")[:-1])
        s = C.Store(p)
        self.assertEqual(s.keys(), ["a"])

    def test_line_separators_inside_a_record_dont_split_it(self):
        # json.dumps(ensure_ascii=False) leaves U+0085, U+2028 and U+2029 raw; str.splitlines would break there
        p = self.path("tasks.jsonl")
        s = C.Store(p)
        texts = {"a": "plain", "b": "one two", "c": "one\u0085two", "d": "one two", "e": "plain too"}
        for k, t in texts.items():
            s.add({"key": k, "text": t})
        self.assertEqual(len(self.lines(p)), 5 + 3)  # the test's own splitlines does break them
        again = C.Store(p)
        self.assertEqual(again.keys(), list(texts))
        self.assertEqual({k: again.get(k)["text"] for k in texts}, texts)
        self.assertEqual([r["key"] for r in C.read_jsonl(p)], list(texts))
        c = self.path("calls.jsonl")
        C.Cache(c).put("k", {"content": "x y"})
        self.assertEqual(C.Cache(c).get("k"), {"content": "x y"})

    def test_many_threads_adding_at_once(self):
        p = self.path("tasks.jsonl")
        s = C.Store(p)
        n_threads, per = 16, 150
        errors = []
        start = threading.Barrier(n_threads)

        def work(t):
            try:
                start.wait()
                for i in range(per):
                    s.add({"key": f"t{t}-{i}", "t": t, "i": i, "pad": "x" * (i * 37 % 3000)})
                    s.add({"key": "shared", "t": t, "i": i})
                    s.has(f"t{t}-{i}")
                    s.get("shared")
                    len(s)
                    if i % 50 == 0:
                        s.all()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=work, args=(t,)) for t in range(n_threads)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(len(s), n_threads * per + 1)
        lines = self.lines(p)
        self.assertEqual(len(lines), 2 * n_threads * per)
        recs = [json.loads(line) for line in lines]  # every line whole
        last_shared = [r for r in recs if r["key"] == "shared"][-1]
        self.assertEqual(s.get("shared"), last_shared)  # memory and file agree on the later line
        s2 = C.Store(p)
        self.assertEqual(len(s2), n_threads * per + 1)
        self.assertEqual(s2.get("shared"), last_shared)
        self.assertEqual(s2.get("t3-77")["pad"], "x" * (77 * 37 % 3000))


class CacheTests(TmpCase):
    def test_get_put_and_reload(self):
        p = self.path("cache", "runs.jsonl")
        c = C.Cache(p)
        self.assertIsNone(c.get("k"))
        c.put("k", {"verdict": "passed", "seconds": 1.5})
        self.assertEqual(c.get("k"), {"verdict": "passed", "seconds": 1.5})
        self.assertTrue(c.has("k"))
        self.assertEqual(self.lines(p), [json.dumps({"key": "k", "value": {"verdict": "passed", "seconds": 1.5}})])
        self.assertEqual(C.Cache(p).get("k"), {"verdict": "passed", "seconds": 1.5})

    def test_half_written_last_line(self):
        p = self.path("calls.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"key": "a", "value": {"content": "x"}}) + "\n" + '{"key": "b", "value": {"cont')
        c = C.Cache(p)
        self.assertIsNone(c.get("b"))
        self.assertEqual(c.get("a"), {"content": "x"})
        c.put("b", {"content": "y"})
        self.assertEqual(C.Cache(p).get("b"), {"content": "y"})

    def test_many_threads_putting_at_once(self):
        p = self.path("calls.jsonl")
        c = C.Cache(p)
        errors = []

        def work(t):
            try:
                for i in range(200):
                    k = C.key_of("m", t, i)
                    c.put(k, {"t": t, "i": i, "content": "é" * (i % 50)})
                    if c.get(k) != {"t": t, "i": i, "content": "é" * (i % 50)}:
                        errors.append((t, i))
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=work, args=(t,)) for t in range(12)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(60)
        self.assertEqual(errors, [])
        c2 = C.Cache(p)
        self.assertEqual(len(c2), 12 * 200)
        self.assertEqual(c2.get(C.key_of("m", 5, 199)), {"t": 5, "i": 199, "content": "é" * 49})


class FileTests(TmpCase):
    def test_write_and_read_jsonl(self):
        p = self.path("a", "seeds.jsonl")
        self.assertEqual(C.read_jsonl(p), [])
        C.write_jsonl(p, [{"a": 1}, {"b": "ü"}])
        self.assertEqual(C.read_jsonl(p), [{"a": 1}, {"b": "ü"}])
        self.assertFalse(os.path.exists(p + ".tmp"))
        C.write_jsonl(p, [{"c": 3}])  # replaced whole
        self.assertEqual(C.read_jsonl(p), [{"c": 3}])
        with open(p, "a", encoding="utf-8") as f:
            f.write('{"half": ')
        self.assertEqual(C.read_jsonl(p), [{"c": 3}])

    def test_write_json_is_atomic_and_read_json_has_a_default(self):
        p = self.path("b", "RUN.json")
        self.assertEqual(C.read_json(p, {"none": True}), {"none": True})
        C.write_json(p, {"size": "smoke", "ü": 1})
        self.assertEqual(C.read_json(p), {"size": "smoke", "ü": 1})
        self.assertFalse(os.path.exists(p + ".tmp"))

    def test_append_jsonl_mends_a_half_line_first(self):
        p = self.path("gate.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write('{"t": 1, "event": "sw')
        C.append_jsonl(p, {"t": 2})
        C.append_jsonl(p, {"t": 3})
        self.assertEqual(C.read_jsonl(p), [{"t": 2}, {"t": 3}])

    def test_append_jsonl_from_many_threads(self):
        p = self.path("gate.jsonl")
        threads = [threading.Thread(target=lambda t=t: [C.append_jsonl(p, {"t": t, "i": i, "x": "y" * 500})
                                                        for i in range(100)]) for t in range(10)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(60)
        rows = C.read_jsonl(p)
        self.assertEqual(len(rows), 1000)
        self.assertEqual(len(self.lines(p)), 1000)


class ProgressTests(TmpCase):
    def test_lines_and_counts_from_many_threads(self):
        log = self.path("progress.log")
        prog = C.Progress("tasks", 400, log)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            threads = [threading.Thread(target=lambda t=t: [prog.step(f"seed-{t}-{i}", "done", 1.25, skipped=i % 4 == 0)
                                                            for i in range(40)]) for t in range(10)]
            for th in threads:
                th.start()
            for th in threads:
                th.join(60)
        self.assertEqual(prog.done, 400)
        self.assertEqual(prog.new, 300)
        lines = self.lines(log)
        self.assertEqual(len(lines), 300)
        self.assertEqual(len(err.getvalue().splitlines()), 300)
        self.assertTrue(all(" done 1.2s (left ~" in l or " done 1.3s (left ~" in l for l in lines), lines[:2])
        self.assertIn("[tasks 400/400]", "".join(lines))  # the counter reaches the total exactly once
        self.assertRegex(lines[0], r"^\d\d:\d\d:\d\d \[tasks \d+/400\] seed-")

    def test_no_log_path(self):
        prog = C.Progress("seeds", 2)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            prog.step("a", "kept")
        self.assertIn("[seeds 1/2] a kept (left ~", err.getvalue())


class StopTests(TmpCase):
    def test_check_stop(self):
        C.check_stop(self.tmp)  # nothing to stop
        with open(self.path("STOP"), "w"):
            pass
        with self.assertRaises(C.StopRequested):
            C.check_stop(self.tmp)
        os.remove(self.path("STOP"))
        C.check_stop(self.tmp)

    def test_write_stopped_and_stopped(self):
        path = C.write_stopped(self.tmp, "Stopped early", ["Only 3 of 25 steps kept.", "", "Run it again."])
        self.assertEqual(path, self.path("STOPPED.md"))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "# Stopped early\n\nOnly 3 of 25 steps kept.\n\nRun it again.\n")
        e = C.Stopped("tasks: only 3/25 kept")
        self.assertIsInstance(e, SystemExit)
        self.assertEqual(e.code, 3)
        self.assertEqual(str(e), "tasks: only 3/25 kept")
        self.assertFalse(issubclass(C.StopRequested, SystemExit))  # threads raise it; run.py turns it into exit 3


class RunRecordTests(TmpCase):
    def test_keeps_earlier_starts(self):
        r1 = C.run_record(self.tmp, size="smoke", args=["--size", "smoke"], started="2026-11-03T01:00:00+01:00")
        self.assertEqual(r1["starts"], [])
        r2 = C.run_record(self.tmp, size="smoke", args=["--limit", "2"])
        self.assertEqual(r2["args"], ["--limit", "2"])
        self.assertIn("started", r2)
        self.assertEqual(r2["starts"], [{"size": "smoke", "args": ["--size", "smoke"],
                                         "started": "2026-11-03T01:00:00+01:00"}])
        r3 = C.run_record(self.tmp, size="night")
        self.assertEqual([s.get("args") for s in r3["starts"]], [["--size", "smoke"], ["--limit", "2"]])
        self.assertEqual(C.read_json(self.path("RUN.json")), r3)

    def test_paths(self):
        self.assertEqual(C.HERE, _paths.HERE)
        self.assertEqual(C.DATA_ROOT, os.path.join(_paths.HERE, "data", "gen"))


if __name__ == "__main__":
    unittest.main()
