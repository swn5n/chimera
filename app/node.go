package main

// The node is this computer's membership in a network: it sends heartbeats,
// and when you're Connected it lends your Ollama models by pulling work from
// the hub, SheepIt style. Disconnecting can either finish the current step
// first or stop right away (the hub hands that step to another device).

import (
	"context"
	"errors"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"
)

type runningStep struct {
	ID              string    `json:"id"`
	Model           string    `json:"model"`
	Purpose         string    `json:"purpose,omitempty"`
	Requester       string    `json:"requester"`
	RequesterDevice string    `json:"requester_device"`
	Started         time.Time `json:"started"`
	Tokens          int       `json:"tokens"`

	cancel     context.CancelFunc
	stopReason string // "disconnect" or "requester"
}

type Node struct {
	app *App

	mu       sync.Mutex
	hubOK    bool
	hubErr   string
	snap     *NetSnapshot
	lastBeat time.Time

	lending      bool
	draining     bool
	connecting   bool
	autoHelped   bool // we connected this device to help the owner's long task
	pausedReason string
	lendErr      string
	running      map[string]*runningStep
	usedModels   map[string]bool
	loopActive   bool
	pollCancel   context.CancelFunc

	wake    chan struct{}
	beatNow chan struct{}
}

func NewNode(app *App) *Node {
	return &Node{
		app:        app,
		running:    map[string]*runningStep{},
		usedModels: map[string]bool{},
		wake:       make(chan struct{}, 1),
		beatNow:    make(chan struct{}, 1),
	}
}

func signal1(ch chan struct{}) {
	select {
	case ch <- struct{}{}:
	default:
	}
}

func (n *Node) client() (*HubClient, error) {
	cfg := n.app.config()
	if !cfg.Joined() {
		return nil, errors.New("not in a network")
	}
	return NewHubClient(cfg.HubAddress, cfg.Token)
}

// ---------- membership ----------

func (n *Node) membershipLoop() {
	t := time.NewTicker(3 * time.Second)
	defer t.Stop()
	for {
		n.heartbeat()
		select {
		case <-n.app.quit:
			return
		case <-t.C:
		case <-n.beatNow:
		}
	}
}

func (n *Node) sharedModels() []ModelInfo {
	cfg := n.app.config()
	st := n.app.ollama.State()
	if st.Status != "running" {
		return nil
	}
	var out []ModelInfo
	for _, m := range n.app.annotate(st.Models) {
		if cfg.IsUnshared(m.Name) {
			continue
		}
		if cfg.MaxModelGB > 0 && m.SizeGB() > cfg.MaxModelGB {
			continue
		}
		if m.Fits == "too_big" && m.CanChat() {
			continue // would spill out of GPU memory and time out
		}
		out = append(out, m)
	}
	return out
}

// runningModel says whether a step running here is using the model.
func (n *Node) runningModel(model string) bool {
	n.mu.Lock()
	defer n.mu.Unlock()
	for _, rs := range n.running {
		if normModel(rs.Model) == normModel(model) {
			return true
		}
	}
	return false
}

func (n *Node) isShared(model string) bool {
	for _, m := range n.sharedModels() {
		if normModel(m.Name) == normModel(model) {
			return true
		}
	}
	return false
}

func (n *Node) heartbeat() {
	cfg := n.app.config()
	if !cfg.Joined() {
		n.mu.Lock()
		changed := n.hubOK || n.snap != nil || n.hubErr != ""
		n.hubOK, n.snap, n.hubErr = false, nil, ""
		n.mu.Unlock()
		if changed {
			n.app.notify()
		}
		return
	}
	c, err := n.client()
	if err != nil {
		return
	}
	ost := n.app.ollama.State()
	sys := n.app.sysInfo()
	n.mu.Lock()
	hb := heartbeatReq{
		Name:          cfg.DeviceName,
		Lending:       n.lending && n.pausedReason == "",
		Draining:      n.draining,
		Slots:         cfg.MaxSlots,
		OllamaOK:      ost.Status == "running",
		OllamaVersion: ost.Version,
		AppVersion:    Version,
		RunTests:      cfg.RunTests && canSandbox(),
		LendPlugins:   cfg.LendPlugins,
	}
	n.mu.Unlock()
	hb.Models = n.sharedModels()
	hb.Profile = n.app.profile()
	if sys.OS != "" {
		hb.Info = &sys
	}
	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
	snap, err := c.Heartbeat(ctx, hb)
	cancel()

	n.mu.Lock()
	if err != nil {
		var ae *apiError
		if errors.As(err, &ae) && ae.Status == 401 {
			n.hubErr = ae.Msg
		} else {
			n.hubErr = friendlyNetErr(err, "the hub ("+cfg.HubAddress+")")
		}
		n.hubOK = false
	} else {
		n.hubOK, n.hubErr = true, ""
		n.snap = &snap
		n.lastBeat = time.Now()
		if snap.Network.Name != "" && snap.Network.Name != cfg.NetworkName {
			go n.app.updateConfig(func(c *Config) { c.NetworkName = snap.Network.Name })
		}
	}
	n.mu.Unlock()
	if err == nil {
		n.autoHelp(cfg, snap.OwnerBusy)
	}
	n.app.notify()
}

// autoHelp connects this device to pitch in while its owner has a long task
// running, and stands it down again afterwards (only devices it pulled in).
func (n *Node) autoHelp(cfg Config, ownerBusy bool) {
	if !cfg.AutoHelp {
		return
	}
	n.mu.Lock()
	lending, draining, connecting := n.lending, n.draining, n.connecting
	helped := n.autoHelped
	n.mu.Unlock()
	switch {
	case ownerBusy && !lending && !connecting && n.app.ollama.Running():
		n.mu.Lock()
		n.autoHelped = true
		n.mu.Unlock()
		go func() {
			if err := n.Connect(); err != nil {
				n.mu.Lock()
				n.autoHelped = false
				n.mu.Unlock()
			} else {
				log.Printf("Auto-connected to help your long task")
			}
		}()
	case !ownerBusy && helped && lending && !draining:
		n.mu.Lock()
		n.autoHelped = false
		n.mu.Unlock()
		log.Printf("Your long task finished; standing down")
		n.Disconnect("finish")
	}
}

// ---------- lending ----------

func (n *Node) Lending() (lending, draining bool) {
	n.mu.Lock()
	defer n.mu.Unlock()
	return n.lending, n.draining
}

// Connect starts lending this computer's models. Ollama is required: if it
// isn't running we try to open it first.
func (n *Node) Connect() error {
	cfg := n.app.config()
	if !cfg.Joined() {
		return errors.New("Join or host a network first")
	}
	n.mu.Lock()
	if n.lending && !n.draining {
		n.mu.Unlock()
		return nil
	}
	if n.draining {
		// Changed their mind while finishing up: keep lending.
		n.draining = false
		n.mu.Unlock()
		n.app.notify()
		signal1(n.beatNow)
		n.ensureLoop()
		return nil
	}
	n.connecting = true
	n.lendErr = ""
	n.mu.Unlock()
	n.app.notify()

	fail := func(msg string) error {
		n.mu.Lock()
		n.connecting = false
		n.lendErr = msg
		n.mu.Unlock()
		n.app.notify()
		return errors.New(msg)
	}

	if !n.app.ollama.Running() {
		if !cfg.AutoStartOllama {
			return fail("Ollama isn't running. Open Ollama first, then Connect.")
		}
		if err := n.app.ollama.Start(30 * time.Second); err != nil {
			return fail(err.Error())
		}
		time.Sleep(1200 * time.Millisecond) // let the model list load
		n.app.ollama.Refresh()
		time.Sleep(800 * time.Millisecond)
	}
	if len(n.sharedModels()) == 0 {
		if len(n.app.ollama.State().Models) == 0 {
			return fail("Ollama has no models yet. Pull one under This device, then Connect.")
		}
		return fail("None of your models are shared. Turn one on under This device (or raise your size limit).")
	}

	n.mu.Lock()
	n.connecting = false
	n.lending = true
	n.draining = false
	n.pausedReason = ""
	n.mu.Unlock()
	log.Printf("Connected: lending %d model(s)", len(n.sharedModels()))
	n.app.notify()
	signal1(n.beatNow)
	n.ensureLoop()
	return nil
}

// Disconnect stops lending. mode "finish" lets running steps complete first;
// "now" stops them and the hub moves them to another device.
func (n *Node) Disconnect(mode string) {
	n.mu.Lock()
	if !n.lending {
		n.connecting = false
		n.mu.Unlock()
		return
	}
	if n.pollCancel != nil {
		n.pollCancel()
	}
	if mode == "finish" && len(n.running) > 0 {
		n.draining = true
		count := len(n.running)
		n.mu.Unlock()
		log.Printf("Disconnecting after %d running step(s) finish", count)
		n.app.notify()
		signal1(n.beatNow)
		signal1(n.wake)
		return
	}
	for _, rs := range n.running {
		rs.stopReason = "disconnect"
		rs.cancel()
	}
	n.lending = false
	n.draining = false
	n.pausedReason = ""
	n.mu.Unlock()
	log.Printf("Disconnected (%s)", mode)
	n.app.notify()
	signal1(n.beatNow)
	signal1(n.wake)
	go n.freeMemory()
}

func (n *Node) finishDrain() {
	n.mu.Lock()
	if !n.draining {
		n.mu.Unlock()
		return
	}
	n.lending = false
	n.draining = false
	n.mu.Unlock()
	log.Printf("Finished the last step; disconnected")
	n.app.notify()
	signal1(n.beatNow)
	go n.freeMemory()
}

func (n *Node) freeMemory() {
	if !n.app.config().FreeMemoryOnDisconnect {
		return
	}
	n.mu.Lock()
	used := n.usedModels
	n.usedModels = map[string]bool{}
	n.mu.Unlock()
	if len(used) == 0 {
		return
	}
	st := n.app.ollama.State()
	client := n.app.ollama.Client()
	for _, m := range st.Models {
		if m.Loaded && used[normModel(m.Name)] {
			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			if err := client.Unload(ctx, m.Name); err == nil {
				log.Printf("Freed memory used by %s", m.Name)
			}
			cancel()
		}
	}
	n.app.ollama.Refresh()
}

func (n *Node) ensureLoop() {
	n.mu.Lock()
	if n.loopActive {
		n.mu.Unlock()
		signal1(n.wake)
		return
	}
	n.loopActive = true
	n.mu.Unlock()
	go n.lendLoop()
}

func (n *Node) waitWake(d time.Duration) {
	select {
	case <-n.wake:
	case <-time.After(d):
	case <-n.app.quit:
	}
}

func (n *Node) lendLoop() {
	defer func() {
		n.mu.Lock()
		n.loopActive = false
		n.mu.Unlock()
	}()
	backoff := time.Second
	for {
		select {
		case <-n.app.quit:
			return
		default:
		}
		cfg := n.app.config()
		n.mu.Lock()
		lending, draining := n.lending, n.draining
		free := cfg.MaxSlots - len(n.running)
		running := len(n.running)
		n.mu.Unlock()

		if !lending {
			return
		}
		if draining {
			if running == 0 {
				n.finishDrain()
				return
			}
			n.waitWake(time.Second)
			continue
		}
		if !n.app.ollama.Running() {
			n.setPaused("Ollama stopped. Lending resumes when it's back.")
			n.waitWake(2 * time.Second)
			continue
		}
		if len(n.sharedModels()) == 0 {
			n.setPaused("No shared models right now.")
			n.waitWake(2 * time.Second)
			continue
		}
		n.setPaused("")
		if free <= 0 {
			n.waitWake(2 * time.Second)
			continue
		}
		c, err := n.client()
		if err != nil {
			n.waitWake(2 * time.Second)
			continue
		}
		ctx, cancel := context.WithTimeout(context.Background(), 35*time.Second)
		n.mu.Lock()
		n.pollCancel = cancel
		n.mu.Unlock()
		a, err := c.Poll(ctx, 25)
		cancel()
		n.mu.Lock()
		n.pollCancel = nil
		stillLending := n.lending && !n.draining
		n.mu.Unlock()

		if a != nil && !stillLending {
			// Arrived just as we were disconnecting; hand it back.
			fctx, fc := context.WithTimeout(context.Background(), 5*time.Second)
			_ = c.Fail(fctx, a.StepID, failReq{Error: n.app.config().DeviceName + " is disconnecting", Retryable: true})
			fc()
			continue
		}
		if err != nil {
			if ctx.Err() != nil && errors.Is(ctx.Err(), context.Canceled) {
				continue
			}
			var ae *apiError
			if errors.As(err, &ae) && ae.Status == 401 {
				n.setPaused(ae.Msg)
			}
			n.waitWake(backoff)
			if backoff < 15*time.Second {
				backoff *= 2
			}
			continue
		}
		backoff = time.Second
		if a != nil {
			n.runStep(c, a)
		}
	}
}

func (n *Node) setPaused(reason string) {
	n.mu.Lock()
	changed := n.pausedReason != reason
	n.pausedReason = reason
	n.mu.Unlock()
	if changed {
		n.app.notify()
		signal1(n.beatNow)
	}
}

func (n *Node) runStep(c *HubClient, a *Assignment) {
	ctx, cancel := context.WithCancel(context.Background())
	label := a.Model
	if a.Kind == "run_python" || a.Kind == "run_blender" {
		label = "a library test run"
	}
	if a.Kind == "run_plugin" {
		label = "the " + a.Plugin + " plugin"
	}
	rs := &runningStep{ID: a.StepID, Model: label, Purpose: a.Purpose, Requester: a.Requester, RequesterDevice: a.RequesterDevice, Started: time.Now(), cancel: cancel}
	n.mu.Lock()
	n.running[a.StepID] = rs
	if a.Model != "" && (a.Kind == "" || a.Kind == "chat") {
		n.usedModels[normModel(a.Model)] = true
	}
	n.mu.Unlock()
	log.Printf("Running a step for %s (%s) on %s", a.Requester, a.RequesterDevice, label)
	n.app.notify()
	signal1(n.beatNow)

	go func() {
		defer func() {
			cancel()
			n.mu.Lock()
			delete(n.running, a.StepID)
			n.mu.Unlock()
			n.app.notify()
			signal1(n.beatNow)
			signal1(n.wake)
		}()

		var bmu sync.Mutex
		var content, thinking strings.Builder
		post := func() bool {
			bmu.Lock()
			cs, ts := content.String(), thinking.String()
			content.Reset()
			thinking.Reset()
			bmu.Unlock()
			pctx, pc := context.WithTimeout(context.Background(), 8*time.Second)
			defer pc()
			cancelReq, err := c.Progress(pctx, a.StepID, cs, ts)
			if err != nil {
				bmu.Lock() // keep the text for the next try
				rest := content.String()
				restT := thinking.String()
				content.Reset()
				thinking.Reset()
				content.WriteString(cs + rest)
				thinking.WriteString(ts + restT)
				bmu.Unlock()
				return false
			}
			return cancelReq
		}

		if a.Kind == "run_plugin" {
			n.runPluginStep(ctx, cancel, c, a, rs)
			return
		}

		if a.Kind == "run_python" || a.Kind == "run_blender" {
			done := make(chan runResult, 1)
			go func() { done <- n.app.runScript(ctx, a.Kind, a.Script) }()
			var res runResult
		wait:
			for {
				select {
				case res = <-done:
					break wait
				case <-time.After(5 * time.Second):
					if post() { // the requester asked to stop: cancel the script
						cancel()
					}
				}
			}
			bmu.Lock()
			content.WriteString(res.JSON())
			bmu.Unlock()
			post()
			fctx, fc := context.WithTimeout(context.Background(), 10*time.Second)
			defer fc()
			_ = c.Complete(fctx, a.StepID, ChatStats{})
			log.Printf("Library test run finished: %s", res.Summary)
			return
		}

		if !n.isShared(a.Model) {
			fctx, fc := context.WithTimeout(context.Background(), 5*time.Second)
			_ = c.Fail(fctx, a.StepID, failReq{Error: a.Model + " isn't shared on " + n.app.config().DeviceName, Retryable: true})
			fc()
			return
		}

		stopFlusher := make(chan struct{})
		flusherDone := make(chan struct{})
		go func() {
			defer close(flusherDone)
			tk := time.NewTicker(150 * time.Millisecond)
			defer tk.Stop()
			last := time.Now()
			for {
				select {
				case <-stopFlusher:
					return
				case <-tk.C:
				}
				bmu.Lock()
				has := content.Len() > 0 || thinking.Len() > 0
				bmu.Unlock()
				if has || time.Since(last) > time.Second {
					last = time.Now()
					if post() {
						n.mu.Lock()
						rs.stopReason = "requester"
						n.mu.Unlock()
						cancel()
						return
					}
				}
			}
		}()

		opts := map[string]any{}
		for k, v := range a.Options {
			opts[k] = v
		}
		if a.NumCtx > 0 {
			opts["num_ctx"] = a.NumCtx
		}
		stats, err := n.app.ollama.Client().ChatStream(ctx, a.Model, a.Messages, opts, a.Format, func(cs, ts string) {
			bmu.Lock()
			content.WriteString(cs)
			thinking.WriteString(ts)
			bmu.Unlock()
			n.mu.Lock()
			rs.Tokens++
			n.mu.Unlock()
		})
		close(stopFlusher)
		<-flusherDone

		n.mu.Lock()
		reason, toks := rs.stopReason, rs.Tokens
		n.mu.Unlock()
		fctx, fc := context.WithTimeout(context.Background(), 10*time.Second)
		defer fc()
		if err == nil {
			post()
			n.app.perf.Record(a.Model, stats)
			if cerr := c.Complete(fctx, a.StepID, stats); cerr != nil {
				log.Printf("step %s: reporting completion: %v", a.StepID, cerr)
			}
			log.Printf("Finished a step for %s: %d tokens at %.1f tok/s", a.Requester, stats.EvalCount, stats.TokPerSec())
			return
		}
		switch reason {
		case "requester":
			post()
			_ = c.Fail(fctx, a.StepID, failReq{Error: "cancelled", Cancelled: true, ApproxTokens: toks})
		case "disconnect":
			_ = c.Fail(fctx, a.StepID, failReq{Error: n.app.config().DeviceName + " disconnected", Retryable: true})
		default:
			log.Printf("step %s failed: %v", a.StepID, err)
			_ = c.Fail(fctx, a.StepID, failReq{Error: n.app.config().DeviceName + ": " + err.Error(), Retryable: true})
		}
	}()
}

// runPluginStep runs a plugin for someone in the network: its progress goes
// back as status lines (every few seconds even when it says nothing, so the hub
// never thinks it stalled), and what it made goes back as files.
func (n *Node) runPluginStep(ctx context.Context, cancel context.CancelFunc, c *HubClient, a *Assignment, rs *runningStep) {
	var smu sync.Mutex
	status, frac, dirty := "Starting the "+a.Plugin+" plugin", 0.0, true
	post := func() {
		smu.Lock()
		msg, f := status, frac
		dirty = false
		smu.Unlock()
		pctx, pc := context.WithTimeout(context.Background(), 8*time.Second)
		defer pc()
		if stop, err := c.Status(pctx, a.StepID, msg, f); err == nil && stop {
			n.mu.Lock()
			rs.stopReason = "requester"
			n.mu.Unlock()
			cancel()
		}
	}
	stop := make(chan struct{})
	ticker := make(chan struct{})
	go func() {
		defer close(ticker)
		last := time.Time{}
		tk := time.NewTicker(time.Second)
		defer tk.Stop()
		for {
			select {
			case <-stop:
				return
			case <-tk.C:
			}
			smu.Lock()
			d := dirty
			smu.Unlock()
			if (d && time.Since(last) > time.Second) || time.Since(last) > 5*time.Second {
				last = time.Now()
				post()
			}
		}
	}()
	// The options come from the request here, with a model on this computer, so
	// the asker's own GPU stays out of it.
	own := sameOwner(a.Requester, n.app.config().Owner)
	starting := status
	input, note, took := n.app.withPluginOptions(ctx, a.Plugin, a.Input, own, func(msg string) {
		smu.Lock()
		status, dirty = msg, true
		smu.Unlock()
	})
	smu.Lock()
	if status != starting { // the options are read; the plugin itself starts now
		status, dirty = starting, true
	}
	smu.Unlock()
	if note != "" && ctx.Err() == nil {
		nctx, nc := context.WithTimeout(context.Background(), 8*time.Second)
		if stop, err := c.Note(nctx, a.StepID, note); err == nil && stop {
			n.mu.Lock()
			rs.stopReason = "requester"
			n.mu.Unlock()
			cancel()
		}
		nc()
	}
	res := n.app.runPlugin(ctx, a.StepID, a.Plugin, input, func(msg string, f float64) {
		smu.Lock()
		if msg != "" {
			status = msg
		}
		if f >= 0 {
			frac = f
		}
		dirty = true
		smu.Unlock()
	})
	close(stop)
	<-ticker

	n.mu.Lock()
	reason := rs.stopReason
	n.mu.Unlock()
	fctx, fc := context.WithTimeout(context.Background(), 60*time.Second)
	defer fc()
	switch {
	case res.OK:
		if res.Summary == "" {
			res.Summary = fmt.Sprintf("The %s plugin made %s.", a.Plugin, plural(len(res.Files), "file"))
		}
		pctx, pc := context.WithTimeout(context.Background(), 8*time.Second)
		_, _ = c.Progress(pctx, a.StepID, res.Summary, "")
		pc()
		stats := ChatStats{TotalDuration: int64((res.Seconds + took.Seconds()) * 1e9)} // the options are part of the job
		if err := c.CompleteWithFiles(fctx, a.StepID, stats, res.Files); err != nil {
			log.Printf("step %s: reporting the plugin's result: %v", a.StepID, err)
			return
		}
		log.Printf("Finished the %s plugin for %s in %.0fs (%d file(s))", a.Plugin, a.Requester, res.Seconds, len(res.Files))
	case reason == "requester" || res.Cancelled && reason != "disconnect":
		_ = c.Fail(fctx, a.StepID, failReq{Error: "cancelled", Cancelled: true})
	case reason == "disconnect":
		_ = c.Fail(fctx, a.StepID, failReq{Error: n.app.config().DeviceName + " disconnected", Retryable: true})
	default:
		log.Printf("step %s: the %s plugin failed: %s", a.StepID, a.Plugin, res.Error)
		_ = c.Fail(fctx, a.StepID, failReq{Error: res.Error, Retryable: res.Retryable})
	}
}

// ---------- state for the interface ----------

type LendingView struct {
	State   string        `json:"state"` // disconnected, connecting, connected, draining, paused
	Reason  string        `json:"reason,omitempty"`
	Error   string        `json:"error,omitempty"`
	Running []runningView `json:"running"`
	Shared  int           `json:"shared"`
}

type runningView struct {
	ID              string `json:"id"`
	Model           string `json:"model"`
	Purpose         string `json:"purpose,omitempty"`
	Requester       string `json:"requester"`
	RequesterDevice string `json:"requester_device"`
	Seconds         int    `json:"seconds"`
	Tokens          int    `json:"tokens"`
}

func (n *Node) view(ollamaUp bool) (LendingView, bool, string, *NetSnapshot) {
	n.mu.Lock()
	defer n.mu.Unlock()
	v := LendingView{State: "disconnected", Error: n.lendErr, Running: []runningView{}}
	switch {
	case n.connecting:
		v.State = "connecting"
	case n.draining:
		v.State = "draining"
	case n.lending && !ollamaUp:
		v.State, v.Reason = "paused", "Ollama stopped. Lending resumes when it's back."
	case n.lending && !n.hubOK && !n.lastBeat.IsZero():
		v.State, v.Reason = "paused", "Can't reach the network's host right now. Lending resumes when it's back."
	case n.lending && n.pausedReason != "":
		v.State, v.Reason = "paused", n.pausedReason
	case n.lending:
		v.State = "connected"
	}
	for _, rs := range n.running {
		v.Running = append(v.Running, runningView{
			ID: rs.ID, Model: rs.Model, Purpose: rs.Purpose, Requester: rs.Requester, RequesterDevice: rs.RequesterDevice,
			Seconds: int(time.Since(rs.Started).Seconds()), Tokens: rs.Tokens,
		})
	}
	return v, n.hubOK, n.hubErr, n.snap
}

// interruptPoll makes the lending loop re-check things right away, e.g.
// when Ollama stops.
func (n *Node) interruptPoll() {
	n.mu.Lock()
	if n.pollCancel != nil {
		n.pollCancel()
	}
	n.mu.Unlock()
	signal1(n.wake)
	signal1(n.beatNow)
}

func (n *Node) clearLendError() {
	n.mu.Lock()
	n.lendErr = ""
	n.mu.Unlock()
}
