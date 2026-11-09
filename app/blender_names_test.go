package main

import (
	"context"
	"strings"
	"testing"
	"time"
)

func TestTheSheetIsOnlyForBlenderTasks(t *testing.T) {
	a := &App{tools: &ToolScanner{ext: map[string]ToolInfo{"blender": {ID: "blender", Have: true, Path: "/x/blender"}}}, namesOf: "/x/blender", names: "ShaderNodeEmission inputs: Color, Strength"}
	plain := hydraPlan{Title: "A shop", Summary: "A site."}
	for _, c := range []struct {
		name, kind, goal string
		plan             hydraPlan
		want             bool
	}{
		{"a Blender step", "blender", "a chair", plain, true},
		{"a code step in a Blender task", "code", "write a Blender script", plain, true},
		{"the plan says bpy", "code", "a chair", hydraPlan{Summary: "Uses bpy."}, true},
		{"not Blender", "code", "write a web shop", plain, false},
		{"prose about it stays out only if it doesn't name it", "writing", "an essay on chairs", plain, false},
	} {
		got := a.namesBlock(context.Background(), c.kind, c.plan, c.goal)
		if (got != "") != c.want {
			t.Errorf("%s: %q", c.name, got)
		}
		if c.want && !strings.Contains(got, "Color, Strength") {
			t.Errorf("%s: no sheet in %q", c.name, got)
		}
	}
	a.names = ""
	if got := a.namesBlock(context.Background(), "blender", plain, "a chair"); got != "" {
		t.Fatalf("no Blender, no sheet: %q", got)
	}
}

func TestNoBlenderNoNames(t *testing.T) {
	if got := readBlenderNames(context.Background(), ""); got != "" {
		t.Fatal(got)
	}
	if got := readBlenderNames(context.Background(), "/no/such/blender"); got != "" {
		t.Fatal(got)
	}
}

// The sheet has to be what this Blender really accepts, so the names that crash most
// have to be right on it, and each real Blender has to be able to print it.
func TestRealBlenderPrintsItsNames(t *testing.T) {
	path := testBlender(t)
	sheet := readBlenderNames(context.Background(), path)
	if sheet == "" {
		t.Fatal("no sheet")
	}
	for _, want := range []string{"ShaderNodeBsdfPrincipled inputs: Base Color", "scene.render.engine:", "image_settings.file_format:", "bmesh.ops.create_cone:", "radius1", "TRACK_NEGATIVE_Z", "bpy.ops.mesh.primitive_cone_add:"} {
		if !strings.Contains(sheet, want) {
			t.Errorf("no %q in\n%s", want, sheet)
		}
	}
	if strings.Contains(sheet, "diameter1") {
		t.Fatal("an old name")
	}
	if len(sheet) > 4000 {
		t.Fatalf("too long for every worker's prompt: %d", len(sheet))
	}
	// Blender 5's inputs[name] can't find a socket it keeps unavailable, so the sheet
	// doesn't offer one: the shaders' Weight never shows, Map Range's Steps only when
	// stepped. Blender 3's Principled has Subsurface IOR for its default method,
	// Blender 5's only for Random Walk (Skin).
	old := strings.HasPrefix(runOut(10*time.Second, path, "--version"), "Blender 3.")
	for _, l := range strings.Split(sheet, "\n") {
		_, list, ok := strings.Cut(l, " inputs: ")
		for _, name := range strings.Split(list, ", ") {
			if ok && (name == "Weight" || name == "Steps" || name == "Subsurface IOR" && !old) {
				t.Errorf("%s isn't available on a new node: %q", name, l)
			}
		}
	}
	if !strings.Contains(sheet, "ShaderNodeEmission inputs: Color, Strength\n") {
		t.Errorf("Emission is its colour and strength:\n%s", sheet)
	}
}
