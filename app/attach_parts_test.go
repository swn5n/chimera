package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAnOBJsPartsAreNamedBiggestFirst(t *testing.T) {
	var b strings.Builder
	tri := func(x, y, z, size float64) {
		fmt.Fprintf(&b, "v %g %g %g\nv %g %g %g\nv %g %g %g\nf -3 -2 -1\n", x, y, z, x+size, y, z, x, y+size, z)
	}
	b.WriteString("mtllib m.mtl\no Body\n")
	tri(0, 0, 0, 4)
	for i := 0; i < 4; i++ { // a numbered run, then one apart from it
		fmt.Fprintf(&b, "o Bolt_%d\n", i)
		tri(1, 1, 1, 0.05)
	}
	b.WriteString("o Bolt_7\n")
	tri(1, 1, 1, 0.05)
	b.WriteString("o Door\nv 0 0 0\nv 1.5 0 0\nv 0 2 0\nf 19 20 21\n") // counted from the file's first vertex: its own three, a 2-long part
	b.WriteString("g Door\n")                                          // the same name again: one part
	tri(0, 0, 0, 0.5)
	for i := 0; i < 45; i++ { // more than the list holds
		fmt.Fprintf(&b, "o Trim_%c%c\n", 'a'+i%26, 'a'+i/26)
		tri(2, 2, 2, 0.01)
	}
	dir := t.TempDir()
	p := filepath.Join(dir, "digger.obj")
	os.WriteFile(p, []byte(b.String()), 0o644)
	x := readFacts(p, "digger.obj", int64(b.Len()), func(string) bool { return true })
	for _, want := range []string{
		"Its parts, biggest first (the names on its o and g lines, which three.js's OBJLoader gives its meshes, for getObjectByName): `Body` (4), `Door` (2), `Bolt_0` to `Bolt_3` (0.05), `Bolt_7` (0.05), `Trim_aa` (0.01)",
		", and 9 more, smaller",
		"They all share one origin, so to turn one about its own hinge, put it in a Group placed at the hinge",
	} {
		if !strings.Contains(x.Parts, want) {
			t.Errorf("missing %q in:\n%s", want, x.Parts)
		}
	}
	if n := strings.Count(x.Parts, "`Trim_"); n != 36 { // 40 entries: Body, Door, the run, Bolt_7 and 36 trims
		t.Errorf("%d trims listed", n)
	}
	// It's on the model's line in what the engine is told.
	_, note := describeAttachments(dir, []AttachedFile{{Path: "digger.obj", Bytes: int64(b.Len())}}, 24000)
	if !strings.Contains(note, "for getObjectByName): `Body` (4)") {
		t.Errorf("the note:\n%s", note)
	}
	// One part isn't a list.
	os.WriteFile(p, []byte("o Only\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"), 0o644)
	if x := readFacts(p, "digger.obj", 40, func(string) bool { return true }); x.Parts != "" {
		t.Errorf("one part: %q", x.Parts)
	}
}

func TestAGLTFsPartsAndWhatItsAnimationsMove(t *testing.T) {
	box := func(lo, hi float64) map[string]any {
		return map[string]any{"count": 3, "type": "VEC3", "componentType": 5126, "min": []float64{lo, 0, lo}, "max": []float64{hi, hi, hi}}
	}
	doc := map[string]any{
		"asset": map[string]any{"version": "2.0"}, "scene": 0,
		"scenes": []any{map[string]any{"nodes": []int{0}}},
		"nodes": []any{
			map[string]any{"name": "RootNode", "children": []int{1}}, // wraps one part: left out
			map[string]any{"name": "Excavator", "children": []int{2, 4, 5, 6, 7, 8}},
			map[string]any{"name": "Boom", "mesh": 0, "children": []int{3}, "translation": []float64{0, 1, 0}},
			map[string]any{"name": "Bucket", "mesh": 1, "translation": []float64{0, 2, 0}},
			map[string]any{"name": "Wheel FL", "children": []int{9}},
			map[string]any{"name": "Light", "mesh": 2},
			map[string]any{"name": "Light", "mesh": 2, "translation": []float64{1, 0, 0}},
			map[string]any{"name": "Bone"},
			map[string]any{"name": "Bone.001"},
			map[string]any{"mesh": 2}, // the wheel's own mesh, with no name
		},
		"meshes": []any{
			map[string]any{"primitives": []any{map[string]any{"attributes": map[string]int{"POSITION": 0}}}},
			map[string]any{"primitives": []any{map[string]any{"attributes": map[string]int{"POSITION": 1}}}},
			map[string]any{"primitives": []any{map[string]any{"attributes": map[string]int{"POSITION": 2}}}},
		},
		"accessors": []any{box(-1, 3), box(0, 0.5), box(0, 0.2), map[string]any{"count": 2, "type": "SCALAR", "componentType": 5126, "min": []float64{0}, "max": []float64{2.5}}},
		"skins":     []any{map[string]any{"joints": []int{7, 8}}},
		"animations": []any{
			map[string]any{"name": "Dig", "samplers": []any{map[string]any{"input": 3, "output": 3}},
				"channels": []any{map[string]any{"sampler": 0, "target": map[string]any{"node": 2, "path": "rotation"}}, map[string]any{"sampler": 0, "target": map[string]any{"node": 3, "path": "rotation"}},
					map[string]any{"sampler": 0, "target": map[string]any{"node": 3, "path": "translation"}}}},
			map[string]any{"name": "Walk", "samplers": []any{map[string]any{"input": 3, "output": 3}},
				"channels": []any{map[string]any{"sampler": 0, "target": map[string]any{"node": 7, "path": "rotation"}}, map[string]any{"sampler": 0, "target": map[string]any{"node": 8, "path": "rotation"}}}},
		},
	}
	dir := t.TempDir()
	p := filepath.Join(dir, "digger.glb")
	data := glbOf(t, doc)
	os.WriteFile(p, data, 0o644)
	x := readFacts(p, "digger.glb", int64(len(data)), func(string) bool { return true })
	for _, want := range []string{
		`animations: "Dig" (2.5 s; moves ` + "`Boom`, `Bucket`" + `), "Walk" (2.5 s; moves 2 bones)`,
	} {
		if !strings.Contains(x.Detail, want) {
			t.Errorf("missing %q in:\n%s", want, x.Detail)
		}
	}
	for _, want := range []string{
		"Its parts, biggest first (glTF node names, which three.js's GLTFLoader gives its objects, for getObjectByName): `Excavator` (",
		"`Boom` (4 m, in `Excavator`), `Bucket` (0.5 m, in `Boom`)",
		"`Wheel FL` (0.2 m, in `Excavator`)",
		"In three.js spaces become _ and [ ] . : / are left out (`Wheel FL` is `Wheel_FL` there); a name that comes twice gets _1, _2… in three.js after the first",
	} {
		if !strings.Contains(x.Parts, want) {
			t.Errorf("missing %q in:\n%s", want, x.Parts)
		}
	}
	for _, not := range []string{"RootNode", "`Bone`", "Bone.001", "share one origin", "sit at one origin"} {
		if strings.Contains(x.Parts, not) {
			t.Errorf("%q shouldn't be in:\n%s", not, x.Parts)
		}
	}
	// A model exported from an OBJ (every part turned the same way, with no place of its
	// own, as Blender writes it) says how to turn one.
	q := []float64{0.7071068, 0, 0, 0.7071068}
	doc["nodes"] = []any{map[string]any{"name": "Arm", "mesh": 0, "rotation": q}, map[string]any{"name": "Cab", "mesh": 1, "rotation": q}}
	doc["scenes"] = []any{map[string]any{"nodes": []int{0, 1}}}
	delete(doc, "skins")
	delete(doc, "animations")
	data = glbOf(t, doc)
	os.WriteFile(p, data, 0o644)
	if x := readFacts(p, "digger.glb", int64(len(data)), func(string) bool { return true }); !strings.Contains(x.Parts, "`Arm` (4 m), `Cab` (0.5 m). They all sit at one origin") {
		t.Errorf("at the origin:\n%s", x.Parts)
	}
}
