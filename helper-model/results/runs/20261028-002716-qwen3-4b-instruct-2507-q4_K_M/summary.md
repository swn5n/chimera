# qwen3:4b-instruct-2507-q4_K_M on the helper eval (v1.1)

2026-10-28T00:27:16-05:00 · Ollama 0.40.1 · digest `0edcdef34593` · think=unset · seed=7 · samples=1

## Planner

Chimera accepts 100%, strictly valid 18% (86% after format-only tidying), quality 0.86 (coverage 99%, step count 64%, kind 84%, parallel 93%, no review step 91%). Latency p50 4.3 s, p95 6.3 s; thinks on 0% of calls.

| case | accepted | valid | steps | width | kind | quality | missed | errors |
|---|---|---|---|---|---|---|---|---|
| code-01 | yes | no | 6 | 2 | code | 1.00 | – | dep_unknown, schema:pattern |
| code-02 | yes | no | 7 | 2 | code | 0.80 | – | dep_unknown, schema:pattern |
| code-03 | yes | no | 6 | 2 | code | 1.00 | – | dep_unknown, schema:pattern |
| code-04 | yes | no | 5 | 3 | code | 1.00 | – | dep_unknown, schema:pattern |
| code-05 | yes | no | 6 | 2 | general | 0.80 | – | dep_unknown, schema:pattern |
| code-06 | yes | no | 5 | 2 | general | 0.60 | – | dep_unknown, id_missing, schema:pattern |
| code-07 | yes | no | 7 | 2 | code | 0.80 | – | schema:pattern |
| code-08 | yes | no | 6 | 2 | code | 1.00 | – | schema:additionalProperties, schema:required |
| code-09 | yes | yes | 4 | 2 | code | 1.00 | – | – |
| code-10 | yes | no | 4 | 2 | code | 1.00 | – | dep_unknown, schema:pattern |
| code-11 | yes | no | 5 | 3 | code | 1.00 | – | schema:pattern |
| code-12 | yes | no | 4 | 3 | code | 1.00 | – | dep_unknown, schema:pattern |
| res-01 | yes | no | 4 | 2 | research | 1.00 | – | dep_unknown, schema:pattern |
| res-02 | yes | yes | 5 | 2 | writing | 1.00 | – | – |
| res-03 | yes | no | 6 | 1 | writing | 0.80 | – | schema:pattern |
| res-04 | yes | no | 5 | 2 | research | 1.00 | – | dep_unknown, schema:pattern |
| res-05 | yes | no | 5 | 5 | writing | 1.00 | – | id_missing, schema:pattern |
| res-06 | yes | yes | 5 | 1 | writing | 0.60 | – | – |
| res-07 | yes | no | 6 | 6 | research | 0.80 | – | schema:pattern |
| res-08 | yes | no | 7 | 4 | research | 0.80 | – | schema:pattern |
| res-09 | yes | no | 7 | 3 | writing | 1.00 | – | schema:pattern |
| res-10 | yes | no | 5 | 1 | research | 0.80 | – | schema:pattern |
| res-11 | yes | no | 1 | 1 | writing | 0.80 | – | schema:minItems, step_count |
| bl-01 | yes | yes | 4 | 1 | blender | 0.80 | – | – |
| bl-02 | yes | no | 5 | 2 | blender | 1.00 | – | dep_unknown, id_missing, schema:pattern |
| bl-03 | yes | no | 6 | 2 | blender | 1.00 | – | schema:pattern |
| bl-04 | yes | no | 6 | 1 | code | 0.60 | – | schema:pattern |
| bl-05 | yes | no | 6 | 2 | blender | 1.00 | – | schema:pattern |
| bl-06 | yes | no | 4 | 2 | blender | 0.97 | headless | dep_unknown, schema:pattern |
| bl-07 | yes | no | 7 | 2 | code | 0.40 | – | id_missing, schema:pattern, schema:required |
| bl-08 | yes | no | 7 | 2 | blender | 0.80 | – | schema:pattern |
| bl-09 | yes | no | 6 | 3 | code | 0.80 | – | dep_unknown, schema:pattern |
| bl-10 | yes | yes | 7 | 2 | blender | 0.80 | – | – |
| bl-11 | yes | no | 6 | 5 | blender | 0.60 | – | schema:pattern |
| batch-01 | yes | yes | 3 | 3 | writing | 1.00 | – | – |
| batch-02 | yes | no | 8 | 8 | writing | 0.76 | hearthstone | id_missing, schema:maxItems, schema:pattern, step_count |
| batch-03 | yes | yes | 2 | 1 | writing | 1.00 | – | – |
| batch-04 | yes | no | 4 | 4 | writing | 0.80 | – | schema:pattern |
| batch-05 | yes | no | 8 | 8 | writing | 0.75 | summary | schema:maxItems, schema:pattern, step_count |
| batch-06 | yes | yes | 5 | 2 | writing | 0.60 | – | – |
| batch-07 | yes | no | 4 | 4 | writing | 1.00 | – | schema:pattern |
| batch-08 | yes | no | 8 | 8 | writing | 0.80 | – | schema:maxItems, schema:pattern, step_count |
| batch-09 | yes | no | 6 | 6 | general | 0.80 | – | schema:required |
| batch-10 | yes | no | 6 | 6 | code | 1.00 | – | id_missing, schema:pattern |

## Reviewer

Chimera accepts 100%, strictly valid 100%, done right 62%: caught 60% of flawed results, accepted 67% of good ones, named the main flaw 89% of the time it caught one; score in band 58%. Latency p50 0.3 s.

| case | accepted | expected | said | score | main flaw named |
|---|---|---|---|---|---|
| rev-01 | yes | done | not done | 50 | – |
| rev-02 | yes | not done | done | 100 | – |
| rev-03 | yes | not done | not done | 50 | yes |
| rev-04 | yes | not done | done | 100 | – |
| rev-05 | yes | done | done | 100 | – |
| rev-06 | yes | not done | done | 100 | – |
| rev-07 | yes | not done | not done | 50 | no |
| rev-08 | yes | done | not done | 50 | – |
| rev-09 | yes | not done | done | 100 | – |
| rev-10 | yes | not done | not done | 70 | yes |
| rev-11 | yes | not done | not done | 40 | yes |
| rev-12 | yes | done | done | 100 | – |
| rev-13 | yes | done | not done | 50 | – |
| rev-14 | yes | not done | not done | 50 | yes |
| rev-15 | yes | done | done | 100 | – |
| rev-16 | yes | not done | not done | 50 | yes |
| rev-17 | yes | not done | not done | 60 | yes |
| rev-18 | yes | done | done | 100 | – |
| rev-19 | yes | not done | done | 100 | – |
| rev-20 | yes | not done | not done | 50 | yes |
| rev-21 | yes | done | done | 100 | – |
| rev-22 | yes | not done | not done | 20 | yes |
| rev-23 | yes | not done | done | 100 | – |
| rev-24 | yes | done | done | 100 | – |

## Head gate

On 43 confident pairs: accuracy 95%, precision 89%, recall 100% (2 false yes, 0 false no). Through Chimera's word filter then the gate: 93%; word rule alone (no model): 58%. Chimera accepts 100% of answers. Latency p50 0.1 s, p95 0.1 s, 0 over 8 s.

| pair | confidence | expected | gate said | reaches gate | word rule |
|---|---|---|---|---|---|
| res-04/text-to-3d | high | no | no | yes (1.00) | use |
| res-07/text-to-3d | high | no | no | yes (0.67) | no |
| bl-05/acestep-music | high | no | no | yes (0.92) | use |
| bl-09/text-to-3d | high | no | no | yes (0.92) | use |
| bl-10/text-to-3d | high | no | no | yes (0.42) | no |
| batch-07/comfyui-image | high | no | no | yes (0.42) | no |
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
| chat-17/comfyui-image | high | no | no | yes (0.75) | use |
| chat-18/comfyui-image | high | no | no | yes (1.00) | use |
| chat-19/comfyui-image | high | no | no | yes (1.00) | use |
| chat-20/text-to-3d | high | no | no | yes (0.42) | no |
| chat-21/acestep-music | high | no | no | yes (0.42) | no |
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
| head-11/comfyui-image | high | use | use | yes (0.42) | no |
| head-12/comfyui-image | high | use | use | yes (0.50) | no |
| head-13/acestep-music | high | use | use | yes (0.50) | no |
| head-14/text-to-3d | high | use | use | yes (1.00) | use |
| head-15/comfyui-image | medium | use | use | no (0.00) | no |

