package main

// Hydra 1.0 is the network's helper model: a LoRA-tuned Qwen3-4B (2.9 GB) that
// every computer can run whole. It does three jobs, the ones it was trained on
// with exactly Chimera's prompts (see helper-model/ in the repo): Hydra's
// planner, Hydra's looping-mode reviewer, and the "should a Head handle this?"
// check for words-only requests. Steps for those jobs carry prefer_model; any
// computer the step may run on that has the helper gets it first, and with no
// such computer the step is routed exactly as before. The helper is never
// picked for anything else (chats, worker steps, combining, library jobs,
// reading a Head's options): its training covered only the three JSON jobs.

import (
	"strings"
	"time"
)

const helperModel = "hydra:1.0"

// helperMaxCtx is the most context a request may need (Chimera's estimate, in
// tokens) to go to the helper: whatever fits the 8K bucket (ctxBucket). Hydra
// was trained on inputs of up to 8,192 tokens, and the 8K bucket keeps it at
// about 4 GB on any computer. Bigger plans and reviews go to the biggest model.
const helperMaxCtx = 7000

// helperMaxReviewCtx is the most a review may need to go to the helper, about
// 5,800 characters of result. On the long review cases (helper-model/eval-long,
// five unseeded tries each) Hydra 1.0 caught 25 of 25 flawed results of up to
// 5,500 characters but only 6 of 15 from 8,300 on, where gpt-oss:120b caught 14.
// Longer results are reviewed by the biggest model.
const helperMaxReviewCtx = 3500

// preferredScore puts a computer that has the step's preferred model ahead of
// every other choice the hub scores (those stay well under 100,000).
const preferredScore = 1e6

// helperWait is how long a helper step waits for a free computer that has the
// helper but hasn't asked for work yet (between two steps) before it goes to
// another model. A busy one isn't waited for.
const helperWait = 3 * time.Second

// isHelperModel reports whether a model is one of the helper's versions
// ("hydra:1.0", a later "hydra:1.1", or a copy kept under a namespace).
func isHelperModel(name string) bool {
	n := normModel(name)
	if i := strings.LastIndex(n, "/"); i >= 0 {
		n = n[i+1:]
	}
	return strings.HasPrefix(n, "hydra:")
}

// helperFor is the model a planner, reviewer or Head-check request needing
// needCtx tokens should prefer: the helper when the request fits it, else none.
func helperFor(needCtx int) string {
	if needCtx > helperMaxCtx {
		return ""
	}
	return helperModel
}

// helperForReview is helperFor for the looping reviewer, which the helper only
// gets for shorter results (helperMaxReviewCtx).
func helperForReview(needCtx int) string {
	if needCtx > helperMaxReviewCtx {
		return ""
	}
	return helperFor(needCtx)
}
