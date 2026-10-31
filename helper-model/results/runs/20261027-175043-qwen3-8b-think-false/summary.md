# qwen3:8b on the helper eval (v0-draft)

2026-10-27T17:50:43-05:00 · Ollama 0.40.1 · digest `500a1f067a9f` · think=false · seed=7 · samples=1

## Planner

Chimera accepts 95%, strictly valid 84% (84% after format-only tidying), quality 0.84 (coverage 88%, step count 84%, kind 84%, parallel 74%, no review step 89%). Latency p50 4.6 s, p95 11.5 s; thinks on 0% of calls.

| case | accepted | valid | steps | width | kind | quality | missed | errors |
|---|---|---|---|---|---|---|---|---|
| code-01 | yes | yes | 4 | 2 | code | 1.00 | – | – |
| code-02 | yes | yes | 5 | 1 | code | 1.00 | – | – |
| code-03 | yes | yes | 6 | 2 | code | 1.00 | – | – |
| code-04 | yes | yes | 4 | 1 | code | 1.00 | – | – |
| code-05 | yes | yes | 4 | 2 | general | 0.80 | – | – |
| res-01 | yes | yes | 4 | 2 | research | 1.00 | – | – |
| res-02 | yes | yes | 7 | 4 | research | 0.80 | – | – |
| res-03 | yes | yes | 5 | 1 | writing | 0.80 | – | – |
| res-04 | yes | yes | 2 | 1 | research | 0.80 | – | – |
| res-05 | yes | no | 5 | 1 | writing | 0.80 | – | schema:additionalProperties, schema:required |
| bl-01 | yes | yes | 4 | 1 | blender | 0.80 | – | – |
| bl-02 | yes | yes | 5 | 1 | blender | 0.95 | selected | – |
| bl-03 | NO | no | – | – | – | 0.00 | ground, pine, overlap, sun, fog, 30 seconds | chimera_rejects, not_json |
| bl-04 | yes | yes | 4 | 1 | blender | 0.80 | – | – |
| bl-05 | yes | yes | 5 | 2 | general | 0.80 | – | – |
| batch-01 | yes | yes | 3 | 3 | general | 0.85 | german, japanese, code block | – |
| batch-02 | yes | no | 8 | 8 | writing | 0.76 | hearthstone | schema:maxItems, schema:pattern, step_count |
| batch-03 | yes | yes | 2 | 1 | general | 1.00 | – | – |
| batch-04 | yes | yes | 4 | 4 | code | 1.00 | – | – |

## Reviewer

Chimera accepts 100%, strictly valid 100%, done right 71%: caught 67% of flawed results, accepted 80% of good ones, named the main flaw 67% of the time it caught one; score in band 57%. Latency p50 0.6 s.

| case | accepted | expected | said | score | main flaw named |
|---|---|---|---|---|---|
| rev-01 | yes | done | not done | 70 | – |
| rev-02 | yes | not done | not done | 60 | no |
| rev-03 | yes | not done | not done | 60 | yes |
| rev-04 | yes | not done | done | 95 | – |
| rev-05 | yes | done | done | 95 | – |
| rev-06 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | not done | 60 | no |
| rev-08 | yes | done | done | 100 | – |
| rev-09 | yes | not done | done | 98 | – |
| rev-10 | yes | not done | not done | 70 | yes |
| rev-11 | yes | not done | not done | 30 | yes |
| rev-12 | yes | done | done | 100 | – |
| rev-13 | yes | done | done | 100 | – |
| rev-14 | yes | not done | not done | 80 | yes |

## Head gate

On 29 confident pairs: accuracy 93%, precision 85%, recall 100% (2 false yes, 0 false no). Through Chimera's word filter then the gate: 93%; word rule alone (no model): 66%. Chimera accepts 100% of answers. Latency p50 0.1 s, p95 0.2 s, 0 over 8 s.

| pair | confidence | expected | gate said | reaches gate | word rule |
|---|---|---|---|---|---|
| res-04/text-to-3d | high | no | no | yes (1.00) | use |
| bl-05/acestep-music | high | no | no | yes (0.92) | use |
| chat-01/comfyui-image | high | no | no | no (0.00) | no |
| chat-02/comfyui-image | high | no | no | yes (1.00) | use |
| chat-03/comfyui-image | high | no | no | no (0.00) | no |
| chat-04/demo-poster | high | no | no | yes (0.50) | no |
| chat-05/comfyui-image | high | no | no | yes (0.50) | no |
| chat-06/comfyui-image | high | no | no | yes (0.42) | no |
| chat-07/comfyui-image | medium | no | no | yes (0.83) | use |
| chat-08/comfyui-image | high | no | no | yes (0.50) | no |
| chat-09/acestep-music | medium | no | no | yes (0.67) | no |
| chat-10/comfyui-image | high | no | no | yes (0.25) | no |
| chat-11/comfyui-image | high | no | no | yes (0.42) | no |
| chat-11/text-to-3d | high | no | no | yes (0.42) | no |
| chat-12/demo-poster | low | no | use ✗ | yes (0.00) | no |
| chat-13/comfyui-image | medium | no | use ✗ | no (0.17) | no |
| chat-14/comfyui-image | high | no | no | yes (1.00) | use |
| chat-15/comfyui-image | medium | no | use ✗ | no (0.00) | no |
| chat-16/text-to-3d | high | no | no | yes (0.50) | no |
| head-01/comfyui-image | high | use | use | yes (0.92) | use |
| head-02/comfyui-image | high | use | use | no (0.17) | no |
| head-03/comfyui-image | high | use | use | yes (0.42) | no |
| head-04/comfyui-image | high | use | use | yes (0.92) | use |
| head-05/demo-poster | high | use | use | yes (0.75) | use |
| head-05/comfyui-image | medium | use | use | no (0.00) | no |
| head-06/acestep-music | high | use | use | yes (0.83) | use |
| head-07/acestep-music | high | use | use | yes (0.42) | no |
| head-08/text-to-3d | high | use | use | yes (1.00) | use |
| head-09/comfyui-image | medium | use | use | yes (0.83) | use |
| head-10/comfyui-image | high | use | use | yes (0.67) | no |

