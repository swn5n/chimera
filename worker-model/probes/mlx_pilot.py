#!/usr/bin/env python3
"""Probe (a), the MLX pilot: LoRA training speed and peak memory for Gemma 4 12B on the Studio, with the plan's
training settings, on 40 examples shaped to the plan's lengths.

    ~/chimera-tools/helper-train/.venv/bin/python probes/mlx_pilot.py --hf DIR --work ~/chimera-tools/worker-train/probes

The bar (docs/hydra-worker-plan.md, base model): 60 tok/s or more in all (prompts included, as the plan's time
estimate counts them) with peak memory under 75 GB. MLX-LM's own "Tokens/sec" counts answer tokens only.

Settings from the plan's TRAINING section: LoRA on all 48 layers (the default keys), rank 32, scale 20, dropout 0.05,
AdamW at 2e-5, batch 1 x gradient accumulation 8, max_seq_length 12,288, mask_prompt and grad_checkpoint on. The 40
examples run once each (40 iterations, one pass, so the tokens processed are known exactly). Lengths follow the
plan's data: mostly short (about 3,000 tokens on average over about 1,700 examples, 5.1M tokens), some long inputs
(5-8K) and a few near the 12,288 limit (11,677-11,824 here), which set the peak memory.

The examples' text is Hydra 1.0's own training data (helper-model/data/sft-v3, gpt-oss:120b's answers to Chimera's
helper requests: no Claude output), cut and stitched to those lengths; the adapter isn't used for anything. Training runs on a
local copy of the base folder whose chat template is the worker training template (probes/template_parity.py's
worker_template: thinking off, and an assistant turn starts with the empty thought block), as the real training will,
through probes/mlx_train_driver.py with MLX's cache capped at 8 GB, as the real training must (--cache-limit-gb 0 runs
uncapped). Token counts come from MLX-LM's own tokenizer and dataset code. The plan says "20 iterations on 40
examples"; at batch 1 that can't cover them, so this is one pass of the 40. The first try is kept as
results/probes/probe-a-first-try.json: same settings, no cache cap, and (as the audit found) on the stock prompt,
because MLX-LM's wrapper turned thinking on.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from probes.template_parity import worker_template  # noqa: E402

REPO = os.path.dirname(HERE)
SOURCE = os.path.join(REPO, "helper-model", "data", "sft-v3", "train.jsonl")
MAX_SEQ = 12288
# (count, total tokens low, high, answer tokens low, high): 40 examples, about 3,900 tokens on average
SHAPE = [(30, 1500, 3200, 300, 1200), (6, 5000, 8000, 800, 2500), (4, 11600, 12200, 1500, 3400)]
SETTINGS = {"num_layers": 48, "rank": 32, "scale": 20.0, "dropout": 0.05, "lr": 2e-5, "batch": 1, "grad_accum": 8}


def base_folder(hf, out):
    """A folder with the base's files linked and the worker training template as its chat template."""
    os.makedirs(out, exist_ok=True)
    for name in os.listdir(hf):
        dst = os.path.join(out, name)
        if name == "chat_template.jinja" or os.path.lexists(dst):
            continue
        os.symlink(os.path.realpath(os.path.join(hf, name)), dst)
    with open(os.path.join(hf, "chat_template.jinja"), encoding="utf-8") as f:
        stock = f.read()
    with open(os.path.join(out, "chat_template.jinja"), "w", encoding="utf-8") as f:
        f.write(worker_template(stock))
    return out


def real_lengths(base, data):
    """Each row's tokens as MLX-LM counts them."""
    from pathlib import Path

    from mlx_lm.tuner.datasets import ChatDataset
    from mlx_lm.utils import load_tokenizer
    wrapper = load_tokenizer(Path(base))
    with open(os.path.join(data, "train.jsonl"), encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    return [len(ChatDataset([r], wrapper, mask_prompt=True).process(r)[0]) for r in rows]


def build_data(tok, out, seed=20261030):
    """train.jsonl (40) and valid.jsonl (2) in the chat format, each example's tokens in its SHAPE range."""
    rng = random.Random(seed)
    with open(SOURCE, encoding="utf-8") as f:
        src = [json.loads(l)["messages"] for l in f if l.strip()]
    users = [m["content"] for ms in src for m in ms if m["role"] == "user"]
    answers = [m["content"] for ms in src for m in ms if m["role"] == "assistant"]
    system = next(m["content"] for m in src[0] if m["role"] == "system")

    def stitch(pool, want):
        parts, n = [], 0
        while n < want:
            t = rng.choice(pool)
            parts.append(t)
            n += len(tok(t, add_special_tokens=False)["input_ids"]) + 2
        return "\n\n".join(parts)

    def cut(text, want):
        ids = tok(text, add_special_tokens=False)["input_ids"]
        return tok.decode(ids[:want]) if len(ids) > want else text

    rows = []
    for count, lo, hi, alo, ahi in SHAPE:
        for _ in range(count):
            total, ans_n = rng.randint(lo, hi), rng.randint(alo, ahi)
            answer = cut(stitch(answers, ans_n), ans_n)
            sys_n = len(tok(system, add_special_tokens=False)["input_ids"])
            user = cut(stitch(users, total - ans_n - sys_n), max(50, total - ans_n - sys_n - 20))
            msgs = [{"role": "system", "content": system}, {"role": "user", "content": user},
                    {"role": "assistant", "content": answer}]
            n = len(tok.apply_chat_template(msgs, return_dict=False))
            if n > MAX_SEQ:  # trim the prompt to fit: MLX-LM would cut the answer instead
                user = cut(user, len(tok(user, add_special_tokens=False)["input_ids"]) - (n - MAX_SEQ) - 8)
                msgs[1]["content"] = user
                n = len(tok.apply_chat_template(msgs, return_dict=False))
            rows.append({"messages": msgs, "_tokens": n})
    rng.shuffle(rows)
    os.makedirs(out, exist_ok=True)
    for name, part in (("train.jsonl", rows), ("valid.jsonl", rows[:2])):
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            for r in part:
                f.write(json.dumps({"messages": r["messages"]}, ensure_ascii=False) + "\n")
    return [r["_tokens"] for r in rows]


def config(model, data, adapters, iters):
    s = SETTINGS
    return "\n".join([
        "# probe (a), the MLX pilot: the plan's worker training settings, 40 iterations",
        f"model: {json.dumps(model)}", "train: true", "fine_tune_type: lora", "optimizer: adamw",
        f"data: {json.dumps(data)}", "seed: 0", f"num_layers: {s['num_layers']}", f"batch_size: {s['batch']}",
        f"iters: {iters}", "val_batches: 1", f"learning_rate: {s['lr']:.2e}", "steps_per_report: 4",
        f"steps_per_eval: {iters * 10}", f"grad_accumulation_steps: {s['grad_accum']}",
        f"adapter_path: {json.dumps(adapters)}", f"save_every: {iters * 10}", "test: false",
        f"max_seq_length: {MAX_SEQ}", "grad_checkpoint: true", "mask_prompt: true",
        "lora_parameters:", f"  rank: {s['rank']}", f"  scale: {s['scale']}", f"  dropout: {s['dropout']}", ""])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hf", required=True, help="the Hugging Face model folder")
    ap.add_argument("--work", required=True, help="where the pilot's folders go")
    ap.add_argument("--out", default=os.path.join(HERE, "results", "probes", "probe-a.json"))
    ap.add_argument("--cache-limit-gb", type=float, default=8.0)
    a = ap.parse_args(argv)
    from transformers import AutoTokenizer
    base = base_folder(a.hf, os.path.join(a.work, "base-worker-template"))
    tok = AutoTokenizer.from_pretrained(base)
    data = os.path.join(a.work, "pilot-data")
    build_data(tok, data)
    lengths = real_lengths(base, data)
    iters = len(lengths)
    cfg = os.path.join(a.work, "pilot.yaml")
    adapters = os.path.join(a.work, "pilot-adapters")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(config(base, data, adapters, iters))
    log = os.path.join(a.work, "pilot-train.log")
    reports = os.path.join(a.work, "pilot-reports.jsonl")
    driver = os.path.join(HERE, "probes", "mlx_train_driver.py")
    t0 = time.time()
    with open(log, "w", encoding="utf-8") as lf:
        p = subprocess.run([sys.executable, driver, "-c", cfg, "--report", reports, "--cache-limit-gb",
                            str(a.cache_limit_gb)], stdout=lf, stderr=subprocess.STDOUT)
    wall = time.time() - t0
    its, memory = [], {}
    if os.path.exists(reports):
        with open(reports, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("kind") == "memory":
                    memory = r
                elif r.get("kind") == "train":
                    its.append({"iter": r["iteration"], "loss": r["train_loss"], "it_s": r["iterations_per_second"],
                                "answer_tok_s": r["tokens_per_second"], "trained": r["trained_tokens"],
                                "peak_gb": r["peak_memory"]})
    # Training time from MLX-LM's own It/sec over each report window (it times only the training steps: no model
    # load, no validation), so tokens in all per second = the pass's tokens over that time.
    train_s = 0.0
    prev = 0
    for r in its:
        train_s += (r["iter"] - prev) / r["it_s"] if r["it_s"] else 0.0
        prev = r["iter"]
    done = its[-1]["iter"] if its else 0
    total = sum(lengths) if done == iters else None
    res = {"exit": p.returncode, "iters_done": done, "examples": iters, "tokens_all": sum(lengths),
           "tokens_mean": round(sum(lengths) / len(lengths)), "tokens_max": max(lengths),
           "answer_tokens_trained": its[-1]["trained"] if its else None,
           "train_seconds": round(train_s, 1), "wall_seconds": round(wall, 1),
           "tok_s_all": round(total / train_s, 1) if total and train_s else None,
           "tok_s_answers": round(its[-1]["trained"] / train_s, 1) if its and train_s else None,
           "peak_gb": max((r["peak_gb"] for r in its), default=None), "memory": memory, "reports": its,
           "settings": SETTINGS,
           "max_seq": MAX_SEQ, "shape": SHAPE, "log": log, "config": cfg,
           "bar": {"tok_s_all_min": 60, "peak_gb_max": 75}}
    res["pass"] = bool(res["tok_s_all"] and res["peak_gb"] and res["tok_s_all"] >= 60 and res["peak_gb"] < 75)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "reports"}, indent=1))
    return 0 if p.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
