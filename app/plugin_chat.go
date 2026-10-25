package main

// A chat message that comes with a picture is a job for a plugin. The app asks
// the hub which plugins fit the request (relevant ones, best rated first), lets
// a model turn the request's words into the plugin's options ("light from the
// left, darker shadow"), and runs the plugin on whichever computer has it. The
// pictures the plugin makes come back into the chat, and the stars you give
// the reply go to that plugin.

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"
)

type pluginChoice struct {
	PluginCandidate
	local bool // installed on this computer; run it here
}

// runPlugin answers a message with a Head. img is nil for a request made of words alone.
func (g *GenManager) runPlugin(gen *generation, req chatReq, text string, img *SessionFile, data []byte, picked *pluginChoice) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	gen.mu.Lock()
	gen.cancelFn = cancel
	gen.mu.Unlock()
	final := g.app.runPluginChat(ctx, gen, req, text, img, data, picked)
	gen.emit(final)
	g.saveResult(gen)
	time.AfterFunc(2*time.Minute, func() {
		g.mu.Lock()
		delete(g.gens, gen.id)
		g.mu.Unlock()
	})
}

func (a *App) runPluginChat(ctx context.Context, gen *generation, req chatReq, text string, img *SessionFile, data []byte, picked *pluginChoice) genEvent {
	var choice pluginChoice
	var why string
	if picked != nil {
		choice = *picked
	} else {
		mime := ""
		if img != nil {
			mime = img.MIME
		}
		var err error
		if choice, why, err = a.choosePlugin(ctx, text, mime); err != nil {
			return genEvent{Type: "error", Error: err.Error()}
		}
	}
	gen.emit(genEvent{Type: "plugin", Plugin: choice.ID, Model: choice.Name})
	opts, optNote := a.pluginOptions(ctx, choice.PluginCandidate, text)
	if note := strings.TrimSpace(why + " " + optNote); note != "" {
		gen.emit(genEvent{Type: "note", Reason: note})
	}
	in := map[string]any{
		"options": opts,
		"request": text,
		"return":  "files", // Chimera reads the files from the output folder
	}
	if img != nil {
		in["image"] = map[string]string{"name": img.Name, "data_base64": base64.StdEncoding.EncodeToString(data)}
	}
	input, _ := json.Marshal(in)

	saved := map[string]bool{} // a reconnect replays the files; keep each once
	emit := func(ev genEvent) {
		if ev.Type == "file" {
			f := ev.raw
			if f == nil || len(f.Data) == 0 || saved[f.SHA256+f.Name] {
				return
			}
			saved[f.SHA256+f.Name] = true
			mime := sniffMIME(f.Name, f.Data) // .glb and the like detect as octet-stream by bytes alone
			if len(choice.Produces) > 0 && !acceptsType(choice.Produces, mime) {
				gen.emit(genEvent{Type: "note", Reason: fmt.Sprintf("Left out %s: %s says it makes %s, not %s.",
					f.Name, choice.Name, strings.Join(choice.Produces, ", "), mime)})
				return
			}
			sf, err := a.sessions.SaveFile(gen.sessionID, f.Name, mime, f.Data)
			if err != nil {
				gen.emit(genEvent{Type: "note", Reason: "Couldn't save " + f.Name + ": " + err.Error()})
				return
			}
			ev = genEvent{Type: "file", File: &sf}
		}
		gen.emit(ev)
	}

	if !choice.local {
		c, err := a.node.client()
		if err == nil {
			sreq := submitReq{Kind: "run_plugin", Plugin: choice.ID, Input: input, Target: req.Target, Private: req.Private,
				Purpose: "Plugin: " + choice.Name}
			sctx, sc := context.WithTimeout(ctx, 30*time.Second)
			id, serr := c.Submit(sctx, sreq)
			sc()
			if serr == nil {
				gen.mu.Lock()
				gen.stepID = id
				gen.mu.Unlock()
				return a.followStep(ctx, c, id, emit)
			}
			if a.tools.Plugin(choice.ID) == nil || req.Target != "" {
				return genEvent{Type: "error", Error: friendlyNetErr(serr, "the hub")}
			}
			gen.emit(genEvent{Type: "note", Reason: "Nobody else could run " + choice.Name + " right now, so it ran on your computer."})
		} else if a.tools.Plugin(choice.ID) == nil {
			return genEvent{Type: "error", Error: err.Error()}
		}
	}
	return a.runPluginHere(ctx, gen, choice.PluginCandidate, input, emit)
}

// runPluginHere runs a plugin on this computer (not through the network).
func (a *App) runPluginHere(ctx context.Context, gen *generation, p PluginCandidate, input []byte, emit func(genEvent)) genEvent {
	cfg := a.config()
	emit(genEvent{Type: "assigned", Device: cfg.DeviceID, DeviceName: cfg.DeviceName, Owner: cfg.Owner, Model: p.Name, Local: true})
	res := a.runPlugin(ctx, "here-"+gen.id, p.ID, input, func(msg string, f float64) {
		if f < 0 {
			f = 0
		}
		emit(genEvent{Type: "status", Reason: msg, Fraction: f})
	})
	switch {
	case res.Cancelled:
		return genEvent{Type: "cancelled", Local: true}
	case !res.OK:
		return genEvent{Type: "error", Error: res.Error}
	}
	if res.Summary == "" {
		res.Summary = fmt.Sprintf("%s made %s.", p.Name, plural(len(res.Files), "file"))
	}
	emit(genEvent{Type: "delta", Content: res.Summary})
	for i := range res.Files {
		emit(genEvent{Type: "file", raw: &res.Files[i]})
	}
	return genEvent{Type: "done", Free: true, Local: true}
}

// choosePlugin picks the plugin for a request: the network's answer when this
// computer is in one (relevant plugins, best rated first), otherwise the most
// relevant plugin installed here.
func (a *App) choosePlugin(ctx context.Context, text, mime string) (pluginChoice, string, error) {
	if a.config().Joined() {
		if c, err := a.node.client(); err == nil {
			sctx, sc := context.WithTimeout(ctx, 10*time.Second)
			cands, err := c.Plugins(sctx, text, mime)
			sc()
			if err == nil && len(cands) > 0 {
				best := cands[0]
				why := ""
				if len(cands) > 1 {
					why = fmt.Sprintf("%d Heads could do this; %s is the best rated.", len(cands), best.Name)
				}
				return pluginChoice{PluginCandidate: best}, why, nil
			}
		}
	}
	local := a.localPluginCandidates(text, mime)
	if len(local) > 0 {
		return pluginChoice{PluginCandidate: local[0], local: true}, "", nil
	}
	if mime == "" {
		return pluginChoice{}, "", errors.New("No Head in the pool can make that yet.")
	}
	return pluginChoice{}, "", errors.New("No Head in the pool can do that with a picture yet. Install one (Settings → Heads) or ask without the picture.")
}

// headForText decides whether a message made of words alone is a job for a Head
// (an image generator, a 3D mesh maker, …) rather than a chat model. It is the
// "should a tool handle this?" check: first, are there Heads online that run
// from words and match the request at all; then a quick yes/no from the fastest
// model, with the Head's own description in front of it, so Heads don't take
// over ordinary conversation ("how does image generation work?" stays a chat).
// With no model to ask, only a very strong word match counts. Returns the Head
// and a note for the reply when one should run.
func (a *App) headForText(ctx context.Context, text string) (*pluginChoice, string) {
	if strings.TrimSpace(text) == "" {
		return nil, ""
	}
	var cands []PluginCandidate
	local := false
	if a.config().Joined() {
		if c, err := a.node.client(); err == nil {
			sctx, sc := context.WithTimeout(ctx, 8*time.Second)
			cands, _ = c.Plugins(sctx, text, "")
			sc()
		}
	}
	if len(cands) == 0 {
		cands, local = a.localPluginCandidates(text, ""), true
	}
	if len(cands) == 0 {
		return nil, ""
	}
	best := cands[0]
	use, asked := a.headGate(ctx, best, text)
	if !asked { // no model around to ask: only a request that plainly names the Head's job
		use = best.Relevance >= 0.75
	}
	if !use {
		return nil, ""
	}
	why := ""
	if len(cands) > 1 {
		why = fmt.Sprintf("%d Heads could do this; %s is the best rated.", len(cands), best.Name)
	}
	return &pluginChoice{PluginCandidate: best, local: local}, why
}

const headGatePrompt = `You decide whether a request should be handled by a tool or by a conversational AI model.
Say yes only when the person is asking for the thing the tool makes or does — not when they are asking a question about it, talking about it, or want text. Reply with JSON only: {"use": true} or {"use": false}.`

var headGateSchema = json.RawMessage(`{"type":"object","properties":{"use":{"type":"boolean"}},"required":["use"]}`)

// headGate asks the fastest model whether the Head should handle the request.
// asked is false when no model could be reached.
func (a *App) headGate(ctx context.Context, p PluginCandidate, text string) (use, asked bool) {
	desc := p.Name + ": " + p.Summary
	if p.WhenToUse != "" {
		desc += "\nUse it when: " + p.WhenToUse
	}
	msgs := []ChatMessage{
		{Role: "system", Content: headGatePrompt},
		{Role: "user", Content: "Tool: " + desc + "\n\nRequest: " + text + "\n\nShould this tool handle the request?"},
	}
	req := submitReq{Messages: msgs, Format: headGateSchema, Prefer: "fastest", NeedCtx: historyTokens(msgs) + 256,
		Options: map[string]any{"temperature": 0}, Purpose: "Deciding whether " + p.Name + " should handle a request"}
	gctx, cancel := context.WithTimeout(ctx, 45*time.Second)
	defer cancel()
	var reply strings.Builder
	final := a.runPrompt(gctx, req, func(ev genEvent) {
		switch ev.Type {
		case "delta":
			reply.WriteString(ev.Content)
		case "replay", "requeued":
			reply.Reset()
			reply.WriteString(ev.Content)
		}
	}, nil)
	if final.Type != "done" {
		return false, false
	}
	var ans struct {
		Use bool `json:"use"`
	}
	if !extractJSON(reply.String(), &ans) {
		return false, true
	}
	return ans.Use, true
}

func (a *App) localPluginCandidates(text, mime string) []PluginCandidate {
	terms := pluginTerms(text, mime != "")
	var out []PluginCandidate
	for _, p := range a.tools.PluginInfos() {
		if !p.Have {
			continue
		}
		if mime != "" && !acceptsType(p.Accepts, mime) {
			continue
		}
		if mime == "" && len(p.Accepts) > 0 && !p.OptionalInput {
			continue
		}
		rel := pluginRelevance(terms, p)
		if len(terms) > 0 && rel < pluginMinRelevance {
			continue
		}
		out = append(out, PluginCandidate{ID: p.ID, Name: p.Name, Version: p.Version, Summary: p.Summary,
			WhenToUse: p.WhenToUse, Accepts: p.Accepts, Produces: p.Produces, Caps: p.Caps, Options: p.Options,
			Devices: 1, Relevance: rel, Score: pluginPriorStars})
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Relevance > out[j].Relevance })
	return out
}

// ---------- options from the request ----------

type optionSchema struct {
	Type        string                  `json:"type"`
	Description string                  `json:"description,omitempty"`
	Enum        []any                   `json:"enum,omitempty"`
	Minimum     *float64                `json:"minimum,omitempty"`
	Maximum     *float64                `json:"maximum,omitempty"`
	Pattern     string                  `json:"pattern,omitempty"`
	Items       *optionSchema           `json:"items,omitempty"`
	Properties  map[string]optionSchema `json:"properties,omitempty"`
}

const optionsPrompt = `You set the options of a tool from what a person asked for. Reply with JSON only, following the schema.
Include only the options the request asks for, in words or numbers; leave everything else out so the tool uses its defaults. An empty object {} is a fine answer.`

// pluginOptions asks a model to turn the request into the plugin's options.
// Anything it can't do (no schema, no model, a bad answer) means the defaults.
func (a *App) pluginOptions(ctx context.Context, p PluginCandidate, text string) (map[string]any, string) {
	out := map[string]any{}
	var schema optionSchema
	if strings.TrimSpace(text) == "" || len(p.Options) == 0 || json.Unmarshal(p.Options, &schema) != nil || len(schema.Properties) == 0 {
		return out, ""
	}
	msgs := []ChatMessage{
		{Role: "system", Content: optionsPrompt},
		{Role: "user", Content: fmt.Sprintf("Tool: %s. %s\nOptions (JSON schema): %s\n\nRequest: %s", p.Name, p.Summary, string(p.Options), text)},
	}
	req := submitReq{Messages: msgs, Format: p.Options, Prefer: "fastest", NeedCtx: historyTokens(msgs) + 1024,
		Options: map[string]any{"temperature": 0}, Purpose: "Choosing options for " + p.Name}
	octx, cancel := context.WithTimeout(ctx, 90*time.Second)
	defer cancel()
	var reply strings.Builder
	final := a.runPrompt(octx, req, func(ev genEvent) {
		switch ev.Type {
		case "delta":
			reply.WriteString(ev.Content)
		case "replay", "requeued":
			reply.Reset()
			reply.WriteString(ev.Content)
		}
	}, nil)
	if final.Type != "done" {
		return out, "(Couldn't read options from your request, so the plugin used its defaults.)"
	}
	var raw map[string]any
	if !extractJSON(reply.String(), &raw) {
		return out, "(Couldn't read options from your request, so the plugin used its defaults.)"
	}
	out = cleanOptions(schema, raw)
	if len(out) == 0 {
		return out, ""
	}
	var parts []string
	for _, k := range sortedKeys(out) {
		parts = append(parts, fmt.Sprintf("%s %v", strings.ReplaceAll(k, "_", " "), out[k]))
	}
	return out, "Options from your request: " + strings.Join(parts, ", ") + "."
}

func sortedKeys(m map[string]any) []string {
	var ks []string
	for k := range m {
		ks = append(ks, k)
	}
	sort.Strings(ks)
	return ks
}

// cleanOptions keeps only options the schema knows, with values it allows.
func cleanOptions(schema optionSchema, raw map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range raw {
		s, ok := schema.Properties[k]
		if !ok {
			continue
		}
		if cv, ok := cleanValue(s, v); ok {
			out[k] = cv
		}
	}
	return out
}

func cleanValue(s optionSchema, v any) (any, bool) {
	inEnum := func(x any) bool {
		if len(s.Enum) == 0 {
			return true
		}
		for _, e := range s.Enum {
			if fmt.Sprint(e) == fmt.Sprint(x) {
				return true
			}
		}
		return false
	}
	switch s.Type {
	case "boolean":
		b, ok := v.(bool)
		return b, ok
	case "number", "integer":
		f, ok := v.(float64)
		if !ok || math.IsNaN(f) || math.IsInf(f, 0) {
			return nil, false
		}
		if s.Minimum != nil && f < *s.Minimum {
			f = *s.Minimum
		}
		if s.Maximum != nil && f > *s.Maximum {
			f = *s.Maximum
		}
		if s.Type == "integer" {
			return math.Round(f), inEnum(math.Round(f))
		}
		return f, inEnum(f)
	case "string":
		str, ok := v.(string)
		if !ok || len(str) > 200 {
			return nil, false
		}
		return str, inEnum(str)
	case "array":
		arr, ok := v.([]any)
		if !ok || s.Items == nil || len(arr) > 20 {
			return nil, false
		}
		var out []any
		for _, x := range arr {
			if cx, ok := cleanValue(*s.Items, x); ok {
				out = append(out, cx)
			}
		}
		return out, len(out) > 0
	}
	return nil, false
}
