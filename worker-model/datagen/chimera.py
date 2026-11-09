"""The Chimera binary, as the data generator uses it: every request a worker, the planner or the reviewer gets, the
validator's verdicts, the joins, the result check and the names sheets come from it, so nothing here is a Python
copy of Chimera (DESIGN.md, "Go is the source of truth").

    ch = Chimera(binary)
    req = ch.worker_request(plan, 0, {}, goal=goal, names=sheet)   # {messages, need_ctx, mode, sid, ...}

Each call runs the binary once, with JSON on stdin (written with ensure_ascii=False), and reads one JSON object from
its stdout: --hydra-worker-request, --hydra-plan-request, --hydra-review-request, --hydra-read-reply and
--hydra-assemble's jobs and join. A non-zero exit, a binary that won't start, or output that isn't one JSON object
raises ChimeraError with stderr's last line. Those modes are pure functions of their input and take milliseconds, so
their output is memoised in this process (an LRU keyed by common.key_of(mode, payload), bounded by size), never on
disk: a resumed run asks the binary again, which costs nothing and can't go stale.

Two methods run more than the binary: check_result runs a script in Chimera's sandbox (Blender or Python), with
the look turned off (CHIMERA_LOOK_MODEL names no model, so no vision model is loaded beside the teacher) and a fresh
--data-dir that is removed afterwards; blender_names runs the asked Blender through a PATH shim (tools/blender_check's
launcher), since `chimera --blender-names` takes the first `blender` on PATH, so each version prints its own sheet.
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading

from datagen.common import key_of
from tools import blender_check, blenders

NO_LOOK = "datagen-no-look"  # CHIMERA_LOOK_MODEL for check_result: a prefix no model's name starts with
MODE_TIMEOUT = 300.0  # a pure mode; a long list of assemble jobs is the slowest
CHECK_TIMEOUT = blender_check.TIMEOUT  # Chimera's own limit for a Blender check is 120 s
NAMES_TIMEOUT = 120.0  # Chimera gives Blender 30 s to print the sheet, after finding it
MEMO_BYTES = 64_000_000  # of memoised output; the oldest go first


class ChimeraError(RuntimeError):
    """The binary failed, couldn't be started, or didn't print one JSON object."""


def _last_line(text):
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    return lines[-1] if lines else ""


def _text(b):
    return b.decode("utf-8", "replace") if isinstance(b, bytes) else (b or "")


class Chimera:
    """One Chimera binary. env is added to the environment of every run (OLLAMA_HOST, say, for check_result)."""

    def __init__(self, binary, *, env=None, memo_bytes=MEMO_BYTES):
        self.binary = os.path.abspath(binary)
        self.env = dict(env or {})
        self.memo_bytes = memo_bytes
        self._memo = collections.OrderedDict()  # key -> stdout text
        self._memo_size = 0
        self._lock = threading.Lock()
        self._sha = None  # ((size, mtime_ns), hex)
        self._version = None
        self._names = {}  # Blender path -> sheet

    # ------------------------------------------------------------ running

    def _environ(self, **extra):
        env = dict(os.environ)
        env.update(self.env)
        env.update(extra)
        return env

    def _run(self, what, args, stdin=None, *, env=None, timeout=MODE_TIMEOUT, cwd=None):
        """(exit, stdout, stderr) of one run; ChimeraError if it couldn't start or ran out of time."""
        try:
            p = subprocess.run([self.binary, *args], input=stdin, capture_output=True, timeout=timeout,
                               env=env or self._environ(), cwd=cwd)
        except subprocess.TimeoutExpired as e:
            raise ChimeraError(f"chimera {what}: no answer in {timeout:.0f} s: {_last_line(_text(e.stderr))}") from None
        except OSError as e:
            raise ChimeraError(f"chimera {what}: couldn't run {self.binary}: {e}") from None
        return p.returncode, _text(p.stdout), _text(p.stderr)

    def _json(self, mode, payload):
        """What `chimera <mode>` prints for payload, memoised."""
        key = key_of(mode, payload)
        with self._lock:
            out = self._memo.get(key)
            if out is not None:
                self._memo.move_to_end(key)
        if out is not None:
            return self._parse(mode, out, "")  # parsed afresh, so a caller's changes never reach the memo
        stdin = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        code, out, err = self._run(mode, [mode], stdin)
        if code != 0:
            raise ChimeraError(f"chimera {mode}: exit {code}: {_last_line(err)}")
        obj = self._parse(mode, out, err)
        with self._lock:
            if key not in self._memo:
                self._memo[key] = out
                self._memo_size += len(out)
            while self._memo_size > self.memo_bytes and len(self._memo) > 1:
                _, old = self._memo.popitem(last=False)
                self._memo_size -= len(old)
        return obj

    @staticmethod
    def _parse(mode, out, err):
        try:
            obj = json.loads(out)
        except ValueError:
            obj = None
        if not isinstance(obj, dict):
            raise ChimeraError(f"chimera {mode}: not one JSON object on stdout ({out.strip()[:120]!r}): "
                               f"{_last_line(err)}")
        return obj

    # ------------------------------------------------------------ the binary itself

    def version(self) -> str:
        """The binary's version, like "0.8.0" (`chimera --version` prints "chimera 0.8.0")."""
        if self._version is None:
            code, out, err = self._run("--version", ["--version"], timeout=30)
            words = out.split()
            if code != 0 or len(words) != 2 or words[0] != "chimera":
                raise ChimeraError(f"chimera --version: exit {code}: {out.strip()[:120]!r} {_last_line(err)}")
            self._version = words[1]
        return self._version

    def sha256(self) -> str:
        """The binary file's sha256, hex. Worked out again if the file changes."""
        st = os.stat(self.binary)
        stamp = (st.st_size, st.st_mtime_ns)
        if self._sha is None or self._sha[0] != stamp:
            h = hashlib.sha256()
            with open(self.binary, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
            self._sha = (stamp, h.hexdigest())
        return self._sha[1]

    # ------------------------------------------------------------ requests

    def worker_request(self, plan, index, outputs, *, goal="", names="", names_gate=True, refs=None, prev_result=None,
                       critique="", piece=None, crash=None, room=None) -> dict:
        """The request step `index` of `plan` gets (--hydra-worker-request): {messages, need_ctx, mode, sid, n, lone,
        deps, round2_matched}. The plan is cleaned by Go. `outputs` is keyed by cleaned step id; a value is a string
        (done), None (failed) or {"output": str, "status": ...}, and a step left out counts as failed. With
        names_gate the sheet only goes to a step namesBlock would give it to (a Blender step, or a task that says
        Blender or bpy). A crash (Go's workerCrash: step, part, function, piece_line, line, source, error, runner)
        with the piece that crashed makes it the repair request; round 2's fields are dropped there, as Chimera does.
        """
        payload = {"plan": plan, "index": index, "outputs": outputs or {}, "goal": goal or "", "names": names or "",
                   "names_gate": bool(names_gate), "critique": critique or ""}
        if refs is not None:
            payload["refs"] = refs
        if prev_result is not None:
            payload["prev_result"] = prev_result
        if crash is not None:
            if piece is None:
                raise ValueError("a repair request needs the piece that crashed")
            payload["piece"], payload["crash"] = piece, crash
        if room is not None:
            payload["room"] = room
        return self._json("--hydra-worker-request", payload)

    def plan_request(self, goal, *, history=None, prior="", critique="", refs=None) -> dict:
        """The planner's request for a round (--hydra-plan-request): {messages, need_ctx, format, helper_fits}.
        history is the chat before the task ([{"role", "content"}]); prior and critique are the round's base, the
        result it improves and what still needs work; refs are the library's entries (those scoring 0.3 or more are
        shown). helper_fits says whether Chimera would prefer hydra:1.0 for it."""
        return self._json("--hydra-plan-request", {"goal": goal, "history": history, "prior": prior or "",
                                                   "critique": critique or "", "refs": refs})

    def review_request(self, goal, result) -> dict:
        """The looping reviewer's request (--hydra-review-request): {messages, need_ctx, format, helper_fits}."""
        return self._json("--hydra-review-request", {"goal": goal, "result": result})

    def read_plan(self, reply) -> dict:
        """A planner's reply read as Chimera reads it: {"ok", "plan"}, the plan cleaned ({title, kind, summary,
        steps: [{id, title, kind, instructions, depends_on}]}), or None when it can't be read."""
        return self._json("--hydra-read-reply", {"plan": reply})

    def read_review(self, reply) -> dict:
        """A reviewer's reply read as Chimera reads it: {"ok", "done", "score", "critique"} (a score that isn't a
        whole number makes it unreadable)."""
        return self._json("--hydra-read-reply", {"review": reply})

    # ------------------------------------------------------------ pieces and joins (--hydra-assemble)

    def _jobs(self, name, jobs):
        jobs = list(jobs)
        if not jobs:
            return []
        out = self._json("--hydra-assemble", {name: jobs})
        if not isinstance(out.get(name), list) or len(out[name]) != len(jobs):
            raise ChimeraError(f"chimera --hydra-assemble: no {name} list of {len(jobs)} in its answer")
        return out[name]

    def validate(self, jobs) -> list:
        """The validator's verdict per job ({text, mode, sid, deps, lone, step, done_reason, reject_cut,
        max_tokens}): [{sid, mode, ok, contract_ok, form_ok, issues, handoff, files, body, code, code_line, section,
        library}]."""
        return self._jobs("validate", jobs)

    def alone(self, jobs) -> list:
        """Each piece's run-alone script (jobs as validate's, plus keep_ctx, ctx_name, also), None for a piece with
        no code to run."""
        return self._jobs("alone", jobs)

    def locate(self, jobs) -> list:
        """Each check read through a line map (jobs {linemap, check, script}): Go's checkSpot."""
        return self._jobs("locate", jobs)

    def scan(self, codes) -> list:
        """Go's reading of each Python source: {"ok", "tree"} or {"ok": false, "line", "msg"}."""
        return self._jobs("scan", codes)

    def slug(self, titles) -> list:
        """planSlug of each title."""
        return self._jobs("slug", titles)

    def join(self, plan, outputs, *, goal="", done_reasons=None, reject_cut=False) -> dict:
        """What joining the plan's pieces gives (--hydra-assemble): {title, fallback, reasons, seams, notes, failed,
        script, script_kind, text, linemap, files, parts, assumptions, assumptions_note, editor_wanted, pieces}.
        outputs as for worker_request; done_reasons is Ollama's per step id."""
        return self._json("--hydra-assemble", {"plan": plan, "outputs": outputs or {}, "goal": goal or "",
                                               "done_reasons": done_reasons or {}, "reject_cut": bool(reject_cut)})

    # ------------------------------------------------------------ runs

    def check_result(self, path, *, goal=None, work_dir, blender=None, timeout=CHECK_TIMEOUT) -> dict:
        """Chimera's result check of a script (.py) or reply (.md), as looping mode does it but with the look off:
        {"check": {outcome, runner, summary, error, line, source, output, ...}, "critique", "exit", "stated"}.
        exit is 0 for passed, 1 for failed or wrong_scene, 2 otherwise; stated is the runner Chimera said it ran
        ("Blender 5.2.2", "Python 3.13.5"), or None. Each check gets a fresh --data-dir in its own folder under
        work_dir, removed afterwards. blender, a Blender binary, is put first on PATH through a launcher; without
        it Chimera takes the first Blender it finds."""
        if blender and blenders.check_path(blender):
            raise ChimeraError(f"chimera --check-result: {blenders.check_path(blender)}")
        os.makedirs(work_dir, exist_ok=True)
        run_dir = tempfile.mkdtemp(prefix="check-", dir=work_dir)
        try:
            data_dir = os.path.join(run_dir, "data")
            os.makedirs(data_dir)
            env = self._environ(CHIMERA_LOOK_MODEL=NO_LOOK)
            if blender:
                bin_dir = os.path.join(run_dir, "bin")
                blender_check.write_launcher(bin_dir, blender)
                env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
            args = ["--data-dir", data_dir, "--check-result", os.path.abspath(path)]
            if goal:
                args += ["--check-goal", goal]
            code, out, err = self._run("--check-result", args, env=env, timeout=timeout, cwd=run_dir)
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)
        rec = blender_check.parse_json(out)
        if not isinstance(rec, dict) or not isinstance(rec.get("check"), dict):
            raise ChimeraError(f"chimera --check-result: exit {code}, no verdict: {_last_line(err)}")
        rec["exit"] = code
        rec["stated"] = blender_check.stated_runner(err)[0]
        return rec

    def blender_names(self, blender_path, scratch) -> str:
        """The names sheet that Blender prints (`chimera --blender-names`, the text a long task's Blender steps get
        after namesBlock's words), asked once per Blender in this process. The run's folder is made under scratch
        and removed."""
        with self._lock:
            sheet = self._names.get(blender_path)
        if sheet is not None:
            return sheet
        why = blenders.check_path(blender_path)
        if why:
            raise ChimeraError(f"chimera --blender-names: {why}")
        os.makedirs(scratch, exist_ok=True)
        run_dir = tempfile.mkdtemp(prefix="names-", dir=scratch)
        try:
            bin_dir = os.path.join(run_dir, "bin")
            blender_check.write_launcher(bin_dir, blender_path)
            env = self._environ()
            env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
            code, out, err = self._run("--blender-names", ["--blender-names"], env=env, timeout=NAMES_TIMEOUT,
                                       cwd=run_dir)
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)
        sheet = out.strip()
        if code != 0 or not sheet:
            raise ChimeraError(f"chimera --blender-names: exit {code}, no sheet from {blender_path}: {_last_line(err)}")
        with self._lock:
            self._names[blender_path] = sheet
        return sheet
