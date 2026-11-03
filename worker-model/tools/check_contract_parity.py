#!/usr/bin/env python3
"""Check the sub-agent contract in Go against the Python prototype it was ported from.

    CHIMERA_BIN=path python3 tools/check_contract_parity.py     # exit 1 on any difference, 2 if it couldn't run
    python3 tools/check_contract_parity.py --chimera PATH --out results.txt
    python3 tools/check_contract_parity.py --texts-only         # just the frozen texts, no binary needed

Go (app/hydra_contract.go) is the source of truth for what a worker is sent, and training data is built with
`chimera --hydra-worker-request`, so the model learns exactly those bytes. The eval, the measured results and the
contract's tests all stand on contract/prompt.py, so the two must not differ. This script checks:

- the frozen texts: every text and word list in Go, read from the source, against contract/texts.py and planinfo.py
  (and namesBlock's words in app/blender_names.go);
- whole requests, every key: each step of each frozen plan, every W1-W4 eval case, lone steps, failed dependencies,
  each form a dependency's output can take, round 2 (joined results, moved steps, settings at the top, results it
  can't match), repairs, near-miss handoffs, refs, the names sheet, plans cleanPlan has to fix, and seeded random
  text for the patterns, whose Python and RE2 forms differ most;
- that every frozen text really appeared in a request Go built, so nothing above passed by not being used.

Three places Go and Python are known to part, none of them reached by any plan, reply or result we have, and left
alone because Go is the one that stays:
- case: Python's re.I also folds i with the Turkish ı and İ ("JAVASCRİPT" names a language there), and its lower()
  knows a final Greek sigma and turns İ into two characters (so a heading in capitals matches a Greek title there);
- settingsOf has no Python parser: where ast.parse refuses a whole script for any syntax error it refuses one only
  for strings or brackets that don't close, and it takes `SETTINGS_s1 = other = {}`, which assigned_names doesn't;
- a fence's language: strings.Fields in codeBlocks keeps the control characters \\x1c-\\x1f that str.split() drops.

The binary comes from --chimera or $CHIMERA_BIN (build it with `go build -o <path> .` in app/, removing the old file
first). The cases are the eval's: nothing here goes into training data, and --out holds no case text beyond the
start of a difference.
"""
from __future__ import annotations

import argparse
import ast
import concurrent.futures
import json
import os
import random
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # worker-model/
if HERE not in sys.path:
    sys.path.insert(0, HERE)
APP = os.path.join(os.path.dirname(HERE), "app")

import evalset  # noqa: E402
from contract import planinfo, prompt  # noqa: E402
from contract import validate as V  # noqa: E402
from contract import texts as T  # noqa: E402
from contract.goport import clean_plan  # noqa: E402
from contract.join import join  # noqa: E402
from runner import cases as C  # noqa: E402
from tests import contract_fixtures as F  # noqa: E402

GO_FILE = os.path.join(APP, "hydra_contract.go")
NAMES_GO = os.path.join(APP, "blender_names.go")
PIECE_GO = os.path.join(APP, "hydra_piece.go")
FUZZ_SEED = 20261101
SHEET = "ShaderNodeEmission inputs: Color, Strength\nLight: color, energy, use_shadow"  # a stand-in for Blender's sheet
REFS = [{"title": "Keep the seat", "kind": "lesson", "summary": "A test reference.", "content": "x" * 3100},
        {"title": "Twö", "kind": "snippet", "summary": "", "content": "print('ok') {sid}"}]
CRITIQUE = "The legs float above the floor; fix them. {part}"

# Python name -> Go const in hydra_contract.go.
TEXTS = {
    "CONTRACT_OPENING": "contractOpening", "CONTRACT_PROJECT": "contractProject", "CONTRACT_PLAN_HEAD": "contractPlanHead",
    "CONTRACT_OUTLINE_OTHER": "contractOutlineOther", "CONTRACT_OUTLINE_YOURS": "contractOutlineYours",
    "CONTRACT_OUTLINE_USES": "contractOutlineUses", "CONTRACT_USED_BY": "contractUsedBy",
    "CONTRACT_USED_BY_NONE": "contractUsedByNone", "CONTRACT_JOIN_HEAD": "contractJoinHead",
    "CONTRACT_HANDOFF": "contractHandoff", "CONTRACT_LONE_OPENING": "contractLoneOpening",
    "MODE_BLENDER": "rulesBlender", "MODE_PYTHON_SCRIPT": "rulesPythonScript", "MODE_FILES": "rulesFiles",
    "MODE_SECTION": "rulesSection", "MODE_SECTION_RESEARCH": "rulesResearch", "CONTRACT_USER_STEP": "contractUserStep",
    "CONTRACT_USER_DEP_HEAD": "contractUserDepHead", "CONTRACT_USER_DEP_HANDOFF": "contractUserDepHandoff",
    "CONTRACT_USER_DEP_NO_HANDOFF": "contractUserDepNoHandoff", "CONTRACT_USER_DEP_FAILED": "contractUserDepFailed",
    "CONTRACT_ROUND2_PART": "contractRound2Part", "CONTRACT_ROUND2_CRITIQUE": "contractRound2Critique",
    "CONTRACT_ROUND2_NO_CRITIQUE": "contractRound2NoCritique", "CONTRACT_REPAIR": "contractRepair",
    "CONTRACT_REPAIR_IMPORTS": "contractRepairImports", "NAMES_HEAD": "contractNamesHead",
}
NUMBERS = {"CONTRACT_OUTLINE_CUT": "contractOutlineCut", "CONTRACT_USER_DEP_CUT": "contractUserDepCut",
           "CONTRACT_ROUND2_CUT": "contractRound2Cut", "STEP_ROOM": "contractRoom"}
WORD_LISTS = {"CODE_EXTS": ("codeExts", planinfo.CODE_EXTS), "_TECH_NOUNS": ("techNouns", planinfo._TECH_NOUNS),
              "_BEFORE": ("langBefore", planinfo._BEFORE), "_BEFORE_WITH": ("langBeforeWith", planinfo._BEFORE_WITH),
              "_WORD_NAMES": ("wordNames", planinfo._WORD_NAMES.replace("|Express", ""))}

_GO_STRING = re.compile(r'`[^`]*`|"(?:[^"\\\n]|\\.)*"')


def go_const(src, name):
    """The value of a Go const: a number, or string literals joined with +."""
    m = re.search(r"(?m)^\s*%s\s*=\s*" % re.escape(name), src)
    if not m:
        return None
    at = m.end()
    n = re.match(r"\d+", src[at:])
    if n:
        return int(n.group(0))
    out = ""
    while True:
        lit = _GO_STRING.match(src, at)
        if not lit:
            return None
        s = lit.group(0)
        out += s[1:-1] if s[0] == "`" else json.loads(s)
        plus = re.compile(r"\s*\+\s*").match(src, lit.end())
        if not plus or not _GO_STRING.match(src, plus.end()):
            return out
        at = plus.end()


def pattern_words(pattern):
    """The words a pattern's alternatives are made of, whichever way it groups them."""
    return sorted(re.findall(r"[A-Za-z_]+", re.sub(r"\(\?-?i?:?\)?|\\[wbsWBS]\*?|\\.", " ", pattern)))


def check_texts():
    """Every frozen text and word list against the Go source. Returns the differences."""
    with open(GO_FILE, encoding="utf-8") as f:
        src = f.read()
    with open(NAMES_GO, encoding="utf-8") as f:
        names_src = f.read()
    bad = []
    pairs = [(py, go, getattr(T, py)) for py, go in TEXTS.items()]
    pairs += [(py, go, getattr(T, py)) for py, go in NUMBERS.items()]
    pairs += [(py, go, v) for py, (go, v) in WORD_LISTS.items()]
    for py, go, want in pairs:
        got = go_const(src, go)
        if got != want:
            bad.append("text %s: Go's %s differs: %r" % (py, go, got if got is None else str(got)[:200]))
    if json.dumps(T.NAMES_HEAD, ensure_ascii=False) not in names_src:
        bad.append("text NAMES_HEAD: not namesBlock's words in app/blender_names.go")
    with open(PIECE_GO, encoding="utf-8") as f:
        piece_src = f.read()
    calls = re.search(r"var forbiddenCallNames = map\[string\]string\{(.*?)\n\}", piece_src, re.S)
    if dict(re.findall(r'"([^"]+)": "([^"]+)"', calls.group(1))) != V.FORBIDDEN_CALLS:
        bad.append("table FORBIDDEN_CALLS: Go's forbiddenCallNames differs")
    if go_const(piece_src, "maxPieceTokens") != V.MAX_PIECE_TOKENS:
        bad.append("number MAX_PIECE_TOKENS: Go's maxPieceTokens differs")
    for py, go, source in (("_HARMONY", "harmonyRe", piece_src), ("_WEB_DATA", "webDataRe", src), ("_BLENDER", "blenderWordsRe", src)):
        have = pattern_words(getattr(V, py).pattern if py == "_HARMONY" else getattr(planinfo, py).pattern)
        line = re.search(r"(?m)^\s*%s\s*=.*$" % go, source).group(0)
        if pattern_words("".join(re.findall(r"`([^`]*)`", line))) != have:
            bad.append("words %s: Go's %s differs" % (py, go))
    return bad, len(pairs) + 6


# ---------------------------------------------------------------- the cases

def case(group, where, plan, index, **kw):
    return dict(kw, group=group, where=where, plan=plan, index=index)


def frozen(es):
    """(task id, plan, outputs by plan id, goal, prior result, critique) for each frozen plan."""
    plans, deps = C.load_frozen()
    goals = C.task_goals(es)
    out = []
    for tid, item in plans.items():
        steps = (deps.get(tid) or {}).get("steps") or {}
        outputs = {sid: (st["reply"] if st.get("status") == "verified" else None) for sid, st in steps.items()}
        goal, _, prior, critique = goals.get(tid, ("", None, "", ""))
        out.append((tid, clean_plan(item["plan"]), outputs, goal, prior or None, critique if prior else None))
    return out


def lone(plan, i):
    """Step i on its own, as a one-step plan."""
    s = dict(plan["steps"][i], depends_on=[])
    return dict(plan, steps=[s])


def near_misses(reply):
    """A contract reply with its handoff rewritten every way workers have written it, and some they might."""
    m = re.search(r"```handoff\n(.*?)\n```\s*$", reply, re.S)
    if not m:
        return {}
    head, lines = reply[:m.start()], m.group(1)
    keys = lines.split("\n")
    block = "```handoff\n" + lines + "\n```"
    return {
        "plain": head + "```\n" + lines + "\n```\n", "text": head + "```text\n" + lines + "\n```",
        "yaml": head + "```yaml\n" + lines + "\n```\n", "unfenced": head + lines + "\n",
        "label": head + "handoff\n" + lines, "label-bold": head + "**Handoff:**\n\n" + lines + "\n\n",
        "label-heading": head + "### Handoff\n" + lines, "label-code": head + "`handoff`\n" + lines,
        "blank-lines": head + "\n\n".join(keys), "unclosed": head + "```handoff\n" + lines,
        "plain-unclosed": head + "```\n" + lines, "twice": head + lines + "\n\n" + block + "\n",
        "twice-label": head + "Handoff\n" + lines + "\n" + block,
        "twice-other": head + lines.replace("provides:", "provides: other,", 1) + "\n" + block,
        "two-blocks": head + "```handoff\nprovides: a\nuses: none\nassumed: none\n```\n\n" + block,
        "after": reply + "\nThat's all.", "crlf": reply.replace("\n", "\r\n"), "upper": head + block.upper(),
        "tilde": head + "~~~handoff\n" + lines + "\n~~~", "longer-fence": head + "````handoff\n" + lines + "\n````",
        "indented": head + "  ```handoff\n  " + "\n  ".join(keys) + "\n  ```",
        "extra-line": head + "```handoff\n" + lines + "\nnote: extra\n```",
        "missing-key": head + "```handoff\n" + "\n".join(keys[:2]) + "\n```",
        "none-forms": head + "```handoff\nprovides: None.\nuses: n/a\nassumed: -\n```",
        "spaced": head + "```handoff\n  Provides :  a  \n\tuses:\u00a0b\u202f\nASSUMED:c\n```", "only": block,
        "no-space": head + "\n```handoff\nprovides:x\nuses:y\nassumed:z\n```\n\n\n",
    }


def output_forms(text):
    return {"done": {"output": text, "status": "done"}, "library": {"output": text, "status": "library"},
            "no-status": {"output": text}, "failed": {"status": "failed"}, "failed-text": {"output": text, "status": "failed"},
            "null": {"output": None}, "empty": {}, "string": text, "none": None}


def settings_on_top(script):
    """A joined script with every SETTINGS_ dict in one part at the top, as an older joiner wrote it."""
    tree = ast.parse(script)
    lines = script.split("\n")
    cut, dicts = set(), []
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "").startswith("SETTINGS_"):
            dicts.append("\n".join(lines[node.lineno - 1:node.end_lineno]))
            cut.update(range(node.lineno - 1, node.end_lineno))
    if not dicts:
        return ""
    first = next(i for i, l in enumerate(lines) if l.startswith("# --- "))
    return "\n".join(lines[:first] + ["# Settings"] + "\n\n# next one\n".join(dicts).split("\n") + ["", ""] +
                     [l for i, l in enumerate(lines) if i >= first and i not in cut])


def round2_cases(tid, plan, outputs, goal):
    """Round 2 on one plan: its joined result, and that result under a changed plan."""
    out = []
    j = join(plan, outputs, goal=goal)
    n = len(plan["steps"])
    prevs = {}
    if j.text:
        prevs["joined"] = j.text
    if j.script:
        prevs["script"] = "```python\n" + j.script + "\n```"
        top = settings_on_top(j.script)
        if top:
            prevs["settings-on-top"] = "Done.\n\n```python\n" + top + "\n```\n"
    for name, prev in prevs.items():
        for i in range(n):
            out.append(case("round2", "%s/s%d %s" % (tid, i + 1, name), plan, i, outputs=outputs, goal=goal,
                            prev_result=prev, critique=CRITIQUE))
        if n > 1:  # a step moved up: its names change with its place
            short = dict(plan, steps=[dict(s, depends_on=[]) for s in plan["steps"][1:]])
            for i in range(n - 1):
                out.append(case("round2", "%s/s%d moved %s" % (tid, i + 1, name), short, i, outputs=outputs, goal=goal,
                                prev_result=prev))
    for i in range(n):
        for name, prev in (("unrelated", "Some other result."), ("empty", ""), ("long", "é" * 3100)):
            out.append(case("round2", "%s/s%d %s" % (tid, i + 1, name), plan, i, outputs=outputs, goal=goal,
                            prev_result=prev, critique="" if name == "empty" else CRITIQUE))
    return out


CRASHES = {
    "function": {"step": "s1", "function": "build_s1", "piece_line": 41, "source": 'x.inputs["Transmission"]',
                 "error": "KeyError: 'Transmission'", "runner": "Blender 5.2.2"},
    "helper": {"step": "s2", "part": "helper", "function": "_s2_LEG", "piece_line": 7, "source": "y = {piece}",
               "error": "NameError: name 'a' is not defined", "runner": "Blender 5.0.1"},
    "settings": {"step": "s2", "part": "settings", "function": None, "piece_line": 3, "source": "s", "error": "e"},
    "import": {"step": "s3", "part": "import", "function": None, "piece_line": 1, "source": "import x", "error": "e",
               "runner": "Python 3.13"},
    "bare": {"source": "a", "error": "b"},
    "line-only": {"line": 90, "piece_line": None, "source": "", "error": "e", "runner": ""},
    "nothing": {},
}


def step_cases(es):
    frozen_plans = frozen(es)
    out = []
    # every W1-W4 case, as the runners build it
    for c in C.load_cases(es):
        kw = dict(outputs=c.outputs, goal=c.goal)
        if c.repair:
            kw.update(piece=c.repair["piece"], crash=c.repair["crash"])
        elif c.prev_result is not None:
            kw.update(prev_result=c.prev_result, critique=c.critique)
        out.append(case(c.part, c.id, c.plan, c.index, **kw))
        if c.part != "w1":
            out.append(case("lone", c.id, lone(c.plan, c.index), 0, outputs={}, goal=c.goal))
    samples = []
    for tid, plan, outputs, goal, prior, critique in frozen_plans:
        n = len(plan["steps"])
        for i, s in enumerate(plan["steps"]):
            where = "%s/s%d" % (tid, i + 1)
            kw = dict(outputs=outputs, goal=goal)
            if prior:
                kw.update(prev_result=prior, critique=critique)
            out.append(case("frozen", where, plan, i, **kw))
            out.append(case("lone", where, lone(plan, i), 0, outputs={}, goal=goal))
            deps = planinfo.dep_indexes(plan, i)
            if deps:
                out.append(case("failed", where + " all", plan, i, outputs={}, goal=goal))
                for j in deps:
                    did = plan["steps"][j]["id"]
                    out.append(case("failed", "%s %s" % (where, did), plan, i, outputs=dict(outputs, **{did: None}), goal=goal))
                    text = outputs.get(did) or "A reply.\n"
                    for name, v in output_forms(text).items():
                        out.append(case("outputs", "%s %s %s" % (where, did, name), plan, i,
                                        outputs=dict(outputs, **{did: v}), goal=goal))
                    if outputs.get(did):
                        samples.append((plan, i, outputs, did, goal, where))
            reply = outputs.get(s["id"])
            if reply:
                for name, crash in CRASHES.items():
                    out.append(case("repair", "%s %s" % (where, name), plan, i, outputs=outputs, goal=goal,
                                    piece="\u00a0\n" + reply + "\x1c\n", crash=crash))
            out.append(case("names", where, plan, i, outputs=outputs, goal=goal, refs=REFS, names=SHEET, room=16384))
            # every plan's words through code_mode, whatever its kinds
            coded = dict(plan, kind="code", steps=[dict(st, kind="code") for st in plan["steps"]])
            out.append(case("modes", where, coded, i, outputs={}, goal=goal))
            research = dict(plan, steps=[dict(st, kind="research") for st in plan["steps"]])
            out.append(case("modes", where + " research", research, i, outputs=outputs, goal=goal))
        out += round2_cases(tid, plan, outputs, goal)
    for plan, i, outputs, did, goal, where in samples[:60]:
        for name, reply in near_misses(outputs[did]).items():
            out.append(case("handoff", "%s %s %s" % (where, did, name), plan, i, outputs=dict(outputs, **{did: reply}), goal=goal))
    return out


def raw_plan(*steps, **kw):
    return dict({"title": "P", "kind": "code", "summary": "S"}, **kw, steps=[
        {"id": sid, "title": t, "kind": k, "instructions": ins, "depends_on": deps} for sid, t, k, ins, deps in steps])


def hand_cases():
    """What the eval's plans don't reach: plans cleanPlan has to fix, cuts inside a character, literal braces,
    and scripts that make the settings reader work."""
    plans = {
        "dup-ids": raw_plan(("a", "A", "code", "x", []), ("a", "B", "code", "y", ["a"]), ("a", "C", "code", "z", ["a", "a"])),
        "clash": raw_plan(("s2", "A", "code", "x", []), ("s2", "B", "code", "y", ["s2"]), ("s3", "C", "code", "z", ["s2"])),
        "forward-deps": raw_plan(("a", "A", "code", "x", ["b"]), ("b", "B", "code", "y", ["b", "c"]), ("c", "C", "writing", "z", ["a", "b", "a"])),
        "blanks": raw_plan(("", " ", "nonsense", "", []), ("", "\u00a0", "", "\x85", []), ("x", "\x1c", "code", "\t", [])),
        "no-title": raw_plan(("a", "A", "code", "x", []), title="  ", summary="", kind="odd"),
        "nine": raw_plan(*[("s%d" % k, "T%d" % k, "writing", "x", []) for k in range(1, 11)]),
        "braces": raw_plan(("a", "{summary} {sid}", "code", "{title} {n}", []), ("b", "{name}", "code", "{instructions}", ["a"]),
                           title="{summary}", summary="{title}"),
        "whitespace": raw_plan(("a", "  A\n\tB\u00a0C\u202fD\x1cE\u3000F  ", "writing", "one\n\ntwo\x1fthree " + "é" * 400, []),
                               ("b", "Two", "general", "x", ["a"])),
        "percent": raw_plan(("a", "100%s", "code", "%d %s", []), ("b", "%v", "code", "%", ["a"]), summary="%"),
        "nulls": dict(raw_plan(("a", "A", "code", "x", [])), summary=None, steps=[
            {"id": None, "title": None, "kind": None, "instructions": None, "depends_on": None},
            {"id": "b", "title": "B", "kind": "code", "instructions": "y", "depends_on": ["s1"]}]),
    }
    out = []
    for name, p in plans.items():
        outputs = {s["id"]: "Reply of %s.\n" % s["id"] for s in p["steps"]}
        for i in range(min(len(p["steps"]), 8)):
            out.append(case("clean", name, p, i, outputs=outputs))
            out.append(case("clean", name + " round 2", p, i, outputs=outputs, prev_result="## %s\ntext" % p["steps"][i]["title"]))
    big = raw_plan(("a", "A", "code", "x", []), ("b", "B", "code", "y", ["a"]))
    for k in range(7990, 8006):  # a dependency cut inside a two-byte and a three-byte character
        for ch in ("é", "→", "\U0001f600"):
            text = "x" * k + ch * 10 + "\n```handoff\nprovides: a\nuses: none\nassumed: none\n```"
            out.append(case("clean", "cut %d %s" % (k, ch), big, 1, outputs={"a": text}))
    for k in range(5990, 6006):
        out.append(case("clean", "round 2 cut %d" % k, big, 1, outputs={"a": "x"}, prev_result="y" * k + "→" * 9))
    out += settings_cases()
    for name, plan, pieces in (("fixture-blender", F.BLENDER_PLAN, F.BLENDER_OUTPUTS),
                               ("fixture-script", F.SCRIPT_PLAN, {"s1": F.SCRIPT_A, "s2": F.SCRIPT_B}),
                               ("fixture-files", F.FILES_PLAN, {"s1": F.FILES_1, "s2": F.FILES_2, "s3": F.FILES_3}),
                               ("fixture-section", F.SECTION_PLAN, {"s1": F.SECTION_1, "s2": F.SECTION_2})):
        out += round2_cases(name, plan, pieces, "")
    return out


# The scripts settingsOf has to read. {old} is the step's number in the script.
SETTINGS_SCRIPTS = {
    "plain": 'import bpy\n\n# about s1\n\nSETTINGS_s1 = {\n    "a": 1,\n}\n\n# --- s1: Table ---\ndef build_s1(ctx):\n    pass\n',
    "annotated": 'SETTINGS_s1: dict = {"a": 1}\n# --- s1: Table ---\ndef build_s1(ctx):\n    pass\n',
    "annotated-bare": 'SETTINGS_s1 : dict\n# --- s1: Table ---\ndef build_s1(ctx):\n    pass\n',
    "semicolon": 'x = 1; SETTINGS_s1 = {"a": 1}\n# --- s1: Table ---\ndef build_s1(ctx):\n    pass\n',
    "semicolon-after": 'SETTINGS_s1 = {"a": 1}; y = 2\n# --- s1: Table ---\ndef build_s1(ctx):\n    pass\n',
    "in-string": 'DOC = """\nSETTINGS_s1 = {"fake": 1}\n"""\n\nSETTINGS_s1 = {"a": "]"}\n# --- s1: Table ---\ndef build_s1(ctx):\n    pass\n',
    "in-comment": '# SETTINGS_s1 = {"fake": 1}\nSETTINGS_s1 = {"a": 1}  # { not a bracket\n# --- s1: Table ---\ndef build_s1(ctx):\n    pass\n',
    "indented-first": 'def f():\n    SETTINGS_s1 = {"fake": 1}\n\n\nSETTINGS_s1 = {"a": 1}\n# --- s1: Table ---\ndef build_s1(ctx):\n    pass\n',
    "continued": 'SETTINGS_s1 = \\\n    {"a": 1,\n     "b": (1, 2)}\n# --- s1: Table ---\ndef build_s1(ctx):\n    pass\n',
    "compared": 'SETTINGS_s1 == 1\nSETTINGS_s1 = {"a": 1}\n# --- s1: Table ---\ndef build_s1(ctx):\n    pass\n',
    "one-line-if": 'if x: SETTINGS_s1 = 1; y = 2\nSETTINGS_s1 = {"a": 1}\n# --- s1: Table ---\ndef build_s1(ctx):\n    pass\n',
    "other-step-first": 'SETTINGS_s2 = {"b": 1}\n\n\nSETTINGS_s1 = {"a": 1}\n# --- s1: Table ---\ndef build_s1(ctx):\n    pass\n',
    "strings": "NOTE = 'it\\'s (' + \"a\\\"b[\" + r'\\'{' + f'{1}('\nSETTINGS_s1 = {'a': 1}\n# --- s1: Table ---\ndef build_s1(ctx):\n    pass\n",
    "none": '# --- s1: Table ---\ndef build_s1(ctx):\n    pass\n',
    "nothing-in-its-part": '# --- s1: Table ---\n# --- s2: Lamp ---\ndef build_s2(ctx):\n    pass\n',
    "else-semicolon": 'if a:\n    b = 1\nelse: c = 2; SETTINGS_s1 = {"fake": 1}\nSETTINGS_s1 = {"a": 1}\n# --- s1: Table ---\ndef build_s1(ctx):\n    pass\n',
}


def settings_cases():
    p = raw_plan(("a", "Table", "blender", "Build it.", []), ("b", "Lamp", "blender", "Add it.", ["a"]), kind="blender")
    out = []
    for name, script in SETTINGS_SCRIPTS.items():
        prev = "```python\n" + script + "```\n"
        out.append(case("settings", name, p, 0, outputs={"a": "x"}, prev_result=prev))
        moved = raw_plan(("b", "Lamp", "blender", "Add it.", []), ("a", "Table", "blender", "Build it.", []), kind="blender")
        out.append(case("settings", name + " moved", moved, 1, outputs={"b": "x"}, prev_result=prev))
    return out


# ---------------------------------------------------------------- seeded random text for the patterns

VOCAB = """Blender blender BLENDER bpy BMESH mathutils blenders bpyx .blend x.blend .blender .BLEND EEVEE Eevee eevee EEVEEs
javascript JavaScript typescript node.js nodejs Node.JS deno golang kotlin haskell perl powershell objective-c php scala
scalable lua java javas JAVA jquery next.js nuxt vue.js vuejs react.js reactjs angularjs sveltekit swiftui gradle npm webpack
html5 neoforge spigot bukkit nullpointerexception userscript xcode c++ C++ c# C# c+++ c## c csharp dotnet .NET ASP.NET .net
x.NETy NET Rust Swift Ruby Rails Dart Flutter Elixir React Angular Vue Svelte Electron Jest Node Express rust swift react
in In using Using with With written Written Go go GO golang program programs module code package service server binary CLI
tool app apps crate gem component hook backend frontend API script compiler page pages site website template UI widget
route middleware plugin extension test tests Native router controller file function struct trait macro form forms HTML CSS
JS html css / and & + , page file frontend markup stylesheet styles selector grid layout animation scrape parses crawling
fetches download extracted generates rendered export outputs output converts save saves saving saved print prints printing
email emails read reads reading report . ! ? main.py src/store.py a/b/c.ts ./x.go /usr/bin/x.sh data.csv report.json x.pyc
x.pyi a.b.py my-file.rs x_y.lua Dockerfile Makefile package.json go.mod Cargo.toml requirements.txt pyproject.toml
my-package.json xDockerfile Dockerfiles""".split()
PHRASES = ["geometry nodes", "Geometry Nodes", "principled bsdf", "pointiness", "react native", "spring boot", "bash script",
           "shell script", "zsh script", "minecraft mod", "fabric mod", "forge mod", "chrome extension", "browser extension",
           "firefox add-on", "android app", "front end", "front-end", "on Rails", "written in", "Written in", "HTML/CSS",
           "HTML and JavaScript", "CSS + JS", "HTML , CSS", "in HTML", "Using CSS", "in Go", "with Rust", "in Express",
           "Go program", "Go tools", "React component", "Rust code-base", "my Express API", "with Express shipping"]
SEPS = [" "] * 14 + ["  ", "\t", "\n", "\u00a0", "\u202f", "\u2011", "\u3000", "\x1c", "\x85", "\u2028", "-", "_", ".", ",", "/",
                     "(", ")", "", "é", "日本", "\u0301", "²", "½", "ﬁ", "\u212a", "ſ", '"', "'", ":", "#", "+"]
PATH_BITS = ["src", "a.b", "my-dir", "x_y", "é", "data", "..", ".", "lib2"]
EXTS = planinfo.CODE_EXTS.split("|") + ["csv", "json", "pyc", "pyx", "md", "txt", "pyi2", "PY", "Go"]


def fuzz_text(rng):
    # short texts, and no Blender words in half: one word that should count mustn't hide behind another
    vocab = VOCAB if rng.random() < .5 else [w for w in VOCAB if not re.search(r"(?i)blend|bpy|bmesh|mathutils|eevee", w)]
    words = [rng.choice(PHRASES) if rng.random() < .2 else rng.choice(vocab) for _ in range(rng.choice((1, 2, 2, 3, 3, 4, 6, 10)))]
    out = rng.choice(["", "", " ", "\n", "é"])
    for w in words:
        if rng.random() < .2:  # Python's \s takes these, RE2's doesn't
            w = w.replace(" ", rng.choice(["\u00a0", "\u202f", "\u3000", "\x1c", "\x85", "\v", "  ", "\n", "\t"]))
        out += w + rng.choice(SEPS)
    return out


def fuzz_path(rng):
    bits = [rng.choice(PATH_BITS) for _ in range(rng.randint(0, 3))]
    return "/".join(bits + [rng.choice(["main", "a-b", "x_1", "é", "store"]) + "." + rng.choice(EXTS)])


def fuzz_cases(n, seed=FUZZ_SEED):
    rng = random.Random(seed)
    out = []
    for k in range(n):
        p = raw_plan(("a", "Step", "code", fuzz_text(rng), []))
        out.append(case("fuzz", "words %d" % k, p, 0, outputs={}))
    for k in range(n // 4):
        paths = [fuzz_path(rng) for _ in range(rng.randint(1, 3))]
        words = "Write " + rng.choice(SEPS).join(paths) + rng.choice(SEPS)
        prev = "\n\n".join(rng.choice(["File: %s\n```python\nx = 1\n```", "**File:** `%s`\n\n```js\ny\n```", "File: %s (part)\n~~~go\nz\n~~~",
                                       "### File: %s:\n```\nq\n```", "File: %s extra\n```\nq\n```"]) % q for q in paths)
        p = raw_plan(("a", "Files", "code", words, []), ("b", "Other", "code", "Write src/other.py", []))
        out.append(case("fuzz", "paths %d" % k, p, 0, outputs={}, prev_result=prev))
    for k in range(n // 4):
        title = fuzz_text(rng).strip() or "Title"
        other = rng.choice([title, title.upper(), title + "!", "  " + title, title.replace(" ", "\u00a0"), "Else"])
        script = "```python\n# --- s%d: %s ---\nSETTINGS_s%d = {}\ndef build_s%d(ctx):\n    _s%d_x(ctx); build_s%dx; a_s%d_; SETTINGS_s%d[0]\n" \
                 "\ndef main():\n    pass\n\nif __name__ == \"__main__\":\n    main()\n```\n" % ((2, other) + (2,) * 6)
        p = raw_plan(("a", title, "blender", "Build it.", []), kind="blender")
        out.append(case("fuzz", "titles %d" % k, p, 0, outputs={}, prev_result=script))
        p = raw_plan(("a", title, "code", "Write it.", []), ("b", "Other", "code", "More.", []))
        out.append(case("fuzz", "script titles %d" % k, p, 0, outputs={}, prev_result=script))
        p = raw_plan(("a", title, "writing", "Write it.", []), ("b", "Other", "writing", "More.", []), kind="writing")
        out.append(case("fuzz", "sections %d" % k, p, 0, outputs={}, prev_result="# Top\n\n## %s\n  text\n\n## Other\nmore\n" % other))
    return out


# ---------------------------------------------------------------- running

def py_request(c):
    plan = clean_plan(c["plan"])
    kw = dict(goal=c.get("goal") or "", refs=c.get("refs"), names=c.get("names") or "", room=c.get("room", T.STEP_ROOM))
    if c.get("crash") is not None:
        return prompt.repair_request(plan, c["index"], c.get("outputs") or {}, c["piece"], c["crash"], **kw).to_dict()
    return prompt.worker_request(plan, c["index"], c.get("outputs") or {}, prev_result=c.get("prev_result"),
                                 critique=c.get("critique"), **kw).to_dict()


def go_input(c):
    return json.dumps({k: v for k, v in c.items() if k not in ("group", "where")}, ensure_ascii=False)


class CouldNotRun(Exception):
    pass


def go_request(binary, c):
    p = subprocess.run([binary, "--hydra-worker-request"], input=go_input(c).encode("utf-8"), capture_output=True)
    if p.returncode != 0:
        raise CouldNotRun("%s/%s: exit %d: %s" % (c["group"], c["where"], p.returncode, p.stderr.decode("utf-8", "replace")[:400]))
    return json.loads(p.stdout)


def first_difference(py, go):
    for key in sorted(set(py) | set(go)):
        a, b = py.get(key), go.get(key)
        if a == b:
            continue
        if key == "messages" and isinstance(b, list) and len(a) == len(b):
            for n, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    s, t = x["content"], y["content"]
                    at = next((k for k, (p, q) in enumerate(zip(s, t)) if p != q), min(len(s), len(t)))
                    return "message %d differs at %d (lengths %d, %d):\n      Python %r\n      Go     %r" % (
                        n, at, len(s), len(t), s[max(0, at - 40):at + 60], t[max(0, at - 40):at + 60])
        return "%s: Python %r, Go %r" % (key, str(a)[:200], str(b)[:200])
    return ""


def unused_texts(seen):
    """Frozen texts no request held. Placeholders split a text into the literal runs that must appear."""
    out = []
    for py in TEXTS:
        for run in re.split(r"\{\w+\}", getattr(T, py)):
            if run.strip() and not any(run in s for s in seen):
                out.append(py)
                break
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chimera", default=os.environ.get("CHIMERA_BIN", ""), help="a Chimera binary (default: $CHIMERA_BIN)")
    ap.add_argument("--fuzz", type=int, default=1200, help="how many random texts")
    ap.add_argument("--seed", type=int, default=FUZZ_SEED, help="their seed")
    ap.add_argument("--texts-only", action="store_true", help="only the frozen texts against the Go source")
    ap.add_argument("--out", help="also write the report here")
    a = ap.parse_args(argv)

    bad, ntexts = check_texts()
    lines = ["Frozen texts and word lists: %d, %d differ." % (ntexts, len(bad))] + bad
    if not a.texts_only:
        if not a.chimera or not os.path.exists(a.chimera):
            print("no Chimera binary: pass --chimera PATH or set CHIMERA_BIN (see tools/check_contract_parity.py)")
            return 2
        es = evalset.load()
        cs = step_cases(es) + hand_cases() + fuzz_cases(a.fuzz, a.seed)
        counts, wrong = {}, {}
        seen, modes = set(), {}
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(24, (os.cpu_count() or 4) * 2)) as pool:
                goes = list(pool.map(lambda c: go_request(a.chimera, c), cs, chunksize=1))
        except CouldNotRun as e:
            print("couldn't run the binary (is it older than --hydra-worker-request? rebuild it): %s" % e)
            return 2
        for c, go in zip(cs, goes):
            counts[c["group"]] = counts.get(c["group"], 0) + 1
            py = py_request(c)
            diff = first_difference(py, go)
            if diff:
                wrong.setdefault(c["group"], []).append("  %s %s: %s" % (c["group"], c["where"], diff))
                bad.append(diff)
            modes[go["mode"]] = modes.get(go["mode"], 0) + 1
            for m in go["messages"]:
                seen.add(m["content"])
        unused = unused_texts(seen)
        lines.append("Requests: %d, %d differ." % (len(cs), sum(len(v) for v in wrong.values())))
        lines.append("  by group: " + ", ".join("%s %d" % (k, v) for k, v in counts.items()))
        lines.append("  by mode: " + ", ".join("%s %d" % (k, v) for k, v in sorted(modes.items())))
        for group, diffs in wrong.items():
            lines += diffs[:8] + (["  … and %d more in %s" % (len(diffs) - 8, group)] if len(diffs) > 8 else [])
        if unused:
            lines.append("Frozen texts no request held: " + ", ".join(unused))
            bad += unused
    report = "\n".join(lines)
    print(report)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(report + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
