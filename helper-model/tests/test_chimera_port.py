"""The Python ports of Chimera's Go code, against values worked out from the Go source."""
import unittest

from tests import _paths  # noqa: F401
from helper import chimera_port as cp
from helper import prompts


COMFY = {"id": "comfyui-image", "name": "ComfyUI image generation",
         "summary": "Generates a picture from a text description with the Stable Diffusion / SDXL / Flux checkpoint loaded in ComfyUI on this computer.",
         "when_to_use": "Someone asks to generate, make, draw, render or create an image, picture, illustration, concept art, wallpaper or photo of something from a description.",
         "tags": ["generate", "image", "picture", "draw", "render", "illustration", "concept art", "text to image", "stable diffusion", "sdxl", "flux"],
         "task_kinds": ["image-generation"], "accepts": []}


class PortTests(unittest.TestCase):
    def test_truncate_counts_bytes_and_keeps_characters_whole(self):
        self.assertEqual(cp.truncate("hello", 5), "hello")
        self.assertEqual(cp.truncate("hello", 3), "hel\n…(cut)")
        self.assertEqual(cp.truncate("aé", 2), "a\n…(cut)")  # é is 2 bytes: don't cut inside it

    def test_sizes(self):
        self.assertEqual(cp.estimate_tokens("abcdef"), 66)
        self.assertEqual(cp.ctx_bucket(5000), 8192)
        self.assertEqual(cp.ctx_bucket(7001), 32768)
        self.assertEqual(cp.ctx_bucket(30001), 65536)
        self.assertEqual(cp.ctx_bucket(70000), 131072)
        self.assertEqual(cp.ctx_bucket(70000, 40960), 40960)

    def test_go_trim_space_keeps_what_go_keeps(self):
        self.assertEqual(cp.go_trim_space("  x 　"), "x")
        self.assertEqual(cp.go_trim_space("\x1cx"), "\x1cx")

    def test_extract_json(self):
        ok, v, used = cp.extract_json('noise {"use": true} noise', cp.GATE_SPEC)
        self.assertTrue(ok)
        self.assertTrue(v["use"])
        self.assertEqual(used, '{"use": true}')
        self.assertEqual(cp.extract_json("null", cp.GATE_SPEC)[:2], (True, {"use": False}))
        self.assertFalse(cp.extract_json("[true]", cp.GATE_SPEC)[0])
        ok, v, _ = cp.extract_json('{"title": "x", "title": null}', cp.PLAN_SPEC)
        self.assertEqual(v["title"], "x")  # null leaves a string as it was

    def test_clean_plan_drops_forward_and_unknown_deps(self):
        ok, p, _ = cp.extract_json('{"title":"t","kind":"code","summary":"s","steps":['
                                   '{"id":"a","title":"A","kind":"code","instructions":"i","depends_on":["b","zz"]},'
                                   '{"id":"b","title":"B","kind":"oops","instructions":"i","depends_on":["a","a"]}]}', cp.PLAN_SPEC)
        c = cp.clean_plan(p)
        self.assertEqual(c["steps"][0]["depends_on"], [])
        self.assertEqual(c["steps"][1]["depends_on"], ["a", "a"])
        self.assertEqual(c["steps"][1]["kind"], "code")
        self.assertEqual({s["status"] for s in c["steps"]}, {"waiting"})

    def test_tokenize_and_terms(self):
        self.assertEqual(cp.tokenize("Make me an image of a WOLF, please!"), ["image", "wolf"])
        self.assertEqual(cp.plugin_terms("do it"), [])
        self.assertEqual(cp.plugin_terms("I need a picture", with_input=True), [])

    def test_relevance_worked_example(self):
        # "generate": not a substring of the name ("generation"), so the tags (2.5); "image":
        # in the name (3); "wolf": nowhere. (2.5 + 3) / 6 = 0.9166 -> round2 -> 0.92
        terms = cp.plugin_terms("generate an image of a wolf")
        self.assertEqual(terms, ["generate", "image", "wolf"])
        self.assertEqual(cp.plugin_relevance(terms, COMFY), 0.92)

    def test_reaches_gate(self):
        self.assertTrue(cp.reaches_gate("how does stable diffusion turn noise into a picture?", COMFY)[0])
        self.assertFalse(cp.reaches_gate("what's the capital of Australia?", COMFY)[0])
        self.assertTrue(cp.reaches_gate("make one", COMFY)[0])  # no usable words: every Head is a candidate
        self.assertFalse(cp.reaches_gate("   ", COMFY)[0])
        needs_picture = dict(COMFY, accepts=["image/png"])
        self.assertFalse(cp.reaches_gate("generate an image", needs_picture)[0])

    def test_messages_match_chimera(self):
        m = cp.gate_messages(COMFY, "draw a fox")
        self.assertEqual(m[0]["content"], prompts.HEAD_GATE_PROMPT)
        self.assertTrue(m[1]["content"].startswith("Tool: ComfyUI image generation: Generates a picture"))
        self.assertIn("\nUse it when: Someone asks", m[1]["content"])
        self.assertTrue(m[1]["content"].endswith("\n\nRequest: draw a fox\n\nShould this tool handle the request?"))
        m = cp.planner_messages("Do X.", history=[{"role": "user", "content": "hi"}], prior="old", critique="fix Y")
        self.assertTrue(m[1]["content"].startswith("Earlier in this chat (for context only):\n\n[user]\nhi\n\n---\nThe task:\nDo X."))
        self.assertIn("\n\nWhat still needs work:\nfix Y\n\n", m[1]["content"])
        b = cp.chat_body("gate", "m", m)
        self.assertEqual(b["options"]["temperature"], 0)
        self.assertNotIn("think", b)
        self.assertEqual(cp.chat_body("planner", "m", m)["format"], "json")


class SyncTests(unittest.TestCase):
    @unittest.skipUnless(__import__("os").path.isdir(_paths.APP), "Chimera's app/ folder isn't next to helper-model/")
    def test_prompts_and_port_match_app(self):
        from tools import check_prompts_sync
        self.assertEqual(check_prompts_sync.check(_paths.APP), [])


if __name__ == "__main__":
    unittest.main()
