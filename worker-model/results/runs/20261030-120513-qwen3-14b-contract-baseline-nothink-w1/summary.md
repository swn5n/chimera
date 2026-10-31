# qwen3:14b, contract prompt, on the worker eval (w1.0)

2026-10-30T12:05:13-05:00 · Ollama 0.40.1 · digest `bdbd181c33f2` · samples 3 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: every request sends "think": false (Chimera 0.7.0 sends no think field; the trained worker's template forces thinking off); a worker step's reply content is cut after 6144 tokens and scored as a runaway in content (the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap; every reply, thinking included, is cut after 16384 tokens (the runaway guard; a worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard).

| – | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 (checked) | crash 5.2.2 (all) | no script | assertions | API errors | repaired | expect | runaway | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 42 | 50% | 50% | 30 | 33% | 33% | 33% | 60% | 60% | 0% | – | 3.5 | – | – | 0% | 0% | 561.0 | 60.650000000000006 | 10.2635 |
| w1 | 42 | 50% | 50% | 30 | 33% | 33% | 33% | 60% | 60% | 0% | – | 3.5 | – | – | 0% | 0% | 561.0 | 60.650000000000006 | 10.2635 |
| blender | 30 | 43% | 43% | 30 | 33% | 33% | 33% | 60% | 60% | 0% | – | 3.5 | – | – | 0% | 0% | 687.5 | 60.45 | 11.949000000000002 |
| files | 6 | 50% | 50% | – | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 418.0 | 60.9 | 6.9925 |
| section | 6 | 83% | 83% | – | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 268.0 | 61.150000000000006 | 5.8095 |

contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: line): what data generation keeps. Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run (no script: 0) and a runaway (0, of which 0 had no script) count as fails, not as left out. strict: not a runaway; Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows (tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same rule; the probes run there). crash: the check's outcome was failed (a definite crash); "checked" is over the 30 samples Blender checked (the plan's "definite crashes at most 10%"), "all" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a crash. no script: the reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 (no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has. runaway: the runner stopped reading the reply, in content (its content passed the reply cap of 6144 tokens, thinking not counted, or the guard hit while it wrote content) or in thinking (the runaway guard, 16384 tokens with thinking, hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and no think field and has neither limit. cut off: Ollama itself stopped at a length limit. The plan's cut-off bar counts both.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bw-01/s1 | 0 | blender | ok | joined | pass | pass | – | 0 | 351 | 7.545 | – |
| bw-01/s1 | 1 | blender | ok | joined | pass | pass | – | 0 | 349 | 5.799 | – |
| bw-01/s1 | 2 | blender | ok | joined | pass | pass | – | 0 | 325 | 5.416 | – |
| bw-01/s5 | 0 | blender | broken | after_deps | pass | pass | – | 0 | 607 | 12.338 | contract: no_settings |
| bw-01/s5 | 1 | blender | broken | after_deps | pass | pass | – | 0 | 730 | 12.21 | contract: no_settings |
| bw-01/s5 | 2 | blender | broken | after_deps | failed | failed | – | 0 | 698 | 11.688 | 5.2.2: line 66: ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 3 items, not 4 |
| bw-03/s1 | 0 | blender | broken | alone | failed | failed | – | 13 | 2292 | 39.784 | 5.2.2: line 42: TypeError: Converting py args to operator properties: enum "ORIGIN_CENTER_CURSOR" not found in ('GEOMETR |
| bw-03/s1 | 1 | blender | broken | alone | failed | failed | – | 8 | 2294 | 38.441 | 5.2.2: line 79: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| bw-03/s1 | 2 | blender | broken | alone | failed | failed | – | 11 | 2312 | 38.676 | 5.2.2: line 56: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| bw-04/s1 | 0 | blender | broken | alone | failed | failed | – | 0 | 559 | 10.658 | 5.2.2: line 42: TypeError: bpy_struct: item.attr = val: enum "PERSPECTIVE" not found in ('PERSP', 'ORTHO', 'PANO', 'CUST |
| bw-04/s1 | 1 | blender | ok | joined | unsure | unsure | – | 1 | 495 | 8.209 | 5.2.2: line 37: AttributeError: Calling operator "bpy.ops.uv.sculpt_mode_toggle" error, could not be found |
| bw-04/s1 | 2 | blender | broken | alone | unsure | unsure | – | 2 | 563 | 9.33 | 5.2.2: line 39: AttributeError: Calling operator "bpy.ops.uv.sculpt_mode_toggle" error, could not be found |
| bw-05/s1 | 0 | blender | broken | alone | failed | failed | – | 12 | 1242 | 21.939 | 5.2.2: line 15: AttributeError: 'GeometryNodeTree' object has no attribute 'inputs' |
| bw-05/s1 | 1 | blender | broken | alone | failed | failed | – | 14 | 1223 | 20.347 | 5.2.2: line 14: AttributeError: 'GeometryNodeTree' object has no attribute 'inputs' |
| bw-05/s1 | 2 | blender | broken | alone | failed | failed | – | 12 | 1334 | 22.199 | 5.2.2: line 15: AttributeError: 'GeometryNodeTree' object has no attribute 'inputs' |
| bw-09/s1 | 0 | blender | broken | alone | pass | pass | – | 0 | 1029 | 18.465 | contract: saves_or_renders |
| bw-09/s1 | 1 | blender | broken | alone | failed | failed | – | 0 | 1697 | 28.263 | 5.2.2: line 43: RuntimeError: internal error setting the array |
| bw-09/s1 | 2 | blender | broken | alone | pass | pass | – | 0 | 971 | 16.15 | contract: deletes_scene, saves_or_renders |
| bw-09/s3 | 0 | blender | ok | joined | failed | failed | – | 3 | 722 | 13.238 | 5.2.2: line 4: ImportError: cannot import name 'AddNode' from 'bpy_extras.node_utils' (/Applications/Blender 3.app/Conte |
| bw-09/s3 | 1 | blender | ok | joined | failed | failed | – | 3 | 492 | 8.163 | 5.2.2: line 4: ImportError: cannot import name 'FindNode' from 'bpy_extras.node_utils' (/Applications/Blender 3.app/Cont |
| bw-09/s3 | 2 | blender | ok | joined | failed | failed | – | 3 | 677 | 11.21 | 5.2.2: line 4: ImportError: cannot import name 'find_node_tree' from 'bpy_extras.node_utils' (/Applications/Blender 3.ap |
| bw-10/s1 | 0 | blender | ok | joined | pass | pass | – | 0 | 190 | 4.604 | – |
| bw-10/s1 | 1 | blender | ok | joined | pass | pass | – | 0 | 183 | 3.052 | – |
| bw-10/s1 | 2 | blender | ok | joined | pass | pass | – | 0 | 187 | 3.12 | – |
| bw-10/s4 | 0 | blender | ok | joined | failed | failed | – | 2 | 943 | 17.731 | 5.2.2: line 67: RuntimeError: internal error setting the array |
| bw-10/s4 | 1 | blender | ok | joined | failed | failed | – | 3 | 905 | 15.111 | 5.2.2: line 86: ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 4 items, not 5 |
| bw-10/s4 | 2 | blender | ok | joined | failed | failed | – | 2 | 789 | 13.158 | 5.2.2: line 104: AttributeError: 'Object' object has no attribute 'game_settings' |
| code-01/s1 | 0 | files | broken | – | – | – | – | – | 266 | 5.558 | contract: no_file_line |
| code-01/s1 | 1 | files | broken | – | – | – | – | – | 271 | 4.464 | contract: no_file_line |
| code-01/s1 | 2 | files | broken | – | – | – | – | – | 325 | 5.356 | contract: no_file_line |
| code-12/s1 | 0 | files | ok | – | – | – | – | – | 514 | 9.869 | – |
| code-12/s1 | 1 | files | ok | – | – | – | – | – | 511 | 8.451 | – |
| code-12/s1 | 2 | files | ok | – | – | – | – | – | 511 | 8.427 | – |
| res-01/s1 | 0 | section | ok | – | – | – | – | – | 224 | 4.679 | – |
| res-01/s5 | 0 | section | ok | – | – | – | – | – | 653 | 15.737 | – |
| res-06/s1 | 0 | section | ok | – | – | – | – | – | 251 | 6.299 | – |
| res-06/s3 | 0 | section | ok | – | – | – | – | – | 227 | 4.797 | – |
| bl-03/s1 | 0 | blender | broken | alone | failed | failed | – | 6 | 585 | 10.785 | 5.2.2: line 30: AttributeError: 'NoiseTexture' object has no attribute 'noise_scale' |
| bl-03/s1 | 1 | blender | broken | alone | failed | failed | – | 6 | 438 | 7.242 | 5.2.2: line 26: AttributeError: 'DisplaceModifier' object has no attribute 'method' |
| bl-03/s1 | 2 | blender | broken | alone | failed | failed | – | 4 | 677 | 11.278 | 5.2.2: line 25: AttributeError: 'DisplaceModifier' object has no attribute 'method' |
| batch-06/s1 | 0 | section | broken | – | – | – | – | – | 285 | 5.32 | contract: no_heading |
| batch-06/s2 | 0 | section | ok | – | – | – | – | – | 334 | 6.747 | – |
