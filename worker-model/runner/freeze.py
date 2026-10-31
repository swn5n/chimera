#!/usr/bin/env python3
"""Freeze W1's plans and dependency outputs into eval/frozen/, so every model is scored on the same steps.

    python3 runner/freeze.py --dry-run                 # what it would ask, and what is frozen already; calls nothing
    python3 runner/freeze.py --what plans              # plans only (hydra:1.0, about 4 s each)
    python3 runner/freeze.py                           # plans, then dependency outputs (gpt-oss:120b: hours)
    python3 runner/freeze.py --tasks bw-01,code-03     # only these tasks

EVAL ONLY: everything it writes is eval data (eval/frozen/plans.json and deps.json carry the worker eval's canary
and an EVAL ONLY note); never train on it. Meant for a run with the Studio not lending (gpt-oss:120b is 65 GB).

Plans: Chimera's exact planner request (onePass, app/hydra.go, through helper-model's chimera_port: the planner
prompt, the task, any chat history and round-2 parts, format "json", num_ctx from historyTokens + 2048) on
hydra:1.0. As in onePass, a plan Chimera can't read is asked once more on the fallback planner (gpt-oss:120b). The
plan freezes after cleanPlan. About 10 tasks are planned on gpt-oss:120b directly, as the plan asks: the cases
that name a planner ("freeze_planner" in the case), else --gpt-oss-plans of them picked by a fixed rule (spread
over the task groups, ordered by the sha256 of the id), recorded in plans.json.

Dependency outputs: for every step another step depends on, gpt-oss:120b answers the contract's request
(contract/prompt.py) with the dependencies it uses already frozen, in plan order. A reply is kept only if
verified (up to --tries; Blender gets --tries-blender):
- every mode: the validator passes (contract kept, not cut off, at most 3,500 tokens);
- blender: no API lint errors, a strict pass alone (join.alone_script) and joined with its frozen dependencies in
  5.2.2 and 5.0.1 (Chimera's check and the whole output of the direct run, blender_run.counted_strict), and the
  joined run prints no stand-in and leaves no .001 duplicates (both read from the direct run's whole output);
- python-script and files: joined with its dependencies without a syntax error or a file conflict.
A step with no verified reply is frozen as "rejected" (its dependents are skipped in W1). --today-deps N also
freezes N dependency outputs from qwen3.8:27b under today's prompt (no handoff), for the mixed-pool cases.

Resumable: plans.json and deps.json are rewritten after every plan and every step; a rerun skips what is there
(--retry-rejected asks rejected steps again; a task whose plan changed starts its outputs over).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from runner import blender_run  # noqa: E402
from runner import cases as C  # noqa: E402
from runner.common import (CHIMERA_VERSION, OllamaError, ask, call_fields, chat_body, helper_port,  # noqa: E402
                           loaded_models, model_info, now, read_json, rel, runaway, runaway_in, write_json)
from runner.step_eval import add_common_args, blender_from_args, lint_facts, make_client  # noqa: E402

import evalset  # noqa: E402
from contract import planinfo, prompt as cprompt, today  # noqa: E402
from contract.join import alone_script, join  # noqa: E402
from contract.validate import validate_piece  # noqa: E402

PLANNER = "hydra:1.0"
FALLBACK_PLANNER = "gpt-oss:120b"
TEACHER = "gpt-oss:120b"
TODAY_MODEL = "qwen3.8:27b"
NOTE = ("EVAL ONLY, never training data. Frozen by worker-model/runner/freeze.py from model replies to the worker "
        "eval's W1 tasks (Claude-written eval prompts and helper-model's eval prompts); training on it would make the "
        "eval meaningless.")


def doc(part, version):
    """An empty eval/frozen/ file: the worker eval's version, canary and EVAL ONLY note, like every eval file."""
    return {"version": version, "canary": evalset.CANARY, "note": NOTE, "part": part, "made_by": "runner/freeze.py",
            "meta": {}, "items": []}


def group(tid):
    return tid.split("-")[0]  # code, res, bl, batch, bw


def gpt_oss_tasks(task_ids, cases_say, n):
    """Which tasks are planned on gpt-oss:120b: those whose case says so, then n in all picked by a fixed rule:
    round-robin over the task groups, each group ordered by the sha256 of the id."""
    chosen = [t for t in task_ids if cases_say.get(t) == FALLBACK_PLANNER]
    groups = {}
    for t in sorted(task_ids, key=lambda x: hashlib.sha256(x.encode()).hexdigest()):
        if t not in chosen and t not in cases_say:
            groups.setdefault(group(t), []).append(t)
    names = sorted(groups)
    k = 0
    while len(chosen) < n and any(groups.values()):
        g = groups[names[k % len(names)]]
        if g:
            chosen.append(g.pop(0))
        k += 1
    return chosen


def planner_request(cp, goal, history, prior, critique, model):
    msgs = cp.planner_messages(goal, history, prior, critique)
    return cp.chat_body("planner", model, msgs)


def freeze_plan(cp, client, tid, goal, history, prior, critique, model, fallback, timeout):
    """One plan as onePass gets it. Returns the plans.json item (with "plan": None when no planner gave one)."""
    tries = []
    for m in [model] + ([fallback] if fallback and fallback != model else []):
        body = planner_request(cp, goal, history, prior, critique, m)
        call = ask(client, body, timeout, attempts=1)
        ok, plan, _ = cp.extract_json(call["content"] or "", cp.PLAN_SPEC) if not call["error"] else (False, None, None)
        ok = ok and bool(plan and plan.get("steps"))
        t = {"model": m, "ok": ok, "options": body["options"], "reply": call["content"]}
        t.update(call_fields(call))
        tries.append(t)
        if ok:
            clean = cp.clean_plan(plan)
            # keep only the plan's own fields (cleanPlan's status and Go's zero values for the rest aren't the plan)
            clean = {"title": clean["title"], "kind": clean["kind"], "summary": clean["summary"],
                     "steps": [{"id": s["id"], "title": s["title"], "kind": s["kind"], "instructions": s["instructions"],
                                "depends_on": list(s["depends_on"] or [])} for s in clean["steps"]]}
            return {"id": tid, "planner_model": m, "asked_first": model, "plan": clean, "tries": tries,
                    "frozen_on": now().date().isoformat()}
    return {"id": tid, "planner_model": None, "asked_first": model, "plan": None, "tries": tries,
            "frozen_on": now().date().isoformat()}


def needed_steps(plan):
    """Plan ids of the steps some other step depends on (their outputs are W1's inputs), in plan order."""
    used = {d for s in plan["steps"] for d in s.get("depends_on") or []}
    return [s["id"] for s in plan["steps"] if s["id"] in used]


def verify(plan, i, reply, outputs, call, goal, blender, linter):
    """(kept, verdict) for one dependency reply under the contract (outputs: the frozen dependencies)."""
    st = plan["steps"][i]
    mode = planinfo.step_mode(plan, i, goal)
    piece = validate_piece(reply or "", mode, sid="s%d" % (i + 1), deps=planinfo.dep_names(plan, i),
                           lone=len(plan["steps"]) == 1, step=st,
                           done_reason=(call.get("stats") or {}).get("done_reason") or "")
    v = {"mode": mode, "validator": sorted({x.code for x in piece.errors})}
    if not piece.ok:
        return False, v
    deps = {d: outputs[d] for d in (st.get("depends_on") or []) if outputs.get(d)}
    j = join(plan, dict(deps, **{st["id"]: reply}), goal=goal)
    if j.fallback:
        v["join"] = j.reasons[:3]
        return False, v
    if mode in ("python-script", "files"):
        bad = [s.code for s in j.seams if s.code in ("join_syntax", "file_conflict", "import_unresolved", "duplicate_name")]
        v["seams"] = bad
        return not bad, v
    if mode != "blender":
        return True, v
    if linter is not None:
        errs = [x for x in linter.lint(piece.code) if x["level"] == "error"]
        v["lint_errors"] = len(errs)
        if errs:
            return False, v
    if blender is None:
        v["blender"] = "not run"
        return False, v
    # Both runs of each (blender_run.Blender.run): Chimera's check, and the direct run, whose whole output is kept.
    # Strict needs both (blender_run.counted_strict), and the stand-in and .001 duplicates come from the direct run:
    # the check shows only the last 1,500 characters of output, where an early stand-in line is long gone.
    alone, joined = blender.run(alone_script(piece)), blender.run(j.script)
    v["alone"] = {k: blender_run.counted_strict(r, alone["probe"].get(k)) for k, r in alone["check"].items()}
    v["joined"] = {k: blender_run.counted_strict(r, joined["probe"].get(k)) for k, r in joined["check"].items()}
    stand_in = any(r.get("stand_in") for r in joined["probe"].values()) and len(deps) == len(st.get("depends_on") or [])
    dupes = sorted({d for r in joined["probe"].values() for d in r.get("dupes") or []})
    v["joined_stand_in"], v["dupes"] = stand_in, dupes
    return all(v["alone"].values()) and all(v["joined"].values()) and not stand_in and not dupes, v


def freeze_deps(item, dep_doc_item, client, teacher, tries, tries_blender, goal, prior, critique, blender, linter,
                timeout, save, retry_rejected=False):
    """Freeze the needed steps of one plan, in plan order, saving after each one."""
    plan = item["plan"]
    steps = dep_doc_item["steps"]
    for sid_ in needed_steps(plan):
        if sid_ in steps and (steps[sid_]["status"] == "verified" or not retry_rejected):
            continue
        i = next(k for k, s in enumerate(plan["steps"]) if s["id"] == sid_)
        st = plan["steps"][i]
        if any((steps.get(d) or {}).get("status") != "verified" for d in st.get("depends_on") or []):
            steps[sid_] = {"status": "rejected", "why": "a dependency has no verified output", "tries": 0}
            save()
            continue
        outputs = {d: steps[d]["reply"] for d in st.get("depends_on") or []}
        mode = planinfo.step_mode(plan, i, goal)
        n = tries_blender if mode == "blender" else tries
        attempts = []
        kept = None
        for _ in range(n):
            r = cprompt.worker_request(plan, i, outputs, goal=goal, prev_result=prior, critique=critique)
            body = chat_body(teacher, r.messages, r.need_ctx, 0)
            call = ask(client, body, timeout, worker=True)
            if runaway(call):  # cut at the reply cap: a rejected try of its own, never verified
                ok, verdict = False, {"mode": mode, "runaway": (call.get("stats") or {}).get("runner_limit"),
                                      "runaway_in": runaway_in(call)}
            elif call["error"]:
                attempts.append({"error": call["error"]})
                continue
            else:
                ok, verdict = verify(plan, i, call["content"], outputs, call, goal, blender, linter)
            a = {"kept": ok, "verdict": verdict}
            a.update({k: v for k, v in call_fields(call).items() if k in ("stats", "wall_s", "done_reason", "tok_s")})
            attempts.append(a)
            print(f"  {item['id']} {sid_} ({mode}): {'kept' if ok else 'rejected'} {json.dumps(verdict)[:160]}", file=sys.stderr)
            if ok:
                kept = call["content"]
                break
        steps[sid_] = {"status": "verified" if kept else "rejected", "model": teacher, "mode": mode,
                       "reply": kept, "tries": len(attempts), "attempts": attempts,
                       "frozen_on": now().date().isoformat()}
        save()


def freeze_today(item, dep_item, client, model, goal, blender, timeout, save):
    """One today's-format output (no handoff) for the first needed step whose own dependencies are verified."""
    plan, steps = item["plan"], dep_item["steps"]
    for sid_ in needed_steps(plan):
        s = steps.get(sid_) or {}
        if s.get("status") != "verified" or s.get("today"):
            continue
        i = next(k for k, x in enumerate(plan["steps"]) if x["id"] == sid_)
        outputs = {d: C.strip_handoff(steps[d]["reply"]) for d in plan["steps"][i].get("depends_on") or []}
        r = today.worker_messages(plan, i, outputs)
        call = ask(client, chat_body(model, r["messages"], r["need_ctx"], 0), timeout, worker=True)
        ok = not call["error"] and (call.get("stats") or {}).get("done_reason") != "length" and bool((call["content"] or "").strip())
        v = {}
        if ok and planinfo.step_mode(plan, i, goal) == "blender":
            script = blender_run.reply_script(call["content"])
            rr = blender.run(script) if (script and blender) else {"check": {}, "probe": {}}
            v = {k: blender_run.counted_strict(x, rr["probe"].get(k)) for k, x in rr["check"].items()}
            ok = bool(v) and all(v.values())
        s["today"] = {"status": "verified" if ok else "rejected", "model": model, "reply": call["content"] if ok else None,
                      "verdict": v, "frozen_on": now().date().isoformat()}
        save()
        return ok
    return False


def main(argv=None, blender=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--what", default="plans,deps", help="plans, deps or both (comma-separated)")
    ap.add_argument("--tasks", help="W1 task ids, comma-separated (default: all 54)")
    ap.add_argument("--planner", default=PLANNER)
    ap.add_argument("--fallback-planner", default=FALLBACK_PLANNER, help="asked when the planner's plan can't be read")
    ap.add_argument("--gpt-oss-plans", type=int, default=10, help="tasks planned on the fallback planner directly")
    ap.add_argument("--teacher", default=TEACHER, help="the model whose verified replies become dependency outputs")
    ap.add_argument("--tries", type=int, default=2, help="replies per non-Blender step before it is rejected")
    ap.add_argument("--tries-blender", type=int, default=4, help="replies per Blender step before it is rejected")
    ap.add_argument("--today-deps", type=int, default=10, help="today's-format dependency outputs to add (mixed pools)")
    ap.add_argument("--today-model", default=TODAY_MODEL)
    ap.add_argument("--retry-rejected", action="store_true")
    ap.add_argument("--frozen", default=C.FROZEN_DIR, help="where plans.json and deps.json go")
    add_common_args(ap)
    a = ap.parse_args(argv)
    what = {w.strip() for w in a.what.split(",") if w.strip()}
    if what - {"plans", "deps"}:
        ap.error("--what takes plans and/or deps")
    es = evalset.load()
    goals = C.task_goals(es)
    order = [c["id"] for c in es.cases("w1")] + es.helper_prompt_ids()
    task_ids = [t for t in order if not a.tasks or t in {x.strip() for x in a.tasks.split(",")}]
    say = {c["id"]: c["freeze_planner"] for c in es.cases("w1") if c.get("freeze_planner")}
    say.update((es.docs["w1"]["helper_prompts"].get("freeze_planner") or {}))
    big = gpt_oss_tasks(order, say, a.gpt_oss_plans)
    plans_path, deps_path = os.path.join(a.frozen, "plans.json"), os.path.join(a.frozen, "deps.json")
    plans_doc = read_json(plans_path) or doc("W1 frozen plans", es.version)
    deps_doc = read_json(deps_path) or doc("W1 frozen dependency outputs", es.version)
    have_plans = {p["id"]: p for p in plans_doc["items"]}
    have_deps = {d["id"]: d for d in deps_doc["items"]}
    cp = helper_port()

    if a.dry_run:
        print(f"{len(task_ids)} tasks; {len(have_plans)} plans and {len(have_deps)} dependency sets frozen in {rel(a.frozen)}")
        print(f"planned on {a.fallback_planner} directly ({len(big)}): {', '.join(big)}")
        todo = [t for t in task_ids if not (have_plans.get(t) or {}).get("plan")]
        print(f"plans to freeze: {len(todo)} ({a.planner}, then {a.fallback_planner} for a plan Chimera can't read)")
        if todo:
            t = todo[0]
            goal, history, prior, critique = goals[t]
            m = a.fallback_planner if t in big else a.planner
            print(f"--- planner request for {t} on {m}:")
            print(json.dumps(planner_request(cp, goal, history, prior, critique, m), indent=2, ensure_ascii=False))
        need = sum(len(needed_steps(p["plan"])) for p in have_plans.values() if p.get("plan"))
        print(f"dependency outputs: {need} needed by the frozen plans so far, on {a.teacher} under the contract; "
              f"up to {a.tries_blender} tries for Blender, {a.tries} otherwise; verified by the validator, the API lint "
              f"and Chimera's check in Blender {', '.join(blender_run.blenders.VERSIONS)} alone and joined; "
              f"plus {a.today_deps} today's-format outputs from {a.today_model}")
        for tid, p in have_plans.items():
            if p.get("plan") and needed_steps(p["plan"]):
                st = needed_steps(p["plan"])[0]
                i = next(k for k, s in enumerate(p["plan"]["steps"]) if s["id"] == st)
                r = cprompt.worker_request(p["plan"], i, {}, goal=goals.get(tid, ("",))[0])
                print(f"--- first dependency request ({tid} {st}): need_ctx {r.need_ctx}")
                print(json.dumps(chat_body(a.teacher, r.messages, r.need_ctx, 0), indent=2, ensure_ascii=False)[:3000])
                break
        return 0

    os.makedirs(a.frozen, exist_ok=True)
    client = make_client(a)
    try:
        ver = client.version()
        models = [a.planner, a.fallback_planner] if "plans" in what else []
        if "deps" in what:
            models += [a.teacher] + ([a.today_model] if a.today_deps else [])
        infos = {m: model_info(client, m) for m in dict.fromkeys(models)}
    except OllamaError as e:
        print("error:", e, file=sys.stderr)
        return 2
    loaded_before = loaded_models(client)
    run_meta = {"ollama_version": ver, "machine": platform.node(), "python": platform.python_version(),
                "chimera_version_of_requests": CHIMERA_VERSION, "reply_cap": a.reply_cap,
                "max_reply_tokens": a.max_reply_tokens,
                "models": {m: {"digest": i.get("digest"), "details": i.get("details")} for m, i in infos.items()}}

    def save():
        plans_doc["items"] = list(have_plans.values())
        deps_doc["items"] = list(have_deps.values())
        plans_doc["meta"] = dict(plans_doc.get("meta") or {}, gpt_oss_tasks=big, last_run=run_meta,
                                 planner=a.planner, fallback_planner=a.fallback_planner)
        deps_doc["meta"] = dict(deps_doc.get("meta") or {}, last_run=run_meta, teacher=a.teacher,
                                today_model=a.today_model)
        write_json(plans_path, plans_doc)
        write_json(deps_path, deps_doc)

    if "plans" in what:
        for t in task_ids:
            if (have_plans.get(t) or {}).get("plan"):
                continue
            goal, history, prior, critique = goals[t]
            first = a.fallback_planner if t in big else a.planner
            item = freeze_plan(cp, client, t, goal, history, prior, critique, first, a.fallback_planner, a.timeout)
            have_plans[t] = item
            save()
            print(f"plan {t}: {item['planner_model'] or 'NONE'}"
                  + (f", {len(item['plan']['steps'])} steps" if item["plan"] else ""), file=sys.stderr)
    if "deps" in what:
        if blender is None:
            try:
                blender = blender_from_args(a)
            except RuntimeError as e:
                print("error:", e, file=sys.stderr)
                return 2
        linter = lint_facts()
        for t in task_ids:
            item = have_plans.get(t)
            if not item or not item.get("plan"):
                continue
            sha = C.plan_sha(item["plan"])
            d = have_deps.get(t)
            if not d or d.get("plan_sha") != sha:
                d = have_deps[t] = {"id": t, "plan_sha": sha, "steps": {}}
            goal, _, prior, critique = goals[t]
            freeze_deps(item, d, client, a.teacher, a.tries, a.tries_blender, goal, prior or None,
                        critique if prior else None, blender, linter, a.timeout, save, a.retry_rejected)
        made = sum(1 for d in have_deps.values() for s in d["steps"].values() if s.get("today"))
        for t in task_ids:
            if made >= a.today_deps:
                break
            if t in have_plans and t in have_deps and have_plans[t].get("plan"):
                if freeze_today(have_plans[t], have_deps[t], client, a.today_model, goals[t][0], blender, a.timeout, save):
                    made += 1
    if not a.no_unload:
        for m in infos:
            if m not in loaded_before:
                client.unload(m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
