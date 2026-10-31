# qwen3:14b, contract prompt, on the worker eval (w1.0)

2026-10-30T11:04:31-05:00 · Ollama 0.40.1 · digest `bdbd181c33f2` · samples 3 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: every request sends "think": false (Chimera 0.7.0 sends no think field; the trained worker's template forces thinking off); a worker step's reply content is cut after 6144 tokens and scored as a runaway in content (the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap; every reply, thinking included, is cut after 16384 tokens (the runaway guard; a worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard).

| – | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 (checked) | crash 5.2.2 (all) | no script | assertions | API errors | repaired | expect | runaway | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 102 | 89% | 88% | 90 | 21% | 24% | 21% | 74% | 71% | 0% | 19% | 5.86 | 37% | 42% | 4% (0 thinking, 4 content) | 0% | 592.0 | 60.6 | 10.541 |
| w2 | 48 | 79% | 79% | 48 | 17% | 17% | 17% | 75% | 69% | 0% | 12% | 10.0 | – | – | 8% (0 thinking, 4 content) | 0% | 681.5 | 60.8 | 11.453 |
| w3 | 30 | 100% | 100% | 30 | 37% | 47% | 37% | 63% | 63% | 0% | 37% | 1.1 | 37% | – | 0% | 0% | 508.0 | 60.55 | 8.57 |
| w4f | 13 | 100% | 92% | 6 | 0% | 0% | 0% | 100% | 100% | 0% | 0% | 1.17 | – | 23% | 0% | 0% | 533 | 61.1 | 9.224 |
| w4l | 11 | 91% | 91% | 6 | 0% | 0% | 0% | 100% | 100% | 0% | 0% | 1.17 | – | 64% | 0% | 0% | 600 | 54.4 | 17.414 |
| blender | 90 | 89% | 88% | 90 | 21% | 24% | 21% | 74% | 71% | 0% | 19% | 5.86 | 37% | 42% | 4% (0 thinking, 4 content) | 0% | 600.0 | 60.6 | 10.599 |
| files | 6 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | 50% | 0% | 0% | 520.5 | 58.099999999999994 | 9.107 |
| python-script | 3 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 601 | 61.3 | 9.828 |
| section | 3 | 67% | 67% | – | – | – | – | – | – | – | – | – | – | 67% | 0% | 0% | 540 | 54.5 | 21.481 |

contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: line): what data generation keeps. Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run (no script: 0) and a runaway (4, of which 4 had no script) count as fails, not as left out. strict: not a runaway; Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows (tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same rule; the probes run there). crash: the check's outcome was failed (a definite crash); "checked" is over the 86 samples Blender checked (the plan's "definite crashes at most 10%"), "all" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a crash. no script: the reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 (no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has. runaway: the runner stopped reading the reply, in content (its content passed the reply cap of 6144 tokens, thinking not counted, or the guard hit while it wrote content) or in thinking (the runaway guard, 16384 tokens with thinking, hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and no think field and has neither limit. cut off: Ollama itself stopped at a length limit. The plan's cut-off bar counts both.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 540 | 9.952 | 5.2.2: line 4: ImportError: cannot import name 'ImportAction' from 'bpy_extras.io_utils' (/Applications/Blender 3.app/Co |
| w2-01 | 1 | blender | broken | none | runaway | runaway | – | 1 | 6144 | 106.03 | runaway in content: cut at 6144 tokens |
| w2-01 | 2 | blender | ok | joined | failed | failed | FAIL | 1 | 670 | 11.11 | 5.2.2: line 4: ImportError: cannot import name 'ImportAction' from 'bpy_extras.io_utils' (/Applications/Blender 3.app/Co |
| w2-02 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 648 | 11.55 | 5.2.2: line 28: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-02 | 1 | blender | ok | joined | failed | failed | FAIL | 2 | 677 | 11.16 | 5.2.2: line 32: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-02 | 2 | blender | ok | joined | failed | failed | FAIL | 2 | 662 | 10.907 | 5.2.2: line 31: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-04 | 0 | blender | ok | joined | failed | failed | FAIL | 4 | 958 | 16.63 | 5.2.2: line 65: NameError: name 'cos' is not defined |
| w2-04 | 1 | blender | ok | joined | failed | failed | FAIL | 8 | 963 | 15.919 | 5.2.2: line 33: AttributeError: 'Curve' object has no attribute 'use_fill' |
| w2-04 | 2 | blender | ok | joined | failed | failed | FAIL | 2 | 999 | 16.495 | 5.2.2: line 71: NameError: name 'cos' is not defined |
| w2-05 | 0 | blender | ok | joined | failed | failed | FAIL | 3 | 739 | 12.979 | 5.2.2: line 38: RuntimeError: Error: Node type ShaderNodeColorRamp undefined |
| w2-05 | 1 | blender | ok | joined | failed | failed | FAIL | 4 | 725 | 11.954 | 5.2.2: line 4: ImportError: cannot import name 'find_node_tree' from 'bpy_extras.node_utils' (/Applications/Blender 3.ap |
| w2-05 | 2 | blender | ok | joined | failed | failed | FAIL | 3 | 682 | 11.242 | 5.2.2: line 4: ImportError: cannot import name 'ShaderNodeTexImage' from 'bpy_extras.node_shader_utils' (/Applications/B |
| w2-07 | 0 | blender | broken | none | runaway | runaway | – | 361 | 6144 | 106.183 | runaway in content: cut at 6144 tokens |
| w2-07 | 1 | blender | ok | joined | pass | pass | ok | 0 | 643 | 10.657 | – |
| w2-07 | 2 | blender | ok | joined | failed | failed | FAIL | 2 | 903 | 14.907 | 5.2.2: line 45: TypeError: CurveSplines.new(): error with argument 1, "type" -  enum "PATH" not found in ('POLY', 'BEZIE |
| w2-08 | 0 | blender | ok | joined | unsure | unsure | FAIL | 2 | 260 | 5.168 | 5.2.2: line 21: TypeError: bpy_struct: item.attr = val: enum "EEVEE" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH', |
| w2-08 | 1 | blender | ok | joined | unsure | unsure | FAIL | 2 | 248 | 4.085 | 5.2.2: line 17: TypeError: bpy_struct: item.attr = val: enum "EEVEE" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH', |
| w2-08 | 2 | blender | ok | joined | unsure | unsure | FAIL | 2 | 262 | 4.316 | 5.2.2: line 18: TypeError: bpy_struct: item.attr = val: enum "EEVEE" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH', |
| w2-10 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 470 | 8.52 | 5.2.2: line 49: SyntaxError: invalid syntax |
| w2-10 | 1 | blender | ok | joined | failed | failed | FAIL | 3 | 434 | 7.131 | 5.2.2: line 20: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-10 | 2 | blender | ok | joined | failed | failed | FAIL | 3 | 409 | 6.73 | 5.2.2: line 20: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-12 | 0 | blender | ok | joined | failed | failed | FAIL | 10 | 925 | 16.142 | 5.2.2: line 40: TypeError: bpy_struct: item.attr = val: enum "ENDPOINTS" not found in ('OFFSET', 'END_POINTS') |
| w2-12 | 1 | blender | broken | alone | failed | failed | FAIL | 1 | 5566 | 95.004 | 5.2.2: line 766: SyntaxError: invalid syntax |
| w2-12 | 2 | blender | broken | none | runaway | runaway | – | 1 | 6144 | 105.661 | runaway in content: cut at 6144 tokens |
| w2-13 | 0 | blender | broken | alone | failed | failed | FAIL | 15 | 966 | 16.885 | 5.2.2: line 21: TypeError: bpy_struct: item.attr = val: enum "SHADING_SOLID" not found in ('BOUNDS', 'WIRE', 'SOLID', 'T |
| w2-13 | 1 | blender | ok | joined | failed | failed | FAIL | 9 | 1261 | 20.972 | 5.2.2: line 48: AttributeError: 'GeometryNodeTree' object has no attribute 'inputs' |
| w2-13 | 2 | blender | broken | alone | failed | failed | FAIL | 8 | 818 | 13.606 | 5.2.2: line 56: AttributeError: 'GeometryNodeTree' object has no attribute 'inputs' |
| w2-14 | 0 | blender | ok | joined | failed | failed | FAIL | 4 | 996 | 17.302 | 5.2.2: line 66: RuntimeError: Error: Node type GeometryNodePointsOnGrid undefined |
| w2-14 | 1 | blender | ok | joined | failed | failed | FAIL | 2 | 977 | 16.25 | 5.2.2: line 49: TypeError: Converting py args to operator properties:: keyword "segments" unrecognized |
| w2-14 | 2 | blender | broken | none | runaway | runaway | – | 1 | 6144 | 106.511 | runaway in content: cut at 6144 tokens |
| w2-16 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 178 | 3.963 | 5.2.2: line 20: TypeError: bpy_struct: item.attr = val: enum "Punchy" not found in ('None', 'AgX - Punchy', 'AgX - Greys |
| w2-16 | 1 | blender | ok | joined | failed | failed | FAIL | 0 | 177 | 2.933 | 5.2.2: line 19: TypeError: bpy_struct: item.attr = val: enum "Punchy" not found in ('None', 'AgX - Punchy', 'AgX - Greys |
| w2-16 | 2 | blender | ok | joined | failed | failed | FAIL | 0 | 192 | 3.174 | 5.2.2: line 22: TypeError: bpy_struct: item.attr = val: enum "Punchy" not found in ('None', 'AgX - Punchy', 'AgX - Greys |
| w2-18 | 0 | blender | ok | joined | pass | pass | FAIL | 0 | 703 | 12.564 | – |
| w2-18 | 1 | blender | ok | joined | failed | failed | FAIL | 3 | 729 | 12.122 | 5.2.2: line 28: AttributeError: 'AreaLight' object has no attribute 'distance' |
| w2-18 | 2 | blender | ok | joined | failed | failed | FAIL | 6 | 984 | 16.384 | 5.2.2: line 36: RuntimeError: Error: Node type ShaderNodeLight undefined |
| w2-19 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 629 | 11.356 | 5.2.2: line 54: AttributeError: 'Action' object has no attribute 'fcurves' |
| w2-19 | 1 | blender | ok | joined | failed | failed | FAIL | 1 | 527 | 8.743 | 5.2.2: line 46: AttributeError: 'Action' object has no attribute 'fcurves' |
| w2-19 | 2 | blender | broken | alone | failed | failed | FAIL | 1 | 594 | 9.855 | 5.2.2: line 51: AttributeError: 'Action' object has no attribute 'fcurves' |
| w2-21 | 0 | blender | ok | joined | pass | pass | ok | 0 | 590 | 10.541 | – |
| w2-21 | 1 | blender | ok | joined | pass | pass | ok | 0 | 635 | 10.536 | – |
| w2-21 | 2 | blender | ok | joined | pass | pass | FAIL | 0 | 681 | 11.306 | – |
| w2-25 | 0 | blender | ok | joined | pass | pass | ok | 0 | 298 | 5.762 | – |
| w2-25 | 1 | blender | ok | joined | pass | pass | ok | 0 | 286 | 4.726 | – |
| w2-25 | 2 | blender | ok | joined | pass | pass | ok | 0 | 281 | 4.653 | – |
| w2-27 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 1561 | 26.867 | 5.2.2: line 62: AttributeError: bpy_struct: attribute "loop_total" from "MeshPolygon" is read-only |
| w2-27 | 1 | blender | broken | alone | failed | failed | FAIL | 3 | 1253 | 20.858 | 5.2.2: line 64: AttributeError: 'NoiseTexture' object has no attribute 'noise_type' |
| w2-27 | 2 | blender | ok | joined | failed | failed | FAIL | 4 | 1039 | 17.268 | 5.2.2: line 39: AttributeError: 'SubsurfModifier' object has no attribute 'use_subdivision_diamond' |
| w3-01 | 0 | blender | ok | joined | pass | pass | ok | 0 | 523 | 10.438 | – |
| w3-01 | 1 | blender | ok | joined | pass | pass | ok | 0 | 512 | 8.566 | – |
| w3-01 | 2 | blender | ok | joined | failed | failed | FAIL | 1 | 521 | 8.716 | 5.2.2: line 27: AttributeError: 'BevelModifier' object has no attribute 'offset' |
| w3-03 | 0 | blender | ok | joined | pass | pass | ok | 0 | 246 | 5.497 | – |
| w3-03 | 1 | blender | ok | joined | pass | pass | ok | 0 | 246 | 4.085 | – |
| w3-03 | 2 | blender | ok | joined | pass | pass | ok | 0 | 246 | 4.09 | – |
| w3-04 | 0 | blender | ok | joined | pass | pass | ok | 0 | 404 | 8.259 | – |
| w3-04 | 1 | blender | ok | joined | pass | pass | ok | 0 | 404 | 6.734 | – |
| w3-04 | 2 | blender | ok | joined | pass | pass | ok | 0 | 391 | 6.497 | – |
| w3-06 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 515 | 10.082 | 5.2.2: line 31: AttributeError: 'Mesh' object has no attribute 'use_auto_smooth' |
| w3-06 | 1 | blender | ok | joined | failed | failed | FAIL | 1 | 500 | 8.311 | 5.2.2: line 32: AttributeError: 'Mesh' object has no attribute 'auto_smooth_angle' |
| w3-06 | 2 | blender | ok | joined | failed | failed | FAIL | 1 | 516 | 8.574 | 5.2.2: line 32: AttributeError: 'Mesh' object has no attribute 'auto_smooth_angle' |
| w3-09 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 431 | 8.62 | 5.2.2: line 21: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w3-09 | 1 | blender | ok | joined | failed | failed | FAIL | 1 | 433 | 7.188 | 5.2.2: line 21: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w3-09 | 2 | blender | ok | joined | failed | failed | FAIL | 1 | 435 | 7.218 | 5.2.2: line 29: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w3-11 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 627 | 11.242 | 5.2.2: line 21: AttributeError: 'tuple' object has no attribute 'new' |
| w3-11 | 1 | blender | ok | joined | failed | failed | FAIL | 1 | 606 | 10.083 | 5.2.2: line 21: AttributeError: 'NodeSocketShader' object has no attribute 'default_value' |
| w3-11 | 2 | blender | ok | joined | failed | failed | FAIL | 1 | 617 | 10.267 | 5.2.2: line 22: AttributeError: 'tuple' object has no attribute 'new' |
| w3-12 | 0 | blender | ok | joined | pass | pass | ok | 0 | 589 | 11.607 | – |
| w3-12 | 1 | blender | ok | joined | pass | pass | ok | 0 | 311 | 5.189 | – |
| w3-12 | 2 | blender | ok | joined | pass | pass | ok | 0 | 504 | 8.351 | – |
| w3-13 | 0 | blender | ok | joined | failed | failed | FAIL | 3 | 840 | 15.836 | 5.2.2: line 22: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-13 | 1 | blender | ok | joined | failed | failed | FAIL | 3 | 775 | 12.933 | 5.2.2: line 20: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-13 | 2 | blender | ok | joined | failed | failed | FAIL | 3 | 787 | 13.152 | 5.2.2: line 20: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-14 | 0 | blender | ok | joined | failed | failed | FAIL | 4 | 233 | 5.128 | 5.2.2: line 17: AttributeError: 'SceneEEVEE' object has no attribute 'use_ray_tracing'. Did you mean: 'use_raytracing'? |
| w3-14 | 1 | blender | ok | joined | failed | failed | FAIL | 4 | 240 | 3.986 | 5.2.2: line 17: AttributeError: 'SceneEEVEE' object has no attribute 'use_ray_tracing'. Did you mean: 'use_raytracing'? |
| w3-14 | 2 | blender | ok | joined | failed | failed | FAIL | 4 | 241 | 4.007 | 5.2.2: line 17: AttributeError: 'SceneEEVEE' object has no attribute 'use_ray_tracing'. Did you mean: 'use_raytracing'? |
| w3-19 | 0 | blender | ok | joined | failed | pass | FAIL | 0 | 565 | 11.004 | 5.2.2: line 39: TypeError: bpy_struct[key] = val: id properties not supported for this type |
| w3-19 | 1 | blender | ok | joined | failed | pass | FAIL | 0 | 548 | 9.133 | 5.2.2: line 38: TypeError: bpy_struct[key] = val: id properties not supported for this type |
| w3-19 | 2 | blender | ok | joined | failed | pass | FAIL | 0 | 548 | 9.116 | 5.2.2: line 38: TypeError: bpy_struct[key] = val: id properties not supported for this type |
| w4f-01 | 0 | blender | ok | joined | failed | failed | FAIL | 3 | 655 | 11.72 | 5.2.2: line 40: AttributeError: 'Camera' object has no attribute 'sensor_size'. Did you mean: 'sensor_fit'? |
| w4f-01 | 1 | blender | ok, near miss | joined | failed | failed | FAIL | 1 | 461 | 7.594 | 5.2.2: line 35: AttributeError: 'CameraDOFSettings' object has no attribute 'aperture' |
| w4f-01 | 2 | blender | ok | joined | failed | failed | FAIL | 0 | 502 | 8.269 | 5.2.2: line 36: AttributeError: 'CameraDOFSettings' object has no attribute 'aperture_f_number' |
| w4f-02 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 890 | 15.582 | 5.2.2: line 37: AttributeError: 'DecimateModifier' object has no attribute 'use_collapse' |
| w4f-02 | 1 | blender | ok | joined | failed | failed | FAIL | 1 | 1017 | 16.813 | 5.2.2: line 29: TypeError: bpy_struct: item.attr = val: enum "SHADING_WIRE" not found in ('BOUNDS', 'WIRE', 'SOLID', 'TE |
| w4f-02 | 2 | blender | ok | joined | failed | failed | FAIL | 0 | 897 | 14.81 | 5.2.2: line 36: RuntimeError: internal error setting the array |
| w4f-05 | 0 | python-script | ok | – | – | – | – | – | 533 | 9.224 | missed assumed_mentions, must_not_match |
| w4f-05 | 1 | python-script | ok | – | – | – | – | – | 614 | 10.075 | missed assumed_mentions, must_not_match |
| w4f-05 | 2 | python-script | ok | – | – | – | – | – | 601 | 9.828 | missed assumed_mentions, must_not_match |
| w4f-06 | 0 | files | ok | – | – | – | – | – | 325 | 5.83 | missed must_mention, assumed_mentions |
| w4f-06 | 1 | files | ok | – | – | – | – | – | 441 | 7.208 | missed must_mention, assumed_mentions |
| w4f-06 | 2 | files | ok | – | – | – | – | – | 438 | 7.158 | missed must_mention |
| w4f-08 | 0 | section | ok | – | – | – | – | – | 404 | 7.088 | – |
| w4l-02 | 0 | section | ok | – | – | – | – | – | 554 | 21.481 | – |
| w4l-04 | 0 | blender | ok | after_deps | failed | failed | FAIL | 0 | 776 | 24.812 | 5.2.2: line 355: AttributeError: 'Action' object has no attribute 'fcurves' |
| w4l-04 | 1 | blender | ok | after_deps | failed | failed | FAIL | 0 | 944 | 17.414 | 5.2.2: line 364: AttributeError: 'Action' object has no attribute 'fcurves' |
| w4l-04 | 2 | blender | ok | after_deps | failed | failed | FAIL | 0 | 780 | 14.4 | 5.2.2: line 328: NameError: name 'cos' is not defined |
| w4l-07 | 0 | files | ok | – | – | – | – | – | 656 | 21.961 | – |
| w4l-07 | 1 | files | ok | – | – | – | – | – | 600 | 11.006 | – |
| w4l-07 | 2 | files | ok | – | – | – | – | – | 607 | 11.129 | – |
| w4l-08 | 0 | blender | ok | after_deps | failed | failed | FAIL | 3 | 413 | 20.112 | 5.2.2: line 134: ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 3 items, not 4 |
| w4l-08 | 1 | blender | ok | after_deps | failed | failed | FAIL | 4 | 562 | 10.541 | 5.2.2: line 134: ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 3 items, not 4 |
| w4l-08 | 2 | blender | ok | after_deps | failed | failed | FAIL | 0 | 482 | 9.038 | 5.2.2: line 134: ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 3 items, not 4 |
| w4l-10 | 0 | section | broken | – | – | – | – | – | 540 | 28.668 | contract: handoff_missing, no_heading |
