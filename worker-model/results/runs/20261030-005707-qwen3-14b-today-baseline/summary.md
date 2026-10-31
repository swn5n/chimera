# qwen3:14b, today prompt, on the worker eval (w1.0)

2026-10-30T00:57:07-05:00 · Ollama 0.40.1 · digest `bdbd181c33f2` · samples 1 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: repair cases (W3) under today's prompt get the contract's repair part appended (Chimera 0.7.0 has no step repair); a worker step's reply content is cut after 6144 tokens and scored as a runaway in content (the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap; every reply, thinking included, is cut after 16384 tokens (the runaway guard; a worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard).

| – | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 (checked) | crash 5.2.2 (all) | no script | assertions | API errors | repaired | expect | runaway | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 36 | 25% | 25% | 30 | 30% | 30% | 30% | 63% | 63% | 0% | 30% | 1.9 | 60% | 10% | 0% | 0% | 2781.0 | 58.7 | 47.9045 |
| w2 | 16 | 0% | 0% | 16 | 12% | 12% | 12% | 75% | 75% | 0% | 12% | 2.81 | – | – | 0% | 0% | 3719.5 | 58.85 | 63.8575 |
| w3 | 10 | 90% | 90% | 10 | 60% | 60% | 60% | 40% | 40% | 0% | 60% | 1.0 | 60% | – | 0% | 0% | 2354.0 | 58.95 | 41.11150000000001 |
| w4f | 5 | 0% | 0% | 2 | 0% | 0% | 0% | 100% | 100% | 0% | 0% | 0.5 | – | 0% | 0% | 0% | 899 | 60.3 | 15.262 |
| w4l | 5 | 0% | 0% | 2 | 50% | 50% | 50% | 50% | 50% | 0% | 50% | 0.5 | – | 20% | 0% | 0% | 3335 | 52.8 | 69.523 |
| blender | 30 | 30% | 30% | 30 | 30% | 30% | 30% | 63% | 63% | 0% | 30% | 1.9 | 60% | 25% | 0% | 0% | 3099.0 | 58.7 | 53.647999999999996 |
| files | 2 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 1931.0 | 57.400000000000006 | 39.265499999999996 |
| python-script | 1 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 899 | 60.3 | 15.262 |
| section | 3 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 1058 | 54.3 | 30.831 |

contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: line): what data generation keeps. Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run (no script: 0) and a runaway (0, of which 0 had no script) count as fails, not as left out. strict: not a runaway; Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows (tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same rule; the probes run there). crash: the check's outcome was failed (a definite crash); "checked" is over the 30 samples Blender checked (the plan's "definite crashes at most 10%"), "all" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a crash. no script: the reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 (no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has. runaway: the runner stopped reading the reply, in content (its content passed the reply cap of 6144 tokens, thinking not counted, or the guard hit while it wrote content) or in thinking (the runaway guard, 16384 tokens with thinking, hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and no think field and has neither limit. cut off: Ollama itself stopped at a length limit. The plan's cut-off bar counts both.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 2114 | 35.532 | 5.2.2: line 10: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w2-02 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 2114 | 35.305 | 5.2.2: line 11: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-04 | 0 | blender | broken | alone | unsure | unsure | FAIL | 3 | 6389 | 109.48 | 5.2.2: line 16: AttributeError: 'NoneType' object has no attribute 'co' and no __dict__ for setting new attributes |
| w2-05 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 1450 | 24.179 | 5.2.2: line 39: KeyError: 'bpy_prop_collection[key]: key "Height" not found' |
| w2-07 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 7213 | 126.236 | 5.2.2: line 24: AttributeError: 'BevelModifier' object has no attribute 'depth' |
| w2-08 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 1384 | 23.457 | 5.2.2: line 5: AttributeError: 'RenderSettings' object has no attribute 'samples' |
| w2-10 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 5453 | 94.687 | 5.2.2: line 6: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-12 | 0 | blender | broken | alone | failed | failed | FAIL | 8 | 7875 | 139.967 | 5.2.2: line 11: TypeError: BlendDataNodeTrees.new(): error with keyword argument "type" -  enum "GEOMETRY_NODES" not fou |
| w2-13 | 0 | blender | broken | alone | unsure | unsure | FAIL | 10 | 6132 | 107.561 | 5.2.2: line 9: AttributeError: Calling operator "bpy.ops.mesh.icosphere_add" error, could not be found |
| w2-14 | 0 | blender | broken | alone | failed | failed | FAIL | 8 | 4799 | 83.19 | 5.2.2: line 5: TypeError: Converting py args to operator properties:: keyword "x_segments" unrecognized |
| w2-16 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 1793 | 30.38 | 5.2.2: line 5: AttributeError: 'RenderSettings' object has no attribute 'color_management' |
| w2-18 | 0 | blender | broken | alone | pass | pass | ok | 0 | 6183 | 108.067 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-19 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 2879 | 49.155 | 5.2.2: line 20: AttributeError: 'Action' object has no attribute 'fcurves' |
| w2-21 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 896 | 15.255 | 5.2.2: line 32: NameError: name 'cos' is not defined |
| w2-25 | 0 | blender | broken | alone | pass | pass | ok | 0 | 2025 | 34.365 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-27 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 4560 | 78.56 | 5.2.2: line 8: TypeError: Converting py args to operator properties:: keyword "subdivisions" unrecognized |
| w3-01 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 1289 | 22.802 | 5.2.2: line 27: AttributeError: 'BevelModifier' object has no attribute 'offset_value'. Did you mean: 'offset_type'? |
| w3-03 | 0 | blender | ok | joined | pass | pass | ok | 0 | 1583 | 27.299 | – |
| w3-04 | 0 | blender | ok | joined | pass | pass | ok | 0 | 2966 | 51.36 | – |
| w3-06 | 0 | blender | ok | joined | pass | pass | ok | 0 | 3400 | 59.122 | – |
| w3-09 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 3232 | 55.936 | 5.2.2: line 19: AttributeError: 'ShaderNodeBsdfPrincipled' object has no attribute 'use_transmission' |
| w3-11 | 0 | blender | ok | joined | pass | pass | ok | 0 | 1095 | 19.469 | – |
| w3-12 | 0 | blender | broken | after_deps | pass | pass | ok | 1 | 2683 | 46.654 | contract: handoff_missing |
| w3-13 | 0 | blender | ok | joined | failed | failed | FAIL | 3 | 2025 | 35.569 | 5.2.2: line 22: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-14 | 0 | blender | ok | joined | failed | failed | FAIL | 3 | 787 | 13.829 | 5.2.2: line 18: AttributeError: 'SceneEEVEE' object has no attribute 'use_bloom' |
| w3-19 | 0 | blender | ok | joined | pass | pass | ok | 0 | 5724 | 101.187 | – |
| w4f-01 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 4394 | 75.483 | 5.2.2: line 27: AttributeError: 'CameraDOFSettings' object has no attribute 'aperture_f_number' |
| w4f-02 | 0 | blender | broken | alone | failed | failed | FAIL | 0 | 4170 | 71.524 | 5.2.2: line 10: AttributeError: 'CollisionSettings' object has no attribute 'shape' |
| w4f-05 | 0 | python-script | broken | – | – | – | – | – | 899 | 15.262 | contract: handoff_missing |
| w4f-06 | 0 | files | broken | – | – | – | – | – | 527 | 9.008 | contract: handoff_missing, no_file_line |
| w4f-08 | 0 | section | broken | – | – | – | – | – | 695 | 11.787 | contract: handoff_missing, no_heading |
| w4l-02 | 0 | section | broken | – | – | – | – | – | 1058 | 30.831 | contract: handoff_missing, no_heading |
| w4l-04 | 0 | blender | broken | after_deps | failed | failed | FAIL | 1 | 5938 | 121.472 | 5.2.2: line 316: AttributeError: 'Scene' object has no attribute 'use_frame_loop' |
| w4l-07 | 0 | files | broken | – | – | – | – | – | 3335 | 69.523 | contract: handoff_missing, no_file_line |
| w4l-08 | 0 | blender | broken | after_deps | pass | pass | ok | 0 | 3746 | 81.433 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w4l-10 | 0 | section | broken | – | – | – | – | – | 1341 | 42.52 | contract: handoff_missing, no_heading |
