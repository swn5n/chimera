#!/usr/bin/env python3
"""Probe (b), the round trip into Ollama: fuse an empty LoRA adapter into Gemma 4 12B with MLX-LM, convert it to GGUF
with llama.cpp, quantize to Q5_K_M (and Q4_K_M, the official model's quantization, to tell conversion from
quantization), import it into Ollama 0.40.1, and check that at temperature 0 it answers like gemma4:12b-it-q4_K_M.

    ~/chimera-tools/helper-train/.venv/bin/python probes/round_trip.py --hf DIR --work ~/chimera-tools/worker-train/probes

EVAL ONLY: the requests are Chimera's worker requests for eval cases (probes/template_parity.py's spread); the
answers are compared, never kept as data. The imported models are throwaways named wm-probe-gemma4-rt:*.

Steps (each up to the quantizing skipped when its output exists; `ollama create` always runs): an empty adapter (1 LoRA step at learning rate 0, so B stays zero), the
fuse (bf16), the GGUF source folder (helper-model/train/gguf_source.py: the base model's tokenizer files, then
named_specials: the converter's transformers 4.57 doesn't count Gemma 4's named tokens as special, so without this
<|turn> and the like come out as normal tokens and prompts tokenize differently), the bf16 GGUF (llama.cpp's
convert_hf_to_gguf.py in the helper's converter environment), llama-quantize to Q5_K_M and Q4_K_M, then `ollama
create` with the worker's RENDERER and PARSER and the official model's sampling parameters (no DRAFT: a trained worker
has no matching draft model). Then the comparison, each request on a freshly loaded model (keep_alive 0), temperature
0, seed 0, 160 tokens: the prompt token counts must be the same (the tokenizer and the renderer survived the
conversion), and the greedy replies are compared token by token (by the HF tokenizer) up to the first difference. The
bar, fixed before the first run: the same prompt counts on every request; our Q4_K_M agrees with the official Q4_K_M
on the first 32 tokens of at least 6 of the 8 replies, and our Q5_K_M on the first 16 of at least 6. The user retired the
Q4_K_M part on Oct 30: it compared our plain quantization with the official's imatrix one, and the rule names Q5_K_M.
It is still reported, as a diagnostic, but "pass" no longer reads it (the Oct 30 probe-b.json was written before that).

Added after the first run: the official Q4_K_M was quantized with an importance matrix (quantize.imatrix.* in its
GGUF) and ours without one, so those two differ numerically by design. The conversion's own test is therefore our bf16
GGUF in Ollama against MLX-LM's greedy reply on the same bf16 weights, same prompt tokens: reported as "reference"
(not part of the bar). Models are imported with the worker's renderer and parser (probes/template_parity.py, part 2), so the prompt is the
non-thinking one with the empty thought block; the official model is asked with "think": false, ours as Chimera asks,
with no think field. The first two tries are kept as probe-b-first-try.json (the named tokens came out as normal
ones) and probe-b-second-try.json (plain RENDERER gemma4: no empty thought block on a model without the official
manifest).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from probes.template_parity import WORKER_PARSER, WORKER_RENDERER, ask_chat, leaks, post  # noqa: E402
from runner import cases as C  # noqa: E402

import evalset  # noqa: E402

REPO = os.path.dirname(HERE)
HT = os.path.expanduser("~/chimera-tools/helper-train")
LC = os.path.join(HT, "llama.cpp")
CPY = os.path.join(HT, ".venv-convert", "bin", "python")
QBIN = os.path.join(LC, "build", "bin", "llama-quantize")
OFFICIAL = "gemma4:12b-it-q4_K_M"
CASES = ["w2-01", "w2-10", "w3-04", "w3-12", "w4f-01", "w4l-02", "bw-01/s1", "res-01/s5"]
PREDICT = 160


def run(cmd, log, **kw):
    with open(log, "a", encoding="utf-8") as f:
        f.write("\n$ " + " ".join(cmd) + "\n")
        f.flush()
        t = time.time()
        p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, **kw)
        f.write(f"[exit {p.returncode}, {time.time() - t:.0f} s]\n")
    if p.returncode:
        raise SystemExit(f"failed: {' '.join(cmd[:3])} … (see {log})")


def named_specials(src):
    """Add Gemma 4's named tokens (sot_token, eot_token, think_token, …) to additional_special_tokens in the GGUF source
    folder's tokenizer_config.json, the 4.x way of saying they're special. Returns how many were added."""
    p = os.path.join(src, "tokenizer_config.json")
    with open(p, encoding="utf-8") as f:
        cfg = json.load(f)
    have = list(cfg.get("additional_special_tokens") or [])
    named = [v for k, v in cfg.items() if k.endswith("_token") and isinstance(v, str)
             and k not in ("bos_token", "eos_token", "unk_token", "pad_token", "mask_token")]
    add = [t for t in named if t not in have]
    cfg["additional_special_tokens"] = have + add
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1, ensure_ascii=False)
    return len(add)


def mlx_reference(base, requests, predict):
    """{case id: greedy reply} from MLX-LM on the bf16 weights, the prompts' exact HF token ids (temperature 0)."""
    import mlx.core as mx
    from mlx_lm import generate, load
    model, tokenizer = load(base)
    out = {}
    for cid, ids in requests.items():
        out[cid] = generate(model, tokenizer, prompt=ids, max_tokens=predict, verbose=False)
        mx.clear_cache()
    del model
    mx.clear_cache()
    return out


def first_diff(tok, a, b):
    """(index of the first differing token, tokens compared): the HF tokenizer's tokens of two replies."""
    x, y = tok(a, add_special_tokens=False)["input_ids"], tok(b, add_special_tokens=False)["input_ids"]
    n = min(len(x), len(y))
    for i in range(n):
        if x[i] != y[i]:
            return i, n
    return n, n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hf", required=True, help="the Hugging Face model folder")
    ap.add_argument("--work", required=True)
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--out", default=os.path.join(HERE, "results", "probes", "probe-b.json"))
    a = ap.parse_args(argv)
    w = os.path.join(a.work, "round-trip")
    os.makedirs(w, exist_ok=True)
    log = os.path.join(w, "round-trip.log")
    base = os.path.join(a.work, "base-worker-template")  # mlx_pilot.py's: the base with the worker template
    if not os.path.isdir(base):
        from probes.mlx_pilot import base_folder
        base_folder(a.hf, base)
    res = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "official": OFFICIAL, "steps": {}}

    # 1. the empty adapter: one LoRA step at learning rate 0 (LoRA's B starts at zero, so the delta is zero)
    ad = os.path.join(w, "empty-adapters")
    if not os.path.exists(os.path.join(ad, "adapters.safetensors")):
        data = os.path.join(a.work, "pilot-data")
        cfg = os.path.join(w, "empty.yaml")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write("\n".join([f"model: {json.dumps(base)}", "train: true", "fine_tune_type: lora", "optimizer: adamw",
                               f"data: {json.dumps(data)}", "seed: 0", "num_layers: 48", "batch_size: 1", "iters: 1",
                               "val_batches: 1", "learning_rate: 0.0", "steps_per_report: 1", "steps_per_eval: 100",
                               f"adapter_path: {json.dumps(ad)}", "save_every: 100", "max_seq_length: 12288",
                               "grad_checkpoint: true", "mask_prompt: true", "lora_parameters:", "  rank: 32",
                               "  scale: 20.0", "  dropout: 0.0", ""]))
        run([sys.executable, "-m", "mlx_lm", "lora", "-c", cfg], log)
    res["steps"]["empty_adapter"] = ad
    # 2. fuse
    fused = os.path.join(w, "fused")
    if not os.path.exists(os.path.join(fused, "config.json")):
        shutil.rmtree(fused, ignore_errors=True)
        run([sys.executable, "-m", "mlx_lm", "fuse", "--model", base, "--adapter-path", ad, "--save-path", fused], log)
    with open(os.path.join(fused, "config.json"), encoding="utf-8") as f:
        fc = json.load(f)
    res["steps"]["fused_config"] = {"architectures": fc.get("architectures"), "model_type": fc.get("model_type")}
    # 3. GGUF: the source folder with the base's tokenizer files, then bf16
    src = os.path.join(w, "gguf-src")
    bf16 = os.path.join(w, "rt2-bf16.gguf")
    if not os.path.exists(bf16):
        run([CPY, os.path.join(REPO, "helper-model", "train", "gguf_source.py"), "--base", "google/gemma-4-12B-it",
             "--fused", fused, "--out", src], log)
        res["steps"]["named_specials_added"] = named_specials(src)
        run([CPY, os.path.join(LC, "convert_hf_to_gguf.py"), src, "--outfile", bf16 + ".part", "--outtype", "bf16",
             "--model-name", "wm probe gemma4 round trip"], log)
        os.replace(bf16 + ".part", bf16)
    # 4. quantize
    ggs = {}
    for q in ("Q5_K_M", "Q4_K_M"):
        g = os.path.join(w, f"rt2-{q.lower()}.gguf")
        if not os.path.exists(g):
            run([QBIN, bf16, g + ".part", q], log)
            os.replace(g + ".part", g)
        ggs[q] = g
    res["steps"]["gguf"] = {q: round(os.path.getsize(g) / 1e9, 2) for q, g in ggs.items()}
    # 5. into Ollama, prompted like the official model
    show = post(a.host, "/api/show", {"model": OFFICIAL})
    params = [l for l in show.get("modelfile", "").splitlines() if l.startswith("PARAMETER ") and "draft" not in l]
    tags = {}
    for q, g in list(ggs.items()) + [("bf16", bf16)]:
        tag = f"wm-probe-gemma4-rt:{q.lower()}"
        mf = os.path.join(w, f"Modelfile.{q.lower()}")
        with open(mf, "w", encoding="utf-8") as f:
            f.write("\n".join([f"FROM {g}", f"RENDERER {WORKER_RENDERER}", f"PARSER {WORKER_PARSER}"] + params) + "\n")
        run(["ollama", "create", tag, "-f", mf], log)
        tags[q] = tag
    res["models"] = tags
    res["show"] = {t: {k: v for k, v in post(a.host, "/api/show", {"model": t}).items()
                       if k in ("thinking", "capabilities", "details")} for t in [OFFICIAL] + list(tags.values())}

    # 6. compare
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.hf)
    es = evalset.load()
    cs = {c.id: c for c in C.load_cases(es, C.PARTS, CASES, False, 0, C.FROZEN_DIR, [])}
    reqs = {cid: C.request(cs[cid], "contract") for cid in CASES}
    prompt_ids = {cid: tok.apply_chat_template(r["messages"], add_generation_prompt=True, enable_thinking=False,
                                               return_dict=False) for cid, r in reqs.items()}
    reference = mlx_reference(base, prompt_ids, PREDICT)
    rows = []
    for cid in CASES:
        req = reqs[cid]
        msgs = req["messages"]
        num_ctx = 16384 if req["need_ctx"] > 8192 - 64 else 8192
        hf_n = len(prompt_ids[cid])
        row = {"id": cid, "hf_tokens": hf_n, "mlx_reference": reference[cid]}
        off = ask_chat(a.host, OFFICIAL, msgs, num_ctx, think=False, predict=PREDICT)
        row["official"] = off
        d, n = first_diff(tok, off["content"], reference[cid])
        row["official_vs_mlx"] = {"first_diff": d, "compared": n}
        for q, tag in tags.items():
            r = ask_chat(a.host, tag, msgs, num_ctx, predict=PREDICT)  # no think field, as Chimera asks
            d, n = first_diff(tok, off["content"], r["content"])
            dm, nm = first_diff(tok, reference[cid], r["content"])
            row[q] = dict(r, first_diff=d, compared=n, same_prompt_count=r["prompt_tokens"] == off["prompt_tokens"],
                          first_diff_vs_mlx=dm, compared_vs_mlx=nm, leaks=leaks(r["content"]))
        rows.append(row)
        print(cid, "prompt", off["prompt_tokens"], {q: (row[q]["prompt_tokens"], row[q]["first_diff"],
                                                        row[q]["first_diff_vs_mlx"]) for q in tags}, file=sys.stderr)
    res["cases"] = rows
    same = all(r[q]["same_prompt_count"] for r in rows for q in tags)
    q4 = sum(1 for r in rows if r["Q4_K_M"]["first_diff"] >= min(32, r["Q4_K_M"]["compared"]))
    q5 = sum(1 for r in rows if r["Q5_K_M"]["first_diff"] >= min(16, r["Q5_K_M"]["compared"]))
    res["verdict"] = {"same_prompt_counts": same, "q4_first_32_same": q4, "q5_first_16_same": q5,
                      "pass": same and q5 >= 6,
                      "bf16_vs_mlx_first_diff": [r["bf16"]["first_diff_vs_mlx"] for r in rows],
                      "official_vs_mlx_first_diff": [r["official_vs_mlx"]["first_diff"] for r in rows],
                      "no_thinking": all(not r[q]["thinking"] and not r[q]["leaks"] for r in rows for q in tags)}
    res["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    print(json.dumps(res["verdict"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
