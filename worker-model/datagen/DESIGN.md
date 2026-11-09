# Hydra Worker data generation: design (Nov 3, 2026)

The code in this folder makes Hydra Worker 1.0's training data. It follows `docs/hydra-worker-plan.md`, section
"3. TRAINING DATA", with the contract as approved on Nov 1 and ported to Go on Nov 2. This file is the spec the
modules were written against; the README's "Data generation" section is the user-facing summary.

## Rules that hold everywhere

- **No Claude output in training data.** Claude writes code, topic labels, teacher instructions, judge rubrics and
  test fixtures. Seed texts, plans, pieces, repairs and tests run in the sandbox are written by open models
  (gpt-oss:120b, hydra:1.0, qwen3.8:27b, qwen3:8b). Every Claude-written text that could be mistaken for data
  (test fixtures, canned mock replies) carries `# test fixture, never training data` (runner/mock_ollama.MARK).
- **Go is the source of truth** for every request a worker gets and for every join: the Chimera binary's
  `--hydra-worker-request`, `--hydra-assemble`, and (new) `--hydra-plan-request`, `--hydra-review-request`,
  `--hydra-read-reply`. No Python copy of a request enters training data.
- **The training input is exactly Chimera's request.** Teacher-only hints go into the teacher's copy (appended to
  its system message) and never into the stored training request. The stored request is the Go output, untouched.
- **Eval stays out.** Nothing from `worker-model/eval/` (plans, deps, W2 facts) or `helper-model/eval*/` is fed to
  a teacher or kept. Seeds and examples pass `tools/check_overlap.EvalIndex`.
- **Nothing outside `--data-dir`** is written by a run (default `worker-model/data/gen/<size>/`, gitignored), except
  the Blender and Python run folders under `$WM_SCRATCH` (removed after each run), and Ollama's own state.
- **Prompts that Hydra 1.0 was trained on are not changed.** The new Go modes print the existing requests.
- **Resumable and deterministic.** Every model call and every Blender/Python run is cached by a hash of its full
  input; a seed's work is a deterministic function of the cache. Kill a run and start it again: finished seeds are
  skipped, unfinished ones replay from the cache to where they stopped. Changing a prompt changes the hash, so a
  resumed run never reuses a reply to a different request.

## Data folder (`--data-dir`, default `worker-model/data/gen/<size>`)

```
RUN.json              size, models, binary sha and version, fingerprint, Ollama version, started, args (rewritten on
                      each start)
names/5.2.2.txt       `chimera --blender-names` from each Blender (printed again at every start, never read back)
names/5.0.1.txt
cache/calls.jsonl     one line per model call (key -> reply, stats, wall)            common.Cache
cache/runs.jsonl      one line per Blender or Python run (key -> verdict, seconds)   common.Cache
seeds.jsonl           the seeds this size uses (derived, rewritten atomically)
seed_calls.jsonl      the teacher's seed-writing calls (Store)
tasks.jsonl           one line per finished seed: everything that happened (Store)
gate.jsonl            model switches and waits (append only)
progress.log          one line per finished step and seed
STOP                  touch it to stop after the calls in flight (the run exits 3)
STOPPED.md            written by an early stop
early_stop.json       the early stop passed (or was passed over with --no-early-stop): it isn't checked again
sft/train.jsonl, valid.jsonl, train.meta.jsonl, valid.meta.jsonl, STATS.md      build
REPORT.md, report.json                                                           report
```

## Modules and who calls whom

```
run.py ── seeds.py ── llm.py, topics.py, common.py
       ── task.py ─── llm.py (Gate, LLM), chimera.py, blender_gate.py, code_gate.py, prose_gate.py,
       │              judges.py, hints.py, names (chimera.py), common.py
       ── build.py ── common.py, tools/check_overlap.py
       └─ report.py
```

### common.py

- `HERE` (worker-model/), `DATA_ROOT` (worker-model/data/gen).
- `key_of(*parts) -> str`: sha256 of `json.dumps(parts, sort_keys=True, ensure_ascii=False)`, first 24 hex chars.
- `stable_int(*parts) -> int` (first 8 hex chars of sha256 over "\x1f".join(map(str, parts)), as helper-model's),
  `rng(*parts) -> random.Random`, `chance(p, *parts) -> bool` (stable_int % 10000 < p * 10000).
- `est_tokens(text) -> int`: Chimera's estimateTokens, `len(text.encode()) // 3 + 64`; `msgs_tokens(messages)`:
  the sum over messages (Chimera's historyTokens).
- `class Store(path)`: append-only JSONL keyed by `rec["key"]`, as helper-model's (a half last line is skipped and
  the file gets its newline back; the later of two lines wins) plus a `threading.Lock` around `add`, `has`, `get`,
  `all`, `__len__`. `add` flushes; no fsync.
- `class Cache(path)`: a Store of `{"key", "value"}`; `get(key) -> value|None`, `put(key, value)`.
- `write_jsonl(path, rows)` (atomic: .tmp then os.replace), `read_jsonl(path)` ([] when missing),
  `write_json(path, obj)` (atomic).
- `class Progress(stage, total, log_path)`: helper-model's (`step(label, status, wall=None)`), thread-safe.
- `class StopRequested(Exception)`; `check_stop(data_dir)` raises it when `data_dir/STOP` exists.
  `write_stopped(data_dir, title, lines)` writes STOPPED.md. `class Stopped(SystemExit)` (code 3).
- `run_record(data_dir, **fields)`: RUN.json (keeps earlier `starts` in a list).

### chimera.py (the binary)

`class Chimera(binary)`. Every method runs one subprocess with JSON on stdin and parses one JSON object from
stdout; a non-zero exit or unreadable output raises `ChimeraError` with stderr's last line. Inputs are passed
with `ensure_ascii=False`. Pure functions of their input, so results are memoised in-process (an LRU keyed by
`key_of(mode, payload)`; no disk cache needed: each call takes milliseconds).

- `version() -> str` (`--version`), `sha256() -> str` (of the binary file).
- `worker_request(plan, index, outputs, *, goal="", names="", names_gate=True, refs=None, prev_result=None,
  critique="", piece=None, crash=None, room=None) -> dict` → `--hydra-worker-request`.
  Returns `{messages, need_ctx, mode, sid, n, lone, deps, round2_matched}`. `outputs` is keyed by cleaned step id;
  a step left out counts as failed (Go's rule); a value is a string (done) or `{"output": str, "status": ...}`.
- `plan_request(goal, *, history=None, prior="", critique="", refs=None) -> dict` → `--hydra-plan-request`:
  `{messages, need_ctx, format, helper_fits}`.
- `review_request(goal, result) -> dict` → `--hydra-review-request`: `{messages, need_ctx, format, helper_fits}`.
- `read_plan(reply) -> {"ok": bool, "plan": cleaned plan | None}` and `read_review(reply) -> {"ok", "done",
  "score", "critique"}` → `--hydra-read-reply`.
- `validate(jobs) -> [verdict]`, `alone(jobs) -> [str|None]`, `locate(jobs) -> [dict]`, `scan(codes) -> [dict]`,
  `slug(titles)`: the `--hydra-assemble` jobs (one subprocess for a whole list).
- `join(plan, outputs, *, goal="", done_reasons=None, reject_cut=False) -> dict`: `--hydra-assemble`'s join.
- `check_result(path, *, goal=None, work_dir) -> dict`: `--data-dir <fresh dir> --check-result path
  [--check-goal goal]` with `CHIMERA_LOOK_MODEL=datagen-no-look` in the environment (no vision call: it would load
  qwen3.8:27b next to gpt-oss:120b). Returns the parsed JSON plus `exit`.
- `blender_names(blender_path, scratch) -> str`: `--blender-names` with a PATH shim (tools/blender_check's
  launcher) so the asked version prints its own sheet.

### New Go modes (app/, CLI only: real long tasks unchanged)

All in a new `app/datagen_cli.go`, flags in `app/main.go` beside the other two, exit 0, or 2 with a
`<mode>: ...` line on stderr. They print what the app itself would send, built by the same functions:

- `--hydra-plan-request`: stdin `{"goal", "history": [{"role","content"}]|null, "prior", "critique",
  "refs": [LibEntry]|null}`. The user message is built by a function factored out of `onePass` (both use it), from
  `planPrior(prior, critique)` and `critique` exactly as onePass gets them from `base`; refs are filtered by
  `Score >= 0.3` as onePass does. Stdout `{"messages", "need_ctx": historyTokens + 2048, "format": "json",
  "helper_fits": need_ctx <= helperMaxCtx}`.
- `--hydra-review-request`: stdin `{"goal", "result"}`; `reviewRequest(taskReq{Goal: goal}, result)`; stdout
  `{"messages", "need_ctx", "format": "json", "helper_fits": need_ctx <= helperMaxReviewCtx}`.
- `--hydra-read-reply`: stdin `{"plan": reply}` → `{"ok", "plan"}` with askPlanner's rule (extractJSON into
  hydraPlan and at least one step), the plan after `cleanPlan`; or `{"review": reply}` → `{"ok", "done", "score",
  "critique"}` with askReviewer's rule.
- `--hydra-worker-request` gains `"names_gate": bool`: when true, `names` is added only if namesBlock's rule holds
  (`kind == "blender"` or `blenderTaskRe` matches goal + title + summary), through a `namesApply(kind, plan, goal)`
  factored out of `namesBlock`, which both use.
- Go tests for each mode, and `go test ./...` still passes.

### llm.py (models)

- `class Gate(groups, parallel=1, idle_switch_s=15.0, starve_s=1200.0, log_path=None)`. `groups` is a list of
  sets of model names that can be loaded together (default `[{"gpt-oss:120b", "hydra:1.0"}, {"qwen3.8:27b"},
  {"qwen3:8b"}]`; a model in no group is its own group). `with gate.slot(model, purpose):` blocks until the model's
  group is the active group and fewer than `parallel` calls are in flight. Switching policy: stay on the active
  group while anyone waits for it; switch when nobody has asked for the active group for `idle_switch_s`
  (threads are often in a Blender check for a few seconds, so waiting a little avoids switching back and forth),
  or when someone has waited for another group for `starve_s`. Switch to the group with the most waiters (ties:
  the longest wait). A switch waits for the calls in flight to end. Every switch and every wait over 60 s goes to
  `gate.jsonl` (`{"t", "from", "to", "waiters", "waited_s"}`). `stats()` gives counts and seconds.
- `class LLM(host, gate, cache, timeout=900.0)`. `call(model, messages, *, purpose, options=None, fmt=None,
  think=None, worker=False, sample=0, num_ctx=None) -> Reply`.
  - The body is Chimera's (`runner.common.chat_body`'s shape without its names hook: stream true, keep_alive
    "15m", only role and content per message, `options.num_ctx`, `format` only when given, `think` only when
    given). `num_ctx`: the argument, else `FIXED_CTX[model]` (32768 for gpt-oss:120b, qwen3.8:27b and qwen3:8b,
    so the 65 GB model never reloads for a bigger bucket), else `ctx_bucket(msgs_tokens(messages) + 4096)`.
  - `options.seed = stable_int(key)` unless the caller gives one, so samples differ and replay the same.
  - The cache key is `key_of(model, messages, options without seed, fmt, think, worker, sample)`.
  - A cached reply returns at once with `cached=True` and no gate slot. Only finished calls are cached (no error,
    or a runaway, which is a property of the reply); a failed call is not, so a resumed run asks again.
  - Uses `runner.common.Ollama` (the 16,384-token guard; `worker=True` also caps content at 6,144) and
    `runner.common.ask` (two tries when the call itself fails).
  - `Reply` (a dataclass): `content, thinking_chars, stats, done_reason, error, wall_s, cached, key, model`.
    `runaway` property (`done_reason == "runner_cut"`).
  - `stats()` per model and purpose: calls, cached, wall seconds, eval and prompt tokens.

### topics.py and seeds.py

- `topics.py` (Claude-written labels and instructions; the seed texts come from the teacher):
  `BLENDER_TOPICS` (about 35 labels across modelling, modifiers, geometry nodes from Python, materials, lighting,
  cameras and keyframes, render and 5.x compositor settings, scatter, bmesh, simulations), `PYTHON_TOPICS` (about
  25: runnable programs a person asks for), `MIXED_TOPICS` (about 10: a Blender scene plus writing about it),
  `STYLES`, `LENGTHS`, `SEED_SYSTEM`, `seed_user(target, topic, style, length, k) -> str`. Blender seeds must ask
  for scenes built from nothing (no existing .blend, images or other files unless the task makes them) in Blender
  5.x, and must be multi-part tasks a planner would split into 2-6 steps. Python seeds must be runnable with the
  standard library, no network, no GUI. None of the eval's scenarios: the instruction tells the teacher to avoid
  "product shots of bottles or watches, bookshelves, staircases, ..." (the eval's titles, listed by
  `seeds.eval_titles()` at run time, not copied by hand).
- `seeds.py`: `make_seeds(llm, data_dir, size) -> [seed]`.
  - New seeds: `size["new_calls"]` = `{target: (calls, k)}`; one teacher call per (target, i) (gpt-oss:120b,
    `fmt="json"`, temperature left to the model, num_predict 7000), reply `{"tasks": [str, ...]}`. Each call's record
    goes to `seed_calls.jsonl` (key `f"{target}-{i:04d}"`).
  - Helper seeds: from `helper-model/data/seeds.jsonl`, `seeds2.jsonl`, `seeds3.jsonl` (read only), by category.
    `small_task` seeds are lone-step candidates (`size["helper"]["small_task"]`, about 60 at night).
  - Kept if 15 to 8,000 characters, not an exact or near repeat (5-word shingles, Jaccard >= 0.5, against every
    kept seed of either source), not an eval overlap (`EvalIndex.check(text, 0.3)` empty), and not naming an eval
    scenario (`eval_titles()`: every multi-word title of the worker eval's plans, lower-cased, matched as a
    phrase). Drops go to the seeds record with their reason.
  - A seed: `{"key": seed_id, "seed_id", "source": "new"|"helper", "category": "blender"|"python"|"mixed"|
    "coding"|"research_draft"|"planning"|"batch"|"small_task", "text", "history", "params", "call_key"}`. New
    seed ids: `n-{target}-{i:04d}-{j:02d}`; helper seed ids are kept as they are.
  - Which seeds a size uses is chosen by `rng("pick", size_name, category)` over each category's kept seeds.

### hints.py (teacher only)

`hints_for(plan, i, mode, facts, failures=()) -> str`, appended by `teacher_copy(messages, hints)` to the
teacher's system message under the line `Notes for you, the teacher (Chimera doesn't send these):`.
- Always: "Format rules win over the instructions' wording about files." (the plan's wording), and for Blender:
  "The script is checked in Blender 5.2.2 and 5.0.1, sandboxed: no files outside its folder exist, so guard any
  file the task names (os.path.exists) and fall back to something built in code."
- Blender facts, mechanical, from `rna_lint.Facts` (both dumps, made by the two Blenders): for every node whose
  label or idname appears in the step's title or instructions (`Facts.labels`), its inputs and outputs per
  version; for every RNA class named there, its properties (names, enum items) per version, differences marked;
  and the engine and file-format enum values. Capped at 6,000 characters, most-mentioned first.
- `failures`: lint findings and crash lines of earlier candidates for this step; their classes and nodes are put
  first. So hints get sharper after a failure, still mechanical.

### blender_gate.py

`class BlenderGate(chimera, cache, versions=blenders.VERSIONS, jobs=4, linter=None, work=None)`.
Runs Blender through `runner.blender_run.Blender` (Chimera's `--check-result` per version through the PATH shim,
plus the direct sandboxed run whose whole output is read), with `probe_src` replaced by a no-op: the probe it keeps
is `tools/scene_probe`'s epilogue (ctx keys, names, `.001` duplicates), never the eval's probe. A semaphore
limits Blender processes to `jobs`. Every run is cached in `cache/runs.jsonl` by
`key_of("blender", script, versions, chimera.sha256(), RUN_FORMAT)`.

- `piece_check(plan, i, text, verdict, earlier, goal="") -> dict`. `verdict` is the Go validator's for this text;
  `earlier` is `{sid: text}` of the kept pieces of every earlier step (a dropped step is left out, so the join
  marks it failed). Steps, in order, stopping at the first that fails:
  1. lint (`rna_lint.Linter(Facts.load())`): any error fails (`lint:<kind>`).
  2. alone: Go's `alone` job with `keep_ctx: true, ctx_name: "ctx"`; `Blender.run`; `counted_strict` in both
     versions (`alone_strict:<v>`); the provides check (`runner.score.provides_probe(handoff, probe)` against
     each version's probe: `provides_missing`; Go's verdict has the handoff as a dict, so this is
     `runner.score.provided_names(handoff["provides"])` against the probe's `ctx_keys` and `names`), and no `.001`
     duplicates (`dupes`).
  3. joined: `chimera.join(plan, earlier + {this}, goal)`; a fallback fails (`join_fallback`); a seam in
     `{duplicate_name, ctx_key_missing, uses_unmatched, join_syntax}` fails (`seam:<code>`) unless it names a step
     that isn't in `earlier`; `Blender.run(script)`, `counted_strict` in both (`joined_strict:<v>`); a stand-in
     printed fails (`stand_in`) unless one of this step's dependencies is missing from `earlier`; no duplicates.
  Returns `{"ok", "reasons": [...], "lint": [findings], "alone": {v: {...}}, "joined": {v: {...}},
  "stand_in", "dupes", "provides_missing", "scene": {"objects", "materials", "collections", "ctx_keys"} (the
  alone probe's, factory names removed), "crash": crash|None, "seconds"}`. `crash` is the first definite crash
  with a line in this piece: for the alone run the line is the piece's code line (the alone script keeps line
  numbers) and `function`/`part` come from Go's `scan` tree or `ast`; for the joined run it is Go's `locate`
  with the join's line map. Its shape is Go's `workerCrash`: `{step, part, function, piece_line, line, source,
  error, runner}` (runner "Blender 5.2.2").
- `plan_check(plan, kept, goal) -> dict`: the join of every kept piece, run in both versions; strict in both, no
  duplicates, a stand-in only if a step was dropped, and every step's provides still present at the end
  (`provides_lost: [sid]`: a later step deleted or renamed it). If it fails, `culprit` is the step the line map
  names for a crash; for lost provides it is null (the step that removed them can't be told apart). Also runs `chimera.check_result` on the joined script with the goal (look off) and records its outcome
  (`scene_outcome`, `scene_critique`) without gating on it.

### code_gate.py and pysandbox.py

- `pysandbox.run(files, entry, *, timeout=30, stdin="", work=None) -> {"exit", "output", "timed_out",
  "seconds"}`: writes `files` (`{relative path: text}`) into a fresh folder, runs `python3 -I entry` there under
  `sandbox-exec` (no network; reads of /Users and /Volumes denied except the folder; writes only in the folder;
  no process-exec except python3 itself). Output capped at 20,000 characters. Unsandboxed only if sandbox-exec is
  missing, recorded as `sandboxed: false`.
- `class CodeGate(chimera, cache, work=None)`:
  - `piece_check(plan, i, text, verdict, earlier, mode, tests=None) -> dict`. python-script: the join of earlier +
    this (`join_syntax`, `duplicate_name` seams fail), the piece compiles, every identifier named under provides
    (`foo()`, `Foo`, `foo`) is a top-level name of the piece (`symbols_missing`), and when `tests` is valid, the
    tests pass against the joined file (`tests_failed`, with the traceback's last line). files: the join's seams
    `{join_syntax, file_conflict, import_unresolved, duplicate_name}` fail; every `.py` file compiles; tests as
    above with the merged files. Returns `{"ok", "reasons", "tests": {...}|None, "crash": crash|None,
    "seconds"}`; `crash` is a definite Python error located in this piece (runner "Python").
  - `tests_check(plan, i, tests_code, earlier, candidates, mode) -> {"valid", "why", "stub_failed",
    "passed": [bool per candidate]}`: tests count only if they fail on the stub (earlier steps only, this step's
    names missing) and pass on at least one candidate. A test file is `import sys; sys.path.insert(0, ".")`, then
    `import project` (python-script: the joined file saved as project.py; its main() is guarded) or the files'
    modules, then the teacher's asserts.
  - `plan_check(plan, kept, goal) -> dict`: the whole joined project compiles; if it has an entry point,
    `chimera.check_result` on it (Python, sandboxed, 30 s) must not say `failed` (a definite crash); `unsure` and
    `skipped` are recorded, not gated.
- Runs are cached in `cache/runs.jsonl` (`key_of("python", files, entry, stdin, the interpreter's real path,
  its version)`).

### prose_gate.py

`section_check(plan, i, text, verdict, earlier_sections) -> dict`: deterministic checks on a section piece. The Go
validator's `ai_talk`, `unmarked_link` and `placeholder` warnings fail here; a word target in the step's
instructions (`about 300 words`, `200-400 words`, `under 150 words`) must be met within 30%; the first or last
paragraph may not introduce or sum up the whole project (`In this document`, `In conclusion`, `To summarize`, ...)
unless the step's title says it is the introduction or conclusion; and no more than 20% of its 8-word shingles
may appear in an earlier sibling section of the same plan (`overlap:<sid>`). Returns `{"ok", "reasons", "words",
"target", "overlap"}`.

### judges.py (rubrics are Claude-written; replies are never training data)

All at temperature 0, `fmt="json"`, on gpt-oss:120b (second opinion on qwen3.8:27b where asked).
- `scene_messages(goal, plan, i, handoff, scene) -> messages` → `parse_scene(content) -> {"ok", "why"} | None`:
  did this piece build what its step asks, and nothing a sibling step owns? `scene` is what the piece made.
- `prose_messages(goal, plan, i, section, deps) -> messages` → `parse_prose(content) -> {"score": 1-5,
  "problems": [str]} | None`: does the section do its step, only its step, in the plan's terms, with no invented
  sources? Kept at 4 or more.
- `tests_messages(goal, plan, i, mode, deps) -> messages` → `parse_tests(content) -> str | None`: one python block
  of plain asserts that checks the step's functions by the names the plan and step give; no network, no files
  outside the folder, finishes in under 10 seconds, prints `tests ok` at the end.

### task.py (one seed, start to end)

`run_seed(env, seed) -> record`, deterministic given the caches. `env` bundles the LLM, Chimera, the gates, the
names sheets, the linter, the overlap index and the size's settings.

1. **Plan.** The planner for this seed: `chance(size["gpt_oss_planner"] (0.3), "planner", seed_id)` picks
   gpt-oss:120b, else hydra:1.0. A helper seed that drew gpt-oss and has an accepted plan in
   `helper-model/data/raw/plans*.jsonl` reuses that reply (re-read with `read_plan`, so cleaned by Go). Otherwise
   `plan_request(seed.text, history=seed.history)`, the call (format json, the planner's own options:
   `num_ctx` from Chimera's bucket, no temperature), `read_plan`. If hydra:1.0's plan can't be read, gpt-oss:120b
   is asked once, as Chimera does. No plan: the seed ends `no_plan`.
2. **Steps, in plan order.** For step i: its mode and request come from `worker_request(plan, i, outputs,
   goal=seed.text, names=sheet, names_gate=True)`, where `outputs` holds the kept pieces (a dropped step is left
   out: Chimera tells the step it failed). The names sheet is 5.2.2's for 75% of Blender steps, 5.0.1's for 15%,
   none for 10% (`rng("names", seed_id, sid)`), recorded on the step. The request is stored as it is: that is the
   training input.
3. **Candidates (adaptive best-of-N).** The teacher's copy is the request with `hints_for(...)` added. Samples
   are drawn in rounds: Blender 2 then 2 more (4 at most), python-script and files 2 then 1 (3), section 1 then 1
   (2). Each candidate goes through: the reply (no error, not a runaway, done_reason not "length"), the harmony
   check (`<|...|>`, `<|channel>`, `<channel|>`, `assistantfinal`, `<think>`), the Go validator (`form_ok`, reject_cut,
   max_tokens 3,500), the example's size (request plus target `est_tokens` <= 12,288), then its mode's gate
   (blender_gate / code_gate / prose_gate). For code, the teacher's tests are written once per step (before the
   first candidate is checked) and judged valid after the first round (`tests_check`). Among candidates that pass
   the mechanical gate, fewest validator warnings then shortest goes first to the judge (scene judge for Blender,
   prose judge for sections; code has none); the first the judge accepts is kept. Every other passing candidate
   is kept as an alternate.
4. **Repairs.** If none passed, the candidate that got furthest with a definite crash in its own piece gets up to
   2 repair turns: `worker_request(..., piece=its reply, crash=its crash)`, which is Chimera's own repair message
   (the training input of a repair example), the teacher's copy with hints (now with the crash's names first), and
   the gate again. A second turn repairs the first turn's reply with its own crash. A repair that passes and
   changes at most 30% of the piece's code lines (`runner.score.lines_changed(before, after)` over the number of
   lines in the failed piece's code)
   is a repair example; a passing repair is also the step's kept piece, but the step then gives no normal example
   (see "After the review", D3).
5. **Second sampler.** Still nothing for a Blender or code step: 2 samples from qwen3.8:27b (the gate groups its
   calls into a qwen phase), same checks, no repairs.
6. **Drop.** Still nothing: the step is dropped with the reasons of the candidate that got furthest; later steps
   that depend on it are told it failed (a natural failed-dependency example).
7. **Variants** (extra examples of a step that has a kept piece and at least one dependency; never fed to later
   steps): `failed_dep` (`chance(size["failed_dep"], ...)`: one dependency, chosen by rng, is left out of
   `outputs`), and `mixed_pool` (`chance(size["mixed_pool"], ...)`: one dependency's output is replaced by what
   qwen3.8:27b or qwen3:8b (rng) wrote for that step under today's prompt, `contract.today.worker_messages`, from
   the same inputs). Both are checked alone only (Blender: lint, alone strict, stand-ins expected; code: compile,
   symbols; sections: the prose gate and judge), with the same best-of-N but no repairs or second sampler.
8. **Plan check.** When every step was tried: Blender plans get `blender_gate.plan_check`, Python plans
   `code_gate.plan_check`. A failure names a culprit: the culprit's alternates are tried (when no later step
   depends on it, up to 3 more joins); still failing, the plan's Blender (or code) examples are marked
   `plan_failed` (build leaves them out unless `--keep-plan-failed`).
9. **Round 2** (`chance(size["round2"], "round2", seed_id)`, only when round 1 kept at least one step and the plan
   has 2+ steps): the round's result is the join's text plus its assumptions note. For a script, the check
   (`chimera.check_result` with the goal, look off): a `failed` or `wrong_scene` outcome makes its `critique` the
   next planner's critique (Chimera skips the review then). Otherwise the review: `review_request`, hydra:1.0 if
   `helper_fits` else gpt-oss:120b, `read_review`; `done` ends the seed (`round2: "review_done"`). Then
   `plan_request(goal, prior=result, critique=critique)` on hydra:1.0 if `helper_fits` else gpt-oss:120b, and
   round 2's steps exactly as above with `prev_result=result, critique=critique` in every request.
10. The record: `{"key": seed_id, "seed", "status": "done"|"no_plan"|"error", "error", "rounds": [round],
    "seconds", "finished"}`; round: `{"round", "planner": {model, key, wall_s, fell_back, reused}, "plan",
    "steps": [step], "variants": [step], "plan_check", "check", "review", "critique"}`; step: `{"sid", "index",
    "kind", "mode", "variant", "names", "request": {messages, need_ctx}, "request_tokens", "tests",
    "candidates": [cand], "repairs": [repair], "kept": {"from": "cand"|"repair"|"second", "index"}|null,
    "alternates": [index], "drop": [reasons]|null, "plan_failed": bool, "seconds": {teacher, checks, judge}}`;
    cand: `{"model", "key", "sample", "content", "done_reason", "stats", "wall_s", "cached", "gate": {...},
    "judge": {...}|null, "passed": bool}`; repair: `{"from", "turn", "crash", "request", "content", "key", "gate",
    "lines_changed", "example": bool}`.

Concurrency: `size["seeds_parallel"]` seeds run at once in threads (smoke 6); the Gate serialises model calls;
Blender and Python runs overlap them. `check_stop` is called before every model call.

### build.py

`build(data_dir, size, keep_plan_failed=False) -> stats`. From `tasks.jsonl` only:
- one example per kept step (`{"messages": request.messages + [{"role": "assistant", "content": kept content}]}`)
  and per repair example (its own request + the repair);
- dropped when over 12,288 estimated tokens, when `EvalIndex.check(user + target, 0.5)` hits, when a repair
  would take repairs over 15% of the Blender and code examples (latest dropped first, by rng), or on an exact
  duplicate of another example's messages;
- split: 5% of seed groups (at least 1 when there are 4 or more) go to valid, by `stable_int("split", group)`;
- `sft/train.jsonl`, `valid.jsonl`, the parallel `*.meta.jsonl` (`{"group", "seed_id", "sid", "round", "kind",
  "mode", "variant", "model", "names", "repaired", "request_tokens", "target_tokens"}`), and `STATS.md`.
- `tools/check_overlap.py` is run on both files as a last check (exit 1 stops the build).

### report.py

`report(data_dir) -> dict` and `REPORT.md`: seeds made and kept (by reason); plans by planner and the read rate;
steps by mode: tried, kept on the first round of samples, after more samples, after repairs, from the second
sampler, dropped (by reason); variants; plan checks; round 2; model time per purpose (from the call cache and
`gate.jsonl`), Blender and Python seconds; wall time; and the projection the smoke is for: seconds of teacher time
per kept example by kind and the hours to reach the plan's 1,700 examples in its mix (Blender 640, code 540,
writing 300, research 130, general 90), at 1 and 2 parallel requests.

### run.py and sizes.py

`python3 -m datagen.run --size smoke|night [--data-dir D] [--stages seeds,tasks,build,report] [--host H]
[--chimera BIN] [--limit N] [--keep-plan-failed]`. Exit codes: 0 done, 2 Ollama or a model or Blender missing,
3 stopped (STOP, or an early stop), 130 Ctrl-C. Night has an early stop: after 25 seeds, under 30% of tried steps
kept writes STOPPED.md.

Smoke (20 seeds): new Blender 6, new Python 3, new mixed 1, helper blender 2, coding 3, research_draft 2, planning
1, small_task 2; `failed_dep` 0.25, `mixed_pool` 0.25, `round2` 0.2 (higher than night, so every path runs).
Night: every kept seed, `failed_dep` 0.1, `mixed_pool` 0.1, `round2` 0.1.

`worker-model/run_datagen.sh`: builds a fresh binary into `data/gen/bin/` (removing the old one first), runs the
datagen tests, checks Ollama and the models, then runs the size under `caffeinate -i`, teeing to `data/gen/<size>.log`.

## After the review (Nov 3)

A review of the code above found these; the fixes changed the spec. Where a section above says otherwise, this list
wins.

- **No first-turn example from a repair (D3).** A step kept from a repair gives only its repair example (the repair
  request plus the repair), when it has one. The repair's reply answers "Your piece crashed ...", so paired with the
  first request it would teach the worker to talk about crashes it was never shown. The repaired piece still feeds
  the later steps, the join and the plan check.
- **Variants are judged (G11).** `pick` always runs the judge, so a Blender variant gets the scene judge on what its
  alone run built, like the step.
- **Unconfirmed tests (G1).** Tests that fail on the stub and on every first-round candidate (or that had no ready
  candidate to try) are `unconfirmed`, not invalid: what failed them may be the candidates. Every later candidate,
  repair and second-sampler sample is gated with them, and the first that passes confirms them (`valid`,
  `confirmed_by`). Only if nothing ever passes are the candidates whose one reason was `tests_failed` gated again
  without them, and one is kept (`kept_untested`). Every code step records `tests_status`: `valid`, `unconfirmed` or
  `none:<why>` (`none:variant` for a variant). The build drops `unconfirmed` examples unless `--keep-untested`, and
  the report counts kept code steps by status. A repair only starts from a crash Chimera's own check could show (a
  compile, the import run, `--check-result`), never from a failed teacher test. Tests are also invalid when no assert
  is reachable from module level (`parse_tests`) or when they pass on a hollow copy of the passing candidate, whose
  functions and methods return None (`passes_on_hollow`). Without tests the import run also fails on a timeout and
  on a missing module of the project's own.
- **Repairs carry the crashed Blender's sheet; files repairs aren't examples (D1).** `piece_check(..., prefer=)` takes
  the crash from the Blender whose sheet the request carries first, then the other. A repair request carries the
  sheet of the Blender named in its crash (`runner`), as Chimera's would, since Chimera prints the sheet and runs the
  check with the same Blender. If that version's sheet isn't here, the repair still runs but gives no example
  (`sendable` false). Files-mode repairs can keep a piece but never give an example: Chimera can't send them. Code
  crashes name the real interpreter, "Python 3.x.y", as Chimera's check states it.
- **The early stop is checked once per data folder (A7).** The first time `early_stop["after"]` seeds are done it
  either stops the run, or it passed (or `--no-early-stop` carries on past it) and `early_stop.json` says so; later
  starts don't check it again. A failed check writes nothing, so the next start stops again until `--no-early-stop`.
- **Chimera's fingerprint (A4).** Each start that runs the tasks or build stage hashes what the binary sends for
  fixed inputs (`run.fingerprint`: every step's worker request of a fixed Blender plan and a fixed code plan, the
  last step's repair and round-2 requests, the planner's round-1 and round-2 requests, the reviewer's request) and
  the names sheets, printed again at every start. RUN.json and every task record carry it. If `tasks.jsonl` has
  records and the last start that ran the tasks stage had another fingerprint (or none), the start exits 2 unless
  `--new-binary-ok`, which makes the seeds with an old fingerprint again. The build drops examples of records with
  another or no fingerprint (`old_fingerprint`). A build-only start takes the fingerprint too, so it needs the
  binary and both Blenders.
- **Teacher notes never reach a target (D5).** `hints.echoed_note(text, extra)` finds an 8-word run (in
  `tools/check_overlap`'s words) of HEAD, FORMAT_NOTE, BLENDER_NOTE, the facts header or "Earlier tries of this step
  failed on", or of `extra`. Precheck drops a candidate that repeats one (`teacher_note`, stage harmony), with the
  failure lines only the teacher was shown (`hints.teacher_lines`: lint messages and crash errors) as `extra`; the
  build drops such an example again. `tools/check_overlap.MARKS` gains "Notes for you, the teacher" and "(Chimera
  doesn't send these)", so the last check flags them too.
- **Lending preflight.** `run_datagen.sh` first asks this Mac's Chimera (`GET /api/state` on 7470-7474, or
  `CHIMERA_UI_PORTS`) for `lending.state` and stops (exit 1) unless it is `disconnected`, or nothing answers;
  `FORCE=1` warns and goes on. During the run, `llm.py` asks Ollama's `/api/ps` at most once a minute and logs a
  loaded model the run never called to `gate.jsonl` (`"event": "foreign"`); the report names them, since their
  loads inflate the model time and the projection.

Also changed:
- Plans are checked against the eval (D2): the head (title and summary), each step's title and instructions, and the
  whole plan at 0.5 of `Env.eval_index`, and the eval titles on the head. A hit is no plan (`reason: "eval_plan"`).
  The build's eval check reads every message, the system prompt too, so a hit drops one example instead of failing
  the whole build at the last check. The helper's accepted gpt-oss plans are read from `target` (D4).
- Blender gate: a stand-in fails when its printed key is one a present step provides, even with another dependency
  missing (G5); an earlier kept piece's provided name gone after the joined run fails `removes_earlier`, with
  `removed` listing those steps (G6); joined runs save Chimera's output paths under `wm_out/` in the run folder
  (G7); the direct run is under the watchdog (G9) and prints a start line first, and a run without it is a tool
  problem, not a cached verdict (G10). `RUN_FORMAT` is in the run key and was bumped.
- Code gate: an unresolved import is excused per seam, only when it names a module a dropped dependency was to
  write and no present file is a near miss of it (G3, G4); a NameError for a name a dropped step was to give is
  `unsure_dropped` in the plan check. A run with no traceback and a failing exit (the sandbox can't start the
  interpreter, say) is an error, not cached (G10), and `run.py` checks first that python3 starts in the sandbox.
- `run.py` returns 4 after the build and report when seeds ended in an error (A6), and `run_datagen.sh` exits 4
  too. A seed that ends in the same error as on the last start doesn't count toward the errors in a row (A1).
- Seeds: Ctrl-C with parallel seed calls starts no waiting call (A2); the stage stops only when under half of its
  calls answered, else it notes the failed ones and goes on (A3). Stored lines are split on `\n` only (A5).
- New drop reasons in the build, in order: `old_fingerprint`, `too_long`, `eval_overlap`, `teacher_note`,
  `tests_unconfirmed`, `duplicate`, `repair_cap`. New candidate and step reasons: `teacher_note`, `removes_earlier`,
  `import_timeout`.
- After the re-check: tests that a later candidate confirms are checked on its hollow copy first
  (`tests_check`, kept as `tests["confirm"]`), so tests that only name a symbol never become valid that way; a
  repair that quotes the error its own request shows isn't a teacher note when another try had that error too
  (`teacher_lines`); a repair example's `names` is the sheet its request carries; a build-only start refuses
  records of other requests unless `--new-binary-ok`; and the fingerprint covers every mode, the lone opening and
  a failed dependency (`FP_PLANS` has five plans).
- After the first smoke seed (Nov 3): gpt-oss lost every section of a five-step memo (and the next plan's first two)
  to the prose gate, so a section's teacher copy now gives the heading line to start with (`section_heading`: the
  heading its instructions give outright, else the title without its instruction verb and bracketed notes),
  a length band inside the check's (`note_band`: about n is 0.85n to 1.1n), the framing rule when it applies, and
  on its second try what the first was dropped for (`_section_failures`). `heading_not_title` no longer fails a
  heading that is the bare title (articles aside) or the given heading (`heading_fits`): 46% of the 712 section titles
  in gpt-oss's stored plans start with a verb ("Write ...", "Research ..."), and a target printing "## Write ...
  (≈600 words)" teaches a heading nobody wants. Chimera's validator only warns on it either way.
  The second try of that seed showed three more things, also changed: told "Write 510 to 660 words" gpt-oss wrote
  862, then 782 (stored replies: 1.16 to 1.32 times the target), so the note's band is now 0.75 to 0.9 times the
  target and a too-long try is told to cut to about the band's middle; sections get a third try (`ROUNDS`), and a
  try the prose judge turned down passes its problems on (failures are collected after the judge); the judge was
  given the whole piece and marked every section down for "an extra handoff code block", so it now sees the
  handoff on its own, labelled as what the format requires; and "In summary" closing a section's last paragraph
  ("In summary, the licensing economics present a near-parity scenario") counts as an outro only beside words for
  the whole document.
  A review of that code found more, also changed (the rules are in `prose_gate.py`'s docstring). Word targets read
  gpt-oss's U+2011 hyphen and "≈"; a number for the whole section (a total of its length, "a 600-word section", "a
  2,000-word decision memo", a title's "(≈N words total)") outranks a part's, a limit for items ("a headline (max
  10 words)", "(≤80 words each)", "For each, ...", a part in one item of a list: "- Executive Brief (≈250 words)")
  is set aside unless a sentence asks for that one item ("Write a blurb (max 120 words)"), so is an N-word document
  another step wrote ("the 2,000-word report from s1"), and two different counts with none for the whole set no
  target: a wrong band is worse than none. The heading the instructions give outright (`given_heading`: 'section
  titled "X"', 'under the heading "X"', a backticked `## X`; not a part's "section titled" in a later item of a
  whole document) is the one told, and the bare title then no longer fits unless the two share no word; when they
  speak of a heading it can't read, the teacher is told to use theirs, else the bare title. `bare_title` keeps the
  title when unsure ("Research and outline content", "Research Scientist – AI"), not for a plain verb before a
  Title Case name ("Research Windows Developer Laptop"). A heading Go passes still has to fit or be a whole phrase
  of the instructions ("ent the break" isn't). A step that asks for its own introduction or conclusion, or whose
  title names the whole deliverable, isn't checked for framing, and "other steps do that" is said only when another
  section is one. A dropped section's lines no longer quote its heading and give the echo check no extra (they
  quote the model and the judge, not us), but their fixed wording and the judge's lines about the format are among
  `echoed_note`'s own notes, and a grader's problem that only parrots the judge's prompt isn't passed on; the prose
  judge is told the ## heading is required (`HEADING_LINE`); a try only qwen3.8 turned down is told qwen3.8's
  problems. Against the code before this second round, on the 712 section steps of the stored plans: 10 gain a
  target (the 7 blurbs' own "(max 120 words)", a memo's ≈2,400, a press release, an analysis), 6 lose one that was
  a part's (four emails' body copy, one file of a media kit, a blog's introductory paragraph), one memo's band goes
  from a part's ≈250 to its 2,000; 33 told headings change (mostly a plain verb now stripped), and the 26 steps with an
  unread cue are told a heading to fall back on.

## After the smoke (Nov 4)

The 20-seed smoke run (`results/DATAGEN-SMOKE.md`) kept 63 examples at about 280 s of model time each, and a strict
read found 30% of them bad. Its verified causes, all in data generation but one (item 6, the `uses_unmatched` seam in
Go, left for a separate decision; decided Nov 5 and fixed in the contract, contract question 4 at the end of "After
the third smoke"), were fixed in six parts. Where a section above says otherwise, this list wins.

- **A reply's form made plain (item 1, and the stand-in in item 5; `normalise.py`, new).** gpt-oss wrote 160 of its 163
  File lines as `**File: path**`, which the validator refuses, so 77-81 of its 86 files pieces failed on form. Before
  any other check, precheck rewrites characters only: `file_lines` makes the line the validator reads before each
  block the exact `File: x` or `File: x (part)` (python-script and files), and `marker_dashes` gives a stand-in
  marker written with U+2010-2012 or U+2212 an ASCII hyphen (Blender). The candidate's content is the plain text,
  `normalised` counts the lines, and the raw reply stays in the call cache. On the smoke's 151 files candidates the
  validator then passes 113 instead of 32. A repair's request carries the plain piece, as the target does.
- **The next try is told why (item 1).** Every gate's result has `tell`: plain lines, teacher-only, empty on a pass
  (the seam's own message and what to do, a stub and whose file it is, the measured size or direction, a claimed
  source, ...). `_failures` passes, for Blender and code, the validator's messages for what failed (`_validator_lines`),
  lint errors, the crash, then the tell lines (not one that repeats the crash's error); for a section its own lines,
  then the tell lines. `hints_for` lists them under FAILED_ON in every mode; files steps get FILES_NOTE, and
  `teacher_lines` gives the echo check extra lines in every mode but a section's.
- **The teacher's tests (item 2).** 13 of the 17 unconfirmed code steps had wrong tests. TESTS_SYSTEM now says: test
  the step, not the task; an example isn't exact text; a command line is tested in-process; data only in a layout
  given; non-Python files only for existence, JSON and given values; never guess a name. In files mode the test
  prelude star-imports the candidate's own quiet modules and binds `step_modules` (the stub gets none).
  `parse_tests` refuses tests that start a process or guess names (`parse_tests_why`: "subprocess", "name_guess"),
  and the writer is asked once more in the same conversation (`judges.tests_retry_messages`, `tests["refused"]`); a
  reply that gives no tests leaves its reason as the why. Tests are written at the first batch with a candidate past
  precheck, and not while no candidate writes a .py file (`none:no_python`). Tests no candidate ever passes get one
  rewrite (`judges.tests_rewrite_messages`: each candidate's failing assert line, the error's last line and its
  provides line, never its code; candidates with the same failure share a line), which counts only if it passes
  `tests_check` on those candidates; then they are gated again (`before_rewrite`). No rewrite when
  `code_gate.tests_fault` already says "third_party". A piece kept untested gets `none:tests_unreachable` (a sandbox
  refusal of a process the tests start, or a module only the tests import that no step before names) or
  `none:third_party` (a package outside the standard library the candidates import), else stays `unconfirmed`. The
  build drops `unconfirmed` and `none:third_party` unless `--keep-untested`.
- **The scene judge's listing, and what is measured (item 3).** 7 of its 8 Blender drops were false. The factory
  engine and world are labelled as the factory's, and a measuring epilogue (data generation only; `RUN_FORMAT` 3)
  adds sizes, locations, modifiers, animation, lights' power and direction, cameras, node groups and actions; the
  listing is cut to 12,000 characters by shortening its longest list ("(and N more not shown)"). SCENE_SYSTEM says
  what the listing can't show and that sizes are for telling objects apart. What the step itself gives is checked
  after the alone run: `size_mismatch` (a size triple, or named sides from a values step, that nothing measures
  within 10%), `aim_mismatch` (a light or camera the step says points down that doesn't) and `output_not_asked` (a
  `SETTINGS_sN["output"]` path in a step that never asks to save or render). They fail the piece with tell lines but
  start no repair (Chimera repairs only crashes), at task's stage "alone". 8 of the 29 kept Blender examples fail
  them now; no false alarm was found on size or direction.
- **Prose (item 4).** `prose_gate` fails `claims_source` (tests, measurements or sources presented as fact),
  `step_id_leak` (a plan step's id in the text) and `csv_fields` (a CSV row with another field count than its
  header), each with a tell line quoting the model; on 122 stored texts all 20 firings were real. PROSE_SYSTEM asks
  about claims a section couldn't know and items that disagree, and an invented fact is never "a small problem". A
  section written with a dependency missing always gets qwen3.8's second opinion and is kept only if both keep it or
  gpt-oss gave it 5 (`judge["rule"]` "missing_dep"). Every judge and the tests writer see the goal under
  GOAL_HEAD, which says the worker never saw it.
- **Smaller fixes (item 5).** Stub files for another step's file fail (`stub_for_other_step`), and a (part) block of
  structured data (JSON, TOML, YAML, ...) fails `seam:part_not_mergeable`. The lint no longer flags Cycles' add-on
  preferences. No note names a Blender version (`[newer only]`, `hints.unversioned`, which the Blender gate's tell
  lines use too), and a reply naming one its request doesn't is `teacher_note` (`echoed` "version_leak", precheck
  and build). The build caps examples written with a dependency that failed in the run itself at 10% of their mode
  (`failed_dep_share`) and puts one group of every mode with two or more in valid.
- **Time.** The second sampler's draws send `num_predict` 8192 (`SECOND_OPTIONS`; one smoke reply thought 16,384
  tokens and wrote nothing). The report costs a kind with no examples from its own tries (Laplace's rule), counts a
  call once per seed, tells a model a restart left loaded from Chimera lending, and counts what these changes did
  (`after_smoke`: plain replies, version leaks, tests refusals and rewrites, missing-dependency judgements).
- **Not changed.** Go's `uses_unmatched` misreading "X from sN" (item 6; fixed Nov 5 in the contract, contract
  question 4), and its File-line regex reading `File: __init__.py` as `init__.py` (app/ is frozen here); thinking
  off for the second sampler (not measured); a test run that ends in SystemExit(1) with no traceback still counts as
  a run error (G10); the eval runner's own stand-in
  check still reads only an ASCII hyphen. Nothing here has met a real model yet: a smaller second smoke run is next,
  in a new data folder (`--data-dir`, `--limit N` for fewer seeds): Chimera's fingerprint didn't change, so the
  smoke's own folder would skip its 20 finished seeds and only build them again.
- **Checked (Nov 3 night, the Studio, offline, with a copy of the smoke's binary and both Blenders).** 435 datagen
  tests pass (433 before), and 743 for the whole folder. The smoke's 63 built requests are still byte for byte what
  the binary prints for their recorded inputs, and a build of the smoke's records with this code (49 examples: 4
  teacher notes, 17 unconfirmed tests, 10 over the failed-dependency share dropped; valid holds every mode) gives 49
  of 49. New record keys: candidate `normalised`, `before_rewrite`, `echoed` "version_leak"; tests `refused`,
  `rewrite`, `errors`, `run_errors`, `fault`; judge `rule`; gates' `tell`, Blender's `measured`, code's `stubs`, prose's
  `claims`, `step_ids`, `csv`.

## After the re-check (Nov 4)

Independent checkers replayed the smoke offline against the fixes above and found 21 defects (in the code gate, the
Blender gate, prose and the records' integrity). All but one (prose-4, below) were fixed in four parts to one shared
interface, then checked together. A second replay found 18 more (and 2 of the first still open), fixed the same way
(the third check, Nov 4), a third look at the prose gate 3 more, fixed in `prose_gate.py` (the fourth, Nov 4), and
the fourth's two checkers (recall and precision) 9 more there, mended by a second fixer (the mend, Nov 4); the
bullets below say how things are after them. Where a section above says otherwise, this list wins.

- **The pipeline's format.** Every task record carries `format` (`task.DATAGEN_FORMAT`, 2); the first smoke's
  records carry none and count as 1 (`task.record_format`). The tasks stage makes a seed of another format again,
  as for a changed fingerprint, and the build drops its examples before any other check (`old_format`); a start that
  runs the build alone on such records exits 2 unless `--new-binary-ok`. `run_datagen.sh` logs into the data folder
  in use (`<data>/run.log`, no longer `data/gen/<size>.log`) and exits 1 instead of running in `data/gen/smoke/`
  without a `--data-dir` once a smoke there has finished (REPORT.md written, every seed of seeds.jsonl done or
  no_plan). `datagen.run` refuses that start too (exit 2, before any check, writing nothing) while every finished
  record there is of another format (`run.finished_smoke`), unless `--new-binary-ok`; such a folder can't be rebuilt.
- **What counts as the notes'.** `hints.echoed_note(text, extra, request)`: a run of an extra line that Chimera's
  request holds too is Chimera's words, and a run with 4 or more words that start with a digit is a size, so neither
  counts; nor does a run that the failed candidate a line describes holds itself (`hints.Tell`, paired by
  `task._failures` for tell lines and validator messages: the five handoff names a tell line quotes back are the
  model's); precheck passes the request (a repair's own). `hints.notes_leak` finds the notes' words for the Blenders
  and the checks ("[newer only]", "the older Blender", "both Blenders", "either Blender", "two Blender versions",
  "sandbox", "sandboxed") in a reply whose request doesn't say them (`echoed` "notes_leak"); BLENDER_NOTE itself no
  longer says "sandboxed" or "two Blender versions" (the old wording is in RETIRED). notes_leak and `version_leak`
  run only for Blender steps, in precheck and in the build ("Django==5.0.1" is no leak). A size tell line names the
  thing and where its size comes from ("no object measures 2.2 × 0.9 × 0.8 m for the sofa (its size from s1); the
  nearest is ..."), never the step's phrase.
- **Tests.** Every reply the tests reader refuses (`task.REFUSED`: name_guess, subprocess, tests_syntax,
  no_asserts) gets its one retry, told why (`judges.TESTS_REFUSED` words all four); a step whose tests are still
  refused is `none:tests_refused`, which the build drops unless `--keep-untested`. What the retry gave is
  `t["retry"]` (`gave`: tests, refused, empty, none or runaway; `callable`: `task.names_callable` of the step's
  words): an empty `{"tests": ""}`, as TESTS_SYSTEM asks, on a step that names nothing to call is no refusal
  (`none:no_tests`, kept), and only a retry refused again joins `t["refused"]` (without a key or time of its own). A
  piece kept with no tests that ran (none written, refused, or not counting; variants too) is asked
  `code_gate.import_fault` on its kept gate (`Round.settle_tests`, again when the plan check swaps an alternate in):
  "third_party", kept as `step["import_fault"]`, gives `none:third_party` (dropped) when its import run ended on a
  ModuleNotFoundError for a module outside the standard library that the piece imports, that no project piece writes
  (`written`: `Round.given`, the round's earlier kept pieces and those the request was built from, a variant's
  inputs), that no step names as a project file (a/b.py, b.py, a/, a dotted name) and that no dropped earlier code
  step names at all (`dropped`: `Round.dropped_code`, the earlier code steps the request lacked, a failed_dep's
  left-out one too); the import run records `run["missing"]` for it. Only a dropped step's bare or backticked words
  count, since it may have been the one to write the module (a kept writing step's "`openpyxl` can read it later"
  no longer keeps such a piece); `tests_fault` takes the same `dropped`; "python-docx" still names no docx module.
  `code_gate.no_python(texts, mode, words, python_project)` is False when the step's title and instructions name
  Python (`names_python`: a .py file, Python's own syntax, Python itself) or the round is a Python project
  (`Round.python_project`: an earlier kept piece or a dependency piece is Python; 11 of the smoke's 22 such steps
  never say Python), so a Python step whose tries leave their .py files out keeps its tests. A kept code example on
  which nothing ran (`step["nothing_ran"]`, `task.ran_nothing`: its kept gate has no `tests` and no `run`, so it was
  only compiled and parse-checked; every `none:no_python` one) is marked `unverified` in its meta and counted in
  STATS.md. `none:no_tests` stays kept.
  The tests writer reads the goal under its own head, `judges.TESTS_GOAL_HEAD` ("test against its step").
- **The code gate.** In files mode each of the piece's own non-Python files is parsed as merged (`parse_file`,
  reason `parse:<ext>` at stage compile with a tell line, every result in `gate["parse"]`): JSON and .ipynb
  (json.loads; the files their tools read with comments, tsconfig and the like, with those taken out), TOML, YAML
  (only if PyYAML imports; composed, never constructed, so application tags such as `!Ref` or `!include`, values
  PyYAML can't construct and an anchor set twice pass, while broken structure, tab indents and undefined aliases
  fail) and JavaScript (`node --check` on a copy in a sandboxed run folder, `pysandbox.run_tool`,
  10 s, cached under `key_of("node-check", ...)`; a .js file with import or export as .mjs). A template, JSX or Flow
  is skipped, not failed, and a part added to a file that didn't parse before isn't blamed. `normalise` writes
  "(part)" only where Go read a part: `**File: x (part)**` is Go's whole file x, so it is left as it is and fails
  on form. A file the step's own words name is another step's stub only on strong evidence (it names another
  step's id, or a later step's title names the path); a file over three lines counts only when it holds nothing but
  a note in its first three lines saying another step provides it (`_longer_placeholder`): a page (.md, .rst, a
  README) that says placeholder or stub, or a .py file of stubs only (`_stub_python`), so a real file with a TODO
  naming a later step passes. Every file the gate runs starts with HARNESS, which prints a start line and, at exit,
  an end line (both stripped; `run["harness"]`): a nonzero exit with the end line and no traceback is a SystemExit
  and the script's verdict (the tests: tests_failed, "SystemExit: exit N with no traceback"; the import run:
  `import_exit`; an entry point: unsure), while a run with no end line (os._exit, a signal) stays an uncached error.
  Every code-gate run key changed with it. What ran on a piece is in its gate (`piece_check`'s docstring):
  `gate["tests"]` when the teacher's tests ran, `gate["run"]` when the import run did (python-script: whenever
  valid tests didn't pass; files: only for a .py module that only defines things).
- **The Blender gate.** A size from a values step is checked on the joined run's measurements, only when that step
  is in the join (`measured["joined_sizes"]`, the failure's `stage` "joined"), never for a variant; the values
  piece's own SETTINGS literal (`settings_sides`) decides what the dependent is held to (`_held`: all three sides
  agreeing with the words, the piece's numbers, `piece_sides`; any side that differs skips the size, "unmeasured"
  "other_values"), and a size whose thing the measure cut is unmeasured ("cut"), not failed (`size_states`; fits
  None). An angle given with "down" sets how far down (`aim_z`: z at most -sin(N) + 0.1; every limit is now "at
  most"); "N degrees from vertical / straight down" is 90 - N below level, and a clause with any other angle,
  unit or rotation it can't read is skipped; "straight down the corridor" asks nothing. A size is asked unless
  another step makes the thing (`_makes`, which stops at relative and aiming words; an earlier step's title or its
  own size for the thing count too, a later one's only through its words), and not after "from sN", "built in sN"
  or a place word ("2 m above the kitchen island (...)", `_referred`). The listing gives `base_size` where
  modifiers change an object's size, "(N more not listed)" on a field that was cut, and the factory engine as
  ENGINE_UNCHANGED ("the listing can't tell whether the piece set it") or, when the piece's code assigns an engine
  (`sets_engine`), ENGINE_SET; SCENE_SYSTEM explains all three and that a stand-in's modifier may leave 0 x 0 x 0.
  `RUN_FORMAT` is unchanged, so cached Blender runs stay valid.
- **Prose.** `prose_gate.section_check(..., dep_texts, missing_deps, prev_result)` gets the dependencies' pieces as
  the judge is shown them, the ids of those that failed and, in round 2 on, the previous result as the step's request
  gives it (`Round.prev_part`: its own part by Go's findPart, else the result cut to 6,000 bytes; "" in round 1),
  all given material (`given_material`): a measurement, result or source it holds is excused (`claims_given`), and a
  claim that tests or a benchmark were run always counts. Material is read clause by clause: a clause that says the
  data wasn't there ("No survey results were available", "couldn't find", "unknown") gives none of it, nor a heading
  its own piece denies, and a sentence with a mark ("(unverified)", "Assumed:") gives no figures and no words to a
  result or a measurement, so a dependency's (or the previous round's) marked guess restated without its mark fires
  (the smoke's s1 marked its invented 8K timings; restated by s3 they were excused). Figures are (digits, unit) pairs,
  and label numbers are no data (list numbers, "week 1", versions, model numbers, resolutions, file names, word
  counts, the plan's and steps' titles' figures). A figure in the step's own words counts with the same unit or sign
  (62%, $699, 47.5 C, 12 May; a bare number only if it can't be a count), with no 4-figure threshold, and a bare count
  they give with the word it counts ("We surveyed 40 plot holders", "4 of the 9 laptops") is theirs, as a label is. A
  claim with figures needs the blocks that hold its words to give half of them (`_tied`: an honest s1's "8 GB of VRAM"
  no longer excuses "Benchmarks show Octane needs 8 GB and renders 40% faster"), and a pointing clause's words count
  only when the pieces give every figure (`_pointed`). A claim with no figure is excused only by material that says
  its data, not by its word alone (an honest research step that found nothing still names the benchmark, and its
  heading is its step's title): by a piece's clause that holds the word, neither denies it nor asks for it (a modal,
  "recommended", "next step", "planned", unless a result verb and a figure stand beside it: "64% ... said they would
  prefer"; "Benchmarks: none found", "n/a" and "Missing data: ..." deny it) and, for a word that is data, carries a
  figure, a result verb, a comparison or a past verb after the word, in a sentence that with the one after it on its
  line holds half of what the claim says (`_content` reads the claim's own clause, words inside the claim too, and
  leaves out adverbs in -ly and prepositions: "Both vendors' benchmarks show only GPU speed scores" or "Running a
  benchmark takes about 2 days" no longer give "Benchmarks show Octane produces cleaner reflections", nor a long
  previous result that names every topic), or by a label of the piece's body over rows with figures ("Survey
  results:" over "- Tuesday evening: 64%"; not "Survey details:"), else by a piece (its heading too) whose text holds
  all the sentence says; by the own words only when no dependency is missing and a clause holds the word with a
  figure after a colon, in rows under a results label ("Readings (taken hourly on 3 June):" over "09:00 41.2 C") or
  after the word in its clause ("In the survey, 62% want hybrid working"), where no size, bound, time, target or
  question stands before it (not "the survey of 120 members", "a $5,000 budget", "(n = 340)", "The target benchmark
  time is 4 minutes", "Check whether the benchmark is under 5 minutes"), or they make the claim themselves (not in a
  question: "Find out what the survey found"); a source's name they give is enough, a name that is data, or one they
  give only as a place to get data ("using data from Statista and CNET"), only where they say what it found
  ("Summarise the survey, which found ...", "the audit's finding that ..."), and one given only as someone to act
  ("Ask Dan to sign it") not at all. "According to the data" cites the given data itself (with a figure, the figures
  given; without one, a sentence of data that holds half the claim). A title names a topic, not data, and an
  own-words clause that points at another step ("Based on the benchmark data from s1", "s1's survey", "the previous
  step") gives nothing: that step's piece has to. More invented shapes count ("based on the latest vendor
  catalogues", "observed in the benchmark", "research shows", "studies have shown", "studies consistently show",
  "tests show", "testing revealed", "the benchmark found", "a blind test found", "a survey of 2,000 campers found",
  "recent research by Stanford suggests", "data from the Outdoor Industry Association shows", "industry figures put",
  "a 2023 study found", "in our side-by-side tests", "in our assumed tests", "in the assumed benchmark", "when tested
  on", "we benchmarked", "we tested both", "we surveyed" and "we interviewed" with or without a number, "the
  following evaluation pits X against Y using a standardized test scene", a survey's respondents ("62% of
  respondents", "respondents cited", "62% of artists surveyed", "Survey - n=1,200"), an image metric's or a render
  time's figure ("an SSIM of 0.98", "| Total render time (8 K) | 12 min 02 s |"; not a target, a limit, a modal or
  "Expect ..."), a publisher in brackets after a figure ("(Grand View Research)", "(Nielsen 2023)", "(per Nielsen)",
  "(Puget Systems, 2024)", "(Smith et al., 2021)"; not "(Per Plot)", "(N=250)" or an event's "(Chelsea, 2024)"), a
  publisher that reports ("Statista reports", "Gartner predicts"), a study's own title with its year ("Bankrate Survey
  2025"), a vendor's site or price page with a price ("Otoy's website lists ...", "as listed on Otoy's website",
  "Maxon's current list price"), "per a 2024 Puget Systems benchmark", a "Source:" line also in a table cell, and a
  citation outside the sentences: a Sources or References list's items, a footnote's line and a table's Source column,
  each only where it reads as a citation (a year, a link, a publisher, a study's noun) and isn't a system a plan's
  data comes from ("ERP (SAP)"; "Further reading" and "| Source | Target |" aren't citations); analysts, market
  researchers, economists and observers, and experts who estimate, report, find, say or warn, only where what they
  say came out follows (a that-clause, a market figure, a forecast, a trend: not "experts demonstrate how to shape a
  boule", "analysts estimate each ticket in story points"); "a panel of", the blind, side-by-side and head-to-head
  tests, "In a 2024 poll of" and experts' advice only where a result came out: a past verb (also after a plural
  noun for people: "artists preferred renders from Octane"), a score, a comparison of what the sentence names ("than
  Redshift", "ahead of Redshift", "outperforms", "most artists prefer", a quality's comparative; not "more than 12
  cheeses", "lighter than 400 g", "behind Ludlow Castle", "which soil drains better", "for better yields", "the loaf
  most visitors prefer", "entries that score higher") or a result in the present ("Octane clearly wins on glass",
  "picks Octane every time", "is the clear favourite"; not "each visitor picks Hobbs House"), with no instruction
  after the shape's comma ("In the test render, make the Rim light brighter than the Key"), where an -ed word after
  a preposition, "and" or a wh-word, before the plain noun it describes, in a clause about someone ("judges, who
  between them founded ...") or before a preposition after the object of one ("than the maximum printed on the
  sidewall", "the distance the car travelled on each surface") isn't a past verb, and experts' advice counts only
  with a past verb or a rating, not a comparison or a threshold ("quieter than at weekends", "at 0.5% wear"); "per"
  only where it cites, at a sentence's start or after a comma, never in how-to prose; "based on" only before a data
  noun; "according to" an audit or a comparison too, not "this comparison" or "the table above"), a mark clears only
  the claims of its own clause ("(unverified)", "(assumed ...)", "is an assumption"; a leading "Assumed:" the whole
  sentence; no longer a plain "assuming"; "Octane costs $699 (assumed), and benchmarks show ..." marks the price) and
  never a test or benchmark it says was run or a first-person measurement, survey, poll, interview or recording ("We
  surveyed 40 artists (unverified)"), and a denial ("No benchmarks were run") isn't a claim, but "It's no secret
  that ..." is no denial. CLAIMS_TELL says to leave the figure out and say the data wasn't available (list it under
  assumed), and a research step's tell, CLAIMS_TELL_RESEARCH, to omit any test, measurement or survey it says was
  done and mark unsure figures (unverified) (no record holds an older wording, so none is in RETIRED); a claim the
  material gives only marked gets CLAIMS_TELL_MARK (keep the mark), and one with no figure whose data the material
  has (a survey's rows under its heading, the person's pasted readings) CLAIMS_TELL_CITE (give that figure, or leave
  the result out), since "say the data wasn't available" would steer the next try to drop data it was given; each
  claim's line is in `claims_why`, and a section with claims of two kinds gets a line for each. The two new lines
  were never sent before, share no 8-word run with a stored reply, and are in TELL_NOTES. PROSE_SYSTEM names runs
  and measurements. "call it an assumed estimate" is gone. A section
  written with a dependency missing is kept only if qwen3.8 keeps it, whatever gpt-oss's score: a 5 no longer keeps
  it (`judge["rule"]` "missing_dep" as before).
- **The report.** `after_smoke` also counts notes_leak drops by mode and, over kept code steps, those still refused
  (`refused_untested`), those `import_fault` dropped (`third_party_import`), `none:no_tests` steps whose words name
  something to call (`no_tests_callable`, `task.names_callable`), the share with no Python (`no_python`) and those
  nothing ran on (`nothing_ran`, by mode); `tests_refused` counts only the whys of `task.REFUSED` (older records are
  read the same way), and what the retries gave is `tests_retries` (REPORT.md: "what those retries gave").
- **New record keys.** Task `format`; step `import_fault` and `nothing_ran`; tests `retry`; tests_status
  `none:tests_refused`; candidate `echoed` "notes_leak"; code gate `parse`, `run["missing"]`, `run["harness"]`,
  reasons `parse:<ext>` and `import_exit`; Blender `measured["joined_sizes"]`, size entries' `thing`, `vars`,
  `piece_sides` and `unmeasured` (fits None), aim entries' `angle`; prose `claims_given`; meta `unverified` and
  `format` (build.META_KEYS); STATS.md `unverified_by_mode`. `DATAGEN_FORMAT` stays 2: no real record was made at 2
  before the third check, and every key it added is read with a default.
- **Not changed.** prose-4: `csv_fields` can fire on a letter or verse whose comma-heavy lines follow each other,
  and `step_id_leak` on a lone lower-case step id; both are left for the second smoke to show. Go's seams (app/ is
  frozen here): `uses_unmatched` misreading "X from sN" (fixed Nov 5 in the contract, contract question 4), and
  `File: __init__.py` read as `init__.py`. Also left: a
  SystemExit(1) printed after a handled traceback reads as that traceback; tests that call os._exit are an error;
  TypeScript, .json5 and .jsonc aren't parsed, and a .js file with top-level await but no import or export passes
  node unread; the first code step of a project whose words never say Python and whose tries write no .py still
  asks for no tests (nothing earlier is Python); a claim with no figures fires when the step's instructions only ask
  for its data; the measuring epilogue's budget cut drops the last objects first (cameras), which needs a
  `RUN_FORMAT` bump to fix. Left on purpose by the third check, each erring toward skipping: a longer JS or YAML file
  with a placeholder note over real content isn't a stub; "Add chairs around the table (0.45 × 0.45 × 0.9 m each)"
  and a size whose thing can't be read but whose words name another step's thing aren't asked; a later step's
  "Make the island glossy" takes an earlier step's island size away; "aimed down at a 20 degree angle" isn't read;
  a values piece is never checked against its own words; a "per" citation mid-sentence with no comma no longer
  fires; a marked third-party run ("Puget's tests were run ... (unverified)") fires in research steps; a dotted
  number after an unknown capitalised word reads as a version; a round-2 request's critique isn't given material;
  lint findings and crashes aren't paired with their candidate (only tell lines and validator messages are). Left
  by the fourth and the mend: an event recap's "a panel of judges chose the 12 finalists", a recipe's "We found that
  3 folds ..." and "We tested 2 flours ...", and "based on the manufacturer's published specs" or "the public price
  list" still fire; "Market analysts suggest ... should stock more" counts, since analysts are a source with a trend
  word after them; a comparison that names nothing isn't caught ("In side-by-side trials the mulched bed stays
  cooler"); a claim with no figure that a piece gives only in other words, or only under its heading (the piece's
  step title over a survey's rows, a table or JSON), fires, now with CLAIMS_TELL_CITE; a marked piece still gives a
  source's name ("According to the yield analysis" over a marked "The yield analysis puts bed A ahead"), as the
  check's fix asked, while "Trials show bed A ahead" over it fires; a list item under Sources that reads as no
  citation ("- Club minutes") isn't checked; "N% faster" with no test word isn't a claim (a figure the section
  computed would fire), and invented measurements with no test, metric or source word ("Octane completed the frame
  roughly 25 % faster") pass, so a stored s3 that drops its quoted sentences still passes the gate (a section-level
  check of measured figures wasn't tried); "Render times are under 5 minutes" isn't read (a bound before the figure
  is taken for a limit); "We recorded 14 complaints" over the person's "We've had 14 complaints" fires.
  Nothing here has met a real model: how often notes_leak, tests_refused, the parse check, the joined sizes, the
  claim rules and the missing-dependency rule fire, and how often a writer obeys with `{"tests": ""}`, is for the
  second smoke, in a folder of its own.
- **Checked (Nov 4, the Studio, offline, with a fresh copy of the smoke's binary and both Blenders).** 497 datagen
  tests pass (494 after the four parts; the integrator added the retry for the last two refusals and a test of
  no_python by code_gate's own rule), and 805 for the whole folder, none skipped. The smoke's 63 built requests are
  still byte for byte what the binary prints for their recorded inputs. A build of the smoke's records drops all 80
  examples as `old_format`; with the format check bypassed it keeps the same 49 as on Nov 3 (49 of 49 requests the
  binary's), and with each kept code step's tests_status settled again by today's rules on what the records hold, 53
  (research_draft-0009-04 s4 and planning-0002-08 s6 drop as `third_party` instead of unconfirmed, and four steps
  are kept as `none:tests_unreachable`; 53 of 53 the binary's). That replay can't ask the tests writer again: 9 of
  the stored tests would be refused today (8 name_guess, 1 subprocess), and 4 of the kept steps among them could end
  `none:tests_refused` if their retries fail. Over the 525 distinct stored replies, today's checks flag 27
  version_leak (as before) and 6 more notes_leak, all Blender, none kept: notes_leak fires on 10 of 258 Blender
  replies, always for "sandbox", 4 of them version leaks too; on the 267 others neither check fires, and no
  echoed_note fires with or without the request subtracted.
- **Checked after the third check (Nov 4, the Studio, offline, a fresh copy of the smoke's binary, both
  Blenders).** 535 datagen tests pass (534 after the four parts; the integrator added the plan check's swap: a code
  alternate is settled again from its own gate, since import_fault and nothing_ran read the old piece's, so an
  alternate that ran clean after one whose import missed openpyxl was dropped as third_party), and 843 for the whole
  folder, none skipped. The smoke's 63 built requests are still byte for byte the binary's. Rebuilt from the smoke's
  records with the format check bypassed: the same 49 (stored tests_status) and, settled again through today's
  `Round.settle_tests`, the same 53 as after the re-check, row for row and split for split, every request the
  binary's; their meta now carries `format`. On those records only 4 kept steps have `nothing_ran` and all are
  unconfirmed (dropped), so no example turns unverified, and `dropped`/`written` change no reading; the offline
  replays of the four parts (which re-gate the stored replies) put the new rules' effects at: python_project asks
  for tests on a docs-only try in a Python project; an answered `{"tests": ""}` keeps small_task-0014-09 s1 (the
  only refused step whose words name nothing to call); 10 kept steps nothing ran on, all already none:no_python;
  the Blender regate of 82 stored candidates gives the same reasons and tell lines as before (16 output_not_asked,
  6 stand_in, 4 size_mismatch, 3 aim_mismatch, 54 ok); claims_source fires on the same 12 of 122 stored sections.
  Over the 525 distinct stored replies the echo and leak checks flag the same 27 version_leak and 6 notes_leak as
  after the re-check, and none of the new wordings (BLENDER_NOTE, CLAIMS_TELL_RESEARCH) holds an 8-word run of a
  stored reply. A tiny run on the tests' stand-in Ollama: every record format 2, 37 of 37 stored requests the
  binary's (the only tell lines in one are a repair's crash line, which Chimera's repair request shows itself), no
  8-word run of teacher text in a target its request doesn't hold, every meta line `format` 2, and records turned
  format 1 refused by a build-only start and made again by a tasks start with no new model call. A `--size smoke`
  start with no `--data-dir` on a copy of the first smoke's folder exits 2 for every stage set and leaves it
  byte-identical.

- **Checked after the fourth (prose) check (Nov 4, the Studio, offline, a fresh copy of the smoke's binary, both
  Blenders).** 544 datagen tests pass (78 of them prose, 9 new, each failing on the third check's code) and 852 for
  the whole folder, none skipped, run with `WM_SCRATCH` outside the home folder: under `data/scratch` the four node
  tests fail because node 24's realpath reads `/Users`, which the sandbox denies, so `node_check` there skips every
  .js file (code_gate and pysandbox are unchanged since the third check). The prose gate on stored text: of 6,463
  stored model sentences, the same 15 flag as before and no claim phrase changes; 0 of 808 goal and instruction
  sentences differ; claims_source fires on the same 12 of 122 stored sections, every reason, claim and given claim
  the same; the 22 section requests are byte for byte the binary's. Replaying the smoke's research_draft-0007-04
  candidates as if s1 had worked and only recommended a benchmark, the stored "the side-by-side benchmark indicates
  ..." now fires (it was excused). The checker's probes: all their invented figure-less claims after an honest s1
  fire (50 of 50 with ten honest pieces, 4 of 4 with the own words naming s1's data, the smoke plan's 6 of 7, the
  seventh "according to the render quality comparison" as before), as do the present-tense, forecast and marked
  first-person ones (9, 16 and 8 of them); the 13 ordinary sentences of r2-prose-3 and 10 of 10 -ed event and lesson
  sentences pass; the legit restatements are excused as before (17 of 20 by a dependency's piece, 14 of 20 by the own
  words).
- **Checked after the mend (Nov 4, the Studio, offline, a fresh copy of the smoke's binary, both Blenders).** 559
  datagen tests pass (93 of them prose, 15 new, each failing on the fourth check's code) and 867 for the whole folder,
  none skipped, with `WM_SCRATCH` outside the home folder. The prose gate on stored text, against the fourth check's
  code: of 34,066 stored model sentences (the smoke's calls, the eval runs' replies and the helper's review items) 42
  more flag and none less, every one an invented citation, survey, test or measurement (gpt-oss's market pieces'
  "(Grand View Research)", "(per Nielsen)", "Bankrate Survey 2025", "Respondents cited"; the render memo's "In our
  assumed tests", "in the assumed benchmark", "The following evaluation pits ...", its SSIM, dB and render-time
  rows); as whole texts 21 of 2,583 differ, phrases added only, and the Source columns and lists of data-pipeline
  plans ("ERP (SAP)") don't count; 0 of 5,226 goal, instruction and helper-seed sentences differ, and 0 of 808 in the
  smoke's own (as whole texts one request differs: its own reference list, which its words give a section). claims_source fires on 17 of 122 stored sections (12 before): the 5 new are the render memo's "Current
  workflow audit" and "Recommendation" sections with render times its seed never gave, two of them kept SFT targets of
  the first smoke (t15, t18); no stored section stops failing, no other reason and no given claim changes, and the
  22 section requests are byte for byte the binary's. The checkers' probes: the recall side's 148 of 148 invented
  shapes fire in both step kinds (2 before), 30 of 30 soft results (6), every excuse route they found closed (B1 to
  B4, the long previous result, targets and questions in the own words, "using data from Statista", "Ask Dan"), the
  smoke's stored s1 marked timings restated by s3 fire with the mark line, and 18 of the 2,664 sentences of
  gpt-oss's research_draft results flag (0); the precision side's genre, comparison, soft-shape and hedged fixtures
  are all right but one (product copy's "In side-by-side tests the Alba 2 is quieter", which its checker called a
  catch), and its given-data fixtures that still fire (a survey's rows, table or JSON under only the piece's
  heading, an own-words table under no label, a piece whose one mention of the survey is advice, a round-2 table
  under its heading: 23) all get CLAIMS_TELL_CITE, and "We recorded 14 complaints" (the person wrote "We've had")
  the plain line; its leak fixtures (18) still fire. Kept as before: the round-3
  probes' verdicts (50 of 50 honest-piece claims, the 13 ordinary sentences of r2-prose-3, 10 of 10 -ed sentences,
  17 of 20 and 14 of 20 restatements excused), but for "12 May", the energy audit and the render quality comparison,
  which now read right, and the fourth check's fixer's three marked-piece rows and probe2's two, which now fire with
  the mark line by the check's own fix. Stored s3 sections that drop the sentences their tell quotes still pass:
  what is left are invented figures with no test, metric or source word.

## After the second smoke (Nov 4)

The second smoke run (`results/DATAGEN-SMOKE.md`, "Second smoke run": 12 seeds into `data/gen/smoke2/`) kept 47
examples, and a blind audit graded 16 of them bad. Nine causes were found and prototyped offline, each re-run by a
skeptic, and a critic proposed an order; the user approved its steps 0-5 and small fixes, built in five parts to one
interface (K1-K15) and then put together. The Blender batch (hidden errors, geometry: step 6) and the teacher notes
(step 7) are not in it. Where a section above says otherwise, this list wins. Every number is offline, on both smoke
runs' records (no model call), graded by the audit (ids X01-X80, drops D01-D19).

- **Formats.** `task.DATAGEN_FORMAT` 3 (both smoke runs' records are now another format: made again by a tasks
  start, `old_format` in the build; `run.py` and `run_datagen.sh` suggest `--data-dir data/gen/smoke3`).
  `blender_gate.RUN_FORMAT` 4: the measuring records the scene's camera (`scene_camera`, after the listing's budget
  cut, so the judge's listing and its cache keys are unchanged), so every Blender run is made again once.
- **A failed dependency's output claimed (`dep_honesty.py`, new).** `check(messages, text)` reads which dependencies
  Chimera's own request (a repair's own, never the teacher's copy) says failed and the piece's handoff with the
  contract's parser: a uses item that names a failed step, holds its title or a code-like name no received piece
  holds is `dep_claimed:<sid>`, unless the item, its "sN:" group or a ;-group naming that step is marked (failed,
  missing, stand-in, assumed, ...); an assumed line of none while one failed is `dep_unlisted`. Of the 737 stored
  candidates and repairs (175 with a failed dependency, hand-labelled 95 claims and 65 honest) it flags 91, all
  claims, misses 4 (X70's "(assumed)" inside the item among them) and never fires without a failed dependency; of
  the audit it flags 13 of the 15 bad written with one, 3 of 4 weak, 0 of 16 ok. It runs as a stage after every
  mode's gate and before the judge (`task.Round.honest`, stage `gate:dep_honesty`, its tell lines to the next
  batch), and in the build on the stored request and target (`dep_claimed`), so old records are filtered too. The
  tell asks for the item step first and marked, "s2: rows (failed)", and assumed to start "s2 failed:": until Nov 5
  (contract question 4) Go's usesChunks read "lamp from s2 (failed)" after another step's item as that step's
  (`uses_unmatched`); since then that form reads right too. Through the binary every asked form passes the validator
  and the join with no new issue or seam.
- **Kept as a dependency, not an example (`task.SOFT_REASONS`).** `dep_claimed`, `dep_unlisted`, `output_missing`
  and `camera_not_active` leave a piece usable by later steps. When no try of a normal step passes but one failed
  only on them, the furthest such that the judge accepts (`SOFT_JUDGED` 2 asked, furthest first, then the fewest kinds
  of fault, then drawn order) is kept for the later
  steps and the join as a pass is, with `step["no_example"]` its reasons: no example (`task.examples`, the build's
  `no_example` drop, the report's "dependency only"), no alternates, no variants; a variant never soft-keeps. It is
  judged because its piece becomes the later steps' given material: unjudged, the replay brought back three sections
  the judge had rightly dropped for invented benchmarks and part numbers (D03, D05, D08). A Blender piece whose only
  faults are the soft ones still gets its joined check (`blender_gate.SOFT_MEASURED`), so a soft keep never enters
  later joins unchecked (the 9 stored step tries that fail only softly all join cleanly).
- **No output handed over, no camera made the scene's (`blender_gate.py`).** `output_missing`: the step's words ask
  to render or save a .blend ("(optional)", "optionally", "if desired" ask nothing) and `SETTINGS_sN["output"]` holds
  no path of that kind (the copy of Go's hasOutput matches the binary on all 290 joined tries); its tell names the
  step's own file ("//room.png") or a kind, never a copyable wrong name, in at most 240 characters. 39 of the 380
  stored Blender tries, 5 of those that passed (X43, X05, X58, X20 bad, and a repair now kept as a dependency); 0 of
  the graded ok. `camera_not_active`: the step adds a camera of its own and the scene's camera after the run is none
  or the factory one untouched, in every version that recorded it: 8 firings, all read and right (X47 weak; the
  first run's 7 were already judged out or not kept). The factory camera's copy the step asks for by name is no
  duplicate while it is the scene's camera (`factory_copies`): D15 passes, alone, joined and in its plan check; D12,
  which leaves the factory camera rendering, stays a duplicate.
- **Files in the wrong place (`layout.py`, new; code_gate stage `layout_import`).** In files mode the piece's own
  .py imports are read on the join (the pieces its request was built from, `project=`; nothing run) against where a
  real run looks: the file's folder and those above it, the standard library and the runs' interpreter's own paths
  left out, guarded imports and sys.path or packaging configs skipped. 5 of 224 stored files tries, all smoke2's
  n-python-0001-02 s6 (X80, X32 bad), 0 of the other 176 that join; their joined CLI dies on start, while the
  unflagged alternates run. `plan_check`'s backstop (`entry_layout`; only for a module no run of the entry could
  find, from its folder or one above, in a project with no path config) blames the step whose file holds the failing
  import of a module the project has in another folder.
- **Nothing checked the language (`lang_check.py`, new).** By the File: path's extension only, an unverified files
  example with a code file no parser here read and passed is dropped (`unchecked_code`): smoke2's three PowerShell
  pieces (X17, X74 bad, X54 weak), and the first run's config.lua and queries.sql, which look right (its cost);
  never a Python file. `parse_file` now also parses Go, shell, Ruby, Swift and XML with this Mac's own tools
  (`LocalParsers`, sandboxed, cached as `local-parse`); no stored file is in them. Every result is in the gate's
  `parse`, the one key the build reads.
- **Tests that never reached the code (`code_gate.tests_fault`, kept=).** Tests that failed only on a module no step
  in this step's dependency closure names, while the kept piece wrote its own file where its words say, are
  `none:tests_unreachable`, which the build now keeps marked unverified: smoke2's D17-D19 (2 weak, 1 ok by the drop
  check) and, settled again by today's rules, 4 of the first run's files steps (n-python-0001-02 s2-s4,
  n-python-0001-01 s5), whose records predate the earlier rounds' rules too. The rewrite's errors stay in `tests["rewrite_errors"]`.
- **Lazy third-party imports (`code_gate.import_fault`).** With no tests on the kept piece, an unguarded import
  inside a function of a module outside the standard library, the project and the runs' interpreter is
  `third_party` (dropped): X44 alone of the 107 Python tries that passed everything else.
- **Build filters on facts (`build.fact_drops`, in this order).** `dep_claimed`, `validator_warning` (Chimera's
  `handoff_long`, `uses_undeclared` or `provides_missing` on the kept item's stored verdict), `unchecked_code`, and
  for Blender `ctx_channel` (a top-level ctx key other than scene, collection and objects, written or read) and
  `dead_output_key` (an
  output-like `SETTINGS_sN` key other than "output", which Chimera never reads). No model time, no cascade. The last
  two rest on hydra:1.0's values-only first steps of three Blender seeds: check them on the next smoke.
  `FAILED_DEP_CAP` stays a ceiling, counted after `dep_claimed`.
- **The next try's notes.** `hints.failure_lines` keeps the newest FAILURES_KEEP lines (the later tries' are the new
  tell lines): over smoke2's 75 later batches 4 of 146 lines are left out instead of 13, over the first run's 174, 45
  of 347 instead of 75; a repair passes its own crash and lint last, so its crash stays listed (10 of 10), and the
  facts block names the newest failure's first. `echoed_note` knows every new tell wording (`dep_honesty`, `layout`,
  `blender_gate.TELL_FORMS`).
- **Dependencies shown whole (`judges.DEPS_BUDGET` 40,000).** The prose judge and the tests writer see all
  dependencies under one budget, cut as Chimera's pieceCap cuts (longest first), not 4,000 each: every stored call
  sees them whole, the 28 labelled rows that had been cut are the prompts judged whole (drops 15 to 12), and the
  largest prompt (53,288 characters, about 18,000 tokens) stays inside gpt-oss:120b's 32,768.
- **The report.** Model time counts only the calls the records use (smoke2: 330 calls and 9,314 s, not the seeded
  cache's 1,031 and 28,131 s; 701 left out), and `after_audit` counts the new gates' firings, the soft keeps, the
  tests_unreachable steps and the rewrites' errors; STATS.md has the facts filters' table. `run_datagen.sh` puts
  `WM_SCRATCH` in `$TMPDIR` (else /tmp), outside the home folder, by default.
- **The tests' fakes.** A canned piece's handoff is written as if every dependency delivered; asked with a failed one,
  qwen3.8 says so, gpt-oss once its notes carry dep_honesty's tell, and a title in `STUBBORN` never (so the tiny
  run's first gpt-oss batch fails the stage and the told one passes). The areas' stand-ins for each other's rules are
  gone.
- **Not changed.** The Blender batch (silent faults, geometry, X06 X07 X27 X39) and the teacher notes (PLACE_NOTE,
  FILES_NOTE, a failed-dependency note, an output note, a values-step note): steps 6 and 7. Go's usesChunks (fixed
  Nov 5 in the contract, contract question 4). Left:
  `dep_unlisted` fires on an honest "assumed: none" from a piece that needed nothing of the failed step; the 4 known
  dep_honesty misses; nested output-like SETTINGS keys; the listing still doesn't show the judge the scene camera; a
  rewrite with an 8,000-character goal and six different failures would need the 65,536 window (a reload). Whether
  the tell lines bring honest pieces back is for the third smoke.
- **New record keys.** Step `no_example`; candidate gate `dep_honesty`, stage `gate:dep_honesty`; code gate
  `layout`, `lazy_imports`, reasons `layout_import`, plan check `entry_layout` (entry `layout`), parse kinds Go,
  Shell, Ruby, Swift, XML; Blender `factory_copies`, `measured["output_missing"]`, `measured["camera"]`, the measure's
  `scene_camera`; tests `rewrite_errors`; build drops `no_example`, `dep_claimed`, `validator_warning`,
  `unchecked_code`, `ctx_channel`, `dead_output_key`, stats `facts`, `no_example`, `failed_dep_share`,
  `unverified_by_why`; report `after_audit`, the steps' "dependency only".
- **Checked at integration (Nov 4, the Studio, offline, a fresh copy of the smoke's binary, both Blenders; the
  repairs below change some of these numbers).** 659 datagen tests pass
  (the five parts' 656, and the integrator's three: a soft fault still joined, every run of a new tell wording
  refused, a render never handed over kept as a dependency in real Blender), and 967 for the whole folder, none
  skipped. Both runs' built requests are still byte for byte the binary's (63 of 63, 47 of 47). Rebuilt with today's
  build (format check bypassed; stored tests_status, then settled again by today's rules), with every request the
  binary's and no ok example of the audit dropped or fired on:

  | run | kept | by mode (blender, python-script, files, section) | new filters' drops | settled again |
  |---|---|---|---|---|
  | first (63 built) | 40 of 80 | 17, 10, 3, 10 | dep_claimed 13 (X14 X36 X53 X55 X56 X59 X69 X76 bad, X75 weak, 4 ungraded), validator_warning 3 (X66 weak, 2 ungraded), ctx_channel 1 (X42), dead_output_key 2 (X40 bad, X23 weak) | 44 (4 files steps none:tests_unreachable, 2 third_party) |
  | second (47 built) | 29 of 52 | 10, 9, 8, 2 | dep_claimed 8 (X10 X32 X44 X45 X58 bad, X12 X67 weak, 1 the cap dropped before), validator_warning 2 (X15 X19), unchecked_code 3 (X17 X74 bad, X54 weak), ctx_channel 4 (X13 X38 X77 X79), dead_output_key 2 (X20 bad, X65 weak) | 32 (D17-D19 none:tests_unreachable) |

  Of the second run's 16 bad the build drops 8 and its 21 weak 10; the gates take two more in a real run (X05's
  output_missing, X80's layout_import), leaving the step-6 four (X06 X07 X27 X39) and X18 and X61. Replayed through
  today's gates on the stored tries (Blender sandboxed at RUN_FORMAT 4, task.solve's order, the stored judge's word),
  of the second run's 59 steps 38 keep the same try, 13 stay dropped, X80's takes its alternate (cand 0, which runs),
  D15 is kept (its judge call still to make) and 6 would need new draws (the stored pick fails, nothing stored after
  it): with nothing better drawn they are soft keeps (blender-0008-00 s1 and s5, X05 and X58; n-blender-0000-00 s3,
  X47; blender-0002-02 s4's repair; research_draft-0007-04 s5; X44's step from another try); 4 of its 11 variants
  need new draws and 2 drop (X45, X20). No later request changes for sure; 8 do if a new draw passes. The first run
  (format 1, so the checks of earlier rounds show too: 8 need draws and 4 drop on those) has 10 steps that need new
  draws on this round's checks, 1 soft keep of another try and 1 different try (a repair the factory camera rule now
  passes): 1 later request changes for sure, 13 if a new draw passes, and round 2's 7 behind coding-0012-01 s7. D03,
  D05, D07 and D08 stay dropped by their judge. Over the 737 distinct stored replies (525 and 212), the echo and leak
  checks flag what they did after the re-check (the first run's 27 version_leak and 6 notes_leak, none in the second);
  the new tell wordings refuse none of them, though 29 told lines carry one, and every one of their 79 runs of up to 8
  words is refused when a reply repeats it. A tiny run on the tests' stand-in Ollama: every record format 3, every
  stored request the binary's, no teacher-only 8-word run in a target its request doesn't hold, dep_honesty firing on
  the first batches and the told ones kept; with Main stubborn, it is kept only as a dependency in both rounds, the
  build drops it as no_example and the report counts it "dependency only".
- **Repairs after the integration check (Nov 4).** Four checkers re-ran the integrated work offline (filters, gates,
  integrity, tells and the seam). Each of their six medium defects was reproduced first, then mended with a test; the
  cheap low ones too.
  - `dead_output_key` takes the plan step (`build.plan_step`, so `collect` gives `(messages, meta, item, step)`). A
    key the piece reads itself counts only when it names a place (`_DEAD_PLACE`: a path, a folder, a pattern), not a
    format or colour mode it applies, and not a file of its own kind (`OWN_FILES`: a script, an export). Nor does it
    count for a step that asks to set the output path or format and asks Chimera for no render or save
    (`sets_output`): the first run's n-blender-0002-02 s5 keeps "output_path" and "output_format" and applies them, as
    its words say. Of the 355 distinct stored Blender tries it names 50 instead of 80; of the 51 that passed, 6
    instead of 7. Every graded firing still fires (X20, X40, X58, X23, X65, X77), and none is ok.
  - A step that asks Chimera for a render or a save is told of the piece's dead keys (`dead_tell`; its wording is in
    `TELL_FORMS`) whatever else fails the piece. 25 of the 39 distinct output_missing tries kept their path under a
    key of their own. A retry that only adds "output" passed every gate and then fell to the build (X58's and X20's
    told forms). The line has no reason of its own, since K5 makes this a fact and not a gate. The longest line is 157
    characters, and none of the 737 stored replies holds its wording.
  - `ctx_channel` counts reads too (`ctx["k"]` as a value, `ctx.get("k")`). The s2 that read a values step's
    `ctx["variables"]` was kept while its s1 was dropped. On the 51 passing pieces it fires on 11 instead of 5: X64,
    X27 and X18 bad, X19 and X67 weak, and one ungraded. 9 of the 108 mechanically passing tries read such a key, and
    none is graded ok.
  - The plan check's `entry_layout` backstop reads where a real run of the entry could look
    (`layout.search_folders`: the entry's folder and every folder above it, a cwd for `python3 -m`). It skips a
    project with a path config (`layout.path_config`, shared with `layout_findings`). Before, a src-layout package two
    folders deep that imports itself inside `main()` passed every gate, then failed the plan check and with it every
    code step of its round. Now it stays unsure, as it did before the backstop, with or without pyproject.toml. The 8
    stored files rounds give the same plan checks as before: X80's is still `entry_layout` with culprit s6. The
    root-entry case of a sibling import inside src/ still blames that file.
  - `run.finished_run` (it was `finished_smoke`) refuses, before writing anything, any start in a folder that holds a
    finished run whose records are all of another format. That holds for every size, and for a folder `--data-dir`
    names too. `run_datagen.sh` refuses it as well (exit 1, before the build, the tests or a log there). Both go ahead
    with `--new-binary-ok`. Before, re-running the second smoke's own command on a scratch copy of data/gen/smoke2
    made 16 model calls and replaced its `sft/`; now it exits 2 and no file changes. Both real smoke folders read as
    refused (formats 1 and 2), and data/gen/smoke3 does not.
  - `dep_honesty.claimed_line` writes the example as the item's name whole, else the failed step's title (Chimera's
    words). The name is at most `NAME_WORDS` (5) words, cut at a word's end, and never "…". 3 of the 108 stored lines
    had "s1: … (failed)" or a cut that ended in "…". A six-word name, copied, is an 8-word run of the line, which the
    echo check refuses in every mode but a section's. The 91 flagged tries, rewritten as their lines ask, all pass
    `check()` and are not refused as an echo. They gain no new validator code but the 5 `handoff_long` that the
    rewrite's appended assumed line gives.
  - New record keys: Blender `measured["dead_output"]` (the keys, when the step asks for an output) and stats
    `facts_examples`.
  - Low ones:
    - dep_honesty also runs on a Blender try that failed only softly (its stage is kept). Its claims are now in
      `no_example`, in `after_audit` and in the same batch's tell. 4 of the 7 such stored tries written with a
      dependency missing claim it; X58's soft keep now lists `dep_unlisted`.
    - At one stage, `soft_keep` prefers the try with the fewest kinds of fault, then drawn order. It no longer mixes
      the candidates' and the repairs' indexes.
    - A joined size fault no longer drops the alone run's output or camera tell line.
    - "Optional:", "if you like" and "if needed" ask for no output and no camera. On the corpus of 301 steps nothing
      changes.
    - dep_honesty excuses three forms: an item marked "not needed" or "unused", an assumed line that starts with
      none but names the failed step or says it failed, and a lone dash. The stored tries have none of them.
    - STATS.md counts what a facts filter found once per example, and says so when no kept example was written with
      a dependency missing. stats.json lists each filter's examples (`facts_examples`).
    - `run.scratch_default` gives a direct `datagen.run` the same `WM_SCRATCH` default as run_datagen.sh, outside the
      home folder, and warns when one is set under /Users or /Volumes.
  - Left as they were:
    - With nothing received and several steps failed, the step named in the dep tell's example is a guess.
    - A literal reading of the output tell, a separate `SETTINGS_sN["output"] = ...` statement, gives
      `top_level_code`.
    - An animation step's generic ".png or .mp4" path.
    - Steps that say only F12.
    - Layout lines over 240 characters with nested folders.
    - `handoff_long` after an appended admission.
    - The README's Common commands and Blender check sections, outside data generation, still set `WM_SCRATCH` to
      data/scratch (Common commands now says to unset it for data generation).
- **Checked after the repairs (Nov 4, the Studio, offline, a fresh copy of the smoke's binary, both Blenders
  sandboxed).**
  - Tests: 667 datagen tests pass (659 and 8 new), and 975 for the whole folder, none skipped.
  - Requests: 63 of 63 and 47 of 47 built requests are still byte for byte the binary's.
  - Rebuilt with today's build (format check bypassed), with every request the binary's (39/39, 43/43, 27/27,
    30/30). No ok example of the audit is dropped or fired on:

    | run | kept (stored tests_status) | by mode (blender, python-script, files, section) | changed drops | settled again |
    |---|---|---|---|---|
    | first | 39 of 80 | 16, 10, 3, 10 | ctx_channel 2 (X42, and X64 by its reads), dead_output_key 2 (X40 on output_filepath alone, X23 on output_path alone) | 43 |
    | second | 27 of 52 | 8, 9, 8, 2 | ctx_channel 6 (X13 X38 X77 X79, and X18 X27 by their reads), dead_output_key 2 (X20 X65) | 30 |

  - What that leaves: of the second run's 16 bad the build drops 10, and the gates catch X05 and X80 in a real run.
    That leaves X06, X07 and X39 (step 6) and X61. Of its 21 weak it drops 10. Of the first run's bad it drops 13 of
    18, the version_leak pair among them. X01, X30, X33, X43 and X62 are left.
  - Gate replay (`replay6.py`, the integrator's with these two flow changes, its Blender runs cached): every outcome
    is the same as at integration. The one difference is that X58's soft keep now carries `dep_unlisted` with its
    `output_missing`.
  - Echo and leak checks: they flag what they did. 1,039 told lines (4 of them the new dead-key line) and 33 with a
    new wording refuse none of the stored replies.
  - The tiny run, plain and with Main stubborn, gives the integrator's numbers. The difference is that the format-1
    copy, a finished folder now, is refused by a tasks start too (exit 2) and remade with `--new-binary-ok` with 0
    model calls into the same records.

## After the third smoke (Nov 4)

The third smoke run (`results/DATAGEN-SMOKE.md`, "Third smoke run": 8 seeds into `data/gen/smoke3/`) built 25
examples, 12% bad against 38% on the same seeds, but Blender gave 3: hydra:1.0 opens most of its Blender rounds with
a values-only step ("Define variables and render settings"), the contract gave such a step no way to hand values on,
and the build-only filter that dropped what the teacher improvised told nobody (904 s on 8 steps that could never be
examples). On Nov 4 the user decided contract question 1 (a values-only Blender step hands its values on in
`ctx["values"]`) and approved this round: (1) ctx["values"] in the contract, (2) a values-step note and ctx_channel as
a gate with a tell, soft on a step with dependents, (3) step 6, the Blender batch (hidden errors and geometry), (4) the
names sheet without unavailable sockets (Weight), and the same fix in Chimera's crash-names hook, (5) the repair share
counted on code lines. It was built in twelve parts (K1-K12) to one interface and one binary (B, sha256
`9348067c…`, then `4a29b0e6…` after the integrator's one fix to the crash-names prelude, then `7c4df992…` after the
repairs the independent checks asked for, both below). Where a section above says otherwise, this list wins. Every number is offline, on the three smoke runs'
records and the two audits (X01-X80, Y01-Y49), with no model call.

- **Formats.** `task.DATAGEN_FORMAT` 4: the three smoke runs' records (formats 1, 2 and 3) are another format's, made
  again by a tasks start and dropped by the build (`old_format`), and a finished folder of them is refused;
  `run.py` and `run_datagen.sh` now suggest `--data-dir data/gen/smoke4` for the fourth smoke.
  `blender_gate.RUN_FORMAT` 5, once for this round's Blender batch (the names line's ctx["values"] keys, step 6's
  prelude, report and geometry line, curve sizes from the evaluated mesh), so every Blender run is made again. The
  epilogues aren't part of a run's key: a `cache/runs.jsonl` entry a format-5 build wrote before step 6 landed would be
  judged nothing by it. None exists (only the tests' fresh caches ran in that window).
- **ctx["values"] in the contract (`app/hydra_contract.go`, `hydra_piece.go`, `hydra_assemble.go`; `contract/`, byte
  for byte).** The Blender rule gets one sentence, Chimera's words and so what requests carry, right after "...find
  what your dependencies list under provides.": `ctx["values"] is the same for plain values other steps use, such as
  sizes, colours and counts; hand on the ones a person might change from your SETTINGS_{sid}, so they stay editable
  there (ctx["values"]["table_height"] = SETTINGS_{sid}["table_height"]).` The guard and `main()` build
  `"values": {}`, and an alone script run after an older ctx gets `ctx.setdefault("values", {})`, one line in the tail,
  so a piece's line numbers don't move (without it, Chimera's check calls such a run unsure on KeyError 'values').
  The validator warns `provides_missing` once per channel, objects first. `ctx_key_missing` judges ctx["values"]
  reads too, and a channel isn't judged from the first piece that writes it so its keys can't be read (the whole
  dict, `|=`, `update()`, a computed key, setdefault with one; that piece's own reads included): with literal keys
  only, `ctx["values"].update(SETTINGS_s1)` followed by a literal reader gave 2 false seams, and 22 of the 72 stored
  pieces with an improvised channel write it that way. The seams (not provides_missing) also count writes through a
  name bound to the channel and straight into `ctx.get()` or `ctx.setdefault()` (Repaired, below). Measured: 1,447 distinct
  stored Blender pieces, 0 verdicts differ; 111 joins, 0 differ in seams, reasons, fallback or line maps; 2,778 alone
  scripts differ only by the literal and the keep_ctx line. Parity with B: 42 texts and 6,291 requests, 0 differ, and
  the full join parity 0 differ (with 275 fixture verdicts, 64 fixture joins and 5,081 random joins, the new values
  snippets and seam plans among them). Every Blender eval request grows by 87-88 tokens; none of the 87 crosses
  7,000, 8,192 or 12,000. `join._code_like` now rules a word out by `str.isdecimal()`, as Go's IsDigit does (no stored
  token starts with a non-decimal digit). The plan doc's frozen Blender paragraph is the new text, with a "Changed
  Nov 4" note. Real long tasks still don't call the contract.
- **The eval's helpers in lockstep (`runner/score.py`, `tools/scene_probe.py`, `runner/blender_run.py`).**
  `provided_names` leaves `CTX_OWN` (objects, values, scene, collection) out, so `ctx["values"]["sofa_width"]` names
  "sofa_width"; `provides_probe` reads the probe's `ctx_values`; the scene probe lists ctx["values"] keys, keys only,
  never the numbers, and a ctx without them prints byte-identical lines. On 757 stored scored Blender records
  `provides_probe` equals the stored score, and no stored provides line quotes `["values"]`.
- **ctx_channel, a gate since format 4 (`blender_gate.py`, `task.py`).** A top-level ctx key other than
  `CTX_CONTRACT`'s (scene, collection, objects, values), written or read, is a reason at the alone stage, after the
  alone run's checks and the measured ones; the try still goes on to the joined check (`SOFT_GATE`), and a variant
  fails on it. It is soft only on a step some later step depends on (`task.SOFT_IF_USED`; `Round.used`: not a variant,
  `planinfo.user_names` not empty): kept so its dependents keep it, with no example, and with no dependent dropping
  it costs nothing. Its stage is alone (rank 3). Its tell (`ctx_tell`, teacher-only, at most 240 characters, told
  whatever else fails the piece, a crash or a lint error too) is `Chimera's ctx has only "scene", "collection",
  "objects" and "values", not ctx["variables"]: ` and then, by what the piece does with its keys, write `put each
  value a later step uses in ctx["values"] under its SETTINGS_sN key and list the keys under provides`, read `take
  what a dependency lists under provides from ctx["values"] or ctx["objects"], with a stand-in if it is missing`, or,
  when every key it writes names an output, Chimera's own words about `SETTINGS_sN["output"]`. The words are ours,
  not Chimera's new sentence: its 4 runs are in `TELL_FORMS`, share no run with `MODE_BLENDER`, and refuse none of the
  782 distinct stored replies nor any of the 63 stored variables/settings tries rewritten to ctx["values"]. On the
  stored tries 77 of the 437 distinct fire (37 write, 40 only read, 35 of the readers copying their dependency's
  key), with lines of 191-227 characters. Replayed with `soft(reasons, used)`: smoke 3 fire (3 soft keeps), smoke2 8
  (6 soft keeps, 1 hard drop, n-blender-0000-01 r2 s4, and 1 variant), smoke3 9 (7 soft keeps, 2 hard drops, r2 s3
  and s4). Of the graded entries it fires on 18, 11 weak and 7 bad, 0 ok, every one already dropped by the build
  before (the gate and the filter read the same keys: 0 of 457 stored tries with Blender code differ). The names
  line lists ctx["values"] keys (the gate's `ctx_values`, `_have`, the judge's listing, its rubric), so a values step
  passes `provides_missing` and its readers pass `removes_earlier`; the stand_in tell now says the marker is for a
  dependency's ctx["objects"] or ctx["values"] key that is missing.
- **The build's backstop (`build.py`).** `FACT_DROPS` and their order are unchanged. The ctx_channel filter should
  fire on no format-4 record: the gate fails such a try first, and a soft keep gives no example (`no_example`, which
  the build drops before the filters). A firing there is a hole in the gate, named in stats.json's `facts_examples`.
  It still drops what it did on older records rebuilt with the format check bypassed (the offline comparisons), which
  is why it stays. In the tiny run below it fires on none.
- **The values-step note (`hints.py`, teacher only).** A Blender step whose title opens with define, declare or
  specify and names variables, dimensions, settings, colours and the like, or is the script's header (`values_step`:
  `VALUES_TITLE`, `HEADER_TITLE`; the title only, and no "set": "Set up ... render settings" steps make or apply
  things), and that some step depends on, gets `VALUES_NOTE` after the versions note: `Later steps use the values
  this step defines: keep them in SETTINGS_sN and, in build_sN, put each one they use in ctx["values"] under the same
  key; list those keys under provides. ctx has no other key for them.` On the 770 distinct Blender steps of the
  helper's raw plans and the three smoke runs it finds 10 (8 by their title, 2 header steps), every one a values-first
  step with dependents, 0 false. 13 stored step-rounds would get it, whose 45 tries wrote ctx["settings"] or
  ctx["variables"] 21 times. Its two fixed parts are in `echoed_note` (`VALUES_FORMS`): 0 of 782 stored replies and
  0 of 135 kept targets newly refused, 0 of 145 graded items newly flagged.
- **Step 6a, hidden errors (`silent.py`, new; soft, stage alone).** A third `--python-expr` prelude watches the piece
  (5.2.2: `sys.monitoring`, RAISE, EXCEPTION_HANDLED and LINE at its guard lines only; 5.0.1: settrace in the script's
  frames), and an epilogue right after the script prints its report (`SILENT_MARK`, at most 6,000 characters).
  `swallowed`: an error from Blender that the piece's own except caught at one of its lines. `skipped_input`: a node
  input looked up by a name the node doesn't have, behind a guard that skipped it, and the input it meant left at its
  default. Each counts only when every version watched and shows it, and not when it is excused (`silent.WHY`: not
  from Blender, not in every version, another computer's GPU, an add-on, a mode switch, get-or-create, an exists
  probe, a file, a set that landed after all, another way that worked). Joined, the piece's hidden errors are
  recorded only. On the 191 distinct stored alone scripts that ran clean (382 runs, every one watched): of the 118
  that pass the gate, 7 are flagged, 3 swallowed (X07=Y44's fcurves and channelbag errors, X58=Y09's and X20=Y27's
  refused FFMPEG enum) and 4 skipped_input (X06=Y08's Base_Color, Specular and Transmission, its smoke2 sibling cand
  1, smoke blender-0008-00 r1 s2 repair 0, smoke3's D29); 9 more of the 74 that fail a later check. Graded flagged:
  8 entries, all bad (4 pieces), 0 ok or weak. Joined-only flags 0 of 133. With and without the prelude 0 of 48 runs
  differ, at +0.00 s median. Its tells (5 forms, 222-292 characters) refuse none of the stored replies.
- **Step 6b, geometry (`geometry.py`, new; the geometry line in blender_gate; soft, stage alone, nested joined).**
  Curves, texts and surfaces are sized from their evaluated mesh (a bevelled bezier measured 4 x 2 x 2 before and
  2.04 x 0.32 x 0.1 now; mesh rows and the listing byte-identical on 348 of 356 runs, the other 8 random trees). A
  geometry line per object (world box, vertices and faces, curve settings, instances, animation, parents, and what
  moves) is read against the step's words: `place_mismatch` (a thing put at a point where neither its centre, the
  middle of its bottom nor its origin is), `flat_extrusion` (a depth asked that every object of the thing lacks),
  `nested` (a flat thing buried in the solid it is to stand behind, before or beside). A reader may fail a step only
  after a held-out check (the scene-check rule: test a word rule on held-out data): on 261 Blender steps of 62 seeds
  outside the smoke runs, places read 22 (16 ok, 5 weak, 1 misread), depths 17 (4, 11, 2) and relations 15 (5, 2, 8),
  so `geometry.GATED` holds place_mismatch and flat_extrusion (`MISREADS` 2 or fewer) and nested is recorded only this
  round. Three reader changes came after the first held-out pass, so those readings aren't fully held out. "On the
  floor" and above or below are recorded, never reasons. It fires on X01 and X27=Y30 (place_mismatch, bad) and
  X39=Y46 (flat_extrusion, bad: the logo with no faces the third smoke's audit found); nested would fire on X06=Y08
  and its two siblings, all three already skipped_input. 0 graded ok or weak are flagged, even with every reader
  gated. +0.05-0.07 s median a run.
- **The names sheet, the crash names and the facts (`app/blender_names.go`, `app/runner.go`;
  `tools/rna_dump_blender.py`, `rna_lint.py`; `hints._sockets`).** Chimera's sheet lists a shader's inputs only if
  enabled, so Principled, Emission and Glass no longer list Weight, which `inputs["Weight"]` can't find in Blender 5
  (5.2.2's sheet 2,900 characters, 5.0.1's 2,883; on 3.6.23 Principled keeps Subsurface IOR, available there). Real
  long tasks get it too, as they get the crash-names hook's fix (K3, the user was told): a KeyError on a bpy
  collection counts a key missing only if it isn't `in` it, and offers its keys deduped and filtered by `in`, so a
  Weight crash in 5.2.2 gets 30 names, starting "Coat Weight", "Sheen Weight", "Subsurface Weight", where it got none,
  and Weight and Subsurface IOR are never offered. The RNA dumps record each socket's availability and what reveals a
  hidden one (one setting, or a pair, at most 4): only Weight, on 22 shader nodes, is never available in either
  version. The lint errors on such an input (`input 'Weight' on ... is never available to a script
  (inputs['Weight'] raises KeyError)`): on the stored data one new error, on 4 blocks of 2 replies that crashed in
  real Blender on it, none on the eval's 1,272 scripts, and no graded ok or weak flagged. The hints' facts leave
  never-usable sockets out and mark revealed ones ("W [float] (with noise_dimensions 1D or 4D)"): 48 of 556 entries
  change, none over FACTS_CAP. `data/rna/*.json` was made again by the integrator (`tools/rna_dump.py dump`, the
  same bytes as the builder's sandboxed dumps but for `made` and `seconds`: 5.2.2 1,507,044 bytes, 5.0.1 1,408,349),
  so the facts and lint tests that need the new dumps run now.
- **The repair share on code lines (`task.code_lines`, `repair_lines`).** A repair example changes at most
  `REPAIR_SHARE` (30%) of the failed piece's code lines: comments, docstrings and blank lines left out, indents
  counted, both sides read the same way. Of the 37 stored repairs (all Blender, all parse), the 5 that passed go from
  0.079, 0.196, 0.347, 0.368 and 0.318 on every line to 0.055, 0.14, 0.282, 0.22 and 0.175 on code lines: 3 come under
  30% (smoke2 blender-0002-02 r1 s4, smoke2 n-blender-0002-01 r1 s3, smoke3 blender-0002-02 r1 s2, the third smoke's
  lost example), none goes over, and of the 32 that didn't pass 2 cross each way. The three admitted are ungraded and
  two look doubtful (s4 deletes the compositor setup, n-blender-0002-01 s3 turns the GPU on for the whole scene):
  grade them blind at the fourth smoke, where REPORT.md names every repair that crosses. `REPAIR_CAP` (15%) may bind
  more often. Since the repairs below, an example also leaves out at most `REPAIR_SHRINK` (10%) of the code lines net,
  which keeps s4 (the compositor deleted) out.
- **The report (`report.py`).** `NEW_GATES` add ctx_channel and step 6's five reasons, and `after_audit` gains a
  count for each change, each with its REPORT.md line: ctx_channel by whether a later step depends on the step (its
  tries, and its steps kept, dependency only or dropped: "unused" should hold no dependency only), the soft keeps by
  reason and the same split, the values-only steps (kept, dependency only, dropped; of their kept pieces, those whose
  code writes ctx["values"], `writes_values`, and those whose alone run listed ctx["values"] keys, `hands_on`, which
  sees a write through a name too), Chimera's provides_missing warnings that are only a reader's own stand-ins
  (`provides_stand_in`, by channel: every key the piece also reads or tests with `in`), plain values registered in
  ctx["objects"] (`values_in_objects`: counted, not gated), step 6's facts (excused hidden errors by why, attribute
  misses, joined-only hidden errors, the floor and above/below readings, the faults the ungated readers would give),
  the geometry readers' held-out counts, and the passed repairs whose share is on the other side of 30% counted on
  every line, by name. On the stored records (formats 1-3, so no gate count is this round's): values steps 6, 4 and
  3 (the 13 step-rounds), none of their kept pieces writing ctx["values"]; provides_missing on 14, 6 and 5 tries, 6, 6
  and 3 of them own stand-ins; over the 437 distinct stored Blender tries 22 warn, 12 only for own stand-ins, and 9
  register plain values in ctx["objects"] (4 mechanical passes, the datagen mapper's count); the repairs crossing in
  are the three above. Of the graded entries the own-stand-in warnings sit on 3 kept pieces, all bad (X45=Y35, X51),
  and plain values in ctx["objects"] on one, bad (X43): leaving such keys out of provides_missing (cut, below) would
  bring nothing graded good back.
- **The tests' fakes and the tiny run (`tests/datagen_fakes.py`, `tests/test_datagen_run.py`).** The stand-in has
  the values pair: a values step (`VALUES_TITLES`) hands its SETTINGS_s1 value on in ctx["values"] and lists it
  under provides, with the guard's new literal (`VALUES_OK`), on qwen3.8:27b and on gpt-oss:120b once its notes carry
  a run of the ctx tell (`CTX_FORMS`), else in ctx["variables"] (`VALUES_VARS`, ctx_channel its only fault); a title
  in `STUBBORN_CTX` never fixes it on any model; Lamp post reads `ctx["values"]["lamp_height"]` with a stand-in. GUARD
  and every other canned piece keep the old guard. `ValuesRunTests` runs main's tasks stage for real on three seeds
  (told; stubborn with a dependent; the same stubborn step with none), with tiny's variants and its round 2 off,
  through binary B and real Blender 5.2.2 and 5.0.1, then the build and the report: every record is format 4; every
  stored request is byte for byte the binary's, carries the contract's sentence and guard, and holds no teacher text;
  `VALUES_NOTE` is in every teacher copy of the two values steps with a dependent and in no other; the told s1's
  first batch fails on ctx_channel alone, the told batch hears the tell and passes, its run lists lamp_height, and s1
  and s2 reach the training file with targets free of teacher text; the stubborn s1 is kept with `no_example`
  ['ctx_channel'] and its reader is dropped by Chimera's own seam (`ctx_key_missing`), while alone the same step is
  dropped; the backstop fires on none; the report counts ctx_channel on 8 tries of 2 used steps and 6 of 1 unused.
  About 17 s.
- **Cut, and why.** A soft stand-in for input files (`stand_in_input`): not in the round the user approved, its yield
  gain an unmeasured upper bound, and it would keep two graded-bad pieces as dependencies; next round's candidate.
  Leaving a piece's own stand-in keys out of provides_missing: it would change 34 stored verdicts; the report now
  measures it (the graded ones are bad). Names sheet option B (conditional sockets listed with their setting): its
  benefit is unmeasured; the facts mark them for the teacher instead. hasattr and interpolation as gates: they can't
  tell harm from a dead probe, so they stay facts. Gating plain values in ctx["objects"]: 9 cases, so counted only. A
  note for the readers: readers copy their writer's channel (35 of 40), so the values-step note fixes it at the
  source. nested as a reason: its reader misread 8 of 15 held-out steps. Re-freezing the eval's values steps (bw-01,
  bw-10), its values cases and `probes/fleet/requests.json`: eval-only, nothing needs them before the trained worker
  is scored. The teacher notes of step 7, the DEAD_TELL split, the `_provided` wrapper (the in-place
  `provided_names` replaces it) and a validator check of the guard's literal (nothing reads it).
- **Left.** A write through a function's parameter (`def put(d, k, v)`, called with ctx["values"]) or through a
  name also bound to something else still counts for nothing, so its literal reader gets a false seam (none stored).
  A reader that silently defaults (`ctx["values"].get(k, x)` with no stand-in print)
  passes every check. In 5.0.1 a piece that sets its own trace or runs threads isn't watched; 5.2.2 needs monitoring
  tool ids 2-4 free; a pure guard operand is evaluated twice. The depth reader's 2 misreads are at the limit, and
  places and depths judge only numbers in the step's own words. Shape, scale and light are still unjudged. Model
  time: each flagged normal step gets a told batch (about 60 s) and, if that fails, two qwen3.8 samples (about 190 s),
  and qwen3.8 already took 32% of the Blender model time.
- **New record keys.** Blender gate `ctx_channel` ({"written", "read"}) and `ctx_tell`; measured `silent`,
  `joined_silent`, `places`, `depths`, `relations`; direct-run probe records `silent`, `geom`, `ctx_values`; the
  scene's `ctx_values`; a repair's `share` and `lines_changed` on code lines, and `shrink`; a places row's
  `stand_in_fault`; measured `joined_places`; report `after_audit`'s `ctx_channel`, `soft_keeps`, `values_steps`, `provides_stand_in`,
  `values_in_objects`, `step6` (with `stood_in`), `readers`, `repair_share` (with `shrunk`).
- **Checked (Nov 4, the Studio, offline, a fresh copy of binary B, Blender 5.2.2 and 5.0.1 sandboxed).** The whole
  datagen suite, 762 tests, passes but one, with 3 skipped (hints' RealSocketsTests, until `data/rna` is remade): the
  one is `test_datagen_silent.py:730`, which reads silent's tell forms as the last of `blender_gate.TELL_FORMS`, where
  geometry's now follow them (step 6b's, as step 6a's interface said; the fix is to find them by index). The build,
  report and run tests, 87 after the last edits (39, 11 and 37), pass, the tiny values run among them. 13 of 13
  mutants of this part's rules are caught (the used split, a variant counted as used, in-tests ignored, the share on
  every line, writes_values or values_in_objects broken, the report's lines gone, ctx_channel out of NEW_GATES, the
  backstop gone, smoke3 suggested, the fake never told, never stubborn, the old guard in VALUES_OK). `build.py`'s code
  is unchanged but for docstrings and a comment, so no stored example is dropped or kept differently by it.
- **Integrated (Nov 4, the Studio, binary B, which a fresh build of `app/` reproduces byte for byte).** Two seams.
  `test_datagen_silent.py:730` now finds silent's forms in `blender_gate.TELL_FORMS` by index. And the crash-names
  hook's new `_chimera_coll = bpy.types.bpy_prop_collection` stopped every check of `hydra_test.py`'s stand-in
  Blender (its bpy has no `types`) as unsure, 36 of its 133 checks failing: it is now
  `getattr(getattr(bpy, "types", None), "bpy_prop_collection", ())`, the same class in a real Blender and an empty
  tuple isinstance never matches elsewhere (`TestTheNamesHookRunsWithoutBpyTypes`), and B was built again. Go: gofmt
  and vet clean, 211 tests pass (also with `-race`), the real-Blender names, crash-names and scene tests pass on
  5.2.2, 5.0.1 and 3.6.23, and the Windows and Linux builds compile. `hydra_test.py` 133/133, `run_it.py` 27/27 and
  `heads_text_test.py` 16/16. Parity with B: 42 texts and 6,291
  requests, and the full join parity, 0 differ. The whole worker-model folder, 1,103 tests (762 of them datagen's),
  passes with none skipped, after `data/rna` was made again. Every stored request of the three smoke runs made again
  through B (286: 143 Blender, 143 other): every Blender one differs from the stored one only in the guard literal,
  the ctx["values"] sentence and the names sheet's lines, the 5 section steps of Blender tasks only in the sheet, the
  other 138 not at all; 2 Blender step requests cross 8,192 (smoke n-blender-0000-00 r1 s3, 8,135 to 8,223; smoke2
  blender-0008-00 r1 s4, 8,161 to 8,216). Replayed with the final gate in both Blenders (the 191 alone scripts and 126
  joins): of the 118 gate-passing pieces step 6 flags 10 (hidden errors 7, geometry 3), the graded ones 14 entries,
  all bad (X06, X07 and X39 among them, and Y46), 0 ok or weak; nested would fire on 3, never a reason. The repair
  share, the ctx_channel replay, provided_names and the echo check (0 of 782 distinct stored replies and 0 of 110
  distinct kept targets refused before or after; every new tell form, the values note's parts and the filled note
  are refused when a reply repeats them, Chimera's own MODE_BLENDER is not) give the figures above.
- **Repaired (Nov 4, after five independent checks of the integrated round; binary B `7c4df992…`).** Four defects,
  one of them found by two checkers, and five cheap misfires; none changes a stored verdict or flags a graded entry.
  - *The alias false seam* (`ctxBoundWrites` in `app/hydra_assemble.go`, `join._bound_writes`, byte for byte). A
    values step writing `v = ctx["values"]; v["sofa_width"] = ...` or `vals = ctx.setdefault("values", {})` gave each
    literal reader a `ctx_key_missing` in the real gate (5.2.2 and 5.0.1), which `SEAMS_FAIL` fails though the joined
    script runs, and the told retry heard that no earlier step registers the key; 181 of the 343 distinct stored
    pieces that write ctx["objects"] do it only through a bound name. The seams, and only they (provides_missing
    still reads `ctx_keys` alone, so alias writers draw no new validator_warning), now count a literal key stored or
    setdefault() through a name every plain binding of which is ctx[channel], ctx.get(channel, ...) or
    ctx.setdefault(channel, ...), or straight into `ctx.get(...)[k]` or `ctx.setdefault(...)[k]`; a computed key,
    `update()` or `|=` through one is opaque. Reads through one stay unrecorded, so it can only take seams away: 0 of
    the 111 stored joins and 0 of the 412 with a step failed in turn change. In the real gate, sandboxed, all seven
    writer forms (literal, update(), an alias, a setdefault alias, `setdefault()[k]`, `get()[k]`, an alias loop) now
    pass with both readers, alone and joined. Parity with the new B: 42 texts and 6,291 requests, 0 differ; the full
    join parity 0 differ (310 fixture verdicts, 81 fixture joins, 5,087 random joins, 62 of 62 codes, the new alias
    snippets and seam plans among them). Every stored smoke request rebuilt through it is what the integrator's B gave.
  - *A thing of separate parts* (`geometry._together`). A table of a top and four unparented legs at (1, 0, 0), a
    chair of parts and letters Word_E..Word_O "centred at the origin" failed `place_mismatch` in both versions, each
    part judged on its own, and the tell named an arbitrary leg. Two or more matched geometry objects are now also
    judged by the box round them all (its centre or the middle of its bottom), and a fault's tell names the part
    nearest the point (`_off`). On the stored runs 115 of 126 matched places match one object, all 8 stored faults
    are single objects.
  - *A place on a stand-in.* A vase stood "on the table top at (1, 0, 0.75)" lands on the 1 m stand-in cube alone, at
    (0, 0, 1), in both versions, and was told to move to the point, ignoring its dependency. An alone run that printed
    a stand-in (any version) now judges no place: the row is recorded (`unmeasured` "stand_in", `stand_in_fault` the
    line it would have told; REPORT.md counts them, step6 `stood_in`), and piece_check judges the places on the joined
    run instead (`measured_check(..., places=True)`, the `joined_places` rows), where the dependencies are real, as
    relations already were: the vase passes, and the gate test's box left at its floor's origin still fails, now
    joined. Skipping such places outright would have lost that box. Of the 25 stored alone runs that printed a
    stand-in and ask a place (59 places), the 12 that reached a joined run fit there (23) or match nothing (4).
  - *A repair that deletes what fails* (`task.repair_measures`, `REPAIR_SHRINK` 10%). Counted on code lines, smoke2
    blender-0002-02 r1 s4 came under `REPAIR_SHARE` (0.282) with a repair that deletes the 21-line compositor block its
    step asks for instead of porting it to 5.x (78 code lines to 58), judged ok. An example now also leaves out at most
    10% of the base's code lines net (`rp["shrink"]`); of the 37 stored repairs it is the only one over 6.2%, and
    REPORT.md names such passed repairs (`repair_share`'s `shrunk`). `DATAGEN_FORMAT` stays 4: no format-4 record
    exists but the tests'.
  - *The cheap misfires* (the step-6 checker's 49 correct pieces through the whole gate in both Blenders). A point
    after "starting/beginning/ending at" (`_ROW_END`: an Array fence whose box centre is at x 2.25), a plain "bevel" (a
    width: a card's "vertex bevel of 0.004 m"; a bevel depth still asks one), a depth under 2 mm (`MIN_DEPTH`: the
    geometry line's 1 mm can't tell a 0.76 mm card from flat) and an IndexError whose handler is a fallback (an empty
    material slot list filled in the handler: `get_or_create`, as a KeyError) ask or count nothing now, and a guarded
    miss one of whose close inputs the piece names as a string isn't `skipped_input` (it set "Specular IOR Level" to
    0.5, its default, on another path). A depth tell writes millimetres, not "0 m". Of the checker's 11 correct
    pieces that step 6 flagged, 10 pass it now (the vase and the parts among them), and nothing else changed among
    its 50 fixtures: the two controls, the real camera fault (`camera_to_view_selected` moves the camera headless)
    and the contrived second collection link still fire. The held-out readings are
    unchanged (22, 17, 15), and the filled values note is now refused across the step's names too
    (`hints.VALUES_FILLED`: 11 of its 32 runs were refused by nothing).
  - *Replayed.* The step-6 replay on the 191 stored alone scripts and 126 joins gives the integrator's output byte for
    byte (10 of 118 gate-passing pieces flagged, 14 graded entries, all bad, 0 ok or weak). The echo check: 0 of the
    892 distinct stored replies and kept targets refused before or after, and all 20 new fixed wordings refused.
    Tests: Go 211 (also `-race`), gofmt and vet clean, and the real-Blender set on 5.2.2, 5.0.1 and 3.6.23; the worker-model folder
    1,111 (768 datagen), none skipped; the Windows and Linux builds compile. Left: a write through a function's parameter, or through a name
    also bound to something else, still counts for nothing; `_blender_stage` ranks every soft alone reason "alone"
    even when the try passed its join, by design; the backstop's TELL_FORMS still leave this round's stand-in,
    provides_missing and never-available lines to precheck, as they did the older tells.
- **Decided Nov 5 and done: in the contract (the user's contract question 4).** The re-check after the repairs found
  that `usesChunks` (Go) and `_uses_chunks` (Python), which gave everything before a uses line's second step id to
  the first, failed the readers this round is for: `uses: ctx["values"]["sofa_width"] from s1, ctx["objects"]["sofa"]
  from s2` read 'sofa' as s1's, `uses_unmatched` is in `SEAMS_FAIL`, and the piece failed in the real gate (5.2.2 and
  5.0.1, sandboxed) although the joined script runs strict with no stand-in, while the same piece written
  `s1: ...; s2: ...` passed; the told retry heard the false line. On the stored records 33 of 229 uses lines name
  two or more steps, 24 pieces had a `uses_unmatched`, and in 11 every one of them was this misread (8 Blender
  candidates failed on it alone). Of the two ways (the contract, or excusing it in data generation only) the user
  chose the contract, in Go and Python with parity. A uses line is now a list of items, cut at "," and ";" outside
  brackets, each given to the step id in it or after it ("X from sN", "X (sN)"), or to an "sN:" lead before it, as
  before. Ids joined by and, or, /, "," and the like are one group, and "s2-s6" a range (at most 9 apart); a group is
  judged as one: skipped when a member failed or isn't in the join, else a seam only when no member holds the name,
  with the same words and the group written s1/s2 (one step's message is byte for byte the old one). An id with
  ":" or an arrow after it runs forward; "and" and spaced dashes mark where one step's names end; an id in a bracket
  of an item with a shallower id takes only that bracket ("X from s1 (s2 failed, so Y is a stand-in)"); text no id
  comes after, in its ;-group, is no step's; one seam per piece, steps and name. `_uses_chunks`' docstring has the
  11 rules; the parity tool compares the chunks (`uses_chunks` through --hydra-assemble) on the tests' lines,
  `random_reader_uses` and every stored task's uses line, and joins `random_reader_plans` and a fixed plan for each
  form. No request, prompt, tell or note text changed, and DATAGEN_FORMAT stays 4 (no format-4 record exists yet; the Blender run
  caches are keyed by the binary's hash). Through the binary, the build before against this one on the 2,483 stored
  corpus joins (everything but `uses_unmatched` the same): on the 776 piece rows that don't fall back 700 seams on
  252 rows became 121 on 77 (all 483 misreads gone, 7 real seams added, 81 of the 81 a careful reading keeps still
  found); its 161 distinct piece rows as run, 113 seams on 45 rows became 28 on 19; its 564 eval rows (85 as run, 479
  the parity tool's variants), 615 became 95; data-generation Blender pieces
  with a `uses_unmatched` 24 became 8, all asides; of the 8 stored gate failures on `seam:uses_unmatched` 4 now pass
  (the 4 left: an own SETTINGS_s3, SETTINGS_s4 mirrored, SETTINGS_s2 defaults and a quoted title). The values reader
  above passes the real gate written suffix, bracket, comment or prefix first, and a real fault still fails. The
  integration's own replay, B6 against B7 on 2,747 joins (the 111 stored joins as they ran, the 412 with each step
  failed in turn, the 837 candidates and repairs joined as the gates join them, the parity tool's 463 task joins (the
  66 stored eval tasks with their cut, library and failed-step variants) and the eval's 924 step replies; the groups
  overlap), changed nothing but `uses_unmatched`, and every changed seam was read: the 143 distinct ones removed
  are 137 misreads (the step before, or only the first id of a group or range) and 6 asides, none of them right as
  written, and of the 10 distinct ones added 8 are real (four CSV names and three lights now with their own step,
  rock_material from s3) and 2 asides as group messages (TrackTo from s1/s2/s3, SETTINGS_s5 from s1/s2). By join:
  as run 86 seams became 19, a step failed 251 became 51, candidates 94 became 35, the parity tool's task joins 768
  became 144. The seam verdict of all 142 stored Blender candidates whose gate reached the join is the stored one through
  B6; through B7 4 pass the seam check and none fails it anew. Those 4 in the real gate today (5.2.2 and 5.0.1,
  sandboxed): all strict alone and joined; 2 pass, one fails on a stand-in its joined run prints with no dependency
  missing, one on `ctx_channel` (Nov 4's; B6 gives it too, with the seam). On the eval's 39 stored task results with a
  join, `uses_unmatched` 81 became 15 (the records, from older builds, hold 53); under `--seam combine` 9 of the 30
  multi-step tasks that don't fall back would go to the combine instead of 23, and none the other way. Left then, and
  what round 8 (the next bullet) did with it: the SETTINGS_sN rule went in, and the two forms that gave a false seam
  the old reading didn't (two ids in one item after a leading word, "Uses s1's table_top with s2's lamp_shade", and
  the "with its b plus" form) now read right; the rest read as they did: "s1: a, b, c from s2" (b to s1), "s1, s2: a"
  (a to s2), "a from s1, made_here (own), b from s2" (made_here to s2), "X from s1 and s2's Y" (the whole item the
  group s1/s2), "s2: lamp (failed), table_top from s1" (table_top to the failed s2, unchecked; with ";" it reads
  right), "table_top from s1, s2 (failed)" (s2 in s1's group, so table_top unchecked), an id inside a path, an arrow
  after a suffix id ("table_obj (s1) -> lamp_obj (s2)": lamp_obj to s1) and a second list after a full stop or "also"
  ("table_top from s1. Also lamp_shade, rug_mesh from s2": lamp_shade to s1). The worker eval's seam counts from
  before (`seams_mean`, `--seam combine`) aren't comparable with new ones.
- **Decided Nov 5 and done: round 8 of the uses reader (the user's yes, the same day), trimmed to what was approved and
  narrowed after independent checks.** In Go and Python with parity (`_uses_chunks`' docstring has the rules, 1-11 with
  5b and 6b), and nothing else: no request, prompt, tell or note text changed, and DATAGEN_FORMAT stays 4 (no format-4
  record exists yet; its comment names this reader). (A) A name SETTINGS_sN (the contract gives every step one dict by
  that name) is judged against sN alone, wherever it is in the line (in a chunk, in text that goes to no step, in a line
  with no step id), and skipped only if sN failed or isn't in the join; so is a key the whole line has only in
  SETTINGS_sN subscripts of one step (SETTINGS_s1["lamp_h"] gives lamp_h to s1; a key uses_names also finds outside its
  subscripts, on the whole line or in any of the line's chunks, or one in two steps' subscripts, stays with its item;
  `settingsKeys`, `_settings_keys`). (B) An item of "<id>'s name" or "<id> name" pairs after a lead with no name, with
  no name between one pair and the next id, reads its runs forward ("Uses s1's table_top with s2's lamp_shade", "the s1
  a with the s2 b"; not after "from", and not "Extends s1's scene with lamp_obj from s2's output"; rule 5b), and is no
  prefix item for rule 10, so the items around it read as before; and a suffix id's list is broken by plus before a name
  when the words right after the id are "with its" or "with their" and no mark stands between the ids ("frame_obj from
  s1 with its leg_objs plus slat_objs from s2" gives leg_objs to s1; rules 6b and 7). Round 8 first did more, and that
  came out the same day: arrows that no longer made a suffix id forward, and arrow pairs; a full stop, "|", also and
  then as breaks anywhere, with the list after one moved to the next item, and the abbreviations, keep words and call
  exemption its repair added to them; failure words, with negations and qualifiers, in rules 9 and 10. Its re-checkers
  found those read many hand-made lines worse than round 7's reader (B7), none of them stored: arrow mixes ("Uses s1 ->
  table_top s2: lamp_shade": 4 templates, 60 of 60 lines each), qualified continuations, abbreviations outside the list,
  failure words outside the lists. The trim that took them out kept (B) wider than the forms approved, and independent
  checks of it (the same day) found four ways it read hand-made lines worse than B7, none stored, each now narrowed to
  B7's reading: the pair item was a prefix item, so the items around it changed owner ("Uses s1's table_top and s2's
  lamp_shade, sofa_obj, rug_mesh from s3" gave sofa_obj to s2; 3 templates, 60 of 60 lines each, and 10 hand lines); a
  pair could have names between it and the next id ("Extends s1's scene with lamp_obj from s2's output", "Uses s1
  table_obj with lamp_obj plus shade_obj made in s2 lamp.py": lamp_obj to s1; 2 templates and 30 lines); a bare "with"
  let a break cut, though "with" is often a verb's partner ("Joins rows_df from s1 with totals_df plus summary_df from
  s2" gave totals_df to s1; 1 template and 28 lines); and also and then were breaks, which was round 8's other change,
  not (B). The trim's build reads 24 lines better than this one, each now as B7 reads it (8 an item after a pair item,
  "..., rug_mesh" no step's again; 10 then or also; 6 a bare "with"), and this one reads 73 of the checks' lines and the
  trim's own "sofa_obj, Uses s1's table_top with s2's lamp_shade" (sofa_obj to s1 again) better than it. Measured
  against B7 at join level (an honest join must give no false seam, and a dishonest one must catch each dropped name
  against its step, as round 8's checkers scored it), no line of any earlier set reads worse, and no name is newly wrong
  at chunk level in any set. Lines read wrong, B7 to this reader: round 7's checker 48 to 46 of 229 and its joins 32 to
  27 of 85; round 8's checker 130 to 61 of 238 and 32 to 17 of 85; the repair's 36 to 29 of 72; the re-checker's 90 to
  55 of 234 and 49 to 41 of 74; the design's new lines 224 to 157 of 302 (correct seams 103 to 166); the hand-made set 5
  to 4 of 64 (seams 63 to 64 of 64); the held-out set unchanged; 56 lines written for the trim 31 to 8; the independent
  checks' 265 and 109 lines 158 to 42 and 41 to 20; 20 lines written for the narrowing 19 to 7; the re-checker's 900
  template lines unchanged. Of the earlier sets' 1,418 lines 243 read differently from B7 (124 through (A), seams only;
  82 through 5b; 37 through the break), 239 better and 4 at the same score. Thirteen hand-made lines read worse than B7,
  all through (A) as approved, and the main session accepted them as they are (Nov 5), with no code change: (A) judges a
  SETTINGS_sN the line says it doesn't use, in text no chunk reaches ("table_top from s1, not SETTINGS_s2", "SETTINGS_s2
  (unused)", "SETTINGS_s1 isn't needed; lamp_shade from s2"; 5 of the independent checks' lines and 2 of the
  re-checker's) and inside a chunk whose group has a failed step ("lamp_shade (not SETTINGS_s1) from s2" with s2 failed,
  "... rather than SETTINGS_s1", "s2: lamp_shade (SETTINGS_s1 unused)"; 6 of the re-checker's 12 negation lines), where
  B7 judged nothing. The name gives a seam only when sN has no SETTINGS_sN dict of its own (in Blender mode a contract
  breach). A key of such a subscript ("table_w from s1, not SETTINGS_s2['width']", "table_obj from s1;
  SETTINGS_s2['seat_h'] isn't needed") gives one whenever sN's piece lacks that key, which needs no breach: the checks
  after the keys fix (below) found it, and the main session accepted it as it is too. Of the 211 lines they wrote for
  the key rule (940 joins; B7 read 143 wrong, this reader 76) 14 read worse than B7: 10 a negated key with a false seam
  on an honest join, 3 negated forms whose seam comes only in decoy joins, and one a quote span inside an item (below);
  the integrity check's own 3 negated-key lines read worse the same way. No stored line has either form, nor any of the
  49,982 fuzz lines with a key. Judging keys only in chunks whose steps ran read 27 lines of the earlier sets worse than
  B7 to fix those 10, and still judging them in lines with no step id 20. It follows the approved "wherever it is in the
  line"; in a chunk whose steps ran B7 judged such a name against the chunk's step at the same score. Leaving such names
  out would bring back round 8's failure words; the other way, judging no SETTINGS name or key in a skipped chunk and
  dropping the whole-line pass, read 86 of the re-checker's hand-made lines worse than this reader (1,140 with its
  templates and composites), as the re-checker measured it. The re-checks also found one defect in (A)'s keys, fixed the
  same day by narrowing: whether a key is also found elsewhere was read on the whole line only, where an apostrophe or
  backtick span can hide a plain use ("Uses s2's seat_h; SETTINGS_s1['seat_h'] is s1's default": with the chain blanked
  the line reads as one quoted name, from the apostrophe of s2's to that of s1's), so the key went to s1, whose dict
  holds it, and a join where s2 lost seat_h had no seam (B7 had one; the re-checker's 4 hand-made joins KQ01-KQ04, and
  320 of its 1,000 made lines with a plain use and a key use of one name). Each of the line's chunks, with its chains
  blanked the same way, is now read too, so more keys stay with their chunk. KQ01-KQ04 now give the s2 seam, as B7 does;
  on 1,000 other made lines of that kind the key went to s1 on 231 before and on none after, and none of those 1,000
  misses an s2 seam B7 gives (it gives 18 that B7 misses). A quote span inside one chunk still hides a plain use ("s2's
  seat_h (a 'seat' height) and SETTINGS_s1['seat_h']": seat_h to s1, so with s1 failed s2 goes unchecked, where B7
  checked it; with s1 present 12 such lines score as under B7 but miss s2 where B7 missed s1); fixing it belongs in the
  tokeniser (a possessive apostrophe opens a quoted name), with its own checks. It changes no seam on any judged set
  above, nor on the re-checker's 275 lines, 2,788 template lines and 3,000 composite lines, the keys of no stored line
  (1 of the 633 has a subscript at all) and those of 4 of the 365,960 lines, all fuzz, each a key taken out. Round 8
  before the trim (B8) had more of the earlier sets right (41, 15, 25, 14, 3, 42, 22 and 34 wrong) but read 23 of the
  re-checker's 234 lines, 3 of its 74, 1 of the checker's 85 and 16 of the trim's 56 worse than B7. Without a cue plus,
  also and then each read verb lines worse ("load_rows() (s1) feeds totals() plus save_rows() (s2)" gives totals to s1).
  Marks come first: where a lower-case "and" at the item's own bracket depth, or a dash with white space on each side,
  stands between two ids, no break between them cuts, so that gap reads as B7 read it ("And", "&", "--" and an "and"
  inside brackets are no marks) (round 8's order, breaks first, read "table_top from s1 plus leg_mesh from it and
  lamp_shade from s2" worse). Other gaps of the line are not held to B7 by it: in "table_top from s1 with its leg_mesh
  plus seat_mesh from s2 and lamp_shade from s3" the break still cuts between s1 and s2 (leg_mesh to s1, where B7 gave
  it to s2), and a pair item's gap with no mark reads forward ("Uses s1's table_top and s2's lamp_shade with s3's
  rug_mesh": lamp_shade to s2, B7 s3). Of the 365,960 lines round 8 measured (stored, hand-made, the checkers' and fuzz)
  613 read differently from B7, 596 through 5b and 17 through the break, 391 of them by attribution; the checker's 1,500
  template lines change on 180, all pairs or "with its ... plus" lines, each as its template reads. Stored: no stored
  line's chunks change (633 distinct lines; the replay's 493, 309 with an id); the replay of 2,747 stored joins changes
  nothing but `uses_unmatched`, and only through (A): 28 joins on 9 distinct lines lose a seam on a SETTINGS_sN name and
  none gains one, 7 lines the piece's own SETTINGS (a fallback, defaults, "mirrored into", "merged into SETTINGS_s4",
  "positions read via SETTINGS_s5") and 2 SETTINGS_s1 given to s2, which s1 holds. By join: as run 19 seams became 18, a
  step failed 51 became 47, candidates 35 became 28, the parity tool's task joins 144 became 128 (86, 251, 94 and 768
  before round 7); corpus rows with a seam 77 became 57 (seams 121 to 101). The keys and the whole-line pass change no
  stored seam, and every stored join reads as under B8 and under the trim's build. Data-generation Blender pieces with a
  `uses_unmatched` 8 became 1 (24 before round 7); of the 8 stored gate failures on `seam:uses_unmatched` 7 pass the
  seam check (4 under B7), and the quoted title ("Import and Extrude SVG") still fails it. On the eval's 39 stored task
  results with a join `uses_unmatched` 15 became 14 (bw-06 s5's own SETTINGS_s5), all seams 17 became 16, and no `--seam
  combine` route changes. The 286 stored smoke requests are byte-identical. Left, as B7 reads them and pinned in the
  tests where written out: an arrow after a suffix id ("table_obj (s1) -> lamp_obj (s2)": lamp_obj to s1); a second list
  after a full stop, "|", also or then ("table_top from s1. Also lamp_shade, rug_mesh from s2": lamp_shade to s1); "s2:
  lamp_shade (failed), table_top, table_legs from s1" (table_top to the failed s2, unchecked); "table_top from s1, s2
  (failed)" (s2 in s1's group, so table_top unchecked); a forward id's list broken by plus ("From s1 a plus b from s2":
  b to s1); a purpose clause ("a from s1 for placing b, c from s2": b to s1); a list broken by then or also, by plus
  after a bare "with", with no "with" right after the id or with a mark before it ("a from s1 with its b then c from
  s2", "a from s1 with b plus c from s2", "a from s1 together with its b plus c from s2": b to s2; "a from s1 with its b
  and d plus c from s2": d to s2); a pair before a suffix id, which isn't an item of pairs ("Uses s1's table_top with
  lamp_shade from s2": table_top to s2); pairs with a name between them ("Uses s1's a and b with s2's c": b to s2); the
  items around a pair item, read as without it ("Uses s1's a with s2's b, c": c unchecked; "c, Uses s1's a with s2's b":
  c to s1); "s1: a, b, c from s2" (b to s1), "s1, s2: a" (a to s2), "a from s1, made_here (own), b from s2" (made_here
  to s2), "X from s1 and s2's Y" (one group s1/s2), "a, b, from s1" (a and b unchecked), an id inside a path, a quoted
  title judged as a name, and a possessive before a single-quoted subscript, which pairs with its quote into one quoted
  name ("s1's SETTINGS_s1['seat_h'] with s2's lamp_shade": "s SETTINGS_s1[" judged against s1); read otherwise than B7
  and accepted as it is (above), the SETTINGS_sN, or key of one, a line says it doesn't use; and, left from the keys fix
  (above), a plain use inside a quote span of its own chunk. The worker eval's seam counts from before aren't comparable
  with new ones.

## After the fourth smoke (Nov 5)

The fourth smoke run (`results/DATAGEN-SMOKE.md`, "Fourth smoke run": the third run's 8 seeds into `data/gen/smoke4/`)
built 26 examples, 8% bad, but Blender gave 4 from 21 steps, and the audit found why ("Why Blender still yields
little"): Blender 5 API faults the notes don't cover, build-only filters that never tell the teacher, the values
steps' provides limit, a scene judge that broke its own rubric on all 4 of its Blender rejections, the camera habit,
and a second sampler that took 35% of the Blender model time for 1 example. On Nov 5 the user approved this round
("Yes, fix round"): Blender 5 API facts for the teacher, tells for what the build drops, the scene judge kept to its
own rubric, the camera habit, and the second sampler's budget. It is data generation only: nothing in `app/` changed
(Chimera's request text, the contract, the validator and its limits, the names sheet), nor hydra's planner, reviewer
and Head-check prompts. The two contract limits stay as they are: Chimera's `handoffLineMax` (300; a values-only step
that lists the 19-20 keys its plan names fails `handoff_long`, a question for the user, so nothing here treats it
differently and no tell loops on it) and `MAX_TARGET_TOKENS` (3,500 with Chimera's estimate). It was built in four
parts (facts, tells, judge, budget), each against the same tree and the fourth smoke's binary (`458dcbfc…`), then
joined (Integrated, below). Where a section above says otherwise, this list wins. Every number is offline, on the
stored records of smoke2-4 (where said, also the first smoke's and the helper's stored plans), Blender 5.2.2 and
5.0.1 sandboxed, with no model call.

- **Formats.** `task.DATAGEN_FORMAT` 5, once for the round: a format-4 record was judged by other rules (the gate's
  new reasons fail tries that passed, the lint passes tries it failed, the scene judge sees other messages and some
  rejections are overruled, a fence-fixed reply passes precheck), and a run drew by another policy (a third told
  batch, qwen3.8 skipped, its `num_predict`), so smoke4's records are another format's now, as smoke2's and smoke3's
  are: a tasks start makes them again, the build drops them (`old_format`), and a finished folder of them is refused.
  `run.py` and `run_datagen.sh` suggest `--data-dir data/gen/smoke5` for the fifth smoke. `blender_gate.RUN_FORMAT`
  stays 5: no prelude or epilogue changed (`attr_miss`, `doubled_depth` and the judge's labelled locations read what
  format-5 runs already print, the silent report and the geometry line; `build_facts` and the stand-in checks read the
  code and Chimera's verdict), so every cached run is still good; replayed, the base tree and this one make the same
  scripts (every run of smoke2-4 the one made was a cache hit for the other).
- **Blender 5's API facts, and the habits (`hints.py`, `tools/rna_lint.py`, `silent.py`, with the wiring in
  `blender_gate.measured_check`, `task.SOFT_IF_USED` and `report.NEW_GATES`).** The fourth smoke's teacher kept
  writing the Blender 4 API (16 of 123 Blender tries crashed or were linted on `Action.fcurves`, all 8 tries of
  blender-0008-00 s5 missed the video settings, all 6 of blender-0002-02 s4 the compositor), stood its new camera
  behind the factory one, rendered or saved where the step said to, and the lint failed the one try that guarded its
  old path properly. The step corpus below is the 545 distinct Blender steps of the helper's raw plans and replans and
  the four smoke runs.
  - *The facts (`BLENDER5`, `step_notes`, `api_facts`; teacher-only, after the versions note and the values note).*
    Six, each given when the step's words name its topic or an earlier try's failure does: keyframes (an Action has no
    fcurves; `bpy_extras.anim_utils.action_get_channelbag_for_slot(action, slot)` with the ID's
    `animation_data.action_slot`, None before the first key, holds the keyframe_points), video (`media_type` "VIDEO"
    first, which sets FFMPEG; `file_format = "FFMPEG"` alone raises TypeError; the container is `ffmpeg.format`,
    MPEG4 for .mp4, the codec `ffmpeg.codec`; no `ffmpeg.container`), the compositor (no `scene.node_tree`;
    `scene.compositing_node_group`, a `CompositorNodeTree` group whose Group Output, through `interface.new_socket`, is
    what a render gets; no Composite node; a transparent PNG needs only `film_transparent` with the PNG at its default
    RGBA), SVG import (`bpy.ops.import_curve.svg`, not a wm operator, into a collection named after the file, about
    0.28 mm per SVG pixel), a curve's extrude (both ways, to twice the value: 0.08 spans -0.08 to 0.08, and a negative
    value is clamped to 0, as the third smoke's flat blender-0002-02 s1; for a depth d on one side, extrude d/2 and move
    d/2, or a Solidify of d at offset -1, which goes to -Z on a flat filled curve of either winding and on an imported
    SVG curve) and the Subsurface Scattering node (no Weight a script can reach; the Principled BSDF's is Subsurface
    Weight). No version is named, code is short identifiers. Every claim was run in both sandboxed Blenders before it
    was written (27 of 27 in each; `tests/test_datagen_blender5.py` runs 32 such claims again, about 2 s). Not given:
    the new-key preference (`keyframe_new_interpolation_type` "LINEAR" leaves keyframe_insert's keys BEZIER in both).
    On the step corpus the words give keyframes 84 steps, video 68, compositor 49, extrude 42 (only with a curve, text,
    logo or SVG word), SVG 10, subsurface 4; on the stored tries (smoke2/3/4) keyframes 30/27/28 tries (5/5/4 steps),
    video 8/7/8, compositor 5/6/6, extrude 6/8/13, SVG 4/6/6, subsurface 9/9/8, every one by its words (the failure
    triggers add none: every stored step that failed on a trap names it).
  - *The fix on a failure line (`fix_for`, in `_line`).* A lint finding, crash or plain line whose text hits a fact's
    pattern ends with its replacement ("; its F-curves are in
    anim_utils.action_get_channelbag_for_slot(action, slot).fcurves", "; set image_settings.media_type to 'VIDEO'
    first, which makes file_format FFMPEG", the container, `scene.compositing_node_group`, no Composite node,
    `bpy.ops.import_curve.svg`, Weight; a Blender step's line only, since the checks), cut before it when the line
    would pass 240 (a hidden-error tell keeps its end since the checks, below), so the next try and the repair
    hear what to write instead of the lint's nearest names ("(has: 'usd_import', 'stl_import', 'ply_import')" for
    `wm.svg_import`). The crash itself is untouched: a repair's request stays Chimera's text, the fix and the facts
    reach the teacher only in its copy. Of the stored tries, 9/15/24 would have heard a fix (smoke4: 75 fcurves lines,
    10 video lines); the compositor and SVG faults of smoke4 were on its last tries, so nothing after heard them.
  - *The camera habit and the render rule (`CAMERA_NOTE`, `OUTPUT_NOTE`).* A step that adds a camera of its own
    (`blender_gate.asks_camera`, camera_not_active's reading, so not where another step says which camera renders) is
    told a render uses `scene.camera`, which the start-up scene's camera holds, so to make its own the scene's (11 of
    the 14 tries of n-blender-0000-01's two camera steps didn't, and their "Camera" became Camera.001). A step whose
    words ask Chimera to render or save (`asked_outputs`) is told Chimera's mode rule wins over its wording, in our
    words, sharing no run with Chimera's rule: every one of the 12 stored saves_or_renders tries is on such a step.
    Camera on 56 corpus steps and 34/31/31 stored tries, output on 211 and 19/21/27.
  - *Guarded reads in the lint (`rna_lint.guards`, `Linter._guarded`).* An attribute read that can't run without its
    name is no finding: behind `hasattr(x, "name")` or `getattr(x, "name", <falsy>)` on the same expression (an if,
    elif or while test, an and, an or after a not, a conditional expression, a comprehension's if, an assert, an early
    return, continue, break or raise when it is missing), until the receiver's name is bound again, and anything in a
    branch no version reaches (the body behind a hasattr whose name no version's type has; the else or elif behind one
    every version's type has was one too until the independent checks, Nov 6, below, and so was a probe on bpy.ops and
    an assert or raise on a name no version has). A try is no guard (silent.py's policy B holds such a piece), nor is
    a nested function. Of
    the 289 distinct stored Blender codes 5 lose findings (6 tries), every one a real guard: smoke4's
    n-blender-0000-01 r2 s3 c5 (it sets LINEAR through the channelbag and makes its camera the scene's) now passes
    this part's gate in both Blenders, though the integrated gate gives it `validator_warning:provides_missing`
    (below); smoke2/3's r2 s3 c2 fails on ctx_channel instead, smoke3's r1 s3 r0 on dupes and ctx_channel, smoke3's
    variant c1 never reached the gate, smoke4's blender-0008-00 s4 r0 on attr_miss. On the eval's 763 distinct stored
    Blender replies 13 lost an error (20 findings: EEVEE's bloom, SSR and samples, auto smooth, fcurves behind hasattr
    or a dead else; 12 and 19 since the checks, whose else came back), and the 64 verified scripts lose their one
    warning (w3-19's `mod.properties`, behind hasattr): the eval's `lint_errors_mean` would move if a run were
    rescored (5 of the 18 stored runs), and `runner/freeze.py`'s verify, a pass/fail gate, could keep other replies
    (on the 11 stored W1 dependency replies it keeps the same with or without the rule), so since Nov 6 the rule is
    the data generator's only (`Linter(facts, guards=True)`; Decided (Nov 6), below) and the eval and freeze lint as
    before.
  - *attr_miss as a reason (`silent.missed_keys`, `asks_linear`, `missed_tell`; soft as ctx_channel is: `SOFT_GATE`,
    `task.SOFT_IF_USED`, stage alone).* Step 6's attribute misses stay facts, but one on the way to the keys (fcurves,
    channelbag(s), keyframe_points, or anything on an Action* struct) in every version is a reason when the step's
    words ask for linear keys (`LINEAR_ASK`: 16 of the 545 corpus steps, every one about keyframes; never an image
    texture's, a shape key's or a colour ramp's interpolation) and every version's report shows keys and none of them
    LINEAR. Its tell names the channelbag path. The only stored step asking it is blender-0008-00 s4 (all four runs),
    which s5 depends on, so it is soft there. It fires on smoke2's c5 (X07, graded bad: already a soft keep by
    `swallowed`), smoke3's c4 (already `joined_dupes`), and smoke4's c4 (the kept piece that claims LINEAR: now a soft
    keep with no example; its example was already lost to the failed-dependency cap), c5 (with dep_claimed) and r0
    (lint:attr before). It fires on no piece whose keys are linear: smoke3's kept c5 (its hasattr on Action.fcurves
    missed too) stays a pass, and the first smoke's c4 (LINEAR, no miss) gets nothing. The record gains
    `measured.silent.missed` only when it fires.
  - *The echo check.* 25 new wordings (26 since the checks: the camera note, the output note's two parts and its fills
    for s1-s8, the six
    facts, seven fixes, attr_miss's two fixed runs), all registered in `echoed_note` (`blender_habit`, `output_note`,
    `blender_fact`, `failure_line`; `silent.MISSED_FORMS` directly, so `blender_gate.TELL_FORMS` and the tests that
    pin it are unchanged), every 8-word run of each refused in tests. None shares a run with Chimera's Blender rule for
    s1-s8 or the 165 stored requests, and code that does what each says (the channelbag loop, the video settings, a
    compositor group, the SVG import, a half extrude and a Solidify, the Subsurface Weight, `ctx["scene"].camera =
    cam`, an "output" dict) repeats none.
- **What the build drops, told at the gate, and the stand-in marker (`blender_gate.build_facts`, `stand_ins.py`, new;
  `task.SOFT_IF_USED`, `report.py`).** In the fourth smoke Chimera's validator warnings (`handoff_long`,
  `uses_undeclared`, `provides_missing`) reached no tell (`task._validator_lines` sends only a failed precheck's
  errors and form warnings) and `dead_output_key` was told only to a step that asks Chimera for a render or a save:
  28 of its 123 Blender tries carried a dead key, none was told, and 5 kept pieces fell to these build filters after
  sampling had stopped. Now `piece_check` reads, before any run, what the build would drop the piece for and the two
  marker faults, tells them whatever else fails the piece (`facts_tell`, after `ctx_tell`, before the measured faults;
  the record keeps `facts`: `warnings`, `dead_output`, `stand_ins`, `reasons`, `waived`), and adds their reasons last
  at the alone stage, after `ctx_channel`: `validator_warning:<code>`, `dead_output_key`, `marker_misused`,
  `silent_default` (`blender_gate.FACT_REASONS`). Each goes on to the joined check (`SOFT_GATE`, `_hard` by prefix),
  ranks "alone" in `_blender_stage`, and is soft only on a step a later step depends on (`SOFT_IF_USED`), as
  `ctx_channel` is: a variant fails on it, and a step nothing depends on is dropped when no try comes back clean. The
  build's filters stay as the backstop. Code modes are unchanged (their validator warnings stay build drops).
  - *The tells* (ours, teacher-only, at most 240 characters; a line that would run long quotes one key and "and
    more"). provides_missing: the channel and keys from Chimera's message (from the code when the record cut it, its
    substring test), "list under provides each key a later step reads, and leave out of ctx[...] the ones none does";
    when every key is one the piece also reads or tests with `in` (its own stand-in for a dependency's key,
    `report.stand_in_warnings`' `own`), that a stand-in stays under a name of the piece's own and only what the step
    makes is registered. uses_undeclared: take nothing from a step this one doesn't depend on, keep the value in its
    own SETTINGS (naming the steps and its dependencies; a second form when it depends on none). handoff_long: the
    line and its length against Chimera's 300, with advice by line (provides: only the exact names; a plain list on
    a step that isn't a values step: name and register only what a later step or the result uses; uses: each step and
    its main names; assumed: each guess in a few words). dead_output_key: `DEAD_TELL` when the step asks for an
    output, as before, and `DEAD_UNASKED` when it asks for none ("leave that key out, since Chimera reads only
    "output", and only for a step that asks for one"); the build's step excuse (`sets_output`) applies, so the gate
    and the filter read the same keys.
  - *The open contract question, left as it was.* `handoff_long` on a values-only step's provides line
    (`hints.values_step`), whatever its form since Nov 6 (Decided (Nov 6), below; until then only one that is a plain
    list of names, `plain_names`: items cut at commas, semicolons and "and" outside brackets, each a name with at most
    one note in brackets: all 6 distinct long values-step lines of smoke2-4, 331-420 characters, and 1 of the 21 other
    long provides lines), gets no reason and no tell, and the build still drops it (`validator_warning`). A piece
    carrying it fails nothing else new either (`waived`: the build drops it whatever a told batch does, so failing it
    would cost batches that can't win its example; the fourth smoke's two values steps also print the marker for
    render_device). No tell a values step can get asks it to shorten that list: provides_missing asks it to list its
    keys, which is then exempt, and the long-line advice is never given to it (tested), so nothing loops on it. On
    the stored records it covers 5 tries of 2 steps, 2 of them kept (REPORT.md's new line).
  - *The stand-in marker (`stand_ins.py`, static, no run).* Chimera's Blender rule makes the marker a dependency's
    missing ctx key. `marker_misused`: a print of the marker whose key is a literal (the first word after it, or the
    print's second argument; the gpt-oss hyphen and an f-string's whole first word read too; since the checks past
    filler words, `stand_ins.FILLER`) and is no dependency's
    key the piece reads: on a step with no dependency always (the fourth smoke's values steps' "chimera: stand-in
    render_device (fallback to CPU)"), else unless the key is a name the piece looks up (a ctx or other dict key,
    `bpy.data`, another step's SETTINGS, a string value of its SETTINGS, a helper's or a loop's literal; with or
    without chimera_, or the start of one, "room" for room_length) or one an earlier kept piece hands on (its
    provides names, the uses reader's code-like words, the ctx keys its code writes, its SETTINGS keys when it writes
    ctx["values"] in a loop). A key a variable gives is the reader's own loop and isn't judged. `silent_default`: a
    read of a dependency's ctx["values"] key with a default and no marker (`.get(k, d)` with d not None,
    `.get(k) or d`, `x if k in values else d`, through ctx or a name bound to it): a key is a dependency's when an
    earlier kept piece hands it on, or, with a dependency missing, when the piece doesn't write it itself; a key the
    piece writes (a loop over its own SETTINGS included) is get-or-create, and one no present dependency hands on is
    excused. A helper's key stands for the literal keys passed to it (none a dependency's: excused); one that can't
    be read ("bench_" + k) is taken for a dependency's. Covered by a marker with its key, or any marker in the same
    function (since the checks also a stand-in helper's keys and a marker loop in a function around or calling the
    read's). A step with no dependency has no silent default. Tells: the marker's keys and that the line is for a
    missing dependency's ctx["objects"] or ctx["values"] key; the silent keys (or the helper) and that where the
    piece makes its own value for a missing key it adds Chimera's own `print("chimera: stand-in", key)` (a slot, so
    the call itself is no echo).
  - *Measured on its own (the stored tries, the earlier steps' kept pieces as the gate joined them, variants alone).*
    smoke4: of its 123 Blender tries 73 carry a fact or a marker fault; 52 reached the gate and would be told (28 of
    them heard by a batch the stored run drew anyway), and 22 on 15 steps of 4 seeds would get a reason
    (dead_output_key 11, silent_default 7, marker_misused 6, provides_missing 6, handoff_long 1; 5 more waived). Of the
    28 dead-key tries 21 are told and 11 get the reason; 7 never reached the gate. Extra model time if every told try
    failed again: 498-644 s (1 told gpt-oss batch, about 60 s, and 3 qwen3.8 batches, about 146 s each), against
    4,957 s of Blender model time. The graded Blender entries of the three audits on these runs: 5 bad and 4 weak fire,
    none of the 4 ok; the marker and the silent default fire on 4 bad (X05, X20, X58, Z26) and on Z12, the weak example
    the audit named for it, and on no other. Every fired try's reasons are the same read from Go's code as from the
    target's python blocks (226 distinct tries, 0 differ). 14 new forms, in `blender_gate.TELL_FORMS`
    (`BUILD_TELL_FORMS`, `stand_ins.TELL_FORMS`, before silent's and geometry's); none shares a run of 8 words with any
    of Chimera's texts (`contract.texts`, the Blender rule filled for s1-s7), and none names a version.
- **The scene judge kept to its rubric, and an extrusion check (`judges.py`, `blender_gate._listed`,
  `task.Round.judge`, `geometry.py`).** The audit found the scene judge broke its own rubric on all 4 of its Blender
  rejections, and the one bad Blender example was a logo extruded 0.08 m both ways where its step asks 0.08 m in
  negative Z. Nothing in a request or a note changed here.
  - *Where an object is (`blender_gate._where`, `_boxes`).* A location in the judge's listing was the object's origin
    only. smoke4's n-blender-0000-00 r1 s2 c0 (and smoke2's = smoke3's same step) builds cubes at their points and
    then calls `transform_apply(scale=True)`, which applies the location too, so every origin is (0, 0, 0) while the
    geometry is where the step puts it (replayed: smoke2's fridge centre (1.2, -0.3, 0) and stools' (±0.6, ±0.3,
    0.5), the step's own points); the judge failed both for "all placed at the origin". A location is now
    `{"geometry_centre", "geometry_bottom", "origin"}`: the centre of the geometry's world box and the middle of its
    bottom, from the geometry line every format-5 run already prints (GEOM_EPILOGUE), then the origin; a light, a
    camera, an empty or a run without the line gives `{"origin"}`. On the 61 stored judged tries of smoke2-4 (51
    distinct pieces, replayed alone), every run has the line and 99 of the 148 objects listed get a geometry location;
    on 12 tries 33 objects' origins lie more than 5 cm from both their geometry's centre and its bottom, and those 12
    hold all 3 position rejections. The largest judge message is 3,607 estimated tokens.
  - *Output forms (SCENE_SYSTEM).* A new paragraph: every piece has the one shape its request sets (a settings dict
    and a build function, run with the other steps' pieces in one script, saved or rendered once after the last
    step), which replaces any output form a step names for its code (a string variable, a script returned, printed,
    exported or written to a .py, the scripts combined), so the judge judges what the code built. Of 383 distinct
    steps of Blender plans (the helper's stored plans and the smoke runs, kinds blender and code), 164 name such a
    form (".py" 62, output or return the code 43, a string variable 4, plain text or combine 3, "write a Python
    script" and the like 52). Two of the rejections rested on one ("missing blender_script variable output",
    smoke4's n-blender-0000-00 r1 s1 c0 and the first smoke's copy; "did not produce the required script export",
    smoke4's n-blender-0000-01 r1 s4 c5). The rubric also says what the location labels are and that a step's sizes,
    positions and numbers are measured by other checks, with values its dependencies hand on that the judge doesn't
    see. Its 7 new sentences share no 8-word run with any stored reply or kept target of smoke2-4 (the rubric reaches
    no request either way: the scene judge's reason is told to no teacher).
  - *No goal (`scene_messages`).* The scene judge saw the person's task under GOAL_HEAD. Its two questions are the
    request's, which carries the plan and the dependencies' pieces, never the goal. Of the 133 stored scene-judge
    verdicts of the four smoke runs, one gives a reason only the goal holds, and it is false: smoke4's
    n-blender-0000-01 r1 s2 c0, "length 2.0 m instead of required 2.2 m", where 2.2 m is the goal's and 2.0 the
    `sofa_dim` that s1's piece sets in the request (two first-smoke reasons naming EEVEE took it from the listing's
    engine, not the goal); none needed it. So the scene judge's messages are the outline, the step, the handoff and the
    listing; the prose judge and the tests writer keep the goal. A verdict is now a function of what the judge is
    shown, so two seeds with the same plan share it from the cache (a test's second run needed another plan title).
  - *A rejection that rests only on what is measured is overruled (`judges.overruled`, `names_output_form`;
    `task.Round.judge`).* A scene judge's rejection whose reason, once its size claims ("sofa size is wrong", a
    length or a number with its unit "instead of" another), position claims ("all placed at the origin", "instead of
    the specified coordinates") and, on a step that names one, output-form claims are taken out, says nothing else
    (no thing missing, extra or another step's, no setting, material, animation, light or camera property, no number
    left, so a count of things stays the judge's) is overruled: the record keeps the judge's verdict and gets `ok`
    true, `rule` "overruled" and `overruled` (its kinds, `judges.OVERRULED`). Overruled, not sent for a second
    opinion: the gate measured the step's own sizes and places before the judge was asked (`size_mismatch`,
    `place_mismatch`), and a second opinion is qwen3.8, which the model gate keeps apart from gpt-oss (a swap each
    way). The prose judge is other code with a rubric that is about invented figures, so it isn't touched. On the 133
    stored verdicts (51 rejections): 7 overruled, 5 distinct pieces (positions 2, a size 1, output forms 2), every
    reason false against the run; in smoke2-4, 6 of the 8 rejections. The 44 that stand rest on settings, missing or
    extra things, or (smoke2's = smoke3's n-blender-0000-01 r2 s4 c0) which material is on which object, outside the
    overrule's kinds. One overruled piece has a real fault its judge didn't name: smoke4's n-blender-0000-00 r1 s2 c0
    puts its stools' tops at the step's z 0.5 (centre 0.11, bottom -0.28, so 0.28 m into the floor) where the step
    gives "(±0.6, ±0.3, 0.5)", and no check reads a ± point (3 of the 305 distinct stored Blender steps have one, 2 of
    them this step): the one example it wins is weak at best. Every Blender judge call is asked again under the new
    messages (smoke4's 19 calls, 208 s, 4% of its Blender model time). Since Nov 6 a size or position claim is
    overruled only when the gate's readers read a value for the thing it names (Decided (Nov 6), below): of the 7
    overrules only the 3 output forms stay, and that step's position claim stands.
  - *doubled_depth (`geometry.asked_doubled`, `doubled_states`, `_one_way`, `DOUBLED_TELL`; soft, stage alone).*
    Blender's extrude of a curve or a text goes both ways (5.2.2 and 5.0.1, sandboxed: extrude 0.08 gives z -0.08 to
    0.08; a bevel depth adds its own on both sides; fill mode and offset change neither); one way takes half the value
    and a move by that half, or a Solidify (offset -1: z -0.08 to 0). `flat_extrusion` read only a depth of zero.
    `asked_depths` now says when a depth is the thing's whole depth one way ("one_way"): a side right after the
    number ("in the negative Z direction", "downward", "one way"), a mesh, its faces or a plane being what is
    extruded (nearest the extrusion word), or a whole depth or thickness of anything but a curve or a text; never an
    extrude value of a curve or a text, a range, a random depth, a value to record or a bevel depth. A one-way depth
    fails when every candidate (`depth_states`' own) is twice it (within 10%) at its thinnest, less a curve's bevel,
    none flat or instanced; its tell, ours, names the Blender fact. Held out (the 261 steps): of the 17 depth
    readings 9 are one-way, 1 misread (blender-0008-03 s2 extruding s1's "Leaf", which alone is a stand-in:
    flat_extrusion's same misread), so `HELD_OUT` has it at 9 and 1 and it is gated (`MISREADS` 2). The side path
    read none of them: of the 5,154 distinct stored plan steps only blender-0002-02 s1 names a side for an extrusion,
    so the held-out count vouches for the mesh and whole-depth readings only. A direction isn't judged: the geometry
    line holds no curve's plane, and a curve extruded 0.04 at z 0 (0.08 m, centred) passes "0.08 m in the negative
    Z". On every stored try of the 2 distinct stored steps that name a depth (31 tries of smoke-smoke4, 27 distinct,
    replayed alone) it fires on 6, all blender-0002-02 s1's text or curve at 0.16 m (smoke c1, smoke2 c0, smoke3 c0,
    smoke4 c2, c5 and repair 0), c5 the audit's bad example, and on none of blender-0008-00 s1's logos of 0.15 m. No
    graded ok or weak entry is flagged. Its fixed run after the depth is in `geometry.TELL_FORMS` (its start is
    DEPTH_TELL's, registered once).
  - *The report.* `after_audit` counts `scene_overruled` ({"verdicts", "kept", kind: n}) with a REPORT.md line, and
    `NEW_GATES` and the geometry rows have `doubled_depth`; the readers' line lists its held-out counts.
- **The second sampler's budget (`task.py`: `Round.solve`, the new `Round.teacher_batch`, `heard`, `api_only`,
  `api_fault`, `api_names`, `fault_keys`, `THIRD_BATCH`, `SECOND_OPTIONS`; Blender only).** In the fourth smoke
  qwen3.8 took 1,756 s, 35% of Blender model time, for 1 example, and 9 of its 60 stored Blender calls of smoke2-4
  ran out at `num_predict` 8,192 while still thinking (1,083 s, no gate pass). "With the fence" below means with the
  handoff fence fix (the next bullet) replayed through the real gate.
  - *A third told batch when the second heard its notes.* A Blender step whose second batch failed only on faults the
    first didn't have (`heard`: no `fault_keys` in common; a key is a Blender API name, another lint error, a
    validator code, a crash's error, a strict run's first tell line, an echo label or the reason itself) gets one
    more batch of 2 gpt-oss samples, told both batches' failures, before its repairs; qwen3.8 still comes after it if
    it fails. Why: a told batch kept 9 of the 41 Blender steps whose first batch failed (22%) at about 65 s (the mean
    Blender draw is 32.5 s over 228), where qwen3.8 kept 9 of the 30 steps it was asked on at about 161 s a step
    (4,831 s); a section's third batch kept 4 of 18 after two failed (22%). Counted per sampler (the report's new
    lines; smoke2 rebuilt with today's filters), told samples gave 5 Blender examples in 3,135 s (1.59 per 1,000 s),
    qwen3.8 2 in 4,831 s (0.41). With the fence alone it fires on 13 steps (smoke2 4, smoke3 3, smoke4 6): +26 calls,
    +847 s. qwen3.8 had 2,040 s and 5 kept pieces on those steps (3 built: smoke2 blender-0008-00 r1 s4 and
    n-blender-0000-00 r1 s2, smoke4 blender-0002-02 r1 s1, graded bad); they aren't lost, but they won't replay. At
    the told rate the third batch keeps about 2.9 of the 13 and saves about 450 s of the qwen3.8 time after it, so it
    costs about 400 s over the three runs for about 1.8 more kept steps: a yield bet, not a saving.
  - *No qwen3.8 when every teacher sample failed only on Blender API names (`api_only`).* A try is an API fault when
    every reason is a lint error of a kind that means a name Blender lacks (`API_LINT`: attr, socket, enum, module,
    node_type, op, op_arg, arg, class) or a strict run whose crash names one, in the forms the stored runs show
    (`_API_CRASH`: a type's, a collection's or a Blender module's attribute, a bmesh operator, an enum value set or
    passed as a keyword, a collection key); a wrong value, a read-only attribute or the script's own NameError isn't.
    The repairs don't count (they show Chimera's crash and dodge the name). Why: on the 30 steps that reached qwen3.8
    the two models fail on such names about as often (38 of gpt-oss's 120 tries, 21 of qwen3.8's 60), in the same
    families (an action's fcurves, the compositor's tree, video output, SVG import). With the fence alone it fires on 4
    steps (smoke4 n-blender-0000-01 r1 s3 and r2 s3, and blender-0008-00 r1 s4 in smoke3 and smoke4): -8 calls,
    -647 s (smoke4 517: 10% of its Blender model time). Its cost there: qwen3.8's 2 kept pieces of blender-0008-00 r1
    s4, neither an example (the failed-dependency cap dropped both): smoke4's misses its getattr probes and its keys
    stay Bezier (the audit's wrong piece, now `attr_miss`), smoke3's reaches the channelbags after a dead legacy probe
    and is plausibly right. With the API facts in the notes the rule should fire less, mostly on names no fact covers.
  - *More room for qwen3.8's thinking: `num_predict` 12,288* (was 8,192; one passing reply of the third smoke used
    8,118). The 9 length-outs had thought 6,499-7,399 tokens and written 0-797 of content, and qwen3.8's gate-pass rate
    doesn't fall with its thinking (under 2,000 tokens 2 of 8, 2,000-3,000 3 of 16, 3,000-4,000 3 of 14, 4,000-5,000
    2 of 12). Each such call costs at most 4,096 tokens more, 54-66 s at its own 62-76 tok/s. Ollama 0.40.1 counts
    thinking and content together in num_predict, so there is no thinking-only cap; think false would make it
    another sampler, which nothing offline measures. A Blender prompt (up to about 8,300 tokens) plus 12,288 fits
    qwen3.8's fixed 32,768 num_ctx, under the client's runaway guard (16,384); the 6,144-token content cap stays. The
    key changes, so no stored qwen3.8 reply replays.
  - Code steps are unchanged. A Blender step past its batches records `step["sampler"]` ({"heard", "third",
    "second": "asked" or "skipped", and "why" "api_faults" and "api" when skipped}); the report counts it.
- **The handoff fence (`normalise.handoff_fence`, `task.normalised`, `Round.precheck`).** gpt-oss often writes the
  handoff block's language as its first line: an untagged fence, then "handoff", then the three key lines, which the
  validator doesn't read as a handoff (handoff_missing: 11 of the fourth smoke's 12 such Blender tries, 8 of the
  third's 9, 9 of the second's 10). That block, at the very end of the reply, becomes a ```handoff block, and a
  closing fence glued to the end of the assumed line (handoff_unclosed_end) goes on a line of its own; only those two
  forms, only when the block holds the three key lines and nothing else, and only if the validator then reads the
  contract's fenced block, closed and last, with no handoff issue. A handoff in a docstring, keys inside the python
  block, a "handoff" label above a plain block (4 distinct files tries, handoff_unlabelled) or a plain block with no
  label stay failing, and a lone step's reply is left alone. Characters and lines only; the raw reply stays in the
  cache, and `c["normalised"]` gets "handoff_fence" when it fixed something. On every stored try of smoke2-4 in every
  code mode it changes 30 (9, 9, 12; all gpt-oss's, all Blender), 28 of them then validate (smoke4's other two save
  the file or are too long) and, through the budget part's gate, 3 passed: smoke2 n-blender-0002-01 r1 s3 c3, smoke3
  blender-0008-00 r1 s1 c3 (its step was dropped, which gave s2-s5 a failed dependency) and smoke4 blender-0002-02 r1
  s3 c3 (a second pass in a step its batch kept). Through the integrated gate and Round.gate (dep_honesty after it) 2
  pass, smoke2's and smoke4's: smoke3's blender-0008-00 r1 s1 c3 fails `marker_misused`, softly, and smoke3's
  failed-dependency variant of n-blender-0000-01 r2 s3 (c1) passes the gate but fails `dep_claimed:s2`, so the fence
  wins no smoke3 example (Integrated; Independent checks). hints.echoed_note, version_leak and notes_leak give the
  same answer on all 30 before and after.
- **The report (`report.py`: `projection`, `night_failed_deps`, `samplers`, `_sampler_lines`, `_capped_lines`;
  `build._stats`' `failed_dep_capped`).** The build's stats list each example the failed-dependency cap dropped, and
  the projection counts back what a night's build would keep at the same share: the cap floors `0.1 * others / 0.9`,
  so a smoke's 4 Blender examples allow none, where a night's 640 allow about 71. A mode keeps min(natural, 0.1 *
  others / 0.9) at scale, and only a kind with built examples gets it back. Smoke4: Blender 4 (+0.44) examples,
  1,242.8 s each before and 1,118.9 now, 270.3 h to the plan's 1,700 before and 248.3 now (208.0 and 191.0 at 2);
  smoke3 314.0 h and 287.7; smoke2, rebuilt with today's filters (27 of its 47 examples), 174.4 h either way (its
  stored REPORT.md: 92.6 h). The cap itself is unchanged. REPORT.md gets a line per mode and
  sampler (first samples, told samples, the second sampler, repairs, variants: calls, model seconds of its own calls,
  gate passes, steps kept with an example to give, built examples, examples per 1,000 s) and, for records that have
  it, the second sampler's budget. On smoke4, Blender: first samples 42 calls, 1,284 s, 6 passes, 1 example (0.78);
  told 38, 1,153 s, 7, 2 (1.73); qwen3.8 24, 1,756 s, 5, 1 (0.57); repairs 11, 360 s, 2, 0; code: first samples
  20.62 examples per 1,000 s, qwen3.8 6.48. The report also counts `build_tells` (by used and unused, as
  `ctx_channel`), `handoff_exempt` (worked out from stored verdicts, so older records count too: 5 tries of 2 steps on
  smoke4, 2 of them kept) and `scene_overruled`.
- **New record keys.** The Blender gate's `facts` and `facts_tell`; measured `silent.missed` (only when attr_miss
  fires) and `doubled` rows, a depths row's `one_way`; a judge record's `rule` "overruled" and `overruled`; a step's
  `sampler`; a candidate's `normalised` "handoff_fence"; `sft/stats.json`'s `failed_dep_capped`; report
  `after_audit`'s `build_tells`, `handoff_exempt`, `scene_overruled`, and report `samplers`.
- **Integrated (Nov 6, the Studio, offline, binary `458dcbfc…`, Blender 5.2.2 and 5.0.1 sandboxed).** The four
  patches went in in the order facts, tells, judge, budget. Where two touched one thing, both are kept:
  `blender_gate.SOFT_GATE` is SOFT_MEASURED (with judge's `doubled_depth`) plus `ctx_channel`, facts' `attr_miss`
  and tells' `FACT_REASONS`, and `_hard` excuses `FACT_REASONS` by prefix; `task.SOFT_IF_USED` holds `ctx_channel`,
  `attr_miss` and the four `FACT_REASONS`, `SOFT_REASONS` gains `doubled_depth`, and `_BLENDER_STAGES` ranks
  `attr_miss`, the four and `doubled_depth` at the alone stage; `report.NEW_GATES` is the old list plus `attr_miss`,
  `doubled_depth` and `blender_gate.FACT_REASONS`, `_GEOMETRY` gains judge's doubled row, and report imports both
  judge's `judges` and budget's `FAILED_DEP_CAP` and `natural_failed_dep`; piece_check's and measured_check's
  docstrings list every new reason and record key; `task.py`'s docstring has budget's sampler sentence and tells' soft
  reasons; `test_the_soft_reasons` pins the merged sets. Two areas had each added a class `AfterTheFourthSmokeTests`
  to `test_datagen_report.py`, budget's after the `if __name__` block, so the second hid the first: they are one class
  now (budget's helpers `call`, `meta` and `write` with it), before the block. The functions two areas changed (each
  `Round` method by one) are those, `blender_gate.measured_check`'s code (facts and judge), `piece_check` (tells' code,
  the others' docstrings) and `report.after_audit` and `_format4_lines` (tells and judge), every one with both areas'
  lines, and `blender_gate.TELL_FORMS` keeps geometry's forms last
  (`test_this_rounds_tell_wordings_are_known_to_the_echo_check` has every area's). DATAGEN_FORMAT went to 5 (above),
  with `test_datagen_run.py`'s and two other tests' pins, and `run_datagen.sh`'s and `run.py`'s words for the fifth
  smoke.
  - *Tests.* The whole worker-model folder in three foreground parts that cover every module, with `CHIMERA_BIN`:
    `test_datagen_blender`, `test_datagen_blender5` and `test_datagen_run` 122 in 4.5 minutes, the other 18 datagen
    modules 710 in 2.8, the 22 others 350 in 2.1: 1,182, all passing, none skipped (in the real tree, so
    `test_the_users_home_is_unreadable` passes too). The datagen tests on their own, one run: 832 in 7.3 minutes, all
    passing. `tools/check_contract_parity.py`: 42 texts and 6,291 requests, 0 differ; `tools/check_join_parity.py`: 0
    differ. `app/` is byte-identical to the tree before the round.
  - *Requests.* Every stored step and repair request of smoke2-4 made again through the binary from its stored
    inputs (206: 78, 62, 66): the base tree and this one give the same bytes for all 206, and smoke4's 66 are byte for
    byte the stored ones (smoke2's and smoke3's other 38 and 30 were made by older binaries, as before the round). Every
    stored Blender teacher call made again (350: 122, 105, 123; under the base tree all 123 of smoke4's give the stored
    cache key): each teacher copy is the stored request plus notes under HEAD and nothing else. With the stored runs'
    failure lines the notes change on 71, 63 and 67 calls (camera note, output note, the facts, fixes on failure
    lines; every Blender qwen3.8 call's key changes anyway, by `num_predict`, and until the checks every code one's
    did too); with the integrated gate's lines told in their
    place, on 84, 73 and 87 (smoke4: 89 build_facts and marker lines, 69 failure lines with a fix, 2 `doubled_depth`
    and 2 `attr_miss` lines), growing by about 520-660 characters on average, at most 2,078.
  - *Verdicts.* Every stored Blender try of smoke2-4 gated again with the base tree and this one (smoke4 from its cached
    runs, smoke2 and smoke3 run again sandboxed, 145 runs; the base tree reproduces smoke4's 92 stored verdicts of 92):
    15, 20 and 26 of the 87, 79 and 92 gated tries change, and the fence lets 9, 9 and 10 more reach the gate (1 passes
    the gate in each run: smoke2's n-blender-0002-01 r1 s3 c3, smoke3's n-blender-0000-01 r2 s3 failed_dep variant c1,
    smoke4's blender-0002-02 r1 s3 c3; smoke3's blender-0008-00 r1 s1 c3, which passed the budget part's gate, now
    fails `marker_misused`, softly, since its step has dependents). Through Round.gate, which runs dep_honesty next, 2
    pass (smoke2's and smoke4's): smoke3's variant c1 credits "sofa object created in step s2", the dependency it leaves
    out, and fails `dep_claimed:s2` (the independent checks, replayed through Round.solve). smoke4's reasons added:
    dead_output_key 11, marker_misused 7, provides_missing 7, silent_default 7, attr_miss 3, doubled_depth 2,
    handoff_long 1; lint:attr removed on 2. Of smoke4's kept pieces 7 that passed now fail: blender-0002-02 s1 c5
    (doubled_depth and marker_misused, soft: Z26, bad, a built example), n-blender-0000-00 s1 c3 (dead key, soft), s2 r0
    (silent default, soft), s4 c5 (dead key, hard: nothing depends on it), blender-0008-00 s3 c2 (provides_missing and
    marker, soft), s4 c4 (attr_miss, soft) and n-blender-0000-01 r2 s4 c0 (silent default, hard: Z12, weak, the other
    built example); blender-0008-00 s5 r1, a soft keep already, gains three. In smoke2 8 kept pieces change, all graded
    bad or weak (bad: X05, X07, X20, X45 and X58 and their twins; weak: X19, X65 and X77, and two twins); in smoke3 3,
    none graded. Of the 7 graded ok entries none gains a reason. The two parts meet on the judge: of smoke4's 4
    overruled rejections, 3 (n-blender-0000-00 r1 s1 c0, n-blender-0000-01 r1 s2 c0 and r1 s4 c5) now fail at the gate
    first (a dead key; provides_missing and a silent default; a dead key and a silent default), so only
    n-blender-0000-00 r1 s2 c0 still wins its example by the overrule (until Nov 6: its position claim names no thing,
    and no reader reads its stools' ± point, so the rejection stands now). And the sampler: with the integrated gate's
    reasons the third batch fires on 11 steps (smoke2 3, smoke3 3, smoke4 5), not 13, measured through Round.solve with
    dep_honesty and the judge (12, smoke4 6, by recombining the stored reasons, which left out dep_honesty: smoke4's
    blender-0008-00 r1 s2's fenced c0 and c3 both get `dep_claimed:s1`, a fault in common): n-blender-0000-00 r1 s2
    drops out in all three runs, smoke3's n-blender-0000-01 r2 s3 comes in, and qwen3.8 is skipped on the same 4. Six of
    the 11 rested on a told build fact or ctx_channel that `fault_keys` missed (fixed by the checks: 5, smoke2 2, smoke3
    2, smoke4 1).
  - *Echo.* Every new wording against the stored records with this tree's hints: 0 of the 447 distinct stored replies
    of smoke2-4 (with their requests) and 0 of the 61 kept targets refused, before or after; and every stored reply of
    a told call checked against that call's own told lines as the integrated gate would tell them (precheck's way,
    192 calls), 0 refused.
  - *The scene judge.* All 61 stored Blender judge calls of smoke2-4 get new messages (24, 18, 19), none of them with
    the goal (all 61 before); 6 of the 8 rejections are overruled (smoke2 1, smoke3 1, smoke4 4), 2 since Nov 6
    (smoke4's two output forms; Decided (Nov 6), below).
- **Independent checks (Nov 6, the Studio, offline, binary `458dcbfc…`, Blender 5.2.2 and 5.0.1 sandboxed, no model
  call).** Checkers of the four parts, the integration and the rules, then a verifier, read the round against the
  stored records: 33 findings held, 27 distinct (6 found twice or three times): 15 defects, fixed here with a test each
  that fails on the round's tree, 8 doc slips, fixed, and 4 decisions (below, Left). Fixed:
  - *The lint's guards (`rna_lint._guarded`, `_ops`, `_hardened`).* A hasattr or getattr on bpy.ops or one of its
    groups is always true in both Blenders (a group answers any name; the call raises "could not be found"), so it
    guards nothing: the lint excused `if hasattr(bpy.ops.import_scene, "obj")`, and smoke4's blender-0008-00 s1 c5,
    its `wm.svg_import` put behind such a probe and its marker taken out, passed the gate with the dead operator on a
    path the sandbox never reaches (now `lint:op`, as stored).
    The else or elif behind a hasattr whose name every version has is checked again: its receiver may be None
    (`scene.camera`, a `.get()`), and a typo there ran clean on the factory scene and crashed without a camera. An
    assert, or a raise when the name is missing, on a name no version has keeps its finding: that is a certain crash,
    and the fcurves fix hangs on the finding (in every layout since the second checks, below). A return, continue or
    break stays a guard, and so does an assert on a name some version has. The 289 stored codes lint the same; of the
    eval's 763 replies one dead else's error comes back (12 lose an error, 19 findings, with the rule: since Nov 6 the
    eval's own lint has none, Decided below).
  - *The notes (`hints._line`, `failure_lines`, `silent.refit`, `PLAN_STEPS`).* A fix ends a Blender step's failure
    line only (a code step whose own `import_svg` crashed was told the SVG operator; none stored). A hidden-error
    tell (silent's SWALLOWED and SWALLOWED_ATTR) keeps its end beside a fix, its quoted error and then its source cut
    instead, in up to the tell's own 299 characters: cutting at 240 had taken away "the piece's own except caught it"
    and what to do (smoke4's blender-0008-00 s5 r1 video line, heard by c4 and c5; SWALLOWED_ATTR's fixed words alone
    are 165 characters, so with the fcurves fix it can't fit 240 at all). OUTPUT_NOTE's and VALUES_NOTE's fills
    reach s8, since Chimera's cleanPlan keeps 8 steps (a run across SETTINGS_s8 was refused by nothing; no stored
    plan has 8). CAMERA_NOTE no longer calls the start-up scene empty (it holds a cube and a light), and the SVG fact
    says import as curves is `import_curve.svg` (wm's SVG operator imports Grease Pencil). Notes on the 350 stored
    Blender teacher calls change on 38, 37 and 39 (the two wordings and those two calls' line); no request changes.
  - *The stand-in reader (`stand_ins`).* Filler words before a key a variable gives (for, missing, created, object,
    setting, key, name and the like: `FILLER`) are no key, and "for" at the marker's end reads the print's second
    argument: 11 of the first smoke's 258 Blender tries were read as marking "missing", "created", "object" or
    "setting", each a correct marker a told batch would have been asked to drop; now none is, one reads its real key
    (Pulse_Curve), and smoke2-4's markers read the same (the fourth smoke's "input {name} not found" still reads
    "input"). A marker printed with %, + or .format counts. A stand-in helper that prints the marker with its
    parameter as the key covers the keys passed to it (`vals.get("w") or _s2_stand_in("w")`), and a marker loop in the
    function around a read, or in one that calls it, covers it (a lambda or a nested get() in build_s2, a top-level
    _s2_value(ctx, key); since the second checks only the values' own loop, below); a marker with a literal key still
    covers only its own function, so the fourth smoke's GPU fallback in a build_s4 covers no nested get(). chimera_
    is stripped on both sides; a name bound to ctx["values"] is the binding function's (a helper's parameter of that
    name is its own dict, unless every call fills it with ctx["values"], since the second checks); a loop over a
    literal list reads its strings as keys. The checkers' hand-made pieces (D, E, A, B, C, F-H, X1-X3, X5) run
    strict alone and joined in both Blenders and pass the gate now; the round's gate failed each on silent_default or
    marker_misused.
  - *What the build drops (`blender_gate.dead_output_key`, `_loaded`, `INPUT_FILES`, `warning_faults`' earlier).* A
    `*_filepath` key the piece hands to a loader (images.load, a library load, an import, open, append or link
    operator) or whose value is a font or a sound is a file it reads in, not a dead output (a texture the step asks
    for was told "leave that key out"; images, .exr, .hdr and .blend can be either, so only the loader tells). The
    build's filter reads the same way: on every stored try of smoke-smoke4 nothing changes. provides_missing's
    stand-in tell goes only to keys a dependency hands on, or to any with a dependency missing; a get-or-create of the
    step's own object gets the plain tell, which lists it.
  - *The overrule (`judges._OTHER`).* Its n't stood behind `\b` and matched no contraction, and a claim beside a thing
    never made, omitted or left out, a count in words, a turn, a float, an overlap, a place on or beside another
    thing, or a shape was overruled. Those words keep a rejection now (the tests' fixture mark moved beside the reason:
    its "never" is one). The 7 overrules of the 130 distinct stored verdicts are the same; of the checkers' 24 and 9
    hand-written mixed reasons none is overruled (23 and 9 were).
  - *doubled_depth's reader (`geometry._one_way`, `_SIDE_AFTER`, `_BOTH`, `_extruded`, `DOUBLED_MESH_TELL`).* A side
    counts only right after the length ("0.08 m in the negative Z direction", "0.1 m downward"; a rotation's "about
    +X" or a later "and move it down" said none; a comma, a bracket or "only", "straight" may come between since the
    second checks, below), a plane a thing stands on and a facing verb are no mesh extruded,
    "both directions" or "each side" isn't one way, and a thing that is no curve or text is told without the curve's
    fact (a new tell form, registered with the echo check and in `TELL_FORMS`). The checkers' 8 correct pieces pass in
    both Blenders now, the fourth smoke's bad Pulse_Curve still fails, and the 261 held-out steps' and every stored
    step's readings are the same.
  - *The sampler (`task.SECOND_OPTIONS_CODE`, `fault_keys`).* The 12,288 room is Blender's only, as designed: a code
    step keeps 8,192, so smoke4's and smoke3's 18 code-mode qwen3.8 calls each give their stored keys again (0 of 18
    under the round's tree) and the fifth smoke replays its code steps from the cache. A told build fact or
    ctx_channel that came back is a fault in common: through Round.solve the third batch fires on 5 steps (smoke2 2,
    smoke3 2, smoke4 1, n-blender-0000-01 r1 s4, whose second batch the validator stopped) instead of 11; on 4 since
    Nov 6, when a batch stopped short of the earlier one is no longer heard (Decided (Nov 6), below).
  - *Docs and the report.* The README's guard paragraph after the DYNAMIC_STRUCTS sentence it had cut off; step 6's
    attribute misses that are the attr_miss reason no longer counted as facts only; the fence's and the sampler's
    figures measured through Round.solve (above, and normalise.py's docstring); smoke2's projection; the functions two
    areas changed; the scene judge's listing test named for what it checks.
  - *Measured on the stored records.* Every stored Blender try of smoke2-4 gated again with the round's tree and this
    one (288 tries, all runs cached): no reason changes, and one tell does (smoke4's n-blender-0000-01 r1 s3 c1, whose
    "target" marker now matches the chimera_target it makes, a try its lint fails first). Every Blender step replayed
    through Round.solve (stored replies, no model): only the 6 sampler steps change; smoke4's 26 code steps and
    variants (19 and 7) and its 6 section steps replay strictly from the stored calls (9 files steps missed their
    qwen3.8 call under the round's tree), and so do smoke3's 26, and keep what they kept. The
    echo check refuses 0 of the 447 stored replies and 0 of the 61 kept targets, before and after, and none of the 350
    told calls' stored replies; no new wording shares a run with Chimera's Blender rule for s1-s8 or with any of the
    243 distinct stored requests.
    Still DATAGEN_FORMAT 5: no format-5 record exists yet (smoke5 hasn't run), and each fix is to how a format-5 run
    judges and draws.
  - *Tests.* The whole worker-model folder in the same three foreground parts, with `CHIMERA_BIN`, in the real tree:
    `test_datagen_blender`, `test_datagen_blender5` and `test_datagen_run` 122 in 4.4 minutes, the other 18 datagen
    modules 723 in 2.8, the 22 others 352 in 2.2: 1,197, all passing, none skipped (15 new, 13 of them datagen's),
    `test_the_users_home_is_unreadable` among them; in the scratch copy the same, but for that one, which reads a copy
    under /private/tmp. `tools/check_contract_parity.py`: 42 texts and 6,291 requests, 0 differ;
    `tools/check_join_parity.py`: 0 differ, in both trees. `app/` is untouched.
- **Decided (Nov 6, the Studio, offline, binary `458dcbfc…`, Blender 5.2.2 and 5.0.1 sandboxed, no model call).** The
  main session decided the four questions the independent checks left, on the verifier's and the repairer's options.
  Each has a test that fails on the tree before (run there with the new tests: 11 failures and 3 errors) and passes
  here. No teacher note, tell or rubric wording changed, so the echo check has nothing new to register, and no
  request, prompt or Chimera text changed.
  - *The lint's guard rule is data generation's only (`rna_lint.Linter(facts, guards=False)`; facts-4, integ-7,
    safety-4).* The flag turns on `guards()` and `Linter._guarded` with the checks' refinements (the bpy.ops probe, the
    hard facts, the else behind a name every version has); off, the Linter is the one before Nov 5. `datagen/run.py`,
    `BlenderGate`'s own linter (made when none is given) and the test env that stands for run.py's pass
    `guards=True`; `runner/score.py`, `step_eval.py`'s `lint_facts` (which `task_eval.py`, `freeze.py` and
    `rescore.py` use), `tools/rna_dump.py`'s lint command and `lint_source` keep the default. Why: the round was
    approved as data generation only, and `freeze.verify` is a pass/fail gate on W1's frozen inputs, which every
    model's W1 score stands on. Measured: the eval's 763 distinct stored Blender reply scripts, its 64 verified
    scripts and `freeze.verify` on the 11 stored W1 dependency replies (blender none, so the lint decides what follows
    the validator and the join) give base's findings and verdicts, every field (0 differ); the 18 stored eval runs'
    lint figures are base's (on the 5 the rule moved, `lint_errors_mean` is 2.72, 2.59, 0.67, 1.62 and 2.37 again);
    the gate's linter gives the round's findings on the 289 distinct stored Blender codes (331 tries; 0 differ), and
    `guards=True` the round's on every eval reply and verified script too.
    `test_the_evals_own_passing_scripts_are_clean` expects w3-19's one warning from the default Linter again, as base
    did, and none with `guards=True`; new:
    `GuardedAccessTests.test_the_rule_is_data_generation_only` (the guarded class lints with `guards=True`) and
    `ReadersTests.test_the_gates_lint_has_the_guarded_read_rule` in `test_datagen_blender.py`.
  - *Every values step's long provides line is left as it was (`blender_gate.warning_faults`; tells-3, safety-3).*
    `handoff_long` on a `hints.values_step`'s provides line is exempt whatever the line's form: no reason, no tell, and
    none of the other build facts' reasons (`waived`), which is how every values step was treated before the round;
    `plain_names` now only picks the long-line advice for a step that isn't a values step, and the report's
    `handoff_exempt` counts every form. Why: the user said nothing may change how a values-only step failing
    `handoff_long` is treated, and the round's plain-list rule made it depend on how the line is written. Measured,
    through the real gate in both Blenders: hand-made values pieces with 19, 20, 25 and 30 keys under provides in six
    forms (a plain list, behind 'ctx["values"]:' or 'ctx["values"] keys', grouped, with a note after it, with values;
    24 pieces, 341-853 characters) all pass, strict alone and joined, with no reason and no tell, exactly as base's gate
    (reasons, ok and tells equal); the round failed the 20 that aren't plain on `validator_warning:handoff_long` with
    "give only the exact names". The same lines on a step that isn't a values step (12 pieces) get the reason and
    its tell, as in the round. On the stored records `warning_faults` changes on 0 of smoke2-4's 341 tries with a
    verdict (their long values-step lines are all plain; `handoff_exempt` stays 1, 1 and 5 tries) and on 5 of the
    first smoke's 257 (3 steps, lines like "SETTINGS_s1 (all dimensions, colours, render settings); ctx["objects"]
    keys: ...", 385-580 characters), which the round's gate would have failed and told to shorten. Tests:
    `test_a_values_steps_long_list_is_left_as_it_was` (was `..._plain_list_...`; six forms, and each on a step that
    isn't a values step), the gate's `test_a_silent_default_and_the_values_steps_list` (a lead and a note, in both
    Blenders), the report's `test_build_tells_and_the_values_steps_long_list` (a lead counts).
  - *An overrule rests on a measurement (`judges.overruled(verdict, plan, i, scene)`, `claims`, `readings`;
    `task.Round.judge` passes the plan, the step and the try's gate "scene"; judge-3).* A size claim is overruled only
    when the thing it names (what is left of its clause once the claims and the neutral words are out, `claims`)
    is a thing `blender_gate.asked_sizes` read every side of (a side named by a variable, "sofa_dim (length)", is
    measured by nothing), and a position claim only when it is one `geometry.asked_places` read a point for, by the
    reader's own words for the thing (since the second checks: the claim's words all among the reading's, and no other
    object of the judge's listing going by them; one shared word until then, below); a claim that names no thing
    ("all placed at the origin") only when every object of the judge's listing is one a reading is for (its name's
    words all among the reading's; `geometry._match`'s most shared words until then); with no reading, or no listing,
    it stands. Output-form claims keep their rule.
    Why: a single-dimension fault ("radius 0.6 m instead of 0.3 m") or a relative place is measured by nothing else,
    so overruling it could make a true catch a bad example, and losing an example costs less than a bad one. Measured
    on the 130 distinct stored scene-judge verdicts of smoke-smoke4 (48 rejections): 3 overruled instead of 7, the
    output forms (smoke's and smoke4's n-blender-0000-00 r1 s1, smoke4's n-blender-0000-01 r1 s4 c5). Four go: the
    kitchen's position claim in smoke2, smoke3 and smoke4 (n-blender-0000-00 r1 s2 c0: it names no thing, and the
    listing's 4 stools have no point read, the step's "(±0.6, ±0.3, 0.5)"; smoke4's c0 has them 0.28 m into the floor,
    the weak example the overrule won), and smoke4's sofa (n-blender-0000-01 r1 s2 c0, "length 2.0 m instead of
    required 2.2 m": its length is sofa_dim, a variable, and the claim is false, 2.0 being what s1's piece sets). The
    verifier expected only the sofa's to go; the kitchen's go too because no reader reads a ± point. None is overruled
    anew. Of the checkers' hand-made reasons none of 8 single-dimension sizes and 8 relative places is overruled (the
    round overruled 7 and 5), while the read controls (a triple, a point) still are. Through Round.solve (stored
    replies): the kitchen's c0 is a judge rejection in all three runs, so smoke2's and smoke3's soft keep (on
    ctx_channel) and smoke4's built example are gone (the replay stops there: no judge verdict was stored for a later
    try, and smoke4's runs out at qwen3.8), and smoke4's n-blender-0000-01 r1 s2, a soft keep, is dropped (its other
    stored tries all failed), which in a run takes it from s3 and s4. The docstrings of `overruled` and `Round.judge`
    say what it rests on. Tests: `OverruleTests.test_an_overrule_rests_on_a_measurement` (the stored sofa and kitchen
    steps and listing, the checkers' cases, the no-thing claim's listing), the stored overrules on a step that reads
    them, and `SoftKeepTests.test_a_scene_rejection_resting_on_a_size_or_a_place_alone_is_overruled` (a measured mock
    plan, and the mock plan's one-sided floor, which stands).
  - *A later batch is heard only when it got as far (`task.heard`; budget-3).* Besides no fault in common and neither
    batch empty, the best `_progress` among the later batch's tries must be at least the best among the earlier's.
    Why: a batch stopped short of where the earlier failed says nothing of the notes, and its new faults are only its
    own; it is the round's `_progress`, and exactly the case of the one firing the checks left. Measured through
    Round.solve on the stored replies (the repairer's replay, its fallback by position): the third batch fires on 2, 2
    and 0 steps of smoke2-4 instead of 2, 2 and 1 (smoke4's n-blender-0000-01 r1 s4 goes: its first batch got to
    progress 12, its second, too_long, to 2), and qwen3.8 is skipped on the same 0, 1 and 3; on that step qwen3.8 is
    asked instead (its stored draws fail, a strict alone run and dead_output_key with silent_default, so it is dropped
    either way). Every other replayed step's sampler, kept and tries' reasons are the round's, but for the overrules'
    four. Test: `SamplerBudgetTests.test_a_batch_stopped_short_of_the_earlier_is_not_heard` (that step's shape).
  - *Tests.* The whole worker-model folder in the same three foreground parts, with `CHIMERA_BIN`, in the real tree:
    `test_datagen_blender`, `test_datagen_blender5` and `test_datagen_run` 123 in 4.3 minutes, the other 18 datagen
    modules 725 in 2.7, the 22 others 353 in 2.1: 1,201 (848 datagen, 4 new), all passing, none skipped,
    `test_the_users_home_is_unreadable` among them; in the scratch copy the same, but for that one, which reads a copy
    under /private/tmp there. `tools/check_contract_parity.py`: 42 texts and 6,291 requests, 0 differ;
    `tools/check_join_parity.py`: 0 differ (1,186 replies, 463 task joins), in both trees. `app/` is untouched.
- **Second checks (Nov 6, the Studio, offline, binary `458dcbfc…`, Blender 5.2.2 and 5.0.1 sandboxed, no model
  call).** Three reviewers read this tree, after the repairs and the decisions; each repro was run again and none was
  refuted: 13 findings, 12 distinct, 9 defects, fixed with a test each that fails on the tree before (11 tests, 24
  failures with their subtests there), and 3 doc slips, fixed. Fixed:
  - *The stand-in reader (`stand_ins`: `_under_values`, `_looped`, `_binder`, `_keyless`, `_Reader.param`).* The
    repairs let any marker with a variable's key, or none, in build_sN cover a silent default in a nested get(), a
    lambda or a helper it calls, and in stored pieces that is mostly an object's marker loop (66 of the 137 such
    markers of smoke-smoke4 sit in a build_sN that tests only ctx["objects"]): Z12 (smoke4's n-blender-0000-01 r2 s4
    c0, the case silent_default was made for) with four lines of one added passed the gate in both Blenders. Now only
    the values' own marker loop (under a ctx["values"] test) covers a read in a function around or called, and the
    keys it loops over (a literal list, SETTINGS_sN's) wherever they are read; any keyed marker in the read's own
    function covers it, as in the round; a marker with no key covers nothing. A key is handed to a stand-in helper only
    as the same name bound the same way (two loops naming their variable k had excused each other); a helper's
    parameter every call fills with ctx["values"] is ctx["values"] (`_s3_powers(vals)` reading `vals.get(...)` passed;
    `_s3_powers(ctx["values"])` passed in the round too); a stand-in helper may print its key through repr(), str() or
    a .format keyword. On a step with no dependency a marker with no key is marker_misused, quoted by its own words
    (a dash before them, "chimera: stand-in – GPU unavailable, falling back to CPU", read as no key). Through the real
    gate in both Blenders (cached runs), of the reviewers' 17 hand-made pieces, all strict alone and joined, the 7
    silent defaults fail on silent_default, the 8 correct ones pass, the control fails on marker_misused, and the dash
    GPU fallback on a step with dependencies still passes (Left); Z12's variant fails again, and every earlier
    checker's piece (A-N, X1-X5, V19-V30) reads the same. Of the 548 distinct stored tries of smoke-smoke4 5 change,
    all the first smoke's keyless markers on steps with no dependency (GPU, DOF, SVG, node groups, "generated
    blender_script"; none kept, each failed already).
  - *An input file through a helper (`blender_gate._loaded`, `_reaches_loader`).* A key passed to a function of the
    piece whose parameter reaches a loader, or its value passed so, is a file read in
    (`_s3_image("shade_texture_filepath")` was told "leave that key out"); 0 stored tries change.
  - *The overrule's match (`judges._read_for`).* A claim's thing rests on a reading only when its words are all among
    the reading's and no other object of the listing goes by them, and a no-thing claim only when every listed
    object's words are among a reading's: one shared word had overruled "the side table is too big" on the coffee
    table's size, "the sofa cushions", "Chair_Main" (Desk_Main read), "Vase_Right" (Vase_Left's point), the coffee
    table's legs, and "the sizes are wrong" beside a sofa cushion. A part named after the read thing still counts. The
    130 stored verdicts give the same 3 overrules.
  - *doubled_depth's side (`geometry._SIDE_AFTER`, `_PHRASE_END`).* A comma, a bracket or a word that is no verb of
    its own (only, straight, pointing, going) may come between the length and its side, and a later bevel's "each
    side" is no both ways: the repairs had dropped six wordings the round read, and smoke4's bad Pulse_Curve piece
    passed under four of them in both Blenders (doubled_depth again now). The 261 held-out steps, the 2,738 corpus
    steps (42 readings, 19 one way) and every stored step read the same.
  - *The gate's guard rule (`rna_lint._everywhere`, `guards`).* A probe on bpy.context was read as a name no version
    has (its members are filled in at run time, no RNA property), so its whole branch was excused, though the probe is
    true and the branch runs in both Blenders; and a certain crash kept its finding only after the if: now also in its
    other branch, before an else that raises, in an assert's `and` and in a raising if's test. The default Linter is
    untouched: on 2,673 collected scripts (the eval's 1,316 blocks and 776 picks, 64 verified, 18 frozen, 499 stored)
    base's and this one's give the same findings, and the guarded linters before and after too.
  - *Docs.* smoke4's code replay (26 code steps and variants, 6 sections), freeze's stored verdicts, and the README's
    "would all be overruled" (2 since Nov 6).
  - *Measured.* Every stored Blender try of smoke2-4 gated again by the tree before and this one (288 tries, all runs
    cached): every row the same, field for field; through Round.solve (stored replies, fallback by position) the third
    batch fires on 2, 2 and 0 steps and qwen3.8 is skipped on 0, 1 and 3 in both, every step the same. No wording, note,
    tell or request changed (every datagen constant is the same), so the echo check has nothing new.
  - *Tests.* The whole worker-model folder in the same three foreground parts, with `CHIMERA_BIN`, in the real tree:
    `test_datagen_blender`, `test_datagen_blender5` and `test_datagen_run` 123 in 4.3 minutes, the other 18 datagen
    modules 733 in 2.7, the 22 others 354 in 2.1: 1,210 (856 datagen, 9 new), all passing, none skipped,
    `test_the_users_home_is_unreadable` among them; in the scratch copy the same, but for that one.
    `tools/check_contract_parity.py`: 42 texts and 6,291 requests, 0 differ; `tools/check_join_parity.py`: 0 differ,
    in both trees. `app/` is untouched.
  - *Left.* A marker with no key on a step with a dependency is still unjudged (13 of the first smoke's tries, 10 of
    them "– Acme_Logo not found, ..."; none in smoke2-4): reading the word after a dash as the key would read prose
    ("no", "could", "creating") as keys and tell a stand-in for a dependency's object to go. The main session left
    it so (Nov 6) and had the report count it: `stand_ins.keyless` lists a piece's markers with no key, and
    `report.after_audit`'s `keyless_markers` ({"tries", "steps", "kept"}, a REPORT.md line when it has tries) counts
    them on steps with a dependency: the first smoke 13 tries of 6 steps, none kept; smoke2-4 none. If the fifth
    smoke shows the form there, an identifier after the dash ("– render_device") can be read as the key. With it
    (2 new tests) the whole folder is 1,212 in the real tree (858 datagen), all passing in the same three parts, none
    skipped, and both parity tools 0 differ. A shorter claim with no listing ("the table is too big", a coffee table read and a side table
    not) is still overruled; with a listing showing both it stands.
- **Left.** Whether the teacher follows the camera and output notes, the facts and the new tells, what a third batch
  writes and what qwen3.8 does with more room can't be measured offline: the fifth smoke shows it. Only interpolation
  is measured, so another guarded miss (auto smooth, EEVEE's soft shadows) now passes the lint and stays a fact; a
  guarded socket lookup is still a lint error; a guard on an alias excuses nothing; `asks_linear` misses "constant
  speed" asks that never say linear. The File Output node's `base_path`, `file_slots` and NodeTree.inputs get no fact.
  `marker_misused` reads the key from the print, so a stand-in named by its object rather than its key fires when that
  dependency is missing (4 stored tries, none kept); ctx["objects"] reads with a silent default aren't judged; a try
  with four fact lines and a crash can push the oldest line of its batch out of the notes (`FAILURES_KEEP` 6). The
  new reasons are hard on a step nothing depends on, so such a step is dropped at the gate when no told try comes back
  clean (smoke4's n-blender-0000-00 s4, its join's combine step), and Z12, the weak valid example, is lost unless a
  told retry is clean. The overrule's classifier is hand-built on the stored rejections, so its counts are in-sample;
  a ± point is read by no place reader, a curve's extrusion side by nothing, and doubled_depth's side path has no
  held-out reading. `_API_CRASH` counts any capitalised type's missing attribute as Blender's (none of the script's
  own in the stored records); `api_only`'s evidence is 4 steps. The projection now divides by a fractional count.
  The four decisions the independent checks left were made on Nov 6 (Decided (Nov 6), above). Since then a claim the
  judge makes on a single dimension, a relative place, a "±" point or a variable's side stands, true or false, and so
  does one that names no thing when the listing shows an object no reader read a value for (smoke4's
  n-blender-0000-01 r1 s2 loses its soft keep to the judge's false sofa length), and since the second checks one on
  another thing that shares a word with a read one: what such claims cost a night is for the fifth smoke to show.
  Also left: FILLER leaves "settings" a key ("chimera: stand-in settings dict" stays a marker_misused), the chimera_
  match lets a marker named after an object the piece makes itself pass (smoke4's "target"), a refitted hidden-error
  line runs past FAILURE_CHARS to 299, and what the second checks left (above): a keyless marker on a step with a
  dependency, and a shorter claim with no listing.
- **Next.** The fifth smoke: the same 8 seeds into `data/gen/smoke5`, its seeds.jsonl and a cache seeded with the
  fourth run's calls copied in first. It pays Blender model time again (every Blender teacher copy whose step names a
  trap, a camera or an output, every scene-judge call and every Blender qwen3.8 call is new; the code steps' qwen3.8
  calls replay from the cache since the checks), and its audit says whether the
  round won the 3-6 Blender examples per smoke the analyst estimated. Then the nights. The values steps' provides
  limit (`handoffLineMax`) stays the user's question.

## After the fifth smoke (Nov 6)

The fifth smoke run (`results/DATAGEN-SMOKE.md`, "Fifth smoke run": the fourth run's 8 seeds into `data/gen/smoke5/`)
built 31 examples instead of 26, Blender 9 instead of 4 at 590 s of model time each instead of 1,243, a projection of
154 h for 1,700 instead of 270, and 6% bad in a blind audit (no Blender example bad, all 9 weak; the one bad new
example a section whose packaging script doesn't parse). Its yield analyst ranked what still held Blender back ("What
holds Blender back now"). On Nov 6 the user approved this round ("Yes, next round") in answer to "Start the small
data-generation round the audit ranked?", after a message that named six changes, all data generation only: the
keyframe slot named in the Blender 5 fact and its fix, a note on the handoff lines' form to every Blender step that
isn't a values step before any sampler runs, a plain print instead of the stand-in marker for a missing input file,
the third told batch retired, a section's python code parsed, and a module-level read of a global ctx flagged. Nothing
in `app/` changed (Chimera's request text, the contract, the validator and its limits, `aloneScript`, the names sheet),
nor hydra's planner, reviewer and Head-check prompts. `handoffLineMax` (300) and `MAX_TARGET_TOKENS` (3,500) are
treated as before, the values steps' waiver of `handoff_long` is exactly as it was and no new note or tell reaches a
values step about its provides line, and nothing here says what `SETTINGS_sN["output"]` holds for a .blend and a
render. It was built in two parts against the same tree and the fifth smoke's binary (`458dcbfc…`), the notes (items
1-3) and the checks (items 4-6), then joined (Integrated, below). Where a section above says otherwise, this list
wins. Every number is offline, on the stored records of smoke2-5 (where said, also the first smoke's and the eval's
stored replies), Blender 5.2.2 and 5.0.1 sandboxed (`pysandbox.run_tool` or the gate's own runner), with no model call.

- **Formats.** `task.DATAGEN_FORMAT` 6, once for the round: a format-5 record was drawn by another policy (a third
  told batch after a heard second one, and the repair and qwen3.8 after it told three batches' failures) and judged
  by other rules (a section whose python block doesn't compile passed; a Blender try with a global ctx read had no
  such reason or line), and every Blender teacher copy is new (the Blender note is in each), so smoke5's records are
  another format's now, as smoke2-4's are: a tasks start makes them again, the build drops them (`old_format`), and a
  finished folder of them is refused. `run.py` and `run_datagen.sh` suggest `--data-dir data/gen/smoke6` for the sixth
  smoke. `blender_gate.RUN_FORMAT` stays 5: no prelude, epilogue, run script or run-cache key changed (`global_ctx`,
  `code_faults` and `stand_ins.for_file` read the code), so every cached run is still good; the integration's
  replays (every gated try of smoke2-5 under both trees, smoke5's steps through `Round.solve`) made no new run.
- **The keyframe slot (`hints.BLENDER5`'s keyframes fact, `KEYFRAMES_FIX`, its patterns in `fix_for`; item 1).** The
  fifth smoke's teacher still wrote `Action.fcurves` on 11 of 121 Blender tries, and 6 more took the channelbag path
  with a wrong slot: None on 4 (n-blender-0000-01 r2 s4 c2-c4 and r0), the action on 1 and a function that doesn't
  exist on 1 (blender-0008-00 s4 r0 and r1), because the fact said "(action, slot)" without naming the slot and "(None
  before its first key)" read as "pass None"; and the failure lines of those 6 ended with no fix, since only
  `Action.fcurves` had one, so the tries after them heard the crash alone.
  - *The fact* now reads: after an ID's first keyframe_insert its F-curves are in the channelbag that
    `bpy_extras.anim_utils.action_get_channelbag_for_slot(action, slot)` gives, slot being that ID's
    `animation_data.action_slot` (`obj.animation_data.action_slot` for an object obj), which that first key sets; the
    channelbag's fcurves hold the keyframe_points. It says no "None". *The fix*: "use
    anim_utils.action_get_channelbag_for_slot(action, obj.animation_data.action_slot).fcurves", 93 characters, so a
    hidden-error tell (`silent.SWALLOWED_ATTR`, 166 fixed characters) still keeps its end beside it within
    `silent.TELL_CHARS` (the most a fix can be there is 101); the fact comes with every line the fix ends, and says when
    to read the slot. It now also ends a line whose text has `'NoneType' object has no attribute 'fcurves'`, `expected a
    ActionSlot type` or `action_get_channelbag_for_action` (the three wrong-slot forms); another None's error gets no
    fix. The old fact and fix are in `hints.RETIRED` (still ours to the echo check).
  - *Checked in both Blenders, sandboxed (`--factory-startup`), 17 of 17 claims in each:* a new object has no
    animation_data before its first key; the first keyframe_insert sets `animation_data.action_slot` ("OBchimera_k");
    `action_get_channelbag_for_slot(action, obj.animation_data.action_slot)` gives an ActionChannelbag whose fcurves
    are exactly keyframe_insert's (location[2] and rotation_euler[0-2]), BEZIER, and LINEAR set on their
    keyframe_points is what plays (rotation 3.1416 at the middle frame); a slot of None gives no channelbag, the action
    passed as the slot raises TypeError, `action_get_channelbag_for_action` doesn't exist; a second object's keys are in
    its own slot's channelbag; a camera data's lens key is through `cam.data.animation_data.action_slot` (the object has
    no animation_data); an action assigned by hand has no slot until keyframe_insert, which keeps that action; a node
    input's key is through `node_tree.animation_data.action_slot`. `tests/test_datagen_blender5.py` runs the fix's own
    expression, as written, on 7 of those in both Blenders (`TheSlotHoldsInBlenderTests`).
  - *The analyst's slot test, again:* every stored Blender try of smoke2-5 whose lint, crash or runs name the keyframe
    API (48 tries: 7, 7, 17, 17), its code patched to the named form (`X.animation_data.action.fcurves`,
    `action.fcurves`, a slot of None or the action, the made-up function, smoke4's iterated `strip.channelbag`), through
    the real gate in both Blenders and dep_honesty as `Round.gate` runs them: no keyframe fault is left on any; 21 pass
    the gate, 17 also dep_honesty (3, 4, 2, 8; the analyst's 6 of 12 on smoke5 is 8 of 17 here). The rest fail on what
    else they do (camera_not_active, dupes, another lint name, silent_default, a seam, handoff_long; dep_claimed where
    s1 was dropped). By step: smoke4's n-blender-0000-00 r1 s3 (a soft keep, c0) and smoke5's n-blender-0000-01 r2 s4
    (dropped) would get an example (c2 of the told batch, c1 of the first); smoke2's, smoke3's and smoke5's
    blender-0008-00 s4 would get theirs from the first or told batch (c2 told; c0 and c1 first batch) instead of from
    qwen3.8 (smoke2's c5 is X07 and Y44, bad; smoke5's c4 is V33, weak). A first-batch win (`ROUNDS["blender"]` is (2,
    2): c0 and c1 hear no failure line, so no fix) rests on the fact's wording alone. The
    ok example on a touched step, smoke3's n-blender-0000-00 s3 c2 (Y39, Z02), comes before its patched c3, so nothing
    good is displaced.
  - *On the stored notes:* the fact reaches the same steps by their words (5, 5, 4 and 5 steps; the new failure
    patterns add none, as every step with a slot fault names keyframes). Distinct stored failure lines ending with the
    fix: 3, 6, 24 and 16 (12 before on smoke5: the 4 new are the wrong-slot lines of blender-0008-00 s4 and
    n-blender-0000-01 r2 s4). The fix is 10 characters longer (93 against 83), so more lines are cut before it ("…": 3,
    3, 8, 5 instead of 2, 0, 1, 1), each keeping its source and the error's type ("'Action' object has no attribute
    'fcurves' (the olde…").
- **Handoff lines before any sampler (`hints.HANDOFF_NOTE`, `hints_for`; item 2).** qwen3.8 is the last sampler, so its
  long handoff lines were never told: smoke5's blender-0008-00 s2 and s3 were kept only as dependencies on
  `handoff_long` (provides 339 and 309 characters, a note in brackets after each name). Every Blender step that isn't a
  values step (`hints.values_step` false), in a plan of more than one step (Chimera's Lone has no handoff), now gets,
  after the versions note and before the step's own notes, the failures and the facts: give provides and uses as exact
  names only, comma-separated, a ctx key bare (sofa, not `ctx["objects"]["sofa"]`) with no note or size in brackets
  after it, and on uses the step each came from (sofa from s2); keep each of the three lines within 300 characters
  (`contract.validate.HANDOFF_LINE_MAX`, Chimera's `handoffLineMax`: `handoff_long` counts characters on provides, uses
  and assumed). The assumed line is held to the length only. A ctx key goes bare because Chimera's rule has later steps
  find in ctx what a dependency lists under provides (and `provides_missing` is a substring test there). A values step
  gets no word of it: its provides line is the user's open question. Since `hints_for` makes every teacher copy, the
  note reaches the first batch, the told batches, the repairs and qwen3.8 alike
  (`test_every_sampler_of_the_step_hears_the_handoff_note` drives `Round.solve` to each). What it reaches on the
  stored calls is in Integrated, below.
  - *The stored lines against it:* of the 400 stored tries on such steps whose handoff the validator read, 249 already
    keep the note whole (provides and uses names only, each line within 300); 42 have a line over 300 (provides 23,
    assumed 21, uses 9; 35 of the tries qwen3.8's, 7 gpt-oss's). smoke5's two qwen3.8 pieces with names-only lines
    (blender-0008-00 r1 s2 c6: provides 111 and uses 40 characters; s3 c6: 67 and 84; the code and the assumed line as
    they were) pass the gate in both Blenders and dep_honesty: +2 examples (both accepted by the scene judge as soft
    keeps; the drop audit graded them weak, D26 and D27). smoke5's n-blender-0000-00 r1 s2 c4 (qwen3.8, provides 493)
    would still run long names-only (29 names, 463 characters): the note doesn't say which to drop, and
    `LONG_ADVICE["provides_list"]` says that after the fact.
- **A plain print for a missing input file (`hints.BLENDER_NOTE`, `stand_ins.for_file`, `MARKER_FILE_TELL`; `check`'s
  "files", `tell`; item 3).** Chimera's Blender rule makes the stand-in line a dependency's missing ctx key ("If one is
  missing because your piece runs alone, make a simple stand-in and print(\"chimera: stand-in\", key)"), and an input
  file is no such key. In smoke5 the marker stood for an SVG, an HDRI or a font on 9 of the 12 marker_misused tries
  and 11 of the 23 gated tries with a misused marker (blender-0008-00 s1 and s3, blender-0002-02 s1), and gpt-oss repeated it on 5 of 10 told retries after
  `MARKER_TELL`'s "say other fallbacks another way or not at all". The reason is unchanged; only the note and the tell
  say what to print instead (no normaliser edits a target).
  - *The note:* BLENDER_NOTE now says, after "without the stand-in marker", to print a plain line of the piece's own
    that names the missing file instead; the older wording goes to `RETIRED`.
  - *The reader:* a misused marker stands for a file (`for_file`) when its key has a file's extension ("acme.svg"), or
    the print is, within its own function, in the else of an if that tests a path is there (`os.path.exists`, `isfile`,
    a Path's `is_file()`) or whose body loads a file (`blender_gate._loader`, or `open`), in the body of an if that
    tests one isn't or that follows a load in the same block (`if not new_objs:` after an SVG import; a load inside a
    function the block defines doesn't count), or in an except of a try whose body loads or tests one. A font looked up
    by name (`bpy.data.fonts.get`) is no file; a font loaded from a path the piece tests is. Of the 103 stored Blender
    tries of smoke-smoke5 with a misused marker (`check` on their code, as the gate joins them) it reads 40 as files (2,
    7, 6, 11, 14), on blender-0008-00 s1, s3 and smoke2's s5 mixed-pool variant and blender-0002-02 s1, and none of the
    other 63 (a dependency's object, the GPU, render_device, world, a font datablock, an output path, a collection).
    The checks below narrowed it (a tested path the piece reads in, an if after a load that tests what it gave, a key
    naming a file the piece reads in), with the same reading of all 103.
  - *The tell (`MARKER_FILE_TELL`, ours, at most 240 characters with its keys):* the stand-in line is for a missing
    dependency's ctx key, not a file the piece can't find; where a file is missing, say so in a plain print instead,
    naming the file and what the piece builds in its place. A piece with both kinds gets both lines; it is registered in
    `stand_ins.TELL_FORMS`, so in `blender_gate.TELL_FORMS`.
  - *The replacement print through the gate:* the 38 file-marker tries of smoke2-5 with each such print made a plain
    print (the rest of the code as it was), through the real gate in both Blenders and dep_honesty: 6 pass (smoke3's
    blender-0008-00 s1 c2; smoke5's blender-0002-02 s1 r1, blender-0008-00 s1 c2 and c3, s3 c2 and c3); the other 32
    fail on what else they do (output_missing, flat_extrusion, doubled_depth, camera_not_active, a lint name, a crash,
    provides_missing, the validator). By step: smoke3's blender-0008-00 s1 (dropped) and smoke5's s3 (a soft keep; also
    item 2's) would get an example, smoke5's s1 would get its own from the told batch (c2) instead of qwen3.8's c4 (V27,
    weak). smoke5's blender-0002-02 s1 r1 passes but stays no example: its shrink is 0.119, over `REPAIR_SHRINK` 0.10
    (the analyst counted it +1; the drop audit's D11 says the same).
  - *Together on smoke5* the three notes items would win about 3 Blender examples (n-blender-0000-01 r2 s4,
    blender-0008-00 s2 and s3), all resting on a scene judge offline can't ask (s2's and s3's c6 it accepted); an
    earlier batch's passing try would come before qwen3.8's example on smoke2's blender-0008-00 s4 (c2, told; X07, Y44,
    bad) and smoke5's s4 and s1 (c1 of the first batch, c2 told; V33 and V27, weak), and the wins carry the drop audit's grades for smoke5's s2 and s3 c6 (D26,
    D27, weak: s2's deletes same-named data it didn't make).
- **The third told batch is retired (`task.Round.solve`, `heard`, `report.samplers` and `_sampler_lines`; item 4).**
  `THIRD_BATCH` is gone: a Blender step that gets past its ROUNDS batches goes to its repairs and qwen3.8 as before the
  fourth smoke's round, whether or not its second batch heard the notes. `heard` is still worked out and recorded
  (`step["sampler"]` keeps its shape, `{"heard", "third": 0, "second", ...}`), so a format-5 record (whose `"third"`
  is 2 where the batch ran) and a new one read the same way; REPORT.md's budget line keeps its old words for records
  that have a third batch and otherwise says how many steps heard their notes (`budget["heard"]`, new). Why: in the
  fifth smoke it fired on 3 steps (n-blender-0000-01 r2 s4, blender-0008-00 r1 s2 and s3), 6 calls, 195.0 s, no gate
  pass (four alone crashes, one of them also linted, a top_level_code, and a provides_missing with a misused marker and
  a stand-in), and one of its tries (blender-0008-00 s2 c5) was the base of the step's only repair (30.1 s,
  silent_default, not kept); the audit's replays found it passing nothing either. smoke2-4's records have no third
  batch (formats 2 to 4); replayed with the tree before, it fires on smoke2's n-blender-0002-01 r1 s4 and
  blender-0008-00 r1 s4, smoke3's blender-0002-02 r1 s4 and blender-0008-00 r1 s3, and none of smoke4 (their stored
  records end before a fifth teacher draw, so that replay can't finish them); with this tree on none, and those steps
  go on to their stored repairs and qwen3.8 as the stored runs did. REPORT.md made again from a copy of smoke5 with
  this tree is byte-identical to the stored one (its budget: 13 steps, 3 heard, 3 with a third batch, none kept from
  it). The replay of smoke5's steps with both trees is in Integrated, below.
  - *Tests.* `SamplerBudgetTests.test_a_batch_that_heard_its_notes_gets_no_third_batch` and
    `test_when_qwen_fails_after_a_heard_batch_the_step_is_dropped` (were `..._gets_one_more_told_batch` and
    `test_when_the_third_batch_fails_qwen_still_comes`: the same stub tries, now 4 gpt-oss draws, then qwen3.8 told
    both batches); the report's `test_a_line_per_sampler` expects `budget["heard"]`, and
    `test_a_heard_batch_with_no_third_batch` is new.
- **A section's code must compile (`prose_gate.code_faults`, `older_fstring`, `code_tell`, `CODE_TELL`,
  `OLDER_FSTRING`; `section_check`; item 5).** The fifth smoke's bad section example (V08, smoke5 blender-0008-00 r1
  s6 c0, upheld bad) is a packaging script, the step's one deliverable, whose README f-string opens a key with `"` and
  closes it with `'`; nothing read a section's code. Now every python block of a section must compile, else the
  section fails `code_syntax` with a tell (the gate's own, `TELL_REASONS`): the block's line, quoted, and Python's
  message (`"its python block doesn't compile, so none of it can run: fix its line 41 ("- Resolution:
  {ctx["values"]["render_re…"): invalid syntax. Perhaps you forgot a comma?"`, 162 characters).
  - *What counts as a section's code.* What Chimera's own result check could pick as a script (pickScript's
    `pythonLang`): a closed block tagged python, py, python3, bpy or a .py name, with the indent all its lines share
    taken off (as pickScript does); not an untagged block, a shell, JSON or other block, nor an interactive session
    (every line a `>>>` or `...` prompt; since the checks below, also a block whose first line is a `>>>` prompt,
    whatever output follows). On the stored section tries the untagged blocks are all listings and prose
    (the smoke runs' 10, the eval's 5: a README's text, a licence line, a URL, a tree of files): read as Python, every
    one would fail. It is parsed (`ast.parse`, neither compiled nor run, as the approved item says; the main
    session's decision after the checks below), so an excerpt from inside a function or loop (`return None`,
    `break`, `await`) passes, with SyntaxWarnings ignored.
  - *Which grammar.* Blender 5.2.2 runs Python 3.13.13 and 5.0.1 runs 3.11.13 (measured in the sandbox), and the gate
    runs Blender pieces in both. `ast.parse(feature_version=(3, 11))` refuses 3.12's type parameters but not the
    f-strings PEP 701 allowed, so a block that imports bpy is also read with the tokenizer for those forms
    (`older_fstring`): the f-string's own quote inside it, a backslash or a comment in a field, a line break in a
    field of an f-string in single quotes; a `#` inside a string in a field, an escaped quote and a backslash-newline
    in the f-string's text are fine in 3.11 too. Its messages are ours (OLDER_FSTRING, no version named). A plain
    Python block is read with this Python's grammar, as the code gate compiles. On a Python before 3.12 the reader
    returns nothing, since compile() there refuses the forms itself. Measured against each Blender's own compile(),
    sandboxed: on the 2,028 distinct python blocks of the stored records (every mode) and the eval (its replies and
    items) 5.2.2's 34 failures are this Python's 34, 5.0.1's are the same 34, and the f-string reader flags no block
    this Python compiles (no stored block uses a 3.12-only f-string); on the test's 12 hand-made cases (each form,
    seven 3.11-safe ones and the packaging script) 5.0.1 refuses exactly the four forms and the packaging script, and
    5.2.2 only the packaging script.
  - *Measured.* The stored section tries of the five smoke runs (114: 37, 26, 18, 17, 16) hold 68 fenced blocks (bash
    21, json 20, untagged 10, dotenv 5, markdown 3, cron 2, cmd 1, yaml 1, python 5); the 5 python blocks are all
    blender-0008-00 s6's (smoke3's c0, c1 and its kept c2, smoke4's c0, smoke5's c0), and only smoke5's c0 (V08) fails:
    3.13's "invalid syntax. Perhaps you forgot a comma?" at its line 41 (5.0.1: "f-string: unterminated string"), a
    real fault, read by hand; 0 false alarms. The eval's 54 stored section replies hold one python block, which
    compiles, and its 481 section item texts none. Of the graded entries only V08 is touched; the other graded
    sections of that step (X61, X75, Y03, Y26, Z14, Z23 and V28) have no python block or one that compiles.
  - *Tests.* `CodeTests` (the packaging script's shape, each 3.12-only form in a Blender script and the same code
    without bpy, the 3.11-safe forms, what counts as code, the wording) and `CodeInBlenderTests` (each Blender's own
    compile() on the same cases, about 1 s) in `test_datagen_prose.py`; `test_tell_notes_are_the_fixed_wording` pins
    the five new notes.
- **A module-level read of a global ctx (`blender_gate.global_ctx`, `global_ctx_tell`, `GLOBAL_CTX_TELL`,
  `GLOBAL_CTX_FORMS`, `JOINED_SHOWS`, `_hard`, `piece_check`, `tell_lines`; `task._BLENDER_STAGES`, `fault_keys`;
  item 6).** The gate's alone run (Chimera's `aloneScript`) binds `ctx` at module level before it calls `build_sN`,
  so a module-level helper that reads a global `ctx` it was never passed runs there; Chimera's real join calls
  `build_sN(ctx)` inside `main()`, where `ctx` is main's own, and the read raises NameError in the person's script.
  The fix is in the generator, as decided: `aloneScript` is unchanged.
  - *The reading.* Python's own scopes decide (`symtable`, on the piece's code with its main guards blanked, as
    Chimera drops them): a function (a module-level def, a method, a lambda, a function or comprehension nested in a
    helper, or `build_sN` itself when its parameter has another name) that reads `ctx` resolved as a global. A
    parameter, an assignment, a loop, with, except, import or walrus target is the function's own, a closure of
    `build_sN`'s `ctx` is fine, and a `global ctx` assigned in some function, or a module-level `ctx` outside the main
    guard (the validator's `top_level_code` refuses one anyway), binds it. Recorded as `gate["global_ctx"]`
    (`[{"function", "line"}]`).
  - *What it does.* Told whatever else fails, after ctx_tell's line (`global_ctx_tell`: the functions, at most 3,
    "_s3_make reads ctx without being given it: pass ctx in as an argument, since Chimera's join calls build_s3(ctx)
    inside a function and the piece has no ctx outside it", 165 characters with one name, 164-221 on the 9 stored
    tries it fires on, under FAILURE_CHARS); a reason, `global_ctx`, at the alone stage's end, after build_facts'. It
    is hard in task.py (no soft keep: the piece breaks the joined script), but the gate still goes on to the joined
    run (`JOINED_SHOWS`, which `_hard` excuses), since that run is Chimera's own join: its NameError is a crash in the
    piece, so a repair is sent it, as Chimera would send one (smoke4's n-blender-0000-01 r2 s2 c0 crashed so on its
    joined run, and its repair, r0, is the step's kept piece; stopping it at the alone stage would have lost that
    repair). A variant, checked alone, fails on it. `_blender_stage` ranks it with the joined run (a try that passed
    every alone check got that far), so no stored try's stage or progress moves; `fault_keys` has it (told whatever
    else fails, so `heard` sees it come back).
  - *Measured.* On every stored Blender try of the five smoke runs (729: 258, 122, 105, 123, 121) it fires on 9 tries
    (smoke4 4, smoke5 5; 8 gpt-oss, 1 qwen3.8) of 5 steps in 3 seeds: smoke4's n-blender-0000-01 r1 s4 c1 and r2 s2 c0,
    c1, c2, smoke5's n-blender-0000-00 r1 s4 c3 and n-blender-0000-01 r1 s2 c3 and r1 s3 c0, c3, c4 (the 4 the audit's
    skeptic named, D14 and D10, among them); none in smoke, smoke2 or smoke3, and no kept piece. The reason is reached
    on 4 (smoke4's r2 s2 c0, beside its joined crash; smoke5's r1 s2 c3 beside size_mismatch, r1 s3 c0 and c3 beside
    aim_mismatch and dead_output_key), 3 are only told (they stopped at lint or alone first) and 2 never reached the
    gate (handoff_missing, too_long). On the eval's 990 distinct stored Blender reply blocks and its own 55 pieces it
    fires on none. Each of the 9, run in a main()-style join in 5.2.2 and 5.0.1 (sandboxed), raises "NameError: name
    'ctx' is not defined" in its helper: in Chimera's own join (render skipped as the gate does) for the 8 Chimera
    joins (smoke4's r2 s2 c2 has no handoff block, so the joiner leaves it out) and in a hand join (the earlier kept
    pieces and the try without their guards, then a main() with a local ctx) for all 9; smoke4's r2 s2 c1 crashes first
    on `bmesh.ops.create_cube.__self__` (its lint:module), and with those arguments taken out of a copy it reaches the
    read in both joins in both Blenders. Run alone, 4 pass in both Blenders (the gap) and 5 crash on something else.
    Replayed through `Round.solve` (smoke4 and smoke5, stored replies), no step's outcome changes: smoke5's
    n-blender-0000-01 r1 s3 is dropped with global_ctx among its reasons; smoke4's r2 s2 is still kept from c0's
    repair; the line reaches smoke5's r1 s3 batch 2 (2 gpt-oss calls) and qwen3.8 (2), and smoke4's r1 s4 and r2 s2
    later tries, whose keys change. Graded entries: none of the examples; of the drops, D14 (audit 5, smoke5's r1 s3:
    c0 and c3 gain the reason, c4 the line) and D16 (audit 4, smoke4's r1 s4: c1 the line); D10's c3 (audit 5) never
    reached the gate (too_long), so nothing changes there. REPORT.md counts the reason with the other new gates
    (`NEW_GATES`).
  - *Tests.* `tests/test_datagen_global_ctx.py` (new: the readings, every kind of scope, the line and its forms
    against the echo check and Chimera's Blender rule for s1-s8, the reason's place in `_hard`, `soft`,
    `_blender_stage`, `fault_keys` and the report), and `GlobalCtxTests` in `test_datagen_blender.py`, in both real
    Blenders: a box whose module-level `_s2_link` reads the global ctx passes alone, fails `global_ctx` and joins, where
    Chimera's join crashes with the NameError in `_s2_link` (the crash for a repair); as a variant it fails alone (the
    tree before passes that variant, `ok` with no reason, and fails only its joined run); given ctx it passes.
- **The echo check.** Twelve new wordings, all ours: HANDOFF_NOTE (under the new label "handoff_note"), BLENDER_NOTE,
  the keyframes fact and KEYFRAMES_FIX (under "blender_fact"), MARKER_FILE_TELL's fixed part (in
  `stand_ins.TELL_FORMS`), `GLOBAL_CTX_FORMS` (2, in `blender_gate.TELL_FORMS`), and in `prose_gate.TELL_NOTES`
  code_syntax's head and `OLDER_FSTRING`'s 4 messages; and three retired ones (the old Blender note, fact and fix),
  still registered. Every 8-word run of each new one is refused under its label, in any case (tested). None names a
  version (the fix's code is the call alone; OLDER_FSTRING has no digit), and none shares an 8-word run with
  Chimera's Blender rule filled for s1-s8, the other modes' rules, any string of `contract.texts`, or any of the
  stored kept targets, replies and request messages of smoke2-5. Code that does what the notes say (the channelbag
  with the object's slot in five forms, a camera data's, a plain print for a missing SVG, a names-only handoff with
  step ids) repeats none of them (tested). What the integrated check refuses on the stored texts is in Integrated,
  below: nothing.
- **New record keys.** A Blender gate's `global_ctx` and `global_ctx_tell` (only when it fires); a section gate's
  `code` (code_faults', always: `[]` when every block compiles); `stand_ins.check`'s `files` (the misused marker's keys
  that stand for a file, in the gate's facts); report `samplers.budget["heard"]`. New reasons: `global_ctx` (Blender),
  `code_syntax` (section), both in `report.NEW_GATES`. `step["sampler"]["third"]` is 0 on every new record.
- **Tests (the two parts).** The notes: `AfterTheFifthSmokeTests` in `test_datagen_hints.py` (6: the fact and the fix
  name the slot, the fix on the wrong-slot lines, the handoff note's steps, every sampler hears it, the Blender note's
  plain print, the new wordings to the echo check), `MissingFileTests` in `test_datagen_stand_ins.py` (3) and
  `TheSlotHoldsInBlenderTests` in `test_datagen_blender5.py` (1); changed where the behaviour is meant to: the fix's
  wording in `test_a_failure_calls_for_its_fact_and_its_line_names_the_replacement`, the handoff note on the non-values
  steps in `test_the_note_for_a_values_step`, the fourth tell form in `test_the_tells_are_short_and_ours`. The checks:
  `test_datagen_global_ctx.py` (7), `CodeTests` (4) and `CodeInBlenderTests` (1), `GlobalCtxTests` (1),
  `test_a_heard_batch_with_no_third_batch` (1), the two rewritten sampler tests, and the changed
  `test_tell_notes_are_the_fixed_wording` and `test_a_line_per_sampler`. Both parts changed
  `test_this_rounds_tell_wordings_are_known_to_the_echo_check` (each its own lines). Every new, rewritten or changed
  test fails on the tree before (the notes' 14: 6 failures, 8 errors; the checks' 19: 16 failures and 22 errors with
  their subtests).
- **Integrated (Nov 6, the Studio, offline, binary `458dcbfc…`, Blender 5.2.2 and 5.0.1 sandboxed).** The two patches
  went in in the order notes, checks, on a copy of the tree both were made against (equal to the real one outside
  data). The one file both touched is `tests/test_datagen_blender.py`, in one test,
  `test_this_rounds_tell_wordings_are_known_to_the_echo_check`: it has both parts' lines in `blender_gate.TELL_FORMS`'s
  order (stand_ins' forms with MARKER_FILE_TELL last of its own, then silent's, then `GLOBAL_CTX_FORMS`, then
  geometry's, which stay last). No merged module has a duplicate class or method name or code after its main block.
  DATAGEN_FORMAT went to 6 (above), with `test_datagen_run.py`'s pins (its docstring, `RecordFormatTests` (6, 6) and
  `other_formats` with format 5 among the old ones, `ValuesRunTests.test_the_run_is_format_6` and its examples'
  format, the refusal tests with format 5 among the finished folders and smoke6 and smoke7 as new ones),
  `test_datagen_task.py`'s pin and `test_datagen_build.py`'s comment, and `run_datagen.sh`'s and `run.py`'s words
  for the sixth smoke.
  - *Tests.* The whole worker-model folder in three foreground parts that cover every module, with `CHIMERA_BIN`, in
    the real tree: `test_datagen_blender`, `test_datagen_blender5` and `test_datagen_run` 125 in 4.6 minutes, the other
    19 datagen modules 757 in 2.8, the 22 others 354 in 2.1: 1,236 (882 datagen; 24 new, 2 rewritten), all passing,
    none skipped, `test_the_users_home_is_unreadable` included (the same in the scratch copy but for that test, which
    reads a copy under /private/tmp there). `tools/check_contract_parity.py`: 42 texts and 6,291 requests, 0 differ;
    `tools/check_join_parity.py`: 0 differ. `app/` and `contract/` are untouched.
  - *Requests.* Every stored step and repair request of smoke2-5 made again through the binary from its stored inputs
    (272: 78, 62, 66, 66): the tree before and this one give the same bytes for all 272, and smoke4's and smoke5's 66
    each are byte for byte the stored ones (smoke2's other 38 and smoke3's 30 were made by older binaries, as before
    the round).
  - *Teacher calls.* Every stored Blender teacher call of smoke2-5 (471: 122, 105, 123, 121) made again in each tree's
    own `Round.solve` order: with the stored tells, the tree before gives all 121 of smoke5's stored cache keys; then
    each tree with the tells its own gate gives every stored try (replayed below). This tree draws 460 of the 467 the
    tree before does (smoke4's other 4 are qwen3.8 calls both skip, `api_only`): not smoke5's 6 third-batch draws
    (n-blender-0000-01 r2 s4 c4 and c5, blender-0008-00 s2 and s3 c4 and c5) nor blender-0008-00 s2's repair r0, whose
    base was c5, 225.1 s in all. All 460 hear new notes and get a new key (the Blender note is in each), every one the
    stored request plus notes under HEAD and nothing else; the notes grow by 349-355 characters on average (73 to
    734). HANDOFF_NOTE is in 428 (114, 99, 109, 106): 314 batch calls, 34 repairs and all 80 qwen3.8 calls; the other
    32 are every values step's calls (8, 6, 10, 8), whose notes change only in the Blender note (and on 2 the
    keyframes fact). The keyframes fact's new words reach 107 calls (70 batch, 15 repair, 22 qwen3.8), the fix's 44
    (18, 12, 14), MARKER_FILE_TELL's line in MARKER_TELL's place 30 (12, 2, 16; 6, 6, 8 and 10 by run), and
    global_ctx's line 10 (smoke4 6, smoke5 4), which on smoke4's n-blender-0000-01 r1 s4 and r2 s2 pushes an older
    line out of the newest six (4 calls). On smoke5's three third-batch steps the repair and qwen3.8 now hear two
    batches' failures: the third batch's lines are gone from 7 calls, and an older line is back in the window on 3.
    The other modes' notes before any failure are the same on all 136 of their steps.
  - *Gate verdicts.* Every stored try of smoke2-5 that reached its gate (424: Blender 360, 87, 79, 92, 102; section
    64, 22, 15, 14, 13) gated again by both trees as `Round.gate` runs it, dep_honesty as `Round.honest` adds it;
    smoke5's 115 with the tree before are its stored records (the judge's reasons aside), and no run was made (all
    from the cache). Reasons, ok and dep_honesty differ on 5: `global_ctx` on smoke4's n-blender-0000-01 r2 s2 c0
    (beside its joined crash; the step is kept from its repair r0, ungraded) and smoke5's n-blender-0000-01 r1 s2 c3
    (beside size_mismatch; the step's kept c2, V25 weak, is unchanged), r1 s3 c0 and c3 (D14, right, best bad), and
    `code_syntax` on smoke5's blender-0008-00 s6 c0, the step's kept piece (V08, bad: that example goes). The tell
    differs on 31 Blender tries (3, 4, 9, 15): 24 MARKER_FILE_TELL's line in MARKER_TELL's place (on steps graded
    X05/Y49 bad, V35/Z26 bad with the kept c5 among them, V27 weak, D11, D12, D19/D27 and D25), 7 global_ctx's line
    (D14, D16, V25's step and smoke4's r2 s2); and on V08's section.
  - *Echo check.* With this tree's notes it refuses none of smoke2-5's 129 stored built examples (the build's own
    check), 102 distinct kept pieces, 558 distinct stored replies with their own requests, nor the stored replies of
    the 460 calls above against the told lines this tree would have given them (as precheck passes them); the same as
    the tree before.
  - *`Round.solve` on smoke5's 29 Blender and section steps and variants* (stored replies, by position where a key no
    longer matches): the tree before replays all 29 as stored (148 runs from the cache); this one changes 6.
    n-blender-0000-01 r1 s2 (c3 gains global_ctx) and r1 s3 (its drop gains global_ctx, its draws the same) keep their
    outcome. The three third-batch steps say `"third": 0` and don't draw c4 and c5 (n-blender-0000-01 r2 s4 61.0 s,
    blender-0008-00 s3 63.2 s, s2 70.7 s and its repair r0 30.1 s): n-blender-0000-01 r2 s4 is dropped either way, and
    blender-0008-00 s2 and s3 keep qwen3.8's soft keep. blender-0008-00 s6 fails c0 on code_syntax and draws a told
    second try, which no stored reply answers: V08 is gone, and whether the step wins an example back is the next
    smoke's. Every Blender teacher, repair and qwen3.8 call the replay asks for (114) answers by position, not by key
    (only the sections' and the judge's calls hit): in a run each is a new model call.
- **Checks (Nov 6).** Three independent reviewers read the round in the real tree (the notes, the checks, the docs);
  each finding was run again in a copy, and all eight held. Fixed, each with a test that fails on the tree before:
  - *`for_file` read too widely:* an if after a load in the same block counted though its test read something else (a
    GPU test after an HDRI's load gave render_device the file tell), and an exists test of an output folder and a key
    with an output's extension (a video's name) counted as missing inputs. Now the if must test what the load gave
    (`_after_load`, `_gives`, `LOAD_GIVES`: a scene's, a collection's or bpy.data's objects, the selection, the active
    object, bpy.data, the load's result, or a name bound to one at or after it), an exists test counts only for a path
    the piece reads in (`_tests_input`: a variable or a dict key of the tested path reaching a loader or an open() for
    reading, also through a helper of the piece, `_reaches_read`), and a key's extension only when the piece reads
    that file in (`_names_an_input`). All 544 stored tries of smoke-smoke5 with a stand-in in their code keep their
    markers, files, silent reads and tells (103 misused, 40 files). Two `MissingFileTests` fixtures gained the load
    they stand for; `test_an_output_or_another_test_after_a_load_is_no_input_file` is new.
  - *The keyframes fact's dotted name after a plain `import bpy_extras`:* under `--factory-startup` neither Blender
    has `bpy_extras.anim_utils` then, and the crash, "module 'bpy_extras' has no attribute 'anim_utils'", got no
    fix. It now ends with `ANIM_UTILS_FIX` ("import the submodule first: from bpy_extras import anim_utils", 8 words,
    ours to the echo check, while a piece that writes the import repeats no run of it), and the fact comes with it;
    the fact's words are unchanged. `TheSlotHoldsInBlenderTests` prints Blender's own message in both and checks the
    fix ends it; `test_a_plain_import_of_bpy_extras_gets_the_import` is new. No stored failure has that error.
  - *`older_fstring` read only the outermost f-string:* a nested one reusing its own quote (also in a triple-quoted
    f-string or a format spec) or breaking a line passed `code_syntax`, which 5.0.1 refuses; each f-string is now
    read with its own quote as it closes. Found while checking that: a line continuation in a field (no token) passed
    too, and is now "backslash". On 50 hand-made f-string cases it agrees with 5.0.1's own compile() on 48 (40 before),
    all but the two type-parameter forms; on the 2,028 stored and eval blocks it flags nothing more (34, none of them
    an f-string form, as before). `NESTED` (6) is in `CodeTests` and `CodeInBlenderTests`.
  - *A session with its output:* a block whose first line is a `>>>` prompt is a session, as a doctest shows one; no
    stored block has a `>>>` line.
  - *Doc slips:* three of the keyframe-step wins counted as the told batch's are the first batch's (c0, c1), which
    hears the fact but no fix; the third batch's 195.0 s; qwen3.8's 339 and 309 characters; smoke2-4's formats 2 to
    4; the replays of smoke2-4 couldn't judge a third batch (task.py said none passed); 9 of the 12 marker_misused
    tries (11 of the 23 gated tries with a misused marker).
  - *Measured after the fixes, offline:* the 424 gated tries of smoke2-5 gated again by both trees give the same
    reasons, ok, dep_honesty and tells; the 272 requests and the 460 drawn Blender teacher calls the same notes and
    keys; the echo check refuses none of the 129 built examples, 102 kept pieces and 558 replies, and the new fix
    shares no run with Chimera's texts or any stored record. Tests: 1,239 (885 datagen; 3 new) in the three parts,
    125 in 4.5 minutes, 760 in 2.8, 354 in 2.1, none skipped; both parity tools 0 differ.
  - *Decided by the main session the same day:* `code_syntax` compiled where the approved item says parse, so a
    section's excerpt from inside a function or loop (`return`, `break`, `await`) failed; it now parses (`ast.parse`,
    with `older_fstring` for a Blender script, as before). None of the 2,028 blocks parses and fails to compile, so no
    stored verdict changes. Left: `for_file` misses a test that reads only a count taken before the load, and a file
    read through an operator that isn't a loader (a video strip); the suggested CLAUDE.md said the gate's joined run
    had the global-ctx gap (it is Chimera's own join, which crashed on the read: only the alone run, so a variant, had
    it), corrected there and in `results/DATAGEN-SMOKE.md` ("A new gate gap") by the main session.
- **Left.** Whether gpt-oss now names the slot and prints a plain line for a missing file, whether qwen3.8 keeps its
  lines short, and what the 7 later calls on the third batch's steps and blender-0008-00 s6's told try write, only the
  next smoke shows (5 of 10 told retries repeated the marker after a tell, and 9 tries ignored the keyframes fact); the
  examples counted as won rest on a scene judge offline can't ask. The fix cuts more failure lines before it, each
  keeping its source and error type. A font looked up by name keeps MARKER_TELL, and a marker after an SVG import
  behind another if (smoke2's blender-0008-00 s1 c3) isn't read as a file's. The handoff note asks for names only, not
  which to drop, so a piece that hands on 29 names still runs long. The fact's example names an object's slot; a camera
  data's or a node tree's is the "ID" it speaks of (checked, but given no form of its own). code_syntax reads only
  blocks tagged as Python, so an untagged script isn't compiled, and a bpy block is held to Python 3.11's f-strings but
  not to anything else 3.12 added outside them (type parameters, which feature_version could add; none stored).
  global_ctx reads only the name `ctx`, the one name the alone run's tail binds besides `bpy` (which Chimera's join
  imports too), and fires on a dead helper as on a live one (no stored piece has one); a repair is sent only for the
  joined crash, so a try that fails global_ctx only in a variant, or on a path the joined run doesn't take, gets the
  line but no repair. The gap itself is Chimera's: `aloneScript` (app/hydra_assemble.go) binds ctx at module level,
  where Chimera's join holds it in main(), so a script Chimera checks alone can pass while its join crashes; building
  the alone script's ctx inside a function, as main() does, would close it for the real flow too, a contract-side
  change for the user to decide (until then global_ctx holds it in the generator). Not in this round, as the user's
  message said: `dead_output_key` following a key through the piece's own getter (`_s3_get('output_path', ctx)`: 4
  false DEAD_UNASKED tells on smoke5's n-blender-0000-01 r1 s3, no example lost), the soft keep judging tries that
  built something before those whose alone run is empty (blender-0002-02 s2's r1 was never judged; `SOFT_JUDGED` 2),
  and more cheap API facts (Transmission Weight, Specular IOR Level, `view_layer.objects.active`, the area light's
  shapes, TrackTo's `TRACK_NEGATIVE_Z`). The values steps' provides limit (`handoffLineMax`) and what
  `SETTINGS_sN["output"]` holds for a .blend and a render stay the user's questions.
- **Next.** The sixth smoke: the same 8 seeds into `data/gen/smoke6`, its seeds.jsonl and a cache seeded with the
  fifth run's calls (`cache/calls.jsonl`) copied in first. It pays Blender model time again: every Blender teacher
  copy is new (the Blender note is in each), and so is every scene-judge call on a new piece and every Blender qwen3.8
  call; the code steps' calls replay from the cache (their notes and Chimera's requests are unchanged), a section
  after Blender steps whose pieces change doesn't, and blender-0008-00 s6 draws a told try. Its audit says whether the
  round won the 3-5 more Blender examples the analyst and the notes part estimated. Then the nights.
