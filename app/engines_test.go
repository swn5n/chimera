package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// TestFakeEngineServer is not a test: an engine's command runs the test binary
// with "-test.run=^TestFakeEngineServer$ -- fake-engine <port> <log>", and this
// serves an OpenAI-style streaming chat API there until it's stopped.
func TestFakeEngineServer(t *testing.T) {
	args := flag.Args()
	if len(args) < 3 || args[0] != "fake-engine" {
		t.Skip("only runs as an engine for the other tests")
	}
	port, logPath := args[1], args[2]
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte(`{"status":"ok"}`)) })
	mux.HandleFunc("POST /v1/chat/completions", func(w http.ResponseWriter, r *http.Request) {
		var req map[string]any
		_ = json.NewDecoder(r.Body).Decode(&req)
		b, _ := json.Marshal(req)
		if f, err := os.OpenFile(logPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644); err == nil {
			f.Write(append(b, '\n'))
			f.Close()
		}
		last := ""
		for _, m := range req["messages"].([]any) {
			if mm := m.(map[string]any); mm["role"] == "user" {
				last = mm["content"].(string)
			}
		}
		fl := w.(http.Flusher)
		w.Header().Set("Content-Type", "text/event-stream")
		send := func(v any) { b, _ := json.Marshal(v); fmt.Fprintf(w, "data: %s\n\n", b); fl.Flush() }
		delta := func(k, v string) {
			send(map[string]any{"choices": []any{map[string]any{"delta": map[string]string{k: v}}}})
		}
		if kw, _ := req["chat_template_kwargs"].(map[string]any); kw != nil && kw["enable_thinking"] == true {
			delta("reasoning_content", "think ")
			delta("reasoning_content", "hard. ")
		}
		if strings.Contains(last, "slow") {
			for i := 0; i < 600; i++ {
				select {
				case <-r.Context().Done():
					return
				case <-time.After(20 * time.Millisecond):
				}
				delta("content", "w ")
			}
		}
		delta("content", "Hello ")
		delta("content", "there.")
		send(map[string]any{"choices": []any{map[string]any{"delta": map[string]any{}, "finish_reason": "stop"}}})
		send(map[string]any{"choices": []any{}, "usage": map[string]int{"prompt_tokens": 12, "completion_tokens": 4},
			"timings": map[string]float64{"predicted_n": 4, "predicted_per_second": 3.82}})
		fmt.Fprint(w, "data: [DONE]\n\n")
		fl.Flush()
	})
	srv := &http.Server{Addr: "127.0.0.1:" + port, Handler: mux}
	_ = srv.ListenAndServe()
}

func freePort(t *testing.T) int {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port
}

// engineApp is an app whose engines.json has one engine, "fake", run by this test binary.
func engineApp(t *testing.T, edit func(*EngineSpec)) (*App, string) {
	t.Helper()
	dir := t.TempDir()
	logPath := filepath.Join(dir, "requests.jsonl")
	spec := EngineSpec{ID: "fake", Name: "Fake Flash", Port: freePort(t), Context: 32768, MaxTokens: 8192,
		Command:  []string{os.Args[0], "-test.run=^TestFakeEngineServer$", "--", "fake-engine", "{port}", logPath},
		Thinking: []string{"off", "low", "medium", "high", "max"}, DefaultThinking: "high", StartSeconds: 30}
	if edit != nil {
		edit(&spec)
	}
	b, _ := json.Marshal([]EngineSpec{spec})
	if err := os.WriteFile(filepath.Join(dir, "engines.json"), b, 0o644); err != nil {
		t.Fatal(err)
	}
	a := NewApp(dir, 0, 0, "http://127.0.0.1:1")
	t.Cleanup(a.engines.StopAll)
	return a, logPath
}

func lastRequest(t *testing.T, logPath string) map[string]any {
	t.Helper()
	b, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(string(b)), "\n")
	var req map[string]any
	if err := json.Unmarshal([]byte(lines[len(lines)-1]), &req); err != nil {
		t.Fatal(err)
	}
	return req
}

func TestAnEngineStartsWhenAChatNeedsItAndStopsWhenAsked(t *testing.T) {
	a, logPath := engineApp(t, nil)
	if v := a.engines.Views(); len(v) != 1 || v[0].Status != "stopped" || v[0].Model != "engine:fake" {
		t.Fatalf("before: %+v", v)
	}
	var evs []genEvent
	final := a.engines.Run(context.Background(), "fake", []ChatMessage{{Role: "user", Content: "hi"}}, "high", func(e genEvent) { evs = append(evs, e) })
	if final.Type != "done" || final.Tokens != 4 || final.PromptTokens != 12 || final.TokPerSec != 3.82 || !final.Local {
		t.Fatalf("final: %+v", final)
	}
	var content, thinking string
	assigned := false
	for _, e := range evs {
		content += e.Content
		thinking += e.Thinking
		if e.Type == "assigned" && e.Model == "Fake Flash" && e.Local {
			assigned = true
		}
	}
	if content != "Hello there." || thinking != "think hard. " || !assigned {
		t.Fatalf("content %q thinking %q assigned %v", content, thinking, assigned)
	}
	req := lastRequest(t, logPath)
	if req["reasoning_effort"] != "high" || req["chat_template_kwargs"].(map[string]any)["enable_thinking"] != true || req["stream"] != true {
		t.Fatalf("request: %v", req)
	}
	if mt := req["max_tokens"].(float64); mt <= 0 || mt > 8192 {
		t.Fatalf("max_tokens %v", mt)
	}
	v := a.engines.Views()[0]
	if v.Status != "ready" || v.External {
		t.Fatalf("after a reply: %+v", v)
	}
	a.engines.Stop("fake")
	if v := a.engines.Views()[0]; v.Status != "stopped" {
		t.Fatalf("after stop: %+v", v)
	}
	a.engines.mu.Lock()
	p := a.engines.specs[0].Port
	a.engines.mu.Unlock()
	if portBusy(p) {
		t.Fatal("the server is still listening after Stop")
	}
}

func TestThinkingLevelsBecomeTheRightFields(t *testing.T) {
	s := EngineSpec{Thinking: []string{"off", "low", "high"}, DefaultThinking: "low"}
	for level, want := range map[string]string{"off": `{"chat_template_kwargs":{"enable_thinking":false}}`,
		"high": `{"chat_template_kwargs":{"enable_thinking":true},"reasoning_effort":"high"}`,
		"":     `{"chat_template_kwargs":{"enable_thinking":true},"reasoning_effort":"low"}`,
		"max":  `{}`} { // not one it takes: nothing is sent
		body := map[string]any{}
		s.thinkingFields(level, body)
		b, _ := json.Marshal(body)
		if string(b) != want {
			t.Errorf("%q: %s, want %s", level, b, want)
		}
	}
	none := map[string]any{}
	EngineSpec{}.thinkingFields("high", none)
	if len(none) != 0 {
		t.Errorf("an engine that doesn't think got %v", none)
	}
}

func TestStoppingAReplyEndsItAndTheNextOneStillRuns(t *testing.T) {
	a, _ := engineApp(t, nil)
	ctx, cancel := context.WithCancel(context.Background())
	got := make(chan genEvent, 1)
	go func() {
		got <- a.engines.Run(ctx, "fake", []ChatMessage{{Role: "user", Content: "slow please"}}, "off", func(genEvent) {})
	}()
	time.Sleep(1500 * time.Millisecond)
	cancel()
	select {
	case f := <-got:
		if f.Type != "cancelled" {
			t.Fatalf("stopped reply: %+v", f)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("cancelling didn't end the reply")
	}
	f := a.engines.Run(context.Background(), "fake", []ChatMessage{{Role: "user", Content: "again"}}, "off", func(genEvent) {})
	if f.Type != "done" {
		t.Fatalf("next reply: %+v", f)
	}
}

func TestAServerAlreadyRunningIsUsedButNotStopped(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/health" {
			w.Write([]byte("ok"))
			return
		}
		w.WriteHeader(404)
	}))
	defer srv.Close()
	port, _ := strconv.Atoi(srv.URL[strings.LastIndex(srv.URL, ":")+1:])
	a, _ := engineApp(t, func(s *EngineSpec) { s.Port = port; s.Command = []string{"/nonexistent/should-not-run"} })
	if err := a.engines.Start(context.Background(), "fake", nil); err != nil {
		t.Fatal(err)
	}
	if v := a.engines.Views()[0]; v.Status != "ready" || !v.External {
		t.Fatalf("%+v", v)
	}
	a.engines.Stop("fake")
	if res, err := http.Get(srv.URL + "/health"); err != nil || res.StatusCode != 200 {
		t.Fatal("Stop took down a server Chimera didn't start")
	}
}

func TestAnEngineWhoseDriveIsGoneSaysSo(t *testing.T) {
	a, _ := engineApp(t, func(s *EngineSpec) {
		s.ModelPaths = []string{"/Volumes/NoSuchDrive/model.gguf"}
		s.Command = append(s.Command, "{model}")
	})
	if v := a.engines.Views()[0]; v.Status != "missing" || !strings.Contains(v.Error, "NoSuchDrive") {
		t.Fatalf("%+v", v)
	}
	f := a.engines.Run(context.Background(), "fake", []ChatMessage{{Role: "user", Content: "hi"}}, "", func(genEvent) {})
	if f.Type != "error" || !strings.Contains(f.Error, "can't find the model") {
		t.Fatalf("%+v", f)
	}
}

func TestEngineModelsAreNamedEngineColonID(t *testing.T) {
	for in, want := range map[string]string{"engine:deepseek-v4.1-flash": "deepseek-v4.1-flash", "engine:Bad ID": "", "gemma4:12b": "", "engine:": ""} {
		id, ok := engineID(in)
		if (want != "") != ok || (ok && id != want) {
			t.Errorf("%q: %q %v", in, id, ok)
		}
	}
}

// waitFinal waits for a generation to end and returns its last event.
func waitFinal(t *testing.T, gen *generation) genEvent {
	t.Helper()
	replay, ch := gen.Subscribe()
	if ch == nil {
		return replay[len(replay)-1]
	}
	for {
		select {
		case ev, ok := <-ch:
			if !ok {
				gen.mu.Lock()
				f := *gen.final
				gen.mu.Unlock()
				return f
			}
			if ev.Type == "done" || ev.Type == "error" || ev.Type == "cancelled" {
				time.Sleep(100 * time.Millisecond) // saveResult runs right after
				return ev
			}
		case <-time.After(30 * time.Second):
			t.Fatal("the reply never finished")
		}
	}
}

func TestAChatWithAnEngineIsSavedWithItsThinking(t *testing.T) {
	a, logPath := engineApp(t, nil)
	gen, err := a.gens.Start(chatReq{Message: "first question", Model: "engine:fake", Thinking: "medium"})
	if err != nil {
		t.Fatal(err)
	}
	if f := waitFinal(t, gen); f.Type != "done" {
		t.Fatalf("%+v", f)
	}
	sess, err := a.sessions.Get(gen.sessionID)
	if err != nil {
		t.Fatal(err)
	}
	if len(sess.Messages) != 2 {
		t.Fatalf("%d messages", len(sess.Messages))
	}
	m := sess.Messages[1]
	if m.Status != "" || m.Content != "Hello there." || m.Thinking != "think hard. " || m.Model != "Fake Flash" || m.ThinkLevel != "medium" ||
		m.Tokens != 4 || m.TokPerSec != 3.82 || !m.Local || m.PromptTokens != 12 {
		t.Fatalf("%+v", m)
	}
	if lastRequest(t, logPath)["reasoning_effort"] != "medium" {
		t.Fatal("the thinking level wasn't sent")
	}

	// Write the last reply again: still two messages, the same question.
	gen2, err := a.gens.Start(chatReq{SessionID: sess.ID, Regenerate: true, Model: "engine:fake", Thinking: "off"})
	if err != nil {
		t.Fatal(err)
	}
	waitFinal(t, gen2)
	sess, _ = a.sessions.Get(sess.ID)
	if len(sess.Messages) != 2 || sess.Messages[0].Content != "first question" || sess.Messages[1].ThinkLevel != "off" || sess.Messages[1].Thinking != "" {
		t.Fatalf("after regenerate: %+v", sess.Messages)
	}
	msgs := lastRequest(t, logPath)["messages"].([]any)
	if len(msgs) != 1 || msgs[0].(map[string]any)["content"] != "first question" {
		t.Fatalf("regenerate sent %v", msgs)
	}

	// A follow-up, then change the first message: what came after it goes.
	gen3, _ := a.gens.Start(chatReq{SessionID: sess.ID, Message: "second", Model: "engine:fake"})
	waitFinal(t, gen3)
	zero := 0
	gen4, err := a.gens.Start(chatReq{SessionID: sess.ID, Message: "first, changed", Model: "engine:fake", EditAt: &zero})
	if err != nil {
		t.Fatal(err)
	}
	waitFinal(t, gen4)
	sess, _ = a.sessions.Get(sess.ID)
	if len(sess.Messages) != 2 || sess.Messages[0].Content != "first, changed" || sess.Title != "first, changed" {
		t.Fatalf("after edit: title %q %+v", sess.Title, sess.Messages)
	}
	one := 1
	if _, err := a.gens.Start(chatReq{SessionID: sess.ID, Message: "x", Model: "engine:fake", EditAt: &one}); err == nil {
		t.Fatal("editing a reply (not your message) should be refused")
	}
}

func TestAChatRenamedByHandKeepsItsTitle(t *testing.T) {
	a, _ := engineApp(t, nil)
	gen, _ := a.gens.Start(chatReq{Message: "hello", Model: "engine:fake"})
	waitFinal(t, gen)
	if _, err := a.sessions.Edit(gen.sessionID, func(s *Session) { s.Title, s.Named = "My title", true }); err != nil {
		t.Fatal(err)
	}
	zero := 0
	gen2, _ := a.gens.Start(chatReq{SessionID: gen.sessionID, Message: "changed", Model: "engine:fake", EditAt: &zero})
	waitFinal(t, gen2)
	if s, _ := a.sessions.Get(gen.sessionID); s.Title != "My title" {
		t.Fatalf("title %q", s.Title)
	}
}

func TestAWindowThatOpensTheChatLaterIsToldWhenThinkingBegan(t *testing.T) {
	gen := &generation{id: "g1", sessionID: "s1", status: "running", subs: map[chan genEvent]struct{}{}}
	gen.emit(genEvent{Type: "delta", Content: "", Thinking: "first thought. "})
	time.Sleep(20 * time.Millisecond)
	gen.emit(genEvent{Type: "delta", Thinking: "second. "})
	replay, ch := gen.Subscribe()
	if ch == nil {
		t.Fatal("a running reply should give a channel")
	}
	var d *genEvent
	for i := range replay {
		if replay[i].Type == "delta" {
			d = &replay[i]
		}
	}
	if d == nil || d.Thinking != "first thought. second. " || d.ThinkAt == "" {
		t.Fatalf("replay: %+v", replay)
	}
	at, err := time.Parse(time.RFC3339Nano, d.ThinkAt)
	if err != nil || time.Since(at) < 20*time.Millisecond || time.Since(at) > 5*time.Second {
		t.Fatalf("think_at %q: %v", d.ThinkAt, err)
	}
	quiet := &generation{id: "g2", status: "running", subs: map[chan genEvent]struct{}{}}
	quiet.emit(genEvent{Type: "delta", Content: "no thinking"})
	if r, _ := quiet.Subscribe(); r[len(r)-1].ThinkAt != "" {
		t.Fatal("a reply that never thought has no think_at")
	}
}
