"""Running a step's Python in a sandbox: the code gate's test runs, imports and entry points (DESIGN.md, "code_gate.py
and pysandbox.py").

    r = run({"project.py": code, "test_step.py": tests}, "test_step.py", timeout=30)
    # {"exit": 0, "output": "...", "timed_out": False, "seconds": 0.08, "sandboxed": True, "cut": 0}

The files are written into a fresh folder and `python3 -I -B entry` runs there under sandbox-exec, with a profile in
the spirit of Chimera's own for a script (macScriptProfile, app/runner.go): no network; /Users, /Volumes and root's
home unreadable except the run folder (and the interpreter's own install, should it live in a home folder); writes
only in the run folder; no new processes, no signals to others, no Apple Events, LaunchServices or pasteboard.
HOME and TMPDIR are the run folder and nothing else of this process's environment reaches the script. -I keeps
PYTHON* variables, the user's site-packages and the script's folder off sys.path; -B writes no bytecode.

A /bin/sh watchdog outside the sandbox, Chimera's (runner.go's watchdog), kills the script by its pid and the run's
process group when this process goes away, even by kill -9: the read end of a pipe only this process holds is the
watchdog's standard input. A timeout closes that pipe too, so a script that left the group with setsid is still
reached; then the group is killed as a backstop. The output (stdout and stderr together) keeps its first 4,000 and
last 16,000 characters at most, with a line saying how much was cut between them, so a traceback at the end always
survives.

Without sandbox-exec (not macOS) the script runs unsandboxed, recorded as "sandboxed": false: the data generator
only runs on the Studio, and its callers can refuse such a run. version() says which Python the runs get, the way
Chimera names it in a repair ("Python 3.13.12"), and own_paths() where it imports its own modules from (the code
gate's reading of "installed").

run_tool runs another program the same way (the same profile, which lets only that program start, and the same
watchdog): the code gate's `node --check` of a files piece's JavaScript and lang_check's parsers (gofmt, bash -n, zsh
-n, ruby -c, xmllint, swift-frontend -parse), which only parse.
"""
from __future__ import annotations

import codecs
import functools
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

from tools import blender_check

TIMEOUT = 30.0  # Chimera's own limit for a Python check (runSandboxed)
TOOL_TIMEOUT = 10.0  # run_tool's: a parse check (node --check) takes well under a second
OUTPUT_CAP = 20_000  # characters of output kept
HEAD_KEEP = 4_000  # of them, from the start; the rest is the end
_GRACE_S = 3.0  # after the watchdog is told, before the group is killed by hand
_MARK_ROOM = 60  # characters the "… (n characters cut) …" line can take

# Chimera's watchdog (app/runner.go), with the script's standard input from a file ($1) instead of /dev/null: fd 0 is
# the pipe whose other end only the parent holds.
WATCHDOG = """exec 3<&0
f=$1
shift
"$@" <"$f" 3<&- &
c=$!
(read _ <&3; kill -KILL $c 2>/dev/null; kill -KILL 0) &
w=$!
exec 3<&-
wait $c
s=$?
kill $w 2>/dev/null
exit $s"""


def python3() -> str:
    """The interpreter the runs use: python3 on PATH, else the one running this."""
    return shutil.which("python3") or sys.executable


def version(python=None) -> str:
    """What `python3 --version` says ("Python 3.13.12"), as Chimera reads its Python (tools.go), or "" when it
    doesn't answer as a Python 3. Run once, outside the sandbox: it is the interpreter alone, no script."""
    try:
        p = subprocess.run([python or python3(), "--version"], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    said = (p.stdout or p.stderr or "").strip()
    return said if p.returncode == 0 and said.startswith("Python 3") and "\n" not in said else ""


@functools.cache
def own_paths(python=None) -> tuple:
    """The folders the interpreter's own runs import from (its sys.path under -I: the standard library, lib-dynload
    and its site-packages, never a script's folder or the user's site-packages), as `python3 -I -c` prints them, run
    once outside the sandbox (the interpreter alone, no script); () when it doesn't answer. The code gate reads a
    module found there as the interpreter's (installed), not the project's and not missing: a run in the sandbox
    imports it from those same folders."""
    try:
        p = subprocess.run([python or python3(), "-I", "-c", "import json, sys; print(json.dumps(sys.path))"],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
        paths = json.loads(p.stdout) if p.returncode == 0 else []
    except (OSError, subprocess.SubprocessError, ValueError):
        return ()
    return tuple(x for x in paths if isinstance(x, str) and x and os.path.isabs(x))


def can_sandbox() -> bool:
    return sys.platform == "darwin" and shutil.which("sandbox-exec") is not None


# ---------------------------------------------------------------- the profile (macScriptProfile's rules)

def _sb(p):
    return '"' + p.replace("\\", "\\\\").replace('"', '\\"') + '"'


def tool_home(binary):
    """The folder a program's own files live in: its .app bundle, or the prefix above bin/ (toolHome)."""
    d = os.path.dirname(os.path.realpath(binary))
    i = d.find(".app/")
    if i >= 0:
        return d[:i + 4]
    return os.path.dirname(d) if os.path.basename(d) == "bin" else d


def hidden_root(d):
    """d when the profile would hide it (a program kept in a home folder or on another volume), else "" (hiddenRoot):
    only an app bundle or a deep install folder, never a shallow one that would undo the hiding."""
    for p in ("/Users/", "/Volumes/"):
        if d.startswith(p) and ((d.endswith(".app") and d.count("/") >= 3) or d.count("/") >= 4):
            return d
    return ""


def exec_root(d):
    """A program's folder it may start its own helpers from (execRoot): a bundle or a deep prefix, never /usr."""
    if d and (".app" in d or d.count(os.sep) >= 3):
        return d
    return ""


def profile(run_dir, python):
    """The sandbox-exec profile for running python (or run_tool's program) in run_dir."""
    real_dir, home = os.path.realpath(run_dir), tool_home(python)
    reads, execs = [], []
    for kind, p, out in (("subpath", real_dir, reads), ("subpath", hidden_root(home), reads),
                         ("literal", python, execs), ("literal", os.path.realpath(python), execs),
                         ("subpath", exec_root(home), execs)):
        rule = f" ({kind} {_sb(p)})"
        if p and rule not in out:
            out.append(rule)
    return f"""(version 1)
(allow default)
(deny network*)
(deny file-read* (subpath "/Users") (subpath "/Volumes") (subpath "/private/var/root"))
(allow file-read*{"".join(reads)})
(deny file-write*)
(allow file-write* (subpath {_sb(real_dir)}) (literal "/dev/null") (regex #"^/dev/tty") (regex #"^/dev/fd/"))
(deny appleevent-send)
(deny mach-lookup (global-name "com.apple.coreservices.launchservicesd") (global-name "com.apple.pasteboard.1"))
(deny signal)
(allow signal (target self))
(deny process-fork)
(deny process-exec*)
(allow process-exec*{"".join(execs)})"""


# ---------------------------------------------------------------- files

def safe_path(rel) -> str:
    """rel as a plain relative path inside the run folder; ValueError for one that is absolute, leaves the folder,
    is empty or names a folder. A model's File: line is never trusted to stay inside."""
    if not isinstance(rel, str) or not rel.strip() or "\x00" in rel:
        raise ValueError(f"not a file path: {rel!r}")
    p = rel.replace("\\", "/")
    if p.startswith("/") or (len(p) > 1 and p[1] == ":"):
        raise ValueError(f"not a relative path: {rel!r}")
    norm = os.path.normpath(p)
    if norm in (".", "") or norm == ".." or norm.startswith("../") or p.endswith("/"):
        raise ValueError(f"leaves the run folder or names a folder: {rel!r}")
    return norm


def write_files(root, files):
    """Write {relative path: text} under root (paths checked by safe_path)."""
    for rel, text in files.items():
        path = os.path.join(root, safe_path(rel))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text if isinstance(text, str) else str(text))


# ---------------------------------------------------------------- output

class _Tail:
    """Output read as it comes: the first HEAD_KEEP characters and the last (cap - HEAD_KEEP), and how many there
    were in all, so a script that prints forever costs no memory."""

    def __init__(self, cap=OUTPUT_CAP, head=HEAD_KEEP):
        self.cap, self.head_keep, self.tail_keep = cap, head, cap - head
        self.head, self.tail, self.total = "", "", 0
        self._dec = codecs.getincrementaldecoder("utf-8")("replace")

    def feed(self, data, final=False):
        s = self._dec.decode(data, final)
        if not s:
            return
        self.total += len(s)
        room = self.head_keep - len(self.head)
        if room > 0:
            self.head += s[:room]
            s = s[room:]
        if s:
            self.tail = (self.tail + s)[-self.tail_keep:]

    def text(self):
        """(output, characters cut)."""
        if self.total <= self.cap:
            return self.head + self.tail, 0
        keep = self.tail[-(self.tail_keep - _MARK_ROOM):]  # the mark line takes its room from the tail
        cut = self.total - len(self.head) - len(keep)
        return self.head + f"\n… ({cut} characters cut) …\n" + keep, cut


def _read_all(fd, tail):
    try:
        while True:
            b = os.read(fd, 65536)
            if not b:
                break
            tail.feed(b)
    except OSError:
        pass
    tail.feed(b"", final=True)


def hide_paths(text, run_dir):
    """The run folder out of the output (hidePaths): a traceback names project.py, not /…/wm-py-x/run/project.py,
    so the same run reads the same every time."""
    for d in sorted({os.path.realpath(run_dir), os.path.abspath(run_dir)}, key=len, reverse=True):
        text = text.replace(d + os.sep, "").replace(d, ".")
    return text


def _sandbox_failed(output):
    return any(l.strip().startswith("sandbox-exec:") for l in output.split("\n")[:5])


def _kill_group(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


# ---------------------------------------------------------------- running

def run(files, entry, *, timeout=TIMEOUT, stdin="", work=None, python=None, sandbox=None) -> dict:
    """Write files ({relative path: text}) into a fresh folder under work ($WM_SCRATCH or data/scratch by default)
    and run `python3 -I -B entry` there, sandboxed, with stdin as its standard input. Returns {"exit" (None when it
    timed out or couldn't start), "output" (stdout and stderr, capped), "timed_out", "seconds", "sandboxed", "cut"
    (characters of output left out)}, plus "error" when it couldn't start. sandbox: None to sandbox when this computer
    can, False to run unsandboxed (tests only). ValueError for a path that leaves the folder. The folder is removed
    afterwards."""
    entry = safe_path(entry)
    files = {safe_path(k): v for k, v in (files or {}).items()}
    if entry not in files:
        raise ValueError(f"the entry {entry!r} isn't one of the files")
    python = python or python3()
    return _run(files, python, ["-I", "-B", entry], timeout=timeout, stdin=stdin, work=work, sandbox=sandbox)


def run_tool(files, program, args, *, timeout=TOOL_TIMEOUT, work=None, sandbox=None) -> dict:
    """program (a path, as shutil.which gives it) with args, in a fresh folder holding files, under the same profile
    and watchdog as a script (the profile lets program start and nothing else): code_gate's `node --check` of a
    piece's JavaScript, on a copy, so a model's file is never read in place. Returns what run() does; a program that
    isn't there is an "error"."""
    files = {safe_path(k): v for k, v in (files or {}).items()}
    if not program or not os.path.exists(program):
        return {"exit": None, "output": "", "timed_out": False, "seconds": 0.0, "sandboxed": False, "cut": 0,
                "error": f"no such program: {program!r}"}
    return _run(files, program, list(args), timeout=timeout, stdin="", work=work, sandbox=sandbox)


def tool_version(program) -> str:
    """The first line `program --version` prints ("v24.19.0"), run once outside the sandbox (the program alone, no
    file), or "" when it doesn't answer."""
    try:
        p = subprocess.run([program, "--version"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    said = (p.stdout or p.stderr or "").strip().split("\n")[0].strip()
    return said if p.returncode == 0 else ""


def _run(files, program, args, *, timeout, stdin, work, sandbox):
    """files (paths already checked) written into a fresh folder, then program with args run there under the
    watchdog, sandboxed when it can be: run() and run_tool()."""
    use_sandbox = can_sandbox() if sandbox is None else bool(sandbox) and can_sandbox()
    base = tempfile.mkdtemp(prefix="wm-py-", dir=blender_check.scratch_root(work))
    out = {"exit": None, "output": "", "timed_out": False, "seconds": 0.0, "sandboxed": use_sandbox, "cut": 0}
    try:
        run_dir = os.path.join(base, "run")
        os.makedirs(run_dir)
        write_files(run_dir, files)
        stdin_path = os.path.join(base, "stdin")  # beside the run folder: the watchdog opens it, the script can't
        with open(stdin_path, "w", encoding="utf-8") as f:
            f.write(stdin or "")
        inner = [program] + list(args)
        if use_sandbox:
            inner = ["sandbox-exec", "-p", profile(run_dir, program)] + inner
        argv = ["/bin/sh", "-c", WATCHDOG, "wm-pysandbox", stdin_path] + inner
        env = {"HOME": run_dir, "TMPDIR": run_dir, "TMP": run_dir, "TEMP": run_dir, "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONNOUSERSITE": "1", "LANG": "en_US.UTF-8", "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        out.update(_spawn(argv, run_dir, env, timeout))
        out["output"] = hide_paths(out["output"], run_dir)
        if use_sandbox and out["exit"] and _sandbox_failed(out["output"]):
            out["error"] = "the sandbox couldn't start"  # not the script's doing (sandboxDidNotStart)
        return out
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _spawn(argv, cwd, env, timeout):
    alive_r, alive_w = os.pipe()  # not inheritable: only this process holds alive_w
    rd, wr = os.pipe()
    t0 = time.monotonic()
    try:
        p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=alive_r, stdout=wr, stderr=wr, start_new_session=True)
    except OSError as e:
        for fd in (alive_r, alive_w, rd, wr):
            os.close(fd)
        return {"error": f"couldn't start: {e}"}
    os.close(alive_r)
    os.close(wr)
    tail = _Tail()
    reader = threading.Thread(target=_read_all, args=(rd, tail), daemon=True)
    reader.start()
    timed_out, code = False, None
    try:
        try:
            code = p.wait(timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.close(alive_w)  # the watchdog kills the script by pid, then the group
            alive_w = None
            try:
                p.wait(_GRACE_S)
            except subprocess.TimeoutExpired:
                pass
            _kill_group(p.pid)
            p.wait()
    except BaseException:  # Ctrl-C or a stop: nothing of the run is left behind
        if alive_w is not None:
            os.close(alive_w)  # the watchdog's kill by pid reaches a script that left the group
            alive_w = None
        _kill_group(p.pid)
        p.kill()
        p.wait()
        raise
    finally:
        if alive_w is not None:
            os.close(alive_w)
        _kill_group(p.pid)  # anything it left behind
        reader.join(5)
        try:
            os.close(rd)
        except OSError:
            pass
    output, cut = tail.text()
    if timed_out:
        output += f"\n(timed out after {timeout:g} s)"
    return {"exit": None if timed_out else code, "output": output, "timed_out": timed_out,
            "seconds": round(time.monotonic() - t0, 3), "cut": cut}
