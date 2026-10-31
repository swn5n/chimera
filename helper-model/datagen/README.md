# Synthetic training data

`bash run_datagen.sh` (in `helper-model/`) makes the helper's training data on the Studio: a 15-minute
smoke run of every stage into `data/smoke/`, then the overnight run into `data/` (about 7 to 8 hours).
Switch lending off in Chimera first. Everything is resumable: run the same command again after a stop.

## Where the data comes from

- **Teacher:** gpt-oss:120b (Apache 2.0) writes the seed requests, the plans, the reviews, the Heads and
  the gate messages, and the gate answers. Its reasoning effort is its own default unless `EFFORT=high`.
- **Workers:** qwen3:4b-instruct-2507, qwen3:1.7b and qwen3:8b (Apache 2.0, thinking off) write the
  results the reviewer judges, so it sees the kind of good and flawed work small models really produce.
- **Never Claude.** No request, result or target is written by Claude. The instructions that steer the
  teacher (`teacher_prompts.py`, `taxonomy.py`) are short topic labels and rules, not example requests,
  and they aren't part of the data. The fixed text in every example is Chimera's own prompt templates
  (`helper/prompts.py`), which the helper has to answer.
- **Never the eval set.** Seeds come from topic labels, not from `eval/`; every seed, gate message and
  final example is checked against it (`tools/check_overlap.py`: canary, repeats, shared 8-grams), and
  none of the eval set's four Heads is used.

## Stages

| Stage | What happens | Kept only if |
|---|---|---|
| seeds | The teacher writes requests per category (coding, research and drafting, Blender, batch, planning, small checkable tasks, and follow-ups after a short chat), with topic, style, length and language varied | not a repeat or near-repeat (5-word shingles) and not close to the eval set |
| plans | The teacher plans each request through Chimera's exact planner call, up to 2 tries | strictly valid after format-only fixes (ids renamed s1..sN, code fences dropped, empty `depends_on` filled in), no review/combine step, the right kind for the category (Blender plans must be `blender`), batch plans run in parallel |
| results | Workers answer a sample of tasks; some answers are cut short, lose a section, or get one deliberate flaw from the teacher | the answer came back |
| reviews | The teacher reviews each result twice through Chimera's reviewer call | both verdicts strictly valid and in agreement, and "not done" for anything known to be broken |
| replans | Round-2 plans after a "not done" review, as Hydra's looping mode sends them | the same rules as plans |
| gate | The teacher invents words-only Heads, writes messages of 13 known types for each (6 want the Head's result, 7 don't), and answers each through Chimera's gate call | the teacher's answer matches the message's type |
| build | MLX-LM chat files, split by seed or Head (none on both sides, at least 2 groups per job in valid), checked against the eval set again. Drops plans with a step that only makes a PDF/Word/Excel/PowerPoint file (outside coding jobs: Chimera's workers return text) and examples over ~7,500 tokens; keeps Blender plans rejected only for being labelled `code`, relabelled `blender`; repeats "done" reviews 2x in train | the target is strictly valid |

A stage stops the run early (writing `STOPPED.md`) if its first 20 items look wrong, for example when
fewer than half the plans are acceptable, so a bad night doesn't go unnoticed until morning.

## Files (in `data/`, or `data/smoke/` for the smoke run)

- `sft/train.jsonl`, `sft/valid.jsonl`: the training files, one `{"messages": [system, user, assistant]}` per line.
  `*.meta.jsonl` line up with them (job, category, variant, label, group).
- `STATS.md`: counts, acceptance rates, label balance, lengths (and the `--max-seq-length` to train with), time spent.
- `seeds.jsonl`, `review_items.jsonl`, `gate_heads.jsonl`, `gate_requests.jsonl`: the intermediate material.
- `classifier/gate.jsonl`, `classifier/kinds.jsonl`: labelled data for the embedding-classifier experiments.
- `raw/`: every model reply, accepted or not, with the reasons; this is what makes resuming work.

`python3 -m datagen.run --size night --stages build` rebuilds the training files from `raw/` without calling a model.

## v2 (Oct 28): `--stages v2`, on top of a finished v1 run

v1's helper got the planner and the gate right but not the reviewer: its reply starts with `"done"`, so it picks a
verdict before checking anything, and it missed flaws you only see by checking (a fifth item missing, one wrong
conversion, a word limit, a missing filter). Asking for a check first lifted the untrained base from 15 to 20 of 24
eval reviews, but not v1, whose checks were one-line assertions. So v2 trains the check in. `bash run_v2.sh` runs
these stages (smoke run first), then trains v2. Nothing of v1's is changed; v2 writes new files beside it.

| Stage | What happens | Kept only if |
|---|---|---|
| seeds2 | Batch requests with 8 to 15 items (v1 planned a 10-item batch as 10 steps; Chimera keeps 8) | as for seeds, and not a repeat of a v1 seed |
| plans2 | Seeds whose v1 plans all failed for a reason a one-line hint fixes (one step, steps waiting on each other, a review/combine step, a Blender plan labelled `code`) get up to two more tries with the hint; the long-batch seeds get a plain try, then a hinted one. The hint is only in the teacher's copy of Chimera's request: the training example is Chimera's exact request | as for plans |
| answers | The teacher answers 90 small tasks (also answered by the workers) and 60 planner tasks the workers didn't get, as a worker would: mostly right, so the reviewer sees more finished work | the answer came back |
| flaws2 | 130 more flawed copies of worker results and teacher answers, weighted towards flaws you only see by checking (one wrong value, a skipped item, an ignored condition or limit) | the rewrite is usable |
| reviews2 | Every review item (v1's and the new ones) reviewed twice by the teacher with a note asking for a `check` first: one line per requirement, with counts and working shown. The training example is Chimera's exact reviewer request; the target is `{"check", "done", "score", "critique"}`, check first | both verdicts valid with a check, in agreement, "not done" for anything known to be broken, and a "done" whose check doesn't mark anything failed |
| build2 | `sft-v2/`: v1's plans, re-plans and gate examples, the hinted plans, and only check-first reviews (two reviewer formats would conflict); "done" reviews repeated until they're about 40% (at most 3x) | the target is strictly valid (reviews: with the check first) |

v2's files: `seeds2.jsonl`, `review_items2.jsonl`, `sft-v2/`, `STATS-v2.md`, `RUN-v2.json`, and `raw/*2.jsonl` plus
`raw/answers.jsonl`. About 5 hours on the Studio for the night size.

## v3 (Oct 28 night): `--stages v3`, on top of v1 and v2 (`datagen/v3.py`)

v2's helper copied the check's format but not the checking: "each conversion correct" without converting, "about
60 words" for a 190-word text, a list of what an SQL query contains instead of what the task asked (a 2025 filter).
Its planner also gave every item of an 8- to 10-item batch its own step. `bash run_v3.sh` first asks v2 and the base
for worked checks by prompt alone (`--variant check-working`, a few minutes), then runs these stages and trains v3.

| Stage | What happens | Kept only if |
|---|---|---|
| seeds3 | 10 more calls for batch jobs with 8 to 15 items | not a repeat of a v1, v2 or v3 seed |
| plans3 | Each planned with a hint (teacher's copy only) to use 3 to 5 groups of items; a second try adds hints for what went wrong | as for plans, and 3 to 5 steps |
| answers3 | The teacher answers 60 small tasks and 80 planner tasks it hasn't answered yet | the answer came back |
| flaws3 | 150 flawed copies of results nobody flawed yet, weighted to a wrong value, a wrong count, a broken length limit, an ignored condition | the rewrite is usable |
| reviews3 | Every review item (v2's and v3's) reviewed again with `CHECK_NOTE3`: list the task's requirements first, check each, redo counts and calculations in the open, estimate lengths. Results known to be broken get one pass (it must say not done), the rest two that agree | as in v2 (checks up to 2,000 characters) |
| build3 | `sft-v3/`: v1's plans, re-plans and gate examples, v2's hinted plans, plans3, and only v3's reviews | the target is strictly valid |

v3's files: `seeds3.jsonl`, `review_items3.jsonl`, `sft-v3/`, `STATS-v3.md`, `RUN-v3.json`, `raw/*3.jsonl`. About 5
hours for the night size.
