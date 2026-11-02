# Task-level run, arm B: contract prompt, workers qwen3.8:27b, join

2026-11-01T15:44:21-06:00 · combine model qwen3.8:27b · seam pass: none · Ollama 0.40.1 · Blender 5.2.2, 5.0.1

EVAL ONLY: model output for eval plans; never training data.

| tasks | Blender n | Blender pass 5.2.2 | 5.0.1 | both | Python n | Python pass | assertions | fallback | seams | cut off | runaway | steps runaway | steps kept the contract | steps in exact form | one script | reviewer done | median s | total s | tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 4 | 2 | 0% | 0% | 0% | 2 | 0% | 0% | 25% | 0.75 | 0% | 0% | 0% | 88% | 88% | 100% | – | 138.88 | 841.3 | 50649 |

Pass rates are over every task of the kind: Blender n is every plan with a Blender step, Python n every python-script plan without a files step. A result the check didn't run counts as a fail: unchecked {"blender": {}, "python": {"no_entry_point": 1}}. pass: Chimera's check passed with no Traceback or Error: line in its 1,500-character output tail, and the direct run of the same script has none in its whole output. runaway: the combine or a lone step hit the reply cap (6144 content tokens for a step, thinking not counted) or the runaway guard (16384 tokens, thinking included); steps runaway: steps the cap or the guard cut ("in thinking": the guard hit while the model was still thinking). steps kept the contract: Chimera can join the piece (the near-miss handoff forms included, since Oct 30); in exact form: no errors and the contract's exact written form, what data generation keeps. no_entry_point (unchecked): a joined Python script where no step defines main(), which Chimera's check would pass without running anything. cut off: Ollama itself stopped at a length limit. one script: of the Blender tasks, results holding exactly one Blender script.

How the result was made: {"fallback": 1, "joined": 3}; checks: {"checked": 3, "no_entry_point": 1}.

## Tasks

| task | sample | steps (s, tokens, contract) | result by | 5.2.2 | 5.0.1 | assertions | seams | s | first problem |
|---|---|---|---|---|---|---|---|---|---|
| bw-01 | 0 | s1 24s 1502t ok, s2 61s 3745t ok, s3 40s 2429t x, s4 79s 4618t ok, s5 34s 2098t ok, s6 73s 4103t x, s7 75s 3069t ok | fallback | failed | failed | 1 failed | 0 | 511.11 | 5.2.2: line 216: AttributeError: bpy_prop_collection: attribute "links" not found |
| bw-03 | 0 | s1 179s 12433t ok | joined | failed | failed | 1 failed | 0 | 179.1 | 5.2.2: line 206: AttributeError: bpy_prop_collection: attribute "unlink" not found |
| code-10 | 0 | s1 15s 1034t ok, s2 37s 2512t ok | joined | – | – | – | 2 | 52.47 | – |
| batch-10 | 0 | s1 21s 1403t ok, s2 9s 538t ok, s3 19s 1218t ok, s4 19s 1231t ok, s5 19s 1243t ok, s6 11s 703t ok | joined | – | – | – | 1 | 98.66 | no_entry_point: no step defines main(), so the joined script runs nothing (seam missing_entry_point); Chimera's check would pass it without  |
