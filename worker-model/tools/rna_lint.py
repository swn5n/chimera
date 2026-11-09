"""Flag Blender API names in a script that neither Blender's own dump knows (data/rna/<version>.json).

Best effort and precision first: it's teacher-only help and a data filter, so it only speaks when
it knows what a name refers to. It types variables from what the script itself does
(bpy.data.objects.new, obj.modifiers.new(type="BEVEL"), nodes.new("ShaderNodeTexNoise"),
nodes["Principled BSDF"], bpy.context.scene.render, the contract's ctx["scene"], for-loops over
collections, ...) and follows RNA pointers from the dump. A name bound anywhere in a way it can't
type (a parameter, a tuple, an unknown call) is left alone in that scope.

Findings:
- error: the name exists in neither version (a crash in both): attributes, node input/output
  names, node type ids, modifier/light types, enum values, mathutils/bmesh/bpy module names,
  bpy.ops operators, bpy.types classes, from-imports. Also a node input Blender never makes
  available to a script (usable(): the shaders' Weight), which inputs['Weight'] can't find.
- warn: it exists in only one of the versions.
- syntax: the script doesn't parse.
Each finding says what does exist nearby (difflib), for the teacher's repair turn.

An attribute read that can't run without the name being there is no finding (guards(), Nov 5): one behind
hasattr(x, "name"), or getattr(x, "name", <a falsy default>), on the same expression (an if or elif test, a while
test, an and, an or after a not, a conditional expression, a comprehension's if, an assert, or an early return,
continue, break or raise when it is missing), and anything in the body behind hasattr(x, "name") where no version's
x has the name, a branch no version can reach. A try around an access is no guard (the hidden-errors check,
datagen/silent.py, holds such a piece to what it caught). After the independent checks (Nov 6) three things are no
guard either: a hasattr or getattr on bpy.ops or one of its groups (it answers any name, so it is always true and
the dead operator behind it runs), the elif or else behind a hasattr whose name every version's x has (x may be
None: scene.camera, a .get(), the active object), and an assert or a raise when it is missing on a name no version
has (that is a certain crash, so its finding, and the fix the teacher hears on it, stay).
n-blender-0000-01 r2 s3 c5 of the fourth smoke was dropped for `elif hasattr(act, "fcurves") and act.fcurves:`
behind a working channelbag path, though it runs clean in both Blenders. Whether a guard then skipped what the step
asks for is the gate's to judge (datagen/silent.py's attr_miss).
The rule is data generation's only (decided Nov 6): it is on in a Linter made with guards=True, which the data
generator's linters are (datagen/run.py, datagen.blender_gate.BlenderGate's own), and off by default, so the worker
eval (runner/score.py, step_eval.py, task_eval.py and freeze.py's verify, a pass/fail gate on W1's frozen inputs),
tools/rna_dump.py's lint command and lint_source() lint exactly as before Nov 5.
"""
from __future__ import annotations

import ast
import difflib
import glob
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # worker-model/
RNA_DIR = os.path.join(HERE, "data", "rna")

# bpy.context members that aren't RNA properties of Context (they're filled in at run time).
CONTEXT = {"scene": "Scene", "view_layer": "ViewLayer", "collection": "Collection", "active_object": "Object",
           "object": "Object", "edit_object": "Object", "preferences": "Preferences",
           "window_manager": "WindowManager", "blend_data": "BlendData", "selected_objects": "[]Object",
           "visible_objects": "[]Object", "selectable_objects": "[]Object", "selected_editable_objects": "[]Object"}
BPY_MODULES = ("app", "utils", "path", "props", "msgbus", "types", "ops")
# Nodes whose sockets come from a node group or that a script builds itself: never socket-checked.
GROUPISH = ("Group", "GroupInput", "GroupOutput", "CustomGroup")
# Structs Blender makes per node group at run time: in 5.2.2 a geometry-nodes modifier's `properties` is a
# GeometryNodesModifierInterface (inputs, outputs, panels) made for its group, while the dump sees only the empty
# static type. Their attributes (and their subclasses') are never checked.
DYNAMIC_STRUCTS = ("NodesModifierProperties", "SequencerCompositorModifierProperties", "AddonPreferences")
SIDES = ("inputs", "outputs")


def usable(info, side, sock):
    """Whether a script can reach socket sock (a dump's [name, identifier, socket type, available]) of the node whose
    dump entry is info: always for an output (5.0.1's Render Layers passes come from the view layer, not the node, and
    a script reads outputs to link them) and for an old dump's three-field socket; else when it is available on a
    fresh node, when a setting the dump measured reveals its name (info["reveal"], tools/rna_dump_blender.py: Noise's
    W with noise_dimensions 1D or 4D, Map Range's Steps with interpolation_type STEPPED, Mesh Line's Resolution with a
    pair), or when another socket of its name is available (Mix's A_Vector is its A input once data_type is VECTOR).
    inputs[name] finds only an available socket, so one none of these reach raises KeyError whatever the script sets:
    in 5.2.2 and 5.0.1 that is the Weight input of 22 shader nodes (the Principled BSDF's, Emission's, Glass's) and
    nothing else. The lint and the teacher's facts (datagen.hints) use this one rule, on Facts.node's entry."""
    if side == "outputs" or len(sock) < 4 or sock[3]:
        return True
    if sock[0] in info.get("reveal", {}).get(side, {}):
        return True
    return any(len(s) > 3 and s[3] and s[0] == sock[0] for s in info.get(side, ()))


def _merged(first, other):
    """first (a node type's entry in the first tree type the dump made it in) with what other (its entry in a later
    tree type) adds: a socket available in either is available, and a name that is then available leaves the reveal.
    5.2.2's compositor makes Object Info with As Instance and Geometry unavailable, while a geometry tree has both;
    Facts.node gives the compositor's entry first (the dump's keys are sorted), so without this the lint would call
    a geometry script's inputs['As Instance'] never available. first itself when nothing changes, so an old dump's
    entries (three fields) are what they were."""
    flip = {side: {(s[0], s[1]) for s in other.get(side, ()) if len(s) > 3 and s[3]} for side in SIDES}
    if not any(len(s) > 3 and not s[3] and (s[0], s[1]) in flip[side] for side in SIDES for s in first.get(side, ())):
        return first
    out = dict(first)
    reveal = {}
    for side in SIDES:
        out[side] = [list(s[:3]) + [True] + list(s[4:]) if len(s) > 3 and not s[3] and (s[0], s[1]) in flip[side]
                     else s for s in first.get(side, ())]
        shown = {s[0] for s in out[side] if len(s) > 3 and s[3]}
        got = {}
        for e in (first, other):
            for name, settings in e.get("reveal", {}).get(side, {}).items():
                if name not in shown:
                    got.setdefault(name, [])
                    got[name] += [x for x in settings if x not in got[name]]
        reveal[side] = got
    out["reveal"] = reveal
    return out


class Facts:
    """Both versions' dumps, with lookups that answer per version."""

    def __init__(self, dumps):
        if not dumps:
            raise ValueError(f"no RNA dumps: run python3 tools/rna_dump.py dump (they go in {RNA_DIR})")
        self.dumps = dumps
        self.versions = sorted(dumps, key=lambda v: [int(x) for x in v.split(".")], reverse=True)
        self._attrs = {}
        self._sub = None
        self.labels = {}
        self.node_ids = set()
        # sockets_all: the names and identifiers a script can reach on some node type (usable); sockets_seen also
        # those it can't (the shaders' Weight), which an old dump never has.
        self.sockets_all = {s: set() for s in SIDES}
        self.sockets_seen = {s: set() for s in SIDES}
        self._nodes = {}  # version -> {idname: its entry, merged over the tree types it is made in (_merged)}
        for v, d in dumps.items():
            merged = self._nodes.setdefault(v, {})
            for tree in d["nodes"].values():
                for idname, n in tree.items():
                    self.node_ids.add(idname)
                    self.labels.setdefault(n["label"], set()).add(idname)
                    merged[idname] = _merged(merged[idname], n) if idname in merged else n
                    for s in SIDES:
                        self.sockets_all[s].update(x for sock in n[s] if usable(n, s, sock) for x in sock[:2])
                        self.sockets_seen[s].update(x for sock in n[s] for x in sock[:2])
            for tree in d.get("default_trees", {}).values():
                for name, idname in tree:
                    self.labels.setdefault(name, set()).add(idname)

    @classmethod
    def load(cls, rna_dir=RNA_DIR):
        dumps = {}
        for path in sorted(glob.glob(os.path.join(rna_dir, "*.json"))):
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and "classes" in d:
                dumps[d["blender"]] = d
        return cls(dumps)

    def has_class(self, name, v=None):
        vs = [v] if v else self.versions
        return any(name in self.dumps[x]["classes"] for x in vs)

    def attrs(self, name, v):
        """Every attribute an instance of class `name` has in version v (None if no such class there)."""
        key = (name, v)
        if key not in self._attrs:
            classes = self.dumps[v]["classes"]
            out, c, seen = set(), name, set()
            if name not in classes:
                self._attrs[key] = None
                return None
            while c and c in classes and c not in seen:
                seen.add(c)
                k = classes[c]
                out.update(k["props"], k["funcs"], k["py"])
                c = k["base"]
            out.update(classes["bpy_struct"]["py"] if "bpy_struct" in classes else ())
            self._attrs[key] = out
        return self._attrs[key]

    def prop(self, name, attr, v):
        """The property dict for name.attr in v, looked up through the bases (None if none)."""
        classes = self.dumps[v]["classes"]
        c, seen = name, set()
        while c and c in classes and c not in seen:
            seen.add(c)
            p = classes[c]["props"].get(attr)
            if p is not None:
                return p
            c = classes[c]["base"]
        return None

    def fparams(self, name, func, v):
        """Keyword names of name.func() in v, looked up through the bases (None if unknown)."""
        classes = self.dumps[v]["classes"]
        c, seen = name, set()
        while c and c in classes and c not in seen:
            seen.add(c)
            k = classes[c]
            if func in k.get("fparams", {}):
                return k["fparams"][func]
            if func in k["funcs"] or func in k["py"]:
                return None  # it's there, but without parameter facts
            c = k["base"]
        return None

    def collection_attrs(self, t, v):
        """What a collection of type "[]Item@Srna" has in v: bpy_prop_collection's methods plus its
        srna's properties and functions. None if the dump predates the collection facts."""
        base = self.module("bpy.types.bpy_prop_collection", v)
        if base is None:
            return None
        srna = t.split("@", 1)[1] if "@" in t else None
        if srna:
            extra = self.attrs(srna, v)
            if extra is None:
                return None
            return base | extra
        return base

    def subclasses(self, name):
        """name and every class whose base chain reaches it, in any version."""
        if self._sub is None:
            self._sub = {}
            for d in self.dumps.values():
                for c, k in d["classes"].items():
                    if k["base"]:
                        self._sub.setdefault(k["base"], set()).add(c)
        out, todo = set(), [name]
        while todo:
            c = todo.pop()
            if c in out:
                continue
            out.add(c)
            todo.extend(self._sub.get(c, ()))
        return out

    def node(self, idname, v):
        """idname's entry in v: the first tree type's, with what its other tree types make available (_merged)."""
        return self._nodes[v].get(idname)

    def is_node(self, idname):
        return [v for v in self.versions if self.node(idname, v) is not None]

    def module(self, name, v):
        m = self.dumps[v].get("modules", {}).get(name)
        return None if m is None else set(m)

    def ops(self, sub, v):
        o = self.dumps[v].get("ops", {}).get(sub)
        return None if o is None else set(o)

    def op_props(self, op, v):
        """The keyword properties of operator "group.name" in v (None if unknown)."""
        p = self.dumps[v].get("op_props", {}).get(op)
        return None if p is None else set(p)

    def type_map(self, kind):
        """{enum value: {class, ...}} for modifier, light, texture or curve types, over both versions."""
        out = {}
        for d in self.dumps.values():
            for k, c in (d.get("types", {}).get(kind) or {}).items():
                out.setdefault(k, set())
                if c:
                    out[k].add(c)
        return out

    def enum_items(self, cls, attr, v):
        """Values an enum property takes in v, or None when the dump has no live measurement of it.
        Only values measured on a live instance count (static items are a placeholder for dynamic
        enums such as the render engine); the static ones are added because a live list can be
        narrowed by the instance's state (file formats by media type)."""
        p = self.prop(cls, attr, v)
        if not p or p.get("type") != "ENUM" or p.get("flag") or p.get("cut"):
            return None
        d = self.dumps[v]
        for c in [cls] + self._bases(cls, v):
            live = d.get("live_enums", {}).get(f"{c}.{attr}") or d.get("dynamic_enums", {}).get(f"{c}.{attr}")
            if live:
                return set(live) | set(p.get("items") or ())
        return None

    def _bases(self, name, v):
        classes, out, c = self.dumps[v]["classes"], [], name
        while c in classes and classes[c]["base"] and classes[c]["base"] not in out:
            c = classes[c]["base"]
            out.append(c)
        return out


# ---------- typing what the script binds ----------

def literal(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def call_arg(call, pos, kw):
    """The string literal passed as positional pos or keyword kw, else None."""
    for k in call.keywords:
        if k.arg == kw:
            return literal(k.value)
    if len(call.args) > pos:
        return literal(call.args[pos])
    return None


class Scope:
    def __init__(self, node, parent):
        self.node, self.parent = node, parent
        self.bindings = {}  # name -> list of ("expr", node) / ("iter", node) / ("unknown", None) / ("type", set)
        self.env = {}       # name -> frozenset of types, or None (can't tell)
        self.globals = set()
        self.children = []

    def bind(self, name, how, node=None):
        self.bindings.setdefault(name, []).append((how, node))

    def lookup(self, name):
        s = self
        while s is not None:
            if name in s.globals:
                s = s.root()
                return s.env.get(name)
            if name in s.bindings:
                return s.env.get(name)
            s = s.parent
        return None

    def root(self):
        s = self
        while s.parent is not None:
            s = s.parent
        return s


def _bind_target(scope, t, how, node):
    if isinstance(t, ast.Name):
        scope.bind(t.id, how, node)
    elif isinstance(t, (ast.Tuple, ast.List)):
        for e in t.elts:
            _bind_target(scope, e, "unknown", None)
    elif isinstance(t, ast.Starred):
        _bind_target(scope, t.value, "unknown", None)


def collect(scope, body_nodes):
    """Record every binding in this scope; nested functions and classes get their own scopes."""
    stack = list(body_nodes)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            if not isinstance(n, ast.Lambda):
                scope.bind(n.name, "unknown")
                stack.extend(n.decorator_list)
            child = Scope(n, scope)
            scope.children.append(child)
            a = n.args
            for arg in a.posonlyargs + a.args + a.kwonlyargs + ([a.vararg] if a.vararg else []) + ([a.kwarg] if a.kwarg else []):
                child.bind(arg.arg, "unknown")
            stack.extend(d for d in a.defaults + a.kw_defaults if d is not None)
            collect(child, n.body if isinstance(n.body, list) else [n.body])
            continue
        if isinstance(n, ast.ClassDef):
            scope.bind(n.name, "unknown")
            child = Scope(n, scope)  # class bodies: names there are attributes, not variables in methods
            scope.children.append(child)
            collect(child, n.body)
            continue
        if isinstance(n, ast.Assign):
            for t in n.targets:
                _bind_target(scope, t, "expr", n.value)
        elif isinstance(n, ast.AnnAssign):
            _bind_target(scope, n.target, "expr" if n.value is not None else "unknown", n.value)
        elif isinstance(n, ast.AugAssign):
            _bind_target(scope, n.target, "unknown", None)
        elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
            _bind_target(scope, n.target, "iter", n.iter)
        elif isinstance(n, ast.NamedExpr):
            _bind_target(scope, n.target, "expr", n.value)
        elif isinstance(n, (ast.With, ast.AsyncWith)):
            for it in n.items:
                if it.optional_vars is not None:
                    _bind_target(scope, it.optional_vars, "unknown", None)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            scope.bind(n.name, "unknown")
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                if isinstance(n, ast.Import):
                    if al.asname:
                        scope.bind(al.asname, "type", {"module:" + al.name})
                    else:
                        top = al.name.split(".")[0]
                        scope.bind(top, "type", {"module:" + top})
                elif n.module == "bpy" and al.name in ("context", "data"):
                    scope.bind(al.asname or al.name, "type", {"Context" if al.name == "context" else "BlendData"})
                elif n.module and al.name != "*":
                    mod = f"{n.module}.{al.name}"
                    scope.bind(al.asname or al.name, "type", {"module:" + mod})
        elif isinstance(n, ast.Global):
            scope.globals.update(n.names)
        elif isinstance(n, ast.Nonlocal):
            for name in n.names:
                scope.bind(name, "unknown")
        elif isinstance(n, ast.Delete):
            for t in n.targets:
                _bind_target(scope, t, "unknown", None)
        elif hasattr(ast, "MatchAs") and isinstance(n, (ast.MatchAs, ast.MatchStar)) and getattr(n, "name", None):
            scope.bind(n.name, "unknown")
        stack.extend(ast.iter_child_nodes(n))


class Typer:
    def __init__(self, facts, script_defs):
        self.f = facts
        self.defs = script_defs

    def expand(self, cls):
        return frozenset(self.f.subclasses(cls))

    def of(self, node, scope):
        """frozenset of type names, or None. Types: RNA class names, "[]X@Srna" for collections of X,
        "module:name", "ops:sub", "Context"."""
        f = self.f
        if isinstance(node, ast.Name):
            return scope.lookup(node.id)
        if isinstance(node, ast.Attribute):
            base = self.of(node.value, scope)
            if not base:
                return None
            out = set()
            for t in base:
                r = self._attr_type(t, node.attr)
                if r is None:
                    return None
                out |= r
            return frozenset(out) or None
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name) and node.value.id == "ctx" and literal(node.slice) in ("scene", "collection"):
                return frozenset({"Scene" if literal(node.slice) == "scene" else "Collection"})
            base = self.of(node.value, scope)
            return self._item_type(base, node.slice)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            meth = node.func.attr
            base = self.of(node.func.value, scope)
            if not base:
                return None
            if base == {"module:bmesh"} and meth in ("new", "from_edit_mesh"):
                return frozenset({"module:bmesh.types.BMesh"})  # its attributes are checked like a module's
            if meth == "get" and node.args:
                return self._item_type(base, node.args[0])
            if meth == "copy" and all(not t.startswith(("[]", "module:", "ops:")) and t != "Context" for t in base):
                return base
            if meth == "new":
                out = set()
                for t in base:
                    r = self._new_type(t, node)
                    if r is None:
                        return None
                    out |= r
                return frozenset(out) or None
        return None

    def _attr_type(self, t, attr):
        f = self.f
        if t == "module:bpy":
            if attr == "context":
                return {"Context"}
            if attr == "data":
                return {"BlendData"}
            return {"module:bpy." + attr} if attr in BPY_MODULES else None
        if t == "module:bpy.ops":
            return {"ops:" + attr}
        if t.startswith("module:"):
            name = t[len("module:"):] + "." + attr
            return {"module:" + name} if any(f.module(name, v) is not None for v in f.versions) else None
        if t == "Context":
            c = CONTEXT.get(attr)
            return {c} if c else None
        if t.startswith("[]"):
            srna = t.split("@", 1)[1] if "@" in t else None
            if srna:
                return self._attr_type(srna, attr)
            return None
        if t.startswith("ops:"):
            return None
        out = set()
        for v in f.versions:
            p = f.prop(t, attr, v)
            if p is None:
                continue
            if p["type"] == "POINTER" and p.get("fixed"):
                out |= self.expand(p["fixed"])
            elif p["type"] == "COLLECTION" and p.get("fixed"):
                out.add("[]" + p["fixed"] + ("@" + p["srna"] if p.get("srna") else ""))
            else:
                return None
        return out or None

    def _item_type(self, base, key):
        if not base:
            return None
        out = set()
        for t in base:
            if not t.startswith("[]"):
                return None
            item = t[2:].split("@", 1)[0]
            name = literal(key)
            if item == "Node" and name is not None:
                ids = self.f.labels.get(name)
                if not ids:
                    return None  # a node the script named itself: could be anything
                out |= ids
            else:
                out |= self.expand(item)
        return frozenset(out) or None

    def _new_type(self, t, call):
        if not t.startswith("[]"):
            return None
        item = t[2:].split("@", 1)[0]
        f = self.f
        if item == "Node":
            idname = call_arg(call, 0, "type")
            return {idname} if idname and f.is_node(idname) else None
        if item == "Modifier":
            mt = call_arg(call, 1, "type")
            classes = f.type_map("modifier").get(mt) if mt else None
            return set(classes) if classes else set(self.expand("Modifier"))
        if item == "Light":
            lt = call_arg(call, 1, "type")
            classes = f.type_map("light").get(lt) if lt else None
            return set(classes) if classes else set(self.expand("Light"))
        if item == "Texture":
            tt = call_arg(call, 1, "type")
            classes = f.type_map("texture").get(tt) if tt else None
            return set(classes) if classes else set(self.expand("Texture"))
        if item == "Curve":
            ct = call_arg(call, 1, "type")
            classes = f.type_map("curve").get(ct) if ct else None
            return set(classes) if classes else set(self.expand("Curve"))
        if item == "NodeTree":
            tt = call_arg(call, 1, "type")
            return {tt} if tt and f.has_class(tt) else set(self.expand("NodeTree"))
        if item in ("Object", "Mesh", "Material", "Camera", "World", "Collection", "Image", "Action", "Scene"):
            return {item}
        return set(self.expand(item))


def type_scopes(typer, root, rounds=4):
    """Fill every scope's env; a few rounds so names used before their binding in the file settle."""
    scopes = []

    def walk(s):
        scopes.append(s)
        for c in s.children:
            walk(c)
    walk(root)
    for _ in range(rounds):
        for s in scopes:
            env = {}
            for name, binds in s.bindings.items():
                out, ok = set(), True
                for how, node in binds:
                    if how == "unknown":
                        ok = False
                    elif how == "type":
                        out |= node
                    elif how == "expr":
                        t = typer.of(node, s)
                        ok = ok and bool(t)
                        out |= t or set()
                    elif how == "iter":
                        t = typer.of(node, s)
                        item = typer._item_type(t, None) if t else None
                        ok = ok and bool(item)
                        out |= item or set()
                env[name] = frozenset(out) if ok and out else None
            s.env = env
    return scopes


# ---------- the checks ----------

def script_defined(tree):
    """Socket names the script makes itself, and RNA properties it registers (bpy.types.X.name = ...)."""
    sockets, props, groupish = set(), {}, False
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr in ("new_socket", "new") and isinstance(n.func.value, ast.Attribute) and \
                    n.func.value.attr in ("interface", "inputs", "outputs"):
                groupish = True
                for a in n.args + [k.value for k in n.keywords]:
                    if literal(a):
                        sockets.add(literal(a))
            if n.func.attr == "new_socket":
                groupish = True
        if isinstance(n, ast.Attribute) and n.attr in ("interface", "node_groups"):
            groupish = True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.endswith(GROUPISH) and \
                n.value.startswith(("ShaderNode", "GeometryNode", "CompositorNode", "Node")):
            groupish = True
        if isinstance(n, ast.Assign):
            for t in n.targets:
                # bpy.types.Scene.my_settings = bpy.props.PointerProperty(...)
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Attribute) and \
                        isinstance(t.value.value, ast.Attribute) and t.value.value.attr == "types":
                    props.setdefault(t.value.attr, set()).add(t.attr)
    return {"sockets": sockets, "props": props, "groupish": groupish}


# ---------- guarded accesses ----------

_EXITS = (ast.Return, ast.Raise, ast.Continue, ast.Break)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _falsy(node):
    """Whether node is a literal that is false: None, False, 0, "", (), [], {}."""
    if isinstance(node, ast.Constant):
        return not node.value
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return not node.elts
    return isinstance(node, ast.Dict) and not node.keys


def _probe(test):
    """(x, name) when test is hasattr(x, "name") or getattr(x, "name", <falsy>) (true only when x has name)."""
    if isinstance(test, ast.Call) and isinstance(test.func, ast.Name) and not test.keywords:
        a = test.args
        if test.func.id == "hasattr" and len(a) == 2 and literal(a[1]) is not None:
            return a[0], literal(a[1])
        if test.func.id == "getattr" and len(a) == 3 and literal(a[1]) is not None and _falsy(a[2]):
            return a[0], literal(a[1])
    return None


def _facts(test):
    """(if true, if false): what test being true or false says of which attributes exist, as
    [(receiver, name, exists, hard)]. hasattr and a getattr with a falsy default say it both ways (a getattr only
    one: a false value may be the attribute's own); not swaps them; and says its parts' when true, or theirs when
    false. hard is False here: guards() sets it for a fact that holds only because an assert or a raise stops the
    script where it doesn't (_hardened)."""
    p = _probe(test)
    if p is not None:
        fact = (p[0], p[1], True, False)
        no = (p[0], p[1], False, False)
        return [fact], ([no] if test.func.id == "hasattr" else [])
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        t, f = _facts(test.operand)
        return f, t
    if isinstance(test, ast.BoolOp):
        parts = [_facts(v) for v in test.values]
        if isinstance(test.op, ast.And):
            return [x for t, _ in parts for x in t], []
        return [], [x for _, f in parts for x in f]
    return [], []


def _ends(body):
    """Whether a block always leaves where it is: its last statement returns, raises, continues or breaks."""
    return bool(body) and isinstance(body[-1], _EXITS)


def _hardened(facts, body=None):
    """facts as holding only because the script stops where they don't (an assert, or a branch ending in a raise):
    hard, so Linter._guarded keeps a finding they would excuse on a name no version has."""
    if body is not None and not isinstance(body[-1], ast.Raise):
        return facts
    return [(x, name, exists, True) for x, name, exists, _ in facts]


def _root(node):
    while isinstance(node, (ast.Attribute, ast.Subscript, ast.Call)):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


def _bound(stmt):
    """The names a statement binds where it is (not inside nested scopes)."""
    out = set()
    targets = []
    if isinstance(stmt, ast.Assign):
        targets = stmt.targets
    elif isinstance(stmt, (ast.AugAssign, ast.AnnAssign)):
        targets = [stmt.target]
    elif isinstance(stmt, (ast.For, ast.AsyncFor)):
        targets = [stmt.target]
    elif isinstance(stmt, (ast.With, ast.AsyncWith)):
        targets = [i.optional_vars for i in stmt.items if i.optional_vars is not None]
    for t in targets:
        for n in ast.walk(t):
            if isinstance(n, ast.Name):
                out.add(n.id)
    return out


def guards(tree):
    """{id(attribute node): [(receiver, name, exists, hard), ...]}: what must hold for each attribute read in tree to
    run at all, from the hasattr and getattr tests around it (_facts), for the lint's guarded-access rule. A fact holds
    from its test to the end of what the test guards, and after an if whose branch leaves (`if not hasattr(x, "a"):
    return`) to the end of that block, until a statement there binds the receiver's name again; a nested function,
    lambda or class starts with none (it runs later). hard: the fact holds after an assert, or after a branch that
    raises where it doesn't (_hardened), and, since the second checks (Nov 6), in the other branch of an if whose one
    branch raises, and in an assert's later operands or those of a raising if's test that lead past the raise."""
    out = {}

    def key(fact):
        return (ast.dump(fact[0]), fact[1], fact[2], fact[3])

    def expr(n, known, hard=()):
        """hard: the BoolOp operators (ast.And, ast.Or) whose later operands run only where the script stops if
        the earlier ones say otherwise (an assert's and, an if that raises): their facts are hard there."""
        if n is None:
            return
        if isinstance(n, _SCOPES):
            scope(n)
            return
        if isinstance(n, ast.BoolOp):
            so_far = list(known)
            for v in n.values:
                expr(v, so_far)
                t, f = _facts(v)
                new = t if isinstance(n.op, ast.And) else f
                so_far = so_far + (_hardened(new) if isinstance(n.op, hard) else new)
            return
        if isinstance(n, ast.IfExp):
            t, f = _facts(n.test)
            expr(n.test, known)
            expr(n.body, known + t)
            expr(n.orelse, known + f)
            return
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            so_far = list(known)
            for g in n.generators:
                expr(g.iter, so_far)
                for c in g.ifs:
                    expr(c, so_far)
                    so_far = so_far + _facts(c)[0]
            for part in ((n.key, n.value) if isinstance(n, ast.DictComp) else (n.elt,)):
                expr(part, so_far)
            return
        if isinstance(n, ast.Attribute) and known:
            out[id(n)] = list({key(f): f for f in known}.values())
        for c in ast.iter_child_nodes(n):
            expr(c, known)

    def block(stmts, known):
        known = list(known)
        for s in stmts:
            stmt(s, known)
            bound = _bound(s)
            if bound:
                known = [f for f in known if _root(f[0]) not in bound]
            if isinstance(s, ast.If):
                t, f = _facts(s.test)
                if _ends(s.body) and not _ends(s.orelse):
                    known = known + _hardened(f, s.body)
                elif s.orelse and _ends(s.orelse) and not _ends(s.body):
                    known = known + _hardened(t, s.orelse)
            elif isinstance(s, ast.Assert):
                known = known + _hardened(_facts(s.test)[0])

    def stmt(s, known):
        if isinstance(s, _SCOPES):
            for d in getattr(s, "decorator_list", []):
                expr(d, known)
            if not isinstance(s, ast.ClassDef):
                for d in s.args.defaults + s.args.kw_defaults:
                    expr(d, known)
            scope(s)
        elif isinstance(s, (ast.If, ast.While)):
            t, f = _facts(s.test)
            # an if whose branch raises: the other branch, and the test's later operands that lead to it, run only
            # where the script doesn't stop (if not hasattr(a, "x"): raise ... else: a.x; if not hasattr(a, "x") or
            # not a.x: raise; the second checks, Nov 6)
            body_raises = isinstance(s, ast.If) and bool(s.body) and isinstance(s.body[-1], ast.Raise)
            else_raises = isinstance(s, ast.If) and bool(s.orelse) and isinstance(s.orelse[-1], ast.Raise)
            expr(s.test, known, (ast.Or,) * body_raises + (ast.And,) * else_raises)
            block(s.body, known + (_hardened(t) if else_raises else t))
            block(s.orelse, known + (_hardened(f) if body_raises else f))
        elif isinstance(s, ast.Assert):  # its and's later operands run only where it holds so far
            expr(s.test, known, (ast.And,))
            expr(s.msg, known)
        elif isinstance(s, (ast.For, ast.AsyncFor)):
            expr(s.target, known)
            expr(s.iter, known)
            block(s.body, known)
            block(s.orelse, known)
        elif isinstance(s, (ast.With, ast.AsyncWith)):
            for i in s.items:
                expr(i.context_expr, known)
                expr(i.optional_vars, known)
            block(s.body, known)
        elif isinstance(s, ast.Try) or (hasattr(ast, "TryStar") and isinstance(s, ast.TryStar)):
            block(s.body, known)
            for h in s.handlers:
                expr(h.type, known)
                block(h.body, known)
            block(s.orelse, known)
            block(s.finalbody, known)
        elif hasattr(ast, "Match") and isinstance(s, ast.Match):
            expr(s.subject, known)
            for c in s.cases:
                expr(c.guard, known)
                block(c.body, known)
        else:
            expr(s, known)

    def scope(n):
        if isinstance(n, ast.Lambda):
            expr(n.body, [])
        else:
            block(n.body, [])

    block(tree.body, [])
    return out


def near(name, options, n=3):
    m = difflib.get_close_matches(name, sorted(options), n=n, cutoff=0.6)
    return f" (has: {', '.join(repr(x) for x in m)})" if m else ""


class Linter:
    def __init__(self, facts, guards=False):
        """facts: a Facts. guards: the guarded-read rule (guards(), _guarded), data generation's only: datagen/run.py
        and BlenderGate's linter pass True; the eval, freeze's verify, rna_dump's lint and lint_source() keep the
        default, False, and lint as before Nov 5 (decided Nov 6)."""
        self.f = facts
        self.use_guards = guards
        self.dynamic = set().union(*(facts.subclasses(c) for c in DYNAMIC_STRUCTS))

    def lint(self, src, filename="script.py"):
        try:
            tree = ast.parse(src, filename)
        except SyntaxError as e:
            return [{"level": "error", "kind": "syntax", "line": e.lineno or 0, "name": "",
                     "message": f"doesn't parse: {e.msg}"}]
        self.defs = script_defined(tree)
        self.guards = guards(tree) if self.use_guards else {}
        self.typer = Typer(self.f, self.defs)
        root = Scope(tree, None)
        collect(root, tree.body)
        scopes = type_scopes(self.typer, root)
        self.out = []
        for s in scopes:
            for n in self._own_nodes(s):
                self._check(n, s)
        seen, uniq = set(), []
        for x in sorted(self.out, key=lambda x: (x["line"], x["kind"], x["name"])):
            k = (x["line"], x["kind"], x["name"], x["message"])
            if k not in seen:
                seen.add(k)
                uniq.append(x)
        return uniq

    def _own_nodes(self, scope):
        """The scope's nodes, without descending into nested scopes."""
        body = scope.node.body if isinstance(scope.node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
            else [scope.node.body]
        nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        stack = list(body)
        while stack:
            n = stack.pop()
            if isinstance(n, nested):
                # Its own scope checks its body; its decorators and defaults are evaluated here.
                if not isinstance(n, ast.Lambda):
                    stack.extend(n.decorator_list)
                if not isinstance(n, ast.ClassDef):
                    stack.extend(d for d in n.args.defaults + n.args.kw_defaults if d is not None)
                continue
            yield n
            stack.extend(ast.iter_child_nodes(n))

    def _add(self, level, kind, node, name, message):
        self.out.append({"level": level, "kind": kind, "line": getattr(node, "lineno", 0), "name": name, "message": message})

    def _versions_text(self, vs):
        return " or ".join(vs) if len(vs) > 1 else vs[0]

    def _check(self, n, scope):
        if isinstance(n, ast.Attribute):
            self._check_attr(n, scope)
        elif isinstance(n, ast.Subscript) and isinstance(n.value, ast.Attribute) and n.value.attr in SIDES:
            if literal(n.slice) is not None:
                self._check_socket(n, n.value, literal(n.slice), scope)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            fv = n.func.value
            if n.func.attr == "get" and isinstance(fv, ast.Attribute) and fv.attr in SIDES and n.args and literal(n.args[0]):
                self._check_socket(n, fv, literal(n.args[0]), scope)
            if n.func.attr == "new":
                self._check_new(n, scope)
            self._check_op_call(n, scope)
            self._check_call_keywords(n, scope)
        elif isinstance(n, ast.Assign) and literal(n.value) is not None:
            for t in n.targets:
                if isinstance(t, ast.Attribute):
                    self._check_enum(t, literal(n.value), scope)
        elif isinstance(n, ast.ImportFrom) and n.module:
            self._check_from_import(n)

    def _guarded(self, n, scope):
        """Whether attribute read n can't run unless its name is there (guards(); only in a Linter made with
        guards=True, the data generator's): a fact around it says its own
        receiver has it, or one says a name exists that no version's type of its receiver has, so its branch never
        runs. Not a fact on bpy.ops or one of its groups (_ops: hasattr and getattr are always true there), nor a hard
        one (an assert's, or a raise's when the name is missing) on a name no version has: the script stops there in
        every version, a certain crash the finding names. The else behind a hasattr whose name every version has is no
        branch no version reaches: its receiver may be None (scene.camera, a .get())."""
        facts = self.guards.get(id(n))
        if not facts:
            return False
        recv = ast.dump(n.value)
        for x, name, exists, hard in facts:
            if self._ops(x, scope):
                continue
            have = self._everywhere(x, name, scope)
            if hard and have is False:
                continue
            if exists and name == n.attr and ast.dump(x) == recv:
                return True
            if exists and have is False:
                return True
        return False

    def _ops(self, node, scope):
        """Whether node is bpy.ops or one of its groups (bpy.ops.wm): any name is there (an operator that doesn't exist
        is made on the call and fails then), so a hasattr or a getattr on it guards nothing."""
        base = self.typer.of(node, scope)
        if base and any(t.startswith("ops:") or t == "module:bpy.ops" for t in base):
            return True
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        return isinstance(node, ast.Name) and node.id == "bpy" and len(parts) <= 2 and parts[-1:] == ["ops"]

    def _everywhere(self, node, attr, scope):
        """True when every version's every type node can be has attr, False when none has it, None when it can't
        tell (an untyped, dynamic or partly known receiver, a name some versions have, a property the script
        registers, bpy.context, whose members are filled in at run time: the second checks, Nov 6, found
        hasattr(bpy.context, "active_object") read as a branch no version reaches)."""
        f = self.f
        base = self.typer.of(node, scope)
        if not base or not all(f.has_class(t) for t in base) or any(t in self.dynamic for t in base) or \
                "Context" in base:  # bpy.context's members are filled in at run time, no RNA property (_check_attr)
            return None
        for t in base:
            for c in [t] + [b for v in f.versions for b in f._bases(t, v)]:
                if attr in self.defs["props"].get(c, ()):
                    return None
        got = set()
        for v in f.versions:
            for t in base:
                s = f.attrs(t, v)
                if s is None:
                    return None
                got.add(attr in s)
        return got.pop() if len(got) == 1 else None

    def _check_attr(self, n, scope):
        attr = n.attr
        if attr.startswith("__"):
            return
        base = self.typer.of(n.value, scope)
        if not base:
            return
        if self.use_guards and self._guarded(n, scope):
            return
        f = self.f
        if all(t.startswith("module:") for t in base) and len(base) == 1:
            mod = next(iter(base))[len("module:"):]
            have = {v: f.module(mod, v) for v in f.versions}
            if mod == "bpy" or any(x is None for x in have.values()):
                return  # bpy's own names, or a module we didn't dump
            missing = [v for v, names in have.items() if attr not in names]
            self._report_missing(n, "module", f"{mod}.{attr}", missing,
                                 f"module '{mod}' has no '{attr}'", set().union(*have.values()), attr)
            return
        if len(base) == 1 and next(iter(base)).startswith("ops:"):
            sub = next(iter(base))[4:]
            have = {v: f.ops(sub, v) for v in f.versions}
            if all(x is None for x in have.values()):
                return  # no such group: reported on bpy.ops.<group> itself (module bpy.ops)
            missing = [v for v, names in have.items() if names is None or attr not in names]
            self._report_missing(n, "op", f"bpy.ops.{sub}.{attr}", missing, f"no operator bpy.ops.{sub}.{attr}",
                                 set().union(*(x for x in have.values() if x)), attr)
            return
        if all(t.startswith("[]") for t in base):
            self._check_collection_attr(n, base, attr)
            return
        if any(t.startswith(("module:", "ops:", "[]")) or t == "Context" for t in base):
            return
        known = [t for t in base if f.has_class(t)]
        if not known or len(known) < len(base):
            return
        if any(t in self.dynamic for t in known):
            return
        for t in known:
            for c in [t] + [b for v in f.versions for b in f._bases(t, v)]:
                if attr in self.defs["props"].get(c, ()):
                    return
        missing, absent = [], []
        options = set()
        for v in f.versions:
            sets = [f.attrs(t, v) for t in known]
            sets = [s for s in sets if s is not None]
            if not sets:
                absent.append(v)  # no such class in this version: a class-level problem, not this attribute's
                continue
            if not any(attr in s for s in sets):
                missing.append(v)
            for s in sets:
                options |= s
        label = self._label(known)
        what = f"{label} has no attribute '{attr}'"
        if missing and absent and len(missing) + len(absent) == len(f.versions):
            # the class is in some versions only, and none of them has the attribute: say so, not "only in"
            self._add("warn", "attr", n, attr, f"{what} in Blender {self._versions_text(missing)} "
                      f"(Blender {self._versions_text(absent)} has no {label}){near(attr, options)}")
            return
        self._report_missing(n, "attr", attr, missing, what, options, attr)

    def _check_collection_attr(self, n, base, attr):
        f = self.f
        missing, options = [], set()
        for v in f.versions:
            sets = [f.collection_attrs(t, v) for t in base]
            if any(x is None for x in sets):
                return  # a collection we have no facts for in this version
            if not any(attr in x for x in sets):
                missing.append(v)
            for x in sets:
                options |= x
        items = sorted({t[2:].split("@", 1)[0] for t in base})
        srnas = sorted({t.split("@", 1)[1] for t in base if "@" in t})
        label = f"a collection of {'/'.join(items)}" + (f" ({'/'.join(srnas)})" if srnas else "")
        self._report_missing(n, "attr", attr, missing, f"{label} has no attribute '{attr}'", options, attr)

    def _check_call_keywords(self, call, scope):
        """obj.method(keyword=...) on a typed receiver: a keyword the method doesn't take is a TypeError."""
        if not call.keywords or not isinstance(call.func, ast.Attribute):
            return
        base = self.typer.of(call.func.value, scope)
        if not base:
            return
        f = self.f
        meth = call.func.attr
        owners = []
        for t in base:
            if t.startswith("[]"):
                if "@" not in t:
                    return
                owners.append(t.split("@", 1)[1])
            elif t.startswith(("module:", "ops:")) or t == "Context" or not f.has_class(t):
                return
            else:
                owners.append(t)
        per_version = {}
        for v in f.versions:
            got = [f.fparams(o, meth, v) for o in owners if f.has_class(o, v)]
            if not got:
                continue
            if any(g is None or "**" in g for g in got):
                return  # a method we have no parameters for, or one that takes any keyword
            per_version[v] = set().union(*got)
        if not per_version:
            return
        for k in call.keywords:
            if k.arg is None:
                continue
            missing = [v for v, names in per_version.items() if k.arg not in names]
            label = "/".join(sorted(owners)) if len(owners) <= 3 else self._label(owners)
            self._report_missing(call, "arg", f"{meth}({k.arg}=)", missing, f"{label}.{meth}() has no keyword '{k.arg}'",
                                 set().union(*per_version.values()), k.arg)

    def _label(self, classes):
        """"Mesh", "PointLight/SpotLight", or "ID (any of its 64 types)" for a whole family."""
        classes = sorted(classes)
        if len(classes) <= 3:
            return "/".join(classes)
        f = self.f
        for c in classes:  # the family's root: every other class has it among its bases
            if all(c == o or any(c in f._bases(o, v) for v in f.versions) for o in classes):
                return f"{c} (any of its {len(classes)} types)"
        return f"{classes[0]} (or {len(classes) - 1} related classes)"

    def _report_missing(self, node, kind, name, missing, what, options, key):
        f = self.f
        if not missing:
            return
        if len(missing) == len(f.versions):
            self._add("error", kind, node, name, f"{what} in Blender {self._versions_text(missing)}{near(key, options)}")
        else:
            have = [v for v in f.versions if v not in missing]
            self._add("warn", kind, node, name, f"{what} in Blender {self._versions_text(missing)} "
                      f"(only in {self._versions_text(have)})")

    def _check_socket(self, node, side_attr, key, scope):
        side = side_attr.attr
        f = self.f
        base = self.typer.of(side_attr.value, scope)
        nodes = [t for t in (base or ()) if f.is_node(t)]
        if base and len(nodes) == len(base):
            if any(t.endswith(GROUPISH) for t in nodes):
                return
            infos = {v: [f.node(t, v) for t in nodes] for v in f.versions}
            if any(i and i.get("dynamic") for v in infos for i in infos[v]):
                return
            missing, never, present, options = [], [], [], set()
            for v, lst in infos.items():
                lst = [i for i in lst if i]
                if not lst:
                    continue
                present.append(v)
                # Only what a script can reach (usable): inputs['Weight'] on a Principled BSDF raises KeyError though
                # the node has that socket, and near() never offers it.
                names = {x for i in lst for sock in i[side] if usable(i, side, sock) for x in sock[:2]}
                options |= {sock[0] for i in lst for sock in i[side] if usable(i, side, sock)}
                if key not in names:
                    missing.append(v)
                    if any(key in sock[:2] for i in lst for sock in i[side]):
                        never.append(v)
            label = "/".join(sorted(nodes)) if len(nodes) <= 3 else f"{len(nodes)} node types"
            if never and missing == present:  # the node has it, but no version lets a script reach it
                self._add("error", "socket", node, key, f"{side[:-1]} '{key}' on {label} is never available to a "
                          f"script ({side}['{key}'] raises KeyError){near(key, options)}")
                return
            self._report_missing(node, "socket", key, missing, f"no {side[:-1]} '{key}' on {label}", options, key)
            return
        if base is None:
            # Unknown node: only a name no node has, in a script that builds no node groups of its own.
            if self.defs["groupish"] or key in self.defs["sockets"]:
                return
            if key not in self.f.sockets_all[side]:
                what = "a script can use " if key in self.f.sockets_seen[side] else ""
                self._add("error", "socket", node, key, f"no node type has an {side[:-1]} '{key}' {what}in Blender "
                          f"{self._versions_text(f.versions)}{near(key, f.sockets_all[side])}")

    def _check_new(self, call, scope):
        f = self.f
        base = self.typer.of(call.func.value, scope)
        recv = call.func.value
        is_nodes = (base and any(t.startswith("[]Node@") or t == "[]Node" for t in base)) or \
            (isinstance(recv, ast.Attribute) and recv.attr == "nodes")
        if is_nodes:
            idname = call_arg(call, 0, "type")
            if idname:
                have = f.is_node(idname)
                missing = [v for v in f.versions if v not in have]
                self._report_missing(call, "node_type", idname, missing, f"no node type '{idname}'",
                                     f.node_ids, idname)
            return
        if not base:
            return
        items = {t[2:].split("@", 1)[0] for t in base if t.startswith("[]")}
        for item, kind, pos in (("Modifier", "modifier", 1), ("Light", "light", 1)):
            if item in items:
                val = call_arg(call, pos, "type")
                if val:
                    have = {v for v in f.versions if val in (f.dumps[v].get("types", {}).get(kind) or {})}
                    missing = [v for v in f.versions if v not in have]
                    self._report_missing(call, "enum", val, missing, f"no {kind} type '{val}'",
                                         set(f.type_map(kind)), val)

    def _check_op_call(self, call, scope):
        """bpy.ops.group.op(keyword=...): a keyword the operator doesn't have is a TypeError."""
        base = self.typer.of(call.func.value, scope)
        if not base or len(base) != 1 or not next(iter(base)).startswith("ops:"):
            return
        op = next(iter(base))[4:] + "." + call.func.attr
        f = self.f
        have = {v: f.op_props(op, v) for v in f.versions}
        if any(x is None for x in have.values()):
            return  # an operator we don't know (flagged as such) or a dump without op_props
        for k in call.keywords:
            if k.arg is None:
                continue  # **kwargs
            missing = [v for v, names in have.items() if k.arg not in names]
            self._report_missing(call, "op_arg", f"bpy.ops.{op}({k.arg}=)", missing,
                                 f"bpy.ops.{op} has no keyword '{k.arg}'", set().union(*have.values()), k.arg)

    def _check_enum(self, target, value, scope):
        base = self.typer.of(target.value, scope)
        if not base:
            return
        f = self.f
        known = [t for t in base if f.has_class(t)]
        if len(known) != len(base):
            return
        missing, options, any_enum = [], set(), False
        for v in f.versions:
            sets = [f.enum_items(t, target.attr, v) for t in known]
            if any(f.prop(t, target.attr, v) is not None and s is None for t, s in zip(known, sets)):
                return  # some class has it as a non-enum or an enum we can't list
            sets = [s for s in sets if s is not None]
            if not sets:
                continue
            any_enum = True
            if not any(value in s for s in sets):
                missing.append(v)
            for s in sets:
                options |= s
        if any_enum:
            self._report_missing(target, "enum", value, missing, f"'{value}' isn't a value of "
                                 f"{'/'.join(sorted(known)) if len(known) <= 3 else sorted(known)[0]}.{target.attr}", options, value)

    def _check_from_import(self, n):
        f = self.f
        if n.module == "bpy.types":
            for al in n.names:
                missing = [v for v in f.versions if al.name not in f.dumps[v]["classes"]
                           and al.name not in (f.module("bpy.types", v) or ())]
                self._report_missing(n, "class", al.name, missing, f"no class bpy.types.{al.name}",
                                     set(f.dumps[f.versions[0]]["classes"]), al.name)
            return
        have = {v: f.module(n.module, v) for v in f.versions}
        if any(x is None for x in have.values()) or n.module == "bpy":
            return
        for al in n.names:
            if al.name == "*":
                continue
            missing = [v for v, names in have.items() if al.name not in names]
            self._report_missing(n, "module", f"{n.module}.{al.name}", missing,
                                 f"can't import '{al.name}' from {n.module}", set().union(*have.values()), al.name)


def lint_source(src, facts=None, filename="script.py"):
    return Linter(facts or Facts.load()).lint(src, filename)


def format_findings(findings, filename=""):
    pre = f"{filename}:" if filename else "line "
    return "\n".join(f"{pre}{x['line']}: {x['level']}: {x['message']}" for x in findings)
