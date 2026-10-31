package main

// A chat message that comes with a picture is a job for a plugin. The app asks
// the hub which plugins fit the request (relevant ones, best rated first) and
// runs the plugin on whichever computer has it. That computer also lets a model
// of its own turn the request's words into the plugin's options ("light from
// the left, darker shadow"), so asking for someone else's plugin never spins up
// the asker's GPU. The pictures the plugin makes come back into the chat, and
// the stars you give the reply go to that plugin.

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"slices"
	"sort"
	"strings"
	"time"
)

type pluginChoice struct {
	PluginCandidate
	local bool   // installed on this computer; run it here
	why   string // why this one, for the reply's note ("2 Heads could do this; …")
}

// pluginScope is where the request may run, for picking its Head.
func (r chatReq) pluginScope() pluginScope {
	return pluginScope{Target: r.Target, Private: r.Private}
}

// elsewhere says whether scope pins the request to another computer, so a
// Head installed here mustn't stand in.
func (a *App) elsewhere(scope pluginScope) bool {
	return scope.Target != "" && scope.Target != a.config().DeviceID
}

// headRunsHere says whether a Head is installed on this computer and able to
// run here. Only such a Head is the person's own, which may use this
// computer's GPU; an installed copy that can't run here doesn't count.
func (a *App) headRunsHere(id string) bool {
	p := a.tools.Plugin(id)
	return p != nil && p.Probe.Have && p.Err == ""
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
		choice, why = *picked, picked.why
	} else {
		mime := ""
		if img != nil {
			mime = img.MIME
		}
		var err error
		if choice, why, err = a.choosePlugin(ctx, text, mime, req.pluginScope()); err != nil {
			return genEvent{Type: "error", Error: err.Error()}
		}
	}
	gen.emit(genEvent{Type: "plugin", Plugin: choice.ID, Model: choice.Name})
	// The reply shows one note, so each new line is added to it rather than
	// replacing it. Lines from the computer running the plugin go when the step
	// is retried on another one.
	var mine, theirs []string
	showNotes := func() {
		gen.emit(genEvent{Type: "note", Reason: strings.Join(append(append([]string{}, mine...), theirs...), " ")})
	}
	add := func(to *[]string, s string) {
		s = strings.TrimSpace(s)
		if s == "" || slices.Contains(mine, s) || slices.Contains(theirs, s) { // a reconnect replays the worker's note
			return
		}
		*to = append(*to, s)
		showNotes()
	}
	note := func(s string) { add(&mine, s) }
	note(why)
	// No options: the computer that runs the plugin reads them from the request
	// with its own model (withPluginOptions).
	in := map[string]any{
		"request": text,
		"return":  "files", // Chimera reads the files from the output folder
	}
	if img != nil {
		in["image"] = map[string]string{"name": img.Name, "data_base64": base64.StdEncoding.EncodeToString(data)}
	}
	input, _ := json.Marshal(in)

	saved := map[string]bool{} // a reconnect replays the files; keep each once
	emit := func(ev genEvent) {
		switch ev.Type {
		case "note": // from the computer running the plugin: the options it read
			add(&theirs, ev.Reason)
			return
		case "requeued":
			if len(theirs) > 0 {
				theirs = nil
				showNotes()
			}
		case "file":
			f := ev.raw
			if f == nil || len(f.Data) == 0 || saved[f.SHA256+f.Name] {
				return
			}
			saved[f.SHA256+f.Name] = true
			mime := sniffMIME(f.Name, f.Data) // .glb and the like detect as octet-stream by bytes alone
			if len(choice.Produces) > 0 && !acceptsType(choice.Produces, mime) {
				note(fmt.Sprintf("Left out %s: %s says it makes %s, not %s.",
					f.Name, choice.Name, strings.Join(choice.Produces, ", "), mime))
				return
			}
			sf, err := a.sessions.SaveFile(gen.sessionID, f.Name, mime, f.Data)
			if err != nil {
				note("Couldn't save " + f.Name + ": " + err.Error())
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
			if !a.headRunsHere(choice.ID) || req.Target != "" {
				return genEvent{Type: "error", Error: friendlyNetErr(serr, "the hub")}
			}
			note("Nobody else could run " + choice.Name + " right now, so it ran on your computer.")
		} else if !a.headRunsHere(choice.ID) {
			return genEvent{Type: "error", Error: err.Error()}
		}
	}
	return a.runPluginHere(ctx, gen, choice.PluginCandidate, input, emit)
}

// runPluginHere runs a plugin on this computer (not through the network): one
// installed here, so the person's own, and this computer reads its options too.
func (a *App) runPluginHere(ctx context.Context, gen *generation, p PluginCandidate, input []byte, emit func(genEvent)) genEvent {
	cfg := a.config()
	emit(genEvent{Type: "assigned", Device: cfg.DeviceID, DeviceName: cfg.DeviceName, Owner: cfg.Owner, Model: p.Name, Local: true})
	progress := func(msg string, f float64) {
		if f < 0 {
			f = 0
		}
		emit(genEvent{Type: "status", Reason: msg, Fraction: f})
	}
	read := false
	input, optNote, _ := a.withPluginOptions(ctx, p.ID, input, true, func(msg string) { read = true; progress(msg, 0) })
	if optNote != "" {
		emit(genEvent{Type: "note", Reason: optNote})
	}
	if read {
		progress("Starting "+p.Name, 0)
	}
	res := a.runPlugin(ctx, "here-"+gen.id, p.ID, input, progress)
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
// computer is in one (relevant plugins on the devices the request may run on,
// best rated first), otherwise the most relevant plugin installed here.
func (a *App) choosePlugin(ctx context.Context, text, mime string, scope pluginScope) (pluginChoice, string, error) {
	if a.config().Joined() {
		if c, err := a.node.client(); err == nil {
			sctx, sc := context.WithTimeout(ctx, 10*time.Second)
			cands, err := c.Plugins(sctx, text, mime, scope)
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
	if a.elsewhere(scope) {
		return pluginChoice{}, "", errors.New("The computer picked in Run on has no Head that can do that. Pick another one, or Best available.")
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
// when one should run.
func (a *App) headForText(ctx context.Context, text string, scope pluginScope) *pluginChoice {
	if strings.TrimSpace(text) == "" {
		return nil
	}
	var cands []PluginCandidate
	local := false
	if a.config().Joined() {
		if c, err := a.node.client(); err == nil {
			sctx, sc := context.WithTimeout(ctx, 8*time.Second)
			cands, _ = c.Plugins(sctx, text, "", scope)
			sc()
		}
	}
	if len(cands) == 0 && !a.elsewhere(scope) {
		cands, local = a.localPluginCandidates(text, ""), true
	}
	if len(cands) == 0 {
		return nil
	}
	best := cands[0]
	// Someone else's Head is decided on another computer, never this one; a Head
	// that runs here is the person's own, and this computer may help decide.
	mine := local || a.headRunsHere(best.ID)
	use, asked := a.headGate(ctx, best, text, !mine)
	if !asked { // no model around to ask: only a request that plainly names the Head's job
		use = best.Relevance >= 0.75
	}
	if !use {
		return nil
	}
	choice := &pluginChoice{PluginCandidate: best, local: local}
	if len(cands) > 1 {
		choice.why = fmt.Sprintf("%d Heads could do this; %s is the best rated.", len(cands), best.Name)
	}
	return choice
}

const headGatePrompt = `You decide whether a request should be handled by a tool or by a conversational AI model.
Say yes only when the person is asking for the thing the tool makes or does — not when they are asking a question about it, talking about it, or want text. Reply with JSON only: {"use": true} or {"use": false}.`

var headGateSchema = json.RawMessage(`{"type":"object","properties":{"use":{"type":"boolean"}},"required":["use"]}`)

// gateWaitElsewhere is how long the "should a Head do this?" question waits for
// another computer to take it before the words alone decide.
const gateWaitElsewhere = 8 * time.Second

// headGate asks the helper model (Hydra 1.0), or else the fastest model,
// whether the Head should handle the request, on another computer when notHere
// is set. Those may all be busy (a Head job takes minutes), so if none takes
// the question within a few seconds it isn't asked. asked is false when no
// model could be reached.
func (a *App) headGate(ctx context.Context, p PluginCandidate, text string, notHere bool) (use, asked bool) {
	desc := p.Name + ": " + p.Summary
	if p.WhenToUse != "" {
		desc += "\nUse it when: " + p.WhenToUse
	}
	msgs := []ChatMessage{
		{Role: "system", Content: headGatePrompt},
		{Role: "user", Content: "Tool: " + desc + "\n\nRequest: " + text + "\n\nShould this tool handle the request?"},
	}
	req := submitReq{Messages: msgs, Format: headGateSchema, Prefer: "fastest", NeedCtx: historyTokens(msgs) + 256,
		Options: map[string]any{"temperature": 0}, Purpose: "Deciding whether " + p.Name + " should handle a request", NotHere: notHere}
	req.PreferModel = helperFor(req.NeedCtx) // Hydra 1.0 was trained for this check
	gctx, cancel := context.WithTimeout(ctx, 45*time.Second)
	defer cancel()
	var unassigned *time.Timer
	if notHere {
		unassigned = time.AfterFunc(gateWaitElsewhere, cancel)
		defer unassigned.Stop()
	}
	var reply strings.Builder
	final := a.runPrompt(gctx, req, func(ev genEvent) {
		switch ev.Type {
		case "assigned":
			if unassigned != nil {
				unassigned.Stop()
			}
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

const (
	optionsFailed  = "(Couldn't read options from your request, so the Head used its defaults.)"
	optionsNoModel = "(The Head's computer has no model to read options from your request with, so the Head used its defaults.)"
)

// optionsWanted says whether a plugin's input still needs its options, which
// the asker leaves out for the computer that runs the plugin, and returns the
// input's fields and the request's words. Input that already has options
// (from an older Chimera) is run as it is.
func optionsWanted(input []byte) (map[string]json.RawMessage, string, bool) {
	var in map[string]json.RawMessage
	if json.Unmarshal(input, &in) != nil || in == nil {
		return nil, "", false
	}
	if _, has := in["options"]; has {
		return nil, "", false
	}
	var text string
	json.Unmarshal(in["request"], &text)
	return in, text, true
}

// withPluginOptions runs on the computer that runs the plugin, just before it:
// a model here turns the request's words into the plugin's options, which go
// into the input. own says the step is for this computer's owner, who may use
// any model here; for someone else only the models the owner shares count.
// Returns the input to run, a note for the asker and the time it took.
func (a *App) withPluginOptions(ctx context.Context, id string, input []byte, own bool, status func(string)) ([]byte, string, time.Duration) {
	in, text, ok := optionsWanted(input)
	if !ok {
		return input, "", 0
	}
	t0 := time.Now()
	opts, note := map[string]any{}, ""
	if a.headRunsHere(id) && strings.TrimSpace(text) != "" {
		opts, note = a.readPluginOptions(ctx, a.tools.Plugin(id).Manifest, text, own, status)
	}
	in["options"], _ = json.Marshal(opts)
	out, err := json.Marshal(in)
	if err != nil {
		return input, "", 0
	}
	return out, note, time.Since(t0)
}

// fastestChatModel is the chat model that fits its computer and answers
// soonest, the way the hub picks "fastest" (eta: loading it, then its speed).
// The helper model isn't one: reading options isn't one of its jobs.
func fastestChatModel(models []ModelInfo) (ModelInfo, bool) {
	var best ModelInfo
	found := false
	for _, m := range models {
		if !m.ForChat() || m.Fits == "too_big" {
			continue
		}
		if !found || eta(m) < eta(best) {
			best, found = m, true
		}
	}
	return best, found
}

// modelInUse says whether a model is in memory or a step here is using it,
// asking Ollama now rather than trusting the last poll.
func (a *App) modelInUse(m ModelInfo) bool {
	if m.Loaded || (a.node != nil && a.node.runningModel(m.Name)) {
		return true
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	loaded, err := a.ollama.Client().PS(ctx)
	if err != nil {
		return true // not sure: leave it to Ollama's usual timer
	}
	for _, l := range loaded {
		if normModel(l.Name) == normModel(m.Name) || normModel(l.Model) == normModel(m.Name) {
			return true
		}
	}
	return false
}

// readPluginOptions asks the fastest model on this computer to turn the request
// into the plugin's options. Anything it can't do (no schema, no model, a bad
// answer) means the defaults. A model loaded just for this is unloaded straight
// after, so its memory is free for the plugin.
func (a *App) readPluginOptions(ctx context.Context, m PluginManifest, text string, own bool, status func(string)) (map[string]any, string) {
	out := map[string]any{}
	var schema optionSchema
	if len(m.Options) == 0 || json.Unmarshal(m.Options, &schema) != nil || len(schema.Properties) == 0 {
		return out, ""
	}
	if !a.ollama.Running() {
		return out, optionsNoModel
	}
	models := a.annotate(a.ollama.State().Models)
	if !own {
		models = a.node.sharedModels()
	}
	model, ok := fastestChatModel(models)
	if !ok {
		return out, optionsNoModel
	}
	status("Reading the options from the request")
	msgs := []ChatMessage{
		{Role: "system", Content: optionsPrompt},
		{Role: "user", Content: fmt.Sprintf("Tool: %s. %s\nOptions (JSON schema): %s\n\nRequest: %s", m.Name, m.Summary, string(m.Options), text)},
	}
	keep := "15m"
	if !a.modelInUse(model) {
		keep = "0s"
	}
	octx, cancel := context.WithTimeout(ctx, 90*time.Second)
	defer cancel()
	var reply strings.Builder
	stats, err := a.ollama.Client().ChatStreamKeep(octx, model.Name, msgs,
		map[string]any{"temperature": 0, "num_ctx": ctxBucket(historyTokens(msgs)+1024, model.CtxMax)}, m.Options, keep,
		func(c, _ string) { reply.WriteString(c) })
	if err != nil {
		return out, optionsFailed
	}
	a.perf.Record(model.Name, stats)
	var raw map[string]any
	if !extractJSON(reply.String(), &raw) {
		return out, optionsFailed
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
