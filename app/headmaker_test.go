package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

var tinyPNG = []byte("\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x03\x08\x06\x00\x00\x00" + strings.Repeat("\x00", 40))

func strPtr(s string) *string { return &s }

func programForm() headForm {
	return headForm{Name: "Background remover", Summary: "Cuts the subject out of a picture.",
		WhenToUse: "Someone asks to remove a picture's background.", Tags: []string{" Background ", "cutout", "background"},
		Maker: HeadSpec{Kind: "program", Input: "picture", Output: []string{"picture", "nonsense"},
			Command: "rembg i {{input}} {{out}}/{{name}}_cutout.png --alpha {{strength}}",
			Options: []HeadOption{{Name: "Strength", Type: "number", Description: "how strongly to cut", Default: "0.5", Min: new(float64), Max: ptrF(1)}}}}
}

func ptrF(f float64) *float64 { return &f }

// The form becomes an ordinary plugin.json that Chimera reads like any Head's.
func TestHeadFormMakesAManifest(t *testing.T) {
	f := programForm()
	if err := f.check(); err != nil {
		t.Fatal(err)
	}
	if f.ID != "background-remover" || len(f.Tags) != 2 || f.Maker.Options[0].Name != "strength" || f.Maker.Options[0].Default != 0.5 {
		t.Fatalf("tidied form: %+v", f)
	}
	b, err := f.manifest("1.0.0")
	if err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(t.TempDir(), f.ID)
	os.MkdirAll(dir, 0o755)
	os.WriteFile(filepath.Join(dir, "plugin.json"), b, 0o644)
	m, _, err := readManifest(dir)
	if err != nil {
		t.Fatal(err)
	}
	if m.Entry != "run.py" || m.Network != "" || len(m.Maker) == 0 || !acceptsType(m.Accepts, "image/jpeg") ||
		!acceptsType(m.Produces, "image/png") || acceptsType(m.Produces, "model/gltf-binary") {
		t.Fatalf("manifest: %+v", m)
	}
	var schema optionSchema
	if json.Unmarshal(m.Options, &schema) != nil || schema.Properties["strength"].Type != "number" ||
		!strings.Contains(schema.Properties["strength"].Description, "(default 0.5)") || *schema.Properties["strength"].Maximum != 1 {
		t.Fatalf("options schema: %s", m.Options)
	}

	s := serverForm()
	if err := s.check(); err != nil {
		t.Fatal(err)
	}
	b, _ = s.manifest("1.0.0")
	var mm madeManifest
	json.Unmarshal(b, &mm)
	if mm.Network != "localhost" || len(mm.Accepts) != 0 || string(mm.Maker.Body) == "" || mm.Maker.Command != "" {
		t.Fatalf("a server Head talks to this computer's servers and keeps its JSON template: %s", b)
	}
}

func serverForm() headForm {
	return headForm{Name: "SD pictures", Summary: "Makes pictures.", WhenToUse: "Someone asks for a picture.",
		Maker: HeadSpec{Kind: "server", Input: "words", Output: []string{"picture"}, URL: "http://127.0.0.1:7860/sdapi/v1/txt2img", Command: "left over",
			Options: []HeadOption{{Name: "steps", Type: "integer", Description: "steps", Default: 25.4}}},
		BodyText: strPtr(`{"prompt": "{{prompt}}", "steps": "{{steps}}", "seed": "{{seed}}"}`)}
}

// Mistakes are caught with a sentence that says what to change.
func TestHeadFormRefusesMistakes(t *testing.T) {
	cases := []struct {
		want   string
		change func(f *headForm)
	}{
		{"name", func(f *headForm) { f.Name = " " }},
		{"when the pool should use it", func(f *headForm) { f.WhenToUse = "" }},
		{"{{inptu}}", func(f *headForm) { f.Maker.Command = "rembg {{inptu}} {{out}}/a.png" }},
		{"needs {{input}}", func(f *headForm) { f.Maker.Command = "rembg {{out}}/a.png" }},
		{"words only", func(f *headForm) { f.Maker.Input = "words" }},
		{"when there's no picture", func(f *headForm) { f.Maker.Input = "either" }},
		{"gives back", func(f *headForm) { f.Maker.Output = []string{"nonsense"} }},
		{"how it runs", func(f *headForm) { f.Maker.Kind = "magic" }},
		{"what the setting strength means", func(f *headForm) { f.Maker.Options[0].Description = "" }},
		{"must be a number", func(f *headForm) { f.Maker.Options[0].Default = "lots" }},
		{"outside its lowest and highest", func(f *headForm) { f.Maker.Options[0].Default = 3.0 }},
		{"already a placeholder", func(f *headForm) { f.Maker.Options[0].Name = "out" }},
		{"at least two choices", func(f *headForm) {
			f.Maker.Options[0] = HeadOption{Name: "style", Type: "choice", Description: "look", Choices: []string{"soft"}}
		}},
		{"one of its choices", func(f *headForm) {
			f.Maker.Options[0] = HeadOption{Name: "style", Type: "choice", Description: "look", Choices: []string{"soft", "hard"}, Default: "none"}
		}},
		{"full paths", func(f *headForm) { f.Maker.Reads = []string{"models"} }},
		{"There's no folder", func(f *headForm) { f.Maker.Reads = []string{"/no/such/folder/anywhere"} }},
	}
	for _, c := range cases {
		f := programForm()
		c.change(&f)
		if err := f.check(); err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("want an error about %q, got %v", c.want, err)
		}
	}
	server := []struct {
		want   string
		change func(f *headForm)
	}{
		{"on this computer", func(f *headForm) { f.Maker.URL = "https://api.example.com/v1/images" }},
		{"isn't valid JSON", func(f *headForm) { f.BodyText = strPtr(`{"steps": {{steps}}}`) }},
		{"never reaches the server", func(f *headForm) { f.Maker.Input = "picture" }},
		{"no JSON to send", func(f *headForm) { f.Maker.Method = "get" }},
		{"{{out}}", func(f *headForm) { f.BodyText = strPtr(`{"path": "{{out}}"}`) }},
	}
	for _, c := range server {
		f := serverForm()
		c.change(&f)
		if err := f.check(); err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("server: want an error about %q, got %v", c.want, err)
		}
	}
	f := serverForm()
	f.Maker.Input, f.Maker.UploadField = "picture", "file"
	if err := f.check(); err != nil {
		t.Errorf("a picture sent as a file upload is fine: %v", err)
	}
}

func TestSniffAndAcceptTextAndMoreMeshes(t *testing.T) {
	if !acceptsType([]string{"text/plain"}, sniffMIME("a.txt", []byte("hello"))) {
		t.Fatal("a text Head that says text/plain keeps its .txt (the sniffed type has a charset)")
	}
	for name, want := range map[string]string{"a.stl": "model/stl", "a.ply": "model/ply", "a.blend": "application/x-blender"} {
		if got := sniffMIME(name, []byte("solid x\n")); name != "a.blend" && got != want {
			t.Errorf("sniffMIME(%s) = %s", name, got)
		}
	}
	if got := sniffMIME("a.blend", append([]byte("BLENDER-v300"), make([]byte, 64)...)); got != "application/x-blender" {
		t.Errorf("sniffMIME(a.blend) = %s", got)
	}
	if got := sniffMIME("a.ogg", append([]byte("OggS\x00\x02"), make([]byte, 64)...)); !acceptsType([]string{"audio/*"}, got) {
		t.Errorf("an .ogg is sound: %s", got)
	}
	if got := sniffMIME("speech.aiff", append([]byte("FORM\x00\x01\x08\x0cAIFCFVER"), make([]byte, 64)...)); !acceptsType([]string{"audio/*"}, got) {
		t.Errorf("the Mac's say makes AIFF-C, which is sound: %s", got)
	}
}

// testMakerApp is an App with just what saving and probing a made Head needs.
func testMakerApp(t *testing.T) *App {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the test programs are Unix ones")
	}
	py := findPython()
	if py == "" {
		t.Skip("no Python 3")
	}
	a := &App{dataDir: t.TempDir(), cfg: Config{DeviceName: "test", LendPlugins: true}, quit: make(chan struct{})}
	a.tools = NewToolScanner(a)
	a.tools.ext["python"] = ToolInfo{ID: "python", Have: true, Path: py}
	return a
}

// runMade runs a made Head's run.py the way Chimera does, minus the sandbox.
func runMade(t *testing.T, a *App, p *installedPlugin, input string) (map[string]any, string) {
	t.Helper()
	out := filepath.Join(t.TempDir(), "out")
	os.MkdirAll(out, 0o755)
	cmd := exec.Command(a.tools.Path("python"), "-E", "-s", filepath.Join(p.Dir, "run.py"), out)
	cmd.Env = pluginEnv(p.Manifest, out, t.TempDir(), "", "test")
	cmd.Stdin = strings.NewReader(input)
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	cmd.Run()
	var res map[string]any
	if err := json.Unmarshal(lastJSONLine(stdout.Bytes()), &res); err != nil {
		t.Fatalf("no result line: %q / %q", stdout.String(), stderr.String())
	}
	return res, out
}

func saveOrFail(t *testing.T, a *App, f headForm) *installedPlugin {
	t.Helper()
	p, err := a.saveHead(f)
	if err != nil {
		t.Fatal(err)
	}
	return p
}

func picInput(request string) string {
	b, _ := json.Marshal(map[string]any{"request": request, "options": map[string]any{},
		"image": map[string]string{"name": "chair.png", "data_base64": base64.StdEncoding.EncodeToString(tinyPNG)}})
	return string(b)
}

func TestMadeProgramHeadRuns(t *testing.T) {
	a := testMakerApp(t)
	f := programForm()
	f.Maker.Command = "/bin/cp {{input}} {{out}}/{{name}}_copy.png"
	f.Maker.Options = nil
	p := saveOrFail(t, a, f)
	if !p.Probe.Have || !strings.Contains(strings.Join(p.Probe.Sandbox.Read, " "), "/bin") {
		t.Fatalf("probe: %+v %s", p.Probe, p.Err)
	}
	res, out := runMade(t, a, p, picInput("copy it"))
	got, _ := os.ReadFile(filepath.Join(out, "chair_copy.png"))
	if res["ok"] != true || !bytes.Equal(got, tinyPNG) {
		t.Fatalf("copy: %v", res)
	}
	if res, _ := runMade(t, a, p, `{"request":"no picture"}`); res["ok"] != false || !strings.Contains(res["error"].(string), "Attach a picture") {
		t.Fatalf("a picture Head without a picture: %v", res)
	}

	// Words in, text out; a yes/no setting adds its own words to the command, or nothing.
	words := headForm{Name: "Echo", Summary: "Says it back.", WhenToUse: "echo", Maker: HeadSpec{Kind: "program", Input: "words", Output: []string{"text"},
		Command: "/bin/echo {{loud}} {{count}}x {{prompt}}",
		Options: []HeadOption{{Name: "loud", Type: "boolean", Description: "shout", Yes: strPtr("LOUD"), No: strPtr("")},
			{Name: "count", Type: "integer", Description: "times", Default: 3.0}}}}
	p = saveOrFail(t, a, words)
	res, _ = runMade(t, a, p, `{"request":"hello world","options":{"loud":true,"count":2,"sneaky":"$(rm -rf ~)"}}`)
	if res["ok"] != true || res["summary"] != "LOUD 2x hello world" {
		t.Fatalf("echo with settings: %v", res)
	}
	res, _ = runMade(t, a, p, `{"request":"hi; rm -rf ~","options":{}}`)
	if res["summary"] != "3x hi; rm -rf ~" {
		t.Fatalf("defaults, and the words stay one argument (no shell): %v", res)
	}

	// A program that saves where it runs still counts; one that fails says why.
	cwd := headForm{Name: "Writes here", Summary: "Writes a file.", WhenToUse: "write", Maker: HeadSpec{Kind: "program", Input: "words", Output: []string{"text"},
		Command: `/bin/sh -c "echo made in place > made.txt"`}}
	res, out = runMade(t, a, saveOrFail(t, a, cwd), `{"request":"x"}`)
	if res["ok"] != true || res["summary"] != "made in place" || !fileExists(filepath.Join(out, "made.txt")) {
		t.Fatalf("file in the working folder: %v", res)
	}
	bad := headForm{Name: "Fails", Summary: "Fails.", WhenToUse: "fail", Maker: HeadSpec{Kind: "program", Input: "words", Output: []string{"file"},
		Command: `/bin/sh -c "echo the model is missing >&2; exit 4"`}}
	res, _ = runMade(t, a, saveOrFail(t, a, bad), `{"request":"x"}`)
	if msg, _ := res["error"].(string); res["ok"] != false || !strings.Contains(msg, "exit code 4") || !strings.Contains(msg, "the model is missing") {
		t.Fatalf("failure: %v", res)
	}

	missing := headForm{Name: "Missing", Summary: "Not here.", WhenToUse: "never", Maker: HeadSpec{Kind: "program", Input: "words", Output: []string{"file"},
		Command: "/no/such/tool {{prompt}} /no/such/script.py"}}
	p = saveOrFail(t, a, missing)
	if p.Probe.Have || !strings.Contains(strings.Join(p.Probe.Missing, " "), "/no/such/tool") {
		t.Fatalf("a missing program is reported by the probe: %+v", p.Probe)
	}
}

func TestMadeServerHeadRuns(t *testing.T) {
	a := testMakerApp(t)
	var got map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/sdapi/v1/txt2img":
			json.NewDecoder(r.Body).Decode(&got)
			json.NewEncoder(w).Encode(map[string]any{"images": []string{base64.StdEncoding.EncodeToString(tinyPNG)}, "info": "x"})
		case "/mesh":
			var in map[string]any
			json.NewDecoder(r.Body).Decode(&in)
			if in["image"] != base64.StdEncoding.EncodeToString(tinyPNG) {
				http.Error(w, "no picture", 422)
				return
			}
			w.Header().Set("Content-Type", "application/octet-stream")
			w.Write(append([]byte("glTF\x02\x00\x00\x00"), make([]byte, 200)...))
		case "/upload":
			if err := r.ParseMultipartForm(1 << 20); err != nil || r.FormValue("mode") != "fast" {
				http.Error(w, "bad form", 400)
				return
			}
			file, _, err := r.FormFile("file")
			if err != nil {
				http.Error(w, "no file", 400)
				return
			}
			b, _ := io.ReadAll(file)
			w.Header().Set("Content-Type", "image/png")
			w.Write(b)
		case "/caption":
			json.NewEncoder(w).Encode(map[string]string{"text": "a wooden chair"})
		case "/nothing":
			json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
		}
	}))
	defer srv.Close()

	f := serverForm()
	f.Maker.URL = srv.URL + "/sdapi/v1/txt2img"
	f.Maker.ResultField = "images"
	p := saveOrFail(t, a, f)
	if !p.Probe.Have {
		t.Fatalf("the test server is up: %+v", p.Probe)
	}
	res, out := runMade(t, a, p, `{"request":"a red car","options":{"steps":30}}`)
	if res["ok"] != true || got["prompt"] != "a red car" || got["steps"] != 30.0 {
		t.Fatalf("txt2img: %v, the server got %v", res, got)
	}
	if _, isNum := got["seed"].(float64); !isNum {
		t.Fatalf("a placeholder alone in quotes keeps its type: seed %v", got["seed"])
	}
	if !fileExists(filepath.Join(out, "sd-pictures.png")) {
		t.Fatalf("want the picture saved as sd-pictures.png: %v", res)
	}

	mesh := headForm{Name: "Mesh", Summary: "Meshes.", WhenToUse: "3d", Maker: HeadSpec{Kind: "server", Input: "picture", Output: []string{"model"},
		URL: srv.URL + "/mesh"}, BodyText: strPtr(`{"image": "{{input_base64}}", "type": "glb"}`)}
	res, out = runMade(t, a, saveOrFail(t, a, mesh), picInput("make it 3d"))
	if res["ok"] != true || !fileExists(filepath.Join(out, "chair_mesh.glb")) {
		t.Fatalf("raw bytes back: %v", res)
	}

	up := headForm{Name: "Upload", Summary: "Uploads.", WhenToUse: "up", Maker: HeadSpec{Kind: "server", Input: "picture", Output: []string{"picture"},
		URL: srv.URL + "/upload", UploadField: "file"}, BodyText: strPtr(`{"mode": "fast"}`)}
	res, out = runMade(t, a, saveOrFail(t, a, up), picInput("x"))
	if b, _ := os.ReadFile(filepath.Join(out, "chair_upload.png")); res["ok"] != true || !bytes.Equal(b, tinyPNG) {
		t.Fatalf("multipart upload: %v", res)
	}

	caption := headForm{Name: "Caption", Summary: "Captions.", WhenToUse: "caption", Maker: HeadSpec{Kind: "server", Input: "words", Output: []string{"text"},
		URL: srv.URL + "/caption"}, BodyText: strPtr(`{"q": "{{prompt}}"}`)}
	if res, _ = runMade(t, a, saveOrFail(t, a, caption), `{"request":"what is it"}`); res["summary"] != "a wooden chair" {
		t.Fatalf("text answer: %v", res)
	}

	nothing := headForm{Name: "Nothing", Summary: "Nothing.", WhenToUse: "n", Maker: HeadSpec{Kind: "server", Input: "words", Output: []string{"picture"},
		URL: srv.URL + "/nothing"}}
	if res, _ = runMade(t, a, saveOrFail(t, a, nothing), `{"request":"x"}`); res["ok"] != false || !strings.Contains(res["error"].(string), "Where the result is") {
		t.Fatalf("an answer without a file says where to look: %v", res)
	}

	srv.Close()
	p, _ = a.tools.refreshPlugin(p.Dir)
	if p.Probe.Have || !strings.Contains(strings.Join(p.Probe.Missing, " "), "Start the server") {
		t.Fatalf("a stopped server is reported: %+v", p.Probe)
	}
}

// Saving again changes a made Head (a new version); a Head written by hand is left alone.
func TestSaveHeadReplacesOnlyMadeHeads(t *testing.T) {
	a := testMakerApp(t)
	f := programForm()
	f.Maker.Command = "/bin/cp {{input}} {{out}}/x.png"
	f.Maker.Options = nil
	saveOrFail(t, a, f)
	if _, err := a.saveHead(f); err == nil || err.(headError).code != 409 {
		t.Fatalf("a second Head with the same name must not overwrite the first: %v", err)
	}
	f.Replace = true
	if p := saveOrFail(t, a, f); p.Manifest.Version != "1.0.1" {
		t.Fatalf("changed Head: version %s", p.Manifest.Version)
	}
	if got := a.tools.MadeHeads(); len(got) != 1 || got[0] != "background-remover" {
		t.Fatalf("made Heads: %v", got)
	}

	hand := filepath.Join(a.dataDir, "plugins", "by-hand")
	os.MkdirAll(hand, 0o755)
	os.WriteFile(filepath.Join(hand, "plugin.json"), []byte(`{"chimera_plugin":1,"id":"by-hand","name":"By hand","entry":"run.py"}`), 0o644)
	h := programForm()
	h.ID, h.Replace = "by-hand", true
	if _, err := a.saveHead(h); err == nil || !strings.Contains(err.Error(), "by hand") {
		t.Fatalf("a hand-written Head is never replaced by the maker: %v", err)
	}

	mux := http.NewServeMux()
	a.headRoutes(mux)
	rr := httptest.NewRecorder()
	mux.ServeHTTP(rr, httptest.NewRequest("GET", "/api/heads/background-remover", nil))
	var got struct {
		Editable bool     `json:"editable"`
		Maker    HeadSpec `json:"maker"`
	}
	if json.Unmarshal(rr.Body.Bytes(), &got); rr.Code != 200 || !got.Editable || got.Maker.Command == "" {
		t.Fatalf("GET a made Head: %d %s", rr.Code, rr.Body)
	}
}
