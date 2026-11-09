package main

// The sub-agent contract: what a worker is told when Chimera itself is going to
// join the pieces (docs/hydra-worker-plan.md, "The sub-agent contract", approved by
// the user on Nov 1). Each step gets a shape to keep, chosen from what the step is
// (its mode), the whole plan, and the handoffs of the steps it uses, so that the
// pieces fit without a model reading them all again.
//
// This file is the source of truth for those texts. Training data is built from them
// with chimera --hydra-worker-request, so a model learns exactly what it will be
// sent; change one and the model needs retraining. Nothing here runs in a real long
// task yet: those keep workerPrompt. The Python prototype this came from is
// worker-model/contract/, and worker-model/tools/check_contract_parity.py fails if
// the two build different requests.

import (
	"fmt"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

// The frozen texts. {name} is filled in by fillText, so the rules' own braces stay.
const (
	contractOpening = `You are one worker in Chimera: a sub-agent. A planner split a person's task into steps, and AI models on different computers are doing them at the same time. You do step {sid} of {n}. When every step is done, Chimera joins the pieces into the finished result, so build only your piece, exactly in the shape below, and leave the other steps' work to them. Nobody will answer questions: if something is missing, make a sensible assumption and say so in your handoff.`

	contractProject = `Project: {title}
{summary}`

	contractPlanHead     = `The plan (→ is your step; the others are there so you can use their names and stay out of their way):`
	contractOutlineOther = `  {name}. {title} [{kind}]{uses}: {instructions}`
	contractOutlineYours = `→ {name}. {title} [{kind}]{uses}: your step, in full below`
	contractOutlineUses  = ` (uses {names})`
	contractOutlineCut   = 300 // characters of another step's instructions
	contractUsedBy       = `Steps that use your piece: {names}.`
	contractUsedByNone   = `Nothing else uses your piece: it goes straight into the finished result.`
	contractJoinHead     = `How Chimera joins your piece:`

	contractHandoff = "End with this block, one short line each (\"none\" if there's nothing):\n" +
		"```handoff\n" +
		"provides: what your piece makes that other steps or the result use, by exact name\n" +
		"uses: what you took from which step, by exact name\n" +
		"assumed: what you had to guess\n" +
		"```"

	contractLoneOpening = `You are one worker in Chimera, and the only one on this task: your reply is the finished result the person gets. Nobody will answer questions: if something is missing, make a sensible assumption and say so.`

	rulesBlender = `Write one python code block for Blender 5.0 or newer, run headless with blender -b --python. At the top level put only imports, one dict SETTINGS_{sid} = {...} with the values a person might want to change, and def build_{sid}(ctx): holding all your step's work (helpers go inside it or are named _{sid}_…). End with if __name__ == "__main__": build_{sid}({"scene": bpy.context.scene, "collection": bpy.context.scene.collection, "objects": {}, "values": {}}). Chimera calls every step's build_ function in plan order in one script with one shared ctx: ctx["scene"]; ctx["collection"], the project's collection, where you link everything you create; ctx["objects"], where you register what other steps use under short keys (ctx["objects"]["table"] = obj) and find what your dependencies list under provides. ctx["values"] is the same for plain values other steps use, such as sizes, colours and counts; hand on the ones a person might change from your SETTINGS_{sid}, so they stay editable there (ctx["values"]["table_height"] = SETTINGS_{sid}["table_height"]). If one is missing because your piece runs alone, make a simple stand-in and print("chimera: stand-in", key). Name new objects, materials and collections chimera_…. Prefer bpy.data over bpy.ops. Don't open, load or save .blend files, render or quit: if your step says to, put the path or render settings in SETTINGS_{sid}["output"] and Chimera does it once, after the last step; if it says to open a file another step saved, use what that step built, which is already in the scene. Don't delete or change what you didn't create, and change scene-wide settings (engine, world, colour management) only if your step is about them.`

	rulesPythonScript = `Write Python 3 functions and classes only, in one python code block, with no code that runs on import. Chimera puts every step's code into one file in plan order. Use exactly the names the plan gives and don't redefine another step's names. If your step runs the program, define main(); Chimera calls it at the end.`

	rulesFiles = `Give each file you own in full, in its own fenced block with the language named, with its path on the line just before it, like File: src/store.py. If another step also writes that file, give only your part, marked File: src/store.py (part). Import other steps' code by the plan's exact names. No placeholders, TODOs or stubs for other steps' parts. Under provides, list your files and public signatures and, if your step runs the program, how.`

	rulesSection = `Write only your section, starting with ## and the heading your step gives (else its title). No introduction, conclusion or summary of the whole project unless that is your step; don't repeat what other steps cover; use your dependencies' terms; match any tone and length your step gives; don't mention that you're an AI or that there are other workers.`

	rulesResearch = `Give concrete findings. You have no internet: never invent sources, links, numbers or quotes; mark anything uncertain (unverified).`

	contractUserStep = `Your step, {sid}: {title}
{instructions}`

	contractUserDepHead    = `From {name}, "{title}" (you use it):`
	contractUserDepHandoff = `Its handoff:
{lines}`
	contractUserDepNoHandoff = `Its handoff: none (it didn't give one)`
	contractUserDepCut       = 8000 // bytes, like runStep's truncate
	contractUserDepFailed    = `(that step failed; assume what you need and list it under assumed)`

	contractRound2Part = `Last round's result for your part:
{part}`
	contractRound2Cut      = 6000 // bytes, when its own part can't be found
	contractRound2Critique = `What still needs work:
{critique}`
	contractRound2NoCritique = `none`

	contractRepair = `Your piece crashed when Chimera ran the joined script in {runner}:
line {line} in {function}: {source}
{exception}

Your piece was:
{piece}

Give your whole piece again, fixed, in the same shape and with the same names. Running stops at the first error, so check the rest of your piece against {runner}'s API too.`

	contractRepairImports = `the imports`

	// The words of namesBlock (blender_names.go) in front of the sheet.
	contractNamesHead = "\n\nThe exact names in the Blender this will run on, printed by that Blender. Use these, not ones you remember from other versions:\n"

	contractRoom = 4096 // a step's reply room, as runStep's first round
)

// The modes: the shape a step's piece comes back in.
const (
	modeBlender      = "blender"
	modePythonScript = "python-script"
	modeFiles        = "files"
	modeSection      = "section"
)

var modeRules = map[string]string{modeBlender: rulesBlender, modePythonScript: rulesPythonScript, modeFiles: rulesFiles, modeSection: rulesSection}

// fillText puts values into a frozen text, given as name, value pairs, in one pass:
// a title holding "{summary}" isn't filled in again.
func fillText(text string, pairs ...string) string {
	r := make([]string, 0, len(pairs))
	for i := 0; i+1 < len(pairs); i += 2 {
		r = append(r, "{"+pairs[i]+"}", pairs[i+1])
	}
	return strings.NewReplacer(r...).Replace(text)
}

// ---------- reading plans the way the prototype measured them ----------

// RE2 has no lookarounds and its \b, \w and \s are ASCII only, while plans are full
// of no-break spaces and letters from everywhere. So the patterns below spell out
// Python's \w and \s, which is what they were measured with, and write a boundary as
// the one character beside the match, with the match itself in a capture group.
const (
	pyWordChars  = `\p{L}\p{N}_`
	pySpaceChars = `\t\n\v\f\r \x1c-\x1f\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}`
	pyW          = `[` + pyWordChars + `]`
	pyS          = `[` + pySpaceChars + `]`
	notWord      = `[^` + pyWordChars + `]`
)

// isPySpace is str.isspace: unicode.IsSpace plus four control characters.
func isPySpace(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) }

func pyTrim(s string) string { return strings.TrimFunc(s, isPySpace) }

// oneLine squashes whitespace to single spaces, for the outline's one-line entries.
func oneLine(s string) string { return strings.Join(strings.FieldsFunc(s, isPySpace), " ") }

// pyMatches finds a pattern's matches the way Python's finditer does. The newlines
// stand for the two ends of the text, which pass every boundary here, and each next
// search starts on the last character of the match before, so that it can be a
// boundary again. It returns each match's start and end in text.
func pyMatches(re *regexp.Regexp, text string) [][2]int {
	s := "\n" + text + "\n"
	var out [][2]int
	for at := 0; ; {
		m := re.FindStringSubmatchIndex(s[at:])
		if m == nil {
			return out
		}
		g := 2
		for m[g] < 0 { // the group of the alternative that matched
			g += 2
		}
		start, end := at+m[g], at+m[g+1]
		out = append(out, [2]int{start - 1, end - 1})
		_, size := utf8.DecodeLastRuneInString(s[:end])
		at = end - size
	}
}

func pyHas(re *regexp.Regexp, text string) bool { return re.MatchString("\n" + text + "\n") }

const (
	// Source files only: a Python script that reads data.csv or writes report.json is
	// still one script.
	codeExts = `py|pyi|pyw|js|mjs|cjs|ts|tsx|jsx|go|rs|java|kt|kts|swift|cpp|cc|cxx|hpp|cs|rb|php|html|htm|css|scss|sass|less|vue|svelte|lua|dart|sh|bash|zsh|ps1|toml|gradle|sql`

	techNouns = `program|programs|code|codebase|app|apps|application|project|crate|crates|library|module|modules|package|packages|gem|gems|component|components|hook|hooks|server|service|backend|frontend|front end|front-end|API|CLI|tool|binary|script|scripts|compiler|toolchain|page|pages|site|website|template|templates|UI|widget|widgets|route|routes|middleware|plugin|extension|test|tests|on Rails|Native|router|controller|file|files|function|functions|struct|structs|trait|traits|macro|macros|form|forms`

	langBefore     = `(?:[Ii]n|[Uu]sing|[Ww]ritten in)`
	langBeforeWith = `(?:[Ii]n|[Uu]sing|[Ww]ritten in|[Ww]ith)`
	wordNames      = `Rust|Swift|Ruby|Rails|Dart|Flutter|Elixir|React|Angular|Vue|Svelte|Electron|Jest|Node`
)

var (
	// Blender's own module and feature names: a plan that never says "Blender" can
	// still be one. EEVEE only in capitals (Eevee is a Pokémon).
	blenderWordsRe = regexp.MustCompile(notWord + `(?i:blender|bpy|bmesh|mathutils|geometry nodes|principled bsdf|pointiness)` + notWord + `|(?i:\.blend)` + notWord + `|` + notWord + `EEVEE` + notWord)

	pathRe = regexp.MustCompile(`[^` + pyWordChars + `/.-]((?:[` + pyWordChars + `.-]+/)*[` + pyWordChars + `-]+\.(?:` + codeExts + `))` + notWord +
		`|` + notWord + `(Dockerfile|Makefile|package\.json|go\.mod|Cargo\.toml|requirements\.txt|pyproject\.toml)` + notWord)

	// "Other languages", in three kinds. Names that are seldom anything else, in any
	// case, plus tools and frameworks that imply a language (.NET in capitals, after
	// anything, for ASP.NET);
	langNamesRe = regexp.MustCompile(`[^` + pyWordChars + `.]((?i:javascript|typescript|node\.?js|deno|golang|kotlin|haskell|perl|powershell|objective-c|php|scala|lua|java|jquery|next\.js|nuxt|vue\.?js|react\.?js|reactjs|react native|angularjs|sveltekit|swiftui|spring boot|gradle|npm|webpack|html5|bash script|shell script|zsh script|minecraft mod|fabric mod|forge mod|neoforge|spigot|bukkit|nullpointerexception|chrome extension|browser extension|firefox add-on|userscript|android app|xcode|c\+\+|c#|csharp|dotnet))[^` + pyWordChars + `+#]` +
		`|(?s:.)(\.NET)` + notWord)
	// names that are also English words, capitalised and next to a programming word:
	// "in Rust", "a Swift package", "my Express API", not "rust patches" or "react to";
	// Go keeps a narrower rule, since "Go file by file" is an instruction, not Go code;
	wordLangsRe = regexp.MustCompile(notWord + `(` + langBeforeWith + ` (?:` + wordNames + `)|` + langBefore + ` Express|(?:` + wordNames + `|Express)` + pyS + `+(?:` + techNouns + `))[^` + pyWordChars + `-]`)
	goLangRe    = regexp.MustCompile(notWord + `(Go` + pyS + `+(?:program|module|code|package|service|server|binary|CLI|tool|app)s?|` + langBefore + ` Go)[^` + pyWordChars + `-]`)
	// HTML and CSS: paired, or "in HTML", or before a web word, unless the sentence
	// says a program reads or writes it ("scrape HTML pages", "an HTML report").
	webPairRe = regexp.MustCompile(notWord + `((?:HTML|CSS)` + pyS + `*(?:/|and|&|\+|,)` + pyS + `*(?:HTML|CSS|JS|JavaScript))` + notWord)
	webRe     = regexp.MustCompile(notWord + `(` + langBefore + ` (?:HTML|CSS)|(?:HTML|CSS)` + pyS + `+(?:page|pages|file|files|site|website|frontend|front end|front-end|UI|form|forms|template|templates|markup|stylesheet|stylesheets|styles|selector|selectors|grid|layout|animation|animations))` + notWord)
	webDataRe = regexp.MustCompile(notWord + `(?:(?i:scrap|pars|crawl|fetch|download|extract|generat|render|export|convert)` + pyW + `*|(?i:outputs?|sav(?:e|es|ing)|prints?|printing|emails?|reads?|reading))` + notWord)
)

// otherLanguage gives the words that make text name a language other than Python
// (or imply one), "" if none.
func otherLanguage(text string) string {
	for _, re := range []*regexp.Regexp{langNamesRe, wordLangsRe, goLangRe, webPairRe} {
		if m := pyMatches(re, text); len(m) > 0 {
			return text[m[0][0]:m[0][1]]
		}
	}
	for _, m := range pyMatches(webRe, text) {
		sentence := strings.LastIndexAny(text[:m[0]], ".!?\n") + 1
		if !pyHas(webDataRe, text[sentence:m[0]]) {
			return text[m[0]:m[1]]
		}
	}
	return ""
}

// stepName is a step's name in the contract, by position: s1 to s8 (cleanPlan allows
// 8), so build_s2 is always valid Python. The planner's own ids only link depends_on.
func stepName(i int) string { return "s" + strconv.Itoa(i+1) }

// depIndexes lists the steps step i depends on, in plan order, once each. An id that
// cleanPlan left clashing means its first step.
func depIndexes(plan hydraPlan, i int) []int {
	first := map[string]int{}
	for j := len(plan.Steps) - 1; j >= 0; j-- {
		first[plan.Steps[j].ID] = j
	}
	var out []int
	for _, d := range plan.Steps[i].DependsOn {
		if j, ok := first[d]; ok && j < i && !slices.Contains(out, j) {
			out = append(out, j)
		}
	}
	slices.Sort(out)
	return out
}

func depNames(plan hydraPlan, i int) []string {
	out := []string{}
	for _, j := range depIndexes(plan, i) {
		out = append(out, stepName(j))
	}
	return out
}

// userNames lists the steps that use step i's piece.
func userNames(plan hydraPlan, i int) []string {
	out := []string{}
	for j := range plan.Steps {
		if slices.Contains(depIndexes(plan, j), i) {
			out = append(out, stepName(j))
		}
	}
	return out
}

// contractPlanText is everything mode selection reads.
func contractPlanText(plan hydraPlan, goal string) string {
	parts := []string{goal, plan.Title, plan.Summary}
	for _, s := range plan.Steps {
		parts = append(parts, s.Title, s.Instructions)
	}
	return strings.Join(parts, "\n")
}

// codeMode is the mode a code step of this plan gets. A code step can be a Blender
// one (the fallback planner mislabels these), and a plan is a set of files as soon
// as it names a path or another language.
func codeMode(plan hydraPlan, goal string) string {
	text := contractPlanText(plan, goal)
	switch {
	case pyHas(blenderWordsRe, text):
		return modeBlender
	case pyHas(pathRe, text) || otherLanguage(text) != "":
		return modeFiles
	}
	return modePythonScript
}

// stepMode is the mode of step i.
func stepMode(plan hydraPlan, i int, goal string) string {
	switch plan.Steps[i].Kind {
	case "blender":
		return modeBlender
	case "code":
		return codeMode(plan, goal)
	}
	return modeSection
}

// ---------- the worker's request ----------

// workerAsk is what a step's request is built from, besides the plan. A dependency's
// reply is its step's Output, and a step with Status "failed" has none.
type workerAsk struct {
	Goal       string
	Refs       []LibEntry
	Names      string  // the names sheet, if there's one for this step
	PrevResult *string // from round 2 on, last round's result
	Critique   string
	Room       int // reply room on top of the input: contractRoom unless it was cut off
}

type workerRequest struct {
	Messages      []ChatMessage `json:"messages"`
	NeedCtx       int           `json:"need_ctx"`
	Mode          string        `json:"mode"`
	Sid           string        `json:"sid"`
	N             int           `json:"n"`
	Lone          bool          `json:"lone"`
	Deps          []string      `json:"deps"`
	Round2Matched bool          `json:"round2_matched"` // its own part was found in last round's result
}

// modeRulesFor is the frozen rules for a mode, for step sid. Research adds a line.
func modeRulesFor(mode, sid, kind string) string {
	rules := fillText(modeRules[mode], "sid", sid)
	if mode == modeSection && kind == "research" {
		rules += "\n" + rulesResearch
	}
	return rules
}

// contractOutline is the plan's lines, with → on step i.
func contractOutline(plan hydraPlan, i int) string {
	var out []string
	for j, s := range plan.Steps {
		uses := ""
		if deps := depNames(plan, j); len(deps) > 0 {
			uses = fillText(contractOutlineUses, "names", strings.Join(deps, ", "))
		}
		vals := []string{"name", stepName(j), "title", oneLine(s.Title), "kind", s.Kind, "uses", uses}
		if j == i {
			out = append(out, fillText(contractOutlineYours, vals...))
		} else {
			out = append(out, fillText(contractOutlineOther, append(vals, "instructions", capRunes(oneLine(s.Instructions), contractOutlineCut))...))
		}
	}
	return strings.Join(out, "\n")
}

// contractNames puts namesBlock's words around a names sheet.
func contractNames(sheet string) string {
	if sheet == "" {
		return ""
	}
	return contractNamesHead + sheet
}

// contractSystem is the system prompt for step i. A lone step's reply is the result
// itself: it gets the same rules, but no plan and no handoff.
func contractSystem(plan hydraPlan, i int, ask workerAsk) string {
	sid, n := stepName(i), len(plan.Steps)
	rules := modeRulesFor(stepMode(plan, i, ask.Goal), sid, plan.Steps[i].Kind)
	project := fillText(contractProject, "title", plan.Title, "summary", plan.Summary)
	var parts []string
	if n == 1 {
		parts = []string{contractLoneOpening, project, contractJoinHead + "\n" + rules}
	} else {
		used := contractUsedByNone
		if users := userNames(plan, i); len(users) > 0 {
			used = fillText(contractUsedBy, "names", strings.Join(users, ", "))
		}
		parts = []string{fillText(contractOpening, "sid", sid, "n", strconv.Itoa(n)), project,
			contractPlanHead + "\n" + contractOutline(plan, i) + "\n" + used,
			contractJoinHead + "\n" + rules, contractHandoff}
	}
	return strings.Join(parts, "\n\n") + refsBlock(ask.Refs) + contractNames(ask.Names)
}

// depPart is one dependency's part of the user message: its handoff, then its piece
// without it, cut as runStep cuts it.
func depPart(plan hydraPlan, j int) string {
	s := plan.Steps[j]
	head := fillText(contractUserDepHead, "name", stepName(j), "title", s.Title)
	if s.Status == "failed" {
		return head + "\n" + contractUserDepFailed
	}
	handoff, blocks := parseHandoff(s.Output)
	lines := contractUserDepNoHandoff
	if handoff != nil {
		lines = fillText(contractUserDepHandoff, "lines", strings.Join(handoff.lines(), "\n"))
	}
	return head + "\n" + lines + "\n" + truncate(stripHandoff(s.Output, blocks), contractUserDepCut)
}

// contractUser is the user message for step i; from round 2 on it adds the step's
// part of last round's result and the critique, and says if that part was found.
func contractUser(plan hydraPlan, i int, ask workerAsk) (string, bool) {
	s := plan.Steps[i]
	parts := []string{fillText(contractUserStep, "sid", stepName(i), "title", s.Title, "instructions", s.Instructions)}
	for _, j := range depIndexes(plan, i) {
		parts = append(parts, depPart(plan, j))
	}
	matched := false
	if ask.PrevResult != nil {
		var part string
		part, matched = findPart(*ask.PrevResult, plan, i, stepMode(plan, i, ask.Goal))
		critique := ask.Critique
		if critique == "" {
			critique = contractRound2NoCritique
		}
		parts = append(parts, fillText(contractRound2Part, "part", part), fillText(contractRound2Critique, "critique", critique))
	}
	return strings.Join(parts, "\n\n"), matched
}

// contractRequest is the request for step i of a cleaned plan. NeedCtx as runStep.
func contractRequest(plan hydraPlan, i int, ask workerAsk) workerRequest {
	user, matched := contractUser(plan, i, ask)
	msgs := []ChatMessage{{Role: "system", Content: contractSystem(plan, i, ask)}, {Role: "user", Content: user}}
	return workerRequest{Messages: msgs, NeedCtx: historyTokens(msgs) + ask.Room, Mode: stepMode(plan, i, ask.Goal), Sid: stepName(i),
		N: len(plan.Steps), Lone: len(plan.Steps) == 1, Deps: depNames(plan, i), Round2Matched: matched}
}

// workerCrash is where a joined script crashed: a check's line, read through the line
// map. PieceLine is the line in the piece's own code block, the numbering the worker
// knows; the joined script's would mean nothing to it.
type workerCrash struct {
	Step      string `json:"step"`
	Part      string `json:"part"`     // settings or import, when no function holds the line
	Function  string `json:"function"` // build_s2, a _s2_ helper or constant
	PieceLine int    `json:"piece_line"`
	Line      int    `json:"line"`
	Source    string `json:"source"`
	Error     string `json:"error"`
	Runner    string `json:"runner"` // like "Blender 5.2.2"
}

// crashWhere is what the repair message's "in {function}" names.
func crashWhere(c workerCrash) string {
	if c.Function != "" {
		return c.Function
	}
	sid := c.Step
	if sid == "" {
		sid = "s1"
	}
	switch c.Part {
	case "settings":
		return "SETTINGS_" + sid
	case "import":
		return contractRepairImports
	}
	return "build_" + sid
}

// repairText is the repair message's own part. piece is the worker's whole reply.
func repairText(piece string, c workerCrash) string {
	runner := c.Runner
	if runner == "" {
		runner = "Blender"
	}
	line := "?"
	if c.PieceLine != 0 {
		line = strconv.Itoa(c.PieceLine)
	} else if c.Line != 0 {
		line = strconv.Itoa(c.Line)
	}
	return fillText(contractRepair, "runner", runner, "line", line, "function", crashWhere(c), "source", c.Source, "exception", c.Error, "piece", pyTrim(piece))
}

// contractRepairRequest is looping mode's step repair: the step's first-round request,
// then the repair message. Last round's result stays out of it: the piece is there.
func contractRepairRequest(plan hydraPlan, i int, ask workerAsk, piece string, c workerCrash) workerRequest {
	ask.PrevResult, ask.Critique = nil, ""
	req := contractRequest(plan, i, ask)
	req.Messages[1].Content += "\n\n" + repairText(piece, c)
	req.NeedCtx = historyTokens(req.Messages) + ask.Room
	return req
}

// ---------- reading a handoff ----------

// workerHandoff is a worker's three lines, as it wrote them.
type workerHandoff struct{ Provides, Uses, Assumed string }

// lines gives the three lines, "none" for an empty one.
func (h workerHandoff) lines() []string {
	or := func(s string) string {
		if s == "" {
			return "none"
		}
		return s
	}
	return []string{"provides: " + or(h.Provides), "uses: " + or(h.Uses), "assumed: " + or(h.Assumed)}
}

var (
	handoffKeyRe = regexp.MustCompile(`^` + pyS + `*((?i:provides|uses|assumed))` + pyS + `*:` + pyS + `*(.*?)` + pyS + `*$`)
	handoffNone  = regexp.MustCompile(`^(?i:(?:none|nothing|n/a|-)?\.?)$`)
	// A label line just above unfenced key lines: "handoff", "**Handoff**", "### Handoff".
	handoffLabelRe = regexp.MustCompile("^" + pyS + "*(?:#{1,6}" + pyS + "*)?[*_`]*" + pyS + "*(?i:handoff)" + pyS + "*:?" + pyS + "*[*_`]*" + pyS + "*:?" + pyS + "*$")
)

func handoffValue(v string) string {
	v = strings.TrimSpace(v)
	if handoffNone.MatchString(v) {
		return ""
	}
	return v
}

// handoffKey reads a provides, uses or assumed line.
func handoffKey(line string) (key, value string, ok bool) {
	m := handoffKeyRe.FindStringSubmatch(line)
	if m == nil {
		return "", "", false
	}
	return strings.ToLower(m[1]), m[2], true
}

// keyValues is the values of the key lines among lines.
func keyValues(lines []string) map[string]string {
	out := map[string]string{}
	for _, l := range lines {
		if k, v, ok := handoffKey(l); ok {
			out[k] = handoffValue(v)
		}
	}
	return out
}

// hasAllKeys says keys are provides, uses and assumed, repeats or not.
func hasAllKeys(keys []string) bool {
	set := map[string]bool{}
	for _, k := range keys {
		set[k] = true
	}
	return len(set) == 3 && set["provides"] && set["uses"] && set["assumed"]
}

// onlyKeyLines says a block holds the three lines and nothing else.
func onlyKeyLines(body string) bool {
	var keys []string
	n := 0
	for _, l := range strings.Split(body, "\n") {
		if strings.TrimSpace(l) == "" {
			continue
		}
		n++
		if k, _, ok := handoffKey(l); ok {
			keys = append(keys, k)
		}
	}
	return len(keys) == n && hasAllKeys(keys)
}

func plainLang(l string) bool {
	switch l {
	case "", "text", "txt", "plain", "plaintext", "yaml", "yml":
		return true
	}
	return false
}

// unfencedHandoff finds a handoff written with no fence: the reply's last non-blank
// lines, after every code block, are key lines, maybe under a label. The result
// stands for those lines: Start-1 is its first line and End its last.
func unfencedHandoff(text string, blocks []codeBlock) (codeBlock, bool) {
	lines := strings.Split(text, "\n")
	after := -1
	for _, b := range blocks {
		if !b.Closed {
			after = max(after, len(lines)) // an open block runs to the end
		} else {
			after = max(after, b.End)
		}
	}
	var keys []string
	first, last, k := -1, -1, len(lines)-1
	for ; k > after; k-- {
		if strings.TrimSpace(lines[k]) == "" {
			continue
		}
		key, _, ok := handoffKey(lines[k])
		if !ok {
			break
		}
		keys = append(keys, key)
		first = k
		if last < 0 {
			last = k
		}
	}
	if !hasAllKeys(keys) {
		return codeBlock{}, false
	}
	open := first
	if k > after && handoffLabelRe.MatchString(lines[k]) {
		open = k
	}
	return codeBlock{Lang: "handoff", Body: strings.Join(lines[first:last+1], "\n"), Closed: true, Start: open + 1, End: last}, true
}

// handoffBlocks finds a reply's handoff: the contract's ```handoff block, or else, read
// leniently because workers do write them, the three lines in a plain block (maybe
// left open at the end) or with no fence at the very end of the reply.
func handoffBlocks(text string) []codeBlock {
	all := codeBlocks(text)
	var fenced, plain []codeBlock
	for _, b := range all {
		if b.Lang == "handoff" {
			fenced = append(fenced, b)
		}
		if plainLang(b.Lang) && b.Closed && onlyKeyLines(b.Body) {
			plain = append(plain, b)
		}
	}
	if len(fenced) > 0 {
		return fenced
	}
	if len(plain) == 0 && len(all) > 0 {
		if b := all[len(all)-1]; !b.Closed && plainLang(b.Lang) && onlyKeyLines(b.Body) {
			plain = []codeBlock{b}
		}
	}
	if len(plain) > 0 {
		return plain[len(plain)-1:]
	}
	if b, ok := unfencedHandoff(text, all); ok {
		return []codeBlock{b}
	}
	return nil
}

// parseHandoff reads a reply's handoff, the last one if it wrote several, and gives
// the blocks it found. Whether the handoff keeps the contract's form is the
// validator's business: a next step just needs to read it.
func parseHandoff(text string) (*workerHandoff, []codeBlock) {
	blocks := handoffBlocks(text)
	if len(blocks) == 0 {
		return nil, nil
	}
	vals := keyValues(strings.Split(blocks[len(blocks)-1].Body, "\n"))
	return &workerHandoff{vals["provides"], vals["uses"], vals["assumed"]}, blocks
}

// copyAbove finds a copy of block b's three lines written just above it with no fence,
// maybe under a label: first and last line. With other values they may be the piece's
// own words, which stay.
func copyAbove(lines []string, b codeBlock) (from, to int, ok bool) {
	from, first, last, found := keysAbove(lines, b)
	if !found {
		return 0, 0, false
	}
	above, block := keyValues(lines[first:last+1]), keyValues(strings.Split(b.Body, "\n"))
	if len(above) != len(block) {
		return 0, 0, false
	}
	for key, v := range above {
		if w, in := block[key]; !in || v != w {
			return 0, 0, false
		}
	}
	return from, last, true
}

// stripHandoff is a reply without its handoff blocks, trimmed.
func stripHandoff(text string, blocks []codeBlock) string {
	lines := strings.Split(text, "\n")
	drop := map[int]bool{}
	dropLines := func(from, to int) {
		for i := from; i <= to; i++ {
			drop[i] = true
		}
	}
	for _, b := range blocks {
		open := b.Start - 1
		end := len(lines) - 1
		if b.Closed {
			end = b.End
		}
		dropLines(open, end)
		if open > 0 {
			if from, to, ok := copyAbove(lines, b); ok {
				dropLines(from, to)
			}
		}
	}
	var kept []string
	for i, l := range lines {
		if !drop[i] {
			kept = append(kept, l)
		}
	}
	return strings.TrimSpace(strings.Join(kept, "\n"))
}

// ---------- round 2: a step's part of the last result ----------

var (
	scriptHeaderRe = regexp.MustCompile(`^# --- (s\p{Nd}+): (.*) ---$`)
	notTitleRe     = regexp.MustCompile(`[^` + pyWordChars + pySpaceChars + `]`)
	partMarkRe     = regexp.MustCompile(`^` + pyS + `*(?i:\(part\))` + pyS + `*$`)
)

func normTitle(s string) string {
	return oneLine(notTitleRe.ReplaceAllString(strings.ToLower(s), " "))
}

// fileLine reads a File: line, however it was decorated.
func fileLine(line string) (path string, part, ok bool) {
	path, part, _, ok = fileLineForm(line)
	return path, part, ok
}

// renameStep gives a step's names its number in this round's plan: steps move
// between rounds, and a piece has to be told its own names.
func renameStep(text, old, sid string) string {
	if old == sid {
		return text
	}
	q := regexp.QuoteMeta(old)
	re := regexp.MustCompile(notWord + `((?:SETTINGS_|build_)` + q + `)` + notWord + `|` + notWord + `(_` + q + `_)`)
	var b strings.Builder
	at := 0
	for _, m := range pyMatches(re, text) {
		b.WriteString(text[at:m[0]])
		if name := text[m[0]:m[1]]; name[0] == '_' {
			b.WriteString("_" + sid + "_")
		} else {
			b.WriteString(strings.TrimSuffix(name, old) + sid)
		}
		at = m[1]
	}
	b.WriteString(text[at:])
	return b.String()
}

// findPart finds the part of last round's result that step i redoes: its code by the
// step header's title, its files by the paths its title and instructions name, its
// section by heading. If it can't, the worker gets the result, cut.
func findPart(prev string, plan hydraPlan, i int, mode string) (string, bool) {
	st := plan.Steps[i]
	want, skip := normTitle(st.Title), 0 // steps with the same title get its parts in turn
	for _, s := range plan.Steps[:i] {
		if normTitle(s.Title) == want {
			skip++
		}
	}
	found, ok := "", false
	switch mode {
	case modeBlender, modePythonScript:
		found, ok = findScriptPart(prev, want, stepName(i), mode, skip)
	case modeFiles:
		found = findFilesPart(prev, st.Title+"\n"+st.Instructions)
		ok = found != ""
	case modeSection:
		found = findSection(prev, want, skip)
		ok = found != ""
	}
	if !ok {
		return truncate(prev, contractRound2Cut), false
	}
	return found, true
}

// findScriptPart finds a step's own code in a joined script, without Chimera's
// header. Chimera's own lines end it: in Blender its main(), in both the main guard
// (a python-script step may define main() itself, which stays in its part).
func findScriptPart(prev, want, sid, mode string, skip int) (string, bool) {
	for _, b := range codeBlocks(prev) {
		lines := strings.Split(b.Body, "\n")
		type header struct {
			at         int
			old, title string
		}
		var heads []header
		for k, l := range lines {
			if m := scriptHeaderRe.FindStringSubmatch(l); m != nil {
				heads = append(heads, header{k, m[1], m[2]})
			}
		}
		for n, h := range heads {
			if normTitle(h.title) != want {
				continue
			}
			if skip > 0 {
				skip--
				continue
			}
			end := len(lines)
			if n+1 < len(heads) {
				end = heads[n+1].at
			}
			for e := h.at + 1; e < end; e++ {
				if strings.HasPrefix(lines[e], "if __name__") || (mode == modeBlender && strings.HasPrefix(lines[e], "def main(")) {
					end = e
					break
				}
			}
			part := strings.Trim(strings.Join(lines[h.at+1:end], "\n"), "\n")
			if mode == modeBlender {
				// A result can hold every SETTINGS_ dict at the top.
				has := regexp.MustCompile(`(?m)^SETTINGS_` + regexp.QuoteMeta(h.old) + pyS + `*[:=]`)
				if !has.MatchString(part) {
					if settings := settingsOf(b.Body, h.old); settings != "" {
						part = settings + "\n\n\n" + part
					}
				}
			}
			return renameStep(part, h.old, sid), true
		}
	}
	return "", false
}

// findFilesPart gives the blocks of the files that the step's words name.
func findFilesPart(prev, words string) string {
	var paths []string
	for _, m := range pyMatches(pathRe, words) {
		paths = append(paths, words[m[0]:m[1]])
	}
	lines := strings.Split(prev, "\n")
	var found []string
	for _, b := range codeBlocks(prev) {
		j := b.Start - 2
		for j >= 0 && pyTrim(lines[j]) == "" {
			j--
		}
		if j < 0 {
			continue
		}
		path, part, ok := fileLine(lines[j])
		if !ok || !slices.Contains(paths, path) {
			continue
		}
		mark := ""
		if part {
			mark = " (part)"
		}
		found = append(found, fmt.Sprintf("File: %s%s\n```%s\n%s\n```", path, mark, b.Lang, b.Body))
	}
	return strings.Join(found, "\n\n")
}

// findSection gives the section under a ## heading with the step's title.
func findSection(prev, want string, skip int) string {
	lines := strings.Split(prev, "\n")
	for k, l := range lines {
		if !strings.HasPrefix(l, "## ") || normTitle(l[3:]) != want {
			continue
		}
		if skip > 0 {
			skip--
			continue
		}
		end := k + 1
		for end < len(lines) && !strings.HasPrefix(lines[end], "# ") && !strings.HasPrefix(lines[end], "## ") {
			end++
		}
		return pyTrim(strings.Join(lines[k:end], "\n"))
	}
	return ""
}

// settingsOf finds a step's SETTINGS_ dict among a script's top-level statements,
// with the comments just above it. Only a plain assignment counts.
func settingsOf(script, sid string) string {
	tree, e := pyParse(script)
	if e != nil {
		return ""
	}
	lines := strings.Split(script, "\n")
	for _, s := range pySegments(script, tree) {
		if isSettings(s.node, sid) {
			return strings.Join(sourceLines(lines, s.start, s.end), "\n")
		}
	}
	return ""
}
