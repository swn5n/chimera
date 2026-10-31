"""Runs inside Blender (blender -b --factory-startup --python rna_dump_blender.py -- OUT.json).

Dumps Blender's own API facts as JSON for tools/rna_dump.py: every RNA class's own properties
(type, pointer target, enum items), functions and Python attributes, the sockets of every node
type it can make in each node tree type, the type-to-class maps for modifiers, lights, textures
and curves, dynamic enums (render engines, view transforms), module and operator names. Facts
only, made by Blender itself: teacher-only hints and a lint, never training text.
"""
import json
import re
import sys
import time

import bpy

T0 = time.time()
ENUM_CAP = 300  # an enum with more items is cut (icon lists and the like)
SKIP_CLASS = re.compile(r"_(PT|MT|HT|UL|OT|GT|GGT|AST)_")  # UI and operator classes: not script data


def own(rna, cls=None):
    """An RNA struct's own properties and functions (not its base's), and its class's own Python attributes."""
    base = rna.base
    bprops = set(base.properties.keys()) if base else set()
    bfuncs = set(base.functions.keys()) if base else set()
    props = {}
    for p in rna.properties:
        if p.identifier in bprops:
            continue
        d = {"type": p.type}
        if p.type in ("POINTER", "COLLECTION") and getattr(p, "fixed_type", None) is not None:
            d["fixed"] = p.fixed_type.identifier
            if p.type == "COLLECTION" and getattr(p, "srna", None) is not None:
                d["srna"] = p.srna.identifier
        if p.type == "ENUM":
            items = [e.identifier for e in p.enum_items]
            d["items"] = items[:ENUM_CAP]
            if len(items) > ENUM_CAP:
                d["cut"] = len(items)
            if p.is_enum_flag:
                d["flag"] = True
        if p.is_readonly:
            d["ro"] = True
        props[p.identifier] = d
    funcs = sorted(f.identifier for f in rna.functions if f.identifier not in bfuncs)
    # Each function's keyword parameters (inputs only); "**" when it takes any keyword.
    fparams = {f.identifier: [x.identifier for x in f.parameters if not x.is_output]
               for f in rna.functions if f.identifier not in bfuncs}
    py = []
    if cls is not None:
        pybase = cls.__mro__[1] if len(cls.__mro__) > 1 else object
        py = sorted(a for a in set(dir(cls)) - set(dir(pybase)) - set(props) - set(funcs) if not a.startswith("__"))
        for a in py:
            sig = py_params(getattr(cls, a, None))
            if sig is not None:
                fparams[a] = sig
    out = {"base": base.identifier if base else "bpy_struct", "props": props, "funcs": funcs, "py": py}
    if fparams:
        out["fparams"] = fparams
    return out


def py_params(fn):
    """A Python method's keyword names (without self), "**" for **kwargs, or None if it has no signature."""
    import inspect
    if not inspect.isfunction(fn):
        return None
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    out = []
    for i, (name, p) in enumerate(sig.parameters.items()):
        if i == 0 and name in ("self", "cls"):
            continue
        if p.kind == p.VAR_KEYWORD:
            out.append("**")
        elif p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY):
            out.append(name)
    return out


def classes():
    """Every class in bpy.types, plus the structs only reachable through a property (an add-on's
    settings such as Scene.cycles, collection helpers such as ObjectModifiers), with their bases."""
    out = {"bpy_struct": {"base": None, "props": {}, "funcs": [],
                          "py": sorted(a for a in dir(bpy.types.bpy_struct) if not a.startswith("__"))}}
    failed = {}
    todo = []
    for name in dir(bpy.types):
        cls = getattr(bpy.types, name, None)
        if SKIP_CLASS.search(name) or not hasattr(cls, "bl_rna"):
            continue
        todo.append((cls.bl_rna, cls))
    while todo:
        rna, cls = todo.pop()
        ident = rna.identifier
        if ident in out or SKIP_CLASS.search(ident):
            continue
        if cls is None:
            cls = getattr(bpy.types, ident, None)
        try:
            out[ident] = own(rna, cls)
        except Exception as e:  # noqa: BLE001
            failed[ident] = type(e).__name__
            continue
        if rna.base is not None and rna.base.identifier not in out:
            todo.append((rna.base, None))
        for p in rna.properties:
            if p.type in ("POINTER", "COLLECTION"):
                for s in (getattr(p, "fixed_type", None), getattr(p, "srna", None)):
                    if s is not None and s.identifier not in out:
                        todo.append((s, None))
    return out, failed


def sockets(coll):
    return [[s.name, s.identifier, s.bl_idname] for s in coll]


def node_trees():
    """One tree per node tree type, in the order to try (materials first: some shader nodes only go there)."""
    trees = {}
    mat = bpy.data.materials.new("chimera_dump_mat")
    world = bpy.data.worlds.new("chimera_dump_world")
    for idb in (mat, world):
        if idb.node_tree is None:  # 5.x makes the tree already (use_nodes is deprecated there)
            idb.use_nodes = True
    shader = [t for t in (mat.node_tree, world.node_tree) if t is not None]
    for kind in ("ShaderNodeTree", "GeometryNodeTree", "CompositorNodeTree", "TextureNodeTree"):
        try:
            trees.setdefault(kind, []).append(bpy.data.node_groups.new("chimera_dump_" + kind, kind))
        except Exception as e:  # noqa: BLE001
            trees.setdefault(kind, [])
            print("chimera-dump: no", kind, type(e).__name__, e)
    trees["ShaderNodeTree"] = shader + trees["ShaderNodeTree"]
    defaults = {"material": [[n.name, n.bl_idname] for n in mat.node_tree.nodes] if mat.node_tree else [],
                "world": [[n.name, n.bl_idname] for n in world.node_tree.nodes] if world.node_tree else []}
    return trees, defaults


def nodes():
    trees, defaults = node_trees()
    out = {k: {} for k in trees}
    tried = set()
    for name in dir(bpy.types):
        cls = getattr(bpy.types, name, None)
        try:
            if not (isinstance(cls, type) and issubclass(cls, bpy.types.Node)):
                continue
        except TypeError:
            continue
        idname = cls.bl_rna.identifier
        tried.add(idname)
        for kind, tlist in trees.items():
            for tree in tlist:
                try:
                    n = tree.nodes.new(idname)
                except Exception:  # noqa: BLE001  (not allowed in this tree, or abstract)
                    continue
                # Sockets can change with the node's settings (dynamic): a collection property of
                # its own (repeat items, capture items, menu items) means a script may add more.
                dyn = any(p.type == "COLLECTION" for p in cls.bl_rna.properties
                          if p.identifier not in bpy.types.Node.bl_rna.properties)
                # label: what nodes.new names it ("Principled BSDF"), so nodes["..."] can be typed.
                out[kind][idname] = {"label": n.bl_label, "inputs": sockets(n.inputs),
                                     "outputs": sockets(n.outputs), "dynamic": dyn}
                live_enums(n)
                tree.nodes.remove(n)
                break
    made = {i for k in out.values() for i in k}
    return out, sorted(tried - made), defaults


LIVE = {}  # "Class.prop" -> the values Blender accepts, measured on a real instance


def live_enums(inst):
    """Every settable, single-value enum of a live struct, with the values its error message lists.
    Static enum items can't be trusted: dynamic enums (engine, view transform, colour spaces) show
    a placeholder there."""
    rna = inst.bl_rna
    for p in rna.properties:
        if p.type != "ENUM" or p.is_enum_flag or p.is_readonly or p.identifier.startswith("bl_"):
            continue
        key = rna.identifier + "." + p.identifier
        if key in LIVE:
            continue
        items = dynamic_enum(inst, p.identifier)
        if items and len(items) <= ENUM_CAP:  # not icon lists and the like
            LIVE[key] = items


def type_map(make, items):
    """{enum value: the RNA class Blender makes for it} (None where it can't make one here)."""
    out = {}
    for t in items:
        try:
            out[t] = make(t)
        except Exception:  # noqa: BLE001
            out[t] = None
    return out


def enum_items(cls, prop):
    return [e.identifier for e in cls.bl_rna.properties[prop].enum_items]


def type_maps():
    obj = bpy.data.objects.new("chimera_dump_obj", bpy.data.meshes.new("chimera_dump_mesh"))

    def modifier(t):
        m = obj.modifiers.new("m", t)
        live_enums(m)
        name = m.bl_rna.identifier
        obj.modifiers.remove(m)
        return name

    def constraint(t):
        c = obj.constraints.new(t)
        live_enums(c)
        name = c.bl_rna.identifier
        obj.constraints.remove(c)
        return name

    def made(x):
        live_enums(x)
        return x.bl_rna.identifier

    return {
        "modifier": type_map(modifier, enum_items(bpy.types.Modifier, "type")),
        "constraint": type_map(constraint, enum_items(bpy.types.Constraint, "type")),
        "light": type_map(lambda t: made(bpy.data.lights.new("l", t)), enum_items(bpy.types.Light, "type")),
        "texture": type_map(lambda t: made(bpy.data.textures.new("t", t)), enum_items(bpy.types.Texture, "type")),
        "curve": type_map(lambda t: made(bpy.data.curves.new("c", t)), ["CURVE", "SURFACE", "FONT"]),
    }


def live_instances():
    """Live enums of the structs a fresh scene has: scene settings, the default objects and their data."""
    s = bpy.context.scene
    insts = [s, s.render, s.render.image_settings, s.view_settings, s.display_settings, s.sequencer_colorspace_settings,
             s.unit_settings, s.eevee, s.display, s.display.shading, s.world, s.view_layers[0], s.collection]
    for name in ("cycles", "cycles_curves"):
        if hasattr(s, name):
            insts.append(getattr(s, name))
    for o in s.objects:
        insts += [o, o.data]
        if hasattr(o, "cycles"):
            insts.append(o.cycles)
    img = bpy.data.images.new("chimera_dump_img", 4, 4)
    insts += [img, img.colorspace_settings, bpy.data.materials.new("chimera_dump_enum_mat"),
              bpy.data.cameras.new("chimera_dump_cam"), bpy.data.actions.new("chimera_dump_action")]
    for x in insts:
        try:
            live_enums(x)
        except Exception:  # noqa: BLE001
            pass


def dynamic_enum(owner, prop):
    """Items of an enum Blender fills at run time, read from the error a bad value gives."""
    try:
        setattr(owner, prop, "__chimera_not_a_value__")
    except TypeError as e:
        tail = str(e).split("not found in", 1)
        return re.findall(r"'([^']+)'", tail[1]) if len(tail) == 2 else []
    return []


def dynamic_enums():
    s = bpy.context.scene
    return {"RenderSettings.engine": dynamic_enum(s.render, "engine"),
            "ColorManagedViewSettings.view_transform": dynamic_enum(s.view_settings, "view_transform"),
            "ColorManagedViewSettings.look": dynamic_enum(s.view_settings, "look"),
            "ColorManagedDisplaySettings.display_device": dynamic_enum(s.display_settings, "display_device")}


# Python packages whose submodules a script may import (from bpy_extras import anim_utils): every submodule gets an
# entry of its own, and the package's names include all its submodules, imported yet or not.
PACKAGES = ("bpy_extras", "bpy.utils")


def submodules(m):
    """The submodule names of a Python package (none for a plain or C module), folders without an __init__.py
    (namespace packages, such as bpy_extras.wm_utils) included."""
    import os
    import pkgutil
    path = list(getattr(m, "__path__", None) or [])
    names = {x.name for x in pkgutil.iter_modules(path)}
    for d in path:
        try:
            names.update(n for n in os.listdir(d) if n.isidentifier() and n != "__pycache__"
                         and os.path.isdir(os.path.join(d, n)))
        except OSError:
            pass
    return sorted(names)


def modules():
    import importlib
    out = {}
    names = ["bpy", "bpy.types", "bpy.ops", "bpy.app", "bpy.app.handlers", "bpy.utils", "bpy.path", "bpy.props", "bpy.msgbus",
             "mathutils", "mathutils.noise", "mathutils.geometry", "mathutils.bvhtree", "mathutils.kdtree",
             "mathutils.interpolate", "bmesh", "bmesh.ops", "bmesh.types", "bmesh.utils", "bmesh.geometry", "bpy_extras"]
    for pkg in PACKAGES:
        try:
            names += [pkg + "." + s for s in submodules(importlib.import_module(pkg)) if pkg + "." + s not in names]
        except Exception:  # noqa: BLE001
            continue
    found = {}
    for n in names:
        try:
            m = importlib.import_module(n)
        except Exception:  # noqa: BLE001
            try:  # bpy.app.handlers and the like are attributes, not importable modules
                head, _, tail = n.rpartition(".")
                m = getattr(importlib.import_module(head), tail)
            except Exception:  # noqa: BLE001
                continue
        found[n] = m
    # dir() only after every import above: importing a submodule adds it to its package's names
    for n, m in found.items():
        out[n] = sorted({a for a in dir(m) if not a.startswith("__")} | set(submodules(m)))
    import mathutils
    import bmesh
    # What every RNA collection has (keys, get, foreach_set, ...), whatever its own helpers.
    out["bpy.types.bpy_prop_collection"] = sorted(a for a in dir(bpy.types.bpy_prop_collection) if not a.startswith("__"))
    for n in ("Vector", "Matrix", "Euler", "Quaternion", "Color"):
        out["mathutils." + n] = sorted(a for a in dir(getattr(mathutils, n)) if not a.startswith("__"))
    for n in dir(bmesh.types):
        if n.startswith("BM"):
            out["bmesh.types." + n] = sorted(a for a in dir(getattr(bmesh.types, n)) if not a.startswith("__"))
    return out


def ops():
    """{group: [operator, ...]} and {"group.operator": [its keyword properties]}."""
    out, props = {}, {}
    for sub in dir(bpy.ops):
        if sub.startswith("_"):
            continue
        try:
            mod = getattr(bpy.ops, sub)
            out[sub] = sorted(o for o in dir(mod) if not o.startswith("_"))
        except Exception:  # noqa: BLE001
            continue
        for o in out[sub]:
            try:
                props[sub + "." + o] = sorted(p.identifier for p in getattr(mod, o).get_rna_type().properties
                                              if p.identifier != "rna_type")
            except Exception:  # noqa: BLE001
                pass
    return out, props


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        raise SystemExit("usage: blender -b --factory-startup --python rna_dump_blender.py -- OUT.json")
    cls, cls_failed = classes()
    node_info, node_failed, default_trees = nodes()  # also fills LIVE from every node it makes
    types = type_maps()                              # and from every modifier, constraint, light, ...
    live_instances()
    op_names, op_props = ops()
    d = {
        "note": "Made by Blender itself (worker-model/tools/rna_dump.py): API facts for teacher hints and the lint. "
                "Not training text.",
        "blender": "%d.%d.%d" % tuple(bpy.app.version[:3]),
        "version_string": bpy.app.version_string,
        "build_hash": bpy.app.build_hash.decode() if isinstance(bpy.app.build_hash, bytes) else str(bpy.app.build_hash),
        "made": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "classes": cls,
        "classes_failed": cls_failed,
        "nodes": node_info,
        "nodes_not_made": node_failed,
        "default_trees": default_trees,
        "types": types,
        "dynamic_enums": dynamic_enums(),
        "live_enums": LIVE,
        "context": sorted(a for a in dir(bpy.context) if not a.startswith("__")),
        "modules": modules(),
        "ops": op_names,
        "op_props": op_props,
    }
    d["seconds"] = round(time.time() - T0, 1)
    with open(argv[0], "w", encoding="utf-8") as f:
        json.dump(d, f, separators=(",", ":"), sort_keys=True)
    n = sum(len(v) for v in node_info.values())
    print("chimera-dump: wrote %s: %d classes, %d nodes, %d not made, %.1f s" % (argv[0], len(cls), n, len(node_failed), d["seconds"]))


main()
