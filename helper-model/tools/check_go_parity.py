#!/usr/bin/env python3
"""Check helper/chimera_port.py against Chimera's real Go code on real replies.

    python3 tools/check_go_parity.py                 # every reply in results/runs/*/raw.jsonl + the test fixtures
    python3 tools/check_go_parity.py --go /opt/homebrew/bin/go

Copies the Go source of extractJSON, cleanPlan, hydraStep, hydraPlan and reviewVerdict out of
app/ (cut out by parsing, not retyped), wraps them in a tiny program, runs it with `go run`,
and compares what Go decides for each reply with what the Python port decides: accepted or
not, and the plan, verdict or answer Chimera would act on. Writes results/GO_PARITY.txt.
Needs Go 1.21 or newer.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
APP = os.path.join(os.path.dirname(HERE), "app")

from helper import chimera_port as cp  # noqa: E402

PIECES = [("library.go", "func extractJSON("), ("hydra.go", "func cleanPlan("), ("hydra.go", "type hydraStep struct"),
          ("hydra.go", "type hydraPlan struct"), ("hydra.go", "type reviewVerdict struct")]

MAIN = r'''
func main() {
	sc := bufio.NewScanner(os.Stdin)
	sc.Buffer(make([]byte, 1<<20), 1<<28)
	enc := json.NewEncoder(os.Stdout)
	for sc.Scan() {
		var in struct {
			Job  string `json:"job"`
			Text string `json:"text"`
		}
		if err := json.Unmarshal(sc.Bytes(), &in); err != nil {
			panic(err)
		}
		switch in.Job {
		case "planner":
			var p hydraPlan
			ok := extractJSON(in.Text, &p) && len(p.Steps) > 0
			if ok {
				p = cleanPlan(p)
				enc.Encode(map[string]any{"ok": true, "value": p})
			} else {
				enc.Encode(map[string]any{"ok": false})
			}
		case "reviewer":
			var v reviewVerdict
			ok := extractJSON(in.Text, &v)
			enc.Encode(map[string]any{"ok": ok, "value": v})
		default:
			var g struct {
				Use bool `json:"use"`
			}
			ok := extractJSON(in.Text, &g)
			enc.Encode(map[string]any{"ok": ok, "value": map[string]any{"use": g.Use}})
		}
	}
}
'''


def cut(src, start):
    """The Go declaration that begins at start, through its matching closing brace."""
    i = src.index(start)
    j = src.index("{", i)
    depth, k = 0, j
    while k < len(src):
        c = src[k]
        if c in "\"'`":  # skip string, rune and raw-string literals
            q, k = c, k + 1
            while src[k] != q:
                k += 2 if (src[k] == "\\" and q != "`") else 1
        elif src.startswith("//", k):
            k = src.index("\n", k)
            continue
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
        k += 1
    raise ValueError(f"no end for {start}")


def go_program():
    parts = ["package main", "", 'import (\n\t"bufio"\n\t"encoding/json"\n\t"fmt"\n\t"os"\n\t"strings"\n\t"time"\n)', ""]
    for fname, start in PIECES:
        with open(os.path.join(APP, fname), encoding="utf-8") as f:
            parts.append(cut(f.read(), start))
        parts.append("")
    parts.append(MAIN)
    return "\n".join(parts)


def cases():
    out = []
    for path in sorted(glob.glob(os.path.join(HERE, "results", "runs", "*", "raw.jsonl"))):
        with open(path, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                out.append({"job": r["job"], "text": r["reply"], "where": f"{os.path.basename(os.path.dirname(path))}/{r['id']}"})
    fx = os.path.join(HERE, "tests", "fixtures", "go_parity.jsonl")
    if os.path.exists(fx):
        with open(fx, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                r = json.loads(line)
                out.append({"job": r["job"], "text": r["text"], "where": f"fixture {i}"})
    return out


def py_view(job, text):
    if job == "planner":
        ok, v, _ = cp.extract_json(text, cp.PLAN_SPEC)
        ok = bool(ok and v["steps"])
        return ok, (cp.clean_plan(v) if ok else None)
    spec = cp.REVIEW_SPEC if job == "reviewer" else cp.GATE_SPEC
    ok, v, _ = cp.extract_json(text, spec)
    return ok, v


def comparable(job, v):
    if v is None:
        return None
    if job == "planner":
        return {"title": v["title"], "kind": v["kind"], "summary": v["summary"],
                "steps": [{"id": s["id"], "title": s["title"], "kind": s["kind"], "instructions": s["instructions"],
                           "depends_on": list(s.get("depends_on") or [])} for s in v["steps"]]}
    if job == "reviewer":
        return {"done": v["done"], "score": v["score"], "critique": v["critique"]}
    return {"use": v["use"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--go", default=shutil.which("go") or "/opt/homebrew/bin/go")
    ap.add_argument("--out", default=os.path.join(HERE, "results", "GO_PARITY.txt"))
    a = ap.parse_args(argv)
    if not os.path.exists(a.go) and not shutil.which(a.go):
        print("Go isn't installed here; skipping the parity check")
        return 0
    cs = cases()
    with tempfile.TemporaryDirectory(prefix="chimera-parity-") as d:
        with open(os.path.join(d, "main.go"), "w", encoding="utf-8") as f:
            f.write(go_program())
        with open(os.path.join(d, "go.mod"), "w") as f:
            f.write("module parity\n\ngo 1.21\n")
        feed = "".join(json.dumps({"job": c["job"], "text": c["text"]}) + "\n" for c in cs)
        env = dict(os.environ, GOFLAGS="-mod=mod", GOTOOLCHAIN="local")
        p = subprocess.run([a.go, "run", "."], cwd=d, input=feed, capture_output=True, text=True, env=env)
    if p.returncode != 0:
        print("go run failed:\n" + p.stderr)
        return 2
    goes = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
    if len(goes) != len(cs):
        print(f"Go answered {len(goes)} of {len(cs)} cases")
        return 2
    bad = []
    for c, g in zip(cs, goes):
        ok, v = py_view(c["job"], c["text"])
        gv = g.get("value") if g["ok"] else None
        if c["job"] != "planner" and g["ok"]:
            gv = {k.lower(): x for k, x in gv.items()}
        if ok != g["ok"] or (ok and comparable(c["job"], v) != comparable(c["job"], gv)):
            bad.append(f"{c['where']} ({c['job']}): Go ok={g['ok']} value={json.dumps(comparable(c['job'], gv))[:300]}\n"
                       f"    Python ok={ok} value={json.dumps(comparable(c['job'], v))[:300]}")
    lines = [f"Go vs Python port on {len(cs)} replies: {len(cs) - len(bad)} agree, {len(bad)} differ."] + bad
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(lines[0] + (" See " + os.path.relpath(a.out, HERE) if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
