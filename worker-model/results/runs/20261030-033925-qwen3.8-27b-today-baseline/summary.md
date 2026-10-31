# qwen3.8:27b, today prompt, on the worker eval (w1.0)

2026-10-30T03:39:25-05:00 · Ollama 0.40.1 · digest `47951e4a6661` · samples 1 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: repair cases (W3) under today's prompt get the contract's repair part appended (Chimera 0.7.0 has no step repair); a worker step's reply content is cut after 6144 tokens and scored as a runaway in content (the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap; every reply, thinking included, is cut after 16384 tokens (the runaway guard; a worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard).

| – | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 (checked) | crash 5.2.2 (all) | no script | assertions | API errors | repaired | expect | runaway | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 36 | 6% | 6% | 30 | 57% | 63% | 57% | 43% | 43% | 0% | 43% | 0.87 | 70% | 10% | 0% | 0% | 2394.0 | 73.9 | 33.446 |
| w2 | 16 | 0% | 0% | 16 | 50% | 62% | 50% | 50% | 50% | 0% | 31% | 1.12 | – | – | 0% | 0% | 2596.0 | 75.4 | 35.101 |
| w3 | 10 | 20% | 20% | 10 | 70% | 70% | 70% | 30% | 30% | 0% | 60% | 0.6 | 70% | – | 0% | 0% | 1846.5 | 74.3 | 27.0135 |
| w4f | 5 | 0% | 0% | 2 | 50% | 50% | 50% | 50% | 50% | 0% | 50% | 0.0 | – | 0% | 0% | 0% | 1358 | 71.4 | 17.141 |
| w4l | 5 | 0% | 0% | 2 | 50% | 50% | 50% | 50% | 50% | 0% | 50% | 1.0 | – | 20% | 0% | 0% | 2843 | 65.0 | 63.11 |
| blender | 30 | 7% | 7% | 30 | 57% | 63% | 57% | 43% | 43% | 0% | 43% | 0.87 | 70% | 25% | 0% | 0% | 2457.5 | 74.7 | 33.446 |
| files | 2 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 1806.5 | 71.55000000000001 | 32.89 |
| python-script | 1 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 1358 | 81.9 | 17.141 |
| section | 3 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 2437 | 60.1 | 59.813 |

contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: line): what data generation keeps. Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run (no script: 0) and a runaway (0, of which 0 had no script) count as fails, not as left out. strict: not a runaway; Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows (tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same rule; the probes run there). crash: the check's outcome was failed (a definite crash); "checked" is over the 30 samples Blender checked (the plan's "definite crashes at most 10%"), "all" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a crash. no script: the reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 (no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has. runaway: the runner stopped reading the reply, in content (its content passed the reply cap of 6144 tokens, thinking not counted, or the guard hit while it wrote content) or in thinking (the runaway guard, 16384 tokens with thinking, hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and no think field and has neither limit. cut off: Ollama itself stopped at a length limit. The plan's cut-off bar counts both.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | blender | broken | alone | pass | pass | FAIL | 0 | 2628 | 34.205 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-02 | 0 | blender | broken | alone | pass | pass | FAIL | 0 | 2187 | 28.074 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-04 | 0 | blender | broken | alone | failed | failed | FAIL | 6 | 6774 | 88.729 | 5.2.2: line 54: AttributeError: 'Mesh' object has no attribute 'normals_compute'. Did you mean: 'normals_domain'? |
| w2-05 | 0 | blender | broken | alone | pass | pass | FAIL | 0 | 2156 | 27.56 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-07 | 0 | blender | broken | alone | pass | pass | ok | 0 | 5096 | 68.253 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-08 | 0 | blender | broken | alone | failed | failed | FAIL | 5 | 1201 | 16.471 | 5.2.2: line 33: AttributeError: 'SceneEEVEE' object has no attribute 'use_ssr' |
| w2-10 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 1474 | 20.762 | 5.2.2: line 11: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-12 | 0 | blender | broken | alone | failed | pass | FAIL | 0 | 4320 | 58.358 | 5.2.2: line 105: TypeError: bpy_struct[key] = val: id properties not supported for this type |
| w2-13 | 0 | blender | broken | alone | failed | pass | FAIL | 0 | 3616 | 48.617 | 5.2.2: line 68: TypeError: bpy_struct[key] = val: id properties not supported for this type |
| w2-14 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 4147 | 55.11 | 5.2.2: line 57: RuntimeError: Error: Node type GeometryNodeRandomValue undefined |
| w2-16 | 0 | blender | broken | alone | pass | pass | ok | 0 | 2351 | 31.787 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-18 | 0 | blender | broken | alone | pass | pass | ok | 0 | 2564 | 35.997 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-19 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 3611 | 49.673 | 5.2.2: line 29: AttributeError: 'Object' object has no attribute 'animation_data_action'. Did you mean: 'animation_data_ |
| w2-21 | 0 | blender | broken | alone | pass | pass | ok | 0 | 2339 | 32.687 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-25 | 0 | blender | broken | alone | pass | pass | ok | 0 | 885 | 12.148 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-27 | 0 | blender | broken | alone | failed | failed | FAIL | 0 | 3067 | 42.979 | 5.2.2: line 74: TypeError: Scene.ray_cast(): error with argument 1, "depsgraph" -  Function.depsgraph expected a Depsgra |
| w3-01 | 0 | blender | broken | alone | pass | pass | ok | 0 | 1730 | 23.878 | contract: handoff_not_last |
| w3-03 | 0 | blender | ok | joined | pass | pass | ok | 0 | 1002 | 14.644 | – |
| w3-04 | 0 | blender | ok | joined | pass | pass | ok | 0 | 1027 | 14.725 | – |
| w3-06 | 0 | blender | broken | alone | pass | pass | FAIL | 0 | 1808 | 26.523 | contract: handoff_missing |
| w3-09 | 0 | blender | broken | alone | pass | pass | ok | 0 | 1885 | 27.504 | contract: handoff_missing |
| w3-11 | 0 | blender | broken | alone | pass | pass | ok | 0 | 1726 | 23.949 | contract: handoff_not_last |
| w3-12 | 0 | blender | broken | after_deps | failed | failed | FAIL | 0 | 2037 | 29.397 | 5.2.2: line 76: TypeError: Scene.ray_cast(): error with argument 1, "depsgraph" -  Function.depsgraph expected a Depsgra |
| w3-13 | 0 | blender | broken | alone | failed | failed | FAIL | 0 | 4726 | 67.289 | 5.2.2: line 50: AttributeError: 'EdgeSplitModifier' object has no attribute 'use_smooth_shade' |
| w3-14 | 0 | blender | broken | alone | failed | failed | FAIL | 6 | 3470 | 48.544 | 5.2.2: line 23: AttributeError: 'RaytraceEEVEE' object has no attribute 'use_raytraced_reflections' |
| w3-19 | 0 | blender | broken | alone | pass | pass | ok | 0 | 3852 | 54.069 | contract: handoff_not_last |
| w4f-01 | 0 | blender | broken | alone | failed | failed | FAIL | 0 | 1943 | 27.637 | 5.2.2: line 28: NameError: name 'sensor_W' is not defined. Did you mean: 'sensor_h'? |
| w4f-02 | 0 | blender | broken | alone | pass | pass | ok | 0 | 14897 | 229.375 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w4f-05 | 0 | python-script | broken | – | – | – | – | – | 1358 | 17.141 | contract: handoff_missing, harmony_leftover |
| w4f-06 | 0 | files | broken | – | – | – | – | – | 1144 | 16.62 | contract: handoff_missing, no_file_line |
| w4f-08 | 0 | section | broken | – | – | – | – | – | 891 | 16.084 | contract: handoff_missing, no_heading |
| w4l-02 | 0 | section | broken | – | – | – | – | – | 2437 | 59.813 | contract: handoff_missing, no_heading |
| w4l-04 | 0 | blender | broken | after_deps | failed | failed | FAIL | 1 | 5874 | 104.919 | 5.2.2: line 372: AttributeError: 'Action' object has no attribute 'fcurves' |
| w4l-07 | 0 | files | broken | – | – | – | – | – | 2469 | 49.16 | contract: handoff_missing, no_file_line |
| w4l-08 | 0 | blender | broken | after_deps | pass | pass | ok | 1 | 2843 | 63.11 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w4l-10 | 0 | section | broken | – | – | – | – | – | 3855 | 93.765 | contract: handoff_missing, no_heading |
