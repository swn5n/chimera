# qwen3:4b on the helper eval (v0-draft)

2026-10-27T17:41:12-05:00 · Ollama 0.40.1 · digest `359d7dd4bcda` · think=false · seed=7 · samples=1

## Planner

Chimera accepts 95%, strictly valid 79% (79% after format-only tidying), quality 0.85 (coverage 94%, step count 84%, kind 79%, parallel 79%, no review step 89%). Latency p50 3.6 s, p95 4.8 s; thinks on 0% of calls.

| case | accepted | valid | steps | width | kind | quality | missed | errors |
|---|---|---|---|---|---|---|---|---|
| code-01 | yes | yes | 5 | 4 | code | 1.00 | – | – |
| code-02 | yes | yes | 5 | 2 | code | 1.00 | – | – |
| code-03 | yes | yes | 3 | 1 | code | 1.00 | – | – |
| code-04 | yes | yes | 3 | 2 | code | 1.00 | – | – |
| code-05 | yes | yes | 4 | 1 | general | 0.80 | – | – |
| res-01 | yes | yes | 6 | 5 | research | 1.00 | – | – |
| res-02 | yes | yes | 5 | 3 | general | 0.80 | – | – |
| res-03 | yes | yes | 5 | 3 | writing | 0.80 | – | – |
| res-04 | yes | no | 4 | 2 | research | 0.96 | licen | schema:additionalProperties, schema:required |
| res-05 | yes | yes | 4 | 4 | writing | 1.00 | – | – |
| bl-01 | yes | yes | 4 | 4 | blender | 1.00 | – | – |
| bl-02 | yes | yes | 3 | 1 | blender | 1.00 | – | – |
| bl-03 | yes | yes | 4 | 1 | blender | 0.80 | – | – |
| bl-04 | yes | yes | 2 | 1 | code | 0.80 | – | – |
| bl-05 | NO | no | – | – | – | 0.00 | bake, bass, emission, 32, compositor, camera | chimera_rejects, id_missing, schema:additionalProperties, schema:maxItems, schema:required, schema:type, step_count |
| batch-01 | yes | no | 1 | 1 | writing | 0.60 | – | schema:minItems, step_count |
| batch-02 | yes | no | 1 | 1 | writing | 0.60 | – | schema:minItems, step_count |
| batch-03 | yes | yes | 2 | 1 | writing | 1.00 | – | – |
| batch-04 | yes | yes | 4 | 4 | code | 1.00 | – | – |

## Reviewer

Chimera accepts 100%, strictly valid 100%, done right 64%: caught 67% of flawed results, accepted 60% of good ones, named the main flaw 83% of the time it caught one; score in band 50%. Latency p50 0.8 s.

| case | accepted | expected | said | score | main flaw named |
|---|---|---|---|---|---|
| rev-01 | yes | done | not done | 90 | – |
| rev-02 | yes | not done | not done | 60 | yes |
| rev-03 | yes | not done | not done | 50 | yes |
| rev-04 | yes | not done | done | 100 | – |
| rev-05 | yes | done | done | 100 | – |
| rev-06 | yes | not done | done | 100 | – |
| rev-07 | yes | not done | not done | 60 | no |
| rev-08 | yes | done | not done | 60 | – |
| rev-09 | yes | not done | done | 100 | – |
| rev-10 | yes | not done | not done | 85 | yes |
| rev-11 | yes | not done | not done | 60 | yes |
| rev-12 | yes | done | done | 100 | – |
| rev-13 | yes | done | done | 100 | – |
| rev-14 | yes | not done | not done | 80 | yes |

## Head gate

On 29 confident pairs: accuracy 86%, precision 73%, recall 100% (4 false yes, 0 false no). Through Chimera's word filter then the gate: 86%; word rule alone (no model): 66%. Chimera accepts 100% of answers. Latency p50 0.1 s, p95 0.2 s, 0 over 8 s.

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
| chat-07/comfyui-image | medium | no | use ✗ | yes (0.83) | use |
| chat-08/comfyui-image | high | no | no | yes (0.50) | no |
| chat-09/acestep-music | medium | no | no | yes (0.67) | no |
| chat-10/comfyui-image | high | no | no | yes (0.25) | no |
| chat-11/comfyui-image | high | no | use ✗ | yes (0.42) | no |
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

