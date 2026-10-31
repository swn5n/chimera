# chimera-helper:v3-bf16 on the helper eval (v1.1)

2026-10-29T10:45:47-05:00 · Ollama 0.40.1 · digest `a2a6339f875b` · think=unset · seed=7 · samples=1

## Planner

Chimera accepts 100%, strictly valid 91% (91% after format-only tidying), quality 0.93 (coverage 99%, step count 89%, kind 91%, parallel 91%, no review step 95%). Latency p50 8.1 s, p95 14.3 s; thinks on 0% of calls.

| case | accepted | valid | steps | width | kind | quality | missed | errors |
|---|---|---|---|---|---|---|---|---|
| code-01 | yes | yes | 5 | 2 | code | 1.00 | – | – |
| code-02 | yes | yes | 3 | 1 | code | 1.00 | – | – |
| code-03 | yes | yes | 5 | 2 | code | 1.00 | – | – |
| code-04 | yes | yes | 2 | 1 | code | 0.93 | table-driven | – |
| code-05 | yes | no | 2 | 2 | general | 0.80 | – | schema:enum |
| code-06 | yes | yes | 3 | 2 | code | 1.00 | – | – |
| code-07 | yes | yes | 5 | 3 | code | 1.00 | – | – |
| code-08 | yes | yes | 3 | 2 | code | 1.00 | – | – |
| code-09 | yes | yes | 3 | 2 | code | 1.00 | – | – |
| code-10 | yes | yes | 3 | 1 | code | 1.00 | – | – |
| code-11 | yes | yes | 3 | 1 | code | 1.00 | – | – |
| code-12 | yes | yes | 2 | 1 | code | 1.00 | – | – |
| res-01 | yes | yes | 5 | 2 | research | 1.00 | – | – |
| res-02 | yes | yes | 3 | 2 | writing | 1.00 | – | – |
| res-03 | yes | yes | 3 | 1 | writing | 0.80 | – | – |
| res-04 | yes | yes | 3 | 2 | research | 1.00 | – | – |
| res-05 | yes | yes | 5 | 5 | writing | 1.00 | – | – |
| res-06 | yes | yes | 4 | 4 | writing | 1.00 | – | – |
| res-07 | yes | yes | 4 | 3 | writing | 0.80 | – | – |
| res-08 | yes | yes | 5 | 4 | research | 0.97 | 10gbe | – |
| res-09 | yes | yes | 7 | 7 | writing | 1.00 | – | – |
| res-10 | yes | yes | 2 | 1 | writing | 0.80 | – | – |
| res-11 | yes | no | 1 | 1 | writing | 0.80 | – | schema:minItems, step_count |
| bl-01 | yes | yes | 5 | 3 | blender | 1.00 | – | – |
| bl-02 | yes | yes | 3 | 1 | blender | 1.00 | – | – |
| bl-03 | yes | yes | 3 | 1 | blender | 0.60 | – | – |
| bl-04 | yes | yes | 2 | 1 | code | 0.80 | – | – |
| bl-05 | yes | yes | 4 | 2 | blender | 1.00 | – | – |
| bl-06 | yes | yes | 3 | 2 | blender | 1.00 | – | – |
| bl-07 | yes | yes | 5 | 1 | code | 0.80 | – | – |
| bl-08 | yes | yes | 3 | 1 | blender | 1.00 | – | – |
| bl-09 | yes | yes | 3 | 1 | blender | 1.00 | – | – |
| bl-10 | yes | yes | 4 | 1 | blender | 1.00 | – | – |
| bl-11 | yes | yes | 7 | 5 | blender | 0.77 | compositor | – |
| batch-01 | yes | yes | 3 | 3 | writing | 1.00 | – | – |
| batch-02 | yes | yes | 2 | 2 | writing | 0.80 | – | – |
| batch-03 | yes | yes | 3 | 2 | writing | 1.00 | – | – |
| batch-04 | yes | yes | 4 | 4 | code | 1.00 | – | – |
| batch-05 | yes | no | 8 | 8 | writing | 0.80 | – | schema:maxItems, schema:pattern, step_count |
| batch-06 | yes | yes | 2 | 1 | writing | 0.80 | – | – |
| batch-07 | yes | yes | 4 | 4 | writing | 1.00 | – | – |
| batch-08 | yes | no | 8 | 8 | writing | 0.80 | – | schema:maxItems, schema:pattern, step_count |
| batch-09 | yes | yes | 6 | 5 | writing | 0.80 | – | – |
| batch-10 | yes | yes | 6 | 6 | code | 1.00 | – | – |

