#!/usr/bin/env python3
"""Write results/TRAINING-<name>.md: the run's settings, losses and eval scores next to the baselines.

    python3 train/summarize.py --name v1 --run ~/chimera-tools/helper-train/v1 --model chimera-helper:v1
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# MLX-LM up to ~0.2x printed "Iter 10: Train loss 1.650, ..., Tokens/sec 2410.5, ..., Peak mem 21.7 GB".
TRAIN_RE = re.compile(r"Iter (\d+): Train loss ([0-9.]+)")
VAL_RE = re.compile(r"Iter (\d+): Val loss ([0-9.]+)")
SPEED_RE = re.compile(r"Tokens/sec ([0-9.]+)")
MEM_RE = re.compile(r"[Pp]eak mem(?:ory)?:?\s*([0-9.]+)\s*GB")
# MLX-LM 0.32 prints a table instead: "    10    1.666 ▼       99      7.6k" and "     1    val 1.521    48.67s"
# (tok/s there counts only the tokens the loss is taken on: with mask_prompt, the answers).
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
ROW_RE = re.compile(r"^\s*(\d+)\s+([0-9]*\.[0-9]+)\s*\S?\s+([0-9.,]+)\s+[0-9.,]+[kKMG]?\s*$")
VALROW_RE = re.compile(r"^\s*(\d+)\s+val\s+([0-9]*\.[0-9]+)")


def parse_log(text):
    text = ANSI_RE.sub("", text)
    train = [(int(i), float(v)) for i, v in TRAIN_RE.findall(text)]
    val = [(int(i), float(v)) for i, v in VAL_RE.findall(text)]
    speeds = [float(x) for x in SPEED_RE.findall(text)]
    for line in text.splitlines():
        m = VALROW_RE.match(line)
        if m:
            val.append((int(m.group(1)), float(m.group(2))))
            continue
        m = ROW_RE.match(line)
        if m:
            train.append((int(m.group(1)), float(m.group(2))))
            speeds.append(float(m.group(3).replace(",", "")))
    mem = [float(x) for x in MEM_RE.findall(text)]
    return {"train": train, "val": val, "tokens_per_s": round(sum(speeds) / len(speeds)) if speeds else None,
            "peak_mem_gb": max(mem) if mem else None}


def helper_models(exclude):
    """The other chimera-helper versions that have a full standard run, oldest name first."""
    names = set()
    for p in glob.glob(os.path.join(HERE, "results", "runs", "*", "summary.json")):
        with open(p, encoding="utf-8") as f:
            m = json.load(f)["meta"]
        if m["model"].startswith("chimera-helper:") and m["model"] != exclude:
            names.add(m["model"])
    return sorted(names)


def latest_summary(model, eval_version):
    best = None
    for p in sorted(glob.glob(os.path.join(HERE, "results", "runs", "*", "summary.json"))):
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        m = d["meta"]
        if (m["model"] == model and m["eval_version"] == eval_version and not m.get("limit") and m["think"] == "unset"
                and not m.get("variant") and {"planner", "reviewer", "gate"} <= set(m["jobs"])):
            best = d
    return best


def pc(x):
    return "–" if x is None else f"{100 * x:.0f}%"


def row(label, s):
    if not s:
        return f"| {label} | – | – | – | – | – |"
    p, r, g = s["summary"].get("planner", {}), s["summary"].get("reviewer", {}), s["summary"].get("gate", {})
    q = p.get("quality")
    return (f"| {label} | {'–' if q is None else f'{q:.2f}'} ({pc(p.get('valid'))} strict) | {pc(r.get('done_accuracy'))} "
            f"(caught {pc(r.get('flaws_caught'))}, accepted good {pc(r.get('good_accepted'))}) | {pc(g.get('accuracy'))} | "
            f"{p.get('latency_p50_s', '–')} s / {r.get('latency_p50_s', '–')} s / {g.get('latency_p50_s', '–')} s |")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    ap.add_argument("--run", required=True, help="the run folder (lora.yaml, train.log, import.txt)")
    ap.add_argument("--model", required=True, help="the Ollama name it was scored under")
    a = ap.parse_args(argv)
    sys.path.insert(0, HERE)
    from helper import evalset
    ver = evalset.load().version

    def read(name):
        p = os.path.join(a.run, name)
        return open(p, encoding="utf-8").read() if os.path.exists(p) else ""

    log = parse_log(read("train.log"))
    L = [f"# Helper model {a.name}: training and eval", "",
         f"LoRA on Qwen3-4B-Instruct-2507 with MLX-LM, imported into Ollama as `{a.model}` and scored on eval {ver} with "
         "Chimera's exact requests (`runner/run_eval.py`). Files: `" + a.run + "`.", "",
         "## Training", ""]
    if log["train"]:
        t0, t1 = log["train"][0], log["train"][-1]
        L.append(f"- Train loss {t0[1]:.3f} at step {t0[0]} → {t1[1]:.3f} at step {t1[0]}.")
    if log["val"]:
        v0, v1 = log["val"][0], log["val"][-1]
        vmin = min(log["val"], key=lambda x: x[1])
        L.append(f"- Validation loss {v0[1]:.3f} at step {v0[0]} → {v1[1]:.3f} at step {v1[0]} (lowest {vmin[1]:.3f} at step {vmin[0]}).")
        if vmin[0] < v1[0] and v1[1] > vmin[1] * 1.05:
            L.append("- Validation loss rose after its low point: some overfitting; an earlier checkpoint may score better.")
    if log["tokens_per_s"]:
        L.append(f"- About {log['tokens_per_s']} trained tokens/s" + (f"; peak memory {log['peak_mem_gb']} GB." if log["peak_mem_gb"] else "."))
    try:
        start = os.path.getmtime(os.path.join(a.run, "lora.yaml"))
        end = os.path.getmtime(os.path.join(a.run, "train.log"))
        L.append(f"- Training took about {(end - start) / 60:.0f} minutes, including the first download of the base model.")
    except OSError:
        pass
    imp = read("import.txt").strip()
    if imp:
        L.append(f"- Into Ollama: {imp}")
    L += ["", "Settings (`lora.yaml`):", "", "```yaml", read("lora.yaml").strip(), "```", "",
          "## Eval", "",
          "| Model | Plan quality (strictly valid) | Reviewer right | Gate right | p50: plan / review / gate |",
          "|---|---|---|---|---|",
          row(f"**{a.model} (this run)**", latest_summary(a.model, ver)),
          *[row(f"{m} (earlier)", latest_summary(m, ver)) for m in helper_models(a.model) if latest_summary(m, ver)],
          row("qwen3:4b-instruct-2507 (the base, untrained)", latest_summary("qwen3:4b-instruct-2507-q4_K_M", ver)),
          row("qwen3:4b, thinking (best stock)", latest_summary("qwen3:4b", ver)),
          row("gpt-oss:120b (teacher)", latest_summary("gpt-oss:120b", ver)), "",
          "Full per-case detail: `results/runs/<time>-" + re.sub(r"[^A-Za-z0-9._-]+", "-", a.model) + "*/summary.md`; "
          "case by case against another run: `python3 runner/compare.py <run> <run>`."]
    mine = latest_summary(a.model, ver)
    rv = (mine or {}).get("summary", {}).get("reviewer", {})
    if rv.get("check_chars_median") is not None:
        L += ["", f"The reviewer wrote its check first in {pc(rv.get('check_first'))} of replies (median "
              f"{rv['check_chars_median']:.0f} characters); Chimera ignores the field and reads the same verdict."]
    out = os.path.join(HERE, "results", f"TRAINING-{a.name}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("wrote", os.path.relpath(out, HERE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
