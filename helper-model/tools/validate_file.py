#!/usr/bin/env python3
"""Filter a JSONL file of model replies with a job's validator (the training-data gate).

    python3 tools/validate_file.py --job planner plans.jsonl --keep kept.jsonl --reject rejected.jsonl
    python3 tools/validate_file.py --job gate answers.jsonl --field answer --max-warnings 0

Each line is a JSON object; --field (default "output") holds the reply, as text or as an
already parsed object. Kept lines must be strictly valid (helper/validate.py) and have no
more than --max-warnings warnings (-1, the default, ignores warnings). With --tidy, plans get
the format-only fixes first (step ids renamed s1..sN, missing depends_on filled with []), and
the kept line carries the tidied plan. Prints how many lines each issue code rejected.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from helper.validate import VALIDATORS, tidy_plan  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--job", required=True, choices=sorted(VALIDATORS))
    ap.add_argument("--field", default="output")
    ap.add_argument("--keep")
    ap.add_argument("--reject")
    ap.add_argument("--max-warnings", type=int, default=-1)
    ap.add_argument("--tidy", action="store_true", help="planner only: apply the format-only fixes before checking")
    a = ap.parse_args(argv)
    keep = open(a.keep, "w", encoding="utf-8") if a.keep else None
    reject = open(a.reject, "w", encoding="utf-8") if a.reject else None
    kept = total = 0
    why = Counter()
    with open(a.input, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            total += 1
            rec = json.loads(line)
            reply = rec.get(a.field)
            if a.tidy and a.job == "planner":
                obj = reply
                if isinstance(obj, str):
                    try:
                        obj = json.loads(obj)
                    except ValueError:
                        obj = None
                if isinstance(obj, dict):
                    reply = tidy_plan(obj)
            text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
            res = VALIDATORS[a.job](text)
            ok = res.valid and (a.max_warnings < 0 or len(res.warnings) <= a.max_warnings)
            if ok:
                kept += 1
                if keep:
                    out = dict(rec)
                    if a.tidy and a.job == "planner" and isinstance(reply, dict):
                        out[a.field] = reply
                    keep.write(json.dumps(out, ensure_ascii=False) + "\n")
            else:
                codes = sorted({i.code for i in res.errors} | ({i.code for i in res.warnings} if a.max_warnings >= 0 else set()))
                why.update(codes)
                if reject:
                    reject.write(json.dumps(dict(rec, _rejected=codes), ensure_ascii=False) + "\n")
    for fh in (keep, reject):
        if fh:
            fh.close()
    print(f"kept {kept} of {total}")
    for code, n in why.most_common():
        print(f"  {n:5}  {code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
