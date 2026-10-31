"""The contract's worker request: system prompt, user message, round-2 parts and the repair message.

    from contract import prompt
    req = prompt.worker_request(plan, index, outputs, goal=goal)       # round 1
    req = prompt.worker_request(plan, index, outputs, prev_result=last, critique=c)   # round 2 on
    req = prompt.repair_request(plan, index, outputs, piece, crash)    # crash = linemap.locate_check(...)
    req.messages, req.need_ctx, req.mode, req.sid

plan is a cleaned plan (goport.clean_plan), as Chimera runs it. outputs maps a step's plan id to its reply
(a string), None for a failed step, or {"output", "status"} (today.norm_output). Every text comes from texts.py;
the layout is the plan's "WORKER SYSTEM PROMPT", "MODE RULES", "USER MESSAGE" and "REPAIR MESSAGE".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from . import planinfo
from . import texts as T
from .goport import cap_runes, history_tokens, truncate
from .join import find_part
from .today import norm_output, refs_block
from .validate import parse_handoff, strip_handoff


@dataclass
class WorkerRequest:
    messages: List[dict]
    need_ctx: int
    mode: str
    sid: str
    n: int
    lone: bool
    deps: List[str] = field(default_factory=list)
    round2_matched: bool = False  # round 2: the step's own part was found in the last result

    def to_dict(self):
        return {"messages": self.messages, "need_ctx": self.need_ctx, "mode": self.mode, "sid": self.sid,
                "n": self.n, "lone": self.lone, "deps": self.deps, "round2_matched": self.round2_matched}


def mode_rules(mode, sid, kind=""):
    """The frozen rules for a mode, for step sid (research steps get the extra line)."""
    rules = T.fill(T.MODE_RULES[mode], sid=sid)
    if mode == "section" and kind == "research":
        rules += "\n" + T.MODE_SECTION_RESEARCH
    return rules


def outline(plan, i):
    """The plan lines, → on step i."""
    out = []
    for j, s in enumerate(plan["steps"]):
        deps = planinfo.dep_names(plan, j)
        uses = T.fill(T.CONTRACT_OUTLINE_USES, names=", ".join(deps)) if deps else ""
        vals = dict(name="s%d" % (j + 1), title=planinfo.one_line(s["title"]), kind=s["kind"], uses=uses)
        if j == i:
            out.append(T.fill(T.CONTRACT_OUTLINE_YOURS, **vals))
        else:
            vals["instructions"] = cap_runes(planinfo.one_line(s["instructions"]), T.CONTRACT_OUTLINE_CUT)
            out.append(T.fill(T.CONTRACT_OUTLINE_OTHER, **vals))
    return "\n".join(out)


def system_prompt(plan, i, goal="", refs=None):
    """The worker system prompt for step i, refsBlock appended unchanged."""
    steps = plan["steps"]
    sid, n = "s%d" % (i + 1), len(steps)
    mode = planinfo.step_mode(plan, i, goal)
    rules = mode_rules(mode, sid, steps[i]["kind"])
    project = T.fill(T.CONTRACT_PROJECT, title=plan["title"], summary=plan["summary"])
    if n == 1:
        parts = [T.CONTRACT_LONE_OPENING, project, T.CONTRACT_JOIN_HEAD + "\n" + rules]
    else:
        users = planinfo.user_names(plan, i)
        used = T.fill(T.CONTRACT_USED_BY, names=", ".join(users)) if users else T.CONTRACT_USED_BY_NONE
        parts = [T.fill(T.CONTRACT_OPENING, sid=sid, n=n), project,
                 T.CONTRACT_PLAN_HEAD + "\n" + outline(plan, i) + "\n" + used,
                 T.CONTRACT_JOIN_HEAD + "\n" + rules, T.CONTRACT_HANDOFF]
    return "\n\n".join(parts) + refs_block(refs)


def dep_part(plan, j, outputs):
    """One dependency's part of the user message."""
    s = plan["steps"][j]
    head = T.fill(T.CONTRACT_USER_DEP_HEAD, name="s%d" % (j + 1), title=s["title"])
    text, status, _ = norm_output(outputs.get(s["id"]))
    if status == "failed":
        return head + "\n" + T.CONTRACT_USER_DEP_FAILED
    handoff, blocks, _ = parse_handoff(text)
    lines = T.fill(T.CONTRACT_USER_DEP_HANDOFF, lines="\n".join(handoff.lines())) if handoff \
        else T.CONTRACT_USER_DEP_NO_HANDOFF
    return head + "\n" + lines + "\n" + truncate(strip_handoff(text, blocks), T.CONTRACT_USER_DEP_CUT)


def user_message(plan, i, outputs=None, prev_result=None, critique=None, goal=""):
    """The user message for step i; with prev_result (round 2 on), the step's part of it and the critique.
    Returns (message, matched): matched says whether the step's own part was found in prev_result."""
    outputs = outputs or {}
    s = plan["steps"][i]
    parts = [T.fill(T.CONTRACT_USER_STEP, sid="s%d" % (i + 1), title=s["title"], instructions=s["instructions"])]
    parts += [dep_part(plan, j, outputs) for j in planinfo.dep_indexes(plan, i)]
    matched = False
    if prev_result is not None:
        part, matched = find_part(prev_result, plan, i, planinfo.step_mode(plan, i, goal))
        parts.append(T.fill(T.CONTRACT_ROUND2_PART, part=part))
        parts.append(T.fill(T.CONTRACT_ROUND2_CRITIQUE, critique=critique or T.CONTRACT_ROUND2_NO_CRITIQUE))
    return "\n\n".join(parts), matched


def worker_request(plan, i, outputs=None, goal="", refs=None, prev_result=None, critique=None, room=T.STEP_ROOM):
    """The contract request for step i (0-based). NeedCtx as runStep: historyTokens(msgs) + room."""
    user, matched = user_message(plan, i, outputs, prev_result, critique, goal)
    msgs = [{"role": "system", "content": system_prompt(plan, i, goal, refs)}, {"role": "user", "content": user}]
    return WorkerRequest(msgs, history_tokens(msgs) + room, planinfo.step_mode(plan, i, goal), "s%d" % (i + 1),
                         len(plan["steps"]), len(plan["steps"]) == 1, planinfo.dep_names(plan, i), matched)


def crash_where(crash):
    """What the repair message's "in {function}" names: the line map's function (build_s2, a _s2_ helper or
    constant, SETTINGS_s2), "the imports" for an import line (FILLED), else the step's build function."""
    if crash.get("function"):
        return crash["function"]
    sid = crash.get("step") or "s1"
    part = crash.get("part")
    if part == "settings":
        return "SETTINGS_" + sid
    if part == "import":
        return T.CONTRACT_REPAIR_IMPORTS
    return "build_" + sid


def repair_text(piece, crash, runner=""):
    """The repair message's own part. crash: linemap.locate_check()'s dict (piece_line, function, part, source,
    error, runner)."""
    return T.fill(T.CONTRACT_REPAIR, runner=runner or crash.get("runner") or "Blender",
                  line=crash.get("piece_line") or crash.get("line") or "?", function=crash_where(crash),
                  source=crash.get("source", ""), exception=crash.get("error", ""), piece=piece.strip())


def repair_request(plan, i, outputs, piece, crash, goal="", refs=None, room=T.STEP_ROOM):
    """Looping mode's step repair: the step's request as above, then the repair message."""
    req = worker_request(plan, i, outputs, goal, refs, room=room)
    req.messages[1]["content"] += "\n\n" + repair_text(piece, crash)
    req.need_ctx = history_tokens(req.messages) + room
    return req
