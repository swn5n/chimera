"""The layout check of a files piece: does each .py file it writes find the project's own modules where the joined
project really puts them? (results/DATAGEN-SMOKE.md, "Second smoke run": the audit's files-layout cause and its
skeptic).

    got = layout_findings(files, own, paths=pysandbox.own_paths(), later=later_words)
    # {"ok", "checked", "skipped", "findings": [{"file", "line", "module", "statement", "found_at"}], "tell"}

Why: Go's importSeams (app/hydra_assemble.go) resolves an import by any dotted suffix of a project file's path, and
the code gate's tests and import run put every folder holding a .py file on sys.path, so `from find_cmd import
cmd_find` in a root-level contactmgr.py passes the join, the tests and the import run when the file is
src/find_cmd.py. Python doesn't: run from its own folder (`python3 contactmgr.py`) or the root, it can't see src/.
gpt-oss copies the src/ folder of Chimera's format example ("like File: src/store.py") when a step names no path (26
of its 87 files tries where nothing named src, qwen3.8 0 of 42), so smoke2's n-python-0001-02 kept src/find_cmd.py
and src/export_cmd.py beside root-level modules, and its s6 entry points imported them by bare name: X80 (the step's
kept piece) and X32 (its failed_dep variant), both bad, and the finished CLI crashed on start.

A fact of the joined project (every earlier kept piece's files, or those a variant's request was built from, plus
this piece), read in-process and statically: nothing of the project runs, and no sandbox run is needed. For every
absolute import statement of the piece's own .py blocks (module level and inside functions, imports_of), the search
is what a real run could give that file: its own folder (`python3 path`), then every folder above it to the root (a
cwd for `python3 -m`). An import is a finding only when that search finds nothing, the module isn't the
interpreter's (its top name in the standard library, or found on the interpreter's own folders: installed), and it
is a project module somewhere else (one of the dotted suffixes Go reads a project .py file or folder by), so a
dropped or left-out dependency's module never counts; `from pkg import mod` with pkg a folder here counts when mod
is only another pkg's (and pkg's own __init__.py doesn't bind it). Skipped: imports in a try with an ImportError,
ModuleNotFoundError, Exception or bare handler, imports under TYPE_CHECKING, a file that changes sys.path itself, a
block that doesn't parse alone, and a project that says how its folders get on the path (pyproject.toml, setup.py,
setup.cfg, conftest.py, pytest.ini, tox.ini, a .pth file, a PYTHONPATH line in a non-Python file) or whose later steps
name one (it may not be written yet). Only this piece's own statements are read, so an earlier step's file is never
blamed here: an earlier piece's bare sibling import inside src/ is the plan check's to find (code_gate.plan_check's
entry_layout, blaming the file whose import failed).

The analyst's check also asked Python's own PathFinder in pysandbox and imported each quiet module for real; the
skeptic dropped both. The finder gave the same 5 flags as this reading on all 181 joinable candidates, and the import
run added nothing on the data while it could blame a correct piece for an earlier file's import (a real-pieces case:
gpt-oss's src/ tries for s2-s5, s1 in src/, and s6 importing src.<module> as asked failed on data_utils, so s6 was
dropped and the faulty s2-s5 kept).

Measured on both runs' 224 files candidates and repairs (151 and 73; 181 join, 116 write their own .py, 56 passed
every other check, 46 of them with Python), as task.gate calls it (normal steps against their request's pieces,
variants alone with project=): it flags 5, all smoke2 n-python-0001-02 r1 s6 tries that had passed: the step's cand 1
(gpt-oss, kept: X80) and cand 3 (qwen3.8), the failed_dep variant's cand 0 and cand 1 (kept: X32), and the mixed_pool
variant's cand 0 (export_cmd). Run as `python3 contactmgr.py add ...` on the joined project, the first four crash on
start with ModuleNotFoundError: find_cmd, and the mixed_pool's on export_cmd with a stand-in for its unjoinable s3
(the analyst's run); the step's unflagged cand 0 and cand 2 start and add a contact. Nothing else changes: a regate of
all 152 stored code candidates with a gate record, old gate against this one, differs on those 5 alone. 0 in the
first run, 0 of the 5 ok and 8 weak graded files examples (X25 and X72 put their own file in src/ but import
data_utils, which Python finds at the root, so they run as src.*; their copying of src/ is a teacher note's to fix).
Only two files projects in these runs write Python (the contact CLI and the tasktimer package), so other layouts are
untested: a project that expects PYTHONPATH from outside its files, tests relying on pytest settings it doesn't hold,
or a later step meant to move a file could still fire. 0 of the 1,001 distinct stored replies of both runs share a
run of TELL_FORMS.

The tell line (tell_line) states the fact and where the module is, never a rule, in at most 240 characters
(hints.FAILURE_CHARS; the quoted statement gives way first): "contactmgr.py imports find_cmd (`from find_cmd import
cmd_find`), but from the project's root Python finds no find_cmd: the project has it only at src/find_cmd.py (from
the root: src.find_cmd)". TELL_FORMS is its fixed wording, ours, for hints.echoed_note.
"""
from __future__ import annotations

import ast
import os
import re
import sys
from importlib.machinery import PathFinder

from contract import validate as cv
from datagen import pysandbox

PATH_CONFIG = re.compile(r"(?:^|/)(?:pyproject\.toml|setup\.py|setup\.cfg|conftest\.py|pytest\.ini|tox\.ini|"
                         r"[^/]+\.pth)$")
_CONFIG_WORDS = re.compile(r"(?<![\w.-])(?:pyproject\.toml|setup\.py|setup\.cfg|conftest\.py|pytest\.ini|tox\.ini|"
                           r"PYTHONPATH)(?![\w-]|\.\w)")
PYTHONPATH = re.compile(r"\bPYTHONPATH\b")
_SYS_PATH = re.compile(r"\bsys\.path\b|\bsite\.addsitedir\b|\bspec_from_file_location\b")
_CATCHES = frozenset(["ImportError", "ModuleNotFoundError", "Exception", "BaseException"])
_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ())) | frozenset(sys.builtin_module_names)
STATEMENT_CHARS = 60  # of the model's import statement quoted in a tell line
LINE_CHARS = 240  # hints.FAILURE_CHARS: a longer line is cut at its end, which says where the module is

TELL = ("{file} imports {module} (`{statement}`), but from {looked} Python finds no {module}: the project has it only "
        "at {where}")
LOOKED_ROOT = "the project's root"
LOOKED_ABOVE = "{folder}/ or a folder above it"
WHERE = "{path} (from the root: {name})"
TELL_FORMS = tuple(dict.fromkeys(  # the fixed runs of 5 words or more between the model's names (echoed_note's)
    q for t in (TELL.replace("{looked}", LOOKED_ROOT), TELL.replace("{looked}", LOOKED_ABOVE), WHERE)
    for q in (p.strip(" :,/") for p in re.split(r"\(`\{\w+\}`\)|\{\w+\}", t)) if len(re.findall(r"\w+", q)) >= 5))


def module_names(path):
    """moduleNames (app/hydra_assemble.go): every dotted suffix a project file can be imported by."""
    parts = [x for x in path[:-3].split("/") if x not in ("", ".")] if path.endswith(".py") else []
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return [".".join(parts[k:]) for k in range(len(parts))]


def project_modules(files):
    """{dotted name: [paths]} of every name Go would resolve a project .py file (or a folder holding one, as a
    package, regular or namespace) by."""
    out = {}
    for p in files:
        if not p.endswith(".py"):
            continue
        for n in module_names(p):
            out.setdefault(n, []).append(p)
        d = p.split("/")[:-1]
        for k in range(len(d)):
            for j in range(k + 1):
                out.setdefault(".".join(d[j:k + 1]), []).append("/".join(d[:k + 1]) + "/")
    return out


def interpreters(module, paths=()) -> bool:
    """module is the interpreter's own: its top name is in the standard library, or PathFinder finds it on paths
    (pysandbox.own_paths: the folders the sandboxed runs import from, so installed packages count)."""
    top = (module or "").split(".")[0]
    if not top:
        return False
    if top in _STDLIB:
        return True
    try:
        return bool(paths) and PathFinder.find_spec(top, list(paths)) is not None
    except (ImportError, ValueError, OSError):
        return False


def folders(files):
    """Every folder of the project's paths, the root ("") among them, as resolve takes them."""
    out = {""}
    for p in files:
        parts = p.split("/")[:-1]
        for k in range(1, len(parts) + 1):
            out.add("/".join(parts[:k]))
    return out


def resolve(module, search, files, dirs):
    """Python's path search read on the joined tree: where module is found from the folders of search, in order ("" is
    the root): "a/b.py", or "a/b/" for a package folder (with or without __init__.py); None when it isn't. A module
    a.py has no submodules."""
    parts = module.split(".")
    for top in search:
        base = top
        for k, part in enumerate(parts):
            cand = f"{base}/{part}" if base else part
            if k == len(parts) - 1:
                if cand + ".py" in files:
                    return cand + ".py"
                if cand in dirs:
                    return cand + "/"
                break
            if cand not in dirs:
                break
            base = cand
    return None


def guards(node) -> bool:
    """node's body is a guard for an import in it: a try whose handlers catch an import's failure (ImportError,
    ModuleNotFoundError, Exception, BaseException, or a bare except; except* too), or `if TYPE_CHECKING:`. Only the
    body: a try's handlers, else and finally, and the if's else, run when the import isn't guarded."""
    if isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
        for h in node.handlers:
            if h.type is None:
                return True
            for x in (h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]):
                if (x.attr if isinstance(x, ast.Attribute) else getattr(x, "id", "")) in _CATCHES:
                    return True
        return False
    return isinstance(node, ast.If) and \
        (getattr(node.test, "attr", None) or getattr(node.test, "id", None)) == "TYPE_CHECKING"


def imports_of(code):
    """[(line, module, names or None, statement)] of code's absolute imports outside a guard (guards; relative ones
    are Go's seam's): `import a.b` gives a.b; `from a.b import c, d` gives a.b with names [c, d] (each may be a name
    or a submodule). None when code doesn't parse."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    out = []

    def walk(node, guarded):
        for field, value in ast.iter_fields(node):
            g = guarded or (field == "body" and guards(node))
            for ch in (value if isinstance(value, list) else [value]):
                if not isinstance(ch, ast.AST):
                    continue
                if isinstance(ch, (ast.Import, ast.ImportFrom)) and not g:
                    stmt = ast.unparse(ch)
                    if isinstance(ch, ast.Import):
                        out.extend((ch.lineno, a.name, None, stmt) for a in ch.names)
                    elif ch.level == 0 and ch.module:
                        out.append((ch.lineno, ch.module, [a.name for a in ch.names], stmt))
                walk(ch, g)

    walk(tree, False)
    return out


def _binds(files, init, name):
    """The package's __init__.py (init: its path) binds name at its top level, so `from pkg import name` finds it."""
    try:
        return name in cv.top_level_names(ast.parse(files.get(init) or ""))
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False


def path_config(files):
    """The project's files that say how its folders get on the path (PATH_CONFIG's, and a non-Python file with a
    PYTHONPATH line), sorted: with any, no reading here can say where Python looks (layout_findings and code_gate's
    plan-check backstop skip the project)."""
    return sorted(p for p in files if PATH_CONFIG.search(p)) + \
        sorted(p for p, b in files.items() if not p.endswith(".py") and PYTHONPATH.search(b or ""))


def search_folders(path):
    """Where a real run of the file at path could look for an absolute import: its own folder (`python3 path`), then
    every folder above it to the root ("", a cwd for `python3 -m`)."""
    here = os.path.dirname(path)
    parts = here.split("/") if here else []
    return ["/".join(parts[:k]) for k in range(len(parts), -1, -1)]


def layout_findings(files, own, paths=(), later="") -> dict:
    """The check on the joined project. files: {path: text} (paths as pysandbox.safe_path gives them); own: the
    piece's FileParts (.path, .body: its own blocks, a part's body alone); paths: the interpreter's own folders
    (interpreters); later: the later steps' words (a config they name skips the project). Returns {"ok", "checked"
    (the own .py files read), "skipped" ({path or "project": why}), "findings": [{"file", "line" (in the piece's
    own block), "module", "statement", "found_at" (project paths)}], "tell" (tell_line of each)}."""
    out = {"ok": True, "checked": [], "skipped": {}, "findings": [], "tell": []}
    cfg = path_config(files)
    if cfg:
        out["skipped"]["project"] = "it says how its folders get on the path: " + ", ".join(cfg[:3])
        return out
    m = _CONFIG_WORDS.search(later or "")
    if m:
        out["skipped"]["project"] = f"a later step names {m.group(0)}"
        return out
    mods, dirs, seen = project_modules(files), folders(files), set()
    for fp in own or ():
        try:
            path = pysandbox.safe_path(fp.path)
        except ValueError:
            continue
        if not path.endswith(".py") or path not in files:
            continue
        if _SYS_PATH.search(files[path]):
            out["skipped"][path] = "it changes sys.path itself"
            continue
        got = imports_of(fp.body)
        if got is None:  # a part that only parses where Go merges it; the file's other blocks are still read
            out["skipped"].setdefault(path, "its block doesn't parse alone")
            continue
        if path not in out["checked"]:
            out["checked"].append(path)
        search = search_folders(path)
        for line, module, names, stmt in got:
            if (path, module, stmt) in seen or interpreters(module, paths):
                continue
            seen.add((path, module, stmt))
            where = resolve(module, search, files, dirs)
            if where is None:
                if module in mods:
                    out["findings"].append({"file": path, "line": line, "module": module, "statement": stmt,
                                            "found_at": sorted(set(mods[module]))})
                continue
            if where.endswith("/"):  # a package here: a name it imports may be a submodule only another one has
                for nm in names or ():
                    sub = f"{module}.{nm}"
                    if nm != "*" and sub in mods and not resolve(sub, search, files, dirs) and \
                            not _binds(files, where + "__init__.py", nm):
                        out["findings"].append({"file": path, "line": line, "module": sub, "statement": stmt,
                                                "found_at": sorted(set(mods[sub]))})
    out["ok"] = not out["findings"]
    out["tell"] = [tell_line(f) for f in out["findings"]]
    return out


def tell_line(f):
    """What the next try's teacher hears about a finding: the fact and where the module is (TELL)."""
    here = os.path.dirname(f["file"])
    stmt = " ".join((f.get("statement") or "").split())
    if len(stmt) > STATEMENT_CHARS:
        stmt = stmt[:STATEMENT_CHARS - 1] + "…"
    files = [p for p in f["found_at"] if p.endswith(".py")]
    if files:
        where = WHERE.format(path=files[0], name=module_names(files[0])[0])
        if len(files) > 1:
            where += f" and {len(files) - 1} more"
    else:
        where = ", ".join(f["found_at"][:2])
    looked = LOOKED_ABOVE.format(folder=here) if here else LOOKED_ROOT
    line = TELL.format(file=f["file"], module=f["module"], statement=stmt, looked=looked, where=where)
    over = len(line) - LINE_CHARS
    if over > 0 and len(stmt) > 20:  # the statement gives way first, so the line keeps its end
        stmt = stmt[:max(20, len(stmt) - over - 1)] + "…"
        line = TELL.format(file=f["file"], module=f["module"], statement=stmt, looked=looked, where=where)
    return line
