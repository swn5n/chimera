"""Stage 6: Head gate data. The teacher invents words-only Heads (never the eval set's), writes
messages of known types for each (half wanting the Head's result, half not), and answers each
through Chimera's exact gate request. Only messages whose answer matches their type are kept."""
from __future__ import annotations

import os
import re

from . import taxonomy as tx
from . import teacher_prompts as tp
from .common import Progress, Store, final_sanity, first_list, parse_obj, read_jsonl, rng, sanity, stable_int, write_jsonl

from helper import chimera_port as cp
from helper import evalset
from helper.validate import validate_gate
from tools.check_overlap import build_index, check_line

_ID = re.compile(r"[^a-z0-9]+")


def _clean_head(h):
    if not isinstance(h, dict):
        return None
    need = ("name", "summary", "when_to_use")
    if not all(isinstance(h.get(k), str) and h[k].strip() for k in need):
        return None
    hid = _ID.sub("-", str(h.get("id") or h["name"]).lower()).strip("-")[:40] or "head"
    tags = [t for t in (h.get("tags") or []) if isinstance(t, str)][:12]
    return {"id": hid, "name": h["name"].strip(), "summary": h["summary"].strip(), "when_to_use": h["when_to_use"].strip(),
            "when_not_to_use": (h.get("when_not_to_use") or "").strip() if isinstance(h.get("when_not_to_use"), str) else "",
            "tags": tags, "task_kinds": [], "accepts": [], "optional_input": False}


def run_heads(models, size, data_dir, teacher, log=None):
    store = Store(os.path.join(data_dir, "raw", "gate_head_calls.jsonl"))
    kinds = list(tx.HEAD_KINDS)
    rng("headkinds").shuffle(kinds)
    prog = Progress("heads", size["head_calls"], log)
    checked = good = 0
    tails = []
    for i in range(size["head_calls"]):
        key = f"heads-{i:03d}"
        if store.has(key):
            prog.step(key, "done before", skipped=True)
            continue
        kind = kinds[i % len(kinds)]
        k = size["heads_per_call"]
        messages = [{"role": "system", "content": tp.HEADS_SYSTEM}, {"role": "user", "content": tp.heads_user(k, kind)}]
        call = models.chat(teacher, messages, fmt="json", think=models.teacher_think(),
                           options={"seed": stable_int("heads", key), "num_ctx": 8192, "num_predict": 6000})
        heads = [h for h in map(_clean_head, first_list(parse_obj(call["content"]), "heads", lambda x: isinstance(x, dict))) if h]
        store.add({"key": key, "kind": kind, "heads": heads, "error": call["error"], "wall_s": round(call["wall_s"] or 0, 2),
                   "reply": None if heads else (call["content"] or "")[:3000]})
        checked += 1
        good += len(heads) >= max(1, k // 2)
        tails.append(call["content"])
        prog.step(key, f"{len(heads)}/{k} Heads", call["wall_s"])
        sanity(data_dir, "heads", "calls gave at least half the Heads asked for", good, checked, 0.7, size, tails)
    final_sanity(data_dir, "heads", "calls gave at least half the Heads asked for", good, checked, 0.5, size, tails)
    # Keep each Head once, and none of the eval set's.
    es = evalset.load()
    banned = {h["id"] for h in es.heads.values()} | {h["name"].lower() for h in es.heads.values()}
    heads, ids, names = [], set(), set()
    for rec in sorted(store.all(), key=lambda r: r["key"]):
        for h in rec["heads"]:
            if h["id"] in banned or h["name"].lower() in banned or h["name"].lower() in names:
                continue
            base, n = h["id"], 2
            while h["id"] in ids:
                h = dict(h, id=f"{base}-{n}")
                n += 1
            ids.add(h["id"])
            names.add(h["name"].lower())
            heads.append(dict(h, kind=rec["kind"]))
    write_jsonl(os.path.join(data_dir, "gate_heads.jsonl"), heads)
    return heads


def run_requests(models, size, data_dir, teacher, heads, log=None):
    store = Store(os.path.join(data_dir, "raw", "gate_request_calls.jsonl"))
    jobs = [(h, c) for h in heads for c in range(size["gate_calls_per_head"])]
    prog = Progress("gate messages", len(jobs), log)
    checked = good = 0
    tails = []
    for h, c in jobs:
        key = f"{h['id']}-{c}"
        if store.has(key):
            prog.step(key, "done before", skipped=True)
            continue
        language = rng("gatelang", key).choice(tx.OTHER_LANGUAGES)
        k = size["gate_per_call"]
        messages = [{"role": "system", "content": tp.GATE_SYSTEM},
                    {"role": "user", "content": tp.gate_user(k, h, language, tx.GATE_YES, tx.GATE_NO)}]
        call = models.chat(teacher, messages, fmt="json", think=models.teacher_think(),
                           options={"seed": stable_int("gatemsgs", key), "num_ctx": 8192, "num_predict": 6000})
        msgs = []
        for m in first_list(parse_obj(call["content"]), "messages", lambda x: isinstance(x, dict)):
            if isinstance(m, dict) and m.get("type") in {**tx.GATE_YES, **tx.GATE_NO} and isinstance(m.get("text"), str) \
                    and 3 <= len(m["text"].strip()) <= 3000:
                msgs.append({"type": m["type"], "text": m["text"].strip(), "label": m["type"] in tx.GATE_YES})
        store.add({"key": key, "head_id": h["id"], "language": language, "messages": msgs, "error": call["error"],
                   "wall_s": round(call["wall_s"] or 0, 2), "reply": None if msgs else (call["content"] or "")[:3000]})
        checked += 1
        good += len(msgs) >= max(1, k // 2)
        tails.append(call["content"])
        prog.step(key, f"{len(msgs)}/{k} messages", call["wall_s"])
        sanity(data_dir, "gate messages", "calls gave at least half the messages asked for", good, checked, 0.7, size, tails)
    final_sanity(data_dir, "gate messages", "calls gave at least half the messages asked for", good, checked, 0.5, size, tails)
    es = evalset.load()
    index = build_index(es, 8)
    out, seen = [], set()
    by_id = {h["id"]: h for h in heads}
    for rec in sorted(store.all(), key=lambda r: r["key"]):
        if rec["head_id"] not in by_id:
            continue
        for j, m in enumerate(rec["messages"]):
            norm = " ".join(m["text"].lower().split())
            if norm in seen or check_line(m["text"], es, index, 8, 0.3):
                continue
            seen.add(norm)
            reach, rel, _ = cp.reaches_gate(m["text"], by_id[rec["head_id"]])
            out.append({"req_id": f"{rec['key']}-{j:02d}", "head_id": rec["head_id"], "type": m["type"], "label": m["label"],
                        "text": m["text"], "reaches": reach, "relevance": rel})
    write_jsonl(os.path.join(data_dir, "gate_requests.jsonl"), out)
    return out


def run_answers(models, size, data_dir, teacher, heads, requests, log=None):
    store = Store(os.path.join(data_dir, "raw", "gate_answers.jsonl"))
    by_id = {h["id"]: h for h in heads}
    prog = Progress("gate answers", len(requests), log)
    checked = valid = agree = 0
    tails = []
    for q in requests:
        if store.has(q["req_id"]):
            prog.step(q["req_id"], "done before", skipped=True)
            continue
        messages = cp.gate_messages(by_id[q["head_id"]], q["text"])
        body = cp.chat_body("gate", teacher, messages)
        body["options"].update(seed=stable_int("gate", q["req_id"]), num_predict=3000)
        if models.teacher_think() is not None:
            body["think"] = models.teacher_think()
        call = models.call(body, timeout=120)
        res = validate_gate(call["content"])
        ok = bool(res.valid and not call["error"])
        store.add({"key": q["req_id"], "valid": ok, "use": bool(res.effective), "reply": (call["content"] or "")[:500],
                   "error": call["error"], "wall_s": round(call["wall_s"] or 0, 2)})
        checked += 1
        valid += ok
        agree += ok and bool(res.effective) == q["label"]
        tails.append(call["content"])
        prog.step(q["req_id"], ("use" if res.effective else "no") + f" (type says {'use' if q['label'] else 'no'})", call["wall_s"])
        sanity(data_dir, "gate answers", "answers were valid", valid, checked, 0.9, size, tails)
        sanity(data_dir, "gate answers", "answers matched the message type", agree, checked, 0.5, size, tails)
    final_sanity(data_dir, "gate answers", "answers were valid", valid, checked, 0.5, size, tails)
    return {"requests": len(requests), "kept": sum(1 for q in requests if (store.get(q["req_id"]) or {}).get("valid")
                                                   and store.get(q["req_id"])["use"] == q["label"])}


def run(models, size, data_dir, teacher, log=None):
    heads = run_heads(models, size, data_dir, teacher, log)
    requests = run_requests(models, size, data_dir, teacher, heads, log)
    return run_answers(models, size, data_dir, teacher, heads, requests, log)
