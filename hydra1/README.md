# Hydra 1.0

Hydra is how Chimera handles a long task: one big job turned into small pieces that several computers work on at once. It isn't a separate model. It's a set of steps and system prompts inside the Chimera app (`app/hydra.go` and `app/prompts.go`), run on whatever models the network is lending.

## What happens when you start a long task

1. **Plan.** The task goes to the biggest model lending on the network (for your group, gpt-oss:120b or Llama 3.3 70B on the M3 Ultra). It replies with a plan in JSON: a title, the kind of task (code, writing, research, Blender or general), a short summary, and 2 to 7 steps. Steps say which other steps they need, so independent steps can run at the same time. The planner also sees the last few messages of the chat and any checked library entries that match the task.
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

Turn on **Keep going until done** with a long task and Hydra doesn't stop at one pass. After combining, the biggest model reviews the result against your goal and answers: is this done, and if not, what's missing? If it's not done, Hydra plans another round that builds on the previous result and fixes what the review flagged, runs it, and reviews again — up to six rounds, stopping as soon as the result is good enough. The task card shows the round it's on and when it's reviewing. This is the BlenderGym finding in practice: more rounds of generating and checking beat a single pass from a bigger model.

While a long task runs, your own idle computers connect on their own to help with the steps and stand down when it's finished.

## The library: distilling ourselves

When you rate a reply 4 or 5 stars and say what worked, the biggest model on the network turns it into a reusable entry (code, a Blender script, a lesson or a prompt template). Entries are reviewed by the biggest model, Python and Blender scripts can be test-run on the host's computer, and anything that fails waits for the host to review. Over time the library becomes the network's own memory of what works, built from your own best answers rather than from anyone else's models. The host can export every rated reply from the Library tab as training data for a small model of your own.

## Where to change things

- Planner, worker, combiner, curator and reviewer prompts: `app/prompts.go`
- How plans run (parallelism, retries, library reuse): `app/hydra.go`
- How the library is checked: `app/library.go`
