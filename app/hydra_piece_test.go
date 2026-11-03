package main

import (
	"slices"
	"strings"
	"testing"
)

// Hand-made pieces: test fixtures, never training data.

const fixtureHandoff = "```handoff\nprovides: thing\nuses: none\nassumed: none\n```\n"

const fixtureS2 = `import bpy

SETTINGS_s2 = {"size": 1.0}


def _s2_helper():
    return 1


def build_s2(ctx):
    ctx["objects"]["thing"] = None


if __name__ == "__main__":
    build_s2({"scene": bpy.context.scene, "collection": bpy.context.scene.collection, "objects": {}})`

func issueCodes(p *workerPiece, level string) []string {
	var out []string
	for _, i := range p.Issues {
		if i.Level == level {
			out = append(out, i.Code)
		}
	}
	return out
}

func blenderPiece(code string) *workerPiece {
	return validatePiece("```python\n"+code+"\n```\n\n"+fixtureHandoff, pieceAsk{Mode: modeBlender, Sid: "s2", MaxTokens: maxPieceTokens})
}

func TestAGoodPieceKeepsTheContract(t *testing.T) {
	p := blenderPiece(fixtureS2)
	if !p.ok() || !p.formOK() || len(p.Issues) != 0 {
		t.Fatalf("%+v", p.Issues)
	}
	if p.CodeLine != 2 || p.Handoff.Provides != "thing" || p.Handoff.Uses != "" || strings.Contains(p.Body, "handoff") {
		t.Errorf("code line %d, handoff %+v, body %q", p.CodeLine, *p.Handoff, p.Body)
	}
}

func TestHandoffForms(t *testing.T) {
	lines := "provides: thing\nuses: none\nassumed: none"
	code := "```python\n" + fixtureS2 + "\n```\n\n"
	for _, c := range []struct{ name, tail, warn string }{
		{"a bare label", "handoff\n" + lines + "\n", "handoff_unfenced"},
		{"a decorated label", "**Handoff:**\n\n" + lines + "\n\n", "handoff_unfenced"},
		{"no label", lines + "\n", "handoff_unfenced"},
		{"blank lines between", strings.ReplaceAll(lines, "\n", "\n\n") + "\n", "handoff_unfenced"},
		{"a plain fence", "```\n" + lines + "\n```\n", "handoff_unlabelled"},
		{"a text fence", "```text\n" + lines + "\n```", "handoff_unlabelled"},
		{"no closing fence", "```handoff\n" + lines + "\n", "handoff_unclosed_end"},
		{"written twice", lines + "\n\n```handoff\n" + lines + "\n```\n", "handoff_twice"},
	} {
		p := validatePiece(code+c.tail, pieceAsk{Mode: modeBlender, Sid: "s2"})
		if !p.ok() || !p.contractOK() || p.formOK() {
			t.Errorf("%s: ok %v, contract %v, form %v: %+v", c.name, p.ok(), p.contractOK(), p.formOK(), p.Issues)
		}
		if !slices.Contains(issueCodes(p, "warn"), c.warn) {
			t.Errorf("%s: no %s: %+v", c.name, c.warn, p.Issues)
		}
		if p.Handoff.Provides != "thing" {
			t.Errorf("%s: %+v", c.name, *p.Handoff)
		}
	}
	for tail, code2 := range map[string]string{
		"```handoff\nprovides: a\nuses: b\n```":                       "handoff_shape",
		"```handoff\nprovides: a\nuses: b\nassumed: c\nnotes: d\n```": "handoff_shape",
		"```handoff\nprovides: a\nuses: b\nassumed: c\n```\nThanks!":  "handoff_not_last",
		fixtureHandoff + fixtureHandoff:                               "handoff_many",
		"```handoff\nprovides: a\nand more":                           "handoff_unclosed",
		"Thanks.":                                                     "handoff_missing",
	} {
		p := validatePiece(code+tail, pieceAsk{Mode: modeBlender, Sid: "s2"})
		if !slices.Contains(issueCodes(p, "error"), code2) {
			t.Errorf("%q: %+v", tail, p.Issues)
		}
	}
}

func TestLoneStepsGetNoHandoff(t *testing.T) {
	code := "```python\n" + fixtureS2 + "\n```\n"
	if p := validatePiece(code, pieceAsk{Mode: modeBlender, Sid: "s2", Lone: true}); !p.ok() {
		t.Errorf("%+v", p.Issues)
	}
	p := validatePiece(code+"\n"+fixtureHandoff, pieceAsk{Mode: modeBlender, Sid: "s2", Lone: true})
	if !p.ok() || !slices.Contains(issueCodes(p, "warn"), "handoff_in_lone") {
		t.Errorf("%+v", p.Issues)
	}
}

func TestUsesLine(t *testing.T) {
	code := "```python\n" + fixtureS2 + "\n```\n\n"
	ask := pieceAsk{Mode: modeBlender, Sid: "s2", Deps: []string{"s1"}}
	check := func(uses, level, code2 string) {
		t.Helper()
		p := validatePiece(code+"```handoff\nprovides: thing\nuses: "+uses+"\nassumed: none\n```\n", ask)
		if !slices.Contains(issueCodes(p, level), code2) {
			t.Errorf("%q: %+v", uses, p.Issues)
		}
	}
	check("the table from s3", "error", "uses_not_dependency")
	ask.Sid = "s3"
	check("the table from s2", "warn", "uses_undeclared")
	check("nothing from s1, since it failed", "warn", "handoff_wordy")
}

func TestBlenderTopLevelRules(t *testing.T) {
	for _, c := range []struct {
		name, code string
		level      string
		want       string
	}{
		{"code at the top", fixtureS2 + "\nprint('hi')", "error", "top_level_code"},
		{"a loop at the top", fixtureS2 + "\nfor i in x:\n    pass", "error", "top_level_code"},
		{"a type statement", fixtureS2 + "\ntype Size = int", "error", "top_level_code"},
		{"another step's name", fixtureS2 + "\ndef build_s3(ctx):\n    pass", "error", "wrong_step_names"},
		{"a helper of another step", fixtureS2 + "\n_s1_X = 1", "error", "wrong_step_names"},
		{"no settings", strings.Replace(fixtureS2, `SETTINGS_s2 = {"size": 1.0}`, "", 1), "error", "no_settings"},
		{"settings twice", fixtureS2 + "\nSETTINGS_s2 = {}", "error", "many_settings"},
		{"settings not a dict", strings.Replace(fixtureS2, `{"size": 1.0}`, "dict()", 1), "error", "settings_not_dict"},
		{"no guard", fixtureS2[:strings.Index(fixtureS2, "if __name__")], "error", "no_main_guard"},
		{"a guard that does nothing", strings.Replace(fixtureS2, "build_s2({", "print({", 1), "error", "guard_not_build"},
		{"two guards", fixtureS2 + "\nif __name__ == '__main__':\n    pass", "warn", "many_guards"},
		{"build takes two", strings.Replace(fixtureS2, "def build_s2(ctx):", "def build_s2(ctx, x):", 1), "warn", "build_signature"},
		{"a star import", "from bpy import *\n" + fixtureS2, "warn", "star_import"},
		{"a save", strings.Replace(fixtureS2, "    ctx[", "    bpy.ops.wm.save_mainfile()\n    ctx[", 1), "error", "saves_or_renders"},
		{"a render", strings.Replace(fixtureS2, "    ctx[", "    bpy.ops.render.render(write_still=True)\n    ctx[", 1), "error", "saves_or_renders"},
		{"select all, delete", strings.Replace(fixtureS2, "    ctx[", "    bpy.ops.object.select_all(action='SELECT')\n    bpy.ops.object.delete()\n    ctx[", 1), "error", "deletes_scene"},
		{"a wiping loop", strings.Replace(fixtureS2, "    ctx[", "    for o in bpy.data.objects:\n        bpy.data.objects.remove(o)\n    ctx[", 1), "error", "deletes_scene"},
		{"a wiping loop through a name", strings.Replace(fixtureS2, "    ctx[", "    objs = bpy.data.objects\n    for o in list(objs):\n        if o.name != 'Camera':\n            objs.remove(o)\n    ctx[", 1), "error", "deletes_scene"},
		{"a loop that picks", strings.Replace(fixtureS2, "    ctx[", "    for o in bpy.data.objects:\n        if o.name.startswith('chimera_'):\n            bpy.data.objects.remove(o)\n    ctx[", 1), "warn", "removes_in_loop"},
		{"a key not provided", strings.Replace(fixtureS2, `"thing"`, `"other"`, 1), "warn", "provides_missing"},
		{"a syntax error", fixtureS2 + "\ndef broken(:\n    pass", "error", "syntax_error"},
	} {
		p := blenderPiece(c.code)
		if !slices.Contains(issueCodes(p, c.level), c.want) {
			t.Errorf("%s: %+v", c.name, p.Issues)
		}
	}
	if p := blenderPiece(fixtureS2 + "\ndef broken(:\n    pass"); !p.contractOK() {
		t.Error("a syntax error alone keeps the contract's shape")
	}
}

func TestScriptTopLevelRules(t *testing.T) {
	check := func(code, level, want string) {
		t.Helper()
		p := validatePiece("```python\n"+code+"\n```\n\n"+fixtureHandoff, pieceAsk{Mode: modePythonScript, Sid: "s1"})
		if want == "" {
			if len(p.Issues) != 0 {
				t.Errorf("%q: %+v", code, p.Issues)
			}
		} else if !slices.Contains(issueCodes(p, level), want) {
			t.Errorf("%q: %+v", code, p.Issues)
		}
	}
	check("import os\n\nLIMIT = {'a': (1, -2.5), 'b': [None, 1+2j]}\n\ndef main():\n    pass", "", "")
	check("try:\n    import yaml\nexcept ImportError:\n    yaml = None\n\nclass C:\n    pass", "", "")
	check("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import a", "", "")
	check("LIMIT = os.cpu_count()", "warn", "top_level_assign")
	check("KEYS = {[1]: 2}", "warn", "top_level_assign")
	check("if __name__ == '__main__':\n    main()", "warn", "main_guard")
	check("print('hi')", "error", "runs_on_import")
	check("# TODO: the rest\ndef f():\n    pass", "warn", "placeholder")
}

func TestLiteralValues(t *testing.T) {
	for src, want := range map[string]bool{
		"1": true, "-1.5": true, "+2": true, "'a'": true, "b'a'": true, "None": true, "True": true, "...": true,
		"(1, [2], {3: 4})": true, "{1, 2}": true, "set()": true, "1+2j": true, "-1-2j": true,
		"-True": false, "1+2": false, "2j+1j": false, "f()": false, "x": false, "not 1": false, "~1": false, "{**a}": false,
		"{[1]: 2}": false, "{[1]}": false, "{(1, [2]): 3}": false, "set(x)": false, "f'a'": false,
	} {
		_, got := literalValue(parsed(t, src).body[0].value)
		if got != want {
			t.Errorf("%s: %v", src, got)
		}
	}
}

func TestFilesPieces(t *testing.T) {
	check := func(text, level, want string) *workerPiece {
		t.Helper()
		p := validatePiece(text+"\n\n"+fixtureHandoff, pieceAsk{Mode: modeFiles, Sid: "s1"})
		if !slices.Contains(issueCodes(p, level), want) {
			t.Errorf("%q: %+v", text, p.Issues)
		}
		return p
	}
	check("Some words.", "error", "no_file_blocks")
	check("```python\nx = 1\n```", "error", "no_file_line")
	check("**File: a.py**\n```python\nx = 1\n```", "warn", "file_line_decorated")
	check("File: a.py\n```\nx = 1\n```", "warn", "no_language")
	check("File: a.py\n```python\nx = 1\n```\nFile: a.py\n```python\nx = 2\n```", "warn", "duplicate_file")
	check("File: a.py\n```python\nx = (\n```", "error", "syntax_error")
	check("File: a.txt\n```text\nTODO\n```", "warn", "placeholder")
	p := validatePiece("File: src/a.py (part)\n```python\nx = 1\n```\n\n"+fixtureHandoff, pieceAsk{Mode: modeFiles, Sid: "s1"})
	if !p.formOK() || len(p.Files) != 1 || p.Files[0] != (filePart{"src/a.py", true, "python", "x = 1"}) {
		t.Errorf("%+v %+v", p.Issues, p.Files)
	}
}

func TestSectionPieces(t *testing.T) {
	step := &hydraStep{Title: "The plan", Kind: "research", Instructions: "Write it."}
	check := func(text, level, want string) {
		t.Helper()
		p := validatePiece(text+"\n\n"+fixtureHandoff, pieceAsk{Mode: modeSection, Sid: "s1", Step: step})
		if want == "" {
			if len(p.Issues) != 0 {
				t.Errorf("%q: %+v", text, p.Issues)
			}
		} else if !slices.Contains(issueCodes(p, level), want) {
			t.Errorf("%q: %+v", text, p.Issues)
		}
	}
	check("## The plan\n\nWords.", "", "")
	check("# The plan\n\nWords.", "error", "no_heading")
	check("Words.", "error", "no_heading")
	check("## Other things\n\nWords.", "warn", "heading_not_title")
	check("## The plan\n\nAs an AI, I can't.", "warn", "ai_talk")
	check("## The plan\n\nSee http://a.b/c for more.", "warn", "unmarked_link")
	check("## The plan\n\nSee http://a.b/c (unverified) for more.", "", "")
}

func TestRepliesThatCantWork(t *testing.T) {
	ask := pieceAsk{Mode: modeBlender, Sid: "s2", RejectCut: true, DoneReason: "length", MaxTokens: 10}
	if p := validatePiece("  \n", ask); !slices.Equal(issueCodes(p, "error"), []string{"empty"}) {
		t.Errorf("%+v", p.Issues)
	}
	p := validatePiece("<think>hm</think>```python\n"+fixtureS2+"\n```\n"+fixtureHandoff, ask)
	for _, want := range []string{"cut_off", "too_long", "harmony_leftover"} {
		if !slices.Contains(issueCodes(p, "error"), want) {
			t.Errorf("no %s: %+v", want, p.Issues)
		}
	}
}
