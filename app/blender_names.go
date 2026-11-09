package main

// The names sheet. Most crashes in long tasks are wrong or outdated Blender names: of
// 144 in 37 real tasks, about three in four were a socket, attribute, enum or keyword
// that this Blender doesn't have, like "Specular" or diameter1, and each one costs a
// repair. The models learned an older Blender. So the workers and the combine get
// the real names, printed by the Blender on this computer: it's the one the result is
// checked on, it's always right for that version, and nobody writes it by hand.

import (
	"context"
	"fmt"
	"os/exec"
	"regexp"
	"strings"
	"time"
)

const (
	namesStart = "chimera-names-start"
	namesEnd   = "chimera-names-end"
)

// blenderNamesExpr prints what Blender itself says. Anything an older Blender
// doesn't have is left out. A socket Blender keeps unavailable (the shaders' Weight,
// or Noise's W until noise_dimensions is 1D or 4D) is left out: in Blender 5
// inputs[name] can't find it. An enum's real choices can depend on the rest of the
// scene, so it asks by setting a wrong one and reading the refusal.
const blenderNamesExpr = `import bpy, bmesh, re
out = []
def line(label, names):
    names = [n for n in names if n]
    if names:
        out.append(label + ": " + ", ".join(names))
tree = bpy.data.node_groups.new("names", "ShaderNodeTree")
for ident in ("ShaderNodeBsdfPrincipled", "ShaderNodeEmission", "ShaderNodeBsdfGlass", "ShaderNodeTexNoise", "ShaderNodeTexVoronoi", "ShaderNodeTexBrick", "ShaderNodeTexWave", "ShaderNodeBump", "ShaderNodeMapping", "ShaderNodeMix", "ShaderNodeMapRange"):
    try:
        line(ident + " inputs", list(dict.fromkeys(i.name for i in tree.nodes.new(ident).inputs if i.enabled)))
    except RuntimeError:
        pass
def choices(owner, prop):
    try:
        setattr(owner, prop, "?")
    except TypeError as e:
        return re.findall(r"'(\w+)'", str(e).split(" not found in ")[-1])
    return []
s = bpy.context.scene
line("scene.render.engine", choices(s.render, "engine"))
line("image_settings.file_format", choices(s.render.image_settings, "file_format"))
line("image_settings.color_mode", choices(s.render.image_settings, "color_mode"))
con = bpy.data.objects.new("names", None).constraints.new("TRACK_TO")
line("TrackTo track_axis", choices(con, "track_axis"))
line("TrackTo up_axis", choices(con, "up_axis"))
kinds = (bpy.types.PointLight, bpy.types.SunLight, bpy.types.SpotLight, bpy.types.AreaLight)
own = [set(k.bl_rna.properties.keys()) - set(bpy.types.Light.bl_rna.properties.keys()) - {"rna_type"} for k in kinds]
shared = set.intersection(*own)
line("Light", [k for k in ("color", "energy", "use_shadow", "shadow_soft_size") if k in bpy.types.Light.bl_rna.properties or k in shared])
for k, names in zip(kinds, own):
    line(k.__name__ + " also", sorted(n for n in names - shared if not n.startswith(("shadow", "use_shadow", "show_"))))
for op in ("primitive_cube_add", "primitive_uv_sphere_add", "primitive_cylinder_add", "primitive_cone_add", "primitive_plane_add", "primitive_torus_add"):
    line("bpy.ops.mesh." + op, [k for k in getattr(bpy.ops.mesh, op).get_rna_type().properties.keys() if k not in ("rna_type", "enter_editmode", "align", "generate_uvs", "calc_uvs")])
for op in ("create_uvsphere", "create_icosphere", "create_cone", "create_cube", "create_grid", "create_circle"):
    m = re.match(r"[^(]*\(([^)]*)\)", (getattr(bmesh.ops, op).__doc__ or "").strip())
    line("bmesh.ops." + op, [a.strip().split("=")[0] for a in m.group(1).split(",") if a.strip()] if m else [])
print("\n` + namesStart + `\n" + "\n".join(out) + "\n` + namesEnd + `", flush=True)
`

var namesRe = regexp.MustCompile(`(?s)` + namesStart + `\n(.*)\n` + namesEnd)

// readBlenderNames asks a Blender for its names. No Blender, or one that won't say,
// just means no sheet.
func readBlenderNames(ctx context.Context, blender string) string {
	if blender == "" {
		return ""
	}
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, blender, "-b", "--factory-startup", "--python-expr", blenderNamesExpr, "--")
	hideWindow(cmd)
	out, err := cmd.Output()
	if err != nil {
		return ""
	}
	m := namesRe.FindSubmatch(out)
	if m == nil {
		return ""
	}
	return string(m[1])
}

// blenderNames is the sheet for the Blender here, asked for once. It runs nothing but
// the text above, so it needs no sandbox.
func (a *App) blenderNames(ctx context.Context) string {
	path := a.tools.Path("blender")
	a.namesMu.Lock()
	defer a.namesMu.Unlock()
	if a.namesOf != path {
		a.namesOf, a.names = path, readBlenderNames(ctx, path)
	}
	return a.names
}

// namesApply says whether a step of this kind gets the sheet: a Blender step, or any
// step of a task that says Blender or bpy.
func namesApply(kind string, plan hydraPlan, goal string) bool {
	return kind == "blender" || blenderTaskRe.MatchString(goal+"\n"+plan.Title+"\n"+plan.Summary)
}

// namesBlock adds the sheet to a Blender task's system prompt.
func (a *App) namesBlock(ctx context.Context, kind string, plan hydraPlan, goal string) string {
	if !namesApply(kind, plan, goal) {
		return ""
	}
	sheet := a.blenderNames(ctx)
	if sheet == "" {
		return ""
	}
	return "\n\nThe exact names in the Blender this will run on, printed by that Blender. Use these, not ones you remember from other versions:\n" + sheet
}

var blenderTaskRe = regexp.MustCompile(`(?i)\b(?:blender|bpy)\b`)

// runBlenderNames is chimera --blender-names, for looking at the sheet and for the
// worker eval, which measures it.
func runBlenderNames() int {
	p, _ := findBlender()
	sheet := readBlenderNames(context.Background(), p)
	if sheet == "" {
		return 1
	}
	fmt.Println(strings.TrimSpace(sheet))
	return 0
}
