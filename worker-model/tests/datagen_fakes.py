"""A stand-in Ollama for the data generator's tests (tests/test_datagen_task.py, tests/test_datagen_build.py), the
canned plans and pieces it answers with, and the shared setup (a Chimera binary built from app/, or a copy of one).

TEST FIXTURE ONLY, NEVER TRAINING DATA: every reply here is Claude-written test text and carries MARK (the line
`# test fixture, never training data`, runner/mock_ollama.MARK), so tools/check_overlap.py flags any of it that
reaches a training file.

    fake = FakeOllama(log_path)                    # starts on 127.0.0.1, a free port
    fake.plans[goal] = BLENDER_PLAN                # what the planner answers for a goal (else DEFAULT_PLAN)
    ... point datagen at fake.url ...
    fake.jobs()                                    # [(job, model)] of every /api/chat call, in order

Jobs are told apart as datagen sends them: by the system prompt's opening (the seed writer, the planner, the
reviewer, the contract worker and the lone worker, today's worker, the scene judge, the prose judge, the tests
writer) and the model in the body. A worker's reply depends on the step it is told it does ("Your step, s2: Lamp"),
its mode (the contract's "How Chimera joins your piece" rules), whether it is Chimera's repair message, and the
model, so a test can steer every path of a step:
- Blender: Floor passes; Lamp crashes (a TypeError in build_s2) unless it is asked as a repair; Shelf always crashes
  the same way, repaired or not, except on qwen3.8:27b (the second sampler), which passes. Dash writes its stand-in
  marker with U+2011 for the hyphen; Glow names Blender 5.2.2 in a comment except on qwen3.8:27b. The values pair
  (VALUES_PLAN, ctx["values"] since Nov 4): a values step (VALUES_TITLES) hands its SETTINGS_s1 value on in
  ctx["values"] and lists it under provides, with the guard's new literal (VALUES_OK), on qwen3.8:27b and on
  gpt-oss:120b once its notes carry a run of the ctx tell (CTX_FORMS, blender_gate.TELL_FORMS'), else in
  ctx["variables"] (VALUES_VARS: ctx_channel its only fault), so its first batch fails and the told one passes; a
  title in STUBBORN_CTX writes VALUES_VARS on every model, told or not (a soft keep with a dependent, a drop without
  one: VALUES_STUBBORN_PLAN, VALUES_LONE_PLAN); Lamp post reads ctx["values"]["lamp_height"] with a stand-in. GUARD
  and every other canned piece keep the guard of before Nov 4.
- files: Parser passes; Totals provides total() but defines totl (symbols_missing, no crash) except on qwen3.8:27b;
  Format raises a NameError on import whatever is asked (a crash, so it is repaired, and still dropped); Scale
  raises one unless asked as a repair; Main passes. Bold passes once its "**File: x**" line is made plain; Page
  writes only an HTML file; Fixed leaves out its File line until its notes say what earlier tries failed on.
- python-script: Count passes; Report raises a NameError on import unless asked as a repair; so does Summary,
  whose repair rewrites most of it. Words returns {} (its tests fail) except on qwen3.8:27b; Letters fails its
  tests on every model (a NameError once called, or the case kept); Echo repeats a teacher note in a comment.
  Tally, Lines and Shout are right on every model; Docs imports python-docx, which the sandbox lacks.
- sections: Caption and Note pass; anything else gets a generic section.
Steps with other titles get a generic piece of their mode. A canned piece's handoff is written as if every dependency
had delivered (Main: "assumed: none"; Caption: "chimera_lamp from s2"; Lamp and Shelf: "s1's floor"). When the request
says a dependency failed, qwen3.8:27b says so (honest: an item from that step written "s2: item (failed)", an
assumed line of none made "s2 failed: ..."), and gpt-oss:120b does once its notes carry dep_honesty's tell line, so
its first batch fails datagen's dep_honesty stage and the next one, told, passes; a title in STUBBORN never says so
(a test that wants a step kept only as a dependency, task.SOFT_REASONS, adds one). The tests writer answers by title
too (Parser, Totals, Count, Words, Letters, Bold, Tally, Lines, Docs and Shout get asserts, the rest none): Tally's
expect the wrong count,
Lines' import a module no step makes, Shout's start a process, which the reader refuses. A tests call that shows the
writer tests of REWRITES (a rewrite, or the retry after a refusal) gets that entry's tests ("" for none better).
The prose judge scores 5, 2 for a title in prose_low, or prose_scores[(title, model)].
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests import _paths
from datagen import blender_gate as BG
from datagen import dep_honesty, hints, judges, topics
from runner import mock_ollama

MARK = mock_ollama.MARK
GO = shutil.which("go") or next((p for p in ("/opt/homebrew/bin/go", "/usr/local/go/bin/go") if os.path.exists(p)),
                                None)
MODELS = ("gpt-oss:120b", "hydra:1.0", "qwen3.8:27b", "qwen3:8b")
REPAIR = "Your piece crashed when Chimera ran the joined script in"
TEACHER, SECOND = "gpt-oss:120b", "qwen3.8:27b"
STUBBORN = set()  # step titles whose pieces never say a dependency failed, told or not (honest)
STUBBORN_CTX = set()  # values-step titles whose pieces never stop writing ctx["variables"], told or not, on any model
GUARD = 'if __name__ == "__main__":\n    build_{sid}({{"scene": bpy.context.scene, ' \
        '"collection": bpy.context.scene.collection, "objects": {{}}}})\n'
# The contract's guard since Nov 4 (texts.MODE_BLENDER's, with ctx["values"]): the values pieces' only; GUARD stays
GUARD_VALUES = 'if __name__ == "__main__":\n    build_{sid}({{"scene": bpy.context.scene, ' \
               '"collection": bpy.context.scene.collection, "objects": {{}}, "values": {{}}}})\n'
# The ctx tell's fixed runs (blender_gate.TELL_FORMS from ctx_tell's head and advice): a teacher copy that carries one
# was told its piece's ctx key isn't Chimera's
CTX_FORMS = tuple(f for f in BG.TELL_FORMS if f in BG.CTX_HEAD or any(f in a for a in BG.CTX_ADVICE.values()))

# ---------------------------------------------------------------- plans

BLENDER_PLAN = {"title": "Mock lamp room", "kind": "blender",
                "summary": "A floor, a lamp above it and a caption. " + MARK, "steps": [
                    {"id": "s1", "title": "Floor", "kind": "blender", "depends_on": [],
                     "instructions": "Make a 4 m floor plane chimera_floor and register it as "
                                     "ctx['objects']['floor']."},
                    {"id": "s2", "title": "Lamp", "kind": "blender", "depends_on": ["s1"],
                     "instructions": "Hang a point lamp chimera_lamp 2.5 m above s1's floor and register it as "
                                     "ctx['objects']['lamp']."},
                    {"id": "s3", "title": "Caption", "kind": "writing", "depends_on": ["s2"],
                     "instructions": "Write a caption of about 60 words for the lamp-lit room."}]}
FILES_PLAN = {"title": "Mock tally tool", "kind": "code",
              "summary": "A small tool that totals a line of numbers. " + MARK, "steps": [
                  {"id": "s1", "title": "Parser", "kind": "code", "depends_on": [],
                   "instructions": "Write tool/parse.py with parse_line(line), which splits a comma-separated line "
                                   "into stripped, non-empty fields."},
                  {"id": "s2", "title": "Totals", "kind": "code", "depends_on": ["s1"],
                   "instructions": "Write tool/totals.py with total(line), the sum of the line's whole-number fields "
                                   "as an int, using parse_line from s1."},
                  {"id": "s3", "title": "Format", "kind": "code", "depends_on": ["s1"],
                   "instructions": "Write tool/fmt.py with show(n), which returns 'total: <n>'."},
                  {"id": "s4", "title": "Main", "kind": "code", "depends_on": ["s2", "s3"],
                   "instructions": "Write tool/main.py with main(), which prints the total of the line '1,2,3'."}]}
SCRIPT_PLAN = {"title": "Mock word counter", "kind": "code", "summary": "Count words and report them. " + MARK,
               "steps": [
                   {"id": "s1", "title": "Count", "kind": "code", "depends_on": [],
                    "instructions": "Write count_words(text), which returns a dict of each lower-cased word's count."},
                   {"id": "s2", "title": "Report", "kind": "code", "depends_on": ["s1"],
                    "instructions": "Write report(counts), which returns the lines 'word: n', most frequent first."}]}
REWRITE_PLAN = {"title": "Mock word summary", "kind": "code", "summary": "Count words and sum them up. " + MARK,
                "steps": [SCRIPT_PLAN["steps"][0],
                          {"id": "s2", "title": "Summary", "kind": "code", "depends_on": ["s1"],
                           "instructions": "Write summary(counts), which returns 'n words, m distinct'."}]}
TRIM_PLAN = {"title": "Mock word table", "kind": "code", "summary": "Count words and show a table. " + MARK,
             "steps": [SCRIPT_PLAN["steps"][0],
                       {"id": "s2", "title": "Table", "kind": "code", "depends_on": ["s1"],
                        "instructions": "Write table(counts), which returns 'word n' lines, most frequent first, "
                                        "and a TOTAL line."}]}
TEXT_PLAN = {"title": "Mock text tools", "kind": "code", "summary": "Three small text helpers. " + MARK, "steps": [
    SCRIPT_PLAN["steps"][0],
    {"id": "s2", "title": "Words", "kind": "code", "depends_on": [],
     "instructions": "Write count_lower(text), which returns a dict of each lower-cased word's count."},
    {"id": "s3", "title": "Letters", "kind": "code", "depends_on": [],
     "instructions": "Write count_letters(text), which returns a dict of each lower-cased letter's count."},
    {"id": "s4", "title": "Echo", "kind": "code", "depends_on": [],
     "instructions": "Write split_words(text), which returns the text's words in order."}]}
VOWELS_PLAN = {"title": "Mock vowels", "kind": "code", "summary": "Count words and vowels. " + MARK, "steps": [
    SCRIPT_PLAN["steps"][0],
    {"id": "s2", "title": "Vowels", "kind": "code", "depends_on": [],
     "instructions": "Write count_vowels(text), which returns a dict of each vowel's count."}]}
SCALE_PLAN = {"title": "Mock scaler", "kind": "code", "summary": "Parse a line and scale numbers. " + MARK, "steps": [
    FILES_PLAN["steps"][0],
    {"id": "s2", "title": "Scale", "kind": "code", "depends_on": [],
     "instructions": "Write tool/scale.py with scale(n), which returns n times the factor 10."}]}
LONE_PLAN = {"title": "Mock note", "kind": "writing", "summary": "A short note. " + MARK, "steps": [
    {"id": "s1", "title": "Note", "kind": "writing", "depends_on": [],
     "instructions": "Write a note of about 50 words thanking a neighbour for watering the plants."}]}
SHELF_PLAN = {"title": "Mock shelf", "kind": "blender", "summary": "A floor and a shelf. " + MARK, "steps": [
    BLENDER_PLAN["steps"][0],
    {"id": "s2", "title": "Shelf", "kind": "blender", "depends_on": ["s1"],
     "instructions": "Stand a shelf chimera_shelf on s1's floor and register it as ctx['objects']['shelf']."}]}
BOLD_PLAN = {"title": "Mock shouting tool", "kind": "code", "summary": "A parser, a shouter and a page. " + MARK,
             "steps": [FILES_PLAN["steps"][0],
                       {"id": "s2", "title": "Bold", "kind": "code", "depends_on": [],
                        "instructions": "Write tool/bold.py with shout(text), which returns text in capitals."},
                       {"id": "s3", "title": "Page", "kind": "code", "depends_on": [],
                        "instructions": "Write web/index.html, a page that says hello."}]}
FIXED_PLAN = {"title": "Mock fixed tool", "kind": "code", "summary": "A parser and a constant. " + MARK, "steps": [
    FILES_PLAN["steps"][0],
    {"id": "s2", "title": "Fixed", "kind": "code", "depends_on": [],
     "instructions": "Write tool/fixed.py with fixed(), which returns 1."}]}
CHECKS_PLAN = {"title": "Mock text counters", "kind": "code", "summary": "Count words, lines and save. " + MARK,
               "steps": [SCRIPT_PLAN["steps"][0],
                         {"id": "s2", "title": "Tally", "kind": "code", "depends_on": [],
                          "instructions": "Write tally(text), which returns how many words text has."},
                         {"id": "s3", "title": "Lines", "kind": "code", "depends_on": [],
                          "instructions": "Write count_lines(text), which returns how many lines text has."},
                         {"id": "s4", "title": "Docs", "kind": "code", "depends_on": [],
                          "instructions": "Write save_doc(text, path), which writes text into a Word file at path."}]}
REFUSE_PLAN = {"title": "Mock shouter", "kind": "code", "summary": "Count words and shout. " + MARK, "steps": [
    SCRIPT_PLAN["steps"][0],
    {"id": "s2", "title": "Shout", "kind": "code", "depends_on": [],
     "instructions": "Write shout(text), which returns text in capitals."}]}
STUB_PLAN = {"title": "Mock glowing room", "kind": "blender", "summary": "A floor, a lamp and a glow. " + MARK,
             "steps": [BLENDER_PLAN["steps"][0],
                       dict(BLENDER_PLAN["steps"][1], title="Dash"),
                       {"id": "s3", "title": "Glow", "kind": "blender", "depends_on": [],
                        "instructions": "Add a glowing plane chimera_s3 and register it as ctx['objects']['s3']."}]}
WRITE_PLAN = {"title": "Mock Lisbon trip", "kind": "writing", "summary": "Weather, then what to pack. " + MARK,
              "steps": [{"id": "s1", "title": "Weather facts", "kind": "research", "depends_on": [],
                         "instructions": "Research the usual May weather in Lisbon."},
                        {"id": "s2", "title": "Packing list", "kind": "writing", "depends_on": ["s1"],
                         "instructions": "Using s1's weather facts, write a short packing list for a May trip to "
                                         "Lisbon."}]}
# A values-only first step (hints.values_step: its title, and s2 depends on it) and the step that reads its value.
# Its pieces are VALUES_VARS and VALUES_OK below, by its title; the stubborn one's title is a test's to put in
# STUBBORN_CTX.
VALUES_STEP = {"id": "s1", "title": "Define variables for the lamp", "kind": "blender", "depends_on": [],
               "instructions": "Keep the lamp's height in SETTINGS_s1 as lamp_height and hand it on to the later "
                               "steps."}
STUBBORN_VALUES_STEP = dict(VALUES_STEP, title="Define the lamp's variables")
VALUES_TITLES = (VALUES_STEP["title"], STUBBORN_VALUES_STEP["title"])
LAMP_POST_STEP = {"id": "s2", "title": "Lamp post", "kind": "blender", "depends_on": ["s1"],
                  "instructions": "Make a point lamp chimera_post_lamp at the height s1 hands on and register it as "
                                  "ctx['objects']['post_lamp']."}
VALUES_PLAN = {"title": "Mock lamp post", "kind": "blender", "summary": "The lamp's height, then the lamp. " + MARK,
               "steps": [VALUES_STEP, LAMP_POST_STEP]}
VALUES_STUBBORN_PLAN = dict(VALUES_PLAN, title="Mock stubborn lamp post", steps=[STUBBORN_VALUES_STEP, LAMP_POST_STEP])
# The stubborn values step with nothing depending on it (a rug of its own beside it, a generic piece): not
# values_step, and its ctx key isn't soft (task.SOFT_IF_USED)
VALUES_LONE_PLAN = {"title": "Mock lamp sizes", "kind": "blender", "summary": "The lamp's height and a rug. " + MARK,
                    "steps": [STUBBORN_VALUES_STEP,
                              {"id": "s2", "title": "Rug", "kind": "blender", "depends_on": [],
                               "instructions": "Lay a square rug plane chimera_s2 and register it as "
                                               "ctx['objects']['s2']."}]}
DEFAULT_PLAN = LONE_PLAN

# ---------------------------------------------------------------- pieces


def _blender(sid, code, provides, uses="none", assumed="none", guard=GUARD):
    return (f"Here is my piece.\n\n```python\n{MARK}\n{code.strip()}\n\n\n{guard.format(sid=sid)}```\n\n"
            f"```handoff\nprovides: {provides}\nuses: {uses}\nassumed: {assumed}\n```\n")


FLOOR_CODE = '''
import bpy

SETTINGS_s1 = {"size": 4.0}


def build_s1(ctx):
    h = SETTINGS_s1["size"] / 2
    mesh = bpy.data.meshes.new("chimera_floor")
    mesh.from_pydata([(-h, -h, 0), (h, -h, 0), (h, h, 0), (-h, h, 0)], [], [(0, 1, 2, 3)])
    floor = bpy.data.objects.new("chimera_floor", mesh)
    ctx["collection"].objects.link(floor)
    ctx["objects"]["floor"] = floor
'''
LAMP_CODE = '''
import bpy

SETTINGS_s2 = {"height": 2.5, "energy": 500.0}


def build_s2(ctx):
    s = SETTINGS_s2
    floor = ctx["objects"].get("floor")
    if floor is None:
        print("chimera: stand-in", "floor")
        floor = bpy.data.objects.new("chimera_floor_standin", None)
        ctx["collection"].objects.link(floor)
    light = bpy.data.lights.new("chimera_lamp", type="POINT")
    light.energy = s["energy"]
    lamp = bpy.data.objects.new("chimera_lamp", light)
    lamp.location = (floor.location.x, floor.location.y, floor.location.z + s["height"])
    ctx["collection"].objects.link(lamp)
    ctx["objects"]["lamp"] = lamp
'''
SHELF_CODE = LAMP_CODE.replace('SETTINGS_s2 = {"height": 2.5, "energy": 500.0}', 'SETTINGS_s2 = {"height": 1.2}') \
    .replace('    light = bpy.data.lights.new("chimera_lamp", type="POINT")\n    light.energy = s["energy"]\n'
             '    lamp = bpy.data.objects.new("chimera_lamp", light)\n',
             '    mesh = bpy.data.meshes.new("chimera_shelf")\n'
             '    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 0.3, 0), (0, 0.3, 0)], [], [(0, 1, 2, 3)])\n'
             '    lamp = bpy.data.objects.new("chimera_shelf", mesh)\n') \
    .replace('ctx["objects"]["lamp"] = lamp', 'ctx["objects"]["shelf"] = lamp')
CRASH_TYPE = 'type="POINTY"'  # not one of the light types: a TypeError in build_s2, in every Blender
FLOOR = _blender("s1", FLOOR_CODE, 'chimera_floor as ctx["objects"]["floor"]', assumed="the floor lies at z = 0")
LAMP_OK = _blender("s2", LAMP_CODE, 'chimera_lamp as ctx["objects"]["lamp"]', 's1\'s ctx["objects"]["floor"]')
LAMP_CRASH = LAMP_OK.replace('type="POINT"', CRASH_TYPE)
SHELF_OK = _blender("s2", SHELF_CODE, 'chimera_shelf as ctx["objects"]["shelf"]', 's1\'s ctx["objects"]["floor"]')
SHELF_CRASH = SHELF_OK.replace('floor.location.y, floor.location.z + s["height"])', 'floor.location.y)')
DASH = LAMP_OK.replace('"chimera: stand-in"', '"chimera: stand\u2011in"')  # gpt-oss's non-breaking hyphen
GLOW_OK = mock_ollama.contract_piece("s3", [])
GLOW_LEAK = GLOW_OK.replace("\nimport bpy\n", "\nimport bpy  # checked in Blender 5.2.2\n", 1)  # a teacher note's

# The values pair (VALUES_PLAN). The values step as the contract has it since Nov 4: its value in SETTINGS_s1, handed
# on in ctx["values"] under the same key, listed under provides, with the guard's new literal; and as the stored tries
# of the values-only steps wrote it (21 of their 45 tries), in a ctx key Chimera's join doesn't make, ctx["variables"],
# with nothing quoted under provides (ctx_channel, the only fault: told, gpt-oss writes VALUES_OK).
VALUES_OK_CODE = '''
import bpy

SETTINGS_s1 = {"lamp_height": 2.5}


def build_s1(ctx):
    ctx["values"]["lamp_height"] = SETTINGS_s1["lamp_height"]
'''
VALUES_VARS_CODE = '''
import bpy

SETTINGS_s1 = {"lamp_height": 2.5}


def build_s1(ctx):
    ctx["variables"] = dict(SETTINGS_s1)
'''
LAMP_POST_CODE = '''
import bpy

SETTINGS_s2 = {"energy": 500.0, "fallback_height": 2.0}


def build_s2(ctx):
    height = ctx["values"].get("lamp_height")
    if height is None:
        print("chimera: stand-in", "lamp_height")
        height = SETTINGS_s2["fallback_height"]
    light = bpy.data.lights.new("chimera_post_lamp", type="POINT")
    light.energy = SETTINGS_s2["energy"]
    lamp = bpy.data.objects.new("chimera_post_lamp", light)
    lamp.location = (0.0, 0.0, height)
    ctx["collection"].objects.link(lamp)
    ctx["objects"]["post_lamp"] = lamp
'''
VALUES_OK = _blender("s1", VALUES_OK_CODE, 'ctx["values"]["lamp_height"]', guard=GUARD_VALUES)
VALUES_VARS = _blender("s1", VALUES_VARS_CODE, "the lamp's height, for the later steps", guard=GUARD_VALUES)
LAMP_POST = _blender("s2", LAMP_POST_CODE, 'chimera_post_lamp as ctx["objects"]["post_lamp"]',
                     's1\'s ctx["values"]["lamp_height"]', guard=GUARD_VALUES)

CAPTION = """## Caption

One warm point lamp hangs low over a bare square floor, and its light pools in a soft circle that fades to shadow
at the edges. Nothing else stands in the room, so the eye goes straight to the glow and the quiet space around it.
The scene feels calm, a little lonely, and ready for whatever is placed under the lamp next.

```handoff
provides: the caption under ## Caption
uses: chimera_lamp from s2
assumed: """ + MARK + """
```
"""
NOTE = """## Note

Thank you so much for watering my plants while I was away. They all look happy and green, and the basil has even
grown taller than when I left. I really appreciate you giving up your time for this, and I would love to return
the favour whenever you travel next.

<!-- """ + MARK + """ -->
"""


def _section(title, sid, uses="none"):
    words = ("This part covers " + title.lower() + " in plain terms with the details a reader needs to act on it. ") * 4
    return (f"## {title}\n\n{words.strip()}\n\n```handoff\nprovides: the section {title}\nuses: {uses}\n"
            f"assumed: {MARK}\n```\n")


def _files(blocks, provides, uses="none", assumed="none", line="File: {}"):
    body = "\n\n".join(f"{line.format(path)}\n```python\n{MARK}\n{code.strip()}\n```" for path, code in blocks)
    return f"{body}\n\n```handoff\nprovides: {provides}\nuses: {uses}\nassumed: {assumed}\n```\n"


PARSER = _files([("tool/parse.py", '''
def parse_line(line):
    """The comma-separated fields of line, stripped, empty ones left out."""
    return [f.strip() for f in line.split(",") if f.strip()]
''')], "tool/parse.py: parse_line(line) -> list of str")
TOTALS_WRONG = _files([("tool/totals.py", '''
from tool.parse import parse_line


def totl(line):
    return sum(int(f) for f in parse_line(line) if f.lstrip("-").isdigit())
''')], "tool/totals.py: total(line) -> int", "parse_line from s1")
TOTALS = TOTALS_WRONG.replace("def totl(line):", "def total(line):")
FORMAT_BROKEN = _files([("tool/fmt.py", '''
def show(n, width=WIDTH):
    return ("total: %d" % n).ljust(width)
''')], "tool/fmt.py: show(n) -> str")
SCALE_OK = _files([("tool/scale.py", '''
FACTOR = 10


def scale(n, factor=FACTOR):
    """n times the factor."""
    value = n * factor
    return value
''')], "tool/scale.py: scale(n) -> number")
SCALE_CRASH = SCALE_OK.replace("factor=FACTOR)", "factor=FACTR)")  # a NameError when it is imported
MAIN = _files([("tool/main.py", '''
from tool.totals import total


def main():
    print("total: %d" % total("1,2,3"))


if __name__ == "__main__":
    main()
''')], "tool/main.py: main(), run with python3 tool/main.py", "total from s2")
BOLD = _files([("tool/bold.py", '''
def shout(text):
    """text in capitals."""
    return text.upper()
''')], "tool/bold.py: shout(text) -> str", line="**File: {}**")  # gpt-oss's decorated File line
PAGE = ("File: web/index.html\n```html\n<!-- " + MARK + " -->\n<p>hello</p>\n```\n\n"
        "```handoff\nprovides: web/index.html, the hello page\nuses: none\nassumed: none\n```\n")
FIXED_OK = _files([("tool/fixed.py", '''
def fixed():
    """Always 1."""
    return 1
''')], "tool/fixed.py: fixed() -> int")
FIXED_BAD = FIXED_OK.replace("File: tool/fixed.py\n", "Here is the file.\n\n")  # no File line: no_file_line


def _script(code, provides, uses="none"):
    return (f"My piece.\n\n```python\n{MARK}\n{code.strip()}\n```\n\n"
            f"```handoff\nprovides: {provides}\nuses: {uses}\nassumed: none\n```\n")


COUNT = _script('''
def count_words(text):
    """Each lower-cased word's count."""
    counts = {}
    for w in text.lower().split():
        counts[w] = counts.get(w, 0) + 1
    return counts
''', "count_words(text) -> dict")
REPORT_OK = _script('''
TOP = 10


def report(counts, top=TOP):
    """Lines "word: n", most frequent first."""
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    return ["%s: %d" % kv for kv in items]
''', "report(counts) -> list of str", "count_words from s1")
REPORT_CRASH = REPORT_OK.replace("top=TOP)", "top=TOPN)")  # a NameError when it is imported

SUMMARY_CRASH = _script('''
def summary(counts, sep=SEP):
    return "%d words, %d distinct" % (sum(counts.values()), len(counts))
''', "summary(counts) -> str", "count_words from s1")
SUMMARY_REWRITE = _script('''
def _total(counts):
    """How many words in all."""
    return sum(counts.values())


def summary(counts):
    """'n words, m distinct'."""
    words = _total(counts)
    distinct = len(counts)
    return "%d words, %d distinct" % (words, distinct)
''', "summary(counts) -> str", "count_words from s1")  # a repair that rewrites most of the piece
TABLE_CRASH = _script('''
WIDTH = 12
TOP = 20
SEP = " "


def _cell(word, width):
    return word[:width].ljust(width)


def _row(word, n, width=WIDTH):
    return "%s%s%d" % (_cell(word, width), SEP, n)


def _ranked(counts, top=TOP):
    rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return rows[:top]


def _footer(counts, width=WIDTH):
    total = sum(counts.values())
    return "%s%s%d" % (_cell("TOTAL", width), SEP, total)


def table(counts, width=WIDHT, top=TOP):
    lines = [_row(w, n, width) for w, n in _ranked(counts, top)]
    if not lines:
        return []
    lines.append(_footer(counts, width))
    return lines
''', "table(counts) -> list of str", "count_words from s1")  # a NameError when it is imported
TABLE_TRIMMED = TABLE_CRASH.replace("width=WIDHT", "width=WIDTH").replace(
    "\n\n\ndef _footer(counts, width=WIDTH):\n    total = sum(counts.values())\n"
    "    return \"%s%s%d\" % (_cell(\"TOTAL\", width), SEP, total)", "").replace(
    "    lines.append(_footer(counts, width))\n", "")  # the repair fixes the name and drops the TOTAL line its step asks for
WORDS_OK = _script('''
def count_lower(text):
    """Each lower-cased word's count."""
    counts = {}
    for w in text.lower().split():
        counts[w] = counts.get(w, 0) + 1
    return counts
''', "count_lower(text) -> dict")
WORDS_EMPTY = _script('''
def count_lower(text):
    """Each lower-cased word's count."""
    return {}
''', "count_lower(text) -> dict")  # imports fine, fails its tests
LETTERS_CALL = _script('''
def count_letters(text):
    """Each lower-cased letter's count."""
    counts = {}
    for ch in text.lower():
        if ch.isalpha():
            counts[ch] = counts.get(ch, zero) + 1
    return counts
''', "count_letters(text) -> dict")  # imports fine, a NameError once called (by its tests)
LETTERS_CASE = LETTERS_CALL.replace("text.lower()", "text").replace("zero", "0")  # runs, keeps the case
VOWELS_RENAMED = _script('''
def vowels(text):
    """Each vowel's count."""
    return {v: text.count(v) for v in "aeiou" if v in text}
''', "vowels(text) -> dict")  # the wrong name: fails the tests that only ask for count_vowels
VOWELS_EMPTY = _script('''
def count_vowels(text):
    """Each vowel's count."""
    return {}
''', "count_vowels(text) -> dict")  # passes them, and so does a hollow copy
ECHO = _script('''
def split_words(text):
    """The text's words in order."""
    # ''' + hints.FORMAT_NOTE + '''
    return text.split()
''', "split_words(text) -> list of str")  # repeats a teacher-only note
TALLY = _script('''
def tally(text):
    """How many words text has."""
    return len(text.split())
''', "tally(text) -> int")
LINES = _script('''
def count_lines(text):
    """How many lines text has."""
    return len(text.splitlines())
''', "count_lines(text) -> int")
DOCS = _script('''
import docx


def save_doc(text, path):
    """Write text into a Word file at path."""
    doc = docx.Document()
    doc.add_paragraph(text)
    doc.save(path)
''', "save_doc(text, path)")  # python-docx: not in the sandbox's standard library
SHOUT = _script('''
def shout(text):
    """text in capitals."""
    return text.upper()
''', "shout(text) -> str")

TESTS = {
    "Parser": 'from tool.parse import parse_line\nassert parse_line(" a, b ,,c ") == ["a", "b", "c"]\n',
    "Totals": 'from tool.totals import total\nassert total("1, 2, x, 4") == 7\n',
    "Count": 'assert count_words("A a b") == {"a": 2, "b": 1}\n',
    "Words": 'assert count_lower("A a b") == {"a": 2, "b": 1}\n',
    "Letters": 'assert count_letters("Aa b") == {"a": 2, "b": 1}\n',
    "Vowels": 'assert callable(count_vowels)\n',  # names the symbol, checks nothing it does
    "Bold": 'from tool.bold import shout\nassert shout("ab") == "AB"\n',
    "Tally": '# wrong count\nassert tally("a b c") == 4, "three words"\n',  # the tests' own mistake
    "Lines": '# guessed module\nfrom wordtool import count_lines\nassert count_lines("a\\nb") == 2\n',
    "Docs": '# needs docx\nsave_doc("hi", "out.docx")\nimport os\nassert os.path.exists("out.docx")\n',
    "Shout": '# starts a process\nimport subprocess\nsubprocess.run(["python3", "-c", "pass"])\n'
             'assert shout("a") == "A"\n',
}
# A tests call that shows the writer tests holding one of these lines (a rewrite, a retry after a refusal) gets
# that entry's tests; "" when it has none better.
REWRITES = {
    "# wrong count": 'assert tally("a b c") == 3, "three words"\nassert tally("") == 0\n',
    "# guessed module": "",
    "# needs docx": "",
    "# starts a process": 'assert shout("ab") == "AB"\n',
}
TODAY_CODE = "```python\n" + MARK + "\ndef total(line):\n    return sum(int(x) for x in line.split(','))\n```\n"


def generic_piece(mode, sid, title):
    """A piece of the mode for a step this module has no canned piece for."""
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") or "part"
    if mode == "blender":
        return mock_ollama.contract_piece(sid, [])
    if mode == "python-script":
        return _script(f"def {slug}():\n    return {slug!r}\n", f"{slug}()")
    if mode == "files":
        return _files([(f"{slug}.py", f"def {slug}():\n    return {slug!r}\n")], f"{slug}.py: {slug}()")
    return _section(title, sid)


def worker_reply(model, system, user, vary=(), seed=0):
    """A contract or lone worker's reply, by the step, its mode, the repair message and the model. A Blender step whose
    title is in vary gets a reply that differs by the call's seed (so its samples differ)."""
    text = _worker_reply(model, system, user)
    m = re.search(r"^Your step, s\d+: (.+)$", user, re.M)
    if m and m.group(1).strip() in vary and text.startswith("Here is my piece."):
        text = text.replace("Here is my piece.", f"Here is my piece, try {seed % 997}.", 1)
    return text


def _worker_reply(model, system, user):
    text = _canned(model, system, user)
    m = re.search(r"^Your step, s\d+: (.+)$", user, re.M)
    failed = [d for d, v in dep_honesty.deps_of([{"role": "user", "content": user}]).items() if v["failed"]]
    if not failed or (m and m.group(1).strip() in STUBBORN):
        return text
    if model == SECOND or any(form in system for form in dep_honesty.TELL_FORMS):
        return honest(text, failed)
    return text


_USES = re.compile(r"^(uses|assumed):[ \t]*(.*)$", re.M)


def honest(text, failed):
    """text with its handoff saying what the failed dependencies gave it, in the forms dep_honesty's tell asks for:
    a uses item that names one of failed ("chimera_lamp from s2", "s1's ctx[...]") written "s2: chimera_lamp
    (failed)", an assumed line of none made "s2 failed: ..."; the rest as it is."""
    def item(it):
        sid = next((d for d in failed if re.search(r"\b%s\b" % d, it)), None)
        if sid is None:
            return it
        name = re.sub(r"\s*\bfrom %s\b|\b%s['’]s\s*" % (sid, sid), "", it).strip() or "its output"
        return f"{sid}: {name} (failed)"

    def line(m):
        key, value = m.group(1), m.group(2).strip()
        if key == "uses":
            if value.lower() in ("", "none"):
                return m.group(0)
            return "uses: " + ", ".join(item(x.strip()) for x in value.split(","))
        if value.lower() in ("", "none"):
            steps = failed[0] if len(failed) == 1 else ", ".join(failed[:-1]) + " and " + failed[-1]
            return f"assumed: {steps} failed: made do without {'it' if len(failed) == 1 else 'them'}"
        return m.group(0)
    head, sep, rest = text.rpartition("```handoff\n")
    return head + sep + _USES.sub(line, rest) if sep else text


def _canned(model, system, user):
    m = re.search(r"^Your step, (s\d+): (.+)$", user, re.M)
    sid, title = (m.group(1), m.group(2).strip()) if m else ("s1", "")
    joins = system.split("How Chimera joins your piece:\n", 1)[-1]
    mode = ("blender" if joins.startswith("Write one python code block for Blender") else
            "python-script" if joins.startswith("Write Python 3 functions") else
            "files" if joins.startswith("Give each file you own") else "section")
    repair = REPAIR in user
    second = model == "qwen3.8:27b"
    if mode == "blender":
        if title == "Floor":
            return FLOOR
        if title == "Lamp":
            return LAMP_OK if repair else LAMP_CRASH
        if title == "Shelf":
            return SHELF_OK if second else SHELF_CRASH
        if title == "Dash":
            return DASH
        if title == "Glow":
            return GLOW_OK if second else GLOW_LEAK
        if title in VALUES_TITLES:
            if title in STUBBORN_CTX:
                return VALUES_VARS
            return VALUES_OK if second or any(form in system for form in CTX_FORMS) else VALUES_VARS
        if title == "Lamp post":
            return LAMP_POST
    elif mode == "files":
        if title == "Parser":
            return PARSER
        if title == "Totals":
            return TOTALS if second else TOTALS_WRONG
        if title == "Format":
            return FORMAT_BROKEN
        if title == "Scale":
            return SCALE_OK if repair else SCALE_CRASH
        if title == "Main":
            return MAIN
        if title == "Bold":
            return BOLD
        if title == "Page":
            return PAGE
        if title == "Fixed":
            return FIXED_OK if hints.FAILED_ON in system else FIXED_BAD
    elif mode == "python-script":
        if title == "Count":
            return COUNT
        if title == "Report":
            return REPORT_OK if repair else REPORT_CRASH
        if title == "Summary":
            return SUMMARY_REWRITE if repair else SUMMARY_CRASH
        if title == "Table":
            return TABLE_TRIMMED if repair else TABLE_CRASH
        if title == "Words":
            return WORDS_OK if second else WORDS_EMPTY
        if title == "Letters":
            return LETTERS_CASE if second else LETTERS_CALL
        if title == "Echo":
            return ECHO
        if title == "Vowels":
            return VOWELS_EMPTY if second else VOWELS_RENAMED
        if title in ("Tally", "Lines", "Docs", "Shout"):
            return {"Tally": TALLY, "Lines": LINES, "Docs": DOCS, "Shout": SHOUT}[title]
    else:
        if title == "Caption":
            return CAPTION
        if title == "Note":
            return NOTE
    return generic_piece(mode, sid, title)


def _today(system):
    m = re.search(r"^→ (\d+)\. (.+)$", system, re.M)
    title = m.group(2).strip() if m else ""
    if title in ("Totals", "Parser", "Format", "Main", "Count", "Report"):
        return TODAY_CODE
    return mock_ollama.today_script("step%s" % (m.group(1) if m else "1"))


# ---------------------------------------------------------------- the server

class FixtureIndex:
    """An EvalIndex that lets the test-fixture mark through and nothing else, so a test can follow canned text through
    the seed and build filters; tools/check_overlap.py (its own EvalIndex) still flags every line that carries it."""

    MARK_HIT = "mark:test-fixture"

    def __init__(self, index):
        self.index = index

    def check(self, text, threshold=0.5):
        return [h for h in self.index.check(text, threshold) if h[0] != self.MARK_HIT]


class FakeOllama:
    """The stand-in, on 127.0.0.1 at a free port, until stop(). plans: {goal: plan} (a goal found in the planner's
    message; DEFAULT_PLAN else); bad_plans: goals whose hydra:1.0 plan can't be read (so gpt-oss:120b is asked);
    review_done: goals the reviewer calls done; scene_reject and prose_low: step titles the judges turn down;
    scene_why: {step title: why} the scene judge turns a step down with (its reason, the mark beside it);
    prose_scores: {(step title, model): score} the prose judge gives instead; errors: models whose calls fail (HTTP
    500), to test a failed call; vary: Blender step titles whose samples differ; models: the models it has
    (/api/tags and /api/show)."""

    def __init__(self, log_path=None):
        self.log_path = log_path
        self.plans = {}
        self.bad_plans = set()
        self.review_done = set()
        self.scene_reject = set()
        self.scene_why = {}
        self.prose_low = set()
        self.prose_scores = {}
        self.errors = set()
        self.vary = set()
        self.models = set(MODELS)
        self.lock = threading.Lock()
        self.calls = []  # {"job", "model", "body"} per /api/chat call
        self.other = []  # the other paths asked
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                with fake.lock:
                    fake.other.append(self.path)
                if self.path == "/api/version":
                    return self._send(200, {"version": "0.0.0-fake"})
                if self.path == "/api/tags":
                    return self._send(200, {"models": [{"name": m, "model": m, "digest": "0" * 12, "size": 1}
                                                       for m in sorted(fake.models)]})
                if self.path == "/api/ps":
                    return self._send(200, {"models": []})
                self._send(404, {"error": "not found"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                b = json.loads(self.rfile.read(n) or b"{}")
                if self.path != "/api/chat":
                    with fake.lock:
                        fake.other.append(self.path)
                    if self.path == "/api/show":
                        if b.get("model") not in fake.models:
                            return self._send(404, {"error": "model not found"})
                        return self._send(200, {"details": {"family": "fake"}, "capabilities": ["completion"],
                                                "model_info": {"fake.context_length": 131072}})
                    if self.path == "/api/generate":
                        return self._send(200, {"done": True})
                    return self._send(404, {"error": "not found"})
                job, text = fake.answer(b)
                with fake.lock:
                    fake.calls.append({"job": job, "model": b.get("model"), "body": b})
                    if fake.log_path:
                        with open(fake.log_path, "a", encoding="utf-8") as f:
                            f.write(json.dumps({"job": job, "body": b}, ensure_ascii=False) + "\n")
                if text is None:
                    return self._send(500, {"error": "fake: this model fails"})
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                step = max(1, len(text) // 3)
                chunks = [{"message": {"role": "assistant", "content": text[i:i + step]}, "done": False}
                          for i in range(0, len(text), step)]
                chunks.append({"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop",
                               "prompt_eval_count": sum(len(m["content"]) for m in b.get("messages") or []) // 4,
                               "eval_count": len(text) // 4 + 3, "total_duration": 2000000, "load_duration": 1000,
                               "prompt_eval_duration": 1000, "eval_duration": 1000000})
                try:
                    for ch in chunks:
                        self.wfile.write((json.dumps(ch) + "\n").encode())
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()

    def jobs(self):
        """[(job, model)] of every chat call so far."""
        with self.lock:
            return [(c["job"], c["model"]) for c in self.calls]

    def bodies(self, job=None):
        with self.lock:
            return [c["body"] for c in self.calls if job is None or c["job"] == job]

    def answer(self, body):
        """(job, reply text) for one /api/chat body; the text is None for a call that fails."""
        model = body.get("model") or ""
        msgs = body.get("messages") or []
        system = msgs[0]["content"] if msgs and msgs[0]["role"] == "system" else ""
        user = msgs[-1]["content"] if msgs else ""
        everything = "\n".join(m.get("content") or "" for m in msgs)
        job, text = self._answer(model, system, user, (body.get("options") or {}).get("seed") or 0, everything)
        return job, (None if model in self.errors else text)

    def _goal_in(self, user, table):
        return next((g for g in table if g and g in user), None)

    def _answer(self, model, system, user, seed, everything=""):
        shown = next((k for k in REWRITES if k in everything), None)  # earlier tests of ours, shown to the writer
        if shown is not None:
            return "tests_rewrite", json.dumps({"tests": (MARK + "\n" + REWRITES[shown]) if REWRITES[shown] else ""})
        if system == topics.SEED_SYSTEM:
            m = re.search(r"Write (\d+) different requests", user)
            k = int(m.group(1)) if m else 2
            what = re.search(r"Each asks for (.+?)\.\n", user)
            topic = re.search(r"^Topic: (.+)$", user, re.M)
            return "seed", json.dumps({"tasks": [
                f"Please make me {what.group(1) if what else 'something'}, on {topic.group(1) if topic else 'anything'}"
                f" (request {j + 1}). {MARK}" for j in range(k)]})
        if system.startswith(mock_ollama.PLANNER_OPENING):
            goal = self._goal_in(user, self.plans)
            if model == "hydra:1.0" and self._goal_in(user, self.bad_plans):
                return "plan", "I would split this into a few steps. " + MARK
            return "plan", json.dumps(self.plans[goal] if goal else DEFAULT_PLAN)
        if system.startswith(mock_ollama.REVIEW_OPENING):
            done = self._goal_in(user, self.review_done) is not None
            return "review", json.dumps({"done": done, "score": 90 if done else 60,
                                         "critique": "" if done else "Make the light warmer. " + MARK})
        if system.startswith(mock_ollama.CONTRACT_OPENING) or system.startswith(mock_ollama.LONE_OPENING):
            return "worker", worker_reply(model, system, user, self.vary, seed)
        if system.startswith(mock_ollama.TODAY_OPENING):
            return "today", _today(system)
        if system == judges.SCENE_SYSTEM:
            title = re.search(r"^The step under review, s\d+: (.+)$", user, re.M)
            name = title.group(1).strip() if title else ""
            if name in self.scene_why:  # the mark beside the reason: its "never" is a fault word to overruled()
                return "scene_judge", json.dumps({"ok": False, "why": self.scene_why[name], "fixture": MARK})
            ok = name not in self.scene_reject
            return "scene_judge", json.dumps({"ok": ok, "why": ("it built its step. " if ok else "the wrong thing. ")
                                              + MARK})
        if system == judges.PROSE_SYSTEM:
            title = re.search(r"^The step under review, s\d+: (.+)$", user, re.M)
            name = title.group(1).strip() if title else ""
            score = self.prose_scores.get((name, model), 2 if name in self.prose_low else 5)
            problems = [] if score == 5 else [MARK] if score < 4 else ["The list could be shorter. " + MARK]
            return "prose_judge", json.dumps({"score": score, "problems": problems, "note": MARK})
        if system.startswith(judges.TESTS_SYSTEM[:60]):
            title = re.search(r"^The step under review, s\d+: (.+)$", user, re.M)
            code = TESTS.get(title.group(1).strip() if title else "", "")
            return "tests", json.dumps({"tests": (MARK + "\n" + code) if code else ""})
        return "other", "OK " + MARK


# ---------------------------------------------------------------- shared setup

def given_chimera():
    """$CHIMERA_BIN when it names a binary that can run, else None."""
    given = os.environ.get("CHIMERA_BIN") or ""
    return given if os.path.isfile(given) and os.access(given, os.X_OK) else None


HAVE_CHIMERA = bool(GO or given_chimera())


def build_chimera(dest_dir):
    """A Chimera binary at dest_dir/chimera (removed first: macOS kills a signed binary overwritten in place): a copy
    of $CHIMERA_BIN when it names one (copy_chimera), else built from app/. Raises RuntimeError if the build fails."""
    if given_chimera():
        return copy_chimera(given_chimera(), dest_dir)
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, "chimera")
    if os.path.exists(path):
        os.remove(path)
    env = dict(os.environ, PATH=os.path.dirname(GO) + os.pathsep + os.environ.get("PATH", ""))
    p = subprocess.run([GO, "build", "-o", path, "."], cwd=_paths.APP, capture_output=True, text=True, env=env,
                       timeout=900)
    if p.returncode:
        raise RuntimeError("go build failed: " + p.stderr[-3000:])
    return path


def copy_chimera(binary, dest_dir):
    """A copy of a Chimera binary at dest_dir/chimera (removed first: macOS kills a signed binary overwritten in
    place), for a run that names one ($CHIMERA_BIN) instead of building it."""
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, "chimera")
    if os.path.exists(path):
        os.remove(path)
    shutil.copy2(binary, path)
    return path


def binary_request(binary, plan, goal, inputs, names):
    """What --hydra-worker-request prints for a step record's inputs, run directly (not through datagen.chimera's
    memo): the check that a stored training request is exactly Chimera's. names: {version: sheet}."""
    payload = {"plan": plan, "index": inputs["index"], "outputs": inputs["outputs"], "goal": goal,
               "names": names.get(inputs.get("names")) or "", "names_gate": True,
               "critique": inputs.get("critique") or ""}
    if inputs.get("prev_result") is not None:
        payload["prev_result"] = inputs["prev_result"]
    if inputs.get("crash") is not None:
        payload["piece"], payload["crash"] = inputs["piece"], inputs["crash"]
    p = subprocess.run([binary, "--hydra-worker-request"], input=json.dumps(payload, ensure_ascii=False).encode(),
                       capture_output=True, timeout=60)
    if p.returncode:
        raise RuntimeError(p.stderr.decode()[-500:])
    return json.loads(p.stdout)
