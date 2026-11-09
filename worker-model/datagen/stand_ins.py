"""The stand-in marker and silent defaults, read from a Blender piece's code (no run): two gate reasons with tells
(blender_gate.piece_check, DESIGN.md "After the fourth smoke").

    found = check(code, deps, earlier)  # deps: ["s1"]; earlier: {"s1": text} of the earlier steps' kept pieces
    lines = tell(found)                 # teacher-only lines, at most FAILURE_CHARS each

Chimera's Blender rule says what the marker is for: a piece finds what its dependencies list under provides in
ctx["objects"] and ctx["values"], and "If one is missing because your piece runs alone, make a simple stand-in and
print("chimera: stand-in", key)". So the line names a dependency's key, and the person reading Chimera's result
learns that the piece ran with a stand-in for it. Two habits break that, and nothing else in the gate sees either,
because neither shows in a run that passes:

- marker_misused: a print of the marker for something that is no dependency's key the piece reads. The fourth smoke's
  n-blender-0000-01 r1 s1 and r2 s1, values steps with no dependency, print "chimera: stand-in render_device
  (fallback to CPU)" when the GPU can't be set; others mark a font, an SVG or an HDRI file, an output folder, an
  input a node lacks. The joined run catches such a line only when it prints (stand_in), and a GPU fallback doesn't
  print in the sandbox. Since the fifth smoke (Nov 6) a marker for an input file the piece can't find (for_file: a
  key with a file's extension that names a file the piece reads in, or the print where a test of a path it reads in
  or a load failed) is told to be a plain line of the piece's own that names the file (MARKER_FILE_TELL); the reason
  is the same. A marker counts when its key is a
  literal (the first word after the marker, past filler words such as for, missing, created and object, or the
  print's second argument): a key a variable gives
  ("chimera: stand-in", key; f"chimera: stand-in for missing object '{key}'"; "chimera: stand-in %s" % key) is the
  reader's own loop and isn't judged. On a step with no dependency a marker with no key at all is misused too, its
  tell quoting its own words (the second checks, Nov 6: the first smoke's "chimera: stand-in – GPU unavailable,
  falling back to CPU", a dash before the words, read as no key). It is no fault when the step depends on something
  and the key is a name the piece looks up (lookups: a key it reads from ctx, a name it gets from bpy.data or any
  other dict, a string value of its SETTINGS, a string it passes to a helper of its own or loops over) or one its
  dependencies hand on (dep_names), with or without chimera_ before either.
- silent_default: a read of a dependency's ctx["values"] key with a default and no marker: ctx["values"].get(k, d)
  with a d that isn't None, ctx["values"].get(k) or d, or d if k isn't in ctx["values"] (ctx by any name its build_
  function gives it, a name the same function, or one around it, binds to ctx["values"], or a helper's parameter
  every call fills with it). Alone, such a piece builds with its own number and says nothing; joined after a
  dependency that failed to hand the key on, the same. n-blender-0000-01 r2 s4 c0, the only Blender example in the
  fourth smoke's valid, reads every value through def
  get(key): return ctx["values"].get(key, SETTINGS_s4[key]). A key the piece writes into ctx["values"] itself is its
  own (get-or-create), and so is one no dependency hands on when every dependency is there; with one missing, any key
  the piece doesn't write may be the missing one's. A key a variable gives (a helper's parameter) stands for the literal
  keys the piece passes to that helper, a loop's over a literal list for that list's strings; one that can't be read so
  ("bench_" + k in a loop) is taken for a dependency's. The read is covered by a marker with its key (a stand-in
  helper's: a function of the piece that prints the marker with its parameter as the key, also through repr(), str()
  or a .format keyword, covers the keys passed to it as the same name), by a marker in the same function when either
  key is a variable, or by the values' own marker loop (a variable's key under a ctx["values"] test: if key not in
  vals) in a function around the read or one that calls it, which also covers the keys it loops over wherever they are
  read (the independent checks, Nov 6: a _sN_ helper or a lambda read with the marker loop in build_sN; the second
  checks, the same day: an object's marker loop there covers no such read). A marker with no key covers nothing.

dep_names: what the earlier kept pieces hand on: their provides lines' names (bracketed ctx keys, chimera_ names and
the code-like words the uses reader takes, contract.join.uses_names), the ctx["objects"] and ctx["values"] keys
their code writes, and a dependency's SETTINGS keys when it writes ctx["values"] in a way whose keys can't be read
(a loop over its SETTINGS, update()). The tells are ours (teacher-only); TELL_FORMS is their fixed wording, for
hints.echoed_note through blender_gate.TELL_FORMS."""
from __future__ import annotations

import ast
import json
import os
import re

from contract import validate as V
from contract.goport import code_blocks, python_lang
from contract.join import uses_names
from datagen.hints import FAILURE_CHARS
from runner.score import provided_names

MARKER = "chimera: stand-in"
CHANNELS = ("objects", "values")
CTX_OWN = ("objects", "values", "scene", "collection", "ctx")  # the contract's own words, no step's name
_DASHES = dict.fromkeys(map(ord, "‐‑‒−"), "-")  # gpt-oss writes the marker's hyphen as U+2011
_LEAD = re.compile(r"[\s:]+")  # after the marker, before its key
_TOKEN = re.compile(r"[\"'`]?([\w.-]+)")  # a word, with an opening quote
_GAP = re.compile(r"[\s/,]+")  # between filler words ("key/name")
# Words gpt-oss puts between the marker and a key a variable gives (f"chimera: stand-in for missing object '{key}'",
# "chimera: stand-in for", key): not a key (the independent checks, Nov 6: 11 of the first smoke's 258 Blender tries
# were read as marking "missing", "created", "object" or "setting")
FILLER = frozenset({"for", "missing", "created", "creating", "object", "objects", "key", "keys", "name", "names",
                    "setting", "variable", "value"})
_FIRST = re.compile(r"\s*[\"'`]?([\w.-]+)")  # a second argument's first word
QUOTES = 3  # keys a tell quotes
KEYLESS_CHARS = 40  # of a keyless marker's own words in its tell (_keyless)
# The tell lines (ours, teacher-only). {quotes} are the piece's own keys, {where} its helper's name, {marker}
# Chimera's own words for the line (MARKER_CALL, its Blender rule's).
MARKER_CALL = 'print("chimera: stand-in", key)'
MARKER_TELL = ('{quotes}: the piece prints the stand-in line for no key a dependency hands on, but that line is for '
               'the ctx["objects"] or ctx["values"] key of a missing dependency; say other fallbacks another way or '
               'not at all')
SILENT_TELL = ('{quotes} from ctx["values"]: read with a default and no stand-in line, though a dependency hands it '
               'on; where the piece makes its own value for a missing key, add {marker}')
SILENT_HELPER_TELL = ('{where} reads ctx["values"] with a default and no stand-in line: where the piece makes its own '
                      'value for a missing key a dependency hands on, add {marker}')
# Since the fifth smoke (Nov 6): a misused marker for an input file the piece can't find (for_file) is told what to
# print instead. In smoke5 the marker stood for an SVG, an HDRI or a font on 9 of the 12 marker_misused tries and 11
# of the 23 gated tries with a misused marker (blender-0008-00 s1 and s3, blender-0002-02 s1), and 5 of the 10 told
# retries printed it again after MARKER_TELL's "say other fallbacks another way or not at all". With a plain print in
# its place 5 of smoke5's 14 such tries pass the gate in both Blenders (6 of the 38 of smoke2-5); the others fail on
# what else they do.
MARKER_FILE_TELL = ('{quotes}: the stand-in line is for a missing dependency\'s ctx key, not a file the piece can\'t '
                    'find; where a file is missing, say so in a plain print instead, naming the file and what the '
                    'piece builds in its place')
# Their fixed wording, for echoed_note: the runs of 5 words or more between the slots (Chimera's MARKER_CALL is a
# slot, so a reply that writes the call isn't refused for it)
TELL_FORMS = tuple(p.strip(" :,.") for t in (MARKER_TELL, SILENT_TELL, SILENT_HELPER_TELL, MARKER_FILE_TELL)
                   for p in re.split(r"\{\w+\}", t) if len(re.findall(r"\w+", p)) >= 5)
# What reads as an input file (for_file): a key with a file's extension, and the calls that test a path is there
FILE_EXTS = frozenset((".svg", ".hdr", ".hdri", ".exr", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".tga", ".bmp",
                       ".webp", ".ttf", ".otf", ".woff", ".woff2", ".pfb", ".obj", ".fbx", ".glb", ".gltf", ".stl",
                       ".ply", ".abc", ".usd", ".usda", ".usdc", ".usdz", ".dae", ".x3d", ".wav", ".mp3", ".ogg",
                       ".flac", ".mp4", ".mov", ".avi", ".mkv", ".blend", ".vdb", ".csv", ".json", ".txt"))
FILE_TESTS = frozenset(("exists", "isfile", "lexists", "is_file", "access"))


def piece_code(content):
    """Every closed python block of a reply, in order (task.piece_code's reading; task imports blender_gate, which
    imports this module, so it isn't imported here)."""
    return "\n".join(b.body for b in code_blocks(content or "") if b.closed and python_lang(b.lang))


def _str(n):
    return n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else None


def _parse(code):
    try:
        return ast.parse(code or "")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


def _ctx_names(tree):
    """ctx, and the first parameter of each top-level build_sN function (blender_gate._ctx_names)."""
    names = {"ctx"}
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and re.fullmatch(r"build_s\d+", n.name):
            params = n.args.posonlyargs + n.args.args
            if params:
                names.add(params[0].arg)
    return names


class _Reader:
    """One parse of a piece of step sid: ctx names, the names bound to ctx["objects"] or ctx["values"] (in the function
    that binds them), its own SETTINGS_<sid> and the names bound to it (every SETTINGS_ dict when sid is None), every
    node's enclosing function, the piece's own helpers and who calls them."""

    def __init__(self, tree, sid=None):
        self.tree, self.sid = tree, sid
        self.ctx = _ctx_names(tree)
        self.func = {}  # id(node) -> its innermost enclosing FunctionDef or Lambda (None at the top)
        self.parent = {}  # id(node) -> the node it is a child of
        self._enclose(tree, None)
        # (id of the binding function or None, name) -> channel, for names every plain binding of which in that
        # function is ctx[channel] or get/setdefault (a name is the function's own where it binds it: Python's scope)
        self.alias = {}
        self.local = {}  # id(function) -> the names it binds (its parameters and plain assignments)
        bound = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign):
                ch = self._channel_of(n.value)
                fn = self.func.get(id(n))
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        bound.setdefault((id(fn) if fn else None, t.id), set()).add(ch)
                        self.local.setdefault(id(fn) if fn else None, set()).add(t.id)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                a = n.args
                self.local.setdefault(id(n), set()).update(
                    x.arg for x in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg] if x is not None)
        for key, chs in bound.items():
            if len(chs) == 1 and None not in chs and key[1] not in self.ctx:
                self.alias[key] = next(iter(chs))
        self.callers = {}  # function name -> the functions (nodes, None at the top) that call it by name
        calls = {}  # function name -> its calls by name
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                self.callers.setdefault(n.func.id, []).append(self.func.get(id(n)))
                calls.setdefault(n.func.id, []).append(n)
        # (id of a function, parameter) -> channel, for a parameter its function never binds again and every call of
        # it by name fills with the same channel, ctx["values"] or a name bound to it (the second checks, Nov 6:
        # _s3_powers(vals) reading vals.get("key_light_power", 800.0)); twice, for a helper handing it on to another
        self.param = {}
        defs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for _ in range(2):
            for fn in defs:
                got = calls.get(fn.name) or []
                params = [a.arg for a in fn.args.posonlyargs + fn.args.args]
                for k, p in enumerate(params):
                    if (id(fn), p) in bound or p in self.ctx or not got:
                        continue
                    chs = {self._passed(c, k, p) for c in got}
                    if len(chs) == 1 and None not in chs:
                        self.param[(id(fn), p)] = next(iter(chs))
        self.settings = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and
                         (n.id == "SETTINGS_" + sid if sid else n.id.startswith("SETTINGS_"))}
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Name) and n.value.id in self.settings:
                self.settings.update(t.id for t in n.targets if isinstance(t, ast.Name))
        self.helpers = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def _enclose(self, node, fn):
        """Every node's innermost enclosing function, without recursion (a long chain of operators nests deep)."""
        stack = [(node, fn)]
        while stack:
            node, fn = stack.pop()
            for child in ast.iter_child_nodes(node):
                self.func[id(child)] = fn
                self.parent[id(child)] = node
                stack.append((child, child if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
                              else fn))

    def _passed(self, call, k, param):
        """The channel a call passes at parameter param (position k, or by its name), None for anything else (a
        starred argument, none at all)."""
        if any(isinstance(a, ast.Starred) for a in call.args[:k + 1]) or any(w.arg is None for w in call.keywords):
            return None
        v = call.args[k] if k < len(call.args) else next((w.value for w in call.keywords if w.arg == param), None)
        return self.channel(v) if v is not None else None

    def _channel_of(self, n):
        """The channel a value is: ctx["objects"] / ctx["values"], ctx.get or ctx.setdefault of one, "x or {}" of
        one; else None."""
        if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or) and n.values:
            n = n.values[0]
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id in self.ctx:
            k = _str(n.slice)
            return k if k in CHANNELS else None
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("get", "setdefault") and \
                isinstance(n.func.value, ast.Name) and n.func.value.id in self.ctx and n.args:
            k = _str(n.args[0])
            return k if k in CHANNELS else None
        return None

    def channel(self, n):
        """The channel an expression stands for: ctx[...] or one of its forms (_channel_of), or a name bound to
        one where it is read (the innermost function around it that binds the name, as a parameter or by an
        assignment, or the module; a parameter only when every call fills it with that channel); None otherwise."""
        if isinstance(n, ast.Name):
            for fn in self.chain(n) + [None]:
                k = id(fn) if fn else None
                if n.id in self.local.get(k, ()):
                    return self.alias.get((k, n.id)) or self.param.get((k, n.id))
            return None
        return self._channel_of(n)

    def chain(self, node):
        """The functions around node, innermost first (lambdas included)."""
        out = []
        fn = self.func.get(id(node))
        while fn is not None:
            out.append(fn)
            fn = self.func.get(id(fn))
        return out

    def around(self, node):
        """The functions whose marker covers a read at node: those around it, and those that call one of them by
        name (a top-level _sN_ helper build_sN calls), with the functions around those."""
        out = self.chain(node)
        for fn in list(out):
            for caller in self.callers.get(getattr(fn, "name", None), ()):
                if caller is not None:
                    out += [caller] + self.chain(caller)
        return out

    def is_settings(self, n):
        return isinstance(n, ast.Name) and n.id in self.settings

    def where(self, node):
        fn = self.func.get(id(node))
        return fn.name if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) else None


def _marker_text(first):
    """(the literal text a print's first argument starts with, whether a value follows it, the node of the first
    value) for a str constant, an f-string, "..." % x, "..." + x and "...".format(x); None for anything else."""
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value, False, None
    if isinstance(first, ast.JoinedStr):
        text = ""
        for part in first.values:
            if not (isinstance(part, ast.Constant) and isinstance(part.value, str)):
                return text, True, getattr(part, "value", None)
            text += part.value
        return text, False, None
    if isinstance(first, ast.BinOp) and isinstance(first.op, (ast.Mod, ast.Add)) and _str(first.left) is not None:
        text = _str(first.left)
        if isinstance(first.op, ast.Mod):
            text = re.split(r"%(?!%)", text, maxsplit=1)[0]
            arg = first.right.elts[0] if isinstance(first.right, ast.Tuple) and first.right.elts else first.right
        else:
            arg = first.right
        return text, True, arg
    if isinstance(first, ast.Call) and isinstance(first.func, ast.Attribute) and first.func.attr == "format" and \
            _str(first.func.value) is not None:
        text = _str(first.func.value)
        field = re.search(r"\{(?!\{)([^{}!:]*)", text)
        field = field.group(1).strip() if field else ""
        if field.isidentifier():  # "chimera: stand-in {key}".format(key=key): the keyword it names
            value = next((w.value for w in first.keywords if w.arg == field), None)
        else:
            k = int(field) if field.isdigit() else 0
            value = first.args[k] if k < len(first.args) else None
        return re.split(r"\{(?!\{)", text, maxsplit=1)[0], True, value
    return None


def _unwrap(n):
    """A key's own node, out of repr() or str() (print("chimera: stand-in", repr(key)))."""
    while isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("repr", "str") and \
            len(n.args) == 1 and not n.keywords:
        n = n.args[0]
    return n


def _marker_key(rest, dynamic, second):
    """A marker's literal key from the text after the marker (rest): its first word past the FILLER words; when
    nothing but filler and quotes is left, second's first word (the print's second argument, a literal string, or
    None); None when a variable gives it (an f-string's value right after the filler, a word that runs into a
    value)."""
    lead = _LEAD.match(rest)
    pos = lead.end() if lead else 0
    while lead:
        t = _TOKEN.match(rest, pos)
        if not t:
            break
        word = t.group(1).strip(".-")
        if word.lower() not in FILLER:
            return word if not dynamic or t.end() < len(rest) else None  # a word that runs into a value isn't whole
        gap = _GAP.match(rest, t.end())
        pos = gap.end() if gap else t.end()
        if not gap:
            break
    if rest[pos:].strip(" :'\"`") or dynamic or second is None:
        return None
    m = _FIRST.match(second)
    return m.group(1).strip(".-") if m else None


def markers(r):
    """[(line, key or None, function)] for every print of the marker: key is a literal (the first word after the
    marker in the first argument, past filler words, else the second argument's first word when it is a literal
    string), None when a variable, an f-string's value or a %, + or .format value gives it."""
    return [(n.lineno, key, r.where(n)) for n, key, _ in _marker_prints(r)]


def _marker_prints(r):
    """[(print node, key or None, the node a variable key is in or None)] for markers()."""
    out = []
    for n in ast.walk(r.tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print" and n.args):
            continue
        got = _marker_text(n.args[0])
        if got is None:
            continue
        text, dynamic, value = got
        text = text.translate(_DASHES)
        if not text.lstrip().lower().startswith(MARKER):
            continue
        rest = text.lstrip()[len(MARKER):]
        second = _str(n.args[1]) if len(n.args) > 1 and not dynamic else None
        key = _marker_key(rest, dynamic, second) or None
        if key is None and value is None and len(n.args) > 1 and not dynamic:
            value = n.args[1]
        out.append((n, key, value))
    return out


def _keyless(n):
    """What a marker print with no key says after the marker, for its tell's quote (the second checks, Nov 6: the
    first smoke's "chimera: stand-in – GPU unavailable, falling back to CPU" on a step with no dependency read as no
    key and was never judged); its whole text when nothing follows."""
    got = _marker_text(n.args[0])
    text = (got[0] if got else "").translate(_DASHES).strip()
    rest = text[len(MARKER):].strip(" :-–—()[]'\"`") if text.lower().startswith(MARKER) else ""
    return (rest or text or MARKER)[:KEYLESS_CHARS]


def keyless(code):
    """What each marker print with no key at all says after the marker (_keyless), in the piece's order: "chimera:
    stand-in – Acme_Logo not found" or a bare marker, neither a literal key nor a variable's; [] for code that
    doesn't parse. check judges such a marker only on a step with no dependency (marker_misused); on a step with one
    it is neither judged nor any read's cover, as decided after the second checks (Nov 6: 13 first-smoke tries, none
    in smoke2-4), and report.after_audit counts it there (keyless_markers) so the fifth smoke shows whether it
    needs a reading."""
    tree = _parse(code)
    if tree is None:
        return []
    bare = [n for n, k, v in _marker_prints(_Reader(tree, None))
            if k is None and (v is None or isinstance(_unwrap(v), ast.Constant))]
    return [_keyless(n) for n in sorted(bare, key=lambda n: (n.lineno, n.col_offset))]


def _loads(nodes):
    """Whether statements load a file (blender_gate._loader: bpy.data's load()s, an import, open, append or link
    operator) or call open(), when they run: a function or class they define is not looked into."""
    from datagen import blender_gate  # it imports this module
    return any(isinstance(x, ast.Call) and (blender_gate._loader(x) or isinstance(x.func, ast.Name) and
                                            x.func.id == "open") for x in _walk_here(nodes))


_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _before(r, stmt):
    """The statements before stmt in the block that holds it (its parent's body, orelse, finalbody or handler's)."""
    up = r.parent.get(id(stmt))
    for field in ("body", "orelse", "finalbody"):
        block = getattr(up, field, None)
        if isinstance(block, list) and any(s is stmt for s in block):
            return block[:next(k for k, s in enumerate(block) if s is stmt)]
    return []


def _walk_here(nodes):
    """The nodes of statements as they run: a function or class they define is not looked into."""
    stack = [s for s in nodes if not isinstance(s, _DEFS)]
    while stack:
        x = stack.pop()
        yield x
        stack.extend(c for c in ast.iter_child_nodes(x) if not isinstance(c, _DEFS))


# What a load adds, which a test of what it gave reads (_after_load): the objects of a scene, a collection or bpy.data,
# the selection or the active object, bpy.data's datablocks (bpy.data.curves), or the load call's own result
LOAD_GIVES = frozenset(("objects", "all_objects", "selected_objects", "selected_editable_objects", "active_object",
                        "object"))


def _gives(n, names):
    """Whether expression n reads what a load gives (LOAD_GIVES, bpy.data, a load's result) or a name holding it."""
    return any(isinstance(x, ast.Name) and x.id in names or
               isinstance(x, ast.Attribute) and (x.attr in LOAD_GIVES or x.attr == "data" and
                                                 isinstance(x.value, ast.Name) and x.value.id == "bpy") or
               isinstance(x, ast.Call) and _reads_file(x) for x in ast.walk(n))


def _after_load(r, stmt):
    """Whether if-statement stmt tests what a load before it in its block gave: an earlier statement of the block
    loads a file (_loads) and the if's test reads what it added (_gives), or a name bound at or after the first such
    statement to it (if not new_objs: after an SVG import, with new_objs = set(scene.objects) - before; if
    len(mesh_objs) == 0:). An if that only follows a load tests something else (the checks of Nov 6: a GPU test
    after an HDRI's load)."""
    before = _before(r, stmt)
    first = next((k for k, s in enumerate(before) if _loads([s])), None)
    if first is None:
        return False
    sets = []  # (names bound, value) of each binding at or after the load: an assignment, or x.extend(...) and the like
    for x in _walk_here(before[first:]):
        if isinstance(x, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)) and x.value is not None:
            targets = x.targets if isinstance(x, ast.Assign) else [x.target]
            sets.append(({y.id for t in targets for y in ast.walk(t) if isinstance(y, ast.Name)}, x.value))
        elif isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and isinstance(x.func.value, ast.Name) and \
                x.func.attr in ("append", "extend", "add", "update") and x.args:
            sets.append(({x.func.value.id}, x.args[0]))
    gave = set()
    while True:  # a name bound to one that holds what the load gave holds it too (mesh_objs from new_objs)
        more = {name for names, value in sets if _gives(value, gave) for name in names} - gave
        if not more:
            break
        gave |= more
    return _gives(stmt.test, gave)


def _reads_file(call):
    """Whether call reads a file in: a loader (blender_gate._loader) or open() for reading (no mode, or one without
    w, a, x or +)."""
    from datagen import blender_gate  # it imports this module
    if blender_gate._loader(call):
        return True
    if not (isinstance(call.func, ast.Name) and call.func.id == "open"):
        return False
    mode = call.args[1] if len(call.args) > 1 else next((k.value for k in call.keywords if k.arg == "mode"), None)
    return mode is None or isinstance(mode, ast.Constant) and isinstance(mode.value, str) and \
        not set(mode.value) & set("wax+")


def _args(call):
    return list(call.args) + [k.value for k in call.keywords]


def _reaches_read(r, has):
    """Whether a read of a file (_reads_file) anywhere in the piece gets an argument of which has(node) holds, or a
    name bound to one; also through a function of the piece whose parameter reaches such a read, called with one
    (blender_gate._loaded's reading, for a path rather than a key)."""
    from datagen import blender_gate
    names = blender_gate._bound_from(r.tree, has)

    def hit(n):
        return has(n) or any(isinstance(x, ast.Name) and x.id in names for x in ast.walk(n))

    def reaches(scope, test):
        bound = blender_gate._bound_from(scope, test)
        return any(isinstance(c, ast.Call) and _reads_file(c) and
                   any(test(a) or any(isinstance(x, ast.Name) and x.id in bound for x in ast.walk(a))
                       for a in _args(c)) for c in ast.walk(scope))
    if reaches(r.tree, hit):
        return True
    for fn in r.helpers.values():
        params = [a.arg for a in fn.args.posonlyargs + fn.args.args]
        for k, p in enumerate(params):
            if not reaches(fn, lambda n, p=p: any(isinstance(x, ast.Name) and x.id == p for x in ast.walk(n))):
                continue
            for c in ast.walk(r.tree):
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == fn.name:
                    v = c.args[k] if k < len(c.args) else next((w.value for w in c.keywords if w.arg == p), None)
                    if v is not None and hit(v):
                        return True
    return False


def _variables(r):
    """The names the piece binds other than by an import (a module such as os or bpy is no path)."""
    imported = {(a.asname or a.name).split(".")[0] for n in ast.walk(r.tree)
                if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    out = {n.id for n in ast.walk(r.tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    for n in ast.walk(r.tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = n.args
            out.update(x.arg for x in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg] if x is not None)
    return out - imported


def _keyed(n, keys):
    """Whether n reads one of keys from a dict (d["key"] or d.get("key"))."""
    return any(isinstance(x, ast.Subscript) and isinstance(x.slice, ast.Constant) and x.slice.value in keys or
               isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr == "get" and x.args and
               isinstance(x.args[0], ast.Constant) and x.args[0].value in keys for x in ast.walk(n))


def _tests_input(r, n):
    """Whether expression n tests that a path the piece reads in is there (FILE_TESTS' calls): the path tested
    (os.path.isfile(p)'s argument, or what p.is_file() is called on) is made of a variable or a dict key that reaches
    a read of a file (_reaches_read). An output folder tested before the piece makes it is no input (the checks of
    Nov 6)."""
    variables = None
    for x in ast.walk(n):
        if not (isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr in FILE_TESTS):
            continue
        path = x.args[0] if x.args else x.func.value
        variables = _variables(r) if variables is None else variables
        # a dict's key read in the path (SETTINGS_s1["svg_path"]): the key, not the dict, and of a chain
        # (ctx["values"]["hdri"]) the last key only (ast.walk reads the outer read first)
        keys, dicts = set(), set()
        for y in ast.walk(path):
            if isinstance(y, ast.Subscript) and isinstance(y.slice, ast.Constant) and isinstance(y.slice.value, str):
                got, inner = y.slice.value, y.value
            elif isinstance(y, ast.Call) and isinstance(y.func, ast.Attribute) and y.func.attr == "get" and y.args \
                    and isinstance(y.args[0], ast.Constant) and isinstance(y.args[0].value, str):
                got, inner = y.args[0].value, y.func.value
            else:
                continue
            if id(y) not in dicts:
                keys.add(got)
            dicts.add(id(inner))
        names = {y.id for y in ast.walk(path) if isinstance(y, ast.Name) and y.id in variables and id(y) not in dicts}
        if (names or keys) and _reaches_read(r, lambda m: _keyed(m, keys) or any(
                isinstance(y, ast.Name) and y.id in names for y in ast.walk(m))):
            return True
    return False


def _names_an_input(r, key):
    """Whether key, a file's name ("acme.svg"), is the name of a file the piece reads in: a string of the piece ending
    in it, or a dict entry holding one, reaches a read of a file (_reaches_read). A video or a .blend the piece
    writes is no input (the checks of Nov 6)."""
    base = os.path.basename(str(key)).lower()

    def named(n):
        return isinstance(n, ast.Constant) and isinstance(n.value, str) and \
            os.path.basename(n.value.replace("\\", "/")).lower() == base
    keys = {k.value for d in ast.walk(r.tree) if isinstance(d, ast.Dict) for k, v in zip(d.keys, d.values)
            if isinstance(k, ast.Constant) and isinstance(k.value, str) and v is not None and named(v)}
    return _reaches_read(r, lambda m: any(named(y) for y in ast.walk(m)) or bool(keys) and _keyed(m, keys))


def for_file(r, node, key):
    """Whether a marker print (node) stands in for an input file the piece can't find rather than a key (since the
    fifth smoke, Nov 6; its tell is MARKER_FILE_TELL): its key has a file's extension and names a file the piece
    reads in ("acme.svg", _names_an_input), or the print is where a file is missing, within its own function: the
    else of an if that tests a path the piece reads in is there (_tests_input) or whose body loads a file, the body
    of an if that tests one isn't (if not os.path.isfile(svg_path)), whose else loads one, or that tests what a load
    before it in the same block gave (if not new_objs: after an SVG import; _after_load), or an except of a try whose
    body loads a file or tests one. A datablock looked up by name (bpy.data.fonts.get) is no file, nor an output the
    piece writes (the checks of Nov 6: an output folder tested, a video's name with its extension, a GPU test after an
    HDRI's load). Of the 103 stored Blender tries of smoke-smoke5 with a misused marker it reads 40 as files (an SVG,
    an SVG import that gave nothing, an HDRI or environment image, a font file; smoke5 14 of 26), and none of the
    others (a dependency's object, the GPU, render_device, world, a font datablock, an output path)."""
    if key and os.path.splitext(str(key))[1].lower() in FILE_EXTS and _names_an_input(r, key):
        return True
    child, up = node, r.parent.get(id(node))
    while up is not None and not isinstance(up, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        if isinstance(up, ast.If):
            negated = isinstance(up.test, ast.UnaryOp) and isinstance(up.test.op, ast.Not)
            if child in up.orelse and (_tests_input(r, up.test) and not negated or _loads(up.body)):
                return True
            if child in up.body and (negated and _tests_input(r, up.test) or _loads(up.orelse) or
                                     _after_load(r, up)):
                return True
        if isinstance(up, ast.ExceptHandler):
            t = r.parent.get(id(up))
            if isinstance(t, (ast.Try, getattr(ast, "TryStar", ast.Try))) and \
                    (_loads(t.body) or any(_tests_input(r, s) for s in t.body)):
                return True
        child, up = up, r.parent.get(id(up))
    return False


def stand_in_helpers(r):
    """{function name: parameter} for the piece's functions that print the marker with one of their parameters as
    the key (def _s2_stand_in(key): print("chimera: stand-in", key); return SETTINGS_s2[key]), also through repr() or
    str() or a .format keyword: the keys passed to it are marked."""
    out = {}
    for n, key, value in _marker_prints(r):
        fn = r.func.get(id(n))
        value = _unwrap(value)
        if key is None and isinstance(value, ast.Name) and isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and value.id in [a.arg for a in fn.args.posonlyargs + fn.args.args]:
            out[fn.name] = value.id
    return out


_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_COMPS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)


def _gens(x):
    """[(target, iter)] of a for loop or a comprehension, [] for anything else."""
    if isinstance(x, (ast.For, ast.AsyncFor)):
        return [(x.target, x.iter)]
    return [(g.target, g.iter) for g in x.generators] if isinstance(x, _COMPS) else []


def _binds(target, name):
    return any(isinstance(t, ast.Name) and t.id == name for t in ast.walk(target))


def _binder(r, node):
    """What binds a variable key's name where it is read: the innermost for loop or comprehension around it whose
    target does, else its function (None at the top)."""
    x = node
    while id(x) in r.parent:
        x = r.parent[id(x)]
        if isinstance(x, _FUNCS):
            return x
        if any(_binds(t, node.id) for t, _ in _gens(x)):
            return x
    return None


def _under_values(r, n):
    """Whether marker print n sits under a test that reads ctx["values"] (if key not in vals, an else of if key in
    vals, a loop over keys a comprehension picks by it) in its own function."""
    x = n
    while id(x) in r.parent:
        x = r.parent[id(x)]
        if isinstance(x, _FUNCS):
            return False
        tests = [x.test] if isinstance(x, (ast.If, ast.IfExp, ast.While)) else [it for _, it in _gens(x)] + \
            [c for g in getattr(x, "generators", ()) for c in g.ifs]
        if any(r.channel(y) == "values" for t in tests for y in ast.walk(t)):
            return True
    return False


def _looped(r, name):
    """The strings a marker's loop variable runs over: a literal list's, or the piece's own SETTINGS keys (for key in
    SETTINGS_s2, its .keys() or .items()); [] when they can't be read."""
    x = name
    while id(x) in r.parent:
        x = r.parent[id(x)]
        if isinstance(x, _FUNCS):
            return []
        for target, it in _gens(x):
            if isinstance(target, ast.Name) and target.id == name.id and isinstance(it, (ast.Tuple, ast.List, ast.Set)):
                keys = [_str(e) for e in it.elts]
                return [] if None in keys else keys
            first = target.elts[0] if isinstance(target, ast.Tuple) and target.elts else target
            if not (isinstance(first, ast.Name) and first.id == name.id):
                continue
            if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) and not it.args and \
                    it.func.attr == ("keys" if first is target else "items"):
                it = it.func.value
            elif first is not target:
                return []
            return _settings_keys(r.tree, r.sid) if r.is_settings(it) else []
    return []


def lookups(r):
    """The names the piece looks up or may look up by: every literal key it reads from ctx (any key) or a name bound
    to a channel, gets from any dict-like (.get("k"), x["k"], "k" in x) but its own SETTINGS dict (another step's
    SETTINGS_sM is a dependency's values, read the way pieces handed them on before ctx["values"]), a SETTINGS dict's
    string values, the strings it passes to helpers of its own, and the strings of a literal a for loop goes over."""
    out = set()
    for n in ast.walk(r.tree):
        if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load) and not r.is_settings(n.value):
            k = _str(n.slice)
            if k is not None:
                out.add(k)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("get", "setdefault") \
                and n.args and not r.is_settings(n.func.value):
            k = _str(n.args[0])
            if k is not None:
                out.add(k)
        elif isinstance(n, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in n.ops):
            k = _str(n.left)
            if k is not None and not any(r.is_settings(x) for x in n.comparators):
                out.add(k)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in r.helpers:
            out.update(k for k in map(_str, n.args) if k is not None)
        elif isinstance(n, (ast.For, ast.comprehension)) and isinstance(n.iter, (ast.Tuple, ast.List, ast.Set)):
            out.update(k for k in map(_str, n.iter.elts) if k is not None)
        elif isinstance(n, ast.Assign) and isinstance(n.value, ast.Dict) and \
                any(isinstance(t, ast.Name) and t.id.startswith("SETTINGS_") for t in n.targets):
            out.update(k for v in n.value.values for k in (_str(x) for x in ast.walk(v)) if k is not None)
    return out


def _settings_keys(tree, sid=None):
    """The keys of the piece's top-level SETTINGS_<sid> dict (every SETTINGS_ dict's when sid is None)."""
    out = []
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Dict) and \
                any(isinstance(t, ast.Name) and (t.id == "SETTINGS_" + sid if sid else t.id.startswith("SETTINGS_"))
                    for t in n.targets):
            out += [k for k in map(_str, n.value.keys) if k is not None]
    return out


def written_values(r):
    """The literal keys the piece writes into ctx["values"] (a store, setdefault), through ctx or a bound name, and
    its own SETTINGS keys when it also writes ctx["values"] in a way whose keys can't be read (a computed key, as a
    loop over its SETTINGS writes them, or update())."""
    out, opaque = set(), False
    for n in ast.walk(r.tree):
        if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store) and r.channel(n.value) == "values":
            k = _str(n.slice)
            if k is not None:
                out.add(k)
            else:
                opaque = True
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("setdefault", "update") \
                and r.channel(n.func.value) == "values":
            k = _str(n.args[0]) if n.func.attr == "setdefault" and n.args else None
            if k is not None:
                out.add(k)
            else:
                opaque = True
    if opaque:
        out.update(_settings_keys(r.tree, r.sid))
    return out


def _values_get(r, n):
    """(key node, default node or None) when n reads ctx["values"] with .get, else None."""
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args and \
            r.channel(n.func.value) == "values":
        return n.args[0], (n.args[1] if len(n.args) > 1 else n.keywords[0].value if n.keywords else None)
    return None


def _none(n):
    return n is None or isinstance(n, ast.Constant) and n.value is None


def silent_reads(r):
    """[(key node, line, function)] for every read of ctx["values"] with a default: .get(k, d) with d not None,
    .get(k) or d, and an x-if-k-in-values-else-d (either way round)."""
    out = []
    for n in ast.walk(r.tree):
        g = _values_get(r, n)
        if g is not None and not _none(g[1]):
            out.append((g[0], n.lineno, r.where(n)))
        elif isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or) and len(n.values) > 1:
            g = _values_get(r, n.values[0])
            if g is not None and _none(g[1]):
                out.append((g[0], n.lineno, r.where(n)))
        elif isinstance(n, ast.IfExp) and isinstance(n.test, ast.Compare) and len(n.test.ops) == 1 and \
                isinstance(n.test.ops[0], (ast.In, ast.NotIn)) and r.channel(n.test.comparators[0]) == "values":
            out.append((n.test.left, n.lineno, r.where(n)))
    return out


def dep_names(texts):
    """What earlier kept pieces hand on (texts: their replies): provides names, written ctx keys, and the SETTINGS
    keys of one that writes ctx["values"] in a way whose keys can't be read."""
    out = set()
    for text in texts:
        h = V.parse_handoff(text or "")[0]
        provides = (h.provides if h is not None else "") or ""
        out.update(provided_names(provides))
        out.update(uses_names(provides))
        tree = _parse(piece_code(text))
        if tree is None:
            continue
        for ch in CHANNELS:
            written, _, opaque = V.ctx_keys(tree, ch)
            out.update(written)
            if opaque:
                out.update(_settings_keys(tree))
        out.update(written_values(_Reader(tree)))
    return out - set(CTX_OWN)


def _helper_keys(r, fn, param):
    """The literal keys the piece passes to helper fn's parameter param (by position or name), [] when none is
    literal."""
    if fn is None:
        return []
    params = [a.arg for a in fn.args.posonlyargs + fn.args.args]
    if param not in params:
        return []
    k = params.index(param)
    out = []
    for n in ast.walk(r.tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == fn.name:
            v = n.args[k] if k < len(n.args) else next((w.value for w in n.keywords if w.arg == param), None)
            if _str(v) is not None:
                out.append(_str(v))
    return out


def _matches(key, seen):
    """A marker's key names something the piece looks up: the same name, with chimera_ before either or not, or the
    start of one ("room" for room_length: "chimera: stand-in room dimensions"), or a name with more after it."""
    seen = set(seen) | {x.removeprefix("chimera_") for x in seen}
    for k in (key, key.removeprefix("chimera_")):
        if k in seen or any(x.startswith(k + "_") or k.startswith(x + "_") for x in seen if len(x) > 2):
            return True
    return False


def _loop_keys(r):
    """{id(name node): [strings]} for each read of a loop variable that runs over a literal list of strings (for k in
    ("seat_h", "leg_r"), or a comprehension's): the keys it stands for."""
    out = {}
    for n in ast.walk(r.tree):
        if isinstance(n, ast.For):
            gens, inside = [(n.target, n.iter)], n.body
        elif isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            gens = [(g.target, g.iter) for g in n.generators]
            inside = [n.key, n.value] if isinstance(n, ast.DictComp) else [n.elt]
            inside += [c for g in n.generators for c in g.ifs]
        else:
            continue
        for target, it in gens:
            if not (isinstance(target, ast.Name) and isinstance(it, (ast.Tuple, ast.List, ast.Set)) and it.elts):
                continue
            keys = [_str(x) for x in it.elts]
            if None in keys:
                continue
            for part in inside:
                for x in ast.walk(part):
                    if isinstance(x, ast.Name) and x.id == target.id and isinstance(x.ctx, ast.Load):
                        out[id(x)] = keys
    return out


def check(code, deps=(), earlier=None, sid=None):
    """The two faults of a Blender piece's code. deps: the step's dependency ids ("s1"); earlier: {"sN": text} of the
    earlier steps' kept pieces, as the gate joins them (a variant, checked alone, has none: every dependency is
    missing); sid: the step's own id, whose SETTINGS_<sid> is the piece's own (None: every SETTINGS_ dict). Returns
    {"marker": [keys], "silent": [{"key", "line", "function"}] (key None for a variable's), "dep_names": sorted,
    "missing": whether a dependency has no kept piece, "files": the marker's keys that stand in for a missing input
    file (for_file, since Nov 6: told what to print instead)}, empty lists for code that doesn't parse."""
    earlier = earlier or {}
    names = dep_names(earlier.values())
    missing = any(d not in earlier for d in deps or ())
    out = {"marker": [], "silent": [], "dep_names": sorted(names), "missing": missing, "files": []}
    tree = _parse(code)
    if tree is None:
        return out
    r = _Reader(tree, sid)
    prints = _marker_prints(r)
    seen = lookups(r) | names
    files = set()  # the keys of markers that stand in for a missing file (for_file), told MARKER_FILE_TELL
    for n, key, value in prints:
        if key is None and not deps and (value is None or isinstance(_unwrap(value), ast.Constant)):
            key = _keyless(n)  # a marker with no key on a step with no dependency: misused all the same
        if key is None:
            continue
        if for_file(r, n, key):
            files.add(key)
        if key in out["marker"]:
            continue
        if not deps or not _matches(key, seen):
            out["marker"].append(key)
    out["files"] = [k for k in out["marker"] if k in files]
    if not deps:
        return out
    own = written_values(r)
    literal_marks = {k for _, k, _ in prints if k is not None}
    helpers = stand_in_helpers(r)
    for name, param in helpers.items():  # the keys passed to a stand-in helper are marked
        literal_marks.update(_helper_keys(r, r.helpers.get(name), param))
    # A marker covers a read only when it has a key: a literal one, or one a variable or an expression gives (a marker
    # with no key, "chimera: stand-in – sofa not found", covers nothing: the second checks, Nov 6)
    keyed = [(n, k, v) for n, k, v in prints if k is not None or (v is not None and
                                                                not isinstance(_unwrap(v), ast.Constant))]
    marked = {id(r.func.get(id(n))) for n, _, _ in keyed}  # functions (id; id(None) for the top) with a marker
    dynamic = {id(r.func.get(id(n))) for n, k, _ in keyed if k is None}
    # A marker loop under a ctx["values"] test (if key not in vals) is the values' own: it covers reads in the
    # functions it is around or calls, and the keys it loops over wherever they are read (the second checks: an
    # object's marker loop in build_s3 covered a nested get()'s silent default)
    values_marks = [(n, v) for n, k, v in keyed if k is None and _under_values(r, n)]
    values_funcs = {id(r.func.get(id(n))) for n, _ in values_marks}
    for n, v in values_marks:
        if isinstance(_unwrap(v), ast.Name):
            literal_marks.update(_looped(r, _unwrap(v)))
    loops = _loop_keys(r)

    def dependency(k):
        return k not in own and (k in names or missing)

    def handed(node):
        """A variable key passed, as the same name bound the same way (the loop that binds it, else its function), to
        a stand-in helper (vals.get(k) or _s2_stand_in(k)); a loop or function inside that binds it again is another
        name."""
        where = _binder(r, node)
        stack = list(ast.iter_child_nodes(where if where is not None else r.tree))
        while stack:
            n = stack.pop()
            if n is not where and (isinstance(n, _FUNCS) and node.id in r.local.get(id(n), ()) or
                                   any(_binds(t, node.id) for t, _ in _gens(n))):
                continue
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in helpers and \
                    any(isinstance(a, ast.Name) and a.id == node.id for a in n.args):
                return True
            stack.extend(ast.iter_child_nodes(n))
        return False
    for node, line, where in silent_reads(r):
        k = _str(node)
        inner = id(r.func.get(id(node)))  # the read's own function (id(None) at the top)
        # a marker with a variable's key in the read's own function covers it, and a values marker loop in one around
        # it or one that calls it; a marker with a literal key covers only reads in its own function, as before (the
        # fourth smoke's GPU fallback "render_device" in a build_s4 covers no nested get(key) helper's silent read)
        around = {id(f) for f in r.around(node)} | {inner}
        covered = inner in dynamic or bool(around & values_funcs)
        keys = [k]
        if k is not None:
            if not dependency(k) or k in literal_marks or covered:
                continue
        elif isinstance(node, ast.Name) and id(node) in loops:  # a loop over a literal list: its strings, as keys
            if covered or handed(node):
                continue
            keys = [x for x in loops[id(node)] if dependency(x) and x not in literal_marks]
        else:  # a variable's key: the helper's literal keys when it has some, else taken for a dependency's
            if inner in marked or covered or (isinstance(node, ast.Name) and handed(node)):
                continue
            fn = r.helpers.get(where) if where else None
            param = node.id if isinstance(node, ast.Name) else None
            got = _helper_keys(r, fn, param)
            if got and not any(dependency(x) and x not in literal_marks for x in got):
                continue
        for key in keys:
            row = {"key": key, "line": line, "function": where}
            if row not in out["silent"]:
                out["silent"].append(row)
    return out


def _quote(keys, n=QUOTES):
    return ", ".join(json.dumps(k) for k in keys[:n]) + (" and more" if len(keys) > n else "")


def fitted(form, keys, **slots):
    """form filled with up to QUOTES of keys, or with the first one and "and more" when that runs past
    FAILURE_CHARS (long keys)."""
    line = form.format(quotes=_quote(keys), **slots)
    return line if len(line) <= FAILURE_CHARS else form.format(quotes=_quote(keys, 1), **slots)


def tell(found):
    """The tell lines for check's faults (teacher-only), each at most FAILURE_CHARS long: one for the marker's keys
    that stand in for a missing input file (found["files"], since the fifth smoke: MARKER_FILE_TELL, what to print
    instead), one for its other keys, one for the silent literal keys, one for a helper that reads with a variable's
    key."""
    lines = []
    files = [k for k in found.get("files") or [] if k in (found.get("marker") or [])]
    if files:
        lines.append(fitted(MARKER_FILE_TELL, files))
    keys = [k for k in found.get("marker") or [] if k not in files]
    if keys:
        lines.append(fitted(MARKER_TELL, keys))
    rows = found.get("silent") or []
    keys = list(dict.fromkeys(x["key"] for x in rows if x["key"] is not None))
    if keys:
        lines.append(fitted(SILENT_TELL, keys, marker=MARKER_CALL))
    helpers = list(dict.fromkeys(x["function"] or "the piece" for x in rows if x["key"] is None))
    if helpers:
        lines.append(SILENT_HELPER_TELL.format(where=", ".join(h + "()" if h != "the piece" else h
                                                               for h in helpers[:QUOTES]), marker=MARKER_CALL))
    return [line[:FAILURE_CHARS] for line in lines]
