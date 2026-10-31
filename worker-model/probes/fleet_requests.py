#!/usr/bin/env python3
"""Write probes/fleet/requests.json for fleet-probe: two of the eval's worker requests (EVAL ONLY, the contract prompt)
and the token counts the worker training template gives them.

    ~/chimera-tools/helper-train/.venv/bin/python -B probes/fleet_requests.py --hf DIR
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from runner import cases as C  # noqa: E402

import evalset  # noqa: E402

SHORT, LONG = "w3-12", "w4l-02"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hf", required=True, help="the Hugging Face model folder (tokenizer and template)")
    a = ap.parse_args()
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.hf)
    cs = {c.id: c for c in C.load_cases(evalset.load(), C.PARTS, [SHORT, LONG], False, 0, C.FROZEN_DIR, [])}
    out = {"note": "EVAL ONLY: never training data"}
    for key, cid in (("short", SHORT), ("long", LONG)):
        msgs = C.request(cs[cid], "contract")["messages"]
        n = len(tok.apply_chat_template(msgs, add_generation_prompt=True, enable_thinking=False, return_dict=False))
        out[key] = {"id": cid, "messages": msgs, "prompt_tokens": n}
    path = os.path.join(HERE, "probes", "fleet", "requests.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(path, out["short"]["prompt_tokens"], out["long"]["prompt_tokens"])


if __name__ == "__main__":
    main()
