#!/usr/bin/env python3
"""Helpers for run_baselines.sh (tonight's A/B): which T1 tasks to run, and unloading models between runs.

    python3 -m runner.baselines t1 [--max-blender 12] [--max-code 10] [--frozen DIR]   # T1 task ids, one per line
    python3 -m runner.baselines unload --keep gpt-oss:120b,qwen3.8:27b [--host H]    # unload every other loaded model
    python3 -m runner.baselines loaded [--host H]                                    # what Ollama has loaded
    python3 -m runner.baselines quick-w1                                             # the quick subset's W1 tasks (a,b,c)
    python3 -m runner.baselines w1-cases [--frozen DIR]                              # how many quick W1 steps can run

EVAL ONLY: the task ids are the worker eval's W1 tasks (never training data).

T1 tonight (the plan's T1 is 30 tasks, 12 Blender, 10 code and 8 prose, with frozen plans; the eval doesn't list
them): the frozen W1 plans with a Blender step (up to --max-blender) and the python-script plans (up to --max-code),
the quick subset's tasks first within each kind, then the rest in the eval's order, and the two kinds alternated
(Blender, code, Blender, code, ...) so that every chunk the script runs holds both. Multi-file plans (a files step)
are left out: task_eval can't score them (Chimera's check doesn't run a project). Prose plans are left out tonight.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from runner import cases as C  # noqa: E402
from runner.common import Ollama, OllamaError, loaded_models  # noqa: E402

import evalset  # noqa: E402
from contract import planinfo  # noqa: E402


def task_kind(plan, goal=""):
    """"blender" (a Blender step), "python" (python-script steps, no files step), "files", or None (prose): the
    population task_eval scores the task in."""
    modes = {planinfo.step_mode(plan, i, goal) for i in range(len(plan["steps"]))}
    if "blender" in modes:
        return "blender"
    if "files" in modes:
        return "files"
    if "python-script" in modes:
        return "python"
    return None


def t1_tasks(es, frozen_dir=C.FROZEN_DIR, max_blender=12, max_code=10):
    """T1 tonight: frozen W1 task ids, Blender and python-script plans alternated (see the module docstring)."""
    plans, _ = C.load_frozen(frozen_dir)
    goals = C.task_goals(es)
    order = [c["id"] for c in es.cases("w1")] + es.helper_prompt_ids()
    quick = [t for t in es.quick.get("w1_tasks") or []]
    ranked = [t for t in quick if t in order] + [t for t in order if t not in quick]
    kinds = {"blender": [], "python": []}
    for t in ranked:
        plan = (plans.get(t) or {}).get("plan")
        if not plan:
            continue
        k = task_kind(plan, goals.get(t, ("",))[0])
        if k in kinds:
            kinds[k].append(t)
    bl, py = kinds["blender"][:max_blender], kinds["python"][:max_code]
    out = []
    for i in range(max(len(bl), len(py))):
        out += [x[i] for x in (bl, py) if i < len(x)]
    return out


def _name(m):
    return m if ":" in m else m + ":latest"


def unload_except(client, keep, wait=60.0, log=None):
    """Unload every model Ollama has loaded except keep (names; ":latest" assumed without a tag), and wait until
    /api/ps no longer lists them (so a 65 GB model is really gone before the next one loads). Returns the names
    unloaded."""
    keep = {_name(k) for k in keep}
    gone = sorted(m for m in loaded_models(client) if m and _name(m) not in keep)
    for m in gone:
        if log:
            log(f"unloading {m}")
        client.unload(m)
    deadline = time.monotonic() + wait
    while gone and time.monotonic() < deadline:
        if not set(gone) & loaded_models(client):
            break
        time.sleep(1.0)
    return gone


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t1 = sub.add_parser("t1", help="T1 task ids for tonight, one per line")
    t1.add_argument("--frozen", default=C.FROZEN_DIR)
    t1.add_argument("--max-blender", type=int, default=12)
    t1.add_argument("--max-code", type=int, default=10)
    sub.add_parser("quick-w1", help="the quick subset's W1 task ids, comma-separated")
    w1 = sub.add_parser("w1-cases", help="how many of the quick subset's W1 steps have their dependencies frozen")
    w1.add_argument("--frozen", default=C.FROZEN_DIR)
    for name in ("unload", "loaded"):
        p = sub.add_parser(name)
        p.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "127.0.0.1:11434"))
        if name == "unload":
            p.add_argument("--keep", default="", help="comma-separated models to leave loaded")
            p.add_argument("--wait", type=float, default=60.0)
    a = ap.parse_args(argv)
    if a.cmd == "t1":
        for t in t1_tasks(evalset.load(), a.frozen, a.max_blender, a.max_code):
            print(t)
        return 0
    if a.cmd == "quick-w1":
        print(",".join(evalset.load().quick.get("w1_tasks") or []))
        return 0
    if a.cmd == "w1-cases":
        print(len(C.load_cases(evalset.load(), parts=["w1"], quick=True, frozen_dir=a.frozen)))
        return 0
    client = Ollama(a.host, 60)
    try:
        client.version()
    except OllamaError as e:
        print("error:", e, file=sys.stderr)
        return 2
    if a.cmd == "loaded":
        for m in sorted(loaded_models(client)):
            print(m)
        return 0
    unload_except(client, [k.strip() for k in a.keep.split(",") if k.strip()], a.wait,
                  log=lambda s: print(s, file=sys.stderr))
    return 0


if __name__ == "__main__":
    sys.exit(main())
