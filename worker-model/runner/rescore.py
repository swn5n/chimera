#!/usr/bin/env python3
"""Score finished step runs again from their stored replies, with no model calls (after a scorer or validator fix).

    python3 runner/rescore.py results/runs/<run> [...]           # these runs
    python3 runner/rescore.py --tag baseline                      # every finished step run with the tag
    python3 runner/rescore.py --tag baseline --dry-run            # say what would change, write nothing

EVAL ONLY: it rescores model replies to eval cases; nothing in it is training data.

Each reply is scored as runner/step_eval.py scores it now (the validator, the word checks, the API lint, Blender).
Blender runs again only where the step's script is no longer the one that ran. A record scored since Oct 30 says
which script its results are for (score_step's script_sha); for an older one the script is rebuilt, today's way and
then the way it was built before Oct 30 (blender_run.script_for_step with call_build=False), and its stored results
are kept when a rebuild matches the stored record (run kind, line count, notes) and today's script is the same.
Everything else of a record (the reply, its stats and timings) is kept as it is. The old raw.jsonl, summary.json,
summary.md and meta.json go to data/rescore-backup/<stamp>/<run>/ first (an existing backup is never overwritten);
meta.json gets a "rescored" note (--note says what changed). Calls that failed outright stay as they were (there is
no reply to score). Run folders are taken once each, and only finished runs on the current eval version.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from runner import blender_run, score  # noqa: E402
from runner import cases as C  # noqa: E402
from runner.common import STEP_RUNS, now, read_json, rel, write_json  # noqa: E402
from runner.report import run_tag  # noqa: E402
from runner.step_eval import blender_from_args, lint_facts  # noqa: E402

import evalset  # noqa: E402

BACKUP = os.path.join(HERE, "data", "rescore-backup")


def read_records(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def run_cases(es, meta, frozen):
    """{case id: Case} for the run's cases, built as step_eval built them."""
    skipped = []
    cs = C.load_cases(es, meta.get("parts") or C.PARTS, meta.get("cases"), False, 0, frozen, skipped)
    return {c.id: c for c in cs}


def old_script(case, rec):
    """The script the stored Blender results were for (or its sha), or None when it can't be told for sure."""
    b = (rec.get("score") or {}).get("blender") or {}
    if not b.get("check"):
        return None
    if b.get("script_sha"):
        return b["script_sha"]
    found = set()
    for call_build in (True, False):
        kind, script, notes = blender_run.script_for_step(case.plan, case.index, case.outputs, rec.get("reply") or "",
                                                          case.goal, call_build=call_build)
        lines = script.count("\n") + 1 if script else 0
        if (kind, lines, notes) == (b.get("run"), b.get("lines"), b.get("notes")):
            found.add(script)
    return found.pop() if len(found) == 1 else None  # both rebuilds match but differ: can't tell which ran


def changes(before, after):
    """What a rescore changed in one record's verdicts, as short words."""
    out = []
    for key in ("contract_ok", "form_ok"):
        a, b = before["contract"].get(key), after["contract"].get(key)
        if a != b:
            out.append(f"{key} {a}->{b}")
    bb, ab = before.get("blender") or {}, after.get("blender") or {}
    if bb.get("run") != ab.get("run"):
        out.append(f"run {bb.get('run')}->{ab.get('run')}")
    for v in ("5.2.2", "5.0.1"):
        for what, get in (("strict", lambda x: (x.get("strict") or {}).get(v)),
                          ("outcome", lambda x: ((x.get("check") or {}).get(v) or {}).get("outcome")),
                          ("assertions", lambda x: ((x.get("probe") or {}).get(v) or {}).get("assert_fails"))):
            a, b = get(bb), get(ab)
            if a != b:
                out.append(f"{what} {v} {a}->{b}")
    a, b = (before.get("repair") or {}).get("fixed"), (after.get("repair") or {}).get("fixed")
    if a != b:
        out.append(f"repaired {a}->{b}")
    ea = all(x.get("ok") for x in (before.get("expect") or {}).values())
    eb = all(x.get("ok") for x in (after.get("expect") or {}).values())
    if ea != eb:
        out.append(f"expect {ea}->{eb}")
    return out


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def rescore_run(run_dir, es, a, blender, linter, stamp):
    run_dir = os.path.normpath(run_dir)
    meta = read_json(os.path.join(run_dir, "meta.json")) or {}
    records = read_records(os.path.join(run_dir, "raw.jsonl"))
    cs = run_cases(es, meta, a.frozen)
    out, reran, kept, changed, missing = [], 0, 0, [], []
    for rec in records:
        case = cs.get(rec["id"])
        if case is None or rec.get("score") is None and not (rec.get("error") or "").startswith("scoring failed"):
            if case is None:
                missing.append(rec["id"])
            out.append(rec)
            continue
        call = {"content": rec.get("reply") or "", "stats": rec.get("stats") or {}}
        old = rec.get("score")
        reuse = None
        if old and case.mode == "blender":
            s = old_script(case, rec)
            reuse = {"script": s, "blender": old.get("blender")} if s is not None else None
        if a.dry_run:  # no Blender: what the stored results can be kept for is scored in full, the rest without it
            new = score.score_step(case, rec["prompt"], call["content"], call, None, linter, reuse)
            b = new.get("blender") or {}
            held = bool(reuse and b.get("check") is not None and b.get("check") is (reuse["blender"] or {}).get("check"))
            if case.mode == "blender" and b.get("lines"):
                if held:
                    kept += 1
                else:
                    reran += 1
            if old:
                c = changes(old, new)
                if not held:
                    c = [x for x in c if x.startswith(("contract_ok", "form_ok", "run "))]
                if c:
                    changed.append(f"{rec['id']} s{rec['sample']}: " + ", ".join(c))
            out.append(rec)
            continue
        new = score.score_step(case, rec["prompt"], call["content"], call, blender, linter, reuse)
        if case.mode == "blender" and (new.get("blender") or {}).get("check"):
            if reuse and new["blender"].get("check") is (reuse["blender"] or {}).get("check"):
                kept += 1
            else:
                reran += 1
        if old:
            c = changes(old, new)
            if c:
                changed.append(f"{rec['id']} s{rec['sample']}: " + ", ".join(c))
        rec = dict(rec, score=new)
        if (rec.get("error") or "").startswith("scoring failed"):
            rec.pop("error")
            rec.pop("score_error", None)
        out.append(rec)
        print(f"  {rec['id']:16} s{rec['sample']} {score.brief(rec)}", file=sys.stderr)
    name = os.path.basename(run_dir)
    print(f"{name}: {len(records)} records, Blender {'would run' if a.dry_run else 'ran'} again for {reran}, "
          f"kept for {kept}; {len(changed)} changed" + (f"; {len(missing)} cases not found: {missing[:3]}" if missing else ""),
          file=sys.stderr)
    for c in changed:
        print("   ", c, file=sys.stderr)
    if a.dry_run:
        return
    bk = os.path.join(BACKUP, stamp, name)
    if os.path.exists(bk):
        raise SystemExit(f"error: the backup {rel(bk)} already exists; not overwriting it")
    os.makedirs(bk)
    for f in ("raw.jsonl", "summary.json", "summary.md", "meta.json"):
        if os.path.exists(os.path.join(run_dir, f)):
            shutil.copy2(os.path.join(run_dir, f), os.path.join(bk, f))
    meta.setdefault("rescored", []).append(
        f"{stamp}: rescored by runner/rescore.py ({a.note}); Blender ran again for {reran} replies, "
        f"{len(changed)} records changed; the old files are in {rel(bk)}")
    summary = score.aggregate(out)
    md = score.render_md(meta, summary, out)  # everything is made before anything is written
    write_atomic(os.path.join(run_dir, "raw.jsonl"), "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
    write_json(os.path.join(run_dir, "meta.json"), meta)
    write_json(os.path.join(run_dir, "summary.json"), {"meta": meta, "summary": summary})
    write_atomic(os.path.join(run_dir, "summary.md"), md)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="*", help="step run folders")
    ap.add_argument("--tag", help="every finished step run in --runs-dir whose tag starts with this")
    ap.add_argument("--runs-dir", default=STEP_RUNS)
    ap.add_argument("--frozen", default=C.FROZEN_DIR)
    ap.add_argument("--chimera", help="the Chimera binary for --check-result (default $CHIMERA_BIN)")
    ap.add_argument("--versions", help="Blender versions, comma-separated (default 5.2.2,5.0.1)")
    ap.add_argument("--blender", action="append", metavar="VERSION=PATH")
    ap.add_argument("--scratch", help="where Blender run folders go (default $WM_SCRATCH, else worker-model/data/scratch)")
    ap.add_argument("--dry-run", action="store_true", help="say what would change; run no Blender, write nothing")
    ap.add_argument("--note", default="the scorer and validator as they are now",
                    help="what changed, for meta.json's rescored note")
    a = ap.parse_args(argv)
    a.no_blender = a.dry_run
    es = evalset.load()
    runs = [os.path.normpath(r) for r in a.runs]
    if a.tag is not None:
        runs += [os.path.dirname(p) for p in sorted(glob.glob(os.path.join(a.runs_dir, "*", "meta.json")))
                 if run_tag(os.path.dirname(p), read_json(p) or {}).startswith(a.tag)]
    good, names = [], {}
    for d in dict.fromkeys(os.path.realpath(r) for r in runs):  # each run once
        m = read_json(os.path.join(d, "meta.json")) or {}
        why = ("no raw.jsonl" if not os.path.exists(os.path.join(d, "raw.jsonl")) else "not finished" if not
               m.get("finished") else f"eval {m.get('eval_version')}, not {es.version}" if m.get("eval_version") !=
               es.version else "a task run (T1)" if "arm" in m else "")
        if why:
            print(f"skipped {rel(d)}: {why}", file=sys.stderr)
        else:
            good.append(d)
            names.setdefault(os.path.basename(d), []).append(d)
    runs = good
    stamp = now().strftime("%Y%m%d-%H%M%S")
    clash = [n for n, ds in names.items() if len(ds) > 1] + \
        [os.path.basename(d) for d in runs if os.path.exists(os.path.join(BACKUP, stamp, os.path.basename(d)))]
    if clash and not a.dry_run:  # checked before anything is scored, so a batch never stops halfway
        print(f"error: backup names clash ({', '.join(sorted(set(clash)))}); rescore those runs separately",
              file=sys.stderr)
        return 2
    if not runs:
        ap.error("no runs (give run folders or --tag)")
    try:
        blender = blender_from_args(a)
    except RuntimeError as e:
        print("error:", e, file=sys.stderr)
        return 2
    linter = lint_facts()
    for d in runs:
        rescore_run(d, es, a, blender, linter, stamp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
