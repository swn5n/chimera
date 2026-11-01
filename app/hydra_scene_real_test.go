package main

import (
	"context"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"
)

const (
	realClear  = "import bpy\nimport math\nfrom mathutils import Vector\nbpy.ops.object.select_all(action='SELECT')\nbpy.ops.object.delete()\n"
	realTable  = "bpy.ops.mesh.primitive_cylinder_add(radius=1, depth=0.1, location=(0, 0, 0.75))\nbpy.context.object.name = 'table'\n"
	realCamera = "cd = bpy.data.cameras.new('c')\ncam = bpy.data.objects.new('c', cd)\nbpy.context.scene.collection.objects.link(cam)\nbpy.context.scene.camera = cam\ncam.location = (0, -5, 3)\n"
	realLook   = "t = bpy.data.objects['table']\ncon = cam.constraints.new('TRACK_TO')\ncon.target = t\ncon.track_axis = 'TRACK_NEGATIVE_Z'\ncon.up_axis = 'UP_Y'\nbpy.context.view_layer.update()\nf = cam.data.view_frame(scene=bpy.context.scene)\n"
	// A ball at the frame's right edge, depth 8 frames away, moved by dx in view-plane units.
	ballLine = "bpy.ops.mesh.primitive_uv_sphere_add(radius=%R, location=cam.matrix_world @ (((f[0] + f[1]) / 2 * 8) + Vector((%D, 0, 0))))\nbpy.context.object.name = 'ball'\n"
	// A box laid along the camera's own axes, across the top of the frame or down its right edge.
	railAt = "bpy.ops.mesh.primitive_cube_add(size=1, location=cam.matrix_world @ (((f[0] + f[3]) / 2 * 8) + Vector((0, 0.01, 0))), rotation=cam.matrix_world.to_euler())\nr = bpy.context.object\nr.name = 'rail'\nr.scale = (60, 0.1, 0.1)\n"
	poleAt = "bpy.ops.mesh.primitive_cube_add(size=1, location=cam.matrix_world @ (((f[0] + f[1]) / 2 * 8) + Vector((0.01, 0, 0))), rotation=cam.matrix_world.to_euler())\nr = bpy.context.object\nr.name = 'pole'\nr.scale = (0.1, 60, 0.1)\n"
)

func ballAt(radius, dx string) string {
	return strings.NewReplacer("%R", radius, "%D", dx).Replace(ballLine)
}

func realSceneRun(t *testing.T, path, script string) runResult {
	t.Helper()
	file := filepath.Join(t.TempDir(), "script.py")
	if err := os.WriteFile(file, []byte(script), 0o600); err != nil {
		t.Fatal(err)
	}
	return realBlender(t, path, file, blenderStopAtRender+blenderCrashNames+blenderSceneFacts, blenderMeasureScene)
}

func testBlender(t *testing.T) string {
	path := os.Getenv("CHIMERA_TEST_BLENDER")
	if path == "" {
		path, _ = findBlender()
	}
	if path == "" {
		t.Skip("no Blender here")
	}
	return path
}

// room is walls that are planes, as a model writes them, a floor, and enough small
// things that the walls count as big: the camera stands in the room, off to one side.
const roomOf = realClear + `
def plane(name, verts):
    m = bpy.data.meshes.new(name)
    m.from_pydata(verts, [], [(0, 1, 2, 3)])
    bpy.context.scene.collection.objects.link(bpy.data.objects.new(name, m))
plane('wall_n', [(-5, 5, 0), (5, 5, 0), (5, 5, 3), (-5, 5, 3)])
plane('wall_s', [(-5, -5, 0), (5, -5, 0), (5, -5, 3), (-5, -5, 3)])
plane('wall_e', [(5, -5, 0), (5, 5, 0), (5, 5, 3), (5, -5, 3)])
plane('wall_w', [(-5, -5, 0), (-5, 5, 0), (-5, 5, 3), (-5, -5, 3)])
plane('floor', [(-5, -5, 0), (5, -5, 0), (5, 5, 0), (-5, 5, 0)])
for i in range(9):
    bpy.ops.mesh.primitive_cube_add(size=0.3, location=(-1 + i * 0.25, 2, 0.2))
    bpy.context.object.name = 'book'
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, location=(0, 3, 0.5))
bpy.context.object.name = 'sofa'
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, location=(0, -3, 0.5))
bpy.context.object.name = 'chair'
` + realCamera + `cam.location = (3, 0, 1.5)
cam.rotation_euler = (math.radians(90), 0, math.radians(30))
`

// a tree beside the camera, which looks at the ground: the ground doesn't say the camera is among things.
const groundOf = realClear + `
bpy.ops.mesh.primitive_plane_add(size=100)
bpy.context.object.name = 'ground'
bpy.ops.mesh.primitive_cone_add(radius1=1, depth=6, location=(0, 0, 3))
bpy.context.object.name = 'tree'
` + realCamera + `cam.location = (20, 20, 3)
cam.rotation_euler = (math.radians(60), 0, math.radians(-45 + 180 + 180))
cam.rotation_euler = (math.radians(60), 0, math.radians(135 + 180))
`

func manyWords(n, size int) string {
	return "import itertools\nnames = [''.join(p) for p in itertools.islice(itertools.product('abcdefghijklmnopqrstuvwxyz', repeat=4), " +
		strconv.Itoa(n) + ")]\nm = bpy.data.meshes.new('m')\nm.from_pydata([(0, 0, 0), (0.1, 0, 0), (0, 0.1, 0)], [], [(0, 1, 2)])\nfor i, w in enumerate(names):\n    o = bpy.data.objects.new('x' * " + strconv.Itoa(size) + " + w, m)\n    bpy.context.scene.collection.objects.link(o)\n    o.location = ((i % 40) * 0.05 - 1, 0, (i // 40) * 0.05 + 0.2)\n"
}

func TestRealSceneScenes(t *testing.T) {
	path := testBlender(t)
	const two = "A scene of a table and a ball."
	base := realClear + realTable + realCamera + realLook
	for _, c := range []struct{ name, script, goal, outcome, has string }{
		{"half over the edge, with plenty of it on view", base + ballAt("2", "0.4"), two, "passed", "2 of its 2 objects"},
		{"a small thing a little over the edge", base + ballAt("0.2", "-0.08"), two, "passed", "2 of its 2 objects"},
		{"a rail too long for the frame, along its top edge", base + railAt, "A scene of a table and a rail.", "passed", "2 of its 2 objects"},
		{"a pole too tall for the frame, along its side", base + poleAt, "A scene of a table and a pole.", "passed", "2 of its 2 objects"},
		{"a card seen exactly edge-on", realClear + realTable + realCamera + "cam.location = (0, 0, 5)\nm = bpy.data.meshes.new('card')\nm.from_pydata([(0, -0.3, -0.3), (0, 0.3, -0.3), (0, 0.3, 0.3), (0, -0.3, 0.3)], [], [(0, 1, 2, 3)])\nbpy.context.scene.collection.objects.link(bpy.data.objects.new('card', m))\n", "A scene of a table and a card.", "passed", "2 of its 2 objects"},
		{"out of frame, and small enough to fit it", base + "bpy.ops.mesh.primitive_uv_sphere_add(radius=0.2, location=(7, 0, 1))\nbpy.context.object.name = 'ball'\n", "A scene of a table.", "passed", "1 of its 2 objects"},
		{"barely in frame counts as out", base + ballAt("0.2", "0.08"), "A scene of a table.", "passed", "1 of its 2 objects"},
		{"a fence the viewport doesn't show, just off to the side", base + "bpy.ops.mesh.primitive_cube_add(size=0.5, location=(7, 0, 1))\nbpy.context.object.name = 'fence'\nm = bpy.context.object.modifiers.new('a', 'ARRAY')\nm.count = 3\nm.show_viewport = False\n", "A scene of a table and a fence.", "passed", ""},
		{"a kerb that runs back past the camera", base + "bpy.ops.mesh.primitive_cube_add(size=1, location=(12, 0, 0.05))\nr = bpy.context.object\nr.name = 'kerb'\nr.scale = (0.1, 80, 0.1)\n", "A scene of a table and a kerb.", "passed", ""},
		{"the plane walls say the camera is in a room", roomOf, "A scene of a sofa and a chair.", "passed", ""},
		{"a ground doesn't say the camera is among things", groundOf, "A scene of a tree.", "wrong_scene", "doesn't show tree"},
		{"a second camera may be the shot for it", base + "bpy.ops.mesh.primitive_uv_sphere_add(radius=0.2, location=(40, 0, 1))\nbpy.context.object.name = 'ball'\nc2 = bpy.data.objects.new('c2', bpy.data.cameras.new('c2'))\nbpy.context.scene.collection.objects.link(c2)\n", two, "passed", ""},
		{"nothing at all is still measured", realClear, "A scene of a table.", "wrong_scene", "no camera"},
		{"names in camel case", base + "bpy.ops.mesh.primitive_uv_sphere_add(radius=0.2, location=(40, 0, 1))\nbpy.context.object.name = 'CoffeeCup'\n", "A scene of a table and a cup.", "wrong_scene", "doesn't show CoffeeCup"},
		{"names in capitals", base + "bpy.ops.mesh.primitive_uv_sphere_add(radius=0.2, location=(40, 0, 1))\nbpy.context.object.name = 'Ball'\n", two, "wrong_scene", "doesn't show Ball"},
		{"helpers out of shot", base + "for i, n in enumerate(('ball_target', 'lamp_helper', 'vase_guide', 'mug_dummy', 'cup_proxy', 'Bowl_TARGET')):\n    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.2, location=(40 + i, 0, 1))\n    bpy.context.object.name = n\n", "A scene of a table, a ball, a lamp, a vase, a mug, a cup and a bowl.", "passed", ""},
		{"what's out of shot is listed first, among many", base + "for i in range(200):\n    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.01, segments=8, ring_count=6, location=(0.002 * i, 0, 1))\n    bpy.context.object.name = 'chimera_item'\nbpy.ops.mesh.primitive_uv_sphere_add(radius=0.2, location=(40, 0, 1))\nbpy.context.object.name = 'ball'\n", frameAll, "wrong_scene", "ball is out of frame"},
	} {
		res := realSceneRun(t, path, c.script)
		got := judgeRun("run_blender", "Blender", c.goal, c.script, res)
		if got.Outcome != c.outcome || !strings.Contains(got.Summary, c.has) {
			_, f, _ := takeScene(res)
			t.Errorf("%s: want %s with %q, got %s: %s\nfacts %+v", c.name, c.outcome, c.has, got.Outcome, got.Summary, f)
		}
	}
}

func TestRealSceneCaps(t *testing.T) {
	path := testBlender(t)
	base := realClear + realTable + realCamera + realLook
	for _, c := range []struct {
		name, script string
		kept         bool
	}{
		{"too many words", base + manyWords(420, 0), false},
		{"too many bytes", base + manyWords(300, 30), false},
		{"just enough", base + manyWords(150, 24), true},
	} {
		res := realSceneRun(t, path, c.script)
		_, f, _ := takeScene(res)
		if f == nil {
			t.Fatalf("%s: nothing measured", c.name)
		}
		if kept := len(f.Shown)+len(f.Hidden) > 0; kept != c.kept {
			t.Errorf("%s: words kept %v, want %v", c.name, kept, c.kept)
		}
		for _, l := range strings.Split(res.Stderr, "\n") {
			if strings.HasPrefix(l, sceneMarker) && len(l) > 11000 {
				t.Errorf("%s: a scene line of %d bytes won't fit the tail", c.name, len(l))
			}
		}
	}
}

// Through the real tail buffers: a run the tests above read in full.
func TestRealSceneTails(t *testing.T) {
	if runtime.GOOS != "darwin" || !checkSandboxOK() {
		t.Skip("needs macOS's sandbox")
	}
	path := testBlender(t)
	a := checkApp(t, Config{CheckResults: true})
	a.tools.ext["blender"] = ToolInfo{ID: "blender", Have: true, Path: path, Version: "Blender 5.2.2"}
	script := realClear + realTable + realCamera + realLook + manyWords(150, 24) + "bpy.ops.render.render(write_still=False)\n"
	res := a.checkScript(context.Background(), "run_blender", script)
	c := judgeRun("run_blender", "Blender 5.2.2", "A scene of a table.", script, res)
	if !strings.Contains(c.Summary, "up to its render") || !strings.Contains(c.Summary, "objects are in the camera's frame") {
		t.Fatalf("a long scene line takes the render's line with it: %+v\n%s", c, res.Output)
	}
}

// What the span counts: a mat that isn't much bigger than the rest does, a far-flung thing
// and the default cube don't, and the cube alone still gives a view to offer.
func TestRealSceneSpan(t *testing.T) {
	path := testBlender(t)
	mixed := realClear + "bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(0, 0, 0.1))\n" +
		"for x in (-0.5, 0, 0.5):\n    bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(x, 0, 1))\n" +
		"bpy.ops.mesh.primitive_plane_add(size=4)\nbpy.context.object.name = 'mat'\nbpy.ops.mesh.primitive_cube_add(size=1, location=(1e7, 0, 0))\n" + realCamera + "cam.rotation_euler = (math.radians(60), 0, 0)\n"
	_, f, _ := takeScene(realSceneRun(t, path, mixed))
	if f == nil || len(f.Span) != 2 || f.Span[0][0] != -2 || f.Span[1][0] != 2 {
		t.Fatalf("the mat counts and the far thing doesn't: %+v", f)
	}
	res := realSceneRun(t, path, "import bpy\nbpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(30, 0, 1))\n")
	if strings.Contains(res.Output, "Blender 3.") {
		return // no session_uid there, so it can't prove the cube is the original
	}
	_, f, _ = takeScene(res)
	if f == nil || !f.Cube || len(f.Span) != 2 || f.Span[0][0] != 29 {
		t.Fatalf("the default cube is no part of the span: %+v", f)
	}
	_, f, _ = takeScene(realSceneRun(t, path, "import bpy\nbpy.data.objects.remove(bpy.data.objects['Camera'])\n"))
	if f == nil || !f.Cube || len(f.Span) != 2 || f.Pose == nil {
		t.Fatalf("the cube alone still gives a view: %+v", f)
	}
}
