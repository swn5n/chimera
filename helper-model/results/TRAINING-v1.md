# Helper model v1: training and eval

LoRA on Qwen3-4B-Instruct-2507 with MLX-LM, imported into Ollama as `chimera-helper:v1` and scored on eval v1.1 with Chimera's exact requests (`runner/run_eval.py`). Files: `/Users/fx/chimera-tools/helper-train/v1`.

## Training

- Train loss 1.666 at step 10 → 0.449 at step 934.
- Validation loss 1.521 at step 1 → 0.716 at step 934 (lowest 0.716 at step 934).
- About 109 trained tokens/s.
- Training took about 156 minutes, including the first download of the base model.
- Into Ollama: GGUF Q4_K_M made with llama.cpp (like the baselines), the base model's template

Settings (`lora.yaml`):

```yaml
# Written by train/make_config.py; MLX-LM LoRA settings for the Chimera helper model.
model: "Qwen/Qwen3-4B-Instruct-2507"
train: true
fine_tune_type: lora
optimizer: adamw
data: "/Users/fx/Desktop/chimera/helper-model/data/sft"
seed: 0
num_layers: 36
batch_size: 4
iters: 934
val_batches: -1
learning_rate: 2.00e-05
steps_per_report: 10
steps_per_eval: 100
grad_accumulation_steps: 1
resume_adapter_file: null
adapter_path: "/Users/fx/chimera-tools/helper-train/v1/adapters"
save_every: 100
test: false
max_seq_length: 8192
grad_checkpoint: true
mask_prompt: true
lora_parameters:
  rank: 16
  scale: 20.0
  dropout: 0.05
lr_schedule:
  name: cosine_decay
  warmup: 40
  warmup_init: 1.0e-07
  arguments: [2.00e-05, 894, 2.00e-06]
```

## Eval

| Model | Plan quality (strictly valid) | Reviewer right | Gate right | p50: plan / review / gate |
|---|---|---|---|---|
| **chimera-helper:v1 (this run)** | 0.92 (91% strict) | 71% (caught 73%, accepted good 67%) | 98% | 3.995 s / 0.579 s / 0.081 s |
| qwen3:4b-instruct-2507 (the base, untrained) | 0.86 (18% strict) | 62% (caught 60%, accepted good 67%) | 95% | 4.334 s / 0.253 s / 0.089 s |
| qwen3:4b, thinking (best stock) | 0.95 (93% strict) | 96% (caught 100%, accepted good 89%) | 100% | 31.005 s / 9.189 s / 1.77 s |
| gpt-oss:120b (teacher) | 0.92 (98% strict) | 96% (caught 93%, accepted good 100%) | 98% | 11.253 s / 3.117 s / 1.03 s |

Full per-case detail: `results/runs/<time>-chimera-helper-v1*/summary.md`.
