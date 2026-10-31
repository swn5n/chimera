# Hydra 1.0's reviews at lower temperatures

Oct 29, on the Studio. Chimera sends no temperature with a review, so `hydra:1.0` reviews at its Modelfile's 0.7, and in a real long task its verdict on the same result changed from one try to the next (`docs/hydra-1.0-handoff.md`, "Checked on the Studio"). This measures whether a lower temperature would be better. Chimera itself is unchanged.

Reviewer job only, Chimera's exact request plus `--temperature`, 10 unseeded tries per case (`--seed none --samples 10`, so tries vary the way they do in Chimera), on `eval/` (v1.1, 24 short results) and `eval-long/` (long-1, 16 results of 3,900 to 12,400 characters). Each row has 240 or 160 reviews.

| reviewer, temperature | set | right | flawed caught | good accepted | cases whose verdict varies | p50 |
|---|---|---|---|---|---|---|
| hydra:1.0, 0.7 (unset, as in Chimera) | eval/ | 81.7% | 86.0% | 74.4% | 9 of 24 | 1.0 s |
| hydra:1.0, 0.2 | eval/ | 82.5% | 86.0% | 76.7% | 7 of 24 | 1.2 s |
| hydra:1.0, 0 | eval/ | 75.0% | 86.7% | **55.6%** | 0 of 24 | 1.1 s |
| gpt-oss:120b, unset (its default) | eval/ | **92.9%** | 93.3% | 92.2% | 1 of 24 | 3.5 s |
| hydra:1.0, 0.7 (unset, as in Chimera) | eval-long/ | 81.2% | 75.0% | 87.5% | 5 of 16 | 1.2 s |
| hydra:1.0, 0.2 | eval-long/ | 80.0% | 72.5% | 87.5% | 2 of 16 | 1.2 s |
| hydra:1.0, 0 | eval-long/ | 81.2% | 75.0% | 87.5% | 0 of 16 | 1.3 s |

eval-long/ by result length (right, then flawed results caught):

| temperature | under 6,000 characters | 6,000 and over |
|---|---|---|
| 0.7 | 88/90, caught 49/50 | 42/70, caught 11/30 |
| 0.2 | 87/90, caught 47/50 | 41/70, caught 11/30 |
| 0 | 90/90, caught 50/50 | 40/70, caught 10/30 |

- **Temperature 0 makes the verdicts repeat, not get better.** On the short set it turns four mostly-right cases into always-wrong ones: rev-01 (9/10 → 0/10), rev-24 (6/10 → 0/10), rev-07 (4/10 → 0/10), rev-13 (2/10 → 0/10). They are mostly good results it now always rejects. It gains rev-06 (7 → 10), rev-17 (8 → 10) and a try here and there (rev-05, rev-21). That is 81.7% → 75.0% right, and good results accepted drops from 74% to 56%, which in looping mode means extra rounds on work that was already done.
- **0.2 is the same as 0.7** within the noise (82.5% vs 81.7%, 80.0% vs 81.2%), with slightly fewer varying cases.
- **No temperature helps with long results:** from 6,000 characters on it catches 10 or 11 of 30 flawed results at any setting. Those misses are fixed habits on particular cases (rev-long-03 0/10 at every setting, rev-long-16 at most 2/10), not sampling noise. The review limit added in Chimera on Oct 29 (`helperMaxReviewCtx`, about 5,800 characters of result) is what covers them.
- **A majority of three reviews wouldn't help either.** Worked out from each case's rate at 0.7, it's 82.5% on eval/ (from 81.7%) and 81.5% on eval-long/ (from 81.2%), for three times the calls.
- **The two real Blender results** from the handoff's long task, 3 tries each: at 0, Hydra said done to the script that crashes on `mathutils.radians` all 3 times, and "not done, backdrop not curved" to the other one all 3 times. At 0.2 it was mixed, as at 0.7.
- **The eval v1.1 headline understates the gap.** With seed 7 and one try, Hydra 1.0 scored 22/24 to gpt-oss:120b's 23/24 (`QUANT-v3.md`, `BASELINES.md`). Unseeded over 10 tries it's 19.6/24 (81.7%) to 22.3/24 (92.9%), so on short reviews the teacher is about 11 points ahead, not one case. gpt-oss:120b barely varies (only rev-08 changes between tries) and takes about 3.5 s a review to Hydra's 1.0 s. On `eval-long/`, unseeded over 5 tries, it got 74/80 to Hydra's 67/80 (`runs-long/*-unseeded5`).
- **Where Hydra loses on short reviews** (right of 10, Hydra at 0.7 against gpt-oss:120b):
  - rev-19, a temperature conversion with one wrong answer (98.6 °F as 36.0 °C): 0 against 10. This is the known arithmetic gap.
  - rev-13, a correct `cat | wc -l` one-liner it rejects: 2 against 10.
  - rev-24, a fine two-sentence apology it rejects: 6 against 10.
  - Small gaps on rev-06 (a 60-word blurb that's 190 words: 7 against 10) and rev-17 (a four-line limerick: 8 against 10).

  Hydra is ahead on rev-07, a Blender script that wipes the user's scene: 4 against 0. Both are poor on rev-08, a correct orbiting camera: 2 against 3. These are the cases for Hydra 1.1's review data: redoing arithmetic, not rejecting correct short answers, and line and word counts.

Conclusion: keep the review temperature as it is. 0 makes reviews consistent but wrong more often, and nothing at any temperature closes the long-result gap. The ways forward are the shorter review limit (done) and Hydra 1.1 trained on longer reviews and on results that crash or are cut off. `QUANT-v3.md` saw the same direction with one seeded try per case (22, 20, 19 of 24 at 0.7, 0.2, 0).

Runs: `results/runs-temp/` (`20261029-145621-hydra-1.0-eval`, `-150034-…-eval-long`, `-150355-…-t0.2-eval`, `-150916-…-t0.2-eval-long`, `-151237-…-t0-eval`, `-151716-…-t0-eval-long`, and `20261029-153202-gpt-oss-120b-eval`). Per case: `python3 runner/compare.py --jobs reviewer results/runs-temp/20261029-145621-hydra-1.0-eval results/runs-temp/20261029-150355-hydra-1.0-t0.2-eval results/runs-temp/20261029-151237-hydra-1.0-t0-eval` (`compare.py` shows the first try of each case only).
