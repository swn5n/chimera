package main

// The piece validator: does one worker reply keep the contract's shape for its mode?
// An error means the piece breaks a mode rule, so joining it would fall back to a
// model combine, or it can't work at all (a syntax error, a reply cut at its length
// limit). A warning is a quality note for measuring. Nothing here runs in a real long
// task yet. The prototype this came from is worker-model/contract/validate.py, and
// worker-model/tools/check_join_parity.py fails if the two read a reply differently.

import (
	"fmt"
	"regexp"
	"slices"
	"strings"
	"unicode"
	"unicode/utf8"
)

const (
	maxPieceTokens = 3500 // the data filter: longer targets are rejected
	handoffLineMax = 300  // "one short line each": longer is a warning
)

// contractCodes are the errors that mean a piece doesn't keep the contract's shape. A
// syntax error alone doesn't count: the shape is there, the code just doesn't parse.
var contractCodes = codeSet("empty", "cut_off", "too_long", "harmony_leftover",
	"handoff_missing", "handoff_many", "handoff_unclosed", "handoff_shape", "handoff_not_last", "uses_not_dependency",
	"no_python_block", "many_python_blocks", "unclosed_block", "top_level_code", "wrong_step_names",
	"no_settings", "many_settings", "settings_not_dict", "no_build", "many_build", "no_main_guard",
	"guard_not_build", "saves_or_renders", "deletes_scene", "runs_on_import",
	"no_file_blocks", "no_file_line", "no_heading")

// formCodes are warnings for a near miss of the contract's written form that joining
// reads anyway: fine for Chimera to join, but never a training target, which must
// teach the exact form.
var formCodes = codeSet("handoff_unfenced", "handoff_unlabelled", "handoff_unclosed_end", "handoff_twice", "file_line_decorated")

func codeSet(codes ...string) map[string]bool {
	out := map[string]bool{}
	for _, c := range codes {
		out[c] = true
	}
	return out
}

// pieceIssue is one thing wrong with a piece, or, with Level "seam", with how pieces
// meet. Line is a line of the reply, from 1, or 0 for none.
type pieceIssue struct {
	Level   string `json:"level"`
	Code    string `json:"code"`
	Message string `json:"message"`
	Line    int    `json:"line"`
	Step    string `json:"step,omitempty"` // a seam: the step it's about
}

// filePart is one file block of a files-mode piece.
type filePart struct {
	Path string
	Part bool
	Lang string
	Body string
}

// workerPiece is one reply, read.
type workerPiece struct {
	Sid      string
	Mode     string
	Text     string
	Issues   []pieceIssue
	Handoff  *workerHandoff
	Body     string // the reply without its handoff block
	Code     string // blender and python-script: the python block's body
	CodeLine int    // the reply's line that is the code's line 1
	Tree     *pyNode
	Files    []filePart
	Section  string
	Library  bool // a library entry, which runStep writes as a bare block
}

func (p *workerPiece) note(level, code, message string, line int) {
	p.Issues = append(p.Issues, pieceIssue{Level: level, Code: code, Message: message, Line: line})
}

func (p *workerPiece) err(code, message string, line int)  { p.note("error", code, message, line) }
func (p *workerPiece) warn(code, message string, line int) { p.note("warn", code, message, line) }

func (p *workerPiece) ok() bool {
	return !slices.ContainsFunc(p.Issues, func(i pieceIssue) bool { return i.Level == "error" })
}

func (p *workerPiece) contractOK() bool {
	return !slices.ContainsFunc(p.Issues, func(i pieceIssue) bool { return i.Level == "error" && contractCodes[i.Code] })
}

// formOK says no errors, and the contract's exact written form: what data keeps.
func (p *workerPiece) formOK() bool {
	return p.ok() && !slices.ContainsFunc(p.Issues, func(i pieceIssue) bool { return formCodes[i.Code] })
}

func (p *workerPiece) reasons() []string {
	var out []string
	for _, i := range p.Issues {
		if i.Level == "error" {
			out = append(out, i.Code+": "+i.Message)
		}
	}
	return out
}

// ---------- the handoff ----------

var (
	stepRefRe  = regexp.MustCompile(notWord + `(s[1-9]\p{Nd}?)` + notWord)
	negatedRe  = regexp.MustCompile(`^(?i:none|nothing|(?:no|not)(?:` + notWord + `|$))`)
	harmonyRe  = regexp.MustCompile(`<\|(?:start|end|message|channel|return|call|constrain)\|>|assistantfinal|</?think>`)
	fileFormRe = regexp.MustCompile("^" + pyS + "*(?P<pre>[*_#>`\\-" + pySpaceChars + "]*)File:(?P<mid>[*_" + pySpaceChars + "]*)`?(?P<path>[^`*" + pySpaceChars + "]+?)`?(?P<post>\\**)(?P<rest>" + pyS + ".*)?" + pyS + "*$")
)

// handoffForm says how a reply wrote its handoff: "fenced", as the contract has it,
// "plain", in a block with no language or a plain one, or "unfenced".
func handoffForm(text string, blocks []codeBlock) string {
	switch {
	case len(blocks) == 0:
		return ""
	case blocks[0].Lang != "handoff":
		return "plain"
	case slices.ContainsFunc(codeBlocks(text), func(b codeBlock) bool { return b.Lang == "handoff" }):
		return "fenced"
	}
	return "unfenced"
}

// keysAbove finds the three key lines written just above block b, whatever they say:
// their first and last line, and from, which is the first or the label's if there's one.
func keysAbove(lines []string, b codeBlock) (from, first, last int, ok bool) {
	var keys []string
	first, last = -1, -1
	k := b.Start - 2
	for ; k >= 0; k-- {
		if strings.TrimSpace(lines[k]) == "" {
			continue
		}
		key, _, isKey := handoffKey(lines[k])
		if !isKey {
			break
		}
		keys = append(keys, key)
		first = k
		if last < 0 {
			last = k
		}
	}
	if len(keys) != 3 || !hasAllKeys(keys) {
		return 0, 0, 0, false
	}
	if k >= 0 && handoffLabelRe.MatchString(lines[k]) {
		return k, first, last, true
	}
	return first, first, last, true
}

// handoffIssues says what breaks the shape of a handoff, near-miss forms being warnings.
func handoffIssues(text string, blocks []codeBlock, form string) []pieceIssue {
	var out []pieceIssue
	add := func(level, code, message string, line int) {
		out = append(out, pieceIssue{Level: level, Code: code, Message: message, Line: line})
	}
	if len(blocks) == 0 {
		return nil
	}
	switch form {
	case "plain":
		add("warn", "handoff_unlabelled", "the handoff is in a plain ``` block; the contract's is ```handoff (read anyway)", blocks[0].Start)
	case "unfenced":
		add("warn", "handoff_unfenced", "the handoff lines have no ```handoff fence (read anyway)", blocks[0].Start)
	}
	if len(blocks) > 1 {
		add("error", "handoff_many", fmt.Sprintf("%d handoff blocks; the contract has exactly one", len(blocks)), blocks[1].Start)
	}
	b := blocks[len(blocks)-1]
	if !b.Closed {
		// An open block holding just the three lines is the handoff with its closing
		// fence missing: read like an unfenced one. Anything else is still broken.
		if onlyKeyLines(b.Body) {
			add("warn", "handoff_unclosed_end", "the handoff block's closing ``` is missing at the end of the reply (read anyway)", b.Start)
		} else {
			add("error", "handoff_unclosed", "the handoff block is never closed", b.Start)
		}
	}
	lines := strings.Split(text, "\n")
	if form == "fenced" || form == "plain" {
		if from, _, _, ok := keysAbove(lines, b); ok {
			add("warn", "handoff_twice", "the three handoff lines are also written unfenced just above the block (read from the block)", from+1)
		}
	}
	bodyLines := strings.Split(b.Body, "\n")
	bodyLine := b.Start // the 0-based line of the body's first line
	if form == "unfenced" {
		bodyLine = b.End - len(bodyLines) + 1
	}
	seen := map[string]bool{}
	var extra []int
	for j, line := range bodyLines {
		if strings.TrimSpace(line) == "" {
			continue
		}
		key, _, ok := handoffKey(line)
		if !ok {
			extra = append(extra, j)
			continue
		}
		if seen[key] {
			add("error", "handoff_shape", "the handoff has two "+key+": lines", bodyLine+1+j)
		}
		seen[key] = true
	}
	var missing []string
	for _, k := range []string{"provides", "uses", "assumed"} {
		if !seen[k] {
			missing = append(missing, k)
		}
	}
	if len(missing) > 0 {
		add("error", "handoff_shape", "the handoff has no "+strings.Join(missing, " or ")+" line", b.Start)
	}
	if len(extra) > 0 {
		add("error", "handoff_shape", fmt.Sprintf("the handoff has %d line(s) besides provides, uses and assumed", len(extra)), bodyLine+1+extra[0])
	}
	if b.Closed && strings.TrimSpace(strings.Join(lines[b.End+1:], "\n")) != "" {
		add("error", "handoff_not_last", "text after the handoff block (the contract ends with it)", b.End+2)
	}
	return out
}

// usesSteps lists the steps a uses line names, in order of first mention.
func usesSteps(uses string) []string {
	var out []string
	for _, m := range pyMatches(stepRefRe, uses) {
		if s := uses[m[0]:m[1]]; !slices.Contains(out, s) {
			out = append(out, s)
		}
	}
	return out
}

// stepNumber reads the number in s2. A uses line can have any digits in it.
func stepNumber(s string) int {
	if s == "" {
		return 0
	}
	n := 0
	for _, r := range s[1:] {
		n = n*10 + pyDigitValue(r)
	}
	return n
}

// pyDigitValue is a Unicode decimal digit's value: they run in tens.
func pyDigitValue(r rune) int {
	if r >= '0' && r <= '9' {
		return int(r - '0')
	}
	for _, t := range unicode.Nd.R16 {
		if rune(t.Lo) <= r && r <= rune(t.Hi) {
			return int(r-rune(t.Lo)) % 10
		}
	}
	for _, t := range unicode.Nd.R32 {
		if rune(t.Lo) <= r && r <= rune(t.Hi) {
			return int(r-rune(t.Lo)) % 10
		}
	}
	return 0
}

// ---------- reading the tree ----------

// pyDotted gives bpy.ops.wm.save_mainfile for that attribute chain, "" if it isn't one.
func pyDotted(n *pyNode) string {
	var parts []string
	for n.kind == "Attribute" {
		parts = append(parts, n.name)
		n = n.value
	}
	if n.kind != "Name" {
		return ""
	}
	parts = append(parts, n.name)
	slices.Reverse(parts)
	return strings.Join(parts, ".")
}

func isStrConstant(n *pyNode) bool { return n != nil && n.kind == "Constant" && n.constant == "str" }

func isMainGuard(n *pyNode) bool {
	if n.kind != "If" || n.test.kind != "Compare" || len(n.test.ops) != 1 || n.test.ops[0] != "Eq" {
		return false
	}
	name, value := false, false
	for _, s := range []*pyNode{n.test.left, n.test.elts[0]} {
		name = name || (s.kind == "Name" && s.name == "__name__")
		value = value || (isStrConstant(s) && s.str == "__main__")
	}
	return name && value
}

func isDocstring(n *pyNode) bool { return n.kind == "Expr" && isStrConstant(n.value) }

func isImport(n *pyNode) bool { return n.kind == "Import" || n.kind == "ImportFrom" }

func isDef(n *pyNode) bool { return n.kind == "FunctionDef" || n.kind == "AsyncFunctionDef" }

func isAssign(n *pyNode) bool { return n.kind == "Assign" || n.kind == "AnnAssign" }

// defName is a def's or class's name, "" for anything else.
func defName(n *pyNode) string {
	if isDef(n) || n.kind == "ClassDef" {
		return n.name
	}
	return ""
}

// assignedNames gives the names a top-level assignment binds. ok is false if a target
// isn't a plain name.
func assignedNames(n *pyNode) (names []string, ok bool) {
	targets := n.elts
	if n.kind == "AnnAssign" {
		targets = []*pyNode{n.target}
	}
	for _, t := range targets {
		items := []*pyNode{t}
		if t.kind == "Tuple" || t.kind == "List" {
			items = t.elts
		}
		for _, x := range items {
			if x.kind != "Name" {
				return nil, false
			}
			names = append(names, x.name)
		}
	}
	return names, true
}

func isSettings(n *pyNode, sid string) bool {
	if !isAssign(n) {
		return false
	}
	names, ok := assignedNames(n)
	return ok && len(names) == 1 && names[0] == "SETTINGS_"+sid
}

// topLevelNames lists what a module binds at its top, imports as they're bound.
func topLevelNames(tree *pyNode) []string {
	var out []string
	for _, n := range tree.body {
		switch {
		case isDef(n) || n.kind == "ClassDef":
			out = append(out, n.name)
		case isAssign(n):
			names, _ := assignedNames(n)
			out = append(out, names...)
		case n.kind == "Import":
			for _, a := range n.names {
				if a.asname != "" {
					out = append(out, a.asname)
				} else {
					out = append(out, strings.Split(a.name, ".")[0])
				}
			}
		case n.kind == "ImportFrom":
			for _, a := range n.names {
				if a.asname != "" {
					out = append(out, a.asname)
				} else if a.name != "*" {
					out = append(out, a.name)
				}
			}
		}
	}
	return out
}

// literalValue is ast.literal_eval without the values: ok says it would succeed, and
// hashable says the result could be a dict key or set member.
func literalValue(n *pyNode) (hashable, ok bool) {
	number := func(n *pyNode) bool {
		return n.kind == "Constant" && (n.constant == "int" || n.constant == "float" || n.constant == "complex")
	}
	signed := func(n *pyNode) (string, bool) {
		if n.kind == "UnaryOp" && (n.op == "UAdd" || n.op == "USub") {
			n = n.value
		}
		return n.constant, number(n)
	}
	switch n.kind {
	case "Constant":
		return true, true
	case "Tuple", "List":
		hashable = n.kind == "Tuple"
		for _, x := range n.elts {
			h, ok := literalValue(x)
			if !ok {
				return false, false
			}
			hashable = hashable && h
		}
		return hashable, true
	case "Set":
		for _, x := range n.elts {
			if h, ok := literalValue(x); !ok || !h {
				return false, false
			}
		}
		return false, true
	case "Call":
		return false, n.fn.kind == "Name" && n.fn.name == "set" && len(n.args) == 0 && len(n.keywords) == 0
	case "Dict":
		for _, k := range n.keys {
			if k == nil {
				return false, false
			}
			if h, ok := literalValue(k); !ok || !h {
				return false, false
			}
		}
		for _, v := range n.kids[len(n.keys):] {
			if _, ok := literalValue(v); !ok {
				return false, false
			}
		}
		return false, true
	case "BinOp":
		if n.op == "Add" || n.op == "Sub" {
			kind, ok := signed(n.left)
			if ok && kind != "complex" && number(n.right) && n.right.constant == "complex" {
				return true, true
			}
		}
		return false, false
	}
	_, ok = signed(n)
	return true, ok && n.kind == "UnaryOp"
}

// ctxChannels are the ctx dicts steps hand things on in (the blender mode rule).
var ctxChannels = []string{"objects", "values"}

// ctxKeys gives the literal keys a piece stores into and reads from ctx[channel]
// ("objects" or "values"), and opaque: it also writes ctx[channel] in a way whose keys
// can't be read (the whole dict assigned, update(), a key that isn't a literal string).
// Names bound to ctx[channel] aren't followed here: ctxBoundWrites follows them for the
// seams only, so provides_missing asks nothing new of an alias writer.
func ctxKeys(tree *pyNode, channel string) (written, read []string, opaque bool) {
	objects := func(n *pyNode) bool {
		return n.kind == "Subscript" && n.value.kind == "Name" && n.value.name == "ctx" && isStrConstant(n.slice) && n.slice.str == channel
	}
	add := func(list *[]string, key string) {
		if !slices.Contains(*list, key) {
			*list = append(*list, key)
		}
	}
	for _, n := range pyWalk(tree) {
		switch {
		case n.kind == "Subscript" && n.store && (objects(n) || objects(n.value) && !isStrConstant(n.slice)):
			opaque = true
		case n.kind == "Call" && n.fn.kind == "Attribute" && objects(n.fn.value) &&
			(n.fn.name == "update" || n.fn.name == "setdefault" && len(n.args) > 0 && !isStrConstant(n.args[0])):
			opaque = true
		}
		switch {
		case n.kind == "Subscript" && objects(n.value) && isStrConstant(n.slice):
			if n.store {
				add(&written, n.slice.str)
			} else {
				add(&read, n.slice.str)
			}
		case n.kind == "Call" && n.fn.kind == "Attribute" && (n.fn.name == "get" || n.fn.name == "setdefault") &&
			objects(n.fn.value) && len(n.args) > 0 && isStrConstant(n.args[0]):
			if n.fn.name == "setdefault" {
				add(&written, n.args[0].str)
			} else {
				add(&read, n.args[0].str)
			}
		}
	}
	return written, read, opaque
}

// What the blender mode rule forbids: "Don't open, load or save .blend files, render or
// quit".
var forbiddenCallNames = map[string]string{
	"bpy.ops.wm.save_mainfile": "saves the .blend file", "bpy.ops.wm.save_as_mainfile": "saves the .blend file",
	"bpy.ops.wm.save_as_mainfile_copy": "saves the .blend file", "bpy.ops.wm.open_mainfile": "opens a .blend file",
	"bpy.ops.wm.read_homefile": "loads the start-up file", "bpy.ops.wm.read_factory_settings": "resets the scene",
	"bpy.data.libraries.load": "loads a .blend file", "bpy.ops.wm.append": "loads from a .blend file",
	"bpy.ops.wm.link": "loads from a .blend file", "bpy.ops.render.render": "renders",
	"bpy.ops.render.opengl": "renders", "bpy.ops.wm.quit_blender": "quits", "sys.exit": "quits", "exit": "quits",
	"quit": "quits", "os._exit": "quits",
}

// What a loop that removes everything it goes over wipes: the scene's objects or data,
// or the project's shared collection, where other steps' work is. ctx["scene"] reads
// as ctx.scene, and names bound to these are followed.
var wipedSources = []string{"bpy.data.objects", "bpy.data.meshes", "bpy.data.materials", "bpy.context.scene.objects",
	"bpy.context.scene.collection.objects", "bpy.context.collection.objects", "bpy.context.view_layer.objects",
	"ctx.scene.objects", "ctx.scene.collection.objects", "ctx.collection.objects"}

type forbiddenCall struct {
	line       int
	name, what string
}

// callKeyword gives a call's constant string keyword.
func callKeyword(call *pyNode, name string) (string, bool) {
	for _, k := range call.keywords {
		if k.name == name && k.value.kind == "Constant" {
			return k.value.str, k.value.constant == "str"
		}
	}
	return "", false
}

// scriptAliases gives the value of each name bound once, by a plain name = value,
// anywhere in the script.
func scriptAliases(tree *pyNode) map[string]*pyNode {
	seen := map[string][]*pyNode{}
	for _, n := range pyWalk(tree) {
		if n.kind == "Assign" && len(n.elts) == 1 && n.elts[0].kind == "Name" {
			seen[n.elts[0].name] = append(seen[n.elts[0].name], n.value)
		}
	}
	out := map[string]*pyNode{}
	for k, v := range seen {
		if len(v) == 1 {
			out[k] = v[0]
		}
	}
	return out
}

// pyRef is pyDotted that reads ctx["scene"] as ctx.scene and follows aliases.
func pyRef(n *pyNode, aliases map[string]*pyNode, depth int) string {
	switch n.kind {
	case "Name":
		if v, ok := aliases[n.name]; ok && depth < 5 {
			if r := pyRef(v, aliases, depth+1); r != "" {
				return r
			}
		}
		return n.name
	case "Attribute":
		if base := pyRef(n.value, aliases, depth); base != "" {
			return base + "." + n.name
		}
	case "Subscript":
		if isStrConstant(n.slice) {
			if base := pyRef(n.value, aliases, depth); base != "" {
				return base + "." + n.slice.str
			}
		}
	}
	return ""
}

// loopSource is what a for loop goes over, through list(), sorted(), .values() and the like.
func loopSource(it *pyNode) *pyNode {
	for {
		switch {
		case it.kind == "Call" && slices.Contains([]string{"list", "tuple", "sorted", "reversed", "enumerate"}, pyDotted(it.fn)) && len(it.args) > 0:
			it = it.args[0]
		case it.kind == "Call" && it.fn.kind == "Attribute" && it.fn.name == "values" && len(it.args) == 0:
			it = it.fn.value
		case it.kind == "Subscript" && it.slice.kind == "Slice":
			it = it.value
		default:
			return it
		}
	}
}

// loopVar is the name a for loop binds each item to (the second of i, o over enumerate()).
func loopVar(n *pyNode) string {
	if n.target.kind == "Name" {
		return n.target.name
	}
	if n.target.kind == "Tuple" && len(n.target.elts) == 2 && n.target.elts[1].kind == "Name" &&
		n.iter.kind == "Call" && pyDotted(n.iter.fn) == "enumerate" {
		return n.target.elts[1].name
	}
	return ""
}

func pyNot(test *pyNode) *pyNode { return &pyNode{kind: "UnaryOp", op: "Not", value: test} }

// callsUnder gives every call in a loop body with the if tests it sits under. An
// `if …: continue` (or break) before it counts as its negated test.
func callsUnder(body, conds []*pyNode, found func(call *pyNode, conds []*pyNode)) {
	conds = slices.Clone(conds)
	for _, st := range body {
		switch st.kind {
		case "If":
			callsUnder(st.body, append(slices.Clone(conds), st.test), found)
			callsUnder(st.orelse, append(slices.Clone(conds), pyNot(st.test)), found)
			if leaves(st.body) {
				conds = append(conds, pyNot(st.test))
			} else if leaves(st.orelse) {
				conds = append(conds, st.test)
			}
		case "For", "While", "With", "Try":
			callsUnder(st.body, conds, found)
			callsUnder(st.orelse, conds, found)
			callsUnder(st.finalbody, conds, found)
			for _, h := range st.handlers {
				callsUnder(h.body, conds, found)
			}
		default:
			for _, c := range pyWalk(st) {
				if c.kind == "Call" {
					found(c, conds)
				}
			}
		}
	}
}

// leaves says a block ends with continue or break.
func leaves(block []*pyNode) bool {
	if len(block) == 0 {
		return false
	}
	k := block[len(block)-1].kind
	return k == "Continue" || k == "Break"
}

// excludes says an if test only skips a few things (!=, not in, is not, not
// o.name.startswith(…)): the loop still removes the rest. `not m.users` picks.
func excludes(test *pyNode) bool {
	if test.kind == "UnaryOp" && test.op == "Not" {
		inner := test.value
		if inner.kind == "UnaryOp" && inner.op == "Not" {
			return excludes(inner.value)
		}
		if inner.kind == "Compare" {
			return allOps(inner, "Eq", "In", "Is")
		}
		return inner.kind == "Call" || inner.kind == "BoolOp"
	}
	if test.kind == "Compare" {
		return allOps(test, "NotEq", "NotIn", "IsNot")
	}
	if test.kind == "BoolOp" && test.op == "And" {
		for _, v := range test.elts {
			if !excludes(v) {
				return false
			}
		}
		return true
	}
	return false
}

func allOps(compare *pyNode, ops ...string) bool {
	for _, op := range compare.ops {
		if !slices.Contains(ops, op) {
			return false
		}
	}
	return true
}

// forbiddenCalls finds each call the blender mode rule forbids, and scene wipes.
func forbiddenCalls(tree *pyNode) []forbiddenCall {
	var out []forbiddenCall
	var selected, deletes []*pyNode
	walked := pyWalk(tree)
	for _, c := range walked {
		if c.kind != "Call" {
			continue
		}
		name := pyDotted(c.fn)
		if what, ok := forbiddenCallNames[name]; ok {
			out = append(out, forbiddenCall{c.line, name, what})
		}
		if name == "bpy.ops.object.select_all" {
			if v, ok := callKeyword(c, "action"); ok && v == "SELECT" {
				selected = append(selected, c)
			}
		}
		if name == "bpy.ops.object.delete" {
			deletes = append(deletes, c)
		}
	}
	// "Don't delete or change what you didn't create": select everything, then delete.
	if len(selected) > 0 && len(deletes) > 0 {
		out = append(out, forbiddenCall{deletes[0].line, "bpy.ops.object.delete", "deletes everything in the scene"})
	}
	aliases := scriptAliases(tree)
	for _, n := range walked {
		if n.kind == "For" {
			if v := loopVar(n); v != "" {
				if src := pyRef(loopSource(n.iter), aliases, 0); slices.Contains(wipedSources, src) {
					out = append(out, loopRemovals(n, v, src)...)
				}
			}
		}
		if n.kind != "Call" {
			continue
		}
		if pyDotted(n.fn) == "bpy.data.batch_remove" {
			out = append(out, forbiddenCall{n.line, "bpy.data.batch_remove", "removes data in bulk"})
		}
		// There's no such method in Blender 5, but it says what the piece meant to do.
		if ref := pyRef(n.fn, aliases, 0); strings.HasSuffix(ref, ".clear") && slices.Contains(wipedSources, strings.TrimSuffix(ref, ".clear")) {
			out = append(out, forbiddenCall{n.line, pyDotted(n.fn), "tries to remove everything in " + strings.TrimSuffix(ref, ".clear")})
		}
	}
	return out
}

// loopRemovals reads a loop over something shared. With no test, or one that only
// skips a few things, everything goes; a test of its own picks: a note, not a break.
func loopRemovals(loop *pyNode, v, src string) []forbiddenCall {
	var first, every *pyNode
	callsUnder(loop.body, nil, func(c *pyNode, conds []*pyNode) {
		if !strings.HasSuffix(pyDotted(c.fn), ".remove") || len(c.args) == 0 || c.args[0].kind != "Name" || c.args[0].name != v {
			return
		}
		if first == nil {
			first = c
		}
		whole := true
		for _, t := range conds {
			whole = whole && excludes(t)
		}
		if whole && every == nil {
			every = c
		}
	})
	switch {
	case every != nil:
		return []forbiddenCall{{every.line, pyDotted(every.fn), "removes everything in " + src}}
	case first != nil:
		return []forbiddenCall{{first.line, pyDotted(first.fn), "removes some of " + src + " in a loop"}}
	}
	return nil
}

// ---------- the checks ----------

var (
	stepNameRe = regexp.MustCompile(`^(?:SETTINGS_|build_|_)(s\p{Nd}+)(?:_|$)`)
	stubRe     = regexp.MustCompile(notWord + `(?i:TODO|FIXME|placeholder|implement (?:this|me))` + notWord +
		`|#` + pyS + `*\.\.\.|(?m:^)` + pyS + `*\.\.\.` + pyS + `*(?m:$)`)
	aiTalkRe = regexp.MustCompile(notWord + `((?i:as an ai|language model|other workers?|the workers|sub-?agents?))` + notWord)
	linkRe   = regexp.MustCompile(`((?i:https?://)[^` + pySpaceChars + `]+)|` + notWord + `((?i:doi:)` + pyS + `*[^` + pySpaceChars + `]+|10\.\p{Nd}{4,9}/[^` + pySpaceChars + `]+)`)
	pieceBpy = regexp.MustCompile(`(?m:^)` + pyS + `*(?:import` + pyS + `+(?:[` + pyWordChars + `.]+` + pyS + `*,` + pyS + `*)*bpy|from` + pyS + `+bpy)` + notWord)
)

// pieceAsk is what a reply is checked against.
type pieceAsk struct {
	Mode       string
	Sid        string
	Deps       []string
	Lone       bool
	Step       *hydraStep // the plan's step, for the section checks
	DoneReason string
	RejectCut  bool // a reply its model cut off at its output limit fails
	MaxTokens  int  // 0 for no limit
}

// validatePiece checks one reply against the contract for its mode.
func validatePiece(text string, ask pieceAsk) *workerPiece {
	p := &workerPiece{Sid: ask.Sid, Mode: ask.Mode, Text: text}
	if strings.TrimSpace(text) == "" {
		p.err("empty", "the reply is empty", 0)
		return p
	}
	if ask.RejectCut && ask.DoneReason == "length" {
		p.err("cut_off", "its model stopped at its output limit, so the piece may be cut off", 0)
	}
	if ask.MaxTokens > 0 && estimateTokens(text) > ask.MaxTokens {
		p.err("too_long", fmt.Sprintf("about %d tokens, over the %d a piece may have", estimateTokens(text), ask.MaxTokens), 0)
	}
	if m := harmonyRe.FindStringIndex(text); m != nil {
		p.err("harmony_leftover", "the reply has "+pyRepr(text[m[0]:m[1]])+", left over from the model's own format", strings.Count(text[:m[0]], "\n")+1)
	}
	handoff, blocks := parseHandoff(text)
	p.Handoff = handoff
	if ask.Lone {
		if len(blocks) > 0 {
			p.warn("handoff_in_lone", "a lone step gets no handoff; it is stripped", blocks[0].Start)
		}
	} else {
		p.Issues = append(p.Issues, handoffIssues(text, blocks, handoffForm(text, blocks))...)
		if len(blocks) == 0 {
			p.err("handoff_missing", "no ```handoff block at the end", 0)
		}
		if handoff != nil {
			checkUses(p, handoff, ask)
		}
	}
	p.Body = stripHandoff(text, blocks)
	taken := map[int]bool{}
	for _, b := range blocks {
		taken[b.Start] = true
	}
	var rest []codeBlock
	for _, b := range codeBlocks(text) {
		if b.Lang != "handoff" && !taken[b.Start] { // a plain block read as the handoff isn't code
			rest = append(rest, b)
		}
	}
	switch ask.Mode {
	case modeBlender:
		pythonPiece(p, rest, true)
	case modePythonScript:
		pythonPiece(p, rest, false)
	case modeFiles:
		filesPiece(p, rest)
	case modeSection:
		sectionPiece(p, ask.Step)
	}
	return p
}

func checkUses(p *workerPiece, h *workerHandoff, ask pieceAsk) {
	if negatedRe.MatchString(h.Uses) { // "nothing from s1 (…)": none, in more words
		p.warn("handoff_wordy", "uses says "+pyRepr(capChars(h.Uses, 60))+"; the contract's word for nothing is \"none\"", 0)
		h.Uses = ""
	}
	for _, f := range []struct{ key, value string }{{"provides", h.Provides}, {"uses", h.Uses}, {"assumed", h.Assumed}} {
		if n := utf8.RuneCountInString(f.value); n > handoffLineMax {
			p.warn("handoff_long", fmt.Sprintf("the %s line has %d characters; the contract asks for one short line", f.key, n), 0)
		}
	}
	deps := strings.Join(ask.Deps, ", ")
	if deps == "" {
		deps = "nothing"
	}
	var used, bad []string
	for _, s := range usesSteps(h.Uses) {
		if !slices.Contains(ask.Deps, s) && s != ask.Sid {
			used = append(used, s)
			// Pieces run in plan order, so an earlier step's work is there whether or not
			// the plan says so. A later step's isn't there yet.
			if stepNumber(s) > stepNumber(ask.Sid) {
				bad = append(bad, s)
			}
		}
	}
	if len(bad) > 0 {
		p.err("uses_not_dependency", fmt.Sprintf("uses names %s, which comes after %s (it depends on %s)", strings.Join(bad, ", "), ask.Sid, deps), 0)
	} else if len(used) > 0 {
		p.warn("uses_undeclared", fmt.Sprintf("uses names %s, earlier steps it doesn't depend on (it depends on %s)", strings.Join(used, ", "), deps), 0)
	}
}

// capChars is the first n characters of s.
func capChars(s string, n int) string {
	for i := range s {
		if n == 0 {
			return s[:i]
		}
		n--
	}
	return s
}

func pythonPiece(p *workerPiece, blocks []codeBlock, blender bool) {
	var py, others []codeBlock
	for _, b := range blocks {
		if pythonLang(b.Lang) || (b.Lang == "" && (!blender || pyHas(pieceBpy, b.Body))) {
			py = append(py, b)
		} else {
			others = append(others, b)
		}
	}
	if len(others) > 0 {
		p.warn("extra_block", fmt.Sprintf("%d other code block(s) besides the python one; joining ignores them", len(others)), others[0].Start)
	}
	if len(py) == 0 {
		p.err("no_python_block", "no python code block", 0)
		return
	}
	if len(py) > 1 {
		p.err("many_python_blocks", fmt.Sprintf("%d python code blocks; the mode has exactly one", len(py)), py[1].Start)
		return
	}
	b := py[0]
	p.Code, p.CodeLine = b.Body, b.Start+1
	if !b.Closed {
		p.err("unclosed_block", "the python block is never closed (cut off?)", b.Start)
	}
	if b.Lang == "" {
		p.warn("no_language", "the code block doesn't name its language", b.Start)
	}
	tree, e := pyParse(b.Body)
	if e != nil {
		p.err("syntax_error", "SyntaxError: "+e.msg, p.CodeLine+max(e.line, 1)-1)
		return
	}
	p.Tree = tree
	if blender {
		blenderTopLevel(p)
	} else {
		scriptTopLevel(p)
	}
}

// blenderTopLevel checks that column-0 lines are only imports, SETTINGS_sN, def
// build_sN, _sN_ helpers, comments, docstrings and the main guard. It reads the tree,
// so a statement's continuation lines count as it.
func blenderTopLevel(p *workerPiece) {
	sid, at := p.Sid, p.CodeLine-1
	helper := "_" + sid + "_"
	var settings, builds, guards []*pyNode
	for _, node := range p.Tree.body {
		line := at + node.line
		name := defName(node)
		names, plain := []string(nil), false
		if isAssign(node) {
			names, plain = assignedNames(node)
		}
		switch {
		case isImport(node):
			if node.kind == "ImportFrom" && slices.ContainsFunc(node.names, func(a pyAlias) bool { return a.name == "*" }) {
				module := node.name
				if module == "" {
					module = "None"
				}
				p.warn("star_import", "from "+module+" import *", line)
			}
		case isDocstring(node):
		case isSettings(node, sid):
			settings = append(settings, node)
			if node.value == nil || node.value.kind != "Dict" {
				p.err("settings_not_dict", "SETTINGS_"+sid+" isn't a {...} dict", line)
			}
		case isDef(node) && name == "build_"+sid:
			builds = append(builds, node)
			a := node.params
			if a.positional != 1 || a.varargs || a.keywordOnly > 0 || a.kwargs {
				p.warn("build_signature", "build_"+sid+" should take one argument, ctx", line)
			}
		case name != "" && strings.HasPrefix(name, helper):
		case plain && len(names) > 0 && allPrefixed(names, helper):
		case isMainGuard(node):
			guards = append(guards, node)
		default:
			if name != "" {
				names = []string{name}
			}
			other := ""
			for _, n := range names {
				if m := stepNameRe.FindStringSubmatch(n); m != nil && m[1] != sid && other == "" {
					other = n
				}
			}
			if other != "" {
				p.err("wrong_step_names", other+" is named for another step (this is "+sid+")", line)
				break
			}
			what := strings.ToLower(node.kind)
			if len(names) > 0 {
				what = strings.Join(names, ", ")
			}
			p.err("top_level_code", fmt.Sprintf("top-level %s isn't an import, SETTINGS_%s, build_%s, a _%s_ helper or the main guard", what, sid, sid, sid), line)
		}
	}
	switch {
	case len(settings) == 0:
		p.err("no_settings", "no SETTINGS_"+sid+" = {...} dict", 0)
	case len(settings) > 1:
		p.err("many_settings", fmt.Sprintf("SETTINGS_%s is set %d times", sid, len(settings)), at+settings[1].line)
	}
	switch {
	case len(builds) == 0:
		p.err("no_build", "no def build_"+sid+"(ctx):", 0)
	case len(builds) > 1:
		p.err("many_build", fmt.Sprintf("build_%s is defined %d times", sid, len(builds)), at+builds[1].line)
	}
	if len(guards) == 0 {
		p.err("no_main_guard", "no if __name__ == \"__main__\": build_"+sid+"(...) at the end", 0)
	} else {
		called := false
		for _, g := range guards {
			for _, c := range pyWalk(g) {
				called = called || (c.kind == "Call" && pyDotted(c.fn) == "build_"+sid)
			}
		}
		if !called {
			p.err("guard_not_build", "the main guard doesn't call build_"+sid, at+guards[0].line)
		}
		if len(guards) > 1 {
			p.warn("many_guards", fmt.Sprintf("%d main guards", len(guards)), at+guards[1].line)
		}
	}
	for _, f := range forbiddenCalls(p.Tree) {
		switch {
		case strings.HasPrefix(f.what, "removes some of"):
			p.warn("removes_in_loop", f.name+" "+f.what+"; check it only removes what this step made", at+f.line)
		case strings.Contains(f.what, "everything") || strings.Contains(f.what, "bulk"):
			p.err("deletes_scene", f.name+" "+f.what+"; other steps' work is in the scene too", at+f.line)
		default:
			p.err("saves_or_renders", f.name+" "+f.what+"; the mode rule leaves that to Chimera (SETTINGS_"+sid+"[\"output\"])", at+f.line)
		}
	}
	for _, channel := range ctxChannels {
		if p.Handoff == nil {
			break
		}
		written, _, _ := ctxKeys(p.Tree, channel)
		var missing []string
		for _, k := range written {
			if !strings.Contains(p.Handoff.Provides, k) {
				missing = append(missing, k)
			}
		}
		if len(missing) > 0 {
			p.warn("provides_missing", "registers ctx[\""+channel+"\"] key(s) "+strings.Join(missing, ", ")+" that provides doesn't list", 0)
		}
	}
}

func allPrefixed(names []string, prefix string) bool {
	for _, n := range names {
		if !strings.HasPrefix(n, prefix) {
			return false
		}
	}
	return true
}

// scriptTopLevel checks for functions and classes only, with no code that runs on import.
func scriptTopLevel(p *workerPiece) {
	at := p.CodeLine - 1
	for _, node := range p.Tree.body {
		line := at + node.line
		if isImport(node) || isDef(node) || node.kind == "ClassDef" || isDocstring(node) {
			continue
		}
		if isAssign(node) {
			if names, ok := assignedNames(node); ok {
				if node.value != nil {
					if _, literal := literalValue(node.value); !literal {
						p.warn("top_level_assign", strings.Join(names, ", ")+" is set by running code on import", line)
					}
				}
				continue
			}
		}
		if isMainGuard(node) {
			p.warn("main_guard", "a main guard; Chimera calls main() itself and drops it", line)
			continue
		}
		if node.kind == "Try" && !slices.ContainsFunc(node.body, func(n *pyNode) bool { return !isImport(n) }) {
			continue // try: import x / except ImportError
		}
		if node.kind == "If" {
			if d := pyDotted(node.test); d == "TYPE_CHECKING" || d == "typing.TYPE_CHECKING" {
				continue
			}
		}
		p.err("runs_on_import", "top-level "+strings.ToLower(node.kind)+" runs when the file is imported", line)
	}
	if p.Code != "" && pyHas(stubRe, p.Code) {
		p.warn("placeholder", "a TODO, placeholder or stub", 0)
	}
}

// fileLineForm reads a File: line, and says if it's decorated beyond the plain form.
func fileLineForm(line string) (path string, part, decorated, ok bool) {
	m := fileFormRe.FindStringSubmatch(line)
	if m == nil {
		return "", false, false, false
	}
	group := func(name string) string { return m[fileFormRe.SubexpIndex(name)] }
	rest := pyTrim(group("rest"))
	part = partMarkRe.MatchString(rest)
	decorated = strings.TrimSpace(group("pre")) != "" || strings.TrimSpace(group("mid")) != "" || group("post") != "" || (rest != "" && !part)
	return strings.TrimRight(group("path"), ":"), part, decorated, true
}

// filesPiece checks that every block has a File: line just before it.
func filesPiece(p *workerPiece, blocks []codeBlock) {
	if len(blocks) == 0 {
		p.err("no_file_blocks", "no code blocks; the mode gives each file in its own fenced block", 0)
		return
	}
	lines := strings.Split(p.Text, "\n")
	type file struct {
		path string
		part bool
	}
	seen := map[file]bool{}
	for _, b := range blocks {
		j := b.Start - 2
		for j >= 0 && strings.TrimSpace(lines[j]) == "" {
			j--
		}
		ok := false
		var path string
		var part, decorated bool
		if j >= 0 {
			path, part, decorated, ok = fileLineForm(lines[j])
		}
		if !ok {
			p.err("no_file_line", fmt.Sprintf("the block at line %d has no File: line just before it", b.Start), b.Start)
			continue
		}
		if decorated {
			p.warn("file_line_decorated", "the File: line for "+path+" isn't plain (File: path or File: path (part))", j+1)
		}
		if !b.Closed {
			p.err("unclosed_block", "the block for "+path+" is never closed (cut off?)", b.Start)
		}
		if b.Lang == "" {
			p.warn("no_language", "the block for "+path+" doesn't name its language", b.Start)
		}
		if seen[file{path, part}] && !part {
			p.warn("duplicate_file", path+" is given twice", b.Start)
		}
		seen[file{path, part}] = true
		p.Files = append(p.Files, filePart{path, part, b.Lang, b.Body})
		if strings.HasSuffix(path, ".py") || pythonLang(b.Lang) {
			if _, e := pyParse(b.Body); e != nil {
				p.err("syntax_error", path+": SyntaxError: "+e.msg, b.Start+max(e.line, 1))
			}
		}
		if pyHas(stubRe, b.Body) {
			p.warn("placeholder", path+" has a TODO, placeholder or stub", b.Start)
		}
	}
}

// sectionPiece checks that a section starts with ## and keeps the mode rule's other
// checkable parts.
func sectionPiece(p *workerPiece, step *hydraStep) {
	body := p.Body
	first, _, _ := strings.Cut(body, "\n")
	if !strings.HasPrefix(body, "## ") {
		why := "doesn't start with a ## heading"
		if strings.HasPrefix(first, "# ") {
			why = "starts with a level-1 heading"
		}
		p.err("no_heading", "the section "+why, 1)
		return
	}
	heading := pyTrim(first[3:])
	p.Section = body
	var title, instructions, kind string
	if step != nil {
		title, instructions, kind = step.Title, step.Instructions, step.Kind
	}
	if title != "" && normTitle(heading) != normTitle(title) && !strings.Contains(normTitle(instructions), normTitle(heading)) {
		p.warn("heading_not_title", "heading "+pyRepr(heading)+" is neither the step's title nor in its instructions", 1)
	}
	if m := pyMatches(aiTalkRe, body); len(m) > 0 {
		p.warn("ai_talk", "mentions "+pyRepr(body[m[0][0]:m[0][1]]), strings.Count(body[:m[0][0]], "\n")+1)
	}
	if kind != "research" {
		return
	}
	for _, m := range pyMatches(linkRe, body) {
		end := strings.Index(body[m[1]:], "\n")
		if end < 0 {
			end = len(body)
		} else {
			end += m[1]
		}
		if !strings.Contains(body[m[0]:end], "(unverified)") {
			p.warn("unmarked_link", capChars(body[m[0]:m[1]], 80)+" isn't marked (unverified)", strings.Count(body[:m[0]], "\n")+1)
		}
	}
}

// pieceVerdict is a piece as data, for --hydra-assemble.
type pieceVerdict struct {
	Sid        string           `json:"sid"`
	Mode       string           `json:"mode"`
	OK         bool             `json:"ok"`
	ContractOK bool             `json:"contract_ok"`
	FormOK     bool             `json:"form_ok"`
	Issues     []pieceIssue     `json:"issues"`
	Handoff    map[string]any   `json:"handoff"`
	Files      []map[string]any `json:"files"`
	Body       string           `json:"body"`
	Code       string           `json:"code"`
	CodeLine   int              `json:"code_line"`
	Section    string           `json:"section"`
	Library    bool             `json:"library"`
}

func (p *workerPiece) verdict() pieceVerdict {
	v := pieceVerdict{Sid: p.Sid, Mode: p.Mode, OK: p.ok(), ContractOK: p.contractOK(), FormOK: p.formOK(),
		Issues: p.Issues, Files: []map[string]any{}, Body: p.Body, Code: p.Code, CodeLine: p.CodeLine, Section: p.Section, Library: p.Library}
	if v.Issues == nil {
		v.Issues = []pieceIssue{}
	}
	if h := p.Handoff; h != nil {
		v.Handoff = map[string]any{"provides": h.Provides, "uses": h.Uses, "assumed": h.Assumed}
	}
	for _, f := range p.Files {
		v.Files = append(v.Files, map[string]any{"path": f.Path, "part": f.Part, "lang": f.Lang})
	}
	return v
}
