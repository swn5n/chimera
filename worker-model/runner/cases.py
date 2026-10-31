"""Worker eval cases as the runners use them: one step of a cleaned plan, its inputs as replies, and the two
requests (today's worker prompt or the draft contract).

EVAL ONLY: the cases come from eval/ (and eval/frozen/), never training data.

    import evalset
    from runner import cases
    es = evalset.load()
    cs = cases.load_cases(es, parts=["w2"], ids=["w2-01"])
    req = cases.request(cs[0], "contract")      # {"messages", "need_ctx", "mode", "notes"}

An input in the eval is {"status": "failed"} or {"status": "done", "handoff": {...} | null, "piece": [...] |
"from": [...]}. As a dependency's reply it is the piece, plus its handoff as a ```handoff block when it has one.
Today's prompt gets the piece without the handoff: today's workers never write one, so arm A's world has none.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from runner.common import HELPER, HERE, read_json

import evalset  # noqa: E402  (worker-model/evalset.py)
from contract import planinfo, prompt as cprompt, today  # noqa: E402
from contract.goport import clean_plan, history_tokens  # noqa: E402

FROZEN_DIR = os.path.join(HERE, "eval", "frozen")
PROMPTS = ("today", "contract")
PARTS = ("w1", "w2", "w3", "w4f", "w4l")


@dataclass
class StepCase:
    id: str
    part: str
    mode: str  # the contract's mode, as planinfo.step_mode reads the plan
    plan: dict  # cleaned (goport.clean_plan), as Chimera runs it
    index: int  # 0-based position of the step
    goal: str = ""
    inputs: dict = field(default_factory=dict)  # the eval's inputs, by plan id
    outputs: Dict[str, Optional[str]] = field(default_factory=dict)  # dependency replies, handoffs included
    outputs_today: Dict[str, Optional[str]] = field(default_factory=dict)  # the same without handoff blocks
    prev_result: Optional[str] = None  # round 2: last round's result
    critique: Optional[str] = None
    repair: Optional[dict] = None  # W3: {"piece": the broken reply, "crash": repair_text's dict}
    expect: dict = field(default_factory=dict)
    case: dict = field(default_factory=dict)  # the eval case itself (W3's fix, W2's facts, …)
    eval_mode: str = ""  # the mode the eval file states (should equal mode)

    @property
    def step(self):
        return self.plan["steps"][self.index]

    @property
    def sid(self):
        return "s%d" % (self.index + 1)

    @property
    def deps(self):
        return planinfo.dep_names(self.plan, self.index)

    @property
    def dep_ids(self):
        return [self.plan["steps"][j]["id"] for j in planinfo.dep_indexes(self.plan, self.index)]

    @property
    def lone(self):
        return len(self.plan["steps"]) == 1

    @property
    def prose(self):
        return self.mode == "section"


def handoff_block(h):
    """A handoff dict as the ```handoff block a contract piece ends with."""
    return "```handoff\nprovides: %s\nuses: %s\nassumed: %s\n```" % (
        h.get("provides") or "none", h.get("uses") or "none", h.get("assumed") or "none")


def input_reply(d, text=None, handoff=True):
    """One eval input as the dependency's reply (None for a failed step)."""
    if d.get("status") == "failed":
        return None
    body = text if text is not None else evalset.code(d.get("piece"))
    if handoff and d.get("handoff"):
        body = body.rstrip() + "\n\n" + handoff_block(d["handoff"]) + "\n"
    return body


def repair_crash(crash):
    """A W3 crash record as prompt.repair_text wants it (the line in the piece's own block, as the line map gives)."""
    return {"piece_line": crash.get("line"), "function": crash.get("function"), "source": crash.get("source", ""),
            "error": crash.get("exception", ""), "runner": "Blender " + crash.get("version", "")}


def from_eval(es, c, part):
    """A W2-W4 eval case as a StepCase."""
    plan = clean_plan(c["plan"])
    index = next(i for i, s in enumerate(plan["steps"]) if s["id"] == c["step"])
    long = es.long_inputs(c) if part == "w4l" else {}
    outputs, outputs_today = {}, {}
    for sid, d in (c.get("inputs") or {}).items():
        outputs[sid] = input_reply(d, long.get(sid))
        outputs_today[sid] = input_reply(d, long.get(sid), handoff=False)
    sc = StepCase(id=c["id"], part=part, mode=planinfo.step_mode(plan, index), plan=plan, index=index,
                  inputs=c.get("inputs") or {}, outputs=outputs, outputs_today=outputs_today,
                  expect=c.get("expect") or {}, case=c, eval_mode=c.get("mode", ""))
    if part == "w4l" and c.get("round2"):
        sc.prev_result, sc.critique = es.previous_result(c), c["round2"].get("critique") or ""
    if part == "w3":
        sc.repair = {"piece": evalset.code(c["piece"]), "crash": repair_crash(c["crash"])}
    return sc


# ---------------------------------------------------------------- W1: steps of the frozen plans

def task_goals(es):
    """W1 task id -> (goal, history, prior, critique): the 10 new Blender tasks' prompts and helper-model's
    44 long-task prompts (read from helper-model/eval/prompts.json, which the eval only references)."""
    out = {c["id"]: (c["prompt"], None, "", "") for c in es.cases("w1")}
    hp = es.docs["w1"]["helper_prompts"]
    src = read_json(os.path.join(HELPER, hp["file"].split("/", 1)[1]), {"items": []})
    by = {p["id"]: p for p in src["items"]}
    for pid in hp["ids"]:
        p = by.get(pid)
        if p:
            out[pid] = (p["prompt"], p.get("history"), p.get("prior") or "", p.get("critique") or "")
    return out


def plan_sha(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()


def load_frozen(frozen_dir=FROZEN_DIR):
    """(plans by task id, deps by task id) from eval/frozen/ ({} when nothing is frozen yet)."""
    plans = read_json(os.path.join(frozen_dir, "plans.json"), {}) or {}
    deps = read_json(os.path.join(frozen_dir, "deps.json"), {}) or {}
    return ({p["id"]: p for p in plans.get("items") or []}, {d["id"]: d for d in deps.get("items") or []})


def w1_cases(es, frozen_dir=FROZEN_DIR, tasks=None, skipped=None):
    """Every step of every frozen plan whose dependencies all have a frozen outcome (a verified output, or a
    step that failed). A dependency left "rejected" (no verified output) skips the step; skipped collects why.
    A dependency with a "today" variant (today's format, no handoff) gives one more case, "<task>/<sN>-today"."""
    plans, deps = load_frozen(frozen_dir)
    goals = task_goals(es)
    out = []
    for tid, item in plans.items():
        if tasks and tid not in tasks:
            continue
        plan = item["plan"]
        steps = (deps.get(tid) or {}).get("steps") or {}
        if (deps.get(tid) or {}).get("plan_sha") not in (None, plan_sha(plan)):
            if skipped is not None:
                skipped.append(f"{tid}: deps.json was frozen for another plan")
            continue
        goal, _, prior, critique = goals.get(tid, ("", None, "", ""))
        for i, st in enumerate(plan["steps"]):
            dep_ids = [plan["steps"][j]["id"] for j in planinfo.dep_indexes(plan, i)]
            missing = [d for d in dep_ids if (steps.get(d) or {}).get("status") not in ("verified", "failed")]
            if missing:
                if skipped is not None:
                    skipped.append(f"{tid}/s{i + 1}: no frozen output for {', '.join(missing)}")
                continue
            outputs = {d: (steps[d]["reply"] if steps[d]["status"] == "verified" else None) for d in dep_ids}
            base = StepCase(id=f"{tid}/s{i + 1}", part="w1", mode=planinfo.step_mode(plan, i, goal), plan=plan,
                            index=i, goal=goal, outputs=outputs,
                            outputs_today={d: (strip_handoff(v) if v else v) for d, v in outputs.items()},
                            prev_result=prior or None, critique=critique if prior else None, case=item)
            out.append(base)
            for d in dep_ids:
                tv = (steps.get(d) or {}).get("today")
                if tv and tv.get("status") == "verified":
                    o = dict(outputs, **{d: tv["reply"]})
                    out.append(StepCase(id=f"{tid}/s{i + 1}-today", part="w1", mode=base.mode, plan=plan, index=i,
                                        goal=goal, outputs=o, outputs_today=dict(base.outputs_today, **{d: tv["reply"]}),
                                        prev_result=base.prev_result, critique=base.critique, case=item))
                    break
    return out


def strip_handoff(text):
    from contract.validate import parse_handoff, strip_handoff as strip
    _, blocks, _ = parse_handoff(text)
    return strip(text, blocks)


# ---------------------------------------------------------------- choosing cases

def load_cases(es, parts=PARTS, ids=None, quick=False, limit=0, frozen_dir=FROZEN_DIR, skipped=None):
    """The step cases to run: the parts asked for, or only ids, or the quick subset (its W2-W4 cases plus the
    first and last step of its W1 tasks, once their plans are frozen). limit: at most N cases per part."""
    want = set(ids or [])
    qcases = set(es.quick.get("cases") or []) if quick else set()
    out = []
    for part in parts:
        got = []
        if part == "w1":
            tasks = set(es.quick.get("w1_tasks") or []) if quick else None
            w1 = w1_cases(es, frozen_dir, tasks, skipped)
            if quick:
                by = {}
                for c in w1:
                    if not c.id.endswith("-today"):
                        by.setdefault(c.id.split("/")[0], []).append(c)
                w1 = [x for cs in by.values() for x in ([cs[0], cs[-1]] if len(cs) > 1 else cs)]
            got = [c for c in w1 if not want or c.id in want or c.id.split("/")[0] in want]
        else:
            for c in es.cases(part):
                if (want and c["id"] not in want) or (quick and c["id"] not in qcases):
                    continue
                got.append(from_eval(es, c, part))
        out += got[:limit] if limit else got
    return out


# ---------------------------------------------------------------- requests

def request(case, prompt_name, refs=None):
    """The messages a worker gets for this case under a prompt ("today" or "contract"), and the NeedCtx runStep
    would ask for. notes says where the request is not exactly what Chimera 0.7.0 would send."""
    notes = []
    if prompt_name == "contract":
        if case.repair:
            r = cprompt.repair_request(case.plan, case.index, case.outputs, case.repair["piece"], case.repair["crash"],
                                       goal=case.goal, refs=refs)
        else:
            r = cprompt.worker_request(case.plan, case.index, case.outputs, goal=case.goal, refs=refs,
                                       prev_result=case.prev_result, critique=case.critique)
        return {"messages": r.messages, "need_ctx": r.need_ctx, "mode": r.mode, "notes": notes,
                "round2_matched": r.round2_matched if case.prev_result is not None else None}
    if prompt_name != "today":
        raise ValueError(f"unknown prompt {prompt_name!r}")
    r = today.worker_messages(case.plan, case.index, case.outputs_today, refs=refs)
    msgs = r["messages"]
    if case.repair:
        # Chimera 0.7.0 has no step repair: a crash goes back to the planner. For a comparison the repair message's
        # own part goes after today's user message.
        msgs = [msgs[0], dict(msgs[1], content=msgs[1]["content"] + "\n\n" + cprompt.repair_text(
            case.repair["piece"], case.repair["crash"]))]
        notes.append("today has no step repair: the contract's repair part is appended to today's request")
    if case.prev_result is not None:
        notes.append("today's workers never see the last round's result (only the planner does), so it isn't sent")
    return {"messages": msgs, "need_ctx": history_tokens(msgs) + 4096, "mode": case.mode, "notes": notes,
            "round2_matched": None}
