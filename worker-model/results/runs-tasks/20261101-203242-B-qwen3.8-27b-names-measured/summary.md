# Task-level run, arm B: contract prompt, workers qwen3.8:27b, join

2026-11-01T20:32:42-06:00 · combine model qwen3.8:27b · seam pass: none · Ollama 0.40.1 · Blender 5.2.2, 5.0.1

EVAL ONLY: model output for eval plans; never training data.

| tasks | Blender n | Blender pass 5.2.2 | 5.0.1 | both | Python n | Python pass | assertions | fallback | seams | cut off | runaway | steps runaway | steps kept the contract | steps in exact form | one script | reviewer done | median s | total s | tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 12 | 12 | 8% | 8% | 8% | 0 | – | 10% | 50% | 1.42 | 0% | 0% | 2% (0 in thinking) | 83% | 83% | 92% | – | 397.255 | 5388.7 | 326599 |

Pass rates are over every task of the kind: Blender n is every plan with a Blender step, Python n every python-script plan without a files step. A result the check didn't run counts as a fail: unchecked {"blender": {"skipped": 1}, "python": {}}. pass: Chimera's check passed with no Traceback or Error: line in its 1,500-character output tail, and the direct run of the same script has none in its whole output. runaway: the combine or a lone step hit the reply cap (6144 content tokens for a step, thinking not counted) or the runaway guard (16384 tokens, thinking included); steps runaway: steps the cap or the guard cut ("in thinking": the guard hit while the model was still thinking). steps kept the contract: Chimera can join the piece (the near-miss handoff forms included, since Oct 30); in exact form: no errors and the contract's exact written form, what data generation keeps. no_entry_point (unchecked): a joined Python script where no step defines main(), which Chimera's check would pass without running anything. cut off: Ollama itself stopped at a length limit. one script: of the Blender tasks, results holding exactly one Blender script.

How the result was made: {"fallback": 6, "joined": 6}; checks: {"checked": 11, "skipped": 1}.

## Tasks

| task | sample | steps (s, tokens, contract) | result by | 5.2.2 | 5.0.1 | assertions | seams | s | first problem |
|---|---|---|---|---|---|---|---|---|---|
| bw-01 | 0 | s1 22s 1125t ok, s2 72s 4580t ok, s3 45s 2565t ok, s4 76s 4445t ok, s5 46s 2898t ok, s6 85s 5063t ok, s7 81s 3310t ok | joined | failed | failed | 1 failed | 5 | 430.96 | 5.2.2: line 78: AttributeError: module 'bpy' has no attribute 'matrix' |
| bw-02 | 0 | s1 36s 2189t ok, s2 112s 7559t ok, s3 89s 5417t ok, s4 153s 9409t ok | joined | pass | pass | ok | 6 | 391.29 | – |
| bw-03 | 0 | s1 117s 8004t ok | joined | failed | failed | 1 failed | 0 | 117.64 | 5.2.2: line 62: AttributeError: bpy_prop_collection: attribute "unlink" not found |
| bw-04 | 0 | s1 85s 6025t ok, s2 269s 17926t ok, s3 144s 9504t x, s4 181s 10691t ok | fallback | failed | failed | 1 failed | 0 | 783.71 | 5.2.2: line 187: AttributeError: 'Action' object has no attribute 'fcurves' |
| bw-05 | 0 | s1 235s 16149t ok, s2 73s 4400t ok | joined | failed | failed | 1 failed | 0 | 308.76 | 5.2.2: line 52: RuntimeError: Error: Node type GeometryNodeGroupInput undefined |
| bw-06 | 0 | s1 116s 7910t ok, s2 78s 4953t ok, s3 114s 6741t ok, s4 91s 5536t x, s5 79s 4358t x, s6 65s 3545t x | fallback | failed | failed | 1 failed | 0 | 744.27 | 5.2.2: line 383: ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 3 items, not 4 |
| bw-07 | 0 | s1 25s 1393t ok, s2 62s 3835t ok, s3 86s 5350t ok, s4 61s 3367t x | fallback | – | – | – | 0 | 335.58 | fallback: s4: uses_not_dependency: uses names s1, which s4 doesn't depend on (it depends on s2, s3) |
| bw-08 | 0 | s1 127s 8579t ok, s2 96s 6103t ok, s3 113s 6474t ok, s4 115s 6430t ok | joined | failed | failed | 1 failed | 3 | 453.89 | 5.2.2: line 397: TypeError: bpy_struct: item.attr = val: RenderSettings.fps expected an int type, not float |
| bw-09 | 0 | s1 116s 7927t ok, s2 269s 16384t x, s3 165s 10350t ok, s4 91s 4942t ok | fallback | failed | failed | 1 failed | 0 | 787.73 | runaway steps s2; 5.2.2: line 113: TypeError: bpy_struct: item.attr = val: enum "SHADER" not found in ('FLOAT', 'VECTOR', 'RGBA') |
| bw-10 | 0 | s1 30s 1755t ok, s2 63s 3909t ok, s3 37s 2239t ok, s4 58s 3653t ok, s5 101s 5816t x | fallback | failed | failed | 1 failed | 0 | 381.35 | 5.2.2: line 234: TypeError: Scene.ray_cast(): error with argument 1, "depsgraph" -  Function.depsgraph expected a Depsgraph type, not Vector |
| bl-01 | 0 | s1 78s 4910t ok, s2 45s 2607t ok, s3 59s 3431t ok, s4 65s 3294t ok | joined | failed | failed | – | 3 | 250.34 | 5.2.2: line 44: TypeError: bpy_prop_collection.__contains__: expected a string or a tuple of strings |
| bl-03 | 0 | s1 58s 3386t ok, s2 112s 6992t ok, s3 148s 8514t x | fallback | failed | failed | – | 0 | 403.22 | 5.2.2: line 219: AttributeError: 'Object' object has no attribute 'visible_render'. Did you mean: 'visible_camera'? |
