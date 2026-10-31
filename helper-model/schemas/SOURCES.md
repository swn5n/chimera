# What Chimera parses today, and what the schemas add

Read from Chimera 0.6.1 (`app/`, git `c2aef2c`). The three `*.schema.json` files are the
**strict target** the helper must produce. Chimera itself is more lenient, so the validators
report both: `chimera_ok` (Chimera would accept the reply) and `valid` (strict).
`python3 tools/check_prompts_sync.py` fails if any Go line this file describes changes.

## How every reply is read (all three jobs)

`extractJSON` (app/library.go) trims the reply, tries Go's `json.Unmarshal` on all of it, and
if that fails, on the text from the first `{` to the last `}`. With Go's decoder:

- Keys match case-insensitively (`"Done"` fills `done`). Unknown keys are ignored.
- A missing key, or `null`, leaves Go's zero value: `""`, `false`, `0`, an empty list.
- A wrong type anywhere fails the whole decode, including fields Chimera fills in itself
  (`"tokens": "a few"` or `"started": "yesterday"` in a step rejects the plan).
- Integers must be integer literals: `85`, not `85.0` or `8.5e1`. `NaN` and `Infinity` fail.
- Text around the object is tolerated (code fences, "Here's the plan:"), unless a `}` comes
  after the object, e.g. two objects in one reply.
- A repeated key: the last one wins.

Chimera's request never sets `think`, so thinking models think by default; only `content` is
parsed, never the thinking text. All three jobs use `keep_alive: "15m"` and
`num_ctx = ctxBucket(historyTokens(messages) + extra)` (8192 for anything short).

## Planner — `onePass` in app/hydra.go

- Model: `Prefer: "largest"`. Format: `"json"` (JSON mode, no schema). No temperature: the
  model's own default. `extra` for num_ctx: 2048.
- Messages: `hydraPlannerPrompt` as system; user = `contextBlock(history)` (last 6 chat turns,
  2,500 bytes each) + the goal, then on later rounds the previous result (12,000 bytes) and the
  reviewer's critique, then `refsBlock` (verified library entries scoring 0.3 or more).
- Decoded into `hydraPlan`; the task fails ("The planner didn't return a usable plan") if
  that fails or there are no steps. Then `cleanPlan` repairs it:

| Field | Go type | What Chimera does with a bad value | Strict target |
|---|---|---|---|
| `title` | string | blank → "Long task" | non-empty |
| `kind` | string | not one of the five (case-sensitive) → "general" | `code`, `writing`, `research`, `blender`, `general` |
| `summary` | string | missing → workers see an empty summary | non-empty, 2–3 sentences (warn past 4) |
| `steps` | []hydraStep | 0 → task fails; 1 → runs alone with no combine step; more than 8 → first 8 kept | 2 to 7 |
| `steps[].id` | string | empty or repeated → `s<i+1>` (not re-checked, so it can still clash) | `s1`…`sN`, in order (order is a warning) |
| `steps[].title` | string | blank → "Step N" | non-empty |
| `steps[].kind` | string | not one of the five → the plan's kind | one of the five |
| `steps[].instructions` | string | blank → the title | non-empty (warn under 25 characters) |
| `steps[].depends_on` | []string | keeps only ids of **earlier** steps; forward, unknown and self references are dropped silently | ids of earlier steps only, no repeats |
| `status`, `device`, `owner`, `model`, `output`, `tokens`, `tok_s`, `credits`, `free`, `local`, `note`, `error`, `from_library`, `started`, `finished` | various | decoded (a wrong type rejects the plan), then filled by Chimera | not allowed |

Sanity rules on top of the schema (`helper/validate.py`): step count, ids present and
unique, every dependency names an earlier step, no cycles, no whitespace-only strings
(errors); review/combine steps the prompt rules out, short instructions, repeated titles, a
plan kind no step has (warnings).

## Reviewer — `review` in app/hydra.go

- Runs only in looping mode ("Keep going until done"), after each pass but the last (6 passes
  at most). Model: largest. Format `"json"`. No temperature. `extra`: 1024.
- User message: `"The task:\n" + goal + "\n\nThe result so far:\n" + result` (result cut at 40,000 bytes).
- Decoded into `reviewVerdict {done bool, score int, critique string}`.
- If the call fails or the reply doesn't decode, the loop **stops as if done**. A missing
  `done` reads as false, so another round runs, with whatever critique there is (maybe none).
- `score` is never read. The critique goes straight into the next round's planner message.
- Strict target: all three keys; `score` an integer 0–100; a non-empty critique when not done
  and an empty one when done (as the prompt says). Warnings: done with a score under 50, not
  done at 90 or more, a critique under 20 or over 1,500 characters.
- Optional `check` string, written first (from v2): the helper's own check of each requirement
  before it commits to a verdict. `extractJSON` (app/library.go) is plain `json.Unmarshal` into
  `reviewVerdict`, which ignores unknown fields, so Chimera reads exactly the same verdict with
  or without it (checked Oct 28 against Chimera 0.6.1). Why: the prompt's reply starts with
  `"done"`, so a model that doesn't think picks the verdict before looking at anything; asking
  for a check first lifted the untrained 4B base from 15 to 20 of 24 review cases.

## Head gate — `headForText` / `headGate` in app/plugin_chat.go

- Only for a message with **no picture** and **"Best available"** as the model, outside long
  tasks. A picture always goes to a Head with no gate; an explicit model never does.
- Before any model is asked, a word filter picks candidates: Heads that need no file
  (`accepts` empty or `optional_input`), whose `pluginRelevance` to the message is at least
  0.25, or every such Head if the message has no usable words at all. Only the best-rated
  candidate goes to the gate.
- Model: `Prefer: "fastest"`, on another computer unless the Head runs on the asker (8 s to be
  picked up, 45 s in all). Format: `headGateSchema`. Options: `temperature: 0`. `extra`: 256.
- User message: `"Tool: " + name + ": " + summary [+ "\nUse it when: " + when_to_use] +
  "\n\nRequest: " + text + "\n\nShould this tool handle the request?"`.
- Decoded into `struct{Use bool}`; a reply that doesn't decode is `use=false`. If no model
  could be reached, the word filter decides alone: relevance of 0.75 or more means use.
- Strict target: exactly `{"use": true}` or `{"use": false}`.

## Worth a decision (noticed while reading; nothing changed)

1. The prompt asks for 2 to 7 steps, but `cleanPlan` accepts 1 and keeps up to 8.
2. `cleanPlan`'s id repair isn't re-checked: ids `"s2"` then `""` both become `"s2"`.
3. A forward or unknown `depends_on` is dropped without a note, so that step runs without the
   input it asked for.
4. A non-integer `score` (72.5, 85.0) fails the decode and ends the loop as if done, although
   `score` is never used. A missing `done` runs another round with an empty critique.
5. The gate never sees the Head's `when_not_to_use`, which is exactly the hard-negative text
   (comfyui-image's says "questions about images, or anything that wants words back"), nor the
   chat history, so "make one" after talking about a poster can't be judged.
6. The word filter matches substrings: any message containing "computer" scores 0.25 against
   every Head whose summary says "on this computer", and a message with no usable words
   ("make one", "do it") reaches the gate for every words-only Head.
7. Planner and reviewer run at the model's default temperature with thinking on by default,
   so the same goal can plan differently each time; thinking time adds to every call.
8. Ollama 0.40.1 aborts a reply that keeps repeating a token ("prediction aborted, token repeat
   limit reached"). Chimera gets that as an error: the reviewer then stops the loop as if done,
   and the planner fails the task. On eval v1 it hit 6 of 672 calls (about 1%), each a reply that
   ran into endless spaces, tabs or newlines inside its JSON: three qwen3:1.7b reviews and three
   qwen3:8b plans with thinking off.
9. With thinking on, the reasoning nearly fills the context Chimera asks for. Every call in the
   baselines got `num_ctx` 8,192 (the reply budget is only +2,048 for plans and +1,024 for
   reviews), yet prompt plus thinking plus reply reached 7,656 tokens (qwen3:1.7b reviewing a
   short result), 7,008 (qwen3:4b, same review) and 6,412 (qwen3:4b, a plan). A longer
   goal or result could run out of room mid-thought.
10. Nothing caps a reply's length. Chimera sets no `num_predict` and no time limit on the planner
    or reviewer, and the hub's stall check (`stallAfter`, 30 s without progress, app/hub.go)
    counts streamed thinking as progress. On eval v1, qwen3:8b with thinking on looped in its
    reasoning on bl-11 for the runner's full 600 s (238,000 characters, one sentence repeated 451
    times) and never wrote a plan. In Chimera that long task would hang until someone cancels it.
11. JSON mode (`format: "json"`) only guarantees some JSON object. qwen3:8b replied `{}` to one
    goal (the task fails), and with thinking off, qwen3:4b and qwen3:8b wrote malformed keys such
    as `": "` in 8 and 7 of 44 plans, losing `title`, `kind` or `instructions` from a step.
    Sending the schema itself as `format`, as the gate already does, should rule most of these
    out (untested).

