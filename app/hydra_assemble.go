package main

// Joining a plan's pieces into the finished result with no model. In blender mode that
// makes one script: imports deduplicated at the top, then each step's part in plan
// order (cleanPlan keeps dependencies on earlier steps only, so plan order is valid),
// holding the piece's SETTINGS_sN, _sN_ constants, helpers and build function in the
// piece's own order, then main(), which makes ctx with a chimera_<slug> collection,
// calls build_s1(ctx) and the rest, then does the save or render from
// SETTINGS_*["output"] once. A python-script plan is the same, with main() called at
// the end (no main() is a seam). Files merge by path, and sections go in plan order
// under "# title".
//
// A piece that breaks its mode's rules sends the task to today's combine (fallback),
// and a seam is a place where pieces that are each fine may not fit. Nothing here runs
// in a real long task yet. The prototype this came from is worker-model/contract/
// join.py and linemap.py, and worker-model/tools/check_join_parity.py fails if the two
// join anything differently.

import (
	"encoding/json"
	"fmt"
	"regexp"
	"slices"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"
)

const stepHeader = "# --- {sid}: {title} ---" // marks each step's part of a joined script

// joinedResult is what joining gives.
type joinedResult struct {
	PlanTitle    string
	Fallback     bool
	Reasons      []string
	Text         string
	HasScript    bool
	Script       string
	ScriptKind   string // run_blender or run_python, as the check names them
	LineMap      *lineMap
	Files        []joinedFile
	Assumptions  [][2]string // step, what it assumed
	Seams        []pieceIssue
	Pieces       []*workerPiece
	Failed       []string
	Notes        []string
	Parts        []joinedPart // the result after its "# title", in order
	EditorWanted bool         // two or more sections: the editor pass would join them
	Edited       bool         // the editor gave the text
	RawText      string       // with Edited: the plain concatenation it replaced
}

type joinedFile struct {
	Path  string   `json:"path"`
	Lang  string   `json:"lang"`
	Body  string   `json:"body"`
	Steps []string `json:"steps"`
}

type joinedPart struct {
	Mode  string   `json:"mode"`
	Steps []string `json:"steps"`
	Text  string   `json:"text"`
}

// assumptionsNote is the reply's Assumptions note, "" if no step had to guess.
func (j *joinedResult) assumptionsNote() string {
	if len(j.Assumptions) == 0 {
		return ""
	}
	var parts []string
	for _, a := range j.Assumptions {
		parts = append(parts, a[0]+": "+a[1])
	}
	return "Assumptions: " + strings.Join(parts, "; ")
}

func seam(code, message, sid string) pieceIssue {
	return pieceIssue{Level: "seam", Code: code, Message: message, Step: sid}
}

var slugRe = regexp.MustCompile(`[^a-z0-9]+`)

// planSlug names a plan's collection.
func planSlug(title string) string {
	s := strings.Trim(slugRe.ReplaceAllString(strings.ToLower(title), "_"), "_")
	if len(s) > 40 {
		s = s[:40]
	}
	if s = strings.Trim(s, "_"); s != "" {
		return s
	}
	return "project"
}

// ---------- python source plumbing ----------

type pySegment struct {
	node       *pyNode
	start, end int
}

// pyLines is code's lines as Python's parser counts them: a lone carriage return ends
// a line for it, not for a split.
func pyLines(code string) []string {
	return strings.Split(strings.ReplaceAll(strings.ReplaceAll(code, "\r\n", "\n"), "\r", "\n"), "\n")
}

// pySegments gives each top-level statement's line range, with the comment lines just
// above it and its decorators. A statement sharing a line with the one before gets
// that line's range.
func pySegments(code string, tree *pyNode) []pySegment {
	lines := pyLines(code)
	var out []pySegment
	prevEnd := 0
	for _, n := range tree.body {
		first := n.line
		for _, d := range n.decorators {
			first = min(first, d.line)
		}
		start := first
		if first > prevEnd {
			start = prevEnd + 1
			for start < first && start <= len(lines) && strings.TrimSpace(lines[start-1]) == "" {
				start++
			}
		}
		out = append(out, pySegment{n, start, n.end})
		prevEnd = max(prevEnd, n.end)
	}
	return out
}

// sourceLines is lines a to b, from 1, kept inside the slice.
func sourceLines(lines []string, a, b int) []string {
	a, b = min(max(a, 1), len(lines)+1), min(b, len(lines))
	if b < a {
		return nil
	}
	return lines[a-1 : b]
}

type importKey struct {
	from                 bool
	level                int
	module, name, asname string
}

type importOrigin struct {
	sid  string
	line int
}

type importBinding struct{ what, sid string }

type importConflict struct {
	name     string
	was, now importBinding
}

// importSet is imports from several pieces, deduplicated name by name, in first-seen
// order. origin is where each came from first; bound is what each name is.
type importSet struct {
	order     []importKey
	origin    map[importKey]*importOrigin
	bound     map[string]importBinding
	conflicts []importConflict
}

func newImportSet() *importSet {
	return &importSet{origin: map[importKey]*importOrigin{}, bound: map[string]importBinding{}}
}

func importKeys(n *pyNode) []importKey {
	var out []importKey
	for _, a := range n.names {
		if n.kind == "Import" {
			out = append(out, importKey{name: a.name, asname: a.asname})
		} else {
			out = append(out, importKey{from: true, level: n.level, module: n.name, name: a.name, asname: a.asname})
		}
	}
	return out
}

func (s *importSet) add(n *pyNode, sid string, line int) {
	for _, k := range importKeys(n) {
		if _, ok := s.origin[k]; !ok {
			s.origin[k] = &importOrigin{sid, line}
			s.order = append(s.order, k)
		}
		var name, what string
		switch {
		case !k.from:
			root, _, _ := strings.Cut(k.name, ".")
			name, what = k.asname, "import "+k.name
			if k.asname == "" {
				name, what = root, "import "+root
			}
		case k.name == "*" || k.module == "__future__":
			continue
		default:
			name, what = k.asname, "from "+strings.Repeat(".", k.level)+k.module+" import "+k.name
			if k.asname == "" {
				name = k.name
			}
		}
		was, seen := s.bound[name]
		if seen && was.what != what {
			s.conflicts = append(s.conflicts, importConflict{name, was, importBinding{what, sid}})
		}
		if !seen {
			s.bound[name] = importBinding{what, sid}
		}
	}
}

// addFirst puts an import at the very top, with no origin: one Chimera needs itself.
func (s *importSet) addFirst(k importKey) {
	s.origin[k] = nil
	s.order = append([]importKey{k}, s.order...)
}

type importLine struct {
	text   string
	origin *importOrigin
}

// lines writes the imports for a joined file: __future__ first, then plain imports,
// then from-imports, each in first-seen order. A from-import line holds the names of
// one piece statement that no earlier piece imported, so the line map blames the step
// that wrote the name. Keys in skip are left out.
func (s *importSet) lines(skip map[importKey]*importOrigin) []importLine {
	type group struct {
		level  int
		module string
		origin importOrigin
	}
	grouped := func(future bool) (order []group, keys map[group][]importKey) {
		keys = map[group][]importKey{}
		for _, k := range s.order {
			if _, skipped := skip[k]; skipped || !k.from || (k.module == "__future__") != future {
				continue
			}
			g := group{k.level, k.module, *s.origin[k]}
			if _, ok := keys[g]; !ok {
				order = append(order, g)
			}
			keys[g] = append(keys[g], k)
		}
		return order, keys
	}
	var out []importLine
	order, keys := grouped(true)
	for _, g := range order {
		var names []string
		for _, k := range keys[g] {
			names = append(names, k.name)
		}
		o := g.origin
		out = append(out, importLine{"from __future__ import " + strings.Join(names, ", "), &o})
	}
	for _, k := range s.order {
		if _, skipped := skip[k]; skipped || k.from {
			continue
		}
		text := "import " + k.name
		if k.asname != "" {
			text += " as " + k.asname
		}
		out = append(out, importLine{text, s.origin[k]})
	}
	order, keys = grouped(false)
	for _, g := range order {
		src := strings.Repeat(".", g.level) + g.module
		o := g.origin
		var names []string
		for _, k := range keys[g] {
			switch {
			case k.name == "*":
				out = append(out, importLine{"from " + src + " import *", &o})
			case k.asname != "":
				names = append(names, k.name+" as "+k.asname)
			default:
				names = append(names, k.name)
			}
		}
		if len(names) > 0 {
			out = append(out, importLine{"from " + src + " import " + strings.Join(names, ", "), &o})
		}
	}
	return out
}

// scriptWriter is a joined script being written, with each line's origin.
type scriptWriter struct {
	lines   []string
	origins []*lineOrigin
}

func (s *scriptWriter) add(text string, origin *lineOrigin) {
	for _, l := range strings.Split(text, "\n") {
		s.lines = append(s.lines, l)
		s.origins = append(s.origins, origin)
	}
}

func (s *scriptWriter) addFrom(code []string, a, b int, sid, part, function string) {
	for i, l := range sourceLines(code, a, b) {
		s.lines = append(s.lines, l)
		s.origins = append(s.origins, &lineOrigin{sid, part, function, a + i})
	}
}

func (s *scriptWriter) text() string {
	return strings.TrimRight(strings.Join(s.lines, "\n"), "\n") + "\n"
}

// pyStringLines gives the lines that start inside a multi-line string, which an indent
// would change.
func pyStringLines(code string) map[int]bool {
	inside := map[int]bool{}
	mark := func(a, b int) {
		for n := a + 1; n <= b; n++ {
			inside[n] = true
		}
	}
	var open []int
	for _, t := range pyLex(pyNormalize(code)).toks {
		switch {
		case t.kind == pyTokString:
			mark(t.line, t.end)
		case t.kind == pyTokFStart:
			open = append(open, t.line)
		case t.kind == pyTokFEnd && len(open) > 0:
			mark(open[len(open)-1], t.end)
			open = open[:len(open)-1]
		}
	}
	return inside
}

// wrapLibrary makes a library entry (a bare fenced block from runStep) a contract piece:
// in blender mode its code goes into def build_sN(ctx): with the imports hoisted. Star
// imports or its own main guard count as a seam.
func wrapLibrary(p *workerPiece, sid, mode string) []pieceIssue {
	var blocks []codeBlock
	for _, b := range codeBlocks(p.Text) {
		if pythonLang(b.Lang) || b.Lang == "" {
			blocks = append(blocks, b)
		}
	}
	p.Library = true
	if len(blocks) != 1 {
		return []pieceIssue{seam("library_seam", "the library entry isn't one python block", sid)}
	}
	code := blocks[0].Body
	tree, e := pyParse(code)
	if e != nil {
		return []pieceIssue{seam("library_seam", "the library entry doesn't parse: "+e.msg, sid)}
	}
	var seams []pieceIssue
	for _, n := range tree.body {
		star := n.kind == "ImportFrom" && slices.ContainsFunc(n.names, func(a pyAlias) bool { return a.name == "*" })
		if star || isMainGuard(n) {
			seams = append(seams, seam("library_seam", "the library entry has a star import or its own main guard", sid))
			break
		}
	}
	if mode == modeBlender {
		lines := pyLines(code)
		inString := pyStringLines(code)
		var imports, rest []string
		written := 0 // statements can share a line: it goes out once
		for _, s := range pySegments(code, tree) {
			start := max(s.start, written+1)
			if start > s.end {
				continue
			}
			written = s.end
			if isImport(s.node) {
				imports = append(imports, sourceLines(lines, start, s.end)...)
				continue
			}
			for i, l := range sourceLines(lines, start, s.end) {
				if pyTrim(l) != "" && !inString[start+i] {
					l = "    " + l
				}
				rest = append(rest, l)
			}
		}
		out := append(imports, "SETTINGS_"+sid+" = {}", "", "def build_"+sid+"(ctx):")
		out = append(out, rest...)
		if len(rest) == 0 {
			out = append(out, "    pass")
		}
		code = strings.Join(out, "\n")
		if tree, e = pyParse(code); e != nil {
			return append(seams, seam("library_seam", "the library entry doesn't parse: "+e.msg, sid))
		}
	}
	p.Code, p.Tree, p.CodeLine = code, tree, 1
	return seams
}

// aloneScript is a blender piece as data generation runs it alone: its own code with
// its main guard blanked out, so every line keeps the piece's own number, then ctx
// built at module level as the mode rule's guard builds it, and build_sN(ctx).
// keepCtx: the script follows its dependencies' script, so a module-level dict named
// ctxName there that looks like a ctx is passed on, with what they registered. also:
// more build functions to call after it, in order.
func aloneScript(p *workerPiece, keepCtx bool, ctxName string, also []string) string {
	lines := pyLines(p.Code)
	for _, s := range pySegments(p.Code, p.Tree) {
		if isMainGuard(s.node) {
			for n := s.node.line; n <= s.end && n <= len(lines); n++ {
				lines[n-1] = ""
			}
		}
	}
	for len(lines) > 0 && pyTrim(lines[len(lines)-1]) == "" {
		lines = lines[:len(lines)-1]
	}
	imports := newImportSet()
	for _, n := range p.Tree.body {
		if isImport(n) {
			imports.add(n, p.Sid, n.line)
		}
	}
	var tail []string
	if _, ok := imports.origin[importKey{name: "bpy"}]; !ok {
		tail = append(tail, "import bpy")
	}
	fresh := `{"scene": bpy.context.scene, "collection": bpy.context.scene.collection, "objects": {}, "values": {}}`
	if keepCtx {
		c := ctxName
		tail = append(tail, fmt.Sprintf(`ctx = %s if isinstance(globals().get("%s"), dict) and isinstance(%s.get("objects"), dict) and "collection" in %s else %s`, c, c, c, c, fresh))
		tail = append(tail, `ctx.setdefault("values", {})`) // a ctx from before ctx["values"]
	} else {
		tail = append(tail, "ctx = "+fresh)
	}
	for _, sid := range append([]string{p.Sid}, also...) {
		tail = append(tail, "build_"+sid+"(ctx)")
	}
	return strings.Join(append(append(lines, "", ""), tail...), "\n") + "\n"
}

// ---------- blender and python-script ----------

// chimeraOutputFn saves and renders what the steps put in SETTINGS_*["output"], once.
const chimeraOutputFn = `def _chimera_output(settings):
    """Chimera's: the save and render the steps put in SETTINGS_*["output"], done once after the last step."""
    import os
    out = {}
    for s in settings:
        o = s.get("output") if isinstance(s, dict) else None
        if isinstance(o, str):
            o = {"blend" if o.lower().endswith(".blend") else "render": o}
        for k, v in (o.items() if isinstance(o, dict) else ()):
            if isinstance(v, dict):
                out.update(v)  # {"render": {"filepath": ..., "resolution": ...}}
            else:
                out[k] = v
    scene, media = bpy.context.scene, (".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff", ".bmp", ".webp",
                                       ".mp4", ".mkv", ".mov", ".avi")
    strs = [v for v in out.values() if isinstance(v, str)]
    blend = next((v for v in strs if v.lower().endswith(".blend")), None)
    render = next((v for v in strs if os.path.splitext(v)[1].lower() in media), None)

    def put(obj, attr, v):
        try:
            setattr(obj, attr, v)
        except (AttributeError, TypeError, ValueError) as e:
            print("chimera: output setting skipped:", attr, e)

    def path(p):
        p = bpy.path.abspath(p) if p.startswith("//") else os.path.abspath(os.path.expanduser(p))
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        return p

    r = scene.render
    res = out.get("resolution")
    if isinstance(res, (list, tuple)) and len(res) == 2:
        put(r, "resolution_x", int(res[0]))
        put(r, "resolution_y", int(res[1]))
    names = {"resolution_x": ("resolution_x", "width", "render_width"),
             "resolution_y": ("resolution_y", "height", "render_height"),
             "resolution_percentage": ("resolution_percentage",), "fps": ("fps",), "frame_start": ("frame_start",),
             "frame_end": ("frame_end",)}
    for attr, keys in names.items():
        v = next((out[k] for k in keys if isinstance(out.get(k), (int, float)) and not isinstance(out.get(k), bool)), None)
        if v is not None:
            put(scene if attr.startswith("frame_") else r, attr, int(v))
    engine = out.get("engine") or out.get("render_engine")
    if isinstance(engine, str):
        put(r, "engine", engine.upper())
    samples = out.get("samples") or out.get("render_samples")
    if isinstance(samples, int) and not isinstance(samples, bool):
        if r.engine == "CYCLES" and getattr(scene, "cycles", None) is not None:
            put(scene.cycles, "samples", samples)
        elif getattr(scene, "eevee", None) is not None:
            put(scene.eevee, "taa_render_samples", samples)
    if blend:
        bpy.ops.wm.save_as_mainfile(filepath=path(blend))
        print("chimera: saved", blend)
    if render:
        ext = os.path.splitext(render)[1].lower()
        video = ext in (".mp4", ".mkv", ".mov", ".avi") or bool(out.get("animation"))
        r.filepath = path(render)
        if video:
            put(r.image_settings, "media_type", "VIDEO")
            put(r.image_settings, "file_format", "FFMPEG")
        else:
            fmt = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".exr": "OPEN_EXR", ".tif": "TIFF",
                   ".tiff": "TIFF", ".bmp": "BMP", ".webp": "WEBP"}.get(ext)
            if fmt:
                put(r.image_settings, "file_format", fmt)
        if scene.camera is None:
            print("chimera: no camera in the scene, so no render")
            return
        bpy.ops.render.render(animation=video, write_still=not video)`

// hasOutput says a piece's settings name an output.
func hasOutput(p *workerPiece) bool {
	for _, n := range p.Tree.body {
		if isSettings(n, p.Sid) && n.value != nil && n.value.kind == "Dict" {
			return slices.ContainsFunc(n.value.keys, func(k *pyNode) bool { return isStrConstant(k) && k.str == "output" })
		}
	}
	return false
}

// partOf gives the part and function a top-level statement of a piece gets in the line
// map. function is the def or class name, or the first name an assignment binds (a _s2_
// constant), so a repair message can say where.
func partOf(n *pyNode, sid string, blender bool) (part, function string) {
	name := defName(n)
	if isAssign(n) {
		names, _ := assignedNames(n)
		if blender && len(names) == 1 && names[0] == "SETTINGS_"+sid {
			return "settings", "SETTINGS_" + sid
		}
		if len(names) > 0 {
			name = names[0]
		}
	}
	if !blender {
		return "code", name
	}
	if name == "build_"+sid {
		return "build", name
	}
	return "helper", name
}

type scriptPart struct {
	code       []string
	a, b       int
	part, name string
	gap        int
}

// joinScript joins blender or python-script pieces, in plan order, into one script.
// Each step's part keeps the piece's own top-level order, so a SETTINGS dict that uses
// the step's own _sN_ constant works joined just as it does alone. Only the imports
// move: to the top, deduplicated.
func joinScript(plan hydraPlan, pieces []*workerPiece, mode string) (string, *lineMap, []pieceIssue) {
	blender := mode == modeBlender
	imports, s := newImportSet(), &scriptWriter{}
	var seams []pieceIssue
	var order, mains []string
	for _, p := range pieces {
		order = append(order, p.Sid)
	}
	titles := map[string]string{}
	for i, st := range plan.Steps {
		titles[stepName(i)] = oneLine(st.Title)
	}
	bodies := make([][]scriptPart, len(pieces))
	for i, p := range pieces {
		code := pyLines(p.Code)
		prevEnd, dropped, written := -1, false, 0
		for _, seg := range pySegments(p.Code, p.Tree) {
			n := seg.node
			switch {
			case isImport(n):
				imports.add(n, p.Sid, n.line)
				dropped = true
			case isDocstring(n) || isMainGuard(n):
				dropped = true // the piece's own docstring and run-alone guard aren't in the joined script
			default:
				part, name := partOf(n, p.Sid, blender)
				// Statements can share a line: it goes out once.
				start := max(seg.start, written+1)
				if start <= seg.end {
					// Blank lines before it: the piece's own, at most 2, when nothing was left out in between, else 2.
					gap := 2
					if prevEnd >= 0 && !dropped {
						gap = min(2, start-prevEnd-1)
					}
					bodies[i] = append(bodies[i], scriptPart{code, start, seg.end, part, name, gap})
					prevEnd, dropped, written = seg.end, false, seg.end
				}
				if !blender && n.kind == "FunctionDef" && n.name == "main" {
					mains = append(mains, p.Sid)
				}
			}
		}
	}
	for _, c := range imports.conflicts {
		seams = append(seams, seam("import_conflict", fmt.Sprintf("%s is %s in %s but %s in %s", c.name, c.was.what, c.was.sid, c.now.what, c.now.sid), c.now.sid))
	}
	s.add("# "+oneLine(plan.Title), nil)
	kind, plural, how := "Python", "s", "each step's part in plan order; main() runs at the end."
	if blender {
		kind, how = "Blender", "each step's part in plan order, with its SETTINGS_ dict; main() runs the steps, then saves or renders once."
	}
	if len(pieces) == 1 {
		plural = ""
	}
	s.add(fmt.Sprintf("# Joined by Chimera from %d %s piece%s (%s): %s", len(pieces), kind, plural, strings.Join(order, ", "), how), nil)
	if _, ok := imports.origin[importKey{name: "bpy"}]; blender && !ok {
		imports.addFirst(importKey{name: "bpy"}) // main() needs it
	}
	for _, l := range imports.lines(nil) {
		var o *lineOrigin
		if l.origin != nil {
			o = &lineOrigin{l.origin.sid, "import", "", l.origin.line}
		}
		s.add(l.text, o)
	}
	for i, p := range pieces {
		s.add("", nil)
		s.add("", nil)
		s.add(fillText(stepHeader, "sid", p.Sid, "title", titles[p.Sid]), nil)
		for k, part := range bodies[i] {
			if k > 0 {
				for g := 0; g < part.gap; g++ {
					s.add("", nil)
				}
			}
			s.addFrom(part.code, part.a, part.b, p.Sid, part.part, part.name)
		}
	}
	main := func(function string) *lineOrigin { return &lineOrigin{Part: "main", Function: function} }
	switch {
	case blender:
		var outputs []string
		for _, p := range pieces {
			if hasOutput(p) {
				outputs = append(outputs, "SETTINGS_"+p.Sid)
			}
		}
		s.add("", nil)
		s.add("", nil)
		s.add("def main():", main("main"))
		lines := []string{"    scene = bpy.context.scene",
			"    collection = bpy.data.collections.new(\"chimera_" + planSlug(plan.Title) + "\")",
			"    scene.collection.children.link(collection)",
			"    ctx = {\"scene\": scene, \"collection\": collection, \"objects\": {}, \"values\": {}}"}
		for _, sid := range order {
			lines = append(lines, "    build_"+sid+"(ctx)")
		}
		if len(outputs) > 0 {
			lines = append(lines, "    _chimera_output(["+strings.Join(outputs, ", ")+"])")
		}
		lines = append(lines, "    return ctx")
		for _, l := range lines {
			s.add(l, main("main"))
		}
		if len(outputs) > 0 {
			s.add("", nil)
			s.add("", nil)
			s.add(chimeraOutputFn, &lineOrigin{Part: "output", Function: "_chimera_output"})
		}
		s.add("", nil)
		s.add("", nil)
		// ctx at module level, so a probe appended to the script sees what was registered.
		s.add("if __name__ == \"__main__\":\n    ctx = main()", main(""))
	case len(mains) > 0:
		if len(mains) > 1 {
			seams = append(seams, seam("duplicate_name", "main() is defined by "+strings.Join(mains, ", "), mains[len(mains)-1]))
		}
		s.add("", nil)
		s.add("", nil)
		s.add("if __name__ == \"__main__\":\n    main()", main(""))
	default:
		// Nothing would run: the check would pass in no time without running a line of
		// the steps' code.
		seams = append(seams, seam("missing_entry_point", "no step defines main(), so the joined script only defines functions and runs nothing (a check of it would pass without running the steps' code)", ""))
	}
	script := s.text()
	seams = append(seams, duplicateNames(pieces)...)
	lm := &lineMap{Kind: mode, Titles: titles, Origins: s.origins}
	if _, e := pyParse(script); e != nil { // every piece parsed alone, so this is the joiner's fault or a dedent clash
		seams = append(seams, seam("join_syntax", fmt.Sprintf("the joined script doesn't parse at line %d: %s", e.line, e.msg), lm.locate(e.line).Step))
	}
	return script, lm, seams
}

// definedNames lists what a module's own defs, classes and assignments bind at its top.
func definedNames(tree *pyNode) []string {
	var out []string
	for _, n := range tree.body {
		switch {
		case isDef(n) || n.kind == "ClassDef":
			out = append(out, n.name)
		case isAssign(n):
			names, _ := assignedNames(n)
			out = append(out, names...)
		}
	}
	return out
}

func duplicateNames(pieces []*workerPiece) []pieceIssue {
	seen := map[string]string{}
	var seams []pieceIssue
	for _, p := range pieces {
		done := map[string]bool{}
		for _, n := range definedNames(p.Tree) {
			if done[n] {
				continue
			}
			done[n] = true
			if first, ok := seen[n]; ok && first != p.Sid {
				seams = append(seams, seam("duplicate_name", n+" is defined by "+first+" and "+p.Sid, p.Sid))
			}
			if _, ok := seen[n]; !ok {
				seen[n] = p.Sid
			}
		}
	}
	return seams
}

// ctxDict says n is ctx[channel], ctx.get(channel, ...) or ctx.setdefault(channel, ...):
// the dict itself.
func ctxDict(n *pyNode, channel string) bool {
	if n.kind == "Subscript" {
		return n.value.kind == "Name" && n.value.name == "ctx" && isStrConstant(n.slice) && n.slice.str == channel
	}
	return n.kind == "Call" && n.fn.kind == "Attribute" && (n.fn.name == "get" || n.fn.name == "setdefault") &&
		n.fn.value.kind == "Name" && n.fn.value.name == "ctx" && len(n.args) > 0 && isStrConstant(n.args[0]) &&
		n.args[0].str == channel
}

// ctxBoundWrites gives the writes into ctx[channel] that ctxKeys doesn't follow: through
// a name every plain binding of which (name = ..., name: T = ...) is the dict itself
// (ctxDict: vals = ctx.setdefault("values", {}), objs = ctx["objects"]), or straight into
// ctx.get(channel)[k] or ctx.setdefault(channel, {})[k]. A literal key stored or
// setdefault() through one is written; a computed key, update() or an augmented
// assignment to the name (|=) is opaque. Reads through one stay unrecorded, so this only
// takes seams away. A values step writing v = ctx["values"]; v["sofa_width"] = ... gave
// each of its readers a false ctx_key_missing in the real gate, which fails them though
// the joined script runs; 181 of 343 stored data-generation pieces that write
// ctx["objects"] do it only through a bound name. On the stored joins it changes no
// seam: 0 of 111 as they ran, 0 of 412 with a step failed in turn.
func ctxBoundWrites(tree *pyNode, channel string) (written []string, opaque bool) {
	seen := map[string][]*pyNode{}
	for _, n := range pyWalk(tree) {
		switch {
		case n.kind == "Assign" && len(n.elts) == 1 && n.elts[0].kind == "Name":
			seen[n.elts[0].name] = append(seen[n.elts[0].name], n.value)
		case n.kind == "AnnAssign" && n.target.kind == "Name" && n.value != nil:
			seen[n.target.name] = append(seen[n.target.name], n.value)
		}
	}
	names := map[string]bool{}
	for k, values := range seen {
		names[k] = true
		for _, v := range values {
			if !ctxDict(v, channel) {
				names[k] = false
			}
		}
	}
	through := func(n *pyNode) bool {
		return n.kind == "Name" && names[n.name] || n.kind == "Call" && ctxDict(n, channel)
	}
	add := func(key string) {
		if !slices.Contains(written, key) {
			written = append(written, key)
		}
	}
	for _, n := range pyWalk(tree) {
		switch {
		case n.kind == "Subscript" && n.store && through(n.value):
			if isStrConstant(n.slice) {
				add(n.slice.str)
			} else {
				opaque = true
			}
		case n.kind == "Call" && n.fn.kind == "Attribute" && through(n.fn.value):
			if n.fn.name == "update" || n.fn.name == "setdefault" && len(n.args) > 0 && !isStrConstant(n.args[0]) {
				opaque = true
			} else if n.fn.name == "setdefault" && len(n.args) > 0 {
				add(n.args[0].str)
			}
		case n.kind == "AugAssign" && n.target.kind == "Name" && names[n.target.name]:
			opaque = true
		}
	}
	return written, opaque
}

// ctxKeySeams finds a ctx["objects"] or ctx["values"] key a step reads that no earlier
// step writes: in the joined run it would make a stand-in, which counts as a failure.
// After a step that writes keys that can't be read (opaque), that channel isn't judged.
// Writes through a name bound to the channel count too (ctxBoundWrites), here only:
// provides_missing still reads ctxKeys alone.
func ctxKeySeams(pieces []*workerPiece, failed []string) []pieceIssue {
	var seams []pieceIssue
	for _, channel := range ctxChannels {
		written, unknown := map[string]bool{}, false
		for _, p := range pieces {
			w, r, opaque := ctxKeys(p.Tree, channel)
			bw, bopaque := ctxBoundWrites(p.Tree, channel)
			for _, k := range bw {
				if !slices.Contains(w, k) {
					w = append(w, k)
				}
			}
			unknown = unknown || opaque || bopaque
			for _, k := range r {
				if !unknown && !written[k] && !slices.Contains(w, k) {
					why := ""
					if len(failed) > 0 {
						why = " (the step that should have made it failed)"
					}
					seams = append(seams, seam("ctx_key_missing", fmt.Sprintf("%s reads ctx[%q][%s], which no earlier step registers%s", p.Sid, channel, pyRepr(k), why), p.Sid))
				}
			}
			for _, k := range w {
				written[k] = true
			}
		}
	}
	return seams
}

// ---------- uses and provides ----------

var (
	usesTokenRe = regexp.MustCompile("`([^`]+)`|\"([^\"]{1,80})\"|'([^']{1,80})'|([" + pyWordChars + "./-]+\\." + pyW + "+|[A-Za-z_]" + pyW + "*(?:\\(\\))?)")
	keyInRe     = regexp.MustCompile(`\[` + pyS + `*['"]([^'"]+)['"]` + pyS + `*\]`)
	identRe     = regexp.MustCompile(`^[A-Za-z_]` + pyW + `*$`)
	dottedRe    = regexp.MustCompile(`^[A-Za-z_][` + pyWordChars + `.]*$`)
	stepIDRe    = regexp.MustCompile(`^s\p{Nd}+$`)
	sourceExtRe = regexp.MustCompile(`\.(?:py|js|ts|json|blend|png|css|html)\n?$`)
	camelRe     = regexp.MustCompile(`[a-z][A-Z]`)
	shortExtRe  = regexp.MustCompile(`\.` + pyW + `{1,5}\n?$`)
)

// codeLike says a bare word looks like a name in code: snake_case, CamelCase inside, a
// dotted name, or a path.
func codeLike(tok string) bool {
	if tok == "" {
		return false
	}
	if r, _ := utf8.DecodeRuneInString(tok); unicode.IsDigit(r) {
		return false
	}
	if strings.Contains(tok, "/") || sourceExtRe.MatchString(tok) {
		return true
	}
	if strings.Contains(tok, ".") {
		for _, x := range strings.Split(tok, ".") {
			if utf8.RuneCountInString(x) <= 1 || !identRe.MatchString(x) {
				return false
			}
		}
		return true
	}
	return strings.Contains(strings.Trim(tok, "_"), "_") || camelRe.MatchString(tok)
}

// usesNames finds code-like names in a piece of a uses line: quoted or backticked ones,
// bare snake_case, dotted, CamelCase or path-like words, and calls.
func usesNames(chunk string) []string {
	var out []string
	add := func(s string) {
		if !slices.Contains(out, s) {
			out = append(out, s)
		}
	}
	for _, m := range usesTokenRe.FindAllStringSubmatch(chunk, -1) {
		quoted := m[1]
		if quoted == "" {
			quoted = m[2]
		}
		if quoted == "" {
			quoted = m[3]
		}
		tok := quoted
		if tok == "" {
			tok = m[4]
		}
		tok = pyTrim(tok)
		if keys := keyInRe.FindAllStringSubmatch(tok, -1); keys != nil { // ctx["objects"]["table"] -> table
			add(keys[len(keys)-1][1])
			continue
		}
		call := strings.HasSuffix(tok, "()")
		tok = strings.TrimRight(tok, ".,;:")
		tok = strings.TrimSuffix(tok, "()")
		if stepIDRe.MatchString(tok) || utf8.RuneCountInString(tok) < 2 {
			continue
		}
		if quoted != "" || (call && identRe.MatchString(tok)) || codeLike(tok) {
			add(tok)
		}
	}
	return out
}

// ---------- uses lines ----------
//
// A uses line is read as a list of items (cut at "," and ";" outside brackets), each given to the
// step id in it, or after it ("X from s1", "X (s1)"), or to an "sN:" lead before it, as the user
// decided on Nov 5 (contract question 4). Until then the line was cut at each id and the text
// before an id's successor was that id's, so "a from s1, b from s2" read b as s1's. Ids joined by
// "and", "/", "," and the like are one group, and "s2-s6" a range; a group is judged as one. Text
// no id comes after, in its ;-group, is no step's. A second round the same day (round 8, the
// user's yes) fixed the two forms the first read worse than the reader before it: two ids in one
// item after a lead word, read as "<id>'s name" or "<id> name" pairs ("Uses s1's a with s2's b",
// rule 5b), and a list broken by plus after "with its" or "with their" ("a from s1 with its b plus
// c from s2", rules 6b and 7); and usesSeams judges a SETTINGS_sN name, and a key the line has
// only in its subscripts, against sN. Round 8's other changes (arrows, the full stop, "|", also and
// then as breaks, second lists, failure words) were taken out the same day, and these two
// narrowed: a pair item's runs are forward but it is no prefix item for rule 10, so the items
// around it read as before; an item with a name between one pair and the next id is no pair
// item; and a bare "with" lets no break cut. The wider forms read lines worse than round 7's
// reader.
// The rules (1-11, with 5b and 6b, in the comments below) are written out in
// worker-model/contract/join.py's _uses_chunks, which gives the same chunks on every line
// (check_join_parity). Positions are byte offsets of whole runes, where Python's are code points;
// every character the rules compare is one rune, the brackets, separators, quotes, "/" and "." are
// ASCII, and every rune rules 5b, 6b and 7's cue compare is ASCII but white space (isPySpace), \w
// (isPyWord) and the ’ of ’s, so their words are matched in ASCII case only (asciiFold, not
// strings.EqualFold, which folds ſ with s and K with k).

// isPyWord is re's \w for one character, as wholeWord's isWord.
func isPyWord(r rune) bool { return r == '_' || unicode.IsLetter(r) || unicode.IsNumber(r) }

const usesRangeMax = 9 // a range's span at most this; past it only its two ends

var (
	usesConnectRe  = regexp.MustCompile(`^(?:(?:` + pyS + `|[,/&+]|and|or)*|[-–—])$`)
	usesPrefixRe   = regexp.MustCompile(`^` + notWord + `*(?:(?:[Ff]rom|[Ss]teps?)` + notWord + `+)?$`)
	usesOpenRe     = regexp.MustCompile(`^` + pyS + `*[)\]}]*` + pyS + `*(?::|：|->|=>|→|[-–—]` + pyS + `)`)
	usesBareRe     = regexp.MustCompile(`^(?:` + pyS + `|[,/&+.\-–—]|and|or)*$`)
	usesEndsRe     = regexp.MustCompile(`^[` + pySpaceChars + `.]*$`)
	settingsNameRe = regexp.MustCompile(`^SETTINGS_(s[1-9][0-9]?)$`) // a name the step it names judges (round 8)
	settingsSubRe  = regexp.MustCompile(notWord + `(SETTINGS_s[1-9][0-9]?(?:` + pyS + `*\[` + pyS + `*['"][^'"]+['"]` + pyS + `*\])+)`)
	settingsSidRe  = regexp.MustCompile(`^SETTINGS_(s[1-9][0-9]?)`)
)

var (
	usesBreakWords = []string{"plus"}                   // rule 6b
	usesSkipWords  = []string{"plus", "the", "a", "an"} // rule 6b: passed on the way to the name
	usesCue        = []string{"with"}                   // rule 7: the word after a suffix run that lets a break cut
	usesCueOwners  = []string{"its", "their"}           // rule 7: the word after the cue
)

type usesChunk struct {
	steps []string
	text  string
}

type usesGroup struct{ steps []string }

type usesRef struct {
	start, end int
	sid        string
}

type usesRun struct {
	steps      []string
	start, end int
}

type usesItem struct {
	start, end, semi                                 int
	owner                                            []*usesGroup // per byte of the item; nil: no owner (or no owners at all)
	hasRef, prefix, pair, lastOpen, endsWithID, bare bool
	first, last                                      *usesGroup
}

func isDash(r rune) bool { return r == '-' || r == '–' || r == '—' }

// usesRuns joins refs into runs (rule 4).
func usesRuns(uses string, refs []usesRef) []usesRun {
	var runs []usesRun
	for _, r := range refs {
		if n := len(runs); n > 0 {
			last := &runs[n-1]
			gap := uses[last.end:r.start]
			if usesConnectRe.MatchString(gap) || (len(last.steps) == 1 && last.steps[0] == r.sid) {
				if gap == "-" || gap == "–" || gap == "—" {
					a, b := stepNumber(last.steps[len(last.steps)-1]), stepNumber(r.sid)
					if a < b && b <= a+usesRangeMax {
						for k := a + 1; k < b; k++ {
							if s := fmt.Sprintf("s%d", k); !slices.Contains(last.steps, s) {
								last.steps = append(last.steps, s)
							}
						}
					}
				}
				if !slices.Contains(last.steps, r.sid) {
					last.steps = append(last.steps, r.sid)
				}
				last.end = r.end
				continue
			}
		}
		runs = append(runs, usesRun{[]string{r.sid}, r.start, r.end})
	}
	return runs
}

// usesBracketEnd is just after the closer of the bracket opened at o (the first closer after o of depth level), else b.
func usesBracketEnd(kind []byte, depth []int, o, b, level int) int {
	for c := o + 1; c < b; c++ {
		if kind[c] == 'c' && depth[c] == level {
			return c + 1
		}
	}
	return b
}

// usesMarks is rule 6: the starts of the marks in [a, b).
func usesMarks(uses string, kind []byte, depth []int, a, b, level int) []int {
	var out []int
	for i := a; i < b; {
		r, size := utf8.DecodeRuneInString(uses[i:])
		if kind[i] == 'x' && depth[i] <= level {
			if r == 'a' && i+3 <= b && strings.HasPrefix(uses[i:], "and") {
				p, _ := utf8.DecodeLastRuneInString(uses[:i])
				q, _ := utf8.DecodeRuneInString(uses[i+3:])
				if (i == 0 || !isPyWord(p)) && (i+3 == len(uses) || !isPyWord(q)) {
					out = append(out, i)
				}
			} else if isDash(r) && i > 0 && i+size < len(uses) {
				p, _ := utf8.DecodeLastRuneInString(uses[:i])
				q, _ := utf8.DecodeRuneInString(uses[i+size:])
				if isPySpace(p) && isPySpace(q) {
					out = append(out, i)
				}
			}
		}
		i += size
	}
	return out
}

// asciiFold says whether s is w (lower-case ASCII letters) in any ASCII case; a byte of a longer rune never matches.
func asciiFold(s, w string) bool {
	if len(s) != len(w) {
		return false
	}
	for k := 0; k < len(w); k++ {
		c := s[k]
		if 'A' <= c && c <= 'Z' {
			c += 'a' - 'A'
		}
		if c != w[k] {
			return false
		}
	}
	return true
}

// usesWordAt is the word of words at i, in any ASCII case, ending by b, with no \w character just
// before or just after it; else "".
func usesWordAt(uses string, i, b int, words []string) string {
	for _, w := range words {
		e := i + len(w)
		if e > b || !asciiFold(uses[i:e], w) {
			continue
		}
		if p, _ := utf8.DecodeLastRuneInString(uses[:i]); i > 0 && isPyWord(p) {
			continue
		}
		if q, _ := utf8.DecodeRuneInString(uses[e:]); e < len(uses) && isPyWord(q) {
			continue
		}
		return w
	}
	return ""
}

// usesNameWord is rules 5b and 6b: the word at j (the runes up to the next white space, or b) holds a name.
func usesNameWord(uses string, j, b int) bool {
	k := j
	for k < b {
		r, size := utf8.DecodeRuneInString(uses[k:])
		if isPySpace(r) {
			break
		}
		k += size
	}
	return k > j && len(usesNames(uses[j:k])) > 0
}

// usesBreaks is rule 6b: the starts of the breaks in [a, b), each a break word before a word with a name.
func usesBreaks(uses string, kind []byte, depth []int, a, b, level int) []int {
	var out []int
	memo := map[int]bool{}
	namedFrom := func(j int) bool { // past white space, break words and articles, the next word holds a name
		var passed []int
		var r bool
		for {
			for j < b {
				c, size := utf8.DecodeRuneInString(uses[j:])
				if !isPySpace(c) {
					break
				}
				j += size
			}
			if v, ok := memo[j]; ok {
				r = v
				break
			}
			w := usesWordAt(uses, j, b, usesSkipWords)
			if w == "" {
				r = usesNameWord(uses, j, b)
				memo[j] = r
				break
			}
			passed = append(passed, j)
			j += len(w)
		}
		for _, x := range passed {
			memo[x] = r
		}
		return r
	}
	for i := a; i < b; {
		_, size := utf8.DecodeRuneInString(uses[i:])
		if kind[i] == 'x' && depth[i] <= level {
			if w := usesWordAt(uses, i, b, usesBreakWords); w != "" && namedFrom(i+len(w)) {
				out = append(out, i)
			}
		}
		i += size
	}
	return out
}

// usesCued is rule 7: the first word after a suffix run's end lo (past white space and closers, before hi) is "with",
// and the word after it (past white space) "its" or "their".
func usesCued(uses string, lo, hi int) bool {
	j := lo
	for j < hi {
		r, size := utf8.DecodeRuneInString(uses[j:])
		if !isPySpace(r) && r != ')' && r != ']' && r != '}' {
			break
		}
		j += size
	}
	w := usesWordAt(uses, j, hi, usesCue)
	if w == "" {
		return false
	}
	j += len(w)
	for j < hi {
		r, size := utf8.DecodeRuneInString(uses[j:])
		if !isPySpace(r) {
			break
		}
		j += size
	}
	return usesWordAt(uses, j, hi, usesCueOwners) != ""
}

// usesPair is rule 5b for the run [s, e): 's or ’s right after it with no \w after that, or white space
// and a word with a name, unless the word just before the run is "from".
func usesPair(uses string, a, b, s, e int) bool {
	for _, p := range []string{"'s", "’s"} {
		if strings.HasPrefix(uses[e:b], p) {
			if q, _ := utf8.DecodeRuneInString(uses[e+len(p):]); e+len(p) == len(uses) || !isPyWord(q) {
				return true
			}
		}
	}
	j := e
	for j < b {
		r, size := utf8.DecodeRuneInString(uses[j:])
		if !isPySpace(r) {
			break
		}
		j += size
	}
	if j == e || j == b || !usesNameWord(uses, j, b) {
		return false
	}
	k := s
	for k > a {
		r, size := utf8.DecodeLastRuneInString(uses[:k])
		if !isPySpace(r) {
			break
		}
		k -= size
	}
	w := k
	for w > a {
		r, size := utf8.DecodeLastRuneInString(uses[:w])
		if !isPyWord(r) {
			break
		}
		w -= size
	}
	return !(k < s && asciiFold(uses[w:k], "from"))
}

// usesQuiet is rule 5b's gap: between a run's end e and the next run's start s, past 's or ’s right after the run,
// white space and the word after it (the runes up to the next white space), usesNames finds no name.
func usesQuiet(uses string, e, s int) bool {
	j := e
	for _, p := range []string{"'s", "’s"} {
		if strings.HasPrefix(uses[j:s], p) {
			j += len(p)
			break
		}
	}
	for j < s {
		r, size := utf8.DecodeRuneInString(uses[j:])
		if !isPySpace(r) {
			break
		}
		j += size
	}
	for j < s {
		r, size := utf8.DecodeRuneInString(uses[j:])
		if isPySpace(r) {
			break
		}
		j += size
	}
	return len(usesNames(uses[j:s])) == 0
}

func usesRead(uses string, it *usesItem, refs []usesRef, kind []byte, depth []int) {
	a, b := it.start, it.end
	it.hasRef = true
	it.endsWithID = usesEndsRe.MatchString(uses[refs[len(refs)-1].end:b])
	var rest strings.Builder // rule 9's text
	for i, k := a, 0; i < b; {
		r, size := utf8.DecodeRuneInString(uses[i:])
		for k < len(refs) && refs[k].end <= i {
			k++
		}
		if !(k < len(refs) && refs[k].start <= i) && kind[i] == 'x' && depth[i] == 0 {
			rest.WriteRune(r)
		}
		i += size
	}
	it.bare = usesBareRe.MatchString(rest.String())
	dmin := depth[refs[0].start]
	for _, r := range refs {
		dmin = min(dmin, depth[r.start])
	}
	var shallow, deep []usesRef
	for _, r := range refs {
		if depth[r.start] == dmin {
			shallow = append(shallow, r)
		} else {
			deep = append(deep, r)
		}
	}
	runs := usesRuns(uses, shallow)
	it.prefix = usesPrefixRe.MatchString(uses[a:runs[0].start])
	if !it.prefix && len(runs) >= 2 && len(usesNames(uses[a:runs[0].start])) == 0 { // rule 5b
		it.pair = !slices.ContainsFunc(runs, func(r usesRun) bool { return !usesPair(uses, a, b, r.start, r.end) })
		for k := 0; it.pair && k+1 < len(runs); k++ {
			it.pair = usesQuiet(uses, runs[k].end, runs[k+1].start)
		}
	}
	opened := make([]bool, len(runs))
	for k, r := range runs {
		opened[k] = usesOpenRe.MatchString(uses[r.end:b])
	}
	marks := usesMarks(uses, kind, depth, a, b, dmin)
	breaks := usesBreaks(uses, kind, depth, a, b, dmin)
	groups := make([]*usesGroup, len(runs))
	for k, r := range runs {
		groups[k] = &usesGroup{r.steps}
	}
	var cuts []int
	for k := 0; k+1 < len(runs); k++ { // rule 7
		lo, hi := runs[k].end, runs[k+1].start
		var ms, bs []int
		for _, m := range marks {
			if lo <= m && m < hi {
				ms = append(ms, m)
			}
		}
		for _, x := range breaks {
			if lo <= x && x < hi {
				bs = append(bs, x)
			}
		}
		switch {
		case it.prefix || it.pair || opened[k]:
			if len(ms) > 0 {
				cuts = append(cuts, ms[len(ms)-1])
			} else {
				cuts = append(cuts, hi)
			}
		case len(ms) > 0:
			cuts = append(cuts, ms[0])
		case len(bs) > 0 && usesCued(uses, lo, hi):
			cuts = append(cuts, bs[0])
		default:
			j := lo
			for j < hi && kind[j] == 'x' {
				r, size := utf8.DecodeRuneInString(uses[j:])
				if !isPySpace(r) {
					break
				}
				j += size
			}
			if j < hi && kind[j] == 'o' && depth[j] == dmin+1 {
				cuts = append(cuts, usesBracketEnd(kind, depth, j, b, dmin))
			} else {
				cuts = append(cuts, lo)
			}
		}
	}
	owner := make([]*usesGroup, b-a)
	starts := append([]int{a}, cuts...)
	ends := append(append([]int(nil), cuts...), b)
	for k, g := range groups {
		for i := starts[k]; i < ends[k]; i++ {
			owner[i-a] = g
		}
	}
	for o := a; len(deep) > 0 && o < b; { // rule 8
		if kind[o] == 'o' && depth[o] == dmin+1 {
			e := usesBracketEnd(kind, depth, o, b, dmin)
			var held []usesRef
			for _, r := range deep {
				if o < r.start && r.start < e {
					held = append(held, r)
				}
			}
			if held != nil {
				var steps []string
				for _, r := range usesRuns(uses, held) {
					for _, s := range r.steps {
						if !slices.Contains(steps, s) {
							steps = append(steps, s)
						}
					}
				}
				g := &usesGroup{steps}
				for i := o; i < e; i++ {
					owner[i-a] = g
				}
			}
			o = e
		} else {
			o++
		}
	}
	it.owner = owner
	it.first, it.last, it.lastOpen = groups[0], groups[len(groups)-1], opened[len(opened)-1]
}

// usesChunks reads a uses line into chunks, each with the steps it was taken from, in the
// line's order: items (rules 1-3), runs of ids, pairs, marks and breaks (4-8, with 5b and 6b),
// bare items and items with no id (9, 10), then the chunks, cut where the steps change and just
// before each id (11). No id: none.
func usesChunks(uses string) []usesChunk {
	var refs []usesRef
	for _, m := range pyMatches(stepRefRe, uses) {
		refs = append(refs, usesRef{m[0], m[1], uses[m[0]:m[1]]})
	}
	if refs == nil {
		return nil
	}
	n := len(uses)
	kind, depth := make([]byte, n), make([]int, n) // rule 1, per byte of each rune
	var cuts []int
	for i, d := 0, 0; i < n; {
		r, size := utf8.DecodeRuneInString(uses[i:])
		k := byte('x')
		switch {
		case r == '(' || r == '[' || r == '{':
			d++
			k = 'o'
		case (r == ')' || r == ']' || r == '}') && d > 0:
			d--
			k = 'c'
		}
		if k == 'x' && d == 0 && (r == ',' || r == ';') {
			cuts = append(cuts, i)
		}
		for j := i; j < i+size; j++ {
			kind[j], depth[j] = k, d
		}
		i += size
	}
	var items []*usesItem
	start, semi := 0, 0
	for _, at := range append(cuts, n) { // rule 2
		if pyTrim(uses[start:at]) != "" {
			it := &usesItem{start: start, end: at, semi: semi}
			var mine []usesRef
			for _, r := range refs {
				if start <= r.start && r.end <= at {
					mine = append(mine, r)
				}
			}
			if mine != nil {
				usesRead(uses, it, mine, kind, depth)
			}
			items = append(items, it)
		}
		if at < n && uses[at] == ';' {
			semi++
		}
		start = at + 1
	}
	for k := 1; k < len(items); k++ { // rule 9
		it, prev := items[k], items[k-1]
		if it.hasRef && it.bare && prev.hasRef && prev.endsWithID && prev.semi == it.semi {
			shared := prev.last
			for _, g := range it.owner {
				if g != shared {
					for _, s := range g.steps {
						if !slices.Contains(shared.steps, s) {
							shared.steps = append(shared.steps, s)
						}
					}
				}
			}
			for i := range it.owner {
				it.owner[i] = shared
			}
			it.first, it.last = shared, shared
		}
	}
	for k, it := range items { // rule 10
		if it.hasRef {
			continue
		}
		var before, after *usesItem
		for j := k - 1; j >= 0 && before == nil; j-- {
			if items[j].hasRef && items[j].semi == it.semi {
				before = items[j]
			}
		}
		for j := k + 1; j < len(items) && after == nil; j++ {
			if items[j].hasRef && items[j].semi == it.semi {
				after = items[j]
			}
		}
		var g *usesGroup
		switch {
		case before != nil && (before.prefix || before.lastOpen):
			g = before.last
		case after != nil && !after.prefix:
			g = after.first
		}
		if g != nil {
			it.owner = make([]*usesGroup, it.end-it.start)
			for i := range it.owner {
				it.owner[i] = g
			}
		}
	}
	cutAt := map[int]bool{} // rule 11
	for _, r := range refs {
		s, e := r.start, r.end
		if s > 0 && (uses[s-1] == '/' || uses[s-1] == '.') {
			continue
		}
		if s > 0 && e < n && uses[s-1] == uses[e] && strings.IndexByte("\"'`", uses[e]) >= 0 {
			cutAt[s-1] = true
			for _, it := range items {
				if it.start <= s && s < it.end {
					if it.owner != nil && it.start <= s-1 {
						it.owner[s-1-it.start] = it.owner[s-it.start]
					}
					break
				}
			}
		} else {
			cutAt[s] = true
		}
	}
	var out []usesChunk
	for _, it := range items {
		if it.owner == nil {
			continue
		}
		var cur *usesGroup
		s := it.start
		for i := it.start; i <= it.end; {
			var g *usesGroup
			size := 1
			if i < it.end {
				g = it.owner[i-it.start]
				_, size = utf8.DecodeRuneInString(uses[i:])
			}
			if i < it.end && g == cur && !cutAt[i] {
				i += size
				continue
			}
			if cur != nil && i > s {
				out = append(out, usesChunk{append([]string(nil), cur.steps...), uses[s:i]})
			}
			cur, s = g, i
			i += size
		}
	}
	return out
}

// wholeWord is re.search(r"\b" + re.escape(x) + r"\b", hay).
func wholeWord(hay, x string) bool {
	isWord := func(s string, last bool) bool {
		var r rune
		if last {
			r, _ = utf8.DecodeLastRuneInString(s)
		} else {
			r, _ = utf8.DecodeRuneInString(s)
		}
		return s != "" && (r == '_' || unicode.IsLetter(r) || unicode.IsNumber(r))
	}
	bound := func(i int) bool { return isWord(hay[:i], true) != isWord(hay[i:], false) }
	for i := 0; i <= len(hay); {
		at := strings.Index(hay[i:], x)
		if at < 0 {
			return false
		}
		at += i
		if bound(at) && bound(at+len(x)) {
			return true
		}
		_, size := utf8.DecodeRuneInString(hay[at:])
		i = at + max(size, 1)
	}
	return false
}

// usesHay is what a step's piece offers a uses line: its provides line, code, files and
// section (else body).
func usesHay(d *workerPiece) string {
	var hay strings.Builder
	if d.Handoff != nil {
		hay.WriteString(d.Handoff.Provides)
	}
	hay.WriteString("\n" + d.Code + "\n")
	for i, f := range d.Files {
		if i > 0 {
			hay.WriteString("\n")
		}
		hay.WriteString(f.Path + "\n" + f.Body)
	}
	hay.WriteString("\n")
	if d.Section != "" {
		hay.WriteString(d.Section)
	} else {
		hay.WriteString(d.Body)
	}
	return hay.String()
}

// usesFound says whether a hay holds a name a uses line gives.
func usesFound(name, hay string) bool {
	if strings.Contains(name, "/") || (shortExtRe.MatchString(name) && !dottedRe.MatchString(name)) {
		return strings.Contains(hay, name) // a path
	}
	for _, x := range strings.Split(name, ".") { // a name, or a dotted one (Store.all: class Store with a method all)
		if !wholeWord(hay, x) {
			return false
		}
	}
	return true
}

// settingsKeys maps each key a uses line has only in subscripts of SETTINGS_sN, all of one step, to
// that step (SETTINGS_s1["width"]: width is s1's; round 8). A key usesNames also finds elsewhere in the
// line, or in chains of two steps, isn't in it ("width_m from s2 (overrides SETTINGS_s1["width_m"])"
// keeps width_m with s2). Elsewhere is read twice, with every such chain blanked out (one space each):
// on the whole line, which also holds the text no chunk reaches, and on each of the line's chunks
// (usesChunks(text), which usesSeams passes in), the pieces the seams read. A quote span on the whole
// line can hide a plain use its chunk shows: in "Uses s2's seat_h; SETTINGS_s1['seat_h'] is s1's
// default" the blanked line gives one quoted name, "s seat_h;   is s1", and the chunk "s2's seat_h"
// gives seat_h, so seat_h stays with s2 (Nov 5, round 8's re-check; before it the key went to s1,
// whose dict held it, and s2 went unchecked).
func settingsKeys(text string, chunks []usesChunk) map[string]string {
	ms := pyMatches(settingsSubRe, text)
	if ms == nil {
		return nil
	}
	stepsOf := map[string][]string{}
	for _, m := range ms {
		chain := text[m[0]:m[1]]
		sid := settingsSidRe.FindStringSubmatch(chain)[1]
		for _, k := range keyInRe.FindAllStringSubmatch(chain[len("SETTINGS_")+len(sid):], -1) {
			if !slices.Contains(stepsOf[k[1]], sid) {
				stepsOf[k[1]] = append(stepsOf[k[1]], sid)
			}
		}
	}
	others := usesNames(blankChains(text, ms))
	for _, c := range chunks {
		others = append(others, usesNames(blankChains(c.text, pyMatches(settingsSubRe, c.text)))...)
	}
	out := map[string]string{}
	for k, steps := range stepsOf {
		if len(steps) == 1 && !slices.Contains(others, k) {
			out[k] = steps[0]
		}
	}
	return out
}

// blankChains is text with each of its settingsSubRe matches ms replaced by one space (Python's
// _SETTINGS_SUB.sub(" ", text)).
func blankChains(text string, ms [][2]int) string {
	var b strings.Builder
	at := 0
	for _, m := range ms {
		b.WriteString(text[at:m[0]])
		b.WriteString(" ")
		at = m[1]
	}
	b.WriteString(text[at:])
	return b.String()
}

// usesSeams checks that every "uses" matches a "provides": each code-like name a uses
// line gives for a step must appear in that step's provides line or its piece. The steps
// are usesChunks'. A group is skipped when one of its steps failed or isn't in the join
// (it may have made the name), else a name none of them holds is a seam, written with the
// group as s1/s2; one per piece, steps and name. One step's message is as before Nov 5.
// Since round 8 (Nov 5) a SETTINGS_sN name, and a key the line has only in subscripts of one
// step's SETTINGS_sN (settingsKeys), is judged against sN alone, wherever it is in the line (the
// contract gives each step one dict SETTINGS_{sid}, so the name carries its step), and skipped
// only when sN failed or isn't in the join: in a chunk, and, after the chunks, in text that goes
// to no step and in a line with no step id ("SETTINGS_s1, panel_array"). So it also judges a
// SETTINGS_sN the line says it doesn't use, in text no chunk reaches ("table_top from s1, not
// SETTINGS_s2", "SETTINGS_s2 (unused)") and inside a chunk whose group has a failed step
// ("lamp_shade (not SETTINGS_s1) from s2" with s2 failed), where round 7's reader judged nothing:
// the name is a seam only when sN has no SETTINGS_sN dict (in Blender mode a contract breach), a
// key ("not SETTINGS_s2['width']") whenever sN's piece lacks it, with no breach. Accepted as it is
// (Nov 5, the main session's decision): it follows the approved "wherever it is in the line", no
// stored line has either, and the narrowings tried read more lines worse than they fixed.
func usesSeams(pieces []*workerPiece, failed []string) []pieceIssue {
	var seams []pieceIssue
	find := func(sid string) *workerPiece {
		i := slices.IndexFunc(pieces, func(p *workerPiece) bool { return p.Sid == sid })
		if i < 0 {
			return nil
		}
		return pieces[i]
	}
	for _, p := range pieces {
		if p.Handoff == nil || p.Handoff.Uses == "" {
			continue
		}
		seen := map[string]bool{}
		hays := map[string]string{}
		hay := func(s string) string {
			h, ok := hays[s]
			if !ok {
				h = usesHay(find(s))
				hays[s] = h
			}
			return h
		}
		absent := func(s string) bool { return slices.Contains(failed, s) || find(s) == nil }
		chunks := usesChunks(p.Handoff.Uses)
		keys := settingsKeys(p.Handoff.Uses, chunks)
		for _, c := range chunks {
			skip := slices.ContainsFunc(c.steps, absent)
			for _, name := range usesNames(c.text) {
				steps := c.steps
				one, ok := keys[name]
				if m := settingsNameRe.FindStringSubmatch(name); m != nil {
					one, ok = m[1], true
				}
				if ok { // SETTINGS_sN and its keys are sN's, whatever chunk they are in
					steps = []string{one}
					if absent(one) {
						continue
					}
				} else if skip {
					continue
				}
				dep := strings.Join(steps, "/")
				if seen[dep+"\x00"+name] {
					continue
				}
				seen[dep+"\x00"+name] = true
				if !slices.ContainsFunc(steps, func(s string) bool { return usesFound(name, hay(s)) }) {
					seams = append(seams, seam("uses_unmatched", fmt.Sprintf("%s uses %s from %s, which %s doesn't provide", p.Sid, pyRepr(name), dep, dep), p.Sid))
				}
			}
		}
		for _, name := range usesNames(p.Handoff.Uses) { // text no chunk reaches, and a line with no step id
			one, ok := keys[name]
			if m := settingsNameRe.FindStringSubmatch(name); m != nil {
				one, ok = m[1], true
			}
			if !ok || absent(one) || seen[one+"\x00"+name] {
				continue
			}
			seen[one+"\x00"+name] = true
			if !usesFound(name, hay(one)) {
				seams = append(seams, seam("uses_unmatched", fmt.Sprintf("%s uses %s from %s, which %s doesn't provide", p.Sid, pyRepr(name), one, one), p.Sid))
			}
		}
	}
	return seams
}

// ---------- files ----------

func mergeable(tree *pyNode) bool {
	for _, n := range tree.body {
		if isImport(n) || isDef(n) || n.kind == "ClassDef" || isDocstring(n) {
			continue
		}
		if isAssign(n) {
			if _, ok := assignedNames(n); ok {
				continue
			}
		}
		return false
	}
	return true
}

type stepBody struct{ sid, body string }

// mergePython makes a Python file from its full version, if any, and "(part)" blocks.
// The full version stays as it is; the parts' new imports go after its imports, and
// the parts' code, in plan order, before its main guard, else at the end. ok is false
// when a part holds more than imports, defs, classes and constants.
func mergePython(base *string, parts []stepBody) (string, bool) {
	type parsed struct {
		stepBody
		tree *pyNode
	}
	var trees []parsed
	for _, part := range parts {
		tree, e := pyParse(part.body)
		if e != nil || !mergeable(tree) {
			return "", false
		}
		trees = append(trees, parsed{part, tree})
	}
	have, every := newImportSet(), newImportSet()
	var baseLines []string
	var baseTree *pyNode
	if base != nil {
		var e *pySyntaxError
		if baseTree, e = pyParse(*base); e != nil {
			return "", false
		}
		baseLines = pyLines(*base)
		for _, n := range baseTree.body {
			if isImport(n) {
				have.add(n, "base", n.line)
				every.add(n, "base", n.line)
			}
		}
	}
	var chunks []string
	for _, t := range trees {
		lines := pyLines(t.body)
		written := 0 // statements can share a line: it goes out once
		for _, s := range pySegments(t.body, t.tree) {
			if isImport(s.node) {
				every.add(s.node, t.sid, s.node.line)
			} else if !isDocstring(s.node) || s.node != t.tree.body[0] {
				if start := max(s.start, written+1); start <= s.end {
					chunks = append(chunks, strings.Join(sourceLines(lines, start, s.end), "\n"))
					written = s.end
				}
			}
		}
	}
	var newImports []string
	for _, l := range every.lines(have.origin) {
		newImports = append(newImports, l.text)
	}
	if baseTree == nil {
		var kept []string
		for _, c := range append([]string{strings.Join(newImports, "\n")}, chunks...) {
			if pyTrim(c) != "" {
				kept = append(kept, c)
			}
		}
		return strings.Join(kept, "\n\n\n") + "\n", true
	}
	body := baseTree.body
	var guard *pyNode
	for i := len(body) - 1; i >= 0 && guard == nil; i-- {
		if isMainGuard(body[i]) {
			guard = body[i]
		}
	}
	lastImport := 0
	for _, n := range body {
		if isImport(n) {
			lastImport = max(lastImport, n.end)
		}
	}
	if lastImport == 0 && len(body) > 0 && isDocstring(body[0]) {
		lastImport = body[0].end
	}
	cut := len(baseLines) + 1
	for _, s := range pySegments(*base, baseTree) {
		if guard != nil && s.node == guard {
			cut = s.start
			break
		}
	}
	head := slices.Concat(sourceLines(baseLines, 1, lastImport), newImports, sourceLines(baseLines, lastImport+1, cut-1))
	tail := sourceLines(baseLines, cut, len(baseLines))
	out := strings.TrimRight(strings.Join(head, "\n"), "\n") + "\n\n\n" + strings.Join(chunks, "\n\n\n")
	if len(tail) > 0 {
		out += "\n\n\n" + strings.Trim(strings.Join(tail, "\n"), "\n")
	}
	return strings.TrimRight(out, "\n") + "\n", true
}

// moduleNames lists the names a project file can be imported by: every dotted suffix
// of its path.
func moduleNames(path string) []string {
	var parts []string
	for _, x := range strings.Split(strings.TrimSuffix(path, ".py"), "/") {
		if x != "" && x != "." {
			parts = append(parts, x)
		}
	}
	if len(parts) > 0 && parts[len(parts)-1] == "__init__" {
		parts = parts[:len(parts)-1]
	}
	var out []string
	for k := range parts {
		out = append(out, strings.Join(parts[k:], "."))
	}
	return out
}

// importSeams checks that every `from X import a` between project files resolves: X
// is a project file that defines a.
func importSeams(files []joinedFile) []pieceIssue {
	trees := map[string]*pyNode{}
	var paths []string
	for _, f := range files {
		if strings.HasSuffix(f.Path, ".py") {
			if tree, e := pyParse(f.Body); e == nil {
				if _, ok := trees[f.Path]; !ok {
					paths = append(paths, f.Path)
				}
				trees[f.Path] = tree
			}
		}
	}
	deepest := slices.Clone(paths) // the longest path claims a shared suffix first
	sort.SliceStable(deepest, func(a, b int) bool { return strings.Count(deepest[a], "/") > strings.Count(deepest[b], "/") })
	modules := map[string]string{}
	tops := map[string]bool{}
	for _, path := range deepest {
		for _, name := range moduleNames(path) {
			if _, ok := modules[name]; !ok {
				modules[name] = path
			}
			top, _, _ := strings.Cut(name, ".")
			tops[top] = true
		}
	}
	defined := map[string]map[string]bool{}
	for path, tree := range trees {
		defined[path] = map[string]bool{}
		for _, n := range topLevelNames(tree) {
			defined[path][n] = true
		}
	}
	var seams []pieceIssue
	unresolved := func(format string, args ...any) {
		seams = append(seams, seam("import_unresolved", fmt.Sprintf(format, args...), ""))
	}
	for _, path := range paths {
		pkg := strings.Split(path, "/")
		pkg = pkg[:len(pkg)-1]
		for _, n := range pyWalk(trees[path]) {
			if n.kind == "Import" {
				for _, a := range n.names {
					top, _, _ := strings.Cut(a.name, ".")
					if _, known := modules[a.name]; tops[top] && !known && strings.Contains(a.name, ".") {
						unresolved("%s: import %s: no such project file", path, a.name)
					}
				}
			}
			if n.kind != "ImportFrom" {
				continue
			}
			var mod, target string
			if n.level > 0 {
				base, resolvable := []string(nil), n.level-1 <= len(pkg)
				if resolvable {
					base = pkg[:len(pkg)-(n.level-1)]
				}
				mod = strings.Join(append(slices.Clone(base), moduleParts(n.name)...), ".")
				if resolvable {
					target = modules[mod]
				}
				if target == "" && n.name != "" {
					unresolved("%s: from %s%s import …: no such project file", path, strings.Repeat(".", n.level), n.name)
					continue
				}
			} else {
				mod = n.name
				target = modules[mod]
			}
			if target == "" {
				top, _, _ := strings.Cut(mod, ".")
				if tops[top] && n.level == 0 {
					unresolved("%s: from %s import …: no such project file", path, mod)
				}
				continue
			}
			for _, a := range n.names {
				if _, known := modules[mod+"."+a.name]; a.name != "*" && !defined[target][a.name] && !known {
					from := mod
					if from == "" {
						from = "."
					}
					unresolved("%s: from %s import %s: %s doesn't define %s", path, from, a.name, target, a.name)
				}
			}
		}
	}
	return seams
}

func moduleParts(module string) []string {
	if module == "" {
		return nil
	}
	return []string{module}
}

// joinFiles merges files-mode pieces by path.
func joinFiles(pieces []*workerPiece) ([]joinedFile, []pieceIssue) {
	type entry struct {
		sid string
		f   filePart
	}
	byPath := map[string][]entry{}
	var order []string
	for _, p := range pieces {
		for _, f := range p.Files {
			if _, ok := byPath[f.Path]; !ok {
				order = append(order, f.Path)
			}
			byPath[f.Path] = append(byPath[f.Path], entry{p.Sid, f})
		}
	}
	var files []joinedFile
	var seams []pieceIssue
	for _, path := range order {
		var full, parts []entry
		var steps []string
		for _, e := range byPath[path] {
			if e.f.Part {
				parts = append(parts, e)
			} else {
				full = append(full, e)
			}
			if !slices.Contains(steps, e.sid) {
				steps = append(steps, e.sid)
			}
		}
		writers := map[string]bool{}
		var sids []string
		for _, e := range full {
			writers[e.sid] = true
			sids = append(sids, e.sid)
		}
		if len(writers) > 1 {
			seams = append(seams, seam("file_conflict", path+" is written in full by "+strings.Join(sids, ", "), full[1].sid))
		}
		var base *string
		lang := ""
		if len(full) > 0 {
			base, lang = &full[0].f.Body, full[0].f.Lang
		} else {
			lang = parts[0].f.Lang
		}
		body := ""
		if base != nil {
			body = *base
		}
		if len(parts) > 0 {
			var bodies []stepBody
			var partSids []string
			for _, e := range parts {
				bodies = append(bodies, stepBody{e.sid, e.f.Body})
				partSids = append(partSids, e.sid)
			}
			merged, ok := "", false
			if strings.HasSuffix(path, ".py") || pythonLang(lang) {
				merged, ok = mergePython(base, bodies)
			}
			if !ok {
				seams = append(seams, seam("part_not_mergeable", path+": the (part) blocks from "+strings.Join(partSids, ", ")+" can't be merged mechanically", parts[0].sid))
				var all []string
				if base != nil {
					all = append(all, *base)
				}
				for _, e := range parts {
					all = append(all, e.f.Body)
				}
				merged = strings.Join(all, "\n\n")
			}
			body = merged
		}
		files = append(files, joinedFile{path, lang, strings.TrimRight(body, "\n"), steps})
	}
	seams = append(seams, importSeams(files)...)
	for _, f := range files {
		if !strings.HasSuffix(f.Path, ".py") {
			continue
		}
		tree, e := pyParse(f.Body)
		if e != nil {
			seams = append(seams, seam("join_syntax", fmt.Sprintf("%s doesn't parse after merging (line %d: %s)", f.Path, e.line, e.msg), ""))
			continue
		}
		names := topLevelNames(tree)
		counts := map[string]int{}
		for _, n := range names {
			counts[n]++
		}
		var dups []string
		for n, c := range counts {
			if c > 1 {
				dups = append(dups, n)
			}
		}
		sort.Strings(dups)
		if len(dups) > 0 && len(f.Steps) > 1 {
			seams = append(seams, seam("duplicate_name", f.Path+" defines "+strings.Join(dups, ", ")+" more than once after merging", ""))
		}
	}
	return files, seams
}

// ---------- the whole plan ----------

// joinAsk is what joining needs besides the plan. Editor is the hook for the editor
// pass over two or more sections, which isn't written yet, because its prompt would be
// a new frozen text: what it returns, if anything, becomes the result's text. It must
// keep the code blocks as they are, since the result check runs on them.
type joinAsk struct {
	Goal        string
	DoneReasons map[string]string // Ollama's done_reason by plan id
	RejectCut   bool
	Editor      func(*joinedResult) string
}

// joinPlan validates every piece and joins them. A step's reply is its Output, and a
// step with Status "failed" has none; "library" is a library entry.
func joinPlan(plan hydraPlan, ask joinAsk) *joinedResult {
	j := &joinedResult{PlanTitle: oneLine(plan.Title)}
	lone := len(plan.Steps) == 1
	for i := range plan.Steps {
		st := &plan.Steps[i]
		sid := stepName(i)
		mode := stepMode(plan, i, ask.Goal)
		switch st.Status {
		case "failed":
			j.Failed = append(j.Failed, sid)
			j.Notes = append(j.Notes, fmt.Sprintf("%s (%s) failed, so its part is missing.", sid, oneLine(st.Title)))
		case "library":
			p := &workerPiece{Sid: sid, Mode: mode, Text: st.Output, Body: strings.TrimSpace(st.Output)}
			if mode == modeBlender || mode == modePythonScript {
				j.Seams = append(j.Seams, wrapLibrary(p, sid, mode)...)
				if p.Tree == nil {
					j.Reasons = append(j.Reasons, sid+": the library entry can't be joined")
				}
			} else {
				j.Reasons = append(j.Reasons, sid+": a library entry in "+mode+" mode has no file path or heading")
			}
			j.Pieces = append(j.Pieces, p)
		default:
			p := validatePiece(st.Output, pieceAsk{Mode: mode, Sid: sid, Deps: depNames(plan, i), Lone: lone, Step: st,
				DoneReason: ask.DoneReasons[st.ID], RejectCut: ask.RejectCut})
			j.Pieces = append(j.Pieces, p)
			for _, r := range p.reasons() {
				j.Reasons = append(j.Reasons, sid+": "+r)
			}
			if p.Handoff != nil && p.Handoff.Assumed != "" {
				j.Assumptions = append(j.Assumptions, [2]string{sid, p.Handoff.Assumed})
			}
		}
	}
	if len(j.Reasons) > 0 {
		j.Fallback = true
		return j
	}
	if len(j.Pieces) == 0 {
		j.Fallback = true
		j.Reasons = append(j.Reasons, "no step finished")
		return j
	}
	byMode := map[string][]*workerPiece{}
	for _, p := range j.Pieces {
		byMode[p.Mode] = append(byMode[p.Mode], p)
	}
	rendered := map[string]string{}
	for _, mode := range []string{modeBlender, modePythonScript} {
		ps := byMode[mode]
		if len(ps) == 0 {
			continue
		}
		script, lm, seams := joinScript(plan, ps, mode)
		j.Seams = append(j.Seams, seams...)
		if mode == modeBlender {
			j.Seams = append(j.Seams, ctxKeySeams(ps, j.Failed)...)
		}
		if !j.HasScript { // a plan has at most one of the two
			j.HasScript, j.Script, j.LineMap = true, script, lm
			j.ScriptKind = "run_python"
			if mode == modeBlender {
				j.ScriptKind = "run_blender"
			}
		}
		run, tail := "python3 script.py", "."
		if mode == modeBlender {
			run, tail = "blender -b --python script.py", " (what to change is in each step's SETTINGS_ dict)."
		}
		rendered[mode] = "```python\n" + script + "```\n\nRun it with: " + run + tail
	}
	if ps := byMode[modeFiles]; len(ps) > 0 {
		files, seams := joinFiles(ps)
		j.Files, j.Seams = files, append(j.Seams, seams...)
		var blocks []string
		for _, f := range files {
			blocks = append(blocks, fmt.Sprintf("File: %s\n```%s\n%s\n```", f.Path, f.Lang, f.Body))
		}
		rendered[modeFiles] = strings.Join(blocks, "\n\n")
	}
	j.Seams = append(j.Seams, usesSeams(j.Pieces, j.Failed)...)
	for _, p := range j.Pieces {
		if p.Mode == modeSection {
			text := p.Section
			if text == "" {
				text = p.Body
			}
			j.Parts = append(j.Parts, joinedPart{modeSection, []string{p.Sid}, text})
		} else if !slices.ContainsFunc(j.Parts, func(x joinedPart) bool { return x.Mode == p.Mode }) {
			var steps []string
			for _, q := range byMode[p.Mode] {
				steps = append(steps, q.Sid)
			}
			j.Parts = append(j.Parts, joinedPart{p.Mode, steps, rendered[p.Mode]})
		}
	}
	texts := []string{"# " + j.PlanTitle}
	sections := 0
	for _, x := range j.Parts {
		texts = append(texts, x.Text)
		if x.Mode == modeSection {
			sections++
		}
	}
	j.Text = strings.TrimRightFunc(strings.Join(texts, "\n\n"), isPySpace) + "\n"
	j.EditorWanted = sections > 1
	if ask.Editor != nil && j.EditorWanted {
		if edited := ask.Editor(j); strings.TrimSpace(edited) != "" {
			j.RawText, j.Text, j.Edited = j.Text, strings.TrimRightFunc(edited, isPySpace)+"\n", true
		}
	}
	return j
}

// ---------- the line map ----------

// lineOrigin is where one line of a joined script came from. Part is build, helper,
// code, settings, import, main or output. Step is "" for Chimera's own main and output,
// and Line is the line in the step's own python block, the numbering a repair uses.
type lineOrigin struct {
	Step     string
	Part     string
	Function string
	Line     int
}

// MarshalJSON writes [step, part, function, line], null for what isn't there, the form
// a saved line map has.
func (o lineOrigin) MarshalJSON() ([]byte, error) {
	null := func(s string) any {
		if s == "" {
			return nil
		}
		return s
	}
	var line any
	if o.Line != 0 {
		line = o.Line
	}
	return json.Marshal([]any{null(o.Step), o.Part, null(o.Function), line})
}

// UnmarshalJSON reads that form.
func (o *lineOrigin) UnmarshalJSON(data []byte) error {
	var v [4]any
	if err := json.Unmarshal(data, &v); err != nil {
		return err
	}
	o.Step, _ = v[0].(string)
	o.Part, _ = v[1].(string)
	o.Function, _ = v[2].(string)
	if n, ok := v[3].(float64); ok {
		o.Line = int(n)
	}
	return nil
}

// lineMap says which step each line of a joined script came from. A nil origin is a
// line Chimera wrote, like the header.
type lineMap struct {
	Kind    string            `json:"kind"`
	Titles  map[string]string `json:"titles"`
	Origins []*lineOrigin     `json:"origins"`
}

// lineSpot is where a line of a joined script is. A crash counts for step repair
// (Repair is the step) when it's in that step's build function, helpers, code,
// settings or imports. A crash in main or output is a seam, not one step's.
type lineSpot struct {
	Line      int    `json:"line"`
	Step      string `json:"step,omitempty"`
	Title     string `json:"title,omitempty"`
	Part      string `json:"part,omitempty"`
	Function  string `json:"function,omitempty"`
	PieceLine int    `json:"piece_line,omitempty"`
	Repair    string `json:"repair,omitempty"`
}

func (m *lineMap) locate(line int) lineSpot {
	spot := lineSpot{Line: line}
	if line < 1 || line > len(m.Origins) {
		spot.Part = "outside"
		return spot
	}
	o := m.Origins[line-1]
	if o == nil {
		spot.Part = "chimera"
		return spot
	}
	spot.Step, spot.Part, spot.Function, spot.PieceLine = o.Step, o.Part, o.Function, o.Line
	if o.Step != "" {
		spot.Title = m.Titles[o.Step]
		if slices.Contains([]string{"build", "helper", "code", "settings", "import"}, o.Part) {
			spot.Repair = o.Step
		}
	}
	return spot
}

// checkAt is a result check's verdict, as far as the line map cares.
type checkAt struct {
	Outcome string `json:"outcome"`
	Line    int    `json:"line"`
	Error   string `json:"error"`
	Source  string `json:"source"`
	Runner  string `json:"runner"`
}

// checkSpot is a check's crash line read against the line map. Definite says the check
// found the script itself crashed; only that gets a step repair. SourceMatches, given
// the joined script, guards against checking a different file than the map is for.
type checkSpot struct {
	lineSpot
	Outcome       string `json:"outcome"`
	Error         string `json:"error"`
	Source        string `json:"source"`
	Runner        string `json:"runner"`
	Definite      bool   `json:"definite"`
	SourceMatches *bool  `json:"source_matches,omitempty"`
}

func (m *lineMap) locateCheck(c checkAt, script *string) checkSpot {
	out := checkSpot{Outcome: c.Outcome, Error: c.Error, Source: c.Source, Runner: c.Runner, Definite: c.Outcome == "failed"}
	if c.Line != 0 {
		out.lineSpot = m.locate(c.Line)
	}
	if script != nil && c.Line != 0 {
		lines := strings.Split(*script, "\n")
		src := ""
		if c.Line > 0 && c.Line <= len(lines) {
			src = pyTrim(lines[c.Line-1])
		}
		stem, cut := strings.CutSuffix(out.Source, "…")
		matches := src != "" && (src == pyTrim(out.Source) || (cut && strings.HasPrefix(src, stem)))
		out.SourceMatches = &matches
	}
	if !out.Definite {
		out.Repair = ""
	}
	return out
}
