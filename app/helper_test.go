package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestHelperModelNamesAndSizeGuard(t *testing.T) {
	for name, want := range map[string]bool{"hydra:1.0": true, "Hydra:1.0": true, "swn5n/hydra:1.0": true, "hydra": true,
		"hydra:1.1": true, "hydrate:7b": false, "qwen3:4b": false, "gpt-oss:120b": false} {
		if got := isHelperModel(name); got != want {
			t.Errorf("isHelperModel(%q) = %v, want %v", name, got, want)
		}
	}
	if helperFor(helperMaxCtx) != helperModel || helperFor(helperMaxCtx+1) != "" {
		t.Fatal("requests that fit the 8K bucket go to the helper, bigger ones don't")
	}
	if ctxBucket(helperMaxCtx, 0) != 8192 {
		t.Fatal("the helper's size limit must stay inside the 8K bucket")
	}
}

// The helper reviews only shorter results: on the long review cases it was
// reliable up to about 5,500 characters and missed most flaws from 8,300 on.
func TestHelperReviewsOnlyShorterResults(t *testing.T) {
	req := taskReq{Goal: strings.Repeat("g", 300)}
	for size, want := range map[int]string{1000: helperModel, 5500: helperModel, 6300: "", 8300: "", 20000: ""} {
		if got := reviewRequest(req, strings.Repeat("x", size)).PreferModel; got != want {
			t.Errorf("a %d-character result: prefer_model %q, want %q", size, got, want)
		}
	}
	if helperMaxReviewCtx > helperMaxCtx {
		t.Fatal("the review limit must stay inside the helper's own limit")
	}
}

func helperTestHub(t *testing.T) *Hub {
	t.Helper()
	h := NewHub(filepath.Join(t.TempDir(), "hub.json"), 0)
	h.lib = loadLibrary(filepath.Join(t.TempDir(), "library.json"))
	return h
}

func lender(id, name, owner string, models ...ModelInfo) *hubDevice {
	return &hubDevice{ID: id, Name: name, Owner: owner, online: true, lending: true, ollamaOK: true, lastSeen: time.Now(), slots: 1, models: models}
}

var (
	hydraM = ModelInfo{Name: "hydra:1.0", ParamsB: 4, SizeBytes: 2.9e9, Caps: []string{"completion"}}
	bigM   = ModelInfo{Name: "big:70b", ParamsB: 70, SizeBytes: 43e9, Loaded: true, Caps: []string{"completion"}}
	midM   = ModelInfo{Name: "mid:8b", ParamsB: 8, SizeBytes: 5e9, Caps: []string{"completion"}}
)

func submitStep(t *testing.T, h *Hub, asker *hubDevice, body string) (*hubStep, *httptest.ResponseRecorder) {
	t.Helper()
	rr := httptest.NewRecorder()
	h.handleSubmit(rr, httptest.NewRequest("POST", "/v1/steps", strings.NewReader(body)), asker)
	var out struct{ ID string }
	_ = json.Unmarshal(rr.Body.Bytes(), &out)
	return h.steps[out.ID], rr
}

// The planner, reviewer and Head check go to a computer that has the helper,
// ahead of the biggest model; with no helper anywhere, they route as before.
func TestHubPrefersTheHelperForItsJobs(t *testing.T) {
	plan := `{"messages":[{"role":"user","content":"plan this"}],"prefer":"largest","need_ctx":3000,"prefer_model":"hydra:1.0"}`
	gate := `{"messages":[{"role":"user","content":"Should this tool handle the request?"}],"prefer":"fastest","prefer_model":"hydra:1.0","not_here":true}`
	// Both lenders are waiting for work; the hub hands the step to the best one.
	run := func(laptopModels []ModelInfo, body string) *hubStep {
		h := helperTestHub(t)
		h.st.Devices["s"] = lender("s", "Studio", "Andrews", bigM)
		h.st.Devices["l"] = lender("l", "Laptop", "Bob", laptopModels...)
		asker := &hubDevice{ID: "a", Name: "Asker", Owner: "Sam", online: true, lastSeen: time.Now()}
		h.st.Devices["a"] = asker
		for _, id := range []string{"s", "l"} {
			h.waiters[id] = &waiter{deviceID: id, ch: make(chan *hubStep, 1)}
		}
		st, rr := submitStep(t, h, asker, body)
		if rr.Code != 200 || st == nil {
			t.Fatalf("submit: %d %s", rr.Code, rr.Body)
		}
		return st
	}
	if st := run([]ModelInfo{midM, hydraM}, plan); st.Assigned != "l" || st.RunModel != "hydra:1.0" {
		t.Fatalf("the helper should win over the biggest model: got %s on %s", st.RunModel, st.Assigned)
	}
	// The same step without prefer_model (an older asker) still goes to the biggest model.
	if st := run([]ModelInfo{midM, hydraM}, strings.Replace(plan, `,"prefer_model":"hydra:1.0"`, "", 1)); st.Assigned != "s" || st.RunModel != "big:70b" {
		t.Fatalf("without prefer_model: want big:70b on the Studio, got %s on %s", st.RunModel, st.Assigned)
	}
	// Nobody has the helper: the step routes exactly as Prefer says.
	if st := run([]ModelInfo{midM}, plan); st.Assigned != "s" || st.RunModel != "big:70b" {
		t.Fatalf("no helper: want the biggest model, got %s on %s", st.RunModel, st.Assigned)
	}
	// The Head check: the helper first, else the fastest model.
	if st := run([]ModelInfo{midM, hydraM}, gate); st.Assigned != "l" || st.RunModel != "hydra:1.0" {
		t.Fatalf("Head check: want the helper, got %s on %s", st.RunModel, st.Assigned)
	}
	h := helperTestHub(t)
	if _, score, ok := h.fits(lender("l", "Laptop", "Bob", midM, hydraM), &hubStep{Prefer: "fastest", PreferModel: helperModel, Exclude: map[string]bool{}}); !ok || score < preferredScore/2 {
		t.Fatalf("the helper's computer should score far above the rest: %v %v", score, ok)
	}
}

// The helper only does its own three jobs: never a chat, a worker step,
// combining or a library job, even where it's the only model.
func TestHelperNeverTakesOrdinaryWork(t *testing.T) {
	h := helperTestHub(t)
	only := lender("h", "Helper box", "Bob", hydraM)
	asker := &hubDevice{ID: "a", Name: "Asker", Owner: "Sam", online: true, lastSeen: time.Now()}
	h.st.Devices["h"], h.st.Devices["a"] = only, asker
	for _, prefer := range []string{"", "largest", "fastest"} {
		if m, _, ok := h.fits(only, &hubStep{Prefer: prefer, Exclude: map[string]bool{}}); ok {
			t.Errorf("prefer %q: the helper must not take ordinary work, got %s", prefer, m)
		}
	}
	if _, rr := submitStep(t, h, asker, `{"messages":[{"role":"user","content":"hi"}]}`); rr.Code != 409 {
		t.Fatalf("a chat with only the helper lending: want 409 (no model), got %d %s", rr.Code, rr.Body)
	}
	if top := h.largestLocked(&hubStep{Exclude: map[string]bool{}}); top != 0 {
		t.Fatalf("the library's 'biggest model' must not count the helper: %v", top)
	}
	// Asked for by name, it still runs (an explicit choice).
	if m, _, ok := h.fits(only, &hubStep{Model: "hydra:1.0", Exclude: map[string]bool{}}); !ok || m != "hydra:1.0" {
		t.Fatal("a step that names the helper may run on it")
	}
	if m, ok := fastestChatModel([]ModelInfo{{Name: "hydra:1.0", ParamsB: 4, SizeBytes: 2.9e9, Loaded: true}, {Name: "big:14b", ParamsB: 14, SizeBytes: 9e9}}); !ok || m.Name != "big:14b" {
		t.Fatalf("reading a Head's options isn't the helper's job: got %s", m.Name)
	}
	if best := bestFor(DeviceProfile{}, []ModelInfo{{Name: "hydra:1.0", Caps: []string{"completion"}, TokS: 120, CtxMax: 262144}}); len(best) != 0 {
		t.Fatalf("the helper alone doesn't make a computer good for fast replies or long context: %v", best)
	}
}

// prefer_model keeps to the step's limits: Only my devices, not_here, and the
// context it needs.
func TestHelperPreferenceKeepsTheStepsLimits(t *testing.T) {
	h := helperTestHub(t)
	asker := lender("a", "Asker", "Sam", hydraM)
	other := lender("o", "Other", "Bob", midM, hydraM)
	h.st.Devices["a"], h.st.Devices["o"] = asker, other
	st := &hubStep{RequesterID: "a", RequesterOwner: "Sam", Prefer: "fastest", PreferModel: helperModel, Exclude: map[string]bool{"a": true}}
	if _, _, ok := h.fits(asker, st); ok {
		t.Fatal("not_here: the asker's helper must not take the step")
	}
	if m, _, _ := h.fits(other, st); m != "hydra:1.0" {
		t.Fatalf("another computer's helper should: got %q", m)
	}
	private := &hubStep{RequesterID: "a", RequesterOwner: "Sam", Private: true, Prefer: "largest", PreferModel: helperModel, Exclude: map[string]bool{}}
	if _, _, ok := h.fits(other, private); ok {
		t.Fatal("Only my devices: someone else's helper is out of bounds")
	}
	small := ModelInfo{Name: "hydra:1.0", ParamsB: 4, Caps: []string{"completion"}, CtxMax: 8192}
	other.models = []ModelInfo{midM, small}
	if m, _, _ := h.fits(other, &hubStep{Prefer: "largest", PreferModel: helperModel, NeedCtx: 20000, Exclude: map[string]bool{}}); m != "mid:8b" {
		t.Fatalf("a helper without room for the text gives way: got %q", m)
	}
}

// On this computer (not joined, or nobody lending) the same rules hold.
func TestLocalModelChoiceAndTheHelper(t *testing.T) {
	big := ModelInfo{Name: "big:14b", ParamsB: 14, Caps: []string{"completion"}}
	vis := ModelInfo{Name: "eyes:8b", ParamsB: 8, Caps: []string{"completion", "vision"}}
	models := []ModelInfo{hydraM, big, vis}
	if m, _ := pickLocalModel(models, "", nil, "largest", helperModel); m.Name != "hydra:1.0" {
		t.Fatalf("the helper's job: want hydra:1.0, got %s", m.Name)
	}
	if m, _ := pickLocalModel(models, "", nil, "largest", ""); m.Name != "big:14b" {
		t.Fatalf("anything else: never the helper, got %s", m.Name)
	}
	if m, _ := pickLocalModel(models, "", nil, "fastest", ""); m.Name == "hydra:1.0" {
		t.Fatal("fastest: never the helper")
	}
	if m, _ := pickLocalModel(models, "", []string{"vision"}, "", helperModel); m.Name != "eyes:8b" {
		t.Fatalf("a capability the helper lacks: got %s", m.Name)
	}
	if _, ok := pickLocalModel([]ModelInfo{hydraM}, "", nil, "", ""); ok {
		t.Fatal("only the helper here: a chat has no model")
	}
	if m, _ := pickLocalModel(models, "hydra:1.0", nil, "", ""); m.Name != "hydra:1.0" {
		t.Fatal("named explicitly, it's used")
	}
}

func TestParseOllamaParameters(t *testing.T) {
	in := "repeat_penalty                 1\nstop                           \"<|im_start|>\"\nstop                           \"<|im_end|>\"\n" +
		"temperature                    0.7\ntop_k                          20\ntop_p                          0.8\nnum_predict                    4096"
	got := parseOllamaParameters(in)
	want := map[string]any{"num_predict": int64(4096), "repeat_penalty": int64(1), "stop": []string{"<|im_start|>", "<|im_end|>"},
		"temperature": 0.7, "top_k": int64(20), "top_p": 0.8}
	if fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("got %v\nwant %v", got, want)
	}
}

// fakeOllama is enough of Ollama's API for the helper's install: models, show,
// blobs and create.
type fakeOllama struct {
	mu      sync.Mutex
	models  []string
	show    map[string]ollamaShowFull
	blobs   map[string][]byte
	creates []map[string]any
}

func (f *fakeOllama) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	switch {
	case r.URL.Path == "/api/version":
		writeJSON(w, 200, map[string]string{"version": "0.40.1"})
	case r.URL.Path == "/api/tags":
		var ms []map[string]any
		for _, m := range f.models {
			ms = append(ms, map[string]any{"name": m, "model": m, "size": 2_900_000_000, "digest": "d-" + m,
				"details": map[string]string{"family": "qwen3", "parameter_size": "4.0B", "quantization_level": "Q5_K_M"}})
		}
		writeJSON(w, 200, map[string]any{"models": ms})
	case r.URL.Path == "/api/ps":
		writeJSON(w, 200, map[string]any{"models": []any{}})
	case r.URL.Path == "/api/show":
		var req struct{ Model string }
		_ = json.NewDecoder(r.Body).Decode(&req)
		sf, ok := f.show[req.Model]
		if !ok {
			writeJSON(w, 200, map[string]any{"capabilities": []string{"completion"}})
			return
		}
		writeJSON(w, 200, map[string]any{"capabilities": []string{"completion"}, "modelfile": sf.Modelfile, "template": sf.Template,
			"parameters": sf.Parameters, "license": sf.License})
	case strings.HasPrefix(r.URL.Path, "/api/blobs/"):
		digest := strings.TrimPrefix(r.URL.Path, "/api/blobs/")
		if r.Method == "HEAD" {
			if _, ok := f.blobs[digest]; ok {
				w.WriteHeader(200)
			} else {
				w.WriteHeader(404)
			}
			return
		}
		b, _ := io.ReadAll(r.Body)
		sum := sha256.Sum256(b)
		if "sha256:"+hex.EncodeToString(sum[:]) != digest {
			w.WriteHeader(400)
			return
		}
		f.blobs[digest] = b
		w.WriteHeader(201)
	case r.URL.Path == "/api/create":
		var req map[string]any
		_ = json.NewDecoder(r.Body).Decode(&req)
		files, _ := req["files"].(map[string]any)
		for _, d := range files {
			if _, ok := f.blobs[fmt.Sprint(d)]; !ok {
				writeJSON(w, 400, map[string]string{"error": "no blob " + fmt.Sprint(d)})
				return
			}
		}
		f.creates = append(f.creates, req)
		f.models = append(f.models, fmt.Sprint(req["model"]))
		w.Header().Set("Content-Type", "application/x-ndjson")
		fmt.Fprintln(w, `{"status":"using existing layer"}`)
		fmt.Fprintln(w, `{"status":"success"}`)
	default:
		w.WriteHeader(404)
	}
}

// The host hands out its own Hydra 1.0 and another computer in its network
// makes it in its own Ollama: same file, template, parameters and licence.
func TestHelperGoesFromTheHostToAnotherComputer(t *testing.T) {
	weights := []byte(strings.Repeat("GGUF fake weights ", 50000))
	sum := sha256.Sum256(weights)
	digest := "sha256:" + hex.EncodeToString(sum[:])
	blobDir := t.TempDir()
	blob := filepath.Join(blobDir, "sha256-"+hex.EncodeToString(sum[:]))
	if err := os.WriteFile(blob, weights, 0o644); err != nil {
		t.Fatal(err)
	}
	hostOllama := &fakeOllama{models: []string{"hydra:1.0", "big:70b"}, blobs: map[string][]byte{}, show: map[string]ollamaShowFull{
		"hydra:1.0": {Modelfile: "# Modelfile generated by \"ollama show\"\nFROM " + blob + "\nTEMPLATE \"\"\"x\"\"\"\n",
			Template: "{{ .Prompt }}", Parameters: "stop                           \"<|im_end|>\"\nnum_predict                    4096", License: "Apache License 2.0"}}}
	hostOS := httptest.NewServer(hostOllama)
	defer hostOS.Close()
	host := NewApp(t.TempDir(), 0, 0, hostOS.URL)
	host.ollama.check()

	h := helperTestHub(t)
	h.SetHelperSource(host.sharedHelper)
	var off *HelperOffer
	for i := 0; i < 100 && off == nil; i++ { // built in the background on first ask
		off = h.helperOffer()
		time.Sleep(20 * time.Millisecond)
	}
	if off == nil || off.Digest != digest || off.Size != int64(len(weights)) || off.Parameters["num_predict"] != int64(4096) {
		t.Fatalf("the host's offer: %+v", off)
	}
	worker := lender("w", "Laptop", "Bob", midM)
	worker.Token = "tok-w"
	h.st.Devices["w"] = worker
	h.tokens["tok-w"] = "w"
	hubSrv := httptest.NewServer(h.routes())
	defer hubSrv.Close()

	// The snapshot tells members the host has it; the offer itself carries the file's details.
	rr := httptest.NewRecorder()
	h.handleNetwork(rr, httptest.NewRequest("GET", "/v1/network", nil), worker)
	var snap NetSnapshot
	if json.Unmarshal(rr.Body.Bytes(), &snap) != nil || snap.Network.Helper == nil || snap.Network.Helper.Model != helperModel {
		t.Fatalf("the snapshot should say the host shares the helper: %s", rr.Body.String())
	}
	if strings.Contains(rr.Body.String(), blobDir) {
		t.Fatal("the host's file path must not leave the host")
	}

	workerOllama := &fakeOllama{models: []string{"mid:8b"}, blobs: map[string][]byte{}, show: map[string]ollamaShowFull{}}
	workerOS := httptest.NewServer(workerOllama)
	defer workerOS.Close()
	w := NewApp(t.TempDir(), 0, 0, workerOS.URL)
	w.ollama.check()
	w.updateConfig(func(c *Config) { c.HubAddress, c.Token = hubSrv.URL, "tok-w" })
	var copied int64 = -1
	if err := w.installHelper(context.Background(), func(status string, done, total int64) {
		if status == "Copying from the host" {
			copied = done
		}
	}); err != nil {
		t.Fatal(err)
	}
	workerOllama.mu.Lock()
	defer workerOllama.mu.Unlock()
	if string(workerOllama.blobs[digest]) != string(weights) || copied != int64(len(weights)) {
		t.Fatalf("the model file should arrive whole: %d bytes, copy progress %d", len(workerOllama.blobs[digest]), copied)
	}
	if len(workerOllama.creates) != 1 {
		t.Fatalf("want one create, got %d", len(workerOllama.creates))
	}
	var buf strings.Builder
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(workerOllama.creates[0])
	c := buf.String()
	for _, want := range []string{`"model":"hydra:1.0"`, `"files":{"hydra-1.0.gguf":"` + digest + `"}`, `"template":"{{ .Prompt }}"`,
		`"stop":["<|im_end|>"]`, `"num_predict":4096`, `"license":"Apache License 2.0"`} {
		if !strings.Contains(c, want) {
			t.Errorf("create request lacks %s: %s", want, c)
		}
	}
}

func TestHelperFileFromTheManifest(t *testing.T) {
	dir := t.TempDir()
	weights := []byte("weights")
	sum := sha256.Sum256(weights)
	hexs := hex.EncodeToString(sum[:])
	os.MkdirAll(filepath.Join(dir, "blobs"), 0o755)
	os.WriteFile(filepath.Join(dir, "blobs", "sha256-"+hexs), weights, 0o644)
	man := filepath.Join(dir, "manifests-v2", "ollama.com", "library", "hydra", "1.0")
	os.MkdirAll(filepath.Dir(man), 0o755)
	os.WriteFile(man, []byte(`{"layers":[{"mediaType":"application/vnd.ollama.image.template","digest":"sha256:`+strings.Repeat("0", 64)+
		`"},{"mediaType":"application/vnd.ollama.image.model","digest":"sha256:`+hexs+`"}]}`), 0o644)
	t.Setenv("OLLAMA_MODELS", dir)
	p, d, err := findModelFile("FROM hydra:1.0\n", "hydra:1.0")
	if err != nil || d != "sha256:"+hexs || !strings.HasSuffix(p, "sha256-"+hexs) {
		t.Fatalf("got %q %q %v", p, d, err)
	}
	// A FROM path that isn't a blob is hashed.
	other := filepath.Join(t.TempDir(), "helper.gguf")
	os.WriteFile(other, weights, 0o644)
	if _, d, err := findModelFile("FROM "+other+"\n", "hydra:1.0"); err != nil || d != "sha256:"+hexs {
		t.Fatalf("hashed digest: %q %v", d, err)
	}
}

func TestHubLimitsHelperSends(t *testing.T) {
	h := helperTestHub(t)
	f := filepath.Join(t.TempDir(), "sha256-"+strings.Repeat("a", 64))
	os.WriteFile(f, []byte("x"), 0o644)
	h.SetHelperSource(func() *HelperOffer {
		return &HelperOffer{Model: helperModel, Size: 1, Digest: "sha256:" + strings.Repeat("a", 64), path: f}
	})
	d := lender("w", "Laptop", "Bob")
	h.helperSending = helperSendsMax
	rr := httptest.NewRecorder()
	h.handleHelperModel(rr, httptest.NewRequest("GET", "/v1/helper/model", nil), d)
	if rr.Code != 429 {
		t.Fatalf("over the limit: want 429, got %d", rr.Code)
	}
	h.helperSending = 0
	rr = httptest.NewRecorder()
	h.handleHelperModel(rr, httptest.NewRequest("GET", "/v1/helper/model", nil), d)
	if rr.Code != 200 || rr.Body.String() != "x" || h.helperSending != 0 {
		t.Fatalf("a send: %d %q, still sending %d", rr.Code, rr.Body.String(), h.helperSending)
	}
	h.SetHelperSource(nil)
	rr = httptest.NewRecorder()
	h.handleHelper(rr, httptest.NewRequest("GET", "/v1/helper", nil), d)
	if rr.Code != 404 {
		t.Fatalf("no helper on the host: want 404, got %d", rr.Code)
	}
}

// A free computer with the helper that hasn't asked for work yet (it has just
// finished a step, like the combine before a review) gets a moment before the
// step goes to another model; a busy one isn't waited for.
func TestHelperStepWaitsBrieflyForAFreeHelper(t *testing.T) {
	setup := func(studioBusy bool) (*Hub, *hubDevice, *hubStep) {
		h := helperTestHub(t)
		studio := lender("s", "Studio", "Andrews", bigM, hydraM) // lending, but not waiting for work this moment
		h.st.Devices["s"] = studio
		h.st.Devices["l"] = lender("l", "Laptop", "Bob", midM)
		asker := &hubDevice{ID: "a", Name: "Asker", Owner: "Sam", online: true, lastSeen: time.Now()}
		h.st.Devices["a"] = asker
		if studioBusy {
			h.steps["busy"] = &hubStep{ID: "busy", Status: "running", Assigned: "s", Exclude: map[string]bool{}, subs: map[chan hubEvent]struct{}{}}
		}
		h.waiters["l"] = &waiter{deviceID: "l", ch: make(chan *hubStep, 1)}
		st, rr := submitStep(t, h, asker, `{"messages":[{"role":"user","content":"review this"}],"prefer":"largest","prefer_model":"hydra:1.0"}`)
		if rr.Code != 200 {
			t.Fatalf("submit: %d %s", rr.Code, rr.Body)
		}
		return h, studio, st
	}
	h, studio, st := setup(false)
	if st.Status != "queued" {
		t.Fatalf("the Studio is free and about to ask: the laptop shouldn't get it, but it went to %s", st.Assigned)
	}
	if m, _, ok := h.fits(studio, st); !ok || m != "hydra:1.0" {
		t.Fatal("when the Studio asks, it gets the step on the helper")
	}
	st.Created = time.Now().Add(-helperWait - time.Second) // the Studio didn't ask in time
	h.dispatchLocked()
	if st.Assigned != "l" || st.RunModel != "mid:8b" {
		t.Fatalf("after the wait the step goes on: got %s on %s", st.RunModel, st.Assigned)
	}
	_, _, st = setup(true)
	if st.Assigned != "l" {
		t.Fatalf("a busy helper isn't waited for: the step should go to the laptop at once, got %q (%s)", st.Assigned, st.Status)
	}
}

// Ollama gives up partway through the copy (a full disk) while the host's
// stream is momentarily slow. The HTTP transport is still reading the host's
// stream after Ollama has answered; nothing may report progress from there,
// or the app writes to a finished response and crashes (found in review; run
// with -race to see it on the old code).
func TestHelperInstallSurvivesOllamaFailingMidCopy(t *testing.T) {
	digest := "sha256:" + strings.Repeat("b", 64)
	size := int64(64 << 20)
	hub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v1/helper":
			writeJSON(w, 200, map[string]any{"model": "hydra:1.0", "size": size, "digest": digest})
		case "/v1/helper/model":
			w.Header().Set("Content-Length", fmt.Sprint(size))
			w.WriteHeader(200)
			w.Write(make([]byte, 2<<20))
			w.(http.Flusher).Flush()
			select { // a Wi-Fi hiccup
			case <-time.After(1500 * time.Millisecond):
			case <-r.Context().Done():
				return
			}
			w.Write(make([]byte, size-(2<<20)))
		}
	}))
	defer hub.Close()
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/version":
			writeJSON(w, 200, map[string]string{"version": "0.40.1"})
		case r.URL.Path == "/api/tags", r.URL.Path == "/api/ps":
			writeJSON(w, 200, map[string]any{"models": []any{}})
		case strings.HasPrefix(r.URL.Path, "/api/blobs/") && r.Method == "HEAD":
			w.WriteHeader(404)
		case strings.HasPrefix(r.URL.Path, "/api/blobs/"):
			io.CopyN(io.Discard, r.Body, 1<<20)
			time.Sleep(300 * time.Millisecond)
			writeJSON(w, 500, map[string]string{"error": "no space left on device"})
		default:
			w.WriteHeader(404)
		}
	}))
	defer ollama.Close()
	a := NewApp(t.TempDir(), 0, 0, ollama.URL)
	a.ollama.check()
	a.updateConfig(func(c *Config) { c.HubAddress, c.Token = hub.URL, "tok" })
	ui := httptest.NewServer(http.HandlerFunc(a.handleHelperInstall))
	defer ui.Close()
	resp, err := http.Post(ui.URL, "application/json", nil)
	if err != nil {
		t.Fatal(err)
	}
	b, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if !strings.Contains(string(b), "no space left on device") || !strings.Contains(string(b), `"type":"error"`) {
		t.Fatalf("the person should see Ollama's error:\n%s", b)
	}
	time.Sleep(2 * time.Second) // let the transport finish reading the host's stream
	if a.helper.installing {
		t.Fatal("a failed install must let the person try again")
	}
}

// A computer that stops taking the copy (asleep, gone) gives the host's send
// slot back once the write deadline passes, instead of when TCP gives up.
func TestHubGivesUpOnAStalledHelperCopy(t *testing.T) {
	defer func(old time.Duration) { helperStall = old }(helperStall)
	helperStall = 300 * time.Millisecond
	h := helperTestHub(t)
	f := filepath.Join(t.TempDir(), "sha256-"+strings.Repeat("c", 64))
	if err := os.WriteFile(f, make([]byte, 256<<20), 0o644); err != nil {
		t.Fatal(err)
	}
	h.SetHelperSource(func() *HelperOffer {
		return &HelperOffer{Model: helperModel, Size: 256 << 20, Digest: "sha256:" + strings.Repeat("c", 64), path: f}
	})
	d := lender("w", "Laptop", "Bob")
	d.Token = "tok-w"
	h.st.Devices["w"] = d
	h.tokens["tok-w"] = "w"
	srv := httptest.NewServer(h.routes())
	defer srv.Close()
	sending := func() int {
		h.mu.Lock()
		defer h.mu.Unlock()
		return h.helperSending
	}
	req, _ := http.NewRequest("GET", srv.URL+"/v1/helper/model", nil)
	req.Header.Set("Authorization", "Bearer tok-w")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	io.CopyN(io.Discard, resp.Body, 1<<20) // then stop reading, like a laptop that went to sleep
	if n := sending(); n != 1 {
		t.Fatalf("one copy under way: helperSending = %d", n)
	}
	deadline := time.Now().Add(10 * time.Second)
	for sending() != 0 && time.Now().Before(deadline) {
		time.Sleep(50 * time.Millisecond)
	}
	if n := sending(); n != 0 {
		t.Fatalf("the stalled copy should have given its slot back: helperSending = %d", n)
	}
}

// The other end: a host whose stream stops (gone to sleep mid-copy) doesn't
// leave this computer stuck "setting up" forever.
func TestHelperInstallStopsAStalledCopy(t *testing.T) {
	defer func(old time.Duration) { helperStall = old }(helperStall)
	helperStall = 500 * time.Millisecond
	digest := "sha256:" + strings.Repeat("d", 64)
	size := int64(8 << 20)
	hub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v1/helper":
			writeJSON(w, 200, map[string]any{"model": "hydra:1.0", "size": size, "digest": digest})
		case "/v1/helper/model":
			w.Header().Set("Content-Length", fmt.Sprint(size))
			w.WriteHeader(200)
			w.Write(make([]byte, 1<<20))
			w.(http.Flusher).Flush()
			<-r.Context().Done() // and nothing more
		}
	}))
	defer hub.Close()
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/version":
			writeJSON(w, 200, map[string]string{"version": "0.40.1"})
		case r.URL.Path == "/api/tags", r.URL.Path == "/api/ps":
			writeJSON(w, 200, map[string]any{"models": []any{}})
		case strings.HasPrefix(r.URL.Path, "/api/blobs/") && r.Method == "HEAD":
			w.WriteHeader(404)
		case strings.HasPrefix(r.URL.Path, "/api/blobs/"):
			io.Copy(io.Discard, r.Body)
			w.WriteHeader(400)
		default:
			w.WriteHeader(404)
		}
	}))
	defer ollama.Close()
	a := NewApp(t.TempDir(), 0, 0, ollama.URL)
	a.ollama.check()
	a.updateConfig(func(c *Config) { c.HubAddress, c.Token = hub.URL, "tok" })
	done := make(chan error, 1)
	go func() { done <- a.installHelper(context.Background(), func(string, int64, int64) {}) }()
	select {
	case err := <-done:
		if err == nil || !strings.Contains(err.Error(), "stopped") {
			t.Fatalf("want the stalled-copy message, got %v", err)
		}
	case <-time.After(15 * time.Second):
		t.Fatal("a stalled copy should be given up")
	}
}
