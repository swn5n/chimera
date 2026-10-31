# Hydra Worker 1.0: the sub-agent model (plan)

Oct 29, 2026. Status on Oct 30: decisions 2-4 answered (the rule; both baselines downloaded; v1 and v2 in the Trash),
1 is yours to answer now that the A/B below has run; 9 is moot (the pilot measured 193 tok/s); the rule's score half and probes a-c are done, d is open (see "Probes a-c"); `worker-model/` built; nothing trained. Made by a design panel (three designs from
different angles, two judges, one synthesis) that read Chimera's code and `helper-model/` and checked licences on the
model cards. Training data rule as for Hydra 1.0: no Claude output in training data (`helper-model/datagen/README.md`).

## Decisions that are yours

1. **Do you approve the sub-agent contract: the worker prompt, the mode rules, the 3-line handoff block, the user-message layout, the round-2 part and the repair message? Once training data is made it freezes, like the planner prompt.**
   - Recommendation: Yes, after reading it next to tonight's baseline A/B (today's prompt against the draft). That includes: Blender 5.0 or newer only, steps named s1-s8 by position, saving and rendering moved to the end of the joined script, and the opening kept as 'You are one worker in Chimera: a sub-agent'.
   - Why: No training data can be made until this is fixed. Any later change means retraining, just as Hydra 1.0's three prompts can't change without retraining it.

2. **Should the base model be chosen by this rule: Gemma 4 12B if its four probes pass (MLX speed and memory, the round trip into Ollama, template parity, fit on the 3080 Ti and M4 Pro) and its untrained score is within 5 points of Qwen3-14B; otherwise Qwen3-14B?**
   - Recommendation: Yes.
   - Why: Gemma fits the 16 GB GPU comfortably with a 32K context and should be about 20% faster, but nobody has run its pipeline on this machine yet. Qwen3-14B uses Hydra 1.0's proven pipeline but is only 'tight' on the 3080 Ti, with a 16K context limit. Both are Apache 2.0.

3. **OK to download gemma4:12b-it-q4_K_M (8.0 GB) and qwen3:14b (9.3 GB) for the baselines, and then the chosen base from Hugging Face (google/gemma-4-12b-it about 24 GB, or Qwen/Qwen3-14B about 29.5 GB)?**
   - Recommendation: Yes to both baselines and the base. Skip gpt-oss:20b (14 GB) and qwen3.5:9b (6.6 GB).
   - Why: The base can't be chosen or trained without them. The two optional models are already ruled out for training, so they would only be extra comparisons.

4. **OK to delete ~/chimera-tools/helper-train/v1 and v2 (37 GB)? Optionally also v3's leftovers (about 24 GB: fused, bf16 GGUF, q4/q6/q8), keeping helper-q5_k_m.gguf, the adapters and the Modelfiles.**
   - Recommendation: Yes to v1 and v2. Slimming v3 is optional.
   - Why: The managed disk peak is about 90 GB with Gemma and about 110 GB with Qwen, against 133 GB free. v3 replaced v1 and v2, and hydra:1.0 itself lives in Ollama.

5. **Can the Studio stop lending for about 4 nights of data generation (35-45 h, resumable) plus about a day of training? And may its Ollama be restarted with OLLAMA_NUM_PARALLEL=2 for those nights, then set back?**
   - Recommendation: Yes, on nights you pick in advance.
   - Why: gpt-oss:120b (65 GB) plus the Blender checks, and then 50-65 GB of training memory, leave no room for lending. Two parallel requests cut data generation by about a third, but setting that needs an Ollama restart, which interrupts the real Chimera on the Studio.

6. **Should 0.8.0 change what long tasks do? That means: the contract prompt for every worker step, Chimera joining Blender and Python pieces that follow it instead of a model combining them, step-only repair in looping mode, round-2 workers getting their part of the previous result, and the KV-estimate fix.**
   - Recommendation: Yes. Ship the contract, joining, repair and round-2 parts as phase 1, only if the task-level test shows they do at least as well as today (arm B ≥ arm A). Ship the KV fix with phase 2, when the model arrives.
   - Why: These change the behaviour of every long task, even on computers without the new model. The KV fix also changes how Chimera sizes gpt-oss and other sliding-window models.

7. **Should the result check also run in single-pass mode, not only with 'Keep going until done', when result checks are on, so that a crash gets one step repair?**
   - Recommendation: Not in v1; decide after the task-level eval.
   - Why: It changes what the existing setting means and adds time to every Blender or Python task.

8. **Should the model be named hydra:worker-1.0 ('Hydra Worker 1.0') or hydra:sub-1.0?**
   - Recommendation: hydra:worker-1.0
   - Why: It matches 'worker' in the code and prompts. The hydra: prefix already makes 0.7.0 builds keep it out of chats and ordinary steps.

9. **If the MLX pilot measures under 60 tok/s, should the data or layers be cut, or should a single 80 GB GPU be rented (a few dollars per run, on your account and payment)?**
   - Recommendation: Cut first: train only the top 32 layers, or use about 1,200 examples. Rent only for v2, if it's needed then.
   - Why: This keeps everything on the Studio, which is the only machine that can run the teacher and the Blender checks anyway.

10. **Can you spend about an hour at the 3080 Ti PC and the M4 Pro to measure the candidates' speed and memory use, and to try /api/blobs + /api/create on Windows?**
   - Recommendation: Yes, once the downloads are done.
   - Why: This is the evidence for the fleet part of the bar. It can't be measured remotely, and the Windows install path is still unverified.

## Tonight's A/B (Oct 30, stages a, b and e of run_baselines.sh)

From `worker-model/results/BASELINES.md`: the quick subset's 36 W2-W4 cases, one sample each (gpt-oss:120b two,
qwen3:4b three), unseeded, as Chimera 0.7.0 sends them (think unset, num_ctx 8192). Done 00:57-07:29, no failed runs.
The numbers below are after the Oct 30 rescore (see the next section): the scorer had counted pieces whose build
never ran as passes.

- **The contract costs nothing in correctness.** Strict Blender pass in 5.2.2, paired by case and sample: of the
  replies that passed under only one prompt, 21 passed only under today's and 20 only under the contract, over all six
  models (74 against 73 passes of 270). With the scene assertions too, 19 against 20. Per model the strict gap is 0-2
  passes either way (qwen3:14b 30% today, 23% contract; Gemma 20%, 27%; qwen3.8:27b 57%, 50%; gpt-oss:120b 38%, 38%;
  qwen3:8b 23%, 30%; qwen3:4b 13%, 12%).
- **It makes pieces joinable.** Contract kept: 86-89% for the 12B and bigger models, against 0-6% under today's
  prompt. qwen3:14b's 25% under today's prompt is its W3 repairs, whose input already holds a contract piece. The small
  models keep it 75-77% but only 43-47% in the exact form, so they write near-misses.
- **The 8K bucket is too small for thinking workers.** Gemma 4 stops at the window: 14-19% of its replies ran out
  at the 8,192-token window (all its "cut off"; 8 of the 12 with no answer at all, 4 cut mid-script). The Qwen3 models run past it by shifting the context (up to
  19,049 tokens in an 8K window), so they lose the start of their prompt mid-reply. Today's Chimera does the same
  (a worker step's `NeedCtx` is its prompt plus 4,096).
- Even the teacher crashes on most traps: gpt-oss:120b passes 38% strict, which sets the data-generation yield
  (best-of-N with checks). qwen3.8:27b is the best untrained worker (50-57%, the fewest API errors per reply).
- Fixed on the way: the validator didn't read a File: line wrapped in bold (`**File: src/notes.py**`, gpt-oss:120b's
  form), so it rejected the teacher's code-file replies. Re-scored (gpt-oss:120b contract kept 80% to 86%), and
  `code-01`/`code-12` were dropped from `eval/frozen/deps.json` so the next freeze redoes them.
- Frozen: 54 plans (10 from gpt-oss:120b, 44 from hydra:1.0); dependency outputs for the quick tasks, 11 verified and
  13 rejected over 10 tasks. Stages c (W1 steps), d (T1 arms) and f (the other tasks' dependencies) aren't run.

## The base-model rule's score half (Oct 30, stage g: thinking off)

The trained worker runs with thinking off, so the rule's score is measured that way: stage g of run_baselines.sh,
both bases under the contract prompt with `"think": false` (each model's own switch, no new Ollama models), 3
samples per Blender and code case: the 36 W2-W4 cases and the 18 W1 steps with frozen inputs (11:04-12:26, no
failed runs). Then two independent audits of the raw replies (seven checkers and two rounds of skeptics). Their
fixes, then a rescore of all 16 baseline runs from the stored replies (`runner/rescore.py`, no model calls):

- **Fixed: empty passes.** A piece that broke a mode rule wasn't joined and ran on its own; with no main guard its
  build function was never called, so the untouched factory scene passed strict. 15 replies over all runs, 7 of
  Gemma's 29 thinking-off W2-W4 passes and 2 of qwen3:14b's 21; called now, each hits a real API error (14 definite
  crashes, 1 the check rates unsure). That
  gap was +8.9 before the fix and is +3.3 after it. Also: a piece run after its dependencies gets their ctx; dependencies that don't join share one ctx;
  a script that only defines things counts as having nothing to run.
- **Fixed in the validator:** two near-miss handoffs (a closing fence missing at the end; an unfenced copy just
  above the block) and `bpy.data.objects.clear()` as a scene wipe. The report's gap lines said "(within 5)" for
  every gap of -5 or better, +40.5 included; they now give the exact counts, the verdict, the one-sided pairs with
  McNemar's p and a case-bootstrap 90% interval.

Thinking off, Gemma 4 12B minus qwen3:14b, paired by case and sample:

| reading | Gemma | qwen3:14b | gap | 90% interval (case bootstrap) |
|---|---|---|---|---|
| All parts strict 5.2.2 (the plan's main number, every part of the quick subset) | 31/120 | 29/120 | +1.7 | -6.7 to +10.0 |
| W2-W4 strict 5.2.2 | 22/90 | 19/90 | +3.3 | -7.8 to +13.3 |
| W1 strict 5.2.2 (10 steps) | 9/30 | 10/30 | -3.3 | -16.7 to +6.7 |
| strict + scene 5.2.2 (W2-W4; W1 has no assertions) | 15/90 | 17/90 | -2.2 | -10.0 to +4.4 |
| W2-W4 contract kept | 94/102 | 91/102 | +2.9 | -2.9 to +9.4 |
| W1 contract kept | 36/42 | 21/42 | +35.7 | +13.6 to +57.1 |

- **The score half passes as written:** every line is -5 or better. Margins in samples: W1 strict 1 (one more qwen
  pass would make it -6.7), strict + scene 3, all-parts strict 9.
- **But this subset can't tell the two apart on correctness.** No strict difference is significant (McNemar p 0.65
  to 1.0), and every strict interval reaches below -5: the data fit Gemma being 7 (all parts) to 17 (W1) points
  worse as well as ahead. Narrowing that takes more cases, not more samples.
- Gemma's W2-W4 strict lead is its W3 repairs (15/30 against 11/30), and 4 of its 15 strict passes there don't build
  the asked-for scene (strict + scene 11 each). On the W2 API traps Gemma is slightly behind (7/48 against 8/48;
  with the scene 4 against 6). W4f and W4l: none pass for either.
- **The one clear difference is keeping the contract on W1 steps** (+35.7, McNemar p < 0.01): where a step says to save, qwen3:14b
  called the save itself in 10 of 12 samples (Gemma in 2, and it used `SETTINGS_sN["output"]` in 6); it also left out
  SETTINGS_sN (6 samples), the main guard (3) and the File: line on code-01/s1 (3). Both cleared the scene equally
  often (5 samples each). That's what training teaches, so it argues less for Gemma than it looks. The W2-W4
  contract lead (+2.9) comes from qwen3:14b's 4 replies that ran to the runner's 6,144-token cap in repetition loops.
- **Thinking on against off** (stage a, one sample) shows no measurable change for either model on W2-W4.
- **Not settled by this:** the full eval (this is 30 of 57 W2-W4 Blender cases and 10 W1 Blender steps). The probes
  are in the next section.
- **Eval issues found, for w1.1:** one frozen W1 step (bw-03/s1, "Clears the default scene") conflicts with the
  blender mode rule; both models fail it in all 3 samples. And `runner/cases.py`'s `input_reply` appends a
  second handoff block to long inputs that already end with one (w4l-04 s1-s4, w4l-05 s1-s3; w4l-05 s7's input is
  stitched from two pieces with a handoff each), so those inputs never join. Fixing either changes the prompts, so it waits for the next eval version.

## Probes a-c (Oct 30, on the Studio)

Scripts in `worker-model/probes/`, results in `worker-model/results/probes/` (its README says which file is which).
An independent audit (three auditors and a skeptic) checked them and found a real fault in the first probe (c), which
is fixed; a and c were then run again on the fixed path.

| Probe | Bar | Result | Verdict |
|---|---|---|---|
| (a) MLX pilot | 60 tok/s or more in all, peak under 75 GB | 193.1 tok/s in all (51.8 answer tok/s), 65.2 GB | Pass |
| (b) Round trip | At temperature 0 it answers like gemma4:12b-it-q4_K_M | Q5_K_M: same prompts, closer to the full-precision model than the official Q4_K_M | Pass (a Q4 side test of ours retired by you, below) |
| (c) Template parity | Token for token, empty thought block included; no thought text in the reply | 176 of 176 eval requests token for token (all that can be built today; 80 more W1 steps wait on frozen dependency outputs); no thinking with no think field | Pass |
| (d) Fleet fit | /api/ps size_vram at 8K, 16K and 32K on the 3080 Ti and M4 Pro, 100% on the GPU | Not run: needs you at those machines (steps: `docs/probe-d-steps.md`) | Open |

**So the rule stands at: the score half and probes a, b and c pass, d is open. If d passes, the base is Gemma 4 12B.**

(a) One pass of the 40 examples at batch 1 (the rule says "20 iterations on 40 examples", which can't cover them), in
the worker's prompt form (no `<|think|>`, the empty thought block; the text is Hydra 1.0's data stitched to length,
with its reviewer system prompt, since no worker data exists yet), with the plan's settings: rank 32, all 48 layers, gradient accumulation 8, mean 3,934 tokens,
longest 11,824, 815 s. MLX's active memory peaked at 65.2 GB. Audit figures at the 12,288 limit: about 67 GB, and 75 s
per example uncapped, 86.5 s with the cache cap, so the bar holds there too. With MLX's cache capped at 8 GB (see
below), active plus cache was 66.7 GB and the system's wired memory 78.9 GB, with a 10.7 GB Ollama model still loaded for
the first minutes. At this speed the plan's 5.1M tokens take about 6-8 h, not 14-16 h. Sustained speed over hours
isn't measured (the longest run is 14 minutes).

(b) The conversion is exact. An empty adapter (all 328 lora_b tensors zero) fused to 666 text tensors byte-identical
to Hugging Face's. The GGUF's tokens, scores and token types equal the official file's on all 262,144 entries, and
its bf16 weights equal Hugging Face's on all 666 tensors. The official file has 239 more merges, which build junk
tokens and changed nothing in 3.6M tokens of real text; ours equal tokenizer.json, which is what training uses.
Prompt token counts match the official model on all 8 requests (and on 7 more in the audit). Our Q5_K_M agrees with
the official on the first 16 tokens of 7 of 8 replies (the bar we set before running: 6).

**Decided by you on Oct 30: the Q4 side test is retired, and it stays as a diagnostic only.** The same script also asked that our Q4_K_M match the official's on the first 32 tokens of 6 of
8 replies. It matched 2, so `probe-b.json` says `"pass": false`. That test compared unlike things: the official Q4_K_M was
quantized with an importance matrix (imatrix) and ours without. It isn't in the rule, which names Q5_K_M. Mean KL divergence
from our bf16, and how often the top token matches:

| Model | KL divergence | Same top token |
|---|---|---|
| Our Q5_K_M with an imatrix | 0.292 | 87.6% |
| Our Q5_K_M | 0.379 | 84.8% |
| Our Q4_K_M with an imatrix | 0.445 | 83.5% |
| The official Q4_K_M | 0.475 | 83.3% |
| Our Q4_K_M | 0.750 | 77.0% |

First-N agreement is also a noisy bar: unquantized bf16 reaches the official's first 16 tokens on only 10 of 15
requests, the same as Q5_K_M. `probe-b.json` stays as measured, with that `"pass": false`; the decision is recorded
here and in `results/probes/README.md`.

(c) What it took:
- Ollama 0.40.1 ignores a TEMPLATE on a gemma4 model: `ollama create` adds RENDERER gemma4 and PARSER gemma4. That
  renderer thinks unless told otherwise, and with `think: false` it wrote the empty thought block only on the official
  manifest, not on a model from the same weights.
- **`RENDERER gemma4-large` with `PARSER gemma4-no-thinking`** is the worker's setup: the renderer writes the block
  whenever thinking is off and the parser takes the thinking capability away, so with both, thinking is off with no
  think field and the block is always there. No Chimera change is needed for a step. Streamed replies as
  Chimera sends them are clean: all text in `content`, `done_reason` "stop", no markers (audit).
- The training side needs a patched template too (`probes/template_parity.py`, `worker_template`). MLX-LM's tokenizer
  wrapper passes `enable_thinking=True` for Gemma 4, so stock training puts `<|think|>` in the system turn and no empty
  block: 0 of 176 requests matched Ollama's prompt. The first probe (c) called the HF tokenizer directly, which
  defaults to no thinking, so it passed while the real path was wrong; the audit caught it. With the template fixed,
  through MLX-LM's own dataset code: 176 of 176 prompts token for token, and every target is the answer plus
  `<turn|>` and a newline.
- Every worker request is system plus user (repairs and round 2 are in the user message), so assistant-turn history
  doesn't arise. It would differ by 4 tokens per earlier turn, so train on one assistant turn and keep the worker out
  of chats.

**Before training (from the audit):**
- Train through a driver that caps MLX's cache (`probes/mlx_train_driver.py`, 8 GB): `mlx_lm lora` has no such option,
  and uncapped, a 9.5 GB Ollama model loaded alongside crashed a near-limit example with a Metal out-of-memory error.
  Keep Ollama from loading models during the run.
- Move `named_specials` (`probes/round_trip.py`) into the worker's GGUF step and fail the build unless the token types
  equal the official's and a rendered prompt tokenizes like HF's. Without it `<|turn>` splits into `<`, `|`, `turn` and
  every prompt is wrong, because the converter's transformers 4.57 doesn't count Gemma's named tokens as special.
- Data generation rejects answers holding `<|channel>` or `<channel|>` (the template would alter them).
- Add Q5_K_M with an imatrix at the quant gate (about 5 minutes), calibrated on training text only, never eval or
  Claude text; use KL divergence rather than first-N agreement; any Q4_K_M scored needs an imatrix too.
- The worker's create step adds the Apache 2.0 licence text. No DRAFT: the official's draft model isn't ours, so the
  official's speed may not carry over; that's unmeasured.
- If probe (d) sends the rule to Qwen3-14B, it needs this same MLX-against-Ollama check: `enable_thinking` applies there
  too, and its template isn't downloaded.
- For the next eval version: none of the 176 eval requests that can be built today lies between 2,830 and 7,799 real
  tokens (80 more W1 steps wait on frozen dependency outputs), and every W4L case is above workerMaxCtx, so W4 can't
  set that limit as planned.

**For 0.8.0 (from the audit):**
- Get from host must carry the renderer and parser: `/api/show` has them only as Modelfile lines, and today's install
  body makes a model that thinks on the wrong prompt. `/api/create` accepts both on 0.40.1 (Mac).
- `/api/create` doesn't validate them: an unknown name says success, then every chat fails with HTTP 500. After
  creating, check the Modelfile lines and `thinking.default` false, and set a minimum Ollama version once we know which
  release added these names. Windows and other Ollama versions are unchecked.
- Send `"truncate": false` on worker steps: at num_ctx 8192 a prompt of 8,192 tokens or more is silently cut to about
  4,099 with HTTP 200. Rare, but it loses the system prompt.
- The KV estimate fix is already planned; until it ships Chimera marks our Q5_K_M too big for 15.5 GB (`/api/ps` shows
  9.46 GB at 8K). Probe (d) reads `/api/ps` directly, so it doesn't need the fix.

Not checked by any of this: a trained adapter through the whole path into Ollama, Windows, and the other computers.

## Work that needs no decision (in order)

- Set up worker-model/ next to helper-model/, reusing runner/ollama_client, check_overlap and the Store pattern, with a gitignored data folder. Write a disk ledger without deleting anything. (about 1 h)
- Build the Blender tooling: a wrapper that runs `chimera --check-result` once per Blender version, with a PATH shim and a fresh --data-dir each time (5.2.2 is /Applications/Blender 3.app, 5.0.1 is /Applications/Blender.app), and asserts the 'running it in Blender X' line. Add the strict pass rule (exit 0, no Traceback or Error line), the scene-probe epilogue, the Python test harness (-I, 30 s, a test counts only if it fails on a stub), and a script that dumps Blender's own RNA and socket facts from both versions for teacher-only hints and the removed-API lint. (about 0.5 day)
- Write the draft contract as a Python prototype, for measuring only (not in app/): prompt builder, piece validator, Blender and Python joiner with a line map, file merge and handoff parser. (about 0.5-1 day)
- Write the worker eval with a new canary: W1 (the 44 existing long-task prompts plus 10 new Blender tasks), W2 (30 Blender 5 API traps, each checked by running it in both versions), W3 (20 real-crash repairs), W4 (failed-dependency and long-input cases), hidden tests, and the 60-case quick subset. Freeze plans from hydra:1.0 (gpt-oss:120b for about 10 tasks) and dependency outputs from gpt-oss:120b, verified. Extend tools/check_overlap.py to it. (about 1 day of writing plus 3 h of compute)
- Write the task-level runner, a Python port of onePass using the prototype joiner, with qwen3.8:27b fixed as the seam and combine model. (about 0.5 day)
- Run the overnight baselines on installed models: gpt-oss:120b, qwen3.8:27b, qwen3:8b and qwen3:4b-instruct-2507, each with today's workerPrompt and with the draft contract, on the quick subset, plus T1 arms A, A2, B and C. Ask the user to switch lending off for clean timings; it isn't a blocker. This shows where today's workers crash, by API area, and whether the contract and joining help untrained models. (about 8-10 h of machine time)
- Write the data-generation code for every stage (seeds from topic labels, plans, step inputs in dependency order, adaptive best-of-N, checks, combinability, repairs, build) and run a 20-seed smoke test with the draft contract. The smoke data is thrown away; it measures acceptance rates and seconds per sample to re-budget the 35-45 h estimate. (about 1.5-2 days plus 2 h)

## Work after the decisions

- After the contract is approved: move it into Go. That means workerPrompt, workerKindRules and the repair message in prompts.go, the new hydra_assemble.go, and CLI modes --hydra-worker-request and --hydra-assemble, plus Go golden tests, check_prompts_sync for the new frozen texts and fake_ollama_hydra.py updates. Data generation then switches to the binary as its only source of truth. (about 1.5-2 days)
- After the download OK: run the base baselines on gemma4:12b-it-q4_K_M and qwen3:14b (about half a night). Then the probes: the MLX pilot (30 min); the round trip into Ollama 0.40.1 with token-level template parity, including the empty thought or think block (2-3 h); and, with the user, the fleet fit and speed checks on the 3080 Ti and M4 Pro (about 1 h). Then confirm the base by the rule.
- After the deletion OK (helper-train v1 and v2): download the chosen Hugging Face base (24-30 GB). Delete temporary files strictly in order: the fused model after conversion, the bf16 GGUF after quantizing.
- Run data generation with lending off: night 1 (smoke run, then about 12 h). Next day, train v0.1 on about 500 examples (about 2 h at the Oct 30 pilot's speed), carry it through GGUF, import and the quick eval to prove the pipeline and the contract. Then nights 2-4 for the rest (about 25-30 h), to about 1,700 kept examples.
- Train v1 (about 6-8 h for Gemma by the Oct 30 pilot; Qwen is unmeasured, and its 17-19 h estimate comes from the scaling that was about twice too slow for Gemma). Then fuse, GGUF and the quants one at a time, imported as hydra:worker-dev-<run> (1-2 h). Then the full W1-W4, T1 and T2 eval and the temperature study (about 8-10 h). Pick the quant: Q5_K_M unless the bf16 comparison says otherwise.
- Chimera 0.8.0 phase 1 (it can overlap data generation): the contract prompt, joining, seam pass, step repair in looping mode, round-2 parts and card lines, shipped only if T1 arm B ≥ arm A. Then go test, hydra_test.py additions, run_it.py and heads_text_test.py. (about 2 days)
- Phase 2 with the model: the KV-estimate fix, workerFor per kind from the eval table, the shared-model list in helper_share.go (with RENDERER and PARSER: Gemma needs them, see Sharing), the Models page row, credits, and worker_test.py. Then real machines: host first, Get from host on the PC (Windows /api/blobs) and the Macs, one real looping Blender task, and T3 on the pool. Add the CLAUDE.md rule: hydra:worker-1.0 only on 0.8.0 or newer, host first. (about 2-3 days)
- Plan v2 from v1's failures, grouped by API area and error: targeted seeds, on-policy rejection sampling with teacher repairs, possibly DPO or ORPO on verified pass/crash pairs, longer inputs. Same frozen eval and the same bar.

## The plan in full

HYDRA WORKER 1.0: THE SUB-AGENT MODEL (final plan)

IN SHORT
Build "Hydra Worker 1.0" (Ollama name hydra:worker-1.0). It is a 12-15B model trained on one job only: one Hydra worker step, done under a new, frozen sub-agent contract. The contract is how the pieces fit together at the end of the chain:
- Every worker is told it is step sN of n.
- It sees what each sibling step is doing.
- It writes its piece in a fixed shape for its kind: a Blender step is `def build_sN(ctx)`; a code step is functions in one shared file, or labelled files; a prose step is one "##" section.
- It ends with a 3-line handoff (provides / uses / assumed).

Chimera then joins Blender and Python pieces itself, with no model, and runs the existing result check on the joined script. A crash inside build_sN re-asks step sN alone.

Training data comes from gpt-oss:120b answering Chimera's exact worker request on real hydra:1.0 plans. An answer is kept only if it runs in Blender 5.2.2 and 5.0.1, both alone and joined with the rest of its plan.

The contract and the joiner can ship in 0.8.0 before the model exists, if the eval shows they help ordinary models. After that, the model gets worker steps kind by kind, only where it beats today's workers.

This plan starts from the two top-scored designs, "fleet-and-eval" and "data-first" (tied on the judges' totals). It takes from "contract-first" the Go-only source of truth, the validator, the line map and step repair, and the seam pass. It fixes every must-fix item.

FACTS I RE-CHECKED TODAY (Oct 29)
Gemma 4 12B:
- It exists. The Hugging Face card for google/gemma-4-12b-it says Apache 2.0, 11.95B parameters, 48 layers (40 sliding-window layers with a 1024-token window, 8 global layers with 1 KV head of 512 and K=V), 262K vocabulary, 256K context.
- Its pretraining "cutoff date of January 2025". It is not newer than Qwen3, so Blender 5 knowledge has to come from the verified data whichever base wins.
- With thinking off, the 12B "still emits an empty thought block".
- Ollama tags: gemma4:12b-it-q4_K_M is 8.0 GB.

Qwen3-14B:
- The card says Apache 2.0, 14.8B, 40 layers, 40 query heads and 8 KV heads, 32K native context.
- enable_thinking=False is a hard switch that turns thinking off.

MLX-LM 0.32.2, installed on the Studio:
- It maps gemma4_unified to gemma4.
- qwen3_5.py passes use_kernel=not self.training, so training falls into a per-token loop (gated_delta.py line 590, `for t in range(T)`).

The local llama.cpp (commit c3df4b7, Oct 28) registers Gemma4UnifiedForConditionalGeneration. It writes key_length 512 and a per-layer head_count_kv array. Because of that, Chimera's parseShow (app/ollama_monitor.go) would estimate 0.8-1.6 MB of KV cache per token. That makes Gemma Q5_K_M too_big on the 3080 Ti.

Blender --check-result:
- It uses a `blender` on PATH first, otherwise the newest app.
- 5.2.2 is /Applications/Blender 3.app, 5.0.1 is /Applications/Blender.app, and 3.6.23 is /Applications/Blender 2.app.
- So checking in both versions needs a PATH shim and a fresh --data-dir for each run.

Blender steps in the planner's own data: of the 357 Blender steps in helper-model/data/sft-v3, about half mention a .blend file (172) or saving (175).

The fake Ollama: tests/plugin-network/fake_ollama_hydra.py line 147 routes on the opening "You are one worker in Chimera".

The Studio's lend limit and the pool:
- The Studio lends models up to 57 GB, so gpt-oss:120b (65.4 GB) never does pool work.
- Today's worker steps go to the biggest shared model: the hub scores size×10, times 0.6 if the fit is tight, plus 30 if loaded, minus eta.

Correction to one of the designs: on Oct 29 it was gpt-oss:120b's plan, not hydra:1.0's, that turned the Blender studio task into a code step plus a writing step. hydra:1.0 planned 3 Blender steps.

Fleet, from hub.json:
- FX3: M3 Ultra, 96 GB
- FX1: M4 Pro, 24 GB
- FX2: M4 Max, 36 GB
- The 3080 Ti PC has not joined yet.

Disk: 133 GiB free. helper-train v1 is 19 GB, v2 18 GB, v3 28 GB.

1. BASE MODEL

Shortlist:

(1) Gemma 4 12B (google/gemma-4-12b-it). Licence Apache 2.0. Provisional pick.
- Dense; it trains with ordinary LoRA layers in MLX-LM 0.32.2 (vision and audio weights are stripped).
- Into Ollama: either mlx_lm fuse, then train/gguf_source.py, then llama.cpp convert_hf_to_gguf.py, then llama-quantize, then ollama create; or Ollama's own import from the safetensors folder with --quantize. Use RENDERER gemma4-large and PARSER gemma4-no-thinking (see "Probes a-c"): Ollama 0.40.1 ignores a TEMPLATE on gemma4 models, and the official model's lines (RENDERER gemma4, PARSER gemma4) think, and leave out the empty thought block on our model.
- Its real KV cache is about 0.34 GB for the windows plus 8-16 KB per token. So Q5_K_M (about 8.5 GB text-only, an estimate) needs about 9.4 GB at 8K and about 10 GB at 32K: "comfortable" on the 3080 Ti and on the M4 Pro (24 GB).
- Estimated speed at Q5_K_M (Chimera's estTokS; hydra:1.0 measures about 75% of its estimate on the Studio):

| Computer | tok/s |
|---|---|
| 3080 Ti | ~36 |
| Studio | ~58 |
| M4 Max | ~29 |
| M4 Pro | ~19 |

- Training at 12B is about 20% cheaper than Qwen3-14B.
- Risks: a new pipeline (a unified checkpoint, the empty thought block, RENDERER/PARSER on import and on sharing), and the 262K-vocabulary logits use a lot of training memory.

(2) Qwen3-14B (Qwen/Qwen3-14B). Licence Apache 2.0. The fallback, and the choice on a tie or if any Gemma probe fails.
- Exactly hydra:1.0's pipeline: MLX qwen3, llama.cpp Qwen3ForCausalLM, Ollama's qwen3 template with the empty think block forced (Chimera never sends think).
- KV cache 160 KB per token.
- In Chimera's fit maths it is "tight" on the 3080 Ti at both Q5_K_M (10.5 GB) and Q4_K_M (9.3 GB), with CtxMax 16K. It is tight at Q5_K_M on the M4 Pro too.
- Estimated speed:

| Computer | Q5_K_M | Q4_K_M |
|---|---|---|
| 3080 Ti | ~29 tok/s | ~33 tok/s |
| Studio | ~47 tok/s | |
| M4 Max | ~23 tok/s | |
| M4 Pro | ~16 tok/s | |

(3) Qwen3.5-9B. Licence Apache 2.0 (card read by the design panel). Baseline only, optional. MLX-LM trains its DeltaNet layers token by token, which is impractical for 8-12K-token examples. It is trainable only on a rented CUDA GPU.

Rejected:
- gpt-oss-20b (Apache 2.0): LoRA on MXFP4 experts means de-quantizing and re-quantizing, which loses its quantization-aware training. Harmony reasoning eats each step's room. Its 14 GB leaves about 8K of context on 16 GB.
- Ministral 3 14B: FP8 weights.
- The 24-35B catalog models: they don't fit 16 GB with context.

Decision rule, fixed now. Gemma 4 12B wins if all four probes pass and its untrained contract score on the worker eval is within 5 points of qwen3:14b:
- (a) MLX pilot: 20 LoRA iterations on 40 real-length examples, at 60 total tok/s or more, with peak memory under 75 GB.
- (b) Round trip: fuse an empty adapter, convert to GGUF, quantize to Q5_K_M and import. At temperature 0 it must answer like gemma4:12b-it-q4_K_M.
- (c) Template parity, token for token, between the prompt MLX trains on and the one Ollama renders, empty thought block included. The reply Chimera receives must carry no thought-block text.
- (d) /api/ps size_vram at 8K, 16K and 32K on the 3080 Ti and the M4 Pro, with 100% on the GPU.

Otherwise Qwen3-14B.

2. THE SUB-AGENT CONTRACT
The planner, reviewer and gate prompts stay unchanged, and so does the plan JSON (title, kind, summary, steps with id, title, kind, instructions, depends_on). Once training data is made, these freeze: the worker system prompt, the mode rules, the handoff block, the user-message layout, the round-2 part and the repair message. check_prompts_sync covers them.

Chimera names steps by position, s1 to s8 (cleanPlan allows 8), so names like build_s2 are always valid Python.

Modes, chosen by Chimera from the content:
- blender: a step of kind blender, or a code step in a plan whose goal, summary or instructions mention Blender or bpy (the fallback planner mislabels these).
- python-script: other code steps in a Python plan that names no file paths.
- files: code plans that name paths, or other languages.
- section: writing, research and general steps.

WORKER SYSTEM PROMPT (proposed text; it keeps the opening the test fake routes on):

"You are one worker in Chimera: a sub-agent. A planner split a person's task into steps, and AI models on different computers are doing them at the same time. You do step s{i} of {n}. When every step is done, Chimera joins the pieces into the finished result, so build only your piece, exactly in the shape below, and leave the other steps' work to them. Nobody will answer questions: if something is missing, make a sensible assumption and say so in your handoff.

Project: {title}
{summary}

The plan (→ is your step; the others are there so you can use their names and stay out of their way):
  s1. {title} [{kind}]: {its instructions, cut to 300 characters}
→ s2. {title} [{kind}] (uses s1): your step, in full below
  …
{Steps that use your piece: s3. | Nothing else uses your piece: it goes straight into the finished result.}

How Chimera joins your piece:
{mode rules}

End with this block, one short line each ("none" if there's nothing):
```handoff
provides: what your piece makes that other steps or the result use, by exact name
uses: what you took from which step, by exact name
assumed: what you had to guess
```"

Today's refsBlock follows, unchanged. A lone step gets "You are one worker in Chimera, and the only one on this task: your reply is the finished result the person gets", the same mode rules, and no handoff.

MODE RULES (frozen)

blender:
"Write one python code block for Blender 5.0 or newer, run headless with blender -b --python. At the top level put only imports, one dict SETTINGS_s2 = {...} with the values a person might want to change, and def build_s2(ctx): holding all your step's work (helpers go inside it or are named _s2_…). End with if __name__ == "__main__": build_s2({"scene": bpy.context.scene, "collection": bpy.context.scene.collection, "objects": {}}). Chimera calls every step's build_ function in plan order in one script with one shared ctx: ctx["scene"]; ctx["collection"], the project's collection, where you link everything you create; ctx["objects"], where you register what other steps use under short keys (ctx["objects"]["table"] = obj) and find what your dependencies list under provides. If one is missing because your piece runs alone, make a simple stand-in and print("chimera: stand-in", key). Name new objects, materials and collections chimera_…. Prefer bpy.data over bpy.ops. Don't open, load or save .blend files, render or quit: if your step says to, put the path or render settings in SETTINGS_s2["output"] and Chimera does it once, after the last step; if it says to open a file another step saved, use what that step built, which is already in the scene. Don't delete or change what you didn't create, and change scene-wide settings (engine, world, colour management) only if your step is about them."

Why the file rule: in a joined script, opening a .blend file wipes the earlier steps' work, and the check stops at the first render.

Today's rule says "4.x or 5.x". This changes it to 5.0+, the only versions that can be checked here.

python-script:
"Write Python 3 functions and classes only, in one python code block, with no code that runs on import. Chimera puts every step's code into one file in plan order. Use exactly the names the plan gives and don't redefine another step's names. If your step runs the program, define main(); Chimera calls it at the end."

files:
"Give each file you own in full, in its own fenced block with the language named, with its path on the line just before it, like File: src/store.py. If another step also writes that file, give only your part, marked File: src/store.py (part). Import other steps' code by the plan's exact names. No placeholders, TODOs or stubs for other steps' parts. Under provides, list your files and public signatures and, if your step runs the program, how."

section:
"Write only your section, starting with ## and the heading your step gives (else its title). No introduction, conclusion or summary of the whole project unless that is your step; don't repeat what other steps cover; use your dependencies' terms; match any tone and length your step gives; don't mention that you're an AI or that there are other workers."

Research adds: "Give concrete findings. You have no internet: never invent sources, links, numbers or quotes; mark anything uncertain (unverified)."

USER MESSAGE (frozen layout)
"Your step, s2: {title}
{instructions}

From s1, "{title}" (you use it):
Its handoff: {its three lines}
{its piece without the handoff, up to 8,000 characters, or: (that step failed; assume what you need and list it under assumed)}"

From round 2 on, two parts are added:
- "Last round's result for your part:", followed by the matching build_ function, file or section of the previous joined result (matched by title or path), or else that result cut to 6,000 characters.
- "What still needs work:", followed by the critique.

Today, workers in later rounds never see the previous result; only the planner does (onePass).

REPAIR MESSAGE (looping mode, used when the line map places a crash inside build_sN)
The step as above, then:
"Your piece crashed when Chimera ran the joined script in Blender {version}:
line {L} in build_s2: {source}
{exception}

Your piece was:
{piece}

Give your whole piece again, fixed, in the same shape and with the same names. Running stops at the first error, so check the rest of your piece against Blender {version}'s API too."

Blender API notes stay out of the worker's prompt in v1. They go only to the teacher, so no Claude-curated text enters training inputs and nothing extra ships with Chimera.

JOINING
New Go code on the asking computer, in app/hydra_assemble.go. Nothing is trained on it, so it can change freely.

Validation of every piece:
- exactly one handoff block
- blender: exactly one python block whose column-0 lines are only imports, SETTINGS_sN, def build_sN, _sN_ helpers, comments, docstrings and the main guard
- files: every block has a File: line
- section: starts with "## "

Blender:
- One script: imports deduplicated; a "# Settings" part with every SETTINGS_* dict at the top; the build functions in plan order (cleanPlan keeps dependencies only on earlier steps, so plan order is valid).
- main() makes ctx with a chimera_<slug> collection, calls build_s1(ctx) and the rest, then does the save or render from SETTINGS_*["output"] once.
- A line map records which lines belong to which step.
- A library-reuse step (runStep writes a bare fenced block) is indented into build_sN(ctx). If it has star imports or its own main guard, it counts as a seam.

python-script: joined the same way, with main() called at the end.

files:
- Merged by path.
- "(part)" blocks are merged when they hold only imports, defs, classes and constants.
- Every "uses" must match a "provides", and every `from X import a` must resolve.

Sections: "# title" plus the sections in plan order, then the editor joins them and keeps their content.

Seam pass:
- When it runs: a crash in main(), a NameError or KeyError on a provided name, duplicate top-level names, a "uses" with no matching "provides", or a file conflict.
- It runs on the largest model and returns only the functions or files that change, so its replies stay short and don't get cut off.
- Its prompt starts "You are Hydra's final editor", so the test fake still routes it.

Fallback: any piece that breaks its mode rules sends the task to today's synthPrompt combine, with the handoffs added, and the card says why. Handoff blocks are stripped from the result, and the "assumed" lines become an Assumptions note on the reply.

Looping mode:
- A definite crash inside build_sN gets a repair request for sN alone (at most 2 per round), then the script is joined and checked again, before the review.
- Only crashes outside the pieces, repeated faults and review critiques go back to the frozen planner. This targets the Oct 29 problem that each round rewrote large parts.

hydraStep gains handoff, mode, repairs and lines.

3. TRAINING DATA
Rule: no Claude output in training data. Claude writes only code, topic labels, teacher instructions and rubrics, the probe, lint and harness, and the eval set. The worker prompt itself is app code, like the three prompts Hydra 1.0 was trained on.

Go is the single source of truth. Data generation builds requests and joins pieces with new modes of the Chimera binary (--hydra-worker-request and --hydra-assemble, beside --check-result), so there is no Python copy to drift. A Python prototype is used only for measuring, until the contract is frozen.

Tasks:
- About 830 from the helper's 951 teacher seeds: all but the 179 single-step small_task seeds, of which about 60 are kept for lone steps.
- About 500 new teacher-written seeds from about 70 Claude-written topic labels:
  - Blender, 300: modelling, modifiers, geometry nodes from Python, materials, lighting, cameras and keyframes, render and 5.x compositor settings, scatter, bmesh, simulations.
  - Runnable Python, 150.
  - Mixed Blender plus writing, 50.
- Deduplicated with 5-word shingles, and checked with check_overlap against eval/, eval-long/ and the new worker eval.

Plans:
- Chimera's exact, frozen planner request: about 70% from hydra:1.0 (about 4 s each) and about 30% from gpt-oss:120b, the fallback planner (raw/plans*.jsonl reused).
- Kept if cleanPlan accepts them.
- About 10% are round-2 plans made from a real round: join, check, review, then hydra:1.0 re-plans.

Step inputs:
- Made plan by plan in dependency order, with the accepted pieces truncated as Chimera does.
- Variants: about 10% with a failed dependency; about 4% lone steps; about 10% round-2; about 10% whose dependency output comes from another open model (qwen3.8:27b or qwen3:8b) under today's prompt, so the worker copes with mixed pools.

Candidates:
- gpt-oss:120b (Apache 2.0) at its default reasoning effort, with qwen3.8:27b (Apache 2.0) as a second sampler for Blender and code, in separate phases.
- Teacher-only hints, in the teacher's copy of the request only: "format rules win over the instructions' wording about files", plus a mechanical Blender API facts dump made by Blender 5.2.2 and 5.0.1 themselves (socket names per node type, RNA properties of the classes the step touches).
- Adaptive best-of-N: Blender up to 4 samples (2, then 2 more), code up to 3, prose 2. Then up to 2 teacher repair turns with the real traceback.

Checks every candidate goes through:
- All kinds: the Go validator. It checks the shape and the handoff, allows "uses" only from depends_on steps, rejects answers cut off at the length limit, targets over 3,500 tokens and examples over 12,288 tokens, and rejects harmony leftovers.
- Blender:
  - A strict run alone in 5.2.2 and in 5.0.1. It must exit 0 with no Traceback or Error line, which is stricter than judgeRun's "unsure".
  - A removed-API lint, from the RNA dump plus the Oct 29 list: mathutils.radians, use_auto_smooth, the Transmission and Specular sockets, NoiseTexture.noise_scale, RenderSettings.use_viewport, BevelModifier offset/depth, unlinking from the wrong collection.
  - A scene-probe epilogue. Its JSON must show the chimera_ names and ctx keys the handoff provides.
  - A teacher judge at temperature 0 on the scene dump: it built what was asked and nothing a sibling owns.
  - Then the piece is joined after its accepted dependencies and run again.
  - At plan level, the whole joined script must pass in both versions, print no stand-in, leave no .001 duplicates and keep every provided name. If it fails, the line map names the step: try the next candidate (up to 4 combinations), otherwise drop that plan's Blender examples.
  - Drops are counted by reason, so the data doesn't quietly drift toward easy scenes.
- Code:
  - py_compile on every file; imports between files resolve; the provided symbols exist.
  - Teacher-written tests count only if they fail on a stub and pass on at least one candidate. They run in the sandbox (Python -I, 30 s) and never enter training.
  - At plan level, the joined project compiles and its entry point runs.
- Prose:
  - Deterministic checks: the heading; no intro or outro for the whole project; length within 30% of any target; no AI or worker talk; no unmarked URLs or DOIs; the handoff.
  - Then gpt-oss:120b judges every piece, with qwen3.8:27b on about 20% to catch self-preference. Keep 4 out of 5 or better.
  - Sibling sections must stay under an n-gram overlap limit.
- Repairs: a failed candidate plus its real error becomes an example when the teacher's repair, made through the exact repair message, passes and changes at most 30% of the lines. Capped at about 15% of the Blender and code examples.

Kept for v1: about 1,700 examples, with a 5% validation split by seed group.

| Kind | Examples |
|---|---|
| Blender | 640 (520 build + 120 repair) |
| Code | 540 (460 + 80 repair; at least 70% run Python) |
| Writing | 300 |
| Research | 130 |
| General | 90 |

Spread across them: about 150 round-2, 100 failed-dependency, 60 lone, 170 mixed-pool and 150 long-input (5-8K tokens) examples.

Cost:
- About 4,500-5,500 long gpt-oss:120b answers, about 35 s each at the measured 82 tok/s (about 2.5-3K tokens including reasoning), plus about 2,500 short calls.
- About 35-45 h of Studio time with 2 parallel requests: 3-4 nights, resumable. The Blender runs (about 4 h of CPU) overlap.
- A 20-seed smoke run measures this first, with a STOPPED.md early stop.

Overlap guard: the worker eval gets a new canary, and tools/check_overlap.py is extended to its tasks, plan instructions and frozen dependency outputs, and run on every training file.

4. EVAL
Location: worker-model/eval/. Claude writes it; it is eval only and has its own canary. The runner reuses helper-model/runner.

STEP LEVEL (about 220 cases)
- W1, about 150 steps: from the 44 existing long-task eval prompts plus 10 new Blender tasks. Plans are frozen from hydra:1.0, and from gpt-oss:120b for about 10 tasks. Dependency outputs are frozen too: verified gpt-oss:120b pieces under the contract, plus 10 cases with today's-format outputs from qwen3.8:27b.
- W2, 30 Blender 5 API-trap steps, each fact checked by running it in both versions: Transmission Weight, smooth by angle, Noise Texture's Scale input, bevel width and segments, the EEVEE engine id, the 5.x compositor, geometry-node interface sockets, AgX, collection linking, keyframes and NLA, bmesh, world nodes.
- W3, 20 repairs of real crashes.
- W4, 10 cases with a failed dependency and 10 long-input cases (6-12K tokens), to set workerMaxCtx.
- A 60-case quick subset for iterating.

Step-level scores:
- contract compliance
- Blender strict pass in 5.2.2 (the main number) and 5.0.1, with dependencies joined, plus a count of API errors
- scene assertions and the provides probe
- staying in its own lane
- code: hidden tests and interface names
- prose: two blind judges with a rubric, plus pairwise against qwen3.8:27b in both orders
- repairs: fixed in one try, and the share of lines changed
- tokens, tok/s and wall time

Blender and code get 3 unseeded samples each at the model's own defaults (Chimera sends none); prose gets 1 sample and 2 judges. Comparisons use paired statistics.

TASK LEVEL
T1: 30 tasks (12 Blender, 10 code, 8 prose) with frozen plans. One fixed seam and combine model, qwen3.8:27b, for every arm:

| Arm | Prompt | Workers | Joining |
|---|---|---|---|
| A | today's | qwen3.8:27b | model combine (today's real pool) |
| A2 | today's | gpt-oss:120b | model combine (the Oct 29 setup) |
| B | contract | qwen3.8:27b | joining |
| C | contract | gpt-oss:120b | joining (ceiling) |
| D | contract | untrained base | joining |
| E | contract | trained worker | joining |
| F | contract | trained worker | joining, no seam pass |
| G | contract | trained worker, every other step on qwen3:8b | joining |

T1 scores:
- the strict check of the result in both versions, in round 1
- the reviewer's "done" rate (gpt-oss:120b, 3 samples)
- scripts and files against how many there should be
- fallback rate, seams, cut-offs and wall time

T2, looping: 8 Blender and 4 Python tasks on a closed-network test Chimera (its own data folder, --no-open, and leftover processes killed, because test instances bind the real UDP port 7479). Up to 6 rounds. Measures rounds until it passes and repairs used.

T3: 10 tasks on the real 0.8.0 pool.

BASELINES
1. Tonight, installed models: gpt-oss:120b, qwen3.8:27b, qwen3:8b and qwen3:4b-instruct-2507, each with today's prompt and with the draft contract, on the quick subset, plus T1 arms A, A2, B and C.
2. After the downloads: gemma4:12b-it-q4_K_M and qwen3:14b (with think unset as Chimera sends it, and with the forced non-thinking template); gpt-oss:20b optional.
3. Fleet runs on the PC and the M4 Pro.
4. The trained model at bf16, Q4_K_M, Q5_K_M and Q6_K.

BAR
prefer_model is turned on per kind only where that kind clears its bar.
- Blender: a strict pass in both versions on at least 75% of samples, and at least gpt-oss:120b with the same contract, and at least qwen3.8:27b + 15 points, and at least the untrained base + 20. Definite crashes at most 10%.
- Code: hidden tests at least qwen3.8:27b's and at least gpt-oss:120b's − 5. Interfaces match in at least 95%.
- Prose: pairwise against qwen3.8:27b, win plus tie at least 50% (95% lower bound at least 40%) with both judges.
- All kinds: contract kept in at least 97%; cut-offs at most 2%; nothing below the untrained base. W3: at least 70% fixed in one try, median change at most 20% of the lines.
- Task level: T1 round-1 joined Blender and Python pass at least arm B's and at least arm C's − 5; joining works without fallback in at least 90% of tasks; reviewer done rate at least B − 3; T2 median rounds until it passes at most 2 (the island task took 6 rounds or more).
- Quantization: Q5_K_M within 3 points of bf16, with no format slips.
- Fleet: on the 3080 Ti, 100% on the GPU at the context the steps use, at least 25 tok/s, and a 1,500-token step in 75 s or less. On the M4 Pro, at least 15 tok/s.
- Phase-1 gate (contract and joining, before the model): B at least A on T1 Blender and code passes, and the prose done rate at least A − 3. If the contract hurts untrained models, the asker sends it only when a computer with the worker is online.

5. TRAINING
On the Studio: MLX-LM 0.32.2 in the helper's pinned environment. run_train_worker.sh is a copy of run_train.sh with BASE_HF, BASE_OLLAMA and a free-disk check of about 90 GB.

Settings:
- LoRA on all layers (48 for Gemma, 40 for Qwen) with the default keys (all linear projections).
- Rank 32, scale 20, dropout 0.05.
- AdamW at 2e-5, 5% warmup, cosine decay to 2e-6.
- 1 epoch, batch 1 × gradient accumulation 8: about 1,600 micro-steps and 200 updates.
- max_seq_length 12,288. Longer examples are dropped before training, because MLX-LM truncates them and would cut the target and its handoff.
- mask_prompt and grad_checkpoint on; validation every 200 micro-steps on 25 batches; save every 200.
- workerMaxCtx 12,000, no higher than the trained length. Chimera's NeedCtx includes the 4,096 tokens of room, and the round-2 part counts towards it.

Memory:
- bf16 weights: 24 GB for Gemma, 29.5 GB for Qwen.
- Logits at 12K tokens: about 6.4 GB in bf16 for Gemma's 262K vocabulary (about 13 GB in fp32, plus gradients); about 3.7 GB for Qwen.
- Expect a 50-65 GB peak, so gpt-oss:120b is unloaded (train/ollama_unload.py), the Studio isn't lending, and data generation doesn't run at the same time.

Time:
- Helper v3 processed about 2.1-2.3M tokens, prompts included, in about 2 h: about 300 tok/s in all on a 4B. The logged 97 tok/s counts answer tokens only.
- Scaled up: Gemma about 90-100 tok/s, Qwen3-14B about 75-85.
- About 5.1M tokens, so Gemma about 14-16 h and Qwen about 17-19 h. Measured since (Oct 30 pilot): Gemma 193 tok/s in all, so about 6-8 h; Qwen isn't measured, and the same scaling was about twice too slow for Gemma.
- Order: a 20-iteration pilot (30 min); then v0.1 on about 500 examples from the first data night (about 2 h at the Oct 30 pilot's speed), carried through fuse, GGUF, import and the quick eval, to prove the pipeline and the contract; then the full v1.
- If the pilot is under 60 tok/s: train only the top 32 layers, or cut to about 1,200 examples, or rent one 80 GB GPU.

Quantization: Q5_K_M is the release (about 8.5 GB for Gemma, 10.5 GB for Qwen). Score Q4_K_M and Q6_K against bf16 first, and never fall back to Q4_K_M unscored (helper v3 slipped at Q4_K_M).

Modelfile:
- The base's template or RENDERER/PARSER with thinking forced off.
- num_predict 6144, as a guard against runaways.
- Temperature from a small study: 0.3, 0.7 and 1.0 on the W1 and W2 Blender cases.
- LICENSE: the Apache 2.0 text plus a "modified" note.

Development tags are named hydra:worker-dev-<run>, so 0.7.0 builds keep them out of chats and ordinary steps while they sit in the Studio's Ollama. They are removed after scoring.

Disk (133 GiB free):

| Item | Size | When it goes |
|---|---|---|
| Baselines | 17 GB (+14 optional) | |
| HF base | 24-30 GB | |
| Fused model | 22-30 GB | deleted after the GGUF |
| bf16 GGUF | 22-30 GB | deleted after the quants |
| Quants | one at a time, plus their Ollama copies | |

- The managed peak is about 90 GB for Gemma and about 110 GB for Qwen.
- Deleting helper-train v1 and v2 (37 GB) needs the user's OK. It is recommended, and in effect required if Qwen3-14B wins.
- Optional: v3's intermediates, about 24 GB (keep helper-q5_k_m.gguf, the adapters and the Modelfiles).
- Don't touch the user's own big Ollama models; the two deepseek-r1:70b entries very likely share one blob anyway.

v2 is built from v1's failures, sorted by API area and error:
- targeted seeds
- on-policy rejection sampling with teacher repairs (other computers in the pool can sample)
- DPO or ORPO on verified pass/crash pairs, if MLX-LM supports it
- longer inputs
- possibly a mechanical API-notes block in the worker's prompt, if the eval shows it helps

6. INTEGRATION (CHIMERA 0.8.0)

Phase 1, no model: the contract prompt, joining, the seam pass, step repair in looping mode, the round-2 parts and the card lines. Gated by the phase-1 test.

Phase 2, with the model:
- runStep sets PreferModel = workerFor(mode, NeedCtx). It returns the worker only for modes that cleared the bar and when NeedCtx ≤ workerMaxCtx, and never for pinned ("Run on") steps.
- The second attempt drops PreferModel if the first one ran on the worker. Repairs prefer the worker too.
- No hub change is needed. Any 0.7.0 hub honours PreferModel by name (score 1e6 − eta) and waits up to 3 s only for a *free* computer that has the worker. Busy ones aren't waited for, so leftover parallel steps go to other models under the same contract.

The worker is kept out of chats, combines, seam passes, plans, reviews, the gate, library jobs and Head options; naming it explicitly still works. 0.8.0 splits isHelperModel into:
- isHydraModel: any hydra: tag, for ForChat and forChat in app.js
- the helper's versions
- isWorkerModel: hydra:worker-*

KV estimate fix (ollama_monitor.go parseShow), required for Gemma:
- Count only full-attention layers per token, plus a fixed term for the sliding windows.
- Read the window size and the layer pattern from /api/show, with a small per-architecture fallback for when the arrays are missing, and check it against /api/ps.
- It also corrects fits for gpt-oss and other sliding-window models. That is a behaviour change, so it gets tests.

Sharing: helper_share.go goes from one constant to a list (hydra:1.0 and hydra:worker-1.0).
- /v1/helper is kept for 0.7.0 members, and a model parameter is added.
- RENDERER and PARSER are carried along: Gemma needs them (gemma4-large, gemma4-no-thinking). /api/create on 0.40.1 accepts them on the Mac; Windows is unchecked. See "Probes a-c".
- Same stall and concurrency limits.
- About 8.5-10.5 GB: 3-5 minutes on good Wi-Fi, longer over Tailscale.
- Offered only where the model fits.

Mixed versions:
- A 0.7.0 asker never reaches the worker.
- A 0.8.0 asker on a 0.7.0 hub: routing works.
- 0.6.x has no hydra: exclusion, so the worker would win chats there. Rule for CLAUDE.md: install the worker only on 0.8.0 or newer, host first. 0.7.0's Models page labels it "the network's helper", which is cosmetic.
- hubProto unchanged.

What the user sees:
- A "Worker: Hydra Worker 1.0 (8.5 GB), Get from host" row with fit and speed.
- Task cards with each step's model and device, its "assumed" lines, and "Joined by Chimera from 4 pieces", "qwen3.8:27b fixed 1 seam" or "Combined by X: s3 didn't keep the piece shape".
- Repair lines, like "s3 crashed at line 23 (KeyError: 'Transmission'); asked s3 again; passes in Blender 5.2.2".
- One script with the settings at the top, how to run it, and an Assumptions note.
- Credit weight 1.5 (Gemma) or 1.85 (Qwen).

Tests:
- Go golden tests: validator, joiner, line map, library wrap, handoff stripping, workerFor, the KV fix.
- check_prompts_sync extended to the new frozen texts.
- fake_ollama_hydra.py taught the repair job.
- hydra_test.py additions: one joined script, the fallback, repair, prefer per kind, an old asker unaffected.
- run_it.py and heads_text_test.py.
- Real checks: host first; Get from host on the PC (Windows /api/blobs + /api/create is still unverified) and the Macs; one real looping Blender task.

7. ORDER OF WORK
See start_now and after_decisions. About 8-11 working days elapsed, with about 4-5 Studio nights plus about 1.5 days of training.

8. RISKS
1. The teacher's Blender 5 ceiling: gpt-oss:120b crashed in every real Blender task. Mitigation: pass rates tracked per area, repairs using Blender's own API facts, a second sampler, the early stop.
2. "It runs" is not "it's right": probes, assertions, lane checks and judges reduce this, but don't remove it.
3. The frozen planner's file handoffs and vague interfaces: measured by drop reasons and the seam rate.
4. The Gemma pipeline is untested here: probes first, Qwen3-14B as the fallback.
5. A template mismatch silently ruins a fine-tune: the token-level parity test.
6. Training time and memory are estimates: the pilot measures them.
7. The 16 GB laptop GPU also drives the display, and Qwen3-14B is tight on it: measured with size_vram.
8. Untrained models may not keep the contract, which means more fallbacks and no gain: the A/B gate.
9. prefer_model beats every model: per-kind enablement, the context limit, and the retry without it.
10. Judge self-preference: two judges, pairwise in both orders, execution first.
11. Lock-in: changing any frozen text means retraining.
12. A leak into the eval: the canary and check_overlap.
13. Disk peak: the deletion order and the user's OK.
14. Data generation uses the Studio's real Ollama: setting OLLAMA_NUM_PARALLEL needs a restart that interrupts the real Chimera, and a leftover test instance can join the real pool.
15. Fleet unknowns: Windows /api/blobs, the copy over Wi-Fi and Tailscale, laptop throttling, and no script checks on Windows.

LEFT OUT OF v1 ON PURPOSE
- The worker as combiner or seam fixer.
- Thinking mode, tools, vision and audio, Heads called from steps.
- DPO or RL.
- API notes in the worker's prompt.
- The result check in single-pass mode (unless the user says yes).
- Running multi-file projects in Chimera's own result check (only data generation does that).
- Blender 4.x and Windows script checks; running JS and other languages.
- Steps over 12K tokens.
- A smaller worker for small computers; per-kind adapters.
- Training on real user tasks.
- Any change to the planner, reviewer or gate prompts, and any retraining of Hydra 1.0.

LICENCES
| Model | Role | Licence | Source |
|---|---|---|---|
| Gemma 4 12B | base, pick | Apache 2.0 | HF card read today |
| Qwen3-14B | base, fallback | Apache 2.0 | HF card read today |
| Qwen3.5-9B | optional baseline | Apache 2.0 | HF card, per the design panel |
| gpt-oss-20b | optional baseline | Apache 2.0 plus OpenAI's usage policy | HF card, per the design panel |
| gpt-oss:120b | teacher and judge | Apache 2.0 | the Studio's /api/show, read today; helper README: no restriction found on training with its outputs |
| qwen3.8:27b | second sampler and second judge | Apache 2.0 | /api/show, read today |
| qwen3:8b | baseline | Apache 2.0 | /api/show, read today |
| qwen3:4b-instruct-2507 | baseline | Apache 2.0 | helper README |

Keep the Apache 2.0 text and a "modified" note in the Modelfile LICENSE.

KEY FILES
- /Users/fx/Desktop/chimera/app/prompts.go (workerPrompt, workerKindRules, synthPrompt)
- /Users/fx/Desktop/chimera/app/hydra.go (runStep, onePass, cleanPlan)
- /Users/fx/Desktop/chimera/app/ollama_monitor.go (parseShow KV)
- /Users/fx/Desktop/chimera/app/profile.go (fitModel)
- /Users/fx/Desktop/chimera/app/hub.go (fits, modelOK, ctxBucket)
- /Users/fx/Desktop/chimera/app/helper.go
- /Users/fx/Desktop/chimera/app/helper_share.go
- /Users/fx/Desktop/chimera/app/tools.go (findBlender)
- /Users/fx/Desktop/chimera/app/runner.go (blenderStopAtRender)
- /Users/fx/Desktop/chimera/app/checkresult_cli.go
- /Users/fx/Desktop/chimera/tests/plugin-network/fake_ollama_hydra.py
- /Users/fx/Desktop/chimera/helper-model/ (runner, tools/check_overlap.py, tools/check_prompts_sync.py, tools/check_go_parity.py, train/)
