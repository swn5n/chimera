# chimera-helper:v2 on the helper eval (v1.1)

2026-10-28T22:34:56-05:00 · Ollama 0.40.1 · digest `6b8d96ff77dc` · think=unset · seed=7 · samples=1

## Planner

Chimera accepts 100%, strictly valid 89% (91% after format-only tidying), quality 0.94 (coverage 98%, step count 89%, kind 91%, parallel 91%, no review step 100%). Latency p50 4.4 s, p95 5.8 s; thinks on 0% of calls.

| case | accepted | valid | steps | width | kind | quality | missed | errors |
|---|---|---|---|---|---|---|---|---|
| code-01 | yes | yes | 5 | 2 | code | 1.00 | – | – |
| code-02 | yes | yes | 3 | 1 | code | 1.00 | – | – |
| code-03 | yes | yes | 5 | 2 | code | 1.00 | – | – |
| code-04 | yes | no | 3 | 1 | code | 0.93 | table-driven | schema:enum |
| code-05 | yes | no | 2 | 1 | code | 1.00 | – | dep_self, id_duplicate |
| code-06 | yes | yes | 2 | 1 | code | 1.00 | – | – |
| code-07 | yes | yes | 4 | 2 | code | 1.00 | – | – |
| code-08 | yes | yes | 2 | 1 | code | 0.80 | – | – |
| code-09 | yes | yes | 2 | 1 | code | 1.00 | – | – |
| code-10 | yes | yes | 3 | 1 | code | 1.00 | – | – |
| code-11 | yes | yes | 2 | 1 | code | 0.97 | retry-after | – |
| code-12 | yes | yes | 3 | 2 | code | 1.00 | – | – |
| res-01 | yes | yes | 4 | 3 | research | 1.00 | – | – |
| res-02 | yes | yes | 5 | 2 | writing | 1.00 | – | – |
| res-03 | yes | yes | 5 | 3 | writing | 1.00 | – | – |
| res-04 | yes | yes | 4 | 2 | research | 1.00 | – | – |
| res-05 | yes | yes | 2 | 1 | writing | 0.80 | – | – |
| res-06 | yes | yes | 4 | 3 | writing | 1.00 | – | – |
| res-07 | yes | yes | 4 | 3 | writing | 1.00 | – | – |
| res-08 | yes | yes | 4 | 3 | research | 0.97 | 10gbe | – |
| res-09 | yes | yes | 5 | 2 | writing | 1.00 | – | – |
| res-10 | yes | yes | 2 | 1 | writing | 0.80 | – | – |
| res-11 | yes | yes | 2 | 1 | writing | 1.00 | – | – |
| bl-01 | yes | yes | 4 | 1 | blender | 0.80 | – | – |
| bl-02 | yes | yes | 2 | 1 | blender | 1.00 | – | – |
| bl-03 | yes | yes | 4 | 2 | blender | 1.00 | – | – |
| bl-04 | yes | yes | 2 | 2 | code | 0.80 | – | – |
| bl-05 | yes | yes | 5 | 2 | blender | 1.00 | – | – |
| bl-06 | yes | yes | 3 | 1 | code | 1.00 | – | – |
| bl-07 | yes | yes | 2 | 1 | code | 0.80 | – | – |
| bl-08 | yes | yes | 2 | 1 | blender | 1.00 | – | – |
| bl-09 | yes | yes | 3 | 1 | code | 0.80 | – | – |
| bl-10 | yes | yes | 4 | 1 | blender | 1.00 | – | – |
| bl-11 | yes | yes | 6 | 5 | blender | 0.77 | compositor | – |
| batch-01 | yes | yes | 3 | 3 | writing | 1.00 | – | – |
| batch-02 | yes | no | 8 | 8 | writing | 0.76 | hearthstone | schema:maxItems, schema:pattern, step_count |
| batch-03 | yes | yes | 2 | 1 | writing | 1.00 | – | – |
| batch-04 | yes | yes | 4 | 4 | code | 1.00 | – | – |
| batch-05 | yes | no | 8 | 8 | writing | 0.80 | – | schema:maxItems, schema:pattern, step_count |
| batch-06 | yes | yes | 3 | 1 | writing | 0.80 | – | – |
| batch-07 | yes | yes | 4 | 4 | writing | 1.00 | – | – |
| batch-08 | yes | no | 8 | 8 | writing | 0.80 | – | schema:maxItems, schema:pattern, step_count |
| batch-09 | yes | yes | 6 | 5 | writing | 0.80 | – | – |
| batch-10 | yes | yes | 6 | 6 | code | 1.00 | – | – |

## Reviewer

Chimera accepts 100%, strictly valid 100%, done right 79%: caught 73% of flawed results, accepted 89% of good ones, named the main flaw 91% of the time it caught one; score in band 75%. Latency p50 0.7 s. Check written first 100%, median 179 characters.

| case | accepted | expected | said | score | main flaw named |
|---|---|---|---|---|---|
| rev-01 | yes | done | done | 95 | – |
| rev-02 | yes | not done | not done | 80 | yes |
| rev-03 | yes | not done | not done | 40 | yes |
| rev-04 | yes | not done | not done | 70 | yes |
| rev-05 | yes | done | done | 95 | – |
| rev-06 | yes | not done | done | 95 | – |
| rev-07 | yes | not done | done | 95 | – |
| rev-08 | yes | done | not done | 30 | – |
| rev-09 | yes | not done | not done | 60 | yes |
| rev-10 | yes | not done | not done | 40 | no |
| rev-11 | yes | not done | not done | 40 | yes |
| rev-12 | yes | done | done | 100 | – |
| rev-13 | yes | done | done | 100 | – |
| rev-14 | yes | not done | not done | 70 | yes |
| rev-15 | yes | done | done | 100 | – |
| rev-16 | yes | not done | not done | 30 | yes |
| rev-17 | yes | not done | not done | 45 | yes |
| rev-18 | yes | done | done | 100 | – |
| rev-19 | yes | not done | done | 100 | – |
| rev-20 | yes | not done | not done | 20 | yes |
| rev-21 | yes | done | done | 95 | – |
| rev-22 | yes | not done | not done | 30 | yes |
| rev-23 | yes | not done | done | 100 | – |
| rev-24 | yes | done | done | 90 | – |

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

