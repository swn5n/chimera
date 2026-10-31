#!/usr/bin/env python3
"""Run whole frozen plans the way Hydra's onePass does, and check the result: the plan's task-level test (T1).

    python3 runner/task_eval.py --arm A,B --tasks bw-01,bw-04             # frozen plans (runner/freeze.py)
    python3 runner/task_eval.py --arm A,B --workers qwen3:8b --case w2-01  # an eval case's own plan, cheaper workers
    python3 runner/task_eval.py --arm B --case w2-01 --dry-run            # print the first requests, call nothing

EVAL ONLY: the plans and tasks are eval/ (never training data), and so are the replies and results this writes.

One pass, round 1 (onePass in app/hydra.go, with parallelism 1): every step in plan order (dependencies are always
on earlier steps), each with runStep's request and up to two tries when the call fails; then
- today's arms (A, A2): onePass's combine, synthPrompt on the combine model (contract/today.combine_messages);
- the contract's arms (B, C): Chimera joins the pieces (contract/join.py). A piece that breaks its mode's rules
  sends the task to the same combine with the pieces as written (the fallback). The seam pass isn't written yet
  (its prompt would be a new frozen text): seams are counted, and --seam combine sends a task with seams to the
  fallback combine instead of keeping the joined result.
A lone step's reply is the result, as in onePass. Every step's reply content is held to the reply cap
(runner/common.py, REPLY_CAP, thinking not counted) and the whole reply to the runaway guard: a step cut at either is
a runaway, used as Chimera would use a cut-off step. A joined Python result whose steps define no main() (the
seam missing_entry_point) gets the outcome no_entry_point: unchecked, a fail. Then the result check: if the
result was cut off, "cut_off" ("runaway" when the cap or the runaway guard cut it); otherwise `chimera
--check-result result.md` in Blender 5.2.2 and 5.0.1 (a Python result once) and the direct run of the script it
picks (its whole output for the strict rule, and the eval's scene assertions when the task has them: W1's new
Blender tasks), and with --review a reviewer's done rate. The summary's pass rates are over every task of the kind
(a Blender plan, a python-script plan): a result that wasn't checked counts as a fail and is listed apart.

| Arm | Prompt   | Workers (default) | Joining |
| A   | today    | qwen3.8:27b       | model combine |
| A2  | today    | gpt-oss:120b      | model combine |
| B   | contract | qwen3.8:27b       | joining |
| C   | contract | gpt-oss:120b      | joining (ceiling) |

The combine model is qwen3.8:27b for every arm (--combine-model). --workers replaces the arm's worker model
(the run folder says which). One folder per arm: results/runs-tasks/<time>-<arm>-<workers>/ with meta.json,
raw.jsonl (every step's reply, the combine, the result, the checks), summary.json and summary.md.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from runner import blender_run  # noqa: E402
from runner import cases as C  # noqa: E402
from runner.common import (CHIMERA_VERSION, SYNTH_ROOM, TASK_RUNS, OllamaError, ask, call_fields,  # noqa: E402
                           chat_body, fmt_pct, helper_port, loaded_models, md_table, median, model_info, new_run_dir,
                           now, pct, rel, runaway, timer, write_json)
from runner.step_eval import add_common_args, blender_from_args, limit_notes, lint_facts, make_client  # noqa: E402

import evalset  # noqa: E402
from contract import planinfo, prompt as cprompt, today  # noqa: E402
from contract.goport import clean_plan  # noqa: E402
from contract.join import join  # noqa: E402
from contract.validate import validate_piece  # noqa: E402

ARMS = {
    "A": {"prompt": "today", "workers": "qwen3.8:27b", "joining": "combine"},
    "A2": {"prompt": "today", "workers": "gpt-oss:120b", "joining": "combine"},
    "B": {"prompt": "contract", "workers": "qwen3.8:27b", "joining": "join"},
    "C": {"prompt": "contract", "workers": "gpt-oss:120b", "joining": "join"},
}
COMBINE_MODEL = "qwen3.8:27b"
REVIEW_MODEL = "gpt-oss:120b"
VERSIONS = ("5.2.2", "5.0.1")


class Task:
    """One plan to run: id, cleaned plan, goal (what the combine and the check are told), round-2 parts, the
    assertions for the joined scene (W1's new Blender tasks), and where it came from."""

    def __init__(self, tid, plan, goal, source, prior=None, critique=None, assertions=None):
        self.id, self.plan, self.goal, self.source = tid, plan, goal, source
        self.prior, self.critique, self.assertions = prior, critique, assertions or []

    @property
    def kinds(self):
        return {self.plan["kind"]} | {s["kind"] for s in self.plan["steps"]}


def load_tasks(es, task_ids=None, case_ids=None, frozen_dir=C.FROZEN_DIR):
    """Frozen W1 plans (all, or task_ids) and eval cases' own plans (case_ids: W2-W4 ids). A case plan's goal is its
    title and summary (those cases have no task prompt of their own)."""
    out = []
    if task_ids is not None or not case_ids:
        plans, _ = C.load_frozen(frozen_dir)
        goals = C.task_goals(es)
        asserts = {c["id"]: (c.get("expect") or {}).get("assertions") for c in es.cases("w1")}
        for tid, item in plans.items():
            if task_ids and tid not in task_ids:
                continue
            goal, _, prior, critique = goals.get(tid, ("", None, "", ""))
            out.append(Task(tid, item["plan"], goal, "frozen:" + item.get("planner_model", "?"), prior or None,
                            critique if prior else None, asserts.get(tid)))
        missing = [t for t in task_ids or [] if t not in plans]
        if missing:
            raise ValueError(f"no frozen plan for {', '.join(missing)} (run runner/freeze.py first)")
    for cid in case_ids or []:
        c = es.by_id(cid)
        if "plan" not in c:
            raise ValueError(f"{cid} has no plan of its own (a W1 task needs a frozen plan: --tasks)")
        plan = clean_plan(c["plan"])
        out.append(Task(cid, plan, f"{plan['title']}: {plan['summary']}", "case-plan"))
    return out


def run_task(task, arm, client, workers, combine_model, ctx_max, timeout, seam_mode="none"):
    """One pass of one task under one arm. Returns the record (steps, combine, join, result)."""
    plan, steps = task.plan, task.plan["steps"]
    spec = ARMS[arm]
    elapsed = timer()
    outputs, done_reasons, rec_steps = {}, {}, []
    # runStep's room: 4096, and a lone step gets max(4096, room) with room = synthRoom in round 1
    for i, st in enumerate(steps):
        if spec["prompt"] == "contract":
            r = cprompt.worker_request(plan, i, outputs, goal=task.goal, prev_result=task.prior, critique=task.critique)
            msgs, need = r.messages, r.need_ctx
        else:
            r = today.worker_messages(plan, i, outputs)
            msgs, need = r["messages"], r["need_ctx"]
        body = chat_body(workers, msgs, need, ctx_max.get(workers, 0))
        call = ask(client, body, timeout, worker=True)
        cut = runaway(call)  # the reply cap stopped it: a step cut off at its limit (a runaway), not a failed step
        outputs[st["id"]] = None if call["error"] and not cut else call["content"]
        done_reasons[st["id"]] = "length" if cut else (call.get("stats") or {}).get("done_reason") or ""
        mode = planinfo.step_mode(plan, i, task.goal)
        piece = validate_piece(call["content"] or "", mode, sid="s%d" % (i + 1), deps=planinfo.dep_names(plan, i),
                               lone=len(steps) == 1, step=st, done_reason=done_reasons[st["id"]], max_tokens=None)
        sr = {"sid": "s%d" % (i + 1), "id": st["id"], "title": st["title"], "kind": st["kind"], "mode": mode,
              "model": workers, "need_ctx": need, "options": body["options"], "reply": call["content"],
              "status": "failed" if outputs[st["id"]] is None else "done", "runaway": cut,
              "contract_ok": piece.contract_ok, "form_ok": piece.form_ok, "piece_ok": piece.ok,
              "contract_errors": sorted({x.code for x in piece.errors})}
        sr.update(call_fields(call))
        rec_steps.append(sr)
        print(f"  {task.id} {sr['sid']} {sr['status']} {sr['wall_s'] or 0:.1f}s "
              f"{(sr['stats'] or {}).get('eval_count') or 0} tok, contract {'ok' if piece.contract_ok else 'broken'}",
              file=sys.stderr)
    rec = {"task": task.id, "source": task.source, "arm": arm, "prompt": spec["prompt"], "workers": workers,
           "combine_model": combine_model, "steps": rec_steps, "combine": None, "join": None,
           "runaway_steps": [x["sid"] for x in rec_steps if x["runaway"]], "has_assertions": bool(task.assertions)}
    n_done = sum(1 for s in rec_steps if s["status"] == "done")
    if n_done == 0:
        rec.update(result=None, how="none", error="None of the steps finished.", wall_s=elapsed())
        return rec
    result_runaway = False
    if len(steps) == 1:  # onePass: a lone step's output is the result
        how, text = "lone", outputs[steps[0]["id"]]
        cut = done_reasons[steps[0]["id"]] == "length"
        result_runaway = rec_steps[0]["runaway"]
        if spec["joining"] == "join":
            j = join(plan, outputs, goal=task.goal, done_reasons=done_reasons)
            rec["join"] = join_record(j)
            if not j.fallback:
                how, text = "joined", result_text(j)
    elif spec["joining"] == "join":
        j = join(plan, outputs, goal=task.goal, done_reasons=done_reasons)
        rec["join"] = join_record(j)
        if j.fallback or (seam_mode == "combine" and j.seams):
            how = "fallback" if j.fallback else "seam_combine"
            text, cut, rec["combine"] = combine(task, plan, outputs, client, combine_model, ctx_max, timeout)
        else:
            how, text, cut = "joined", result_text(j), False
    else:
        how = "combine"
        text, cut, rec["combine"] = combine(task, plan, outputs, client, combine_model, ctx_max, timeout)
    if rec["combine"]:
        result_runaway = rec["combine"]["runaway"]
    rec.update(how=how, result=text, cut=cut, result_runaway=bool(cut and result_runaway), wall_s=elapsed())
    return rec


def result_text(j):
    """The joined result as the person would get it: handoffs stripped, the assumed lines as an Assumptions note."""
    note = j.assumptions_note()
    return j.text + ("\n" + note + "\n" if note else "")


def join_record(j):
    return {"fallback": j.fallback, "reasons": j.reasons, "seams": [{"code": s.code, "message": s.message[:200],
                                                                    "step": getattr(s, "sid", None)} for s in j.seams],
            "failed": j.failed, "script_kind": j.script_kind, "assumptions": len(j.assumptions)}


def combine(task, plan, outputs, client, model, ctx_max, timeout):
    """onePass's combine (synthPrompt) on the combine model: (text, cut, record)."""
    r = today.combine_messages(task.goal, plan, outputs, room=SYNTH_ROOM)
    body = chat_body(model, r["messages"], r["need_ctx"], ctx_max.get(model, 0))
    call = ask(client, body, timeout, attempts=1)
    crec = {"model": model, "need_ctx": r["need_ctx"], "options": body["options"], "reply": call["content"],
            "runaway": runaway(call)}
    crec.update(call_fields(call))
    if crec["runaway"]:
        return call["content"], True, crec
    print(f"  {task.id} combine on {model} {crec['wall_s'] or 0:.1f}s {(crec['stats'] or {}).get('eval_count') or 0} tok"
          + (f" ERROR {call['error']}" if call["error"] else ""), file=sys.stderr)
    if call["error"]:
        return None, False, crec
    return call["content"], crec["done_reason"] == "length", crec


def check_result(task, rec, blender, linter):
    """The result check (checkResult, app/hydra_check.go, as looping mode runs it) on both Blenders, plus the
    eval's scene assertions and the lint of the script the check picks."""
    text = rec.get("result")
    out = {"scripts": blender_run.count_scripts(text or "")}
    if text is None:
        out["outcome"] = "no_result"
        return out
    if rec.get("cut"):  # what made the result (the combine, or a lone step) stopped at its limit
        out["outcome"] = "runaway" if rec.get("result_runaway") else "cut_off"
        return out
    kind, script, why = blender_run.pick_script(text, task.kinds)
    out.update(kind=kind or None, why=why or None, script_lines=script.count("\n") + 1 if script else 0)
    if not kind:
        out["outcome"] = "nothing_to_check"
        return out
    if why:
        out["outcome"] = "skipped"
        return out
    if kind == "run_python" and rec.get("how") == "joined" and \
            any(s.get("code") == "missing_entry_point" for s in (rec.get("join") or {}).get("seams") or []):
        # The joined Python only defines functions: Chimera's check would pass it in no time without running a line
        # of the steps' code (contract/join.py's seam), so it isn't a pass. Not run; counted as a fail.
        out["outcome"] = "no_entry_point"
        out["why"] = ("no step defines main(), so the joined script runs nothing (seam missing_entry_point); "
                      "Chimera's check would pass it without running the steps' code")
        return out
    if linter is not None and kind == "run_blender":
        found = linter.lint(script)
        out["lint_errors"] = sum(1 for x in found if x["level"] == "error")
    if blender is None:
        out["outcome"] = "not_run"
        return out
    if kind == "run_blender":
        out["check"] = blender.check(text, name="result.md", goal=task.goal)
        # The direct run of the script the check picks: its whole output for the strict rule (the check shows only the
        # last 1,500 characters), and the scene for the assertions.
        probe = blender.probe(script)
        out["probe"] = {v: {k: r.get(k) for k in ("exit", "strict_full", "bad_lines", "blender", "version_ok", "stand_in",
                                                  "stopped_at_render", "seconds")} for v, r in probe.items()}
        out["strict"] = {v: blender_run.counted_strict(c, out["probe"].get(v)) for v, c in out["check"].items()}
        if task.assertions:
            out["assertions"] = {}
            for v, r in probe.items():
                out["assertions"][v] = evalset.check_assertions(r["probe"], task.assertions) if r.get("probe") else ["no probe output"]
        out["outcome"] = "checked"
    else:
        out["check"] = {"python": blender.check_python(text, goal=task.goal)}
        out["outcome"] = "checked"
    return out


def review(task, text, client, model, timeout, samples):
    """The looping reviewer (reviewRequest, app/hydra.go) on a fixed model: the share of samples saying done."""
    cp = helper_port()
    msgs = cp.review_messages(task.goal, text)
    body = cp.chat_body("reviewer", model, msgs)
    out = []
    for _ in range(samples):
        call = client.chat(body, timeout)
        ok, v, _ = cp.extract_json(call["content"] or "", cp.REVIEW_SPEC) if not call["error"] else (False, None, None)
        out.append({"ok": ok, "done": v["done"] if ok else None, "score": v["score"] if ok else None,
                    "critique": (v or {}).get("critique", "")[:300], "error": call["error"], "wall_s": round(call["wall_s"], 2)})
    return out


def passes(rec, v):
    """The strict pass that counts, in one version: Chimera's check of the result, and the whole output of the direct
    run of the script it picks (blender_run.counted_strict)."""
    ck = rec.get("check") or {}
    if "strict" in ck:
        return bool(ck["strict"].get(v))
    return blender_run.counted_strict((ck.get("check") or {}).get(v), (ck.get("probe") or {}).get(v))


def py_passes(rec):
    """Chimera's check of a Python result passed, and it ran something (a joined script with no entry point never
    passes: its outcome is no_entry_point)."""
    ck = rec.get("check") or {}
    if ck.get("outcome") != "checked":
        return False
    return (((ck.get("check") or {}).get("python")) or {}).get("outcome") == "passed"


def step_modes(rec):
    return {s.get("mode") for s in rec.get("steps") or []}


def population(rec):
    """Which pass rate a task counts in: "blender" (a plan with a Blender step), "python" (a python-script plan, no
    files step), "files" (a multi-file code plan: Chimera's check can't run those, and the hidden tests aren't
    built), or None (prose)."""
    m = step_modes(rec)
    if "blender" in m:
        return "blender"
    if "files" in m:
        return "files"
    if "python-script" in m:
        return "python"
    return None


UNCHECKED = ("runaway", "cut_off", "skipped", "nothing_to_check", "no_result", "no_entry_point")


def summarize(records):
    """Pass rates over every task of their kind: a result that wasn't checked (the combine or a lone step cut off or
    run away, several scripts so the check skipped it, no script, no result, a joined Python script with no entry
    point) counts as a fail, and "unchecked" says how many of each. None when Blender wasn't run (--no-blender).
    steps_contract_ok counts the near-miss handoffs as kept (Chimera joins them); steps_form_ok only the exact form."""
    n = len(records)
    pops = {"blender": [], "python": [], "files": []}
    for r in records:
        k = population(r)
        if k:
            pops[k].append(r)
    bl, py = pops["blender"], pops["python"]
    joins = [r for r in records if r.get("join")]
    steps = [x for r in records for x in r["steps"]]

    def outcome(r):
        return (r.get("check") or {}).get("outcome")

    out = {"n": n, "errors": sum(1 for r in records if r.get("error")),
           "how": {h: sum(1 for r in records if r.get("how") == h) for h in sorted({r.get("how") for r in records if r.get("how")})},
           "outcomes": {o: sum(1 for r in records if outcome(r) == o)
                        for o in sorted({outcome(r) for r in records} - {None})},
           "blender_n": len(bl), "python_n": len(py), "files_n": len(pops["files"]),
           "blender_checked": sum(1 for r in bl if outcome(r) == "checked"),
           "python_checked": sum(1 for r in py if outcome(r) == "checked"),
           "unchecked": {k: {o: sum(1 for r in pop if outcome(r) == o) for o in UNCHECKED}
                         for k, pop in (("blender", bl), ("python", py))},
           "fallback": pct(sum(1 for r in joins if r["join"]["fallback"]), len(joins)) if joins else None,
           "seams_mean": round(sum(len(r["join"]["seams"]) for r in joins) / len(joins), 2) if joins else None,
           "cut": pct(sum(1 for r in records if r.get("cut") and not r.get("result_runaway")), n),
           "runaway": pct(sum(1 for r in records if r.get("result_runaway")), n),
           "runaway_steps": sum(1 for x in steps if x.get("runaway")),
           "runaway_steps_thinking": sum(1 for x in steps if x.get("runaway") and x.get("runaway_in") == "thinking"),
           "steps_runaway": pct(sum(1 for x in steps if x.get("runaway")), len(steps)),
           "steps_contract_ok": pct(sum(1 for x in steps if x["contract_ok"]), len(steps)),
           "steps_form_ok": pct(sum(1 for x in steps if x.get("form_ok")), len([x for x in steps if "form_ok" in x]))
           if any("form_ok" in x for x in steps) else None,
           "wall_s_median": median([r.get("wall_s") for r in records]),
           "wall_s_total": round(sum(r.get("wall_s") or 0 for r in records), 1),
           "tokens_total": sum((x.get("stats") or {}).get("eval_count") or 0 for x in steps) +
           sum(((r.get("combine") or {}).get("stats") or {}).get("eval_count") or 0 for r in records),
           "one_script": pct(sum(1 for r in bl if ((r.get("check") or {}).get("scripts") or {}).get("blender") == 1),
                             len(bl)) if bl else None}
    bl_ok = bl and not any(outcome(r) == "not_run" for r in bl)
    for v in VERSIONS:
        out[f"pass_{v}"] = pct(sum(1 for r in bl if passes(r, v)), len(bl)) if bl_ok else None
    out["pass_both"] = pct(sum(1 for r in bl if all(passes(r, v) for v in VERSIONS)), len(bl)) if bl_ok else None
    py_ok = py and not any(outcome(r) == "not_run" for r in py)
    out["python_pass"] = pct(sum(1 for r in py if py_passes(r)), len(py)) if py_ok else None
    # Scene assertions: every task that has them; a result with no scene (unchecked) fails them
    asr = [r for r in records if r.get("has_assertions") or (r.get("check") or {}).get("assertions")]
    out["assertions_5.2.2"] = pct(sum(1 for r in asr if (r.get("check") or {}).get("assertions") is not None
                                      and not r["check"]["assertions"].get("5.2.2")), len(asr)) \
        if asr and not any(outcome(r) == "not_run" for r in asr) else None
    revs = [x for r in records for x in r.get("review") or [] if x["ok"]]
    out["review_done"] = pct(sum(1 for x in revs if x["done"]), len(revs)) if revs else None
    return out


def render_md(meta, s, records):
    lines = [f"# Task-level run, arm {meta['arm']}: {meta['prompt']} prompt, workers {meta['workers']}, "
             f"{meta['joining']}", "",
             f"{meta['started']} · combine model {meta['combine_model']} · seam pass: {meta['seam']} · "
             f"Ollama {meta.get('ollama_version', '?')} · Blender {', '.join(meta.get('blender_versions') or []) or 'not run'}",
             "", "EVAL ONLY: model output for eval plans; never training data.", ""]
    rows = [["tasks", "Blender n", "Blender pass 5.2.2", "5.0.1", "both", "Python n", "Python pass", "assertions",
             "fallback", "seams", "cut off", "runaway", "steps runaway", "steps kept the contract",
             "steps in exact form", "one script", "reviewer done", "median s", "total s", "tokens"],
            [s["n"], s["blender_n"], fmt_pct(s["pass_5.2.2"]), fmt_pct(s["pass_5.0.1"]), fmt_pct(s["pass_both"]),
             s["python_n"], fmt_pct(s["python_pass"]), fmt_pct(s["assertions_5.2.2"]), fmt_pct(s["fallback"]),
             s["seams_mean"], fmt_pct(s["cut"]), fmt_pct(s["runaway"]),
             fmt_pct(s["steps_runaway"]) + (f" ({s.get('runaway_steps_thinking', 0)} in thinking)" if s["runaway_steps"] else ""),
             fmt_pct(s["steps_contract_ok"]), fmt_pct(s.get("steps_form_ok")), fmt_pct(s["one_script"]),
             fmt_pct(s["review_done"]), s["wall_s_median"], s["wall_s_total"], s["tokens_total"]]]
    un = {k: {o: c for o, c in v.items() if c} for k, v in s["unchecked"].items()}
    lines += [md_table(rows), "",
              "Pass rates are over every task of the kind: Blender n is every plan with a Blender step, Python n every "
              "python-script plan without a files step"
              + (f" ({s['files_n']} multi-file plans aren't scored: Chimera's check can't run them)" if s["files_n"] else "")
              + ". A result the check didn't run counts as a fail: "
              f"unchecked {json.dumps(un)}. pass: Chimera's check passed with no Traceback or Error: line in its "
              "1,500-character output tail, and the direct run of the same script has none in its whole output. "
              "runaway: the combine or a lone step hit the reply cap"
              + (f" ({meta['reply_cap']} content tokens for a step, thinking not counted)" if meta.get("reply_cap") else "")
              + " or the runaway guard"
              + (f" ({meta['max_reply_tokens']} tokens, thinking included)" if meta.get("max_reply_tokens") else "")
              + "; steps runaway: steps the cap or the guard cut (\"in thinking\": the guard hit while the model was "
              "still thinking). steps kept the contract: Chimera can join the piece (the near-miss handoff forms "
              "included, since Oct 30); in exact form: no errors and the contract's exact written form, what data "
              "generation keeps. no_entry_point (unchecked): a joined Python script where no step defines main(), "
              "which Chimera's check would pass without running anything. cut off: Ollama itself stopped at a "
              "length limit. one script: of the Blender tasks, results holding exactly one Blender script.", "",
              f"How the result was made: {json.dumps(s['how'])}; checks: {json.dumps(s['outcomes'])}.", "",
              "## Tasks", ""]
    rows = [["task", "sample", "steps (s, tokens, contract)", "result by", "5.2.2", "5.0.1", "assertions", "seams", "s",
             "first problem"]]
    for r in records:
        ck = (r.get("check") or {}).get("check") or {}
        pr = (r.get("check") or {}).get("probe") or {}

        def cell(v):
            if v not in ck:
                return "–"
            if passes(r, v):
                return "pass"
            return (ck[v] or {}).get("outcome") if (ck[v] or {}).get("outcome") != "passed" else "not strict"
        problem = r.get("error") or ""
        for v in VERSIONS:
            c, p = ck.get(v) or {}, pr.get(v) or {}
            if v in ck and not passes(r, v) and not problem:
                if not c.get("strict"):
                    problem = f"{v}: " + (f"line {c['line']}: {c.get('error')}" if c.get("line") else (c.get("strict_why") or c.get("summary") or ""))
                else:
                    problem = f"{v}: the direct run printed " + ((p.get("bad_lines") or ["?"])[0])[:100]
        if not problem and (r.get("join") or {}).get("reasons"):
            problem = "fallback: " + r["join"]["reasons"][0]
        if not problem and (r.get("check") or {}).get("outcome") not in ("checked", None):
            problem = r["check"]["outcome"] + (": " + r["check"]["why"] if r["check"].get("why") else "")
        if r.get("runaway_steps"):
            problem = "runaway steps " + ", ".join(r["runaway_steps"]) + (("; " + problem) if problem else "")
        a = (r.get("check") or {}).get("assertions")
        steps = ", ".join(f"{x['sid']} {x['wall_s'] or 0:.0f}s {(x['stats'] or {}).get('eval_count') or 0}t "
                          f"{('ok' if x.get('form_ok', True) else 'near') if x['contract_ok'] else 'x'}" for x in r["steps"])
        rows.append([r["task"], r.get("sample", 0), steps, r.get("how"), cell("5.2.2"), cell("5.0.1"),
                     "–" if not a else ("ok" if not a.get("5.2.2") else f"{len(a['5.2.2'])} failed"),
                     len((r.get("join") or {}).get("seams") or []), r.get("wall_s"), problem[:140]])
    lines += [md_table(rows), ""]
    return "\n".join(lines)


def main(argv=None, blender=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", default="A,B", help="comma-separated: " + ", ".join(ARMS))
    ap.add_argument("--workers", help="the worker model for every arm asked for (default: each arm's own)")
    ap.add_argument("--combine-model", default=COMBINE_MODEL, help=f"the combine (and seam) model (default {COMBINE_MODEL})")
    ap.add_argument("--tasks", help="frozen W1 task ids, comma-separated (default: every frozen plan)")
    ap.add_argument("--case", action="append", help="an eval case whose own plan to run (W2-W4 ids; repeatable)")
    ap.add_argument("--frozen", default=C.FROZEN_DIR)
    ap.add_argument("--samples", type=int, default=1, help="passes per task (unseeded)")
    ap.add_argument("--seam", choices=["none", "combine"], default="none",
                    help="contract arms with seams: keep the joined result (none) or use the fallback combine")
    ap.add_argument("--review", type=int, default=0, metavar="N", help=f"N reviews of each result on --review-model")
    ap.add_argument("--review-model", default=REVIEW_MODEL)
    ap.add_argument("--out", default=TASK_RUNS)
    add_common_args(ap)
    a = ap.parse_args(argv)
    arms = [x.strip().upper() for x in a.arm.split(",") if x.strip()]
    bad = [x for x in arms if x not in ARMS]
    if bad:
        ap.error(f"unknown arm(s) {bad}; pick from {list(ARMS)}")
    es = evalset.load()
    try:
        tasks = load_tasks(es, [t.strip() for t in a.tasks.split(",")] if a.tasks else None, a.case, a.frozen)
    except (ValueError, KeyError) as e:
        print("error:", e, file=sys.stderr)
        return 2
    if not tasks:
        print("no tasks: freeze plans first (runner/freeze.py), or pass --case with an eval case id", file=sys.stderr)
        return 2
    if a.dry_run:
        for arm in arms:
            spec, w = ARMS[arm], a.workers or ARMS[arm]["workers"]
            t = tasks[0]
            if spec["prompt"] == "contract":
                r = cprompt.worker_request(t.plan, 0, {}, goal=t.goal, prev_result=t.prior, critique=t.critique)
                msgs, need = r.messages, r.need_ctx
            else:
                r = today.worker_messages(t.plan, 0, {})
                msgs, need = r["messages"], r["need_ctx"]
            print(f"--- arm {arm}: {t.id} s1 on {w}, then {spec['joining']}"
                  + (f" on {a.combine_model}" if spec["joining"] == "combine" else ""))
            print(json.dumps(chat_body(w, msgs, need, a.ctx_max), indent=2, ensure_ascii=False))
        print(f"{len(tasks)} task(s) x {len(arms)} arm(s) x {a.samples} sample(s)")
        return 0

    client = make_client(a)
    models = sorted({a.workers or ARMS[x]["workers"] for x in arms} | {a.combine_model} |
                    ({a.review_model} if a.review else set()))
    try:
        ver = client.version()
        infos = {m: model_info(client, m) for m in models}
    except OllamaError as e:
        print("error:", e, file=sys.stderr)
        return 2
    ctx_max = {m: a.ctx_max or i["context_length"] for m, i in infos.items()}
    if blender is None:
        try:
            blender = blender_from_args(a)
        except RuntimeError as e:
            print("error:", e, "(or pass --no-blender)", file=sys.stderr)
            return 2
    linter = lint_facts()
    loaded_before = loaded_models(client)
    for arm in arms:
        spec, workers = ARMS[arm], a.workers or ARMS[arm]["workers"]
        started = now()
        run_dir = new_run_dir(a.out, arm, workers, a.tag)
        meta = {"arm": arm, "prompt": spec["prompt"], "joining": spec["joining"], "workers": workers,
                "arm_default_workers": spec["workers"], "combine_model": a.combine_model, "seam": a.seam,
                "models": {m: {k: infos[m].get(k) for k in ("digest", "details", "context_length")} for m in models},
                "ollama_version": ver, "host": client.base, "eval_version": es.version, "tasks": [t.id for t in tasks],
                "task_sources": {t.id: t.source for t in tasks}, "samples": a.samples, "review": a.review,
                "review_model": a.review_model if a.review else None, "chimera_version_of_requests": CHIMERA_VERSION,
                "blender_versions": list(blender.versions) if blender else [], "started": started.isoformat(timespec="seconds"),
                "python": platform.python_version(), "machine": platform.node(),
                "differences_from_chimera": ["steps run one at a time (onePass with parallelism 1)",
                                             "no library references or library reuse",
                                             "every step on the one worker model, the combine on a fixed model"]
                + (["contract arms: no seam pass (not written yet); seams are counted only"] if spec["joining"] == "join" and a.seam == "none" else [])
                + (["contract arms: tasks with seams go to the fallback combine"] if spec["joining"] == "join" and a.seam == "combine" else [])
                + limit_notes(a),
                "reply_cap": a.reply_cap, "max_reply_tokens": a.max_reply_tokens, "tag": a.tag,
                "eval_only": "EVAL ONLY: model output for eval plans, never training data"}
        write_json(os.path.join(run_dir, "meta.json"), meta)
        print(f"arm {arm}: {spec['prompt']} prompt, workers {workers}, {spec['joining']} -> {rel(run_dir)}", file=sys.stderr)
        records = []
        with open(os.path.join(run_dir, "raw.jsonl"), "w", encoding="utf-8") as raw:
            for t in tasks:
                for sample in range(a.samples):
                    rec = run_task(t, arm, client, workers, a.combine_model, ctx_max, a.timeout, a.seam)
                    rec["sample"] = sample
                    t_check = timer()
                    rec["check"] = check_result(t, rec, blender, linter)
                    rec["check"]["seconds"] = t_check()
                    if a.review and rec.get("result"):
                        rec["review"] = review(t, rec["result"], client, a.review_model, a.timeout, a.review)
                    raw.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    raw.flush()
                    records.append(rec)
                    ck = rec["check"].get("check") or {}
                    print(f"[{arm}] {t.id} s{sample}: {rec.get('how')}, " +
                          (", ".join(f"{v} {'pass' if passes(rec, v) else (c or {}).get('outcome')}" for v, c in ck.items())
                           or rec["check"].get("outcome", "?")) + f", {rec.get('wall_s')} s", file=sys.stderr)
        s = summarize(records)
        meta["finished"] = now().isoformat(timespec="seconds")
        write_json(os.path.join(run_dir, "meta.json"), meta)
        write_json(os.path.join(run_dir, "summary.json"), {"meta": meta, "summary": s})
        with open(os.path.join(run_dir, "summary.md"), "w", encoding="utf-8") as f:
            f.write(render_md(meta, s, records))
        print("wrote", rel(os.path.join(run_dir, "summary.md")), file=sys.stderr)
    if not a.no_unload:
        for m in models:
            if m not in loaded_before:
                client.unload(m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
