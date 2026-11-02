# Task-level run, arm A: today prompt, workers qwen3.8:27b, combine

2026-11-01T17:54:19-06:00 · combine model qwen3.8:27b · seam pass: none · Ollama 0.40.1 · Blender 5.2.2, 5.0.1

EVAL ONLY: model output for eval plans; never training data.

| tasks | Blender n | Blender pass 5.2.2 | 5.0.1 | both | Python n | Python pass | assertions | fallback | seams | cut off | runaway | steps runaway | steps kept the contract | steps in exact form | one script | reviewer done | median s | total s | tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 12 | 12 | 8% | 17% | 8% | 0 | – | 0% | – | – | 0% | 17% | 0% | 0% | 0% | 83% | – | 354.305 | 4580.4 | 277019 |

Pass rates are over every task of the kind: Blender n is every plan with a Blender step, Python n every python-script plan without a files step. A result the check didn't run counts as a fail: unchecked {"blender": {"runaway": 2}, "python": {}}. pass: Chimera's check passed with no Traceback or Error: line in its 1,500-character output tail, and the direct run of the same script has none in its whole output. runaway: the combine or a lone step hit the reply cap (6144 content tokens for a step, thinking not counted) or the runaway guard (16384 tokens, thinking included); steps runaway: steps the cap or the guard cut ("in thinking": the guard hit while the model was still thinking). steps kept the contract: Chimera can join the piece (the near-miss handoff forms included, since Oct 30); in exact form: no errors and the contract's exact written form, what data generation keeps. no_entry_point (unchecked): a joined Python script where no step defines main(), which Chimera's check would pass without running anything. cut off: Ollama itself stopped at a length limit. one script: of the Blender tasks, results holding exactly one Blender script.

How the result was made: {"combine": 11, "lone": 1}; checks: {"checked": 10, "runaway": 2}.

## Tasks

| task | sample | steps (s, tokens, contract) | result by | 5.2.2 | 5.0.1 | assertions | seams | s | first problem |
|---|---|---|---|---|---|---|---|---|---|
| bw-01 | 0 | s1 14s 624t x, s2 32s 2046t x, s3 33s 2161t x, s4 55s 3847t x, s5 37s 2692t x, s6 39s 2363t x, s7 34s 861t x | combine | failed | failed | 1 failed | 0 | 433.5 | 5.2.2: line 228: TypeError: BlendDataObjects.new(): required parameter "object_data" not specified |
| bw-02 | 0 | s1 18s 1039t x, s2 40s 2393t x, s3 76s 4778t x, s4 68s 4269t x | combine | failed | failed | 1 failed | 0 | 296.41 | 5.2.2: line 263: AttributeError: 'RenderSettings' object has no attribute 'file_format'. Did you mean: 'views_format'? |
| bw-03 | 0 | s1 91s 6070t x | lone | failed | failed | 1 failed | 0 | 90.78 | 5.2.2: line 27: AttributeError: bpy_prop_collection: attribute "clear" not found |
| bw-04 | 0 | s1 44s 2748t x, s2 95s 6111t x, s3 93s 5667t x, s4 64s 3155t x | combine | failed | failed | 1 failed | 0 | 412.2 | 5.2.2: line 108: AttributeError: 'Object' object has no attribute 'rigid_body_type' |
| bw-05 | 0 | s1 141s 9274t x, s2 64s 3882t x | combine | failed | pass | 1 failed | 0 | 429.23 | 5.2.2: line 69: TypeError: bpy_struct: item.attr = val: NodeSocketInt.default_value expected an int type, not float |
| bw-06 | 0 | s1 56s 4065t x, s2 63s 4030t x, s3 46s 2540t x, s4 83s 5396t x, s5 39s 2288t x, s6 32s 1769t x | combine | failed | failed | 1 failed | 0 | 466.13 | 5.2.2: line 169: ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 3 items, not 4 |
| bw-07 | 0 | s1 9s 412t x, s2 44s 2779t x, s3 59s 3849t x, s4 58s 3429t x | combine | pass | pass | 1 failed | 0 | 239.95 | – |
| bw-08 | 0 | s1 165s 11231t x, s2 63s 3791t x, s3 97s 5457t x, s4 75s 3878t x | combine | – | – | – | 0 | 701.27 | runaway |
| bw-09 | 0 | s1 68s 4551t x, s2 67s 4399t x, s3 283s 17065t x, s4 71s 3571t x | combine | – | – | – | 0 | 777.58 | runaway |
| bw-10 | 0 | s1 24s 1435t x, s2 51s 3155t x, s3 26s 1495t x, s4 42s 2558t x, s5 59s 3253t x | combine | failed | failed | 1 failed | 0 | 267.93 | 5.2.2: line 172: TypeError: Scene.ray_cast(): error with argument 1, "depsgraph" -  Function.depsgraph expected a Depsgraph type, not Vector |
| bl-01 | 0 | s1 34s 2175t x, s2 39s 2447t x, s3 39s 2408t x, s4 44s 2442t x | combine | failed | failed | – | 0 | 205.32 | 5.2.2: line 21: TypeError: bmesh operators expect a single BMesh positional argument, all other args must be keywords |
| bl-03 | 0 | s1 60s 3904t x, s2 62s 4039t x, s3 71s 4373t x | combine | failed | failed | – | 0 | 260.09 | 5.2.2: line 69: TypeError: bmesh operators expect a single BMesh positional argument, all other args must be keywords |
