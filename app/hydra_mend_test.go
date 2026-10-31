package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

const mendScriptText = "import bpy\n\ndef wood():\n    mat = bpy.data.materials.new(\"chimera_wood\")\n    bsdf.inputs['Specular'].default_value = 0.2\n    return mat\n\ndef glaze():\n    mat = bpy.data.materials.new(\"chimera_glaze\")\n    bsdf.inputs['Specular'].default_value = 0.2\n    return mat\n"

func TestParseEditsReadsWhatARealModelWrites(t *testing.T) {
	reply := "<<<<<<< FIND\n    a = 1\n=======\n    a = 2\n>>>>>>> END\n\nAnd then:\n\n```\n<<<<<<< FIND\nb = 1\n\nc = 1\n=======\nb = 2\n>>>>>>> END\n```\n"
	got := parseEdits(reply)
	if len(got) != 2 || got[0].Find != "    a = 1" || got[0].Replace != "    a = 2" || got[1].Find != "b = 1\n\nc = 1" || got[1].Replace != "b = 2" {
		t.Fatalf("%#v", got)
	}
	if got := parseEdits(strings.ReplaceAll(reply, "\n", "\r\n")); len(got) != 2 || got[0].Find != "    a = 1" {
		t.Fatalf("Windows line ends: %#v", got)
	}
	if got := parseEdits("<<<<<<< FIND\na\n=======\n>>>>>>> END"); len(got) != 1 || got[0].Replace != "" {
		t.Fatalf("an edit may delete lines: %#v", got)
	}
	if got := parseEdits("<<<<<<< FIND\n\n=======\nb\n>>>>>>> END"); len(got) != 0 {
		t.Fatalf("nothing to find: %#v", got)
	}
	if got := parseEdits("<<<<<<< FIND\na\n=======\nb\n>>>>>>> END\n<<<<<<< FIND\nc\n=======\nd"); len(got) != 1 {
		t.Fatalf("an edit that stopped early doesn't count: %#v", got)
	}
	if got := parseEdits("Here is the whole script again:\n```python\nimport bpy\n```"); len(got) != 0 {
		t.Fatalf("no edits: %#v", got)
	}
	// Markers are whole lines: a banner in the code isn't one.
	banner := "<<<<<<< FIND\nx = 1  # =======\n# =========\ny = 2\n=======\nx = 3\n>>>>>>> END"
	if got := parseEdits(banner); len(got) != 1 || got[0].Find != "x = 1  # =======\n# =========\ny = 2" || got[0].Replace != "x = 3" {
		t.Fatalf("a comment banner: %#v", got)
	}
	if got := parseEdits("    <<<<<<< FIND\n    a\n    =======\n    b\n    >>>>>>> END"); len(got) != 1 {
		t.Fatalf("indented markers: %#v", got)
	}
	// A code fence around a side would end the script's own block.
	if got := parseEdits("<<<<<<< FIND\n```python\nx = 1\n```\n=======\n```python\nx = 2\n```\n>>>>>>> END"); len(got) != 1 || got[0].Find != "x = 1" || got[0].Replace != "x = 2" {
		t.Fatalf("fences around both sides: %#v", got)
	}
	if got := parseEdits("<<<<<<< FIND\nx = 1\n=======\n```\nx = 2\n```\n>>>>>>> END"); len(got) != 1 || got[0].Replace != "x = 2" {
		t.Fatalf("a fence around one side: %#v", got)
	}
	if got := parseEdits("<<<<<<< FIND\nx = 1\n=======\nx = 2\n```\ny = 3\n>>>>>>> END"); len(got) != 0 {
		t.Fatalf("an edit that adds a fence: %#v", got)
	}
	twice := "<<<<<<< FIND\na\n=======\na\nb\n>>>>>>> END\n<<<<<<< FIND\na\n=======\na\nb\n>>>>>>> END"
	if got := parseEdits(twice); len(got) != 1 {
		t.Fatalf("a repeated edit counts once: %#v", got)
	}
	noEnd := "<<<<<<< FIND\na\n=======\nb\n<<<<<<< FIND\nc\n=======\nd\n>>>>>>> END"
	if got := parseEdits(noEnd); len(got) != 0 {
		t.Fatalf("an edit that ran into the next: %#v", got)
	}
}

func TestApplyEdits(t *testing.T) {
	apply := func(text string, e ...edit) (string, int, int) { return applyEdits(text, e) }
	if got, n, miss := apply("a\nb  \nc\n", edit{"b", "B"}); got != "a\nB\nc\n" || n != 1 || miss != 0 {
		t.Fatalf("trailing spaces don't count: %q %d %d", got, n, miss)
	}
	// The Oct 31 misses: right lines, wrong indent. The new lines move with them.
	got, n, _ := apply(mendScriptText, edit{"def wood():\n  mat = bpy.data.materials.new(\"chimera_wood\")", "def wood():\n  mat = bpy.data.materials.new(\"chimera_wood2\")\n  mat.use_nodes = True"})
	if n != 1 || !strings.Contains(got, "def wood():\n    mat = bpy.data.materials.new(\"chimera_wood2\")\n    mat.use_nodes = True\n") {
		t.Fatalf("each line takes the indent of the line it stands for: %d %q", n, got)
	}
	got, n, _ = apply("if x:\n        y = 1\n        z = 2\n", edit{"    y = 1\n    z = 2", "    y = 3\n    if y:\n        z = 2"})
	if n != 1 || got != "if x:\n        y = 3\n        if y:\n            z = 2\n" {
		t.Fatalf("the new lines move by the same amount: %q", got)
	}
	// One wrong line copied to two places: fixing it fixes both.
	got, n, _ = apply(mendScriptText, edit{"    bsdf.inputs['Specular'].default_value = 0.2", "    bsdf.inputs['Specular IOR Level'].default_value = 0.2"})
	if n != 1 || strings.Contains(got, "['Specular']") || strings.Count(got, "Specular IOR Level") != 2 {
		t.Fatalf("%q", got)
	}
	if got, n, miss := apply("a\nb\n", edit{"b", "B"}, edit{"nothing", "x"}); got != "a\nB\n" || n != 1 || miss != 1 {
		t.Fatalf("the edits that match still apply: %q %d %d", got, n, miss)
	}
	if got, n, _ := apply("a\nb\n", edit{"a\nb", ""}); n != 1 || got != "\n" {
		t.Fatalf("deleting: %q", got)
	}
	if got, _, _ := apply("a\nb\n", edit{"a", "a\na2"}); got != "a\na2\nb\n" {
		t.Fatalf("adding after an anchor: %q", got)
	}
	// Later edits see the earlier ones' work, and an overlap stays one place.
	if got, _, _ := apply("x\nx\nx\n", edit{"x\nx", "y"}); got != "y\nx\n" {
		t.Fatalf("overlaps: %q", got)
	}
	// A line shallower than the first keeps its place relative to it.
	got, _, _ = apply("        y = 1\n", edit{"    y = 1", "    y = 1\nz = 2"})
	if got != "        y = 1\n    z = 2\n" {
		t.Fatalf("deeper: %q", got)
	}
	got, _, _ = apply("y = 1\n", edit{"    y = 1", "    y = 1\nz = 2"})
	if got != "y = 1\nz = 2\n" {
		t.Fatalf("shallower: %q", got)
	}
	// Adding lines belongs in one place: a line that's in several doesn't name it.
	if got, n, miss := apply("link(a)\nx\nlink(a)\n", edit{"link(a)", "link(a)\nb = 1"}); n != 0 || miss != 1 || strings.Contains(got, "b = 1") {
		t.Fatalf("an insertion at a line that's in two places: %q %d %d", got, n, miss)
	}
	if got, n, _ := apply("x\nlink(a)\ny\nlink(a)\n", edit{"x\nlink(a)", "x\nlink(a)\nb = 1"}); n != 1 || strings.Count(got, "b = 1") != 1 {
		t.Fatalf("enough lines to name the place: %q", got)
	}
	if got, n, miss := apply("a\nb\nz\na\nb\n", edit{"a\nb", "a\nnew\nb"}); n != 0 || miss != 1 || strings.Contains(got, "new") {
		t.Fatalf("an insertion inside a FIND that's in two places: %q", got)
	}
	if got, n, _ := apply("a = 1\r\nb = 2\r\n", edit{"a = 1", "a = 3"}); n != 1 || !strings.HasPrefix(got, "a = 3\n") {
		t.Fatalf("Windows line ends: %q %d", got, n)
	}
	// A script inside a list item: the lines have an indent the script doesn't.
	listed := "1. Run this:\n\n   ```python\n   import bpy\n   x = 1\n   ```\n"
	if got, n, _ := apply(listed, edit{"x = 1", "x = 2"}); n != 1 || !strings.Contains(got, "\n   x = 2\n") {
		t.Fatalf("%q", got)
	}
}

func fencedScript(body string) string {
	return "Here is the script.\n\n```python\n" + body + "\n```\n\nRun it.\n"
}

func TestEditedResult(t *testing.T) {
	kinds := map[string]bool{"blender": true}
	body := "import bpy\nimport math\n\nscene = bpy.context.scene\nx = 1\ny = 2\nz = 3\nprint(x, y, z)"
	base := fencedScript(body)
	if got, whole := editedResult(base, "<<<<<<< FIND\nx = 1\n=======\nx = 5\n>>>>>>> END", kinds); whole || !strings.Contains(got, "x = 5") || !strings.Contains(got, "Run it.") {
		t.Fatalf("edits: %q %v", got, whole)
	}
	if got, whole := editedResult(base, "```python\n"+strings.ReplaceAll(body, "x = 1", "x = 7")+"\n```", kinds); !whole ||
		!strings.Contains(got, "x = 7") || !strings.Contains(got, "Here is the script.") || !strings.Contains(got, "Run it.") {
		t.Fatalf("a whole script instead of edits goes in the script's place: %q %v", got, whole)
	}
	if got, whole := editedResult(base, "Nothing to change.", kinds); whole || got != base {
		t.Fatalf("no edits and no script: %q %v", got, whole)
	}
	if got, whole := editedResult(base, "<<<<<<< FIND\nnot in it\n=======\nx\n>>>>>>> END", kinds); whole || got != base {
		t.Fatalf("edits that find nothing: %q %v", got, whole)
	}
	// Edits that would leave no script to check are no use: a result without one
	// would pass for fine.
	if got, _ := editedResult(base, "<<<<<<< FIND\n```\n=======\nx\n>>>>>>> END", kinds); got != base {
		t.Fatalf("edits that break the code block: %q", got)
	}
	long := "import bpy\n" + strings.Repeat("x = 1\n", 40) + "print(x)"
	big := fencedScript(long)
	// A short snippet isn't the script written out, however much it looks like one.
	snippet := fencedScript("import bpy\na = 1\nb = 2\nc = 3\nd = 4\ne = 5\nf = 6")
	if got, whole := editedResult(big, snippet, kinds); whole || got != big {
		t.Fatalf("a snippet replaced the whole result: %v", whole)
	}
	nums := "import bpy\n"
	for i := range 40 {
		nums += fmt.Sprintf("x%d = %d\n", i, i)
	}
	numbered := fencedScript(nums + "print(x0)")
	if got, whole := editedResult(numbered, fencedScript(strings.ReplaceAll(nums, "x1 = 1\n", "x1 = 2\n")+"print(x0)"), kinds); !whole || got == numbered {
		t.Fatalf("about the same size and mostly the same lines is a write-out: %v", whole)
	}
	other := "import bpy\n"
	for i := range 30 {
		other += fmt.Sprintf("y%d = %d\n", i, i)
	}
	if got, whole := editedResult(numbered, fencedScript(other), kinds); whole || got != numbered {
		t.Fatalf("a long block with other lines isn't this script: %v", whole)
	}
	// A valid edit stays even if the script stops being the one to run.
	if got, _ := editedResult(fencedScript("x = 1\ny = 2\nz = 3\na = 4\nb = 5\nc = 6\nprint(a)"), "<<<<<<< FIND\nx = 1\n=======\nimport tkinter\nx = 1\n>>>>>>> END", map[string]bool{"code": true}); !strings.Contains(got, "tkinter") {
		t.Fatalf("an edit that stops the check from running is still an edit: %q", got)
	}
	// An edit with no end marker and a write-out in one reply is neither.
	if got, whole := editedResult(base, "<<<<<<< FIND\nx = 1\n=======\n"+fencedScript(body), kinds); whole || got != base {
		t.Fatalf("edit markers aren't a script: %q %v", got, whole)
	}
	// Edits in a fence that all miss are edits, not a script full of markers.
	fenced := "```python\n<<<<<<< FIND\nnot in it\nnor this\n=======\nimport bpy\na = 1\nb = 2\nc = 3\n>>>>>>> END\n```"
	if got, whole := editedResult(base, fenced, kinds); whole || got != base {
		t.Fatalf("edits that miss: %q %v", got, whole)
	}
	// A model shown only the first part of a long result can't have written it all.
	huge := fencedScript("import bpy\n" + strings.Repeat("x = 1  # filler filler filler filler filler\n", 1500))
	if len(huge) <= earlierLimit {
		t.Fatal("the test needs a result over earlierLimit")
	}
	if got, whole := editedResult(huge, fencedScript("import bpy\n"+strings.Repeat("x = 1\n", 1400)), kinds); whole || got != huge {
		t.Fatalf("a write-out of a result it saw part of: %v", whole)
	}
}

func TestRepairsChangeOnlyTheScript(t *testing.T) {
	kinds := map[string]bool{"blender": true}
	body := "import bpy\nimport math\n\nscene = bpy.context.scene\nx = bad\ny = 2\nz = 3\nprint(x, y, z)"
	fix := "<<<<<<< FIND\nx = bad\n=======\nx = 1\n>>>>>>> END"
	if got := repairedScript(body, fix, kinds); !strings.Contains(got, "x = 1") || strings.Contains(got, "bad") {
		t.Fatalf("%q", got)
	}
	if got := repairedScript(body, "```python\n"+strings.ReplaceAll(body, "x = bad", "x = 1")+"\n```", kinds); !strings.Contains(got, "x = 1") {
		t.Fatalf("written out: %q", got)
	}
	if got := repairedScript(body, "Nothing to fix.", kinds); got != "" {
		t.Fatalf("%q", got)
	}
	if got := repairedScript(body, "<<<<<<< FIND\nnot in it\n=======\nx\n>>>>>>> END", kinds); got != "" {
		t.Fatalf("%q", got)
	}
	// Back in its place: a list item's indent, a CRLF result, and a copy of the
	// same lines in a block nobody runs.
	for _, c := range []struct{ name, result string }{
		{"plain", "Intro.\n\n```python\n" + body + "\n```\n\nRun it.\n"},
		{"list item", "1. Run this:\n\n   ```python\n" + strings.ReplaceAll("   "+body, "\n", "\n   ") + "\n   ```\n\n2. Done.\n"},
		{"crlf", strings.ReplaceAll("Intro.\n\n```python\n"+body+"\n```\n\nRun it.\n", "\n", "\r\n")},
		{"a copy", "```text\n" + body + "\n```\n\n```python\n" + body + "\n```\n"},
	} {
		_, block, _ := pickBlock(kinds, c.result)
		fixed := repairedScript(dedent(block.Body), fix, kinds)
		got := withScript(c.result, block, fixed)
		if _, s, _ := pickScript(kinds, got); !strings.Contains(s, "x = 1") || strings.Contains(s, "bad") {
			t.Fatalf("%s: the script that runs: %q", c.name, got)
		}
		if strings.Count(got, "x = 1") != 1 {
			t.Fatalf("%s: only the script that runs changes: %q", c.name, got)
		}
		if c.name != "a copy" && (!strings.Contains(got, "ntro.") && !strings.Contains(got, "Run this")) {
			t.Fatalf("%s: the rest stays: %q", c.name, got)
		}
	}
}

// Whether a result has a script to check doesn't depend on how the latest plan
// was labelled.
func TestKindsLastTheWholeTask(t *testing.T) {
	r := &taskRun{}
	r.addKinds(hydraPlan{Kind: "code"})
	r.addKinds(hydraPlan{Kind: "general", Steps: []hydraStep{{Kind: "writing"}}})
	got := r.allKinds()
	if !got["code"] || !got["general"] || !got["writing"] {
		t.Fatalf("%v", got)
	}
	got["code"] = false
	if !r.allKinds()["code"] {
		t.Fatal("allKinds hands out a copy")
	}
}

func TestPieceCap(t *testing.T) {
	fits := func(sizes []int, limit int) int {
		c := pieceCap(sizes, limit)
		total := 0
		for _, n := range sizes {
			total += min(n, c)
		}
		if total > limit {
			t.Fatalf("%v at %d: %d is over the limit", sizes, c, total)
		}
		return c
	}
	// The Oct 31 bug: 60,000 / 6 steps cut a 16,052-character script at 10,000,
	// with the total far under the limit.
	if c := fits([]int{16052, 2000, 1500, 1800, 900, 1200}, 60000); c < 16052 {
		t.Fatalf("nothing needs cutting, but it's cut at %d", c)
	}
	if c := fits([]int{50000, 20000, 1000}, 60000); c != 39000 {
		t.Fatalf("the short pieces stay whole, the longest gets what's left: %d", c)
	}
	if c := fits([]int{40000, 40000}, 60000); c != 30000 {
		t.Fatalf("%d", c)
	}
	if c := fits(nil, 60000); c != 60000 {
		t.Fatalf("%d", c)
	}
}

func TestGradeOrdersRounds(t *testing.T) {
	ok := []resultCheck{{Outcome: "passed"}, {Outcome: "unsure"}, {Outcome: "skipped"}}
	wrongBetter := resultCheck{Outcome: "wrong_scene", Seen: 0.8}
	wrongWorse := resultCheck{Outcome: "wrong_scene", Seen: 0.1}
	runs := resultCheck{Outcome: "failed", Error: "KeyError: 'bpy_prop_collection[key]: key \"Specular\" not found'"}
	wontStart := resultCheck{Outcome: "failed", Error: "SyntaxError: invalid syntax"}
	noScript := resultCheck{}
	cut := resultCheck{Outcome: "cut_off"}
	for _, c := range ok {
		if c.grade() != ok[0].grade() {
			t.Fatalf("nothing known to be wrong with %+v", c)
		}
	}
	if !(ok[0].grade() > wrongBetter.grade() && wrongBetter.grade() > wrongWorse.grade() && wrongWorse.grade() > runs.grade() && runs.grade() > wontStart.grade() && wontStart.grade() > noScript.grade() && noScript.grade() > cut.grade()) {
		t.Fatal("best to worst: fine, the wrong scene (more of it in view first), runs part-way, doesn't start, no script, cut off")
	}
	empty := roundResult{Check: cut}
	if empty.grade() >= cut.grade() {
		t.Fatal("a round with nothing in it is the worst of all")
	}
	if (roundResult{Text: "x", Check: runs}).grade() != runs.grade() {
		t.Fatal("otherwise a round's grade is its check's")
	}
	for _, e := range []string{"IndentationError: unexpected indent", "TabError: inconsistent use of tabs"} {
		if (resultCheck{Outcome: "failed", Error: e}).grade() != wontStart.grade() {
			t.Fatal(e)
		}
	}
}

// The note and the card describe the result the person got.
func TestFinalCheckFollowsTheKeptRoundAndUndoneRepairs(t *testing.T) {
	rec := TaskRecord{Round: 3, Kept: 1, Checks: []resultCheck{
		{Round: 1, Outcome: "failed", Error: "first"}, {Round: 1, Mend: 1, Outcome: "passed"},
		{Round: 2, Outcome: "failed"}, {Round: 3, Outcome: "failed"}}}
	if c := finalCheck(rec); c.Outcome != "passed" || c.Mend != 1 {
		t.Fatalf("the kept round's last check: %+v", c)
	}
	rec = TaskRecord{Round: 1, Checks: []resultCheck{{Round: 1, Outcome: "failed", Error: "kept"}, {Round: 1, Mend: 1, Outcome: "failed", Error: "worse", Undone: true}}}
	if c := finalCheck(rec); c.Error != "kept" {
		t.Fatalf("a repair taken back isn't the result: %+v", c)
	}
	if c := finalCheck(TaskRecord{Round: 2, Kept: 2, Checks: []resultCheck{{Round: 1, Outcome: "failed"}}}); c.Outcome != "" {
		t.Fatalf("that round had nothing to check: %+v", c)
	}
}

// An out-of-range index into Blender's own data is a crash; the same in what
// the person's scene might hold, or a plain list, may not be the script's fault.
func TestIndexErrorIsACrashOnlyInWhatTheScriptMade(t *testing.T) {
	run := func(script, source, msg string) resultCheck {
		out := "Traceback (most recent call last):\n  File \"script.py\", line 3, in <module>\n    " + source + "\nIndexError: " + msg + "\n\nError: script failed, file: 'script.py', exiting.\n"
		return judgeRun("run_blender", "Blender 5.2.2", "", script, runResult{ExitCode: 1, Stderr: out, Output: out})
	}
	range2 := "bpy_prop_collection[index]: index 2 out of range, size 2"
	if c := run("import bpy\nsp = curve.splines.new('BEZIER')\nsp.bezier_points[2].co = (0, 0, 0)\n", "sp.bezier_points[2].co = (0, 0, 0)", range2); c.Outcome != "failed" || c.Line != 3 {
		t.Fatalf("%+v", c)
	}
	if c := run("import bpy\n\nobj = bpy.data.objects[7]\n", "obj = bpy.data.objects[7]", range2); c.Outcome != "unsure" {
		t.Fatalf("may be your own scene: %+v", c)
	}
	if c := run("import bpy\nobj = bpy.context.active_object\nslot = obj.material_slots[0]\n", "slot = obj.material_slots[0]", range2); c.Outcome != "unsure" {
		t.Fatalf("your selection: %+v", c)
	}
	if c := run("import bpy\nobjs = [o for o in bpy.data.objects if 'Hero' in o.name]\nobj = objs[0]\n", "obj = objs[0]", "list index out of range"); c.Outcome != "unsure" {
		t.Fatalf("a list may come from your scene: %+v", c)
	}
	if c := run("import bpy\nobj = bpy.data.objects.get('Hero')\nv = obj.data.vertices[9]\n", "v = obj.data.vertices[9]", range2); c.Outcome != "unsure" {
		t.Fatalf("an object the script found, not made: %+v", c)
	}
	out := "Traceback (most recent call last):\n  File \"script.py\", line 3, in <module>\n    sp.bezier_points[2].co = (0, 0, 0)\nIndexError: " + range2 + "\n\nError: script failed, file: 'script.py', exiting.\n"
	made := "import bpy\nsp = curve.splines.new('BEZIER')\nsp.bezier_points[2].co = (0, 0, 0)\n"
	if c := judgeRun("run_blender", "Blender 5.2.2", "for Blender 4.2", made, runResult{ExitCode: 1, Stderr: out, Output: out}); c.Outcome != "unsure" {
		t.Fatalf("the goal names another Blender: %+v", c)
	}
}

// The Oct 31 tabletop script: bpy.context.region is None with -b, and the task
// said to run it that way. Without that in the goal, it may be meant for the window.
func TestAnErrorWithMoreLinesEndedTheRun(t *testing.T) {
	out := "Traceback (most recent call last):\n  File \"script.py\", line 2, in <module>\n    bpy.ops.mesh.foo()\nRuntimeError: Error: first line\n  second line of the message\n\nError: script failed, file: 'script.py', exiting.\n"
	e, ok := lastPyError(out)
	if !ok || !e.Last || e.Type != "RuntimeError" {
		t.Fatalf("%+v", e)
	}
	went := "Traceback (most recent call last):\n  File \"script.py\", line 2, in <module>\n    x\nRuntimeError: Error: first line\n  more\nand then the script went on\n"
	if e, _ := lastPyError(went); e.Last {
		t.Fatalf("it went on after it: %+v", e)
	}
}

func TestAHeadlessTaskCantBlameTheMissingWindow(t *testing.T) {
	script := "import bpy\nimport bmesh\n\nbm = bmesh.new()\nbmesh.ops.create_circle(\n    bm,\n    radius=1,\n    matrix=bpy.context.region.view_matrix,\n)\n"
	out := "Traceback (most recent call last):\n  File \"script.py\", line 8, in <module>\n    matrix=bpy.context.region.view_matrix,\nAttributeError: 'NoneType' object has no attribute 'view_matrix'\n\nError: script failed, file: 'script.py', exiting.\n"
	run := func(goal, s string) resultCheck {
		return judgeRun("run_blender", "Blender 5.2.2", goal, s, runResult{ExitCode: 1, Stderr: out, Output: out})
	}
	for _, goal := range []string{"Write one script, runnable with blender -b --python, that builds a table", "a headless script for a table", "for blender --background"} {
		if c := run(goal, script); c.Outcome != "failed" || c.Line != 8 {
			t.Fatalf("%s: %+v", goal, c)
		}
	}
	if c := run("Write a script that builds a table", script); c.Outcome != "unsure" {
		t.Fatalf("it may be meant for the window: %+v", c)
	}
	other := strings.ReplaceAll(strings.ReplaceAll(script, "bpy.context.region.view_matrix", "obj.matrix_world"), "\nbm = bmesh", "\nobj = bpy.data.objects.get('Hero')\nbm = bmesh")
	if c := run("runnable with blender -b --python", other); c.Outcome != "unsure" {
		t.Fatalf("a None that isn't the window may still be your scene: %+v", c)
	}
	c := resultCheck{Outcome: "unsure", Runner: "Blender 5.2.2", Line: 22, Error: "AttributeError: 'NoneType' object has no attribute 'view_matrix'"}
	if s := unsureLine(c); !strings.Contains(s, "line 22") || !strings.Contains(s, "view_matrix") {
		t.Fatal(s)
	}
	if unsureLine(resultCheck{Outcome: "unsure"}) != "" || unsureLine(resultCheck{Outcome: "passed"}) != "" {
		t.Fatal("only a script that stopped on an error has anything to say")
	}
}

func TestLaterRoundsWorkFromTheResult(t *testing.T) {
	base := roundResult{Round: 1, Text: "the script", Critique: "add a fill light"}
	if s := earlierForWorker(roundResult{}, false); s != "" {
		t.Fatalf("the first round has nothing before it: %q", s)
	}
	edit := earlierForWorker(base, true)
	if !strings.Contains(edit, "the script") || !strings.Contains(edit, "add a fill light") || !strings.Contains(edit, "only the code your step adds or changes") {
		t.Fatal(edit)
	}
	if strings.Contains(earlierForWorker(base, false), "only the code") {
		t.Fatal("outside a script a worker's own text is the piece")
	}
	if !strings.Contains(hydraMendPrompt, "<<<<<<< FIND") || !strings.HasPrefix(synthEditPrompt, "You are Hydra's final editor") {
		t.Fatal("the edit format goes with the prompts")
	}
}

func TestNamesLineReadsAndIsCut(t *testing.T) {
	out := "Traceback (most recent call last):\n  File \"script.py\", line 3, in <module>\n    tex.noise_scale = 1\nAttributeError: 'NoiseTexture' object has no attribute 'noise_scale'\n" +
		namesMarker + `{"kind":"attr","wrong":"noise_scale","of":"NoiseTexture","names":["noise_depth","contrast"]}` + "\n\nError: script failed, file: 'script.py', exiting.\n"
	res, names := takeNames(runResult{ExitCode: 1, Stderr: out, Output: out})
	if strings.Contains(res.Output, namesMarker) || strings.Contains(res.Stderr, namesMarker) || names.line() != "NoiseTexture has no noise_scale. What it does have: noise_depth, contrast." {
		t.Fatalf("%q %q", res.Output, names.line())
	}
	c := judgeRun("run_blender", "Blender 5.2.2", "", "import bpy\ntex = bpy.data.textures.new('n', 'NOISE')\ntex.noise_scale = 1\n", runResult{ExitCode: 1, Stderr: out, Output: out})
	if c.Outcome != "failed" || c.Line != 3 || c.Names == "" || strings.Contains(c.Output, namesMarker) {
		t.Fatalf("the line changes nothing else: %+v", c)
	}
	if cr := crashCritique("run_blender", "Blender 5.2.2", c); !strings.HasSuffix(cr, c.Names) {
		t.Fatalf("the critique ends with them: %q", cr)
	}
	long := strings.Repeat("x", 3000)
	c.Error, c.Names = long, "the names"
	if cr := crashCritique("run_blender", "Blender 5.2.2", c); !strings.HasSuffix(cr, "\nthe names") {
		t.Fatalf("a long error can't lose them: %q", cr[len(cr)-40:])
	}
	if _, n := takeNames(runResult{Output: namesMarker + "not json\n"}); n.Wrong != "" {
		t.Fatalf("a line that doesn't parse: %+v", n)
	}
	if _, n := takeNames(runResult{Output: namesMarker + `{"kind":"attr","wrong":"a","of":"B","names":[]}`}); n.Wrong != "" {
		t.Fatalf("no names, nothing to say: %+v", n)
	}
	earlier := namesMarker + `{"kind":"attr","wrong":"a","of":"B","names":["c"]}` + "\nTraceback (most recent call last):\n  File \"script.py\", line 9, in <module>\nNameError: name 'x' is not defined\n"
	if _, n := takeNames(runResult{Output: earlier}); n.Wrong != "" {
		t.Fatalf("names from before the last traceback are another error's: %+v", n)
	}
	other := "Traceback (most recent call last):\n  File \"script.py\", line 3, in <module>\n    x = y\nNameError: name 'y' is not defined\n" + namesMarker + `{"kind":"attr","wrong":"zzz","of":"B","names":["c"]}` + "\n\nError: script failed, file: 'script.py', exiting.\n"
	if c := judgeRun("run_blender", "Blender 5.2.2", "", "import bpy\n\nx = y\n", runResult{ExitCode: 1, Stderr: other, Output: other}); c.Names != "" {
		t.Fatalf("names about something else aren't used: %+v", c)
	}
	on := crashNames{Kind: "attr", Wrong: "file_format", Of: "RenderSettings", Names: []string{"image_settings"}, On: []string{"image_settings"}, More: true}
	if s := on.line(); s != "RenderSettings has no file_format: that's on its image_settings. What it does have: image_settings, …." {
		t.Fatal(s)
	}
	key := crashNames{Kind: "key", Wrong: "Specular", Of: "bsdf.inputs", Names: []string{"Specular IOR Level", "Base Color"}}
	if s := key.line(); s != `bsdf.inputs has no "Specular". What it does have: "Specular IOR Level", "Base Color".` {
		t.Fatal(s)
	}
	many := crashNames{Kind: "kw", Wrong: "x", Of: "f", Names: strings.Split(strings.Repeat("a_long_keyword_name ", 100), " ")}
	if s := many.line(); len(s) > namesLimit+100 || !strings.HasSuffix(s, "….") {
		t.Fatalf("%d %q", len(s), s[len(s)-20:])
	}
}

// Real Blender, when there's one here. CHIMERA_TEST_BLENDER picks a version.
func TestRealBlenderListsTheRealNames(t *testing.T) {
	path := os.Getenv("CHIMERA_TEST_BLENDER")
	if path == "" {
		path, _ = findBlender()
	}
	if path == "" {
		t.Skip("no Blender here")
	}
	for _, c := range []struct{ name, script, has string }{
		{"a property set", "import bpy\ntex = bpy.data.textures.new('n', type='NOISE')\ntex.noise_scale = 1.0\n", "contrast"},
		{"a property read", "import bpy\nc = bpy.data.curves.new('c', 'CURVE')\nc.dimensions = '3D'\ns = c.splines.new('NURBS')\ns.use_cyclic = True\n", "use_cyclic_u"},
		{"a collection's method", "import bpy\nc = bpy.data.curves.new('c', 'CURVE')\nc.splines.clear_all()\n", "clear"},
		{"a modifier made by a call", "import bpy\nbpy.data.objects['Cube'].modifiers.new('b', 'BEVEL').offset = 1\n", ""},
		{"a socket", "import bpy\nmat = bpy.data.materials.new('m')\nmat.use_nodes = True\nb = mat.node_tree.nodes['Principled BSDF']\nb.inputs['Specular'].default_value = 0.5\n", `"Specular IOR Level"`},
		{"a socket by a variable", "import bpy\nmat = bpy.data.materials.new('m')\nmat.use_nodes = True\nb = mat.node_tree.nodes['Principled BSDF']\nfor k in ('Metallic', 'Emission'):\n    b.inputs[k].default_value = 0.5\n", `"Emission Color"`},
		{"in a function", "import bpy\n\ndef build(s):\n    s.use_cyclic = True\n\nc = bpy.data.curves.new('c', 'CURVE')\nbuild(c.splines.new('POLY'))\n", "use_cyclic_u"},
		{"an operator", "import bpy\nbpy.ops.mesh.primitive_cone_add(\n    vertices=8,\n    diameter1=2,\n)\n", "radius1"},
		{"a bmesh operator", "import bpy\nimport bmesh\nbm = bmesh.new()\nbmesh.ops.create_cone(bm, diameter1=1, segments=8)\n", "radius1"},
		{"a bmesh keyword", "import bpy\nimport bmesh\nbm = bmesh.new()\nbmesh.ops.extrude_face_region(bm, faces=[])\n", "geom"},
		{"a module", "import bpy\nimport mathutils\nx = mathutils.radians(1)\n", "Vector"},
		{"nothing to list", "import bpy\nx = bpy.context.region.view_matrix\n", ""},
		{"a plain error", "import bpy\nprint(undefined_name)\n", ""},
		{"where it really is", "import bpy\nbpy.context.scene.render.file_format = 'PNG'\n", "that's on its image_settings"},
		{"a pointer that's empty isn't where", "import bpy\no = bpy.data.objects['Cube']\no.mass = 1\n", "Object has no mass. What it does have"},
		{"a class", "import bpy\nimport mathutils\nm = mathutils.Matrix.LookAt\n", "Matrix has no LookAt"},
		{"an operator that doesn't exist", "import bpy\nbpy.ops.object.track_to_constraint(track='-Z')\n", "bpy.ops.object has no track_to_constraint"},
		{"the right collection of two", "import bpy\nm = bpy.data.materials.new('m')\nm.use_nodes = True\nb = m.node_tree.nodes['Principled BSDF']\no = m.node_tree.nodes['Material Output']\no.inputs['Surface'].default_value = b.inputs['Specular'].default_value\n", `"Specular IOR Level"`},
		{"a loop header, not its body", "import bpy\nt = bpy.data.textures.new('n', type='NOISE')\nc = bpy.data.objects['Cube']\nif t.wrong_one:\n    c.wrong_one = 1\n", "NoiseTexture has no wrong_one"},
		{"two statements on a line", "import bpy\nt = bpy.data.textures.new('n', type='NOISE')\nc = bpy.data.objects['Camera'].data\nt.wrong_one = 1; c.wrong_one = 2\n", "NoiseTexture has no wrong_one"},
	} {
		dir := t.TempDir()
		script := filepath.Join(dir, "script.py")
		if err := os.WriteFile(script, []byte(c.script), 0o600); err != nil {
			t.Fatal(err)
		}
		res := realBlender(t, path, script, blenderStopAtRender+blenderCrashNames+blenderSceneFacts, blenderMeasureScene)
		exit := res.ExitCode
		res, names := takeNames(res)
		res, _, _ = takeScene(res)
		if strings.Contains(res.Output, "Blender 3.") && strings.Contains(c.has, `"`) {
			continue // these sockets still had their old names
		}
		if exit != 1 {
			t.Errorf("%s: exit %d, want the script's failure:\n%s", c.name, exit, res.Output)
		}
		if strings.Contains(res.Output, "_chimera") {
			t.Errorf("%s: the hook itself failed:\n%s", c.name, res.Output)
		}
		if c.has == "" {
			if names.Wrong != "" && c.name != "a modifier made by a call" {
				t.Errorf("%s: %q", c.name, names.line())
			}
			continue
		}
		if !strings.Contains(names.line(), c.has) {
			t.Errorf("%s: want %s in %q\n%s", c.name, c.has, names.line(), res.Output)
		}
	}
}

// The hook can't change what a run means: each of these reads the same with it
// and without it, whatever the script's own code does when it's touched again.
func TestTheNamesHookLeavesTheVerdictAlone(t *testing.T) {
	path := os.Getenv("CHIMERA_TEST_BLENDER")
	if path == "" {
		path, _ = findBlender()
	}
	if path == "" {
		t.Skip("no Blender here")
	}
	for _, c := range []struct {
		name, script string
		theirs       bool // the failing object is the script's own, so no names
	}{
		{"a warning at parse time", "import bpy, re\n\ndef clean(name):\n    return re.sub(\"[^\\w]+\", \"_\", name)\n\nbpy.data.objects['Cube'].modifiers.new('b', 'BEVEL').segment = 3\n", false},
		{"a property that prints", "import bpy, sys\n\nclass R:\n    @property\n    def tex(self):\n        print('read', file=sys.stderr)\n        return bpy.data.textures.new('n', type='NOISE')\n\nr = R()\nr.tex.noise_scale = 1.0\n", false},
		{"a property that exits", "import bpy, os\n\nn = [0]\nclass R:\n    @property\n    def tex(self):\n        n[0] += 1\n        if n[0] > 1:\n            os._exit(0)\n        return bpy.data.textures.new('n', type='NOISE')\n\nr = R()\nr.tex.noise_scale = 1.0\n", false},
		{"__getattr__ that prints", "import sys\nimport bpy\n\nclass T:\n    def __getattr__(self, name):\n        print('looked up', name, file=sys.stderr)\n        raise AttributeError(name)\n\nprint(T().wrong_name)\n", true},
		{"__str__ that exits", "import bpy, os\n\nn = [0]\nclass E(AttributeError):\n    def __str__(self):\n        n[0] += 1\n        if n[0] > 1:\n            os._exit(0)\n        return 'boom'\n\nraise E('x')\n", true},
		{"a huge message", "import bpy\nraise ValueError('key \"' * 200000)\n", true},
		{"a long attribute list", "import bpy\n\nclass T:\n    pass\n\nfor i in range(100):\n    setattr(T, 'attribute_%d_' % i + 'x' * 300, 1)\nprint(T().wrong_name)\n", true},
		{"its own excepthook", "import bpy, sys\nsys.excepthook = lambda *a: print('mine')\nprint(undefined_name)\n", true},
		{"a getter on Blender's own type", "import bpy\n\ndef g(self):\n    raise ValueError('bad getter')\n\nbpy.types.Scene.sock = bpy.props.StringProperty(get=g)\nm = bpy.data.materials.new('m')\nm.use_nodes = True\nb = m.node_tree.nodes['Principled BSDF']\nb.inputs[bpy.context.scene.sock].default_value = 0.5\n", true},
		{"a getter that renders", "import bpy\n\nn = [0]\ndef g(self):\n    n[0] += 1\n    if n[0] > 1:\n        bpy.ops.render.render()\n    return 'Specular'\n\nbpy.types.Scene.sock = bpy.props.StringProperty(get=g)\nm = bpy.data.materials.new('m')\nm.use_nodes = True\nb = m.node_tree.nodes['Principled BSDF']\nb.inputs[bpy.context.scene.sock].default_value = 0.5\n", true},
		{"open wrapped with logging", "import bpy, builtins, logging\n\nreal = builtins.open\ndef mine(*a, **k):\n    logging.warning('open')\n    return real(*a, **k)\n\nbuiltins.open = mine\nprint(undefined_name)\n", true},
	} {
		dir := t.TempDir()
		script := filepath.Join(dir, "script.py")
		if err := os.WriteFile(script, []byte(c.script), 0o600); err != nil {
			t.Fatal(err)
		}
		run := func(prelude, after string) resultCheck {
			return judgeRun("run_blender", "Blender", "", c.script, realBlender(t, path, script, prelude, after))
		}
		with, without := run(blenderStopAtRender+blenderCrashNames+blenderSceneFacts, blenderMeasureScene), run(blenderStopAtRender, "")
		if with.Outcome != without.Outcome || with.Line != without.Line || with.Error != without.Error {
			t.Errorf("%s: with the hook %s line %d %q, without it %s line %d %q", c.name, with.Outcome, with.Line, with.Error, without.Outcome, without.Line, without.Error)
		}
		if c.theirs && with.Names != "" {
			t.Errorf("%s: the script's own objects get no names: %q", c.name, with.Names)
		}
	}
}

func TestAnOperatorThatDoesntExistIsTheScripts(t *testing.T) {
	crash := "Traceback (most recent call last):\n  File \"script.py\", line 3, in <module>\n    bpy.ops.object.look_at()\nAttributeError: Calling operator \"bpy.ops.object.look_at\" error, could not be found\n\nError: script failed, file: 'script.py', exiting.\n"
	out := crash + namesMarker + `{"kind":"attr","wrong":"look_at","of":"bpy.ops.object","names":["align"]}` + "\n"
	script := "import bpy\n\nbpy.ops.object.look_at()\n"
	run := func(goal, s string) string {
		return judgeRun("run_blender", "Blender 5.2.2", goal, s, runResult{ExitCode: 1, Stderr: out, Output: out}).Outcome
	}
	if c := judgeRun("run_blender", "Blender 5.2.2", "build a scene", script, runResult{ExitCode: 1, Stderr: crash, Output: crash}); c.Outcome != "unsure" {
		t.Fatalf("a family of operators Blender doesn't have may be an add-on's: %+v", c)
	}
	for _, goal := range []string{"rig it with Rigify", "use the Node Wrangler", "with the Extra Objects", "use my plugin"} {
		if got := run(goal, script); got != "unsure" {
			t.Fatalf("%s: %s", goal, got)
		}
	}
	if got := run("Add one cube and build a scene", script); got != "failed" {
		t.Fatalf("the word add one isn't an add-on: %s", got)
	}
	exportCrash := strings.ReplaceAll(strings.ReplaceAll(crash, "bpy.ops.object.look_at()", "bpy.ops.export_scene.obj(filepath='x.obj')"), "bpy.ops.object.look_at", "bpy.ops.export_scene.obj")
	exportOut := exportCrash + namesMarker + `{"kind":"attr","wrong":"obj","of":"bpy.ops.export_scene","names":["fbx"]}` + "\n"
	if c := judgeRun("run_blender", "Blender 5.2.2", "build a scene", "import bpy\n\nbpy.ops.export_scene.obj(filepath='x.obj')\n", runResult{ExitCode: 1, Stderr: exportOut, Output: exportOut}); c.Outcome != "failed" {
		t.Fatalf("a missing operator on a line about files isn't the sandbox's doing: %+v", c)
	}
	withDef := fenced("python", script) + fenced("python", "import bpy\n\nclass LookAt(bpy.types.Operator):\n    bl_idname = \"object.look_at\"\n    bl_label = \"Look\"\n\nbpy.utils.register_class(LookAt)\n")
	failed := resultCheck{Outcome: "failed", Runner: "Blender 5.2.2", Error: `AttributeError: Calling operator "bpy.ops.object.look_at" error, could not be found`}
	if c := otherBlocks(failed, withDef, script); c.Outcome != "unsure" {
		t.Fatalf("another block of the result defines it: %+v", c)
	}
	if got := run("build a scene", script); got != "failed" {
		t.Fatalf("a made-up operator: %s", got)
	}
	if got := run("use the Extra Objects add-on to build a scene", script); got != "unsure" {
		t.Fatalf("the task is about an add-on: %s", got)
	}
	if got := run("build a scene", "import bpy, addon_utils\n\nbpy.ops.object.look_at()\n"); got != "unsure" {
		t.Fatalf("the script turns one on: %s", got)
	}
}

// realBlender runs script the way runSandboxed does, without the sandbox.
func realBlender(t *testing.T, path, script, prelude, after string) runResult {
	t.Helper()
	dir := filepath.Dir(script)
	args := []string{"-b", "--factory-startup", "--python-exit-code", "1", "--python-expr", prelude, "--python", script}
	if after != "" {
		args = append(args, "--python-expr", after)
	}
	cmd := exec.Command(path, append(args, "--")...)
	cmd.Dir = dir
	var out, errs strings.Builder
	cmd.Stdout, cmd.Stderr = &out, &errs
	err := cmd.Run()
	exit := 0
	if ee, ok := err.(*exec.ExitError); ok {
		exit = ee.ExitCode()
	}
	tail := errs.String()
	if len(tail) > 19000 {
		tail = tail[len(tail)-19000:]
	}
	return runResult{ExitCode: exit, Stderr: hidePaths(tail, dir), Output: hidePaths(out.String()+errs.String(), dir)}
}
