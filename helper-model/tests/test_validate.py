"""Validator behaviour on hand-made replies. Fixtures here are test data only: never train on them."""
import json
import unittest

from tests import _paths  # noqa: F401
from helper.validate import canonicalize_plan, tidy_plan, valid_after_tidy, validate_gate, validate_plan, validate_review


def step(i, deps=(), kind="code", title=None, instructions=None):
    return {"id": f"s{i}", "title": title or f"Part {i} of the program",
            "kind": kind, "instructions": instructions or f"Write module part{i}.py exposing run_{i}() for the CLI.",
            "depends_on": list(deps)}


def plan(steps, kind="code", **extra):
    p = {"title": "Dup finder", "kind": kind, "summary": "A CLI that finds duplicate photos. It prints groups.", "steps": steps}
    p.update(extra)
    return p


def codes(r):
    return [i.code for i in r.issues]


class PlanTests(unittest.TestCase):
    def test_canonical_plan_is_valid(self):
        r = validate_plan(json.dumps(plan([step(1), step(2), step(3, ["s1", "s2"])])))
        self.assertTrue(r.chimera_ok)
        self.assertTrue(r.valid, codes(r))
        self.assertEqual(r.metrics["steps"], 3)
        self.assertEqual(r.metrics["width"], 2)
        self.assertEqual(r.metrics["depth"], 2)

    def test_fenced_or_chatty_reply_is_accepted_by_chimera_but_not_strict(self):
        body = json.dumps(plan([step(1), step(2)]))
        for text in ("```json\n" + body + "\n```", "Here is the plan:\n" + body + "\nGood luck!"):
            r = validate_plan(text)
            self.assertTrue(r.chimera_ok)
            self.assertFalse(r.valid)
            self.assertIn("extra_text", codes(r))

    def test_numeric_ids_make_chimera_reject_the_whole_plan(self):
        p = plan([step(1), step(2)])
        p["steps"][0]["id"] = 1
        r = validate_plan(json.dumps(p))
        self.assertFalse(r.chimera_ok)
        self.assertIsNone(r.effective)
        self.assertIn("chimera_rejects", codes(r))

    def test_depends_on_as_a_string_is_rejected(self):
        p = plan([step(1), step(2)])
        p["steps"][1]["depends_on"] = "s1"
        self.assertFalse(validate_plan(json.dumps(p)).chimera_ok)

    def test_wrong_type_in_a_field_chimera_fills_itself_still_rejects(self):
        for key, val in (("tokens", "a few"), ("status", 3), ("started", "yesterday"), ("free", "no")):
            p = plan([step(1), step(2)])
            p["steps"][0][key] = val
            self.assertFalse(validate_plan(json.dumps(p)).chimera_ok, key)
        p = plan([step(1), step(2)])
        p["steps"][0]["started"] = "2026-10-27T12:00:00Z"  # a valid time decodes fine
        r = validate_plan(json.dumps(p))
        self.assertTrue(r.chimera_ok)
        self.assertIn("schema:additionalProperties", codes(r))

    def test_forward_dependency_is_dropped_by_chimera_and_flagged(self):
        r = validate_plan(json.dumps(plan([step(1, ["s2"]), step(2)])))
        self.assertTrue(r.chimera_ok)
        self.assertEqual(r.effective["steps"][0]["depends_on"], [])
        self.assertIn("dep_forward", codes(r))
        self.assertFalse(r.valid)

    def test_cycle_self_and_unknown_dependencies(self):
        r = validate_plan(json.dumps(plan([step(1, ["s2"]), step(2, ["s1"])])))
        self.assertIn("dep_cycle", codes(r))
        r = validate_plan(json.dumps(plan([step(1), step(2, ["s2"])])))
        self.assertIn("dep_self", codes(r))
        self.assertNotIn("dep_cycle", codes(r))
        r = validate_plan(json.dumps(plan([step(1), step(2, ["s9"])])))
        self.assertIn("dep_unknown", codes(r))

    def test_step_counts(self):
        r = validate_plan(json.dumps(plan([step(1)])))
        self.assertTrue(r.chimera_ok)  # Chimera runs a single step without combining
        self.assertIn("step_count", codes(r))
        nine = [step(i) for i in range(1, 10)]
        for s in nine:
            s["id"] = "s1"  # also exercise the id repair
        r = validate_plan(json.dumps(plan(nine)))
        self.assertTrue(r.chimera_ok)
        self.assertEqual(len(r.effective["steps"]), 8)
        self.assertIn("step_count", codes(r))
        self.assertIn("schema:maxItems", codes(r))
        r = validate_plan(json.dumps(plan([])))
        self.assertFalse(r.chimera_ok)

    def test_unknown_kinds_are_rewritten_by_chimera(self):
        r = validate_plan(json.dumps(plan([step(1, kind="python"), step(2)], kind="Code")))
        self.assertTrue(r.chimera_ok)
        self.assertEqual(r.effective["kind"], "general")
        self.assertEqual(r.effective["steps"][0]["kind"], "general")
        self.assertIn("schema:enum", codes(r))

    def test_keys_match_case_insensitively_like_go(self):
        p = plan([step(1), step(2)])
        p["Title"] = p.pop("title")
        r = validate_plan(json.dumps(p))
        self.assertTrue(r.chimera_ok)
        self.assertEqual(r.effective["title"], "Dup finder")
        self.assertIn("schema:required", codes(r))
        self.assertIn("schema:additionalProperties", codes(r))

    def test_blank_strings_are_repaired_by_chimera_and_flagged(self):
        p = plan([step(1, title="   "), step(2, instructions=" ")], title=" ")
        r = validate_plan(json.dumps(p))
        self.assertTrue(r.chimera_ok)
        self.assertEqual(r.effective["title"], "Long task")
        self.assertEqual(r.effective["steps"][0]["title"], "Step 1")
        self.assertEqual(r.effective["steps"][1]["instructions"], r.effective["steps"][1]["title"])
        for c in ("blank_title", "blank_title", "blank_instructions"):
            self.assertIn(c, codes(r))

    def test_clean_plan_id_repair_can_leave_a_clash(self):
        # cleanPlan renames an empty or repeated id to s<i+1> without re-checking it, so
        # ids "s2" then "" both end up "s2". The validator flags the input as id_missing.
        p = plan([step(1), step(2)])
        p["steps"][0]["id"] = "s2"
        p["steps"][1]["id"] = ""
        r = validate_plan(json.dumps(p))
        self.assertEqual([s["id"] for s in r.effective["steps"]], ["s2", "s2"])
        self.assertIn("id_missing", codes(r))

    def test_meta_steps_and_short_instructions_warn(self):
        r = validate_plan(json.dumps(plan([step(1), step(2, title="Review and combine everything", instructions="Combine.")])))
        self.assertIn("meta_step", codes(r))
        self.assertIn("instructions_short", codes(r))
        self.assertTrue(r.valid)  # warnings only

    def test_not_json(self):
        for text in ("", "Sure, here's a plan: first write code, then test.", "[1, 2]", "null"):
            r = validate_plan(text)
            self.assertFalse(r.chimera_ok, text)

    def test_canonicalize_plan(self):
        p = plan([step(1), step(2), step(3)])
        for s, new in zip(p["steps"], ("a", "b", "c")):
            s["id"] = new
        p["steps"][2]["depends_on"] = ["a", "zzz"]
        q = canonicalize_plan(p)
        self.assertEqual([s["id"] for s in q["steps"]], ["s1", "s2", "s3"])
        self.assertEqual(q["steps"][2]["depends_on"], ["s1"])
        self.assertTrue(validate_plan(json.dumps(q)).valid)

    def test_tidy_plan_fills_missing_depends_on(self):
        p = plan([step(1), step(2)])
        for s in p["steps"]:
            del s["depends_on"]
        r = validate_plan("```json\n" + json.dumps(p) + "\n```")
        self.assertTrue(r.chimera_ok)
        self.assertFalse(r.valid)
        self.assertTrue(valid_after_tidy(r))
        self.assertEqual([s["depends_on"] for s in tidy_plan(p)["steps"]], [[], []])
        bad = plan([step(1, ["s2"]), step(2)])  # tidying doesn't excuse a real error
        self.assertFalse(valid_after_tidy(validate_plan(json.dumps(bad))))


class ReviewTests(unittest.TestCase):
    def test_good_verdicts(self):
        self.assertTrue(validate_review('{"done": true, "score": 88, "critique": ""}').valid)
        r = validate_review('{"done": false, "score": 40, "critique": "There are no tests; add pytest cases for parse()."}')
        self.assertTrue(r.valid)
        self.assertFalse(r.effective["done"])

    def test_non_integer_score_stops_the_loop(self):
        for s in ("72.5", "85.0", "1e2", '"85"'):
            r = validate_review('{"done": false, "score": %s, "critique": "Add the missing tests for parse()."}' % s)
            self.assertFalse(r.chimera_ok, s)
            self.assertTrue(r.effective["done"], s)  # Chimera treats an unreadable verdict as done

    def test_string_booleans_are_rejected(self):
        r = validate_review('{"done": "false", "score": 50, "critique": "Missing the summary section."}')
        self.assertFalse(r.chimera_ok)

    def test_missing_done_means_another_round(self):
        r = validate_review('{"score": 50, "critique": "Missing the summary section."}')
        self.assertTrue(r.chimera_ok)
        self.assertFalse(r.effective["done"])
        self.assertIn("schema:required", codes(r))

    def test_critique_rules(self):
        self.assertIn("schema:minLength", codes(validate_review('{"done": false, "score": 50, "critique": ""}')))
        self.assertIn("schema:maxLength", codes(validate_review('{"done": true, "score": 90, "critique": "Nice."}')))
        self.assertIn("blank_critique", codes(validate_review('{"done": false, "score": 50, "critique": "  "}')))
        self.assertIn("schema:maximum", codes(validate_review('{"done": true, "score": 150, "critique": ""}')))
        self.assertIn("done_low_score", codes(validate_review('{"done": true, "score": 20, "critique": ""}')))

    def test_nan_is_not_json(self):
        self.assertFalse(validate_review('{"done": true, "score": NaN, "critique": ""}').chimera_ok)

    def test_repeated_keys(self):
        r = validate_review('{"done": true, "done": false, "score": 50, "critique": "Add the error handling."}')
        self.assertTrue(r.chimera_ok)
        self.assertFalse(r.effective["done"])  # the last one wins, as in Go
        self.assertIn("repeated_key", codes(r))


class GateTests(unittest.TestCase):
    def test_answers(self):
        self.assertTrue(validate_gate('{"use": true}').valid)
        self.assertTrue(validate_gate('{"use": true}').effective)
        self.assertFalse(validate_gate('{"use": false}').effective)

    def test_unreadable_answers_count_as_no(self):
        for text in ('{"use": "yes"}', "Yes", "", '{"use": true}\n{"use": false}', '{"use": 1}'):
            r = validate_gate(text)
            self.assertFalse(r.chimera_ok, text)
            self.assertFalse(r.effective, text)

    def test_lenient_readings(self):
        r = validate_gate('Sure! {"use": true} Hope that helps')
        self.assertTrue(r.chimera_ok)
        self.assertTrue(r.effective)
        self.assertIn("extra_text", codes(r))
        r = validate_gate('{"use": true, "reason": "they asked for a picture"}')
        self.assertTrue(r.effective)
        self.assertIn("schema:additionalProperties", codes(r))
        r = validate_gate("{}")
        self.assertTrue(r.chimera_ok)
        self.assertFalse(r.effective)
        self.assertIn("schema:required", codes(r))


if __name__ == "__main__":
    unittest.main()
