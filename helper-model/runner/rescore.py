#!/usr/bin/env python3
"""Re-score finished runs with the current validators and scoring, without calling a model.

    python3 runner/rescore.py --all
    python3 runner/rescore.py --all --to-current     # also move older runs onto the current eval version
    python3 runner/rescore.py results/runs/20261027-172116-qwen3-1.7b

Each run is scored against the eval set it ran on: eval/ if the version matches, otherwise
eval/archive/<version>/. With --to-current, a run from an older version is scored against the
current eval instead and relabelled with its version, but only when both versions send the
model exactly the same requests (a change to labels or scoring rules only). If any request
differs, the run has to be repeated, and it's left as it was. Rewrites the run's raw.jsonl
scores, summary.json and summary.md; the replies and timings are left as they were.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from helper import evalset  # noqa: E402
from runner import run_eval, scoring  # noqa: E402

JOBS = ("planner", "reviewer", "gate")


def eval_for(version, eval_dir=evalset.EVAL_DIR):
    cur = evalset.load(eval_dir)
    if cur.version == version:
        return cur
    arch = os.path.join(eval_dir, "archive", version)
    if not os.path.isdir(arch):
        raise SystemExit(f"no eval set for version {version} (looked in {eval_dir} and its archive/)")
    return evalset.load(arch)


def requests_of(es, variant=None):
    return {c["job"] + ":" + c["id"]: c["messages"] for c in run_eval.build_cases(es, JOBS, variant)}


def rescore(run_dir, eval_dir=evalset.EVAL_DIR, to_current=False):
    with open(os.path.join(run_dir, "summary.json"), encoding="utf-8") as f:
        doc = json.load(f)
    meta, old = doc["meta"], doc["summary"]
    es = eval_for(meta["eval_version"], eval_dir)
    if to_current:
        cur = evalset.load(eval_dir)
        if cur.version != es.version:
            if requests_of(es, meta.get("variant")) != requests_of(cur, meta.get("variant")):
                raise SystemExit(f"{os.path.basename(run_dir)}: eval {cur.version} asks the model different things "
                                 f"from {es.version}, so this run has to be repeated, not re-scored")
            meta.setdefault("rescored_from", meta["eval_version"])
            meta["eval_version"] = cur.version
            es = cur
            with open(os.path.join(run_dir, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
    cases = {c["job"] + ":" + c["id"]: c for c in run_eval.build_cases(es, JOBS, meta.get("variant"))}
    records = []
    raw = os.path.join(run_dir, "raw.jsonl")
    if os.path.exists(raw):
        with open(raw, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                c = cases[rec["job"] + ":" + rec["id"]]
                res = run_eval.validate(rec["job"], rec["reply"], meta.get("variant"))
                rec["validation"] = res.to_dict()
                rec["score"] = run_eval.score_case(c, res, {"error": rec.get("error")})
                records.append(rec)
        with open(raw, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    summary = scoring.aggregate(records)
    for k in ("embed", "embed_error"):
        if k in old:
            summary[k] = old[k]
    with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "summary": summary}, f, indent=2, ensure_ascii=False)
    with open(os.path.join(run_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(scoring.render_md(meta, summary, records))
    return len(records)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="*")
    ap.add_argument("--all", action="store_true", help="every finished run in results/runs/")
    ap.add_argument("--to-current", action="store_true", help="move runs on an older eval version onto the current one when the requests are identical")
    ap.add_argument("--eval-dir", default=evalset.EVAL_DIR)
    ap.add_argument("--from-version", help="with --to-current: only runs on this eval version")
    a = ap.parse_args(argv)
    runs = a.runs or []
    if a.all:
        runs = sorted(os.path.dirname(p) for p in glob.glob(os.path.join(HERE, "results", "runs", "*", "summary.json")))
    if not runs:
        ap.error("name a run folder, or pass --all")
    for r in runs:
        if a.from_version:
            with open(os.path.join(r, "summary.json"), encoding="utf-8") as f:
                if json.load(f)["meta"]["eval_version"] != a.from_version:
                    continue
        n = rescore(r, a.eval_dir, a.to_current)
        print(f"{os.path.basename(r.rstrip('/'))}: re-scored {n} replies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
