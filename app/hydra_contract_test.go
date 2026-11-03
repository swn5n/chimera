package main

// Test fixtures only, never training data. Most of these are the prototype's own
// checks (worker-model/tests/test_contract_prompt.py), so the two can be read side
// by side; worker-model/tools/check_contract_parity.py compares whole requests.

import (
	"bytes"
	"context"
	"encoding/json"
	"strings"
	"testing"
)

type contractStep struct {
	title, kind, instructions string
	deps                      []string
}

func contractPlanOf(kind string, steps ...contractStep) hydraPlan {
	p := hydraPlan{Title: "P", Kind: kind, Summary: "A project."}
	for i, s := range steps {
		p.Steps = append(p.Steps, hydraStep{ID: stepName(i), Title: s.title, Kind: s.kind, Instructions: s.instructions, DependsOn: s.deps})
	}
	return cleanPlan(p)
}

// threeSteps is a small Blender plan: s3 uses s2.
func threeSteps() hydraPlan {
	return contractPlanOf("blender",
		contractStep{"Floor", "blender", "Make a floor.", nil},
		contractStep{"Side table", "blender", "Build a table.", nil},
		contractStep{"Lamp", "blender", "Put a lamp on it.", []string{"s2"}})
}

const pieceWithHandoff = "Here it is.\n\n```python\nx = 1\n```\n\n```handoff\nprovides: chimera_table\nuses: none\nassumed: it stands at x = 1\n```\n"

func TestStepModes(t *testing.T) {
	code := func(s string) hydraPlan { return contractPlanOf("code", contractStep{"Step", "code", s, nil}) }
	for _, c := range []struct {
		plan hydraPlan
		goal string
		want string
	}{
		{contractPlanOf("code", contractStep{"Scene", "blender", "Build it.", nil}), "", modeBlender},
		{code("Write a bpy script for the desk."), "", modeBlender},
		{code("Write the script."), "Make it in Blender", modeBlender},
		{code("Write count_words(text)."), "", modePythonScript},
		{code("Read data.csv and write report.json."), "", modePythonScript},
		{code("Write src/store.py."), "", modeFiles},
		{code("A page in HTML and JavaScript."), "", modeFiles},
		{code("Write the Go server."), "", modeFiles},
		{code("Let's go over the CLI."), "", modePythonScript}, // "go" isn't Go
		{contractPlanOf("code", contractStep{"Intro", "writing", "Write it.", nil}, contractStep{"Code", "code", "Write main.py", nil}), "", modeSection},
		{contractPlanOf("research", contractStep{"Facts", "research", "Find them.", nil}), "", modeSection},
		{contractPlanOf("general", contractStep{"Do it", "general", "Do it.", nil}), "", modeSection},
	} {
		if got := stepMode(c.plan, 0, c.goal); got != c.want {
			t.Errorf("%q, goal %q: %s, want %s", c.plan.Steps[0].Instructions, c.goal, got, c.want)
		}
	}
}

// Ordinary English words mustn't make a Python plan a files plan, and tasks that
// name no language but imply one mustn't stay Python.
func TestLanguageWordsNeedAProgrammingContext(t *testing.T) {
	for _, text := range []string{
		"Write a script that computes the angular velocity of a spinning top.",
		"A Python bot that can react to chat messages.",
		"A tool that prints a summary and an HTML report to stdout.",
		"Draw a rust-coloured sunset gradient in Python.",
		"A swift Python solver for sudoku.",
		"Rust patches spread where the paint is thin; model their growth over time.",
		"React to each event by logging it.",
		"Express the result as a fraction.",
		"A Python scraper that downloads HTML pages and counts the links.",
		"A script that generates an HTML page from the CSV.",
		"Write a Node class for a linked list.",
		"Go file by file through the folder and count the lines.",
		"Simulate the board game Go with a tiny engine.",
		"Ship it with Express delivery labels.",
		"Build a React-based dashboard",
		"Rust code-golf answers", // a hyphen makes it another word
		"Write a typescripted answer",
		"Use the scalable approach",
		"x.NETwork and my.java.lang",
		"In Expressive terms, describe C",
	} {
		if got := otherLanguage(text); got != "" {
			t.Errorf("%q: names %q", text, got)
		}
	}
	for _, c := range [][2]string{
		{"Add rate limiting to my Express API.", "Express API"},
		{"My Fabric mod crashes on world load.", "Fabric mod"},
		{"Fix the NullPointerException in HomesState.load().", "NullPointerException"},
		{"Write it in Rust with no unsafe code.", "in Rust"},
		{"A Rust program that renames photos.", "Rust program"},
		{"A Swift package for parsing dates.", "Swift package"},
		{"Build a React component for the table.", "React component"},
		{"An Angular service for the API.", "Angular service"},
		{"A single-page HTML/JS app for a scoreboard.", "HTML/JS"},
		{"Build an HTML page with a form.", "HTML page"},
		{"A Node.js script that watches a folder.", "Node.js"},
		{"A Rails app for bookings.", "Rails app"},
		{"Write the tests with Jest.", "with Jest"},
		{"Port it to ASP.NET.", ".NET"},
		{"A bash script that backs up my files.", "bash script"},
		{"Write the Go server.", "Go server"},
		{"Write it in Go.", "in Go"},
		{"A C++ ray tracer.", "C++"},
		{"A Go\u00a0server", "Go\u00a0server"}, // plans are full of no-break spaces
		{"日本語 javascript 日本語", "javascript"},
	} {
		if got := otherLanguage(c[0]); got != c[1] {
			t.Errorf("%q: %q, want %q", c[0], got, c[1])
		}
	}
	// Python's \b knows these are letters; RE2's doesn't.
	for _, text := range []string{"éin Rust", "日javascript", "javascript語", "éGo server"} {
		if got := otherLanguage(text); got != "" {
			t.Errorf("%q: names %q", text, got)
		}
	}
}

func TestBlenderWordsWithoutTheWordBlender(t *testing.T) {
	code := func(s string) string {
		return stepMode(contractPlanOf("code", contractStep{"Step", "code", s, nil}), 0, "")
	}
	for _, text := range []string{"Build a Geometry Nodes setup from Python that scatters rivets.", "For every .blend in the queue folder, set the samples and render frame 1.",
		"A rusty metal material with edge wear from Pointiness.", "Render it with EEVEE.", "Make the mesh with bmesh."} {
		if got := code(text); got != modeBlender {
			t.Errorf("%q: %s", text, got)
		}
	}
	if got := code("List every Eevee evolution."); got != modePythonScript {
		t.Errorf("Eevee is a Pokémon: %s", got)
	}
}

func TestPathsAreSourceFilesAtTheirOwnBoundaries(t *testing.T) {
	text := "Edit src/app/main.py, Dockerfile, my-package.json and x.pyi, not data.csv, a.b.py or /abs/x.go."
	var got []string
	for _, m := range pyMatches(pathRe, text) {
		got = append(got, text[m[0]:m[1]])
	}
	if want := "src/app/main.py Dockerfile package.json x.pyi"; strings.Join(got, " ") != want {
		t.Fatalf("%q, want %q", got, want)
	}
}

func TestPositionalNamesDependenciesAndUsers(t *testing.T) {
	p := cleanPlan(hydraPlan{Kind: "code", Steps: []hydraStep{
		{ID: "alpha", Title: "A", Kind: "code", Instructions: "a"},
		{ID: "beta", Title: "B", Kind: "code", Instructions: "b", DependsOn: []string{"alpha", "alpha"}},
		{ID: "gamma", Title: "C", Kind: "code", Instructions: "c", DependsOn: []string{"beta", "alpha", "x"}}}})
	for _, c := range []struct {
		got  []string
		want string
	}{{depNames(p, 2), "s1 s2"}, {depNames(p, 1), "s1"}, {depNames(p, 0), ""}, {userNames(p, 0), "s2 s3"}, {userNames(p, 2), ""}} {
		if got := strings.Join(c.got, " "); got != c.want {
			t.Errorf("%q, want %q", got, c.want)
		}
	}
}

func TestSystemPromptLayout(t *testing.T) {
	p := threeSteps()
	parts := strings.Split(contractSystem(p, 1, workerAsk{}), "\n\n")
	if len(parts) != 5 {
		t.Fatalf("%d parts: %q", len(parts), parts)
	}
	if want := "You do step s2 of 3."; !strings.Contains(parts[0], want) || !strings.HasPrefix(parts[0], "You are one worker in Chimera: a sub-agent.") {
		t.Errorf("opening: %q", parts[0])
	}
	if parts[1] != "Project: P\nA project." {
		t.Errorf("project: %q", parts[1])
	}
	want := contractPlanHead + "\n" +
		"  s1. Floor [blender]: Make a floor.\n" +
		"→ s2. Side table [blender]: your step, in full below\n" +
		"  s3. Lamp [blender] (uses s2): Put a lamp on it.\n" +
		"Steps that use your piece: s3."
	if parts[2] != want {
		t.Errorf("outline:\n%s", parts[2])
	}
	if parts[3] != contractJoinHead+"\n"+strings.ReplaceAll(rulesBlender, "{sid}", "s2") {
		t.Errorf("rules: %q", parts[3])
	}
	if parts[4] != contractHandoff {
		t.Errorf("handoff: %q", parts[4])
	}
	last := contractSystem(p, 2, workerAsk{})
	for _, want := range []string{"→ s3. Lamp [blender] (uses s2): your step, in full below", contractUsedByNone} {
		if !strings.Contains(last, want) {
			t.Errorf("no %q in\n%s", want, last)
		}
	}
	if !strings.Contains(rulesBlender, `SETTINGS_{sid} = {...}`) || strings.Contains(modeRulesFor(modeBlender, "s4", "blender"), "{sid}") ||
		!strings.Contains(modeRulesFor(modeBlender, "s4", "blender"), `build_s4({"scene": bpy.context.scene,`) {
		t.Error("the rules' own braces have to stay and {sid} has to go")
	}
}

func TestFillTextIsOnePass(t *testing.T) {
	if got := fillText("{title}: {summary} {other}", "title", "{summary}", "summary", "x"); got != "{summary}: x {other}" {
		t.Fatal(got)
	}
}

func TestOtherStepsInstructionsAreCutToOneLine(t *testing.T) {
	p := threeSteps()
	p.Steps[0].Instructions = "Line one.\n\nLine   two.\u00a0" + strings.Repeat("é", 400)
	p.Steps[0].Title = " Floor\n and\ttiles "
	line := strings.Split(contractOutline(p, 1), "\n")[0]
	head := "  s1. Floor and tiles [blender]: "
	if !strings.HasPrefix(line, head+"Line one. Line two. é") {
		t.Fatalf("%q", line)
	}
	if text := []rune(strings.TrimPrefix(line, head)); len(text) != 300 || text[299] != '…' {
		t.Fatalf("%d characters, ending %q", len(text), string(text[299]))
	}
}

func TestLoneStep(t *testing.T) {
	p := contractPlanOf("code", contractStep{"Count", "code", "Write count_words(text).", nil})
	p.Title = "Counter"
	got := contractSystem(p, 0, workerAsk{})
	if want := contractLoneOpening + "\n\nProject: Counter\nA project.\n\n" + contractJoinHead + "\n" + rulesPythonScript; got != want {
		t.Fatalf("%q", got)
	}
	if strings.Contains(got, "handoff") || strings.Contains(got, "The plan (") {
		t.Fatalf("a lone step has no plan and no handoff: %q", got)
	}
	req := contractRequest(p, 0, workerAsk{Room: contractRoom})
	if !req.Lone || req.Messages[1].Content != "Your step, s1: Count\nWrite count_words(text)." {
		t.Fatalf("%+v", req)
	}
}

func TestResearchLineRefsAndNames(t *testing.T) {
	p := contractPlanOf("research", contractStep{"Facts", "research", "Find them.", nil}, contractStep{"Write", "writing", "Write it.", []string{"s1"}})
	if got := contractSystem(p, 0, workerAsk{}); !strings.Contains(got, rulesSection+"\n"+rulesResearch) {
		t.Errorf("no research line in %q", got)
	}
	if got := contractSystem(p, 1, workerAsk{}); strings.Contains(got, rulesResearch) {
		t.Errorf("research line on a writing step: %q", got)
	}
	refs := []LibEntry{{Title: "R", Kind: "lesson", Summary: "S", Content: "C"}}
	got := contractSystem(p, 1, workerAsk{Refs: refs, Names: "Light: energy"})
	want := contractHandoff + refsBlock(refs) + contractNamesHead + "Light: energy"
	if !strings.HasSuffix(got, want) {
		t.Fatalf("%q", got)
	}
	if got := contractSystem(p, 1, workerAsk{Names: ""}); !strings.HasSuffix(got, contractHandoff) {
		t.Fatalf("no sheet, no words about it: %q", got)
	}
}

// The sheet comes with the same words the real tasks' prompt gives it.
func TestNamesHaveNamesBlocksWords(t *testing.T) {
	a := &App{tools: &ToolScanner{ext: map[string]ToolInfo{"blender": {ID: "blender", Have: true, Path: "/x/blender"}}}, namesOf: "/x/blender", names: "Light: energy"}
	if got, want := contractNames("Light: energy"), a.namesBlock(context.Background(), "blender", hydraPlan{}, ""); got != want {
		t.Fatalf("%q\nwant %q", got, want)
	}
}

func TestDependencyParts(t *testing.T) {
	p := threeSteps()
	p.Steps[1].Output, p.Steps[1].Status = pieceWithHandoff, "done"
	want := "From s2, \"Side table\" (you use it):\nIts handoff:\nprovides: chimera_table\nuses: none\nassumed: it stands at x = 1\nHere it is.\n\n```python\nx = 1\n```"
	if got := depPart(p, 1); got != want {
		t.Fatalf("%q", got)
	}
	msg, _ := contractUser(p, 2, workerAsk{})
	if !strings.HasPrefix(msg, "Your step, s3: Lamp\nPut a lamp on it.\n\n"+want) {
		t.Fatalf("%q", msg)
	}

	p.Steps[1].Status = "failed"
	if got := depPart(p, 1); got != "From s2, \"Side table\" (you use it):\n"+contractUserDepFailed {
		t.Fatalf("failed: %q", got)
	}

	p.Steps[1].Output, p.Steps[1].Status = "Here is a script.\n```python\nx\n```", "library"
	if got := depPart(p, 1); !strings.HasSuffix(got, "(you use it):\n"+contractUserDepNoHandoff+"\nHere is a script.\n```python\nx\n```") {
		t.Fatalf("no handoff: %q", got)
	}

	p.Steps[1].Output, p.Steps[1].Status = strings.Repeat("x", 9000)+"\n```handoff\nprovides: a\nuses: none\nassumed: none\n```", "done"
	if got := depPart(p, 1); !strings.HasSuffix(got, "\n"+strings.Repeat("x", 8000)+"\n…(cut)") {
		t.Fatalf("not cut at 8,000 bytes: %d", len(got))
	}
}

// Workers do write the handoff in other forms, and whoever uses their piece should
// see the same thing, with those lines gone from the piece.
func TestNearMissHandoffsAreReadTheSame(t *testing.T) {
	head := "Here it is.\n\n```python\nx = 1\n```\n\n"
	lines := "provides: chimera_table\nuses: none\nassumed: it stands at x = 1"
	block := "```handoff\n" + lines + "\n```\n"
	want := workerHandoff{Provides: "chimera_table", Assumed: "it stands at x = 1"}
	for name, reply := range map[string]string{
		"the contract's":   head + block,
		"plain block":      head + "```\n" + lines + "\n```\n",
		"yaml block":       head + "```yaml\n" + lines + "\n```",
		"left open":        head + "```handoff\n" + lines,
		"plain, left open": head + "```\n" + lines,
		"no fence":         head + lines + "\n",
		"under a label":    head + "**Handoff:**\n\n" + lines + "\n\n",
		"blank lines":      head + strings.ReplaceAll(lines, "\n", "\n\n"),
		"written twice":    head + lines + "\n\n" + block,
		"windows":          strings.ReplaceAll(head+block, "\n", "\r\n"),
		"loud":             head + "```handoff\nPROVIDES : chimera_table \nUses:\tnone.\nassumed: it stands at x = 1\n```",
	} {
		h, blocks := parseHandoff(reply)
		if h == nil || *h != want {
			t.Errorf("%s: %+v", name, h)
			continue
		}
		if got := strings.ReplaceAll(stripHandoff(reply, blocks), "\r", ""); got != strings.TrimSpace(head) {
			t.Errorf("%s: left %q", name, got)
		}
	}
	for name, reply := range map[string]string{
		"no handoff":        "Just text.\n```python\nx = 1\n```",
		"key lines in code": "```python\nprovides: a\nuses: b\nassumed: c\nx = 1\n```",
		"two lines":         "provides: a\nuses: b\n",
		"words after":       "provides: a\nuses: b\nassumed: c\nThat's all.",
	} {
		if h, blocks := parseHandoff(reply); h != nil || len(blocks) != 0 {
			t.Errorf("%s: read %+v", name, h)
		}
	}
	// With other values, lines above the block may be the piece's own words.
	reply := "provides: something else\nuses: a\nassumed: b\n\n" + block
	_, blocks := parseHandoff(reply)
	if got := stripHandoff(reply, blocks); !strings.HasPrefix(got, "provides: something else") {
		t.Errorf("%q", got)
	}
	// Several blocks: the last is read and all go.
	reply = "```handoff\nprovides: first\nuses: none\nassumed: none\n```\n\ntext\n\n" + block
	h, blocks := parseHandoff(reply)
	if h.Provides != "chimera_table" || stripHandoff(reply, blocks) != "text" {
		t.Errorf("%+v, %q", h, stripHandoff(reply, blocks))
	}
}

func TestRoundTwoFindsAStepsPart(t *testing.T) {
	result := "```python\nimport bpy\n\n# --- s1: Floor ---\nSETTINGS_s1 = {}\n\n\ndef build_s1(ctx):\n    _s1_helper(ctx)\n\n\n# --- s2: Side table ---\nSETTINGS_s2 = {\"a\": 1}\n\n\ndef _s2_box():\n    pass\n\n\ndef build_s2(ctx):\n    other_s2_name = build_s2x\n\n\ndef main():\n    ctx = {}\n\n\nif __name__ == \"__main__\":\n    main()\n```\n"
	p := threeSteps()
	got, ok := findPart(result, p, 1, modeBlender)
	if want := "SETTINGS_s2 = {\"a\": 1}\n\n\ndef _s2_box():\n    pass\n\n\ndef build_s2(ctx):\n    other_s2_name = build_s2x"; !ok || got != want {
		t.Fatalf("%v %q", ok, got)
	}

	// The step moved up in this round's plan: it has to be told its new names.
	moved := contractPlanOf("blender", contractStep{"Side  TABLE!", "blender", "Build a table.", nil})
	got, ok = findPart(result, moved, 0, modeBlender)
	if want := "SETTINGS_s1 = {\"a\": 1}\n\n\ndef _s1_box():\n    pass\n\n\ndef build_s1(ctx):\n    other_s2_name = build_s2x"; !ok || got != want {
		t.Fatalf("%v %q", ok, got)
	}

	// A python-script step may define main() itself; only the guard ends its part.
	script := strings.Replace(strings.Replace(result, "# --- s2: Side table ---\n", "# --- s2: Runner ---\n", 1), "Floor", "Base", 1)
	got, ok = findPart(script, contractPlanOf("code", contractStep{"Base", "code", "b", nil}, contractStep{"Runner", "code", "r", nil}), 1, modePythonScript)
	if !ok || !strings.HasSuffix(got, "def main():\n    ctx = {}") {
		t.Fatalf("%v %q", ok, got)
	}

	// A header with nothing under it is still found.
	got, ok = findPart("```python\n# --- s1: Floor ---\n# --- s2: Side table ---\nx\n```", p, 0, modeBlender)
	if !ok || got != "" {
		t.Fatalf("%v %q", ok, got)
	}

	section := "# Project\n\n## Side table\nIt stands.\n\n## Lamp\nIt shines.\n"
	w := contractPlanOf("writing", contractStep{"Lamp", "writing", "w", nil}, contractStep{"Side table", "writing", "w", nil})
	if got, ok = findPart(section, w, 1, modeSection); !ok || got != "## Side table\nIt stands." {
		t.Fatalf("%v %q", ok, got)
	}

	files := "File: src/store.py\n```python\nx = 1\n```\n\n**File:** `src/app.py` (part)\n\n```python\ny = 2\n```\n\nFile: other.py\n```python\nz\n```\n"
	f := contractPlanOf("code", contractStep{"Store", "code", "Write src/store.py and src/app.py.", nil})
	want := "File: src/store.py\n```python\nx = 1\n```\n\nFile: src/app.py (part)\n```python\ny = 2\n```"
	if got, ok = findPart(files, f, 0, modeFiles); !ok || got != want {
		t.Fatalf("%v %q", ok, got)
	}

	long := strings.Repeat("y", 7000)
	if got, ok = findPart(long, p, 0, modeBlender); ok || got != strings.Repeat("y", 6000)+"\n…(cut)" {
		t.Fatalf("%v %d", ok, len(got))
	}
}

func TestRoundTwoParts(t *testing.T) {
	p := threeSteps()
	prev := "```python\n# --- s2: Side table ---\nSETTINGS_s2 = {}\n```"
	req := contractRequest(p, 1, workerAsk{PrevResult: &prev, Critique: "Legs float.", Room: contractRoom})
	want := "Your step, s2: Side table\nBuild a table.\n\nLast round's result for your part:\nSETTINGS_s2 = {}\n\nWhat still needs work:\nLegs float."
	if !req.Round2Matched || req.Messages[1].Content != want {
		t.Fatalf("%+v", req)
	}
	other := "Some other result."
	req = contractRequest(p, 1, workerAsk{PrevResult: &other, Room: contractRoom})
	if req.Round2Matched || !strings.HasSuffix(req.Messages[1].Content, "Last round's result for your part:\nSome other result.\n\nWhat still needs work:\nnone") {
		t.Fatalf("%+v", req)
	}
}

// Results joined with every SETTINGS_ dict at the top still give the step its dict,
// with the comments just above it, and Python's tokens aren't taken for code.
func TestSettingsAtTheTop(t *testing.T) {
	const build = "# --- s1: Floor ---\ndef build_s1(ctx):\n    pass\n"
	for name, c := range map[string][2]string{
		"plain":         {"import bpy\n\n# about it\n\nSETTINGS_s1 = {\n    \"a\": 1,\n}\n\n", "# about it\n\nSETTINGS_s1 = {\n    \"a\": 1,\n}"},
		"annotated":     {"SETTINGS_s1: dict = {}\n", "SETTINGS_s1: dict = {}"},
		"semicolons":    {"x = 1; SETTINGS_s1 = {}\n", "x = 1; SETTINGS_s1 = {}"},
		"in a string":   {"D = \"\"\"\nSETTINGS_s1 = 0\n\"\"\"\n\nSETTINGS_s1 = {\"a\": \"]\"}\n", "SETTINGS_s1 = {\"a\": \"]\"}"},
		"in a comment":  {"# SETTINGS_s1 = 0\nSETTINGS_s1 = {}  # {\n", "# SETTINGS_s1 = 0\nSETTINGS_s1 = {}  # {"},
		"indented":      {"def f():\n    SETTINGS_s1 = 0\n\n\nSETTINGS_s1 = {}\n", "SETTINGS_s1 = {}"},
		"continued":     {"SETTINGS_s1 = \\\n    {\"a\": 1,\n     \"b\": 2}\n", "SETTINGS_s1 = \\\n    {\"a\": 1,\n     \"b\": 2}"},
		"a comparison":  {"SETTINGS_s1 == 1\nSETTINGS_s1 = {}\n", "SETTINGS_s1 = {}"},
		"one-line if":   {"if x: SETTINGS_s1 = 1; y = 2\nSETTINGS_s1 = {}\n", "SETTINGS_s1 = {}"},
		"a tricky line": {"N = 'it\\'s (' + \"a\\\"b[\"\nSETTINGS_s1 = {}\n", "SETTINGS_s1 = {}"},
		"none":          {"", ""},
		"never closes":  {"x = (1,\nSETTINGS_s1 = {}\n", ""},
		"open string":   {"x = \"\"\"\nSETTINGS_s1 = {}\n", ""},
	} {
		if got := settingsOf(c[0]+build, "s1"); got != c[1] {
			t.Errorf("%s: %q, want %q", name, got, c[1])
		}
	}
	got, ok := findPart("```python\nSETTINGS_s1 = {}\n\n"+build+"```", threeSteps(), 0, modeBlender)
	if want := "SETTINGS_s1 = {}\n\n\ndef build_s1(ctx):\n    pass"; !ok || got != want {
		t.Fatalf("%v %q", ok, got)
	}
}

func TestNeedCtxIsRunSteps(t *testing.T) {
	p := threeSteps()
	p.Steps[1].Output, p.Steps[1].Status = pieceWithHandoff, "done"
	req := contractRequest(p, 2, workerAsk{Room: contractRoom})
	if want := historyTokens(req.Messages) + 4096; req.NeedCtx != want {
		t.Fatalf("%d, want %d", req.NeedCtx, want)
	}
	if req.Sid != "s3" || req.N != 3 || req.Mode != modeBlender || req.Lone || strings.Join(req.Deps, ",") != "s2" {
		t.Fatalf("%+v", req)
	}
}

func TestRepairMessage(t *testing.T) {
	p := threeSteps()
	p.Steps[1].Output, p.Steps[1].Status = pieceWithHandoff, "done"
	ask := workerAsk{Room: contractRoom}
	normal := contractRequest(p, 2, ask)
	crash := workerCrash{Step: "s3", Function: "build_s3", PieceLine: 41, Source: `x.inputs["Transmission"]`, Error: "KeyError: 'Transmission'", Runner: "Blender 5.2.2"}
	prev, piece := "the last result", "\n```python\nbroken\n```\n"
	ask.PrevResult, ask.Critique = &prev, "ignored: the piece is here"
	req := contractRepairRequest(p, 2, ask, piece, crash)
	want := normal.Messages[1].Content + "\n\nYour piece crashed when Chimera ran the joined script in Blender 5.2.2:\nline 41 in build_s3: x.inputs[\"Transmission\"]\nKeyError: 'Transmission'\n\nYour piece was:\n```python\nbroken\n```\n\nGive your whole piece again, fixed, in the same shape and with the same names. Running stops at the first error, so check the rest of your piece against Blender 5.2.2's API too."
	if req.Messages[1].Content != want {
		t.Fatalf("%q", req.Messages[1].Content)
	}
	if req.Messages[0] != normal.Messages[0] || req.NeedCtx != historyTokens(req.Messages)+contractRoom {
		t.Fatalf("%+v", req)
	}
	for _, c := range []struct {
		crash workerCrash
		where string
	}{
		{workerCrash{Step: "s2", Part: "helper", Function: "_s2_LEG"}, "_s2_LEG"},
		{workerCrash{Step: "s2", Part: "settings"}, "SETTINGS_s2"},
		{workerCrash{Step: "s3", Part: "import"}, "the imports"},
		{workerCrash{Step: "s3", Part: "build"}, "build_s3"},
		{workerCrash{}, "build_s1"},
	} {
		if got := crashWhere(c.crash); got != c.where {
			t.Errorf("%+v: %s", c.crash, got)
		}
	}
	if got := repairText("x", workerCrash{}); !strings.HasPrefix(got, "Your piece crashed when Chimera ran the joined script in Blender:\nline ? in build_s1: \n") {
		t.Fatalf("%q", got)
	}
	if got := repairText("x", workerCrash{Line: 90}); !strings.Contains(got, "line 90 in") {
		t.Fatalf("%q", got)
	}
}

func runRequest(t *testing.T, input string) (workerRequest, int) {
	t.Helper()
	var out bytes.Buffer
	code := runWorkerRequest(strings.NewReader(input), &out)
	var req workerRequest
	if code == 0 {
		if err := json.Unmarshal(out.Bytes(), &req); err != nil {
			t.Fatal(err)
		}
	}
	return req, code
}

func TestWorkerRequestCommand(t *testing.T) {
	plan := `{"title": "", "kind": "blender", "summary": "S", "steps": [
		{"id": "a", "title": "One", "kind": "blender", "instructions": "x", "depends_on": []},
		{"id": "b", "title": "Two", "kind": "blender", "instructions": "y", "depends_on": ["a", "later"]},
		{"id": "c", "title": "Three", "kind": "blender", "instructions": "z", "depends_on": ["a", "b"]}]}`
	piece, _ := json.Marshal("```handoff\nprovides: p\nuses: none\nassumed: none\n```")
	req, code := runRequest(t, `{"plan": `+plan+`, "index": 2, "goal": "G", "names": "Light: energy", "room": 8192,
		"outputs": {"a": `+string(piece)+`, "b": null}}`)
	if code != 0 {
		t.Fatal(code)
	}
	if req.Sid != "s3" || req.N != 3 || req.Mode != modeBlender || strings.Join(req.Deps, ",") != "s1,s2" || req.NeedCtx != historyTokens(req.Messages)+8192 {
		t.Fatalf("%+v", req)
	}
	if !strings.Contains(req.Messages[0].Content, "Project: Long task\nS") || !strings.HasSuffix(req.Messages[0].Content, contractNamesHead+"Light: energy") {
		t.Fatalf("%q", req.Messages[0].Content)
	}
	if !strings.Contains(req.Messages[1].Content, "provides: p") || !strings.Contains(req.Messages[1].Content, "From s2, \"Two\" (you use it):\n"+contractUserDepFailed) {
		t.Fatalf("%q", req.Messages[1].Content)
	}

	// Each form an output can take. A step left out counts as failed.
	for _, c := range []struct {
		output string
		failed bool
	}{
		{`"out": "x"`, true}, {`"a": null`, true}, {`"a": {"status": "failed"}`, true}, {`"a": {"output": null}`, true}, {`"a": {}`, true},
		{`"a": {"output": "x", "status": "failed"}`, true}, {`"a": "x"`, false}, {`"a": {"output": "x"}`, false}, {`"a": {"output": "x", "status": "library"}`, false},
	} {
		req, code := runRequest(t, `{"plan": `+plan+`, "index": 1, "outputs": {`+c.output+`}}`)
		if failed := strings.Contains(req.Messages[1].Content, contractUserDepFailed); code != 0 || failed != c.failed {
			t.Errorf("%s: exit %d, failed %v", c.output, code, failed)
		}
	}

	// A repair, and its round-2 fields left out.
	req, code = runRequest(t, `{"plan": `+plan+`, "index": 0, "prev_result": "last", "critique": "c", "piece": "the piece", "crash": {"step": "s1", "line": 3, "error": "E"}}`)
	if code != 0 || !strings.Contains(req.Messages[1].Content, "line 3 in build_s1: \nE\n\nYour piece was:\nthe piece\n") || strings.Contains(req.Messages[1].Content, "Last round's") {
		t.Fatalf("%d %+v", code, req)
	}

	req, code = runRequest(t, `{"plan": {"steps": [{"title": "Only"}]}, "index": 0}`)
	if code != 0 || !req.Lone || req.Deps == nil {
		t.Fatalf("%d %+v", code, req)
	}

	for _, bad := range []string{``, `not json`, `{"plan": {"steps": []}}`, `{"plan": ` + plan + `, "index": 3}`, `{"plan": ` + plan + `, "index": -1}`, `{"plan": ` + plan + `, "outputs": {"a": 5}}`} {
		if _, code := runRequest(t, bad); code != 2 {
			t.Errorf("%q: exit %d", bad, code)
		}
	}
}

// deps prints as [], not null: the training data's readers take the JSON as it is.
func TestWorkerRequestKeepsItsKeys(t *testing.T) {
	var out bytes.Buffer
	if code := runWorkerRequest(strings.NewReader(`{"plan": {"steps": [{"title": "Only"}]}}`), &out); code != 0 {
		t.Fatal(code)
	}
	var got map[string]any
	if err := json.Unmarshal(out.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"messages", "need_ctx", "mode", "sid", "n", "lone", "deps", "round2_matched"} {
		if _, ok := got[key]; !ok {
			t.Errorf("no %s in %s", key, out.String())
		}
	}
	if d, ok := got["deps"].([]any); !ok || len(d) != 0 {
		t.Errorf("deps: %v", got["deps"])
	}
}
