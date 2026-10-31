#!/usr/bin/env python3
"""Write an Ollama Modelfile for the trained model: our weights, with the base model's chat template,
parameters and licence copied from Ollama, so the helper is prompted exactly as the base was.

    ollama show qwen3:4b-instruct-2507-q4_K_M --modelfile > base.Modelfile
    python3 train/make_modelfile.py --base base.Modelfile --from RUN/fused --out RUN/Modelfile
    python3 train/make_modelfile.py ... --temperature 0.2 --num-predict 4096   # other defaults for Chimera's calls

Chimera sets no temperature or length limit for the planner and reviewer, so the model's own defaults apply.
"""
from __future__ import annotations

import argparse
import sys


def strip_from(text):
    """The Modelfile without its FROM line(s) and top-level comments; triple-quoted blocks kept as they are."""
    out, inside = [], False
    for line in text.splitlines():
        if not inside:
            s = line.strip()
            if s.upper().startswith("FROM ") or s.startswith("#"):
                continue
        out.append(line)
        if line.count('"""') % 2 == 1:
            inside = not inside
    if inside:
        raise ValueError("unbalanced triple quotes in the base Modelfile")
    return "\n".join(out).strip() + "\n"


def set_parameter(text, name, value):
    """The Modelfile with PARAMETER <name> set to value (replacing any lines for it; outside quoted blocks)."""
    out, inside, done = [], False, False
    for line in text.splitlines():
        if not inside and line.strip().split()[:2] == ["PARAMETER", name]:
            if not done:
                out.append(f"PARAMETER {name} {value}")
                done = True
            continue
        out.append(line)
        if line.count('"""') % 2 == 1:
            inside = not inside
    if not done:
        # before the first LICENSE block (or at the end), with the other PARAMETER lines
        at = next((i for i, l in enumerate(out) if l.startswith("LICENSE ")), len(out))
        out.insert(at, f"PARAMETER {name} {value}")
    return "\n".join(out).strip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="the output of: ollama show <base> --modelfile")
    ap.add_argument("--from", dest="src", required=True, help="our weights: a folder of safetensors or a .gguf file")
    ap.add_argument("--out", required=True)
    ap.add_argument("--temperature", help="override the base's default temperature")
    ap.add_argument("--num-predict", type=int, help="cap every reply at this many tokens")
    a = ap.parse_args(argv)
    with open(a.base, encoding="utf-8") as f:
        rest = strip_from(f.read())
    if "TEMPLATE" not in rest:
        print("the base Modelfile has no TEMPLATE; is the base model installed?", file=sys.stderr)
        return 2
    if a.temperature is not None:
        rest = set_parameter(rest, "temperature", a.temperature)
    if a.num_predict:
        rest = set_parameter(rest, "num_predict", a.num_predict)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(f"FROM {a.src}\n{rest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
