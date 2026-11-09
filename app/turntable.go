package main

// Turntables. A 3D model attached for an engine is rendered with this computer's
// Blender into the chat's folder as a numbered run of WebP frames, one full turn
// with a transparent background and a soft shadow under it, plus a poster (frame 0,
// a little sharper), so a page can spin the model without a 3D library: the Raka
// site's machines, first made by hand on Nov 7, were made this way. The engine reads
// only text, so the frames' line in what it's told says which model they show and
// how far apart they are (attach.go).
//
// The render is the script in turntable.py, in the script sandbox (runner.go), with
// the model and the files it loads (an OBJ's .mtl and textures, a glTF's buffers and
// textures) copied into the run's own folder, since the sandbox can't read the home
// folder. Blender's compiled GPU kernels are kept between runs in the data folder
// (blender-cache), the one other folder the sandbox may write: compiling them takes
// about three minutes the first time, and a frame after that about a second. A model
// whose turntable is already in the chat's folder, made from the same bytes the same
// way, isn't rendered again (.turntable.json beside the frames says how it was made).

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	_ "embed"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

//go:embed turntable.py
var turntableScript string

const (
	turnFrames    = 72 // 5 degrees apart: what the Raka site used, and the user's pick (Nov 9)
	turnPx        = 800
	turnSamples   = 48
	turnStart     = 45.0 // frame 0 is turned this far from how the file faces: a three-quarter view
	turnMaxModels = 12   // turned in one message; the rest are named in the reply's note
	turnTimeout   = 30 * time.Minute
	turnFileMax   = 20 << 20 // one frame
	turnVersion   = 1        // raise it when the render changes, so turntables are made again
	turnRecord    = ".turntable.json"
	turnMarker    = "chimera-turn: "
)

// turnable says whether a file is a model a turntable can be made of.
func turnable(f AttachedFile) bool {
	if f.Kind != "3d" || f.Made != "" {
		return false
	}
	switch strings.ToLower(path.Ext(f.Path)) {
	case ".glb", ".gltf", ".obj", ".fbx", ".stl", ".ply":
		return true
	}
	return false
}

type turnSettings struct {
	Frames  int     `json:"frames"`
	Px      int     `json:"px"`
	Samples int     `json:"samples"`
	Start   float64 `json:"start"`
	GPU     bool    `json:"gpu"`
}

func defaultTurn() turnSettings {
	return turnSettings{Frames: turnFrames, Px: turnPx, Samples: turnSamples, Start: turnStart, GPU: true}
}

// turnMade is .turntable.json: what the frames beside it were made from, and how.
type turnMade struct {
	Version  int          `json:"version"`
	Model    string       `json:"model"` // its path in the chat's folder
	Sum      string       `json:"sum"`   // of the model and the files it loads
	Settings turnSettings `json:"settings"`
	Frames   []string     `json:"frames"` // names in the folder
	Poster   string       `json:"poster"`
	Device   string       `json:"device,omitempty"`
	Faces    int          `json:"faces,omitempty"`
	Size     []float64    `json:"size,omitempty"` // the model's size, x y z, in its own units
	Seconds  float64      `json:"seconds"`
	At       time.Time    `json:"at"`
}

// turnResult is a turntable in the chat's folder.
type turnResult struct {
	Dir    string   // its folder, relative to the chat's
	Frames []string // relative to the chat's folder, in order
	Poster string
	Reused bool
	Made   turnMade
}

// turnProgress is how a render is going: phase "copying", "opening", "gpu" (getting
// the GPU ready, minutes the first time) or "frames" (Done of Frames).
type turnProgress struct {
	Phase       string
	Done, Total int
}

var turnOne = make(chan struct{}, 1) // one turntable at a time on this computer

// turntableBlender is the Blender turntables are made with, or why there's none.
func (a *App) turntableBlender() (string, string) {
	p := a.tools.Path("blender")
	switch {
	case p == "":
		return "", "Blender isn't installed on this computer"
	case !canSandbox():
		return "", "this computer can't run Blender in a sandbox"
	}
	return p, ""
}

func (a *App) turnCache() string { return turnCacheFor() }

var turnCacheFor = turnCacheDir // tests give their own

var (
	turnCacheOnce sync.Once
	turnCachePath string
)

// turnCacheDir is where Blender keeps the GPU kernels it compiles. Under the sandbox,
// Cycles' Metal code crashes on a cache folder whose path has a space (an uncaught
// NSURL exception) or that lies under a folder the sandbox hides, as /Users is but for
// the folders allowed (a segmentation fault): on Nov 9 the first two turntables in the
// real app died both ways, its cache being in ~/Library/Application Support. So it's
// macOS's own per-user cache folder (/var/folders/…/C, from getconf), else the temporary
// one, and only a plain path outside /Users and /Volumes; with none, each run compiles
// its kernels again.
func turnCacheDir() string {
	turnCacheOnce.Do(func() {
		var cands []string
		if runtime.GOOS == "darwin" {
			if d := strings.TrimSpace(runOut(5*time.Second, "/usr/bin/getconf", "DARWIN_USER_CACHE_DIR")); d != "" {
				cands = append(cands, filepath.Join(d, "chimera-blender-kernels"))
			}
		}
		cands = append(cands, filepath.Join(os.TempDir(), "chimera-blender-kernels"))
		for _, c := range cands {
			if cacheSafe(c) {
				turnCachePath = c
				return
			}
		}
	})
	return turnCachePath
}

// cacheSafe says whether Blender can keep its kernels at p: a plain path, outside the
// folders the sandbox hides.
func cacheSafe(p string) bool {
	if !filepath.IsAbs(p) {
		return false
	}
	for _, hidden := range []string{"/Users", "/Volumes", "/private/var/root", "/home", "/root"} {
		if p == hidden || strings.HasPrefix(p, hidden+"/") {
			return false
		}
	}
	for _, r := range p {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || strings.ContainsRune("/._-", r)) {
			return false
		}
	}
	return true
}

// renderTurntable makes a turntable of model (a path in folder) in folder, or finds
// the one already there. also names other files of its message, where an FBX's
// textures may be. progress hears how it goes (it may be nil).
func renderTurntable(ctx context.Context, blender, cache, folder, model string, also []string, set turnSettings, progress func(turnProgress)) (turnResult, error) {
	say := func(p turnProgress) {
		if progress != nil {
			progress(p)
		}
	}
	if _, err := insideFolder(folder, model); err != nil {
		return turnResult{}, errors.New("it isn't in the chat's folder any more")
	}
	needs := turnNeeds(folder, model, also)
	sum, err := turnSum(folder, append([]string{model}, needs...))
	if err != nil {
		return turnResult{}, err
	}
	dir, old, err := turnDir(folder, model)
	if err != nil {
		return turnResult{}, err
	}
	if old != nil && old.Version == turnVersion && old.Sum == sum && old.Settings == set && turnFilesThere(folder, dir, *old) {
		return turnFound(dir, *old, true), nil
	}

	say(turnProgress{Phase: "copying"})
	type runInfo struct {
		Faces  int       `json:"faces"`
		Size   []float64 `json:"size"`
		Device string    `json:"device"`
		Format string    `json:"format"`
	}
	start := time.Now()
	try := func(s turnSettings) (string, runInfo, int, error) {
		var (
			mu   sync.Mutex
			info runInfo
			done int
			slow *time.Timer
		)
		defer func() {
			mu.Lock()
			if slow != nil {
				slow.Stop()
			}
			mu.Unlock()
		}()
		opts := map[string]any{"model": "in/" + model, "out": "out", "frames": s.Frames, "px": s.Px,
			"samples": s.Samples, "start": s.Start, "gpu": s.GPU}
		run, err := turnRun(ctx, blender, cache, folder, append([]string{model}, needs...), opts, turnTimeout, func(word, arg string) {
			mu.Lock()
			defer mu.Unlock()
			switch word {
			case "imported":
				say(turnProgress{Phase: "opening"})
			case "info":
				_ = json.Unmarshal([]byte(arg), &info)
				say(turnProgress{Phase: "frames", Total: s.Frames})
				if strings.HasPrefix(info.Device, "GPU") {
					// The first frame on the GPU waits for its kernels: minutes the first time.
					slow = time.AfterFunc(20*time.Second, func() { // a warm start in the sandbox takes about 11 s
						mu.Lock()
						defer mu.Unlock()
						if done == 0 && ctx.Err() == nil {
							say(turnProgress{Phase: "gpu", Total: s.Frames})
						}
					})
				}
			case "frame":
				done++
				if slow != nil {
					slow.Stop()
				}
				say(turnProgress{Phase: "frames", Done: done, Total: s.Frames})
			}
		})
		mu.Lock()
		defer mu.Unlock()
		return run, info, done, err
	}
	run, info, done, err := try(set)
	var bs blenderStopped
	if err != nil && errors.As(err, &bs) && set.GPU && ctx.Err() == nil {
		// Blender died on the GPU (Cycles' Metal code has crashed under the sandbox
		// before): once more on the processor, slower but steadier.
		log.Printf("turntable: %s: Blender stopped on the GPU after %d of %d frames (%v); trying the CPU", model, done, set.Frames, bs.err)
		say(turnProgress{Phase: "cpu", Total: set.Frames})
		cpu := set
		cpu.GPU = false
		run, info, done, err = try(cpu)
		if err == nil {
			info.Device += ", after the GPU stopped"
		}
	}
	if err != nil {
		if errors.As(err, &bs) {
			err = fmt.Errorf("Blender stopped after %d of %d frames (%v)", done, set.Frames, bs.err)
		}
		if ctx.Err() == nil {
			log.Printf("turntable: %s: %v", model, err)
		}
		return turnResult{}, err
	}
	defer os.RemoveAll(run)

	// What it made is read outside the sandbox: plain files only, each a picture.
	ext := ".webp"
	if info.Format == "png" {
		ext = ".png"
	}
	pad := max(2, len(strconv.Itoa(set.Frames-1)))
	var names []string
	for i := 0; i < set.Frames; i++ {
		names = append(names, fmt.Sprintf("f%0*d%s", pad, i, ext))
	}
	poster := "poster" + ext
	for _, n := range append(append([]string(nil), names...), poster) {
		if !turnPicture(filepath.Join(run, "out", n)) {
			return turnResult{}, fmt.Errorf("Blender didn't write %s", n)
		}
	}
	made := turnMade{Version: turnVersion, Model: model, Sum: sum, Settings: set, Frames: names, Poster: poster,
		Device: info.Device, Faces: info.Faces, Size: info.Size, Seconds: round1(time.Since(start).Seconds()), At: time.Now().UTC()}
	if err := placeTurntable(folder, dir, filepath.Join(run, "out"), old, made); err != nil {
		return turnResult{}, err
	}
	return turnFound(dir, made, false), nil
}

// logBlenderCrash puts what Blender left about a crash in Chimera's log: its own
// crash report (blender.crash.txt in its temporary folder, the run's) or the end of
// what it printed, since the run's folder is about to go.
func logBlenderCrash(run, out string, err error) {
	text := ""
	if m, _ := filepath.Glob(filepath.Join(run, "*.crash.txt")); len(m) > 0 {
		if st, e := os.Lstat(m[0]); e == nil && st.Mode().IsRegular() {
			text = string(readHead(m[0], 4000))
		}
	}
	if text == "" {
		text = out
	}
	text = strings.TrimSpace(text)
	if len(text) > 3000 {
		text = "…" + text[len(text)-3000:]
	}
	log.Printf("turntable: Blender stopped (%v):\n%s", err, text)
}

// blenderStopped is a run that ended badly with no reason of the script's own.
type blenderStopped struct{ err error }

func (e blenderStopped) Error() string { return fmt.Sprintf("Blender stopped (%v)", e.err) }

// turnRun runs turntable.py with Blender in the sandbox, with files (paths in
// folder) copied into the run's in/ and opts after "--", and hands each "chimera-turn:"
// line to line (its first word and the rest). It gives the run's folder, for the caller
// to read out/ from and then remove; when it fails, the folder is gone already. Blender's
// compiled GPU kernels are kept in cache (the one other folder it may write).
func turnRun(ctx context.Context, blender, cache, folder string, files []string, opts map[string]any, timeout time.Duration, line func(word, arg string)) (string, error) {
	run, err := os.MkdirTemp("", "chimera-turn-*")
	if err != nil {
		return "", err
	}
	ok := false
	defer func() {
		if !ok {
			os.RemoveAll(run)
		}
	}()
	if real, err := filepath.EvalSymlinks(run); err == nil {
		run = real
	}
	for _, rel := range files {
		src, err := insideFolder(folder, rel)
		if err != nil {
			continue
		}
		dst := filepath.Join(run, "in", filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(dst), 0o700); err != nil {
			return "", err
		}
		if err := copyFile(src, dst); err != nil {
			return "", fmt.Errorf("couldn't copy %s for Blender: %v", rel, err)
		}
	}
	script := filepath.Join(run, "turntable.py")
	if err := os.WriteFile(script, []byte(turntableScript), 0o600); err != nil {
		return "", err
	}
	b, _ := json.Marshal(opts)
	args := []string{"-b", "--factory-startup", "--python-exit-code", "1", "--python", script, "--", string(b)}
	if cache != "" {
		if err := os.MkdirAll(cache, 0o700); err != nil {
			cache = ""
		}
	}
	argv, _, sandboxOK := sandboxedWith(blender, args, run, cache)
	if !sandboxOK {
		return "", errors.New("this computer can't run Blender in a sandbox")
	}
	alive, keep, err := os.Pipe()
	if err != nil {
		return "", err
	}
	defer alive.Close()
	defer keep.Close()
	cctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := watchedCommand(cctx, append([]string{"/bin/sh", "-c", watchdog, "chimera-turn"}, argv...), run, alive, keep)
	if cache != "" {
		cmd.Env = append(cmd.Env, "XDG_CACHE_HOME="+cache) // Cycles keeps its compiled kernels there
	}
	var mu sync.Mutex
	why := ""
	tail := &tailBuffer{max: 6000}
	cmd.Stdout = io.MultiWriter(tail, &lineWriter{fn: func(l string) {
		rest, ok := strings.CutPrefix(l, turnMarker)
		if !ok {
			return
		}
		word, arg, _ := strings.Cut(rest, " ")
		if word == "error" {
			mu.Lock()
			why = arg
			mu.Unlock()
		}
		if line != nil {
			line(word, arg)
		}
	}})
	cmd.Stderr = tail
	err = cmd.Run()
	killGroup(cmd)
	mu.Lock()
	reason := why
	mu.Unlock()
	switch {
	case ctx.Err() != nil:
		return "", ctx.Err()
	case cctx.Err() == context.DeadlineExceeded:
		return "", fmt.Errorf("it wasn't done after %s", timeout)
	case reason != "":
		return "", errors.New(reason)
	case err != nil:
		out := hidePaths(tail.String(), run)
		if sandboxDidNotStart(out) {
			return "", errors.New("the sandbox couldn't start Blender")
		}
		if e, ok := lastPyError(out); ok {
			return "", fmt.Errorf("Blender stopped on %s", errLine(e))
		}
		logBlenderCrash(run, out, err)
		return "", blenderStopped{err}
	}
	ok = true
	return run, nil
}

func turnFound(dir string, m turnMade, reused bool) turnResult {
	r := turnResult{Dir: dir, Poster: path.Join(dir, m.Poster), Reused: reused, Made: m}
	for _, n := range m.Frames {
		r.Frames = append(r.Frames, path.Join(dir, n))
	}
	return r
}

// turnDir is the folder a model's turntable goes in: "<its name>-turntable" beside
// it, or with a number when that name is taken by something else. A folder of ours
// for this model is used again, and its record comes back.
func turnDir(folder, model string) (string, *turnMade, error) {
	root, err := filepath.EvalSymlinks(folder)
	if err != nil {
		return "", nil, err
	}
	stem := strings.TrimSuffix(path.Base(model), path.Ext(model))
	base := path.Join(path.Dir(model), stem+"-turntable")
	for n := 1; n < 100; n++ {
		cand := base
		if n > 1 {
			cand = fmt.Sprintf("%s-%d", base, n)
		}
		full := filepath.Join(root, filepath.FromSlash(cand))
		st, err := os.Lstat(full)
		if errors.Is(err, os.ErrNotExist) {
			return cand, nil, nil
		}
		if err != nil || !st.IsDir() {
			continue
		}
		b, err := os.ReadFile(filepath.Join(full, turnRecord))
		if err != nil {
			continue // someone else's folder
		}
		var m turnMade
		if json.Unmarshal(b, &m) == nil && m.Model == model {
			return cand, &m, nil
		}
	}
	return "", nil, errors.New("too many turntable folders beside it")
}

func turnFilesThere(folder, dir string, m turnMade) bool {
	if len(m.Frames) == 0 || m.Poster == "" {
		return false
	}
	for _, n := range append(append([]string(nil), m.Frames...), m.Poster) {
		full, err := insideFolder(folder, path.Join(dir, n))
		if err != nil {
			return false
		}
		if st, err := os.Stat(full); err != nil || !st.Mode().IsRegular() || st.Size() == 0 {
			return false
		}
	}
	return true
}

// turnPicture says whether a file Blender made is a plain WebP or PNG file of a sane size.
func turnPicture(p string) bool {
	st, err := os.Lstat(p)
	if err != nil || !st.Mode().IsRegular() || st.Size() < 16 || st.Size() > turnFileMax {
		return false
	}
	head := readHead(p, 16)
	return (len(head) >= 12 && string(head[0:4]) == "RIFF" && string(head[8:12]) == "WEBP") || bytes.HasPrefix(head, []byte("\x89PNG\r\n\x1a\n"))
}

// placeTurntable moves the frames into the chat's folder, in place of the ones made
// there before for this model (old), and writes the record beside them.
func placeTurntable(folder, dir, from string, old *turnMade, made turnMade) error {
	root, err := filepath.EvalSymlinks(folder)
	if err != nil {
		return err
	}
	full := filepath.Join(root, filepath.FromSlash(dir))
	if err := os.MkdirAll(full, 0o755); err != nil {
		return err
	}
	if real, err := filepath.EvalSymlinks(full); err != nil || !strings.HasPrefix(real, root+string(filepath.Separator)) {
		return errors.New("its folder leads out of the chat's folder")
	}
	if old != nil {
		for _, n := range append(append([]string(nil), old.Frames...), old.Poster) {
			if n != "" && !strings.ContainsAny(n, `/\`) && !strings.HasPrefix(n, ".") {
				_ = os.Remove(filepath.Join(full, n))
			}
		}
	}
	_ = os.Remove(filepath.Join(full, turnRecord))
	for _, n := range append(append([]string(nil), made.Frames...), made.Poster) {
		dst := filepath.Join(full, n)
		if st, err := os.Lstat(dst); err == nil && !st.Mode().IsRegular() {
			return fmt.Errorf("%s in its folder isn't a plain file", n)
		}
		_ = os.Remove(dst)
		if err := moveFile(filepath.Join(from, n), dst); err != nil {
			return fmt.Errorf("couldn't put %s in the chat's folder: %v", n, err)
		}
	}
	b, _ := json.MarshalIndent(made, "", " ")
	return os.WriteFile(filepath.Join(full, turnRecord), b, 0o644)
}

// turnSum is a hash of the files (paths in folder) and their bytes.
func turnSum(folder string, rels []string) (string, error) {
	h := sha256.New()
	for _, rel := range rels {
		full, err := insideFolder(folder, rel)
		if err != nil {
			return "", fmt.Errorf("%s isn't in the chat's folder", rel)
		}
		f, err := os.Open(full)
		if err != nil {
			return "", err
		}
		fmt.Fprintf(h, "%s\x00", rel)
		_, err = io.Copy(h, f)
		f.Close()
		if err != nil {
			return "", err
		}
		h.Write([]byte{0})
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// turnNeeds lists the files a model loads from beside it that are in folder (paths
// relative to it): an OBJ's materials and their textures, a glTF's buffers and
// textures, and for an FBX, which names its textures in ways that vary, the pictures
// among also that are in its folder or under it.
func turnNeeds(folder, model string, also []string) []string {
	seen := map[string]bool{strings.ToLower(model): true}
	var out []string
	add := func(from, ref string) string {
		ref = strings.TrimSpace(strings.ReplaceAll(ref, `\`, "/"))
		if ref == "" || strings.HasPrefix(ref, "data:") {
			return ""
		}
		for _, cand := range []string{path.Join(path.Dir(from), ref), path.Join(path.Dir(from), path.Base(ref))} {
			cand = path.Clean(cand)
			if cand == ".." || strings.HasPrefix(cand, "../") || strings.HasPrefix(cand, "/") {
				continue
			}
			full, err := insideFolder(folder, cand)
			if err != nil {
				continue
			}
			if st, err := os.Stat(full); err != nil || !st.Mode().IsRegular() {
				continue
			}
			if !seen[strings.ToLower(cand)] {
				seen[strings.ToLower(cand)] = true
				out = append(out, cand)
			}
			return cand
		}
		return ""
	}
	full, err := insideFolder(folder, model)
	if err != nil {
		return nil
	}
	switch strings.ToLower(path.Ext(model)) {
	case ".obj":
		for _, lib := range objLibs(full) {
			if mtl := add(model, lib); mtl != "" {
				if mfull, err := insideFolder(folder, mtl); err == nil {
					for _, tex := range mtlMaps(mfull) {
						add(mtl, tex)
					}
				}
			}
		}
	case ".gltf", ".glb":
		for _, u := range gltfURIs(full) {
			if v, err := url.PathUnescape(u); err == nil {
				u = v
			}
			add(model, u)
		}
	case ".fbx":
		dir := path.Dir(model)
		for _, p := range also {
			switch {
			case !isTexture(p):
			case dir == ".":
				add(model, p)
			case strings.HasPrefix(p, dir+"/"):
				add(model, strings.TrimPrefix(p, dir+"/"))
			}
		}
	}
	sort.Strings(out)
	return out
}

func isTexture(p string) bool {
	switch strings.ToLower(path.Ext(p)) {
	case ".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".bmp", ".exr", ".hdr", ".webp":
		return true
	}
	return false
}

// objLibs are the materials files an OBJ names (its mtllib lines).
func objLibs(full string) []string {
	f, err := os.Open(full)
	if err != nil {
		return nil
	}
	defer f.Close()
	var out []string
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 64<<10), 8<<20)
	for sc.Scan() {
		line := bytes.TrimSpace(sc.Bytes())
		if bytes.HasPrefix(line, []byte("mtllib")) && len(line) > 7 && (line[6] == ' ' || line[6] == '\t') {
			// Blender reads the rest of the line as one name (it may have spaces);
			// the format says names; only the ones that are there are used.
			rest := strings.TrimSpace(string(line[7:]))
			out = append(out, rest)
			if f := strings.Fields(rest); len(f) > 1 {
				out = append(out, f...)
			}
		}
	}
	return out
}

// mtlMaps are the pictures a materials file names.
func mtlMaps(full string) []string {
	b, err := os.ReadFile(full)
	if err != nil || len(b) > 16<<20 {
		return nil
	}
	var out []string
	for _, line := range strings.Split(string(b), "\n") {
		fs := strings.Fields(line)
		if len(fs) < 2 {
			continue
		}
		if k := strings.ToLower(fs[0]); strings.HasPrefix(k, "map_") || k == "bump" || k == "disp" || k == "decal" || k == "norm" || k == "refl" {
			if name := mtlMapName(fs); name != "" {
				out = append(out, name)
			}
		}
	}
	return out
}

// gltfURIs are the files a glTF model (a .gltf's JSON or a .glb's) names: its buffers and images.
func gltfURIs(full string) []string {
	head := readHead(full, 20)
	var js []byte
	if bytes.HasPrefix(head, []byte("glTF")) {
		if len(head) < 20 || string(head[16:20]) != "JSON" {
			return nil
		}
		n := int(binary.LittleEndian.Uint32(head[12:]))
		if n <= 0 || n > 64<<20 {
			return nil
		}
		f, err := os.Open(full)
		if err != nil {
			return nil
		}
		js = make([]byte, n)
		_, err = f.ReadAt(js, 20)
		f.Close()
		if err != nil {
			return nil
		}
	} else {
		b, err := os.ReadFile(full)
		if err != nil || len(b) > 64<<20 {
			return nil
		}
		js = b
	}
	var d struct {
		Buffers []struct {
			URI string `json:"uri"`
		} `json:"buffers"`
		Images []struct {
			URI string `json:"uri"`
		} `json:"images"`
	}
	if json.Unmarshal(js, &d) != nil {
		return nil
	}
	var out []string
	for _, b := range d.Buffers {
		out = append(out, b.URI)
	}
	for _, im := range d.Images {
		out = append(out, im.URI)
	}
	return out
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.OpenFile(dst, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		return err
	}
	return out.Close()
}

// lineWriter hands each line written to it to fn (Blender's output, as it comes).
type lineWriter struct {
	mu  sync.Mutex
	buf []byte
	fn  func(string)
}

func (w *lineWriter) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.buf = append(w.buf, p...)
	for {
		i := bytes.IndexByte(w.buf, '\n')
		if i < 0 {
			break
		}
		line := strings.TrimRight(string(w.buf[:i]), "\r")
		w.buf = w.buf[i+1:]
		w.fn(line)
	}
	if len(w.buf) > 64<<10 { // a very long line with no end yet: only its end matters
		w.buf = append([]byte(nil), w.buf[len(w.buf)-4096:]...)
	}
	return len(p), nil
}

// turnWords says what a turntable's frames are, for what the model is told: which
// model they show, and how far apart they are.
func turnWords(model string, frames int) string {
	deg := trimZero(strconv.FormatFloat(360/float64(frames), 'f', 2, 64))
	deg = strings.TrimSuffix(strings.TrimRight(deg, "0"), ".")
	return fmt.Sprintf("A turntable of `%s` that Chimera rendered: one full turn in %d frames, %s° apart, so frame n is n × %s° on from frame 0, a three-quarter view; "+
		"as the number goes up it turns counterclockwise seen from above (its near side moves right); a soft shadow under it, the rest see-through. "+
		"A page can spin it by showing one frame at a time (preload them; a scroll or a drag picks the frame)", model, frames, deg, deg)
}

// runTurntableCLI is chimera --turntable: a turntable of one model file, made as a
// chat makes one, beside it.
func runTurntableCLI(dataDir, model string) int {
	full, err := filepath.Abs(model)
	if err != nil {
		fmt.Fprintln(os.Stderr, "turntable:", err)
		return 2
	}
	if st, err := os.Stat(full); err != nil || !st.Mode().IsRegular() {
		fmt.Fprintln(os.Stderr, "turntable: no such file:", model)
		return 2
	}
	blender, _ := findBlender()
	if p := os.Getenv("CHIMERA_TEST_BLENDER"); p != "" {
		blender = p
	}
	if blender == "" {
		fmt.Fprintln(os.Stderr, "turntable: Blender isn't installed here")
		return 2
	}
	set := defaultTurn()
	if v, err := strconv.Atoi(os.Getenv("CHIMERA_TURN_FRAMES")); err == nil && v >= 4 && v <= 720 {
		set.Frames = v
	}
	if v, err := strconv.Atoi(os.Getenv("CHIMERA_TURN_PX")); err == nil && v >= 32 && v <= 4096 {
		set.Px = v
	}
	if v, err := strconv.Atoi(os.Getenv("CHIMERA_TURN_SAMPLES")); err == nil && v >= 1 && v <= 4096 {
		set.Samples = v
	}
	if os.Getenv("CHIMERA_TURN_CPU") == "1" {
		set.GPU = false
	}
	last := ""
	res, err := renderTurntable(context.Background(), blender, turnCacheDir(), filepath.Dir(full), filepath.Base(full), nil, set,
		func(p turnProgress) {
			if s := turnStatus(filepath.Base(full), p, 1, 1); s != last {
				last = s
				fmt.Fprintln(os.Stderr, s)
			}
		})
	if err != nil {
		fmt.Fprintln(os.Stderr, "turntable:", err)
		return 1
	}
	b, _ := json.MarshalIndent(map[string]any{"folder": filepath.Join(filepath.Dir(full), filepath.FromSlash(res.Dir)), "frames": len(res.Frames),
		"poster": res.Poster, "reused": res.Reused, "made": res.Made}, "", "  ")
	fmt.Println(string(b))
	return 0
}

// turnStatus is the line a reply shows while a turntable is made.
func turnStatus(model string, p turnProgress, n, of int) string {
	which := "a turntable of " + model
	if of > 1 {
		which = fmt.Sprintf("turntable %d of %d (%s)", n, of, model)
	}
	switch p.Phase {
	case "copying", "opening":
		return "Opening " + model + " in Blender for " + which + "…"
	case "gpu":
		return "Getting Blender ready to render on the GPU for " + which + " (the first time on this computer takes a few minutes)…"
	case "cpu":
		return "Blender stopped on the GPU, so rendering " + which + " on the processor instead (slower)…"
	case "frames":
		return fmt.Sprintf("Rendering %s: frame %d of %d…", which, p.Done, p.Total)
	}
	return "Making " + which + "…"
}
