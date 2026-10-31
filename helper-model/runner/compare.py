#!/usr/bin/env python3
"""Put finished runs side by side, case by case.

    python3 runner/compare.py 20261028-151235-chimera-helper-v1 20261028-002716-qwen3-4b-instruct-2507-q4_K_M
    python3 runner/compare.py --jobs reviewer results/runs/*check-first*

Each argument is a run folder (a path, or a name under results/runs/). Marks: ✗ = wrong (reviewer: the done
verdict; gate: the answer; planner: not strictly valid), with the score or quality next to it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(HERE, "results", "runs")


def load(run):
    d = run if os.path.isdir(run) else os.path.join(RUNS, run)
    with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    recs = {}
    with open(os.path.join(d, "raw.jsonl"), encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("sample", 0) == 0:
                recs[(r["job"], r["id"])] = r
    name = meta["model"] + (f" [{meta['variant']}]" if meta.get("variant") else "") + \
        (f" think={meta['think']}" if meta.get("think") not in (None, "unset") else "") + \
        (f" temp={meta['temperature']}" if meta.get("temperature") not in (None, "unset") else "")
    return name, meta, recs


def cell(job, s):
    if job == "reviewer":
        return f"{'done' if s['done'] else 'not'} {s['score'] if s['score'] is not None else '–'}{'' if s['done_ok'] else ' ✗'}"
    if job == "gate":
        return f"{'use' if s['use'] else 'no'}{'' if s['correct'] else ' ✗'}"
    return f"{s.get('steps', '–')} steps {s['quality']:.2f}{'' if s['valid'] else ' ✗'}"


def expected(job, r):
    s = r["score"]
    if job == "reviewer":
        return "done" if s["expected_done"] else "not done"
    if job == "gate":
        return "use" if s["expected"] else "no"
    return ""


def right(job, s):
    return s["done_ok"] if job == "reviewer" else (s["correct"] if job == "gate" else s["valid"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--jobs", default="planner,reviewer,gate")
    a = ap.parse_args(argv)
    runs = [load(r) for r in a.runs]
    for job in [j.strip() for j in a.jobs.split(",") if j.strip()]:
        ids = []
        for _, _, recs in runs:
            for (j, cid) in recs:
                if j == job and cid not in ids:
                    ids.append(cid)
        if not ids:
            continue
        if job == "gate":  # confident pairs only, like the scores (the label's confidence is the same in every run)
            def low(cid):
                r = next((recs[(job, cid)] for _, _, recs in runs if (job, cid) in recs), None)
                return bool(r) and r["score"].get("confidence") == "low"
            ids = [i for i in ids if not low(i)]
        print(f"## {job}\n")
        print("| case | expected | " + " | ".join(n for n, _, _ in runs) + " |")
        print("|---|---|" + "---|" * len(runs))
        totals = [[0, 0] for _ in runs]
        for cid in ids:
            first = next(recs[(job, cid)] for _, _, recs in runs if (job, cid) in recs)
            row = []
            for k, (_, _, recs) in enumerate(runs):
                r = recs.get((job, cid))
                if r is None:
                    row.append("–")
                    continue
                totals[k][0] += bool(right(job, r["score"]))
                totals[k][1] += 1
                row.append(cell(job, r["score"]))
            print(f"| {cid} | {expected(job, first)} | " + " | ".join(row) + " |")
        print("| **right** | | " + " | ".join(f"**{r}/{n}**" if n else "–" for r, n in totals) + " |\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
