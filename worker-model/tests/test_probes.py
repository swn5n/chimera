"""probes/: the worker training template and the GGUF source fix, on fixture text (no model, no Ollama, no MLX).

TEST FIXTURES ONLY, NEVER TRAINING DATA."""
import ast
import json
import os
import tempfile
import unittest

from tests import _paths  # noqa: F401
from probes import round_trip, template_parity as tp
from probes.mlx_train_driver import wired_gb

# The two lines of Gemma 4's stock chat template that the worker template changes, with some of what's around them
STOCK = ("{%- set enable_thinking = enable_thinking | default(false) -%}\n{{- bos_token -}}\n"
         "    {%- if not continue_same_model_turn -%}\n        {{- '<|turn>' + role + '\\n' }}\n\n    {%- endif -%}\n")


class WorkerTemplateTests(unittest.TestCase):
    def test_thinking_is_off_whatever_the_caller_passes(self):
        # MLX-LM's tokenizer wrapper passes enable_thinking=True for Gemma 4: an Oct 30 audit found the patched
        # template never fired on the real training path because the default survived
        out = tp.worker_template(STOCK)
        self.assertIn("{%- set enable_thinking = false -%}", out)
        self.assertNotIn("default(false)", out)

    def test_an_assistant_turn_starts_with_the_empty_thought_block(self):
        out = tp.worker_template(STOCK)
        self.assertIn("role == 'model' and not enable_thinking and not continue_same_model_turn", out)
        self.assertIn("{{- '<|channel>thought\\n<channel|>' -}}", out)
        self.assertLess(out.index("<|turn>"), out.index("<|channel>"))

    def test_a_changed_stock_template_stops_it(self):
        with self.assertRaises(SystemExit):
            tp.worker_template(STOCK.replace("enable_thinking | default(false)", "enable_thinking"))
        with self.assertRaises(SystemExit):
            tp.worker_template(STOCK.replace("'<|turn>' + role", "'<|turn>' ~ role"))

    def test_the_worker_setup_is_the_one_that_turns_thinking_off(self):
        self.assertEqual((tp.WORKER_RENDERER, tp.WORKER_PARSER), ("gemma4-large", "gemma4-no-thinking"))

    def test_leaks(self):
        self.assertEqual(tp.leaks("plain answer"), [])
        self.assertEqual(tp.leaks("<|channel>thought\n<channel|>x"), ["<|channel>", "<channel|>", "thought\n"])


class NamedSpecialsTests(unittest.TestCase):
    def test_named_tokens_become_additional_specials(self):
        # transformers 4.57 (llama.cpp's converter here) doesn't count Gemma 4's named tokens as special, so they came
        # out of the GGUF as normal tokens and <|turn> split into <, |, turn
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "tokenizer_config.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"bos_token": "<bos>", "eos_token": "<eos>", "sot_token": "<|turn>", "eot_token": "<turn|>",
                           "think_token": "<|think|>", "additional_special_tokens": ["<x>", "<turn|>"],
                           "model_max_length": 5}, f)
            self.assertEqual(round_trip.named_specials(d), 2)
            with open(p, encoding="utf-8") as f:
                cfg = json.load(f)
            self.assertEqual(cfg["additional_special_tokens"], ["<x>", "<turn|>", "<|turn>", "<|think|>"])
            self.assertEqual(round_trip.named_specials(d), 0)  # once is enough


class DriverTests(unittest.TestCase):
    def test_wired_memory_reads_vm_stat(self):
        self.assertGreater(wired_gb(), 0.1)

    def test_the_pilot_goes_through_the_driver_with_a_cache_limit(self):
        with open(os.path.join(os.path.dirname(tp.__file__), "mlx_pilot.py"), encoding="utf-8") as f:
            src = f.read()
        ast.parse(src)
        self.assertIn('"--cache-limit-gb"', src)
        self.assertIn("mlx_train_driver.py", src)


if __name__ == "__main__":
    unittest.main()
