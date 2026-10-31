# qwen3:4b-instruct-2507-q4_K_M, contract prompt, on the worker eval (w1.0)

2026-10-30T06:44:53-05:00 · Ollama 0.40.1 · digest `0edcdef34593` · samples 3 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: a worker step's reply content is cut after 6144 tokens and scored as a runaway in content (the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap; every reply, thinking included, is cut after 16384 tokens (the runaway guard; a worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard).

| – | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 (checked) | crash 5.2.2 (all) | no script | assertions | API errors | repaired | expect | runaway | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 102 | 78% | 43% | 90 | 12% | 12% | 12% | 83% | 79% | 0% | 11% | 4.53 | 33% | 38% | 5% (0 thinking, 5 content) | 0% | 923.0 | 138.6 | 7.1615 |
| w2 | 48 | 79% | 17% | 48 | 0% | 0% | 0% | 93% | 88% | 0% | 0% | 7.35 | – | – | 6% (0 thinking, 3 content) | 0% | 1185.5 | 139.14999999999998 | 8.634 |
| w3 | 30 | 87% | 87% | 30 | 33% | 33% | 33% | 63% | 63% | 0% | 30% | 1.17 | 33% | – | 3% (0 thinking, 1 content) | 0% | 688.5 | 137.55 | 5.0865 |
| w4f | 13 | 54% | 38% | 6 | 0% | 0% | 0% | 100% | 83% | 0% | 0% | 2.33 | – | 31% | 8% (0 thinking, 1 content) | 0% | 804 | 141.4 | 5.801 |
| w4l | 11 | 73% | 46% | 6 | 17% | 17% | 17% | 83% | 83% | 0% | 17% | 1.0 | – | 46% | 0% | 0% | 1109 | 115.7 | 11.193 |
| blender | 90 | 79% | 43% | 90 | 12% | 12% | 12% | 83% | 79% | 0% | 11% | 4.53 | 33% | 50% | 6% (0 thinking, 5 content) | 0% | 970.0 | 138.6 | 7.213 |
| files | 6 | 50% | 0% | – | – | – | – | – | – | – | – | – | – | 17% | 0% | 0% | 744.5 | 129.25 | 5.9245 |
| python-script | 3 | 67% | 67% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 792 | 141.4 | 5.711 |
| section | 3 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | 67% | 0% | 0% | 880 | 116.0 | 11.985 |

contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: line): what data generation keeps. Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run (no script: 0) and a runaway (5, of which 4 had no script) count as fails, not as left out. strict: not a runaway; Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows (tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same rule; the probes run there). crash: the check's outcome was failed (a definite crash); "checked" is over the 86 samples Blender checked (the plan's "definite crashes at most 10%"), "all" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a crash. no script: the reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 (no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has. runaway: the runner stopped reading the reply, in content (its content passed the reply cap of 6144 tokens, thinking not counted, or the guard hit while it wrote content) or in thinking (the runaway guard, 16384 tokens with thinking, hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and no think field and has neither limit. cut off: Ollama itself stopped at a length limit. The plan's cut-off bar counts both.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | blender | broken | alone | failed | failed | FAIL | 5 | 915 | 6.869 | 5.2.2: line 39: RuntimeError: Error: Node type ShaderNodeBsdfTransmission undefined |
| w2-01 | 1 | blender | ok, near miss | joined | failed | failed | FAIL | 7 | 954 | 6.908 | 5.2.2: line 36: RuntimeError: Error: Node type ShaderNodeBsdfTransmission undefined |
| w2-01 | 2 | blender | broken | alone | failed | failed | FAIL | 5 | 798 | 5.79 | 5.2.2: line 33: RuntimeError: Error: Node type ShaderNodeBsdfTransmission undefined |
| w2-02 | 0 | blender | ok, near miss | joined | failed | failed | FAIL | 11 | 1006 | 7.556 | 5.2.2: line 32: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-02 | 1 | blender | ok, near miss | alone | failed | failed | FAIL | 1 | 928 | 6.715 | 5.2.2: line 9: SyntaxError: leading zeros in decimal integer literals are not permitted; use an 0o prefix for octal inte |
| w2-02 | 2 | blender | ok, near miss | joined | failed | failed | FAIL | 6 | 822 | 5.953 | 5.2.2: line 35: AttributeError: 'ShaderNodeBsdfPrincipled' object has no attribute 'specular' |
| w2-04 | 0 | blender | ok | joined | failed | failed | FAIL | 5 | 1587 | 11.761 | 5.2.2: line 25: AttributeError: bpy_prop_collection: attribute "clear" not found |
| w2-04 | 1 | blender | ok, near miss | alone | failed | failed | FAIL | 1 | 1614 | 11.752 | 5.2.2: line 53: SyntaxError: invalid syntax. Perhaps you forgot a comma? |
| w2-04 | 2 | blender | ok, near miss | alone | failed | failed | FAIL | 1 | 1129 | 8.166 | 5.2.2: line 56: SyntaxError: invalid syntax. Perhaps you forgot a comma? |
| w2-05 | 0 | blender | ok, near miss | joined | failed | failed | FAIL | 12 | 893 | 6.715 | 5.2.2: line 31: AttributeError: 'ShaderNodeTexNoise' object has no attribute 'scale' |
| w2-05 | 1 | blender | ok | joined | failed | failed | FAIL | 5 | 1934 | 14.109 | 5.2.2: line 31: AttributeError: 'ShaderNodeTexNoise' object has no attribute 'scale' |
| w2-05 | 2 | blender | ok, near miss | joined | failed | failed | FAIL | 4 | 807 | 5.845 | 5.2.2: line 36: AttributeError: 'ShaderNodeTexNoise' object has no attribute 'scale' |
| w2-07 | 0 | blender | ok, near miss | joined | failed | failed | FAIL | 1 | 1242 | 9.259 | 5.2.2: line 25: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-07 | 1 | blender | ok, near miss | joined | failed | failed | FAIL | 3 | 1879 | 13.697 | 5.2.2: line 27: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-07 | 2 | blender | ok, near miss | joined | failed | failed | FAIL | 5 | 1585 | 11.536 | 5.2.2: line 27: AttributeError: bpy_prop_collection: attribute "active" not found |
| w2-08 | 0 | blender | ok, near miss | joined | unsure | unsure | FAIL | 4 | 532 | 4.11 | 5.2.2: line 22: TypeError: bpy_struct: item.attr = val: enum "EEVEE" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH', |
| w2-08 | 1 | blender | ok, near miss | joined | unsure | unsure | FAIL | 4 | 490 | 3.531 | 5.2.2: line 22: TypeError: bpy_struct: item.attr = val: enum "EEVEE" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH', |
| w2-08 | 2 | blender | broken | alone | unsure | unsure | FAIL | 2 | 403 | 2.903 | 5.2.2: line 18: TypeError: bpy_struct: item.attr = val: enum "EEVEE" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH', |
| w2-10 | 0 | blender | broken | alone | failed | failed | FAIL | 4 | 967 | 7.202 | 5.2.2: line 68: NameError: name 'ctx' is not defined |
| w2-10 | 1 | blender | ok, near miss | joined | failed | failed | FAIL | 4 | 983 | 7.121 | 5.2.2: line 21: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-10 | 2 | blender | ok, near miss | joined | failed | failed | FAIL | 3 | 733 | 5.29 | 5.2.2: line 23: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-12 | 0 | blender | ok, near miss | joined | failed | failed | FAIL | 9 | 983 | 7.362 | 5.2.2: line 35: RuntimeError: Error: Node type GeometryNodeInputGeometry undefined |
| w2-12 | 1 | blender | ok | joined | failed | failed | FAIL | 7 | 1354 | 9.841 | 5.2.2: line 31: RuntimeError: Error: Node type GeometryNodeInputGeometry undefined |
| w2-12 | 2 | blender | broken | none | runaway | runaway | – | 127 | 6144 | 47.526 | runaway in content: cut at 6144 tokens |
| w2-13 | 0 | blender | ok | joined | failed | failed | FAIL | 16 | 1612 | 12.019 | 5.2.2: line 46: AttributeError: 'GeometryNodeTree' object has no attribute 'inputs' |
| w2-13 | 1 | blender | ok, near miss | joined | failed | failed | FAIL | 14 | 1372 | 9.949 | 5.2.2: line 34: RuntimeError: internal error setting the array |
| w2-13 | 2 | blender | ok | joined | failed | failed | FAIL | 8 | 1448 | 10.534 | 5.2.2: line 43: TypeError: ObjectModifiers.new(): error with argument 2, "type" -  enum "GEOMETRY_NODES" not found in (' |
| w2-14 | 0 | blender | ok, near miss | joined | failed | failed | FAIL | 14 | 1701 | 12.624 | 5.2.2: line 27: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-14 | 1 | blender | broken | none | runaway | runaway | – | 4 | 6144 | 47.545 | runaway in content: cut at 6144 tokens |
| w2-14 | 2 | blender | broken | alone | failed | failed | FAIL | 18 | 1601 | 11.64 | 5.2.2: line 159: NameError: name 'cone_obj' is not defined |
| w2-16 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 399 | 3.148 | 5.2.2: line 14: TypeError: bpy_struct: item.attr = val: enum "Punchity" not found in ('None', 'AgX - Punchy', 'AgX - Gre |
| w2-16 | 1 | blender | ok, near miss | joined | failed | failed | FAIL | 0 | 298 | 2.149 | 5.2.2: line 18: TypeError: bpy_struct: item.attr = val: enum "Punchy" not found in ('None', 'AgX - Punchy', 'AgX - Greys |
| w2-16 | 2 | blender | ok, near miss | joined | failed | failed | FAIL | 2 | 426 | 3.061 | 5.2.2: line 19: TypeError: bpy_struct: item.attr = val: enum "Punchibility" not found in ('None', 'AgX - Punchy', 'AgX - |
| w2-18 | 0 | blender | ok | joined | failed | failed | FAIL | 13 | 1567 | 11.636 | 5.2.2: line 38: AttributeError: bpy_prop_collection: attribute "new" not found |
| w2-18 | 1 | blender | ok | joined | failed | failed | FAIL | 1 | 1369 | 9.95 | 5.2.2: line 31: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-18 | 2 | blender | ok, near miss | joined | failed | failed | FAIL | 0 | 1046 | 7.575 | 5.2.2: line 64: TypeError: BlendDataLights.new(): error with keyword argument "type" -  enum "area" not found in ('POINT |
| w2-19 | 0 | blender | ok | joined | failed | failed | FAIL | 7 | 1463 | 10.869 | 5.2.2: line 25: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-19 | 1 | blender | broken | none | runaway | runaway | – | 0 | 6144 | 47.485 | runaway in content: cut at 6144 tokens |
| w2-19 | 2 | blender | ok, near miss | joined | failed | failed | FAIL | 8 | 1255 | 9.102 | 5.2.2: line 23: AttributeError: bpy_prop_collection: attribute "clear" not found |
| w2-21 | 0 | blender | ok, near miss | joined | failed | failed | FAIL | 1 | 883 | 6.648 | 5.2.2: line 28: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-21 | 1 | blender | ok, near miss | joined | failed | failed | FAIL | 2 | 1388 | 10.042 | 5.2.2: line 28: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-21 | 2 | blender | ok, near miss | joined | failed | failed | FAIL | 3 | 1312 | 9.512 | 5.2.2: line 29: AttributeError: bpy_prop_collection: attribute "append" not found |
| w2-25 | 0 | blender | ok, near miss | joined | failed | failed | FAIL | 0 | 505 | 3.875 | 5.2.2: line 28: TypeError: bpy_struct: item.attr = val: Object.data expected a Image type, not Camera |
| w2-25 | 1 | blender | ok, near miss | joined | failed | failed | FAIL | 1 | 498 | 3.583 | 5.2.2: line 29: TypeError: bpy_struct: item.attr = val: Object.data expected a Image type, not Camera |
| w2-25 | 2 | blender | ok, near miss | joined | failed | failed | FAIL | 0 | 577 | 4.147 | 5.2.2: line 44: NameError: name 'SETTINGS_s_3' is not defined. Did you mean: 'SETTINGS_s3'? |
| w2-27 | 0 | blender | ok, near miss | alone | failed | failed | FAIL | 1 | 1953 | 14.497 | 5.2.2: line 56: SyntaxError: unterminated string literal (detected at line 56) |
| w2-27 | 1 | blender | broken | alone | failed | failed | FAIL | 0 | 2077 | 15.199 | 5.2.2: line 197: NameError: name 'plane_from' is not defined |
| w2-27 | 2 | blender | ok, near miss | alone | failed | failed | FAIL | 1 | 2654 | 19.532 | 5.2.2: line 95: SyntaxError: invalid syntax |
| w3-01 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 696 | 5.699 | 5.2.2: line 41: AttributeError: 'BevelModifier' object has no attribute 'offset' |
| w3-01 | 1 | blender | ok | joined | pass | pass | ok | 0 | 666 | 4.9 | – |
| w3-01 | 2 | blender | ok | joined | pass | pass | ok | 0 | 918 | 6.758 | – |
| w3-03 | 0 | blender | ok | joined | pass | pass | ok | 0 | 246 | 2.282 | – |
| w3-03 | 1 | blender | ok | joined | pass | pass | ok | 0 | 246 | 1.806 | – |
| w3-03 | 2 | blender | ok | joined | pass | pass | ok | 0 | 246 | 1.822 | – |
| w3-04 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 532 | 4.392 | 5.2.2: line 36: TypeError: bpy_prop_collection.__contains__: expected a string or a tuple of strings |
| w3-04 | 1 | blender | ok | joined | failed | failed | FAIL | 0 | 462 | 3.397 | 5.2.2: line 30: TypeError: bpy_prop_collection.__contains__: expected a string or a tuple of strings |
| w3-04 | 2 | blender | ok | joined | failed | failed | FAIL | 0 | 406 | 2.981 | 5.2.2: line 30: TypeError: bpy_prop_collection.__contains__: expected a string or a tuple of strings |
| w3-06 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 820 | 6.503 | 5.2.2: line 45: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-06 | 1 | blender | broken | alone | failed | failed | FAIL | 3 | 1013 | 7.443 | 5.2.2: line 39: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-06 | 2 | blender | broken | alone | failed | failed | FAIL | 1 | 1210 | 8.881 | 5.2.2: line 47: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-09 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 709 | 5.666 | 5.2.2: line 45: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w3-09 | 1 | blender | ok | joined | failed | failed | FAIL | 2 | 674 | 4.948 | 5.2.2: line 44: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w3-09 | 2 | blender | ok | joined | failed | failed | FAIL | 2 | 714 | 5.155 | 5.2.2: line 41: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w3-11 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 753 | 5.782 | 5.2.2: line 52: TypeError: BlendDataTextures.new(): error with argument 2, "type" -  enum "TEXNOISE" not found in ('NONE |
| w3-11 | 1 | blender | ok | joined | failed | failed | FAIL | 2 | 640 | 4.707 | 5.2.2: line 48: AttributeError: 'ImageTexture' object has no attribute 'scale' |
| w3-11 | 2 | blender | ok | joined | failed | failed | FAIL | 2 | 681 | 5.018 | 5.2.2: line 51: AttributeError: 'NoiseTexture' object has no attribute 'noise_scale' |
| w3-12 | 0 | blender | ok | joined | pass | pass | ok | 0 | 744 | 6.049 | – |
| w3-12 | 1 | blender | broken | after_deps | pass | pass | ok | 0 | 600 | 4.425 | contract: handoff_shape |
| w3-12 | 2 | blender | ok | joined | pass | pass | ok | 0 | 510 | 3.748 | – |
| w3-13 | 0 | blender | ok | joined | failed | failed | FAIL | 3 | 973 | 7.722 | 5.2.2: line 21: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-13 | 1 | blender | ok | joined | failed | failed | FAIL | 3 | 981 | 7.224 | 5.2.2: line 26: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-13 | 2 | blender | ok | joined | failed | failed | FAIL | 3 | 912 | 6.725 | 5.2.2: line 21: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-14 | 0 | blender | ok | joined | failed | failed | FAIL | 3 | 293 | 2.534 | 5.2.2: line 19: AttributeError: 'SceneEEVEE' object has no attribute 'use_bloom' |
| w3-14 | 1 | blender | ok | joined | failed | failed | FAIL | 3 | 293 | 2.156 | 5.2.2: line 23: AttributeError: 'SceneEEVEE' object has no attribute 'use_bloom' |
| w3-14 | 2 | blender | ok | joined | failed | failed | FAIL | 3 | 286 | 2.101 | 5.2.2: line 19: AttributeError: 'SceneEEVEE' object has no attribute 'use_bloom' |
| w3-19 | 0 | blender | broken | alone | runaway | runaway | ok | 0 | 6144 | 48.861 | runaway in content: cut at 6144 tokens |
| w3-19 | 1 | blender | ok | joined | pass | pass | FAIL | 0 | 873 | 6.479 | – |
| w3-19 | 2 | blender | ok | joined | pass | pass | ok | 0 | 996 | 7.306 | – |
| w4f-01 | 0 | blender | ok, near miss | joined | failed | failed | FAIL | 2 | 1050 | 7.875 | 5.2.2: line 41: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w4f-01 | 1 | blender | ok, near miss | joined | failed | failed | FAIL | 2 | 829 | 6.006 | 5.2.2: line 52: AttributeError: bpy_struct: attribute "dof" from "Camera" is read-only |
| w4f-01 | 2 | blender | ok | joined | failed | failed | FAIL | 6 | 1411 | 10.243 | 5.2.2: line 42: TypeError: bpy_struct: item.attr = val: enum "ONLY" not found in ('ROUND', 'OBJECT', 'PROFILE') |
| w4f-02 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 1666 | 12.374 | 5.2.2: line 38: TypeError: Nodes.new(): error with argument 1, "type" -  Function.type expected a string type, not _RNAM |
| w4f-02 | 1 | blender | broken | none | runaway | runaway | – | 0 | 6144 | 47.601 | runaway in content: cut at 6144 tokens |
| w4f-02 | 2 | blender | ok | joined | failed | failed | FAIL | 3 | 1503 | 10.964 | 5.2.2: line 51: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w4f-05 | 0 | python-script | ok | – | – | – | – | – | 792 | 5.801 | missed assumed_mentions, must_not_match |
| w4f-05 | 1 | python-script | ok | – | – | – | – | – | 804 | 5.711 | missed must_not_match |
| w4f-05 | 2 | python-script | broken | – | – | – | – | – | 626 | 4.425 | contract: handoff_missing, syntax_error |
| w4f-06 | 0 | files | broken | – | – | – | – | – | 594 | 4.375 | contract: handoff_missing |
| w4f-06 | 1 | files | broken | – | – | – | – | – | 541 | 3.829 | contract: handoff_missing |
| w4f-06 | 2 | files | broken | – | – | – | – | – | 646 | 4.59 | contract: handoff_missing |
| w4f-08 | 0 | section | ok | – | – | – | – | – | 520 | 3.829 | – |
| w4l-02 | 0 | section | ok | – | – | – | – | – | 880 | 11.985 | – |
| w4l-04 | 0 | blender | ok | after_deps | failed | failed | FAIL | 0 | 1421 | 16.068 | 5.2.2: line 299: TypeError: bpy_prop_collection.__contains__: expected a string or a tuple of strings |
| w4l-04 | 1 | blender | ok | after_deps | pass | pass | ok | 0 | 1405 | 12.193 | – |
| w4l-04 | 2 | blender | ok | after_deps | failed | failed | FAIL | 1 | 1109 | 9.656 | 5.2.2: line 335: AttributeError: type object 'Matrix' has no attribute 'LookAt' |
| w4l-07 | 0 | files | ok, near miss | – | – | – | – | – | 1282 | 14.603 | missed uses_mentions |
| w4l-07 | 1 | files | ok, near miss | – | – | – | – | – | 1065 | 9.169 | missed uses_mentions |
| w4l-07 | 2 | files | ok, near miss | – | – | – | – | – | 843 | 7.259 | – |
| w4l-08 | 0 | blender | broken | after_deps | failed | failed | FAIL | 2 | 762 | 11.193 | 5.2.2: line 140: ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 3 items, not 4 |
| w4l-08 | 1 | blender | broken | after_deps | failed | failed | FAIL | 1 | 1039 | 9.284 | 5.2.2: line 160: ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 3 items, not 4 |
| w4l-08 | 2 | blender | broken | after_deps | failed | failed | FAIL | 2 | 1118 | 10.014 | 5.2.2: line 149: ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 3 items, not 4 |
| w4l-10 | 0 | section | ok | – | – | – | – | – | 1421 | 20.59 | missed must_mention, uses_mentions |
