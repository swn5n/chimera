# Task-level run, arm A: today prompt, workers qwen3.8:27b, combine

2026-11-01T15:58:32-06:00 · combine model qwen3.8:27b · seam pass: none · Ollama 0.40.1 · Blender 5.2.2, 5.0.1

EVAL ONLY: model output for eval plans; never training data.

| tasks | Blender n | Blender pass 5.2.2 | 5.0.1 | both | Python n | Python pass | assertions | fallback | seams | cut off | runaway | steps runaway | steps kept the contract | steps in exact form | one script | reviewer done | median s | total s | tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 4 | 4 | 0% | 0% | 0% | 0 | – | 0% | – | – | 0% | 0% | 0% | 0% | 0% | 100% | – | 365.15999999999997 | 1488.6 | 94512 |

Pass rates are over every task of the kind: Blender n is every plan with a Blender step, Python n every python-script plan without a files step. A result the check didn't run counts as a fail: unchecked {"blender": {}, "python": {}}. pass: Chimera's check passed with no Traceback or Error: line in its 1,500-character output tail, and the direct run of the same script has none in its whole output. runaway: the combine or a lone step hit the reply cap (6144 content tokens for a step, thinking not counted) or the runaway guard (16384 tokens, thinking included); steps runaway: steps the cap or the guard cut ("in thinking": the guard hit while the model was still thinking). steps kept the contract: Chimera can join the piece (the near-miss handoff forms included, since Oct 30); in exact form: no errors and the contract's exact written form, what data generation keeps. no_entry_point (unchecked): a joined Python script where no step defines main(), which Chimera's check would pass without running anything. cut off: Ollama itself stopped at a length limit. one script: of the Blender tasks, results holding exactly one Blender script.

How the result was made: {"combine": 4}; checks: {"checked": 4}.

## Tasks

| task | sample | steps (s, tokens, contract) | result by | 5.2.2 | 5.0.1 | assertions | seams | s | first problem |
|---|---|---|---|---|---|---|---|---|---|
| bw-04 | 0 | s1 41s 3028t x, s2 71s 4637t x, s3 58s 3672t x, s4 69s 4076t x | combine | failed | failed | 1 failed | 0 | 475.07 | 5.2.2: line 20: AttributeError: bpy_prop_collection: attribute "unlink" not found |
| bw-05 | 0 | s1 99s 6879t x, s2 68s 4210t x | combine | failed | failed | 1 failed | 0 | 349.5 | 5.2.2: line 41: TypeError: NodeTreeInterface.new_socket(): was called with invalid keyword argument(s) (default_value), expected (name, desc |
| bw-09 | 0 | s1 65s 4562t x, s2 58s 4023t x, s3 54s 3805t x, s4 69s 3497t x | combine | failed | failed | 1 failed | 0 | 380.82 | 5.2.2: line 216: SyntaxError: closing parenthesis ')' does not match opening parenthesis '[' on line 214 |
| bw-10 | 0 | s1 15s 1052t x, s2 48s 3131t x, s3 30s 1948t x, s4 39s 2594t x, s5 81s 4862t x | combine | unsure | unsure | 1 failed | 0 | 283.17 | 5.2.2: line 32: TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType' |
