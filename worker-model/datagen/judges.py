"""The teacher's judges and the tests writer: the messages each is sent and lenient readers of their replies
(DESIGN.md, "judges.py"; the plan's scene judge, prose judge and teacher-written tests).

    msgs = scene_messages(goal, plan, i, handoff, scene)
    verdict = parse_scene(llm.call("gpt-oss:120b", msgs, purpose="judge", fmt=FMT, options=OPTIONS).content)

The rubrics here are Claude-written instructions, which the plan allows; the replies are the judges' own and are never
training data, and neither are the tests, which only run in the sandbox. Every judge runs at temperature 0 with
format json (FMT, OPTIONS) on gpt-oss:120b, with qwen3.8:27b as a second opinion where the caller asks for one: the
messages are the same for both. A reader takes the first JSON object in a reply (the whole reply, else the first
{...} that decodes, so a reply wrapped in prose or a code fence still reads) and returns None for anything it can't
use, so the caller can ask again or count the judge as silent.

The prose judge sees the person's task under GOAL_HEAD, and the tests writer under TESTS_GOAL_HEAD, both saying the
worker never saw it: Chimera's worker request carries the plan, the step and its dependencies' pieces, never the goal,
and in the smoke (Nov 3) the prose judge marked sections down for not using a CSV that only the goal held. The tests
writer's head says to test against the step, since it judges nothing. The scene judge hasn't seen the goal since Nov 5
(scene_messages). The rubrics say what an honest reply to a step
whose material isn't in its request looks like. The prose judge and the tests writer see the dependencies' pieces
under one budget (DEPS_BUDGET), cut as Chimera's pieceCap cuts the combine's, so a name late in a long dependency is
still there.

- scene: did a Blender piece, run alone, build what its step asks and nothing a sibling step owns? {"ok", "why"}.
  The listing is what the run measured (blender_gate._scene), and the judge is told never to fail a piece for what
  it can't show: 7 of the smoke's 8 scene-judge drops were false, 6 for a default engine or world the listing showed
  as if the piece set it, or for modifiers and keyframes it left out, and 1 for an object registered under the two
  ctx keys the plan named it by. The engine's two labels (the factory default, which can't tell whether the piece
  set it; set by the piece), a size before modifiers ("base_size": a dependency's stand-in can leave a modifier
  nothing to show) and a field's "(N more not listed)" are the gate's (blender_gate), explained in SCENE_SYSTEM.
  Since Nov 4 the listing has the keys a piece put in ctx["values"] ("ctx_values", keys only, when there are some:
  the contract's channel for plain values), and the rubric names them beside the ctx["objects"] keys, so a values
  step's handoff is seen and not read as a piece that made nothing. Since Nov 5 (the fourth smoke's audit: all 4 of
  its Blender rejections judged what the rubric forbids) a location says where the geometry is beside the object's
  origin (blender_gate._where), the rubric says the contract's shape replaces any output form a step names and that
  a step's numbers are measured elsewhere, the judge no longer sees the goal (scene_messages), and a rejection whose
  only reasons are sizes, positions or an output form the step names is overruled (overruled; task.Round.judge),
  since Nov 6 only when each size or position claim rests on what the gate's readers read (a size's three sides, a
  point) for the thing it names (claims, readings).
- prose: does a section do its step, only its step, in the plan's terms, with no invented sources, no claims it
  couldn't know (a research step's "(unverified)" covers an uncertain claim, never a test it says was run, as in
  prose_gate), and items that agree? {"score" 1-5, "problems"}; kept at PROSE_KEEP (4) or more (prose_kept; its
  strict PROSE_STRICT (5) has no caller since Nov 4: a section with a dependency missing needs qwen3.8's keep).
- tests: plain asserts for a code step's functions by the names the plan gives, written before any candidate is
  seen, so they can be checked against a stub and the candidates (code_gate.tests_check). The reply is JSON with the
  code in "tests"; a fenced python block or bare code reads too. Tests that start a process, guess names, don't
  compile or reach no assert are refused (parse_tests_why says why), and the writer is told why once
  (TESTS_REFUSED, tests_retry_messages). When tests fail every candidate that passed everything else, the writer can
  be asked once more (tests_rewrite_messages), shown only each failure's assert line, error and the candidate's
  provides names, never its code.
"""
from __future__ import annotations

import ast
import json
import re

from contract import validate as cv
from contract.goport import code_blocks, python_lang
from contract.today import piece_cap

FMT = "json"
OPTIONS = {"temperature": 0}
PROSE_KEEP = 4
PROSE_STRICT = 5  # prose_kept(strict=True): only a section the judge found nothing wrong with
TESTS_OK = "tests ok"  # code_gate.TESTS_OK: the line that says the tests ran to their end
GOAL_HEAD = "The person's task (the worker never saw it; judge against its request):"
# The tests writer's own head: it judges nothing, and "judge against its request" blurred TESTS_SYSTEM's "Test this
# step's instructions, not the person's whole task".
TESTS_GOAL_HEAD = "The person's task (the worker never saw it; test against its step):"
_STEP_CUT = 600  # characters of another step's instructions in the outline
# Characters of all of a step's dependencies' pieces together, as the prose judge and the tests writer see them, cut as
# Chimera's combine cuts its pieces (pieceCap): the shortest stay whole, only the longest are cut. Until Nov 4 each was
# cut to 4,000, and the judge called names past the cut "invented": in the labelled set's 28 rows with a dependency over
# 4,000 (6 or 7 dependencies, 28,000-40,000 characters in all) Priya, Sophie and "Too Good To Go" were past it, and
# judged with them whole, drops of the 26 with nothing invented went from 15 to 12 while both invented texts stayed
# dropped (results/DATAGEN-SMOKE.md, "Prose: the claims rules and the judge"). At 40,000 those 28 prompts are byte for
# byte the ones judged whole and the other 183 are unchanged; at 36,000 the 7-dependency rows would lose the last
# 1,632-1,942 characters of their two longest. Every stored call of both smoke runs sees its dependencies whole (at most
# 16,032 in all, a tests writer's; 11 tests calls and 3 rewrites change, no prose call). The largest prompt of them all,
# 53,288 characters (a labelled row), estimates 17,907 tokens (common.msgs_tokens, bytes / 3), 22,003 with ROOM, and
# gpt-oss counted at most 13,494 on such prompts; it reads 3.6-4.5 characters a token on the second run's stored calls,
# and its replies were at most 1,782 tokens for a judge and 4,190 for the tests writer. The worst the budget lets in
# (seven steps, six dependencies at the validator's largest piece, the section as large, 12,000 of earlier tests) stays
# in gpt-oss:120b's fixed 32,768 (llm.ctx_for: estimate plus ROOM up to 30,000) for the judge and the tests writer with
# an 8,000-character goal, and for a rewrite with a 1,500-character goal (the smoke runs' longest is 1,458) and eight
# different failures (28,493); only a rewrite with an 8,000-character goal and six different failures or more (30,007)
# would get 65,536, a reload, never a cut.
DEPS_BUDGET = 40000
# Characters of the scene listing. In the smoke a listing of names and types was at most 590 characters (12 objects);
# with sizes, locations and modifiers an object takes about 200, so 12,000 shows about 55 before the longest list is
# shortened (_listing). With an 8,000-character goal, seven steps and a 2,500-character step, the judge's messages
# come to about 10,700 estimated tokens, a third of gpt-oss:120b's fixed 32,768.
_SCENE_CUT = 12000
_TESTS_CUT = 12000  # characters of the earlier tests shown to a rewrite
_FAILURE_CUT = 300  # characters of each part of a failure shown to a rewrite


SCENE_SYSTEM = """You check one step of a Blender task that a planner split into steps. Each step's piece is a Python script; this one was run alone, headless, in Blender's factory scene, and you get a listing of what the run measured: the objects it created, with their types and, as far as they were measured, sizes, locations, modifiers, animation, lights' power and direction and cameras; the materials, collections, node groups and actions; the world and the render engine; and the keys it registered in ctx["objects"] for other steps and the values it put in ctx["values"] for them (the factory cube, camera and light are left out). The worker that wrote the piece saw only the plan, its step and its dependencies' pieces (its request), never the person's task. Decide two things from the plan and that listing only:

1. Did the piece build what its step asks for? Every thing the step's instructions say to make should be stood for by at least one object, material, collection, node group, action or ctx key, judging by names, types and what was measured. Names may differ from the instructions' words (chimera_table_top for "table"), one object may stand for several parts, and one object may be registered under several ctx keys, one for each name the plan gives it.
2. Did it build only its own step? Making something another step of the plan owns (the lighting step also building the table) fails.

Running alone, a piece has none of its dependencies' work, so it may make a simple stand-in for what it uses from them: in a run without a dependency's work, empties or placeholders named after that dependency's objects, or marked as stand-ins, are stand-ins, not another step's work. Helper objects a step needs (an empty to aim at, a camera target) are fine. When a step names material its request doesn't contain (an image, a file, measurements), saying so, leaving the values out or listing them under "assumed" in the handoff, and building a plain fallback counts as doing the step.

Every piece has the one shape its request sets: a Python block with a settings dict and a build function, which Chimera runs with the other steps' pieces in one script, saving or rendering once after the last step. That shape replaces any form of output a step names for its code (the code in a string variable, a script returned as text, printed, exported or written to a .py file, the steps' scripts combined into one), so never fail a piece for not giving its code in that form: judge what the code built.

The listing shows only what the run measured. Never fail a piece for something it can't show: property values, keyframe values, which material is on which object, render, output or world settings. An engine shown as "(the factory default: the listing can't tell whether the piece set it)" may or may not have been set by the piece, and one shown as set by the piece was assigned by its code; a world shown as the factory world is the one Blender starts with, whose settings the listing can't show. A list that ends "(and N more not shown)" and a field with "(N more not listed)" were cut, so don't fail a piece for something that may be among those. Sizes and locations are there to tell what each object is; an object's "base_size", when listed, is its size before modifiers, and a modifier on a dependency's stand-in may leave nothing to show (0 x 0 x 0), which isn't a piece that made nothing. In locations, "geometry_centre" and "geometry_bottom" are the centre of the box round an object's geometry in world space and the middle of that box's bottom, which say where the object is; "origin" is the object's own origin, which can lie away from its geometry (it stays at the world origin when a transform is applied, say). The sizes, positions and other numbers a step gives are measured against the run by other checks before you see it, using values its dependencies hand it that you don't see: never fail a piece for a size, a position or a number. Don't judge looks, sizes, positions, colours, code style or how well it would render (other checks measure those): only whether the right things exist. A piece that made nothing fails. If the step only changes settings (render, world, colour management) and the listing shows no objects, judge by its ctx keys and values and what the instructions ask; a settings-only step that was asked for no objects passes with none.

Reply with one JSON object and nothing else: {"ok": true or false, "why": "one short sentence: what is missing or extra, or what it built"}"""

PROSE_SYSTEM = """You grade one section of a written result that a planner split into steps; each step's section is written separately and Chimera joins them in plan order. The worker that wrote it saw only the plan, its step and its dependencies' pieces (its request), never the person's task. Grade only this step's section, against the plan:

- Does it do what its step's instructions ask, each point of them?
- Does it do only its step: no introduction, conclusion or summary of the whole project unless that is its step, and nothing another step covers?
- Does it use the plan's terms and its dependencies' names and facts, without contradicting them?
- Does it invent nothing: no made-up sources, links, quotes, studies, statistics or exact figures presented as fact? In a research step an uncertain claim marked (unverified) is fine and an unmarked invented one is not, but no mark makes a test or benchmark it says was run true.
- Does it claim only what it could know? Tests it says were run, measurements it says were taken, figures it says come from a source or a website, and named contacts with phone numbers or emails are invented when neither its step nor its dependencies' pieces give them; listing them under "assumed" in the handoff doesn't make a claim stated as fact in the section true.
- Do its items agree with each other: an order or a route that holds together (no stop past the destination), totals and counts that add up, the same figure the same wherever it appears?
- When its step names material its request doesn't contain (data, a file, a log), saying so and leaving the values null or under "assumed" counts as doing the step; making them up doesn't.
- Does it match any tone, audience and length the step gives, and never mention being an AI, a model or other workers?

Score it 1 to 5:
5 does its step fully and only its step, in the plan's terms, with nothing invented;
4 does its step with small problems a light edit would fix (an invented fact or source, a claim it couldn't know or items that contradict each other is never a small problem);
3 does part of its step, or strays into other steps, or is padded;
2 mostly misses its step, or invents sources, facts or measurements, or its items contradict each other;
1 wrong, empty or off-topic.

Reply with one JSON object and nothing else: {"score": 1 to 5, "problems": ["one short line per problem"]} (an empty list when there are none)."""

TESTS_SYSTEM = """You write tests for one step of a Python project that a planner split into steps. Other models write the steps' code; your tests decide whether a piece of code does its step, so they must check what the step asks for, by the names the plan and the step give, and nothing else. The worker writing the step sees only the plan, its step and its dependencies' pieces, never the person's task.

The tests run against the project as it stands when this step is done: the earlier steps' code plus this step's, in a sandbox with Python 3 and its standard library only, no network, no other programs, writes only in the current folder, and a 10 second limit.

Rules:
- Plain top-level assert statements (with a message where it helps), no unittest or pytest, no test functions left uncalled.
- Test this step's instructions, not the person's whole task: a requirement of the task that the step doesn't repeat belongs to another step.
- Call only the functions, classes, methods and constants that this step, the plan or a dependency's piece writes as code, the way they describe them. Never guess a name or a module: no list of possible names tried in turn, no search of globals(), dir() or the folder for one. Every test must exercise this step's own names; the earlier steps' names may be used to set things up. Tests that pass without this step's code are thrown away. If the step names nothing that can be called and no file to check, reply with empty tests.
- Check behaviour the step's instructions make certain: return values, raised errors, state changes, files written in the current folder. Don't check what they leave open (the order of ties, exact wording, formatting, printed output) unless they specify it. An example in the step is one acceptable result, not the exact text to expect.
- Data your tests write for the code to read has a layout the step or a dependency's piece gives; if neither gives one, don't test reading it.
- Test a command-line entry point in-process: set sys.argv to a list, capture its output with contextlib.redirect_stdout, and catch SystemExit and check its code (the exit status). Never start a process (subprocess, os.system, os.fork, os.exec*, multiprocessing, python -m): the sandbox refuses them.
- For a file that isn't Python (JSON, SQL, HTML, a config file), check only that it exists at the step's path, that JSON parses, and the exact values the step gives. Never match a file's source text, Python's included.
- Deterministic: no randomness without a fixed seed, no clocks, no network, nothing that reads standard input or waits.
- Small inputs, so it all finishes in well under 10 seconds.
- Read your asserts once more in order: each must hold for a correct piece at the point it runs, after what the lines before it did.
- End with print("tests ok").
{how}

Reply with one JSON object and nothing else: {{"tests": "the Python code"}} ({{"tests": ""}} when nothing in the step can be tested by name)."""

# What the test file's prelude does before the teacher's code (code_gate._prelude): python-script imports the joined
# project; files puts the project's folders on sys.path and star-imports this step's own quiet modules, binding
# step_modules, so the writer never has to guess a module the plan doesn't name (4 of the smoke's 13 files steps
# with unconfirmed tests failed on a guessed one).
TESTS_HOW = {
    "python-script": "- The project is one file, importable as project, with every step's names at its top level. Your "
                     "code comes after `import project` and `from project import *`, so call the names directly.",
    "files": "- The project's files are in the current folder at their paths, and the current folder and every folder "
             "holding a .py file are on sys.path. This step's modules that only define things are imported before "
             "your code and their public names are in scope; step_modules lists them. Import an earlier step's "
             "module only by the path the plan or its piece gives (src/store.py: from src.store import Store).",
}

TESTS_REWRITE = """They failed on every candidate that passed the other checks. What each failure was (the candidates' code isn't shown, and a candidate may be wrong):
{failures}

Read each failure against the step's instructions. Where your tests are at fault (a name or module the step doesn't give, data in a layout it doesn't give, an example read as exact text, a process started, an assert that can't hold after the lines before it), correct them; where the step really asks for what an assert checks, keep it. Don't fit the tests to a candidate. The rules above still hold. Reply with the whole corrected tests in the same JSON."""

# Why the tests writer's reply was refused (parse_tests_why), as its one retry is told after its own reply
# (tests_retry_messages): every why task.REFUSED counts, so a step's tests are "none:tests_refused" only after a retry
TESTS_REFUSED = {
    "subprocess": "These tests start another program (subprocess, os.system, python -m), which the sandbox refuses, "
                  "so they would fail on every piece. Call this step's functions in the tests' own process.",
    "name_guess": "These tests try possible names or modules, or search a namespace or the folder for one, instead "
                  "of using the names the plan and this step give, so they can't tell whether a piece does its step.",
    "tests_syntax": "These tests don't compile as Python, so they can't run on any piece.",
    "no_asserts": "These tests reach no assert when they run (one inside a function nothing calls never runs), so "
                  "every piece would pass them. Assert what this step's instructions ask, in code that runs."}
TESTS_REFUSED_TAIL = "Write them again by the rules above. Reply with the whole tests in the same JSON."


# ---------------------------------------------------------------- what every judge is shown

def _cut(s, n):
    s = s or ""
    return s if len(s) <= n else s[:n - 1] + "…"


def outline(plan, i):
    """The plan's steps, one line each, step i marked with → and given in full below by the caller."""
    lines = [f"Project: {plan.get('title') or ''}"]
    if plan.get("summary"):
        lines.append(plan["summary"])
    lines.append("")
    lines.append("The plan:")
    ids = {st.get("id"): f"s{k + 1}" for k, st in enumerate(plan.get("steps") or [])}
    for k, st in enumerate(plan.get("steps") or []):
        deps = [ids[d] for d in st.get("depends_on") or [] if d in ids]
        uses = f" (uses {', '.join(deps)})" if deps else ""
        mark, what = ("→", "the step under review") if k == i else (" ", _cut(st.get("instructions"), _STEP_CUT))
        lines.append(f"{mark} s{k + 1}. {st.get('title') or ''} [{st.get('kind') or ''}]{uses}: {what}")
    return "\n".join(lines)


def _step(plan, i):
    st = (plan.get("steps") or [])[i]
    return f"The step under review, s{i + 1}: {st.get('title') or ''}\n{st.get('instructions') or ''}"


def _deps_text(deps):
    """Dependencies' pieces ({sid: text} or [(sid, text)]), at most DEPS_BUDGET characters together: the shortest stay
    whole and the longest are cut to one length (contract.today.piece_cap, Chimera's pieceCap). A failed one (no
    text) takes no room."""
    items = sorted(deps.items()) if isinstance(deps, dict) else list(deps or [])
    if not items:
        return "Its dependencies: none."
    cap = piece_cap([len(text or "") for _, text in items], DEPS_BUDGET)
    return "\n\n".join(f"From {sid}:\n" + (_cut(text, cap) if text else "(that step failed: nothing)")
                       for sid, text in items)


def _handoff_text(handoff):
    if isinstance(handoff, str):
        return handoff.strip() or "none"
    h = handoff or {}
    return "\n".join(f"{k}: {h.get(k) or 'none'}" for k in ("provides", "uses", "assumed"))


def _goal(goal, head=GOAL_HEAD):
    return f"{head}\n{goal or ''}"


# ---------------------------------------------------------------- the scene judge

_FIRST = ("objects", "materials", "collections", "ctx_keys", "ctx_values")


def _listing(scene, cut=_SCENE_CUT):
    """The scene as the judge reads it: one line per key, objects, materials, collections, ctx keys and ctx values
    (_FIRST) first, then the rest by name, each value as JSON. Over cut characters, the longest list loses items from
    its end, with a note of how many aren't shown, until it fits, so a scattered scene's hundreds of objects can't
    push its ctx keys out of the listing; whatever is still over is cut. "nothing" for an empty scene."""
    scene = scene or {}
    keys = [k for k in _FIRST if k in scene] + sorted(k for k in scene if k not in _FIRST)
    shown, hidden = {k: scene[k] for k in keys}, dict.fromkeys(keys, 0)

    def line(k):
        more = f" (and {hidden[k]} more not shown)" if hidden[k] else ""
        return f"{k}: {json.dumps(shown[k], ensure_ascii=False)}{more}"

    lines = {k: line(k) for k in keys}
    while True:
        over = sum(len(s) + 1 for s in lines.values()) - 1 - cut
        lists = [k for k in keys if isinstance(shown[k], list) and shown[k]]
        if over <= 0 or not lists:
            break
        k = max(lists, key=lambda k: len(lines[k]))
        items, n, freed = shown[k], 0, 0
        while n < len(items) and freed < over:
            n += 1
            freed += len(json.dumps(items[-n], ensure_ascii=False)) + 2
        shown[k], hidden[k] = items[:-n], hidden[k] + n
        lines[k] = line(k)
    return _cut("\n".join(lines[k] for k in keys), cut) or "nothing"


def scene_messages(goal, plan, i, handoff, scene) -> list:
    """The scene judge's messages: did step i's Blender piece, run alone, build what its step asks and nothing a
    sibling owns? handoff: the piece's ({provides, uses, assumed}); scene: what the run measured (blender_gate's
    _scene: "objects", "materials", "collections", "ctx_keys", "ctx_values" when it has some, then whatever else it
    lists, factory names removed), shown by _listing.

    goal isn't shown (kept in the signature for the callers): its two questions are the request's, which carries the
    plan, never the goal, and what the goal adds is numbers and words the request doesn't carry. Of the 133 stored
    scene-judge verdicts of the four smoke runs, one gives a reason only the goal holds, and it turned a piece down
    falsely: smoke4's n-blender-0000-01 r1 s2, "length 2.0 m instead of required 2.2 m", where 2.2 m is the goal's
    and 2.0 the value its dependency's piece sets in the request; no verdict needed the goal."""
    user = "\n\n".join([outline(plan, i), _step(plan, i),
                        f"The piece's handoff:\n{_handoff_text(handoff)}",
                        "What the piece created when run alone:\n" + _listing(scene)])
    return [{"role": "system", "content": SCENE_SYSTEM}, {"role": "user", "content": user}]


def parse_scene(content):
    """{"ok": bool, "why": str} from the scene judge's reply, or None."""
    obj = first_json(content)
    if obj is None:
        return None
    ok = _truth(obj.get("ok", obj.get("pass", obj.get("passed"))))
    if ok is None:
        return None
    why = obj.get("why", obj.get("reason", ""))
    return {"ok": ok, "why": why.strip() if isinstance(why, str) else json.dumps(why, ensure_ascii=False)}


# ---------------------------------------------------------------- what a scene judge's rejection may not rest on
# SCENE_SYSTEM forbids judging sizes, positions and numbers, and the contract's shape replaces any output form a step
# names; the fourth smoke's 4 Blender rejections all rested on those. overruled() reads a rejection's "why" for them:
# what each of these matches is taken out, and a rejection is overruled only when something was taken out, nothing
# left says anything else (_OTHER, a number, or a "wrong" of some other thing), and each size or position claim rests
# on a reading (claims, readings: decided Nov 6).
_NUM_RE = r"\d+(?:\.\d+)?"
_UNIT_REQ = r"\s*(?:mm|cm|m|metres?|meters?)\b"
_UNIT_RE = r"(?:%s)?" % _UNIT_REQ
_SIZE_WORD = r"(?:sizes?|dimensions?|lengths?|widths?|heights?|depths?|thickness|radius|diameter)"
_FORM = (r"(?:the\s+|a\s+|an\s+|any\s+)?(?:required\s+|requested\s+|specified\s+|expected\s+|final\s+)?"
         r"(?:`?\w*script`?\s+(?:variable|string)(?:\s+output)?|string\s+variable(?:\s+`?\w+`?)?(?:\s+output)?|"
         r"(?:python\s+)?script\s+(?:export|text|file|output|string)|"
         r"(?:final|combined|complete|single|exported|full)\s+(?:python\s+|\.py\s+)?(?:script|file)(?:\s+text)?|"
         r"\.py\s+(?:file|text|script)|code\s+as\s+(?:a\s+)?(?:string|text|variable)|"
         r"export(?:ed)?\s+(?:of\s+)?(?:the\s+)?(?:final\s+)?script|(?:script\s+)?export)")
_FORM_FAULT = re.compile(r"\b(?:(?:is\s+|was\s+)?missing\s+|lacks?\s+|lacking\s+|no\s+|without\s+|"
                         r"did\s?n[o']?t\s+(?:produce|output|return|provide|give|create|define|export|write|include)"
                         r"\s+|not\s+(?:produced|output|returned|exported|written|provided|given)(?:\s+as)?\s+)"
                         + _FORM + r"|\b" + _FORM + r"\s+(?:is\s+|was\s+)?(?:missing|absent|not\s+(?:produced|"
                         r"returned|exported|given))", re.I)
# a size word, or a number with its unit, before "instead of" another: never a bare count ("4 instead of 2 stools")
_SIZE_FAULT = re.compile(
    r"\b(?:" + _SIZE_WORD + r"|scale)\s+(?:is|are|was|were)\s+(?:wrong|incorrect|off|different|too\s+\w+)|"
    r"\b(?:wrong|incorrect)\s+(?:default\s+)?(?:" + _SIZE_WORD + r"|scale)|"
    r"(?:\b" + _SIZE_WORD + r"\s+(?:of\s+)?" + _NUM_RE + _UNIT_RE + r"|\b" + _NUM_RE + _UNIT_REQ + r")"
    r"\s+(?:instead\s+of|rather\s+than|not)\s+(?:the\s+)?(?:required\s+|specified\s+|requested\s+|expected\s+|"
    r"given\s+)?" + _NUM_RE + _UNIT_RE + r"|"
    r"\btoo\s+(?:big|small|large|tall|short|long|wide|narrow|thin|thick)\b", re.I)
_PLACES_WORD = r"(?:positions?|coordinates?|locations?|places?|points?|placement)"
_POSITION_FAULT = re.compile(
    r"\b(?:(?:all|they|it|each|every\s+\w+)\s+)?(?:(?:are|is|were|was)\s+(?:all\s+)?)?(?:placed|positioned|located|"
    r"put|sit(?:s|ting)?|lie|lies|are|is|were|was)\s+(?:all\s+)?(?:at|on)\s+(?:the\s+)?(?:world\s+)?origin"
    r"(?:\s*\(\s*0\s*,\s*0\s*,\s*0\s*\))?|"
    r"\b(?:all\s+)?locations?\s+(?:are|is|were|was)\s+(?:all\s+)?(?:at\s+)?\(\s*0\s*,\s*0\s*,\s*0\s*\)|"
    r"\binstead\s+of\s+(?:at\s+)?(?:the|their|its)\s+(?:required\s+|specified\s+|given\s+|requested\s+|correct\s+|"
    r"stated\s+|expected\s+)?" + _PLACES_WORD + r"|"
    r"\b(?:wrong|incorrect)(?:ly)?\s+(?:placed|positioned|located|" + _PLACES_WORD + r")|"
    r"\b" + _PLACES_WORD + r"\s+(?:is|are|were|was)\s+(?:wrong|incorrect|off)|"
    r"\bnot\s+(?:placed|positioned|located|cent(?:er|re)d)\s+(?:at|on)\s+(?:the\s+)?(?:required\s+|specified\s+|"
    r"given\s+)?(?:" + _PLACES_WORD + r"|\([^()]{0,40}\)|origin)", re.I)
# Saying what the piece did make, or that what it made are stand-ins: no fault of their own
_NEUTRAL = re.compile(r"\b(?:(?:all|the)\s+)?objects?\s+(?:were\s+|are\s+|was\s+|is\s+)?(?:created|built|made)\b|"
                      r"\b(?:it\s+)?(?:only\s+)?(?:created|made|built)\s+(?:only\s+)?(?:\w+\s+)?(?:placeholder|"
                      r"stand.?in)s?(?:\s+objects?)?\b|\b(?:placeholder|stand.?in)s?(?:\s+objects?)?\b", re.I)
# Anything else a rejection may rest on, which the judge is for (a thing missing or extra, made nothing) or which no
# check here measures (materials, settings, animation, modifiers, lights' and cameras' properties, ctx keys). After the
# independent checks (Nov 6) also: a contraction's n't (\b before it never matched inside "doesn't"), what was never
# made, omitted, forgotten, skipped or left out, a count in words, a turn, a facing, an overlap, floating, a place
# relative to another thing, and a shape: none of them is measured (asked_sizes reads only a size's three sides and
# asked_places a point).
_OTHER = re.compile(r"\b(?:missing|miss(?:es)?|lacks?|lacking|absent|no|none|not|without|nothing|empty|zero|only|"
                    r"extra|unexpected|unrequested|another|other|belongs?|beyond|outside|also|changed|changes|"
                    r"switch\w*|sets?|added|adds|instead|wrong|incorrect|invalid|fail\w*|error\w*|materials?|"
                    r"textures?|colou?rs?|engine|eevee|cycles|world|render\w*|settings?|samples?|resolution|"
                    r"keyframes?|keys?|animat\w*|frames?|fps|modifiers?|lens|focal|power|energy|watts?|shadows?|"
                    r"assign\w*|ctx|values?|variables?|handoff|provides?|camera|lights?|lamps?|snippet|verification|"
                    r"print\w*|counts?|never|omit\w*|forg[eo]t\w*|skip\w*|left\s+out|leaves?\s+out|ignor\w*|"
                    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|single|pairs?|both|several|"
                    r"rotat\w*|turn(?:s|ed|ing)?|upside|sideways|tilt\w*|fac(?:e|es|ed|ing)|orient\w*|overlap\w*|"
                    r"intersect\w*|penetrat\w*|clip(?:s|ped|ping)?|float\w*|hover\w*|inside|under(?:neath)?|"
                    r"beneath|beside|behind|above|below|between|against|top|next\s+to|apart|touch\w*|reach\w*|"
                    r"gone|pok\w*|through|across|scatter\w*|spread\w*|stack\w*|rows?|arrang\w*|gaps?|"
                    r"shapes?|shaped|cylind\w*|spher\w*|cubes?|box\w*|cones?|torus|prism\w*|pyramid\w*|"
                    r"round\w*|flat\w*|curv\w*|primitive\w*)\b|\w*n['\u2019]t\b|\d", re.I)
_STEP_FORM = re.compile(r"\bstring\s+variable|\bas\s+(?:a\s+)?(?:single\s+)?string\b|\b(?:return|output|print|give|"
                        r"provide|export|write|produce)\w*\s+(?:the\s+|a\s+|this\s+|your\s+|all\s+)?"
                        r"(?:complete\s+|final\s+|whole\s+|full\s+|combined\s+|single\s+)?(?:\.py\s+|python\s+)?"
                        r"(?:code|snippet|script|\.py)\b|\.py\b|\bplain\s+text\b|\bconcatenat\w*|\bcombine\w*\s+"
                        r"(?:all\s+)?(?:the\s+)?(?:\w+\s+)?(?:scripts|snippets|strings|sections)\b|"
                        r"\bexport\s+the\s+(?:final\s+)?script\b", re.I)
OVERRULED = ("size", "position", "output_form")  # overruled()'s kinds, as a judge record's "overruled" lists them


def names_output_form(step):
    """The words by which a plan step names an output form for its code (a string variable, the code or script
    returned, printed, exported or written as a .py, the steps' scripts combined), or None: the forms the contract's
    shape replaces (SCENE_SYSTEM), so a rejection for not giving one is overruled only on a step that names one."""
    m = _STEP_FORM.search(f"{(step or {}).get('title') or ''}\n{(step or {}).get('instructions') or ''}")
    return m.group(0) if m else None


# An overrule rests on a measurement (decided Nov 6): a size or position claim is overruled only when the gate's own
# readers read a value for the thing it names, a size with every side given (blender_gate.asked_sizes; a side named
# only by a variable, "sofa_dim (length)", is measured by nothing) or a point (geometry.asked_places), since
# size_mismatch and place_mismatch measured those before the judge was asked. A claim's thing is what is left of its
# clause (_CLAIM_CLAUSE) once the claims and the neutral words are taken out, cut into things at _THING_CUT, each
# the telling words of its part (blender_gate._words, less _CLAIM_FILLER); it is matched to a reading when its words
# are all among the reader's own name for its thing, and the listing shows no other thing they may name (_read_for:
# the second checks, Nov 6; one shared word had overruled a claim on a side table by the coffee table's size).
_CLAIM_CLAUSE = re.compile(r";|\.(?=\s|$)|\bbut\b|\bwhile\b|\bwhereas\b|,\s*and\b", re.I)
_THING_CUT = re.compile(r"[,()\[\]/&:]|\band\b|\bor\b|\bwith\b", re.I)
_CLAIM_FILLER = frozenset(
    "are were was been being has have had its their they them this that these those all every which whose but while "
    "whereas than rather required specified requested expected given stated correct actual current final piece step "
    "scene listing listed run measured shows shown should must would will can could seems appears created made placed "
    "positioned located put sits sit sitting lie lies lying origin world coordinates coordinate positions position "
    "locations location places place points point placement sizes dimensions lengths widths heights depths thickness "
    "radius diameter scale big small large tall short long wide narrow thin thick metres meters metre meter".split())


def claims(why, step):
    """[(kind, things)] for each size or position claim in a scene judge's reason, clause by clause (_CLAIM_CLAUSE):
    things is a list of word sets, one per thing its clause names once every claim (an output form's too, on a step
    that names one) and the neutral words are taken out (_THING_CUT, _CLAIM_FILLER); [] when it names none ("all
    placed at the origin instead of the specified coordinates")."""
    from datagen import blender_gate as bg
    out = []
    for clause in _CLAIM_CLAUSE.split(" ".join(str(why or "").split())):
        rest, found = " " + clause + " ", []
        for kind, pattern in (("output_form", _FORM_FAULT), ("size", _SIZE_FAULT), ("position", _POSITION_FAULT)):
            if kind == "output_form" and not names_output_form(step):
                continue
            rest, n = pattern.subn(" ", rest)
            if n and kind != "output_form":
                found.append(kind)
        rest = _NEUTRAL.sub(" ", rest)
        things = [w for w in (bg._words(part) - _CLAIM_FILLER for part in _THING_CUT.split(rest)) if w]
        out += [(kind, things) for kind in found]
    return out


def readings(plan, i):
    """{"size": [word set], "position": [(words, quoted)]}: the things step i's sizes and points are read for, as
    the gate's readers read them (blender_gate.asked_sizes with every side given, its thing's words as size_states
    takes them; geometry.asked_places with a point, an "origin" one included, the words place_states matches by)."""
    from datagen import blender_gate as bg, geometry
    return {"size": [bg._words(a.get("thing") or "") or set(a.get("words") or ())
                     for a in bg.asked_sizes(plan, i) if a.get("sides") and None not in a["sides"]],
            "position": [(list(a.get("words") or []), bool(a.get("quoted")))
                         for a in geometry.asked_places(plan, i) if a.get("point") is not None]}


def _place_words(words, quoted):
    """The words a place reading names its thing by: its words, and a quoted name's own words."""
    from datagen import blender_gate as bg
    return {w.lower() for w in words} | ({x for w in words for x in bg._name_words(w)} if quoted else set())


def _read_for(kind, things, got, scene):
    """Whether claim (kind, things) rests on a reading of got (readings()): each thing's words are all among one
    reading's (the second checks, Nov 6: one shared word overruled "the side table is too big" on the coffee table's
    size, and "the sofa cushions" on the sofa's), and every object of the judge's listing (scene["objects"]) those
    words may name is a thing read for, or a part named after one ("the table" stands beside a side table no reader
    read); for a claim that names no thing, every object of the listing is one a reading is for (its name's words all
    among the reading's), and there is at least one."""
    from datagen import blender_gate as bg
    if not got[kind]:
        return False
    names = got[kind] if kind == "size" else [_place_words(w, q) for w, q in got[kind]]
    objs = [o if isinstance(o, str) else o[0] if isinstance(o, (list, tuple)) and o else
            o.get("name") if isinstance(o, dict) else None for o in (scene or {}).get("objects") or []]
    objs = [bg._words(n) for n in objs if isinstance(n, str) and n]
    if things:
        for t in things:
            read = [n for n in names if t <= n]
            if not read or any(t <= o and not any(o <= n or n <= o for n in read) for o in objs):
                return False
        return True
    return bool(objs) and all(o and any(o <= n for n in names) for o in objs)


def overruled(verdict, plan, i, scene=None):
    """The kinds (OVERRULED's, in its order) a scene judge's rejection of step i's piece rests on when those are all it
    rests on and each size or position claim rests on a measurement: a size ("the fridge is too big"), a position
    ("the stove is placed at the origin instead of the specified coordinates") or, on a step that names one
    (names_output_form), an output form the contract replaces ("missing blender_script variable output", "did not
    produce the required script export"); [] for an acceptance, an unreadable verdict, or a rejection with anything
    else in its reason: something missing, extra or another step's, settings, materials, animation, any number left
    over (a count of things is the judge's to judge), something never made, omitted or left out, a count in words, a
    turn, an overlap, floating, a place beside or on another thing, a shape (_OTHER, widened after the independent
    checks of Nov 6), an output form on a step that names none.

    What a size or position claim rests on (decided Nov 6): the gate measured the step's sizes and places before the
    judge was asked (a try reaches it only after the gate), but only those its readers read: three given sides of a
    thing (blender_gate.asked_sizes: not "3 m tall", "a radius of 0.3 m" or a side named by a variable) and a point
    (geometry.asked_places: not "0.4 m to the right of the sofa", a "±" point or "above the floor"). So a claim is
    overruled only when each thing it names (claims()) has all its words among those of a thing the readers read a
    value for (readings()), and no other object of the judge's listing (scene, the gate's "scene") goes by those
    words (_read_for: "the side table", "the sofa cushions" or "the table" beside a side table stand on the coffee
    table's or the sofa's reading), and one that names no thing ("all placed at the origin") only when every object
    the listing shows is one they read a value for, its name's words all among the reading's; a claim whose thing no
    reading names, or a step whose readers read nothing for it, stands, and so does a no-thing claim with no listing.
    An output form claim needs no measurement: the contract's shape replaces any form a step names.

    On the 130 distinct stored scene-judge verdicts of the four smoke runs (48 rejections) it overrules 3, all output
    forms, on 2 distinct steps (n-blender-0000-00 r1 s1 in the first smoke and in smoke4, and smoke4's
    n-blender-0000-01 r1 s4 c5). Before Nov 6 the overrule rested on the rubric and took 7: the 3 position claims of
    n-blender-0000-00 r1 s2 (smoke2, smoke3, smoke4) stand now, as they name no thing and its stools'
    "(±0.6, ±0.3, 0.5)" is read by no reader (smoke4's c0 has them 0.28 m into the floor), and so does smoke4's
    n-blender-0000-01 r1 s2 c0 "sofa size is wrong (length 2.0 m instead of required 2.2 m)", whose length is
    sofa_dim, a variable. The other 41 rest on settings, a missing or extra thing or a material assignment, and stand
    either way."""
    if not verdict or verdict.get("ok") is not False:
        return []
    step = plan["steps"][i]
    why = " " + " ".join(str(verdict.get("why") or "").split()) + " "
    kinds = set()
    for kind, pattern in (("output_form", _FORM_FAULT), ("size", _SIZE_FAULT), ("position", _POSITION_FAULT)):
        if kind == "output_form" and not names_output_form(step):
            continue
        why, n = pattern.subn(" ", why)
        if n:
            kinds.add(kind)
    why = _NEUTRAL.sub(" ", why)
    if not kinds or _OTHER.search(why):
        return []
    got = None
    for kind, things in claims(verdict.get("why"), step):
        got = got or readings(plan, i)
        if not _read_for(kind, things, got, scene):
            return []
    return [k for k in OVERRULED if k in kinds]


# ---------------------------------------------------------------- the prose judge

HANDOFF_HEAD = ("Its handoff, the note to later steps that its format requires after the section (not part of the "
                "section, so don't grade it as text; \"assumed\" lists what the writer had to assume):")
HEADING_LINE = ("Its format requires the section to start with a ## heading line, also above JSON, a table or a "
                "list; that line is not extra text.")


def prose_messages(goal, plan, i, section, deps) -> list:
    """The prose judge's messages for step i's section (the candidate's text), with its dependencies' pieces (deps:
    {sid: text}). The handoff block the contract asks for after a section is shown on its own, as such: in the
    first smoke seed (Nov 3) the judge, given the whole piece, marked every section down for "an extra handoff code
    block". It is told the ## heading line is required too (HEADING_LINE): it called one above a CSV "extra
    introductory text", and the next try's notes would then have said both to keep it and to drop it."""
    blocks, _ = cv.handoff_blocks(section or "")
    body = cv.strip_handoff(section or "", blocks) if blocks else (section or "")
    handoff = (blocks[-1].body.strip() if blocks else "") or "none"
    user = "\n\n".join([_goal(goal), outline(plan, i), _step(plan, i),
                        "Its dependencies' pieces:\n" + _deps_text(deps), HANDOFF_HEAD + "\n" + handoff,
                        HEADING_LINE, "The section to grade:\n" + body.strip()])
    return [{"role": "system", "content": PROSE_SYSTEM}, {"role": "user", "content": user}]


def parse_prose(content):
    """{"score": 1-5, "problems": [str]} from the prose judge's reply, or None (no object, or no score from 1 to
    5). A whole-number score comes back as an int."""
    obj = first_json(content)
    if obj is None:
        return None
    score = _number(obj.get("score", obj.get("rating")))
    if score is None or not 1 <= score <= 5:
        return None
    problems = obj.get("problems", obj.get("issues", []))
    if isinstance(problems, str):
        problems = [problems] if problems.strip() else []
    elif not isinstance(problems, list):
        problems = []
    problems = [p.strip() if isinstance(p, str) else json.dumps(p, ensure_ascii=False) for p in problems
                if p not in (None, "")]
    return {"score": int(score) if score == int(score) else score, "problems": [p for p in problems if p]}


def prose_kept(parsed, strict=False) -> bool:
    """The prose judge keeps a section at PROSE_KEEP or more; strict, only at PROSE_STRICT. In the smoke, kept
    sections at 4 named only their length as a problem while claiming tests that were never run and prices "taken
    from" websites. task.py once let a 5 keep a section written with a dependency missing; since Nov 4 such a
    section needs qwen3.8's keep whatever the score, since of those gpt-oss gave 5 some invented the missing step's
    facts, so nothing asks for strict now."""
    return bool(parsed) and parsed["score"] >= (PROSE_STRICT if strict else PROSE_KEEP)


# ---------------------------------------------------------------- the tests writer

def _tests_user(goal, plan, i, deps):
    return "\n\n".join([_goal(goal, TESTS_GOAL_HEAD), outline(plan, i), _step(plan, i),
                        "Its dependencies' pieces (already in the project):\n" + _deps_text(deps)])


def _tests_system(mode):
    if mode not in TESTS_HOW:
        raise ValueError(f"no tests for mode {mode!r}")
    return TESTS_SYSTEM.format(how=TESTS_HOW[mode])


def tests_messages(goal, plan, i, mode, deps) -> list:
    """The tests writer's messages for code step i in mode python-script or files, with its dependencies' pieces
    (deps: {sid: text}), written before any candidate exists."""
    return [{"role": "system", "content": _tests_system(mode)},
            {"role": "user", "content": _tests_user(goal, plan, i, deps)}]


def tests_retry_messages(messages, reply, why) -> list:
    """The tests writer asked once more after parse_tests refused its reply for a rule it breaks (why: a key of
    TESTS_REFUSED): the same conversation (messages, tests_messages'), its own reply, then why it was refused. Not
    tests_rewrite_messages, whose text says the tests failed on every candidate: refused tests never ran."""
    return list(messages) + [{"role": "assistant", "content": reply or ""},
                             {"role": "user", "content": TESTS_REFUSED[why] + " " + TESTS_REFUSED_TAIL}]


def _fenced(code):
    """code in a python fence longer than any run of backticks in it."""
    run = max((len(m) for m in re.findall(r"`+", code)), default=0)
    fence = "`" * max(3, run + 1)
    return f"{fence}python\n{code.rstrip()}\n{fence}"


def _one_line(v, n=_FAILURE_CUT):
    if isinstance(v, (list, tuple)):
        v = ", ".join(str(x) for x in v if x not in (None, ""))
    return _cut(" ".join(str(v or "").split()), n)


def _failure_lines(failures):
    """One line per distinct failure, the candidates that had it numbered in the caller's order."""
    who = {}  # (assert, error, provides) -> candidate numbers, in first-seen order
    for k, f in enumerate(failures or []):
        f = f or {}
        who.setdefault(tuple(_one_line(f.get(x)) for x in ("assert", "error", "provides")), []).append(k + 1)
    lines = []
    for (line, error, provides), ks in who.items():
        name = f"candidate {ks[0]}" if len(ks) == 1 else \
            "candidates " + ", ".join(map(str, ks[:-1])) + f" and {ks[-1]}"
        it, its = ("it", "its") if len(ks) == 1 else ("they", "their")
        at = f"the failing assert: {line}; " if line else ""  # none known: an error outside an assert, say
        lines.append(f"- {name}: {at}the error: {error or 'none given'}; {its} handoff provides: "
                     f"{provides or 'none'}")
    return "\n".join(lines) or "- (no failure was recorded)"


def tests_rewrite_messages(goal, plan, i, mode, deps, old_tests, failures) -> list:
    """The tests writer asked once more, for tests that failed every candidate that passed everything else: the
    same system prompt and step as tests_messages, then the earlier tests and, per failing candidate, only what the
    caller gives as failures: [{"assert": the failing assert line or "" (not known: the error says what failed),
    "error": the error's last line,
    "provides": its handoff's provides names (a string or a list)}], never a candidate's code, so the new tests are
    still written to the step and must again fail on the stub and pass a candidate (code_gate.tests_check).
    Candidates with the same failure share a line. In the smoke, 13 of the 17 steps whose tests no candidate passed
    had tests at fault, and in 8 of those the only fault was the one their first failure shows."""
    user = "\n\n".join([_tests_user(goal, plan, i, deps),
                        "Your earlier tests for this step:\n" + _fenced(_cut(old_tests or "", _TESTS_CUT)),
                        TESTS_REWRITE.format(failures=_failure_lines(failures))])
    return [{"role": "system", "content": _tests_system(mode)}, {"role": "user", "content": user}]


def parse_tests(content):
    """The tests' Python code from the writer's reply, or None (parse_tests_why says why): from the JSON's "tests"
    (or "code"), else the first python block, else the reply itself. It must compile, start no process, guess no
    names (_guesses) and hold at least one assert that running it reaches (reached_asserts: not one only inside a
    test function nobody calls); print("tests ok") is added at the end when it is missing, since code_gate needs that
    line to know the tests ran to the end (a stub that passes them all the same makes them invalid there)."""
    return _read_tests(content)[0]


def parse_tests_why(content):
    """Why parse_tests refuses a reply, or None when it reads: "no_tests" (no code: an empty "tests", a JSON object
    without one, or a bare reply that isn't Python), "tests_syntax" (code that doesn't compile), "subprocess" (it
    starts a process, which the sandbox refuses: the smoke's subprocess test failed the same way on every candidate),
    "name_guess" (it tries possible names or modules, or searches a namespace or the folder for one), "no_asserts"
    (no assert that running it reaches)."""
    return _read_tests(content)[1]


def _read_tests(content):
    """(code, None) or (None, why) for parse_tests and parse_tests_why."""
    code, bare = None, False
    obj = first_json(content)
    for k in ("tests", "code", "python", "test"):
        if obj is not None and isinstance(obj.get(k), str):
            code = obj[k]
            break
    if code is None:
        if _whole_object(content):  # JSON with no code in it (a note, say): nothing to run
            return None, "no_tests"
        code, bare = content or "", True  # no JSON, or an object that is only a dict in the code
    blocks = [b for b in code_blocks(code) if b.closed and (python_lang(b.lang) or b.lang == "")]
    if blocks:
        code, bare = blocks[0].body, False
    code = code.strip("\n")
    if not code.strip():
        return None, "no_tests"
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None, "no_tests" if bare else "tests_syntax"
    if _starts_process(tree):
        return None, "subprocess"
    if _guesses(tree):
        return None, "name_guess"
    if not reached_asserts(tree):
        return None, "no_asserts"
    if TESTS_OK not in code:
        code += '\nprint("tests ok")'
    return code + "\n", None


def _whole_object(content):
    try:
        return isinstance(json.loads((content or "").strip()), dict)
    except ValueError:
        return False


# ---------------------------------------------------------------- tests that can't count

_PROCESS_MODULES = frozenset(["subprocess", "multiprocessing"])
_PROCESS_NAMES = frozenset(["Popen", "ProcessPoolExecutor", "create_subprocess_exec", "create_subprocess_shell"])
_OS_PROCESS = re.compile(r"(system|popen|fork|forkpty|exec\w*|spawn\w*|posix_spawnp?|startfile)$")
_IMPORTERS = frozenset(["import_module", "__import__"])


def _process_module(name):
    return (name or "").split(".")[0] in _PROCESS_MODULES


def _importer(call):
    """importlib.import_module(...) or __import__(...)."""
    if not isinstance(call, ast.Call):
        return False
    f = call.func
    return (isinstance(f, ast.Name) and f.id in _IMPORTERS) or (isinstance(f, ast.Attribute) and f.attr in _IMPORTERS)


def _const(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _starts_process(tree) -> bool:
    """Does the code import subprocess or multiprocessing (or name it to an importer), or touch os.system, os.popen,
    os.fork, os.exec*, os.spawn*, Popen, a process pool or asyncio's subprocesses? The sandbox refuses every one."""
    for n in ast.walk(tree):
        if isinstance(n, ast.Import) and any(_process_module(a.name) for a in n.names):
            return True
        if isinstance(n, ast.ImportFrom):
            names = [a.name for a in n.names]
            if _process_module(n.module) or any(x in _PROCESS_NAMES for x in names) or \
                    (n.module == "os" and any(_OS_PROCESS.match(x) for x in names)):
                return True
        if isinstance(n, ast.Attribute) and (n.attr in _PROCESS_NAMES or (
                isinstance(n.value, ast.Name) and n.value.id == "os" and _OS_PROCESS.match(n.attr))):
            return True
        if isinstance(n, ast.Name) and n.id in _PROCESS_NAMES:
            return True
        if isinstance(n, ast.Call) and _importer(n) and n.args and _process_module(_const(n.args[0])):
            return True
    return False


_NAMESPACE_CALLS = frozenset(["globals", "locals", "vars", "dir"])
_WRAPPERS = frozenset(["list", "sorted", "tuple", "set", "iter", "reversed", "enumerate"])
_LISTINGS = frozenset(["listdir", "scandir", "walk", "glob", "iglob", "rglob", "iterdir"])
_LOOPS = (ast.For, ast.AsyncFor, ast.While)
_COMPS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _unwrap(node):
    """node without list(), sorted() and the like around it, nor .items(), .keys() or .values() after it."""
    while isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name) and f.id in _WRAPPERS and node.args:
            node = node.args[0]
        elif isinstance(f, ast.Attribute) and f.attr in ("items", "keys", "values", "copy") and not node.args:
            node = f.value
        else:
            break
    return node


def _namespace(node) -> bool:
    """globals(), locals(), vars(x), dir(x), inspect.getmembers(x), x.__dict__ or sys.modules, unwrapped."""
    node = _unwrap(node)
    if isinstance(node, ast.Call):
        f = node.func
        return (isinstance(f, ast.Name) and f.id in _NAMESPACE_CALLS) or \
            (isinstance(f, ast.Attribute) and f.attr == "getmembers")
    if isinstance(node, ast.Attribute):
        return node.attr == "__dict__" or (node.attr == "modules" and isinstance(node.value, ast.Name) and
                                           node.value.id == "sys")
    return False


def _listing_call(node) -> bool:
    """os.listdir(...), os.scandir, os.walk, glob.glob, Path.glob, rglob, iterdir: the folder's files."""
    node = _unwrap(node)
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (isinstance(f, ast.Attribute) and f.attr in _LISTINGS) or (isinstance(f, ast.Name) and f.id in _LISTINGS)


def _names_in(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _targets(target):
    return {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}


def _looks_up(nodes, var) -> bool:
    """Does anything in nodes look a name up by var (or a string built from it): getattr or hasattr with it,
    importlib.import_module or __import__ of it, a namespace subscripted, .get() or tested with `in` by it?"""
    for top in nodes:
        for n in ast.walk(top):
            if isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Name) and f.id in ("getattr", "hasattr") and len(n.args) >= 2 and \
                        var & _names_in(n.args[1]):
                    return True
                if _importer(n) and n.args and var & _names_in(n.args[0]):
                    return True
                if isinstance(f, ast.Attribute) and f.attr == "get" and _namespace(f.value) and n.args and \
                        var & _names_in(n.args[0]):
                    return True
            elif isinstance(n, ast.Subscript) and _namespace(n.value) and var & _names_in(n.slice):
                return True
            elif isinstance(n, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in n.ops) and \
                    any(_namespace(c) for c in n.comparators) and var & _names_in(n.left):
                return True
    return False


def _walk_here(stmts):
    """The nodes of stmts that belong to this loop: not in a nested def, class, lambda or loop."""
    todo = [s for s in stmts if not isinstance(s, _SCOPES + _LOOPS)]
    while todo:
        n = todo.pop()
        yield n
        todo += [c for c in ast.iter_child_nodes(n) if not isinstance(c, _SCOPES + _LOOPS)]


def _candidate_lists(tree):
    """The names bound to a literal list, tuple or set of two or more strings (a list of possible names, perhaps)."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and _string_list(n.value):
            out |= {t.id for t in n.targets if isinstance(t, ast.Name)}
    return out


def _string_list(node):
    return isinstance(node, (ast.List, ast.Tuple, ast.Set)) and len(node.elts) >= 2 and \
        all(_const(e) is not None for e in node.elts)


def _guesses(tree) -> bool:
    """Does the code guess a name or a module, which the tests writer is told never to do? The forms the smoke's
    tests had, and their near kin: a loop over a list of possible names that stops at the first one found (break,
    return, or an assignment under a test that looks it up), or a comprehension that keeps the ones found; a loop or
    comprehension over globals(), dir(), vars() or the like that picks by name; a loop over the folder's files that
    imports what it finds; an if/elif (or `or`) chain trying two names on the same object; and a try that imports a
    name from one module and, on ImportError, the same name from a differently named one. A loop that asserts every
    name of a list exists only checks them, and isn't a guess. On the smoke's 35 stored tests this refuses 9: 7 of
    the 17 that were never confirmed, and 2 valid ones that found their name by trying several."""
    lists = _candidate_lists(tree)

    def possible(it):
        return _string_list(it) or (isinstance(it, ast.Name) and it.id in lists)

    for n in ast.walk(tree):
        if isinstance(n, (ast.For, ast.AsyncFor)):
            var, here = _targets(n.target), list(_walk_here(n.body))
            if possible(n.iter) and _looks_up(n.body, var) and (
                    any(isinstance(x, (ast.Break, ast.Return)) for x in here) or
                    any(isinstance(x, ast.If) and _looks_up([x.test], var) and _assigns(x.body) for x in here)):
                return True
            if _namespace(n.iter) and any(isinstance(x, ast.If) and var & _names_in(x.test) for x in here):
                return True
            if _listing_call(n.iter) and any(_importer(x) and x.args and _const(x.args[0]) is None for x in here):
                return True
        elif isinstance(n, _COMPS):
            for g in n.generators:
                var = _targets(g.target)
                if (possible(g.iter) and _looks_up(g.ifs, var)) or \
                        (_namespace(g.iter) and any(var & _names_in(c) for c in g.ifs)):
                    return True
        elif isinstance(n, ast.If) and _tries_two(_chain(n)):
            return True
        elif isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or) and _tries_two(n.values):
            return True
        elif isinstance(n, ast.Try) and _imports_elsewhere(n):
            return True
    return False


def _assigns(stmts):
    """Does stmts keep something (an assignment, or an append or add to a list of finds)?"""
    return any(isinstance(x, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.NamedExpr)) or
               (isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr in ("append", "add"))
               for x in _walk_here(stmts))


def _chain(node):
    """The tests of an if/elif chain."""
    tests = []
    while isinstance(node, ast.If):
        tests.append(node.test)
        node = node.orelse[0] if len(node.orelse) == 1 else None
    return tests


def _tried(node):
    """(object, name) for each hasattr(x, "name"), getattr(x, "name", ...) and "name" in globals() / dir(x) in node."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("hasattr", "getattr") and \
                len(n.args) >= 2 and _const(n.args[1]) is not None:
            out.add((ast.dump(n.args[0]), _const(n.args[1])))
        elif isinstance(n, ast.Compare) and len(n.ops) == 1 and isinstance(n.ops[0], ast.In) and \
                _const(n.left) is not None and _namespace(n.comparators[0]):
            out.add((ast.dump(_unwrap(n.comparators[0])), _const(n.left)))
    return out


def _tries_two(parts):
    """Do two of parts (an if/elif chain's tests, an `or`'s values) each try a different name on the same object?"""
    tried = [_tried(p) for p in parts]
    for a in range(len(tried)):
        for b in range(a + 1, len(tried)):
            if any(oa == ob and na != nb for oa, na in tried[a] for ob, nb in tried[b]):
                return True
    return False


def _imported(stmts):
    """{bound name: the module's last part} for the imports of stmts (nested tries included, not defs or loops)."""
    out = {}
    for n in _walk_here(stmts):
        if isinstance(n, ast.ImportFrom) and n.module:
            for a in n.names:
                out[a.asname or a.name] = n.module.split(".")[-1]
        elif isinstance(n, ast.Import):
            for a in n.names:
                out[a.asname or a.name.split(".")[0]] = a.name.split(".")[-1]
    return out


def _imports_elsewhere(node):
    """A try whose body imports a name and whose ImportError handler imports the same name from a module with
    another name (export.cmd_export, else cmd_export.cmd_export); src.store, else store, is the same module."""
    first = _imported(node.body)
    for h in node.handlers:
        caught = _names_in(h.type) if h.type is not None else {"ImportError"}
        if not caught & {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}:
            continue
        for name, mod in _imported(h.body).items():
            if name in first and first[name] != mod:
                return True
    return False


_BLOCKS = (ast.If, ast.For, ast.While, ast.With, ast.Try) + ((ast.TryStar,) if hasattr(ast, "TryStar") else ())
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _runs(stmts):
    """The statements of a block that run when it runs: these and those inside its if, for, while, with and try
    blocks, never a def's or class's body."""
    for s in stmts:
        yield s
        if isinstance(s, _BLOCKS):
            for field in ("body", "orelse", "finalbody"):
                yield from _runs(getattr(s, field, None) or [])
            for h in getattr(s, "handlers", None) or []:
                yield from _runs(h.body)


def _called(stmts):
    """The plain names called (f(...)) in stmts, the bodies of defs and classes left out."""
    out, todo = set(), [s for s in stmts if not isinstance(s, _DEFS)]
    while todo:
        n = todo.pop()
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            out.add(n.func.id)
        todo += [c for c in ast.iter_child_nodes(n) if not isinstance(c, _DEFS)]
    return out


def reached_asserts(tree) -> int:
    """How many assert statements running the module reaches: those in its body (inside top-level if, for, while,
    with and try blocks too) and those in a function the module calls by name, or one such a function calls."""
    top = list(_runs(tree.body))
    defs = {s.name: s for s in top if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))}
    n = sum(isinstance(s, ast.Assert) for s in top)
    todo, seen = sorted(_called(tree.body)), set()
    while todo:
        name = todo.pop()
        if name in seen or name not in defs:
            continue
        seen.add(name)
        n += sum(isinstance(s, ast.Assert) for s in _runs(defs[name].body))
        todo += sorted(_called(defs[name].body) - seen)
    return n


# ---------------------------------------------------------------- reading replies

def first_json(content):
    """The first JSON object in a reply: the whole reply, else the first "{" from which an object decodes. None if
    there is none."""
    s = (content or "").strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except ValueError:
        pass
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", s):
        try:
            obj, _ = dec.raw_decode(s, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _truth(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    if isinstance(v, str):
        t = v.strip().lower()
        if t in ("true", "yes", "pass", "passed", "ok"):
            return True
        if t in ("false", "no", "fail", "failed"):
            return False
    return None


def _number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v else None  # NaN is no score
    if isinstance(v, str):
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:/\s*5)?\s*", v)
        return float(m.group(1)) if m else None
    return None
