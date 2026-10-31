// fleet-probe is probe (d) of the worker base-model rule (docs/hydra-worker-plan.md, docs/probe-d-steps.md): does the
// worker's Q5_K_M fit a computer's GPU, and how fast does it run there?
//
//	fleet-probe --gguf rt2-q5_k_m.gguf        import that GGUF and measure it
//	fleet-probe --model qwen3:14b             measure a model that's already in Ollama
//
// One file with nothing to install, for the 3080 Ti PC and the M4 Pro. It imports the GGUF as Chimera's Get from host
// will (/api/blobs, then /api/create with the worker's renderer and parser), which also tries that path on Windows.
// Then, on the local Ollama, with nothing else loaded: for num_ctx 8192, 16384 and 32768 it loads the model and
// reads /api/ps while it's loaded (the rule's bar: size_vram equal to size, 100% on the GPU), then measures speed
// with the same streamed request Chimera sends. The requests are in requests.json (EVAL ONLY: two of the eval's
// worker requests, with the token counts the training template gives them); replies are read and thrown away.
//
// It prints a verdict per bar and writes fleet-probe-<computer>.json next to where it's run, including when a
// measurement fails or the run stops partway: what was measured is always kept. On NVIDIA it waits for video memory to
// come back between loads, because a reload that reads stale free memory spills to the CPU and would look like a real
// misfit, and a Fit that fails is measured once more before it counts. Stdlib only.
package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"sync/atomic"
	"time"
)

const (
	workerRenderer  = "gemma4-large"
	workerParser    = "gemma4-no-thinking"
	importTag       = "wm-probe-fleet:q5"
	keepAlive       = "15m" // Chimera's
	speedTokens     = 300
	stepTokens      = 1500
	minSpeedTokens  = 200      // a shorter reply says little about speed
	referenceOllama = "0.40.1" // what the Studio's probes ran on
)

// Set by build.sh, so a cut-off copy of the GGUF is caught before it goes near Ollama.
var wantDigest, wantSize string

var contexts = []int{8192, 16384, 32768}

//go:embed requests.json
var requestsJSON []byte

type message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type request struct {
	ID           string    `json:"id"`
	Messages     []message `json:"messages"`
	PromptTokens int       `json:"prompt_tokens"`
}

type requests struct {
	Short request `json:"short"`
	Long  request `json:"long"`
}

// chatResult is one streamed reply's numbers. The reply's text isn't kept.
type chatResult struct {
	PromptTokens int     `json:"prompt_tokens"`
	Tokens       int     `json:"tokens"`
	TokS         float64 `json:"tok_s"`
	PromptS      float64 `json:"prompt_s"`
	LoadS        float64 `json:"load_s"`
	WallS        float64 `json:"wall_s"`
	DoneReason   string  `json:"done_reason"`
	ThinkingText bool    `json:"thinking_text"`
	Markers      bool    `json:"markers"`
	EmptyReply   bool    `json:"empty_reply"`
}

type fit struct {
	NumCtx    int        `json:"num_ctx"`
	CtxLen    int        `json:"context_length"` // what Ollama says it loaded
	Runner    string     `json:"runner,omitempty"`
	SizeGB    float64    `json:"size_gb"`
	VRAMGB    float64    `json:"vram_gb"`
	GPUPct    float64    `json:"gpu_pct"`
	GPUUsedMB int        `json:"gpu_used_mb,omitempty"` // nvidia-smi while loaded
	Speed     chatResult `json:"speed"`
	Failure   string     `json:"failure,omitempty"`
	Others    string     `json:"other_models,omitempty"` // loaded at the same time, so the reading doesn't count
	First     *fit       `json:"first_try,omitempty"`    // the failing reading, when it was measured again
}

func (f fit) ok() bool {
	return f.Failure == "" && f.Others == "" && f.SizeGB > 0 && f.VRAMGB >= f.SizeGB && f.CtxLen == f.NumCtx
}

type report struct {
	Computer      string     `json:"computer"`
	OS            string     `json:"os"`
	Hardware      string     `json:"hardware"`
	OllamaVersion string     `json:"ollama_version"`
	Model         string     `json:"model"`
	Imported      bool       `json:"imported"`
	Digest        string     `json:"digest,omitempty"`
	ImportSeconds float64    `json:"import_seconds,omitempty"`
	Thinking      any        `json:"thinking,omitempty"`
	Renderer      string     `json:"renderer,omitempty"`
	Parser        string     `json:"parser,omitempty"`
	GPUUsedBefore int        `json:"gpu_used_before_mb,omitempty"`
	Fits          []fit      `json:"fits"`
	Step          chatResult `json:"step_8k"`
	StepFailure   string     `json:"step_failure,omitempty"`
	StepGPUPct    float64    `json:"step_gpu_pct"`
	Step1500S     float64    `json:"step_1500_seconds"`
	StepColdS     float64    `json:"step_1500_seconds_with_load"`
	Long          chatResult `json:"long_prompt_16k"`
	LongFailure   string     `json:"long_failure,omitempty"`
	LongGPUPct    float64    `json:"long_gpu_pct"`
	Verdicts      []verdict  `json:"verdicts"`
	Stopped       string     `json:"stopped,omitempty"` // why the run ended early
	Finished      string     `json:"finished"`
}

type verdict struct {
	Name string `json:"name"`
	Bar  string `json:"bar"`
	Got  string `json:"got"`
	OK   bool   `json:"ok"`
	Note string `json:"note,omitempty"`
}

type client struct {
	base string
	http *http.Client
	// How long a reply may go silent: a model that's loading can take Ollama's five minutes to fail, and a step
	// that stalls never ends by itself. A stall becomes a recorded failure.
	firstLine, nextLine, stallUpload time.Duration
}

func newClient(base string) *client {
	return &client{base: strings.TrimRight(base, "/"), http: &http.Client{}, firstLine: 6 * time.Minute,
		nextLine: 2 * time.Minute, stallUpload: 2 * time.Minute}
}

func (c *client) url(p string) string { return c.base + p }

// post sends JSON and decodes the reply. Ollama's error text comes back as the error.
func (c *client) post(ctx context.Context, path string, in, out any) error {
	b, _ := json.Marshal(in)
	req, err := http.NewRequestWithContext(ctx, "POST", c.url(path), bytes.NewReader(b))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		return fmt.Errorf("%s: HTTP %d: %s", path, resp.StatusCode, trimError(body))
	}
	if out == nil {
		return nil
	}
	return json.Unmarshal(body, out)
}

func trimError(b []byte) string {
	var e struct {
		Error string `json:"error"`
	}
	if json.Unmarshal(b, &e) == nil && e.Error != "" {
		return e.Error
	}
	s := strings.TrimSpace(string(b))
	if len(s) > 200 {
		s = s[:200]
	}
	return s
}

func (c *client) version(ctx context.Context) (string, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", c.url("/api/version"), nil)
	if err != nil {
		return "", err
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	var v struct {
		Version string `json:"version"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&v); err != nil {
		return "", err
	}
	return v.Version, nil
}

type loaded struct {
	Name     string `json:"name"`
	Size     int64  `json:"size"`
	SizeVRAM int64  `json:"size_vram"`
	CtxLen   int    `json:"context_length"`
	Details  struct {
		Runner string `json:"runner"`
	} `json:"details"`
}

// same says whether a name from /api/ps is the model asked for ("foo" is "foo:latest").
func same(name, model string) bool { return name == model || name == model+":latest" }

func (c *client) ps(ctx context.Context) ([]loaded, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", c.url("/api/ps"), nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var v struct {
		Models []loaded `json:"models"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&v); err != nil {
		return nil, err
	}
	return v.Models, nil
}

// fileDigest is the file's sha256 in Ollama's form.
func fileDigest(path string) (string, int64, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", 0, err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return "", 0, err
	}
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", 0, err
	}
	return "sha256:" + hex.EncodeToString(h.Sum(nil)), st.Size(), nil
}

// counter counts what the transport has read, for the progress line.
type counter struct {
	r io.Reader
	n atomic.Int64
}

func (c *counter) Read(p []byte) (int, error) {
	n, err := c.r.Read(p)
	c.n.Add(int64(n))
	return n, err
}

// upload puts the GGUF in Ollama's blob store unless it's there already, as Chimera's Get from host does.
func (c *client) upload(ctx context.Context, path, digest string, size int64) error {
	head, err := http.NewRequestWithContext(ctx, "HEAD", c.url("/api/blobs/"+digest), nil)
	if err != nil {
		return err
	}
	if resp, err := c.http.Do(head); err == nil {
		resp.Body.Close()
		if resp.StatusCode == http.StatusOK {
			fmt.Println("  already in Ollama's blob store")
			return nil
		}
	}
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	ctx, cancel := context.WithCancelCause(ctx)
	defer cancel(nil)
	cr := &counter{r: f}
	req, err := http.NewRequestWithContext(ctx, "POST", c.url("/api/blobs/"+digest), cr)
	if err != nil {
		return err
	}
	req.ContentLength = size
	done := make(chan struct{})
	go func() {
		tick := time.NewTicker(time.Second)
		defer tick.Stop()
		seen, moved, said := int64(0), time.Now(), time.Now()
		for {
			select {
			case <-done:
				return
			case <-tick.C:
				n := cr.n.Load()
				if n != seen {
					seen, moved = n, time.Now()
				}
				if n < size && time.Since(moved) > c.stallUpload { // once it's all sent, Ollama checks it: that's slow, not stuck
					cancel(fmt.Errorf("the copy stalled at %.1f GB", float64(n)/1e9))
					return
				}
				if time.Since(said) >= 10*time.Second {
					said = time.Now()
					fmt.Printf("  %.1f of %.1f GB\n", float64(n)/1e9, float64(size)/1e9)
				}
			}
		}
	}()
	resp, err := c.http.Do(req)
	close(done)
	if err != nil {
		if cause := context.Cause(ctx); cause != nil {
			return cause
		}
		return err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		return fmt.Errorf("/api/blobs: HTTP %d: %s", resp.StatusCode, trimError(body))
	}
	return nil
}

func (c *client) create(ctx context.Context, tag, digest string) error {
	return c.post(ctx, "/api/create", map[string]any{
		"model": tag, "files": map[string]string{"model.gguf": digest},
		"renderer": workerRenderer, "parser": workerParser, "stream": false,
	}, nil)
}

var modelfileLine = regexp.MustCompile(`(?m)^(RENDERER|PARSER) (\S+)\s*$`)

// show gets the renderer and parser (only in the Modelfile text on 0.40.1) and the thinking setting.
func (c *client) show(ctx context.Context, model string) (renderer, parser string, thinking any, err error) {
	var s struct {
		Modelfile string `json:"modelfile"`
		Thinking  any    `json:"thinking"`
	}
	if err = c.post(ctx, "/api/show", map[string]any{"model": model}, &s); err != nil {
		return
	}
	for _, m := range modelfileLine.FindAllStringSubmatch(s.Modelfile, -1) {
		if m[1] == "RENDERER" {
			renderer = m[2]
		} else {
			parser = m[2]
		}
	}
	return renderer, parser, s.Thinking, nil
}

// unload frees the model and waits until its memory is back. Only this model is waited for: another one that has
// loaded meanwhile is reported at the next reading, by name.
func (c *client) unload(ctx context.Context, model string, usedBefore int) error {
	if err := c.post(ctx, "/api/generate", map[string]any{"model": model, "keep_alive": 0, "stream": false}, nil); err != nil {
		return err
	}
	for i := 0; ; i++ { // Ollama unloads in the background
		ms, err := c.ps(ctx)
		if err != nil {
			return err
		}
		gone := true
		for _, m := range ms {
			gone = gone && !same(m.Name, model)
		}
		if gone {
			break
		}
		if i == 120 {
			return errors.New("the model didn't unload within a minute")
		}
		time.Sleep(500 * time.Millisecond)
	}
	settleGPU(ctx, usedBefore)
	return nil
}

// settleGPU waits for video memory to come back after a model leaves /api/ps. Ollama lists it as gone before the card
// has it free, and a load in that gap reads less free memory than there is, puts layers on the CPU and looks like a
// real misfit. Macs share memory and need no wait.
func settleGPU(ctx context.Context, usedBefore int) {
	if runtime.GOOS == "darwin" {
		return
	}
	if usedBefore < 0 { // no nvidia-smi to ask
		sleep(ctx, 6*time.Second)
		return
	}
	for i := 0; i < 15; i++ {
		if used := gpuUsedMB(); used >= 0 && used <= usedBefore+300 {
			return
		}
		sleep(ctx, time.Second)
	}
}

func sleep(ctx context.Context, d time.Duration) {
	select {
	case <-ctx.Done():
	case <-time.After(d):
	}
}

// gpuUsedMB is the NVIDIA card's used memory, -1 with no nvidia-smi.
func gpuUsedMB() int {
	s := runTool(20*time.Second, "nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits")
	n, err := strconv.Atoi(strings.TrimSpace(strings.SplitN(s, "\n", 2)[0]))
	if err != nil {
		return -1
	}
	return n
}

func runTool(limit time.Duration, name string, args ...string) string {
	ctx, cancel := context.WithTimeout(context.Background(), limit)
	defer cancel()
	out, err := exec.CommandContext(ctx, name, args...).Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

var markers = []string{"<|channel>", "<channel|>", "<|think|>", "<turn|>", "<|turn>"}

// chat is Chimera's streamed worker request (ollama.go ChatStreamKeep: no think field, no temperature), with a limit.
func (c *client) chat(parent context.Context, model string, msgs []message, numCtx, predict int) (chatResult, error) {
	var r chatResult
	ctx, cancel := context.WithCancelCause(parent)
	defer cancel(nil)
	var last atomic.Int64
	var lines atomic.Int64
	last.Store(time.Now().UnixNano())
	done := make(chan struct{})
	defer close(done)
	go func() { // a reply that goes silent is a failure, and a long wait says it's still going
		tick := time.NewTicker(time.Second)
		defer tick.Stop()
		start, said := time.Now(), time.Now()
		for {
			select {
			case <-done:
				return
			case <-tick.C:
				limit := c.nextLine
				if lines.Load() == 0 {
					limit = c.firstLine
				}
				if idle := time.Since(time.Unix(0, last.Load())); idle > limit {
					cancel(fmt.Errorf("no reply for %.0f s", idle.Seconds()))
					return
				}
				if time.Since(said) >= 30*time.Second {
					said = time.Now()
					fmt.Printf("  still working (%.0f s)\n", time.Since(start).Seconds())
				}
			}
		}
	}()
	b, _ := json.Marshal(map[string]any{"model": model, "messages": msgs, "stream": true, "keep_alive": keepAlive,
		"options": map[string]any{"num_ctx": numCtx, "num_predict": predict}})
	req, err := http.NewRequestWithContext(ctx, "POST", c.url("/api/chat"), bytes.NewReader(b))
	if err != nil {
		return r, err
	}
	req.Header.Set("Content-Type", "application/json")
	start := time.Now()
	resp, err := c.http.Do(req)
	if err != nil {
		if cause := context.Cause(ctx); cause != nil {
			return r, cause
		}
		return r, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		body, _ := io.ReadAll(resp.Body)
		return r, fmt.Errorf("/api/chat: HTTP %d: %s", resp.StatusCode, trimError(body))
	}
	sc := bufio.NewScanner(resp.Body)
	sc.Buffer(make([]byte, 0, 1<<20), 1<<26)
	var text strings.Builder
	sawDone := false
	for sc.Scan() {
		lines.Add(1)
		last.Store(time.Now().UnixNano())
		var ch struct {
			Message struct {
				Content  string `json:"content"`
				Thinking string `json:"thinking"`
			} `json:"message"`
			Done               bool   `json:"done"`
			DoneReason         string `json:"done_reason"`
			Error              string `json:"error"`
			PromptEvalCount    int    `json:"prompt_eval_count"`
			PromptEvalDuration int64  `json:"prompt_eval_duration"`
			EvalCount          int    `json:"eval_count"`
			EvalDuration       int64  `json:"eval_duration"`
			LoadDuration       int64  `json:"load_duration"`
		}
		if err := json.Unmarshal(sc.Bytes(), &ch); err != nil {
			return r, fmt.Errorf("/api/chat: bad line: %w", err)
		}
		if ch.Error != "" {
			return r, errors.New(ch.Error)
		}
		text.WriteString(ch.Message.Content)
		if ch.Message.Thinking != "" {
			r.ThinkingText = true
		}
		if ch.Done {
			sawDone = true
			r.PromptTokens, r.Tokens, r.DoneReason = ch.PromptEvalCount, ch.EvalCount, ch.DoneReason
			r.PromptS = float64(ch.PromptEvalDuration) / 1e9
			r.LoadS = float64(ch.LoadDuration) / 1e9
			if ch.EvalDuration > 0 {
				r.TokS = float64(ch.EvalCount) / (float64(ch.EvalDuration) / 1e9)
			}
		}
	}
	if err := sc.Err(); err != nil {
		if cause := context.Cause(ctx); cause != nil {
			return r, cause
		}
		return r, err
	}
	if !sawDone {
		return r, errors.New("/api/chat: the stream ended with no final line")
	}
	r.WallS = time.Since(start).Seconds()
	s := text.String()
	r.EmptyReply = strings.TrimSpace(s) == ""
	for _, m := range markers {
		if strings.Contains(s, m) {
			r.Markers = true
		}
	}
	return r, nil
}

func gb(n int64) float64 { return float64(n) / 1e9 }

// hardware says what the computer is, best effort.
func hardware() string {
	var parts []string
	if s := runTool(20*time.Second, "nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader"); s != "" {
		parts = append(parts, s)
	}
	if runtime.GOOS == "darwin" {
		if s := runTool(5*time.Second, "sysctl", "-n", "machdep.cpu.brand_string"); s != "" {
			parts = append(parts, s)
		}
		if s := runTool(5*time.Second, "sysctl", "-n", "hw.memsize"); s != "" {
			var n int64
			fmt.Sscan(s, &n)
			parts = append(parts, fmt.Sprintf("%.0f GB", float64(n)/(1<<30)))
		}
	}
	return strings.Join(parts, ", ")
}

// bars gives the verdicts. The rule's bar is 100% on the GPU at all three sizes, at the context asked for; the fleet
// numbers are the plan's shipping bar (3080 Ti: 25 tok/s and a 1,500-token step in 75 s; M4 Pro: 15 tok/s), which depend
// on which computer. Anything not measured is a failed line, not a missing one.
func bars(r *report, goos string, want requests, importedHere bool) []verdict {
	var v []verdict
	for _, n := range contexts {
		name := fmt.Sprintf("Fit at %dK", n/1024)
		var f *fit
		for i := range r.Fits {
			if r.Fits[i].NumCtx == n {
				f = &r.Fits[i]
			}
		}
		if f == nil {
			v = append(v, verdict{Name: name, Bar: "100% on the GPU", Got: "not measured"})
			continue
		}
		got := fmt.Sprintf("%.1f%% (%.1f of %.1f GB)", f.GPUPct, f.VRAMGB, f.SizeGB)
		note := ""
		switch {
		case f.Failure != "":
			got = f.Failure
		case f.Others != "":
			got = "not valid: " + f.Others + " was loaded too"
		case f.SizeGB > 0 && f.VRAMGB == 0:
			note = "Ollama isn't using the GPU at all: that's a setup problem, not a fit result"
		case f.CtxLen != f.NumCtx:
			got += fmt.Sprintf(", but Ollama loaded %d context", f.CtxLen)
		}
		if f.First != nil {
			note = strings.TrimSpace(note + " Measured twice; both are in the report.")
		}
		v = append(v, verdict{Name: name, Bar: "100% on the GPU", Got: got, OK: f.ok(), Note: note})
	}
	if importedHere {
		off := thinkingOff(r.Thinking)
		got := r.Renderer + " and " + r.Parser
		if !off {
			got += ", but thinking isn't off"
		}
		v = append(v, verdict{Name: "Worker setup", Bar: workerRenderer + " and " + workerParser + ", thinking off", Got: got,
			OK: r.Renderer == workerRenderer && r.Parser == workerParser && off})
		clean, seen := true, 0
		for _, c := range measured(r) {
			seen++
			if c.ThinkingText || c.Markers || c.EmptyReply {
				clean = false
			}
		}
		v = append(v, verdict{Name: "Replies", Bar: "text, no thinking, no markers", Got: yesNo(clean && seen > 0), OK: clean && seen > 0})
		v = append(v, tokensLine("Short prompt tokens", want.Short.PromptTokens, r.Step.PromptTokens, r.StepFailure))
		v = append(v, tokensLine("Long prompt tokens", want.Long.PromptTokens, r.Long.PromptTokens, r.LongFailure))
	}
	bar, name := 25.0, "Speed (3080 Ti)"
	if goos == "darwin" {
		bar, name = 15.0, "Speed (M4 Pro)"
	}
	const shipping = "the plan's shipping bar, measured on the untrained model"
	got, note := fmt.Sprintf("%.1f tok/s", r.Step.TokS), shipping
	if r.StepFailure != "" {
		got = "not measured: " + r.StepFailure
	} else if r.Step.Tokens < minSpeedTokens {
		got, note = fmt.Sprintf("%.1f tok/s over only %d tokens", r.Step.TokS, r.Step.Tokens), shipping+"; too short a reply to count"
	}
	if r.StepFailure == "" && r.StepGPUPct > 0 && r.StepGPUPct < 100 {
		note += fmt.Sprintf("; only %.1f%% was on the GPU", r.StepGPUPct)
	}
	v = append(v, verdict{Name: name, Bar: fmt.Sprintf("%.0f tok/s or more", bar), Got: got, Note: note,
		OK: r.StepFailure == "" && r.Step.TokS >= bar && r.Step.Tokens >= minSpeedTokens})
	if goos != "darwin" {
		v = append(v, verdict{Name: "1,500-token step (3080 Ti)", Bar: "75 s or less", Got: fmt.Sprintf("%.0f s", r.Step1500S),
			OK:   r.StepFailure == "" && r.Step1500S > 0 && r.Step1500S <= 75,
			Note: fmt.Sprintf("prompt time plus 1,500 tokens at the measured speed; %.0f s with the model loading first", r.StepColdS)})
	}
	if len(r.Fits) > 0 && r.Fits[0].Failure == "" && r.Fits[0].Speed.TokS > 0 {
		steady, worst := true, ""
		for _, f := range r.Fits[1:] {
			if f.Failure == "" && f.Speed.TokS < 0.8*r.Fits[0].Speed.TokS {
				steady, worst = false, fmt.Sprintf("%.1f tok/s at %dK against %.1f at 8K", f.Speed.TokS, f.NumCtx/1024, r.Fits[0].Speed.TokS)
			}
		}
		if worst == "" {
			worst = "yes"
		}
		v = append(v, verdict{Name: "Speed at larger contexts", Bar: "within 20% of 8K", Got: worst, OK: steady,
			Note: "a slowdown here can mean paging that size_vram doesn't show"})
	}
	return v
}

func tokensLine(name string, want, got int, failure string) verdict {
	if failure != "" {
		return verdict{Name: name, Bar: fmt.Sprint(want), Got: "not measured: " + failure}
	}
	return verdict{Name: name, Bar: fmt.Sprint(want), Got: fmt.Sprint(got), OK: got == want}
}

// thinkingOff reads /api/show's thinking setting: {"values":[false],"default":false} on the worker.
func thinkingOff(t any) bool {
	m, ok := t.(map[string]any)
	if !ok {
		return false
	}
	d, ok := m["default"].(bool)
	return ok && !d
}

// measured is every reply that came back.
func measured(r *report) []chatResult {
	out := speeds(r)
	if r.StepFailure == "" && r.Step.Tokens > 0 {
		out = append(out, r.Step)
	}
	if r.LongFailure == "" && r.Long.Tokens > 0 {
		out = append(out, r.Long)
	}
	return out
}

func speeds(r *report) []chatResult {
	var out []chatResult
	for _, f := range r.Fits {
		if f.Failure == "" {
			out = append(out, f.Speed)
		}
	}
	return out
}

func yesNo(ok bool) string {
	if ok {
		return "yes"
	}
	return "no"
}

func stop(format string, a ...any) {
	fmt.Fprintf(os.Stderr, "\nSTOPPED: "+format+"\n", a...)
	os.Exit(1)
}

// results is what the run prints at the end.
func results(r *report) string {
	var b strings.Builder
	fmt.Fprintf(&b, "\nResults for %s\n", r.Computer)
	for _, v := range r.Verdicts {
		word := "PASS"
		if !v.OK {
			word = "FAIL"
		}
		fmt.Fprintf(&b, "  %s  %s: %s (bar: %s)\n", word, v.Name, v.Got, v.Bar)
		if v.Note != "" {
			fmt.Fprintf(&b, "        %s\n", v.Note)
		}
	}
	if r.Stopped != "" {
		fmt.Fprintf(&b, "\nSTOPPED early: %s\n", r.Stopped)
	}
	return b.String()
}

// finish prints the verdicts, then writes the report: a run that stopped early keeps what it measured, and a file that
// can't be written doesn't lose the verdicts.
func finish(r *report, want requests, path string) {
	r.Verdicts = bars(r, runtime.GOOS, want, r.Imported)
	r.Finished = time.Now().Format(time.RFC3339)
	fmt.Print(results(r))
	if path == "" {
		path = "fleet-probe-" + regexp.MustCompile(`[^A-Za-z0-9._-]+`).ReplaceAllString(r.Computer, "-") + ".json"
	}
	b, _ := json.MarshalIndent(r, "", " ")
	if err := os.WriteFile(path, b, 0o644); err != nil {
		fmt.Fprintf(os.Stderr, "\nCouldn't write %s (%v). Copy the results above.\n", path, err)
	} else {
		fmt.Printf("\nWrote %s. Copy the results above, or bring that file back to the Studio.\n", path)
	}
	if r.Stopped != "" {
		os.Exit(1)
	}
}

// measureFit loads the model at one context and reads /api/ps while it's loaded.
func measureFit(ctx context.Context, c *client, model string, msgs []message, n, usedBefore int) fit {
	f := fit{NumCtx: n}
	sp, err := c.chat(ctx, model, msgs, n, speedTokens)
	if err != nil {
		f.Failure = err.Error()
		return f
	}
	f.Speed = sp
	ms, err := c.ps(ctx)
	if err != nil {
		f.Failure = "/api/ps: " + err.Error()
		return f
	}
	var others []string
	for _, m := range ms {
		if !same(m.Name, model) {
			others = append(others, m.Name)
			continue
		}
		f.SizeGB, f.VRAMGB, f.CtxLen, f.Runner = gb(m.Size), gb(m.SizeVRAM), m.CtxLen, m.Details.Runner
		if m.Size > 0 {
			f.GPUPct = 100 * float64(m.SizeVRAM) / float64(m.Size)
		}
	}
	f.Others = strings.Join(others, ", ")
	if f.SizeGB == 0 {
		f.Failure = "the model wasn't in /api/ps after a reply"
	}
	if usedBefore >= 0 {
		if used := gpuUsedMB(); used >= 0 {
			f.GPUUsedMB = used
		}
	}
	return f
}

func gpuPct(ctx context.Context, c *client, model string) float64 {
	ms, err := c.ps(ctx)
	if err != nil {
		return 0
	}
	for _, m := range ms {
		if same(m.Name, model) && m.Size > 0 {
			return 100 * float64(m.SizeVRAM) / float64(m.Size)
		}
	}
	return 0
}

func main() {
	gguf := flag.String("gguf", "", "the worker GGUF to import and measure")
	model := flag.String("model", "", "measure this model, already in Ollama, instead")
	host := flag.String("host", "http://127.0.0.1:11434", "Ollama's address")
	out := flag.String("out", "", "the report file (default fleet-probe-<computer>.json)")
	flag.Parse()
	if (*gguf == "") == (*model == "") {
		stop("give --gguf FILE or --model NAME (not both)")
	}
	var want requests
	if err := json.Unmarshal(requestsJSON, &want); err != nil {
		stop("requests.json: %v", err)
	}
	ctx := context.Background()
	c := newClient(*host)
	name, _ := os.Hostname()
	r := report{Computer: name, OS: runtime.GOOS + "/" + runtime.GOARCH, Hardware: hardware()}
	var err error
	if r.OllamaVersion, err = c.version(ctx); err != nil {
		stop("Ollama isn't answering at %s (%v). Open Ollama and run this again.", *host, err)
	}
	fmt.Printf("%s, %s, %s; Ollama %s\n", r.Computer, r.OS, r.Hardware, r.OllamaVersion)
	if r.OllamaVersion != referenceOllama {
		fmt.Printf("Note: the Studio's probes ran on Ollama %s. Update this one first if you can.\n", referenceOllama)
	}
	ms, err := c.ps(ctx)
	if err != nil {
		stop("/api/ps: %v", err)
	}
	usedBefore := gpuUsedMB()
	if len(ms) == 1 && same(ms[0].Name, importTag) { // left by an interrupted run of this tool
		fmt.Println("Unloading the test model an earlier run left loaded")
		if err := c.unload(ctx, importTag, -1); err != nil {
			stop("unloading: %v", err)
		}
		usedBefore = gpuUsedMB()
	} else if len(ms) > 0 {
		var lines []string
		for _, m := range ms {
			lines = append(lines, "  ollama stop "+m.Name)
		}
		stop("Ollama has a model loaded, which would change the measurement. Disconnect in Chimera, run this, then run the tool again:\n%s",
			strings.Join(lines, "\n"))
	}
	r.GPUUsedBefore = usedBefore
	if usedBefore > 1000 {
		fmt.Printf("Note: something is already using %d MB of the GPU's memory. Close it if you can.\n", usedBefore)
	}
	r.Model = *model
	if *gguf != "" {
		r.Model, r.Imported = importTag, true
		fmt.Printf("Importing %s as Chimera's Get from host will\n", filepath.Base(*gguf))
		t := time.Now()
		if st, err := os.Stat(*gguf); err != nil {
			stop("can't read the GGUF: %v", err)
		} else if wantSize != "" && fmt.Sprint(st.Size()) != wantSize {
			stop("this copy of the file is %d bytes and should be %s: it was cut off, or it isn't the test model. Delete it and copy it again.", st.Size(), wantSize)
		}
		fmt.Println("  checking the file (a minute or two)")
		digest, size, err := fileDigest(*gguf)
		if err != nil {
			stop("can't read the GGUF: %v", err)
		}
		if wantDigest != "" && digest != wantDigest {
			stop("this copy of the file is damaged: its checksum is wrong. Delete it and copy it again.")
		}
		r.Digest = digest
		if err := c.upload(ctx, *gguf, digest, size); err != nil {
			stop("copying it into Ollama failed: %v", err)
		}
		if err := c.create(ctx, importTag, digest); err != nil {
			stop("/api/create failed: %v", err)
		}
		r.ImportSeconds = time.Since(t).Seconds()
		fmt.Printf("  done in %.0f s\n", r.ImportSeconds)
	}
	if r.Renderer, r.Parser, r.Thinking, err = c.show(ctx, r.Model); err != nil {
		stop("/api/show: %v", err)
	}
	for _, n := range contexts {
		fmt.Printf("Measuring at %dK context\n", n/1024)
		f := measureFit(ctx, c, r.Model, want.Short.Messages, n, usedBefore)
		if strings.Contains(f.Failure, "unknown renderer") {
			r.Fits = append(r.Fits, f)
			r.Stopped = fmt.Sprintf("this Ollama (%s) doesn't know the worker's renderer. Update Ollama and run this again.", r.OllamaVersion)
			finish(&r, want, *out)
			return
		}
		if !f.ok() { // a stale memory reading or a brief visitor shouldn't decide the base: once more, after a wait
			fmt.Printf("  didn't pass (%s); measuring again in 20 s\n", describe(f))
			if err := c.unload(ctx, r.Model, usedBefore); err != nil {
				fmt.Println("  couldn't unload:", err)
			}
			sleep(ctx, 20*time.Second)
			first := f
			f = measureFit(ctx, c, r.Model, want.Short.Messages, n, usedBefore)
			f.First = &first
		}
		fmt.Printf("  %s\n", describe(f))
		r.Fits = append(r.Fits, f)
		if err := c.unload(ctx, r.Model, usedBefore); err != nil {
			r.Stopped = "unloading: " + err.Error()
			finish(&r, want, *out)
			return
		}
	}
	fmt.Println("Measuring a whole step at 8K")
	if r.Step, err = c.chat(ctx, r.Model, want.Short.Messages, 8192, stepTokens); err != nil {
		r.StepFailure = err.Error()
		fmt.Println("  failed:", err)
	} else {
		r.StepGPUPct = gpuPct(ctx, c, r.Model)
		if r.Step.TokS > 0 {
			r.Step1500S = r.Step.PromptS + float64(stepTokens)/r.Step.TokS
			r.StepColdS = r.Step1500S + r.Step.LoadS
		}
	}
	if err := c.unload(ctx, r.Model, usedBefore); err != nil {
		r.Stopped = "unloading: " + err.Error()
		finish(&r, want, *out)
		return
	}
	fmt.Println("Measuring a long prompt at 16K")
	if r.Long, err = c.chat(ctx, r.Model, want.Long.Messages, 16384, 64); err != nil {
		r.LongFailure = err.Error()
		fmt.Println("  failed:", err)
	} else {
		r.LongGPUPct = gpuPct(ctx, c, r.Model)
	}
	if err := c.unload(ctx, r.Model, usedBefore); err != nil {
		r.Stopped = "unloading: " + err.Error()
	}
	finish(&r, want, *out)
}

// describe is one reading in a line.
func describe(f fit) string {
	switch {
	case f.Failure != "":
		return "failed: " + f.Failure
	case f.Others != "":
		return f.Others + " was loaded too"
	}
	s := fmt.Sprintf("%.1f of %.1f GB on the GPU (%.1f%%), context %d, %.1f tok/s", f.VRAMGB, f.SizeGB, f.GPUPct, f.CtxLen, f.Speed.TokS)
	if f.GPUUsedMB > 0 {
		s += fmt.Sprintf(", nvidia-smi says %d MB in use", f.GPUUsedMB)
	}
	return s
}
