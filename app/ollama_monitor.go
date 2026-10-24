package main

import (
	"context"
	"errors"
	"math"
	"sort"
	"strings"
	"sync"
	"time"
)

// ModelInfo is one Ollama model as Chimera sees it.
type ModelInfo struct {
	Name      string   `json:"name"`
	Digest    string   `json:"digest"`
	SizeBytes int64    `json:"size"`
	Family    string   `json:"family"`
	ParamSize string   `json:"param_size"`
	ParamsB   float64  `json:"params_b"`
	Quant     string   `json:"quant"`
	Caps      []string `json:"caps"`
	Context   int      `json:"context"`
	Loaded    bool     `json:"loaded"`

	// Filled in from the model's architecture and this computer's limits.
	KV         int     `json:"kv,omitempty"`          // KV-cache bytes per token of context
	ActiveFrac float64 `json:"active_frac,omitempty"` // share of weights used per token (MoE < 1)
	CtxMax     int     `json:"ctx_max"`               // largest context that fits on its device
	Fits       string  `json:"fits,omitempty"`        // comfortable, tight, too_big
	NeedGB     float64 `json:"need_gb,omitempty"`     // memory with an 8K context
	TokS       float64 `json:"tok_s,omitempty"`       // measured generation speed here
	EstTokS    float64 `json:"est_tok_s,omitempty"`   // estimate from memory bandwidth
}

func (m ModelInfo) HasCap(c string) bool {
	for _, x := range m.Caps {
		if x == c {
			return true
		}
	}
	return false
}

// Speed is the best guess of tokens per second: measured if we have it.
func (m ModelInfo) Speed() float64 {
	if m.TokS > 0 {
		return m.TokS
	}
	return m.EstTokS
}

func (m ModelInfo) CanChat() bool {
	if len(m.Caps) == 0 {
		return !strings.Contains(strings.ToLower(m.Name), "embed")
	}
	for _, c := range m.Caps {
		if c == "completion" {
			return true
		}
	}
	return false
}

func (m ModelInfo) SizeGB() float64 { return float64(m.SizeBytes) / 1e9 }

type OllamaState struct {
	Status    string      `json:"status"` // checking, running, stopped, missing, starting
	Version   string      `json:"version"`
	URL       string      `json:"url"`
	Installed bool        `json:"installed"`
	Models    []ModelInfo `json:"models"`
	Error     string      `json:"error,omitempty"`
}

type showInfo struct {
	caps       []string
	ctx        int
	kv         int
	activeFrac float64
}

// parseShow pulls capabilities, context length, KV-cache size per token and
// the mixture-of-experts ratio out of /api/show.
func parseShow(sh ollamaShow) showInfo {
	info := showInfo{caps: sh.Capabilities, activeFrac: 1}
	num := func(v any) float64 {
		switch t := v.(type) {
		case float64:
			return t
		case []any: // per-layer values: take the largest
			best := 0.0
			for _, x := range t {
				if f, ok := x.(float64); ok && f > best {
					best = f
				}
			}
			return best
		}
		return 0
	}
	arch, _ := sh.ModelInfo["general.architecture"].(string)
	g := func(name string) float64 { return num(sh.ModelInfo[arch+"."+name]) }
	info.ctx = int(g("context_length"))
	if info.ctx == 0 {
		for k, v := range sh.ModelInfo {
			if strings.HasSuffix(k, ".context_length") && !strings.Contains(k, "vision") {
				info.ctx = int(num(v))
			}
		}
	}
	layers := g("block_count")
	heads := g("attention.head_count")
	kvHeads := g("attention.head_count_kv")
	if kvHeads == 0 {
		kvHeads = heads
	}
	keyLen, valLen := g("attention.key_length"), g("attention.value_length")
	if keyLen == 0 && heads > 0 {
		keyLen = g("embedding_length") / heads
	}
	if valLen == 0 {
		valLen = keyLen
	}
	if layers > 0 && kvHeads > 0 && keyLen > 0 {
		info.kv = int(layers * kvHeads * (keyLen + valLen) * 2) // f16 cache; conservative
	}
	if experts, used := g("expert_count"), g("expert_used_count"); experts > 1 && used > 0 {
		info.activeFrac = math.Min(1, used/experts+0.03)
	}
	return info
}

// OllamaMonitor keeps an up-to-date picture of the local Ollama.
type OllamaMonitor struct {
	app *App

	mu           sync.Mutex
	client       *OllamaClient
	state        OllamaState
	cache        map[string]showInfo // by digest
	lastTags     time.Time
	installed    bool
	installedAt  time.Time
	startingTill time.Time
	kick         chan struct{}
}

func NewOllamaMonitor(app *App, url string) *OllamaMonitor {
	c := NewOllamaClient(url)
	return &OllamaMonitor{
		app:    app,
		client: c,
		state:  OllamaState{Status: "checking", URL: c.Base},
		cache:  map[string]showInfo{},
		kick:   make(chan struct{}, 1),
	}
}

func (m *OllamaMonitor) Client() *OllamaClient {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.client
}

func (m *OllamaMonitor) State() OllamaState {
	m.mu.Lock()
	defer m.mu.Unlock()
	s := m.state
	s.Models = append([]ModelInfo(nil), m.state.Models...)
	return s
}

func (m *OllamaMonitor) Running() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.state.Status == "running"
}

func (m *OllamaMonitor) SetURL(u string) {
	m.mu.Lock()
	m.client = NewOllamaClient(u)
	m.state.URL = m.client.Base
	m.lastTags = time.Time{}
	m.mu.Unlock()
	m.Kick()
}

func (m *OllamaMonitor) Kick() {
	select {
	case m.kick <- struct{}{}:
	default:
	}
}

// Refresh forces the model list to reload on the next check.
func (m *OllamaMonitor) Refresh() {
	m.mu.Lock()
	m.lastTags = time.Time{}
	m.mu.Unlock()
	m.Kick()
}

func (m *OllamaMonitor) loop() {
	for {
		m.check()
		select {
		case <-m.app.quit:
			return
		case <-time.After(2500 * time.Millisecond):
		case <-m.kick:
		}
	}
}

func (m *OllamaMonitor) check() {
	m.mu.Lock()
	client := m.client
	needTags := time.Since(m.lastTags) > 8*time.Second
	m.mu.Unlock()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	ver, err := client.Version(ctx)
	cancel()

	if err != nil {
		m.mu.Lock()
		if time.Since(m.installedAt) > 15*time.Second {
			m.installed = ollamaInstalled()
			m.installedAt = time.Now()
		}
		next := m.state
		next.Version = ""
		next.Models = nil
		next.Installed = m.installed
		next.Error = ""
		switch {
		case time.Now().Before(m.startingTill):
			next.Status = "starting"
		case m.installed:
			next.Status = "stopped"
		default:
			next.Status = "missing"
		}
		wasUp := m.state.Status == "running"
		changed := next.Status != m.state.Status || len(m.state.Models) > 0
		m.state = next
		m.lastTags = time.Time{}
		m.mu.Unlock()
		if changed {
			m.app.notify()
		}
		if wasUp && m.app.node != nil {
			m.app.node.interruptPoll()
		}
		return
	}

	m.mu.Lock()
	models := m.state.Models
	m.mu.Unlock()

	if needTags || len(models) == 0 {
		ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
		tags, terr := client.Tags(ctx)
		cancel()
		if terr == nil {
			models = make([]ModelInfo, 0, len(tags))
			for _, t := range tags {
				mi := ModelInfo{
					Name:      t.Name,
					Digest:    t.Digest,
					SizeBytes: t.Size,
					Family:    t.Details.Family,
					ParamSize: t.Details.ParameterSize,
					ParamsB:   parseParamsB(t.Details.ParameterSize),
					Quant:     t.Details.QuantizationLevel,
				}
				if mi.ParamsB == 0 && t.Size > 0 {
					mi.ParamsB = round1(float64(t.Size) / 0.6e9) // rough guess for 4-bit models
				}
				m.mu.Lock()
				info, ok := m.cache[t.Digest]
				m.mu.Unlock()
				if !ok {
					sctx, scancel := context.WithTimeout(context.Background(), 5*time.Second)
					sh, serr := client.Show(sctx, t.Name)
					scancel()
					if serr == nil {
						info = parseShow(sh)
						m.mu.Lock()
						m.cache[t.Digest] = info
						m.mu.Unlock()
					}
				}
				mi.Caps = info.caps
				mi.Context = info.ctx
				mi.KV = info.kv
				mi.ActiveFrac = info.activeFrac
				models = append(models, mi)
			}
			sort.Slice(models, func(i, j int) bool { return models[i].ParamsB > models[j].ParamsB })
			m.mu.Lock()
			m.lastTags = time.Now()
			m.mu.Unlock()
		}
	}

	ctx, cancel = context.WithTimeout(context.Background(), 3*time.Second)
	loaded, perr := client.PS(ctx)
	cancel()
	if perr == nil {
		set := map[string]bool{}
		for _, l := range loaded {
			set[normModel(l.Name)] = true
			set[normModel(l.Model)] = true
		}
		next := make([]ModelInfo, len(models))
		copy(next, models)
		for i := range next {
			next[i].Loaded = set[normModel(next[i].Name)]
		}
		models = next
	}

	m.mu.Lock()
	prev := m.state
	cameBack := prev.Status != "running"
	m.state = OllamaState{Status: "running", Version: ver, URL: client.Base, Installed: true, Models: models}
	m.installed = true
	m.startingTill = time.Time{}
	changed := prev.Status != "running" || prev.Version != ver || !sameModels(prev.Models, models)
	m.mu.Unlock()
	if changed {
		m.app.notify()
	}
	if cameBack && m.app.node != nil {
		m.app.node.interruptPoll()
	}
}

func sameModels(a, b []ModelInfo) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i].Name != b[i].Name || a[i].Digest != b[i].Digest || a[i].Loaded != b[i].Loaded || len(a[i].Caps) != len(b[i].Caps) {
			return false
		}
	}
	return true
}

var errOllamaMissing = errors.New("Ollama isn't installed on this computer. Get it from ollama.com/download")

// Start opens Ollama if it's installed and waits for it to answer.
func (m *OllamaMonitor) Start(wait time.Duration) error {
	if m.Running() {
		return nil
	}
	if !ollamaInstalled() {
		return errOllamaMissing
	}
	m.mu.Lock()
	m.startingTill = time.Now().Add(wait)
	m.state.Status = "starting"
	m.mu.Unlock()
	m.app.notify()
	if err := startOllama(); err != nil {
		m.mu.Lock()
		m.startingTill = time.Time{}
		m.mu.Unlock()
		m.Kick()
		return err
	}
	deadline := time.Now().Add(wait)
	for time.Now().Before(deadline) {
		time.Sleep(700 * time.Millisecond)
		m.Kick()
		if m.Running() {
			return nil
		}
	}
	m.mu.Lock()
	m.startingTill = time.Time{}
	m.mu.Unlock()
	m.Kick()
	return errors.New("Ollama didn't start in time. Try opening it yourself, then press Connect again")
}
