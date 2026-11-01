# The first long task across three computers (Oct 31, 2026)

One real looping long task, started from the Studio with "Keep going until done": a Blender tabletop scene with a table,
mug, lamp, lights and camera. All three computers ran Chimera 0.7.0: FX3 (the Studio), FX2 (M4 Max) and FX4 (3080 Ti,
Windows). Task `b7c2326f0d4b`, session `e67e7ffd2d58`. Two independent audits read the raw events and the code. Every
round's script, the hub samples and the event stream are in `~/chimera-tools/joint-task-20261031/`, because the stored
session keeps only the last round.

## What worked

- 32 minutes, 5 of 6 rounds, 23 worker steps: 11 on FX3, 8 on FX2, 4 on FX4. All 34 hub jobs finished: nothing failed,
  retried, requeued or moved.
- Windows and an Ollama as old as 0.17.0 both worked as lenders, and `done_reason` travelled through the hub from Windows.
- `hydra:1.0` made all 5 plans, valid first time, in 6-13 s at 111-121 tok/s.
- The result check gave a real verdict in about 1 s each round, and every outcome reproduced with `chimera --check-result`.
- Credits balance exactly: FX_M3 -78.05, FX2 +48.25, FX3080ti +29.80.
- The final reply said plainly that the script still crashes.

## What it didn't do

It never produced a working script. Round 1 stopped on an IndexError the check called unsure; rounds 2-5 crashed in
Blender 5.2.2, and rounds 4 and 5 hit the same `Specular` KeyError, so the same-fault rule ended the task.

| Round | Crash | Fix that would have got past it |
|---|---|---|
| 1 | `bezier_points.add(1)` then writing 3 points (IndexError) | `add(2)`, and the check then passes |
| 2 | `block.clear()`: no such method | Several more faults behind it |
| 3 | `splines.new('NGON')`: no such type | Several more faults behind it |
| 4 | `inputs["Specular"]`: renamed `Specular IOR Level` | That one token, and the check then passes |
| 5 | `inputs['Specular']` again, in new code | At least 4 kinds of fault behind it |

"Passes" means no crash; no scene was inspected. Round 5, which the person received, was further from working than rounds 1
and 4.

## Findings, biggest first

1. **A later round can't edit the result.** Only the planner sees the previous script and the critique. Workers and the
   combine get neither (`hydra.go`: planner at 476, worker at 912-924, combine at about 576), so every round is a rewrite:
   consecutive rounds kept 6-15% of their lines. Suggested: from round 2, give workers and the combine the previous script
   and the check's error, or try a one-step mend (the whole script plus the traceback) before spending a round.
2. **The combine is where the crashes come from.** Four of the five crashes were lines no worker wrote. This is the case for
   the worker contract's joining with no model (`docs/hydra-worker-plan.md`).
3. **The task delivers the last round, not the best one.** Nothing compares rounds, and the session keeps only the last.
4. **Routing is nearly all size** (worker steps fixed, see Routing below; chats still work this way). `hub.go:1005` is size x 10 + loaded x 30 - eta, with eta assuming 500 tokens. So
   `deepseek-r1:70b` at 15 tok/s took 69% of the run's wall time for 21% of its tokens, while FX2 sat at 75 tok/s, and
   round 3's whole chain ran there with both other computers idle. The audit estimates about 19 minutes instead of 32 with
   a faster model, on the same tokens. Whether the output would be as good isn't measured.
5. **The combine's budget cut a whole script.** `60000 / len(steps)` (`hydra.go:577`) gave round 4's six steps 10,000
   characters each, and cut a 16,052-character worker script that passed with one line removed. Cut only when the total
   is over the limit, longest first.
6. **A worker cut off at its window counts as done and is paid.** Round 4 s3 (FX4) spent all 8,192 tokens thinking, returned
   nothing, and was charged 8.90 credits. Treat a `length` stop with empty text or an open code block as a failed attempt.
7. **Thinking eats the 8K window.** FX4's `qwen3.5:9b` spent about 92% of 26,231 tokens on hidden thinking. This confirms
   Next item 7 in CLAUDE.md.
8. **An unsure crash reaches nobody.** IndexError isn't in the check's failing list, and an unsure run's error isn't passed
   on, so round 1's one-character fix was lost. Add it to the list and pass unsure errors into the next critique, which is
   data, not a prompt change.
9. **Hydra's plans are valid but often unhelpful.** Four of five ended in a "combine everything" step its prompt forbids
   (668 s on the slow model), and some dictated the very name that had crashed (`bpy.data.meshes.clear()`, "NGON",
   `Specular`). `cleanPlan` could drop such a step; the rest is for Hydra 1.x's data. `hydra:1.0` reviewed nothing here:
   all five results were over its size limit, as designed.
10. **Smaller things.**
    - The Studio's two big models evict each other every round: about 3 minutes.
    - The task stream sent 78.9 MB, with 1,759 events identical to the one before.
    - `deepseek-r1:70b` shows as three rows, which inflates "lending 47 models".
    - The reply body still claims a working scene under the failure note.
    - `wm-probe-*` test models were scored but never picked.

None of these needs a change to the planner, reviewer or gate prompts.

## Fixing the loop (Oct 31, same day)

Findings 1, 3, 5 and 8 are fixed, and 2 is smaller: the combine only writes edits from round 2 on. Findings 4, 6, 7, 9 and 10
are not. The evidence is in `~/chimera-tools/joint-task-rerun-20261031/`: the runs in `runs/`,
renders in `looks/`, and the repair test in `mend-experiment/`.

**What changed**

- **Repairs.** A script that crashes gets up to 8 quick repairs inside its round (5 at first; see "The real names"): a model gets the script and the error and
  replies with FIND/REPLACE edits, Chimera applies them to the script and runs it again (`hydra_mend.go`, new prompt
  `hydraMendPrompt`). A repair that leaves it worse is taken back, and two tries in a row that get nowhere end it.
- **Later rounds edit.** Workers and the combine see the result so far and the critique. For a script the combine replies
  with edits (`synthEditPrompt`), unless the last result was cut off. A round whose edits change nothing isn't reviewed
  again, and two such rounds stop the loop.
- **Best round.** The person gets the best round, and the next round works from it. Order: a script with nothing known to be
  wrong, one that runs part-way, one that doesn't start, no script, cut off. Ties go to the later round. Two rounds in a row
  that don't improve stop the loop, and a reply from an earlier round says so.
- **Smaller.** The combine's budget only cuts when the total is over 60,000 characters, longest first. An out-of-range index
  into something the script made counts as a crash. No trained prompt changed.

**Which reply format.** Tried on the five real crashing scripts from this task, each with a real Blender check after every
try. Coder-Next heretic with edits, three tries each and up to 5 repairs: 7 of 15 passed, 2,707 tokens and 93 s on average.
The same model writing the whole script back, up to 4 repairs: 2 of 5, 8,162 tokens and 134 s. `qwen3.8:27b`, before the
indent fix: edits 3 of 5, whole script 2 of 5, and two whole-script tries ran out at 8,192 tokens with no script. Told to
change little, models didn't rewrite (82-100% of lines kept either way); edits are simply cheaper and can't turn into a
rewrite. Most missed edits had the right lines and the wrong indent, so Chimera now matches without the indent.

**Real runs on the pool.** Nine runs, on two goals. "Runs" means the delivered script ran to its end in a fresh Blender 5.2.2,
or in 5.0.1 for rerun 0, outside the check as well.

| Run | Build | Goal | Time | Rounds | Repair tries | Script runs? |
|---|---|---|---|---|---|---|
| First run, Oct 31 | 0.7.0 | Tabletop | 32 min | 5 of 6 | none (didn't exist) | No |
| Rerun 0 | before the reviews | Tabletop | 5 min 14 s | 1 | 3 | Yes |
| Rerun 1 | before the reviews | Tabletop | 6 min 28 s | 1 | 1 | Yes |
| Rerun 2 | before the reviews | Tabletop | 10 min 49 s | 1 | 4 | Yes |
| Rerun 3 | before the reviews | Island | 6 min 26 s | 1 | 5 | Yes |
| Rerun 4 | before the reviews | Tabletop | 11 min 40 s | 2 | 2 | Yes |
| Final 1 | after both reviews | Tabletop | 10 min 52 s | 2 | 0 | No: `bpy.context.region` is None with `-b`, called unsure |
| Final 2 | after both reviews | Island | 13 min 22 s | 3 | 8 | Yes |
| Last 1 | the final build | Tabletop | 5 min 21 s | 1 | 2 | No: saves to `/`, and the reply says so |
| Last 2 | the final build | Island | 21 min 8 s | 2 | 8 | No: a wrong `NoiseTexture` name, and the reply says so |

So 6 of 9 scripts ran, in 5-21 minutes, against one 32-minute run with none. On the final build it's 0 of 2. These are too few
runs to give a rate, and the models decide much of it. What the final build does reliably is keep the script and say what's
wrong: all of last 1's and last 2's repairs kept 97-100% of the lines, and both replies carry a note. On Oct 29 the island
task used all 6 rounds and ended unsure, in 14 minutes.

Rerun 0's asking test instance lent itself (`auto_help`), so it ran on the Studio alone; the others had that off. Rerun 2's work
landed on FX3 by routing, not by choice. Rerun 4 was meant to be on the final build, but the old test instance was still
running, the new one quit with "already running", and the run used the older one. Its data is real and is labelled as such
above.

Final 1 is why the check changed again. Its script crashes when run as the task said, with `blender -b`, but "NoneType" counted
as maybe the computer's fault. So it was unsure, got no repair, was reviewed done, and had no note. Now a task that says
`-b` or headless can't blame Blender's missing window, a script that stopped on any unjudged error carries a note on the reply,
and that error goes into the next round's critique.

**Later rounds, for real.** Reruns 4, final 1, final 2 and last 2 reached round 2 or 3. In final 2 the combine's edits kept 91-98%
of the lines between rounds; in rerun 4, 72% (last night 6-15%). Rerun 4's round 2 and final 2's round 3 each crashed on the
edits, were repaired, and passed.

**What this didn't fix.**

1. **Passing doesn't mean right.** Models can't see a render, and the reviewer called every script that ran done. Rendered and
   measured:
   - Rerun 0: the mug is cut off at the top of the frame, and the lamp is barely in it.
   - Rerun 1: everything is in frame, but the table is upside down, its legs pointing up, and the mug is a tiny flat ring.
   - Rerun 2: a black frame. The camera sees none of the 6 objects.
   - Rerun 3: grey cones on blue water, most of the island out of frame, the trees with no material.
   - Rerun 4: a close-up showing part of the table and one round shape, with the default cube still in the scene.
   - Final 2: almost empty. 9 of 13 objects are out of frame, and the default cube is still there.

   Some of this can be measured: objects inside the camera's view, and the default cube left behind. A camera that sees
   nothing is a crash of a kind.
2. **Models don't know the API, and repairs can only guess.** `Specular`, `Transmission`, `Emission`, `Displacement`,
   `NoiseTexture.noise_scale`. Last 2 tried 8 times on one line. (Addressed below.)
3. **Scripts still write to places that only look right.** Last 1 saves next to an empty `bpy.data.filepath`, which is `/`.

**Edits work when the critique is right.** Rerun 0's script with a real critique written from its render (the camera and the
handle), two real workers and a real combine on the edit prompt: 2 edits in 957 tokens and 19 s, 94% of lines kept, the check
still passes, and the render has the table, the mug with its handle and the lamp all in frame. That's the case for giving
the loop better facts rather than more rounds.

## The real names (Oct 31, same day)

When a script stops on a wrong name, the check now lists the real ones, and repairs and later rounds get them in the critique.
No trained prompt changed. For example:

```
RenderSettings has no file_format: that's on its image_settings. What it does have: …
bsdf.inputs has no "Specular". What it does have: "Specular IOR Level", "Specular Tint", …
bmesh.ops.extrude_face_region has no keyword faces. The keywords it takes: geom, …
```

A hook in the check's prelude (`blenderCrashNames`, `runner.go`) runs as Blender dies. It looks at the real object: attributes,
collection keys, and the keywords of `bpy.ops` and `bmesh.ops`, closest matches first. It also says where a name really lives, by
following pointers, and lists the real operators for one that doesn't exist. Only Blender 5.2's Python hands over the object on
every error, so the hook works it out from the failing statement. It worked on 5.2.2, 5.0.1 and 3.6.23.

Two reviews went at the hook in real Blender, and they mattered. The first version could turn a crash into "unsure" through
a Python warning, run the script's own properties a second time, and name the wrong object on a busy line. It's now deny by
default: it reads only what can't run the script's code, and says nothing unless it can show this object is the one that
failed. The check also stopped excusing an operator that doesn't exist, unless Blender has no such family of operators or the
task is about an add-on: that excuse was ending repairs on real crashes.

**Measured.** The five crashed scripts from the first run plus two later ones, three tries each, on Coder-Next heretic, with
Chimera's repair rules and real Blender checks, with and without the names.

| Repairs allowed | Names | Passed | Tokens per script | Time per script |
|---|---|---|---|---|
| 5 | yes | 12 of 21 | 2,604 | 42 s |
| 5 | no | 12 of 21 | 4,356 | 66 s |
| 9 | yes | **18 of 21** | 2,817 | 47 s |
| 9 | no | 11 of 21 | 6,022 | 92 s |

At 9, on the same script and try, only the names passed 8 times and only the plain version once (sign test p = 0.04). At 5 the
gain doesn't show, because scripts have many separate faults and ran out of repairs while still moving: each repair cleared
its error 91% of the time with names and 76% without. Every pass came within 8 repairs, so `hydraMends` is now 8. These are 7
scripts on one model, and the plain version's 12 and 11 show the noise is a run or two. The test harness is a Python copy of
the repair rules, not Chimera itself.

**Real runs on the final build**, with the test Chimera confirmed by its process this time.

| Run | Goal | Time | Rounds | Repairs | Computers | Script runs? | What the camera sees |
|---|---|---|---|---|---|---|---|
| Names 1 | Tabletop | 6 min 48 s | 1 | 3 | FX2, FX3, FX4 | No: saves to `/`, and the reply says so | |
| Names 2 | Island | 24 min 5 s | 2 | 9 | FX2, FX3, FX4 | Yes | Parts of its 3 objects, one the default cube |
| Names 3 | Tabletop | 9 min 54 s | 1 | 6 | FX3 only | Yes | None of the 6 objects |
| Names 4 | Island | 5 min 31 s | 1 | 2 | FX2, FX3, FX4 | Yes | None of the 8 objects |

So 3 of 4 ran, and with the 0 of 2 before the names and the repair limit that's better, though four runs can't prove a rate.
Names 2 spent 8 repairs on three lines: the model kept trying `NoiseTexture` attributes with the list in front of it, because
what it wanted doesn't exist there. The list says what's real, not what to do instead.

The scene check below came next.

## The scene check (Oct 31, same day)

A script that runs can still build the wrong thing, and the reviewer can't see a render. So after a script finishes, or as its
render starts, the check measures the scene it built (`blenderSceneFacts`, judged in `hydra_scene.go`). If it's certainly wrong, the
outcome is `wrong_scene`: no review, repairs with the measurements, then the next round. It needs no GPU, so it runs in the sandbox.

**It claims little, on purpose.** The first version counted what rays reached. Two reviews wrote scenes a person would keep and set
it off: a snow globe (rays stop at glass), softbox cards kept out of shot, 400 tiny stars falling between rays, an interior with a
wall behind the camera, a cube the script kept on purpose, "Model a wooden picture frame". A false alarm costs repairs that can
damage a good scene, while a miss costs nothing new, so it now says only:

- **Out of frame**, by bounding box, when the task says to frame everything and the camera isn't standing among the objects.
- **The camera sees none of them**: nothing reached at all and every box outside the frame, in a task that builds a scene or frames everything.
- **No camera**, when the task clearly wants one.
- **No geometry**: a plain mesh with no vertices.
- **The default cube**: the original factory object, untouched, in a task that builds a scene and doesn't mention a cube.

Tasks on the person's own file, add-ons, animation, several scenes and goals not in English go unjudged. All 45 false-alarm scripts
from the second review now pass; they're in `~/chimera-tools/joint-task-rerun-20261031/scene-experiment/false-alarm-scripts/`, and the
tests carry the cases.

**What it costs and misses.** It says nothing about shape, scale or light: run 1's upside-down table passes, and an object only
partly in frame counts as in. Goals in other languages get no scene check at all.

**Telling a repair what to do.** Reporting the fault wasn't enough. On 10 real scripts, 3 tries each: 15 of 30 fixed with only the
fault, 16 of 30 with measurements and a place to stand. The models moved the camera and left it pointing the wrong way, because
they can't work out a rotation. So the check now works one out, tries that view with the same rays, and hands over the two
numbers ("with rotation_mode = 'XYZ', location = ..., rotation_euler = ..."): **26 of 30 fixed**, at 1.9 repairs, 2,561 tokens and 37 s
per script. That test used a build from before the rules were narrowed, and a Python copy of the repair rules.

**Real runs** on the pool, with the test Chimera confirmed by its process each time.

| Run | Goal | Time | Rounds | Repairs | Script | The result |
|---|---|---|---|---|---|---|
| Scene 1 | Tabletop | 10 min 34 s | 1 | 2 | Runs | All in frame, very dark, a table like a barrel |
| Scene 2 | Island | 3 min 42 s | 1 | 0 | Stops: an edit-mode operator in object mode, and the reply says so | |
| Scene 3 | Tabletop | 7 min 26 s | 1 | 1 | Runs | All in frame, table too tall |
| Scene 4 | Island | 10 min 12 s | 2 | 6 | Runs | An island in the sea, all in frame, a tree floating |
| End 1 | Tabletop | 7 min 9 s | 1 | 2 | Runs | Table, mug and lamp, the lamp's top cut off |
| End 2 | Island | 4 min 32 s | 1 | 8 | Runs | Trees and a pier in a cropped close view |
| End 3 | Tabletop | 6 min 48 s | 1 | 4 | Runs, but can't save its render | Table, mug and lamp all in frame, the mug flat |
| End 4 | Island | 4 min 48 s | 1 | 0 | Stops: a modifier looked up by a wrong name, and the reply says so | |

Six of eight scripts ran with their subjects in frame, against none of the first runs: the black frames and the shots of nothing are
gone. Scene 1 shows the new path: a crash repaired, two objects found out of frame, repaired, passed. But these are crude pictures,
not good ones. Scale, placement and light are still poor, and nothing checks them.

Scene runs used a build before the second review, End runs the build before one last fix to the card's wording; the final code
differs from End's only in that line.

**Still open.**
- End 3 saves to `//render.png` with no saved file: Blender can't write that, and the check stops before the render, so it passes.
- Scene 2 and End 4 stopped on errors the check won't judge (`poll()` failed, a key on something the script made): they get a note but no repair.
- What a model can't be told: proportions, things floating, light. A person, or a model that can see, has to judge those.

## Routing (Oct 31, same day)

A real long task after the scene check ran all three steps on the Studio's deepseek-r1:70b (294 s of its 342 s), with FX2 and FX4
idle. Size won every step. The 203 real steps say size is the wrong thing to go by:

| Computer and model | Steps | Median time | Tokens/s | Median tokens | Median characters |
|---|---|---|---|---|---|
| FX2 gpt-oss:20b | 79 | 22 s | 73.7 | 1,389 | 2,041 |
| FX3 deepseek-r1:70b | 83 | 104 s | 15 | 1,251 | 2,308 |
| FX4 qwen3.5:9b | 40 | 131 s | 52 | 6,853 | 932 |

FX4's speed looks healthy, but most of its tokens are hidden thinking, so no speed figure a computer reports would have shown this.

**The rule** (`app/hub_workers.go`). Worker steps now send `prefer: "worker"` and the task's id. The hub learns the seconds a step
really takes for each computer and model (`worker_secs` in `hub.json`), and a step goes to the lowest cost: those seconds, or a guess
from speed for a model not yet timed, plus load time if it isn't loaded. Three things push against a pick:

- 45 s for each step that computer already did for this task, up to 2, so a chain spreads when computers are close, and a long
  task doesn't keep handing turns to a much slower one.
- 600 s for a model never timed, so the 32 leftover `wm-probe-*` models don't get real work on paper speed.
- 1,000 s for a model under 8B, more than the 600 s, so a timed tiny model can't beat an untimed proper one.

A step that came back empty or cut off counts 300 s worse, since a model that gave up quickly isn't quick. If a computer at least 45 s
better is free but not asking at that moment (it has usually just finished the step before), the step waits up to 3 s for it, as a
helper step does. Chats, the combine and the only step of a one-step plan keep the old scoring: they are the answer, not a piece
of it. Nothing about the planner, reviewer or gate changed.

**What it does on paper.** With no timings the live fleet comes out close, so steps spread: FX3 qwen3.8:27b 31 s, FX2 gpt-oss:20b
34 s, FX4 qwen3.5:9b 32 s. With timings: FX2 22 s, FX3 31 s, FX4 131 s. A chain of 23 steps goes FX2 21, FX3 2, FX4 0, in 522 s of
step time. A round of side-by-side steps uses every free computer.

**Review.** An independent review found five faults, fixed above: a timed tiny model beat an untimed proper one, a lone step
went to the quickest model though it is the whole reply, an empty reply read as quick, the spread had no limit, and timed models
ignored load time. It also raised a much better computer losing a step while between polls, which is the 3 s wait.

**Decided against, for now: holding a step for a busy computer.** A free slow computer takes a step even when a busy fast one would
finish sooner. The reviewer's version compares real seconds and helped a simulation (148 to 133 s a plan, no-answers 6.8% to 3.9%),
but it was 4% worse on one fleet, and FX3's samples there are another model's times scaled down. It's more rule on top of a rule
that hasn't run on the real pool yet. If real tasks show FX4 holding up rounds, the patch is in the review's journal; turning thinking
off for worker steps may fix the cause instead, and would need an A/B.

**Tested.** Go 95/95 (also `-race`), `hydra_test.py` 126/126, `run_it.py` 27/27, `heads_text_test.py` 16/16. Each fix was broken on
purpose and a test failed for it, and so did unplugging the rule from Hydra (11.20b, end to end). Spreading moves test credits between FX_M3, FX2 and FX3080ti, since they are different owners. Chains aren't flattened: a chain still
runs one step at a time, it just no longer runs them all on one computer.

**On the real pool.** With the Studio restarted on this build (FX2 and FX4 not updated, since the rule lives on the hub and in the
asker) the same goal ran twice from the Studio's Chimera, one run after the other:

| Run | Worker steps | Worker time | Whole task |
|---|---|---|---|
| Before routing | FX3 deepseek-r1:70b, three times | 294 s | 342 s, 1 round |
| First, nothing timed | Round 1: FX3 54 s, FX4 189 s, FX2 52 s. 13 steps over 3 rounds: FX2 9, FX3 3, FX4 1 | 729 s | 859 s, 3 rounds |
| Second, timed | FX2 26 s, FX3 48 s, FX2 25 s | 99 s | 178 s, 1 round |

The first run's round 1 is the spread the rule predicts, and its 189 s on FX4 is what the hub learned from: FX4 got no step after that,
and FX2 and FX3 did the rest. Timings after both runs: FX2 gpt-oss:20b 29 s, FX3 the 80B coder 43 s and qwen3.8:27b 53 s, FX4 qwen3.5:9b
189 s. No step failed, and all three computers stayed in the pool through the restart. A round of three or more steps side by side
hasn't happened with timings known, so whether FX4 holds such a round up is still unmeasured. These are single runs, and a task's total
depends on how many rounds the loop takes.

**What they made.** Routing moved the work; it didn't make the scripts better. Neither run's script finished, and both replies say so
in their note. The first stopped at `scene.render.engine = 'EEVEE'`: the name is `BLENDER_EEVEE`, Blender's error lists the real names,
and the check still called it "unsure" because `envReason` (`hydra_check.go:637`) takes any unknown engine for an add-on's, so no
repair was tried. With that name corrected the scene shows a cup on a table with a lit patch beside it, far better framed than the
dark table corner before routing, though the lamp reads poorly. The second stopped at `cycles_prefs.get_devices()`, which returns nothing
to iterate, and has no camera at all: the goal doesn't mention one, so the scene check stayed silent, and the reviewer called it done.

## Everyday goals (Oct 31 to Nov 1)

The routing runs showed two faults. The check took any unknown render engine for an add-on's, so `'EEVEE'` got no repair, and it took
any `NoneType` crash for a fresh scene's doing, so `get_devices()`, which returns nothing on every Blender 5, got none either and the
scene was never measured. And a goal that doesn't mention a camera got no scene check at all: your first coffee cup render was a dark
table corner, with 40% of the cup in frame, and it passed.

**The change.** Blender's own engines, by any name, now count as the script's mistake (`ownEngineRe`). A `NoneType` crash does too, if
the goal builds a scene from nothing and the script reads nothing from a window, an add-on, the command line or a file. A goal that asks
for a scene (`newSceneRe`: scene, landscape, diorama, still life) now wants a camera, and that camera has to show what the goal names:
`goalThings` takes the last word of each noun phrase, and if objects with that word exist and none is in frame, it's a fault, with the
worked-out view for the repair. If there's no camera, the check works out a view with a temporary one. An object counts as out if its box
is, or if the frame could hold it but holds under half and under 2% of the rays reach it (12 rays for a rod). A plain mesh with a
material and no faces now counts as having no geometry: a real repair built fruit that way, from `create_uvsphere` with no segments.

**What the reviews changed.** The first version also had a count rule, "more than half the objects are out of frame". Reviewers wrote
real scenes aimed at both rules and read every render:

| Test | First version | Final |
|---|---|---|
| 280 good script and goal pairs | 90 flagged on the 203 that aren't real-run scripts | 24, of which 22 are real-run scripts rightly flagged, and F6 and s15 really are cut off |
| 63 scenes built to be bad | 22 caught | 23 caught |
| 58 scenes in chat wordings, 17 of them aimed at weak spots | 16 flagged, all among the 17 | 0, and all 8 bad ones caught |
| 73 scripts from qwen3.8:27b, judged by eye | 3 of 22 good flagged, 31 of 51 bad caught | 2 of 22 good, 31 of 51 bad |

The count rule went: it fired on 37 good pairs and 3 bad ones, because a wall of tiles or a forest is mostly out of any good picture, and
no number separated those. The last two rows' fixes were written after seeing those scenes, so they aren't held-out figures. The two
left on good model scripts are accurate: one's ground really has no geometry, and the other's reeds are mostly out of shot. Other things
that went in from the reviews: position words, a verb read as a noun, what's in a cup, a light source that can stand outside the shot, a
place word that only an extra carries (`isPlace`: a Garage_Door above the frame says nothing about the garage once the bike shows), wordings that
rule out a camera or say what it's for, and a word must match exactly to say something is missing, though it may start a longer word
to say something is shown. Rules for one object filling the frame, a scene that's a speck and bare ground were built and tested by a reviewer and left
out, because each needs its own word list or threshold and a miss costs nothing new. The patch is in the review's journal if real tasks ask for them. Mutation testing ran 413 single changes: 306 survived the first tests, and the tests added
(`hydra_scene_limits_test.go`, `hydra_scene_real_test.go`) kill 292 of those, and the other 14 are equivalent or don't matter.

**Real tasks on the final build**, from a test asker, on the pool's new routing:

| Goal | Time | Rounds | Repairs | Script | What it made |
|---|---|---|---|---|---|
| Coffee cup, table, lamp | 2 min 10 s | 1 | 0 | Runs | The cup is buried inside a 1.5 m cube used as a table |
| Bowl of fruit on a kitchen table | 4 min 35 s | 1 | 8 | Runs | All there, small, the fruit under the table |
| Campfire, two logs, a tent | 3 min 15 s | 1 | 3 | Runs | Reads as a campfire, the best of the set |
| Teapot and two cups on a tray | 6 min 25 s | 1 | 4 | Stops at line 362, and the reply says so | |
| Red bicycle against a brick wall | 11 min 23 s | 3 | 5 | Runs | The camera sees nothing |
| Rocky island, palm, pier | 4 min 41 s | 1 | 5 | Runs | Two repairs brought the pier into shot, a poor close view, fronds out |

Five of six ran to the end, against none of the two before this change, and an earlier build of it got four of four. The check caught and fixed real
faults on the way: a lamp out of shot, a pier out of shot, three default cubes. But most of these pictures are still wrong, and in ways
word rules can't see. The cup's name is there and its box is in frame. **That's the limit of this approach:** two rounds of reviews have
taken the rules about as far as they go. What's left needs something that can look at a render and say whether the cup is in it.

**Side by side, measured at last.** Four of these tasks had rounds of three steps or more at once with timings known, the case Routing left open. FX4 took
a step in each and finished last every time, at 134 to 154 s, while the others were done at 40 to 93 s, so it added about 50 to 85 s to
those rounds. No step failed. It doesn't change the left-out hold rule's case much either way: turning FX4's thinking off is still the
thing to try first.

## The look (Nov 1)

Word rules had gone as far as they could: a cup buried in a 1.5 m cube and a camera that saw nothing both passed. So once a scene passes
everything else, a vision model on the same computer now looks at a small render and says what it can make out (`app/hydra_look.go`).

**How it works.** At the end of measuring, the prelude saves the scene. If the goal asks for a scene, a second Blender in the same
sandbox loads that file with its code off and renders 512 pixels at 16 samples on the processor, under a second here. It's a second
Blender because most scripts stop at their render, where another can't start, and so the script's code never runs again. The model
gets the goal and the picture and lists the physical objects asked for, seen or not, as JSON. The check goes to `wrong_scene` if the
picture is blank or strictly more than half of those can't be seen, and repairs get that along with the measurements. If the task says what
the camera is on, or there's a second camera, only seeing none of it counts. A check with a look takes 4 to 5 seconds, 11 to 13 if
the model has to load. Anything that goes wrong, no model, no answer, an answer it can't read, leaves the check as it was.

**Measured first.** Before any code, 135 scenes the reviewers had labelled by eye were rendered and put to two vision models:

| Rule | qwen3.8:27b: good flagged | bad caught | gemma4:12b: good flagged | bad caught |
|---|---|---|---|---|
| Any one thing missing | 19 of 77 | 57 of 58 | 27 of 77 | 58 of 58 |
| The first thing missing | 6 | 50 | 11 | 49 |
| **Most of them missing** | **4** | **54** | 9 | 52 |
| All of them missing | 1 | 46 | 3 | 45 |

Most of the good ones it flagged really were poor: a nearly black guitar, a bridge cropped until the train was a red band.

**The final figures.** These go through the real sandbox, the rules and the look together:

| Scenes | Good flagged | Bad caught | Rules alone caught |
|---|---|---|---|
| 147 the rule was chosen on | 4 of 83 (2 by the look) | 56 of 64 | 40 |
| 40 from gemma4:12b, held out | 0 of 13 | 15 of 27 | 4 |

The held-out row is the honest one, though its 13 good scenes only bound the false-alarm rate at about 21%, and the prompt below was written
after seeing those pictures. The labels are one reviewer's eye, or mine. No Claude output is training data here: nothing is trained.

**What the review changed.** The first prompt said "the main things the request names", so "a key light and a camera" counted as things
missing from a perfect picture: on goals nobody tuned on, 6 of 9 good pictures were flagged. It now asks only for physical objects in the
shot. A safety hole is closed: a script could leave a link at the picture's path, and the app, outside the sandbox, would read whatever
it pointed at and send it to the model, or hang on a pipe. The path is now cleared first and read only if it's a plain small file. Also: a
Workbench scene isn't looked at, since Cycles can't copy its light; textures painted in code are packed before the save; Stop during a
look keeps the pass; a look's fault ranks above a measured one, so a repair that really breaks a scene is taken back; only the model that was
measured gets to judge (`CHIMERA_LOOK_MODEL` tries another); and goals that can't use a picture don't pay for a render.

**Real tasks on the final build**, the same six goals as before, from a test asker with all three computers:

| Goal | Before the look | With it | Time | What it made |
|---|---|---|---|---|
| Coffee cup, table, lamp | Passed, cup buried | Passed | 4 min | All three there, dim |
| Bowl of fruit | Passed, fruit under the table | Passed | 2 min 40 s | Bowl of fruit on a table, the bowl oversized |
| Campfire, logs, tent | Passed, the best of the set | Note says it shows nothing | 3 min 35 s | A pale ball: rightly not passed |
| Teapot, two cups, tray | Stopped, with a note | Stopped, with a note | 2 min 10 s | `primitive_teapot_add` doesn't exist |
| Red bicycle, brick wall | Passed, camera sees nothing | Note says it can't see them | 6 min 31 s | Parts of a bicycle, apart |
| Island, palm, pier | Passed, a poor close view | Passed | 5 min 4 s | Palm and pier on an island, clearly |

These are single runs, and the campfire shows how much they vary: the same goal did better last time. Nothing empty passed this time. Three
pictures are about what was asked for, and the other three say they aren't. That's the point: a reply can now be trusted when it
doesn't carry a note. What's still missing is skill: repairs get told what can't be seen, but a model that can't build a bicycle
doesn't learn to from that.

**Still open.**
- The look's catch rate on held-out scenes is 56%: on low-contrast pictures the model tends to confirm what the request named.
- It only runs on a computer with qwen3.8, so a task started from FX4 or FX2 gets no look. The pool could lend one, but a worker on an older
  build would drop the picture and answer blind, so that needs a version bump first.
- Two wrong names can take turns (`FFMPEG`, `H264`), which the same-fault rule doesn't see, and that spent 16 repairs in one earlier run.
- The picture isn't shown on the task card, and the repair model doesn't see it.

**From another computer (Nov 1, on 0.8.0).** With all three computers updated, the first long task started anywhere but the Studio ran from FX2:
"a scene of basic shapes on a table with a basic sky background like the early 90s cgi renders". About 2 minutes 10 seconds, one round. It planned and
reviewed on FX4's `hydra:1.0`, ran steps on FX3 and FX2, and combined and repaired on FX3. The check ran on FX2, in its own sandbox and Blender 5.2.2: three crashes,
then the default cube, then a pass after 4 repairs, with no note. FX2 has no `qwen3.8`, so it skipped the look; run here afterwards, the look passes it too. The picture is a cube,
sphere and cone on a flat square, recognisable and fittingly plain, but pale, with the sphere and cone half sunk into the table, which nothing checks. FX2's own steps were free, as they
should be. Still unchecked: a long task started from Windows or Linux, and the look anywhere but the Studio.
