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
  bpy.ops operators, bpy.types classes, from-imports.
- warn: it exists in only one of the versions.
- syntax: the script doesn't parse.
Each finding says what does exist nearby (difflib), for the teacher's repair turn.
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
DYNAMIC_STRUCTS = ("NodesModifierProperties", "SequencerCompositorModifierProperties")
SIDES = ("inputs", "outputs")


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
        self.sockets_all = {s: set() for s in SIDES}
        for d in dumps.values():
            for tree in d["nodes"].values():
                for idname, n in tree.items():
                    self.node_ids.add(idname)
                    self.labels.setdefault(n["label"], set()).add(idname)
                    for s in SIDES:
                        self.sockets_all[s].update(x for sock in n[s] for x in sock[:2])
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
        for tree in self.dumps[v]["nodes"].values():
            if idname in tree:
                return tree[idname]
        return None

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


def near(name, options, n=3):
    m = difflib.get_close_matches(name, sorted(options), n=n, cutoff=0.6)
    return f" (has: {', '.join(repr(x) for x in m)})" if m else ""


class Linter:
    def __init__(self, facts):
        self.f = facts
        self.dynamic = set().union(*(facts.subclasses(c) for c in DYNAMIC_STRUCTS))

    def lint(self, src, filename="script.py"):
        try:
            tree = ast.parse(src, filename)
        except SyntaxError as e:
            return [{"level": "error", "kind": "syntax", "line": e.lineno or 0, "name": "",
                     "message": f"doesn't parse: {e.msg}"}]
        self.defs = script_defined(tree)
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

    def _check_attr(self, n, scope):
        attr = n.attr
        if attr.startswith("__"):
            return
        base = self.typer.of(n.value, scope)
        if not base:
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
            missing, options = [], set()
            for v, lst in infos.items():
                lst = [i for i in lst if i]
                if not lst:
                    continue
                names = {x for i in lst for sock in i[side] for x in sock[:2]}
                options |= {sock[0] for i in lst for sock in i[side]}
                if key not in names:
                    missing.append(v)
            label = "/".join(sorted(nodes)) if len(nodes) <= 3 else f"{len(nodes)} node types"
            self._report_missing(node, "socket", key, missing, f"no {side[:-1]} '{key}' on {label}", options, key)
            return
        if base is None:
            # Unknown node: only a name no node has, in a script that builds no node groups of its own.
            if self.defs["groupish"] or key in self.defs["sockets"]:
                return
            if key not in self.f.sockets_all[side]:
                self._add("error", "socket", node, key, f"no node type has an {side[:-1]} '{key}' in Blender "
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
