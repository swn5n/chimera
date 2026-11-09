"""datagen/report.py on hand-made records (fixtures, with the mark; tests/test_datagen_build.py's own helpers): errored
seeds apart, code steps by their tests, what the changes after the first smoke did, the tests retries' outcomes apart
from the refusals, models the run never called and those a restart left loaded, a kind with no examples, a call a seed
makes twice; and since the second smoke's audit: model time from the calls the records use only (each once, an
earlier run's calls in a seeded cache said apart, the cache's other calls left out), the new gates' firings and what
became of their steps, steps kept only as a dependency (no_example) in the steps table and out of the tests table and
the projection's keep rate, tests that couldn't reach the code, the tests rewrites' errors, and the build's new drops
from sft/stats.json; and since the third smoke (format 4): ctx_channel by whether a later step depends on the step,
soft keeps by reason, the values-only steps and their pieces' ctx["values"], provides_missing warnings that are a
reader's own stand-ins, plain values in ctx["objects"], step 6's facts, the geometry readers' held-out counts, and
repairs whose share crosses REPAIR_SHARE on code lines; after the fourth smoke, blender_gate.build_facts' reasons by
the same split and handoff_long on a values-only step's provides line, the failed-dependency cap as a night's build
would apply it in the projection, and a line per sampler. The report itself is run end to end in
tests/test_datagen_build.py and, on the values run, in tests/test_datagen_run.py.
"""
import datetime
import os
import shutil
import tempfile
import unittest

from tests import _paths  # noqa: F401
from tests import datagen_fakes as F
from tests.test_datagen_build import piece, read, record, step
from datagen import common as C
from datagen import report as RP
from tools import blender_check

MARK = F.MARK
_tmp = None


def setUpModule():
    global _tmp
    _tmp = tempfile.mkdtemp(prefix="test-datagen-report-", dir=blender_check.scratch_root())


def tearDownModule():
    if _tmp:
        shutil.rmtree(_tmp, ignore_errors=True)


def iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()


class ReportTests(unittest.TestCase):
    """report.py on hand-made records (fixtures): errored seeds apart, code steps by their tests, foreign models."""

    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="report-", dir=_tmp)
        self.addCleanup(shutil.rmtree, self.data, True)

    def test_errored_seeds_tests_and_foreign_models(self):
        code = [step(f"s{k}", mode="python-script", kind="code", content=piece(f"s{k}", k)) for k in (1, 2, 3)]
        for st, status in zip(code, ("valid", "unconfirmed", "valid")):
            st["tests_status"], st["seconds"] = status, {"teacher": 10.0}
        code[2]["kept"], code[2]["drop"] = None, ["import_crash: ModuleNotFoundError " + MARK]
        done = record("n-python-0001-00", code)
        # an errored seed: the step it was on when the call failed has no kept piece and no drop
        broken = step("s1", mode="python-script", kind="code")
        broken.update(kept=None, drop=None, seconds={"teacher": 500.0})
        errored = dict(record("n-python-0002-00", [broken]), status="error", error="CallFailed: " + MARK)
        # a seed whose plan repeated the eval (task.eval_plan): no plan
        evalled = {"key": "n-python-0003-00", "status": "no_plan", "seed": {"seed_id": "n-python-0003-00"},
                   "rounds": [{"round": 1, "plan": None, "planner": {
                       "model": "hydra:1.0", "drew": "hydra:1.0", "reason": "eval_plan", "eval_hits": ["w2-27"],
                       "tries": [{"model": "hydra:1.0", "ok": True}]}}]}
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [done, errored, evalled])
        C.write_jsonl(os.path.join(self.data, "gate.jsonl"), [
            {"t": "2026-11-03T01:00:00", "event": "foreign", "models": ["qwen3-coder-next:latest"]},
            {"t": "2026-11-03T01:05:00", "event": "foreign", "models": ["deepseek-r1:70b", "qwen3-coder-next:latest"]},
            {"t": "2026-11-03T01:06:00", "event": "switch", "why": "idle", "from": "a", "to": "b"}])
        rep = RP.report(self.data)
        self.assertEqual((rep["status"], rep["errored"]), ({"done": 1, "error": 1, "no_plan": 1}, 1))
        self.assertEqual(rep["plans"]["by_planner"]["round 1: repeated the eval (no plan)"], 1)
        self.assertEqual(rep["steps"]["python-script"]["tried"], 3)  # not the errored seed's step
        self.assertEqual(rep["drops"], {"python-script": {"import_crash": 1}})  # no "?"
        self.assertEqual(rep["tests"], {"python-script": {"valid": 1, "unconfirmed": 1}})
        self.assertEqual(rep["projection"]["per_kind"]["code"]["model_s"], 30.0)
        self.assertEqual((rep["gate"]["foreign"], rep["gate"]["foreign_models"], rep["gate"]["switches"]),
                         (2, ["deepseek-r1:70b", "qwen3-coder-next:latest"], 1))
        text = read(os.path.join(self.data, RP.REPORT_FILE))
        self.assertIn("Seeds finished: 2 (done 1, no_plan 1)", text)
        self.assertIn("**Errored seeds: 1.**", text)
        self.assertIn("| python-script | unconfirmed | 1 |", text)
        self.assertIn("2 times a model was loaded that this start hadn't called and no earlier start of this run left "
                      "(deepseek-r1:70b, qwen3-coder-next:latest)", text)
        self.assertNotIn("Left loaded by this run's own earlier starts", text)  # no RUN.json: no earlier start

    def test_models_a_restart_left_loaded(self):
        """A foreign event for a model this run called itself, within keep_alive of its last call before the start
        the event falls in, is the run's own leftover; later than that, or a model it never called, is someone
        else's."""
        t0 = 1793739000.0
        models = {"teacher": "gpt-oss:120b", "helper": "hydra:1.0"}
        C.write_json(os.path.join(self.data, "RUN.json"), {"started": iso(t0 + 3600), "models": models,
                                                           "starts": [{"started": iso(t0), "models": models}]})
        calls = C.Cache(os.path.join(self.data, "cache", "calls.jsonl"))
        calls.put("k-plan", {"model": "hydra:1.0", "purpose": "plan", "wall_s": 9.0, "t": iso(t0 + 3000),
                             "content": MARK})
        calls.put("k-worker", {"model": "gpt-oss:120b", "purpose": "worker", "wall_s": 30.0, "t": iso(t0 + 3700),
                               "content": MARK})
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [record("n-blender-0001-00", [step("s1")])])
        C.write_jsonl(os.path.join(self.data, "gate.jsonl"), [
            {"t": t0 + 3600 + 1, "event": "foreign", "models": ["hydra:1.0"]},  # 601 s after its last call
            {"t": t0 + 3600 + 60, "event": "foreign", "models": ["deepseek-r1:70b", "hydra:1.0"]},
            {"t": t0 + 3600 + 1500, "event": "foreign", "models": ["hydra:1.0"]}])  # 2,100 s after: not ours
        rep = RP.report(self.data)
        g = rep["gate"]
        self.assertEqual((g["foreign"], g["left_loaded"], g["left_loaded_models"]), (3, 2, ["hydra:1.0"]))
        self.assertEqual((g["other"], g["other_models"]), (2, ["deepseek-r1:70b", "hydra:1.0"]))
        text = read(os.path.join(self.data, RP.REPORT_FILE))
        self.assertIn("**Left loaded by this run's own earlier starts:** 2 times a model this start hadn't called yet "
                      "was loaded (hydra:1.0), within keep_alive (15m)", text)
        self.assertIn("not Chimera lending", text)
        self.assertIn("**Other models in Ollama:** 2 times a model was loaded", text)

    def test_what_the_changes_after_the_smoke_did(self):
        files = step("s1", mode="files", kind="code")
        files["candidates"][0]["normalised"] = {"file_lines": 2, "marker_dashes": 0}
        files["tests"] = {"refused": [{"why": "subprocess"}], "rewrite": {"valid": True}}
        files["tests_status"] = "valid"
        docs = step("s2", mode="python-script", kind="code")
        docs["tests"] = {"rewrite": {"skipped": "third_party"}}
        docs["tests_status"] = "none:third_party"
        glow = step("s3")
        glow["candidates"] = [{"model": "qwen3.8:27b", "content": MARK, "echoed": "version_leak"},
                              {"model": "gpt-oss:120b", "content": piece("s3"),
                               "normalised": {"file_lines": 0, "marker_dashes": 1}},
                              {"model": "qwen3.8:27b", "content": MARK, "echoed": "notes_leak"}]
        glow["kept"] = {"from": "cand", "index": 1}
        packing = step("s4", mode="section", kind="writing", content="## Packing\n\n" + MARK)
        packing["missing_deps"] = ["s1"]
        packing["candidates"][0]["judge"] = {"ok": False, "rule": "missing_dep"}
        # kept code steps with no tests that ran; Shout's record is of the shape before the retry was kept apart (its
        # empty retry in refused), Greet's and Yell's of today's
        shout = step("s5", mode="python-script", kind="code")
        shout.update(tests={"code": None, "refused": [{"why": "name_guess"}, {"why": "no_tests"}]},
                     tests_status="none:tests_refused")
        greet = step("s10", mode="python-script", kind="code")
        greet.update(tests={"code": None, "why": "no_tests", "refused": [{"why": "subprocess", "key": "t1"}],
                            "retry": {"why": "no_tests", "gave": "empty", "callable": False}},
                     tests_status="none:no_tests")
        yell = step("s11", mode="python-script", kind="code")
        yell.update(tests={"code": None, "why": "name_guess",
                           "refused": [{"why": "name_guess", "key": "t2"}, {"why": "name_guess", "retry": True}],
                           "retry": {"why": "name_guess", "gave": "refused", "callable": True}},
                    tests_status="none:tests_refused")
        cheer = step("s12", mode="python-script", kind="code")
        cheer.update(tests={"code": None, "why": "no_tests", "refused": [{"why": "no_asserts", "key": "t3"}],
                            "retry": {"why": "no_tests", "gave": "empty", "callable": True}},
                     tests_status="none:tests_refused")
        saver = step("s6", mode="files", kind="code")
        saver.update(tests={"code": None, "why": "no_tests"}, tests_status="none:third_party",
                     import_fault="third_party")
        callable_ = step("s7", mode="files", kind="code")
        callable_.update(tests={"code": None, "why": "no_tests"}, tests_status="none:no_tests")
        nothing = step("s8", mode="files", kind="code")
        nothing.update(tests={"code": None, "why": "no_tests"}, tests_status="none:no_tests", nothing_ran=True)
        page = step("s9", mode="files", kind="code")
        page.update(tests={"code": None, "why": "no_python"}, tests_status="none:no_python", nothing_ran=True)
        variant = step("s9", mode="files", kind="code", variant="failed_dep")
        variant["tests_status"] = "none:variant"
        plan = {"steps": [{"title": f"Step {k}", "instructions": "Write it. " + MARK} for k in range(1, 13)]}
        plan["steps"][6]["instructions"] = "Write tool/run.py with run(args), the command line. " + MARK
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [record(
            "n-mixed-0001-00", [files, docs, glow, packing, shout, saver, callable_, nothing, page, greet, yell,
                                cheer], [variant], plan=plan)])
        a = RP.report(self.data)["after_smoke"]
        # only real refusals count (a why task.REFUSED refuses: Shout's empty retry isn't one), and what each retry
        # gave is apart: Greet's empty tests on a step that names nothing to call are no refusal (none:no_tests)
        self.assertEqual(a, {"normalised": {"files": {"file_lines": 1}, "blender": {"marker_dashes": 1}},
                             "version_leak": {"blender": 1}, "notes_leak": {"blender": 1},
                             "tests_refused": {"subprocess": 2, "name_guess": 3, "no_asserts": 1},
                             "tests_retries": {"empty tests on a step with nothing to call (no refusal)": 1,
                                               "refused again": 1,
                                               "empty tests on a step that names a callable (still refused)": 1},
                             "tests_rewrites": {"counted": 1, "skipped: third_party": 1},
                             "missing_dep_judged": {"turned down": 1},
                             "refused_untested": {"python-script": 3}, "third_party_import": {"files": 1},
                             "no_tests_callable": {"files": 1}, "no_python": {"files": {"steps": 1, "of": 5}},
                             "nothing_ran": {"files": 2}})
        text = read(os.path.join(self.data, RP.REPORT_FILE))
        self.assertIn("After the smoke run's changes: replies made plain (blender: marker_dashes 1; files: file_lines "
                      "1); dropped for a Blender version only the notes name: blender 1; for the notes' words for the "
                      "Blenders or the sandbox: blender 1; tests refused and asked again: name_guess 3, no_asserts 1, "
                      "subprocess 2; what those retries gave: empty tests on a step that names a callable (still "
                      "refused) 1, empty tests on a step with nothing to call (no refusal) 1, refused again 1; tests "
                      "rewrites: counted 1, skipped: third_party 1; sections judged with a dependency missing: turned "
                      "down 1.",
                      text)
        self.assertIn("Kept code steps with no tests that ran: tests still refused after the retry (dropped): "
                      "python-script 3; a package outside the standard library missing from the import run "
                      "(dropped): files 1; no tests given although the step names a callable (kept): files 1; no "
                      "Python to test (kept, unverified): files 1 of 5; nothing ran on them at all, those among them "
                      "(kept, unverified): files 2.", text)

    def test_a_kind_with_no_examples_and_a_call_made_twice(self):
        """research kept 0 of 2 tries: costed from its own tries over a Laplace keep rate, (0 + 1) / (2 + 2), not
        at the other kinds' mean; general had no tries: the mean, said so. A judge call two candidates of one seed
        share (the second from the cache) counts once in that seed, again in another seed."""
        def judged(sid, n):
            st = step(sid, content=piece(sid, n))
            st["seconds"] = {"teacher": 10.0, "judge": 8.0}  # the shared judge call added twice, as task.judge does
            st["candidates"] = [dict(st["candidates"][0], key=f"cand-{n}-{k}", wall_s=5.0, cached=False,
                                     judge={"key": "judge-same-scene", "wall_s": 4.0, "cached": k > 0})
                                for k in range(2)]
            return st
        research = []
        for k, secs in ((1, 40.0), (2, 50.0)):
            st = step(f"s{k}", mode="section", kind="research")
            st.update(kept=None, drop=["validator:no_heading"], seconds={"teacher": secs})
            research.append(st)
        writing = step("s3", mode="section", kind="writing", content="## Soil\n\n" + MARK)
        writing["seconds"] = {"teacher": 12.0}
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [
            record("n-blender-0001-00", [judged("s1", 1)]), record("n-blender-0002-00", [judged("s1", 2)]),
            record("n-mixed-0001-00", research + [writing])])
        pr = RP.report(self.data)["projection"]
        per = pr["per_kind"]
        self.assertEqual(per["blender"]["model_s"], 2 * (18.0 - 4.0))
        self.assertEqual((per["blender"]["costed"], per["blender"]["s_per_example"]), ("measured", 14.0))
        r = per["research"]
        self.assertEqual((r["costed"], r["tried"], r["kept"], r["s_per_try"], r["keep_rate"], r["estimate_s"]),
                         ("estimate", 2, 0, 45.0, 0.25, 180.0))
        self.assertIsNone(r["s_per_example"])
        self.assertEqual(per["general"]["costed"], "mean")
        mean = (14.0 * 640 + 12.0 * 300) / (640 + 300)
        self.assertEqual(pr["mean_s"], round(mean, 1))
        self.assertEqual(per["code"]["costed"], "mean")
        want = (640 * 14.0 + 540 * mean + 300 * 12.0 + 130 * 180.0 + 90 * mean) / 3600
        self.assertEqual(pr["hours_to_plan_mix"]["1"], round(want, 1))
        text = read(os.path.join(self.data, RP.REPORT_FILE))
        self.assertIn("| research | 2 | 0 | 0 | 90.0 | 180.0 (estimate) | 130 |", text)
        self.assertIn("research has no built examples, so it is costed from its own 2 tries (45.0 s of model time "
                      "each) at an estimated keep rate of 25%, Laplace's rule (kept + 1) / (tried + 2) with 0 kept",
                      text)
        self.assertIn(f"general had no tries here, so it is costed at the plan-weighted mean of the measured kinds "
                      f"({round(mean, 1)} s per example)", text)
        self.assertNotIn("costed at the mean.", text)


class AfterTheAuditTests(unittest.TestCase):
    """What report.py says since the second smoke run's audit (DATAGEN-SMOKE.md, "Second smoke run")."""

    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="report-audit-", dir=_tmp)
        self.addCleanup(shutil.rmtree, self.data, True)

    def test_model_time_counts_only_the_calls_the_records_use(self):
        """The second run's cache was seeded with the first run's 744 calls, and the table summed them all. Now: the
        calls a record uses (an errored seed's too: they were made) and seed_calls.jsonl's, each once; one made
        before the run's first start is an earlier run's, said apart; a cached call no record uses is left out."""
        t0 = 1793739000.0
        C.write_json(os.path.join(self.data, "RUN.json"), {"started": iso(t0), "models": {"teacher": "gpt-oss:120b"}})
        calls = C.Cache(os.path.join(self.data, "cache", "calls.jsonl"))
        for key, model, purpose, wall, t, extra in (
                ("k-cand", "gpt-oss:120b", "worker", 30.0, t0 + 60, {"stats": {"eval_count": 500}}),
                ("k-judge", "gpt-oss:120b", "judge", 8.0, t0 - 86400, {}),  # an earlier run's, from the cache
                ("k-seed", "gpt-oss:120b", "seed", 40.0, t0 + 1, {}),
                ("k-old", "gpt-oss:120b", "worker", 100.0, t0 - 86400, {}),  # copied in, never used here
                ("k-err", "qwen3.8:27b", "second", 20.0, t0 + 120, {"error": "boom " + MARK})):
            calls.put(key, dict({"model": model, "purpose": purpose, "wall_s": wall, "t": iso(t), "content": MARK},
                                **extra))
        used = step("s1")
        used["candidates"][0].update(key="k-cand", wall_s=30.0, judge={"key": "k-judge", "wall_s": 8.0})
        again = step("s2")  # the same judge call again, from the cache: still one call
        again["candidates"][0].update(key="k-cand", wall_s=30.0, judge={"key": "k-judge", "wall_s": 8.0})
        broken = step("s1")
        broken["candidates"][0].update(key="k-err", wall_s=20.0)
        broken.update(kept=None, drop=None)
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [
            record("n-blender-0001-00", [used, again]),
            dict(record("n-blender-0002-00", [broken]), status="error", error="CallFailed: " + MARK)])
        C.write_jsonl(os.path.join(self.data, "seed_calls.jsonl"), [
            {"key": "blender-0000", "call_key": "k-seed", "tries": [{"sample": 0, "key": "k-seed"}], "wall_s": 40.0}])
        rep = RP.report(self.data)
        zero = {"eval_tokens": 0, "errors": 0, "earlier": 0, "earlier_s": 0.0}
        self.assertEqual(rep["model_time"], {
            "gpt-oss:120b judge": dict(zero, calls=1, wall_s=8.0, earlier=1, earlier_s=8.0),
            "gpt-oss:120b seed": dict(zero, calls=1, wall_s=40.0),
            "gpt-oss:120b worker": dict(zero, calls=1, wall_s=30.0, eval_tokens=500),
            "qwen3.8:27b second": dict(zero, calls=1, wall_s=20.0, errors=1)})
        self.assertEqual(rep["calls_left_out"], {"calls": 1, "wall_s": 100.0})
        # a seed's id is no call: used_calls reads every "key", and the cache sorts them out
        self.assertEqual(RP.used_calls(self.data, []), {"k-seed", "blender-0000"})
        text = read(os.path.join(self.data, RP.REPORT_FILE))
        self.assertIn("| gpt-oss:120b worker | 1 | 30.0 | 500 | 0 |", text)
        self.assertIn("Only the calls the records use, each once (4). Of them, 1 (8.0 s) came from a run whose cache "
                      "this one was seeded with: made before this run's first start, answered from the cache here. "
                      "Left out of the table: 1 call in the cache that no record uses (100.0 s).", text)

    def test_what_the_changes_after_the_audit_did(self):
        """The new gates' firings over every try (dep_claimed:<sid> as dep_claimed) and what became of their steps;
        steps kept only as a dependency (no_example), apart in the steps table and left out of the tests table and
        of the projection's keep count; kept code steps whose tests couldn't reach their code; and what each tests
        rewrite said of the candidates it failed."""
        claimed = step("s1")  # kept from its second try, after the first claimed a failed dependency
        claimed["candidates"] = [{"model": "gpt-oss:120b", "content": MARK, "reasons": ["dep_claimed:s9",
                                                                                         "dep_unlisted"]},
                                 {"model": "gpt-oss:120b", "content": piece("s1"), "reasons": []}]
        claimed["kept"] = {"from": "cand", "index": 1}
        soft = step("s2")  # every try handed no output over: kept for the later steps, no example
        soft["candidates"][0]["reasons"] = ["output_missing"]
        soft["no_example"] = ["output_missing"]
        camera = step("s3")
        camera["candidates"][0]["reasons"] = ["camera_not_active", "output_missing", "join_syntax"]
        camera["repairs"] = [{"model": "gpt-oss:120b", "content": MARK, "turn": 1, "reasons": ["camera_not_active"]}]
        camera.update(kept=None, drop=["camera_not_active"])
        layout = step("s4", mode="files", kind="code")
        layout["candidates"][0]["reasons"] = ["layout_import"]
        layout.update(kept=None, drop=["layout_import"])
        unreachable = step("s5", mode="python-script", kind="code")
        unreachable["tests"] = {"code": MARK, "kept_untested": True, "fault": "tests_unreachable", "rewrite_errors": [
            {"from": "cand", "index": 0, "error": "ModuleNotFoundError: No module named 'tasktimer'  " + MARK},
            {"from": "second", "index": 1, "error": "AssertionError: Expected exit code 0, got 2"}]}
        unreachable["tests_status"] = "none:tests_unreachable"
        soft_code = step("s6", mode="python-script", kind="code")
        soft_code.update(tests_status="valid", no_example=["dep_claimed:s1"])
        soft_code["candidates"][0]["reasons"] = ["dep_claimed:s1"]
        variant = step("s2", variant="failed_dep")
        variant["candidates"][0]["reasons"] = ["dep_unlisted"]
        variant.update(kept=None, drop=["dep_unlisted"])
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [record(
            "n-mixed-0001-00", [claimed, soft, camera, layout, unreachable, soft_code], [variant])])
        rep = RP.report(self.data)
        a = rep["after_audit"]
        self.assertEqual(a["gates"], {"dep_claimed": {"blender": 1, "python-script": 1}, "dep_unlisted": {"blender": 2},
                                      "output_missing": {"blender": 2}, "camera_not_active": {"blender": 2},
                                      "layout_import": {"files": 1}})
        self.assertEqual(a["gate_steps"], {"dep_claimed": {"kept": 1, "dependency only": 1},
                                           "dep_unlisted": {"kept": 1, "dropped": 1},
                                           "output_missing": {"dependency only": 1, "dropped": 1},
                                           "camera_not_active": {"dropped": 1}, "layout_import": {"dropped": 1}})
        self.assertEqual((a["no_example"], a["no_example_why"], a["tests_unreachable"]),
                         ({"blender": 1, "python-script": 1}, {"dep_claimed": 1, "output_missing": 1},
                          {"python-script": 1}))
        self.assertEqual(a["rewrite_errors"], [{
            "seed": "n-mixed-0001-00", "round": 1, "sid": "s5", "mode": "python-script",
            "tests": "none:tests_unreachable",
            "errors": ["cand 0: ModuleNotFoundError: No module named 'tasktimer' " + " ".join(MARK.split()),
                       "second 1: AssertionError: Expected exit code 0, got 2"]}])
        self.assertEqual((rep["steps"]["blender"]["dependency only"], rep["steps"]["python-script"]["dependency only"]),
                         (1, 1))
        self.assertEqual(rep["tests"], {"python-script": {"none:tests_unreachable": 1}})  # not the soft keep's valid
        per = rep["projection"]["per_kind"]
        self.assertEqual((per["blender"]["tried"], per["blender"]["kept"], per["blender"]["examples"]), (4, 1, 1))
        text = read(os.path.join(self.data, RP.REPORT_FILE))
        self.assertIn("| mode | tried | first samples | more samples | repairs | second sampler | dependency only | "
                      "dropped | plan_failed |", text)
        self.assertIn("After the second smoke run's audit: the new gates fired, dep_claimed on 2 tries (blender 1, "
                      "python-script 1) of 2 steps (dependency only 1, kept 1); dep_unlisted on 2 tries (blender 2) of "
                      "2 steps (dropped 1, kept 1); output_missing on 2 tries (blender 2) of 2 steps (dependency only "
                      "1, dropped 1); camera_not_active on 2 tries (blender 2) of 1 step (dropped 1); layout_import on "
                      "1 try (files 1) of 1 step (dropped 1). Steps kept only as a dependency (no example): blender 1, "
                      "python-script 1, for dep_claimed 1, output_missing 1. Kept code steps whose tests couldn't "
                      "reach their code (kept, unverified): python-script 1.", text)
        self.assertIn("What the tests rewrites said of the candidates they failed (1 step, rewrite_errors):", text)
        self.assertIn("| n-mixed-0001-00 | 1 | s5 | python-script | none:tests_unreachable | 2: cand 0: "
                      "ModuleNotFoundError: No module named 'tasktimer'", text)
        self.assertIn("none:tests_unreachable: the tests couldn't reach the step's code, kept and marked unverified",
                      text)

    def test_the_builds_new_drops(self):
        """sft/stats.json's facts filters and no_example drops, with how often each fired when that was more often
        than it dropped (an example is dropped by the first that fires); nothing before a build."""
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [record("n-blender-0001-00", [step("s1")])])
        self.assertIsNone(RP.report(self.data)["build"])
        C.write_json(os.path.join(self.data, "sft", "stats.json"), {
            "kept": 29, "examples": 52, "published": True,
            "dropped": {"dep_claimed": 8, "tests_unconfirmed": 3, "validator_warning": 2, "no_example": 1},
            "facts": {"dep_claimed": {"dropped": 8, "fired": 8}, "validator_warning": {"dropped": 2, "fired": 4}},
            "unverified_by_why": {"none:tests_unreachable": 1}})
        b = RP.report(self.data)["build"]
        self.assertEqual(b["new"], {"dep_claimed": 8, "validator_warning": 2, "no_example": 1})
        self.assertEqual(b["unverified_by_why"], {"none:tests_unreachable": 1})
        self.assertIn("The build's new drops (of 52 examples, 29 kept): dep_claimed 8, validator_warning 2 (fired on "
                      "4), no_example 1.", read(os.path.join(self.data, RP.REPORT_FILE)))


def blender_piece(sid, body, provides="none"):
    """A Blender piece (a fixture, with the mark): SETTINGS and build_sN around body's lines, and a handoff."""
    lines = "\n".join("    " + line for line in body.strip("\n").split("\n"))
    return (f"```python\n{MARK}\nimport bpy\n\nSETTINGS_{sid} = {{\"size\": 1.0}}\n\n\ndef build_{sid}(ctx):\n{lines}\n"
            f"```\n\n```handoff\nprovides: {provides}\nuses: none\nassumed: none\n```\n")


def warned(channel, keys):
    """A stored verdict with Chimera's provides_missing warning on channel for keys (the validator's own words)."""
    message = f'registers ctx["{channel}"] key(s) {", ".join(keys)} that provides doesn\'t list'
    return {"ok": True, "issues": [{"level": "warn", "code": "provides_missing", "line": 0, "message": message}]}


class AfterTheThirdSmokeTests(unittest.TestCase):
    """What report.py counts since the third smoke (format 4), on hand-made records (fixtures): ctx_channel by
    whether a later step depends on the step, soft keeps by reason and the same split, the values-only steps and
    whether their kept pieces hand values on in ctx["values"], Chimera's provides_missing warnings that are only a
    reader's own stand-ins, step 6's facts, the geometry readers' held-out counts, and the passed repairs whose share
    crosses REPAIR_SHARE on code lines but not on every line, or the reverse."""

    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="report-format4-", dir=_tmp)
        self.addCleanup(shutil.rmtree, self.data, True)

    def plan(self, *deps):
        """A plan whose step k depends on deps[k] (step ids); s1 is a values-only step by its title."""
        titles = ["Define variables for the room"] + [f"Step {k}" for k in range(2, len(deps) + 1)]
        return {"steps": [{"id": f"s{k}", "title": titles[k - 1], "kind": "blender", "depends_on": list(d),
                           "instructions": "Build it. " + MARK} for k, d in enumerate(deps, 1)]}

    def test_ctx_channel_soft_keeps_and_values_steps(self):
        used = step("s1", content=blender_piece("s1", 'ctx["variables"] = dict(SETTINGS_s1)'))
        used["candidates"] = [dict(used["candidates"][0], reasons=["ctx_channel"]) for _ in range(3)]
        used["no_example"] = ["ctx_channel"]
        soft = step("s2", content=piece("s2"))
        soft["candidates"][0]["reasons"] = ["swallowed", "place_mismatch"]
        soft["no_example"] = ["place_mismatch", "swallowed"]
        lone = step("s3", content=piece("s3"))
        lone["candidates"] = [dict(lone["candidates"][0], reasons=["ctx_channel", "lint:socket"]),
                              dict(lone["candidates"][0], reasons=["ctx_channel"])]
        lone.update(kept=None, drop=["ctx_channel"])
        variant = step("s1", variant="mixed_pool")  # of the step s2 depends on: still unused, as it feeds no step
        variant["candidates"][0]["reasons"] = ["ctx_channel"]
        variant.update(kept=None, drop=["ctx_channel"])
        # the values step of a second seed: its kept piece hands its value on through a name bound to ctx["values"]
        # (the code reader doesn't see it, the alone run's listing does), and a third's through update()
        alias = step("s1", content=blender_piece("s1", 'v = ctx["values"]\nv["width"] = SETTINGS_s1["size"]'))
        alias["candidates"][0]["gate"] = {"scene": {"objects": [], "ctx_values": ["width"]}}
        plain = step("s1", content=blender_piece("s1", 'ctx["values"].update(SETTINGS_s1)\n'
                                                       'ctx["objects"]["room"] = (1.0, -2.0)'))
        dropped = step("s1", content=blender_piece("s1", 's = SETTINGS_s1\nctx["objects"]["height"] = s["size"]'))
        dropped.update(kept=None, drop=["lint:socket"])
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [
            record("n-blender-0001-00", [used, soft, lone], [variant], plan=self.plan([], ["s1"], [])),
            record("n-blender-0002-00", [alias, step("s2")], plan=self.plan([], ["s1"])),
            record("n-blender-0003-00", [plain, step("s2")], plan=self.plan([], ["s1"])),
            record("n-blender-0004-00", [dropped, step("s2")], plan=self.plan([], ["s1"])),
            record("n-blender-0005-00", [step("s1"), step("s2")], plan=self.plan([], []))])  # nothing depends on s1
        rep = RP.report(self.data)
        a = rep["after_audit"]
        self.assertEqual(a["ctx_channel"], {"used": {"tries": 3, "dependency only": 1},
                                            "unused": {"tries": 3, "dropped": 2}})
        self.assertEqual(a["gates"]["ctx_channel"], {"blender": 6})
        self.assertEqual((a["gates"]["swallowed"], a["gates"]["place_mismatch"]), ({"blender": 1}, {"blender": 1}))
        # step 6's reasons are soft on a step nothing depends on too (s2 here); ctx_channel only on a used one
        self.assertEqual(a["soft_keeps"], {"ctx_channel": {"used": 1}, "place_mismatch": {"unused": 1},
                                           "swallowed": {"unused": 1}})
        self.assertEqual(a["no_example_why"], {"ctx_channel": 1, "place_mismatch": 1, "swallowed": 1})
        # the values steps: s1 of the four plans with a dependent (not the last seed's)
        self.assertEqual(a["values_steps"], {"steps": 4, "dependency only": 1, "kept": 2, "dropped": 1,
                                             "writes_values": 1, "hands_on": 1})
        self.assertTrue(RP.writes_values('ctx["values"]["k"] = 1') and RP.writes_values(
            'def build_s1(c):\n    c["values"].setdefault("k", 1)'))
        self.assertFalse(RP.writes_values('x = ctx["values"].get("k")') or RP.writes_values('ctx["values"] = {}')
                         or RP.writes_values("def broken(:"))
        # plain values registered in ctx["objects"]: counted (the kept one of the third seed, the dropped fourth's)
        self.assertEqual(a["values_in_objects"], {"tries": 2, "kept": 1})
        self.assertEqual(RP.values_in_objects('for k, v in SETTINGS_s1.items():\n    ctx["objects"][k] = v'),
                         ["<loop over SETTINGS>"])
        self.assertEqual(RP.values_in_objects('ctx["objects"]["lamp"] = bpy.data.objects.new("l", None)'), [])
        text = read(os.path.join(self.data, RP.REPORT_FILE))
        self.assertIn("ctx_channel (a ctx key Chimera's join doesn't make; a gate since format 4): on steps a later "
                      "step depends on (soft there), 3 tries of 1 step (dependency only 1); on the others, variants "
                      "among them (hard), 3 tries of 2 steps (dropped 2).", text)
        self.assertIn("Steps kept only as a dependency by each reason, on steps a later step depends on and on the "
                      "others: ctx_channel 1 and 0; place_mismatch 0 and 1; swallowed 0 and 1.", text)
        self.assertIn("Values-only steps (hints.values_step: their notes carry the values note): 4 (dependency only "
                      "1, dropped 1, kept 2); of their kept pieces, 1 write ctx[\"values\"] and 1 handed "
                      "ctx[\"values\"] keys on when run alone.", text)
        self.assertIn("Plain values registered in ctx[\"objects\"] (counted, not a gate; ctx[\"values\"] is theirs): "
                      "2 tries, 1 of them kept pieces that give an example.", text)
        self.assertIn("After the second smoke run's audit: the new gates fired, ", text)
        self.assertIn("ctx_channel on 6 tries (blender 6) of 3 steps (dependency only 1, dropped 2)", text)

    def test_provides_missing_for_a_readers_own_stand_ins(self):
        """A reader that registers its stand-in for a dependency's key where it found none warns provides_missing
        though it is right: counted apart (own) when every key it names is one the piece also reads or tests with
        in, and apart again when the warning is on a kept piece that gives an example (the build drops it)."""
        reader = step("s2", content=blender_piece("s2", 'if "floor" not in ctx["objects"]:\n'
                                                        '    print("chimera: stand-in", "floor")\n'
                                                        '    ctx["objects"]["floor"] = None'))
        reader["candidates"][0]["verdict"] = warned("objects", ["floor"])
        values = step("s3", content=blender_piece("s3", 'h = ctx["values"].get("height")\nif h is None:\n'
                                                        '    ctx["values"]["height"] = 2.0'))
        values["candidates"][0]["verdict"] = warned("values", ["height"])
        values["no_example"] = ["swallowed"]  # kept only as a dependency: no example, so not the build's drop
        own = step("s4", content=blender_piece("s4", 'ctx["objects"]["rug"] = None\nctx["objects"]["lamp"] = '
                                                     'ctx["objects"].get("lamp")'))
        own["candidates"] = [dict(own["candidates"][0], verdict=warned("objects", ["rug", "lamp"])),
                             dict(own["candidates"][0], verdict=warned("objects", ["lamp"]))]
        own["kept"] = {"from": "cand", "index": 1}
        cut = step("s5", content=blender_piece("s5", 'ctx["objects"]["a_very_long_key"] = None',
                                               provides="chimera_s5"))
        cut["candidates"][0]["verdict"] = {"ok": True, "issues": [{"level": "warn", "code": "provides_missing",
                                                                   "message": 'registers ctx["objects"] key(s) a_ve'}],
                                           "handoff": {"provides": "chimera_s5"}}
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [record("n-blender-0001-00", [reader, values, own, cut])])
        a = RP.report(self.data)["after_audit"]
        self.assertEqual(a["provides_stand_in"], {"objects": {"fired": 4, "own": 2, "kept": 3, "kept_own": 2},
                                                  "values": {"fired": 1, "own": 1, "kept": 0, "kept_own": 0}})
        self.assertEqual(RP.stand_in_warnings(cut["candidates"][0]), [("objects", ["a_very_long_key"], False)])
        self.assertIn('Chimera\'s provides_missing warnings: ctx["objects"] on 4 tries, 2 of them only for the '
                      "piece's own stand-ins (keys it reads or tests too), 3 on kept pieces that give an example (2 "
                      'own stand-ins), which the build drops (validator_warning); ctx["values"] on 1 try, 1 of them',
                      read(os.path.join(self.data, RP.REPORT_FILE)))

    def test_step_six_facts_and_the_readers(self):
        """Excused hidden errors by why, attribute misses, hidden errors found only joined, the floor and above or
        below readings across the versions, and the faults of a geometry reader that isn't gated (nested this round:
        recorded, never a reason); a gated reader's fault is a reason, not counted there; a place fault on a run that
        printed a stand-in (recorded only). The held-out counts are geometry.HELD_OUT's."""
        c = step("s1")
        c["candidates"][0]["gate"] = {"measured": {
            "silent": {"swallowed": [], "skipped": [], "attr_miss": [{"line": 3, "attr": "use_nodes", "on": "World"}],
                       "excused": [{"line": 4, "why": "gpu"}, {"line": 9, "why": "file"}, {"line": 12, "why": "gpu"}]},
            "joined_silent": {"swallowed": [{"line": 4}], "skipped": [], "attr_miss": [], "excused": []},
            "places": [{"phrase": "on the floor", "floor": [True, True]}, {"phrase": "on the ground",
                                                                          "floor": [True, None]},
                       {"phrase": "at (0, 0, 1)", "fits": False, "fault": "a gated fault " + MARK},
                       {"phrase": "at (1, 0, 0.75)", "fits": None, "unmeasured": "stand_in",
                        "stand_in_fault": "a fault on the stand-in " + MARK}],
            "depths": [{"phrase": "0.1 m deep", "fits": True}],
            "relations": [{"phrase": "above the table", "holds": [False, False]},
                          {"phrase": "behind the plate", "fits": False, "fault": "a nested fault " + MARK}]}}
        quiet = step("s2")
        quiet["candidates"][0]["gate"] = {"measured": {"silent": {"swallowed": [], "skipped": [], "attr_miss": [],
                                                                  "excused": []}}}
        # a miss that is the attr_miss reason itself counts under the new gates, not here (the independent checks)
        fired = step("s3")
        miss = [{"line": 5, "attr": "fcurves", "on": "Action"}]
        fired["candidates"][0]["reasons"] = ["attr_miss"]
        fired["candidates"][0]["gate"] = {"measured": {"silent": {"swallowed": [], "skipped": [], "attr_miss": miss,
                                                                  "missed": miss, "excused": []}}}
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [record("n-blender-0001-00", [c, quiet, fired])])
        a = RP.report(self.data)["after_audit"]
        self.assertEqual(a["step6"], {"excused": {"file": 1, "gpu": 2}, "attr_miss": 1, "joined_silent": 1,
                                      "floor": {"unread": 1, "yes": 1}, "holds": {"no": 1}, "off": {"nested": 1},
                                      "stood_in": {"place_mismatch": 1}})
        self.assertEqual(a["readers"], {"place_mismatch": {"read": 22, "misread": 1, "gated": True},
                                        "flat_extrusion": {"read": 17, "misread": 2, "gated": True},
                                        "nested": {"read": 15, "misread": 8, "gated": False},
                                        "doubled_depth": {"read": 9, "misread": 1, "gated": True}})
        text = read(os.path.join(self.data, RP.REPORT_FILE))
        self.assertIn("Step 6's facts (no reason of their own): hidden errors excused file 1, gpu 2; tries whose "
                      "hasattr or getattr found no such attribute 1; tries whose joined run found a hidden error at "
                      "the piece's lines (recorded only) 1; \"on the floor\" readings unread 1, yes 1; above or below "
                      "readings no 1; faults of the geometry readers not gated (recorded only) nested 1; place "
                      "faults on runs that printed a stand-in (recorded only) place_mismatch 1.", text)
        self.assertIn("The geometry readers on the held-out steps: place_mismatch read 22, misread 1 (gated); "
                      "flat_extrusion read 17, misread 2 (gated); nested read 15, misread 8 (recorded only); "
                      "doubled_depth read 9, misread 1 (gated) (gated at "
                      "2 misreads or fewer).", text)

    def test_scene_rejections_overruled_and_doubled_depth(self):
        """After the fourth smoke (Nov 5): the scene judge's rejections overruled for resting only on a size, a
        position or an output form (judge rule "overruled"), by kind and whether the try was kept; and doubled_depth
        among the new gates, by mode and by what became of its step."""
        kept = step("s1")
        kept["candidates"][0]["judge"] = {"verdict": {"ok": False, "why": "sofa size is wrong " + MARK}, "ok": True,
                                          "rule": "overruled", "overruled": ["size"]}
        other = step("s2")
        other["candidates"] = [dict(other["candidates"][0], judge={"verdict": {"ok": False, "why": "x " + MARK},
                                                                   "ok": True, "rule": "overruled",
                                                                   "overruled": ["size", "position"]}),
                               dict(other["candidates"][0], judge={"verdict": {"ok": True, "why": MARK}, "ok": True})]
        other["kept"] = {"from": "cand", "index": 1}
        doubled = step("s3")
        doubled["candidates"][0]["reasons"] = ["doubled_depth"]
        doubled["no_example"] = ["doubled_depth"]
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [record("n-blender-0001-00", [kept, other, doubled])])
        a = RP.report(self.data)["after_audit"]
        self.assertEqual(a["scene_overruled"], {"verdicts": 2, "kept": 1, "size": 2, "position": 1})
        self.assertEqual(a["gates"]["doubled_depth"], {"blender": 1})
        self.assertEqual(a["gate_steps"]["doubled_depth"], {"dependency only": 1})
        text = read(os.path.join(self.data, RP.REPORT_FILE))
        self.assertIn("Scene-judge rejections overruled (they rest only on a size, a position or an output form the "
                      "step names): 2 (position 1, size 2), 1 of them on the try kept.", text)
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [record("n-blender-0001-00", [step("s1")])])
        a = RP.report(self.data)["after_audit"]
        self.assertEqual(a["scene_overruled"], {})
        self.assertNotIn("Scene-judge rejections overruled", read(os.path.join(self.data, RP.REPORT_FILE)))

    def test_repairs_whose_share_crosses_on_code_lines(self):
        """The share is counted on code lines since format 4 (task.repair_lines), worked out from the record's own
        texts: a passed repair that rewords the comments around the line it fixes is under REPAIR_SHARE on code lines
        and over it on every line (crossed_in, named for a blind grade); one that changes most of a few code lines
        among many comments is the reverse (crossed_out); a repair that didn't pass isn't named."""
        def block(body):
            return f"```python\n{MARK}\n{body}\n```\n"
        code = "\n".join(f"x{k} = {k}" for k in range(10))
        noted = "\n".join(f"# note {k}\nx{k} = {k}" for k in range(10))
        reworded = "\n".join(f"# reworded {k}\nx{k} = {k if k else 'fixed'}" for k in range(10))
        few = "\n".join([f"# a long comment {k}" for k in range(12)] + ["a = 1", "b = 2", "c = 3"])
        fewer = "\n".join([f"# a long comment {k}" for k in range(12)] + ["a = 10", "b = 20", "c = 3"])

        def repaired(sid, before, after, passed=True):
            st = step(sid, content=block(after), repair="TypeError: fixed")
            st["repairs"][0].update(inputs={"piece": block(before)}, passed=passed, example=passed)
            return st
        steps = [repaired("s1", noted, reworded), repaired("s2", few, fewer), repaired("s3", code, code, False),
                 repaired("s4", noted, reworded, passed=False)]
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [record("n-blender-0001-00", steps)])
        rs = RP.report(self.data)["after_audit"]["repair_share"]
        self.assertEqual((rs["repairs"], rs["passed"], rs["examples"]), (4, 2, 2))
        self.assertEqual(rs["crossed_in"], ["n-blender-0001-00 r1 s1 repair 1 (0.524 -> 0.1)"])
        self.assertEqual(rs["crossed_out"], ["n-blender-0001-00 r1 s2 repair 1 (0.125 -> 0.667)"])
        self.assertEqual(rs["shrunk"], [])
        self.assertIn("Repairs with a share on code lines: 4 (2 passed, 2 examples); passed ones on the other side of "
                      "30% counted on every line: in 1 (n-blender-0001-00 r1 s1 repair 1 (0.524 -> 0.1)), out 1 "
                      "(n-blender-0001-00 r1 s2 repair 1 (0.125 -> 0.667)); passed ones that leave out more than 10% "
                      "of their code lines (no example) 0.",
                      read(os.path.join(self.data, RP.REPORT_FILE)))

    def test_passed_repairs_that_leave_code_out_are_named(self):
        """A passed repair that leaves out more than REPAIR_SHRINK of its code lines net (smoke2 blender-0002-02 r1
        s4 deleted the compositor block its step asks for) is named for the blind grade; one that didn't pass, or
        that leaves out less, isn't."""
        def block(body):
            return f"```python\n{MARK}\n{body}\n```\n"
        code = "\n".join(f"x{k} = {k}" for k in range(20))
        trimmed = "\n".join(f"x{k} = {k}" for k in range(16))  # 4 of 20 left out
        one = "\n".join(f"x{k} = {k}" for k in range(19))  # 1 of 20

        def repaired(sid, before, after, passed=True):
            st = step(sid, content=block(after), repair="TypeError: fixed")
            st["repairs"][0].update(inputs={"piece": block(before)}, passed=passed, example=False)
            return st
        steps = [repaired("s1", code, trimmed), repaired("s2", code, one), repaired("s3", code, trimmed, False)]
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [record("n-blender-0001-00", steps)])
        rs = RP.report(self.data)["after_audit"]["repair_share"]
        self.assertEqual(rs["shrunk"], ["n-blender-0001-00 r1 s1 repair 1 (20% of its code lines left out)"])
        self.assertIn("passed ones that leave out more than 10% of their code lines (no example) 1 "
                      "(n-blender-0001-00 r1 s1 repair 1 (20% of its code lines left out)).",
                      read(os.path.join(self.data, RP.REPORT_FILE)))


def call(key, purpose, wall, model="gpt-oss:120b"):
    return key, {"model": model, "purpose": purpose, "wall_s": wall, "stats": {}, "t": "2026-11-05T21:00:00-06:00"}


def meta(seed_id, sid, mode="blender", kind="blender", missing=(), source="cand"):
    return {"group": seed_id.rsplit("-", 1)[0], "seed_id": seed_id, "sid": sid, "round": 1, "kind": kind,
            "mode": mode, "variant": None, "model": "gpt-oss:120b", "missing_deps": list(missing), "source": source,
            "repaired": source == "repair", "turn": 0}


class AfterTheFourthSmokeTests(unittest.TestCase):
    """What report.py counts after the fourth smoke (DATAGEN-SMOKE.md, "Fourth smoke run"), on hand-made records
    (fixtures): blender_gate.build_facts' reasons (what the build drops, told at the gate, and the stand-in marker's
    faults) by whether a later step depends on the step, as ctx_channel, and Chimera's handoff_long on a values-only
    step's provides line (the open contract question; any form since Nov 6), read from the stored verdict so older
    records count too;
    the failed-dependency cap as a night's build would apply it in the projection, and a line per sampler with its gate
    passes and examples per 1,000 s of its own model time, plus the second sampler's budget (task.Round.solve's
    step["sampler"])."""

    def setUp(self):
        self.data = tempfile.mkdtemp(prefix="report-fourth-", dir=_tmp)
        self.addCleanup(shutil.rmtree, self.data, True)

    def write(self, recs, metas, stats):
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), recs)
        C.write_jsonl(os.path.join(self.data, "sft", "train.meta.jsonl"), metas)
        C.write_json(os.path.join(self.data, "sft", "stats.json"), stats)

    def test_build_tells_and_the_values_steps_long_list(self):
        plan = AfterTheThirdSmokeTests.plan(None, [], ["s1"], ["s2"])
        names = ", ".join("value_%02d" % k for k in range(30))
        values = step("s1", content=blender_piece("s1", 'ctx["values"].update(SETTINGS_s1)', provides=names))
        values["candidates"][0]["verdict"] = {"ok": True, "issues": [{"level": "warn", "code": "handoff_long",
                                                                      "message": "the provides line has %d characters; "
                                                                                 "the contract asks for one short line"
                                                                                 % len(names), "line": 0}],
                                              "handoff": {"provides": names, "uses": "none", "assumed": "none"}}
        # a second try with the same names behind a lead: exempt too, whatever the form (decided Nov 6)
        lead = 'ctx["values"]: ' + names
        values["candidates"].append(dict(values["candidates"][0], index=1, verdict=dict(
            values["candidates"][0]["verdict"], handoff={"provides": lead, "uses": "none", "assumed": "none"})))
        used = step("s2", content=blender_piece("s2", 'w = ctx["values"].get("value_01", 2.0)'))
        used["candidates"] = [dict(used["candidates"][0], reasons=["silent_default"]),
                              dict(used["candidates"][0], reasons=["silent_default", "dead_output_key"])]
        used.update(kept={"from": "cand", "index": 1}, no_example=["dead_output_key", "silent_default"])
        last = step("s3", content=piece("s3"))
        last["candidates"] = [dict(last["candidates"][0], reasons=["validator_warning:handoff_long"])]
        last.update(kept=None, drop=["validator_warning:handoff_long"])
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [record("n-blender-0001-00", [values, used, last],
                                                                      plan=plan)])
        a = RP.report(self.data)["after_audit"]
        self.assertEqual(a["build_tells"], {"silent_default": {"used": {"tries": 2, "dependency only": 1}},
                                            "dead_output_key": {"used": {"tries": 1, "dependency only": 1}},
                                            "validator_warning": {"unused": {"tries": 1, "dropped": 1}}})
        self.assertEqual(a["gates"]["validator_warning"], {"blender": 1})
        self.assertEqual(a["soft_keeps"], {"dead_output_key": {"used": 1}, "silent_default": {"used": 1}})
        self.assertEqual(a["handoff_exempt"], {"tries": 2, "steps": 1, "kept": 1})
        text = read(os.path.join(self.data, RP.REPORT_FILE))
        self.assertIn("What the build would drop, told at the gate, and the stand-in marker's faults (since the fourth "
                      "smoke; soft on steps a later step depends on): validator_warning used 0 tries of 0 steps "
                      "(none), unused 1 try of 1 step (dropped 1); dead_output_key used 1 try of 1 step (dependency "
                      "only 1)", text)
        self.assertIn("Chimera's handoff_long on a values-only step's provides line (the open contract question: "
                      "no reason, no tell): 2 tries of 1 step, 1 of them kept pieces that give an example, which the "
                      "build drops (validator_warning).", text)
        self.assertEqual(a["keyless_markers"], {})  # no marker with no key here: no line
        self.assertNotIn("Stand-in markers with no key", text)

    def test_keyless_markers_on_steps_with_a_dependency(self):
        """The one decision the second checks left (Nov 6): a stand-in marker with no key on a step with a dependency
        is neither judged nor any read's cover, so the report counts it for the fifth smoke to show; the same marker
        on a step with no dependency is marker_misused and isn't counted here."""
        plan = AfterTheThirdSmokeTests.plan(None, [], ["s1"])
        bare = 'print("chimera: stand-in – sofa not found, aiming at a placeholder")'
        first = step("s1", content=blender_piece("s1", bare))
        second = step("s2", content=blender_piece("s2", bare))
        second["candidates"].append(dict(second["candidates"][0], index=1,
                                         content=blender_piece("s2", 'print("chimera: stand-in", "sofa")')))
        C.write_jsonl(os.path.join(self.data, "tasks.jsonl"), [record("n-blender-0001-00", [first, second],
                                                                      plan=plan)])
        a = RP.report(self.data)["after_audit"]
        self.assertEqual(a["keyless_markers"], {"tries": 1, "steps": 1, "kept": 1})
        self.assertIn("Stand-in markers with no key on a step with a dependency (neither judged nor any read's cover, "
                      "left so after the second checks of Nov 6): 1 try of 1 step, 1 of them kept pieces that give an "
                      "example.", read(os.path.join(self.data, RP.REPORT_FILE)))

    def test_the_projection_counts_what_a_nights_cap_would_keep(self):
        # the fourth smoke's case: 4 Blender examples allow int(0.1 * 4 / 0.9) = 0 written with a failed dependency,
        # so both such were dropped; a night's 640 would keep about 71, the same 10% share: 0.444 of 4.444
        recs = []
        for k in range(2):
            steps = [step(f"s{j}", content=piece(f"s{j}", k)) for j in (1, 2, 3)]
            steps[2]["missing_deps"] = ["s2"]
            for st in steps:
                st["seconds"] = {"teacher": 10.0}
            prose = step("s4", mode="section", kind="writing", content=f"## Part {k}\n\n{MARK}\n")
            prose.update(missing_deps=["s3"], seconds={"teacher": 5.0})
            recs.append(record(f"n-blender-000{k}-00", steps + [prose]))
        metas = [meta(f"n-blender-000{k}-00", f"s{j}") for k in range(2) for j in (1, 2)]
        capped = [{"mode": "blender", "kind": "blender", "example": f"n-blender-000{k}-00 r1 s3"} for k in range(2)]
        capped.append({"mode": "section", "kind": "writing", "example": "n-blender-0000-00 r1 s4"})
        self.write(recs, metas, {"kept": 4, "examples": 7, "dropped": {"failed_dep_share": 3},
                                 "failed_dep_capped": capped})
        pr = RP.report(self.data)["projection"]
        b = pr["per_kind"]["blender"]
        self.assertEqual((b["examples"], b["capped_back"], b["model_s"]), (4, 0.444, 60.0))
        self.assertEqual(b["s_per_example"], round(60.0 / (4 + 0.4 / 0.9), 1))  # 13.5, against 15.0 before
        self.assertEqual(pr["failed_dep_cap"]["by_mode"]["blender"],
                         {"kept": 4, "natural": 0, "dropped": 2, "allowed": 0.444, "back": 0.444})
        w = pr["per_kind"]["writing"]  # no built examples: an estimate, whose keep rate counts the step as kept
        self.assertEqual((w["costed"], w["kept"], w.get("capped_back")), ("estimate", 2, None))
        text = read(os.path.join(self.data, RP.REPORT_FILE))
        self.assertIn("| blender | 6 | 6 | 4 (+0.44) | 60.0 | 13.5 | 640 |", text)
        self.assertIn("dropped 3 examples here (n-blender-0000-00 r1 s3, n-blender-0001-00 r1 s3, n-blender-0000-00 "
                      "r1 s4): blender 2 of them, with 4 examples kept and 0 of those written so, where a night keeps "
                      "0.44", text)
        self.assertIn("counts back what it would keep at the same share: blender 0.44. Not writing:", text)
        # a natural one the cap kept counts as kept: only what a night keeps beyond it comes back
        metas.append(meta("n-blender-0000-00", "s3", missing=["s2"]))
        self.write(recs, metas, {"kept": 5, "failed_dep_capped": capped[1:2]})
        b = RP.report(self.data)["projection"]["per_kind"]["blender"]
        self.assertEqual((b["examples"], b.get("capped_back")), (5, None))  # 1 of 5 kept is over 10% already
        # stats from a build before they listed the cap's drops: said so, nothing counted back
        self.write(recs, metas[:4], {"kept": 4, "dropped": {"failed_dep_share": 2}})
        pr = RP.report(self.data)["projection"]
        self.assertEqual((pr["failed_dep_cap"], pr["per_kind"]["blender"]["s_per_example"]), (None, 15.0))
        self.assertIn("The build's stats don't list what the failed-dependency cap dropped",
                      read(os.path.join(self.data, RP.REPORT_FILE)))

    def test_a_line_per_sampler(self):
        def cand(key, sample, mech=False, model="gpt-oss:120b"):
            return {"model": model, "key": key, "sample": sample, "wall_s": 1.0, "content": piece("s1"), "mech": mech,
                    "reasons": [] if mech else ["dupes"]}
        heard = step("s1")  # kept from qwen3.8, after a third told batch
        heard["candidates"] = [cand(f"h{k}", k) for k in range(6)] + \
            [cand("hq0", 0, True, "qwen3.8:27b"), cand("hq1", 1, False, "qwen3.8:27b")]
        heard["repairs"] = [{"model": "gpt-oss:120b", "key": "hr0", "wall_s": 1.0, "mech": False, "turn": 1}]
        heard.update(kept={"from": "second", "index": 6}, sampler={"heard": True, "third": 2, "second": "asked"})
        third = step("s2")  # kept from its third told batch
        third["candidates"] = [cand(f"t{k}", k) for k in range(4)] + [cand("t4", 4, True), cand("t5", 5)]
        third.update(kept={"from": "cand", "index": 4}, sampler={"heard": True, "third": 2, "second": None})
        api = step("s3")  # every sample failed on an API name: no qwen3.8
        api["candidates"] = [cand(f"a{k}", k) for k in range(4)]
        api.update(kept=None, drop=["lint:attr"],
                   sampler={"heard": False, "third": 0, "second": "skipped", "why": "api_faults", "api": ["fcurves"]})
        first = step("s4", mode="python-script", kind="code")
        first["candidates"] = [cand("c0", 0, True)]
        mended = step("s5", repair="a crash")  # kept from a repair over the share: no example, so not "kept" here
        mended["candidates"] = [cand("m0", 0)]
        mended["repairs"][0].update(key="mr0", wall_s=1.0, mech=True, example=False)
        recs = [record("n-blender-0001-00", [heard, third, api, first, mended])]
        cache = C.Cache(os.path.join(self.data, "cache", "calls.jsonl"))
        for key, value in ([call(f"h{k}", "worker", 30.0) for k in range(6)] +
                           [call("hq0", "second", 100.0, "qwen3.8:27b"), call("hq1", "second", 60.0, "qwen3.8:27b"),
                            call("hr0", "repair", 20.0)] + [call(f"t{k}", "worker", 25.0) for k in range(6)] +
                           [call(f"a{k}", "worker", 10.0) for k in range(4)] + [call("c0", "worker", 8.0)] +
                           [call("m0", "worker", 10.0), call("mr0", "repair", 10.0)]):
            cache.put(key, value)
        self.write(recs, [meta("n-blender-0001-00", "s1", source="second"), meta("n-blender-0001-00", "s2"),
                          meta("n-blender-0001-00", "s4", mode="python-script", kind="code")],
                   {"kept": 3, "failed_dep_capped": []})
        sm = RP.report(self.data)["samplers"]
        bl = sm["by_family"]["blender"]
        self.assertEqual(list(bl), ["first samples", "told samples", "second sampler", "repairs"])
        self.assertEqual(bl["first samples"], {"calls": 7, "model_s": 140.0, "gate_passes": 0, "kept": 0,
                                               "examples": 0, "per_1000_s": 0.0})
        self.assertEqual(bl["told samples"], {"calls": 10, "model_s": 240.0, "gate_passes": 1, "kept": 1,
                                              "examples": 1, "per_1000_s": 4.17})
        self.assertEqual(bl["second sampler"], {"calls": 2, "model_s": 160.0, "gate_passes": 1, "kept": 1,
                                                "examples": 1, "per_1000_s": 6.25})
        self.assertEqual(bl["repairs"], {"calls": 2, "model_s": 30.0, "gate_passes": 1, "kept": 0, "examples": 0,
                                         "per_1000_s": 0.0})
        self.assertEqual(sm["by_family"]["code"]["first samples"]["examples"], 1)
        self.assertEqual(sm["budget"], {"recorded": 3, "heard": 2, "third": 2, "third_kept": 1, "skipped": 1,
                                        "skipped_api": {"fcurves": 1}, "asked": 1})
        text = read(os.path.join(self.data, RP.REPORT_FILE))
        self.assertIn("| blender | told samples | 10 | 240.0 | 1 | 1 | 1 | 4.17 |", text)
        self.assertIn("The second sampler's budget (Blender, 3 steps past their batches): 2 got a third told batch "
                      "because their second heard the notes (1 kept from it); 1 weren't sent to the second sampler "
                      "because every teacher sample failed only on Blender API names (fcurves 1); 1 were.", text)

    def test_a_heard_batch_with_no_third_batch(self):
        """After the fifth smoke (Nov 6) the third told batch is retired: a record whose step heard its notes has
        "third" 0, and the budget line says how many heard them instead of a third batch none got."""
        def cand(key, sample, mech=False, model="gpt-oss:120b"):
            return {"model": model, "key": key, "sample": sample, "wall_s": 1.0, "content": piece("s1"), "mech": mech,
                    "reasons": [] if mech else ["dupes"]}
        heard = step("s1")  # kept from qwen3.8 right after its second batch, which heard the notes
        heard["candidates"] = [cand(f"h{k}", k) for k in range(4)] + [cand("hq0", 0, True, "qwen3.8:27b")]
        heard.update(kept={"from": "second", "index": 4}, sampler={"heard": True, "third": 0, "second": "asked"})
        deaf = step("s2")
        deaf["candidates"] = [cand(f"d{k}", k) for k in range(4)] + [cand("dq0", 0, True, "qwen3.8:27b")]
        deaf.update(kept={"from": "second", "index": 4}, sampler={"heard": False, "third": 0, "second": "asked"})
        cache = C.Cache(os.path.join(self.data, "cache", "calls.jsonl"))
        for key, value in ([call(f"h{k}", "worker", 30.0) for k in range(4)] + [call(f"d{k}", "worker", 30.0)
                                                                                for k in range(4)] +
                           [call("hq0", "second", 100.0, "qwen3.8:27b"), call("dq0", "second", 90.0, "qwen3.8:27b")]):
            cache.put(key, value)
        self.write([record("n-blender-0001-00", [heard, deaf])],
                   [meta("n-blender-0001-00", "s1", source="second"), meta("n-blender-0001-00", "s2", source="second")],
                   {"kept": 2, "failed_dep_capped": []})
        b = RP.report(self.data)["samplers"]["budget"]
        self.assertEqual(b, {"recorded": 2, "heard": 1, "third": 0, "third_kept": 0, "skipped": 0, "skipped_api": {},
                             "asked": 2})
        text = read(os.path.join(self.data, RP.REPORT_FILE))
        self.assertIn("The second sampler's budget (Blender, 2 steps past their batches): 1 had a second batch that "
                      "heard the notes, which draws no third batch since the fifth smoke; 0 weren't sent to the "
                      "second sampler because every teacher sample failed only on Blender API names; 2 were.", text)
        self.assertNotIn("got a third told batch", text)


if __name__ == "__main__":
    unittest.main()
