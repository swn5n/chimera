"""Scores one model reply against its eval case, and sums them up per job."""
from __future__ import annotations

from collections import Counter

from helper.chimera_port import WORD_RULE_MIN
from helper.validate import valid_after_tidy


def _has_any(text, words):
    t = text.lower()
    return any(w.lower() in t for w in words)


def plan_text(plan):
    parts = [plan.get("title", ""), plan.get("summary", "")]
    for s in plan["steps"]:
        parts += [s.get("title", ""), s.get("instructions", "")]
    return "\n".join(parts)


def score_planner(case, res, call):
    exp = case["planner"]
    out = {"chimera_ok": res.chimera_ok, "valid": res.valid, "valid_tidied": res.valid or valid_after_tidy(res)}
    if not res.chimera_ok:
        out.update(quality=0.0, coverage=0.0, steps_ok=False, kind_ok=False, parallel_ok=False, no_meta=False,
                   missed=[g[0] for g in exp["must_cover"]])
        return out
    plan, m = res.effective, res.metrics
    text = plan_text(plan)
    missed = [g[0] for g in exp["must_cover"] if not _has_any(text, g)]
    n = len(exp["must_cover"])
    lo, hi = exp["steps"]
    parts = {"coverage": (1 - len(missed) / n) if n else 1.0,
             "steps_ok": lo <= m["steps"] <= hi,
             "kind_ok": plan["kind"] in exp["kind"],
             "parallel_ok": m["width"] >= exp["min_parallel"],
             "no_meta": not any(i.code == "meta_step" for i in res.issues)}
    out.update(parts)
    out["quality"] = round(sum(float(v) for v in parts.values()) / len(parts), 4)
    out.update(missed=missed, steps=m["steps"], width=m["width"], depth=m["depth"], kind=plan["kind"])
    return out


def score_reviewer(case, res, call):
    exp = case["expected"]
    eff = res.effective  # a reply Chimera can't read (or a failed call) counts as done
    done = bool(eff["done"])
    lo, hi = exp["score"]
    out = {"chimera_ok": res.chimera_ok, "valid": res.valid, "done": done, "expected_done": exp["done"],
           "done_ok": done == exp["done"], "score": eff["score"] if res.chimera_ok else None,
           "score_ok": bool(res.chimera_ok and lo <= eff["score"] <= hi)}
    if not exp["done"] and not done:
        crit = eff.get("critique") or ""
        named = [_has_any(crit, f["mention"]) for f in case["flaws"]]
        out["primary_flaw_named"] = named[0]
        out["flaws_named"] = round(sum(named) / len(named), 4)
    return out


def score_gate(label, res, call, reach):
    reaches, rel = reach[0], reach[1]
    word_rule = bool(reaches and rel >= WORD_RULE_MIN)
    errored = bool(call.get("error"))
    use = word_rule if errored else bool(res.effective)  # no answer: Chimera's word rule decides
    out = {"chimera_ok": res.chimera_ok and not errored, "valid": res.valid and not errored, "use": use,
           "expected": label["use"], "correct": use == label["use"], "confidence": label["confidence"],
           "reaches": reaches, "relevance": rel, "word_rule_use": word_rule, "pipeline_use": bool(reaches and use)}
    out["pipeline_correct"] = out["pipeline_use"] == label["use"]
    out["word_rule_correct"] = word_rule == label["use"]
    return out


def _rate(xs):
    xs = list(xs)
    return round(sum(1 for x in xs if x) / len(xs), 4) if xs else None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def _pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return round(xs[min(len(xs) - 1, max(0, int(round(q * len(xs) + 0.5)) - 1))], 3)


def gate_counts(scores):
    conf = [s for s in scores if s["confidence"] != "low"]
    tp = sum(1 for s in conf if s["use"] and s["expected"])
    fp = sum(1 for s in conf if s["use"] and not s["expected"])
    fn = sum(1 for s in conf if not s["use"] and s["expected"])
    prec = round(tp / (tp + fp), 4) if tp + fp else None
    rec = round(tp / (tp + fn), 4) if tp + fn else None
    f1 = round(2 * prec * rec / (prec + rec), 4) if prec and rec else (0.0 if prec == 0 or rec == 0 else None)
    return {"pairs": len(conf), "accuracy": _rate(s["correct"] for s in conf), "precision": prec, "recall": rec, "f1": f1,
            "false_positives": fp, "false_negatives": fn,
            "reached_accuracy": _rate(s["correct"] for s in conf if s["reaches"]),
            "pipeline_accuracy": _rate(s["pipeline_correct"] for s in conf),
            "word_rule_accuracy": _rate(s["word_rule_correct"] for s in conf)}


def aggregate(records):
    out = {}
    for job in ("planner", "reviewer", "gate"):
        rs = [r for r in records if r["job"] == job]
        if not rs:
            continue
        sc = [r["score"] for r in rs]
        lat = [r["wall_s"] for r in rs]
        evals = [(r.get("stats") or {}).get("eval_count") for r in rs]
        think = [len(r.get("thinking") or "") for r in rs]
        a = {"n": len(rs), "chimera_ok": _rate(s["chimera_ok"] for s in sc), "valid": _rate(s["valid"] for s in sc),
             "call_errors": sum(1 for r in rs if r.get("error")),
             "latency_p50_s": _pct(lat, 0.5), "latency_p95_s": _pct(lat, 0.95),
             "latency_max_s": round(max(x for x in lat if x is not None), 3) if any(x is not None for x in lat) else None,
             "eval_tokens_mean": _mean(evals), "thinks": _rate(t > 0 for t in think), "thinking_chars_mean": _mean(think),
             "issues": dict(Counter(i["code"] for r in rs for i in r["validation"]["issues"]).most_common())}
        if job == "planner":
            a.update(valid_tidied=_rate(s.get("valid_tidied", s["valid"]) for s in sc),
                     quality=_mean(s["quality"] for s in sc), coverage=_mean(s["coverage"] for s in sc),
                     steps_ok=_rate(s["steps_ok"] for s in sc), kind_ok=_rate(s["kind_ok"] for s in sc),
                     parallel_ok=_rate(s["parallel_ok"] for s in sc), no_meta=_rate(s["no_meta"] for s in sc),
                     steps_mean=_mean(s.get("steps") for s in sc))
        elif job == "reviewer":
            flawed = [s for s in sc if not s["expected_done"]]
            good = [s for s in sc if s["expected_done"]]
            a.update(done_accuracy=_rate(s["done_ok"] for s in sc),
                     flaws_caught=_rate(not s["done"] for s in flawed),
                     good_accepted=_rate(s["done"] for s in good),
                     score_in_band=_rate(s["score_ok"] for s in sc),
                     main_flaw_named=_rate(s["primary_flaw_named"] for s in flawed if "primary_flaw_named" in s))
            checks = [r["validation"].get("metrics", {}) for r in rs]
            if any("check_chars" in m for m in checks):  # the check-first experiment
                a.update(check_first=_rate(m.get("check_first") for m in checks),
                         check_chars_median=_pct([m.get("check_chars") for m in checks], 0.5))
        else:
            a.update(gate_counts(sc))
            a["over_8s"] = sum(1 for x in lat if x is not None and x > 8)
            a["low_confidence_answers"] = {r["id"]: r["score"]["use"] for r in rs if r["score"]["confidence"] == "low"}
        out[job] = a
    return out


def _pc(x):
    return "–" if x is None else f"{100 * x:.0f}%"


def _s(x):
    return "–" if x is None else f"{x:.1f} s"


def render_md(meta, summary, records):
    L = [f"# {meta['model']} on the helper eval ({meta['eval_version']})", "",
         f"{meta['started']} · Ollama {meta['ollama_version']} · digest `{meta.get('digest', '?')[:12]}` · "
         f"think={meta['think']} · seed={meta['seed']} · samples={meta['samples']}" +
         (f" · temperature={meta['temperature']}" if meta.get("temperature") not in (None, "unset") else "") +
         (f" · **experiment: {meta['variant']}** (not Chimera's own request)" if meta.get("variant") else ""), ""]
    p = summary.get("planner")
    if p:
        L += ["## Planner", "", f"Chimera accepts {_pc(p['chimera_ok'])}, strictly valid {_pc(p['valid'])} "
              f"({_pc(p.get('valid_tidied'))} after format-only tidying), "
              f"quality {p['quality']:.2f} (coverage {_pc(p['coverage'])}, step count {_pc(p['steps_ok'])}, "
              f"kind {_pc(p['kind_ok'])}, parallel {_pc(p['parallel_ok'])}, no review step {_pc(p['no_meta'])}). "
              f"Latency p50 {_s(p['latency_p50_s'])}, p95 {_s(p['latency_p95_s'])}; thinks on {_pc(p['thinks'])} of calls.", "",
              "| case | accepted | valid | steps | width | kind | quality | missed | errors |", "|---|---|---|---|---|---|---|---|---|"]
        for r in records:
            if r["job"] != "planner":
                continue
            s = r["score"]
            errs = sorted({i["code"] for i in r["validation"]["issues"] if i["level"] == "error"})
            L.append(f"| {r['id']} | {'yes' if s['chimera_ok'] else 'NO'} | {'yes' if s['valid'] else 'no'} | {s.get('steps', '–')} | "
                     f"{s.get('width', '–')} | {s.get('kind', '–')} | {s['quality']:.2f} | {', '.join(s.get('missed') or []) or '–'} | "
                     f"{', '.join(errs) or '–'} |")
        L.append("")
    v = summary.get("reviewer")
    if v:
        L += ["## Reviewer", "", f"Chimera accepts {_pc(v['chimera_ok'])}, strictly valid {_pc(v['valid'])}, "
              f"done right {_pc(v['done_accuracy'])}: caught {_pc(v['flaws_caught'])} of flawed results, accepted "
              f"{_pc(v['good_accepted'])} of good ones, named the main flaw {_pc(v['main_flaw_named'])} of the time it "
              f"caught one; score in band {_pc(v['score_in_band'])}. Latency p50 {_s(v['latency_p50_s'])}." +
              (f" Check written first {_pc(v['check_first'])}, median {v['check_chars_median']:.0f} characters."
               if v.get("check_chars_median") is not None else ""), "",
              "| case | accepted | expected | said | score | main flaw named |", "|---|---|---|---|---|---|"]
        for r in records:
            if r["job"] != "reviewer":
                continue
            s = r["score"]
            named = s.get("primary_flaw_named")
            L.append(f"| {r['id']} | {'yes' if s['chimera_ok'] else 'NO'} | {'done' if s['expected_done'] else 'not done'} | "
                     f"{'done' if s['done'] else 'not done'} | {s['score'] if s['score'] is not None else '–'} | "
                     f"{'–' if named is None else ('yes' if named else 'no')} |")
        L.append("")
    g = summary.get("gate")
    if g:
        L += ["## Head gate", "", f"On {g['pairs']} confident pairs: accuracy {_pc(g['accuracy'])}, precision {_pc(g['precision'])}, "
              f"recall {_pc(g['recall'])} ({g['false_positives']} false yes, {g['false_negatives']} false no). Through "
              f"Chimera's word filter then the gate: {_pc(g['pipeline_accuracy'])}; word rule alone (no model): "
              f"{_pc(g['word_rule_accuracy'])}. Chimera accepts {_pc(g['chimera_ok'])} of answers. Latency p50 "
              f"{_s(g['latency_p50_s'])}, p95 {_s(g['latency_p95_s'])}, {g['over_8s']} over 8 s.", "",
              "| pair | confidence | expected | gate said | reaches gate | word rule |", "|---|---|---|---|---|---|"]
        for r in records:
            if r["job"] != "gate":
                continue
            s = r["score"]
            mark = "" if s["correct"] else " ✗"
            L.append(f"| {r['id']} | {s['confidence']} | {'use' if s['expected'] else 'no'} | {'use' if s['use'] else 'no'}{mark} | "
                     f"{'yes' if s['reaches'] else 'no'} ({s['relevance']:.2f}) | {'use' if s['word_rule_use'] else 'no'} |")
        L.append("")
    e = summary.get("embed")
    if e:
        L += ["## Zero-shot embedding check", "", f"Gate AUC {e['gate_auc']:.2f} over {e['gate_pairs']} confident pairs "
              f"(1.0 = every right Head scores above every wrong one; 0.5 = chance). Nearest-kind accuracy "
              f"{_pc(e['kind_accuracy'])} on {e['kind_cases']} planner prompts. Nothing was fitted on the eval set.", ""]
    return "\n".join(L) + "\n"
