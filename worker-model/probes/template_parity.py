#!/usr/bin/env python3
"""Probe (c), template parity: the prompt MLX-LM trains Gemma 4 on against the one Ollama renders, token for token,
the empty thought block included, and no thought text in the reply Chimera gets.

    ~/chimera-tools/helper-train/.venv/bin/python probes/template_parity.py --hf DIR --ollama-model gemma4:12b-it-q4_K_M

Run it with the helper's MLX-LM environment (it has transformers). EVAL ONLY: the requests are Chimera's worker
requests for eval cases (runner/cases.py), and the answers are the model's own greedy replies; nothing here is
training data, and the probe's models are throwaways.

Ollama has no tokenize endpoint, so token parity is shown two ways, each request on a freshly loaded model
(keep_alive 0, so no prompt cache): the prompt token count Ollama reports (prompt_eval_count) against the HF
tokenizer's, and greedy replies (temperature 0, seed 0) from /api/chat against /api/generate with raw=true and the HF
template's exact prompt text: the same count and the same reply mean the same tokens.

Parts:
1. Ollama's own rendering (RENDERER gemma4) with "think": false, against the HF template with enable_thinking=False.
2. The worker's model setup (--worker-tag): RENDERER gemma4-large and PARSER gemma4-no-thinking, made through
   /api/create's JSON fields, as Chimera's Get from host makes models. Ollama 0.40.1 ignores a TEMPLATE for a gemma4
   model (ollama create adds RENDERER gemma4 to it), and a model on the plain "gemma4" renderer thinks by default,
   with no empty thought block when told not to unless it's the official manifest; the "-large" renderer writes the
   block whenever thinking is off and the "-no-thinking" parser takes the thinking capability away, so with both it's
   always there. Asked with no think field, as
   Chimera asks: the same checks, and no thinking field or thought markup in the reply.
3. MLX-LM's training side, through its own path (mlx_lm.utils.load_tokenizer and tuner/datasets.ChatDataset with
   mask_prompt, which is what training runs): MLX-LM's tokenizer wrapper passes enable_thinking=True for Gemma 4 when
   the caller doesn't say, so with the stock template training gets <|think|> and no empty thought block, a prompt
   the worker never gets at inference; and the template puts the empty thought block only in the generation prompt, so
   the full conversation isn't the prompt plus the answer. The worker training template (worker_template below) fixes
   both, and then the prompt part equals, token for token, what Ollama renders in part 2.
4. Over every eval request that can be built (176 on Oct 30; 80 W1 steps wait on frozen dependency outputs), with no
   inference: Ollama's rendered text (/api/chat "_debug_render_only") against the HF no-thinking text and against
   MLX-LM's training prompt. Ollama still loads the model for a render, and it stays loaded for 5 minutes.

An earlier version of part 3 called the HF tokenizer directly, which defaults to no thinking, so it passed while the
real path was wrong (an independent audit found it): keep this going through MLX-LM's own code.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from runner import cases as C  # noqa: E402

import evalset  # noqa: E402

EMPTY_THOUGHT = "<|channel>thought\n<channel|>"

# The worker's Ollama setup: see part 2 of the docstring.
WORKER_RENDERER = "gemma4-large"
WORKER_PARSER = "gemma4-no-thinking"


def worker_template(stock):
    """The HF chat template for training the worker: thinking always off, and an assistant turn also starts with the
    empty thought block, as the generation prompt does, so the full conversation is the prompt plus the answer
    (MLX-LM masks the prompt by the generation prompt's length). Training rows have one assistant turn: Ollama writes
    no block on earlier assistant turns in a history, and no worker request has any."""
    old = "{{- '<|turn>' + role + '\\n' }}"
    think = "{%- set enable_thinking = enable_thinking | default(false) -%}"
    if old not in stock or think not in stock:
        raise SystemExit("the stock template has changed: nothing to patch")
    new = old + ("\n    {%- if role == 'model' and not enable_thinking and not continue_same_model_turn -%}"
                 "{{- '" + EMPTY_THOUGHT.replace("\n", "\\n") + "' -}}{%- endif -%}")
    # MLX-LM's tokenizer wrapper passes enable_thinking=True for Gemma 4 unless told otherwise; the worker never thinks
    return stock.replace(old, new, 1).replace(think, "{%- set enable_thinking = false -%}", 1)


def post(host, path, body, timeout=600):
    req = urllib.request.Request(host + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def ask_chat(host, model, messages, num_ctx, think="unset", predict=48):
    body = {"model": model, "messages": messages, "stream": False, "keep_alive": 0,
            "options": {"temperature": 0, "seed": 0, "num_predict": predict, "num_ctx": num_ctx}}
    if think != "unset":
        body["think"] = think
    r = post(host, "/api/chat", body)
    m = r.get("message") or {}
    return {"prompt_tokens": r.get("prompt_eval_count"), "content": m.get("content", ""),
            "thinking": m.get("thinking", ""), "done_reason": r.get("done_reason")}


def ask_raw(host, model, prompt, num_ctx, predict=48):
    r = post(host, "/api/generate", {"model": model, "prompt": prompt, "raw": True, "stream": False, "keep_alive": 0,
                                     "options": {"temperature": 0, "seed": 0, "num_predict": predict,
                                                 "num_ctx": num_ctx}})
    return {"prompt_tokens": r.get("prompt_eval_count"), "content": r.get("response", ""), "done_reason": r.get("done_reason")}


def weights_digest(host, model):
    """The digest of a model's main weights blob, from /api/show's first FROM line."""
    show = post(host, "/api/show", {"model": model})
    for line in show.get("modelfile", "").splitlines():
        if line.startswith("FROM ") and "/blobs/" in line:
            return "sha256:" + os.path.basename(line[5:].strip()).split("sha256-")[1]
    raise SystemExit(f"can't find {model}'s weights blob in /api/show")


def create_worker(host, tag, base_model):
    """A throwaway model on the base's weights blob with the worker's renderer and parser, through /api/create's
    JSON fields (Chimera's Get from host uses this call), so the blob isn't copied."""
    digest = weights_digest(host, base_model)
    body = {"model": tag, "files": {"model.gguf": digest}, "renderer": WORKER_RENDERER, "parser": WORKER_PARSER,
            "stream": False}
    r = post(host, "/api/create", body, timeout=1800)
    show = post(host, "/api/show", {"model": tag})
    return {"blob": digest, "status": r.get("status"), "renderer": WORKER_RENDERER, "parser": WORKER_PARSER,
            "thinking": show.get("thinking"), "capabilities": show.get("capabilities"),
            "modelfile_lines": [l for l in show.get("modelfile", "").splitlines()
                                if l.split(" ")[0] in ("RENDERER", "PARSER")]}


def render(host, model, messages):
    """The text Ollama would send the model for this chat, with no inference."""
    r = post(host, "/api/chat", {"model": model, "messages": messages, "stream": False, "_debug_render_only": True})
    return (r.get("_debug_info") or {}).get("rendered_template")


def mlx_row(tokenizer, messages, answer):
    """(tokens, offset) from MLX-LM's own dataset code, as training gets them."""
    from mlx_lm.tuner.datasets import ChatDataset
    row = {"messages": messages + [{"role": "assistant", "content": answer}]}
    return ChatDataset([row], tokenizer, mask_prompt=True).process(row)


def leaks(text):
    return [m for m in ("<|channel>", "<channel|>", "<|think|>", "thought\n") if m in (text or "")]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hf", required=True, help="the Hugging Face model folder (tokenizer and chat template)")
    ap.add_argument("--ollama-model", default="gemma4:12b-it-q4_K_M")
    ap.add_argument("--weights-from", help="the model whose weights the worker setup uses (default --ollama-model)")
    ap.add_argument("--worker-tag", default="wm-probe-gemma4-worker:c", help="the throwaway worker model to create")
    ap.add_argument("--base", default=os.path.expanduser("~/chimera-tools/worker-train/probes/base-worker-template"),
                    help="the base folder training uses (its chat template is rewritten)")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--case", action="append", help="eval case ids (default: a spread of the quick subset)")
    ap.add_argument("--out", default=os.path.join(HERE, "results", "probes", "probe-c.json"))
    a = ap.parse_args(argv)

    from pathlib import Path

    from mlx_lm.utils import load_tokenizer
    from transformers import AutoTokenizer

    from probes.mlx_pilot import base_folder
    tok = AutoTokenizer.from_pretrained(a.hf)
    base = base_folder(a.hf, a.base)  # rewrites its chat template from the stock one, with worker_template
    mlx_stock, mlx_worker = load_tokenizer(Path(a.hf)), load_tokenizer(Path(base))
    es = evalset.load()
    ids = a.case or ["w2-01", "w2-10", "w3-04", "w3-12", "w4f-01", "w4l-02", "bw-01/s1", "res-01/s5"]
    cs = {c.id: c for c in C.load_cases(es, C.PARTS, ids, False, 0, C.FROZEN_DIR, [])}
    report = {"hf": a.hf, "ollama_model": a.ollama_model, "worker_tag": a.worker_tag, "cases": [],
              "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "eval_only": "EVAL ONLY: never training data"}
    report["worker_model"] = create_worker(a.host, a.worker_tag, a.weights_from or a.ollama_model)
    for cid in ids:
        c = cs.get(cid)
        if c is None:
            report["cases"].append({"id": cid, "error": "case not found"})
            continue
        req = C.request(c, "contract")
        msgs = req["messages"]
        num_ctx = 16384 if req["need_ctx"] > 8192 - 64 else 8192
        ws = [m["role"] for m in msgs if m["content"] != m["content"].strip()]
        text = tok.apply_chat_template(msgs, add_generation_prompt=True, enable_thinking=False, tokenize=False)
        hf_ids = tok.apply_chat_template(msgs, add_generation_prompt=True, enable_thinking=False, tokenize=True,
                                         return_dict=False)
        think_ids = tok.apply_chat_template(msgs, add_generation_prompt=True, enable_thinking=True, tokenize=True,
                                            return_dict=False)
        raw_text = text[len(tok.bos_token):] if text.startswith(tok.bos_token) else text
        row = {"id": cid, "messages": [m["role"] for m in msgs], "content_with_outer_whitespace": ws,
               "hf_tokens": len(hf_ids), "hf_tokens_thinking": len(think_ids),
               "ends_with_empty_thought": text.endswith(EMPTY_THOUGHT), "num_ctx": num_ctx}
        # 1. Ollama's renderer with think false, and think unset
        row["renderer_think_false"] = ask_chat(a.host, a.ollama_model, msgs, num_ctx, think=False)
        row["renderer_think_unset"] = ask_chat(a.host, a.ollama_model, msgs, num_ctx, predict=8)
        row["raw_hf_text"] = ask_raw(a.host, a.ollama_model, raw_text, num_ctx)
        # 2. the worker template, asked as Chimera asks (no think field)
        row["worker_no_think_field"] = ask_chat(a.host, a.worker_tag, msgs, num_ctx)
        row["raw_hf_text_on_worker"] = ask_raw(a.host, a.worker_tag, raw_text, num_ctx)
        r1, r2, rw, rr = (row["renderer_think_false"], row["raw_hf_text"], row["worker_no_think_field"],
                          row["raw_hf_text_on_worker"])
        row["checks"] = {
            "renderer_count_is_hf": r1["prompt_tokens"] == len(hf_ids),
            "renderer_reply_is_raw": r1["content"] == r2["content"],
            "raw_count_is_hf": r2["prompt_tokens"] == len(hf_ids),
            "worker_count_is_hf": rw["prompt_tokens"] == len(hf_ids),
            "worker_reply_is_raw": rw["content"] == rr["content"],
            "worker_no_thinking": not rw["thinking"] and not leaks(rw["content"]),
            "unset_thinks": row["renderer_think_unset"]["prompt_tokens"] == len(think_ids),
        }
        # 3. MLX-LM's training side, with the model's own greedy reply as the answer
        answer = rw["content"].strip() or "ok"
        ans = tok(answer, add_special_tokens=False)["input_ids"]
        for name, wrapper in (("stock", mlx_stock), ("worker", mlx_worker)):
            full, offset = mlx_row(wrapper, msgs, answer)
            row["mlx_" + name] = {
                "full_tokens": len(full), "offset": offset,
                "prompt_is_inference_prompt": full[:offset] == hf_ids,
                "target_is_answer_then_end": full[offset:] == ans + tok("<turn|>\n", add_special_tokens=False)["input_ids"],
                "has_think_token": tok.convert_tokens_to_ids("<|think|>") in full,
            }
        report["cases"].append(row)
        print(cid, json.dumps(row["checks"]), "mlx stock", row["mlx_stock"]["prompt_is_inference_prompt"],
              "worker", row["mlx_worker"]["prompt_is_inference_prompt"], row["mlx_worker"]["target_is_answer_then_end"],
              file=sys.stderr)
    # 4. every eval request: Ollama's render against HF's text and MLX-LM's training prompt (no inference)
    every = C.load_cases(es, C.PARTS, None, False, 0, C.FROZEN_DIR, [])
    tally = {"requests": 0, "render_is_hf_text": 0, "mlx_stock_prompt_is_render": 0, "mlx_worker_prompt_is_render": 0,
             "mlx_worker_target_ok": 0, "other_than_system_user": 0, "mismatches": []}
    probe_answer = "```python\nimport bpy\nprint('x')\n```"
    ans_ids = tok(probe_answer, add_special_tokens=False)["input_ids"] + tok("<turn|>\n", add_special_tokens=False)["input_ids"]
    for c in every:
        msgs = C.request(c, "contract")["messages"]
        text = tok.apply_chat_template(msgs, add_generation_prompt=True, enable_thinking=False, tokenize=False)
        rendered = render(a.host, a.worker_tag, msgs)
        ids = tok(rendered, add_special_tokens=False)["input_ids"]
        tally["requests"] += 1
        tally["other_than_system_user"] += [m["role"] for m in msgs] != ["system", "user"]
        tally["render_is_hf_text"] += rendered == text
        t0, o0 = mlx_row(mlx_stock, msgs, probe_answer)
        t1, o1 = mlx_row(mlx_worker, msgs, probe_answer)
        tally["mlx_stock_prompt_is_render"] += t0[:o0] == ids
        tally["mlx_worker_prompt_is_render"] += t1[:o1] == ids
        tally["mlx_worker_target_ok"] += t1[o1:] == ans_ids
        if rendered != text or t1[:o1] != ids or t1[o1:] != ans_ids:
            tally["mismatches"].append(c.id)
    report["every_request"] = tally
    print(json.dumps({k: v for k, v in tally.items() if k != "mismatches"}), tally["mismatches"][:5], file=sys.stderr)
    live = [c for c in report["cases"] if "checks" in c]
    report["verdict"] = {
        "ollama_side": all(all(v for v in c["checks"].values()) for c in live),
        "mlx_side": all(c["mlx_worker"]["prompt_is_inference_prompt"] and c["mlx_worker"]["target_is_answer_then_end"]
                        and not c["mlx_worker"]["has_think_token"] for c in live),
        "every_request": tally["requests"] > 0 and tally["requests"] == tally["render_is_hf_text"] ==
        tally["mlx_worker_prompt_is_render"] == tally["mlx_worker_target_ok"]}
    report["verdict"]["pass"] = all(report["verdict"].values())
    report["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    print("wrote", a.out, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
