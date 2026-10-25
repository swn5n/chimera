package main

// runPrompt sends one prompt to the network and streams the reply back. If
// nobody is lending (or the hub can't be reached) it runs on this computer's
// best model instead, so a chat always gets an answer when Ollama is here.

import (
	"context"
	"errors"
	"strings"
	"time"
)

// fallbackWorthy says whether a failed submit should run on this computer
// instead, and why (for the note shown with the reply).
func fallbackWorthy(err error, req submitReq) (bool, string) {
	var ae *apiError
	if errors.As(err, &ae) {
		if ae.Status == 402 { // out of credits
			return true, "You're out of credits, so this ran on your computer."
		}
		if ae.Status != 409 {
			return false, ""
		}
		switch {
		case strings.HasPrefix(ae.Msg, "No device lending"):
			return true, "No device in the network had room for this much text, so this ran on your computer."
		case strings.HasPrefix(ae.Msg, "None of your own devices"):
			return true, "None of your devices was lending, so this ran on your computer."
		case strings.HasPrefix(ae.Msg, "No device"):
			if req.Model != "" {
				return true, "Nobody was lending " + req.Model + ", so this ran on your computer."
			}
			return true, "Nobody was lending, so this ran on your computer."
		}
		return false, ""
	}
	return true, "Couldn't reach the network, so this ran on your computer."
}

// bestLocalModel picks the strongest model here that fits and has the needed capabilities.
func (a *App) bestLocalModel(want string, caps []string, prefer string) (ModelInfo, bool) {
	models := a.annotate(a.ollama.State().Models)
	if want != "" {
		for _, m := range models {
			if normModel(m.Name) == normModel(want) {
				return m, true
			}
		}
	}
	var best ModelInfo
	bestScore := -1e18
	for _, m := range models {
		if !m.CanChat() || m.Fits == "too_big" {
			continue
		}
		ok := true
		for _, c := range caps {
			if !m.HasCap(c) {
				ok = false
			}
		}
		if !ok {
			continue
		}
		s := m.ParamsB
		if m.Fits == "tight" {
			s *= 0.6 // works, but close to the memory limit: prefer a roomier model of similar size
		}
		if prefer == "fastest" {
			s = m.Speed()
		}
		if s > bestScore {
			best, bestScore = m, s
		}
	}
	return best, bestScore > -1e18
}

// runPrompt returns the terminal event (done, error or cancelled). stepID is
// told the hub step id so callers can cancel it.
func (a *App) runPrompt(ctx context.Context, req submitReq, emit func(genEvent), stepID func(string)) genEvent {
	note := ""
	if a.config().Joined() {
		c, err := a.node.client()
		if err == nil {
			sctx, cancel := context.WithTimeout(ctx, 15*time.Second)
			id, serr := c.Submit(sctx, req)
			cancel()
			if serr == nil {
				if stepID != nil {
					stepID(id)
				}
				return a.followStep(ctx, c, id, emit)
			}
			ok, why := fallbackWorthy(serr, req)
			if !ok || req.Target != "" {
				return genEvent{Type: "error", Error: friendlyNetErr(serr, "the hub")}
			}
			note = why
		}
	}
	return a.runLocalPrompt(ctx, req, note, emit)
}

func (a *App) followStep(ctx context.Context, c *HubClient, id string, emit func(genEvent)) genEvent {
	// Cancel the hub step as soon as the context is cancelled, even mid-stream:
	// the event stream itself is detached from ctx (so a brief reconnect doesn't
	// drop it), so this watcher is what actually stops the work on cancel.
	done := make(chan struct{})
	defer close(done)
	go func() {
		select {
		case <-ctx.Done():
			cctx, cc := context.WithTimeout(context.Background(), 5*time.Second)
			_ = c.Cancel(cctx, id)
			cc()
		case <-done:
		}
	}()
	var final genEvent
	var lastErr error
	for attempt := 0; attempt < 6; attempt++ {
		if ctx.Err() != nil && final.Type == "" {
			cctx, cc := context.WithTimeout(context.Background(), 5*time.Second)
			_ = c.Cancel(cctx, id)
			cc()
			return genEvent{Type: "cancelled"}
		}
		lastErr = c.Events(context.WithoutCancel(ctx), id, func(ev hubEvent) bool {
			ge := genEvent{Type: ev.Type, Content: ev.Content, Thinking: ev.Thinking, Device: ev.Device,
				DeviceName: ev.DeviceName, Owner: ev.Owner, Model: ev.Model, Reason: ev.Reason, Error: ev.Error,
				Credits: ev.Credits, Free: ev.Free, Fraction: ev.Fraction, raw: ev.File}
			if ev.Stats != nil {
				ge.Tokens, ge.PromptTokens, ge.TokPerSec = ev.Stats.EvalCount, ev.Stats.PromptEvalCount, ev.Stats.TokPerSec()
			}
			if ev.Type == "delta" && attempt > 0 {
				ge.Type = "replay" // a reconnect replays the full text so far
			}
			switch ev.Type {
			case "done", "error", "cancelled":
				final = ge
				return false
			}
			emit(ge)
			return true
		})
		if final.Type != "" {
			return final
		}
		time.Sleep(time.Duration(attempt+1) * time.Second)
	}
	msg := "Lost the connection to the hub while waiting for the reply."
	if lastErr != nil {
		msg = friendlyNetErr(lastErr, "the hub")
	}
	return genEvent{Type: "error", Error: msg}
}

func (a *App) runLocalPrompt(ctx context.Context, req submitReq, note string, emit func(genEvent)) genEvent {
	if !a.ollama.Running() {
		if note != "" {
			return genEvent{Type: "error", Error: strings.TrimSuffix(note, ", so this ran on your computer.") + ", and Ollama isn't running on this computer either."}
		}
		return genEvent{Type: "error", Error: "Ollama isn't running on this computer, and you're not in a network yet."}
	}
	m, ok := a.bestLocalModel(req.Model, req.NeedCaps, req.Prefer)
	if !ok {
		return genEvent{Type: "error", Error: "This computer has no chat model that fits. Download one in Models."}
	}
	cfg := a.config()
	if note != "" {
		if req.Model != "" && normModel(req.Model) != normModel(m.Name) {
			note = strings.TrimSuffix(note, ".") + " with " + m.Name + ", the best model here."
		}
		emit(genEvent{Type: "note", Reason: note})
	}
	emit(genEvent{Type: "assigned", Device: cfg.DeviceID, DeviceName: cfg.DeviceName, Owner: cfg.Owner, Model: m.Name, Local: true})
	opts := map[string]any{"num_ctx": ctxBucket(req.NeedCtx, m.CtxMax)}
	for k, v := range req.Options {
		opts[k] = v
	}
	stats, err := a.ollama.Client().ChatStream(ctx, m.Name, req.Messages, opts, req.Format, func(c, t string) {
		emit(genEvent{Type: "delta", Content: c, Thinking: t})
	})
	if err != nil {
		if ctx.Err() != nil {
			return genEvent{Type: "cancelled", Local: true}
		}
		return genEvent{Type: "error", Error: err.Error()}
	}
	a.perf.Record(m.Name, stats)
	return genEvent{Type: "done", Tokens: stats.EvalCount, PromptTokens: stats.PromptEvalCount, TokPerSec: stats.TokPerSec(), Free: true, Local: true}
}

func historyTokens(msgs []ChatMessage) int {
	n := 0
	for _, m := range msgs {
		n += estimateTokens(m.Content)
	}
	return n
}
