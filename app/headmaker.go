package main

// The Head maker (Settings → Heads → Make a Head) builds a working Head from a
// few answers instead of code, for the two shapes almost every Head has:
//   program  a program on this computer, run with a command line whose
//            {{placeholders}} are filled from the request (the picture's file,
//            the words, the folder to save results in, the Head's settings)
//   server   a server on this computer called over HTTP (an image or 3D model
//            server), with the same placeholders in its address and JSON
// The answers go into the "maker" block of the Head's plugin.json, and the same
// small runner (headkit/run.py) reads them. So a made Head is an ordinary Head
// folder: it runs in the same sandbox, can be copied to another computer, and
// opens in the maker again to be changed. "Try it" runs any Head installed
// here once, the way the pool would, and shows what came back.

import (
	_ "embed"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"sync"
	"time"
)

//go:embed headkit/run.py
var headRunner []byte

const headMakerFormat = 1

// HeadSpec is the "maker" block of a made Head's plugin.json: what the form
// asked, and what headkit/run.py reads.
type HeadSpec struct {
	Format int      `json:"format"`
	Kind   string   `json:"kind"`   // program or server
	Input  string   `json:"input"`  // picture, words or either (a picture, or words alone)
	Output []string `json:"output"` // picture, model, video, sound, text, file
	// program
	Command        string `json:"command,omitempty"`
	CommandNoInput string `json:"command_no_input,omitempty"` // with input "either", when there's no picture
	// server
	URL         string          `json:"url,omitempty"`
	Method      string          `json:"method,omitempty"`
	Body        json.RawMessage `json:"body,omitempty"`         // a JSON template
	UploadField string          `json:"upload_field,omitempty"` // send the picture as a file upload under this name
	HealthURL   string          `json:"health_url,omitempty"`
	ResultField string          `json:"result_field,omitempty"` // where the file is in a JSON answer, e.g. images.0
	// both
	Reads    []string     `json:"reads,omitempty"` // folders it reads besides its own
	Options  []HeadOption `json:"options,omitempty"`
	TypicalS int          `json:"typical_s,omitempty"` // how long a run usually takes, for the progress bar
}

// HeadOption is one setting people can ask for in words ("make it darker").
type HeadOption struct {
	Name        string   `json:"name"`
	Type        string   `json:"type"` // number, integer, boolean, choice, text
	Description string   `json:"description"`
	Default     any      `json:"default"`
	Min         *float64 `json:"min,omitempty"`
	Max         *float64 `json:"max,omitempty"`
	Choices     []string `json:"choices,omitempty"`
	Yes         *string  `json:"yes,omitempty"` // a program's yes/no setting: what it adds to the command
	No          *string  `json:"no,omitempty"`
}

// headForm is what the form sends: the manifest's words plus the maker block.
type headForm struct {
	ID           string   `json:"id"`
	Name         string   `json:"name"`
	Summary      string   `json:"summary"`
	WhenToUse    string   `json:"when_to_use"`
	WhenNotToUse string   `json:"when_not_to_use"`
	Tags         []string `json:"tags"`
	TimeoutS     int      `json:"timeout_s"`
	Maker        HeadSpec `json:"maker"`
	BodyText     *string  `json:"body_text,omitempty"` // the JSON to send, as typed (checked here, stored as JSON)
	Replace      bool     `json:"replace,omitempty"`   // change the made Head with this id
}

var (
	headOptionRe   = regexp.MustCompile(`^[a-z][a-z0-9_]{0,31}$`)
	placeholderRe  = regexp.MustCompile(`\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}`)
	uploadFieldRe  = regexp.MustCompile(`^[A-Za-z0-9_.\-\[\]]{1,64}$`)
	headSlugDashes = regexp.MustCompile(`[^a-z0-9]+`)
)

// The placeholders headkit/run.py fills in, besides the Head's own settings.
var headPlaceholders = map[string][]string{
	"program": {"prompt", "input", "name", "out", "cache", "blender", "seed"},
	"server":  {"prompt", "input_base64", "input_data_url", "name", "seed"},
}

// What each kind of output means in MIME types; the asker keeps only these.
var headOutputs = []struct {
	key   string
	types []string
}{
	{"picture", []string{"image/*"}},
	{"model", []string{"model/*", "application/x-blender"}},
	{"video", []string{"video/*"}},
	{"sound", []string{"audio/*"}},
	{"text", []string{"text/*", "application/json"}},
	{"file", []string{"*/*"}},
}

func headSlug(name string) string {
	s := strings.Trim(headSlugDashes.ReplaceAllString(strings.ToLower(name), "-"), "-")
	if len(s) > 48 {
		s = strings.TrimRight(s[:48], "-")
	}
	if len(s) < 2 {
		s = "my-head"
	}
	return s
}

func placeholdersIn(s string) []string {
	var out []string
	for _, m := range placeholderRe.FindAllStringSubmatch(s, -1) {
		if !slices.Contains(out, m[1]) {
			out = append(out, m[1])
		}
	}
	return out
}

// localURL says whether u is an http(s) address on this computer, the only
// servers a made Head may call.
func localURL(u string) bool {
	p, err := url.Parse(u)
	if err != nil || (p.Scheme != "http" && p.Scheme != "https") {
		return false
	}
	h := strings.ToLower(p.Hostname())
	return h == "localhost" || h == "::1" || strings.HasPrefix(h, "127.")
}

func expandHome(p string) string {
	if p == "~" || strings.HasPrefix(p, "~/") || strings.HasPrefix(p, `~\`) {
		return filepath.Join(realHome(), p[1:])
	}
	return p
}

func fmtDefault(v any) string {
	switch x := v.(type) {
	case float64:
		return strconv.FormatFloat(x, 'g', -1, 64)
	case bool:
		if x {
			return "yes"
		}
		return "no"
	case string:
		return x
	}
	return ""
}

// check tidies the form and says, in words for the person filling it in,
// what's missing or wrong.
func (f *headForm) check() error {
	f.Name, f.Summary = strings.TrimSpace(f.Name), strings.TrimSpace(f.Summary)
	f.WhenToUse, f.WhenNotToUse = strings.TrimSpace(f.WhenToUse), strings.TrimSpace(f.WhenNotToUse)
	switch {
	case f.Name == "":
		return errors.New("Give the Head a name.")
	case len(f.Name) > 60:
		return errors.New("Keep the name under 60 characters.")
	case f.Summary == "":
		return errors.New("Say in one sentence what it makes or does.")
	case f.WhenToUse == "":
		return errors.New("Say when the pool should use it. A model reads this to decide which requests go to the Head.")
	}
	f.ID = strings.TrimSpace(f.ID)
	if f.ID == "" {
		f.ID = headSlug(f.Name)
	}
	if !pluginIDRe.MatchString(f.ID) {
		return fmt.Errorf("The Head's id %q must be 2-48 lowercase letters, digits or dashes.", f.ID)
	}
	var tags []string
	for _, t := range f.Tags {
		t = strings.ToLower(strings.TrimSpace(t))
		if t != "" && len(t) <= 40 && !slices.Contains(tags, t) && len(tags) < 16 {
			tags = append(tags, t)
		}
	}
	f.Tags = tags
	if f.TimeoutS <= 0 {
		f.TimeoutS = 1800
	}
	f.TimeoutS = clampInt(f.TimeoutS, 30, 7200)

	s := &f.Maker
	s.Format = headMakerFormat
	if s.Input != "picture" && s.Input != "words" && s.Input != "either" {
		return errors.New("Say what it works on: a picture, words, or either.")
	}
	var outs []string
	for _, o := range headOutputs {
		if slices.Contains(s.Output, o.key) {
			outs = append(outs, o.key)
		}
	}
	if len(outs) == 0 {
		return errors.New("Pick what it gives back.")
	}
	s.Output = outs
	if s.TypicalS <= 0 {
		s.TypicalS = 60
	}
	s.TypicalS = clampInt(s.TypicalS, 1, 7200)
	allowed, ok := headPlaceholders[s.Kind]
	if !ok {
		return errors.New("Choose how it runs: a program on this computer, or a server on this computer.")
	}
	allowed = append([]string{}, allowed...)
	if err := s.checkOptions(); err != nil {
		return err
	}
	for _, o := range s.Options {
		allowed = append(allowed, o.Name)
	}
	unknown := func(where, text string) error {
		for _, p := range placeholdersIn(text) {
			if !slices.Contains(allowed, p) {
				return fmt.Errorf("%s uses {{%s}}, which isn't a placeholder or one of its settings. It can use %s.", where, p, "{{"+strings.Join(allowed, "}}, {{")+"}}")
			}
		}
		return nil
	}
	switch s.Kind {
	case "program":
		s.Command, s.CommandNoInput = strings.TrimSpace(s.Command), strings.TrimSpace(s.CommandNoInput)
		s.URL, s.Method, s.Body, s.UploadField, s.HealthURL, s.ResultField = "", "", nil, "", "", ""
		if s.Command == "" {
			return errors.New("Write the command that runs the program.")
		}
		if err := unknown("The command", s.Command); err != nil {
			return err
		}
		usesInput := slices.Contains(placeholdersIn(s.Command), "input")
		switch {
		case s.Input != "words" && !usesInput:
			return errors.New("The command needs {{input}} where the picture's file goes, or the program never sees the picture.")
		case s.Input == "words" && usesInput:
			return errors.New("This Head works on words only, so its command can't use {{input}}. Use {{prompt}} for the words.")
		}
		if s.Input == "either" {
			if s.CommandNoInput == "" {
				return errors.New("Write the command to run when there's no picture, too.")
			}
			if err := unknown("The command without a picture", s.CommandNoInput); err != nil {
				return err
			}
			if slices.Contains(placeholdersIn(s.CommandNoInput), "input") {
				return errors.New("The command for when there's no picture can't use {{input}}.")
			}
		} else {
			s.CommandNoInput = ""
		}
	case "server":
		s.Command, s.CommandNoInput = "", ""
		s.URL, s.HealthURL = strings.TrimSpace(s.URL), strings.TrimSpace(s.HealthURL)
		s.UploadField, s.ResultField = strings.TrimSpace(s.UploadField), strings.TrimSpace(s.ResultField)
		if !localURL(s.URL) {
			return errors.New("The server's address must be on this computer, like http://127.0.0.1:8080/generate. Heads never reach the internet.")
		}
		if s.HealthURL != "" && !localURL(s.HealthURL) {
			return errors.New("The address that checks the server must be on this computer too.")
		}
		s.Method = strings.ToUpper(strings.TrimSpace(s.Method))
		if s.Method == "" {
			s.Method = "POST"
		}
		if s.Method != "GET" && s.Method != "POST" && s.Method != "PUT" {
			return errors.New("The method must be POST, GET or PUT.")
		}
		if f.BodyText != nil {
			s.Body = json.RawMessage(*f.BodyText)
		}
		if body := strings.TrimSpace(string(s.Body)); body == "" || body == "null" {
			s.Body = nil
		} else {
			var v any
			if err := json.Unmarshal([]byte(body), &v); err != nil {
				return fmt.Errorf("The JSON to send isn't valid JSON (%v). Put each {{placeholder}} in quotes: \"{{steps}}\" still sends a number.", err)
			}
			s.Body = json.RawMessage(body)
		}
		if s.Method == "GET" && s.Body != nil {
			return errors.New("A GET request has no JSON to send. Choose POST, or put the values in the address.")
		}
		if err := unknown("The address", s.URL); err != nil {
			return err
		}
		if err := unknown("The JSON to send", string(s.Body)); err != nil {
			return err
		}
		if s.UploadField != "" && !uploadFieldRe.MatchString(s.UploadField) {
			return errors.New("The upload field's name can only have letters, digits and _ . - [ ].")
		}
		if s.UploadField != "" && s.Method == "GET" {
			return errors.New("A picture can't be uploaded with GET. Choose POST.")
		}
		if len(s.ResultField) > 120 {
			return errors.New("Keep where the result is short, like images.0 or data.mesh.")
		}
		names := placeholdersIn(s.URL + string(s.Body))
		sendsPic := s.UploadField != "" || slices.Contains(names, "input_base64") || slices.Contains(names, "input_data_url")
		switch {
		case s.Input != "words" && !sendsPic:
			return errors.New("The picture never reaches the server. Put \"{{input_base64}}\" (or \"{{input_data_url}}\") in the JSON, or send it as a file upload.")
		case s.Input == "words" && sendsPic:
			return errors.New("This Head works on words only, so it has no picture to send. Use {{prompt}} for the words.")
		}
	}
	var reads []string
	for _, r := range s.Reads {
		r = strings.TrimSpace(r)
		if r == "" {
			continue
		}
		r = expandHome(r)
		if !filepath.IsAbs(r) {
			return fmt.Errorf("Write folders it reads as full paths, like /Users/you/models, not %q.", r)
		}
		if !fileExists(r) {
			return fmt.Errorf("There's no folder at %s.", r)
		}
		if !slices.Contains(reads, r) {
			reads = append(reads, r)
		}
	}
	s.Reads = reads
	return nil
}

func (s *HeadSpec) checkOptions() error {
	reserved := headPlaceholders[s.Kind]
	var seen []string
	for i := range s.Options {
		o := &s.Options[i]
		o.Name = strings.ReplaceAll(strings.ToLower(strings.TrimSpace(o.Name)), " ", "_")
		o.Description = strings.TrimSpace(o.Description)
		switch {
		case !headOptionRe.MatchString(o.Name):
			return fmt.Errorf("A setting's name is lowercase letters, digits and _ (like strength), not %q.", o.Name)
		case o.Name != "seed" && slices.Contains(reserved, o.Name):
			return fmt.Errorf("{{%s}} is already a placeholder; call the setting something else.", o.Name)
		case slices.Contains(seen, o.Name):
			return fmt.Errorf("There are two settings called %s.", o.Name)
		case o.Description == "":
			return fmt.Errorf("Say what the setting %s means, so the model knows when a request asks for it.", o.Name)
		case len(o.Description) > 300:
			return fmt.Errorf("Keep the description of %s under 300 characters.", o.Name)
		}
		seen = append(seen, o.Name)
		if o.Type != "boolean" || s.Kind != "program" {
			o.Yes, o.No = nil, nil
		}
		if o.Type != "number" && o.Type != "integer" {
			o.Min, o.Max = nil, nil
		}
		if o.Type != "choice" {
			o.Choices = nil
		}
		switch o.Type {
		case "number", "integer":
			if o.Min != nil && o.Max != nil && *o.Min > *o.Max {
				return fmt.Errorf("The lowest value of %s is above its highest.", o.Name)
			}
			d, ok := o.Default.(float64)
			if !ok {
				if s, isStr := o.Default.(string); isStr && strings.TrimSpace(s) != "" {
					f, err := strconv.ParseFloat(strings.TrimSpace(s), 64)
					if err != nil {
						return fmt.Errorf("The default of %s must be a number.", o.Name)
					}
					d, ok = f, true
				}
			}
			if !ok {
				if o.Min != nil {
					d = *o.Min
				} else {
					d = 0
				}
			}
			if o.Type == "integer" {
				d = math.Round(d)
			}
			if (o.Min != nil && d < *o.Min) || (o.Max != nil && d > *o.Max) {
				return fmt.Errorf("The default of %s is outside its lowest and highest values.", o.Name)
			}
			o.Default = d
		case "boolean":
			b, _ := o.Default.(bool)
			o.Default = b
			for _, t := range []*string{o.Yes, o.No} {
				if t != nil {
					*t = strings.TrimSpace(*t)
				}
			}
		case "choice":
			var cs []string
			for _, c := range o.Choices {
				c = strings.TrimSpace(c)
				if c != "" && len(c) <= 60 && !slices.Contains(cs, c) {
					cs = append(cs, c)
				}
			}
			if len(cs) < 2 {
				return fmt.Errorf("Give %s at least two choices.", o.Name)
			}
			if len(cs) > 30 {
				return fmt.Errorf("Give %s at most 30 choices.", o.Name)
			}
			o.Choices = cs
			d, _ := o.Default.(string)
			if d = strings.TrimSpace(d); d == "" {
				d = cs[0]
			}
			if !slices.Contains(cs, d) {
				return fmt.Errorf("The default of %s must be one of its choices.", o.Name)
			}
			o.Default = d
		case "text":
			d, _ := o.Default.(string)
			if len(d) > 200 {
				return fmt.Errorf("Keep the default of %s under 200 characters.", o.Name)
			}
			o.Default = d
		default:
			return fmt.Errorf("Pick what kind of setting %s is.", o.Name)
		}
	}
	return nil
}

// optionsSchema is the JSON schema of the settings: the model that reads them
// from a request's words follows it, and Chimera checks its answer against it.
func (s HeadSpec) optionsSchema() json.RawMessage {
	if len(s.Options) == 0 {
		return nil
	}
	props := map[string]any{}
	for _, o := range s.Options {
		desc := o.Description
		if d := fmtDefault(o.Default); d != "" {
			desc += " (default " + d + ")"
		}
		p := map[string]any{"description": desc}
		switch o.Type {
		case "number", "integer":
			p["type"] = o.Type
			if o.Min != nil {
				p["minimum"] = *o.Min
			}
			if o.Max != nil {
				p["maximum"] = *o.Max
			}
		case "boolean":
			p["type"] = "boolean"
		case "choice":
			p["type"], p["enum"] = "string", o.Choices
		default:
			p["type"] = "string"
		}
		props[o.Name] = p
	}
	b, _ := json.Marshal(map[string]any{"type": "object", "properties": props})
	return b
}

// madeManifest is plugin.json for a made Head, in the order a person reads it.
type madeManifest struct {
	Format        int             `json:"chimera_plugin"`
	ID            string          `json:"id"`
	Name          string          `json:"name"`
	Version       string          `json:"version"`
	Summary       string          `json:"summary"`
	WhenToUse     string          `json:"when_to_use"`
	WhenNotToUse  string          `json:"when_not_to_use,omitempty"`
	Tags          []string        `json:"tags"`
	TaskKinds     []string        `json:"task_kinds"`
	Accepts       []string        `json:"accepts"`
	OptionalInput bool            `json:"optional_input,omitempty"`
	Produces      []string        `json:"produces"`
	Entry         string          `json:"entry"`
	Interpreter   string          `json:"interpreter"`
	Network       string          `json:"network,omitempty"`
	TimeoutS      int             `json:"timeout_s"`
	Options       json.RawMessage `json:"options,omitempty"`
	Maker         HeadSpec        `json:"maker"`
}

func (f headForm) manifest(version string) ([]byte, error) {
	s := f.Maker
	m := madeManifest{Format: 1, ID: f.ID, Name: f.Name, Version: version, Summary: f.Summary, WhenToUse: f.WhenToUse,
		WhenNotToUse: f.WhenNotToUse, Tags: f.Tags, TaskKinds: []string{}, Accepts: []string{}, OptionalInput: s.Input == "either",
		Entry: "run.py", Interpreter: "python3", TimeoutS: f.TimeoutS, Options: s.optionsSchema(), Maker: s}
	if m.Tags == nil {
		m.Tags = []string{}
	}
	if s.Input != "words" {
		m.Accepts = []string{"image/*"}
	}
	for _, o := range headOutputs {
		if slices.Contains(s.Output, o.key) {
			m.Produces = append(m.Produces, o.types...)
		}
	}
	if s.Kind == "server" {
		m.Network = "localhost"
	}
	b, err := json.MarshalIndent(m, "", "  ")
	return append(b, '\n'), err
}

// nextVersion bumps the last number of a version (1.0.3 → 1.0.4), so the pool
// sees that a changed Head is new.
func nextVersion(v string) string {
	parts := strings.Split(strings.TrimSpace(v), ".")
	if len(parts) == 3 {
		if n, err := strconv.Atoi(parts[2]); err == nil {
			parts[2] = strconv.Itoa(n + 1)
			return strings.Join(parts, ".")
		}
	}
	return "1.0.0"
}

type headError struct {
	code int
	msg  string
}

func (e headError) Error() string { return e.msg }

// saveHead writes a made Head into the heads folder (or changes one made
// before) and checks it straight away.
func (a *App) saveHead(f headForm) (*installedPlugin, error) {
	if err := f.check(); err != nil {
		return nil, headError{400, err.Error()}
	}
	dir := filepath.Join(a.dataDir, "plugins", f.ID)
	if other := a.tools.Plugin(f.ID); other != nil && resolved(other.Dir) != resolved(dir) {
		return nil, headError{409, fmt.Sprintf("A Head with the id %s is already installed from %s. Give this one another name.", f.ID, other.Dir)}
	}
	version := "1.0.0"
	if fileExists(filepath.Join(dir, "plugin.json")) {
		old, _, err := readManifest(dir)
		switch {
		case !f.Replace:
			return nil, headError{409, fmt.Sprintf("There's already a Head called %s on this computer. Give this one another name, or edit that one.", f.ID)}
		case err == nil && len(old.Maker) == 0:
			return nil, headError{409, fmt.Sprintf("%s wasn't made with the Head maker, so change its plugin.json by hand instead.", f.ID)}
		case err == nil:
			version = nextVersion(old.Version)
		}
	} else if fileExists(dir) && !f.Replace {
		return nil, headError{409, fmt.Sprintf("The heads folder already has a folder called %s. Give this Head another name.", f.ID)}
	}
	b, err := f.manifest(version)
	if err != nil {
		return nil, err
	}
	if err := writeFileAtomic(filepath.Join(dir, "run.py"), headRunner); err != nil {
		return nil, err
	}
	if err := writeFileAtomic(filepath.Join(dir, "plugin.json"), b); err != nil {
		return nil, err
	}
	p, err := a.tools.refreshPlugin(dir)
	a.tools.Kick() // so a scan that started before this doesn't leave the Head out
	return p, err
}

// refreshPlugin reads and probes one plugin folder now rather than at the next
// scan: right after the Head maker writes it, or before trying it (the server it
// needs may have just been started).
func (t *ToolScanner) refreshPlugin(dir string) (*installedPlugin, error) {
	m, mod, err := readManifest(dir)
	if err != nil {
		return nil, err
	}
	p := &installedPlugin{Dir: dir, Manifest: m, modTime: mod}
	p.Probe, p.Err = t.probePlugin(p)
	p.probedAt = time.Now()
	if !canSandbox() && p.Err == "" && !t.app.config().UnsandboxedHeads {
		p.Err = noSandboxNote
	}
	t.mu.Lock()
	t.plugins[m.ID] = p
	t.mu.Unlock()
	t.app.notify()
	return p, nil
}

// MadeHeads lists the Heads installed here that the Head maker made, which it can open again.
func (t *ToolScanner) MadeHeads() []string {
	t.mu.Lock()
	defer t.mu.Unlock()
	out := []string{}
	for id, p := range t.plugins {
		if len(p.Manifest.Maker) > 0 {
			out = append(out, id)
		}
	}
	slices.Sort(out)
	return out
}

func pluginNote(p *installedPlugin) string {
	switch {
	case p.Err != "":
		return p.Err
	case !p.Probe.Have:
		return strings.Join(p.Probe.Missing, "; ")
	}
	return ""
}

// ---------- the API ----------

func (a *App) headRoutes(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/heads", func(w http.ResponseWriter, r *http.Request) {
		var f headForm
		if err := readJSON(r, &f, 1<<20); err != nil {
			writeErr(w, 400, "bad request")
			return
		}
		p, err := a.saveHead(f)
		var he headError
		switch {
		case errors.As(err, &he):
			writeErr(w, he.code, he.msg)
			return
		case err != nil:
			writeErr(w, 500, "Couldn't save the Head: "+err.Error())
			return
		}
		writeJSON(w, 200, map[string]any{"id": p.Manifest.ID, "version": p.Manifest.Version, "dir": p.Dir,
			"have": p.Probe.Have && p.Err == "", "note": pluginNote(p)})
	})
	mux.HandleFunc("GET /api/heads/{id}", func(w http.ResponseWriter, r *http.Request) {
		p := a.tools.Plugin(r.PathValue("id"))
		if p == nil {
			writeErr(w, 404, "That Head isn't installed on this computer.")
			return
		}
		m := p.Manifest
		out := map[string]any{"id": m.ID, "name": m.Name, "version": m.Version, "summary": m.Summary,
			"when_to_use": m.WhenToUse, "when_not_to_use": m.WhenNotToUse, "tags": m.Tags, "timeout_s": m.TimeoutS,
			"accepts": m.Accepts, "optional_input": m.OptionalInput, "dir": p.Dir, "editable": len(m.Maker) > 0,
			"have": p.Probe.Have && p.Err == "", "note": pluginNote(p)}
		if len(m.Maker) > 0 {
			out["maker"] = m.Maker
		}
		writeJSON(w, 200, out)
	})
	mux.HandleFunc("POST /api/heads/{id}/try", a.handleHeadTry)
}

// handleHeadTry runs a Head installed here once, the way the pool would run it
// for its owner: options read from the words by a model here, the sandbox, the
// Head's progress. It streams that progress, then the result with its files,
// which are also kept in head-tries/<id>/ to open.
func (a *App) handleHeadTry(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	var req struct {
		Request string `json:"request"`
		Image   *struct {
			Name       string `json:"name"`
			DataBase64 string `json:"data_base64"`
		} `json:"image"`
	}
	if err := readJSON(r, &req, pluginInputMax); err != nil {
		writeErr(w, 400, "bad request")
		return
	}
	p := a.tools.Plugin(id)
	if p == nil {
		writeErr(w, 404, "That Head isn't installed on this computer.")
		return
	}
	if req.Image != nil {
		if _, err := base64.StdEncoding.DecodeString(req.Image.DataBase64); err != nil || req.Image.DataBase64 == "" {
			writeErr(w, 400, "The picture didn't arrive in one piece.")
			return
		}
	}
	fl, ok := w.(http.Flusher)
	if !ok {
		writeErr(w, 500, "streaming unsupported")
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.WriteHeader(200)
	var mu sync.Mutex
	send := func(v any) {
		mu.Lock()
		defer mu.Unlock()
		writeSSE(w, "", v)
		fl.Flush()
	}
	status := func(msg string, f float64) { send(map[string]any{"type": "status", "message": msg, "fraction": f}) }
	status("Checking that "+p.Manifest.Name+" can run here", -1)
	if fresh, err := a.tools.refreshPlugin(p.Dir); err == nil {
		p = fresh
	} else {
		send(map[string]any{"type": "done", "ok": false, "error": err.Error()})
		return
	}
	if note := pluginNote(p); note != "" {
		send(map[string]any{"type": "done", "ok": false, "error": "Can't run here: " + note})
		return
	}
	in := map[string]any{"request": req.Request, "return": "files"}
	if req.Image != nil {
		in["image"] = map[string]string{"name": req.Image.Name, "data_base64": req.Image.DataBase64}
	}
	input, _ := json.Marshal(in)
	ctx := r.Context() // closing the dialog stops the run
	input, note, _ := a.withPluginOptions(ctx, id, input, true, func(msg string) { status(msg, -1) })
	if note != "" {
		send(map[string]any{"type": "note", "message": note})
	}
	res := a.runPlugin(ctx, "try-"+id, id, input, status)
	if res.Cancelled {
		return
	}
	dir := filepath.Join(a.dataDir, "head-tries", id)
	_ = os.RemoveAll(dir)
	type tryFile struct {
		Name   string `json:"name"`
		MIME   string `json:"mime"`
		Bytes  int    `json:"bytes"`
		Width  int    `json:"width,omitempty"`
		Height int    `json:"height,omitempty"`
		Data   string `json:"data_base64,omitempty"` // pictures only, to show them
		Kept   bool   `json:"kept"`                  // the asker's Chimera keeps it (it's a type the Head says it makes)
	}
	var files []tryFile
	for _, f := range res.Files {
		tf := tryFile{Name: f.Name, MIME: sniffMIME(f.Name, f.Data), Bytes: f.Bytes, Width: f.Width, Height: f.Height}
		tf.Kept = len(p.Manifest.Produces) == 0 || acceptsType(p.Manifest.Produces, tf.MIME)
		if strings.HasPrefix(tf.MIME, "image/") && f.Bytes <= 12<<20 {
			tf.Data = base64.StdEncoding.EncodeToString(f.Data)
		}
		if os.MkdirAll(dir, 0o755) == nil {
			_ = os.WriteFile(filepath.Join(dir, filepath.Base(f.Name)), f.Data, 0o644)
		}
		files = append(files, tf)
	}
	send(map[string]any{"type": "done", "ok": res.OK, "summary": res.Summary, "error": res.Error,
		"seconds": res.Seconds, "files": files, "produces": p.Manifest.Produces})
}
