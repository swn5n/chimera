"""The code gate: what a python-script or files candidate must pass before it can be a training target, the teacher's
tests and whether they count, and the plan-level check of the whole joined project (DESIGN.md, "code_gate.py and
pysandbox.py"; the plan's "Checks every candidate goes through", Code).

    gate = CodeGate(chimera, Cache(data_dir + "/cache/runs.jsonl"))
    got = gate.piece_check(plan, i, text, verdict, earlier, "python-script", tests=tests, goal=goal)
    # {"ok", "reasons", "stage", "tests", "crash", "seams", "stubs", "symbols_missing", "parse", "layout",
    #  "lazy_imports", "run", "tell", "seconds"}
    got = gate.piece_check(plan, i, text, verdict, {}, "files", goal=goal, project=inputs)   # a variant, alone
    fault = tests_fault(step["tests"], plan, i, candidates, dropped=gone, kept=text)
    # None | "tests_unreachable" | "third_party"
    fault = import_fault(kept["gate"], plan, i, candidates, dropped=gone, written=inputs)   # None | "third_party"
    no_python(candidates, "files", title + "\n" + instructions, python_project=False)   # True: no tests to write

Chimera does every join (chimera.join): the candidate after the kept pieces of the earlier steps, later steps left
out, so Go marks them failed, exactly as the project would look when this step finishes. A piece is then checked in
stages, stopping at the first that fails:
1. join: no fallback, the mode the request had, and none of the seams that break a joined project (python-script:
   join_syntax, duplicate_name, import_conflict; files: join_syntax, file_conflict, import_unresolved,
   duplicate_name, and part_not_mergeable for structured data, below; an unresolved import is excused, seam by seam,
   only when it is a dropped dependency's module, since the step was told it failed: see _Dropped, which the plan
   check shares). In files mode, no stub of another step's file either (stub_for_other_step, below).
2. compile: the piece's code and the joined script (python-script), or every merged .py file (files), with Python's
   own compile(), which never runs anything. In files mode the piece's other files are parsed too (parse_file,
   "parse:<ext>"): JSON (.json, .ipynb) with json.loads, TOML with tomllib, YAML with PyYAML's composer when it
   imports (syntax, anchors and aliases; tags such as !Ref or !include aren't constructed, so they pass), and
   JavaScript (.js, .mjs, .cjs) with `node --check` when node is on PATH, on a copy in a sandboxed run folder (it
   only parses); Go, shell, Ruby, Swift and XML with the parsers this computer has (lang_check.LocalParsers), the
   same way. What a checker can't read isn't failed (a template's {{ }}, JSX, tsconfig's comments, bash 4 or Ruby 3
   grammar are allowed), nor a part added to a file that didn't parse before it. Every result is in the gate's
   "parse", which the build's lang_check.build_drop reads for a files example nothing ran on ("unchecked_code").
3. symbols: every name the handoff's provides line gives as code (`name`, name(), or a dotted one) is a top-level
   name of the piece (a def, class, assignment or import); bare code-like words (snake_case, CamelCase) need only
   appear in the piece, since they are as often words about the code as names in it.
3b. layout_import (files): every import of the piece's own .py files finds the project's module where a real run
   looks for it, from the file's folder and the folders above it (layout.layout_findings, read on the join, nothing
   run; a variant's on the pieces its request was built from, project=). Go's join and the runs below find a module
   in any folder, so neither shows a root file importing src/find_cmd.py as find_cmd (smoke2's X80 and X32).
4. run, in pysandbox: with valid tests, the teacher's tests against the joined project (they must exit 0 and print
   "tests ok"); without them, or when they fail, an import of the project (its main() is guarded, so nothing runs
   but the definitions), which fails the piece on a definite crash, on a ModuleNotFoundError for one of the
   project's own modules that no dropped dependency explains, on a timeout (import_timeout) and on an exit
   (import_exit: sys.exit or argparse at module level).

A definite crash is the error that ended a run, of a type Chimera's judgeRun calls the script's own fault in Python
(SyntaxError, IndentationError, TabError, NameError, UnboundLocalError, AttributeError, TypeError), and it is the
piece's crash when its innermost frame in the project is this step's code: through the join's line map (chimera.locate)
for python-script, through the piece's own file blocks for files. Its shape is Go's workerCrash, its runner the
interpreter's own "Python 3.x.y" as Chimera says it (CodeGate.runner), so chimera.worker_request(..., piece=text,
crash=crash) makes Chimera's own repair request from it. A crash only ever comes from a compile or the import run,
which Chimera's own check of the joined project could show, never from a teacher test that failed.

Tests count (tests_check) only if they fail on the stub, the project of the earlier steps alone, pass on at least
one candidate, and fail on a hollow copy of the first that passes (every function and method body of its own code
made `return None`), so a test that only names this step's symbols doesn't count. The test file is a prelude, then
the teacher's code: for python-script `import project` and
`from project import *` (the joined file saved as project.py); for files, sys.path gets the project's root and every
folder holding a .py file, so both `from src.store import Store` and a sibling's `from store import Store` resolve as
Chimera's own import check resolves them, then this candidate's own quiet modules (those the import run imports:
.py files of its that only define things) are star-imported and bound as `step_modules` (the module objects, so a
test can patch a module's globals). The stub gets none, so this step's names are undefined there (a NameError), as
in python-script mode. The tests' writer never sees a candidate, and in the smoke it guessed the module 3 times in 4
when the step named no file (n-python-0001-02: add_cmd for cmd_add.py, contactmgr for find_command.py).

Two rules for files mode that Go only warns about, or not at all (both from the Nov 3 smoke):
- part_not_mergeable fails when its path is structured data (.json, .toml, .yaml, .yml, .xml, .ipynb, lockfiles,
  Pipfile: STRUCTURED). Go merges (part) blocks only for Python; anything else is appended after a blank line,
  which is fine for Markdown, .gitignore, .env or plain text, and never for these: a JSON part after a whole file is
  two objects (coding-0012-01 round 2's package.json, which only the teacher's tests caught). A non-Python part
  always gets the seam, so a part alone fails too: it can't be added to anyone's file.
- stub_for_other_step (stubs_for_others): a file the candidate writes in full that is a stub for another step's
  file. Only the stub's own evidence counts, never Go's bare placeholder warning, which fires on Slack Block Kit's
  placeholder: keys and HTML attributes. A stub is a small file (3 non-blank lines at most, or nothing but comments,
  or one comment-like key), or a longer one that holds nothing but its note: its first 3 lines say another step
  provides it, and it is a doc page whose note says placeholder or stub (an outline under it), or Python of nothing
  but stubs (a real 49-line module headed "TODO: the formatter is added in step s4." is no stub). Then one of: it
  says another step provides it ("provided by step s3", "will be written in a later step", "later steps
  overwrite"); it says it is a placeholder (TODO, stub) and a later step's title or instructions name its path; or
  it holds nothing (comments, whitespace, one comment-like key) and a later step names its path (an empty
  __init__.py is a whole file). When this step's own title or instructions name the file (its plan asked for a
  placeholder README, its .env.example, its package's __init__.py), only the stronger evidence counts: the stub
  names another step's id, or a later step's title names the path. In the smoke a first step kept such stubs (as its
  plan asked); the join keeps the first writer, so four later steps that wrote the real files dropped on
  file_conflict. That step (coding-0012-01 round 1 s1) still fails, on the 7 files later titles name.

Every result says what the next try's teacher should hear (piece_check's "tell": plain lines, teacher-only): the
seam's own message, the stub and whose file it is, the compile error, the provided names the piece lacks, the
import crash's last line. Not a failed teacher test: those tests may be wrong (13 of the smoke's 17 unconfirmed
were), and fitting them isn't the step's job.

tests_fault says when tests that never passed are clearly the tests' fault (a sandbox refusal of the process they
start, or a module only they import that no step before this one names and no candidate writes, or that only a
step outside this one's dependencies names while the kept piece wrote its own file), or that the step can't be
tested here (only a module outside the standard library the candidates import is missing: "third_party");
import_fault says the same of a kept piece no tests ran on, from its import run or from a package its functions
import that isn't installed here (lazy_imports, which the import run never reaches). A module counts as
the project's, never third_party, when a candidate writes it (or a text the caller adds: a variant's input pieces),
a step names it as a file, or an earlier code step that was dropped names it at all (outside_project: that step may
have been the one to write it; a kept one's piece is in the project, and a writing step's words write no module).
no_python says a files step has nothing to test: no candidate writes a .py file, the step's own words don't ask
for Python (names_python), and the round isn't a Python project (python_project: the caller's reading, from the
earlier kept pieces and the step's dependency pieces).

Every file the gate runs (the tests, the import, the entry point) starts with HARNESS, which writes one line before
anything of the project runs and one from an atexit hook when Python finishes on its own; CodeGate.run takes both
out of the output and keeps them as run["harness"]. That is the signal for SystemExit (G10): a run whose harness
finished with a failing exit and no traceback that ended it was ended by the project or the tests themselves
(sys.exit(1), argparse's exit 2, exit("message")), so it is the script's verdict, cached: a test failure
(tests_failed, with "SystemExit: exit N with no traceback (its last output: ...)" as its error), and import_exit
for the import run. Without the end line nothing is known about the script, as before: the interpreter didn't start
the file, or Python never finished (os._exit, a signal, a crash of the interpreter), and the run is an error. In the
smoke this was 2 of 5 candidates in a re-run of n-python-0001-02 s2, failed as run_error and never gated again.

Every sandbox run is cached in cache/runs.jsonl by key_of("python", files, entry, stdin, the interpreter's real path
and version), a parse by node by key_of("node-check", extension, text, node's real path and version), one by the
other parsers by key_of("local-parse", language, extension, arguments, text, the tool's real path, size and mtime),
and a plan check's chimera.check_result by key_of("python-check", script, goal, the binary's sha256), so a resumed
run replays them. A run that says nothing about the script (tool_failure: exit 71, 126 or 127, or another failing exit with no
Python traceback and no "tests ok", unless its harness finished) is an error, never cached.
"""
from __future__ import annotations

import ast
import builtins
import difflib
import functools
import json
import keyword
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import tomllib

from contract import validate as cv
from contract.goport import code_blocks
from datagen import lang_check, layout, pysandbox
from datagen.common import key_of
from datagen.layout import module_names
from tools import blender_check

RUNNER = "Python"  # workerCrash.runner when the interpreter's version can't be read (scriptBlocker's fallback)
DEFINITE = frozenset(["SyntaxError", "IndentationError", "TabError", "NameError", "UnboundLocalError",
                      "AttributeError", "TypeError"])  # crashType(blender=false), app/hydra_check.go
TOOL_EXITS = frozenset([71, 126, 127])  # the interpreter couldn't run (EX_OSERR, can't execute, not found)
NEAR_MISS = 0.85  # difflib ratio from which an unresolved module is taken for a misspelt present one
FAIL_SEAMS = {"python-script": frozenset(["join_syntax", "duplicate_name", "import_conflict"]),
              "files": frozenset(["join_syntax", "file_conflict", "import_unresolved", "duplicate_name"])}
TESTS_FILE = "wm_step_tests.py"
IMPORT_FILE = "wm_import.py"
ENTRY_FILE = "wm_entry.py"
TESTS_OK = "tests ok"
HARNESS_START = "wm-harness: started"  # the harness's first line, written before anything of the project runs
HARNESS_END = "wm-harness: python exited"  # its last, from an atexit hook: Python finished on its own
# Every file the gate runs (tests, import, entry) starts with this. Both lines go straight to fd 1 (stdout and stderr
# share the pipe), so buffering can't reorder them, and both are taken out of the output before anything reads it.
# Once per process: tests that import every .py file in the folder import themselves too (n-python-0001-02 s5's).
HARNESS = ("import os as _wm_os, sys as _wm_sys, atexit as _wm_atexit\n\n\n"
           "def _wm_exited():\n"
           "    for _f in (_wm_sys.stdout, _wm_sys.stderr, _wm_sys.__stdout__, _wm_sys.__stderr__):\n"
           "        try:\n"
           "            _f.flush()\n"
           "        except Exception:\n"
           "            pass\n"
           f"    _wm_os.write(1, b'\\n{HARNESS_END}\\n')\n\n\n"
           "if not hasattr(_wm_sys, '_wm_harness'):\n"
           "    _wm_sys._wm_harness = True\n"
           f"    _wm_os.write(1, b'{HARNESS_START}\\n')\n"
           "    _wm_atexit.register(_wm_exited)\n")
PROJECT = "project.py"
ENTRY_NAMES = ("main.py", "__main__.py", "cli.py", "app.py", "run.py")  # preferred entry files, in this order
_ENV_ATTR = re.compile(r"module '(os|ctypes|signal|select|socket|fcntl|termios|resource|time|msvcrt|winreg)' "
                       r"has no attribute")  # osAttrRe: this computer's doing, not the script's
_FRAME = re.compile(r'^\s*File "([^"]+)", line (\d+)(?:, in (.+))?\s*$')  # frameRe
_EXC = re.compile(r"^([A-Za-z_][\w.]*)(?:: (.*))?$")  # excRe
_CARET = re.compile(r"^\s*[~^]+\s*$")  # caretRe
_NOT_NAMES = frozenset(dir(builtins)) | frozenset(keyword.kwlist) | frozenset(["self", "cls", "none", "None"])
_FILE_EXT = frozenset(["py", "txt", "json", "csv", "md", "toml", "yaml", "yml", "ini", "cfg", "html", "htm", "js",
                       "ts", "css", "sh", "log", "db", "sqlite", "xml", "png", "jpg", "svg", "pdf", "lock", "env"])
_UNRESOLVED = re.compile(r"^(?P<path>[^:]+): (?:from (?P<dots>\.*)(?P<mod>\S*) import …|import (?P<imp>\S+)): "
                         r"no such project file$")  # importSeams' wording (app/hydra_assemble.go)
_PY_PATH = re.compile(r"[\w./-]*\w\.py\b")
_HYPHENS = "\\-\u2010\u2011\u2012"
_PY_WORD = re.compile(r"(?<![\w./" + _HYPHENS + r"])(?:[Pp]ython|PYTHON)(?:\s?3(?:\.\d+)*)?(?!\w|\.\w)(?!\s+-[A-Za-z])")
_PY_SYNTAX = re.compile(r"\bfrom\s+\.*[A-Za-z_][\w.]*\s+import\s+[\w*(]|__(?:init|main|name)__")
_NO_MODULE = re.compile(r"No module named '([^']+)'")
_NO_NAME = re.compile(r"name '([A-Za-z_]\w*)' is not defined")

# part_not_mergeable fails for these paths (appending a part to them never gives a valid file)
STRUCTURED = re.compile(r"\.(?:json|jsonc|json5|ipynb|toml|ya?ml|xml|lockb?)$|(?:^|/)Pipfile$", re.I)
_PART_SEAM = re.compile(r"^(?P<path>.+?): the \(part\) blocks from ")  # joinFiles' wording (app/hydra_assemble.go)

# parse:<ext>: what files mode checks a piece's other files with (parse_file)
PARSED = {"json": "JSON", "ipynb": "JSON", "toml": "TOML", "yaml": "YAML", "yml": "YAML", "js": "JavaScript",
          "mjs": "JavaScript", "cjs": "JavaScript"}
# JSON files their own tools read with comments and trailing commas (tsc, VS Code, ESLint, Babel, dev containers)
_JSONC = re.compile(r"(?:^|/)(?:tsconfig[\w.-]*|jsconfig[\w.-]*|\.eslintrc|\.babelrc|babel\.config|"
                    r"devcontainer)\.json$|(?:^|/)\.(?:vscode|devcontainer)/[^/]+\.json$", re.I)
_TEMPLATE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)  # Helm, Jinja, cookiecutter: not the file's own syntax
_JSX = re.compile(r"<[A-Za-z][\w.:-]*(?:\s[^<>]*)?/?>")
_NODE_ERROR = re.compile(r"^(SyntaxError: .*)$", re.M)
_ESM = re.compile(r"^[ \t]*(?:import[\s{*'\"]|export[\s{*])", re.M)
_NODE_LINE = re.compile(r"^wm_check\.\w+:(\d+)", re.M)

# stub_for_other_step: what a stub file says about whose it is
_STUB_WORDS = re.compile(r"\b(?:TODO|FIXME|placeholders?|stubs?|implement (?:this|me))\b", re.I)
_PLACEHOLDER = re.compile(r"\b(?:placeholders?|stubs?)\b", re.I)  # a doc's note for the whole page, not a part
_PAGE = re.compile(r"\.(?:md|markdown|rst)$|(?:^|/)readme[^/]*\.txt$", re.I)  # prose, not requirements.txt
_STEP_REF = (r"(?:(?:the\s+)?step\s+(s\d+)\b|(s\d+)\b|"
             r"(?:the\s+|a\s+)?(?:later|next|future|subsequent|another|other)\s+steps?\b)")
_PROVIDED_BY = [
    re.compile(r"\b(?:provided|written|implemented|defined|filled(?:\s+in)?|replaced|added|add|overwritten|populated|"
               r"completed|expanded|supplied|created|generated)\b[^\n]{0,60}?\b(?:in|by)\s+" + _STEP_REF, re.I),
    re.compile(r"\b(?:step\s+)?(s\d+)\s+(?:will\s+)?(?:writes?|provides?|implements?|fills?|replaces?|overwrites?|"
               r"defines?|creates?)\b", re.I),
    re.compile(r"\blater\s+steps?\b[^\n]{0,60}?\b(?:overwrite|replace|fill|extend|provide|write|implement|define|"
               r"populate)", re.I),
]
_COMMENT = re.compile(r"^(?:#|//|/\*|\*|<!--|-->|--|;)")
_DOC_EXT = re.compile(r"\.(?:md|markdown|txt|rst)$", re.I)  # "#" is a heading there, not a comment
_COMMENT_KEYS = frozenset(["comment", "placeholder", "todo", "note", "stub"])
_BRACKETS = re.compile(r"^[\[\]{}(),]*$")

# tests_fault
_REFUSED = re.compile(r"^(?:PermissionError|OSError)\b.*(?:Operation not permitted|Errno 1\b)")
_STARTS_PROCESS = re.compile(r"\b(?:subprocess|os\.(?:system|popen|fork|forkpty|exec\w*|spawn\w*|posix_spawn\w*)|"
                             r"multiprocessing|pty\.spawn|asyncio\.create_subprocess_\w+)\b")
_CANT_IMPORT = re.compile(r"cannot import name '[^']+' from '([^']+)'")
_IMPORT_ERROR = re.compile(r"(?:ModuleNotFoundError|ImportError)\b")
_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ())) | frozenset(sys.builtin_module_names)


# ---------------------------------------------------------------- reading a run's output

def last_error(output):
    """The last Python traceback in output (lastPyError's reading, app/hydra_check.go): {"type", "msg", "frames":
    [{"file", "line", "func", "source"}], "last"}, last saying nothing but blank lines came after it (it ended the
    run). A SyntaxError has no "Traceback" line, only its frame. None if there is none."""
    lines = (output or "").split("\n")
    cur, last, end_at, in_block = None, None, 0, False
    i = 0
    while i < len(lines):
        l = lines[i].rstrip("\r")
        if l.startswith("Traceback (most recent call last):"):
            cur, in_block = {"frames": []}, True
            i += 1
            continue
        m = _FRAME.match(l)
        if m:
            if not in_block:
                cur, in_block = {"frames": []}, True
            f = {"file": m.group(1), "line": int(m.group(2)), "func": m.group(3) or "", "source": ""}
            if i + 1 < len(lines):
                nxt = lines[i + 1].rstrip("\r")
                if nxt.startswith(" ") and not _FRAME.match(nxt) and not _CARET.match(nxt):
                    f["source"] = nxt.strip()
                    i += 1
            cur["frames"].append(f)
            i += 1
            continue
        if not in_block or l == "" or l.startswith((" ", "\t")):
            i += 1
            continue
        m = _EXC.match(l)
        if m and _exc_name(m.group(1)) and cur["frames"]:
            cur["type"], cur["msg"] = m.group(1), m.group(2) or ""
            last, end_at = cur, i
        in_block = False
        i += 1
    if last is None:
        return None
    rest = [l for l in lines[end_at + 1:] if not l.startswith((" ", "\t"))]
    last["last"] = not any(l.strip() and not l.startswith("(timed out after") for l in rest)
    return last


def _exc_name(t):
    base = t.rsplit(".", 1)[-1]
    if base in ("Error", "Warning", "Info"):
        return False
    return any(base.endswith(s) for s in ("Error", "Exception", "Exit", "Interrupt", "Iteration", "Group")) or \
        ("." in t and base.endswith("error"))


def err_line(e):
    """errLine: "Type: message", at most 300 characters."""
    s = e["type"] + (": " + e["msg"] if e.get("msg") else "")
    return s if len(s) <= 300 else s[:299] + "…"


def definite(e) -> bool:
    """The error is the script's own fault, as judgeRun reads a Python run, and it ended the run."""
    return bool(e) and e.get("last") and e["type"] in DEFINITE and not _ENV_ATTR.search(e.get("msg") or "")


def _project_frame(e, paths):
    """The innermost frame in one of the project's files (paths: relative paths)."""
    for f in reversed(e["frames"]):
        p = f["file"][2:] if f["file"].startswith("./") else f["file"]
        if p in paths:
            return dict(f, file=p)
    return None


def tests_passed(run) -> bool:
    """The tests ran to their end: exit 0, not timed out, and a line saying "tests ok"."""
    return run.get("exit") == 0 and not run.get("timed_out") and not run.get("error") and _said_ok(run)


def _said_ok(run):
    return any(l.strip() == TESTS_OK for l in (run.get("output") or "").split("\n"))


def take_harness(output):
    """(output without the harness's two lines, {"started", "ended"}): whether the harness's first line ran and
    whether Python finished on its own (its atexit hook wrote the last line)."""
    text, head, tail = output or "", HARNESS_START + "\n", "\n" + HARNESS_END + "\n"
    lines = text.split("\n")
    started, ended = HARNESS_START in lines, HARNESS_END in lines
    if text.startswith(head):
        text = text[len(head):]
    if text.endswith(tail):
        text = text[:-len(tail)]  # exactly what the hook wrote, so the output is as the script left it
    if HARNESS_START in text or HARNESS_END in text:  # elsewhere too (a warning at start-up, at shutdown)
        text = "\n".join(l for l in text.split("\n") if l not in (HARNESS_START, HARNESS_END))
    return text, {"started": started, "ended": ended}


def system_exit(run) -> bool:
    """A harnessed run that Python finished on its own with a failing exit and no traceback that ended it: the
    project or the tests raised SystemExit (sys.exit(1), argparse's exit 2 on bad arguments, exit("message")). A
    traceback at the end of the output ended the run only with exit 1, the only code an uncaught exception gives;
    after any other code it was printed and handled (traceback.print_exc(), then sys.exit(4))."""
    h = run.get("harness") or {}
    if not h.get("ended") or run.get("exit") in (0, None) or run.get("timed_out") or _said_ok(run):
        return False
    e = last_error(run.get("output"))
    return not (e and e.get("last") and run.get("exit") == 1)  # an uncaught exception always exits 1


def tool_failure(run):
    """Why a finished run says nothing about the script, or None. A harnessed run (run["harness"], the gate's own
    files) is the script's verdict once Python finished on its own, SystemExit included; it is a tool failure only
    when the harness's first line never ran (the interpreter didn't start the file) or Python never finished, with
    no traceback to say why (os._exit, a signal, a crash of the interpreter). Any other run: the interpreter couldn't
    run (exit 71, 126 or 127, as the Xcode shim's "couldn't spawn" in the sandbox), or it failed with no Python
    traceback and no "tests ok" line (sandbox-exec refusing, a crash of the interpreter itself). A timeout is the
    script's own."""
    x = run.get("exit")
    if x in (0, None):
        return None
    h = run.get("harness")
    if h is not None:
        if h.get("ended"):
            return None
        if not h.get("started"):
            return f"the interpreter couldn't run the script (exit {x})" if x in TOOL_EXITS else \
                f"the interpreter didn't start the script (exit {x})"
    elif x in TOOL_EXITS:
        return f"the interpreter couldn't run the script (exit {x})"
    if last_error(run.get("output")) is None and not _said_ok(run):
        return f"exit {x} with no Python traceback" + (", and Python didn't finish" if h is not None else "")
    return None


def _run_error(run):
    """What a failed run says: the last error's line, a SystemExit's exit code and last line of output, else its last
    line of output."""
    e = last_error(run.get("output"))
    if e and not system_exit(run):
        return err_line(e)
    if run.get("error"):
        return run["error"]
    if run.get("exit") == 0:
        return f"exited 0 without printing {TESTS_OK!r}"
    tail = [l.strip() for l in (run.get("output") or "").split("\n") if l.strip()]
    if system_exit(run):
        said = f" (its last output: {tail[-1][:200]})" if tail else ""
        return f"SystemExit: exit {run.get('exit')} with no traceback{said}"
    return tail[-1][:300] if tail else f"exit {run.get('exit')}"


# ---------------------------------------------------------------- the provides line

_BACKTICK = re.compile(r"`([^`\n]+)`")
_QUOTED = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'")
_DOTTED = r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*"
_LEAD = re.compile(r"^\s*(?:def\s+|class\s+)?(" + _DOTTED + r")\s*(\(.*)?$")
_CALL = re.compile(r"(?<![\w.])(" + _DOTTED + r")\(")
_WORD = re.compile(r"(?<![\w./\\-])(" + _DOTTED + r")(?![\w/\\-]|\.\w)")
_ARGS = re.compile(r"\(([^()]+)\)")


def provided_symbols(provides):
    """(strict, loose): the names a provides line gives as code. strict are written as code, `name` or name() or a
    dotted one of those; loose are bare code-like words (snake_case, CamelCase inside, a.b). Builtins, keywords,
    paths and file names are left out, and so are arguments: count_words(text, top_n=10) gives count_words only."""
    text = provides or ""
    strict, loose = [], []

    def add(out, name):
        name = name.strip(".")
        first = name.split(".")[0]
        if not name or first in _NOT_NAMES or name.split(".")[-1].lower() in _FILE_EXT or len(name) < 2:
            return
        if name.startswith("__") and name.endswith("__"):
            return
        if name not in strict and name not in loose:
            out.append(name)

    for m in _BACKTICK.finditer(text):
        lead = _LEAD.match(m.group(1))
        if lead and "/" not in m.group(1).split("(")[0]:
            add(strict, lead.group(1))
    text = _QUOTED.sub(" ", _BACKTICK.sub(" ", text))
    while True:  # arguments go, innermost first: (text, top_n=10) -> ()
        nxt = _ARGS.sub("()", text)
        if nxt == text:
            break
        text = nxt
    for m in _CALL.finditer(text):
        add(strict, m.group(1))
    for m in _WORD.finditer(text):
        w = m.group(1)
        if "." in w or "_" in w.strip("_") or re.search(r"[a-z][A-Z]", w):
            add(loose, w)
    return strict, loose


def _whole_word(hay, word):
    return re.search(r"(?<![\w])" + re.escape(word) + r"(?![\w])", hay) is not None


def missing_symbols(provides, tops, hay):
    """The provided names a piece doesn't have. tops: its top-level names (and, for files, its module names); hay:
    the piece's code (and prose) a loose or dotted name may be found in."""
    strict, loose = provided_symbols(provides)
    missing = []
    for name in strict:
        first, *rest = name.split(".")
        if name in tops or (first in tops and all(_whole_word(hay, x) for x in rest)):
            continue
        missing.append(name)
    for name in loose:
        if not all(_whole_word(hay, x) for x in name.split(".")):
            missing.append(name)
    return missing


# ---------------------------------------------------------------- the gate

class CodeGate:
    """The gate for python-script and files steps. chimera: datagen.chimera.Chimera; cache: a common.Cache for runs
    (None: nothing cached); work: where run folders go ($WM_SCRATCH or data/scratch); jobs: Python processes at once.
    python is the interpreter every run uses (pysandbox.python3()), runner what it says it is ("Python 3.13.12", as
    Chimera's check names it) and own_paths where it imports its own modules from (pysandbox.own_paths: what counts as
    installed), read once here; local the other languages' parsers (lang_check.LocalParsers), cached with the runs."""

    def __init__(self, chimera, cache, work=None, jobs=4, timeout=pysandbox.TIMEOUT):
        self.chimera, self.cache, self.timeout = chimera, cache, timeout
        self.work = blender_check.scratch_root(work)
        self._slots = threading.Semaphore(jobs)
        self.python = pysandbox.python3()
        self.runner = pysandbox.version(self.python) or RUNNER
        self.own_paths = pysandbox.own_paths(self.python)
        self.node = shutil.which("node")
        self.node_version = pysandbox.tool_version(self.node) if self.node else ""
        self.local = lang_check.LocalParsers(cache, self.work)

    # ------------------------------------------------------------ runs

    def run(self, files, entry, stdin="") -> dict:
        """pysandbox.run, cached. A run that couldn't start, or that says nothing about the script (tool_failure),
        has an "error" and isn't cached, so it is tried again. When the entry starts with HARNESS (the gate's own
        files), its two lines are taken out of the output and kept as "harness"."""
        key = key_of("python", files, entry, stdin, os.path.realpath(self.python), self.runner)
        if self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                return dict(hit, cached=True)
        with self._slots:
            got = pysandbox.run(files, entry, timeout=self.timeout, stdin=stdin, work=self.work, python=self.python)
        if (files.get(entry) or "").startswith(HARNESS):
            got["output"], got["harness"] = take_harness(got.get("output"))
        if not got.get("error") and tool_failure(got):
            got["error"] = tool_failure(got)
        if self.cache is not None and not got.get("error"):
            self.cache.put(key, got)
        return dict(got, cached=False)

    def _check(self, script, goal):
        """chimera.check_result of a joined python-script, cached: {check, critique, exit, stated}."""
        key = key_of("python-check", script, goal or "", self.chimera.sha256())
        if self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                return dict(hit, cached=True)
        d = tempfile.mkdtemp(prefix="wm-pycheck-", dir=self.work)
        try:
            path = os.path.join(d, PROJECT)
            with open(path, "w", encoding="utf-8") as f:
                f.write(script)
            with self._slots:
                rec = self.chimera.check_result(path, goal=goal or None, work_dir=d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        c = rec.get("check") or {}
        got = {"check": {k: c.get(k) for k in ("outcome", "runner", "summary", "line", "source", "error", "seconds")},
               "critique": rec.get("critique") or "", "exit": rec.get("exit"), "stated": rec.get("stated")}
        if self.cache is not None:
            self.cache.put(key, got)
        return dict(got, cached=False)

    def node_check(self, ext, body) -> dict:
        """`node --check` of body saved as wm_check.<ext> in a run folder (pysandbox.run_tool: the script profile,
        the watchdog; node only parses, it runs nothing), cached by the body, the extension and node's real path and
        version: {"ok", "error" (its SyntaxError line), "line"}, or {"skipped": why} without node or when the run
        says nothing (an error, a timeout: not cached). A .js file with import or export statements is checked as
        .mjs: node 24 takes such a file for a module and then --check passes it unread (a broken one too)."""
        if not self.node or not self.node_version:
            return {"skipped": "no node on PATH"}
        if ext == "js" and _ESM.search(body):
            ext = "mjs"
        key = key_of("node-check", ext, body, os.path.realpath(self.node), self.node_version)
        if self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                return dict(hit, cached=True)
        name = "wm_check." + ext
        with self._slots:
            run = pysandbox.run_tool({name: body}, self.node, ["--check", name], work=self.work)
        out = run.get("output") or ""
        if run.get("exit") == 0 and not run.get("error"):
            got = {"ok": True, "error": None, "line": 0}
        elif run.get("exit") == 1 and _NODE_ERROR.search(out):
            m = _NODE_LINE.search(out)
            got = {"ok": False, "error": _NODE_ERROR.search(out).group(1)[:300], "line": int(m.group(1)) if m else 0}
        else:
            return {"skipped": run.get("error") or ("timed out" if run.get("timed_out") else
                                                    f"node exited {run.get('exit')} with no SyntaxError")}
        if self.cache is not None:
            self.cache.put(key, got)
        return dict(got, cached=False)

    def parse_file(self, path, body) -> dict | None:
        """The parse check of one of a files piece's other files, by its extension (PARSED): JSON (.json, .ipynb;
        with comments and trailing commas for the files their own tools read so, _JSONC), TOML (tomllib), YAML
        (PyYAML's composer, every document, only when it imports: _parse_data) and JavaScript (.js, .mjs, .cjs:
        node_check); and, by lang_check.LOCAL_EXT, Go (.go), shell (.sh, .bash, .zsh), Ruby (.rb), Swift (.swift) and
        XML (.xml, .plist, .svg, .csproj) with the parsers this computer has (lang_check.LocalParsers: gofmt -e,
        bash -n, zsh -n, bash --posix -n for #!/bin/sh, ruby -c, xmllint, swift-frontend -parse, each sandboxed on a
        copy; none of them runs the file). None for a path it doesn't check; else {"path", "kind", "ok", "error",
        "line"}, or {"path", "kind", "skipped": why} when it can't be told: no checker here, a template ({{ }} or
        {% %}, Helm's or Jinja's, which isn't the file's own syntax), JSX or Flow in a .js file (node can't read
        them), bash 4 or Ruby 3 grammar the system's bash 3.2 and Ruby 2.6 can't read, or a tool that said nothing.
        Every result lands in the gate's "parse" (piece_check), the local parsers' too: it is the one record of what
        was parsed that lang_check.unchecked_code reads (there is no separate key for them)."""
        ext = path.rsplit(".", 1)[-1].lower() if "." in os.path.basename(path) else ""
        kind = PARSED.get(ext) or lang_check.LOCAL_EXT.get(ext)
        if kind is None:
            return None
        out = {"path": path, "kind": kind}
        if kind in lang_check.LOCAL:
            with self._slots:
                got = self.local.check(kind, body, path)
            if got.get("skipped"):
                return dict(out, skipped=got["skipped"])
            err, line = got["error"], got["line"]
        elif kind == "JavaScript":
            got = self.node_check(ext, body)
            if got.get("skipped"):
                return dict(out, skipped=got["skipped"])
            err, line = got["error"], got["line"]
            if err and (_JSX.search(body) and re.search(r"Unexpected token '?<|Unexpected token '?>", err) or
                        re.search(r"@flow\b", body)):
                return dict(out, skipped="jsx or flow, which node can't read")
        else:
            got = _parse_data(kind, body, bool(_JSONC.search(path)))
            if got is None:
                return dict(out, skipped="PyYAML isn't installed")
            err, line = got
        if err and _TEMPLATE.search(body):
            return dict(out, skipped="a template")
        return dict(out, ok=not err, error=err, line=line)

    # ------------------------------------------------------------ plans and projects

    @staticmethod
    def _by_sid(plan, pieces):
        """{sid: text} from pieces keyed by the cleaned plan's ids or by worker names ("s2"), as blender_gate.by_id
        reads them: a plan id first. Unknown keys and empty texts are dropped."""
        steps = plan.get("steps") or []
        ids = [st.get("id") for st in steps]
        out = {}
        for k, text in (pieces or {}).items():
            if not text:
                continue
            if k in ids:
                out[f"s{ids.index(k) + 1}"] = text
            elif re.fullmatch(r"s\d+", str(k)) and 1 <= int(k[1:]) <= len(steps):
                out[k] = text
        return out

    def _outputs(self, plan, by_sid):
        """{sid: text} as the join's outputs, keyed by the cleaned plan's step ids."""
        out = {}
        for k, st in enumerate(plan.get("steps") or []):
            sid = f"s{k + 1}"
            if by_sid.get(sid):
                out[st.get("id") or sid] = by_sid[sid]
        return out

    def _deps(self, plan, i):
        steps = plan.get("steps") or []
        ids = {st.get("id") or f"s{k + 1}": f"s{k + 1}" for k, st in enumerate(steps)}
        return [ids[d] for d in (steps[i].get("depends_on") or []) if d in ids]

    def _join(self, plan, by_sid, goal):
        return self.chimera.join(plan, self._outputs(plan, by_sid), goal=goal or "")

    @staticmethod
    def _files(joined, mode):
        """The joined project as {path: text} (python-script: project.py), or raises ValueError for a path that
        would leave the run folder."""
        if mode == "python-script":
            script = joined.get("script") if joined.get("script_kind") == "run_python" else None
            return {PROJECT: script or ""}
        files = {}
        for f in joined.get("files") or []:
            files[pysandbox.safe_path(f["path"])] = (f.get("body") or "") + "\n"
        return files

    @staticmethod
    def _prelude(files, mode, mods=()):
        """What a test or import run starts with: python-script imports the project; files puts the project's
        folders on sys.path, then (mods: the step's own quiet modules, for tests) star-imports each and binds them
        as step_modules."""
        if mode == "python-script":
            return 'import sys\nsys.path.insert(0, ".")\nimport project\nfrom project import *\n'
        dirs = ["."] + sorted({os.path.dirname(p) for p in files if p.endswith(".py") and os.path.dirname(p)})
        head = "import sys\nsys.path[:0] = %r\n" % dirs
        if mods:
            head += "".join(f"from {m} import *\n" for m in mods)
            head += ("import importlib as _wm_importlib\n"
                     "step_modules = [_wm_importlib.import_module(_m) for _m in %r]\n" % list(mods))
        return head

    def _with_tests(self, files, mode, tests_code, own=()):
        """files with the test file added: the prelude (the step's own modules for files mode: own, its FileParts;
        none for the stub), then the teacher's code."""
        out = dict(files)
        mods = _step_modules(files, own) if mode == "files" else ()
        out[TESTS_FILE] = HARNESS + self._prelude(files, mode, mods) + "\n" + tests_code.rstrip("\n") + "\n"
        return out

    def _own(self, plan, i, text):
        """A files candidate's own FileParts, as the validator reads them (contract.validate)."""
        return cv.validate_piece(text, "files", sid=f"s{i + 1}", deps=self._deps(plan, i),
                                 lone=len(plan.get("steps") or []) == 1, reject_cut=False, max_tokens=None).files

    # ------------------------------------------------------------ where a crash is

    def _crash_python(self, joined, sid, e):
        """A python-script crash in this step's part of project.py, through the join's line map."""
        f = _project_frame(e, {PROJECT})
        if f is None or not joined.get("linemap"):
            return None
        spot = self.chimera.locate([{"linemap": joined["linemap"], "script": joined.get("script"), "check": {
            "outcome": "failed", "line": f["line"], "error": err_line(e), "source": f["source"],
            "runner": self.runner}}])[0]
        if spot.get("repair") != sid:
            return None
        source = f["source"] or _line_at(joined.get("script"), f["line"])
        return {"step": sid, "part": spot.get("part") or "", "function": spot.get("function") or "",
                "piece_line": spot.get("piece_line") or 0, "line": f["line"], "source": source,
                "error": err_line(e), "runner": self.runner}

    def _crash_files(self, files, own, sid, e):
        """A files crash in one of this step's blocks: own is the piece's own FileParts (contract.validate)."""
        f = _project_frame(e, set(files))
        if f is None:
            return None
        source = f["source"] or _line_at(files.get(f["file"]), f["line"])
        line = _block_line(own, f["file"], files.get(f["file"]) or "", f["line"], source)
        if not line:
            return None
        func = f["func"] if f["func"] and f["func"] != "<module>" else ""
        return {"step": sid, "part": "code", "function": f"{func} in {f['file']}" if func else f["file"],
                "piece_line": line, "line": f["line"], "source": source, "error": err_line(e),
                "runner": self.runner}

    def _crash(self, mode, joined, files, own, sid, run):
        e = last_error(run.get("output"))
        if run.get("exit") in (0, None) or not definite(e):
            return None
        if mode == "python-script":
            return self._crash_python(joined, sid, e)
        return self._crash_files(files, own, sid, e)

    # ------------------------------------------------------------ a candidate

    def piece_check(self, plan, i, text, verdict, earlier, mode, tests=None, *, goal="", project=None) -> dict:
        """Check candidate text for step i (verdict: the Go validator's for it; earlier: {sid: text} of the kept pieces
        of earlier steps, a dropped step left out; tests: the step's tests, a string or tests_check's record with
        "code" and "valid", run only when valid). goal is the seed's text, which Chimera's mode choice reads.
        Returns {"ok", "reasons", "stage" (where it stopped: join, compile, symbols, layout_import, run, or done),
        "tests" (the tests run: {"passed", "error", "exit", "timed_out", "seconds"}) or None, "crash" (Go's
        workerCrash, runner self.runner, from the compile or the import run only) or None, "seams", "excused" (the
        seams a dropped dependency explains, when there are any), "stubs" (files mode: the paths of
        stub_for_other_step), "symbols_missing", "compile_error", "parse" (files mode: parse_file's result for each of
        the piece's other files it checks, the local parsers' included, when there are any: what
        lang_check.unchecked_code reads), "layout" (files mode, once the layout stage ran: layout.layout_findings'
        {"checked", "skipped", "findings"}), "lazy_imports" (once the run stage is reached: _lazy_imports, for
        import_fault), "run" (the import run when there were no tests or they failed, with "missing" when it ended on a
        ModuleNotFoundError), "tell" (plain lines for the next try's teacher; empty when it passed), "seconds"}.

        project (files mode): {plan id or sid: text} of the pieces the step's request was built from, for the layout
        stage alone; a variant, otherwise checked alone (earlier {}), passes its inputs here, so its imports are read
        against the project it was written for (smoke2's X32). None: the layout stage reads the gate's own join
        (earlier plus this piece). An input Chimera can't join with it (a mixed_pool dependency written under today's
        prompt) is left out, as a failed step would be.

        What ran on the piece: "tests" is set when the teacher's tests ran on it (passed or not), and "run" when the
        import run did (python-script: whenever valid tests didn't pass; files: only when the piece writes a .py
        module that only defines things, _step_modules), whatever it ended on ("exit", "error", "missing"). A gate
        with both None ran nothing of the piece: only the join, compile() (which runs nothing) and, in files mode,
        the parse checks ("parse") and the layout reading (which runs nothing either) read it. A passing piece's
        "stage" is then "done" all the same."""
        t0 = time.monotonic()
        sid = f"s{i + 1}"
        out = {"ok": False, "reasons": [], "stage": "join", "tests": None, "crash": None, "seams": [], "stubs": [],
               "symbols_missing": [], "compile_error": None, "run": None, "tell": []}

        def done(stage=None):
            out["stage"] = stage or out["stage"]
            out["ok"] = not out["reasons"]
            if out["ok"]:
                out["stage"] = "done"
                out["tell"] = []
            out["seconds"] = round(time.monotonic() - t0, 3)
            return out

        if mode not in FAIL_SEAMS:
            raise ValueError(f"not a code mode: {mode!r}")
        if verdict is None:
            verdict = self._verdict(plan, i, text, mode, goal)
        pieces = {k: v for k, v in self._by_sid(plan, earlier).items() if k != sid}
        pieces[sid] = text
        joined = self._join(plan, pieces, goal)
        mine = next((p for p in joined.get("pieces") or [] if p.get("sid") == sid), None)
        if mine is not None and mine.get("mode") != mode:  # the request had another mode: goal not passed?
            out["reasons"].append("mode_mismatch")
            return done()
        if joined.get("fallback") or mine is None:
            out["reasons"].append("join_fallback")
            out["join_reasons"] = list(joined.get("reasons") or [])
            if out["join_reasons"]:
                out["tell"].append("Chimera couldn't join it: " + "; ".join(out["join_reasons"][:3]))
            return done()
        known = set(pieces)
        dropped = _Dropped(plan, known, joined)
        for s in joined.get("seams") or []:
            if not seam_breaks(s, mode) or (s.get("step") and s["step"] not in known):
                continue
            if dropped.seam_excused(s):
                out.setdefault("excused", []).append(s)  # the file it imports was a dropped dependency's
                continue
            out["seams"].append(s)
            r = "seam:" + s["code"]
            if r not in out["reasons"]:
                out["reasons"].append(r)
            out["tell"].append(seam_line(s))
        own = self._own(plan, i, text) if mode == "files" else []
        if mode == "files":
            for path, owner in stubs_for_others(plan, i, own):
                out["stubs"].append(path)
                if "stub_for_other_step" not in out["reasons"]:
                    out["reasons"].append("stub_for_other_step")
                out["tell"].append(f"it writes {path}, which {'step ' + owner if owner else 'a later step'} owns: "
                                   "write only the files your step owns")
        try:
            files = self._files(joined, mode)
        except ValueError as e:
            out["reasons"].append("bad_path")
            out["compile_error"] = str(e)
            out["tell"].append(f"a File: path leaves the project's folder ({e})")
            return done()
        if out["reasons"]:
            return done()

        # 2. compile
        if mode == "python-script":
            code = verdict.get("code") or mine.get("code") or ""
            err = _compile(code, f"{sid}.py")
            if err:
                out["reasons"].append("compile")
                out["compile_error"] = err["error"]
                out["tell"].append(f"it doesn't compile: line {err['line']}: {err['error']}")
                where = _enclosing(code, err["line"])
                part = "import" if not where and re.match(r"(?:import|from)\s", err["source"]) else "code"
                out["crash"] = {"step": sid, "part": part, "function": where, "piece_line": err["line"], "line": 0,
                                "source": err["source"], "error": err["error"], "runner": self.runner}
                return done("compile")
            err = _compile(files[PROJECT], PROJECT)
            if err:
                out["reasons"].append("join_compile")
                out["compile_error"] = err["error"]
                out["tell"].append(f"joined after the earlier steps' code it doesn't compile: {err['error']}")
                return done("compile")
        else:
            for path, body in files.items():
                if not path.endswith(".py"):
                    continue
                err = _compile(body, path)
                if err:
                    out["reasons"].append("compile")
                    out["compile_error"] = f"{path}: {err['error']}"
                    out["tell"].append(f"{path} doesn't compile once joined: line {err['line']}: {err['error']}")
                    line = _block_line(own, path, body, err["line"], err["source"])
                    if line:
                        out["crash"] = {"step": sid, "part": "code", "function": path, "piece_line": line,
                                        "line": err["line"], "source": err["source"], "error": err["error"],
                                        "runner": self.runner}
                    return done("compile")
            self._parse_own(out, files, own)
            if out["reasons"]:
                return done("compile")

        # 3. symbols
        provides = ((verdict.get("handoff") or {}).get("provides")) or ""
        if mode == "python-script":
            tops = set(_top_names(code))
            hay = (verdict.get("body") or text)
        else:
            tops, hay = set(), verdict.get("body") or text
            for fp in own:
                if fp.path.endswith(".py") or cv.python_lang(fp.lang):
                    tops.update(_top_names(fp.body))
                    tops.update(module_names(fp.path))
                    for m in module_names(fp.path):
                        tops.update(m.split("."))
                else:
                    tops.update(re.findall(r"[A-Za-z_]\w*", fp.body))  # another language: its words
        missing = missing_symbols(provides, tops, hay)
        if missing:
            out["symbols_missing"] = missing
            out["reasons"].append("symbols_missing")
            out["tell"].append(f"its handoff's provides line names {', '.join(missing)}, which the piece doesn't "
                               "define")
            return done("symbols")

        # 3b. layout (files): the piece's imports as a real run finds them, which neither Go's join nor the runs
        # below show (both find a module in any folder)
        if mode == "files":
            self._layout(out, plan, i, text, own, files, project, goal)
            if out["reasons"]:
                return done("layout_import")

        # 4. run
        out["lazy_imports"] = self._lazy_imports(code if mode == "python-script" else "", own)
        code_tests, valid = _tests_of(tests)
        if code_tests and valid:
            run = self.run(self._with_tests(files, mode, code_tests, own), TESTS_FILE)
            ok = tests_passed(run)
            out["tests"] = {"passed": ok, "error": None if ok else _run_error(run), "exit": run.get("exit"),
                            "timed_out": run.get("timed_out"), "seconds": run.get("seconds"),
                            "sandboxed": run.get("sandboxed"), "cached": run.get("cached")}
            if run.get("error"):
                out["reasons"].append("run_error")
                return done("run")
            if ok:
                return done("run")
            # A failed teacher test is never a crash to repair from (Chimera's check can't show it); the import run
            # below is, so a crash on import still gets its repair.
            out["reasons"].append("tests_failed")
        self._import_run(out, joined, files, mode, own, sid, dropped, code if mode == "python-script" else "")
        return done("run")

    def _parse_own(self, out, files, own):
        """The parse check (parse_file) of every file of the piece's own (own: its FileParts) that isn't Python, as
        merged, into out: "parse" (every result), and a reason "parse:<ext>" and a tell line for each that fails. A
        part (JavaScript: a structured part already failed on its seam) is blamed only when the file before it was
        added still parses: an earlier step's broken file isn't this piece's."""
        seen = set()
        for fp in own:
            try:
                path = pysandbox.safe_path(fp.path)
            except ValueError:
                continue
            if path in seen or path not in files or path.endswith(".py"):
                continue
            seen.add(path)
            got = self.parse_file(path, files[path])
            if got is None:
                continue
            out.setdefault("parse", []).append(got)
            if got.get("skipped") or got["ok"]:
                continue
            mine = "\n\n".join(x.body.rstrip("\n") for x in own if x.path == fp.path and x.part)  # as Go joins
            merged = files[path].rstrip("\n")
            if mine and merged.endswith(mine):
                before = merged[:len(merged) - len(mine)].rstrip("\n")
                was = self.parse_file(path, before + "\n") if before.strip() else {"ok": True}
                if not was or was.get("skipped") or not was.get("ok"):
                    got["skipped"] = "the file didn't parse before this piece's part either"
                    continue
            ext = path.rsplit(".", 1)[-1].lower()
            if "parse:" + ext not in out["reasons"]:
                out["reasons"].append("parse:" + ext)
            at = f"line {got['line']}: " if got.get("line") else ""
            out["tell"].append(f"{path} isn't valid {got['kind']}: {at}{got['error']}")

    def _layout(self, out, plan, i, text, own, files, project, goal):
        """The layout stage (layout.layout_findings) into out: "layout", and the reason "layout_import" with a tell
        line per finding. files: the gate's own join (earlier plus this piece); project: the pieces the request was
        built from (a variant's inputs), joined anew with this piece, or None for files. The later steps' words go
        along, since a config they name (pyproject.toml, PYTHONPATH) may say how the folders get on the path. Starts
        no repair: Chimera's own check can't show it (a ModuleNotFoundError isn't one of its crash types)."""
        if project is not None:
            files = self._project_files(plan, i, text, project, goal)
            if files is None:
                out["layout"] = {"checked": [], "skipped": {"project": "the request's pieces don't join"},
                                 "findings": []}
                return
        later = "\n".join(_step_words(st) for st in (plan.get("steps") or [])[i + 1:])
        got = layout.layout_findings(files, own, self.own_paths, later)
        out["layout"] = {k: got[k] for k in ("checked", "skipped", "findings")}
        if not got["ok"]:
            out["reasons"].append("layout_import")
            out["tell"].extend(got["tell"])

    def _project_files(self, plan, i, text, project, goal):
        """{path: text} of the join of project ({plan id or sid: text}) and this piece, with an input Chimera can't
        join left out as a failed step would be; None when this piece itself doesn't join with them."""
        sid = f"s{i + 1}"
        pieces = {k: v for k, v in self._by_sid(plan, project).items() if k != sid}
        pieces[sid] = text
        joined = self._join(plan, pieces, goal)
        if joined.get("fallback"):
            bad = {r.split(":", 1)[0] for r in joined.get("reasons") or [] if re.match(r"s\d+:", r)} - {sid}
            if not bad:
                return None
            joined = self._join(plan, {k: v for k, v in pieces.items() if k not in bad}, goal)
            if joined.get("fallback"):
                return None
        try:
            return self._files(joined, "files")
        except ValueError:
            return None

    def _lazy_imports(self, code, own):
        """The modules the piece's own code (python-script: code; files: its own .py blocks) imports only inside a
        function body, unguarded (lazy_imports), that are neither the standard library's nor installed for the runs'
        interpreter (layout.interpreters on own_paths): what the import run never executes, for import_fault."""
        bodies = [code] if code else [fp.body for fp in own or () if fp.path.endswith(".py") or cv.python_lang(fp.lang)]
        return sorted({m for b in bodies for m in lazy_imports(b) if not layout.interpreters(m, self.own_paths)})

    def _import_run(self, out, joined, files, mode, own, sid, dropped, verdict_code=""):
        """The import run (_import_file) into out: "run", its reasons and "crash" (a definite crash in this piece).
        When it ended on a ModuleNotFoundError, run["missing"] says for which module, whether it is the project's
        (a project file's module or package) and whether this piece's own code imports it (verdict_code: a
        python-script piece's code; a files piece's are its .py blocks), for import_fault."""
        entry = self._import_file(files, mode, own)
        if entry is None:
            return
        run = self.run(dict(files, **{IMPORT_FILE: entry}), IMPORT_FILE)
        e = last_error(run.get("output"))
        out["run"] = {"exit": run.get("exit"), "error": None if run.get("exit") == 0 else _run_error(run),
                      "timed_out": run.get("timed_out"), "seconds": run.get("seconds"),
                      "sandboxed": run.get("sandboxed"), "cached": run.get("cached")}
        if run.get("error"):
            out["reasons"].append("run_error")
        elif run.get("timed_out"):
            out["reasons"].append("import_timeout")  # an import does nothing but define things: it never takes 30 s
            out["tell"].append(f"importing it didn't finish in {self.timeout:g} s: nothing should run when it is "
                               "imported")
        elif system_exit(run):
            out["reasons"].append("import_exit")  # sys.exit or argparse at module level: as above, nothing should run
            out["tell"].append(f"importing it exited (exit {run.get('exit')}) before it finished: nothing should run "
                               "when it is imported")
        elif run.get("exit") != 0 and (definite(e) or dropped.own_module_missing(e, files)):
            out["reasons"].append("import_crash")
            out["tell"].append(f"importing it crashed: {out['run']['error']}")
        if e and e.get("last") and e.get("type") == "ModuleNotFoundError" and _NO_MODULE.search(e.get("msg") or ""):
            module = _NO_MODULE.search(e["msg"]).group(1)
            code = [(verdict_code or "")] if mode == "python-script" else \
                [fp.body for fp in own if fp.path.endswith(".py") or cv.python_lang(fp.lang)]
            out["run"]["missing"] = {"module": module,
                                     "project": _top(module) in dropped.tops or module in dropped.modules,
                                     "piece": any(_imports_module(_imports_of(c), module) for c in code)}
        out["crash"] = self._crash(mode, joined, files, own, sid, run)

    def _verdict(self, plan, i, text, mode, goal):
        """The Go validator's verdict, when the caller has none."""
        sid = f"s{i + 1}"
        return self.chimera.validate([{"text": text, "mode": mode, "sid": sid, "deps": self._deps(plan, i),
                                       "lone": len(plan.get("steps") or []) == 1, "step": plan["steps"][i]}])[0]

    @staticmethod
    def _import_file(files, mode, own):
        """What the import run runs: the project imported (python-script), or this step's own .py modules that do
        nothing but define things when imported (files). None if there's nothing to import."""
        if mode == "python-script":
            return HARNESS + 'import sys\nsys.path.insert(0, ".")\nimport project\n'
        mods = _step_modules(files, own)
        if not mods:
            return None
        return HARNESS + CodeGate._prelude(files, mode) + "".join(f"import {m}\n" for m in mods)

    # ------------------------------------------------------------ the teacher's tests

    def tests_check(self, plan, i, tests_code, earlier, candidates, mode, *, goal="") -> dict:
        """Do the teacher's tests for step i count? They must fail on the stub (the project of the earlier steps
        alone: this step's names missing), pass on at least one candidate (texts), and fail on a hollow copy of the
        first that passes (hollow_piece: its own functions and methods return None), so tests that only import or
        name this step's symbols don't count. In files mode each candidate's run (and the hollow copy's) has its own
        quiet modules star-imported first, the stub's none. Returns {"valid", "why" ("" when valid; no_tests,
        tests_syntax, run_error, passes_on_stub, no_candidate_passed, no_candidates, passes_on_hollow),
        "stub_failed", "passed": [bool per candidate], "stub": {exit, error, timed_out}, "errors": [str|None per
        candidate], "hollow": {candidate, exit, error, timed_out} or None (nothing in it to hollow)}. The hollow copy
        is only run, never kept."""
        out = {"valid": False, "why": "", "stub_failed": None, "passed": [False] * len(candidates or []),
               "stub": None, "errors": [None] * len(candidates or []), "hollow": None}
        if mode not in FAIL_SEAMS:
            raise ValueError(f"not a code mode: {mode!r}")
        if not (tests_code or "").strip():
            out["why"] = "no_tests"
            return out
        if _compile(tests_code, TESTS_FILE):
            out["why"] = "tests_syntax"
            return out
        sid = f"s{i + 1}"
        base = {k: v for k, v in self._by_sid(plan, earlier).items() if k != sid}
        stub_join = self._join(plan, base, goal) if base else {}
        try:
            stub_files = self._files(stub_join, mode) if base and not stub_join.get("fallback") else \
                self._files({}, mode)
        except ValueError:
            stub_files = self._files({}, mode)
        stub = self.run(self._with_tests(stub_files, mode, tests_code), TESTS_FILE)
        out["stub"] = {"exit": stub.get("exit"), "error": _run_error(stub) if not tests_passed(stub) else None,
                       "timed_out": stub.get("timed_out")}
        if stub.get("error"):  # a run that couldn't start says nothing about the tests
            out["why"] = "run_error"
            return out
        out["stub_failed"] = not tests_passed(stub)
        if not out["stub_failed"]:
            out["why"] = "passes_on_stub"
            return out
        if not candidates:
            out["why"] = "no_candidates"
            return out
        for k, text in enumerate(candidates):
            joined = self._join(plan, dict(base, **{sid: text}), goal)
            if joined.get("fallback"):
                out["errors"][k] = "join_fallback"
                continue
            try:
                files = self._files(joined, mode)
            except ValueError as e:
                out["errors"][k] = f"bad_path: {e}"
                continue
            own = self._own(plan, i, text) if mode == "files" else ()
            run = self.run(self._with_tests(files, mode, tests_code, own), TESTS_FILE)
            out["passed"][k] = tests_passed(run)
            if not out["passed"][k]:
                out["errors"][k] = _run_error(run)
        if not any(out["passed"]):
            out["why"] = "no_candidate_passed"
            return out
        k = out["passed"].index(True)
        hollow = hollow_piece(candidates[k])
        if hollow is not None:
            joined = self._join(plan, dict(base, **{sid: hollow}), goal)
            try:
                files = None if joined.get("fallback") else self._files(joined, mode)
            except ValueError:
                files = None
            if files is None:  # Go joins whatever the real piece joins, so this shouldn't happen
                out["hollow"] = {"candidate": k, "exit": None, "timed_out": False, "error": "join_fallback"}
            else:
                own = self._own(plan, i, hollow) if mode == "files" else ()
                run = self.run(self._with_tests(files, mode, tests_code, own), TESTS_FILE)
                out["hollow"] = {"candidate": k, "exit": run.get("exit"), "timed_out": run.get("timed_out"),
                                 "error": _run_error(run) if not tests_passed(run) else None}
                if run.get("error") or tests_passed(run):
                    out["why"] = "run_error" if run.get("error") else "passes_on_hollow"
                    return out
        out["valid"] = True
        return out

    # ------------------------------------------------------------ the whole plan

    def plan_check(self, plan, kept, goal) -> dict:
        """The plan-level check of a code plan: the join of every kept piece ({sid: text}) has no fallback and none of
        its mode's breaking seams, compiles, and its entry point doesn't crash. python-script: chimera.check_result
        on the joined script (Python, sandboxed, looks off) must not say failed; files: the entry file (one with a
        main guard, main.py, cli.py and the like first) is run in pysandbox with the whole project, and only a
        definite crash in a project file fails, or (entry_layout, with "layout" in the entry's record) a
        ModuleNotFoundError raised in a project file for a module the project has in another folder, blamed on the
        step that wrote the file whose import failed (_layout_miss). Unsure and skipped outcomes are recorded, not
        gated. What a dropped step explains (_Dropped) doesn't fail the plan either: an unresolved import of its
        module (in "excused"), and a NameError, blamed on a step that depends on it, for a name it was to provide
        (outcome "unsure_dropped"). Returns {"ok", "reasons", "culprit" (the step a failure is blamed on, or None), "mode",
        "seams", "compile_error", "check" (python-script) or "entry" (files), "seconds"}."""
        t0 = time.monotonic()
        out = {"ok": False, "reasons": [], "culprit": None, "mode": None, "seams": [], "compile_error": None,
               "check": None, "entry": None}

        def done():
            out["ok"] = not out["reasons"]
            out["seconds"] = round(time.monotonic() - t0, 3)
            return out

        joined = self._join(plan, self._by_sid(plan, kept), goal)
        if joined.get("fallback"):
            out["reasons"].append("join_fallback")
            out["join_reasons"] = list(joined.get("reasons") or [])
            bad = [r.split(":", 1)[0] for r in joined.get("reasons") or [] if re.match(r"s\d+:", r)]
            out["culprit"] = bad[0] if bad else None
            return done()
        if joined.get("script_kind") == "run_python":
            mode = "python-script"
        elif joined.get("files"):
            mode = "files"
        else:
            out["mode"] = None
            out["note"] = "no Python in this plan's join"
            return done()
        out["mode"] = mode
        dropped = _Dropped(plan, set(self._by_sid(plan, kept)), joined)
        for s in joined.get("seams") or []:
            if seam_breaks(s, mode) and dropped.seam_excused(s):
                out.setdefault("excused", []).append(s)
            elif seam_breaks(s, mode):
                out["seams"].append(s)
                if "seam:" + s["code"] not in out["reasons"]:
                    out["reasons"].append("seam:" + s["code"])
                out["culprit"] = out["culprit"] or s.get("step") or None
        try:
            files = self._files(joined, mode)
        except ValueError as e:
            out["reasons"].append("bad_path")
            out["compile_error"] = str(e)
            return done()
        for path, body in files.items():
            if path.endswith(".py"):
                err = _compile(body, path)
                if err:
                    out["reasons"].append("compile")
                    out["compile_error"] = f"{path}: {err['error']}"
                    out["culprit"] = out["culprit"] or self._blame(joined, mode, path, err["line"])
                    return done()
        if out["reasons"]:
            return done()
        if mode == "python-script":
            if any(s.get("code") == "missing_entry_point" for s in joined.get("seams") or []):
                out["check"] = {"outcome": "skipped", "summary": "no step defines main()"}
                return done()
            rec = self._check(files[PROJECT], goal)
            out["check"] = dict(rec["check"], critique=rec["critique"], exit=rec["exit"], stated=rec["stated"],
                                cached=rec.get("cached"))
            if rec["check"].get("outcome") == "failed":
                line = rec["check"].get("line") or 0
                culprit = self._blame(joined, mode, PROJECT, line) if line else None
                if dropped.name_excused(culprit, rec["check"].get("error")):
                    out["check"]["outcome"] = "unsure_dropped"
                    return done()
                out["reasons"].append("entry_failed")
                out["culprit"] = culprit
            return done()
        entry = _entry_file(files, joined)
        if entry is None:
            out["entry"] = {"outcome": "skipped", "summary": "no file with a main guard"}
            return done()
        run = self.run(dict(files, **{ENTRY_FILE: _entry_launcher(entry)}), ENTRY_FILE)
        e = last_error(run.get("output"))
        miss = None
        if run.get("error"):
            outcome = "skipped"
        elif run.get("exit") == 0:
            outcome = "passed"
        elif not run.get("timed_out") and definite(e) and _project_frame(e, set(files)):
            outcome = "failed"
        else:
            outcome = "unsure"
            miss = None if run.get("timed_out") else _layout_miss(e, files, entry)
        out["entry"] = {"path": entry, "outcome": outcome, "exit": run.get("exit"), "timed_out": run.get("timed_out"),
                        "error": None if run.get("exit") == 0 else _run_error(run), "seconds": run.get("seconds"),
                        "sandboxed": run.get("sandboxed"), "cached": run.get("cached")}
        if miss:
            # the layout's fault, not the computer's: the launcher gives the entry's folder and the root, as a real
            # run does, and the module is the project's, in another folder (smoke2's X80, which the gate now
            # catches; this is for an earlier piece's bare sibling import, which no gate of its own could see)
            out["entry"].update(outcome="failed", layout=miss)
            out["reasons"].append("entry_layout")
            out["culprit"] = self._blame(joined, mode, miss["file"], miss["line"])
            return done()
        if outcome == "failed":
            f = _project_frame(e, set(files))
            culprit = self._blame(joined, mode, f["file"], f["line"])
            if dropped.name_excused(culprit, err_line(e)):
                out["entry"]["outcome"] = "unsure_dropped"
                return done()
            out["reasons"].append("entry_failed")
            out["culprit"] = culprit
        return done()

    def _blame(self, joined, mode, path, line):
        """The step a line of the joined project belongs to: the line map's for python-script, the only step that
        wrote that file for files (None when several did)."""
        if mode == "python-script":
            if not joined.get("linemap") or not line:
                return None
            spot = self.chimera.locate([{"linemap": joined["linemap"], "check": {"outcome": "failed", "line": line}}])[0]
            return spot.get("repair") or spot.get("step") or None
        steps = next((f.get("steps") or [] for f in joined.get("files") or [] if f.get("path") == path), [])
        return steps[0] if len(steps) == 1 else None


# ---------------------------------------------------------------- helpers

def _parse_data(kind, body, jsonc=False):
    """(error or None, line) of body read as JSON, TOML or YAML; None when YAML can't be read here (no PyYAML).
    jsonc: comments and trailing commas are taken out first (_strip_jsonc). YAML is only composed (_yaml_loader),
    never constructed: its syntax, anchors and aliases are checked, while the application tags real files use (!Ref,
    !GetAtt and !Sub in CloudFormation, Home Assistant's !include and !secret, Ansible's !vault, GitLab's
    !reference, mkdocs' !!python/name:) and values PyYAML's constructors refuse (a 2024-13-45 date) pass."""
    try:
        if kind == "JSON":
            json.loads(_strip_jsonc(body) if jsonc else body)
        elif kind == "TOML":
            tomllib.loads(body)
        else:
            loader = _yaml_loader()
            if loader is None:
                return None
            import yaml
            try:
                for _ in yaml.compose_all(body, Loader=loader):
                    pass
            except yaml.YAMLError as e:
                mark = getattr(e, "problem_mark", None)
                what = " ".join(x for x in (getattr(e, "context", None), getattr(e, "problem", None)) if x)
                return (what or str(e).split("\n")[0])[:300], (mark.line + 1 if mark is not None else 0)
    except json.JSONDecodeError as e:
        return e.msg[:300], e.lineno
    except tomllib.TOMLDecodeError as e:
        msg = str(e)
        m = re.search(r"\(at line (\d+)", msg)
        return msg[:300], int(m.group(1)) if m else 0
    except (ValueError, RecursionError, MemoryError, TypeError) as e:
        return f"{type(e).__name__}: {e}"[:300], 0
    return None, 0


@functools.cache
def _yaml_loader():
    """PyYAML's SafeLoader for composing only, with one change: an anchor may be set again (YAML 1.1 and 1.2 allow
    it, and an alias then means the latest), where PyYAML's composer says "found duplicate anchor". None without
    PyYAML."""
    try:
        import yaml
    except ImportError:
        return None

    class Loader(yaml.SafeLoader):
        def compose_node(self, parent, index):
            event = self.peek_event()
            if not isinstance(event, yaml.AliasEvent) and event.anchor is not None:
                self.anchors.pop(event.anchor, None)
            return super().compose_node(parent, index)

    return Loader


def _strip_jsonc(text):
    """text with // and /* */ comments and trailing commas taken out, strings left as they are: the JSON with
    comments that tsconfig.json and VS Code's settings are written in. Line breaks stay, so a line still counts."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            out.append("\n" * text.count("\n", i, n if j < 0 else j))
            i = n if j < 0 else j + 2
        elif c == ",":
            j = i + 1
            while j < n:  # past blanks and comments to what follows the comma
                if text[j] in " \t\r\n":
                    j += 1
                elif text.startswith("//", j):
                    k = text.find("\n", j)
                    j = n if k < 0 else k
                elif text.startswith("/*", j):
                    k = text.find("*/", j + 2)
                    j = n if k < 0 else k + 2
                else:
                    break
            if j >= n or text[j] not in "}]":
                out.append(c)  # else a trailing comma, left out
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _tests_of(tests):
    """(code, valid) from piece_check's tests argument."""
    if tests is None:
        return "", False
    if isinstance(tests, str):
        return tests, True
    return tests.get("code") or "", bool(tests.get("valid"))


def seam_breaks(seam, mode) -> bool:
    """A seam of Go's join that fails a piece or a plan of this mode: one of FAIL_SEAMS[mode], or in files mode a
    part_not_mergeable whose path is structured data (STRUCTURED)."""
    code = seam.get("code")
    if code in FAIL_SEAMS[mode]:
        return True
    if mode == "files" and code == "part_not_mergeable":
        m = _PART_SEAM.match(seam.get("message") or "")
        return bool(m and STRUCTURED.search(m.group("path")))
    return False


def seam_line(seam):
    """A failing seam told to the next try's teacher: Go's own message, and what to do about it."""
    msg, code = seam.get("message") or seam.get("code") or "", seam.get("code")
    if code == "part_not_mergeable":
        m = _PART_SEAM.match(msg)
        path = m.group("path") if m else "that file"
        return (f"{path} is structured data, so a (part) block of it can't be added to the file: write it whole, and "
                "only if your step owns it")
    if code == "file_conflict":
        return f"the join says: {msg}; an earlier step already writes that file in full, so leave it to that step"
    if code == "import_unresolved":
        return f"the join says: {msg}; import only files your step or an earlier step writes"
    return f"the join says: {msg}"


def _step_modules(files, own):
    """The modules of a files piece that the import run imports and its tests star-import: each .py file it writes
    (own: its FileParts) that only defines things in the merged project (files), by its longest module name."""
    mods = []
    for fp in own or ():
        try:
            path = pysandbox.safe_path(fp.path)
        except ValueError:
            continue
        if not path.endswith(".py") or path not in files or not _quiet(files[path]):
            continue
        names = [m for m in module_names(path)
                 if all(x.isidentifier() and not keyword.iskeyword(x) for x in m.split("."))]
        if names and names[0] not in mods:
            mods.append(names[0])
    return mods


# ---------------------------------------------------------------- stubs for another step

def stubs_for_others(plan, i, own):
    """[(path, owner)]: the files step i's piece (own: its FileParts) writes in full that are stubs for another
    step's file (the rules in the module's docstring); owner is the step the stub names ("s3"), else the first later
    step whose title or instructions name the path, else None (a later step, unnamed)."""
    steps = plan.get("steps") or []
    sid = f"s{i + 1}"
    mine = _step_words(steps[i]) if i < len(steps) else ""
    later = [(f"s{k + 1}", st.get("title") or "", _step_words(st)) for k, st in enumerate(steps) if k > i]
    out = []
    for fp in own or ():
        if fp.part or any(p == fp.path for p, _ in out):
            continue
        small, hollow = _small_file(fp.body), _hollow_file(fp.body, fp.path)
        said, named = _provider(fp.body, sid, len(steps))
        if not (small or hollow or (said and _longer_placeholder(fp.body, fp.path, sid, len(steps)))):
            continue
        stub_word = bool(_STUB_WORDS.search(fp.body))
        init = os.path.basename(fp.path) == "__init__.py"  # an empty one is a whole file
        by_title = next((s for s, title, _ in later if _names_path(title, fp.path)), None)
        by_words = next((s for s, _, words in later if _names_path(words, fp.path)), None)
        if _names_path(mine, fp.path):
            # its own words ask for this file (a placeholder README, .env.example, its package's __init__.py): only
            # a stub that names another step, or one whose file a later step's title names
            if named:
                out.append((fp.path, named))
            elif by_title and (said or stub_word or (hollow and not init)):
                out.append((fp.path, by_title))
        elif said:
            out.append((fp.path, named or by_title or by_words))
        elif by_words and (stub_word or (hollow and not init)):
            out.append((fp.path, by_title or by_words))
    return out


def _longer_placeholder(body, path, sid, n):
    """A file over 3 lines that is a placeholder all the same: its first 3 non-blank lines say that another or a
    later step provides it, and the file holds nothing else. That is a page (.md, .markdown, .rst, a README .txt)
    whose note says placeholder or stub ("Placeholder README: will be expanded in later steps", then an outline: a
    TODO there is about one part of a real page), or Python whose note has a stub word and whose code is only stubs
    (_stub_python). So a step's own real module headed "TODO: the report formatter is added in step s4." isn't one,
    nor a config of real defaults headed "# placeholder defaults, replaced by step s3", nor a requirements.txt of
    real pins under such a note; any other file that holds nothing (comments, brackets, one comment-like key) is
    hollow already (_hollow_file)."""
    head = "\n".join([l for l in (body or "").split("\n") if l.strip()][:3])
    if not _provider(head, sid, n)[0]:
        return False
    if _PAGE.search(path or ""):
        return bool(_PLACEHOLDER.search(head))
    return (path or "").endswith(".py") and bool(_STUB_WORDS.search(head)) and _stub_python(body)


def _stub_python(code):
    """code holds nothing but stubs: docstrings, pass, ..., and top-level defs and classes whose bodies are only
    those, raise NotImplementedError, and (in a class) such methods; imports too, but only beside such a def or
    class (imports alone are a package's re-exports). An assignment, a call or a real body is something."""
    try:
        tree = ast.parse(code or "")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False
    defs = (ast.FunctionDef, ast.AsyncFunctionDef)

    def idle(n):
        return isinstance(n, ast.Pass) or cv.is_docstring(n) or (
            isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and n.value.value is Ellipsis) or (
            isinstance(n, ast.Raise) and cv.dotted(n.exc.func if isinstance(n.exc, ast.Call) else n.exc) ==
            "NotImplementedError")

    def stub(n):
        if isinstance(n, defs):
            return all(idle(x) for x in n.body)
        if isinstance(n, ast.ClassDef):
            return all(idle(x) or (isinstance(x, defs) and stub(x)) for x in n.body)
        return False

    some = False
    for n in tree.body:
        if isinstance(n, (ast.ClassDef,) + defs):
            if not stub(n):
                return False
            some = True
        elif isinstance(n, ast.Raise) or not (idle(n) or isinstance(n, (ast.Import, ast.ImportFrom))):
            return False
    return some or not any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in tree.body)


def _step_words(st):
    return f"{st.get('title') or ''}\n{st.get('instructions') or ''}"


def _names_path(words, path):
    """words name path: as written, or by its file name when it is in a folder."""
    for p in {path, os.path.basename(path)}:
        if p and re.search(r"(?<![\w/.-])" + re.escape(p) + r"(?![\w/-]|\.\w)", words or ""):
            return True
    return False


def _small_file(body):
    """At most 3 non-blank lines."""
    return len([l for l in (body or "").split("\n") if l.strip()]) <= 3


def _hollow_file(body, path):
    """Nothing but whitespace, comments (and the brackets around them), or one comment-like key ({"_comment": ...},
    `placeholder: ...`): a file that holds nothing. "[]" or "{}" alone is data, not a stub."""
    lines = [l.strip() for l in (body or "").split("\n") if l.strip()]
    if not lines:
        return True
    doc = bool(_DOC_EXT.search(path or ""))
    comments = [l for l in lines if (l.startswith(("<!--", "-->")) if doc else _COMMENT.match(l))]
    rest = [l for l in lines if l not in comments]
    if comments and all(_BRACKETS.match(l) for l in rest):
        return True
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if isinstance(data, dict) and len(data) == 1:
        (k, v), = data.items()
        return isinstance(v, str) and k.strip("_/ ").lower() in _COMMENT_KEYS
    m = re.fullmatch(r"[\"']?([\w/]+)[\"']?\s*:\s*.*", rest[0]) if len(rest) == 1 and not doc else None
    return bool(m and m.group(1).strip("_/").lower() in _COMMENT_KEYS)


def _provider(body, sid, n):
    """(said, step): whether the body says another step (or a later one) provides it, and which step it names
    ("s3"; None for "a later step"). A step id that is this step's own or isn't in the plan names nobody."""
    for rx in _PROVIDED_BY:
        for m in rx.finditer(body or ""):
            ids = [g for g in m.groups() if g]
            named = next((x.lower() for x in ids if x.lower() != sid and 1 <= int(x[1:]) <= n), None)
            if ids and not named:
                continue  # "provided by step s1" in s1's own file, or a step the plan doesn't have
            return True, named
    return False, None


# ---------------------------------------------------------------- whose fault failing tests are

def tests_fault(tests_record, plan, i, candidates=None, dropped=(), kept=None):
    """Why tests that no candidate passed say nothing about the candidates, or None (keep them unconfirmed).
    tests_record: the step's tests dict: "code", "check" (tests_check's record: the stub's and each candidate's
    errors), "confirm" (a later tests_check), and the errors of the candidates gated with them, under "errors",
    "gate_errors" or "run_errors" (strings, or dicts with "error": a gate's tests or import run). candidates: their
    texts (or tests_record["candidates"]), to tell what they write and import; without them a module counts as
    unwritten when every failure is the same missing module. dropped: the plan ids of the earlier code steps that
    weren't kept (outside_project). kept: the text of the piece the step keeps untested (task's untested), for the
    closure rule below; without it every candidate given must meet that rule's own-file test.
    - "third_party": every candidate failure (the tests' and the import runs') is a ModuleNotFoundError for modules
      outside the standard library and the project (outside_project) that the candidates import (docx, openpyxl:
      research_draft-0009-04 s4 and planning-0002-08 s6 in the smoke), so nothing can pass here.
    - "tests_unreachable", only when clearly the tests' fault: every failure is the sandbox refusing a process the
      tests start (PermissionError or "Operation not permitted", the tests calling subprocess, os.fork, an exec);
      or every failure is an ImportError for a module the tests import that no candidate writes and that this
      step's title and instructions don't name, nor an earlier step's (or a later step's do: n-python-0001-02 s3's
      tests imported s6's contactmgr); or (_closure) an earlier step names it but neither this step nor any step it
      depends on, directly or through another, does, and the kept piece wrote a .py file at a path this step's own
      words give, so the module is another step's, which these tries can't write (one that did would be a stub for
      another step), and the tries did write their own. When the tests raise their own ImportError ("Could not
      import cmd_add from add_cmd"), the module is one of those the tests import, which needs the candidates' texts
      to tell.
    A missing name the plan gives, or a path the step's instructions ask for, stays unconfirmed (None); so does a
    dependency's module (it is in the closure) and a try that put its own file at another path than its words give.

    The closure rule is smoke2's n-python-0001-01 r1 s3, s4 and s6 (D17-D19): the teacher's tests drove s1's
    tasktimer.__main__.cli(); those steps depend on s2 only, and s1 was dropped (validator:no_file_line), so the stub
    and every try died on "No module named 'tasktimer.__main__'". s1's layout names __main__.py, so the old reading
    (any earlier step's words) kept them unconfirmed and the build dropped three pieces that do their steps (start,
    stop and report, run against s2's utils in pysandbox): weak, weak and ok. Replayed over both runs' 53 code steps
    with tests (27 where none passed), it changes exactly those 3, none in the first run. The one rewrite each got
    (told only the import error) failed for its own reasons (s3's argv, s4's return 1 against SystemExit(1), s6's
    test contradicting the step's date rule), and this reading ignores the rewrite: the tests that failed the kept
    piece reached only another step's module, so the build keeps it as none:tests_unreachable, marked unverified,
    and the rewrite's errors stay in the record for the report (task's tests["rewrite_errors"], which this never
    reads as a failure)."""
    t = tests_record or {}
    code = t.get("code") or ""
    cands = [x for x in (candidates if candidates is not None else t.get("candidates") or []) if x]
    if any(any((rec or {}).get("passed") or ()) for rec in (t.get("check"), t.get("confirm")) if isinstance(rec, dict)):
        return None  # a candidate passed them
    stub, fails = _record_errors(t)
    every = ([stub] if stub else []) + fails
    if not every:
        return None
    steps = plan.get("steps") or []
    written, imported = _written_modules(cands), _imported_modules(cands)
    missing = [_NO_MODULE.search(e).group(1) if e.startswith("ModuleNotFoundError") and _NO_MODULE.search(e) else None
               for e in fails]
    if fails and all(missing) and all(
            outside_project(m, plan, i, written, dropped) and
            (_imports_module(imported, m) if cands else not _imports_text(code, m)) for m in missing):
        return "third_party"  # not the project's own (no candidate writes it, no step names it), not Python's
    if all(_REFUSED.match(e) for e in every) and _STARTS_PROCESS.search(code):
        return "tests_unreachable"
    if not all(_IMPORT_ERROR.match(e) for e in every):
        return None
    gone = {_missing_module(e) for e in every} - {None}
    if len({_top(x) for x in gone}) > 1:
        return None
    if gone:  # the stub may miss the package ('src') where a candidate misses its module ('src.index')
        suspects = [max(gone, key=len)]
    elif cands:  # the tests' own message names no module ("Could not import cmd_add from add_cmd")
        suspects = sorted(x for x in _imports_of(code) if _top(x) not in _STDLIB)
    else:
        return None
    mine = _step_words(steps[i]) if i < len(steps) else ""
    before = "\n".join(_step_words(st) for st in steps[:i + 1])
    after = "\n".join(_step_words(st) for st in steps[i + 1:])
    reach = "\n".join(_step_words(steps[j]) for j in sorted(_closure(plan, i) | {i}) if j < len(steps))
    own = [kept] if kept else cands
    wrote_own = bool(own) and all(any(fp.path.endswith(".py") and _names_path(mine, fp.path) for fp in files)
                                  for files in _texts_files(own))
    for m in suspects:
        made_later = _names_module(after, m) and not _names_module(mine, m)
        not_reached = wrote_own and not _names_module(reach, m)
        if _imports_text(code, m) and not _has_module(written, m) and \
                (not _names_module(before, m) or made_later or not_reached):
            return "tests_unreachable"
    return None


def _closure(plan, i):
    """The indexes of the steps step i depends on, directly or through another (each step's depends_on read as
    dep_indexes reads it: an id's first step, earlier steps only)."""
    steps = plan.get("steps") or []
    first = {}
    for j in range(len(steps) - 1, -1, -1):
        first[steps[j].get("id") or f"s{j + 1}"] = j
    out, todo = set(), [i]
    while todo:
        k = todo.pop()
        for d in (steps[k].get("depends_on") or []) if k < len(steps) else ():
            j = first.get(d)
            if j is not None and j < k and j not in out:
                out.add(j)
                todo.append(j)
    return out


def outside_project(module, plan, i, written=(), dropped=()) -> bool:
    """module (one a run missed) is neither Python's nor the project's, as far as step i can tell: its top package
    isn't in the standard library, nothing written writes it (written: _written_modules of the candidates and any
    text the caller counts as the project's), no step names it as a project file (a/b.py, b.py, a/, a dotted name),
    and no dropped earlier code step names it at all, even as a bare word or in backticks (the `cmd_add` module,
    cmd_add(args)), since that step may be the one that was to write it (n-python-0001-02 s6 in a cascaded replay of
    the smoke: s2, which names cmd_add, was dropped). dropped: the plan ids of the earlier code steps (files or
    python-script) that weren't kept; only their words count, since a kept step's piece is in the project (the run
    shows it didn't write the module) and a writing step's never writes one ("Keep the data so that `openpyxl` can
    read it later." keeps openpyxl a library). A word inside a library's name doesn't count ("python-docx" names no
    docx module): it must be a whole token, with no hyphen, dot or slash next to it."""
    steps = plan.get("steps") or []
    if not module or _top(module) in _STDLIB or _has_module(set(written or ()), module):
        return False
    if any(_names_module(_step_words(st), module, files_only=True) for st in steps):
        return False
    gone = set(dropped or ())
    return not any(_names_token(_step_words(st), module) for k, st in enumerate(steps[:i])
                   if (st.get("id") or f"s{k + 1}") in gone)


def _names_token(words, module):
    """words have module as a whole token (dotted as it is, or its last part): not part of a longer name, a path or
    a file name ("python-docx", "report.docx", "lib/docx")."""
    for name in {module, module.split(".")[-1]}:
        if re.search(r"(?<![\w./" + _HYPHENS + r"])" + re.escape(name) + r"(?![\w/" + _HYPHENS + r"]|\.\w)",
                     words or ""):
            return True
    return False


def import_fault(gate, plan, i, texts=(), dropped=(), written=()):
    """"third_party" when the piece kept for step i, which no tests ran on, can't be checked here, else None. gate:
    piece_check's result on it, as task.py keeps it on the candidate. Either
    - its own import run ended on a ModuleNotFoundError for a module outside the standard library that the piece
      imports, or
    - (no tests in the gate) its code imports such a module only inside a function body, outside a try that would
      catch the import's failure (gate["lazy_imports"], _lazy_imports: neither the standard library's nor installed
      for the runs' interpreter), which the import run never executes;
    and that module is no candidate's (texts: the step's candidate texts), no text of written's (more texts whose
    modules are the project's: a variant's input pieces, since a variant is gated alone and its own import of a
    dependency's module always misses), no project file's, and no dropped earlier code step names it (dropped: their
    plan ids; outside_project). A gate made before the import run recorded what it missed ("missing") is read from
    the error line and the texts alone; one made before "lazy_imports" gives none.

    The lazy branch is smoke2's X44 (research_draft-0009-04 s4, bad): python-docx imported only inside
    _load_docx_library, so the import run exited 0, no tests ran, and nothing ever ran main(), whose _add_code_block
    loads a Pt it never binds; the plan check's entry stopped "unsure" on the missing docx. The same seed's cand 0 and
    the first run's s4, importing docx at the top, were already third_party. Over both runs' 107 Python candidates
    that passed every other check it fires on X44 alone (0 ok, 0 weak); counting guarded and installed packages too it
    would fire on 6, 5 of them tabulate fallbacks in a try (X12 among them, weak). The build drops none:third_party
    as before."""
    gate = gate or {}
    mods = None
    run = gate.get("run") or {}
    err = run.get("error") or ""
    m = _NO_MODULE.search(err) if err.startswith("ModuleNotFoundError") else None
    if m:
        module, seen = m.group(1), run.get("missing") or {}
        if seen.get("module") == module:
            mine = not (seen.get("project") or not seen.get("piece"))  # not the project's own, nor an earlier step's
        else:
            mine = _imports_module(_imported_modules(texts), module)
        if mine:
            mods = _written_modules([*(texts or ()), *(written or ())])
            if outside_project(module, plan, i, mods, dropped):
                return "third_party"
    lazy = [] if gate.get("tests") else gate.get("lazy_imports") or []
    if lazy:
        mods = mods if mods is not None else _written_modules([*(texts or ()), *(written or ())])
        if any(outside_project(x, plan, i, mods, dropped) for x in lazy):
            return "third_party"
    return None


def lazy_imports(code) -> list:
    """The modules code's absolute import statements bring in only inside a function or method body (at any depth),
    outside a guard (layout.guards: a try catching ImportError, ModuleNotFoundError, Exception, BaseException or
    anything, or TYPE_CHECKING): what importing the module never runs. In order, each once; [] when code doesn't
    parse."""
    try:
        tree = ast.parse(code or "")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    out = []

    def walk(node, inside, guarded):
        for field, value in ast.iter_fields(node):
            g = guarded or (field == "body" and layout.guards(node))
            for ch in (value if isinstance(value, list) else [value]):
                if not isinstance(ch, ast.AST):
                    continue
                if inside and not g and isinstance(ch, (ast.Import, ast.ImportFrom)):
                    names = [a.name for a in ch.names] if isinstance(ch, ast.Import) else \
                        [ch.module] if not ch.level and ch.module else []
                    out.extend(n for n in dict.fromkeys(names) if n not in out)
                walk(ch, inside or isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)), g)

    walk(tree, False, False)
    return out


def no_python(texts, mode, words="", python_project=False) -> bool:
    """A files step has nothing the tests could import: none of the candidate texts given writes a .py file, the
    step's own words (words: its title and instructions) don't ask for Python (names_python), and the round isn't a
    Python project (python_project: an earlier kept piece of the round, or one of the step's dependency pieces,
    writes a .py file; the caller reads that), so a Python step whose candidates leave their .py files out still
    gets its tests (and those fail them). Most steps of a Python project never say Python ("Implement the `find`
    sub-command": 11 of the smoke's 22). False for python-script, and when no text is given (nothing to tell
    from)."""
    texts = [x for x in texts or () if x]
    if mode != "files" or not texts or python_project or names_python(words):
        return False
    return not any(fp.path.endswith(".py") for files in _texts_files(texts) for fp in files)


def names_python(words) -> bool:
    """words (a step's title and instructions) name Python: a .py file (to write or to use: "Using the utilities
    from data_utils.py"), a Python-only name (`from x import y`, __init__, __main__, __name__) or Python itself
    ("a Python script", "Python 3.12", "python-docx", a Python package by its name). Not Python where it is another
    program's flag or path ("--python-expr", "/usr/bin/python3"), part of a longer name ("IPython", "CPython") or a
    command run with options ("python -m http.server", a README's): those come with steps that write no Python. A
    package's folder or a module named only by "module" or "package" doesn't count: in the stored gpt-oss plans,
    29 of 29 code steps that said so without naming Python were Lua, Go, JavaScript or .NET."""
    w = words or ""
    return bool(_PY_PATH.search(w) or _PY_SYNTAX.search(w) or _PY_WORD.search(w))


def _record_errors(t):
    """(the stub's error or None, every candidate failure's error line) of a tests record."""
    stub, fails = None, []
    for rec in (t.get("check"), t.get("confirm")):
        if not isinstance(rec, dict):
            continue
        stub = stub or ((rec.get("stub") or {}).get("error") if isinstance(rec.get("stub"), dict) else None)
        fails += [e for e in rec.get("errors") or [] if e]
    for key in ("errors", "gate_errors", "run_errors"):
        for e in t.get(key) or []:
            e = e.get("error") if isinstance(e, dict) else e
            if e:
                fails.append(e)
    return stub, [e for e in fails if e not in ("join_fallback",) and not e.startswith("bad_path")]


def _missing_module(error):
    """The module an ImportError or ModuleNotFoundError line is about, or None."""
    e = error or ""
    if not _IMPORT_ERROR.match(e):
        return None
    m = _NO_MODULE.search(e) or _CANT_IMPORT.search(e)
    return m.group(1) if m else None


def _top(module):
    return (module or "").split(".")[0]


def _texts_files(texts):
    out = []
    for text in texts or ():
        try:
            out.append(cv.validate_piece(text, "files", reject_cut=False, max_tokens=None).files)
        except Exception:  # a reply the validator can't read writes nothing
            out.append([])
    return out


def _written_modules(texts):
    """Every module name the candidates' .py files can be imported by (python-script: "project")."""
    mods = {"project"}
    for files in _texts_files(texts):
        for fp in files:
            mods.update(module_names(fp.path))
    return mods


def _has_module(written, module):
    """A candidate writes module, or a package of that name (a folder holding its .py files)."""
    return module in written or any(m.startswith(module + ".") for m in written)


def _imports_of(code):
    """The modules code imports (absolute imports, by ast, and importlib.import_module("...") with a literal)."""
    out = set(re.findall(r"import_module\(\s*['\"]([\w.]+)['\"]", code or ""))
    try:
        tree = ast.parse(code or "")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return out
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and not n.level and n.module:
            out.add(n.module)
    return out


def _imported_modules(texts):
    """The modules the candidates' code imports, from every block but the handoff."""
    return {m for text in texts or () for b in code_blocks(text or "") if b.lang != "handoff"
            for m in _imports_of(b.body)}


def _imports_module(imported, module):
    return any(x == module or _top(x) == _top(module) for x in imported)


def _imports_text(code, module):
    """The tests' own code imports module (or its top package)."""
    return _imports_module(_imports_of(code), module)


def _names_module(words, module, files_only=False):
    """words name module: dotted, as its file (a/b.py or b.py) or its folder (a/). files_only: only as a project
    module is named (a file, a folder, a dotted name), not a bare word ("python-docx" names a library)."""
    if not words or not module:
        return False
    parts = module.split(".")
    forms = {"/".join(parts) + ".py", parts[-1] + ".py", "/".join(parts) + "/"}
    if not files_only or "." in module:
        forms.add(module)
    return any(re.search(r"(?<![\w.])" + re.escape(f) + r"(?![\w])", words) for f in forms)


class _Dropped:
    """What the steps a join leaves out explain, one seam or error at a time; piece_check and plan_check share it.
    present: the positional ids (s1, s2, ...) of the steps in the join. An unresolved import (Go's "no such project
    file" seam, or the import run's ModuleNotFoundError) is excused only when the file that imports it is a piece of
    a step that depends on a dropped step, that dropped step names the module (in its title or instructions,
    dotted, as a path, or as the module's file name), and no module of a present file is a near miss of it (a
    misspelt import of a step that is there). A "doesn't define" seam is never excused. A NameError blamed on a
    step is excused when a dropped dependency of that step names the name."""

    def __init__(self, plan, present, joined):
        steps = plan.get("steps") or []
        sids = [f"s{k + 1}" for k in range(len(steps))]
        ids = {st.get("id") or sid: sid for st, sid in zip(steps, sids)}
        self.words = {sid: f"{st.get('title') or ''}\n{st.get('instructions') or ''}" for st, sid in zip(steps, sids)}
        self.dropped = {sid: [ids[d] for d in st.get("depends_on") or [] if d in ids and ids[d] not in present]
                        for st, sid in zip(steps, sids) if sid in present}
        self.owners, self.bodies = {}, {}
        for f in joined.get("files") or []:
            self.owners.setdefault(f.get("path"), set()).update(f.get("steps") or [])
            self.bodies[f.get("path")] = f.get("body") or ""
        for p in joined.get("pieces") or []:
            for f in p.get("files") or []:
                self.owners.setdefault(f.get("path"), set()).add(p.get("sid"))
        self.modules = {n for path in self.bodies for n in module_names(path)}
        self.tops = {n.split(".")[0] for n in self.modules}

    def _names(self, d, module):
        """Dropped step d's title or instructions name module."""
        text = self.words.get(d) or ""
        last = module.split(".")[-1] + ".py"
        for p in _PY_PATH.findall(text):
            if module in module_names(p) or os.path.basename(p) == last:
                return True
        return re.search(r"(?<![\w./])" + re.escape(module) + r"(?![\w/]|\.\w)", text) is not None

    def import_excused(self, path, module):
        if not module or not path:
            return False
        if any(difflib.SequenceMatcher(None, module, n).ratio() >= NEAR_MISS for n in self.modules):
            return False
        return any(self._names(d, module) for s in sorted(self.owners.get(path) or ()) for d in self.dropped.get(s, ()))

    def seam_excused(self, seam) -> bool:
        if seam.get("code") != "import_unresolved":
            return False
        m = _UNRESOLVED.match(seam.get("message") or "")
        if not m:
            return False
        path = m.group("path")
        if m.group("imp"):
            mods = [m.group("imp")]
        else:
            level, name = len(m.group("dots")), m.group("mod")
            pkg = path.split("/")[:-1]
            if level - 1 > len(pkg):
                return False
            mod = ".".join((pkg[:len(pkg) - (level - 1)] if level else []) + ([name] if name else []))
            mods = [mod]
            if any(n.startswith(mod + ".") for n in self.modules):  # a package that is there: its names are modules
                mods = self._imported(path, level, name, mod)
        return bool(mods) and all(self.import_excused(path, x) for x in mods)

    def _imported(self, path, level, name, mod):
        """The modules `from <mod> import a, b` in path names (mod.a, mod.b); [] when that can't be told."""
        try:
            tree = ast.parse(self.bodies.get(path) or "")
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return []
        out = []
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.level == level and (n.module or "") == name:
                if any(a.name == "*" for a in n.names):
                    return []
                out += [f"{mod}.{a.name}" for a in n.names]
        return out

    def own_module_missing(self, e, files) -> bool:
        """The run ended on a ModuleNotFoundError for one of the project's own modules (its top package is one of
        the project's, as Go's importSeams reads them) that no dropped dependency explains."""
        if not e or not e.get("last") or e.get("type") != "ModuleNotFoundError":
            return False
        m = _NO_MODULE.search(e.get("msg") or "")
        if not m or m.group(1).split(".")[0] not in self.tops:
            return False
        f = _project_frame(e, set(files))
        return not self.import_excused(f["file"] if f else None, m.group(1))

    def name_excused(self, sid, error) -> bool:
        """error ("NameError: name 'x' is not defined") is for a name a dropped dependency of step sid names."""
        m = _NO_NAME.search(error or "")
        if not sid or not m or not (error or "").startswith("NameError"):
            return False
        word = re.compile(r"(?<![\w.])" + re.escape(m.group(1)) + r"(?!\w)")
        return any(word.search(self.words.get(d) or "") for d in self.dropped.get(sid, ()))


def hollow_piece(text):
    """text with every function body and method body of its own code made `return None` (hollow), the rest as it
    is, so a test that passes on it checks none of the piece's behaviour; None when there is nothing to hollow. Only
    ever run in the sandbox, never kept: it is code_gate's, not a teacher's or a worker's."""
    lines = (text or "").split("\n")
    changed = False
    for b in reversed(code_blocks(text or "")):
        if not b.closed or b.lang == "handoff":
            continue
        new = hollow(b.body)
        if new is None or new == b.body:
            continue
        fence = lines[b.open_line]
        pad = " " * (len(fence) - len(fence.lstrip(" ")))
        lines[b.open_line + 1:b.close_line] = [(pad + l) if l else l for l in new.split("\n")]
        changed = True
    return "\n".join(lines) if changed else None


def hollow(code):
    """code with the body of every top-level def, and of every method of a top-level class, replaced by `return
    None` (by ast's positions, so the rest keeps its text); None if it doesn't parse."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    defs = (ast.FunctionDef, ast.AsyncFunctionDef)
    bodies = [n.body for n in tree.body if isinstance(n, defs)]
    bodies += [m.body for n in tree.body if isinstance(n, ast.ClassDef) for m in n.body if isinstance(m, defs)]
    lines = [l.encode("utf-8") for l in code.split("\n")]  # ast's columns count bytes
    for body in sorted(bodies, key=lambda b: (b[0].lineno, b[0].col_offset), reverse=True):
        first, last = body[0], body[-1]
        lines[first.lineno - 1:last.end_lineno] = [lines[first.lineno - 1][:first.col_offset] + b"return None" +
                                                   lines[last.end_lineno - 1][last.end_col_offset:]]
    return "\n".join(l.decode("utf-8") for l in lines)


def _compile(src, name):
    """None if src compiles, else {"error", "line", "source"}. compile() only reads the code; nothing runs."""
    try:
        compile(src, name, "exec", dont_inherit=True)
        return None
    except SyntaxError as e:
        cls = type(e).__name__
        return {"error": f"{cls}: {e.msg}", "line": e.lineno or 0, "source": (e.text or "").strip()}
    except (ValueError, RecursionError, MemoryError, OverflowError) as e:
        return {"error": f"{type(e).__name__}: {e}", "line": 0, "source": ""}


def _top_names(code):
    try:
        return cv.top_level_names(ast.parse(code))
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []


def _quiet(src):
    """A module that only defines things when imported: imports, defs, classes, assignments, docstrings, a main
    guard, try-imports and TYPE_CHECKING blocks."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                          ast.Assign, ast.AnnAssign)) or cv.is_docstring(n) or cv.is_main_guard(n):
            continue
        if isinstance(n, ast.Try) and all(isinstance(x, (ast.Import, ast.ImportFrom)) for x in n.body):
            continue
        if isinstance(n, ast.If) and cv.dotted(n.test) in ("TYPE_CHECKING", "typing.TYPE_CHECKING"):
            continue
        return False
    return True


def _line_at(text, n):
    lines = (text or "").split("\n")
    return lines[n - 1].strip() if 0 < n <= len(lines) else ""


def _enclosing(code, line):
    """The top-level def, class or constant a line of a piece is in ("" if none): what the repair message names."""
    lines = (code or "").split("\n")
    for k in range(min(line, len(lines)) - 1, -1, -1):
        m = re.match(r"(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)|([A-Za-z_]\w*)\s*(?::[^=]*)?=", lines[k])
        if m:
            return m.group(1) or m.group(2)
        if lines[k] and not lines[k][0].isspace() and not lines[k].startswith(("#", "@", ")", "]", "}")):
            return ""
    return ""


def _block_line(own, path, body, line, source):
    """The line in this piece's own block for path that line of the merged file is: the same number when the piece
    wrote the file whole and the join kept it as it is, else the one line of the block with that text. 0 if the piece
    has no block for path or the line can't be told."""
    blocks = [fp for fp in own if fp.path == path]
    if not blocks:
        return 0
    merged = body.rstrip("\n").split("\n")
    for fp in blocks:
        mine = fp.body.rstrip("\n").split("\n")
        if not fp.part and mine == merged[:len(mine)] and 0 < line <= len(mine):
            return line
    want = (source or _line_at(body, line)).strip()
    if not want:
        return 0
    hits = [(fp, k) for fp in blocks for k, l in enumerate(fp.body.split("\n"), 1) if l.strip() == want]
    return hits[0][1] if len(hits) == 1 else 0


def _entry_file(files, joined):
    """The project's entry point: a .py file with a main guard, by ENTRY_NAMES first, then the last step's."""
    guarded = []
    for path, body in files.items():
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(body)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        if path.endswith("__main__.py") or any(cv.is_main_guard(n) for n in tree.body):
            guarded.append(path)
    if not guarded:
        return None
    for name in ENTRY_NAMES:
        for p in guarded:
            if os.path.basename(p) == name:
                return p
    order = {f.get("path"): max((int(s[1:]) for s in f.get("steps") or [] if s[1:].isdigit()), default=0)
             for f in joined.get("files") or []}
    return max(guarded, key=lambda p: order.get(p, 0))


def _layout_miss(e, files, entry):
    """The end of a files entry run that is the layout's fault (plan_check's entry_layout): a ModuleNotFoundError
    that ended it, raised in one of the project's files (its innermost project frame: the file whose import failed),
    for a module the project has in another folder (layout.project_modules) and that no real run of the entry could
    find either: not from the entry's folder nor any folder above it (layout.search_folders: a cwd for `python3 -m`,
    as the gate's own layout reading looks), and only when no file of the project says how its folders get on the
    path (layout.path_config). {"file", "line", "module", "found_at"} or None. A dropped step's module is never one:
    it isn't in the project at all. In the smoke this is smoke2's n-python-0001-02, whose entry ended on `No module
    named 'find_cmd'` with src/find_cmd.py in the project and was taken for unsure, so the plan passed: of the 8 files
    rounds of both runs with kept pieces it is the one that changes, blaming s6, and with s6's alternates (cand 2,
    cand 0) swapped in the plan passes again (their entry gets as far as argparse asking for a command). For an
    earlier piece's bare sibling import inside src/, run from a root-level entry, it blames that earlier step, whose
    file holds the import: a culprit some later step depends on isn't swapped (task.try_alternates), so the plan
    fails, as for entry_failed. A package two folders deep (src/wm_notes/cli.py importing wm_notes.store inside
    main(), the launcher's `python3 src/wm_notes/cli.py` can't see src/) is run as `python3 -m wm_notes.cli` from
    src/, or installed by its pyproject.toml: it stays unsure, as before the backstop, rather than failing the plan
    and every code step of its round (smoke2's tasktimer/tasktimer/ layout, in a step that was dropped, is the only
    such in the runs)."""
    if not e or not e.get("last") or e.get("type") != "ModuleNotFoundError":
        return None
    m = _NO_MODULE.search(e.get("msg") or "")
    mods = layout.project_modules(files)
    if not m or m.group(1) not in mods or layout.path_config(files):
        return None
    if layout.resolve(m.group(1), layout.search_folders(entry), files, layout.folders(files)) is not None:
        return None
    f = _project_frame(e, set(files))
    if f is None:
        return None
    return {"file": f["file"], "line": f["line"], "module": m.group(1), "found_at": sorted(set(mods[m.group(1)]))}


def _entry_launcher(entry):
    """Runs entry as `python3 entry` would, its own folder first on sys.path, the project's root after it."""
    d = os.path.dirname(entry) or "."
    return (HARNESS + "import runpy, sys\n"
            f"sys.path[:0] = {[d, '.'] if d != '.' else ['.']!r}\n"
            f"sys.argv = [{entry!r}]\n"
            f"runpy.run_path({entry!r}, run_name='__main__')\n")
