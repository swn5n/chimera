# Task-level run, arm A: today prompt, workers qwen3.8:27b, combine

2026-11-01T16:47:03-06:00 · combine model qwen3.8:27b · seam pass: none · Ollama 0.40.1 · Blender 5.2.2, 5.0.1

EVAL ONLY: model output for eval plans; never training data.

| tasks | Blender n | Blender pass 5.2.2 | 5.0.1 | both | Python n | Python pass | assertions | fallback | seams | cut off | runaway | steps runaway | steps kept the contract | steps in exact form | one script | reviewer done | median s | total s | tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 4 | 4 | 25% | 25% | 25% | 0 | – | 0% | – | – | 0% | 0% | 0% | 0% | 0% | 100% | – | 264.71500000000003 | 1259.5 | 78833 |

Pass rates are over every task of the kind: Blender n is every plan with a Blender step, Python n every python-script plan without a files step. A result the check didn't run counts as a fail: unchecked {"blender": {}, "python": {}}. pass: Chimera's check passed with no Traceback or Error: line in its 1,500-character output tail, and the direct run of the same script has none in its whole output. runaway: the combine or a lone step hit the reply cap (6144 content tokens for a step, thinking not counted) or the runaway guard (16384 tokens, thinking included); steps runaway: steps the cap or the guard cut ("in thinking": the guard hit while the model was still thinking). steps kept the contract: Chimera can join the piece (the near-miss handoff forms included, since Oct 30); in exact form: no errors and the contract's exact written form, what data generation keeps. no_entry_point (unchecked): a joined Python script where no step defines main(), which Chimera's check would pass without running anything. cut off: Ollama itself stopped at a length limit. one script: of the Blender tasks, results holding exactly one Blender script.

How the result was made: {"combine": 4}; checks: {"checked": 4}.

## Tasks

| task | sample | steps (s, tokens, contract) | result by | 5.2.2 | 5.0.1 | assertions | seams | s | first problem |
|---|---|---|---|---|---|---|---|---|---|
| bw-02 | 0 | s1 15s 1054t x, s2 52s 3658t x, s3 85s 5727t x, s4 74s 4718t x | combine | pass | pass | 1 failed | 0 | 296.79 | – |
| bw-06 | 0 | s1 53s 3672t x, s2 71s 4696t x, s3 72s 4441t x, s4 78s 5166t x, s5 46s 2700t x, s6 36s 2169t x | combine | failed | failed | 1 failed | 0 | 514.43 | 5.2.2: line 273: ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 3 items, not 4 |
| bw-07 | 0 | s1 13s 817t x, s2 53s 3450t x, s3 51s 3302t x, s4 49s 2850t x | combine | failed | failed | 1 failed | 0 | 232.64 | 5.2.2: line 80: AttributeError: 'Curve' object has no attribute 'use_even_segments' |
| bl-03 | 0 | s1 44s 2989t x, s2 53s 3441t x, s3 55s 3301t x | combine | failed | failed | – | 0 | 215.69 | 5.2.2: line 40: AttributeError: 'CloudsTexture' object has no attribute 'turbulence' |
