# gemma4:12b-it-q4_K_M, contract prompt, on the worker eval (w1.0)

2026-10-30T12:15:25-05:00 · Ollama 0.40.1 · digest `6114515d63c1` · samples 3 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: every request sends "think": false (Chimera 0.7.0 sends no think field; the trained worker's template forces thinking off); a worker step's reply content is cut after 6144 tokens and scored as a runaway in content (the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap; every reply, thinking included, is cut after 16384 tokens (the runaway guard; a worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard).

| – | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 (checked) | crash 5.2.2 (all) | no script | assertions | API errors | repaired | expect | runaway | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 42 | 86% | 74% | 30 | 30% | 30% | 30% | 60% | 60% | 0% | – | 3.57 | – | – | 0% | 0% | 671.0 | 62.05 | 11.48 |
| w1 | 42 | 86% | 74% | 30 | 30% | 30% | 30% | 60% | 60% | 0% | – | 3.57 | – | – | 0% | 0% | 671.0 | 62.05 | 11.48 |
| blender | 30 | 80% | 80% | 30 | 30% | 30% | 30% | 60% | 60% | 0% | – | 3.57 | – | – | 0% | 0% | 808.5 | 62.2 | 14.006 |
| files | 6 | 100% | 17% | – | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 489.0 | 69.9 | 7.631 |
| section | 6 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 408.0 | 53.5 | 8.3765 |

contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: line): what data generation keeps. Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run (no script: 0) and a runaway (0, of which 0 had no script) count as fails, not as left out. strict: not a runaway; Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows (tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same rule; the probes run there). crash: the check's outcome was failed (a definite crash); "checked" is over the 30 samples Blender checked (the plan's "definite crashes at most 10%"), "all" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a crash. no script: the reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 (no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has. runaway: the runner stopped reading the reply, in content (its content passed the reply cap of 6144 tokens, thinking not counted, or the guard hit while it wrote content) or in thinking (the runaway guard, 16384 tokens with thinking, hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and no think field and has neither limit. cut off: Ollama itself stopped at a length limit. The plan's cut-off bar counts both.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bw-01/s1 | 0 | blender | ok | joined | pass | pass | – | 0 | 311 | 6.861 | – |
| bw-01/s1 | 1 | blender | ok | joined | pass | pass | – | 0 | 471 | 7.024 | – |
| bw-01/s1 | 2 | blender | ok | joined | pass | pass | – | 0 | 478 | 7.406 | – |
| bw-01/s5 | 0 | blender | ok | joined | pass | pass | – | 0 | 759 | 13.912 | – |
| bw-01/s5 | 1 | blender | ok | joined | pass | pass | – | 0 | 843 | 12.816 | – |
| bw-01/s5 | 2 | blender | ok | joined | pass | pass | – | 0 | 784 | 11.858 | – |
| bw-03/s1 | 0 | blender | broken | alone | failed | failed | – | 14 | 2364 | 35.62 | 5.2.2: line 39: RuntimeError: Error: Node type _OUTPUT_MATERIAL undefined |
| bw-03/s1 | 1 | blender | broken | alone | failed | failed | – | 10 | 2463 | 37.739 | 5.2.2: line 23: RuntimeError: Error: Node type Background undefined |
| bw-03/s1 | 2 | blender | broken | alone | failed | failed | – | 10 | 2421 | 35.9 | 5.2.2: line 23: AttributeError: 'SceneEEVEE' object has no attribute 'use_bloom' |
| bw-04/s1 | 0 | blender | broken | alone | failed | failed | – | 1 | 731 | 12.443 | 5.2.2: line 15: AttributeError: bpy_prop_collection: attribute "clear" not found |
| bw-04/s1 | 1 | blender | broken | alone | failed | failed | – | 1 | 699 | 10.771 | 5.2.2: line 19: AttributeError: bpy_prop_collection: attribute "clear" not found |
| bw-04/s1 | 2 | blender | ok | joined | failed | failed | – | 0 | 680 | 11.388 | 5.2.2: line 57: AttributeError: 'Vector' object has no attribute 'to_euler'. Did you mean: 'to_tuple'? |
| bw-05/s1 | 0 | blender | ok | joined | failed | failed | – | 12 | 1692 | 30.244 | 5.2.2: line 27: AttributeError: 'GeometryNodeTree' object has no attribute 'inputs' |
| bw-05/s1 | 1 | blender | ok | joined | failed | failed | – | 14 | 1362 | 22.151 | 5.2.2: line 16: AttributeError: 'GeometryNodeTree' object has no attribute 'outputs' |
| bw-05/s1 | 2 | blender | ok | joined | failed | failed | – | 9 | 1236 | 19.394 | 5.2.2: line 14: TypeError: BlendDataNodeTrees.new(): required parameter "type" not specified |
| bw-09/s1 | 0 | blender | ok | joined | failed | failed | – | 2 | 1426 | 24.2 | 5.2.2: line 55: AttributeError: bpy_prop_collection: attribute "node_tree" not found |
| bw-09/s1 | 1 | blender | ok | joined | failed | failed | – | 6 | 1421 | 22.473 | 5.2.2: line 25: AttributeError: 'Collection' object has no attribute 'new' |
| bw-09/s1 | 2 | blender | ok | joined | failed | failed | – | 9 | 1462 | 22.664 | 5.2.2: line 24: AttributeError: 'Collection' object has no attribute 'new' |
| bw-09/s3 | 0 | blender | ok | joined | unsure | unsure | – | 5 | 654 | 11.572 | 5.2.2: line 17: TypeError: bpy_struct: item.attr = val: enum "EVEE" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH',  |
| bw-09/s3 | 1 | blender | broken | alone | unsure | unsure | – | 1 | 879 | 14.6 | 5.2.2: line 19: TypeError: bpy_struct: item.attr = val: enum "BLENDER_EEVEE_NEXT" not found in ('BLENDER_EEVEE', 'BLENDE |
| bw-09/s3 | 2 | blender | ok | joined | unsure | unsure | – | 4 | 834 | 14.484 | 5.2.2: line 17: TypeError: bpy_struct: item.attr = val: enum "BLENDER_EEVEE_NEXT" not found in ('BLENDER_EEVEE', 'BLENDE |
| bw-10/s1 | 0 | blender | ok | joined | pass | pass | – | 0 | 331 | 6.82 | – |
| bw-10/s1 | 1 | blender | ok | joined | pass | pass | – | 0 | 292 | 5.18 | – |
| bw-10/s1 | 2 | blender | ok | joined | pass | pass | – | 0 | 374 | 6.483 | – |
| bw-10/s4 | 0 | blender | ok | joined | failed | failed | – | 1 | 1059 | 19.94 | 5.2.2: line 122: AttributeError: 'Object' object has no attribute 'physics' |
| bw-10/s4 | 1 | blender | ok | joined | failed | failed | – | 1 | 901 | 14.824 | 5.2.2: line 94: AttributeError: BMeshOpsModule: operator "create_empty_grid" doesn't exist |
| bw-10/s4 | 2 | blender | ok | joined | failed | failed | – | 1 | 829 | 14.319 | 5.2.2: line 71: AttributeError: 'Material' object has no attribute 'node_tail'. Did you mean: 'node_tree'? |
| code-01/s1 | 0 | files | ok, near miss | – | – | – | – | – | 370 | 7.14 | – |
| code-01/s1 | 1 | files | ok, near miss | – | – | – | – | – | 343 | 5.405 | – |
| code-01/s1 | 2 | files | ok, near miss | – | – | – | – | – | 319 | 5.125 | – |
| code-12/s1 | 0 | files | ok, near miss | – | – | – | – | – | 662 | 10.129 | – |
| code-12/s1 | 1 | files | ok | – | – | – | – | – | 608 | 8.122 | – |
| code-12/s1 | 2 | files | ok, near miss | – | – | – | – | – | 630 | 8.349 | – |
| res-01/s1 | 0 | section | ok | – | – | – | – | – | 444 | 10.224 | – |
| res-01/s5 | 0 | section | ok | – | – | – | – | – | 637 | 16.549 | – |
| res-06/s1 | 0 | section | ok | – | – | – | – | – | 247 | 7.577 | – |
| res-06/s3 | 0 | section | ok | – | – | – | – | – | 284 | 6.517 | – |
| bl-03/s1 | 0 | blender | ok | joined | failed | failed | – | 1 | 592 | 10.949 | 5.2.2: line 36: TypeError: BlendDataTextures.new(): error with keyword argument "type" -  enum "TEXTURE_NOISE" not found |
| bl-03/s1 | 1 | blender | ok | joined | failed | failed | – | 3 | 555 | 9.153 | 5.2.2: line 33: TypeError: BlendDataTextures.new(): error with keyword argument "type" -  enum "RE_NOISE" not found in ( |
| bl-03/s1 | 2 | blender | ok | joined | failed | failed | – | 2 | 788 | 14.1 | 5.2.2: line 19: AttributeError: type object 'Object' has no attribute 'matrix_world' |
| batch-06/s1 | 0 | section | ok | – | – | – | – | – | 446 | 8.489 | – |
| batch-06/s2 | 0 | section | ok | – | – | – | – | – | 372 | 8.264 | – |
