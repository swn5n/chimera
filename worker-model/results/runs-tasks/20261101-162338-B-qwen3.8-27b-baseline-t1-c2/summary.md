# Task-level run, arm B: contract prompt, workers qwen3.8:27b, join

2026-11-01T16:23:38-06:00 · combine model qwen3.8:27b · seam pass: none · Ollama 0.40.1 · Blender 5.2.2, 5.0.1

EVAL ONLY: model output for eval plans; never training data.

| tasks | Blender n | Blender pass 5.2.2 | 5.0.1 | both | Python n | Python pass | assertions | fallback | seams | cut off | runaway | steps runaway | steps kept the contract | steps in exact form | one script | reviewer done | median s | total s | tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 4 | 4 | 0% | 0% | 0% | 0 | – | 0% | 50% | 0.0 | 0% | 0% | 0% | 73% | 73% | 100% | – | 319.405 | 1387.8 | 87718 |

Pass rates are over every task of the kind: Blender n is every plan with a Blender step, Python n every python-script plan without a files step. A result the check didn't run counts as a fail: unchecked {"blender": {}, "python": {}}. pass: Chimera's check passed with no Traceback or Error: line in its 1,500-character output tail, and the direct run of the same script has none in its whole output. runaway: the combine or a lone step hit the reply cap (6144 content tokens for a step, thinking not counted) or the runaway guard (16384 tokens, thinking included); steps runaway: steps the cap or the guard cut ("in thinking": the guard hit while the model was still thinking). steps kept the contract: Chimera can join the piece (the near-miss handoff forms included, since Oct 30); in exact form: no errors and the contract's exact written form, what data generation keeps. no_entry_point (unchecked): a joined Python script where no step defines main(), which Chimera's check would pass without running anything. cut off: Ollama itself stopped at a length limit. one script: of the Blender tasks, results holding exactly one Blender script.

How the result was made: {"fallback": 2, "joined": 2}; checks: {"checked": 4}.

## Tasks

| task | sample | steps (s, tokens, contract) | result by | 5.2.2 | 5.0.1 | assertions | seams | s | first problem |
|---|---|---|---|---|---|---|---|---|---|
| bw-04 | 0 | s1 44s 3028t ok, s2 187s 12569t ok, s3 61s 3790t x, s4 77s 4081t ok | fallback | failed | failed | 1 failed | 0 | 465.62 | 5.2.2: line 181: AttributeError: 'Action' object has no attribute 'fcurves' |
| bw-05 | 0 | s1 227s 16096t ok, s2 56s 3170t ok | joined | failed | failed | 1 failed | 0 | 283.41 | 5.2.2: line 118: RuntimeError: Error: Node type GeometryNodeInputRandomValue undefined |
| bw-09 | 0 | s1 69s 4757t ok, s2 54s 3662t ok, s3 66s 4449t ok, s4 108s 5830t ok | joined | unsure | unsure | 1 failed | 0 | 296.92 | 5.2.2: line 167: ValueError: expected a 4x4 matrix |
| bw-10 | 0 | s1 30s 1891t ok, s2 57s 3547t x, s3 30s 1864t ok, s4 47s 2998t x, s5 105s 6304t x | fallback | failed | failed | 1 failed | 0 | 341.89 | 5.2.2: line 163: KeyError: 'bpy_prop_collection[key]: key "Color1" not found' |
