package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"image/color"
	"image/png"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"testing"
	"time"
)

func eyeServer(t *testing.T, chat http.HandlerFunc) *httptest.Server {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/version":
			w.Write([]byte(`{"version":"0.40.1"}`))
		case "/api/tags":
			w.Write([]byte(`{"models":[{"name":"qwen3.8:27b","model":"qwen3.8:27b","size":18000000000,"digest":"abc","details":{"parameter_size":"27.8B"}}]}`))
		case "/api/show":
			w.Write([]byte(`{"capabilities":["completion","vision"],"model_info":{}}`))
		case "/api/chat":
			chat(w, r)
		}
	}))
	return srv
}

func eyeApp(t *testing.T, url string) *App {
	dir := t.TempDir()
	a := &App{dataDir: dir, cfg: Config{DeviceName: "t", CheckResults: true}, quit: make(chan struct{})}
	a.tools = NewToolScanner(a)
	a.perf = NewPerfStore(dir)
	a.sys = detectSysInfo()
	a.sessions = NewSessionStore(dir)
	a.ollama = NewOllamaMonitor(a, url)
	a.ollama.check()
	a.tools.ext["blender"] = ToolInfo{ID: "blender", Have: true, Path: testBlender(t), Version: "Blender 5.2.2"}
	return a
}

const goodCup = `import bpy, math
from mathutils import Vector
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
def mat(n, rgb, rough=.5):
    m = bpy.data.materials.new(n); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]; b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough
    return m
bpy.ops.mesh.primitive_plane_add(size=30, location=(0,0,0)); f=bpy.context.object; f.name="Floor"; f.data.materials.append(mat("floor",(.55,.55,.58)))
bpy.ops.mesh.primitive_cube_add(size=1, location=(0,0,.75)); t=bpy.context.object; t.name="TableTop"; t.scale=(2.4,1.4,.1); t.data.materials.append(mat("oak",(.42,.22,.07)))
for dx in (-1.1,1.1):
    for dy in (-.6,.6):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(dx,dy,.35)); l=bpy.context.object; l.name="TableLeg"; l.scale=(.1,.1,.7); l.data.materials.append(mat("oak2",(.42,.22,.07)))
bpy.ops.mesh.primitive_cylinder_add(radius=.17, depth=.34, location=(0,0,.97)); c=bpy.context.object; c.name="Cup"; c.data.materials.append(mat("red",(.75,.03,.03),.25))
bpy.ops.mesh.primitive_torus_add(major_radius=.09, minor_radius=.02, location=(.2,0,.98), rotation=(math.radians(90),0,0)); h=bpy.context.object; h.name="CupHandle"; h.data.materials.append(mat("red2",(.75,.03,.03),.25))
bpy.ops.object.light_add(type='SUN', location=(3,-3,6), rotation=(.7,.2,.5)); bpy.context.object.name="KeyLight"; bpy.context.object.data.energy=3
bpy.ops.object.light_add(type='AREA', location=(-3,-2,3), rotation=(1,-.6,0)); bpy.context.object.name="FillLight"; bpy.context.object.data.energy=120; bpy.context.object.data.size=3
bpy.ops.object.camera_add(location=(0,-4.2,2.1)); a=bpy.context.object; a.name="Camera"
a.rotation_euler=(Vector((0,0,.9))-a.location).to_track_quat('-Z','Y').to_euler()
bpy.context.scene.camera=a
bpy.context.scene.world = bpy.data.worlds.new("w"); bpy.context.scene.world.use_nodes=True
bpy.context.scene.world.node_tree.nodes["Background"].inputs[0].default_value=(.6,.65,.75,1)
`

// Stop while the model looks: a script that passed everything else is still a script that passed.
func TestLookStopDuringALookKeepsThePass(t *testing.T) {
	started := make(chan struct{}, 1)
	var srv *httptest.Server
	srv = eyeServer(t, func(w http.ResponseWriter, r *http.Request) {
		io.Copy(io.Discard, r.Body)
		started <- struct{}{}
		<-r.Context().Done()
	})
	defer srv.Close()
	a := eyeApp(t, srv.URL)
	tm := NewTaskManager(a)
	run := &taskRun{id: "x", sessionID: "none", kinds: map[string]bool{"blender": true}}
	ctx, cancel := context.WithCancel(context.Background())
	go func() { <-started; time.Sleep(100 * time.Millisecond); cancel() }()
	pass := passResult{Text: "```python\n" + goodCup + "```\n"}
	c := tm.checkResult(ctx, run, taskReq{Goal: "Create a blender scene of a red cup on a wooden table", Loop: true}, 2, pass)
	if ctx.Err() == nil {
		t.Fatal("the look never started")
	}
	if c.Outcome != "passed" {
		t.Fatalf("outcome %q grade %v checks %d", c.Outcome, c.grade(), len(run.rec.Checks))
	}
	if len(run.rec.Checks) != 1 || run.rec.Checks[0].Outcome != "passed" {
		t.Fatalf("the card keeps what was known: %+v", run.rec.Checks)
	}
}

func TestLookAMeasuredFaultRanksBelowALook(t *testing.T) {
	look := withLook(resultCheck{Outcome: "passed", Summary: "Ran it."}, answer(false, true, false, false), "eye", false)
	blank := withLook(resultCheck{Outcome: "passed", Summary: "Ran it."}, answer(true), "eye", false)
	out := resultCheck{Outcome: "wrong_scene", Faults: 1, Seen: 0.75, Error: "Table is out of frame."}
	none := resultCheck{Outcome: "wrong_scene", Faults: 1, Seen: 0, Error: "The camera sees none of the 6 objects."}
	fmt.Printf("look %.3f blank %.3f out-of-frame %.3f sees-none %.3f\n", look.grade(), blank.grade(), out.grade(), none.grade())
	if !(out.grade() < look.grade()) || !(none.grade() < blank.grade()) || !(look.grade() < (resultCheck{Outcome: "passed"}).grade()) {
		t.Fatal("a measured fault has to rank below a model's opinion, and an opinion below a pass")
	}
	if a, b := withLook(resultCheck{Outcome: "passed"}, answer(false, true, false, false), "eye", false), withLook(resultCheck{Outcome: "passed"}, answer(false, false, false), "eye", false); !(b.grade() < a.grade()) {
		t.Fatal("among looks, more seen ranks higher")
	}
}

func TestLookOneShotOfSeveralNeedsOnlySomething(t *testing.T) {
	f := facts(nil)
	two := facts(func(f *sceneFacts) { f.Cameras = 2 })
	for _, c := range []struct {
		goal string
		f    *sceneFacts
		ans  lookAnswer
		want string
	}{
		{"create a scene of a kitchen with a table, a fridge and a stove", f, answer(false, true, false, false), "wrong_scene"},
		{"create a scene of a kitchen with a table, a fridge and a stove, with the camera focused on the table", f, answer(false, true, false, false), "passed"},
		{"create a scene of a kitchen with a table, a fridge and a stove, with the camera focused on the table", f, answer(false, false, false, false), "wrong_scene"},
		{"create a scene of a kitchen with a table, a fridge and a stove, with the camera focused on the table", f, answer(true), "wrong_scene"},
		{"create a scene with a camera aimed at the table, framing the whole scene, of a table, a fridge and a stove", f, answer(false, true, false, false), "wrong_scene"},
		{"create a scene of a sofa, a bookshelf and a lamp", two, answer(false, true, false, false), "passed"},
		{"create a scene of a sofa, a bookshelf and a lamp", two, answer(false, false, false, false), "wrong_scene"},
	} {
		got := withLook(resultCheck{Outcome: "passed", Summary: "Ran it.", Scene: c.f}, c.ans, "eye", partOfIt(c.goal, c.f))
		if got.Outcome != c.want {
			t.Errorf("%q: %s %q", c.goal, got.Outcome, got.Error)
		}
	}
}

func TestLookOnlyTheMeasuredModelLooks(t *testing.T) {
	for name, c := range map[string]struct {
		models []ModelInfo
		want   string
	}{
		"only an OCR model": {[]ModelInfo{{Name: "glm-ocr", ParamsB: 0.9, Caps: []string{"completion", "vision"}}}, ""},
		"another model":     {[]ModelInfo{{Name: "gemma4:12b", ParamsB: 12, Caps: []string{"completion", "vision"}}}, ""},
		"the measured one":  {[]ModelInfo{{Name: "gemma4:26b", ParamsB: 26, Caps: []string{"completion", "vision"}}, {Name: "qwen3.8:27b", ParamsB: 27, Caps: []string{"completion", "vision"}}}, "qwen3.8:27b"},
	} {
		a := &App{dataDir: t.TempDir(), cfg: Config{DeviceName: "t"}, quit: make(chan struct{})}
		a.perf = NewPerfStore(a.dataDir)
		a.sys = detectSysInfo()
		a.ollama = NewOllamaMonitor(a, "")
		a.ollama.state.Models = c.models
		m, ok := a.lookModel()
		if ok != (c.want != "") || m.Name != c.want {
			t.Errorf("%s: %q %v", name, m.Name, ok)
		}
	}
}

// A stand-in Blender in nothing but shell builtins, so that the sandbox can't refuse it for the wrong reason.
func standIn(t *testing.T, body string) string {
	p := filepath.Join(t.TempDir(), "fake-blender")
	if err := os.WriteFile(p, []byte("#!/bin/bash\n"+body+"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	return p
}

func lookDir(t *testing.T) string {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, lookBlend), []byte("BLENDER"), 0o600); err != nil {
		t.Fatal(err)
	}
	return dir
}

const standInPNG = `printf '\211PNG fresh' > chimera-look.png`

func TestLookTheLookRendersInTheSandbox(t *testing.T) {
	if !checkSandboxOK() {
		t.Skip("needs a sandbox")
	}
	home, _ := os.UserHomeDir()
	secret, err := os.CreateTemp(home, ".chimera-verify-*")
	if err != nil {
		t.Fatal(err)
	}
	defer os.Remove(secret.Name())
	secret.WriteString("hidden\n")
	secret.Close()
	dir := lookDir(t)
	b := standIn(t, `if read line < "`+secret.Name()+`"; then printf 'READ IT' > leaked; else printf 'refused' > leaked; fi`+"\n"+standInPNG)
	png := renderLook(context.Background(), b, dir)
	got, err := os.ReadFile(filepath.Join(dir, "leaked"))
	if err != nil {
		t.Fatalf("stand-in never ran: %v (picture %d)", err, len(png))
	}
	if string(got) != "refused" {
		t.Fatalf("the look's Blender read a home file: %q", got)
	}
}

func TestLookStoppingTheLookStopsItsBlender(t *testing.T) {
	if !checkSandboxOK() {
		t.Skip("needs a sandbox")
	}
	dir := lookDir(t)
	b := standIn(t, `printf '%s' "$$" > pid
trap '' TERM HUP INT
while :; do :; done`)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan []byte, 1)
	go func() { done <- renderLook(ctx, b, dir) }()
	pidFile := filepath.Join(dir, "pid")
	var pid int
	for i := 0; i < 100 && pid == 0; i++ {
		time.Sleep(50 * time.Millisecond)
		s, _ := os.ReadFile(pidFile)
		pid, _ = strconv.Atoi(strings.TrimSpace(string(s)))
	}
	if pid == 0 {
		t.Fatal("stand-in never started")
	}
	cancel()
	select {
	case <-done:
	case <-time.After(3 * time.Second): // the watchdog stops it at once; WaitDelay alone takes 5 s
		defer syscall.Kill(pid, syscall.SIGKILL)
		t.Fatal("Stop didn't reach the look's Blender at once")
	}
	time.Sleep(600 * time.Millisecond)
	if err := syscall.Kill(pid, 0); err == nil {
		syscall.Kill(pid, syscall.SIGKILL)
		t.Fatalf("its Blender (pid %d) outlived Stop", pid)
	}
}

// What a script leaves where the picture will go is never the picture.
func TestLookWhatAScriptLeftIsNotAPicture(t *testing.T) {
	if !checkSandboxOK() {
		t.Skip("needs a sandbox")
	}
	home, _ := os.UserHomeDir()
	secret, err := os.CreateTemp(home, ".chimera-verify-*")
	if err != nil {
		t.Fatal(err)
	}
	defer os.Remove(secret.Name())
	secret.WriteString("hidden")
	secret.Close()
	failing := standIn(t, `exit 0`) // Blender that writes nothing and says all is well
	writing := standIn(t, standInPNG)
	huge := standIn(t, `i=0; while [ $i -lt 400 ]; do printf '%016384d' 0 >> chimera-look.png; printf '%016384d' 0 >> chimera-look.png; i=$((i+1)); done`)
	for _, c := range []struct {
		name    string
		blender string
		plant   func(p string) error
		want    string
	}{
		{"a symlink to a hidden file", failing, func(p string) error { return os.Symlink(secret.Name(), p) }, ""},
		{"a symlink to /dev/zero", failing, func(p string) error { return os.Symlink("/dev/zero", p) }, ""},
		{"a FIFO", failing, func(p string) error { return syscall.Mkfifo(p, 0o600) }, ""},
		{"planted bytes", failing, func(p string) error { return os.WriteFile(p, []byte("not a picture"), 0o600) }, ""},
		{"a sparse terabyte", failing, func(p string) error {
			f, err := os.Create(p)
			if err == nil {
				err = f.Truncate(1 << 40)
				f.Close()
			}
			return err
		}, ""},
		{"a folder", failing, func(p string) error { return os.Mkdir(p, 0o700) }, ""},
		{"too big, from Blender itself", huge, func(p string) error { return nil }, ""},
		{"a symlink the render replaces", writing, func(p string) error { return os.Symlink(secret.Name(), p) }, "\x89PNG fresh"},
		{"planted bytes the render replaces", writing, func(p string) error { return os.WriteFile(p, []byte("not a picture"), 0o600) }, "\x89PNG fresh"},
	} {
		dir := lookDir(t)
		if err := c.plant(filepath.Join(dir, lookPNG)); err != nil {
			t.Fatal(err)
		}
		done := make(chan []byte, 1)
		go func() { done <- renderLook(context.Background(), c.blender, dir) }()
		select {
		case got := <-done:
			if string(got) != c.want {
				t.Errorf("%s: %d bytes: %q", c.name, len(got), string(got[:min(len(got), 20)]))
			}
		case <-time.After(20 * time.Second):
			t.Fatalf("%s: renderLook hung", c.name)
		}
	}
}

func TestLookNoRenderForChecksThatCantUseIt(t *testing.T) {
	var asked atomic.Int32
	srv := eyeServer(t, func(w http.ResponseWriter, r *http.Request) { asked.Add(1) })
	defer srv.Close()
	a := eyeApp(t, srv.URL)
	const wrong = "import bpy\nbpy.ops.mesh.primitive_uv_sphere_add()\nbpy.data.objects.remove(bpy.data.objects['Camera'])\n"
	for _, c := range []struct {
		name, goal, script string
		want               bool
	}{
		{"a scene it can judge", "Create a blender scene of a red cup on a wooden table", goodCup, true},
		{"a goal with no scene", "Write a Python function that makes a grid mesh in the file.", goodCup, false},
		{"a scene the rules already failed", "Create a blender scene of a red cup on a wooden table", wrong, false},
	} {
		if res := a.checkScript(context.Background(), "run_blender", c.goal, c.script); (len(res.Look) > 0) != c.want {
			t.Errorf("%s: %d bytes", c.name, len(res.Look))
		}
	}
}

// A picture is small whatever the script asked for, and it isn't cropped.
func TestLookThePictureIsSmall(t *testing.T) {
	path := testBlender(t)
	if !checkSandboxOK() {
		t.Skip("needs a sandbox")
	}
	dir := t.TempDir()
	script := filepath.Join(dir, "script.py")
	body := goodCup + "\nr = bpy.context.scene.render\nr.resolution_x, r.resolution_y = 4000, 1000\nr.use_border, r.use_crop_to_border = True, True\nr.border_max_x, r.border_max_y = .1, .1\nr.film_transparent = True\n"
	os.WriteFile(script, []byte(body), 0o600)
	realBlender(t, path, script, blenderStopAtRender+blenderCrashNames+blenderSceneFacts, blenderMeasureScene)
	b := renderLook(context.Background(), path, dir)
	img, err := png.DecodeConfig(bytes.NewReader(b))
	if err != nil {
		t.Fatalf("%v (%d bytes)", err, len(b))
	}
	if img.Width != 512 || img.Height != 128 {
		t.Fatalf("%dx%d", img.Width, img.Height)
	}
	if img.ColorModel != color.RGBAModel && img.ColorModel != color.NRGBAModel {
		// an opaque RGB PNG decodes as RGBA with no transparency
		t.Logf("colour model %v", img.ColorModel)
	}
}

// The script had finished, so whatever went wrong after the marker isn't its doing.
func TestLookACrashAfterTheMeasuringIsntTheScripts(t *testing.T) {
	line, _ := json.Marshal(facts(nil))
	out := "\n" + sceneStartMarker + "\n" + sceneMarker + string(line) + "\n"
	c := judgeRun("run_blender", "Blender", "Create a blender scene of a cup", "import bpy\n", runResult{ExitCode: 1, Output: out, Stderr: out})
	if c.Outcome != "passed" {
		t.Fatalf("%+v", c)
	}
}

// Stop during the look at a repair that ran clean: the repair stays, not the crash it fixed.
func TestLookStopDuringARepairsLookKeepsTheRepair(t *testing.T) {
	started := make(chan struct{}, 1)
	srv := eyeServer(t, func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		if strings.Contains(string(b), `"images"`) {
			started <- struct{}{}
			<-r.Context().Done()
			return
		}
		reply, _ := json.Marshal("<<<<<<< FIND\nprint(nope_undefined)\n=======\nprint('fixed')\n>>>>>>> END\n")
		fmt.Fprintf(w, "{\"message\":{\"role\":\"assistant\",\"content\":%s},\"done\":false}\n{\"message\":{\"role\":\"assistant\",\"content\":\"\"},\"done\":true,\"done_reason\":\"stop\"}\n", reply)
	})
	defer srv.Close()
	a := eyeApp(t, srv.URL)
	tm := NewTaskManager(a)
	run := &taskRun{id: "x", sessionID: "none", kinds: map[string]bool{"blender": true}}
	req := taskReq{Goal: "Create a blender scene of a red cup on a wooden table", Loop: true}
	pass := passResult{Text: "```python\n" + goodCup + "\nprint(nope_undefined)\n```\n"}
	chk := tm.checkResult(context.Background(), run, req, 1, pass)
	if chk.Outcome != "failed" {
		t.Fatalf("the script has to crash first: %+v", chk)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { <-started; time.Sleep(100 * time.Millisecond); cancel() }()
	cur, c := tm.mendScript(ctx, run, req, 1, pass, chk)
	if ctx.Err() == nil {
		t.Fatal("the look never started")
	}
	if strings.Contains(cur.Text, "nope_undefined") || c.Outcome != "passed" {
		t.Fatalf("the repair was lost: %q, text has the crash: %v", c.Outcome, strings.Contains(cur.Text, "nope_undefined"))
	}
}

func lookFrom(t *testing.T, path, body string) []byte {
	t.Helper()
	dir := t.TempDir()
	script := filepath.Join(dir, "script.py")
	if err := os.WriteFile(script, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	realBlender(t, path, script, blenderStopAtRender+blenderCrashNames+blenderSceneFacts, blenderMeasureScene)
	return renderLook(context.Background(), path, dir)
}

// The output a script chose for itself doesn't stop the look's own picture.
func TestLookAnyOutputSettingStillGivesAPicture(t *testing.T) {
	path := testBlender(t)
	if !checkSandboxOK() {
		t.Skip("needs a sandbox")
	}
	const media = "r = bpy.context.scene.render\nif hasattr(r.image_settings, 'media_type'):\n    r.image_settings.media_type = '%s'\n"
	for name, tail := range map[string]string{
		"video":      fmt.Sprintf(media, "VIDEO"),
		"multilayer": fmt.Sprintf(media, "MULTI_LAYER_IMAGE"),
		"stereo":     "bpy.context.scene.render.use_multiview = True\n",
	} {
		if !bytes.HasPrefix(lookFrom(t, path, goodCup+"\n"+tail), []byte("\x89PNG")) {
			t.Errorf("%s: no picture", name)
		}
	}
}

// Pixels set in code are in the saved copy. A generated image starts black.
func TestLookPixelsSetInCodeSurviveTheSave(t *testing.T) {
	path := testBlender(t)
	if !checkSandboxOK() {
		t.Skip("needs a sandbox")
	}
	const glowing = `import bpy
bpy.ops.mesh.primitive_cube_add(size=4)
o = bpy.context.object
i = bpy.data.images.new("painted", 8, 8)
i.pixels = [1.0] * (8 * 8 * 4)
m = bpy.data.materials.new("m")
m.use_nodes = True
n = m.node_tree
tex = n.nodes.new("ShaderNodeTexImage")
tex.image = i
out = n.nodes.get("Material Output")
em = n.nodes.new("ShaderNodeEmission")
n.links.new(tex.outputs[0], em.inputs[0])
n.links.new(em.outputs[0], out.inputs[0])
o.data.materials.append(m)
`
	img, err := png.Decode(bytes.NewReader(lookFrom(t, path, glowing)))
	if err != nil {
		t.Fatal(err)
	}
	c := img.Bounds().Min.Add(img.Bounds().Size().Div(2))
	if r, _, _, _ := img.At(c.X, c.Y).RGBA(); r < 0x8000 {
		t.Fatalf("the cube in the middle of the picture is dark: %d", r>>8)
	}
}
