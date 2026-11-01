package main

// A script is changed by edits, not written out again. Asked for the whole
// script back, a model that's fixing one line retypes hundreds and sometimes
// drops or changes some on the way; on the Oct 31 three-computer task
// consecutive rounds kept 6-15% of their lines and most crashes were in lines
// nobody had meant to touch. With edits a repair costs a few hundred tokens
// and can't turn into a rewrite: Chimera applies them, and the check runs again.

import (
	"context"
	"fmt"
	"log"
	"regexp"
	"slices"
	"strings"
)

// hydraMends is how many repairs a crashed script gets in a round: every real
// script that got there at all did so within 8, and most have several faults.
const hydraMends = 8

// editRe finds one edit in a reply. Its markers are whole lines, since a comment
// banner in the code can hold the same characters. An edit without its end
// marker, from a reply that stopped early, isn't complete, so it doesn't count.
var editRe = regexp.MustCompile(`(?ms)^[ \t]*<{5,}[ \t]*FIND[^\n]*\n(.*?)^[ \t]*={5,}[ \t]*\n(.*?)^[ \t]*>{5,}[ \t]*END`)

// fenceLineRe is a line that opens or closes a code block, and editMarkerRe
// the line an edit starts with.
var (
	fenceLineRe  = regexp.MustCompile("^[ \t]*(```|~~~)[\\w.-]*[ \t]*$")
	editMarkerRe = regexp.MustCompile(`(?m)^[ \t]*<{5,}[ \t]*FIND`)
)

type edit struct{ Find, Replace string }

// parseEdits reads the edits in a reply. A repeated edit counts once. An edit
// that would add a code fence is dropped: it would end the script's own block,
// and whatever came after it would no longer be checked. So is one that ran into
// the next edit for want of its end marker.
func parseEdits(reply string) []edit {
	reply = strings.ReplaceAll(reply, "\r\n", "\n")
	var out []edit
	for _, m := range editRe.FindAllStringSubmatch(reply, -1) {
		e := edit{unfence(strings.TrimSuffix(m[1], "\n")), unfence(strings.TrimSuffix(m[2], "\n"))}
		if strings.TrimSpace(e.Find) == "" || fenceLines(e.Replace) != fenceLines(e.Find) || slices.Contains(out, e) || editMarkerRe.MatchString(m[2]) {
			continue
		}
		out = append(out, e)
	}
	return out
}

// unfence takes off a code fence around one side of an edit.
func unfence(s string) string {
	lines := strings.Split(s, "\n")
	if n := len(lines); n >= 2 && fenceLineRe.MatchString(lines[0]) && fenceLineRe.MatchString(lines[n-1]) {
		return strings.Join(lines[1:n-1], "\n")
	}
	return s
}

func fenceLines(s string) int {
	n := 0
	for _, l := range strings.Split(s, "\n") {
		if fenceLineRe.MatchString(l) {
			n++
		}
	}
	return n
}

// applyEdits makes the edits it can in text and says how many took and how
// many found nothing to change. Lines match without their trailing spaces and,
// failing that, without their indent, which is what models get wrong (and a
// script inside a list item has an extra one): the new lines then move by the
// same amount. An edit that matches several places changes them all, since a
// wrong line copied around is wrong everywhere, unless it only adds lines: those
// belong in one place, and it doesn't say which.
func applyEdits(text string, edits []edit) (string, int, int) {
	lines := strings.Split(text, "\n")
	applied, missed := 0, 0
	for _, e := range edits {
		find := strings.Split(strings.Trim(e.Find, "\n"), "\n")
		hits := findLines(lines, find, strings.TrimRight)
		if len(hits) == 0 {
			hits = findLines(lines, find, strings.Trim)
		}
		if len(hits) == 0 || (len(hits) > 1 && keepsAll(e.Replace, find)) {
			missed++
			continue
		}
		applied++
		for i := len(hits) - 1; i >= 0; i-- { // from the end, so the earlier places stay put
			at := hits[i]
			repl := reindented(strings.Split(e.Replace, "\n"), find, lines[at:at+len(find)])
			lines = append(lines[:at:at], append(repl, lines[at+len(find):]...)...)
		}
	}
	return strings.Join(lines, "\n"), applied, missed
}

// keepsAll says whether a replacement still has all of find's lines, in order:
// it only adds to them.
func keepsAll(replace string, find []string) bool {
	i := 0
	for _, l := range strings.Split(replace, "\n") {
		if i < len(find) && strings.TrimSpace(l) == strings.TrimSpace(find[i]) {
			i++
		}
	}
	return i == len(find)
}

// findLines is where find's lines stand in lines, compared after trim. Places
// don't overlap.
func findLines(lines, find []string, trim func(string, string) string) []int {
	var hits []int
	for i := 0; i+len(find) <= len(lines); i++ {
		same := true
		for j := range find {
			if trim(lines[i+j], " \t\r") != trim(find[j], " \t\r") {
				same = false
				break
			}
		}
		if same {
			hits = append(hits, i)
			i += len(find) - 1
		}
	}
	return hits
}

// indentOf is the indent of the first line with text.
func indentOf(lines []string) string {
	for _, l := range lines {
		if t := strings.TrimLeft(l, " \t"); t != "" {
			return l[:len(l)-len(t)]
		}
	}
	return ""
}

// reindented gives an edit's new lines the indents of the lines its FIND
// matched: a new line with the indent of a FIND line gets what that line really
// has, and the rest move with the first line.
func reindented(repl, find, got []string) []string {
	real := map[string]string{}
	for i, f := range find {
		if t := strings.TrimLeft(f, " \t"); t != "" {
			ind := f[:len(f)-len(t)]
			if _, seen := real[ind]; !seen {
				real[ind] = got[i][:len(got[i])-len(strings.TrimLeft(got[i], " \t"))]
			}
		}
	}
	out := moved(repl, indentOf(find), indentOf(got))
	for i, l := range repl {
		t := strings.TrimLeft(l, " \t")
		if to, ok := real[l[:len(l)-len(t)]]; ok && t != "" {
			out[i] = to + t
		}
	}
	return out
}

// moved reindents lines from one indent to another.
func moved(lines []string, from, to string) []string {
	if from == to {
		return lines
	}
	out := make([]string, len(lines))
	for i, l := range lines {
		switch {
		case strings.TrimSpace(l) == "":
			out[i] = l
		case strings.HasPrefix(l, from):
			out[i] = to + l[len(from):]
		default: // shallower than the first line: it moves by the same amount
			if add, ok := strings.CutPrefix(to, from); ok {
				out[i] = add + l
			} else if cut, ok := strings.CutPrefix(from, to); ok {
				out[i] = strings.TrimPrefix(l, cut)
			} else {
				out[i] = to + strings.TrimLeft(l, " \t")
			}
		}
	}
	return out
}

// similarSize says whether a script is big enough to stand for was, by the
// measure pickScript uses for two scripts of similar size.
func similarSize(script, was string) bool {
	return script != "" && 2*codeLines(script) >= codeLines(was)
}

// writtenOut says whether a reply's script is was written out again: about as
// long and mostly the same lines. A snippet isn't, nor is an edit in a code block.
func writtenOut(reply, script, was string) bool {
	if editMarkerRe.MatchString(reply) || !similarSize(script, was) {
		return false
	}
	has := map[string]bool{}
	for _, l := range strings.Split(script, "\n") {
		has[strings.TrimSpace(l)] = true
	}
	lines, same := 0, 0
	for _, l := range slices.Compact(slices.Sorted(slices.Values(strings.Split(was, "\n")))) {
		if t := strings.TrimSpace(l); t != "" {
			lines++
			if has[t] {
				same++
			}
		}
	}
	return 2*same >= lines
}

// hasBlockLike says whether text still has a whole code block about was's size.
func hasBlockLike(text, was string) bool {
	for _, b := range codeBlocks(text) {
		if b.Closed && similarSize(b.Body, was) {
			return true
		}
	}
	return false
}

// editedResult is what a combine's reply makes of the result so far, and whether
// it wrote the script out. A model that did is taken at its word (the check and
// the choice of the best round judge it) if it can have seen all of it; the rest
// of the result stays. Edits that would leave most of the script unchecked aren't
// used. Nothing usable leaves the result as it was.
func editedResult(base, reply string, kinds map[string]bool) (string, bool) {
	_, block, _ := pickBlock(kinds, base)
	was := dedent(block.Body)
	text, applied, missed := applyEdits(base, parseEdits(reply))
	if applied > 0 && hasBlockLike(text, was) {
		log.Printf("hydra: %d edits applied, %d found nothing to change", applied, missed)
		return text, false
	}
	if _, script, _ := pickScript(kinds, reply); len(base) <= earlierLimit && writtenOut(reply, script, was) {
		log.Printf("hydra: the model wrote the script out instead of editing it")
		return withScript(base, block, script), true
	}
	log.Printf("hydra: no usable edits (%d found nothing to change); the result stays as it was", missed)
	return base, false
}

// repairedScript is what a repair's reply makes of the script it was shown, or
// "" if nothing usable.
func repairedScript(script, reply string, kinds map[string]bool) string {
	text, applied, _ := applyEdits(script, parseEdits(reply))
	if applied > 0 && similarSize(text, script) {
		return text
	}
	if _, fixed, _ := pickScript(kinds, reply); writtenOut(reply, fixed, script) {
		return fixed
	}
	return ""
}

// mendScript repairs a script that crashed: the model gets the script and the
// error, Chimera applies its edits and runs the script again, up to hydraMends
// times. It returns the best the round got to and that one's check. A repair
// that leaves the script worse is taken back. Two tries in a row that get
// nowhere end it: worse, nothing that applies, or the same error on the same line.
func (t *TaskManager) mendScript(ctx context.Context, run *taskRun, req taskReq, round int, pass passResult, chk resultCheck) (passResult, resultCheck) {
	kinds := run.allKinds()
	cur, curChk := pass, chk
	stuck, made := 0, 0 // made counts the repairs that went in, for the card
	missed := false     // the last reply changed nothing
	var who [3]string   // device, owner and model of the repair that stuck
	defer func() {
		run.mu.Lock()
		run.rec.MendDevice, run.rec.MendOwner, run.rec.MendModel = who[0], who[1], who[2]
		run.mu.Unlock()
	}()
	for n := 1; n <= hydraMends && curChk.repairable() && stuck < 2; n++ {
		_, block, _ := pickBlock(kinds, cur.Text)
		script := dedent(block.Body)
		critique := curChk.Critique
		if missed {
			critique += "\n\nYour last reply changed nothing: copy each FIND from the script exactly as it stands."
		}
		reply, ev := t.askMend(ctx, run, req, round, script, critique)
		if ev.Type == "error" {
			log.Printf("hydra: round %d: repair %d didn't finish: %s", round, n, ev.Error)
		}
		if ev.Type != "done" {
			break
		}
		// It only saw the script, so that's all that changes, and the result
		// has to keep a script that can run.
		text := cur.Text
		if fixed := repairedScript(script, reply, kinds); fixed != "" {
			text = withScript(cur.Text, block, fixed)
		}
		if _, s, _ := pickScript(kinds, text); s == "" {
			text = cur.Text
		}
		if missed = text == cur.Text; missed {
			stuck++
			continue
		}
		made++
		next := passResult{Text: text, Model: pass.Model, Mend: made}
		c := t.checkResult(ctx, run, req, round, next)
		if ctx.Err() != nil && c.Outcome != "passed" { // stopped during the look, it had still passed
			break
		}
		switch {
		case c.grade() < curChk.grade():
			if c.Outcome != "" {
				t.undoMend(run)
			}
			stuck++
			continue
		case c.sameFault(curChk) && c.Line == curChk.Line:
			stuck++
		default:
			stuck = 0
		}
		cur, curChk = next, c
		t.showResult(run, text)
		t.save(run, false)
		run.mu.Lock()
		who = [3]string{run.rec.MendDevice, run.rec.MendOwner, run.rec.MendModel}
		run.mu.Unlock()
	}
	return cur, curChk
}

// askMend asks for one repair and returns the reply. The event says how it ended.
func (t *TaskManager) askMend(ctx context.Context, run *taskRun, req taskReq, round int, script, critique string) (string, genEvent) {
	run.mu.Lock()
	run.rec.Phase = "mending"
	run.rec.MendDevice, run.rec.MendOwner, run.rec.MendModel = "", "", ""
	run.mu.Unlock()
	run.push(true)
	t.save(run, false)
	msgs := []ChatMessage{{Role: "system", Content: hydraMendPrompt}, {Role: "user", Content: fmt.Sprintf(
		"The task:\n%s\n\nThe script:\n```python\n%s\n```\n\nWhat happened when it ran:\n%s", req.Goal, script, critique)}}
	mreq := submitReq{Private: req.Private, Messages: msgs, Prefer: "largest", TaskWork: true,
		NeedCtx: historyTokens(msgs) + synthRoom, Purpose: "Hydra: repairing the script (round " + itoaSmall(round) + ")"}
	var reply strings.Builder
	ev := t.app.runPrompt(ctx, mreq, func(ev genEvent) {
		switch ev.Type {
		case "assigned":
			run.mu.Lock()
			run.rec.MendDevice, run.rec.MendOwner, run.rec.MendModel = deviceLabelGo(ev), ev.Owner, ev.Model
			run.mu.Unlock()
			run.push(true)
		case "delta":
			reply.WriteString(ev.Content)
		case "replay", "requeued":
			reply.Reset()
			reply.WriteString(ev.Content)
		}
	}, nil)
	run.mu.Lock()
	run.rec.Tokens += ev.Tokens
	run.rec.Credits += ev.Credits
	run.mu.Unlock()
	return reply.String(), ev
}

// undoMend marks the latest check's repair as taken back.
func (t *TaskManager) undoMend(run *taskRun) {
	run.mu.Lock()
	if n := len(run.rec.Checks); n > 0 {
		run.rec.Checks[n-1].Undone = true
	}
	run.mu.Unlock()
	run.push(true)
}
