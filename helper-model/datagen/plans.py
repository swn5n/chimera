"""Stage 2: the teacher plans each planner seed through Chimera's exact planner request, and
(stage 5) re-plans after a review says the result isn't done, exactly as Hydra's looping mode does."""
from __future__ import annotations

import json
import os

from . import taxonomy as tx
from .common import Progress, Store, final_sanity, parse_obj, read_jsonl, round_robin, sanity, stable_int, warn_if_low

from helper import chimera_port as cp
from helper.validate import tidy_plan, validate_plan

# Errors that only concern the format and disappear when the plan is re-serialised with tidy_plan
# (code fences or text around the JSON, ids like "step1"). Anything else rejects the plan.
FORMAT_ONLY = {"extra_text", "schema:pattern"}
# Quality warnings that also reject a plan as a training target.
BLOCKING_WARNINGS = {"meta_step", "kind_mismatch", "duplicate_titles"}


def judge_plan(category, text):
    """Is a teacher plan good enough to train on? Returns (ok, reasons, target text, result)."""
    res = validate_plan(text)
    if not res.chimera_ok:
        return False, ["chimera_rejects"], None, res
    if not isinstance(res.obj, dict):
        return False, ["not_one_json_object"], None, res
    reasons = []
    for i in res.errors:
        if i.code in FORMAT_ONLY or (i.code == "schema:required" and 'missing "depends_on"' in i.message):
            continue
        reasons.append(i.code)
    target = json.dumps(tidy_plan(res.obj), ensure_ascii=False)
    res2 = validate_plan(target)
    reasons += [i.code for i in res2.errors]
    reasons += [i.code for i in res2.warnings if i.code in BLOCKING_WARNINGS]
    if res2.effective:
        kinds = tx.EXPECT_KIND.get(category)
        if kinds and res2.effective["kind"] not in kinds:
            reasons.append("kind:" + res2.effective["kind"])
        if category == "batch" and res2.metrics.get("width", 0) < 2:
            reasons.append("batch_not_parallel")
    reasons = sorted(set(reasons))
    return (not reasons), reasons, (None if reasons else target), res2


def _plan_body(models, teacher, messages, seed_parts):
    body = cp.chat_body("planner", teacher, messages)
    body["options"].update(seed=stable_int("plan", *seed_parts), num_predict=6000)
    if models.teacher_think() is not None:
        body["think"] = models.teacher_think()
    return body


def _attempts(models, store, key_base, category, messages, teacher, attempts, extra):
    """Try up to `attempts` times; returns the accepted record or the last one."""
    last = None
    for k in range(attempts):
        key = f"{key_base}#a{k}"
        rec = store.get(key)
        if rec is None:
            call = models.call(_plan_body(models, teacher, messages, (key_base, k)))
            if call["error"]:
                ok, reasons, target, res = False, ["call_error"], None, None
            else:
                ok, reasons, target, res = judge_plan(category, call["content"])
            rec = dict(extra, key=key, attempt=k, category=category, accepted=ok, reasons=reasons, target=target,
                       messages=messages if ok else None, reply=None if ok else (call["content"] or "")[:6000],
                       thinking_chars=len(call["thinking"] or ""), wall_s=round(call["wall_s"] or 0, 2),
                       error=call["error"], metrics=(res.metrics if res is not None else None))
            store.add(rec)
            rec["_new"] = True
        last = rec
        if rec["accepted"]:
            break
    return last


def run(models, size, data_dir, teacher, log=None):
    seeds = [s for s in read_jsonl(os.path.join(data_dir, "seeds.jsonl")) if s["category"] in tx.PLANNER_CATS]
    seeds = round_robin(seeds, key=lambda s: s["category"])
    if size.get("max_plan_seeds"):
        seeds = seeds[:size["max_plan_seeds"]]
    store = Store(os.path.join(data_dir, "raw", "plans.jsonl"))
    prog = Progress("plans", len(seeds), log)
    checked = good = 0
    tails = []
    for s in seeds:
        messages = cp.planner_messages(s["text"], s.get("history"))
        rec = _attempts(models, store, s["seed_id"], s["category"], messages, teacher, size["plan_attempts"],
                        {"seed_id": s["seed_id"], "source": "plan"})
        if not rec.pop("_new", False):
            prog.step(s["seed_id"], "done before", skipped=True)
            continue
        checked += 1
        good += rec["accepted"]
        tails.append(rec.get("reply") or rec.get("target"))
        prog.step(s["seed_id"], "accepted" if rec["accepted"] else "rejected: " + ", ".join(rec["reasons"]), rec["wall_s"])
        sanity(data_dir, "plans", "seeds got an acceptable plan", good, checked, 0.5, size, tails)
    final_sanity(data_dir, "plans", "seeds got an acceptable plan", good, checked, 0.3, size, tails)
    allrecs = store.all()
    return {"seeds": len(seeds), "accepted": len({r["seed_id"] for r in allrecs if r["accepted"]})}


def run_replans(models, size, data_dir, teacher, log=None):
    """Round-2 plans: the previous result and the review's critique, as Hydra sends them."""
    from .reviews import judged_reviews
    seeds = {s["seed_id"]: s for s in read_jsonl(os.path.join(data_dir, "seeds.jsonl"))}
    cands = [j for j in judged_reviews(data_dir) if j["accepted"] and not j["target_obj"]["done"]
             and seeds.get(j["seed_id"], {}).get("category") in tx.PLANNER_CATS]
    cands.sort(key=lambda j: stable_int("replan", j["item_key"]))
    cands = cands[:size["replans"]]
    store = Store(os.path.join(data_dir, "raw", "replans.jsonl"))
    prog = Progress("replans", len(cands), log)
    checked = good = 0
    tails = []
    for j in cands:
        s = seeds[j["seed_id"]]
        messages = cp.planner_messages(s["text"], s.get("history"), prior=j["result"], critique=j["target_obj"]["critique"])
        rec = _attempts(models, store, "re:" + j["item_key"], s["category"], messages, teacher, 1,
                        {"seed_id": j["seed_id"], "source": "replan", "item_key": j["item_key"]})
        if not rec.pop("_new", False):
            prog.step(j["item_key"], "done before", skipped=True)
            continue
        checked += 1
        good += rec["accepted"]
        tails.append(rec.get("reply") or rec.get("target"))
        prog.step(j["item_key"], "accepted" if rec["accepted"] else "rejected: " + ", ".join(rec["reasons"]), rec["wall_s"])
    warn_if_low("replans", "re-plans were acceptable", good, checked, 0.4)
    return {"candidates": len(cands), "accepted": sum(1 for r in store.all() if r["accepted"])}


# ---------------------------------------------------------------- v2: plans with a hint

# v1 rejection reasons a one-line hint to the teacher can fix. The training example keeps Chimera's exact
# planner request (no hint); only the teacher's copy has it.
HINTABLE = {"schema:minItems", "schema:maxItems", "step_count", "schema:pattern", "batch_not_parallel", "meta_step", "kind:code"}


def plan_hints(category, reasons, steps=None):
    """The hints for a plan rejected for `reasons` (steps: how many steps it had, if known)."""
    from . import teacher_prompts as tp
    r = set(reasons)
    out = []
    if "schema:minItems" in r or ("step_count" in r and steps is not None and steps < 2):
        out.append(tp.PLAN_HINTS["one_step"])
    if "schema:maxItems" in r or ("step_count" in r and steps is not None and steps > 7):
        out.append(tp.PLAN_HINTS["too_many"])
    if "batch_not_parallel" in r:
        out.append(tp.PLAN_HINTS["not_parallel"])
    if "meta_step" in r:
        out.append(tp.PLAN_HINTS["meta_step"])
    if "kind:code" in r and category == "blender":
        out.append(tp.PLAN_HINTS["blender_kind"])
    return out


def hinted_candidates(data_dir):
    """Seeds for stage plans2: v1 planner seeds whose every plan was rejected only for reasons a hint can fix
    (a Blender plan whose one problem was the `code` label is already recovered by the build, so not here),
    then the long-batch seeds from seeds2, which get a first try without a hint."""
    seeds = {s["seed_id"]: s for s in read_jsonl(os.path.join(data_dir, "seeds.jsonl"))}
    by = {}
    for r in Store(os.path.join(data_dir, "raw", "plans.jsonl")).all():
        by.setdefault(r["seed_id"], []).append(r)
    out = []
    for sid, rs in sorted(by.items()):
        if any(r["accepted"] for r in rs) or sid not in seeds:
            continue
        last = sorted(rs, key=lambda r: r["attempt"])[-1]
        reasons = set(last["reasons"] or [])
        if not reasons or not reasons <= HINTABLE or reasons == {"kind:code"}:
            continue
        if "kind:code" in reasons and last["category"] != "blender":
            continue
        steps = (last.get("metrics") or {}).get("steps")
        if steps is None:
            obj = parse_obj(last.get("reply"))
            steps = len(obj["steps"]) if isinstance(obj, dict) and isinstance(obj.get("steps"), list) else None
        hints = plan_hints(last["category"], reasons, steps)
        if hints:
            out.append({"seed": seeds[sid], "hints": hints, "v1_reasons": sorted(reasons), "new": False})
    for s in read_jsonl(os.path.join(data_dir, "seeds2.jsonl")):
        out.append({"seed": s, "hints": [], "v1_reasons": [], "new": True})
    return out


def _hinted_body(models, teacher, messages, hints, seed_parts):
    from . import teacher_prompts as tp
    msgs = [dict(m) for m in messages]
    if hints:
        msgs[0]["content"] += tp.PLAN_HINT_INTRO + " ".join(hints)
    return _plan_body(models, teacher, msgs, seed_parts)


def run_hinted(models, size, data_dir, teacher, log=None):
    """Stage plans2. A new seed gets a plain first try (like v1), then one with hints for what went wrong;
    a v1 reject gets up to two hinted tries."""
    cands = hinted_candidates(data_dir)
    if size.get("plan_hint_max"):
        cands = cands[:size["plan_hint_max"]]
    store = Store(os.path.join(data_dir, "raw", "plans2.jsonl"))
    prog = Progress("plans2", len(cands), log)
    checked = good = 0
    for c in cands:
        s = c["seed"]
        messages = cp.planner_messages(s["text"], s.get("history"))  # Chimera's exact request: the training input
        hints = list(c["hints"])
        tries = [[]] + [None] if c["new"] else [hints, hints]  # None: hints from the try before
        last, new = None, False
        for k, h in enumerate(tries):
            key = f"{s['seed_id']}#h{k}"
            rec = store.get(key)
            if rec is None:
                if h is None:
                    h = plan_hints(s["category"], last["reasons"], (last.get("metrics") or {}).get("steps"))
                    if not h:
                        break  # nothing a hint can fix
                call = models.call(_hinted_body(models, teacher, messages, h, ("h", s["seed_id"], k)))
                if call["error"]:
                    ok, reasons, target, res = False, ["call_error"], None, None
                else:
                    ok, reasons, target, res = judge_plan(s["category"], call["content"])
                rec = {"key": key, "seed_id": s["seed_id"], "attempt": k, "category": s["category"], "source": "plan2",
                       "hints": h, "new_seed": c["new"], "v1_reasons": c["v1_reasons"], "accepted": ok, "reasons": reasons,
                       "target": target, "messages": messages if ok else None,
                       "reply": None if ok else (call["content"] or "")[:6000], "thinking_chars": len(call["thinking"] or ""),
                       "wall_s": round(call["wall_s"] or 0, 2), "error": call["error"],
                       "metrics": (res.metrics if res is not None else None)}
                store.add(rec)
                new = True
            last = rec
            if rec["accepted"]:
                break
        if not new:
            prog.step(s["seed_id"], "done before", skipped=True)
            continue
        checked += 1
        good += bool(last and last["accepted"])
        status = "accepted" if last and last["accepted"] else "rejected: " + ", ".join(last["reasons"] if last else [])
        prog.step(s["seed_id"] + (" (new)" if c["new"] else ""), status, last["wall_s"] if last else None)
    warn_if_low("plans2", "plans were acceptable", good, checked, 0.4)
    recs = store.all()
    return {"candidates": len(cands), "accepted": len({r["seed_id"] for r in recs if r["accepted"]})}
