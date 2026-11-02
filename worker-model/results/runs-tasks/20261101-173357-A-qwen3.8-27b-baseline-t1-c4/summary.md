# Task-level run, arm A: today prompt, workers qwen3.8:27b, combine

2026-11-01T17:33:57-06:00 · combine model qwen3.8:27b · seam pass: none · Ollama 0.40.1 · Blender 5.2.2, 5.0.1

EVAL ONLY: model output for eval plans; never training data.

| tasks | Blender n | Blender pass 5.2.2 | 5.0.1 | both | Python n | Python pass | assertions | fallback | seams | cut off | runaway | steps runaway | steps kept the contract | steps in exact form | one script | reviewer done | median s | total s | tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 2 | 0% | 0% | 0% | 0 | – | 0% | – | – | 0% | 0% | 0% | 0% | 0% | 100% | – | 295.32 | 590.6 | 35578 |

Pass rates are over every task of the kind: Blender n is every plan with a Blender step, Python n every python-script plan without a files step. A result the check didn't run counts as a fail: unchecked {"blender": {}, "python": {}}. pass: Chimera's check passed with no Traceback or Error: line in its 1,500-character output tail, and the direct run of the same script has none in its whole output. runaway: the combine or a lone step hit the reply cap (6144 content tokens for a step, thinking not counted) or the runaway guard (16384 tokens, thinking included); steps runaway: steps the cap or the guard cut ("in thinking": the guard hit while the model was still thinking). steps kept the contract: Chimera can join the piece (the near-miss handoff forms included, since Oct 30); in exact form: no errors and the contract's exact written form, what data generation keeps. no_entry_point (unchecked): a joined Python script where no step defines main(), which Chimera's check would pass without running anything. cut off: Ollama itself stopped at a length limit. one script: of the Blender tasks, results holding exactly one Blender script.

How the result was made: {"combine": 2}; checks: {"checked": 2}.

## Tasks

| task | sample | steps (s, tokens, contract) | result by | 5.2.2 | 5.0.1 | assertions | seams | s | first problem |
|---|---|---|---|---|---|---|---|---|---|
| bw-08 | 0 | s1 83s 5630t x, s2 55s 3396t x, s3 70s 3880t x, s4 86s 4783t x | combine | failed | failed | 1 failed | 0 | 405.58 | 5.2.2: line 220: ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 3 items, not 4 |
| bl-01 | 0 | s1 37s 2626t x, s2 45s 3019t x, s3 33s 2172t x, s4 30s 1588t x | combine | failed | failed | – | 0 | 185.06 | 5.2.2: line 36: AttributeError: 'Object' object has no attribute 'visible_cycle'. Did you mean: 'visible_camera'? |
