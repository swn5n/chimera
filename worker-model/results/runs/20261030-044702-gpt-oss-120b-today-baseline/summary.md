# gpt-oss:120b, today prompt, on the worker eval (w1.0)

2026-10-30T04:47:02-05:00 · Ollama 0.40.1 · digest `714d86958b6e` · samples 2 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: repair cases (W3) under today's prompt get the contract's repair part appended (Chimera 0.7.0 has no step repair); a worker step's reply content is cut after 6144 tokens and scored as a runaway in content (the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap; every reply, thinking included, is cut after 16384 tokens (the runaway guard; a worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard).

| – | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 (checked) | crash 5.2.2 (all) | no script | assertions | API errors | repaired | expect | runaway | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 69 | 1% | 1% | 60 | 38% | 42% | 38% | 62% | 62% | 0% | 32% | 1.62 | 50% | 12% | 0% | 0% | 1320 | 82.3 | 16.589 |
| w2 | 32 | 0% | 0% | 32 | 31% | 31% | 31% | 69% | 69% | 0% | 22% | 2.19 | – | – | 0% | 0% | 1313.5 | 82.4 | 16.1725 |
| w3 | 20 | 5% | 5% | 20 | 50% | 60% | 50% | 50% | 50% | 0% | 45% | 1.25 | 50% | – | 0% | 0% | 1357.5 | 82.0 | 16.985500000000002 |
| w4f | 9 | 0% | 0% | 4 | 25% | 25% | 25% | 75% | 75% | 0% | 25% | 0.25 | – | 0% | 0% | 0% | 1124 | 82.5 | 13.681 |
| w4l | 8 | 0% | 0% | 4 | 50% | 50% | 50% | 50% | 50% | 0% | 50% | 0.25 | – | 25% | 0% | 0% | 1382.5 | 78.69999999999999 | 19.375500000000002 |
| blender | 60 | 2% | 2% | 60 | 38% | 42% | 38% | 62% | 62% | 0% | 32% | 1.62 | 50% | 25% | 0% | 0% | 1327.5 | 82.3 | 16.5945 |
| files | 4 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 1063.0 | 80.9 | 14.4025 |
| python-script | 2 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 1134.0 | 82.45 | 13.9505 |
| section | 3 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 1445 | 78.4 | 27.258 |

contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: line): what data generation keeps. Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run (no script: 0) and a runaway (0, of which 0 had no script) count as fails, not as left out. strict: not a runaway; Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows (tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same rule; the probes run there). crash: the check's outcome was failed (a definite crash); "checked" is over the 60 samples Blender checked (the plan's "definite crashes at most 10%"), "all" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a crash. no script: the reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 (no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has. runaway: the runner stopped reading the reply, in content (its content passed the reply cap of 6144 tokens, thinking not counted, or the guard hit while it wrote content) or in thinking (the runaway guard, 16384 tokens with thinking, hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and no think field and has neither limit. cut off: Ollama itself stopped at a length limit. The plan's cut-off bar counts both.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 1300 | 16.133 | 5.2.2: line 21: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w2-01 | 1 | blender | broken | alone | failed | failed | FAIL | 2 | 1277 | 15.57 | 5.2.2: line 43: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w2-02 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 950 | 11.86 | 5.2.2: line 26: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-02 | 1 | blender | broken | alone | failed | failed | FAIL | 1 | 899 | 10.967 | 5.2.2: line 24: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-04 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 1837 | 22.673 | 5.2.2: line 70: AttributeError: 'Mesh' object has no attribute 'use_auto_smooth' |
| w2-04 | 1 | blender | broken | alone | failed | failed | FAIL | 2 | 1361 | 16.6 | 5.2.2: line 73: AttributeError: 'Mesh' object has no attribute 'use_auto_smooth' |
| w2-05 | 0 | blender | broken | alone | pass | pass | FAIL | 0 | 986 | 12.334 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-05 | 1 | blender | broken | alone | pass | pass | FAIL | 0 | 1057 | 12.908 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-07 | 0 | blender | broken | alone | pass | pass | ok | 0 | 2399 | 29.611 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-07 | 1 | blender | broken | alone | failed | failed | FAIL | 1 | 1757 | 21.429 | 5.2.2: line 70: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-08 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 754 | 9.484 | 5.2.2: line 14: AttributeError: 'SceneEEVEE' object has no attribute 'use_ssr' |
| w2-08 | 1 | blender | broken | alone | pass | pass | FAIL | 4 | 1097 | 13.38 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-10 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 1040 | 12.947 | 5.2.2: line 13: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-10 | 1 | blender | broken | alone | failed | failed | FAIL | 2 | 1208 | 14.734 | 5.2.2: line 13: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-12 | 0 | blender | broken | alone | failed | failed | FAIL | 12 | 2988 | 36.914 | 5.2.2: line 38: AttributeError: 'GeometryNodeTree' object has no attribute 'inputs' |
| w2-12 | 1 | blender | broken | alone | failed | failed | FAIL | 5 | 3074 | 37.7 | 5.2.2: line 26: AttributeError: 'GeometryNodeTree' object has no attribute 'inputs' |
| w2-13 | 0 | blender | broken | alone | failed | failed | FAIL | 8 | 1791 | 22.134 | 5.2.2: line 43: TypeError: BlendDataNodeTrees.new(): error with argument 2, "type" -  enum "GEOMETRY_NODES" not found in |
| w2-13 | 1 | blender | broken | alone | failed | failed | FAIL | 8 | 2213 | 27.044 | 5.2.2: line 33: AttributeError: 'GeometryNodeTree' object has no attribute 'inputs' |
| w2-14 | 0 | blender | broken | alone | failed | failed | FAIL | 8 | 2191 | 27.04 | 5.2.2: line 50: TypeError: Converting py args to operator properties:: keyword "radius" unrecognized |
| w2-14 | 1 | blender | broken | alone | failed | failed | FAIL | 1 | 2415 | 29.556 | 5.2.2: line 26: AttributeError: 'Mesh' object has no attribute 'from_mesh' |
| w2-16 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 923 | 11.542 | 5.2.2: line 21: AttributeError: type object 'Scene' has no attribute 'view_settings' |
| w2-16 | 1 | blender | broken | alone | failed | failed | FAIL | 1 | 591 | 7.221 | 5.2.2: line 14: TypeError: bpy_struct: item.attr = val: enum "Punch" not found in ('None', 'AgX - Punchy', 'AgX - Greysc |
| w2-18 | 0 | blender | broken | alone | pass | pass | ok | 0 | 1327 | 16.436 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-18 | 1 | blender | broken | alone | pass | pass | ok | 0 | 1558 | 19.011 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-19 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 1066 | 13.659 | 5.2.2: line 49: AttributeError: 'Action' object has no attribute 'fcurves' |
| w2-19 | 1 | blender | broken | alone | failed | failed | FAIL | 2 | 1383 | 16.88 | 5.2.2: line 41: KeyError: 'bpy_prop_collection[key]: key "Sheen" not found' |
| w2-21 | 0 | blender | broken | alone | pass | pass | ok | 0 | 1150 | 14.286 | contract: guard_not_build, handoff_missing, no_build, no_settings |
| w2-21 | 1 | blender | broken | alone | failed | failed | FAIL | 1 | 1328 | 16.212 | 5.2.2: line 25: NameError: name 'Matrix' is not defined |
| w2-25 | 0 | blender | broken | alone | pass | pass | ok | 0 | 585 | 7.429 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-25 | 1 | blender | broken | alone | pass | pass | ok | 0 | 676 | 8.221 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-27 | 0 | blender | broken | alone | pass | pass | ok | 0 | 1382 | 17.11 | contract: guard_not_build, handoff_missing, no_build, no_settings |
| w2-27 | 1 | blender | broken | alone | failed | failed | FAIL | 1 | 1429 | 17.85 | 5.2.2: line 64: AttributeError: 'Mesh' object has no attribute 'calc_normals'. Did you mean: 'flip_normals'? |
| w3-01 | 0 | blender | broken | alone | pass | pass | ok | 0 | 1250 | 16.027 | contract: handoff_missing |
| w3-01 | 1 | blender | broken | alone | pass | pass | ok | 0 | 1310 | 16.058 | contract: handoff_missing |
| w3-03 | 0 | blender | broken | alone | pass | pass | ok | 0 | 988 | 12.692 | contract: handoff_missing |
| w3-03 | 1 | blender | broken | alone | pass | pass | ok | 0 | 663 | 8.132 | contract: handoff_missing |
| w3-04 | 0 | blender | broken | alone | pass | pass | ok | 0 | 1222 | 15.48 | contract: handoff_missing |
| w3-04 | 1 | blender | broken | alone | pass | pass | ok | 0 | 1028 | 12.587 | contract: handoff_missing |
| w3-06 | 0 | blender | broken | alone | pass | pass | ok | 0 | 1494 | 18.978 | contract: handoff_missing |
| w3-06 | 1 | blender | broken | alone | pass | pass | ok | 2 | 1592 | 19.516 | contract: handoff_missing |
| w3-09 | 0 | blender | broken | alone | pass | pass | FAIL | 1 | 1536 | 19.433 | contract: handoff_missing |
| w3-09 | 1 | blender | broken | alone | failed | failed | FAIL | 1 | 1519 | 18.599 | 5.2.2: line 42: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w3-11 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 1795 | 22.763 | 5.2.2: line 85: AttributeError: 'Mesh' object has no attribute 'use_auto_smooth' |
| w3-11 | 1 | blender | broken | alone | failed | failed | FAIL | 1 | 1546 | 18.977 | 5.2.2: line 82: AttributeError: 'Mesh' object has no attribute 'use_auto_smooth' |
| w3-12 | 0 | blender | broken | after_deps | failed | failed | FAIL | 3 | 1348 | 17.241 | 5.2.2: line 108: AttributeError: module 'mathutils' has no attribute 'pi' |
| w3-12 | 1 | blender | broken | after_deps | pass | pass | ok | 0 | 1352 | 16.589 | contract: handoff_missing |
| w3-13 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 1588 | 20.346 | 5.2.2: line 39: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-13 | 1 | blender | broken | alone | failed | failed | FAIL | 2 | 2199 | 27.075 | 5.2.2: line 108: AttributeError: 'Mesh' object has no attribute 'use_auto_smooth' |
| w3-14 | 0 | blender | broken | alone | failed | failed | FAIL | 6 | 852 | 10.983 | 5.2.2: line 28: AttributeError: 'SceneEEVEE' object has no attribute 'use_screen_space_reflection' |
| w3-14 | 1 | blender | broken | alone | failed | failed | FAIL | 5 | 857 | 10.484 | 5.2.2: line 26: AttributeError: 'SceneEEVEE' object has no attribute 'use_ssr' |
| w3-19 | 0 | blender | broken | alone | failed | pass | FAIL | 0 | 1603 | 20.398 | 5.2.2: line 80: TypeError: bpy_struct[key] = val: id properties not supported for this type |
| w3-19 | 1 | blender | ok | joined | failed | pass | FAIL | 0 | 1363 | 16.73 | 5.2.2: line 80: TypeError: bpy_struct[key] = val: id properties not supported for this type |
| w4f-01 | 0 | blender | broken | alone | failed | failed | FAIL | 0 | 1131 | 14.07 | 5.2.2: line 35: RuntimeError: Product object 'chimera_product' not found. Make sure the previous step created it with th |
| w4f-01 | 1 | blender | broken | alone | failed | failed | FAIL | 0 | 987 | 12.319 | 5.2.2: line 12: RuntimeError: Product object 'chimera_product' not found. Cannot place camera. |
| w4f-02 | 0 | blender | broken | alone | pass | pass | ok | 0 | 2005 | 24.734 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w4f-02 | 1 | blender | broken | alone | failed | failed | FAIL | 1 | 1822 | 22.225 | 5.2.2: line 9: ImportError: cannot import name 'BVHTree' from 'mathutils' (unknown location). Did you mean: 'bvhtree'? |
| w4f-05 | 0 | python-script | broken | – | – | – | – | – | 1144 | 14.22 | contract: handoff_missing |
| w4f-05 | 1 | python-script | broken | – | – | – | – | – | 1124 | 13.681 | contract: handoff_missing |
| w4f-06 | 0 | files | broken | – | – | – | – | – | 836 | 10.432 | contract: handoff_missing, no_file_line |
| w4f-06 | 1 | files | broken | – | – | – | – | – | 783 | 9.53 | contract: handoff_missing, no_file_line |
| w4f-08 | 0 | section | broken | – | – | – | – | – | 689 | 8.632 | contract: handoff_missing |
| w4l-02 | 0 | section | broken | – | – | – | – | – | 1445 | 27.258 | contract: handoff_missing, no_heading |
| w4l-04 | 0 | blender | broken | after_deps | failed | failed | FAIL | 0 | 1860 | 28.19 | 5.2.2: line 327: AttributeError: 'Action' object has no attribute 'fcurves' |
| w4l-04 | 1 | blender | broken | after_deps | failed | failed | FAIL | 1 | 1320 | 16.836 | 5.2.2: line 356: AttributeError: 'Action' object has no attribute 'fcurves' |
| w4l-07 | 0 | files | broken | – | – | – | – | – | 1290 | 20.378 | contract: handoff_missing, no_file_line |
| w4l-07 | 1 | files | broken | – | – | – | – | – | 1449 | 18.373 | contract: handoff_missing, no_file_line |
| w4l-08 | 0 | blender | broken | after_deps | pass | pass | ok | 0 | 994 | 17.876 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w4l-08 | 1 | blender | broken | after_deps | pass | pass | ok | 0 | 1026 | 13.163 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w4l-10 | 0 | section | broken | – | – | – | – | – | 2141 | 36.201 | contract: handoff_missing, no_heading |
