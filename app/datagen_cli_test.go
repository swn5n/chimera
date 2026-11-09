package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

// askedOllama is a stand-in Ollama with one chat model. It keeps every chat request
// and answers each with reply.
type askedOllama struct {
	srv   *httptest.Server
	mu    sync.Mutex
	reply string
	asked []ollamaAsk
}

type ollamaAsk struct {
	Messages []ChatMessage  `json:"messages"`
	Format   string         `json:"format"`
	Options  map[string]any `json:"options"`
}

func newAskedOllama(t *testing.T) *askedOllama {
	o := &askedOllama{}
	o.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/version":
			w.Write([]byte(`{"version":"0.40.1"}`))
		case "/api/tags":
			w.Write([]byte(`{"models":[{"name":"qwen3:8b","model":"qwen3:8b","size":5200000000,"digest":"abc","details":{"parameter_size":"8.2B"}}]}`))
		case "/api/show":
			w.Write([]byte(`{"capabilities":["completion"],"model_info":{}}`))
		case "/api/chat":
			var a ollamaAsk
			b, _ := io.ReadAll(r.Body)
			if err := json.Unmarshal(b, &a); err != nil {
				t.Errorf("a chat request that isn't JSON: %v", err)
			}
			o.mu.Lock()
			o.asked = append(o.asked, a)
			content, _ := json.Marshal(o.reply)
			o.mu.Unlock()
			fmt.Fprintf(w, "{\"message\":{\"role\":\"assistant\",\"content\":%s},\"done\":false}\n{\"message\":{\"role\":\"assistant\",\"content\":\"\"},\"done\":true,\"done_reason\":\"stop\"}\n", content)
		}
	}))
	t.Cleanup(o.srv.Close)
	return o
}

// answer sets the reply and forgets what was asked before.
func (o *askedOllama) answer(reply string) {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.reply, o.asked = reply, nil
}

func (o *askedOllama) requests() []ollamaAsk {
	o.mu.Lock()
	defer o.mu.Unlock()
	return append([]ollamaAsk(nil), o.asked...)
}

// askedApp is a Chimera in no network, so every step runs on its Ollama.
func askedApp(t *testing.T, o *askedOllama) (*TaskManager, *taskRun) {
	dir := t.TempDir()
	a := &App{dataDir: dir, cfg: Config{DeviceName: "t"}, quit: make(chan struct{})}
	a.tools = NewToolScanner(a)
	a.perf = NewPerfStore(dir)
	a.sys = detectSysInfo()
	a.sessions = NewSessionStore(dir)
	a.ollama = NewOllamaMonitor(a, o.srv.URL)
	a.ollama.check()
	if !a.ollama.Running() {
		t.Fatal("the stand-in Ollama isn't seen")
	}
	return NewTaskManager(a), &taskRun{id: "x", sessionID: "none", kinds: map[string]bool{}}
}

// runMode runs a mode on input and decodes what it prints into out.
func runMode(t *testing.T, mode func(io.Reader, io.Writer) int, input any, out any) {
	t.Helper()
	in, err := json.Marshal(input)
	if err != nil {
		t.Fatal(err)
	}
	var b bytes.Buffer
	if code := mode(bytes.NewReader(in), &b); code != 0 {
		t.Fatalf("exit %d for %s", code, in)
	}
	if err := json.Unmarshal(b.Bytes(), out); err != nil {
		t.Fatalf("%v: %s", err, b.String())
	}
}

type promptRequestJSON struct {
	Messages   []ChatMessage `json:"messages"`
	NeedCtx    int           `json:"need_ctx"`
	Format     string        `json:"format"`
	HelperFits bool          `json:"helper_fits"`
}

// The planner's request, as a real round sends it to a model and as the mode prints it.
func TestPlanRequestIsWhatOnePassSends(t *testing.T) {
	o := newAskedOllama(t)
	tm, run := askedApp(t, o)
	history := []ChatMessage{{Role: "user", Content: "a table, please"}, {Role: "assistant", Content: strings.Repeat("Here it is. ", 400)}}
	for _, c := range []struct {
		name     string
		req      taskReq
		round    int
		base     roundResult
		wantPart string
	}{
		{"round 1", taskReq{Goal: "Make a chair in Blender"}, 1, roundResult{}, "Make a chair in Blender"},
		{"round 1 after a chat", taskReq{Goal: "now add a lamp", history: history}, 1, roundResult{}, "Earlier in this chat (for context only):"},
		{"a later round", taskReq{Goal: "Write a CLI that counts words — «unicode» too"}, 2, roundResult{Text: "```python\nprint(1)\n```", Critique: "It doesn't count."}, "The previous attempt produced this result:\n```python"},
		{"a later round after an empty one", taskReq{Goal: "a poem"}, 3, roundResult{Critique: "It stopped before writing anything."}, "(nothing: the last round's result was empty)"},
		{"a long result is cut", taskReq{Goal: "a long essay"}, 2, roundResult{Text: strings.Repeat("é words ", 3000), Critique: "Shorter."}, "\n…(cut)\n\nWhat still needs work:\nShorter."},
	} {
		o.answer("not a plan")
		if _, ev := tm.onePass(context.Background(), run, c.req, c.round, c.base, synthRoom); ev.Type != "error" {
			t.Fatalf("%s: the stand-in's reply isn't a plan, so the round has to stop: %+v", c.name, ev)
		}
		asked := o.requests()
		if len(asked) != 1 {
			t.Fatalf("%s: %d requests", c.name, len(asked))
		}
		var got promptRequestJSON
		runMode(t, runPlanRequest, map[string]any{"goal": c.req.Goal, "history": c.req.history, "prior": c.base.Text, "critique": c.base.Critique}, &got)
		if len(got.Messages) != 2 || got.Messages[0] != asked[0].Messages[0] || got.Messages[1] != asked[0].Messages[1] {
			t.Fatalf("%s: the mode prints\n%+v\nbut the round sent\n%+v", c.name, got.Messages, asked[0].Messages)
		}
		if !strings.Contains(got.Messages[1].Content, c.wantPart) || got.Messages[0].Content != hydraPlannerPrompt {
			t.Fatalf("%s: %q", c.name, got.Messages[1].Content)
		}
		if got.Format != "json" || asked[0].Format != "json" {
			t.Fatalf("%s: format %q, sent %q", c.name, got.Format, asked[0].Format)
		}
		if got.NeedCtx != historyTokens(got.Messages)+2048 || got.HelperFits != (got.NeedCtx <= helperMaxCtx) {
			t.Fatalf("%s: need_ctx %d, helper_fits %v", c.name, got.NeedCtx, got.HelperFits)
		}
		if n, ok := asked[0].Options["num_ctx"].(float64); !ok || int(n) != ctxBucket(got.NeedCtx, 0) {
			t.Fatalf("%s: num_ctx %v for need_ctx %d", c.name, asked[0].Options["num_ctx"], got.NeedCtx)
		}
	}
}

// The library's references: only those onePass would show, in the words it shows them.
func TestPlanRequestShowsTheUsefulRefs(t *testing.T) {
	refs := []LibEntry{{Title: "Wood material", Kind: "blender", Summary: "Oak.", Content: "mat = 1", Score: 0.3},
		{Title: "Unrelated", Kind: "snippet", Summary: "No.", Content: "x = 2", Score: 0.29}}
	var got promptRequestJSON
	runMode(t, runPlanRequest, map[string]any{"goal": "a table", "refs": refs}, &got)
	want := planRequest(taskReq{Goal: "a table"}, 1, "", "", []LibEntry{refs[0]})
	if got.Messages[1].Content != want.Messages[1].Content || got.Messages[1].Content != "a table"+refsBlock(refs[:1]) {
		t.Fatalf("%q", got.Messages[1].Content)
	}
	if strings.Contains(got.Messages[1].Content, "Unrelated") {
		t.Fatal("a reference under 0.3 was shown")
	}
	var plain promptRequestJSON
	runMode(t, runPlanRequest, map[string]any{"goal": "a table", "refs": nil, "history": nil}, &plain)
	if plain.Messages[1].Content != "a table" {
		t.Fatalf("%q", plain.Messages[1].Content)
	}
}

// The helper gets the plan while it fits the 8K bucket, as onePass's PreferModel says.
func TestPlanRequestSaysWhenTheHelperFits(t *testing.T) {
	system := estimateTokens(hydraPlannerPrompt)
	for _, extra := range []int{-1, 0, 1} {
		// estimateTokens is len/3 + 64: this goal makes need_ctx helperMaxCtx + extra.
		goal := strings.Repeat("x", (helperMaxCtx-2048-system-64+extra)*3)
		var got promptRequestJSON
		runMode(t, runPlanRequest, map[string]any{"goal": goal}, &got)
		pr := planRequest(taskReq{Goal: goal}, 1, "", "", nil)
		if got.NeedCtx != helperMaxCtx+extra || got.HelperFits != (extra <= 0) || got.HelperFits != (pr.PreferModel == helperModel) {
			t.Fatalf("extra %d: need_ctx %d, helper_fits %v, prefer %q", extra, got.NeedCtx, got.HelperFits, pr.PreferModel)
		}
	}
}

// The reviewer's request, as a round sends it and as the mode prints it.
func TestReviewRequestIsWhatAReviewSends(t *testing.T) {
	o := newAskedOllama(t)
	tm, run := askedApp(t, o)
	for _, c := range []struct {
		name, goal, result string
		fits               bool
	}{
		{"short", "Make a chair in Blender", "```python\nimport bpy\n```", true},
		{"too long for the helper", "Write an essay", strings.Repeat("A sentence. ", 1000), false},
		{"cut at 40,000", "Write a book", strings.Repeat("ü", 30000), false},
	} {
		o.answer(`{"done": true, "score": 90, "critique": ""}`)
		tm.review(context.Background(), run, taskReq{Goal: c.goal}, c.result)
		asked := o.requests()
		if len(asked) != 1 {
			t.Fatalf("%s: %d requests", c.name, len(asked))
		}
		var got promptRequestJSON
		runMode(t, runReviewRequest, map[string]any{"goal": c.goal, "result": c.result}, &got)
		if len(got.Messages) != 2 || got.Messages[0] != asked[0].Messages[0] || got.Messages[1] != asked[0].Messages[1] {
			t.Fatalf("%s: the mode prints\n%+v\nbut the review sent\n%+v", c.name, got.Messages, asked[0].Messages)
		}
		if got.Messages[0].Content != hydraReviewPrompt || got.Format != "json" || asked[0].Format != "json" {
			t.Fatalf("%s: %+v", c.name, got)
		}
		if got.NeedCtx != historyTokens(got.Messages)+1024 || got.HelperFits != c.fits || got.HelperFits != (got.NeedCtx <= helperMaxReviewCtx) {
			t.Fatalf("%s: need_ctx %d, helper_fits %v", c.name, got.NeedCtx, got.HelperFits)
		}
	}
}

type planReplyJSON struct {
	OK   bool       `json:"ok"`
	Plan *hydraPlan `json:"plan"`
}

// A planner's reply, read by a real ask and by the mode.
func TestReadReplyReadsAPlanAsTheTaskDoes(t *testing.T) {
	o := newAskedOllama(t)
	tm, run := askedApp(t, o)
	nine := `{"title": "Nine", "kind": "code", "steps": [` + strings.TrimSuffix(strings.Repeat(`{"title": "a", "kind": "code", "instructions": "do"},`, 9), ",") + `]}`
	for _, reply := range []string{
		`{"title": "Chair", "kind": "blender", "summary": "A chair.", "steps": [{"id": "s1", "title": "Seat", "kind": "blender", "instructions": "Build the seat.", "depends_on": []}, {"id": "s2", "title": "Legs", "kind": "blender", "instructions": "Four legs.", "depends_on": ["s1"]}]}`,
		"Here is the plan:\n```json\n" + `{"title": "", "kind": "nonsense", "steps": [{"title": "", "kind": "x"}, {"id": "a", "title": "B", "depends_on": ["a", "later", "s1"]}, {"id": "a", "title": "C", "instructions": "c"}]}` + "\n```\nDone.",
		nine,
		`{"title": "No steps", "steps": []}`,
		`{"title": "Steps of the wrong type", "steps": "one"}`,
		"I can't plan this.",
		"",
		`{"title": "Broken" "steps": [{}]}`,
	} {
		o.answer(reply)
		plan, ev, ok := tm.askPlanner(context.Background(), run, planRequest(taskReq{Goal: "g"}, 1, "", "", nil))
		if ev.Type != "done" {
			t.Fatalf("%q: %+v", reply, ev)
		}
		var got planReplyJSON
		runMode(t, runReadReply, map[string]any{"plan": reply}, &got)
		if got.OK != ok || (got.Plan != nil) != ok {
			t.Fatalf("%q: the mode says %v, the task %v", reply, got.OK, ok)
		}
		if !ok {
			continue
		}
		want := cleanPlan(plan)
		if len(got.Plan.Steps) != len(want.Steps) || got.Plan.Title != want.Title || got.Plan.Kind != want.Kind || got.Plan.Summary != want.Summary {
			t.Fatalf("%q: %+v, want %+v", reply, got.Plan, want)
		}
		for i, s := range want.Steps {
			g := got.Plan.Steps[i]
			if g.ID != s.ID || g.Title != s.Title || g.Kind != s.Kind || g.Instructions != s.Instructions || strings.Join(g.DependsOn, ",") != strings.Join(s.DependsOn, ",") {
				t.Fatalf("%q: step %d is %+v, want %+v", reply, i, g, s)
			}
		}
	}
}

// The printed plan is the planner's part only, with every list a list.
func TestReadReplyPrintsThePlanOnly(t *testing.T) {
	var b bytes.Buffer
	in := `{"plan": "{\"steps\": [{\"title\": \"Only\", \"output\": \"from the planner\", \"model\": \"m\"}]}"}`
	if code := runReadReply(strings.NewReader(in), &b); code != 0 {
		t.Fatal(code)
	}
	const want = `{"ok":true,"plan":{"title":"Long task","kind":"general","summary":"","steps":[{"id":"s1","title":"Only","kind":"general","instructions":"Only","depends_on":[]}]}}` + "\n"
	if b.String() != want {
		t.Fatalf("%s", b.String())
	}
	b.Reset()
	if code := runReadReply(strings.NewReader(`{"plan": "no"}`), &b); code != 0 || b.String() != `{"ok":false,"plan":null}`+"\n" {
		t.Fatalf("%d %s", code, b.String())
	}
	// The plan it prints is one the other modes take as it is.
	var got planReplyJSON
	runMode(t, runReadReply, map[string]any{"plan": `{"steps": [{"title": "A"}, {"title": "B", "depends_on": ["s1"]}]}`}, &got)
	var req workerRequest
	runMode(t, runWorkerRequest, map[string]any{"plan": got.Plan, "index": 1, "outputs": map[string]any{"s1": "done"}}, &req)
	if req.Sid != "s2" || strings.Join(req.Deps, ",") != "s1" {
		t.Fatalf("%+v", req)
	}
}

// A reviewer's reply, read by a real ask and by the mode.
func TestReadReplyReadsAReviewAsTheTaskDoes(t *testing.T) {
	o := newAskedOllama(t)
	tm, run := askedApp(t, o)
	for _, reply := range []string{
		`{"done": true, "score": 95, "critique": ""}`,
		`{"done": false, "score": 40, "critique": "The legs float."}`,
		"Verdict:\n" + `{"done": false, "score": 40, "critique": "Add a seat."}` + "\nThat's all.",
		`{"done": false, "score": 72.5, "critique": "Half marks don't read."}`,
		`{"done": "no", "critique": "a string"}`,
		`{"critique": "only this"}`,
		"Looks good to me.",
		"",
	} {
		o.answer(reply)
		v, ev, ok := tm.askReviewer(context.Background(), run, reviewRequest(taskReq{Goal: "g"}, "r"))
		if ev.Type != "done" {
			t.Fatalf("%q: %+v", reply, ev)
		}
		var got reviewReply
		runMode(t, runReadReply, map[string]any{"review": reply}, &got)
		if got != (reviewReply{OK: ok, Done: v.Done, Score: v.Score, Critique: v.Critique}) {
			t.Fatalf("%q: the mode says %+v, the task %v %+v", reply, got, ok, v)
		}
	}
}

// With names_gate, a step gets the sheet exactly when a real round's step would:
// runStep and the combine add namesBlock, which says the same words around it.
func TestNamesGateIsNamesBlocksRule(t *testing.T) {
	const sheet = "ShaderNodeEmission inputs: Color, Strength"
	a := &App{tools: &ToolScanner{ext: map[string]ToolInfo{"blender": {ID: "blender", Have: true, Path: "/x/blender"}}}, namesOf: "/x/blender", names: sheet}
	step := func(kind string) map[string]any {
		return map[string]any{"title": "One", "kind": kind, "instructions": "Do it."}
	}
	for _, c := range []struct {
		name, kind, goal, title, summary string
	}{
		{"a Blender step", "blender", "a chair", "Chair", "A chair."},
		{"a code step in a Blender task", "code", "write a Blender script", "Shop", ""},
		{"the plan says bpy", "code", "a chair", "Chair", "Uses bpy."},
		{"the title says Blender", "writing", "an essay", "BLENDER notes", ""},
		{"not Blender", "code", "write a web shop", "Shop", "A site."},
		{"blenders are kitchen things", "writing", "compare kitchen blenders", "Blenders", ""},
		{"a kind cleanPlan fixes", "nonsense", "a chair", "Chair", ""},
	} {
		plan := map[string]any{"title": c.title, "kind": "general", "summary": c.summary, "steps": []any{step(c.kind), step("general")}}
		cleaned := cleanPlan(hydraPlan{Title: c.title, Kind: "general", Summary: c.summary, Steps: []hydraStep{{Title: "One", Kind: c.kind, Instructions: "Do it."}, {Title: "One", Kind: "general", Instructions: "Do it."}}})
		block := a.namesBlock(context.Background(), cleaned.Steps[0].Kind, cleaned, c.goal)
		for _, crash := range []any{nil, map[string]any{"step": "s1", "line": 2, "error": "E"}} {
			in := map[string]any{"plan": plan, "index": 0, "outputs": map[string]any{}, "goal": c.goal, "names": sheet, "piece": "p", "crash": crash}
			var bare, gated, ungated workerRequest
			runMode(t, runWorkerRequest, merged(in, map[string]any{"names": ""}), &bare)
			runMode(t, runWorkerRequest, merged(in, map[string]any{"names_gate": true}), &gated)
			runMode(t, runWorkerRequest, merged(in, map[string]any{"names_gate": false}), &ungated)
			if gated.Messages[0].Content != bare.Messages[0].Content+block {
				t.Errorf("%s (crash %v): namesBlock gives %q, the gate added %q", c.name, crash != nil, block, strings.TrimPrefix(gated.Messages[0].Content, bare.Messages[0].Content))
			}
			if ungated.Messages[0].Content != bare.Messages[0].Content+contractNames(sheet) {
				t.Errorf("%s: without the gate the sheet goes to every step", c.name)
			}
			if gated.Messages[1] != bare.Messages[1] || gated.NeedCtx != historyTokens(gated.Messages)+contractRoom {
				t.Errorf("%s: %+v", c.name, gated)
			}
		}
	}
}

func merged(a, b map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range a {
		out[k] = v
	}
	for k, v := range b {
		out[k] = v
	}
	return out
}

func TestDatagenModesFailWithExit2(t *testing.T) {
	for _, c := range []struct {
		name  string
		mode  func(io.Reader, io.Writer) int
		input string
	}{
		{"plan: not JSON", runPlanRequest, "nope"},
		{"plan: history of the wrong type", runPlanRequest, `{"goal": "g", "history": "earlier"}`},
		{"review: not JSON", runReviewRequest, ""},
		{"review: result of the wrong type", runReviewRequest, `{"goal": "g", "result": 3}`},
		{"read: neither", runReadReply, `{}`},
		{"read: both", runReadReply, `{"plan": "{}", "review": "{}"}`},
		{"read: not a string", runReadReply, `{"plan": {"steps": []}}`},
	} {
		var b bytes.Buffer
		if code := c.mode(strings.NewReader(c.input), &b); code != 2 || b.Len() != 0 {
			t.Errorf("%s: exit %d, printed %q", c.name, code, b.String())
		}
	}
}
