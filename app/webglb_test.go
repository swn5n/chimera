package main

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAModelIsSavedAsAGLBForPagesAndKeptForNextTime(t *testing.T) {
	blender := fakeTurnBlender(t)
	folder, cache := t.TempDir(), t.TempDir()
	writeFiles(t, folder, map[string]string{
		"machines/x.obj":     "mtllib x.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n",
		"machines/x.mtl":     "newmtl a\nmap_Kd tex.png\n",
		"machines/tex.png":   "first",
		"machines/y.stl":     "solid y\nendsolid y\n",
		"machines/y-web.glb": "someone's own file, of the name y's copy would take",
	})
	ctx := context.Background()
	rel, reused, err := webGLB(ctx, blender, cache, folder, "machines/x.obj", nil)
	if err != nil || rel != "machines/x-web.glb" || reused {
		t.Fatalf("%q %v %v", rel, reused, err)
	}
	full := filepath.Join(folder, "machines", "x-web.glb")
	if !webFile(full) {
		t.Fatal("the GLB isn't in the chat's folder")
	}
	var rec webMade
	if b, err := os.ReadFile(filepath.Join(folder, "machines", ".x-web.glb.json")); err != nil || json.Unmarshal(b, &rec) != nil || rec.Model != "machines/x.obj" || rec.Bytes == 0 {
		t.Fatalf("record: %+v %v", rec, err)
	}
	// The same bytes: the GLB that's there. A changed texture: made again, in the same place.
	if rel, reused, err := webGLB(ctx, blender, cache, folder, "machines/x.obj", nil); err != nil || !reused || rel != "machines/x-web.glb" {
		t.Fatalf("again: %q %v %v", rel, reused, err)
	}
	os.WriteFile(filepath.Join(folder, "machines", "tex.png"), []byte("second"), 0o644)
	if rel, reused, err := webGLB(ctx, blender, cache, folder, "machines/x.obj", nil); err != nil || reused || rel != "machines/x-web.glb" {
		t.Fatalf("changed texture: %q %v %v", rel, reused, err)
	}
	// Someone's own file of that name is left alone.
	if rel, _, err := webGLB(ctx, blender, cache, folder, "machines/y.stl", nil); err != nil || rel != "machines/y-web-2.glb" {
		t.Fatalf("y: %q %v", rel, err)
	}
	if b, _ := os.ReadFile(filepath.Join(folder, "machines", "y-web.glb")); !strings.HasPrefix(string(b), "someone's own") {
		t.Error("someone's own file was touched")
	}
	writeFiles(t, folder, map[string]string{"broken.ply": "ply\nformat ascii 1.0\nend_header\n"})
	if _, _, err := webGLB(ctx, blender, cache, folder, "broken.ply", nil); err == nil || err.Error() != "Blender couldn't read it: not a model" {
		t.Fatalf("broken: %v", err)
	}
	if fileExists(filepath.Join(folder, "broken-web.glb")) {
		t.Error("a failed GLB left a file")
	}
	for p, want := range map[string]bool{"a.obj": true, "a.FBX": true, "a.stl": true, "a.ply": true, "a.glb": false, "a.gltf": false} {
		if got := webable(AttachedFile{Path: p, Kind: "3d"}); got != want {
			t.Errorf("webable(%s) = %v", p, got)
		}
	}
	if webable(AttachedFile{Path: "a-web.obj", Kind: "3d", Made: "glb"}) {
		t.Error("what Chimera made isn't saved again")
	}
}

func TestTheModelIsToldToLoadTheGLBForPages(t *testing.T) {
	folder := t.TempDir()
	obj := "o Arm\nv 0 0 0\nv 4 0 0\nv 0 1 0\nf 1 2 3\no Cab\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 4 5 6\n"
	js := []byte(`{"asset":{"version":"2.0"},"extensionsRequired":["KHR_draco_mesh_compression"],"scenes":[{"nodes":[0,1]}],` +
		`"nodes":[{"name":"Arm","mesh":0},{"name":"Cab","mesh":1}],"meshes":[{"primitives":[{"attributes":{"POSITION":0}}]},{"primitives":[{"attributes":{"POSITION":1}}]}],` +
		`"accessors":[{"count":3,"min":[0,0,0],"max":[4,1,0]},{"count":3,"min":[0,0,0],"max":[1,1,0]}]}`)
	for len(js)%4 != 0 {
		js = append(js, ' ')
	}
	glb := append([]byte("glTF"), binary.LittleEndian.AppendUint32(nil, 2)...)
	glb = binary.LittleEndian.AppendUint32(glb, uint32(20+len(js)))
	glb = binary.LittleEndian.AppendUint32(glb, uint32(len(js)))
	glb = append(append(glb, "JSON"...), js...)
	writeFiles(t, folder, map[string]string{"m/x.obj": obj + strings.Repeat("# padding\n", 400), "m/x-web.glb": string(glb)})
	objSize := int64(len(obj) + 400*10)
	files := []AttachedFile{
		{Path: "m/x.obj", Bytes: objSize, GLB: "m/x-web.glb"},
		{Path: "m/x-web.glb", Bytes: int64(len(glb)), Made: "glb", From: "m/x.obj"},
	}
	_, note := describeAttachments(folder, files, 24000)
	for _, want := range []string{
		"Attached file", // one attached, with what was made of it
		"with 1 GLB Chimera made from it (",
		"): 1 copy for web pages.",
		"Chimera saved a copy of it for web pages, much quicker to load: `m/x-web.glb` (",
		"Its parts are listed with `m/x-web.glb`",
		"- `m/x-web.glb`: 3D model, glTF binary (.glb), ",
		"A copy of `m/x.obj` that Chimera saved for web pages, 1/",
		"the size of `x.obj`: the same model and part names, its meshes Draco-compressed and its textures inside",
		"Load this one in a page, not `x.obj`",
		`Its meshes are Draco-compressed: three.js needs a DRACOLoader for them, given to the GLTFLoader with setDRACOLoader, its decoder from the same three.js version (new DRACOLoader().setDecoderPath("https://cdn.jsdelivr.net/npm/three@<version>/examples/jsm/libs/draco/gltf/"))`,
		"Its parts, biggest first (glTF node names, which three.js's GLTFLoader gives its objects, for getObjectByName): `Arm` (4 m), `Cab` (1 m)",
	} {
		if !strings.Contains(note, want) {
			t.Errorf("missing %q in:\n%s", want, note)
		}
	}
	if strings.Contains(note, "the names on its o and g lines") {
		t.Errorf("the OBJ's own list should give way to the copy's:\n%s", note)
	}
	// When neither could be made, the reason comes once.
	files = []AttachedFile{{Path: "m/x.obj", Bytes: objSize, NoTurn: "Blender can't read it", NoGLB: "Blender can't read it"}}
	if _, note := describeAttachments(folder, files, 24000); !strings.Contains(note, "Chimera couldn't make a turntable or a copy for web pages of it: Blender can't read it") || strings.Count(note, "Blender can't read it") != 1 {
		t.Errorf("one reason:\n%s", note)
	}
}

// Real Blender, when there's one here (CHIMERA_TEST_BLENDER picks it): an OBJ with its
// .mtl and texture, and a PLY, saved for pages in the sandbox.
func TestRealBlenderSavesAGLBForPages(t *testing.T) {
	blender := testBlender(t)
	if !canSandbox() {
		t.Skip("no sandbox here")
	}
	folder, cache := t.TempDir(), t.TempDir()
	writeFiles(t, folder, map[string]string{
		"box/cube.obj": "mtllib cube.mtl\no Body\nv -1 -1 0\nv 1 -1 0\nv 1 1 0\nv -1 1 0\nv -1 -1 2\nv 1 -1 2\nv 1 1 2\nv -1 1 2\nvt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nusemtl paint\n" +
			"f 1/1 2/2 3/3 4/4\nf 5/1 8/2 7/3 6/4\nf 1/1 5/2 6/3 2/4\nf 2/1 6/2 7/3 3/4\nf 3/1 7/2 8/3 4/4\nf 4/1 8/2 5/3 1/4\n" +
			"o Lid\nv -1 -1 2\nv 1 -1 2\nv 1 1 2.5\nf 9 10 11\n",
		"box/cube.mtl": "newmtl paint\nKd 1 1 1\nmap_Kd paint.png\n",
		"tri.ply":      "ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nelement face 1\nproperty list uchar int vertex_indices\nend_header\n0 0 0\n1 0 0\n0 0 1\n3 0 1 2\n",
	})
	os.WriteFile(filepath.Join(folder, "box", "paint.png"), pngOf(t, cutout(8, 8)), 0o644)
	for _, model := range []string{"box/cube.obj", "tri.ply"} {
		rel, _, err := webGLB(context.Background(), blender, cache, folder, model, nil)
		if err != nil {
			t.Fatalf("%s: %v", model, err)
		}
		full := filepath.Join(folder, filepath.FromSlash(rel))
		x := readFacts(full, rel, 0, func(string) bool { return true })
		if x.Format != "glTF binary (.glb)" || !strings.Contains(x.Warn, "Draco-compressed") {
			t.Fatalf("%s: %+v", rel, x)
		}
		head := readHead(full, 1<<20)
		n := int(binary.LittleEndian.Uint32(head[12:]))
		var d struct {
			Nodes []struct {
				Name     string    `json:"name"`
				Rotation []float64 `json:"rotation"`
			} `json:"nodes"`
			Images []json.RawMessage `json:"images"`
		}
		if err := json.Unmarshal(head[20:20+n], &d); err != nil {
			t.Fatal(err)
		}
		for _, nd := range d.Nodes {
			if len(nd.Rotation) > 0 {
				t.Errorf("%s: part %q keeps a turn of its own: %v", rel, nd.Name, nd.Rotation)
			}
		}
		if model == "box/cube.obj" {
			if len(d.Images) != 1 || len(d.Nodes) != 2 || !strings.Contains(x.Parts, "`Body`") || !strings.Contains(x.Parts, "`Lid`") || !strings.Contains(x.Parts, "They all sit at one origin") {
				t.Fatalf("the cube: %d images, %d nodes, parts %q", len(d.Images), len(d.Nodes), x.Parts)
			}
		}
	}
}
