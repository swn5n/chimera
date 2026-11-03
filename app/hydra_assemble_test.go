package main

import (
	"bytes"
	"encoding/json"
	"slices"
	"strings"
	"testing"
)

// Hand-made plans and pieces: test fixtures, never training data.

func blenderStep(id, title, deps string) hydraStep {
	s := hydraStep{ID: id, Title: title, Kind: "blender", Instructions: "Build it in Blender."}
	if deps != "" {
		s.DependsOn = strings.Split(deps, ",")
	}
	return s
}

func blenderReply(sid, body, extra, provides, uses string) string {
	return "```python\nimport bpy\n" + extra + "\nSETTINGS_" + sid + " = {\"size\": 1}\n\n\ndef build_" + sid + "(ctx):\n" + body +
		"\n\n\nif __name__ == \"__main__\":\n    build_" + sid + "({\"scene\": bpy.context.scene, \"collection\": bpy.context.scene.collection, \"objects\": {}})\n```\n\n" +
		"```handoff\nprovides: " + provides + "\nuses: " + uses + "\nassumed: none\n```\n"
}

func twoStepPlan() hydraPlan {
	plan := cleanPlan(hydraPlan{Title: "A Reading  Corner!", Kind: "blender", Summary: "A floor and a table.", Steps: []hydraStep{
		blenderStep("floor", "The floor", ""), blenderStep("table", "The table", "floor")}})
	plan.Steps[0].Output = blenderReply("s1", "    ctx[\"objects\"][\"floor\"] = 1", "from mathutils import Vector\n", "floor as ctx[\"objects\"][\"floor\"]", "none")
	plan.Steps[1].Output = blenderReply("s2", "    print(ctx[\"objects\"][\"floor\"])", "from mathutils import Euler, Vector\n", "nothing", "floor from s1")
	return plan
}

func seamCodes(j *joinedResult) []string {
	var out []string
	for _, s := range j.Seams {
		out = append(out, s.Code)
	}
	return out
}

func TestJoinBlender(t *testing.T) {
	j := joinPlan(twoStepPlan(), joinAsk{})
	if j.Fallback || len(j.Seams) != 0 {
		t.Fatalf("%v %+v", j.Reasons, j.Seams)
	}
	lines := strings.Split(j.Script, "\n")
	if lines[0] != "# A Reading Corner!" {
		t.Errorf("first line %q", lines[0])
	}
	var imports []string
	for _, l := range lines {
		if strings.HasPrefix(l, "import ") || strings.HasPrefix(l, "from ") {
			imports = append(imports, l)
		}
	}
	if want := []string{"import bpy", "from mathutils import Vector", "from mathutils import Euler"}; !slices.Equal(imports, want) {
		t.Errorf("imports %q", imports)
	}
	last := -1
	for _, x := range []string{"# --- s1: The floor ---", "SETTINGS_s1 = {", "def build_s1", "# --- s2: The table ---", "def build_s2", "def main():",
		`collection = bpy.data.collections.new("chimera_a_reading_corner")`, "    build_s1(ctx)\n    build_s2(ctx)\n    return ctx"} {
		at := strings.Index(j.Script, x)
		if at <= last {
			t.Errorf("%q at %d, after %d", x, at, last)
		}
		last = at
	}
	if strings.Count(j.Script, "__main__") != 1 || !strings.HasSuffix(j.Script, "if __name__ == \"__main__\":\n    ctx = main()\n") {
		t.Errorf("the guard: %q", j.Script[len(j.Script)-80:])
	}
	if j.ScriptKind != "run_blender" || !strings.HasPrefix(j.Text, "# A Reading Corner!\n\n```python\n") ||
		!strings.Contains(j.Text, "Run it with: blender -b --python script.py (what to change") || strings.Contains(j.Text, "provides:") {
		t.Errorf("text %q", j.Text[:60])
	}
	if strings.Contains(j.Script, "_chimera_output") {
		t.Error("no step named an output")
	}
}

func TestJoinOutputRunsOnce(t *testing.T) {
	plan := twoStepPlan()
	plan.Steps[1].Output = strings.Replace(plan.Steps[1].Output, `{"size": 1}`, `{"size": 1, "output": "x.png"}`, 1)
	j := joinPlan(plan, joinAsk{})
	if !strings.Contains(j.Script, "    _chimera_output([SETTINGS_s2])\n") || !strings.Contains(j.Script, chimeraOutputFn) {
		t.Error("no output step")
	}
	spot := j.LineMap.locate(strings.Count(j.Script[:strings.Index(j.Script, "bpy.ops.render.render(")], "\n") + 1)
	if spot.Part != "output" || spot.Function != "_chimera_output" || spot.Repair != "" {
		t.Errorf("%+v", spot)
	}
}

func TestLineMap(t *testing.T) {
	j := joinPlan(twoStepPlan(), joinAsk{})
	find := func(text string) int { return strings.Count(j.Script[:strings.Index(j.Script, text)], "\n") + 1 }
	for text, want := range map[string]lineSpot{
		"import bpy":                {Step: "s1", Title: "The floor", Part: "import", PieceLine: 1, Repair: "s1"},
		"SETTINGS_s2 = ":            {Step: "s2", Title: "The table", Part: "settings", Function: "SETTINGS_s2", PieceLine: 4, Repair: "s2"},
		`print(ctx["objects"]`:      {Step: "s2", Title: "The table", Part: "build", Function: "build_s2", PieceLine: 8, Repair: "s2"},
		"# --- s1: The floor ---":   {Part: "chimera"},
		"scene = bpy.context.scene": {Part: "main", Function: "main"},
	} {
		got := j.LineMap.locate(find(text))
		want.Line = got.Line
		if got != want {
			t.Errorf("%q: %+v, want %+v", text, got, want)
		}
	}
	if got := j.LineMap.locate(0); got.Part != "outside" {
		t.Errorf("%+v", got)
	}
	line := find(`print(ctx["objects"]`)
	source := `    print(ctx["objects"]["floor"])`
	c := j.LineMap.locateCheck(checkAt{Outcome: "failed", Line: line, Error: "KeyError", Source: source}, &j.Script)
	if !c.Definite || c.Repair != "s2" || c.SourceMatches == nil || !*c.SourceMatches {
		t.Errorf("%+v", c)
	}
	c = j.LineMap.locateCheck(checkAt{Outcome: "unsure", Line: line, Source: "other"}, &j.Script)
	if c.Definite || c.Repair != "" || *c.SourceMatches {
		t.Errorf("%+v", c)
	}
}

func TestLineMapJSONIsTheSavedForm(t *testing.T) {
	b, err := json.Marshal(&lineMap{Kind: "blender", Origins: []*lineOrigin{nil, {"s1", "build", "build_s1", 3}, {Part: "main"}}})
	if err != nil {
		t.Fatal(err)
	}
	if want := `{"kind":"blender","titles":null,"origins":[null,["s1","build","build_s1",3],[null,"main",null,null]]}`; string(b) != want {
		t.Errorf("%s", b)
	}
	var m lineMap
	if err := json.Unmarshal(b, &m); err != nil || *m.Origins[1] != (lineOrigin{"s1", "build", "build_s1", 3}) || m.Origins[0] != nil {
		t.Errorf("%v %+v", err, m.Origins)
	}
}

func TestJoinFallsBackOnABrokenPiece(t *testing.T) {
	plan := twoStepPlan()
	plan.Steps[1].Output = "no code here"
	j := joinPlan(plan, joinAsk{})
	if !j.Fallback || j.HasScript || !strings.HasPrefix(j.Reasons[0], "s2: handoff_missing: ") {
		t.Errorf("%+v", j)
	}
	plan = twoStepPlan()
	plan.Steps[0].Status, plan.Steps[1].Status = "failed", "failed"
	if j := joinPlan(plan, joinAsk{}); !j.Fallback || !slices.Equal(j.Reasons, []string{"no step finished"}) {
		t.Errorf("%+v", j)
	}
}

func TestJoinCarriesOnWithoutAFailedStep(t *testing.T) {
	plan := twoStepPlan()
	plan.Steps[0].Status = "failed"
	j := joinPlan(plan, joinAsk{})
	if j.Fallback || !slices.Equal(j.Failed, []string{"s1"}) || j.Notes[0] != "s1 (The floor) failed, so its part is missing." {
		t.Fatalf("%+v", j)
	}
	if !slices.Contains(seamCodes(j), "ctx_key_missing") || !strings.Contains(j.Seams[0].Message, `ctx["objects"]['floor'], which no earlier step registers (the step that should have made it failed)`) {
		t.Errorf("%+v", j.Seams)
	}
}

func TestSeams(t *testing.T) {
	plan := twoStepPlan()
	plan.Steps[1].Output = strings.Replace(plan.Steps[1].Output, "uses: floor from s1", "uses: wall_panel from s1", 1)
	plan.Steps[1].Output = strings.Replace(plan.Steps[1].Output, "from mathutils import Euler, Vector", "from other import Vector", 1)
	plan.Steps[1].Output = strings.Replace(plan.Steps[1].Output, "\ndef build_s2", "\n_s2_X = 1\n\n\ndef build_s2", 1)
	j := joinPlan(plan, joinAsk{})
	if got := seamCodes(j); !slices.Contains(got, "import_conflict") || !slices.Contains(got, "uses_unmatched") {
		t.Fatalf("%+v", j.Seams)
	}
	if !strings.Contains(j.Seams[0].Message, "Vector is from mathutils import Vector in s1 but from other import Vector in s2") {
		t.Errorf("%s", j.Seams[0].Message)
	}
}

func TestUsesNames(t *testing.T) {
	for chunk, want := range map[string][]string{
		"the table_top from s1":                 {"table_top"},
		"`Store.all` and 'plain words' from":    {"Store.all", "plain words"},
		"`ctx[\"objects\"][\"table\"]` from s1": {"table"},
		"run() and helper_fn() and CamelCase":   {"run", "helper_fn", "CamelCase"},
		"src/store.py, data.csv and a floor.":   {"src/store.py", "data.csv"},
		"s1 s2 a b":                             nil,
		"the x_y, the x_y":                      {"x_y"},
	} {
		if got := usesNames(chunk); !slices.Equal(got, want) {
			t.Errorf("%q: %q", chunk, got)
		}
	}
}

func TestWholeWord(t *testing.T) {
	for _, c := range []struct {
		hay, x string
		want   bool
	}{{"a table here", "table", true}, {"tables", "table", false}, {"é_table", "table", false}, {"a-table", "table", true}, {"x", "", true}, {"", "", false}, {"a -b", "-b", false}, {"a-b", "-b", true}} {
		if got := wholeWord(c.hay, c.x); got != c.want {
			t.Errorf("%q %q: %v", c.hay, c.x, got)
		}
	}
}

func scriptPlan(replies ...string) hydraPlan {
	plan := hydraPlan{Title: "A tool", Kind: "code", Summary: "A small tool."}
	for i := range replies {
		plan.Steps = append(plan.Steps, hydraStep{ID: stepName(i), Title: "Part " + stepName(i), Kind: "code", Instructions: "Write it."})
	}
	plan = cleanPlan(plan)
	for i, r := range replies {
		plan.Steps[i].Output = r
	}
	return plan
}

func TestJoinPythonScript(t *testing.T) {
	a := "```python\nimport os\n\ndef helper():\n    return os.name\n```\n\n" + fixtureHandoff
	b := "```python\nimport os\nimport sys\n\ndef main():\n    print(helper(), sys.argv)\n```\n\n```handoff\nprovides: main\nuses: helper from s1\nassumed: none\n```\n"
	j := joinPlan(scriptPlan(a, b), joinAsk{})
	if j.Fallback || len(j.Seams) != 0 {
		t.Fatalf("%v %+v", j.Reasons, j.Seams)
	}
	if j.ScriptKind != "run_python" || !strings.HasSuffix(j.Script, "if __name__ == \"__main__\":\n    main()\n") || strings.Count(j.Script, "import os") != 1 ||
		!strings.Contains(j.Text, "Run it with: python3 script.py.") {
		t.Errorf("%s", j.Script)
	}
	j = joinPlan(scriptPlan(a), joinAsk{})
	if !slices.Contains(seamCodes(j), "missing_entry_point") {
		t.Errorf("%+v", j.Seams)
	}
	j = joinPlan(scriptPlan(b, b), joinAsk{})
	if !slices.Contains(seamCodes(j), "duplicate_name") {
		t.Errorf("%+v", j.Seams)
	}
}

func TestALoneCarriageReturnEndsALine(t *testing.T) {
	j := joinPlan(scriptPlan("```python\ndef main():\n    a = 1\r    b = 2\n```\n\n"+fixtureHandoff, "```python\nimport os\n```\n\n"+fixtureHandoff), joinAsk{})
	if j.Fallback || !strings.Contains(j.Script, "    a = 1\n    b = 2\n") {
		t.Errorf("%v\n%s", j.Reasons, j.Script)
	}
}

func filesPlan(replies ...string) hydraPlan {
	plan := hydraPlan{Title: "A site", Kind: "code", Summary: "src/store.py and more."}
	for i := range replies {
		plan.Steps = append(plan.Steps, hydraStep{ID: stepName(i), Title: "Part", Kind: "code", Instructions: "Write src/store.py."})
	}
	plan = cleanPlan(plan)
	for i, r := range replies {
		plan.Steps[i].Output = r
	}
	return plan
}

func TestJoinFiles(t *testing.T) {
	a := "File: src/store.py\n```python\n\"\"\"Doc.\"\"\"\nimport os\n\nX = 1\n\nif __name__ == \"__main__\":\n    main()\n```\n\n" + fixtureHandoff
	b := "File: src/store.py (part)\n```python\nimport sys\nimport os\n\ndef main():\n    pass\n```\n\nFile: src/app.py\n```python\nfrom store import main, nothing\n```\n\n" + fixtureHandoff
	j := joinPlan(filesPlan(a, b), joinAsk{})
	if j.Fallback || len(j.Files) != 2 {
		t.Fatalf("%v %+v", j.Reasons, j.Files)
	}
	want := "\"\"\"Doc.\"\"\"\nimport os\nimport sys\n\nX = 1\n\n\ndef main():\n    pass\n\n\nif __name__ == \"__main__\":\n    main()"
	if j.Files[0].Body != want || !slices.Equal(j.Files[0].Steps, []string{"s1", "s2"}) {
		t.Errorf("%q %v", j.Files[0].Body, j.Files[0].Steps)
	}
	if !slices.Contains(seamCodes(j), "import_unresolved") || !strings.Contains(j.Text, "File: src/app.py\n```python\nfrom store import main, nothing\n```") {
		t.Errorf("%+v", j.Seams)
	}
}

func TestMergePython(t *testing.T) {
	got, ok := mergePython(nil, []stepBody{{"s1", "import os\n\ndef f():\n    pass"}, {"s2", "import os\nimport sys\n\nX = 1"}})
	if want := "import os\nimport sys\n\n\ndef f():\n    pass\n\n\nX = 1\n"; !ok || got != want {
		t.Errorf("%q", got)
	}
	if _, ok := mergePython(nil, []stepBody{{"s1", "print('runs')"}}); ok {
		t.Error("a part that runs code merged")
	}
	if _, ok := mergePython(nil, []stepBody{{"s1", "def f(:"}}); ok {
		t.Error("a part that doesn't parse merged")
	}
}

func TestPartsThatCantMerge(t *testing.T) {
	a := "File: src/a.txt (part)\n```text\none\n```\n\n" + fixtureHandoff
	b := "File: src/a.txt (part)\n```text\ntwo\n```\n\n" + fixtureHandoff
	j := joinPlan(filesPlan(a, b), joinAsk{})
	if !slices.Contains(seamCodes(j), "part_not_mergeable") || j.Files[0].Body != "one\n\ntwo" {
		t.Errorf("%+v %+v", j.Seams, j.Files)
	}
}

func TestJoinSectionsAndTheEditorHook(t *testing.T) {
	plan := cleanPlan(hydraPlan{Title: "A report", Kind: "writing", Steps: []hydraStep{
		{ID: "a", Title: "One", Kind: "writing", Instructions: "Write."}, {ID: "b", Title: "Two", Kind: "writing", Instructions: "Write."}}})
	plan.Steps[0].Output = "## One\n\nFirst.\n\n" + fixtureHandoff
	plan.Steps[1].Output = "## Two\n\nSecond.\n\n" + fixtureHandoff
	j := joinPlan(plan, joinAsk{})
	if want := "# A report\n\n## One\n\nFirst.\n\n## Two\n\nSecond.\n"; j.Text != want || !j.EditorWanted || j.Edited {
		t.Errorf("%q", j.Text)
	}
	j = joinPlan(plan, joinAsk{Editor: func(*joinedResult) string { return "# Edited  \n\n" }})
	if j.Text != "# Edited\n" || !j.Edited || !strings.HasPrefix(j.RawText, "# A report") {
		t.Errorf("%+v", j)
	}
}

func TestLibraryEntries(t *testing.T) {
	plan := twoStepPlan()
	plan.Steps[0].Status = "library"
	plan.Steps[0].Output = "```python\nimport bpy\nimport math\n\nx = 1\nprint(x)\n```"
	j := joinPlan(plan, joinAsk{})
	if j.Fallback || !j.Pieces[0].Library {
		t.Fatalf("%v", j.Reasons)
	}
	if !strings.Contains(j.Script, "SETTINGS_s1 = {}\n\n\ndef build_s1(ctx):\n    x = 1\n    print(x)\n") && !strings.Contains(j.Script, "SETTINGS_s1 = {}\n\ndef build_s1(ctx):\n") {
		t.Errorf("%s", j.Script)
	}
	plan.Steps[0].Output = "```python\ndef broken(:\n```"
	if j := joinPlan(plan, joinAsk{}); !j.Fallback || !strings.Contains(j.Reasons[0], "the library entry can't be joined") {
		t.Errorf("%v", j.Reasons)
	}
}

func TestAloneScript(t *testing.T) {
	p := validatePiece("```python\n"+fixtureS2+"\n```\n\n"+fixtureHandoff, pieceAsk{Mode: modeBlender, Sid: "s2"})
	got := aloneScript(p, false, "ctx", []string{"s3"})
	if strings.Contains(got, "__main__") || strings.Contains(got, "import bpy\nctx") {
		t.Errorf("%s", got)
	}
	if !strings.HasSuffix(got, "\n\nctx = {\"scene\": bpy.context.scene, \"collection\": bpy.context.scene.collection, \"objects\": {}}\nbuild_s2(ctx)\nbuild_s3(ctx)\n") {
		t.Errorf("%q", got)
	}
	if _, err := pyParse(got); err != nil {
		t.Error(err.msg)
	}
	if got := aloneScript(p, true, "ctx1", nil); !strings.Contains(got, `ctx = ctx1 if isinstance(globals().get("ctx1"), dict)`) {
		t.Errorf("%s", got)
	}
}

func TestPlanSlug(t *testing.T) {
	for title, want := range map[string]string{"A Reading Corner!": "a_reading_corner", "": "project", "!!!": "project", "é": "project",
		strings.Repeat("ab ", 20): "ab_ab_ab_ab_ab_ab_ab_ab_ab_ab_ab_ab_ab_a"} {
		if got := planSlug(title); got != want {
			t.Errorf("%q: %q", title, got)
		}
	}
}

func TestAssembleCommand(t *testing.T) {
	plan := twoStepPlan()
	in, _ := json.Marshal(map[string]any{"plan": plan, "outputs": map[string]string{"floor": plan.Steps[0].Output, "table": plan.Steps[1].Output}, "reject_cut": true})
	var out bytes.Buffer
	if code := runAssemble(bytes.NewReader(in), &out); code != 0 {
		t.Fatalf("exit %d", code)
	}
	var got struct {
		Fallback bool    `json:"fallback"`
		Script   *string `json:"script"`
		Kind     string  `json:"script_kind"`
		LineMap  lineMap `json:"linemap"`
		Pieces   []struct {
			Sid        string `json:"sid"`
			ContractOK bool   `json:"contract_ok"`
		} `json:"pieces"`
	}
	if err := json.Unmarshal(out.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if got.Fallback || got.Script == nil || got.Kind != "run_blender" || len(got.LineMap.Origins) == 0 || len(got.Pieces) != 2 || !got.Pieces[1].ContractOK {
		t.Errorf("%+v", got)
	}
	out.Reset()
	in = []byte(`{"validate": [{"text": "## Hi\n", "mode": "section", "lone": true}, {"text": ""  , "mode": "blender"}]}`)
	if code := runAssemble(bytes.NewReader(in), &out); code != 0 {
		t.Fatalf("exit %d", code)
	}
	var jobs struct {
		Validate []pieceVerdict `json:"validate"`
	}
	if err := json.Unmarshal(out.Bytes(), &jobs); err != nil || len(jobs.Validate) != 2 || !jobs.Validate[0].OK || jobs.Validate[1].Issues[0].Code != "empty" {
		t.Errorf("%v %+v", err, jobs)
	}
	if code := runAssemble(strings.NewReader(`{"validate": [{"text": "x", "mode": "nonsense"}]}`), &bytes.Buffer{}); code != 2 {
		t.Errorf("exit %d", code)
	}
}
