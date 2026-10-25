package main

// A curated set of Ollama models, so each computer can download what fits it
// well (with headroom, to avoid models that barely fit and then time out),
// and the network ends up with the same models for the same jobs.

import (
	"math"
	"runtime"
	"sort"
	"strings"
)

type CatalogItem struct {
	Tag     string   `json:"tag"`
	Label   string   `json:"label"`
	SizeGB  float64  `json:"size_gb"`
	ParamsB float64  `json:"params_b"`
	ActiveB float64  `json:"active_b,omitempty"`
	CtxK    int      `json:"ctx_k"`
	Caps    []string `json:"caps"`
	Roles   []string `json:"roles"`
	Blurb   string   `json:"blurb"`
	MacOnly bool     `json:"mac_only,omitempty"`
	NoMac   bool     `json:"no_mac,omitempty"` // no Metal build: Nvidia/AMD/CPU only
	KVKB    float64  `json:"-"`                // KV cache per token of context, when known from the architecture

	// For this computer:
	Fit        string   `json:"fit"`     // comfortable, tight, too_big, unsupported
	NeedGB     float64  `json:"need_gb"` // memory with an 8K context
	Installed  bool     `json:"installed"`
	Best       bool     `json:"best"`
	EstTokS    float64  `json:"est_tok_s,omitempty"`
	OverLimit  bool     `json:"over_limit,omitempty"` // bigger than your lending limit
	NetDevices []string `json:"net_devices"`          // devices in the network that have it
	NetMixed   bool     `json:"net_mixed,omitempty"`  // devices have different versions
}

// The curated catalog. Every tag was confirmed on ollama.com (Oct 24, 2026); sizes are the default
// tag's download. Rough tiers: small/fast → coding → vision → reasoning → big → embeddings → media.
// Picture and 3D-mesh generation are mostly NOT Ollama models (and Ollama's own image models are
// Mac-only so far): they're Heads wrapping ComfyUI, Hunyuan3D and the like — see ../heads/.
var catalog = []CatalogItem{
	// ---- small and fast (1–4B) ----
	{Tag: "qwen3.5:2b", Label: "Qwen 3.5 2B", SizeGB: 2.7, ParamsB: 2, CtxK: 256, Caps: []string{"tools", "thinking", "vision"}, Roles: []string{"fast"}, Blurb: "Tiny and quick. Good for routing, short answers and small machines."},
	{Tag: "llama3.2:3b", Label: "Llama 3.2 3B", SizeGB: 2.0, ParamsB: 3, CtxK: 128, Caps: []string{"tools"}, Roles: []string{"fast", "general"}, Blurb: "Meta's tiny all-rounder: quick chat, summaries and simple tool calls on almost any machine."},
	{Tag: "qwen3.5:4b", Label: "Qwen 3.5 4B", SizeGB: 3.3, ParamsB: 4, CtxK: 256, Caps: []string{"tools", "thinking", "vision"}, Roles: []string{"fast", "general", "vision"}, Blurb: "Small Qwen that also looks at images and thinks step by step, in under 4 GB."},
	{Tag: "nemotron-3-nano:4b", Label: "Nemotron 3 Nano 4B", SizeGB: 2.8, ParamsB: 4, CtxK: 256, Caps: []string{"tools", "thinking"}, Roles: []string{"fast", "reasoning"}, Blurb: "NVIDIA's 4B with switchable reasoning and tool use, built for quick local agents."},
	{Tag: "gemma4:e4b", Label: "Gemma 4 E4B", SizeGB: 6.6, ParamsB: 8, CtxK: 128, Caps: []string{"tools", "thinking", "vision", "audio"}, Roles: []string{"fast", "general", "vision", "audio"}, Blurb: "Google's small Gemma 4 (4.5B effective): text, images and audio in under 7 GB."},
	{Tag: "qwen3.5:9b", Label: "Qwen 3.5 9B", SizeGB: 6.6, ParamsB: 9, CtxK: 256, Caps: []string{"tools", "thinking", "vision"}, Roles: []string{"general", "coding", "reasoning", "fast"}, Blurb: "Solid all-rounder that fits almost anything."},

	// ---- coding ----
	{Tag: "qwen2.5-coder:7b", Label: "Qwen 2.5 Coder 7B", SizeGB: 4.7, ParamsB: 7, CtxK: 32, Caps: []string{"tools"}, Roles: []string{"coding"}, Blurb: "Proven small coding model for an 8 GB GPU: completion, fixes, explanations."},
	{Tag: "qwen2.5-coder:14b", Label: "Qwen 2.5 Coder 14B", SizeGB: 9.0, ParamsB: 14, CtxK: 32, Caps: []string{"tools"}, Roles: []string{"coding"}, Blurb: "The 16 GB-GPU coder: clearly stronger than the 7B with room left for context."},
	{Tag: "devstral-small-2:24b", Label: "Devstral Small 2 24B", SizeGB: 15, ParamsB: 24, CtxK: 384, Caps: []string{"tools", "vision"}, Roles: []string{"coding", "planner"}, Blurb: "Mistral's agentic coder: explores whole codebases, edits many files, reads screenshots."},
	{Tag: "qwen3-coder:30b", Label: "Qwen3-Coder 30B", SizeGB: 19, ParamsB: 30.5, ActiveB: 3.3, CtxK: 256, KVKB: 96, Caps: []string{"tools"}, Roles: []string{"coding"}, Blurb: "The go-to local coding model. Fast because only 3B is active."},
	{Tag: "qwen3-coder-next", Label: "Qwen3 Coder Next 80B-A3B", SizeGB: 52, ParamsB: 80, ActiveB: 3, CtxK: 256, Caps: []string{"tools"}, Roles: []string{"coding", "planner"}, Blurb: "Large mixture-of-experts coding agent, quick because 3B fires per token. Needs ~64 GB."},

	// ---- vision ----
	{Tag: "glm-ocr", Label: "GLM-OCR 0.9B", SizeGB: 2.7, ParamsB: 0.9, CtxK: 128, Caps: []string{"vision", "tools"}, Roles: []string{"vision"}, Blurb: "Tiny document reader: scans, tables and formulas to text."},
	{Tag: "qwen3-vl:4b", Label: "Qwen3-VL 4B", SizeGB: 3.3, ParamsB: 4, CtxK: 256, Caps: []string{"tools", "thinking", "vision"}, Roles: []string{"vision", "fast"}, Blurb: "Small image-and-video model for screenshots, OCR and diagrams on 6–8 GB GPUs."},
	{Tag: "qwen3-vl:8b", Label: "Qwen3-VL 8B", SizeGB: 6.2, ParamsB: 8, CtxK: 256, Caps: []string{"tools", "thinking", "vision"}, Roles: []string{"vision"}, Blurb: "Best small model for screenshots, UI and reading text in images."},
	{Tag: "llama3.2-vision:11b", Label: "Llama 3.2 Vision 11B", SizeGB: 7.8, ParamsB: 11, CtxK: 128, Caps: []string{"vision"}, Roles: []string{"vision"}, Blurb: "Meta's image model for a 12 GB GPU: captions, charts, visual Q&A."},
	{Tag: "gemma4:12b", Label: "Gemma 4 12B", SizeGB: 8.0, ParamsB: 12, CtxK: 256, Caps: []string{"tools", "thinking", "vision", "audio"}, Roles: []string{"general", "reasoning", "vision", "audio"}, Blurb: "Sees images and hears audio. Strong for its size."},
	{Tag: "bonsai-2:27b", Label: "Bonsai 2 27B (ternary)", SizeGB: 8.3, ParamsB: 27, CtxK: 256, Caps: []string{"tools", "thinking", "vision"}, Roles: []string{"vision", "general"}, Blurb: "A 27B vision model squeezed into 8.3 GB with ternary weights: a big model on a small GPU."},

	// ---- reasoning ----
	{Tag: "deepseek-r1:8b", Label: "DeepSeek-R1 8B", SizeGB: 5.2, ParamsB: 8, CtxK: 128, Caps: []string{"tools", "thinking"}, Roles: []string{"reasoning"}, Blurb: "Shows its working before answering; the R1 size for 8 GB GPUs."},
	{Tag: "deepseek-r1:14b", Label: "DeepSeek-R1 14B", SizeGB: 9.0, ParamsB: 14, CtxK: 128, Caps: []string{"tools", "thinking"}, Roles: []string{"reasoning"}, Blurb: "Mid-size thinking model for maths, logic and planning on a 16 GB GPU."},
	{Tag: "gpt-oss:20b", Label: "gpt-oss 20B", SizeGB: 14, ParamsB: 21, ActiveB: 3.6, CtxK: 128, KVKB: 48, Caps: []string{"tools", "thinking"}, Roles: []string{"reasoning", "general"}, Blurb: "Fast reasoning model (mixture of experts). Runs in 16 GB."},
	{Tag: "magistral:24b", Label: "Magistral 24B", SizeGB: 14, ParamsB: 24, CtxK: 39, Caps: []string{"tools", "thinking"}, Roles: []string{"reasoning"}, Blurb: "Mistral's traceable reasoning model; keep prompts under ~40K tokens."},
	{Tag: "deepseek-r1:32b", Label: "DeepSeek-R1 32B", SizeGB: 20, ParamsB: 32, CtxK: 128, Caps: []string{"tools", "thinking"}, Roles: []string{"reasoning"}, Blurb: "Strong step-by-step reasoner for 24 GB GPUs or 32 GB+ Macs."},

	// ---- general, mid to big ----
	{Tag: "gemma4:26b", Label: "Gemma 4 26B", SizeGB: 18, ParamsB: 26, ActiveB: 4, CtxK: 256, Caps: []string{"tools", "thinking", "vision", "audio"}, Roles: []string{"general", "vision", "audio"}, Blurb: "Mixture of experts with vision and audio. Quick for its size."},
	{Tag: "qwen3.6:27b", Label: "Qwen 3.6 27B", SizeGB: 18, ParamsB: 27, CtxK: 256, Caps: []string{"tools", "thinking", "vision"}, Roles: []string{"general", "coding", "reasoning"}, Blurb: "Dense and careful: agentic coding and long reasoning."},
	{Tag: "qwen3.8:27b", Label: "Qwen 3.8 27B", SizeGB: 18, ParamsB: 27, CtxK: 256, Caps: []string{"tools", "thinking", "vision"}, Roles: []string{"general", "coding", "reasoning", "planner"}, Blurb: "Newest Qwen generation: one 27B for coding, research, long agent runs, images and long video."},
	{Tag: "nemotron3:33b", Label: "Nemotron 3 Omni 33B", SizeGB: 21, ParamsB: 33, CtxK: 128, Caps: []string{"tools", "thinking", "vision", "audio"}, Roles: []string{"vision", "audio", "general"}, Blurb: "NVIDIA model that understands video, speech, images and text, transcription included."},
	{Tag: "qwen3.6:35b", Label: "Qwen 3.6 35B", SizeGB: 24, ParamsB: 35, ActiveB: 3, CtxK: 256, Caps: []string{"tools", "thinking", "vision"}, Roles: []string{"general", "coding"}, Blurb: "Mixture-of-experts sibling of the 27B: faster, similar quality."},
	{Tag: "nemotron-3.5-bolt:74b-a9b", Label: "Nemotron 3.5 Bolt 74B-A9B", SizeGB: 25, ParamsB: 74, ActiveB: 9, CtxK: 256, Caps: []string{"tools", "thinking", "vision"}, Roles: []string{"general", "vision", "planner"}, NoMac: true, Blurb: "Fast 74B mixture of experts with vision in 25 GB — Nvidia/AMD only, no Metal build."},
	{Tag: "llama3.3:70b", Label: "Llama 3.3 70B", SizeGB: 43, ParamsB: 70.6, CtxK: 128, KVKB: 320, Caps: []string{"tools"}, Roles: []string{"planner"}, Blurb: "Big dense generalist. Slower; good writer and planner."},
	{Tag: "qwen3-next:80b", Label: "Qwen3-Next 80B-A3B", SizeGB: 50, ParamsB: 80, ActiveB: 3, CtxK: 256, Caps: []string{"tools", "thinking"}, Roles: []string{"general", "planner"}, Blurb: "80B of knowledge at 3B-per-token speed; a flagship for a 64–96 GB machine."},
	{Tag: "gpt-oss:120b", Label: "gpt-oss 120B", SizeGB: 65, ParamsB: 117, ActiveB: 5.1, CtxK: 128, KVKB: 72, Caps: []string{"tools", "thinking"}, Roles: []string{"planner", "reasoning"}, Blurb: "The network's brain: plans long tasks and reviews work. Needs ~96 GB."},
	{Tag: "nemotron-3.5-super:120b", Label: "Nemotron 3.5 Super 120B-A12B", SizeGB: 80, ParamsB: 120, ActiveB: 12, CtxK: 1024, Caps: []string{"tools", "thinking", "vision"}, Roles: []string{"planner", "reasoning", "vision"}, Blurb: "NVIDIA's 1M-context vision model for a 96 GB machine."},
	{Tag: "qwen3.5:122b", Label: "Qwen 3.5 122B", SizeGB: 81, ParamsB: 122, ActiveB: 10, CtxK: 256, Caps: []string{"tools", "thinking", "vision"}, Roles: []string{"planner"}, Blurb: "Largest option here, with vision. Needs 128 GB."},

	// ---- embeddings ----
	{Tag: "nomic-embed-text", Label: "Nomic Embed", SizeGB: 0.27, ParamsB: 0.14, CtxK: 8, Caps: []string{"embedding"}, Roles: []string{"embeddings"}, Blurb: "Tiny embedding model for searching the library."},
	{Tag: "embeddinggemma", Label: "EmbeddingGemma", SizeGB: 0.62, ParamsB: 0.3, CtxK: 2, Caps: []string{"embedding"}, Roles: []string{"embeddings"}, Blurb: "Google's small multilingual embedding model."},
	{Tag: "qwen3-embedding:0.6b", Label: "Qwen3 Embedding 0.6B", SizeGB: 0.64, ParamsB: 0.6, CtxK: 32, Caps: []string{"embedding"}, Roles: []string{"embeddings"}, Blurb: "Small modern text and code embedder with a 32K window."},
	{Tag: "bge-m3:567m", Label: "BGE-M3", SizeGB: 1.2, ParamsB: 0.567, CtxK: 8, Caps: []string{"embedding"}, Roles: []string{"embeddings"}, Blurb: "Multilingual embeddings (100+ languages) with an 8K window; good for long documents."},

	// ---- media (Ollama's own; Mac only so far — for Nvidia use a Head, see ../heads/) ----
	{Tag: "x/z-image-turbo", Label: "Z-Image Turbo", SizeGB: 13, ParamsB: 6, Caps: []string{"image"}, Roles: []string{"images"}, MacOnly: true, Blurb: "Makes images from text. Experimental, Mac only for now."},
	{Tag: "x/flux2-klein:4b", Label: "FLUX.2 Klein 4B", SizeGB: 5.7, ParamsB: 4, Caps: []string{"image"}, Roles: []string{"images"}, MacOnly: true, Blurb: "Fast image generator with readable in-image text (Apache-2.0). Mac only for now; wants ~13 GB."},
	{Tag: "phonon", Label: "Phonon TTS", SizeGB: 0.104, ParamsB: 0.031, CtxK: 8, Caps: []string{"audio"}, Roles: []string{"audio"}, MacOnly: true, Blurb: "Reads text aloud (English) through Ollama's speech API. Apple Silicon only, Ollama 0.40.9+."},
}

var roleOrder = []string{"planner", "general", "coding", "reasoning", "vision", "audio", "fast", "embeddings", "images"}

var roleNames = map[string]string{
	"planner": "Planner (biggest brain)", "general": "General", "coding": "Coding", "reasoning": "Reasoning",
	"vision": "Vision", "audio": "Audio", "fast": "Fast and small", "embeddings": "Embeddings", "images": "Image generation",
}

// catalogFor rates every catalog model for this computer and marks the best pick per role.
func (a *App) catalogFor() ([]CatalogItem, map[string]string) {
	sys := a.sysInfo()
	usable, _ := usableMemory(sys)
	bw := memoryBandwidth(sys)
	cfg := a.config()
	installed := map[string]ModelInfo{}
	for _, m := range a.annotate(a.ollama.State().Models) {
		installed[normModel(m.Name)] = m
	}
	// Who in the network has what (and whether versions match).
	netHas := map[string][]string{}
	netDigests := map[string]map[string]bool{}
	_, _, _, snap := a.node.view(true)
	if snap != nil {
		for _, d := range snap.Devices {
			for _, m := range d.Models {
				k := normModel(m.Name)
				netHas[k] = append(netHas[k], d.Name)
				if netDigests[k] == nil {
					netDigests[k] = map[string]bool{}
				}
				if m.Digest != "" {
					netDigests[k][m.Digest] = true
				}
			}
		}
	}
	out := make([]CatalogItem, len(catalog))
	for i, c := range catalog {
		kv := c.KVKB * 1024
		if kv <= 0 {
			kv = kvGuessBytes(c.ParamsB)
		}
		need8k := c.SizeGB + overheadGB(c.SizeGB) + kv*8192/1e9
		c.NeedGB = round1(need8k)
		switch {
		case c.MacOnly && runtime.GOOS != "darwin", c.NoMac && runtime.GOOS == "darwin":
			c.Fit = "unsupported"
		case usable <= 0:
			c.Fit = "unknown"
		case need8k <= usable*comfortShare:
			c.Fit = "comfortable"
		case need8k <= usable*maxShare:
			c.Fit = "tight"
		default:
			c.Fit = "too_big"
		}
		k := normModel(c.Tag)
		inst, have := installed[k]
		c.Installed = have
		active := 1.0
		if c.ActiveB > 0 && c.ParamsB > 0 {
			active = c.ActiveB / c.ParamsB
		}
		if !contains(c.Caps, "embedding") && !contains(c.Caps, "image") {
			c.EstTokS = estTokS(c.SizeGB, active, bw)
		}
		if have && inst.Fits != "" && c.Fit != "unsupported" { // measured beats guessed
			c.Fit, c.NeedGB = inst.Fits, inst.NeedGB
			if s := inst.Speed(); s > 0 {
				c.EstTokS = s
			}
		}
		c.OverLimit = cfg.MaxModelGB > 0 && c.SizeGB > cfg.MaxModelGB
		c.NetDevices = netHas[k]
		if c.NetDevices == nil {
			c.NetDevices = []string{}
		}
		c.NetMixed = len(netDigests[k]) > 1
		out[i] = c
	}
	// Best pick per role: the biggest model that fits comfortably (smallest for "fast").
	best := map[string]string{}
	for _, role := range roleOrder {
		idx := -1
		for i, c := range out {
			if !contains(c.Roles, role) || c.Fit != "comfortable" {
				continue
			}
			if idx < 0 {
				idx = i
				continue
			}
			if role == "fast" {
				if c.ParamsB < out[idx].ParamsB {
					idx = i
				}
			} else if c.ParamsB > out[idx].ParamsB {
				idx = i
			}
		}
		if idx >= 0 {
			out[idx].Best = true
			best[role] = out[idx].Tag
		}
	}
	return out, best
}

// kvGuessBytes is a rough KV cache size per token of context for a model
// whose architecture we don't know: about 128 KB for an 8B model, growing
// slower than the parameter count (bigger models mostly add width, and
// grouped-query attention keeps the cache small).
func kvGuessBytes(paramsB float64) float64 {
	if paramsB <= 0 {
		paramsB = 8
	}
	return 131072 * math.Pow(paramsB/8, 0.45)
}

func clampF(v, lo, hi float64) float64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

func catalogItem(tag string) (CatalogItem, bool) {
	for _, c := range catalog {
		if normModel(c.Tag) == normModel(tag) {
			return c, true
		}
	}
	return CatalogItem{}, false
}

// rolesSorted returns roles in display order with friendly names.
func rolesSorted(best map[string]string) []map[string]string {
	var out []map[string]string
	for _, r := range roleOrder {
		out = append(out, map[string]string{"role": r, "name": roleNames[r], "tag": best[r]})
	}
	sort.SliceStable(out, func(i, j int) bool { return false })
	return out
}

func lowerAll(ss []string) []string {
	out := make([]string, len(ss))
	for i, s := range ss {
		out[i] = strings.ToLower(s)
	}
	return out
}
