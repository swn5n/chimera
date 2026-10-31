# qwen3:14b, contract prompt, on the worker eval (w1.0)

2026-10-30T01:32:43-05:00 · Ollama 0.40.1 · digest `bdbd181c33f2` · samples 1 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: a worker step's reply content is cut after 6144 tokens and scored as a runaway in content (the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap; every reply, thinking included, is cut after 16384 tokens (the runaway guard; a worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard).

| – | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 (checked) | crash 5.2.2 (all) | no script | assertions | API errors | repaired | expect | runaway | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 36 | 86% | 83% | 30 | 23% | 27% | 23% | 67% | 67% | 0% | 20% | 1.83 | 40% | 30% | 0% | 0% | 1884.0 | 58.55 | 38.0075 |
| w2 | 16 | 81% | 81% | 16 | 19% | 19% | 19% | 69% | 69% | 0% | 12% | 2.31 | – | – | 0% | 0% | 4435.0 | 57.85 | 77.75800000000001 |
| w3 | 10 | 100% | 100% | 10 | 40% | 50% | 40% | 60% | 60% | 0% | 40% | 0.9 | 40% | – | 0% | 0% | 1217.0 | 59.15 | 22.343 |
| w4f | 5 | 80% | 60% | 2 | 0% | 0% | 0% | 50% | 50% | 0% | 0% | 3.5 | – | 40% | 0% | 0% | 1186 | 59.4 | 20.084 |
| w4l | 5 | 80% | 80% | 2 | 0% | 0% | 0% | 100% | 100% | 0% | 0% | 1.0 | – | 20% | 0% | 0% | 2079 | 51.0 | 50.235 |
| blender | 30 | 90% | 87% | 30 | 23% | 27% | 23% | 67% | 67% | 0% | 20% | 1.83 | 40% | 50% | 0% | 0% | 2641.5 | 58.55 | 49.1435 |
| files | 2 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 1422.5 | 56.05 | 31.917 |
| python-script | 1 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 1186 | 60.6 | 20.084 |
| section | 3 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | 33% | 0% | 0% | 833 | 53.4 | 28.21 |

contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: line): what data generation keeps. Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run (no script: 0) and a runaway (0, of which 0 had no script) count as fails, not as left out. strict: not a runaway; Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows (tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same rule; the probes run there). crash: the check's outcome was failed (a definite crash); "checked" is over the 30 samples Blender checked (the plan's "definite crashes at most 10%"), "all" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a crash. no script: the reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 (no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has. runaway: the runner stopped reading the reply, in content (its content passed the reply cap of 6144 tokens, thinking not counted, or the guard hit while it wrote content) or in thinking (the runaway guard, 16384 tokens with thinking, hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and no think field and has neither limit. cut off: Ollama itself stopped at a length limit. The plan's cut-off bar counts both.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 1075 | 19.136 | 5.2.2: line 25: RuntimeError: Error: Node type ShaderNodeBsdfVolume undefined |
| w2-02 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 2425 | 42.173 | 5.2.2: line 27: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-04 | 0 | blender | ok | joined | unsure | unsure | FAIL | 3 | 5072 | 89.72 | 5.2.2: line 34: AttributeError: Calling operator "bpy.ops.mesh.select_face_by_radius" error, could not be found |
| w2-05 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 5217 | 92.339 | 5.2.2: line 33: ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 4 items, not 3 |
| w2-07 | 0 | blender | ok | joined | pass | pass | ok | 0 | 4554 | 80.153 | – |
| w2-08 | 0 | blender | ok | joined | unsure | unsure | FAIL | 2 | 785 | 13.847 | 5.2.2: line 18: TypeError: bpy_struct: item.attr = val: enum "EEVEE" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH', |
| w2-10 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 1957 | 33.842 | 5.2.2: line 16: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-12 | 0 | blender | ok | joined | failed | failed | FAIL | 5 | 6160 | 109.619 | 5.2.2: line 20: TypeError: BlendDataNodeTrees.new(): error with keyword argument "type" -  enum "GEOMETRY_NODE_GROUP" no |
| w2-13 | 0 | blender | ok | joined | failed | failed | FAIL | 8 | 7194 | 128.744 | 5.2.2: line 35: AttributeError: 'GeometryNodeTree' object has no attribute 'inputs' |
| w2-14 | 0 | blender | broken | alone | failed | failed | FAIL | 5 | 4316 | 75.363 | 5.2.2: line 25: TypeError: Converting py args to operator properties:: keyword "radius" unrecognized |
| w2-16 | 0 | blender | ok | joined | failed | failed | FAIL | 4 | 1632 | 28.163 | 5.2.2: line 17: AttributeError: 'ColorManagedDisplaySettings' object has no attribute 'view_transform' |
| w2-18 | 0 | blender | broken | alone | pass | pass | FAIL | 0 | 4704 | 82.418 | contract: uses_not_dependency |
| w2-19 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 5513 | 97.18 | 5.2.2: line 36: AttributeError: 'Action' object has no attribute 'fcurves' |
| w2-21 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 3480 | 60.408 | 5.2.2: line 45: AttributeError: 'Mesh' object attribute 'shade_smooth' is read-only |
| w2-25 | 0 | blender | ok | joined | pass | pass | ok | 0 | 1743 | 30.081 | – |
| w2-27 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 5669 | 100.037 | 5.2.2: line 65: TypeError: Scene.ray_cast(): error with argument 1, "depsgraph" -  Function.depsgraph expected a Depsgra |
| w3-01 | 0 | blender | ok | joined | pass | pass | ok | 0 | 1071 | 20.062 | – |
| w3-03 | 0 | blender | ok | joined | pass | pass | ok | 0 | 657 | 12.296 | – |
| w3-04 | 0 | blender | ok | joined | pass | pass | ok | 0 | 1451 | 26.367 | – |
| w3-06 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 3170 | 56.114 | 5.2.2: line 31: AttributeError: 'Mesh' object has no attribute 'auto_smooth_angle' |
| w3-09 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 1783 | 31.618 | 5.2.2: line 31: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w3-11 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 1129 | 20.666 | 5.2.2: line 21: AttributeError: 'tuple' object has no attribute 'new' |
| w3-12 | 0 | blender | ok | joined | pass | pass | ok | 0 | 1094 | 20.133 | – |
| w3-13 | 0 | blender | ok | joined | failed | failed | FAIL | 3 | 5087 | 91.642 | 5.2.2: line 26: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-14 | 0 | blender | ok | joined | failed | failed | FAIL | 3 | 674 | 12.433 | 5.2.2: line 19: AttributeError: 'SceneEEVEE' object has no attribute 'use_bloom' |
| w3-19 | 0 | blender | ok | joined | failed | pass | FAIL | 0 | 1305 | 24.02 | 5.2.2: line 38: TypeError: bpy_struct[key] = val: id properties not supported for this type |
| w4f-01 | 0 | blender | ok, near miss | joined | unsure | unsure | FAIL | 1 | 1811 | 31.446 | 5.2.2: line 53: AttributeError: 'NoneType' object has no attribute 'materials' |
| w4f-02 | 0 | blender | ok | joined | failed | failed | FAIL | 6 | 3496 | 60.958 | 5.2.2: line 22: TypeError: Converting py args to operator properties:: keyword "fill" unrecognized |
| w4f-05 | 0 | python-script | ok | – | – | – | – | – | 1186 | 20.084 | missed assumed_mentions, must_not_match |
| w4f-06 | 0 | files | broken | – | – | – | – | – | 766 | 13.599 | contract: no_file_line |
| w4f-08 | 0 | section | ok | – | – | – | – | – | 745 | 13.145 | – |
| w4l-02 | 0 | section | ok | – | – | – | – | – | 833 | 28.21 | missed needles |
| w4l-04 | 0 | blender | ok | after_deps | failed | failed | FAIL | 1 | 6969 | 150.243 | 5.2.2: line 336: AttributeError: 'Action' object has no attribute 'fcurves' |
| w4l-07 | 0 | files | broken | – | – | – | – | – | 2079 | 50.235 | contract: no_file_line |
| w4l-08 | 0 | blender | ok | after_deps | failed | failed | FAIL | 1 | 2858 | 70.568 | 5.2.2: line 140: AttributeError: 'RenderSettings' object has no attribute 'exposure' |
| w4l-10 | 0 | section | ok | – | – | – | – | – | 1106 | 42.568 | missed must_mention |
