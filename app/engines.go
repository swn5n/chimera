package main

// Engines: models that run on this computer outside Ollama, each from its own
// server that Chimera starts when a chat needs it and stops once it's been idle
// a while (DeepSeek V4.1 Flash read from an SSD by InferSSD, for example). An
// engine is this computer's own: it's never lent, never shown to the network,
// and long tasks and Heads don't use it. Engines are described in engines.json
// in the data folder; the server must speak the OpenAI chat API (streamed).

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

// EngineSpec is one entry of engines.json.
type EngineSpec struct {
	ID   string `json:"id"`             // lowercase letters, digits, dots and dashes: "deepseek-v4.1-flash"
	Name string `json:"name"`           // shown in the model picker
	Note string `json:"note,omitempty"` // a line shown with it
	// Command starts the server. {port}, {context} and {model} are filled in.
	Command []string `json:"command"`
	Dir     string   `json:"dir,omitempty"` // the command's working folder
	// ModelPaths: the first one that exists is {model} (say, an SSD that may be
	// unplugged, then a copy on the internal drive).
	ModelPaths []string `json:"model_paths,omitempty"`
	Port       int      `json:"port"`    // its API, on 127.0.0.1
	Context    int      `json:"context"` // tokens the server holds: prompt and answer
	MaxTokens  int      `json:"max_tokens,omitempty"`
	// Thinking lists the thinking levels it takes ("off" turns thinking off; the
	// rest go as reasoning_effort). Empty: it doesn't think, or not on request.
	Thinking        []string `json:"thinking,omitempty"`
	DefaultThinking string   `json:"default_thinking,omitempty"`
	IdleMinutes     int      `json:"idle_minutes,omitempty"`  // stop it after this long unused (default 20)
	StartSeconds    int      `json:"start_seconds,omitempty"` // how long it may take to be ready (default 600)
	FreeOllama      bool     `json:"free_ollama,omitempty"`   // unload Ollama's idle models before starting
	ModelName       string   `json:"model_name,omitempty"`    // the request's "model" field, if the server wants one
}

// EngineView is what the interface shows of an engine.
type EngineView struct {
	ID              string   `json:"id"`
	Model           string   `json:"model"` // what a chat asks for: "engine:<id>"
	Name            string   `json:"name"`
	Note            string   `json:"note,omitempty"`
	Status          string   `json:"status"` // stopped, starting, ready, stopping, error, missing
	Error           string   `json:"error,omitempty"`
	Busy            bool     `json:"busy"`
	External        bool     `json:"external,omitempty"` // was already running: not Chimera's to stop
	ModelPath       string   `json:"model_path,omitempty"`
	Context         int      `json:"context"`
	MaxTokens       int      `json:"max_tokens"`
	Thinking        []string `json:"thinking,omitempty"`
	DefaultThinking string   `json:"default_thinking,omitempty"`
	IdleMinutes     int      `json:"idle_minutes"`
	ReadySecs       float64  `json:"ready_secs,omitempty"` // how long the last start took
	Since           string   `json:"since,omitempty"`      // when it became ready
}

const enginePrefix = "engine:"

// engineID returns the engine a chat's model names, if it names one.
func engineID(model string) (string, bool) {
	if !strings.HasPrefix(model, enginePrefix) {
		return "", false
	}
	id := strings.TrimPrefix(model, enginePrefix)
	return id, validEngineID(id)
}

var engineIDRe = regexp.MustCompile(`^[a-z0-9][a-z0-9.-]{0,47}$`)

func validEngineID(id string) bool { return engineIDRe.MatchString(id) }

func (s EngineSpec) idle() time.Duration {
	if s.IdleMinutes > 0 {
		return time.Duration(s.IdleMinutes) * time.Minute
	}
	return 20 * time.Minute
}

func (s EngineSpec) startTimeout() time.Duration {
	if s.StartSeconds > 0 {
		return time.Duration(s.StartSeconds) * time.Second
	}
	return 10 * time.Minute
}

func (s EngineSpec) context() int {
	if s.Context > 0 {
		return s.Context
	}
	return 32768
}

func (s EngineSpec) maxTokens() int {
	if s.MaxTokens > 0 && s.MaxTokens < s.context() {
		return s.MaxTokens
	}
	return s.context() * 3 / 4
}

// modelPath is the first model file there is, or "" (and the first one wanted).
func (s EngineSpec) modelPath() (string, string) {
	for _, p := range s.ModelPaths {
		if fileExists(p) {
			return p, ""
		}
	}
	if len(s.ModelPaths) > 0 {
		return "", s.ModelPaths[0]
	}
	return "", ""
}

// argv fills in the command's placeholders.
func (s EngineSpec) argv(model string) []string {
	out := make([]string, len(s.Command))
	r := strings.NewReplacer("{port}", strconv.Itoa(s.Port), "{context}", strconv.Itoa(s.context()), "{model}", model)
	for i, a := range s.Command {
		out[i] = r.Replace(a)
	}
	return out
}

// thinkingFields turns a thinking level into the request's fields.
func (s EngineSpec) thinkingFields(level string, body map[string]any) {
	if len(s.Thinking) == 0 {
		return
	}
	if level == "" {
		level = s.DefaultThinking
	}
	ok := false
	for _, t := range s.Thinking {
		if t == level {
			ok = true
		}
	}
	if !ok || level == "" {
		return
	}
	if level == "off" {
		body["chat_template_kwargs"] = map[string]any{"enable_thinking": false}
		return
	}
	body["chat_template_kwargs"] = map[string]any{"enable_thinking": true}
	body["reasoning_effort"] = level
}

type engine struct {
	spec EngineSpec

	status    string
	err       string
	external  bool
	modelPath string
	cmd       *exec.Cmd
	watch     *exec.Cmd // kills the server if Chimera dies first
	watchPipe *os.File  // its end of the watchdog's pipe
	exited    chan struct{}
	readyIn   time.Duration
	readyAt   time.Time
	lastUsed  time.Time
	busy      int
	starting  chan struct{} // closed when a start finishes (ready or not)
	cancels   map[int]context.CancelFunc
	nextReq   int
	turn      chan struct{} // one reply at a time
}

// EngineManager runs the engines in engines.json.
type EngineManager struct {
	app  *App
	path string
	logs string

	mu      sync.Mutex
	specs   []EngineSpec
	loadErr string
	modTime time.Time
	engines map[string]*engine
	client  *http.Client
}

func NewEngineManager(app *App, dataDir string) *EngineManager {
	m := &EngineManager{app: app, path: filepath.Join(dataDir, "engines.json"), logs: filepath.Join(dataDir, "engines"),
		engines: map[string]*engine{},
		client:  &http.Client{Transport: &http.Transport{Proxy: nil, DialContext: (&net.Dialer{Timeout: 5 * time.Second}).DialContext}}}
	m.reloadLocked()
	return m
}

// reloadLocked rereads engines.json when it changed, so edits apply without a restart.
func (m *EngineManager) reloadLocked() {
	st, err := os.Stat(m.path)
	if err != nil {
		m.specs, m.loadErr, m.modTime = nil, "", time.Time{}
		return
	}
	if st.ModTime().Equal(m.modTime) {
		return
	}
	m.modTime = st.ModTime()
	b, err := os.ReadFile(m.path)
	if err != nil {
		m.loadErr = err.Error()
		return
	}
	var specs []EngineSpec
	if err := json.Unmarshal(b, &specs); err != nil {
		m.loadErr = "engines.json: " + err.Error()
		log.Printf("engines: %s", m.loadErr)
		return
	}
	m.loadErr = ""
	m.specs = nil
	seen := map[string]bool{}
	for _, s := range specs {
		if !validEngineID(s.ID) || seen[s.ID] || len(s.Command) == 0 || s.Port <= 0 || s.Port > 65535 {
			log.Printf("engines: skipping an entry with a bad id, no command or no port (%q)", s.ID)
			continue
		}
		if s.Name == "" {
			s.Name = s.ID
		}
		seen[s.ID] = true
		m.specs = append(m.specs, s)
		if e := m.engines[s.ID]; e != nil {
			e.spec = s // a running server keeps going; new settings apply from its next start
		}
	}
}

func (m *EngineManager) getLocked(id string) (*engine, bool) {
	m.reloadLocked()
	for _, s := range m.specs {
		if s.ID != id {
			continue
		}
		e := m.engines[id]
		if e == nil {
			e = &engine{spec: s, status: "stopped", cancels: map[int]context.CancelFunc{}, turn: make(chan struct{}, 1)}
			m.engines[id] = e
		}
		return e, true
	}
	return nil, false
}

// Views lists the engines for the interface.
func (m *EngineManager) Views() []EngineView {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.reloadLocked()
	out := []EngineView{}
	for _, s := range m.specs {
		e, _ := m.getLocked(s.ID)
		v := EngineView{ID: s.ID, Model: enginePrefix + s.ID, Name: s.Name, Note: s.Note, Status: e.status, Error: e.err,
			Busy: e.busy > 0, External: e.external, ModelPath: e.modelPath, Context: s.context(), MaxTokens: s.maxTokens(),
			Thinking: s.Thinking, DefaultThinking: s.DefaultThinking, IdleMinutes: int(s.idle() / time.Minute)}
		if e.status == "stopped" || e.status == "error" {
			if p, want := s.modelPath(); p == "" && want != "" {
				v.Status, v.Error = "missing", "Can't find the model at "+want+" (is the drive plugged in?)"
			} else {
				v.ModelPath = p
			}
		}
		if !e.readyAt.IsZero() && e.status == "ready" {
			v.ReadySecs = round1(e.readyIn.Seconds())
			v.Since = e.readyAt.Format(time.RFC3339)
		}
		out = append(out, v)
	}
	return out
}

// TextBudget is how much of attached files' text (in characters) goes with a
// message to this engine: about a quarter of its window, so the chat and the
// answer keep the rest.
func (m *EngineManager) TextBudget(id string) int {
	m.mu.Lock()
	defer m.mu.Unlock()
	if e, ok := m.getLocked(id); ok {
		return e.spec.context() * 3 / 4
	}
	return 24000
}

// Running says whether the engine's server is up or on its way (it holds its memory then).
func (m *EngineManager) Running(id string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	e, ok := m.getLocked(id)
	return ok && (e.status == "ready" || e.status == "starting" || e.status == "stopping")
}

func (m *EngineManager) Name(id string) string {
	m.mu.Lock()
	defer m.mu.Unlock()
	if e, ok := m.getLocked(id); ok {
		return e.spec.Name
	}
	return id
}

// Start makes sure the engine's server is up, starting it if it isn't.
// status is told what's happening while it waits.
func (m *EngineManager) Start(ctx context.Context, id string, status func(string)) error {
	for {
		m.mu.Lock()
		e, ok := m.getLocked(id)
		if !ok {
			m.mu.Unlock()
			return fmt.Errorf("there's no engine called %s here (see engines.json)", id)
		}
		switch e.status {
		case "ready":
			m.mu.Unlock()
			return nil
		case "starting", "stopping":
			wait := e.starting
			m.mu.Unlock()
			if status != nil {
				status("Waiting for " + e.spec.Name + " to start…")
			}
			if wait == nil {
				time.Sleep(500 * time.Millisecond)
				continue
			}
			select {
			case <-wait:
			case <-ctx.Done():
				return ctx.Err()
			}
			continue
		}
		e.status, e.err = "starting", ""
		e.starting = make(chan struct{})
		spec := e.spec
		m.mu.Unlock()
		m.app.notify()

		err := m.launch(ctx, e, spec, status)
		m.mu.Lock()
		if err != nil {
			e.status, e.err = "error", err.Error()
		}
		close(e.starting)
		e.starting = nil
		m.mu.Unlock()
		m.app.notify()
		return err
	}
}

func (m *EngineManager) health(ctx context.Context, port int) bool {
	cctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(cctx, "GET", fmt.Sprintf("http://127.0.0.1:%d/health", port), nil)
	res, err := m.client.Do(req)
	if err != nil {
		return false
	}
	io.Copy(io.Discard, io.LimitReader(res.Body, 1<<16))
	res.Body.Close()
	return res.StatusCode == 200
}

func portBusy(port int) bool {
	c, err := net.DialTimeout("tcp", fmt.Sprintf("127.0.0.1:%d", port), 500*time.Millisecond)
	if err != nil {
		return false
	}
	c.Close()
	return true
}

func (m *EngineManager) launch(ctx context.Context, e *engine, spec EngineSpec, status func(string)) error {
	say := func(s string) {
		if status != nil {
			status(s)
		}
	}
	if portBusy(spec.Port) {
		// Something already answers there: use it if it's a healthy server, but it isn't ours to stop.
		if m.health(ctx, spec.Port) {
			m.mu.Lock()
			e.status, e.external, e.readyAt, e.readyIn, e.lastUsed = "ready", true, time.Now(), 0, time.Now()
			e.modelPath = ""
			m.mu.Unlock()
			log.Printf("engines: %s was already running on port %d; using it", spec.ID, spec.Port)
			return nil
		}
		return fmt.Errorf("port %d is in use by another program, so %s can't start", spec.Port, spec.Name)
	}
	model, want := spec.modelPath()
	if model == "" && want != "" {
		return fmt.Errorf("can't find the model at %s (is the drive plugged in?)", want)
	}
	argv := spec.argv(model)
	if _, err := exec.LookPath(argv[0]); err != nil {
		return fmt.Errorf("can't find %s", argv[0])
	}
	if spec.FreeOllama {
		say("Making room: unloading Ollama's idle models…")
		m.app.unloadIdleOllama(ctx)
	}
	where := "this computer"
	if model != "" {
		where = filepath.Dir(model)
		if strings.HasPrefix(model, "/Volumes/") {
			where = strings.SplitN(strings.TrimPrefix(model, "/Volumes/"), "/", 2)[0]
		}
	}
	say(fmt.Sprintf("Starting %s from %s…", spec.Name, where))
	_ = os.MkdirAll(m.logs, 0o755)
	logf, err := os.Create(filepath.Join(m.logs, spec.ID+".log"))
	if err != nil {
		return err
	}
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Dir = spec.Dir
	cmd.Env = engineEnv()
	cmd.Stdout, cmd.Stderr = logf, logf
	newProcessGroup(cmd)
	hideWindow(cmd)
	started := time.Now()
	if err := cmd.Start(); err != nil {
		logf.Close()
		return fmt.Errorf("couldn't start %s: %v", spec.Name, err)
	}
	exited := make(chan struct{})
	go func() {
		_ = cmd.Wait()
		logf.Close()
		close(exited)
		m.mu.Lock()
		if e.cmd == cmd {
			if e.status != "stopping" && e.status != "stopped" {
				e.status = "error"
				e.err = spec.Name + " stopped by itself: " + lastLogLine(filepath.Join(m.logs, spec.ID+".log"))
			} else {
				e.status = "stopped"
			}
			e.cmd = nil
			if e.watch != nil && e.watch.Process != nil {
				_ = e.watch.Process.Kill()
			}
			e.watch, e.watchPipe = nil, nil
			for _, c := range e.cancels {
				c()
			}
		}
		m.mu.Unlock()
		m.app.notify()
	}()
	watch, pipe := startWatchdog(cmd.Process.Pid)
	m.mu.Lock()
	e.cmd, e.exited, e.watch, e.watchPipe, e.external, e.modelPath = cmd, exited, watch, pipe, false, model
	m.mu.Unlock()
	log.Printf("engines: started %s (pid %d): %s", spec.ID, cmd.Process.Pid, strings.Join(argv, " "))

	deadline := time.Now().Add(spec.startTimeout())
	tick := time.NewTicker(time.Second)
	defer tick.Stop()
	for {
		if m.health(ctx, spec.Port) {
			m.mu.Lock()
			e.status, e.readyAt, e.readyIn, e.lastUsed = "ready", time.Now(), time.Since(started), time.Now()
			m.mu.Unlock()
			log.Printf("engines: %s is ready after %.0f s", spec.ID, time.Since(started).Seconds())
			return nil
		}
		select {
		case <-exited:
			return fmt.Errorf("%s didn't start: %s", spec.Name, lastLogLine(filepath.Join(m.logs, spec.ID+".log")))
		case <-ctx.Done():
			m.Stop(spec.ID)
			return ctx.Err()
		case <-tick.C:
		}
		if time.Now().After(deadline) {
			m.Stop(spec.ID)
			return fmt.Errorf("%s wasn't ready after %s", spec.Name, spec.startTimeout())
		}
		say(fmt.Sprintf("Starting %s from %s… (%d s)", spec.Name, where, int(time.Since(started).Seconds())))
	}
}

// engineEnv is a plain environment for an engine: some servers refuse to start
// when they see variables they don't know (InferSSD refuses CONTEXT, MODEL and others).
func engineEnv() []string {
	var env []string
	for _, k := range []string{"HOME", "USER", "LOGNAME", "PATH", "SHELL", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "USERPROFILE", "APPDATA", "LOCALAPPDATA"} {
		if v := os.Getenv(k); v != "" {
			env = append(env, k+"="+v)
		}
	}
	return env
}

func lastLogLine(path string) string {
	b, err := os.ReadFile(path)
	if err != nil {
		return "no log"
	}
	if len(b) > 16<<10 {
		b = b[len(b)-16<<10:]
	}
	lines := strings.Split(strings.TrimSpace(string(b)), "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		if l := strings.TrimSpace(lines[i]); l != "" {
			if len(l) > 300 {
				l = l[:300] + "…"
			}
			return l
		}
	}
	return "its log is empty"
}

// Stop stops the engine's server if Chimera started it, and ends any reply it's writing.
func (m *EngineManager) Stop(id string) {
	m.mu.Lock()
	e, ok := m.getLocked(id)
	if !ok {
		m.mu.Unlock()
		return
	}
	for _, c := range e.cancels {
		c()
	}
	if e.external {
		e.status, e.external = "stopped", false // just forget it: it isn't ours
		m.mu.Unlock()
		m.app.notify()
		return
	}
	cmd, exited, watch := e.cmd, e.exited, e.watch
	if cmd == nil {
		if e.status != "starting" {
			e.status = "stopped"
		}
		m.mu.Unlock()
		m.app.notify()
		return
	}
	e.status = "stopping"
	m.mu.Unlock()
	m.app.notify()
	if watch != nil && watch.Process != nil {
		_ = watch.Process.Kill() // so it can't later signal a group whose number was reused
	}
	_ = interruptGroup(cmd) // a server shuts down cleanly on Ctrl-C
	select {
	case <-exited:
	case <-time.After(20 * time.Second):
		killGroup(cmd)
		<-exited
	}
	log.Printf("engines: stopped %s", id)
}

// StopAll stops every engine Chimera started, at once (when Chimera quits).
func (m *EngineManager) StopAll() {
	m.mu.Lock()
	var ids []string
	for id, e := range m.engines {
		if e.cmd != nil {
			ids = append(ids, id)
		}
	}
	m.mu.Unlock()
	var wg sync.WaitGroup
	for _, id := range ids {
		wg.Add(1)
		go func(id string) { defer wg.Done(); m.Stop(id) }(id)
	}
	wg.Wait()
}

// idleLoop stops servers nobody has used for a while: they hold a lot of memory.
func (m *EngineManager) idleLoop() {
	t := time.NewTicker(30 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-m.app.quit:
			return
		case <-t.C:
		}
		m.mu.Lock()
		var stop []string
		for id, e := range m.engines {
			if e.cmd != nil && e.status == "ready" && e.busy == 0 && time.Since(e.lastUsed) > e.spec.idle() {
				stop = append(stop, id)
			}
		}
		m.mu.Unlock()
		for _, id := range stop {
			log.Printf("engines: %s has been idle a while; stopping it to free memory", id)
			m.Stop(id)
		}
	}
}

// engineChunk is one streamed event of the OpenAI chat API.
type engineChunk struct {
	Choices []struct {
		Delta struct {
			Content          string `json:"content"`
			ReasoningContent string `json:"reasoning_content"`
			Reasoning        string `json:"reasoning"`
		} `json:"delta"`
		FinishReason *string `json:"finish_reason"`
	} `json:"choices"`
	Usage *struct {
		PromptTokens     int `json:"prompt_tokens"`
		CompletionTokens int `json:"completion_tokens"`
	} `json:"usage"`
	Timings *struct {
		PromptN            int     `json:"prompt_n"`
		PromptPerSecond    float64 `json:"prompt_per_second"`
		PredictedN         int     `json:"predicted_n"`
		PredictedPerSecond float64 `json:"predicted_per_second"`
	} `json:"timings"`
	Error any `json:"error"`
}

// Run writes one reply with the engine, starting its server first if needed.
// It returns the final event (done, error or cancelled).
func (m *EngineManager) Run(ctx context.Context, id string, msgs []ChatMessage, thinking string, emit func(genEvent)) genEvent {
	m.mu.Lock()
	e, ok := m.getLocked(id)
	if !ok {
		m.mu.Unlock()
		return genEvent{Type: "error", Error: "There's no engine called " + id + " on this computer any more."}
	}
	spec := e.spec
	e.busy++
	e.lastUsed = time.Now()
	n := e.nextReq
	e.nextReq++
	rctx, cancel := context.WithCancel(ctx)
	e.cancels[n] = cancel
	turn := e.turn
	m.mu.Unlock()
	m.app.notify()
	defer func() {
		cancel()
		m.mu.Lock()
		e.busy--
		e.lastUsed = time.Now()
		delete(e.cancels, n)
		m.mu.Unlock()
		m.app.notify()
	}()

	cfg := m.app.config()
	emit(genEvent{Type: "assigned", Device: cfg.DeviceID, DeviceName: cfg.DeviceName, Owner: cfg.Owner, Model: spec.Name, Local: true})
	status := func(s string) { emit(genEvent{Type: "status", Reason: s}) }

	// One reply at a time: the server works on one prompt at once.
	select {
	case turn <- struct{}{}:
	default:
		status("Waiting for " + spec.Name + " to finish another reply…")
		select {
		case turn <- struct{}{}:
		case <-rctx.Done():
			return genEvent{Type: "cancelled", Local: true}
		}
	}
	defer func() { <-turn }()

	if err := m.Start(rctx, id, status); err != nil {
		if rctx.Err() != nil {
			return genEvent{Type: "cancelled", Local: true}
		}
		return genEvent{Type: "error", Error: err.Error()}
	}
	prompt := historyTokens(msgs)
	room := spec.context() - prompt - 512
	if room < 1024 {
		return genEvent{Type: "error", Error: fmt.Sprintf("This chat is too long for %s's %s-token window. Start a new chat (or raise its context in engines.json).", spec.Name, fmtK(spec.context()))}
	}
	maxTok := spec.maxTokens()
	if maxTok > room {
		maxTok = room
	}
	body := map[string]any{"messages": openAIMessages(msgs), "stream": true, "max_tokens": maxTok,
		"stream_options": map[string]any{"include_usage": true}}
	if spec.ModelName != "" {
		body["model"] = spec.ModelName
	}
	spec.thinkingFields(thinking, body)
	status(fmt.Sprintf("Reading your message (about %s tokens)…", fmtNum(prompt)))
	b, _ := json.Marshal(body)
	req, _ := http.NewRequestWithContext(rctx, "POST", fmt.Sprintf("http://127.0.0.1:%d/v1/chat/completions", spec.Port), bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	start := time.Now()
	res, err := m.client.Do(req)
	if err != nil {
		if rctx.Err() != nil {
			return genEvent{Type: "cancelled", Local: true}
		}
		return genEvent{Type: "error", Error: fmt.Sprintf("%s didn't answer: %v", spec.Name, err)}
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		msg, _ := io.ReadAll(io.LimitReader(res.Body, 4096))
		return genEvent{Type: "error", Error: fmt.Sprintf("%s said %d: %s", spec.Name, res.StatusCode, strings.TrimSpace(string(msg)))}
	}
	var (
		final              = genEvent{Type: "done", Free: true, Local: true}
		firstAt, answerAt  time.Time
		finish             string
		gotContent, gotAny bool
		sawDone            bool
		thinkText          strings.Builder
		answerText         strings.Builder
	)
	sc := bufio.NewScanner(res.Body)
	sc.Buffer(make([]byte, 0, 64<<10), 8<<20)
	for sc.Scan() {
		line := sc.Bytes()
		if !bytes.HasPrefix(line, []byte("data:")) {
			continue
		}
		data := bytes.TrimSpace(line[5:])
		if bytes.Equal(data, []byte("[DONE]")) {
			sawDone = true
			break
		}
		var ch engineChunk
		if json.Unmarshal(data, &ch) != nil {
			continue
		}
		if ch.Error != nil {
			return genEvent{Type: "error", Error: fmt.Sprintf("%s: %v", spec.Name, ch.Error)}
		}
		if ch.Usage != nil {
			final.PromptTokens, final.Tokens = ch.Usage.PromptTokens, ch.Usage.CompletionTokens
		}
		if ch.Timings != nil {
			if ch.Timings.PredictedPerSecond > 0 {
				final.TokPerSec = round2(ch.Timings.PredictedPerSecond)
			}
			if ch.Timings.PredictedN > 0 && final.Tokens == 0 {
				final.Tokens = ch.Timings.PredictedN
			}
		}
		for _, c := range ch.Choices {
			if c.FinishReason != nil && *c.FinishReason != "" {
				finish = *c.FinishReason
			}
			t := c.Delta.ReasoningContent
			if t == "" {
				t = c.Delta.Reasoning
			}
			if t == "" && c.Delta.Content == "" {
				continue
			}
			if !gotAny {
				gotAny, firstAt = true, time.Now()
				if t != "" {
					status("Thinking…")
				} else {
					status("Writing…")
				}
			}
			if c.Delta.Content != "" && !gotContent {
				gotContent, answerAt = true, time.Now()
			}
			thinkText.WriteString(t)
			answerText.WriteString(c.Delta.Content)
			emit(genEvent{Type: "delta", Content: c.Delta.Content, Thinking: t})
		}
	}
	if rctx.Err() == nil && (sc.Err() != nil || (!sawDone && finish == "")) {
		// The server went away mid-reply: say so plainly, with its last words if it died.
		why := "the connection broke"
		time.Sleep(300 * time.Millisecond) // let the exit be noticed
		m.mu.Lock()
		if e.status == "error" && e.err != "" {
			why = e.err
		}
		m.mu.Unlock()
		return genEvent{Type: "error", Error: fmt.Sprintf("%s stopped in the middle of its reply (%s). What it wrote is kept above.", spec.Name, strings.TrimSuffix(why, "."))}
	}
	if rctx.Err() != nil {
		final.Type = "cancelled"
	}
	if finish == "length" {
		final.DoneReason = "length"
	}
	// Some servers send the whole thinking again as the answer when they're cut off mid-thought.
	if final.DoneReason == "length" && answerText.Len() > 0 && answerText.String() == thinkText.String() {
		emit(genEvent{Type: "replay", Content: "", Thinking: thinkText.String()})
	}
	if !firstAt.IsZero() {
		end := time.Now()
		if !answerAt.IsZero() {
			end = answerAt
		}
		if thinkText.Len() > 0 {
			final.ThinkSecs = round1(end.Sub(firstAt).Seconds())
		}
		final.WaitSecs = round1(firstAt.Sub(start).Seconds())
	}
	return final
}

func openAIMessages(msgs []ChatMessage) []map[string]string {
	out := make([]map[string]string, 0, len(msgs))
	for _, m := range msgs {
		out = append(out, map[string]string{"role": m.Role, "content": m.Content})
	}
	return out
}

func fmtK(n int) string {
	if n >= 1024 {
		return fmt.Sprintf("%dK", n/1024)
	}
	return strconv.Itoa(n)
}

func fmtNum(n int) string {
	s := strconv.Itoa(n)
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	return s
}

// unloadIdleOllama asks Ollama to let go of every loaded model nothing is using,
// to make room in memory for an engine.
func (a *App) unloadIdleOllama(ctx context.Context) {
	if !a.ollama.Running() {
		return
	}
	cctx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	c := a.ollama.Client()
	loaded, err := c.PS(cctx)
	if err != nil {
		return
	}
	for _, p := range loaded {
		if a.ollamaBusy(p.Name) {
			continue
		}
		if err := c.Unload(cctx, p.Name); err == nil {
			log.Printf("engines: unloaded %s from Ollama to make room", p.Name)
		}
	}
}

// ollamaBusy says whether a loaded Ollama model is being used right now: by a
// step this computer is running for the network, or by one of its own chats.
func (a *App) ollamaBusy(model string) bool {
	if a.node != nil && a.node.runningModel(model) {
		return true
	}
	return a.gens.usingLocal(model)
}
