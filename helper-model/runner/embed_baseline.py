"""Zero-shot embedding check for the gate and for task kinds: nothing is trained, and no
threshold is picked on the eval set (AUC needs none), so the eval stays clean.

Gate: cosine similarity between the request (as an instructed query) and the Head's
description; AUC says how well that ranks right Heads above wrong ones. Kinds: the nearest of
five one-line kind descriptions, against the planner cases' acceptable kinds. A trained
classifier on top of the embeddings needs the synthetic training data first.
"""
from __future__ import annotations

import math
import time

from helper import chimera_port as cp

GATE_TASK = "Given a message someone sent to an AI assistant, retrieve the description of a tool that should make what they asked for"
KIND_TASK = "Given a task someone wants done, retrieve the kind of work it is"
KIND_DOCS = {
    "code": "Writing, fixing or testing software: code, scripts, apps, mods, programs and their tests.",
    "writing": "Writing prose: articles, blog posts, product copy, documentation, translations, descriptions.",
    "research": "Researching, comparing or analysing options and facts, then reporting findings or a recommendation.",
    "blender": "Building or changing a 3D scene in Blender with Python (bpy): objects, materials, lights, cameras, animation, geometry nodes.",
    "general": "Any other task: planning, organising, classifying or summarising information.",
}


def query(task, text):
    return f"Instruct: {task}\nQuery:{text}"  # the Qwen3-Embedding query format


def cosine(a, b):
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def auc(pos, neg):
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 4)


def run(client, model, es):
    t0 = time.monotonic()
    pairs = [(p, g, h) for p, g, h in es.gate_pairs() if g["confidence"] != "low"]
    reqs = sorted({p["prompt"] for p, _, _ in pairs})
    hids = sorted({h["id"] for _, _, h in pairs})
    qv = dict(zip(reqs, client.embed(model, [query(GATE_TASK, r) for r in reqs])))
    hv = dict(zip(hids, client.embed(model, [cp.head_description(es.heads[h]) for h in hids])))
    scored = [{"id": f"{p['id']}/{h['id']}", "use": g["use"], "cosine": round(cosine(qv[p["prompt"]], hv[h["id"]]), 4)}
              for p, g, h in pairs]
    cases = es.planner_cases()
    kinds = list(KIND_DOCS)
    kv = client.embed(model, [KIND_DOCS[k] for k in kinds])
    gv = client.embed(model, [query(KIND_TASK, c["prompt"]) for c in cases])
    detail = []
    for c, v in zip(cases, gv):
        sims = {k: cosine(v, kv[i]) for i, k in enumerate(kinds)}
        best = max(sims, key=sims.get)
        detail.append({"id": c["id"], "nearest": best, "ok": best in c["planner"]["kind"]})
    return {"gate_auc": auc([s["cosine"] for s in scored if s["use"]], [s["cosine"] for s in scored if not s["use"]]),
            "gate_pairs": len(scored), "kind_accuracy": round(sum(d["ok"] for d in detail) / len(detail), 4),
            "kind_cases": len(detail), "pairs": scored, "kinds": detail, "wall_s": round(time.monotonic() - t0, 3)}
