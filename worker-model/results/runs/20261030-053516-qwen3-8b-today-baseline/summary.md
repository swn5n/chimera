# qwen3:8b, today prompt, on the worker eval (w1.0)

2026-10-30T05:35:16-05:00 · Ollama 0.40.1 · digest `500a1f067a9f` · samples 1 (prose 1) · unseeded · Blender 5.2.2, 5.0.1

EVAL ONLY: model replies to eval cases; never training data.

Differences from what Chimera 0.7.0 sends: repair cases (W3) under today's prompt get the contract's repair part appended (Chimera 0.7.0 has no step repair); a worker step's reply content is cut after 6144 tokens and scored as a runaway in content (the reply cap: Hydra Worker's num_predict, the cap Chimera should hold every step's content to); thinking doesn't count toward it. Chimera 0.7.0 sends no num_predict and no think field and has no cap; every reply, thinking included, is cut after 16384 tokens (the runaway guard; a worker reply cut there while still thinking is scored as a runaway in thinking; Chimera has no guard).

| – | n | contract kept | form ok | Blender n | strict 5.2.2 | strict 5.0.1 | both | crash 5.2.2 (checked) | crash 5.2.2 (all) | no script | assertions | API errors | repaired | expect | runaway | cut off | tokens | tok/s | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 36 | 0% | 0% | 30 | 23% | 23% | 23% | 69% | 67% | 3% | 20% | 3.67 | 40% | 0% | 0% | 0% | 2580.5 | 92.65 | 31.927 |
| w2 | 16 | 0% | 0% | 16 | 6% | 6% | 6% | 81% | 81% | 0% | 6% | 3.81 | – | – | 0% | 0% | 4897.0 | 91.5 | 53.835 |
| w3 | 10 | 0% | 0% | 10 | 40% | 40% | 40% | 56% | 50% | 10% | 30% | 4.6 | 40% | – | 0% | 0% | 2057.0 | 92.8 | 22.6675 |
| w4f | 5 | 0% | 0% | 2 | 0% | 0% | 0% | 100% | 100% | 0% | 0% | 1.5 | – | 0% | 0% | 0% | 1255 | 95.3 | 13.366 |
| w4l | 5 | 0% | 0% | 2 | 100% | 100% | 100% | 0% | 0% | 0% | 100% | 0.0 | – | 0% | 0% | 0% | 3064 | 80.0 | 43.667 |
| blender | 30 | 0% | 0% | 30 | 23% | 23% | 23% | 69% | 67% | 3% | 20% | 3.67 | 40% | 0% | 0% | 0% | 3020.0 | 92.65 | 34.8475 |
| files | 2 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 4503.0 | 87.75 | 57.502500000000005 |
| python-script | 1 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 1255 | 95.3 | 13.366 |
| section | 3 | 0% | 0% | – | – | – | – | – | – | – | – | – | – | 0% | 0% | 0% | 1771 | 83.2 | 27.835 |

contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: line): what data generation keeps. Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run (no script: 1) and a runaway (0, of which 0 had no script) count as fails, not as left out. strict: not a runaway; Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows (tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same rule; the probes run there). crash: the check's outcome was failed (a definite crash); "checked" is over the 29 samples Blender checked (the plan's "definite crashes at most 10%"), "all" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a crash. no script: the reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 (no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern check the case has. runaway: the runner stopped reading the reply, in content (its content passed the reply cap of 6144 tokens, thinking not counted, or the guard hit while it wrote content) or in thinking (the runaway guard, 16384 tokens with thinking, hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and no think field and has neither limit. cut off: Ollama itself stopped at a length limit. The plan's cut-off bar counts both.

## Samples

| case | sample | mode | contract | run | 5.2.2 | 5.0.1 | assert | lint | tokens | s | first problem |
|---|---|---|---|---|---|---|---|---|---|---|---|
| w2-01 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 2262 | 24.157 | 5.2.2: line 8: RuntimeError: Error: Node type ShaderNodeGlassBSDF undefined |
| w2-02 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 1838 | 19.504 | 5.2.2: line 10: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w2-04 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 4653 | 50.585 | 5.2.2: line 4: TypeError: Converting py args to operator properties:: keyword "segments" unrecognized |
| w2-05 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 6020 | 66.276 | 5.2.2: line 10: RuntimeError: Error: Node type ShaderNodeNoiseTexture undefined |
| w2-07 | 0 | blender | broken | alone | failed | failed | FAIL | 5 | 8969 | 101.138 | 5.2.2: line 5: TypeError: Converting py args to operator properties:: keyword "radius" unrecognized |
| w2-08 | 0 | blender | broken | alone | unsure | unsure | FAIL | 4 | 1172 | 12.483 | 5.2.2: line 4: TypeError: bpy_struct: item.attr = val: enum "EEVEE" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH',  |
| w2-10 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 3692 | 39.755 | 5.2.2: line 4: AttributeError: 'Scene' object has no attribute 'node_tree' |
| w2-12 | 0 | blender | broken | alone | failed | failed | FAIL | 16 | 8915 | 100.59 | 5.2.2: line 5: TypeError: BlendDataNodeTrees.new(): error with keyword argument "type" -  enum "GEOMETRY" not found in ( |
| w2-13 | 0 | blender | broken | alone | failed | failed | FAIL | 10 | 6475 | 72.136 | 5.2.2: line 14: TypeError: BlendDataNodeTrees.new(): error with keyword argument "type" -  enum "GEOMETRYNODETREE" not f |
| w2-14 | 0 | blender | broken | alone | failed | failed | FAIL | 9 | 6780 | 76.378 | 5.2.2: line 15: AttributeError: 'NodesModifier' object has no attribute 'node_tree' |
| w2-16 | 0 | blender | broken | alone | failed | failed | FAIL | 4 | 1022 | 11.003 | 5.2.2: line 4: AttributeError: 'Scene' object has no attribute 'color_management' |
| w2-18 | 0 | blender | broken | alone | failed | failed | FAIL | 0 | 4172 | 45.651 | 5.2.2: line 24: TypeError: BlendDataLights.new(): required parameter "type" not specified |
| w2-19 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 5839 | 65.359 | 5.2.2: line 21: AttributeError: 'Action' object has no attribute 'fcurves' |
| w2-21 | 0 | blender | broken | alone | unsure | unsure | FAIL | 2 | 5141 | 57.085 | 5.2.2: line 12: AttributeError: Calling operator "bpy.ops.mesh.icosphere_add" error, could not be found |
| w2-25 | 0 | blender | broken | alone | pass | pass | ok | 0 | 1863 | 20.202 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w2-27 | 0 | blender | broken | alone | failed | failed | FAIL | 0 | 7201 | 81.802 | 5.2.2: line 26: ValueError: too many values to unpack (expected 3) |
| w3-01 | 0 | blender | broken | alone | pass | pass | ok | 0 | 1545 | 17.344 | contract: handoff_missing |
| w3-03 | 0 | blender | broken | alone | pass | pass | ok | 0 | 1193 | 13.107 | contract: handoff_missing |
| w3-04 | 0 | blender | broken | alone | pass | pass | ok | 0 | 2098 | 23.027 | contract: handoff_missing |
| w3-06 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 2976 | 32.985 | 5.2.2: line 27: AttributeError: 'Mesh' object has no attribute 'auto_smooth_angle' |
| w3-09 | 0 | blender | broken | alone | pass | pass | FAIL | 1 | 2813 | 30.869 | contract: handoff_missing |
| w3-11 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 2016 | 22.308 | 5.2.2: line 13: AttributeError: 'ShaderNodeTexNoise' object has no attribute 'scale' |
| w3-12 | 0 | blender | broken | after_deps | failed | failed | FAIL | 7 | 1757 | 19.54 | 5.2.2: line 55: KeyError: 'bpy_prop_collection[key]: key "Specular" not found' |
| w3-13 | 0 | blender | broken | none | – | – | – | 31 | 3286 | 36.71 | no script: not joined: s1: handoff_missing: no ```handoff block at the end; s1: no_build: no def build_s1(ctx):; s1: no_ |
| w3-14 | 0 | blender | broken | alone | failed | failed | FAIL | 3 | 841 | 9.274 | 5.2.2: line 14: AttributeError: 'SceneEEVEE' object has no attribute 'use_bloom' |
| w3-19 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 2179 | 24.097 | 5.2.2: line 34: AttributeError: 'NodesModifier' object has no attribute 'inputs' |
| w4f-01 | 0 | blender | broken | alone | failed | failed | FAIL | 2 | 2348 | 25.198 | 5.2.2: line 10: AttributeError: 'Camera' object has no attribute 'fstop' |
| w4f-02 | 0 | blender | broken | alone | failed | failed | FAIL | 1 | 3409 | 36.926 | 5.2.2: line 6: TypeError: Converting py args to operator properties:: keyword "radius" unrecognized |
| w4f-05 | 0 | python-script | broken | – | – | – | – | – | 1255 | 13.366 | contract: handoff_missing |
| w4f-06 | 0 | files | broken | – | – | – | – | – | 1022 | 10.873 | contract: handoff_missing, no_file_line |
| w4f-08 | 0 | section | broken | – | – | – | – | – | 1157 | 12.304 | contract: handoff_missing, no_heading |
| w4l-02 | 0 | section | broken | – | – | – | – | – | 1771 | 27.835 | contract: handoff_missing, no_heading |
| w4l-04 | 0 | blender | broken | after_deps | pass | pass | ok | 0 | 8306 | 109.357 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w4l-07 | 0 | files | broken | – | – | – | – | – | 7984 | 104.132 | contract: handoff_missing, no_file_line |
| w4l-08 | 0 | blender | broken | after_deps | pass | pass | ok | 0 | 3064 | 43.667 | contract: handoff_missing, no_build, no_main_guard, no_settings |
| w4l-10 | 0 | section | broken | – | – | – | – | – | 1947 | 34.576 | contract: handoff_missing, no_heading |
