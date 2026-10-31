# qwen3:1.7b on the helper eval (v1.1)

2026-10-27T23:13:57-05:00 · Ollama 0.40.1 · digest `8f68893c685c` · think=unset · seed=7 · samples=1

## Planner

Chimera accepts 100%, strictly valid 14% (86% after format-only tidying), quality 0.80 (coverage 91%, step count 84%, kind 36%, parallel 93%, no review step 98%). Latency p50 4.0 s, p95 8.4 s; thinks on 100% of calls.

| case | accepted | valid | steps | width | kind | quality | missed | errors |
|---|---|---|---|---|---|---|---|---|
| code-01 | yes | no | 5 | 5 | general | 0.80 | – | schema:required |
| code-02 | yes | yes | 3 | 1 | general | 0.80 | – | – |
| code-03 | yes | no | 4 | 4 | general | 0.76 | sethome | schema:required |
| code-04 | yes | no | 3 | 3 | general | 0.80 | – | schema:required |
| code-05 | yes | yes | 2 | 1 | general | 0.80 | – | – |
| code-06 | yes | no | 3 | 3 | general | 0.80 | – | schema:required |
| code-07 | yes | no | 3 | 3 | code | 1.00 | – | schema:required |
| code-08 | yes | no | 6 | 6 | general | 0.80 | – | schema:required |
| code-09 | yes | no | 4 | 4 | general | 0.76 | launchd | schema:required |
| code-10 | yes | no | 3 | 3 | general | 0.80 | – | schema:required |
| code-11 | yes | no | 3 | 3 | general | 0.80 | – | schema:required |
| code-12 | yes | no | 3 | 3 | general | 0.80 | – | schema:required |
| res-01 | yes | no | 4 | 4 | research | 1.00 | – | schema:required |
| res-02 | yes | no | 5 | 5 | general | 0.80 | – | schema:required |
| res-03 | yes | no | 4 | 4 | writing | 0.96 | point | schema:required |
| res-04 | yes | no | 4 | 4 | general | 0.60 | – | schema:required |
| res-05 | yes | yes | 5 | 5 | general | 0.80 | – | – |
| res-06 | yes | no | 3 | 3 | writing | 1.00 | – | schema:required |
| res-07 | yes | no | 5 | 5 | general | 0.80 | – | schema:required |
| res-08 | yes | no | 4 | 4 | general | 0.77 | buy | schema:required |
| res-09 | yes | no | 7 | 7 | general | 0.80 | – | schema:required |
| res-10 | yes | no | 1 | 1 | general | 0.35 | empfehl | schema:minItems, step_count |
| res-11 | yes | no | 4 | 4 | writing | 1.00 | – | schema:required |
| bl-01 | yes | no | 4 | 4 | blender | 1.00 | – | schema:required |
| bl-02 | yes | yes | 3 | 1 | general | 0.75 | selected | – |
| bl-03 | yes | no | 4 | 4 | blender | 1.00 | – | schema:required |
| bl-04 | yes | yes | 4 | 1 | general | 0.80 | – | – |
| bl-05 | yes | no | 4 | 4 | blender | 1.00 | – | schema:required |
| bl-06 | yes | no | 5 | 5 | blender | 0.93 | png, headless | schema:required |
| bl-07 | yes | no | 5 | 5 | code | 0.80 | – | schema:required |
| bl-08 | yes | no | 2 | 2 | general | 0.80 | – | schema:required |
| bl-09 | yes | no | 4 | 4 | general | 0.80 | – | schema:required |
| bl-10 | yes | no | 5 | 5 | blender | 1.00 | – | schema:required |
| bl-11 | yes | no | 6 | 6 | blender | 0.77 | compositor | schema:required |
| batch-01 | yes | no | 1 | 1 | general | 0.45 | german, japanese, code block | schema:minItems, step_count |
| batch-02 | yes | no | 8 | 8 | general | 0.56 | hearthstone | schema:maxItems, schema:pattern, schema:required, step_count |
| batch-03 | yes | no | 2 | 2 | general | 1.00 | – | schema:required |
| batch-04 | yes | no | 4 | 4 | writing | 0.80 | – | schema:required |
| batch-05 | yes | no | 8 | 8 | general | 0.55 | summary | schema:maxItems, schema:pattern, step_count |
| batch-06 | yes | no | 2 | 2 | general | 0.80 | group, fix | schema:required |
| batch-07 | yes | no | 1 | 1 | writing | 0.60 | – | schema:minItems, step_count |
| batch-08 | yes | no | 8 | 8 | general | 0.60 | – | schema:maxItems, schema:pattern, schema:required, step_count |
| batch-09 | yes | yes | 2 | 1 | general | 1.00 | – | – |
| batch-10 | yes | no | 6 | 6 | general | 0.77 | weekday | schema:required |

## Reviewer

Chimera accepts 96%, strictly valid 92%, done right 58%: caught 60% of flawed results, accepted 56% of good ones, named the main flaw 78% of the time it caught one; score in band 58%. Latency p50 2.2 s.

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
| rev-15 | yes | done | done | 100 | – |
| rev-16 | yes | not done | not done | 80 | yes |
| rev-17 | yes | not done | not done | 75 | yes |
| rev-18 | yes | done | done | 100 | – |
| rev-19 | yes | not done | not done | 70 | yes |
| rev-20 | yes | not done | not done | 60 | yes |
| rev-21 | yes | done | not done | 85 | – |
| rev-22 | yes | not done | not done | 0 | yes |
| rev-23 | yes | not done | not done | 50 | yes |
| rev-24 | yes | done | not done | 85 | – |

## Head gate

On 43 confident pairs: accuracy 95%, precision 89%, recall 100% (2 false yes, 0 false no). Through Chimera's word filter then the gate: 93%; word rule alone (no model): 58%. Chimera accepts 100% of answers. Latency p50 0.7 s, p95 1.0 s, 0 over 8 s.

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

