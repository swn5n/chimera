"""Load the eval set (eval/*.json) and check it is well formed.

EVAL ONLY: everything in eval/ was written by Claude to score models. Never train on it
(Anthropic's terms bar training on Claude outputs, and it would make the scores meaningless);
tools/check_overlap.py checks training files for leaks.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .chimera_port import KINDS

EVAL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval")
FILES = ("prompts.json", "review_cases.json", "heads.json")
CATEGORIES = ("coding", "research_draft", "blender", "batch", "chat", "head")
CONFIDENCE = ("high", "medium", "low")


@dataclass
class EvalSet:
    version: str
    canary: str
    prompts: list
    reviews: list
    heads: dict  # id -> head

    def planner_cases(self):
        return [p for p in self.prompts if p.get("planner")]

    def gate_pairs(self):
        return [(p, g, self.heads[g["head"]]) for p in self.prompts for g in p.get("gate") or []]


def _read(eval_dir, name):
    with open(os.path.join(eval_dir, name), encoding="utf-8") as f:
        return json.load(f)


def load(eval_dir: str = EVAL_DIR) -> EvalSet:
    docs = {n: _read(eval_dir, n) for n in FILES}
    problems = check(docs)
    if problems:
        raise ValueError("eval set problems:\n  " + "\n  ".join(problems))
    heads = {h["id"]: h for h in docs["heads.json"]["heads"]}
    d = docs["prompts.json"]
    return EvalSet(d["version"], d["canary"], d["items"], docs["review_cases.json"]["items"], heads)


def _strs(v, nonempty=True):
    return isinstance(v, list) and (v or not nonempty) and all(isinstance(x, str) and x for x in v)


def check(docs) -> list:
    out = []
    versions = {n: d.get("version") for n, d in docs.items()}
    canaries = {n: d.get("canary") for n, d in docs.items()}
    if len(set(versions.values())) != 1:
        out.append(f"versions differ: {versions}")
    if len(set(canaries.values())) != 1 or not all(canaries.values()):
        out.append("every eval file needs the same canary string")
    heads = {}
    for h in docs["heads.json"].get("heads", []):
        hid = h.get("id")
        if not hid or hid in heads:
            out.append(f"head id missing or repeated: {hid!r}")
            continue
        heads[hid] = h
        for k in ("name", "summary", "when_to_use"):
            if not isinstance(h.get(k), str) or not h[k]:
                out.append(f"head {hid}: {k} missing")
        if h.get("status") not in ("real", "test", "hypothetical"):
            out.append(f"head {hid}: status must be real, test or hypothetical")
    ids = set()
    for p in docs["prompts.json"].get("items", []):
        pid = p.get("id")
        where = f"prompt {pid}"
        if not pid or pid in ids:
            out.append(f"prompt id missing or repeated: {pid!r}")
        ids.add(pid)
        if p.get("category") not in CATEGORIES:
            out.append(f"{where}: category must be one of {CATEGORIES}")
        if not isinstance(p.get("prompt"), str) or not p["prompt"].strip():
            out.append(f"{where}: empty prompt")
        for m in p.get("history") or []:
            if m.get("role") not in ("user", "assistant") or not isinstance(m.get("content"), str):
                out.append(f"{where}: history entries need role user/assistant and content")
        if bool(p.get("prior")) != bool(p.get("critique")):
            out.append(f"{where}: prior and critique go together")
        pl = p.get("planner")
        if pl is not None:
            if not _strs(pl.get("kind")) or not set(pl["kind"]) <= set(KINDS):
                out.append(f"{where}: planner.kind must list kinds from {KINDS}")
            st = pl.get("steps")
            if not (isinstance(st, list) and len(st) == 2 and all(isinstance(x, int) for x in st) and 1 <= st[0] <= st[1] <= 8):
                out.append(f"{where}: planner.steps must be [min, max] with 1 <= min <= max <= 8")
            if not isinstance(pl.get("must_cover"), list) or not all(_strs(g) for g in pl["must_cover"]):
                out.append(f"{where}: planner.must_cover must be a list of non-empty word lists")
            if not isinstance(pl.get("min_parallel"), int) or pl["min_parallel"] < 1:
                out.append(f"{where}: planner.min_parallel must be an integer >= 1")
        for g in p.get("gate") or []:
            if g.get("head") not in heads:
                out.append(f"{where}: gate head {g.get('head')!r} isn't in heads.json")
            if not isinstance(g.get("use"), bool):
                out.append(f"{where}: gate use must be true or false")
            if g.get("confidence") not in CONFIDENCE:
                out.append(f"{where}: gate confidence must be one of {CONFIDENCE}")
        eh = p.get("expect_head")
        if eh is not None:
            if not _strs(eh) or not set(eh) <= set(heads):
                out.append(f"{where}: expect_head must list known heads")
            for g in p.get("gate") or []:
                if g.get("head") in eh and g.get("use") is not True:
                    out.append(f"{where}: expect_head names {g['head']} but its gate label says false")
        if p.get("category") == "head" and not eh:
            out.append(f"{where}: a head prompt needs expect_head")
        if p.get("category") == "chat" and eh:
            out.append(f"{where}: a chat prompt can't expect a Head")
        if p.get("category") in ("chat", "head") and pl is not None:
            out.append(f"{where}: chat and head prompts aren't planner cases")
        if p.get("category") not in ("chat", "head") and pl is None:
            out.append(f"{where}: {p.get('category')} prompts need planner expectations")
    for r in docs["review_cases.json"].get("items", []):
        rid = r.get("id")
        where = f"review {rid}"
        if not rid or rid in ids:
            out.append(f"review id missing or repeated: {rid!r}")
        ids.add(rid)
        if r.get("category") not in CATEGORIES:
            out.append(f"{where}: category must be one of {CATEGORIES}")
        for k in ("task", "result"):
            if not isinstance(r.get(k), str) or not r[k].strip():
                out.append(f"{where}: {k} missing")
        e = r.get("expected") or {}
        if not isinstance(e.get("done"), bool):
            out.append(f"{where}: expected.done must be true or false")
        sc = e.get("score")
        if not (isinstance(sc, list) and len(sc) == 2 and all(isinstance(x, int) for x in sc) and 0 <= sc[0] <= sc[1] <= 100):
            out.append(f"{where}: expected.score must be [low, high] within 0-100")
        if e.get("done") is False and not r.get("flaws"):
            out.append(f"{where}: a not-done case needs its flaws")
        for f in r.get("flaws") or []:
            if not isinstance(f.get("what"), str) or not _strs(f.get("mention")):
                out.append(f"{where}: each flaw needs what and a mention word list")
        if r.get("confidence") not in CONFIDENCE:
            out.append(f"{where}: confidence must be one of {CONFIDENCE}")
    return out
