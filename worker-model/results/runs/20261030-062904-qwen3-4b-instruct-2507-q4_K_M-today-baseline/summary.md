# qwen3:4b-instruct-2507-q4_K_M, today prompt, on the worker eval (w1.0)

2026-10-30T06:29:04-05:00 · Ollama 0.40.1 · digest `0edcdef34593` · samples 3 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: repair cases (W3) under today's prompt get the contract's repair part appended (Chimera 0.7.0 has no step repair); a worker step's reply content is cut after 6144 tokens and scored as a runaway in content (the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap; every reply, thinking included, is cut after 16384 tokens (the runaway guard; a worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard).

| – | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 (checked) | crash 5.2.2 (all) | no script | assertions | API errors | repaired | expect | runaway | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 102 | 0% | 0% | 90 | 13% | 13% | 13% | 75% | 70% | 3% | 7% | 3.07 | 27% | 12% | 3% (0 thinking, 3 content) | 0% | 629.0 | 140.75 | 4.7125 |
| w2 | 48 | 0% | 0% | 48 | 4% | 4% | 4% | 74% | 67% | 6% | 2% | 3.69 | – | – | 4% (0 thinking, 2 content) | 0% | 786.0 | 141.25 | 5.641500000000001 |
| w3 | 30 | 0% | 0% | 30 | 27% | 27% | 27% | 73% | 73% | 0% | 17% | 1.0 | 27% | – | 0% | 0% | 506.0 | 140.05 | 3.7960000000000003 |
| w4f | 13 | 0% | 0% | 6 | 0% | 0% | 0% | 100% | 100% | 0% | 0% | 10.0 | – | 0% | 0% | 0% | 612 | 142.9 | 4.304 |
| w4l | 11 | 0% | 0% | 6 | 33% | 33% | 33% | 60% | 50% | 0% | 0% | 1.5 | – | 27% | 9% (0 thinking, 1 content) | 0% | 664 | 118.2 | 7.626 |
| blender | 90 | 0% | 0% | 90 | 13% | 13% | 13% | 75% | 70% | 3% | 7% | 3.07 | 27% | 25% | 3% (0 thinking, 3 content) | 0% | 638.5 | 140.64999999999998 | 4.745 |
| files | 6 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 566.0 | 132.7 | 4.3315 |
| python-script | 3 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 631 | 142.9 | 4.451 |
| section | 3 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 920 | 117.0 | 11.958 |

contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: line): what data generation keeps. Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run (no script: 3) and a runaway (3, of which 3 had no script) count as fails, not as left out. strict: not a runaway; Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows (tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same rule; the probes run there). crash: the check's outcome was failed (a definite crash); "checked" is over the 84 samples Blender checked (the plan's "definite crashes at most 10%"), "all" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a crash. no script: the reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 (no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has. runaway: the runner stopped reading the reply, in content (its content passed the reply cap of 6144 tokens, thinking not counted, or the guard hit while it wrote content) or in thinking (the runaway guard, 16384 tokens with thinking, hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and no think field and has neither limit. cut off: Ollama itself stopped at a length limit. The plan's cut-off bar counts both.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | blender | broken | alone | failed | failed | FAIL | 7 | 655 | 4.74 | 5.2.2: line 24: KeyError: 'bpy_prop_collection[key]: key "Ior" not found' |
| w2-01 | 1 | blender | broken | alone | failed | failed | FAIL | 3 | 695 | 4.93 | 5.2.2: line 25: KeyError: 'bpy_prop_collection[key]: key "Ior" not found' |
| w2-01 | 2 | blender | broken | alone | failed | failed | FAIL | 5 | 546 | 3.912 | 5.2.2: line 23: RuntimeError: Error: Node type ShaderNodeBsdfTransmission undefined |
| w2-02 | 0 | blender | broken | alone | failed | failed | FAIL | 4 | 627 | 4.544 | 5.2.2: line 31: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-02 | 1 | blender | broken | alone | failed | failed | FAIL | 4 | 648 | 4.639 | 5.2.2: line 22: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-02 | 2 | blender | broken | alone | failed | failed | FAIL | 4 | 545 | 3.884 | 5.2.2: line 22: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-04 | 0 | blender | broken | alone | failed | failed | FAIL | 5 | 3260 | 24.433 | 5.2.2: line 13: TypeError: bpy_struct: item.attr = val: enum "NONE" not found in ('FULL', 'BACK', 'FRONT', 'HALF') |
| w2-04 | 1 | blender | broken | alone | failed | failed | FAIL | 9 | 2068 | 15.082 | 5.2.2: line 31: AttributeError: 'Curve' object has no attribute 'points' |
| w2-04 | 2 | blender | broken | none | runaway | runaway | – | 0 | 6144 | 48.403 | runaway in content: cut at 6144 tokens |
| w2-05 | 0 | blender | broken | alone | failed | failed | FAIL | 7 | 530 | 4.024 | 5.2.2: line 15: AttributeError: 'ShaderNodeTexNoise' object has no attribute 'scale' |
| w2-05 | 1 | blender | broken | alone | failed | failed | FAIL | 4 | 624 | 4.442 | 5.2.2: line 15: AttributeError: 'ShaderNodeTexNoise' object has no attribute 'scale' |
| w2-05 | 2 | blender | broken | alone | failed | failed | FAIL | 5 | 784 | 5.649 | 5.2.2: line 15: AttributeError: 'ShaderNodeTexNoise' object has no attribute 'scale' |
| w2-07 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 1193 | 8.625 | 5.2.2: line 70: AttributeError: 'BevelModifier' object has no attribute 'offset' |
| w2-07 | 1 | blender | broken | alone | failed | failed | FAIL | 6 | 1792 | 13.007 | 5.2.2: line 16: AttributeError: bpy_prop_collection: attribute "link" not found |
| w2-07 | 2 | blender | broken | alone | failed | failed | FAIL | 5 | 1939 | 14.103 | 5.2.2: line 26: AttributeError: 'Mesh' object has no attribute 'from_mesh' |
| w2-08 | 0 | blender | broken | alone | unsure | unsure | FAIL | 3 | 569 | 4.169 | 5.2.2: line 4: TypeError: bpy_struct: item.attr = val: enum "EEVEE" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH',  |
| w2-08 | 1 | blender | broken | alone | unsure | unsure | FAIL | 5 | 250 | 1.795 | 5.2.2: line 4: TypeError: bpy_struct: item.attr = val: enum "EEVEE" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH',  |
| w2-08 | 2 | blender | broken | alone | unsure | unsure | FAIL | 5 | 321 | 2.287 | 5.2.2: line 4: TypeError: bpy_struct: item.attr = val: enum "EEVEE" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH',  |
| w2-10 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 437 | 3.21 | 5.2.2: line 7: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-10 | 1 | blender | broken | alone | failed | failed | FAIL | 3 | 454 | 3.222 | 5.2.2: line 7: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-10 | 2 | blender | broken | alone | failed | failed | FAIL | 4 | 460 | 3.274 | 5.2.2: line 7: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-12 | 0 | blender | broken | alone | failed | failed | FAIL | 16 | 1104 | 8.12 | 5.2.2: line 19: AttributeError: 'GeometryNodeTree' object has no attribute 'inputs' |
| w2-12 | 1 | blender | broken | alone | failed | failed | FAIL | 8 | 989 | 7.071 | 5.2.2: line 13: RuntimeError: Error: Node type GeometryNodeGroupInput undefined |
| w2-12 | 2 | blender | broken | alone | failed | failed | FAIL | 9 | 1589 | 11.649 | 5.2.2: line 17: RuntimeError: Error: Node type GeometryNodeGroupInput undefined |
| w2-13 | 0 | blender | broken | alone | unsure | unsure | FAIL | 12 | 1262 | 9.272 | 5.2.2: line 4: RuntimeError: Error: 'Meshes/chimera_ground_plane.blend': nothing indicated |
| w2-13 | 1 | blender | broken | alone | failed | failed | FAIL | 7 | 868 | 6.236 | 5.2.2: line 9: TypeError: ObjectModifiers.new(): error with keyword argument "type" -  enum "GEOMETRY_NODES" not found i |
| w2-13 | 2 | blender | broken | alone | failed | failed | FAIL | 4 | 975 | 6.986 | 5.2.2: line 35: RuntimeError: Error: Node type GeometryNodeInputGeometry undefined |
| w2-14 | 0 | blender | broken | alone | unsure | unsure | FAIL | 1 | 1076 | 7.839 | 5.2.2: line 5: RuntimeError: Error: 'tree_cone': nothing indicated |
| w2-14 | 1 | blender | broken | alone | failed | failed | FAIL | 6 | 1525 | 11.035 | 5.2.2: line 5: TypeError: Converting py args to operator properties:: keyword "use_homefile" unrecognized |
| w2-14 | 2 | blender | broken | alone | unsure | unsure | FAIL | 0 | 968 | 6.93 | 5.2.2: line 5: RuntimeError: Error: '/Users/username/Documents/Blender/GeometryNodes/TreeScatter': nothing indicated |
| w2-16 | 0 | blender | broken | none | – | – | – | 1 | 62 | 0.582 | no script: not joined: s3: handoff_missing: no ```handoff block at the end; s3: top_level_code: top-level assign isn't a |
| w2-16 | 1 | blender | broken | none | – | – | – | 1 | 59 | 0.416 | no script: not joined: s3: handoff_missing: no ```handoff block at the end; s3: top_level_code: top-level assign isn't a |
| w2-16 | 2 | blender | broken | none | – | – | – | 4 | 71 | 0.506 | no script: not joined: s3: handoff_missing: no ```handoff block at the end; s3: top_level_code: top-level assign isn't a |
| w2-18 | 0 | blender | broken | alone | unsure | unsure | FAIL | 0 | 1676 | 12.15 | 5.2.2: line 57: KeyError: 'bpy_prop_collection[key]: key "Chimera_Project" not found' |
| w2-18 | 1 | blender | broken | alone | pass | pass | FAIL | 0 | 777 | 5.529 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-18 | 2 | blender | broken | alone | failed | failed | FAIL | 1 | 834 | 5.938 | 5.2.2: line 7: AttributeError: bpy_prop_collection: attribute "clear" not found |
| w2-19 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 775 | 5.634 | 5.2.2: line 26: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-19 | 1 | blender | broken | alone | failed | failed | FAIL | 1 | 1247 | 8.915 | 5.2.2: line 36: SyntaxError: cannot assign to expression here. Maybe you meant '==' instead of '='? |
| w2-19 | 2 | blender | broken | alone | unsure | unsure | FAIL | 1 | 788 | 5.632 | 5.2.2: line 41: AttributeError: 'NoneType' object has no attribute 'action' |
| w2-21 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 1159 | 8.383 | 5.2.2: line 42: AttributeError: 'Context' object has no attribute 'bm' |
| w2-21 | 1 | blender | broken | alone | failed | failed | FAIL | 2 | 769 | 5.494 | 5.2.2: line 10: AttributeError: 'Scene' object has no attribute 'user_data'. Did you mean: 'asset_data'? |
| w2-21 | 2 | blender | broken | none | runaway | runaway | – | 1 | 6144 | 46.893 | runaway in content: cut at 6144 tokens |
| w2-25 | 0 | blender | broken | alone | failed | failed | FAIL | 0 | 326 | 2.456 | 5.2.2: line 14: AttributeError: bpy_struct: attribute "type" from "Object" is read-only |
| w2-25 | 1 | blender | broken | alone | pass | pass | ok | 0 | 176 | 1.267 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-25 | 2 | blender | broken | alone | failed | failed | FAIL | 1 | 182 | 1.31 | 5.2.2: line 5: RuntimeError: Error: ID type 'OBJECT' is not valid for an object |
| w2-27 | 0 | blender | broken | alone | unsure | unsure | FAIL | 0 | 1564 | 11.31 | 5.2.2: line 122: ZeroDivisionError: float division by zero |
| w2-27 | 1 | blender | broken | alone | failed | failed | FAIL | 1 | 1046 | 7.491 | 5.2.2: line 15: SyntaxError: invalid syntax |
| w2-27 | 2 | blender | broken | alone | failed | failed | FAIL | 0 | 1952 | 14.109 | 5.2.2: line 91: ValueError: bpy_struct: item.attr = val: Image.pixels: array length cannot be changed to 1 (expected 4) |
| w3-01 | 0 | blender | broken | alone | failed | failed | FAIL | 0 | 507 | 3.989 | 5.2.2: line 9: NameError: name 'bmesh' is not defined. Did you mean: 'mesh'? |
| w3-01 | 1 | blender | broken | alone | failed | failed | FAIL | 0 | 505 | 3.669 | 5.2.2: line 9: NameError: name 'bmesh' is not defined. Did you mean: 'mesh'? |
| w3-01 | 2 | blender | broken | alone | failed | failed | FAIL | 0 | 519 | 3.766 | 5.2.2: line 9: NameError: name 'bmesh' is not defined. Did you mean: 'mesh'? |
| w3-03 | 0 | blender | broken | alone | pass | pass | ok | 0 | 231 | 1.89 | contract: handoff_missing |
| w3-03 | 1 | blender | broken | alone | failed | failed | FAIL | 0 | 215 | 1.553 | 5.2.2: line 3: NameError: name 'tqdm' is not defined |
| w3-03 | 2 | blender | broken | alone | pass | pass | ok | 0 | 261 | 1.871 | contract: handoff_missing |
| w3-04 | 0 | blender | broken | alone | failed | failed | FAIL | 0 | 332 | 2.654 | 5.2.2: line 4: NameError: name 'than' is not defined |
| w3-04 | 1 | blender | broken | alone | failed | failed | FAIL | 0 | 330 | 2.389 | 5.2.2: line 4: NameError: name 'than' is not defined |
| w3-04 | 2 | blender | broken | alone | failed | failed | FAIL | 0 | 332 | 2.407 | 5.2.2: line 4: NameError: name 'than' is not defined |
| w3-06 | 0 | blender | broken | alone | failed | failed | FAIL | 0 | 613 | 4.75 | 5.2.2: line 46: KeyError: 'bpy_prop_collection[key]: key "Shader Node Output" not found' |
| w3-06 | 1 | blender | broken | alone | failed | failed | FAIL | 1 | 463 | 3.354 | 5.2.2: line 37: RuntimeError: Error: Node type ShaderNodePrincipledBSDF undefined |
| w3-06 | 2 | blender | broken | alone | failed | failed | FAIL | 0 | 592 | 4.276 | 5.2.2: line 44: KeyError: 'bpy_prop_collection[key]: key "Material Output" not found' |
| w3-09 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 604 | 4.602 | 5.2.2: line 9: AttributeError: bpy_struct: attribute "node_tree" from "Material" is read-only |
| w3-09 | 1 | blender | broken | alone | failed | failed | FAIL | 1 | 575 | 4.15 | 5.2.2: line 9: AttributeError: bpy_struct: attribute "node_tree" from "Material" is read-only |
| w3-09 | 2 | blender | broken | alone | failed | failed | FAIL | 2 | 498 | 3.574 | 5.2.2: line 27: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w3-11 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 642 | 4.996 | 5.2.2: line 30: NameError: name 'bmesh' is not defined |
| w3-11 | 1 | blender | broken | alone | failed | failed | FAIL | 2 | 555 | 4.004 | 5.2.2: line 24: NameError: name 'bmesh' is not defined |
| w3-11 | 2 | blender | broken | alone | failed | failed | FAIL | 1 | 635 | 4.617 | 5.2.2: line 24: NameError: name 'bmesh' is not defined |
| w3-12 | 0 | blender | broken | after_deps | pass | pass | ok | 0 | 481 | 3.826 | contract: handoff_missing |
| w3-12 | 1 | blender | broken | after_deps | pass | pass | ok | 0 | 457 | 3.327 | contract: handoff_missing |
| w3-12 | 2 | blender | broken | after_deps | pass | pass | ok | 0 | 458 | 3.328 | contract: handoff_missing |
| w3-13 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 788 | 6.093 | 5.2.2: line 21: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-13 | 1 | blender | broken | alone | failed | failed | FAIL | 3 | 867 | 6.359 | 5.2.2: line 21: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-13 | 2 | blender | broken | alone | failed | failed | FAIL | 4 | 793 | 5.787 | 5.2.2: line 12: AttributeError: bpy_struct: attribute "node_tree" from "Material" is read-only |
| w3-14 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 230 | 1.908 | 5.2.2: line 16: AttributeError: 'SceneEEVEE' object has no attribute 'use_bloom' |
| w3-14 | 1 | blender | broken | alone | failed | failed | FAIL | 3 | 230 | 1.67 | 5.2.2: line 16: AttributeError: 'SceneEEVEE' object has no attribute 'use_bloom' |
| w3-14 | 2 | blender | broken | alone | failed | failed | FAIL | 3 | 238 | 1.715 | 5.2.2: line 16: AttributeError: 'SceneEEVEE' object has no attribute 'use_bloom' |
| w3-19 | 0 | blender | broken | alone | pass | pass | FAIL | 0 | 727 | 5.621 | contract: handoff_missing |
| w3-19 | 1 | blender | broken | alone | pass | pass | FAIL | 0 | 1163 | 8.46 | contract: handoff_missing |
| w3-19 | 2 | blender | broken | alone | pass | pass | FAIL | 0 | 795 | 5.795 | contract: handoff_missing |
| w4f-01 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 519 | 3.8 | 5.2.2: line 17: SyntaxError: '[' was never closed |
| w4f-01 | 1 | blender | broken | alone | failed | failed | FAIL | 3 | 1181 | 8.432 | 5.2.2: line 17: KeyError: 'bpy_prop_collection[key]: key "chimera_camera" not found' |
| w4f-01 | 2 | blender | broken | alone | failed | failed | FAIL | 1 | 431 | 3.071 | 5.2.2: line 27: AttributeError: bpy_struct: attribute "dof" from "Camera" is read-only |
| w4f-02 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 1113 | 8.034 | 5.2.2: line 19: AttributeError: bpy_prop_collection: attribute "link" not found |
| w4f-02 | 1 | blender | broken | alone | failed | failed | FAIL | 0 | 1286 | 9.18 | 5.2.2: line 48: TypeError: bpy_struct: item.attr = val: |
| w4f-02 | 2 | blender | broken | alone | failed | failed | FAIL | 52 | 2905 | 21.15 | 5.2.2: line 14: AttributeError: bpy_prop_collection: attribute "link" not found |
| w4f-05 | 0 | python-script | broken | – | – | – | – | – | 645 | 4.685 | contract: handoff_missing |
| w4f-05 | 1 | python-script | broken | – | – | – | – | – | 612 | 4.304 | contract: handoff_missing |
| w4f-05 | 2 | python-script | broken | – | – | – | – | – | 631 | 4.451 | contract: handoff_missing |
| w4f-06 | 0 | files | broken | – | – | – | – | – | 486 | 3.496 | contract: handoff_missing, no_file_line |
| w4f-06 | 1 | files | broken | – | – | – | – | – | 249 | 1.751 | contract: handoff_missing, no_file_line |
| w4f-06 | 2 | files | broken | – | – | – | – | – | 542 | 3.815 | contract: handoff_missing, no_file_line |
| w4f-08 | 0 | section | broken | – | – | – | – | – | 390 | 2.816 | contract: handoff_missing, no_heading |
| w4l-02 | 0 | section | broken | – | – | – | – | – | 920 | 11.958 | contract: handoff_missing, no_heading |
| w4l-04 | 0 | blender | broken | none | runaway | runaway | – | 0 | 6144 | 57.146 | runaway in content: cut at 6144 tokens |
| w4l-04 | 1 | blender | broken | after_deps | pass | pass | FAIL | 0 | 1762 | 15.051 | contract: handoff_missing |
| w4l-04 | 2 | blender | broken | after_deps | pass | pass | FAIL | 0 | 1023 | 8.669 | contract: handoff_missing |
| w4l-07 | 0 | files | broken | – | – | – | – | – | 595 | 7.333 | contract: handoff_missing, no_file_line |
| w4l-07 | 1 | files | broken | – | – | – | – | – | 590 | 4.848 | contract: handoff_missing, no_file_line |
| w4l-07 | 2 | files | broken | – | – | – | – | – | 664 | 5.472 | contract: handoff_missing, no_file_line |
| w4l-08 | 0 | blender | broken | after_deps | failed | failed | FAIL | 3 | 523 | 7.626 | 5.2.2: line 132: AttributeError: 'PointLight' object has no attribute 'specular_intensity' |
| w4l-08 | 1 | blender | broken | after_deps | failed | failed | FAIL | 3 | 397 | 3.431 | 5.2.2: line 132: AttributeError: 'SunLight' object has no attribute 'rotation_euler' |
| w4l-08 | 2 | blender | broken | after_deps | failed | failed | FAIL | 3 | 406 | 3.495 | 5.2.2: line 132: AttributeError: 'SunLight' object has no attribute 'rotation_euler' |
| w4l-10 | 0 | section | broken | – | – | – | – | – | 1055 | 15.275 | contract: handoff_missing, no_heading |
