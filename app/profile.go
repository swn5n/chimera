package main

// What this computer can run: usable memory, the largest model that fits
// with room to spare (big models that barely fit spill out of GPU memory and
// time out), how much context each installed model can have here, measured
// speed, and what the computer is best used for.

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const (
	comfortShare = 0.70 // recommended: model + 8K context within 70% of usable memory
	maxShare     = 0.97 // ceiling before Ollama spills layers onto the CPU (slow, and steps time out)
	minCtx       = 2048
)

type DeviceProfile struct {
	UsableGB     float64    `json:"usable_gb"`
	ComfortGB    float64    `json:"comfort_gb"`
	MaxGB        float64    `json:"max_gb"`
	BandwidthGBs float64    `json:"bandwidth_gbs,omitempty"`
	Accel        string     `json:"accel"`
	BestFor      []string   `json:"best_for"`
	Tools        []ToolInfo `json:"tools"`
	CanTest      bool       `json:"can_test"` // can safely sandbox library test runs
}

// usableMemory is how much memory a model can use on this computer.
func usableMemory(s SysInfo) (float64, string) {
	if s.OS == "macOS" {
		share := 0.67 // macOS lets the GPU use about two thirds of RAM on smaller Macs...
		if s.RAMGB >= 48 {
			share = 0.75 // ...and about three quarters on bigger ones
		}
		return round1(s.RAMGB * share), "Apple GPU"
	}
	best, accel := 0.0, ""
	for _, g := range s.GPUs {
		n := strings.ToLower(g.Name)
		if g.VRAMGB > best {
			best = g.VRAMGB
			switch {
			case strings.Contains(n, "nvidia") || strings.Contains(n, "geforce") || strings.Contains(n, "rtx") || strings.Contains(n, "quadro"):
				accel = "NVIDIA GPU"
			case strings.Contains(n, "amd") || strings.Contains(n, "radeon"):
				accel = "AMD GPU"
			case strings.Contains(n, "intel") || strings.Contains(n, "arc"):
				accel = "Intel GPU"
			default:
				accel = "GPU"
			}
		}
	}
	if best >= 2 { // integrated GPUs report a sliver of memory; Ollama runs those on the CPU
		return round1(math.Max(0, best-0.5)), accel
	}
	return round1(s.RAMGB * 0.5), "CPU only"
}

// Memory bandwidth decides generation speed. Most specific names first.
var bandwidthTable = []struct {
	match string
	gbs   float64
}{
	{"m4 max|40-core", 546}, {"m4 max", 410}, {"m4 pro", 273}, {"m4", 120},
	{"m3 ultra", 819}, {"m3 max|40-core", 400}, {"m3 max", 300}, {"m3 pro", 150}, {"m3", 100},
	{"m2 ultra", 800}, {"m2 max", 400}, {"m2 pro", 200}, {"m2", 100},
	{"m1 ultra", 800}, {"m1 max", 400}, {"m1 pro", 200}, {"m1", 68},
	{"m5 max", 610}, {"m5 pro", 300}, {"m5", 153},
	{"5090 laptop", 896}, {"5080 laptop", 896}, {"5070 ti laptop", 672}, {"5070 laptop", 384},
	{"4090 laptop", 576}, {"4080 laptop", 432}, {"4070 laptop", 256}, {"4060 laptop", 256}, {"4050 laptop", 192},
	{"3080 ti laptop", 512}, {"3080 laptop", 448}, {"3070 ti laptop", 448}, {"3070 laptop", 448}, {"3060 laptop", 336},
	{"5090", 1792}, {"5080", 960}, {"5070 ti", 896}, {"5070", 672}, {"5060 ti", 448}, {"5060", 448},
	{"4090", 1008}, {"4080 super", 736}, {"4080", 717}, {"4070 ti super", 672}, {"4070 ti", 504}, {"4070 super", 504}, {"4070", 504}, {"4060 ti", 288}, {"4060", 272},
	{"3090 ti", 1008}, {"3090", 936}, {"3080 ti", 912}, {"3080", 760}, {"3070 ti", 608}, {"3070", 448}, {"3060 ti", 448}, {"3060", 360},
	{"7900 xtx", 960}, {"7900 xt", 800}, {"7900 gre", 576}, {"7800 xt", 624}, {"7700 xt", 432}, {"7600", 288},
	{"9070 xt", 640}, {"9070", 640}, {"9060 xt", 320},
	{"6950 xt", 576}, {"6900 xt", 512}, {"6800 xt", 512}, {"6800", 512}, {"6700 xt", 384},
}

func memoryBandwidth(s SysInfo) float64 {
	names := []string{strings.ToLower(s.Chip)}
	for _, g := range s.GPUs {
		names = append(names, strings.ToLower(g.Name))
	}
	joined := strings.Join(names, " | ")
	for _, row := range bandwidthTable {
		parts := strings.Split(row.match, "|")
		ok := true
		for _, p := range parts {
			if !strings.Contains(joined, p) {
				ok = false
				break
			}
		}
		if ok {
			return row.gbs
		}
	}
	return 0
}

// ---------- measured speed ----------

type perfEntry struct {
	TokS       float64   `json:"tok_s"`
	PromptTokS float64   `json:"prompt_tok_s"`
	LoadS      float64   `json:"load_s"`
	Runs       int       `json:"runs"`
	Updated    time.Time `json:"updated"`
}

type PerfStore struct {
	path string
	mu   sync.Mutex
	m    map[string]perfEntry
}

func NewPerfStore(dataDir string) *PerfStore {
	p := &PerfStore{path: filepath.Join(dataDir, "perf.json"), m: map[string]perfEntry{}}
	if b, err := os.ReadFile(p.path); err == nil {
		_ = json.Unmarshal(b, &p.m)
	}
	return p
}

// Record folds one finished generation into the running averages.
func (p *PerfStore) Record(model string, st ChatStats) {
	if st.EvalCount < 8 || st.EvalDuration <= 0 {
		return
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	key := normModel(model)
	e := p.m[key]
	tok := float64(st.EvalCount) / (float64(st.EvalDuration) / 1e9)
	prompt := 0.0
	if st.PromptEvalDuration > 0 && st.PromptEvalCount > 0 {
		prompt = float64(st.PromptEvalCount) / (float64(st.PromptEvalDuration) / 1e9)
	}
	ema := func(old, v float64) float64 {
		if old == 0 || e.Runs == 0 {
			return v
		}
		return old*0.7 + v*0.3
	}
	e.TokS = round1(ema(e.TokS, tok))
	if prompt > 0 {
		e.PromptTokS = round1(ema(e.PromptTokS, prompt))
	}
	if st.LoadDuration > 500e6 {
		e.LoadS = round1(float64(st.LoadDuration) / 1e9)
	}
	e.Runs++
	e.Updated = time.Now()
	p.m[key] = e
	if b, err := json.MarshalIndent(p.m, "", "  "); err == nil {
		_ = writeFileAtomic(p.path, b)
	}
}

func (p *PerfStore) Get(model string) perfEntry {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.m[normModel(model)]
}

// ---------- putting it together ----------

// overheadGB is Ollama's compute buffers on top of the weights and KV cache.
func overheadGB(sizeGB float64) float64 { return 0.3 + 0.02*sizeGB }

func pow2Floor(n int) int {
	if n < 1 {
		return 0
	}
	p := 1
	for p*2 <= n {
		p *= 2
	}
	return p
}

// fitModel works out the context limit and fit for a model on this computer.
func fitModel(m ModelInfo, usableGB float64) (ctxMax int, fits string) {
	size := m.SizeGB()
	kv := kvBytes(m)
	room := usableGB*maxShare - size - overheadGB(size)
	need8k := needGB(m)
	switch {
	case need8k <= usableGB*comfortShare:
		fits = "comfortable"
	case need8k <= usableGB*maxShare:
		fits = "tight"
	default:
		fits = "too_big"
	}
	if room <= 0 {
		return 0, "too_big"
	}
	tokens := int(room * 1e9 / kv)
	if m.Context > 0 && tokens > m.Context {
		tokens = m.Context
	}
	ctxMax = pow2Floor(tokens)
	if ctxMax < minCtx {
		return 0, "too_big"
	}
	return ctxMax, fits
}

// kvBytes is the KV cache per token of context, estimated when unknown.
func kvBytes(m ModelInfo) float64 {
	if m.KV > 0 {
		return float64(m.KV)
	}
	return kvGuessBytes(m.ParamsB)
}

// needGB is the memory a model takes with an 8K context.
func needGB(m ModelInfo) float64 {
	size := m.SizeGB()
	return size + overheadGB(size) + kvBytes(m)*8192/1e9
}

// estTokS guesses generation speed from memory bandwidth: each token reads
// the active weights once. Mixture-of-experts models also read attention,
// shared layers and routing, so they get less of a boost than their active
// share suggests.
func estTokS(sizeGB, activeFrac, bandwidth float64) float64 {
	if bandwidth <= 0 || sizeGB <= 0 {
		return 0
	}
	if activeFrac <= 0 || activeFrac >= 1 {
		activeFrac = 1
	} else {
		activeFrac = math.Min(1, activeFrac+0.1)
	}
	return round1(bandwidth * 0.6 / (sizeGB * activeFrac))
}

// annotate fills in context limits, fit and speed for this computer's models.
func (a *App) annotate(models []ModelInfo) []ModelInfo {
	sys := a.sysInfo()
	usable, _ := usableMemory(sys)
	bw := memoryBandwidth(sys)
	out := make([]ModelInfo, len(models))
	for i, m := range models {
		m.CtxMax, m.Fits = fitModel(m, usable)
		m.NeedGB = round1(needGB(m))
		m.TokS = a.perf.Get(m.Name).TokS
		m.EstTokS = estTokS(m.SizeGB(), m.ActiveFrac, bw)
		out[i] = m
	}
	return out
}

func (a *App) profile() DeviceProfile {
	sys := a.sysInfo()
	usable, accel := usableMemory(sys)
	p := DeviceProfile{
		UsableGB:     usable,
		ComfortGB:    round1(usable * comfortShare),
		MaxGB:        round1(usable * maxShare),
		BandwidthGBs: memoryBandwidth(sys),
		Accel:        accel,
		Tools:        a.tools.List(),
		CanTest:      canSandbox(),
	}
	if sys.OS == "" {
		p.Accel = "Checking…"
	}
	models := a.annotate(a.ollama.State().Models)
	p.BestFor = bestFor(p, models)
	return p
}

func bestFor(p DeviceProfile, models []ModelInfo) []string {
	var out []string
	switch {
	case p.ComfortGB >= 40:
		out = append(out, "Big models")
	case p.ComfortGB >= 14:
		out = append(out, "Mid-size models")
	case p.ComfortGB > 0:
		out = append(out, "Small models")
	}
	longest, fastest := 0, 0.0
	for _, m := range models {
		if !m.CanChat() || m.Fits == "too_big" {
			continue
		}
		if m.CtxMax > longest {
			longest = m.CtxMax
		}
		if s := m.Speed(); s > fastest {
			fastest = s
		}
	}
	if longest >= 65536 {
		out = append(out, "Long context")
	}
	if fastest >= 60 {
		out = append(out, "Fast replies")
	}
	for _, t := range p.Tools {
		if t.Have && t.Lendable && t.Label != "" {
			out = append(out, t.Label)
		}
	}
	return out
}
