"""datagen/topics.py and datagen/seeds.py: the labels and their rotation, the teacher's instructions, reading its
replies, every drop reason, the helper's seeds by category, picking, and resuming from seed_calls.jsonl.

The teacher is a fake LLM object (no HTTP): its replies are made up here from nonsense words, and every reply and
every request long enough to carry it carries runner/mock_ollama.MARK: test text, never training data. Because
EvalIndex flags that mark, most tests judge seeds with a fake index; the real one is tested on its own."""
import hashlib
import json
import os
import random
import shutil
import signal
import tempfile
import threading
import time
import unittest

from tests import _paths  # noqa: F401
import evalset
from datagen import common as C
from datagen import llm as L
from datagen import seeds as S
from datagen import topics as T
from runner import common as rc
from runner.mock_ollama import MARK

PLAN_AREAS = {"modelling", "modifiers", "geometry nodes from Python", "materials", "lighting",
              "cameras and keyframes", "render and compositor", "scatter", "bmesh", "simulations"}
VOCAB = [a + b for a in ("ka", "lo", "mi", "nu", "pe", "ru", "sa", "ti", "vo", "ze")
         for b in ("bat", "dor", "fen", "gil", "hum", "jax", "kip", "lun", "mox", "pir", "qua", "rex", "sol", "tum")]
LEAK = "zzleakzz"  # what FakeIndex counts as an eval overlap


def text(*parts, n=40):
    """A made-up request of n nonsense words, different for different parts, with the fixture mark."""
    r = random.Random("|".join(map(str, parts)))
    return "fixture request " + " ".join(r.choice(VOCAB) for _ in range(n)) + "\n" + MARK


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def reply(tasks):
    return json.dumps({"tasks": tasks, "note": MARK})


class FakeIndex:
    """Stands in for tools/check_overlap.EvalIndex: a text with LEAK in it overlaps the eval."""

    def __init__(self):
        self.thresholds = set()

    def check(self, t, threshold=0.5):
        self.thresholds.add(threshold)
        return [("fake-eval:leak", 1.0)] if LEAK in t else []


class FakeLLM:
    """The LLM's interface without HTTP: request() is the real one (so keys are the real keys), call() answers
    from respond(call_key, sample), which returns reply content, or a Reply to return as it is."""

    request = L.LLM.request

    def __init__(self, size, respond, parallel=1, stop_at=None, delay=0.0):
        self.by_messages = {json.dumps(c["messages"]): c["key"] for c in S.plan_calls(size)}
        self.respond, self.stop_at, self.delay = respond, stop_at, delay
        self.gate = type("G", (), {"parallel": parallel})()
        self.log = []  # (call key, sample, model, purpose, options, fmt, think)
        self.lock = threading.Lock()
        self.active = self.most = 0

    def call(self, model, messages, *, purpose, options=None, fmt=None, think=None, worker=False, sample=0,
             num_ctx=None):
        key, _ = self.request(model, messages, options=options, fmt=fmt, think=think, worker=worker, sample=sample,
                              num_ctx=num_ctx)
        ck = self.by_messages[json.dumps(messages)]
        with self.lock:
            if self.stop_at is not None and len(self.log) >= self.stop_at:
                raise C.StopRequested("test stop")
            self.log.append((ck, sample, model, purpose, dict(options or {}), fmt, think))
            self.active += 1
            self.most = max(self.most, self.active)
        try:
            time.sleep(self.delay)
            got = self.respond(ck, sample)
        finally:
            with self.lock:
                self.active -= 1
        if isinstance(got, L.Reply):
            got.key, got.model, got.purpose, got.sample = key, model, purpose, sample
            return got
        return L.Reply(content=got, done_reason="stop", wall_s=0.01, key=key, model=model, purpose=purpose,
                       sample=sample)

    def keys(self):
        return [x[0] for x in self.log]


def plain(ck, sample):
    """Every call answers with four distinct requests."""
    return reply([text(ck, j) for j in range(4)])


class Temp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wm-dg-seeds-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def dir(self, name="d"):
        return os.path.join(self.tmp, name)

    def run_stage(self, size, llm, data_dir=None, **kw):
        kw.setdefault("helper_files", ())
        kw.setdefault("index", FakeIndex())
        return S.make_seeds(llm, data_dir or self.dir(), size, **kw)

    def dropped(self, data_dir=None):
        return C.read_jsonl(os.path.join(data_dir or self.dir(), S.DROPPED_FILE))

    def stats(self, data_dir=None):
        return C.read_json(os.path.join(data_dir or self.dir(), S.STATS_FILE))


def size_of(name="t", new=None, pick=None):
    return {"name": name, "new_calls": new or {}, "pick": pick or {}}


# ---------------------------------------------------------------- topics.py

class TopicsTest(unittest.TestCase):
    def test_counts_and_the_plans_areas(self):
        self.assertTrue(30 <= len(T.BLENDER_TOPICS) <= 40, len(T.BLENDER_TOPICS))
        self.assertTrue(20 <= len(T.PYTHON_TOPICS) <= 30, len(T.PYTHON_TOPICS))
        self.assertTrue(8 <= len(T.MIXED_TOPICS) <= 12, len(T.MIXED_TOPICS))
        self.assertEqual({a for a, _ in T.BLENDER_AREAS}, PLAN_AREAS)
        labels = T.BLENDER_TOPICS + T.PYTHON_TOPICS + T.MIXED_TOPICS
        self.assertEqual(len(set(labels)), len(labels))
        self.assertEqual(set(T.BLENDER_TOPICS), {lb for _, ls in T.BLENDER_AREAS for lb in ls})

    def test_the_rotation_covers_every_area_and_label(self):
        n = len(T.BLENDER_TOPICS)
        self.assertEqual({T.topic_for("blender", i)[1] for i in range(10)}, PLAN_AREAS)
        for start in range(n):  # any ten calls in a row
            self.assertEqual(len({T.topic_for("blender", start + i)[1] for i in range(10)}), 10, start)
        self.assertEqual(sorted(T.topic_for("blender", i)[0] for i in range(n)), sorted(T.BLENDER_TOPICS))
        self.assertEqual(T.topic_for("blender", n), T.topic_for("blender", 0))
        areas = [a for a, _ in T.PYTHON_AREAS]
        self.assertEqual({T.topic_for("python", i)[1] for i in range(len(areas))}, set(areas))
        self.assertEqual(sorted(T.topic_for("python", i)[0] for i in range(len(T.PYTHON_TOPICS))),
                         sorted(T.PYTHON_TOPICS))
        for i in range(2 * n):
            topic, area = T.topic_for("mixed", i)
            self.assertTrue(topic.startswith(T.MIXED_TOPICS[i % len(T.MIXED_TOPICS)]))
            self.assertNotIn(T.topic_for("blender", i)[0], topic)  # not the same technique as blender call i
            self.assertIn(area, PLAN_AREAS)
        with self.assertRaises(ValueError):
            T.topic_for("rust", 0)

    def test_styles_and_lengths_hold_their_weights(self):
        for pairs, fn in ((T.STYLES, T.style_for), (T.LENGTHS, T.length_for)):
            cycle = sum(w for _, w in pairs)
            for target in T.TARGETS:
                got = [fn(target, i) for i in range(cycle)]
                self.assertEqual({v: got.count(v) for v in got}, {v: w for v, w in pairs})
                self.assertEqual(got, [fn(target, i) for i in range(cycle, 2 * cycle)])

    def test_no_label_names_an_eval_scenario(self):
        match = S.TitleMatch(S.eval_titles())
        single = {t for t in S.eval_titles(multi_word=False) if len(S.words(t)) == 1}
        self.assertTrue(single)
        for label in T.BLENDER_TOPICS + T.PYTHON_TOPICS + T.MIXED_TOPICS:
            self.assertIsNone(match.find(label), label)
            self.assertFalse(single & set(S.words(label)), label)

    def test_the_instructions(self):
        b = T.seed_user("blender", "a topic", "plain", "short", 5)
        for part in ("Write 5 different requests", "Blender 5.x", "new, empty Blender file", "no add-ons",
                     "no existing .blend file", "blender -b", "2 to 6 parts", "Write in English",
                     "Topic: a topic", "How they write: plain", "How long: short", '{"tasks": ["...", "..."]}'):
            self.assertIn(part, b)
        p = T.seed_user("python", "x", "y", "z", 3)
        for part in ("standard library", "no network", "no GUI window", "no waiting for someone to type",
                     "2 to 6 parts", "files that already exist"):
            self.assertIn(part, p)
        self.assertNotIn("Blender", p)
        m = T.seed_user("mixed", "x", "y", "z", 3)
        for part in ("Blender 5.x", "piece of writing", "new, empty Blender file", "separate helpers"):
            self.assertIn(part, m)
        self.assertNotIn("covered elsewhere", b)
        self.assertIn("covered elsewhere already, so don't write about them or close variations of them: a; b.",
                      T.seed_user("blender", "x", "y", "z", 2, avoid=("a", "b")))
        with self.assertRaises(ValueError):
            T.seed_user("rust", "x", "y", "z", 2)

    def test_each_target_avoids_its_own_eval_titles(self):
        calls = {c["target"]: c for c in S.plan_calls(size_of(new={"blender": (1, 2), "python": (1, 2),
                                                                     "mixed": (1, 2)}))}
        blender = S.eval_titles(("blender",), multi_word=False)
        code = S.eval_titles(("code", "general"), multi_word=False)
        self.assertTrue(blender and code)
        for target, want, other in (("blender", blender, code), ("python", code, blender),
                                    ("mixed", blender, code)):
            user = calls[target]["messages"][1]["content"]
            for t in want:
                self.assertIn(t, user)
            self.assertTrue(any(t not in user for t in other if t not in want), target)
            self.assertEqual(calls[target]["messages"][0]["content"], T.SEED_SYSTEM)


# ---------------------------------------------------------------- reading replies and the eval titles

class ParseTest(unittest.TestCase):
    def test_replies(self):
        a, b = text("p", 1), text("p", 2)
        self.assertEqual(S.parse_tasks(reply([a, b])), [a.strip(), b.strip()])
        self.assertEqual(S.parse_tasks("```json\n" + reply([a]) + "\n```"), [a.strip()])
        self.assertEqual(S.parse_tasks("Here they are: " + reply([a]) + " " + MARK), [a.strip()])
        self.assertEqual(S.parse_tasks(json.dumps({"requests": [a, b], "note": MARK})), [a.strip(), b.strip()])
        self.assertEqual(S.parse_tasks(json.dumps({"tasks": [{"text": a}, {"task": b}, {"n": 1}], "x": MARK})),
                         [a.strip(), b.strip()])
        self.assertEqual(S.parse_tasks(json.dumps([a, 7, "  ", None, b])), [a.strip(), b.strip()])
        self.assertEqual(S.parse_tasks(reply(["  " + a + "\n\n"])), [a.strip()])
        self.assertEqual(S.parse_tasks(reply([])), [])
        for bad in ("", "not json " + MARK, '{"tasks": "one ' + MARK + '"}', '{"tasks": [' + MARK, None):
            self.assertIsNone(S.parse_tasks(bad), bad)

    def test_eval_titles_are_read_from_the_eval(self):
        titles = S.eval_titles()
        self.assertEqual(titles, sorted(set(titles)))
        self.assertTrue(all(t == t.lower() and len(S.words(t)) >= 2 for t in titles))
        frozen = load(os.path.join(evalset.EVAL_DIR, "frozen", "plans.json"))
        first = frozen["items"][0]["plan"]["title"]
        self.assertIn(" ".join(first.split()).lower(), titles)
        self.assertTrue(set(S.eval_titles(("blender",))) < set(titles))
        self.assertTrue(set(titles) < set(S.eval_titles(multi_word=False)))

    def test_titles_match_as_phrases(self):
        m = S.TitleMatch(["low-poly rocky island", "to-do cli", "snowman"])
        self.assertEqual(m.find("Build a LOW POLY rocky-island scene"), "low-poly rocky island")
        self.assertEqual(m.find("a to do CLI in python"), "to-do cli")
        self.assertIsNone(m.find("a low-poly rocky islands chain"))  # islands isn't island
        self.assertIsNone(m.find("a snowman"))  # one-word titles aren't matched
        self.assertIsNone(m.find("rocky island, low-poly"))


# ---------------------------------------------------------------- the stage

class DropTest(Temp):
    def test_every_drop_reason(self):
        title = S.eval_titles(("blender",))[0]
        good, other = text("good"), text("other")
        w = good.split(" ")
        near = " ".join(w[:20] + ["vexvex"] + w[21:])
        same = "FIXTURE REQUEST, " + good[len("fixture request "):].replace(" ", ",  ", 3)  # the mark unchanged
        long = (MARK + " " + text("long", n=1500))[:8000] + "x"
        tasks = [good, "make a cube", long, same, near, text("leak") + " " + LEAK,
                 text("title") + " " + title + " " + MARK, other]
        size = size_of(new={"blender": (1, 8)}, pick={"blender": None})
        idx = FakeIndex()
        got = self.run_stage(size, FakeLLM(size, lambda ck, s: reply(tasks)), index=idx)
        self.assertEqual({s["text"] for s in got}, {good.strip(), other.strip()})
        self.assertEqual({s["seed_id"] for s in got}, {"n-blender-0000-00", "n-blender-0000-07"})
        why = {d["seed_id"]: (d["reason"], d["detail"]) for d in self.dropped()}
        self.assertEqual(why["n-blender-0000-01"], ("length", "11 characters"))
        self.assertEqual(why["n-blender-0000-02"], ("length", "8001 characters"))
        self.assertEqual(why["n-blender-0000-03"], ("repeat", "n-blender-0000-00"))
        self.assertEqual(why["n-blender-0000-04"][0], "near_repeat")
        self.assertEqual(why["n-blender-0000-04"][1]["seed_id"], "n-blender-0000-00")
        self.assertGreaterEqual(why["n-blender-0000-04"][1]["jaccard"], S.NEAR)
        self.assertEqual(why["n-blender-0000-05"], ("eval_overlap", ["fake-eval:leak"]))
        self.assertEqual(why["n-blender-0000-06"], ("eval_title", title))
        self.assertEqual(idx.thresholds, {S.EVAL_THRESHOLD})
        st = self.stats()
        self.assertEqual(st["dropped"], {"length": 2, "eval_overlap": 1, "eval_title": 1, "repeat": 1,
                                         "near_repeat": 1})
        self.assertEqual((st["kept"], st["offered"], st["seeds"]), (2, 8, 2))
        self.assertEqual(st["dropped_by"], {"blender": st["dropped"]})
        for d in self.dropped():  # a drop keeps the whole seed
            self.assertEqual(d["source"], "new")
            self.assertIn("call_key", d)

    def test_length_bounds(self):
        for n, cut in ((14, True), (15, False), (8000, False), (8001, True)):
            pool = S.Pool(FakeIndex(), [])
            reason, _ = pool.offer({"seed_id": "x", "source": "new", "category": "python",
                                    "text": ("q" * n), "history": None})
            self.assertEqual(reason == "length", cut, n)

    def test_a_distant_text_is_not_a_near_repeat(self):
        a = text("a")
        w = a.split(" ")
        half = " ".join(w[:20] + [x + "q" for x in w[20:]]) + "\n" + MARK  # half the words changed
        pool = S.Pool(FakeIndex(), [])
        self.assertEqual(pool.offer({"seed_id": "a", "source": "new", "category": "python", "text": a}), (None, None))
        self.assertEqual(pool.offer({"seed_id": "b", "source": "new", "category": "python", "text": half}),
                         (None, None))

    def test_the_real_eval_index(self):
        from tools.check_overlap import EvalIndex
        w1 = load(os.path.join(evalset.EVAL_DIR, "w1_tasks.json"))
        prompt = w1["items"][0]["prompt"]  # read at run time, never copied
        tasks = [prompt, text("marked")]
        size = size_of(new={"python": (1, 2)}, pick={"python": None})
        got = self.run_stage(size, FakeLLM(size, lambda ck, s: reply(tasks)), index=EvalIndex(8))
        self.assertEqual(got, [])
        why = {d["seed_id"]: d for d in self.dropped()}
        self.assertEqual(why["n-python-0000-00"]["reason"], "eval_overlap")
        self.assertTrue(any(h.startswith("worker-eval:") for h in why["n-python-0000-00"]["detail"]))
        self.assertEqual(why["n-python-0000-01"]["reason"], "eval_overlap")
        self.assertIn("mark:test-fixture", why["n-python-0000-01"]["detail"])  # a fixture can never be a seed


class HelperTest(Temp):
    def write_helper(self):
        a = os.path.join(self.tmp, "seeds.jsonl")
        b = os.path.join(self.tmp, "seeds2.jsonl")
        hist = [{"role": "user", "content": text("h", "u")}, {"role": "assistant", "content": text("h", "a")}]
        rows_a = [{"seed_id": "blender-0000-00", "category": "blender", "text": text("hb", 0), "history": None,
                   "from": "blender", "params": {"topic": "t1", "k": 3}},
                  {"seed_id": "blender-0000-01", "category": "blender", "text": text("hb", 1), "history": None,
                   "from": "blender", "params": {"topic": "t1", "k": 3}},
                  {"seed_id": "followup-0000-00", "category": "coding", "text": text("hf", 0), "history": hist,
                   "from": "followup", "params": {"topic": "t2"}},
                  {"seed_id": "coding-0001-00", "category": "coding", "text": text("hc", 0), "history": None,
                   "from": "coding", "params": {}},
                  {"seed_id": "small_task-0000-00", "category": "small_task", "text": text("hs", 0),
                   "history": None, "from": "small_task", "params": {}},
                  {"seed_id": "research_draft-0000-00", "category": "research_draft", "text": text("hr", 0),
                   "history": [{"role": "user", "content": text("hr", "u") + " " + LEAK}], "from": "research_draft",
                   "params": {}}]
        rows_b = [{"seed_id": "batch_large-0000-00", "category": "batch", "text": text("hl", 0), "history": None,
                   "from": "batch_large", "params": {"large": True}}]
        C.write_jsonl(a, rows_a)
        C.write_jsonl(b, rows_b)
        return [a, b], rows_a + rows_b

    def test_by_category(self):
        files, rows = self.write_helper()
        size = size_of(pick={"helper_blender": 1, "helper_coding": None, "helper_small_task": 1, "helper_batch": 5,
                             "helper_research_draft": 1, "helper_planning": 2})
        got = self.run_stage(size, None, helper_files=files)
        ids = [s["seed_id"] for s in got]
        self.assertEqual(len(ids), 5)
        self.assertEqual(len([i for i in ids if i.startswith("blender")]), 1)
        self.assertEqual({i for i in ids if not i.startswith("blender")},
                         {"followup-0000-00", "coding-0001-00", "small_task-0000-00", "batch_large-0000-00"})
        by = {s["seed_id"]: s for s in got}
        f = by["followup-0000-00"]
        self.assertEqual((f["source"], f["category"], S.pick_name(f), f["call_key"]),
                         ("helper", "coding", "helper_coding", None))
        self.assertEqual(f["history"], rows[2]["history"])
        self.assertEqual(f["params"], {"topic": "t2", "file": "seeds.jsonl", "from": "followup"})
        self.assertEqual(by["batch_large-0000-00"]["params"]["file"], "seeds2.jsonl")
        self.assertEqual(f["key"], f["seed_id"])
        # the research seed's history overlaps the eval, so it is dropped
        self.assertEqual([(d["seed_id"], d["reason"]) for d in self.dropped()],
                         [("research_draft-0000-00", "eval_overlap")])
        pick = self.stats()["pick"]
        self.assertEqual(pick["helper_batch"], {"wanted": 5, "picked": 1, "kept": 1})
        self.assertEqual(pick["helper_coding"], {"wanted": None, "picked": 2, "kept": 2})
        self.assertEqual(pick["helper_research_draft"], {"wanted": 1, "picked": 0, "kept": 0})
        self.assertEqual(pick["helper_planning"], {"wanted": 2, "picked": 0, "kept": 0})
        self.assertEqual(self.stats()["helper"]["by_category"],
                         {"blender": 2, "coding": 2, "small_task": 1, "research_draft": 1, "batch": 1})
        # the order takes one pick name at a time
        self.assertEqual([S.pick_name(s) for s in got][:4],
                         ["helper_blender", "helper_coding", "helper_batch", "helper_small_task"])

    def test_a_new_seed_repeating_a_helper_seed_is_dropped(self):
        files, rows = self.write_helper()
        size = size_of(new={"blender": (1, 2)}, pick={"blender": None, "helper_blender": None})
        llm = FakeLLM(size, lambda ck, s: reply([rows[0]["text"], text("fresh")]))
        got = self.run_stage(size, llm, helper_files=files)
        self.assertIn("n-blender-0000-01", [s["seed_id"] for s in got])
        self.assertIn("blender-0000-00", [s["seed_id"] for s in got])
        d = {x["seed_id"]: x for x in self.dropped()}
        self.assertEqual((d["n-blender-0000-00"]["reason"], d["n-blender-0000-00"]["detail"]),
                         ("repeat", "blender-0000-00"))

    def test_the_real_helper_files(self):
        before = {p: sha(p) for p in S.HELPER_FILES}
        size = size_of(pick={"helper_" + c: None for c in S.HELPER_CATEGORIES})
        got = self.run_stage(size, None, helper_files=None)
        rows = [r for p in S.HELPER_FILES for r in C.read_jsonl(p)]
        self.assertEqual({p: sha(p) for p in S.HELPER_FILES}, before)
        want = {}
        for r in rows:
            want[r["category"]] = want.get(r["category"], 0) + 1
        st = self.stats()
        self.assertEqual(st["helper"]["read"], len(rows))
        self.assertEqual(st["helper"]["by_category"], want)
        self.assertEqual(set(want), set(S.HELPER_CATEGORIES))
        dropped = self.dropped()
        self.assertEqual(len(got) + len(dropped), len(rows))
        self.assertEqual({s["seed_id"] for s in got} | {d["seed_id"] for d in dropped}, {r["seed_id"] for r in rows})
        cat = {r["seed_id"]: r["category"] for r in rows}
        for s in got:
            self.assertEqual((s["source"], s["category"]), ("helper", cat[s["seed_id"]]))
        self.assertTrue(all(d["reason"] in S.REASONS for d in dropped))
        self.assertTrue(sum(1 for s in got if s["history"]) > 0)

    def test_missing_helper_files(self):
        gone = [os.path.join(self.tmp, "nope.jsonl")]
        with self.assertRaises(FileNotFoundError):
            self.run_stage(size_of(pick={"helper_coding": 3}), None, helper_files=gone)
        size = size_of(new={"python": (1, 4)}, pick={"python": 2})
        got = self.run_stage(size, FakeLLM(size, plain), helper_files=gone)
        self.assertEqual(len(got), 2)
        self.assertEqual(self.stats()["helper"]["missing"], gone)


class PickTest(Temp):
    SIZE = {"blender": (3, 4), "python": (2, 3)}

    def test_deterministic_and_spread_over_calls(self):
        size = size_of("smoke", new=self.SIZE, pick={"blender": 3, "python": 2})
        a = self.run_stage(size, FakeLLM(size, plain), data_dir=self.dir("a"))
        b = self.run_stage(size, FakeLLM(size, plain), data_dir=self.dir("b"))
        self.assertEqual(a, b)
        self.assertEqual(sha(os.path.join(self.dir("a"), S.SEEDS_FILE)), sha(os.path.join(self.dir("b"), S.SEEDS_FILE)))
        self.assertEqual([s["category"] for s in a], ["blender", "python", "blender", "python", "blender"])
        calls = [s["seed_id"].rsplit("-", 1)[0] for s in a if s["category"] == "blender"]
        self.assertEqual(sorted(calls), ["n-blender-0000", "n-blender-0001", "n-blender-0002"])
        calls = [s["seed_id"].rsplit("-", 1)[0] for s in a if s["category"] == "python"]
        self.assertEqual(sorted(calls), ["n-python-0000", "n-python-0001"])
        for s in a:
            self.assertEqual(s["key"], s["seed_id"])
            self.assertEqual((s["source"], s["history"]), ("new", None))
            self.assertEqual(s["params"]["target"], s["category"])
            self.assertIn(s["params"]["topic"], T.BLENDER_TOPICS + T.PYTHON_TOPICS)

    def test_the_size_name_and_all(self):
        size = size_of("smoke", new=self.SIZE, pick={"blender": None, "python": "all"})
        a = self.run_stage(size, FakeLLM(size, plain), data_dir=self.dir("a"))
        self.assertEqual(len(a), 5 * 4)  # every task of the five calls (plain answers four each)
        night = dict(size, name="night")
        b = self.run_stage(night, FakeLLM(night, plain), data_dir=self.dir("b"))
        self.assertEqual(sorted(s["seed_id"] for s in a), sorted(s["seed_id"] for s in b))
        self.assertNotEqual([s["seed_id"] for s in a], [s["seed_id"] for s in b])
        kept = [s for s in a if s["category"] == "blender"]
        self.assertEqual(S.pick(kept, 4, "smoke", "blender"), S.pick(kept, None, "smoke", "blender")[:4])
        self.assertEqual(S.pick(kept, 0, "smoke", "blender"), [])
        # fewer seeds than calls: distinct calls, and not always the first ones
        ids = [{"seed_id": f"n-blender-{i:04d}-{j:02d}"} for i in range(6) for j in range(2)]
        chosen = [{s["seed_id"][:-3] for s in S.pick(ids, 3, name, "blender")} for name in "abcde"]
        self.assertTrue(all(len(c) == 3 for c in chosen))
        self.assertTrue(any(c != {"n-blender-0000", "n-blender-0001", "n-blender-0002"} for c in chosen))
        self.assertEqual(S.wanted({"pick": {}}, "blender"), 0)
        self.assertEqual(S.wanted({"pick": {}, "helper": {"small_task": 60}}, "helper_small_task"), 60)

    def test_unknown_targets_and_no_llm(self):
        with self.assertRaises(ValueError):
            S.plan_calls(size_of(new={"rust": (1, 2)}))
        with self.assertRaises(ValueError):
            self.run_stage(size_of(new={"python": (1, 2)}), None)
        keys = [c["key"] for c in S.plan_calls(size_of(new={"blender": (3, 2), "python": (1, 2), "mixed": (2, 2)}))]
        self.assertEqual(keys, ["blender-0000", "python-0000", "mixed-0000", "blender-0001", "mixed-0001",
                                "blender-0002"])


class CallTest(Temp):
    def test_the_teacher_call(self):
        size = size_of(new={"mixed": (2, 3)}, pick={"mixed": None})
        llm = FakeLLM(size, plain)
        self.run_stage(size, llm)
        self.assertEqual(len(llm.log), 2)
        for ck, sample, model, purpose, options, fmt, think in llm.log:
            self.assertEqual((sample, model, purpose, fmt, think), (0, "gpt-oss:120b", "seed", "json", None))
            self.assertEqual(options, {"num_predict": 7000})
        recs = C.read_jsonl(os.path.join(self.dir(), S.CALLS_FILE))
        self.assertEqual(sorted(r["key"] for r in recs), ["mixed-0000", "mixed-0001"])
        r = recs[0]
        call = next(c for c in S.plan_calls(size) if c["key"] == r["key"])
        self.assertEqual(r["request_key"], llm.request("gpt-oss:120b", call["messages"],
                                                       options={"num_predict": 7000}, fmt="json")[0])
        self.assertEqual((r["call_key"], r["error"], r["unreadable"], len(r["items"]), r["reply"]),
                         (r["request_key"], None, False, 4, None))
        self.assertEqual(r["params"], call["params"])

    def test_an_unreadable_reply_is_asked_once_more(self):
        runaway = L.Reply(content="{" + MARK, done_reason=rc.RUNNER_CUT, error="runaway: " + MARK)

        def respond(ck, sample):
            if ck == "python-0000":
                return "not json " + MARK if sample == 0 else reply([text(ck, "second")])
            if ck == "python-0001":
                return "still not json " + MARK
            return runaway if sample == 0 else reply([text(ck, "after the runaway")])

        size = size_of(new={"python": (3, 2)}, pick={"python": None})
        llm = FakeLLM(size, respond)
        got = self.run_stage(size, llm)
        self.assertEqual(sorted((k, s) for k, s, *_ in llm.log),
                         [("python-0000", 0), ("python-0000", 1), ("python-0001", 0), ("python-0001", 1),
                          ("python-0002", 0), ("python-0002", 1)])
        recs = {r["key"]: r for r in C.read_jsonl(os.path.join(self.dir(), S.CALLS_FILE))}
        r = recs["python-0000"]
        self.assertEqual(([t["tasks"] for t in r["tries"]], r["unreadable"]), ([None, 1], False))
        self.assertNotEqual(r["call_key"], r["request_key"])
        self.assertEqual(r["call_key"], r["tries"][1]["key"])
        seed = next(s for s in got if s["seed_id"] == "n-python-0000-00")
        self.assertEqual(seed["call_key"], r["call_key"])
        bad = recs["python-0001"]
        self.assertEqual((bad["items"], bad["unreadable"], bad["error"]), ([], True, None))
        self.assertTrue(bad["reply"].startswith("still not json"))
        self.assertEqual(recs["python-0002"]["error"], None)  # a runaway is a reply, not a failure
        self.assertEqual({s["seed_id"] for s in got}, {"n-python-0000-00", "n-python-0002-00"})
        st = self.stats()["calls"]["python"]
        self.assertEqual((st["calls"], st["answered"], st["unreadable"], st["retried"], st["tasks"]),
                         (3, 3, 1, 3, 2))

    def test_parallel_calls_give_the_same_seeds(self):
        size = size_of(new={"blender": (4, 4), "python": (3, 4), "mixed": (2, 4)},
                       pick={"blender": 5, "python": 4, "mixed": 2})
        one = self.run_stage(size, FakeLLM(size, plain), data_dir=self.dir("one"))
        llm = FakeLLM(size, plain, parallel=3, delay=0.05)
        many = self.run_stage(size, llm, data_dir=self.dir("many"))
        self.assertGreater(llm.most, 1)
        self.assertLessEqual(llm.most, 3)
        self.assertEqual(one, many)

    def test_ctrl_c_with_parallel_calls_starts_no_waiting_call(self):
        """Ctrl-C (SIGINT, as the first call starts) leaves at once; only the calls in flight then end on their own."""
        size = size_of(new={"blender": (6, 2), "python": (6, 2)}, pick={"blender": None, "python": None})
        sent = []

        def respond(ck, sample):
            if not sent:
                sent.append(ck)
                os.kill(os.getpid(), signal.SIGINT)  # handled in the main thread, which waits in run_calls
            return plain(ck, sample)
        llm = FakeLLM(size, respond, parallel=2, delay=0.3)
        t0 = time.monotonic()
        with self.assertRaises(KeyboardInterrupt):
            self.run_stage(size, llm)
        self.assertLess(time.monotonic() - t0, 1.0)  # not the 12 calls' 1.8 s
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and (llm.active or time.monotonic() - t0 < 1.0):
            time.sleep(0.05)
        self.assertLessEqual(len(llm.log), 2)  # the two in flight, nothing taken from the queue after them
        self.assertFalse(os.path.exists(os.path.join(self.dir(), S.SEEDS_FILE)))

    def test_stop_file(self):
        size = size_of(new={"python": (2, 2)}, pick={"python": None})
        os.makedirs(self.dir())
        open(C.stop_path(self.dir()), "w").close()
        llm = FakeLLM(size, plain)
        with self.assertRaises(C.StopRequested):
            self.run_stage(size, llm)
        self.assertEqual(llm.log, [])


class ResumeTest(Temp):
    SIZE = size_of("smoke", new={"blender": (3, 4), "python": (2, 3)}, pick={"blender": 4, "python": 3})

    def test_a_stopped_run_resumes_where_it_stopped(self):
        whole = self.run_stage(self.SIZE, FakeLLM(self.SIZE, plain), data_dir=self.dir("whole"))
        first = FakeLLM(self.SIZE, plain, stop_at=2)
        with self.assertRaises(C.StopRequested):
            self.run_stage(self.SIZE, first)
        self.assertEqual(first.keys(), ["blender-0000", "python-0000"])
        self.assertEqual(len(C.read_jsonl(os.path.join(self.dir(), S.CALLS_FILE))), 2)
        self.assertFalse(os.path.exists(os.path.join(self.dir(), S.SEEDS_FILE)))
        with open(os.path.join(self.dir(), S.CALLS_FILE), "a", encoding="utf-8") as f:
            f.write('{"key": "python-0001", "half a li')  # a write cut off by a kill
        second = FakeLLM(self.SIZE, plain)
        got = self.run_stage(self.SIZE, second)
        self.assertEqual(second.keys(), ["blender-0001", "python-0001", "blender-0002"])
        self.assertEqual(got, whole)
        third = FakeLLM(self.SIZE, plain)
        self.assertEqual(self.run_stage(self.SIZE, third), whole)
        self.assertEqual(third.log, [])
        self.assertEqual(self.stats()["made_now"], 0)

    def test_a_failed_call_is_asked_again(self):
        def flaky(ck, sample):
            return L.Reply(content="", error="connection refused") if ck == "python-0001" else plain(ck, sample)

        first = FakeLLM(self.SIZE, flaky)
        got = self.run_stage(self.SIZE, first)
        self.assertEqual(len(first.log), 5)  # one failure in five calls: not a stage failure
        self.assertNotIn("n-python-0001", {s["seed_id"].rsplit("-", 1)[0] for s in got})
        rec = C.Store(os.path.join(self.dir(), S.CALLS_FILE)).get("python-0001")
        self.assertEqual((rec["error"], rec["items"], len(rec["tries"])), ("connection refused", [], 1))
        self.assertEqual(self.stats()["calls"]["python"]["errors"], 1)
        second = FakeLLM(self.SIZE, plain)
        self.assertEqual(self.run_stage(self.SIZE, second),
                         self.run_stage(self.SIZE, FakeLLM(self.SIZE, plain), data_dir=self.dir("whole")))
        self.assertEqual(second.keys(), ["python-0001"])

    def test_a_call_failing_again_on_its_own_doesnt_stop_the_stage(self):
        """The failure rate is judged against the size's five calls, not the one re-asked on the next start."""
        def flaky(ck, sample):
            return L.Reply(content="", error="connection refused") if ck == "python-0001" else plain(ck, sample)

        first = self.run_stage(self.SIZE, FakeLLM(self.SIZE, flaky))
        again = FakeLLM(self.SIZE, flaky)
        self.assertEqual(self.run_stage(self.SIZE, again), first)
        self.assertEqual(again.keys(), ["python-0001"])
        st = self.stats()
        self.assertEqual((st["made_now"], st["failed_now"], st["failed_calls"]), (1, 1, ["python-0001"]))
        with open(os.path.join(self.dir(), "progress.log"), encoding="utf-8") as f:
            self.assertIn("1 of 5 teacher calls failed (python-0001)", f.read())

    def test_most_calls_failing_stops_the_stage(self):
        llm = FakeLLM(self.SIZE, lambda ck, s: L.Reply(content="", error="connection refused"))
        with self.assertRaises(S.SeedError):
            self.run_stage(self.SIZE, llm)
        recs = C.read_jsonl(os.path.join(self.dir(), S.CALLS_FILE))
        self.assertEqual(len(recs), 5)
        self.assertTrue(all(r["error"] for r in recs))
        self.assertFalse(os.path.exists(os.path.join(self.dir(), S.SEEDS_FILE)))

    def test_a_changed_request_is_asked_again(self):
        self.run_stage(self.SIZE, FakeLLM(self.SIZE, plain))
        changed = size_of("smoke", new={"blender": (3, 4), "python": (2, 5)}, pick={"blender": 4, "python": 3})
        llm = FakeLLM(changed, plain)
        self.run_stage(changed, llm)
        self.assertEqual(sorted(llm.keys()), ["python-0000", "python-0001"])
        longer = size_of("smoke", new={"blender": (4, 4), "python": (2, 5)}, pick={"blender": 4, "python": 3})
        llm = FakeLLM(longer, plain)
        got = self.run_stage(longer, llm)
        self.assertEqual(llm.keys(), ["blender-0003"])
        self.assertEqual(C.read_jsonl(os.path.join(self.dir(), S.DROPPED_FILE)), [])
        self.assertEqual(len(got), 7)


if __name__ == "__main__":
    unittest.main()
