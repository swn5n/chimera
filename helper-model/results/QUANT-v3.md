# chimera-helper:v3 at other quantizations and temperatures

Oct 29. The same v3 weights (`~/chimera-tools/helper-train/v3/`), scored on eval v1.1 with Chimera's exact requests. All but the first have replies capped at 4,096 tokens. A *slip* is a step key written as `"depends"` (or with its quote left open) instead of `"depends_on"`; a *runaway* is a reply that never ended (it got stuck inside the open key) and hit the eval's 10-minute limit, or was stopped by the 4,096-token cap. No training example has such a key, and v2 at Q4_K_M never wrote one.

| v3 as | GB | slips (of steps) | runaways | Chimera accepts plans | plans strictly valid | plan quality | plan p50 | reviewer right | review p50 | gate right |
|---|---|---|---|---|---|---|---|---|---|---|
| Q4_K_M, temperature 0.7 (as first imported) | 2.50 | 11 (144) | 2 | 41/44 | 33/44 | 0.89 | 4.1 s | 22/24 | 0.9 s | 43/43 |
| Q4_K_M, temperature 0.2 | 2.50 | 6 (155) | 1 | 43/44 | 36/44 | 0.93 | 3.7 s | 20/24 | 1.0 s | 43/43 |
| Q4_K_M, temperature 0 | 2.50 | 6 (151) | 0 | 44/44 | 38/44 | 0.96 | 3.7 s | 19/24 | 1.0 s | 43/43 |
| **Q5_K_M**, temperature 0.7 | 2.89 | 0 (147) | 0 | 44/44 | 41/44 | 0.95 | 4.2 s | 22/24 | 1.1 s | 43/43 |
| Q6_K, temperature 0.7 | 3.31 | 0 (153) | 0 | 44/44 | 39/44 | 0.93 | 4.5 s | 21/24 | 1.2 s | 43/43 |
| Q8_0, temperature 0.7 | 4.28 | 0 (160) | 0 | 44/44 | 41/44 | 0.94 | 5.2 s | 21/24 | 1.3 s | 43/43 |
| bf16 (not quantized), temperature 0.7 | 8.05 | 0 (170) | 0 | 44/44 | 40/44 | 0.93 | 8.1 s | – | – | – |

Conclusion: the slip comes from Q4_K_M quantization, not from sampling (still 6 at temperature 0) or from the training data. From Q5_K_M up it's gone, and so are the runaways. Q5_K_M is the smallest clean one, and scores as well as any (the differences between Q5_K_M, Q6_K and Q8_0 are within the eval's noise), for 0.4 GB more than Q4_K_M and about 0.1 s more per plan. Lower temperatures cut the slips but cost reviews, so the helper keeps the base's 0.7. `run_train.sh` now quantizes to Q5_K_M and caps replies at 4,096 tokens by default (`QUANT`, `NUM_PREDICT`).

v3 at Q5_K_M was released as **Hydra 1.0** (`hydra:1.0` in Ollama). Made by `run_settings.sh` and `run_quants.sh`; per case: `python3 runner/compare.py results/runs/20261029-065950-chimera-helper-v3 results/runs/20261029-103846-chimera-helper-v3-t02 results/runs/20261029-104229-chimera-helper-v3-t0 results/runs/20261029-113810-chimera-helper-v3-q5_k_m results/runs/20261029-114226-chimera-helper-v3-q6_k results/runs/20261029-114640-chimera-helper-v3-q8_0 results/runs/20261029-104547-chimera-helper-v3-bf16`.
