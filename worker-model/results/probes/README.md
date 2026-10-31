# Base-model probes (Oct 30, on the Studio)

EVAL ONLY: replies to eval cases, never training data. The verdicts and what they mean are in
`docs/hydra-worker-plan.md`, "Probes a-c". Scripts are in `worker-model/probes/`.

| File | What it is |
|---|---|
| `probe-a.json` | (a) MLX pilot, final: the worker's prompt form (its fixed template, on Hydra 1.0's text), MLX cache capped at 8 GB |
| `probe-a-first-try.json` | (a) first run: uncapped, and on the stock prompt, because MLX-LM's tokenizer wrapper turned thinking on |
| `probe-b.json` | (b) round trip, final, as measured. `"pass": false` comes from the Q4_K_M side test, which compared our plain quantization with the official's imatrix one; the rule names Q5_K_M, which met its bar. The user retired that test on Oct 30, so (b) counts as passed; this file isn't edited |
| `probe-b-first-try.json` | (b) Gemma's named tokens came out of the GGUF as normal tokens (fixed: `named_specials`) |
| `probe-b-second-try.json` | (b) plain `RENDERER gemma4`: no empty thought block on a model without the official manifest |
| `probe-c.json` | (c) template parity, final, on our Q5_K_M, through MLX-LM's own dataset code |
| `probe-c-before-audit.json` | (c) a false pass: it called the HF tokenizer directly, not MLX-LM's path |
| `probe-c-template-try.json` | (c) a TEMPLATE on the official blob: ignored by Ollama 0.40.1, the model thinks |
