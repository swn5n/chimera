# gemma4:12b-it-q4_K_M, contract prompt, on the worker eval (w1.0)

2026-10-30T11:34:43-05:00 · Ollama 0.40.1 · digest `6114515d63c1` · samples 3 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: every request sends "think": false (Chimera 0.7.0 sends no think field; the trained worker's template forces thinking off); a worker step's reply content is cut after 6144 tokens and scored as a runaway in content (the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap; every reply, thinking included, is cut after 16384 tokens (the runaway guard; a worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard).

| – | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 (checked) | crash 5.2.2 (all) | no script | assertions | API errors | repaired | expect | runaway | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 102 | 92% | 83% | 90 | 24% | 24% | 24% | 69% | 69% | 0% | 17% | 2.37 | 50% | 71% | 0% | 0% | 814.5 | 62.55 | 13.6765 |
| w2 | 48 | 85% | 85% | 48 | 15% | 15% | 15% | 73% | 73% | 0% | 8% | 3.46 | – | – | 0% | 0% | 877.5 | 60.349999999999994 | 14.180499999999999 |
| w3 | 30 | 100% | 93% | 30 | 50% | 50% | 50% | 50% | 50% | 0% | 37% | 1.07 | 50% | – | 0% | 0% | 794.0 | 64.85 | 12.8355 |
| w4f | 13 | 92% | 69% | 6 | 0% | 0% | 0% | 100% | 100% | 0% | 0% | 1.83 | – | 62% | 0% | 0% | 763 | 65.3 | 11.768 |
| w4l | 11 | 100% | 64% | 6 | 0% | 0% | 0% | 100% | 100% | 0% | 0% | 0.67 | – | 82% | 0% | 0% | 859 | 56.4 | 21.741 |
| blender | 90 | 91% | 84% | 90 | 24% | 24% | 24% | 69% | 69% | 0% | 17% | 2.37 | 50% | 83% | 0% | 0% | 842.0 | 61.75 | 13.827 |
| files | 6 | 100% | 50% | – | – | – | – | – | – | – | – | – | – | 67% | 0% | 0% | 627.5 | 68.95 | 9.619 |
| python-script | 3 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | 67% | 0% | 0% | 848 | 73.5 | 12.167 |
| section | 3 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | 33% | 0% | 0% | 676 | 50.8 | 24.038 |

contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: line): what data generation keeps. Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run (no script: 0) and a runaway (0, of which 0 had no script) count as fails, not as left out. strict: not a runaway; Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows (tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same rule; the probes run there). crash: the check's outcome was failed (a definite crash); "checked" is over the 90 samples Blender checked (the plan's "definite crashes at most 10%"), "all" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a crash. no script: the reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 (no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has. runaway: the runner stopped reading the reply, in content (its content passed the reply cap of 6144 tokens, thinking not counted, or the guard hit while it wrote content) or in thinking (the runaway guard, 16384 tokens with thinking, hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and no think field and has neither limit. cut off: Ollama itself stopped at a length limit. The plan's cut-off bar counts both.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 648 | 10.231 | 5.2.2: line 29: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w2-01 | 1 | blender | ok | joined | failed | failed | FAIL | 4 | 783 | 11.612 | 5.2.2: line 23: RuntimeError: Error: Node type ShaderNode_Principled undefined |
| w2-01 | 2 | blender | ok | joined | failed | failed | FAIL | 1 | 521 | 7.577 | 5.2.2: line 25: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w2-02 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 966 | 14.559 | 5.2.2: line 28: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-02 | 1 | blender | ok | joined | unsure | unsure | FAIL | 2 | 1210 | 18.327 | 5.2.2: line 80: AttributeError: 'NoneType' object has no attribute 'materials' |
| w2-02 | 2 | blender | ok | joined | pass | pass | FAIL | 2 | 795 | 12.16 | – |
| w2-04 | 0 | blender | ok | joined | failed | failed | FAIL | 3 | 1047 | 17.991 | 5.2.2: line 19: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-04 | 1 | blender | ok | joined | failed | failed | FAIL | 4 | 1519 | 26.152 | 5.2.2: line 19: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-04 | 2 | blender | ok | joined | pass | pass | FAIL | 0 | 1380 | 23.721 | – |
| w2-05 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 850 | 13.802 | 5.2.2: line 32: RuntimeError: Error: Node type _USE_OUTPUT undefined |
| w2-05 | 1 | blender | ok | joined | failed | failed | FAIL | 4 | 826 | 12.565 | 5.2.2: line 30: RuntimeError: Error: Node type ShaderNode_Output undefined |
| w2-05 | 2 | blender | ok | joined | failed | failed | FAIL | 3 | 784 | 11.656 | 5.2.2: line 29: RuntimeError: Error: Node type ShaderNode_Output_Material undefined |
| w2-07 | 0 | blender | ok | joined | failed | failed | FAIL | 6 | 3307 | 55.842 | 5.2.2: line 20: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-07 | 1 | blender | broken | alone | failed | failed | FAIL | 2 | 3829 | 65.456 | 5.2.2: line 14: AttributeError: 'Collection' object has no attribute 'new' |
| w2-07 | 2 | blender | broken | alone | failed | failed | FAIL | 1 | 952 | 16.187 | 5.2.2: line 51: AttributeError: 'Mesh' object has no attribute 'from_py_data'. Did you mean: 'from_pydata'? |
| w2-08 | 0 | blender | ok | joined | unsure | unsure | FAIL | 3 | 396 | 7.41 | 5.2.2: line 19: TypeError: bpy_struct: item.attr = val: enum "BLENDER_EEVEE_NEXT" not found in ('BLENDER_EEVEE', 'BLENDE |
| w2-08 | 1 | blender | ok | joined | unsure | unsure | FAIL | 2 | 482 | 8.431 | 5.2.2: line 19: TypeError: bpy_struct: item.attr = val: enum "BLENDER_EEVEE_NEXT" not found in ('BLENDER_EEVEE', 'BLENDE |
| w2-08 | 2 | blender | ok | joined | unsure | unsure | FAIL | 3 | 483 | 8.436 | 5.2.2: line 19: TypeError: bpy_struct: item.attr = val: enum "BLENDER_EEVEE_NEXT" not found in ('BLENDER_EEVEE', 'BLENDE |
| w2-10 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 789 | 13.716 | 5.2.2: line 17: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-10 | 1 | blender | broken | alone | failed | failed | FAIL | 6 | 548 | 9.725 | 5.2.2: line 16: AttributeError: 'Context' object has no attribute 'use_nodes' |
| w2-10 | 2 | blender | ok | joined | failed | failed | FAIL | 2 | 573 | 9.055 | 5.2.2: line 18: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-12 | 0 | blender | ok | joined | failed | failed | FAIL | 11 | 1241 | 22.484 | 5.2.2: line 29: TypeError: BlendDataNodeTrees.new(): required parameter "type" not specified |
| w2-12 | 1 | blender | ok | joined | failed | failed | FAIL | 12 | 2084 | 38.373 | 5.2.2: line 19: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-12 | 2 | blender | ok | joined | failed | failed | FAIL | 18 | 1580 | 27.188 | 5.2.2: line 18: AttributeError: 'Collection' object has no attribute 'create' |
| w2-13 | 0 | blender | ok | joined | failed | failed | FAIL | 10 | 1870 | 35.289 | 5.2.2: line 18: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-13 | 1 | blender | ok | joined | unsure | unsure | FAIL | 12 | 1168 | 19.097 | 5.2.2: line 24: AttributeError: 'NoneType' object has no attribute 'scale' and no __dict__ for setting new attributes |
| w2-13 | 2 | blender | ok | joined | unsure | unsure | FAIL | 8 | 1253 | 20.458 | 5.2.2: line 24: AttributeError: 'NoneType' object has no attribute 'data' |
| w2-14 | 0 | blender | broken | alone | failed | failed | FAIL | 11 | 1433 | 23.784 | 5.2.2: line 17: AttributeError: 'Collection' object has no attribute 'collection' |
| w2-14 | 1 | blender | ok | joined | failed | failed | FAIL | 0 | 1309 | 22.507 | 5.2.2: line 20: TypeError: CollectionObjects.link(): error with argument 1, "object" -  Function.object expected a Objec |
| w2-14 | 2 | blender | ok | joined | failed | failed | FAIL | 6 | 1390 | 23.499 | 5.2.2: line 19: TypeError: Converting py args to operator properties:: keyword "name" unrecognized |
| w2-16 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 491 | 9.423 | 5.2.2: line 18: AttributeError: 'Scene' object has no attribute 'make_options_visible' |
| w2-16 | 1 | blender | ok | joined | failed | failed | FAIL | 1 | 418 | 7.56 | 5.2.2: line 21: AttributeError: 'Scene' object has no attribute 'make_color_management_enabled' |
| w2-16 | 2 | blender | ok | joined | failed | failed | FAIL | 4 | 425 | 7.82 | 5.2.2: line 19: AttributeError: 'Scene' object has no attribute '_wm' |
| w2-18 | 0 | blender | ok | joined | pass | pass | ok | 0 | 731 | 13.637 | – |
| w2-18 | 1 | blender | ok | joined | pass | pass | FAIL | 0 | 811 | 13.469 | – |
| w2-18 | 2 | blender | ok | joined | failed | failed | FAIL | 1 | 729 | 12.241 | 5.2.2: line 18: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-19 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 1172 | 21.632 | 5.2.2: line 22: TypeError: bpy_struct: item.attr = val: Object.data expected a Image type, not Mesh |
| w2-19 | 1 | blender | ok | joined | failed | failed | FAIL | 1 | 615 | 9.974 | 5.2.2: line 17: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-19 | 2 | blender | ok | joined | failed | failed | FAIL | 0 | 749 | 13.096 | 5.2.2: line 53: AttributeError: 'Action' object has no attribute 'fcurves' |
| w2-21 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 905 | 15.298 | 5.2.2: line 21: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-21 | 1 | blender | ok | joined | failed | failed | FAIL | 3 | 1384 | 25.208 | 5.2.2: line 23: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-21 | 2 | blender | ok | joined | failed | failed | FAIL | 2 | 1031 | 18.25 | 5.2.2: line 26: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-25 | 0 | blender | ok | joined | pass | pass | ok | 0 | 435 | 7.517 | – |
| w2-25 | 1 | blender | ok | joined | pass | pass | ok | 0 | 409 | 6.393 | – |
| w2-25 | 2 | blender | ok | joined | pass | pass | ok | 0 | 463 | 7.299 | – |
| w2-27 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 922 | 15.134 | 5.2.2: line 20: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-27 | 1 | blender | broken | alone | failed | failed | FAIL | 5 | 1033 | 17.846 | 5.2.2: line 19: TypeError: Converting py args to operator properties:: keyword "name" unrecognized |
| w2-27 | 2 | blender | ok | joined | failed | failed | FAIL | 1 | 934 | 15.594 | 5.2.2: line 21: AttributeError: bpy_prop_collection: attribute "append" not found |
| w3-01 | 0 | blender | ok | joined | pass | pass | ok | 0 | 816 | 13.106 | – |
| w3-01 | 1 | blender | ok | joined | failed | failed | FAIL | 1 | 855 | 12.653 | 5.2.2: line 48: AttributeError: 'BevelModifier' object has no attribute 'use_mean_plane' |
| w3-01 | 2 | blender | ok | joined | pass | pass | ok | 0 | 707 | 9.83 | – |
| w3-03 | 0 | blender | ok | joined | pass | pass | ok | 0 | 370 | 6.798 | – |
| w3-03 | 1 | blender | ok | joined | pass | pass | ok | 0 | 351 | 5.479 | – |
| w3-03 | 2 | blender | ok | joined | pass | pass | ok | 0 | 298 | 4.191 | – |
| w3-04 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 500 | 8.806 | 5.2.2: line 37: AttributeError: Vector subtraction: (Vector - tuple) invalid type for this operation |
| w3-04 | 1 | blender | ok | joined | pass | pass | ok | 0 | 528 | 7.594 | – |
| w3-04 | 2 | blender | ok | joined | pass | pass | ok | 0 | 483 | 7.178 | – |
| w3-06 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 852 | 15.247 | 5.2.2: line 53: RuntimeError: Error: Node type _OUTPUT_NODE undefined |
| w3-06 | 1 | blender | ok | joined | pass | pass | FAIL | 0 | 650 | 10.396 | – |
| w3-06 | 2 | blender | ok | joined | pass | pass | FAIL | 0 | 676 | 10.761 | – |
| w3-09 | 0 | blender | ok | joined | pass | pass | ok | 1 | 834 | 14.146 | – |
| w3-09 | 1 | blender | ok | joined | pass | pass | FAIL | 1 | 782 | 12.937 | – |
| w3-09 | 2 | blender | ok | joined | pass | pass | ok | 1 | 708 | 10.83 | – |
| w3-11 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 899 | 16.0 | 5.2.2: line 65: AttributeError: 'Material' object has no attribute 'no_cycles'. Did you mean: 'cycles'? |
| w3-11 | 1 | blender | ok | joined | failed | failed | FAIL | 2 | 870 | 13.852 | 5.2.2: line 24: AttributeError: 'ShaderNodeTexNoise' object has no attribute 'scale' |
| w3-11 | 2 | blender | ok | joined | pass | pass | ok | 0 | 919 | 14.304 | – |
| w3-12 | 0 | blender | ok | joined | pass | pass | ok | 0 | 756 | 13.766 | – |
| w3-12 | 1 | blender | ok, near miss | after_deps | failed | failed | FAIL | 1 | 813 | 13.404 | 5.2.2: line 40: SyntaxError: invalid syntax |
| w3-12 | 2 | blender | ok, near miss | after_deps | failed | failed | FAIL | 1 | 806 | 12.734 | 5.2.2: line 40: SyntaxError: invalid syntax |
| w3-13 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 1375 | 22.51 | 5.2.2: line 65: TypeError: bmesh operators expect a single BMesh positional argument, all other args must be keywords |
| w3-13 | 1 | blender | ok | joined | pass | pass | FAIL | 2 | 1098 | 17.62 | – |
| w3-13 | 2 | blender | ok | joined | failed | failed | FAIL | 2 | 1102 | 17.43 | 5.2.2: line 30: TypeError: bpy_struct: item.attr = val: |
| w3-14 | 0 | blender | ok | joined | failed | failed | FAIL | 3 | 404 | 7.821 | 5.2.2: line 25: AttributeError: 'SceneEEVEE' object has no attribute 'use_bloom' |
| w3-14 | 1 | blender | ok | joined | failed | failed | FAIL | 3 | 392 | 6.451 | 5.2.2: line 31: AttributeError: 'SceneEEVEE' object has no attribute 'use_bloom' |
| w3-14 | 2 | blender | ok | joined | failed | failed | FAIL | 3 | 437 | 6.795 | 5.2.2: line 34: AttributeError: 'SceneEEVEE' object has no attribute 'use_bloom' |
| w3-19 | 0 | blender | ok | joined | failed | failed | FAIL | 4 | 1147 | 19.192 | 5.2.2: line 26: RuntimeError: Error: Node type GeometryNodeInput undefined |
| w3-19 | 1 | blender | ok | joined | failed | failed | FAIL | 4 | 896 | 13.863 | 5.2.2: line 25: RuntimeError: Error: Node type GeometryNodeGroupInput undefined |
| w3-19 | 2 | blender | ok | joined | failed | failed | FAIL | 0 | 919 | 14.259 | 5.2.2: line 25: RuntimeError: Error: Node type GeometryNodeGroupInput undefined |
| w4f-01 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 763 | 13.938 | 5.2.2: line 27: TypeError: bpy_struct: item.attr = val: Object.data expected a Image type, not Mesh |
| w4f-01 | 1 | blender | ok | joined | failed | failed | FAIL | 2 | 635 | 9.845 | 5.2.2: line 33: AttributeError: 'Camera' object has no attribute 'focus_distance' |
| w4f-01 | 2 | blender | ok | joined | failed | failed | FAIL | 2 | 666 | 11.768 | 5.2.2: line 21: TypeError: bpy_struct: item.attr = val: Object.data expected a Image type, not Mesh |
| w4f-02 | 0 | blender | ok | joined | failed | failed | FAIL | 4 | 1176 | 20.472 | 5.2.2: line 35: RuntimeError: Error: Node type ShaderNodeBsdf undefined |
| w4f-02 | 1 | blender | broken | alone | failed | failed | FAIL | 0 | 991 | 16.459 | 5.2.2: line 35: TypeError: BlendDataObjects.new(): required parameter "object_data" not specified |
| w4f-02 | 2 | blender | ok | joined | failed | failed | FAIL | 2 | 1151 | 20.177 | 5.2.2: line 23: UnboundLocalError: cannot access local variable 'bpy' where it is not associated with a value |
| w4f-05 | 0 | python-script | ok | – | – | – | – | – | 848 | 12.167 | – |
| w4f-05 | 1 | python-script | ok | – | – | – | – | – | 975 | 13.353 | missed must_not_match |
| w4f-05 | 2 | python-script | ok | – | – | – | – | – | 806 | 11.685 | – |
| w4f-06 | 0 | files | ok, near miss | – | – | – | – | – | 502 | 7.714 | missed must_mention |
| w4f-06 | 1 | files | ok, near miss | – | – | – | – | – | 482 | 6.675 | – |
| w4f-06 | 2 | files | ok, near miss | – | – | – | – | – | 488 | 6.863 | missed assumed_mentions |
| w4f-08 | 0 | section | ok | – | – | – | – | – | 393 | 8.804 | – |
| w4l-02 | 0 | section | ok | – | – | – | – | – | 716 | 24.038 | missed uses_mentions |
| w4l-04 | 0 | blender | ok, near miss | after_deps | failed | failed | FAIL | 1 | 1171 | 30.439 | 5.2.2: line 339: TypeError: Converting py args to operator properties: enum "PLAIN" not found in ('PLAIN_AXES', 'ARROWS' |
| w4l-04 | 1 | blender | ok | after_deps | failed | failed | FAIL | 0 | 1363 | 24.33 | 5.2.2: line 381: AttributeError: 'Action' object has no attribute 'fcurves' |
| w4l-04 | 2 | blender | ok | after_deps | failed | failed | FAIL | 0 | 1031 | 18.089 | 5.2.2: line 361: AttributeError: 'Action' object has no attribute 'fcurves' |
| w4l-07 | 0 | files | ok | – | – | – | – | – | 753 | 21.741 | – |
| w4l-07 | 1 | files | ok | – | – | – | – | – | 762 | 11.524 | – |
| w4l-07 | 2 | files | ok | – | – | – | – | – | 850 | 13.051 | – |
| w4l-08 | 0 | blender | ok, near miss | after_deps | failed | failed | FAIL | 1 | 870 | 27.571 | 5.2.2: line 150: SyntaxError: positional argument follows keyword argument |
| w4l-08 | 1 | blender | ok, near miss | after_deps | failed | failed | FAIL | 1 | 894 | 17.238 | 5.2.2: line 148: SyntaxError: positional argument follows keyword argument |
| w4l-08 | 2 | blender | ok, near miss | after_deps | failed | failed | FAIL | 1 | 859 | 16.609 | 5.2.2: line 155: SyntaxError: positional argument follows keyword argument |
| w4l-10 | 0 | section | ok | – | – | – | – | – | 676 | 29.735 | missed must_mention |
