"""v3 (Oct 28 night): what v2's eval still missed, on top of v1's and v2's data (neither is changed).

- seeds3 + plans3: more batch jobs with 8 to 15 items, planned in 3 to 5 groups. v2 gave every item its own
  step from 8 items up, past Chimera's 7 (it keeps 8 and drops the rest).
- answers3: more of the teacher's own answers, so finished work stays about a third of the reviews.
- flaws3: more flawed copies of the kinds v2 still let through: a wrong value, a wrong count, a broken
  length limit, an ignored condition.
- reviews3: every review item reviewed again with checks that start from the task's requirements and redo
  the counts and calculations in the open (teacher_prompts.CHECK_NOTE3). Results known to be broken get one
  pass (it must say not done); the rest get two that must agree.
- build3: sft-v3/ and STATS-v3.md: v1's and v2's plans plus plans3, v1's gate examples, reviews3 only.
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict

from . import taxonomy as tx
from . import teacher_prompts as tp
from .build import _example, _pct, _q, collect, file_making_steps, write_split
from .common import (Progress, Store, final_sanity, parse_obj, read_jsonl, rng, round_robin, sanity, stable_int,
                     warn_if_low, weighted, write_jsonl)
from .plans import _hinted_body, judge_plan, plan_hints
from .results import _has_code, _usable, review_items2, review_tasks
from .reviews import _FAILED_MARK, CHECK_SCHEMA, checked_target
from .seeds import _WORDS, _texts, build_large_batch_call, shingles

from helper import chimera_port as cp
from helper import evalset
from helper.validate import validate_review
from tools.check_overlap import build_index, check_line

V3_DIR = "sft-v3"
MAX_CHECK3 = 2000  # v3's checks show their working, so they run longer than v2's


# ---------------------------------------------------------------- seeds3

def run_seeds3(models, size, data_dir, teacher, log=None):
    store = Store(os.path.join(data_dir, "raw", "seed_calls3.jsonl"))
    n = size.get("batch_large_calls3", 0)
    prog = Progress("seeds3", n, log)
    checked = good = 0
    replies = []
    for i in range(n):
        key = f"batch_large3-{i:04d}"
        if store.has(key):
            prog.step(key, "done before", skipped=True)
            continue
        messages, params = build_large_batch_call(i, size, gen=3)
        call = models.chat(teacher, messages, fmt="json", think=models.teacher_think(),
                           options={"seed": stable_int("seedcall3", key), "num_ctx": 8192, "num_predict": 7000})
        items = _texts("batch", parse_obj(call["content"])) if not call["error"] else []
        store.add({"key": key, "category": "batch", "params": params, "items": items, "error": call["error"],
                   "wall_s": round(call["wall_s"] or 0, 2), "reply": None if items else (call["content"] or "")[:4000]})
        checked += 1
        good += len(items) >= max(1, params["k"] // 2)
        replies.append(call["content"])
        prog.step(key, f"{len(items)}/{params['k']} usable" + (f" ERROR {call['error']}" if call["error"] else ""), call["wall_s"])
    final_sanity(data_dir, "seeds3", "teacher replies had at least half the requests asked for", good, checked, 0.5, size, replies)
    return assemble3(store, data_dir)


def assemble3(store, data_dir):
    """seeds3.jsonl: new seeds that repeat none of v1's or v2's, or each other, and aren't close to the eval set."""
    es = evalset.load()
    index = build_index(es, 8)
    old = read_jsonl(os.path.join(data_dir, "seeds.jsonl")) + read_jsonl(os.path.join(data_dir, "seeds2.jsonl"))
    seen = {" ".join(_WORDS.findall(s["text"].lower())) for s in old}
    sh_all = [shingles(s["text"]) for s in old]
    kept, dropped = [], []
    for rec in sorted(store.all(), key=lambda r: r["key"]):
        for j, it in enumerate(rec["items"]):
            text = it["text"]
            norm = " ".join(_WORDS.findall(text.lower()))
            sh = shingles(text)
            why = "repeat" if norm in seen else None
            if why is None and any(len(sh & o) and len(sh & o) / len(sh | o) >= 0.5 for o in sh_all):
                why = "near-repeat"
            if why is None and check_line(text, es, index, 8, 0.3):
                why = "overlaps the eval set"
            seed = {"seed_id": f"{rec['key']}-{j:02d}", "category": "batch", "text": text, "history": it.get("history"),
                    "from": "batch_large3", "params": rec["params"]}
            if why:
                dropped.append(dict(seed, dropped=why))
                continue
            seen.add(norm)
            sh_all.append(sh)
            kept.append(seed)
    write_jsonl(os.path.join(data_dir, "seeds3.jsonl"), kept)
    write_jsonl(os.path.join(data_dir, "raw", "seeds3_dropped.jsonl"), dropped)
    return {"seeds": len(kept), "dropped": len(dropped)}


# ---------------------------------------------------------------- plans3

def run_plans3(models, size, data_dir, teacher, log=None):
    """Every long-batch seed is planned with the grouping hint (in the teacher's copy only); a second try adds
    hints for whatever went wrong the first time."""
    seeds = read_jsonl(os.path.join(data_dir, "seeds3.jsonl"))
    store = Store(os.path.join(data_dir, "raw", "plans3.jsonl"))
    prog = Progress("plans3", len(seeds), log)
    checked = good = 0
    for s in seeds:
        messages = cp.planner_messages(s["text"], s.get("history"))  # Chimera's exact request: the training input
        last, new = None, False
        for k in range(2):
            key = f"{s['seed_id']}#g{k}"
            rec = store.get(key)
            if rec is None:
                hints = [tp.PLAN_HINTS["group"]]
                if last is not None:
                    hints += [h for h in plan_hints("batch", last["reasons"], (last.get("metrics") or {}).get("steps"))
                              if h not in hints and h != tp.PLAN_HINTS["too_many"]]
                call = models.call(_hinted_body(models, teacher, messages, hints, ("g", s["seed_id"], k)))
                if call["error"]:
                    ok, reasons, target, res = False, ["call_error"], None, None
                else:
                    ok, reasons, target, res = judge_plan("batch", call["content"])
                steps = len(json.loads(target)["steps"]) if ok else None
                if ok and not 3 <= steps <= 5:
                    ok, reasons, target = False, [f"steps:{steps}"], None  # the point is 3 to 5 groups
                rec = {"key": key, "seed_id": s["seed_id"], "attempt": k, "category": "batch", "source": "plan3",
                       "hints": hints, "new_seed": True, "accepted": ok, "reasons": reasons, "target": target,
                       "messages": messages if ok else None, "reply": None if ok else (call["content"] or "")[:6000],
                       "thinking_chars": len(call["thinking"] or ""), "wall_s": round(call["wall_s"] or 0, 2),
                       "error": call["error"], "metrics": (res.metrics if res is not None else None)}
                store.add(rec)
                new = True
            last = rec
            if rec["accepted"]:
                break
        if not new:
            prog.step(s["seed_id"], "done before", skipped=True)
            continue
        checked += 1
        good += bool(last["accepted"])
        prog.step(s["seed_id"], "accepted" if last["accepted"] else "rejected: " + ", ".join(last["reasons"]), last["wall_s"])
    warn_if_low("plans3", "plans were acceptable", good, checked, 0.4)
    return {"seeds": len(seeds), "accepted": len({r["seed_id"] for r in store.all() if r["accepted"]})}


# ---------------------------------------------------------------- answers3

def answer_tasks3(seeds, size, data_dir):
    """Tasks the teacher hasn't answered yet: small tasks, and planner tasks the workers didn't get either."""
    used = {t["seed_id"] for t in review_tasks(seeds, size)}
    done = {a["seed_id"] for a in Store(os.path.join(data_dir, "raw", "answers.jsonl")).all()}
    small = sorted((s for s in seeds if s["category"] == "small_task" and s["seed_id"] not in done),
                   key=lambda s: stable_int("ta3", s["seed_id"]))
    planner = sorted((s for s in seeds if s["category"] in tx.PLANNER_CATS and s["seed_id"] not in used | done),
                     key=lambda s: stable_int("ta3", s["seed_id"]))
    planner = round_robin(planner, key=lambda s: s["category"])
    return small[:size.get("teacher_small3", 0)] + planner[:size.get("teacher_planner3", 0)]


def run_answers3(models, size, data_dir, teacher, log=None):
    seeds = read_jsonl(os.path.join(data_dir, "seeds.jsonl"))
    tasks = answer_tasks3(seeds, size, data_dir)
    store = Store(os.path.join(data_dir, "raw", "answers3.jsonl"))
    prog = Progress("answers3", len(tasks), log)
    checked = good = 0
    tails = []
    for t in tasks:
        sid = t["seed_id"]
        if store.has(sid):
            prog.step(sid, "done before", skipped=True)
            continue
        long = t["category"] in tx.PLANNER_CATS
        messages = list(t.get("history") or []) + [{"role": "user", "content": t["text"]}]
        opts = {"seed": stable_int("answer3", sid), "num_ctx": 8192, "num_predict": 5000 if long else 2500}
        call = models.chat(teacher, messages, think=models.teacher_think(), options=opts)
        text = call["content"] or ""
        store.add({"key": sid, "seed_id": sid, "worker": teacher, "category": t["category"], "result": text,
                   "done_reason": (call["stats"] or {}).get("done_reason"), "error": call["error"],
                   "wall_s": round(call["wall_s"] or 0, 2)})
        checked += 1
        good += bool(text.strip()) and not call["error"]
        tails.append(text or call["error"])
        prog.step(sid, f"{len(text)} chars" + (f" ERROR {call['error']}" if call["error"] else ""), call["wall_s"])
        sanity(data_dir, "answers3", "teacher answers came back", good, checked, 0.8, size, tails)
    final_sanity(data_dir, "answers3", "teacher answers came back", good, checked, 0.5, size, tails)
    return {"tasks": len(tasks), "answers": len(store.all())}


# ---------------------------------------------------------------- flaws3

def flaw3_candidates(data_dir, size):
    """Results nobody has flawed yet (worker results, v2's and v3's teacher answers), short enough for the
    teacher's context, in a fixed order."""
    flawed = {f["seed_id"] for f in Store(os.path.join(data_dir, "raw", "flaws.jsonl")).all()}
    flawed2 = {f["key"] for f in Store(os.path.join(data_dir, "raw", "flaws2.jsonl")).all()}
    out = []
    for source, name in (("worker", "results.jsonl"), ("teacher", "answers.jsonl"), ("teacher3", "answers3.jsonl")):
        for r in Store(os.path.join(data_dir, "raw", name)).all():
            if not _usable(r) or len(r["result"]) > 6000 or r.get("done_reason") == "length":
                continue
            key = f"{source}:{r['seed_id']}"
            if (source == "worker" and r["seed_id"] in flawed) or key in flawed2:
                continue
            out.append(dict(r, source=source, key=key))
    out.sort(key=lambda r: stable_int("flaw3", r["key"]))
    return out[:size.get("flaws3", 0)]


def run_flaws3(models, size, data_dir, teacher, log=None):
    store = Store(os.path.join(data_dir, "raw", "flaws3.jsonl"))
    seeds = {s["seed_id"]: s for s in read_jsonl(os.path.join(data_dir, "seeds.jsonl"))}
    pick = [r for r in flaw3_candidates(data_dir, size) if r["seed_id"] in seeds]
    prog = Progress("flaws3", len(pick), log)
    checked = good = 0
    for r in pick:
        key = r["key"]
        if store.has(key):
            prog.step(key, "done before", skipped=True)
            continue
        kinds = [(k, w) for k, code, w in tx.FLAW_KINDS3 if _has_code(r["result"]) or not code]
        kind = weighted(rng("flawkind3", key), kinds)
        messages = [{"role": "system", "content": tp.FLAW_SYSTEM},
                    {"role": "user", "content": tp.flaw_user(seeds[r["seed_id"]]["text"], r["result"], kind)}]
        call = models.chat(teacher, messages, fmt="json", think=models.teacher_think(),
                           options={"seed": stable_int("flawcall3", key), "num_ctx": 8192, "num_predict": 5000})
        obj = parse_obj(call["content"]) or {}
        resp, flaw = obj.get("response"), obj.get("flaw")
        ok = (isinstance(resp, str) and isinstance(flaw, str) and resp.strip() != r["result"].strip()
              and len(resp) >= 0.3 * len(r["result"]) and len(flaw.strip()) > 5)  # a length flaw may shorten a lot
        store.add({"key": key, "seed_id": r["seed_id"], "source": r["source"], "flaw_kind": kind, "ok": ok,
                   "response": resp if ok else None, "flaw": flaw if ok else None,
                   "reply": None if ok else (call["content"] or "")[:3000], "error": call["error"],
                   "wall_s": round(call["wall_s"] or 0, 2)})
        checked += 1
        good += ok
        prog.step(key, "ok" if ok else "unusable" + (f" ERROR {call['error']}" if call["error"] else ""), call["wall_s"])
    warn_if_low("flaws3", "flawed copies were usable", good, checked, 0.5)
    return {"picked": len(pick), "usable": sum(1 for f in store.all() if f["ok"])}


# ---------------------------------------------------------------- reviews3

def review_items3(data_dir, size):
    """v2's review items, plus v3's teacher answers and flawed copies (review_items3.jsonl)."""
    items = review_items2(data_dir, size)
    seeds = {s["seed_id"]: s for s in read_jsonl(os.path.join(data_dir, "seeds.jsonl"))}
    for a in sorted(Store(os.path.join(data_dir, "raw", "answers3.jsonl")).all(), key=lambda a: a["seed_id"]):
        if not _usable(a) or a["seed_id"] not in seeds:
            continue
        cut = a.get("done_reason") == "length"
        items.append({"seed_id": a["seed_id"], "task": seeds[a["seed_id"]]["text"], "worker": a["worker"],
                      "category": a["category"], "key": f"{a['seed_id']}:teacher3", "variant": "teacher3_cut" if cut else "teacher3",
                      "result": a["result"], "expected_done": False if cut else None, "flaw": None})
    for f in sorted(Store(os.path.join(data_dir, "raw", "flaws3.jsonl")).all(), key=lambda f: f["key"]):
        if not f["ok"] or f["seed_id"] not in seeds:
            continue
        s = seeds[f["seed_id"]]
        items.append({"seed_id": f["seed_id"], "task": s["text"], "worker": f["source"], "category": s["category"],
                      "key": f"{f['seed_id']}:flaw3-{f['source']}", "variant": "flaw3_" + f["source"],
                      "result": f["response"], "expected_done": False, "flaw": f["flaw"], "flaw_kind": f["flaw_kind"]})
    write_jsonl(os.path.join(data_dir, "review_items3.jsonl"), items)
    return items


def passes3(item):
    return 1 if item["expected_done"] is False else 2


def _body3(models, teacher, item, p):
    messages = cp.review_messages(item["task"], item["result"])
    messages = [dict(messages[0], content=messages[0]["content"] + tp.CHECK_NOTE3)] + messages[1:]
    body = cp.chat_body("reviewer", teacher, messages)
    body["format"] = CHECK_SCHEMA
    body["options"].update(seed=stable_int("review3", item["key"], p), num_predict=5000)
    if models.teacher_think() is not None:
        body["think"] = models.teacher_think()
    return body


def run_reviews3(models, size, data_dir, teacher, log=None):
    items = review_items3(data_dir, size)
    store = Store(os.path.join(data_dir, "raw", "reviews3.jsonl"))
    prog = Progress("reviews3", len(items), log)
    checked = valid = agree = 0
    tails = []
    for it in items:
        recs, new = [], False
        for p in range(passes3(it)):
            key = f"{it['key']}#p{p}"
            rec = store.get(key)
            if rec is None:
                call = models.call(_body3(models, teacher, it, p))
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
        ok_all = all(r["valid"] for r in recs)
        valid += ok_all
        agree += ok_all and len({r["done"] for r in recs}) == 1
        tails.append(recs[0]["reply"])
        verdicts = "/".join(("done" if r["done"] else "not done") if r["valid"] else "invalid" for r in recs)
        prog.step(f"{it['key']} [{it['variant']}]", verdicts, sum(r["wall_s"] for r in recs))
        sanity(data_dir, "reviews3", "items got valid verdicts with a check", valid, checked, 0.7, size, tails)
        sanity(data_dir, "reviews3", "items got agreeing verdicts", agree, checked, 0.5, size, tails)
    final_sanity(data_dir, "reviews3", "items got valid verdicts with a check", valid, checked, 0.5, size, tails)
    return {"items": len(items), "accepted": sum(1 for j in judged_reviews3(data_dir) if j["accepted"])}


def judged_reviews3(data_dir):
    store = Store(os.path.join(data_dir, "raw", "reviews3.jsonl"))
    out = []
    for it in read_jsonl(os.path.join(data_dir, "review_items3.jsonl")):
        recs = [store.get(f"{it['key']}#p{p}") for p in range(passes3(it))]
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
        elif len(recs[0]["check"]) > MAX_CHECK3:
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


# ---------------------------------------------------------------- build3

def collect3(data_dir, notes):
    ex = [e for e in collect(data_dir, notes) if e["meta"]["job"] != "reviewer"]
    added = Counter()
    for name in ("plans2.jsonl", "plans3.jsonl"):
        for r in Store(os.path.join(data_dir, "raw", name)).all():
            if not r["accepted"]:
                continue
            steps = file_making_steps(json.loads(r["target"]))
            if steps and r["category"] != "coding":
                notes["file_steps_dropped"].append(steps[0])
                continue
            ex.append(_example("planner", r["seed_id"], r["messages"], r["target"], source=r["source"], category=r["category"],
                               hinted=bool(r["hints"]), new_seed=r["new_seed"]))
            added[r["source"]] += 1
    notes["plans_added"] = dict(added)
    for j in judged_reviews3(data_dir):
        if j["accepted"]:
            ex.append(_example("reviewer", j["seed_id"], cp.review_messages(j["task"], j["result"]), j["target"],
                               source="review3", variant=j["variant"], category=j["category"], done=j["target_obj"]["done"],
                               flaw_kind=j.get("flaw_kind")))
    return ex


def run_build3(data_dir, size=None):
    notes = {}
    examples = collect3(data_dir, notes)
    train, valid, leaked, broken = write_split(data_dir, examples, V3_DIR, "shuffle3", notes)
    return write_stats3(data_dir, train, valid, leaked, broken, notes)


def write_stats3(data_dir, train, valid, leaked, broken, notes):
    raw = lambda n: Store(os.path.join(data_dir, "raw", n)).all()  # noqa: E731
    allx = [e for e in train + valid if not e["meta"].get("repeat")]
    judged = judged_reviews3(data_dir)
    plans3, answers3, flaws3, reviews3 = raw("plans3.jsonl"), raw("answers3.jsonl"), raw("flaws3.jsonl"), raw("reviews3.jsonl")
    L = ["# Synthetic training data, v3", "",
         "What changed from v2 (`STATS-v2.md`, `sft-v2/`): every reviewer example was reviewed again with a check that "
         "first lists what the task requires and then verifies each requirement, redoing counts and calculations in the "
         "open (v2's helper wrote checks like \"each conversion correct\" without converting anything); more flawed "
         "copies of the kinds v2 let through; more of the teacher's own answers; and long batch jobs planned in 3 to 5 "
         "groups (v2 gave every item its own step). As before, everything was written by gpt-oss:120b or the Qwen "
         "workers, never by Claude, and checked against the eval set.", "",
         f"Training files: `{V3_DIR}/train.jsonl` ({len(train)} lines) and `{V3_DIR}/valid.jsonl` ({len(valid)}).", "",
         "## Examples", "", "| job | train | valid | detail |", "|---|---|---|---|"]
    for job in ("planner", "reviewer", "gate"):
        tr = sum(1 for e in train if e["meta"]["job"] == job and not e["meta"].get("repeat"))
        va = sum(1 for e in valid if e["meta"]["job"] == job)
        xs = [e["meta"] for e in allx if e["meta"]["job"] == job]
        if job == "planner":
            steps = Counter(len(json.loads(e["messages"][-1]["content"])["steps"]) for e in allx
                            if e["meta"]["job"] == "planner" and e["meta"]["category"] == "batch")
            det = ", ".join(f"{k} {v}" for k, v in sorted(Counter(m["category"] for m in xs).items())) + \
                  f"; from v2's hints {sum(1 for m in xs if m['source'] == 'plan2')}, long batches in groups " \
                  f"{sum(1 for m in xs if m['source'] == 'plan3')}; batch plans by steps: " + \
                  ", ".join(f"{k}: {v}" for k, v in sorted(steps.items()))
        elif job == "reviewer":
            d = Counter(m["done"] for m in xs)
            det = f"done {d[True]}, not done {d[False]}; " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(m["variant"] for m in xs).items()))
        else:
            u = Counter(m["use"] for m in xs)
            det = f"use {u[True]}, no {u[False]}"
        L.append(f"| {job} | {tr} | {va} | {det} |")
    rv_train = [e for e in train if e["meta"]["job"] == "reviewer"]
    L += ["", f"\"Done\" reviews appear {notes.get('done_repeat', 1)}x in train ({notes.get('done_repeated', 0)} repeats), "
          f"so they are {_pct(sum(1 for e in rv_train if e['meta']['done']), len(rv_train))} of the reviewer's lines. "
          f"Dropped at the end: {len(leaked)} too close to the eval set, {len(broken)} targets not strictly valid, "
          f"{notes.get('too_long', 0)} over about 7500 tokens.", ""]
    checks = [len(j["target_obj"]["check"]) for j in judged if j["accepted"]]
    rv_why = Counter(j["why"] for j in judged if not j["accepted"])
    acc_by = defaultdict(lambda: [0, 0])
    for j in judged:
        acc_by[j["variant"]][1] += 1
        acc_by[j["variant"]][0] += j["accepted"]
    done_by = Counter(j["variant"] for j in judged if j["accepted"] and j["target_obj"]["done"])
    p3 = {}
    for r in plans3:
        p3.setdefault(r["seed_id"], []).append(r)
    kinds = "; ".join(f"{k.split(':')[0][:50]} {v}" for k, v in Counter(f["flaw_kind"] for f in flaws3 if f["ok"]).most_common())
    L += ["## Stages", "",
          f"- Long-batch seeds: {len(read_jsonl(os.path.join(data_dir, 'seeds3.jsonl')))} kept; "
          f"{sum(1 for rs in p3.values() if any(r['accepted'] for r in rs))} of {len(p3)} planned in 3 to 5 groups.",
          f"- The teacher's own answers: {len(answers3)} more ({sum(1 for a in answers3 if a.get('done_reason') == 'length')} hit the length cap).",
          f"- Flawed copies: {sum(1 for f in flaws3 if f['ok'])} of {len(flaws3)} usable "
          f"({kinds}).",
          f"- Reviews with worked checks: {len(judged)} items, {sum(1 for j in judged if j['accepted'])} accepted; rejected: "
          f"{', '.join(f'{k} {v}' for k, v in rv_why.most_common()) or 'none'}. Checks: median {_q(checks, 0.5)} characters, "
          f"95th percentile {_q(checks, 0.95)}.", "",
          "| review material | accepted | of which done |", "|---|---|---|"]
    for v, (a, n) in sorted(acc_by.items()):
        L.append(f"| {v} | {a}/{n} ({_pct(a, n)}) | {done_by.get(v, 0)} |")
    wall = {"seeds3": raw("seed_calls3.jsonl"), "plans3": plans3, "answers3": answers3, "flaws3": flaws3, "reviews3": reviews3}

    def dur(v):
        s = sum(r.get("wall_s") or 0 for r in v)
        return f"{s / 3600:.1f} h" if s >= 3600 else f"{s / 60:.0f} min"
    L += ["", "Model time spent: " + ", ".join(f"{k} {dur(v)}" for k, v in wall.items()), ""]
    with open(os.path.join(data_dir, "STATS-v3.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    jobs = Counter(e["meta"]["job"] for e in allx)
    return {"train": len(train), "valid": len(valid), "by_job": dict(jobs), "leaked": len(leaked), "broken": len(broken),
            "done_repeat": notes.get("done_repeat")}
