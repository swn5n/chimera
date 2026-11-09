package main

// Before an engine is asked about a message's files: turntables of its 3D models
// (turntable.go), then a line on what each picture shows (describe.go), the
// turntables' first frames included. Both are on by default, each with a switch on
// the composer for the message (the user's choice, Nov 9). This runs in the reply's
// own goroutine, so Stop ends it, and its progress is the reply's status line. What
// it finished is kept with the message (its files and what the model is told), also
// when it's stopped, so Write again and the chat's later turns have it.

import (
	"context"
	"fmt"
	"os"
	"path"
	"sort"
	"strings"
	"time"
)

type attachPrep struct {
	text       string // the message's words
	turntables bool
	describe   bool
	webGLB     bool
}

// wantsPrep says whether a message's files need any of it.
func wantsPrep(files []AttachedFile, p attachPrep) bool {
	for _, f := range files {
		if (p.turntables && turnable(f)) || (p.describe && f.Kind == "picture") || (p.webGLB && webable(f)) {
			return true
		}
	}
	return false
}

// prepAttachments makes the turntables and descriptions, saves them with the message
// and returns what the model is told about its files now ("" if nothing changed).
func (g *GenManager) prepAttachments(ctx context.Context, gen *generation, engine string, p attachPrep) string {
	a := g.app
	sess, err := a.sessions.Get(gen.sessionID)
	if err != nil {
		return ""
	}
	ui := -1
	for i, m := range sess.Messages {
		if m.GenID == gen.id && i > 0 && sess.Messages[i-1].Role == "user" {
			ui = i - 1
		}
	}
	if ui < 0 || sess.Messages[ui].AttachedIn == "" {
		return ""
	}
	user := sess.Messages[ui]
	folder := user.AttachedIn
	files := append([]AttachedFile(nil), user.Attached...)
	status := func(s string, f float64) { gen.emit(genEvent{Type: "status", Reason: s, Fraction: f}) }
	var notes []string
	var ex noteExtras
	if p.webGLB { // first: quick, and a model's copy is then no model of its own to turn
		var n []string
		files, n = a.addWebGLBs(ctx, folder, files, status)
		notes = append(notes, n...)
	}
	if p.turntables && ctx.Err() == nil {
		var n []string
		files, n = a.addTurntables(ctx, folder, files, status)
		notes = append(notes, n...)
	}
	if p.describe && ctx.Err() == nil {
		notes = append(notes, a.describePictures(ctx, engine, folder, files, &ex, status)...)
	}
	files, note := describeAttachmentsWith(folder, files, a.engines.TextBudget(engine), ex)
	if note == user.FilesNote && len(files) == len(user.Attached) {
		changed := false
		for i := range files {
			changed = changed || files[i] != user.Attached[i]
		}
		if !changed {
			if len(notes) > 0 {
				gen.emit(genEvent{Type: "note", Reason: strings.Join(notes, " ")})
			}
			return ""
		}
	}
	_, _ = a.sessions.Update(gen.sessionID, func(s *Session) {
		for i := range s.Messages {
			if s.Messages[i].GenID == gen.id && i > 0 && s.Messages[i-1].Role == "user" {
				s.Messages[i-1].Attached, s.Messages[i-1].FilesNote = files, note
			}
		}
	})
	gen.emit(genEvent{Type: "attached"})
	if len(notes) > 0 {
		gen.emit(genEvent{Type: "note", Reason: strings.Join(notes, " ")})
	}
	return note
}

// addTurntables renders the turntables of a message's 3D models (the first
// turnMaxModels, in the list's order) and adds their frames to its files.
func (a *App) addTurntables(ctx context.Context, folder string, files []AttachedFile, status func(string, float64)) ([]AttachedFile, []string) {
	var models []int
	for i, f := range files {
		if turnable(f) {
			models = append(models, i)
		}
	}
	if len(models) == 0 {
		return files, nil
	}
	sort.SliceStable(models, func(i, j int) bool { return natLess(files[models[i]].Path, files[models[j]].Path) })
	blender, why := a.turntableBlender()
	if why != "" {
		return files, []string{"No turntables: " + why + "."}
	}
	var notes []string
	if len(models) > turnMaxModels {
		notes = append(notes, fmt.Sprintf("Turntables were made of the first %d of its %d 3D models (one message gets up to %d).", turnMaxModels, len(models), turnMaxModels))
		models = models[:turnMaxModels]
	}
	select { // one turntable at a time on this computer
	case turnOne <- struct{}{}:
	default:
		status("Waiting for another chat's turntable to finish…", 0)
		select {
		case turnOne <- struct{}{}:
		case <-ctx.Done():
			return files, notes
		}
	}
	defer func() { <-turnOne }()
	also := make([]string, 0, len(files))
	at := map[string]int{}
	for i, f := range files {
		also = append(also, f.Path)
		at[strings.ToLower(f.Path)] = i
	}
	var failed []string
	for n, i := range models {
		m := files[i]
		if strings.EqualFold(path.Ext(m.Path), ".fbx") && !isBinaryFBX(folder, m.Path) {
			files[i].NoTurn = "Blender can't read a text (ASCII) FBX; save it as a binary FBX or as glTF"
			failed = append(failed, fmt.Sprintf("%s (%s)", m.Path, files[i].NoTurn))
			continue
		}
		name := path.Base(m.Path)
		res, err := renderTurntable(ctx, blender, a.turnCache(), folder, m.Path, also, defaultTurn(), func(p turnProgress) {
			part := 0.0
			if p.Total > 0 {
				part = float64(p.Done) / float64(p.Total)
			}
			status(turnStatus(name, p, n+1, len(models)), (float64(n)+part)/float64(len(models)))
		})
		if err != nil {
			if ctx.Err() != nil {
				break
			}
			files[i].NoTurn = err.Error()
			failed = append(failed, fmt.Sprintf("%s (%s)", m.Path, strings.TrimSuffix(err.Error(), ".")))
			continue
		}
		files[i].Turntable, files[i].NoTurn = res.Dir, ""
		for _, p := range append(append([]string(nil), res.Frames...), res.Poster) {
			var size int64
			if full, err := insideFolder(folder, p); err == nil {
				if st, err := os.Stat(full); err == nil {
					size = st.Size()
				}
			}
			af := AttachedFile{Path: p, Bytes: size, Kind: "picture", Made: "turntable", From: m.Path}
			if j, ok := at[strings.ToLower(p)]; ok {
				af.Name = files[j].Name
				files[j] = af // attached again (the folder had it from before): it's the turntable's frame
				continue
			}
			at[strings.ToLower(p)] = len(files)
			files = append(files, af)
		}
	}
	switch {
	case len(failed) == 1:
		notes = append(notes, "No turntable of "+failed[0]+".")
	case len(failed) > 1 && len(failed) <= 3:
		notes = append(notes, "No turntables of "+strings.Join(failed, ", ")+".")
	case len(failed) > 3:
		notes = append(notes, fmt.Sprintf("%d of the 3D models couldn't be turned: what the model was told says why for each.", len(failed)))
	}
	return files, notes
}

// addWebGLBs saves a message's OBJ, FBX, STL and PLY models as GLBs for web pages (the
// first webMaxModels, in the list's order) and adds them to its files.
func (a *App) addWebGLBs(ctx context.Context, folder string, files []AttachedFile, status func(string, float64)) ([]AttachedFile, []string) {
	var models []int
	for i, f := range files {
		if webable(f) {
			models = append(models, i)
		}
	}
	if len(models) == 0 {
		return files, nil
	}
	sort.SliceStable(models, func(i, j int) bool { return natLess(files[models[i]].Path, files[models[j]].Path) })
	blender, why := a.turntableBlender()
	if why != "" {
		return files, []string{"No GLBs for web pages: " + why + "."}
	}
	var notes []string
	if len(models) > webMaxModels {
		notes = append(notes, fmt.Sprintf("GLBs for web pages were made of the first %d of its %d models (one message gets up to %d).", webMaxModels, len(models), webMaxModels))
		models = models[:webMaxModels]
	}
	select { // one Blender at a time on this computer
	case turnOne <- struct{}{}:
	default:
		status("Waiting for another chat's Blender to finish…", 0)
		select {
		case turnOne <- struct{}{}:
		case <-ctx.Done():
			return files, notes
		}
	}
	defer func() { <-turnOne }()
	also := make([]string, 0, len(files))
	at := map[string]int{}
	for i, f := range files {
		also = append(also, f.Path)
		at[strings.ToLower(f.Path)] = i
	}
	var failed []string
	for n, i := range models {
		m := files[i]
		if strings.EqualFold(path.Ext(m.Path), ".fbx") && !isBinaryFBX(folder, m.Path) {
			files[i].NoGLB = "Blender can't read a text (ASCII) FBX; save it as a binary FBX or as glTF"
			failed = append(failed, fmt.Sprintf("%s (%s)", m.Path, files[i].NoGLB))
			continue
		}
		status(fmt.Sprintf("Saving %s as a GLB for web pages (%d of %d)…", path.Base(m.Path), n+1, len(models)), float64(n)/float64(len(models)))
		rel, _, err := webGLB(ctx, blender, a.turnCache(), folder, m.Path, also)
		if err != nil {
			if ctx.Err() != nil {
				break
			}
			files[i].NoGLB = err.Error()
			failed = append(failed, fmt.Sprintf("%s (%s)", m.Path, strings.TrimSuffix(err.Error(), ".")))
			continue
		}
		files[i].GLB, files[i].NoGLB = rel, ""
		var size int64
		if full, err := insideFolder(folder, rel); err == nil {
			if st, err := os.Stat(full); err == nil {
				size = st.Size()
			}
		}
		g := AttachedFile{Path: rel, Bytes: size, Kind: "3d", Made: "glb", From: m.Path}
		if j, ok := at[strings.ToLower(rel)]; ok {
			g.Name = files[j].Name
			files[j] = g // attached again (the folder had it from before): it's the copy
			continue
		}
		at[strings.ToLower(rel)] = len(files)
		files = append(files, g)
	}
	switch {
	case len(failed) == 1:
		notes = append(notes, "No GLB for web pages of "+failed[0]+".")
	case len(failed) > 1 && len(failed) <= 3:
		notes = append(notes, "No GLBs for web pages of "+strings.Join(failed, ", ")+".")
	case len(failed) > 3:
		notes = append(notes, fmt.Sprintf("%d of the models couldn't be saved as GLBs for web pages: what the model was told says why for each.", len(failed)))
	}
	return files, notes
}

func isBinaryFBX(folder, rel string) bool {
	full, err := insideFolder(folder, rel)
	if err != nil {
		return false
	}
	return strings.HasPrefix(string(readHead(full, 32)), "Kaydara FBX Binary")
}

// describePictures has the vision model write what each picture shows (one per line
// of the list: a numbered run's first frame), into files[i].Shows.
func (a *App) describePictures(ctx context.Context, engine, folder string, files []AttachedFile, ex *noteExtras, status func(string, float64)) []string {
	facts := attachFacts(folder, files)
	lines := attachLines(files, facts, attachOrder(files))
	if len(lines) > attachListMax {
		lines = lines[:attachListMax] // the list stops there
	}
	var pics []int
	for _, l := range lines {
		f := files[l.idx]
		if facts[l.idx].Kind != "picture" || (f.Made == "turntable" && !l.seq) || f.Shows != "" {
			continue
		}
		pics = append(pics, l.idx)
	}
	if len(pics) == 0 {
		return nil
	}
	m, ok := a.describeModel()
	if !ok {
		return nil // no vision model here: the note says only facts come
	}
	ex.DescribedBy = m.Name
	// Pictures this model has looked at before (by their bytes) aren't looked at again.
	cache := seenCacheFor(a.dataDir)
	sums := map[int]string{}
	var fresh []int
	for _, i := range pics {
		if full, err := insideFolder(folder, files[i].Path); err == nil {
			sums[i] = fileSum(full)
		}
		if line, ok := cache.get(m.Name, sums[i]); ok && sums[i] != "" {
			files[i].Shows = line
			continue
		}
		fresh = append(fresh, i)
	}
	if pics = fresh; len(pics) == 0 {
		return nil
	}
	defer cache.save()
	client := a.ollama.Client()
	loaded := false
	pctx, pcancel := context.WithTimeout(ctx, 5*time.Second)
	if ps, err := client.PS(pctx); err == nil {
		for _, x := range ps {
			loaded = loaded || normModel(x.Name) == normModel(m.Name)
		}
	}
	pcancel()
	if a.engines.Running(engine) && !loaded {
		free, known := freeMemoryNow()
		if ok, why := roomBeside(m.SizeBytes, free, known); !ok {
			ex.NotDescribed = fmt.Sprintf("%s was running, without room beside it for %s", a.engines.Name(engine), m.Name)
			return []string{fmt.Sprintf("Pictures not described: %s was running and there wasn't room for %s beside it (%s).", a.engines.Name(engine), m.Name, why)}
		}
	}
	dctx, cancel := context.WithTimeout(ctx, describeTime)
	defer cancel()
	todo := min(len(pics), describeMax)
	var unread, wrong, late int
	for n, i := range pics[:todo] {
		if dctx.Err() != nil {
			late = todo - n
			break
		}
		status(fmt.Sprintf("Looking at your pictures with %s: %d of %d…", m.Name, n+1, todo), float64(n)/float64(todo))
		full, err := insideFolder(folder, files[i].Path)
		if err != nil {
			unread++
			continue
		}
		data, filled, tone, err := visionCopy(dctx, full, facts[i])
		if err != nil {
			unread++
			continue
		}
		actx, acancel := context.WithTimeout(dctx, describeEach)
		ans, err := askDescribe(actx, client, m.Name, data, filled)
		acancel()
		if err != nil {
			if dctx.Err() != nil {
				late = todo - n
				break
			}
			wrong++
			continue
		}
		files[i].Shows = showsLine(ans, tone)
		if sums[i] != "" {
			cache.put(m.Name, sums[i], files[i].Shows)
		}
	}
	// It goes again unless it was loaded before or something else is using it now.
	if !loaded && !a.ollamaBusy(m.Name) {
		uctx, ucancel := context.WithTimeout(context.Background(), 10*time.Second)
		_ = client.Unload(uctx, m.Name)
		ucancel()
	}
	var why []string
	if over := len(pics) - todo; over > 0 {
		why = append(why, fmt.Sprintf("%s over the %d a message gets looked at", fmtNum(over), describeMax))
	}
	if late > 0 {
		why = append(why, fmt.Sprintf("%s left when the %d minutes for looking ran out", fmtNum(late), int(describeTime.Minutes())))
	}
	if unread > 0 {
		why = append(why, fmt.Sprintf("%s that can't be read here", fmtNum(unread)))
	}
	if wrong > 0 {
		why = append(why, fmt.Sprintf("%s %s couldn't answer about", fmtNum(wrong), m.Name))
	}
	ex.NotDescribed = strings.Join(why, "; ")
	if ctx.Err() == nil && (late > 0 || wrong > 0) {
		return []string{fmt.Sprintf("Some pictures weren't described: %s.", ex.NotDescribed)}
	}
	return nil
}
