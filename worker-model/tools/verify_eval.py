#!/usr/bin/env python3
"""Re-run the worker eval's own checks in real Blenders and (with --write) record what they found.

    python3 tools/verify_eval.py [--part w1|w2|w3|w4f|w4l|all] [--case ID] [--write]
                                 [--blender PATH ...] [--chimera PATH] [--tokens MODEL]

- W1: each new task's reference scene runs strictly in every Blender and passes its scene assertions.
- W2: each case's right code passes and its assertions hold; its facts_check (the file's facts_prelude
  first) passes, asserting what the facts sentences name; each trap fails with the error recorded
  (or, for a trap marked only_in, fails only there and runs in the other version).
- W3: each broken piece crashes as recorded (the traceback is recorded with --write); its reference
  fix passes. With --chimera (or CHIMERA_BIN), also records what `chimera --check-result` says, per
  Blender, through a PATH shim and a fresh --data-dir each time.
- W4f: reference pieces run alone, print their stand-ins and pass their assertions.
- W4l: long inputs are rebuilt from their sources; --write records sha256, size and a token estimate;
  --tokens MODEL also measures the tokens with that model in the local Ollama (one short call each).

Blenders default to tools/blenders.py's, /Applications/Blender 3.app (5.2.2) and /Applications/Blender.app
(5.0.1), run directly (never through a symlink) with -b --factory-startup in a fresh folder each time (its
cwd and TMPDIR, removed afterwards) under --work: $WM_SCRATCH/verify-eval, else worker-model/data/verify-eval
(gitignored). Every Blender fact is checked in both versions, so a run without exactly 5.2.2 and 5.0.1 is a
failure and --write refuses it. Strict pass: exit 0 and no Traceback or Error line. Exit status 1 when a
check fails.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # worker-model/
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import evalset  # noqa: E402
from tools import blenders as blender_paths  # noqa: E402

DEFAULT_BLENDERS = list(blender_paths.VERSIONS.values())
SCRIPT = "script.py"
PROBE_MARK = "CHIMERA_PROBE "
FACTS_OK = "WM_FACTS_OK"


def default_work():
    """$WM_SCRATCH/verify-eval, else worker-model/data/verify-eval (gitignored): never the system temp folder."""
    scratch = os.environ.get("WM_SCRATCH")
    return os.path.join(scratch, "verify-eval") if scratch else os.path.join(HERE, "data", "verify-eval")


def version_problems(found, want=evalset.VERSIONS):
    """What is wrong with the Blenders found ([version, ...]): every eval fact is checked in exactly want."""
    out = []
    for v in want:
        if found.count(v) == 0:
            out.append(f"no Blender {v}: every fact must be checked in {' and '.join(want)}")
        elif found.count(v) > 1:
            out.append(f"Blender {v} given twice")
    for v in sorted(set(found) - set(want)):
        out.append(f"Blender {v} isn't one of the eval's versions ({', '.join(want)})")
    return out


def blender_version(path):
    out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=60).stdout
    m = re.search(r"Blender (\d+\.\d+\.\d+)", out)
    return m.group(1) if m else "?"


def parse_run(output):
    """The last traceback in Blender's output: exception line, and the deepest frame inside script.py."""
    lines = output.split("\n")
    starts = [i for i, l in enumerate(lines) if l.startswith("Traceback (most recent call last):")]
    if not starts:
        return {}
    block, frames, exc = lines[starts[-1] + 1:], [], ""
    for i, l in enumerate(block):
        m = re.match(r'\s+File "([^"]+)", line (\d+), in (.+)$', l)
        if m:
            src = block[i + 1].strip() if i + 1 < len(block) and not block[i + 1].strip().startswith("File ") else ""
            frames.append({"file": m.group(1), "line": int(m.group(2)), "function": m.group(3), "source": src})
        elif l and not l[0].isspace():
            exc = l
            break
    tb_end = starts[-1] + 1 + (block.index(exc) if exc in block else len(block))
    out = {"exception": exc, "traceback": "\n".join(lines[starts[-1]:tb_end + 1])}
    mine = [f for f in frames if os.path.basename(f["file"]) == SCRIPT]
    if mine:
        out.update(line=mine[-1]["line"], function=mine[-1]["function"], source=mine[-1]["source"])
    return out


def run_blender(path, script, work, timeout=120):
    d = tempfile.mkdtemp(prefix="run-", dir=work)
    with open(os.path.join(d, SCRIPT), "w", encoding="utf-8") as f:
        f.write(script)
    t0 = time.time()
    try:
        p = subprocess.run([path, "-b", "--factory-startup", "--python-exit-code", "1", "--python", SCRIPT],
                           cwd=d, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout,
                           env=dict(os.environ, TMPDIR=d))
        code_, output = p.returncode, p.stdout
    except subprocess.TimeoutExpired as e:
        code_, output = -1, (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
    r = {"exit": code_, "seconds": round(time.time() - t0, 1), "output": output}
    r.update(parse_run(output))
    r["strict"] = code_ == 0 and "Traceback" not in output and not re.search(r"^Error", output, re.M)
    probe = [l[len(PROBE_MARK):] for l in output.split("\n") if l.startswith(PROBE_MARK)]
    if probe:
        r["probe"] = json.loads(probe[-1])
    shutil.rmtree(d, ignore_errors=True)
    return r


def probe_text():
    with open(os.path.join(evalset.EVAL_DIR, evalset.PROBE), encoding="utf-8") as f:
        return f.read()


def with_probe(script):
    return script.rstrip() + "\n\n# ---- scene probe (eval) ----\n" + probe_text()


class Checker:
    def __init__(self, blenders, work, jobs=4):
        self.blenders = [(blender_version(b), b) for b in blenders]
        self.work = work
        self.pool = ThreadPoolExecutor(max_workers=jobs)
        self.failures = []

    def run_all(self, script):
        """{version: result} for one script in every Blender, in parallel."""
        futs = {v: self.pool.submit(run_blender, b, script, self.work) for v, b in self.blenders}
        return {v: f.result() for v, f in futs.items()}

    def fail(self, cid, msg):
        self.failures.append(f"{cid}: {msg}")
        print(f"  FAIL {cid}: {msg}")


def _brief(r):
    return r.get("exception") or ("passed" if r["strict"] else f"exit {r['exit']}, no traceback")


def check_w1(ck, c):
    res = ck.run_all(with_probe(evalset.code(c["reference"])))
    rec = {}
    for v, r in res.items():
        fails = evalset.check_assertions(r["probe"], c["expect"]["assertions"]) if r.get("probe") else ["no probe output"]
        if not r["strict"]:
            ck.fail(c["id"], f"reference doesn't pass in {v}: {_brief(r)}")
        for f in fails:
            ck.fail(c["id"], f"{v}: {f}")
        rec[v] = {"reference": "passed" if r["strict"] else _brief(r), "assertions": "passed" if not fails else fails}
    return rec


def per_version(x, v):
    """A trap's error or message: one string, or {version: string} when the versions differ (None when the
    dict names no such version: nothing recorded, so no failure can match it)."""
    return x.get(v) if isinstance(x, dict) else x


def _trap_expect(t, v):
    return not t.get("only_in") or v in t["only_in"]


def facts_script(c, prelude):
    """A W2 case's facts check: the file's facts_prelude, the case's setup, its facts_check, a closing mark."""
    return "\n".join([evalset.code(prelude), evalset.code(c.get("setup")), evalset.code(c["facts_check"]),
                      f"print({FACTS_OK!r})"])


def check_w2(ck, c, prelude=None):
    setup = evalset.code(c.get("setup"))
    res = ck.run_all(with_probe(setup + "\n" + evalset.code(c["right"]) + "\nprint('WM_RIGHT_OK')"))
    rec = {v: {"right": None, "assertions": None, "facts": None, "traps": {}} for v, _ in ck.blenders}
    for v, r in res.items():
        ok = r["strict"] and "WM_RIGHT_OK" in r["output"]
        rec[v]["right"] = "passed" if ok else _brief(r)
        if not ok:
            ck.fail(c["id"], f"right code fails in {v}: {_brief(r)}")
        fails = evalset.check_assertions(r["probe"], c["expect"]["assertions"]) if r.get("probe") else ["no probe output"]
        rec[v]["assertions"] = "passed" if not fails else fails
        for f in fails:
            ck.fail(c["id"], f"{v}: {f}")
    if not c.get("facts_check"):
        ck.fail(c["id"], "no facts_check: its facts aren't checked")
    else:
        for v, r in ck.run_all(facts_script(c, prelude)).items():
            ok = r["strict"] and FACTS_OK in r["output"]
            rec[v]["facts"] = "passed" if ok else (r.get("exception") or _brief(r)) + (
                f" (facts_check line {r['line']}: {r.get('source', '')})" if r.get("line") else "")
            if not ok:
                ck.fail(c["id"], f"facts_check fails in {v}: {rec[v]['facts']}")
    for t in c["traps"]:
        tres = ck.run_all(setup + "\n" + evalset.code(t["code"]) + "\nprint('WM_TRAP_RAN')")
        for v, r in tres.items():
            exc = r.get("exception", "")
            if _trap_expect(t, v):
                err, msg = per_version(t["error"], v), per_version(t.get("message", ""), v)
                if err is None or msg is None:
                    rec[v]["traps"][t["api"]] = exc or _brief(r)
                    ck.fail(c["id"], f"trap {t['api']!r} records no error or message for {v}, where it should fail")
                    continue
                good = (not r["strict"]) and exc.startswith(err) and msg in exc
                rec[v]["traps"][t["api"]] = exc or _brief(r)
                if not good:
                    ck.fail(c["id"], f"trap {t['api']!r} in {v}: expected {err}: {msg!r}, got {exc or _brief(r)!r}")
            else:
                ran = r["strict"] and "WM_TRAP_RAN" in r["output"]
                rec[v]["traps"][t["api"]] = "runs (no error)" if ran else (exc or _brief(r))
                if not ran:
                    ck.fail(c["id"], f"trap {t['api']!r} should run without an error in {v}, got {exc or _brief(r)!r}")
    return rec


def chimera_check(chimera, blender, md_text, work, goal=""):
    """What `chimera --check-result` says about a reply, with this Blender first on PATH."""
    d = tempfile.mkdtemp(prefix="chk-", dir=work)
    shim = os.path.join(d, "shim")
    os.makedirs(shim)
    with open(os.path.join(shim, "blender"), "w") as f:
        f.write(f'#!/bin/bash\nexec "{blender}" "$@"\n')
    os.chmod(os.path.join(shim, "blender"), 0o755)
    reply = os.path.join(d, "reply.md")
    with open(reply, "w", encoding="utf-8") as f:
        f.write(md_text)
    env = dict(os.environ, PATH=shim + os.pathsep + os.environ.get("PATH", ""))
    args = [chimera, "--data-dir", os.path.join(d, "data"), "--check-result", reply]
    if goal:
        args += ["--check-goal", goal]
    p = subprocess.run(args, env=env, capture_output=True, text=True, timeout=300)
    shutil.rmtree(d, ignore_errors=True)
    try:
        c = json.loads(p.stdout)["check"]
    except (ValueError, KeyError):
        return {"error": (p.stderr or p.stdout)[-400:]}
    out = {k: c.get(k) for k in ("outcome", "runner", "summary", "line", "source", "error") if c.get(k) not in (None, "")}
    m = re.search(r"running it in (.+?), sandboxed", p.stderr)
    out["ran_in"] = m.group(1) if m else None
    return out


def check_w3(ck, c, chimera=None):
    piece = evalset.code(c["piece"])
    script = evalset.python_blocks(piece)[0]
    want_v = c["crash"]["version"]
    res = ck.run_all(script)
    rec = {}
    for v, r in res.items():
        crashes_here = v in c["crash"].get("crashes_in", [want_v])
        entry = {k: r.get(k) for k in ("exception", "line", "function", "source") if r.get(k) is not None}
        entry["traceback"] = r.get("traceback", "")
        entry["passes"] = r["strict"]
        if crashes_here and r["strict"]:
            ck.fail(c["id"], f"piece should crash in {v} but passes")
        if crashes_here and not r["strict"] and not r.get("exception", "").startswith(c["crash"]["exception"].split(":")[0]):
            ck.fail(c["id"], f"{v}: expected {c['crash']['exception']!r}, got {r.get('exception')!r}")
        if not crashes_here and not r["strict"]:
            ck.fail(c["id"], f"piece should run in {v} (crash only in {c['crash'].get('crashes_in')}), got {_brief(r)}")
        if chimera:
            b = dict((x, y) for x, y in ck.blenders)[v]
            entry["chimera"] = chimera_check(chimera, b, piece, ck.work)
        rec[v] = entry
    fix = evalset.code(c["fix"]["reference"])
    blocks = evalset.python_blocks(fix)
    fres = ck.run_all(with_probe(blocks[0] if blocks else fix))
    for v, r in fres.items():
        rec[v]["reference_fix"] = "passed" if r["strict"] else _brief(r)
        if not r["strict"]:
            ck.fail(c["id"], f"reference fix fails in {v}: {_brief(r)}")
        fails = evalset.check_assertions(r.get("probe") or {}, c.get("expect", {}).get("assertions") or [])
        for f in fails:
            ck.fail(c["id"], f"reference fix {v}: {f}")
        for pat in c["fix"].get("must_not_match") or []:
            if re.search(pat, fix):
                ck.fail(c["id"], f"reference fix matches must_not_match {pat!r}")
        for pat in c["fix"].get("must_match") or []:
            if not re.search(pat, fix):
                ck.fail(c["id"], f"reference fix misses must_match {pat!r}")
    for pat in c["fix"].get("must_not_match") or []:
        if not re.search(pat, piece):
            ck.fail(c["id"], f"must_not_match {pat!r} doesn't match the broken piece (it should)")
    return rec


def check_w4f(ck, c):
    ref = c.get("reference")
    if not ref or c["mode"] != "blender":
        return None
    blocks = evalset.python_blocks(evalset.code(ref))
    res = ck.run_all(with_probe(blocks[0]))
    rec = {}
    for v, r in res.items():
        fails = evalset.check_assertions(r.get("probe") or {}, c["expect"].get("assertions") or [])
        stand = "chimera: stand-in" in r["output"]
        if not r["strict"]:
            ck.fail(c["id"], f"reference fails in {v}: {_brief(r)}")
        if c["expect"].get("stand_in") and not stand:
            ck.fail(c["id"], f"reference prints no stand-in in {v}")
        for f in fails:
            ck.fail(c["id"], f"{v}: {f}")
        rec[v] = {"reference": "passed" if r["strict"] else _brief(r), "stand_in": stand, "assertions": "passed" if not fails else fails}
    return rec


def ollama_tokens(model, text, host="http://127.0.0.1:11434"):
    body = {"model": model, "prompt": text, "raw": True, "stream": False,
            "options": {"num_predict": 1, "num_ctx": 32768, "temperature": 0}, "keep_alive": "30s"}
    req = urllib.request.Request(host + "/api/generate", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())["prompt_eval_count"]


def check_w4l(ck, c, tokens_model=None):
    total, info = 0, {}
    for sid, d in c["inputs"].items():
        if not d.get("from"):
            continue
        parts = [evalset._source_text(s) for s in d["from"]]
        text = d.get("joiner", "\n\n").join(parts)
        info[sid] = {"sha256": evalset.sha256(text), "chars": len(text)}
        total += len(text)
        if d.get("sha256") and d["sha256"] != info[sid]["sha256"]:
            ck.fail(c["id"], f"inputs.{sid} changed since it was recorded")
        if len(text) > evalset.PIECE_LIMIT:
            ck.fail(c["id"], f"inputs.{sid} is {len(text)} characters, over {evalset.PIECE_LIMIT}")
    rd = c.get("round2")
    r2 = ""
    if rd:
        r2 = "\n\n".join(evalset._source_text(s) for s in rd["previous_from"])
        info["round2"] = {"sha256": evalset.sha256(r2), "chars": len(r2)}
        total += len(r2)
    alltext = "\n\n".join(c_ for c_ in [evalset.code(x.get("piece")) if x.get("piece") else "" for x in c["inputs"].values()] if c_)
    alltext += "\n\n" + "\n\n".join(evalset.build_piece(dict(d, sha256=None)) for d in c["inputs"].values() if d.get("from")) + "\n\n" + r2
    for g in c["expect"]["needles"]:
        if not any(w.lower() in alltext.lower() for w in g):
            ck.fail(c["id"], f"needle group {g} isn't in the inputs")
    est = round(len(alltext) / 3.6)
    tok = {"estimate": est, "chars": len(alltext)}
    if tokens_model:
        tok["measured"] = ollama_tokens(tokens_model, alltext)
        tok["model"] = tokens_model
    return info, tok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--part", default="all", choices=["all", "w1", "w2", "w3", "w4f", "w4l"])
    ap.add_argument("--case", action="append", help="only these case ids (repeatable)")
    ap.add_argument("--blender", action="append", help="a Blender binary (repeatable; default: 5.2.2 and 5.0.1 in /Applications)")
    ap.add_argument("--chimera", default=os.environ.get("CHIMERA_BIN"), help="a Chimera binary for W3's --check-result records (default: $CHIMERA_BIN)")
    ap.add_argument("--tokens", help="W4 long inputs: measure tokens with this local Ollama model")
    ap.add_argument("--work", default=None, help="where the run folders go (default $WM_SCRATCH/verify-eval, else "
                                                  "worker-model/data/verify-eval)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--write", action="store_true", help="record the results in the eval files (only when every check passed)")
    ap.add_argument("--force-write", action="store_true", help="with --write: record the results even when a check failed")
    a = ap.parse_args(argv)
    a.work = a.work or default_work()
    made_work = not os.path.isdir(a.work)
    os.makedirs(a.work, exist_ok=True)
    blenders = a.blender or DEFAULT_BLENDERS
    parts = ["w1", "w2", "w3", "w4f", "w4l"] if a.part == "all" else [a.part]
    docs = {}
    for p in parts:
        with open(os.path.join(evalset.EVAL_DIR, evalset.FILES[p]), encoding="utf-8") as f:
            docs[p] = json.load(f)
    failures = []
    ck = None
    if any(p != "w4l" for p in parts):
        missing = [b for b in blenders if blender_paths.check_path(b)]
        for b in missing:
            failures.append(f"Blender: {blender_paths.check_path(b)}")
        ck = Checker([b for b in blenders if b not in missing], a.work, a.jobs)
        print("Blenders:", ", ".join(f"{v} ({b})" for v, b in ck.blenders) or "none")
        failures += [f"Blender: {x}" for x in version_problems([v for v, _ in ck.blenders])]
        for f in failures:
            print("  FAIL", f)
    wrong_blenders = bool(failures)  # never recorded, not even with --force-write: verified means both versions
    for part in parts:
        for c in docs[part]["items"]:
            if a.case and c["id"] not in a.case:
                continue
            print(f"{part} {c['id']}")
            if part == "w1":
                c["verified"] = check_w1(ck, c)
            elif part == "w2":
                c["verified"] = check_w2(ck, c, docs["w2"].get("facts_prelude"))
            elif part == "w3":
                c["verified"] = check_w3(ck, c, a.chimera)
            elif part == "w4f":
                r = check_w4f(ck, c)
                if r is not None:
                    c["verified"] = r
            elif part == "w4l":
                ck4 = ck or Checker([], a.work)
                info, tok = check_w4l(ck4, c, a.tokens)
                for sid, x in info.items():
                    if sid == "round2":
                        c["round2"]["sha256"], c["round2"]["chars"] = x["sha256"], x["chars"]
                    else:
                        c["inputs"][sid]["sha256"], c["inputs"][sid]["chars"] = x["sha256"], x["chars"]
                if a.tokens or not isinstance((c.get("input_tokens") or {}).get("measured"), int):
                    c["input_tokens"] = tok
                else:
                    c["input_tokens"].update(estimate=tok["estimate"], chars=tok["chars"])
                failures += ck4.failures
                ck4.failures = []
            if part in ("w1", "w2", "w3", "w4f") and "verified" in c:
                c["verified_on"] = time.strftime("%Y-%m-%d")
    if ck:
        failures += ck.failures
    if a.write and wrong_blenders:
        print("not written: every result is recorded for Blender " + " and ".join(evalset.VERSIONS) + ", run in both")
    elif a.write and failures and not a.force_write:
        print("not written: fix the failures first (or pass --force-write to record them anyway)")
    elif a.write:
        for p in parts:
            path = os.path.join(evalset.EVAL_DIR, evalset.FILES[p])
            with open(path, "w", encoding="utf-8") as f:
                json.dump(docs[p], f, indent=1, ensure_ascii=False)
                f.write("\n")
        print("written:", ", ".join(evalset.FILES[p] for p in parts))
    print(f"{len(failures)} check(s) failed" if failures else "all checks passed")
    if made_work:
        try:
            os.rmdir(a.work)  # every run folder is removed; take the folder too when this run made it
        except OSError:
            pass
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
