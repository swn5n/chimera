package main

// Facts before opinions: in looping mode ("Keep going until done"), each
// round's result is checked before anyone reviews it. A Blender or Python
// script in it runs here, in the sandbox (runner.go), and a result its model
// cut off at its output limit is caught from Ollama's done_reason. A script
// that crashes, or a result that was cut off, isn't done: the round skips the
// review and the next one gets the error as its critique. Anything the check
// can't be sure of leaves the decision to the reviewer, as before.
//
// No prompt changes: the critique reaches the planner as data, through the
// same "What still needs work" text a review's critique does, and the
// reviewer's input is unchanged (Hydra 1.0 was trained on both).

import (
	"context"
	"fmt"
	"os/exec"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
)

// synthRoom is the reply room a combine gets (NeedCtx on top of its input);
// after a cut-off the next round's combine gets more, up to synthRoomMax.
const (
	synthRoom    = 4096
	synthRoomMax = 16384
)

// checkMinLines is the fewest code lines a block needs to count as a script
// (shorter ones are snippets and examples).
const checkMinLines = 6

// resultCheck is what checking one round's result found. It goes on the task
// card; Critique is what the next round's planner gets.
type resultCheck struct {
	Round    int     `json:"round"`
	Outcome  string  `json:"outcome"`          // running, passed, failed, unsure, skipped, cut_off
	Runner   string  `json:"runner,omitempty"` // "Blender 5.2.2", "Python 3.13.12"
	Summary  string  `json:"summary"`          // the card's line
	Error    string  `json:"error,omitempty"`  // the exception line
	Line     int     `json:"line,omitempty"`
	Source   string  `json:"source,omitempty"` // that line of the script
	Model    string  `json:"model,omitempty"`  // cut_off: who stopped at the limit
	Tokens   int     `json:"tokens,omitempty"` // cut_off: how much it wrote
	Output   string  `json:"output,omitempty"` // the end of what it printed, paths hidden
	Seconds  float64 `json:"seconds,omitempty"`
	Stopped  bool    `json:"stopped,omitempty"` // the same fault as the round before, so Hydra stopped
	Critique string  `json:"-"`
}

// notDone says whether the check overrules any review: the script crashed,
// or the result was cut off.
func (c resultCheck) notDone() bool { return c.Outcome == "failed" || c.Outcome == "cut_off" }

// sameFault says whether two rounds failed the same way (the line may move).
func (c resultCheck) sameFault(prev resultCheck) bool {
	return c.notDone() && prev.notDone() && c.Outcome == prev.Outcome && c.Error == prev.Error
}

// passResult is one round's result and whether its model was cut off.
type passResult struct {
	Text   string
	Cut    bool
	Model  string // who wrote it
	Tokens int
}

// ---------- finding the script ----------

type codeBlock struct {
	Lang, Body string
	Closed     bool
}

var (
	fenceOpenRe = regexp.MustCompile("^ {0,3}(`{3,}|~{3,})(.*)$")
	bpyImport   = regexp.MustCompile(`(?m)^\s*(import\s+([\w.]+\s*,\s*)*bpy\b|from\s+bpy\b)`)
	usesBpy     = regexp.MustCompile(`\bbpy\.`)
	// Scripts that would open a window or start a server never finish on their own.
	windowImport = regexp.MustCompile(`(?m)^\s*(import|from)\s+(tkinter|turtle|pygame|PyQt\d?|PySide\d?|wx|kivy|pyglet|arcade|curses|matplotlib|flask|fastapi|django|streamlit|uvicorn|aiohttp|http\.server|socketserver)\b`)
)

// codeBlocks finds the fenced code blocks in a reply (``` or ~~~).
func codeBlocks(md string) []codeBlock {
	var out []codeBlock
	var cur *codeBlock
	var fence string
	var body []string
	indent := 0 // the opening fence's, which its lines share (a fence in a list item)
	for _, line := range strings.Split(md, "\n") {
		line = strings.TrimRight(line, "\r")
		if cur == nil {
			m := fenceOpenRe.FindStringSubmatch(line)
			if m == nil || (m[1][0] == '`' && strings.Contains(m[2], "`")) {
				continue
			}
			lang := ""
			if f := strings.Fields(m[2]); len(f) > 0 {
				lang = strings.TrimPrefix(strings.Trim(strings.ToLower(f[0]), "{}"), ".")
			}
			cur, fence, body = &codeBlock{Lang: lang}, m[1], nil
			indent = len(line) - len(strings.TrimLeft(line, " "))
			continue
		}
		t := strings.TrimLeft(line, " ")
		if len(line)-len(t) <= 3 && strings.HasPrefix(t, fence[:1]) {
			run := len(t) - len(strings.TrimLeft(t, fence[:1]))
			if run >= len(fence) && strings.TrimSpace(t[run:]) == "" {
				cur.Body, cur.Closed = strings.Join(body, "\n"), true
				out = append(out, *cur)
				cur = nil
				continue
			}
		}
		for i := 0; i < indent && strings.HasPrefix(line, " "); i++ {
			line = line[1:]
		}
		body = append(body, line)
	}
	if cur != nil {
		cur.Body = strings.Join(body, "\n")
		out = append(out, *cur)
	}
	return out
}

// codeLines counts the lines that do something (not blank, not a comment).
func codeLines(body string) int {
	n := 0
	for _, l := range strings.Split(body, "\n") {
		if t := strings.TrimSpace(l); t != "" && !strings.HasPrefix(t, "#") {
			n++
		}
	}
	return n
}

func pythonLang(l string) bool {
	switch l {
	case "python", "py", "python3", "bpy":
		return true
	}
	return strings.HasSuffix(l, ".py")
}

// pickScript finds the script to check in a result: a Blender script (kind
// run_blender) for a plan that may write one, else a plain Python one for a
// coding plan. kinds are the plan's and its steps' kinds. why says why a script
// that's there won't be run; kind "" means there's nothing to check.
func pickScript(kinds map[string]bool, result string) (kind, script, why string) {
	var blender, python []codeBlock
	for _, b := range codeBlocks(result) {
		if !b.Closed || codeLines(b.Body) < checkMinLines || strings.Contains("\n"+b.Body, "\n>>> ") {
			continue
		}
		switch {
		case (pythonLang(b.Lang) || b.Lang == "") && bpyImport.MatchString(b.Body):
			blender = append(blender, b)
		case pythonLang(b.Lang) && !usesBpy.MatchString(b.Body):
			python = append(python, b) // bpy. without importing it is a fragment: neither
		}
	}
	if len(blender) > 0 && (kinds["blender"] || kinds["code"] || kinds["general"]) {
		sort.SliceStable(blender, func(i, j int) bool { return codeLines(blender[i].Body) > codeLines(blender[j].Body) })
		main := codeLines(blender[0].Body)
		similar := 1
		for _, b := range blender[1:] {
			if 2*codeLines(b.Body) > main {
				similar++
			}
		}
		if similar > 1 {
			return "run_blender", "", fmt.Sprintf("the result has %d Blender scripts of similar size, and it isn't clear which one to run", similar)
		}
		return "run_blender", dedent(blender[0].Body), ""
	}
	if len(python) > 0 && kinds["code"] {
		switch {
		case len(python) > 1:
			return "run_python", "", fmt.Sprintf("the result has %d Python files; Hydra only runs a result that is one script", len(python))
		case windowImport.MatchString(python[0].Body):
			return "run_python", "", "it would open a window or start a server"
		}
		return "run_python", dedent(python[0].Body), ""
	}
	return "", "", ""
}

// dedent takes off the indent every line of a script shares (a script
// indented as a whole can't run, and pasted in it wouldn't be).
func dedent(body string) string {
	lines := strings.Split(body, "\n")
	common := -1
	for _, l := range lines {
		if strings.TrimSpace(l) == "" {
			continue
		}
		n := len(l) - len(strings.TrimLeft(l, " \t"))
		if common < 0 || n < common {
			common = n
		}
	}
	if common <= 0 {
		return body
	}
	for i, l := range lines {
		if len(l) >= common {
			lines[i] = l[common:]
		} else {
			lines[i] = strings.TrimLeft(l, " \t")
		}
	}
	return strings.Join(lines, "\n")
}

var (
	notDefinedRe = regexp.MustCompile(`name '(\w+)' is not defined`)
	noAttrRe     = regexp.MustCompile(`'\w+' object has no attribute '(\w+)'`)
)

// inOtherBlock says whether another code block of the result matches re: the
// script may rely on it, and the check runs one block on its own.
func inOtherBlock(result, script string, re *regexp.Regexp) bool {
	for _, b := range codeBlocks(result) {
		if strings.TrimSpace(dedent(b.Body)) != strings.TrimSpace(script) && re.MatchString(b.Body) {
			return true
		}
	}
	return false
}

// otherBlocks turns a crash on something another block of the result has
// into unsure: a NameError for a name it mentions, or an AttributeError for an
// attribute it sets (an add-on block registering a property). The result may
// mean the blocks to go together.
func otherBlocks(c resultCheck, result, script string) resultCheck {
	if c.Outcome != "failed" {
		return c
	}
	if m := notDefinedRe.FindStringSubmatch(c.Error); m != nil && inOtherBlock(result, script, regexp.MustCompile(`\b`+m[1]+`\b`)) {
		c.Outcome = "unsure"
		c.Summary = sentence("Ran the script in " + c.Runner + " here but couldn't tell whether it works: it uses " + m[1] +
			", which another code block of the result has, and the check runs one block on its own")
	} else if m := noAttrRe.FindStringSubmatch(c.Error); m != nil && strings.HasPrefix(c.Error, "AttributeError") &&
		inOtherBlock(result, script, regexp.MustCompile(`\.`+m[1]+`\s*=|(?m)^\s*`+m[1]+`\s*:`)) {
		c.Outcome = "unsure"
		c.Summary = sentence("Ran the script in " + c.Runner + " here but couldn't tell whether it works: it uses ." + m[1] +
			", which another code block of the result sets up, and the check runs one block on its own")
	}
	return c
}

// ---------- whether it can run here ----------

var versionRe = regexp.MustCompile(`(\d+)\.(\d+)`)

func versionOf(s string) (major, minor int, ok bool) {
	m := versionRe.FindStringSubmatch(s)
	if m == nil {
		return 0, 0, false
	}
	major, _ = strconv.Atoi(m[1])
	minor, _ = strconv.Atoi(m[2])
	return major, minor, true
}

// checkSandboxOK says whether this computer has a sandbox strong enough for
// checks: macOS's, or bubblewrap on Linux (the unshare fallback doesn't
// confine writes).
func checkSandboxOK() bool {
	switch runtime.GOOS {
	case "darwin":
		_, err := exec.LookPath("sandbox-exec")
		return err == nil
	case "linux":
		_, err := exec.LookPath("bwrap")
		return err == nil
	}
	return false
}

// scriptBlocker says why this computer won't run a script to check it ("" if
// it will), and what it would run it with.
func (a *App) scriptBlocker(kind, script string) (runner, why string) {
	id, name := "python", "Python"
	if kind == "run_blender" {
		id, name = "blender", "Blender"
	}
	info := a.tools.Info(id)
	runner = name
	if info.Version != "" {
		runner = info.Version
	}
	switch {
	case !a.config().CheckResults:
		return runner, "turn on “Run my long tasks' scripts here to check them” in Settings to check it here"
	case !checkSandboxOK():
		return runner, "this computer can't make a sandbox for it (that needs macOS, or bwrap on Linux)"
	case info.Path == "":
		return runner, name + " isn't installed on this computer"
	}
	major, minor, ok := versionOf(info.Version)
	switch {
	case kind == "run_blender" && !ok:
		return runner, "this computer's Blender version is unknown"
	case kind == "run_blender" && (major < 4 || major > 5):
		return runner, runner + " here isn't the Blender 4.x or 5.x it's written for"
	case kind == "run_python" && !ok:
		return runner, "this computer's Python version is unknown"
	case kind == "run_python" && (major < 3 || (major == 3 && minor < 10)):
		return runner, runner + " here is older than Python 3.10"
	}
	// No riskyScript pre-filter here: the sandbox is the boundary, and the
	// library's word list (a variable called socket) would skip harmless scripts.
	return runner, ""
}

// checkScript runs a long task's script in the sandbox, stopping a Blender
// script at its first render. The caller has asked scriptBlocker first.
func (a *App) checkScript(ctx context.Context, kind, script string) runResult {
	return a.runSandboxed(ctx, kind, script, true)
}

// ---------- reading what happened ----------

var (
	frameRe = regexp.MustCompile(`^\s*File "([^"]+)", line (\d+)(?:, in (.+))?\s*$`)
	excRe   = regexp.MustCompile(`^([A-Za-z_][\w.]*)(?:: (.*))?$`)
	caretRe = regexp.MustCompile(`^\s*[~^]+\s*$`)
)

type pyFrame struct {
	File   string
	Line   int
	Func   string
	Source string
}

type pyError struct {
	Type, Msg string
	Frames    []pyFrame
	Last      bool // nothing but Blender's own closing lines came after it: it ended the run
}

// scriptFrame is the last place in the script itself (its file is script.py).
func (e pyError) scriptFrame() (pyFrame, bool) {
	for i := len(e.Frames) - 1; i >= 0; i-- {
		if e.Frames[i].File == "script.py" {
			return e.Frames[i], true
		}
	}
	return pyFrame{}, false
}

// lastInScript says whether the error happened in the script's own code.
func (e pyError) lastInScript() bool {
	return len(e.Frames) > 0 && e.Frames[len(e.Frames)-1].File == "script.py"
}

// lastPyError reads the last Python traceback in a script's output (the final
// one of a chain). A SyntaxError has no "Traceback" line, only its frame.
func lastPyError(out string) (pyError, bool) {
	var cur, last pyError
	found, inBlock := false, false
	endAt := 0
	lines := strings.Split(out, "\n")
	for i := 0; i < len(lines); i++ {
		l := strings.TrimRight(lines[i], "\r")
		if strings.HasPrefix(l, "Traceback (most recent call last):") {
			cur, inBlock = pyError{}, true
			continue
		}
		if m := frameRe.FindStringSubmatch(l); m != nil {
			if !inBlock {
				cur, inBlock = pyError{}, true
			}
			n, _ := strconv.Atoi(m[2])
			f := pyFrame{File: m[1], Line: n, Func: m[3]}
			if i+1 < len(lines) {
				next := strings.TrimRight(lines[i+1], "\r")
				if strings.HasPrefix(next, " ") && !frameRe.MatchString(next) && !caretRe.MatchString(next) {
					f.Source = strings.TrimSpace(next)
					i++
				}
			}
			cur.Frames = append(cur.Frames, f)
			continue
		}
		if !inBlock || l == "" || strings.HasPrefix(l, " ") || strings.HasPrefix(l, "\t") {
			continue
		}
		// The first line back at the margin ends the traceback: the error.
		if m := excRe.FindStringSubmatch(l); m != nil && isExcName(m[1]) && len(cur.Frames) > 0 {
			cur.Type, cur.Msg = m[1], m[2]
			last, found, endAt = cur, true, i
		}
		inBlock = false
	}
	if found {
		last.Last = true
		for _, l := range lines[endAt+1:] {
			l = strings.TrimSpace(l)
			if strings.HasPrefix(l, "Error: script failed") || strings.HasPrefix(l, "Error: Python:") {
				break // Blender's own lines after the error that ended the script
			}
			if l != "" {
				last.Last = false // the script went on after it: a handled error
				break
			}
		}
	}
	return last, found
}

// isExcName says whether a word names a Python exception. Blender's own
// "Error: script failed, …" line doesn't count.
func isExcName(t string) bool {
	base := t[strings.LastIndex(t, ".")+1:]
	switch base {
	case "Error", "Warning", "Info":
		return false
	}
	for _, s := range []string{"Error", "Exception", "Exit", "Interrupt", "Iteration", "Group"} {
		if strings.HasSuffix(base, s) {
			return true
		}
	}
	// A module's own lowercase ones: re.error, socket.gaierror, struct.error.
	return strings.Contains(t, ".") && strings.HasSuffix(base, "error")
}

var (
	noModuleRe   = regexp.MustCompile(`No module named '([^']+)'`)
	bpyImportErr = regexp.MustCompile(`cannot import name '\w+' from '(bpy|bmesh|mathutils|bpy_extras|gpu|gpu_extras|bl_math|idprop|aud|freestyle)\b`)
	readsInputRe = regexp.MustCompile(`sys\.argv|\bargv\b|os\.environ|getenv\(|\binput\(|sys\.stdin`)
	filesLineRe  = regexp.MustCompile(`open\(|\.load\(|mainfile|render\.render|save_render|\.save\(|filepath|import_|export_|_import\(|_export\(|wm\.append|wm\.link|bpy\.path|os\.path|Path\(|\.write\(|\.read\(`)
	keyNotFound  = regexp.MustCompile(`key "([^"]+)" not found`)
	goalBlender  = regexp.MustCompile(`(?i)\bblender\s*(?:v(?:ersion)?\s*)?(\d+)(?:\.(\d+|x))?(\s*d\b)?`)
	// What the person has selected or the mode they're in, which a fresh scene doesn't have…
	selectionRe = regexp.MustCompile(`bpy\.context\.(active_object|object|selected_objects|selected_editable_objects|edit_object)\b|view_layer\.objects\.active\b|bmesh\.from_edit_mesh`)
	// …unless the script makes it itself before using it.
	setsStateRe = regexp.MustCompile(`bpy\.ops\.\w+\.(\w*_add|primitive_\w+)\(|objects\.new\(|objects\.active\s*=|\.select_set\(|mode_set\(`)
	gpuEnumRe   = regexp.MustCompile(`enum "(CUDA|OPTIX|HIP|ONEAPI|METAL)" not found`)
	osAttrRe    = regexp.MustCompile(`module '(os|ctypes|signal|select|socket|fcntl|termios|resource|time|msvcrt|winreg)' has no attribute`)
	unpackRe    = regexp.MustCompile(`values to unpack`)
	editModeRe  = regexp.MustCompile(`(?i)edit ?mode`)
)

// The errors that can come from this computer, the sandbox or a fresh scene
// rather than from the script (case-insensitive, then exact).
var envMarkers = []string{"[errno", "operation not permitted", "permission denied", "read-only file system",
	"no such file or directory", "cannot open", "can't open", "unable to open", "cannot read", "failed to open",
	"failed to read", "failed to write", "no space left", "could not be found", "could not find", "poll()",
	"context is incorrect", "background mode", "nonetype", "add-on not loaded", "no module named"}
var envMarkersExact = []string{"GPU", "OpenGL", "EGL", "Metal", "Vulkan"}

var osErrors = map[string]bool{"OSError": true, "IOError": true, "EnvironmentError": true, "PermissionError": true,
	"FileNotFoundError": true, "FileExistsError": true, "IsADirectoryError": true, "NotADirectoryError": true,
	"ConnectionError": true, "ConnectionRefusedError": true, "ConnectionResetError": true, "ConnectionAbortedError": true,
	"BrokenPipeError": true, "TimeoutError": true, "BlockingIOError": true, "InterruptedError": true,
	"ProcessLookupError": true, "ChildProcessError": true}

// statementAt is the script's whole statement starting at line (a call can
// run over several lines; a traceback may show only the first).
func statementAt(script string, line int) string {
	lines := strings.Split(script, "\n")
	if line < 1 || line > len(lines) {
		return ""
	}
	var b strings.Builder
	depth := 0
	for i := line - 1; i < len(lines) && i < line+30; i++ {
		b.WriteString(lines[i] + "\n")
		depth += strings.Count(lines[i], "(") + strings.Count(lines[i], "[") + strings.Count(lines[i], "{") -
			strings.Count(lines[i], ")") - strings.Count(lines[i], "]") - strings.Count(lines[i], "}")
		if depth <= 0 {
			break
		}
	}
	return b.String()
}

// scriptBefore is the script up to and including line.
func scriptBefore(script string, line int) string {
	lines := strings.Split(script, "\n")
	if line > len(lines) {
		line = len(lines)
	}
	if line < 0 {
		line = 0
	}
	return strings.Join(lines[:line], "\n")
}

// envReason says why an error may not be the script's fault ("" if it is).
func envReason(blender bool, e pyError, f pyFrame, goal, runner, script string) string {
	at := fmt.Sprintf("line %d on %s", f.Line, errLine(e))
	stmt := statementAt(script, f.Line)
	if stmt == "" {
		stmt = f.Source
	}
	switch t := e.Type; {
	case t == "ModuleNotFoundError":
		if m := noModuleRe.FindStringSubmatch(e.Msg); m != nil {
			return "it needs the " + m[1] + " module, which isn't installed here"
		}
		return "it needs a module that isn't installed here"
	case t == "ImportError" && !(blender && bpyImportErr.MatchString(e.Msg)):
		return "it needs something this computer doesn't have installed"
	case t == "EOFError":
		return "it waits for typed input, which the check doesn't give it"
	case t == "KeyboardInterrupt" || t == "MemoryError" || t == "SystemExit" || t == "RecursionError":
		return "it stopped on " + t + ", which the check can't judge"
	case osErrors[t] || strings.HasSuffix(t, "URLError") || strings.HasPrefix(t, "socket.") || strings.HasPrefix(t, "_tkinter."):
		return "it stopped on " + t + ", which can come from the sandbox or this computer rather than the script"
	}
	low := strings.ToLower(e.Msg)
	for _, m := range envMarkers {
		if strings.Contains(low, m) {
			return "it stopped at " + at + ", which can come from this computer, the sandbox or a fresh scene rather than the script"
		}
	}
	for _, m := range envMarkersExact {
		if strings.Contains(e.Msg, m) {
			return "it stopped at " + at + ", which can come from this computer, the sandbox or a fresh scene rather than the script"
		}
	}
	if m := gpuEnumRe.FindStringSubmatch(e.Msg); m != nil {
		return "it picks a GPU backend (" + m[1] + ") this computer doesn't have; it may be meant for another computer"
	}
	if blender && strings.Contains(stmt, ".engine") && strings.Contains(e.Msg, `enum "`) {
		return "it picks a render engine this Blender doesn't have here (an add-on's?)"
	}
	if osAttrRe.MatchString(e.Msg) {
		return "it uses a call this computer's operating system doesn't have; it may be meant for another computer"
	}
	if readsInputRe.MatchString(stmt) || (readsInputRe.MatchString(script) && (e.Type == "IndexError" || unpackRe.MatchString(e.Msg))) {
		return fmt.Sprintf("it stopped at line %d reading command-line arguments, the environment or typed input, which the check doesn't give it", f.Line)
	}
	if filesLineRe.MatchString(stmt) {
		return fmt.Sprintf("it stopped at line %d on a line that reads or writes files, which the sandbox limits", f.Line)
	}
	if before := scriptBefore(script, f.Line); blender && selectionRe.MatchString(before) && !setsStateRe.MatchString(before) &&
		(noAttrRe.MatchString(e.Msg) || editModeRe.MatchString(e.Msg) || unpackRe.MatchString(e.Msg)) {
		return "it works on what you have selected or the mode you're in, which a fresh scene doesn't have"
	}
	if blender && e.Type == "KeyError" && !strings.Contains(f.Source, ".inputs[") && !strings.Contains(f.Source, ".outputs[") {
		key := ""
		if m := keyNotFound.FindStringSubmatch(e.Msg); m != nil {
			key = m[1]
		}
		if !strings.HasPrefix(key, "chimera_") {
			if key == "" {
				return "it looks up something a fresh scene doesn't have (it may expect your own scene)"
			}
			return "it looks up “" + key + "”, which a fresh scene doesn't have (it may expect your own scene)"
		}
	}
	if blender {
		switch e.Type {
		case "AttributeError", "TypeError", "ValueError", "KeyError", "RuntimeError", "ImportError":
			if v := otherBlender(goal, runner); v != "" {
				return "the task is for Blender " + v + ", and this computer checked it with " + runner
			}
		}
	}
	return ""
}

// otherBlender is the Blender version the goal names when it isn't the one
// this computer checks with ("" if it names none or the same): "5" against
// 4.2, or "5.0" against 5.2.
func otherBlender(goal, runner string) string {
	have, haveMinor, ok := versionOf(runner)
	if !ok {
		return ""
	}
	for _, m := range goalBlender.FindAllStringSubmatch(goal, -1) {
		if m[3] != "" { // "Blender 3D"
			continue
		}
		want, _ := strconv.Atoi(m[1])
		if want != have {
			return m[1]
		}
		if minor, err := strconv.Atoi(m[2]); err == nil && minor != haveMinor {
			return m[1] + "." + m[2]
		}
	}
	return ""
}

// crashType says whether an error means the script itself is broken.
func crashType(blender bool, t string) bool {
	switch t {
	case "SyntaxError", "IndentationError", "TabError", "NameError", "UnboundLocalError", "AttributeError", "TypeError":
		return true
	case "RuntimeError", "ValueError", "KeyError", "ImportError":
		return blender // Blender's API raises these for a wrong call; envReason has let through only those
	}
	return false
}

func errLine(e pyError) string {
	if e.Msg == "" {
		return e.Type
	}
	return capRunes(e.Type+": "+e.Msg, 300)
}

func capRunes(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n-1]) + "…"
}

func lowerFirst(s string) string {
	r := []rune(s)
	if len(r) > 0 && (len(r) == 1 || !(r[1] >= 'A' && r[1] <= 'Z')) {
		r[0] = []rune(strings.ToLower(string(r[0])))[0]
	}
	return string(r)
}

// judgeRun decides what a run means: failed (the script is broken), passed,
// unsure (it may be this computer or the sandbox), or skipped.
func judgeRun(kind, runner, goal, script string, res runResult) resultCheck {
	blender := kind == "run_blender"
	c := resultCheck{Runner: runner, Seconds: res.Seconds, Output: capTail(res.Output, 1500)}
	unsure := func(reason string) resultCheck {
		c.Outcome = "unsure"
		c.Summary = sentence("Ran the script in " + runner + " here but couldn't tell whether it works: " + reason)
		return c
	}
	switch {
	case res.Skipped && strings.Contains(res.Summary, "cancelled"):
		c.Outcome, c.Summary = "skipped", "Didn't finish the script: the check was stopped."
		return c
	case res.Skipped:
		c.Outcome, c.Summary = "skipped", "Didn't run the script: the sandbox couldn't start here."
		return c
	case res.NotRun:
		c.Outcome, c.Summary = "skipped", sentence("Didn't run the script: "+lowerFirst(strings.TrimSuffix(res.Summary, ".")))
		return c
	case res.TimedOut && blender:
		return unsure("it was still running after 2 minutes (a bake, a simulation or a loop?)")
	case res.TimedOut:
		return unsure("it was still running after 30 seconds (a loop, or waiting for something?)")
	}
	errs := res.Stderr
	if errs == "" {
		errs = res.Output
	}
	e, haveErr := lastPyError(errs)
	if res.ExitCode == 0 {
		switch {
		case blender && strings.Contains(res.Output, renderStopMarker):
			c.Outcome = "passed"
			c.Summary = fmt.Sprintf("Ran the script in %s here, sandboxed: no errors up to its render, which the check skips (%.1f s).", runner, res.Seconds)
			return c
		case haveErr:
			return unsure("it ran to the end but printed a Python error: " + errLine(e))
		}
		c.Outcome = "passed"
		c.Summary = fmt.Sprintf("Ran the script in %s here, sandboxed: no errors (%.1f s).", runner, res.Seconds)
		return c
	}
	if res.ExitCode != 1 {
		if blender && (res.ExitCode < 0 || res.ExitCode >= 128) {
			return unsure(fmt.Sprintf("Blender itself stopped (exit code %d), not the script", res.ExitCode))
		}
		return unsure(fmt.Sprintf("it stopped with exit code %d and no Python error", res.ExitCode))
	}
	if !haveErr {
		return unsure("it stopped without a Python error message")
	}
	if !e.Last {
		return unsure("it printed a Python error it went on from (" + errLine(e) + "), then stopped for another reason")
	}
	f, inScript := e.scriptFrame()
	if !inScript || (!blender && !e.lastInScript()) {
		where := "Python's own code"
		if len(e.Frames) > 0 {
			last := e.Frames[len(e.Frames)-1].File
			where = last[strings.LastIndexAny(last, `/\`)+1:]
		}
		return unsure("it stopped on " + e.Type + " inside " + where + ", not in the script itself")
	}
	c.Error, c.Line, c.Source = errLine(e), f.Line, capRunes(f.Source, 200)
	if why := envReason(blender, e, f, goal, runner, script); why != "" {
		return unsure(why)
	}
	if crashType(blender, e.Type) {
		c.Outcome = "failed"
		c.Summary = sentence(fmt.Sprintf("The script crashed in %s here at line %d: %s", runner, f.Line, c.Error))
		return c
	}
	return unsure(fmt.Sprintf("it stopped at line %d on %s, which may depend on its inputs or this computer", f.Line, c.Error))
}

// sentence ends s with a full stop unless it already ends a sentence.
func sentence(s string) string {
	if strings.HasSuffix(s, ".") || strings.HasSuffix(s, "?") || strings.HasSuffix(s, "!") || strings.HasSuffix(s, "…") {
		return s
	}
	return s + "."
}

func capTail(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return "…" + string(r[len(r)-n:])
}

// ---------- what the next round is told ----------

// crashCritique is the next round's critique for a script that crashed.
func crashCritique(kind, runner string, c resultCheck) string {
	var b strings.Builder
	if kind == "run_blender" {
		fmt.Fprintf(&b, "Running the script in %s (blender -b --factory-startup --python script.py: a fresh scene with only the default cube, camera and light, and no add-ons) stopped it at line %d", runner, c.Line)
	} else {
		fmt.Fprintf(&b, "Running the script with %s (python script.py, with no command-line arguments, no typed input and no network) stopped it at line %d", runner, c.Line)
	}
	b.WriteString(":\n")
	if c.Source != "" {
		b.WriteString("    " + c.Source + "\n")
	}
	b.WriteString(c.Error + "\n")
	b.WriteString("Fix this so the whole script runs from start to finish without an error. ")
	// Running stops at the first error: say so, or each round fixes one and
	// a rewrite brings the next.
	if kind == "run_blender" {
		fmt.Fprintf(&b, "Running stops at the first error, so also check the rest of the script against %s's Python API, and keep the parts that already work as they are.", runner)
	} else {
		b.WriteString("Running stops at the first error, so also check the rest of the script, and keep the parts that already work as they are.")
	}
	return capRunes(b.String(), 1000)
}

// cutCritique is the next round's critique for a result that was cut off.
func cutCritique(p passResult) string {
	who := p.Model
	if who == "" {
		who = "the model"
	}
	s := fmt.Sprintf("The result was cut off: %s stopped writing at its output limit (%d tokens), so it ends part-way and the rest is missing.", who, p.Tokens)
	if end := strings.Join(strings.Fields(capTail(p.Text, 120)), " "); end != "" {
		s += " It ends with: \"" + end + "\"."
	}
	return s + " Plan it so the finished result is complete to the end: keep the pieces tight and leave out repetition and long explanations."
}

// loopNext decides what comes after a round's check: "review" as before,
// "again" (another round with the check's critique, no review), or "stop"
// (the same crash or cut-off twice: another round won't fix it).
func loopNext(chk, prev resultCheck) string {
	switch {
	case !chk.notDone():
		return "review"
	case chk.sameFault(prev):
		return "stop"
	}
	return "again"
}

// cutRoom is the reply room for the combine after one was cut off having
// written tokens with room.
func cutRoom(tokens, room int) int {
	return clampInt(max(2*tokens, 2*room), 2*synthRoom, synthRoomMax)
}

// ---------- on the task ----------

// checkResult checks one round's result: whether it was cut off (any mode)
// and, in looping mode, whether its script runs. The check goes on the task
// card; the zero check means there was nothing to check.
func (t *TaskManager) checkResult(ctx context.Context, run *taskRun, req taskReq, round int, pass passResult) resultCheck {
	if pass.Cut {
		who := pass.Model
		if who == "" {
			who = "the model"
		}
		c := resultCheck{Round: round, Outcome: "cut_off", Model: pass.Model, Tokens: pass.Tokens,
			Summary:  fmt.Sprintf("Cut off: %s stopped writing at its output limit (%d tokens), so the end is missing.", who, pass.Tokens),
			Critique: cutCritique(pass)}
		t.addCheck(run, c)
		return c
	}
	if !req.Loop {
		return resultCheck{}
	}
	run.mu.Lock()
	kinds := map[string]bool{run.rec.Kind: true}
	for _, s := range run.rec.Steps {
		kinds[s.Kind] = true
	}
	run.mu.Unlock()
	kind, script, why := pickScript(kinds, pass.Text)
	if kind == "" {
		return resultCheck{}
	}
	runner, blocked := t.app.scriptBlocker(kind, script)
	if why == "" {
		why = blocked
	}
	if why != "" {
		c := resultCheck{Round: round, Outcome: "skipped", Runner: runner, Summary: sentence("Didn't run the script: " + why)}
		t.addCheck(run, c)
		return c
	}
	i := t.addCheck(run, resultCheck{Round: round, Outcome: "running", Runner: runner,
		Summary: "Running the script in " + runner + " here, sandboxed…"})
	run.mu.Lock()
	run.rec.Phase = "checking"
	run.mu.Unlock()
	run.push(true)
	res := t.app.checkScript(ctx, kind, script)
	if ctx.Err() != nil {
		t.dropCheck(run, i)
		return resultCheck{}
	}
	c := otherBlocks(judgeRun(kind, runner, req.Goal, script, res), pass.Text, script)
	c.Round = round
	if c.Outcome == "failed" {
		c.Critique = crashCritique(kind, runner, c)
	}
	t.setCheck(run, i, c)
	return c
}

func (t *TaskManager) addCheck(run *taskRun, c resultCheck) int {
	run.mu.Lock()
	run.rec.Checks = append(run.rec.Checks, c)
	i := len(run.rec.Checks) - 1
	run.mu.Unlock()
	run.push(true)
	t.save(run, false)
	return i
}

func (t *TaskManager) setCheck(run *taskRun, i int, c resultCheck) {
	run.mu.Lock()
	if i < len(run.rec.Checks) {
		run.rec.Checks[i] = c
	}
	run.mu.Unlock()
	run.push(true)
	t.save(run, false)
}

func (t *TaskManager) dropCheck(run *taskRun, i int) {
	run.mu.Lock()
	if i < len(run.rec.Checks) {
		run.rec.Checks = append(run.rec.Checks[:i], run.rec.Checks[i+1:]...)
	}
	run.mu.Unlock()
	run.push(true)
}

// markStopped notes on the last check that Hydra stopped because of it.
func (t *TaskManager) markStopped(run *taskRun) {
	run.mu.Lock()
	if n := len(run.rec.Checks); n > 0 {
		run.rec.Checks[n-1].Stopped = true
	}
	run.mu.Unlock()
	run.push(true)
}

// interruptChecks marks a check that was still running when Chimera closed.
func interruptChecks(rec *TaskRecord) {
	if rec == nil {
		return
	}
	for i := range rec.Checks {
		if rec.Checks[i].Outcome == "running" {
			rec.Checks[i].Outcome, rec.Checks[i].Summary = "skipped", "The check didn't finish (Chimera was closed)."
		}
	}
}

// lastCheck is the task's latest check (zero if none).
func lastCheck(rec TaskRecord) resultCheck {
	if n := len(rec.Checks); n > 0 {
		return rec.Checks[n-1]
	}
	return resultCheck{}
}

// finalCheck is the check of the task's final result: the latest one, if it
// is from the last round (zero otherwise, when that round had nothing to check).
func finalCheck(rec TaskRecord) resultCheck {
	if c := lastCheck(rec); c.Round == rec.Round {
		return c
	}
	return resultCheck{}
}
