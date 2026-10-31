import os
import unittest
from collections import Counter

from tests import _paths  # noqa: F401
from helper import evalset
from helper.chimera_port import reaches_gate


class EvalSetTests(unittest.TestCase):
    def setUp(self):
        self.es = evalset.load()

    def test_loads_clean(self):
        self.assertTrue(self.es.version)
        self.assertTrue(self.es.canary.startswith("CHIMERA-HELPER-EVAL-CANARY"))

    def test_every_file_carries_the_canary(self):
        for name in evalset.FILES:
            with open(os.path.join(evalset.EVAL_DIR, name), encoding="utf-8") as f:
                self.assertIn(self.es.canary, f.read(), name)

    def test_covers_every_task_type(self):
        cats = Counter(p["category"] for p in self.es.prompts)
        for c in evalset.CATEGORIES:
            self.assertGreaterEqual(cats[c], 3, c)

    def test_gate_has_both_answers_and_some_that_reach_the_gate(self):
        pairs = self.es.gate_pairs()
        uses = Counter(g["use"] for _, g, _ in pairs)
        self.assertGreaterEqual(uses[True], 5)
        self.assertGreaterEqual(uses[False], 5)
        reached = [g for p, g, h in pairs if reaches_gate(p["prompt"], h)[0]]
        self.assertGreaterEqual(len(reached), len(pairs) // 2)

    def test_reviews_have_both_verdicts(self):
        done = Counter(r["expected"]["done"] for r in self.es.reviews)
        self.assertGreaterEqual(done[True], 3)
        self.assertGreaterEqual(done[False], 3)

    def test_no_duplicate_prompts(self):
        texts = [p["prompt"].strip().lower() for p in self.es.prompts]
        self.assertEqual(len(texts), len(set(texts)))

    def test_real_heads_match_their_manifests(self):
        import hashlib
        for h in self.es.heads.values():
            if h["status"] == "hypothetical":
                continue
            path = os.path.join(os.path.dirname(_paths.HERE), h["source"])
            if not os.path.exists(path):
                self.skipTest("Chimera's repo isn't next to helper-model/")
            with open(path, "rb") as f:
                self.assertEqual(hashlib.sha256(f.read()).hexdigest(), h["source_sha256"],
                                 f"{h['source']} changed since the eval copied it; re-copy and bump the version")


if __name__ == "__main__":
    unittest.main()
