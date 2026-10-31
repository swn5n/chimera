# qwen3:4b on the helper eval (v0-draft)

2026-10-27T17:25:13-05:00 · Ollama 0.40.1 · digest `359d7dd4bcda` · think=unset · seed=7 · samples=1

## Planner

Chimera accepts 100%, strictly valid 95% (100% after format-only tidying), quality 0.96 (coverage 99%, step count 100%, kind 89%, parallel 89%, no review step 100%). Latency p50 30.9 s, p95 46.2 s; thinks on 100% of calls.

| case | accepted | valid | steps | width | kind | quality | missed | errors |
|---|---|---|---|---|---|---|---|---|
| code-01 | yes | yes | 5 | 2 | code | 1.00 | – | – |
| code-02 | yes | yes | 4 | 1 | code | 1.00 | – | – |
| code-03 | yes | yes | 4 | 3 | code | 1.00 | – | – |
| code-04 | yes | yes | 2 | 1 | code | 1.00 | – | – |
| code-05 | yes | yes | 3 | 2 | code | 1.00 | – | – |
| res-01 | yes | yes | 4 | 3 | research | 1.00 | – | – |
| res-02 | yes | yes | 3 | 2 | writing | 1.00 | – | – |
| res-03 | yes | yes | 4 | 3 | writing | 0.96 | point | – |
| res-04 | yes | yes | 3 | 1 | research | 0.80 | – | – |
| res-05 | yes | no | 5 | 5 | writing | 1.00 | – | schema:required |
| bl-01 | yes | yes | 4 | 3 | blender | 1.00 | – | – |
| bl-02 | yes | yes | 2 | 1 | blender | 1.00 | – | – |
| bl-03 | yes | yes | 4 | 3 | blender | 1.00 | – | – |
| bl-04 | yes | yes | 4 | 1 | code | 0.80 | – | – |
| bl-05 | yes | yes | 5 | 3 | blender | 1.00 | – | – |
| batch-01 | yes | yes | 3 | 3 | writing | 1.00 | – | – |
| batch-02 | yes | yes | 2 | 2 | writing | 0.80 | – | – |
| batch-03 | yes | yes | 2 | 1 | writing | 1.00 | – | – |
| batch-04 | yes | yes | 4 | 4 | writing | 0.80 | – | – |

## Reviewer

Chimera accepts 100%, strictly valid 100%, done right 93%: caught 100% of flawed results, accepted 80% of good ones, named the main flaw 78% of the time it caught one; score in band 93%. Latency p50 18.2 s.

| case | accepted | expected | said | score | main flaw named |
|---|---|---|---|---|---|
| rev-01 | yes | done | done | 100 | – |
| rev-02 | yes | not done | not done | 50 | yes |
| rev-03 | yes | not done | not done | 50 | yes |
| rev-04 | yes | not done | not done | 70 | yes |
| rev-05 | yes | done | done | 100 | – |
| rev-06 | yes | not done | not done | 50 | yes |
| rev-07 | yes | not done | not done | 50 | no |
| rev-08 | yes | done | not done | 65 | – |
| rev-09 | yes | not done | not done | 80 | no |
| rev-10 | yes | not done | not done | 55 | yes |
| rev-11 | yes | not done | not done | 20 | yes |
| rev-12 | yes | done | done | 100 | – |
| rev-13 | yes | done | done | 100 | – |
| rev-14 | yes | not done | not done | 70 | yes |

## Head gate

On 29 confident pairs: accuracy 100%, precision 100%, recall 100% (0 false yes, 0 false no). Through Chimera's word filter then the gate: 93%; word rule alone (no model): 66%. Chimera accepts 100% of answers. Latency p50 1.9 s, p95 3.2 s, 0 over 8 s.

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
| chat-12/demo-poster | low | no | no | yes (0.00) | no |
| chat-13/comfyui-image | medium | no | no | no (0.17) | no |
| chat-14/comfyui-image | high | no | no | yes (1.00) | use |
| chat-15/comfyui-image | medium | no | no | no (0.00) | no |
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

