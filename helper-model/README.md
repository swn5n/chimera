# Chimera helper model (Hydra)

**Hydra 1.0** (Oct 29, 2026) is the released helper: in Ollama as `hydra:1.0`, the same model as
`chimera-helper:v3-q5_k_m` (v3's LoRA on Qwen3-4B-Instruct-2507, quantized to Q5_K_M, 2.9 GB, replies capped at
4,096 tokens). Files: `~/chimera-tools/helper-train/v3/helper-q5_k_m.gguf` and `Modelfile.q5_k_m`. On eval v1.1:
41/44 plans strictly valid (Chimera accepts all 44), 22/24 reviews, 43/43 gate pairs; about 4 s a plan, 1 s a
review, 0.1 s a gate call on the Studio. Known weak spot: it doesn't redo arithmetic when it reviews.

**In Chimera from 0.7.0** (Oct 29): Hydra's planner, the looping reviewer and the Head gate prefer `hydra:1.0`
on any computer the step may use, and fall back to the biggest (or fastest) model when none has it or the request
doesn't fit the 8K context; other computers get it from the host with Models → Get from host. How it works:
`../hydra1/README.md` and `../app/helper.go`. Long review cases for it (results of 3,900 to 12,400 characters,
which `eval/` lacks): `eval-long/`, run with `bash run_long_reviews.sh`.

A small model that every node can run whole, so Hydra's planning and review and the Head
gate don't depend on the biggest model being online. Chimera doesn't pool GPUs: each node
runs its own models, so the helper has to fit on the smallest one.

This folder holds the three jobs' target formats, the validators that filter synthetic
training data and score the tuned model, the eval set, a runner that scores any Ollama model
on it exactly as Chimera would ask, the generator for the synthetic training data
(`datagen/`), and the LoRA training (`train/`). The base is Qwen3-4B-Instruct-2507; the first
LoRA, v1, was trained on Oct 28 (`results/TRAINING-v1.md`: planner and gate at the teacher's level, reviewer
barely better than the base); v2 (`run_v2.sh`, `results/TRAINING-v2.md`) trains the reviewer to check each
requirement before its verdict (17 → 19 of 24 reviews right); v3 (`run_v3.sh`, `results/TRAINING-v3.md`) makes it
start from the task's requirements (22 of 24 reviews, 43 of 43 gate pairs), but its planner sometimes writes a
`"depends"` key, and twice got stuck inside it until the time limit. That came from the Q4_K_M quantization, not the
training (`results/QUANT-v3.md`): **v3 at Q5_K_M** (2.9 GB, `chimera-helper:v3-q5_k_m`) never does it and scores
41/44 plans strictly valid, 22/24 reviews, 43/43 gate pairs. `run_train.sh` now quantizes to Q5_K_M and caps
replies at 4,096 tokens.

| Job | What Chimera asked before 0.7.0 (now Hydra 1.0 first) | Reply |
|---|---|---|
| Planner | Hydra's planner, largest model, `onePass` in app/hydra.go | 2–7 step JSON plan |
| Reviewer | Hydra's looping-mode reviewer, largest model, `review` | `{"done", "score", "critique"}` |
| Head gate | "Should a Head make this?", fastest model, `headGate` in app/plugin_chat.go | `{"use": bool}` |

## Layout

- `schemas/`: the strict target for each job (`*.schema.json`) and `SOURCES.md`, which maps
  every field to the Go code and lists what Chimera tolerates or repairs.
- `helper/`: `validate.py` (the validators), `chimera_port.py` (Python ports of how Chimera
  builds each request and reads each reply), `prompts.py` (Chimera's prompts, generated from
  app/, never retyped), `schema_check.py`, `evalset.py`.
- `eval/`: the eval set. **Eval only, never training data** (see `eval/README.md`). Earlier
  versions are kept in `eval/archive/` so old runs can be re-scored and re-reported.
- `eval-long/`: 16 more review cases with long results (3,900 to 12,400 characters, the size Chimera still sends
  to the helper), also eval only; `run_long_reviews.sh` scores them into `results/runs-long/`.
- `runner/`: `run_eval.py` (score a model), `report.py` (collect runs into
  `results/BASELINES.md`), `rescore.py` (re-score saved replies after a scoring change), `compare.py` (runs side by side, case by case), `scoring.py`, `embed_baseline.py`, `ollama_client.py`, and
  `mock_ollama.py` for tests.
- `tools/`: `check_prompts_sync.py` (fails if app/ changes under the port),
  `check_go_parity.py` (runs Chimera's own Go decoding against the port on real replies),
  `validate_file.py` (the training-data filter), `check_overlap.py` (eval-leak check).
- `datagen/`: the synthetic data generator (see `datagen/README.md`); `run_datagen.sh` runs it.
  Its output goes in `data/` (not in git).
- `run_v2.sh`: v2 in one go: v2's data (`datagen/README.md`, "v2"), then `NAME=v2 EPOCHS=1 DATA=data/sft-v2
  bash run_train.sh`. v2's reviewer writes a `check` of each requirement before its verdict; Chimera ignores the
  field (`schemas/SOURCES.md`).
- `run_v3.sh`: v3 in one go (`datagen/README.md`, "v3"): checks that start from the task's requirements and show
  their working, more of the flaws v2 missed, long batches in 3 to 5 groups; then `NAME=v3 ... DATA=data/sft-v3`.
- `train/` and `run_train.sh`: LoRA training with MLX-LM on Qwen3-4B-Instruct-2507 (all 36 layers, rank 16,
  2 epochs, learning rate 2e-5 with warmup and cosine decay, loss on the answers only), merged, converted to
  GGUF and quantized with llama.cpp (Q5_K_M since v3, `QUANT=` to change it; `train/gguf_source.py` supplies the base model's tokenizer files,
  which llama.cpp's converter can read), put into Ollama as `chimera-helper:<name>` with the base model's
  template, then scored on the eval like the baselines. `train/mlx-requirements.txt` pins the MLX-LM environment
  v1 was trained with. Model files go in `~/chimera-tools/helper-train/<name>/`; the summary in
  `results/TRAINING-<name>.md`.
- `tests/`: `python3 -m unittest discover -s tests -t .` (stdlib only, Python 3.9+).
- `results/`: `runs/<time>-<model>/` per run (meta, raw replies, summary) and `BASELINES.md`.
- `run_baselines.sh` (or double-click `run_baselines.command`): pulls and scores the stock models.

## Common commands

From `~/Desktop/chimera/helper-model`. Each line is one command to run as it is (no comments to paste):

- `python3 -m unittest discover -s tests -t .`: the tests, 80-odd, a few seconds.
- `python3 tools/check_prompts_sync.py`: after any change to app/.
- `bash run_baselines.sh`: qwen3 1.7b/4b/8b plus the embedding check; `THINK=false bash run_baselines.sh` also scores thinking off.
- `python3 runner/run_eval.py --model qwen3.5:4b`: any other Ollama model; add `--dry-run` to see the exact requests.
- `python3 runner/rescore.py --all` then `python3 runner/report.py`: after changing the scoring.
- `python3 runner/compare.py RUN RUN`: runs side by side, case by case.
- `python3 runner/run_eval.py --model M --jobs reviewer --variant check-first`: an experiment, a check before the verdict.
- `python3 runner/run_eval.py --model hydra:1.0 --jobs reviewer --temperature 0 --seed none --samples 10`: the planner and reviewer at a set temperature (Chimera sends none, so the Modelfile's applies); runs get a `-t0` mark.
- `python3 tools/validate_file.py --job planner teacher.jsonl --tidy --keep kept.jsonl --reject rejected.jsonl`: filter teacher output.
- `python3 tools/check_overlap.py train.jsonl`: before every training run.
- `bash run_datagen.sh`: a smoke run, then the overnight data run.
- `bash run_train.sh`: train, put it in Ollama as `chimera-helper:v1`, score it; `NAME=v3 EPOCHS=3 bash run_train.sh` for another run.
- `bash run_v2.sh` and `bash run_v3.sh`: those versions' data (about 5 h each), training and the eval.
- `bash run_settings.sh`: the latest helper at temperature 0.2 and 0, and unquantized (about 15 min).
- `bash run_quants.sh`: the latest helper at Q5_K_M, Q6_K and Q8_0 (about 20 min).
- `bash run_long_reviews.sh`: the long review cases on hydra:1.0 and gpt-oss:120b (about 10 min).

## Rules for the training data

1. **Nothing written by Claude goes into training**: not the eval set, not the test
   fixtures, not seed prompts, targets or rewrites. Anthropic's terms bar training on Claude
   outputs. The teacher is gpt-oss:120b on the Studio.
2. **The eval set stays out**: seeds for synthetic data must come from somewhere else, and
   every training file goes through `tools/check_overlap.py` (canary string, repeated
   prompts, shared 8-grams).
3. **Filter every teacher reply** with `tools/validate_file.py` (strict schema plus sanity
   rules; `--tidy` applies format-only fixes first).
4. **The teacher is installed** (gpt-oss:120b, 65.4 GB, all layers checked Oct 28). It's
   "tight" under the 72 GB usable rule and above the default 57 GB lending limit, so generate
   data while the Studio isn't lending.

## Licences (checked Oct 27, 2026)

| Model | Licence | Notes |
|---|---|---|
| Qwen3 1.7B, 4B, 8B | Apache 2.0 | Each size's Hugging Face card. Ollama's plain `qwen3:4b` is `qwen3:4b-thinking-2507` (same digest, 256K context); 1.7b and 8b are the original hybrid models (40K). |
| Qwen3-4B-Instruct-2507 | Apache 2.0 | Non-thinking only, 256K context. Ollama tag `qwen3:4b-instruct-2507-q4_K_M` (2.5 GB). Baselined Oct 28. |
| Qwen3.5 0.8B, 2B, 4B, 9B | Apache 2.0 | Newer (March 2026), dense, with vision. Checked on Ollama's 0.8b licence file and Artificial Analysis; check the exact size's card before committing. Not in the baselines yet. |
| Qwen3.8 | 27B Apache 2.0; larger ones other licences | No size under 27B, so not a helper candidate. |
| Qwen3-Embedding 0.6B | Apache 2.0 | Queries need the `Instruct: …\nQuery:…` prefix. |
| gpt-oss-120b (teacher) | Apache 2.0 | Plus a two-sentence usage policy (comply with applicable law). Nothing found restricting training on its outputs. |

## What isn't verified

- The Python port of how Chimera reads replies matched Chimera's own Go code on all 1,435
  replies so far (`results/GO_PARITY.txt`, Oct 28; `run_baselines.sh` re-checks it each run).
  Known approximations are marked "approx" in `helper/chimera_port.py`.
- The eval labels, the Head descriptions marked hypothetical, and the plan-quality rules are
  judgement calls, documented next to each item.
- Timings depend on what else the Studio is doing; runs record the Ollama version, the model
  digest and the settings, but not the machine's load.
