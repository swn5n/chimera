# Task-level run, arm B: contract prompt, workers qwen3:8b, join

2026-10-29T23:08:24-05:00 · combine model qwen3.8:27b · seam pass: none · Ollama 0.40.1 · Blender 5.2.2, 5.0.1

EVAL ONLY: model output for eval plans; never training data.

| tasks | Blender pass 5.2.2 | 5.0.1 | both | Python pass | assertions | fallback | seams | cut off | steps kept the contract | one script | reviewer done | median s | total s | tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0% | 0% | 0% | – | – | 100% | 0.0 | 0% | 0% | 100% | – | 231.17 | 231.2 | 18084 |

How the result was made: {"fallback": 1}; checks: {"checked": 1}.

## Tasks

| task | sample | steps (s, tokens, contract) | result by | 5.2.2 | 5.0.1 | assertions | seams | s | first problem |
|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | s1 12s 1067t x, s2 50s 4503t x, s3 27s 2451t x | fallback | failed | failed | – | 0 | 231.17 | 5.2.2: line 119: AttributeError: 'Mesh' object has no attribute 'use_auto_smooth' |
