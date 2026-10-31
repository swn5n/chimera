#!/usr/bin/env python3
"""MLX-LM's LoRA training (mlx_lm lora -c CONFIG) with its per-report numbers written as JSON lines: MLX-LM 0.32.2's
console shows only loss, answer tok/s and tokens, and its run() drops a training callback, so this does what
mlx_lm.lora.main and run do, with one.

    ~/chimera-tools/helper-train/.venv/bin/python probes/mlx_train_driver.py -c pilot.yaml --report reports.jsonl

--cache-limit-gb caps MLX's buffer cache, which `mlx_lm lora` can't: without a cap MLX holds up to about 79 GB of
active plus cached memory on the Studio, and a 9.5 GB Ollama model loaded alongside crashed a near-limit example
with a Metal out-of-memory error (Oct 30 audit); at 8 GB active plus cache stayed at 66.6 GB. --report also gets the
peaks of active plus cache and of the system's wired memory, sampled every 2 s, as a last line of kind "memory".
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import types


def wired_gb():
    """The system's wired memory, from vm_stat."""
    text = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
    page = int(re.search(r"page size of (\d+)", text).group(1))
    return int(re.search(r"Pages wired down:\s+(\d+)", text).group(1)) * page / 1e9


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", required=True)
    ap.add_argument("--report", required=True, help="JSON lines: every train and val report")
    ap.add_argument("--cache-limit-gb", type=float, default=0, help="MLX's buffer cache limit (0: MLX's own default)")
    a = ap.parse_args(argv)
    os.environ["TOKENIZERS_PARALLELISM"] = "true"
    import mlx.core as mx
    import numpy as np
    import yaml
    from mlx_lm import lora
    from mlx_lm.tuner.callbacks import TrainingCallback
    from mlx_lm.utils import load

    args = vars(lora.build_parser().parse_args([]))
    with open(a.config, encoding="utf-8") as f:
        cfg = yaml.load(f, lora.yaml_loader)
    for k, v in cfg.items():
        args[k] = v
    for k, v in lora.CONFIG_DEFAULTS.items():
        if args.get(k) is None:
            args[k] = v
    args = types.SimpleNamespace(**args)

    out = open(a.report, "w", encoding="utf-8")

    class Report(TrainingCallback):
        def on_train_loss_report(self, info):
            out.write(json.dumps(dict(info, kind="train")) + "\n")
            out.flush()

        def on_val_loss_report(self, info):
            out.write(json.dumps(dict(info, kind="val")) + "\n")
            out.flush()

    if a.cache_limit_gb:
        mx.set_cache_limit(int(a.cache_limit_gb * 1e9))
    peaks = {"active_plus_cache_gb": 0.0, "wired_gb": 0.0}
    stop = threading.Event()

    def sample():
        while not stop.wait(2.0):
            peaks["active_plus_cache_gb"] = max(peaks["active_plus_cache_gb"],
                                                (mx.get_active_memory() + mx.get_cache_memory()) / 1e9)
            peaks["wired_gb"] = max(peaks["wired_gb"], wired_gb())

    threading.Thread(target=sample, daemon=True).start()
    np.random.seed(args.seed)
    model, tokenizer = load(args.model, tokenizer_config={"trust_remote_code": False})
    train_set, valid_set, _ = lora.load_dataset(args, tokenizer)
    lora.train_model(args, model, train_set, valid_set, Report())
    stop.set()
    out.write(json.dumps(dict(peaks, kind="memory", cache_limit_gb=a.cache_limit_gb)) + "\n")
    out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
