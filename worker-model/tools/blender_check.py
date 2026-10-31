#!/usr/bin/env python3
"""Run `chimera --check-result` once per Blender version and report each, with a strict pass rule.

    python3 tools/blender_check.py script.py [more.py ...]          # 5.2.2 and 5.0.1
    python3 tools/blender_check.py script.py --versions 5.0.1 --json
    python3 tools/blender_check.py script.py --probe                # also append the scene probe

The Chimera binary comes from --chimera or $CHIMERA_BIN (build it with `go build -o <path> .` in app/).
Chimera's check takes the first `blender` on PATH, so each run gets its own folder with a launcher
script named blender (`exec` of the app's binary, never a symlink: Blender crashes when started
from one) first on PATH, and a fresh --data-dir. Chimera reads the launcher and sandboxes the app's
binary itself. Each run must say "running it in Blender <X>" on stderr, and its JSON must name the
same runner, for the version asked; otherwise the run counts as an error, not a result.

Two verdicts per run:
- the check's own outcome (passed, failed, unsure, skipped), exactly as Chimera's looping mode judges it;
- strict: the check passed (so Blender exited 0) and no line of the output it shows has "Traceback"
  or "Error:" in it (scene probe lines aside). Chimera passes a run that printed Blender's own
  "Error: ..." lines or a handled Python error; strict doesn't. The check's JSON shows only the
  last 1,500 characters of the output, so strict sees no further back than that.

Exit status: 0 if every run passed strictly, 1 if any didn't, 2 if a run couldn't be done or
asserted (no binary, wrong Blender, no JSON).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # worker-model/
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from tools import blenders, scene_probe  # noqa: E402

RUNNING = re.compile(r"running it in (Blender(?: (\d+\.\d+(?:\.\d+)?))?|Python[^,]*)")
TIMEOUT = 240.0  # Chimera's own limit for a Blender check is 120 s


def chimera_bin(arg=None):
    path = arg or os.environ.get("CHIMERA_BIN", "")
    if not path:
        raise RuntimeError("no Chimera binary: pass --chimera PATH or set CHIMERA_BIN "
                           "(cd app && go build -o <path> .)")
    if not (os.path.isfile(path) and os.access(path, os.X_OK)):
        raise RuntimeError(f"Chimera binary {path} isn't there or isn't executable")
    return os.path.abspath(path)


SCRATCH_DEFAULT = os.path.join(HERE, "data", "scratch")  # gitignored (data/); never the system temp folder


def scratch_root(arg=None):
    """Where run folders go: arg, else $WM_SCRATCH, else worker-model/data/scratch/."""
    root = arg or os.environ.get("WM_SCRATCH") or SCRATCH_DEFAULT
    os.makedirs(root, exist_ok=True)
    return root


def launcher_text(blender):
    """A bash launcher Chimera's findBlender follows (launcherTarget reads the quoted .app path)."""
    if any(c in blender for c in '"$`\\\n'):
        raise ValueError(f"can't quote this Blender path safely: {blender!r}")
    return f'#!/bin/bash\nexec "{blender}" "$@"\n'


def write_launcher(bin_dir, blender):
    os.makedirs(bin_dir, exist_ok=True)
    path = os.path.join(bin_dir, "blender")
    with open(path, "w", encoding="utf-8") as f:
        f.write(launcher_text(blender))
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def stated_runner(stderr):
    """("Blender 5.2.2", "5.2.2") from Chimera's "running it in Blender 5.2.2, sandboxed…" line."""
    m = RUNNING.search(stderr or "")
    if not m:
        return None, None
    return m.group(1), m.group(2)


def parse_json(stdout):
    s = (stdout or "").strip()
    try:
        return json.loads(s)
    except ValueError:
        i, j = s.find("{"), s.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(s[i:j + 1])
            except ValueError:
                return None
    return None


def bad_lines(output):
    """Lines that break the strict rule: "Traceback" or "Error:" anywhere in them, probe lines aside."""
    return [l.strip() for l in (output or "").splitlines()
            if not scene_probe.is_probe_line(l) and ("Traceback" in l or "Error:" in l)]


def strict_verdict(exit_code, check, version_ok):
    """(strict pass, why not)."""
    if not version_ok:
        return False, "the run wasn't in the Blender asked for"
    if not check:
        return False, "no verdict from the check"
    if exit_code != 0 or check.get("outcome") != "passed":
        return False, f"check {check.get('outcome', '?')}" + (f": {check['error']}" if check.get("error") else "")
    bad = bad_lines(check.get("output"))
    if bad:
        return False, "printed: " + bad[0][:200]
    return True, ""


def run_one(script, version, blender, chimera, root, goal=None, probe=False, keep=False, timeout=TIMEOUT):
    """One check of one script in one Blender version. Never raises for the run itself."""
    t0 = time.monotonic()
    rec = {"script": script, "version": version, "blender": blender}
    why = blenders.check_path(blender)
    if why:
        rec.update(error=why, strict=False, version_ok=False, outcome=None)
        return rec
    run_dir = tempfile.mkdtemp(prefix=f"check-{version}-", dir=root)
    try:
        bin_dir, data_dir = os.path.join(run_dir, "bin"), os.path.join(run_dir, "data")
        os.makedirs(data_dir)
        write_launcher(bin_dir, blender)
        target = os.path.abspath(script)
        if probe:
            if not script.lower().endswith(".py"):
                raise ValueError("--probe needs a .py script")
            with open(script, encoding="utf-8") as f:
                src = f.read()
            target = os.path.join(run_dir, "script.py")
            with open(target, "w", encoding="utf-8") as f:
                f.write(scene_probe.append(src))
        env = dict(os.environ)
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        cmd = [chimera, "--data-dir", data_dir, "--check-result", target]
        if goal:
            cmd += ["--check-goal", goal]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=run_dir)
            code, out, err = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:  # its output comes as bytes, whatever text= says
            code, out, err = None, _text(e.stdout), _text(e.stderr) + f"\n(timed out after {timeout:.0f} s)"
        j = parse_json(out)
        check = (j or {}).get("check") or {}
        said, said_version = stated_runner(err)
        version_ok = said_version == version and check.get("runner") == f"Blender {version}"
        strict, strict_why = strict_verdict(code, check, version_ok)
        rec.update(exit=code, outcome=check.get("outcome"), runner=check.get("runner"), stated=said,
                   version_ok=version_ok, strict=strict, strict_why=strict_why, seconds=check.get("seconds"),
                   summary=check.get("summary"), error=check.get("error"), line=check.get("line"),
                   source=check.get("source"), output=check.get("output", ""), critique=(j or {}).get("critique", ""),
                   bad_lines=bad_lines(check.get("output")))
        if not j:
            rec["problem"] = "no JSON from chimera --check-result: " + (err or out).strip()[-300:]
        elif not version_ok:
            rec["problem"] = (f"asked for Blender {version}, but Chimera said {said or 'nothing'} "
                              f"and its JSON says {check.get('runner') or 'nothing'}")
        if probe:
            rec["probe"] = scene_probe.parse(check.get("output", ""))
    except Exception as e:  # noqa: BLE001  (a tool problem, reported, not raised)
        rec.update(problem=f"{type(e).__name__}: {e}", strict=False, version_ok=False)
    finally:
        if keep:
            rec["run_dir"] = run_dir
        else:
            shutil.rmtree(run_dir, ignore_errors=True)
    rec["wall_s"] = round(time.monotonic() - t0, 2)
    return rec


def _text(b):
    return b.decode("utf-8", "replace") if isinstance(b, bytes) else (b or "")


def check_all(scripts, wanted=None, paths=None, chimera=None, root=None, goal=None, probe=False, keep=False):
    """Every script in every version (wanted: "5.2.2,5.0.1" or a list; paths: version -> binary)."""
    chimera = chimera_bin(chimera)
    root = scratch_root(root)
    pairs = blenders.pick(paths or blenders.VERSIONS, wanted)
    return [run_one(s, v, path, chimera, root, goal=goal, probe=probe, keep=keep) for s in scripts for v, path in pairs]


def add_run_args(ap):
    ap.add_argument("--versions", help="comma-separated, default every version in tools/blenders.py")
    ap.add_argument("--blender", action="append", metavar="VERSION=PATH", help="another or a different Blender binary")
    ap.add_argument("--chimera", help="the Chimera binary (default $CHIMERA_BIN)")
    ap.add_argument("--goal", help="passed on as --check-goal")
    ap.add_argument("--scratch", help="where run folders go (default $WM_SCRATCH, else worker-model/data/scratch)")
    ap.add_argument("--keep", action="store_true", help="keep each run's folder (launcher and data dir)")


def run_from_args(a, scripts, probe=False):
    versions = blenders.parse_overrides(a.blender)
    pairs = blenders.pick(versions, a.versions)
    chimera = chimera_bin(a.chimera)
    root = scratch_root(a.scratch)
    return [run_one(s, v, path, chimera, root, goal=a.goal, probe=probe, keep=a.keep) for s in scripts for v, path in pairs]


def report(results):
    rows = [["script", "Blender", "ran in", "check", "strict", "s", "why / error"]]
    for r in results:
        why = r.get("problem") or ("" if r.get("strict") else r.get("strict_why") or "")
        if r.get("line") and not r.get("problem"):
            why = f"line {r['line']}: {r.get('error')}"
        rows.append([os.path.basename(r["script"]), r["version"], (r.get("stated") or "-").replace("Blender ", ""),
                     r.get("outcome") or "-", "pass" if r.get("strict") else "FAIL",
                     "" if r.get("seconds") is None else f"{r['seconds']}", (why or "")[:120]])
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]
    fmt = lambda row: "| " + " | ".join(str(c).ljust(w) for c, w in zip(row, widths)) + " |"  # noqa: E731
    lines = [fmt(rows[0]), "|" + "|".join("-" * (w + 2) for w in widths) + "|"] + [fmt(r) for r in rows[1:]]
    for r in results:
        if "probe" in r:
            lines.append(f"probe, {os.path.basename(r['script'])} in {r['version']}: {scene_probe.summary(r.get('probe'))}")
    return "\n".join(lines)


def exit_status(results):
    if any(r.get("problem") or not r.get("version_ok") for r in results):
        return 2
    return 0 if all(r.get("strict") for r in results) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scripts", nargs="+", help=".py scripts or .md replies")
    add_run_args(ap)
    ap.add_argument("--probe", action="store_true", help="append tools/scene_probe.py's epilogue (.py only)")
    ap.add_argument("--json", action="store_true", help="print the run records as JSON")
    a = ap.parse_args(argv)
    try:
        results = run_from_args(a, a.scripts, probe=a.probe)
    except (RuntimeError, ValueError) as e:
        print(f"blender_check: {e}", file=sys.stderr)
        return 2
    print(json.dumps(results, indent=2, ensure_ascii=False) if a.json else report(results))
    return exit_status(results)


if __name__ == "__main__":
    sys.exit(main())
