# Task-level run, arm B: contract prompt, workers qwen3.8:27b, join

2026-11-01T17:43:57-06:00 · combine model qwen3.8:27b · seam pass: none · Ollama 0.40.1 · Blender 5.2.2, 5.0.1

EVAL ONLY: model output for eval plans; never training data.

| tasks | Blender n | Blender pass 5.2.2 | 5.0.1 | both | Python n | Python pass | assertions | fallback | seams | cut off | runaway | steps runaway | steps kept the contract | steps in exact form | one script | reviewer done | median s | total s | tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 2 | 50% | 50% | 50% | 0 | – | 0% | 0% | 3.0 | 0% | 0% | 0% | 100% | 100% | 100% | – | 291.425 | 582.9 | 37791 |

Pass rates are over every task of the kind: Blender n is every plan with a Blender step, Python n every python-script plan without a files step. A result the check didn't run counts as a fail: unchecked {"blender": {}, "python": {}}. pass: Chimera's check passed with no Traceback or Error: line in its 1,500-character output tail, and the direct run of the same script has none in its whole output. runaway: the combine or a lone step hit the reply cap (6144 content tokens for a step, thinking not counted) or the runaway guard (16384 tokens, thinking included); steps runaway: steps the cap or the guard cut ("in thinking": the guard hit while the model was still thinking). steps kept the contract: Chimera can join the piece (the near-miss handoff forms included, since Oct 30); in exact form: no errors and the contract's exact written form, what data generation keeps. no_entry_point (unchecked): a joined Python script where no step defines main(), which Chimera's check would pass without running anything. cut off: Ollama itself stopped at a length limit. one script: of the Blender tasks, results holding exactly one Blender script.

How the result was made: {"joined": 2}; checks: {"checked": 2}.

## Tasks

| task | sample | steps (s, tokens, contract) | result by | 5.2.2 | 5.0.1 | assertions | seams | s | first problem |
|---|---|---|---|---|---|---|---|---|---|
| bw-08 | 0 | s1 118s 8352t ok, s2 49s 3218t ok, s3 142s 9254t ok, s4 94s 5694t ok | joined | failed | failed | 1 failed | 4 | 403.52 | 5.2.2: line 271: AttributeError: 'AreaLight' object has no attribute 'size_x'. Did you mean: 'size_y'? |
| bl-01 | 0 | s1 47s 3292t ok, s2 31s 1854t ok, s3 43s 2681t ok, s4 58s 3446t ok | joined | pass | pass | – | 2 | 179.33 | – |
