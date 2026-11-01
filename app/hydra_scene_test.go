package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const frameAll = "Build a tabletop scene with a camera that frames everything."

func facts(mod func(f *sceneFacts)) *sceneFacts {
	f := &sceneFacts{Camera: &sceneCamera{Name: "cam", At: []float64{0, -5, 2}, Ahead: []float64{0, 1, 0}, Lens: 50, Type: "PERSP"},
		Objects: []sceneObject{{Name: "table", At: []float64{0, 0, 0}, Size: []float64{2, 2, 1}, Hits: 900, Frame: true}, {Name: "mug", At: []float64{0, 0, 1}, Size: []float64{1, 1, 1}, Hits: 100, Frame: true}},
		Total:   2, Seen: 2, Filled: 0.4, Span: [][]float64{{-1, -1, 0}, {1, 1, 2}}}
	if mod != nil {
		mod(f)
	}
	return f
}

func TestSceneFaults(t *testing.T) {
	const camera = "Build a scene with a table and a camera."
	cube := func(f *sceneFacts) { f.Cube = true }
	nothing := func(f *sceneFacts) { f.Seen, f.Out, f.Filled = 0, 2, 0 }
	oneOut := func(f *sceneFacts) {
		f.Total, f.Seen, f.Out = 3, 2, 1
		f.Objects = append(f.Objects, sceneObject{Name: "lamp"})
	}
	noCamera := func(f *sceneFacts) { f.Camera = nil }
	for _, c := range []struct {
		name, goal, script string
		f                  *sceneFacts
		want               string // "" for no fault
	}{
		{"all in frame", frameAll, "", facts(nil), ""},
		{"the camera reaches nothing", frameAll, "", facts(nothing), "The camera sees none of the 2 objects."},
		{"rays reached something that doesn't count", frameAll, "", facts(func(f *sceneFacts) { f.Seen, f.Out, f.Filled = 0, 2, 1 }), "out of frame"},
		{"something rays can't reach", frameAll, "", facts(func(f *sceneFacts) { f.Seen, f.Out, f.Filled, f.Unseen = 0, 0, 0, true }), ""},
		{"the camera in the room", frameAll, "", facts(func(f *sceneFacts) {
			oneOut(f)
			f.Camera.At = []float64{0, 0, 1}
		}), ""},
		{"an add-on", frameAll, "bpy.utils.register_class(Op)", facts(nothing), ""},
		{"an empty mesh it asked for", "Add an empty mesh for me.", "", facts(func(f *sceneFacts) { f.Empty, f.Blank = []string{"a"}, 1 }), ""},
		{"a cube it picks up", "Build a scene with a red box on a floor and a camera.", "box = bpy.context.active_object\nbpy.ops.mesh.primitive_plane_add()", facts(cube), ""},
		{"so it's wrong with any camera", camera, "", facts(nothing), "The camera sees none"},
		{"out of frame, and the task said everything", frameAll, "", facts(oneOut), "lamp is out of frame."},
		{"out of frame, and it didn't", camera, "", facts(oneOut), ""},
		{"a close-up the task asked for", "A close-up of a watch's crown, with a camera on it: the rest is out of shot.", "", facts(func(f *sceneFacts) { f.Total, f.Seen, f.Out = 15, 1, 14 }), ""},
		{"hidden isn't out", frameAll, "", facts(func(f *sceneFacts) { f.Total, f.Seen = 11, 1 }), ""},
		{"no camera, and it asked for one", frameAll, "", facts(noCamera), "The scene has no camera."},
		{"an animated camera at one moment", frameAll, "", facts(func(f *sceneFacts) { f.Animated = true; f.Seen = 0 }), ""},
		{"a script that fills the scene as it plays", frameAll, "bpy.app.handlers.frame_change_pre.append(f)", facts(nothing), ""},
		{"a panoramic camera", frameAll, "", facts(func(f *sceneFacts) { f.Camera.Type = "PANO"; f.Seen = 0 }), ""},
		{"no geometry", "Add a torus.", "", facts(func(f *sceneFacts) { f.Empty, f.Blank = []string{"water"}, 1 }), "water has no geometry."},
		{"two with none", "Add a torus.", "", facts(func(f *sceneFacts) { f.Empty, f.Blank = []string{"water", "floor"}, 2 }), "water, floor have no geometry."},
		{"many with none", "Add a torus.", "", facts(func(f *sceneFacts) { f.Empty, f.Blank = []string{"a", "b", "c"}, 9 }), "a, b, c and 6 more have no geometry."},
		{"nothing in the scene", "Add a material.", "", facts(func(f *sceneFacts) { f.Total, f.Seen = 0, 0 }), ""},
		{"the default cube in a new scene", "Build a small tabletop scene with a table.", "bpy.ops.mesh.primitive_plane_add()", facts(cube), "The default cube is still in the scene."},
		{"a goal that opens with the scene", "A tabletop scene with a mug.", "bpy.ops.mesh.primitive_plane_add()", facts(cube), "The default cube"},
		{"the task is about a cube", "Build a scene with a red cube.", "", facts(cube), ""},
		{"or cubes", "Build a scene of three cubes.", "", facts(cube), ""},
		{"the script uses it", frameAll, "c = bpy.data.objects['Cube']", facts(cube), ""},
	} {
		got := strings.Join(sceneFaults(c.f, c.goal, c.script), " ")
		if (c.want == "") != (got == "") || !strings.Contains(got, c.want) {
			t.Errorf("%s: want %q, got %q", c.name, c.want, got)
		}
	}
	// The review's false alarms: every one of these is a fine result.
	for _, goal := range []string{
		"Add a red sphere to the scene next to what is there.", "Write a script that sets my scene to Cycles at 3840x2160, 128 samples, PNG output.",
		"Write a Blender add-on that adds a panel to the Render properties with a button.", "Add a bevel modifier to every mesh in the scene.",
		"Add a second camera to the scene, looking straight down from above.", "Point the camera at the active object and frame it.",
		"Import my model from ~/Models/chair.obj into the scene and put the camera on it.", "Make a glass material for the active object and render a preview.",
	} {
		if got := sceneFaults(facts(func(f *sceneFacts) { f.Cube, f.Seen, f.Out = true, 0, 2 }), goal, ""); len(got) > 0 {
			t.Errorf("working on the person's own file: %s: %q", goal, got)
		}
	}
	for _, goal := range []string{
		"Model a wooden picture frame.", "Model a bed frame with a headboard and four legs.", "Model an A-frame cabin.", "Model a vintage film camera with a lens, a body and a strap.",
		"Animate a ball bouncing three times over 120 frames.", "Build a low-poly tree. No need to render it.", "Crea una camera da letto con un letto.",
		"Model a bed frame that fits a queen mattress.", "Build a window frame the size of a door.", "Model a smartphone with three cameras on the back.",
		"Build a robot with a camera on its head.", "Create a 3D model of a camera on a tripod.", "Model a render-ready wooden chair.", "Model a chair with the back slats in view from the front.",
	} {
		if got := sceneFaults(facts(noCamera), goal, ""); len(got) > 0 {
			t.Errorf("no camera wanted: %s: %q", goal, got)
		}
	}
	for _, goal := range []string{frameAll, "Build a table with a camera that frames it.", "Add a camera to frame the scene.", "A vase, and render it."} {
		if got := sceneFaults(facts(noCamera), goal, ""); len(got) != 1 {
			t.Errorf("a camera wanted: %s: %q", goal, got)
		}
	}
}

func TestEverydayScenes(t *testing.T) {
	const cup = "can u create a blender scene of a coffee cup on a table lit by a lamp also on the table"
	table := sceneObject{Name: "chimera_table", Size: []float64{2, 1, 1}, Hits: 900, Frame: true}
	lampBase := sceneObject{Name: "chimera_lamp_base", Size: []float64{1, 1, 1}, Hits: 40, Frame: true}
	lampTop := sceneObject{Name: "chimera_lamp_top", Size: []float64{1, 1, 1}, Share: 0}
	scene := func(objects []sceneObject, shown, hidden []string, mod func(f *sceneFacts)) *sceneFacts {
		return facts(func(f *sceneFacts) {
			f.Objects, f.Shown, f.Hidden, f.Total, f.Out, f.Cut = objects, shown, hidden, len(objects), 0, 0
			for _, o := range objects {
				if o.Hits == 0 && !o.Frame {
					f.Out++
				} else if o.Cut {
					f.Cut++
				}
			}
			if mod != nil {
				mod(f)
			}
		})
	}
	mugOut := sceneObject{Name: "chimera_coffee_cup", Size: []float64{1, 1, 1}}
	mugCut := sceneObject{Name: "chimera_coffee_cup", Size: []float64{1, 1, 1}, Hits: 2, Frame: true, Cut: true, Share: 0.4}
	mugIn := sceneObject{Name: "chimera_coffee_cup", Size: []float64{1, 1, 1}, Hits: 30, Frame: true}
	onTable := []string{"chimera", "table", "lamp", "base"}
	things := func(n, out int) *sceneFacts {
		var objects []sceneObject
		for i := range n {
			o := sceneObject{Name: fmt.Sprintf("Plain.%03d", i), Hits: 20, Frame: true}
			if i < out {
				o.Hits, o.Frame = 0, false
			}
			objects = append(objects, o)
		}
		return scene(objects, []string{"plain"}, []string{"plain"}, nil)
	}
	for _, c := range []struct {
		name, goal string
		f          *sceneFacts
		want       string
	}{
		{"what it names is out of shot", cup, scene([]sceneObject{mugOut, table, lampBase}, onTable, []string{"chimera", "coffee", "cup"}, nil), "doesn't show chimera_coffee_cup"},
		{"barely in the corner, as on Oct 31", cup, scene([]sceneObject{mugCut, table, lampBase}, onTable, []string{"chimera", "coffee", "cup"}, nil), "doesn't show chimera_coffee_cup"},
		{"all in", cup, scene([]sceneObject{mugIn, table, lampBase}, append(onTable, "coffee", "cup"), nil, nil), ""},
		{"some of the lamp is in shot", cup, scene([]sceneObject{lampTop, mugIn, table, lampBase}, append(onTable, "coffee", "cup"), []string{"chimera", "lamp", "top"}, nil), ""},
		{"none of it is", cup, scene([]sceneObject{lampTop, mugIn, table}, []string{"chimera", "coffee", "cup", "table"}, []string{"chimera", "lamp", "top"}, nil), "doesn't show chimera_lamp_top"},
		{"a plural", "A scene of two lamps on a table.", scene([]sceneObject{lampTop, table}, []string{"chimera", "table"}, []string{"chimera", "lamp", "top"}, nil), "chimera_lamp_top"},
		{"another word that starts the same", "A scene of a dog having a bath.", scene([]sceneObject{{Name: "Bathroom_Cabinet"}, table}, []string{"chimera", "table"}, []string{"bathroom", "cabinet"}, nil), ""},
		{"but it can show the thing", "A scene of a table.", scene([]sceneObject{{Name: "Table_Leg"}, {Name: "Tabletop", Hits: 300, Frame: true}}, []string{"tabletop"}, []string{"leg", "table"}, nil), ""},
		{"where it stands, by an extra", "A scene of a bike in a garage.", scene([]sceneObject{{Name: "Garage_Door"}, {Name: "Bike", Hits: 300, Frame: true}}, []string{"bike"}, []string{"door", "garage"}, nil), ""},
		{"where it stands, and nothing there", "A scene of a bike in a garage.", scene([]sceneObject{{Name: "Garage_Door"}, {Name: "Bike"}, table}, []string{"chimera", "table"}, []string{"bike", "door", "garage"}, nil), "doesn't show Bike, Garage_Door"},
		{"what stands there isn't where", "A scene of a cat on a sofa.", scene([]sceneObject{{Name: "Cat"}, {Name: "Sofa", Hits: 300, Frame: true}}, []string{"sofa"}, []string{"cat"}, nil), "doesn't show Cat"},
		{"a verb isn't a thing", "A scene of a girl reading on a sofa.", scene([]sceneObject{{Name: "Reading_Lamp"}, {Name: "Sofa", Hits: 300, Frame: true}}, []string{"sofa"}, []string{"lamp", "reading"}, nil), ""},
		{"a word for the shot isn't a thing", "A scene of a cup on a table, with the cup in the middle of the frame.", scene([]sceneObject{{Name: "Picture_Frame"}, mugIn, table}, append(onTable, "coffee", "cup"), []string{"frame", "picture"}, nil), ""},
		{"only what the task named counts", "A scene of a table.", scene([]sceneObject{mugOut, table}, []string{"chimera", "table"}, []string{"chimera", "coffee", "cup"}, nil), ""},
		{"nothing named: a forest is mostly out of any good shot", "A scene of a garden.", things(6, 5), ""},
		{"a place to the left isn't a thing", "A scene of a jug on a table with a cup on the left.", scene([]sceneObject{{Name: "Table_Leg_Left"}, {Name: "Jug", Hits: 30, Frame: true}, {Name: "Cup", Hits: 30, Frame: true}, {Name: "Table", Hits: 300, Frame: true}}, []string{"cup", "jug", "table"}, []string{"leg", "left", "table"}, nil), ""},
		{"a cup of tea has no teapot in it", "A scene of a cup of tea on a table.", scene([]sceneObject{{Name: "Tea_Pot"}, {Name: "Cup", Hits: 30, Frame: true}, table}, []string{"chimera", "cup", "table"}, []string{"pot", "tea"}, nil), ""},
		{"a dining table has no dining chair in it", "A scene of a candle on a dining table.", scene([]sceneObject{{Name: "Dining_Chair"}, {Name: "Candle", Hits: 30, Frame: true}, {Name: "Dining_Table", Hits: 900, Frame: true}}, []string{"candle", "dining", "table"}, []string{"chair", "dining"}, nil), ""},
		{"what lights it can stand outside it", "A still life of fruit in a bowl on a table lit by a window.", scene([]sceneObject{{Name: "Window_Frame"}, {Name: "Bowl", Hits: 30, Frame: true}, table}, []string{"bowl", "chimera", "fruit", "table"}, []string{"frame", "window"}, nil), ""},
		{"unless it's placed", cup, scene([]sceneObject{lampTop, mugIn, table}, []string{"chimera", "coffee", "cup", "table"}, []string{"chimera", "lamp", "top"}, nil), "chimera_lamp_top"},
		{"a helper's word is no thing", "A scene of a farm.", scene([]sceneObject{{Name: "Farmhouse"}, table}, []string{"chimera", "table"}, nil, nil), ""},
		{"three at most", "A scene of a mug, a bowl, a lamp and a spoon.", scene([]sceneObject{{Name: "mug"}, {Name: "bowl"}, {Name: "lamp"}, {Name: "spoon"}, table}, []string{"chimera", "table"}, []string{"bowl", "lamp", "mug", "spoon"}, nil), "mug, bowl, lamp, which"},
		{"a word with no object listed", "A scene of a mug on a table.", scene([]sceneObject{table}, []string{"chimera", "table"}, []string{"mug"}, nil), "doesn't show mug"},
		{"a short word doesn't start a longer one", "A scene of a bus.", scene([]sceneObject{{Name: "Bush"}, table}, []string{"chimera", "table"}, []string{"bush"}, nil), ""},
		{"two cameras, and this one shows something asked for", "A scene of a mug and a table.", scene([]sceneObject{{Name: "mug"}, table}, []string{"chimera", "table"}, []string{"mug"}, func(f *sceneFacts) { f.Cameras = 2 }), ""},
		{"two cameras, and it shows nothing asked for", "A scene of a mug and a bowl.", scene([]sceneObject{{Name: "mug"}, {Name: "bowl"}, table}, []string{"chimera", "table"}, []string{"bowl", "mug"}, func(f *sceneFacts) { f.Cameras = 2 }), "doesn't show mug, bowl"},
		{"among it, and it shows nothing asked for", "A scene of a mug and a bowl.", scene([]sceneObject{{Name: "mug"}, {Name: "bowl"}, table}, []string{"chimera", "table"}, []string{"bowl", "mug"}, func(f *sceneFacts) { f.Camera.At = []float64{0, 0, 1} }), "doesn't show mug, bowl"},
		{"a scene needs a camera", cup, scene([]sceneObject{table}, nil, nil, func(f *sceneFacts) { f.Camera = nil }), "The scene has no camera."},
		{"unless it says not", "A scene of a chair, no camera needed.", scene([]sceneObject{table}, nil, nil, func(f *sceneFacts) { f.Camera = nil }), ""},
		{"or leaves it for later", "A scene of a chair. Don't add a camera, I'll set up the camera myself.", scene([]sceneObject{table}, nil, nil, func(f *sceneFacts) { f.Camera = nil }), ""},
		{"or says so in passing", "blender scene of a sandcastle pls, leave the camera to me", scene([]sceneObject{table}, nil, nil, func(f *sceneFacts) { f.Camera = nil }), ""},
		{"a blank scene it asked for", "Create an empty scene.", scene(nil, nil, nil, func(f *sceneFacts) { f.Camera, f.Total = nil, 0 }), ""},
		{"a script with nothing added leaves the cube", "A scene of a chair.", scene(nil, nil, nil, func(f *sceneFacts) { f.Cube = true }), ""},
		{"and it has to see something", cup, scene([]sceneObject{{Name: "chimera_table"}}, nil, []string{"chimera", "table"}, func(f *sceneFacts) { f.Seen, f.Filled = 0, 0 }), "The camera sees none"},
		{"standing among it", cup, scene([]sceneObject{mugOut, table, lampBase}, onTable, []string{"chimera", "coffee", "cup"}, func(f *sceneFacts) { f.Camera.At = []float64{0, 0, 1} }), ""},
		{"a close-up it asked for", "A close-up scene of a cup on a table.", scene([]sceneObject{mugOut, table, lampBase}, onTable, []string{"chimera", "coffee", "cup"}, nil), ""},
		{"out of shot, as it said", "A scene of a table with a cup just out of shot.", scene([]sceneObject{mugOut, table, lampBase}, onTable, []string{"chimera", "coffee", "cup"}, nil), ""},
		{"it said what the camera is for", "A street scene with a cup and a table, and a camera that shows the whole table.", scene([]sceneObject{mugOut, table, lampBase}, onTable, []string{"chimera", "coffee", "cup"}, nil), ""},
		{"or that the camera should zoom in", "A scene of a cup on a table: zoomed in on the table.", scene([]sceneObject{mugOut, table, lampBase}, onTable, []string{"chimera", "coffee", "cup"}, nil), ""},
		{"or where it stands", "A scene of a cup on a table with the camera at (1, 2, 3).", scene([]sceneObject{mugOut, table, lampBase}, onTable, []string{"chimera", "coffee", "cup"}, nil), ""},
		{"unless that's everything", "A scene of a cup and a table, and a camera that frames everything.", scene([]sceneObject{mugCut, table, lampBase}, onTable, []string{"chimera", "coffee", "cup"}, nil), "doesn't show chimera_coffee_cup"},
		{"the person's own file", "Put a cup on the table in my scene.", scene([]sceneObject{mugOut, table, lampBase}, onTable, []string{"chimera", "coffee", "cup"}, nil), ""},
		{"it moves", cup, scene([]sceneObject{mugOut, table, lampBase}, onTable, []string{"chimera", "coffee", "cup"}, func(f *sceneFacts) { f.Animated = true }), ""},
		{"not a scene", "Model a coffee cup on a table.", scene([]sceneObject{mugOut, table, lampBase}, onTable, []string{"chimera", "coffee", "cup"}, nil), ""},
		{"words that aren't things", "A camera scene with a light.", scene([]sceneObject{{Name: "camera_light"}, table}, []string{"chimera", "table"}, []string{"camera", "light"}, nil), ""},
	} {
		got := strings.Join(sceneFaults(c.f, c.goal, ""), " ")
		if (c.want == "") != (got == "") || !strings.Contains(got, c.want) {
			t.Errorf("%s: want %q, got %q", c.name, c.want, got)
		}
	}
	if m := measured(scene([]sceneObject{table}, nil, nil, func(f *sceneFacts) {
		f.Camera, f.Seen = nil, 0
		f.Pose = &scenePose{At: []float64{1, 2, 3}, Rotation: []float64{1, 0, 0}, Sees: 1}
	})); !strings.Contains(m, "add a camera, make it scene.camera") || strings.Contains(m, "out of frame") {
		t.Fatalf("with no camera there's nothing to be out of frame of: %s", m)
	}
	cut := scene([]sceneObject{mugCut, table}, []string{"chimera", "table"}, []string{"chimera", "coffee", "cup"}, nil)
	if m := measured(cut); !strings.Contains(m, "only 40% of it is in frame") || !strings.Contains(m, "1 of the 2 objects are out of frame") {
		t.Fatal(m)
	}
	if c := withScene(resultCheck{Outcome: "passed", Summary: "Ran."}, cut, "Add a torus to my file.", ""); !strings.Contains(c.Summary, "1 of its 2 objects are in the camera's frame.") {
		t.Fatal(c.Summary)
	}
	if c := withScene(resultCheck{Outcome: "passed", Summary: "Ran."}, cut, cup, ""); c.Outcome != "wrong_scene" || c.Seen != 0.5 {
		t.Fatalf("%+v", c)
	}
}

func TestWhatATaskNames(t *testing.T) {
	for goal, want := range map[string]string{
		"can u create a blender scene of a coffee cup on a table lit by a lamp also on the table": "cup table lamp table",
		"a still life of fruit on a table lit by a window":                                        "fruit table",
		"a scene of a table in sunlight coming through a window":                                  "table",
		"a scene of a kitchen counter with a kettle and a cutting board":                          "kettle board",
		"a scene of a coffee cup on a table with a lamp":                                          "cup table lamp",
		"a scene of a cup of tea on a table":                                                      "cup table",
		"a small wooden cabin near a lake":                                                        "cabin lake",
		"a jug with a cup on the left":                                                            "jug cup",
	} {
		if got := strings.Join(goalThings(goal), " "); got != want {
			t.Errorf("%s: got %q, want %q", goal, got, want)
		}
	}
}

func TestWhatCountsAsAScene(t *testing.T) {
	for _, goal := range []string{
		"can u create a blender scene of a coffee cup on a table lit by a lamp also on the table", "make me a cozy scene with a sofa and a rug", "blender scene of a desk with a laptop",
		"a scene of a bowl of fruit", "a still life of three apples", "Create a desert landscape with a cactus", "i want a scene with a red ball", "give me a low poly forest scene",
		"a diorama of a small harbour", "scene with a table and two chairs", "build the scene described below: a chair and a table", "show me a scene of a dog", "Render a scene of a mug",
		"could you do a scene with a car", "create a new scene", "a mountain landscape at dawn",
	} {
		if !newSceneRe.MatchString(goal) {
			t.Errorf("a scene: %s", goal)
		}
	}
	for _, goal := range []string{
		"model a chair", "make a coffee cup", "Make the scene darker", "Render the scene with Cycles", "Set the scene frame rate to 24", "Remove everything from the scene", "make a low poly island",
		"Set up a sky environment", "create a forest environment",
	} {
		if newSceneRe.MatchString(goal) {
			t.Errorf("not a scene: %s", goal)
		}
	}
	for _, goal := range []string{"add a cube to the scene", "create a cup in the scene", "Add a sun to my scene", "Fix the camera in this scene", "write an add-on that makes a scene",
		"Count the polygons in a scene with many objects", "make a landscape painting", "Create a scene collection for props"} {
		if !ownSceneRe.MatchString(goal) {
			t.Errorf("the person's own scene: %s", goal)
		}
	}
}

func TestTheSceneLineIsTakenOutAndUsed(t *testing.T) {
	line := sceneMarker + `{"camera":{"name":"cam","at":[0,-5,2],"ahead":[0,1,0],"lens":50,"type":"PERSP","own":true},"objects":[{"name":"mug","at":[9,9,9],"size":[1,1,1],"hits":0,"frame":false}],"total":1,"seen":0,"out":1,"filled":0,"cube":false,"empty":[],"animated":false,"span":[[8,8,8],[10,10,10]],"pose":{"at":[9,-3,9],"rotation":[1.5708,0,0],"sees":1,"clip_end":40}}`
	out := "Blender 5.2.2\n" + sceneStartMarker + "\n" + line + "\nBlender quit\n"
	c := judgeRun("run_blender", "Blender 5.2.2", frameAll, "import bpy\n", runResult{ExitCode: 0, Stderr: sceneStartMarker + "\n" + line + "\n", Output: out})
	if c.Outcome != "wrong_scene" || c.Error != "The camera sees none of the 1 objects." || strings.Contains(c.Output, "chimera-check") || c.Faults != 1 {
		t.Fatalf("%+v", c)
	}
	if !c.notDone() || !c.repairable() || c.grade() >= (resultCheck{Outcome: "passed"}).grade() {
		t.Fatalf("a wrong scene isn't done: %+v", c)
	}
	cr := sceneCritique("Blender 5.2.2", c)
	for _, want := range []string{"The camera sees none", "at (0.00, -5.00, 2.00)", "location = (9.00, -3.00, 9.00), rotation_euler = (1.5708, 0.0000, 0.0000), clip_end = 40 on its data", "rotation_mode = 'XYZ'", "no parent", "mug at (9.00, 9.00, 9.00), size (1.00, 1.00, 1.00): out of frame."} {
		if !strings.Contains(cr, want) {
			t.Fatalf("the critique has %q: %s", want, cr)
		}
	}
	if len([]rune(sceneCritique("B", resultCheck{Error: "e", Measured: strings.Repeat("x", 9000)}))) > 2400 {
		t.Fatal("a critique has a limit")
	}
	if !strings.Contains(hookedSummary(t), "2 of its 2 objects are in the camera's frame.") {
		t.Fatal("a scene that's fine says what was measured")
	}
	// Measuring started and never finished: the script had ended, so it passed.
	heavy := "Blender 5.2.2\n" + sceneStartMarker + "\n"
	for _, res := range []runResult{{TimedOut: true, Output: heavy}, {ExitCode: 139, Output: heavy}, {ExitCode: 0, Output: heavy}} {
		if c := judgeRun("run_blender", "Blender 5.2.2", frameAll, "import bpy\n", res); c.Outcome != "passed" {
			t.Fatalf("too heavy to measure isn't the script's fault: %+v", c)
		}
	}
	// A bad line says nothing.
	if _, f, _ := takeScene(runResult{Output: sceneMarker + "not json\n"}); f != nil {
		t.Fatalf("%+v", f)
	}
	after := "Blender 5.2.2\n" + sceneStartMarker + "\nTraceback (most recent call last):\n  File \"script.py\", line 3, in h\nValueError: from a handler\n\nBlender quit\n"
	if c := judgeRun("run_blender", "Blender 5.2.2", frameAll, "import bpy\n", runResult{Output: after, Stderr: after}); c.Outcome != "passed" {
		t.Fatalf("what measuring sets off isn't the script's fault: %+v", c)
	}
	mixed := "Blender 5.2.2\n" + sceneStartMarker + "\n" + renderStopMarker + "\n"
	if c := judgeRun("run_blender", "Blender 5.2.2", frameAll, "import bpy\n", runResult{Output: mixed, Stderr: sceneStartMarker + "\n"}); !strings.Contains(c.Summary, "render") {
		t.Fatalf("the render stop can come after the measuring starts: %+v", c)
	}
	if c := judgeRun("run_blender", "Blender 5.2.2", "", "import bpy\n", runResult{TimedOut: true, Output: "still going"}); c.Outcome != "unsure" {
		t.Fatalf("a script that never finished is still unsure: %+v", c)
	}
}

func hookedSummary(t *testing.T) string {
	t.Helper()
	return withScene(resultCheck{Outcome: "passed", Summary: "Ran it."}, facts(nil), frameAll, "").Summary
}

func TestAWrongSceneStopsWhenItStopsImproving(t *testing.T) {
	five := resultCheck{Outcome: "wrong_scene", Error: "a, b and 5 more are out of frame.", Faults: 1, Seen: 0.5}
	six := resultCheck{Outcome: "wrong_scene", Error: "a, b and 6 more are out of frame.", Faults: 1, Seen: 0.4}
	if !six.sameFault(five) {
		t.Fatal("the count moving the wrong way is the same fault")
	}
	better := resultCheck{Outcome: "wrong_scene", Error: "a, b and 2 more are out of frame.", Faults: 1, Seen: 0.8}
	if better.sameFault(five) {
		t.Fatal("more in frame is progress")
	}
	// Taking the cube out shouldn't count as worse because what's left is in frame less.
	two := resultCheck{Outcome: "wrong_scene", Faults: 2, Seen: 0.9}
	if one := (resultCheck{Outcome: "wrong_scene", Faults: 1, Seen: 0.2}); one.grade() <= two.grade() {
		t.Fatalf("fewer faults first: %v, %v", one.grade(), two.grade())
	}
	partway := resultCheck{Outcome: "unsure", Partway: true}
	if partway.grade() >= two.grade() || partway.grade() <= (resultCheck{Outcome: "failed"}).grade() {
		t.Fatal("a script stopped part-way is below one that ran to its end, and above a sure crash")
	}
	stopped := "Traceback (most recent call last):\n  File \"script.py\", line 3, in <module>\n    os.mkdir('/nope')\nOSError: no\n\nError: script failed, file: 'script.py', exiting.\n"
	if c := judgeRun("run_blender", "Blender 5.2.2", "", "import bpy, os\n\nos.mkdir('/nope')\n", runResult{ExitCode: 1, Stderr: stopped, Output: stopped}); c.Outcome != "unsure" || !c.Partway {
		t.Fatalf("%+v", c)
	}
	two.Outcome, two.Error, two.Runner = "wrong_scene", "The camera sees none", "Blender 5.2.2"
	main := "import bpy\nx = 1\ny = 2\nz = 3\na = 4\nb = 5\n"
	result := fenced("python", main) + fenced("python", "bpy.context.scene.camera = cam\n")
	if c := otherBlocks(two, result, main); c.Outcome != "unsure" || c.Error != "" {
		t.Fatalf("another block may hold the rest of the scene: %+v", c)
	}
}

func TestSavingToTheTopOfTheDiskIsTheScripts(t *testing.T) {
	const headless = "A table, runnable with blender -b --python."
	script := "import bpy\nimport os\n\nbpy.ops.wm.save_as_mainfile(filepath=os.path.join(os.path.dirname(bpy.data.filepath), 'x.blend'))\n"
	for _, msg := range []string{"Operation not permitted", "Read-only file system"} {
		out := "Traceback (most recent call last):\n  File \"script.py\", line 4, in <module>\n    bpy.ops.wm.save_as_mainfile(filepath='/x.blend')\nRuntimeError: Error: Cannot open file /x.blend@ for writing: " + msg + "\n\nError: script failed, file: 'script.py', exiting.\n"
		c := judgeRun("run_blender", "Blender 5.2.2", headless, script, runResult{ExitCode: 1, Stderr: out, Output: out})
		if c.Outcome != "failed" || !strings.Contains(crashCritique("run_blender", "Blender 5.2.2", c), "bpy.data.filepath is empty") {
			t.Fatalf("%s: %+v", msg, c)
		}
		if c := judgeRun("run_blender", "Blender 5.2.2", "A table.", script, runResult{ExitCode: 1, Stderr: out, Output: out}); c.Outcome != "unsure" {
			t.Fatalf("with no -b, the file may have a path: %+v", c)
		}
		if c := judgeRun("run_blender", "Blender 5.2.2", headless, "import bpy, sys\n\nout = sys.argv[-1]\nbpy.ops.wm.save_as_mainfile(filepath=out)\n", runResult{ExitCode: 1, Stderr: out, Output: out}); c.Outcome != "unsure" {
			t.Fatalf("a path it's meant to be given: %+v", c)
		}
	}
	out := "Traceback (most recent call last):\n  File \"script.py\", line 4, in <module>\n    bpy.ops.wm.save_as_mainfile(filepath='/Users/me/x.blend')\nRuntimeError: Error: Cannot open file /Users/me/x.blend@ for writing: Operation not permitted\n\nError: script failed, file: 'script.py', exiting.\n"
	if c := judgeRun("run_blender", "Blender 5.2.2", headless, script, runResult{ExitCode: 1, Stderr: out, Output: out}); c.Outcome != "unsure" {
		t.Fatalf("a folder of yours may just be the sandbox: %+v", c)
	}
}

// Real Blender, when there's one here. CHIMERA_TEST_BLENDER picks a version.
func TestRealBlenderMeasuresTheScene(t *testing.T) {
	path := os.Getenv("CHIMERA_TEST_BLENDER")
	if path == "" {
		path, _ = findBlender()
	}
	if path == "" {
		t.Skip("no Blender here")
	}
	const clear = "import bpy\nimport math\nbpy.ops.object.select_all(action='SELECT')\nbpy.ops.object.delete()\n"
	const table = "bpy.ops.mesh.primitive_cylinder_add(radius=1, depth=0.1, location=(0, 0, 0.75))\nbpy.context.object.name = 'table'\nbpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=0.2, location=(0.3, 0, 0.9))\nbpy.context.object.name = 'mug'\n"
	const cameraAt = "cd = bpy.data.cameras.new('c')\ncam = bpy.data.objects.new('c', cd)\nbpy.context.scene.collection.objects.link(cam)\nbpy.context.scene.camera = cam\ncam.location = (0, -5, 3)\n"
	const overEdge = "from mathutils import Vector\nbpy.context.view_layer.update()\nf = cam.data.view_frame(scene=bpy.context.scene)\nbpy.ops.mesh.primitive_uv_sphere_add(radius=0.2, location=cam.matrix_world @ (((f[0] + f[1]) / 2 * 8) + Vector((0.08, 0, 0))))\nbpy.context.object.name = 'ball'\n"
	const lookAtTable = "t = bpy.data.objects['table']\ncon = cam.constraints.new('TRACK_TO')\ncon.target = t\ncon.track_axis = 'TRACK_NEGATIVE_Z'\ncon.up_axis = 'UP_Y'\n"
	for _, c := range []struct{ name, script, goal, outcome, has string }{
		{"a good scene", clear + table + cameraAt + lookAtTable, frameAll, "passed", "2 of its 2 objects are in the camera's frame."},
		{"the view it offers works", clear + table + cameraAt + "cam.rotation_euler = (math.radians(-90), 0, 0)\nPOSE", frameAll, "passed", "2 of its 2 objects are in the camera's frame."},
		{"looking away", clear + table + cameraAt + "cam.rotation_euler = (math.radians(-90), 0, 0)\n", frameAll, "wrong_scene", "The camera sees none of the 2 objects."},
		{"out of frame", clear + table + cameraAt + lookAtTable + "bpy.ops.mesh.primitive_uv_sphere_add(radius=0.2, location=(40, 0, 1))\nbpy.context.object.name = 'ball'\n", frameAll, "wrong_scene", "ball is out of frame."},
		{"the default cube", "import bpy\nbpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(4, 0, 0))\n", "A scene with a sphere and a camera that frames everything.", "wrong_scene", "The default cube is still in the scene."},
		{"no geometry", clear + "m = bpy.data.meshes.new('water')\no = bpy.data.objects.new('water', m)\nbpy.context.scene.collection.objects.link(o)\n" + table, "Build a table.", "wrong_scene", "water has no geometry."},
		{"no camera", clear + table, frameAll, "wrong_scene", "The scene has no camera."},
		{"stopped at its render, as most are", clear + table + cameraAt + "cam.rotation_euler = (math.radians(-90), 0, 0)\nbpy.ops.render.render(write_still=False)\n", frameAll, "wrong_scene", "The camera sees none"},
		{"something inside something isn't out", clear + table + cameraAt + lookAtTable + "bpy.ops.mesh.primitive_uv_sphere_add(radius=0.01, location=(0, 0, 0.75))\n", frameAll, "passed", "3 of its 3 objects are in the camera's frame."},
		{"an ortho camera", clear + table + cameraAt + "cd.type = 'ORTHO'\ncd.ortho_scale = 4\n" + lookAtTable, frameAll, "passed", "2 of its 2 objects are in the camera's frame."},
		{"things in a glass case", clear + table + cameraAt + lookAtTable + "bpy.ops.mesh.primitive_uv_sphere_add(radius=2, location=(0, 0, 0.8))\ng = bpy.data.materials.new('glass')\ng.use_nodes = True\nbpy.context.object.data.materials.append(g)\n", frameAll, "passed", ""},
		{"many tiny things", clear + cameraAt + "cam.location = (0, -30, 0)\ncam.rotation_euler = (math.radians(90), 0, 0)\nimport random\nfor i in range(60):\n    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.004, segments=8, ring_count=6, location=(random.uniform(-3, 3), 0, random.uniform(-3, 3)))\n", frameAll, "passed", ""},
		{"light cards off to the side", clear + table + cameraAt + lookAtTable + "bpy.ops.mesh.primitive_plane_add(size=2, location=(30, 0, 3))\nc = bpy.context.object\nm = bpy.data.materials.new('soft')\nm.use_nodes = True\nm.node_tree.nodes['Principled BSDF'].inputs['Emission Strength'].default_value = 5\nc.data.materials.append(m)\n", frameAll, "passed", ""},
		{"a guide curve off to the side", clear + table + cameraAt + lookAtTable + "bpy.ops.curve.primitive_bezier_circle_add(location=(40, 0, 0))\n", frameAll, "passed", ""},
		{"a helper collection that doesn't render", clear + table + cameraAt + lookAtTable + "h = bpy.data.collections.new('helpers')\nbpy.context.scene.collection.children.link(h)\nh.hide_render = True\nbpy.ops.mesh.primitive_uv_sphere_add(location=(40, 0, 0))\no = bpy.context.object\nold = o.users_collection[0]\nh.objects.link(o)\nold.objects.unlink(o)\n", frameAll, "passed", ""},
		{"its own cube at the origin", clear + cameraAt + "bpy.ops.mesh.primitive_cube_add(size=2)\nbpy.ops.mesh.primitive_uv_sphere_add(location=(2, 0, 0))\ncam.rotation_euler = (1.0, 0, 0)\n", "Build a scene with a box and a ball, with a camera.", "passed", ""},
		{"a picture frame with no camera", clear + "bpy.ops.mesh.primitive_torus_add()\n", "Model a wooden picture frame.", "passed", ""},
		{"left in edit mode", clear + table + cameraAt + lookAtTable + "bpy.ops.object.mode_set(mode='EDIT')\n", frameAll, "passed", ""},
		{"a second scene", clear + table + "s = bpy.data.scenes.new('other')\no = bpy.data.objects.new('e', None)\ns.collection.objects.link(o)\n", frameAll, "passed", ""},
		{"the wall behind a camera in a room", clear + "for name, x, y, sx, sy in (('n', 0, 5, 5, 0.1), ('s', 0, -5, 5, 0.1), ('e', 5, 0, 0.1, 5), ('w', -5, 0, 0.1, 5)):\n    bpy.ops.mesh.primitive_cube_add(location=(x, y, 1.5))\n    bpy.context.object.name = name\n    bpy.context.object.scale = (sx, sy, 1.5)\nbpy.ops.mesh.primitive_uv_sphere_add(location=(0, 3, 1))\nbpy.context.object.name = 'sofa'\n" + cameraAt + "cam.location = (0, -4, 1.5)\ncam.rotation_euler = (math.radians(90), 0, 0)\n", frameAll, "passed", ""},
		{"a big box under a camera looking down", clear + "bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, -1))\nbpy.context.object.name = 'soil'\nbpy.context.object.scale = (100, 100, 2)\nbpy.ops.mesh.primitive_uv_sphere_add(location=(0, 0, 1))\n" + cameraAt + "cam.location = (0, -6, 6)\ncam.rotation_euler = (math.radians(45), 0, 0)\n", frameAll, "passed", ""},
		{"a ceiling hidden from the render", clear + table + cameraAt + "cam.location = (0, 0, 6)\ncam.rotation_euler = (0, 0, 0)\nbpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 4))\nc = bpy.context.object\nc.scale = (20, 20, 0.2)\nc.hide_render = True\n", frameAll, "passed", ""},
		{"a cube it keeps and recolours", "import bpy\nbox = bpy.context.active_object\nbox.data.materials[0].node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0, 0, 1, 1)\nbpy.ops.mesh.primitive_plane_add(size=9, location=(0, 0, -1))\n", "Build a scene with a blue box on a floor.", "passed", ""},
		{"too far for its clip_end", clear + table + cameraAt + "cam.location = (0, -500, 1)\ncam.rotation_euler = (math.radians(90), 0, 0)\ncd.clip_end = 100\n", frameAll, "wrong_scene", "The camera sees none"},
		{"nobody asked about a camera", "import bpy\nbpy.ops.mesh.primitive_torus_add(location=(50, 0, 0))\n", "Add a torus to my file.", "passed", ""},
		{"a sphere made with no segments, as a real repair did", clear + table + cameraAt + lookAtTable + "import bmesh\nm = bpy.data.meshes.new('apple')\nbm = bmesh.new()\nbmesh.ops.create_uvsphere(bm, radius=1.0)\nbm.to_mesh(m)\nbm.free()\nm.materials.append(bpy.data.materials.new('red'))\nbpy.context.scene.collection.objects.link(bpy.data.objects.new('apple', m))\n", "Build a table scene.", "wrong_scene", "apple has no geometry."},
		{"points left as a guide", clear + table + cameraAt + lookAtTable + "m = bpy.data.meshes.new('guide')\nm.from_pydata([(0, 0, 0), (1, 0, 0)], [(0, 1)], [])\nbpy.context.scene.collection.objects.link(bpy.data.objects.new('guide', m))\n", "Build a table scene.", "passed", ""},
		{"a scene needs a camera", clear + table, "A scene of a table.", "wrong_scene", "The scene has no camera."},
		{"the view it offers a scene with none", clear + table + "POSE", "A scene of a table.", "passed", "2 of its 2 objects are in the camera's frame."},
		{"what the task named is out of shot", clear + table + cameraAt + lookAtTable + "bpy.ops.mesh.primitive_uv_sphere_add(radius=0.2, location=(40, 0, 1))\nbpy.context.object.name = 'ball'\n", "A scene of a table and a ball.", "wrong_scene", "doesn't show ball"},
		{"what it didn't name is its own business", clear + table + cameraAt + lookAtTable + "bpy.ops.mesh.primitive_uv_sphere_add(radius=0.2, location=(40, 0, 1))\nbpy.context.object.name = 'ball'\n", "A scene of a table.", "passed", "2 of its 3 objects"},
		{"most of it is over the edge of the frame", clear + table + cameraAt + lookAtTable + overEdge, "A scene of a table and a ball.", "wrong_scene", "doesn't show ball"},
		{"a fence the viewport doesn't show", clear + table + cameraAt + lookAtTable + "bpy.ops.mesh.primitive_cube_add(size=1, location=(-40, 0, 1))\nbpy.context.object.name = 'fence'\nm = bpy.context.object.modifiers.new('a', 'ARRAY')\nm.count = 80\nm.show_viewport = False\n", "A scene of a table and a fence.", "passed", ""},
		{"an animated camera", clear + table + cameraAt + "cam.rotation_euler = (math.radians(-90), 0, 0)\ncam.keyframe_insert('location', frame=1)\n", frameAll, "passed", ""},
	} {
		dir := t.TempDir()
		script := filepath.Join(dir, "script.py")
		if err := os.WriteFile(script, []byte(c.script), 0o600); err != nil {
			t.Fatal(err)
		}
		text := c.script
		if strings.HasSuffix(text, "POSE") { // what the first run offers goes into a second
			text = strings.TrimSuffix(text, "POSE")
			if err := os.WriteFile(script, []byte(text), 0o600); err != nil {
				t.Fatal(err)
			}
			res, f, _ := takeScene(realBlender(t, path, script, blenderStopAtRender+blenderCrashNames+blenderSceneFacts, blenderMeasureScene))
			if f == nil || f.Pose == nil || f.Pose.Sees != f.Total {
				t.Fatalf("%s: %+v\n%s", c.name, f, res.Output)
			}
			if f.Camera == nil {
				text += cameraAt
			}
			text += fmt.Sprintf("cam.location = %s\ncam.rotation_euler = (%f, %f, %f)\n", coords(f.Pose.At), f.Pose.Rotation[0], f.Pose.Rotation[1], f.Pose.Rotation[2])
			if err := os.WriteFile(script, []byte(text), 0o600); err != nil {
				t.Fatal(err)
			}
		}
		res := realBlender(t, path, script, blenderStopAtRender+blenderCrashNames+blenderSceneFacts, blenderMeasureScene)
		if c.name == "the default cube" && strings.Contains(res.Output, "Blender 3.") {
			continue // no session_uid there, so it can't prove the cube is the original
		}
		got := judgeRun("run_blender", "Blender", c.goal, text, res)
		if got.Outcome != c.outcome || !strings.Contains(got.Summary, c.has) {
			t.Errorf("%s: want %s with %q, got %s: %s\n%s", c.name, c.outcome, c.has, got.Outcome, got.Summary, res.Output)
		}
	}
}
