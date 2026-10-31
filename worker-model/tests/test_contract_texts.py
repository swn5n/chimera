"""The contract's frozen texts match the plan's words (docs/hydra-worker-plan.md), where the plan gives them."""
import os
import unittest

from tests import _paths
from contract import texts as T

PLAN_DOC = os.path.join(_paths.REPO, "docs", "hydra-worker-plan.md")


def plan_doc():
    with open(PLAN_DOC, encoding="utf-8") as f:
        return f.read()


@unittest.skipUnless(os.path.exists(PLAN_DOC), "docs/hydra-worker-plan.md not found")
class PlanWordsTests(unittest.TestCase):
    """Texts marked PLAN in texts.py, filled in as the plan's own example (step s2), appear in it word for word."""

    def setUp(self):
        self.doc = plan_doc()

    def assertInPlan(self, text):
        self.assertTrue(text in self.doc, "not in the plan's words: %r" % text)

    def test_mode_rules(self):
        for mode, rules in T.MODE_RULES.items():
            with self.subTest(mode=mode):
                self.assertInPlan(T.fill(rules, sid="s2"))
        self.assertInPlan(T.MODE_SECTION_RESEARCH)

    def test_system_prompt_parts(self):
        self.assertInPlan(T.fill(T.CONTRACT_OPENING, sid="s{i}", n="{n}"))  # the plan writes "step s{i} of {n}"
        self.assertInPlan(T.CONTRACT_PLAN_HEAD)
        self.assertInPlan(T.CONTRACT_USED_BY_NONE)
        self.assertInPlan(T.CONTRACT_JOIN_HEAD)
        self.assertInPlan(T.CONTRACT_HANDOFF)
        self.assertInPlan(T.CONTRACT_PROJECT)
        self.assertInPlan("→ s2. {title} [{kind}] (uses s1): your step, in full below")
        self.assertInPlan(T.CONTRACT_LONE_OPENING.split(". Nobody")[0])

    def test_user_message_parts(self):
        self.assertInPlan(T.fill(T.CONTRACT_USER_STEP, sid="s2"))
        self.assertInPlan(T.fill(T.CONTRACT_USER_DEP_HEAD, name="s1"))
        self.assertInPlan(T.CONTRACT_USER_DEP_FAILED)
        self.assertInPlan(T.CONTRACT_ROUND2_PART.split("\n")[0])
        self.assertInPlan(T.CONTRACT_ROUND2_CRITIQUE.split("\n")[0])

    def test_repair_message(self):
        filled = T.fill(T.CONTRACT_REPAIR, runner="Blender {version}", function="build_s2", line="{L}")
        for line in filled.split("\n"):
            with self.subTest(line=line):
                self.assertInPlan(line)

    def test_opening_keeps_what_the_test_fake_routes_on(self):
        # tests/plugin-network/fake_ollama_hydra.py routes worker requests on this prefix.
        self.assertTrue(T.CONTRACT_OPENING.startswith("You are one worker in Chimera"))
        self.assertTrue(T.CONTRACT_LONE_OPENING.startswith("You are one worker in Chimera"))


class FillTests(unittest.TestCase):
    def test_fill_leaves_literal_braces_and_is_one_pass(self):
        self.assertIn('{"scene": bpy.context.scene', T.fill(T.MODE_BLENDER, sid="s4"))
        self.assertIn("SETTINGS_s4 = {...}", T.fill(T.MODE_BLENDER, sid="s4"))
        self.assertEqual(T.fill("{title}: {summary}", title="{summary}", summary="x"), "{summary}: x")


if __name__ == "__main__":
    unittest.main()
