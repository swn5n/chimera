"""Stage 1: seed requests, written by the teacher from short topic labels (never from the eval set),
then de-duplicated and checked against the eval set. Output: <data>/seeds.jsonl."""
from __future__ import annotations

import os
import re

from . import taxonomy as tx
from . import teacher_prompts as tp
from .common import Progress, Store, final_sanity, first_list, parse_obj, read_jsonl, rng, sanity, stable_int, weighted, write_jsonl

from helper import evalset
from tools.check_overlap import build_index, check_line


def _style(r):
    return weighted(r, tx.STYLES)


def _language(r):
    return weighted(r, tx.LANGUAGES)


def _length(r):
    pairs = [((d, paste), w) for d, w, paste in tx.LENGTHS]
    return weighted(r, pairs)


def build_call(cat, i, size):
    """The teacher request for seed call i of a category, and what it asked for."""
    r = rng("seedcall", cat, i)
    k = size["per_call"]
    language = _language(r)
    if cat == "small_task":
        kind = r.choice(tx.SMALL_KINDS)
        topic = r.choice(tx.TOPICS["coding"]["areas"] + tx.TOPICS["research_draft"]["areas"] + tx.TOPICS["blender"]["areas"])
        style = _style(r)
        user = tp.small_user(k, kind, topic, style, language)
        return [{"role": "system", "content": tp.SEED_SYSTEM}, {"role": "user", "content": user}], \
            {"kind": kind, "topic": topic, "style": style, "language": language, "k": k, "target": "small_task"}
    if cat == "followup":
        k = size["followup_per_call"]
        target = weighted(r, [("coding", 4), ("research_draft", 2), ("blender", 2), ("batch", 1), ("planning", 1)])
        topic = _topic(target, r)
        user = tp.followup_user(k, tx.CATEGORY_DESC[target], topic, language)
        return [{"role": "system", "content": tp.SEED_SYSTEM}, {"role": "user", "content": user}], \
            {"topic": topic, "language": language, "k": k, "target": target}
    topic = _topic(cat, r)
    style = _style(r)
    length, paste = _length(r)
    if cat == "coding" and any(w in topic for w in ("pasted code", "existing code")):
        length, paste = tx.LENGTHS[2][0], True
    extra = []
    if paste:
        extra.append("Put the pasted material inside the message text itself.")
    if cat == "batch":
        extra.append("Put the full list of items in each message.")
    user = tp.seed_user(k, tx.CATEGORY_DESC[cat], topic, style, length, language, extra)
    return [{"role": "system", "content": tp.SEED_SYSTEM}, {"role": "user", "content": user}], \
        {"topic": topic, "style": style, "length": length, "language": language, "k": k, "target": cat}


def _topic(cat, r):
    t = tx.TOPICS[cat]
    if cat == "coding":
        return f"{r.choice(t['langs'])}: {r.choice(t['areas'])}"
    if cat == "research_draft":
        return f"{r.choice(t['docs'])} about {r.choice(t['areas'])}"
    if cat == "batch":
        return f"{r.choice(t['ops'])}, for a list of {r.choice(t['items'])}"
    return r.choice(t["areas"])


def _texts(cat, obj):
    """The usable items in a teacher reply: [{"text", "history"}]."""
    out = []
    if not isinstance(obj, dict):
        return out
    if cat == "followup":
        for c in first_list(obj, "conversations", lambda x: isinstance(x, dict)):
            if not isinstance(c, dict):
                continue
            u, a, f = c.get("user"), c.get("assistant"), c.get("follow_up")
            if all(isinstance(x, str) and 10 <= len(x.strip()) <= 6000 for x in (u, a, f)):
                out.append({"text": f.strip(), "history": [{"role": "user", "content": u.strip()},
                                                           {"role": "assistant", "content": a.strip()}]})
        return out
    for m in first_list(obj, "messages", lambda x: isinstance(x, (str, dict))):
        if isinstance(m, dict):
            m = m.get("text") or m.get("message")
        if isinstance(m, str) and 15 <= len(m.strip()) <= 8000:
            out.append({"text": m.strip(), "history": None})
    return out


def run(models, size, data_dir, teacher, log=None):
    store = Store(os.path.join(data_dir, "raw", "seed_calls.jsonl"))
    calls = [(cat, i) for cat, n in size["seed_calls"].items() for i in range(n)]
    prog = Progress("seeds", len(calls), log)
    checked = good = 0
    replies = []
    for cat, i in calls:
        key = f"{cat}-{i:04d}"
        if store.has(key):
            prog.step(key, "done before", skipped=True)
            continue
        messages, params = build_call(cat, i, size)
        call = models.chat(teacher, messages, fmt="json", think=models.teacher_think(),
                           options={"seed": stable_int("seedcall", key), "num_ctx": 8192, "num_predict": 7000})
        items = _texts(cat, parse_obj(call["content"])) if not call["error"] else []
        store.add({"key": key, "category": cat, "params": params, "items": items, "error": call["error"],
                   "wall_s": round(call["wall_s"] or 0, 2), "reply": None if items else (call["content"] or "")[:4000]})
        checked += 1
        good += len(items) >= max(1, params["k"] // 2)
        replies.append(call["content"])
        prog.step(key, f"{len(items)}/{params['k']} usable" + (f" ERROR {call['error']}" if call["error"] else ""), call["wall_s"])
        sanity(data_dir, "seeds", "teacher replies had at least half the requests asked for", good, checked, 0.7, size, replies)
    final_sanity(data_dir, "seeds", "teacher replies had at least half the requests asked for", good, checked, 0.5, size, replies)
    return assemble(store, data_dir)


_WORDS = re.compile(r"\w+", re.U)


def shingles(s, n=5):
    w = _WORDS.findall(s.lower())
    return {tuple(w[i:i + n]) for i in range(max(1, len(w) - n + 1))}


def assemble(store, data_dir):
    """Flatten the teacher's replies into seeds: drop repeats, near-repeats and anything close to the eval set."""
    es = evalset.load()
    index = build_index(es, 8)
    kept, dropped, seen_exact, kept_sh = [], [], set(), []
    for rec in sorted(store.all(), key=lambda r: r["key"]):
        cat = rec["category"]
        target = rec["params"].get("target", cat)
        for j, it in enumerate(rec["items"]):
            sid = f"{rec['key']}-{j:02d}"
            text = it["text"]
            full = text + "\n" + "\n".join(m["content"] for m in it.get("history") or [])
            norm = " ".join(_WORDS.findall(text.lower()))
            why = None
            if norm in seen_exact:
                why = "repeat"
            else:
                sh = shingles(text)
                for other in kept_sh:
                    inter = len(sh & other)
                    if inter and inter / len(sh | other) >= 0.5:
                        why = "near-repeat"
                        break
            if why is None:
                hits = check_line(full, es, index, 8, 0.3)
                if hits:
                    why = "overlaps the eval set: " + ", ".join(h[0] for h in hits)
            seed = {"seed_id": sid, "category": target, "text": text, "history": it.get("history"),
                    "from": cat, "params": rec["params"]}
            if why:
                dropped.append(dict(seed, dropped=why))
                continue
            seen_exact.add(norm)
            kept_sh.append(shingles(text))
            kept.append(seed)
    write_jsonl(os.path.join(data_dir, "seeds.jsonl"), kept)
    write_jsonl(os.path.join(data_dir, "raw", "seeds_dropped.jsonl"), dropped)
    return {"seeds": len(kept), "dropped": len(dropped)}


# ---------------------------------------------------------------- v2: longer batches

def build_large_batch_call(i, size, gen=2):
    """A seed call for batch jobs with 8 to 15 items: v1 planned a 10-item batch as 10 steps (Chimera keeps 8)."""
    r = rng(f"seedcall{gen}", "batch_large", i)
    k = size["per_call"]
    language = _language(r)
    topic = _topic("batch", r)
    style = _style(r)
    length, paste = _length(r)
    extra = ["Put the full list of items in each message.", "Each list must have between 8 and 15 items."]
    if paste:
        extra.append("Put the pasted material inside the message text itself.")
    user = tp.seed_user(k, tp.BATCH_LARGE_DESC, topic, style, length, language, extra)
    return [{"role": "system", "content": tp.SEED_SYSTEM}, {"role": "user", "content": user}], \
        {"topic": topic, "style": style, "length": length, "language": language, "k": k, "target": "batch", "large": True}


def run_large_batches(models, size, data_dir, teacher, log=None):
    """Stage seeds2: seed requests for long batch jobs, kept apart from v1's seeds (seeds2.jsonl)."""
    store = Store(os.path.join(data_dir, "raw", "seed_calls2.jsonl"))
    n = size.get("batch_large_calls", 0)
    prog = Progress("seeds2", n, log)
    checked = good = 0
    replies = []
    for i in range(n):
        key = f"batch_large-{i:04d}"
        if store.has(key):
            prog.step(key, "done before", skipped=True)
            continue
        messages, params = build_large_batch_call(i, size)
        call = models.chat(teacher, messages, fmt="json", think=models.teacher_think(),
                           options={"seed": stable_int("seedcall2", key), "num_ctx": 8192, "num_predict": 7000})
        items = _texts("batch", parse_obj(call["content"])) if not call["error"] else []
        store.add({"key": key, "category": "batch", "params": params, "items": items, "error": call["error"],
                   "wall_s": round(call["wall_s"] or 0, 2), "reply": None if items else (call["content"] or "")[:4000]})
        checked += 1
        good += len(items) >= max(1, params["k"] // 2)
        replies.append(call["content"])
        prog.step(key, f"{len(items)}/{params['k']} usable" + (f" ERROR {call['error']}" if call["error"] else ""), call["wall_s"])
    final_sanity(data_dir, "seeds2", "teacher replies had at least half the requests asked for", good, checked, 0.5, size, replies)
    return assemble2(store, data_dir)


def assemble2(store, data_dir):
    """seeds2.jsonl: the new seeds, without repeats of each other or of v1's seeds, and not close to the eval set."""
    es = evalset.load()
    index = build_index(es, 8)
    old = read_jsonl(os.path.join(data_dir, "seeds.jsonl"))
    seen_exact = {" ".join(_WORDS.findall(s["text"].lower())) for s in old}
    kept_sh = [shingles(s["text"]) for s in old]
    kept, dropped = [], []
    for rec in sorted(store.all(), key=lambda r: r["key"]):
        for j, it in enumerate(rec["items"]):
            sid = f"{rec['key']}-{j:02d}"
            text = it["text"]
            norm = " ".join(_WORDS.findall(text.lower()))
            why = None
            if norm in seen_exact:
                why = "repeat"
            else:
                sh = shingles(text)
                if any((len(sh & o) and len(sh & o) / len(sh | o) >= 0.5) for o in kept_sh):
                    why = "near-repeat"
            if why is None and check_line(text, es, index, 8, 0.3):
                why = "overlaps the eval set"
            seed = {"seed_id": sid, "category": rec["category"], "text": text, "history": it.get("history"),
                    "from": "batch_large", "params": rec["params"]}
            if why:
                dropped.append(dict(seed, dropped=why))
                continue
            seen_exact.add(norm)
            kept_sh.append(shingles(text))
            kept.append(seed)
    write_jsonl(os.path.join(data_dir, "seeds2.jsonl"), kept)
    write_jsonl(os.path.join(data_dir, "raw", "seeds2_dropped.jsonl"), dropped)
    return {"seeds": len(kept), "dropped": len(dropped)}
