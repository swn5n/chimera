# qwen3:1.7b on the helper eval (v0-draft)

2026-10-27T17:21:16-05:00 · Ollama 0.40.1 · digest `8f68893c685c` · think=unset · seed=7 · samples=1

## Planner

Chimera accepts 100%, strictly valid 26% (89% after format-only tidying), quality 0.81 (coverage 92%, step count 89%, kind 37%, parallel 95%, no review step 95%). Latency p50 4.8 s, p95 9.7 s; thinks on 100% of calls.

| case | accepted | valid | steps | width | kind | quality | missed | errors |
|---|---|---|---|---|---|---|---|---|
| code-01 | yes | no | 5 | 5 | general | 0.80 | – | schema:required |
| code-02 | yes | yes | 3 | 1 | general | 0.80 | – | – |
| code-03 | yes | no | 4 | 4 | general | 0.76 | sethome | schema:required |
| code-04 | yes | no | 3 | 3 | general | 0.80 | – | schema:required |
| code-05 | yes | yes | 2 | 1 | general | 0.80 | – | – |
| res-01 | yes | no | 4 | 4 | research | 1.00 | – | schema:required |
| res-02 | yes | no | 5 | 5 | general | 0.80 | – | schema:required |
| res-03 | yes | no | 4 | 4 | writing | 0.96 | point | schema:required |
| res-04 | yes | no | 4 | 4 | general | 0.60 | – | schema:required |
| res-05 | yes | yes | 5 | 5 | general | 0.80 | – | – |
| bl-01 | yes | no | 4 | 4 | blender | 1.00 | – | schema:required |
| bl-02 | yes | yes | 3 | 1 | general | 0.75 | selected | – |
| bl-03 | yes | no | 4 | 4 | blender | 1.00 | – | schema:required |
| bl-04 | yes | yes | 4 | 1 | general | 0.80 | – | – |
| bl-05 | yes | no | 4 | 4 | blender | 1.00 | – | schema:required |
| batch-01 | yes | no | 1 | 1 | general | 0.45 | german, japanese, code block | schema:minItems, step_count |
| batch-02 | yes | no | 8 | 8 | general | 0.56 | hearthstone | schema:maxItems, schema:pattern, schema:required, step_count |
| batch-03 | yes | no | 2 | 2 | general | 1.00 | – | schema:required |
| batch-04 | yes | no | 4 | 4 | writing | 0.80 | – | schema:required |

## Reviewer

Chimera accepts 93%, strictly valid 86%, done right 43%: caught 33% of flawed results, accepted 60% of good ones, named the main flaw 33% of the time it caught one; score in band 43%. Latency p50 2.4 s.

| case | accepted | expected | said | score | main flaw named |
|---|---|---|---|---|---|
| rev-01 | yes | done | not done | 85 | – |
| rev-02 | yes | not done | not done | 65 | no |
| rev-03 | yes | not done | done | 100 | – |
| rev-04 | yes | not done | done | 95 | – |
| rev-05 | yes | done | done | 100 | – |
| rev-06 | yes | not done | done | 100 | – |
| rev-07 | yes | not done | done | 100 | – |
| rev-08 | yes | done | not done | 60 | – |
| rev-09 | yes | not done | done | 100 | – |
| rev-10 | yes | not done | not done | 70 | no |
| rev-11 | yes | not done | not done | 20 | yes |
| rev-12 | yes | done | done | 100 | – |
| rev-13 | yes | done | done | 100 | – |
| rev-14 | NO | not done | done | – | – |

## Head gate

On 29 confident pairs: accuracy 93%, precision 85%, recall 100% (2 false yes, 0 false no). Through Chimera's word filter then the gate: 93%; word rule alone (no model): 66%. Chimera accepts 100% of answers. Latency p50 0.8 s, p95 1.1 s, 0 over 8 s.

| pair | confidence | expected | gate said | reaches gate | word rule |
|---|---|---|---|---|---|
| res-04/text-to-3d | high | no | no | yes (1.00) | use |
| bl-05/acestep-music | high | no | no | yes (0.92) | use |
| chat-01/comfyui-image | high | no | no | no (0.00) | no |
| chat-02/comfyui-image | high | no | no | yes (1.00) | use |
| chat-03/comfyui-image | high | no | use ✗ | no (0.00) | no |
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
| chat-13/comfyui-image | medium | no | no | no (0.17) | no |
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

