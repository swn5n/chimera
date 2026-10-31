# Handoff: Hydra 1.0 and Chimera 0.7.0 (Oct 27–29, 2026)

This was done from a claude.ai chat that reached `~/Desktop/chimera` on this Mac through the Claude desktop app's file bridge. The bridge's shell is a Linux VM with no network and no Go, so that chat could not build for macOS, reach Ollama or read Chimera's log here; the user ran the training and eval scripts. The 0.7.0 code was built and tested in a Linux cloud workspace against fake Ollamas. **The next job is to check it on the Studio against the real Ollama, then on the other computers.** `CLAUDE.md` is already updated for 0.7.0; read it first.

## What exists now

**Hydra 1.0, the helper model.**
- Ollama name: `hydra:1.0`, on the Studio only.
- What it is: Qwen3-4B-Instruct-2507 (Apache 2.0) with a LoRA trained on synthetic data from gpt-oss:120b, quantized to Q5_K_M.
- Size: 2.9 GB on disk, about 4 to 4.5 GB in memory at Chimera's 8K context. Its Modelfile caps replies at `num_predict 4096`.
- Files: `~/chimera-tools/helper-train/v3/helper-q5_k_m.gguf` and `Modelfile.q5_k_m`. In Ollama's store it is blob `sha256:d2e366efe862ddea799db18e042add7162af388f48dfd7d7723d37e7c2e4fe81` (2,889,512,416 bytes). Ollama 0.40.1 keeps its manifest at `~/.ollama/models/manifests-v2/ollama.com/library/hydra/1.0`.
- Eval v1.1:
  - Plans: 41/44 strictly valid; Chimera accepts all 44.
  - Reviews: 22/24.
  - Head gate: 43/43 pairs.
  - Speed: about 4 s a plan, 1 s a review, 0.1 s a gate call on the Studio.
  - For comparison, gpt-oss:120b: 43/44 plans, 23/24 reviews, 42/43 gate pairs, at 11 s, 3.1 s and 1.0 s.
  - Known weak spots: it doesn't redo arithmetic when it reviews (98.6 °F → 36.0 °C passes), and it sometimes rejects a correct `cat | wc -l` one-liner.
- The training data, the LoRA training, the eval and all results are in `helper-model/`. Start with its README, then `results/QUANT-v3.md`.

**Chimera 0.7.0: Hydra 1.0 wired in.** The user approved all three jobs, and approved getting the model from the host inside Chimera rather than from ollama.com or by hand.

- **Routing.**
  - Hydra's planner, the looping-mode reviewer and the words-only Head gate send `prefer_model: "hydra:1.0"`.
  - In the hub's `fits`, a device that has it scores `1e6 - eta` and beats everything.
  - A free helper device that isn't long-polling at that moment gets up to 3 s (`helperWait`). This covers a device that has just finished a step, typically the combine right before a review. A busy device isn't waited for.
  - With no helper device, `prefer` (largest or fastest) decides exactly as before.
  - Only requests with `need_ctx <= 7000` (`helperMaxCtx`, the 8K bucket) ask for it: roughly 13,300 characters into a plan. Reviews stop lower, at `need_ctx <= 3500` (`helperMaxReviewCtx`, added Oct 29 on the Studio): about 5,800 characters of result.
- **Kept to its jobs.** `ModelInfo.ForChat()` (`isHelperModel` matches any `hydra:` tag) keeps the helper out of:
  - chats, worker steps and combining
  - library jobs and `largestLocked`
  - the local fallback (`pickLocalModel`)
  - Head options (`fastestChatModel`)
  - "best for", help items, and the chat model picker (`forChat` in app.js).

  A step that names the model explicitly can still use it.
- **Second chance.** If the helper's plan or review can't be read, or its step errors, it is asked once more without `prefer_model` (`askPlanner` and `askReviewer` in hydra.go). The retry routes as "largest" always has: the biggest model among the devices waiting at that moment.
- **Prompts are unchanged on purpose.** Hydra was trained on exactly `hydraPlannerPrompt`, `hydraReviewPrompt` and `headGatePrompt`. Change them and it needs retraining. `helper-model/tools/check_prompts_sync.py` must keep passing; it does now (102 mirrored Go lines).
- **Getting it onto other computers** (`app/helper_share.go`).
  - *On the host:* Chimera finds its Ollama's model file. It reads the `FROM` line of `/api/show`'s modelfile, and falls back to the manifest in `$OLLAMA_MODELS` or `~/.ollama/models`. It advertises the model in the network snapshot (`network.helper`) and serves two endpoints:
    - `GET /v1/helper`: digest, template, parameters parsed from `/api/show`, and licence.
    - `GET /v1/helper/model`: the file in 1 MB writes, each with a 60 s write deadline (`helperStall`); two copies at a time, 429 beyond that.
  - *On the member:* Models → Helper → **Get from host** calls `POST /api/helper/install` (SSE progress). It sends HEAD `/api/blobs/<digest>`; if Ollama doesn't have the file, it streams it into `/api/blobs`, then calls `/api/create` with `files: {"hydra-1.0.gguf": digest}` plus the host's template, parameters and licence.
  - The upload's reader only counts bytes (an atomic). Progress comes from a ticker that is stopped before `installHelper` continues, and a copy that makes no progress for 60 s is stopped.
- **Interface.** The Models page has a "Helper: Hydra 1.0" row at the top of the recommended picks. The task card says who planned, combined and reviewed (`reviewer_device/owner/model` in the record). A one-step task's reply shows its worker's model, not the planner's.
- **Mixed versions.** Older hubs ignore `prefer_model`, and older askers don't send it. An older build treats `hydra:1.0` as an ordinary chat model, so put it only on computers running 0.7.0.
- **Version:** `const Version = "0.7.0"` and the README title.

**Files changed (24).** All are uncommitted, in the same tree as the user's own uncommitted 0.6.1 + pluginScope work.
- Changed: `app/api.go`, `app.go`, `hub.go`, `hydra.go`, `main.go`, `ollama.go`, `ollama_monitor.go`, `plugin_chat.go` (two small edits: `headGate` sets `PreferModel`; `fastestChatModel` uses `ForChat`), `profile.go`, `runprompt.go`, `state.go`, `web/app.js`, `web/index.html`, `app/README.md`, `CLAUDE.md`, `README.md` ("New in 0.7"), `hydra1/README.md`, `tests/plugin-network/README.md`.
- New: `app/helper.go`, `app/helper_share.go`, `app/helper_test.go` (13 tests), `tests/plugin-network/fake_ollama_hydra.py`, `hydra_test.py`, `hydra_ui_check.py`.
- In `helper-model/` (untracked): new `eval-long/` (16 long review cases) and `run_long_reviews.sh`, and a README update (the command list no longer carries inline `#` comments).

**Tested.** All of this ran in the Linux cloud workspace against fake Ollamas, with a Linux build:

| Check | Result |
|---|---|
| Go tests (also with `-race`) | 44/44 |
| `run_it.py` | 27/27 |
| `heads_text_test.py` | 16/16 |
| `hydra_test.py` | 28/28, several runs |
| `hydra_ui_check.py` (Playwright) | 8/8 |
| darwin/arm64 and windows/amd64 builds | compile |

Also: a 600 MB stand-in file copied host to member in about 1.3 s, with both apps under 15 MB of memory.

Two things the tests and the review turned up:
- The first `hydra_test` runs showed the review regularly landing on a smaller model. That is why `helperWait` exists.
- A separate review found that install progress could crash the app if Ollama failed mid-copy. It was written from the HTTP transport's goroutine onto a finished response. This is fixed, and `TestHelperInstallSurvivesOllamaFailingMidCopy` shows the old bug with `-race`.

The Mac's whole `app/` was checked by hash: it is identical to what was tested.

## Checked on the Studio (Oct 29, from Claude Code)
Steps 1 to 4 and 6 of "Next, in order", plus a real Get from host. Step 5 was done on a separate test Chimera, see below.

- **Go tests:** 45/45, also with `-race` (44 plus the new review-limit test).
- **Ollama 0.40.1, real:**
  - `/api/show` for `hydra:1.0` has `FROM /Users/fx/.ollama/models/blobs/sha256-d2e366ef…` and `parameters` in the expected format. `helperOfferFrom` builds the right offer from it (path, digest, 2,889,512,416 bytes, numbers and two `stop`s).
  - `/api/create` with `files` from the existing blob made `copytest:1.0` with the same template, parameters and licence, and it answered. It has been removed; the blob stayed.
  - **Get from host** into a second, empty Ollama on this Mac (port 11435, its own models folder, through a member Chimera joined to a test hub): HEAD 404, the 2.9 GB upload in 2.3 s over loopback (201), `/api/create` in 0.16 s, and the copy answered. It has the same template, licence and parameters (in another order); only `parent_model` differs (`hydra-1.0.gguf`). The scratch copy is deleted.
- **The app:** `build.sh` builds all three. The running app says 0.7.0, its log has "helper: sharing hydra:1.0 with the network (2.9 GB)", and Models → Helper says "Installed, shared". A second launch of the same version opens the running one.
- **End to end, darwin build:** `run_it.py` 27/27, `heads_text_test.py` 16/16 (still "Internet: OPEN", the known sandbox bug), `hydra_test.py` 28/28. No Playwright here, so `hydra_ui_check.py`'s 8 checks were done by hand in the built-in browser on `hydra_test`'s two computers; all 8 hold.
- **Fixed:** the first `run_it.py` run failed "B starts lending: None of your models are shared". Until the hardware check is done (about 0.5 s after launch on a Mac, `system_profiler`), `usableMemory` is 0 and every model is `too_big`, so a Connect in that window finds nothing to share. Reproduced every time with the fake Ollama already up. `Node.Connect` now waits for the hardware check (up to 10 s). This predates 0.7.0.
- **A real looping long task** ("Keep going until done"), on a separate test Chimera (own data folder, closed network, the Studio's Ollama), sharing only gpt-oss:120b, qwen3.8:27b and hydra:1.0, then the same without hydra:1.0. The goal was a Blender 5 product-shot studio script: curved cyclorama, three area lights, 50 mm camera, settings at the top, how to run it.

  | | with hydra:1.0 | gpt-oss:120b only |
  |---|---|---|
  | plan | hydra:1.0, 6.4 s (incl. loading it); 3 `blender` steps | gpt-oss:120b, 12.3 s; a `code` and a `writing` step |
  | workers, combine | gpt-oss:120b, 49 s + 27 s | gpt-oss:120b, 33 s + 22 s |
  | review | hydra:1.0, 3.0 s: done | gpt-oss:120b, 6.8 s: done |
  | total | 85.9 s, 1 round | 74.2 s, 1 round |

  Both results crash in Blender 5.0.1 (`mathutils.radians`; unlinking objects from the scene collection that aren't in it), and both "cycloramas" are flat bevelled planes. Asked 3 times each with Chimera's own review request: gpt-oss:120b caught the `radians` crash 3/3 and passed the other 3/3; hydra:1.0 never named a crash, and its verdicts flipped between tries (done, done, not; not, done, not).
- **Long reviews:** `run_long_reviews.sh` (seed 7) gave 13/16 and 15/16, the same as the run already in `results/runs-long/`. With 5 unseeded samples per case (`--samples 5 --seed none`, like Chimera): hydra:1.0 67/80, gpt-oss:120b 74/80. Under 6,000 characters Hydra got 44/45 and caught 25/25 flawed results; from 8,300 characters it caught 6/15, against 14/15 for gpt-oss:120b (the Flask name mismatch 1/5, the cut-off report 3/5, the cut-off budget result 2/5). So reviews now go to the helper only up to `helperMaxReviewCtx` (3500, about 5,800 characters of result); planning and the Head check keep `helperMaxCtx`. Run 1's result (5,888 characters) would now just go to the biggest model.
- **Review temperature, measured (keep 0.7):** Hydra's reviews run at the Modelfile's 0.7 because Chimera sends none, and that is where the flipping comes from. The runner now has `--temperature`. With 10 unseeded tries per case, 0 makes verdicts repeat, but short-set accuracy drops from 81.7% to 75.0% (it then always rejects several good results). 0.2 matches 0.7, and no setting helps with long results. Measured the same unseeded way, gpt-oss:120b gets 92.9% on `eval/` (the seeded 22 vs 23 of 24 hid an 11-point gap). Its extra wins are arithmetic, correct short answers Hydra rejects, and word and line counts. Details in `helper-model/results/REVIEW-TEMPERATURE.md`. A deterministic check now does that, and more: see "Result check" below.
- **The handoff's step 5 recipe doesn't work on a Studio that isn't lending.** Steps then fall back to this computer, and `pickLocalModel` takes the helper for its jobs whether or not it's shared. gpt-oss:120b (65.4 GB) is also over the Studio's 57 GB lend limit, so the network never sees it.

## Not verified yet (the point of this handoff)
The Mac items (`/api/show`, `/api/blobs` + `/api/create`, a real long task, long reviews) are now checked; see above. Still open:
- **`/api/blobs` and `/api/create` on Windows.**
- **The 2.9 GB copy** over Wi-Fi and over Tailscale. It takes the host's upload bandwidth, two copies at a time.
- **Plan and review quality on more real tasks** than the one Blender task above.
- **The 3 s `helperWait`** and the 60 s stall limits on real networks.

## Next, in order
1. **Go tests on macOS.** Run `cd app && go test ./...`. If `go` isn't on PATH, use `/opt/homebrew/bin/go`.
2. **Check what real Ollama says about Hydra** before trusting the share:
   - `curl -s http://127.0.0.1:11434/api/show -d '{"model":"hydra:1.0"}'`: look at the `FROM` line of `modelfile` and at the `parameters` string.
   - On the Studio's own Ollama, test create-from-files by making a throwaway copy from the existing blob: POST `/api/create` with `{"model":"copytest:1.0","files":{"hydra-1.0.gguf":"sha256:d2e366ef…"}}` plus the template and parameters. Then `ollama rm copytest:1.0`. Don't name it `hydra…`: anything matching `hydra:` counts as the helper.
3. **Build and run 0.7.0.** Run `app/build.sh`, then open `dist/Chimera.app`; it replaces the running older build. Check:
   - Settings says 0.7.0.
   - `~/Library/Application Support/Chimera/chimera.log` has "helper: sharing hydra:1.0 with the network (2.9 GB)", not "can't share".
   - Models → Helper says "Installed, shared".

   Don't run the end-to-end tests while the real Chimera is (re)starting (see `CLAUDE.md`).
4. **End-to-end tests with a darwin build**, from `tests/plugin-network/`: `run_it.py`, `heads_text_test.py`, `hydra_test.py`, and `hydra_ui_check.py` if Playwright is installed.
5. **A real long task.** Run one with "Keep going until done" in Chimera. The card should say it planned and reviewed with `hydra:1.0`. Compare the speed and the plan with a gpt-oss:120b run. Long tasks ignore the composer's model picker, so for that run untick `hydra:1.0` under the Network page's model list (it then isn't shared), and tick it again afterwards.
6. **The long review eval.** Run `cd helper-model && bash run_long_reviews.sh` (about 10 minutes). Runs land in `helper-model/results/runs-long/`. If Hydra is much worse than gpt-oss:120b on long results, lower the review limit (in `app/hydra.go`, pass a smaller limit than `helperMaxCtx` for reviews) or plan Hydra 1.1.
7. **The other computers** (M4 Max, M4 Pro, the 3080 Ti PC, maybe a friend's AMD PC): install 0.7.0 first, from `dist/Chimera-mac.zip` or `Chimera-windows.zip`, then Models → Get from host. Check that the host's devices list shows `hydra:1.0` on each and that a Head check from another computer lands on a helper.
8. **Commit only when the user asks.** The user commits with GitHub Desktop. Their 0.6.1 + pluginScope work (`app/chat.go`, `hub_plugins.go`, `hubclient.go`, `plugin_chat.go`, `plugins_test.go`, `CLAUDE.md`, `README.md`, `heads/README.md`, `scripts/chimera-studio-install.sh`, `heads/hunyuan3d-mac/`) is still uncommitted and shares three files with this change. `helper-model/` is untracked; its `.gitignore` leaves out `data/` and raw replies.

## The user's rules for this work
- **No Claude outputs as training data** (Anthropic's terms). Training data is synthetic, from gpt-oss:120b on the Studio. `helper-model/eval/` and `eval-long/` were written by Claude and are **eval only**; they carry a canary, and `tools/check_overlap.py` checks training files for it.
- **Check the licence** of any model before committing to it. Qwen3-4B-Instruct-2507 is Apache 2.0.
- Say which parts couldn't be run or verified, and flag assumptions.
- Commands for the user to paste must have **no inline `#` comments**: zsh passes them as arguments.
- Don't delete the user's files without asking. `helper-model/data/sft.before-rules/` is a leftover awaiting permission.
- Commit or push only when asked. Don't add encryption or privacy work unprompted (`CLAUDE.md`).

## Ideas parked
- Hydra 1.1: write out arithmetic in review checks, and train on longer review inputs if `eval-long` shows a gap.
- An embedding classifier for the gate (data in `helper-model/data/classifier/`). Low priority: the LLM gate is 43/43 at about 90 ms.
- Reading Head options could become a fourth helper job; it isn't trained or tested for that now.
- "Largest" choosing only among the devices waiting at that moment predates this change. A short wait for the biggest model, like `libraryBigWait`, would help plans and combines when there is no helper.

## Result check (Oct 29, evening)
Looping mode now runs a round's Blender or Python script before the review, on the computer that asked, in a hardened sandbox; a definite crash, or a combine cut off at its output limit, means not done and goes to the next round as its critique. No prompt changed (check_prompts_sync.py stays green). The design came from a three-way design panel; a six-lens review with adversarial verification found 33 issues (about 15 distinct), all fixed, among them a real false crash (a script fenced inside a list item kept its indent), a stale "cut off" note after a later round recovered, and two sandbox holes (a script could kill the person's other processes, and fork to outlive the check). Details: `CLAUDE.md` (Architecture notes, "Result check"), `app/hydra_check.go`, `app/runner.go`.

A second review (the false-crash lens re-run, plus a check of every fix) found 16 more, all handled except low-severity "unsure where a crash was" parser gaps (exception groups, StopIteration): scripts that act on the person's selection or Edit Mode, installed add-ons, another computer's GPU backend or OS call, `--` arguments, multi-line import calls, a handled traceback, and finer Blender versions no longer count as crashes; `os.setsid()` can't escape the watchdog; a launcher without exec is resolved to its app.

Real runs on the Studio:
- The two Oct 29 scripts: caught in Blender 5.2.2 at lines 60 (`mathutils.radians`) and 136 (unlink from the wrong collection), and in 5.0.1; fixed copies pass. A 4K Cycles render stops at the render in 0.5 s and passes; a save outside the folder, a fork, a signal to another process, starting `open`, and reading the home folder are all blocked; a check's processes die within 2 s when Chimera is killed with kill -9.
- The same Blender studio task as before, looping, hydra:1.0 planning and gpt-oss:120b working: round 1 crashed (`'BevelModifier' object has no attribute 'offset'`), round 2 crashed differently (`'depth'`), round 3 passed and was reviewed done by gpt-oss:120b (the result was over the helper's review limit). 414 s in all; before the check, the loop stopped after round 1 with a script that crashed.
- A second real looping task (a low-poly rocky island, Blender 5.2.2): every round crashed on a different, real Blender API mistake (`use_auto_smooth` and the `Transmission` socket, both removed in 4.x, among them), so it used all 6 rounds (14 min) and ended unsure. Each critique named only the first error, so the crash critique now says that running stops at the first error and asks for the rest to be checked against that Blender's API. Re-run with that text: round 1 crashed (`NoiseTexture.noise_scale`), round 2 was unsure (its script imports a second file of the result, which the check doesn't assemble), and gpt-oss:120b reviewed it done, in 275 s. One run each; the models' Blender 4/5 API knowledge, not the loop, is the limit here.
