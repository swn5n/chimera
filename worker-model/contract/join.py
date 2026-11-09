"""Join a plan's pieces into the finished result with no model (the plan's "JOINING").

    from contract.join import join
    j = join(plan, outputs, goal=goal)
    j.fallback, j.reasons   # a piece broke its mode rules: today's synthPrompt combine instead (today.py)
    j.text                  # the result the person gets (handoff blocks stripped)
    j.script, j.linemap     # blender / python-script: the joined script and which step each line came from
    j.assumptions           # [(sid, assumed)], for the reply's Assumptions note
    j.seams                 # what the seam pass would be run for (Issue level "seam")

outputs maps a step's plan id to its reply: a string, None for a failed step, or {"output", "status"}
with status "library" for a library entry runStep wrote as a bare fenced block.

Blender: one script, imports deduplicated at the top, then each step's part in plan order (cleanPlan keeps
dependencies on earlier steps only, so plan order is valid), holding the piece's SETTINGS_sN, _sN_ constants,
helpers and build function in the piece's own order, then main(), which makes ctx with a chimera_<slug>
collection, calls build_s1(ctx) and the rest, then does the save or render from SETTINGS_*["output"] once.
(The plan has every SETTINGS_* dict in one "# Settings" part at the top; that moved a dict above the _sN_
constant it uses, so a piece that ran alone crashed joined.) python-script: the same, main() called at the
end (no main() is a seam). files: merged by path. sections: "# title" and the sections in plan order; the
plan's editor pass over them is a hook here (join's editor), not written.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import planinfo
from .goport import code_blocks, go_trim_space, python_lang, truncate
from .linemap import LineMap
from .today import norm_output
from .validate import (CTX_CHANNELS, Issue, Piece, assigned_names, ctx_keys, def_name, file_line, is_docstring,
                       is_main_guard, top_level_names, validate_piece)
from . import texts as T

STEP_HEADER = "# --- {sid}: {title} ---"  # marks each step's part of a joined script (round 2 finds it by title)
_HEADER_RE = re.compile(r"^# --- (s\d+): (.*) ---$")


@dataclass
class Joined:
    plan_title: str
    fallback: bool = False
    reasons: List[str] = field(default_factory=list)
    text: str = ""
    script: Optional[str] = None
    script_kind: Optional[str] = None  # run_blender / run_python, as Chimera's check names them
    linemap: Optional[LineMap] = None
    files: List[dict] = field(default_factory=list)  # {path, lang, body, steps}
    assumptions: List[tuple] = field(default_factory=list)
    seams: List[Issue] = field(default_factory=list)
    pieces: Dict[str, Piece] = field(default_factory=dict)
    failed: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    parts: List[dict] = field(default_factory=list)  # the result after its "# title", in order: {mode, steps, text}
    editor_wanted: bool = False  # two or more sections: the plan's editor pass would join them (join's editor hook)
    edited: bool = False  # the editor hook gave the text
    raw_text: Optional[str] = None  # with edited: the plain concatenation it replaced

    def assumptions_note(self):
        """The reply's Assumptions note ("" if no step had to guess)."""
        if not self.assumptions:
            return ""
        return "Assumptions: " + "; ".join("%s: %s" % (sid, a) for sid, a in self.assumptions)

    def to_dict(self):
        return {"title": self.plan_title, "fallback": self.fallback, "reasons": self.reasons,
                "script_kind": self.script_kind, "failed": self.failed, "notes": self.notes,
                "editor_wanted": self.editor_wanted, "edited": self.edited,
                "assumptions": [{"step": s, "assumed": a} for s, a in self.assumptions],
                "seams": [dict(i.to_dict(), step=getattr(i, "sid", None)) for i in self.seams],
                "files": [{"path": f["path"], "lang": f["lang"], "steps": f["steps"]} for f in self.files],
                "pieces": {sid: p.to_dict() for sid, p in self.pieces.items()}}


def _seam(code, message, sid=None):
    i = Issue("seam", code, message)
    i.sid = sid
    return i


def slug(title):
    return re.sub(r"[^a-z0-9]+", "_", (title or "").lower()).strip("_")[:40].strip("_") or "project"


# ---------------------------------------------------------------- python source plumbing

def source_lines(code):
    """code's lines as Python's parser counts them: a lone carriage return ends a line for ast, not for split."""
    return code.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def segments(code, tree):
    """[(node, start, end)]: each top-level statement's 1-based line range, with the comment lines just above it
    (and its decorators). A statement sharing a line with the one before (a; b) gets that line's range."""
    lines = source_lines(code)
    out, prev_end = [], 0
    for node in tree.body:
        first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        start = first
        if first > prev_end:
            start = prev_end + 1
            while start < first and go_trim_space(lines[start - 1]) == "":
                start += 1
        out.append((node, start, node.end_lineno))
        prev_end = max(prev_end, node.end_lineno)
    return out


class Imports:
    """Imports from several pieces, deduplicated name by name, in first-seen order.
    origin[key] is (sid, piece line) of the first piece that had it."""

    def __init__(self):
        self.origin = {}  # ("import", name, asname) or ("from", level, module, name, asname) -> (sid, line)
        self.bound = {}  # name -> (what binds it, sid)
        self.conflicts = []  # (name, (what, sid), (what, sid)): two pieces bind one name to different things

    @staticmethod
    def keys(node):
        if isinstance(node, ast.Import):
            return [("import", a.name, a.asname) for a in node.names]
        return [("from", node.level, node.module or "", a.name, a.asname) for a in node.names]

    def add(self, node, sid, line):
        for key in self.keys(node):
            self.origin.setdefault(key, (sid, line))
            if key[0] == "import":
                name, what = key[2] or key[1].split(".")[0], "import " + (key[1] if key[2] else key[1].split(".")[0])
            elif key[3] == "*" or key[2] == "__future__":
                continue
            else:
                name, what = key[4] or key[3], "from %s%s import %s" % ("." * key[1], key[2], key[3])
            if name in self.bound and self.bound[name][0] != what:
                self.conflicts.append((name, self.bound[name], (what, sid)))
            self.bound.setdefault(name, (what, sid))

    def lines(self, skip=()):
        """[(text, origin)] for a joined file: __future__ first, then plain imports, then from-imports, each in
        first-seen order. A from-import line holds the names of one piece statement (one origin) that no earlier
        piece imported, so the line map blames the step that wrote the name: s2's `from mathutils import Vector`
        and s3's `from mathutils import radians` stay two lines. Keys in skip are left out."""
        keys = [k for k in self.origin if k not in skip]
        out = []

        def grouped(ks):  # (level, module, origin) -> keys, in first-seen order
            groups = {}
            for k in ks:
                groups.setdefault((k[1], k[2], self.origin[k]), []).append(k)
            return groups

        future = [k for k in keys if k[0] == "from" and k[2] == "__future__"]
        for (_, _, origin), ks in grouped(future).items():
            out.append(("from __future__ import " + ", ".join(k[3] for k in ks), origin))
        for k in keys:
            if k[0] == "import":
                out.append(("import %s%s" % (k[1], " as " + k[2] if k[2] else ""), self.origin[k]))
        rest = [k for k in keys if k[0] == "from" and k[2] != "__future__"]
        for (level, module, origin), ks in grouped(rest).items():
            src = "." * level + module
            if any(k[3] == "*" for k in ks):
                out.append(("from %s import *" % src, origin))
            names = [k for k in ks if k[3] != "*"]
            if names:
                out.append(("from %s import %s" % (src, ", ".join(k[3] + (" as " + k[4] if k[4] else "") for k in names)),
                            origin))
        return out


class Script:
    """A joined script being written, with each line's origin for the line map."""

    def __init__(self):
        self.lines, self.origins = [], []

    def add(self, text, origin=None):
        for l in text.split("\n"):
            self.lines.append(l)
            self.origins.append(origin)

    def add_from(self, code_lines, start, end, sid, part, function):
        for n in range(start, end + 1):
            self.lines.append(code_lines[n - 1])
            self.origins.append([sid, part, function, n])

    def blank(self):
        if self.lines and self.lines[-1] != "":
            self.add("")

    def text(self):
        return "\n".join(self.lines).rstrip("\n") + "\n"


def _string_lines(code):
    """The lines that start inside a multi-line string, which an indent would change."""
    inside, opened = set(), []
    for t in tokenize.generate_tokens(io.StringIO(code).readline):
        if t.type == tokenize.STRING:
            inside.update(range(t.start[0] + 1, t.end[0] + 1))
        elif t.type == tokenize.FSTRING_START:
            opened.append(t.start[0])
        elif t.type == tokenize.FSTRING_END:
            inside.update(range(opened.pop() + 1, t.end[0] + 1))
    return inside


def wrap_library(piece: Piece, sid, mode):
    """A library entry (a bare fenced block from runStep) as a contract piece: for blender its code goes into
    def build_sN(ctx): with the imports hoisted. Star imports or its own main guard count as a seam."""
    blocks = [b for b in code_blocks(piece.text) if python_lang(b.lang) or b.lang == ""]
    piece.library = True
    seams = []
    if len(blocks) != 1:
        return seams + [_seam("library_seam", "the library entry isn't one python block", sid)]
    code = blocks[0].body
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [_seam("library_seam", "the library entry doesn't parse: %s" % e.msg, sid)]
    if any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names) for n in tree.body) \
            or any(is_main_guard(n) for n in tree.body):
        seams.append(_seam("library_seam", "the library entry has a star import or its own main guard", sid))
    if mode == "blender":
        lines = source_lines(code)
        imports, rest = [], []
        segs = segments(code, tree)
        in_string, written = _string_lines(code), 0
        for node, s, e in segs:
            s = max(s, written + 1)  # statements can share a line: it goes out once
            if s <= e:
                (imports if isinstance(node, (ast.Import, ast.ImportFrom)) else rest).append((s, e))
                written = e
        out = [lines[n - 1] for s, e in imports for n in range(s, e + 1)]
        out += ["SETTINGS_%s = {}" % sid, "", "def build_%s(ctx):" % sid]
        body = [(n, lines[n - 1]) for s, e in rest for n in range(s, e + 1)]
        out += ["    " + l if l.strip() and n not in in_string else l for n, l in body] or ["    pass"]
        code = "\n".join(out)
        try:
            tree = ast.parse(code)
        except SyntaxError as e:  # import a; b = (1,\n 2): hoisting the import cuts the statement beside it in two
            return seams + [_seam("library_seam", "the library entry doesn't parse: %s" % e.msg, sid)]
    piece.code, piece.tree, piece.code_line = code, tree, 1
    return seams


def alone_script(piece: Piece, keep_ctx=False, ctx_name="ctx", also=()):
    """A blender piece as data generation runs it alone: its own code with its main guard blanked out (so every
    line keeps the piece's own number), then ctx built at module level as the mode rule's guard builds it, and
    build_sN(ctx). Module-level ctx lets tools/scene_probe.py see what the piece registered. keep_ctx: the script
    follows its dependencies' script, so a module-level dict named ctx_name already there that looks like a ctx
    (an "objects" dict and a "collection") is passed on instead, with what they registered (join_script's guard
    leaves one named ctx), and one more tail line gives it ctx["values"] if it has none: a dependency's script
    from before Nov 4 (the eval runner's after_deps can put one first) built ctx without it, and the reader then
    died on KeyError 'values' instead of making its stand-ins. The condition is unchanged, since asking for
    "values" there would throw away what the dependencies registered in ctx["objects"]; the piece's own lines keep
    their numbers either way. also: more build functions to call after it, in order."""
    lines = source_lines(piece.code)
    for node, a, b in segments(piece.code, piece.tree):
        if is_main_guard(node):
            for n in range(node.lineno, b + 1):
                lines[n - 1] = ""
    while lines and not lines[-1].strip():
        lines.pop()
    imports = Imports()
    for node in piece.tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.add(node, piece.sid, node.lineno)
    tail = [] if ("import", "bpy", None) in imports.origin else ["import bpy"]
    fresh = '{"scene": bpy.context.scene, "collection": bpy.context.scene.collection, "objects": {}, "values": {}}'
    if keep_ctx:
        c = ctx_name
        tail.append(f'ctx = {c} if isinstance(globals().get("{c}"), dict) and isinstance({c}.get("objects"), dict) '
                    f'and "collection" in {c} else {fresh}')
        tail.append('ctx.setdefault("values", {})')  # a ctx from before ctx["values"]
    else:
        tail.append("ctx = " + fresh)
    tail += ["build_%s(ctx)" % sid for sid in [piece.sid] + list(also)]
    return "\n".join(lines + ["", ""] + tail) + "\n"


# ---------------------------------------------------------------- blender and python-script

_OUTPUT_FN = '''def _chimera_output(settings):
    """Chimera's: the save and render the steps put in SETTINGS_*["output"], done once after the last step."""
    import os
    out = {}
    for s in settings:
        o = s.get("output") if isinstance(s, dict) else None
        if isinstance(o, str):
            o = {"blend" if o.lower().endswith(".blend") else "render": o}
        for k, v in (o.items() if isinstance(o, dict) else ()):
            if isinstance(v, dict):
                out.update(v)  # {"render": {"filepath": ..., "resolution": ...}}
            else:
                out[k] = v
    scene, media = bpy.context.scene, (".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff", ".bmp", ".webp",
                                       ".mp4", ".mkv", ".mov", ".avi")
    strs = [v for v in out.values() if isinstance(v, str)]
    blend = next((v for v in strs if v.lower().endswith(".blend")), None)
    render = next((v for v in strs if os.path.splitext(v)[1].lower() in media), None)

    def put(obj, attr, v):
        try:
            setattr(obj, attr, v)
        except (AttributeError, TypeError, ValueError) as e:
            print("chimera: output setting skipped:", attr, e)

    def path(p):
        p = bpy.path.abspath(p) if p.startswith("//") else os.path.abspath(os.path.expanduser(p))
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        return p

    r = scene.render
    res = out.get("resolution")
    if isinstance(res, (list, tuple)) and len(res) == 2:
        put(r, "resolution_x", int(res[0]))
        put(r, "resolution_y", int(res[1]))
    names = {"resolution_x": ("resolution_x", "width", "render_width"),
             "resolution_y": ("resolution_y", "height", "render_height"),
             "resolution_percentage": ("resolution_percentage",), "fps": ("fps",), "frame_start": ("frame_start",),
             "frame_end": ("frame_end",)}
    for attr, keys in names.items():
        v = next((out[k] for k in keys if isinstance(out.get(k), (int, float)) and not isinstance(out.get(k), bool)), None)
        if v is not None:
            put(scene if attr.startswith("frame_") else r, attr, int(v))
    engine = out.get("engine") or out.get("render_engine")
    if isinstance(engine, str):
        put(r, "engine", engine.upper())
    samples = out.get("samples") or out.get("render_samples")
    if isinstance(samples, int) and not isinstance(samples, bool):
        if r.engine == "CYCLES" and getattr(scene, "cycles", None) is not None:
            put(scene.cycles, "samples", samples)
        elif getattr(scene, "eevee", None) is not None:
            put(scene.eevee, "taa_render_samples", samples)
    if blend:
        bpy.ops.wm.save_as_mainfile(filepath=path(blend))
        print("chimera: saved", blend)
    if render:
        ext = os.path.splitext(render)[1].lower()
        video = ext in (".mp4", ".mkv", ".mov", ".avi") or bool(out.get("animation"))
        r.filepath = path(render)
        if video:
            put(r.image_settings, "media_type", "VIDEO")
            put(r.image_settings, "file_format", "FFMPEG")
        else:
            fmt = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".exr": "OPEN_EXR", ".tif": "TIFF",
                   ".tiff": "TIFF", ".bmp": "BMP", ".webp": "WEBP"}.get(ext)
            if fmt:
                put(r.image_settings, "file_format", fmt)
        if scene.camera is None:
            print("chimera: no camera in the scene, so no render")
            return
        bpy.ops.render.render(animation=video, write_still=not video)'''


def _has_output(piece):
    for node in piece.tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Dict) \
                and assigned_names(node) == ["SETTINGS_" + piece.sid]:
            return any(isinstance(k, ast.Constant) and k.value == "output" for k in node.value.keys)
    return False


def _part_of(node, sid, blender):
    """(part, function) a top-level statement of a piece gets in the line map. function is the def or class
    name, or the first name an assignment binds (a _s2_ constant), so a repair message can say where."""
    name = def_name(node)
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        names = assigned_names(node) or []
        if blender and names == ["SETTINGS_" + sid]:
            return "settings", "SETTINGS_" + sid
        name = names[0] if names else None
    if blender:
        return ("build" if name == "build_" + sid else "helper"), name
    return "code", name


def join_script(plan, pieces, mode):
    """Join blender or python-script pieces (in plan order) into one script. Returns (script, linemap, seams).

    Each step's part keeps the piece's own top-level order (its SETTINGS_sN, _sN_ constants, classes, helpers and
    build function, as the piece has them), so a SETTINGS dict that uses the step's own _sN_ constant works
    joined just as it does alone. Only the imports move: to the top, deduplicated."""
    blender = mode == "blender"
    imports, s, seams = Imports(), Script(), []
    title = planinfo.one_line(plan["title"])
    order = [p.sid for p in pieces]
    titles = {("s%d" % (i + 1)): planinfo.one_line(st["title"]) for i, st in enumerate(plan["steps"])}
    bodies, mains = [], []
    for p in pieces:
        code_lines = source_lines(p.code)
        body, prev_end, dropped, written = [], None, False, 0
        for node, a, b in segments(p.code, p.tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.add(node, p.sid, node.lineno)
                dropped = True
            elif is_docstring(node) or is_main_guard(node):
                dropped = True  # the piece's own docstring and run-alone guard aren't part of the joined script
            else:
                part, name = _part_of(node, p.sid, blender)
                a = max(a, written + 1)  # statements can share a line: it goes out once
                if a <= b:
                    # blank lines before it: the piece's own (at most 2) when nothing was left out in between, else 2
                    gap = 2 if prev_end is None or dropped else min(2, a - prev_end - 1)
                    body.append((code_lines, a, b, part, name, gap))
                    prev_end, dropped, written = b, False, b
                if not blender and isinstance(node, ast.FunctionDef) and node.name == "main":
                    mains.append(p.sid)
        bodies.append((p.sid, body))
    for name, (src1, sid1), (src2, sid2) in imports.conflicts:
        seams.append(_seam("import_conflict", "%s is %s in %s but %s in %s" % (name, src1, sid1, src2, sid2), sid2))

    s.add("# " + title)
    kind = "Blender" if blender else "Python"
    s.add("# Joined by Chimera from %d %s piece%s (%s): %s" % (
        len(pieces), kind, "" if len(pieces) == 1 else "s", ", ".join(order),
        "each step's part in plan order, with its SETTINGS_ dict; main() runs the steps, then saves or renders once."
        if blender else "each step's part in plan order; main() runs at the end."))
    if blender and ("import", "bpy", None) not in imports.origin:  # main() needs it
        imports.origin = {("import", "bpy", None): None, **imports.origin}
    for text, origin in imports.lines():
        s.add(text, origin and [origin[0], "import", None, origin[1]])
    for sid, body in bodies:
        s.add("")
        s.add("")
        s.add(STEP_HEADER.replace("{sid}", sid).replace("{title}", titles.get(sid, "")))
        for i, (code_lines, a, b, part, name, gap) in enumerate(body):
            for _ in range(gap if i else 0):
                s.add("")
            s.add_from(code_lines, a, b, sid, part, name)
    if blender:
        outputs = [p.sid for p in pieces if _has_output(p)]
        s.add("")
        s.add("")
        s.add("def main():", [None, "main", "main", None])
        main_lines = ["    scene = bpy.context.scene",
                      "    collection = bpy.data.collections.new(\"chimera_%s\")" % slug(plan["title"]),
                      "    scene.collection.children.link(collection)",
                      "    ctx = {\"scene\": scene, \"collection\": collection, \"objects\": {}, \"values\": {}}"]
        main_lines += ["    build_%s(ctx)" % sid for sid in order]
        if outputs:
            main_lines.append("    _chimera_output([%s])" % ", ".join("SETTINGS_" + sid for sid in outputs))
        main_lines.append("    return ctx")
        for l in main_lines:
            s.add(l, [None, "main", "main", None])
        if outputs:
            s.add("")
            s.add("")
            s.add(_OUTPUT_FN, [None, "output", "_chimera_output", None])
        s.add("")
        s.add("")
        # ctx at module level, so a probe appended to the script (tools/scene_probe.py) sees what was registered
        s.add("if __name__ == \"__main__\":\n    ctx = main()", [None, "main", None, None])
    elif mains:
        if len(mains) > 1:
            seams.append(_seam("duplicate_name", "main() is defined by %s" % ", ".join(mains), mains[-1]))
        s.add("")
        s.add("")
        s.add("if __name__ == \"__main__\":\n    main()", [None, "main", None, None])
    else:
        # Nothing would run: the check would pass in no time without running a line of the steps' code, and
        # the plan-level rule for code is "the joined project compiles and its entry point runs".
        seams.append(_seam("missing_entry_point", "no step defines main(), so the joined script only defines "
                           "functions and runs nothing (a check of it would pass without running the steps' code)"))
    script = s.text()
    seams += _duplicate_names(pieces)
    lm = LineMap(s.origins, titles, kind=mode)
    try:
        ast.parse(script)
    except SyntaxError as e:  # every piece parsed alone, so this is the joiner's fault or a dedent clash
        seams.append(_seam("join_syntax", "the joined script doesn't parse at line %s: %s" % (e.lineno, e.msg),
                           (lm.locate(e.lineno or 0) or {}).get("step")))
    return script, lm, seams


def defined_names(tree):
    """Names a module's own defs, classes and assignments bind at the top (imports not counted)."""
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            out.extend(assigned_names(node) or [])
    return out


def _duplicate_names(pieces):
    seen, seams = {}, []
    for p in pieces:
        for n in dict.fromkeys(defined_names(p.tree)):
            if n in seen and seen[n] != p.sid:
                seams.append(_seam("duplicate_name", "%s is defined by %s and %s" % (n, seen[n], p.sid), p.sid))
            seen.setdefault(n, p.sid)
    return seams


def _binds(node, channel):
    """Whether node is ctx[channel], ctx.get(channel, ...) or ctx.setdefault(channel, ...): the dict itself."""
    if isinstance(node, ast.Subscript):
        return (isinstance(node.value, ast.Name) and node.value.id == "ctx" and isinstance(node.slice, ast.Constant)
                and node.slice.value == channel)
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("get", "setdefault") and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ctx" and bool(node.args) and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == channel)


def _bound_writes(tree, channel):
    """(written, opaque) of the writes into ctx[channel] that ctx_keys doesn't follow: through a name every plain
    binding of which (name = ..., name: T = ...) is the dict itself (_binds: `vals = ctx.setdefault("values", {})`,
    `objs = ctx["objects"]`), or straight into ctx.get(channel)[k] or ctx.setdefault(channel, {})[k]. A literal key
    stored or setdefault() through one is written; a computed key, update() or an augmented assignment to the name
    (|=) is opaque. Reads through one stay unrecorded, as before, so this only takes seams away. Why: a values
    step that wrote `v = ctx["values"]; v["sofa_width"] = ...` gave each of its readers a false ctx_key_missing in
    the real gate (5.2.2 and 5.0.1), which fails them (blender_gate.SEAMS_FAIL) though the joined script runs, and
    the told retry heard that no earlier step registers the key; 181 of the 343 distinct stored data-generation
    pieces that write ctx["objects"] do it only through a bound name, and 33 of the 72 with an improvised values
    channel. On the stored joins it changes no seam: 0 of 111 as they ran (bw-10's ROCK_COUNT seam stays) and 0 of
    412 with a step failed in turn."""
    seen = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            seen.setdefault(n.targets[0].id, []).append(n.value)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.value is not None:
            seen.setdefault(n.target.id, []).append(n.value)
    names = {k for k, values in seen.items() if all(_binds(v, channel) for v in values)}

    def through(n):
        return isinstance(n, ast.Name) and n.id in names or isinstance(n, ast.Call) and _binds(n, channel)

    def literal(n):
        return isinstance(n, ast.Constant) and isinstance(n.value, str)

    written, opaque = [], False
    for n in ast.walk(tree):
        if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store) and through(n.value):
            if literal(n.slice):
                written.append(n.slice.value)
            else:
                opaque = True
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and through(n.func.value):
            if n.func.attr == "update" or n.func.attr == "setdefault" and n.args and not literal(n.args[0]):
                opaque = True
            elif n.func.attr == "setdefault" and n.args:
                written.append(n.args[0].value)
        elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name) and n.target.id in names:
            opaque = True
    return list(dict.fromkeys(written)), opaque


def _ctx_key_seams(plan, pieces, failed):
    """A ctx["objects"] or ctx["values"] key a step reads that no earlier step writes (in the joined run it would
    make a stand-in, which the plan-level check counts as a failure), every objects seam in plan order before the
    values ones. A channel isn't judged from the first step that writes it in a way whose keys can't be read
    (ctx_keys' opaque: the whole dict, update(), a computed key) on, that step's own reads included: a false seam
    fails a good example at the gate (SEAMS_FAIL), while a value really missing still shows in the joined run.
    On the joins as they ran that changes nothing (0 of 111; bw-10's ROCK_COUNT seam stays). With a step failed in
    turn, 7 of check_join_parity's 463 task joins lose a seam for a key the failed step should have made, after an
    earlier ctx["objects"] = {} or a computed key. Writes through a name bound to the channel count too
    (_bound_writes), here only: provides_missing still reads ctx_keys alone."""
    seams = []
    for channel in CTX_CHANNELS:
        written, opaque = {}, False  # opaque: an earlier step wrote keys that can't be read
        for p in pieces:
            w, r, o = ctx_keys(p.tree, channel)
            bw, bo = _bound_writes(p.tree, channel)
            w += [k for k in bw if k not in w]
            opaque = opaque or o or bo  # this step's own such write counts for its own reads too
            for k in r:
                if not opaque and k not in written and k not in w:
                    why = " (the step that should have made it failed)" if failed else ""
                    seams.append(_seam("ctx_key_missing", "%s reads ctx[\"%s\"][%r], which no earlier step registers%s"
                                       % (p.sid, channel, k, why), p.sid))
            for k in w:
                written.setdefault(k, p.sid)
    return seams


# ---------------------------------------------------------------- uses / provides

_TOKEN = re.compile(r"`([^`]+)`|\"([^\"]{1,80})\"|'([^']{1,80})'|([\w./-]+\.\w+|[A-Za-z_]\w*(?:\(\))?)")
_KEY_IN = re.compile(r"\[\s*['\"]([^'\"]+)['\"]\s*\]")


def _code_like(tok):
    """A bare word that looks like a name in code: snake_case, CamelCase inside, a dotted name, or a path. A word
    starting with a digit isn't one; isdecimal, not isdigit, since Go's unicode.IsDigit is the decimal digits and
    isdigit also counts 128 others such as superscripts (the Nov 4 parity run's reseeded uses lines reached one:
    ²x_y10.123/abcStore.alla/b.py). No stored reply, task, eval file or generated example has a word starting so."""
    if not tok or tok[0].isdecimal():
        return False
    if "/" in tok or re.search(r"\.(py|js|ts|json|blend|png|css|html)$", tok):
        return True
    if "." in tok:
        return all(len(x) > 1 and re.fullmatch(r"[A-Za-z_]\w*", x) for x in tok.split("."))
    return "_" in tok.strip("_") or bool(re.search(r"[a-z][A-Z]", tok))


def uses_names(chunk):
    """Code-like names in a piece of a uses line: quoted or backticked ones, and bare snake_case, dotted,
    CamelCase or path-like words, and calls (name())."""
    out = []
    for m in _TOKEN.finditer(chunk):
        quoted = m.group(1) or m.group(2) or m.group(3)
        tok = (quoted or m.group(4) or "").strip()
        keys = _KEY_IN.findall(tok)
        if keys:  # ctx["objects"]["table"] -> table
            out.append(keys[-1])
            continue
        call = tok.endswith("()")
        tok = tok.rstrip(".,;:")
        tok = tok[:-2] if tok.endswith("()") else tok
        if re.fullmatch(r"s\d+", tok) or len(tok) < 2:
            continue
        if quoted or (call and re.fullmatch(r"[A-Za-z_]\w*", tok)) or _code_like(tok):
            out.append(tok)
    return list(dict.fromkeys(out))


_USES_REF = re.compile(r"\bs[1-9]\d?\b")  # a step id (Go: stepRefRe through pyMatches)
_USES_OPENERS, _USES_CLOSERS, _USES_DASHES, _USES_QUOTES = "([{", ")]}", "-–—", "\"'`"
_USES_CONNECT = re.compile(r"(?:\s|[,/&+]|and|or)*|[-–—]")  # fullmatch: the text between two refs of a run
_USES_PREFIX = re.compile(r"[^\w]*(?:(?:[Ff]rom|[Ss]teps?)[^\w]+)?")  # fullmatch: before a prefix item's first run
_USES_OPEN = re.compile(r"\s*[)\]}]*\s*(?::|：|->|=>|→|[-–—]\s)")  # match: after an open run
_USES_BARE = re.compile(r"(?:\s|[,/&+.\-–—]|and|or)*")  # fullmatch: a bare item's depth-0 text
_USES_ENDS = re.compile(r"[\s.]*")  # fullmatch: after the ref an item ends with
_USES_RANGE_MAX = 9
_USES_POSSESSIVES = ("'s", "’s")  # rule 5b
_USES_BREAK_WORDS = ("plus",)  # rule 6b
_USES_SKIP_WORDS = _USES_BREAK_WORDS + ("the", "a", "an")  # rule 6b: passed on the way to the name after a break
_USES_CUE = ("with",)  # rule 7: the word after a suffix run that lets a break cut
_USES_CUE_OWNERS = ("its", "their")  # rule 7: the word after the cue
_SETTINGS_NAME = re.compile(r"SETTINGS_(s[1-9][0-9]?)")  # uses_seams: fullmatch on a name (Go: settingsNameRe, ^...$)
# _settings_keys: SETTINGS_sN and its subscripts (Go: settingsSubRe, notWord + `(SETTINGS_s...)` through pyMatches)
_SETTINGS_SUB = re.compile(r"(?<![\w])SETTINGS_(s[1-9][0-9]?)((?:\s*\[\s*['\"][^'\"]+['\"]\s*\])+)")


def _uses_w(ch):
    """re's \\w for one character (Go: isPyWord, r == '_' || unicode.IsLetter(r) || unicode.IsNumber(r))."""
    return ch == "_" or ch.isalnum()


def _uses_scan(uses):
    kind, depth, d = [], [], 0
    for ch in uses:
        if ch in _USES_OPENERS:
            d += 1
            kind.append("o")
        elif ch in _USES_CLOSERS and d > 0:
            d -= 1
            kind.append("c")
        else:
            kind.append("x")
        depth.append(d)
    return kind, depth


class _UsesGroup:
    __slots__ = ("steps",)

    def __init__(self, steps):
        self.steps = steps


def _uses_runs(uses, refs):
    """[[steps, start, end]] from refs [(start, end, sid)] in order (rule 4)."""
    runs = []
    for s, e, sid in refs:
        if runs:
            last = runs[-1]
            gap = uses[last[2]:s]
            if _USES_CONNECT.fullmatch(gap) or last[0] == [sid]:
                if len(gap) == 1 and gap in _USES_DASHES:
                    a, b = int(last[0][-1][1:]), int(sid[1:])
                    if a < b <= a + _USES_RANGE_MAX:
                        for n in range(a + 1, b):
                            if "s%d" % n not in last[0]:
                                last[0].append("s%d" % n)
                if sid not in last[0]:
                    last[0].append(sid)
                last[2] = e
                continue
        runs.append([[sid], s, e])
    return runs


def _uses_bracket_end(kind, depth, o, b, level):
    """Just after the closer of the bracket opened at o (the first closer after o of depth level), else b."""
    for c in range(o + 1, b):
        if kind[c] == "c" and depth[c] == level:
            return c + 1
    return b


def _uses_marks(uses, kind, depth, a, b, level):
    """Rule 6: the marks' starts in [a, b)."""
    out, n = [], len(uses)
    for i in range(a, b):
        if kind[i] != "x" or depth[i] > level:
            continue
        ch = uses[i]
        if (ch == "a" and i + 3 <= b and uses.startswith("and", i) and (i == 0 or not _uses_w(uses[i - 1]))
                and (i + 3 == n or not _uses_w(uses[i + 3]))):
            out.append(i)
        elif ch in _USES_DASHES and 0 < i < n - 1 and uses[i - 1].isspace() and uses[i + 1].isspace():
            out.append(i)
    return out


def _uses_word_at(uses, i, b, words):
    """The word of words (ASCII, lower case) at i, in any ASCII case, ending by b, with no \\w character just before
    or just after it; else None."""
    for w in words:
        s = uses[i:i + len(w)]
        if (i + len(w) <= b and s.isascii() and s.lower() == w and (i == 0 or not _uses_w(uses[i - 1]))
                and (i + len(w) == len(uses) or not _uses_w(uses[i + len(w)]))):
            return w
    return None


def _uses_name_word(uses, j, b):
    """Rules 5b and 6b: the word at j (the characters up to the next white space, or b) holds a name."""
    k = j
    while k < b and not uses[k].isspace():
        k += 1
    return k > j and bool(uses_names(uses[j:k]))


def _uses_breaks(uses, kind, depth, a, b, level):
    """Rule 6b: the breaks' starts in [a, b)."""
    out, memo = [], {}

    def named_from(j):  # past white space, break words and articles, the next word holds a name
        passed = []
        while True:
            while j < b and uses[j].isspace():
                j += 1
            if j in memo:
                r = memo[j]
                break
            w = _uses_word_at(uses, j, b, _USES_SKIP_WORDS)
            if w is None:
                r = memo[j] = _uses_name_word(uses, j, b)
                break
            passed.append(j)
            j += len(w)
        for x in passed:
            memo[x] = r
        return r

    for i in range(a, b):
        if kind[i] != "x" or depth[i] > level:
            continue
        w = _uses_word_at(uses, i, b, _USES_BREAK_WORDS)
        if w is not None and named_from(i + len(w)):
            out.append(i)
    return out


def _uses_cued(uses, lo, hi):
    """Rule 7: the first word after a suffix run's end lo (past white space and closers, before hi) is "with", and the
    word after it (past white space) "its" or "their"."""
    j = lo
    while j < hi and (uses[j].isspace() or uses[j] in _USES_CLOSERS):
        j += 1
    w = _uses_word_at(uses, j, hi, _USES_CUE)
    if w is None:
        return False
    j += len(w)
    while j < hi and uses[j].isspace():
        j += 1
    return _uses_word_at(uses, j, hi, _USES_CUE_OWNERS) is not None


def _uses_pair(uses, a, b, s, e):
    """Rule 5b for a run [s, e): a possessive right after it, or white space and a word with a name, not after
    "from"."""
    for p in _USES_POSSESSIVES:
        if uses.startswith(p, e) and e + len(p) <= b and (e + len(p) == len(uses) or not _uses_w(uses[e + len(p)])):
            return True
    j = e
    while j < b and uses[j].isspace():
        j += 1
    if j == e or j == b or not _uses_name_word(uses, j, b):
        return False
    k = s
    while k > a and uses[k - 1].isspace():
        k -= 1
    w = k
    while w > a and _uses_w(uses[w - 1]):
        w -= 1
    before = uses[w:k] if k < s else ""
    return not (before.isascii() and before.lower() == "from")


def _uses_quiet(uses, e, s):
    """Rule 5b: between a run's end e and the next run's start s, past a possessive right after the run, white space
    and the word after it (the characters up to the next white space), uses_names finds no name."""
    j = e
    for p in _USES_POSSESSIVES:
        if uses.startswith(p, j) and j + len(p) <= s:
            j += len(p)
            break
    while j < s and uses[j].isspace():
        j += 1
    while j < s and not uses[j].isspace():
        j += 1
    return not uses_names(uses[j:s])


class _UsesItem:
    __slots__ = ("start", "end", "semi", "owner", "has_ref", "prefix", "pair", "last_open", "ends_with_id", "bare",
                 "first", "last")

    def __init__(self, start, end, semi):
        self.start, self.end, self.semi = start, end, semi
        self.owner = None  # a _UsesGroup (or None) per character of the item
        self.has_ref = self.prefix = self.pair = self.last_open = self.ends_with_id = self.bare = False
        self.first = self.last = None  # its first and last run's groups


def _uses_read(uses, it, refs, kind, depth):
    a, b = it.start, it.end
    it.has_ref = True
    it.ends_with_id = bool(_USES_ENDS.fullmatch(uses[refs[-1][1]:b]))
    rest, k = [], 0
    for i in range(a, b):  # rule 9's text: kind "x" at depth 0, outside the refs
        while k < len(refs) and refs[k][1] <= i:
            k += 1
        if not (k < len(refs) and refs[k][0] <= i) and kind[i] == "x" and depth[i] == 0:
            rest.append(uses[i])
    it.bare = bool(_USES_BARE.fullmatch("".join(rest)))
    dmin = min(depth[s] for s, _, _ in refs)
    runs = _uses_runs(uses, [r for r in refs if depth[r[0]] == dmin])
    it.prefix = bool(_USES_PREFIX.fullmatch(uses[a:runs[0][1]]))
    it.pair = (not it.prefix and len(runs) >= 2 and not uses_names(uses[a:runs[0][1]])  # rule 5b
               and all(_uses_pair(uses, a, b, r[1], r[2]) for r in runs)
               and all(_uses_quiet(uses, runs[k][2], runs[k + 1][1]) for k in range(len(runs) - 1)))
    opened = [bool(_USES_OPEN.match(uses, r[2], b)) for r in runs]
    marks = _uses_marks(uses, kind, depth, a, b, dmin)
    breaks = _uses_breaks(uses, kind, depth, a, b, dmin)
    groups = [_UsesGroup(r[0]) for r in runs]
    cuts = []
    for k in range(len(runs) - 1):  # rule 7
        lo, hi = runs[k][2], runs[k + 1][1]
        ms = [m for m in marks if lo <= m < hi]
        bs = [x for x in breaks if lo <= x < hi]
        if it.prefix or it.pair or opened[k]:
            cuts.append(ms[-1] if ms else hi)
        elif ms:
            cuts.append(ms[0])
        elif bs and _uses_cued(uses, lo, hi):
            cuts.append(bs[0])
        else:
            j = lo
            while j < hi and kind[j] == "x" and uses[j].isspace():
                j += 1
            if j < hi and kind[j] == "o" and depth[j] == dmin + 1:
                cuts.append(_uses_bracket_end(kind, depth, j, b, dmin))
            else:
                cuts.append(lo)
    owner = [None] * (b - a)
    for g, s, e in zip(groups, [a] + cuts, cuts + [b]):
        for i in range(s, e):
            owner[i - a] = g
    deep = [r for r in refs if depth[r[0]] > dmin]
    o = a
    while deep and o < b:  # rule 8
        if kind[o] == "o" and depth[o] == dmin + 1:
            e = _uses_bracket_end(kind, depth, o, b, dmin)
            held = [r for r in deep if o < r[0] < e]
            if held:
                steps = []
                for r in _uses_runs(uses, held):
                    steps += [x for x in r[0] if x not in steps]
                g = _UsesGroup(steps)
                for i in range(o, e):
                    owner[i - a] = g
            o = e
        else:
            o += 1
    it.owner = owner
    it.first, it.last, it.last_open = groups[0], groups[-1], opened[-1]


def _uses_chunks(uses):
    r"""[(steps, text)] in the line's order; [] when the line names no step. steps is a list of step ids (several: a
    group), text what uses_names reads. Since the user's answer to contract question 4 (Nov 5) a uses line is a list of
    items, each given to the step id in it, or after it ("X from s1", "X (s1)"), or to an "sN:" lead before it; until
    then the line was cut at each id, and the text before an id's successor was that id's, so "a from s1, b from s2"
    read b as s1's. A second round the same day (round 8, the user's yes) fixed the two forms the first read worse
    than the reader before it: two ids in one item after a lead word, read as "<id>'s name" or "<id> name" pairs
    ("Uses s1's a with s2's b", rule 5b), and a list broken by plus after "with its" ("a from s1 with its b plus c from
    s2", rules 6b and 7). Round 8's other changes were taken out the same day, and these two narrowed (the items
    around a pair item, a pair with a name before the next id, also and then, and a bare "with" read as round 7's
    reader read them), since the wider forms read lines worse than it (worker-model/datagen/DESIGN.md).
    Go's usesChunks (app/hydra_assemble.go) gives the same chunks on every line (check_join_parity). Positions are
    code points (Go: byte offsets of whole runes); every character the rules compare is one code point, and every one
    rules 5b, 6b and 7's cue compare is ASCII but white space (str.isspace), \w (_uses_w) and the ’ of ’s, so their
    words are matched in ASCII case only.

    1. Depth: depth[i] is the bracket depth after character i; ( [ { add one, ) ] } take one away when one is open.
       kind[i] is "o" an opener, "c" a closer that closed one, "x" anything else. Quotes aren't tracked.
    2. Items: the line is cut at each "," and ";" of kind "x" at depth 0 (the cut characters are in no item); a piece
       that is all white space is no item. Each ";" starts a new ;-group.
    3. Refs: \bs[1-9]\d?\b over the whole line (Go: pyMatches(stepRefRe)); an item's refs are those inside it. dmin is
       the least depth among them: refs at dmin are shallow, the rest deep.
    4. Runs: a shallow ref joins the run before it when the text between fully matches _USES_CONNECT (white space,
       , / & + and or; or exactly one dash), or when that run is this same single step. One dash from sA to sB with
       A < B <= A + _USES_RANGE_MAX adds sA+1 .. sB-1 too ("s2-s6"). A run keeps each step once, in written order.
    5. Kinds: an item is a prefix item when the text before its first run fully matches _USES_PREFIX ("s1: x", "from
       s1 - x", "**s1**: x"); a run is open when _USES_OPEN matches after it (":", an arrow, a spaced dash). Every run
       of a prefix item or of a pair item (5b), and an open run, is forward; the others are suffix runs.
    5b. Pairs: an item that isn't a prefix item, has two or more runs and no name in the text before its first run
       (uses_names finds none there) is a pair item when every run is followed either by a possessive ('s or ’s
       right after the run, inside the item, with no \w character after it) or by white space and then a word (the
       characters up to the next white space, inside the item) that holds a name (uses_names finds one in it), and,
       for the second form, the word just before the run (its \w characters, past white space only, inside the item)
       isn't "from" in any ASCII case; and when, between each run and the next, past a possessive right after the run,
       white space and the word after it (the characters up to the next white space), uses_names finds no name ("Uses
       s1's a with s2's b", "the s1 a with the s2 b", "Combines s1 a & s2 b"; not "chair from s2 table_obj from s1
       rug_obj", not "Extends s1's room with lamp_obj from s2's output", and not "Uses s1 -> a s2 -> b", whose runs
       are open). A pair item is no prefix item for rule 10: the items around it read as they would without 5b.
    6. Marks: an "and" with no \w character beside it, and a dash with white space on both sides, of kind "x" at
       depth dmin or less.
    6b. Breaks: of kind "x" at depth dmin or less inside the item, the word plus (ASCII letters in any case, with no \w
       character just before or just after it), when the first word after it holds a name: past white space and any
       plus and the words the, a, an (the same word test), the characters up to the next white space, inside the
       item, in which uses_names finds a name ("plus slat_objs", "plus the slat_objs"; not "plus its seat_rail" or
       "plus, from s2"; also and then are no breaks).
    7. Runs' text: the first run's starts at the item's start, the last's ends at its end. Between run k and k+1 the
       cut is, for a forward run k, the last mark between them, else run k+1's start; for a suffix run k, the first
       mark between them, else, when the first word after run k (past white space and closers ) ] }) is "with" and
       the word after it (past white space) "its" or "their", both in any ASCII case, the first break between them ("a
       from s1 with its b plus c from s2"; not "Joins a from s1 with b plus c from s2"), else the end of a bracket
       right after run k ("a from s1 (for the camera) b from s2"), else run k's end.
    8. Deep brackets: a bracket whose opener has depth dmin + 1 and that holds a deep ref goes whole to its refs'
       steps, as one group ("base_plate from s1 (s2 failed, so bolt_holes is a stand-in)").
    9. Bare items: an item with a ref whose depth-0 text outside its refs fully matches _USES_BARE ("s2, s3
       (merged)") shares the last group of the item just before it, when that one is in the same ;-group and ends with
       an id (_USES_ENDS after its last ref); its steps are added to that group. In line order.
    10. Items with no ref, within their ;-group: the nearest earlier item with a ref, if it is a prefix item or its
       last run is open, gives its last group; else the nearest later item with a ref, unless it is a prefix item,
       gives its first group ("sofa, table from s2"); else the item is no step's ("scene_root; s1: x").
    11. Chunks: each item's characters are cut where their group changes and just before each ref (before its
       opening quote when the same quote stands right before and after it, '{"s1": ...}', and that quote takes the
       ref's group), but not after "/" or "." (src/s2/legs.py, x.s2). Characters with no group, and empty texts, give
       no chunk.
    """
    uses = uses or ""
    refs = [(m.start(), m.end(), m.group(0)) for m in _USES_REF.finditer(uses)]
    if not refs:
        return []
    kind, depth = _uses_scan(uses)
    items, start, semi = [], 0, 0
    for i in [i for i, ch in enumerate(uses) if ch in ",;" and kind[i] == "x" and depth[i] == 0] + [len(uses)]:
        if uses[start:i].strip():
            it = _UsesItem(start, i, semi)
            mine = [r for r in refs if start <= r[0] and r[1] <= i]
            if mine:
                _uses_read(uses, it, mine, kind, depth)
            items.append(it)
        if i < len(uses) and uses[i] == ";":
            semi += 1
        start = i + 1
    for k in range(1, len(items)):  # rule 9
        it, prev = items[k], items[k - 1]
        if it.has_ref and it.bare and prev.has_ref and prev.ends_with_id and prev.semi == it.semi:
            shared = prev.last
            for g in it.owner:
                if g is not shared:
                    shared.steps += [x for x in g.steps if x not in shared.steps]
            it.owner = [shared] * len(it.owner)
            it.first = it.last = shared
    for k, it in enumerate(items):  # rule 10
        if it.has_ref:
            continue
        before = next((items[j] for j in range(k - 1, -1, -1) if items[j].has_ref and items[j].semi == it.semi), None)
        after = next((items[j] for j in range(k + 1, len(items)) if items[j].has_ref and items[j].semi == it.semi), None)
        g = None
        if before is not None and (before.prefix or before.last_open):
            g = before.last
        elif after is not None and not after.prefix:
            g = after.first
        if g is not None:
            it.owner = [g] * (it.end - it.start)
    cut_at = set()  # rule 11
    for s, e, _ in refs:
        if s > 0 and uses[s - 1] in "/.":
            continue
        if s > 0 and e < len(uses) and uses[s - 1] == uses[e] and uses[e] in _USES_QUOTES:
            cut_at.add(s - 1)
            it = next(x for x in items if x.start <= s < x.end)  # the opening quote goes with its ref
            if it.owner is not None and it.start <= s - 1:
                it.owner[s - 1 - it.start] = it.owner[s - it.start]
        else:
            cut_at.add(s)
    out = []
    for it in items:
        if it.owner is None:
            continue
        cur, s = None, it.start
        for i in range(it.start, it.end + 1):
            g = it.owner[i - it.start] if i < it.end else None
            if i < it.end and g is cur and i not in cut_at:
                continue
            if cur is not None and i > s:
                out.append((list(cur.steps), uses[s:i]))
            cur, s = g, i
    return out


def _uses_hay(d):
    return ((d.handoff.provides if d.handoff else "") + "\n" + (d.code or "") + "\n" +
            "\n".join(f.path + "\n" + f.body for f in d.files) + "\n" + (d.section or d.body or ""))


def _uses_found(name, hay):
    if "/" in name or re.search(r"\.\w{1,5}$", name) and not re.fullmatch(r"[A-Za-z_][\w.]*", name):
        return name in hay  # a path
    return all(re.search(r"\b%s\b" % re.escape(x), hay) for x in name.split("."))  # a name, or a dotted one


def _settings_keys(text, chunks=None):
    """Round 8's keys: {key: sN} for each key a uses line has only in subscripts of SETTINGS_sN, all of one step:
    SETTINGS_s1["width"], SETTINGS_s1['colors']['shade']. A key that uses_names also finds elsewhere in the line, or
    that sits in chains of two steps, stays with its chunk ("width_m from s2 (overrides SETTINGS_s1["width_m"])" keeps
    width_m with s2). Elsewhere is read twice, with every such subscript chain blanked out (one space each): on the
    whole line, which also holds the text no chunk reaches, and on each of the line's chunks (_uses_chunks(text),
    which uses_seams passes in; None reads them here), the pieces the seams read. A quote span on the whole line can
    hide a plain use its chunk shows: in "Uses s2's seat_h; SETTINGS_s1['seat_h'] is s1's default" the blanked line
    gives one quoted name, "s seat_h;   is s1", and the chunk "s2's seat_h" gives seat_h, so seat_h stays with s2
    (Nov 5, round 8's re-check; before it the key went to s1, whose dict held it, and s2 went unchecked). A quote span
    inside one chunk still hides it ("s2's seat_h (a 'seat' height) and SETTINGS_s1['seat_h']": seat_h to s1)."""
    steps_of = {}
    for m in _SETTINGS_SUB.finditer(text):
        for k in _KEY_IN.findall(m.group(2)):
            steps_of.setdefault(k, set()).add(m.group(1))
    if not steps_of:
        return {}
    rest = set(uses_names(_SETTINGS_SUB.sub(" ", text)))
    for _, chunk in _uses_chunks(text) if chunks is None else chunks:
        rest.update(uses_names(_SETTINGS_SUB.sub(" ", chunk)))
    return {k: next(iter(v)) for k, v in steps_of.items() if len(v) == 1 and k not in rest}


def uses_seams(pieces_by_sid, failed):
    """Every "uses" should match a "provides" (heuristic: each code-like name a uses line gives for a step must appear
    in that step's provides line or its piece). The steps are _uses_chunks': each item goes to the step id in it or
    after it, or to an "sN:" lead before it. A group ("from s1 and s2", "s2-s4") is skipped when one of its steps
    failed or isn't in the join (it may have made the name), else a name none of them holds is a seam, written with
    the group as s1/s2; one per piece, steps and name. One step's message is the same as before Nov 5. Since round 8
    (Nov 5) a SETTINGS_sN name, and a key the line has only in subscripts of one step's SETTINGS_sN (_settings_keys),
    is judged against sN alone, wherever it is in the line (the contract gives each step one dict SETTINGS_{sid}, so
    the name carries its step), and skipped only when sN failed or isn't in the join: in a chunk, and, after the
    chunks, in text that goes to no step and in a line with no step id ("SETTINGS_s1, panel_array"). So it also
    judges a SETTINGS_sN the line says it doesn't use, in text no chunk reaches ("table_top from s1, not SETTINGS_s2",
    "SETTINGS_s2 (unused)") and inside a chunk whose group has a failed step ("lamp_shade (not SETTINGS_s1) from s2"
    with s2 failed), where round 7's reader judged nothing: the name gives a seam only when sN has no SETTINGS_sN dict
    of its own (in Blender mode a contract breach), and a key of such a subscript ("table_w from s1, not
    SETTINGS_s2['width']") whenever sN's piece lacks that key, which needs no breach. Accepted as it is (Nov 5, the
    main session's decision): it follows the approved "wherever it is in the line", no stored line has either form,
    and the narrowings tried for the key read more hand-made lines worse than round 7's reader than they fixed."""
    seams = []
    hays = {}

    def hay(s):
        if s not in hays:
            hays[s] = _uses_hay(pieces_by_sid[s])
        return hays[s]

    for sid, p in pieces_by_sid.items():
        if not p.handoff or not p.handoff.uses:
            continue
        seen = set()
        chunks = _uses_chunks(p.handoff.uses)
        keys = _settings_keys(p.handoff.uses, chunks)
        for steps, chunk in chunks:
            skip = any(s in failed or s not in pieces_by_sid for s in steps)
            for name in uses_names(chunk):
                m = _SETTINGS_NAME.fullmatch(name)
                one = m.group(1) if m else keys.get(name)
                if one is not None:  # SETTINGS_sN and its keys are sN's, whatever chunk they are in
                    st = [one]
                    if one in failed or one not in pieces_by_sid:
                        continue
                elif skip:
                    continue
                else:
                    st = steps
                dep = "/".join(st)
                if (dep, name) in seen:
                    continue
                seen.add((dep, name))
                if not any(_uses_found(name, hay(s)) for s in st):
                    seams.append(_seam("uses_unmatched", "%s uses %r from %s, which %s doesn't provide"
                                       % (sid, name, dep, dep), sid))
        for name in uses_names(p.handoff.uses):  # text no chunk reaches, and a line with no step id
            m = _SETTINGS_NAME.fullmatch(name)
            one = m.group(1) if m else keys.get(name)
            if one is None or one in failed or one not in pieces_by_sid or (one, name) in seen:
                continue
            seen.add((one, name))
            if not _uses_found(name, hay(one)):
                seams.append(_seam("uses_unmatched", "%s uses %r from %s, which %s doesn't provide"
                                   % (sid, name, one, one), sid))
    return seams


# ---------------------------------------------------------------- files

_MERGEABLE = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _mergeable(tree):
    for n in tree.body:
        if isinstance(n, _MERGEABLE) or is_docstring(n):
            continue
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and assigned_names(n) is not None:
            continue
        return False
    return True


def merge_python(base, parts):
    """A Python file from its full version (or None) and "(part)" blocks [(sid, body)]. The full version stays
    as it is; the parts' new imports go after its imports, and the parts' code (in plan order) before its main
    guard, else at the end. Returns None when a part holds more than imports, defs, classes and constants."""
    trees = []
    for sid, body in parts:
        try:
            tree = ast.parse(body)
        except SyntaxError:
            return None
        if not _mergeable(tree):
            return None
        trees.append((sid, body, tree))
    have, every = Imports(), Imports()
    base_lines, base_tree = [], None
    if base is not None:
        try:
            base_tree = ast.parse(base)
        except SyntaxError:
            return None
        base_lines = source_lines(base)
        for node in base_tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                have.add(node, "base", node.lineno)
                every.add(node, "base", node.lineno)
    chunks = []
    for sid, body, tree in trees:
        lines = source_lines(body)
        written = 0  # statements can share a line: it goes out once
        for node, a, b in segments(body, tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                every.add(node, sid, node.lineno)
            elif not (is_docstring(node) and node is tree.body[0]):
                a = max(a, written + 1)
                if a <= b:
                    chunks.append("\n".join(lines[a - 1:b]))
                    written = b
    new_imports = [t for t, _ in every.lines(skip=set(have.origin))]
    if base_tree is None:
        return "\n\n\n".join(c for c in ["\n".join(new_imports)] + chunks if c.strip()) + "\n"
    body = base_tree.body
    guard = next((n for n in reversed(body) if is_main_guard(n)), None)
    last_import = max((n.end_lineno for n in body if isinstance(n, (ast.Import, ast.ImportFrom))), default=0)
    if not last_import and body and is_docstring(body[0]):
        last_import = body[0].end_lineno
    cut = ([s for n, s, _ in segments(base, base_tree) if n is guard] or [len(base_lines) + 1])[0]
    head = base_lines[:last_import] + new_imports + base_lines[last_import:cut - 1]
    tail = base_lines[cut - 1:]
    mid = "\n\n\n".join(chunks)
    out = "\n".join(head).rstrip("\n") + "\n\n\n" + mid + ("\n\n\n" + "\n".join(tail).strip("\n") if tail else "")
    return out.rstrip("\n") + "\n"


def _module_names(path):
    """The module names a project file can be imported by: every dotted suffix of its path."""
    p = path[:-3] if path.endswith(".py") else path
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return [".".join(parts[k:]) for k in range(len(parts))] if parts else []


def import_seams(files):
    """Every `from X import a` between project files must resolve (X a project file that defines a)."""
    trees = {}
    for f in files:
        if f["path"].endswith(".py"):
            try:
                trees[f["path"]] = ast.parse(f["body"])
            except SyntaxError:
                pass
    modules = {}
    for path in sorted(trees, key=lambda p: -p.count("/")):  # the longest path claims a shared suffix first
        for name in _module_names(path):
            modules.setdefault(name, path)
    tops = {name.split(".")[0] for name in modules}
    defined = {path: set(top_level_names(t)) for path, t in trees.items()}
    seams = []
    for path, tree in trees.items():
        pkg = path.split("/")[:-1]
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base = pkg[:len(pkg) - (node.level - 1)] if node.level - 1 <= len(pkg) else None
                    mod = ".".join((base or []) + ([node.module] if node.module else []))
                    target = modules.get(mod) if base is not None else None
                    if target is None and node.module:
                        seams.append(_seam("import_unresolved", "%s: from %s%s import …: no such project file"
                                           % (path, "." * node.level, node.module)))
                        continue
                else:
                    mod = node.module or ""
                    target = modules.get(mod)
                if target is None:
                    if mod.split(".")[0] in tops and not node.level:
                        seams.append(_seam("import_unresolved", "%s: from %s import …: no such project file" % (path, mod)))
                    continue
                for a in node.names:
                    if a.name != "*" and a.name not in defined[target] and (mod + "." + a.name) not in modules:
                        seams.append(_seam("import_unresolved", "%s: from %s import %s: %s doesn't define %s"
                                           % (path, mod or ".", a.name, target, a.name)))
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] in tops and a.name not in modules and "." in a.name:
                        seams.append(_seam("import_unresolved", "%s: import %s: no such project file" % (path, a.name)))
    return seams


def join_files(pieces):
    """Merge files-mode pieces by path. Returns (files, seams); files: [{path, lang, body, steps}]."""
    by_path, order = {}, []
    for p in pieces:
        for f in p.files:
            if f.path not in by_path:
                by_path[f.path] = []
                order.append(f.path)
            by_path[f.path].append((p.sid, f))
    files, seams = [], []
    for path in order:
        entries = by_path[path]
        full = [(sid, f) for sid, f in entries if not f.part]
        parts = [(sid, f) for sid, f in entries if f.part]
        if len({sid for sid, _ in full}) > 1:
            seams.append(_seam("file_conflict", "%s is written in full by %s" % (path, ", ".join(sid for sid, _ in full)),
                               full[1][0]))
        base = full[0][1].body if full else None
        lang = (full or parts)[0][1].lang
        steps = list(dict.fromkeys(sid for sid, _ in entries))
        if parts:
            merged = merge_python(base, [(sid, f.body) for sid, f in parts]) \
                if path.endswith(".py") or python_lang(lang) else None
            if merged is None:
                seams.append(_seam("part_not_mergeable", "%s: the (part) blocks from %s can't be merged mechanically"
                                   % (path, ", ".join(sid for sid, _ in parts)), parts[0][0]))
                merged = "\n\n".join(([base] if base is not None else []) + [f.body for _, f in parts])
            body = merged
        else:
            body = base
        files.append({"path": path, "lang": lang, "body": body.rstrip("\n"), "steps": steps})
    seams += import_seams(files)
    for f in files:
        if f["path"].endswith(".py"):
            try:
                ast.parse(f["body"])
            except SyntaxError as e:
                seams.append(_seam("join_syntax", "%s doesn't parse after merging (line %s: %s)" % (f["path"], e.lineno, e.msg)))
            else:
                names = [n for n in top_level_names(ast.parse(f["body"]))]
                dups = sorted({n for n in names if names.count(n) > 1})
                if dups and len(f["steps"]) > 1:
                    seams.append(_seam("duplicate_name", "%s defines %s more than once after merging"
                                       % (f["path"], ", ".join(dups))))
    return files, seams


# ---------------------------------------------------------------- the whole plan

def join(plan, outputs, goal="", done_reasons=None, reject_cut=False, editor=None):
    """Validate every piece and join them. done_reasons: plan id -> Ollama done_reason (for reject_cut).

    editor is the hook for the plan's editor pass ("Sections: '# title' plus the sections in plan order, then the
    editor joins them and keeps their content"), which isn't written here because its prompt would be a new
    frozen text. When the result has two or more sections (j.editor_wanted) and nothing fell back, editor(j) is
    called with the joined Joined; a non-empty string it returns becomes j.text (j.edited True, the plain
    concatenation kept in j.raw_text). It must keep the code blocks as they are: the result check runs on them.
    j.parts lists the result's parts in order, for an editor that edits only the sections."""
    steps = plan["steps"]
    lone = len(steps) == 1
    j = Joined(plan_title=planinfo.one_line(plan["title"]))
    modes = {}
    for i, st in enumerate(steps):
        sid = "s%d" % (i + 1)
        mode = planinfo.step_mode(plan, i, goal)
        modes[sid] = mode
        text, status, _ = norm_output(outputs.get(st["id"]))
        if status == "failed":
            j.failed.append(sid)
            j.notes.append("%s (%s) failed, so its part is missing." % (sid, planinfo.one_line(st["title"])))
            continue
        if status == "library":
            p = Piece(sid=sid, mode=mode, text=text, body=go_trim_space(text))
            if mode in ("blender", "python-script"):
                j.seams += wrap_library(p, sid, mode)
                if p.tree is None:
                    j.reasons.append("%s: the library entry can't be joined" % sid)
            else:
                j.reasons.append("%s: a library entry in %s mode has no file path or heading" % (sid, mode))
            j.pieces[sid] = p
            continue
        p = validate_piece(text, mode, sid=sid, deps=planinfo.dep_names(plan, i), lone=lone, step=st,
                           done_reason=(done_reasons or {}).get(st["id"], ""), reject_cut=reject_cut, max_tokens=None)
        j.pieces[sid] = p
        j.reasons += ["%s: %s" % (sid, r) for r in p.reasons()]
        if p.handoff and p.handoff.assumed:
            j.assumptions.append((sid, p.handoff.assumed))
    if j.reasons:
        j.fallback = True
        return j
    if not j.pieces:
        j.fallback = True
        j.reasons.append("no step finished")
        return j

    by_mode = {}
    for sid, p in j.pieces.items():
        by_mode.setdefault(p.mode, []).append(p)
    rendered = {}
    for mode in ("blender", "python-script"):
        if mode in by_mode:
            ps = by_mode[mode]
            script, lm, seams = join_script(plan, ps, mode)
            j.seams += seams
            if mode == "blender":
                j.seams += _ctx_key_seams(plan, ps, j.failed)
            if j.script is None:  # a plan has at most one of the two (planinfo.code_mode)
                j.script, j.linemap = script, lm
                j.script_kind = "run_blender" if mode == "blender" else "run_python"
            run = "blender -b --python script.py" if mode == "blender" else "python3 script.py"
            rendered[mode] = "```python\n%s```\n\nRun it with: %s%s" % (
                script, run, " (what to change is in each step's SETTINGS_ dict)." if mode == "blender" else ".")
    if "files" in by_mode:
        files, seams = join_files(by_mode["files"])
        j.files, j.seams = files, j.seams + seams
        rendered["files"] = "\n\n".join("File: %s\n```%s\n%s\n```" % (f["path"], f["lang"], f["body"]) for f in files)
    j.seams += uses_seams(j.pieces, j.failed)

    for sid, p in j.pieces.items():
        if p.mode == "section":
            j.parts.append({"mode": "section", "steps": [sid], "text": p.section or p.body})
        elif not any(x["mode"] == p.mode for x in j.parts):
            j.parts.append({"mode": p.mode, "steps": [q.sid for q in by_mode[p.mode]], "text": rendered[p.mode]})
    j.text = "\n\n".join(["# " + j.plan_title] + [x["text"] for x in j.parts]).rstrip() + "\n"
    j.editor_wanted = sum(1 for x in j.parts if x["mode"] == "section") > 1
    if editor is not None and j.editor_wanted:
        edited = editor(j)
        if isinstance(edited, str) and go_trim_space(edited):
            j.raw_text, j.text, j.edited = j.text, edited.rstrip() + "\n", True
    return j


# ---------------------------------------------------------------- round 2: a step's part of the last result

def _norm(s):
    return " ".join(re.sub(r"[^\w\s]", " ", (s or "").lower()).split())


def _rename(text, old, new):
    if old == new:
        return text
    return re.sub(r"\b(SETTINGS_|build_)%s\b|\b_%s_" % (old, old),
                  lambda m: (m.group(1) + new) if m.group(1) else "_%s_" % new, text)


def find_part(prev_result, plan, i, mode):
    """The part of last round's result that step i of this round's plan redoes: its build function (and
    settings) or code by the step header's title, its files by the paths its title and instructions name,
    its section by heading. Returns (text, matched); unmatched is the result cut to 6,000 bytes."""
    st = plan["steps"][i]
    sid = "s%d" % (i + 1)
    want = _norm(st["title"])
    skip = sum(_norm(s["title"]) == want for s in plan["steps"][:i])  # steps with the same title get its parts in turn
    if mode in ("blender", "python-script"):
        # Chimera's own lines end a step's part: in blender its main(), in both the main guard (a python-script
        # step may define main() itself, which stays in its part).
        stops = ("def main(", "if __name__") if mode == "blender" else ("if __name__",)
        for b in code_blocks(prev_result):
            lines = b.body.split("\n")
            heads = [(k, m.group(1), m.group(2)) for k, l in enumerate(lines) if (m := _HEADER_RE.match(l))]
            for n, (k, old, title) in enumerate(heads):
                if _norm(title) != want:
                    continue
                if skip:
                    skip -= 1
                    continue
                end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
                for e in range(k + 1, end):
                    if lines[e].startswith(stops):
                        end = e
                        break
                part = "\n".join(lines[k + 1:end]).strip("\n")  # the step's own code, without Chimera's header
                if mode == "blender" and not re.search(r"(?m)^SETTINGS_%s\s*[:=]" % old, part):
                    settings = _settings_of(b.body, old)  # a result joined with every SETTINGS_ dict at the top
                    if settings:
                        part = settings + "\n\n\n" + part
                return _rename(part, old, sid), True
    elif mode == "files":
        paths = list(dict.fromkeys(m.group(0) for m in planinfo.PATH_RE.finditer(st["title"] + "\n" + st["instructions"])))
        lines = prev_result.split("\n")
        found = []
        for b in code_blocks(prev_result):
            j = b.open_line - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            fl = file_line(lines[j]) if j >= 0 else None
            if fl and fl[0] in paths:
                found.append("File: %s%s\n```%s\n%s\n```" % (fl[0], " (part)" if fl[1] else "", b.lang, b.body))
        if found:
            return "\n\n".join(found), True
    elif mode == "section":
        lines = prev_result.split("\n")
        for k, l in enumerate(lines):
            if l.startswith("## ") and _norm(l[3:]) == want:
                if skip:
                    skip -= 1
                    continue
                end = next((e for e in range(k + 1, len(lines)) if lines[e].startswith(("# ", "## "))), len(lines))
                return "\n".join(lines[k:end]).strip(), True
    return truncate(prev_result, T.CONTRACT_ROUND2_CUT), False


def _settings_of(script, sid):
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return ""
    lines = script.split("\n")
    for node, a, b in segments(script, tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and assigned_names(node) == ["SETTINGS_" + sid]:
            return "\n".join(lines[a - 1:b])
    return ""
