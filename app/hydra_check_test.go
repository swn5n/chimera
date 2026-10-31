package main

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"
)

// What Blender 5.2.2 and Python 3.13 printed for real on the Studio, under the
// check's sandbox, with the throwaway folder already hidden (hidePaths).
const (
	realRadians = "Traceback (most recent call last):\n  File \"script.py\", line 60, in <module>\n    backdrop.rotation_euler = (mathutils.radians(180), 0.0, 0.0)  # flip normal\n                               ^^^^^^^^^^^^^^^^^\nAttributeError: module 'mathutils' has no attribute 'radians'\n\nError: script failed, file: 'script.py', exiting.\nBlender 5.2.2 LTS (hash d13f752e3b9c built 2026-09-15 01:49:19)\n\nBlender quit\n"
	realUnlink  = "Traceback (most recent call last):\n  File \"script.py\", line 136, in <module>\n    bpy.context.scene.collection.objects.unlink(obj)\n    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^\nRuntimeError: Error: Object 'Backdrop' not in collection 'Scene Collection'\n\n\nError: script failed, file: 'script.py', exiting.\nBlender 5.2.2 LTS (hash d13f752e3b9c built 2026-09-15 01:49:19)\n\nBlender quit\n"
	realSyntax  = "  File \"script.py\", line 4\n    def f(:\n          ^\nSyntaxError: invalid syntax\n\nError: script failed, file: 'script.py', exiting.\nBlender 5.2.2 LTS (hash d13f752e3b9c built 2026-09-15 01:49:19)\n\nBlender quit\n"
	realKwarg   = "Traceback (most recent call last):\n  File \"script.py\", line 6, in <module>\n    bpy.ops.mesh.primitive_plane_add(sizee=2)\n    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^\nTypeError: Converting py args to operator properties:: keyword \"sizee\" unrecognized\n\nError: script failed, file: 'script.py', exiting.\nScene\n['Cube', 'Light', 'Camera']\nBlender 5.2.2 LTS (hash d13f752e3b9c built 2026-09-15 01:49:19)\n\nBlender quit\n"
	realScene   = "Traceback (most recent call last):\n  File \"script.py\", line 6, in <module>\n    hero = bpy.data.objects[\"Backdrop\"]\n           ~~~~~~~~~~~~~~~~^^^^^^^^^^^^\nKeyError: 'bpy_prop_collection[key]: key \"Backdrop\" not found'\n\nError: script failed, file: 'script.py', exiting.\n"
	realSocket  = "script.py:3: DeprecationWarning: 'Material.use_nodes' is expected to be removed in Blender 6.0\n  mat.use_nodes = True\nTraceback (most recent call last):\n  File \"script.py\", line 6, in <module>\n    bsdf.inputs[\"Specular\"].default_value = 0.5\n    ~~~~~~~~~~~^^^^^^^^^^^^\nKeyError: 'bpy_prop_collection[key]: key \"Specular\" not found'\n\nError: script failed, file: 'script.py', exiting.\n"
	// Blender's own print landed between the traceback's first lines (stdout
	// and stderr mixed), as it really does.
	realPoll = "Traceback (most recent call last):\nScene\n  File \"script.py\", line 6, in <module>\n    bpy.ops.object.mode_set(mode=\"EDIT\")\n    ~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^\nRuntimeError: Operator bpy.ops.object.mode_set.poll() Context missing active object\n\nError: script failed, file: 'script.py', exiting.\n"
	realSave = "Traceback (most recent call last):\n  File \"script.py\", line 6, in <module>\n    bpy.ops.wm.save_as_mainfile(filepath=\"/private/tmp/chimera-check-escape.blend\")\n    ~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nRuntimeError: Error: Cannot open file /private/tmp/chimera-check-escape.blend@ for writing: Operation not permitted\n\nError: script failed, file: 'script.py', exiting.\n"

	pyJSON  = "[{\"a\": 1}, {\"a\": 2}]\nTraceback (most recent call last):\n  File \"script.py\", line 6, in <module>\n    print(dump({1, 2}))\n          ~~~~^^^^^^^^\n  File \"script.py\", line 4, in dump\n    return json.dumps(x)\n           ~~~~~~~~~~^^^\n  File \"/Library/Frameworks/Python.framework/Versions/3.13/lib/python3.13/json/encoder.py\", line 182, in default\n    raise TypeError(f'Object of type {o.__class__.__name__} '\n                    f'is not JSON serializable')\nTypeError: Object of type set is not JSON serializable\n"
	pyArgv  = "a\nb\nTraceback (most recent call last):\n  File \"script.py\", line 5, in <module>\n    name = sys.argv[1]\n           ~~~~~~~~^^^\nIndexError: list index out of range\n"
	pyChain = "1\nTraceback (most recent call last):\n  File \"script.py\", line 4, in get\n    return data[k]\n           ~~~~^^^\nKeyError: 'b'\n\nDuring handling of the above exception, another exception occurred:\n\nTraceback (most recent call last):\n  File \"script.py\", line 8, in <module>\n    print(get(\"b\"))\n          ~~~^^^^^\n  File \"script.py\", line 6, in get\n    raise ValueError(\"no such key: \" + k)\nValueError: no such key: b\n"
	pyName  = "{\"total\": 7}\nTraceback (most recent call last):\n  File \"script.py\", line 6, in <module>\n    print(totl(items))\n          ^^^^\nNameError: name 'totl' is not defined. Did you mean: 'total'?\n"
)

func bpyScript(lines int) string {
	var b strings.Builder
	b.WriteString("import bpy\n")
	for i := 0; i < lines-1; i++ {
		fmt.Fprintf(&b, "bpy.ops.mesh.primitive_cube_add(location=(%d, 0, 0))\n", i)
	}
	return b.String()
}

func pyScript(lines int, first string) string {
	var b strings.Builder
	b.WriteString(first + "\n")
	for i := 0; i < lines-1; i++ {
		fmt.Fprintf(&b, "print(%d)\n", i)
	}
	return b.String()
}

func fenced(lang, body string) string { return "```" + lang + "\n" + body + "```\n" }

func TestPickScriptFindsTheDeliverable(t *testing.T) {
	blenderPlan := map[string]bool{"blender": true}
	codePlan := map[string]bool{"code": true, "writing": true}
	writing := map[string]bool{"writing": true}
	main := bpyScript(8)
	for _, c := range []struct {
		name   string
		kinds  map[string]bool
		result string
		kind   string
		script string
		why    string
	}{
		{"a Blender script and how to run it", blenderPlan, "Here it is:\n" + fenced("python", main) + "Run it:\n" + fenced("bash", "blender -b --python studio.py\n"), "run_blender", main, ""},
		{"an unlabelled Blender block in a code plan", codePlan, fenced("", main), "run_blender", main, ""},
		{"the main script, not a short extra", blenderPlan, fenced("python", bpyScript(30)) + fenced("python", bpyScript(6)), "run_blender", bpyScript(30), ""},
		{"one Python script in a code plan", codePlan, fenced("py", pyScript(8, "import json")), "run_python", pyScript(8, "import json"), ""},
		{"a 4-line snippet", blenderPlan, fenced("python", bpyScript(4)), "", "", ""},
		{"a fence that never closes", blenderPlan, "```python\n" + main, "", "", ""},
		{"bpy used without importing it (a fragment)", blenderPlan, fenced("python", strings.TrimPrefix(main, "import bpy\n")+"x = 1\ny = 2\n"), "", "", ""},
		{"plain Python in a Blender plan", blenderPlan, fenced("python", pyScript(8, "import json")), "", "", ""},
		{"a Blender script in a writing plan", writing, fenced("python", main), "", "", ""},
		{"a REPL session", codePlan, fenced("python", ">>> import json\n"+pyScript(8, "import os")), "", "", ""},
		{"two Blender scripts of similar size", blenderPlan, fenced("python", bpyScript(20)) + fenced("python", bpyScript(15)), "run_blender", "", "the result has 2 Blender scripts of similar size, and it isn't clear which one to run"},
		{"two Python files", codePlan, fenced("python", pyScript(8, "import os")) + fenced("python", pyScript(8, "import sys")), "run_python", "", "the result has 2 Python files; Hydra only runs a result that is one script"},
		{"a window", codePlan, fenced("python", pyScript(8, "import tkinter")), "run_python", "", "it would open a window or start a server"},
		{"a ~~~ fence holding ```", blenderPlan, "~~~python\n" + main + "```\nnot a fence\n```\n~~~\n", "run_blender", main + "```\nnot a fence\n```", ""},
		{"a fence in a list item", blenderPlan, "1. Save this as studio.py:\n   ```python\n" + indent(main, "   ") + "   ```\n", "run_blender", main, ""},
		{"a script indented as a whole", blenderPlan, fenced("python", indent(main, "    ")), "run_blender", main, ""},
	} {
		kind, script, why := pickScript(c.kinds, c.result)
		if kind != c.kind || strings.TrimSpace(script) != strings.TrimSpace(c.script) || why != c.why {
			t.Errorf("%s: got (%q, %d-char script, %q), want (%q, %d chars, %q)", c.name, kind, len(script), why, c.kind, len(c.script), c.why)
		}
	}
}

func indent(s, by string) string {
	lines := strings.Split(strings.TrimSuffix(s, "\n"), "\n")
	for i := range lines {
		lines[i] = by + lines[i]
	}
	return strings.Join(lines, "\n") + "\n"
}

// A NameError for something another block of the result defines only means
// the check ran one block on its own: unsure, not a crash.
func TestNameFromAnotherBlockIsNotACrash(t *testing.T) {
	helper := "def make_material(name):\n    return bpy.data.materials.new(name)\n"
	main := "import bpy\nmat = make_material('chimera_mat')\nbpy.ops.mesh.primitive_cube_add()\ncube = bpy.context.active_object\ncube.name = 'chimera_cube'\ncube.data.materials.append(mat)\n"
	result := "Add this helper first:\n" + fenced("python", helper) + "Then the script:\n" + fenced("python", main)
	kind, script, _ := pickScript(map[string]bool{"blender": true}, result)
	if kind != "run_blender" || !strings.HasPrefix(script, "import bpy") {
		t.Fatalf("the main script runs: %q %q", kind, script)
	}
	crash := judgeRun(kind, "Blender 5.2.2", "", script, blenderRun(1, "Traceback (most recent call last):\n  File \"script.py\", line 2, in <module>\n    mat = make_material('chimera_mat')\nNameError: name 'make_material' is not defined\n"))
	if crash.Outcome != "failed" {
		t.Fatalf("on its own it's a crash: %+v", crash)
	}
	if c := otherBlocks(crash, result, script); c.Outcome != "unsure" || !strings.Contains(c.Summary, "make_material, which another code block of the result has") {
		t.Fatalf("with the helper elsewhere in the result: %+v", c)
	}
	// A plain import or a tuple assignment in the other block counts too, and
	// so does a property an add-on block registers.
	for _, c := range []struct{ other, err string }{
		{"import bpy\nimport bmesh\n", "NameError: name 'bmesh' is not defined"},
		{"floor, wall = [None, None]\n", "NameError: name 'floor' is not defined"},
		{"import bpy\nbpy.types.Scene.studio = bpy.props.PointerProperty(type=StudioProps)\n", "AttributeError: 'Scene' object has no attribute 'studio'"},
	} {
		failed := resultCheck{Outcome: "failed", Runner: "Blender 5.2.2", Error: c.err}
		if got := otherBlocks(failed, fenced("python", c.other)+fenced("python", main), main); got.Outcome != "unsure" {
			t.Errorf("%s with %q in another block: %+v", c.err, c.other, got)
		}
	}
	if c := otherBlocks(crash, fenced("python", main), script); c.Outcome != "failed" {
		t.Fatalf("defined nowhere: still a crash: %+v", c)
	}
}

// The reply's note and the card speak of the final round's check only.
func TestOnlyTheFinalRoundsCheckLabelsTheResult(t *testing.T) {
	rec := TaskRecord{Round: 2, Checks: []resultCheck{{Round: 1, Outcome: "cut_off"}}}
	if c := finalCheck(rec); c.Outcome != "" {
		t.Fatalf("round 2 had nothing to check, so round 1's cut-off says nothing about it: %+v", c)
	}
	rec.Checks = append(rec.Checks, resultCheck{Round: 2, Outcome: "failed"})
	if c := finalCheck(rec); c.Outcome != "failed" {
		t.Fatalf("round 2's own check: %+v", c)
	}
	if planPrior("", "The result was cut off…") == "" || planPrior("", "") != "" || planPrior("x", "y") != "x" {
		t.Fatal("an empty cut-off result still sends its critique to the planner")
	}
	if c := judgeRun("run_python", "Python", "", "", runResult{Skipped: true, Summary: "The test run was cancelled."}); c.Summary != "Didn't finish the script: the check was stopped." {
		t.Fatalf("a stopped check says so: %q", c.Summary)
	}
}

// tb is a traceback ending the run at line of script.py.
func tb(line int, source, errLine string) string {
	return fmt.Sprintf("Traceback (most recent call last):\n  File \"script.py\", line %d, in <module>\n    %s\n%s\n", line, source, errLine)
}

func blenderRun(exit int, stderr string) runResult {
	return runResult{ExitCode: exit, Stderr: stderr, Output: stderr, Seconds: 0.6}
}

func TestJudgeReadsRealBlenderErrors(t *testing.T) {
	const runner, goal = "Blender 5.2.2", "Write a Python script for Blender 5 that builds a product-shot studio"
	for _, c := range []struct {
		name    string
		res     runResult
		goal    string
		outcome string
		want    string // in the summary
		script  string
	}{
		{"mathutils.radians", blenderRun(1, realRadians), goal, "failed", "line 60: AttributeError: module 'mathutils' has no attribute 'radians'", ""},
		{"unlink from the wrong collection", blenderRun(1, realUnlink), goal, "failed", "line 136: RuntimeError: Error: Object 'Backdrop' not in collection", ""},
		{"a SyntaxError (no Traceback line)", blenderRun(1, realSyntax), goal, "failed", "line 4: SyntaxError: invalid syntax", ""},
		{"a misspelt operator keyword", blenderRun(1, realKwarg), goal, "failed", `keyword "sizee" unrecognized`, ""},
		{"a socket renamed in 4.x", blenderRun(1, realSocket), goal, "failed", `key "Specular" not found`, ""},
		{"an object only the person's scene has", blenderRun(1, realScene), goal, "unsure", "“Backdrop”, which a fresh scene doesn't have", ""},
		{"a poll() failure, with stdout mixed in", blenderRun(1, realPoll), goal, "unsure", "a fresh scene rather than the script", ""},
		{"saving outside the sandbox", blenderRun(1, realSave), goal, "unsure", "line 6 on RuntimeError: Error: Cannot open file", ""},
		{"a task for another Blender", blenderRun(1, realRadians), "A studio script for Blender 4.2", "unsure", "the task is for Blender 4", ""},
		{"Blender 3D isn't a version", blenderRun(1, realRadians), "Make a Blender 3D studio", "failed", "line 60", ""},
		{"timed out", runResult{TimedOut: true, ExitCode: -1}, goal, "unsure", "still running after 2 minutes", ""},
		{"Blender itself crashed", blenderRun(139, "Writing: /tmp/blender.crash.txt\n"), goal, "unsure", "Blender itself stopped (exit code 139)", ""},
		{"no traceback", blenderRun(1, "Error: script failed, file: 'script.py', exiting.\n"), goal, "unsure", "without a Python error message", ""},
		{"ran to the end but printed a traceback", blenderRun(0, realScene), goal, "unsure", "it ran to the end but printed a Python error", ""},
		{"clean", blenderRun(0, "Blender 5.2.2 LTS\n\nBlender quit\n"), goal, "passed", "no errors (0.6 s)", ""},
		{"stopped at its render", runResult{ExitCode: 0, Output: renderStopMarker + "\n", Seconds: 0.5}, goal, "passed", "no errors up to its render", ""},
		{"the sandbox didn't start", runResult{Skipped: true}, goal, "skipped", "the sandbox couldn't start here", ""},
		{"not run", runResult{NotRun: true, Summary: "This computer doesn't have the program needed for this test."}, goal, "skipped", "Didn't run the script: this computer doesn't have the program needed for this test.", ""},
		// The review's cases, with what Blender 5.2.2 really printed.
		{"the camera the person has selected", blenderRun(1, tb(4, "cam.data.lens = 85", "AttributeError: 'Mesh' object has no attribute 'lens'")), goal, "unsure", "what you have selected",
			"import bpy\ncam = bpy.context.active_object\nprint(cam.name)\ncam.data.lens = 85\n"},
		{"its own new object's removed API stays a crash", blenderRun(1, tb(4, "obj.data.use_auto_smooth = True", "AttributeError: 'Mesh' object has no attribute 'use_auto_smooth'")), goal, "failed", "use_auto_smooth",
			"import bpy\nbpy.ops.mesh.primitive_uv_sphere_add()\nobj = bpy.context.active_object\nobj.data.use_auto_smooth = True\n"},
		{"needs Edit Mode", blenderRun(1, tb(6, "bm = bmesh.from_edit_mesh(me)", "ValueError: The mesh must be in editmode")), goal, "unsure", "what you have selected",
			"import bpy, bmesh\nobj = bpy.context.edit_object\nme = obj.data\nprint(me)\nx = 1\nbm = bmesh.from_edit_mesh(me)\n"},
		{"an add-on the person installed", blenderRun(1, tb(4, "bpy.ops.preferences.addon_enable(module=\"bl_ext.user_default.fog\")", "RuntimeError: Error: Add-on not loaded: \"bl_ext.user_default.fog\", cause: No module named 'bl_ext.user_default.fog'")), goal, "unsure", "a fresh scene rather than the script", ""},
		{"a GPU backend for another computer", blenderRun(1, tb(6, "prefs.compute_device_type = 'OPTIX'", "TypeError: bpy_struct: item.attr = val: enum \"OPTIX\" not found in ('NONE', 'METAL')")), goal, "unsure", "GPU backend (OPTIX)", ""},
		{"an add-on's render engine", blenderRun(1, tb(3, "scene.render.engine = 'HYDRA_STORM'", "TypeError: bpy_struct: item.attr = val: enum \"HYDRA_STORM\" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH', 'CYCLES')")), goal, "unsure", "render engine",
			"import bpy\nscene = bpy.context.scene\nscene.render.engine = 'HYDRA_STORM'\n"},
		{"arguments after --", blenderRun(1, tb(6, "src, dst = args", "ValueError: not enough values to unpack (expected 2, got 0)")), goal, "unsure", "command-line arguments",
			"import bpy, sys\nargv = sys.argv\nargs = argv[argv.index('--') + 1:]\nx = 1\ny = 2\nsrc, dst = args\n"},
		{"an import call over several lines", blenderRun(1, tb(7, "bpy.ops.wm.ply_import(", "RuntimeError: Error: PLY Importer: f_230: Invalid PLY header.")), goal, "unsure", "reads or writes files",
			"import bpy\nx = 1\ny = 2\nz = 3\nw = 4\nv = 5\nbpy.ops.wm.ply_import(\n    filepath='/Users/fx/scan.ply',\n)\n"},
		{"a handled error, then exit 1 for another reason", blenderRun(1, tb(16, "total = float(rows)", "TypeError: float() argument must be a string or a real number, not 'list'")+"ERROR couldn't upload the total\n"), goal, "unsure", "it went on from", ""},
		{"the goal names 5.0, checked on 5.2", blenderRun(1, realRadians), "A studio for Blender 5.0", "unsure", "the task is for Blender 5.0", ""},
		{"the goal says Blender v4.2", blenderRun(1, realRadians), "a studio script (Blender v4.2 LTS)", "unsure", "the task is for Blender 4", ""},
	} {
		got := judgeRun("run_blender", runner, c.goal, c.script, c.res)
		if got.Outcome != c.outcome || !strings.Contains(got.Summary, c.want) {
			t.Errorf("%s: got %s %q, want %s containing %q", c.name, got.Outcome, got.Summary, c.outcome, c.want)
		}
		if strings.Contains(got.Error, "script failed") {
			t.Errorf("%s: Blender's own footer taken as the error: %q", c.name, got.Error)
		}
	}
	got := judgeRun("run_blender", runner, goal, "", blenderRun(1, realRadians))
	if got.Line != 60 || got.Source != "backdrop.rotation_euler = (mathutils.radians(180), 0.0, 0.0)  # flip normal" {
		t.Fatalf("the crash should name its line and source: %+v", got)
	}
}

func TestJudgeReadsPythonErrors(t *testing.T) {
	const runner = "Python 3.13.12"
	for _, c := range []struct {
		name    string
		res     runResult
		outcome string
		want    string
		script  string
	}{
		{"a NameError in the script", blenderRun(1, pyName), "failed", "line 6: NameError: name 'totl' is not defined. Did you mean: 'total'?", ""},
		{"a TypeError inside json", blenderRun(1, pyJSON), "unsure", "TypeError inside encoder.py, not in the script itself", ""},
		{"no command-line argument", blenderRun(1, pyArgv), "unsure", "reading command-line arguments", ""},
		{"argparse's usage exit", blenderRun(2, "usage: script.py [-h] folder\nscript.py: error: the following arguments are required: folder\n"), "unsure", "exit code 2 and no Python error", ""},
		{"typed input", blenderRun(1, "Traceback (most recent call last):\n  File \"script.py\", line 3, in <module>\n    name = input(\"Name? \")\nEOFError: EOF when reading a line\n"), "unsure", "typed input", ""},
		{"a missing file", blenderRun(1, "Traceback (most recent call last):\n  File \"script.py\", line 2, in <module>\n    data = load()\nFileNotFoundError: [Errno 2] No such file or directory: 'data.csv'\n"), "unsure", "FileNotFoundError", ""},
		{"a KeyError", blenderRun(1, "Traceback (most recent call last):\n  File \"script.py\", line 2, in <module>\n    x = d[\"b\"]\nKeyError: 'b'\n"), "unsure", "may depend on its inputs", ""},
		{"chained: the last error counts", blenderRun(1, pyChain), "unsure", "line 6 on ValueError: no such key: b", ""},
		{"a missing module", blenderRun(1, "Traceback (most recent call last):\n  File \"script.py\", line 1, in <module>\n    import numpy\nModuleNotFoundError: No module named 'numpy'\n"), "unsure", "needs the numpy module", ""},
		{"timed out", runResult{TimedOut: true, ExitCode: -1}, "unsure", "after 30 seconds", ""},
		{"a call only another OS has", blenderRun(1, "Traceback (most recent call last):\n  File \"script.py\", line 9, in <module>\n    cpus = os.sched_getaffinity(0)\nAttributeError: module 'os' has no attribute 'sched_getaffinity'\n"), "unsure", "operating system doesn't have", ""},
		{"re.error is read as an error, not a crash", blenderRun(1, "Traceback (most recent call last):\n  File \"script.py\", line 2, in <module>\n    re.compile('(')\nre.error: missing ), unterminated subpattern at position 0\n"), "unsure", "re.error", ""},
	} {
		got := judgeRun("run_python", runner, "a script", c.script, c.res)
		if got.Outcome != c.outcome || !strings.Contains(got.Summary, c.want) {
			t.Errorf("%s: got %s %q, want %s containing %q", c.name, got.Outcome, got.Summary, c.outcome, c.want)
		}
	}
	if e, ok := lastPyError(pyJSON); !ok || len(e.Frames) != 3 || e.Frames[2].Source != "raise TypeError(f'Object of type {o.__class__.__name__} '" {
		t.Fatalf("caret lines and a continued source line are skipped: %+v", e)
	}
}

func TestCheckCritiqueNamesTheError(t *testing.T) {
	c := judgeRun("run_blender", "Blender 5.2.2", "a studio", "", blenderRun(1, realRadians))
	cr := crashCritique("run_blender", "Blender 5.2.2", c)
	for _, want := range []string{"Blender 5.2.2", "blender -b --factory-startup --python script.py", "line 60", "mathutils.radians(180)", "AttributeError: module 'mathutils' has no attribute 'radians'", "Fix this"} {
		if !strings.Contains(cr, want) {
			t.Errorf("the critique should say %q:\n%s", want, cr)
		}
	}
	if strings.Contains(cr, "/var/folders") || strings.Contains(cr, "/private") || len(cr) > 1000 {
		t.Errorf("no paths, under 1,000 characters:\n%s", cr)
	}
	py := crashCritique("run_python", "Python 3.13.12", judgeRun("run_python", "Python 3.13.12", "", "", blenderRun(1, pyName)))
	if !strings.Contains(py, "no command-line arguments, no typed input and no network") {
		t.Errorf("the Python critique should say how it ran:\n%s", py)
	}
	cut := cutCritique(passResult{Text: "the end of the result was here and then", Model: "big:70b", Tokens: 4096})
	for _, want := range []string{"big:70b", "4096 tokens", "the end of the result was here and then", "complete to the end"} {
		if !strings.Contains(cut, want) {
			t.Errorf("the cut-off critique should say %q:\n%s", want, cut)
		}
	}
	dir := "/var/folders/ab/xyz/T/chimera-test-1"
	got := hidePaths("File \"/private/var/folders/ab/xyz/T/chimera-test-1/script.py\"; File \""+dir+"/script.py\"", dir)
	if got != "File \"script.py\"; File \"script.py\"" {
		t.Fatalf("both forms of the folder are hidden, with nothing left behind: %q", got)
	}
}

func TestLoopStopsOnTheSameFault(t *testing.T) {
	crash := resultCheck{Outcome: "failed", Error: "AttributeError: x"}
	other := resultCheck{Outcome: "failed", Error: "NameError: y"}
	cut := resultCheck{Outcome: "cut_off"}
	for _, c := range []struct {
		chk, prev resultCheck
		want      string
	}{
		{crash, resultCheck{}, "again"},
		{crash, crash, "stop"},
		{other, crash, "again"},
		{cut, cut, "stop"},
		{cut, crash, "again"},
		{resultCheck{Outcome: "passed"}, crash, "review"},
		{resultCheck{Outcome: "unsure"}, crash, "review"},
		{resultCheck{Outcome: "skipped"}, resultCheck{}, "review"},
		{resultCheck{}, resultCheck{}, "review"},
	} {
		if got := loopNext(c.chk, c.prev); got != c.want {
			t.Errorf("loopNext(%s %q after %s %q) = %s, want %s", c.chk.Outcome, c.chk.Error, c.prev.Outcome, c.prev.Error, got, c.want)
		}
	}
	for _, c := range [][3]int{{4096, 4096, 8192}, {7912, 4096, 15824}, {20000, 8192, 16384}, {100, 4096, 8192}} {
		if got := cutRoom(c[0], c[1]); got != c[2] {
			t.Errorf("cutRoom(%d, %d) = %d, want %d", c[0], c[1], got, c[2])
		}
	}
}

func checkApp(t *testing.T, cfg Config) *App {
	t.Helper()
	a := &App{dataDir: t.TempDir(), cfg: cfg, quit: make(chan struct{})}
	a.tools = NewToolScanner(a)
	a.tools.ext["blender"] = ToolInfo{ID: "blender", Have: true, Path: "/Applications/Blender.app/Contents/MacOS/Blender", Version: "Blender 5.2.2"}
	a.tools.ext["python"] = ToolInfo{ID: "python", Have: true, Path: "/usr/local/bin/python3", Version: "Python 3.13.12"}
	return a
}

// Each kind of script run has its own consent: the library's test runs and
// the check of a long task's result never switch each other on.
func TestResultChecksNeedTheirOwnConsent(t *testing.T) {
	script := bpyScript(8)
	a := checkApp(t, Config{RunTests: true})
	if _, why := a.scriptBlocker("run_blender", script); !strings.Contains(why, "in Settings") {
		t.Fatalf("library test runs on, checks off: %q", why)
	}
	a = checkApp(t, Config{CheckResults: true})
	if res := a.runScript(context.Background(), "run_blender", script); res.Summary != "Test runs are turned off on this computer." {
		t.Fatalf("checks on, library test runs off: %+v", res)
	}
	if !checkSandboxOK() {
		if _, why := a.scriptBlocker("run_blender", script); !strings.Contains(why, "sandbox") {
			t.Fatalf("no sandbox here: %q", why)
		}
		return
	}
	if runner, why := a.scriptBlocker("run_blender", script); why != "" || runner != "Blender 5.2.2" {
		t.Fatalf("this should run: %q %q", runner, why)
	}
	// The sandbox is the boundary for checks: no word list skips a script
	// (Blender node code often has a variable called socket). Library test
	// runs keep their pre-filter.
	risky := script + "import subprocess\nfor socket in []:\n    subprocess.run(['ls'])\n"
	if _, why := a.scriptBlocker("run_blender", risky); why != "" {
		t.Fatalf("checks don't pre-filter: %q", why)
	}
	lib := checkApp(t, Config{RunTests: true})
	if res := lib.runScript(context.Background(), "run_blender", risky); !res.NotRun || !strings.HasPrefix(res.Summary, "Refused") {
		t.Fatalf("library test runs still refuse it: %+v", res)
	}
	a.tools.ext["blender"] = ToolInfo{ID: "blender", Have: true, Path: "/Applications/Blender 3.6.app/Contents/MacOS/Blender", Version: "Blender 3.6.23"}
	if _, why := a.scriptBlocker("run_blender", script); !strings.Contains(why, "isn't the Blender 4.x or 5.x") {
		t.Fatalf("Blender 3.6: %q", why)
	}
	a.tools.ext["python"] = ToolInfo{ID: "python", Have: true, Path: "/usr/bin/python3"}
	if _, why := a.scriptBlocker("run_python", pyScript(8, "import os")); why != "this computer's Python version is unknown" {
		t.Fatalf("unknown Python: %q", why)
	}
	a.tools.ext["python"] = ToolInfo{ID: "python", Have: true, Path: "/usr/bin/python3", Version: "Python 3.9.6"}
	if _, why := a.scriptBlocker("run_python", pyScript(8, "import os")); !strings.Contains(why, "older than Python 3.10") {
		t.Fatalf("Python 3.9: %q", why)
	}
	delete(a.tools.ext, "python")
	if _, why := a.scriptBlocker("run_python", pyScript(8, "import os")); why != "Python isn't installed on this computer" {
		t.Fatalf("no Python: %q", why)
	}
	// On once, for new and existing installs; then it stays what the person chose.
	dir := t.TempDir()
	if c := loadConfig(dir); !c.CheckResults || !c.CheckResultsInit {
		t.Fatalf("a fresh config checks results: %+v", c)
	}
	if err := os.WriteFile(filepath.Join(dir, "config.json"), []byte(`{"check_results": false, "check_results_init": true}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if c := loadConfig(dir); c.CheckResults {
		t.Fatal("turned off stays off")
	}
}

func TestScriptSandboxProfile(t *testing.T) {
	const blender = "/Applications/Blender 3.app/Contents/MacOS/Blender"
	p := macScriptProfile(blender, "/private/var/folders/ab/T/chimera-test-1")
	for _, want := range []string{"(deny network*)", "(deny appleevent-send)", `(global-name "com.apple.coreservices.launchservicesd")`,
		`(global-name "com.apple.pasteboard.1")`, "(deny process-exec*)", `(literal "` + blender + `")`, `(subpath "/Applications/Blender 3.app")`,
		"(deny process-fork)", "(deny signal)", "(allow signal (target self))"} {
		if !strings.Contains(p, want) {
			t.Errorf("the profile should have %s:\n%s", want, p)
		}
	}
	var writes string
	for _, l := range strings.Split(p, "\n") {
		if strings.HasPrefix(l, "(allow file-write*") {
			writes = l
		}
	}
	if !strings.Contains(writes, `(subpath "/private/var/folders/ab/T/chimera-test-1")`) || strings.Contains(writes, `(subpath "/private/var/folders")`) || strings.Contains(writes, "/private/tmp") {
		t.Errorf("writes only in the run folder: %s", writes)
	}
	for _, l := range strings.Split(macScriptProfile("/usr/bin/python3", "/tmp/x"), "\n") {
		if strings.HasPrefix(l, "(allow process-exec*") && strings.Contains(l, `(subpath "/usr")`) {
			t.Errorf("/usr is never a place programs may be started from: %s", l)
		}
	}
	// A program that is a script starts its interpreter, which must be allowed.
	fake := filepath.Join(t.TempDir(), "blender")
	if err := os.WriteFile(fake, []byte("#!/usr/local/bin/python3 -I\nprint('hi')\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	if p := macScriptProfile(fake, t.TempDir()); !strings.Contains(p, `(literal "/usr/local/bin/python3")`) {
		t.Errorf("the #! interpreter may run:\n%s", p)
	}
	// Homebrew's Blender is a #!/bin/bash launcher: it may start the app it
	// names, and /bin's "home" ("/") must never become readable.
	shim := filepath.Join(t.TempDir(), "blender")
	if err := os.WriteFile(shim, []byte("#!/bin/bash\nexec '/Applications/Blender 3.app/Contents/MacOS/Blender' \"$@\"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	p = macScriptProfile(shim, "/private/var/folders/ab/T/chimera-test-2")
	if !strings.Contains(p, `(subpath "/Applications/Blender 3.app")`) || !strings.Contains(p, `(literal "/bin/bash")`) {
		t.Errorf("the launcher and the app it starts may run:\n%s", p)
	}
	if strings.Contains(p, `(subpath "/")`) {
		t.Errorf("nothing makes the whole disk readable again:\n%s", p)
	}
	if a := strings.Join(bwrapScriptArgs("/usr/bin/bwrap", "/usr/bin/blender", []string{"-b"}, "/tmp/x"), " "); !strings.Contains(a, "--tmpfs /run") {
		t.Errorf("bwrap hides /run: %s", a)
	}
}

// The model's done_reason travels from the worker through the hub to the
// computer that asked, live and on a replay.
func TestDoneReasonReachesTheAsker(t *testing.T) {
	h := helperTestHub(t)
	worker := lender("w", "Studio", "Andrews", bigM)
	asker := &hubDevice{ID: "a", Name: "Asker", Owner: "Andrews", online: true, lastSeen: time.Now()}
	h.st.Devices["w"], h.st.Devices["a"] = worker, asker
	st := &hubStep{ID: "s1", RequesterID: asker.ID, RequesterOwner: asker.Owner, RequesterName: asker.Name, Status: "assigned",
		Assigned: worker.ID, RunModel: "big:70b", Attempts: 1, Exclude: map[string]bool{}, subs: map[chan hubEvent]struct{}{}}
	h.steps[st.ID] = st
	ch := make(chan hubEvent, 8)
	st.subs[ch] = struct{}{}
	req := httptest.NewRequest("POST", "/v1/steps/s1/complete", strings.NewReader(`{"stats":{"eval_count":9,"done_reason":"length"}}`))
	req.SetPathValue("id", "s1")
	rr := httptest.NewRecorder()
	h.handleComplete(rr, req, worker)
	if rr.Code != 200 {
		t.Fatalf("complete: %d %s", rr.Code, rr.Body)
	}
	var live hubEvent
	for len(ch) > 0 {
		if ev := <-ch; ev.Type == "done" {
			live = ev
		}
	}
	if live.Stats == nil || live.Stats.DoneReason != "length" || genFromHub(live).DoneReason != "length" {
		t.Fatalf("the live done event should carry done_reason: %+v", live)
	}
	r := h.replayLocked(st)
	if last := r[len(r)-1]; last.Type != "done" || genFromHub(last).DoneReason != "length" {
		t.Fatalf("a replay too: %+v", last)
	}
	if genFromHub(hubEvent{Type: "done", Stats: &ChatStats{EvalCount: 3}}).DoneReason != "" {
		t.Fatal("an older worker sends none")
	}
}

func TestChatStreamReadsDoneReason(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintln(w, `{"message":{"role":"assistant","content":"part"},"done":false}`)
		fmt.Fprintln(w, `{"message":{"role":"assistant","content":""},"done":true,"done_reason":"length","eval_count":4096}`)
	}))
	defer srv.Close()
	stats, err := NewOllamaClient(srv.URL).ChatStream(context.Background(), "big:70b", []ChatMessage{{Role: "user", Content: "hi"}}, nil, nil, func(string, string) {})
	if err != nil || stats.DoneReason != "length" || stats.EvalCount != 4096 {
		t.Fatalf("got %+v %v", stats, err)
	}
}

func TestTailBufferKeepsTheEnd(t *testing.T) {
	b := &tailBuffer{max: 100}
	var wg sync.WaitGroup
	for g := 0; g < 2; g++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; i < 500; i++ {
				fmt.Fprintf(b, "line %d\n", i)
			}
		}()
	}
	wg.Wait()
	b.Write([]byte("THE END\n"))
	if s := b.String(); !strings.HasSuffix(s, "THE END\n") || len(s) > 100+len("…") {
		t.Fatalf("keeps only the last 100 bytes, end intact: %d %q", len(s), s)
	}
}

// The check really runs a script in the sandbox (macOS only, where the tests
// can count on sandbox-exec and a Python).
func TestCheckRunsAPythonScriptForReal(t *testing.T) {
	if runtime.GOOS != "darwin" || !checkSandboxOK() {
		t.Skip("needs macOS's sandbox")
	}
	py := findPython()
	if py == "" {
		t.Skip("no Python here")
	}
	a := checkApp(t, Config{CheckResults: true})
	a.tools.ext["python"] = ToolInfo{ID: "python", Have: true, Path: py, Version: "Python 3.13"}
	res := a.checkScript(context.Background(), "run_python", "items = [1, 2]\nprint(sum(itms))\n")
	c := judgeRun("run_python", "Python", "", "", res)
	if c.Outcome != "failed" || c.Line != 2 || !strings.Contains(c.Error, "NameError") || strings.Contains(res.Stderr, "chimera-test-") {
		t.Fatalf("a NameError on line 2, paths hidden: %+v\n%s", c, res.Stderr)
	}
	home, _ := os.UserHomeDir()
	res = a.checkScript(context.Background(), "run_python", fmt.Sprintf(`import os
try:
    os.listdir(%q)
    print("home: READABLE")
except PermissionError:
    print("home: hidden")
try:
    os.fork()
    print("fork: ALLOWED")
except PermissionError:
    print("fork: blocked")
try:
    os.kill(os.getppid(), 0)  # the same user's process: only the sandbox stops this
    print("signal: ALLOWED")
except PermissionError:
    print("signal: blocked")
`, home))
	if !res.OK || !strings.Contains(res.Output, "home: hidden") || !strings.Contains(res.Output, "fork: blocked") || !strings.Contains(res.Output, "signal: blocked") {
		t.Fatalf("the real home folder is hidden, and the script can't fork or signal others: %+v", res)
	}
	ctx, cancel := context.WithCancel(context.Background())
	time.AfterFunc(300*time.Millisecond, cancel)
	start := time.Now()
	res = a.checkScript(ctx, "run_python", "import time\nwhile True:\n    time.sleep(0.1)\n")
	if !res.Skipped || time.Since(start) > 10*time.Second {
		t.Fatalf("a cancelled check stops promptly: %+v after %s", res, time.Since(start))
	}
}
