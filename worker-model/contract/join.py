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
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import planinfo
from .goport import code_blocks, go_trim_space, python_lang, truncate
from .linemap import LineMap
from .today import norm_output
from .validate import (Issue, Piece, assigned_names, ctx_keys, file_line, is_docstring, is_main_guard,
                       top_level_names, validate_piece)
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

def segments(code, tree):
    """[(node, start, end)]: each top-level statement's 1-based line range, with the comment lines just above it
    (and its decorators). A statement sharing a line with the one before (a; b) gets that line's range."""
    lines = code.split("\n")
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
        lines = code.split("\n")
        imports, rest = [], []
        segs = segments(code, tree)
        for node, s, e in segs:
            (imports if isinstance(node, (ast.Import, ast.ImportFrom)) else rest).append((s, e))
        out = [lines[n - 1] for s, e in imports for n in range(s, e + 1)]
        out += ["SETTINGS_%s = {}" % sid, "", "def build_%s(ctx):" % sid]
        body = [lines[n - 1] for s, e in rest for n in range(s, e + 1)]
        out += ["    " + l if l.strip() else l for l in body] or ["    pass"]
        code = "\n".join(out)
        tree = ast.parse(code)
    piece.code, piece.tree, piece.code_line = code, tree, 1
    return seams


def alone_script(piece: Piece, keep_ctx=False, ctx_name="ctx", also=()):
    """A blender piece as data generation runs it alone: its own code with its main guard blanked out (so every
    line keeps the piece's own number), then ctx built at module level as the mode rule's guard builds it, and
    build_sN(ctx). Module-level ctx lets tools/scene_probe.py see what the piece registered. keep_ctx: the script
    follows its dependencies' script, so a module-level dict named ctx_name already there that looks like a ctx
    (an "objects" dict and a "collection") is passed on instead, with what they registered (join_script's guard
    leaves one named ctx). also: more build functions to call after it, in order."""
    lines = piece.code.split("\n")
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
    fresh = '{"scene": bpy.context.scene, "collection": bpy.context.scene.collection, "objects": {}}'
    if keep_ctx:
        c = ctx_name
        tail.append(f'ctx = {c} if isinstance(globals().get("{c}"), dict) and isinstance({c}.get("objects"), dict) '
                    f'and "collection" in {c} else {fresh}')
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
    name = getattr(node, "name", None)
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
        code_lines = p.code.split("\n")
        body, prev_end, dropped = [], None, False
        for node, a, b in segments(p.code, p.tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.add(node, p.sid, node.lineno)
                dropped = True
            elif is_docstring(node) or is_main_guard(node):
                dropped = True  # the piece's own docstring and run-alone guard aren't part of the joined script
            else:
                part, name = _part_of(node, p.sid, blender)
                # blank lines before it: the piece's own (at most 2) when nothing was left out in between, else 2
                gap = 2 if prev_end is None or dropped else min(2, a - prev_end - 1)
                body.append((code_lines, a, b, part, name, gap))
                prev_end, dropped = b, False
                if not blender and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main":
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
                      "    ctx = {\"scene\": scene, \"collection\": collection, \"objects\": {}}"]
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


def _ctx_key_seams(plan, pieces, failed):
    """A ctx["objects"] key a step reads that no earlier step writes (in the joined run it would make a
    stand-in, which the plan-level check counts as a failure)."""
    seams, written = [], {}
    for p in pieces:
        w, r = ctx_keys(p.tree)
        for k in r:
            if k not in written and k not in w:
                why = " (the step that should have made it failed)" if failed else ""
                seams.append(_seam("ctx_key_missing", "%s reads ctx[\"objects\"][%r], which no earlier step registers%s"
                                   % (p.sid, k, why), p.sid))
        for k in w:
            written.setdefault(k, p.sid)
    return seams


# ---------------------------------------------------------------- uses / provides

_TOKEN = re.compile(r"`([^`]+)`|\"([^\"]{1,80})\"|'([^']{1,80})'|([\w./-]+\.\w+|[A-Za-z_]\w*(?:\(\))?)")
_KEY_IN = re.compile(r"\[\s*['\"]([^'\"]+)['\"]\s*\]")


def _code_like(tok):
    """A bare word that looks like a name in code: snake_case, CamelCase inside, a dotted name, or a path."""
    if not tok or tok[0].isdigit():
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


def _uses_chunks(uses):
    """[(steps, text)]: a uses line split at each step it names; text before the first goes with the first."""
    refs = list(re.finditer(r"\bs[1-9]\d?\b", uses))
    if not refs:
        return []
    out = []
    for k, m in enumerate(refs):
        end = refs[k + 1].start() if k + 1 < len(refs) else len(uses)
        start = 0 if k == 0 else m.start()
        out.append(([m.group(0)], uses[start:end]))
    return out


def uses_seams(pieces_by_sid, failed):
    """Every "uses" should match a "provides" (heuristic: each code-like name a uses line gives for a step
    must appear in that step's provides line or its piece)."""
    seams = []
    for sid, p in pieces_by_sid.items():
        if not p.handoff or not p.handoff.uses:
            continue
        for steps, chunk in _uses_chunks(p.handoff.uses):
            dep = steps[0]
            if dep in failed or dep not in pieces_by_sid:
                continue
            d = pieces_by_sid[dep]
            hay = ((d.handoff.provides if d.handoff else "") + "\n" + (d.code or "") + "\n" +
                   "\n".join(f.path + "\n" + f.body for f in d.files) + "\n" + (d.section or d.body or ""))
            for name in uses_names(chunk):
                if "/" in name or re.search(r"\.\w{1,5}$", name) and not re.fullmatch(r"[A-Za-z_][\w.]*", name):
                    found = name in hay  # a path
                else:  # a name, or a dotted one (Store.all: class Store with a method all)
                    found = all(re.search(r"\b%s\b" % re.escape(x), hay) for x in name.split("."))
                if not found:
                    seams.append(_seam("uses_unmatched", "%s uses %r from %s, which %s doesn't provide"
                                       % (sid, name, dep, dep), sid))
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
        base_lines = base.split("\n")
        for node in base_tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                have.add(node, "base", node.lineno)
                every.add(node, "base", node.lineno)
    chunks = []
    for sid, body, tree in trees:
        lines = body.split("\n")
        for node, a, b in segments(body, tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                every.add(node, sid, node.lineno)
            elif not (is_docstring(node) and node is tree.body[0]):
                chunks.append("\n".join(lines[a - 1:b]))
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
