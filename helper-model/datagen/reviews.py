"""Stage 4: the teacher reviews each (task, result) pair twice through Chimera's exact reviewer
request. A verdict becomes training data only when both passes agree, and, for results we know
are broken, when both say not done."""
from __future__ import annotations

import json
import os
import re

from .common import Progress, Store, final_sanity, parse_obj, read_jsonl, sanity, stable_int

from helper import chimera_port as cp
from helper.validate import validate_review

PASSES = 2


def run(models, size, data_dir, teacher, log=None):
    from .results import review_items
    items = review_items(data_dir, size)
    store = Store(os.path.join(data_dir, "raw", "reviews.jsonl"))
    prog = Progress("reviews", len(items), log)
    checked = both_valid = agree = 0
    tails = []
    for it in items:
        recs, new = [], False
        for p in range(PASSES):
            key = f"{it['key']}#p{p}"
            rec = store.get(key)
            if rec is None:
                messages = cp.review_messages(it["task"], it["result"])
                body = cp.chat_body("reviewer", teacher, messages)
                body["options"].update(seed=stable_int("review", it["key"], p), num_predict=5000)
                if models.teacher_think() is not None:
                    body["think"] = models.teacher_think()
                call = models.call(body)
                res = validate_review(call["content"])
                rec = {"key": key, "item_key": it["key"], "pass": p, "valid": bool(res.valid and not call["error"]),
                       "done": bool(res.effective["done"]), "score": res.effective.get("score"),
                       "critique": res.effective.get("critique"), "reply": (call["content"] or "")[:6000],
                       "error": call["error"], "wall_s": round(call["wall_s"] or 0, 2)}
                store.add(rec)
                new = True
            recs.append(rec)
        if not new:
            prog.step(it["key"], "done before", skipped=True)
            continue
        checked += 1
        ok_both = all(r["valid"] for r in recs)
        both_valid += ok_both
        agree += ok_both and len({r["done"] for r in recs}) == 1
        tails.append(recs[0]["reply"])
        verdicts = "/".join(("done" if r["done"] else "not done") if r["valid"] else "invalid" for r in recs)
        prog.step(f"{it['key']} [{it['variant']}]", verdicts, sum(r["wall_s"] for r in recs))
        sanity(data_dir, "reviews", "items got two valid verdicts", both_valid, checked, 0.7, size, tails)
        sanity(data_dir, "reviews", "items got two agreeing verdicts", agree, checked, 0.5, size, tails)
    final_sanity(data_dir, "reviews", "items got two valid verdicts", both_valid, checked, 0.5, size, tails)
    return {"items": len(items), "accepted": sum(1 for j in judged_reviews(data_dir) if j["accepted"])}


def judged_reviews(data_dir):
    """Each review item with the training target it yields, or why it doesn't."""
    store = Store(os.path.join(data_dir, "raw", "reviews.jsonl"))
    out = []
    for it in read_jsonl(os.path.join(data_dir, "review_items.jsonl")):
        recs = [store.get(f"{it['key']}#p{p}") for p in range(PASSES)]
        why = None
        if any(r is None for r in recs):
            why = "not reviewed yet"
        elif not all(r["valid"] for r in recs):
            why = "invalid verdict"
        elif len({r["done"] for r in recs}) != 1:
            why = "passes disagree"
        elif it["expected_done"] is False and recs[0]["done"]:
            why = "known-broken result called done"
        target = None
        if why is None:
            r = recs[0]
            target = {"done": r["done"], "score": r["score"], "critique": "" if r["done"] else r["critique"]}
        out.append({"item_key": it["key"], "seed_id": it["seed_id"], "variant": it["variant"], "category": it["category"],
                    "task": it["task"], "result": it["result"], "accepted": why is None, "why": why,
                    "target_obj": target, "target": json.dumps(target, ensure_ascii=False) if target else None})
    return out


# ---------------------------------------------------------------- v2: a check before the verdict

# The teacher's copy of Chimera's reviewer request asks for a "check" first (teacher_prompts.CHECK_NOTE); the
# training example keeps Chimera's exact request, so the helper learns to check first unprompted. The schema
# asks Ollama to keep that key order where it can (gpt-oss doesn't always follow it, so the order and the
# check's form are also fixed here).
CHECK_SCHEMA = {"type": "object", "properties": {"check": {"type": "string"}, "done": {"type": "boolean"},
                                                 "score": {"type": "integer"}, "critique": {"type": "string"}},
                "required": ["check", "done", "score", "critique"]}
MAX_CHECK = 1500
# A "done" verdict whose own check marks something as failed.
_FAILED_MARK = re.compile(r"not met|✗|❌|✖|\bfails? to\b", re.I)


def _line(x):
    if isinstance(x, str):
        return x.strip()
    if isinstance(x, dict) and x and all(isinstance(v, (str, bool, int, float)) and not isinstance(v, dict) for v in x.values()):
        return " — ".join(str(v).strip() for v in x.values() if str(v).strip())
    return None


def normalize_check(v):
    """The check as one string, one line per requirement: gpt-oss sometimes writes it as a list of lines,
    a list of small objects, or an object of requirement: finding."""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list) and v:
        lines = [_line(x) for x in v]
        return "\n".join(l for l in lines if l) if all(l is not None for l in lines) else None
    if isinstance(v, dict) and v and all(isinstance(x, str) for x in v.values()):
        return "\n".join(f"{k.strip()}: {x.strip()}" for k, x in v.items())
    return None


def checked_target(obj):
    """The training target from a teacher reply: check first, then the verdict; the critique empty when done
    (as Chimera's prompt says). None if a piece is missing or the wrong type."""
    if not isinstance(obj, dict):
        return None
    check = normalize_check(obj.get("check"))
    done, score, crit = obj.get("done"), obj.get("score"), obj.get("critique")
    if isinstance(score, float) and score.is_integer():
        score = int(score)  # 85.0: Go would reject it, but the meaning is clear; the target gets 85
    if not check or not isinstance(done, bool) or isinstance(score, bool) or not isinstance(score, int) or not isinstance(crit, str):
        return None
    return {"check": check, "done": done, "score": score, "critique": "" if done else crit.strip()}


def _checked_body(models, teacher, item, p):
    from . import teacher_prompts as tp
    messages = cp.review_messages(item["task"], item["result"])
    messages = [dict(messages[0], content=messages[0]["content"] + tp.CHECK_NOTE)] + messages[1:]
    body = cp.chat_body("reviewer", teacher, messages)
    body["format"] = CHECK_SCHEMA
    body["options"].update(seed=stable_int("review2", item["key"], p), num_predict=5000)
    if models.teacher_think() is not None:
        body["think"] = models.teacher_think()
    return body


def run_checked(models, size, data_dir, teacher, log=None):
    """Stage reviews2: every review item (v1's and v2's), reviewed twice with a check first."""
    from .results import review_items2
    items = review_items2(data_dir, size)
    store = Store(os.path.join(data_dir, "raw", "reviews2.jsonl"))
    prog = Progress("reviews2", len(items), log)
    checked = both_valid = agree = 0
    tails = []
    for it in items:
        recs, new = [], False
        for p in range(PASSES):
            key = f"{it['key']}#p{p}"
            rec = store.get(key)
            if rec is None:
                call = models.call(_checked_body(models, teacher, it, p))
                target = None if call["error"] else checked_target(parse_obj(call["content"]))
                ok = target is not None and validate_review(json.dumps(target, ensure_ascii=False), require=("check",)).valid
                rec = {"key": key, "item_key": it["key"], "pass": p, "valid": bool(ok),
                       "done": target["done"] if target else None, "score": target["score"] if target else None,
                       "critique": target["critique"] if target else None, "check": target["check"] if target else None,
                       "reply": (call["content"] or "")[:6000], "error": call["error"], "wall_s": round(call["wall_s"] or 0, 2)}
                store.add(rec)
                new = True
            recs.append(rec)
        if not new:
            prog.step(it["key"], "done before", skipped=True)
            continue
        checked += 1
        ok_both = all(r["valid"] for r in recs)
        both_valid += ok_both
        agree += ok_both and len({r["done"] for r in recs}) == 1
        tails.append(recs[0]["reply"])
        verdicts = "/".join(("done" if r["done"] else "not done") if r["valid"] else "invalid" for r in recs)
        prog.step(f"{it['key']} [{it['variant']}]", verdicts, sum(r["wall_s"] for r in recs))
        sanity(data_dir, "reviews2", "items got two valid verdicts with a check", both_valid, checked, 0.7, size, tails)
        sanity(data_dir, "reviews2", "items got two agreeing verdicts", agree, checked, 0.5, size, tails)
    final_sanity(data_dir, "reviews2", "items got two valid verdicts with a check", both_valid, checked, 0.5, size, tails)
    return {"items": len(items), "accepted": sum(1 for j in judged_checked_reviews(data_dir) if j["accepted"])}


def judged_checked_reviews(data_dir):
    """Each v2 review item with the check-first training target it yields, or why it doesn't."""
    store = Store(os.path.join(data_dir, "raw", "reviews2.jsonl"))
    out = []
    for it in read_jsonl(os.path.join(data_dir, "review_items2.jsonl")):
        recs = [store.get(f"{it['key']}#p{p}") for p in range(PASSES)]
        why = None
        if any(r is None for r in recs):
            why = "not reviewed yet"
        elif not all(r["valid"] for r in recs):
            why = "invalid verdict"
        elif len({r["done"] for r in recs}) != 1:
            why = "passes disagree"
        elif it["expected_done"] is False and recs[0]["done"]:
            why = "known-broken result called done"
        elif recs[0]["done"] and _FAILED_MARK.search(recs[0]["check"]):
            why = "done, but its check marks something failed"
        elif len(recs[0]["check"]) > MAX_CHECK:
            why = "check too long"
        target = None
        if why is None:
            r = recs[0]
            target = {"check": r["check"], "done": r["done"], "score": r["score"], "critique": r["critique"]}
        out.append({"item_key": it["key"], "seed_id": it["seed_id"], "variant": it["variant"], "category": it["category"],
                    "task": it["task"], "result": it["result"], "accepted": why is None, "why": why,
                    "flaw_kind": it.get("flaw_kind"), "target_obj": target,
                    "target": json.dumps(target, ensure_ascii=False) if target else None})
    return out
