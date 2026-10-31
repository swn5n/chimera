# gemma4:12b-it-q4_K_M, today prompt, on the worker eval (w1.0)

2026-10-30T02:05:29-05:00 · Ollama 0.40.1 · digest `6114515d63c1` · samples 1 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: repair cases (W3) under today's prompt get the contract's repair part appended (Chimera 0.7.0 has no step repair); a worker step's reply content is cut after 6144 tokens and scored as a runaway in content (the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap; every reply, thinking included, is cut after 16384 tokens (the runaway guard; a worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard).

| – | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 (checked) | crash 5.2.2 (all) | no script | assertions | API errors | repaired | expect | runaway | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 36 | 0% | 0% | 30 | 20% | 20% | 20% | 70% | 53% | 23% | 17% | 2.72 | 40% | 10% | 0% | 19% | 3459.0 | 59.75 | 64.0265 |
| w2 | 16 | 0% | 0% | 16 | 6% | 6% | 6% | 85% | 69% | 19% | 6% | 4.23 | – | – | 0% | 19% | 4190.0 | 60.55 | 73.475 |
| w3 | 10 | 0% | 0% | 10 | 40% | 40% | 40% | 33% | 20% | 40% | 30% | 1.0 | 40% | – | 0% | 40% | 5885.5 | 59.55 | 99.0295 |
| w4f | 5 | 0% | 0% | 2 | 50% | 50% | 50% | 50% | 50% | 0% | 50% | 1.5 | – | 0% | 0% | 0% | 1966 | 58.2 | 30.428 |
| w4l | 5 | 0% | 0% | 2 | 0% | 0% | 0% | 100% | 100% | 0% | 0% | 1.0 | – | 20% | 0% | 0% | 2843 | 54.4 | 63.638 |
| blender | 30 | 0% | 0% | 30 | 20% | 20% | 20% | 70% | 53% | 23% | 17% | 2.72 | 40% | 25% | 0% | 23% | 4530.5 | 59.75 | 79.015 |
| files | 2 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 2640.0 | 63.650000000000006 | 45.95 |
| python-script | 1 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 2029 | 67.5 | 30.428 |
| section | 3 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 1869 | 54.4 | 44.657 |

contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: line): what data generation keeps. Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run (no script: 7) and a runaway (0, of which 0 had no script) count as fails, not as left out. strict: not a runaway; Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows (tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same rule; the probes run there). crash: the check's outcome was failed (a definite crash); "checked" is over the 23 samples Blender checked (the plan's "definite crashes at most 10%"), "all" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a crash. no script: the reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 (no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has. runaway: the runner stopped reading the reply, in content (its content passed the reply cap of 6144 tokens, thinking not counted, or the guard hit while it wrote content) or in thinking (the runaway guard, 16384 tokens with thinking, hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and no think field and has neither limit. cut off: Ollama itself stopped at a length limit. The plan's cut-off bar counts both.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 2777 | 42.162 | 5.2.2: line 22: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w2-02 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 1850 | 27.913 | 5.2.2: line 16: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-04 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 6031 | 101.625 | 5.2.2: line 58: AttributeError: 'Mesh' object has no attribute 'use_smooths' |
| w2-05 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 3440 | 54.397 | 5.2.2: line 13: RuntimeError: Error: Node type ShaderNode_Output_Material undefined |
| w2-07 | 0 | blender | broken | none | – | – | – | – | 7909 | 118.148 | no script: not joined: s1: empty: the reply is empty; the reply has no Blender script |
| w2-08 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 2147 | 34.952 | 5.2.2: line 21: AttributeError: 'SceneEEVEE' object has no attribute 'render_samples'. Did you mean: 'taa_render_samples |
| w2-10 | 0 | blender | broken | none | – | – | – | – | 7933 | 119.893 | no script: not joined: s3: empty: the reply is empty; the reply has no Blender script |
| w2-12 | 0 | blender | broken | alone | failed | failed | FAIL | 12 | 6579 | 110.154 | 5.2.2: line 21: AttributeError: 'GeometryNodeTree' object has no attribute 'inputs' |
| w2-13 | 0 | blender | broken | alone | failed | failed | FAIL | 13 | 2540 | 43.965 | 5.2.2: line 7: AttributeError: 'module' object has no attribute 'ICOSphere' |
| w2-14 | 0 | blender | broken | alone | failed | failed | FAIL | 14 | 4401 | 76.533 | 5.2.2: line 8: TypeError: Converting py args to operator properties:: keyword "name" unrecognized |
| w2-16 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 1177 | 20.024 | 5.2.2: line 12: TypeError: bpy_struct: item.attr = val: enum "Punchy" not found in ('None', 'AgX - Punchy', 'AgX - Greys |
| w2-18 | 0 | blender | broken | none | – | – | – | – | 7923 | 143.492 | no script: not joined: s2: empty: the reply is empty; the reply has no Blender script |
| w2-19 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 6830 | 112.27 | 5.2.2: line 22: AttributeError: 'Action' object has no attribute 'fcurves' |
| w2-21 | 0 | blender | broken | alone | unsure | unsure | FAIL | 3 | 4660 | 81.497 | 5.2.2: line 18: AttributeError: Calling operator "bpy.ops.mesh.ico_sphere_add" error, could not be found |
| w2-25 | 0 | blender | broken | alone | pass | pass | ok | 0 | 2184 | 35.428 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-27 | 0 | blender | broken | alone | failed | failed | FAIL | 0 | 3979 | 70.417 | 5.2.2: line 40: TypeError: 'int' object is not iterable |
| w3-01 | 0 | blender | broken | none | – | – | – | 0 | 7214 | 114.107 | no script: not joined: s1: handoff_missing: no ```handoff block at the end; s1: unclosed_block: the python block is neve |
| w3-03 | 0 | blender | broken | alone | pass | pass | ok | 0 | 4993 | 83.952 | contract: handoff_missing |
| w3-04 | 0 | blender | broken | alone | pass | pass | ok | 0 | 3193 | 51.569 | contract: handoff_missing |
| w3-06 | 0 | blender | broken | alone | pass | pass | FAIL | 0 | 3202 | 56.877 | contract: handoff_missing |
| w3-09 | 0 | blender | broken | none | – | – | – | 1 | 7392 | 127.98 | no script: not joined: s3: handoff_missing: no ```handoff block at the end; s3: unclosed_block: the python block is neve |
| w3-11 | 0 | blender | broken | none | – | – | – | – | 7170 | 120.254 | no script: not joined: s1: empty: the reply is empty; the reply has no Blender script |
| w3-12 | 0 | blender | broken | after_deps | failed | failed | FAIL | 0 | 3279 | 57.605 | 5.2.2: line 81: ValueError: not enough values to unpack (expected 5, got 4) |
| w3-13 | 0 | blender | broken | alone | failed | failed | FAIL | 4 | 6755 | 121.581 | 5.2.2: line 77: TypeError: ObjectModifiers.new(): error with keyword argument "type" -  enum "SHADING" not found in ('GR |
| w3-14 | 0 | blender | broken | alone | pass | pass | ok | 3 | 5016 | 83.584 | contract: handoff_missing |
| w3-19 | 0 | blender | broken | none | – | – | – | – | 7165 | 122.683 | no script: not joined: s1: empty: the reply is empty; the reply has no Blender script |
| w4f-01 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 2398 | 41.816 | 5.2.2: line 9: AttributeError: 'Camera' object has no attribute 'd_stop' |
| w4f-02 | 0 | blender | broken | alone | pass | pass | ok | 0 | 1966 | 34.168 | contract: guard_not_build, handoff_missing, no_build, no_settings |
| w4f-05 | 0 | python-script | broken | – | – | – | – | – | 2029 | 30.428 | contract: handoff_missing |
| w4f-06 | 0 | files | broken | – | – | – | – | – | 1802 | 27.485 | contract: handoff_missing, no_file_line |
| w4f-08 | 0 | section | broken | – | – | – | – | – | 1548 | 28.818 | contract: handoff_missing, no_heading |
| w4l-02 | 0 | section | broken | – | – | – | – | – | 1869 | 44.657 | contract: handoff_missing, no_heading |
| w4l-04 | 0 | blender | broken | after_deps | failed | failed | FAIL | 1 | 5810 | 108.841 | 5.2.2: line 354: AttributeError: 'Action' object has no attribute 'fcurves' |
| w4l-07 | 0 | files | broken | – | – | – | – | – | 3478 | 64.415 | contract: handoff_missing, no_file_line |
| w4l-08 | 0 | blender | broken | after_deps | failed | failed | FAIL | 1 | 2843 | 63.638 | 5.2.2: line 158: AttributeError: 'SceneEEVEE' object has no attribute 'use_bloom' |
| w4l-10 | 0 | section | broken | – | – | – | – | – | 2681 | 63.151 | contract: handoff_missing, no_heading |
