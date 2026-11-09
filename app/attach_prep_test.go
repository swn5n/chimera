package main

import (
	"bytes"
	"encoding/json"
	"image/color"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// eyes is a stand-in Ollama with qwen3.8:27b: it answers every picture with the
// same description and counts what it's asked.
type eyes struct {
	mu      sync.Mutex
	asked   int
	unloads int
	srv     *httptest.Server
}

func newEyes(t *testing.T) *eyes {
	e := &eyes{}
	e.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/version":
			w.Write([]byte(`{"version":"0.40.1"}`))
		case "/api/tags":
			w.Write([]byte(`{"models":[{"name":"qwen3.8:27b","model":"qwen3.8:27b","size":18000000000,"digest":"abc","details":{"parameter_size":"27.8B"}}]}`))
		case "/api/show":
			w.Write([]byte(`{"capabilities":["completion","vision"],"model_info":{}}`))
		case "/api/ps":
			w.Write([]byte(`{"models":[]}`))
		case "/api/generate":
			var req map[string]any
			json.NewDecoder(r.Body).Decode(&req)
			if req["keep_alive"] == float64(0) {
				e.mu.Lock()
				e.unloads++
				e.mu.Unlock()
			}
			w.Write([]byte(`{"done":true}`))
		case "/api/chat":
			var req struct {
				Messages []struct {
					Images []string `json:"images"`
				} `json:"messages"`
			}
			json.NewDecoder(r.Body).Decode(&req)
			e.mu.Lock()
			e.asked++
			e.mu.Unlock()
			w.Write([]byte(`{"message":{"role":"assistant","content":"{\"shows\":\"an orange stock picker\",\"kind\":\"render\",\"words\":\"\",\"tone\":\"mixed\",\"text_space\":\"the empty right side\"}"}}`))
		}
	}))
	t.Cleanup(e.srv.Close)
	return e
}

func (e *eyes) counts() (int, int) {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.asked, e.unloads
}

// prepApp is an engine app (engines_test.go) with the stand-in Ollama and Blender.
func prepApp(t *testing.T) (*App, string, *eyes, func(string, []byte) chatAttachment) {
	home := t.TempDir()
	os.MkdirAll(filepath.Join(home, "Documents"), 0o755)
	t.Setenv("HOME", home)
	a, logPath := engineApp(t, nil)
	e := newEyes(t)
	a.ollama = NewOllamaMonitor(a, e.srv.URL)
	a.sysMu.Lock()
	a.sys = detectSysInfo()
	a.sysMu.Unlock()
	a.ollama.check()
	a.tools.ext["blender"] = ToolInfo{ID: "blender", Have: true, Path: fakeTurnBlender(t), Version: "Blender 5.2.2"}
	cache := t.TempDir() // not this computer's real kernel cache
	turnCacheFor = func() string { return cache }
	t.Cleanup(func() { turnCacheFor = turnCacheDir })
	mux := http.NewServeMux()
	mux.HandleFunc("POST /api/uploads", a.handleUpload)
	up := func(name string, data []byte) chatAttachment {
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, httptest.NewRequest("POST", "/api/uploads?name="+url.QueryEscape(name), bytes.NewReader(data)))
		var r struct{ ID string }
		if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &r) != nil {
			t.Fatalf("upload %s: %d %s", name, w.Code, w.Body)
		}
		return chatAttachment{Upload: r.ID, Path: name}
	}
	return a, logPath, e, up
}

func TestAnEngineChatTurnsItsModelsAndDescribesItsPictures(t *testing.T) {
	a, logPath, e, up := prepApp(t)
	if _, ok := a.describeModel(); !ok {
		t.Fatal("the stand-in's qwen3.8:27b should be the one to describe")
	}
	spin := []chatAttachment{}
	for _, n := range []string{"00", "01", "02", "03", "04", "05"} {
		spin = append(spin, up("spin/f"+n+".png", pngOf(t, flat(40, 40, color.NRGBA{200, 90, 20, 255}))))
	}
	atts := append([]chatAttachment{
		up("machines/x.obj", []byte("mtllib x.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")),
		up("machines/x.mtl", []byte("newmtl a\nmap_Kd tex.png\n")),
		up("machines/tex.png", pngOf(t, flat(16, 16, color.NRGBA{250, 120, 0, 255}))),
		up("logo.png", pngOf(t, logoOn(60, 30, color.NRGBA{255, 255, 255, 255}))),
	}, spin...)
	gen, err := a.gens.Start(chatReq{Message: "Build a page for the picker", Model: "engine:fake", Thinking: "off", Attachments: atts})
	if err != nil {
		t.Fatal(err)
	}
	past, ch := gen.Subscribe()
	var statuses []string
	var gotAttached bool
	done := make(chan struct{})
	go func() {
		defer close(done)
		for _, ev := range past {
			statuses = append(statuses, ev.Reason)
		}
		for ev := range ch {
			if ev.Type == "status" {
				statuses = append(statuses, ev.Reason)
			}
			gotAttached = gotAttached || ev.Type == "attached"
		}
	}()
	waitSaved(t, a, gen)
	<-done
	sess, _ := a.sessions.Get(gen.sessionID)
	m, reply := sess.Messages[0], sess.Messages[1]
	if reply.Status != "" || reply.Content != "Hello there." || reply.Note != "" {
		t.Fatalf("the reply: %+v", reply)
	}
	byPath := map[string]AttachedFile{}
	for _, f := range m.Attached {
		byPath[f.Path] = f
	}
	if f := byPath["machines/x.obj"]; f.Turntable != "machines/x-turntable" || f.NoTurn != "" {
		t.Fatalf("the model: %+v", f)
	}
	if f := byPath["machines/x-turntable/f71.webp"]; f.Made != "turntable" || f.From != "machines/x.obj" || f.Kind != "picture" || f.Bytes == 0 {
		t.Fatalf("a frame: %+v", f)
	}
	if f := byPath["machines/x-web.glb"]; f.Made != "glb" || f.From != "machines/x.obj" || f.Kind != "3d" || byPath["machines/x.obj"].GLB != "machines/x-web.glb" {
		t.Fatalf("the GLB for pages: %+v", f)
	}
	if len(m.Attached) != 4+6+73+1 || !fileExists(filepath.Join(m.AttachedIn, "machines", "x-turntable", "poster.webp")) || !fileExists(filepath.Join(m.AttachedIn, "machines", "x-web.glb")) {
		t.Fatalf("%d files", len(m.Attached))
	}
	// One look per line of the list: the texture, the logo, the run's first frame and the turntable's.
	asked, unloads := e.counts()
	if asked != 4 || unloads != 1 {
		t.Fatalf("asked %d times, unloaded %d", asked, unloads)
	}
	for _, p := range []string{"machines/tex.png", "logo.png", "spin/f00.png", "machines/x-turntable/f00.webp"} {
		if !strings.HasSuffix(byPath[p].Shows, "an orange stock picker; room for a heading: the empty right side") {
			t.Errorf("%s: %q", p, byPath[p].Shows)
		}
	}
	if byPath["spin/f01.png"].Shows != "" || byPath["machines/x-turntable/poster.webp"].Shows != "" {
		t.Error("a run's later frames and the poster aren't looked at")
	}
	if !strings.HasPrefix(byPath["logo.png"].Shows, "render, light: ") || !strings.HasPrefix(byPath["spin/f00.png"].Shows, "render, mid-toned: ") {
		t.Errorf("measured tones: %q %q", byPath["logo.png"].Shows, byPath["spin/f00.png"].Shows)
	}
	for _, want := range []string{
		"Attached files: 10 (",
		", with 73 pictures and 1 GLB Chimera made from them (",
		"): 1 turntable and 1 copy for web pages.",
		"- `machines/x-web.glb`: 3D model, glTF binary (.glb), ",
		"Load this one in a page, not `x.obj`",
		"- `machines/x-turntable/f00.webp` to `machines/x-turntable/f71.webp`: 72 pictures, WebP, 800 × 800, transparent background",
		"A turntable of `machines/x.obj` that Chimera rendered",
		"What `f00.webp` shows: render",
		"- `spin/f00.png` to `spin/f05.png`: 6 pictures, PNG, 40 × 40",
		"What `f00.png` shows: render, mid-toned: an orange stock picker",
		"- `logo.png`: picture, PNG, 60 × 30, transparent background, ",
		"The \"what it shows\" parts were written by qwen3.8:27b, a vision model on this computer",
	} {
		if !strings.Contains(m.FilesNote, want) {
			t.Errorf("missing %q in:\n%s", want, m.FilesNote)
		}
	}
	msgs := lastRequest(t, logPath)["messages"].([]any)
	if got := msgs[len(msgs)-1].(map[string]any)["content"].(string); got != "Build a page for the picker\n\n"+m.FilesNote {
		t.Fatalf("the engine got %q", got)
	}
	joined := strings.Join(statuses, "\n")
	if !gotAttached || !strings.Contains(joined, "Saving x.obj as a GLB for web pages (1 of 1)…") || !strings.Contains(joined, "Rendering a turntable of x.obj: frame 72 of 72…") || !strings.Contains(joined, "Looking at your pictures with qwen3.8:27b: 4 of 4…") {
		t.Fatalf("attached %v, statuses:\n%s", gotAttached, joined)
	}

	// The same logo again, in a new message: what it shows is remembered, not asked again.
	g1, err := a.gens.Start(chatReq{SessionID: sess.ID, Message: "again", Model: "engine:fake", Thinking: "off",
		Attachments: []chatAttachment{up("logo-again.png", pngOf(t, logoOn(60, 30, color.NRGBA{255, 255, 255, 255})))}})
	if err != nil {
		t.Fatal(err)
	}
	waitSaved(t, a, g1)
	sess, _ = a.sessions.Get(sess.ID)
	if m := sess.Messages[2]; len(m.Attached) != 1 || m.Attached[0].Shows != byPath["logo.png"].Shows || !strings.Contains(m.FilesNote, "written by qwen3.8:27b") {
		t.Fatalf("again: %+v", m)
	}
	if n, _ := e.counts(); n != asked {
		t.Fatalf("a picture looked at before was asked about again (%d asks)", n)
	}
	sess.Messages = sess.Messages[:2] // the parts below count from here
	if err := a.sessions.Save(sess); err != nil {
		t.Fatal(err)
	}

	// All switched off: nothing made, nothing looked at.
	g2, err := a.gens.Start(chatReq{SessionID: sess.ID, Message: "and this", Model: "engine:fake", Thinking: "off", Turntables: new(bool), Describe: new(bool), WebGLB: new(bool),
		Attachments: []chatAttachment{up("z.stl", []byte("solid z\nendsolid z\n")), up("z.png", pngOf(t, flat(8, 8, color.NRGBA{0, 0, 0, 255})))}})
	if err != nil {
		t.Fatal(err)
	}
	waitSaved(t, a, g2)
	sess, _ = a.sessions.Get(sess.ID)
	if m := sess.Messages[2]; len(m.Attached) != 2 || m.Attached[0].Turntable != "" || m.Attached[0].GLB != "" || strings.Contains(m.FilesNote, "what it shows") ||
		fileExists(filepath.Join(m.AttachedIn, "z-turntable")) || fileExists(filepath.Join(m.AttachedIn, "z-web.glb")) {
		t.Fatalf("switched off: %+v", m)
	}
	if asked2, _ := e.counts(); asked2 != asked {
		t.Fatal("a picture was looked at with the switch off")
	}

	// With the engine running and no room beside it, pictures aren't looked at, and the reply says why.
	defer func(f func() (int64, bool)) { freeMemoryNow = f }(freeMemoryNow)
	freeMemoryNow = func() (int64, bool) { return 3 << 30, true }
	if !a.engines.Running("fake") {
		t.Fatal("the engine should still be running")
	}
	g3, err := a.gens.Start(chatReq{SessionID: sess.ID, Message: "one more", Model: "engine:fake", Thinking: "off",
		Attachments: []chatAttachment{up("w.png", pngOf(t, flat(8, 8, color.NRGBA{255, 255, 255, 255})))}})
	if err != nil {
		t.Fatal(err)
	}
	waitSaved(t, a, g3)
	sess, _ = a.sessions.Get(sess.ID)
	if r := sess.Messages[5]; !strings.HasPrefix(r.Note, "Pictures not described: Fake Flash was running and there wasn't room for qwen3.8:27b beside it (it needs about") || !strings.Contains(r.Note, "3 GB is free") {
		t.Fatalf("no room: %q", r.Note)
	}
	if m := sess.Messages[4]; !strings.Contains(m.FilesNote, "Only these facts about the picture come with this message") {
		t.Fatalf("no room, the note: %s", m.FilesNote)
	}
	if asked3, _ := e.counts(); asked3 != asked {
		t.Fatal("a picture was looked at with no room")
	}
}

func TestStopWhileATurntableIsMadeStopsTheReplyAndKeepsTheMessage(t *testing.T) {
	a, logPath, _, up := prepApp(t)
	gen, err := a.gens.Start(chatReq{Message: "spin it", Model: "engine:fake", Thinking: "off", Describe: new(bool), WebGLB: new(bool),
		Attachments: []chatAttachment{up("slow.stl", []byte("solid s\nendsolid s\n"))}})
	if err != nil {
		t.Fatal(err)
	}
	past, ch := gen.Subscribe()
	stopped := make(chan struct{})
	go func() {
		defer close(stopped)
		for _, ev := range past {
			_ = ev
		}
		once := false
		for ev := range ch {
			if ev.Type == "status" && strings.Contains(ev.Reason, "frame 2 of 72") && !once {
				once = true
				a.gens.Cancel(gen.id)
			}
		}
	}()
	start := time.Now()
	waitSaved(t, a, gen)
	<-stopped
	if took := time.Since(start); took > 10*time.Second {
		t.Fatalf("stopping took %s", took)
	}
	sess, _ := a.sessions.Get(gen.sessionID)
	if r := sess.Messages[1]; r.Status != "cancelled" {
		t.Fatalf("the reply: %+v", r)
	}
	m := sess.Messages[0]
	if len(m.Attached) != 1 || m.Attached[0].Turntable != "" || m.Attached[0].NoTurn != "" || fileExists(filepath.Join(m.AttachedIn, "slow-turntable")) {
		t.Fatalf("the message: %+v", m)
	}
	if _, err := os.Stat(logPath); err == nil {
		t.Fatal("the engine was asked after Stop")
	}
}
