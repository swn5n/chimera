# Task-level run, arm B: contract prompt, workers qwen3.8:27b, join

2026-11-01T19:11:23-06:00 · combine model qwen3.8:27b · seam pass: none · Ollama 0.40.1 · Blender 5.2.2, 5.0.1

EVAL ONLY: model output for eval plans; never training data.

| tasks | Blender n | Blender pass 5.2.2 | 5.0.1 | both | Python n | Python pass | assertions | fallback | seams | cut off | runaway | steps runaway | steps kept the contract | steps in exact form | one script | reviewer done | median s | total s | tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 12 | 12 | 0% | 0% | 0% | 0 | – | 0% | 50% | 2.17 | 0% | 0% | 2% (1 in thinking) | 83% | 81% | 100% | – | 369.615 | 4826.1 | 293505 |

Pass rates are over every task of the kind: Blender n is every plan with a Blender step, Python n every python-script plan without a files step. A result the check didn't run counts as a fail: unchecked {"blender": {}, "python": {}}. pass: Chimera's check passed with no Traceback or Error: line in its 1,500-character output tail, and the direct run of the same script has none in its whole output. runaway: the combine or a lone step hit the reply cap (6144 content tokens for a step, thinking not counted) or the runaway guard (16384 tokens, thinking included); steps runaway: steps the cap or the guard cut ("in thinking": the guard hit while the model was still thinking). steps kept the contract: Chimera can join the piece (the near-miss handoff forms included, since Oct 30); in exact form: no errors and the contract's exact written form, what data generation keeps. no_entry_point (unchecked): a joined Python script where no step defines main(), which Chimera's check would pass without running anything. cut off: Ollama itself stopped at a length limit. one script: of the Blender tasks, results holding exactly one Blender script.

How the result was made: {"fallback": 6, "joined": 6}; checks: {"checked": 12}.

## Tasks

| task | sample | steps (s, tokens, contract) | result by | 5.2.2 | 5.0.1 | assertions | seams | s | first problem |
|---|---|---|---|---|---|---|---|---|---|
| bw-01 | 0 | s1 39s 2335t ok, s2 120s 7709t ok, s3 57s 3200t ok, s4 93s 5440t ok, s5 50s 2977t ok, s6 87s 4837t ok, s7 79s 2749t ok | joined | failed | failed | 1 failed | 8 | 524.23 | 5.2.2: line 605: TypeError: BlendDataObjects.new(): required parameter "object_data" not specified |
| bw-02 | 0 | s1 31s 1877t x, s2 50s 2920t ok, s3 95s 5882t ok, s4 87s 4984t ok | fallback | failed | failed | 1 failed | 0 | 400.47 | 5.2.2: line 322: AttributeError: Vector subtraction: (tuple - Vector) invalid type for this operation |
| bw-03 | 0 | s1 242s 16644t ok | joined | failed | failed | 1 failed | 0 | 241.77 | 5.2.2: line 185: ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 3 items, not 4 |
| bw-04 | 0 | s1 66s 4770t ok, s2 119s 7738t ok, s3 66s 3992t ok, s4 69s 3967t ok | joined | failed | failed | 1 failed | 3 | 320.9 | 5.2.2: line 127: AttributeError: 'Object' object has no attribute 'rigid_body_type' |
| bw-05 | 0 | s1 270s 16384t x, s2 55s 3441t ok | fallback | failed | failed | 1 failed | 0 | 508.3 | runaway steps s1; 5.2.2: line 182: TypeError: bpy_struct[key] = val: id properties not supported for this type |
| bw-06 | 0 | s1 164s 11615t ok, s2 115s 7478t ok, s3 89s 5235t ok, s4 78s 4485t x, s5 62s 3537t x, s6 39s 1811t x | fallback | failed | failed | 1 failed | 0 | 713.6 | 5.2.2: line 483: TypeError: bpy_struct: item.attr = val: RenderSettings.fps expected an int type, not float |
| bw-07 | 0 | s1 26s 1527t ok, s2 60s 3669t ok, s3 60s 3661t ok, s4 87s 5011t x | fallback | failed | failed | 1 failed | 0 | 332.19 | 5.2.2: line 118: TypeError: BlendDataObjects.new(): required parameter "object_data" not specified |
| bw-08 | 0 | s1 102s 6766t ok, s2 63s 3713t ok, s3 131s 7569t ok, s4 92s 4720t ok | joined | failed | failed | 1 failed | 6 | 388.1 | 5.2.2: line 67: ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 4 items, not 5 |
| bw-09 | 0 | s1 79s 5246t ok, s2 260s 18005t ok, s3 47s 3237t ok, s4 103s 5344t ok | joined | failed | failed | 1 failed | 5 | 488.88 | 5.2.2: line 577: AttributeError: 'Scene' object has no attribute 'node_tree' |
| bw-10 | 0 | s1 24s 1334t ok, s2 61s 3712t ok, s3 47s 2802t ok, s4 41s 2347t near, s5 89s 4874t x | fallback | failed | failed | 1 failed | 0 | 351.13 | 5.2.2: line 292: TypeError: Scene.ray_cast(): error with argument 1, "depsgraph" -  Function.depsgraph expected a Depsgraph type, not Scene |
| bl-01 | 0 | s1 51s 3442t ok, s2 46s 2741t ok, s3 49s 2901t ok, s4 66s 3682t ok | joined | failed | failed | – | 4 | 212.49 | 5.2.2: line 372: AttributeError: 'ImageFormatSettings' object has no attribute 'premium' |
| bl-03 | 0 | s1 71s 4676t ok, s2 108s 7326t ok, s3 86s 5339t x | fallback | unsure | unsure | – | 0 | 344.0 | 5.2.2: line 145: KeyError: 'faces' |
