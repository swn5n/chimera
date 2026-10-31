# Hydra 1.0

Hydra is how Chimera handles a long task: one big job turned into small pieces that several computers work on at once. It's a set of steps and system prompts inside the Chimera app (`app/hydra.go` and `app/prompts.go`), run on whatever models the network is lending, plus a small model of its own, also called Hydra 1.0 (`hydra:1.0`), that plans the work and reviews it (see "The helper model" below).

## What happens when you start a long task

1. **Plan.** The task goes to the helper model, Hydra 1.0, on any computer the task may use that has it. If none has it, or the task is too long for it, it goes to the biggest model lending on the network (for your group, gpt-oss:120b or Llama 3.3 70B on the M3 Ultra), as before 0.7.0. The planner replies with a plan in JSON: a title, the kind of task (code, writing, research, Blender or general), a short summary, and 2 to 7 steps. Steps say which other steps they need, so independent steps can run at the same time. The planner also sees the last few messages of the chat and any checked library entries that match the task.
2. **Check the library.** Before a code or Blender step goes to a model, Hydra looks for a verified library entry that is clearly the same thing. If there is one, the step uses it as is and no model runs.
3. **Work.** The other steps go out to lending devices, as many at a time as there are devices lending (up to 4). Each worker gets a system prompt that says it's one of several AI workers on different computers, shows the whole plan with its own step marked, and adds rules for that kind of task:
   - code: complete, working code for its piece only, matching the names other steps rely on
   - writing: polished prose for its section only, in the project's tone
   - research: specific findings, unsure points marked (unverified), no invented sources
   - Blender: one headless bpy script for its piece, with new objects named `chimera_…`
   - general: its piece only, done thoroughly
   A step that depends on others also gets their output. A failed step is tried once more.
4. **Combine.** The biggest model merges the pieces into the finished result, with rules for the kind of task (for code, every file in full with run instructions; for Blender, one combined script).

You see every step in the chat as it happens: which computer and model is on it, its output, and the final result. Credits are charged per step like any other request.

## Keep going until done (looping)

Turn on **Keep going until done** with a long task and Hydra doesn't stop at one pass. After combining, Hydra 1.0 (or, without it, the biggest model) reviews the result against your goal and answers: is this done, and if not, what's missing? If it's not done, Hydra plans another round that builds on the previous result and fixes what the review flagged, runs it, and reviews again — up to six rounds, stopping as soon as the result is good enough. The task card shows the round it's on and when it's reviewing. This is the BlenderGym finding in practice: more rounds of generating and checking beat a single pass from a bigger model.

While a long task runs, your own idle computers connect on their own to help with the steps and stand down when it's finished.

## The helper model (Hydra 1.0, from Chimera 0.7.0)

Hydra 1.0 is a small model trained for three jobs, with exactly the prompts Chimera sends: Hydra's planner, Hydra's reviewer, and the check that decides whether a Head should handle a words-only request. It's Qwen3-4B-Instruct-2507 (Apache 2.0) with a LoRA trained on synthetic data from gpt-oss:120b on the Studio, quantized to Q5_K_M: 2.9 GB on disk and about 4 to 4.5 GB in memory with its 8K context, so every computer can run it whole. On the eval it wrote 41 of 44 plans that fully match the format (Chimera accepts all 44), got 22 of 24 reviews and 43 of 43 Head checks right, in about 4 s a plan, 1 s a review and 0.1 s a check on the Studio. Its known weak spot: it doesn't redo arithmetic when it reviews. Training, eval and results: `helper-model/`.

- **Where it runs.** A step for one of its jobs asks for it (`prefer_model`). Any computer the step may run on that has it gets the step ahead of all others; if that computer is free but between two steps, the step waits up to 3 seconds for it, but it never waits for one that's busy. The Head check still never runs on the asking computer when the Head is someone else's. With no such computer, the step goes where it always did: the biggest model for the plan and the review, the fastest for the Head check.
- **What it never does.** Chats, worker steps, combining, library jobs and reading a Head's options never go to it, and the chat's model picker doesn't list it. Its training covered only its three jobs.
- **Too big for it.** Plans and reviews that don't fit Chimera's 8K context (roughly 13,000 characters of input for a plan, 16,000 for a review) go to the biggest model. Hydra 1.0 was trained on inputs up to that size; the eval only checks reviews of short results, so its reviews of long ones are less proven.
- **Second chance.** If Chimera can't read the helper's plan or review, it asks once more without the helper.
- **Getting it.** The host hands out its own copy: on each computer, **Models → Helper → Get from host** copies it into that computer's Ollama with the same template and settings. Only install it on computers that run Chimera 0.7.0 or newer; older ones treat it as an ordinary chat model.

## The library: distilling ourselves

When you rate a reply 4 or 5 stars and say what worked, the biggest model on the network turns it into a reusable entry (code, a Blender script, a lesson or a prompt template). Entries are reviewed by the biggest model, Python and Blender scripts can be test-run on the host's computer, and anything that fails waits for the host to review. Over time the library becomes the network's own memory of what works, built from your own best answers rather than from anyone else's models. The host can export every rated reply from the Library tab as training data for a small model of your own.

## Where to change things

- Planner, worker, combiner, curator and reviewer prompts: `app/prompts.go`. Hydra 1.0 was trained on these exact planner and reviewer prompts (and the Head check's in `app/plugin_chat.go`): change them and the helper needs retraining (`helper-model/`).
- The helper model, its size limit and where it may run: `app/helper.go`; getting it from the host: `app/helper_share.go`
- How plans run (parallelism, retries, library reuse): `app/hydra.go`
- How the library is checked: `app/library.go`
