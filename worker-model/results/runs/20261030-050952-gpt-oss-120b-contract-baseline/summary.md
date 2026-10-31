# gpt-oss:120b, contract prompt, on the worker eval (w1.0)

2026-10-30T05:09:52-05:00 · Ollama 0.40.1 · digest `714d86958b6e` · samples 2 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: a worker step's reply content is cut after 6144 tokens and scored as a runaway in content (the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap; every reply, thinking included, is cut after 16384 tokens (the runaway guard; a worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard).

| – | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 (checked) | crash 5.2.2 (all) | no script | assertions | API errors | repaired | expect | runaway | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 69 | 86% | 80% | 60 | 38% | 42% | 38% | 62% | 62% | 0% | 30% | 1.43 | 55% | 29% | 0% | 0% | 1475 | 81.7 | 18.942 |
| w2 | 32 | 81% | 81% | 32 | 25% | 25% | 25% | 75% | 75% | 0% | 22% | 1.94 | – | – | 0% | 0% | 1497.5 | 81.8 | 19.002499999999998 |
| w3 | 20 | 90% | 90% | 20 | 55% | 65% | 55% | 45% | 45% | 0% | 40% | 1.05 | 55% | – | 0% | 0% | 1418.0 | 81.4 | 17.9465 |
| w4f | 9 | 78% | 56% | 4 | 50% | 50% | 50% | 50% | 50% | 0% | 25% | 0.75 | – | 22% | 0% | 0% | 1464 | 82.0 | 17.906 |
| w4l | 8 | 100% | 75% | 4 | 50% | 50% | 50% | 50% | 50% | 0% | 50% | 0.0 | – | 38% | 0% | 0% | 1451.5 | 78.25 | 25.86 |
| blender | 60 | 83% | 83% | 60 | 38% | 42% | 38% | 62% | 62% | 0% | 30% | 1.43 | 55% | 38% | 0% | 0% | 1483.5 | 81.65 | 19.197 |
| files | 4 | 100% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 1219.5 | 80.3 | 15.547999999999998 |
| python-script | 2 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | 50% | 0% | 0% | 1388.0 | 82.05 | 17.17 |
| section | 3 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | 33% | 0% | 0% | 1229 | 78.3 | 35.239 |

contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: line): what data generation keeps. Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run (no script: 0) and a runaway (0, of which 0 had no script) count as fails, not as left out. strict: not a runaway; Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows (tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same rule; the probes run there). crash: the check's outcome was failed (a definite crash); "checked" is over the 60 samples Blender checked (the plan's "definite crashes at most 10%"), "all" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a crash. no script: the reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 (no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has. runaway: the runner stopped reading the reply, in content (its content passed the reply cap of 6144 tokens, thinking not counted, or the guard hit while it wrote content) or in thinking (the runaway guard, 16384 tokens with thinking, hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and no think field and has neither limit. cut off: Ollama itself stopped at a length limit. The plan's cut-off bar counts both.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 1166 | 14.926 | 5.2.2: line 55: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w2-01 | 1 | blender | ok | joined | failed | failed | FAIL | 0 | 1139 | 13.994 | 5.2.2: line 46: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w2-02 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 904 | 11.726 | 5.2.2: line 38: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-02 | 1 | blender | ok | joined | failed | failed | FAIL | 1 | 1036 | 12.717 | 5.2.2: line 36: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-04 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 1488 | 18.884 | 5.2.2: line 79: AttributeError: 'Mesh' object has no attribute 'use_auto_smooth' |
| w2-04 | 1 | blender | ok | joined | failed | failed | FAIL | 2 | 1594 | 19.569 | 5.2.2: line 79: AttributeError: 'BMEdge' object has no attribute 'bevel_weight' and no __dict__ for setting new attribut |
| w2-05 | 0 | blender | broken | alone | pass | pass | FAIL | 0 | 1507 | 19.121 | contract: handoff_missing |
| w2-05 | 1 | blender | ok | joined | failed | failed | FAIL | 1 | 1479 | 18.16 | 5.2.2: line 66: AttributeError: bpy_prop_collection: attribute "clear" not found |
| w2-07 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 2144 | 27.005 | 5.2.2: line 77: AttributeError: 'MeshEdge' object has no attribute 'bevel_weight' |
| w2-07 | 1 | blender | broken | alone | pass | pass | ok | 0 | 2530 | 31.359 | contract: handoff_missing |
| w2-08 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 1443 | 18.313 | 5.2.2: line 57: AttributeError: 'SceneEEVEE' object has no attribute 'use_ssr' |
| w2-08 | 1 | blender | ok | joined | failed | failed | FAIL | 0 | 1155 | 14.186 | 5.2.2: line 43: AttributeError: 'SceneEEVEE' object has no attribute 'use_ssr' |
| w2-10 | 0 | blender | ok | joined | failed | failed | FAIL | 2 | 1467 | 18.61 | 5.2.2: line 31: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-10 | 1 | blender | ok | joined | failed | failed | FAIL | 2 | 1139 | 13.932 | 5.2.2: line 29: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-12 | 0 | blender | ok | joined | failed | failed | FAIL | 14 | 2617 | 32.85 | 5.2.2: line 45: AttributeError: 'GeometryNodeTree' object has no attribute 'inputs' |
| w2-12 | 1 | blender | broken | alone | failed | failed | FAIL | 1 | 2957 | 36.445 | 5.2.2: line 145: SyntaxError: invalid non-printable character U+202F |
| w2-13 | 0 | blender | ok | joined | failed | failed | FAIL | 8 | 2274 | 28.611 | 5.2.2: line 38: RuntimeError: Error: Object does not have geometry data |
| w2-13 | 1 | blender | ok | joined | failed | failed | FAIL | 8 | 2510 | 30.893 | 5.2.2: line 75: TypeError: BlendDataNodeTrees.new(): error with keyword argument "type" -  enum "GEOMETRY" not found in  |
| w2-14 | 0 | blender | ok | joined | failed | failed | FAIL | 10 | 2780 | 34.855 | 5.2.2: line 38: TypeError: create_cone: keyword "diameter1" is invalid for this operator |
| w2-14 | 1 | blender | ok | joined | failed | failed | FAIL | 7 | 2095 | 25.988 | 5.2.2: line 74: RuntimeError: Error: Node type GeometryNodePointDistribute undefined |
| w2-16 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 674 | 8.887 | 5.2.2: line 27: TypeError: bpy_struct: item.attr = val: enum "Punchy" not found in ('None', 'AgX - Punchy', 'AgX - Greys |
| w2-16 | 1 | blender | ok | joined | failed | failed | FAIL | 0 | 957 | 11.751 | 5.2.2: line 28: TypeError: bpy_struct: item.attr = val: enum "Punchy" not found in ('None', 'AgX - Punchy', 'AgX - Greys |
| w2-18 | 0 | blender | ok | joined | pass | pass | ok | 0 | 1403 | 17.835 | – |
| w2-18 | 1 | blender | ok | joined | pass | pass | ok | 0 | 2132 | 26.249 | – |
| w2-19 | 0 | blender | broken | alone | failed | failed | FAIL | 0 | 1676 | 21.204 | 5.2.2: line 61: AttributeError: 'Action' object has no attribute 'fcurves' |
| w2-19 | 1 | blender | broken | alone | failed | failed | FAIL | 1 | 1668 | 20.492 | 5.2.2: line 53: TypeError: create_uvsphere: keyword "diameter" is invalid for this operator |
| w2-21 | 0 | blender | ok | joined | pass | pass | ok | 0 | 1442 | 18.311 | – |
| w2-21 | 1 | blender | broken | alone | pass | pass | ok | 0 | 1717 | 21.117 | contract: handoff_missing |
| w2-25 | 0 | blender | ok | joined | pass | pass | ok | 0 | 859 | 11.157 | – |
| w2-25 | 1 | blender | ok | joined | pass | pass | ok | 0 | 775 | 9.524 | – |
| w2-27 | 0 | blender | ok | joined | failed | failed | FAIL | 0 | 1712 | 21.638 | 5.2.2: line 125: TypeError: Scene.ray_cast(): error with argument 1, "depsgraph" -  Function.depsgraph expected a Depsgr |
| w2-27 | 1 | blender | ok | joined | failed | failed | FAIL | 1 | 1924 | 23.649 | 5.2.2: line 70: AttributeError: 'Mesh' object has no attribute 'use_auto_smooth' |
| w3-01 | 0 | blender | ok | joined | pass | pass | ok | 0 | 1321 | 17.408 | – |
| w3-01 | 1 | blender | ok | joined | pass | pass | ok | 0 | 1308 | 16.135 | – |
| w3-03 | 0 | blender | ok | joined | pass | pass | ok | 0 | 884 | 11.823 | – |
| w3-03 | 1 | blender | ok | joined | pass | pass | ok | 0 | 649 | 7.989 | – |
| w3-04 | 0 | blender | ok | joined | pass | pass | ok | 0 | 1497 | 19.464 | – |
| w3-04 | 1 | blender | ok | joined | pass | pass | ok | 0 | 1135 | 14.007 | – |
| w3-06 | 0 | blender | ok | joined | pass | pass | FAIL | 0 | 1453 | 18.942 | – |
| w3-06 | 1 | blender | ok | joined | pass | pass | FAIL | 0 | 1603 | 19.795 | – |
| w3-09 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 1058 | 13.995 | 5.2.2: line 34: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w3-09 | 1 | blender | ok | joined | pass | pass | FAIL | 1 | 1162 | 14.324 | – |
| w3-11 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 1770 | 22.708 | 5.2.2: line 84: AttributeError: 'Mesh' object has no attribute 'use_auto_smooth' |
| w3-11 | 1 | blender | ok | joined | pass | pass | ok | 0 | 1557 | 19.273 | – |
| w3-12 | 0 | blender | broken | after_deps | pass | pass | ok | 0 | 1767 | 22.969 | contract: handoff_missing |
| w3-12 | 1 | blender | ok | joined | failed | failed | FAIL | 1 | 1638 | 20.283 | 5.2.2: line 71: AttributeError: 'Scene' object has no attribute 'depsgraph' |
| w3-13 | 0 | blender | ok | joined | failed | failed | FAIL | 5 | 2217 | 28.93 | 5.2.2: line 33: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-13 | 1 | blender | ok | joined | failed | failed | FAIL | 3 | 1493 | 18.485 | 5.2.2: line 35: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-14 | 0 | blender | ok | joined | failed | failed | FAIL | 5 | 972 | 12.797 | 5.2.2: line 41: AttributeError: 'SceneEEVEE' object has no attribute 'use_ray_tracing'. Did you mean: 'use_raytracing'? |
| w3-14 | 1 | blender | ok | joined | failed | failed | FAIL | 4 | 944 | 11.615 | 5.2.2: line 38: AttributeError: 'SceneEEVEE' object has no attribute 'use_ssr' |
| w3-19 | 0 | blender | ok | joined | failed | pass | FAIL | 0 | 1478 | 19.298 | 5.2.2: line 91: TypeError: bpy_struct[key] = val: id properties not supported for this type |
| w3-19 | 1 | blender | ok | joined | failed | pass | FAIL | 0 | 1383 | 17.078 | 5.2.2: line 89: TypeError: bpy_struct[key] = val: id properties not supported for this type |
| w4f-01 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 1606 | 20.323 | 5.2.2: line 54: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w4f-01 | 1 | blender | ok | joined | pass | pass | ok | 0 | 1604 | 19.679 | missed assumed_mentions |
| w4f-02 | 0 | blender | ok | joined | pass | pass | FAIL | 0 | 1890 | 23.825 | missed assumed_mentions |
| w4f-02 | 1 | blender | broken | alone | failed | failed | FAIL | 2 | 2144 | 26.373 | 5.2.2: line 34: AttributeError: module 'mathutils' has no attribute 'cos' |
| w4f-05 | 0 | python-script | ok | – | – | – | – | – | 1312 | 16.434 | missed assumed_mentions |
| w4f-05 | 1 | python-script | ok | – | – | – | – | – | 1464 | 17.906 | – |
| w4f-06 | 0 | files | ok, near miss | – | – | – | – | – | 1064 | 13.513 | missed must_mention |
| w4f-06 | 1 | files | ok, near miss | – | – | – | – | – | 944 | 11.541 | missed must_mention, assumed_mentions |
| w4f-08 | 0 | section | ok | – | – | – | – | – | 681 | 8.655 | – |
| w4l-02 | 0 | section | ok | – | – | – | – | – | 1229 | 39.364 | missed needles |
| w4l-04 | 0 | blender | ok | after_deps | failed | failed | FAIL | 0 | 1428 | 24.226 | 5.2.2: line 369: AttributeError: 'Action' object has no attribute 'fcurves' |
| w4l-04 | 1 | blender | ok | after_deps | failed | failed | FAIL | 0 | 2055 | 26.402 | 5.2.2: line 336: TypeError: bpy_struct: item.attr = val: enum "-Z" not found in ('TRACK_X', 'TRACK_Y', 'TRACK_Z', 'TRACK |
| w4l-07 | 0 | files | ok, near miss | – | – | – | – | – | 1575 | 25.743 | missed uses_mentions |
| w4l-07 | 1 | files | ok, near miss | – | – | – | – | – | 1375 | 17.583 | missed uses_mentions |
| w4l-08 | 0 | blender | ok | after_deps | pass | pass | ok | 0 | 1475 | 25.977 | – |
| w4l-08 | 1 | blender | ok | after_deps | pass | pass | ok | 0 | 1118 | 14.498 | – |
| w4l-10 | 0 | section | ok | – | – | – | – | – | 1927 | 35.239 | missed must_mention, uses_mentions |
