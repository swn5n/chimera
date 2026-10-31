package main

// Plugins are tools a person installs on their own computer so the network can
// call them: a folder with a plugin.json manifest and an entry script, such as
// Perspective's studio shadows for pictures of machines. Plugin code never
// comes from the network. A device lends its plugins (unless its owner turns
// that off), and runs each plugin step in the same kind of sandbox as library
// test runs: no network, the home folder hidden except the folders the plugin
// says it reads, and writes only to the step's output folder, the plugin's own
// cache folder and the system temp folders.
//
// One run of a plugin:
//   stdin   one JSON object, the step input (e.g. {"image": {...}, "options": {...}})
//   argv[1] the output folder (also CHIMERA_OUT); finished files go there
//   stdout  one JSON object: {"ok": true, "summary": "...", "files": [{"path": "a.png"}]}
//           or {"ok": false, "error": "...", "retryable": true}
//   stderr  progress, one JSON object per line: {"event": "progress", "fraction": 0.4, "message": "..."}
//   exit    0 done, 1 failed, 2 bad input, 3 not installed on this computer
// and "<entry> --probe", which prints {"have": true, "caps": [...], "missing": [...],
// "sandbox": {"read": [...]}} so Chimera knows whether it can run here and what it reads.

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"time"
)

const (
	pluginFileMax    = 32 << 20 // one file a plugin returns
	pluginFilesMax   = 64 << 20 // all the files of one step
	pluginInputMax   = 48 << 20 // the step input (pictures travel as base64)
	pluginProbeEvery = 10 * time.Minute
	pluginOutMax     = 96 << 20 // a plugin's stdout (some put their files inline too)
)

var pluginIDRe = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{1,47}$`)
var envNameRe = regexp.MustCompile(`^[A-Z_][A-Z0-9_]{0,63}$`)

const noSandboxNote = "this computer can't sandbox Heads (it needs macOS, or bwrap or unshare on Linux). On Windows you can choose to run them without one: Settings → Heads."

// PluginManifest is the part of plugin.json Chimera reads.
type PluginManifest struct {
	Format       int             `json:"chimera_plugin"`
	ID           string          `json:"id"`
	Name         string          `json:"name"`
	Version      string          `json:"version"`
	Summary      string          `json:"summary"`
	WhenToUse    string          `json:"when_to_use"`
	WhenNotToUse string          `json:"when_not_to_use"`
	TaskKinds    []string        `json:"task_kinds"`
	Tags         []string        `json:"tags"`
	Accepts      []string        `json:"accepts"`  // MIME types of the input file, e.g. image/png
	Produces     []string        `json:"produces"` // MIME types of what comes back
	Entry        string          `json:"entry"`
	Interpreter  string          `json:"interpreter"`       // python3 (default) or sh
	Options      json.RawMessage `json:"options,omitempty"` // JSON schema of the options object
	Env          []string        `json:"env,omitempty"`     // environment variables passed through
	TimeoutS     int             `json:"timeout_s,omitempty"`
	// OptionalInput: the Head can also run from words alone (no file attached), e.g. an
	// image generator that does text-to-image but also takes a picture for image-to-image.
	// A Head with no "accepts" at all is text-only and never needs a file.
	OptionalInput bool `json:"optional_input,omitempty"`
	// Network: "" (none, the default) or "localhost" — the Head may talk to servers on this
	// computer only (ComfyUI, a Hunyuan3D server, …). Still no internet.
	Network string `json:"network,omitempty"`
	// Maker: what the Head maker asked when it made this Head (see headmaker.go);
	// absent for a Head written by hand.
	Maker json.RawMessage `json:"maker,omitempty"`
}

type pluginProbe struct {
	Have    bool     `json:"have"`
	Caps    []string `json:"caps"`
	Missing []string `json:"missing"`
	Sandbox struct {
		Read []string `json:"read"`
	} `json:"sandbox"`
}

type installedPlugin struct {
	Dir      string
	Manifest PluginManifest
	Probe    pluginProbe
	Err      string
	modTime  time.Time
	probedAt time.Time
}

// PluginInfo is what a device tells the network about one of its plugins.
type PluginInfo struct {
	ID            string          `json:"id"`
	Name          string          `json:"name"`
	Version       string          `json:"version"`
	Summary       string          `json:"summary"`
	WhenToUse     string          `json:"when_to_use,omitempty"`
	WhenNotToUse  string          `json:"when_not_to_use,omitempty"`
	TaskKinds     []string        `json:"task_kinds,omitempty"`
	Tags          []string        `json:"tags,omitempty"`
	Accepts       []string        `json:"accepts,omitempty"`
	Produces      []string        `json:"produces,omitempty"`
	Caps          []string        `json:"caps,omitempty"`
	Options       json.RawMessage `json:"options,omitempty"`
	Have          bool            `json:"have"`
	Note          string          `json:"note,omitempty"` // what's missing, when it can't run
	OptionalInput bool            `json:"optional_input,omitempty"`
}

// StepFile is a file a step produced, carried back to whoever asked.
type StepFile struct {
	Name   string `json:"name"`
	MIME   string `json:"mime"`
	Bytes  int    `json:"bytes"`
	SHA256 string `json:"sha256,omitempty"`
	Width  int    `json:"width,omitempty"`
	Height int    `json:"height,omitempty"`
	Data   []byte `json:"data,omitempty"` // base64 in JSON
}

func (f StepFile) withoutData() StepFile { f.Data = nil; return f }

// ---------- finding and probing ----------

// pluginDirs lists candidate plugin folders: every folder in the data folder's
// plugins/, plus CHIMERA_PLUGINS (a path list of plugin folders or folders of them).
func pluginDirs(dataDir string) []string {
	var roots []string
	roots = append(roots, filepath.Join(dataDir, "plugins"))
	for _, p := range filepath.SplitList(os.Getenv("CHIMERA_PLUGINS")) {
		if p = strings.TrimSpace(p); p != "" {
			roots = append(roots, p)
		}
	}
	var out []string
	seen := map[string]bool{}
	add := func(d string) {
		if r, err := filepath.EvalSymlinks(d); err == nil {
			d = r
		}
		if !seen[d] {
			seen[d] = true
			out = append(out, d)
		}
	}
	for _, r := range roots {
		if fileExists(filepath.Join(r, "plugin.json")) {
			add(r)
			continue
		}
		entries, _ := os.ReadDir(r)
		for _, e := range entries {
			d := filepath.Join(r, e.Name())
			if strings.HasPrefix(e.Name(), ".") {
				continue
			}
			if fi, err := os.Stat(d); err == nil && fi.IsDir() && fileExists(filepath.Join(d, "plugin.json")) {
				add(d)
			}
		}
	}
	return out
}

func readManifest(dir string) (PluginManifest, time.Time, error) {
	var m PluginManifest
	path := filepath.Join(dir, "plugin.json")
	fi, err := os.Stat(path)
	if err != nil {
		return m, time.Time{}, err
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return m, time.Time{}, err
	}
	if err := json.Unmarshal(b, &m); err != nil {
		return m, time.Time{}, fmt.Errorf("plugin.json: %v", err)
	}
	m.ID = strings.TrimSpace(m.ID)
	if !pluginIDRe.MatchString(m.ID) {
		return m, time.Time{}, fmt.Errorf("plugin.json: id %q must be 2-48 lowercase letters, digits or dashes", m.ID)
	}
	if m.Name == "" {
		m.Name = m.ID
	}
	if m.Entry == "" {
		return m, time.Time{}, errors.New("plugin.json: no entry")
	}
	if !insideDir(dir, filepath.Join(dir, m.Entry)) {
		return m, time.Time{}, errors.New("plugin.json: the entry must be inside the plugin folder")
	}
	if m.TimeoutS <= 0 {
		m.TimeoutS = 1800
	}
	m.TimeoutS = clampInt(m.TimeoutS, 30, 7200)
	m.Network = strings.ToLower(strings.TrimSpace(m.Network))
	if m.Network != "" && m.Network != "localhost" {
		return m, time.Time{}, fmt.Errorf("plugin.json: network must be \"localhost\" or left out, not %q", m.Network)
	}
	return m, fi.ModTime(), nil
}

func insideDir(dir, p string) bool {
	rel, err := filepath.Rel(dir, p)
	return err == nil && rel != "." && !strings.HasPrefix(rel, "..") && !filepath.IsAbs(rel)
}

// interpreter returns the program that runs a plugin's entry, and its leading arguments.
func (t *ToolScanner) interpreter(m PluginManifest) (string, []string) {
	switch strings.ToLower(strings.TrimSpace(m.Interpreter)) {
	case "", "python", "python3":
		if p := t.Path("python"); p != "" {
			return p, []string{"-E", "-s"} // ignore PYTHON* variables and the user's site-packages
		}
	case "sh":
		if runtime.GOOS != "windows" {
			return "/bin/sh", nil
		}
	}
	return "", nil
}

func (t *ToolScanner) scanPlugins() map[string]*installedPlugin {
	found := map[string]*installedPlugin{}
	sandbox := canSandbox()
	for _, dir := range pluginDirs(t.app.dataDir) {
		m, mod, err := readManifest(dir)
		if err != nil {
			log.Printf("plugins: skipping %s: %v", dir, err)
			continue
		}
		if _, dup := found[m.ID]; dup {
			continue
		}
		t.mu.Lock()
		old := t.plugins[m.ID]
		t.mu.Unlock()
		p := &installedPlugin{Dir: dir, Manifest: m, modTime: mod}
		if old != nil && old.Dir == dir && old.modTime.Equal(mod) && time.Since(old.probedAt) < pluginProbeEvery {
			p.Probe, p.Err, p.probedAt = old.Probe, old.Err, old.probedAt
		} else {
			p.Probe, p.Err = t.probePlugin(p)
			p.probedAt = time.Now()
			if p.Err != "" {
				log.Printf("plugins: %s: %s", m.ID, p.Err)
			} else if !p.Probe.Have {
				log.Printf("plugins: %s can't run here: %s", m.ID, strings.Join(p.Probe.Missing, "; "))
			}
		}
		if !sandbox && p.Err == "" && !t.app.config().UnsandboxedHeads {
			p.Err = noSandboxNote
		}
		found[m.ID] = p
	}
	return found
}

func (t *ToolScanner) probePlugin(p *installedPlugin) (pluginProbe, string) {
	var pr pluginProbe
	interp, lead := t.interpreter(p.Manifest)
	if interp == "" {
		return pr, "needs Python 3 on this computer"
	}
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	args := append(append([]string{}, lead...), filepath.Join(p.Dir, p.Manifest.Entry), "--probe")
	cmd := exec.CommandContext(ctx, interp, args...)
	cmd.Dir = p.Dir
	cmd.Env = pluginEnv(p.Manifest, "", "", t.Path("blender"), "")
	hideWindow(cmd)
	out, _ := cmd.Output() // a probe exits 3 when the plugin can't run here; its JSON says why
	if err := json.Unmarshal(lastJSONLine(out), &pr); err != nil {
		return pr, "its --probe didn't print JSON"
	}
	return pr, ""
}

// lastJSONLine returns the last line of out that looks like a JSON object.
func lastJSONLine(out []byte) []byte {
	lines := bytes.Split(bytes.TrimSpace(out), []byte("\n"))
	for i := len(lines) - 1; i >= 0; i-- {
		l := bytes.TrimSpace(lines[i])
		if len(l) > 1 && l[0] == '{' {
			return l
		}
	}
	return nil
}

func (t *ToolScanner) Plugin(id string) *installedPlugin {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.plugins[id]
}

// PluginInfos describes the plugins installed here, for the network.
func (t *ToolScanner) PluginInfos() []PluginInfo {
	t.mu.Lock()
	defer t.mu.Unlock()
	var out []PluginInfo
	for _, p := range t.plugins {
		m := p.Manifest
		pi := PluginInfo{ID: m.ID, Name: m.Name, Version: m.Version, Summary: m.Summary, WhenToUse: m.WhenToUse,
			WhenNotToUse: m.WhenNotToUse, TaskKinds: m.TaskKinds, Tags: m.Tags, Accepts: m.Accepts,
			Produces: m.Produces, Caps: p.Probe.Caps, Options: m.Options, Have: p.Probe.Have && p.Err == "",
			OptionalInput: m.OptionalInput}
		switch {
		case p.Err != "":
			pi.Note = p.Err
		case !p.Probe.Have:
			pi.Note = strings.Join(p.Probe.Missing, "; ")
		}
		out = append(out, pi)
	}
	sortPluginInfos(out)
	return out
}

func sortPluginInfos(ps []PluginInfo) {
	for i := 1; i < len(ps); i++ {
		for j := i; j > 0 && ps[j].ID < ps[j-1].ID; j-- {
			ps[j], ps[j-1] = ps[j-1], ps[j]
		}
	}
}

// pluginEnv is a bare environment, like a test run's, but with the real home
// folder (a plugin finds its own runtime there; the sandbox still hides the rest).
func pluginEnv(m PluginManifest, out, cache, blender, stepID string) []string {
	env := []string{"LANG=en_US.UTF-8", "PYTHONDONTWRITEBYTECODE=1", "PYTHONNOUSERSITE=1"}
	if h := realHome(); h != "" {
		env = append(env, "HOME="+h)
	}
	pass := []string{"PATH", "TMPDIR", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC",
		"TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA"} // Windows needs these to run Python at all
	for _, k := range m.Env {
		if envNameRe.MatchString(k) && !strings.HasPrefix(k, "CHIMERA_") {
			pass = append(pass, k)
		}
	}
	for _, k := range pass {
		if v := os.Getenv(k); v != "" {
			env = append(env, k+"="+v)
		}
	}
	if out != "" {
		env = append(env, "CHIMERA_OUT="+out)
	}
	if cache != "" {
		env = append(env, "CHIMERA_CACHE="+cache)
	}
	if blender != "" {
		env = append(env, "CHIMERA_BLENDER="+blender)
	}
	if stepID != "" {
		env = append(env, "CHIMERA_STEP="+stepID)
	}
	return env
}

// ---------- running ----------

type pluginRunResult struct {
	OK        bool
	Summary   string
	Error     string
	Retryable bool
	Cancelled bool
	Files     []StepFile
	Seconds   float64
}

type pluginOutput struct {
	OK        bool   `json:"ok"`
	Summary   string `json:"summary"`
	Error     string `json:"error"`
	Retryable bool   `json:"retryable"`
	Files     []struct {
		Path string `json:"path"`
		Name string `json:"name"`
	} `json:"files"`
}

// runPlugin runs one plugin step on this computer. progress gets the plugin's
// own progress messages (fraction 0..1, or -1 when it didn't say).
func (a *App) runPlugin(ctx context.Context, stepID, id string, input []byte, progress func(msg string, frac float64)) pluginRunResult {
	name := a.config().DeviceName
	p := a.tools.Plugin(id)
	if p == nil || !p.Probe.Have || p.Err != "" {
		return pluginRunResult{Error: "The " + id + " plugin can't run on " + name + ".", Retryable: true}
	}
	if len(input) > pluginInputMax {
		return pluginRunResult{Error: "The input is too large for a plugin."}
	}
	interp, lead := a.tools.interpreter(p.Manifest)
	if interp == "" {
		return pluginRunResult{Error: name + " has no Python 3 to run the " + id + " plugin.", Retryable: true}
	}
	if err := os.MkdirAll(filepath.Join(a.dataDir, "plugin-runs"), 0o700); err != nil {
		return pluginRunResult{Error: err.Error(), Retryable: true}
	}
	runDir, err := os.MkdirTemp(filepath.Join(a.dataDir, "plugin-runs"), id+"-*")
	if err != nil {
		return pluginRunResult{Error: err.Error(), Retryable: true}
	}
	defer os.RemoveAll(runDir)
	out := filepath.Join(runDir, "out")
	cache := filepath.Join(a.dataDir, "plugin-cache", id)
	for _, d := range []string{out, cache} {
		if err := os.MkdirAll(d, 0o700); err != nil {
			return pluginRunResult{Error: err.Error(), Retryable: true}
		}
	}
	entry := filepath.Join(p.Dir, p.Manifest.Entry)
	args := append(append(append([]string{}, lead...), entry), out)
	reads := append([]string{p.Dir}, pluginReadPaths(id, p.Probe.Sandbox.Read, a.dataDir, p.Dir)...)
	var stage string // only used by the Linux namespace sandbox, outside the folders it hides
	if runtime.GOOS == "linux" {
		if stage, _ = os.MkdirTemp("/tmp", "chimera-stage-*"); stage != "" {
			defer os.RemoveAll(stage)
		}
	}
	// Chimera's own data folder (its network token, chats, the hub's ledger) is hidden from the
	// plugin wherever it lives, apart from the step's run folder and the plugin's cache inside it.
	argv, how, ok := pluginSandboxed(interp, args, reads, []string{runDir, cache}, []string{a.dataDir}, stage, p.Manifest.Network == "localhost")
	if !ok && a.config().UnsandboxedHeads {
		// Windows (no sandbox Chimera trusts): the owner chose to run Heads anyway. Head code is
		// theirs — installed by hand, never received over the network — so what the sandbox would
		// have guarded against is a hostile input abusing a Head. Say so plainly in the log.
		argv, how, ok = append([]string{interp}, args...), "UNSANDBOXED: this computer can't sandbox Heads and its owner chose to run them anyway", true
	}
	if !ok {
		return pluginRunResult{Error: name + " can't sandbox Heads (it needs macOS, or bwrap or unshare on Linux; on Windows, allow unsandboxed Heads in Settings).", Retryable: true}
	}

	cctx, cancel := context.WithTimeout(ctx, time.Duration(p.Manifest.TimeoutS)*time.Second)
	defer cancel()
	cmd := exec.CommandContext(cctx, argv[0], argv[1:]...)
	cmd.Dir = runDir
	cmd.Env = pluginEnv(p.Manifest, out, cache, a.tools.Path("blender"), stepID)
	cmd.Stdin = bytes.NewReader(input)
	var stdout limitedBuffer
	stdout.max = pluginOutMax
	cmd.Stdout = &stdout
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return pluginRunResult{Error: err.Error(), Retryable: true}
	}
	newProcessGroup(cmd)
	cmd.Cancel = func() error { return terminateGroup(cmd) } // let the plugin stop its own children
	cmd.WaitDelay = 20 * time.Second
	hideWindow(cmd)
	start := time.Now()
	if err := cmd.Start(); err != nil {
		return pluginRunResult{Error: "Couldn't start the plugin: " + err.Error(), Retryable: true}
	}
	var errTail bytes.Buffer
	sc := bufio.NewScanner(stderr)
	sc.Buffer(make([]byte, 64<<10), 1<<20)
	for sc.Scan() {
		line := sc.Bytes()
		var ev struct {
			Event    string   `json:"event"`
			Fraction *float64 `json:"fraction"`
			Message  string   `json:"message"`
		}
		if len(line) > 0 && line[0] == '{' && json.Unmarshal(line, &ev) == nil && ev.Event == "progress" {
			f := -1.0
			if ev.Fraction != nil {
				f = *ev.Fraction
			}
			if progress != nil {
				progress(truncate(ev.Message, 200), f)
			}
			continue
		}
		errTail.Write(line)
		errTail.WriteByte('\n')
		if errTail.Len() > 16<<10 {
			errTail.Next(errTail.Len() - 8<<10)
		}
	}
	werr := cmd.Wait()
	killGroup(cmd) // nothing the plugin started keeps running (or changes its output) after this
	res := pluginRunResult{Seconds: round1(time.Since(start).Seconds())}
	switch {
	case ctx.Err() != nil:
		res.Cancelled, res.Error = true, "cancelled"
		return res
	case cctx.Err() == context.DeadlineExceeded:
		res.Error, res.Retryable = fmt.Sprintf("The %s plugin timed out after %ds.", id, p.Manifest.TimeoutS), true
		return res
	}
	if werr != nil && sandboxDidNotStart(errTail.String()) {
		res.Error, res.Retryable = "Couldn't start the sandbox on "+name+".", true
		return res
	}
	var po pluginOutput
	jerr := json.Unmarshal(lastJSONLine(stdout.Bytes()), &po)
	code := 0
	var ee *exec.ExitError
	if errors.As(werr, &ee) {
		code = ee.ExitCode()
	}
	if jerr != nil || !po.OK || werr != nil {
		msg := strings.TrimSpace(po.Error)
		if msg == "" {
			msg = fmt.Sprintf("The %s plugin stopped (exit code %d). %s", id, code, strings.TrimSpace(tail(errTail.String(), 300)))
		}
		res.Error = msg
		res.Retryable = po.Retryable || code == 3 || (jerr != nil && code != 2)
		return res
	}
	res.Summary = strings.TrimSpace(po.Summary)
	files, ferr := collectPluginFiles(out, po)
	if ferr != nil {
		res.Error = ferr.Error()
		return res
	}
	res.OK, res.Files = true, files
	log.Printf("plugin %s finished in %.1fs (%s)", id, res.Seconds, how)
	return res
}

// collectPluginFiles reads the files a plugin listed (or everything it wrote
// to its output folder) from disk, never trusting paths outside that folder.
func collectPluginFiles(out string, po pluginOutput) ([]StepFile, error) {
	var names []string
	for _, f := range po.Files {
		rel := f.Path
		if rel == "" {
			rel = f.Name
		}
		if rel != "" {
			names = append(names, rel)
		}
	}
	if len(names) == 0 {
		entries, _ := os.ReadDir(out)
		for _, e := range entries {
			if e.Type().IsRegular() && !strings.HasPrefix(e.Name(), ".") {
				names = append(names, e.Name())
			}
		}
	}
	realOut, err := filepath.EvalSymlinks(out)
	if err != nil {
		return nil, err
	}
	var files []StepFile
	total := 0
	for _, rel := range names {
		p := filepath.Join(out, filepath.Clean("/" + rel)[1:])
		if !insideDir(out, p) {
			return nil, fmt.Errorf("the plugin listed a file outside its output folder: %s", rel)
		}
		// Chimera reads these files outside the sandbox: a symlinked folder in the output
		// must not carry a file from somewhere the plugin itself was not allowed to read.
		rp, err := filepath.EvalSymlinks(p)
		if err != nil || !insideDir(realOut, rp) {
			return nil, fmt.Errorf("the plugin listed a file outside its output folder: %s", rel)
		}
		p = rp
		fi, err := os.Lstat(p)
		if err != nil || !fi.Mode().IsRegular() {
			return nil, fmt.Errorf("the plugin didn't write %s", rel)
		}
		if fi.Size() > pluginFileMax {
			return nil, fmt.Errorf("%s is larger than %d MB", rel, pluginFileMax>>20)
		}
		total += int(fi.Size())
		if total > pluginFilesMax {
			return nil, fmt.Errorf("the plugin's files are larger than %d MB together", pluginFilesMax>>20)
		}
		data, err := os.ReadFile(p)
		if err != nil {
			return nil, err
		}
		sum := sha256.Sum256(data)
		f := StepFile{Name: filepath.Base(p), MIME: sniffMIME(p, data), Bytes: len(data), SHA256: hex.EncodeToString(sum[:]), Data: data}
		f.Width, f.Height = imageSize(data)
		files = append(files, f)
	}
	return files, nil
}

func sniffMIME(name string, data []byte) string {
	t := http.DetectContentType(data)
	ext := strings.ToLower(filepath.Ext(name))
	switch {
	case ext == ".usdz" && t == "application/zip":
		return "model/vnd.usdz+zip"
	case (ext == ".m4a" || ext == ".aac") && t == "video/mp4":
		return "audio/mp4"
	case t == "application/ogg" && ext != ".ogv":
		return "audio/ogg"
	}
	if t == "application/octet-stream" || strings.HasPrefix(t, "text/plain") {
		switch ext {
		case ".json":
			return "application/json"
		case ".glb":
			return "model/gltf-binary"
		case ".gltf":
			return "model/gltf+json"
		case ".obj":
			return "model/obj"
		case ".stl":
			return "model/stl"
		case ".ply":
			return "model/ply"
		case ".fbx":
			return "model/fbx"
		case ".blend":
			return "application/x-blender"
		case ".flac":
			return "audio/flac"
		case ".aiff", ".aif", ".aifc": // the Mac's own sound files are often AIFF-C, which isn't sniffed
			return "audio/aiff"
		case ".txt", ".md":
			return "text/plain; charset=utf-8"
		}
	}
	return t
}

// imageSize reads the size of a PNG, JPEG or WebP without decoding it.
func imageSize(b []byte) (int, int) {
	switch {
	case len(b) > 24 && bytes.HasPrefix(b, []byte("\x89PNG\r\n\x1a\n")) && string(b[12:16]) == "IHDR":
		return int(binary.BigEndian.Uint32(b[16:20])), int(binary.BigEndian.Uint32(b[20:24]))
	case len(b) > 4 && b[0] == 0xFF && b[1] == 0xD8:
		for i := 2; i+9 < len(b); {
			if b[i] != 0xFF {
				i++
				continue
			}
			m := b[i+1]
			if m == 0xD8 || m == 0x01 || (m >= 0xD0 && m <= 0xD7) {
				i += 2
				continue
			}
			seg := int(binary.BigEndian.Uint16(b[i+2 : i+4]))
			if m >= 0xC0 && m <= 0xCF && m != 0xC4 && m != 0xC8 && m != 0xCC {
				return int(binary.BigEndian.Uint16(b[i+7 : i+9])), int(binary.BigEndian.Uint16(b[i+5 : i+7]))
			}
			i += 2 + seg
		}
	case len(b) > 30 && string(b[0:4]) == "RIFF" && string(b[8:12]) == "WEBP":
		switch string(b[12:16]) {
		case "VP8X":
			return 1 + (int(b[24]) | int(b[25])<<8 | int(b[26])<<16), 1 + (int(b[27]) | int(b[28])<<8 | int(b[29])<<16)
		case "VP8L":
			v := binary.LittleEndian.Uint32(b[21:25])
			return int(v&0x3FFF) + 1, int((v>>14)&0x3FFF) + 1
		case "VP8 ":
			return int(binary.LittleEndian.Uint16(b[26:28]) & 0x3FFF), int(binary.LittleEndian.Uint16(b[28:30]) & 0x3FFF)
		}
	}
	return 0, 0
}

type limitedBuffer struct {
	bytes.Buffer
	max  int
	over bool
}

func (l *limitedBuffer) Write(p []byte) (int, error) {
	if l.Len()+len(p) > l.max {
		l.over = true
		return len(p), nil // keep draining so the plugin doesn't block
	}
	return l.Buffer.Write(p)
}

var _ io.Writer = (*limitedBuffer)(nil)

// ---------- the plugin sandbox ----------

// pluginSandboxed is sandboxed() for a plugin: the same protection, plus the
// folders the plugin reads (its own folder and the runtime its probe named)
// and the folders it may write.
// localNet lets the plugin reach servers on this computer only (a Head wrapping
// ComfyUI or a 3D model server); the internet stays blocked on macOS, and on
// Linux the network namespace is shared, so the log says so.
func pluginSandboxed(name string, args, reads, writes, hide []string, stage string, localNet bool) (argv []string, how string, ok bool) {
	switch runtime.GOOS {
	case "darwin":
		return macPluginSandbox(name, args, reads, writes, hide, localNet)
	case "linux":
		return linuxPluginSandbox(name, args, reads, writes, hide, stage, localNet)
	default:
		return nil, "", false
	}
}

// pluginReadPaths keeps the folders a probe asked to read that are specific and outside
// Chimera's own data: not /, a home folder or a folder above one (/Users, /home), which would
// undo the sandbox, and nothing in the data folder except inside the plugin's own folder.
func pluginReadPaths(id string, paths []string, dataDir, own string) []string {
	broad := []string{"/Users", "/Volumes", "/home", "/root", "/private/var/root"}
	if h := realHome(); h != "" {
		broad = append(broad, h, resolved(h))
	}
	data, mine := existingPaths([]string{dataDir}), existingPaths([]string{own})
	in := func(q string, dirs []string) bool {
		for _, d := range dirs {
			if q == d || insideDir(d, q) {
				return true
			}
		}
		return false
	}
	var out []string
	for _, p := range paths {
		p = strings.TrimSpace(p)
		if p == "" || !filepath.IsAbs(p) {
			continue
		}
		why := ""
		for _, q := range []string{filepath.Clean(p), resolved(p)} {
			parent := filepath.Dir(q)
			for _, b := range broad {
				if q == "/" || q == b || insideDir(q, b) || parent == "/Users" || parent == "/home" {
					why = "too broad"
				}
			}
			if why == "" && in(q, data) && !in(q, mine) {
				why = "inside Chimera's data folder"
			}
		}
		if why != "" {
			log.Printf("plugins: %s: not letting it read %s (%s)", id, p, why)
			continue
		}
		out = append(out, p)
	}
	return out
}

// existingPaths returns each path and its resolved form, skipping relative and missing ones.
func existingPaths(paths []string) []string {
	var out []string
	seen := map[string]bool{}
	for _, p := range paths {
		p = strings.TrimSpace(p)
		if p == "" || !filepath.IsAbs(p) {
			continue
		}
		if _, err := os.Stat(p); err != nil {
			continue
		}
		for _, q := range []string{filepath.Clean(p), resolved(p)} {
			if !seen[q] {
				seen[q] = true
				out = append(out, q)
			}
		}
	}
	return out
}

func resolved(p string) string {
	if r, err := filepath.EvalSymlinks(p); err == nil {
		return r
	}
	return p
}

// toolHome is the folder a program's own files live in (its .app bundle, or
// the prefix above bin/), which may sit in a home folder.
func toolHome(name string) string {
	dir := filepath.Dir(resolved(name))
	if i := strings.Index(dir, ".app/"); i >= 0 {
		return dir[:i+4]
	}
	if filepath.Base(dir) == "bin" {
		return filepath.Dir(dir)
	}
	return dir
}

// ancestors lists the folders above each path (not "/"), each once.
func ancestors(paths []string) []string {
	var out []string
	seen := map[string]bool{}
	for _, p := range paths {
		for d := filepath.Dir(p); d != "/" && d != "." && d != ""; d = filepath.Dir(d) {
			if !seen[d] {
				seen[d] = true
				out = append(out, d)
			}
		}
	}
	return out
}

func macPluginSandboxProfile(name string, reads, writes, hide []string, localNet bool) string {
	w := existingPaths(writes)
	hd := existingPaths(hide)
	r := existingPaths(append(append(append([]string{}, reads...), toolHome(name)), writes...))
	rule := func(verb, kind string, ps []string, extra string) string {
		if len(ps) == 0 && extra == "" {
			return "" // a rule with no filter would apply to every path
		}
		var b strings.Builder
		fmt.Fprintf(&b, "\n(%s", verb)
		for _, p := range ps {
			fmt.Fprintf(&b, " (%s %s)", kind, sbplQuote(p))
		}
		return b.String() + extra + ")"
	}
	// Later rules win. The home folders are hidden, then what the plugin reads is allowed. Chimera's
	// data folder is hidden after that, so a folder the plugin reads can't contain it, and only the
	// plugin's own folder, the step's run folder and the cache inside it are allowed back.
	// The folders above the allowed ones may be stat-ed but not listed or read: resolving a path
	// (realpath) needs that, and Metal crashes when it can't resolve where it caches GPU kernels.
	net := "\n(deny network*)"
	if localNet { // servers on this computer only; the internet stays off
		net += "\n(allow network* (remote ip \"localhost:*\"))\n(allow network* (local ip \"localhost:*\"))\n(allow network* (remote unix-socket))"
	}
	profile := `(version 1)
(allow default)` + net + `
(deny file-read* (subpath "/Users") (subpath "/Volumes") (subpath "/private/var/root"))` +
		rule("allow file-read*", "subpath", r, "") +
		rule("deny file-read*", "subpath", hd, "") +
		rule("allow file-read*", "subpath", within(r, hd), "") +
		rule("allow file-read-metadata", "literal", ancestors(r), "") +
		"\n(deny file-write*)" +
		rule("allow file-write*", "subpath", w, ` (subpath "/private/var/folders") (subpath "/private/tmp") (literal "/dev/null") (regex #"^/dev/tty") (regex #"^/dev/fd/")`)
	if len(hd) > 0 { // a hidden folder in a temp folder isn't writable either, except the run and cache
		profile += rule("deny file-write*", "subpath", hd, "") + rule("allow file-write*", "subpath", w, "")
	}
	return profile
}

// sandboxHow is the one-line description of the sandbox that goes in the log.
func sandboxHow(localNet bool) string {
	if localNet {
		if runtime.GOOS == "linux" {
			return "sandboxed: network shared (Head talks to a local server; on Linux that means any network), home folder hidden except the plugin's own folders"
		}
		return "sandboxed: this computer's servers only, no internet, home folder hidden except the plugin's own folders"
	}
	return "sandboxed: no network, home folder hidden except the plugin's own folders"
}

// within returns the paths that lie inside one of dirs.
func within(paths, dirs []string) []string {
	var out []string
	for _, p := range paths {
		for _, d := range dirs {
			if insideDir(d, p) {
				out = append(out, p)
				break
			}
		}
	}
	return out
}

// outside returns the paths that lie inside none of dirs.
func outside(paths, dirs []string) []string {
	in := map[string]bool{}
	for _, p := range within(paths, dirs) {
		in[p] = true
	}
	var out []string
	for _, p := range paths {
		if !in[p] {
			out = append(out, p)
		}
	}
	return out
}

func macPluginSandbox(name string, args, reads, writes, hide []string, localNet bool) ([]string, string, bool) {
	p, err := exec.LookPath("sandbox-exec")
	if err != nil {
		return nil, "", false
	}
	profile := macPluginSandboxProfile(name, reads, writes, hide, localNet)
	return append([]string{p, "-p", profile, name}, args...), sandboxHow(localNet), true
}

// bwrapArgs runs name under bubblewrap: no network, the home folders and /tmp empty, the
// folders the plugin reads (r) bound back read-only and the ones it writes (w) read-write, and
// Chimera's data folder (hd) hidden even inside a folder it reads.
func bwrapArgs(bwrap, name string, args, r, w, hd []string, localNet bool) []string {
	argv := []string{bwrap, "--unshare-all", "--die-with-parent", "--new-session"}
	if localNet { // keep this computer's network so the Head can reach its local server
		argv = append(argv, "--share-net")
	}
	argv = append(argv,
		"--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
		"--tmpfs", "/home", "--tmpfs", "/root", "--tmpfs", "/tmp")
	if home := realHome(); home != "" && home != "/home" && home != "/root" {
		argv = append(argv, "--tmpfs", home)
	}
	// Mounts apply in order: the folders the plugin reads, then Chimera's data folder hidden (a
	// folder it reads may contain it), then what it needs inside the data folder bound back.
	for _, d := range outside(r, hd) {
		argv = append(argv, "--ro-bind", d, d)
	}
	for _, d := range hd {
		argv = append(argv, "--tmpfs", d)
	}
	for _, d := range within(r, hd) {
		argv = append(argv, "--ro-bind", d, d)
	}
	for _, d := range w {
		argv = append(argv, "--bind", d, d)
	}
	argv = append(argv, "--chdir", w[0], "--")
	return append(argv, append([]string{name}, args...)...)
}

func linuxPluginSandbox(name string, args, reads, writes, hide []string, stage string, localNet bool) ([]string, string, bool) {
	r := existingPaths(append(append([]string{}, reads...), toolHome(name)))
	w := existingPaths(writes)
	hd := existingPaths(hide)
	if p, err := exec.LookPath("bwrap"); err == nil && len(w) > 0 {
		return bwrapArgs(p, name, args, r, w, hd, localNet), sandboxHow(localNet), true
	}
	// A user + mount + network namespace: no network, the home folders hidden
	// behind empty mounts, and the folders the plugin needs bound back in
	// (through a staging folder, since they live under the hidden ones).
	if p, err := exec.LookPath("unshare"); err == nil && stage != "" {
		sq := func(s string) string { return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'" }
		var b strings.Builder
		b.WriteString("mount --make-rprivate / 2>/dev/null || true; ")
		homes := existingPaths([]string{"/home", "/root", realHome()})
		// Only what lies in a folder about to be hidden needs binding back in; the rest stays visible.
		keep := within(append(append([]string{}, r...), w...), append(append([]string{}, homes...), hd...))
		// make a mount point of the right kind (folder or file) at path
		point := func(path string, dir bool) string {
			if dir {
				return "mkdir -p " + sq(path)
			}
			return "mkdir -p " + sq(filepath.Dir(path)) + " && touch " + sq(path)
		}
		isDir := make([]bool, len(keep))
		for i, d := range keep {
			fi, err := os.Stat(d)
			isDir[i] = err == nil && fi.IsDir()
			fmt.Fprintf(&b, "%s && mount --bind %s %s/%d || exit 97; ", point(fmt.Sprintf("%s/%d", stage, i), isDir[i]), sq(d), sq(stage), i)
		}
		hideAll := func(dirs []string, must bool) {
			var qs []string
			for _, d := range dirs {
				qs = append(qs, sq(d))
			}
			if len(qs) == 0 {
				return
			}
			if must { // if hiding fails, the plugin doesn't run
				b.WriteString("for d in " + strings.Join(qs, " ") + "; do [ ! -d \"$d\" ] || mount -t tmpfs tmpfs \"$d\" || exit 97; done; ")
			} else {
				b.WriteString("for d in " + strings.Join(qs, " ") + "; do [ -d \"$d\" ] && mount -t tmpfs tmpfs \"$d\" 2>/dev/null; done; ")
			}
		}
		inData := map[string]bool{}
		for _, d := range within(keep, hd) {
			inData[d] = true
		}
		bindBack := func(inside bool) {
			for i, d := range keep {
				if inData[d] == inside {
					fmt.Fprintf(&b, "%s && mount --bind %s/%d %s || exit 97; ", point(d, isDir[i]), sq(stage), i, sq(d))
				}
			}
		}
		// Mounts apply in order: the home folders hidden, the folders the plugin reads in them bound
		// back, then Chimera's data folder hidden (a folder it reads may contain it), then what it
		// needs inside the data folder bound back.
		hideAll(homes, false)
		bindBack(false)
		hideAll(hd, true)
		bindBack(true)
		for _, d := range within(r, append(append([]string{}, homes...), hd...)) {
			fmt.Fprintf(&b, "mount -o remount,bind,ro %s 2>/dev/null || true; ", sq(d))
		}
		b.WriteString(`exec "$@"`)
		flags := "-rnm"
		if localNet {
			flags = "-rm" // keep the network namespace so the Head can reach its local server
		}
		argv := []string{p, flags, "--", "/bin/sh", "-c", b.String(), "chimera-sandbox", name}
		return append(argv, args...), sandboxHow(localNet), true
	}
	return nil, "", false
}
