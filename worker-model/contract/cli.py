#!/usr/bin/env python3
"""The contract prototype from the command line. Run from worker-model/:

    python3 -m contract.cli prompt PLAN.json 2 [--outputs OUT.json] [--goal G] [--prev RESULT.md --critique C] [--today]
    python3 -m contract.cli validate PIECE.md --mode blender --sid s2 [--deps s1] [--lone] [--done-reason length]
    python3 -m contract.cli join PLAN.json OUT.json --out DIR [--goal G]
    python3 -m contract.cli locate DIR/linemap.json CHECK.json [--script DIR/script.py]

PLAN.json is a plan as the planner wrote it (cleaned here as Chimera does). OUT.json maps each step's plan id to
its reply: a string, null for a failed step, or {"output": ..., "status": "library"}. STEP is 1-based or sN.
join writes result.md, join.json and, for Blender and Python plans, script.py and linemap.json; check script.py
with `chimera --check-result DIR/script.py > check.json`, then `locate` says which step crashed.
Exit status: validate 1 on errors, join 1 on a fallback, 0 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import prompt, today
from .goport import clean_plan
from .join import join
from .linemap import LineMap, locate_check
from .validate import validate_piece


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f) if path.endswith(".json") else f.read()


def _step(plan, s):
    i = int(s[1:] if s.lower().startswith("s") else s) - 1
    if not 0 <= i < len(plan["steps"]):
        raise SystemExit("no step %s: the plan has %d" % (s, len(plan["steps"])))
    return i


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prompt", help="print a worker request (contract, or today's with --today)")
    p.add_argument("plan")
    p.add_argument("step")
    p.add_argument("--outputs")
    p.add_argument("--goal", default="")
    p.add_argument("--prev", help="last round's result (round 2 on)")
    p.add_argument("--critique", default="")
    p.add_argument("--today", action="store_true", help="today's workerPrompt and runStep message instead")
    v = sub.add_parser("validate", help="check one piece")
    v.add_argument("piece")
    v.add_argument("--mode", required=True, choices=["blender", "python-script", "files", "section"])
    v.add_argument("--sid", default="s1")
    v.add_argument("--deps", default="", help="comma-separated, e.g. s1,s2")
    v.add_argument("--lone", action="store_true")
    v.add_argument("--done-reason", default="")
    j = sub.add_parser("join", help="join a plan's pieces")
    j.add_argument("plan")
    j.add_argument("outputs")
    j.add_argument("--out", required=True)
    j.add_argument("--goal", default="")
    lo = sub.add_parser("locate", help="which step a check's crash line is in")
    lo.add_argument("linemap")
    lo.add_argument("check")
    lo.add_argument("--script")
    a = ap.parse_args(argv)

    if a.cmd == "prompt":
        plan = clean_plan(_load(a.plan))
        outputs = _load(a.outputs) if a.outputs else {}
        i = _step(plan, a.step)
        if a.today:
            out = today.worker_messages(plan, i, outputs)
        else:
            prev = _load(a.prev) if a.prev else None
            out = prompt.worker_request(plan, i, outputs, goal=a.goal, prev_result=prev, critique=a.critique).to_dict()
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    if a.cmd == "validate":
        deps = [d.strip() for d in a.deps.split(",") if d.strip()]
        piece = validate_piece(_load(a.piece), a.mode, sid=a.sid, deps=deps, lone=a.lone, done_reason=a.done_reason)
        print(json.dumps(piece.to_dict(), indent=2, ensure_ascii=False))
        return 0 if piece.ok else 1
    if a.cmd == "join":
        plan = clean_plan(_load(a.plan))
        res = join(plan, _load(a.outputs), goal=a.goal)
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "join.json"), "w", encoding="utf-8") as f:
            json.dump(res.to_dict(), f, indent=2, ensure_ascii=False)
        if not res.fallback:
            with open(os.path.join(a.out, "result.md"), "w", encoding="utf-8") as f:
                f.write(res.text)
        if res.script:
            with open(os.path.join(a.out, "script.py"), "w", encoding="utf-8") as f:
                f.write(res.script)
            res.linemap.save(os.path.join(a.out, "linemap.json"))
        summary = {"fallback": res.fallback, "reasons": res.reasons, "seams": [s.message for s in res.seams],
                   "script": bool(res.script), "files": [f["path"] for f in res.files], "failed": res.failed,
                   "assumptions": res.assumptions_note()}
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 1 if res.fallback else 0
    if a.cmd == "locate":
        script = _load(a.script) if a.script else None
        print(json.dumps(locate_check(_load(a.check), LineMap.load(a.linemap), script), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
