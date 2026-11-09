"""datagen/judges.py: what each judge and the tests writer is shown, and the lenient readers of their replies (the
first JSON object wherever it is, None for anything unusable). Every canned reply here is Claude-written test text
and carries the fixture mark."""
import ast
import json
import re
import unittest

from tests import _paths  # noqa: F401
from datagen import judges as J
from datagen import llm, task
from datagen.common import msgs_tokens
from runner.mock_ollama import MARK

GOAL = "Build a reading corner in Blender: a table with a lamp on it. " + MARK
PLAN = {"title": "Reading corner", "kind": "blender", "summary": "A table with a lamp. " + MARK, "steps": [
    {"id": "s1", "title": "Table", "kind": "blender", "instructions": "Build a wooden table. " + "x" * 700,
     "depends_on": []},
    {"id": "s2", "title": "Lamp", "kind": "blender", "instructions": "Put a brass lamp on the table.",
     "depends_on": ["s1"]},
    {"id": "s3", "title": "Light", "kind": "blender", "instructions": "Light the scene warmly.",
     "depends_on": ["s2"]}]}
CODE_PLAN = {"title": "Word counter", "kind": "code", "summary": "Counts words. " + MARK, "steps": [
    {"id": "s1", "title": "Counting", "kind": "code", "instructions": "Write count_words(text).", "depends_on": []},
    {"id": "s2", "title": "Report", "kind": "code", "instructions": "Write top_words(counts, n).",
     "depends_on": ["s1"]}]}
SCENE = {"objects": [{"name": "chimera_lamp", "type": "MESH"}], "materials": ["chimera_brass"], "collections": [],
         "ctx_keys": ["lamp"]}


class MessagesTests(unittest.TestCase):
    def test_the_scene_judge_sees_the_plan_the_step_the_handoff_and_the_scene(self):
        msgs = J.scene_messages(GOAL, PLAN, 1, {"provides": 'ctx["objects"]["lamp"]', "uses": "the table from s1",
                                                "assumed": ""}, SCENE)
        self.assertEqual([m["role"] for m in msgs], ["system", "user"])
        self.assertEqual(msgs[0]["content"], J.SCENE_SYSTEM)
        user = msgs[1]["content"]
        self.assertTrue(user.startswith("Project: Reading corner\n"))  # no goal since Nov 5 (ScenePromptTests)
        self.assertIn("→ s2. Lamp [blender] (uses s1): the step under review", user)
        self.assertIn("  s3. Light [blender] (uses s2): Light the scene warmly.", user)
        self.assertIn("The step under review, s2: Lamp\nPut a brass lamp on the table.", user)
        self.assertIn('provides: ctx["objects"]["lamp"]\nuses: the table from s1\nassumed: none', user)
        self.assertIn('objects: [{"name": "chimera_lamp", "type": "MESH"}]\nmaterials: ["chimera_brass"]\n'
                      'collections: []\nctx_keys: ["lamp"]', user)
        self.assertTrue(J.scene_messages(GOAL, PLAN, 1, None, {})[1]["content"].endswith("when run alone:\nnothing"))
        s1_line = next(l for l in user.split("\n") if l.startswith("  s1. Table"))
        self.assertLess(len(s1_line), 700)  # another step's instructions are cut
        self.assertTrue(s1_line.endswith("…"))

    def test_the_prose_judge_sees_its_dependencies(self):
        msgs = J.prose_messages(GOAL, PLAN, 2, "## Light\n\nWarm light. " + MARK, {"s2": "## Lamp\n\nBrass. " + MARK,
                                                                                    "s1": None})
        user = msgs[1]["content"]
        self.assertEqual(msgs[0]["content"], J.PROSE_SYSTEM)
        self.assertLess(user.index("From s1:\n(that step failed: nothing)"), user.index("From s2:\n## Lamp"))
        self.assertTrue(user.endswith("The section to grade:\n## Light\n\nWarm light. " + MARK))
        self.assertIn("Its dependencies: none.", J.prose_messages(GOAL, PLAN, 0, "x", {})[1]["content"])

    def test_the_prose_judge_sees_the_handoff_on_its_own(self):
        piece = ("## Light\n\nWarm light. " + MARK + "\n\n```handoff\nprovides: the light section\nuses: s2's lamp\n"
                 "assumed: a 2700 K bulb\n```\n")
        user = J.prose_messages(GOAL, PLAN, 2, piece, {})[1]["content"]
        self.assertTrue(user.endswith("The section to grade:\n## Light\n\nWarm light. " + MARK))
        self.assertIn(J.HANDOFF_HEAD + "\nprovides: the light section\nuses: s2's lamp\nassumed: a 2700 K bulb\n\n"
                      + J.HEADING_LINE + "\n\nThe section to grade:", user)
        self.assertIn(J.HANDOFF_HEAD + "\nnone\n\n", J.prose_messages(GOAL, PLAN, 2, "## Light\n\nx", {})[1]["content"])

    def test_the_prose_judge_is_told_the_heading_is_required(self):
        # real: a judge called the ## heading above a CSV "extra introductory text not required by the step"
        piece = "## Tour dates\n\n```csv\ncity,date\nLyon,2026-05-01\n```\n" + MARK
        user = J.prose_messages(GOAL, PLAN, 2, piece, {})[1]["content"]
        self.assertIn("\n\n" + J.HEADING_LINE + "\n\nThe section to grade:\n## Tour dates\n", user)
        self.assertIn("## heading line", J.HEADING_LINE)
        self.assertIn("not extra text", J.HEADING_LINE)
        self.assertEqual(user.count(J.HEADING_LINE), 1)
        self.assertEqual(J.prose_messages(GOAL, PLAN, 2, piece, {})[0]["content"], J.PROSE_SYSTEM)  # the rubric stays

    def test_the_judges_lines_about_the_format_are_ours(self):
        # A grader's problem can quote them into the next try's notes: a section that repeats them is a teacher note.
        from datagen import hints as H
        user = J.prose_messages(GOAL, PLAN, 2, "## Light\n\nWarm light. " + MARK, {})[1]["content"]
        for line in (J.HEADING_LINE, J.HANDOFF_HEAD):
            self.assertIn(line, user)
            self.assertEqual(H.echoed_note("## Light\n\nWarm light. " + line + " " + MARK), "judge_line", line)
        self.assertIsNone(H.echoed_note("## Light\n\nWarm light from a brass lamp on the table. " + MARK))

    def test_the_tests_writer_is_told_how_the_project_imports(self):
        msgs = J.tests_messages(GOAL, CODE_PLAN, 1, "python-script", {"s1": "```python\ndef count_words(t):\n"
                                                                            "    return {}\n```\n" + MARK})
        system = msgs[0]["content"]
        self.assertIn("`import project` and `from project import *`", system)
        self.assertIn('End with print("tests ok").', system)
        self.assertIn('{"tests": "the Python code"}', system)
        self.assertIn("def count_words(t):", msgs[1]["content"])
        self.assertIn("from src.store import Store", J.tests_messages(GOAL, CODE_PLAN, 1, "files", {})[0]["content"])
        with self.assertRaises(ValueError):
            J.tests_messages(GOAL, CODE_PLAN, 1, "section", {})

    def test_dependencies_share_one_budget(self):
        # a dependency over the old 4,000 is whole when the others leave room: in the labelled set the judge called
        # names past that cut "invented"
        whole = {"s1": "y" * 9000 + MARK, "s2": "z" * 100 + MARK}
        user = J.prose_messages(GOAL, PLAN, 2, "x", whole)[1]["content"]
        self.assertIn("From s1:\n" + whole["s1"] + "\n\nFrom s2:\n" + whole["s2"] + "\n\n", user)
        self.assertIn("From s1:\n" + whole["s1"], J.tests_messages(GOAL, CODE_PLAN, 1, "files", whole)[1]["content"])

    def test_only_the_longest_are_cut(self):  # contract.today.piece_cap, Chimera's pieceCap
        short, long = "s" * 3000 + MARK, "L" * J.DEPS_BUDGET
        text = J._deps_text({"s1": short, "s2": long, "s3": long, "s4": None})
        self.assertIn("From s1:\n" + short + "\n\n", text)
        self.assertIn("From s4:\n(that step failed: nothing)", text)
        got = [re.search(r"From %s:\n(L*…)" % sid, text).group(1) for sid in ("s2", "s3")]
        self.assertEqual([len(g) for g in got], [(J.DEPS_BUDGET - len(short)) // 2] * 2)  # the same length each
        self.assertLessEqual(len(short) + sum(len(g) for g in got), J.DEPS_BUDGET)

    def test_the_largest_prompts_keep_gpt_oss_in_its_fixed_window(self):
        # the worst the budget lets in: seven steps, six dependencies at the validator's largest piece, the section as
        # large, and for a rewrite 12,000 of earlier tests and different failures (DEPS_BUDGET says where it ends)
        piece = "p" * ((task.MAX_TARGET_TOKENS - 64) * 3)
        steps = [{"id": f"s{k + 1}", "title": "T" * 60, "kind": "code", "instructions": "w " * 1250,
                  "depends_on": [f"s{j + 1}" for j in range(6)] if k == 6 else []} for k in range(7)]
        plan = {"title": "P" * 80, "kind": "code", "summary": "S" * 400 + MARK, "steps": steps}
        deps = {f"s{j + 1}": piece for j in range(6)}

        def fails(n):
            return [{"assert": "a" * 400, "error": f"e{k}" * 200, "provides": "p" * 400} for k in range(n)]

        long, smoke = "G" * 8000, "G" * 1500  # the seeds' limit; the smoke runs' longest goal was 1,458
        for msgs in (J.prose_messages(long, plan, 6, piece, deps), J.tests_messages(long, plan, 6, "files", deps),
                     J.tests_rewrite_messages(long, plan, 6, "files", deps, "t" * 13000, fails(5)),
                     J.tests_rewrite_messages(smoke, plan, 6, "files", deps, "t" * 13000, fails(8))):
            self.assertLessEqual(msgs_tokens(msgs) + llm.ROOM, 30000)  # ctx_bucket's 32,768 ends at 30,000
            self.assertEqual(llm.ctx_for("gpt-oss:120b", msgs), llm.FIXED_CTX["gpt-oss:120b"])

    def test_every_judge_and_the_tests_writer_are_told_the_worker_never_saw_the_goal(self):
        # real: the prose judge failed a section for not using a CSV that only the person's task held
        self.assertEqual(J.GOAL_HEAD, "The person's task (the worker never saw it; judge against its request):")
        # the tests writer judges nothing: its own head says to test against the step
        self.assertEqual(J.TESTS_GOAL_HEAD, "The person's task (the worker never saw it; test against its step):")
        deps = {"s1": "```python\ndef count_words(t):\n    return {}\n```\n" + MARK}
        # the scene judge isn't shown the goal at all since Nov 5 (ScenePromptTests)
        for head, msgs in ((J.GOAL_HEAD, J.prose_messages(GOAL, PLAN, 2, "## Light\n\nx", {})),
                           (J.TESTS_GOAL_HEAD, J.tests_messages(GOAL, CODE_PLAN, 1, "files", deps)),
                           (J.TESTS_GOAL_HEAD, J.tests_rewrite_messages(GOAL, CODE_PLAN, 1, "files", deps,
                                                                        "assert 1\n" + MARK, []))):
            user = msgs[1]["content"]
            self.assertTrue(user.startswith(head + "\n" + GOAL + "\n\nProject: "), user[:200])
            self.assertNotIn("The person's task:\n", user)
            self.assertEqual(user.count("The person's task ("), 1)
        for system in (J.SCENE_SYSTEM, J.PROSE_SYSTEM, J.TESTS_SYSTEM):
            self.assertIn("never the person's task", system)

    def test_every_refusal_that_drops_a_step_is_told_to_its_retry(self):
        # task.REFUSED makes a step "none:tests_refused" (the build drops it) only after one retry told why (K4)
        from datagen import task as T
        self.assertEqual(set(J.TESTS_REFUSED), set(T.REFUSED))
        msgs = J.tests_messages(GOAL, CODE_PLAN, 1, "files", {})
        for why, text in J.TESTS_REFUSED.items():
            retry = J.tests_retry_messages(msgs, "assert (\n" + MARK, why)
            self.assertEqual([m["role"] for m in retry], ["system", "user", "assistant", "user"])
            self.assertEqual(retry[3]["content"], text + " " + J.TESTS_REFUSED_TAIL)
            self.assertTrue(text.startswith("These tests ") and len(text) < 240, why)

    def test_the_goal_heads_are_ours(self):
        # A grader's problem or a tests failure can quote them into the next try's notes (hints.echoed_note, K7).
        from datagen import hints as H
        for line in (J.GOAL_HEAD, J.TESTS_GOAL_HEAD):
            self.assertEqual(H.echoed_note("## Light\n\nWarm light. " + line + " " + MARK), "judge_line", line)

    def test_the_rubrics_say_what_an_honest_reply_to_missing_material_is(self):
        for system in (J.SCENE_SYSTEM, J.PROSE_SYSTEM):
            self.assertIn("names material its request doesn't contain", system)
            self.assertIn('"assumed"', system)
            self.assertIn("counts as doing the step", system)
        self.assertIn("leaving the values null", J.PROSE_SYSTEM)

    def test_the_prose_judge_asks_about_claims_and_consistency(self):
        # real: kept sections claimed tests that never ran and prices "taken from" websites, and a route's fuel stops
        # lay past its destination
        for words in ("Tests it says were run", "measurements it says were taken", "a source or a website",
                      "named contacts with phone numbers or emails", "Do its items agree with each other",
                      "no stop past the destination", "totals and counts that add up"):
            self.assertIn(words, J.PROSE_SYSTEM)
        self.assertIn("is never a small problem", J.PROSE_SYSTEM)

    def test_a_mark_covers_an_uncertain_claim_never_a_run(self):
        # As prose_gate reads it: a research step's "(unverified)" may mark a figure it isn't sure of, and the gate's
        # research tell once brought back "Tests were run on an identical workstation (unverified)".
        self.assertIn("In a research step an uncertain claim marked (unverified) is fine", J.PROSE_SYSTEM)
        self.assertIn("no mark makes a test or benchmark it says was run true", J.PROSE_SYSTEM)

    def test_the_scene_judge_is_told_what_the_listing_cant_show(self):
        for words in ("Never fail a piece for something it can't show", "property values, keyframe values",
                      "which material is on which object", "render, output or world settings",
                      "a world shown as the factory world is the one Blender starts with",
                      "empties or placeholders named after that dependency's objects",
                      "one object may be registered under several ctx keys", "sizes, locations, modifiers, animation"):
            self.assertIn(words, J.SCENE_SYSTEM)
        # real: a step asked for EEVEE, its piece set it, and the listing said "the piece didn't change it"
        self.assertNotIn("wasn't set by the piece", J.SCENE_SYSTEM)
        # ctx["values"] (Nov 4): a values step's handoff is seen, not read as a piece that made nothing
        self.assertIn('the keys it registered in ctx["objects"] for other steps and the values it put in '
                      'ctx["values"] for them (the factory cube', J.SCENE_SYSTEM)
        self.assertIn("judge by its ctx keys and values and what the instructions ask", J.SCENE_SYSTEM)

    def test_the_scene_judge_reads_the_gates_labels(self):
        # K8: the engine's two labels, a size before modifiers, a field's cut note (blender_gate writes them)
        for words in ('"(the factory default: the listing can\'t tell whether the piece set it)" may or may not have '
                      'been set by the piece', "one shown as set by the piece was assigned by its code",
                      'an object\'s "base_size", when listed, is its size before modifiers',
                      "a modifier on a dependency's stand-in may leave nothing to show (0 x 0 x 0)",
                      '"(N more not listed)"', '"(and N more not shown)"'):
            self.assertIn(words, J.SCENE_SYSTEM)
        from datagen import blender_gate as G
        for label in (G.ENGINE_UNCHANGED, G.WORLD_UNCHANGED):  # "BLENDER_EEVEE (the factory default: ...)"
            self.assertIn(label.split("(", 1)[1].split(";", 1)[0], J.SCENE_SYSTEM)
        # K8's labels, whether or not blender_gate has them yet
        k8 = G.FACTORY_ENGINE + " (the factory default: the listing can't tell whether the piece set it)"
        self.assertIn(k8.split(" ", 1)[1], J.SCENE_SYSTEM)
        engine_set = getattr(G, "ENGINE_SET", G.FACTORY_ENGINE + " (set by the piece)")
        self.assertIn(engine_set.split("(", 1)[1].rstrip(")"), J.SCENE_SYSTEM)
        self.assertIn(getattr(G, "LISTING_MORE", "(%d more not listed)").replace("%d", "N"), J.SCENE_SYSTEM)

    def test_the_reply_formats_are_unchanged(self):
        self.assertTrue(J.SCENE_SYSTEM.endswith('{"ok": true or false, "why": "one short sentence: what is missing or '
                                                'extra, or what it built"}'))
        self.assertTrue(J.PROSE_SYSTEM.endswith('{"score": 1 to 5, "problems": ["one short line per problem"]} (an '
                                                'empty list when there are none).'))
        self.assertIn('{"tests": "the Python code"}', J.TESTS_SYSTEM.format(how=""))


class TestsWriterTests(unittest.TestCase):
    """What the tests writer is told: the smoke's 13 steps whose tests were at fault broke these rules or had none."""

    def test_the_rules_from_the_smoke(self):
        system = J.tests_messages(GOAL, CODE_PLAN, 1, "python-script", {})[0]["content"]
        for words in ("Test this step's instructions, not the person's whole task",
                      "a requirement of the task that the step doesn't repeat belongs to another step",
                      "An example in the step is one acceptable result, not the exact text to expect",
                      "set sys.argv to a list", "contextlib.redirect_stdout", "catch SystemExit and check its code",
                      "Never start a process (subprocess, os.system, os.fork, os.exec*, multiprocessing",
                      "a layout the step or a dependency's piece gives",
                      "check only that it exists at the step's path, that JSON parses, and the exact values the step "
                      "gives", "Never match a file's source text",
                      "each must hold for a correct piece at the point it runs",
                      "this step, the plan or a dependency's piece writes as code",
                      "Never guess a name or a module: no list of possible names tried in turn"):
            self.assertIn(words, system)
        # in-process CLI tests need sys.argv and main(), which the old rules forbade
        self.assertNotIn("no sys.argv", system)
        self.assertNotIn("don't call main()", system)

    def test_files_mode_is_told_the_steps_modules_are_imported(self):
        how = J.TESTS_HOW["files"]
        self.assertIn("This step's modules that only define things are imported before your code and their public "
                      "names are in scope; step_modules lists them.", how)
        self.assertIn("Import an earlier step's module only by the path the plan or its piece gives", how)
        self.assertNotIn("by its file name", how)  # the old way that made it guess
        self.assertIn(how, J.tests_messages(GOAL, CODE_PLAN, 1, "files", {})[0]["content"])

    def test_files_mode_matches_the_code_gates_prelude(self):
        # The text must say what the harness does: the step's quiet modules star-imported, bound as step_modules.
        from datagen.code_gate import CodeGate
        head = CodeGate._prelude({"tool/parse.py": "", "run.py": ""}, "files", ("parse",))
        self.assertIn("from parse import *", head)
        self.assertIn("step_modules = ", head)
        self.assertNotIn("step_modules", CodeGate._prelude({"tool/parse.py": ""}, "files"))  # the stub's has none


class ScenePromptTests(unittest.TestCase):
    """The scene judge after the fourth smoke's audit (Nov 5): all 4 of its Blender rejections judged what its rubric
    forbids: a sofa's length from the goal, object origins left at (0, 0, 0) by an applied transform, and output
    forms the contract replaces."""

    def test_the_scene_judge_never_sees_the_goal(self):
        # real: "length 2.0 m instead of required 2.2 m": 2.2 m only in the goal, 2.0 m the dependency's value
        msgs = J.scene_messages(GOAL, PLAN, 1, None, SCENE)
        user = msgs[1]["content"]
        self.assertNotIn(GOAL, user)
        self.assertNotIn("Build a reading corner", user)
        self.assertNotIn(J.GOAL_HEAD, user)
        self.assertNotIn("The person's task", user)
        self.assertTrue(user.startswith("Project: Reading corner\n"))
        self.assertEqual(J.scene_messages("another goal " + MARK, PLAN, 1, None, SCENE), msgs)
        self.assertIn("never the person's task", J.SCENE_SYSTEM)  # what the worker saw, still said
        self.assertIn(GOAL, J.prose_messages(GOAL, PLAN, 2, "## Light\n\nx " + MARK, {})[1]["content"])

    def test_the_rubric_says_the_contracts_shape_replaces_an_output_form(self):
        # real: "missing blender_script variable output", "did not produce the required script export"
        for words in ("That shape replaces any form of output a step names for its code",
                      "the code in a string variable, a script returned as text, printed, exported or written to a "
                      ".py file, the steps' scripts combined into one",
                      "never fail a piece for not giving its code in that form: judge what the code built",
                      "saving or rendering once after the last step"):
            self.assertIn(words, J.SCENE_SYSTEM)

    def test_the_rubric_says_what_a_location_is_and_that_numbers_are_measured(self):
        from datagen import blender_gate as G
        for label in (G.WHERE_CENTRE, G.WHERE_BOTTOM, G.WHERE_ORIGIN):
            self.assertIn('"%s"' % label, J.SCENE_SYSTEM)
        for words in ("the centre of the box round an object's geometry in world space and the middle of that box's "
                      "bottom", "which can lie away from its geometry (it stays at the world origin when a transform "
                      "is applied, say)", "measured against the run by other checks before you see it",
                      "never fail a piece for a size, a position or a number"):
            self.assertIn(words, J.SCENE_SYSTEM)

    def test_the_listing_shows_the_location_labels(self):
        from datagen import blender_gate as G
        rec = {"scene": {"objects": [{"name": "chimera_fridge", "type": "MESH", "data": "chimera_fridge"}],
                         "materials": [], "collections": [], "world": "World", "engine": "CYCLES"}, "ctx_live": [],
               "measure": {"objects": [{"n": "chimera_fridge", "t": "MESH", "loc": [0.0, 0.0, 0.0],
                                        "size": [0.8, 0.7, 1.8]}]},
               "geom": {"v": 1, "objects": [{"n": "chimera_fridge", "t": "MESH", "loc": [0.0, 0.0, 0.0],
                                             "lo": [0.8, -0.65, 0.0], "hi": [1.6, 0.05, 1.8], "faces": 6}]}}
        user = J.scene_messages(GOAL, PLAN, 1, None, G._scene(rec))[1]["content"]
        self.assertIn('locations: {"chimera_fridge": {"geometry_centre": [1.2, -0.3, 0.9], "geometry_bottom": '
                      '[1.2, -0.3, 0.0], "origin": [0.0, 0.0, 0.0]}}', user)


def _step(instructions, title="Build kitchen objects"):
    return {"id": "s2", "title": title, "kind": "blender", "instructions": instructions + " " + MARK}


VALUES_STEP = _step("Create a short Python snippet that defines the dimensions. Output the snippet as a string "
                    "variable `blender_script` so it can be later concatenated with other steps.")
EXPORT_STEP = _step("Gather all sections from s1, s2, s3, and produce a single, self-contained Blender 5.x Python "
                    "script. Return the complete script as plain text.", "Export the final script")
PLAIN_STEP = _step("Adds a built-in fridge (0.8 m x 0.7 m x 1.8 m) and positions it at (1.2, -0.3, 0).")


# The stored steps of four overrules before Nov 6 (smoke4's n-blender-0000-01 r1 s2 and n-blender-0000-00 r1 s2, their
# words as stored, cut) and the listing the judge was shown for the kitchen (its stools are 0.28 m into the floor)
SOFA_STEP = _step("Using the variables from s1, add the following objects to the scene:\n1. Sofa: a box with "
                  "dimensions sofa_dim (length) × 0.9 m (width) × 0.8 m (height). Apply a material named "
                  '"SofaTeal" using the sofa_tea RGB colour.', "Create sofa, coffee table, TV stand, floor lamp")
KITCHEN_STEP = _step("Write Blender Python code that:\n2. Creates a rectangular island countertop (2.4 m × 0.9 m "
                     "× 0.92 m) using a plane, applies a light oak material, and places it at the origin.\n3. Adds "
                     "a built-in fridge (0.8 m × 0.7 m × 1.8 m) with a matte white material and positions "
                     "it at (1.2, -0.3, 0).\n4. Adds a stove unit (0.6 m × 0.6 m × 0.9 m) with a black "
                     "metal top material and places it at (1.2, 0.3, 0).\n5. Adds four bar stools (0.45 m × "
                     "0.45 m × 0.78 m) in dark gray, placed symmetrically around the island at (±0.6, ±0.3, "
                     "0.5).")
KITCHEN = {"objects": [["chimera_fridge", "MESH"], ["chimera_island", "MESH"]] +
           [["chimera_stool_%d" % k, "MESH"] for k in range(1, 5)] + [["chimera_stove", "MESH"]]}
FRIDGE = {"objects": [["chimera_fridge", "MESH"]]}  # PLAIN_STEP's listing: its fridge, read by size and by point
STORED_SIZE = "sofa size is wrong (length 2.0 m instead of required 2.2 m)"
STORED_PLACE = "Objects were created but all placed at the origin instead of the specified coordinates"


class OverruleTests(unittest.TestCase):
    """judges.overruled: a scene judge's rejection that rests only on a size, a position or an output form the step
    names, and since Nov 6 (decided) a size or position claim only when the gate's readers read a value for the thing
    it names. The overruled reasons are the stored records' own (smoke-smoke4), the fixture mark beside them; so are
    most of those that stand. PLAIN_STEP gives its fridge three sides and a point, and its listing is the fridge."""

    def check(self, why, step=PLAIN_STEP, ok=False, scene=FRIDGE):
        # the fixture mark goes beside the reason, not in it: its "never" is a fault word (_OTHER) since Nov 6
        return J.overruled({"ok": ok, "why": why, "fixture": MARK}, {"steps": [dict(step, depends_on=[])]}, 0, scene)

    def test_the_stored_rejections_it_overrules(self):
        self.assertEqual(J.OVERRULED, ("size", "position", "output_form"))
        for why, step, kinds in (
                (STORED_SIZE.replace("sofa", "fridge"), PLAIN_STEP, ["size"]),
                (STORED_PLACE, PLAIN_STEP, ["position"]),
                ("objects created but all locations are at (0,0,0) instead of the required positions", PLAIN_STEP,
                 ["position"]),
                ("missing blender_script variable output", VALUES_STEP, ["output_form"]),
                ("did not produce the required script export, only created placeholder objects", EXPORT_STEP,
                 ["output_form"])):
            with self.subTest(why):
                self.assertEqual(self.check(why, step), kinds)

    def test_an_overrule_rests_on_a_measurement(self):
        """Decided Nov 6: a size or position claim is overruled only when the gate's readers read a value for the
        thing it names (asked_sizes' three sides, asked_places' point), and one that names no thing only when every
        object the judge's listing shows is one they read a point for. On the stored steps the sofa's length is
        sofa_dim, a variable, and the kitchen's stools have a "±" point no reader reads: both rejections stand now (4
        of the 7 stored overrules). A single dimension or a relative place is read by nothing (the independent checks'
        cases): they stand too."""
        self.assertEqual(self.check(STORED_SIZE, SOFA_STEP, scene=None), [])
        self.assertEqual(J.readings({"steps": [dict(SOFA_STEP, depends_on=[])]}, 0)["size"], [])
        self.assertEqual(self.check(STORED_PLACE, KITCHEN_STEP, scene=KITCHEN), [])
        self.assertEqual(self.check(STORED_PLACE, KITCHEN_STEP, scene={"objects": KITCHEN["objects"][:2] +
                                                                       KITCHEN["objects"][-1:]}), ["position"])
        self.assertEqual(self.check("the stools are placed at the origin instead of their specified positions",
                                    KITCHEN_STEP, scene=KITCHEN), [])
        self.assertEqual(self.check("the bar stools are too big", KITCHEN_STEP, scene=KITCHEN), ["size"])
        self.assertEqual(self.check("the fridge is placed at the origin instead of its specified position",
                                    KITCHEN_STEP, scene=KITCHEN), ["position"])
        # the same claim with the sofa's three sides given is read, and measured
        self.assertEqual(self.check(STORED_SIZE, _step('Add a sofa (2.2 m x 0.9 m x 0.8 m) named "Sofa".')), ["size"])
        for step, why in (('Add a sofa named "Sofa" 2.2 m long, 0.9 m deep and 0.8 m tall.',
                           "sofa length 3.0 m instead of 2.2 m"),
                          ('Add a sofa named "Sofa" with a length of 2.2 m, a depth of 0.9 m and a height of 0.8 m.',
                           "sofa length 3.0 m instead of 2.2 m"),
                          ('Add a lamp post named "Post", 3 m tall.', "the post's height is wrong"),
                          ('Add a UV sphere named "Ball" with a radius of 0.3 m.', "radius 0.6 m instead of 0.3 m"),
                          ('Add a cylinder named "Pillar" of radius 0.2 m and height 2.5 m.', "the pillar is too short"),
                          ('Add a rug named "Rug" that is 2 m wide.', "the rug is too narrow"),
                          ('Add a cube named "Crate" with 0.5 m sides.', "the crate's size is wrong"),
                          ("Add four bar stools placed symmetrically around the island at (±0.6, ±0.3, 0.5).",
                           "the stools are placed at the origin instead of their specified positions"),
                          ("Put a vase on the side table.", "the vase is wrongly placed"),
                          ("Add a sofa against the back wall and a coffee table 0.5 m in front of it.",
                           "the coffee table's position is wrong"),
                          ("Add a fridge (0.8 m x 0.7 m x 1.8 m) and a stove beside it.",
                           "the stove is placed at the origin"),
                          ("Add a fridge (0.8 m x 0.7 m x 1.8 m) at (1.2, -0.3, 0) and a stove beside it.",
                           "objects are all placed at the origin instead of the specified coordinates")):
            with self.subTest(why):
                self.assertEqual(self.check(why, _step(step), scene={"objects": [["chimera_stove", "MESH"]]}), [])
        # a claim that names no thing needs a listing whose every object a value is read for
        self.assertEqual(self.check(STORED_PLACE, scene=None), [])
        self.assertEqual(self.check(STORED_PLACE, scene={"objects": []}), [])
        self.assertEqual(self.check(STORED_PLACE, scene={"objects": FRIDGE["objects"] + [["chimera_rug", "MESH"]]}),
                         [])
        self.assertEqual(self.check("the dimensions are wrong"), ["size"])
        self.assertEqual(self.check("the dimensions are wrong", scene={"objects": [["chimera_rug", "MESH"]]}), [])
        # an output form needs no reading
        self.assertEqual(self.check("missing blender_script variable output", VALUES_STEP, scene=None),
                         ["output_form"])
        self.assertEqual(J.claims(STORED_SIZE, SOFA_STEP), [("size", [{"sofa"}])])  # its clause's claims name a sofa
        self.assertEqual(J.claims(STORED_PLACE, PLAIN_STEP), [("position", [])])  # "Objects were created": neutral
        self.assertEqual(J.claims("the sofa and the coffee table are too big", PLAIN_STEP),
                         [("size", [{"sofa"}, {"coffee", "table"}])])

    def test_a_claim_on_another_thing_sharing_a_word_stands(self):
        """The second checks (Nov 6): a claim's thing is matched to a reading only when its words are all among the
        reading's and no other object of the listing goes by them; one shared word overruled a claim on a side table
        by the coffee table's size, a cushion by the sofa's, a chair by a desk's, Vase_Right by Vase_Left's point."""
        for step, why, scene in (
                ("Add a coffee table (1.2 m x 0.6 m x 0.4 m) and a side table at the sofa's left end.",
                 "the side table is too big", None),
                ("Build a sofa (2.2 m x 0.9 m x 0.8 m) with two seat cushions.", "the sofa cushions are too big", None),
                ("Add a sofa (2.2 m x 0.9 m x 0.8 m) and a sofa cushion 0.15 m thick.", "the sofa cushion is too thin",
                 None),
                ('Add a desk named "Desk_Main" (1.4 m x 0.7 m x 0.75 m) and a chair named "Chair_Main" 0.9 m tall.',
                 "Chair_Main is too short", None),
                ("Place the coffee table at (0, 1.2, 0) and a side table at the sofa's left end.",
                 "the side table is incorrectly positioned", None),
                ("Place the coffee table at (0, 1.2, 0).", "the coffee table's legs are wrongly placed", None),
                ('Put a vase named "Vase_Left" at (1, 0, 0.8) and a vase named "Vase_Right" beside the sofa.',
                 "Vase_Right is placed at the origin instead of its specified position", None),
                # a shorter name the listing shows on another thing too
                ("Add a coffee table (1.2 m x 0.6 m x 0.4 m) and a side table at the sofa's left end.",
                 "the table is too big", {"objects": [["chimera_coffee_table", "MESH"], ["chimera_side_table", "MESH"]]}),
                # naming no thing, with an object no reading is for (a cushion is no sofa)
                ("Add a sofa (2.2 m x 0.9 m x 0.8 m) and a sofa cushion 0.15 m thick.", "the dimensions are wrong",
                 {"objects": [["chimera_sofa", "MESH"], ["chimera_sofa_cushion", "MESH"]]})):
            with self.subTest(why):
                self.assertEqual(self.check(why, _step(step), scene=scene), [])
        # the read things themselves are overruled, a shorter name too, and a part named after the read thing
        for step, why, scene, kinds in (
                ("Add a coffee table (1.2 m x 0.6 m x 0.4 m) and a side table at the sofa's left end.",
                 "the coffee table is too big", None, ["size"]),
                ("Add a coffee table (1.2 m x 0.6 m x 0.4 m) and a side table at the sofa's left end.",
                 "the table is too big", {"objects": [["chimera_coffee_table", "MESH"]]}, ["size"]),
                ("Add a coffee table (1.2 m x 0.6 m x 0.4 m).", "the coffee table is too big",
                 {"objects": [["chimera_coffee_table_top", "MESH"], ["chimera_coffee_table_leg_1", "MESH"]]}, ["size"]),
                ('Put a vase named "Vase_Left" at (1, 0, 0.8) and a vase named "Vase_Right" beside the sofa.',
                 "Vase_Left is placed at the origin instead of its specified position", None, ["position"]),
                ("Add a sofa (2.2 m x 0.9 m x 0.8 m).", "the dimensions are wrong",
                 {"objects": [["chimera_sofa", "MESH"]]}, ["size"])):
            with self.subTest(why=why, scene=scene):
                self.assertEqual(self.check(why, _step(step), scene=scene), kinds)

    def test_an_output_form_counts_only_on_a_step_that_names_one(self):
        self.assertEqual(self.check("missing blender_script variable output", PLAIN_STEP), [])
        self.assertEqual(self.check("did not produce the required script export", PLAIN_STEP), [])
        self.assertEqual(J.names_output_form(VALUES_STEP), "Output the snippet")
        self.assertTrue(J.names_output_form(EXPORT_STEP))
        self.assertIsNone(J.names_output_form(PLAIN_STEP))
        self.assertIsNone(J.names_output_form(_step("Add a lamp that outputs 800 W of warm light.")))

    def test_the_stored_rejections_that_stand(self):
        for why in ("Materials were created but not assigned to any objects (no placeholders or assignments for "
                    "sofa, coffee_table, tv_stand)",
                    "Missing the required variable definitions and the `blender_script` string; only the engine was "
                    "set",
                    "It changed the scene engine to EEVEE and added an unexpected 'settings' key instead of defining "
                    "the required variables (including a Cycles flag) in the blender_script",
                    "Beam_Top created without the required Solidify, Bevel, Subdivision Surface modifiers (and uses "
                    "wrong default dimensions)",
                    "missing verification snippet; no output or objects created as required",
                    "missing Arch_Mirror object; only Arch_Array was created",
                    "It created extra objects (Arches, Beam_Top, Plank_Left, Plank_Right) that belong to other steps "
                    "and omitted required render settings",
                    "missing camera focal length and light power/soft-shadow settings",
                    "Missing frame range/fps settings and incorrectly switched render engine to EEVEE, which is "
                    "outside its animation step"):
            for step in (PLAIN_STEP, VALUES_STEP, EXPORT_STEP):
                with self.subTest(why=why, step=step["title"]):
                    self.assertEqual(self.check(why, step), [])

    def test_anything_else_in_the_reason_keeps_the_rejection(self):
        for why in ("the sofa is 2.0 m instead of 2.2 m and the lamp is missing",
                    "4 instead of 2 stools",
                    "only 3 stools instead of 4",
                    "the table is 0 x 0 x 0: it made nothing",
                    "the key light's power is 500 W instead of 600 W",
                    "the lens is 50 instead of 35",
                    "all placed at the origin, and the fridge belongs to another step",
                    "wrong objects created"):
            with self.subTest(why):
                self.assertEqual(self.check(why), [])
        self.assertEqual(self.check("sofa size is wrong (2.0 m instead of 2.2 m)", ok=True), [])  # an acceptance
        self.assertEqual(J.overruled(None, {"steps": [PLAIN_STEP]}, 0, FRIDGE), [])
        self.assertEqual(J.overruled({"ok": False, "why": ""}, {"steps": [PLAIN_STEP]}, 0, FRIDGE), [])

    def test_a_claim_beside_a_fault_in_other_words_keeps_the_rejection(self):
        """The independent checks (Nov 6): a stored overruled claim with a missing thing, a count in words, a turn, a
        float, an overlap, a relative place or a shape after it was overruled, since _OTHER knew none of those words
        (and its n't never matched inside "doesn't"). Each stands now; the claim alone is still overruled."""
        stored = "Objects were created but all placed at the origin instead of the specified coordinates"
        size = "fridge size is wrong (length 2.0 m instead of required 0.8 m)"  # PLAIN_STEP's, read
        for why in (stored + "; the stove was never created", stored + ", and the stools were omitted",
                    stored + " and it doesn't create the fridge", stored + ", with two stools rather than four",
                    stored + "; the cushions were forgotten", stored + " and the stools were left out",
                    size + " and the coffee table was never built", size + "; it omits the coffee table",
                    "The stools are placed at the origin and rotated sideways",
                    "The table is placed at the origin upside down",
                    "The stools are placed at the origin and float above the floor",
                    "The stools are wrongly positioned and overlap the island",
                    "The vase is placed at the origin rather than on top of the side table",
                    "The stools are placed at the origin; the fridge is created as a cylinder",
                    "The sofa is too big and the vase is gone",
                    "The shelf is too short and the books are scattered across the floor"):
            with self.subTest(why):
                self.assertEqual(self.check(why), [])
        self.assertTrue(J._OTHER.search("it doesn't"))
        self.assertTrue(J._OTHER.search("it didn\u2019t"))
        self.assertEqual(self.check(stored), ["position"])
        self.assertEqual(self.check(size), ["size"])

    def test_two_kinds_at_once(self):
        self.assertEqual(self.check("the fridge's height is wrong and it is placed at the origin instead of its "
                                    "specified position"), ["size", "position"])


class ListingTests(unittest.TestCase):
    OBJ = {"name": "chimera_rock_000", "type": "MESH", "size": [0.41, 0.39, 0.27], "location": [1.2, -5.6, 0.1],
           "modifiers": ["BEVEL"]}

    def scene(self, n, keys=60):
        return {"objects": [dict(self.OBJ, name=f"chimera_rock_{k:03d}") for k in range(n)],
                "materials": ["chimera_rock_mat"], "collections": ["Rocks"],
                "ctx_keys": [f"rock_{k}" for k in range(keys)], "world": "World (factory) " + MARK,
                "engine": "BLENDER_EEVEE", "actions": []}

    def test_the_lines_and_their_order(self):
        got = J._listing(self.scene(2, 2)).split("\n")
        self.assertEqual([line.split(":")[0] for line in got],
                         ["objects", "materials", "collections", "ctx_keys", "actions", "engine", "world"])
        self.assertEqual(json.loads(got[0].split(": ", 1)[1])[1]["name"], "chimera_rock_001")
        self.assertNotIn("more not shown", "\n".join(got))
        self.assertEqual(J._listing({}), "nothing")
        self.assertEqual(J._listing(None), "nothing")

    def test_the_values_a_piece_handed_on_come_after_its_ctx_keys(self):
        """blender_gate._scene lists ctx["values"] keys ("ctx_values", keys only) only when there are some, so a
        listing without them reads byte for byte as before Nov 4; with them, they come right after the ctx keys."""
        self.assertEqual(J._FIRST, ("objects", "materials", "collections", "ctx_keys", "ctx_values"))
        from datagen import blender_gate as G
        rec = {"scene": {"objects": [], "materials": [], "collections": [], "world": "World",
                         "engine": "BLENDER_EEVEE"}, "ctx_live": []}
        before = J._listing(G._scene(rec))
        self.assertNotIn("ctx_values", before)
        self.assertEqual(J._listing(G._scene(dict(rec, ctx_values=[]))), before)
        got = J._listing(G._scene(dict(rec, ctx_values=["sofa_depth", "sofa_width"]))).split("\n")
        self.assertEqual([line.split(":")[0] for line in got],
                         ["objects", "materials", "collections", "ctx_keys", "ctx_values", "engine", "world"])
        self.assertEqual(got[4], 'ctx_values: ["sofa_depth", "sofa_width"]')
        self.assertEqual(J._listing(dict(self.scene(2, 2), ctx_values=["w"])).split("\n")[4], 'ctx_values: ["w"]')

    def test_a_scattered_scene_keeps_its_ctx_keys(self):
        got = J._listing(self.scene(400))
        self.assertLessEqual(len(got), J._SCENE_CUT)
        objects = next(line for line in got.split("\n") if line.startswith("objects: "))
        shown = json.loads(objects.split(": ", 1)[1].rsplit(" (and ", 1)[0])
        self.assertEqual([o["name"] for o in shown], [f"chimera_rock_{k:03d}" for k in range(len(shown))])
        self.assertTrue(objects.endswith(f" (and {400 - len(shown)} more not shown)"))
        self.assertGreater(len(shown), 40)
        self.assertIn('ctx_keys: ["rock_0", ' + ", ".join(f'"rock_{k}"' for k in range(1, 60)) + "]", got)
        self.assertIn('engine: "BLENDER_EEVEE"', got)
        # what the judge is told about a cut list is what the listing writes
        self.assertIn('"(and N more not shown)"', J.SCENE_SYSTEM)

    def test_the_longest_list_is_cut_first(self):
        s = {"objects": [["chimera_a", "MESH"]] * 5, "materials": [f"chimera_m{k}" for k in range(500)],
             "ctx_keys": ["a"]}
        got = J._listing(s, cut=600).split("\n")
        self.assertEqual(got[0], 'objects: ' + json.dumps([["chimera_a", "MESH"]] * 5))
        self.assertTrue(got[1].startswith('materials: ["chimera_m0", "chimera_m1"'))
        self.assertRegex(got[1], r"\(and \d+ more not shown\)$")
        self.assertEqual(got[2], 'ctx_keys: ["a"]')
        self.assertLessEqual(len("\n".join(got)), 600)

    def test_what_cant_be_shortened_is_cut(self):
        got = J._listing({"world": "W" * 20000 + MARK}, cut=500)
        self.assertEqual(len(got), 500)
        self.assertTrue(got.endswith("…"))

    def test_the_judges_messages_stay_well_inside_its_context(self):
        plan = {"title": "T" * 80, "summary": "S" * 500 + MARK, "steps": [
            {"id": f"s{k}", "title": "Step", "kind": "blender", "instructions": "I" * 2500, "depends_on": []}
            for k in range(7)]}
        msgs = J.scene_messages("G" * 8000 + MARK, plan, 3, {"provides": "p" * 800, "uses": "u" * 400,
                                                            "assumed": "a" * 600}, self.scene(1000))
        self.assertLess(msgs_tokens(msgs), 32768 // 2)  # gpt-oss:120b runs at a fixed 32,768 (llm.FIXED_CTX)
        self.assertIn("more not shown)", msgs[1]["content"])


class RewriteTests(unittest.TestCase):
    OLD = MARK + "\nfrom report import top_words\nassert top_words({'a': 2, 'b': 1}, 1) == [('a', 2)]\n"
    DEPS = {"s1": "File: count.py\n```python\ndef count_words(t):\n    return {}\n```\n" + MARK}

    def msgs(self, failures, old=None, mode="files"):
        return J.tests_rewrite_messages(GOAL, CODE_PLAN, 1, mode, self.DEPS, self.OLD if old is None else old, failures)

    def test_the_same_step_then_the_old_tests_then_the_failures(self):
        first = J.tests_messages(GOAL, CODE_PLAN, 1, "files", self.DEPS)
        msgs = self.msgs([{"assert": "assert top_words({'a': 2, 'b': 1}, 1) == [('a', 2)]",
                           "error": "AssertionError " + MARK, "provides": ["top_words(counts, n)"]}])
        self.assertEqual(msgs[0], first[0])
        user = msgs[1]["content"]
        self.assertTrue(user.startswith(first[1]["content"] + "\n\nYour earlier tests for this step:\n```python\n"
                                        + self.OLD.rstrip() + "\n```\n\n"))
        self.assertIn("\n- candidate 1: the failing assert: assert top_words({'a': 2, 'b': 1}, 1) == [('a', 2)]; "
                      "the error: AssertionError " + MARK + "; its handoff provides: top_words(counts, n)\n", user)
        self.assertIn("the candidates' code isn't shown, and a candidate may be wrong", user)
        self.assertIn("Don't fit the tests to a candidate. The rules above still hold.", user)
        self.assertTrue(user.endswith("Reply with the whole corrected tests in the same JSON."))
        self.assertEqual(self.msgs([], mode="python-script")[0]["content"],
                         J.tests_messages(GOAL, CODE_PLAN, 1, "python-script", {})[0]["content"])
        with self.assertRaises(ValueError):
            self.msgs([], mode="section")

    def test_only_the_assert_the_error_and_the_provides_names(self):
        code = "def top_words(counts, n):\n    return sorted(counts.items())[:n]  # the candidate's own " + MARK
        user = self.msgs([{"assert": "", "error": "ModuleNotFoundError: No module named 'report'",
                           "provides": "top_words", "code": code, "content": code}])[1]["content"]
        self.assertNotIn("sorted(counts.items())", user)
        self.assertIn("- candidate 1: the error: ModuleNotFoundError: No module named 'report'; its handoff provides: "
                      "top_words", user)  # no assert line known: the error says what failed

    def test_the_same_failure_once(self):
        same = {"assert": "assert top_words({}, 1) == []", "error": "AssertionError", "provides": "top_words"}
        user = self.msgs([same, {"error": "NameError: name 'x' is not defined " + MARK}, dict(same)])[1]["content"]
        self.assertIn("- candidates 1 and 3: the failing assert: assert top_words({}, 1) == []; the error: "
                      "AssertionError; their handoff provides: top_words", user)
        self.assertIn("- candidate 2: the error: NameError: name 'x' is not defined " + MARK +
                      "; its handoff provides: none", user)
        self.assertIn("- (no failure was recorded)", self.msgs([])[1]["content"])

    def test_long_failures_are_one_cut_line(self):
        user = self.msgs([{"assert": "assert f(\n    1,\n    2) == 3", "error": "E" * 900 + MARK,
                           "provides": ["a", None, "", "b"]}])[1]["content"]
        line = next(x for x in user.split("\n") if x.startswith("- candidate 1:"))
        self.assertIn("the failing assert: assert f( 1, 2) == 3;", line)
        self.assertIn("E" * 200 + "…; its handoff provides: a, b", line)
        self.assertNotIn("E" * 300, line)

    def test_old_tests_with_a_fence_inside(self):
        old = MARK + "\ns = '````'\nassert len(s) == 4\n"
        user = self.msgs([], old=old)[1]["content"]
        self.assertIn("\n`````python\n" + old.rstrip() + "\n`````\n", user)

    def test_the_rewrites_reply_reads_like_the_first(self):
        reply = json.dumps({"tests": MARK + "\nassert top_words({'a': 2, 'b': 1}, 1) == [('a', 2)]\n"})
        self.assertEqual(J.parse_tests(reply), json.loads(reply)["tests"] + 'print("tests ok")\n')


class SceneReplyTests(unittest.TestCase):
    def test_plain_and_wrapped_replies(self):
        want = {"ok": True, "why": "It built the lamp. " + MARK}
        for reply in ('{"ok": true, "why": "It built the lamp. %s"}' % MARK,
                      'Verdict:\n```json\n{"ok": true, "why": "It built the lamp. %s"}\n```' % MARK,
                      '  {"ok": "yes", "why": "It built the lamp. %s"} trailing words' % MARK):
            self.assertEqual(J.parse_scene(reply), want, reply)
        self.assertEqual(J.parse_scene('{"ok": false, "why": "No lamp. %s"}' % MARK)["ok"], False)
        self.assertEqual(J.parse_scene('{"ok": "false"} ' + MARK), {"ok": False, "why": ""})

    def test_the_first_object_wins(self):
        got = J.parse_scene('{"ok": false, "why": "a"} {"ok": true, "why": "b"} ' + MARK)
        self.assertEqual(got, {"ok": False, "why": "a"})

    def test_unusable_replies(self):
        for reply in ("", "Looks fine to me. " + MARK, '{"why": "no verdict %s"}' % MARK,
                      '{"ok": "maybe", "why": "%s"}' % MARK, '["ok", true] ' + MARK, '{"ok": tru ' + MARK, None):
            self.assertIsNone(J.parse_scene(reply), reply)


class ProseReplyTests(unittest.TestCase):
    def test_scores_and_problems(self):
        self.assertEqual(J.parse_prose('{"score": 4, "problems": ["Repeats s1. %s"]}' % MARK),
                         {"score": 4, "problems": ["Repeats s1. " + MARK]})
        self.assertEqual(J.parse_prose('{"score": "5", "problems": []} ' + MARK), {"score": 5, "problems": []})
        self.assertEqual(J.parse_prose('{"score": 4.0} ' + MARK), {"score": 4, "problems": []})
        self.assertEqual(J.parse_prose('{"score": 3.5, "problems": "Padded. %s"}' % MARK),
                         {"score": 3.5, "problems": ["Padded. " + MARK]})
        self.assertEqual(J.parse_prose('Here: {"rating": "4/5", "issues": ["", null]} ' + MARK)["score"], 4)

    def test_unusable_scores(self):
        for reply in ('{"score": 0} ', '{"score": 6} ', '{"score": true} ', '{"score": "four"} ',
                      '{"problems": []} ', "Score: 4 ", '{"score": null} '):
            self.assertIsNone(J.parse_prose(reply + MARK), reply)

    def test_kept_at_four(self):
        self.assertTrue(J.prose_kept({"score": 4, "problems": []}))
        self.assertTrue(J.prose_kept({"score": 5, "problems": []}))
        self.assertFalse(J.prose_kept({"score": 3.5, "problems": []}))
        self.assertFalse(J.prose_kept(None))

    def test_strict_keeps_only_five(self):
        self.assertTrue(J.prose_kept({"score": 5, "problems": []}, strict=True))
        for score in (4, 4.5, 3):
            self.assertFalse(J.prose_kept({"score": score, "problems": []}, strict=True), score)
            self.assertEqual(J.prose_kept({"score": score, "problems": []}), score >= 4)
        self.assertFalse(J.prose_kept(None, strict=True))
        self.assertEqual(J.PROSE_STRICT, 5)


class TestsReplyTests(unittest.TestCase):
    CODE = MARK + "\nassert top_words({'a': 1}, 1) == [('a', 1)]\n"

    def test_from_json(self):
        got = J.parse_tests(json.dumps({"tests": self.CODE}))
        self.assertEqual(got, self.CODE + 'print("tests ok")\n')
        ast.parse(got)
        fenced = json.dumps({"tests": "```python\n" + self.CODE + "print('tests ok')\n```"})
        self.assertEqual(J.parse_tests(fenced), self.CODE + "print('tests ok')\n")  # not added twice

    def test_from_a_block_or_bare_code(self):
        self.assertEqual(J.parse_tests("Here are the tests:\n```python\n" + self.CODE + "```\nDone."),
                         self.CODE + 'print("tests ok")\n')
        self.assertEqual(J.parse_tests(self.CODE), self.CODE + 'print("tests ok")\n')
        with_dict = MARK + "\ncounts = {\"a\": 1}\nassert top_words(counts, 1) == [(\"a\", 1)]\n"
        self.assertEqual(J.parse_tests("```python\n" + with_dict + "```"), with_dict + 'print("tests ok")\n')

    def test_unusable_tests(self):
        for reply in (json.dumps({"tests": ""}), json.dumps({"tests": MARK + "\nprint('no asserts')\n"}),
                      json.dumps({"tests": MARK + "\nassert (\n"}), "No tests for this step. " + MARK, "",
                      json.dumps({"note": "nothing to test " + MARK})):
            self.assertIsNone(J.parse_tests(reply), reply)

    def test_asserts_the_tests_never_reach_dont_count(self):
        uncalled = MARK + "\nfrom tool.totals import total\n\n\ndef test_total():\n    assert total('1,2') == 3\n"
        for code in (uncalled, uncalled + "\nprint('tests ok')\n",
                     MARK + "\nclass TestTotal:\n    def test_it(self):\n        assert total('1') == 1\n",
                     MARK + "\ndef check():\n    assert total('1') == 1\n\n\nrun = check\n",  # never called by name
                     MARK + "\nif False:\n    def t():\n        assert total('1') == 1\n"):
            self.assertIsNone(J.parse_tests(json.dumps({"tests": code})), code)

    def test_asserts_reached_from_the_module(self):
        for code in (MARK + "\ndef test_total():\n    assert total('1,2') == 3\n\n\ntest_total()\n",
                     MARK + "\ndef a():\n    assert total('1') == 1\n\n\ndef b():\n    a()\n\n\nb()\n",
                     MARK + "\nfor line, want in [('1', 1)]:\n    assert total(line) == want\n",
                     MARK + "\ntry:\n    total(None)\n    assert False, 'no error'\nexcept TypeError:\n    pass\n",
                     MARK + "\nwith open('t.txt', 'w') as f:\n    assert f.write('1') == 1\n",
                     MARK + "\nif total('1') == 1:\n    assert total('2') == 2\n"):
            self.assertEqual(J.parse_tests(json.dumps({"tests": code})), code + 'print("tests ok")\n', code)
        self.assertEqual(J.reached_asserts(ast.parse("assert 1\nassert 2\ndef f():\n    assert 3\nf()\nf()\n")), 3)


def _tests(body):
    return json.dumps({"tests": MARK + "\n" + body})


class TestsRefusedTests(unittest.TestCase):
    """Tests the sandbox can't run, or that guess names, are refused (parse_tests None) with a reason. The guesses are
    the shapes the smoke's tests had."""
    OK = "\nassert top_words({'a': 1}, 1) == [('a', 1)]\n"

    def refused(self, body, why):
        reply = _tests(body)
        self.assertIsNone(J.parse_tests(reply), body)
        self.assertEqual(J.parse_tests_why(reply), why, body)

    def kept(self, body):
        reply = _tests(body)
        self.assertIsNotNone(J.parse_tests(reply), body)
        self.assertIsNone(J.parse_tests_why(reply), body)

    def test_starting_a_process(self):
        # real: a subprocess test of `python -m tasktimer` failed on the stub and every candidate with PermissionError
        for body in ("import subprocess\nr = subprocess.run(['python3', '-m', 'tool'])",
                     "from subprocess import run, PIPE", "import subprocess as sp", "import multiprocessing.pool",
                     "from multiprocessing import Process", "import os\nos.system('ls')", "import os\nos.fork()",
                     "import os\nos.execv('/bin/ls', ['ls'])", "import os\nos.spawnl(os.P_WAIT, 'ls')",
                     "import os\nos.popen('ls')", "from os import system", "from os import execvp",
                     "p = Popen(['ls'])", "import importlib\nimportlib.import_module('subprocess')",
                     "sp = __import__('subprocess.run')",
                     "from concurrent.futures import ProcessPoolExecutor",
                     "import concurrent.futures\nconcurrent.futures.ProcessPoolExecutor()",
                     "import asyncio\nasyncio.create_subprocess_exec('ls')"):
            self.refused(body + self.OK, "subprocess")

    def test_in_process_cli_tests_are_fine(self):
        self.kept("import sys, io, contextlib, os\nsys.argv = ['tool', 'add', 'milk']\nbuf = io.StringIO()\n"
                  "try:\n    with contextlib.redirect_stdout(buf):\n        main()\nexcept SystemExit as e:\n"
                  "    assert e.code in (0, None), e.code\nassert 'milk' in buf.getvalue()\n"
                  "assert os.path.exists('tasks.json')\nassert 'subprocess' not in buf.getvalue()\n")
        self.kept("import os\nfor f in os.listdir('.'):\n    assert not f.endswith('.tmp')\n" + self.OK)

    def test_guessing_names(self):
        for body in (
                # real: a list of possible names, the first found kept
                "_possible = ['pull_and_tag', 'get_pull_cmd', 'PULL_CMD']\n_f = None\nfor _n in _possible:\n"
                "    if _n in globals():\n        _f = globals()[_n]\n        break\nassert _f is not None\n",
                "for attr in ('main', 'cli', 'run'):\n    if hasattr(mod, attr):\n        fn = getattr(mod, attr)\n"
                "        break\nassert fn\n",
                "def entry():\n    for name in ('main', 'run'):\n        if hasattr(mod, name):\n"
                "            return getattr(mod, name)\nassert entry()\n",
                "found = None\nfor n in ['cmd_add', 'add']:\n    if hasattr(mod, n):\n        found = getattr(mod, n)\n"
                "assert found\n",
                "found = []\nfor n in ['cmd_add', 'add']:\n    if hasattr(mod, n):\n        found.append(n)\nassert found\n",
                "for m in ['export', 'cmd_export']:\n    try:\n        mod = importlib.import_module(m)\n        break\n"
                "    except ImportError:\n        pass\nassert mod\n",
                "fns = [getattr(mod, n) for n in ('main', 'run') if hasattr(mod, n)]\nassert fns\n",
                "fn = next(getattr(mod, n) for n in ['main', 'run'] if hasattr(mod, n))\nassert fn\n",
                # real: a search of globals() by part of a name
                "cands = []\nfor name, obj in list(globals().items()):\n    if callable(obj) and 'docx' in name.lower():\n"
                "        cands.append(obj)\nassert cands\n",
                "fs = [obj for name, obj in globals().items() if callable(obj) and 'excel' in name.lower()]\nassert fs\n",
                "fs = [n for n in dir(mod) if n.startswith('cmd_')]\nassert fs\n",
                "fs = {k: v for k, v in vars(mod).items() if 'export' in k}\nassert fs\n",
                "import inspect\nfs = [f for n, f in inspect.getmembers(mod) if n.endswith('_cmd')]\nassert fs\n",
                # real: a search of the folder for the module that has the name
                "import os, importlib\nfn = None\nfor f in os.listdir('.'):\n    if f.endswith('.py'):\n"
                "        m = importlib.import_module(f[:-3])\n        if hasattr(m, 'cmd_import'):\n"
                "            fn = m.cmd_import\nassert fn\n",
                "import glob\nfor p in sorted(glob.glob('*.py')):\n    m = __import__(p[:-3])\nassert m\n",
                # real: an if/elif chain trying two names on one module
                "if hasattr(report, 'main'):\n    fn = report.main\nelif hasattr(report, 'run'):\n    fn = report.run\n"
                "else:\n    raise AssertionError('no entry')\nassert fn\n",
                "fn = getattr(mod, 'main', None) or getattr(mod, 'run', None)\nassert fn\n",
                "if 'load_csv' in globals():\n    f = load_csv\nelif 'read_csv' in globals():\n    f = read_csv\nassert f\n",
                # real: a module guessed three ways
                "try:\n    from export import cmd_export\nexcept ImportError:\n    try:\n        from cmd_export import "
                "cmd_export\n    except ImportError:\n        from contactmgr import cmd_export\nassert cmd_export\n"):
            self.refused(body, "name_guess")

    def test_what_isnt_a_guess(self):
        for body in (
                # every name of a list must exist: a check, not a guess
                "for name in ['load_contacts', 'save_contacts']:\n    if not hasattr(data_utils, name):\n"
                "        raise AssertionError(name)\n",
                "for name in ['load', 'save']:\n    assert callable(getattr(store, name)), name\n",
                "assert all(hasattr(store, n) for n in ('load', 'save'))\n",
                "if hasattr(store, 'load') and hasattr(store, 'save'):\n    pass\nassert store.load() == []\n",
                "if hasattr(mod, 'main'):\n    mod.main()\nassert mod.main\n",
                # the same module by its path or its file name
                "try:\n    from src.store import Store\nexcept ImportError:\n    from store import Store\nassert Store()\n",
                "try:\n    import data_utils\nexcept ImportError as e:\n    raise AssertionError(e)\n"
                "assert data_utils.load_contacts() == []\n",
                "import os\nfor f in ['package.json', 'README.md']:\n    assert os.path.exists(f), f\n",
                "for cmd in ['start', 'stop']:\n    assert cmd in HELP\n",
                "for k, v in counts.items():\n    if k == 'a':\n        assert v == 1\n"):
            self.kept(body + self.OK)

    def test_why_for_each_unusable_reply(self):
        cases = [(json.dumps({"tests": ""}), "no_tests"), (json.dumps({"note": "nothing to test " + MARK}), "no_tests"),
                 ("No tests for this step. " + MARK, "no_tests"), ("", "no_tests"), (None, "no_tests"),
                 (json.dumps({"tests": MARK + "\nassert (\n"}), "tests_syntax"),
                 ("Here:\n```python\n" + MARK + "\nassert (\n```", "tests_syntax"),
                 (json.dumps({"tests": MARK + "\nprint('no asserts')\n"}), "no_asserts"),
                 (json.dumps({"tests": MARK + "\ndef test_a():\n    assert top_words({}, 1) == []\n"}), "no_asserts")]
        for reply, why in cases:
            self.assertIsNone(J.parse_tests(reply), reply)
            self.assertEqual(J.parse_tests_why(reply), why, reply)
        good = json.dumps({"tests": MARK + self.OK})
        self.assertIsNone(J.parse_tests_why(good))
        self.assertIsNotNone(J.parse_tests(good))
        bare_with_a_dict = MARK + "\ncounts = {\"a\": 1}\nassert top_words(counts, 1) == [(\"a\", 1)]\n"
        self.assertIsNone(J.parse_tests_why(bare_with_a_dict))  # an object in bare code isn't the reply's JSON


class FirstJsonTests(unittest.TestCase):
    def test_first_object(self):
        self.assertEqual(J.first_json(' {"a": 1} '), {"a": 1})
        self.assertEqual(J.first_json('text {"a": {"b": 2}} and {"c": 3}'), {"a": {"b": 2}})
        self.assertEqual(J.first_json('{broken {"a": 1}'), {"a": 1})
        self.assertIsNone(J.first_json("[1, 2]"))
        self.assertIsNone(J.first_json("no json"))

    def test_judges_run_at_temperature_0_in_json(self):
        self.assertEqual((J.FMT, J.OPTIONS, J.PROSE_KEEP), ("json", {"temperature": 0}, 4))


if __name__ == "__main__":
    unittest.main()
