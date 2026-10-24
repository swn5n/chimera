package main

// More of the local interface's API: ratings, the shared library, Hydra long
// tasks, speed tests and tool rescans.

import (
	"context"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"
)

func (a *App) moreRoutes(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/feedback", a.handleFeedback)

	mux.HandleFunc("GET /api/library", a.handleLibrary)
	mux.HandleFunc("GET /api/library/export", func(w http.ResponseWriter, r *http.Request) {
		c := a.hubClientOr409(w)
		if c == nil {
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
		defer cancel()
		b, err := c.Raw(ctx, "/v1/library/export")
		if err != nil {
			writeErr(w, apiStatus(err, 502), friendlyNetErr(err, "the hub"))
			return
		}
		w.Header().Set("Content-Type", "application/x-ndjson")
		w.Header().Set("Content-Disposition", `attachment; filename="chimera-ratings-`+time.Now().Format("2006-01-02")+`.jsonl"`)
		_, _ = w.Write(b)
	})
	mux.HandleFunc("GET /api/library/{id}", a.handleLibraryGet)
	mux.HandleFunc("POST /api/library", a.handleLibraryAdd)
	mux.HandleFunc("POST /api/library/{id}/review", a.handleLibraryReview)

	mux.HandleFunc("POST /api/task", a.handleTask)
	mux.HandleFunc("GET /api/task/{id}/stream", func(w http.ResponseWriter, r *http.Request) {
		run := a.tasks.Get(r.PathValue("id"))
		if run == nil {
			writeErr(w, 404, "that task already finished")
			return
		}
		a.streamTask(w, r, run)
	})
	mux.HandleFunc("POST /api/task/{id}/cancel", func(w http.ResponseWriter, r *http.Request) {
		if err := a.tasks.Cancel(r.PathValue("id")); err != nil {
			writeErr(w, 404, err.Error())
			return
		}
		writeJSON(w, 200, map[string]bool{"ok": true})
	})

	mux.HandleFunc("POST /api/network/settings", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			VerifyIdleMin *int `json:"verify_idle_min"`
		}
		if err := readJSON(r, &req, 4096); err != nil {
			writeErr(w, 400, "bad request")
			return
		}
		c := a.hubClientOr409(w)
		if c == nil {
			return
		}
		body := map[string]any{}
		if req.VerifyIdleMin != nil {
			body["verify_idle_min"] = *req.VerifyIdleMin
		}
		ctx, cancel := context.WithTimeout(r.Context(), 6*time.Second)
		defer cancel()
		if err := c.AdminSettings(ctx, body); err != nil {
			writeErr(w, apiStatus(err, 502), friendlyNetErr(err, "the hub"))
			return
		}
		signal1(a.node.beatNow)
		writeJSON(w, 200, map[string]bool{"ok": true})
	})

	mux.HandleFunc("GET /api/discover", func(w http.ResponseWriter, r *http.Request) {
		nets := a.discoverAndMaybeJoin(r.URL.Query().Get("join") == "1")
		out := nets[:0]
		for _, n := range nets {
			if !n.SameApp { // don't list the network we host ourselves
				out = append(out, n)
			}
		}
		if out == nil {
			out = []DiscoveredNet{}
		}
		writeJSON(w, 200, map[string]any{"networks": out, "joined": a.config().Joined()})
	})

	mux.HandleFunc("POST /api/benchmark", a.handleBenchmark)
	mux.HandleFunc("POST /api/tools/rescan", func(w http.ResponseWriter, r *http.Request) {
		a.tools.Kick()
		a.ollama.Refresh()
		writeJSON(w, 200, map[string]bool{"ok": true})
	})
}

// ---------- ratings ----------

type pendingFeedback struct {
	mu     sync.Mutex
	timers map[string]*time.Timer
}

var feedbackTimers = &pendingFeedback{timers: map[string]*time.Timer{}}

func (p *pendingFeedback) stop(key string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if t := p.timers[key]; t != nil {
		t.Stop()
		delete(p.timers, key)
	}
}

func (p *pendingFeedback) later(key string, d time.Duration, fn func()) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if t := p.timers[key]; t != nil {
		t.Stop()
	}
	p.timers[key] = time.AfterFunc(d, func() {
		p.mu.Lock()
		delete(p.timers, key)
		p.mu.Unlock()
		fn()
	})
}

// handleFeedback saves a star rating on a reply. Ratings of 4 or 5 also go to
// the network (with what the person said worked), where the biggest model
// turns the answer into a library entry. 4 and 5 stars wait for the "what
// worked?" note, or send on their own after a few minutes.
func (a *App) handleFeedback(w http.ResponseWriter, r *http.Request) {
	var req struct {
		SessionID string `json:"session_id"`
		Index     int    `json:"index"`
		Rating    int    `json:"rating"`
		Note      string `json:"note"`
		Send      bool   `json:"send"`
	}
	if err := readJSON(r, &req, 1<<16); err != nil || req.Rating < 1 || req.Rating > 5 {
		writeErr(w, 400, "rating must be 1 to 5")
		return
	}
	note := strings.TrimSpace(req.Note)
	var bad string
	_, err := a.sessions.Update(req.SessionID, func(s *Session) {
		if req.Index < 0 || req.Index >= len(s.Messages) {
			bad = "no such message"
			return
		}
		m := &s.Messages[req.Index]
		if m.Role != "assistant" || m.Status != "" || strings.TrimSpace(m.Content) == "" {
			bad = "only finished replies can be rated"
			return
		}
		m.Rating = req.Rating
		if note != "" || req.Send {
			m.RatingNote = truncate(note, 2000)
		}
	})
	if err != nil {
		writeErr(w, 404, "no such chat")
		return
	}
	if bad != "" {
		writeErr(w, 400, bad)
		return
	}
	key := fmt.Sprintf("%s:%d", req.SessionID, req.Index)
	joined := a.config().Joined()
	resp := map[string]any{"ok": true, "joined": joined}
	if !joined {
		writeJSON(w, 200, resp)
		return
	}
	if req.Rating >= 4 && !req.Send {
		// Wait for the note; send anyway if it never comes.
		feedbackTimers.later(key, 3*time.Minute, func() { a.sendFeedback(req.SessionID, req.Index) })
		resp["waiting"] = true
		writeJSON(w, 200, resp)
		return
	}
	feedbackTimers.stop(key)
	queued, sent, ferr := a.sendFeedback(req.SessionID, req.Index)
	resp["sent"], resp["queued"] = sent, queued
	if ferr != nil {
		resp["error"] = ferr.Error()
	}
	writeJSON(w, 200, resp)
}

// sendFeedback sends one rated reply to the network, once.
func (a *App) sendFeedback(sessionID string, idx int) (queued, sent bool, err error) {
	sess, err := a.sessions.Get(sessionID)
	if err != nil || idx < 0 || idx >= len(sess.Messages) {
		return false, false, errors.New("that chat is gone")
	}
	m := sess.Messages[idx]
	if m.RatingSent || m.Rating == 0 {
		return false, m.RatingSent, nil
	}
	prompt := ""
	if m.Task != nil {
		prompt = m.Task.Goal
	} else {
		for i := idx - 1; i >= 0; i-- {
			if sess.Messages[i].Role == "user" {
				prompt = sess.Messages[i].Content
				break
			}
		}
	}
	kind := guessKind(prompt, m.Content)
	if m.Task != nil && m.Task.Kind != "" {
		kind = m.Task.Kind
	}
	c, err := a.node.client()
	if err != nil {
		return false, false, err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	queued, err = c.Feedback(ctx, feedbackReq{Rating: m.Rating, Note: m.RatingNote, Prompt: prompt, Response: m.Content, Model: m.Model, Kind: kind})
	if err != nil {
		log.Printf("sending a rating: %v", err)
		return false, false, errors.New(friendlyNetErr(err, "the hub"))
	}
	_, _ = a.sessions.Update(sessionID, func(s *Session) {
		if idx < len(s.Messages) {
			s.Messages[idx].RatingSent = true
		}
	})
	return queued, true, nil
}

// guessKind labels a reply for the library: blender, code, writing or general.
func guessKind(prompt, response string) string {
	switch {
	case strings.Contains(response, "import bpy"):
		return "blender"
	case strings.Contains(response, "```"):
		return "code"
	case len(response) > 1500 && !strings.Contains(response, "```"):
		return "writing"
	}
	p := strings.ToLower(prompt)
	if strings.Contains(p, "blender") {
		return "blender"
	}
	return "general"
}

// ---------- library ----------

func (a *App) hubClientOr409(w http.ResponseWriter) *HubClient {
	if !a.config().Joined() {
		writeErr(w, 409, "Join or host a network to use the shared library.")
		return nil
	}
	c, err := a.node.client()
	if err != nil {
		writeErr(w, 409, err.Error())
		return nil
	}
	return c
}

func (a *App) handleLibrary(w http.ResponseWriter, r *http.Request) {
	if !a.config().Joined() {
		writeJSON(w, 200, map[string]any{"joined": false, "admin": false, "entries": []LibEntry{}})
		return
	}
	c := a.hubClientOr409(w)
	if c == nil {
		return
	}
	q := r.URL.Query()
	ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
	defer cancel()
	res, err := c.Library(ctx, libQuery{Q: q.Get("q"), Kind: q.Get("kind"), Status: q.Get("status"), Limit: atoiDefault(q.Get("limit"), 100)})
	if err != nil {
		writeErr(w, 502, friendlyNetErr(err, "the hub"))
		return
	}
	if res.Entries == nil {
		res.Entries = []LibEntry{}
	}
	writeJSON(w, 200, map[string]any{"joined": true, "admin": res.Admin, "entries": res.Entries})
}

func (a *App) handleLibraryGet(w http.ResponseWriter, r *http.Request) {
	c := a.hubClientOr409(w)
	if c == nil {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
	defer cancel()
	e, err := c.LibraryGet(ctx, r.PathValue("id"))
	if err != nil {
		writeErr(w, apiStatus(err, 502), friendlyNetErr(err, "the hub"))
		return
	}
	writeJSON(w, 200, e)
}

func (a *App) handleLibraryAdd(w http.ResponseWriter, r *http.Request) {
	var req libAddReq
	if err := readJSON(r, &req, 2<<20); err != nil {
		writeErr(w, 400, "bad request")
		return
	}
	c := a.hubClientOr409(w)
	if c == nil {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
	defer cancel()
	e, err := c.LibraryAdd(ctx, req)
	if err != nil {
		writeErr(w, apiStatus(err, 502), friendlyNetErr(err, "the hub"))
		return
	}
	writeJSON(w, 200, e)
}

func (a *App) handleLibraryReview(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Action string `json:"action"`
		Note   string `json:"note"`
	}
	if err := readJSON(r, &req, 1<<16); err != nil {
		writeErr(w, 400, "bad request")
		return
	}
	c := a.hubClientOr409(w)
	if c == nil {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
	defer cancel()
	out, err := c.LibraryReview(ctx, r.PathValue("id"), req.Action, req.Note)
	if err != nil {
		writeErr(w, apiStatus(err, 502), friendlyNetErr(err, "the hub"))
		return
	}
	signal1(a.node.beatNow) // refresh the library counts
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write(out)
}

func apiStatus(err error, def int) int {
	var ae *apiError
	if errors.As(err, &ae) && ae.Status >= 400 && ae.Status < 500 {
		return ae.Status
	}
	return def
}

// ---------- Hydra long tasks ----------

func (a *App) handleTask(w http.ResponseWriter, r *http.Request) {
	var req taskReq
	if err := readJSON(r, &req, 4<<20); err != nil {
		writeErr(w, 400, "bad request")
		return
	}
	run, err := a.tasks.Start(req)
	if err != nil {
		writeErr(w, 409, err.Error())
		return
	}
	a.streamTask(w, r, run)
}

func (a *App) streamTask(w http.ResponseWriter, r *http.Request, run *taskRun) {
	fl, ok := w.(http.Flusher)
	if !ok {
		writeErr(w, 500, "streaming unsupported")
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.WriteHeader(200)
	replay, ch := run.Subscribe()
	for _, ev := range replay {
		writeSSE(w, "", ev)
	}
	fl.Flush()
	if ch == nil {
		return
	}
	defer run.Unsubscribe(ch)
	ping := time.NewTicker(15 * time.Second)
	defer ping.Stop()
	for {
		select {
		case ev, ok := <-ch:
			if !ok {
				return
			}
			writeSSE(w, "", ev)
			fl.Flush()
		case <-ping.C:
			fmt.Fprint(w, ": ping\n\n")
			fl.Flush()
		case <-r.Context().Done():
			return
		}
	}
}

// ---------- speed test ----------

// handleBenchmark measures a model's real speed on this computer with a short
// reply, so routing and the model list use measured numbers.
func (a *App) handleBenchmark(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Model string `json:"model"`
	}
	if err := readJSON(r, &req, 4096); err != nil || strings.TrimSpace(req.Model) == "" {
		writeErr(w, 400, "which model?")
		return
	}
	if !a.ollama.Running() {
		writeErr(w, 409, "Ollama isn't running")
		return
	}
	var model ModelInfo
	found := false
	for _, m := range a.annotate(a.ollama.State().Models) {
		if normModel(m.Name) == normModel(req.Model) {
			model, found = m, true
		}
	}
	if !found {
		writeErr(w, 404, "that model isn't on this computer")
		return
	}
	if !model.CanChat() {
		writeErr(w, 400, "only chat models can be speed-tested")
		return
	}
	if model.Fits == "too_big" {
		writeErr(w, 409, "This model is too big for this computer's memory; it would spill onto the CPU.")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Minute)
	defer cancel()
	msgs := []ChatMessage{{Role: "user", Content: "In about 150 words, explain why the sky is blue. Plain prose, no lists."}}
	opts := map[string]any{"num_ctx": 2048, "num_predict": 200, "temperature": 0}
	stats, err := a.ollama.Client().ChatStream(ctx, model.Name, msgs, opts, nil, func(string, string) {})
	if err != nil {
		writeErr(w, 502, "The speed test failed: "+err.Error())
		return
	}
	a.perf.Record(model.Name, stats)
	a.notify()
	signal1(a.node.beatNow)
	p := a.perf.Get(model.Name)
	writeJSON(w, 200, map[string]any{"model": model.Name, "tok_s": round1(stats.TokPerSec()), "avg_tok_s": p.TokS,
		"load_s": round1(float64(stats.LoadDuration) / 1e9), "prompt_tok_s": p.PromptTokS})
}
