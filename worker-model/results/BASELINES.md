# Hydra Worker baselines (tonight's A/B)

Eval w1.0. EVAL ONLY: model replies to eval cases; never training data. Made by `runner/report.py` from the runs tagged "baseline…" (`bash run_baselines.sh`); each row is the latest finished run. Requests are Chimera 0.7.0's (no seed, temperature, think or num_predict; unseeded at each model's defaults; stage g alone sends "think": false), except the runners' two limits: a worker step's content is cut at 6,144 tokens and every reply, thinking included, at 16,384 (a runaway, a fail; "th" in thinking, "co" in content).

## Step level: the quick subset's W2, W3 and W4 cases (stage a)

| model | prompt | samples | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | strict + scene 5.2.2 | crash 5.2.2 checked / all | crash 5.0.1 checked / all | runaway | cut off | call errors | API errors | repaired | tokens | tok/s | min |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3:14b | today | 1 (prose 1) | 36 | 25% | 25% | 30 | 30% | 30% | 30% | 30% | 63% / 63% | 63% / 63% | 0% | 0% | 0 | 1.9 | 60% | 2781 | 58.7 | 35.5 |
| qwen3:14b | contract | 1 (prose 1) | 36 | 86% | 83% | 30 | 23% | 27% | 23% | 20% | 67% / 67% | 63% / 63% | 0% | 0% | 0 | 1.83 | 40% | 1884 | 58.5 | 32.7 |
| gemma4:12b-it-q4_K_M | today | 1 (prose 1) | 36 | 0% | 0% | 30 | 20% | 20% | 20% | 17% | 70% / 53% | 70% / 53% | 0% | 19% | 0 | 2.72 | 40% | 3459 | 59.8 | 45.0 |
| gemma4:12b-it-q4_K_M | contract | 1 (prose 1) | 36 | 86% | 83% | 30 | 27% | 27% | 27% | 23% | 68% / 57% | 68% / 57% | 0% | 14% | 0 | 2.59 | 50% | 4998 | 60.7 | 48.8 |
| qwen3.8:27b | today | 1 (prose 1) | 36 | 6% | 6% | 30 | 57% | 63% | 57% | 43% | 43% / 43% | 37% / 37% | 0% | 0% | 0 | 0.87 | 70% | 2394 | 73.9 | 28.9 |
| qwen3.8:27b | contract | 1 (prose 1) | 36 | 89% | 89% | 30 | 50% | 53% | 50% | 37% | 50% / 50% | 47% / 47% | 0% | 0% | 0 | 0.67 | 70% | 3544 | 71.8 | 38.2 |
| gpt-oss:120b | today | 2 (prose 1) | 69 | 1% | 1% | 60 | 38% | 42% | 38% | 32% | 62% / 62% | 58% / 58% | 0% | 0% | 0 | 1.62 | 50% | 1320 | 82.3 | 22.8 |
| gpt-oss:120b | contract | 2 (prose 1) | 69 | 86% | 80% | 60 | 38% | 42% | 38% | 30% | 62% / 62% | 58% / 58% | 0% | 0% | 0 | 1.43 | 55% | 1475 | 81.7 | 25.3 |
| qwen3:8b | today | 1 (prose 1) | 36 | 0% | 0% | 30 | 23% | 23% | 23% | 20% | 69% / 67% | 69% / 67% | 0% | 0% | 0 | 3.67 | 40% | 2580 | 92.7 | 26.2 |
| qwen3:8b | contract | 1 (prose 1) | 36 | 75% | 47% | 30 | 30% | 30% | 30% | 23% | 61% / 57% | 61% / 57% | 0% | 0% | 0 | 2.61 | 70% | 3140 | 89.8 | 27.5 |
| qwen3:4b-instruct-2507-q4_K_M | today | 3 (prose 1) | 102 | 0% | 0% | 90 | 13% | 13% | 13% | 7% | 75% / 70% | 75% / 70% | 3% (0 th, 3 co) | 0% | 0 | 3.07 | 27% | 629 | 140.8 | 15.8 |
| qwen3:4b-instruct-2507-q4_K_M | contract | 3 (prose 1) | 102 | 78% | 43% | 90 | 12% | 12% | 12% | 11% | 83% / 79% | 83% / 79% | 5% (0 th, 5 co) | 0% | 0 | 4.53 | 33% | 923 | 138.6 | 19.9 |

## Step level: the quick subset's W1 steps on the frozen plans (stage c)

No run finished yet.

## Step level: the base candidates with thinking off, W2-W4 (stage g)

| model | prompt | samples | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | strict + scene 5.2.2 | crash 5.2.2 checked / all | crash 5.0.1 checked / all | runaway | cut off | call errors | API errors | repaired | tokens | tok/s | min |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3:14b | contract | 3 (prose 1) | 102 | 89% | 88% | 90 | 21% | 24% | 21% | 19% | 74% / 71% | 71% / 68% | 4% (0 th, 4 co) | 0% | 0 | 5.86 | 37% | 592 | 60.6 | 30.1 |
| gemma4:12b-it-q4_K_M | contract | 3 (prose 1) | 102 | 92% | 83% | 90 | 24% | 24% | 24% | 17% | 69% / 69% | 69% / 69% | 0% | 0% | 0 | 2.37 | 50% | 814 | 62.5 | 30.4 |

## Step level: the base candidates with thinking off, W1 steps (stage g)

| model | prompt | samples | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | strict + scene 5.2.2 | crash 5.2.2 checked / all | crash 5.0.1 checked / all | runaway | cut off | call errors | API errors | repaired | tokens | tok/s | min |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3:14b | contract | 3 (prose 1) | 42 | 50% | 50% | 30 | 33% | 33% | 33% | – | 60% / 60% | 60% / 60% | 0% | 0% | 0 | 3.5 | – | 561 | 60.7 | 10.2 |
| gemma4:12b-it-q4_K_M | contract | 3 (prose 1) | 42 | 86% | 74% | 30 | 30% | 30% | 30% | – | 60% / 60% | 60% / 60% | 0% | 0% | 0 | 3.57 | – | 671 | 62.0 | 11.1 |

Columns: contract kept (the contract's shape, which Chimera joins: the near-miss handoff forms count; a piece whose code has a syntax error keeps the shape but fails strict, and joining sends it to the combine), form ok (the exact form, what data generation keeps); strict (not a runaway, Chimera's check passed with no Traceback or Error: line, and the direct run's whole output has none; a piece that isn't joined still gets its build_sN called, since Oct 30); strict + scene (strict, and the eval's scene assertions hold, over the samples whose case has assertions, "of n" when that isn't all: a script that runs clean but skips the job fails it; W1 has none); crash (the check's outcome failed: over the samples Blender checked, the plan's "at most 10%", and over all Blender samples, where no script isn't a crash); call errors (calls that failed outright, left out of the rates); API errors (tools/rna_lint.py errors per reply); repaired (W3, fixed in the crash's version); tokens and tok/s (medians per reply, thinking included); min (the run's wall time). Samples: Blender and code cases get the samples shown, prose 1 (see the script's header for why some models get fewer than the plan's 3).

## The base-model rule's inputs (PROBES STILL NEEDED)

**Probes still needed: the rule can't pick the base yet.** Probes a, b and c ran on Oct 30 (results/probes/, and "Probes a-c" in docs/hydra-worker-plan.md); d, the fleet, is open. It reads: Gemma 4 12B if all four probes pass (a: the MLX pilot, b: the round trip into Ollama, c: template parity, d: fit and speed on the 3080 Ti and the M4 Pro) and its untrained contract score is within 5 points of qwen3:14b; otherwise Qwen3-14B. None of the probes is run by run_baselines.sh. The score is measured two ways: with thinking off ("think": false, stage g), the setting the trained worker runs in (its template forces thinking off, since Chimera sends no think field), which is the one the rule reads; and with think unset, as Chimera sends requests today (stage a), where both models think and can run out of the 8K context. Below, the contract-prompt numbers on the samples both runs have (paired by case and sample). The plan names the main number "Blender strict pass in 5.2.2"; strict + scene (the stricter reading: the scene the case asks for, too) and contract kept are shown with it, per part group and over all parts ("All parts": every part of the quick subset, the rule's scope on it; strict + scene has none, as W1 has no scene assertions). These are point estimates on the quick subset. Each gap line also gives the pairs that passed for one model only, with McNemar's exact p, and a 90% interval from a case bootstrap (the cases resampled, all samples of a case kept together, 10,000 rounds, seed 20261030) with how often the gap is -5 or better: an interval that reaches below -5 means the data can't rule out Gemma being more than 5 points worse.

### Thinking off (stage g, "think": false): the rule reads these

| part | model | samples paired | contract kept | form ok | strict 5.2.2 | strict both | strict + scene 5.2.2 | crash 5.2.2 checked | runaway |
|---|---|---|---|---|---|---|---|---|---|
| W2-W4 | gemma4:12b-it-q4_K_M | 102 | 92% | 83% | 24% | 24% | 17% | 69% | 0% |
| W2-W4 | qwen3:14b | 102 | 89% | 88% | 21% | 21% | 19% | 74% | 4% (0 th, 4 co) |
| W1 | gemma4:12b-it-q4_K_M | 42 | 86% | 74% | 30% | 30% | – | 60% | 0% |
| W1 | qwen3:14b | 42 | 50% | 50% | 33% | 33% | – | 60% | 0% |

Gaps (Gemma minus qwen3:14b, exact, over the paired samples each rate counts on both sides; the score half of the rule only, untrained, unseeded):

- W2-W4 strict 5.2.2: Gemma 22/90, qwen3:14b 19/90: +3.3 points (Gemma ahead or level); one-sided pairs 11 Gemma, 8 qwen3:14b (McNemar p 0.65); 90% interval -7.8 to +13.3 over 30 cases, gap -5 or better in 91% of resamples
- W2-W4 strict + scene 5.2.2: Gemma 15/90, qwen3:14b 17/90: -2.2 points (Gemma behind, by no more than 5); one-sided pairs 5 Gemma, 7 qwen3:14b (McNemar p 0.77); 90% interval -10.0 to +4.4 over 30 cases, gap -5 or better in 73% of resamples
- W2-W4 contract kept: Gemma 94/102, qwen3:14b 91/102: +2.9 points (Gemma ahead or level); one-sided pairs 9 Gemma, 6 qwen3:14b (McNemar p 0.61); 90% interval -2.9 to +9.4 over 36 cases, gap -5 or better in 99% of resamples
- W1 strict 5.2.2: Gemma 9/30, qwen3:14b 10/30: -3.3 points (Gemma behind, by no more than 5); one-sided pairs 1 Gemma, 2 qwen3:14b (McNemar p 1.00); 90% interval -16.7 to +6.7 over 10 cases, gap -5 or better in 61% of resamples
- W1 contract kept: Gemma 36/42, qwen3:14b 21/42: +35.7 points (Gemma ahead or level); one-sided pairs 17 Gemma, 2 qwen3:14b (McNemar p < 0.01); 90% interval +13.6 to +57.1 over 18 cases, gap -5 or better in 100% of resamples
- All parts strict 5.2.2: Gemma 31/120, qwen3:14b 29/120: +1.7 points (Gemma ahead or level); one-sided pairs 12 Gemma, 10 qwen3:14b (McNemar p 0.83); 90% interval -6.7 to +10.0 over 40 cases, gap -5 or better in 92% of resamples
- All parts contract kept: Gemma 130/144, qwen3:14b 112/144: +12.5 points (Gemma ahead or level); one-sided pairs 26 Gemma, 8 qwen3:14b (McNemar p < 0.01); 90% interval +4.2 to +21.3 over 54 cases, gap -5 or better in 100% of resamples

By part (paired samples):

| part | Blender n | Gemma strict 5.2.2 | qwen3:14b strict 5.2.2 | Gemma strict + scene | qwen3:14b strict + scene |
|---|---|---|---|---|---|
| W2 | 48 | 7/48 | 8/48 | 4/48 | 6/48 |
| W3 | 30 | 15/30 | 11/30 | 11/30 | 11/30 |
| W4F | 6 | 0/6 | 0/6 | 0/6 | 0/6 |
| W4L | 6 | 0/6 | 0/6 | 0/6 | 0/6 |
| W1 | 30 | 9/30 | 10/30 | – | – |

### Think unset, as Chimera sends it (stage a): both think

| part | model | samples paired | contract kept | form ok | strict 5.2.2 | strict both | strict + scene 5.2.2 | crash 5.2.2 checked | runaway |
|---|---|---|---|---|---|---|---|---|---|
| W2-W4 | gemma4:12b-it-q4_K_M | 36 | 86% | 83% | 27% | 27% | 23% | 68% | 0% |
| W2-W4 | qwen3:14b | 36 | 86% | 83% | 23% | 23% | 20% | 67% | 0% |
| W1 | not both run yet | – | – | – | – | – | – | – | – |

Gaps (Gemma minus qwen3:14b, exact, over the paired samples each rate counts on both sides; the score half of the rule only, untrained, unseeded). Stage a has one sample per case: read its lines with care.

- W2-W4 strict 5.2.2: Gemma 8/30, qwen3:14b 7/30: +3.3 points (Gemma ahead or level); one-sided pairs 3 Gemma, 2 qwen3:14b (McNemar p 1.00); 90% interval -10.0 to +16.7 over 30 cases, gap -5 or better in 87% of resamples
- W2-W4 strict + scene 5.2.2: Gemma 7/30, qwen3:14b 6/30: +3.3 points (Gemma ahead or level); one-sided pairs 3 Gemma, 2 qwen3:14b (McNemar p 1.00); 90% interval -10.0 to +16.7 over 30 cases, gap -5 or better in 87% of resamples
- W2-W4 contract kept: Gemma 31/36, qwen3:14b 31/36: +0.0 points (Gemma ahead or level); one-sided pairs 5 Gemma, 5 qwen3:14b (McNemar p 1.00); 90% interval -13.9 to +13.9 over 36 cases, gap -5 or better in 68% of resamples

By part (paired samples):

| part | Blender n | Gemma strict 5.2.2 | qwen3:14b strict 5.2.2 | Gemma strict + scene | qwen3:14b strict + scene |
|---|---|---|---|---|---|
| W2 | 16 | 3/16 | 3/16 | 3/16 | 2/16 |
| W3 | 10 | 5/10 | 4/10 | 4/10 | 4/10 |
| W4F | 2 | 0/2 | 0/2 | 0/2 | 0/2 |
| W4L | 2 | 0/2 | 0/2 | 0/2 | 0/2 |

## T1: whole frozen plans, arms side by side

No T1 run finished yet (stage d of run_baselines.sh; it needs frozen plans, stage b).

## Frozen W1 inputs (eval/frozen)

- Plans: 54 frozen (10 from gpt-oss:120b, 44 from hydra:1.0).
- Dependency outputs: 11 verified, 13 rejected, over 10 tasks; today's-format: 0 verified of 0.
