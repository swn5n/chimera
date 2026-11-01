package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func answer(blank bool, visible ...bool) lookAnswer {
	var a lookAnswer
	a.Blank = blank
	for i, v := range visible {
		a.Things = append(a.Things, struct {
			Name    string `json:"name"`
			Visible bool   `json:"visible"`
		}{string(rune('a' + i)), v})
	}
	return a
}

func TestALookIsHeldToMost(t *testing.T) {
	passed := resultCheck{Outcome: "passed", Summary: "Ran it."}
	for _, c := range []struct {
		name    string
		ans     lookAnswer
		outcome string
		has     string
	}{
		{"all of it", answer(false, true, true, true), "passed", "can make out a, b, c."},
		{"one of three missing", answer(false, true, true, false), "passed", "can make out a, b."},
		{"half isn't most", answer(false, true, false), "passed", "can make out a."},
		{"two of three missing", answer(false, true, false, false), "wrong_scene", "can't make out b, c. It can make out a."},
		{"the only thing there is", answer(false, false), "wrong_scene", "can't make out a."},
		{"nothing to make out", answer(true, false, false), "wrong_scene", "can't make anything out"},
		{"blank, but it names what it can see", answer(true, true, true), "passed", "can make out a, b."},
		{"blank, and nothing listed", answer(true), "wrong_scene", "can't make anything out"},
		{"no opinion", answer(false), "passed", ""},
	} {
		got := withLook(passed, c.ans, "eye", false)
		if got.Outcome != c.outcome || !strings.Contains(got.Summary, c.has) {
			t.Errorf("%s: %s %q", c.name, got.Outcome, got.Summary)
		}
		if (c.outcome == "passed") != (got.Error == "") {
			t.Errorf("%s: error %q", c.name, got.Error)
		}
	}
	long := answer(false, false)
	long.Things[0].Name = strings.Repeat("x", 500)
	if got := withLook(passed, long, "eye", false); len(got.Error) > 200 {
		t.Fatalf("what a model says goes into a critique, so it's kept short: %d", len(got.Error))
	}
	many := answer(false, true, true, true, true, true, true, true, true, false, false, false, false, false, false, false, false, false)
	if got := withLook(passed, many, "eye", false); got.Outcome != "passed" {
		t.Fatalf("only the first few things count: %+v", got)
	}
	f := facts(nil)
	got := withLook(resultCheck{Outcome: "passed", Summary: "Ran it.", Scene: f}, answer(false, true, false, false), "eye", false)
	if got.Measured == "" || got.Faults != 1 || got.Seen < 0.3 || got.Seen > 0.34 || !got.repairable() {
		t.Fatalf("a repair gets the measurements, and it ranks like a wrong scene: %+v", got)
	}
	if cr := sceneCritique("Blender", got); !strings.Contains(cr, "can't make out b, c") || !strings.Contains(cr, got.Measured) {
		t.Fatal(cr)
	}
	if !(got.grade() < (resultCheck{Outcome: "passed"}).grade()) {
		t.Fatal("it ranks below a pass")
	}
}

func TestWhatALookIsFor(t *testing.T) {
	const scene = "create a blender scene of a cup on a table"
	f := facts(nil)
	moving := facts(func(f *sceneFacts) { f.Animated = true })
	for _, c := range []struct {
		name, goal, script string
		f                  *sceneFacts
		want               bool
	}{
		{"a scene", scene, "", f, true},
		{"a close-up leaves things out on purpose", "a scene of a cup, a close-up", "", f, false},
		{"no scene was measured", scene, "", nil, false},
		{"a thing, not a scene", "model a chair", "", f, false},
		{"the person's own file", "create a scene of a cup in my project", "", f, false},
		{"no camera wanted", "a scene of a chair, no camera needed", "", f, false},
		{"part of it meant to be out of shot", "a scene of a table with a cup just out of shot", "", f, false},
		{"it moves", scene, "", moving, false},
		{"it fills in as it plays", scene, "bpy.app.handlers.frame_change_pre.append(f)", f, false},
		{"an add-on", scene, "bpy.utils.register_class(Op)", f, false},
	} {
		if got := wantsLook(c.goal, c.script, c.f); got != c.want {
			t.Errorf("%s: %v", c.name, got)
		}
	}
}

func TestAskingALook(t *testing.T) {
	var got map[string]any
	reply := `{"message":{"content":"{\"things\":[{\"name\":\"cup\",\"visible\":true}],\"blank\":false}"}}`
	status := 200
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/chat" {
			t.Errorf("path %s", r.URL.Path)
		}
		json.NewDecoder(r.Body).Decode(&got)
		w.WriteHeader(status)
		w.Write([]byte(reply))
	}))
	defer srv.Close()
	client := NewOllamaClient(srv.URL)
	ans, err := askLook(context.Background(), client, "eye", `a "quoted" scene`, []byte("picture"))
	if err != nil || len(ans.Things) != 1 || !ans.Things[0].Visible {
		t.Fatalf("%+v %v", ans, err)
	}
	if got["stream"] != false || got["think"] != false || got["format"] == nil || got["model"] != "eye" {
		t.Fatalf("one reply, no thinking, held to the format: %v", got)
	}
	msgs := got["messages"].([]any)
	user := msgs[1].(map[string]any)
	if imgs := user["images"].([]any); len(imgs) != 1 || imgs[0] != base64.StdEncoding.EncodeToString([]byte("picture")) {
		t.Fatalf("the picture goes with the question: %v", user)
	}
	if !strings.Contains(user["content"].(string), `a \"quoted\" scene`) {
		t.Fatalf("the goal is quoted: %v", user["content"])
	}
	for name, set := range map[string]func(){
		"not JSON":       func() { reply = `{"message":{"content":"I see a cup."}}` },
		"an error reply": func() { reply, status = `{"error":"no such model"}`, 500 },
		"an error in it": func() { reply, status = `{"error":"out of memory"}`, 200 },
	} {
		set()
		if _, err := askLook(context.Background(), client, "eye", "a scene", nil); err == nil {
			t.Errorf("%s: no error", name)
		}
	}
	srv.Close()
	if _, err := askLook(context.Background(), client, "eye", "a scene", nil); err == nil {
		t.Fatal("nobody home: no error")
	}
}

// A look with nothing to go on changes nothing.
func TestNoModelNoLook(t *testing.T) {
	a := &App{}
	c := resultCheck{Outcome: "passed", Summary: "Ran it."}
	if a.canLook() {
		t.Fatal("no Ollama, no look")
	}
	if got := a.lookAt(context.Background(), c, "a scene of a cup", []byte("picture")); got.Outcome != "passed" || got.Summary != c.Summary {
		t.Fatalf("%+v", got)
	}
}

func TestARealRenderInTheSandbox(t *testing.T) {
	path := testBlender(t)
	if !checkSandboxOK() {
		t.Skip("needs a sandbox")
	}
	const cam = "import bpy\nbpy.ops.mesh.primitive_uv_sphere_add(location=(0, 0, 0))\n"
	for _, c := range []struct {
		name, script string
		picture      bool
	}{
		{"a script that finishes", cam, true},
		{"one that stops at its render", cam + "bpy.context.scene.render.filepath = '/nowhere/x.png'\nbpy.ops.render.render(write_still=True)\n", true},
		{"its own settings don't matter", cam + "s = bpy.context.scene\ns.render.engine = 'BLENDER_EEVEE'\ns.render.resolution_x = 4000\ns.render.use_border = True\ns.render.film_transparent = True\n", true},
		{"Workbench's light can't be copied", cam + "bpy.context.scene.render.engine = 'BLENDER_WORKBENCH'\n", false},
		{"no camera, nothing to look from", "import bpy\nbpy.data.objects.remove(bpy.data.objects['Camera'])\n", false},
		{"its code doesn't run a second time", cam + "t = bpy.data.texts.new('x.py')\nt.write('open(\"ran-again\", \"w\").write(\"x\")\\n')\nt.use_module = True\n", true},
	} {
		dir := t.TempDir()
		script := filepath.Join(dir, "script.py")
		if err := os.WriteFile(script, []byte(c.script), 0o600); err != nil {
			t.Fatal(err)
		}
		res, f, _ := takeScene(realBlender(t, path, script, blenderStopAtRender+blenderCrashNames+blenderSceneFacts, blenderMeasureScene))
		if f == nil {
			t.Fatalf("%s: nothing measured\n%s", c.name, res.Output)
		}
		png := renderLook(context.Background(), path, dir)
		if c.picture != bytes.HasPrefix(png, []byte("\x89PNG")) {
			t.Fatalf("%s: picture %d bytes\n%s", c.name, len(png), res.Output)
		}
		if _, err := os.Stat(filepath.Join(dir, "ran-again")); err == nil {
			t.Fatalf("%s: the saved file ran its own code", c.name)
		}
	}
}
