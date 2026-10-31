"""Running a worker's Blender script for scoring.

Two runs per Blender version:
- check: Chimera's own result check (`chimera --check-result`, through tools/blender_check.py: a PATH shim per
  version, a fresh --data-dir, Chimera's sandbox, the strict rule) of the script exactly as it is: no probe is
  appended, so the 1,500 characters of output the check shows are all the script's own.
- probe: the probes, out of band, run directly: `blender -b --factory-startup` (Chimera's arguments) under
  sandbox-exec with a profile like Chimera's own (macScriptProfile, app/runner.go: no network, home folders
  unreadable, writes only to the run folder, no new processes), HOME and TMPDIR in the run folder. The script gets
  tools/scene_probe.py's epilogue (ctx["objects"] keys, names, .001 duplicates; no length budget here) and then
  the eval's richer probe (eval/scene_probe.py, "CHIMERA_PROBE {json}", run by exec so an error in it can't fail
  the script) for the scene assertions. A render stops the run there, as Chimera's check does, after the eval
  probe has run. Its whole output is kept: strict_full is the strict rule (tools/blender_check.bad_lines, the
  check's own) over all of it, so it also sees what the check's tail no longer shows.

The strict verdict that counts (counted_strict) needs both: the check's strict and the direct run's strict_full,
in the Blender version asked for.

A step's script (script_for_step): a contract piece joined with its dependencies' pieces by contract/join.py
("joined"); otherwise, the dependencies (joined when they keep the contract, else their scripts one after
another) followed by the reply's own script as Chimera's check would pick it ("after_deps"), or that script
alone ("alone"). "none" when the reply has no Blender script. In "after_deps" the dependencies' calls that would
end the run before the reply's own script (a render, which Chimera's check stops at, a quit, an exit) are
skipped, so the reply's own code always runs.

A contract piece that isn't joined (it broke a mode rule) still gets its build function called (with_build_call):
before Oct 30 a piece with no main guard ran "alone" as a script that only defined functions, so its build never
ran and the untouched factory scene passed strict. Now, when nothing in the reply's own top-level code calls
build_sN, it runs as data generation runs a piece alone (contract/join.alone_script: its guard blanked, ctx made at
module level, build_sN(ctx)); after its dependencies it gets their ctx, which a guard of its own would replace with
an empty one. Its contract verdict is kept apart (score.py): this is about whether its code works.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

from runner.common import HERE

from contract import planinfo  # noqa: E402
from contract.goport import BPY_IMPORT, code_blocks, python_lang  # noqa: E402
from contract.join import alone_script, join  # noqa: E402
from contract.validate import Piece, is_main_guard  # noqa: E402
from tools import blender_check, blenders, scene_probe  # noqa: E402

PROBE_FILE = os.path.join(HERE, "eval", "scene_probe.py")
PROBE_MARK = "CHIMERA_PROBE "
WM_MARK = "wm-probe:"  # this runner's own lines in the direct run
TOOLS_PROBE_BUDGET = 1000000  # the direct run's output isn't cut, so the tools probe's line needn't fit a tail
STAND_IN = "chimera: stand-in"
_HEADER = re.compile(r"(?m)^Blender (\d+\.\d+\.\d+)(?: [A-Za-z]+)? \(hash ")
CHECK_MIN_LINES = 6  # checkMinLines (app/hydra_check.go)
_USES_BPY = re.compile(r"\bbpy\.")
_WINDOW = re.compile(r"(?m)^\s*(import|from)\s+(tkinter|turtle|pygame|PyQt\d?|PySide\d?|wx|kivy|pyglet|arcade|curses|"
                     r"matplotlib|flask|fastapi|django|streamlit|uvicorn|aiohttp|http\.server|socketserver)\b")


# ---------------------------------------------------------------- which script (pickScript, app/hydra_check.go)

def code_lines(body):
    """codeLines: the lines that do something (not blank, not a comment)."""
    return sum(1 for l in body.split("\n") if l.strip() and not l.strip().startswith("#"))


def dedent(body):
    """dedent (app/hydra_check.go): the indent every line shares taken off."""
    lines = body.split("\n")
    ind = [len(l) - len(l.lstrip(" \t")) for l in lines if l.strip()]
    common = min(ind) if ind else 0
    if common <= 0:
        return body
    return "\n".join(l[common:] if len(l) >= common else l.lstrip(" \t") for l in lines)


def pick_script(result, kinds=("blender", "code")):
    """pickScript: (kind, script, why). kind is run_blender, run_python or "" (nothing to check); why says why a
    script that is there wouldn't be run (several Blender scripts of similar size, several Python files)."""
    kinds = set(kinds)
    blender, python = [], []
    for b in code_blocks(result):
        if not b.closed or code_lines(b.body) < CHECK_MIN_LINES or "\n>>> " in "\n" + b.body:
            continue
        if (python_lang(b.lang) or b.lang == "") and BPY_IMPORT.search(b.body):
            blender.append(b)
        elif python_lang(b.lang) and not _USES_BPY.search(b.body):
            python.append(b)
    if blender and kinds & {"blender", "code", "general"}:
        blender.sort(key=lambda b: code_lines(b.body), reverse=True)
        main = code_lines(blender[0].body)
        similar = 1 + sum(1 for b in blender[1:] if 2 * code_lines(b.body) > main)
        if similar > 1:
            return "run_blender", "", ("the result has %d Blender scripts of similar size, and it isn't clear which "
                                       "one to run" % similar)
        return "run_blender", dedent(blender[0].body), ""
    if python and "code" in kinds:
        if len(python) > 1:
            return "run_python", "", "the result has %d Python files; Hydra only runs a result that is one script" % len(python)
        if _WINDOW.search(python[0].body):
            return "run_python", "", "it would open a window or start a server"
        return "run_python", dedent(python[0].body), ""
    return "", "", ""


def count_scripts(result):
    """Closed Blender and plain-Python blocks of at least six code lines (how many scripts a result holds)."""
    n_b = n_p = 0
    for b in code_blocks(result):
        if not b.closed or code_lines(b.body) < CHECK_MIN_LINES:
            continue
        if (python_lang(b.lang) or b.lang == "") and BPY_IMPORT.search(b.body):
            n_b += 1
        elif python_lang(b.lang):
            n_p += 1
    return {"blender": n_b, "python": n_p}


def reply_script(reply):
    """The Blender script in one worker reply, as Chimera's check would pick it ("" if none)."""
    kind, script, _ = pick_script(reply or "", ("blender",))
    return script if kind == "run_blender" else ""


# ---------------------------------------------------------------- a step's script, with its dependencies

# Calls that end a Blender run before the code after them: a render (Chimera's check stops at the first one), a
# quit, an exit. Matched on the dotted name's end, so bpy.ops.render.render and ops.render.render both count, and
# a name imported from bpy.ops (`from bpy.ops import render`, `from bpy import ops as o`) is read as its full name.
_RUN_ENDERS = ("ops.render.render", "ops.render.opengl", "ops.wm.quit_blender")
_EXITS = {"sys.exit", "exit", "quit", "os._exit"}
# What an operator call is replaced by: its own return value when it ran, so a script that checks it
# (`if bpy.ops.render.render(...) != {'FINISHED'}: raise ...`) carries on as it would after a real render.
OP_DONE = "{'FINISHED'}"


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _bpy_aliases(tree):
    """Local names bound by importing from bpy (`from bpy.ops import render as r` -> {"r": "bpy.ops.render"},
    `import bpy.ops as o` -> {"o": "bpy.ops"}), so their calls are matched by their full names."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "bpy":
            for a in node.names:
                out[a.asname or a.name] = node.module + "." + a.name
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.asname and a.name.split(".")[0] == "bpy":
                    out[a.asname] = a.name
    return out


def _system_exit(node):
    """A `raise SystemExit` / `raise SystemExit(...)` statement."""
    if not isinstance(node, ast.Raise) or node.exc is None:
        return False
    exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    return _dotted(exc) in ("SystemExit", "builtins.SystemExit")


def skip_run_enders(script):
    """(script, n): the script with whatever would end the run before the code after it neutralised, so that code
    gets to run; n says how many. A render or quit operator call (bpy.ops.render.render, .opengl,
    bpy.ops.wm.quit_blender) becomes {'FINISHED'}, the operator's own return value; sys.exit, exit, quit and os._exit
    calls become None; a `raise SystemExit(...)` statement becomes pass. A script that doesn't parse comes back as it
    is. Not caught: a render reached another way (getattr, a call through a variable, bpy.ops.render.render bound to
    a name)."""
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return script, 0
    aliases = _bpy_aliases(tree)
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            head, _, rest = name.partition(".")
            if head in aliases:
                name = aliases[head] + ("." + rest if rest else "")
            if name in _EXITS:
                spans.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, "None"))
            elif any(name == e or name.endswith("." + e) for e in _RUN_ENDERS):
                spans.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, OP_DONE))
        elif _system_exit(node):
            spans.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, "pass"))
    spans.sort()
    outer = []
    for sp in spans:  # only the outermost of nested ones (sys.exit(bpy.ops.render.render()), raise SystemExit(...))
        if outer and (sp[0], sp[1]) < (outer[-1][2], outer[-1][3]):
            continue
        outer.append(sp)
    lines = [l.encode("utf-8") for l in script.split("\n")]  # ast's columns are UTF-8 byte offsets
    for l1, c1, l2, c2, new in reversed(outer):
        lines[l1 - 1:l2] = [lines[l1 - 1][:c1] + new.encode() + lines[l2 - 1][c2:]]
    out = "\n".join(l.decode("utf-8") for l in lines)
    try:
        ast.parse(out)
    except SyntaxError:  # never hand on a script this broke
        return script, 0
    return out, len(outer)


_BUILD = re.compile(r"build_s\d+")
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
DEPS_CTX = "_wm_deps_ctx"  # the dependencies' ctx, kept apart before the reply's own script can rebind ctx


def _registered(tree):
    """ids of the nodes inside what's handed to bpy.app.timers.register: a timer never fires under -b (the run ends
    first). A bpy.app.handlers callback can run there (frame_set, view_layer.update), so it counts as reached."""
    out = set()
    aliases = _bpy_aliases(tree)
    for c in ast.walk(tree):
        if isinstance(c, ast.Call):
            name = _dotted(c.func)
            head, _, rest = name.partition(".")
            if head in aliases:
                name = aliases[head] + ("." + rest if rest else "")
            if name in ("bpy.app.timers.register", "app.timers.register"):
                for a in list(c.args) + [k.value for k in c.keywords]:
                    out.update(id(n) for n in ast.walk(a))
    return out


def _reached(tree, name, guard):
    """Whether the script's own code already gets function name run: a reference to it (a call, a variable, a
    decorator, globals()["build_s2"]) in code that runs, following the top-level functions and classes that code
    refers to, minus timers handed to bpy.app.timers. guard: the main guard's code runs too.
    Conservative on purpose: a build the reply might run itself isn't called a second time (that builds twice)."""
    defs = {n.name: n for n in tree.body if isinstance(n, _DEFS)}
    if name in defs and defs[name].decorator_list:
        return True  # a decorated build is handed to its decorator, which may run it: left as it is
    skip = _registered(tree)
    todo = []
    for n in tree.body:
        if isinstance(n, _DEFS):
            todo += n.decorator_list  # decorators run when the def does
        elif guard or not is_main_guard(n):
            todo.append(n)
    seen = set()
    while todo:
        for c in ast.walk(todo.pop()):
            if id(c) in skip:
                continue
            ref = c.id if isinstance(c, ast.Name) and isinstance(c.ctx, ast.Load) else \
                c.value if isinstance(c, ast.Constant) and isinstance(c.value, str) else None
            if ref == name:
                return True
            if ref in defs and ref not in seen:
                seen.add(ref)
                todo.append(defs[ref])
    return False


def _defines_only(stmts):
    """The statements only define things (see inert)."""
    for n in stmts:
        if isinstance(n, (ast.Import, ast.ImportFrom, ast.Pass)):
            continue
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.decorator_list \
                and not any(_calls(d) for d in n.args.defaults + n.args.kw_defaults if d is not None):
            continue
        if isinstance(n, ast.ClassDef) and not n.decorator_list and not n.bases and not n.keywords \
                and _defines_only(n.body):  # a class body runs: it must only define things too
            continue
        if isinstance(n, ast.Try) and _defines_only(n.body) and all(_defines_only(h.body) for h in n.handlers) \
                and _defines_only(n.orelse) and _defines_only(n.finalbody):  # try: import numpy / except: np = None
            continue
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []
        if isinstance(n, (ast.Assign, ast.AnnAssign, ast.Expr)) and n.value is not None and not _calls(n.value) \
                and (not isinstance(n, ast.Expr) or isinstance(n.value, ast.Constant)) \
                and all(isinstance(x, ast.Name) for t in targets for x in ast.walk(t)
                        if not isinstance(x, (ast.Tuple, ast.List, ast.Store, ast.Load))):
            continue  # a name bound to a value; setting an attribute (scene.render.engine = …) does something
        return False
    return True


def _calls(node):
    """A call in node that runs when it's evaluated (a lambda's body doesn't)."""
    todo = [node]
    while todo:
        n = todo.pop()
        if isinstance(n, ast.Call):
            return True
        if not isinstance(n, ast.Lambda):
            todo.extend(ast.iter_child_nodes(n))
        else:
            todo.extend(d for d in n.args.defaults + n.args.kw_defaults if d is not None)
    return False


def inert(tree):
    """The script only defines things: imports (in a try too), defs and classes with no decorators (a class body only
    defining things), and names bound to values with no call in them (a lambda's body doesn't run). Nothing in it
    would run (join.py's missing_entry_point, for a script)."""
    return _defines_only(tree.body)


def with_build_call(own, sid, after_deps=False, ctx_name="ctx"):
    """(script, [build names]): a contract-style reply's own script with its build function called, when its own
    code doesn't run it (alone: not even from its main guard; after_deps: not outside the guard, whose ctx would
    be an empty one, so the guard is left out and the module-level dict ctx_name, the dependencies' ctx, is passed
    on). The build is build_<sid>, else every build_sN the script defines, in order, as joining calls each piece's.
    A script with nothing to call comes back as it is, with []."""
    try:
        tree = ast.parse(own)
    except SyntaxError:
        return own, []
    builds = list(dict.fromkeys(n.name for n in tree.body if isinstance(n, ast.FunctionDef) and _BUILD.fullmatch(n.name)))
    if "build_" + sid in builds:
        builds = ["build_" + sid]
    call = [b for b in builds if not _reached(tree, b, guard=not after_deps)]
    if not call or len(call) < len(builds):
        return own, []  # some build already runs: the script wires its builds itself (and blanking its guard could stop it)
    piece = Piece(sid=call[0][len("build_"):], mode="blender", text=own)
    piece.code, piece.tree = own, tree
    return alone_script(piece, keep_ctx=after_deps, ctx_name=ctx_name,
                        also=[b[len("build_"):] for b in call[1:]]), call


def script_for_step(plan, index, outputs, reply, goal="", call_build=True):
    """(run_kind, script, notes) for step index's reply, with its dependencies (outputs: plan id -> reply or None).
    call_build=False builds the script as before Oct 30: a piece that isn't joined as it is, the dependencies'
    scripts as they are, a script that only defines things run anyway (runner/rescore.py rebuilds old scripts
    with it)."""
    st = plan["steps"][index]
    sid = "s%d" % (index + 1)
    dep_ix = planinfo.dep_indexes(plan, index)
    done = [plan["steps"][j]["id"] for j in dep_ix if outputs.get(plan["steps"][j]["id"])]
    sid_of = {plan["steps"][j]["id"]: "s%d" % (j + 1) for j in dep_ix}
    sub = {d: outputs[d] for d in done}
    j = join(plan, dict(sub, **{st["id"]: reply}), goal=goal)
    if not j.fallback and j.script and j.script_kind == "run_blender":
        return "joined", j.script, ["joined with %s" % ", ".join(done)] if done else []
    notes = ["not joined: " + "; ".join(j.reasons[:3])] if j.reasons else []
    own = reply_script(reply)
    if not own:
        return "none", "", notes + ["the reply has no Blender script"]
    # The dependencies first, then the reply's own script. Whatever in them would end the run first is skipped:
    # the joined dependencies' _chimera_output renders (a step's SETTINGS_sN["output"]), and so may a plain
    # dependency script, and Chimera's check stops at the first render, so the reply's code would never run and a
    # crashing reply would pass. Dependencies that don't join run one after another; contract-style ones get their
    # builds called on one shared module-level ctx, as joining would run them.
    parts, skipped, deps_ctx = [], 0, False
    if done:
        jd = join(plan, sub, goal=goal)
        if not jd.fallback and jd.script and jd.script_kind == "run_blender":
            s, n = skip_run_enders(jd.script)
            parts.append(s)
            skipped += n
            if call_build:  # join_script's guard leaves ctx at module level
                parts.append("%s = globals().get(\"ctx\")  # the dependencies' ctx, for the reply's build" % DEPS_CTX)
                deps_ctx = True
        else:
            for d in done:
                s = reply_script(outputs[d])
                if s:
                    if call_build:  # one shared ctx, kept as DEPS_CTX so no dependency's own `ctx = ...` loses it
                        s, c = with_build_call(s, sid_of[d], after_deps=True, ctx_name=DEPS_CTX)
                        if c:
                            s += "%s = ctx\n" % DEPS_CTX
                            deps_ctx = True
                            notes.append("%s's %s called on the dependencies' shared ctx" % (
                                sid_of[d], ", ".join(b + "(ctx)" for b in c)))
                    s, n = skip_run_enders(s)
                    parts.append(s)
                    skipped += n
        if skipped:
            notes.append("the dependencies' %d render, quit or exit call(s) skipped, so the reply's own script runs"
                         % skipped)
    if call_build:
        orig = own
        own, called = with_build_call(orig, sid, after_deps=deps_ctx, ctx_name=DEPS_CTX)
        if called:
            guarded = any(is_main_guard(n) for n in ast.parse(orig).body)  # it parsed in with_build_call
            how = "with the dependencies' ctx" + (", its own guard left out" if guarded else "") if deps_ctx \
                else "nothing in the script calls %s" % ("them" if len(called) > 1 else "it")
            notes.append("%s called as joining calls %s (%s)" % (", ".join(b + "(ctx)" for b in called),
                                                                 "them" if len(called) > 1 else "it", how))
        else:
            try:
                if inert(ast.parse(own)):
                    return "none", "", notes + ["the reply's script only defines things: nothing in it would run"]
            except SyntaxError:
                pass
    if not done:
        return "alone", own, notes
    parts.append("# ---- the reply's own script ----\n" + own)
    return "after_deps", "\n\n".join(parts) + "\n", notes


# ---------------------------------------------------------------- the sandbox for the direct probe run

def _sb(p):
    return '"' + p.replace("\\", "\\\\").replace('"', '\\"') + '"'


def app_root(binary):
    """The .app bundle a Blender binary is in (or its folder)."""
    p = os.path.realpath(binary)
    i = p.find(".app/")
    return p[:i + 4] if i > 0 else os.path.dirname(p)


def sandbox_profile(run_dir, binary):
    """A sandbox-exec profile in the spirit of Chimera's macScriptProfile (app/runner.go)."""
    rd, root = os.path.realpath(run_dir), app_root(binary)
    return f"""(version 1)
(allow default)
(deny network*)
(deny file-read* (subpath "/Users") (subpath "/Volumes") (subpath "/private/var/root"))
(allow file-read* (subpath {_sb(rd)}) (subpath {_sb(root)}))
(deny file-write*)
(allow file-write* (subpath {_sb(rd)}) (literal "/dev/null") (regex #"^/dev/tty") (regex #"^/dev/fd/"))
(deny appleevent-send)
(deny mach-lookup (global-name "com.apple.coreservices.launchservicesd") (global-name "com.apple.pasteboard.1"))
(deny signal)
(allow signal (target self))
(deny process-fork)
(deny process-exec*)
(allow process-exec* (literal {_sb(binary)}) (literal {_sb(os.path.realpath(binary))}) (subpath {_sb(root)}))"""


def stop_at_render(probe_path):
    """A --python-expr like Chimera's blenderStopAtRender, but it runs the eval probe before it stops."""
    return ("import bpy, os, sys\n"
            "@bpy.app.handlers.persistent\n"
            "def _wm_stop_at_render(*args):\n"
            "    print('wm-probe: stopped at the render', flush=True)\n"
            "    try:\n"
            f"        exec(compile(open({probe_path!r}).read(), 'scene_probe.py', 'exec'), {{'__name__': '_wm_probe'}})\n"
            "    except Exception as e:\n"
            "        print('wm-probe: probe failed at the render:', type(e).__name__, e, flush=True)\n"
            "    sys.stdout.flush()\n"
            "    sys.stderr.flush()\n"
            "    os._exit(0)\n"
            "bpy.app.handlers.render_init.append(_wm_stop_at_render)\n")


def probe_script(script, probe_path):
    """The direct run's script: the step's script, tools/scene_probe.py's epilogue (no budget: nothing here is cut),
    then the eval probe at probe_path, run by exec in its own namespace so an error in it can't fail the script."""
    return (scene_probe.append(script, budget=TOOLS_PROBE_BUDGET).rstrip("\n") + "\n\n\n# ---- scene probe (eval) ----\n"
            "try:\n"
            f"    exec(compile(open({probe_path!r}).read(), 'scene_probe.py', 'exec'), {{'__name__': '_wm_probe'}})\n"
            "except Exception as _wm_e:\n"
            f"    print({WM_MARK + ' probe failed:'!r}, type(_wm_e).__name__, _wm_e, flush=True)\n")


def own_output(output):
    """A run's output without the probes' lines and this runner's own (what the strict rule reads)."""
    return "\n".join(l for l in (output or "").split("\n")
                     if not (l.startswith(PROBE_MARK) or l.startswith(WM_MARK) or scene_probe.is_probe_line(l)))


def blender_version(output):
    """The version in Blender's own header line ("Blender 5.2.2 LTS (hash …)"), or None."""
    m = _HEADER.search(output or "")
    return m.group(1) if m else None


def counted_strict(check, probe):
    """The strict verdict that counts, in one version: Chimera's check passed with no "Traceback" or "Error:" line
    in the 1,500 characters of output it shows, and the direct run's whole output has none either (the same rule),
    in the Blender version asked for. check, probe: one version's records from Blender.check and Blender.probe."""
    check, probe = check or {}, probe or {}
    return bool(check.get("strict")) and bool(probe.get("strict_full")) and probe.get("version_ok") is not False


def parse_probe(output):
    lines = [l[len(PROBE_MARK):] for l in (output or "").split("\n") if l.startswith(PROBE_MARK)]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except ValueError:
        return None


def _last_exception(output):
    lines = (output or "").split("\n")
    starts = [i for i, l in enumerate(lines) if l.startswith("Traceback (most recent call last):")]
    if not starts:
        return ""
    for l in lines[starts[-1] + 1:]:
        if l and not l[0].isspace():
            return l.strip()
    return ""


class Blender:
    """Both runs in every version. versions: {"5.2.2": binary, ...} (tools/blenders.py by default)."""

    def __init__(self, chimera=None, versions=None, work=None, timeout=180.0, sandbox=True):
        self.chimera = blender_check.chimera_bin(chimera)
        self.versions = dict(versions or blenders.VERSIONS)
        for v, path in self.versions.items():
            why = blenders.check_path(path)
            if why:
                raise RuntimeError(f"Blender {v}: {why}")
        self.work = blender_check.scratch_root(work)
        self.timeout = timeout
        self.sandbox = sandbox and shutil.which("sandbox-exec") is not None
        with open(PROBE_FILE, encoding="utf-8") as f:
            self.probe_src = f.read()

    def check(self, text, name="script.py", goal=None):
        """Chimera's check of a script (.py) or a reply (.md) in every version, exactly as it is (no probe appended:
        the probes run out of band in probe(), so the output tail the check shows is the script's own)."""
        d = tempfile.mkdtemp(prefix="wm-check-", dir=self.work)
        try:
            path = os.path.join(d, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            out = {}
            for v, binary in self.versions.items():
                r = blender_check.run_one(path, v, binary, self.chimera, self.work, goal=goal, probe=False,
                                          timeout=self.timeout)
                out[v] = {k: r.get(k) for k in ("outcome", "strict", "strict_why", "line", "source", "error", "seconds",
                                                "wall_s", "runner", "version_ok", "problem", "summary", "bad_lines")}
                out[v]["output_tail"] = (r.get("output") or "")[-600:]
                out[v]["stand_in_tail"] = STAND_IN in (r.get("output") or "")  # the tail only: probe()'s stand_in sees all
            return out
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def run(self, script):
        """Both runs of a .py script: {"check": check(script), "probe": probe(script)}."""
        return {"check": self.check(script), "probe": self.probe(script)}

    def probe(self, script):
        """The probes run directly, sandboxed, in every version: {version: {exit, strict_full, bad_lines, blender,
        version_ok, probe (the eval probe's JSON), ctx_keys, names, dupes (the tools probe's), stand_in, exception,
        stopped_at_render, seconds}}."""
        return {v: self._probe_one(script, binary, v) for v, binary in self.versions.items()}

    def _probe_one(self, script, binary, version=None):
        d = tempfile.mkdtemp(prefix="wm-probe-", dir=self.work)
        t0 = time.monotonic()
        try:
            path, probe_path = os.path.join(d, "script.py"), os.path.join(d, "scene_probe.py")
            with open(probe_path, "w", encoding="utf-8") as f:
                f.write(self.probe_src)
            with open(path, "w", encoding="utf-8") as f:
                f.write(probe_script(script, os.path.realpath(probe_path)))
            cmd = [binary, "-b", "--factory-startup", "--python-exit-code", "1",
                   "--python-expr", stop_at_render(os.path.realpath(probe_path)), "--python", path, "--"]
            if self.sandbox:
                cmd = ["sandbox-exec", "-p", sandbox_profile(d, binary)] + cmd
            env = {"HOME": d, "TMPDIR": d, "TMP": d, "TEMP": d, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                   "LANG": "en_US.UTF-8", "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
            try:
                p = subprocess.run(cmd, cwd=d, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   timeout=self.timeout)
                code, output = p.returncode, p.stdout
            except subprocess.TimeoutExpired as e:
                code = None
                output = (e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")) + \
                    f"\n(timed out after {self.timeout:.0f} s)"
            probe = parse_probe(output)
            tools = scene_probe.parse(output)  # tools/scene_probe.py: ctx["objects"] keys, names, .001 duplicates
            # The strict rule over the whole output, the check's own rule (blender_check.bad_lines), probe lines aside
            bad = blender_check.bad_lines(own_output(output))
            # Blender's header line, else either probe's (os._exit at a render loses the header, which isn't flushed)
            ran = blender_version(output) or (tools or {}).get("blender") or (probe or {}).get("blender")
            out = {"exit": code, "strict_full": code == 0 and not bad, "bad_lines": bad[:5], "probe": probe,
                   "blender": ran, "version_ok": None if (version is None or ran is None) else ran == version,
                   "stand_in": STAND_IN in output, "exception": _last_exception(output),
                   "stopped_at_render": WM_MARK + " stopped at the render" in output,
                   "sandboxed": self.sandbox, "seconds": round(time.monotonic() - t0, 2), "output_tail": output[-600:]}
            if tools is not None and "probe_failed" not in tools:
                out["ctx_keys"] = (tools.get("ctx") or {}).get("keys")
                out["names"] = [o["name"] for o in tools.get("objects") or []] + list(tools.get("materials") or []) + \
                    list(tools.get("collections") or [])
                out["dupes"] = tools.get("dupes") or []
            elif probe is not None:  # stopped at a render: the eval probe ran there, the tools probe didn't
                out["dupes"] = probe.get("duplicates") or []
            return out
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def check_python(self, text, name="result.md", goal=None):
        """Chimera's check of a plain-Python result (run_python): once, no Blender shim."""
        d = tempfile.mkdtemp(prefix="wm-pycheck-", dir=self.work)
        try:
            path = os.path.join(d, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            cmd = [self.chimera, "--data-dir", os.path.join(d, "data"), "--check-result", path]
            if goal:
                cmd += ["--check-goal", goal]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, cwd=d)
                j = blender_check.parse_json(p.stdout) or {}
            except subprocess.TimeoutExpired:
                j = {}
            c = j.get("check") or {}
            return {k: c.get(k) for k in ("outcome", "runner", "summary", "line", "source", "error", "seconds")}
        finally:
            shutil.rmtree(d, ignore_errors=True)
