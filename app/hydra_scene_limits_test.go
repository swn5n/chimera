package main

import (
	"fmt"
	"strings"
	"testing"
)

// namedFacts is a scene of named objects, its counts worked out the way blenderSceneFacts does.
func namedFacts(objects []sceneObject, shown, hidden []string, mod func(f *sceneFacts)) *sceneFacts {
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

// Since addsRe went in, a script with nothing added can't reach the rest of the
// cube rule, so these need a script that adds something.
func TestSceneLimitsCubeGuards(t *testing.T) {
	const adds = "bpy.ops.mesh.primitive_plane_add()\n"
	for _, c := range []struct{ name, goal, script string }{
		{"the task is about a cube", "Build a scene with a red cube.", adds},
		{"or cubes", "Build a scene of three cubes.", adds},
		{"the script names it, after adding", frameAll, adds + "c = bpy.data.objects['Cube']\n"},
		{"in double quotes", frameAll, adds + "c = bpy.data.objects[\"Cube\"]\n"},
		{"the person's own file", "Build a tabletop scene in my project.", adds},
		{"not a new scene", "Model a table.", adds},
	} {
		if got := sceneFaults(facts(func(f *sceneFacts) { f.Cube = true }), c.goal, c.script); len(got) > 0 {
			t.Errorf("%s: %q", c.name, got)
		}
	}
}

func TestSceneLimitsSeesNothingGuards(t *testing.T) {
	for _, c := range []struct {
		name, goal string
		f          *sceneFacts
		want       string
	}{
		{"in frame, and too small for the rays", frameAll, facts(func(f *sceneFacts) { f.Seen, f.Out, f.Filled = 0, 0, 0 }), ""},
		{"a volume rays can't reach, the rest out of frame", "A scene of a cloud.", facts(func(f *sceneFacts) { f.Seen, f.Out, f.Filled, f.Unseen = 0, 2, 0, true }), ""},
		{"nothing it could measure", "A scene of a chair.", facts(func(f *sceneFacts) { f.Objects, f.Total, f.Seen, f.Out, f.Filled = nil, 0, 0, 0, 0 }), ""},
		{"a goal that isn't a scene, but says everything", "Build a chair, with a camera that frames everything.", facts(func(f *sceneFacts) { f.Seen, f.Out, f.Filled = 0, 2, 0 }), "sees none"},
		{"an empty scene isn't an excuse once it has things in it", "Create an empty scene with a table.", facts(func(f *sceneFacts) { f.Camera = nil }), "no camera"},
	} {
		got := strings.Join(sceneFaults(c.f, c.goal, ""), " ")
		if (c.want == "") != (got == "") || !strings.Contains(got, c.want) {
			t.Errorf("%s: want %q, got %q", c.name, c.want, got)
		}
	}
}

func TestSceneLimitsOwnFileAndGeometryGuards(t *testing.T) {
	noCamera := func(f *sceneFacts) { f.Camera = nil }
	blank := func(f *sceneFacts) { f.Empty, f.Blank = []string{"a"}, 1 }
	for _, c := range []struct {
		name, goal string
		f          *sceneFacts
	}{
		{"my scene needs no new camera", "Render my scene and frame everything.", facts(noCamera)},
		{"my scene can hold an empty mesh", "Add a plane to my scene.", facts(blank)},
		{"what plays may fill it later", "Add a torus.", facts(func(f *sceneFacts) { blank(f); f.Animated = true })},
		{"a scene with nothing in it", "A scene with nothing in it.", facts(func(f *sceneFacts) { noCamera(f); f.Objects, f.Total = nil, 0 })},
	} {
		if got := sceneFaults(c.f, c.goal, ""); len(got) > 0 {
			t.Errorf("%s: %q", c.name, got)
		}
	}
}

// Only showing nothing asked for is wrong from among the objects or with a second camera.
func TestSceneLimitsNoneNamedShown(t *testing.T) {
	table := sceneObject{Name: "table", Hits: 900, Frame: true}
	mug, bowl := sceneObject{Name: "mug"}, sceneObject{Name: "bowl"}
	two := func(f *sceneFacts) { f.Cameras = 2 }
	for _, c := range []struct {
		name, goal string
		f          *sceneFacts
	}{
		{"one thing shown, two not", "A scene of a mug, a bowl and a table.", namedFacts([]sceneObject{mug, bowl, table}, []string{"table"}, []string{"bowl", "mug"}, two)},
		{"only one named thing is in the scene", "A scene of a mug on a shelf.", namedFacts([]sceneObject{mug, table}, []string{"table"}, []string{"mug"}, two)},
		{"and just the one was named", "A scene of a mug.", namedFacts([]sceneObject{mug, table}, []string{"table"}, []string{"mug"}, two)},
	} {
		if got := sceneFaults(c.f, c.goal, ""); len(got) > 0 {
			t.Errorf("%s: %q", c.name, got)
		}
	}
}

func TestSceneLimitsWhatGetsNamed(t *testing.T) {
	table := sceneObject{Name: "table", Hits: 900, Frame: true}
	// Other things out of shot that the task didn't ask for aren't named to the repair.
	f := namedFacts([]sceneObject{{Name: "mug"}, {Name: "rug"}, table}, []string{"table"}, []string{"mug", "rug"}, nil)
	if got := strings.Join(sceneFaults(f, "A scene of a mug on a table.", ""), " "); !strings.Contains(got, "doesn't show mug,") && !strings.Contains(got, "doesn't show mug ") || strings.Contains(got, "rug") {
		t.Errorf("only what it named: %q", got)
	}
	// Named twice, listed once.
	f = namedFacts([]sceneObject{table}, []string{"table"}, []string{"mug"}, nil)
	if got := unshown("a mug by a mug and a lamp", f); len(got) != 1 {
		t.Errorf("a word once: %q", got)
	}
	// A word that's hidden with no object in the list still counts: the list has a limit.
	if got := unshown("a mug on a table", namedFacts([]sceneObject{table}, []string{"table"}, []string{"mug"}, nil)); len(got) != 1 || got[0] != "mug" {
		t.Errorf("a word with no object listed: %q", got)
	}
	if got := unshown("a lamp and a shade", namedFacts([]sceneObject{{Name: "Lamp_Shade"}, table}, []string{"table"}, []string{"lamp", "shade"}, nil)); len(got) != 1 {
		t.Errorf("one object, once: %q", got)
	}
	if !hasWord([]string{"cups"}, "cup") || !hasWord([]string{"cup"}, "cups") || !hasWord([]string{"boxes"}, "box") || !hasWord([]string{"box"}, "boxes") {
		t.Error("plurals, either way, also on short words")
	}
	cam := namedFacts([]sceneObject{{Name: "CoffeeCup"}, table}, []string{"table"}, []string{"coffee", "cup"}, nil)
	if got := strings.Join(sceneFaults(cam, "A scene of a cup on a table.", ""), " "); !strings.Contains(got, "CoffeeCup") {
		t.Errorf("a name in camel case: %q", got)
	}
	if m := measured(namedFacts([]sceneObject{{Name: "mug"}}, nil, nil, func(f *sceneFacts) { f.Camera = nil })); !strings.Contains(m, "mug at") || !strings.Contains(m, "in the scene.") {
		t.Errorf("with no camera it's not out of frame: %s", m)
	}
}

func TestSceneLimitsGoalThings(t *testing.T) {
	for goal, want := range map[string]string{
		// every break that ends a noun phrase
		"a jug or a cup": "jug cup", "a jug at a desk": "jug desk", "a jug by a sink": "jug sink", "a row of trees": "row trees",
		"a jug next to a cup": "jug cup", "a jug under a shelf": "jug shelf", "a jug over a sink": "jug sink", "a jug beside a cup": "jug cup",
		"a jug behind a cup": "jug cup", "a jug that holds flowers": "jug flowers", "a jug which holds flowers": "jug flowers",
		"a jug from a shop": "jug shop", "a jug for a guest": "jug guest", "a jug plus a cup": "jug cup", "a fence around a garden": "fence garden",
		"a man standing on a hill": "man hill", "a cat sitting on a mat": "cat mat", "a jug to a cup": "jug cup", "a car parked on a street": "car street",
		"A JUG ON A TABLE": "jug table", "A Jug On A Table": "jug table",
		// two letters are no thing
		"go to a shop": "shop",
		// position words
		"a jug on the left": "jug", "a jug on the right": "jug", "a jug on top": "jug", "a jug on the top": "jug", "a jug at the bottom": "jug", "a jug at the front": "jug",
		"a jug at the back": "jug", "a jug to the side": "jug", "a jug on both sides": "jug", "a jug in the middle": "jug", "a jug in the center": "jug", "a jug in the centre": "jug",
		"a jug in the corner": "jug", "a jug on the edge": "jug", "a jug is next to a cup": "cup", "a jug is near.": "", "a jug is behind.": "",
		"a jug and a shelf above": "jug", "a jug and a shelf below": "jug",
		// what isn't a thing to see
		"a jug in blender": "jug", "a jug in a landscape": "jug", "a jug in an environment": "jug", "a jug in a diorama": "jug", "a jug and a camera": "jug",
		"a jug in the sun": "jug", "a jug and two lights": "jug", "a jug with soft lighting": "jug", "a jug and a light": "jug", "a jug with a mesh": "jug", "a jug and a render": "jug", "a jug and a model": "jug",
		"a jug and some objects": "jug", "a jug and an object": "jug", "a jug in a script": "jug", "a jug in chimera": "jug", "a jug in python": "jug", "a jug and the main part": "jug",
		"a jug in parts": "jug", "a jug and a cup if you can": "jug", "a jug and a cup if you could": "jug", "a jug and a cup if you will": "jug", "a jug and a cup if you would": "jug", "a jug to use": "jug", "a jug by using": "jug",
		"a jug in the main": "jug",
	} {
		if got := strings.Join(goalThings(goal), " "); got != want {
			t.Errorf("%s: got %q, want %q", goal, got, want)
		}
	}
}

func TestSceneLimitsLightsContentsAndSettings(t *testing.T) {
	for goal, want := range map[string]string{
		// A light says where it stands: "on the left" isn't a place in the shot.
		"a jug on a table lit by a window on the left":   "jug table",
		"a jug on a table lit by a window on the right":  "jug table",
		"a jug on a table lit by a window to the side":   "jug table",
		"a jug on a table lit by a lamp from above":      "jug table",
		"a jug on a table lit by a lamp from the above":  "jug table",
		"a jug on a table lit by a window on the wall":   "jug table",
		"a jug on a table lit by a lamp on the ceiling":  "jug table",
		"a jug on a table lit by a lamp to the left":     "jug table",
		"a jug on a table lit by a lamp from the left":   "jug table",
		"a jug on a table illuminated by a window":       "jug table",
		"a jug on a table lit from a window":             "jug table",
		"a jug on a table lit through a window":          "jug table",
		"a jug on a table in moonlight through a window": "jug table",
		"a jug on a table lit by the window":             "jug table",
		"a jug on a table lit by a tall window":          "jug table",
		// Unless it stands in the shot.
		"a jug on a table lit by a lamp on a desk": "jug table lamp desk",
		// What's in something.
		"a mug of coffee": "mug", "a glass of wine": "glass", "a bowl of soup": "bowl", "a plate of cookies": "plate", "a bottle of wine": "bottle", "a jar of honey": "jar",
		"a vase of flowers": "vase", "a basket of apples": "basket", "a pot of tea": "pot", "a stack of papers": "stack", "a pile of leaves": "pile", "a cup of hot tea": "cup",
		// Where, then what.
		"a diorama of a farm with a barn": "barn", "a landscape of a valley with a river": "river", "a scene of farm with a barn": "barn", "a scene of the farm with a barn": "barn", "a scene of a small red farm with a barn": "barn",
	} {
		if got := strings.Join(goalThings(goal), " "); got != want {
			t.Errorf("%s: got %q, want %q", goal, got, want)
		}
	}
}

func TestSceneLimitsNoCameraWords(t *testing.T) {
	for _, goal := range []string{
		"A scene of a chair. It doesn't need a camera.", "A scene of a chair. It does not need a camera.", "A scene of a chair. Skip the camera.", "A scene of a chair. Omit the camera.",
		"A scene of a chair. Leave out the camera.", "A scene of a chair with no real studio camera.", "A scene of a chair. The camera is not needed.",
		"A scene of a chair. I'll add the camera myself.", "A scene of a chair. I'll add the camera later.",
	} {
		if !noCameraRe.MatchString(goal) {
			t.Errorf("no camera wanted: %s", goal)
		}
	}
	for _, goal := range []string{
		"A scene of a chair with no cameraman.",                        // a word that starts with camera
		"No lamp. A scene of a chair and a camera. Add a table later.", // later is in another sentence: the camera is still wanted
	} {
		if noCameraRe.MatchString(goal) {
			t.Errorf("a camera may be wanted: %s", goal)
		}
	}
}

func TestSceneLimitsOwnScene(t *testing.T) {
	for _, goal := range []string{
		"create a cup on the scene", "make a cup in the scene",
		"Count the polygons in a scene", "Add fog to a scene", "Put a lamp into a scene", "Bake lighting for a scene", "Copy a light from a scene",
		"Get the objects of a scene", "Spread trees across a scene", "Scatter rocks throughout a scene", "Count the polygons in a very big scene",
		"Build a scene graph", "Sort the scene collection", "Apply a scene-wide light", "Add a scene strip", "Add a scene transition", "Add a scene node", "Change the scene properties", "Change the scene settings", "Read the scene data", "Set the scene units",
		"Paint a landscape painting", "Set a landscape format", "Use landscape orientation", "Use landscape mode", "Print a landscape poster", "Take a landscape photo", "Hang a landscape picture", "Make a landscape print",
	} {
		if !ownSceneRe.MatchString(goal) {
			t.Errorf("the person's own scene: %s", goal)
		}
	}
}

func TestSceneLimitsShotGoals(t *testing.T) {
	for _, goal := range []string{
		"a camera that frames the cup", "a camera which looks down", "a camera to show the cup", "a camera that frames it", "the camera should see the cup", "the camera must see the cup", "the camera will see the cup",
		"the camera shall see the cup", "the camera needs to see the cup", "the camera has to see the cup", "the camera is to show the cup", "the cameras are to show the cup",
		"the camera should clearly just see the cup", "a camera that sees the cup", "a camera that shows the cup", "a camera that looks down", "a camera that captures the cup", "a camera that points down", "a camera that aims down", "a camera that focuses down",
		"a camera looking down", "a camera aimed down", "a camera pointed down", "a camera pointing down", "a camera focused down", "a camera facing down", "a camera at eye level", "a camera on a tripod",
		"a camera in front of the door", "a camera behind the door", "a camera above the door", "a camera below the door", "a camera beside the door", "a camera near the door", "a camera 2 m away",
		"aim the camera down", "point the camera down", "put the camera low", "place the camera low", "position the camera low", "move the camera low", "set the camera low", "tilt the camera down",
		"aim a camera down", "aim your camera down", "aim the main top camera down", "a 35 mm camera", "a 2 metre camera", "a 2 meter camera", "framing the cup", "frames a cup", "frame an apple",
		"zoomed out", "focused on the cup", "a tight shot", "a tight framing", "with depth of field",
	} {
		if !shotGoalRe.MatchString(goal) {
			t.Errorf("says what the camera is for: %s", goal)
		}
	}
	for _, goal := range []string{
		"a close-up", "a closeup", "macro", "cropped", "a detail shot", "a detail view", "a portrait", "just out of shot", "out of frame", "out of view", "off camera", "off-screen", "offframe", "behind the camera",
		"it reflects the sky", "reflected in a mirror", "its reflection", "a silhouette", "shadows of trees", "the shadow from a tree", "shadow cast by a tree", "first-person", "first person", "a pov",
	} {
		if !tightGoalRe.MatchString(goal) {
			t.Errorf("wants some of it out of shot: %s", goal)
		}
	}
}

func TestSceneLimitsNewScene(t *testing.T) {
	for _, goal := range []string{
		"i want a night scene", "Render a night scene", "show me a night scene", "i need a cozy scene", "give me a scene of a dog", "draw a forest scene", "produce a night scene", "Render a scene of a mug", "show me a scene of a dog",
		"build me a cozy landscape", "make us a diorama", "build the scene described below: a chair", "Build the scene of a farm", "a mountain landscape at dawn", "a still life of apples", "a diorama of a port",
		"Create a desert landscape", "Create a fruit still life", "make a harbour diorama", "could you do a scene with a car", "blender scene of a desk", "3d scene of a desk", "scene with a table",
	} {
		if !newSceneRe.MatchString(goal) {
			t.Errorf("a scene: %s", goal)
		}
	}
}

func TestSceneLimitsMissingGuards(t *testing.T) {
	const scene = "create a blender scene of a coffee cup on a table"
	tbn := func(line int, src, msg string) string {
		return fmt.Sprintf("Traceback (most recent call last):\n  File \"script.py\", line %d, in <module>\n    %s\n%s\n\nError: script failed, file: 'script.py', exiting.\n", line, src, msg)
	}
	none := "AttributeError: 'NoneType' object has no attribute 'view_matrix'"
	for _, c := range []struct{ name, kept string }{
		{"region", "v = bpy.context.region"}, {"region_data", "v = bpy.context.region_data"}, {"area", "v = bpy.context.area"}, {"space_data", "v = bpy.context.space_data"}, {"window", "v = bpy.context.window"},
		{"context", "v = context.region_data"}, {"ctx", "v = ctx.region_data"}, {"C", "v = C.region_data"},
	} {
		script := "import bpy\n" + c.kept + "\nm = v.view_matrix\n"
		out := tbn(3, "m = v.view_matrix", none)
		if got := judgeRun("run_blender", "Blender 5.2.2", scene, script, runResult{ExitCode: 1, Stderr: out, Output: out}); got.Outcome != "unsure" {
			t.Errorf("%s came from the window: %+v", c.name, got)
		}
	}
	for _, c := range []struct{ name, reads string }{
		{"exists", "os.path.exists('/x')"}, {"isfile", "os.path.isfile('/x')"}, {"Path", "Path('/x')"}, {"load", "bpy.data.images.load('/x')"}, {"open", "open('/x')"},
		{"import_", "bpy.ops.import_scene.gltf(filepath='/x')"}, {"_import", "bpy.ops.wm.obj_import(filepath='/x')"}, {"append", "bpy.ops.wm.append(filename='x')"}, {"link", "bpy.ops.wm.link(filename='x')"},
	} {
		script := "import bpy\nimport os\n" + c.reads + "\nv = bpy.data.objects.get('x')\nm = v.view_matrix\n"
		out := tbn(5, "m = v.view_matrix", none)
		if got := judgeRun("run_blender", "Blender 5.2.2", scene, script, runResult{ExitCode: 1, Stderr: out, Output: out}); got.Outcome != "unsure" {
			t.Errorf("%s reads what the sandbox hides: %+v", c.name, got)
		}
	}
	// A plain Python run isn't Blender's scene.
	out := tbn(3, "m = v.view_matrix", none)
	if got := judgeRun("run_python", "Python 3.13", scene, "import x\nv = x.get()\nm = v.view_matrix\n", runResult{ExitCode: 1, Stderr: out, Output: out}); got.Outcome != "unsure" {
		t.Errorf("not Blender: %+v", got)
	}
	// Another marker in the same message keeps its excuse.
	msg := "RuntimeError: Error: cannot open file 'NoneType'"
	out = tbn(3, "m = v.view_matrix", msg)
	if got := judgeRun("run_blender", "Blender 5.2.2", scene, "import bpy\nv = 1\nm = v.view_matrix\n", runResult{ExitCode: 1, Stderr: out, Output: out}); got.Outcome != "unsure" {
		t.Errorf("a file it couldn't open, whatever else it says: %+v", got)
	}
}

func TestSceneLimitsOwnEngines(t *testing.T) {
	const goal = "A studio with a cup, for a client."
	for _, name := range []string{"BLENDER_EEVEE_NEXT", "BLENDER_RENDER", "EEVEE", "EEVEE_NEXT", "CYCLES", "WORKBENCH", "cycles", "eevee"} {
		msg := fmt.Sprintf("TypeError: bpy_struct: item.attr = val: enum \"%s\" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH', 'CYCLES')", name)
		out := fmt.Sprintf("Traceback (most recent call last):\n  File \"script.py\", line 3, in <module>\n    scene.render.engine = '%s'\n%s\n\nError: script failed, file: 'script.py', exiting.\n", name, msg)
		script := "import bpy\nscene = bpy.context.scene\nscene.render.engine = '" + name + "'\n"
		if c := judgeRun("run_blender", "Blender 5.2.2", goal, script, runResult{ExitCode: 1, Stderr: out, Output: out}); c.Outcome != "failed" {
			t.Errorf("%s is a wrong name, not an add-on's engine: %+v", name, c)
		}
	}
	msg := "TypeError: bpy_struct: item.attr = val: enum \"FOO\" not found in ('A', 'B')"
	out := "Traceback (most recent call last):\n  File \"script.py\", line 3, in <module>\n    o.mode = 'FOO'\n" + msg + "\n\nError: script failed, file: 'script.py', exiting.\n"
	if c := judgeRun("run_blender", "Blender 5.2.2", goal, "import bpy\no = bpy.context.object\no.mode = 'FOO'\n", runResult{ExitCode: 1, Stderr: out, Output: out}); c.Outcome != "failed" {
		t.Errorf("not about the engine: %+v", c)
	}
}
