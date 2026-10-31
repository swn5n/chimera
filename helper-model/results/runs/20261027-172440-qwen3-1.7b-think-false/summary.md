# qwen3:1.7b on the helper eval (v0-draft)

2026-10-27T17:24:40-05:00 · Ollama 0.40.1 · digest `8f68893c685c` · think=false · seed=7 · samples=1

## Planner

Chimera accepts 100%, strictly valid 32% (84% after format-only tidying), quality 0.84 (coverage 95%, step count 89%, kind 63%, parallel 79%, no review step 95%). Latency p50 1.3 s, p95 1.7 s; thinks on 0% of calls.

| case | accepted | valid | steps | width | kind | quality | missed | errors |
|---|---|---|---|---|---|---|---|---|
| code-01 | yes | no | 5 | 5 | code | 1.00 | – | schema:enum, schema:required |
| code-02 | yes | no | 4 | 4 | code | 1.00 | – | schema:required |
| code-03 | yes | no | 3 | 3 | general | 0.80 | – | schema:required |
| code-04 | yes | no | 4 | 4 | code | 1.00 | – | schema:required |
| code-05 | yes | no | 4 | 4 | general | 0.80 | – | schema:required |
| res-01 | yes | yes | 4 | 4 | research | 1.00 | – | – |
| res-02 | yes | no | 5 | 5 | general | 0.80 | – | schema:required |
| res-03 | yes | no | 4 | 4 | writing | 0.96 | point | schema:required |
| res-04 | yes | yes | 3 | 1 | general | 0.40 | – | – |
| res-05 | yes | no | 1 | 1 | writing | 0.60 | – | schema:minItems, schema:required, step_count |
| bl-01 | yes | yes | 3 | 1 | blender | 0.80 | – | – |
| bl-02 | yes | no | 1 | 1 | blender | 0.75 | selected | schema:minItems, schema:required, step_count |
| bl-03 | yes | no | 4 | 4 | blender | 0.97 | overlap | schema:required |
| bl-04 | yes | no | 4 | 4 | code | 0.80 | – | schema:required |
| bl-05 | yes | no | 4 | 4 | blender | 1.00 | – | schema:required |
| batch-01 | yes | no | 3 | 3 | general | 1.00 | – | schema:required |
| batch-02 | yes | yes | 2 | 2 | general | 0.52 | lanternfly, hearthstone | – |
| batch-03 | yes | yes | 2 | 2 | general | 1.00 | – | – |
| batch-04 | yes | yes | 4 | 4 | writing | 0.80 | – | – |

## Reviewer

Chimera accepts 86%, strictly valid 71%, done right 71%: caught 67% of flawed results, accepted 80% of good ones, named the main flaw 83% of the time it caught one; score in band 43%. Latency p50 0.4 s.

| case | accepted | expected | said | score | main flaw named |
|---|---|---|---|---|---|
| rev-01 | NO | done | done | – | – |
| rev-02 | NO | not done | done | – | – |
| rev-03 | yes | not done | not done | 60 | yes |
| rev-04 | yes | not done | not done | 85 | yes |
| rev-05 | yes | done | done | 95 | – |
| rev-06 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | not done | 85 | no |
| rev-08 | yes | done | not done | 75 | – |
| rev-09 | yes | not done | done | 100 | – |
| rev-10 | yes | not done | not done | 85 | yes |
| rev-11 | yes | not done | not done | 60 | yes |
| rev-12 | yes | done | done | 100 | – |
| rev-13 | yes | done | done | 100 | – |
| rev-14 | yes | not done | not done | 65 | yes |

## Head gate

On 29 confident pairs: accuracy 83%, precision 69%, recall 100% (5 false yes, 0 false no). Through Chimera's word filter then the gate: 86%; word rule alone (no model): 66%. Chimera accepts 100% of answers. Latency p50 0.1 s, p95 0.1 s, 0 over 8 s.

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
| chat-07/comfyui-image | medium | no | use ✗ | yes (0.83) | use |
| chat-08/comfyui-image | high | no | no | yes (0.50) | no |
| chat-09/acestep-music | medium | no | use ✗ | yes (0.67) | no |
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

