#!/usr/bin/env python3
"""Check the contract's validator and joiner in Go against the Python prototype they were ported from.

    CHIMERA_BIN=path python3 tools/check_join_parity.py        # exit 1 on any difference, 2 if it couldn't run
    python3 tools/check_join_parity.py --chimera PATH --out results.txt
    python3 tools/check_join_parity.py --sample 150 --fuzz 3000   # the quick run the test does

Go (app/hydra_piece.go, hydra_assemble.go, hydra_pyscan.go) is the source of truth for what counts as a kept contract
and what a joined script says, and data generation gets both from `chimera --hydra-assemble`. The measured results
stand on contract/validate.py and join.py, so the two must not differ. This script runs both over:

- replies: every step reply in results/runs/*/raw.jsonl and results/runs-tasks/*/raw.jsonl, validated in its own mode
  with its own step, dependencies and done_reason, comparing every field of the verdict;
- tasks: each stored task's whole set of pieces joined as the runs did, and joined again with the broken pieces taken
  out, each step failed in turn, each step as a library entry, and with reject_cut, comparing everything join returns
  (the script and text byte for byte, the line map, seams, reasons, notes, parts and every piece's verdict), and each
  good Blender piece's run-alone script;
- fixtures: every call the contract's own tests make to the validator, the joiner and their helpers, recorded by
  running those tests;
- random: seeded replies built from the forms the patterns tell apart (handoffs near and far from the contract's,
  File: lines, headings, links, odd spaces and letters), in every mode, seeded plans of files and sections, which the
  stored tasks hardly have, and uses lines, whose heuristics no stored task reaches far into;
- python: real Python files, source by source, and tests/python_syntax_cases.py's corners of the grammar: the reader's
  tree against ast's, or its error against Python's;
- fuzz: seeded damage to the corpus's code, which is what shows a reader's weakness. Here Python is the judge: Go must
  never reject what Python accepts (a failure), and accepted code must read to the same tree. Where Python rejects,
  Go either says the same, says it differently, or doesn't see it; the last two are counted, not failed: the result
  check runs the script in real Blender anyway. A reply's verdict is compared whole unless the code in it is one of
  those. The syntax cases are stricter: Python's words have to match there, but for their short list of exceptions.

The code list is read from the prototype, and a full run fails if any issue or seam code was never compared. To be
sure a clean run means something, the port was broken 60 ways on a copy. All were caught but one that changes nothing:
pySegments' max(prevEnd, end), since statements' ends never go down.

Known places Go and Python part, none of them reached by any reply, task or fixture:
- a syntax error the reader can't see. Go reads on, so it reports other issues or none. That's only known of the
  unicode name in \\N{...}, since the app has no table of names, but compile() has checks no list can exhaust;
- the words of a syntax error, on rarer mistakes: about 1 in 1,000 in the damaged scripts, the same code and level, and
  nearly always the same line. Mostly CPython's second pass using results it memoized with its checks off, which has
  no meaning without its memo table;
- NFKC: Python folds identifiers (a micro sign becomes mu), and the Go standard library can't;
- str.isdigit counts superscripts as digits, and unicode.IsDigit doesn't (a uses word starting with \u00b2);
- case, as in tools/check_contract_parity.py: Turkish dotted letters and a final Greek sigma;
- a lone surrogate in a reply, which Go's JSON can't carry.

Nothing here goes into training data. The binary comes from --chimera or $CHIMERA_BIN (build it with `go build -o
<path> .` in app/, removing the old file first), and --out holds no reply text beyond the start of a difference.
"""
from __future__ import annotations

import argparse
import ast
import collections
import concurrent.futures
import copy
import glob
import json
import os
import random
import re
import subprocess
import sys
import warnings

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # worker-model/
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import evalset  # noqa: E402
from contract import join as J, planinfo  # noqa: E402
from contract import linemap as L  # noqa: E402
from contract import validate as V  # noqa: E402
from contract.goport import clean_plan  # noqa: E402
from runner import cases as C  # noqa: E402
from tests.python_syntax_cases import CASES as SYNTAX_CASES, EXCEPTIONS as SYNTAX_EXCEPTIONS  # noqa: E402

RESULTS = os.path.join(HERE, "results")
FUZZ_SEED = 20261102
BATCH_BYTES = 4_000_000  # one Go process's worth of sources
MAX_SHOWN = 12


def go_call(binary, payload):
    """Run --hydra-assemble on one JSON object."""
    p = subprocess.run([binary, "--hydra-assemble"], input=json.dumps(payload), capture_output=True, text=True,
                       timeout=600)
    if p.returncode:
        raise RuntimeError("chimera --hydra-assemble failed: " + p.stderr[-2000:])
    return json.loads(p.stdout)


def batched(items, size_of, limit=BATCH_BYTES):
    """items in lists of about limit bytes."""
    out, size = [], 0
    for it in items:
        out.append(it)
        size += size_of(it)
        if size > limit:
            yield out
            out, size = [], 0
    if out:
        yield out


def first_difference(a, b, path=""):
    """Where two JSON values first differ, "" if they don't."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in list(a) + [k for k in b if k not in a]:
            d = first_difference(a.get(k), b.get(k), path + "." + str(k))
            if d:
                return d
        return ""
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return "%s: %d items in Python, %d in Go" % (path, len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_difference(x, y, "%s[%d]" % (path, i))
            if d:
                return d
        return ""
    if a == b:
        return ""
    if isinstance(a, str) and isinstance(b, str):
        i = next((n for n, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        return "%s differs at %d: %r / %r" % (path, i, a[max(0, i - 40):i + 60], b[max(0, i - 40):i + 60])
    return "%s: %r / %r" % (path, str(a)[:160], str(b)[:160])


# ---------------------------------------------------------------- Python's side, in Go's JSON

def issue_dict(i):
    d = {"level": i.level, "code": i.code, "message": i.message, "line": i.line}
    if getattr(i, "sid", None):
        d["step"] = i.sid
    return d


def piece_dict(p):
    return {"sid": p.sid, "mode": p.mode, "ok": p.ok, "contract_ok": p.contract_ok, "form_ok": p.form_ok,
            "issues": [issue_dict(i) for i in p.issues], "handoff": p.handoff.to_dict() if p.handoff else None,
            "files": [{"path": f.path, "part": f.part, "lang": f.lang} for f in p.files], "body": p.body,
            "code": p.code or "", "code_line": p.code_line, "section": p.section or "", "library": p.library}


def join_dict(j):
    return {"title": j.plan_title, "fallback": j.fallback, "reasons": j.reasons, "seams": [issue_dict(s) for s in j.seams],
            "notes": j.notes, "failed": j.failed, "script": j.script, "script_kind": j.script_kind or "", "text": j.text,
            "linemap": j.linemap.to_dict() if j.linemap else None, "files": j.files, "parts": j.parts,
            "assumptions": [list(a) for a in j.assumptions], "assumptions_note": j.assumptions_note(),
            "editor_wanted": j.editor_wanted, "pieces": [piece_dict(p) for p in j.pieces.values()]}


def scan_python(src):
    """What ast makes of src, in the form --hydra-assemble's scan writes."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return {"ok": True, "tree": canon(ast.parse(src))}
        except SyntaxError as e:
            return {"ok": False, "line": e.lineno or 0, "msg": e.msg}


_SKIP = (ast.expr_context, ast.operator, ast.boolop, ast.unaryop, ast.cmpop, ast.alias, ast.pattern, ast.type_ignore)
_OPS = {ast.Eq: "Eq", ast.NotEq: "NotEq", ast.Lt: "Lt", ast.LtE: "LtE", ast.Gt: "Gt", ast.GtE: "GtE", ast.Is: "Is",
        ast.IsNot: "IsNot", ast.In: "In", ast.NotIn: "NotIn"}


def canon(n):
    """pyDump's text for an ast node: every node the checks can walk to, its lines, names and constants."""
    out = ["(%s %d" % (type(n).__name__, getattr(n, "lineno", 0))]
    if isinstance(n, (ast.stmt, ast.ExceptHandler)):
        out.append("-%d" % n.end_lineno)
    elif isinstance(n, ast.match_case):
        out.append("-%d" % n.body[-1].end_lineno)
    name = None
    if isinstance(n, ast.Name):
        name = n.id
    elif isinstance(n, ast.Attribute):
        name = n.attr
    elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.TypeVar, ast.ParamSpec, ast.TypeVarTuple,
                        ast.ExceptHandler)):
        name = n.name
    elif isinstance(n, (ast.keyword, ast.arg)):
        name = n.arg
    elif isinstance(n, ast.ImportFrom):
        name = n.module
    if name:
        out.append(" " + name)
    if isinstance(n, ast.Constant):
        v = n.value
        kind = {None: "None", True: "True", False: "False", Ellipsis: "Ellipsis"}.get(v, None) \
            if v is None or v is True or v is False or v is Ellipsis else type(v).__name__
        out.append(" " + kind)
        if isinstance(v, str):
            out.append(" " + v.encode("utf-8", "surrogatepass").hex())
    if isinstance(getattr(n, "ctx", None), ast.Store):
        out.append(" store")
    if isinstance(n, (ast.BoolOp, ast.UnaryOp)):
        out.append(" " + type(n.op).__name__)
    if isinstance(n, ast.BinOp):
        out.append(" " + (type(n.op).__name__ if isinstance(n.op, (ast.Add, ast.Sub)) else "Other"))
    if isinstance(n, ast.Compare):
        out.append(" " + ",".join(_OPS[type(o)] for o in n.ops))
    if isinstance(n, (ast.Import, ast.ImportFrom)):
        out += [" " + a.name + (":" + a.asname if a.asname else "") for a in n.names]
    if isinstance(n, ast.ImportFrom):
        out.append(" .%d" % n.level)
    for c in ast.iter_child_nodes(n):
        if not isinstance(c, _SKIP) and not (isinstance(n, ast.JoinedStr) and isinstance(c, ast.Constant)):
            out.append(" " + canon(c))
    out.append(")")
    return "".join(out)


# ---------------------------------------------------------------- the corpus

def step_cases():
    """Every eval step case by id."""
    es = evalset.load()
    return es, {c.id: c for c in C.load_cases(es)}


def reply_jobs():
    """One validate job per stored step reply: (label, kwargs of validate_piece, text). A reply's own record gives
    its mode and done_reason; its case gives the rest, as the runs had it."""
    es, cases = step_cases()
    plans, _ = C.load_frozen()
    goals = C.task_goals(es)
    out = []
    for path in sorted(glob.glob(os.path.join(RESULTS, "runs", "*", "raw.jsonl"))):
        run = os.path.basename(os.path.dirname(path))
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f):
                r = json.loads(line)
                c = cases.get(r["id"])
                kw = {"sid": c.sid, "deps": c.deps, "lone": c.lone, "step": c.step} if c else {}
                reason = (r.get("stats") or {}).get("done_reason") or r.get("done_reason") or ""
                out.append(("%s/%d" % (run, n), dict(kw, mode=r["mode"], done_reason=reason, reject_cut=True, max_tokens=None),
                            r.get("reply") or ""))
    for rec, run, n in stored_tasks():
        plan, goal = task_plan(rec, plans, goals, es)
        for i, s in enumerate(rec["steps"]):
            kw = {"mode": s.get("mode") or planinfo.step_mode(plan, i, goal), "sid": "s%d" % (i + 1),
                  "deps": planinfo.dep_names(plan, i), "lone": len(plan["steps"]) == 1, "step": plan["steps"][i],
                  "done_reason": s.get("done_reason") or (s.get("stats") or {}).get("done_reason") or "",
                  "reject_cut": False, "max_tokens": None}
            out.append(("%s/%d/%s" % (run, n, kw["sid"]), kw, s.get("reply") or ""))
    return out


def stored_tasks():
    for path in sorted(glob.glob(os.path.join(RESULTS, "runs-tasks", "*", "raw.jsonl"))):
        run = os.path.basename(os.path.dirname(path))
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f):
                yield json.loads(line), run, n


def task_plan(rec, plans, goals, es):
    """(the cleaned plan, the goal) a stored task ran with."""
    tid = rec["task"]
    if tid in plans:
        return plans[tid]["plan"], goals.get(tid, ("",))[0]
    plan = clean_plan(es.by_id(tid)["plan"])
    return plan, "%s: %s" % (plan["title"], plan["summary"])


def task_jobs():
    """(label, plan, outputs, goal, done_reasons, reject_cut) for every stored task, and the variants above."""
    es = evalset.load()
    plans, _ = C.load_frozen()
    goals = C.task_goals(es)
    out = []
    for rec, run, n in stored_tasks():
        plan, goal = task_plan(rec, plans, goals, es)
        label = "%s/%s" % (run, rec["task"])
        outputs, reasons = {}, {}
        for st, s in zip(plan["steps"], rec["steps"]):
            outputs[st["id"]] = None if s.get("status") == "failed" else s.get("reply") or ""
            reasons[st["id"]] = "length" if s.get("runaway") else (s.get("stats") or {}).get("done_reason") or ""
        out.append((label, plan, outputs, goal, reasons, False))
        out.append((label + " reject_cut", plan, outputs, goal, reasons, True))
        j = J.join(plan, outputs, goal=goal, done_reasons=reasons)
        broken = {sid for sid, p in j.pieces.items() if not p.ok}
        if broken:  # what's left joins, which is most of the joiner's code on a task that fell back
            kept = {st["id"]: (None if "s%d" % (i + 1) in broken else outputs[st["id"]])
                    for i, st in enumerate(plan["steps"])}
            out.append((label + " without broken", plan, kept, goal, reasons, False))
        for i, st in enumerate(plan["steps"]):
            base = kept if broken else outputs
            if base.get(st["id"]) is None:
                continue
            out.append((label + " s%d failed" % (i + 1), plan, dict(base, **{st["id"]: None}), goal, reasons, False))
            out.append((label + " s%d library" % (i + 1), plan,
                        dict(base, **{st["id"]: {"output": outputs[st["id"]], "status": "library"}}), goal, reasons, False))
    return out


def alone_jobs(tasks):
    """Each good Blender piece of the stored tasks, as it runs alone."""
    out, seen = [], set()
    for label, plan, outputs, goal, reasons, cut in tasks:
        if " " in label:
            continue
        for i, st in enumerate(plan["steps"]):
            text = outputs.get(st["id"])
            kw = {"mode": planinfo.step_mode(plan, i, goal), "sid": "s%d" % (i + 1), "reject_cut": False, "max_tokens": None}
            if isinstance(text, str) and kw["mode"] == "blender" and text not in seen:
                seen.add(text)
                if V.validate_piece(text, **kw).tree is not None:
                    out.append(("%s s%d" % (label, i + 1), kw, text, False, "ctx", []))
                    out.append(("%s s%d keep" % (label, i + 1), kw, text, True, "ctx1", ["s9"]))
    return out


def recorded_calls():
    """Every call the contract's tests make, recorded by running them against shims. Input only: each is run afresh
    below, on both sides."""
    calls = collections.defaultdict(list)
    real = {"validate": V.validate_piece, "join": J.join, "merge": J.merge_python, "alone": J.alone_script,
            "uses": J.uses_names, "slug": J.slug, "locate": L.locate_check}

    def validate_piece(text, mode, sid="s1", deps=(), lone=False, step=None, done_reason="", reject_cut=True,
                       max_tokens=V.MAX_PIECE_TOKENS):
        kw = {"sid": sid, "deps": list(deps), "lone": lone, "step": step, "done_reason": done_reason,
              "reject_cut": reject_cut, "max_tokens": max_tokens}
        p = real["validate"](text, mode, **kw)  # a call that raises isn't one to compare
        calls["validate"].append(("fixture", dict(copy.deepcopy(kw), mode=mode), text))
        return p

    def join(plan, outputs, goal="", done_reasons=None, reject_cut=False, editor=None):
        calls["join"].append(("fixture", copy.deepcopy(plan), copy.deepcopy(outputs), goal, copy.deepcopy(done_reasons or {}),
                              reject_cut))
        return real["join"](plan, outputs, goal=goal, done_reasons=done_reasons, reject_cut=reject_cut, editor=editor)

    def merge_python(base, parts):
        calls["merge"].append((base, [list(p) for p in parts]))
        return real["merge"](base, parts)

    def alone_script(piece, keep_ctx=False, ctx_name="ctx", also=()):
        if not piece.library:
            calls["alone"].append(("fixture", {"mode": piece.mode, "sid": piece.sid, "reject_cut": False, "max_tokens": None},
                                   piece.text, keep_ctx, ctx_name, list(also)))
        return real["alone"](piece, keep_ctx, ctx_name, also)

    def uses_names(chunk):
        calls["uses"].append(chunk)
        return real["uses"](chunk)

    def slug(title):
        calls["slug"].append(title)
        return real["slug"](title)

    def locate_check(check, lm, script=None):
        calls["locate"].append((copy.deepcopy(check), lm.to_dict(), script))
        return real["locate"](check, lm, script)

    V.validate_piece, J.validate_piece = validate_piece, validate_piece
    J.join, J.merge_python, J.alone_script = join, merge_python, alone_script
    J.uses_names, J.slug, L.locate_check = uses_names, slug, locate_check
    try:
        import importlib
        import io
        import unittest
        suite = unittest.TestSuite()
        for name in ("tests.test_contract_validate", "tests.test_contract_join", "tests.test_contract_prompt"):
            suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(name)))
        unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    finally:
        V.validate_piece, J.validate_piece = real["validate"], real["validate"]
        J.join, J.merge_python, J.alone_script = real["join"], real["merge"], real["alone"]
        J.uses_names, J.slug, L.locate_check = real["uses"], real["slug"], real["locate"]
    return calls


def piece_job(kw, text):
    """A validate_piece call as a --hydra-assemble job: Go's input spells no limit 0."""
    job = dict(kw, text=text)
    if job.get("max_tokens", 1) is None:
        job["max_tokens"] = 0
    if job.get("step") is None:
        job.pop("step", None)
    return job


def known_codes():
    """Every issue and seam code the prototype can give, read from its source."""
    out = set()
    for path, rx in ((V.__file__, r'_err\(p, "(\w+)"|code = "(\w+)" if .* else "(\w+)"|Issue\("\w+", "(\w+)"'), (J.__file__, r'_seam\("(\w+)"')):
        with open(path, encoding="utf-8") as f:
            for m in re.finditer(rx, f.read()):
                out.update(g for g in m.groups() if g)
    return out


class Report:
    def __init__(self):
        self.lines, self.failed = [], 0

    def say(self, line=""):
        self.lines.append(line)
        print(line, flush=True)

    def group(self, name, n, diffs, note=""):
        """One line for a group; diffs are (label, difference)."""
        self.failed += len(diffs)
        self.say("%-22s %7d cases, %d differ.%s" % (name, n, len(diffs), " " + note if note else ""))
        for label, d in diffs[:MAX_SHOWN]:
            self.say("  %s: %s" % (label, d[:600]))
        if len(diffs) > MAX_SHOWN:
            self.say("  and %d more" % (len(diffs) - MAX_SHOWN))


SEEN_CODES = set()  # every code a compared verdict or join had, on both sides


def check_validate(binary, jobs):
    """Compare verdicts. jobs: (label, kwargs, text). Returns the differences."""
    diffs = []
    for batch in batched(jobs, lambda j: len(j[2])):
        got = go_call(binary, {"validate": [piece_job(kw, text) for _, kw, text in batch]})["validate"]
        for (label, kw, text), g in zip(batch, got):
            args = {k: v for k, v in kw.items() if k != "mode"}
            want = piece_dict(V.validate_piece(text, kw["mode"], **args))
            SEEN_CODES.update(i["code"] for i in want["issues"])
            d = first_difference(want, g)
            if d:
                diffs.append((label, d))
    return diffs


def join_one(binary, job):
    label, plan, outputs, goal, reasons, cut = job
    got = go_call(binary, {"plan": plan, "outputs": outputs, "goal": goal, "done_reasons": reasons, "reject_cut": cut})
    want = join_dict(J.join(clean_plan(plan), outputs, goal=goal, done_reasons=reasons, reject_cut=cut))
    SEEN_CODES.update(s["code"] for s in want["seams"])
    SEEN_CODES.update(i["code"] for p in want["pieces"] for i in p["issues"])
    return label, first_difference(want, got), bool(want["script"]), want["fallback"]


def check_join(binary, jobs):
    diffs, scripts, fallbacks = [], 0, 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, (os.cpu_count() or 4) * 2)) as pool:
        for label, d, script, fallback in pool.map(lambda j: join_one(binary, j), jobs):
            scripts += script
            fallbacks += fallback
            if d:
                diffs.append((label, d))
    return diffs, scripts, fallbacks


def check_alone(binary, jobs):
    diffs = []
    for batch in batched(jobs, lambda j: len(j[2])):
        payload = [dict(piece_job(kw, text), keep_ctx=keep, ctx_name=name, also=also) for _, kw, text, keep, name, also in batch]
        got = go_call(binary, {"alone": payload})["alone"]
        for (label, kw, text, keep, name, also), g in zip(batch, got):
            args = {k: v for k, v in kw.items() if k != "mode"}
            d = first_difference(J.alone_script(V.validate_piece(text, kw["mode"], **args), keep, name, also), g)
            if d:
                diffs.append((label, d))
    return diffs


def line_map_jobs(tasks):
    """Each line of each joined script, read as a crash there, and one in a script that isn't the map's."""
    jobs = []
    for job in tasks:
        label, plan, outputs, goal, reasons, cut = job
        if " " not in label:
            j = J.join(plan, outputs, goal=goal, done_reasons=reasons)
            if j.script:
                lines = j.script.split("\n")
                for n, line in enumerate(lines):
                    jobs.append(({"outcome": "failed" if n % 5 else "unsure", "line": n + 1, "error": "E", "source": line, "runner": "Blender"},
                                 j.linemap.to_dict(), j.script if n % 3 else None))
                jobs.append(({"outcome": "failed", "line": len(lines) + 9, "source": "x"}, j.linemap.to_dict(), j.script))
    return jobs


def check_helpers(binary, calls):
    """merge_python, uses_names, slug and locate_check, on what the tests call them with and more."""
    diffs = []
    merges = calls["merge"]
    if merges:
        for (base, parts), g in zip(merges, go_call(binary, {"merge": [{"base": b, "parts": p} for b, p in merges]})["merge"]):
            d = first_difference(J.merge_python(base, parts), g)
            if d:
                diffs.append(("merge", d))
    uses = calls["uses"]
    if uses:
        for s, g in zip(uses, go_call(binary, {"uses_names": uses})["uses_names"]):
            d = first_difference(J.uses_names(s), g)
            if d:
                diffs.append(("uses %r" % s[:60], d))
    slugs = calls["slug"]
    if slugs:
        for s, g in zip(slugs, go_call(binary, {"slug": slugs})["slug"]):
            d = first_difference(J.slug(s), g)
            if d:
                diffs.append(("slug %r" % s[:60], d))
    jobs = calls["locate"]
    if jobs:
        keys = ("line", "step", "title", "part", "function", "piece_line", "repair", "outcome", "error", "source", "runner",
                "definite", "source_matches")
        for batch in batched(jobs, lambda j: len(j[2] or "") // 40 + 300):
            payload = [{"linemap": lm, "check": check.get("check", check), "script": script} for check, lm, script in batch]
            for (check, lm, script), g in zip(batch, go_call(binary, {"locate": payload})["locate"]):
                want = L.locate_check(check, L.LineMap.from_dict(lm), script)
                want = {k: want[k] for k in keys if want.get(k) not in (None, "")}
                got = {k: g[k] for k in keys if g.get(k) not in (None, "")}
                if not check.get("check", check).get("line"):  # no line: Go has nothing to say about it
                    want.pop("line", None), got.pop("line", None)
                d = first_difference(want, got)
                if d:
                    diffs.append(("locate", d))
    return diffs


# ---------------------------------------------------------------- random text

_SPACES = [" ", " ", " ", "  ", "\t", "\u00a0", "\u2003", "\u3000", "\x1c", "\x85", "\u202f", ""]
_WORDS = ["none", "None.", "n/a", "-", "nothing", "no", "not yet", "nothing from s1", "s1", "s2", "s3", "s12", "s9", "s123",
          "s\u0663", "table", "chimera_table", "ctx[\"objects\"][\"table\"]", "Store.all", "a/b.py", "`x.y`", "'a b'", "\"q\"",
          "foo()", "CamelCase", "\u00e9t\u00e9_x", "\u00b2x_y", "x.y.z", "x..y", ".hidden", "v1.2", "data.csv", "a-b.c", "_x_",
          "TODO", "todo", "FIXME", "placeholder", "placeholders", "implement this", "implement me", "# ...", "...", "as an AI",
          "language model", "other worker", "the workers", "sub-agent", "subagents", "http://a.b/c", "HTTPS://x", "doi: 10.1/x",
          "10.1234/abc", "10.123/abc", "(unverified)", "<|start|>", "<|end|>", "assistantfinal", "<think>", "</think>", "<|x|>"]
_LANGS = ["", "python", "py", "python3", "bpy", "x.py", "text", "txt", "plain", "plaintext", "yaml", "yml", "json", "js", "handoff",
          "{.python}", ".py", "PYTHON", "python title=x"]
_FILE_LINES = ["File: a.py", "File: a.py (part)", "File: src/b.py", "**File: a.py**", "**File:** a.py", "File: `a.py`", "### File: a.py",
               "> File: a.py", "- File: a.py", "File: a.py:", "File: a.py (Part)", "File: a.py extra", "File: a.py**", "File:a.py", "File: *a.py*",
               "`File: a.py`", "file: a.py", "File:", "File: a b.py", "\u00a0File:\u00a0a.py\u00a0(part)\u00a0", "__File:__ a.py"]
_CODE = ["import bpy\nSETTINGS_s1 = {\"a\": 1}\n\ndef build_s1(ctx):\n    ctx[\"objects\"][\"table\"] = 1\n\n"
         "if __name__ == \"__main__\":\n    build_s1({})", "import os\n\ndef main():\n    print(os.name)", "def f():\n    return 1",
         "x = 1\ny = f()", "from a import b\n\nclass C:\n    pass", "if __name__ == \"__main__\":\n    main()", "print('hi')",
         "import bpy\nfor o in bpy.data.objects:\n    bpy.data.objects.remove(o)", "def broken(:\n    pass", "# TODO\npass", "..."]
_CODE += ["import bpy\nSETTINGS_s1 = {}\n\ndef build_s1(ctx, more):\n    pass\n\nif __name__ == \"__main__\":\n    build_s1({})",
          "from bpy import *\nSETTINGS_s1 = {}\n\ndef build_s1(ctx):\n    pass\n\nif __name__ == \"__main__\":\n    build_s1({})",
          "SETTINGS_s1 = {}\n\ndef build_s1(ctx):\n    pass\n\nif __name__ == \"__main__\":\n    build_s1({})\nif __name__ == \"__main__\":\n    pass",
          "import bpy\nSETTINGS_s1 = {}\n\ndef build_s1(ctx, *, more=1):\n    pass\n\nif __name__ == \"__main__\":\n    build_s1({})", "x = 1\x00"]
_HEADINGS = ["## Title", "# Title", "## Other", "### Title", "##Title", "## \u00c9t\u00e9", "## Notes (draft)", "## The plan!", "Title"]


_STUBS = ["# TODO: the rest", "# FIXME later", "# a placeholder", "# implement this", "# Implement Me", "pass  # ...", "# ...", "    ...",
          "...", "# nothing here", "# TODOS", "# unplaceholdered", "x = '#  ...'"]


def with_stub(rng, code):
    lines = code.split("\n")
    lines.insert(rng.randrange(len(lines) + 1), rng.choice(_STUBS))
    return "\n".join(lines)


def random_reply(rng):
    parts = []
    for _ in range(rng.randrange(1, 6)):
        how = rng.randrange(8)
        if how == 0:
            parts.append(rng.choice(_HEADINGS))
        elif how == 1:
            parts.append(rng.choice(_FILE_LINES))
        elif how == 2:
            indent = rng.choice(["", "", "", " ", "   ", "    "])
            fence = rng.choice(["```", "```", "```", "~~~", "````"])
            code = rng.choice(_CODE)
            code = with_stub(rng, code) if rng.random() < 0.3 else code
            parts.append("%s%s%s\n%s\n%s" % (indent, fence, rng.choice(_LANGS), code, rng.choice([indent + fence, fence, ""])))
        elif how == 3:
            parts.append(random_handoff(rng))
        else:
            parts.append(rng.choice(_SPACES).join(rng.choice(_WORDS) for _ in range(rng.randrange(1, 6))))
    return rng.choice(["\n", "\n\n", "\r\n"]).join(parts) + rng.choice(["", "\n", "\n\n"])


def random_handoff(rng):
    lines = []
    for key in rng.sample(["provides", "uses", "assumed", "Uses", "PROVIDES", "assumed", "notes"], rng.randrange(1, 5)):
        lines.append("%s%s%s:%s%s%s" % (rng.choice(_SPACES), key, rng.choice(_SPACES), rng.choice(_SPACES),
                                        " ".join(rng.choice(_WORDS) for _ in range(rng.randrange(0, 4))), rng.choice(_SPACES)))
    label = rng.choice(["", "", "handoff\n", "Handoff:\n", "**Handoff**\n", "### Handoff\n", "`handoff`\n", "hand off\n"])
    fence = rng.choice(["```handoff\n%s\n```", "```handoff\n%s\n```", "```\n%s\n```", "```text\n%s\n```", "```yaml\n%s", "```handoff\n%s", "%s"])
    return label + fence % "\n".join(lines)


def random_replies(n):
    rng = random.Random(FUZZ_SEED + 2)
    out = []
    for i in range(n):
        sid = rng.choice(["s1", "s2", "s3"])
        step = {"title": rng.choice(["Title", "The plan", "\u00c9t\u00e9", ""]), "kind": rng.choice(["research", "writing", "general"]),
                "instructions": rng.choice(["Write the notes.", "Under the heading Notes (draft)", ""])}
        kw = {"mode": rng.choice(["blender", "python-script", "files", "section"]), "sid": sid,
              "deps": rng.sample(["s1", "s2"], rng.randrange(0, 3)), "lone": rng.random() < 0.15, "step": step,
              "done_reason": rng.choice(["", "stop", "length"]), "reject_cut": rng.random() < 0.5,
              "max_tokens": rng.choice([None, 3500, 40])}
        out.append(("random %d" % i, kw, random_reply(rng)))
    return out


_SOURCES = ["bpy.data.objects", "bpy.data.meshes", "bpy.data.materials", "bpy.data.lights", "bpy.context.scene.objects", "scene.objects", "objs",
            "bpy.context.scene.collection.objects", "bpy.context.collection.objects", "bpy.context.view_layer.objects", "ctx[\"scene\"].objects",
            "ctx.scene.objects", "ctx[\"scene\"].collection.objects", "ctx[\"collection\"].objects", "ctx.collection.objects", "my_list"]
_ITERS = ["%s", "list(%s)", "tuple(%s)", "sorted(%s)", "reversed(%s)", "%s.values()", "%s[:]", "%s[1:]", "enumerate(%s)", "list(%s.values())", "set(%s)", "%s.keys()"]
_TESTS = ["o.name != 'x'", "o.name == 'x'", "not o.name.startswith('y')", "o.name.startswith('y')", "not (o.name == 'x')", "not (o is y)", "not (o in y)",
          "not (o.name != 'x')", "o not in keep", "o in keep", "o is not cam", "o is cam", "not not o.x", "not o.users", "o.users == 0", "o.users",
          "o.a != 1 and o.b != 2", "o.a != 1 and o.b == 2", "o.a != 1 or o.b != 2", "not (o.a or o.b)", "not (o.a and o.b)", "not f(o)", "f(o)", "o.a < 1", "not o.a < 1", "not x[0]"]
_REMOVES = ["bpy.data.objects.remove(o)", "bpy.data.meshes.remove(o, do_unlink=True)", "objs.remove(o)", "ctx[\"collection\"].objects.unlink(o)", "x.remove(o)", "x.y.remove(o)",
            "bpy.data.objects.remove(p)", "remove(o)", "bpy.data.objects.remove(o.data)", "bpy.ops.object.delete()"]
_WHOLE = ["bpy.data.objects.clear()", "objs.clear()", "ctx[\"scene\"].collection.objects.clear()", "bpy.data.batch_remove(ids=x)", "bpy.ops.object.select_all(action='SELECT')",
          "bpy.ops.object.select_all(action='DESELECT')", "bpy.ops.object.select_all(action=x)", "bpy.ops.object.delete()", "bpy.ops.wm.save_mainfile()", "sys.exit(0)", "quit()", "os._exit(1)"]


def random_loop(rng):
    """A build function that removes things, as the wipe checks tell them apart."""
    src = rng.choice(_SOURCES)
    var = rng.choice(["o", "o", "o", "p"])
    target = "i, " + var if rng.random() < 0.3 else var
    head = "for %s in %s:" % (target, rng.choice(_ITERS) % src)
    body, indent = [], "        "
    for _ in range(rng.randrange(0, 3)):
        how = rng.randrange(4)
        if how == 0:
            body += [indent + "if %s:" % rng.choice(_TESTS), indent + "    " + rng.choice(["continue", "break", "pass"])]
        elif how == 1:
            body += [indent + "if %s:" % rng.choice(_TESTS)]
            indent += "    "
        elif how == 2:
            body += [indent + "if %s:" % rng.choice(_TESTS), indent + "    pass", indent + "else:"]
            indent += "    "
        else:
            body += [indent + rng.choice(["try:", "with x:", "while y:"])]
            indent += "    "
    body.append(indent + rng.choice(_REMOVES))
    if indent.endswith("    ") and "try:" in "\n".join(body):
        body += [b for b in ["    " * (len(indent) // 4 - 1) + "except E:", indent + rng.choice(_REMOVES)]][:2] if body[-2].strip() == "try:" else []
    lines = ["    objs = bpy.data.objects", "    " + head] + body
    if rng.random() < 0.3:
        lines.append("    " + rng.choice(_WHOLE))
    if rng.random() < 0.3:
        lines.insert(0, "    " + rng.choice(_WHOLE))
    return "\n".join(lines)


def random_wipes(n):
    rng = random.Random(FUZZ_SEED + 7)
    out = []
    for i in range(n):
        code = "import bpy\nSETTINGS_s1 = {}\n\ndef build_s1(ctx):\n%s\n\nif __name__ == \"__main__\":\n    build_s1({})" % random_loop(rng)
        out.append(("wipe %d" % i, {"mode": "blender", "sid": "s1"}, "```python\n%s\n```\n\n```handoff\nprovides: x\nuses: none\nassumed: none\n```\n" % code))
    return out


_VALUES = ["1", "-1", "+1.5", "1+2j", "-1-2j", "1.5+2j", "2j+1", "1+2", "1j-1j", "-True", "True", "None", "...", "'a'", "b'a'", "f'a'", "~1", "not 1", "()", "(1,)", "[1]",
           "[f()]", "{}", "{1}", "{[1]}", "{(1, [2])}", "{(1, 2)}", "{[1]: 2}", "{(1, 2): [3]}", "{1: f()}", "{**a}", "set()", "set(x)", "frozenset()", "dict()", "x", "x.y", "f()",
           "1 if x else 2", "[1, [2, {3: 4}]]", "{'a': (1, -2.5)}", "lambda: 1", "-(1)", "--1", "- 1", "1 + -2j", "-1 + 2j", "+1 - 2j", "(1 + 2j) + 3j"]


def random_literals(n):
    rng = random.Random(FUZZ_SEED + 8)
    out = []
    for i in range(n):
        lines = ["%s = %s" % (rng.choice(["A", "B", "C: int", "D, E", "F.g", "h[0]"]), rng.choice(_VALUES)) for _ in range(rng.randrange(1, 4))]
        code = "\n".join(lines) + "\n\ndef main():\n    pass"
        out.append(("literal %d" % i, {"mode": "python-script", "sid": "s1"}, "```python\n%s\n```\n\n```handoff\nprovides: x\nuses: none\nassumed: none\n```\n" % code))
    return out


def random_uses(n):
    rng = random.Random(FUZZ_SEED + 3)
    return [rng.choice(_SPACES + [", ", "; ", " from "]).join(rng.choice(_WORDS) for _ in range(rng.randrange(1, 7))) for _ in range(n)]


def random_titles(n):
    rng = random.Random(FUZZ_SEED + 4)
    letters = ["A", "b", " ", "-", "_", "\u00e9", "\u00df", "\u4e2d", "9", "!", "\t"]
    return ["".join(rng.choice(letters) for _ in range(rng.randrange(0, 60))) for _ in range(n)]


_PY_PARTS = ["import os", "import os as o", "import a.b", "from a import b", "from .a import b", "from . import c", "from .. import d",
             "from pkg.mod import thing", "from pkg import f", "from pkg import nothing", "import pkg.mod", "import pkg.none", "from a import *", "def f():\n    return 1", "def g(x):\n    return x", "class K:\n    pass",
             "X = 1", "\"\"\"A docstring.\"\"\"", "if __name__ == \"__main__\":\n    f()", "print('runs')", "def broken(:\n    pass"]
_PATHS = ["a.py", "src/a.py", "src/pkg/mod.py", "pkg/__init__.py", "mod.py", "b.txt", "web/x.js", "Makefile"]


def random_files_plan(rng, i):
    """A plan of files or of sections, with its replies."""
    n = rng.randrange(1, 4)
    sections = rng.random() < 0.3
    steps = [{"id": "p%d" % k, "title": "Part %d" % k, "kind": "writing" if sections else "code",
              "instructions": "Write part %d of src/a.py." % k, "depends_on": ["p%d" % j for j in range(k) if rng.random() < 0.5]}
             for k in range(n)]
    plan = clean_plan({"title": "Plan %d: t\u00e9st!" % i, "kind": "writing" if sections else "code", "summary": "src/a.py", "steps": steps})
    outputs = {}
    for k, st in enumerate(plan["steps"]):
        hand = "```handoff\nprovides: %s\nuses: %s\nassumed: %s\n```\n" % (
            rng.choice(_WORDS), rng.choice(_WORDS + ["s1 thing", "s1's f()", "s2 g"]), rng.choice(["none", "a guess"]))
        if sections:
            outputs[st["id"]] = "%s\n\nSome text about %s.\n\n%s" % (
                rng.choice(["## Part %d" % k, "## Other", "# Top", "## Part %d" % k]), rng.choice(_WORDS), hand)
            continue
        blocks = []
        for _ in range(rng.randrange(1, 4)):
            path = rng.choice(_PATHS)
            body = "\n\n".join(rng.choice(_PY_PARTS) for _ in range(rng.randrange(1, 5)))
            lang = "python" if path.endswith(".py") else rng.choice(["text", "js", ""])
            blocks.append("File: %s%s\n```%s\n%s\n```" % (path, rng.choice(["", " (part)"]), lang, body))
        outputs[st["id"]] = "\n\n".join(blocks) + "\n\n" + hand
    return ("random plan %d" % i, plan, outputs, "", {}, False)


def random_plans(n):
    rng = random.Random(FUZZ_SEED + 5)
    return [random_files_plan(rng, i) for i in range(n)]


def seam_plans():
    """The seams nothing else reaches: two steps binding one name to different things, and statements that share a
    line, which the joiner cuts apart (a = (1,\\n 2); b = 3)."""
    def plan(kind, words, n=2):
        return clean_plan({"title": "Seams", "kind": kind, "summary": words, "steps": [
            {"id": "p%d" % k, "title": "Part %d" % k, "kind": kind, "instructions": "Do it. " + words} for k in range(n)]})

    def piece(body):
        return "```python\n%s\n```\n\n```handoff\nprovides: x\nuses: none\nassumed: none\n```\n" % body

    def files(path, tail, body):
        return "File: %s%s\n```python\n%s\n```\n\n```handoff\nprovides: x\nuses: none\nassumed: none\n```\n" % (path, tail, body)

    def scripts(provides, code, uses):
        hand = "```handoff\nprovides: %s\nuses: %s\nassumed: none\n```\n"
        return {"p0": "```python\n%s\n```\n\n" % code + hand % (provides, "none"),
                "p1": "```python\ndef main():\n    pass\n```\n\n" + hand % ("main", uses)}

    shared = "a = (1,\n 2); b = 3\n\ndef main():\n    pass"
    twice = "File: x.py\n```python\nX = 1\n```\n\nFile: x.py\n```python\nY = 1\n```\n\n```handoff\nprovides: x\nuses: none\nassumed: none\n```\n"
    return [("seam: import conflict", plan("code", "A tool."), {"p0": piece("from a import b\n\ndef main():\n    pass"),
                                                               "p1": piece("from c import b\n\ndef f():\n    pass")}, "", {}, False),
            ("seam: shared line", plan("code", "A tool."), {"p0": piece(shared), "p1": piece("def f():\n    pass")}, "", {}, False),
            ("seam: a line shared with a dropped docstring", plan("code", "A tool."), {"p0": piece("\"\"\"a\nb\"\"\"; c = 3\n\ndef main():\n    pass"), "p1": piece("def f():\n    pass")}, "", {}, False),
            ("seam: shared line in a part", plan("code", "Write src/x.py."), {"p0": files("src/x.py", " (part)", "a = (1,\n 2); b = 3"),
                                                                              "p1": files("src/x.py", " (part)", "c = 1")}, "", {}, False),
            ("seam: a file twice", plan("code", "Write x.py.", 1), {"p0": twice}, "", {}, False),
            ("seam: a part in a file with no imports", plan("code", "Write src/x.py."), {
                "p0": files("src/x.py", "", "\"\"\"Doc.\"\"\"\n\nX = 1"), "p1": files("src/x.py", " (part)", "import os\n\nY = 2")}, "", {}, False),
            ("seam: a path inside a longer one", plan("code", "A tool."), scripts("xa/b.py", "X = 1", "a/b.py from s1"), "", {}, False),
            ("seam: a file name inside a longer one", plan("code", "A tool."), scripts("xmy-data.csv", "X = 1", "`my-data.csv` from s1"), "", {}, False),
            ("seam: a name inside a longer one", plan("code", "A tool."), scripts("table_top1", "X = 1", "table_top from s1"), "", {}, False),
            ("seam: a name with an accent next to it", plan("code", "A tool."), scripts("\u00e9table_top", "X = 1", "table_top from s1"), "", {}, False),
            ("seam: odd space at the end of a section", plan("writing", "Notes.", 1), {"p0": "## Part 0\n\nText\x1c"}, "", {}, False),
            ("seam: a library entry that won't wrap", plan("blender", "A scene."), {
                "p0": {"output": "```python\nimport os; x = (1,\n 2)\n```", "status": "library"}, "p1": None}, "", {}, False),
            ("seam: a package", plan("code", "Write pkg/__init__.py."), {
                "p0": files("pkg/__init__.py", "", "def f():\n    pass"), "p1": files("app.py", "", "from pkg import f, g\nimport pkg.mod\nimport pkg.other")}, "", {}, False)]


def uses_variants(tasks):
    """The stored tasks with their uses lines swapped for random ones, for the seams they lead to."""
    rng = random.Random(FUZZ_SEED + 6)
    out = []
    for label, plan, outputs, goal, reasons, cut in tasks:
        if " " in label:
            continue
        new = {}
        for k, v in outputs.items():
            if isinstance(v, str):
                words = " ".join(rng.choice(["s1", "s2", "s3", "s1's", "from s2"] + _WORDS) for _ in range(rng.randrange(1, 6)))
                v = "\n".join(("uses: " + words) if l.startswith("uses:") else l for l in v.split("\n"))
            new[k] = v
        out.append((label + " other uses", plan, new, goal, reasons, False))
    return out


# ---------------------------------------------------------------- reader against ast

def real_python_files(roots):
    out = []
    for root in roots:
        for d, _, names in os.walk(root):
            out += [os.path.join(d, n) for n in names if n.endswith(".py")]
    return sorted(out)


def compare_scan(src, g, seen):
    """One source, Python's verdict against Go's. Fills seen, and gives a difference that fails the run, if any."""
    p = scan_python(src)
    if p["ok"] and not g["ok"]:
        seen["go rejected what Python accepts"] += 1
        return "Go says %r at line %s; Python accepts it" % (g.get("msg"), g.get("line"))
    if not p["ok"] and g["ok"]:
        seen["a syntax error Go doesn't see"] += 1
        seen["  unseen: " + p["msg"].split(" (detected")[0][:70]] += 1
        return ""
    if p["ok"]:
        if p["tree"] == g["tree"]:
            seen["same tree"] += 1
        elif "\\N{" in src:
            seen["same but for a \\N{name} Go leaves as written"] += 1
        else:
            nfkc = [t for t in (p["tree"], g["tree"]) if not t.isascii()]
            if len(nfkc) == 2:
                seen["same but for identifiers Python folds (NFKC)"] += 1
                return ""
            return first_difference(p["tree"], g["tree"])
        return ""
    if (p["line"], p["msg"]) == (g.get("line", 0), g.get("msg")):
        seen["same error"] += 1
    elif p["line"] == g.get("line", 0):
        seen["same line, other words"] += 1
        seen["  words: %s / %s" % (p["msg"][:50], (g.get("msg") or "")[:50])] += 1
    else:
        seen["another line"] += 1
        seen["  line: %s / %s" % (p["msg"][:50], (g.get("msg") or "")[:50])] += 1
    return ""


def check_sources(binary, sources, seen):
    """sources: (label, text). Returns the differences."""
    diffs = []
    for batch in batched(sources, lambda s: len(s[1])):
        got = go_call(binary, {"scan": [s for _, s in batch]})["scan"]
        for (label, src), g in zip(batch, got):
            d = compare_scan(src, g, seen)
            if d:
                diffs.append((label, d))
    return diffs


def check_syntax_cases(binary, seen):
    """The hand-picked sources, where Python's words have to match too, but for the few that are known not to."""
    diffs = []
    got = go_call(binary, {"scan": SYNTAX_CASES})["scan"]
    for src, g in zip(SYNTAX_CASES, got):
        d = compare_scan(src, g, seen)
        p = scan_python(src)
        if d:
            diffs.append(("case %r" % src[:40], d))
        elif src not in SYNTAX_EXCEPTIONS and p["ok"] != g["ok"]:
            diffs.append(("case %r" % src[:40], "Python says %s, Go sees nothing" % p.get("msg")))
        elif src not in SYNTAX_EXCEPTIONS and not p["ok"] and (p["line"], p["msg"]) != (g.get("line", 0), g.get("msg")):
            diffs.append(("case %r" % src[:40], "Python: %s %s / Go: %s %s" % (p["line"], p["msg"], g.get("line"), g.get("msg"))))
    return diffs


def read_sources(paths):
    out = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                s = f.read()
            s.encode("utf-8")
        except (UnicodeError, OSError):
            continue
        out.append((p, s))
    return out


# ---------------------------------------------------------------- fuzz

_JUNK = list("()[]{}:,;'\"\n\t #\\=+-*./@!<>%") + ["  ", "    ", "\n\n", "'''", '"""', "f'", "f\"", "in", "if", "else", "for",
                                                  "def ", "class ", "lambda ", "not ", "as ", "é", "—", "“", "0", "1_", "0x"]


def damage(rng, code):
    """One random mistake in code."""
    lines = code.split("\n")
    how = rng.randrange(9)
    if how == 0 and code:  # lose a character
        i = rng.randrange(len(code))
        return code[:i] + code[i + 1:]
    if how == 1 and code:  # add something
        i = rng.randrange(len(code))
        return code[:i] + rng.choice(_JUNK) + code[i:]
    if how == 2 and code:  # change a character
        i = rng.randrange(len(code))
        return code[:i] + rng.choice(_JUNK) + code[i + 1:]
    k = rng.randrange(len(lines))
    if how == 3:  # lose a line
        return "\n".join(lines[:k] + lines[k + 1:])
    if how == 4:  # a line twice
        return "\n".join(lines[:k] + [lines[k]] + lines[k:])
    if how == 5:  # indent wrong
        return "\n".join(lines[:k] + [rng.choice(["  ", "    ", "\t", " "]) + lines[k]] + lines[k + 1:])
    if how == 6:  # outdent wrong
        return "\n".join(lines[:k] + [lines[k][rng.randrange(1, 5):]] + lines[k + 1:])
    if how == 7:  # stops short
        i = rng.randrange(len(code) + 1)
        return code[:i]
    j = rng.randrange(len(lines))  # two lines swapped
    lines[k], lines[j] = lines[j], lines[k]
    return "\n".join(lines)


def fuzz_sources(codes, n):
    """n damaged scripts: one to three mistakes each."""
    rng = random.Random(FUZZ_SEED)
    out = []
    for i in range(n):
        code = rng.choice(codes)
        if len(code) > 6000:  # the mistake's the point, not the size
            at = rng.randrange(len(code) - 6000)
            at = code.rfind("\n", 0, at) + 1
            code = code[at:at + 6000]
        for _ in range(rng.choice((1, 1, 1, 2, 3))):
            code = damage(rng, code)
        out.append(("fuzz %d" % i, code))
    return out


def fuzz_replies(jobs, n):
    """n damaged replies, in the mode and with the dependencies they ran with."""
    rng = random.Random(FUZZ_SEED + 1)
    out = []
    for i in range(n):
        label, kw, text = rng.choice(jobs)
        for _ in range(rng.choice((1, 1, 2, 3))):
            text = damage(rng, text)
        out.append(("%s damaged %d" % (label, i), kw, text))
    return out


def check_fuzz_replies(binary, jobs, seen):
    """Whole verdicts on damaged replies. A difference only counts when Python found the code parses, or the reader
    and Python agree it doesn't: otherwise it's the unseen syntax error from the fuzz above, and it is counted there."""
    diffs = []
    for batch in batched(jobs, lambda j: len(j[2])):
        got = go_call(binary, {"validate": [piece_job(kw, text) for _, kw, text in batch]})["validate"]
        for (label, kw, text), g in zip(batch, got):
            args = {k: v for k, v in kw.items() if k != "mode"}
            want = piece_dict(V.validate_piece(text, kw["mode"], **args))
            d = first_difference(want, g)
            if not d:
                seen["same verdict"] += 1
                continue
            has = lambda v: [i for i in v["issues"] if i["code"] == "syntax_error"]  # noqa: E731
            if has(want) and not has(g):
                seen["a syntax error Go doesn't see"] += 1
            elif has(want) and has(g) and [(i["code"], i["level"]) for i in want["issues"]] == [(i["code"], i["level"]) for i in g["issues"]]:
                seen["same codes, other words on a syntax error"] += 1
            elif has(g) and not has(want):
                seen["go rejected what Python accepts"] += 1
                diffs.append((label, d))
            else:
                diffs.append((label, d))
    return diffs


# ---------------------------------------------------------------- main

def sample(items, n):
    if not n or len(items) <= n:
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def show_seen(rep, seen):
    for k, v in sorted(seen.items(), key=lambda kv: (kv[0].startswith("  "), -kv[1], kv[0])):
        if not k.startswith("  "):
            rep.say("    %6d  %s" % (v, k))
    for prefix in ("  unseen: ", "  words: ", "  line: "):
        top = sorted(((v, k) for k, v in seen.items() if k.startswith(prefix)), reverse=True)
        if top:
            rep.say("    most common %s" % prefix.strip())
        for v, k in top[:10]:
            rep.say("      %5d  %s" % (v, k[len(prefix):]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--chimera", default=os.environ.get("CHIMERA_BIN", ""))
    ap.add_argument("--out")
    ap.add_argument("--sample", type=int, default=0, help="at most this many replies and task joins (0: all of them)")
    ap.add_argument("--fuzz", type=int, default=20000, help="damaged scripts to read; a quarter as many damaged replies")
    ap.add_argument("--random", type=int, default=20000, help="seeded random replies and uses lines")
    ap.add_argument("--python", action="append", help="a folder of real .py files (repeatable; default: the standard "
                    "library's top level and Blender's scripts, if there's a Blender)")
    a = ap.parse_args(argv)
    if not a.chimera:
        print("needs --chimera or CHIMERA_BIN", file=sys.stderr)
        return 2
    rep = Report()
    calls = recorded_calls()
    replies = reply_jobs()
    tasks = task_jobs()
    rep.say("Replies: %d stored, tasks: %d stored." % (len(replies), sum(1 for _ in stored_tasks())))

    diffs = check_validate(a.chimera, sample(replies, a.sample))
    rep.group("replies", len(sample(replies, a.sample)), diffs)
    n = sample(tasks, a.sample)
    diffs, scripts, fallbacks = check_join(a.chimera, n)
    rep.group("task joins", len(n), diffs, "%d gave a script, %d fell back." % (scripts, fallbacks))
    alone = sample(alone_jobs(tasks), a.sample)
    rep.group("alone scripts", len(alone), check_alone(a.chimera, alone))
    rep.group("fixture verdicts", len(calls["validate"]), check_validate(a.chimera, calls["validate"]))
    diffs, scripts, fallbacks = check_join(a.chimera, calls["join"])
    rep.group("fixture joins", len(calls["join"]), diffs, "%d gave a script, %d fell back." % (scripts, fallbacks))
    rep.group("fixture alone", len(calls["alone"]), check_alone(a.chimera, calls["alone"]))
    n = sum(len(calls[k]) for k in ("merge", "uses", "slug", "locate"))
    rep.group("helpers", n, check_helpers(a.chimera, calls))

    count = a.random
    rep.group("random replies", count, check_validate(a.chimera, random_replies(count)))
    rep.group("random wipes", count // 2, check_validate(a.chimera, random_wipes(count // 2)))
    rep.group("random literals", count // 4, check_validate(a.chimera, random_literals(count // 4)))
    plans = random_plans(count // 4) + uses_variants(tasks) + seam_plans()
    diffs, scripts, fallbacks = check_join(a.chimera, plans)
    rep.group("random joins", len(plans), diffs, "%d gave a script, %d fell back." % (scripts, fallbacks))
    words = {"merge": [], "locate": [], "uses": random_uses(count), "slug": random_titles(count // 4)}
    rep.group("random words", count + count // 4, check_helpers(a.chimera, words))
    lines = sample(line_map_jobs(tasks), max(a.sample * 20, 0))
    rep.group("located lines", len(lines), check_helpers(a.chimera, {"merge": [], "uses": [], "slug": [], "locate": lines}))

    never = sorted(known_codes() - SEEN_CODES)
    rep.say("Issue and seam codes compared: %d of %d." % (len(known_codes()) - len(never), len(known_codes())))
    if never and not a.sample:
        rep.group("codes never compared", 0, [(c, "no case reaches it") for c in never])

    roots = a.python
    if roots:
        files = real_python_files(roots)
    else:
        std = os.path.dirname(os.__file__)
        files = sorted(glob.glob(os.path.join(std, "*.py")))
        for name in ("grammar", "patma", "fstring", "type_params", "type_aliases", "unpack_ex", "coroutines", "generators", "lambda", "string_literals"):
            files += glob.glob(os.path.join(std, "test", "test_%s.py" % name))
        files += real_python_files(glob.glob("/Applications/Blender*.app/Contents/Resources/*/scripts/startup"))
    seen = collections.Counter()
    diffs = check_sources(a.chimera, read_sources(files), seen)
    rep.group("python files", len(files), diffs)
    show_seen(rep, seen)
    seen = collections.Counter()
    diffs = check_syntax_cases(a.chimera, seen)
    rep.group("syntax cases", len(SYNTAX_CASES), diffs)
    show_seen(rep, seen)

    codes = sorted({V.validate_piece(t, "blender").code or "" for _, _, t in replies} - {""}) or ["x = 1\n"]
    seen = collections.Counter()
    fuzz = fuzz_sources(codes, a.fuzz)
    diffs = check_sources(a.chimera, fuzz, seen)
    rep.group("damaged scripts", len(fuzz), diffs)
    show_seen(rep, seen)
    seen = collections.Counter()
    damaged = fuzz_replies(replies, a.fuzz // 4)
    diffs = check_fuzz_replies(a.chimera, damaged, seen)
    rep.group("damaged replies", len(damaged), diffs)
    show_seen(rep, seen)

    rep.say()
    rep.say("%d differences in all." % rep.failed if rep.failed else "No differences. 0 differ.")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write("\n".join(rep.lines) + "\n")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
