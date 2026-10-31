# gemma4:12b-it-q4_K_M, contract prompt, on the worker eval (w1.0)

2026-10-30T02:50:30-05:00 · Ollama 0.40.1 · digest `6114515d63c1` · samples 1 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: a worker step's reply content is cut after 6144 tokens and scored as a runaway in content (the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap; every reply, thinking included, is cut after 16384 tokens (the runaway guard; a worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard).

| – | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 (checked) | crash 5.2.2 (all) | no script | assertions | API errors | repaired | expect | runaway | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 36 | 86% | 83% | 30 | 27% | 27% | 27% | 68% | 57% | 17% | 23% | 2.59 | 50% | 60% | 0% | 14% | 4998.5 | 60.650000000000006 | 85.5155 |
| w2 | 16 | 88% | 88% | 16 | 19% | 19% | 19% | 79% | 69% | 12% | 19% | 4.21 | – | – | 0% | 12% | 4820.0 | 61.05 | 84.277 |
| w3 | 10 | 80% | 80% | 10 | 50% | 50% | 50% | 38% | 30% | 20% | 40% | 1.0 | 50% | – | 0% | 20% | 5306.5 | 60.85 | 88.4515 |
| w4f | 5 | 80% | 80% | 2 | 0% | 0% | 0% | 100% | 50% | 50% | 0% | 0.5 | – | 80% | 0% | 20% | 3425 | 62.1 | 52.19 |
| w4l | 5 | 100% | 80% | 2 | 0% | 0% | 0% | 100% | 100% | 0% | 0% | 0.5 | – | 40% | 0% | 0% | 5299 | 55.9 | 102.395 |
| blender | 30 | 83% | 80% | 30 | 27% | 27% | 27% | 68% | 57% | 17% | 23% | 2.59 | 50% | 75% | 0% | 17% | 5350.5 | 60.650000000000006 | 94.01849999999999 |
| files | 2 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | 50% | 0% | 0% | 3878.0 | 62.0 | 69.188 |
| python-script | 1 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | 100% | 0% | 0% | 3425 | 66.5 | 52.19 |
| section | 3 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | 33% | 0% | 0% | 1689 | 55.9 | 41.036 |

contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: line): what data generation keeps. Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run (no script: 5) and a runaway (0, of which 0 had no script) count as fails, not as left out. strict: not a runaway; Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows (tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same rule; the probes run there). crash: the check's outcome was failed (a definite crash); "checked" is over the 25 samples Blender checked (the plan's "definite crashes at most 10%"), "all" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a crash. no script: the reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 (no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has. runaway: the runner stopped reading the reply, in content (its content passed the reply cap of 6144 tokens, thinking not counted, or the guard hit while it wrote content) or in thinking (the runaway guard, 16384 tokens with thinking, hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and no think field and has neither limit. cut off: Ollama itself stopped at a length limit. The plan's cut-off bar counts both.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | blender | ok | joined | failed | failed | FAIL | 5 | 2388 | 38.372 | 5.2.2: line 25: RuntimeError: Error: Node type ShaderNode_Input_Surface undefined |
| w2-02 | 0 | blender | broken | none | – | – | – | – | 7430 | 122.086 | no script: not joined: s2: empty: the reply is empty; the reply has no Blender script |
| w2-04 | 0 | blender | ok | joined | failed | failed | FAIL | 9 | 6824 | 120.09 | 5.2.2: line 25: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-05 | 0 | blender | ok | joined | failed | failed | FAIL | 4 | 7032 | 114.013 | 5.2.2: line 28: RuntimeError: Error: Node type ShaderNode_Output_Material undefined |
| w2-07 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 6415 | 100.824 | 5.2.2: line 72: AttributeError: 'Mesh' object has no attribute 'from_py_data'. Did you mean: 'from_pydata'? |
| w2-08 | 0 | blender | ok | joined | pass | pass | ok | 1 | 1964 | 34.547 | – |
| w2-10 | 0 | blender | ok | joined | failed | failed | FAIL | 7 | 6834 | 111.047 | 5.2.2: line 24: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-12 | 0 | blender | broken | none | – | – | – | – | 7435 | 128.161 | no script: not joined: s1: empty: the reply is empty; the reply has no Blender script |
| w2-13 | 0 | blender | ok | joined | failed | failed | FAIL | 8 | 5723 | 98.668 | 5.2.2: line 23: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-14 | 0 | blender | ok | joined | failed | failed | FAIL | 10 | 2966 | 50.325 | 5.2.2: line 27: TypeError: BlendDataObjects.new(): error with argument 2, "object_data" -  Function.object_data expected |
| w2-16 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 2440 | 38.812 | 5.2.2: line 16: AttributeError: 'RenderSettings' object has no attribute 'color_management' |
| w2-18 | 0 | blender | ok | joined | pass | pass | ok | 0 | 2094 | 35.226 | – |
| w2-19 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 6364 | 105.227 | 5.2.2: line 34: AttributeError: 'BlendData' object has no attribute 'animation_data' |
| w2-21 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 3039 | 53.919 | 5.2.2: line 54: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-25 | 0 | blender | ok | joined | pass | pass | ok | 0 | 3901 | 61.969 | – |
| w2-27 | 0 | blender | ok | joined | failed | failed | FAIL | 9 | 3917 | 69.886 | 5.2.2: line 24: AttributeError: bpy_prop_collection: attribute "append" not found |
| w3-01 | 0 | blender | ok | joined | pass | pass | ok | 0 | 3848 | 63.646 | – |
| w3-03 | 0 | blender | ok | joined | pass | pass | ok | 0 | 5211 | 86.782 | – |
| w3-04 | 0 | blender | ok | joined | pass | pass | ok | 0 | 3370 | 55.98 | – |
| w3-06 | 0 | blender | ok | joined | pass | pass | FAIL | 0 | 4287 | 72.98 | – |
| w3-09 | 0 | blender | ok | joined | pass | pass | ok | 1 | 5801 | 97.916 | – |
| w3-11 | 0 | blender | broken | none | – | – | – | 2 | 6674 | 111.835 | no script: not joined: s1: handoff_missing: no ```handoff block at the end; s1: unclosed_block: the python block is neve |
| w3-12 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 5510 | 90.121 | 5.2.2: line 54: TypeError: Scene.ray_cast(): error with argument 1, "depsgraph" -  Function.depsgraph expected a Depsgra |
| w3-13 | 0 | blender | broken | none | – | – | – | – | 6559 | 120.248 | no script: not joined: s1: empty: the reply is empty; the reply has no Blender script |
| w3-14 | 0 | blender | ok | joined | failed | failed | FAIL | 3 | 3203 | 53.259 | 5.2.2: line 32: AttributeError: 'SceneEEVEE' object has no attribute 'use_bloom' |
| w3-19 | 0 | blender | ok | joined | failed | failed | FAIL | 3 | 5402 | 98.106 | 5.2.2: line 33: RuntimeError: Error: Node type GeometryNodeGroupInput undefined |
| w4f-01 | 0 | blender | broken | none | – | – | – | 1 | 7411 | 123.048 | no script: not joined: s3: handoff_missing: no ```handoff block at the end; s3: unclosed_block: the python block is neve |
| w4f-02 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 4786 | 84.249 | 5.2.2: line 29: TypeError: 'int' object is not iterable |
| w4f-05 | 0 | python-script | ok | – | – | – | – | – | 3425 | 52.19 | – |
| w4f-06 | 0 | files | ok | – | – | – | – | – | 2287 | 35.981 | – |
| w4f-08 | 0 | section | ok | – | – | – | – | – | 1680 | 27.676 | – |
| w4l-02 | 0 | section | ok | – | – | – | – | – | 1689 | 41.036 | missed uses_mentions |
| w4l-04 | 0 | blender | ok | after_deps | failed | failed | FAIL | 0 | 5449 | 107.716 | 5.2.2: line 347: AttributeError: 'Action' object has no attribute 'fcurves' |
| w4l-07 | 0 | files | ok | – | – | – | – | – | 5469 | 102.395 | missed uses_mentions |
| w4l-08 | 0 | blender | ok, near miss | after_deps | failed | failed | FAIL | 1 | 5299 | 108.478 | 5.2.2: line 147: SyntaxError: positional argument follows keyword argument |
| w4l-10 | 0 | section | ok | – | – | – | – | – | 1782 | 50.209 | missed must_mention |
