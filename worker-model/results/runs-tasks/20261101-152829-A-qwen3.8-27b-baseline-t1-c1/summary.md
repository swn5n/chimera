# Task-level run, arm A: today prompt, workers qwen3.8:27b, combine

2026-11-01T15:28:29-06:00 · combine model qwen3.8:27b · seam pass: none · Ollama 0.40.1 · Blender 5.2.2, 5.0.1

EVAL ONLY: model output for eval plans; never training data.

| tasks | Blender n | Blender pass 5.2.2 | 5.0.1 | both | Python n | Python pass | assertions | fallback | seams | cut off | runaway | steps runaway | steps kept the contract | steps in exact form | one script | reviewer done | median s | total s | tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 4 | 2 | 0% | 0% | 0% | 2 | 0% | 0% | – | – | 0% | 0% | 0% | 0% | 0% | 100% | – | 104.005 | 939.4 | 42682 |

Pass rates are over every task of the kind: Blender n is every plan with a Blender step, Python n every python-script plan without a files step. A result the check didn't run counts as a fail: unchecked {"blender": {}, "python": {"nothing_to_check": 1}}. pass: Chimera's check passed with no Traceback or Error: line in its 1,500-character output tail, and the direct run of the same script has none in its whole output. runaway: the combine or a lone step hit the reply cap (6144 content tokens for a step, thinking not counted) or the runaway guard (16384 tokens, thinking included); steps runaway: steps the cap or the guard cut ("in thinking": the guard hit while the model was still thinking). steps kept the contract: Chimera can join the piece (the near-miss handoff forms included, since Oct 30); in exact form: no errors and the contract's exact written form, what data generation keeps. no_entry_point (unchecked): a joined Python script where no step defines main(), which Chimera's check would pass without running anything. cut off: Ollama itself stopped at a length limit. one script: of the Blender tasks, results holding exactly one Blender script.

How the result was made: {"combine": 3, "lone": 1}; checks: {"checked": 3, "nothing_to_check": 1}.

## Tasks

| task | sample | steps (s, tokens, contract) | result by | 5.2.2 | 5.0.1 | assertions | seams | s | first problem |
|---|---|---|---|---|---|---|---|---|---|
| bw-01 | 0 | s1 15s 776t x, s2 65s 4583t x, s3 30s 2038t x, s4 58s 3932t x, s5 120s 0t x, s6 60s 2755t x, s7 55s 2119t x | combine | failed | failed | 1 failed | 0 | 651.27 | 5.2.2: line 55: TypeError: spin: keyword "dist_min" is invalid for this operator |
| bw-03 | 0 | s1 80s 5628t x | lone | failed | failed | 1 failed | 0 | 80.15 | 5.2.2: line 91: TypeError: NodeLinks.new(): error with argument 2, "output" -  Function.output does not support a 'None' assignment NodeSock |
| code-10 | 0 | s1 14s 926t x, s2 46s 3219t x | combine | – | – | – | 0 | 104.73 | – |
| batch-10 | 0 | s1 12s 745t x, s2 5s 324t x, s3 24s 1484t x, s4 13s 835t x, s5 12s 774t x, s6 8s 506t x | combine | – | – | – | 0 | 103.28 | nothing_to_check |
