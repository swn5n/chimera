# Task-level run, arm B: contract prompt, workers qwen3.8:27b, join

2026-11-01T17:08:20-06:00 · combine model qwen3.8:27b · seam pass: none · Ollama 0.40.1 · Blender 5.2.2, 5.0.1

EVAL ONLY: model output for eval plans; never training data.

| tasks | Blender n | Blender pass 5.2.2 | 5.0.1 | both | Python n | Python pass | assertions | fallback | seams | cut off | runaway | steps runaway | steps kept the contract | steps in exact form | one script | reviewer done | median s | total s | tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 4 | 4 | 50% | 50% | 50% | 0 | – | 0% | 75% | 0.5 | 0% | 0% | 0% | 76% | 76% | 100% | – | 270.82 | 1519.8 | 93709 |

Pass rates are over every task of the kind: Blender n is every plan with a Blender step, Python n every python-script plan without a files step. A result the check didn't run counts as a fail: unchecked {"blender": {}, "python": {}}. pass: Chimera's check passed with no Traceback or Error: line in its 1,500-character output tail, and the direct run of the same script has none in its whole output. runaway: the combine or a lone step hit the reply cap (6144 content tokens for a step, thinking not counted) or the runaway guard (16384 tokens, thinking included); steps runaway: steps the cap or the guard cut ("in thinking": the guard hit while the model was still thinking). steps kept the contract: Chimera can join the piece (the near-miss handoff forms included, since Oct 30); in exact form: no errors and the contract's exact written form, what data generation keeps. no_entry_point (unchecked): a joined Python script where no step defines main(), which Chimera's check would pass without running anything. cut off: Ollama itself stopped at a length limit. one script: of the Blender tasks, results holding exactly one Blender script.

How the result was made: {"fallback": 3, "joined": 1}; checks: {"checked": 4}.

## Tasks

| task | sample | steps (s, tokens, contract) | result by | 5.2.2 | 5.0.1 | assertions | seams | s | first problem |
|---|---|---|---|---|---|---|---|---|---|
| bw-02 | 0 | s1 25s 1600t ok, s2 70s 4442t ok, s3 85s 5350t ok, s4 90s 5806t ok | joined | pass | pass | 1 failed | 2 | 269.31 | – |
| bw-06 | 0 | s1 51s 3655t ok, s2 81s 5392t ok, s3 79s 5042t ok, s4 88s 5681t x, s5 71s 4142t x, s6 44s 2522t ok | fallback | failed | failed | 1 failed | 0 | 716.87 | 5.2.2: line 281: ValueError: bpy_struct: item.attr = val: sequences of dimension 0 should contain 4 items, not 3 |
| bw-07 | 0 | s1 25s 1716t ok, s2 51s 3382t ok, s3 77s 5111t ok, s4 57s 3383t x | fallback | failed | failed | 1 failed | 0 | 272.33 | 5.2.2: line 55: NameError: name 'COL_NAME' is not defined. Did you mean: 'COLL_NAME'? |
| bl-03 | 0 | s1 43s 2950t ok, s2 60s 3951t ok, s3 84s 5054t x | fallback | pass | pass | – | 0 | 261.26 | fallback: s3: uses_not_dependency: uses names s1, which s3 doesn't depend on (it depends on s2) |
