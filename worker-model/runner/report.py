#!/usr/bin/env python3
"""Collect every finished baseline run into results/BASELINES.md (tonight's A/B, made by run_baselines.sh).

    python3 runner/report.py                                   # results/runs*, tag "baseline", into results/BASELINES.md
    python3 runner/report.py --tag tiny --runs DIR --task-runs DIR --out DIR/BASELINES.md

EVAL ONLY: it summarises model replies to eval cases; nothing in it is training data.

- Step runs (runner/step_eval.py): every results/runs/*/summary.json on the current eval version whose tag starts
  with --tag, the latest per model, prompt and part group ("W2-W4": the quick subset's W2, W3 and W4 cases; "W1": its
  W1 steps). Per model and prompt: contract kept and form ok, the strict pass in 5.2.2 and 5.0.1, the crash rate over
  the samples Blender checked and over all Blender samples, runaways (in thinking, in content), call errors, API
  errors, tokens and tok/s (medians), wall time.
- T1 (runner/task_eval.py): every results/runs-tasks/* run with the tag (the script runs T1 in chunks of tasks, one
  run folder per chunk and arm), merged per arm and worker model from raw.jsonl (the latest record per task and
  sample), summarised with task_eval.summarize; the phase-1 gate's B against A on the tasks both ran.
- The base-model rule's inputs: gemma4:12b-it-q4_K_M against qwen3:14b under the contract prompt, on the samples
  both runs have, with thinking off (stage g's "think": false, the trained worker's setting: the rule reads these)
  and with think unset as Chimera sends it (stage a); marked "probes still needed": the rule also needs the four
  probes, none of which is run here. Runs are kept apart by their thinking setting (meta.json "think").
- What is frozen in eval/frozen/.
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import math
import os
import random
import sys
from fractions import Fraction

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from runner import cases as C  # noqa: E402
from runner import score, task_eval  # noqa: E402
from runner.common import STEP_RUNS, TASK_RUNS, fmt_pct, md_table, read_json, rel, slug  # noqa: E402

import evalset  # noqa: E402

# run_baselines.sh's lineup, in its order: the two base candidates, today's biggest pool worker, the teacher (the
# ceiling), then the small ones
MODELS = ["qwen3:14b", "gemma4:12b-it-q4_K_M", "qwen3.8:27b", "gpt-oss:120b", "qwen3:8b", "qwen3:4b-instruct-2507-q4_K_M"]
BASES = ("gemma4:12b-it-q4_K_M", "qwen3:14b")  # the base-model rule: Gemma if within 5 points (and its probes pass)
RULE_POINTS = 5.0
ARMS = ("A", "B", "A2", "C")
PROMPTS = ("today", "contract")


def read_jsonl(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def run_tag(run_dir, meta):
    """The run's tag: meta["tag"], else what the folder name has after the model and prompt (older runs)."""
    if meta.get("tag") is not None:
        return meta["tag"]
    name = os.path.basename(run_dir)
    for key in (meta.get("prompt"), slug(meta.get("workers") or "")):
        if key and ("-" + key + "-") in name:
            return name.split("-" + key + "-", 1)[1]
    return ""


def think_key(meta):
    """The run's thinking setting: "off" ("think": false sent), "on" (true) or "unset" (no think field, as Chimera
    0.7.0 sends it; also every run from before the --think option)."""
    t = meta.get("think", "unset")
    return "off" if t is False else "on" if t is True else "unset"


def part_group(meta):
    parts = set(meta.get("parts") or [])
    if not parts:  # older runs: from the case ids
        parts = {("w1" if "/" in c else c.split("-")[0]) for c in meta.get("cases") or []}
    if parts and parts <= {"w2", "w3", "w4f", "w4l"}:
        return "W2-W4"
    if parts == {"w1"}:
        return "W1"
    return "other"


def minutes(meta):
    try:
        a = datetime.datetime.fromisoformat(meta["started"])
        b = datetime.datetime.fromisoformat(meta["finished"])
        return round((b - a).total_seconds() / 60.0, 1)
    except (KeyError, TypeError, ValueError):
        return None


def model_rank(m):
    return (MODELS.index(m), m) if m in MODELS else (len(MODELS), m)


def step_runs(runs_dir, tag, version):
    """{(group, model, prompt, think): (run_dir, summary.json doc)}, the latest run per key."""
    latest = {}
    for path in sorted(glob.glob(os.path.join(runs_dir, "*", "summary.json"))):
        doc = read_json(path) or {}
        m = doc.get("meta") or {}
        d = os.path.dirname(path)
        if m.get("eval_version") != version or not run_tag(d, m).startswith(tag) or not m.get("finished"):
            continue
        latest[(part_group(m), m.get("model"), m.get("prompt"), think_key(m))] = (d, doc)
    return latest


def pair_cell(a, key, b_key=None):
    """"12% / 9%": two rates in one cell."""
    return f"{fmt_pct(a.get(key))} / {fmt_pct(a.get(b_key))}"


def num(v, places):
    """A median for a cell: rounded, "–" when missing."""
    return None if v is None else f"{v:.{places}f}"


def scene_cell(a):
    """strict + scene 5.2.2, with how many samples have scene assertions when that isn't every Blender sample."""
    if a.get("strict_scene_5.2.2") is None:
        return fmt_pct(None)
    n = a.get("scene_n")
    return fmt_pct(a["strict_scene_5.2.2"]) + (f" (of {n})" if n is not None and n != a.get("blender_n") else "")


def runaway_cell(a):
    if not a.get("runaway_n"):
        return fmt_pct(a.get("runaway"))
    return f"{fmt_pct(a['runaway'])} ({a.get('runaway_thinking_n', 0)} th, {a.get('runaway_content_n', 0)} co)"


STEP_HEAD = ["model", "prompt", "samples", "n", "contract kept", "form ok", "Blender n", "strict 5.2.2", "strict 5.0.1",
             "both", "strict + scene 5.2.2", "crash 5.2.2 checked / all", "crash 5.0.1 checked / all", "runaway", "cut off", "call errors",
             "API errors", "repaired", "tokens", "tok/s", "min"]


def step_row(model, prompt, doc):
    m, a = doc["meta"], doc["summary"]["all"]
    return [model, prompt, f"{m.get('samples')} (prose {m.get('prose_samples')})", a["n"], fmt_pct(a.get("contract_ok")),
            fmt_pct(a.get("form_ok")), a.get("blender_n"), fmt_pct(a.get("strict_5.2.2")), fmt_pct(a.get("strict_5.0.1")),
            fmt_pct(a.get("strict_both")), scene_cell(a), pair_cell(a, "crash_checked_5.2.2", "crash_5.2.2"),
            pair_cell(a, "crash_checked_5.0.1", "crash_5.0.1"), runaway_cell(a), fmt_pct(a.get("cut_off")),
            a.get("errors"), a.get("lint_errors_mean"), fmt_pct(a.get("repair_fixed")), num(a.get("tokens_median"), 0),
            num(a.get("tok_s_median"), 1), minutes(m)]


def paired(recs_a, recs_b):
    """The two runs' records restricted to the (case, sample) pairs both have (paired comparison)."""
    keys = {(r["id"], r["sample"]) for r in recs_a} & {(r["id"], r["sample"]) for r in recs_b}
    return ([r for r in recs_a if (r["id"], r["sample"]) in keys], [r for r in recs_b if (r["id"], r["sample"]) in keys])


RULE_SETTINGS = (("off", "Thinking off (stage g, \"think\": false): the rule reads these",
                  "No thinking-off run of both yet (stage g of run_baselines.sh)."),
                 ("unset", "Think unset, as Chimera sends it (stage a): both think", None))


def base_rule(latest):
    """The base-model rule's inputs: both candidates under the contract prompt, per thinking setting and part group,
    paired."""
    L = ["## The base-model rule's inputs (PROBES STILL NEEDED)", "",
         "**Probes still needed: the rule can't pick the base yet.** Probes a, b and c ran on Oct 30 (results/probes/, "
         "and \"Probes a-c\" in docs/hydra-worker-plan.md); d, the fleet, is open. It reads: Gemma 4 12B if all four probes pass "
         "(a: the MLX pilot, b: the round trip into Ollama, c: template parity, d: fit and speed on the 3080 Ti and the "
         "M4 Pro) and its untrained contract score is within 5 points of qwen3:14b; otherwise Qwen3-14B. None of the "
         "probes is run by run_baselines.sh. The score is measured two ways: with thinking off (\"think\": false, "
         "stage g), the setting the trained worker runs in (its template forces thinking off, since Chimera sends no "
         "think field), which is the one the rule reads; and with think unset, as Chimera sends requests today (stage "
         "a), where both models think and can run out of the 8K context. Below, the contract-prompt numbers on the "
         "samples both runs have (paired by case and sample). The plan names the main number \"Blender strict pass "
         "in 5.2.2\"; strict + scene (the stricter reading: the scene the case asks for, too) and contract kept are "
         "shown with it, per part group and over all parts (\"All parts\": every part of the quick subset, the "
         "rule's scope on it; strict + scene has none, as W1 has no scene assertions). These are point estimates on the quick subset. Each gap line also gives the pairs that passed for "
         "one model only, with McNemar's exact p, and a 90% interval from a case bootstrap (the cases resampled, all "
         f"samples of a case kept together, {BOOT:,} rounds, seed {BOOT_SEED}) with how often the gap is -5 or "
         "better: an interval that reaches below -5 means the data can't rule out Gemma being more than 5 points "
         "worse.", ""]
    for think, title, none_yet in RULE_SETTINGS:
        rows, gaps, parts = rule_rows(latest, think)
        L += [f"### {title}", ""]
        if none_yet and all(r[1].startswith("not both run yet") for r in rows[1:]):
            L += [none_yet, ""]
            continue
        L += [md_table(rows), ""]
        if gaps:
            L += ["Gaps (Gemma minus qwen3:14b, exact, over the paired samples each rate counts on both sides; the "
                  "score half of the rule only, untrained, unseeded)" +
                  (". Stage a has one sample per case: read its lines with care." if think == "unset" else ":"), ""]
            L += ["- " + g for g in gaps] + [""]
        if len(parts) > 1:
            L += ["By part (paired samples):", "", md_table(parts), ""]
    return L


def rule_rows(latest, think):
    """The rule's table rows, gap lines and per-part rows for one thinking setting."""
    rows = [["part", "model", "samples paired", "contract kept", "form ok", "strict 5.2.2", "strict both",
             "strict + scene 5.2.2", "crash 5.2.2 checked", "runaway"]]
    gaps, both = [], {}
    for group in ("W2-W4", "W1"):
        runs = [latest.get((group, m, "contract", think)) for m in BASES]
        if not all(runs):
            have = [m for m, r in zip(BASES, runs) if r]
            rows.append([group, "not both run yet" + (f" (have: {', '.join(have)})" if have else ""), "", "", "", "", "",
                         "", "", ""])
            continue
        recs = [read_jsonl(os.path.join(d, "raw.jsonl")) for d, _ in runs]
        if any(r is None for r in recs):
            rows.append([group, "raw.jsonl missing (can't pair)", "", "", "", "", "", "", "", ""])
            continue
        pa, pb = paired(recs[0], recs[1])
        both[group] = (pa, pb)
        aa, ab = score.aggregate(pa)["all"], score.aggregate(pb)["all"]
        for m, a in zip(BASES, (aa, ab)):
            rows.append([group, m, a["n"], fmt_pct(a.get("contract_ok")), fmt_pct(a.get("form_ok")),
                         fmt_pct(a.get("strict_5.2.2")), fmt_pct(a.get("strict_both")), scene_cell(a),
                         fmt_pct(a.get("crash_checked_5.2.2")), runaway_cell(a)])
        gaps += [gap_line(group, what, pa, pb, fn) for what, fn in RULE_GAPS]
    if len(both) == 2:  # the whole worker eval, both part groups together
        pa = both["W2-W4"][0] + both["W1"][0]
        pb = both["W2-W4"][1] + both["W1"][1]
        gaps += [gap_line("All parts", what, pa, pb, fn) for what, fn in RULE_GAPS
                 if all(pair_rate(*both[g], fn) for g in both)]  # a rate one group lacks has no all-parts line
    parts = [["part", "Blender n", "Gemma strict 5.2.2", "qwen3:14b strict 5.2.2", "Gemma strict + scene",
              "qwen3:14b strict + scene"]]
    for group, (pa, pb) in both.items():
        for part in sorted({r["part"] for r in pa}, key=lambda x: ("w1", "w2", "w3", "w4f", "w4l").index(x)
                           if x in ("w1", "w2", "w3", "w4f", "w4l") else 9):
            qa = [r for r in pa if r["part"] == part]
            qb = [r for r in pb if r["part"] == part]
            cells = [pair_rate(qa, qb, fn) for _, fn in RULE_GAPS[:2]]
            if cells[0] is None:
                continue
            parts.append([part.upper(), cells[0][2], f"{cells[0][0][0]}/{cells[0][2]}", f"{cells[0][1][0]}/{cells[0][2]}",
                          f"{cells[1][0][0]}/{cells[1][2]}" if cells[1] else "–",
                          f"{cells[1][1][0]}/{cells[1][2]}" if cells[1] else "–"])
    return rows, [g for g in gaps if g], parts


def _blender_counted(r):
    """A Blender sample that counts in the rates (score.aggregate's blender_n): its call and scoring went through and
    Blender ran or there was nothing to run."""
    return r.get("mode") == "blender" and not r.get("error") and score.blender_status(r) != "not_run"


# The rule's gaps, each over the samples its rate is over: (name, fn(record) -> True/False, or None when the record
# isn't in the rate)
RULE_GAPS = (
    ("strict 5.2.2", lambda r: score.strict(r, "5.2.2") if _blender_counted(r) else None),
    ("strict + scene 5.2.2", lambda r: (score.strict(r, "5.2.2") and bool(score.assertions_ok(r, "5.2.2")))
     if _blender_counted(r) and score.has_assertions(r) else None),
    ("contract kept", lambda r: r["score"]["contract"]["contract_ok"] if not r.get("error") else None),
)
BOOT = 10000  # case-bootstrap resamples
BOOT_SEED = 20261030


def exact_rate(recs, fn):
    """(passes, n) over the records fn counts, or None when it counts none."""
    vals = [v for v in (fn(r) for r in recs) if v is not None]
    return (sum(1 for v in vals if v), len(vals)) if vals else None


def pair_rate(ra, rb, fn):
    """((passes a, n), (passes b, n), n, [(case id, a, b)]) over the (case, sample) pairs fn counts on both sides,
    or None when there are none."""
    kb = {(r["id"], r["sample"]): r for r in rb}
    pairs = []
    for r in ra:
        o = kb.get((r["id"], r["sample"]))
        if o is None:
            continue
        x, y = fn(r), fn(o)
        if x is not None and y is not None:
            pairs.append((r["id"], bool(x), bool(y)))
    if not pairs:
        return None
    return (sum(p[1] for p in pairs), len(pairs)), (sum(p[2] for p in pairs), len(pairs)), len(pairs), pairs


def mcnemar_p(b, c):
    """Exact two-sided McNemar p from the discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def case_bootstrap(pairs, rounds=BOOT, seed=BOOT_SEED):
    """(lo, hi, p): the 90% interval of the gap (points, a minus b) over cases resampled with replacement (all
    samples of a case kept together), and the share of resamples with the gap at least -RULE_POINTS."""
    by = {}
    for cid, x, y in pairs:
        s = by.setdefault(cid, [0, 0, 0])
        s[0] += x
        s[1] += y
        s[2] += 1
    cases = list(by.values())
    rng = random.Random(seed)
    gaps = []
    for _ in range(rounds):
        a = b = n = 0
        for _ in cases:
            x, y, k = cases[rng.randrange(len(cases))]
            a, b, n = a + x, b + y, n + k
        gaps.append(Fraction(100 * (a - b), n))
    gaps.sort()
    return float(gaps[int(0.05 * rounds)]), float(gaps[int(0.95 * rounds) - 1]), \
        sum(1 for g in gaps if g >= -RULE_POINTS) / rounds


def gap_line(group, what, pa, pb, fn):
    """One gap line: both counts over the pairs the rate counts on both sides, the exact gap and its verdict, the
    one-sided pairs and McNemar's p, and the case bootstrap."""
    got = pair_rate(pa, pb, fn)
    if got is None:
        return None
    (xa, n), (xb, _), _, pairs = got
    gap = Fraction(100 * (xa - xb), n)
    only_a = sum(1 for _, x, y in pairs if x and not y)
    only_b = sum(1 for _, x, y in pairs if y and not x)
    lo, hi, p = case_bootstrap(pairs)
    return (f"{group} {what}: Gemma {xa}/{n}, qwen3:14b {xb}/{n}: {gap_words(gap)}; one-sided pairs {only_a} Gemma, "
            f"{only_b} qwen3:14b (McNemar p {p_cell(mcnemar_p(only_a, only_b))}); 90% interval {lo:+.1f} to {hi:+.1f} "
            f"over {len({c for c, _, _ in pairs})} cases, gap -{RULE_POINTS:.0f} or better in {100 * p:.0f}% of "
            f"resamples")


def p_cell(p):
    return "< 0.01" if p < 0.01 else f"{p:.2f}"


def gap_words(gap):
    """A gap line's verdict on the score half of the rule (Gemma at most RULE_POINTS behind), from the exact gap
    (a Fraction, so a gap of exactly -5 isn't misread through float error)."""
    if gap >= 0:
        verdict = "Gemma ahead or level"
    elif gap >= -RULE_POINTS:
        verdict = f"Gemma behind, by no more than {RULE_POINTS:.0f}"
    else:
        verdict = f"Gemma more than {RULE_POINTS:.0f} points behind"
    shown = f"{float(gap):+.1f}"
    if shown in ("-5.0", "+5.0") and gap != int(gap):  # the verdict is the exact value's: show enough to see it
        shown = f"{float(gap):+.2f}"
    return f"{shown} points ({verdict})"


def task_runs(task_dir, tag, version):
    """{(arm, workers): [records]} from every task run with the tag, the latest record per (task, sample), plus
    {(arm, workers): [meta]}."""
    recs, metas = {}, {}
    for path in sorted(glob.glob(os.path.join(task_dir, "*", "meta.json"))):
        m = read_json(path) or {}
        d = os.path.dirname(path)
        if m.get("eval_version") != version or not run_tag(d, m).startswith(tag) or not m.get("finished"):
            continue
        key = (m.get("arm"), m.get("workers"))
        metas.setdefault(key, []).append(m)
        got = read_jsonl(os.path.join(d, "raw.jsonl")) or []
        by = recs.setdefault(key, {})
        for r in got:
            by[(r["task"], r.get("sample", 0))] = r
    return {k: list(v.values()) for k, v in recs.items()}, metas


T1_HEAD = ["arm", "prompt, workers, joining", "tasks", "Blender n", "pass 5.2.2", "5.0.1", "both", "Python n",
           "Python pass", "fallback", "seams", "cut off", "runaway", "steps kept the contract", "steps in exact form",
           "one script", "total min", "tokens"]


def t1_section(task_dir, tag, version):
    recs, metas = task_runs(task_dir, tag, version)
    L = ["## T1: whole frozen plans, arms side by side", ""]
    if not recs:
        return L + ["No T1 run finished yet (stage d of run_baselines.sh; it needs frozen plans, stage b).", ""]
    rows = [T1_HEAD]
    keys = sorted(recs, key=lambda k: (ARMS.index(k[0]) if k[0] in ARMS else 9, k[1] or ""))
    for arm, workers in keys:
        s = task_eval.summarize(recs[(arm, workers)])
        spec = task_eval.ARMS.get(arm, {})
        rows.append([arm, f"{spec.get('prompt')}, {workers}, {spec.get('joining')}", s["n"], s["blender_n"],
                     fmt_pct(s["pass_5.2.2"]), fmt_pct(s["pass_5.0.1"]), fmt_pct(s["pass_both"]), s["python_n"],
                     fmt_pct(s["python_pass"]), fmt_pct(s["fallback"]), s["seams_mean"], fmt_pct(s["cut"]),
                     fmt_pct(s["runaway"]), fmt_pct(s["steps_contract_ok"]), fmt_pct(s.get("steps_form_ok")),
                     fmt_pct(s["one_script"]), round(s["wall_s_total"] / 60.0, 1), s["tokens_total"]])
    combine = sorted({m.get("combine_model") for ms in metas.values() for m in ms})
    L += [md_table(rows), "",
          f"Combine (and fallback) model: {', '.join(c for c in combine if c)}. One pass, round 1, steps one at a time "
          "(so the wall times are sums, not Chimera's parallel time); no reviewer tonight unless REVIEW was set; no "
          "seam pass (seams are only counted). Pass rates are over every task of the kind; a result that wasn't "
          "checked (cut off, runaway, several scripts, no script, a joined Python script with no entry point) is a "
          "fail. Multi-file plans aren't in T1 tonight (the check can't run them).", ""]
    # The phase-1 gate: B at least A on T1 Blender and code passes, on the tasks both arms ran
    gate = []
    for a_arm, b_arm in (("A", "B"), ("A2", "C")):
        ka = [k for k in recs if k[0] == a_arm]
        kb = [k for k in recs if k[0] == b_arm]
        if not ka or not kb:
            continue
        ra, rb = recs[ka[0]], recs[kb[0]]
        shared = {r["task"] for r in ra} & {r["task"] for r in rb}
        sa = task_eval.summarize([r for r in ra if r["task"] in shared])
        sb = task_eval.summarize([r for r in rb if r["task"] in shared])
        gate.append(f"- {b_arm} against {a_arm} on the {len(shared)} tasks both ran: Blender pass in both versions "
                    f"{fmt_pct(sb['pass_both'])} against {fmt_pct(sa['pass_both'])} ({sb['blender_n']} Blender tasks), "
                    f"Python pass {fmt_pct(sb['python_pass'])} against {fmt_pct(sa['python_pass'])} "
                    f"({sb['python_n']} Python tasks)")
    if gate:
        L += ["Paired, on the same tasks (the phase-1 gate is B at least A on T1 Blender and code passes; tonight's "
              "T1 is the script's subset, not the plan's 30 tasks):", ""] + gate + [""]
    return L


def frozen_section(frozen_dir):
    plans, deps = C.load_frozen(frozen_dir)
    L = [f"## Frozen W1 inputs ({rel(frozen_dir)})", ""]
    if not plans:
        return L + ["Nothing frozen yet (stage b).", ""]
    by = {}
    for p in plans.values():
        by[p.get("planner_model") or "none"] = by.get(p.get("planner_model") or "none", 0) + 1
    st = [s for d in deps.values() for s in (d.get("steps") or {}).values()]
    today = [s["today"] for s in st if s.get("today")]
    L += [f"- Plans: {len(plans)} frozen ({', '.join(f'{v} from {k}' for k, v in sorted(by.items()))}).",
          f"- Dependency outputs: {sum(1 for s in st if s.get('status') == 'verified')} verified, "
          f"{sum(1 for s in st if s.get('status') == 'rejected')} rejected, over {len(deps)} tasks; today's-format: "
          f"{sum(1 for t in today if t.get('status') == 'verified')} verified of {len(today)}.", ""]
    return L


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", default=STEP_RUNS)
    ap.add_argument("--task-runs", default=TASK_RUNS)
    ap.add_argument("--frozen", default=C.FROZEN_DIR)
    ap.add_argument("--tag", default="baseline", help="count only runs whose tag starts with this (default baseline)")
    ap.add_argument("--out", default=os.path.join(HERE, "results", "BASELINES.md"))
    a = ap.parse_args(argv)
    es = evalset.load()
    latest = step_runs(a.runs, a.tag, es.version)
    L = ["# Hydra Worker baselines (tonight's A/B)", "",
         f"Eval {es.version}. EVAL ONLY: model replies to eval cases; never training data. Made by `runner/report.py` "
         f"from the runs tagged \"{a.tag}…\" (`bash run_baselines.sh`); each row is the latest finished run. Requests "
         "are Chimera 0.7.0's (no seed, temperature, think or num_predict; unseeded at each model's defaults; stage g "
         "alone sends \"think\": false), except the runners' two limits: a worker step's content is cut at 6,144 tokens and every reply, thinking included, "
         "at 16,384 (a runaway, a fail; \"th\" in thinking, \"co\" in content).", ""]
    for think, group, what in (("unset", "W2-W4", "the quick subset's W2, W3 and W4 cases (stage a)"),
                               ("unset", "W1", "the quick subset's W1 steps on the frozen plans (stage c)"),
                               ("off", "W2-W4", "the base candidates with thinking off, W2-W4 (stage g)"),
                               ("off", "W1", "the base candidates with thinking off, W1 steps (stage g)")):
        keys = sorted((k for k in latest if k[0] == group and k[3] == think),
                      key=lambda k: (model_rank(k[1]), PROMPTS.index(k[2]) if k[2] in PROMPTS else 9))
        L += [f"## Step level: {what}", ""]
        if not keys:
            L += ["No run finished yet.", ""]
            continue
        L += [md_table([STEP_HEAD] + [step_row(k[1], k[2], latest[k][1]) for k in keys]), ""]
        lineup, prompts = (MODELS, PROMPTS) if think == "unset" else (BASES, ("contract",))
        missing = [f"{m} {p}" for m in lineup for p in prompts if (group, m, p, think) not in latest]
        if missing:
            L += ["Not run yet: " + ", ".join(missing) + ".", ""]
    L += ["Columns: contract kept (the contract's shape, which Chimera joins: the near-miss handoff forms count; a "
          "piece whose code has a syntax error keeps the shape but fails strict, and joining sends it to the combine), "
          "form ok (the exact form, what data generation keeps); strict (not a runaway, Chimera's check passed with no "
          "Traceback or Error: line, and the direct run's whole output has none; a piece that isn't joined still gets "
          "its build_sN called, since Oct 30); strict + scene (strict, and the eval's scene assertions hold, over the "
          "samples whose case has assertions, \"of n\" when that isn't all: a script that runs clean but skips the job "
          "fails it; W1 has none); crash (the check's outcome failed: "
          "over the samples Blender checked, the plan's \"at most 10%\", and over all Blender samples, where no script "
          "isn't a crash); call errors (calls that failed outright, left out of the rates); API errors "
          "(tools/rna_lint.py errors per reply); repaired (W3, fixed in the crash's version); tokens and tok/s (medians "
          "per reply, thinking included); min (the run's wall time). Samples: Blender and code cases get the samples "
          "shown, prose 1 (see the script's header for why some models get fewer than the plan's 3).", ""]
    L += base_rule(latest)
    L += t1_section(a.task_runs, a.tag, es.version)
    L += frozen_section(a.frozen)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(L).rstrip() + "\n")
    print("wrote", a.out, f"({len(latest)} step runs)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
