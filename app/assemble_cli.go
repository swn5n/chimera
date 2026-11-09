package main

// chimera --hydra-assemble: reads one JSON object on stdin and prints, as JSON, what the
// joiner makes of a plan's pieces. It's how training data gets Chimera's own verdicts
// and joined scripts, and how worker-model/tools/check_join_parity.py compares them
// with the prototype. It needs no data folder, network or window.
//
// The input: plan, as the planner wrote it (it's cleaned here); outputs, each step's
// reply by plan id, as for --hydra-worker-request; goal; done_reasons, Ollama's by plan
// id; reject_cut. The output is what joining gives, with the pieces' verdicts.
//
// Other jobs share the mode, and a job given leaves the join out: validate checks
// replies on their own (a cut reply fails unless reject_cut says otherwise, and
// max_tokens is the usual limit if it's left out, 0 for none), alone gives a piece's
// run-alone script, locate reads a check through a line map, and merge, uses_names,
// slug and scan call one part directly, for comparing with the prototype.

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
)

type pieceInput struct {
	Text       string     `json:"text"`
	Mode       string     `json:"mode"`
	Sid        *string    `json:"sid"`
	Deps       []string   `json:"deps"`
	Lone       bool       `json:"lone"`
	Step       *hydraStep `json:"step"`
	DoneReason string     `json:"done_reason"`
	RejectCut  *bool      `json:"reject_cut"`
	MaxTokens  *int       `json:"max_tokens"` // absent for the usual limit, 0 for none
}

func (in pieceInput) validate() *workerPiece {
	ask := pieceAsk{Mode: in.Mode, Sid: "s1", Deps: in.Deps, Lone: in.Lone, Step: in.Step, DoneReason: in.DoneReason, RejectCut: true, MaxTokens: maxPieceTokens}
	if in.Sid != nil {
		ask.Sid = *in.Sid
	}
	if in.RejectCut != nil {
		ask.RejectCut = *in.RejectCut
	}
	if in.MaxTokens != nil {
		ask.MaxTokens = *in.MaxTokens
	}
	return validatePiece(in.Text, ask)
}

type aloneInput struct {
	pieceInput
	KeepCtx bool     `json:"keep_ctx"`
	CtxName string   `json:"ctx_name"`
	Also    []string `json:"also"`
}

type mergeInput struct {
	Base  *string     `json:"base"`
	Parts [][2]string `json:"parts"` // step, body
}

type locateInput struct {
	LineMap lineMap `json:"linemap"`
	Check   checkAt `json:"check"`
	Script  *string `json:"script"`
}

type assembleInput struct {
	Plan        hydraPlan                  `json:"plan"`
	Outputs     map[string]json.RawMessage `json:"outputs"`
	Goal        string                     `json:"goal"`
	DoneReasons map[string]string          `json:"done_reasons"`
	RejectCut   bool                       `json:"reject_cut"`

	Validate   []pieceInput  `json:"validate"`
	Alone      []aloneInput  `json:"alone"`
	Locate     []locateInput `json:"locate"`
	Merge      []mergeInput  `json:"merge"`
	UsesNames  []string      `json:"uses_names"`
	UsesChunks []string      `json:"uses_chunks"`
	Slug       []string      `json:"slug"`
	Scan       []string      `json:"scan"`
}

// assembled is joinPlan's result as data.
type assembled struct {
	Title           string         `json:"title"`
	Fallback        bool           `json:"fallback"`
	Reasons         []string       `json:"reasons"`
	Seams           []pieceIssue   `json:"seams"`
	Notes           []string       `json:"notes"`
	Failed          []string       `json:"failed"`
	Script          *string        `json:"script"`
	ScriptKind      string         `json:"script_kind"`
	Text            string         `json:"text"`
	LineMap         *lineMap       `json:"linemap"`
	Files           []joinedFile   `json:"files"`
	Parts           []joinedPart   `json:"parts"`
	Assumptions     [][2]string    `json:"assumptions"`
	AssumptionsNote string         `json:"assumptions_note"`
	EditorWanted    bool           `json:"editor_wanted"`
	Pieces          []pieceVerdict `json:"pieces"`
}

func assembleResult(j *joinedResult) assembled {
	out := assembled{Title: j.PlanTitle, Fallback: j.Fallback, Reasons: orEmpty(j.Reasons), Seams: orEmpty(j.Seams), Notes: orEmpty(j.Notes),
		Failed: orEmpty(j.Failed), ScriptKind: j.ScriptKind, Text: j.Text, LineMap: j.LineMap, Files: orEmpty(j.Files), Parts: orEmpty(j.Parts),
		Assumptions: orEmpty(j.Assumptions), AssumptionsNote: j.assumptionsNote(), EditorWanted: j.EditorWanted, Pieces: []pieceVerdict{}}
	if j.HasScript {
		out.Script = &j.Script
	}
	for _, p := range j.Pieces {
		out.Pieces = append(out.Pieces, p.verdict())
	}
	return out
}

// orEmpty keeps a list a list in the JSON, with nothing in it.
func orEmpty[T any](s []T) []T {
	if s == nil {
		return []T{}
	}
	return s
}

type scanResult struct {
	OK   bool   `json:"ok"`
	Tree string `json:"tree,omitempty"`
	Line int    `json:"line,omitempty"`
	Msg  string `json:"msg,omitempty"`
}

func scanSource(src string) scanResult {
	tree, err := pyParse(src)
	if err != nil {
		return scanResult{Line: err.line, Msg: err.msg}
	}
	var b strings.Builder
	pyDump(&b, tree)
	return scanResult{OK: true, Tree: b.String()}
}

// otherJobs runs what's asked for besides a join: nil if nothing is.
func otherJobs(r assembleInput) map[string]any {
	out := map[string]any{}
	if r.Validate != nil {
		verdicts := []pieceVerdict{}
		for _, in := range r.Validate {
			verdicts = append(verdicts, in.validate().verdict())
		}
		out["validate"] = verdicts
	}
	if r.Alone != nil {
		scripts := []*string{} // null for a piece with no code to run
		for _, in := range r.Alone {
			name := in.CtxName
			if name == "" {
				name = "ctx"
			}
			p := in.validate()
			if p.Tree == nil {
				scripts = append(scripts, nil)
				continue
			}
			script := aloneScript(p, in.KeepCtx, name, in.Also)
			scripts = append(scripts, &script)
		}
		out["alone"] = scripts
	}
	if r.Locate != nil {
		spots := []checkSpot{}
		for _, in := range r.Locate {
			spots = append(spots, in.LineMap.locateCheck(in.Check, in.Script))
		}
		out["locate"] = spots
	}
	if r.Merge != nil {
		merged := []*string{}
		for _, in := range r.Merge {
			var parts []stepBody
			for _, p := range in.Parts {
				parts = append(parts, stepBody{p[0], p[1]})
			}
			if m, ok := mergePython(in.Base, parts); ok {
				merged = append(merged, &m)
			} else {
				merged = append(merged, nil)
			}
		}
		out["merge"] = merged
	}
	if r.UsesNames != nil {
		names := [][]string{}
		for _, s := range r.UsesNames {
			names = append(names, append([]string{}, usesNames(s)...))
		}
		out["uses_names"] = names
	}
	if r.UsesChunks != nil {
		lines := [][][2]any{}
		for _, s := range r.UsesChunks {
			chunks := [][2]any{}
			for _, c := range usesChunks(s) {
				chunks = append(chunks, [2]any{c.steps, c.text})
			}
			lines = append(lines, chunks)
		}
		out["uses_chunks"] = lines
	}
	if r.Slug != nil {
		slugs := []string{}
		for _, s := range r.Slug {
			slugs = append(slugs, planSlug(s))
		}
		out["slug"] = slugs
	}
	if r.Scan != nil {
		scans := []scanResult{}
		for _, src := range r.Scan {
			scans = append(scans, scanSource(src))
		}
		out["scan"] = scans
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

func runAssemble(in io.Reader, out io.Writer) int {
	fail := func(format string, args ...any) int {
		fmt.Fprintf(os.Stderr, "assemble: "+format+"\n", args...)
		return 2
	}
	var r assembleInput
	if err := json.NewDecoder(in).Decode(&r); err != nil {
		return fail("%v", err)
	}
	for _, v := range r.Validate {
		if modeRules[v.Mode] == "" {
			return fail("unknown mode %q", v.Mode)
		}
	}
	for _, v := range r.Alone {
		if modeRules[v.Mode] == "" {
			return fail("unknown mode %q", v.Mode)
		}
	}
	var result any
	if jobs := otherJobs(r); jobs != nil {
		result = jobs
	} else {
		plan := cleanPlan(r.Plan)
		for i := range plan.Steps {
			s := &plan.Steps[i]
			var err error
			if s.Output, s.Status, err = stepOutcome(r.Outputs[s.ID]); err != nil {
				return fail("the output of %s: %v", s.ID, err)
			}
		}
		result = assembleResult(joinPlan(plan, joinAsk{Goal: r.Goal, DoneReasons: r.DoneReasons, RejectCut: r.RejectCut}))
	}
	enc := json.NewEncoder(out)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(result); err != nil {
		return fail("%v", err)
	}
	return 0
}
