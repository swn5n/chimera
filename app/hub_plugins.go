package main

// The network's plugins as the hub sees them: what the online devices say they
// have installed, one library entry per plugin (where people's star ratings
// for its results collect), and the search a requester's app uses to pick a
// plugin for a request: only plugins relevant to what was asked, and among
// those the best rated.

import (
	"encoding/json"
	"fmt"
	"log"
	"math"
	"net/http"
	"sort"
	"strings"
	"time"
)

const (
	pluginBonusShare = 0.5 // a Head's owner earns this much extra on top of the time charge, from the network…
	pluginBonusMin   = 0.1 // …and never less than this per run for someone else: a fast deterministic tool still counts
	pluginStarBonus  = 1.0 // …plus this many credits each time someone else rates its result 4 or 5 stars

	pluginMinRelevance = 0.25 // at least one solid match with what the plugin says it does
	pluginPriorStars   = 3.5  // a plugin starts as if it had two 3.5-star ratings, so one
	pluginPriorWeight  = 2.0  // lucky 5 doesn't beat a plugin with a long record of 4s
)

const (
	maxPluginsPerDevice = 32  // plugins a device may advertise (the rest of its list is ignored)
	maxPluginEntries    = 200 // plugin entries the library keeps
	maxPluginRuns       = 2000
)

// pluginRun is a finished plugin step its requester may still rate.
type pluginRun struct {
	Plugin string    `json:"plugin"`
	Owner  string    `json:"owner"`
	Worker string    `json:"worker"`
	At     time.Time `json:"at"`
}

// PluginCandidate is one plugin the network could run for a request.
type PluginCandidate struct {
	ID        string          `json:"id"`
	Name      string          `json:"name"`
	Version   string          `json:"version"`
	Summary   string          `json:"summary"`
	WhenToUse string          `json:"when_to_use,omitempty"`
	Accepts   []string        `json:"accepts,omitempty"`
	Produces  []string        `json:"produces,omitempty"`
	Caps      []string        `json:"caps,omitempty"`
	Options   json.RawMessage `json:"options,omitempty"`
	Devices   int             `json:"devices"`   // online devices that would run it for the asker
	Relevance float64         `json:"relevance"` // 0..1, how well it matches what was asked
	Rating    float64         `json:"rating"`    // average stars, 0 when nobody rated it yet
	Rated     int             `json:"rated"`
	Score     float64         `json:"score"` // the rating the ranking used (with the prior)
	Uses      int             `json:"uses"`
	EntryID   string          `json:"entry_id,omitempty"`
	Status    string          `json:"status,omitempty"`
}

func clampFloat(v, lo, hi float64) float64 {
	if math.IsNaN(v) || v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func (h *Hub) pluginEntryLocked(id string) *LibEntry {
	for _, e := range h.lib.Entries {
		if e.Kind == "plugin" && e.Plugin == id {
			return e
		}
	}
	return nil
}

func pluginTags(p PluginInfo) []string {
	tags := []string{}
	seen := map[string]bool{}
	for _, t := range append(append([]string{}, p.Tags...), p.TaskKinds...) {
		if t = strings.ToLower(strings.TrimSpace(t)); t != "" && !seen[t] && len(tags) < 10 {
			seen[t] = true
			tags = append(tags, t)
		}
	}
	return tags
}

// pluginEntryContent is what the library shows about a plugin (never code).
func pluginEntryContent(p PluginInfo) string {
	var b strings.Builder
	if p.WhenToUse != "" {
		fmt.Fprintf(&b, "When to use: %s\n", p.WhenToUse)
	}
	if p.WhenNotToUse != "" {
		fmt.Fprintf(&b, "Not for: %s\n", p.WhenNotToUse)
	}
	if len(p.Accepts) > 0 {
		fmt.Fprintf(&b, "Takes: %s\n", strings.Join(p.Accepts, ", "))
	}
	if len(p.Produces) > 0 {
		fmt.Fprintf(&b, "Gives back: %s\n", strings.Join(p.Produces, ", "))
	}
	var schema struct {
		Properties map[string]struct {
			Description string `json:"description"`
		} `json:"properties"`
	}
	if json.Unmarshal(p.Options, &schema) == nil && len(schema.Properties) > 0 {
		var names []string
		for k := range schema.Properties {
			names = append(names, k)
		}
		sort.Strings(names)
		fmt.Fprintf(&b, "Options: %s\n", strings.Join(names, ", "))
	}
	b.WriteString("Runs on the computers that have it installed. Attach a picture in a chat and ask for it.")
	return b.String()
}

// syncPluginEntriesLocked keeps one library entry per plugin a device has.
func (h *Hub) syncPluginEntriesLocked(d *hubDevice) {
	for _, p := range d.profile.Plugins {
		if !p.Have || !pluginIDRe.MatchString(p.ID) {
			continue
		}
		title := strings.TrimSpace(p.Name)
		if title == "" {
			title = p.ID
		}
		e := h.pluginEntryLocked(p.ID)
		if e == nil && h.pluginEntryCountLocked() >= maxPluginEntries {
			continue
		}
		if e == nil {
			now := time.Now()
			e = &LibEntry{ID: randomID(6), Kind: "plugin", Plugin: p.ID, Version: p.Version, Title: truncate(title, 120),
				Summary: truncate(p.Summary, 600), Content: pluginEntryContent(p), Tags: pluginTags(p),
				Status: "unverified", Waiting: "its first run for someone",
				Source: LibSource{Owner: d.Owner, Device: d.Name, From: "plugin"}, Checks: []LibCheck{}, Created: now, Updated: now}
			h.lib.Entries[e.ID] = e
			h.lib.dirty = true
			log.Printf("library: plugin %s %s from %s", p.ID, p.Version, d.Name)
			continue
		}
		if versionLess(e.Version, p.Version) && sameOwner(e.Source.Owner, d.Owner) {
			// A newer version keeps its ratings but proves itself again on its next run. Only the
			// owner who brought the plugin rewrites its entry: anyone can claim a higher version.
			e.Version, e.Title, e.Summary = p.Version, truncate(title, 120), truncate(p.Summary, 600)
			e.Content, e.Tags = pluginEntryContent(p), pluginTags(p)
			if e.Status == "verified" {
				e.Status, e.Waiting = "unverified", "its first run of version "+p.Version
			}
			e.Updated = time.Now()
			h.lib.dirty = true
		}
	}
}

func (h *Hub) pluginEntryCountLocked() int {
	n := 0
	for _, e := range h.lib.Entries {
		if e.Kind == "plugin" {
			n++
		}
	}
	return n
}

// pluginStepDoneLocked records a plugin step on its library entry: a use, and
// the first successful run for someone verifies it.
func (h *Hub) pluginStepDoneLocked(st *hubStep, worker *hubDevice, status string) {
	if status != "done" || worker == nil {
		return
	}
	h.lib.PluginRuns[st.ID] = &pluginRun{Plugin: st.Plugin, Owner: st.RequesterOwner, Worker: worker.Owner, At: time.Now()}
	for len(h.lib.PluginRuns) > maxPluginRuns { // forget the oldest
		oldest := ""
		for id, r := range h.lib.PluginRuns {
			if oldest == "" || r.At.Before(h.lib.PluginRuns[oldest].At) {
				oldest = id
			}
		}
		delete(h.lib.PluginRuns, oldest)
	}
	h.lib.dirty = true
	e := h.pluginEntryLocked(st.Plugin)
	if e == nil {
		return
	}
	e.Uses++
	if e.Status == "unverified" && len(st.Files) > 0 {
		e.Status, e.Waiting = "verified", ""
		e.Checks = append(e.Checks, LibCheck{At: time.Now(), Kind: "run", Device: worker.Name, Verdict: "pass",
			Detail: fmt.Sprintf("Ran for %s and returned %d file(s).", firstNonEmpty(st.RequesterOwner, "someone"), len(st.Files))})
	}
	e.Updated = time.Now()
	h.lib.dirty = true
}

// ratePluginLocked adds one person's stars to a plugin. A plugin that keeps
// getting 1 or 2 stars waits for the host to look at it.
func (h *Hub) ratePluginLocked(id string, rating int) string {
	e := h.pluginEntryLocked(id)
	if e == nil {
		return ""
	}
	e.Stars += rating
	e.Rated++
	if rating >= 4 {
		e.Votes++
	}
	if avg, _ := pluginRating(e); e.Rated >= 3 && avg < 2 && e.Status != "flagged" {
		e.Status, e.Flag = "flagged", fmt.Sprintf("Rated %.1f stars on average by %d people.", avg, e.Rated)
	}
	e.Updated = time.Now()
	h.lib.dirty = true
	return e.ID
}

// pluginRating is the stars the ranking uses: the average pulled toward the
// prior until a plugin has a few ratings.
func pluginRating(e *LibEntry) (avg, score float64) {
	if e == nil {
		return 0, pluginPriorStars
	}
	if e.Rated > 0 {
		avg = round2(float64(e.Stars) / float64(e.Rated))
	}
	score = (float64(e.Stars) + pluginPriorStars*pluginPriorWeight) / (float64(e.Rated) + pluginPriorWeight)
	return avg, round2(score)
}

// Words that say nothing about the job when a picture comes with the request.
var pluginWeakWords = map[string]bool{"picture": true, "pictures": true, "image": true, "images": true, "photo": true,
	"photos": true, "photograph": true, "pic": true, "pics": true, "file": true, "files": true, "add": true, "put": true,
	"give": true, "get": true, "need": true, "want": true, "like": true, "just": true, "it": true, "thing": true}

// pluginTerms are the words of a request that can tell plugins apart. With a
// picture attached, words like "picture" say nothing; with no picture they are
// the point ("generate an image of…"), so they stay.
func pluginTerms(q string, withInput bool) []string {
	var out []string
	for _, t := range tokenize(q) {
		if withInput && pluginWeakWords[t] {
			continue
		}
		if !withInput && (t == "it" || t == "just" || t == "thing" || t == "like" || t == "want" || t == "need") {
			continue
		}
		out = append(out, t)
	}
	return out
}

// pluginRelevance is how well a request's words match what a plugin says it does.
func pluginRelevance(terms []string, p PluginInfo) float64 {
	if len(terms) == 0 {
		return 0
	}
	name := strings.ToLower(p.Name + " " + p.ID)
	tags := strings.ToLower(strings.Join(append(append([]string{}, p.Tags...), p.TaskKinds...), " "))
	summary := strings.ToLower(p.Summary)
	when := strings.ToLower(p.WhenToUse)
	sum := 0.0
	for _, t := range terms {
		switch {
		case strings.Contains(name, t):
			sum += 3
		case strings.Contains(tags, t):
			sum += 2.5
		case strings.Contains(summary, t):
			sum += 1.5
		case strings.Contains(when, t):
			sum += 1
		}
	}
	return round2(math.Min(1, sum/6)) // two strong matches make a plugin fully relevant
}

func acceptsType(accepts []string, mime string) bool {
	mime = strings.ToLower(strings.TrimSpace(mime))
	for _, a := range accepts {
		a = strings.ToLower(strings.TrimSpace(a))
		if a == mime || a == "*/*" || (strings.HasSuffix(a, "/*") && strings.HasPrefix(mime, strings.TrimSuffix(a, "*"))) {
			return true
		}
	}
	return false
}

// pluginScope is where a request may run: the device picked in "Run on" and
// "Only my devices". The search only counts plugins on those devices, the same
// limits fits puts on the step itself, so the best rated plugin is one the step
// can actually go to.
type pluginScope struct {
	Target  string // a device ID, or "" for any
	Private bool   // only the asker's own devices
}

// pluginCandidatesLocked lists the plugins that could run for viewer's request:
// relevant to the words (when there are any) and able to take the input, ranked
// by their ratings. all=true lists every plugin in the network.
func (h *Hub) pluginCandidatesLocked(viewer *hubDevice, query, accepts string, all bool, scope pluginScope) []PluginCandidate {
	type agg struct {
		info    PluginInfo
		devices int
		caps    map[string]bool
	}
	found := map[string]*agg{}
	for _, d := range h.st.Devices {
		if !h.onlineLocked(d) || !d.lending || d.draining || !d.ollamaOK {
			continue
		}
		mine := viewer != nil && sameOwner(d.Owner, viewer.Owner)
		if !d.lendPlugins && !mine {
			continue
		}
		if (scope.Target != "" && d.ID != scope.Target) || (scope.Private && !mine) {
			continue
		}
		for _, p := range d.profile.Plugins {
			if !p.Have || !d.hasTool("plugin:"+p.ID) {
				continue
			}
			a := found[p.ID]
			if a == nil {
				a = &agg{info: p, caps: map[string]bool{}}
				found[p.ID] = a
			} else if versionLess(a.info.Version, p.Version) {
				a.info = p
			}
			a.devices++
			for _, c := range p.Caps {
				a.caps[c] = true
			}
		}
	}
	terms := pluginTerms(query, accepts != "")
	var out []PluginCandidate
	for id, a := range found {
		p := a.info
		rel := pluginRelevance(terms, p)
		e := h.pluginEntryLocked(id)
		if !all {
			if len(terms) > 0 && rel < pluginMinRelevance {
				continue
			}
			if accepts != "" && !acceptsType(p.Accepts, accepts) {
				continue
			}
			if accepts == "" && len(p.Accepts) > 0 && !p.OptionalInput {
				continue // it needs an input file and none was given
			}
			if e != nil && e.Status == "flagged" {
				continue
			}
		}
		avg, score := pluginRating(e)
		c := PluginCandidate{ID: id, Name: p.Name, Version: p.Version, Summary: p.Summary, WhenToUse: p.WhenToUse,
			Accepts: p.Accepts, Produces: p.Produces, Options: p.Options, Devices: a.devices, Relevance: rel,
			Rating: avg, Score: score}
		for cp := range a.caps {
			c.Caps = append(c.Caps, cp)
		}
		sort.Strings(c.Caps)
		if e != nil {
			c.Rated, c.Uses, c.EntryID, c.Status = e.Rated, e.Uses, e.ID, e.Status
		}
		out = append(out, c)
	}
	sort.Slice(out, func(i, j int) bool {
		a, b := out[i], out[j]
		if a.Score != b.Score { // the star rating decides between relevant plugins
			return a.Score > b.Score
		}
		if a.Relevance != b.Relevance {
			return a.Relevance > b.Relevance
		}
		if a.Uses != b.Uses {
			return a.Uses > b.Uses
		}
		return a.ID < b.ID
	})
	return out
}

func (h *Hub) handlePlugins(w http.ResponseWriter, r *http.Request, d *hubDevice) {
	q := r.URL.Query()
	h.mu.Lock()
	out := h.pluginCandidatesLocked(d, q.Get("q"), q.Get("accepts"), q.Get("all") == "1",
		pluginScope{Target: q.Get("target"), Private: q.Get("private") == "1"})
	h.mu.Unlock()
	if n := atoiDefault(q.Get("limit"), 10); n > 0 && len(out) > n {
		out = out[:n]
	}
	if out == nil {
		out = []PluginCandidate{}
	}
	writeJSON(w, 200, map[string]any{"plugins": out})
}
