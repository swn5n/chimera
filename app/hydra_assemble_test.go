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
	if !strings.Contains(j.Script, "\n    ctx = {\"scene\": scene, \"collection\": collection, \"objects\": {}, \"values\": {}}\n    build_s1(ctx)\n") {
		t.Errorf("main's ctx has both channels, on one line:\n%s", j.Script)
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

	// ctx["values"] is judged as ctx["objects"] is, each channel on its own, until a
	// step writes it in a way whose keys can't be read (the natural update(SETTINGS_s1)
	// would otherwise give its reader a false seam).
	keySeams := func(s1, s2 string) []pieceIssue {
		plan := twoStepPlan()
		plan.Steps[0].Output = blenderReply("s1", "    ctx[\"objects\"][\"floor\"] = 1"+s1, "", "floor as ctx[\"objects\"][\"floor\"]", "none")
		plan.Steps[1].Output = blenderReply("s2", s2+"\n    print(ctx[\"objects\"][\"floor\"])", "", "nothing", "floor from s1")
		var out []pieceIssue
		for _, s := range joinPlan(plan, joinAsk{}).Seams {
			if s.Code == "ctx_key_missing" {
				out = append(out, s)
			}
		}
		return out
	}
	read := "    print(ctx[\"values\"][\"sofa_width\"])"
	if got := keySeams("", read); len(got) != 1 || got[0].Message != `s2 reads ctx["values"]['sofa_width'], which no earlier step registers` || got[0].Step != "s2" {
		t.Errorf("a value nobody hands on: %+v", got)
	}
	if got := keySeams("", "    print(ctx[\"values\"].get(\"sofa_width\", 1))"); len(got) != 1 {
		t.Errorf("get() reads too: %+v", got)
	}
	for name, c := range map[string][2]string{
		"a literal key":          {"\n    ctx[\"values\"][\"sofa_width\"] = SETTINGS_s1[\"size\"]", read},
		"a literal setdefault":   {"\n    ctx[\"values\"].setdefault(\"sofa_width\", 2)", read},
		"update() before":        {"\n    ctx[\"values\"].update(SETTINGS_s1)", read},
		"the whole dict":         {"\n    ctx[\"values\"] = dict(SETTINGS_s1)", read},
		"|=":                     {"\n    ctx[\"values\"] |= SETTINGS_s1", read},
		"a computed key":         {"\n    for k, v in SETTINGS_s1.items():\n        ctx[\"values\"][k] = v", read},
		"a computed setdefault":  {"\n    for k in SETTINGS_s1:\n        ctx[\"values\"].setdefault(k, SETTINGS_s1[k])", read},
		"its own update() first": {"", "    ctx[\"values\"].update(SETTINGS_s2)\n" + read},
		"its own update() after": {"", read + "\n    ctx[\"values\"].update(SETTINGS_s2)"},
		"its own literal write":  {"", "    ctx[\"values\"][\"sofa_width\"] = 1\n" + read},
	} {
		if got := keySeams(c[0], c[1]); len(got) != 0 {
			t.Errorf("%s: %+v", name, got)
		}
	}
	// A write through a name bound to the dict, or straight into ctx.get() or
	// ctx.setdefault(), is a write (ctxBoundWrites): each of these gave the reader a false
	// seam in the real gate. A bound name isn't opaque by itself, which would silence the
	// channel behind every alias (285 of 1,389 stored pieces bind ctx["objects"] to one):
	// only a computed key, update() or |= through it is.
	for name, s1 := range map[string]string{
		"an alias":                  "\n    v = ctx[\"values\"]\n    v[\"sofa_width\"] = 1",
		"a setdefault alias":        "\n    vals = ctx.setdefault(\"values\", {})\n    vals[\"sofa_width\"] = 1",
		"a get alias":               "\n    vals = ctx.get(\"values\", {})\n    vals[\"sofa_width\"] = 1",
		"an annotated alias":        "\n    vals: dict = ctx[\"values\"]\n    vals[\"sofa_width\"] = 1",
		"an alias's setdefault":     "\n    v = ctx[\"values\"]\n    v.setdefault(\"sofa_width\", 1)",
		"a store into setdefault()": "\n    ctx.setdefault(\"values\", {})[\"sofa_width\"] = 1",
		"a store into get()":        "\n    ctx.get(\"values\")[\"sofa_width\"] = 1",
		"an alias bound twice":      "\n    v = ctx[\"values\"]\n    v[\"x\"] = 1\n    v = ctx.setdefault(\"values\", {})\n    v[\"sofa_width\"] = 1",
		"an alias's update()":       "\n    v = ctx[\"values\"]\n    v.update(SETTINGS_s1)",
		"update() on setdefault()":  "\n    ctx.setdefault(\"values\", {}).update(SETTINGS_s1)",
		"an alias's computed key":   "\n    v = ctx[\"values\"]\n    for k in SETTINGS_s1:\n        v[k] = SETTINGS_s1[k]",
		"|= on an alias":            "\n    v = ctx[\"values\"]\n    v |= SETTINGS_s1",
	} {
		if got := keySeams(s1, read); len(got) != 0 {
			t.Errorf("%s: %+v", name, got)
		}
	}
	// ... and nothing more: another key through the alias, a name also bound to something
	// else, a copy, and a read through an alias leave the seam where it was.
	for name, s1 := range map[string]string{
		"another key":             "\n    v = ctx[\"values\"]\n    v[\"sofa_depth\"] = 1",
		"a name bound twice":      "\n    v = ctx[\"values\"]\n    v = {}\n    v[\"sofa_width\"] = 1",
		"a copy":                  "\n    v = dict(ctx[\"values\"])\n    v[\"sofa_width\"] = 1",
		"another channel":         "\n    v = ctx[\"objects\"]\n    v[\"sofa_width\"] = 1",
		"a read through an alias": "\n    v = ctx[\"values\"]\n    print(v[\"sofa_width\"])",
	} {
		if got := keySeams(s1, read); len(got) != 1 {
			t.Errorf("%s: %+v", name, got)
		}
	}
	// The objects channel follows the same names: a step's own write through one covers
	// its own read.
	if got := keySeams("", "    objs = ctx[\"objects\"]\n    objs[\"lamp\"] = 1\n    print(ctx[\"objects\"][\"lamp\"])"); len(got) != 0 {
		t.Errorf("its own alias write: %+v", got)
	}

	// The objects channel is unchanged, and a values write that can't be read doesn't
	// stop it being judged; each channel's seams come in plan order, objects first.
	if got := keySeams("\n    ctx[\"values\"].update(SETTINGS_s1)", "    print(ctx[\"objects\"][\"lamp\"])"); len(got) != 1 || got[0].Message != `s2 reads ctx["objects"]['lamp'], which no earlier step registers` {
		t.Errorf("objects after a values update(): %+v", got)
	}
	if got := keySeams("\n    ctx[\"objects\"].update({})", "    print(ctx[\"objects\"][\"lamp\"])"); len(got) != 0 {
		t.Errorf("objects after an objects update(): %+v", got)
	}
	plan = twoStepPlan()
	plan.Steps[0].Output = blenderReply("s1", "    ctx[\"objects\"][\"floor\"] = ctx[\"values\"][\"rug\"]", "", "floor as ctx[\"objects\"][\"floor\"]", "none")
	plan.Steps[1].Output = blenderReply("s2", "    print(ctx[\"objects\"][\"floor\"], ctx[\"objects\"][\"lamp\"])", "", "nothing", "floor from s1")
	var msgs []string
	for _, s := range joinPlan(plan, joinAsk{}).Seams {
		msgs = append(msgs, s.Message)
	}
	if want := []string{`s2 reads ctx["objects"]['lamp'], which no earlier step registers`, `s1 reads ctx["values"]['rug'], which no earlier step registers`}; !slices.Equal(msgs, want) {
		t.Errorf("%q", msgs)
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
	if !strings.HasSuffix(got, "\n\nctx = {\"scene\": bpy.context.scene, \"collection\": bpy.context.scene.collection, \"objects\": {}, \"values\": {}}\nbuild_s2(ctx)\nbuild_s3(ctx)\n") {
		t.Errorf("%q", got)
	}
	if _, err := pyParse(got); err != nil {
		t.Error(err.msg)
	}
	keep, plain := aloneScript(p, true, "ctx1", nil), aloneScript(p, false, "ctx1", nil)
	if !strings.Contains(keep, `ctx = ctx1 if isinstance(globals().get("ctx1"), dict)`) || !strings.Contains(keep, "\nctx.setdefault(\"values\", {})\nbuild_s2(ctx)\n") {
		t.Errorf("%s", keep)
	}
	// A ctx kept from before ctx["values"] gets it in one line of the tail: the piece's
	// own lines keep their numbers, and a plain alone script its length.
	kl, pl := strings.Split(keep, "\n"), strings.Split(plain, "\n")
	if len(kl) != len(pl)+1 || !slices.Equal(kl[:len(pl)-3], pl[:len(pl)-3]) || pl[len(pl)-3] != "ctx = "+`{"scene": bpy.context.scene, "collection": bpy.context.scene.collection, "objects": {}, "values": {}}` {
		t.Errorf("%d lines kept, %d plain:\n%s", len(kl), len(pl), keep)
	}
	if _, err := pyParse(keep); err != nil {
		t.Error(err.msg)
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

// Hand-made uses lines and the chunks the uses reader gives them (contract question 4, Nov 5): test
// fixtures, never training data. worker-model/tests/test_contract_join.py's USES_LINES holds the same
// table, so the parity tool compares both readers on every line.
func TestUsesChunksGiveEachItemToTheStepAfterIt(t *testing.T) {
	cases := []struct {
		uses string
		want []usesChunk
	}{
		{"table_top from s1, lamp_shade from s2", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, " lamp_shade from "}, {[]string{"s2"}, "s2"}}},
		{"s1: table_top; s2: lamp_shade", []usesChunk{{[]string{"s1"}, "s1: table_top"}, {[]string{"s2"}, " "}, {[]string{"s2"}, "s2: lamp_shade"}}},
		{"table_top (s1), lamp_shade (s2)", []usesChunk{{[]string{"s1"}, "table_top ("}, {[]string{"s1"}, "s1)"}, {[]string{"s2"}, " lamp_shade ("}, {[]string{"s2"}, "s2)"}}},
		{"table_top (from s1, for the height), lamp_shade (from s2, aimed later)", []usesChunk{{[]string{"s1"}, "table_top (from "}, {[]string{"s1"}, "s1, for the height)"}, {[]string{"s2"}, " lamp_shade (from "}, {[]string{"s2"}, "s2, aimed later)"}}},
		{"ctx[\"values\"][\"sofa_width\"] from s1, ctx[\"objects\"][\"sofa\"] from s2", []usesChunk{{[]string{"s1"}, "ctx[\"values\"][\"sofa_width\"] from "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, " ctx[\"objects\"][\"sofa\"] from "}, {[]string{"s2"}, "s2"}}},
		{"s1: ctx[\"values\"][\"sofa_width\"]; s2: ctx[\"objects\"][\"sofa\"]", []usesChunk{{[]string{"s1"}, "s1: ctx[\"values\"][\"sofa_width\"]"}, {[]string{"s2"}, " "}, {[]string{"s2"}, "s2: ctx[\"objects\"][\"sofa\"]"}}},
		{"s1: table_top, lamp_shade from s2", []usesChunk{{[]string{"s1"}, "s1: table_top"}, {[]string{"s2"}, " lamp_shade from "}, {[]string{"s2"}, "s2"}}},
		{"s1: table_top, leg_height", []usesChunk{{[]string{"s1"}, "s1: table_top"}, {[]string{"s1"}, " leg_height"}}},
		{"sofa, coffee_table from s2", []usesChunk{{[]string{"s2"}, "sofa"}, {[]string{"s2"}, " coffee_table from "}, {[]string{"s2"}, "s2"}}},
		{"table_top from s1, lamp_shade from s2 (failed)", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, " lamp_shade from "}, {[]string{"s2"}, "s2 (failed)"}}},
		{"table_top from s1; s2: lamp_shade (failed)", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, " "}, {[]string{"s2"}, "s2: lamp_shade (failed)"}}},
		{"s2: lamp_shade (failed), table_top from s1", []usesChunk{{[]string{"s2"}, "s2: lamp_shade (failed)"}, {[]string{"s1"}, " table_top from "}, {[]string{"s1"}, "s1"}}},
		{"table_top from s1, s2: lamp_shade (failed)", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, " "}, {[]string{"s2"}, "s2: lamp_shade (failed)"}}},
		{"table_top from s1 and lamp_shade from s2", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1 "}, {[]string{"s2"}, "and lamp_shade from "}, {[]string{"s2"}, "s2"}}},
		{"s1: table_top and lamp_shade from s2", []usesChunk{{[]string{"s1"}, "s1: table_top "}, {[]string{"s2"}, "and lamp_shade from "}, {[]string{"s2"}, "s2"}}},
		{"frame_obj from s1 with its leg_objs and slat_objs from s2", []usesChunk{{[]string{"s1"}, "frame_obj from "}, {[]string{"s1"}, "s1 with its leg_objs "}, {[]string{"s2"}, "and slat_objs from "}, {[]string{"s2"}, "s2"}}},
		{"frame_obj from s1 plus slat_objs from s2", []usesChunk{{[]string{"s1"}, "frame_obj from "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, " plus slat_objs from "}, {[]string{"s2"}, "s2"}}},
		{"load_rows() (s1) feeds totals() (s2)", []usesChunk{{[]string{"s1"}, "load_rows() ("}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, ") feeds totals() ("}, {[]string{"s2"}, "s2)"}}},
		{"table_top \u2014 s1, lamp_shade \u2014 s2", []usesChunk{{[]string{"s1"}, "table_top \u2014 "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, " lamp_shade \u2014 "}, {[]string{"s2"}, "s2"}}},
		{"s2 \u2014 make_leg(), leg_count; s1 \u2014 table_top", []usesChunk{{[]string{"s2"}, "s2 \u2014 make_leg()"}, {[]string{"s2"}, " leg_count"}, {[]string{"s1"}, " "}, {[]string{"s1"}, "s1 \u2014 table_top"}}},
		{"the lamp (s2) \u2014 lamp_shade, lamp_cord; the table (s1) \u2014 table_top", []usesChunk{{[]string{"s2"}, "the lamp ("}, {[]string{"s2"}, "s2) \u2014 lamp_shade"}, {[]string{"s2"}, " lamp_cord"}, {[]string{"s1"}, " the table ("}, {[]string{"s1"}, "s1) \u2014 table_top"}}},
		{"keys table_top/leg_height (s1) \u2014 lamp_shade (s2)", []usesChunk{{[]string{"s1"}, "keys table_top/leg_height ("}, {[]string{"s1"}, "s1) "}, {[]string{"s2"}, "\u2014 lamp_shade ("}, {[]string{"s2"}, "s2)"}}},
		{"the outputs of s1 and s2: table_top, lamp_shade", []usesChunk{{[]string{"s1", "s2"}, "the outputs of "}, {[]string{"s1", "s2"}, "s1 and "}, {[]string{"s1", "s2"}, "s2: table_top"}, {[]string{"s1", "s2"}, " lamp_shade"}}},
		{"sofa_body, floor_lamp from s2 and s3", []usesChunk{{[]string{"s2", "s3"}, "sofa_body"}, {[]string{"s2", "s3"}, " floor_lamp from "}, {[]string{"s2", "s3"}, "s2 and "}, {[]string{"s2", "s3"}, "s3"}}},
		{"Acme_Logo from s1/s4", []usesChunk{{[]string{"s1", "s4"}, "Acme_Logo from "}, {[]string{"s1", "s4"}, "s1/s4"}}},
		{"render_engine from s1, s2, s3 (merged)", []usesChunk{{[]string{"s1", "s2", "s3"}, "render_engine from "}, {[]string{"s1", "s2", "s3"}, "s1"}, {[]string{"s1", "s2", "s3"}, " "}, {[]string{"s1", "s2", "s3"}, "s2"}, {[]string{"s1", "s2", "s3"}, " "}, {[]string{"s1", "s2", "s3"}, "s3 (merged)"}}},
		{"key_light_obj, product_camera from s2\u2013s6", []usesChunk{{[]string{"s2", "s3", "s4", "s5", "s6"}, "key_light_obj"}, {[]string{"s2", "s3", "s4", "s5", "s6"}, " product_camera from "}, {[]string{"s2", "s3", "s4", "s5", "s6"}, "s2\u2013"}, {[]string{"s2", "s3", "s4", "s5", "s6"}, "s6"}}},
		{"frame_start from s1-s3", []usesChunk{{[]string{"s1", "s2", "s3"}, "frame_start from "}, {[]string{"s1", "s2", "s3"}, "s1-"}, {[]string{"s1", "s2", "s3"}, "s3"}}},
		{"x from s1\u2013s99", []usesChunk{{[]string{"s1", "s99"}, "x from "}, {[]string{"s1", "s99"}, "s1\u2013"}, {[]string{"s1", "s99"}, "s99"}}},
		{"app.py/db.py (s2, s3), todo.py (s1)", []usesChunk{{[]string{"s2", "s3"}, "app.py/db.py ("}, {[]string{"s2", "s3"}, "s2, "}, {[]string{"s2", "s3"}, "s3)"}, {[]string{"s1"}, " todo.py ("}, {[]string{"s1"}, "s1)"}}},
		{"table_top (s2 reads it) from s1", []usesChunk{{[]string{"s1"}, "table_top "}, {[]string{"s2"}, "("}, {[]string{"s2"}, "s2 reads it)"}, {[]string{"s1"}, " from "}, {[]string{"s1"}, "s1"}}},
		{"base_plate from s1 (s2 failed, so bolt_holes is a stand-in)", []usesChunk{{[]string{"s1"}, "base_plate from "}, {[]string{"s1"}, "s1 "}, {[]string{"s2"}, "("}, {[]string{"s2"}, "s2 failed, so bolt_holes is a stand-in)"}}},
		{"scene_root; s1: table_top", []usesChunk{{[]string{"s1"}, " "}, {[]string{"s1"}, "s1: table_top"}}},
		{"table_top, leg_height; lamp_shade from s2", []usesChunk{{[]string{"s2"}, " lamp_shade from "}, {[]string{"s2"}, "s2"}}},
		{"camera from s4, island, rocks", []usesChunk{{[]string{"s4"}, "camera from "}, {[]string{"s4"}, "s4"}}},
		{"Priya Shah's email from s3's guide", []usesChunk{{[]string{"s3"}, "Priya Shah's email from "}, {[]string{"s3"}, "s3's guide"}}},
		{"src/s2/legs.py from s2, top.py from s1", []usesChunk{{[]string{"s2"}, "src/s2/legs.py from "}, {[]string{"s2"}, "s2"}, {[]string{"s1"}, " top.py from "}, {[]string{"s1"}, "s1"}}},
		{"s1.variables, s2.furniture", []usesChunk{{[]string{"s1"}, "s1.variables"}, {[]string{"s2"}, " "}, {[]string{"s2"}, "s2.furniture"}}},
		{"{\"s1\": [\"table_top\"], \"s2\": [\"lamp_shade\"]}", []usesChunk{{[]string{"s1"}, "{"}, {[]string{"s1"}, "\"s1\": [\"table_top\"], "}, {[]string{"s2"}, "\"s2\": [\"lamp_shade\"]}"}}},
		{"s1's Store, s2's search()", []usesChunk{{[]string{"s1"}, "s1's Store"}, {[]string{"s2"}, " "}, {[]string{"s2"}, "s2's search()"}}},
		{"table_top from s1\u0662", []usesChunk{{[]string{"s1\u0662"}, "table_top from "}, {[]string{"s1\u0662"}, "s1\u0662"}}},
		{"s1:\u00a0table_top; s2\uff1alamp_shade", []usesChunk{{[]string{"s1"}, "s1:\u00a0table_top"}, {[]string{"s2"}, " "}, {[]string{"s2"}, "s2\uff1alamp_shade"}}},
		{"table_top from step s1 and lamp_shade from step s2", []usesChunk{{[]string{"s1"}, "table_top from step "}, {[]string{"s1"}, "s1 "}, {[]string{"s2"}, "and lamp_shade from step "}, {[]string{"s2"}, "s2"}}},
		{"none", []usesChunk{}},
		{"", []usesChunk{}},
		// forms seen on the stored records
		{"settings from s1; island, fridge from s2; key_light from s3", []usesChunk{{[]string{"s1"}, "settings from "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, " island"}, {[]string{"s2"}, " fridge from "}, {[]string{"s2"}, "s2"}, {[]string{"s3"}, " key_light from "}, {[]string{"s3"}, "s3"}}},
		{"keys table_top, leg_height, lamp_shade from s2 and s3", []usesChunk{{[]string{"s2", "s3"}, "keys table_top"}, {[]string{"s2", "s3"}, " leg_height"}, {[]string{"s2", "s3"}, " lamp_shade from "}, {[]string{"s2", "s3"}, "s2 and "}, {[]string{"s2", "s3"}, "s3"}}},
		{"variables (sofa_width, sofa_depth from s1); objects sofa_body, sofa_legs from s2", []usesChunk{{[]string{"s1"}, "variables (sofa_width, sofa_depth from "}, {[]string{"s1"}, "s1)"}, {[]string{"s2"}, " objects sofa_body"}, {[]string{"s2"}, " sofa_legs from "}, {[]string{"s2"}, "s2"}}},
		{"table_top (from s1, for aiming the camera), lamp_shade (from s2, for the light)", []usesChunk{{[]string{"s1"}, "table_top (from "}, {[]string{"s1"}, "s1, for aiming the camera)"}, {[]string{"s2"}, " lamp_shade (from "}, {[]string{"s2"}, "s2, for the light)"}}},
		{"base_plate, bolt_holes from s1 and s2 (s2 failed)", []usesChunk{{[]string{"s1", "s2"}, "base_plate"}, {[]string{"s1", "s2"}, " bolt_holes from "}, {[]string{"s1", "s2"}, "s1 and "}, {[]string{"s1", "s2"}, "s2 "}, {[]string{"s2"}, "("}, {[]string{"s2"}, "s2 failed)"}}},
		// known misses, pinned as they read: made_here goes to s2, SETTINGS_s1 is no id (round 8's seams judge it
		// against s1 all the same), "s2's" joins the group, leg_height stays with s1, table_top is s2's, and an id in
		// a path is still an id (round 8 reads "frame_obj from s1 with its leg_objs plus slat_objs from s2" right)
		{"table_top from s1, made_here (own), lamp_shade from s2", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, " made_here (own)"}, {[]string{"s2"}, " lamp_shade from "}, {[]string{"s2"}, "s2"}}},
		{"SETTINGS_s1 values, lamp_shade from s2", []usesChunk{{[]string{"s2"}, "SETTINGS_s1 values"}, {[]string{"s2"}, " lamp_shade from "}, {[]string{"s2"}, "s2"}}},
		{"table_top from s1 and s2's lamp_shade", []usesChunk{{[]string{"s1", "s2"}, "table_top from "}, {[]string{"s1", "s2"}, "s1 and "}, {[]string{"s1", "s2"}, "s2's lamp_shade"}}},
		{"s1: table_top, leg_height, lamp_shade from s2", []usesChunk{{[]string{"s1"}, "s1: table_top"}, {[]string{"s1"}, " leg_height"}, {[]string{"s2"}, " lamp_shade from "}, {[]string{"s2"}, "s2"}}},
		{"s1, s2: table_top", []usesChunk{{[]string{"s1"}, "s1"}, {[]string{"s2"}, " "}, {[]string{"s2"}, "s2: table_top"}}},
		{"src/s2/legs.py from s1", []usesChunk{{[]string{"s2"}, "src/s2"}, {[]string{"s1"}, "/legs.py from "}, {[]string{"s1"}, "s1"}}},
		// more forms: open ids, arrows, leads, marks, quoted and bracketed ids, ranges past usesRangeMax
		{"s2's slat_objs and frame_obj from s1", []usesChunk{{[]string{"s2"}, "s2's slat_objs "}, {[]string{"s1"}, "and frame_obj from "}, {[]string{"s1"}, "s1"}}},
		{"table_top from s1 (see s2 for lamp_shade)", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1 "}, {[]string{"s2"}, "(see "}, {[]string{"s2"}, "s2 for lamp_shade)"}}},
		{"Acme_Logo (s1) -> logo_mat", []usesChunk{{[]string{"s1"}, "Acme_Logo ("}, {[]string{"s1"}, "s1) -> logo_mat"}}},
		{"s1 => table_top, s2 -> lamp_shade", []usesChunk{{[]string{"s1"}, "s1 => table_top"}, {[]string{"s2"}, " "}, {[]string{"s2"}, "s2 -> lamp_shade"}}},
		{"from s1: table_top; from s2: lamp_shade", []usesChunk{{[]string{"s1"}, "from "}, {[]string{"s1"}, "s1: table_top"}, {[]string{"s2"}, " from "}, {[]string{"s2"}, "s2: lamp_shade"}}},
		{"Steps s1 and s2: table_top, lamp_shade", []usesChunk{{[]string{"s1", "s2"}, "Steps "}, {[]string{"s1", "s2"}, "s1 and "}, {[]string{"s1", "s2"}, "s2: table_top"}, {[]string{"s1", "s2"}, " lamp_shade"}}},
		{"**s1**: table_top; **s2**: lamp_shade", []usesChunk{{[]string{"s1"}, "**"}, {[]string{"s1"}, "s1**: table_top"}, {[]string{"s2"}, " **"}, {[]string{"s2"}, "s2**: lamp_shade"}}},
		{"table_top from s1, s2: lamp_shade (failed), leg_height from s3", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, " "}, {[]string{"s2"}, "s2: lamp_shade (failed)"}, {[]string{"s3"}, " leg_height from "}, {[]string{"s3"}, "s3"}}},
		{"s4 (failed): lamp_shade", []usesChunk{{[]string{"s4"}, "s4 (failed): lamp_shade"}}},
		{"table_top from s1, s2, s3 (merged), lamp_shade from s4", []usesChunk{{[]string{"s1", "s2", "s3"}, "table_top from "}, {[]string{"s1", "s2", "s3"}, "s1"}, {[]string{"s1", "s2", "s3"}, " "}, {[]string{"s1", "s2", "s3"}, "s2"}, {[]string{"s1", "s2", "s3"}, " "}, {[]string{"s1", "s2", "s3"}, "s3 (merged)"}, {[]string{"s4"}, " lamp_shade from "}, {[]string{"s4"}, "s4"}}},
		{"x from s1\u2013s12", []usesChunk{{[]string{"s1", "s12"}, "x from "}, {[]string{"s1", "s12"}, "s1\u2013"}, {[]string{"s1", "s12"}, "s12"}}},
		{"x from s3-s1", []usesChunk{{[]string{"s3", "s1"}, "x from "}, {[]string{"s3", "s1"}, "s3-"}, {[]string{"s3", "s1"}, "s1"}}},
		// round 8 (Nov 5, the user's yes): "<id>'s name" and "<id> name" pairs after a lead with no name read forward
		// (rule 5b), not after "from", not when a run isn't a pair, and not with a name between a pair and the next id
		// (there lamp_obj, and shade_obj, go to s2); the items around a pair item read as round 7 reads them (rug_mesh is
		// no step's, sofa_obj is s3's and then s1's)
		{"Uses s1's table_top with s2's lamp_shade", []usesChunk{{[]string{"s1"}, "Uses "}, {[]string{"s1"}, "s1's table_top with "}, {[]string{"s2"}, "s2's lamp_shade"}}},
		{"the s1 table_top with the s2 lamp_shade", []usesChunk{{[]string{"s1"}, "the "}, {[]string{"s1"}, "s1 table_top with the "}, {[]string{"s2"}, "s2 lamp_shade"}}},
		{"Combines s1 table_top & s2 lamp_shade", []usesChunk{{[]string{"s1"}, "Combines "}, {[]string{"s1"}, "s1 table_top & "}, {[]string{"s2"}, "s2 lamp_shade"}}},
		{"uses s1's table_top as the base for s2's lamp_shade", []usesChunk{{[]string{"s1"}, "uses "}, {[]string{"s1"}, "s1's table_top as the base for "}, {[]string{"s2"}, "s2's lamp_shade"}}},
		{"Uses s1's table_top with s2's lamp_shade, rug_mesh", []usesChunk{{[]string{"s1"}, "Uses "}, {[]string{"s1"}, "s1's table_top with "}, {[]string{"s2"}, "s2's lamp_shade"}}},
		{"chair from s2 table_obj from s1 rug_obj", []usesChunk{{[]string{"s2"}, "chair from "}, {[]string{"s2"}, "s2"}, {[]string{"s1"}, " table_obj from "}, {[]string{"s1"}, "s1 rug_obj"}}},
		{"Combines s1 table_top & lamp_shade from s2", []usesChunk{{[]string{"s1"}, "Combines "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, " table_top & lamp_shade from "}, {[]string{"s2"}, "s2"}}},
		{"Extends s1's scene with lamp_obj from s2's output", []usesChunk{{[]string{"s1"}, "Extends "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, "'s scene with lamp_obj from "}, {[]string{"s2"}, "s2's output"}}},
		{"Uses s1 table_obj with lamp_obj plus shade_obj made in s2 lamp.py", []usesChunk{{[]string{"s1"}, "Uses "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, " table_obj with lamp_obj plus shade_obj made in "}, {[]string{"s2"}, "s2 lamp.py"}}},
		{"Uses s1's table_top and s2's lamp_shade, sofa_obj, rug_mesh from s3", []usesChunk{{[]string{"s1"}, "Uses "}, {[]string{"s1"}, "s1's table_top "}, {[]string{"s2"}, "and "}, {[]string{"s2"}, "s2's lamp_shade"}, {[]string{"s3"}, " sofa_obj"}, {[]string{"s3"}, " rug_mesh from "}, {[]string{"s3"}, "s3"}}},
		{"sofa_obj, Uses s1's table_top with s2's lamp_shade", []usesChunk{{[]string{"s1"}, "sofa_obj"}, {[]string{"s1"}, " Uses "}, {[]string{"s1"}, "s1's table_top with "}, {[]string{"s2"}, "s2's lamp_shade"}}},
		// a list broken by plus after "with its" or "with their" (rules 6b and 7): what stands between "with" and the
		// break stays with the id before it; not past a mark, not after a bare "with" (totals_df and lamp_obj are s2's),
		// not without "with" right after the id, and not before a word with no name
		{"frame_obj from s1 with its leg_objs plus slat_objs from s2", []usesChunk{{[]string{"s1"}, "frame_obj from "}, {[]string{"s1"}, "s1 with its leg_objs "}, {[]string{"s2"}, "plus slat_objs from "}, {[]string{"s2"}, "s2"}}},
		{"frame_obj from s1 with its leg_objs plus its seat_rail plus slat_objs from s2", []usesChunk{{[]string{"s1"}, "frame_obj from "}, {[]string{"s1"}, "s1 with its leg_objs plus its seat_rail "}, {[]string{"s2"}, "plus slat_objs from "}, {[]string{"s2"}, "s2"}}},
		{"frame_obj from s1 with its leg_objs PLUS slat_objs from s2", []usesChunk{{[]string{"s1"}, "frame_obj from "}, {[]string{"s1"}, "s1 with its leg_objs "}, {[]string{"s2"}, "PLUS slat_objs from "}, {[]string{"s2"}, "s2"}}},
		{"frame_obj (s1) With its leg_objs plus the slat_objs (s2)", []usesChunk{{[]string{"s1"}, "frame_obj ("}, {[]string{"s1"}, "s1) With its leg_objs "}, {[]string{"s2"}, "plus the slat_objs ("}, {[]string{"s2"}, "s2)"}}},
		{"frame_objs from s1 with their leg_objs plus slat_objs from s2", []usesChunk{{[]string{"s1"}, "frame_objs from "}, {[]string{"s1"}, "s1 with their leg_objs "}, {[]string{"s2"}, "plus slat_objs from "}, {[]string{"s2"}, "s2"}}},
		{"Joins rows_df from s1 with totals_df plus summary_df from s2", []usesChunk{{[]string{"s1"}, "Joins rows_df from "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, " with totals_df plus summary_df from "}, {[]string{"s2"}, "s2"}}},
		{"table_obj from s1 with lamp_obj plus rug_obj from s2", []usesChunk{{[]string{"s1"}, "table_obj from "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, " with lamp_obj plus rug_obj from "}, {[]string{"s2"}, "s2"}}},
		{"load_rows() (s1) feeds totals() plus save_rows() (s2)", []usesChunk{{[]string{"s1"}, "load_rows() ("}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, ") feeds totals() plus save_rows() ("}, {[]string{"s2"}, "s2)"}}},
		{"table_top from s1 with its leg_mesh and seat_mesh plus lamp_shade from s2", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1 with its leg_mesh "}, {[]string{"s2"}, "and seat_mesh plus lamp_shade from "}, {[]string{"s2"}, "s2"}}},
		{"frame_obj from s1 with its leg_objs plus, from s2, slat_objs", []usesChunk{{[]string{"s1"}, "frame_obj from "}, {[]string{"s1"}, "s1 with its leg_objs plus"}, {[]string{"s2"}, " from "}, {[]string{"s2"}, "s2"}, {[]string{"s2"}, " slat_objs"}}},
		{"table_top from s1 then its leg_mesh, lamp_shade from s2", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1 then its leg_mesh"}, {[]string{"s2"}, " lamp_shade from "}, {[]string{"s2"}, "s2"}}},
		// round 8's known misses, pinned as round 7 reads them (its other rules were taken out): an arrow after a suffix
		// id gives it the names after the arrow (lamp_obj is s1's); a second list after a full stop, "|" or then stays
		// with the id before (lamp_shade is s1's); a bare item that says failed is merged (table_top is s1/s2's); an item
		// after a lead that says failed stays with it (table_top is s2's); a forward id's list broken by plus (lamp_shade
		// is s1's), a purpose clause (sofa_obj is s1's), a break before a colon (lamp_shade is s1's), and a list broken by
		// then or also after "with" (leg_mesh is s2's)
		{"table_obj (s1) -> lamp_obj (s2)", []usesChunk{{[]string{"s1"}, "table_obj ("}, {[]string{"s1"}, "s1) -> lamp_obj ("}, {[]string{"s2"}, "s2)"}}},
		{"table_top from s1. Also lamp_shade, rug_mesh from s2", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1. Also lamp_shade"}, {[]string{"s2"}, " rug_mesh from "}, {[]string{"s2"}, "s2"}}},
		{"table_top from s1 | lamp_shade, rug_mesh from s2", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1 | lamp_shade"}, {[]string{"s2"}, " rug_mesh from "}, {[]string{"s2"}, "s2"}}},
		{"table_top from s1 then lamp_shade, rug_mesh from s2", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1 then lamp_shade"}, {[]string{"s2"}, " rug_mesh from "}, {[]string{"s2"}, "s2"}}},
		{"table_top from s1, s2 (failed)", []usesChunk{{[]string{"s1", "s2"}, "table_top from "}, {[]string{"s1", "s2"}, "s1"}, {[]string{"s1", "s2"}, " "}, {[]string{"s1", "s2"}, "s2 (failed)"}}},
		{"s2: lamp_shade (failed), table_top, table_legs from s1", []usesChunk{{[]string{"s2"}, "s2: lamp_shade (failed)"}, {[]string{"s2"}, " table_top"}, {[]string{"s1"}, " table_legs from "}, {[]string{"s1"}, "s1"}}},
		{"From s1 table_top plus lamp_shade from s2", []usesChunk{{[]string{"s1"}, "From "}, {[]string{"s1"}, "s1 table_top plus lamp_shade from "}, {[]string{"s2"}, "s2"}}},
		{"sofa_width, sofa_depth from s1 for placing sofa_obj, rug_obj from s2", []usesChunk{{[]string{"s1"}, "sofa_width"}, {[]string{"s1"}, " sofa_depth from "}, {[]string{"s1"}, "s1 for placing sofa_obj"}, {[]string{"s2"}, " rug_obj from "}, {[]string{"s2"}, "s2"}}},
		{"table_top from s1. Then: lamp_shade, rug_mesh from s2", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1. Then: lamp_shade"}, {[]string{"s2"}, " rug_mesh from "}, {[]string{"s2"}, "s2"}}},
		{"table_top from s1 with its leg_mesh then lamp_shade from s2", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, " with its leg_mesh then lamp_shade from "}, {[]string{"s2"}, "s2"}}},
		{"table_top from s1 with leg_mesh also lamp_shade from s2", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1"}, {[]string{"s2"}, " with leg_mesh also lamp_shade from "}, {[]string{"s2"}, "s2"}}},
		// round 7's reading of forms round 8's other rules read worse, kept: arrows after a lead word, an abbreviation, a
		// continuation and a failure word that doesn't say a step failed
		{"Uses s1 -> table_top s2: lamp_shade", []usesChunk{{[]string{"s1"}, "Uses "}, {[]string{"s1"}, "s1 -> table_top "}, {[]string{"s2"}, "s2: lamp_shade"}}},
		{"Uses s1 -> table_top s2 -> lamp_shade", []usesChunk{{[]string{"s1"}, "Uses "}, {[]string{"s1"}, "s1 -> table_top "}, {[]string{"s2"}, "s2 -> lamp_shade"}}},
		{"table_top from s1 incl. leg_mesh, lamp_shade from s2", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1 incl. leg_mesh"}, {[]string{"s2"}, " lamp_shade from "}, {[]string{"s2"}, "s2"}}},
		{"table_top from s1. leg_mesh too, lamp_shade from s2", []usesChunk{{[]string{"s1"}, "table_top from "}, {[]string{"s1"}, "s1. leg_mesh too"}, {[]string{"s2"}, " lamp_shade from "}, {[]string{"s2"}, "s2"}}},
		{"table_top from s1, s2 (no failures)", []usesChunk{{[]string{"s1", "s2"}, "table_top from "}, {[]string{"s1", "s2"}, "s1"}, {[]string{"s1", "s2"}, " "}, {[]string{"s1", "s2"}, "s2 (no failures)"}}},
	}
	for _, c := range cases {
		got := usesChunks(c.uses)
		if !slices.EqualFunc(got, c.want, func(a, b usesChunk) bool { return a.text == b.text && slices.Equal(a.steps, b.steps) }) {
			t.Errorf("%q:\n got %q\nwant %q", c.uses, got, c.want)
		}
	}
}

// Hand-made pieces (test fixtures, never training data): a group is judged as one, a single step's
// message is today's, and a name is one seam per piece and steps.
func TestUsesSeamsReadGroups(t *testing.T) {
	piece := func(sid, provides, uses string) *workerPiece {
		return &workerPiece{Sid: sid, Handoff: &workerHandoff{Provides: provides, Uses: uses}}
	}
	msgs := func(ps []*workerPiece, failed ...string) []string {
		var out []string
		for _, s := range usesSeams(ps, failed) {
			out = append(out, s.Message)
		}
		return out
	}
	s1, s2 := piece("s1", "table_top", "none"), piece("s2", "lamp_shade", "none")
	for _, uses := range []string{"table_top from s1, lamp_shade from s2", "table_top (s1), lamp_shade (s2)", "s1: table_top; s2: lamp_shade",
		"table_top (from s1, for the height), lamp_shade (from s2, aimed later)", "table_top from s1 and lamp_shade from s2",
		"{\"s1\": [\"table_top\"], \"s2\": [\"lamp_shade\"]}", "scene_root; s1: table_top", "table_top from s1, s2 (merged)"} {
		if got := msgs([]*workerPiece{s1, s2, piece("s3", "x", uses)}); got != nil {
			t.Errorf("%q: %q", uses, got)
		}
	}
	got := msgs([]*workerPiece{s1, s2, piece("s3", "x", "table_top from s1, lamp_shade from s1")})
	if !slices.Equal(got, []string{"s3 uses 'lamp_shade' from s1, which s1 doesn't provide"}) { // today's words
		t.Errorf("%q", got)
	}
	got = msgs([]*workerPiece{s1, s2, piece("s3", "x", "lamp_shade from s1, table_top from s2")}) // each to the id after it
	if !slices.Equal(got, []string{"s3 uses 'lamp_shade' from s1, which s1 doesn't provide", "s3 uses 'table_top' from s2, which s2 doesn't provide"}) {
		t.Errorf("%q", got)
	}
	for _, uses := range []string{"desk_top from s1 and s2", "desk_top from s1-s2", "desk_top from s1/s2"} {
		got = msgs([]*workerPiece{s1, s2, piece("s3", "x", uses)})
		if !slices.Equal(got, []string{"s3 uses 'desk_top' from s1/s2, which s1/s2 doesn't provide"}) {
			t.Errorf("%q: %q", uses, got)
		}
		if got = msgs([]*workerPiece{s1, s2, piece("s3", "x", uses)}, "s2"); got != nil { // s2 may have made it
			t.Errorf("%q: %q", uses, got)
		}
	}
	if got = msgs([]*workerPiece{s1, piece("s3", "x", "desk_top from s1 and s2")}); got != nil { // s2 isn't in the join
		t.Errorf("%q", got)
	}
	for _, uses := range []string{"table_top from s1, lamp_shade from s2 (failed)", "table_top from s1, s2: lamp_shade (failed)",
		"table_top from s1 (s2 failed, so lamp_shade is a stand-in)", "table_top (s1), lamp_shade (s2, failed)"} {
		if got = msgs([]*workerPiece{s1, piece("s3", "x", uses)}, "s2"); got != nil {
			t.Errorf("%q: %q", uses, got)
		}
	}
	got = msgs([]*workerPiece{s1, piece("s3", "x", "lamp_shade from s2 (failed), not_made from s1")}, "s2") // s1's item is still checked
	if !slices.Equal(got, []string{"s3 uses 'not_made' from s1, which s1 doesn't provide"}) {
		t.Errorf("%q", got)
	}
	got = msgs([]*workerPiece{s1, s2, piece("s3", "x", "x_y from s1 (x_y again)")})
	if len(got) != 1 || !strings.Contains(got[0], "'x_y' from s1") { // one seam per piece, steps and name
		t.Errorf("%q", got)
	}
	// round 8 (Nov 5): a SETTINGS_sN name, and a key the line has only in SETTINGS_sN subscripts, is judged against sN
	// alone, wherever it is in the line, and the pairs and breaks as they read, on pieces that hold SETTINGS dicts
	// (a failed step's piece is left out, as in a join); worker-model/tests/test_contract_join.py's USES_SEAMS_ROUND8
	// holds the same table
	coded := func(sid, code, provides, uses string) *workerPiece {
		return &workerPiece{Sid: sid, Code: code, Handoff: &workerHandoff{Provides: provides, Uses: uses}}
	}
	for _, c := range []struct {
		uses         string
		failed, want []string
	}{
		// its own SETTINGS, in an aside
		{"Plank from s1 (parameters taken from own SETTINGS_s3)", nil, nil},
		// a key s1's SETTINGS holds
		{"lamp_shade from s2 sized by SETTINGS_s1[\"lamp_h\"]", nil, nil},
		// one it lacks: a seam from s1, though s2 failed
		{"lamp_shade from s2 sized by SETTINGS_s1[\"lamp_w\"]", []string{"s2"}, []string{"s3 uses 'lamp_w' from s1, which s1 doesn't provide"}},
		// s1 failed: nothing
		{"lamp_shade from s2 sized by SETTINGS_s1[\"lamp_w\"]", []string{"s1"}, nil},
		// SETTINGS_s4 isn't in the join
		{"lamp_shade from s2 (falls back to SETTINGS_s4 defaults)", nil, nil},
		// SETTINGS_s2 is s2's, whatever item it is in
		{"SETTINGS_s2 from s1", nil, nil},
		// a key that also stands outside its chain stays with its item
		{"width_m from s2 (overrides SETTINGS_s1[\"width_m\"])", nil, []string{"s3 uses 'width_m' from s2, which s2 doesn't provide"}},
		// a line with no step id: SETTINGS_s1's key is still s1's
		{"SETTINGS_s1[\"lamp_w\"]", nil, []string{"s3 uses 'lamp_w' from s1, which s1 doesn't provide"}},
		{"SETTINGS_s1[\"lamp_h\"], panel_array", nil, nil},
		// text no step reads
		{"lamp_shade from s2, SETTINGS_s1[\"lamp_w\"] for its height", nil, []string{"s3 uses 'lamp_w' from s1, which s1 doesn't provide"}},
		// s1 failed: nothing
		{"SETTINGS_s1[\"lamp_w\"]", []string{"s1"}, nil},
		// SETTINGS_s4 in a ;-group with no id, not in the join
		{"table_top from s1; SETTINGS_s4", nil, nil},
		// pairs
		{"Uses s1's table_top with s2's lamp_shade", nil, nil},
		// a list broken by plus after "with": frame_obj is s1's
		{"frame_obj from s1 with its table_top plus lamp_shade from s2", nil, []string{"s3 uses 'frame_obj' from s1, which s1 doesn't provide"}},
		// and after "With their"
		{"frame_obj from s1 With their table_top plus lamp_shade from s2", nil, []string{"s3 uses 'frame_obj' from s1, which s1 doesn't provide"}},
		// no "with": lamp_shade stays with s2
		{"table_top (s1) feeds lamp_shade plus not_made (s2)", nil, []string{"s3 uses 'not_made' from s2, which s2 doesn't provide"}},
		// an item after a pair item reads as round 7 reads it: not_made is no step's
		{"Uses s1's table_top and s2's lamp_shade, not_made", nil, nil},
		// a key the line also uses plainly, in a quote span of the whole line, stays with its chunk: lamp_h is s2's, which
		// lacks it, though SETTINGS_s1 holds the key (round 8's re-check, Nov 5: KQ01-KQ04 and the controls KC01-KC03 of
		// its keys_quote.py, with seat_h as these fixtures' lamp_h; test fixtures, never training data)
		{"Uses s2's lamp_h; SETTINGS_s1['lamp_h'] is s1's default", nil, []string{"s3 uses 'lamp_h' from s2, which s2 doesn't provide"}},
		// (the quoted "s SETTINGS_s1[" is read as round 7 reads it)
		{"s2's lamp_h plus s1's SETTINGS_s1['lamp_h']", nil, []string{"s3 uses 'lamp_h' from s2, which s2 doesn't provide", "s3 uses 's SETTINGS_s1[' from s1, which s1 doesn't provide"}},
		{"SETTINGS_s1['lamp_h'] for s1's chair; lamp_h from s2's helper", nil, []string{"s3 uses 'lamp_h' from s2, which s2 doesn't provide"}},
		{"`lamp_h from s2` and SETTINGS_s1['lamp_h']", nil, []string{"s3 uses 'lamp_h' from s2, which s2 doesn't provide"}},
		// the controls: the plain use outside any quote span, as before the re-check
		{"lamp_h from s2, SETTINGS_s1['lamp_h'] from s1", nil, []string{"s3 uses 'lamp_h' from s2, which s2 doesn't provide"}},
		{"Uses s2 lamp_h; SETTINGS_s1['lamp_h'] (s1) as the default", nil, []string{"s3 uses 'lamp_h' from s2, which s2 doesn't provide"}},
		{"lamp_h from s2's helper, SETTINGS_s1['lamp_h'] from s1", nil, []string{"s3 uses 'lamp_h' from s2, which s2 doesn't provide"}},
	} {
		var ps []*workerPiece
		if !slices.Contains(c.failed, "s1") {
			ps = append(ps, coded("s1", "table_top = 1\nSETTINGS_s1 = {'lamp_h': 1}", "table_top", "none"))
		}
		if !slices.Contains(c.failed, "s2") {
			ps = append(ps, coded("s2", "lamp_shade = 1\nSETTINGS_s2 = {}", "lamp_shade", "none"))
		}
		ps = append(ps, coded("s3", "SETTINGS_s3 = {}\ndef main():\n    pass", "main", c.uses))
		if got := msgs(ps, c.failed...); !slices.Equal(got, c.want) {
			t.Errorf("%q (failed %q):\n got %q\nwant %q", c.uses, c.failed, got, c.want)
		}
	}
}
