#!/usr/bin/env python3
"""Check a training file for leaks from every eval set before training on it.

    python3 tools/check_overlap.py train.jsonl [--field prompt] [--n 8] [--threshold 0.5]

Checks against three eval sets: helper-model/eval/ (v1.1), helper-model/eval-long/ and this folder's eval/
(the worker eval, eval/frozen/ included). A training line is flagged when it contains either canary
string, repeats an eval text (after lower-casing and squashing punctuation and spaces), or contains at
least --threshold of an eval text's word n-grams. It is also flagged when it carries one of this
folder's own marks (MARKS): the test fixtures' and mock Ollama's code mark, or the scene probes'
epilogue and output lines, all Claude-written. The approach and the helper sets' texts come from
helper-model/tools/check_overlap.py, loaded by path as it is (helper-model stays off sys.path, and no
bytecode is written into it); the worker set's texts come from evalset.texts().
Exit status 1 when anything is flagged. Without --field, every string in the line is checked.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # worker-model/
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import evalset  # noqa: E402

HELPER_TOOL = os.path.join(evalset.HELPER, "tools", "check_overlap.py")
HELPER_PKG = os.path.join(evalset.HELPER, "helper")

# Claude-written text from this folder that must never reach training either, by a fixed line it always carries
# (tests/test_check_overlap.py checks each one against its source): the code mark of tests/contract_fixtures.py
# and runner/mock_ollama.py, the epilogue that tools/scene_probe.py appends and the line it prints, and
# eval/scene_probe.py's output line (the eval probe's own text carries the canary).
MARKS = {
    "# test fixture, never training data": "mark:test-fixture",
    "# ---- chimera scene probe (worker-model/tools/scene_probe.py)": "mark:scene-probe-epilogue",
    "chimera-probe:": "mark:scene-probe-output",
    "CHIMERA_PROBE ": "mark:eval-probe-output",
}


class _no_bytecode:
    """Don't write __pycache__ into helper-model/ while loading its modules (this folder only reads it)."""

    def __enter__(self):
        self.was, sys.dont_write_bytecode = sys.dont_write_bytecode, True

    def __exit__(self, *exc):
        sys.dont_write_bytecode = self.was


def helper_modules():
    """(helper-model's tools/check_overlap.py, its helper.evalset), loaded by path: both folders have tools/ and
    tests/ packages, so helper-model is never left on sys.path (its check_overlap puts it there; it is taken off
    again), and no bytecode is written into it. The helper package is registered under its own name, as
    runner/common.py's helper_port does."""
    pkg = sys.modules.get("helper")
    if pkg is None:
        spec = importlib.util.spec_from_file_location("helper", os.path.join(HELPER_PKG, "__init__.py"),
                                                      submodule_search_locations=[HELPER_PKG])
        pkg = importlib.util.module_from_spec(spec)
        sys.modules["helper"] = pkg
        with _no_bytecode():
            spec.loader.exec_module(pkg)
    if [os.path.realpath(p) for p in getattr(pkg, "__path__", [])] != [os.path.realpath(HELPER_PKG)]:
        raise RuntimeError(f"another module named helper is loaded ({getattr(pkg, '__file__', pkg)})")
    saved = list(sys.path)
    try:
        with _no_bytecode():
            hevalset = importlib.import_module("helper.evalset")
            spec = importlib.util.spec_from_file_location("helper_check_overlap", HELPER_TOOL)
            hc = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hc)
    finally:
        sys.path[:] = saved
    return hc, hevalset


class EvalIndex:
    """Every eval text from all three sets, by id, with their n-grams; the canaries and this folder's marks."""

    def __init__(self, n=8, helper_dir=evalset.HELPER, worker_dir=evalset.EVAL_DIR):
        hc, hevalset = helper_modules()
        self.words, self.strings = hc.words, hc.strings

        self.n = n
        self.canaries, self.sets = [], []
        self.grams, self.exact, self.sizes = defaultdict(set), {}, {}
        for name, sub in (("helper-eval", "eval"), ("helper-eval-long", "eval-long")):
            es = hevalset.load(os.path.join(helper_dir, sub))
            self.canaries.append(es.canary)
            self.sets.append(f"{name} {es.version}")
            for eid, text in hc.eval_texts(es):
                self._add(f"{name}:{eid}", text, keep_short=True)
        ws = evalset.load(worker_dir, helper_dir)
        self.canaries.append(ws.canary)
        self.sets.append(f"worker-eval {ws.version}")
        for eid, text in evalset.texts(worker_dir):
            self._add(f"worker-eval:{eid}", text, keep_short=False)
        for name in ("w4l",):  # the long inputs as the worker sees them (rebuilt, so their joins are covered too)
            for c in ws.cases(name):
                for sid, text in ws.long_inputs(c).items():
                    self._add(f"worker-eval:{c['id']}/inputs.{sid}", text, keep_short=False)
        self.canary_marks = sorted({c.split()[-1] for c in self.canaries})

    def _add(self, eid, text, keep_short):
        w = self.words(text)
        if len(w) < self.n:
            if keep_short:  # helper-model's rule: short eval texts (a chat prompt like "hi") must not be repeated whole
                self.exact[" ".join(w)] = eid
            return
        g = {tuple(w[i:i + self.n]) for i in range(len(w) - self.n + 1)}
        self.sizes[eid] = len(g)
        for x in g:
            self.grams[x].add(eid)

    def check(self, text, threshold=0.5):
        hits = [("canary", 1.0) for mark in self.canary_marks if mark in text]
        hits += [(name, 1.0) for mark, name in MARKS.items() if mark in text]
        w = self.words(text)
        whole = " ".join(w)
        if whole in self.exact:
            hits.append((self.exact[whole], 1.0))
        counts = defaultdict(int)
        for x in {tuple(w[i:i + self.n]) for i in range(len(w) - self.n + 1)}:
            for eid in self.grams.get(x, ()):
                counts[eid] += 1
        for eid, c in counts.items():
            frac = c / self.sizes[eid]
            if frac >= threshold:
                hits.append((eid, round(frac, 3)))
        return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("train", help="a JSONL file (or plain text, one example per line)")
    ap.add_argument("--field", help="the key that holds the text to check (default: every string in the line)")
    ap.add_argument("--n", type=int, default=8, help="n-gram length in words (default 8)")
    ap.add_argument("--threshold", type=float, default=0.5, help="share of an eval text's n-grams that counts as a copy")
    a = ap.parse_args(argv)
    index = EvalIndex(a.n)
    flagged = total = 0
    with open(a.train, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                obj = json.loads(line)
                text = "\n".join(index.strings(obj.get(a.field) if a.field and isinstance(obj, dict) else obj))
            except ValueError:
                text = line
            hits = index.check(text, a.threshold)
            if hits:
                flagged += 1
                print(f"line {lineno}: " + ", ".join(f"{eid} ({frac:.0%})" for eid, frac in hits))
    sets = ", ".join(index.sets)
    print(f"{flagged} of {total} lines overlap the eval sets ({sets})" if flagged else f"no overlap with the eval sets ({sets}) in {total} lines")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
