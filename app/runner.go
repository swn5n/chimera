package main

// Runs untrusted Python and Blender scripts inside a real sandbox: no network,
// the home folder hidden, no other programs, and writes limited to a throwaway
// folder. If this computer can't provide that sandbox, the script isn't run at
// all. Two callers, each with its own consent:
//   - library test runs on the host computer (runScript), only when its owner
//     turned on "Test library scripts on this computer";
//   - the check of a looping long task's result on the computer that asked
//     (checkScript, hydra_check.go), only with "Run long tasks' scripts here
//     to check them".
//
// The riskyScript regex is only a fast pre-filter, never the boundary.

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"time"
)

type runResult struct {
	OK       bool    `json:"ok"`
	Skipped  bool    `json:"skipped,omitempty"` // couldn't sandbox here; not a failure of the script
	ExitCode int     `json:"exit_code"`
	Seconds  float64 `json:"seconds"`
	Summary  string  `json:"summary"`
	Output   string  `json:"output"`

	// Only for this computer, never sent to the hub.
	Stderr   string `json:"-"` // the end of what it printed as errors, paths hidden
	TimedOut bool   `json:"-"`
	NotRun   bool   `json:"-"` // refused, no program, or it couldn't start
	Look     []byte `json:"-"` // a render of the scene it built, to look at (PNG)
}

// canSandbox reports whether this computer can safely run an untrusted script.
func canSandbox() bool {
	switch runtime.GOOS {
	case "darwin":
		_, err := exec.LookPath("sandbox-exec")
		return err == nil
	case "linux":
		if _, err := exec.LookPath("bwrap"); err == nil {
			return true
		}
		_, err := exec.LookPath("unshare")
		return err == nil
	default:
		return false
	}
}

// runScript test-runs a library entry, when this computer's owner allows it.
func (a *App) runScript(ctx context.Context, kind, script string) runResult {
	if !a.config().RunTests {
		return runResult{Summary: "Test runs are turned off on this computer."}
	}
	if riskyScript.MatchString(script) {
		return runResult{NotRun: true, Summary: "Refused: the script touches files, the network or other programs."}
	}
	return a.runSandboxed(ctx, kind, script, false, nil)
}

// watchdog runs a sandboxed command ("$@") and, beside it, waits for its own
// standard input to close (the app holds the other end), then kills the
// command (by its pid: it may have left the process group with setsid) and
// the process group. The command's exit status is passed on. The watcher
// reads a copy of the input (fd 3): a background job's own input is /dev/null.
const watchdog = `exec 3<&0
"$@" </dev/null 3<&- &
c=$!
(read _ <&3; kill -KILL $c 2>/dev/null; kill -KILL 0) &
w=$!
exec 3<&-
wait $c
s=$?
kill $w 2>/dev/null
exit $s`

// renderStopMarker is what blenderStopAtRender prints when it stops a render.
const renderStopMarker = "chimera-check: stopped at the render"

// blenderStopAtRender ends Blender cleanly the moment a script starts a render:
// a check is about whether the script runs, and a render can take hours.
const blenderStopAtRender = `import bpy, os, sys, time
@bpy.app.handlers.persistent
def _chimera_stop_at_render(*args):
    print("` + renderStopMarker + `", flush=True)
    try:
        sys._chimera_scene()
    except BaseException:
        pass
    sys.stderr.flush()
    os._exit(0)
bpy.app.handlers.render_init.append(_chimera_stop_at_render)
`

// lookBlend is the scene a checked script built, saved for renderLook, and lookPNG
// what that renders.
const (
	lookBlend = "chimera-look.blend"
	lookPNG   = "chimera-look.png"
)

// blenderLook renders that scene from its camera, small and on the processor: a
// look at it needs a picture, not a good one. It's in a Blender of its own, because
// most scripts stop at their render, where a second one can't start, and because
// the script's code shouldn't run again.
const blenderLook = `import bpy, os
s = bpy.context.scene
r, c = s.render, s.cycles
r.engine, c.device, c.samples, c.use_adaptive_sampling, c.use_denoising, c.time_limit = "CYCLES", "CPU", 16, False, False, 20
k = 512 / max(r.resolution_x * r.pixel_aspect_x, r.resolution_y * r.pixel_aspect_y)
r.resolution_x, r.resolution_y, r.resolution_percentage = max(16, int(r.resolution_x * k)), max(16, int(r.resolution_y * k)), 100
r.use_border, r.film_transparent, r.use_compositing, r.use_sequencer = False, False, False, False
if hasattr(r.image_settings, "media_type"):
    r.image_settings.media_type = "IMAGE"
r.use_multiview = False
r.image_settings.file_format, r.image_settings.color_mode = "PNG", "RGB"
r.filepath = os.path.join(os.getcwd(), "` + lookPNG + `")
bpy.ops.render.render(write_still=True)
`

// sceneMarker starts the line blenderSceneFacts prints; sceneStartMarker says the
// script had finished and it was starting, so that a scene too heavy to measure
// can't turn a script that ran into one that didn't.
const (
	sceneMarker      = "chimera-check: scene "
	sceneStartMarker = "chimera-check: measuring the scene"
)

// blenderSceneFacts measures what a script built, once it has finished or as its
// render starts: what the check can't get from whether it crashed. It needs no GPU,
// so it works in the sandbox, and it does no judging: that's judgeRun's, which
// knows what the task asked. An object counts only if it would render as something
// to frame, so helpers, guide curves and light cards off to the side don't. A box
// outside the frame is proof an object's out of it; rays only show what's reachable,
// since they miss what's small and stop at glass, so a ray that misses proves nothing.
const blenderSceneFacts = `sys._chimera_cube = getattr(bpy.data.objects.get("Cube"), "session_uid", None)
sys._chimera_dir = os.getcwd()
def _chimera_pose(scene, dg, data, where, seen, pts, low, high, vector):
    # A view that frames the main objects, from the side the camera is on, tried
    # with rays: a model can use numbers, but can't work out a rotation.
    import math
    mid = vector([(a + b) / 2 for a, b in zip(low, high)])
    reach = max((p - mid).length for p in pts)
    way = mid - where if where else vector((-0.66, 0.62, -0.42))  # no camera yet: from the front, a little above
    if way.length < 1e-3:
        way = vector((0, 1, -0.4))
    way.normalize()
    if way.z > -0.1:
        way.z = -0.25
        way.normalize()
    corners = data.view_frame(scene=scene)
    half = min(abs(corners[0].x), abs(corners[0].y)) / abs(corners[0].z)
    far = 1.05 * reach / math.sin(math.atan(half))
    at = mid - way * far
    turn = way.to_track_quat("-Z", "Y")
    reachable = max(data.clip_end, 1.1 * (far + reach))
    names, wide, tall = set(), 32, 18
    tr, br, bl, tl = corners
    for j in range(tall):
        for i in range(wide):
            u, v = (i + 0.5) / wide, (j + 0.5) / tall
            hit = scene.ray_cast(dg, at, (turn @ tl.lerp(tr, u).lerp(bl.lerp(br, u), v)).normalized(), distance=reachable)
            if hit[0] and hit[4] and hit[4].original.name in seen:
                names.add(hit[4].original.name)
    pose = {"at": [round(x, 3) for x in at], "rotation": [round(x, 4) for x in turn.to_euler("XYZ")], "sees": len(names)}
    if reachable > data.clip_end:
        pose["clip_end"] = round(reachable, 1)
    return pose
def _chimera_scene():
    sys.stdout.flush()
    time.sleep(0.05)  # its output and errors go by separate pipes: the script's has to arrive first
    print("\n` + sceneStartMarker + `", file=_chimera_err, flush=True)
    full = [s for s in bpy.data.scenes if s.objects]
    if len(full) > 1 or (full and full[0] != bpy.context.scene):
        return  # which of them is the work?
    from bpy_extras.object_utils import world_to_camera_view as view
    from mathutils import Vector as vector
    scene = bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get()
    cam = scene.camera
    live = cam.evaluated_get(dg) if cam else None
    rendered = set()
    def walk(layer):
        if not layer.exclude and not layer.collection.hide_render and not layer.indirect_only:
            rendered.add(layer.collection.name)
            for c in layer.children:
                walk(c)
    walk(bpy.context.view_layer.layer_collection)
    def factory(o):
        slots = [m for m in o.data.materials if m]
        if not slots:
            return True
        node = slots[0].node_tree.nodes.get("Principled BSDF") if len(slots) == 1 and slots[0].name == "Material" and slots[0].node_tree else None
        return bool(node) and [round(x, 3) for x in node.inputs["Base Color"].default_value] == [0.8, 0.8, 0.8, 1]
    def glows(o):
        for slot in o.material_slots:
            tree = slot.material.node_tree if slot.material else None
            for n in tree.nodes if tree else []:
                strength = n.inputs.get("Emission Strength") if n.type == "BSDF_PRINCIPLED" else None
                if n.type == "EMISSION" or (strength and (strength.is_linked or strength.default_value > 0)):
                    return True
        return False
    facts = {"camera": None, "filled": 0.0, "cube": False, "empty": [], "blank": 0, "animated": bool(bpy.data.actions) or scene.rigidbody_world is not None or any(a and a.drivers for a in [o.animation_data for o in scene.objects] + [cam.data.animation_data if cam else None])}
    rows, corners, seen = [], {}, {}
    sources = set()
    for o in scene.objects:
        for p in o.particle_systems:
            sources.update([p.settings.instance_object] if p.settings.instance_object else [])
            sources.update(p.settings.instance_collection.objects if p.settings.instance_collection else [])
    def unmeasured(o):  # it renders, and rays can't reach it
        return not o.hide_render and o.visible_camera and any(c.name in rendered for c in o.users_collection) and (o.type in ("VOLUME", "POINTCLOUD", "GPENCIL", "GREASEPENCIL", "CURVES") or (o.type in ("MESH", "CURVE", "SURFACE", "META", "FONT") and not o.visible_get()))
    facts["unseen"] = any(unmeasured(o) for o in scene.objects)
    for o in scene.objects:
        if o.type not in ("MESH", "CURVE", "SURFACE", "META", "FONT") or not o.visible_get() or o.hide_render or not o.visible_camera:
            continue
        if not any(c.name in rendered for c in o.users_collection) or o in sources or ((o.particle_systems or o.instance_type != "NONE") and not o.show_instancer_for_render):
            continue
        e = o.evaluated_get(dg)
        size = list(e.dimensions)
        if o.type == "MESH" and o.modifiers and not e.data.polygons:  # points or a volume, perhaps: rays can't reach those
            facts["unseen"] = True
        plain = o.type == "MESH" and o.mode == "OBJECT" and not o.modifiers and not o.children and not o.animation_data and o.instance_type == "NONE"
        if plain and (len(e.data.vertices) == 0 or (not e.data.polygons and o.data.materials)):  # with a material, it was meant to show
            facts["blank"] += 1
            if len(facts["empty"]) < 3:
                facts["empty"].append(o.name[:40])
        if o.name == "Cube" and o.type == "MESH" and sys._chimera_cube is not None and getattr(o, "session_uid", None) == sys._chimera_cube and len(o.data.vertices) == 8 and not o.modifiers and factory(o) and [round(x, 3) for x in size] == [2, 2, 2] and tuple(o.location) == (0, 0, 0) and tuple(o.rotation_euler) == (0, 0, 0):
            facts["cube"] = True
        if max(size) == 0:
            continue
        if o.type == "CURVE":
            mesh = e.to_mesh()
            faces = len(mesh.polygons) if mesh else 0
            e.to_mesh_clear()
            if not faces:
                continue
        elif o.type == "MESH" and not e.data.polygons:
            continue
        pts = [e.matrix_world @ vector(c) for c in e.bound_box]
        middle = sum(pts, vector()) / 8
        row = {"name": o.name[:40], "at": [round(x, 3) for x in middle], "size": [round(x, 3) for x in size], "frame": False, "hits": 0}
        if live:
            v = [view(scene, live, p) for p in pts]
            ahead_only = all(c.z > 0 for c in v)  # behind the camera, the sides are mirrored
            row["frame"] = not (all(c.z <= 0 or c.z > live.data.clip_end for c in v) or (ahead_only and (all(c.x < 0 for c in v) or all(c.x > 1 for c in v) or all(c.y < 0 for c in v) or all(c.y > 1 for c in v))))
            if ahead_only:  # how much of it the frame holds, for something small enough to fit
                left, right, under, over = min(c.x for c in v), max(c.x for c in v), min(c.y for c in v), max(c.y for c in v)
                box = (right - left) * (over - under)
                inside = max(0, min(right, 1) - max(left, 0)) * max(0, min(over, 1) - max(under, 0))
                row["fits"] = right - left <= 1 and over - under <= 1
                row["share"] = round(inside / box, 3) if box > 1e-9 else float(row["frame"])
        if any(x.show_render and not x.show_viewport for x in o.modifiers):
            row["frame"], row["fits"] = True, False  # what's measured here isn't what renders
        if row["frame"] or not (min(size) <= 0.01 * max(size) or glows(o)):
            rows.append(row)
            corners[o.name[:40]] = pts
            seen[o.name[:40]] = row
    if cam:
        m, d = live.matrix_world.normalized(), live.data
        where = m.translation.copy()
        ahead = (m.to_quaternion() @ vector((0, 0, -1))).normalized()
        facts["camera"] = {"name": cam.name[:40], "at": [round(x, 3) for x in where], "ahead": [round(x, 3) for x in ahead], "lens": round(d.lens, 1), "type": d.type, "clip": [round(d.clip_start, 3), round(d.clip_end, 1)]}
        if d.type != "PANO":
            tr, br, bl, tl = [m @ p for p in d.view_frame(scene=scene)]
            wide, tall, hits = 64, 36, 0
            for j in range(tall):
                for i in range(wide):
                    u, v = (i + 0.5) / wide, (j + 0.5) / tall
                    p = tl.lerp(tr, u).lerp(bl.lerp(br, u), v)
                    if d.type == "ORTHO":
                        start, way, far = p + ahead * (d.clip_start - (p - where).dot(ahead)), ahead, d.clip_end - d.clip_start
                    else:
                        start, way, far = where, (p - where).normalized(), d.clip_end
                    hit = scene.ray_cast(dg, start, way, distance=far)
                    if hit[0]:
                        hits += 1
                        name = hit[4].original.name[:40] if hit[4] else ""
                        if name in seen:
                            seen[name]["hits"] += 1
            facts["filled"] = round(hits / (wide * tall), 4)
            if not hits and d.type == "PERSP":  # small things fall between the rays
                for row in rows[:300]:
                    if row["frame"]:
                        hit = scene.ray_cast(dg, where, (vector(row["at"]) - where).normalized(), distance=d.clip_end)
                        name = hit[4].original.name[:40] if hit[0] and hit[4] else ""
                        if name in seen:
                            seen[name]["hits"] += 1
    facts["total"] = len(rows)
    facts["seen"] = sum(1 for r in rows if r["hits"])
    facts["out"] = sum(1 for r in rows if not r["frame"] and not r["hits"])
    for r in rows:
        if r["frame"] and r.pop("fits", False) and r["share"] < 0.5 and r["hits"] < (12 if min(r["size"]) < 0.05 * max(r["size"]) else 46):  # 46 rays are 2% of them, enough to make something out; a rod takes fewer
            r["cut"] = True
        elif "share" in r:
            del r["share"]
    facts["cut"] = sum(1 for r in rows if r.get("cut"))
    facts["cameras"] = sum(1 for o in scene.objects if o.type == "CAMERA")
    def named(rs):  # what's called what, for telling whether what the task named made it in
        return sorted({w.lower() for r in rs for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+", r["name"])})
    shown = named(r for r in rows if (r["frame"] or r["hits"]) and not r.get("cut"))
    hidden = named(r for r in rows if (not (r["frame"] or r["hits"]) or r.get("cut")) and not re.search(r"(?i)target|helper|guide|dummy|proxy", r["name"]))
    if len(shown) + len(hidden) <= 400 and len(json.dumps(shown + hidden)) <= 6000:
        facts["shown"], facts["hidden"] = shown, hidden
    sizes = sorted(max(r["size"]) for r in rows)
    typical = sizes[(len(sizes) - 1) // 2] if sizes else 0
    def lying(n):  # a ground, not a wall: walls say where a room ends
        z, x, y = [[p[i] for p in corners[n]] for i in (2, 0, 1)]
        return max(z) - min(z) < 0.02 * (max(x) - min(x) + max(y) - min(y))
    main = [r["name"] for r in rows if not (max(r["size"]) > 3 * typical and min(r["size"]) <= 0.01 * max(r["size"]) and lying(r["name"])) and not (facts["cube"] and r["name"] == "Cube")] or list(corners)
    pts = [p for n in main for p in corners[n] if max(abs(x) for x in p) < 1e6]
    if pts:
        low = [min(p[i] for p in pts) for i in range(3)]
        high = [max(p[i] for p in pts) for i in range(3)]
        facts["span"] = [[round(x, 3) for x in low], [round(x, 3) for x in high]]
        if cam and cam.data.type == "PERSP":
            facts["pose"] = _chimera_pose(scene, dg, live.data, m.translation, seen, pts, low, high, vector)
        elif not cam:
            d = bpy.data.cameras.new("chimera-view")
            facts["pose"] = _chimera_pose(scene, dg, d, None, seen, pts, low, high, vector)
            bpy.data.cameras.remove(d)
    rows.sort(key=lambda r: (bool(r["hits"]) and not r.get("cut"), r["frame"]))
    keep, size = [], 0
    for r in rows:
        size += len(json.dumps(r)) + 2
        if size > 2200:
            break
        keep.append(r)
    facts["objects"] = keep
    print("\n` + sceneMarker + `" + json.dumps(facts), file=_chimera_err, flush=True)
    if cam and cam.type == "CAMERA" and scene.render.engine != "BLENDER_WORKBENCH":  # its light is the display's, which Cycles can't copy
        for i in bpy.data.images:
            if i.is_dirty and i.source == "GENERATED":
                i.pack()  # pixels set in code aren't saved otherwise
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(sys._chimera_dir, "` + lookBlend + `"), copy=True, check_existing=False)
sys._chimera_scene = _chimera_scene
`

// blenderMeasureScene runs blenderSceneFacts once the script has finished.
const blenderMeasureScene = `import sys
try:
    sys._chimera_scene()
except BaseException:
    pass
`

// namesMarker starts the line blenderCrashNames prints.
const namesMarker = "chimera-check: names "

// blenderCrashNames finds the real names when a script stops on a wrong one in
// Blender's API, the commonest crash and one models can't fix by guessing: Blender
// rarely says what the right name is. It runs as Blender dies, so it can look at
// the real object. Only some Blender versions put that on the error, so it goes by
// the failing statement. It must not change what the run means, so it reads only
// what can't run the script's code (a property read twice could print, hang or
// exit, and a script can register those on Blender's own types), binds what it
// uses before the script runs, and says nothing unless it can show this object is
// the one that failed. It's for honest mistakes: a script aimed at it could still
// slip past, as it could by other means, and the sandbox is what holds it in.
const blenderCrashNames = `import ast, builtins, difflib, gc, json, re, warnings, weakref
globals().update({k: v for k, v in vars(builtins).items() if not k.startswith("__")})
_chimera_err = sys.__stderr__
def _chimera_names(t, e, tb):
    def ours(o):
        if type(o) in weakref.ProxyTypes or any(c.__module__ == "__main__" for c in type(o).__mro__):
            return True
        return isinstance(o, type) and any(c.__module__ == "__main__" for c in type.mro(o))
    def read(o, a):
        k = type(o)
        if k is type(sys):
            if a in vars(o):
                return vars(o)[a]
            if not vars(o)["__name__"].startswith(("bpy.ops", "bpy.types", "bmesh.ops")):
                raise ValueError
        elif bpy.types.bpy_struct in k.__mro__ and k is not bpy.types.Context:
            p = k.bl_rna.properties.get(a)
            if p is None or (p.is_runtime and p.type != "POINTER"):
                raise ValueError
        elif k.__flags__ & (1 << 9) and k is not bpy.types.Context:
            raise ValueError
        return getattr(o, a)
    def has(o):
        return sorted(vars(o)) if type(o) is type(sys) else dir(o)
    if ours(e):
        return
    msg = (e.args[0] if len(e.args) == 1 and type(e.args[0]) is str else "")[:2000]
    where, line = None, 0
    while tb:
        if os.path.basename(tb.tb_frame.f_code.co_filename) == "script.py":
            where, line = tb.tb_frame, tb.tb_lineno
        tb = tb.tb_next
    if where is None:
        return
    with open(where.f_code.co_filename, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    stmts = [n for n in ast.walk(tree) if isinstance(n, ast.stmt) and n.lineno <= line <= n.end_lineno]
    size = min([n.end_lineno - n.lineno for n in stmts], default=0)
    nodes = []
    for s in stmts:
        if s.end_lineno - s.lineno == size:
            for field, v in ast.iter_fields(s):
                if field not in ("body", "orelse", "finalbody", "handlers", "cases"):
                    for x in v if isinstance(v, list) else [v]:
                        if isinstance(x, ast.AST):
                            nodes += ast.walk(x)
    bound = {x.id for c in nodes if isinstance(c, ast.comprehension) for x in ast.walk(c.target) if isinstance(x, ast.Name)}
    inside = where.f_code.co_name in ("<listcomp>", "<setcomp>", "<dictcomp>", "<genexpr>")
    def value(n):
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            if n.id in bound and not inside:
                raise ValueError
            v = where.f_locals[n.id] if n.id in where.f_locals else where.f_globals[n.id]
        elif isinstance(n, ast.Attribute):
            v = read(value(n.value), n.attr)
        elif isinstance(n, ast.Subscript):
            k = value(n.slice)
            if type(k) not in (str, int):
                raise ValueError
            v = value(n.value)[k]
        else:
            raise ValueError
        if ours(v):
            raise ValueError
        return v
    kind, wrong, of, names, on = "", "", "", [], []
    if issubclass(t, AttributeError):
        op = re.search(r'Calling operator "bpy\.ops\.(\w+)\.(\w+)"', msg)
        attr = re.search(r"""has no attribute '(\w+)'|attribute "(\w+)" not found""", msg)
        if op:
            kind, wrong, of = "attr", op.group(2), "bpy.ops." + op.group(1)
            names = [x for x in dir(getattr(bpy.ops, op.group(1))) if not x.startswith("_")]
        elif attr:
            wrong = attr.group(1) or attr.group(2)
            owner = re.match(r"'(\w+)' object", msg)
            obj = getattr(e, "obj", None)
            for n in nodes:
                if obj is None and isinstance(n, ast.Attribute) and n.attr == wrong:
                    try:
                        v = value(n.value)
                        if (not owner or type(v).__name__ == owner.group(1)) and wrong not in has(v):
                            obj = v
                    except Exception:
                        pass
            if obj is not None and not ours(obj):
                kind = "attr"
                of = obj.__name__ if type(obj) is type(sys) or isinstance(obj, type) else type(obj).__name__
                names = [x for x in has(obj) if not x.startswith(("_", "bl_")) and x != "rna_type"]
                rna = getattr(type(obj), "bl_rna", None)
                def holds(p):
                    v = read(obj, p.identifier)
                    return v is not None and getattr(v, "is_embedded_data", True)
                for p in rna.properties if rna else []:
                    if p.type == "POINTER" and p.identifier not in ("rna_type", "field", "texture_mapping") and wrong in p.fixed_type.properties and holds(p):
                        on.append(p.identifier)
    elif issubclass(t, KeyError):
        key = re.search(r'key "(.*)" not found', msg)
        for n in nodes:
            if key and not names and isinstance(n, ast.Subscript):
                try:
                    c = value(n.value)
                    if value(n.slice) == key.group(1) and key.group(1) not in c.keys():
                        kind, wrong, of, names = "key", key.group(1), ast.unparse(n.value), list(c.keys())
                except Exception:
                    pass
    elif issubclass(t, TypeError):
        word = re.search(r'keyword "(\w+)"', msg)
        for n in nodes:
            if word and not names and isinstance(n, ast.Call) and any(k.arg == word.group(1) for k in n.keywords):
                try:
                    f = value(n.func)
                    if hasattr(f, "get_rna_type"):
                        ks = [p.identifier for p in f.get_rna_type().properties if p.identifier != "rna_type"]
                    elif type(f).__name__ == "BMeshOpFunc":
                        ks = re.findall(r"(\w+)=", f.__doc__.split("->")[0])
                    else:
                        ks = []
                    if ks and word.group(1) not in ks:
                        kind, wrong, of, names = "kw", word.group(1), ast.unparse(n.func), ks
                except Exception:
                    pass
    if names:
        close = difflib.get_close_matches(wrong, names, 8, 0.4)
        names = on + [x for x in close if x not in on] + [x for x in names if x not in on and x not in close]
        keep, size = [], 0
        for x in names:
            size += len(json.dumps(x)) + 2
            if size > 1500:
                break
            keep.append(x)
        print("` + namesMarker + `" + json.dumps({"kind": kind, "wrong": wrong[:100], "of": of[:100], "names": keep, "on": on, "more": len(keep) < len(names)}), file=_chimera_err, flush=True)
_chimera_prev = sys.excepthook
def _chimera_crash(t, e, tb):
    _chimera_prev(t, e, tb)
    try:
        on, trace, prof = gc.isenabled(), sys.gettrace(), sys.getprofile()
        gc.disable()
        sys.settrace(None)
        sys.setprofile(None)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                _chimera_names(t, e, tb)
        finally:
            sys.settrace(trace)
            sys.setprofile(prof)
            if on:
                gc.enable()
    except BaseException:
        pass
sys.excepthook = _chimera_crash
`

// runSandboxed runs a script (kind run_python or run_blender) in the sandbox
// and says how it went. stopAtRender ends a Blender script at its first render.
func (a *App) runSandboxed(ctx context.Context, kind, script string, stopAtRender bool, look func(runResult) bool) runResult {
	dir, err := os.MkdirTemp("", "chimera-test-*")
	if err != nil {
		return runResult{NotRun: true, Summary: "Couldn't make a temporary folder: " + err.Error()}
	}
	defer os.RemoveAll(dir)
	path := filepath.Join(dir, "script.py")
	if err := os.WriteFile(path, []byte(script), 0o600); err != nil {
		return runResult{NotRun: true, Summary: err.Error()}
	}
	var name string
	var args []string
	timeout := 30 * time.Second
	switch kind {
	case "run_python":
		name = a.tools.Path("python")
		args = []string{"-I", path}
	case "run_blender":
		name = a.tools.Path("blender")
		args = []string{"-b", "--factory-startup", "--python-exit-code", "1"}
		if stopAtRender {
			args = append(args, "--python-expr", blenderStopAtRender+blenderCrashNames+blenderSceneFacts)
		}
		args = append(args, "--python", path)
		if stopAtRender {
			args = append(args, "--python-expr", blenderMeasureScene)
		}
		// "--" ends Blender's own options, so the script can read sys.argv after it.
		args = append(args, "--")
		timeout = 120 * time.Second
	}
	if name == "" {
		return runResult{NotRun: true, Summary: "This computer doesn't have the program needed for this test."}
	}
	argv, how, ok := sandboxed(name, args, dir)
	if !ok {
		// No real sandbox here: never run an untrusted script unprotected.
		return runResult{Skipped: true, Summary: "This computer can't safely sandbox a test run, so it didn't run it."}
	}
	// A watchdog outside the sandbox stops the whole run if this app goes away
	// (even a crash): the pipe on its standard input closes, and it kills the
	// run's process group. The sandbox doesn't let the script fork out of it.
	alive, keep, err := os.Pipe()
	if err != nil {
		return runResult{NotRun: true, Summary: "Couldn't start: " + err.Error()}
	}
	defer alive.Close()
	defer keep.Close()
	argv = append([]string{"/bin/sh", "-c", watchdog, "chimera-check"}, argv...)

	cctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := watchedCommand(cctx, argv, dir, alive, keep)
	both, errOut := &tailBuffer{max: 4000}, &tailBuffer{max: 19000} // room for the names line on top of a traceback
	if stopAtRender {
		both.max = 12000 // a check's scene line has to fit whole, or what came before it goes with it
	}
	cmd.Stdout = both
	cmd.Stderr = io.MultiWriter(both, errOut)
	start := time.Now()
	err = cmd.Run()
	killGroup(cmd) // anything it left behind
	out := both.String()

	if err != nil && sandboxDidNotStart(out) {
		// The sandbox itself couldn't start; treat it as "couldn't check here",
		// not as the script failing, so a good entry isn't flagged.
		return runResult{Skipped: true, Summary: "Couldn't start the sandbox, so the script didn't run.", Output: hidePaths(out, dir)}
	}
	if err != nil && strings.Contains(out, "fork: Operation not permitted") {
		// A launcher script that runs the program without exec can't start it
		// in the sandbox (no forking): couldn't check here, not a failure.
		return runResult{Skipped: true, Summary: "Couldn't start " + filepath.Base(name) + " through its launcher in the sandbox.", Output: hidePaths(out, dir)}
	}
	res := runResult{Seconds: round1(time.Since(start).Seconds()), Output: hidePaths(out, dir), Stderr: hidePaths(errOut.String(), dir)}
	switch {
	case cctx.Err() == context.DeadlineExceeded && ctx.Err() == nil:
		res.Summary = fmt.Sprintf("Timed out after %s.", timeout)
		res.ExitCode = -1
		res.TimedOut = true
	case ctx.Err() != nil:
		res.Skipped = true
		res.Summary = "The test run was cancelled."
	case cmd.ProcessState == nil:
		res.NotRun = true
		res.Summary = "Couldn't start: " + err.Error()
		res.ExitCode = -1
	default:
		// The exit code decides, also when Run only complained that a child
		// kept the output open after a clean exit (exec.ErrWaitDelay).
		res.ExitCode = cmd.ProcessState.ExitCode()
		if res.ExitCode != 0 {
			res.Summary = fmt.Sprintf("Exited with code %d after %.1fs.", res.ExitCode, res.Seconds)
			break
		}
		res.OK = true
		res.Summary = fmt.Sprintf("Ran cleanly in %.1fs.", res.Seconds)
		if kind == "run_blender" && strings.Contains(out, "Error:") {
			res.OK = false
			res.Summary = "Blender reported an error."
		}
	}
	if res.OK && how != "" {
		res.Summary += " (" + how + ")"
	}
	if look != nil && look(res) {
		res.Look = renderLook(ctx, name, dir)
	}
	return res
}

// watchedCommand is a sandboxed run under the watchdog, in its own process group, so
// stopping it also stops whatever it started. Stopping goes through the watchdog,
// which also reaches a script that left the group; WaitDelay and killGroup are the
// backstops.
func watchedCommand(ctx context.Context, argv []string, dir string, alive, keep *os.File) *exec.Cmd {
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	cmd.Dir = dir
	cmd.Env = scriptEnv(dir)
	cmd.Stdin = alive
	newProcessGroup(cmd)
	cmd.Cancel = func() error { keep.Close(); return nil }
	cmd.WaitDelay = 5 * time.Second
	hideWindow(cmd)
	return cmd
}

// renderLook renders the scene a checked script saved in dir, in the same sandbox.
// Anything that goes wrong just means there's no picture to look at. It loads a
// file the script made, so that file's own code stays off.
func renderLook(ctx context.Context, blender, dir string) []byte {
	blend := filepath.Join(dir, lookBlend)
	if _, err := os.Stat(blend); err != nil {
		return nil
	}
	// The script had this folder first, so what's called lookPNG now isn't a render.
	out := filepath.Join(dir, lookPNG)
	if err := os.Remove(out); err != nil && !os.IsNotExist(err) {
		return nil
	}
	argv, _, ok := sandboxed(blender, []string{"-b", "--factory-startup", "--disable-autoexec", blend, "--python-expr", blenderLook, "--"}, dir)
	if !ok {
		return nil
	}
	alive, keep, err := os.Pipe()
	if err != nil {
		return nil
	}
	defer alive.Close()
	defer keep.Close()
	cctx, cancel := context.WithTimeout(ctx, lookRenderTime)
	defer cancel()
	cmd := watchedCommand(cctx, append([]string{"/bin/sh", "-c", watchdog, "chimera-check"}, argv...), dir, alive, keep)
	err = cmd.Run()
	killGroup(cmd)
	if err != nil {
		return nil
	}
	// This runs outside the sandbox, so it won't follow a link or wait on a pipe.
	if fi, err := os.Lstat(out); err != nil || !fi.Mode().IsRegular() || fi.Size() > lookMaxBytes {
		return nil
	}
	png, err := os.ReadFile(out)
	if err != nil {
		return nil
	}
	return png
}

// tailBuffer keeps the last max bytes written to it. The two goroutines that
// copy a command's output can write at once, hence the lock.
type tailBuffer struct {
	mu  sync.Mutex
	max int
	b   []byte
}

func (t *tailBuffer) Write(p []byte) (int, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.b = append(t.b, p...)
	if len(t.b) > 2*t.max {
		t.b = append([]byte(nil), t.b[len(t.b)-t.max:]...)
	}
	return len(p), nil
}

func (t *tailBuffer) String() string {
	t.mu.Lock()
	defer t.mu.Unlock()
	return tail(string(t.b), t.max)
}

// hidePaths takes the throwaway folder out of what a script printed, so its
// errors read File "script.py" and say nothing about this computer.
func hidePaths(s, dir string) string {
	var forms []string
	if real, err := filepath.EvalSymlinks(dir); err == nil {
		forms = append(forms, real+"/")
	}
	if strings.HasPrefix(dir, "/var/") {
		forms = append(forms, "/private"+dir+"/")
	}
	forms = append(forms, dir+"/")
	// Longest first, so "/private/var/…/" goes before the "/var/…/" inside it.
	for i := range forms {
		for j := i + 1; j < len(forms); j++ {
			if len(forms[j]) > len(forms[i]) {
				forms[i], forms[j] = forms[j], forms[i]
			}
		}
	}
	for _, f := range forms {
		s = strings.ReplaceAll(s, f, "")
	}
	return s
}

func sandboxDidNotStart(out string) bool {
	for _, line := range strings.Split(out, "\n") {
		l := strings.TrimSpace(line)
		if strings.HasPrefix(l, "unshare:") || strings.HasPrefix(l, "bwrap:") || strings.HasPrefix(l, "sandbox-exec:") {
			return true
		}
	}
	return false
}

// scriptEnv is a bare environment: nothing from this computer's own
// environment (tokens, keys) reaches a test script.
func scriptEnv(dir string) []string {
	env := []string{"HOME=" + dir, "TMPDIR=" + dir, "TMP=" + dir, "TEMP=" + dir, "PYTHONDONTWRITEBYTECODE=1", "PYTHONNOUSERSITE=1", "LANG=en_US.UTF-8"}
	for _, k := range []string{"PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC"} {
		if v := os.Getenv(k); v != "" {
			env = append(env, k+"="+v)
		}
	}
	return env
}

// sandboxed returns the command to run a script under a sandbox, a short
// description of the protection, and whether a real sandbox is available at
// all. When ok is false the caller must not run the script.
func sandboxed(name string, args []string, dir string) (argv []string, how string, ok bool) {
	switch runtime.GOOS {
	case "darwin":
		return macSandbox(name, args, dir)
	case "linux":
		return linuxSandbox(name, args, dir)
	default:
		return nil, "", false // no sandbox we trust on this platform
	}
}

func macSandbox(name string, args []string, dir string) ([]string, string, bool) {
	p, err := exec.LookPath("sandbox-exec")
	if err != nil {
		return nil, "", false
	}
	return append([]string{p, "-p", macScriptProfile(name, dir), name}, args...), "sandboxed: no network or home folder", true
}

// macScriptProfile is the macOS sandbox for a script run with the program name
// in the throwaway folder dir: no network; the home folder and other volumes
// unreadable; writes only to dir; no other programs, no new processes, no
// signals to other processes, and no Apple Events, Finder or clipboard. Blender and Python read their own
// files, which may live in a home folder (~/Applications, pyenv), so the
// program's whole app bundle or install prefix is readable.
func macScriptProfile(name, dir string) string {
	realDir := resolved(dir)
	var reads, execs strings.Builder
	seen := map[*strings.Builder]map[string]bool{&reads: {}, &execs: {}}
	rule := func(b *strings.Builder, kind, p string) {
		if p != "" && !seen[b][kind+p] {
			seen[b][kind+p] = true
			fmt.Fprintf(b, " (%s %s)", kind, sbplQuote(p))
		}
	}
	program := func(p string) {
		rule(&reads, "subpath", hiddenRoot(toolHome(p)))
		rule(&execs, "literal", p)
		rule(&execs, "literal", resolved(p))
		rule(&execs, "subpath", execRoot(toolHome(p)))
	}
	rule(&reads, "subpath", realDir)
	program(name)
	if in := shebangInterp(name); in != "" {
		program(in) // a program that is a script (#!) runs its interpreter too
		// A launcher script (Homebrew's for Blender) starts the app it names.
		for _, app := range launchedApps(name) {
			rule(&reads, "subpath", hiddenRoot(app))
			rule(&execs, "subpath", app)
		}
	}
	return fmt.Sprintf(`(version 1)
(allow default)
(deny network*)
(deny file-read* (subpath "/Users") (subpath "/Volumes") (subpath "/private/var/root"))
(allow file-read*%s)
(deny file-write*)
(allow file-write* (subpath %s) (literal "/dev/null") (regex #"^/dev/tty") (regex #"^/dev/fd/"))
(deny appleevent-send)
(deny mach-lookup (global-name "com.apple.coreservices.launchservicesd") (global-name "com.apple.pasteboard.1"))
(deny signal)
(allow signal (target self))
(deny process-fork)
(deny process-exec*)
(allow process-exec*%s)`,
		reads.String(), sbplQuote(realDir), execs.String())
}

// hiddenRoot is d when the profile hides it (a program kept in a home folder
// or on another volume, which must stay readable for it to run), else "":
// everything else is readable anyway. Only an app bundle or a deep install
// folder: a shallow one such as "/" (the home of /bin/sh) or ~/.local would
// undo the hiding.
func hiddenRoot(d string) string {
	for _, p := range []string{"/Users/", "/Volumes/"} {
		if strings.HasPrefix(d, p) && (strings.HasSuffix(d, ".app") && strings.Count(d, "/") >= 3 || strings.Count(d, "/") >= 4) {
			return d
		}
	}
	return ""
}

var launcherTargetRe = regexp.MustCompile(`(?:['"](/[^'"\n]+?\.app/Contents/MacOS/[^'"\n/]+)['"]|(/[^'"\s]+?\.app/Contents/MacOS/[^'"\s/]+))`)

// launcherTarget is the app binary a launcher script (#!) starts, when it
// names exactly one that exists ("" otherwise): Homebrew's Blender is such a
// launcher, and the app itself runs in the sandbox, which can't fork.
func launcherTarget(name string) string {
	if shebangInterp(name) == "" {
		return ""
	}
	f, err := os.Open(name)
	if err != nil {
		return ""
	}
	defer f.Close()
	head := make([]byte, 4096)
	n, _ := io.ReadFull(f, head)
	found := ""
	for _, m := range launcherTargetRe.FindAllStringSubmatch(string(head[:n]), 4) {
		p := m[1] + m[2]
		if fi, err := os.Stat(p); err != nil || fi.IsDir() || (found != "" && found != p) {
			return ""
		}
		found = p
	}
	return found
}

var launchedAppRe = regexp.MustCompile(`(?:['"](/[^'"\n]+?\.app)|(/[^'"\s]+?\.app))/Contents/MacOS/`)

// launchedApps are the app bundles a launcher script starts (the first 4 KB).
func launchedApps(name string) []string {
	f, err := os.Open(name)
	if err != nil {
		return nil
	}
	defer f.Close()
	head := make([]byte, 4096)
	n, _ := io.ReadFull(f, head)
	var out []string
	for _, m := range launchedAppRe.FindAllStringSubmatch(string(head[:n]), 4) {
		out = append(out, m[1]+m[2]) // quoted (it may hold spaces) or not
	}
	return out
}

// execRoot is a program's folder that it may start its own helpers from: an
// app bundle or a deep install prefix, never a shared one like /usr or
// /opt/homebrew ("" then).
func execRoot(d string) string {
	if d == "" {
		return ""
	}
	if strings.Contains(d, ".app") || strings.Count(d, string(filepath.Separator)) >= 3 {
		return d
	}
	return ""
}

// shebangInterp is the interpreter a script program names on its #! line
// ("" for a real program, or for #!/usr/bin/env, which names none).
func shebangInterp(name string) string {
	f, err := os.Open(name)
	if err != nil {
		return ""
	}
	defer f.Close()
	head := make([]byte, 256)
	n, _ := io.ReadFull(f, head)
	line, _, _ := strings.Cut(string(head[:n]), "\n")
	rest, ok := strings.CutPrefix(line, "#!")
	if !ok {
		return ""
	}
	fields := strings.Fields(rest)
	if len(fields) == 0 || filepath.Base(fields[0]) == "env" {
		return ""
	}
	return fields[0]
}

func linuxSandbox(name string, args []string, dir string) ([]string, string, bool) {
	// bubblewrap is the strong option: a read-only view of the system, the home
	// folders replaced with empty ones, writes only to the work folder, no network.
	if p, err := exec.LookPath("bwrap"); err == nil {
		return bwrapScriptArgs(p, name, args, dir), "sandboxed: no network or home folder", true
	}
	// Otherwise a user + mount + network namespace: no network, and the home
	// folders hidden behind empty mounts so secrets aren't readable. The user
	// maps to an unprivileged id, so system files owned by root stay read-only.
	if p, err := exec.LookPath("unshare"); err == nil {
		var dirs []string
		for _, d := range []string{"/home", "/root", "/run", realHome()} {
			if d != "" {
				dirs = append(dirs, "'"+strings.ReplaceAll(d, "'", `'\''`)+"'")
			}
		}
		script := "mount --make-rprivate / 2>/dev/null || true; " +
			"for d in " + strings.Join(dirs, " ") + "; do [ -d \"$d\" ] && mount -t tmpfs tmpfs \"$d\" 2>/dev/null; done; " +
			`exec "$@"`
		argv := []string{p, "-rnm", "--", "/bin/sh", "-c", script, "chimera-sandbox", name}
		return append(argv, args...), "sandboxed: no network or home folder", true
	}
	return nil, "", false
}

// bwrapScriptArgs is the bubblewrap command for a script run. /run is hidden
// too: it holds the session's message bus, which can start other programs.
func bwrapScriptArgs(bwrap, name string, args []string, dir string) []string {
	argv := []string{bwrap, "--unshare-all", "--die-with-parent", "--new-session",
		"--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
		"--tmpfs", "/home", "--tmpfs", "/root", "--tmpfs", "/tmp", "--tmpfs", "/run"}
	if home := realHome(); home != "" && home != "/home" && home != "/root" {
		argv = append(argv, "--tmpfs", home)
	}
	argv = append(argv, "--bind", dir, dir, "--chdir", dir, "--")
	return append(argv, append([]string{name}, args...)...)
}

func realHome() string {
	if h, err := os.UserHomeDir(); err == nil {
		return h
	}
	return ""
}

func (r runResult) JSON() string {
	b, _ := json.Marshal(r)
	return string(b)
}

func tail(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return "…" + s[len(s)-n:]
}

// sbplQuote quotes a path for a macOS sandbox profile.
func sbplQuote(p string) string {
	return `"` + strings.NewReplacer(`\`, `\\`, `"`, `\"`).Replace(p) + `"`
}
