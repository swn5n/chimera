package main

// Detects the "tools" a computer has beyond plain chat: models with vision,
// audio, image generation or embeddings in Ollama, and apps like Blender,
// ComfyUI (images, video, 3D meshes, audio), ffmpeg, Whisper and Python.

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"sync"
	"time"
)

type ToolInfo struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	Label    string `json:"label,omitempty"` // short "best for" tag when present
	Have     bool   `json:"have"`
	Via      string `json:"via,omitempty"`
	Note     string `json:"note,omitempty"`
	Lendable bool   `json:"lendable"`
	GetURL   string `json:"get_url,omitempty"`
	Path     string `json:"-"`
}

type ToolScanner struct {
	app  *App
	mu   sync.Mutex
	ext  map[string]ToolInfo // apps found on disk / running
	last time.Time
	kick chan struct{}
}

func NewToolScanner(app *App) *ToolScanner {
	return &ToolScanner{app: app, ext: map[string]ToolInfo{}, kick: make(chan struct{}, 1)}
}

func (t *ToolScanner) Kick() {
	select {
	case t.kick <- struct{}{}:
	default:
	}
}

func (t *ToolScanner) loop() {
	for {
		t.scan()
		select {
		case <-t.app.quit:
			return
		case <-time.After(60 * time.Second):
		case <-t.kick:
		}
	}
}

func (t *ToolScanner) scan() {
	found := map[string]ToolInfo{}
	if p, v := findBlender(); p != "" {
		found["blender"] = ToolInfo{ID: "blender", Name: "Blender", Have: true, Via: v, Path: p}
	}
	for id, info := range scanComfy() {
		found[id] = info
	}
	if p := findBinary([]string{"ffmpeg"}, []string{"/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"}); p != "" {
		found["ffmpeg"] = ToolInfo{ID: "ffmpeg", Name: "ffmpeg", Have: true, Via: filepath.Base(p), Path: p}
	}
	if p := findBinary([]string{"whisper-cli", "whisper-cpp", "mlx_whisper", "whisper"}, []string{"/opt/homebrew/bin/whisper-cli", "/opt/homebrew/bin/whisper-cpp"}); p != "" {
		found["whisper"] = ToolInfo{ID: "whisper", Name: "Speech to text", Have: true, Via: filepath.Base(p), Path: p}
	}
	if p := findBinary([]string{"piper", "kokoro-tts"}, nil); p != "" {
		found["tts"] = ToolInfo{ID: "tts", Name: "Text to speech", Have: true, Via: filepath.Base(p), Path: p}
	}
	if p := findPython(); p != "" {
		found["python"] = ToolInfo{ID: "python", Name: "Python", Have: true, Via: p, Path: p}
	}
	t.mu.Lock()
	changed := len(found) != len(t.ext)
	for k, v := range found {
		if old, ok := t.ext[k]; !ok || old.Via != v.Via {
			changed = true
		}
	}
	t.ext = found
	t.last = time.Now()
	t.mu.Unlock()
	if changed {
		t.app.notify()
	}
}

func (t *ToolScanner) Path(id string) string {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.ext[id].Path
}

// List merges what Ollama's models can do with the apps found on disk.
func (t *ToolScanner) List() []ToolInfo {
	models := t.app.ollama.State().Models
	byCap := func(test func(ModelInfo) bool) string {
		var names []string
		for _, m := range models {
			if test(m) {
				names = append(names, m.Name)
			}
		}
		return strings.Join(names, ", ")
	}
	t.mu.Lock()
	ext := map[string]ToolInfo{}
	for k, v := range t.ext {
		ext[k] = v
	}
	t.mu.Unlock()
	comfy := ext["comfyui"]
	isMac := runtime.GOOS == "darwin"
	ollamaModel := func(id, name, label string, test func(ModelInfo) bool, get string) ToolInfo {
		via := byCap(test)
		return ToolInfo{ID: id, Name: name, Label: label, Have: via != "", Via: via, Lendable: true, GetURL: get}
	}
	out := []ToolInfo{
		ollamaModel("vision", "Vision (understands images)", "Vision", func(m ModelInfo) bool { return m.HasCap("vision") }, ""),
		ollamaModel("audio", "Audio input", "Audio", func(m ModelInfo) bool { return m.HasCap("audio") }, ""),
		ollamaModel("coding", "Coding models", "Coding", isCoder, ""),
		ollamaModel("embeddings", "Embeddings (search)", "Embeddings", func(m ModelInfo) bool { return m.HasCap("embedding") }, ""),
	}
	img := ollamaModel("image_gen", "Image generation", "Images", func(m ModelInfo) bool { return m.HasCap("image") }, "")
	if !img.Have && comfy.Have && strings.Contains(comfy.Note, "images") {
		img.Have, img.Via = true, "ComfyUI"
	}
	if !img.Have {
		if isMac {
			img.Note = "Download x/z-image-turbo (13 GB) in Models, or run ComfyUI."
		} else {
			img.Note = "Run ComfyUI with an image model. Ollama's image models are Mac-only for now."
			img.GetURL = "https://www.comfy.org/download"
		}
	}
	out = append(out, img)
	comfyTool := func(id, name, label, word string) ToolInfo {
		ti := ToolInfo{ID: id, Name: name, Label: label, Lendable: true}
		if comfy.Have && strings.Contains(comfy.Note, word) {
			ti.Have, ti.Via = true, "ComfyUI"
		} else {
			ti.Note = "Needs ComfyUI with " + word + " nodes, running on this computer."
			ti.GetURL = "https://www.comfy.org/download"
		}
		return ti
	}
	out = append(out,
		comfyTool("video_gen", "Video generation", "Video", "video"),
		comfyTool("mesh_gen", "3D mesh generation", "3D meshes", "3D"),
		comfyTool("audio_gen", "Audio generation", "Audio generation", "audio"),
	)
	if tts, ok := ext["tts"]; ok {
		for i := range out {
			if out[i].ID == "audio_gen" && !out[i].Have {
				out[i].Have, out[i].Via, out[i].Note, out[i].GetURL = true, tts.Via, "", ""
			}
		}
	}
	blender := ext["blender"]
	blender.ID, blender.Name, blender.Label, blender.Lendable = "blender", "Blender", "Blender", true
	if !blender.Have {
		blender.GetURL = "https://www.blender.org/download/"
		blender.Note = "Install Blender to let Chimera test and build Blender scripts here."
	}
	out = append(out, blender)
	cu := ToolInfo{ID: "computer_use", Name: "Computer use", Lendable: false,
		Note: "Never lent to the network: a friend's job should never control your computer."}
	if v := byCap(func(m ModelInfo) bool { return m.HasCap("vision") && m.HasCap("tools") }); v != "" {
		cu.Have, cu.Via = true, v
	}
	out = append(out, cu)
	for _, id := range []string{"comfyui", "ffmpeg", "whisper", "python"} {
		if ti, ok := ext[id]; ok {
			ti.Lendable = id != "python"
			out = append(out, ti)
		}
	}
	return out
}

func isCoder(m ModelInfo) bool {
	n := strings.ToLower(m.Name)
	return strings.Contains(n, "coder") || strings.Contains(n, "codestral") || strings.Contains(n, "devstral") ||
		strings.Contains(n, "-coding") || strings.Contains(n, "codegemma") || strings.Contains(n, "starcoder")
}

func findBinary(names, extra []string) string {
	for _, n := range names {
		if p, err := exec.LookPath(n); err == nil {
			return p
		}
	}
	for _, p := range extra {
		if fileExists(p) {
			return p
		}
	}
	return ""
}

var blenderVersion = regexp.MustCompile(`Blender (\d+\.\d+(\.\d+)?)`)

func findBlender() (path, version string) {
	var cands []string
	switch runtime.GOOS {
	case "darwin":
		cands = []string{"/Applications/Blender.app/Contents/MacOS/Blender", filepath.Join(homeDir(), "Applications/Blender.app/Contents/MacOS/Blender")}
	case "windows":
		matches, _ := filepath.Glob(filepath.Join(os.Getenv("ProgramFiles"), "Blender Foundation", "Blender*", "blender.exe"))
		sort.Sort(sort.Reverse(sort.StringSlice(matches)))
		cands = matches
	default:
		cands = []string{"/snap/bin/blender", "/usr/bin/blender", "/usr/local/bin/blender"}
	}
	if p, err := exec.LookPath("blender"); err == nil {
		cands = append([]string{p}, cands...)
	}
	for _, p := range cands {
		if !fileExists(p) {
			continue
		}
		out := runOut(8*time.Second, p, "--version")
		if m := blenderVersion.FindStringSubmatch(out); m != nil {
			return p, "Blender " + m[1]
		}
		return p, "Blender"
	}
	return "", ""
}

// findPython returns a Python 3 that actually works (not a store/installer stub).
func findPython() string {
	var cands []string
	switch runtime.GOOS {
	case "darwin":
		cands = []string{"/opt/homebrew/bin/python3", "/usr/local/bin/python3"}
		if runOut(3*time.Second, "xcode-select", "-p") != "" {
			cands = append(cands, "/usr/bin/python3") // only real when the developer tools are installed
		}
	case "windows":
		if p, err := exec.LookPath("py"); err == nil {
			if strings.HasPrefix(runOut(5*time.Second, p, "-3", "--version"), "Python 3") {
				return p
			}
		}
		cands = []string{"python3", "python"}
	default:
		cands = []string{"python3"}
	}
	for _, c := range cands {
		p := c
		if !filepath.IsAbs(c) {
			lp, err := exec.LookPath(c)
			if err != nil {
				continue
			}
			p = lp
		} else if !fileExists(c) {
			continue
		}
		if strings.HasPrefix(runOut(5*time.Second, p, "--version"), "Python 3") {
			return p
		}
	}
	return ""
}

// scanComfy looks for a running ComfyUI and guesses what it can make from its nodes.
func scanComfy() map[string]ToolInfo {
	out := map[string]ToolInfo{}
	c := http.Client{Timeout: 1500 * time.Millisecond, Transport: sharedTransport}
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET", "http://127.0.0.1:8188/system_stats", nil)
	resp, err := c.Do(req)
	if err != nil {
		return out
	}
	resp.Body.Close()
	if resp.StatusCode != 200 {
		return out
	}
	req2, _ := http.NewRequestWithContext(ctx, "GET", "http://127.0.0.1:8188/object_info", nil)
	c.Timeout = 4 * time.Second
	resp2, err := c.Do(req2)
	var nodes map[string]json.RawMessage
	if err == nil {
		b, _ := io.ReadAll(io.LimitReader(resp2.Body, 64<<20))
		resp2.Body.Close()
		_ = json.Unmarshal(b, &nodes)
	}
	var can []string
	has := func(words ...string) bool {
		for name := range nodes {
			ln := strings.ToLower(name)
			for _, w := range words {
				if strings.Contains(ln, w) {
					return true
				}
			}
		}
		return false
	}
	if has("ksampler", "samplercustom") {
		can = append(can, "images")
	}
	if has("wanimagetovideo", "wanvideo", "ltxv", "hunyuanvideo", "savevideo", "savewebm", "createvideo", "cosmos") {
		can = append(can, "video")
	}
	if has("hunyuan3d", "triposr", "trellis", "saveglb", "stablefast3d") {
		can = append(can, "3D")
	}
	if has("stableaudio", "acestep", "emptylatentaudio", "saveaudio") {
		can = append(can, "audio")
	}
	out["comfyui"] = ToolInfo{ID: "comfyui", Name: "ComfyUI", Have: true, Via: "running on port 8188", Note: strings.Join(can, ", ")}
	return out
}
