"""The piece validator: does one worker reply keep the contract's shape for its mode?

    from contract.validate import validate_piece
    p = validate_piece(reply, "blender", sid="s2", deps=["s1"])
    p.ok            # no errors at all
    p.contract_ok   # no contract-shape errors (a syntax error alone keeps this True)
    p.issues        # Issue(level "error" | "warn", code, message, line)
    p.handoff       # Handoff(provides, uses, assumed) or None
    p.code, p.tree  # blender / python-script: the python block and its ast
    p.files         # files: FilePart(path, part, lang, body)

"error" means the piece breaks a mode rule (joining it would fall back to a model combine) or can't
work at all (a syntax error, a reply cut at its length limit). "warn" is a quality note for measuring.
The rules are the plan's "Validation of every piece" plus what the mode rules say in words; each
check below names the rule it comes from. Line numbers in issues are 1-based lines of the reply.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .goport import BPY_IMPORT, Block, code_blocks, estimate_tokens, go_trim_space, python_lang

MAX_PIECE_TOKENS = 3500  # the plan's data filter: "targets over 3,500 tokens" are rejected

# Errors that mean the piece doesn't keep the contract's shape (what "contract kept" counts).
CONTRACT_CODES = frozenset([
    "empty", "cut_off", "too_long", "harmony_leftover",
    "handoff_missing", "handoff_many", "handoff_unclosed", "handoff_shape", "handoff_not_last", "uses_not_dependency",
    "no_python_block", "many_python_blocks", "unclosed_block", "top_level_code", "wrong_step_names",
    "no_settings", "many_settings", "settings_not_dict", "no_build", "many_build", "no_main_guard",
    "guard_not_build", "saves_or_renders", "deletes_scene", "runs_on_import",
    "no_file_blocks", "no_file_line", "no_heading",
])

# Warnings for a near-miss of the contract's written form that joining reads anyway. A piece with one keeps the
# contract (contract_ok) but isn't in its exact form (form_ok False): fine for Chimera to join, not for a
# training target, which must teach the exact form.
FORM_CODES = frozenset(["handoff_unfenced", "handoff_unlabelled", "handoff_unclosed_end", "handoff_twice",
                        "file_line_decorated"])


@dataclass
class Issue:
    level: str  # "error" or "warn"
    code: str
    message: str
    line: int = 0  # 1-based line of the reply, 0 if none

    def to_dict(self):
        return {"level": self.level, "code": self.code, "message": self.message, "line": self.line}


@dataclass
class Handoff:
    provides: str
    uses: str
    assumed: str

    def lines(self):
        """The three lines as a worker wrote them, "none" for an empty one."""
        return ["provides: " + (self.provides or "none"), "uses: " + (self.uses or "none"),
                "assumed: " + (self.assumed or "none")]

    def to_dict(self):
        return {"provides": self.provides, "uses": self.uses, "assumed": self.assumed}


@dataclass
class FilePart:
    path: str
    part: bool
    lang: str
    body: str
    line: int  # 1-based line of the opening fence in the reply


@dataclass
class Piece:
    sid: str
    mode: str
    text: str
    issues: List[Issue] = field(default_factory=list)
    handoff: Optional[Handoff] = None
    body: str = ""  # the reply without its handoff block
    code: Optional[str] = None  # blender / python-script: the python block's body
    code_line: int = 0  # 1-based line of the reply that is the code's line 1
    tree: Optional[ast.Module] = None
    files: List[FilePart] = field(default_factory=list)
    section: Optional[str] = None
    library: bool = False  # a library entry runStep wrote as a bare block (join.py wraps it)

    @property
    def errors(self):
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self):
        return [i for i in self.issues if i.level == "warn"]

    @property
    def ok(self):
        return not self.errors

    @property
    def contract_ok(self):
        return not any(i.code in CONTRACT_CODES for i in self.errors)

    @property
    def form_ok(self):
        """No errors, and the contract's exact written form (no FORM_CODES warning): what data generation keeps."""
        return self.ok and not any(i.code in FORM_CODES for i in self.issues)

    def reasons(self):
        return ["%s: %s" % (i.code, i.message) for i in self.errors]

    def to_dict(self):
        return {"sid": self.sid, "mode": self.mode, "ok": self.ok, "contract_ok": self.contract_ok,
                "form_ok": self.form_ok,
                "issues": [i.to_dict() for i in self.issues],
                "handoff": self.handoff.to_dict() if self.handoff else None,
                "files": [{"path": f.path, "part": f.part, "lang": f.lang} for f in self.files]}


# ---------------------------------------------------------------- handoff

_HANDOFF_KEY = re.compile(r"^\s*(provides|uses|assumed)\s*:\s*(.*?)\s*$", re.I)
_NONE = re.compile(r"^(none|nothing|n/a|-)?\.?$", re.I)
STEP_REF = re.compile(r"\bs([1-9]\d?)\b")
_NEGATED = re.compile(r"^(none|nothing|no\b|not\b)", re.I)
HANDOFF_LINE_MAX = 300  # "one short line each": longer is a warning
# The near-miss forms read leniently (warnings, see parse_handoff): a label line just above unfenced key lines
# ("handoff", "Handoff:", "**Handoff**", "### Handoff", "`handoff`"), and the languages a plain block may name.
_HANDOFF_LABEL = re.compile(r"^\s*(?:#{1,6}\s*)?[*_`]*\s*handoff\s*:?\s*[*_`]*\s*:?\s*$", re.I)
_PLAIN_LANGS = ("", "text", "txt", "plain", "plaintext", "yaml", "yml")


def _value(v):
    v = go_trim_space(v)
    return "" if _NONE.match(v) else v


_ALL_KEYS = {"provides", "uses", "assumed"}


def _only_key_lines(body):
    """The block body's non-blank lines are all provides/uses/assumed lines, and every key is there."""
    lines = [l for l in body.split("\n") if go_trim_space(l)]
    keys = [m.group(1).lower() for l in lines if (m := _HANDOFF_KEY.match(l))]
    return len(keys) == len(lines) and set(keys) == _ALL_KEYS


def _unfenced_handoff(text, blocks):
    """The handoff written without its fence, as qwen3:8b and qwen3:4b-instruct did on Oct 29: the reply's last
    non-blank lines, after every code block, are provides/uses/assumed lines with every key there (blank lines
    between them are fine), maybe under a "handoff" label line. Returns a Block standing for those lines (and
    the label), or None."""
    lines = text.split("\n")
    after = max([b.close_line if b.closed else len(lines) for b in blocks], default=-1)  # an open block runs to the end
    k, first, last, keys = len(lines) - 1, None, None, []
    while k > after:
        if go_trim_space(lines[k]):
            m = _HANDOFF_KEY.match(lines[k])
            if not m:
                break
            keys.append(m.group(1).lower())
            first, last = k, (k if last is None else last)
        k -= 1
    if set(keys) != _ALL_KEYS:
        return None
    label = k if k > after and _HANDOFF_LABEL.match(lines[k]) else None
    b = Block("handoff", "", label if label is not None else first)
    b.body, b.closed, b.close_line = "\n".join(lines[first:last + 1]), True, last
    return b


def _key_values(lines):
    """{key: value} of the provides/uses/assumed lines among lines."""
    return {m.group(1).lower(): _value(m.group(2)) for l in lines if (m := _HANDOFF_KEY.match(l))}


def _copy_above(lines, b, same=True):
    """(first, last) 0-based lines of the three key lines written just above block b with no fence (blank lines
    between them fine), maybe under a "handoff" label, ending right above the block's fence (Gemma 4's files replies
    on Oct 30), or None. same: only when their values are the block's, a plain copy (strip_handoff drops it); with
    other values they may be the section's own words, which stay, though the form is still a near miss."""
    k, first, last, keys = b.open_line - 1, None, None, []
    while k >= 0:
        if go_trim_space(lines[k]):
            m = _HANDOFF_KEY.match(lines[k])
            if not m:
                break
            keys.append(m.group(1).lower())
            first, last = k, (k if last is None else last)
        k -= 1
    if sorted(keys) != sorted(_ALL_KEYS) or same and _key_values(lines[first:last + 1]) != _key_values(b.body.split("\n")):
        return None
    return (k if k >= 0 and _HANDOFF_LABEL.match(lines[k]) else first), last


def handoff_blocks(text):
    """(the reply's handoff block(s), form): form is "fenced" (```handoff, the contract's), "plain" (a block with
    no language or a plain-text one, holding only the key lines), "unfenced" (key lines at the very end, maybe
    under a "handoff" label) or "" when there is none. The near-miss forms are read only when no ```handoff
    block exists."""
    all_blocks = code_blocks(text)
    fenced = [b for b in all_blocks if b.lang == "handoff"]
    if fenced:
        return fenced, "fenced"
    plain = [b for b in all_blocks if b.lang in _PLAIN_LANGS and b.closed and _only_key_lines(b.body)]
    if not plain and all_blocks and not all_blocks[-1].closed and all_blocks[-1].lang in _PLAIN_LANGS \
            and _only_key_lines(all_blocks[-1].body):
        plain = all_blocks[-1:]  # a plain block left open at the end (handoff_unclosed_end, below)
    if plain:
        return plain[-1:], "plain"
    b = _unfenced_handoff(text, all_blocks)
    return ([b], "unfenced") if b else ([], "")


def parse_handoff(text):
    """The reply's handoff block, read: (Handoff or None, the handoff Blocks, issues). The Handoff is the last
    block's, read leniently (missing keys are empty); issues say what breaks the shape.

    Besides the contract's ```handoff block, near-miss forms are read, each with a warning so data generation can
    reject them (Piece.form_ok): handoff_unlabelled, the three lines in a plain ``` block (or ```text, ```yaml),
    and handoff_unfenced, the three lines with no fence at the very end of the reply, maybe under a "handoff"
    line. In the Oct 29 smoke runs 5 of the 6 contract replies from qwen3:8b and qwen3:4b-instruct wrote one of
    these, with all three lines; the strict rule sent the whole task to the combine for it. Since Oct 30 also
    handoff_unclosed_end, a ```handoff block holding just the three lines whose closing fence is missing at the
    end of the reply, and handoff_twice, the lines written outside the block as well. A key line only ever reads
    as a handoff here: in a plain block every line must be one."""
    blocks, form = handoff_blocks(text)
    issues = []
    if not blocks:
        return None, blocks, issues
    if form == "plain":
        issues.append(Issue("warn", "handoff_unlabelled", "the handoff is in a plain ``` block; the contract's is "
                            "```handoff (read anyway)", blocks[0].open_line + 1))
    elif form == "unfenced":
        issues.append(Issue("warn", "handoff_unfenced", "the handoff lines have no ```handoff fence (read anyway)",
                            blocks[0].open_line + 1))
    if len(blocks) > 1:
        issues.append(Issue("error", "handoff_many", "%d handoff blocks; the contract has exactly one" % len(blocks),
                            blocks[1].open_line + 1))
    b = blocks[-1]
    if not b.closed:
        # An open block runs to the end of the reply. Holding just the three lines, it is the contract's handoff with
        # its closing fence missing (qwen3:14b, Oct 30): read like an unfenced one. Anything else is still broken.
        if _only_key_lines(b.body):
            issues.append(Issue("warn", "handoff_unclosed_end", "the handoff block's closing ``` is missing at the end "
                                "of the reply (read anyway)", b.open_line + 1))
        else:
            issues.append(Issue("error", "handoff_unclosed", "the handoff block is never closed", b.open_line + 1))
    copy = _copy_above(text.split("\n"), b, same=False) if form in ("fenced", "plain") else None
    if copy:
        issues.append(Issue("warn", "handoff_twice", "the three handoff lines are also written unfenced just above "
                            "the block (read from the block)", copy[0] + 1))
    vals, extra = {}, []
    body_line = b.close_line - len(b.body.split("\n")) + 1 if form == "unfenced" else b.open_line + 1  # 0-based
    for j, line in enumerate(b.body.split("\n")):
        if go_trim_space(line) == "":
            continue
        m = _HANDOFF_KEY.match(line)
        if not m:
            extra.append(j)
            continue
        k = m.group(1).lower()
        if k in vals:
            issues.append(Issue("error", "handoff_shape", "the handoff has two %s: lines" % k, body_line + 1 + j))
        vals[k] = _value(m.group(2))
    missing = [k for k in ("provides", "uses", "assumed") if k not in vals]
    if missing:
        issues.append(Issue("error", "handoff_shape", "the handoff has no %s line" % " or ".join(missing),
                            b.open_line + 1))
    if extra:
        issues.append(Issue("error", "handoff_shape", "the handoff has %d line(s) besides provides, uses and assumed"
                            % len(extra), body_line + 1 + extra[0]))
    if b.closed and go_trim_space("\n".join(text.split("\n")[b.close_line + 1:])) != "":
        issues.append(Issue("error", "handoff_not_last", "text after the handoff block (the contract ends with it)",
                            b.close_line + 2))
    return Handoff(vals.get("provides", ""), vals.get("uses", ""), vals.get("assumed", "")), blocks, issues


def strip_handoff(text, blocks=None):
    """The reply without its handoff block(s), trimmed (a near-miss form's lines, and its label line, too, and a
    copy of the lines written just above the block)."""
    if blocks is None:
        blocks = handoff_blocks(text)[0]
    lines = text.split("\n")
    drop = set()
    for b in blocks:
        end = b.close_line if b.closed else len(lines) - 1
        drop.update(range(b.open_line, end + 1))
        copy = _copy_above(lines, b) if b.open_line > 0 else None
        if copy:
            drop.update(range(copy[0], copy[1] + 1))
    return go_trim_space("\n".join(l for i, l in enumerate(lines) if i not in drop))


def uses_steps(uses: str):
    """The steps a uses line names (s1 … s8), in order of first mention."""
    out = []
    for m in STEP_REF.finditer(uses):
        s = "s" + m.group(1)
        if s not in out:
            out.append(s)
    return out


# ---------------------------------------------------------------- ast helpers

def dotted(node) -> str:
    """bpy.ops.wm.save_mainfile for that attribute chain ("" if it isn't one)."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def is_main_guard(node) -> bool:
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare) or len(node.test.ops) != 1:
        return False
    if not isinstance(node.test.ops[0], ast.Eq):
        return False
    sides = [node.test.left, node.test.comparators[0]]
    names = [s for s in sides if isinstance(s, ast.Name) and s.id == "__name__"]
    consts = [s for s in sides if isinstance(s, ast.Constant) and s.value == "__main__"]
    return bool(names and consts)


def is_docstring(node) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def assigned_names(node):
    """Names a top-level Assign / AnnAssign binds (None if a target isn't a plain name)."""
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names = []
    for t in targets:
        for x in (t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t]):
            if not isinstance(x, ast.Name):
                return None
            names.append(x.id)
    return names


def top_level_names(tree):
    """Names bound at the top of a module: defs, classes, assignments, imports (as bound)."""
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            out.extend(assigned_names(node) or [])
        elif isinstance(node, ast.Import):
            out.extend((a.asname or a.name.split(".")[0]) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.extend((a.asname or a.name) for a in node.names if a.name != "*")
    return out


def literal(node) -> bool:
    try:
        ast.literal_eval(node)
        return True
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False


def ctx_keys(tree):
    """(written, read): the literal keys a piece stores into / reads from ctx["objects"]."""
    written, read = [], []

    def objects_sub(n):
        return (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == "ctx"
                and isinstance(n.slice, ast.Constant) and n.slice.value == "objects")

    for n in ast.walk(tree):
        if isinstance(n, ast.Subscript) and objects_sub(n.value) and isinstance(n.slice, ast.Constant) \
                and isinstance(n.slice.value, str):
            (written if isinstance(n.ctx, ast.Store) else read).append(n.slice.value)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("get", "setdefault") \
                and objects_sub(n.func.value) and n.args and isinstance(n.args[0], ast.Constant) \
                and isinstance(n.args[0].value, str):
            (written if n.func.attr == "setdefault" else read).append(n.args[0].value)
    return list(dict.fromkeys(written)), list(dict.fromkeys(read))


# "Don't open, load or save .blend files, render or quit" (the blender mode rule).
FORBIDDEN_CALLS = {
    "bpy.ops.wm.save_mainfile": "saves the .blend file", "bpy.ops.wm.save_as_mainfile": "saves the .blend file",
    "bpy.ops.wm.save_as_mainfile_copy": "saves the .blend file", "bpy.ops.wm.open_mainfile": "opens a .blend file",
    "bpy.ops.wm.read_homefile": "loads the start-up file", "bpy.ops.wm.read_factory_settings": "resets the scene",
    "bpy.data.libraries.load": "loads a .blend file", "bpy.ops.wm.append": "loads from a .blend file",
    "bpy.ops.wm.link": "loads from a .blend file", "bpy.ops.render.render": "renders",
    "bpy.ops.render.opengl": "renders", "bpy.ops.wm.quit_blender": "quits", "sys.exit": "quits", "exit": "quits",
    "quit": "quits", "os._exit": "quits",
}


def _call_kwarg(call, name):
    for k in call.keywords:
        if k.arg == name and isinstance(k.value, ast.Constant):
            return k.value.value
    return None


# What a loop that removes everything it goes over wipes: the scene's objects or data, or the project's shared
# collection (other steps' work is in it). ctx["scene"] reads as ctx.scene, and names bound to these are followed.
_WIPED = ("bpy.data.objects", "bpy.data.meshes", "bpy.data.materials", "bpy.context.scene.objects",
          "bpy.context.scene.collection.objects", "bpy.context.collection.objects", "bpy.context.view_layer.objects",
          "ctx.scene.objects", "ctx.scene.collection.objects", "ctx.collection.objects")


def _aliases(tree):
    """{name: value node} for names bound once, by a plain `name = value`, anywhere in the script."""
    seen = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            seen.setdefault(n.targets[0].id, []).append(n.value)
    return {k: v[0] for k, v in seen.items() if len(v) == 1}


def _ref(node, aliases, depth=0):
    """dotted() that reads ctx["scene"] as ctx.scene and follows names bound to other references."""
    if isinstance(node, ast.Name):
        if node.id in aliases and depth < 5:
            r = _ref(aliases[node.id], aliases, depth + 1)
            if r:
                return r
        return node.id
    if isinstance(node, ast.Attribute):
        base = _ref(node.value, aliases, depth)
        return base + "." + node.attr if base else ""
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
        base = _ref(node.value, aliases, depth)
        return base + "." + node.slice.value if base else ""
    return ""


def _loop_source(it):
    """What a for loop goes over, through list(), tuple(), sorted(), reversed(), enumerate(), .values() and a [:]
    slice."""
    while True:
        if isinstance(it, ast.Call) and dotted(it.func) in ("list", "tuple", "sorted", "reversed", "enumerate") \
                and it.args:
            it = it.args[0]
        elif isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) and it.func.attr == "values" \
                and not it.args:
            it = it.func.value
        elif isinstance(it, ast.Subscript) and isinstance(it.slice, ast.Slice):
            it = it.value
        else:
            return it


def _loop_var(n):
    """The name a for loop binds each item to (the second of `i, o` over enumerate()), or None."""
    if isinstance(n.target, ast.Name):
        return n.target.id
    if isinstance(n.target, ast.Tuple) and len(n.target.elts) == 2 and isinstance(n.target.elts[1], ast.Name) \
            and isinstance(n.iter, ast.Call) and dotted(n.iter.func) == "enumerate":
        return n.target.elts[1].id
    return None


def _not(test):
    return ast.UnaryOp(op=ast.Not(), operand=test)


def _calls_under(body, conds):
    """(call, [the if tests it sits under]) for every call in a loop body. An `if …: continue` (or break) before it
    counts as its negated test."""
    conds = list(conds)
    for st in body:
        if isinstance(st, ast.If):
            yield from _calls_under(st.body, conds + [st.test])
            yield from _calls_under(st.orelse, conds + [_not(st.test)])
            if st.body and isinstance(st.body[-1], (ast.Continue, ast.Break)):
                conds.append(_not(st.test))
            elif st.orelse and isinstance(st.orelse[-1], (ast.Continue, ast.Break)):
                conds.append(st.test)
        elif isinstance(st, (ast.For, ast.While, ast.With, ast.Try)):
            for field in ("body", "orelse", "finalbody"):
                yield from _calls_under(getattr(st, field, []) or [], conds)
            for h in getattr(st, "handlers", []) or []:
                yield from _calls_under(h.body, conds)
        else:
            yield from ((c, conds) for c in ast.walk(st) if isinstance(c, ast.Call))


def _excludes(test):
    """An if test that only skips a few things (!=, not in, is not, not o.name.startswith(…)): the loop still
    removes the rest. `not m.users` picks (the unused ones), like m.users == 0."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = test.operand
        if isinstance(inner, ast.UnaryOp) and isinstance(inner.op, ast.Not):
            return _excludes(inner.operand)
        if isinstance(inner, ast.Compare):
            return all(isinstance(op, (ast.Eq, ast.In, ast.Is)) for op in inner.ops)
        return isinstance(inner, (ast.Call, ast.BoolOp))
    if isinstance(test, ast.Compare):
        return all(isinstance(op, (ast.NotEq, ast.NotIn, ast.IsNot)) for op in test.ops)
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
        return all(_excludes(v) for v in test.values)
    return False


def forbidden_calls(tree):
    """[(line, name, what)] for each call the blender mode rule forbids, plus scene wipes."""
    out = []
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    for c in calls:
        name = dotted(c.func)
        if name in FORBIDDEN_CALLS:
            out.append((c.lineno, name, FORBIDDEN_CALLS[name]))
    # "Don't delete or change what you didn't create": select everything, then delete.
    sel_all = [c for c in calls if dotted(c.func) == "bpy.ops.object.select_all" and _call_kwarg(c, "action") == "SELECT"]
    deletes = [c for c in calls if dotted(c.func) == "bpy.ops.object.delete"]
    if sel_all and deletes:
        out.append((deletes[0].lineno, "bpy.ops.object.delete", "deletes everything in the scene"))
    aliases = _aliases(tree)
    for n in ast.walk(tree):  # for o in bpy.data.objects: bpy.data.objects.remove(o)
        var = _loop_var(n) if isinstance(n, ast.For) else None
        src = _ref(_loop_source(n.iter), aliases) if var else ""
        if var and src in _WIPED:
            hits = [(c, all(_excludes(t) for t in conds)) for c, conds in _calls_under(n.body, [])
                    if dotted(c.func).endswith(".remove") and c.args and isinstance(c.args[0], ast.Name)
                    and c.args[0].id == var]
            # unconditional, or only skipping a few (if o.name != "Camera"): everything goes; picked by a test of
            # its own (if o.name.startswith("chimera_")): a note, not a break
            every = [c for c, whole in hits if whole]
            if every:
                out.append((every[0].lineno, dotted(every[0].func), "removes everything in " + src))
            elif hits:
                out.append((hits[0][0].lineno, dotted(hits[0][0].func), "removes some of " + src + " in a loop"))
        if isinstance(n, ast.Call) and dotted(n.func) == "bpy.data.batch_remove":
            out.append((n.lineno, "bpy.data.batch_remove", "removes data in bulk"))
        if isinstance(n, ast.Call) and _ref(n.func, aliases) in ["%s.clear" % w for w in _WIPED]:  # Gemma 4, Oct 30
            # there's no such method (an AttributeError in Blender 5): it still says what the piece meant to do
            out.append((n.lineno, dotted(n.func), "tries to remove everything in " + _ref(n.func, aliases)[:-len(".clear")]))
    return out


# ---------------------------------------------------------------- the checks

_HARMONY = re.compile(r"<\|(start|end|message|channel|return|call|constrain)\|>|assistantfinal|</?think>")
_FILE_LINE = re.compile(r"^\s*(?P<pre>[*_#>`\-\s]*)File:(?P<mid>[*_\s]*)`?(?P<path>[^`*\s]+?)`?(?P<post>\**)(?P<rest>\s.*)?\s*$")
_PART = re.compile(r"^\s*\(part\)\s*$", re.I)
_PLACEHOLDER = re.compile(r"\bTODO\b|\bFIXME\b|\bplaceholder\b|#\s*\.\.\.|^\s*\.\.\.\s*$|\bimplement (this|me)\b", re.I | re.M)
_AI_TALK = re.compile(r"\bas an ai\b|\blanguage model\b|\bother workers?\b|\bthe workers\b|\bsub-?agents?\b", re.I)
_LINK = re.compile(r"https?://\S+|\bdoi:\s*\S+|\b10\.\d{4,9}/\S+", re.I)


def _err(p, code, msg, line=0, level="error"):
    p.issues.append(Issue(level, code, msg, line))


def validate_piece(text, mode, sid="s1", deps=(), lone=False, step=None, done_reason="", reject_cut=True,
                   max_tokens=MAX_PIECE_TOKENS) -> Piece:
    """Check one reply against the contract for its mode ("blender", "python-script", "files", "section").

    sid is the step's positional name, deps the positional names of the steps it depends on, step the plan's
    step dict (title, kind, instructions) for the section checks. done_reason "length" with reject_cut fails
    a reply its model cut off at its output limit. max_tokens=None skips the length rule."""
    p = Piece(sid=sid, mode=mode, text=text or "")
    text = p.text
    if go_trim_space(text) == "":
        _err(p, "empty", "the reply is empty")
        return p
    if reject_cut and done_reason == "length":
        _err(p, "cut_off", "its model stopped at its output limit, so the piece may be cut off")
    if max_tokens and estimate_tokens(text) > max_tokens:
        _err(p, "too_long", "about %d tokens, over the %d a piece may have" % (estimate_tokens(text), max_tokens))
    if m := _HARMONY.search(text):
        _err(p, "harmony_leftover", "the reply has %r, left over from the model's own format" % m.group(0),
             text.count("\n", 0, m.start()) + 1)

    handoff, hblocks, hissues = parse_handoff(text)
    p.handoff = handoff
    if lone:
        if hblocks:
            _err(p, "handoff_in_lone", "a lone step gets no handoff; it is stripped", hblocks[0].open_line + 1, "warn")
    else:
        p.issues.extend(hissues)
        if not hblocks:
            _err(p, "handoff_missing", "no ```handoff block at the end")
        if handoff:
            if _NEGATED.match(handoff.uses):  # "nothing from s1 (…)": none, in more words
                _err(p, "handoff_wordy", "uses says %r; the contract's word for nothing is \"none\"" % handoff.uses[:60],
                     level="warn")
                handoff.uses = ""
            for key in ("provides", "uses", "assumed"):
                if len(getattr(handoff, key)) > HANDOFF_LINE_MAX:
                    _err(p, "handoff_long", "the %s line has %d characters; the contract asks for one short line"
                         % (key, len(getattr(handoff, key))), level="warn")
            bad = [s for s in uses_steps(handoff.uses) if s not in deps and s != sid]
            if bad:
                _err(p, "uses_not_dependency", "uses names %s, which %s doesn't depend on (it depends on %s)"
                     % (", ".join(bad), sid, ", ".join(deps) or "nothing"))
    p.body = strip_handoff(text, hblocks)
    taken = {b.open_line for b in hblocks}  # a plain block read as the handoff isn't code
    blocks = [b for b in code_blocks(text) if b.lang != "handoff" and b.open_line not in taken]

    if mode == "blender":
        _python_piece(p, blocks, blender=True)
    elif mode == "python-script":
        _python_piece(p, blocks, blender=False)
    elif mode == "files":
        _files_piece(p, blocks)
    elif mode == "section":
        _section_piece(p, step or {})
    else:
        raise ValueError("unknown mode %r" % mode)
    return p


def _python_piece(p, blocks, blender):
    py = [b for b in blocks if python_lang(b.lang) or (b.lang == "" and (not blender or BPY_IMPORT.search(b.body)))]
    others = [b for b in blocks if b not in py]
    if others:
        _err(p, "extra_block", "%d other code block(s) besides the python one; joining ignores them" % len(others),
             others[0].open_line + 1, "warn")
    if not py:
        _err(p, "no_python_block", "no python code block")
        return
    if len(py) > 1:
        _err(p, "many_python_blocks", "%d python code blocks; the mode has exactly one" % len(py), py[1].open_line + 1)
        return
    b = py[0]
    p.code, p.code_line = b.body, b.open_line + 2
    if not b.closed:
        _err(p, "unclosed_block", "the python block is never closed (cut off?)", b.open_line + 1)
    if b.lang == "":
        _err(p, "no_language", "the code block doesn't name its language", b.open_line + 1, "warn")
    try:
        p.tree = ast.parse(b.body)
    except SyntaxError as e:
        _err(p, "syntax_error", "SyntaxError: %s" % (e.msg,), p.code_line + (e.lineno or 1) - 1)
        return
    if blender:
        _blender_top_level(p)
    else:
        _script_top_level(p)


_STEP_NAME = re.compile(r"^(?:SETTINGS_|build_|_)(s\d+)(?:_|$)")


def _blender_top_level(p):
    """Column-0 lines are only imports, SETTINGS_sN, def build_sN, _sN_ helpers, comments, docstrings and the
    main guard (the plan's validation rule). Read from the ast, so a statement's continuation lines count as it."""
    sid, at = p.sid, p.code_line - 1
    settings, builds, guards = [], [], []
    for node in p.tree.body:
        line = at + node.lineno
        name = getattr(node, "name", None)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
                _err(p, "star_import", "from %s import *" % node.module, line, "warn")
        elif is_docstring(node):
            pass
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and assigned_names(node) == ["SETTINGS_" + sid]:
            settings.append(node)
            if not isinstance(node.value, ast.Dict):
                _err(p, "settings_not_dict", "SETTINGS_%s isn't a {...} dict" % sid, line)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and name == "build_" + sid:
            builds.append(node)
            a = node.args
            if len(a.posonlyargs) + len(a.args) != 1 or a.vararg or a.kwonlyargs or a.kwarg:
                _err(p, "build_signature", "build_%s should take one argument, ctx" % sid, line, "warn")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and name.startswith("_%s_" % sid):
            pass
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and (assigned_names(node) or [""])[0].startswith("_%s_" % sid) \
                and all(n.startswith("_%s_" % sid) for n in assigned_names(node)):
            pass
        elif is_main_guard(node):
            guards.append(node)
        else:
            names = [name] if name else (assigned_names(node) or []) if isinstance(node, (ast.Assign, ast.AnnAssign)) else []
            other = [n for n in names if (m := _STEP_NAME.match(n)) and m.group(1) != sid]
            if other:
                _err(p, "wrong_step_names", "%s is named for another step (this is %s)" % (other[0], sid), line)
            else:
                what = name or (", ".join(names) if names else type(node).__name__.lower())
                _err(p, "top_level_code", "top-level %s isn't an import, SETTINGS_%s, build_%s, a _%s_ helper or the "
                     "main guard" % (what, sid, sid, sid), line)
    if not settings:
        _err(p, "no_settings", "no SETTINGS_%s = {...} dict" % sid)
    elif len(settings) > 1:
        _err(p, "many_settings", "SETTINGS_%s is set %d times" % (sid, len(settings)), at + settings[1].lineno)
    if not builds:
        _err(p, "no_build", "no def build_%s(ctx):" % sid)
    elif len(builds) > 1:
        _err(p, "many_build", "build_%s is defined %d times" % (sid, len(builds)), at + builds[1].lineno)
    if not guards:
        _err(p, "no_main_guard", "no if __name__ == \"__main__\": build_%s(...) at the end" % sid)
    else:
        calls = [dotted(c.func) for g in guards for c in ast.walk(g) if isinstance(c, ast.Call)]
        if "build_" + sid not in calls:
            _err(p, "guard_not_build", "the main guard doesn't call build_%s" % sid, at + guards[0].lineno)
        if len(guards) > 1:
            _err(p, "many_guards", "%d main guards" % len(guards), at + guards[1].lineno, "warn")
    for line, name, what in forbidden_calls(p.tree):
        if what.startswith("removes some of"):
            _err(p, "removes_in_loop", "%s %s; check it only removes what this step made" % (name, what), at + line,
                 "warn")
            continue
        code = "deletes_scene" if "everything" in what or "bulk" in what else "saves_or_renders"
        _err(p, code, "%s %s; the mode rule leaves that to Chimera (SETTINGS_%s[\"output\"])" % (name, what, sid)
             if code == "saves_or_renders" else "%s %s; other steps' work is in the scene too" % (name, what),
             at + line)
    written, _ = ctx_keys(p.tree)
    if p.handoff is not None:
        missing = [k for k in written if k not in p.handoff.provides]
        if missing:
            _err(p, "provides_missing", "registers ctx[\"objects\"] key(s) %s that provides doesn't list"
                 % ", ".join(missing), level="warn")


def _script_top_level(p):
    """Functions and classes only, with no code that runs on import (the python-script mode rule)."""
    at = p.code_line - 1
    for node in p.tree.body:
        line = at + node.lineno
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                or is_docstring(node):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and assigned_names(node) is not None:
            if node.value is not None and not literal(node.value):
                _err(p, "top_level_assign", "%s is set by running code on import" % ", ".join(assigned_names(node)),
                     line, "warn")
            continue
        if is_main_guard(node):
            _err(p, "main_guard", "a main guard; Chimera calls main() itself and drops it", line, "warn")
            continue
        if isinstance(node, ast.Try) and all(isinstance(x, (ast.Import, ast.ImportFrom)) for x in node.body):
            continue  # try: import x / except ImportError
        if isinstance(node, ast.If) and dotted(node.test) in ("TYPE_CHECKING", "typing.TYPE_CHECKING"):
            continue
        _err(p, "runs_on_import", "top-level %s runs when the file is imported" % type(node).__name__.lower(), line)
    if p.code and _PLACEHOLDER.search(p.code):
        _err(p, "placeholder", "a TODO, placeholder or stub", level="warn")


def file_line(line):
    """(path, part, decorated) if line is a File: line, else None."""
    m = _FILE_LINE.match(line)
    if not m:
        return None
    rest = (m.group("rest") or "").strip()
    part = bool(_PART.match(rest))
    decorated = bool(go_trim_space(m.group("pre")) or go_trim_space(m.group("mid")) or m.group("post")
                     or (rest and not part))
    return m.group("path").rstrip(":"), part, decorated


def _files_piece(p, blocks):
    """Every block has a File: line just before it (the plan's validation rule), plus the files mode rule."""
    lines = p.text.split("\n")
    if not blocks:
        _err(p, "no_file_blocks", "no code blocks; the mode gives each file in its own fenced block")
        return
    seen = {}
    for b in blocks:
        j = b.open_line - 1
        while j >= 0 and go_trim_space(lines[j]) == "":
            j -= 1
        fl = file_line(lines[j]) if j >= 0 else None
        if fl is None:
            _err(p, "no_file_line", "the block at line %d has no File: line just before it" % (b.open_line + 1),
                 b.open_line + 1)
            continue
        path, part, decorated = fl
        if decorated:
            _err(p, "file_line_decorated", "the File: line for %s isn't plain (File: path or File: path (part))" % path,
                 j + 1, "warn")
        if not b.closed:
            _err(p, "unclosed_block", "the block for %s is never closed (cut off?)" % path, b.open_line + 1)
        if b.lang == "":
            _err(p, "no_language", "the block for %s doesn't name its language" % path, b.open_line + 1, "warn")
        if (path, part) in seen and not part:
            _err(p, "duplicate_file", "%s is given twice" % path, b.open_line + 1, "warn")
        seen[(path, part)] = True
        p.files.append(FilePart(path, part, b.lang, b.body, b.open_line + 1))
        if path.endswith(".py") or python_lang(b.lang):
            try:
                ast.parse(b.body)
            except SyntaxError as e:
                _err(p, "syntax_error", "%s: SyntaxError: %s" % (path, e.msg), b.open_line + 1 + (e.lineno or 1))
        if _PLACEHOLDER.search(b.body):
            _err(p, "placeholder", "%s has a TODO, placeholder or stub" % path, b.open_line + 1, "warn")


def _norm_heading(s):
    return " ".join(re.sub(r"[^\w\s]", " ", s.lower()).split())


def _section_piece(p, step):
    """Starts with "## " (the plan's validation rule), plus the section mode rule's checkable parts."""
    body = p.body
    if not body.startswith("## "):
        first = body.split("\n", 1)[0]
        why = "starts with a level-1 heading" if first.startswith("# ") else "doesn't start with a ## heading"
        _err(p, "no_heading", "the section %s" % why, 1)
        return
    heading = body.split("\n", 1)[0][3:].strip()
    p.section = body
    title = step.get("title", "")
    if title and _norm_heading(heading) != _norm_heading(title) \
            and _norm_heading(heading) not in _norm_heading(step.get("instructions", "")):
        _err(p, "heading_not_title", "heading %r is neither the step's title nor in its instructions" % heading,
             1, "warn")
    if m := _AI_TALK.search(body):
        _err(p, "ai_talk", "mentions %r" % m.group(0), body.count("\n", 0, m.start()) + 1, "warn")
    if step.get("kind") == "research":
        for m in _LINK.finditer(body):
            end = body.find("\n", m.end())
            if "(unverified)" not in body[m.start():end if end >= 0 else len(body)]:
                _err(p, "unmarked_link", "%s isn't marked (unverified)" % m.group(0)[:80],
                     body.count("\n", 0, m.start()) + 1, "warn")
