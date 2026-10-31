"""Today's worker prompt port (contract/today.py) against app/'s Go source, and the Go helper ports."""
import importlib.util
import os
import re
import sys
import unittest

from tests import _paths
from contract import texts as T
from contract import today
from contract.goport import clean_plan, code_blocks, truncate

PROMPTS_GO = os.path.join(_paths.APP, "prompts.go")
HYDRA_GO = os.path.join(_paths.APP, "hydra.go")
HELPER = os.path.join(_paths.REPO, "helper-model", "helper")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def go_map(src, var):
    """The string values of a Go map[string]string literal (raw `...` or plain "..." strings)."""
    body = src[src.index("var %s = map[string]string{" % var):]
    body = body[:body.index("\n}\n")]
    out = {}
    for m in re.finditer(r'"(\w+)":\s+(?:`([^`]*)`|"((?:[^"\\]|\\.)*)")', body):
        out[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3).encode().decode("unicode_escape")
    return out


@unittest.skipUnless(os.path.exists(PROMPTS_GO), "app/prompts.go not found")
class GoSyncTests(unittest.TestCase):
    """texts.TODAY_* are verbatim copies; these fail when app/ changes them, so the A/B arm stays 'today'."""

    def test_worker_kind_rules(self):
        self.assertEqual(go_map(read(PROMPTS_GO), "workerKindRules"), T.TODAY_KIND_RULES)

    def test_synth_kind_rules(self):
        self.assertEqual(go_map(read(PROMPTS_GO), "synthKindRules"), T.TODAY_SYNTH_KIND_RULES)

    def test_worker_prompt_format(self):
        src = read(PROMPTS_GO)
        m = re.search(r"return fmt\.Sprintf\(`(You are one worker in Chimera[^`]*)`, plan\.Title, plan\.Summary, "
                      r"outline\.String\(\), rules\)", src)
        self.assertIsNotNone(m, "workerPrompt's Sprintf changed shape")
        self.assertEqual(m.group(1), T.TODAY_WORKER_FORMAT)
        for line in ('marker = "→ "', 'fmt.Fprintf(&outline, "%s%d. %s\\n", marker, i+1, s.Title)',
                     'if workerKindRules[kind] == "" {', "kind = plan.Kind", 'rules = workerKindRules["general"]'):
            self.assertIn(line, src)

    def test_synth_prompt(self):
        src = read(PROMPTS_GO)
        self.assertIn('return "' + T.TODAY_SYNTH_HEAD + '" +', src)
        self.assertIn('rules + "' + T.TODAY_SYNTH_TAIL + '"', src)

    def test_run_step_and_combine_lines(self):
        src = read(HYDRA_GO)
        for line in ("user.WriteString(step.Instructions)",
                     'out = "%s"' % T.TODAY_DEP_FAILED,
                     r'fmt.Fprintf(&user, "\n\nOutput from the step \"%s\":\n%s", s.Title, truncate(out, 8000))',
                     'msgs := []ChatMessage{{Role: "system", Content: workerPrompt(rec.hydraPlan, step) + refsBlock(useful)}, '
                     '{Role: "user", Content: user.String()}}',
                     "NeedCtx: historyTokens(msgs) + room",
                     "stepRoom := 4096",
                     r'''fmt.Fprintf(&parts, "Task from the person: %s\n\nProject: %s\n%s\n\nThe workers' outputs:\n", rec.Goal, rec.Title, rec.Summary)''',
                     "budget := 60000 / len(rec.Steps)",
                     'out = "(this step failed: " + s.Error + ")"',
                     r'fmt.Fprintf(&parts, "\n## Step %d: %s\n%s\n", i+1, s.Title, truncate(out, budget))',
                     r'''b.WriteString("\n\nKnown-good references from your network's library, checked by the network (reuse them when they fit; ignore them when they don't):\n")''',
                     r'fmt.Fprintf(&b, "\n--- %s (%s) ---\n%s\n%s\n", e.Title, e.Kind, e.Summary, truncate(e.Content, 3000))'):
            with self.subTest(line=line[:60]):
                self.assertIn(line, src)


class TodayPortTests(unittest.TestCase):
    def setUp(self):
        self.plan = clean_plan({"title": "T", "kind": "code", "summary": "Sum.", "steps": [
            {"id": "a", "title": "One", "kind": "code", "instructions": "Do one.", "depends_on": []},
            {"id": "b", "title": "Two", "kind": "nonsense", "instructions": "Do two.", "depends_on": ["a"]}]})

    def test_worker_prompt(self):
        p = today.worker_prompt(self.plan, self.plan["steps"][1])
        self.assertEqual(p, T.TODAY_WORKER_FORMAT % ("T", "Sum.", "  1. One\n→ 2. Two\n", T.TODAY_KIND_RULES["code"]))
        self.assertIn("The plan (you are the step marked →):\n  1. One\n→ 2. Two\n\nWrite complete", p)

    def test_user_message_with_dependency_and_failure(self):
        msg = today.user_message(self.plan, self.plan["steps"][1], {"a": "x" * 9000})
        self.assertTrue(msg.startswith("Do two.\n\nOutput from the step \"One\":\n" + "x" * 8000 + "\n…(cut)"))
        self.assertEqual(today.user_message(self.plan, self.plan["steps"][1], {"a": None}),
                         "Do two.\n\nOutput from the step \"One\":\n(that step failed; make reasonable assumptions)")

    def test_messages_and_need_ctx(self):
        req = today.worker_messages(self.plan, 0, {}, refs=[{"title": "R", "kind": "snippet", "summary": "S",
                                                             "content": "c"}])
        self.assertIn("--- R (snippet) ---\nS\nc\n", req["messages"][0]["content"])
        size = sum(len(m["content"].encode()) // 3 + 64 for m in req["messages"])
        self.assertEqual(req["need_ctx"], size + 4096)

    def test_combine(self):
        req = today.combine_messages("goal", self.plan, {"a": "A out", "b": {"output": None, "status": "failed",
                                                                            "error": "boom"}})
        self.assertTrue(req["messages"][0]["content"].startswith("You are Hydra's final editor"))
        self.assertIn("## Step 2: Two\n(this step failed: boom)\n", req["messages"][1]["content"])


def load_helper_port():
    """helper-model/helper/chimera_port.py, loaded under another package name (both folders have tests/)."""
    spec = importlib.util.spec_from_file_location("hm_helper", os.path.join(HELPER, "__init__.py"),
                                                  submodule_search_locations=[HELPER])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hm_helper"] = mod
    spec.loader.exec_module(mod)
    return importlib.import_module("hm_helper.chimera_port")


@unittest.skipUnless(os.path.exists(os.path.join(HELPER, "chimera_port.py")), "helper-model not found")
class HelperPortParityTests(unittest.TestCase):
    """goport's clean_plan and truncate agree with helper-model's ports (which check_go_parity ran on real replies)."""

    def test_clean_plan_and_truncate(self):
        hp = load_helper_port()
        plans = [
            {"title": "", "kind": "x", "summary": "s", "steps": [
                {"id": "", "title": " ", "kind": "q", "instructions": "", "depends_on": ["s9"]},
                {"id": "s1", "title": "B", "kind": "code", "instructions": "i", "depends_on": ["s1", "zz"]},
                {"id": "s1", "title": "C", "kind": "blender", "instructions": "j", "depends_on": ["s1"]}]},
            {"title": "N", "kind": "code", "summary": "", "steps": [
                {"id": "s%d" % k, "title": "t%d" % k, "kind": "code", "instructions": "x", "depends_on": ["s1"]}
                for k in range(1, 11)]},
        ]
        for p in plans:
            self.assertEqual(clean_plan(p), hp.clean_plan(p))
        for s, n in (("héllo wörld", 2), ("héllo", 2), ("abc", 3), ("a" * 10, 4)):
            self.assertEqual(truncate(s, n), hp.truncate(s, n))


class CodeBlocksTests(unittest.TestCase):
    def test_port_of_go_code_blocks(self):
        md = "x\n```Python {.x}\na\n  ```\n~~~\nb\n```\nc\n~~~\n  ```py\n  d\n  ```\n```js\nopen"
        bs = code_blocks(md)
        self.assertEqual([(b.lang, b.body, b.closed) for b in bs],
                         [("python", "a", True), ("", "b\n```\nc", True), ("py", "d", True), ("js", "open", False)])
        self.assertEqual((bs[0].open_line, bs[0].close_line), (1, 3))


if __name__ == "__main__":
    unittest.main()
