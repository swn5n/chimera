"""Today's worker request and combine, ported from Chimera 0.7.0 for the A/B arms (arm A and A2: today's prompt).

    from contract import today
    req = today.worker_messages(plan, index, outputs)   # {"messages": [...], "need_ctx": int}
    req = today.combine_messages(goal, plan, outputs)    # the biggest model's combine (synthPrompt)

plan is a cleaned plan (goport.clean_plan). outputs maps a step's plan id to its output: a string, or
None for a failed step, or {"output": str, "status": "done" | "failed" | "library", "error": str}.
The texts live in texts.py; tests/test_contract_today.py checks them and the Go lines cited here against app/.
"""
from __future__ import annotations

from . import texts as T
from .goport import history_tokens, truncate


def norm_output(v):
    """(text, status, error) for one entry of outputs."""
    if v is None:
        return "", "failed", ""
    if isinstance(v, str):
        return v, "done", ""
    status = v.get("status") or ("failed" if v.get("output") is None else "done")
    return v.get("output") or "", status, v.get("error") or ""


def refs_block(refs) -> str:
    """refsBlock (app/hydra.go 310-320). refs: dicts with title, kind, summary, content."""
    if not refs:
        return ""
    return T.REFS_HEAD + "".join(T.REFS_ENTRY % (e["title"], e["kind"], e["summary"], truncate(e["content"], T.REFS_CUT))
                                 for e in refs)


def kind_rules(plan, step) -> str:
    """The rules workerPrompt picks (app/prompts.go 79-86): the step's kind, else the plan's, else general."""
    kind = step.get("kind", "")
    if not T.TODAY_KIND_RULES.get(kind):
        kind = plan.get("kind", "")
    return T.TODAY_KIND_RULES.get(kind) or T.TODAY_KIND_RULES["general"]


def worker_prompt(plan, step) -> str:
    """workerPrompt (app/prompts.go 69-97)."""
    outline = []
    for i, s in enumerate(plan["steps"]):
        marker = "→ " if s["id"] == step["id"] else "  "  # by id, as Go does: a clashing id marks two lines
        outline.append("%s%d. %s\n" % (marker, i + 1, s["title"]))
    return T.TODAY_WORKER_FORMAT % (plan["title"], plan["summary"], "".join(outline), kind_rules(plan, step))


def user_message(plan, step, outputs) -> str:
    """runStep's user message (app/hydra.go 911-923): the instructions, then each dependency's output."""
    parts = [step["instructions"]]
    for dep in step.get("depends_on") or []:
        for s in plan["steps"]:
            if s["id"] == dep:
                out, status, _ = norm_output(outputs.get(s["id"]))
                if status == "failed":
                    out = T.TODAY_DEP_FAILED
                parts.append(T.TODAY_DEP_FORMAT % (s["title"], truncate(out, T.TODAY_DEP_CUT)))
    return "".join(parts)


def worker_messages(plan, index, outputs, refs=None, room=T.STEP_ROOM) -> dict:
    """The messages runStep sends (app/hydra.go 924) and the NeedCtx it asks for (929)."""
    step = plan["steps"][index]
    msgs = [{"role": "system", "content": worker_prompt(plan, step) + refs_block(refs)},
            {"role": "user", "content": user_message(plan, step, outputs)}]
    return {"messages": msgs, "need_ctx": history_tokens(msgs) + room}


def synth_prompt(kind) -> str:
    """synthPrompt (app/prompts.go 107-114)."""
    rules = T.TODAY_SYNTH_KIND_RULES.get(kind) or T.TODAY_SYNTH_KIND_RULES["general"]
    return T.TODAY_SYNTH_HEAD + rules + T.TODAY_SYNTH_TAIL


def combine_messages(goal, plan, outputs, room=4096) -> dict:
    """onePass's combine request (app/hydra.go 575-587). For the contract's fallback ("today's synthPrompt
    combine, with the handoffs added"), pass the pieces as written, handoff blocks included."""
    steps = plan["steps"]
    parts = [T.TODAY_COMBINE_HEAD % (goal, plan["title"], plan["summary"])]
    budget = T.TODAY_COMBINE_BUDGET // len(steps)
    for i, s in enumerate(steps):
        out, status, err = norm_output(outputs.get(s["id"]))
        if status == "failed":
            out = T.TODAY_COMBINE_FAILED % err
        parts.append(T.TODAY_COMBINE_STEP % (i + 1, s["title"], truncate(out, budget)))
    msgs = [{"role": "system", "content": synth_prompt(plan["kind"])}, {"role": "user", "content": "".join(parts)}]
    return {"messages": msgs, "need_ctx": history_tokens(msgs) + room}
