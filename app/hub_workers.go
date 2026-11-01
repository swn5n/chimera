package main

// Where a long task's worker steps run. Size says little about this: on Oct 31
// over 203 real steps FX2's gpt-oss:20b took 22 s a step, deepseek-r1:70b, the
// biggest and so always picked, 104 s, and qwen3.5:9b 131 s for less output, at
// a healthy-looking 52 tokens a second, because most of its tokens are hidden
// thinking. So the hub learns what a step really takes on each computer, and a
// step goes where it'll be done soonest, spreading over the task's computers
// unless that costs much. Chats, the combine and a one-step task's only step don't
// come through here: they want the best answer, not the quickest piece. A free
// computer always takes a step in preference to waiting for a busy one, so a slow
// computer still gets work when a round runs steps side by side.

import (
	"fmt"
	"strings"
	"time"
)

const (
	// A step's usual length, for a model nobody has timed yet.
	workerStepTokens = 1500
	// Below this size a model is a last resort, behind even one nobody has timed.
	workerMinParams = 8.0
	workerSmallCost = 1000.0
	// How much a model nobody has timed counts against it: enough that a
	// proven one wins, so leftover test models don't get real work on paper speed.
	workerUnproven  = 600.0
	workerTightCost = 30.0 // close to the memory limit
	// What each step this computer has already done for the task costs it, up
	// to a limit: a similar computer gets the next one, and over a long task a
	// much slower one doesn't keep getting turns.
	workerSpreadCost = 45.0
	workerSpreadMax  = 2
	// What a step that gave nothing usable counts for, on top of its time.
	workerWasted = 300.0
	// How fast the timing follows a model's latest step.
	workerLearnRate = 0.3
)

// workerGuess is the seconds a worker step should take with a model that hasn't
// been timed, with what counts against it.
func workerGuess(m ModelInfo) float64 {
	speed := m.Speed()
	if speed <= 0 {
		speed = 15
	}
	secs := workerStepTokens / speed
	if m.TokS <= 0 {
		secs += workerUnproven
	}
	return secs + workerLoad(m) + workerExtras(m)
}

func workerLoad(m ModelInfo) float64 {
	if m.Loaded {
		return 0
	}
	return m.SizeGB() / 2.5
}

func workerExtras(m ModelInfo) float64 {
	extra := 0.0
	if m.ParamsB < workerMinParams {
		extra += workerSmallCost
	}
	if m.Fits == "tight" {
		extra += workerTightCost
	}
	return extra
}

func workerKey(deviceID, model string) string {
	return fmt.Sprintf("%s|%s", deviceID, normModel(model))
}

// workerCostLocked is the seconds a worker step would take with m on d, spread
// aside: the time it has really been taking there, else a guess.
func (h *Hub) workerCostLocked(d *hubDevice, m ModelInfo) float64 {
	if secs, ok := h.st.WorkerSecs[workerKey(d.ID, m.Name)]; ok {
		return secs + workerLoad(m) + workerExtras(m)
	}
	return workerGuess(m)
}

// taskStepsOnLocked is how many of st's task's worker steps went to device id.
// workerScoreLocked is what fits ranks a worker step by: higher is better.
func (h *Hub) workerScoreLocked(st *hubStep, d *hubDevice, m ModelInfo) float64 {
	return -h.workerCostLocked(d, m) - workerSpreadCost*float64(min(h.taskStepsOnLocked(st, d.ID), workerSpreadMax))
}

// workerAboutToAskLocked says whether a computer that's free but not asking for
// work this moment would do st much better than d, with score. In a chain that's
// the usual case: the next step arrives as the computer that did the last one
// finishes, just before it asks again. Like a helper step, it gets a moment. A
// computer that's only a little better isn't worth it, and a busy one isn't waited for.
func (h *Hub) workerAboutToAskLocked(st *hubStep, d *hubDevice, score float64) bool {
	if time.Since(st.Created) >= helperWait {
		return false
	}
	for _, o := range h.st.Devices {
		if o == d || h.waiters[o.ID] != nil || st.Exclude[o.ID] || !h.readyLocked(o) {
			continue
		}
		if (st.Target != "" && st.Target != o.ID) || (st.Private && !sameOwner(o.Owner, st.RequesterOwner)) {
			continue
		}
		for _, m := range o.models {
			if m.ForChat() && modelOK(m, st) && h.workerScoreLocked(st, o, m) > score+workerSpreadCost {
				return true
			}
		}
	}
	return false
}

func (h *Hub) taskStepsOnLocked(st *hubStep, id string) int {
	if st.TaskID == "" {
		return 0
	}
	n := 0
	for _, o := range h.steps {
		if o != st && o.TaskID == st.TaskID && o.Assigned == id {
			n++
		}
	}
	return n
}

// noteWorkerStepLocked learns from a finished worker step how long that model
// takes on that computer, loading and thinking included, which is what counts.
// A model that ran out of room or said nothing did it quickly, which mustn't
// read as being quick.
func (h *Hub) noteWorkerStepLocked(st *hubStep, worker *hubDevice) {
	if st.Prefer != "worker" || st.AssignedAt.IsZero() || st.RunModel == "" {
		return
	}
	secs := st.Finished.Sub(st.AssignedAt).Seconds()
	if st.Stats.DoneReason == "length" || strings.TrimSpace(st.Text.String()) == "" {
		secs += workerWasted
	}
	if h.st.WorkerSecs == nil {
		h.st.WorkerSecs = map[string]float64{}
	}
	key := workerKey(worker.ID, st.RunModel)
	if old, ok := h.st.WorkerSecs[key]; ok {
		secs = old + workerLearnRate*(secs-old)
	}
	h.st.WorkerSecs[key] = secs
	h.dirty = true
}
