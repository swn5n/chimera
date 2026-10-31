#!/usr/bin/env python3
"""Write the MLX-LM LoRA config for one training run (no PyYAML needed).

    python3 train/make_config.py --data data/sft --adapters RUN/adapters --out RUN/lora.yaml

Prints {"iters": ..., "train_lines": ...} as JSON. Defaults: Qwen3-4B-Instruct-2507, LoRA rank 16 on
all 36 layers, 2 epochs at batch 4, learning rate 2e-5 with warmup and cosine decay, loss on the
answers only, sequences up to 8,192 tokens with gradient checkpointing.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

DEFAULTS = {"base": "Qwen/Qwen3-4B-Instruct-2507", "epochs": 2.0, "batch": 4, "lr": 2e-5, "lr_end": 2e-6, "warmup": 40,
            "rank": 16, "scale": 20.0, "dropout": 0.05, "layers": 36, "max_seq": 8192, "seed": 0}


def count_lines(path):
    with open(path, encoding="utf-8") as f:
        return sum(1 for l in f if l.strip())


def q(s):
    return json.dumps(str(s))  # a JSON string is a valid YAML scalar


def f(x):
    """A float YAML reads as a float everywhere: "2.00e-05", never "2e-05" (YAML 1.1 reads that as text)."""
    return f"{float(x):.2e}"


def render(a, iters):
    warm = min(a.warmup, max(1, iters // 10))
    return "\n".join([
        "# Written by train/make_config.py; MLX-LM LoRA settings for the Chimera helper model.",
        f"model: {q(a.base)}",
        "train: true",
        "fine_tune_type: lora",
        "optimizer: adamw",
        f"data: {q(os.path.abspath(a.data))}",
        f"seed: {a.seed}",
        f"num_layers: {a.layers}",
        f"batch_size: {a.batch}",
        f"iters: {iters}",
        "val_batches: -1",
        f"learning_rate: {f(a.lr)}",
        "steps_per_report: 10",
        "steps_per_eval: 100",
        "grad_accumulation_steps: 1",
        "resume_adapter_file: null",
        f"adapter_path: {q(os.path.abspath(a.adapters))}",
        "save_every: 100",
        "test: false",
        f"max_seq_length: {a.max_seq}",
        "grad_checkpoint: true",
        "mask_prompt: true",
        "lora_parameters:",
        f"  rank: {a.rank}",
        f"  scale: {float(a.scale):.1f}",
        f"  dropout: {float(a.dropout):.2f}",
        "lr_schedule:",
        "  name: cosine_decay",
        f"  warmup: {warm}",
        "  warmup_init: 1.0e-07",
        f"  arguments: [{f(a.lr)}, {max(1, iters - warm)}, {f(a.lr_end)}]",
        "",
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="folder with train.jsonl and valid.jsonl")
    ap.add_argument("--adapters", required=True)
    ap.add_argument("--out", required=True)
    for k, v in DEFAULTS.items():
        ap.add_argument("--" + k.replace("_", "-"), type=type(v), default=v)
    a = ap.parse_args(argv)
    for name in ("train.jsonl", "valid.jsonl"):
        if not os.path.exists(os.path.join(a.data, name)):
            print(f"missing {os.path.join(a.data, name)}", file=sys.stderr)
            return 2
    n = count_lines(os.path.join(a.data, "train.jsonl"))
    iters = max(1, math.ceil(n * a.epochs / a.batch))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(render(a, iters))
    print(json.dumps({"iters": iters, "train_lines": n, "valid_lines": count_lines(os.path.join(a.data, "valid.jsonl"))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
