"""Stage 3: results for the reviewer to judge. Qwen workers answer seed tasks directly (good
and flawed answers come naturally from small models); some answers are then cut short, lose a
section, or get one deliberate flaw from the teacher, so the reviewer sees known failures too."""
from __future__ import annotations

import os
import re

from . import taxonomy as tx
from . import teacher_prompts as tp
from .common import WORKERS, Progress, Store, final_sanity, parse_obj, read_jsonl, rng, round_robin, sanity, stable_int, warn_if_low, write_jsonl


def review_tasks(seeds, size):
    planner = sorted((s for s in seeds if s["category"] in tx.PLANNER_CATS), key=lambda s: stable_int("rt", s["seed_id"]))
    small = sorted((s for s in seeds if s["category"] == "small_task"), key=lambda s: stable_int("rt", s["seed_id"]))
    return planner[:size["review_planner_tasks"]] + small[:size["review_small_tasks"]]


def worker_for(seed_id, workers=WORKERS):
    return workers[stable_int("worker", seed_id) % len(workers)]


def run_workers(models, size, data_dir, workers=WORKERS, log=None):
    seeds = read_jsonl(os.path.join(data_dir, "seeds.jsonl"))
    tasks = review_tasks(seeds, size)
    store = Store(os.path.join(data_dir, "raw", "results.jsonl"))
    ordered = [t for w in workers for t in tasks if worker_for(t["seed_id"], workers) == w]  # one model loaded at a time
    prog = Progress("results", len(ordered), log)
    checked = good = 0
    tails = []
    for t in ordered:
        sid = t["seed_id"]
        if store.has(sid):
            prog.step(sid, "done before", skipped=True)
            continue
        w = worker_for(sid, workers)
        long = t["category"] in tx.PLANNER_CATS
        messages = list(t.get("history") or []) + [{"role": "user", "content": t["text"]}]
        opts = {"seed": stable_int("result", sid), "num_ctx": 8192,
                "num_predict": size["worker_predict_long"] if long else size["worker_predict_small"]}
        call = models.chat(w, messages, think=False, options=opts)
        if call["error"] and "think" in call["error"].lower():  # a model that won't take the switch at all
            call = models.chat(w, messages, options=opts)
        text = call["content"] or ""
        store.add({"key": sid, "seed_id": sid, "worker": w, "category": t["category"], "result": text,
                   "done_reason": (call["stats"] or {}).get("done_reason"), "error": call["error"],
                   "wall_s": round(call["wall_s"] or 0, 2)})
        checked += 1
        good += bool(text.strip()) and not call["error"]
        tails.append(text or call["error"])
        prog.step(f"{sid} ({w})", f"{len(text)} chars" + (f" ERROR {call['error']}" if call["error"] else ""), call["wall_s"])
        sanity(data_dir, "results", "worker answers came back", good, checked, 0.8, size, tails)
    final_sanity(data_dir, "results", "worker answers came back", good, checked, 0.5, size, tails)
    return {"tasks": len(ordered), "results": len(store.all())}


# ---------------------------------------------------------------- deliberate failures

_MARK = re.compile(r"^\s{0,3}(#{1,6}\s|\d+[.)]\s|[-*]\s+\*\*)")


def truncate(text, r):
    """Cut a result at a line boundary 35-70% of the way through (a reply that stopped early)."""
    lines = text.split("\n")
    goal = len(text) * r.uniform(0.35, 0.7)
    out, n = [], 0
    for line in lines:
        if n + len(line) > goal and out:
            break
        out.append(line)
        n += len(line) + 1
    cut = "\n".join(out).rstrip()
    return cut if 100 <= len(cut) <= 0.85 * len(text) else None


def drop_section(text, r):
    """Remove one heading's section or one numbered/bold item (not the first): a part left out."""
    lines = text.split("\n")
    marks = [i for i, l in enumerate(lines) if _MARK.match(l)]
    if len(marks) < 3:
        return None
    k = r.randrange(1, len(marks))
    start = marks[k]
    end = marks[k + 1] if k + 1 < len(marks) else len(lines)
    removed = "\n".join(lines[start:end])
    if not (0.05 * len(text) <= len(removed) <= 0.5 * len(text)):
        return None
    return "\n".join(lines[:start] + lines[end:]).rstrip()


def _has_code(text):
    return "```" in text


def run_flaws(models, size, data_dir, teacher, log=None):
    """The teacher rewrites some worker answers with exactly one flaw of a given kind."""
    store = Store(os.path.join(data_dir, "raw", "flaws.jsonl"))
    seeds = {s["seed_id"]: s for s in read_jsonl(os.path.join(data_dir, "seeds.jsonl"))}
    # Results up to 6,000 characters, so task + result + rewrite fit Chimera's 8,192-token context
    # (one context size for every teacher call: changing it makes Ollama reload the 65 GB model).
    res = [r for r in Store(os.path.join(data_dir, "raw", "results.jsonl")).all()
           if _usable(r) and len(r["result"]) <= 6000 and r.get("done_reason") != "length"]
    pick = [r for r in sorted(res, key=lambda r: r["seed_id"]) if rng("flaw", r["seed_id"]).random() < size["flaw_frac"]]
    if len(pick) < size.get("min_flaws", 0):  # the smoke run always tries the teacher at least once
        rest = sorted((r for r in res if r not in pick), key=lambda r: stable_int("flawpad", r["seed_id"]))
        pick += rest[:size["min_flaws"] - len(pick)]
    prog = Progress("flaws", len(pick), log)
    checked = good = 0
    tails = []
    for r in pick:
        sid = r["seed_id"]
        if store.has(sid):
            prog.step(sid, "done before", skipped=True)
            continue
        rr = rng("flawkind", sid)
        kinds = [k for k, code in tx.FLAW_KINDS if _has_code(r["result"]) or not code]
        kind = rr.choice(kinds)
        messages = [{"role": "system", "content": tp.FLAW_SYSTEM},
                    {"role": "user", "content": tp.flaw_user(seeds[sid]["text"], r["result"], kind)}]
        call = models.chat(teacher, messages, fmt="json", think=models.teacher_think(),
                           options={"seed": stable_int("flawcall", sid), "num_ctx": 8192, "num_predict": 5000})
        obj = parse_obj(call["content"]) or {}
        resp, flaw = obj.get("response"), obj.get("flaw")
        ok = (isinstance(resp, str) and isinstance(flaw, str) and resp.strip() != r["result"].strip()
              and len(resp) >= 0.5 * len(r["result"]) and len(flaw.strip()) > 5)
        store.add({"key": sid, "seed_id": sid, "flaw_kind": kind, "ok": ok, "response": resp if ok else None,
                   "flaw": flaw if ok else None, "reply": None if ok else (call["content"] or "")[:3000],
                   "error": call["error"], "wall_s": round(call["wall_s"] or 0, 2)})
        checked += 1
        good += ok
        tails.append(call["content"])
        prog.step(sid, "ok" if ok else "unusable" + (f" ERROR {call['error']}" if call["error"] else ""), call["wall_s"])
    warn_if_low("flaws", "flawed copies were usable", good, checked, 0.5)
    return {"picked": len(pick), "usable": sum(1 for f in store.all() if f["ok"])}


def _usable(r):
    return not r["error"] and len((r["result"] or "").strip()) >= 20


def review_items(data_dir, size):
    """Every (task, result) pair the reviewer is asked about, with what a correct verdict must say
    when we know it (expected_done False for cut-off or deliberately broken results)."""
    seeds = {s["seed_id"]: s for s in read_jsonl(os.path.join(data_dir, "seeds.jsonl"))}
    flaws = {f["seed_id"]: f for f in Store(os.path.join(data_dir, "raw", "flaws.jsonl")).all() if f["ok"]}
    items = []
    for r in sorted(Store(os.path.join(data_dir, "raw", "results.jsonl")).all(), key=lambda r: r["seed_id"]):
        if not _usable(r) or r["seed_id"] not in seeds:
            continue
        sid, task, text = r["seed_id"], seeds[r["seed_id"]]["text"], r["result"]
        base = {"seed_id": sid, "task": task, "worker": r["worker"], "category": r["category"]}
        cut = r.get("done_reason") == "length"
        items.append(dict(base, key=f"{sid}:natural", variant="natural_cut" if cut else "natural", result=text,
                          expected_done=False if cut else None, flaw=None))
        if cut:
            continue
        rr = rng("variant", sid)
        if len(text) > 800 and rr.random() < size["truncate_frac"]:
            t = truncate(text, rr)
            if t:
                items.append(dict(base, key=f"{sid}:truncated", variant="truncated", result=t, expected_done=False,
                                  flaw="the result stops partway through"))
        if rr.random() < size["drop_frac"]:
            d = drop_section(text, rr)
            if d:
                items.append(dict(base, key=f"{sid}:dropped", variant="dropped_section", result=d, expected_done=False,
                                  flaw="a section or item is missing"))
        if sid in flaws:
            items.append(dict(base, key=f"{sid}:flaw", variant="teacher_flaw", result=flaws[sid]["response"],
                              expected_done=False, flaw=flaws[sid]["flaw"], flaw_kind=flaws[sid]["flaw_kind"]))
    write_jsonl(os.path.join(data_dir, "review_items.jsonl"), items)
    return items


# ---------------------------------------------------------------- v2: the teacher's own answers, more flaws

def answer_tasks(seeds, size):
    """Tasks for the teacher's own answers (mostly right, so the reviewer sees more work that is done): small tasks,
    which the workers answered too, and planner tasks the workers didn't get, spread over the categories."""
    used = {t["seed_id"] for t in review_tasks(seeds, size)}
    small = sorted((s for s in seeds if s["category"] == "small_task"), key=lambda s: stable_int("ta", s["seed_id"]))
    planner = sorted((s for s in seeds if s["category"] in tx.PLANNER_CATS and s["seed_id"] not in used),
                     key=lambda s: stable_int("ta", s["seed_id"]))
    planner = round_robin(planner, key=lambda s: s["category"])
    return small[:size.get("teacher_small", 0)] + planner[:size.get("teacher_planner", 0)]


def run_teacher_answers(models, size, data_dir, teacher, log=None):
    """Stage answers: the teacher answers tasks directly, as a worker would (no system prompt)."""
    seeds = read_jsonl(os.path.join(data_dir, "seeds.jsonl"))
    tasks = answer_tasks(seeds, size)
    store = Store(os.path.join(data_dir, "raw", "answers.jsonl"))
    prog = Progress("answers", len(tasks), log)
    checked = good = 0
    tails = []
    for t in tasks:
        sid = t["seed_id"]
        if store.has(sid):
            prog.step(sid, "done before", skipped=True)
            continue
        long = t["category"] in tx.PLANNER_CATS
        messages = list(t.get("history") or []) + [{"role": "user", "content": t["text"]}]
        # One context size for every teacher call (a change reloads the 65 GB model); the budget includes its reasoning.
        opts = {"seed": stable_int("answer", sid), "num_ctx": 8192, "num_predict": 5000 if long else 2500}
        call = models.chat(teacher, messages, think=models.teacher_think(), options=opts)
        text = call["content"] or ""
        store.add({"key": sid, "seed_id": sid, "worker": teacher, "category": t["category"], "result": text,
                   "done_reason": (call["stats"] or {}).get("done_reason"), "error": call["error"],
                   "wall_s": round(call["wall_s"] or 0, 2)})
        checked += 1
        good += bool(text.strip()) and not call["error"]
        tails.append(text or call["error"])
        prog.step(sid, f"{len(text)} chars" + (f" ERROR {call['error']}" if call["error"] else ""), call["wall_s"])
        sanity(data_dir, "answers", "teacher answers came back", good, checked, 0.8, size, tails)
    final_sanity(data_dir, "answers", "teacher answers came back", good, checked, 0.5, size, tails)
    return {"tasks": len(tasks), "answers": len(store.all())}


def _flaw2_kind(key, text):
    from .common import weighted
    kinds = [(k, w) for k, code, w in tx.FLAW_KINDS2 if _has_code(text) or not code]
    return weighted(rng("flawkind2", key), kinds)


def flaw2_candidates(data_dir, size):
    """Worker results v1 didn't flaw, and the teacher's answers, short enough for task + result + rewrite to
    fit the teacher's context, in a fixed order; the first size["flaws2"] are used."""
    v1 = {f["seed_id"] for f in Store(os.path.join(data_dir, "raw", "flaws.jsonl")).all()}
    out = []
    for source, name in (("worker", "results.jsonl"), ("teacher", "answers.jsonl")):
        for r in Store(os.path.join(data_dir, "raw", name)).all():
            if not _usable(r) or len(r["result"]) > 6000 or r.get("done_reason") == "length":
                continue
            if source == "worker" and r["seed_id"] in v1:
                continue
            out.append(dict(r, source=source, key=f"{source}:{r['seed_id']}"))
    out.sort(key=lambda r: stable_int("flaw2", r["key"]))
    return out[:size.get("flaws2", 0)]


def run_flaws2(models, size, data_dir, teacher, log=None):
    """Stage flaws2: one more round of flawed copies, mostly the kind you only see by checking."""
    store = Store(os.path.join(data_dir, "raw", "flaws2.jsonl"))
    seeds = {s["seed_id"]: s for s in read_jsonl(os.path.join(data_dir, "seeds.jsonl"))}
    pick = [r for r in flaw2_candidates(data_dir, size) if r["seed_id"] in seeds]
    prog = Progress("flaws2", len(pick), log)
    checked = good = 0
    for r in pick:
        key = r["key"]
        if store.has(key):
            prog.step(key, "done before", skipped=True)
            continue
        kind = _flaw2_kind(key, r["result"])
        messages = [{"role": "system", "content": tp.FLAW_SYSTEM},
                    {"role": "user", "content": tp.flaw_user(seeds[r["seed_id"]]["text"], r["result"], kind)}]
        call = models.chat(teacher, messages, fmt="json", think=models.teacher_think(),
                           options={"seed": stable_int("flawcall2", key), "num_ctx": 8192, "num_predict": 5000})
        obj = parse_obj(call["content"]) or {}
        resp, flaw = obj.get("response"), obj.get("flaw")
        ok = (isinstance(resp, str) and isinstance(flaw, str) and resp.strip() != r["result"].strip()
              and len(resp) >= 0.5 * len(r["result"]) and len(flaw.strip()) > 5)
        store.add({"key": key, "seed_id": r["seed_id"], "source": r["source"], "flaw_kind": kind, "ok": ok,
                   "response": resp if ok else None, "flaw": flaw if ok else None,
                   "reply": None if ok else (call["content"] or "")[:3000], "error": call["error"],
                   "wall_s": round(call["wall_s"] or 0, 2)})
        checked += 1
        good += ok
        prog.step(key, "ok" if ok else "unusable" + (f" ERROR {call['error']}" if call["error"] else ""), call["wall_s"])
    warn_if_low("flaws2", "flawed copies were usable", good, checked, 0.5)
    return {"picked": len(pick), "usable": sum(1 for f in store.all() if f["ok"])}


def review_items2(data_dir, size):
    """v1's review items, plus the teacher's answers and the second round of flawed copies (review_items2.jsonl)."""
    items = review_items(data_dir, size)
    seeds = {s["seed_id"]: s for s in read_jsonl(os.path.join(data_dir, "seeds.jsonl"))}
    for a in sorted(Store(os.path.join(data_dir, "raw", "answers.jsonl")).all(), key=lambda a: a["seed_id"]):
        if not _usable(a) or a["seed_id"] not in seeds:
            continue
        cut = a.get("done_reason") == "length"
        items.append({"seed_id": a["seed_id"], "task": seeds[a["seed_id"]]["text"], "worker": a["worker"],
                      "category": a["category"], "key": f"{a['seed_id']}:teacher", "variant": "teacher_cut" if cut else "teacher",
                      "result": a["result"], "expected_done": False if cut else None, "flaw": None})
    for f in sorted(Store(os.path.join(data_dir, "raw", "flaws2.jsonl")).all(), key=lambda f: f["key"]):
        if not f["ok"] or f["seed_id"] not in seeds:
            continue
        s = seeds[f["seed_id"]]
        items.append({"seed_id": f["seed_id"], "task": s["text"], "worker": f["source"], "category": s["category"],
                      "key": f"{f['seed_id']}:flaw2-{f['source']}", "variant": "flaw2_" + f["source"],
                      "result": f["response"], "expected_done": False, "flaw": f["flaw"], "flaw_kind": f["flaw_kind"]})
    write_jsonl(os.path.join(data_dir, "review_items2.jsonl"), items)
    return items
