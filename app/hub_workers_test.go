package main

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

// The real fleet on Oct 31: what each computer has, with the speeds it reports.
var (
	hereticM  = ModelInfo{Name: "coder-next:80b", ParamsB: 79.7, Fits: "tight", TokS: 71.8, Loaded: true, SizeBytes: 57e9}
	deepseekM = ModelInfo{Name: "deepseek-r1:70b", ParamsB: 70.6, Fits: "comfortable", TokS: 15.3, SizeBytes: 42e9}
	qwen38M   = ModelInfo{Name: "qwen3.8:27b", ParamsB: 30.3, Fits: "comfortable", TokS: 63.3, SizeBytes: 18e9}
	probeM    = ModelInfo{Name: "wm-probe-gemma4-x:nothink", ParamsB: 11.9, Fits: "comfortable", EstTokS: 66.6, SizeBytes: 8e9}
	gptossM   = ModelInfo{Name: "gpt-oss:20b", ParamsB: 20.9, Fits: "comfortable", TokS: 53.6, SizeBytes: 13e9}
	qwen30M   = ModelInfo{Name: "qwen3:30b", ParamsB: 30.5, Fits: "tight", EstTokS: 68.9, SizeBytes: 19e9}
	qwen359M  = ModelInfo{Name: "qwen3.5:9b", ParamsB: 9, Fits: "comfortable", TokS: 51.2, SizeBytes: 6e9}
	qwen352M  = ModelInfo{Name: "qwen3.5:2b", ParamsB: 1.9, Fits: "comfortable", EstTokS: 114, SizeBytes: 2e9}
)

func fleetHub(t *testing.T) (*Hub, *hubDevice) {
	t.Helper()
	h := helperTestHub(t)
	h.st.Devices["fx3"] = lender("fx3", "FX3", "FX_M3", hereticM, deepseekM, qwen38M, probeM)
	h.st.Devices["fx2"] = lender("fx2", "FX2", "FX2", gptossM, qwen30M)
	h.st.Devices["fx4"] = lender("fx4", "FX4", "FX3080ti", qwen359M, qwen352M)
	asker := &hubDevice{ID: "a", Name: "Asker", Owner: "FX_M3", online: true, lastSeen: time.Now()}
	h.st.Devices["a"] = asker
	return h, asker
}

func workerBody(task string) string {
	return fmt.Sprintf(`{"messages":[{"role":"user","content":"a step"}],"prefer":"worker","need_ctx":3000,"task_id":%q}`, task)
}

// runChain gives n steps of a task one after the other, as a plan that's a chain
// does, with every computer free, each taking secs[device] seconds.
func runChain(t *testing.T, h *Hub, asker *hubDevice, task string, n int, secs map[string]float64) []*hubStep {
	t.Helper()
	var out []*hubStep
	for range n {
		for _, id := range []string{"fx2", "fx3", "fx4"} {
			if h.waiters[id] == nil {
				h.waiters[id] = &waiter{deviceID: id, ch: make(chan *hubStep, 1)}
			}
		}
		st, rr := submitStep(t, h, asker, workerBody(task))
		if rr.Code != 200 || st == nil || st.Assigned == "" {
			t.Fatalf("submit: %d %s", rr.Code, rr.Body)
		}
		h.mu.Lock()
		st.Text.WriteString("a piece of the work")
		st.AssignedAt = time.Now().Add(-time.Duration(secs[st.Assigned] * float64(time.Second)))
		h.finishLocked(st, h.st.Devices[st.Assigned], "done", "")
		h.mu.Unlock()
		out = append(out, st)
	}
	return out
}

func TestWorkerStepsGoWhereTheyreDoneSoonest(t *testing.T) {
	h, asker := fleetHub(t)
	h.st.WorkerSecs = map[string]float64{workerKey("fx2", gptossM.Name): 22, workerKey("fx3", deepseekM.Name): 104, workerKey("fx4", qwen359M.Name): 131}
	st := runChain(t, h, asker, "t1", 1, map[string]float64{"fx2": 22})
	if st[0].Assigned != "fx2" || st[0].RunModel != gptossM.Name {
		t.Fatalf("the real timings say FX2: got %s on %s", st[0].RunModel, st[0].Assigned)
	}
	// The biggest model used to win this; its size no longer counts.
	if m, _, _ := h.fits(h.st.Devices["fx3"], &hubStep{Prefer: "worker", Exclude: map[string]bool{}}); m == deepseekM.Name {
		t.Fatal("deepseek-r1:70b is the slowest here, whatever its size")
	}
}

func TestAChainSpreadsAcrossComputers(t *testing.T) {
	h, asker := fleetHub(t)
	h.st.WorkerSecs = map[string]float64{workerKey("fx2", gptossM.Name): 22, workerKey("fx3", qwen38M.Name): 30, workerKey("fx4", qwen359M.Name): 40}
	took := map[string]float64{"fx2": 22, "fx3": 30, "fx4": 40}
	steps := runChain(t, h, asker, "t1", 6, took)
	on := map[string]int{}
	for _, s := range steps {
		on[s.Assigned]++
	}
	if on["fx2"] != 2 || on["fx3"] != 2 || on["fx4"] != 2 {
		t.Fatalf("similar computers share a task: %v", on)
	}
	// Over a long task the spread stops growing, so a slow computer doesn't keep getting turns.
	h, asker = fleetHub(t)
	h.st.WorkerSecs = map[string]float64{workerKey("fx2", gptossM.Name): 22, workerKey("fx3", qwen38M.Name): 30, workerKey("fx4", qwen359M.Name): 131}
	on = map[string]int{}
	for _, s := range runChain(t, h, asker, "long", 23, map[string]float64{"fx2": 22, "fx3": 30, "fx4": 131}) {
		on[s.Assigned]++
	}
	if on["fx4"] != 0 {
		t.Fatalf("23 steps, none for the computer six times slower: %v", on)
	}
	// A much slower computer doesn't get a turn just for being there.
	h, asker = fleetHub(t)
	h.st.WorkerSecs = map[string]float64{workerKey("fx2", gptossM.Name): 22, workerKey("fx3", qwen38M.Name): 30, workerKey("fx4", qwen359M.Name): 131}
	on = map[string]int{}
	for _, s := range runChain(t, h, asker, "t2", 3, map[string]float64{"fx2": 22, "fx3": 30, "fx4": 131}) {
		on[s.Assigned]++
	}
	if on["fx4"] != 0 || on["fx2"] == 0 || on["fx3"] == 0 {
		t.Fatalf("three steps go between the two quick computers: %v", on)
	}
	// Another task starts afresh, and no task id means no spreading.
	if s := runChain(t, h, asker, "t3", 1, map[string]float64{"fx2": 22}); s[0].Assigned != "fx2" {
		t.Fatalf("a new task: %s", s[0].Assigned)
	}
	for range 3 {
		if s := runChain(t, h, asker, "", 1, map[string]float64{"fx2": 22}); s[0].Assigned != "fx2" {
			t.Fatalf("no task id: %s", s[0].Assigned)
		}
	}
}

func TestStepsAtOnceUseEveryComputer(t *testing.T) {
	h, asker := fleetHub(t)
	for _, id := range []string{"fx2", "fx3", "fx4"} {
		h.waiters[id] = &waiter{deviceID: id, ch: make(chan *hubStep, 1)}
	}
	seen := map[string]bool{}
	for range 3 {
		st, rr := submitStep(t, h, asker, workerBody("t1"))
		if rr.Code != 200 || st.Assigned == "" {
			t.Fatalf("%d %s", rr.Code, rr.Body)
		}
		seen[st.Assigned] = true
	}
	if len(seen) != 3 {
		t.Fatalf("three steps at once, three computers: %v", seen)
	}
}

func TestLeftoverAndTinyModelsArentPicked(t *testing.T) {
	h, _ := fleetHub(t)
	step := &hubStep{Prefer: "worker", Exclude: map[string]bool{}}
	// On paper speed alone the test model beats everything here; it's never been timed.
	h.st.WorkerSecs = map[string]float64{workerKey("fx3", hereticM.Name): 300, workerKey("fx3", qwen38M.Name): 400, workerKey("fx3", deepseekM.Name): 500}
	if m, _, _ := h.fits(h.st.Devices["fx3"], step); m != hereticM.Name {
		t.Fatalf("a proven model beats an unproven one, however slow: %s", m)
	}
	if m, _, _ := h.fits(h.st.Devices["fx2"], step); m != gptossM.Name {
		t.Fatalf("unproven, tight, big: %s", m)
	}
	if m, _, _ := h.fits(h.st.Devices["fx4"], step); m != qwen359M.Name {
		t.Fatalf("tiny, however fast: %s", m)
	}
	// Tiny loses even when it's been timed and is quicker: quick isn't enough.
	h.st.WorkerSecs = map[string]float64{workerKey("fx4", qwen352M.Name): 10, workerKey("fx4", qwen359M.Name): 131}
	if m, _, _ := h.fits(h.st.Devices["fx4"], step); m != qwen359M.Name {
		t.Fatalf("a timed tiny model: %s", m)
	}
	// And it loses to a proper model nobody has timed.
	h.st.Devices["x"] = lender("x", "Mixed", "Bob", ModelInfo{Name: "qwen3:14b", ParamsB: 14.8, Fits: "comfortable", EstTokS: 53, SizeBytes: 9e9}, qwen352M)
	h.st.WorkerSecs[workerKey("x", qwen352M.Name)] = 8
	if m, _, _ := h.fits(h.st.Devices["x"], step); m != "qwen3:14b" {
		t.Fatalf("timed and tiny against untimed and proper: %s", m)
	}
	// But a computer with only a tiny model still counts, so a step can run.
	only := lender("x", "Small", "Bob", qwen352M)
	if m, _, ok := h.fits(only, step); !ok || m != qwen352M.Name {
		t.Fatalf("a last resort is still a resort: %s %v", m, ok)
	}
}

func TestChatsAndCombinesRouteAsBefore(t *testing.T) {
	h, _ := fleetHub(t)
	if m, _, _ := h.fits(h.st.Devices["fx3"], &hubStep{Exclude: map[string]bool{}}); m != deepseekM.Name {
		t.Fatalf("a chat: %s", m)
	}
	if m, _, _ := h.fits(h.st.Devices["fx3"], &hubStep{Prefer: "largest", Exclude: map[string]bool{}}); m != hereticM.Name {
		t.Fatalf("a combine: %s", m)
	}
	// And the helper still stays out of worker steps.
	if m, _, ok := h.fits(lender("h", "Helper box", "Bob", hydraM), &hubStep{Prefer: "worker", Exclude: map[string]bool{}}); ok {
		t.Fatalf("the helper must not take a worker step: %s", m)
	}
}

func TestTheHubLearnsWhatAStepTakes(t *testing.T) {
	h, asker := fleetHub(t)
	key := workerKey("fx2", gptossM.Name)
	h.st.WorkerSecs = map[string]float64{key: 1}
	runChain(t, h, asker, "t1", 1, map[string]float64{"fx2": 101})
	if got := h.st.WorkerSecs[key]; got < 30 || got > 32 {
		t.Fatalf("one slow step moves it, not replaces it: %v", got)
	}
	// A failed step teaches nothing, and neither does a chat.
	before := h.st.WorkerSecs[key]
	h.mu.Lock()
	h.finishLocked(&hubStep{Prefer: "worker", RunModel: gptossM.Name, AssignedAt: time.Now().Add(-time.Hour), Exclude: map[string]bool{}}, h.st.Devices["fx2"], "failed", "no")
	h.finishLocked(&hubStep{RunModel: gptossM.Name, AssignedAt: time.Now().Add(-time.Hour), Exclude: map[string]bool{}}, h.st.Devices["fx2"], "done", "")
	h.mu.Unlock()
	if h.st.WorkerSecs[key] != before {
		t.Fatalf("%v", h.st.WorkerSecs[key])
	}
	// A quick reply with nothing in it, or one that ran out of room, is no good time.
	for _, bad := range []func(s *hubStep){
		func(s *hubStep) {},
		func(s *hubStep) { s.Text.WriteString("half a"); s.Stats.DoneReason = "length" },
	} {
		s := &hubStep{Prefer: "worker", RunModel: gptossM.Name, AssignedAt: time.Now().Add(-time.Second), Exclude: map[string]bool{}}
		bad(s)
		h.st.WorkerSecs[key] = 22
		h.mu.Lock()
		h.finishLocked(s, h.st.Devices["fx2"], "done", "")
		h.mu.Unlock()
		if h.st.WorkerSecs[key] <= 22 {
			t.Fatalf("a wasted step can't look quick: %v", h.st.WorkerSecs[key])
		}
	}
	h.st.WorkerSecs[key] = before
	// It lasts over a restart: it's in the hub's saved state.
	b, err := json.Marshal(h.st)
	if err != nil {
		t.Fatal(err)
	}
	var back hubState
	if err := json.Unmarshal(b, &back); err != nil || back.WorkerSecs[key] != before {
		t.Fatalf("%v %v", err, back.WorkerSecs)
	}
}

func TestAFarBetterComputerAboutToAskGetsAMoment(t *testing.T) {
	timed := map[string]float64{workerKey("fx2", gptossM.Name): 22, workerKey("fx3", qwen38M.Name): 30, workerKey("fx4", qwen359M.Name): 131}
	setup := func(asking ...string) (*Hub, *hubStep) {
		h, asker := fleetHub(t)
		h.st.WorkerSecs = timed
		for _, id := range asking {
			h.waiters[id] = &waiter{deviceID: id, ch: make(chan *hubStep, 1)}
		}
		st, rr := submitStep(t, h, asker, workerBody("t"))
		if rr.Code != 200 {
			t.Fatalf("submit: %d %s", rr.Code, rr.Body)
		}
		return h, st
	}
	// FX2 and FX3 have just finished; only FX4, six times slower, is asking.
	h, st := setup("fx4")
	if st.Status != "queued" {
		t.Fatalf("a much better computer is about to ask: it went to %s", st.Assigned)
	}
	h.waiters["fx2"] = &waiter{deviceID: "fx2", ch: make(chan *hubStep, 1)}
	h.dispatchLocked()
	if st.Assigned != "fx2" {
		t.Fatalf("when FX2 asks it gets the step, got %q", st.Assigned)
	}
	// If it never asks, the step doesn't wait for it.
	h, st = setup("fx4")
	st.Created = time.Now().Add(-helperWait - time.Second)
	h.dispatchLocked()
	if st.Assigned != "fx4" {
		t.Fatalf("after the wait the step goes on, got %q", st.Assigned)
	}
	// One a little better isn't worth waiting for.
	if _, st = setup("fx3"); st.Assigned != "fx3" {
		t.Fatalf("FX2 is 8 s better: FX3 should take it at once, got %q (%s)", st.Assigned, st.Status)
	}
	// Nor is a busy one.
	h, asker := fleetHub(t)
	h.st.WorkerSecs = timed
	for _, id := range []string{"fx2", "fx3"} {
		h.steps["busy"+id] = &hubStep{ID: "busy" + id, Status: "running", Assigned: id, Exclude: map[string]bool{}, subs: map[chan hubEvent]struct{}{}}
	}
	h.waiters["fx4"] = &waiter{deviceID: "fx4", ch: make(chan *hubStep, 1)}
	if st, _ = submitStep(t, h, asker, workerBody("t")); st.Assigned != "fx4" {
		t.Fatalf("FX2 and FX3 are busy: FX4 should take it, got %q (%s)", st.Assigned, st.Status)
	}
}

func TestALoadedModelBeatsAnEqualOneThatIsnt(t *testing.T) {
	h := helperTestHub(t)
	cold := ModelInfo{Name: "cold:20b", ParamsB: 20, Fits: "comfortable", TokS: 50, SizeBytes: 40e9}
	warm := ModelInfo{Name: "warm:20b", ParamsB: 20, Fits: "comfortable", TokS: 50, SizeBytes: 40e9, Loaded: true}
	d := lender("d", "D", "Bob", cold, warm)
	h.st.WorkerSecs = map[string]float64{workerKey("d", cold.Name): 20, workerKey("d", warm.Name): 25}
	if m, _, _ := h.fits(d, &hubStep{Prefer: "worker", Exclude: map[string]bool{}}); m != warm.Name {
		t.Fatalf("20 s plus a 16 s load is slower than 25 s: %s", m)
	}
}

func TestALoneStepGoesByQuality(t *testing.T) {
	if workerPrefer(1, false) != "" {
		t.Fatal("no combine after it: it's the reply, so it routes as a reply does")
	}
	if workerPrefer(1, true) != "worker" || workerPrefer(3, false) != "worker" {
		t.Fatal("anything a combine follows is a piece")
	}
}

func TestLocalWorkerStepsPickTheSameWay(t *testing.T) {
	m, ok := pickLocalModel([]ModelInfo{deepseekM, qwen38M, probeM, qwen352M}, "", nil, "worker", "")
	if !ok || m.Name != qwen38M.Name {
		t.Fatalf("with no pool, the proven quick model: %s", m.Name)
	}
	if m, _ := pickLocalModel([]ModelInfo{deepseekM, qwen38M}, "", nil, "", ""); m.Name != deepseekM.Name {
		t.Fatalf("a chat keeps the biggest: %s", m.Name)
	}
}
