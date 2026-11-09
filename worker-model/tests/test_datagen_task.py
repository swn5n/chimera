"""datagen/task.py: one seed, start to end, against a Chimera binary built from app/ once per run (or a copy of
$CHIMERA_BIN when it names one; into $WM_SCRATCH, else data/scratch/, removed afterwards) and the stand-in Ollama of
tests/datagen_fakes.py, whose canned replies are test fixtures (they carry the mark), never training data. Skipped
without Go or a binary.

Code and section plans run their real gates (pysandbox, the prose gate); Blender plans run in real Blender 5.2.2 and
5.0.1 where it says so (the second sampler), and otherwise through a stand-in gate, for the logic that doesn't need
Blender: the plan check's alternates and plan_failed. What is checked: every stored request is exactly what
--hydra-worker-request prints for the inputs it records (run directly, not through the memo), and the teacher's
copies, as the stand-in Ollama received them, carry the notes the requests don't; the planner's choice (hydra:1.0,
gpt-oss:120b by share or by length, a reused helper plan in the helper's real record shape, the fallback when hydra's
plan can't be read) and a plan that repeats the eval; the tests and their stub rule, and tests no first candidate
passes, which stay unconfirmed and gate every later one; repairs as examples, the 30% rule, a step kept from its
repair giving only the repair example, a Blender repair's sheet from the crashed Blender, and files repairs giving
none; a reply that repeats a teacher note; the second sampler; drops and the failed dependency they leave; both
variants, judged; round 2 after a review, and a review that says done; a failed call; STOP. After the smoke run: a
bold File line and a stand-in marker's other hyphen made plain before the checks (the raw reply kept in the cache), a
Blender version only the notes name, the validator's messages and the gates' tell lines in the next try's notes, the
second sampler's num_predict, a files step with no Python file asking for no tests, refused tests asked for again,
one rewrite of tests that fail every candidate (confirmed, or not, then tests_unreachable and third_party), and a
section written without its dependency kept only on both judges' word, whatever gpt-oss's score. After the second
round of checks (Nov 4): the step's own words given to code_gate.no_python, a piece no tests ran on asked
code_gate.import_fault, tests still refused after the retry, the dependencies prose_gate.section_check is given, the
notes' words for the Blenders caught only in Blender steps, and a retry that repeats its own request's words. After
the third (Nov 4): an empty tests retry for a step that names nothing to call, the retry's outcome kept apart from
the refusals, the round's Python given to no_python, the dropped steps and the given pieces given to import_fault and
tests_fault, a piece nothing ran on, last round's part given to the prose gate, a tell line paired with the
candidate it quotes, and a code alternate the plan check swaps in settled again from its own gate. After the second
smoke run's audit (Nov 4): dep_honesty after every mode's gate, on Chimera's own request for the try (a repair's
own), its tell lines in the next batch's notes; the soft keep (a step whose tries failed only on SOFT_REASONS feeds
the later steps and the join as a pass does, with no example and no variants, unjudged; a variant never soft-keeps);
the stage ranks (layout_import, output_missing, camera_not_active, dep_honesty); a repair's own crash as its newest
failure line; the rewrite's errors kept; the code gate's project and tests_fault's kept piece. After the third smoke
run (format 4): ctx_channel soft only on a step some later step depends on (Round.used), never on a variant's try,
step 6's faults soft with or without one, their stage ranks, and a repair's share counted on its code lines
(code_lines, repair_lines); after the fourth, blender_gate.build_facts' reasons soft only on a used step, as
ctx_channel. The call sites are tested with stand-ins for the other modules' rules where a test is
about task.py's side. The eval's text is read from eval/ at run time, never copied here.
"""
import copy
import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from tests import _paths  # noqa: F401
from tests import datagen_fakes as F
import evalset
from contract.join import find_part
from datagen import code_gate as CG
from datagen import common as C
from datagen import hints as H
from datagen import judges as J
from datagen import llm as L
from datagen import prose_gate
from datagen import seeds
from datagen import task as T
from datagen.chimera import Chimera
from datagen.code_gate import CodeGate
from runner import common as rc
from runner.score import lines_changed
from tools import blender_check, blenders, rna_lint
from tools.check_overlap import EvalIndex

MARK = F.MARK
HAVE_BLENDER = all(not blenders.check_path(p) for p in blenders.VERSIONS.values())
GOAL = "Please make the mock project for this test. " + MARK

_tmp = _bin = _fake = _facts = None
_names = {}


def an_eval_plan():
    """The first plan in the worker eval whose head (title and summary) the index keeps, read at run time."""
    for name in evalset.json_files(evalset.EVAL_DIR):
        with open(os.path.join(evalset.EVAL_DIR, name), encoding="utf-8") as f:
            todo = [json.load(f)]
        while todo:
            v = todo.pop(0)
            if isinstance(v, dict):
                if evalset._is_plan(v) and isinstance(v.get("summary"), str) and \
                        len(seeds.words(v["title"] + " " + v["summary"])) >= evalset.HEAD_MIN_WORDS:
                    return v
                todo.extend(v.values())
            elif isinstance(v, list):
                todo.extend(v)
    raise AssertionError("the eval has no plan")


def setUpModule():
    global _tmp, _bin, _fake, _facts, _names
    if not F.HAVE_CHIMERA:
        raise unittest.SkipTest("needs Go to build Chimera, or CHIMERA_BIN")
    _tmp = tempfile.mkdtemp(prefix="test-datagen-task-", dir=blender_check.scratch_root())
    try:
        _bin = F.build_chimera(_tmp)
    except RuntimeError:
        shutil.rmtree(_tmp, ignore_errors=True)
        raise
    _fake = F.FakeOllama(os.path.join(_tmp, "fake.jsonl"))
    _facts = rna_lint.Facts.load()
    if HAVE_BLENDER:
        ch = Chimera(_bin, env={"OLLAMA_HOST": _fake.url})
        _names = {v: ch.blender_names(p, os.path.join(_tmp, "names")) for v, p in blenders.VERSIONS.items()}


def tearDownModule():
    if _fake:
        _fake.stop()
    if _tmp:
        shutil.rmtree(_tmp, ignore_errors=True)


class StubBlender:
    """A stand-in for BlenderGate where a test is about task.py's own logic: every piece passes, except one with
    F.CRASH_TYPE in a version of crash_in, whose crash is the preferred version's when that one fails, else the
    first failing one's (as BlenderGate takes it), and the first n checks of a step in tell ({sid: (n, lines)}), which
    fail as size_mismatch with those tell lines; plan_check fails with culprit `culprit` on its first call
    (fail_once) or always, unless plan_ok. prefers: (sid, prefer) of every piece_check."""

    def __init__(self, culprit="s2", fail_once=True, crash_in=(), plan_ok=False, tell=None):
        self.versions = {"5.2.2": "/nowhere/Blender", "5.0.1": "/nowhere/Blender-5.0.1"}
        self.culprit, self.fail_once, self.crash_in, self.plan_ok = culprit, fail_once, crash_in, plan_ok
        self.tell = dict(tell or {})
        self.calls, self.prefers = [], []

    def piece_check(self, plan, i, text, verdict, earlier, goal="", *, run_on_lint=True, joined=True, prefer=None):
        sid = f"s{i + 1}"
        self.prefers.append((sid, prefer))
        out = {"ok": True, "reasons": [], "crash": None, "lint": [], "joined_checked": joined, "tell": [],
               "scene": {"objects": [[f"chimera_{sid}", "MESH"]], "materials": [], "collections": [],
                         "ctx_keys": [sid]}}
        n, lines = self.tell.get(sid, (0, []))
        if n:
            self.tell[sid] = (n - 1, lines)
            out.update(ok=False, reasons=["size_mismatch"], tell=list(lines))
            return out
        order = ([prefer] if prefer in self.versions else []) + [v for v in self.versions if v != prefer]
        bad = [v for v in order if v in self.crash_in] if F.CRASH_TYPE in text else []
        if bad:
            out.update(ok=False, reasons=["alone_strict:" + v for v in bad], crash={
                "step": sid, "part": "build", "function": f"build_{sid}", "piece_line": 12, "line": 12,
                "source": 'light = bpy.data.lights.new("chimera_lamp", ' + F.CRASH_TYPE + ")",
                "error": 'TypeError: bpy_struct: item.attr = val: enum "POINTY" not found',
                "runner": "Blender " + bad[0]})
        return out

    def plan_check(self, plan, kept, goal=""):
        self.calls.append(dict(kept))
        bad = not self.plan_ok and (not self.fail_once or len(self.calls) == 1)
        return {"ok": not bad, "reasons": ["joined_strict:5.2.2"] if bad else [],
                "culprit": self.culprit if bad else None, "scene_outcome": "passed", "scene_critique": ""}


class Base(unittest.TestCase):
    size = {"gpt_oss_planner": 0.0, "failed_dep": 0.0, "mixed_pool": 0.0, "round2": 0.0, "prose_second": 0.0}

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="seed-", dir=_tmp)
        self.addCleanup(shutil.rmtree, self.dir, True)
        _fake.plans.clear()
        for s in (_fake.bad_plans, _fake.review_done, _fake.scene_reject, _fake.scene_why, _fake.prose_low,
                  _fake.prose_scores, _fake.errors, _fake.vary):
            s.clear()
        with _fake.lock:
            _fake.calls.clear()

    def env(self, blender=None, size=None, stop=None, raw=None, names=None, eval_index=None):
        work = os.path.join(self.dir, "work")
        ch = Chimera(_bin, env={"OLLAMA_HOST": _fake.url})
        runs = C.Cache(os.path.join(self.dir, "cache", "runs.jsonl"))
        gate = L.Gate(idle_switch_s=0.01, log_path=os.path.join(self.dir, "gate.jsonl"), stop=stop)
        llm = L.LLM(_fake.url, gate, C.Cache(os.path.join(self.dir, "cache", "calls.jsonl")), unload=False)
        if blender == "real":
            from datagen.blender_gate import BlenderGate
            blender = BlenderGate(ch, runs, linter=rna_lint.Linter(_facts, guards=True), work=work)  # as run.py's
        return T.Env(llm=llm, chimera=ch, blender=blender, code=CodeGate(ch, runs, work=work), facts=_facts,
                     names=_names if names is None else names, size=dict(self.size, **(size or {})),
                     data_dir=self.dir, work=work, runs=runs, raw_plans=raw or {},
                     log_path=os.path.join(self.dir, "progress.log"), eval_index=eval_index)

    def seed(self, plan, goal=GOAL, source="new", seed_id="n-python-0007-01"):
        _fake.plans[goal] = plan
        return {"key": seed_id, "seed_id": seed_id, "source": source, "category": "python", "text": goal,
                "history": None, "params": {}, "call_key": None}

    def run_seed(self, env, seed):
        rec = T.run_seed(env, seed)
        self.assertEqual(rec["status"], "done", rec.get("traceback"))
        return rec

    def assert_requests_are_chimeras(self, rec, names=None):
        """Every stored request (steps, variants, repairs) is what the binary prints for its recorded inputs (names:
        the env's sheets, _names by default), and carries no teacher notes."""
        n = 0
        for rnd in rec["rounds"]:
            for st in rnd["steps"] + rnd["variants"]:
                if not st.get("request"):
                    continue
                for item in [st] + st["repairs"]:
                    got = F.binary_request(_bin, rnd["plan"], rec["seed"]["text"], item["inputs"],
                                           _names if names is None else names)
                    self.assertEqual(json.dumps(item["request"]["messages"], ensure_ascii=False),
                                     json.dumps(got["messages"], ensure_ascii=False), (st["sid"], st["variant"]))
                    self.assertEqual(item["request"]["need_ctx"], got["need_ctx"])
                    self.assertNotIn(H.HEAD, json.dumps(item["request"]["messages"]))
                    n += 1
        self.assertGreater(n, 0)

    def assert_teacher_copies_carry_the_notes(self, rec):
        """Each worker call the stand-in got is a stored request with the notes added to its system message."""
        stored = []
        for rnd in rec["rounds"]:
            for st in rnd["steps"] + rnd["variants"]:
                for item in ([st] if st.get("request") else []) + st.get("repairs", []):
                    stored.append(item["request"]["messages"])
        bodies = _fake.bodies("worker")
        self.assertTrue(bodies)
        for b in bodies:
            sys_msg, user = b["messages"][0]["content"], b["messages"][1]["content"]
            self.assertIn("\n\n" + H.HEAD + "\n" + H.FORMAT_NOTE, sys_msg)
            base = sys_msg.split("\n\n" + H.HEAD)[0]
            self.assertTrue(any(m[0]["content"].rstrip("\n") == base and m[1]["content"] == user for m in stored))


class PureTests(unittest.TestCase):
    """The parts that need no binary."""

    def test_names_sheets_are_drawn_75_15_10_and_stay_put(self):
        got = [T.names_for("n-blender-0001-00", f"s{k}") for k in range(4000)]
        self.assertAlmostEqual(got.count("5.2.2") / 4000, 0.75, delta=0.03)
        self.assertAlmostEqual(got.count("5.0.1") / 4000, 0.15, delta=0.03)
        self.assertAlmostEqual(got.count(None) / 4000, 0.10, delta=0.03)
        self.assertEqual(got[:50], [T.names_for("n-blender-0001-00", f"s{k}") for k in range(50)])

    def test_stable_leaves_out_what_a_replay_changes(self):
        rec = {"key": "a", "seconds": 3.0, "finished": "now", "rounds": [{"cached": True, "wall_s": 1.5,
                                                                          "steps": [{"seconds": {"teacher": 1}}]}]}
        self.assertEqual(T.stable(rec), {"key": "a", "rounds": [{"wall_s": 1.5, "steps": [{}]}]})

    def test_group_is_the_call_a_seed_came_from(self):
        self.assertEqual(T.group_of("n-blender-0003-02"), "n-blender-0003")
        self.assertEqual(T.group_of("coding-0012-03"), "coding-0012")
        self.assertEqual(T.group_of("odd"), "odd")

    def test_how_far_a_blender_candidate_got(self):
        self.assertEqual(T._blender_stage(["lint:attr"]), "lint")
        self.assertEqual(T._blender_stage(["alone_strict:5.0.1", "dupes"]), "alone")
        self.assertEqual(T._blender_stage(["removes_earlier"]), "joined")  # it ran joined, then lost an earlier name
        self.assertEqual(T._blender_stage([]), "done")

    def test_harmony_leftovers(self):
        for bad in ("<|channel|>final", "<|channel>x", "x<channel|>", "assistantfinal", "<think>", "</think>"):
            self.assertTrue(T.HARMONY.search(bad), bad)
        self.assertFalse(T.HARMONY.search("a | b > c and <b>bold</b>"))

    def test_raw_plans_take_each_seeds_first_accepted_plan(self):
        # The helper's shape (helper-model/datagen/plans.py): an accepted plan's tidied JSON is in "target" and its
        # "reply" is null; a rejected one keeps its reply and has no target; a hinted retry carries "hints".
        d = tempfile.mkdtemp(prefix="raw-", dir=blender_check.scratch_root())
        self.addCleanup(shutil.rmtree, d, True)
        p1, p2 = os.path.join(d, "plans.jsonl"), os.path.join(d, "plans2.jsonl")
        C.write_jsonl(p1, [{"seed_id": "coding-0001-00", "accepted": False, "reply": "no " + MARK, "target": None},
                           {"seed_id": "coding-0001-00", "accepted": True, "reply": None, "target": "yes " + MARK,
                            "key": "k1", "wall_s": 30.0},
                           {"seed_id": "coding-0003-00", "accepted": False, "reply": "rejected " + MARK,
                            "target": None}])
        C.write_jsonl(p2, [{"seed_id": "coding-0001-00", "accepted": True, "reply": None, "target": "later " + MARK},
                           {"seed_id": "blender-0002-01", "accepted": True, "reply": None, "target": "b " + MARK},
                           {"seed_id": "blender-0004-00", "accepted": True, "reply": None, "target": "h " + MARK,
                            "hints": ["a note"]}])
        got = T.raw_plans([p1, p2])
        self.assertEqual(got["coding-0001-00"], {"reply": "yes " + MARK, "key": "k1", "wall_s": 30.0,
                                                 "file": "plans.jsonl"})
        self.assertEqual(got["blender-0002-01"], {"reply": "b " + MARK, "key": None, "wall_s": None,
                                                  "file": "plans2.jsonl"})
        self.assertNotIn("coding-0003-00", got)  # only rejected
        self.assertNotIn("blender-0004-00", got)  # asked with the helper's notes, not Chimera's exact request
        self.assertEqual(len(got), 2)

    def test_a_dropped_sections_lines(self):
        def dropped(reasons, **kw):
            return T._section_failures(dict({"reasons": reasons, "gate": {}, "verdict": None, "judge": None}, **kw))
        about = prose_gate.word_target("Write about 600 words. " + MARK)
        self.assertEqual(dropped(["words_over"], gate={"words": 862, "target": about}),
                         ["length: 862 words, too long (the step asks for about 600 words): cut it to about 495 words"])
        under = prose_gate.word_target("Keep it under 150 words. " + MARK)
        self.assertEqual(dropped(["words_over"], gate={"words": 240, "target": under}),
                         ["length: 240 words, too long (the step asks for under 150 words): cut it to about 128 words"])
        # the model's own heading isn't quoted back: those words aren't ours to tell; and the line holds also when the
        # notes told only to use the heading the instructions give (no line of ours above it to point at)
        self.assertEqual(dropped(["heading_not_title"], gate={"heading": "Soil – and more " + MARK}),
                         [T.HEADING_FAILED])
        self.assertEqual(T.HEADING_FAILED,
                         "the heading line wasn't the step's title or a heading its instructions give")
        self.assertEqual(dropped(["intro"], gate={"framing": ["In this report"]}),
                         [T.FRAMING_FAILED + " (In this report)"])
        # a reason whose line the gate's tell gives (quoting the model) isn't told again as a bare code
        self.assertEqual(dropped(["claims_source", "step_id_leak", "csv_fields"], gate={"tell": ["x " + MARK]}), [])

    def test_the_problems_of_the_verdict_that_turned_it_down(self):
        def judged(first, second=None):
            j = {"verdict": first, "ok": False, "second": second}
            return T._section_failures({"reasons": ["judge"], "gate": {}, "verdict": None, "judge": j})
        kept = {"score": 4, "problems": ["The heading wording is a little long. " + MARK]}
        low = {"score": 2, "problems": ["Invents a 22 % saving as fact. " + MARK]}
        # real: gpt-oss kept it (4) and qwen3.8's second opinion turned it down: the next try hears qwen3.8's reasons
        self.assertEqual(judged(kept, {"verdict": low, "ok": False}), ["a grader found: " + low["problems"][0]])
        self.assertEqual(judged(low), ["a grader found: " + low["problems"][0]])
        self.assertEqual(judged(low, None), judged(low))
        self.assertEqual(judged(kept, {"verdict": None, "ok": False}), ["a grader turned it down"])  # unreadable
        self.assertEqual(judged(None), ["a grader turned it down"])
        # a problem that only parrots the judge's own prompt (a run of eight of its words) isn't passed on
        parrot = {"score": 2, "problems": [
            "Its format requires the section to start with a ## heading line, and it doesn't. " + MARK,
            "Does it do only its step: no introduction, conclusion or summary of the whole project? " + MARK,
            "Invents a 22 % saving as fact. " + MARK]}
        self.assertEqual(judged(parrot), ["a grader found: " + parrot["problems"][2]])
        self.assertEqual(judged(dict(parrot, problems=parrot["problems"][:2])), ["a grader turned it down"])

    def test_what_the_next_try_is_told(self):
        # A Blender or code candidate: the validator's messages for what failed it, lint errors, the crash, then the
        # gate's tell lines; real: 27 of 28 later files tries in the smoke failed the form rule again, never told.
        lint = {"level": "error", "kind": "attr", "message": "Light has no attribute 'enrgy'. " + MARK, "line": 3}
        crash = {"step": "s2", "part": "build", "function": "build_s2", "piece_line": 12, "line": 12,
                 "source": "x = 1", "error": "TypeError: bad. " + MARK, "runner": "Blender 5.2.2"}
        tell = "the lamp faces up; its step says it hangs facing down. " + MARK
        gated = {"verdict": {"ok": True, "form_ok": True, "issues": []}, "crash": crash,
                 "gate": {"lint": [lint, dict(lint, level="warn")], "tell": [tell, ""]}}
        self.assertEqual(T._failures([gated], "blender"), [lint, crash, tell])
        # a code gate's line for its crash says the same as the crash, which keeps its line and source
        compiled = {"verdict": {"ok": True, "form_ok": True, "issues": []}, "crash": dict(crash, runner="Python 3"),
                    "gate": {"tell": ["it doesn't compile: line 12: TypeError: bad. " + MARK, tell]}}
        self.assertEqual(T._failures([compiled], "python-script"), [compiled["crash"], tell])
        issues = [{"level": "warn", "code": "placeholder", "message": "a placeholder. " + MARK},
                  {"level": "warn", "code": "file_line_decorated", "message": "the File: line isn't plain. " + MARK},
                  {"level": "error", "code": "no_file_line", "message": "the block has no File: line. " + MARK}]
        refused = {"verdict": {"ok": False, "form_ok": False, "issues": issues}, "gate": None, "crash": None}
        self.assertEqual(T._failures([refused], "files"), [issues[1]["message"], issues[2]["message"]])
        near = {"verdict": {"ok": True, "form_ok": False, "issues": issues[:2]}, "gate": None, "crash": None}
        self.assertEqual(T._failures([near], "python-script"), [issues[1]["message"]])  # the form warning only
        passed = {"verdict": {"ok": True, "form_ok": True, "issues": issues[:1]}, "gate": {"ok": True, "tell": []}}
        self.assertEqual(T._failures([passed], "files"), [])
        # A section: its own lines, then its gate's.
        line = "it says it was taken from a website. " + MARK
        sec = {"reasons": ["heading_not_title"], "gate": {"tell": [line]}, "verdict": None, "judge": None}
        self.assertEqual(T._failures([sec], "section"), [T.HEADING_FAILED, line])

    def test_a_code_steps_tests_status(self):
        def status(tests, variant=None):
            return T.tests_status({"tests": tests, "variant": variant})
        self.assertEqual(status({"valid": True}), "valid")
        self.assertEqual(status({"kept_untested": True, "fault": None}), "unconfirmed")
        self.assertEqual(status({"kept_untested": True, "fault": "tests_unreachable"}), "none:tests_unreachable")
        self.assertEqual(status({"kept_untested": True, "fault": "third_party"}), "none:third_party")
        self.assertEqual(status({"valid": False, "why": "no_python"}), "none:no_python")
        self.assertEqual(status(None), "none:no_tests")
        self.assertEqual(status({"valid": True}, variant="failed_dep"), "none:variant")
        # refused at parse and not replaced (the retry gave none, or there was none to give: tests_syntax)
        refused = [{"why": "name_guess"}]
        self.assertEqual(status({"code": None, "why": "no_tests", "refused": refused}), "none:tests_refused")
        self.assertEqual(status({"code": None, "why": "subprocess", "refused": refused * 2}), "none:tests_refused")
        self.assertEqual(status({"code": None, "why": "tests_syntax"}), "none:tests_refused")
        self.assertEqual(status({"code": None, "why": "no_asserts"}), "none:tests_refused")
        self.assertEqual(status({"code": "assert f() == 1\n", "valid": True, "refused": refused}), "valid")
        self.assertEqual(status({"code": None, "why": "no_tests"}), "none:no_tests")  # nothing to call, it said
        # a piece no tests ran on whose import missed a package outside the standard library (settle_tests)
        for tests in ({"code": None, "why": "no_tests"}, {"code": None, "why": "no_python"},
                      {"code": None, "why": "no_tests", "refused": refused}):
            self.assertEqual(T.tests_status({"tests": tests, "import_fault": "third_party"}), "none:third_party")
        self.assertEqual(T.tests_status({"tests": None, "variant": "failed_dep", "import_fault": "third_party"}),
                         "none:third_party")
        self.assertEqual(T.tests_status({"tests": {"why": "no_tests"}, "import_fault": None}), "none:no_tests")

    def test_a_step_that_names_a_callable_and_the_records_format(self):
        for words in ("Write parse_line(line), which splits a line.", "Add main() and call it.",
                      "Define class Store with add and get.", "Write def tally over the words."):
            self.assertTrue(T.names_callable(words + " " + MARK), words)
        for words in ("Make sure the function is callable from the entry point.", "Write the file(s) and the "
                      "config file(es).", "A section (about 300 words) on the parser.", ""):
            self.assertFalse(T.names_callable(words + (" " + MARK if words else "")), words)
        plan = {"steps": [{"title": "Parser", "instructions": "Write parse.py. " + MARK}]}
        self.assertEqual(T.step_words(plan, 0), "Parser\nWrite parse.py. " + MARK)
        self.assertEqual((T.record_format({"format": 2}), T.record_format({}), T.record_format(None)), (2, 1, 1))
        self.assertEqual(T.DATAGEN_FORMAT, 6)  # since the fifth smoke (Nov 6)

    def test_the_failing_assert_line(self):
        code = (MARK + "\n"
                'r = tally("a b")\n'
                'assert r == 2, f"expected 2, got {r}"\n'
                'assert tally("") == 0, "empty is %d words" % 0\n'
                'assert tally("x")\n'
                'assert tally("a  b") == 2, "two {} spaces".format("wide")\n'
                'print("tests ok")\n')
        self.assertEqual(T.failing_assert(code, "AssertionError: expected 2, got 3"),
                         'assert r == 2, f"expected 2, got {r}"')
        self.assertEqual(T.failing_assert(code, "AssertionError: empty is 1 words"),
                         'assert tally("") == 0, "empty is %d words" % 0')
        self.assertEqual(T.failing_assert(code, "AssertionError: two wide spaces"),
                         'assert tally("a  b") == 2, "two {} spaces".format("wide")')
        self.assertEqual(T.failing_assert(code, "AssertionError"), 'assert tally("x")')  # the one without a message
        self.assertEqual(T.failing_assert(code, "AssertionError: something else"), "")
        self.assertEqual(T.failing_assert(code, "NameError: name 'tally' is not defined"), "")  # its own line says
        self.assertEqual(T.failing_assert("assert f() == 1\n", "AssertionError: anything"), "assert f() == 1")
        self.assertEqual(T.failing_assert("assert (", "AssertionError"), "")


class ScriptPlanTests(Base):
    size = dict(Base.size, failed_dep=1.0)

    def test_tests_a_repair_example_and_a_variant(self):
        rec = self.run_seed(self.env(), self.seed(F.SCRIPT_PLAN))
        r1 = rec["rounds"][0]
        s1, s2 = r1["steps"]
        self.assertEqual(s1["mode"], "python-script")
        self.assertEqual(s1["kept"], {"from": "cand", "index": 0})
        self.assertTrue(s1["tests"]["valid"], s1["tests"])
        self.assertTrue(s1["candidates"][0]["gate"]["tests"]["passed"])
        self.assertEqual(s1["names"], None)  # not a Blender step: names_gate keeps the sheet out
        # Report: every candidate crashes on import; one repair fixes it, changing 1 line of its code.
        self.assertEqual([c["sample"] for c in s2["candidates"]], [0, 1, 2])  # 2, then 1 more, each its own sample
        self.assertTrue(all(c["crash"] and "NameError" in c["crash"]["error"] for c in s2["candidates"]))
        self.assertEqual(s2["kept"], {"from": "repair", "index": 0})
        rp = s2["repairs"][0]
        self.assertEqual((rp["turn"], rp["passed"], rp["lines_changed"]), (1, True, 1))
        self.assertTrue(rp["example"])
        self.assertLessEqual(rp["share"], T.REPAIR_SHARE)
        self.assertEqual(rp["inputs"]["crash"], s2["candidates"][rp["from"]["cand"]]["crash"])
        self.assertIn(F.REPAIR, rp["request"]["messages"][1]["content"])
        # The failed_dep variant of Report gets the unrepaired piece (variants get no repairs) and is dropped.
        (v,) = r1["variants"]
        self.assertEqual((v["variant"], v["left_out"], v["kept"], v["repairs"]), ("failed_dep", "s1", None, []))
        self.assertEqual(v["missing_deps"], ["s1"])
        self.assertIn("import_crash", v["drop"])
        self.assertEqual(r1["plan_check"]["code"]["ok"], True)
        self.assert_requests_are_chimeras(rec)
        self.assert_teacher_copies_carry_the_notes(rec)
        tests = _fake.bodies("tests")
        self.assertEqual(len(tests), 2)
        self.assertTrue(all(b["format"] == "json" and b["options"]["temperature"] == 0 for b in tests))
        # Report, kept from its repair, gives only the repair example: its reply answers the crash message, which its
        # first request never showed.
        ex = T.examples(rec)
        self.assertEqual([(m["sid"], m["source"], m["repaired"], m["tests"]) for _, m in ex],
                         [("s1", "cand", False, "valid"), ("s2", "repair", True, "none:no_tests")])
        self.assertEqual(ex[1][0][:-1], rp["request"]["messages"])
        self.assertEqual(ex[1][0][-1], {"role": "assistant", "content": rp["content"]})
        self.assertEqual(r1["steps"][0]["tests_status"], "valid")

    def test_a_repair_that_rewrites_most_of_the_piece_is_kept_but_no_example(self):
        rec = self.run_seed(self.env(size={"failed_dep": 0.0}), self.seed(F.REWRITE_PLAN))
        s2 = rec["rounds"][0]["steps"][1]
        rp = s2["repairs"][0]
        self.assertEqual((s2["kept"], rp["passed"]), ({"from": "repair", "index": 0}, True))
        self.assertGreater(rp["share"], T.REPAIR_SHARE)
        self.assertFalse(rp["example"])
        self.assertEqual([(m["sid"], m["repaired"]) for _, m in T.examples(rec)], [("s1", False)])

    def test_a_repair_that_drops_what_its_step_asks_for_is_kept_but_no_example(self):
        # Like smoke2 blender-0002-02 r1 s4, which deleted the compositor block its step asks for: under
        # REPAIR_SHARE on code lines, but leaving out more than REPAIR_SHRINK of them
        rec = self.run_seed(self.env(size={"failed_dep": 0.0}), self.seed(F.TRIM_PLAN))
        s2 = rec["rounds"][0]["steps"][1]
        rp = s2["repairs"][0]
        self.assertEqual((s2["kept"], rp["passed"]), ({"from": "repair", "index": 0}, True))
        self.assertLessEqual(rp["share"], T.REPAIR_SHARE)
        self.assertEqual((rp["share"], rp["shrink"]), (0.263, 0.211))
        self.assertFalse(rp["example"])
        self.assertEqual([(m["sid"], m["repaired"]) for _, m in T.examples(rec)], [("s1", False)])

    def test_round_two_after_a_review(self):
        rec = self.run_seed(self.env(size={"round2": 1.0, "failed_dep": 0.0}), self.seed(F.SCRIPT_PLAN))
        self.assertEqual(rec["round2"], "ran")
        r1, r2 = rec["rounds"]
        self.assertIn(r1["check"]["outcome"], ("passed", "unsure", "skipped"))
        self.assertEqual((r1["review"]["model"], r1["review"]["done"]), ("hydra:1.0", False))
        self.assertEqual(r1["critique"], "Make the light warmer. " + MARK)
        self.assertEqual(r2["prior"], r1["result"])
        self.assertEqual(r2["planner"]["model"], "hydra:1.0")
        for st in r2["steps"]:
            self.assertEqual(st["inputs"]["prev_result"], r1["result"])
            self.assertEqual(st["inputs"]["critique"], r1["critique"])
        self.assertIn(r1["critique"], r2["steps"][0]["request"]["messages"][1]["content"])
        # A repair request leaves round 2's fields out (Chimera's own rule), so it repeats round 1's.
        self.assertEqual(r2["steps"][1]["repairs"][0]["request"], r1["steps"][1]["repairs"][0]["request"])
        self.assert_requests_are_chimeras(rec)


class TestsAndNotesTests(Base):
    """Tests that fail on the stub and on every first-round candidate, and a reply that repeats a teacher note."""

    def test_unconfirmed_tests_gate_every_later_candidate(self):
        rec = self.run_seed(self.env(), self.seed(F.TEXT_PLAN))
        r1 = rec["rounds"][0]
        s1, s2, s3, s4 = r1["steps"]
        self.assertEqual((s1["kept"], s1["tests_status"]), ({"from": "cand", "index": 0}, "valid"))
        # Words: gpt-oss's {} fails the tests in both rounds, so they stay unconfirmed and gate the second sampler,
        # whose piece passes them: that confirms them, and the {} pieces are never kept.
        self.assertEqual([c["model"] for c in s2["candidates"]], ["gpt-oss:120b"] * 3 + ["qwen3.8:27b"] * 2)
        self.assertEqual(s2["tests"]["check"]["why"], "no_candidate_passed")
        self.assertTrue(all(c["gate"]["tests"] is not None for c in s2["candidates"][:4]))
        self.assertTrue(all(c["reasons"] == ["tests_failed"] for c in s2["candidates"][:3]))
        self.assertEqual(s2["kept"], {"from": "second", "index": 3})
        self.assertEqual((s2["tests"]["valid"], s2["tests"]["confirmed_by"], s2["tests_status"]),
                         (True, {"cand": 3}, "valid"))
        # Letters: every candidate fails the tests (gpt-oss's with a NameError once the tests call it), so none is
        # repaired from them (Chimera's own check never runs them) and, as nothing ever passes them, a piece is kept
        # on the import run alone, marked unconfirmed.
        self.assertEqual(s3["repairs"], [])
        self.assertTrue(all("tests_failed" in c["with_tests"]["reasons"] for c in s3["candidates"][:3]))
        self.assertEqual(s3["kept"], {"from": "cand", "index": 0})
        k = s3["candidates"][0]
        self.assertEqual((k["gate"]["tests"], k["gate"]["ok"]), (None, True))
        self.assertEqual((s3["tests"]["valid"], s3["tests"]["kept_untested"], s3["tests_status"]),
                         (False, True, "unconfirmed"))
        self.assertFalse(s3["tests"]["rewrite"]["valid"])  # asked once more first: the same tests, which still fail
        self.assertIsNone(s3["tests"]["fault"])  # a NameError and a wrong count are the pieces' own
        # Echo repeats FORMAT_NOTE, which only the teacher's copy has: every candidate is dropped before the gate.
        self.assertEqual(s4["drop"], ["teacher_note"])
        self.assertTrue(all((c["stage"], c["echoed"]) == ("harmony", "format_note") for c in s4["candidates"]))
        self.assertEqual(s4["tests_status"], "none:no_tests")
        ex = {m["sid"]: m for _, m in T.examples(rec, keep_plan_failed=True)}
        self.assertEqual({k: m["tests"] for k, m in ex.items()}, {"s1": "valid", "s2": "valid", "s3": "unconfirmed"})
        self.assert_requests_are_chimeras(rec)
        self.assert_teacher_copies_carry_the_notes(rec)

    def test_tests_a_hollow_piece_passes_are_never_confirmed(self):
        # Vowels: the tests only name count_vowels. gpt-oss's pieces lack it, so the tests stay unconfirmed;
        # qwen3.8:27b's {} passes them, but so does its hollow copy, so they don't count and nothing is "valid".
        rec = self.run_seed(self.env(), self.seed(F.VOWELS_PLAN))
        s1, s2 = rec["rounds"][0]["steps"]
        self.assertEqual((s2["tests"]["check"]["why"], s2["tests"]["confirm"]["why"]),
                         ("no_candidate_passed", "passes_on_hollow"))
        self.assertEqual(s2["kept"]["from"], "second")
        self.assertEqual((s2["tests"]["valid"], s2["tests"]["unconfirmed"], s2["tests_status"]),
                         (False, False, "none:passes_on_hollow"))
        self.assertNotIn("confirmed_by", s2["tests"])
        ex = {m["sid"]: m for _, m in T.examples(rec, keep_plan_failed=True)}
        self.assertEqual(ex["s2"]["tests"], "none:passes_on_hollow")

    def test_a_files_repair_keeps_its_piece_but_is_no_example(self):
        # Chimera's files join has no line map, so it never sends a files repair: the repaired piece is kept (and
        # feeds the join) but makes no example, neither as a repair nor as the first request's answer.
        rec = self.run_seed(self.env(), self.seed(F.SCALE_PLAN))
        s1, s2 = rec["rounds"][0]["steps"]
        self.assertEqual(s2["mode"], "files")
        rp = s2["repairs"][0]
        self.assertEqual((s2["kept"], rp["passed"]), ({"from": "repair", "index": 0}, True))
        self.assertLessEqual(rp["share"], T.REPAIR_SHARE)
        self.assertEqual((rp["sendable"], rp["example"]), (False, False))
        self.assertEqual([m["sid"] for _, m in T.examples(rec, keep_plan_failed=True)], ["s1"])
        self.assert_requests_are_chimeras(rec)


class FilesPlanTests(Base):
    size = dict(Base.size, failed_dep=1.0, mixed_pool=1.0, round2=1.0)

    def test_second_sampler_drop_failed_dependency_and_variants(self):
        seed = self.seed(F.FILES_PLAN)
        _fake.review_done.add(GOAL)
        rec = self.run_seed(self.env(), seed)
        r1 = rec["rounds"][0]
        s1, s2, s3, s4 = r1["steps"]
        self.assertEqual({s["mode"] for s in r1["steps"]}, {"files"})
        self.assertTrue(s1["kept"] and s1["tests"]["valid"])
        # Totals: gpt-oss's three miss total() (no crash, so no repair); qwen3.8:27b's first is kept.
        self.assertEqual([c["model"] for c in s2["candidates"]], ["gpt-oss:120b"] * 3 + ["qwen3.8:27b"] * 2)
        self.assertTrue(all("symbols_missing" in c["reasons"] for c in s2["candidates"][:3]))
        self.assertEqual((s2["kept"], s2["repairs"]), ({"from": "second", "index": 3}, []))
        # Its tests failed on every first-round candidate, so they stayed unconfirmed until qwen3.8:27b passed them.
        self.assertEqual(s2["tests"]["check"]["why"], "no_candidate_passed")
        self.assertEqual((s2["tests"]["confirmed_by"], s2["tests_status"]), ({"cand": 3}, "valid"))
        # Format: crashes on import whatever it is asked: two repair turns, the second sampler, then dropped.
        self.assertIsNone(s3["kept"])
        self.assertEqual([r["turn"] for r in s3["repairs"]], [1, 2])
        self.assertEqual(s3["repairs"][1]["from"], {"repair": 0})
        self.assertEqual(s3["drop"], ["import_crash"])
        # Main: told Format failed, and kept.
        self.assertEqual(s4["missing_deps"], ["s3"])
        self.assertIn("s3", s4["request"]["messages"][1]["content"])
        self.assertTrue(s4["kept"])
        by = {(v["sid"], v["variant"]): v for v in r1["variants"]}
        self.assertEqual(by[("s4", "failed_dep")]["left_out"], "s2")  # the only dependency it had
        self.assertTrue(by[("s4", "failed_dep")]["kept"])
        mixed = by[("s4", "mixed_pool")]
        self.assertIn(mixed["today"]["model"], ("qwen3.8:27b", "qwen3:8b"))
        self.assertEqual(mixed["inputs"]["outputs"]["s2"], mixed["today"]["content"])
        self.assertTrue(mixed["kept"])
        self.assertEqual([j for j, _ in _fake.jobs()].count("today"), 2)  # s2's and s4's mixed_pool
        # Round 2: the files result has no script to check, and the review says done.
        self.assertEqual(r1["check"]["outcome"], "skipped")
        self.assertEqual(rec["round2"], "review_done")
        self.assertEqual(len(rec["rounds"]), 1)
        self.assertTrue(r1["plan_check"]["code"]["ok"])
        self.assert_requests_are_chimeras(rec)
        self.assert_teacher_copies_carry_the_notes(rec)


class PlannerTests(Base):
    size = dict(Base.size, round2=1.0)

    def test_hydra_plan_unreadable_falls_back_to_gpt_oss_and_a_lone_step(self):
        seed = self.seed(F.LONE_PLAN)
        _fake.bad_plans.add(GOAL)
        rec = self.run_seed(self.env(), seed)
        p = rec["rounds"][0]["planner"]
        self.assertEqual((p["drew"], p["model"], p["fell_back"]), ("hydra:1.0", "gpt-oss:120b", True))
        self.assertEqual([(t["model"], t["ok"]) for t in p["tries"]], [("hydra:1.0", False), ("gpt-oss:120b", True)])
        (st,) = rec["rounds"][0]["steps"]
        self.assertTrue(st["lone"])
        self.assertEqual((st["mode"], st["kept"]["from"]), ("section", "cand"))
        self.assertEqual(rec["round2"], "one_step")
        self.assert_requests_are_chimeras(rec)

    def test_gpt_oss_by_share_and_a_reused_helper_plan(self):
        env = self.env(size={"gpt_oss_planner": 1.0, "round2": 0.0})
        rec = self.run_seed(env, self.seed(F.LONE_PLAN))
        self.assertEqual(rec["rounds"][0]["planner"]["model"], "gpt-oss:120b")
        with _fake.lock:
            _fake.calls.clear()
        raw = {"coding-0001-00": {"reply": json.dumps(F.SCRIPT_PLAN), "key": "k", "wall_s": 41.0,
                                  "file": "plans.jsonl"}}
        env = self.env(size={"gpt_oss_planner": 1.0, "round2": 0.0}, raw=raw)
        rec = self.run_seed(env, self.seed(F.LONE_PLAN, source="helper", seed_id="coding-0001-00"))
        p = rec["rounds"][0]["planner"]
        self.assertTrue(p["reused"])
        self.assertEqual((p["model"], p["orig_wall_s"], p["file"]), ("gpt-oss:120b", 41.0, "plans.jsonl"))
        self.assertEqual(rec["rounds"][0]["plan"]["title"], F.SCRIPT_PLAN["title"])  # the reused one, not the fake's
        self.assertNotIn("plan", [j for j, _ in _fake.jobs()])

    def test_a_plan_that_repeats_the_eval_is_no_plan(self):
        index = F.FixtureIndex(EvalIndex(8))
        ev = an_eval_plan()  # read from eval/ at run time: the eval's text is never copied into code
        rec = T.run_seed(self.env(eval_index=index), self.seed(dict(F.LONE_PLAN, title=ev["title"],
                                                                    summary=ev["summary"])))
        self.assertEqual(rec["status"], "no_plan")
        p = rec["rounds"][0]["planner"]
        self.assertEqual(p["reason"], "eval_plan")
        self.assertTrue(any(h.startswith("worker-eval:") and h.endswith(":head") for h in p["eval_hits"]),
                        p["eval_hits"])
        # An eval scenario's title named in the head is enough, as it is for a seed.
        title = next(t for t in seeds.eval_titles() if len(seeds.words(t)) >= 2)
        goal = "Another note, please. " + MARK
        rec = T.run_seed(self.env(eval_index=index), self.seed(dict(F.LONE_PLAN, title=title.upper()), goal=goal))
        self.assertEqual(rec["status"], "no_plan")
        self.assertIn("eval_title:" + title, rec["rounds"][0]["planner"]["eval_hits"])
        # The fixture's own plan repeats nothing.
        rec = self.run_seed(self.env(eval_index=index), self.seed(F.LONE_PLAN, goal="A third note. " + MARK))
        self.assertNotIn("reason", rec["rounds"][0]["planner"])

    def test_a_request_too_long_for_hydra_goes_to_gpt_oss(self):
        goal = GOAL + " " + "Some more detail about the project. " * 700
        rec = self.run_seed(self.env(size={"round2": 0.0}), self.seed(F.LONE_PLAN, goal=goal))
        p = rec["rounds"][0]["planner"]
        self.assertEqual((p["drew"], p["helper_fits"], p["model"]), ("hydra:1.0", False, "gpt-oss:120b"))
        body = _fake.bodies("plan")[0]
        self.assertEqual(body["format"], "json")
        self.assertEqual(body["options"]["num_ctx"], L.FIXED_CTX["gpt-oss:120b"])


class JudgeAndFailureTests(Base):
    size = dict(Base.size, prose_second=1.0)

    def test_the_prose_judge_turns_a_section_down_and_its_second_opinion(self):
        _fake.prose_low.add("Note")
        rec = self.run_seed(self.env(), self.seed(F.LONE_PLAN))
        (st,) = rec["rounds"][0]["steps"]
        self.assertEqual(len(st["candidates"]), 3)  # sections: 1, then 1 more, then 1 more
        self.assertIsNone(st["kept"])
        self.assertEqual(st["drop"], ["judge"])
        self.assertEqual(st["candidates"][0]["judge"]["verdict"]["score"], 2)
        self.assertIsNone(st["candidates"][0]["judge"]["second"])  # only asked when gpt-oss keeps it
        # each later try is told what the grader found in the ones before
        sys_msgs = [b["messages"][0]["content"] for b in _fake.bodies("worker")]
        problems = st["candidates"][0]["judge"]["verdict"]["problems"]
        self.assertTrue(problems)
        self.assertNotIn(H.FAILED_ON, sys_msgs[0])
        for m in sys_msgs[1:]:
            self.assertIn(H.FAILED_ON + "\n- a grader found: " + problems[0][:200], m)
        _fake.prose_low.clear()  # a new goal: the same messages would replay the low score from the cache
        rec = self.run_seed(self.env(), self.seed(F.LONE_PLAN, goal="Another note, please. " + MARK))
        j = rec["rounds"][0]["steps"][0]["candidates"][0]["judge"]
        self.assertTrue(j["ok"])
        self.assertEqual(j["second"]["model"], "qwen3.8:27b")

    def test_a_failed_call_makes_the_seed_an_error(self):
        _fake.errors.add("hydra:1.0")
        rec = T.run_seed(self.env(), self.seed(F.LONE_PLAN))
        self.assertEqual(rec["status"], "error")
        self.assertIn("hydra:1.0 (plan)", rec["error"])
        self.assertEqual(rec["rounds"], [])

    def test_stop_passes_through(self):
        def stop():
            raise C.StopRequested("STOP exists")
        with self.assertRaises(C.StopRequested):
            T.run_seed(self.env(stop=stop), self.seed(F.LONE_PLAN))


class SectionNotesTests(Base):
    """A dropped section's notes, through the binary's validator and the real prose gate (no model is asked)."""

    PLAN = {"title": "Render memo " + MARK, "kind": "writing", "summary": "A memo on two renderers. " + MARK, "steps": [
        {"id": "s1", "title": "Write Current workflow audit (≈60 words)", "kind": "writing", "depends_on": [],
         "instructions": 'Write the "Current workflow audit" section. ' + MARK},
        {"id": "s2", "title": "Write Side‑by‑side render quality comparison (≈60 words)", "kind": "writing",
         "depends_on": [], "instructions": 'Compose the "Side‑by‑side render quality comparison (resolution 8K)" '
                                           "section. " + MARK}]}
    BODY = ("Both renderers resolve fine fabric weave at full resolution, but one keeps noise lower in the deep "
            "shadows while the other holds sharper glints on brushed metal. Render times sit close together on the "
            "same card, so the choice rests on how each handles glass, caustics and the studio's existing material "
            "library. ")

    def candidate(self, heading, index):
        content = (f"## {heading}\n\n{self.BODY}\n\n```handoff\nprovides: the comparison section\nuses: none\n"
                   f"assumed: {MARK}\n```\n")
        return {"content": content, "runaway": False, "done_reason": "stop", "reasons": [], "stage": "reply",
                "verdict": None, "gate": None, "judge": None, "crash": None, "mech": False, "passed": False,
                "index": index}

    def test_a_second_try_with_the_notes_heading_is_no_teacher_note(self):
        # real: the smoke seed's s3, told its heading, first wrote it with a subtitle after it
        rnd = T.Round(self.env(), self.seed(self.PLAN), 1, self.PLAN, {})
        step = rnd.step_record(1, {})
        told = prose_gate.section_heading(self.PLAN["steps"][1])
        self.assertEqual(told, "Side‑by‑side render quality comparison (resolution 8K)")
        first = self.candidate(told + " – Redshift vs Octane", 0)
        self.assertTrue(rnd.precheck(step, first, step["request"]))
        self.assertFalse(rnd.gate(step, first, False))
        self.assertEqual(first["reasons"], ["heading_not_title"])
        failures = T._failures([first], "section")
        self.assertEqual(failures, [T.HEADING_FAILED] + first["gate"]["tell"])  # the gate's own lines come after
        notes = H.hints_for(self.PLAN, 1, "section", None, failures)
        self.assertIn(H.FAILED_ON + "\n- " + T.HEADING_FAILED, notes)
        self.assertNotIn("Redshift vs Octane", notes)
        extra = H.teacher_lines("section", failures)
        self.assertEqual(extra, [])
        second = self.candidate(told, 1)
        quoted = [f"the heading line: {first['gate']['heading']!r} isn't the one given"]  # the old line
        self.assertEqual(H.echoed_note(second["content"], quoted), "extra")  # would have dropped it
        self.assertTrue(rnd.precheck(step, second, step["request"], extra), second["reasons"])
        self.assertTrue(rnd.gate(step, second, False), second["reasons"])
        # a try that copies the failure line itself into its piece repeats our words: never a target
        third = self.candidate(told, 2)
        third["content"] = third["content"].replace(self.BODY, self.BODY + "Note: " + T.HEADING_FAILED + ". ")
        self.assertFalse(rnd.precheck(step, third, step["request"], extra))
        self.assertEqual((third["reasons"], third["echoed"]), (["teacher_note"], "failure_line"))


class AfterSmokeTests(Base):
    """What the first smoke run (Nov 3) changed in a step's path: replies made plain, versions only the notes name,
    what the next try is told, the second sampler's limit and a files step without Python."""

    def tries_of(self, sid, title):
        """The system messages of the worker calls the stand-in got for one step, in order."""
        return [b["messages"][0]["content"] for b in _fake.bodies("worker")
                if f"Your step, {sid}: {title}\n" in b["messages"][1]["content"]]

    def test_a_bold_file_line_is_made_plain_and_a_python_projects_page(self):
        # real: gpt-oss wrote 129 of its 133 File lines in the smoke as **File: path**, a near miss of the form
        rec = self.run_seed(self.env(), self.seed(F.BOLD_PLAN))
        s1, s2, s3 = rec["rounds"][0]["steps"]
        self.assertEqual({s["mode"] for s in (s1, s2, s3)}, {"files"})
        c = s2["candidates"][0]
        self.assertEqual(c["normalised"], {"file_lines": 1, "marker_dashes": 0})
        self.assertTrue(c["content"].startswith("File: tool/bold.py\n```python\n"), c["content"][:80])
        self.assertEqual((s2["kept"], s2["tests_status"]), ({"from": "cand", "index": 0}, "valid"))
        raw = C.Cache(os.path.join(self.dir, "cache", "calls.jsonl")).get(c["key"])
        self.assertTrue(raw["content"].startswith("**File: tool/bold.py**\n"))  # the reply as it came, in the cache
        ex = {m["sid"]: msgs for msgs, m in T.examples(rec, keep_plan_failed=True)}
        self.assertEqual(ex["s2"][-1], {"role": "assistant", "content": c["content"]})
        # Page writes only HTML, but Parser's and Bold's pieces before it are Python, so the round is a Python
        # project and its tests are asked for (code_gate.no_python's python_project); the writer gives none, and
        # nothing ran on the piece (no import run either), so it is kept, marked nothing_ran (the build: unverified).
        self.assertEqual((s3["kept"], s3["tests"]["why"], s3["tests_status"], s3["nothing_ran"]),
                         ({"from": "cand", "index": 0}, "no_tests", "none:no_tests", True))
        self.assertIsNone(s3["candidates"][0]["gate"]["tests"])
        self.assertEqual((s1["nothing_ran"], s2["nothing_ran"]), (False, False))
        asked = [re.search(r"^The step under review, (s\d+):", b["messages"][1]["content"], re.M).group(1)
                 for b in _fake.bodies("tests")]
        self.assertEqual(asked, ["s1", "s2", "s3"])
        self.assertEqual({m["sid"]: m["nothing_ran"] for _, m in T.examples(rec)}, {"s1": False, "s2": False,
                                                                                    "s3": True})
        self.assert_requests_are_chimeras(rec)

    def test_a_stand_in_marker_with_another_hyphen_and_a_version_only_the_notes_name(self):
        rec = self.run_seed(self.env(blender=StubBlender(plan_ok=True), names={}), self.seed(F.STUB_PLAN))
        s1, s2, s3 = rec["rounds"][0]["steps"]
        c = s2["candidates"][0]
        self.assertEqual(c["normalised"], {"file_lines": 0, "marker_dashes": 1})
        self.assertIn('print("chimera: stand-in", "floor")', c["content"])
        self.assertNotIn("\u2011", c["content"])
        self.assertEqual(s2["kept"], {"from": "cand", "index": 0})
        # real: 4 of qwen3.8's 13 targets named 5.2.2 or 5.0.1, which only the teacher's notes carried
        self.assertEqual([(x["reasons"], x.get("echoed")) for x in s3["candidates"][:4]],
                         [(["teacher_note"], "version_leak")] * 4)
        self.assertEqual(s3["kept"], {"from": "second", "index": 4})
        self.assertNotIn("5.2.2", json.dumps(s3["request"]))
        self.assert_requests_are_chimeras(rec, names={})

    def test_the_validators_message_reaches_the_next_try(self):
        rec = self.run_seed(self.env(), self.seed(F.FIXED_PLAN))
        s2 = rec["rounds"][0]["steps"][1]
        self.assertEqual([c["reasons"] for c in s2["candidates"][:2]], [["validator:no_file_line"]] * 2)
        message = next(x["message"] for x in s2["candidates"][0]["verdict"]["issues"] if x["code"] == "no_file_line")
        self.assertEqual(s2["kept"], {"from": "cand", "index": 2})
        tries = self.tries_of("s2", "Fixed")
        self.assertEqual(len(tries), 3)
        self.assertTrue(all(H.FAILED_ON not in m for m in tries[:2]))
        self.assertIn(H.FAILED_ON + "\n- " + message, tries[2])
        self.assertNotIn(message, json.dumps(s2["request"]))  # teacher-only
        self.assert_requests_are_chimeras(rec)

    def test_a_gates_tell_lines_reach_the_next_try(self):
        line = "it measures 8 m across where its step asks for 4 m. " + MARK
        rec = self.run_seed(self.env(blender=StubBlender(plan_ok=True, tell={"s1": (2, [line])}), names={}),
                            self.seed(F.BLENDER_PLAN))
        s1 = rec["rounds"][0]["steps"][0]
        self.assertEqual([c["reasons"] for c in s1["candidates"]], [["size_mismatch"]] * 2 + [[], []])
        self.assertEqual(s1["kept"], {"from": "cand", "index": 2})
        tries = self.tries_of("s1", "Floor")
        self.assertEqual(len(tries), 4)
        self.assertTrue(all(line not in m for m in tries[:2]))
        self.assertTrue(all(H.FAILED_ON + "\n- " + line in m for m in tries[2:]), tries[2])
        self.assertNotIn(line, json.dumps(s1["request"]))

    def test_the_second_samplers_reply_limit(self):
        # real: one qwen3.8 reply thought for 16,384 tokens and wrote nothing. A code step keeps 8,192 (none of the 58
        # stored code-mode qwen3.8 calls of smoke2-4 ran out at it), as before the fourth smoke's round, so its calls
        # keep their cache keys and seeds; a Blender step has 12,288 (SamplerBudgetTests: a passing Blender reply used
        # 8,118 of 8,192, and 9 of 60 stored Blender calls ran out while still thinking). The independent checks
        # (Nov 6) found the 12,288 reaching this code plan too.
        rec = self.run_seed(self.env(), self.seed(F.TEXT_PLAN))
        self.assertEqual(rec["rounds"][0]["steps"][1]["kept"]["from"], "second")
        bodies = _fake.bodies("worker")
        second = [b for b in bodies if b["model"] == "qwen3.8:27b"]
        self.assertTrue(second)
        self.assertTrue(all(b["options"]["num_predict"] == 8192 for b in second))
        self.assertEqual(T.SECOND_OPTIONS_CODE, {"num_predict": 8192})
        self.assertLess(12288 + 8192, L.FIXED_CTX["qwen3.8:27b"])  # a Blender prompt's 8K and the reply fit its ctx
        self.assertLess(12288, rc.MAX_REPLY_TOKENS)  # under the client's runaway guard
        self.assertNotIn("think", second[0])  # thinking stays as the model has it
        self.assertTrue(all("num_predict" not in b["options"] for b in bodies if b["model"] == "gpt-oss:120b"))


class TestsRewriteTests(Base):
    """The teacher's tests asked for again: once after a refusal, once after failing every candidate."""

    def test_one_rewrite_and_tests_whose_failure_isnt_the_pieces(self):
        rec = self.run_seed(self.env(), self.seed(F.CHECKS_PLAN))
        s1, s2, s3, s4 = rec["rounds"][0]["steps"]
        self.assertEqual({s["mode"] for s in (s1, s2, s3, s4)}, {"python-script"})
        # Tally: the tests want 4 words in "a b c", so they fail all five candidates (3 of gpt-oss's, 2 of
        # qwen3.8's) and stay unconfirmed. The one rewrite, told the failing assert, its error and the provides line,
        # counts on those candidates, and gpt-oss's first is kept with it.
        t = s2["tests"]
        self.assertEqual([c["model"] for c in s2["candidates"]], ["gpt-oss:120b"] * 3 + ["qwen3.8:27b"] * 2)
        self.assertTrue(all(c["before_rewrite"]["reasons"] == ["tests_failed"] for c in s2["candidates"]))
        self.assertEqual((s2["kept"], t["valid"], s2["tests_status"]), ({"from": "cand", "index": 0}, True, "valid"))
        self.assertTrue(s2["candidates"][0]["gate"]["tests"]["passed"])
        rw = t["rewrite"]
        self.assertTrue(rw["valid"])
        once = {"assert": 'assert tally("a b c") == 4, "three words"', "error": "AssertionError: three words",
                "provides": "tally(text) -> int"}
        self.assertEqual(rw["failures"], [once] * 5)
        self.assertIn("# wrong count", rw["old"]["code"])
        self.assertEqual(rw["old"]["why"], "no_candidate_passed")
        self.assertIn('== 3, "three words"', t["code"])
        (body,) = [b for b in _fake.bodies("tests_rewrite") if "# wrong count" in json.dumps(b)]
        shown = "\n".join(m["content"] for m in body["messages"])
        self.assertIn("- candidates 1, 2, 3, 4 and 5: the failing assert: ", shown)  # one line the five share
        self.assertIn("AssertionError: three words", shown)
        self.assertNotIn("len(text.split())", shown)  # never a candidate's code
        # Lines: the tests import a module no step makes, so every run fails the same way and the rewrite gives
        # none better; the piece is kept without them, and they say nothing about it.
        t = s3["tests"]
        self.assertEqual((s3["kept"], t["kept_untested"], t["rewrite"]["valid"]), ({"from": "cand", "index": 0}, True,
                                                                                    False))
        self.assertEqual(t["errors"], ["ModuleNotFoundError: No module named 'wordtool'"])
        self.assertEqual((t["fault"], s3["tests_status"]), ("tests_unreachable", "none:tests_unreachable"))
        # Docs: every candidate imports python-docx, which the sandbox lacks (real: research_draft-0009-04 s4).
        t = s4["tests"]
        self.assertTrue(s4["kept"] and t["kept_untested"])
        self.assertIn("ModuleNotFoundError: No module named 'docx'", t["run_errors"])
        self.assertEqual((t["fault"], s4["tests_status"]), ("third_party", "none:third_party"))
        self.assertEqual(t["rewrite"], {"skipped": "third_party"})  # no tests can bring python-docx in
        self.assertFalse([b for b in _fake.bodies("tests_rewrite") if "# needs docx" in json.dumps(b)])
        ex = {m["sid"]: m["tests"] for _, m in T.examples(rec, keep_plan_failed=True)}
        self.assertEqual(ex, {"s1": "valid", "s2": "valid", "s3": "none:tests_unreachable", "s4": "none:third_party"})
        self.assert_requests_are_chimeras(rec)

    def test_tests_that_start_a_process_are_asked_for_once_more(self):
        rec = self.run_seed(self.env(), self.seed(F.REFUSE_PLAN))
        s2 = rec["rounds"][0]["steps"][1]
        t = s2["tests"]
        self.assertEqual([x["why"] for x in t["refused"]], ["subprocess"])
        self.assertEqual((t["valid"], s2["tests_status"], s2["kept"]), (True, "valid", {"from": "cand", "index": 0}))
        (body,) = _fake.bodies("tests_rewrite")
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user", "assistant", "user"])
        self.assertIn("# starts a process", body["messages"][2]["content"])  # its own reply, then why it was refused
        self.assertEqual(body["messages"][3]["content"], J.TESTS_REFUSED["subprocess"] + " " + J.TESTS_REFUSED_TAIL)
        self.assertEqual(len(_fake.bodies("tests")), 2)  # Count's, Shout's first; no rewrite after the retry


class MissingDependencyTests(Base):
    """A section written with a dependency missing needs qwen3.8's word as well as gpt-oss's, whatever gpt-oss's score
    (real: research_draft-0007-04 lost its research step, and the sections after it invented prices, kept at 4; of
    those gpt-oss gave 5, one sent a road trip's fuel stops past its destination)."""

    def packing(self, gpt, qwen, goal):
        _fake.prose_low.add("Weather facts")
        _fake.prose_scores.update({("Packing list", "gpt-oss:120b"): gpt, ("Packing list", "qwen3.8:27b"): qwen})
        rec = self.run_seed(self.env(), self.seed(F.WRITE_PLAN, goal=goal))
        s1, s2 = rec["rounds"][0]["steps"]
        self.assertEqual((s1["kept"], s2["missing_deps"]), (None, ["s1"]))
        return s2

    def test_both_judges_must_keep_it(self):
        s2 = self.packing(4, 2, "Plan my Lisbon trip. " + MARK)
        self.assertEqual((s2["kept"], s2["drop"]), (None, ["judge"]))
        self.assertTrue(all((c["judge"]["second"]["model"], c["judge"]["rule"]) == ("qwen3.8:27b", "missing_dep")
                            for c in s2["candidates"]))
        s2 = self.packing(5, 2, "Plan my Lisbon trip, please. " + MARK)  # gpt-oss's 5 no longer outweighs qwen3.8
        j = s2["candidates"][0]["judge"]
        self.assertEqual((s2["kept"], s2["drop"], j["verdict"]["score"], j["second"]["ok"], j["ok"], j["rule"]),
                         (None, ["judge"], 5, False, False, "missing_dep"))
        self.assertEqual(len(s2["candidates"]), 3)  # every try turned down the same way
        s2 = self.packing(4, 5, "Plan my Lisbon trip, thanks. " + MARK)
        j = s2["candidates"][0]["judge"]
        self.assertEqual((s2["kept"], j["second"]["ok"], j["ok"]), ({"from": "cand", "index": 0}, True, True))
        s2 = self.packing(5, 4, "Plan my Lisbon trip, merci. " + MARK)
        self.assertEqual(s2["kept"], {"from": "cand", "index": 0})
        # With its dependencies there (or none), a 4 is kept on gpt-oss's word (prose_second is 0 here).
        _fake.prose_scores[("Note", "gpt-oss:120b")] = 4
        rec = self.run_seed(self.env(), self.seed(F.LONE_PLAN, goal="A note for the neighbour. " + MARK))
        j = rec["rounds"][0]["steps"][0]["candidates"][0]["judge"]
        self.assertEqual((j["ok"], j["second"], "rule" in j), (True, None, False))


# Plans of this file's own (fixtures, with the mark): a files step whose words ask for a .py file its tries leave out,
# and a step that imports python-docx, which the sandbox lacks, with no tests written for it.
PY_PAGE_PLAN = dict(F.BOLD_PLAN, title="Mock page tool", steps=F.BOLD_PLAN["steps"][:2] + [
    dict(F.BOLD_PLAN["steps"][2], instructions="Write tool/page.py with page(), which returns the hello page. " +
         MARK)])
DOCS_PLAN = {"title": "Mock word saver", "kind": "code", "summary": "Count words and save them. " + MARK,
             "steps": [F.SCRIPT_PLAN["steps"][0], F.CHECKS_PLAN["steps"][3]]}


class SecondCheckTests(Base):
    """What the second round of checks of the smoke's replies changed in a step's path (Nov 4): no_python reads the
    step's own words, a piece no tests ran on is asked import_fault, tests still refused after the retry, what the
    prose gate is given, and the notes' words for the Blenders, only for Blender steps, less what the request says."""

    def test_no_python_reads_the_steps_own_words(self):
        """The call site: the step's title and instructions go to code_gate.no_python (here a stand-in for its rule:
        no Python when no candidate and nothing in the words names a .py file), so a Python step whose tries left
        their .py files out still gets tests."""
        calls = []

        def by_words(texts, mode, words="", python_project=False):
            calls.append((mode, words))
            return mode == "files" and ".py" not in words and not any(".py" in t for t in texts)
        with mock.patch.object(CG, "no_python", side_effect=by_words):
            rec = self.run_seed(self.env(), self.seed(PY_PAGE_PLAN))
        s3 = rec["rounds"][0]["steps"][2]
        self.assertEqual(rec["format"], T.DATAGEN_FORMAT)
        self.assertTrue(calls)
        self.assertTrue(all(w in [T.step_words(PY_PAGE_PLAN, i) for i in range(3)] for _, w in calls), calls)
        self.assertIn(("files", T.step_words(PY_PAGE_PLAN, 2)), calls)
        # Page's tries write only web/index.html, but its words ask for tool/page.py: tests were asked for
        asked = [re.search(r"^The step under review, (s\d+):", b["messages"][1]["content"], re.M).group(1)
                 for b in _fake.bodies("tests")]
        self.assertEqual(asked, ["s1", "s2", "s3"])
        self.assertEqual((s3["tests"]["why"], s3["tests_status"]), ("no_tests", "none:no_tests"))

    def test_no_python_by_code_gates_own_rule(self):
        """The same with code_gate's real names_python (K1): tool/page.py in Page's words asks for its tests, while
        BOLD_PLAN's Page, which names only web/index.html, is "none:no_python" (test_a_bold_file_line_...)."""
        self.assertTrue(CG.names_python(T.step_words(PY_PAGE_PLAN, 2)))
        self.assertFalse(CG.names_python(T.step_words(F.BOLD_PLAN, 2)))
        rec = self.run_seed(self.env(), self.seed(PY_PAGE_PLAN, goal="A page tool, by the real rule. " + MARK))
        s3 = rec["rounds"][0]["steps"][2]
        asked = [re.search(r"^The step under review, (s\d+):", b["messages"][1]["content"], re.M).group(1)
                 for b in _fake.bodies("tests")]
        self.assertEqual(asked, ["s1", "s2", "s3"])
        self.assertEqual((s3["tests"]["why"], s3["tests_status"]), ("no_tests", "none:no_tests"))
        self.assert_requests_are_chimeras(rec)

    def test_a_piece_no_tests_ran_on_is_asked_import_fault(self):
        """The call site of code_gate.import_fault (a stand-in for its rule here: the import run ended on a missing
        package no candidate writes): Docs, given no tests, imports python-docx, so its piece never ran here."""
        calls = []

        def docx(gate, plan, i, texts, dropped=(), written=()):
            calls.append((i, gate, list(texts)))
            err = (gate.get("run") or {}).get("error") or ""
            return "third_party" if "No module named 'docx'" in err else None
        with mock.patch.dict(F.TESTS, {"Docs": ""}), \
                mock.patch.object(CG, "import_fault", side_effect=docx, create=True):
            rec = self.run_seed(self.env(), self.seed(DOCS_PLAN))
        s1, s2 = rec["rounds"][0]["steps"]
        self.assertEqual((s1["tests_status"], "import_fault" in s1), ("valid", False))  # its tests ran: not asked
        self.assertEqual([c[0] for c in calls], [1])
        _, gate, texts = calls[0]
        kept = s2["candidates"][s2["kept"]["index"]]
        self.assertEqual(gate, kept["gate"])
        self.assertEqual(texts, [c["content"] for c in s2["candidates"]])
        self.assertIn("ModuleNotFoundError: No module named 'docx'", gate["run"]["error"])
        self.assertEqual((s2["tests"]["why"], s2["import_fault"], s2["tests_status"]),
                         ("no_tests", "third_party", "none:third_party"))
        self.assertEqual({m["sid"]: m["tests"] for _, m in T.examples(rec)}, {"s1": "valid", "s2": "none:third_party"})
        self.assertEqual(CG.import_fault(gate, rec["rounds"][0]["plan"], 1, texts), "third_party")  # code_gate's own
        self.assert_requests_are_chimeras(rec)

    def test_tests_still_refused_after_the_retry(self):
        """Shout's tests start a process; told why, the writer gives none at all: the step is kept as
        "none:tests_refused", which the build drops, not as a step with nothing to test."""
        with mock.patch.dict(F.REWRITES, {"# starts a process": ""}), \
                mock.patch.object(CG, "import_fault", return_value=None, create=True):
            rec = self.run_seed(self.env(), self.seed(F.REFUSE_PLAN, goal="Shout, but quietly. " + MARK))
        s2 = rec["rounds"][0]["steps"][1]
        t = s2["tests"]
        # the retry's empty reply isn't a refusal (its outcome is t["retry"]), but Shout's words name shout(text),
        # so empty tests don't say there was nothing to test: the step stays refused
        self.assertEqual(([x["why"] for x in t["refused"]], t["code"], t["why"]), (["subprocess"], None, "no_tests"))
        self.assertEqual(t["retry"], {"why": "no_tests", "gave": "empty", "callable": True})
        self.assertEqual((s2["kept"], s2["tests_status"]), ({"from": "cand", "index": 0}, "none:tests_refused"))
        self.assertIsNone(s2["candidates"][0]["gate"]["tests"])  # gated by its import run alone
        self.assert_requests_are_chimeras(rec)

    def test_tests_that_dont_compile_or_reach_no_assert_get_their_retry_too(self):
        """Every why that makes a step "none:tests_refused" (task.REFUSED) is one the writer is told once
        (judges.TESTS_REFUSED): Shout's first tests don't compile, or assert only inside a function nothing calls;
        the retry's tests count."""
        for why, first in (("tests_syntax", '# no compile\nassert shout("a" == "A"\n'),
                           ("no_asserts", '# no assert runs\ndef test_shout():\n    assert shout("a") == "A"\n')):
            with self.subTest(why=why):
                with _fake.lock:
                    _fake.calls.clear()
                tag = first.split("\n", 1)[0]
                with mock.patch.dict(F.TESTS, {"Shout": first}), \
                        mock.patch.dict(F.REWRITES, {tag: 'assert shout("ab") == "AB"\n'}):
                    rec = self.run_seed(self.env(), self.seed(F.REFUSE_PLAN, goal=f"Shout ({why}). " + MARK))
                s2 = rec["rounds"][0]["steps"][1]
                t = s2["tests"]
                self.assertEqual(J.parse_tests_why(json.dumps({"tests": MARK + "\n" + first})), why)
                self.assertEqual([x["why"] for x in t["refused"]], [why])
                self.assertEqual((t["valid"], s2["tests_status"], s2["kept"]),
                                 (True, "valid", {"from": "cand", "index": 0}))
                (body,) = _fake.bodies("tests_rewrite")
                self.assertEqual([m["role"] for m in body["messages"]], ["system", "user", "assistant", "user"])
                self.assertIn(tag, body["messages"][2]["content"])
                self.assertEqual(body["messages"][3]["content"], J.TESTS_REFUSED[why] + " " + J.TESTS_REFUSED_TAIL)
                self.assert_requests_are_chimeras(rec)

    def test_what_the_prose_gate_is_given(self):
        """prose_gate.section_check gets the dependencies' kept pieces as the judge is shown them ({sid: text, None
        for one that failed}), and the ids of those that failed."""
        real, seen = prose_gate.section_check, []

        def watch(plan, i, text, verdict, earlier, **kw):
            seen.append((plan["title"], i, kw))
            return real(plan, i, text, verdict, earlier, **kw)
        _fake.prose_low.add("Weather facts")
        with mock.patch.object(prose_gate, "section_check", side_effect=watch):
            rec = self.run_seed(self.env(), self.seed(F.WRITE_PLAN, goal="Pack for Lisbon. " + MARK))
            room = self.run_seed(self.env(blender=StubBlender(plan_ok=True), names={}), self.seed(F.BLENDER_PLAN))
        self.assertIn((F.WRITE_PLAN["title"], 1, {"dep_texts": {"s1": None}, "missing_deps": ("s1",),
                                                  "prev_result": ""}), seen)
        self.assertIn((F.WRITE_PLAN["title"], 0, {"dep_texts": {}, "missing_deps": (), "prev_result": ""}), seen)
        self.assertIsNone(rec["rounds"][0]["steps"][0]["kept"])
        lamp = T.kept_target(room["rounds"][0]["steps"][1])[0]
        self.assertIn((F.BLENDER_PLAN["title"], 2, {"dep_texts": {"s2": lamp}, "missing_deps": (), "prev_result": ""}),
                      seen)
        # the prose judge was shown the same
        (body,) = [b for b in _fake.bodies("prose_judge") if "s3: Caption" in b["messages"][1]["content"]]
        self.assertIn(lamp[:200], body["messages"][1]["content"])

    def test_the_notes_words_and_versions_only_in_blender_steps(self):
        """A Blender reply in the notes' words for the two Blenders is a teacher note (notes_leak); a code reply that
        names "5.0.1" or a sandbox is kept, since a code step's notes name neither."""
        glow = F.GLOW_OK.replace("\nimport bpy\n", "\nimport bpy  # safe in both Blenders, sandboxed\n", 1)
        with mock.patch.object(F, "GLOW_LEAK", glow):
            rec = self.run_seed(self.env(blender=StubBlender(plan_ok=True), names={}), self.seed(F.STUB_PLAN))
        s3 = rec["rounds"][0]["steps"][2]
        self.assertEqual([(x["reasons"], x.get("echoed")) for x in s3["candidates"][:4]],
                         [(["teacher_note"], "notes_leak")] * 4)
        self.assertEqual(s3["kept"], {"from": "second", "index": 4})
        count = F.COUNT.replace("    counts = {}\n", "    counts = {}  # like sphinx==5.0.1, run sandboxed\n", 1)
        self.assertNotEqual(count, F.COUNT)
        with mock.patch.object(F, "COUNT", count):  # another goal: the planner's reply to this one is cached
            rec = self.run_seed(self.env(), self.seed(F.SCRIPT_PLAN, goal="Count the words, quietly. " + MARK))
        s1 = rec["rounds"][0]["steps"][0]
        self.assertEqual((s1["kept"], s1["candidates"][0].get("echoed")), ({"from": "cand", "index": 0}, None))
        self.assertIn("sphinx==5.0.1", T.kept_target(s1)[0])

    def test_a_retry_may_say_what_its_request_says(self):
        """The size line quotes the step's own words, and the try after it repeats them: Chimera's words, not ours,
        so precheck's echo check, given the request, lets it through."""
        line = "it measures 8 m across; the step says: Make a 4 m floor plane chimera_floor and register it. " + MARK
        floor = F.FLOOR.replace("import bpy\n", "import bpy\n# Make a 4 m floor plane chimera_floor and register it\n",
                                1)
        with mock.patch.object(F, "FLOOR", floor):
            rec = self.run_seed(self.env(blender=StubBlender(plan_ok=True, tell={"s1": (2, [line])}), names={}),
                                self.seed(F.BLENDER_PLAN, goal="A lamp room, measured. " + MARK))
        s1 = rec["rounds"][0]["steps"][0]
        self.assertEqual([c["reasons"] for c in s1["candidates"]], [["size_mismatch"]] * 2 + [[], []])
        self.assertEqual(s1["kept"], {"from": "cand", "index": 2})
        told = H.teacher_lines("blender", [line])
        asked = "\n".join(m["content"] for m in s1["request"]["messages"])
        self.assertEqual(H.echoed_note(floor, told), "extra")  # without the request, the run counts as ours
        self.assertIsNone(H.echoed_note(floor, told, request=asked))
        self.assert_requests_are_chimeras(rec, names={})


# Plans of this file's own for the third round of checks (fixtures, with the mark): a step whose words name nothing
# to call, after a counting step; BOLD_PLAN with its page first, before any Python piece of the round; and a short
# trip plan of two sections for round 2.
GREET_PLAN = {"title": "Mock greeter", "kind": "code", "summary": "Count words and greet. " + MARK, "steps": [
    F.SCRIPT_PLAN["steps"][0],
    {"id": "s2", "title": "Greet", "kind": "code", "depends_on": [],
     "instructions": "Print a friendly greeting when the script runs. " + MARK}]}
PAGE_FIRST_PLAN = dict(F.BOLD_PLAN, title="Mock page first", steps=[
    dict(F.BOLD_PLAN["steps"][2], id="s1"), dict(F.BOLD_PLAN["steps"][0], id="s2"),
    dict(F.BOLD_PLAN["steps"][1], id="s3")])
GREET_TESTS = '# greeter process\nimport subprocess\nsubprocess.run(["true"])\nassert greet() == "greet"\n'


class ThirdCheckTests(Base):
    """What the third round of checks of the smoke's replies changed in a step's path (Nov 4): an empty retry for a
    step with nothing to call, the retry's outcome kept apart, the round's Python for no_python, the dropped steps
    and the given pieces for import_fault and tests_fault, nothing that ran, last round's part for the prose gate,
    and tell lines paired with their own candidate. Where a rule is another module's, a stand-in watches the call."""

    size = dict(Base.size, failed_dep=1.0, mixed_pool=1.0)

    def test_an_obedient_empty_retry_on_a_step_with_nothing_to_call(self):
        """Greet's first tests start a process; told why, the writer replies {"tests": ""}, as TESTS_SYSTEM asks when
        the step names nothing to call. That is no refusal: the step is "none:no_tests", kept, as if the first reply
        had been empty (Shout's words name shout(text), so its empty retry stays refused:
        test_tests_still_refused_after_the_retry)."""
        self.assertFalse(T.names_callable(T.step_words(GREET_PLAN, 1)))
        with mock.patch.dict(F.TESTS, {"Greet": GREET_TESTS}), mock.patch.dict(F.REWRITES, {"# greeter process": ""}):
            rec = self.run_seed(self.env(size={"failed_dep": 0.0, "mixed_pool": 0.0}), self.seed(GREET_PLAN))
        s2 = rec["rounds"][0]["steps"][1]
        t = s2["tests"]
        self.assertEqual(([x["why"] for x in t["refused"]], t["retry"], t["why"]),
                         (["subprocess"], {"why": "no_tests", "gave": "empty", "callable": False}, "no_tests"))
        self.assertEqual((s2["kept"], s2["tests_status"], s2["nothing_ran"]),
                         ({"from": "cand", "index": 0}, "none:no_tests", False))  # its import run ran
        self.assertEqual({m["sid"]: m["tests"] for _, m in T.examples(rec)}, {"s1": "valid", "s2": "none:no_tests"})
        self.assertEqual(len(_fake.bodies("tests_rewrite")), 1)  # the one retry
        # the retry's call is t's own: its key is in the record once (the report takes a repeated key's time off)
        keys = [x["key"] for x in t["refused"] if "key" in x] + [t["key"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assert_requests_are_chimeras(rec)

    def test_what_a_retry_gave_and_when_it_stays_refused(self):
        def reply(content, done="stop"):
            return L.Reply(content=content, done_reason=done)
        for content, done, gave in (('{"tests": ""}', "stop", "empty"), ('{"tests": "  \\n"}', "stop", "empty"),
                                    ("", "stop", "none"), ("I can't test this step. " + MARK, "stop", "none"),
                                    ('{"note": "nothing"}', "stop", "none"), ('{"tests": ""}', "runner_cut", "runaway"),
                                    (json.dumps({"tests": GREET_TESTS}), "stop", "refused")):
            r = reply(content, done)
            code, why = T._read_tests(r)
            self.assertEqual(T._retry_gave(r, code, why), gave, content)
        r = reply(json.dumps({"tests": 'assert greet() == "greet"\n'}))
        self.assertEqual(T._retry_gave(r, *T._read_tests(r)), "tests")
        first = [{"why": "name_guess", "key": "k1"}]
        for retry, refused in (({"gave": "empty", "callable": False}, False),
                               ({"gave": "empty", "callable": True}, True),
                               ({"gave": "none", "callable": False}, True),
                               ({"gave": "runaway", "callable": False}, True),
                               ({"gave": "refused", "callable": False}, True), (None, True)):
            t = {"code": None, "why": "no_tests", "refused": first, "retry": retry}
            self.assertEqual(T.refused_tests(t), refused, retry)
            self.assertEqual(T.tests_status({"tests": t}), "none:tests_refused" if refused else "none:no_tests")
        self.assertFalse(T.refused_tests({"code": "assert f()\n", "refused": first}))

    def test_the_rounds_python_and_nothing_that_ran(self):
        """BOLD_PLAN's page comes after two Python pieces (test_a_bold_file_line_...: asked for tests); first in
        the round it is "none:no_python", and nothing ran on it either way."""
        seen = []
        real = CG.no_python

        def watch(texts, mode, words="", python_project=False):
            seen.append((words.split("\n", 1)[0], python_project))
            return real(texts, mode, words=words, python_project=python_project)
        with mock.patch.object(CG, "no_python", side_effect=watch):
            rec = self.run_seed(self.env(size={"failed_dep": 0.0, "mixed_pool": 0.0}), self.seed(PAGE_FIRST_PLAN))
        page, parser, bold = rec["rounds"][0]["steps"]
        self.assertEqual(page["title"], "Page")
        self.assertEqual((page["tests"]["why"], page["tests_status"], page["nothing_ran"]),
                         ("no_python", "none:no_python", True))
        self.assertEqual(seen[0], ("Page", False))
        self.assertIn(("Bold", True), seen)  # Parser's piece before it writes tool/parse.py
        self.assertEqual((parser["tests_status"], bold["tests_status"]), ("valid", "valid"))
        self.assertEqual({m["sid"]: (m["tests"], m["nothing_ran"]) for _, m in T.examples(rec)},
                         {"s1": ("none:no_python", True), "s2": ("valid", False), "s3": ("valid", False)})
        rnd = T.Round(self.env(), self.seed(PAGE_FIRST_PLAN), 1, PAGE_FIRST_PLAN, {})
        steps = rec["rounds"][0]["steps"]
        rnd.kept = {s["id"]: T.kept_target(s)[0] for s in steps}  # no step records: the modes are the plan's
        self.assertEqual([rnd.python_project(s) for s in steps], [False, False, True])
        self.assertTrue(T.ran_nothing({"tests": None, "run": None}))
        self.assertFalse(T.ran_nothing({"tests": None, "run": {"exit": 0}}))
        self.assertFalse(T.ran_nothing({"tests": {"passed": True}, "run": None}))

    def test_import_fault_gets_the_dropped_steps_and_the_given_pieces(self):
        """Format is dropped, so Main's request lacks it: only Format's words may excuse a bare module name for
        Main's piece (dropped), and what Parser's and Totals' pieces write is the project's (written). Main's
        failed_dep variant left Totals out too, so Totals' words may excuse one as well, but its piece is still the
        round's (written); its mixed_pool variant was given today's Totals instead of the round's."""
        real, calls = CG.import_fault, []

        def watch(gate, plan, i, texts, dropped=(), written=()):
            calls.append((i, tuple(dropped), list(written)))
            return real(gate, plan, i, texts, dropped=dropped, written=written)
        with mock.patch.object(CG, "import_fault", side_effect=watch):
            rec = self.run_seed(self.env(), self.seed(F.FILES_PLAN, goal="A tally tool, watched. " + MARK))
        r1 = rec["rounds"][0]
        s1, s2, s3, s4 = r1["steps"]
        self.assertIsNone(s3["kept"])
        by = {(v["sid"], v["variant"]): v for v in r1["variants"]}
        one, two = T.kept_target(s1)[0], T.kept_target(s2)[0]
        today = by[("s4", "mixed_pool")]["today"]["content"]
        self.assertEqual([c for c in calls if c[0] == 3], [(3, ("s3",), [one, two]), (3, ("s2", "s3"), [one, two]),
                                                           (3, ("s3",), [one, today])])
        self.assertEqual({(v["sid"], v["variant"]): v["tests_status"] for v in r1["variants"] if v.get("kept")},
                         {("s4", "failed_dep"): "none:variant", ("s4", "mixed_pool"): "none:variant"})
        rnd = T.Round(self.env(), self.seed(F.FILES_PLAN, goal="A tally tool, watched. " + MARK), 1, F.FILES_PLAN,
                      {})  # no step records: the modes are the plan's (Go's stepMode)
        self.assertEqual([rnd.dropped_code(s) for s in r1["steps"]], [(), (), (), ("s3",)])
        self.assertEqual(rnd.dropped_code(by[("s4", "failed_dep")]), ("s2", "s3"))
        rnd.kept = {s["id"]: T.kept_target(s)[0] for s in r1["steps"] if s["kept"]}
        self.assertEqual(rnd.given(by[("s4", "failed_dep")]), [one, two])
        self.assertEqual(rnd.given(by[("s4", "mixed_pool")]), [one, today])
        self.assert_requests_are_chimeras(rec)

    def test_tests_fault_gets_the_dropped_steps(self):
        """The call sites of code_gate.tests_fault (the rewrite's skip and the untested piece's reading) pass the
        earlier code steps the request lacked: none in CHECKS_PLAN, whose steps all depend on nothing."""
        real, calls = CG.tests_fault, []

        def watch(record, plan, i, candidates=None, dropped=(), kept=None):
            calls.append((i, tuple(dropped), kept))
            return real(record, plan, i, candidates=candidates, dropped=dropped, kept=kept)
        with mock.patch.object(CG, "tests_fault", side_effect=watch):
            rec = self.run_seed(self.env(size={"failed_dep": 0.0, "mixed_pool": 0.0}),
                                self.seed(F.CHECKS_PLAN, goal="Count the text, watched. " + MARK))
        steps = rec["rounds"][0]["steps"]
        self.assertEqual({s["sid"]: s["tests_status"] for s in steps},
                         {"s1": "valid", "s2": "valid", "s3": "none:tests_unreachable", "s4": "none:third_party"})
        self.assertTrue(calls)
        self.assertEqual({i for i, _, _ in calls}, {1, 2, 3})
        self.assertTrue(all(d == () for _, d, _ in calls), calls)
        # the untested piece's reading gets the piece kept (the closure rule's own-file test); the rewrite's skip,
        # asked before anything is kept, none
        untested = [(i, k) for i, _, k in calls if k is not None]
        self.assertEqual(untested, [(2, T.kept_target(steps[2])[0]), (3, T.kept_target(steps[3])[0])])

    def test_the_prose_gate_gets_last_rounds_part(self):
        """In round 2 a section's request carries its own part of round 1's result (Go's findPart), or the result
        cut to 6,000 bytes when its part isn't there: that is what prose_gate.section_check is given as prev_result
        (what it excuses is prose_gate's to test). Round 1 gives none. Here Packing
        list, a generic section that repeats Weather facts, was dropped in round 1, so round 1's result has no part
        of its."""
        real, seen = prose_gate.section_check, []

        def watch(plan, i, text, verdict, earlier, **kw):
            seen.append((i, kw.get("prev_result")))
            return real(plan, i, text, verdict, earlier, **kw)
        goal = "Pack for Lisbon, twice. " + MARK
        with mock.patch.object(prose_gate, "section_check", side_effect=watch):
            rec = self.run_seed(self.env(size={"round2": 1.0, "failed_dep": 0.0, "mixed_pool": 0.0}),
                                self.seed(F.WRITE_PLAN, goal=goal))
        self.assertEqual(rec["round2"], "ran")
        r1, r2 = rec["rounds"]
        n1 = sum(1 for s in r1["steps"] for c in s["candidates"] if c.get("gate"))
        self.assertEqual([p for _, p in seen[:n1]], [""] * n1)
        later = seen[n1:]
        self.assertTrue(later)
        self.assertEqual({i for i, _ in later}, {0, 1})
        for i, part in later:
            st = r2["steps"][i]
            self.assertTrue(part)
            self.assertEqual(part, find_part(r1["result"], r2["plan"], i, "section")[0])
            self.assertIn("Last round's result for your part:\n" + part, st["request"]["messages"][1]["content"])
            if st["round2_matched"]:  # its own part, not the whole result
                self.assertTrue(part.startswith("## Weather facts\n"), part[:80])
                self.assertNotIn(F.WRITE_PLAN["title"], part)
            else:
                self.assertEqual(part, r1["result"])  # cut to 6,000 bytes, which this one is under
        self.assertEqual([s["round2_matched"] for s in r2["steps"]], [True, False])
        self.assert_requests_are_chimeras(rec)

    def test_a_tell_line_keeps_its_own_candidates_words(self):
        """A tell line that quotes the failed try's own handoff (five names, an 8-word run) no longer drops the next
        try that keeps that handoff and fixes the rest: the run is the model's (hints.Tell). Real: the Blender
        gate's provides_missing line on a step whose words name the objects otherwise."""
        names = "Floor, Back Wall, Left Wall, Right Wall, Ceiling Light"
        floor = F._blender("s1", F.FLOOR_CODE, names)
        line = (f"the handoff's provides names {names}, but the run made nothing by those names (no object, "
                "collection or ctx key) " + MARK)
        with mock.patch.object(F, "FLOOR", floor):
            rec = self.run_seed(self.env(blender=StubBlender(plan_ok=True, tell={"s1": (2, [line])}), names={}),
                                self.seed(F.BLENDER_PLAN, goal="A lamp room, walled. " + MARK))
        s1 = rec["rounds"][0]["steps"][0]
        self.assertEqual([c["reasons"] for c in s1["candidates"]], [["size_mismatch"]] * 2 + [[], []])
        self.assertEqual(s1["kept"], {"from": "cand", "index": 2})
        failures = T._failures(s1["candidates"][:2], "blender")
        self.assertEqual(failures, [line, line])
        self.assertIsInstance(failures[0], H.Tell)
        self.assertEqual(failures[0].own, floor)
        told = H.teacher_lines("blender", failures)
        self.assertEqual(H.echoed_note(floor, [str(x) for x in told]), "extra")  # unpaired, it would be ours
        self.assertIsNone(H.echoed_note(floor, told))
        self.assert_requests_are_chimeras(rec, names={})


class PlanCheckTests(Base):
    """task.py's plan-check logic with the stand-in Blender gate."""

    def test_the_culprits_alternate_is_swapped_in(self):
        _fake.vary.add("Shelf")
        stub = StubBlender(culprit="s2", fail_once=True)
        rec = self.run_seed(self.env(blender=stub), self.seed(F.SHELF_PLAN))
        r1 = rec["rounds"][0]
        s2 = r1["steps"][1]
        pc = r1["plan_check"]["blender"]
        self.assertTrue(pc["ok"])
        self.assertEqual(len(pc["tries"]), 1)
        self.assertEqual(pc["swapped"]["to"], s2["kept"]["index"])
        self.assertEqual(s2["kept"]["swapped_from"], {"from": "cand", "index": pc["swapped"]["from"]["index"]})
        self.assertNotEqual(stub.calls[0]["s2"], stub.calls[1]["s2"])
        self.assertEqual(stub.calls[1]["s2"], s2["candidates"][s2["kept"]["index"]]["content"])
        self.assertTrue(s2["candidates"][s2["kept"]["index"]]["judge"]["ok"])  # judged before it was tried
        self.assertFalse(any(s["plan_failed"] for s in r1["steps"]))

    def test_a_code_alternate_swapped_in_is_settled_again(self):
        """The kept piece's import run missed openpyxl and nothing else ran ("none:third_party"); the plan check
        fails on it and passes with an alternate whose import run ran clean. What settle_tests read was the old
        piece's: the swap asks it again, so the alternate isn't dropped as third_party (integrator, round 3)."""
        plan = {"title": "Sheets " + MARK, "summary": "x", "steps": [
            {"id": "s1", "title": "Export", "kind": "code", "depends_on": [],
             "instructions": "Write export.py with export(rows). " + MARK},
            {"id": "s2", "title": "Notes", "kind": "code", "depends_on": [],
             "instructions": "Write notes.py with note(text). " + MARK}]}
        rnd = T.Round(None, {"seed_id": "n-python-0009-00", "text": GOAL}, 1, plan, {})
        missed = {"ok": True, "tests": None, "run": {
            "error": "ModuleNotFoundError: No module named 'openpyxl'",
            "missing": {"module": "openpyxl", "project": False, "piece": True}}}
        texts = [f"File: export.py\n```python\nimport {m}  # {MARK}\n```\n" for m in ("openpyxl", "csv")]
        step = {"sid": "s1", "index": 0, "id": "s1", "mode": "files", "variant": None, "inputs": {"outputs": {}},
                "tests": {"code": None, "why": "no_tests", "valid": False}, "repairs": [], "alternates": [1],
                "candidates": [{"index": 0, "content": texts[0], "gate": missed, "passed": True},
                               {"index": 1, "content": texts[1], "gate": {"ok": True, "tests": None, "run": None},
                                "passed": True}],
                "kept": {"from": "cand", "index": 0}}
        rnd.steps.append(step)
        rnd.kept["s1"] = texts[0]
        rnd.settle_tests(step)
        self.assertEqual((step["import_fault"], step["nothing_ran"], step["tests_status"]),
                         ("third_party", False, "none:third_party"))

        class Gate:
            calls = []

            def plan_check(self, plan, kept, goal=""):
                self.calls.append(kept["s1"])
                return {"ok": "openpyxl" not in kept["s1"], "reasons": [], "culprit": "s1"}
        pc = {"ok": False, "tries": [], "swapped": None}
        rnd.try_alternates("code", Gate(), {"culprit": "s1"}, pc)
        self.assertEqual((pc["swapped"]["to"], step["kept"]["index"], Gate.calls), (1, 1, [texts[1]]))
        self.assertEqual((step.get("import_fault"), step["nothing_ran"], step["tests_status"]),
                         (None, True, "none:no_tests"))  # its own gate: nothing ran on it either

    def test_a_culprit_others_depend_on_marks_the_plan_failed(self):
        _fake.vary.add("Shelf")
        stub = StubBlender(culprit="s1", fail_once=False)
        rec = self.run_seed(self.env(blender=stub, size={"failed_dep": 1.0}), self.seed(F.SHELF_PLAN))
        r1 = rec["rounds"][0]
        self.assertEqual(len(stub.calls), 1)  # s2 depends on s1: no alternates are tried
        self.assertFalse(r1["plan_check"]["blender"]["ok"])
        self.assertTrue(all(s["plan_failed"] for s in r1["steps"]))
        self.assertTrue(all(v["plan_failed"] for v in r1["variants"]))
        v = r1["variants"][0]
        self.assertFalse(v["candidates"][0]["gate"]["joined_checked"])  # a variant: alone only
        # its first batch claims the floor of s1, which it was told failed; the next, told so, says s1 failed
        self.assertEqual(v["candidates"][0]["reasons"], ["dep_claimed:s1", "dep_unlisted"])
        self.assertTrue(v["candidates"][v["kept"]["index"]]["judge"]["ok"])  # and judged on that run's scene
        self.assertEqual(T.examples(rec), [])
        self.assertEqual(len(T.examples(rec, keep_plan_failed=True)), 3)


class RepairSheetTests(Base):
    """A Blender repair's names sheet is the one the crashed Blender prints, as in Chimera, whose sheet and check come
    from the same Blender (stand-in gate; the sheets are fixture text)."""

    SHEETS = {"5.2.2": "Fixture sheet of Blender 5.2.2. " + MARK, "5.0.1": "Fixture sheet of Blender 5.0.1. " + MARK}

    def seed_drawing(self, version):
        """A Blender seed whose Lamp step (s2) draws that sheet."""
        sid = next(s for s in (f"n-blender-{k:04d}-00" for k in range(500)) if T.names_for(s, "s2") == version)
        return self.seed(F.BLENDER_PLAN, goal=f"Make the lamp room ({version}). " + MARK, seed_id=sid)

    def lamp(self, names, drew):
        stub = StubBlender(crash_in=("5.0.1",), plan_ok=True)  # Lamp's crash shows only in 5.0.1, like AVIF
        rec = self.run_seed(self.env(blender=stub, names=names), self.seed_drawing(drew))
        s2 = rec["rounds"][0]["steps"][1]
        self.assertEqual((s2["title"], s2["kept"]), ("Lamp", {"from": "repair", "index": 0}))
        self.assertTrue(all(c["crash"]["runner"] == "Blender 5.0.1" for c in s2["candidates"]))
        self.assert_requests_are_chimeras(rec, names=names)
        return rec, s2, s2["repairs"][0], stub

    def test_the_repair_carries_the_crashed_blenders_sheet(self):
        rec, s2, rp, stub = self.lamp(self.SHEETS, "5.2.2")
        self.assertEqual((s2["names"], rp["inputs"]["names"]), ("5.2.2", "5.0.1"))
        system = rp["request"]["messages"][0]["content"]
        self.assertIn(self.SHEETS["5.0.1"], system)
        self.assertNotIn(self.SHEETS["5.2.2"], system)
        self.assertTrue(rp["example"])
        # The gate takes a crash from the request's own Blender first: the step's sheet, then the repair's.
        self.assertEqual([p for s, p in stub.prefers if s == "s2"], ["5.2.2"] * 4 + ["5.0.1"])
        self.assertEqual([(m["sid"], m["repaired"], m["names"]) for _, m in T.examples(rec) if m["sid"] == "s2"],
                         [("s2", True, "5.0.1")])  # the sheet its request carries, not the step's

    def test_without_that_sheet_the_repair_is_no_example(self):
        rec, s2, rp, _ = self.lamp({"5.2.2": self.SHEETS["5.2.2"]}, "5.2.2")
        self.assertEqual((rp["inputs"]["names"], rp["sendable"], rp["example"]), ("5.2.2", False, False))
        self.assertEqual([m["sid"] for _, m in T.examples(rec)], ["s1", "s3"])

    def test_a_step_that_drew_no_sheet_repairs_without_one(self):
        rec, s2, rp, _ = self.lamp(self.SHEETS, None)
        self.assertEqual((s2["names"], rp["inputs"]["names"], rp["example"]), (None, None, True))
        self.assertNotIn(T.NAMES_HEAD, rp["request"]["messages"][0]["content"])


# A plan of this file's own (fixtures, with the mark): Tokens never gives a piece the validator reads, Ranking depends
# on it and says it used s1's tokens (and assumed nothing), Headline depends on Ranking.
RANK_PLAN = {"title": "Mock word ranks", "kind": "code", "summary": "Count, rank and headline words. " + MARK,
             "steps": [{"id": "s1", "title": "Tokens", "kind": "code", "depends_on": [],
                        "instructions": "Write tokens(text), which returns the text's lower-cased words. " + MARK},
                       {"id": "s2", "title": "Ranking", "kind": "code", "depends_on": ["s1"],
                        "instructions": "Write ranking(text), which returns the words of tokens(text) from s1, most "
                                        "frequent first. " + MARK},
                       {"id": "s3", "title": "Headline", "kind": "code", "depends_on": ["s2"],
                        "instructions": "Write headline(text), which returns 'top: <word>' for the first word of "
                                        "ranking(text) from s2. " + MARK}]}
TOKENS_NONE = "I would rather not write this one. " + MARK
RANKING = F._script('''
def ranking(text):
    """The words of tokens(text), most frequent first."""
    words = tokens(text)
    return sorted(set(words), key=lambda w: (-words.count(w), w))
''', "ranking(text) -> list of str", "tokens from s1")
HEADLINE = F._script('''
def headline(text):
    """'top: <word>' for ranking(text)'s first word."""
    return "top: " + ranking(text)[0]
''', "headline(text) -> str", "ranking from s2")


class SoftKeepTests(Base):
    """After the second smoke run's audit (Nov 4): dep_honesty as a stage after every mode's gate, and the soft keep
    (task.SOFT_REASONS): a step none of whose tries passed, but one failed only on faults that leave its piece usable,
    feeds the later steps and the join as a pass does and gives no example; a variant never does. Also the stage
    ranks, the newest failure lines in a repair's notes, the rewrite's errors, and the code gate's project."""
    size = dict(Base.size, failed_dep=1.0, mixed_pool=1.0)

    def replies(self, table):
        """The stand-in Ollama's worker replies for the step titles in table, the canned ones for the rest."""
        real = F._worker_reply

        def reply(model, system, user):
            m = re.search(r"^Your step, s\d+: (.+)$", user, re.M)
            title = m.group(1).strip() if m else ""
            return table[title] if title in table else real(model, system, user)
        p = mock.patch.object(F, "_worker_reply", side_effect=reply)
        p.start()
        self.addCleanup(p.stop)

    def test_a_piece_that_claims_a_failed_step_feeds_the_next_and_gives_no_example(self):
        self.replies({"Tokens": TOKENS_NONE, "Ranking": RANKING, "Headline": HEADLINE})
        rec = self.run_seed(self.env(), self.seed(RANK_PLAN, goal="Rank my words, please. " + MARK))
        r1 = rec["rounds"][0]
        s1, s2, s3 = r1["steps"]
        self.assertEqual({s["mode"] for s in r1["steps"]}, {"python-script"})
        self.assertIsNone(s1["kept"])
        # Ranking: every try (gpt-oss's 3, qwen3.8's 2) passed the code gate, then dep_honesty failed it, before any
        # judge; its tell line went to the next batch's notes, never into the stored request
        self.assertEqual([c["model"] for c in s2["candidates"]], ["gpt-oss:120b"] * 3 + ["qwen3.8:27b"] * 2)
        both = ["dep_claimed:s1", "dep_unlisted"]
        for c in s2["candidates"]:
            self.assertEqual((c["stage"], c["reasons"], c["mech"], c["gate"]["ok"]), (T.DEP_STAGE, both, False, True))
            self.assertEqual(c["gate"]["dep_honesty"]["missing"], ["s1"])
            self.assertEqual([x[:9] for x in c["gate"]["tell"]], ["s1 failed"] * 2)
        told = [b["messages"][0]["content"] for b in _fake.bodies("worker")
                if "Your step, s2: Ranking" in b["messages"][1]["content"] and
                H.FAILED_ON in b["messages"][0]["content"]]
        self.assertEqual(len(told), 3)  # gpt-oss's second batch and qwen3.8's two
        line = H.failure_lines([s2["candidates"][0]["gate"]["tell"][0]])[0]
        self.assertTrue(all("- " + line in t for t in told))
        self.assertNotIn(H.FAILED_ON, json.dumps(s2["request"]))
        # kept for the later steps as a pass is, but no example
        self.assertEqual((s2["kept"], s2["no_example"], s2["drop"], s2["alternates"]),
                         ({"from": "cand", "index": 0}, both, None, []))
        with open(os.path.join(self.dir, "progress.log"), encoding="utf-8") as f:
            self.assertIn("s2 python-script: kept from cand (5 samples, 0 repairs, no example: dep_claimed:s1, "
                          "dep_unlisted)", f.read())
        # Headline's request carries Ranking's piece, as it would a pass's, and Headline is kept as usual
        piece = T.kept_target(s2)[0]
        self.assertEqual((s3["missing_deps"], s3["inputs"]["outputs"]), ([], {"s2": piece}))
        user = s3["request"]["messages"][1]["content"]
        self.assertIn("def ranking(text):", user)
        self.assertNotIn("(that step failed;", user)
        self.assertEqual(s3["kept"], {"from": "cand", "index": 0})
        self.assertNotIn("s2", r1["join"]["failed"])  # the round joins it
        # no variants of a soft keep; Headline's failed_dep variant, Ranking left out, claims it and is dropped:
        # a variant never soft-keeps
        by = {(v["sid"], v["variant"]): v for v in r1["variants"]}
        self.assertFalse([k for k in by if k[0] == "s2"])
        fd = by[("s3", "failed_dep")]
        self.assertEqual((fd["left_out"], fd["kept"], fd["drop"], fd.get("no_example")),
                         ("s2", None, ["dep_claimed:s2", "dep_unlisted"], None))
        # the examples: Headline's (and its mixed_pool variant's), none of Ranking's
        ex = T.examples(rec)
        self.assertIn(("s3", None), [(m["sid"], m["variant"]) for _, m in ex])
        self.assertNotIn("s2", [m["sid"] for _, m in ex])
        self.assertNotIn("s2", [m["sid"] for _, m in T.examples(rec, keep_plan_failed=True)])
        self.assert_requests_are_chimeras(rec)

    def test_a_blender_piece_that_hands_over_no_output_is_kept_once_judged(self):
        """The Blender gate's soft reasons (output_missing, camera_not_active: blender_gate's names, standing in
        here) keep the step's piece for the later steps once the scene judge accepts it, as a pass would be; the next
        step's request has it. A judge that turns its tries down (the first SOFT_JUDGED, furthest first) leaves the
        step dropped, as before soft keeps."""
        class Stub(StubBlender):
            def piece_check(self, plan, i, text, verdict, earlier, goal="", **kw):
                out = super().piece_check(plan, i, text, verdict, earlier, goal, **kw)
                if i == 0:
                    out.update(ok=False, reasons=["output_missing", "camera_not_active"],
                               tell=["the step asks to render, but SETTINGS_s1 has no \"output\" " + MARK])
                return out
        rec = self.run_seed(self.env(blender=Stub(plan_ok=True), names={}),
                            self.seed(F.BLENDER_PLAN, goal="A lamp room, rendered. " + MARK))
        s1, s2, s3 = rec["rounds"][0]["steps"]
        self.assertEqual([c["stage"] for c in s1["candidates"]], ["gate:alone"] * 6)  # 4 of gpt-oss's, 2 of qwen3.8's
        self.assertEqual([c["judge"] is not None for c in s1["candidates"]], [True] + [False] * 5)  # one call
        self.assertEqual((s1["kept"], s1["no_example"]), ({"from": "cand", "index": 0},
                                                          ["camera_not_active", "output_missing"]))
        self.assertEqual(s1["candidates"][0]["reasons"], ["output_missing", "camera_not_active"])  # judged, kept
        self.assertEqual(s2["missing_deps"], [])
        self.assertEqual(s2["inputs"]["outputs"], {"s1": T.kept_target(s1)[0]})
        self.assertTrue(s2["kept"] and not s2.get("no_example"))
        judged = [b for b in _fake.bodies("scene_judge") if "The step under review, s1:" in b["messages"][1]["content"]]
        self.assertEqual(len(judged), 1)
        made = [(m["sid"], m["variant"]) for _, m in T.examples(rec)]
        self.assertEqual(sorted(k for k in made if k[1] is None), [("s2", None), ("s3", None)])
        self.assertFalse([k for k in made if k[0] == "s1"])
        self.assertFalse([v for v in rec["rounds"][0]["variants"] if v["sid"] == "s1"])  # a soft keep gets none
        self.assert_requests_are_chimeras(rec, names={})
        # turned down by the judge: two tries asked, then dropped, and Lamp is written with Floor failed (another plan
        # title: the scene judge's messages hold no goal since Nov 5, so the same plan's verdicts would be the cache's)
        _fake.scene_reject.add("Floor")
        self.addCleanup(_fake.scene_reject.discard, "Floor")
        rec = self.run_seed(self.env(blender=Stub(plan_ok=True), names={}),
                            self.seed(dict(F.BLENDER_PLAN, title="Mock lamp room, rejected"),
                                      goal="A lamp room, rendered and rejected. " + MARK))
        s1, s2, _ = rec["rounds"][0]["steps"]
        self.assertEqual([c["judge"] is not None for c in s1["candidates"]], [True, True] + [False] * 4)
        self.assertEqual((s1["kept"], s1.get("no_example")), (None, None))
        self.assertIn("judge", s1["drop"])
        self.assertEqual(s2["missing_deps"], ["s1"])

    def test_a_scene_rejection_resting_on_a_size_or_a_place_alone_is_overruled(self):
        """The fourth smoke's audit (Nov 5): the scene judge's rejections that rest only on a size, a position or an
        output form the step names (judges.overruled) are overruled, since the gate measured the step's own sizes
        and places first: the step keeps its first try, which gives its example, and the record says why
        (judge["rule"] "overruled", "overruled"). A rejection that says something else is missing stands, and since
        Nov 6 (decided) so does a size or position claim the gate's readers read no value for: the mock plan's "4 m
        floor plane" is one side, and a claim that names no thing needs every object of the try's listing (the gate's
        "scene", here chimera_s2) read."""
        _fake.scene_why["Floor"] = "the floor's size is wrong (length 3.0 m instead of required 4 m)"
        _fake.scene_why["Lamp"] = "the pendant is placed at the origin instead of its specified position"
        measured = copy.deepcopy(F.BLENDER_PLAN)
        measured["title"] = "Mock lamp room, measured"
        measured["steps"][0]["instructions"] = ("Make a floor slab chimera_floor of 4 m x 4 m x 0.1 m and register it "
                                                "as ctx['objects']['floor'].")
        measured["steps"][1]["instructions"] = ("Hang a pendant chimera_pendant at (0, 0, 2.5) over s1's floor and "
                                                "register it as ctx['objects']['lamp'].")
        rec = self.run_seed(self.env(blender=StubBlender(plan_ok=True), names={}),
                            self.seed(measured, goal="A lamp room, its sizes judged. " + MARK))
        s1, s2, _ = rec["rounds"][0]["steps"]
        for st, kinds in ((s1, ["size"]), (s2, ["position"])):
            c = st["candidates"][st["kept"]["index"]]
            self.assertEqual(st["kept"], {"from": "cand", "index": c["index"]})
            self.assertFalse(c["judge"]["verdict"]["ok"])  # the judge's own verdict is kept as it was
            self.assertEqual((c["judge"]["ok"], c["judge"]["rule"], c["judge"]["overruled"]), (True, "overruled",
                                                                                               kinds))
            self.assertNotIn("judge", c["reasons"])
            self.assertTrue(c["passed"])
            self.assertEqual(len(st["candidates"]), 2)  # its first batch: nothing redrawn
        self.assertEqual(s2["missing_deps"], [])
        made = [(m["sid"], m["variant"]) for _, m in T.examples(rec)]
        self.assertIn(("s1", None), made)
        self.assertIn(("s2", None), made)
        # the same claims where the readers read nothing: the mock plan's one-sided floor, and a lamp placed "2.5 m
        # above" the floor with a claim that names no thing on a listing of chimera_s2
        _fake.scene_why["Lamp"] = "Objects were created but all placed at the origin instead of the specified " \
                                  "coordinates"
        rec = self.run_seed(self.env(blender=StubBlender(plan_ok=True), names={}),
                            self.seed(dict(F.BLENDER_PLAN, title="Mock lamp room, unmeasured"),
                                      goal="A lamp room, its sizes unmeasured. " + MARK))
        s1 = rec["rounds"][0]["steps"][0]
        self.assertIsNone(s1["kept"])
        self.assertIn("judge", s1["drop"])
        self.assertFalse([c for c in s1["candidates"] if (c.get("judge") or {}).get("rule") == "overruled"])
        # a rejection that also says something is missing stands
        _fake.scene_why["Floor"] = "the floor is 3.0 m instead of 4 m and its border is missing"
        rec = self.run_seed(self.env(blender=StubBlender(plan_ok=True), names={}),
                            self.seed(dict(F.BLENDER_PLAN, title="Mock lamp room, a border missing"),
                                      goal="A lamp room, its border missing. " + MARK))
        s1 = rec["rounds"][0]["steps"][0]
        self.assertIsNone(s1["kept"])
        self.assertIn("judge", s1["drop"])
        self.assertFalse([c for c in s1["candidates"] if (c.get("judge") or {}).get("rule") == "overruled"])

    def test_a_soft_failed_try_is_held_to_its_failed_dependency_too(self):
        """A Blender try that fails only softly may be kept as a dependency, so dep_honesty runs on it as on a pass
        (the integration check found it never did): its claims join its reasons (still soft, its stage the gate's,
        not DEP_STAGE), its tell line goes to the next batch with the output line, and of the soft tries the soft keep
        takes, at the same stage, one with the fewest kinds of fault: an honest one."""
        class Stub(StubBlender):
            def piece_check(self, plan, i, text, verdict, earlier, goal="", **kw):
                out = super().piece_check(plan, i, text, verdict, earlier, goal, **kw)
                if i == 0:
                    out.update(ok=False, reasons=["alone_strict:5.2.2", "alone_strict:5.0.1"])
                elif i == 1:
                    out.update(ok=False, reasons=["output_missing"],
                               tell=["the step asks Chimera for a render, but SETTINGS_s2 has no \"output\" " + MARK])
                return out
        rec = self.run_seed(self.env(blender=Stub(plan_ok=True), names={}),
                            self.seed(F.BLENDER_PLAN, goal="A lamp room, its floor failing. " + MARK))
        s1, s2, _ = rec["rounds"][0]["steps"]
        self.assertIsNone(s1["kept"])
        self.assertEqual(s2["missing_deps"], ["s1"])
        first = s2["candidates"][0]  # gpt-oss's first batch, not told yet: claims Floor's piece
        self.assertEqual(first["model"], "gpt-oss:120b")
        self.assertEqual(first["stage"], "gate:alone")
        self.assertIn("output_missing", first["reasons"])
        self.assertIn("dep_claimed:s1", first["reasons"])
        self.assertTrue(T.soft(first["reasons"]))
        self.assertEqual(first["gate"]["dep_honesty"]["missing"], ["s1"])
        self.assertEqual([x[:9] for x in first["gate"]["tell"]], ["the step ", "s1 failed"] +
                         ["s1 failed"] * (len(first["gate"]["tell"]) - 2))
        honest = [c for c in s2["candidates"] if c["reasons"] == ["output_missing"]]
        self.assertTrue(honest)  # told, or qwen3.8's
        self.assertEqual(s2["no_example"], ["output_missing"])
        self.assertEqual(s2["kept"], {"from": "cand", "index": honest[0]["index"]})
        self.assertFalse([c for c in s2["candidates"] if c["stage"] == T.DEP_STAGE])

    def test_the_check_gets_chimeras_own_request_in_every_mode(self):
        """dep_honesty runs on every try a mode's gate passed (Blender, a section, files, a python-script repair), on
        the request Chimera sends for it (a repair's own), never the teacher's copy."""
        real, seen = T.DH.check, []

        def watch(messages, text, lenient=False):
            seen.append((json.dumps(messages, ensure_ascii=False), text))
            return real(messages, text, lenient)
        with mock.patch.object(T.DH, "check", side_effect=watch):
            recs = [self.run_seed(self.env(blender=StubBlender(plan_ok=True), names={}, size={"mixed_pool": 0.0}),
                                  self.seed(F.BLENDER_PLAN, goal="A lamp room, honest. " + MARK)),
                    self.run_seed(self.env(size={"mixed_pool": 0.0}),
                                  self.seed(F.SCRIPT_PLAN, goal="Count my words, honest. " + MARK))]
        stored, passed = {}, []
        for rec in recs:
            for rnd in rec["rounds"]:
                for st in rnd["steps"] + rnd["variants"]:
                    for c in st["candidates"] + st["repairs"]:
                        req = (c.get("request") or st["request"])["messages"]
                        stored[c["content"]] = stored.get(c["content"], set()) | {json.dumps(req, ensure_ascii=False)}
                        if (c.get("gate") or {}).get("ok"):
                            passed.append((st["mode"], "turn" in c))
        self.assertEqual({m for m, _ in passed}, {"blender", "section", "python-script"})
        self.assertIn(("python-script", True), passed)  # Report's repair
        self.assertEqual(len(seen), len(passed))
        for msgs, text in seen:
            self.assertNotIn(H.HEAD, msgs)
            self.assertIn(msgs, stored[text])
        self.assertTrue(any(F.REPAIR in msgs for msgs, _ in seen))

    def test_a_repairs_own_crash_is_its_newest_failure_line(self):
        rec = self.run_seed(self.env(size={"failed_dep": 0.0, "mixed_pool": 0.0}),
                            self.seed(F.SCRIPT_PLAN, goal="Count my words, repaired. " + MARK))
        s2 = rec["rounds"][0]["steps"][1]
        rp = s2["repairs"][0]
        (body,) = [b for b in _fake.bodies("worker") if F.REPAIR in b["messages"][1]["content"]]
        notes = body["messages"][0]["content"].split(H.FAILED_ON + "\n", 1)[1].split("\n")
        listed = [x for x in notes if x.startswith("- ")]
        self.assertEqual(listed[-1], "- " + H.failure_lines([rp["inputs"]["crash"]])[0])
        self.assertEqual(len(listed), len(set(listed)))

    def test_a_rewrite_that_fails_every_candidate_keeps_its_errors(self):
        """Lines' tests import a module no step makes; their one rewrite asserts the wrong count, so it fails every
        candidate. What it said of each stays in the tests record (rewrite_errors, for the report), and the piece
        is kept without tests that reached it (tests_unreachable)."""
        wrong = 'assert count_lines("a\\nb") == 3, "two lines are three"\n'
        with mock.patch.dict(F.REWRITES, {"# guessed module": wrong}):
            rec = self.run_seed(self.env(size={"failed_dep": 0.0, "mixed_pool": 0.0}),
                                self.seed(F.CHECKS_PLAN, goal="Count the lines, rewritten. " + MARK))
        s3 = rec["rounds"][0]["steps"][2]
        t = s3["tests"]
        self.assertEqual((t["rewrite"]["valid"], t["rewrite"]["why"]), (False, "no_candidate_passed"))
        self.assertEqual([(e["from"], e["index"]) for e in t["rewrite_errors"]],
                         [("cand", 0), ("cand", 1), ("cand", 2), ("second", 3), ("second", 4)])
        self.assertTrue(all(e["error"].startswith("AssertionError: two lines are three") for e in t["rewrite_errors"]))
        self.assertEqual((s3["kept"], t["fault"], s3["tests_status"]),
                         ({"from": "cand", "index": 0}, "tests_unreachable", "none:tests_unreachable"))
        self.assertNotIn("rewrite_errors", rec["rounds"][0]["steps"][3]["tests"])  # Docs' rewrite: skipped

    def test_the_layout_stage_gets_the_pieces_the_request_was_built_from(self):
        """A files try's code gate gets project: its request's outputs, a variant's own inputs too, though it is
        otherwise checked alone (earlier {}); other modes get None."""
        real, seen = CodeGate.piece_check, []

        def watch(gate, plan, i, text, verdict, earlier, mode, tests=None, **kw):
            seen.append((i, mode, dict(earlier), kw.get("project")))
            return real(gate, plan, i, text, verdict, earlier, mode, tests=tests, **kw)
        with mock.patch.object(CodeGate, "piece_check", autospec=True, side_effect=watch):
            rec = self.run_seed(self.env(size={"mixed_pool": 0.0}),
                                self.seed(F.FILES_PLAN, goal="A tally tool, laid out. " + MARK))
        r1 = rec["rounds"][0]
        allowed = {}
        for st in r1["steps"] + r1["variants"]:
            allowed.setdefault(st["index"], []).append(st["inputs"]["outputs"])
        for i, mode, earlier, project in seen:
            self.assertEqual(mode, "files")
            self.assertIn(project, allowed[i])
            if earlier:  # a step's own: the kept pieces before it, which its request was built from
                self.assertEqual(project, r1["steps"][i]["inputs"]["outputs"])
        tried = [v for v in r1["variants"] if v["candidates"]]
        self.assertTrue(tried)
        for v in tried:  # checked alone, read against its own inputs
            self.assertIn((v["index"], "files", {}, v["inputs"]["outputs"]), seen)
        (fd,) = [v for v in r1["variants"] if v["sid"] == "s4"]
        self.assertTrue(fd["inputs"]["outputs"] and "s2" not in fd["inputs"]["outputs"])


REPORT_NOTED = F._script('''
# how many words the report shows
TOP = 10


def report(counts, top=TOPN):
    """Lines "word: n", most frequent first."""
    # most frequent first, then by the word
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    return ["%s: %d" % kv for kv in items]  # one line per word
''', "report(counts) -> list of str", "count_words from s1")  # a NameError on import, as REPORT_CRASH
REPORT_REWORDED = F._script('''
# the report's length: its top words only
TOP = 10


def report(counts, top=TOP):
    """The report's lines, "word: n" each:
    the most frequent word first, ties by the word."""
    # sort by count, highest first, then alphabetically
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    return ["%s: %d" % kv for kv in items]  # a "word: n" line for each
''', "report(counts) -> list of str", "count_words from s1")  # its one fix, every comment and the docstring reworded
FLOOR_LAMP = dict(F.BLENDER_PLAN, steps=F.BLENDER_PLAN["steps"][:2])  # Lamp depends on Floor; nothing on Lamp


class FaultStub(StubBlender):
    """StubBlender whose piece_check fails a step's tries on given reasons, standing in for blender_gate's (format 4:
    ctx_channel, step 6's): faults {index: reasons} for every check of that step, alone {index: reasons} only for its
    checks alone (a variant's)."""

    def __init__(self, faults=None, alone=None, **kw):
        super().__init__(**kw)
        self.faults, self.alone = dict(faults or {}), dict(alone or {})

    def piece_check(self, plan, i, text, verdict, earlier, goal="", **kw):
        out = super().piece_check(plan, i, text, verdict, earlier, goal, **kw)
        reasons = self.faults.get(i) or (None if kw.get("joined", True) else self.alone.get(i))
        if reasons:
            out.update(ok=False, reasons=list(reasons))
        return out


class FormatFourTests(Base):
    """After the third smoke run (format 4), task.py's side: ctx_channel is soft only on a step some later step
    depends on (SOFT_IF_USED, Round.used), step 6's faults are soft with or without one, and a repair's share counts
    its code lines (code_lines). blender_gate's reasons are FaultStub's here."""

    def test_a_repair_that_rewords_its_comments_is_still_an_example(self):
        """Report's repair fixes its one line and rewords every comment and its docstring around it: 6 of its 10
        lines changed, an example no more on every line, but 1 of its 4 code lines."""
        real = F._worker_reply

        def reply(model, system, user):
            if "Your step, s2: Report" in user:
                return REPORT_REWORDED if F.REPAIR in user else REPORT_NOTED
            return real(model, system, user)
        with mock.patch.object(F, "_worker_reply", side_effect=reply):
            rec = self.run_seed(self.env(), self.seed(F.SCRIPT_PLAN, goal="Count my words, with notes. " + MARK))
        s2 = rec["rounds"][0]["steps"][1]
        self.assertTrue(all(c["crash"] and "NameError" in c["crash"]["error"] for c in s2["candidates"]))
        rp = s2["repairs"][0]
        self.assertEqual((s2["kept"], rp["passed"], rp["lines_changed"], rp["share"]),
                         ({"from": "repair", "index": 0}, True, 1, 0.25))
        self.assertTrue(rp["example"])
        before, after = T.piece_code(REPORT_NOTED), T.piece_code(REPORT_REWORDED)
        self.assertEqual((lines_changed(before, after), len(before.split("\n"))), (6, 10))  # 0.6 on every line
        self.assertEqual([(m["sid"], m["repaired"]) for _, m in T.examples(rec)], [("s1", False), ("s2", True)])

    def test_ctx_channel_is_soft_only_on_a_step_others_depend_on(self):
        """Every try of Floor and of Lamp hands its values on through a ctx key Chimera hasn't (ctx_channel): Floor,
        which Lamp depends on, is kept for it with no example, as an output_missing try is; Lamp, which nothing
        depends on, is dropped."""
        rec = self.run_seed(self.env(blender=FaultStub({0: ["ctx_channel"], 1: ["ctx_channel"]}, plan_ok=True),
                                     names={}),
                            self.seed(FLOOR_LAMP, goal="A floor and its lamp, through their own ctx keys. " + MARK))
        s1, s2 = rec["rounds"][0]["steps"]
        self.assertEqual([(c["stage"], c["reasons"]) for c in s1["candidates"]], [("gate:alone", ["ctx_channel"])] * 6)
        self.assertEqual((s1["kept"], s1["no_example"], s1["drop"]), ({"from": "cand", "index": 0}, ["ctx_channel"],
                                                                      None))
        self.assertEqual((s2["missing_deps"], s2["inputs"]["outputs"]), ([], {"s1": T.kept_target(s1)[0]}))
        self.assertEqual(len(s2["candidates"]), 6)
        self.assertEqual((s2["kept"], s2.get("no_example"), s2["drop"]), (None, None, ["ctx_channel"]))
        self.assertEqual(T.examples(rec), [])
        self.assert_requests_are_chimeras(rec, names={})

    def test_what_the_build_drops_is_soft_only_on_a_step_others_depend_on(self):
        """After the fourth smoke: blender_gate.build_facts' reasons (a dead output key, Chimera's validator warnings,
        the stand-in marker's faults) fail every try of Floor and of Lamp: Floor, which Lamp depends on, is kept for it
        with no example, as ctx_channel's is; Lamp, which nothing depends on, is dropped."""
        for reasons in (["dead_output_key"], ["validator_warning:provides_missing", "marker_misused"],
                        ["silent_default"], ["ctx_channel", "validator_warning:handoff_long"]):
            rec = self.run_seed(self.env(blender=FaultStub({0: reasons, 1: reasons}, plan_ok=True), names={}),
                                self.seed(FLOOR_LAMP, goal="A floor and its lamp, %s. %s" % (reasons[0], MARK)))
            s1, s2 = rec["rounds"][0]["steps"]
            self.assertEqual([c["stage"] for c in s1["candidates"]], ["gate:alone"] * 6, reasons)
            self.assertEqual((s1["kept"], s1["no_example"], s1["drop"]), ({"from": "cand", "index": 0},
                                                                          sorted(reasons), None))
            self.assertEqual((s2["kept"], s2.get("no_example"), s2["drop"]), (None, None, reasons))
            self.assertEqual(T.examples(rec), [])

    def test_step_sixs_faults_are_soft_with_or_without_a_dependent(self):
        """Lamp's every try hides an error behind its own except (swallowed): it is kept, as a soft keep, though
        nothing depends on it."""
        for reasons in (["swallowed"], ["place_mismatch", "skipped_input"], ["nested"]):
            rec = self.run_seed(self.env(blender=FaultStub({1: reasons}, plan_ok=True), names={}),
                                self.seed(FLOOR_LAMP, goal="A floor and its lamp, %s. %s" % (reasons[0], MARK)))
            s1, s2 = rec["rounds"][0]["steps"]
            self.assertEqual((s1["kept"], s1.get("no_example")), ({"from": "cand", "index": 0}, None))
            self.assertEqual((s2["kept"], s2["no_example"]), ({"from": "cand", "index": 0}, sorted(reasons)))
            self.assertEqual([m["sid"] for _, m in T.examples(rec)], ["s1"])

    def test_a_variant_never_takes_ctx_channel_softly(self):
        """Lamp passes, and its failed_dep variant (Floor left out), checked alone, fails on ctx_channel: not soft
        for a variant, though Caption depends on Lamp, so dep_honesty doesn't run on it and it is dropped on that
        alone; failed on swallowed, which is soft for any try, it is held to its failed dependency too (dep_claimed),
        and dropped all the same."""
        size = {"failed_dep": 1.0}
        for reason in ("ctx_channel", "swallowed"):
            rec = self.run_seed(self.env(blender=FaultStub(alone={1: [reason]}, plan_ok=True), names={}, size=size),
                                self.seed(F.BLENDER_PLAN, goal="A lamp room, varied, %s. %s" % (reason, MARK)))
            r1 = rec["rounds"][0]
            self.assertEqual((r1["steps"][1]["kept"], r1["steps"][1].get("no_example")),
                             ({"from": "cand", "index": 0}, None))  # checked joined: no fault
            (v,) = [v for v in r1["variants"] if v["sid"] == "s2"]
            self.assertEqual((v["variant"], v["left_out"], v["kept"], v.get("no_example"), v["repairs"]),
                             ("failed_dep", "s1", None, None, []))
            first = v["candidates"][0]  # gpt-oss's first, not told yet: claims Floor's piece
            self.assertEqual(first["reasons"][0], reason)
            if reason == "ctx_channel":
                self.assertEqual((first["reasons"], v["drop"]), (["ctx_channel"], ["ctx_channel"]))
                self.assertNotIn("dep_honesty", first["gate"])
            else:
                self.assertIn("dep_claimed:s1", first["reasons"])
                self.assertEqual(first["gate"]["dep_honesty"]["missing"], ["s1"])
                self.assertEqual(first["stage"], "gate:alone")
                self.assertIn("swallowed", v["drop"])


class AuditPureTests(unittest.TestCase):
    """The new stages' places in a candidate's progress, the soft reasons and what the records give, with no
    binary."""

    def test_how_far_a_candidate_got(self):
        code = {st: T._progress({"stage": "gate:" + st}) for st in T._CODE_STAGES}
        self.assertEqual(sorted(code, key=code.get), ["join", "compile", "symbols", "layout_import", "run", "done"])
        dep = T._progress({"stage": T.DEP_STAGE})
        self.assertGreater(dep, max(code.values()))
        self.assertGreater(dep, T._progress({"stage": "gate:done"}))  # a Blender candidate's, past the whole gate
        self.assertLess(dep, T._progress({"stage": "judge", "passed": False}))
        for reasons in (["output_missing"], ["camera_not_active"], ["camera_not_active", "output_not_asked"]):
            self.assertEqual(T._blender_stage(reasons), "alone", reasons)
        self.assertEqual(T._blender_stage(["output_missing", "lint:attr"]), "lint")  # the worst one counts
        # format 4: ctx_channel and step 6's alone checks at the alone run, nested at the joined one
        for reason in ("ctx_channel", "swallowed", "skipped_input", "place_mismatch", "flat_extrusion",
                       "doubled_depth"):
            self.assertEqual(T._blender_stage([reason]), "alone", reason)
        self.assertEqual(T._blender_stage(["nested"]), "joined")
        self.assertEqual(T._blender_stage(["nested", "swallowed"]), "alone")
        self.assertEqual(T._blender_stage(["ctx_channel", "lint:socket"]), "lint")

    def test_the_soft_reasons(self):
        self.assertEqual(T.SOFT_REASONS, {"dep_claimed", "dep_unlisted", "output_missing", "camera_not_active",
                                          "swallowed", "skipped_input", "place_mismatch", "flat_extrusion", "nested",
                                          "doubled_depth"})
        # attr_miss since Nov 5 (the test below), and since the fourth smoke also blender_gate.build_facts' reasons
        # (FACT_REASONS), the same way
        self.assertEqual(T.SOFT_IF_USED, {"ctx_channel", "attr_miss", "validator_warning", "dead_output_key",
                                          "marker_misused", "silent_default"})
        for reasons in (["dep_claimed:s1"], ["dep_claimed:s1", "dep_claimed:s3", "dep_unlisted"],
                        ["output_missing", "camera_not_active"], ["swallowed"], ["skipped_input"],
                        ["place_mismatch"], ["flat_extrusion"], ["nested"], ["swallowed", "output_missing"],
                        ["doubled_depth"], ["doubled_depth", "output_missing"]):
            self.assertTrue(T.soft(reasons), reasons)
            self.assertTrue(T.soft(reasons, used=True), reasons)  # soft with or without a dependent
        for reasons in ([], ["judge"], ["dep_claimed:s1", "judge"], ["output_not_asked"], ["tests_failed"],
                        ["layout_import"], ["ctx_channel"], ["ctx_channel", "output_missing"]):
            self.assertFalse(T.soft(reasons), reasons)
        # ctx_channel only on a step a later step depends on, and only with other soft faults
        self.assertTrue(T.soft(["ctx_channel"], used=True))
        self.assertTrue(T.soft(["ctx_channel", "output_missing"], True))
        self.assertTrue(T.soft(["ctx_channel", "nested", "dep_unlisted"], True))
        for reasons in ([], ["ctx_channel", "lint:socket"], ["ctx_channel", "judge"], ["ctx_channel", "stand_in"]):
            self.assertFalse(T.soft(reasons, True), reasons)

    def test_attr_miss_is_soft_only_on_a_step_others_depend_on(self):
        """After the fourth smoke (Nov 5): blender_gate's attr_miss (a guard on the way to the keys found nothing and
        they stayed unlike the linear ones the step asks for) is soft as ctx_channel is, at the alone stage: the piece
        still builds what its dependents use, so it is kept for them with no example; on a step nothing depends on it
        drops the piece."""
        self.assertIn("attr_miss", T.SOFT_IF_USED)
        self.assertNotIn("attr_miss", T.SOFT_REASONS)
        self.assertEqual(T._blender_stage(["attr_miss"]), "alone")
        self.assertEqual(T._blender_stage(["attr_miss", "joined_dupes"]), "alone")
        self.assertFalse(T.soft(["attr_miss"]))
        self.assertTrue(T.soft(["attr_miss"], used=True))
        self.assertTrue(T.soft(["swallowed", "attr_miss"], used=True))
        self.assertTrue(T.soft(["attr_miss", "dep_claimed:s1"], used=True))  # smoke4 blender-0008-00 s4 c5's pair
        self.assertFalse(T.soft(["swallowed", "attr_miss"]))
        for reasons in (["attr_miss", "lint:attr"], ["attr_miss", "joined_dupes"], ["attr_miss", "judge"]):
            self.assertFalse(T.soft(reasons, True), reasons)

    def test_a_step_is_used_when_a_later_step_depends_on_it(self):
        r = T.Round(None, {"seed_id": "n-blender-0009-00", "text": "A lamp room. " + MARK}, 1, F.BLENDER_PLAN,
                    "hydra:1.0")
        self.assertEqual([r.used({"index": i, "variant": None}) for i in range(3)], [True, True, False])
        for kind in ("failed_dep", "mixed_pool"):  # a variant feeds no step, whoever depends on its step
            self.assertFalse(r.used({"index": 0, "variant": kind}))
        lone = dict(F.BLENDER_PLAN, steps=[dict(s, depends_on=[]) for s in F.BLENDER_PLAN["steps"]])
        r = T.Round(None, {"seed_id": "n-blender-0009-01", "text": "Three lone steps. " + MARK}, 1, lone, "hydra:1.0")
        self.assertEqual([r.used({"index": i}) for i in range(3)], [False, False, False])

    def test_a_soft_keep_gives_no_example(self):
        def step(sid, **kw):
            return dict({"sid": sid, "index": int(sid[1:]) - 1, "kind": "code", "mode": "python-script",
                         "variant": None, "names": None, "lone": False, "missing_deps": [],
                         "request": {"messages": [{"role": "user", "content": sid + " " + MARK}]}, "request_tokens": 9,
                         "candidates": [{"content": sid + " piece " + MARK, "model": "gpt-oss:120b"}], "repairs": [],
                         "kept": {"from": "cand", "index": 0}, "tests_status": "none:no_tests"}, **kw)
        rec = {"status": "done", "seed": {"seed_id": "n-python-0009-00", "category": "python", "source": "new"},
               "rounds": [{"round": 1, "steps": [step("s1"), step("s2", no_example=["dep_claimed:s1"])],
                           "variants": []}]}
        for keep in (False, True):
            self.assertEqual([m["sid"] for _, m in T.examples(rec, keep_plan_failed=keep)], ["s1"])

    def test_a_dependency_tell_is_the_only_line_for_its_reasons(self):
        tell = "s1 failed and gave your piece nothing, yet your uses line lists \"rows\" " + MARK
        c = {"content": "## Packing\n\ntext " + MARK, "reasons": ["dep_claimed:s1", "dep_unlisted"],
             "gate": {"tell": [tell]}, "verdict": None}
        self.assertEqual(T._section_failures(c), [])
        self.assertEqual(T._failures([c], "section"), [tell])
        self.assertEqual(T._failures([dict(c, crash=None, gate={"tell": [tell], "lint": []})], "python-script"),
                         [tell])


class RepairShareTests(unittest.TestCase):
    """Format 4: a repair's share is counted on its code lines (task.code_lines: no comments, docstrings or blank
    lines; indents count), both sides read the same way (task.repair_lines); runner.score.lines_changed is the eval's
    and unchanged."""

    def changed(self, before, after):
        b, a = T.repair_lines(before, after)
        return lines_changed("\n".join(b), "\n".join(a))

    def test_what_a_code_line_is(self):
        code = (MARK + "\n"
                "import bpy\n"
                "\n"
                "\n"
                "def build(ctx):\n"
                '    """Make the lamp.\n'
                "\n"
                '    Two lines of docstring."""\n'
                "    # a comment line\n"
                '    name = "chimera_#lamp"  # a trailing comment\n'
                "    'a bare string, as a docstring is'\n"
                '    text = """not a docstring:\n'
                "# kept, it is the string's\n"
                '"""\n'
                "    return name   \n")
        self.assertEqual(T.code_lines(code), ["import bpy", "def build(ctx):", '    name = "chimera_#lamp"',
                                              '    text = """not a docstring:', "# kept, it is the string's", '"""',
                                              "    return name"])
        self.assertEqual((T.code_lines(""), T.code_lines(None), T.code_lines(MARK + "\n\n# only notes\n")),
                         ([], [], []))

    def test_comments_docstrings_and_blank_lines_dont_count(self):
        base = (MARK + "\n"
                "def lamp(power):\n"
                '    """The lamp."""\n'
                "    # make the light\n"
                '    light = make("chimera_lamp", type="POINTY")  # the light\n'
                "    # and set its power\n"
                "    light.energy = power\n"
                "    return light\n")
        reworded = (MARK + "\n"
                    "def lamp(power):\n"
                    '    """A point lamp, its power set:\n'
                    '    the scene\'s only light."""\n'
                    "    # create the point light the step asks for\n"
                    '    light = make("chimera_lamp", type="POINT")  # a point light\n'
                    "\n"
                    "    # its power in watts\n"
                    "    light.energy = power\n"
                    "    return light\n")
        self.assertEqual(self.changed(base, reworded), 1)  # one code line fixed, the comments around it reworded
        self.assertGreater(lines_changed(base, reworded), 3)  # every line: the rewording counted, as until format 4
        trailing = base.replace("# the light", "# was POINTY, now fixed")
        self.assertEqual(self.changed(base, trailing), 0)
        doc = base.replace('"""The lamp."""', '"""Builds the lamp.\n\n    Its power comes from the settings."""')
        self.assertEqual(self.changed(base, doc), 0)
        self.assertEqual(self.changed(base, base.replace("    return light", "\n\n    return light")), 0)
        reindented = base.replace("    light.energy = power\n", "    if power:\n        light.energy = power\n")
        self.assertEqual(self.changed(base, reindented), 2)  # the new if and the line it re-indents
        self.assertEqual(self.changed(reindented, reindented.replace("    return light", "        return light")), 1)

    def test_code_that_doesnt_parse_loses_only_its_blank_and_comment_lines(self):
        broken = 'def lamp(:\n    """The lamp."""\n    # a note\n\n    return make("x")  # the light   \n'
        self.assertEqual(T.code_lines(broken),
                         ["def lamp(:", '    """The lamp."""', '    return make("x")  # the light'])
        self.assertEqual(T.code_lines('x = = 1  # tokenizes, doesn\'t parse\n# a note\n'),
                         ["x = = 1  # tokenizes, doesn't parse"])
        self.assertEqual(T.code_lines('s = """never closed\n# inside\n'), ['s = """never closed'])  # TokenError
        # a fix that makes it parse is read the same way on both sides: its one line, not its comments and docstring
        fixed = broken.replace("def lamp(:", "def lamp():")
        self.assertEqual(self.changed(broken, fixed), 1)
        self.assertEqual(lines_changed("\n".join(T.code_lines(broken)), "\n".join(T.code_lines(fixed))), 3)
        self.assertEqual(T.repair_lines(fixed, fixed), (T.code_lines(fixed), T.code_lines(fixed)))
        self.assertEqual(T.repair_lines(broken, fixed)[1], ["def lamp():", '    """The lamp."""',
                                                            '    return make("x")  # the light'])


    def test_the_shrink(self):
        # repair_measures: (lines_changed, share, shrink) on code lines; shrink is net, below 0 when a repair grows
        base = MARK + "\na = 1\nb = 2\nc = 3\nd = 4\n"
        self.assertEqual(T.repair_measures(base, base.replace("d = 4", "d = 5")), (1, 0.25, 0.0))
        self.assertEqual(T.repair_measures(base, base.replace("c = 3\n", "")), (1, 0.25, 0.25))
        self.assertEqual(T.repair_measures(base, base + "e = 5\nf = 6\n"), (2, 0.5, -0.5))
        self.assertEqual(T.repair_measures(MARK + "\n# only a note\n", base), (None, None, None))
        # comments and docstrings a repair drops aren't left-out code
        noted = base.replace("a = 1", '"""The values."""\n# the first\na = 1')
        self.assertEqual(T.repair_measures(noted, base), (0, 0.0, 0.0))


class HandoffFenceTests(Base):
    """precheck makes the handoff block's fence plain (normalise.handoff_fence) in every code mode, but not for a lone
    step, which the contract gives no handoff."""

    def test_an_untagged_handoff_fence_passes_precheck_and_the_raw_reply_stays(self):
        rnd = T.Round(self.env(blender=StubBlender(plan_ok=True), names={}), self.seed(F.SHELF_PLAN), 1,
                      F.SHELF_PLAN, {})
        step = rnd.step_record(1, {"s1": F.FLOOR})
        self.assertFalse(step["lone"])
        raw = F.SHELF_OK.replace("```handoff\n", "```\nhandoff\n")
        c = {"content": raw, "runaway": False, "done_reason": "stop", "reasons": [], "stage": "reply",
             "verdict": None, "gate": None, "judge": None, "crash": None, "mech": False, "passed": False, "index": 0}
        self.assertTrue(rnd.precheck(step, c, step["request"]), c["reasons"])
        self.assertEqual(c["normalised"], {"file_lines": 0, "marker_dashes": 0, "handoff_fence": 1})
        self.assertEqual(c["content"], F.SHELF_OK)
        self.assertEqual(c["verdict"]["handoff"]["provides"], 'chimera_shelf as ctx["objects"]["shelf"]')
        # before the fix the same reply failed precheck on handoff_missing
        bare = dict(c, content=raw, reasons=[], verdict=None, normalised=None)
        with mock.patch.object(T.N, "handoff_fence", lambda text: (text, 0)):
            self.assertFalse(rnd.precheck(step, bare, step["request"]))
        self.assertEqual(bare["reasons"], ["validator:handoff_missing"])

    def test_every_code_mode_and_not_a_lone_step(self):
        tail = "\n```\nhandoff\nprovides: x.py\nuses: none\nassumed: none\n```\n"
        for mode in ("blender", "python-script", "files"):
            c = {"content": "File: x.py\n```python\n" + MARK + "\nX = 1\n```\n" + tail}
            T.normalised(mode, c)
            self.assertEqual(c["normalised"]["handoff_fence"], 1, mode)
            self.assertTrue(c["content"].endswith("\n```handoff\nprovides: x.py\nuses: none\nassumed: none\n```\n"))
            lone = {"content": "File: x.py\n```python\n" + MARK + "\nX = 1\n```\n" + tail}
            T.normalised(mode, lone, lone=True)
            self.assertNotIn("normalised", lone, mode)
        section = {"content": "## Notes\n\nSome words. " + MARK + "\n" + tail}
        T.normalised("section", section)
        self.assertNotIn("normalised", section)  # sections never wrote it; their mode isn't touched


class SequenceStub(StubBlender):
    """StubBlender whose checks of one step fail in order: fault(k) gives the k-th check of that step's gate dict
    update (reasons, and crash, lint and tell when it has them), or None to let it pass as StubBlender would."""

    def __init__(self, sid, fault):
        super().__init__(plan_ok=True)
        self.sid, self.fault, self.k = sid, fault, 0

    def piece_check(self, plan, i, text, verdict, earlier, goal="", *, run_on_lint=True, joined=True, prefer=None):
        out = super().piece_check(plan, i, text, verdict, earlier, goal, run_on_lint=run_on_lint, joined=joined,
                                  prefer=prefer)
        if f"s{i + 1}" != self.sid:
            return out
        f = self.fault(self.k)
        self.k += 1
        if f:
            out.update(ok=False, reasons=list(f["reasons"]), crash=f.get("crash"), lint=list(f.get("lint") or []),
                       tell=list(f.get("tell") or []))
        return out


TELL_A = "Blender renamed chimera_shelf.001: a name was made twice. " + MARK
TELL_B = "it measures 3 m across where its step asks for 1 m. " + MARK
DUPES = {"reasons": ["dupes"], "tell": [TELL_A]}
SIZES = {"reasons": ["size_mismatch"], "tell": [TELL_B]}
FCURVES_LINT = {"level": "error", "kind": "attr", "line": 12, "name": "fcurves",
                "message": "Action has no attribute 'fcurves' in Blender 5.2.2 or 5.0.1"}
FCURVES = {"reasons": ["lint:attr", "alone_strict:5.2.2", "alone_strict:5.0.1"], "lint": [FCURVES_LINT],
           "crash": {"step": "s2", "part": "build", "function": "build_s2", "piece_line": 12, "line": 12,
                     "source": "for fc in shelf.animation_data.action.fcurves:",
                     "error": "AttributeError: 'Action' object has no attribute 'fcurves'", "runner": "Blender 5.2.2"}}


class SamplerBudgetTests(Base):
    """The second sampler's budget after the fourth smoke (Nov 5): one all of whose samples failed only on Blender
    API names isn't sent to qwen3.8 at all; the same fault twice still goes to qwen3.8. The third told batch for a
    Blender step whose second batch heard its notes (its faults are all new) was retired after the fifth smoke (Nov
    6: 6 calls there, no gate pass): heard is still recorded, and qwen3.8 comes right after the second batch."""

    def shelf_calls(self, model):
        return [b for b in _fake.bodies("worker") if b["model"] == model and
                "Your step, s2: Shelf\n" in b["messages"][1]["content"]]

    def test_a_batch_that_heard_its_notes_gets_no_third_batch(self):
        """Was test_a_batch_that_heard_its_notes_gets_one_more_told_batch: the same tries, and since Nov 6 no third
        gpt-oss batch, so the step is kept from qwen3.8, told both batches' failures."""
        stub = SequenceStub("s2", lambda k: DUPES if k < 2 else SIZES if k < 4 else None)
        rec = self.run_seed(self.env(blender=stub, names={}), self.seed(F.SHELF_PLAN))
        s2 = rec["rounds"][0]["steps"][1]
        self.assertEqual([c["reasons"] for c in s2["candidates"]], [["dupes"]] * 2 + [["size_mismatch"]] * 2 + [[], []])
        self.assertEqual(s2["kept"], {"from": "second", "index": 4})
        self.assertEqual(s2["sampler"], {"heard": True, "third": 0, "second": "asked"})
        self.assertEqual(len(self.shelf_calls("gpt-oss:120b")), 4)
        second = [b["messages"][0]["content"] for b in self.shelf_calls("qwen3.8:27b")]
        self.assertEqual(len(second), 2)
        self.assertTrue(all(H.FAILED_ON in m and TELL_A in m and TELL_B in m for m in second))  # both batches told
        self.assertEqual([(c["model"][:4], c["sample"]) for c in s2["candidates"]],
                         [("gpt-", k) for k in range(4)] + [("qwen", 0), ("qwen", 1)])
        self.assertIn("s2", [m["sid"] for _, m in T.examples(rec)])
        self.assert_requests_are_chimeras(rec, names={})
        self.assertFalse(hasattr(T, "THIRD_BATCH"))

    def test_when_qwen_fails_after_a_heard_batch_the_step_is_dropped(self):
        """Was test_when_the_third_batch_fails_qwen_still_comes: no third batch, so qwen3.8's two tries come after the
        fourth gpt-oss one, and with every try failed the step is dropped."""
        stub = SequenceStub("s2", lambda k: DUPES if k < 2 else SIZES if k < 6 else None)
        rec = self.run_seed(self.env(blender=stub, names={}), self.seed(F.SHELF_PLAN))
        s2 = rec["rounds"][0]["steps"][1]
        self.assertEqual(s2["sampler"], {"heard": True, "third": 0, "second": "asked"})
        self.assertIsNone(s2["kept"])
        self.assertEqual(s2["drop"], ["dupes"])  # the first of the tries that got as far (every one stopped alone)
        self.assertEqual([(c["model"][:4], c["sample"]) for c in s2["candidates"]],
                         [("gpt-", k) for k in range(4)] + [("qwen", 0), ("qwen", 1)])

    def test_the_same_fault_again_goes_to_qwen_without_a_third_batch(self):
        stub = SequenceStub("s2", lambda k: DUPES if k < 4 else None)
        rec = self.run_seed(self.env(blender=stub, names={}), self.seed(F.SHELF_PLAN))
        s2 = rec["rounds"][0]["steps"][1]
        self.assertEqual(s2["sampler"], {"heard": False, "third": 0, "second": "asked"})
        self.assertEqual(s2["kept"], {"from": "second", "index": 4})
        self.assertEqual(len(self.shelf_calls("gpt-oss:120b")), 4)
        self.assertEqual(len(self.shelf_calls("qwen3.8:27b")), 2)
        # a Blender step's qwen3.8 has the room for its thinking (test_the_second_samplers_reply_limit)
        self.assertTrue(all(b["options"]["num_predict"] == T.SECOND_OPTIONS["num_predict"] == 12288
                            for b in self.shelf_calls("qwen3.8:27b")))

    def test_api_faults_only_skip_qwen(self):
        stub = SequenceStub("s2", lambda k: FCURVES)
        rec = self.run_seed(self.env(blender=stub, names={}), self.seed(F.SHELF_PLAN))
        s2 = rec["rounds"][0]["steps"][1]
        self.assertEqual(s2["sampler"], {"heard": False, "third": 0, "second": "skipped", "why": "api_faults",
                                         "api": ["fcurves"]})
        self.assertEqual(self.shelf_calls("qwen3.8:27b"), [])
        self.assertEqual(len(s2["candidates"]), 4)
        self.assertEqual(len(s2["repairs"]), 2)  # the repairs still come (they crash on it too)
        self.assertIsNone(s2["kept"])
        self.assertEqual(s2["drop"], FCURVES["reasons"])

    def test_one_sample_with_another_fault_keeps_qwen(self):
        stub = SequenceStub("s2", lambda k: DUPES if k == 3 else FCURVES)
        rec = self.run_seed(self.env(blender=stub, names={}), self.seed(F.SHELF_PLAN))
        s2 = rec["rounds"][0]["steps"][1]
        self.assertEqual(s2["sampler"]["second"], "asked")
        self.assertEqual(len(self.shelf_calls("qwen3.8:27b")), 2)

    def test_what_counts_as_an_api_fault(self):
        def c(reasons, error=None, lint=()):
            return {"reasons": reasons, "crash": {"error": error} if error else None, "gate": {"lint": list(lint)}}
        strict = ["alone_strict:5.2.2", "alone_strict:5.0.1"]
        # the stored smoke runs' forms: a type's attribute, a collection's, a module's, a bmesh operator, an enum
        # value (set, or a call's keyword), a collection key
        for error, name in (("AttributeError: 'Action' object has no attribute 'fcurves'", "fcurves"),
                            ('AttributeError: bpy_prop_collection: attribute "active" not found', "active"),
                            ("AttributeError: module 'bpy' has no attribute 'mathutils'", "mathutils"),
                            ('AttributeError: BMeshOpsModule: operator "create_cylinder" doesn\'t exist',
                             "create_cylinder"),
                            ('TypeError: bpy_struct: item.attr = val: enum "FFMPEG" not found in (\'PNG\')', "FFMPEG"),
                            ('TypeError: BlendDataCurves.new(): error with keyword argument "type" -  enum "POLY" not '
                             "found in ('CURVE')", "POLY"),
                            ('KeyError: \'bpy_prop_collection[key]: key "Transmission" not found\'', "Transmission")):
            self.assertTrue(T.api_fault(c(strict, error)), error)
            self.assertEqual(T.api_names(c(strict, error)), {name})
        # a wrong value, the script's own names, a read-only attribute, None: not the API's
        for error in ("ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 3 items, not 4",
                      "NameError: name 'bmesh' is not defined",
                      "AttributeError: 'NoneType' object has no attribute 'x'",
                      'AttributeError: bpy_struct: attribute "animation_data" from "Object" is read-only',
                      "RuntimeError: Error: Object 'chimera_sofa_standin' already in collection 'Scene Collection'"):
            self.assertFalse(T.api_fault(c(strict, error)), error)
        self.assertTrue(T.api_fault(c(["lint:attr"], lint=[FCURVES_LINT])))  # a lint error alone counts
        syntax = dict(FCURVES_LINT, kind="syntax", name="")
        self.assertFalse(T.api_fault(c(["lint:syntax"], lint=[syntax])))
        # an API crash with another reason, or an API lint with a crash of the script's own, is not API-only
        self.assertFalse(T.api_fault(c(["lint:attr", "dupes"], lint=[FCURVES_LINT])))
        self.assertFalse(T.api_fault(c(["lint:attr"] + strict, "NameError: name 'x' is not defined", [FCURVES_LINT])))
        self.assertFalse(T.api_fault(c(["validator:handoff_missing"])))
        self.assertFalse(T.api_only([]))

    def test_what_heard_reads(self):
        def c(reasons, error=None, lint=(), tell=(), echoed=None):
            return {"reasons": reasons, "crash": {"error": error} if error else None, "echoed": echoed,
                    "gate": {"lint": list(lint), "tell": list(tell)}}
        strict = ["alone_strict:5.2.2", "alone_strict:5.0.1"]
        fc = c(["lint:attr"] + strict, "AttributeError: 'Action' object has no attribute 'fcurves'", [FCURVES_LINT])
        crash_only = c(strict, "AttributeError: 'Action' object has no attribute 'fcurves'")
        self.assertEqual(T.fault_keys(fc), {"api:fcurves"})
        self.assertEqual(T.fault_keys(crash_only), {"api:fcurves"})  # the lint missed it: the same fault
        handoff = c(["validator:handoff_missing,saves_or_renders"])
        self.assertEqual(T.fault_keys(handoff), {"validator:handoff_missing", "validator:saves_or_renders"})
        geometry = c(strict, tell=["run alone, it failed: chimera_x has no geometry."])
        self.assertEqual(T.fault_keys(geometry), {"run:run alone, it failed: chimera_x has no geometry."})
        self.assertEqual(T.fault_keys(c(["teacher_note"], echoed="version_leak")), {"teacher_note:version_leak"})
        self.assertTrue(T.heard([fc, fc], [handoff, geometry]))  # all new
        self.assertFalse(T.heard([fc, handoff], [crash_only, geometry]))  # fcurves came back
        self.assertFalse(T.heard([fc], []))
        self.assertFalse(T.heard([], [fc]))

    def test_a_told_build_fact_that_came_back_is_a_fault_in_common(self):
        """The independent checks (Nov 6): build_facts' reasons and ctx_channel are told to the next batch whatever
        else fails (tell_lines), but join the try's reasons only once lint and the alone run pass. A fact that came
        back on a try that crashed is the same fault, so the batches share it and no third batch is drawn (smoke4's
        blender-0008-00 r1 s1 on marker_misused, r1 s5 on dead_output_key and silent_default)."""
        strict = ["alone_strict:5.2.2", "alone_strict:5.0.1"]
        marker = {"reasons": ["marker_misused"], "crash": None,
                  "gate": {"lint": [], "facts": {"reasons": ["marker_misused"]}}}
        crashed = {"reasons": strict, "crash": {"error": "NameError: name 'q' is not defined"},
                   "gate": {"lint": [], "facts": {"reasons": ["marker_misused"]}}}
        self.assertEqual(T.fault_keys(crashed), {"marker_misused", "run:NameError: name 'q' is not defined"})
        self.assertFalse(T.heard([marker, marker], [crashed, crashed]))
        ctx = {"reasons": ["lint:attr"], "crash": None, "gate": {"lint": [FCURVES_LINT], "ctx_channel": {"written": [
            "variables"], "read": []}}}
        self.assertEqual(T.fault_keys(ctx), {"api:fcurves", "ctx_channel"})
        later = {"reasons": strict, "crash": {"error": "ValueError: bad"}, "gate": {"ctx_channel": {"written": [
            "variables"], "read": []}}}
        self.assertFalse(T.heard([ctx], [later]))
        quiet = {"reasons": strict, "crash": {"error": "ValueError: bad"}, "gate": {}}
        self.assertTrue(T.heard([ctx], [quiet]))

    def test_a_batch_stopped_short_of_the_earlier_is_not_heard(self):
        """Decided Nov 6: a later batch counts as heard only when it got at least as far as the earlier one (its best
        try's _progress at least the earlier's best), besides sharing no fault. smoke4's n-blender-0000-01 r1 s4 (its
        tries' shape): the first batch got past the alone run to the joined one (progress 12) and lint (11), the second
        stopped at the validator on too_long (2), so its faults are all new but it heard nothing: no third batch."""
        first = {"reasons": ["validator_warning:handoff_long", "dead_output_key", "silent_default",
                             "joined_strict:5.2.2", "joined_strict:5.0.1"], "crash": None, "stage": "gate:alone",
                 "gate": {"lint": []}}
        lint = {"reasons": ["lint:attr", "alone_strict:5.2.2", "alone_strict:5.0.1"], "crash": None,
                "stage": "gate:lint", "gate": {"lint": [dict(FCURVES_LINT, name="from_mesh")]}}
        too_long = {"reasons": ["validator:too_long"], "crash": None, "stage": "validator"}
        self.assertEqual((T._progress(first), T._progress(lint), T._progress(too_long)), (12, 11, 2))
        self.assertTrue(T.fault_keys(first).isdisjoint(T.fault_keys(too_long)))
        self.assertFalse(T.heard([first, lint], [too_long, too_long]))  # stopped short: no third batch
        self.assertTrue(T.heard([lint, too_long], [first]))  # further, and all new
        self.assertTrue(T.heard([first], [dict(first, reasons=["marker_misused"])]))  # as far, all new
        joined = dict(first, reasons=["nested"], stage="gate:joined")
        self.assertEqual(T._progress(joined), 15)
        self.assertTrue(T.heard([first, lint], [too_long, joined]))  # the best try counts
        self.assertFalse(T.heard([first], [dict(first, reasons=["dead_output_key"])]))  # a fault in common, as before


@unittest.skipUnless(HAVE_BLENDER, "needs Blender " + " and ".join(blenders.VERSIONS))
class BlenderTests(Base):
    def test_the_second_sampler_in_real_blender(self):
        rec = self.run_seed(self.env(blender="real"), self.seed(F.SHELF_PLAN, seed_id="n-blender-0004-00"))
        r1 = rec["rounds"][0]
        s1, s2 = r1["steps"]
        self.assertEqual((s1["mode"], s1["kept"]), ("blender", {"from": "cand", "index": 0}))
        self.assertEqual(s1["names"], T.names_for("n-blender-0004-00", "s1"))
        self.assertTrue(s1["candidates"][0]["judge"]["ok"])
        self.assertEqual([(c["model"][:4], c["sample"]) for c in s2["candidates"]],  # 2 + 2, then the second sampler
                         [("gpt-", 0), ("gpt-", 1), ("gpt-", 2), ("gpt-", 3), ("qwen", 0), ("qwen", 1)])
        self.assertTrue(all(c["crash"] and c["crash"]["function"] == "build_s2" for c in s2["candidates"][:4]))
        self.assertEqual([r["passed"] for r in s2["repairs"]], [False, False])
        self.assertEqual(s2["kept"], {"from": "second", "index": 4})
        self.assertTrue(r1["plan_check"]["blender"]["ok"])
        sheet = _names.get(s1["names"]) if s1["names"] else None
        if sheet:
            self.assertIn(sheet, s1["request"]["messages"][0]["content"])
        self.assert_requests_are_chimeras(rec)

    def test_a_render_never_handed_over_is_kept_as_a_dependency_in_real_blender(self):
        """The real Blender gate and task.py together: Floor's step asks for a render its piece never hands to Chimera
        (output_missing, a soft reason), on every try; the gate still joins it (cleanly), the scene judge accepts it,
        and it is kept for Shelf, whose request carries it, with no example of its own."""
        plan = dict(F.SHELF_PLAN, steps=[dict(F.SHELF_PLAN["steps"][0], instructions=(
            "Make a square floor plane chimera_floor, register it as ctx['objects']['floor'] and render the image to "
            "//floor.png. " + MARK)), F.SHELF_PLAN["steps"][1]])
        rec = self.run_seed(self.env(blender="real", size={"failed_dep": 0.0, "mixed_pool": 0.0}),
                            self.seed(plan, goal="A floor and a shelf, rendered. " + MARK, seed_id="n-blender-0005-00"))
        s1, s2 = rec["rounds"][0]["steps"]
        self.assertTrue(all(c["reasons"] == ["output_missing"] for c in s1["candidates"]), s1["drop"])
        c = s1["candidates"][0]
        self.assertTrue(c["gate"]["joined"] and all(x["strict"] for x in c["gate"]["joined"].values()))
        self.assertTrue(c["judge"]["ok"])
        self.assertEqual((s1["kept"], s1["no_example"]), ({"from": "cand", "index": 0}, ["output_missing"]))
        self.assertEqual(s2["inputs"]["outputs"]["s1"], T.kept_target(s1)[0])
        self.assertEqual(s2["missing_deps"], [])
        self.assertNotIn("s1", [m["sid"] for _, m in T.examples(rec)])
        self.assert_requests_are_chimeras(rec)


if __name__ == "__main__":
    unittest.main()
