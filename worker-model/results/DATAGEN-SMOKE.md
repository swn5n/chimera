# Data generation smoke runs (Nov 3 to 6, 2026)

Six runs: the 20-seed smoke run on Nov 3 (first), a 12-seed second run on Nov 4 after the fixes ("Second smoke
run"), an 8-seed third run later on Nov 4 after the next fix round ("Third smoke run"), a fourth on the same 8 seeds
on Nov 5 after the round that followed it ("Fourth smoke run"), a fifth on them on Nov 6 after the fourth run's fix
round ("Fifth smoke run"), and a sixth the same day after the round that followed the fifth ("Sixth smoke run", at
the end).

## First smoke run (Nov 3)

The plan's 20-seed smoke run (`bash run_datagen.sh`, size `smoke`), on the Studio with Ollama 0.40.1 at
OLLAMA_NUM_PARALLEL 1. Teacher gpt-oss:120b, second sampler qwen3.8:27b (thinking on, Ollama's default), planner
hydra:1.0 (12 plans) or gpt-oss (5, plus 3 reused helper plans). The data is in `data/gen/smoke/` (gitignored):
`REPORT.md`, `report.json`, `sft/STATS.md`. Its purpose was to measure acceptance and seconds per example, to
re-budget the plan's 35-45 h.

Chimera was lending through the whole run (FORCE=1), but its log shows no pool step on the Studio from 14:20 to the
end. The report's "other models in Ollama" note is a false alarm: hydra:1.0 and qwen3.8:27b were left loaded by this
run's own earlier starts.

### What ran

Four starts, 5.88 h from first start to last seed. The last start ran 17 seeds in 3.38 h and kept 3 Blender-only seeds
from before. Between starts, the writing-step rules were fixed three times:

- The first seed (a five-section memo) kept 0 of 5 steps. Some drops were the gate's fault: a heading that drops the
  title's verb ("Write ... (≈600 words)") was refused, and a section-level "In summary" counted as a conclusion of the
  whole document. Others were gpt-oss's: it overshoots word counts by 1.15-1.45 times. The prose judge was also
  marking every section down for the required handoff block.
- Fixes: teacher-only notes for sections (heading line, a length band aimed below the target, the framing rule, what
  the last try failed on), a third try, the judge shown the handoff and the required heading as format, and a word
  reader that copes with gpt-oss's U+2011 hyphens and sub-part lengths. Two review rounds checked them on the 712
  section steps in gpt-oss's stored plans.
- After them, the memo kept 4 of 5 and the French tour plan 6 of 6. Section records made under older rules were redone
  (`tasks.before-section-fix*.jsonl` keep the old ones).

### Yield

63 examples built (60 train, 3 valid) of 80 kept. 17 code pieces were dropped by the build because their tests were
never confirmed. 0 seeds ended in an error.

| mode | steps tried | dropped | built examples | model s per built example |
|---|---|---|---|---|
| blender | 46 | 19 | 29 | 363 |
| files | 29 | 12 | 5 | 914 |
| python-script | 11 | 0 | 11 | 121 |
| section | 19 | 4 | 18 | 58 |

By model, 50 built examples come from gpt-oss and 13 from qwen3.8. By source, 49 come from first samples, 13 from the
second sampler and 1 from a repair. Request tokens per example: median 3,602, p90 7,498. Target tokens: median 1,286,
p90 2,473.

### Time

- **Model calls:** 744 calls, 5.36 h: gpt-oss 61%, qwen3.8 38%, hydra:1.0 138 s for 15 plans (all readable).
- **Rules fixed mid-run:** 79 calls (1,521 s) were made under the older section rules and aren't in any final record,
  so the 63 examples rest on about 280 s each.
- **Where step time went:** 55% to steps that were dropped, 14% to code steps kept with unconfirmed tests, 31% to steps
  that became examples.
- **Second sampler:** 122 calls, 7,037 s, 13 built examples (541 s each). About half its time is thinking. One reply
  thought for 16,384 tokens and wrote nothing (269 s).
- **The gate:** 34 group switches cost about 4% (15 s of idle each, plus gpt-oss reloads of 11-21 s). Blender's 273
  runs (547 s) overlapped the model calls.
- **Projection:** about 139 h of model time for the plan's 1,700 examples at 1 parallel, corrected for night's variant
  shares. Resampling the 20 seeds gives 108-247 h. The plan's 35-45 h assumed 75-95 s per example.

### Quality

A strict read of all 63 examples found 18 ok, 26 weak and 19 bad (30% bad):

| mode | ok | weak | bad |
|---|---|---|---|
| blender (29) | 4 | 16 | 9 |
| python-script (11) | 8 | 3 | 0 |
| files (5) | 3 | 1 | 1 |
| section (18) | 3 | 6 | 9 |

Every request is byte for byte Chimera's (63 of 63, regenerated with `--hydra-worker-request`). No teacher note,
judge text or fixture text is in any message. The checks still let through:

- **Blender:** wrong sizes (a size=1 cube scaled by L/2, three times), a ceiling light facing up, a logo that is a
  zigzag curve, and placeholder output paths. Nothing measures shape, size or direction.
- **Prose:** made-up benchmarks, prices, part numbers and contacts presented as fact; a CSV with the wrong field count;
  an invalid Slack manifest. The prose judge kept them at score 4.
- **Failed dependencies:** examples written with a dependency missing are a third of the data and much worse (8 of
  20 bad). 13 of the 20 claim, under `uses:`, output from the step that failed.
- **Leaks:** 4 qwen3.8 targets name the Blender versions (5.2.2, 5.0.1) that only the teacher's notes carry.

### Found and verified (fixed on Nov 4, all but item 6)

Each was confirmed by an independent check against the data and the code (scripts in the session scratchpad).

1. **Files mode:** gpt-oss writes `**File: path**`, so 77-81 of its 86 files pieces fail the validator's form rule,
   and nothing tells the next try why. With the lines made plain, 74 pass the validator and 56 the code gate. Fix:
   normalise a decorated File line before validation (or a teacher note), and pass the validator's messages to the
   next try for code and Blender steps, as sections now do.
2. **Teacher tests:** in 13 of the 17 unconfirmed code steps the tests are wrong, not the piece. They test the whole
   task instead of the step, guess module and function names, start subprocesses the sandbox refuses, or treat an
   example as exact text. Fix: TESTS_SYSTEM rules (all Claude-written teacher instructions), let the files-mode tests
   see the step's own modules, and allow one rewrite. About 9-13 of the 17 would come back.
3. **The scene judge is shown a misleading scene listing:**
   - Blender's default engine and world are listed as if the piece set them.
   - Animations, node groups, modifiers, light power and lens are left out.
   - It doesn't show sizes or directions at all.

   7 of its 8 Blender drops were false. Fix the listing, and turn measured size or direction mismatches into repairs.
4. **Prose checks:** require a fabrication check for claimed sources and measurements, a CSV field-count check, and
   score 5 (or 4 with no disqualifying problem) to keep a section.
5. **Smaller fixes:**
   - a stand-in marker written with U+2011 that the gate can't see;
   - a first step's placeholder files for other steps, which then blocked 4 steps;
   - a lint false positive on Cycles' add-on preferences;
   - the build's natural failed-dependency share;
   - version strings in the teacher notes;
   - the judges being shown the person's goal, which the worker never sees.
6. **In Chimera's own code (Go):** the `uses_unmatched` seam (`usesChunks`) misreads handoffs written "X from sN".
   Changing it changes the contract's validator and its parity with the prototype, so it is a separate decision.
   Decided Nov 5 (contract question 4) and fixed in the contract: each item goes to the step id after it, Go and
   Python with parity (`datagen/DESIGN.md`, "Decided Nov 5 and done").

### Levers on time

Hours to the plan's 1,700 examples, against about 139 h at 1 parallel. The 2-parallel figures use the plan's 1.3x
guess, which hasn't been measured.

| change | 1 parallel |
|---|---|
| files fix (1) with an early stop at round 1 | 118 h |
| keep code pieces whose tests fail only through the tests' fault, after (2) | about 102-121 h |
| qwen3.8 second sampler with thinking off, if its yield holds (not measured) | 112 h |
| all of the above, plus num_predict 8192 for the second sampler | about 66 h (51 h at 2 parallel) |

Even then, 1,700 examples is about 3 nights at 2 parallel, or 5-6 at 1, not the plan's 3-4. Fixing the false drops
also adds examples for the same time.

### What it means

The pipeline works end to end, and its requests are exactly Chimera's. But 30% of what it keeps would teach the worker
wrong things, and at today's yield the full set costs about three times the budget. The verified fixes above are all
in data generation (Claude-written code, rubrics and teacher notes) except item 6. Making them and running a second,
smaller smoke run should come before the nights.

## Second smoke run (Nov 4)

### What ran

12 of the first run's 20 seeds, after the fixes in `datagen/DESIGN.md` ("After the smoke" and "After the re-check"),
into `data/gen/smoke2/` (gitignored). Same models, Ollama 0.40.1, 1 parallel, Chimera 0.8.0's binary (sha256
`1e091290…`). The call cache was seeded with the first run's 744 calls: a request that didn't change is answered from
it, and 287 calls were new. 2.53 h from start to the last seed, 0 errors. Chimera was lending again (FORCE=1).

The report's model-time table sums the whole cache, the copied calls included, so its totals are too high. Its
projection counts only the calls the records use and is right. (Fixed after the run: `report.py` now counts only
those calls, 330 calls and 9,314 s for this run, not the cache's 1,031 and 28,131 s.)

### Yield and time, on the same 12 seeds

| mode | first run: built | second run: built | first: model s per example | second: model s per example |
|---|---|---|---|---|
| blender | 14 | 20 | 469 | 270 |
| files | 3 | 14 | 881 | 184 |
| python-script | 9 | 11 | 78 | 45 |
| section | 7 | 2 | 58 | 348 |
| all | 33 | 47 | 313 | 195 |

- **Files:** fixed. Not one File line needed making plain: the teacher note was enough, and gpt-oss no longer bolds
  them.
- **Blender:** the scene judge dropped nothing. Its drops were all false in the first run.
- **Sections** are now the costliest mode: 2 built of 10. All 6 drops were right (below).
- **The build** dropped 3 code pieces whose tests never passed and 2 for the failed-dependency share.
- **Projection:** 92.6 h of model time for the plan's 1,700 at 1 parallel (71 h at an assumed 1.3x for 2), against
  139 h. Writing has no built example, so its share is an estimate from 7 tries.

### Quality

A blind audit of 80 examples: the first run's 33 from these seeds and the second run's 47, mixed, graded without
knowing which run, with the first run's strict rubric, and every piece run in the sandbox (both Blenders for Blender).

| mode | first run: ok / weak / bad | second run: ok / weak / bad |
|---|---|---|
| blender | 0 / 2 / 12 | 2 / 9 / 9 |
| python-script | 4 / 4 / 1 | 5 / 4 / 2 |
| files | 2 / 1 / 0 | 3 / 7 / 4 |
| section | 0 / 2 / 5 | 0 / 1 / 1 |
| all | 6 / 9 / 18 (55% bad) | 10 / 21 / 16 (34% bad) |

The first run's own audit found 30% bad over all 63. On these 12 seeds, re-read with every piece run, its 33 are 55%
bad, so this audit is the stricter one. Compare the two columns with each other, not with the 30%.

- **Usable** (ok or weak): 15 → 31.
- **Failed dependencies** are still the worst: 6 of the second run's 8 examples written with a dependency missing are
  bad.
- **Cost per usable example:** about 296 s. With 11 of 20 Blender examples usable, 1,700 good examples would still
  take about 140 h, 88 h of it Blender (writing and general are guesses).

19 drops were checked the same way: 14 right, 5 false. 3 tests_unconfirmed (n-python-0001-01 s3, s4, s6: the
teacher's tests drove s1's module, which those steps don't depend on and which was dropped), 1 `dupes` (the copy of
the factory camera the step asks for by name) and 1 `joined_dupes` (the best candidate was dropped by
provides_missing). All 6 section drops were right: every candidate claimed a failed step's output or invented
benchmarks and part numbers.

### Why the bad ones got through

Nine causes, each found by one analyst on the records and the code, with a prototype check run offline on both runs'
candidates (no model calls), then re-run by a skeptic told to refute it. Every skeptic reproduced the counts; most
made the check safer ("partly"), none refuted the cause. Scripts and results: the session scratchpad's
`audit2/rc/`.

| cause | bad examples it explains | check | flags among graded bad / weak / ok |
|---|---|---|---|
| **A failed dependency's output claimed** (`uses:` names a step that failed, or assumes it ran) | 13 of the 15 bad written with a failed dependency, both runs | `failed_dep_claimed`, from the request and the handoff | 13 / 3 / 0 |
| **Blender errors hidden by the piece**: a 3.x/4.x call in `try/except`, or `if name in node.inputs` skipping a wrong name. The teacher, told the line that crashed, wrapped it in `try` | X06, X07, X20, X58 | `silent_faults`: a prelude records exceptions handled in the piece's own lines (sys.monitoring in 5.2.2, settrace in 5.0.1) and socket lookups that missed a close name | 4 of 21 Blender / 0 / 0 |
| **Wrong places and shapes**: objects raised by their height, an extrude of -0.08 clamped to 0, a backplate buried in the logo | X27, X39, X06 (and the first run's X01) | `place_mismatch`, `flat_extrusion`, `nested` (measured) | 4 of 21 / 0 / 0 |
| **No output handed over**: the step asks to render or save, and `SETTINGS_sN` has no `"output"` | X05, X20, X58 (and X43) | `output_missing` | 4 of 21 / 0 / 0 |
| **Files in the wrong place**: the entry imports from the root what its dependencies put in `src/`, copied from the contract's `File: src/store.py` example | X80, X32 | a static import finder on the joined tree | 2 of 4 files / 0 / 0 |
| **Nothing checked the language**: PowerShell pieces, parsed by nothing | X17, X74 | a build filter for code nothing here can parse (by File: extension) | 2 / 1 / 0 |
| **Python faults no test reached**: an undefined `Pt`, a name bound only in `try` | X44 (and weak X15) | an import fault for third-party imports inside functions; a names check | 1 / 1 / 0 |
| **Invented facts outside sections**: in a script's string literals, or a README's claim about another step's code | X44, X61 | covered by the line above for X44; X61 has none | 1 / 0 / 0 |
| **False drops** (above) | D15, D17-D19 | `tests_fault` reads the dependency closure; the factory camera's copy excused when it's the scene camera | +4 examples (1 ok, 3 weak), 0 bad |

A completeness critic then read everything that was left:

- **Values-only first steps.** hydra:1.0 planned 3 of the 4 new Blender seeds to open with "Define variables and
  render settings". The contract gives such a step no way to hand values on, so workers improvise `ctx["variables"]`
  or dead `SETTINGS` keys. That is behind 4 of the 11 weak Blender examples. Two code facts (`ctx_channel`,
  `dead_output_key`) flag 5-7 of 51 passing pieces, none ok, but they rest on 3 seeds.
- **Chimera's own validator warnings:** `handoff_long`, `uses_undeclared` and `provides_missing` reach kept
  examples. As a build filter they would drop 4 bad and 3 weak, 0 ok.
- **The next try's notes keep the oldest failure lines:** `FAILURES_KEEP` 6 keeps the first six, so new tells on later
  tries get cut. 11 of 70 steps had more.
- **Not covered at all:**
  - the camera never made the scene camera;
  - a shade with no material at all, which the scene judge's rubric may not judge;
  - what a node group outputs;
  - the person's input files (acme.svg, the CSV), which never exist in the sandbox;
  - false comments and docstrings inside code.
- **Contract questions:** how a values-only step hands values on, what `SETTINGS_sN["output"]` must hold, the
  `src/store.py` example, and Go's `usesChunks` misreading "X from sN", which is still pending (decided Nov 5 and
  fixed in the contract, contract question 4: each item goes to the step id after it).

The critic's order, all offline:

1. Failed-dependency honesty as a build filter, then as a gate.
2. The pure build filters: languages, validator warnings, `ctx_channel`, `dead_output_key`, lazy third-party imports.
3. The false-drop fixes.
4. The files import finder.
5. `output_missing`.
6. One Blender batch under a single run-format bump (silent faults, geometry, scene camera).
7. The teacher notes.

On smoke2 that removes 14 of the 16 bad (X18 and X61 stay) and 11 of the 21 weak, and loses no ok example directly.
With the 4 false drops back, about 26 of the 47 would be kept, 2 of them bad (8%), before any retry finds a
replacement. Most checks are filters
or gates on facts. Gates cascade: geometry on s1 of blender-0002-02 would take smoke2's only two ok Blender examples
with it unless a flagged piece is kept as a dependency but not as an example, as plan_failed does.

### Prose: the claims rules and the judge

- **The word rules can't see most invented facts.** 211 real texts were labelled by hand: invented claims, given
  facts and look-alikes, in held-out and used slices. On the 166 held-out invented sentences, all seven versions of the
  claims rules (r3, r4, today's, the recall, precision and tells prototypes, and their merge) caught 0, with 0 false
  alarms. 120 of the 166 are bare figures, specs and prices (JSON values, part numbers, "lead time 6 weeks") with no
  claim wording ("a 2023 survey found") for a word rule to read. On the used text they were tuned on, they catch 7-11%.
- **The judge does the work.** On the same set, today's pipeline (gpt-oss, kept at 4 or more, plus qwen3.8's keep
  when a dependency is missing) dropped 21 of the 25 held-out texts with invented claims. Asking qwen3.8 on every
  kept text would have dropped 24, but its false drops on clean text weren't measured.
- **It also dropped 59 of the 144 held-out texts with nothing invented.** Most of those drops name real faults the
  labels don't cover (wrong counts, untranslated text, a missing 11th concert, a cut-off answer).
- **One false-drop cause is verified:** `judges._DEP_CUT` cuts each dependency to 4,000 characters, so the judge
  calls names that sit later in a dependency "invented". In the eval's 6-dependency rows, Priya, Sophie and "Too Good
  To Go" are all past the cut. In real runs 7 of 19 sections (first run) and 1 of 10 (second) had a dependency over
  4,000 characters. The tests writer gets the same cut: 8 code steps in the second run.
- **Judged again with the dependencies whole** (cut at 40,000; the longest prompt was 53,000 characters): of the 26
  rows with nothing invented whose dependencies had been cut, drops went from 15 to 12. 5 flipped to kept and 2 to
  dropped, and the judge no longer called Priya, Sophie or Too Good To Go invented. Both invented texts stayed dropped. The fix: a
  budget over all dependencies instead of 4,000 each (made after the run: `judges.DEPS_BUDGET`, 40,000).

### What it means

The fixes worked where they aimed:

- files are fixed;
- the false Blender drops are gone;
- the model time per example fell by more than a third;
- the bad share fell from 55% to 34% on the same seeds.

But a third of what's kept is still bad, and most of it is quiet: hidden errors, outputs never handed over, claimed
dependencies, wrong places. The checks above are measured offline on both runs and catch 14 of the 16 with no false
alarm on an ok example. They cut the yield, though: at today's model time, 1,700 kept examples (about 92% of
them good) would take about 165 h at 1 parallel, unless retries recover what the gates drop. The unmeasured time
levers from the first run still apply: qwen3.8's thinking off, a num_predict for the second sampler, and 2 parallel.
A third, smaller smoke run after those checks should measure both yield and quality again before the nights.

## After the fix round (Nov 4)

The critic's steps 1-5 are now in the code, with the small fixes: failed-dependency honesty as a gate and a build
filter, the language, validator-warning and values-step filters, the false-drop fixes, the files import finder,
`output_missing` and the scene camera. A piece that fails only on a failed dependency, a missing output or the
camera can still be kept for the later steps, but it gives no example. Steps 6 (the Blender batch: hidden errors,
geometry) and 7 (the teacher notes) are not in it. `datagen/DESIGN.md`, "After the second smoke (Nov 4)", has the
details. Every figure below is offline, on the stored records, with no model call.

- **The second run, rebuilt with today's build:** 30 of the 52 candidate examples kept: 10 ok, 11 weak, 6 bad, and 3
  ungraded (D17-D19, back as unverified). No ok example is dropped or flagged.
- **In a real run the gates take two more** (X05 on its missing output, X80 on its import from the wrong folder).
  That leaves 4 bad of about 28 (about 14%): X06, X07 and X39, which step 6 is aimed at, and X61 (a README's claim
  about another step's code). Of the 21 weak, 10 are dropped.
- **The first run:** 13 of its 18 bad are dropped.
- **Time:** the report's projection on that rebuild is about 170 h at 1 parallel for 1,700 (about 131 h at an assumed
  1.3x for 2), before retries recover anything.
- **Unmeasured until the third smoke:** whether the new tell lines bring honest pieces back. 6 of the second run's
  steps would need new draws, and with none better they are kept only as dependencies.
- **Checks:** 667 datagen tests and 975 for the whole folder pass, every stored request is still byte for byte the
  binary's, and four independent re-checks found nothing high or medium left.

## Third smoke run (Nov 4)

### What ran

8 of the second run's 12 seeds, after the fix round above, into `data/gen/smoke3/` (gitignored): blender-0002-02,
blender-0008-00, n-blender-0000-00, n-blender-0000-01, n-python-0001-02, n-python-0001-01, research_draft-0007-04 and
n-python-0000-00. They were picked to cover every new check. Left out: coding-0015-05 (PowerShell only),
n-mixed-0000-01, n-blender-0002-01 and research_draft-0009-04. Same models, Ollama 0.40.1, 1 parallel, the same binary
(`1e091290…`). The call cache was seeded with the second run's 1,031 calls. The run used 273 calls: 169 of them
(3,852 s) answered from that cache and 104 new (3,754 s). It took 65 minutes, with 0 errors, and Chimera was lending
(FORCE=1).

### Yield and time

| mode | second run: built (these 8 seeds) | third run: built |
|---|---|---|
| blender | 18 | 3 |
| files | 11 | 11 |
| python-script | 10 | 10 |
| section | 1 | 1 |
| all | 40 | 25 |

- **Blender lost 15.** 11 of them are drops that today's build also makes on the second run's own records
  (ctx_channel, validator_warning, dep_claimed, dead_output_key), so the second run's 270 s per Blender example was
  measured on examples now known to be weak or bad. The other 4 come from the run itself:
  - blender-0002-02 s2: its redrawn repair changed 31.8% of the piece's lines, just over `REPAIR_SHARE` (30%), so it
    gives no example. Most of the change was reworded comments.
  - blender-0008-00 s1: dropped as stand_in (right: the second run's pick was X05, which never handed over its file).
  - blender-0008-00 s2 and s4: written with s1 failed, then dropped by the failed-dependency share cap.
- **Model time on the Blender seeds was about the same:** 4,439 s against 4,254 s. Only the count of examples fell.
- **Projection: 314 h** at 1 parallel for 1,700 (241 h at an assumed 1.3x for 2), against about 170 h estimated
  offline. Blender is 1,484 s per example and code 128 s.

### Quality

A blind audit, same rubric as the second run's. The second run's 40 examples on these seeds and the third run's 25
were mixed and renamed. The 16 that both runs built byte for byte were graded once. Every piece was run in the
sandbox, and a skeptic per area tried to overturn each verdict and changed none.

| mode | second run: ok / weak / bad | third run: ok / weak / bad |
|---|---|---|
| blender | 2 / 6 / 10 | 2 / 0 / 1 |
| files | 2 / 6 / 3 | 4 / 6 / 1 |
| python-script | 8 / 1 / 1 | 9 / 1 / 0 |
| section | 0 / 0 / 1 | 0 / 0 / 1 |
| all | 12 / 13 / 15 (38% bad) | 15 / 7 / 3 (12% bad) |

This audit reads the second run's 40 a little stricter than its own did (10 / 17 / 13). Compare the two columns with
each other.

- **More ok examples from fewer:** 15 against 12. Usable (ok or weak): 22 against 25.
- **The 3 bad left:**
  - blender-0002-02 s1: the logo's extrude is clamped to 0, so it has no faces (X39, step 6's geometry check).
  - n-python-0001-01 s6: a fallback calls `datetime(0, 0, 0)`, which always raises. This is one of the 3 steps
    whose tests couldn't reach their code and were kept unverified (the other two are weak).
  - blender-0008-00 s6, a section: a README that claims Blender 3.6 rendered on GPU with "CUDA/OpenCL", a backend
    3.6 doesn't have.
- **Drops:** all 31 were checked. 30 were right (22 of their best tries bad, 8 weak), and 1 was false: a weak files
  example dropped as tests_unconfirmed.
  - All 8 `ctx_channel` drops were right (4 bad, 4 weak).
  - All 4 the failed-dependency share cap took were bad (blender-0008-00 s2-s4, and research_draft-0007-04 s5 with
    invented figures in its assumed line). Lifting the cap for small modes, the cheapest yield fix the analyst found,
    would have let 4 bad examples in.

### The tells

The new gates fired on 13 steps and variants, which got 18 told retries (761 s):
- 4 came back honest and were built;
- 2 came back honest but were capped;
- 1 was kept only as a dependency;
- 6 were dropped.

Of the 8 told retries for a claimed failed dependency, 4 were honest. Of the 3 that claimed again, 2 wrote "s2
failed" under assumed and left the uses item unmarked. Both camera_not_active steps came back passing. Both
output_missing steps fixed the output, but each failed on something else.

### Why the yield fell, and what wins it back

From the yield analyst's reading of the records, checked against the audit:

1. **Values-only first steps (`ctx_channel`), by far the largest.** hydra:1.0 opened 4 of its 5 Blender rounds,
   across the second and third runs, with "Define variables and render settings". The contract gives such a step no
   way to hand values on, so the teacher writes `ctx["variables"]` or `ctx["settings"]` every time. That filter is
   build-only, so no tell or note ever reaches the teacher, and 904 s went into 8 steps that could never be examples.
   Answering contract question 1 and then adding a values-step note and a gate with a tell could win up to 7 back
   here.
2. **The repair share** counts comment lines. Measured on code lines, blender-0002-02 s2 is at 0.156 and would be an
   example.
3. **stand_in on an input file** that no dependency provides (acme.svg, an environment texture) drops a root step
   and cascades. Making it soft would keep the later steps written with s1 present.
4. **Not the cap:** as above, its four were bad.
5. **Time:** on Blender, the qwen3.8 second sampler took 32% of the model time (1,413 s), and none of its 3 kept
   pieces became an example. A third told gpt-oss batch costs about 60 s for 2 draws.

Found on the way: **Chimera's names sheet lists a `Weight` input** on the Principled BSDF, Emission and Glass
shaders (`blenderNamesExpr`, `app/blender_names.go`). The input is unavailable, and `inputs["Weight"]` raises
KeyError in both Blender 5.2.2 and 5.0.1, so the sheet invites the crash. That is true in real long tasks too.
Leaving out sockets with `is_unavailable` fixes it. It changes every Blender request, so it needs a format bump.

### What it means

The checks do what they were built for: bad fell from 38% to 12% on the same seeds, with more ok examples, and every
drop checked but one was right. The cost is yield: Blender gives almost nothing until values-only steps have a way to
hand values on, and the projection is 314 h. What's left that's bad is step 6's (geometry), an unverified files step,
and an invented fact in a section.

## Fourth smoke run (Nov 5)

### What ran

The third run's 8 seeds, into `data/gen/smoke4/` (gitignored), after the Nov 4 round (`datagen/DESIGN.md`, "After
the third smoke": `ctx["values"]` in the contract, the values-step note, `ctx_channel` as a gate with a tell, step 6,
the names sheet without unavailable sockets, the repair share on code lines) and the Nov 5 uses reader. Same models,
Ollama 0.40.1, 1 parallel; the binary `458dcbfc…` that `run_datagen.sh` built, the same build the Nov 5 checks ran on.
The call cache was seeded with the third run's 1,135 calls. The run used 290 calls: 143 (3,070 s) answered from that
cache, which covered every code and writing step, and 147 new. Every Blender request had changed. The tasks took
86.5 minutes (1.44 h with the build and the datagen tests, 768 of them, all passing), with 0 errors. Chimera was
lending (FORCE=1).

### Yield and time

| mode | third run: built | fourth run: built |
|---|---|---|
| blender | 3 | 4 |
| files | 11 | 11 |
| python-script | 10 | 10 |
| section | 1 | 1 |
| all | 25 | 26 |

- **The code examples are byte-identical** to the third run's, because the cache answered them. Only Blender and the
  one section in a Blender seed changed.
- **`ctx_channel` is gone:** it dropped 7 examples in the third run, and fired on none of the fourth run's 123 Blender
  tries. hydra:1.0 still opened 3 of its 6 Blender plan rounds with a values-only step. All 3 were kept, handed their
  values on in `ctx["values"]` (each by copying the whole `SETTINGS_s1` in a loop), and their readers read them.
- **None of the 3 values steps became an example.** Two fell to Chimera's `handoff_long`: their provides lines (331
  and 420 characters) list the 19 and 20 keys the plan names, and the limit is 300. The third fell to
  `dead_output_key`, an `output_path` nobody asked for.
- **Blender: 21 steps and 2 variants, 13 kept, 4 built.** Of the 9 kept pieces without an example:
  - `dead_output_key` took 2 and `validator_warning` 3 (`handoff_long` 2, `provides_missing` 1);
  - the failed-dependency cap took 2;
  - 2 were kept from a repair over `REPAIR_SHARE` on code lines.

  Beyond those 9, 2 were kept only as a dependency, 6 were dropped at the gate, and both variants were dropped.
- **Model time on Blender: 4,957 s,** against 4,439 s; 1,243 s per example, against 1,484 s:
  - steps whose example was built used 492 s (10%);
  - steps kept with no example 2,190 s (44%);
  - steps dropped at the gate 2,080 s (42%).

  The second sampler, qwen3.8, took 1,756 s (35%) and gave 1 example.
- **Projection: 270 h** at 1 parallel for 1,700, or 208 h at an assumed 1.3x for 2, against 314 h.

### Quality

A blind audit, same rubric as before:
- **Regraded:** the fourth run's 4 Blender examples and its section, mixed with the third run's 3 Blender examples and
  its section. Two graders read each one independently, and every Blender piece was run joined in 5.2.2 and 5.0.1. A
  skeptic then settled each grade.
- **Carried over:** the 21 code examples, byte-identical in both runs, keep the third audit's grades.

| mode | third run: ok / weak / bad | fourth run: ok / weak / bad |
|---|---|---|
| blender | 1 / 1 / 1 | 0 / 3 / 1 |
| files | 4 / 6 / 1 | 4 / 6 / 1 |
| python-script | 9 / 1 / 0 | 9 / 1 / 0 |
| section | 0 / 0 / 1 | 0 / 1 / 0 |
| all | 14 / 8 / 3 (12% bad) | 13 / 11 / 2 (8% bad) |

- **Consistency:** on the third run's 4 regraded items, this audit agrees with the third audit on 3. blender-0002-02
  s3 went from ok to weak, so the third run's column reads 14 / 8 / 3 here, where it read 15 / 7 / 3 before.
- **The bad Blender example** is blender-0002-02 s1, from qwen3.8. The logo is extruded 0.08 m both ways, so it is
  0.16 m thick and centred, where the step says "0.08 m in negative Z". No check measures an extrusion's direction or
  a doubled depth; `flat_extrusion` catches only a depth of zero.
- **The 3 weak Blender examples** are weak mostly in their handoffs:
  - uses lines that name no step;
  - an "assumed: none" over choices the request didn't give;
  - values written under computed keys that provides doesn't list;
  - a `ctx["values"]` read with a silent default (`.get(k, SETTINGS_s4[k])`), where the contract asks for the
    stand-in marker;
  - and in one piece, deprecated light `use_nodes` called "future-proof".
- **The section** is weak, with no invented facts. The third run's README claimed CUDA/OpenCL on Blender 3.6.
- **Drops: all 28 were checked.** The 7 identical to the third run's keep the third audit's verdicts. 24 were right
  and 4 false, and every false one is a weak example:
  - n-blender-0000-01 r1 s2, dropped by the scene judge: "sofa size is wrong (2.0 m instead of 2.2 m)". 2.0 is s1's
    kept value, 2.2 is only in the goal, and the judge's own rule forbids judging sizes.
  - n-blender-0000-01 r1 s1 and r2 s1: `handoff_long` on the values steps' faithful provides lists.
  - The third run's `tests_unconfirmed` files example.

### Why Blender still yields little

From the yield analyst's reading of the records. Three checkers then recounted each claim; the figures here are
theirs where they differed.

1. **Blender 5 API faults the teacher keeps making, led by `Action.fcurves`.** It is gone in 5.x, and it hit 16 of
   123 Blender tries, on all 4 animation steps.
   - Every repair dodged it with `hasattr`, `getattr(..., [])` or by deleting the interpolation, instead of using the
     channelbag path, `bpy_extras.anim_utils.action_get_channelbag_for_slot(action, slot).fcurves`, which works in
     both Blenders. With that path, 12 of the 14 crashing tries run clean, though 6 of them then leave their camera as
     Camera.001 behind the factory one.
   - Video needs `image_settings.media_type = "VIDEO"` before FFMPEG, and the container is `ffmpeg.format`. All 8
     tries of blender-0008-00 s5 missed it.
   - The 5.x compositor is `scene.compositing_node_group`, with no Composite node. All 6 tries of blender-0002-02 s4
     missed it.
   - SVG import is `bpy.ops.import_curve.svg`.

   Nothing in the teacher's notes or Chimera's names sheet says any of this.
2. **The build drops what the gate never told the teacher.** Validator warnings (`handoff_long`, `provides_missing`,
   `uses_undeclared`) reach no tell. `dead_output_key` is told only when the step asks for an output: 28 of 123 tries
   carry such a key, and none was told. 5 kept pieces fell to these filters after sampling had stopped.
3. **The values-only steps can't pass `handoff_long`.** VALUES_NOTE asks for every handed-on key under provides, and
   hydra:1.0's plans name 19 or 20 of them. Even a bare list is 331-384 characters. The limit is in the contract
   (Chimera's `handoffLineMax`, 300).
4. **The scene judge broke its own rule on all 4 of its Blender rejections.** It judged sizes from the goal that the
   request doesn't carry, positions that are object origins after `transform_apply`, and output forms the contract
   overrides ("a blender_script variable"). Two of the rejections cost yield:
   - n-blender-0000-01 r1 s2, which took its two dependents with it;
   - n-blender-0000-00 r1 s2, a clean piece that then went to a repair over the share.
5. **The camera habit:** of the 14 tries of n-blender-0000-01's two camera steps, 11 never make their camera the
   scene's camera.
6. **The second sampler** took 35% of Blender model time for 1 example.
   - 2 of its 24 Blender calls ran out of room while still thinking, at `num_predict` 8,192.
   - 3 hit the 3,500-token piece limit. That limit uses Chimera's estimate (bytes / 3 + 64), and it turned down
     pieces of 2,311-2,556 real tokens.
7. **Smaller faults:**
   - An untagged handoff fence: 11 of the 12 tries the validator failed for a missing handoff block. A mechanical fix
     makes 10 of them validate, but only 3 then run clean alone.
   - `rna_lint`'s attr rule fails a `hasattr`-guarded fallback that works: n-blender-0000-01 r2 s3 c5, the one try
     of that step with the camera right.
   - `attr_miss` is recorded but never gated: blender-0008-00 s4's kept piece claims LINEAR keys that stay Bezier.
   - At smoke scale the failed-dependency cap allows 0 Blender examples written with a missing dependency, which
     cost blender-0008-00 s2 and s4. At a night's scale it would allow about 64-71.

Found on the way: the third run's one `Weight` crash was on the Subsurface Scattering node. The names sheet doesn't
list that node, which also keeps an unavailable `Weight`, so the crash's absence now isn't the sheet's doing.

### What it means

The round did what it was aimed at: `ctx_channel`'s drops are gone, values-only steps hand their values on the
contract's way, and quality held (8% bad). But Blender still gives 4 examples from 21 steps, now for other reasons:
- Blender 5 API faults;
- build-only filters with no tell;
- the values steps' provides limit;
- a scene judge that judges sizes;
- the camera habit.

All of them but the provides limit can be fixed in data generation. The analyst estimates 3-6 more Blender examples
per smoke and 15-20% less Blender model time. The provides limit is in the contract, so it is the user's decision.

## Fifth smoke run (Nov 6)

### What ran

The fourth run's 8 seeds, into `data/gen/smoke5/` (gitignored), after the round that followed the fourth run
(`datagen/DESIGN.md`, "After the fourth smoke": Blender 5 facts and the camera and output notes for the teacher, the
build's drops and the stand-in marker's faults told and failed at the gate, `attr_miss` and `doubled_depth`, the
scene judge without the goal and with a measured overrule, a third told batch, no qwen3.8 on API-only steps, the
handoff fence; two rounds of independent checks and the main session's decisions; `DATAGEN_FORMAT` 5). Same models,
Ollama 0.40.1, 1 parallel; the same binary `458dcbfc…` (nothing in `app/` changed). The call cache was seeded with the
fourth run's 1,282 calls (not its runs cache, as before). The run used 286 calls: 150 (3,272 s) answered from that
cache, which again covered every code and writing step, and 136 new. The tasks took 89.2 minutes (1.49 h with the
build and the datagen tests), with 0 errors. Chimera was lending (FORCE=1).

### Yield and time

| mode | fourth run: built | fifth run: built |
|---|---|---|
| blender | 4 | 9 |
| files | 11 | 11 |
| python-script | 10 | 10 |
| section | 1 | 1 |
| all | 26 | 31 |

- **The code examples are byte-identical** to the fourth run's again; only Blender and the section in a Blender seed
  changed.
- **Blender: 21 steps and 2 variants, 11 kept with an example to give, 9 built.** By sampler: first samples 3, told
  samples 3 (one of them a reply the handoff fence made plain), qwen3.8 2, a mixed-pool variant 1; the third batch and
  the repairs gave none. Against the fourth run, 8 were won (n-blender-0000-00 s1 and s3, blender-0008-00 s1 and s4,
  n-blender-0000-01 r1 s2 and its variant, r2 s2 and s3) and 3 lost (blender-0002-02 s1, the bad doubled logo of the
  fourth run, and s2; n-blender-0000-01 r2 s4, whose round 2 had another plan).
- **Model time on Blender: 5,276 s,** against 4,957 s; **590 s per example,** against 1,243 s. qwen3.8 took 2,050 s
  (39%) for 2 examples (0.98 per 1,000 s), the told batches 1,171 s for 3 (2.56), the first samples 1,300 s for 3
  (2.31).
- **Projection: 154 h** at 1 parallel for 1,700, or 119 h at an assumed 1.3x for 2, against 270 h.

### Quality

A blind audit, same rubric:
- **Graded:** the fifth run's 9 Blender examples and its section, all new. Two graders read each independently and ran
  every Blender piece joined in 5.2.2 and 5.0.1; a skeptic settled each grade.
- **Carried over:** the 21 code examples, byte-identical to the fourth run's, keep the fourth audit's grades, and so do
  the fourth run's own 4 Blender examples and its section (not regraded).

| mode | fourth run: ok / weak / bad | fifth run: ok / weak / bad |
|---|---|---|
| blender | 0 / 3 / 1 | 0 / 9 / 0 |
| files | 4 / 6 / 1 | 4 / 6 / 1 |
| python-script | 9 / 1 / 0 | 9 / 1 / 0 |
| section | 0 / 1 / 0 | 0 / 0 / 1 |
| all | 13 / 11 / 2 (8% bad) | 13 / 16 / 2 (6% bad) |

- **No Blender example is bad, and none is ok.** The graders agreed on 7 of 9; the skeptic settled one ok-or-weak as
  weak and refuted one bad (a mixed-pool step that copied its broken dependency's values into its own settings: the
  copied values equal the dependency's, and the joiner rejects that dependency, so nothing is read silently). All 9
  run in both Blenders with the step's sizes, places, light directions and camera aim. They are weak mostly in their
  handoffs and comments: values written that provides doesn't list (one through a bound name), vague uses lines, an
  "assumed: none" over guesses, wrong comments (an area light's shape, its shadow softness), a deprecated
  `use_nodes` call, objects left in the factory collection, a Principled BSDF asked for and an Emission node given.
  Two come close to bad and are worth watching: offsets computed from the wrong axis (harmless numbers here) and a
  self-crossing fallback face for a missing SVG.
- **The bad section** is blender-0008-00 s6, rebuilt because its dependencies changed: its packaging script, the
  step's one deliverable, doesn't parse (a key opened with `"` and closed with `'` inside an f-string), and its README
  says GPU rendering was enabled as fact. The section checks read prose; nothing parses a section's code.
- **Drops: 19 new, all right.** One marked false was refuted (a failed-dependency variant whose own assumed line ties
  its uses item to the failed step). The 9 identical to the fourth run's keep the fourth audit's verdicts. The two
  values steps' kept pieces (n-blender-0000-01 r1 s1 and r2 s1) are the open contract question again, best weak.
- **A new gate gap:** the alone run builds `ctx` at module level (`aloneScript`), so a module-level helper that reads
  a global `ctx` passes alone, while Chimera's real join calls `build_sN` inside `main()` and raises NameError there.
  The gate's joined run is Chimera's own join and already crashed on it (smoke4's n-blender-0000-01 r2 s2 c0), so the
  gap is a variant's, which is checked alone (corrected after the next round's checks; the audit's skeptic first said
  both runs). It took no example here, and no built example of the fourth or fifth run has it.

### What the round did

From the yield analyst's reading of the records (every gate claim replayed through the real gate in both Blenders):
- **The facts and notes worked where they were followed.** Video set `media_type` on 7 of 7 tries (0 of 8 before),
  SVG import went right on 6 of 6, every try of the extruded logo halved its depth or used Solidify (`doubled_depth`
  fired on none), the scene's camera was set on 31 of 32 camera-step tries (12 of 31 before), and render or save calls
  in code fell from 7 tries to 1.
- **Keyframes didn't improve:** `Action.fcurves` on 11 of 121 tries (16 of 123 before), and 6 more took the channelbag
  path with a wrong slot (None, or the action), because the fact says "(action, slot)" without naming the slot and
  "(None before its first key)" reads as "pass None". qwen3.8 used the slot right. With the slot named, 6 of 12
  patched keyframe tries pass the gate.
- **The compositor didn't improve:** the plan's own words ask for a Composite node, so every try built one.
- **The told build facts won 2 examples** (a dead output key and a silent default fixed in the told batch). The
  stand-in marker for a missing input file was repeated on 5 of 10 told retries (gpt-oss), never by qwen3.8. One tell
  was wrong: `dead_output_key` on a step that asks for the output path, read through the piece's own getter (4 tries,
  no example lost).
- **The scene judge** gave 18 verdicts and one rejection, which was right (a material never made); nothing needed an
  overrule. The fourth run's 4 rejections were all false.
- **The sampler:** the third batch fired on 3 steps, 6 calls, 195 s, 0 gate passes. The qwen3.8 skip fired once,
  rightly (the compositor step), saving about 180 s. `num_predict` 12,288 let 5 replies finish that 8,192 would have
  cut, and one still ran out; none passed. The handoff fence made 15 replies plain, 13 reached the gate, and 1 became
  an example; `handoff_missing` fell from 11 tries to 0.

### What holds Blender back now

1. **gpt-oss ignores some notes:** the keyframe slot, the stand-in marker for missing files, and plan words that ask
   for gone APIs (a Composite node, a 'PLANE' area light).
2. **qwen3.8 is the last sampler, so its long handoff lines are never told:** blender-0008-00 s2 and s3 were kept only
   as a dependency on `handoff_long` (349 and 309 characters with notes in brackets); names-only lines of 115 and 77
   characters pass the whole gate. These aren't values steps, so this isn't the contract question.
3. **Two open contract questions:** the values steps' provides limit (2 examples here, both weak, both carrying a
   waived stand-in marker for their own `render_device`), and what `SETTINGS_sN["output"]` holds for a step that asks
   for a .blend and a render (blender-0008-00 s5, 5 tries).

### What it means

The round did what it was aimed at: Blender went from 4 examples to 9 at less than half the model time each, the
projection fell from 270 h to 154 h, and quality held (6% bad, no bad Blender example). The analyst's ranked next
changes, all data generation only: name the keyframe slot in the fact and its fix line (+1 here, and 84 of 545 corpus
steps name keyframes); a note to every Blender step that isn't a values step, before any sampler, that a handoff line
lists names only (+2); a plain print instead of the stand-in marker for a missing input file, in the note and the
tell (+1 to +2); retire the third batch (0 for 6); `dead_output_key` following a key through the piece's own getter;
the soft keep judging tries that built something first; a few cheap API facts. Together about 4-5 more Blender
examples on this run, so about 13-16 instead of 9 and roughly 105-115 h for 1,700. Also found: nothing parses a
section's code, and the module-level `ctx` gap of the alone run. The two contract questions are the user's: the provides limit would
win 2 more here.

## Sixth smoke run (Nov 6)

### What ran

The fifth run's 8 seeds, into `data/gen/smoke6/` (gitignored), after the round that followed the fifth run
(`datagen/DESIGN.md`, "After the fifth smoke": the keyframe slot named, a names-only handoff note for every Blender step
that isn't a values step, a plain print for a missing input file, the third batch retired, a section's python blocks
parsed, a module-level read of a global `ctx` failed; `DATAGEN_FORMAT` 6). Same models, Ollama 0.40.1, 1 parallel, the
same binary `458dcbfc…`. The call cache was seeded with the fifth run's 1,418 calls. The run used 305 calls: 144
(3,103 s) answered from that cache, which covered every code and writing step, and 161 new; every Blender teacher copy
was new. The tasks took 107.1 minutes (1.79 h with the build and the datagen tests), with 0 errors. Chimera was lending
(FORCE=1).

### Yield and time

| mode | fifth run: built | sixth run: built |
|---|---|---|
| blender | 9 | 13 |
| files | 11 | 11 |
| python-script | 10 | 10 |
| section | 1 | 0 |
| all | 31 | 34 |

- **The code examples are byte-identical** to the fifth run's again.
- **Blender: 23 steps and 3 variants, 16 kept, 13 built,** by sampler: first samples 1 (3 before), told samples 7 (3),
  qwen3.8 5 (2), variants 0 (1). Against the fifth run, 7 were won (blender-0002-02 s1 and s4, blender-0008-00 s2, s3
  and s5, n-blender-0000-00 s2 and s4) and 3 lost (n-blender-0000-00 s1, a values step now kept by qwen3.8 with a long
  provides line; n-blender-0000-01 r1 s2's variant; one of round 2's, whose plan changed).
- **The section is gone:** blender-0008-00 s6 (the fifth run's bad example) was redrawn and failed `step_id_leak` ("step
  s5" in a README for a person) on 3 of 3 tries.
- **Model time on Blender: 6,130 s,** against 5,276 s; **463 s per example,** against 590. The told batches gave 7
  examples at 4.6 per 1,000 s, qwen3.8 5 at 2.5.
- **Projection: 134 h** at 1 parallel for 1,700, or 103 h at an assumed 1.3x for 2, against 154 h. It counts every built
  example, bad ones included.

### Quality

A blind audit, same rubric: the sixth run's 13 Blender examples (all new) were graded by two graders each, every piece
run joined in 5.2.2 and 5.0.1, and a skeptic settled each grade; the 21 code examples, byte-identical, keep their
grades.

| mode | fifth run: ok / weak / bad | sixth run: ok / weak / bad |
|---|---|---|
| blender | 0 / 9 / 0 | 1 / 5 / 7 |
| files | 4 / 6 / 1 | 4 / 6 / 1 |
| python-script | 9 / 1 / 0 | 9 / 1 / 0 |
| section | 0 / 0 / 1 | none |
| all | 13 / 16 / 2 (6% bad) | 14 / 12 / 8 (24% bad) |

- **The quality drop is real, not the graders.** A second blind regrade mixed the fifth run's 9 Blender examples with 4
  of the sixth's under new names: the fifth run's came out 8 weak and 1 ok, none bad, as before; the sixth run's two
  bad and one ok came out the same, and its weak n-blender-0000-00 s2 came out bad (a 0.75 m stove where the step says
  0.6 m, cutting into the fridge). So the usable Blender examples (ok or weak) fell from 9 to 6, or 5.
- **The 7 bad Blender examples,** 6 of them from gpt-oss's first and told batches, are faults the gate doesn't measure:
  - lights aimed wrong by their own rotation: n-blender-0000-01 r2 s4's two side spots face the walls, and
    blender-0002-02 s3's softbox points along +Y, 50° off the logo, under a comment saying "point down -Z";
  - a place relative to another thing: blender-0008-00 s2's backplate "behind" the logo cuts through its middle,
    because the piece ignores the extrude depth s1 hands on;
  - a fallback that doesn't do what it says: blender-0008-00 s3, with its HDRI missing, links an Environment Texture with
    no image to the background, so the world renders magenta, while it prints and claims a grey one;
  - handoffs that say a dependency was missing when its piece is right there ("assumed: Acme_Logo missing, stand-in
    created" on blender-0008-00 s2 and s4), or state a missing file as fact;
  - blender-0002-02 s1's "curve forming the letters Pulse" made as one 8-point placeholder loop with no caps;
  - n-blender-0000-00 s4, a combine step, rewriting the other steps' code as strings that nothing runs.
- **Drops:** 15 of the 16 new Blender drops and the section's were right; the 16th (n-blender-0000-01 r1 s1, a values
  step) hangs only on the open contract question and would be a weak example. The checkers found three generator bugs: the stand-in
  check reads the marker as a substring of the whole output, so a piece that prints its own source got a false
  `stand_in`; a repair keeps its base's stale crash when it fails before the gate, which built one incoherent repair
  request; and a dropped step's best try opened with "Key pitfalls from previous failures: ...", a paraphrase of the told
  notes that `normalise` doesn't strip (the step fell on other grounds; whether the echo check would have refused it
  wasn't measured).

### What the round did

From the yield analyst's reading of the records:
- **Every item did what it set out to do.** Channelbag calls with a wrong slot went from 6 tries to 0, and all 6 told
  tries that heard the fix line used `obj.animation_data.action_slot` (the first batch, which hears only the fact,
  still wrote `Action.fcurves` on 6 of 8). qwen3.8's handoff lines over 300 characters or with notes in brackets went
  from 23 of 23 tries to 2 of 20, gpt-oss's bracket notes from 16 to 0, and blender-0008-00 s2 and s3 became examples.
  gpt-oss printed Chimera's marker for a missing file on 3 of 12 tries (14 of 16 before) and a plain line on 6. The
  third batch drew nothing. `code_syntax` never fired (the redrawn section parsed); `global_ctx` was recorded on 6
  gpt-oss tries, the reason on 3, and cost no example.
- **But the told batch now gets pieces past the gate whose faults the gate can't see.** The round removed faults the
  gate measures and tells (wrong API names, long handoff lines, misused markers), so more pieces reach an example,
  and what's left in them is what nothing measures: aim, relative places, fallbacks, the truth of the handoff.
- **What else holds Blender back:** plan wording against Chimera's rule (round 2 of n-blender-0000-01 asks s1 to
  "clear the default scene", which failed `deletes_scene` on 5 of 6 tries and took s2, s3 and s5 down with it, 1,742 s
  for 1 example; steps that ask for their code as a string or as one combined script); round 2's planner fell to
  gpt-oss because its request was 7,167 tokens, over the helper's 7,000; and the values steps' provides limit (2
  examples, both of which guess the numbers the person gave, because a values step's request shows no goal).

### What it means

Yield went up, from 9 Blender examples to 13 and from 154 h to 134 h, but quality went down: 7 of the 13 Blender
examples are bad, against none of the fifth run's 9, and only 6 are usable. More examples at this quality would teach the
worker wrong aims, wrong places and false handoffs, so the next round has to be about quality before the nights: checks
for what the bad ones got wrong (a light's direction against the step's words, a place relative to another named
thing, an Environment Texture with no image, a handoff that calls a present dependency missing or states a missing file
as fact, a combine step that rewrites others' code), the three generator bugs, and a note for plan wording that goes
against Chimera's rule. The values steps' provides limit stays the user's decision; the audit adds that both pieces it
would win guess the person's numbers, because a values step's request shows no goal, which is also Chimera's request
text and the user's to decide.
