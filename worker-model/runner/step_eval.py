#!/usr/bin/env python3
"""Score an Ollama model on the worker eval's step cases, asking what Chimera's runStep asks.

    python3 runner/step_eval.py --model qwen3.8:27b --quick                       # both prompts, 3 samples
    python3 runner/step_eval.py --model qwen3:8b --parts w2 --prompt contract --samples 1
    python3 runner/step_eval.py --model M --case w2-01 --case w3-04 --dry-run     # print the requests, call nothing

EVAL ONLY: the cases are eval/ (never training data), and so are the replies this writes.

Prompts: "today" is Chimera 0.7.0's workerPrompt and runStep message (contract/today.py); "contract" is the draft
sub-agent contract (contract/prompt.py). Each prompt gets its own run folder,
results/runs/<time>-<model>-<prompt>/: meta.json, raw.jsonl (every reply, its stats, timings and scores),
summary.json and summary.md.

The request is Chimera's (runner/common.py): num_ctx = ctxBucket(historyTokens + 4096, the model's context
length or --ctx-max), stream, keep_alive 15m, no format, and no seed, temperature or think field, so samples are
unseeded at the model's own defaults (--think false adds "think": false, the setting the trained worker runs in: its
template forces thinking off, and Chimera never sends think). Blender and code cases get --samples replies, prose
--prose-samples. A reply's content is cut at the reply cap (--reply-cap, 6,144 content tokens: Hydra Worker's
num_predict, the cap Chimera should hold a step to), and the whole reply, thinking included, at the runaway guard
(--max-reply-tokens, 16,384); either is scored as a runaway, a failure of its own, "in content" or "in thinking"
(the guard hit while the model was still thinking).
Scores (runner/score.py): contract compliance (the validator), Blender strict pass in 5.2.2 and 5.0.1 with the
dependencies joined (Chimera's check through tools/blender_check.py, plus the whole output of a direct run), over
every Blender sample (no script and a runaway count as fails), scene assertions (eval/scene_probe.py, run directly
and sandboxed), API errors (tools/rna_lint.py), the eval's word checks, repairs, tokens and timings.
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

from runner import cases as C  # noqa: E402
from runner import score  # noqa: E402
from runner.common import (CHIMERA_VERSION, MAX_REPLY_TOKENS, REPLY_CAP, STEP_RUNS, Ollama, OllamaError,  # noqa: E402
                           ask, call_fields, chat_body, ctx_bucket, loaded_models, model_info, new_run_dir, now, rel,
                           runaway, warm_up, write_json)

import evalset  # noqa: E402


def blender_from_args(a):
    """A runner.blender_run.Blender, or None with --no-blender (raises RuntimeError when it can't be set up)."""
    if a.no_blender:
        return None
    from runner.blender_run import Blender
    from tools import blenders
    versions = blenders.parse_overrides(a.blender)
    if a.versions:
        versions = dict(blenders.pick(versions, a.versions))
    else:
        versions = {v: versions[v] for v in blenders.VERSIONS}
    return Blender(a.chimera, versions, a.scratch)


def lint_facts():
    try:
        from tools import rna_lint
        return rna_lint.Linter(rna_lint.Facts.load())
    except (ValueError, OSError) as e:
        print(f"note: no API lint ({e})", file=sys.stderr)
        return None


def think_field(body, a):
    """body with --think's "think" field (none when unset, as Chimera 0.7.0 sends it)."""
    if getattr(a, "think", "unset") != "unset":
        body["think"] = a.think == "true"
    return body


def make_client(a):
    client = Ollama(a.host, a.timeout)
    client.max_tokens = a.max_reply_tokens
    client.reply_cap = a.reply_cap
    return client


def limit_notes(a):
    """meta.json's lines on the reply cap and the runaway guard. Chimera 0.7.0 has neither: it sends no num_predict
    and no think field for a step, so a thinking model thinks as long as it likes and nothing stops a loop."""
    out = []
    if a.reply_cap:
        out.append(f"a worker step's reply content is cut after {a.reply_cap} tokens and scored as a runaway in content "
                   "(the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); "
                   "thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap")
    if a.max_reply_tokens:
        out.append(f"every reply, thinking included, is cut after {a.max_reply_tokens} tokens (the runaway guard; a "
                   "worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard)")
    return out


def add_common_args(ap):
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "127.0.0.1:11434"))
    ap.add_argument("--ctx-max", type=int, default=0, help="cap on num_ctx (default: the model's own context length)")
    ap.add_argument("--timeout", type=float, default=900.0, help="seconds per call")
    ap.add_argument("--chimera", help="the Chimera binary for --check-result (default $CHIMERA_BIN)")
    ap.add_argument("--versions", help="Blender versions, comma-separated (default 5.2.2,5.0.1)")
    ap.add_argument("--blender", action="append", metavar="VERSION=PATH", help="another or a different Blender binary")
    ap.add_argument("--scratch", help="where Blender run folders go (default $WM_SCRATCH, else worker-model/data/scratch)")
    ap.add_argument("--no-blender", action="store_true", help="score without running Blender")
    ap.add_argument("--no-unload", action="store_true", help="leave the model loaded afterwards")
    ap.add_argument("--reply-cap", type=int, default=REPLY_CAP,
                    help=f"cut a worker step's reply after this many content tokens (thinking not counted) and score "
                         f"it as a runaway (default {REPLY_CAP}, Hydra Worker's num_predict: the cap Chimera should set; 0: off)")
    ap.add_argument("--max-reply-tokens", type=int, default=MAX_REPLY_TOKENS,
                    help="stop reading any reply (worker steps, combine, planner, reviewer) after this many tokens, "
                         "thinking included: the runaway guard (0: off; Chimera has none)")
    ap.add_argument("--think", choices=["unset", "false", "true"], default="unset",
                    help="the request's think field (default unset, as Chimera sends it; false: thinking off, the "
                         "trained worker's setting)")
    ap.add_argument("--tag", default="", help="extra label for the run folder")
    ap.add_argument("--dry-run", action="store_true", help="print the requests, call nothing")


def main(argv=None, blender=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="an Ollama model name, e.g. qwen3.8:27b")
    ap.add_argument("--prompt", choices=["today", "contract", "both"], default="both")
    ap.add_argument("--parts", default="w2,w3,w4f,w4l,w1", help="comma-separated: " + ", ".join(C.PARTS))
    ap.add_argument("--quick", action="store_true", help="the 60-case quick subset (eval/quick.json)")
    ap.add_argument("--case", action="append", help="only this case id (repeatable; a W1 task id takes all its steps)")
    ap.add_argument("--limit", type=int, default=0, help="at most N cases per part")
    ap.add_argument("--samples", type=int, default=3, help="replies per Blender or code case (unseeded)")
    ap.add_argument("--prose-samples", type=int, default=1, help="replies per prose case")
    ap.add_argument("--frozen", default=C.FROZEN_DIR, help="W1's frozen plans and dependency outputs")
    ap.add_argument("--out", default=STEP_RUNS)
    add_common_args(ap)
    a = ap.parse_args(argv)
    parts = [p.strip() for p in a.parts.split(",") if p.strip()]
    bad = [p for p in parts if p not in C.PARTS]
    if bad:
        ap.error(f"unknown part(s) {bad}; pick from {C.PARTS}")
    prompts = ["today", "contract"] if a.prompt == "both" else [a.prompt]

    es = evalset.load()
    skipped = []
    cs = C.load_cases(es, parts, a.case, a.quick, a.limit, a.frozen, skipped)
    if not cs:
        print("no cases to run" + (f" ({len(skipped)} W1 steps skipped: {skipped[0]})" if skipped else
                                   " (W1 needs frozen plans: runner/freeze.py)" if "w1" in parts else ""), file=sys.stderr)
        return 2
    if a.dry_run:
        for pn in prompts:
            for c in cs[:3] if not a.case else cs:
                req = C.request(c, pn)
                body = think_field(chat_body(a.model, req["messages"], req["need_ctx"], a.ctx_max), a)
                print(f"--- {c.id} ({c.part}, {c.mode}, {pn}): need_ctx {req['need_ctx']}, num_ctx {body['options']['num_ctx']}")
                for n in req["notes"]:
                    print("note:", n)
                print(json.dumps(body, indent=2, ensure_ascii=False))
        print(f"{len(cs)} cases x {len(prompts)} prompt(s), eval {es.version}" +
              (f"; {len(skipped)} W1 steps skipped" if skipped else ""))
        return 0

    client = make_client(a)
    try:
        ver = client.version()
        info = model_info(client, a.model)
    except OllamaError as e:
        print("error:", e, file=sys.stderr)
        return 2
    if blender is None:
        try:
            blender = blender_from_args(a)
        except RuntimeError as e:
            print("error:", e, "(or pass --no-blender)", file=sys.stderr)
            return 2
    linter = lint_facts() if any(c.mode == "blender" for c in cs) else None
    was_loaded = a.model in loaded_models(client)
    ctx_max = a.ctx_max or info["context_length"]
    first = C.request(cs[0], prompts[0])
    warm = warm_up(client, a.model, ctx_bucket(first["need_ctx"], ctx_max))
    if warm["error"] and not runaway(warm):
        print("error: the model didn't answer a warm-up message:", warm["error"], file=sys.stderr)
        return 2
    code = 0
    for pn in prompts:
        code = max(code, run_prompt(a, pn, cs, es, client, ver, info, ctx_max, blender, linter, warm, skipped))
    if not a.no_unload and not was_loaded:
        client.unload(a.model)
    return code


def run_prompt(a, pn, cs, es, client, ver, info, ctx_max, blender, linter, warm, skipped):
    started = now()
    run_dir = new_run_dir(a.out, a.model, pn, a.tag)
    diffs = ["repair cases (W3) under today's prompt get the contract's repair part appended (Chimera 0.7.0 has no step repair)"] \
        if pn == "today" and any(c.repair for c in cs) else []
    if a.think != "unset":
        diffs.append(f"every request sends \"think\": {a.think} (Chimera 0.7.0 sends no think field; the trained worker's "
                     "template forces thinking off)")
    meta = {"model": a.model, "prompt": pn, "digest": info.get("digest", ""), "details": info["details"],
            "context_length": info["context_length"], "ctx_max": ctx_max, "ollama_version": ver, "host": client.base,
            "eval_version": es.version, "chimera_version_of_requests": CHIMERA_VERSION, "samples": a.samples,
            "prose_samples": a.prose_samples, "seed": None,
            "think": "unset" if a.think == "unset" else a.think == "true", "temperature": "unset (model default)",
            "cases": [c.id for c in cs], "w1_skipped": skipped, "warmup_s": round(warm["wall_s"], 2),
            "blender_versions": list(blender.versions) if blender else [], "blender_sandboxed_probe": bool(blender and blender.sandbox),
            "started": started.isoformat(timespec="seconds"), "python": platform.python_version(), "machine": platform.node(),
            "differences_from_chimera": diffs + limit_notes(a),
            "reply_cap": a.reply_cap, "max_reply_tokens": a.max_reply_tokens, "tag": a.tag,
            "parts": sorted({c.part for c in cs}), "quick": a.quick,
            "eval_only": "EVAL ONLY: replies to eval cases, never training data"}
    write_json(os.path.join(run_dir, "meta.json"), meta)
    print(f"{a.model} ({info['details'].get('parameter_size', '?')}, {info['details'].get('quantization_level', '?')}), "
          f"{pn} prompt, {len(cs)} cases -> {rel(run_dir)}", file=sys.stderr)
    records = []
    plan = [(c, s) for c in cs for s in range(a.prose_samples if c.prose else a.samples)]
    with open(os.path.join(run_dir, "raw.jsonl"), "w", encoding="utf-8") as raw:
        for k, (c, sample) in enumerate(plan, 1):
            req = C.request(c, pn)
            body = think_field(chat_body(a.model, req["messages"], req["need_ctx"], ctx_max), a)
            call = ask(client, body, a.timeout, worker=True)
            rec = {"id": c.id, "part": c.part, "mode": c.mode, "eval_mode": c.eval_mode, "prompt": pn, "sample": sample,
                   "model": a.model, "need_ctx": req["need_ctx"], "options": body["options"], "notes": req["notes"],
                   "round2_matched": req.get("round2_matched"),
                   "request_chars": [len(m["content"]) for m in body["messages"]],
                   "reply": call["content"], "thinking": call["thinking"]}
            rec.update(call_fields(call))
            rec["runaway"] = runaway(call)
            if rec["runaway"]:
                rec["runaway_error"], rec["error"] = rec["error"], None  # scored: a failure of its own, not a failed call
            if not rec["error"]:
                try:
                    rec["score"] = score.score_step(c, pn, call["content"], call, blender, linter)
                except Exception as e:  # noqa: BLE001  (a scoring bug shouldn't lose the run's replies)
                    rec["score_error"] = f"{type(e).__name__}: {e}"
                    rec["error"] = "scoring failed: " + rec["score_error"]
            raw.write(json.dumps(rec, ensure_ascii=False) + "\n")
            raw.flush()
            records.append(rec)
            print(f"[{k}/{len(plan)}] {c.id:16} s{sample} {score.brief(rec)} {rec['wall_s'] or 0:.1f}s "
                  f"{(rec.get('stats') or {}).get('eval_count') or 0} tok", file=sys.stderr)
    summary = score.aggregate(records)
    meta["finished"] = now().isoformat(timespec="seconds")
    write_json(os.path.join(run_dir, "meta.json"), meta)
    write_json(os.path.join(run_dir, "summary.json"), {"meta": meta, "summary": summary})
    with open(os.path.join(run_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(score.render_md(meta, summary, records))
    print("wrote", rel(os.path.join(run_dir, "summary.md")), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
