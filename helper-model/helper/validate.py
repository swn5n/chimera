"""Validators for the three helper jobs. The data filter now, the scorer later.

    from helper.validate import validate_plan, validate_review, validate_gate
    r = validate_plan(reply_text)
    r.chimera_ok   # Chimera 0.6.1 would accept the reply (its own, lenient reading)
    r.effective    # what Chimera then does with it: the cleaned plan / the verdict / use
    r.valid        # strict: one JSON object, matches schemas/<job>.schema.json, no sanity errors
    r.issues       # Issue(level "error" | "warn", code, message)

"error" means the reply breaks the format or makes Chimera do something other than what the
reply says (a dropped dependency, a renamed step). "warn" is a quality heuristic. Training data
should have no errors; whether to also drop warnings is the filter's choice.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, List

from . import chimera_port as cp
from . import schema_check

KINDS = cp.KINDS


@dataclass
class Issue:
    level: str  # "error" or "warn"
    code: str
    message: str

    def to_dict(self):
        return {"level": self.level, "code": self.code, "message": self.message}


@dataclass
class Result:
    job: str
    chimera_ok: bool
    effective: Any
    obj: Any = None
    schema_ok: bool = False
    issues: List[Issue] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def errors(self):
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self):
        return [i for i in self.issues if i.level == "warn"]

    @property
    def valid(self):
        return self.schema_ok and not self.errors

    def to_dict(self):
        return {"job": self.job, "chimera_ok": self.chimera_ok, "valid": self.valid, "schema_ok": self.schema_ok,
                "effective": self.effective, "issues": [i.to_dict() for i in self.issues], "metrics": self.metrics}


_SCHEMAS = {}


def _schema(job):
    if job not in _SCHEMAS:
        _SCHEMAS[job] = schema_check.load(job)
    return _SCHEMAS[job]


class _DupKey(ValueError):
    pass


def _strict_pairs(pairs):
    keys = [k for k, _ in pairs]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        raise _DupKey("repeated key(s) " + ", ".join(json.dumps(k) for k in dup))
    return dict(pairs)


def _loads_strict(text):
    return json.loads(text, object_pairs_hook=_strict_pairs, parse_constant=cp.reject_constant)


def _strict_parse(text, issues):
    """The reply as exactly one JSON object: nothing around it, no repeated keys, no NaN."""
    t = cp.go_trim_space(text)
    try:
        return _loads_strict(t)
    except _DupKey as e:
        issues.append(Issue("error", "repeated_key", str(e)))
        return None
    except ValueError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if 0 <= start < end:
        try:
            obj = _loads_strict(t[start:end + 1])
        except _DupKey as e:
            issues.append(Issue("error", "repeated_key", str(e)))
            return None
        except ValueError:
            obj = None
        if obj is not None:
            issues.append(Issue("error", "extra_text", "text outside the JSON object (code fence or prose); "
                                                       "Chimera tolerates it, the target format doesn't"))
            return obj
    issues.append(Issue("error", "not_json", "the reply isn't a JSON object"))
    return None


def _check_schema(obj, job, issues):
    errs = schema_check.errors(obj, _schema(job))
    for path, kw, msg in errs:
        issues.append(Issue("error", "schema:" + kw, f"{path}: {msg}"))
    return not errs

# ---------------------------------------------------------------- planner

# Step titles that are the review/combine pass the prompt says happens automatically.
META_STEP = re.compile(r"^\s*(final\s+)?(review|combin|merg|assembl|integrat|compil|consolidat|proofread|"
                       r"quality[- ]check|qa\b|wrap[- ]?up|(put|bring) (it|everything|them) together)", re.I)


def _sentences(s):
    return max(1, len(re.findall(r"[.!?](\s|$)", s.strip())))


def validate_plan(text: str) -> Result:
    """A planner reply. effective is the plan as Chimera runs it (after cleanPlan), or None."""
    ok, decoded, _ = cp.extract_json(text, cp.PLAN_SPEC)
    chimera_ok = bool(ok and decoded["steps"])
    r = Result("planner", chimera_ok, cp.clean_plan(decoded) if chimera_ok else None)
    if not chimera_ok:
        why = "it doesn't decode into hydraPlan" if not ok else "it has no steps"
        r.issues.append(Issue("error", "chimera_rejects",
                              f"Chimera can't use this plan: {why} (the task fails: \"The planner didn't return a usable plan\")"))
    r.obj = _strict_parse(text, r.issues)
    if r.obj is not None:
        r.schema_ok = _check_schema(r.obj, "planner", r.issues)
        if isinstance(r.obj, dict):
            _plan_sanity(r.obj, r.issues)
    if r.effective:
        r.metrics = plan_metrics(r.effective)
    return r


def _plan_sanity(p, issues):
    def add(level, code, msg):
        issues.append(Issue(level, code, msg))

    for key in ("title", "summary"):
        v = p.get(key)
        if isinstance(v, str) and v and not v.strip():
            add("error", "blank_" + key, f"{key} is only whitespace")
    if isinstance(p.get("title"), str) and len(p["title"]) > 60:
        add("warn", "title_long", "the project title is over 60 characters; the prompt asks for a short name")
    if isinstance(p.get("summary"), str) and p["summary"].strip() and _sentences(p["summary"]) > 4:
        add("warn", "summary_long", "the summary is over 4 sentences; the prompt asks for 2 to 3")
    steps = p.get("steps")
    if not isinstance(steps, list):
        return
    n = len(steps)
    if n == 1:
        add("error", "step_count", "1 step: Chimera runs it alone and skips the combine step; the prompt asks for 2 to 7")
    elif n > 7:
        add("error", "step_count", f"{n} steps: the prompt asks for 2 to 7" + ("; Chimera keeps only the first 8" if n > 8 else ""))
    ids = [s.get("id") if isinstance(s, dict) and isinstance(s.get("id"), str) else None for s in steps]
    first = {}
    for i, sid in enumerate(ids):
        if sid is None or not sid.strip():
            add("error", "id_missing", f"step {i + 1} has no id; Chimera calls it s{i + 1}")
        elif sid in first:
            add("error", "id_duplicate", f"step {i + 1} reuses id {sid!r}; Chimera renames it s{i + 1}")
        else:
            first[sid] = i
    if all(ids) and len(first) == n and ids != [f"s{i + 1}" for i in range(n)]:
        add("warn", "id_order", "ids are " + ", ".join(ids) + f", not s1..s{n} in order")
    graph = {i: set() for i in range(n)}
    for i, s in enumerate(steps):
        deps = s.get("depends_on") if isinstance(s, dict) else None
        if not isinstance(deps, list):
            continue
        me = ids[i] or f"step {i + 1}"
        for d in deps:
            if not isinstance(d, str):
                continue
            if d == ids[i]:
                add("error", "dep_self", f"{me} depends on itself")
            elif d not in first:
                add("error", "dep_unknown", f"{me} depends on {d!r}, which isn't a step; Chimera drops it")
            else:
                j = first[d]
                graph[i].add(j)
                if j > i:
                    add("error", "dep_forward", f"{me} depends on a later step ({d}); Chimera drops forward "
                                                "dependencies, so it would run without that input")
    cycle = _find_cycle(graph)
    if cycle:
        add("error", "dep_cycle", "dependency cycle: " + " -> ".join(ids[i] or f"step {i + 1}" for i in cycle))
    titles = []
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            continue
        t, ins = s.get("title"), s.get("instructions")
        if isinstance(t, str):
            if t and not t.strip():
                add("error", "blank_title", f"step {i + 1}'s title is only whitespace; Chimera calls it \"Step {i + 1}\"")
            elif len(t) > 80:
                add("warn", "step_title_long", f"step {i + 1}'s title is over 80 characters")
            if META_STEP.search(t):
                add("warn", "meta_step", f"step {i + 1} ({t.strip()!r}) looks like a review/combine step; "
                                         "the prompt says that happens automatically")
            if t.strip():
                titles.append(t.strip().lower())
        if isinstance(ins, str):
            if ins and not ins.strip():
                add("error", "blank_instructions", f"step {i + 1}'s instructions are only whitespace; Chimera uses the title")
            elif ins.strip() and len(ins.strip()) < 25:
                add("warn", "instructions_short", f"step {i + 1}'s instructions are under 25 characters")
    dups = sorted({t for t in titles if titles.count(t) > 1})
    if dups:
        add("warn", "duplicate_titles", "repeated step title(s): " + ", ".join(dups))
    kinds = [s.get("kind") for s in steps if isinstance(s, dict)]
    pk = p.get("kind")
    if pk in KINDS and pk != "general" and kinds and all(k in KINDS for k in kinds) and pk not in kinds:
        add("warn", "kind_mismatch", f"the plan's kind is {pk} but no step is")


def _find_cycle(graph):
    """A dependency cycle (excluding self-loops, reported separately) as a list of step indexes."""
    state, stack = {}, []

    def visit(i):
        state[i] = 1
        stack.append(i)
        for j in sorted(graph[i]):
            if j == i:
                continue
            if state.get(j) == 1:
                return stack[stack.index(j):] + [j]
            if state.get(j) is None:
                c = visit(j)
                if c:
                    return c
        stack.pop()
        state[i] = 2
        return None

    for i in sorted(graph):
        if state.get(i) is None:
            c = visit(i)
            if c:
                return c
    return None


def plan_metrics(plan) -> dict:
    """Shape of a cleaned plan: step count, longest dependency chain (depth) and the most steps
    that could run at once (width, before Chimera's cap of 4 parallel steps)."""
    steps = plan["steps"]
    ids = [s["id"] for s in steps]
    level = []
    for i, s in enumerate(steps):
        lv = 0
        for d in s.get("depends_on") or []:
            if d in ids[:i]:
                lv = max(lv, level[ids.index(d)] + 1)
        level.append(lv)
    per = Counter(level)
    return {"steps": len(steps), "depth": max(level) + 1, "width": max(per.values()), "roots": per[0],
            "plan_kind": plan["kind"], "step_kinds": sorted({s["kind"] for s in steps})}


def canonicalize_plan(p: dict) -> dict:
    """Rename step ids to s1..sN in order and remap depends_on to match, dropping entries that
    don't name a step. For tidying teacher output before validation; fixes nothing else."""
    q = json.loads(json.dumps(p))
    steps = q.get("steps")
    if not isinstance(steps, list):
        return q
    rename = {}
    for i, s in enumerate(steps):
        if isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"] not in rename:
            rename[s["id"]] = f"s{i + 1}"
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            continue
        s["id"] = f"s{i + 1}"
        if isinstance(s.get("depends_on"), list):
            s["depends_on"] = [rename[d] for d in s["depends_on"] if isinstance(d, str) and d in rename]
    return q

def tidy_plan(p: dict) -> dict:
    """Format-only fixes for a plan: ids renamed s1..sN (depends_on remapped, entries that
    name no step dropped) and a missing depends_on filled with []. What the training-data
    filter applies before checking; it fixes nothing about the plan itself."""
    q = canonicalize_plan(p)
    for s in q.get("steps") or []:
        if isinstance(s, dict) and "depends_on" not in s:
            s["depends_on"] = []
    return q

# ---------------------------------------------------------------- reviewer

def validate_review(text: str, require=()) -> Result:
    """A reviewer reply. effective is the verdict as Chimera uses it: a reply it can't decode
    counts as done (the loop stops with the current result).

    The reply may start with "check", the helper's requirement-by-requirement check (Chimera's
    decoder ignores unknown fields); its length and position go in metrics. require=("check",)
    makes it compulsory, non-blank and first, as in v2's training targets and the check-first
    experiment."""
    ok, decoded, _ = cp.extract_json(text, cp.REVIEW_SPEC)
    r = Result("reviewer", ok, dict(decoded) if ok else {"done": True, "score": 0, "critique": ""})
    if not ok:
        r.issues.append(Issue("error", "chimera_rejects", "Chimera can't decode this verdict and stops the loop as if done"))
    r.obj = _strict_parse(text, r.issues)
    if r.obj is not None:
        r.schema_ok = _check_schema(r.obj, "reviewer", r.issues)
        if isinstance(r.obj, dict):
            _review_sanity(r.obj, r.issues)
            chk = r.obj.get("check")
            if isinstance(chk, str):
                r.metrics["check_chars"] = len(chk)
                r.metrics["check_first"] = next(iter(r.obj)) == "check"
            if "check" in require:
                if "check" not in r.obj:
                    r.issues.append(Issue("error", "missing_check", 'no "check" field'))
                elif isinstance(chk, str) and not chk.strip():
                    r.issues.append(Issue("error", "blank_check", '"check" is empty'))
                elif isinstance(chk, str) and not r.metrics["check_first"]:
                    r.issues.append(Issue("error", "check_not_first", '"check" isn\'t the first key, so it comes after the verdict'))
    return r


def _review_sanity(v, issues):
    done, score, crit = v.get("done"), v.get("score"), v.get("critique")
    if done is False and isinstance(crit, str) and crit and not crit.strip():
        issues.append(Issue("error", "blank_critique", "not done, but the critique is only whitespace: the next round gets nothing to fix"))
    if isinstance(score, int) and not isinstance(score, bool) and isinstance(done, bool):
        if done and score < 50:
            issues.append(Issue("warn", "done_low_score", f"done with a score of {score}"))
        if not done and score >= 90:
            issues.append(Issue("warn", "not_done_high_score", f"not done with a score of {score}"))
    if done is False and isinstance(crit, str) and crit.strip() and len(crit.strip()) < 20:
        issues.append(Issue("warn", "critique_vague", "the critique is under 20 characters"))
    if isinstance(crit, str) and len(crit) > 1500:
        issues.append(Issue("warn", "critique_long", "the critique is over 1,500 characters; the prompt asks for short"))

# ---------------------------------------------------------------- gate

def validate_gate(text: str) -> Result:
    """A gate reply. effective is the decision Chimera makes: a reply it can't decode is use=false."""
    ok, decoded, _ = cp.extract_json(text, cp.GATE_SPEC)
    r = Result("gate", ok, bool(decoded["use"]) if ok else False)
    if not ok:
        r.issues.append(Issue("error", "chimera_rejects", "Chimera can't decode this answer and treats it as use=false"))
    r.obj = _strict_parse(text, r.issues)
    if r.obj is not None:
        r.schema_ok = _check_schema(r.obj, "gate", r.issues)
    return r


VALIDATORS = {"planner": validate_plan, "reviewer": validate_review, "gate": validate_gate}


def valid_after_tidy(res: Result) -> bool:
    """For a planner Result: is the reply strictly valid once its JSON object gets tidy_plan
    (which also drops any code fence or prose around it)?"""
    if res.job != "planner" or not isinstance(res.obj, dict):
        return False
    return validate_plan(json.dumps(tidy_plan(res.obj))).valid
