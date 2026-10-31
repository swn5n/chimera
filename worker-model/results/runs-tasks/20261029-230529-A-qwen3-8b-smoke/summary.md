# Task-level run, arm A: today prompt, workers qwen3:8b, combine

2026-10-29T23:05:29-05:00 · combine model qwen3.8:27b · seam pass: none · Ollama 0.40.1 · Blender 5.2.2, 5.0.1

EVAL ONLY: model output for eval plans; never training data.

| tasks | Blender pass 5.2.2 | 5.0.1 | both | Python pass | assertions | fallback | seams | cut off | steps kept the contract | one script | reviewer done | median s | total s | tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0% | 0% | 0% | – | – | – | – | 0% | 0% | 100% | – | 173.74 | 173.7 | 14222 |

How the result was made: {"combine": 1}; checks: {"checked": 1}.

## Tasks

| task | sample | steps (s, tokens, contract) | result by | 5.2.2 | 5.0.1 | assertions | seams | s | first problem |
|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | s1 21s 1762t x, s2 50s 4622t x, s3 42s 3894t x | combine | failed | failed | – | 0 | 173.74 | 5.2.2: line 110: TypeError: 'float' object cannot be interpreted as an integer |
