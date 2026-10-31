#!/usr/bin/env python3
"""Score any Ollama model on the helper eval set, asking exactly what Chimera asks.

    python3 runner/run_eval.py --model qwen3:4b
    python3 runner/run_eval.py --model qwen3:4b --jobs gate --think false
    python3 runner/run_eval.py --model qwen3-embedding:0.6b --jobs embed
    python3 runner/run_eval.py --model qwen3:4b --dry-run      # print one request per job, call nothing

Requests are built by helper/chimera_port.py: Chimera's system prompts, user messages, format,
temperature, num_ctx and keep_alive. Deliberate differences, all recorded in meta.json:
a fixed sampling seed (--seed none drops it) so runs repeat, an optional "think" field
(Chimera sends none), and an optional temperature for the planner and reviewer (Chimera sends
none, so the model's own default applies). Writes results/runs/<time>-<model>/: meta.json, raw.jsonl (every reply,
its thinking, timings, validation and score), summary.json and summary.md.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from helper import chimera_port as cp  # noqa: E402
from helper import evalset, prompts  # noqa: E402
from helper.validate import VALIDATORS  # noqa: E402
from runner import embed_baseline, scoring  # noqa: E402
from runner.ollama_client import Ollama, OllamaError  # noqa: E402

GATE_TIMEOUT = 45.0  # headGate: context.WithTimeout(ctx, 45*time.Second)
JOBS = ("planner", "reviewer", "gate", "embed")

# Experiments that change what the reviewer is asked; never Chimera's own requests, so their runs are
# labelled with the variant and kept out of the baselines' comparison with Chimera.
CHECK_FIRST_NOTE = (
    '\n\nBefore the verdict, write a "check" field as the first key of the JSON: go through what the task asks '
    "for, one short line per requirement, and say whether the result meets it. Check counts, numbers, limits and "
    "calculations exactly instead of assuming they're right. Then give done, score and critique based on that "
    'check:\n{"check": "...", "done": true | false, "score": 0 to 100, "critique": "..."}')
CHECK_FIRST_SCHEMA = {"type": "object", "properties": {"check": {"type": "string"}, "done": {"type": "boolean"},
                                                       "score": {"type": "integer"}, "critique": {"type": "string"}},
                      "required": ["check", "done", "score", "critique"]}
VARIANTS = {"check-first": "reviewer: a \"check\" of each requirement before the verdict (a field Chimera ignores), "
                           "its key order forced with a JSON schema",
            "check-working": "reviewer: as check-first, but the check lists the task's requirements first and redoes "
                             "counts and calculations (the note v3's teacher gets)"}


def variant_note(variant):
    if variant == "check-first":
        return CHECK_FIRST_NOTE
    if variant == "check-working":
        from datagen import teacher_prompts
        return teacher_prompts.CHECK_NOTE3
    return None


def validate(job, text, variant=None):
    if job == "reviewer" and variant in VARIANTS:
        return VALIDATORS["reviewer"](text, require=("check",))
    return VALIDATORS[job](text)


def build_cases(es, jobs, variant=None):
    cases = []
    if "planner" in jobs:
        for p in es.planner_cases():
            msgs = cp.planner_messages(p["prompt"], p.get("history"), p.get("prior") or "", p.get("critique") or "")
            cases.append({"job": "planner", "id": p["id"], "case": p, "messages": msgs})
    if "reviewer" in jobs:
        for r in es.reviews:
            msgs = cp.review_messages(r["task"], r["result"])
            if variant_note(variant):
                msgs = [dict(msgs[0], content=msgs[0]["content"] + variant_note(variant))] + msgs[1:]
            cases.append({"job": "reviewer", "id": r["id"], "case": r, "messages": msgs})
    if "gate" in jobs:
        for p, g, h in es.gate_pairs():
            cases.append({"job": "gate", "id": f"{p['id']}/{h['id']}", "case": p, "label": g, "head": h,
                          "messages": cp.gate_messages(h, p["prompt"])})
    return cases


def request_body(c, model, args, ctx_max):
    body = cp.chat_body(c["job"], model, c["messages"], ctx_max)
    if args.seed != "none":
        body["options"]["seed"] = int(args.seed)
    if args.think != "unset":
        body["think"] = args.think == "true"
    if getattr(args, "temperature", "unset") != "unset" and c["job"] in ("planner", "reviewer"):
        body["options"]["temperature"] = float(args.temperature)
    if c["job"] == "reviewer" and getattr(args, "variant", None) in VARIANTS:
        body["format"] = CHECK_FIRST_SCHEMA
    return body


def score_case(c, res, call):
    if c["job"] == "planner":
        return scoring.score_planner(c["case"], res, call)
    if c["job"] == "reviewer":
        return scoring.score_reviewer(c["case"], res, call)
    reach = cp.reaches_gate(c["case"]["prompt"], c["head"])
    return scoring.score_gate(c["label"], res, call, reach)


def model_info(client, model):
    info = {"model": model}
    show = client.show(model)
    info["details"] = show.get("details") or {}
    mi = show.get("model_info") or {}
    ctx = [v for k, v in mi.items() if k.endswith(".context_length")]
    info["context_length"] = int(ctx[0]) if ctx else 0
    info["capabilities"] = show.get("capabilities") or []
    want = model if ":" in model else model + ":latest"
    for t in client.tags():
        if t.get("name") == want or t.get("model") == want:
            info["digest"] = t.get("digest", "")
            info["size"] = t.get("size")
    return info


def temp_label(t):
    """The run folder's mark for a set temperature ("t0.2"), or "" when Chimera's default is used."""
    return "" if t in (None, "unset") else "t" + t


def slug(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="an Ollama model name, e.g. qwen3:4b")
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "127.0.0.1:11434"))
    ap.add_argument("--jobs", default="planner,reviewer,gate", help="comma-separated: " + ", ".join(JOBS))
    ap.add_argument("--eval-dir", default=evalset.EVAL_DIR)
    ap.add_argument("--out", default=os.path.join(HERE, "results", "runs"))
    ap.add_argument("--limit", type=int, default=0, help="at most N cases per job (a quick smoke run)")
    ap.add_argument("--samples", type=int, default=1, help="replies per case (sampling varies)")
    ap.add_argument("--seed", default="7", help="Ollama seed so runs repeat, or 'none' to leave it unset like Chimera")
    ap.add_argument("--think", choices=["unset", "true", "false"], default="unset",
                    help="Chimera sends no think field ('unset'); 'false' measures the non-thinking mode")
    ap.add_argument("--temperature", default="unset",
                    help="temperature for planner and reviewer requests; Chimera sends none ('unset'), so the model's "
                         "own default applies (hydra:1.0's Modelfile: 0.7). The gate always gets Chimera's 0")
    ap.add_argument("--ctx-max", type=int, default=0, help="cap on num_ctx (default: the model's own context length)")
    ap.add_argument("--timeout", type=float, default=600.0, help="seconds per planner/reviewer call")
    ap.add_argument("--tag", default="", help="extra label for the run folder")
    ap.add_argument("--variant", choices=sorted(VARIANTS), help="an experiment, not Chimera's request: " +
                    "; ".join(f"{k}: {v}" for k, v in VARIANTS.items()))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-unload", action="store_true", help="leave the model loaded afterwards")
    args = ap.parse_args(argv)
    jobs = [j.strip() for j in args.jobs.split(",") if j.strip()]
    bad = [j for j in jobs if j not in JOBS]
    if bad:
        ap.error(f"unknown job(s) {bad}; pick from {JOBS}")
    if args.temperature != "unset":
        try:
            if not 0 <= float(args.temperature) <= 2:
                raise ValueError
        except ValueError:
            ap.error("--temperature takes a number from 0 to 2, or 'unset'")

    es = evalset.load(args.eval_dir)
    cases = build_cases(es, jobs, args.variant)
    if args.limit:
        per = {}
        cases = [c for c in cases if per.setdefault(c["job"], []).append(c) or len(per[c["job"]]) <= args.limit]
    if args.dry_run:
        shown = set()
        for c in cases:
            if c["job"] not in shown:
                shown.add(c["job"])
                print(f"--- {c['job']} ({c['id']})")
                print(json.dumps(request_body(c, args.model, args, 0), indent=2, ensure_ascii=False))
        print(f"{len(cases)} requests in all, eval {es.version}")
        return 0

    client = Ollama(args.host, args.timeout)
    try:
        ver = client.version()
        info = model_info(client, args.model)
    except OllamaError as e:
        msg = str(e)
        if "not found" in msg:
            msg += f" (run: ollama pull {args.model})"
        print("error:", msg, file=sys.stderr)
        return 2
    ctx_max = args.ctx_max or info["context_length"]
    started = datetime.datetime.now().astimezone()
    run_dir = os.path.join(args.out, started.strftime("%Y%m%d-%H%M%S") + "-" + slug(args.model) +
                           "".join("-" + slug(x) for x in (args.variant, temp_label(args.temperature), args.tag) if x))
    base, n = run_dir, 1
    while os.path.exists(run_dir):  # two runs started in the same second
        n += 1
        run_dir = f"{base}-{n}"
    os.makedirs(run_dir)
    meta = {"model": args.model, "digest": info.get("digest", ""), "details": info["details"], "context_length": info["context_length"],
            "capabilities": info["capabilities"], "ollama_version": ver, "host": client.base, "jobs": jobs,
            "eval_version": es.version, "chimera_version_of_prompts": prompts.CHIMERA_VERSION, "chimera_git_of_prompts": prompts.CHIMERA_GIT,
            "seed": args.seed, "think": args.think, "temperature": args.temperature, "variant": args.variant, "samples": args.samples, "ctx_max": ctx_max, "limit": args.limit,
            "started": started.isoformat(timespec="seconds"), "python": platform.python_version(), "machine": platform.node(),
            "differences_from_chimera": ["fixed seed" if args.seed != "none" else None,
                                         f"think={args.think}" if args.think != "unset" else None,
                                         f"temperature={args.temperature} (planner, reviewer)" if args.temperature != "unset" else None,
                                         f"variant={args.variant} ({VARIANTS[args.variant]})" if args.variant else None]}
    meta["differences_from_chimera"] = [d for d in meta["differences_from_chimera"] if d]
    with open(os.path.join(run_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(f"{args.model} ({info['details'].get('parameter_size', '?')}, {info['details'].get('quantization_level', '?')}) "
          f"on {client.base}, eval {es.version} -> {os.path.relpath(run_dir, HERE)}", file=sys.stderr)

    summary = {}
    records = []
    chat_cases = [c for c in cases if c["job"] != "embed"]
    if chat_cases:
        warm = client.chat({"model": args.model, "messages": [{"role": "user", "content": "Reply with OK."}], "stream": True,
                            "keep_alive": "15m", "options": {"num_ctx": cp.ctx_bucket(1000, ctx_max)}})
        if warm["error"]:
            print("error: the model didn't answer a warm-up message:", warm["error"], file=sys.stderr)
            return 2
        meta["warmup_s"] = round(warm["wall_s"], 2)
    total = len(chat_cases) * args.samples
    k = 0
    with open(os.path.join(run_dir, "raw.jsonl"), "w", encoding="utf-8") as raw:
        for c in chat_cases:
            for sample in range(args.samples):
                k += 1
                body = request_body(c, args.model, args, ctx_max)
                call = client.chat(body, GATE_TIMEOUT if c["job"] == "gate" else args.timeout)
                res = validate(c["job"], call["content"], args.variant)
                sc = score_case(c, res, call)
                rec = {"job": c["job"], "id": c["id"], "sample": sample, "options": body["options"],
                       "format": "schema" if isinstance(body["format"], dict) else body["format"], "think": body.get("think"),
                       "reply": call["content"], "thinking": call["thinking"], "stats": call["stats"],
                       "wall_s": round(call["wall_s"], 3) if call["wall_s"] is not None else None,
                       "first_token_s": call["first_token_s"], "first_content_s": call["first_content_s"],
                       "error": call["error"], "format_dropped": call["format_dropped"],
                       "validation": res.to_dict(), "score": sc}
                raw.write(json.dumps(rec, ensure_ascii=False) + "\n")
                raw.flush()
                records.append(rec)
                verdict = ("ERROR " + call["error"]) if call["error"] else ("ok" if res.valid else ("accepted" if res.chimera_ok else "REJECTED"))
                extra = ""
                if c["job"] == "gate":
                    extra = f" use={sc['use']} want={sc['expected']}"
                elif c["job"] == "reviewer":
                    extra = f" done={sc['done']} want={sc['expected_done']}"
                elif sc.get("quality") is not None:
                    extra = f" quality={sc['quality']:.2f}"
                print(f"[{k}/{total}] {c['job']:8} {c['id']:24} {verdict}{extra} {call['wall_s']:.1f}s", file=sys.stderr)
    summary.update(scoring.aggregate(records))
    if "embed" in jobs:
        try:
            summary["embed"] = embed_baseline.run(client, args.model, es)
            print(f"embed: gate AUC {summary['embed']['gate_auc']}, kind accuracy {summary['embed']['kind_accuracy']}", file=sys.stderr)
        except OllamaError as e:
            summary["embed_error"] = str(e)
            print("embed error:", e, file=sys.stderr)
    meta["finished"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    with open(os.path.join(run_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "summary": summary}, f, indent=2, ensure_ascii=False)
    with open(os.path.join(run_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(scoring.render_md(meta, summary, records))
    if not args.no_unload and chat_cases:
        client.unload(args.model)
    print("wrote", os.path.relpath(os.path.join(run_dir, "summary.md"), HERE), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
