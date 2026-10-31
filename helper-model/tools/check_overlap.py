#!/usr/bin/env python3
"""Check a training file for leaks from the eval set before training on it.

    python3 tools/check_overlap.py train.jsonl [--field prompt] [--n 8] [--threshold 0.5]

Flags a training line that contains the eval set's canary string, repeats an eval text
(after lower-casing and squashing punctuation and spaces), or contains at least --threshold
of an eval text's word n-grams. Eval texts: prompts, chat histories, prior attempts and
critiques, review tasks and review results. Exit status 1 when anything is flagged.
Without --field, every string in the line is checked.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from helper import evalset  # noqa: E402

_WORD = re.compile(r"\w+", re.U)


def words(s):
    return _WORD.findall(s.lower())


def strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from strings(x)


def eval_texts(es):
    for p in es.prompts:
        yield p["id"], p["prompt"]
        for i, m in enumerate(p.get("history") or []):
            yield f"{p['id']}/history{i}", m["content"]
        if p.get("prior"):
            yield p["id"] + "/prior", p["prior"]
            yield p["id"] + "/critique", p["critique"]
    for r in es.reviews:
        yield r["id"] + "/task", r["task"]
        yield r["id"] + "/result", r["result"]


def build_index(es, n):
    grams, exact, sizes = defaultdict(set), {}, {}
    for eid, text in eval_texts(es):
        w = words(text)
        if len(w) < n:
            exact[" ".join(w)] = eid
            continue
        g = {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}
        sizes[eid] = len(g)
        for x in g:
            grams[x].add(eid)
    return grams, exact, sizes


def check_line(text, es, index, n, threshold):
    grams, exact, sizes = index
    hits = []
    if es.canary.split()[-1] in text:
        hits.append(("canary", 1.0))
    w = words(text)
    whole = " ".join(w)
    if whole in exact:
        hits.append((exact[whole], 1.0))
    counts = defaultdict(int)
    for x in {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}:
        for eid in grams.get(x, ()):
            counts[eid] += 1
    for eid, c in counts.items():
        frac = c / sizes[eid]
        if frac >= threshold:
            hits.append((eid, round(frac, 3)))
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("train", help="a JSONL file (or plain text, one example per line)")
    ap.add_argument("--field", help="the key that holds the text to check (default: every string in the line)")
    ap.add_argument("--n", type=int, default=8, help="n-gram length in words (default 8)")
    ap.add_argument("--threshold", type=float, default=0.5, help="share of an eval text's n-grams that counts as a copy")
    a = ap.parse_args(argv)
    es = evalset.load()
    index = build_index(es, a.n)
    flagged = total = 0
    with open(a.train, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                obj = json.loads(line)
                text = "\n".join(strings(obj.get(a.field) if a.field and isinstance(obj, dict) else obj))
            except ValueError:
                text = line
            hits = check_line(text, es, index, a.n, a.threshold)
            if hits:
                flagged += 1
                print(f"line {lineno}: " + ", ".join(f"{eid} ({frac:.0%})" for eid, frac in hits))
    print(f"{flagged} of {total} lines overlap the eval set ({es.version})" if flagged else f"no overlap with the eval set ({es.version}) in {total} lines")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
