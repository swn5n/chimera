package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// fakeOllama answers as Ollama 0.40.1 does on the calls the tool makes.
func fakeOllama(t *testing.T, chatBody string, seen *[]string) *httptest.Server {
	t.Helper()
	blob := false
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		*seen = append(*seen, r.Method+" "+r.URL.Path)
		switch {
		case r.Method == "HEAD" && strings.HasPrefix(r.URL.Path, "/api/blobs/"):
			if blob {
				w.WriteHeader(200)
			} else {
				w.WriteHeader(404)
			}
		case r.Method == "POST" && strings.HasPrefix(r.URL.Path, "/api/blobs/"):
			io.Copy(io.Discard, r.Body)
			blob = true
			w.WriteHeader(201)
		case r.URL.Path == "/api/create":
			var b map[string]any
			json.NewDecoder(r.Body).Decode(&b)
			if b["renderer"] != workerRenderer || b["parser"] != workerParser {
				t.Errorf("create body: %v", b)
			}
			w.Write([]byte(`{"status":"success"}`))
		case r.URL.Path == "/api/chat":
			var b map[string]any
			json.NewDecoder(r.Body).Decode(&b)
			if _, ok := b["think"]; ok {
				t.Errorf("Chimera sends no think field: %v", b)
			}
			if b["stream"] != true {
				t.Errorf("Chimera streams: %v", b)
			}
			w.Write([]byte(chatBody))
		}
	}))
}

func testClient(s *httptest.Server) *client {
	c := newClient(s.URL)
	c.http = s.Client()
	return c
}

func TestChatReadsTheStreamLikeChimera(t *testing.T) {
	var seen []string
	s := fakeOllama(t, `{"message":{"content":"import bpy"}}
{"message":{"content":"\nprint(1)"}}
{"message":{"content":""},"done":true,"done_reason":"stop","prompt_eval_count":1605,"prompt_eval_duration":2000000000,"eval_count":50,"eval_duration":1000000000,"load_duration":500000000}
`, &seen)
	defer s.Close()
	c := testClient(s)
	r, err := c.chat(context.Background(), "m", []message{{"user", "x"}}, 8192, 300)
	if err != nil {
		t.Fatal(err)
	}
	if r.PromptTokens != 1605 || r.Tokens != 50 || r.TokS != 50 || r.PromptS != 2 || r.LoadS != 0.5 || r.DoneReason != "stop" {
		t.Errorf("%+v", r)
	}
	if r.ThinkingText || r.Markers || r.EmptyReply {
		t.Errorf("a clean reply was flagged: %+v", r)
	}
}

func TestChatFlagsThinkingMarkersAndEmptyReplies(t *testing.T) {
	var seen []string
	s := fakeOllama(t, `{"message":{"thinking":"let me see"}}
{"message":{"content":"<|channel>thought\n<channel|>"}}
{"done":true}
`, &seen)
	defer s.Close()
	c := testClient(s)
	r, err := c.chat(context.Background(), "m", nil, 8192, 10)
	if err != nil {
		t.Fatal(err)
	}
	if !r.ThinkingText || !r.Markers {
		t.Errorf("%+v", r)
	}
	s2 := fakeOllama(t, `{"message":{"thinking":"only this"}}
{"done":true}
`, &seen)
	defer s2.Close()
	c = testClient(s2)
	if r, _ = c.chat(context.Background(), "m", nil, 8192, 10); !r.EmptyReply {
		t.Errorf("%+v", r)
	}
}

func TestChatNeedsTheFinalLine(t *testing.T) {
	var seen []string
	s := fakeOllama(t, `{"message":{"content":"cut"}}
`, &seen)
	defer s.Close()
	c := testClient(s)
	if _, err := c.chat(context.Background(), "m", nil, 8192, 10); err == nil {
		t.Fatal("a stream with no final line should fail")
	}
}

func TestStreamedErrorComesBack(t *testing.T) {
	var seen []string
	s := fakeOllama(t, `{"error":"model requires more system memory"}
`, &seen)
	defer s.Close()
	c := testClient(s)
	_, err := c.chat(context.Background(), "m", nil, 8192, 10)
	if err == nil || !strings.Contains(err.Error(), "system memory") {
		t.Fatalf("%v", err)
	}
}

func TestUploadSkipsABlobOllamaHas(t *testing.T) {
	var seen []string
	s := fakeOllama(t, "", &seen)
	defer s.Close()
	p := filepath.Join(t.TempDir(), "x.gguf")
	os.WriteFile(p, []byte("GGUF test"), 0o644)
	digest, size, err := fileDigest(p)
	if err != nil || size != 9 || !strings.HasPrefix(digest, "sha256:") || len(digest) != 71 {
		t.Fatal(digest, size, err)
	}
	c := testClient(s)
	for i := 0; i < 2; i++ {
		if err := c.upload(context.Background(), p, digest, size); err != nil {
			t.Fatal(err)
		}
	}
	posts := 0
	for _, x := range seen {
		if strings.HasPrefix(x, "POST /api/blobs/") {
			posts++
		}
	}
	if posts != 1 {
		t.Errorf("uploaded %d times: %v", posts, seen)
	}
	if err := c.create(context.Background(), importTag, digest); err != nil {
		t.Fatal(err)
	}
}

func TestShowReadsTheModelfileLines(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"modelfile":"# made by\nFROM /x\nRENDERER gemma4-large\nPARSER gemma4-no-thinking\nLICENSE \"\"\"RENDERER nope\"\"\"\n","thinking":{"values":[false],"default":false}}`))
	}))
	defer s.Close()
	c := testClient(s)
	rn, pa, th, err := c.show(context.Background(), "m")
	if err != nil || rn != workerRenderer || pa != workerParser || th == nil {
		t.Fatal(rn, pa, th, err)
	}
}

func goodReport() *report {
	sp := chatResult{TokS: 30, PromptS: 2, Tokens: 300}
	return &report{Renderer: workerRenderer, Parser: workerParser, Thinking: map[string]any{"values": []any{false}, "default": false},
		Step: chatResult{TokS: 30, PromptTokens: 1605, PromptS: 2, Tokens: 800}, StepGPUPct: 100,
		Step1500S: 52, Long: chatResult{PromptTokens: 7799, TokS: 30, Tokens: 64},
		Fits: []fit{{NumCtx: 8192, CtxLen: 8192, SizeGB: 9.5, VRAMGB: 9.5, GPUPct: 100, Speed: sp},
			{NumCtx: 16384, CtxLen: 16384, SizeGB: 9.7, VRAMGB: 9.7, GPUPct: 100, Speed: sp},
			{NumCtx: 32768, CtxLen: 32768, SizeGB: 10.1, VRAMGB: 10.1, GPUPct: 100, Speed: sp}}}
}

func wanted() requests {
	return requests{Short: request{PromptTokens: 1605}, Long: request{PromptTokens: 7799}}
}

func TestBarsOnAGoodRun(t *testing.T) {
	for _, goos := range []string{"windows", "darwin", "linux"} {
		for _, v := range bars(goodReport(), goos, wanted(), true) {
			if !v.OK {
				t.Errorf("%s: %+v", goos, v)
			}
		}
	}
}

func TestBarsCatchWhatMatters(t *testing.T) {
	find := func(vs []verdict, name string) verdict {
		for _, v := range vs {
			if strings.HasPrefix(v.Name, name) {
				return v
			}
		}
		t.Fatalf("no verdict %q in %+v", name, vs)
		return verdict{}
	}
	r := goodReport()
	r.Fits[2].VRAMGB, r.Fits[2].GPUPct = 9.0, 89.1 // part of it on the CPU at 32K
	if find(bars(r, "windows", wanted(), true), "Fit at 32K").OK {
		t.Error("89% on the GPU passed")
	}
	r = goodReport()
	r.Fits[1].Failure = "out of memory"
	if find(bars(r, "windows", wanted(), true), "Fit at 16K").OK {
		t.Error("a failed load passed")
	}
	r = goodReport()
	r.Renderer = "gemma4"
	if find(bars(r, "windows", wanted(), true), "Worker setup").OK {
		t.Error("the wrong renderer passed")
	}
	r = goodReport()
	r.Step.ThinkingText = true
	if find(bars(r, "windows", wanted(), true), "Replies").OK {
		t.Error("thinking passed")
	}
	r = goodReport()
	r.Step.PromptTokens = 1601
	if find(bars(r, "windows", wanted(), true), "Short prompt").OK {
		t.Error("a different prompt count passed")
	}
	r = goodReport()
	r.Step.TokS, r.Step1500S = 20, 80
	if find(bars(r, "windows", wanted(), true), "Speed (3080").OK || find(bars(r, "windows", wanted(), true), "1,500").OK {
		t.Error("the 3080 Ti's speed bars passed at 20 tok/s")
	}
	if !find(bars(r, "darwin", wanted(), true), "Speed (M4").OK {
		t.Error("the M4 Pro's bar is 15 tok/s")
	}
	// the review's cases: a clamped context, another model, thinking on, a three-token reply, a slowdown, no GPU at all
	r = goodReport()
	r.Fits[2].CtxLen = 4096
	if v := find(bars(r, "windows", wanted(), true), "Fit at 32K"); v.OK || !strings.Contains(v.Got, "loaded 4096") {
		t.Errorf("a clamped context passed: %+v", v)
	}
	r = goodReport()
	r.Fits[0].Others = "gemma4:12b"
	if v := find(bars(r, "windows", wanted(), true), "Fit at 8K"); v.OK || !strings.Contains(v.Got, "gemma4:12b") {
		t.Errorf("a reading with another model loaded passed: %+v", v)
	}
	r = goodReport()
	r.Thinking = map[string]any{"values": []any{false, true}, "default": true}
	if find(bars(r, "windows", wanted(), true), "Worker setup").OK {
		t.Error("thinking on passed")
	}
	r = goodReport()
	r.Step.Tokens = 3
	if find(bars(r, "darwin", wanted(), true), "Speed (M4").OK {
		t.Error("three tokens passed the speed bar")
	}
	r = goodReport()
	r.Fits[2].Speed.TokS = 12
	if find(bars(r, "windows", wanted(), true), "Speed at larger").OK {
		t.Error("a slowdown at 32K passed")
	}
	r = goodReport()
	r.Fits[0].VRAMGB, r.Fits[0].GPUPct = 0, 0
	if v := find(bars(r, "windows", wanted(), true), "Fit at 8K"); v.OK || !strings.Contains(v.Note, "isn't using the GPU") {
		t.Errorf("no GPU: %+v", v)
	}
}

func TestAFailedStepStillGivesEveryLine(t *testing.T) {
	r := goodReport()
	r.Step, r.Long = chatResult{}, chatResult{}
	r.StepFailure, r.LongFailure = "/api/chat: HTTP 500: out of memory", "no reply for 121 s"
	r.Fits = r.Fits[:2]
	vs := bars(r, "windows", wanted(), true)
	names := map[string]verdict{}
	for _, v := range vs {
		names[v.Name] = v
	}
	if v := names["Fit at 32K"]; v.OK || v.Got != "not measured" {
		t.Errorf("%+v", v)
	}
	if v := names["Short prompt tokens"]; v.OK || !strings.Contains(v.Got, "out of memory") {
		t.Errorf("%+v", v)
	}
	if v := names["Speed (3080 Ti)"]; v.OK || !strings.Contains(v.Got, "not measured") {
		t.Errorf("%+v", v)
	}
	if !names["Fit at 8K"].OK {
		t.Error("what was measured should still count")
	}
	r.Computer, r.Verdicts, r.Stopped = "PC", vs, "unloading: gone"
	out := results(r)
	for _, want := range []string{"FAIL  Fit at 32K", "PASS  Fit at 8K", "STOPPED early"} {
		if !strings.Contains(out, want) {
			t.Errorf("no %q in %s", want, out)
		}
	}
}

func TestASilentReplyFails(t *testing.T) {
	release := make(chan struct{})
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("{\"message\":{\"content\":\"a\"}}\n"))
		w.(http.Flusher).Flush()
		<-release
	}))
	defer s.Close()
	defer close(release)
	c := testClient(s)
	c.nextLine = 1500 * time.Millisecond
	_, err := c.chat(context.Background(), "m", nil, 8192, 10)
	if err == nil || !strings.Contains(err.Error(), "no reply for") {
		t.Fatalf("%v", err)
	}
}

func TestAStalledUploadStops(t *testing.T) {
	release := make(chan struct{})
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "HEAD" {
			w.WriteHeader(404)
			return
		}
		<-release // reads nothing
	}))
	defer s.Close()
	defer close(release)
	p := filepath.Join(t.TempDir(), "x.gguf")
	os.WriteFile(p, make([]byte, 64<<20), 0o644)
	c := testClient(s)
	c.stallUpload = 1500 * time.Millisecond
	err := c.upload(context.Background(), p, "sha256:00", 64<<20)
	if err == nil || !strings.Contains(err.Error(), "stalled") {
		t.Fatalf("%v", err)
	}
}

func TestThinkingOff(t *testing.T) {
	if thinkingOff(nil) || thinkingOff("x") || thinkingOff(map[string]any{"default": true}) {
		t.Error("should need an explicit default of false")
	}
	if !thinkingOff(map[string]any{"default": false}) {
		t.Error("default false is off")
	}
}

func TestSameModelName(t *testing.T) {
	if !same("foo:latest", "foo") || !same("a:b", "a:b") || same("foo:bar", "foo") {
		t.Error("same")
	}
}

func TestAnOtherModelGetsOnlyFitAndSpeed(t *testing.T) {
	r := goodReport()
	r.Renderer, r.Parser = "", ""
	r.Step.PromptTokens = 1400
	for _, v := range bars(r, "windows", wanted(), false) {
		if !v.OK {
			t.Errorf("%+v", v)
		}
	}
}
