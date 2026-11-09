# A turntable of one 3D model, for a web page that spins it without a 3D library:
# the model turns once about its own vertical axis under fixed studio lights, each
# frame a picture with a transparent background and a soft shadow under the model.
# Chimera runs it in its sandbox (turntable.go) with the model and the files it needs
# copied into the run's folder:
#   Blender -b --factory-startup --python-exit-code 1 --python turntable.py -- '<json>'
# with {"model": "in/x.glb", "out": "out", "frames": 72, "px": 800, "samples": 48,
# "start": 45, "gpu": true}. It writes out/f00.webp ... (or .png where Blender has no
# WebP) and out/poster.webp (frame 0, a little sharper), and prints lines that start
# "chimera-turn:" for Chimera to follow: imported, device, frame <n>, info {json}, done,
# or error <why>. With "glb": "out/x.glb" it first saves the model as a GLB for web
# pages (Draco-compressed meshes, textures inside as WebP; an OBJ's, STL's or PLY's parts
# turned upright in their data) and prints "glb <bytes>"; with "frames": 0 that's all.
import bpy, json, math, os, sys, time
from mathutils import Matrix, Vector


def say(*a):
    print("chimera-turn:", *a, flush=True)


def fail(why):
    say("error", why)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(3)


try:
    opt = json.loads(sys.argv[sys.argv.index("--") + 1])
    model, out = opt["model"], opt["out"]
    frames, px, samples = int(opt["frames"]), int(opt["px"]), int(opt["samples"])
    start = float(opt.get("start", 45))
except Exception as e:  # noqa: BLE001
    fail("bad options: %s" % e)
os.makedirs(out, exist_ok=True)
t0 = time.time()
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
ext = os.path.splitext(model)[1].lower()


def has_op(mod, name):
    try:
        getattr(getattr(bpy.ops, mod), name).get_rna_type()
        return True
    except Exception:  # noqa: BLE001
        return False


def need_addon(mod, name, module, why=None):
    if not has_op(mod, name):
        try:
            bpy.ops.preferences.addon_enable(module=module)
        except Exception:  # noqa: BLE001
            pass
    if not has_op(mod, name):
        fail(why or "this Blender can't import %s files" % ext)


try:
    if ext == ".obj":
        if has_op("wm", "obj_import"):
            bpy.ops.wm.obj_import(filepath=model, forward_axis='NEGATIVE_Z', up_axis='Y')
        else:
            need_addon("import_scene", "obj", "io_scene_obj")
            bpy.ops.import_scene.obj(filepath=model)
    elif ext in (".glb", ".gltf"):
        need_addon("import_scene", "gltf", "io_scene_gltf2")
        bpy.ops.import_scene.gltf(filepath=model)
    elif ext == ".fbx":
        need_addon("import_scene", "fbx", "io_scene_fbx")
        bpy.ops.import_scene.fbx(filepath=model)
    elif ext == ".stl":
        if has_op("wm", "stl_import"):
            bpy.ops.wm.stl_import(filepath=model)
        else:
            need_addon("import_mesh", "stl", "io_mesh_stl")
            bpy.ops.import_mesh.stl(filepath=model)
    elif ext == ".ply":
        if has_op("wm", "ply_import"):
            bpy.ops.wm.ply_import(filepath=model)
        else:
            need_addon("import_mesh", "ply", "io_mesh_ply")
            bpy.ops.import_mesh.ply(filepath=model)
    else:
        fail("can't turn %s files" % ext)
except Exception as e:  # noqa: BLE001
    why = str(e).strip().splitlines()[-1] if str(e).strip() else type(e).__name__
    if why.startswith("Error: "):
        why = why[len("Error: "):]
    why = why.replace("'%s'" % model, "").replace(model, os.path.basename(model)).strip()
    fail("Blender couldn't read it: " + why[:300])
say("imported", "%.1f" % (time.time() - t0))

if opt.get("glb"):
    # A copy for web pages. An OBJ, STL or PLY comes in with the axis change on each
    # part (the same turn on all of them): it goes into their data, so in the GLB every
    # part has no turn or place of its own and a page turns it about the up it expects.
    t1 = time.time()
    if ext in (".obj", ".stl", ".ply"):
        parts = [o for o in scene.objects if o.type == "MESH"]
        if parts:
            for o in scene.objects:
                o.select_set(o in parts)
            bpy.context.view_layer.objects.active = parts[0]
            try:
                bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
            except RuntimeError as e:  # parts that share their data: saved as they came in
                say("note", "kept each part's turn: %s" % str(e).strip().splitlines()[-1][:200])
    need_addon("export_scene", "gltf", "io_scene_gltf2", "this Blender can't save glTF files")
    kw = dict(filepath=os.path.abspath(opt["glb"]), export_format='GLB', export_apply=True,
              export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=6,
              export_image_format='WEBP', export_image_quality=85)
    saved = False
    for leave_out in ((), ("export_image_quality",), ("export_image_quality", "export_image_format")):
        try:
            bpy.ops.export_scene.gltf(**{k: v for k, v in kw.items() if k not in leave_out})
            saved = True
            break
        except TypeError:  # an older Blender without that setting (or WebP)
            continue
        except Exception as e:  # noqa: BLE001
            why = str(e).strip().splitlines()[-1] if str(e).strip() else type(e).__name__
            fail("Blender couldn't save it as a GLB: " + why[:300])
    if not saved or not os.path.isfile(kw["filepath"]):
        fail("Blender didn't save a GLB")
    say("glb", os.path.getsize(kw["filepath"]), "%.1f" % (time.time() - t1))
    if frames <= 0:
        say("done", "%.1f" % (time.time() - t0))
        sys.stdout.flush()
        os._exit(0)

# Its own lights are switched off: the turntable has its lights (and its camera).
for o in scene.objects:
    if o.type in ("LIGHT", "LIGHT_PROBE", "LIGHTPROBE"):
        o.hide_render = True
bpy.context.view_layer.update()

# What renders, as points in the world: every mesh, instanced or not, as Blender has
# evaluated it (modifiers, a rig's pose).
import numpy as np  # noqa: E402

dg = bpy.context.evaluated_depsgraph_get()
shapes = ("MESH", "CURVE", "SURFACE", "META", "FONT")
pts, faces, seen = [], 0, {}
for inst in dg.object_instances:
    ob = inst.object
    if ob.type not in shapes or ob.original.hide_render:
        continue
    key = ob.name
    if key not in seen:  # an object instanced many times is read once
        seen[key] = None
        try:
            me = ob.to_mesh()
        except RuntimeError:
            me = None
        if me is not None:
            n = len(me.vertices)
            if n and len(me.polygons):
                co = np.empty(n * 3, dtype=np.float64)
                me.vertices.foreach_get("co", co)
                co = co.reshape(n, 3)
                if n > 400000:  # a heavy mesh: every few points, and the corners of its box
                    co = np.concatenate([co[:: n // 200000], [[x, y, z] for x in (co[:, 0].min(), co[:, 0].max())
                                                               for y in (co[:, 1].min(), co[:, 1].max()) for z in (co[:, 2].min(), co[:, 2].max())]])
                seen[key] = (co, len(me.polygons))
            ob.to_mesh_clear()
    if seen[key] is None:
        continue
    co, nf = seen[key]
    m = np.array(inst.matrix_world)
    pts.append(co @ m[:3, :3].T + m[:3, 3])
    faces += nf
if not pts:
    fail("it has no faces to show")
P = np.concatenate(pts)
if not np.isfinite(P).all():
    P = P[np.isfinite(P).all(axis=1)]
mn, mx = P.min(axis=0), P.max(axis=0)
cx, cy, floor_z = (mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mn[2]
r = float(np.sqrt((P[:, 0] - cx) ** 2 + (P[:, 1] - cy) ** 2).max())
h = float(mx[2] - mn[2])
if max(r, h) <= 0:
    fail("it has no size")
k = 2.0 / max(r, h)  # it's turned at one size, whatever its units
del P, pts

# The spin: the middle of its footprint, on the ground, goes to the world's origin.
spin = bpy.data.objects.new("chimera_spin", None)
pivot = bpy.data.objects.new("chimera_pivot", None)
scene.collection.objects.link(spin)
scene.collection.objects.link(pivot)
pivot.parent = spin
for o in list(scene.objects):
    if o.parent is None and o not in (spin, pivot):
        o.parent = pivot
pivot.matrix_basis = Matrix.Diagonal((k, k, k, 1.0)) @ Matrix.Translation((-cx, -cy, -floor_z))
R, H = r * k, h * k

# The camera: a product shot from a little above, as close as it can be while the
# whole spin stays in frame (with a margin for the shadow), and centred up and down.
cam_data = bpy.data.cameras.new("chimera_camera")
cam_data.lens, cam_data.sensor_width = 70, 36
cam = bpy.data.objects.new("chimera_camera", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
elev = math.radians(14)
tan_half = (cam_data.sensor_width / 2) / cam_data.lens
ring = [Vector((R * math.cos(a), R * math.sin(a), z)) for a in np.linspace(0, 2 * math.pi, 96, endpoint=False) for z in (0.0, H)]


def view(d, aim):
    target = Vector((0, 0, aim))
    loc = target + Vector((0, -d * math.cos(elev), d * math.sin(elev)))
    rot = (target - loc).to_track_quat('-Z', 'Y').to_matrix()
    inv = rot.transposed()
    xs, ys = [], []
    for p in ring:
        q = inv @ (p - loc)
        if q.z > -1e-6:
            return None
        xs.append(q.x / -q.z / tan_half)
        ys.append(q.y / -q.z / tan_half)
    return max(abs(x) for x in xs), max(ys), min(ys), loc, rot


aim, d = H / 2, 10.0
for _ in range(5):
    lo, hi = 0.01, 1000.0
    for _ in range(60):
        mid = (lo + hi) / 2
        v = view(mid, aim)
        if v is None or max(v[0], v[1], -v[2]) > 0.9:
            lo = mid
        else:
            hi = mid
    d = hi
    _, top, bottom, loc, rot = view(d, aim)
    ray = rot @ Vector((0, (top + bottom) / 2 * tan_half, -1))
    if abs(ray.y) > 1e-9:
        aim = loc.z + ray.z * (-loc.y / ray.y)
target = Vector((0, 0, aim))
cam.location = target + Vector((0, -d * math.cos(elev), d * math.sin(elev)))
cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()
cam_data.clip_start, cam_data.clip_end = max(1e-4, (d - 2 * R) / 100), d * 4 + 10

# Studio light: a big soft key from above left, a fill, and two rims so the edges read
# on a dark page; a dim grey world for what the lights don't reach.
s = max(R, H)
centre = Vector((0, 0, H * 0.5))


def area(name, at, size, energy, color=(1, 1, 1)):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.size, ld.energy, ld.color = size, energy, color
    o = bpy.data.objects.new(name, ld)
    scene.collection.objects.link(o)
    o.location = centre + Vector(at)
    o.rotation_euler = (centre - o.location).to_track_quat('-Z', 'Y').to_euler()


area("chimera_key", (-1.6 * s, -1.4 * s, 2.2 * s), 2.2 * s, 170 * s * s, (1.0, 0.97, 0.93))
area("chimera_fill", (1.8 * s, -1.2 * s, 0.9 * s), 2.5 * s, 55 * s * s, (0.92, 0.95, 1.0))
area("chimera_rim_l", (-1.7 * s, 1.6 * s, 1.2 * s), 1.2 * s, 140 * s * s, (1.0, 0.85, 0.7))
area("chimera_rim_r", (1.7 * s, 1.6 * s, 1.0 * s), 1.2 * s, 110 * s * s)
world = bpy.data.worlds.new("chimera_world")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
if bg is not None:
    bg.inputs["Color"].default_value = (0.05, 0.05, 0.055, 1)
    bg.inputs["Strength"].default_value = 0.35

# A shadow catcher under it: the frames keep a soft contact shadow and nothing else.
floor_me = bpy.data.meshes.new("chimera_floor")
half = s * 4
floor_me.from_pydata([(-half, -half, 0), (half, -half, 0), (half, half, 0), (-half, half, 0)], [], [(0, 1, 2, 3)])
floor = bpy.data.objects.new("chimera_floor", floor_me)
scene.collection.objects.link(floor)
floor.is_shadow_catcher = True


# Surfaces: a part with no material gets its colours (a PLY's or an STL's) or a plain
# light grey; an OBJ's materials, which rarely say how glossy they are, read as
# painted metal, a touch glossy, where the import made them very rough.
def principled(nt):
    return next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)


def plain(name, colour_attr=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = principled(m.node_tree)
    if p is not None:
        p.inputs["Base Color"].default_value = (0.62, 0.62, 0.6, 1)
        p.inputs["Roughness"].default_value = 0.45
        if colour_attr:
            a = m.node_tree.nodes.new("ShaderNodeVertexColor")
            a.layer_name = colour_attr
            m.node_tree.links.new(a.outputs["Color"], p.inputs["Base Color"])
    return m


grey = None
for o in scene.objects:
    if o.type != "MESH" or o.hide_render or any(sl.material for sl in o.material_slots):
        continue
    attrs = getattr(o.data, "color_attributes", None)
    if attrs is not None and len(attrs):
        o.data.materials.append(plain("chimera_colours", attrs[0].name))
    else:
        grey = grey or plain("chimera_grey")
        o.data.materials.append(grey)
if ext == ".obj":
    for m in bpy.data.materials:
        p = principled(m.node_tree) if m.node_tree else None
        if p is not None and p.inputs["Roughness"].default_value > 0.6 and not p.inputs["Roughness"].is_linked:
            p.inputs["Roughness"].default_value = 0.42

scene.render.engine = 'CYCLES'
device = "CPU"
if opt.get("gpu", True):
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for kind in ("METAL", "OPTIX", "CUDA", "HIP", "ONEAPI"):
            try:
                prefs.compute_device_type = kind
            except TypeError:
                continue
            prefs.get_devices()
            gpus = [x for x in prefs.devices if x.type == kind]
            if gpus:
                for x in prefs.devices:
                    x.use = x.type == kind
                if kind == "METAL" and hasattr(prefs, "kernel_optimization_level"):
                    # Scene-specialised kernels are compiled in the background, through
                    # a path the sandbox hides (Blender 5.2.2 aborts on it): the generic
                    # ones, kept in the cache, are what this uses.
                    prefs.kernel_optimization_level = 'OFF'
                scene.cycles.device = 'GPU'
                device = "GPU (%s)" % ", ".join(x.name for x in gpus)
                break
    except Exception as e:  # noqa: BLE001
        say("no GPU:", e)
say("device", device)
scene.cycles.samples = samples
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 6
scene.render.use_persistent_data = True
scene.render.film_transparent = True
scene.render.resolution_x = scene.render.resolution_y = px
scene.render.resolution_percentage = 100
ims = scene.render.image_settings
if hasattr(ims, "media_type"):
    ims.media_type = 'IMAGE'
try:
    ims.file_format = 'WEBP'
    dot = ".webp"
except TypeError:
    ims.file_format = 'PNG'
    dot = ".png"
ims.color_mode = 'RGBA'
ims.quality = 80
try:
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.look = 'AgX - Medium High Contrast'
except TypeError:
    scene.view_settings.view_transform = 'Filmic'
    scene.view_settings.look = 'Medium High Contrast'
say("info", json.dumps({"faces": faces, "size": [round(float(mx[i] - mn[i]), 4) for i in range(3)],
                        "spin_radius": round(r, 4), "device": device, "format": dot[1:], "setup_s": round(time.time() - t0, 1)}))

pad = max(2, len(str(frames - 1)))
for f in range(frames):
    t = time.time()
    spin.rotation_euler = (0, 0, math.radians(start + 360.0 * f / frames))
    scene.render.filepath = os.path.join(out, "f%0*d%s" % (pad, f, dot))
    bpy.ops.render.render(write_still=True)
    if f == 0:
        ims.quality = 88
        bpy.data.images["Render Result"].save_render(os.path.join(out, "poster" + dot), scene=scene)
        ims.quality = 80
    say("frame", f, "%.2f" % (time.time() - t))
say("done", "%.1f" % (time.time() - t0))
