package main

// The network's shared library: known-good snippets, Blender scripts and
// lessons, kept on the hub. It grows from 4 and 5 star answers ("distilling
// ourselves"): the biggest model online turns the answer plus what the person
// said worked into a reusable entry. When devices sit idle, the hub has them
// review entries, and the host's own computers (if they opt in) test-run
// scripts. Anything that fails or looks like spam waits for the host to review.

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strings"
	"time"
	"unicode/utf8"
)

type LibCheck struct {
	At      time.Time `json:"at"`
	Kind    string    `json:"kind"` // review, run
	Device  string    `json:"device"`
	Verdict string    `json:"verdict"` // pass, fail, spam
	Detail  string    `json:"detail"`
}

type LibSource struct {
	Owner  string `json:"owner"`
	Device string `json:"device"`
	Model  string `json:"model"`
	Note   string `json:"note"`
	From   string `json:"from"` // rating, manual
	Rating int    `json:"rating,omitempty"`
}

type LibEntry struct {
	ID       string     `json:"id"`
	Kind     string     `json:"kind"` // snippet, blender, lesson, prompt
	Title    string     `json:"title"`
	Summary  string     `json:"summary"`
	Content  string     `json:"content,omitempty"`
	Language string     `json:"language,omitempty"`
	Tags     []string   `json:"tags"`
	Status   string     `json:"status"` // unverified, verified, flagged
	Flag     string     `json:"flag,omitempty"`
	Waiting  string     `json:"waiting,omitempty"` // what it's waiting on
	Source   LibSource  `json:"source"`
	Checks   []LibCheck `json:"checks"`
	Created  time.Time  `json:"created"`
	Updated  time.Time  `json:"updated"`
	Uses     int        `json:"uses"`
	Votes    int        `json:"votes"`           // 4 and 5 star ratings that led here
	Score    float64    `json:"score,omitempty"` // search relevance, 0..1
	// Plugins (kind "plugin"): which one, and every star rating its results got.
	Plugin  string `json:"plugin,omitempty"`
	Version string `json:"version,omitempty"`
	Stars   int    `json:"stars,omitempty"` // sum of the ratings
	Rated   int    `json:"rated,omitempty"` // how many ratings
}

type Feedback struct {
	ID       string    `json:"id"`
	At       time.Time `json:"at"`
	Owner    string    `json:"owner"`
	Device   string    `json:"device"`
	Rating   int       `json:"rating"`
	Note     string    `json:"note"`
	Prompt   string    `json:"prompt"`
	Response string    `json:"response"`
	Model    string    `json:"model"`
	Kind     string    `json:"kind"`
	Status   string    `json:"status"` // queued, curated, skipped, failed
	EntryID  string    `json:"entry_id,omitempty"`
}

type libJob struct {
	ID         string    `json:"id"`
	Kind       string    `json:"kind"` // curate, review, run
	FeedbackID string    `json:"feedback_id,omitempty"`
	EntryID    string    `json:"entry_id,omitempty"`
	Attempts   int       `json:"attempts"`
	NextTry    time.Time `json:"next_try"`
	StepID     string    `json:"step_id,omitempty"`
}

type LibraryStats struct {
	Total      int `json:"total"`
	Verified   int `json:"verified"`
	Unverified int `json:"unverified"`
	Flagged    int `json:"flagged"`
	Jobs       int `json:"jobs"`
	Feedback   int `json:"feedback"`
}

type library struct {
	path     string
	Entries  map[string]*LibEntry `json:"entries"`
	Feedback []*Feedback          `json:"feedback"`
	Jobs     []*libJob            `json:"jobs"`
	// Finished plugin steps that can still be rated, once each, by whoever asked for them.
	PluginRuns map[string]*pluginRun `json:"plugin_runs,omitempty"`
	dirty      bool
	lastIdle   time.Time
}

func loadLibrary(path string) *library {
	l := &library{path: path, Entries: map[string]*LibEntry{}}
	if b, err := os.ReadFile(path); err == nil {
		_ = json.Unmarshal(b, l)
	}
	if l.Entries == nil {
		l.Entries = map[string]*LibEntry{}
	}
	if l.PluginRuns == nil {
		l.PluginRuns = map[string]*pluginRun{}
	}
	for _, j := range l.Jobs { // steps don't survive a restart
		j.StepID = ""
	}
	return l
}

func (l *library) save() {
	b, err := json.MarshalIndent(l, "", "  ")
	if err != nil {
		return
	}
	if err := writeFileAtomic(l.path, b); err != nil {
		log.Printf("library: saving: %v", err)
		return
	}
	l.dirty = false
}

func (l *library) stats() LibraryStats {
	s := LibraryStats{Total: len(l.Entries), Jobs: len(l.Jobs), Feedback: len(l.Feedback)}
	for _, e := range l.Entries {
		switch e.Status {
		case "verified":
			s.Verified++
		case "flagged":
			s.Flagged++
		default:
			s.Unverified++
		}
	}
	return s
}

// ---------- search ----------

var wordRe = regexp.MustCompile(`[a-z0-9][a-z0-9_+#.-]*`)

var stopWords = map[string]bool{"the": true, "and": true, "for": true, "with": true, "that": true, "this": true, "from": true,
	"into": true, "your": true, "you": true, "are": true, "how": true, "what": true, "can": true, "use": true, "using": true,
	"make": true, "write": true, "create": true, "please": true, "some": true, "about": true, "have": true, "will": true, "should": true,
	"in": true, "of": true, "to": true, "on": true, "an": true, "is": true, "it": true, "at": true, "by": true, "or": true, "as": true,
	"be": true, "do": true, "if": true, "my": true, "me": true, "we": true, "so": true, "up": true, "all": true, "one": true, "new": true}

func tokenize(s string) []string {
	seen := map[string]bool{}
	var out []string
	for _, w := range wordRe.FindAllString(strings.ToLower(s), -1) {
		w = strings.Trim(w, ".-")
		if len(w) < 2 || stopWords[w] || seen[w] {
			continue
		}
		seen[w] = true
		out = append(out, w)
	}
	return out
}

func (l *library) search(q, kind, status string, admin bool, limit int) []LibEntry {
	terms := tokenize(q)
	var out []LibEntry
	for _, e := range l.Entries {
		if e.Status == "flagged" && !admin && status != "flagged" {
			continue
		}
		if kind != "" && e.Kind != kind {
			continue
		}
		if status != "" && e.Status != status {
			continue
		}
		c := *e
		if len(terms) > 0 {
			title, summary, content := strings.ToLower(e.Title), strings.ToLower(e.Summary), strings.ToLower(e.Content)
			tags := strings.ToLower(strings.Join(e.Tags, " "))
			score := 0.0
			for _, t := range terms {
				switch {
				case strings.Contains(title, t):
					score += 3
				case strings.Contains(tags, t):
					score += 2.5
				case strings.Contains(summary, t):
					score += 1.5
				case strings.Contains(content, t):
					score += 0.5
				}
			}
			if score == 0 {
				continue
			}
			c.Score = score / (3 * float64(len(terms)))
			if e.Status == "verified" {
				c.Score *= 1.15
			}
			if e.Votes > 1 { // several people found it useful
				c.Score *= 1 + 0.04*float64(min(e.Votes-1, 5))
			}
		}
		out = append(out, c)
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Score != out[j].Score {
			return out[i].Score > out[j].Score
		}
		return out[i].Updated.After(out[j].Updated)
	})
	if limit > 0 && len(out) > limit {
		out = out[:limit]
	}
	return out
}

// ---------- routes ----------

func (h *Hub) libraryRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /v1/library", h.auth(h.handleLibList))
	mux.HandleFunc("GET /v1/library/{id}", h.auth(h.handleLibGet))
	mux.HandleFunc("POST /v1/library", h.auth(h.handleLibAdd))
	mux.HandleFunc("POST /v1/library/{id}/review", h.auth(h.handleLibReview))
	mux.HandleFunc("POST /v1/library/{id}/used", h.auth(h.handleLibUsed))
	mux.HandleFunc("POST /v1/feedback", h.auth(h.handleFeedback))
	mux.HandleFunc("GET /v1/library/export", h.auth(h.handleLibExport))
}

// handleLibExport gives the host every rated reply as JSON lines: the
// network's own best answers, ready to fine-tune a small model on later
// ("distilling ourselves").
func (h *Hub) handleLibExport(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	h.mu.Lock()
	if !h.isAdminLocked(d) {
		h.mu.Unlock()
		writeErr(w, 403, "Only the network's host can export the ratings.")
		return
	}
	rows := make([]Feedback, 0, len(h.lib.Feedback))
	for _, f := range h.lib.Feedback {
		rows = append(rows, *f)
	}
	h.mu.Unlock()
	w.Header().Set("Content-Type", "application/x-ndjson")
	enc := json.NewEncoder(w)
	for _, f := range rows {
		_ = enc.Encode(map[string]any{"at": f.At, "rating": f.Rating, "what_worked": f.Note, "prompt": f.Prompt,
			"response": f.Response, "model": f.Model, "kind": f.Kind, "owner": f.Owner})
	}
}

func (h *Hub) handleLibList(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	q := r.URL.Query()
	limit := clampInt(atoiDefault(q.Get("limit"), 50), 1, 200)
	h.mu.Lock()
	admin := h.isAdminLocked(d)
	res := h.lib.search(q.Get("q"), q.Get("kind"), q.Get("status"), admin, limit)
	h.mu.Unlock()
	for i := range res {
		if q.Get("full") != "1" && len(res[i].Content) > 400 {
			res[i].Content = res[i].Content[:400] + "…"
		}
		if !admin {
			res[i].Checks = publicChecks(res[i].Checks)
		}
	}
	if res == nil {
		res = []LibEntry{}
	}
	writeJSON(w, 200, map[string]any{"entries": res, "admin": admin})
}

func (h *Hub) handleLibGet(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	h.mu.Lock()
	defer h.mu.Unlock()
	e := h.lib.Entries[r.PathValue("id")]
	if e == nil || (e.Status == "flagged" && !h.isAdminLocked(d)) {
		writeErr(w, 404, "no such entry")
		return
	}
	out := *e
	if !h.isAdminLocked(d) {
		out.Checks = publicChecks(e.Checks)
	}
	writeJSON(w, 200, out)
}

// publicChecks hides test-run output from everyone but the host: it came
// from running a script on the host's computer.
func publicChecks(in []LibCheck) []LibCheck {
	out := make([]LibCheck, len(in))
	for i, c := range in {
		if c.Kind == "run" {
			if line, _, ok := strings.Cut(c.Detail, "\n"); ok {
				c.Detail = line
			}
		}
		out[i] = c
	}
	return out
}

type libAddReq struct {
	Kind     string   `json:"kind"`
	Title    string   `json:"title"`
	Summary  string   `json:"summary"`
	Content  string   `json:"content"`
	Language string   `json:"language"`
	Tags     []string `json:"tags"`
	Note     string   `json:"note"`
}

func (h *Hub) handleLibAdd(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	var req libAddReq
	if err := readJSON(r, &req, 2<<20); err != nil {
		writeErr(w, 400, "bad request")
		return
	}
	if strings.TrimSpace(req.Title) == "" || strings.TrimSpace(req.Content) == "" {
		writeErr(w, 400, "A title and some content are required.")
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	e := h.newEntryLocked(req, LibSource{Owner: d.Owner, Device: d.Name, From: "manual", Note: req.Note})
	writeJSON(w, 200, e)
}

func normalizeKind(kind, language, content string) string {
	kind = strings.ToLower(strings.TrimSpace(kind))
	switch kind {
	case "snippet", "blender", "lesson", "prompt":
	case "plugin":
		kind = "lesson" // plugin entries are made by the hub from installed plugins, never added by hand
	case "code", "script":
		kind = "snippet"
	default:
		kind = "lesson"
	}
	if kind == "snippet" && strings.Contains(content, "import bpy") {
		kind = "blender"
	}
	return kind
}

func (h *Hub) newEntryLocked(req libAddReq, src LibSource) *LibEntry {
	now := time.Now()
	lang := strings.ToLower(strings.TrimSpace(req.Language))
	kind := normalizeKind(req.Kind, lang, req.Content)
	if kind == "blender" {
		lang = "python"
	}
	var tags []string
	for _, t := range req.Tags {
		if t = strings.ToLower(strings.TrimSpace(t)); t != "" && len(tags) < 8 {
			tags = append(tags, t)
		}
	}
	if tags == nil {
		tags = []string{}
	}
	e := &LibEntry{ID: randomID(6), Kind: kind, Title: strings.TrimSpace(req.Title), Summary: strings.TrimSpace(req.Summary),
		Content: strings.TrimSpace(req.Content), Language: lang, Tags: tags, Status: "unverified",
		Source: src, Checks: []LibCheck{}, Created: now, Updated: now}
	h.lib.Entries[e.ID] = e
	h.lib.dirty = true
	h.queueJobLocked(&libJob{Kind: "review", EntryID: e.ID})
	log.Printf("library: new %s entry %q", e.Kind, e.Title)
	return e
}

func (h *Hub) handleLibReview(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	var req struct {
		Action string `json:"action"` // approve, flag, delete, recheck
		Note   string `json:"note"`
	}
	_ = readJSON(r, &req, 1<<16)
	h.mu.Lock()
	defer h.mu.Unlock()
	if !h.isAdminLocked(d) {
		writeErr(w, 403, "Only the network's host can review the library.")
		return
	}
	e := h.lib.Entries[r.PathValue("id")]
	if e == nil {
		writeErr(w, 404, "no such entry")
		return
	}
	now := time.Now()
	switch req.Action {
	case "approve":
		e.Status, e.Flag, e.Waiting = "verified", "", ""
		e.Checks = append(e.Checks, LibCheck{At: now, Kind: "review", Device: d.Owner + " (host)", Verdict: "pass", Detail: firstNonEmpty(req.Note, "Approved by the host.")})
	case "flag":
		e.Status, e.Flag = "flagged", firstNonEmpty(req.Note, "Flagged by the host.")
	case "delete":
		delete(h.lib.Entries, e.ID)
		h.lib.dirty = true
		writeJSON(w, 200, map[string]bool{"ok": true})
		return
	case "recheck":
		e.Status, e.Flag, e.Waiting = "unverified", "", ""
		if e.Kind == "plugin" { // a plugin proves itself by running for someone, not by review
			e.Waiting = "its next run for someone"
		} else {
			h.queueJobLocked(&libJob{Kind: "review", EntryID: e.ID})
		}
	default:
		writeErr(w, 400, "unknown action")
		return
	}
	e.Updated = now
	h.lib.dirty = true
	writeJSON(w, 200, e)
}

func (h *Hub) handleLibUsed(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if e := h.lib.Entries[r.PathValue("id")]; e != nil {
		e.Uses++
		h.lib.dirty = true
	}
	writeJSON(w, 200, map[string]bool{"ok": true})
}

type feedbackReq struct {
	Rating   int    `json:"rating"`
	Note     string `json:"note"`
	Prompt   string `json:"prompt"`
	Response string `json:"response"`
	Model    string `json:"model"`
	Kind     string `json:"kind"`
	Plugin   string `json:"plugin,omitempty"`  // the reply came from this plugin: rate the plugin
	StepID   string `json:"step_id,omitempty"` // the plugin step it rates (one rating per step)
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	for n > 0 && !utf8.RuneStart(s[n]) { // don't cut through a multi-byte character
		n--
	}
	return s[:n] + "\n…(cut)"
}

func (h *Hub) handleFeedback(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	var req feedbackReq
	if err := readJSON(r, &req, 2<<20); err != nil || req.Rating < 1 || req.Rating > 5 {
		writeErr(w, 400, "rating must be 1 to 5")
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	fb := &Feedback{ID: randomID(6), At: time.Now(), Owner: d.Owner, Device: d.Name, Rating: req.Rating,
		Note: truncate(strings.TrimSpace(req.Note), 2000), Prompt: truncate(req.Prompt, 8000), Response: truncate(req.Response, 12000),
		Model: req.Model, Kind: req.Kind, Status: "skipped"}
	queued := false
	if req.Plugin != "" {
		// A plugin's result: the stars go to the plugin, which is how the network
		// picks between plugins that could all do a job. Nothing to curate.
		// Only a run this person asked for counts, once: ratings decide which plugin the network
		// picks, so they can't be posted for plugins someone never used.
		fb.Status = "plugin_ignored"
		if run := h.lib.PluginRuns[req.StepID]; req.StepID != "" && run != nil && run.Plugin == req.Plugin && sameOwner(run.Owner, d.Owner) {
			delete(h.lib.PluginRuns, req.StepID)
			fb.Status = "plugin"
			fb.EntryID = h.ratePluginLocked(req.Plugin, req.Rating)
			if req.Rating >= 4 && run.Worker != "" && !sameOwner(run.Worker, d.Owner) {
				// Someone else found the Head's result good: its owner earns a star bonus, minted by the network.
				h.st.Balances[ownerKey(run.Worker)] += pluginStarBonus
				h.addTxLocked(LedgerTx{At: time.Now(), From: "network", To: run.Worker, Amount: pluginStarBonus,
					Note: fmt.Sprintf("Head star bonus: %s rated %d★", req.Plugin, req.Rating), StepID: req.StepID})
			}
		}
	} else if req.Rating >= 4 && strings.TrimSpace(req.Response) != "" {
		fb.Status = "queued"
		h.queueJobLocked(&libJob{Kind: "curate", FeedbackID: fb.ID})
		queued = true
	}
	h.lib.Feedback = append(h.lib.Feedback, fb)
	if len(h.lib.Feedback) > 500 {
		h.lib.Feedback = h.lib.Feedback[len(h.lib.Feedback)-500:]
	}
	h.lib.dirty = true
	writeJSON(w, 200, map[string]any{"ok": true, "queued": queued})
}

// ---------- jobs ----------

func (h *Hub) queueJobLocked(j *libJob) {
	j.ID = randomID(5)
	j.NextTry = time.Now()
	h.lib.Jobs = append(h.lib.Jobs, j)
	h.lib.dirty = true
}

func (h *Hub) dropJobLocked(j *libJob) {
	out := h.lib.Jobs[:0]
	for _, x := range h.lib.Jobs {
		if x != j {
			out = append(out, x)
		}
	}
	h.lib.Jobs = out
	h.lib.dirty = true
}

func (h *Hub) retryJobLocked(j *libJob, why string) {
	j.StepID = ""
	j.Attempts++
	if j.Attempts >= 3 {
		log.Printf("library: giving up on %s job: %s", j.Kind, why)
		if j.Kind == "curate" {
			if fb := h.feedbackLocked(j.FeedbackID); fb != nil {
				fb.Status = "failed"
			}
		}
		if e := h.lib.Entries[j.EntryID]; e != nil && j.Kind != "curate" {
			e.Waiting = ""
			e.Status, e.Flag = "flagged", "Couldn't check this automatically: "+why
			e.Updated = time.Now()
		}
		h.dropJobLocked(j)
		return
	}
	j.NextTry = time.Now().Add(time.Duration(j.Attempts) * 2 * time.Minute)
	h.lib.dirty = true
}

func (h *Hub) feedbackLocked(id string) *Feedback {
	for _, f := range h.lib.Feedback {
		if f.ID == id {
			return f
		}
	}
	return nil
}

var riskyScript = regexp.MustCompile(`(?i)(os\.remove|os\.unlink|os\.rmdir|os\.removedirs|shutil\.rmtree|shutil\.move|subprocess|os\.system|os\.popen|os\.exec|\bsocket\b|urllib|requests\.|http\.client|ftplib|smtplib|\beval\(|\bexec\(|__import__|ctypes|keyring|getpass|open\([^)]*['"](w|a|wb|ab|r\+|w\+)['"])`)

func runnableKind(e *LibEntry) string {
	if e.Kind == "blender" {
		return "run_blender"
	}
	if e.Kind == "snippet" && (e.Language == "python" || e.Language == "py") {
		return "run_python"
	}
	return ""
}

// libraryTickLocked starts library jobs when devices are free, and, when a
// lending device has been idle long enough, starts re-checking entries.
func (h *Hub) libraryTickLocked(now time.Time) {
	if h.lib.dirty {
		h.lib.save()
	}
	active := 0
	for _, j := range h.lib.Jobs {
		if j.StepID != "" {
			if st := h.steps[j.StepID]; st != nil && !isTerminal(st.Status) {
				active++
				continue
			}
			j.StepID = "" // finished without calling back (shouldn't happen)
		}
	}
	for _, j := range append([]*libJob(nil), h.lib.Jobs...) {
		if active >= 2 || j.StepID != "" || now.Before(j.NextTry) {
			continue
		}
		st := h.jobStepLocked(j)
		if st == nil {
			continue
		}
		if h.submitInternalLocked(st) {
			j.StepID = st.ID
			active++
		} else if j.Kind == "run" {
			// Nobody can test-run it right now. The entry keeps waiting, and the
			// idle check queues it again once a computer that can is lending.
			h.dropJobLocked(j)
		} else {
			j.NextTry = now.Add(time.Minute)
		}
	}
	// Idle verification: re-check entries when someone has been idle a while.
	if len(h.lib.Jobs) > 0 || now.Sub(h.lib.lastIdle) < time.Minute {
		return
	}
	idle := false
	for _, d := range h.st.Devices {
		if h.readyLocked(d) && !d.lastWork.IsZero() && now.Sub(d.lastWork) >= time.Duration(h.st.VerifyIdleMin)*time.Minute {
			idle = true
			break
		}
	}
	if !idle {
		return
	}
	h.lib.lastIdle = now
	canRun := map[string]bool{
		"run_python":  h.possibleLocked(&hubStep{Kind: "run_python"}),
		"run_blender": h.possibleLocked(&hubStep{Kind: "run_blender"}),
	}
	var pick *LibEntry
	for _, e := range h.lib.Entries {
		if e.Kind == "plugin" { // checked by running them for people, not by review
			continue
		}
		due := false
		switch e.Status {
		case "unverified":
			if strings.HasPrefix(e.Waiting, "a computer") {
				due = canRun[runnableKind(e)]
			} else {
				due = e.Waiting == ""
			}
		case "verified":
			last := e.Updated
			for _, c := range e.Checks {
				if c.At.After(last) {
					last = c.At
				}
			}
			due = canRun[runnableKind(e)] && now.Sub(last) > 7*24*time.Hour
		}
		if due && (pick == nil || e.Updated.Before(pick.Updated)) {
			pick = e
		}
	}
	if pick != nil {
		kind := "review"
		if pick.Status == "verified" || strings.HasPrefix(pick.Waiting, "a computer") {
			kind = "run"
		}
		h.queueJobLocked(&libJob{Kind: kind, EntryID: pick.ID})
	}
}

func (h *Hub) jobStepLocked(j *libJob) *hubStep {
	switch j.Kind {
	case "curate":
		fb := h.feedbackLocked(j.FeedbackID)
		if fb == nil {
			h.dropJobLocked(j)
			return nil
		}
		payload, _ := json.MarshalIndent(map[string]any{
			"request": fb.Prompt, "answer": fb.Response, "rating": fb.Rating,
			"what_worked": fb.Note, "model": fb.Model, "task_kind": fb.Kind,
		}, "", "  ")
		return &hubStep{Prefer: "largest", Format: json.RawMessage(`"json"`), Purpose: "Library: saving what worked from a " + strings.Repeat("★", fb.Rating) + " answer",
			NeedCtx:  estimateTokens(string(payload)) + 1500,
			Messages: []ChatMessage{{Role: "system", Content: curatorPrompt}, {Role: "user", Content: string(payload)}},
			onDone:   func(h *Hub, st *hubStep) { h.curateDoneLocked(j, st) }}
	case "review":
		e := h.lib.Entries[j.EntryID]
		if e == nil {
			h.dropJobLocked(j)
			return nil
		}
		payload, _ := json.MarshalIndent(map[string]any{"kind": e.Kind, "title": e.Title, "summary": e.Summary,
			"language": e.Language, "tags": e.Tags, "content": e.Content, "submitter_note": e.Source.Note}, "", "  ")
		// The verdict decides what the whole network treats as trusted, so only
		// the hosting computer's own model may make it, never a member's.
		return &hubStep{Prefer: "largest", HostOnly: true, Format: json.RawMessage(`"json"`), Purpose: "Library: checking “" + e.Title + "”",
			NeedCtx:  estimateTokens(string(payload)) + 1000,
			Messages: []ChatMessage{{Role: "system", Content: reviewerPrompt}, {Role: "user", Content: string(payload)}},
			onDone:   func(h *Hub, st *hubStep) { h.reviewDoneLocked(j, st) }}
	case "run":
		e := h.lib.Entries[j.EntryID]
		if e == nil {
			h.dropJobLocked(j)
			return nil
		}
		kind := runnableKind(e)
		if kind == "" {
			h.dropJobLocked(j)
			return nil
		}
		return &hubStep{Kind: kind, Script: e.Content, Purpose: "Library: test-running “" + e.Title + "”",
			Messages: []ChatMessage{{Role: "user", Content: "test run"}},
			onDone:   func(h *Hub, st *hubStep) { h.runDoneLocked(j, st) }}
	}
	h.dropJobLocked(j)
	return nil
}

func estimateTokens(s string) int { return len(s)/3 + 64 }

// extractJSON finds the first JSON object in a model's reply.
func extractJSON(s string, v any) bool {
	s = strings.TrimSpace(s)
	if json.Unmarshal([]byte(s), v) == nil {
		return true
	}
	start := strings.Index(s, "{")
	end := strings.LastIndex(s, "}")
	if start < 0 || end <= start {
		return false
	}
	return json.Unmarshal([]byte(s[start:end+1]), v) == nil
}

func (h *Hub) deviceName(id string) string {
	if d := h.st.Devices[id]; d != nil {
		return d.Name
	}
	return "a device"
}

func (h *Hub) curateDoneLocked(j *libJob, st *hubStep) {
	if st.Status != "done" {
		h.retryJobLocked(j, firstNonEmpty(st.Err, st.Status))
		return
	}
	var out struct {
		Kind     string   `json:"kind"`
		Title    string   `json:"title"`
		Summary  string   `json:"summary"`
		Language string   `json:"language"`
		Tags     []string `json:"tags"`
		Content  string   `json:"content"`
		Skip     bool     `json:"skip"`
	}
	if !extractJSON(st.Text.String(), &out) {
		h.retryJobLocked(j, "the model's reply wasn't valid JSON")
		return
	}
	fb := h.feedbackLocked(j.FeedbackID)
	h.dropJobLocked(j)
	if fb == nil {
		return
	}
	if out.Skip || strings.TrimSpace(out.Title) == "" || strings.TrimSpace(out.Content) == "" {
		fb.Status = "skipped"
		return
	}
	// The same thing rated well again: count the vote instead of adding a copy.
	if dup := h.findDuplicateLocked(out.Kind, out.Title, out.Content); dup != nil {
		dup.Votes++
		dup.Updated = time.Now()
		detail := fmt.Sprintf("%d stars", fb.Rating)
		if n := strings.TrimSpace(fb.Note); n != "" {
			detail += ": " + n
		}
		dup.Checks = append(dup.Checks, LibCheck{At: time.Now(), Kind: "vote", Device: fb.Owner, Verdict: "pass", Detail: detail})
		h.lib.dirty = true
		fb.Status, fb.EntryID = "curated", dup.ID
		return
	}
	e := h.newEntryLocked(libAddReq{Kind: out.Kind, Title: out.Title, Summary: out.Summary, Content: out.Content, Language: out.Language, Tags: out.Tags},
		LibSource{Owner: fb.Owner, Device: fb.Device, Model: fb.Model, Note: fb.Note, From: "rating", Rating: fb.Rating})
	fb.Status, fb.EntryID = "curated", e.ID
	e.Votes = 1
	e.Checks = append(e.Checks, LibCheck{At: time.Now(), Kind: "curate", Device: h.deviceName(st.Assigned) + " with " + st.RunModel, Verdict: "pass",
		Detail: firstNonEmpty(strings.TrimSpace(fb.Note), "From a "+strings.Repeat("★", fb.Rating)+" reply")})
}

// findDuplicateLocked finds an entry of the same kind and title whose content
// is the same apart from whitespace.
func (h *Hub) findDuplicateLocked(kind, title, content string) *LibEntry {
	norm := func(s string) string { return strings.Join(strings.Fields(strings.ToLower(s)), " ") }
	kind = normalizeKind(kind, "", content)
	for _, e := range h.lib.Entries {
		if e.Kind == kind && norm(e.Title) == norm(title) && norm(e.Content) == norm(content) {
			return e
		}
	}
	return nil
}

func (h *Hub) reviewDoneLocked(j *libJob, st *hubStep) {
	e := h.lib.Entries[j.EntryID]
	if e == nil {
		h.dropJobLocked(j)
		return
	}
	if st.Status != "done" {
		h.retryJobLocked(j, firstNonEmpty(st.Err, st.Status))
		return
	}
	var out struct {
		Verdict string `json:"verdict"`
		Reasons string `json:"reasons"`
	}
	if !extractJSON(st.Text.String(), &out) {
		h.retryJobLocked(j, "the reviewer's reply wasn't valid JSON")
		return
	}
	h.dropJobLocked(j)
	verdict := strings.ToLower(strings.TrimSpace(out.Verdict))
	if verdict != "pass" && verdict != "spam" {
		verdict = "fail"
	}
	now := time.Now()
	e.Checks = append(e.Checks, LibCheck{At: now, Kind: "review", Device: h.deviceName(st.Assigned) + " with " + st.RunModel, Verdict: verdict, Detail: out.Reasons})
	e.Updated = now
	h.lib.dirty = true
	if verdict != "pass" {
		e.Status, e.Waiting = "flagged", ""
		e.Flag = "Reviewer said " + verdict + ": " + firstNonEmpty(out.Reasons, "no reason given")
		return
	}
	kind := runnableKind(e)
	if kind == "" {
		e.Status, e.Flag, e.Waiting = "verified", "", ""
		return
	}
	if riskyScript.MatchString(e.Content) {
		e.Status, e.Waiting = "flagged", ""
		e.Flag = "The script touches files, the network or other programs. Check it yourself before anything runs it."
		return
	}
	e.Waiting = "a computer that can test-run it"
	h.queueJobLocked(&libJob{Kind: "run", EntryID: e.ID})
}

func (h *Hub) runDoneLocked(j *libJob, st *hubStep) {
	e := h.lib.Entries[j.EntryID]
	if e == nil {
		h.dropJobLocked(j)
		return
	}
	if st.Status != "done" {
		h.retryJobLocked(j, firstNonEmpty(st.Err, st.Status))
		return
	}
	var out runResult
	if !extractJSON(st.Text.String(), &out) {
		h.retryJobLocked(j, "the test run didn't report a result")
		return
	}
	h.dropJobLocked(j)
	if out.Skipped {
		// The host couldn't sandbox the run (e.g. it's on Windows). Leave the
		// entry waiting for a computer that can, rather than flagging it.
		e.Waiting = "a computer that can test-run it"
		e.Updated = time.Now()
		h.lib.dirty = true
		return
	}
	now := time.Now()
	verdict := "pass"
	if !out.OK {
		verdict = "fail"
	}
	detail := strings.TrimSpace(out.Output)
	if len(detail) > 1500 {
		detail = "…" + detail[len(detail)-1500:]
	}
	e.Checks = append(e.Checks, LibCheck{At: now, Kind: "run", Device: h.deviceName(st.Assigned), Verdict: verdict,
		Detail: strings.TrimSpace(out.Summary + "\n" + detail)})
	e.Updated, e.Waiting = now, ""
	h.lib.dirty = true
	if out.OK {
		e.Status, e.Flag = "verified", ""
	} else {
		e.Status, e.Flag = "flagged", "The script failed when test-run: "+out.Summary
	}
}

func firstNonEmpty(ss ...string) string {
	for _, s := range ss {
		if strings.TrimSpace(s) != "" {
			return s
		}
	}
	return ""
}
