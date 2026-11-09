"""datagen/normalise.py: the mechanical fixes precheck makes to a reply before it is checked. A decorated File line
before a block (the smoke's shapes: gpt-oss's "**File: path**" with trailing spaces or not, plus "`File: x`",
"### File: x", "*File:* x", "File: `x`", "**File:** x (part)") becomes the plain form the validator passes, and the
join reads the same path and the same part; "**File: x (part)**", which Go reads as the whole file x, stays, and so
do a File line inside a block, a plain one, one with other words after its path and one before the handoff block. The
stand-in marker written with U+2011 (and its kin) gets an ASCII hyphen in its own line only. The Go validator's
verdicts are checked through a real Chimera binary when $CHIMERA_BIN names one.

The replies are hand-written test fixtures (each carries the mark), never training data.
"""
import os
import unittest

from tests import _paths  # noqa: F401
from contract import validate as cv
from datagen import normalise as N
from runner import mock_ollama

MARK = mock_ollama.MARK
BIN = os.environ.get("CHIMERA_BIN") or ""
STEP = {"id": "s1", "title": "Store", "kind": "code", "instructions": "Write store.py with LIMIT and save(). " + MARK}
HANDOFF = "```handoff\nprovides: store.py with LIMIT and save()\nuses: none\nassumed: none\n```"
BODY = "```python\n" + MARK + "\nLIMIT = 3\n\n\ndef save():\n    return LIMIT\n```\n"


def reply(file_line, body=BODY):
    return file_line + "\n" + body + "\n" + HANDOFF


class FileLineTests(unittest.TestCase):
    def test_the_smokes_bold_lines_become_plain(self):
        for line, want in (("**File: store.py**", "File: store.py"),          # 156 of the smoke's 160 rewrites
                           ("**File: src/store.py**  ", "File: src/store.py"),  # with trailing spaces
                           ("**File:** store.py (part)", "File: store.py (part)"),
                           ("### File: store.py (part)", "File: store.py (part)"),
                           ("**File:** store.py", "File: store.py"),
                           ("`File: store.py`", "File: store.py"),
                           ("### File: store.py", "File: store.py"),
                           ("*File:* store.py", "File: store.py"),
                           ("File: `store.py`", "File: store.py"),
                           ("- File: **store.py** (Part)", "File: store.py (part)"),
                           ("File:store.py:", "File: store.py")):
            text, n = N.file_lines(reply(line))
            self.assertEqual((text, n), (reply(want), 1), line)
            self.assertEqual(cv.file_line(want)[0], cv.file_line(line)[0])  # the join reads the same path

    def test_plain_lines_and_words_after_the_path_stay(self):
        for line in ("File: store.py", "File: store.py (part)", "File: README.md (placeholder)",
                     "**File: store.py** - the store", "Here is store.py:", "File:",
                     "**File: _config.yml**", "File: __init__.py"):  # Go reads config.yml, init__.py
            self.assertEqual(N.file_lines(reply(line)), (reply(line), 0), line)

    def test_a_part_go_reads_as_a_whole_file_stays(self):
        # Go reads these as the whole file (the "(part)" is inside the decoration): written plain they would become a
        # part, so they stay decorated and the candidate fails on form (n-python-0001-02 r1 s3's line in the smoke)
        for line in ("**File: store.py (part)**", "**File: src/find_cmd.py (part)**  ", "`File: store.py (part)`",
                     "**File: store.py (Part)**"):
            self.assertEqual(cv.file_line(line)[1], False, line)
            self.assertIsNone(N.plain_file_line(line), line)
            self.assertEqual(N.file_lines(reply(line)), (reply(line), 0), line)
        text = "**File: a.py**\n" + BODY + "\n**File: b.py (part)**\n" + BODY + "\n" + HANDOFF
        got, n = N.file_lines(text)
        self.assertEqual(n, 1)  # a.py is made plain, b.py's line is left for the validator to refuse
        self.assertTrue(got.startswith("File: a.py\n```python"), got)
        self.assertIn("\n**File: b.py (part)**\n```python", got)

    def test_only_the_line_the_validator_reads_before_a_block(self):
        inside = "```python\n" + MARK + "\n# **File: store.py**\nNOTE = '''\n**File: other.py**\n'''\n```\n"
        text = "**File: store.py**\n\n" + inside + "\n**File: notes.md** comes next\n\n" + HANDOFF
        got, n = N.file_lines(text)
        self.assertEqual(n, 1)
        self.assertTrue(got.startswith("File: store.py\n\n```python\n"), got)  # blank lines between, as Go skips
        self.assertIn("# **File: store.py**\nNOTE = '''\n**File: other.py**\n'''", got)  # the block's own text
        self.assertIn("**File: notes.md** comes next", got)
        before_handoff = "File: a.py\n" + BODY + "\n**File: b.py**\n" + HANDOFF
        self.assertEqual(N.file_lines(before_handoff), (before_handoff, 0))

    def test_several_blocks_and_crlf(self):
        text = "**File: a.py**\r\n" + BODY + "\n**File:** b.py (part)\n" + BODY + "\n" + HANDOFF
        got, n = N.file_lines(text)
        self.assertEqual(n, 2)
        self.assertTrue(got.startswith("File: a.py\r\n```python"), got)
        self.assertIn("\nFile: b.py (part)\n```python", got)
        self.assertEqual(N.file_lines(""), ("", 0))

    @unittest.skipUnless(BIN and os.path.exists(BIN), "set CHIMERA_BIN to a Chimera binary")
    def test_chimeras_validator_passes_the_plain_form(self):
        from datagen.chimera import Chimera
        ch = Chimera(BIN, env={"OLLAMA_HOST": "127.0.0.1:9"})
        for line in ("**File: store.py**", "**File:** store.py (part)", "*File:* store.py"):
            jobs = [{"text": t, "mode": "files", "sid": "s1", "deps": [], "lone": False, "step": STEP}
                    for t in (reply(line), N.file_lines(reply(line))[0])]
            before, after = ch.validate(jobs)
            self.assertEqual([x["code"] for x in before["issues"]], ["file_line_decorated"], before)
            self.assertEqual((after["form_ok"], after["issues"]), (True, []), after)
            self.assertEqual([f["path"] for f in before.get("files") or []], ["store.py"])
            # Go read the bold "(part)" line as a whole file; plain, it is the part the reply says it is
            self.assertEqual([(f["path"], f["part"]) for f in after.get("files") or []],
                             [("store.py", "(part)" in line)])
            # the part is the one Go read before the line was made plain, too
            self.assertEqual([(f["path"], f["part"]) for f in before.get("files") or []],
                             [("store.py", "(part)" in line)])
        line = "**File: store.py (part)**"  # Go joins the whole file; the line stays and fails on form
        job = {"text": N.file_lines(reply(line))[0], "mode": "files", "sid": "s1", "deps": [], "lone": False,
               "step": STEP}
        got = ch.validate([job])[0]
        self.assertEqual(([x["code"] for x in got["issues"]], got["form_ok"]), (["file_line_decorated"], False), got)
        self.assertEqual([(f["path"], f["part"]) for f in got.get("files") or []], [("store.py", False)])


class MarkerDashTests(unittest.TestCase):
    def test_the_markers_hyphen_becomes_ascii_in_its_line_only(self):
        code = (MARK + "\nprint(\"chimera: stand\u2011in\", \"ctx_s1\")\n"
                "print(f\"chimera: stand\u2011in \u2013 SVG not found, built in code\")\n"
                "label = \"well\u2011lit\"\n"
                "print('chimera: stand\u2212in', key, 'non\u2011ascii')\n")
        got, n = N.marker_dashes(code)
        self.assertEqual(n, 3)
        self.assertEqual(got, MARK + "\nprint(\"chimera: stand-in\", \"ctx_s1\")\n"
                              "print(f\"chimera: stand-in \u2013 SVG not found, built in code\")\n"  # U+2013 stays
                              "label = \"well\u2011lit\"\n"  # not a marker line: the model's own typography
                              "print('chimera: stand-in', key, 'non-ascii')\n")
        for dash in ("\u2010", "\u2012"):
            self.assertEqual(N.marker_dashes(f"print('chimera: stand{dash}in', k)"),
                             ("print('chimera: stand-in', k)", 1))

    def test_an_ascii_marker_and_other_text_stay(self):
        for text in (MARK + "\nprint(\"chimera: stand-in\", key)\n", "a well\u2011lit room " + MARK, ""):
            self.assertEqual(N.marker_dashes(text), (text, 0))


BLENDER_STEP = {"id": "s2", "title": "Lamp", "kind": "blender", "depends_on": ["s1"],
                "instructions": "Hang a lamp chimera_lamp over s1's floor. " + MARK}
BPY = ("```python\n" + MARK + "\nimport bpy\n\nSETTINGS_s2 = {\"height\": 2.5}\n\n\ndef build_s2(ctx):\n"
       "    lamp = bpy.data.lights.new(\"chimera_lamp\", type=\"POINT\")\n"
       "    ctx[\"objects\"][\"lamp\"] = lamp\n\n\n"
       "if __name__ == \"__main__\":\n    build_s2({\"scene\": bpy.context.scene, \"collection\": "
       "bpy.context.scene.collection, \"objects\": {}, \"values\": {}})\n```\n")
KEYS = "provides: chimera_lamp as ctx[\"objects\"][\"lamp\"]\nuses: s1's floor\nassumed: none"
TAGGED = BPY + "\n```handoff\n" + KEYS + "\n```"


class HandoffFenceTests(unittest.TestCase):
    """The handoff block at a reply's end put in its fence: an untagged fence whose first line is "handoff" (11 of
    the fourth smoke's 12 handoff_missing Blender tries), and a closing fence glued to the assumed line
    (handoff_unclosed_end); nothing else."""

    def test_an_untagged_fence_whose_first_line_is_handoff(self):
        for tail in ("\n```\nhandoff\n" + KEYS + "\n```", "\n```\nhandoff\n" + KEYS + "\n```\n\n",
                     "\n```  \n  handoff \n" + KEYS + "\n```"):
            got, n = N.handoff_fence(BPY + tail)
            self.assertEqual((got.rstrip("\n"), n), (TAGGED, 1), tail)
        crlf = (BPY + "\n```\nhandoff\n" + KEYS + "\n```").replace("\n", "\r\n")
        self.assertEqual(N.handoff_fence(crlf), (TAGGED.replace("\n", "\r\n"), 1))

    def test_a_closing_fence_glued_to_the_assumed_line(self):
        glued = KEYS + "```"
        self.assertEqual(N.handoff_fence(BPY + "\n```handoff\n" + glued), (TAGGED, 1))
        self.assertEqual(N.handoff_fence(BPY + "\n```handoff\n" + KEYS + " ```  \n\n"), (TAGGED + "\n\n", 1))
        # both at once (n-blender-0000-01 r2 s2 c2 in the fourth smoke)
        self.assertEqual(N.handoff_fence(BPY + "\n```\nhandoff\n" + glued), (TAGGED, 2))

    def test_every_other_form_stays(self):
        docstring = BPY.replace('```\n', '"""\nhandoff\n' + KEYS + '\n"""\n```\n')  # inside the code block
        for text in (TAGGED, BPY,
                     docstring,
                     BPY + "\nhandoff\n```\n" + KEYS + "\n```",  # the label above a plain block
                     BPY + "\n```\n" + KEYS + "\n```",  # a plain block, no label (handoff_unlabelled)
                     BPY + "\n```text\nhandoff\n" + KEYS + "\n```",  # another language
                     BPY + "\n```\nHandoff:\n" + KEYS + "\n```",  # not the exact "handoff"
                     BPY + "\n````\nhandoff\n" + KEYS + "\n````",  # another fence
                     BPY + "\n```\nhandoff\n" + KEYS + "\nmore: x\n```",  # a line besides the three
                     BPY + "\n```\nhandoff\nprovides: a\nuses: none\n```",  # a key missing
                     BPY + "\n```\nhandoff\n" + KEYS + "\n```\nThat is all.",  # text after it
                     BPY + "\n```\nhandoff\n" + KEYS + "\n```\n\n```handoff\n" + KEYS + "\n```",  # two
                     BPY + "\n```\nhandoff\n" + KEYS + "```\n```",  # glued, then closed after it
                     BPY + "\n```\nhandoff\n" + KEYS,  # never closed
                     BPY + "\n```handoff\n" + KEYS.replace("assumed: none", "assumed: none````"),  # four
                     BPY + "\n```handoff\nuses: s1's floor```\nprovides: a\nassumed: none",  # glued mid-block
                     ""):
            self.assertEqual(N.handoff_fence(text), (text, 0), text[-80:])

    @unittest.skipUnless(BIN and os.path.exists(BIN), "set CHIMERA_BIN to a Chimera binary")
    def test_chimeras_validator_reads_the_fixed_form(self):
        from datagen.chimera import Chimera
        ch = Chimera(BIN, env={"OLLAMA_HOST": "127.0.0.1:9"})
        for text, before in ((BPY + "\n```\nhandoff\n" + KEYS + "\n```", "handoff_missing"),  # and extra_block
                             (BPY + "\n```handoff\n" + KEYS + "```", "handoff_unclosed_end"),
                             (BPY + "\n```\nhandoff\n" + KEYS + "```", "handoff_missing")):
            jobs = [{"text": t, "mode": "blender", "sid": "s2", "deps": ["s1"], "lone": False, "step": BLENDER_STEP}
                    for t in (text, N.handoff_fence(text)[0])]
            was, now = ch.validate(jobs)
            self.assertIn(before, [x["code"] for x in was["issues"]], was)
            self.assertFalse(was["form_ok"])
            self.assertEqual((now["form_ok"], now["issues"]), (True, []), now)
            self.assertEqual(now["handoff"]["provides"], 'chimera_lamp as ctx["objects"]["lamp"]')
            self.assertEqual(now["handoff"]["assumed"], "")  # "none": the glued fence isn't part of the value
        # what stays fails as before (the docstring form: 1 of the fourth smoke's 12)
        docstring = BPY.replace('```\n', '"""\nhandoff\n' + KEYS + '\n"""\n```\n')
        got = ch.validate([{"text": N.handoff_fence(docstring)[0], "mode": "blender", "sid": "s2", "deps": ["s1"],
                            "lone": False, "step": BLENDER_STEP}])[0]
        self.assertIn("handoff_missing", [x["code"] for x in got["issues"]])

if __name__ == "__main__":
    unittest.main()
