# qwen3:8b, contract prompt, on the worker eval (w1.0)

2026-10-30T06:01:34-05:00 · Ollama 0.40.1 · digest `500a1f067a9f` · samples 1 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: a worker step's reply content is cut after 6144 tokens and scored as a runaway in content (the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap; every reply, thinking included, is cut after 16384 tokens (the runaway guard; a worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard).

| – | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 (checked) | crash 5.2.2 (all) | no script | assertions | API errors | repaired | expect | runaway | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 36 | 75% | 47% | 30 | 30% | 30% | 30% | 61% | 57% | 7% | 23% | 2.61 | 70% | 40% | 0% | 0% | 3139.5 | 89.8 | 35.6995 |
| w2 | 16 | 62% | 19% | 16 | 12% | 12% | 12% | 73% | 69% | 6% | 12% | 4.0 | – | – | 0% | 0% | 4936.0 | 89.25 | 55.8955 |
| w3 | 10 | 100% | 100% | 10 | 70% | 70% | 70% | 30% | 30% | 0% | 50% | 0.9 | 70% | – | 0% | 0% | 2614.0 | 90.55000000000001 | 29.908 |
| w4f | 5 | 80% | 20% | 2 | 0% | 0% | 0% | 100% | 100% | 0% | 0% | 1.5 | – | 60% | 0% | 0% | 1841 | 92.9 | 20.452 |
| w4l | 5 | 60% | 60% | 2 | 0% | 0% | 0% | 100% | 50% | 50% | 0% | 1.0 | – | 20% | 0% | 0% | 4210 | 76.4 | 63.354 |
| blender | 30 | 77% | 47% | 30 | 30% | 30% | 30% | 61% | 57% | 7% | 23% | 2.61 | 70% | 50% | 0% | 0% | 3656.0 | 89.8 | 41.626999999999995 |
| files | 2 | 50% | 0% | – | – | – | – | – | – | – | – | – | – | 50% | 0% | 0% | 4382.5 | 84.2 | 58.65 |
| python-script | 1 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 2361 | 93.3 | 25.619 |
| section | 3 | 100% | 100% | – | – | – | – | – | – | – | – | – | – | 33% | 0% | 0% | 875 | 81.5 | 18.13 |

contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: line): what data generation keeps. Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run (no script: 2) and a runaway (0, of which 0 had no script) count as fails, not as left out. strict: not a runaway; Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows (tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same rule; the probes run there). crash: the check's outcome was failed (a definite crash); "checked" is over the 28 samples Blender checked (the plan's "definite crashes at most 10%"), "all" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a crash. no script: the reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 (no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has. runaway: the runner stopped reading the reply, in content (its content passed the reply cap of 6144 tokens, thinking not counted, or the guard hit while it wrote content) or in thinking (the runaway guard, 16384 tokens with thinking, hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and no think field and has neither limit. cut off: Ollama itself stopped at a length limit. The plan's cut-off bar counts both.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | blender | ok, near miss | joined | failed | failed | FAIL | 2 | 1141 | 12.587 | 5.2.2: line 25: KeyError: 'bpy_prop_collection[key]: key "Transmission" not found' |
| w2-02 | 0 | blender | ok, near miss | joined | failed | failed | FAIL | 16 | 2574 | 28.149 | 5.2.2: line 33: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-04 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 7887 | 91.875 | 5.2.2: line 50: AttributeError: 'Mesh' object has no attribute 'use_auto_smooth' |
| w2-05 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 4874 | 55.039 | 5.2.2: line 30: RuntimeError: Error: Node type ShaderNodeColorRamp undefined |
| w2-07 | 0 | blender | broken | alone | unsure | unsure | FAIL | 2 | 9316 | 108.716 | 5.2.2: line 23: ReferenceError: StructRNA of type Object has been removed |
| w2-08 | 0 | blender | ok, near miss | joined | unsure | unsure | FAIL | 4 | 1243 | 13.676 | 5.2.2: line 17: TypeError: bpy_struct: item.attr = val: enum "EEVEE" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH', |
| w2-10 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 1051 | 11.816 | 5.2.2: line 17: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-12 | 0 | blender | broken | alone | failed | failed | FAIL | 18 | 7584 | 88.163 | 5.2.2: line 79: NameError: name 'ctx' is not defined |
| w2-13 | 0 | blender | broken | none | – | – | – | – | 4998 | 56.752 | no script: not joined: s1: no_python_block: no python code block; the reply has no Blender script |
| w2-14 | 0 | blender | broken | alone | failed | failed | FAIL | 6 | 6961 | 81.232 | 5.2.2: line 33: AttributeError: 'NodesModifier' object has no attribute 'node_tree' |
| w2-16 | 0 | blender | ok | joined | failed | failed | FAIL | 4 | 1334 | 14.645 | 5.2.2: line 16: AttributeError: 'Scene' object has no attribute 'color_management' |
| w2-18 | 0 | blender | ok, near miss | joined | pass | pass | ok | 0 | 6019 | 68.981 | – |
| w2-19 | 0 | blender | ok, near miss | joined | failed | failed | FAIL | 1 | 1440 | 15.786 | 5.2.2: line 35: AttributeError: 'Action' object has no attribute 'fcurves' |
| w2-21 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 7118 | 82.803 | 5.2.2: line 28: AttributeError: BMeshOpsModule: operator "icosphere" doesn't exist |
| w2-25 | 0 | blender | ok, near miss | joined | pass | pass | ok | 0 | 4371 | 49.224 | – |
| w2-27 | 0 | blender | ok, near miss | joined | failed | failed | FAIL | 1 | 6169 | 70.932 | 5.2.2: line 32: AttributeError: 'NoiseTexture' object has no attribute 'noise_scale' |
| w3-01 | 0 | blender | ok | joined | pass | pass | ok | 0 | 2316 | 26.427 | – |
| w3-03 | 0 | blender | ok | joined | pass | pass | ok | 0 | 749 | 8.728 | – |
| w3-04 | 0 | blender | ok | joined | pass | pass | ok | 0 | 4332 | 50.311 | – |
| w3-06 | 0 | blender | ok | joined | pass | pass | FAIL | 0 | 3868 | 44.36 | – |
| w3-09 | 0 | blender | ok | joined | pass | pass | FAIL | 1 | 3419 | 38.894 | – |
| w3-11 | 0 | blender | ok | joined | failed | failed | FAIL | 1 | 2368 | 26.928 | 5.2.2: line 37: AttributeError: 'CloudsTexture' object has no attribute 'scale' |
| w3-12 | 0 | blender | ok | joined | pass | pass | ok | 1 | 1415 | 16.211 | – |
| w3-13 | 0 | blender | ok | joined | failed | failed | FAIL | 3 | 2860 | 32.888 | 5.2.2: line 17: KeyError: 'bpy_prop_collection[key]: key "Specular Factor" not found' |
| w3-14 | 0 | blender | ok | joined | failed | failed | FAIL | 3 | 835 | 9.54 | 5.2.2: line 18: AttributeError: 'SceneEEVEE' object has no attribute 'use_bloom' |
| w3-19 | 0 | blender | ok | joined | pass | pass | ok | 0 | 4594 | 53.552 | – |
| w4f-01 | 0 | blender | ok, near miss | joined | failed | failed | FAIL | 1 | 1370 | 14.986 | 5.2.2: line 30: AttributeError: 'Camera' object has no attribute 'fstop' |
| w4f-02 | 0 | blender | ok, near miss | joined | failed | failed | FAIL | 2 | 3444 | 38.511 | 5.2.2: line 34: TypeError: ObjectModifiers.new(): error with argument 2, "type" -  enum "SCATTER" not found in ('GREASE_ |
| w4f-05 | 0 | python-script | broken | – | – | – | – | – | 2361 | 25.619 | contract: handoff_missing, syntax_error |
| w4f-06 | 0 | files | ok, near miss | – | – | – | – | – | 1841 | 20.452 | – |
| w4f-08 | 0 | section | ok | – | – | – | – | – | 871 | 9.729 | – |
| w4l-02 | 0 | section | ok | – | – | – | – | – | 875 | 18.13 | missed needles |
| w4l-04 | 0 | blender | broken | none | – | – | – | – | 7562 | 106.718 | no script: not joined: s1: handoff_many: 2 handoff blocks; the contract has exactly one; s2: handoff_many: 2 handoff blo |
| w4l-07 | 0 | files | broken | – | – | – | – | – | 6924 | 96.848 | contract: handoff_not_last, no_file_line |
| w4l-08 | 0 | blender | ok | after_deps | failed | failed | FAIL | 1 | 4210 | 63.354 | 5.2.2: line 141: NameError: name 'Vector' is not defined |
| w4l-10 | 0 | section | ok | – | – | – | – | – | 1060 | 25.316 | missed must_mention, uses_mentions |
