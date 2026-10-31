# Long review cases — long-1 (EVAL ONLY)

**Never train on anything in this folder.** It was written by Claude (Opus 5.5) on 2026-10-29 to score models:
Anthropic's terms bar using Claude outputs as training data, and a model trained on its own eval makes the eval
meaningless. Every file carries the same canary string as `eval/`, so `tools/check_overlap.py` catches leaks.

`eval/` only has reviews of short results (all under 1,400 characters). Chimera 0.7.0 first let Hydra 1.0 review
combined results of up to about 16,700 characters (whatever fits the 8K context; bigger ones go to the biggest
model). After these cases were run on Oct 29 (it missed most flaws from 8,300 characters on), the limit is about
5,800 characters (`helperMaxReviewCtx` in `app/helper.go`). These 16 cases are in between: results of 3,900 to 12,400 characters, 8 done and 8 not, in pairs that
share most of their text, so a reviewer has to find the one thing that's wrong.

- Done: a to-do CLI with tests, a Flask notes app (four files plus tests), a volunteer guide, a backup comparison,
  a 14-day SQL plan, a Blender campfire script, a bakery food-waste report, a budget script with README and tests.
- Not done: the to-do CLI without its delete command; the Flask app whose tests import `create_app(config)` while
  `app.py` defines `make_app()`; the guide without its safety section; the backup comparison for a task that asked
  for four options (it has three); the SQL plan with 10 of 14 days; the campfire with no camera; the report cut
  off in its action plan; the budget result cut off in the middle of its tests.
- The code was run: the done cases' tests pass, the cut Flask case fails only because of the planted mismatch,
  and the budget's sample output is the script's own. The Blender script wasn't run (no Blender here).

Run them with `bash run_long_reviews.sh` (from `helper-model/`). Runs go to `results/runs-long/`, so
`report.py` and `BASELINES.md` (eval v1.1) are unaffected. Same file format as `eval/`; the version is `long-1`.
