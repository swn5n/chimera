package main

// Hydra: long tasks. The biggest model available plans the work as a few
// small steps, the steps run at the same time on whichever devices are
// lending (each worker is told it's one piece of a bigger project, with a
// system prompt that suits the kind of task), known-good library entries are
// reused when they match, and the biggest model combines the pieces.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"
)

type hydraStep struct {
	ID           string    `json:"id"`
	Title        string    `json:"title"`
	Kind         string    `json:"kind"`
	Instructions string    `json:"instructions"`
	DependsOn    []string  `json:"depends_on"`
	Status       string    `json:"status"` // waiting, running, done, failed, library
	Device       string    `json:"device,omitempty"`
	Owner        string    `json:"owner,omitempty"`
	Model        string    `json:"model,omitempty"`
	Output       string    `json:"output,omitempty"`
	Tokens       int       `json:"tokens,omitempty"`
	TokS         float64   `json:"tok_s,omitempty"`
	Credits      float64   `json:"credits,omitempty"`
	Free         bool      `json:"free,omitempty"`
	Local        bool      `json:"local,omitempty"`
	Note         string    `json:"note,omitempty"`
	Error        string    `json:"error,omitempty"`
	FromLibrary  string    `json:"from_library,omitempty"`
	Started      time.Time `json:"started,omitempty"`
	Finished     time.Time `json:"finished,omitempty"`
}

type hydraPlan struct {
	Title   string      `json:"title"`
	Kind    string      `json:"kind"`
	Summary string      `json:"summary"`
	Steps   []hydraStep `json:"steps"`
}

type TaskRecord struct {
	hydraPlan
	Goal          string    `json:"goal"`
	Phase         string    `json:"phase"` // planning, working, combining, reviewing, done, error, cancelled
	Round         int       `json:"round,omitempty"`
	Rounds        int       `json:"rounds,omitempty"` // >1 means iterate-until-done
	Critique      string    `json:"critique,omitempty"`
	Error         string    `json:"error,omitempty"`
	PlannerDevice string    `json:"planner_device,omitempty"`
	PlannerOwner  string    `json:"planner_owner,omitempty"`
	PlannerModel  string    `json:"planner_model,omitempty"`
	SynthDevice   string    `json:"synth_device,omitempty"`
	SynthOwner    string    `json:"synth_owner,omitempty"`
	SynthModel    string    `json:"synth_model,omitempty"`
	Refs          []string  `json:"refs,omitempty"` // library entries the plan drew on
	Started       time.Time `json:"started"`
	Finished      time.Time `json:"finished,omitempty"`
	Tokens        int       `json:"tokens,omitempty"`
	Credits       float64   `json:"credits,omitempty"`
}

type taskEvent struct {
	Type      string      `json:"type"` // started, task, delta, done, error, cancelled
	TaskID    string      `json:"task_id,omitempty"`
	SessionID string      `json:"session_id,omitempty"`
	Task      *TaskRecord `json:"task,omitempty"`
	Content   string      `json:"content,omitempty"`
	Error     string      `json:"error,omitempty"`
}

type taskRun struct {
	id, sessionID string
	mu            sync.Mutex
	rec           TaskRecord
	final         strings.Builder
	subs          map[chan taskEvent]struct{}
	finished      bool
	cancel        context.CancelFunc
	lastPush      time.Time
}

type TaskManager struct {
	app  *App
	mu   sync.Mutex
	runs map[string]*taskRun
}

func NewTaskManager(app *App) *TaskManager {
	return &TaskManager{app: app, runs: map[string]*taskRun{}}
}

func (t *TaskManager) Get(id string) *taskRun {
	if id == "" {
		return nil
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.runs[id]
}

type taskReq struct {
	SessionID string `json:"session_id"`
	Goal      string `json:"goal"`
	Private   bool   `json:"private"`
	Loop      bool   `json:"loop"` // iterate until the result meets the goal

	history []ChatMessage // earlier messages in the chat, for context
}

func (t *TaskManager) Start(req taskReq) (*taskRun, error) {
	goal := strings.TrimSpace(req.Goal)
	if goal == "" {
		return nil, errors.New("describe the task first")
	}
	store := t.app.sessions
	var sess *Session
	if req.SessionID != "" {
		if s, err := store.Get(req.SessionID); err == nil {
			sess = s
		}
	}
	if sess == nil {
		sess = store.New()
	}
	for _, m := range sess.Messages {
		if m.Status == "pending" && (t.app.gens.Get(m.GenID) != nil || t.Get(m.TaskID) != nil) {
			return nil, errors.New("a reply is still being written in this chat")
		}
	}
	if len(sess.Messages) == 0 || sess.Title == "New chat" {
		sess.Title = titleFrom(goal)
	}
	req.history = buildHistory(sess.Messages)
	run := &taskRun{id: randomID(6), sessionID: sess.ID, subs: map[chan taskEvent]struct{}{}}
	run.rec = TaskRecord{Goal: goal, Phase: "planning", Started: time.Now()}
	now := time.Now()
	rec := run.rec
	sess.Messages = append(sess.Messages,
		SessionMessage{Role: "user", Content: goal, At: now},
		SessionMessage{Role: "assistant", At: now, Status: "pending", TaskID: run.id, Task: &rec},
	)
	if err := store.Save(sess); err != nil {
		return nil, err
	}
	// Set cancel before the run is reachable, so a cancel can never find it unset.
	ctx, cancel := context.WithCancel(context.Background())
	run.cancel = cancel
	t.mu.Lock()
	t.runs[run.id] = run
	t.mu.Unlock()
	go t.execute(ctx, run, req)
	return run, nil
}

func (r *taskRun) snapshot() TaskRecord {
	rec := r.rec
	rec.Steps = append([]hydraStep(nil), r.rec.Steps...)
	return rec
}

// push sends the current task state to anyone watching.
func (r *taskRun) push(force bool) {
	r.mu.Lock()
	if !force && time.Since(r.lastPush) < 250*time.Millisecond {
		r.mu.Unlock()
		return
	}
	r.lastPush = time.Now()
	rec := r.snapshot()
	r.broadcastLocked(taskEvent{Type: "task", TaskID: r.id, Task: &rec})
	r.mu.Unlock()
}

func (r *taskRun) broadcastLocked(ev taskEvent) {
	for ch := range r.subs {
		select {
		case ch <- ev:
		default:
			close(ch)
			delete(r.subs, ch)
		}
	}
}

func (r *taskRun) Subscribe() ([]taskEvent, chan taskEvent) {
	r.mu.Lock()
	defer r.mu.Unlock()
	rec := r.snapshot()
	replay := []taskEvent{{Type: "started", TaskID: r.id, SessionID: r.sessionID}, {Type: "task", TaskID: r.id, Task: &rec}}
	if r.final.Len() > 0 {
		replay = append(replay, taskEvent{Type: "delta", TaskID: r.id, Content: r.final.String()})
	}
	if r.finished {
		ev := taskEvent{Type: "done", TaskID: r.id, Task: &rec}
		if rec.Phase == "error" {
			ev = taskEvent{Type: "error", TaskID: r.id, Task: &rec, Error: rec.Error}
		} else if rec.Phase == "cancelled" {
			ev = taskEvent{Type: "cancelled", TaskID: r.id, Task: &rec}
		}
		return append(replay, ev), nil
	}
	ch := make(chan taskEvent, 4096)
	r.subs[ch] = struct{}{}
	return replay, ch
}

func (r *taskRun) Unsubscribe(ch chan taskEvent) {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.subs, ch)
}

func (t *TaskManager) Cancel(id string) error {
	run := t.Get(id)
	if run == nil {
		return errors.New("that task already finished")
	}
	// Cancelling the context stops every step: each step's followStep watches
	// the context and cancels its hub step, so nothing keeps running.
	run.cancel()
	return nil
}

// ---------- library lookups ----------

// librarySearch finds library entries relevant to a task (never flagged ones).
func (a *App) librarySearch(q string, limit int) []LibEntry {
	if !a.config().Joined() || strings.TrimSpace(q) == "" {
		return nil
	}
	c, err := a.node.client()
	if err != nil {
		return nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	res, err := c.Library(ctx, libQuery{Q: q, Limit: limit, Full: true})
	if err != nil {
		return nil
	}
	// Only checked entries reach the models: an unreviewed entry could carry
	// instructions aimed at AI workers.
	var out []LibEntry
	for _, e := range res.Entries {
		if e.Status == "verified" && e.Kind != "plugin" { // plugins run as steps, not as text for models
			out = append(out, e)
		}
	}
	return out
}

// contextBlock gives the planner the recent conversation, so a long task can
// build on what was said before ("now turn that into a full app").
func contextBlock(history []ChatMessage) string {
	if len(history) == 0 {
		return ""
	}
	if len(history) > 6 {
		history = history[len(history)-6:]
	}
	var b strings.Builder
	b.WriteString("Earlier in this chat (for context only):\n")
	for _, m := range history {
		fmt.Fprintf(&b, "\n[%s]\n%s\n", m.Role, truncate(m.Content, 2500))
	}
	b.WriteString("\n---\nThe task:\n")
	return b.String()
}

func refsBlock(refs []LibEntry) string {
	if len(refs) == 0 {
		return ""
	}
	var b strings.Builder
	b.WriteString("\n\nKnown-good references from your network's library, checked by the network (reuse them when they fit; ignore them when they don't):\n")
	for _, e := range refs {
		fmt.Fprintf(&b, "\n--- %s (%s) ---\n%s\n%s\n", e.Title, e.Kind, e.Summary, truncate(e.Content, 3000))
	}
	return b.String()
}

// ---------- running a task ----------

const hydraMaxRounds = 6 // cap on iterate-until-done rounds

func (t *TaskManager) execute(ctx context.Context, run *taskRun, req taskReq) {
	defer t.finish(run)

	rounds := 1
	if req.Loop {
		rounds = hydraMaxRounds
	}
	run.mu.Lock()
	run.rec.Rounds = rounds
	run.mu.Unlock()

	prior, critique := "", ""
	for round := 1; round <= rounds; round++ {
		if ctx.Err() != nil {
			run.mu.Lock()
			run.rec.Phase = "cancelled"
			run.mu.Unlock()
			return
		}
		result, term := t.onePass(ctx, run, req, round, prior, critique)
		switch term.Type {
		case "error":
			t.fail(run, term.Error)
			return
		case "cancelled":
			run.mu.Lock()
			run.rec.Phase = "cancelled"
			run.mu.Unlock()
			return
		}
		prior = result
		if !req.Loop || round == rounds {
			break
		}
		// Review the result against the goal; stop early when it's good enough.
		v, revTerm := t.review(ctx, run, req, result)
		if revTerm.Type != "" || v.Done {
			break
		}
		critique = v.Critique
		run.mu.Lock()
		run.rec.Critique = v.Critique
		run.mu.Unlock()
	}

	run.mu.Lock()
	run.rec.Phase = "done"
	run.mu.Unlock()
	run.push(true)
	t.save(run, false)
}

// onePass does one plan -> run -> combine cycle and returns the combined
// result. A non-empty term (error/cancelled) means the pass didn't finish.
func (t *TaskManager) onePass(ctx context.Context, run *taskRun, req taskReq, round int, prior, critique string) (string, genEvent) {
	a := t.app
	setPhase := func(p string) {
		run.mu.Lock()
		run.rec.Phase, run.rec.Round = p, round
		run.mu.Unlock()
		run.push(true)
		t.save(run, false)
	}
	setPhase("planning")

	// 1. Plan on the biggest model available. On a later round, build on the
	// previous attempt and the review's critique instead of starting over.
	refs := a.librarySearch(req.Goal, 3)
	var useful []LibEntry
	for _, e := range refs {
		if e.Score >= 0.3 {
			useful = append(useful, e)
		}
	}
	if round == 1 {
		run.mu.Lock()
		for _, e := range useful {
			run.rec.Refs = append(run.rec.Refs, e.Title)
		}
		run.mu.Unlock()
	}
	userMsg := contextBlock(req.history) + req.Goal
	if prior != "" {
		userMsg += "\n\n---\nThe previous attempt produced this result:\n" + truncate(prior, 12000) +
			"\n\nWhat still needs work:\n" + critique +
			"\n\nPlan the steps to improve it into a result that fully meets the task. Reuse what already works; only redo what needs it."
	}
	userMsg += refsBlock(useful)
	planMsgs := []ChatMessage{{Role: "system", Content: hydraPlannerPrompt}, {Role: "user", Content: userMsg}}
	var planText strings.Builder
	planEv := a.runPrompt(ctx, submitReq{Private: req.Private, Messages: planMsgs, Prefer: "largest", TaskWork: true,
		Format: json.RawMessage(`"json"`), NeedCtx: historyTokens(planMsgs) + 2048, Purpose: "Hydra: planning (round " + itoaSmall(round) + ")"},
		func(ev genEvent) {
			switch ev.Type {
			case "assigned":
				run.mu.Lock()
				run.rec.PlannerDevice, run.rec.PlannerOwner, run.rec.PlannerModel = deviceLabelGo(ev), ev.Owner, ev.Model
				run.mu.Unlock()
				run.push(false)
			case "delta":
				planText.WriteString(ev.Content)
			case "replay":
				planText.Reset()
				planText.WriteString(ev.Content)
			case "requeued":
				planText.Reset()
			}
		}, nil)
	if planEv.Type == "error" || planEv.Type == "cancelled" {
		return "", planEv
	}
	var plan hydraPlan
	if !extractJSON(planText.String(), &plan) || len(plan.Steps) == 0 {
		return "", genEvent{Type: "error", Error: "The planner didn't return a usable plan. Try again, or rephrase the task."}
	}
	plan = cleanPlan(plan)
	run.mu.Lock()
	run.rec.hydraPlan = plan
	run.rec.Tokens += planEv.Tokens
	run.rec.Credits += planEv.Credits
	run.mu.Unlock()
	setPhase("working")

	// 2. Run the steps, in parallel where they don't depend on each other.
	parallel := a.parallelism(req.Private)
	sem := make(chan struct{}, parallel)
	var wg sync.WaitGroup
	for ctx.Err() == nil {
		ready, remaining := t.readySteps(run)
		if remaining == 0 {
			break
		}
		if len(ready) == 0 {
			select {
			case <-ctx.Done():
			case <-time.After(200 * time.Millisecond):
			}
			continue
		}
		select { // wait for a free slot before starting the next step
		case sem <- struct{}{}:
		case <-ctx.Done():
			continue
		}
		idx := ready[0]
		run.mu.Lock()
		run.rec.Steps[idx].Status = "running"
		run.rec.Steps[idx].Started = time.Now()
		run.mu.Unlock()
		run.push(true)
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			defer func() { <-sem }()
			t.runStep(ctx, run, i, req.Private)
		}(idx)
	}
	wg.Wait()
	if ctx.Err() != nil {
		return "", genEvent{Type: "cancelled"}
	}

	// 3. Combine the pieces into one result.
	rec := run.snapshot()
	done := 0
	for _, s := range rec.Steps {
		if s.Status == "done" || s.Status == "library" {
			done++
		}
	}
	if done == 0 {
		return "", genEvent{Type: "error", Error: "None of the steps finished. " + firstFailure(rec.Steps)}
	}
	resetFinal := func(s string) {
		run.mu.Lock()
		run.final.Reset()
		run.final.WriteString(s)
		run.broadcastLocked(taskEvent{Type: "replay", TaskID: run.id, Content: s})
		run.mu.Unlock()
	}
	if len(rec.Steps) == 1 {
		resetFinal(rec.Steps[0].Output)
		return rec.Steps[0].Output, genEvent{}
	}
	setPhase("combining")
	resetFinal("") // a new round's result replaces the last one
	var parts strings.Builder
	fmt.Fprintf(&parts, "Task from the person: %s\n\nProject: %s\n%s\n\nThe workers' outputs:\n", rec.Goal, rec.Title, rec.Summary)
	budget := 60000 / len(rec.Steps)
	for i, s := range rec.Steps {
		out := s.Output
		if s.Status == "failed" {
			out = "(this step failed: " + s.Error + ")"
		}
		fmt.Fprintf(&parts, "\n## Step %d: %s\n%s\n", i+1, s.Title, truncate(out, budget))
	}
	synthMsgs := []ChatMessage{{Role: "system", Content: synthPrompt(rec.Kind)}, {Role: "user", Content: parts.String()}}
	synthEv := a.runPrompt(ctx, submitReq{Private: req.Private, Messages: synthMsgs, Prefer: "largest", TaskWork: true,
		NeedCtx: historyTokens(synthMsgs) + 4096, Purpose: "Hydra: combining (round " + itoaSmall(round) + ")"},
		func(ev genEvent) {
			run.mu.Lock()
			switch ev.Type {
			case "assigned":
				run.rec.SynthDevice, run.rec.SynthOwner, run.rec.SynthModel = deviceLabelGo(ev), ev.Owner, ev.Model
			case "delta":
				run.final.WriteString(ev.Content)
				run.broadcastLocked(taskEvent{Type: "delta", TaskID: run.id, Content: ev.Content})
			case "replay", "requeued":
				run.final.Reset()
				run.final.WriteString(ev.Content)
				run.broadcastLocked(taskEvent{Type: "replay", TaskID: run.id, Content: ev.Content})
			}
			run.mu.Unlock()
			if ev.Type == "assigned" {
				run.push(true)
			}
		}, nil)
	if synthEv.Type == "error" || synthEv.Type == "cancelled" {
		return "", synthEv
	}
	run.mu.Lock()
	run.rec.Tokens += synthEv.Tokens
	run.rec.Credits += synthEv.Credits
	result := run.final.String()
	run.mu.Unlock()
	return result, genEvent{}
}

type reviewVerdict struct {
	Done     bool   `json:"done"`
	Score    int    `json:"score"`
	Critique string `json:"critique"`
}

// review asks the biggest model whether the result fully meets the goal.
func (t *TaskManager) review(ctx context.Context, run *taskRun, req taskReq, result string) (reviewVerdict, genEvent) {
	a := t.app
	run.mu.Lock()
	run.rec.Phase = "reviewing"
	run.mu.Unlock()
	run.push(true)
	msgs := []ChatMessage{
		{Role: "system", Content: hydraReviewPrompt},
		{Role: "user", Content: "The task:\n" + req.Goal + "\n\nThe result so far:\n" + truncate(result, 40000)},
	}
	var out strings.Builder
	ev := a.runPrompt(ctx, submitReq{Private: req.Private, Messages: msgs, Prefer: "largest", TaskWork: true,
		Format: json.RawMessage(`"json"`), NeedCtx: historyTokens(msgs) + 1024, Purpose: "Hydra: reviewing the result"},
		func(ev genEvent) {
			switch ev.Type {
			case "delta":
				out.WriteString(ev.Content)
			case "replay", "requeued":
				out.Reset()
				out.WriteString(ev.Content)
			}
		}, nil)
	if ev.Type == "error" || ev.Type == "cancelled" {
		return reviewVerdict{Done: true}, ev // can't review: treat current result as final
	}
	run.mu.Lock()
	run.rec.Tokens += ev.Tokens
	run.rec.Credits += ev.Credits
	run.mu.Unlock()
	var v reviewVerdict
	if !extractJSON(out.String(), &v) {
		return reviewVerdict{Done: true}, genEvent{} // unparseable: stop with what we have
	}
	return v, genEvent{}
}

func itoaSmall(n int) string { return string(rune('0' + n%10)) }

func deviceLabelGo(ev genEvent) string {
	if ev.Local {
		return ev.DeviceName + " (here)"
	}
	return ev.DeviceName
}

// strongMatch is true when a verified library entry is clearly what a step
// asks for: a high search score, the right kind, and every word of the
// entry's title appearing in the step.
func strongMatch(step hydraStep, e LibEntry) bool {
	if e.Status != "verified" || e.Score < 0.85 {
		return false
	}
	if !(step.Kind == "code" && e.Kind == "snippet") && !(step.Kind == "blender" && e.Kind == "blender") {
		return false
	}
	text := strings.ToLower(step.Title + " " + step.Instructions)
	words := tokenize(e.Title)
	if len(words) == 0 {
		return false
	}
	for _, w := range words {
		if !strings.Contains(text, w) {
			return false
		}
	}
	return true
}

func firstFailure(steps []hydraStep) string {
	for _, s := range steps {
		if s.Error != "" {
			return "First problem: " + s.Error
		}
	}
	return ""
}

// parallelism is how many steps to run at once: one per lending device, up to 4.
func (a *App) parallelism(private bool) int {
	_, _, _, snap := a.node.view(true)
	n := 0
	if snap != nil && a.config().Joined() {
		for _, d := range snap.Devices {
			if d.Lending && !d.Draining && d.OllamaOK && (!private || sameOwner(d.Owner, a.config().Owner)) {
				n += max(1, d.Slots)
			}
		}
	}
	return clampInt(n, 1, 4)
}

func cleanPlan(p hydraPlan) hydraPlan {
	if len(p.Steps) > 8 {
		p.Steps = p.Steps[:8]
	}
	kinds := map[string]bool{"code": true, "writing": true, "research": true, "blender": true, "general": true}
	if !kinds[p.Kind] {
		p.Kind = "general"
	}
	ids := map[string]bool{}
	for i := range p.Steps {
		s := &p.Steps[i]
		if s.ID == "" || ids[s.ID] {
			s.ID = fmt.Sprintf("s%d", i+1)
		}
		ids[s.ID] = true
		if !kinds[s.Kind] {
			s.Kind = p.Kind
		}
		if strings.TrimSpace(s.Title) == "" {
			s.Title = fmt.Sprintf("Step %d", i+1)
		}
		if strings.TrimSpace(s.Instructions) == "" {
			s.Instructions = s.Title
		}
		s.Status = "waiting"
	}
	// Keep only dependencies on earlier steps: that rules out cycles.
	seen := map[string]bool{}
	for i := range p.Steps {
		var deps []string
		for _, d := range p.Steps[i].DependsOn {
			if seen[d] {
				deps = append(deps, d)
			}
		}
		p.Steps[i].DependsOn = deps
		seen[p.Steps[i].ID] = true
	}
	if strings.TrimSpace(p.Title) == "" {
		p.Title = "Long task"
	}
	return p
}

// readySteps returns waiting steps whose dependencies have finished.
func (t *TaskManager) readySteps(run *taskRun) ([]int, int) {
	run.mu.Lock()
	defer run.mu.Unlock()
	status := map[string]string{}
	for _, s := range run.rec.Steps {
		status[s.ID] = s.Status
	}
	var ready []int
	remaining := 0
	for i, s := range run.rec.Steps {
		if s.Status == "waiting" || s.Status == "running" {
			remaining++
		}
		if s.Status != "waiting" {
			continue
		}
		ok := true
		for _, d := range s.DependsOn {
			if st := status[d]; st == "waiting" || st == "running" {
				ok = false
			}
		}
		if ok {
			ready = append(ready, i)
		}
	}
	return ready, remaining
}

func (t *TaskManager) runStep(ctx context.Context, run *taskRun, i int, private bool) {
	a := t.app
	run.mu.Lock()
	rec := run.snapshot()
	step := rec.Steps[i]
	run.mu.Unlock()

	update := func(fn func(s *hydraStep)) {
		run.mu.Lock()
		fn(&run.rec.Steps[i])
		run.mu.Unlock()
		run.push(false)
	}

	// Reuse a known-good library entry outright when it clearly matches:
	// no model needed for something the network already has working code for.
	if hits := a.librarySearch(step.Title, 1); len(hits) > 0 && strongMatch(step, hits[0]) {
		top := hits[0]
		if c, err := a.node.client(); err == nil {
			cctx, cc := context.WithTimeout(context.Background(), 4*time.Second)
			_ = c.LibraryUsed(cctx, top.ID)
			cc()
		}
		update(func(s *hydraStep) {
			s.Status, s.FromLibrary, s.Finished = "library", top.Title, time.Now()
			s.Output = "```" + top.Language + "\n" + top.Content + "\n```"
		})
		run.push(true)
		return
	}
	// Otherwise relevant entries go to the worker as references.
	var useful []LibEntry
	for _, e := range a.librarySearch(step.Title+" "+step.Instructions, 2) {
		if e.Score >= 0.3 {
			useful = append(useful, e)
		}
	}

	var user strings.Builder
	user.WriteString(step.Instructions)
	for _, dep := range step.DependsOn {
		for _, s := range rec.Steps {
			if s.ID == dep {
				out := s.Output
				if s.Status == "failed" {
					out = "(that step failed; make reasonable assumptions)"
				}
				fmt.Fprintf(&user, "\n\nOutput from the step \"%s\":\n%s", s.Title, truncate(out, 8000))
			}
		}
	}
	msgs := []ChatMessage{{Role: "system", Content: workerPrompt(rec.hydraPlan, step) + refsBlock(useful)}, {Role: "user", Content: user.String()}}
	var out strings.Builder
	var lastErr string
	for attempt := 0; attempt < 2; attempt++ {
		out.Reset()
		ev := a.runPrompt(ctx, submitReq{Private: private, Messages: msgs, NeedCtx: historyTokens(msgs) + 4096, TaskWork: true,
			Purpose: fmt.Sprintf("Hydra: step %d of %d", i+1, len(rec.Steps))},
			func(ev genEvent) {
				switch ev.Type {
				case "assigned":
					update(func(s *hydraStep) { s.Device, s.Owner, s.Model, s.Local = ev.DeviceName, ev.Owner, ev.Model, ev.Local })
				case "note":
					update(func(s *hydraStep) { s.Note = ev.Reason })
				case "delta":
					out.WriteString(ev.Content)
					update(func(s *hydraStep) { s.Output = out.String() })
				case "replay", "requeued":
					out.Reset()
					out.WriteString(ev.Content)
					update(func(s *hydraStep) { s.Output = out.String() })
				}
			}, nil)
		switch ev.Type {
		case "done":
			update(func(s *hydraStep) {
				s.Status, s.Output, s.Finished = "done", out.String(), time.Now()
				s.Tokens, s.TokS, s.Credits, s.Free = ev.Tokens, ev.TokPerSec, ev.Credits, ev.Free
			})
			run.mu.Lock()
			run.rec.Tokens += ev.Tokens
			run.rec.Credits += ev.Credits
			run.mu.Unlock()
			run.push(true)
			return
		case "cancelled":
			update(func(s *hydraStep) { s.Status, s.Error = "failed", "cancelled" })
			return
		}
		lastErr = ev.Error
		if ctx.Err() != nil {
			break
		}
	}
	update(func(s *hydraStep) { s.Status, s.Error, s.Finished = "failed", lastErr, time.Now() })
	run.push(true)
}

func (t *TaskManager) stopped(run *taskRun, ev genEvent) bool {
	switch ev.Type {
	case "error":
		t.fail(run, ev.Error)
		return true
	case "cancelled":
		run.mu.Lock()
		run.rec.Phase = "cancelled"
		run.mu.Unlock()
		return true
	}
	return false
}

func (t *TaskManager) fail(run *taskRun, msg string) {
	run.mu.Lock()
	run.rec.Phase, run.rec.Error = "error", msg
	run.mu.Unlock()
	log.Printf("task %s: %s", run.id, msg)
}

func (t *TaskManager) finish(run *taskRun) {
	run.mu.Lock()
	if run.rec.Phase != "error" && run.rec.Phase != "cancelled" && run.rec.Phase != "done" {
		run.rec.Phase = "cancelled"
	}
	run.rec.Finished = time.Now()
	run.finished = true
	rec := run.snapshot()
	ev := taskEvent{Type: "done", TaskID: run.id, Task: &rec}
	switch rec.Phase {
	case "error":
		ev = taskEvent{Type: "error", TaskID: run.id, Task: &rec, Error: rec.Error}
	case "cancelled":
		ev = taskEvent{Type: "cancelled", TaskID: run.id, Task: &rec}
	}
	run.broadcastLocked(ev)
	for ch := range run.subs {
		close(ch)
	}
	run.subs = map[chan taskEvent]struct{}{}
	run.mu.Unlock()
	t.save(run, true)
	t.app.notify()
	time.AfterFunc(2*time.Minute, func() {
		t.mu.Lock()
		delete(t.runs, run.id)
		t.mu.Unlock()
	})
}

// save writes the task into its chat message.
func (t *TaskManager) save(run *taskRun, final bool) {
	run.mu.Lock()
	rec := run.snapshot()
	content := run.final.String()
	run.mu.Unlock()
	_, err := t.app.sessions.Update(run.sessionID, func(s *Session) {
		for i := range s.Messages {
			m := &s.Messages[i]
			if m.TaskID != run.id {
				continue
			}
			r := rec
			m.Task = &r
			m.Content = content
			m.Model = rec.SynthModel
			if m.Model == "" {
				m.Model = rec.PlannerModel
			}
			m.Device, m.Owner = rec.SynthDevice, rec.SynthOwner
			m.Tokens, m.Credits = rec.Tokens, round2(rec.Credits)
			if final {
				switch rec.Phase {
				case "done":
					m.Status = ""
				case "cancelled":
					m.Status = "cancelled"
				default:
					m.Status, m.Error = "error", rec.Error
				}
				m.At = time.Now()
			}
		}
	})
	if err != nil {
		log.Printf("saving task %s: %v", run.id, err)
	}
}
