# qwen3.8:27b, contract prompt, on the worker eval (w1.0)

2026-10-30T04:08:21-05:00 · Ollama 0.40.1 · digest `47951e4a6661` · samples 1 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: a worker step's reply content is cut after 6144 tokens and scored as a runaway in content (the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap; every reply, thinking included, is cut after 16384 tokens (the runaway guard; a worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard).

| – | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 (checked) | crash 5.2.2 (all) | no script | assertions | API errors | repaired | expect | runaway | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 36 | 89% | 89% | 30 | 50% | 53% | 50% | 50% | 50% | 0% | 37% | 0.67 | 70% | 80% | 0% | 0% | 3544.5 | 71.75 | 52.582 |
| w2 | 16 | 94% | 94% | 16 | 44% | 50% | 44% | 56% | 56% | 0% | 25% | 0.88 | – | – | 0% | 0% | 3595.0 | 71.6 | 51.087 |
| w3 | 10 | 70% | 70% | 10 | 70% | 70% | 70% | 30% | 30% | 0% | 60% | 0.5 | 70% | – | 0% | 0% | 3099.5 | 72.15 | 45.658500000000004 |
| w4f | 5 | 100% | 100% | 2 | 0% | 0% | 0% | 100% | 100% | 0% | 0% | 0.0 | – | 100% | 0% | 0% | 2227 | 73.1 | 28.551 |
| w4l | 5 | 100% | 100% | 2 | 50% | 50% | 50% | 50% | 50% | 0% | 50% | 0.5 | – | 60% | 0% | 0% | 3782 | 66.7 | 93.634 |
| blender | 30 | 87% | 87% | 30 | 50% | 53% | 50% | 50% | 50% | 0% | 37% | 0.67 | 70% | 100% | 0% | 0% | 3595.0 | 71.75 | 52.582 |
| files | 2 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | 100% | 0% | 0% | 2278.5 | 72.5 | 42.5875 |
| python-script | 1 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | 100% | 0% | 0% | 2227 | 80.7 | 28.551 |
| section | 3 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | 33% | 0% | 0% | 2439 | 63.1 | 59.988 |

contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: line): what data generation keeps. Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run (no script: 0) and a runaway (0, of which 0 had no script) count as fails, not as left out. strict: not a runaway; Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows (tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same rule; the probes run there). crash: the check's outcome was failed (a definite crash); "checked" is over the 30 samples Blender checked (the plan's "definite crashes at most 10%"), "all" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a crash. no script: the reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 (no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has. runaway: the runner stopped reading the reply, in content (its content passed the reply cap of 6144 tokens, thinking not counted, or the guard hit while it wrote content) or in thinking (the runaway guard, 16384 tokens with thinking, hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and no think field and has neither limit. cut off: Ollama itself stopped at a length limit. The plan's cut-off bar counts both.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | blender | ok | joined | pass | pass | FAIL | 0 | 2873 | 40.671 | – |
| w2-02 | 0 | blender | broken | alone | pass | pass | FAIL | 0 | 3577 | 47.425 | contract: uses_not_dependency |
| w2-04 | 0 | blender | ok | joined | pass | pass | ok | 0 | 8625 | 125.669 | – |
| w2-05 | 0 | blender | ok | joined | pass | pass | FAIL | 0 | 3283 | 44.767 | – |
| w2-07 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 6453 | 93.416 | 5.2.2: line 69: AttributeError: 'BevelModifier' object has no attribute 'use_clamp' |
| w2-08 | 0 | blender | ok | joined | failed | failed | FAIL | 3 | 2779 | 37.965 | 5.2.2: line 28: AttributeError: 'SceneEEVEE' object has no attribute 'taa_viewport_samples'. Did you mean: 'taa_render_s |
| w2-10 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 2554 | 36.471 | 5.2.2: line 19: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-12 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 5260 | 77.112 | 5.2.2: line 5: ImportError: cannot import name 'FloatVector' from 'mathutils' (unknown location) |
| w2-13 | 0 | blender | ok | joined | failed | pass | FAIL | 0 | 4979 | 71.394 | 5.2.2: line 115: TypeError: bpy_struct[key] = val: id properties not supported for this type |
| w2-14 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 7393 | 108.431 | 5.2.2: line 60: TypeError: BlendDataNodeTrees.new(): error with argument 2, "type" -  enum "GeometryNodesTree" not found |
| w2-16 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 1936 | 29.167 | 5.2.2: line 34: TypeError: bpy_struct: item.attr = val: enum "NONE" not found in ('None', 'AgX - Punchy', 'AgX - Greysca |
| w2-18 | 0 | blender | ok | joined | pass | pass | ok | 1 | 3736 | 54.512 | – |
| w2-19 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 6338 | 89.77 | 5.2.2: line 84: AttributeError: 'Action' object has no attribute 'fcurves' |
| w2-21 | 0 | blender | ok | joined | pass | pass | ok | 0 | 3613 | 52.011 | – |
| w2-25 | 0 | blender | ok | joined | pass | pass | ok | 0 | 1196 | 16.956 | – |
| w2-27 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 3570 | 50.163 | 5.2.2: line 80: AttributeError: 'Scene' object has no attribute 'evaluated_depsgraph_get' |
| w3-01 | 0 | blender | broken | alone | pass | pass | ok | 0 | 1519 | 23.186 | contract: handoff_not_last |
| w3-03 | 0 | blender | ok | joined | pass | pass | ok | 0 | 2633 | 38.362 | – |
| w3-04 | 0 | blender | broken | alone | pass | pass | ok | 0 | 1452 | 22.811 | contract: handoff_not_last |
| w3-06 | 0 | blender | ok | joined | pass | pass | FAIL | 0 | 2699 | 40.141 | – |
| w3-09 | 0 | blender | ok | joined | pass | pass | ok | 0 | 2270 | 33.812 | – |
| w3-11 | 0 | blender | broken | alone | pass | pass | ok | 0 | 4017 | 62.335 | contract: handoff_not_last |
| w3-12 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 3519 | 53.153 | 5.2.2: line 72: TypeError: Scene.ray_cast(): required parameter "depsgraph" not specified |
| w3-13 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 10115 | 144.306 | 5.2.2: line 49: TypeError: ObjectModifiers.new(): error with keyword argument "type" -  enum "SMOOTH_BY_ANGLE" not found |
| w3-14 | 0 | blender | ok | joined | failed | failed | FAIL | 5 | 3500 | 51.176 | 5.2.2: line 47: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w3-19 | 0 | blender | ok | joined | pass | pass | ok | 0 | 6246 | 92.398 | – |
| w4f-01 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 3891 | 55.348 | 5.2.2: line 56: NameError: name 'mathutils' is not defined |
| w4f-02 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 4459 | 61.219 | 5.2.2: line 111: AttributeError: 'Scene' object has no attribute 'view_layer'. Did you mean: 'view_layers'? |
| w4f-05 | 0 | python-script | ok | – | – | – | – | – | 2227 | 28.551 | – |
| w4f-06 | 0 | files | ok | – | – | – | – | – | 1126 | 16.634 | – |
| w4f-08 | 0 | section | ok | – | – | – | – | – | 1011 | 17.729 | – |
| w4l-02 | 0 | section | ok | – | – | – | – | – | 2439 | 59.988 | missed needles |
| w4l-04 | 0 | blender | ok | after_deps | failed | failed | FAIL | 1 | 10930 | 185.257 | 5.2.2: line 364: AttributeError: 'Action' object has no attribute 'fcurves' |
| w4l-07 | 0 | files | ok | – | – | – | – | – | 3431 | 68.541 | – |
| w4l-08 | 0 | blender | ok | after_deps | pass | pass | ok | 0 | 4536 | 93.992 | – |
| w4l-10 | 0 | section | ok | – | – | – | – | – | 3782 | 93.634 | missed must_mention |
