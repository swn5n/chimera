"""The contract's worker request (contract/prompt.py) and mode selection (contract/planinfo.py)."""
import copy
import unittest

from tests import _paths  # noqa: F401
from tests import contract_fixtures as F
from contract import planinfo, prompt
from contract import texts as T
from contract.goport import clean_plan
from contract.join import join


def plan_of(*steps, kind="code", summary="A project.", title="P"):
    return clean_plan({"title": title, "kind": kind, "summary": summary, "steps": [
        {"id": "s%d" % (k + 1), "title": t, "kind": sk, "instructions": ins, "depends_on": deps}
        for k, (t, sk, ins, deps) in enumerate(steps)]})


class ModeTests(unittest.TestCase):
    def test_modes(self):
        cases = [
            (plan_of(("Scene", "blender", "Build it.", [])), "", 0, "blender"),
            (plan_of(("Script", "code", "Write a bpy script for the desk.", [])), "", 0, "blender"),
            (plan_of(("Script", "code", "Write the script.", [])), "Make it in Blender", 0, "blender"),
            (plan_of(("Count", "code", "Write count_words(text).", [])), "", 0, "python-script"),
            (plan_of(("Count", "code", "Read data.csv and write report.json.", [])), "", 0, "python-script"),
            (plan_of(("Store", "code", "Write src/store.py.", [])), "", 0, "files"),
            (plan_of(("UI", "code", "A page in HTML and JavaScript.", [])), "", 0, "files"),
            (plan_of(("Server", "code", "Write the Go server.", [])), "", 0, "files"),
            (plan_of(("Tool", "code", "Let's go over the CLI.", [])), "", 0, "python-script"),  # "go" isn't Go
            (plan_of(("Intro", "writing", "Write it.", []), ("Code", "code", "Write main.py", [])), "", 0, "section"),
            (plan_of(("Facts", "research", "Find them.", [])), "", 0, "section"),
            (plan_of(("Do it", "general", "Do it.", [])), "", 0, "section"),
        ]
        for p, goal, i, mode in cases:
            with self.subTest(instructions=p["steps"][i]["instructions"], goal=goal):
                self.assertEqual(planinfo.step_mode(p, i, goal), mode)

    def test_language_words_need_a_programming_context(self):
        # Review, Oct 29: ordinary English words made Python plans files plans, and JS/Java tasks that name no
        # language stayed Python. Each line is a one-step code plan's instructions.
        python = [
            "Write a script that computes the angular velocity of a spinning top.",
            "A Python bot that can react to chat messages.",
            "A tool that prints a summary and an HTML report to stdout.",
            "Draw a rust-coloured sunset gradient in Python.",
            "A swift Python solver for sudoku.",
            "Rust patches spread where the paint is thin; model their growth over time.",
            "React to each event by logging it.",
            "Express the result as a fraction.",
            "A Python scraper that downloads HTML pages and counts the links.",
            "A script that generates an HTML page from the CSV.",
            "Write a Node class for a linked list.",
            "Go file by file through the folder and count the lines.",
            "Simulate the board game Go with a tiny engine.",
            "Ship it with Express delivery labels.",
        ]
        other = [
            ("Add rate limiting to my Express API.", "Express API"),
            ("My Fabric mod crashes on world load.", "Fabric mod"),
            ("Fix the NullPointerException in HomesState.load().", "NullPointerException"),
            ("Write it in Rust with no unsafe code.", "in Rust"),
            ("A Rust program that renames photos.", "Rust program"),
            ("A Swift package for parsing dates.", "Swift package"),
            ("Build a React component for the table.", "React component"),
            ("An Angular service for the API.", "Angular service"),
            ("A single-page HTML/JS app for a scoreboard.", "HTML/JS"),
            ("Build an HTML page with a form.", "HTML page"),
            ("A Node.js script that watches a folder.", "Node.js"),
            ("A Rails app for bookings.", "Rails app"),
            ("Write the tests with Jest.", "with Jest"),
            ("Port it to ASP.NET.", ".NET"),
            ("A bash script that backs up my files.", "bash script"),
            ("Write the Go server.", "Go server"),
            ("Write it in Go.", "in Go"),
            ("A C++ ray tracer.", "C++"),
        ]
        for text in python:
            with self.subTest(text=text):
                self.assertIsNone(planinfo.other_language(text))
                self.assertEqual(planinfo.step_mode(plan_of(("Step", "code", text, [])), 0), "python-script")
        for text, words in other:
            with self.subTest(text=text):
                self.assertEqual(planinfo.other_language(text), words)
                self.assertEqual(planinfo.step_mode(plan_of(("Step", "code", text, [])), 0), "files")

    def test_blender_names_without_the_word_blender(self):
        for text in ("Build a Geometry Nodes setup from Python that scatters rivets.",
                     "For every .blend in the queue folder, set the samples and render frame 1.",
                     "A rusty metal material with edge wear from Pointiness.", "Render it with EEVEE.",
                     "Make the mesh with bmesh."):
            with self.subTest(text=text):
                self.assertEqual(planinfo.step_mode(plan_of(("Step", "code", text, [])), 0), "blender")
        self.assertEqual(planinfo.step_mode(plan_of(("Step", "code", "List every Eevee evolution.", [])), 0),
                         "python-script")

    def test_positional_names_dependencies_and_users(self):
        p = clean_plan({"title": "T", "kind": "code", "summary": "", "steps": [
            {"id": "alpha", "title": "A", "kind": "code", "instructions": "a", "depends_on": []},
            {"id": "beta", "title": "B", "kind": "code", "instructions": "b", "depends_on": ["alpha", "alpha"]},
            {"id": "gamma", "title": "C", "kind": "code", "instructions": "c", "depends_on": ["beta", "alpha", "x"]}]})
        self.assertEqual(planinfo.dep_names(p, 2), ["s1", "s2"])
        self.assertEqual(planinfo.dep_names(p, 1), ["s1"])
        self.assertEqual(planinfo.user_names(p, 0), ["s2", "s3"])
        self.assertEqual(planinfo.user_names(p, 2), [])


class SystemPromptTests(unittest.TestCase):
    def setUp(self):
        self.plan = F.BLENDER_PLAN

    def test_layout(self):
        sp = prompt.system_prompt(self.plan, 1)
        parts = sp.split("\n\n")
        self.assertEqual(parts[0], T.fill(T.CONTRACT_OPENING, sid="s2", n=3))
        self.assertEqual(parts[1], "Project: Reading corner\n" + self.plan["summary"])
        outline = parts[2].split("\n")
        self.assertEqual(outline[0], T.CONTRACT_PLAN_HEAD)
        self.assertTrue(outline[1].startswith("  s1. Floor and material [blender]: Make a 4 x 4 m floor"))
        self.assertEqual(outline[2], "→ s2. Side table [blender]: your step, in full below")
        self.assertTrue(outline[3].startswith("  s3. Lamp on the table [blender] (uses s2): Put a lamp"))
        self.assertEqual(outline[4], "Steps that use your piece: s3.")
        self.assertEqual(parts[3], "How Chimera joins your piece:\n" + T.fill(T.MODE_BLENDER, sid="s2"))
        self.assertEqual(parts[4], T.CONTRACT_HANDOFF)
        self.assertEqual(len(parts), 5)
        self.assertIn("Nothing else uses your piece: it goes straight into the finished result.",
                      prompt.system_prompt(self.plan, 2))
        self.assertIn("→ s3. Lamp on the table [blender] (uses s2): your step, in full below",
                      prompt.system_prompt(self.plan, 2))

    def test_other_steps_instructions_are_cut_to_one_line_of_300(self):
        p = copy.deepcopy(self.plan)
        p["steps"][0]["instructions"] = "Line one.\n\nLine   two. " + "x" * 400
        line = prompt.system_prompt(p, 1).split("\n")[[l.startswith("  s1.") for l in
                                                        prompt.system_prompt(p, 1).split("\n")].index(True)]
        instr = line.split(": ", 1)[1]
        self.assertEqual(len(instr), 300)
        self.assertTrue(instr.startswith("Line one. Line two. xxx"))
        self.assertTrue(instr.endswith("…"))

    def test_lone_step(self):
        p = plan_of(("Count", "code", "Write count_words(text).", []), title="Counter")
        sp = prompt.system_prompt(p, 0)
        self.assertTrue(sp.startswith(T.CONTRACT_LONE_OPENING + "\n\nProject: Counter\n"))
        self.assertIn("How Chimera joins your piece:\n" + T.MODE_PYTHON_SCRIPT, sp)
        self.assertNotIn("handoff", sp)
        self.assertNotIn("The plan (", sp)
        req = prompt.worker_request(p, 0, {})
        self.assertTrue(req.lone)
        self.assertEqual(req.messages[1]["content"], "Your step, s1: Count\nWrite count_words(text).")

    def test_research_rule_and_refs(self):
        p = plan_of(("Facts", "research", "Find them.", []), ("Write", "writing", "Write it.", ["s1"]), kind="research")
        self.assertIn(T.MODE_SECTION + "\n" + T.MODE_SECTION_RESEARCH, prompt.system_prompt(p, 0))
        self.assertNotIn(T.MODE_SECTION_RESEARCH, prompt.system_prompt(p, 1))
        refs = [{"title": "R", "kind": "lesson", "summary": "S", "content": "C"}]
        self.assertTrue(prompt.system_prompt(p, 1, refs=refs).endswith(
            T.CONTRACT_HANDOFF + T.REFS_HEAD + "\n--- R (lesson) ---\nS\nC\n"))


class UserMessageTests(unittest.TestCase):
    def test_dependency_with_handoff(self):
        msg, _ = prompt.user_message(F.BLENDER_PLAN, 2, F.BLENDER_OUTPUTS)
        head = ("Your step, s3: Lamp on the table\n" + F.BLENDER_PLAN["steps"][2]["instructions"] + "\n\n"
                "From s2, \"Side table\" (you use it):\nIts handoff:\n"
                "provides: chimera_table (the top) as ctx[\"objects\"][\"table\"], legs chimera_table_leg_0 to 3 parented to it\n"
                "uses: none\nassumed: the table stands at x = 1, y = 1\n```python\n" + F.MARK)
        self.assertTrue(msg.startswith(head), msg[:600])
        self.assertNotIn("```handoff", msg)

    def test_failed_dependency_and_no_handoff(self):
        msg, _ = prompt.user_message(F.BLENDER_PLAN, 2, dict(F.BLENDER_OUTPUTS, s2=None))
        self.assertTrue(msg.endswith("From s2, \"Side table\" (you use it):\n" + T.CONTRACT_USER_DEP_FAILED))
        msg, _ = prompt.user_message(F.BLENDER_PLAN, 2, dict(F.BLENDER_OUTPUTS, s2="Here is a script.\n```python\nx\n```"))
        self.assertIn("(you use it):\n" + T.CONTRACT_USER_DEP_NO_HANDOFF + "\nHere is a script.", msg)

    def test_dependency_with_an_unfenced_handoff(self):
        # the near-miss form joining reads is shown the same way: its three lines, and the piece without them
        unfenced = F.S2.replace("```handoff\n", "handoff\n").rstrip()
        unfenced = unfenced[:unfenced.rindex("\n```")]
        self.assertTrue(unfenced.endswith("assumed: the table stands at x = 1, y = 1"))
        fenced, _ = prompt.user_message(F.BLENDER_PLAN, 2, F.BLENDER_OUTPUTS)
        msg, _ = prompt.user_message(F.BLENDER_PLAN, 2, dict(F.BLENDER_OUTPUTS, s2=unfenced))
        self.assertEqual(msg, fenced)

    def test_dependency_piece_cut_at_8000_bytes(self):
        long = "x" * 9000 + "\n```handoff\nprovides: a\nuses: none\nassumed: none\n```"
        msg, _ = prompt.user_message(F.BLENDER_PLAN, 2, dict(F.BLENDER_OUTPUTS, s2=long))
        self.assertTrue(msg.endswith("\n" + "x" * 8000 + "\n…(cut)"))

    def test_round_two_parts(self):
        prev = join(F.BLENDER_PLAN, F.BLENDER_OUTPUTS).text
        req = prompt.worker_request(F.BLENDER_PLAN, 1, F.BLENDER_OUTPUTS, prev_result=prev, critique="Legs float.")
        user = req.messages[1]["content"]
        self.assertTrue(req.round2_matched)
        self.assertIn("\n\nLast round's result for your part:\nSETTINGS_s2 = {", user)
        self.assertTrue(user.endswith("\n\nWhat still needs work:\nLegs float."))
        req = prompt.worker_request(F.BLENDER_PLAN, 1, F.BLENDER_OUTPUTS, prev_result="Some other result.")
        self.assertFalse(req.round2_matched)
        self.assertIn("Last round's result for your part:\nSome other result.\n\nWhat still needs work:\nnone",
                      req.messages[1]["content"])

    def test_need_ctx_is_run_steps(self):
        req = prompt.worker_request(F.BLENDER_PLAN, 2, F.BLENDER_OUTPUTS)
        size = sum(len(m["content"].encode()) // 3 + 64 for m in req.messages)
        self.assertEqual(req.need_ctx, size + 4096)
        self.assertEqual((req.sid, req.n, req.mode, req.deps), ("s3", 3, "blender", ["s2"]))


class RepairTests(unittest.TestCase):
    def test_repair_message(self):
        crash = {"step": "s3", "function": "build_s3", "piece_line": 41, "source": "x.inputs[\"Transmission\"]",
                 "error": "KeyError: 'Transmission'", "runner": "Blender 5.2.2"}
        req = prompt.repair_request(F.BLENDER_PLAN, 2, F.BLENDER_OUTPUTS, F.S3_BROKEN, crash)
        user = req.messages[1]["content"]
        normal = prompt.worker_request(F.BLENDER_PLAN, 2, F.BLENDER_OUTPUTS).messages[1]["content"]
        self.assertTrue(user.startswith(normal + "\n\nYour piece crashed when Chimera ran the joined script in "
                                                 "Blender 5.2.2:\nline 41 in build_s3: x.inputs[\"Transmission\"]\n"
                                                 "KeyError: 'Transmission'\n\nYour piece was:\n"))
        self.assertIn(F.S3_BROKEN.strip(), user)
        self.assertTrue(user.endswith("Running stops at the first error, so check the rest of your piece against "
                                      "Blender 5.2.2's API too."))
        self.assertEqual(req.messages[0], prompt.worker_request(F.BLENDER_PLAN, 2, F.BLENDER_OUTPUTS).messages[0])

    def test_where_a_crash_is_named(self):
        # the line map's function when it has one; else what the part is (FILLED texts)
        self.assertEqual(prompt.crash_where({"step": "s2", "part": "helper", "function": "_s2_LEG"}), "_s2_LEG")
        self.assertEqual(prompt.crash_where({"step": "s2", "part": "settings", "function": None}), "SETTINGS_s2")
        self.assertEqual(prompt.crash_where({"step": "s3", "part": "import", "function": None}), T.CONTRACT_REPAIR_IMPORTS)
        self.assertEqual(prompt.crash_where({"step": "s3", "part": "build"}), "build_s3")
        lm_settings = join(F.BLENDER_PLAN, F.BLENDER_OUTPUTS).linemap
        n = next(k for k in range(1, len(lm_settings) + 1) if lm_settings.locate(k)["part"] == "settings")
        self.assertEqual(prompt.crash_where(lm_settings.locate(n)), "SETTINGS_s1")


if __name__ == "__main__":
    unittest.main()
