"""Shared pieces for the data generator: stores, model calls, progress, sanity stops."""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # helper-model/
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from runner.ollama_client import Ollama  # noqa: E402

TEACHER = "gpt-oss:120b"
WORKERS = ("qwen3:4b-instruct-2507-q4_K_M", "qwen3:1.7b", "qwen3:8b")
SOURCE_NOTE = "written by gpt-oss:120b (teacher) or the Qwen workers; nothing here is written by Claude"


def stable_int(*parts) -> int:
    """A number that depends only on parts: the same item always gets the same seed and sample."""
    return int(hashlib.sha256("\x1f".join(map(str, parts)).encode("utf-8")).hexdigest()[:8], 16)


def rng(*parts) -> random.Random:
    return random.Random(stable_int(*parts))


def weighted(r: random.Random, pairs):
    """Pick from [(value, weight), ...]."""
    total = sum(w for _, w in pairs)
    x = r.random() * total
    for v, w in pairs:
        x -= w
        if x <= 0:
            return v
    return pairs[-1][0]


class Store:
    """An append-only JSONL file keyed by "key". A rerun skips keys already written, so every
    stage can stop at any point and pick up where it left off."""

    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.rows = {}
        if os.path.exists(path):
            with open(path, "rb") as f:
                data = f.read()
            if data and not data.endswith(b"\n"):  # an interrupted write: start a fresh line
                with open(path, "ab") as f:
                    f.write(b"\n")
            for line in data.decode("utf-8", "replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue  # the half-written line
                self.rows[r["key"]] = r

    def has(self, key):
        return key in self.rows

    def get(self, key):
        return self.rows.get(key)

    def add(self, rec):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.rows[rec["key"]] = rec

    def all(self):
        return list(self.rows.values())


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def first_list(obj, key, want=None):
    """obj[key] if it's a list, else the first list among obj's values whose items pass want()."""
    if not isinstance(obj, dict):
        return []
    v = obj.get(key)
    if isinstance(v, list):
        return v
    for v in obj.values():
        if isinstance(v, list) and v and (want is None or all(want(x) for x in v)):
            return v
    return []


def parse_obj(text):
    """The first JSON object in a reply (the same leniency as Chimera's extractJSON)."""
    t = (text or "").strip()
    for cand in (t, t[t.find("{"):t.rfind("}") + 1] if "{" in t and "}" in t else ""):
        if not cand:
            continue
        try:
            v = json.loads(cand)
        except ValueError:
            continue
        if isinstance(v, dict):
            return v
    return None


class Models:
    """Calls Ollama, keeping one model loaded at a time (the teacher needs 65 GB)."""

    def __init__(self, host, timeout=300.0, effort=None, log=None):
        self.client = Ollama(host, timeout)
        self.effort = effort  # the teacher's reasoning effort: None (its default), low, medium or high
        self.loaded = None
        self.calls = 0
        self.log = log

    def use(self, model):
        if self.loaded and self.loaded != model:
            self.client.unload(self.loaded)
        self.loaded = model

    def call(self, body, timeout=None):
        self.use(body["model"])
        self.calls += 1
        return self.client.chat(body, timeout or self.client.timeout)

    def chat(self, model, messages, *, fmt=None, options=None, think=None, timeout=None):
        body = {"model": model, "messages": messages, "stream": True, "keep_alive": "15m", "options": dict(options or {})}
        if fmt is not None:
            body["format"] = fmt
        if think is not None:
            body["think"] = think
        return self.call(body, timeout)

    def teacher_think(self):
        return self.effort  # None: leave it to the model's default, as Chimera does

    def close(self):
        if self.loaded:
            self.client.unload(self.loaded)
            self.loaded = None


class Progress:
    def __init__(self, stage, total, log_path=None):
        self.stage, self.total, self.done, self.t0, self.new = stage, total, 0, time.monotonic(), 0
        self.log_path = log_path

    def step(self, label, status, wall=None, skipped=False):
        self.done += 1
        if skipped:
            return
        self.new += 1
        rate = (time.monotonic() - self.t0) / self.new
        left = (self.total - self.done) * rate
        eta = f"{int(left // 3600)}h{int(left % 3600 // 60):02d}m" if left >= 60 else f"{int(left)}s"
        line = f"[{self.stage} {self.done}/{self.total}] {label} {status}" + (f" {wall:.1f}s" if wall else "") + f" (left ~{eta})"
        print(line, file=sys.stderr, flush=True)
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(time.strftime("%H:%M:%S ") + line + "\n")


class Stopped(SystemExit):
    pass


def sanity(data_dir, stage, what, ok, checked, need, size, examples=()):
    """Stop the run early when a stage's first items look wrong, before hours are spent on it."""
    if not size.get("sanity", True) or checked != size["check_after"]:
        return
    rate = ok / checked if checked else 0.0
    if rate >= need:
        print(f"[{stage}] sanity check passed: {what} {ok}/{checked} ({rate:.0%}, needs {need:.0%})", file=sys.stderr)
        return
    lines = [f"# Stopped at the {stage} stage", "",
             f"Only {ok} of the first {checked} {what} ({rate:.0%}; at least {need:.0%} expected).",
             "Nothing is lost: fix the cause, then run the same command again to continue.", "",
             "## Last replies", ""]
    for ex in list(examples)[-3:]:
        lines += ["```", str(ex)[:1500], "```", ""]
    path = os.path.join(data_dir, "STOPPED.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    raise Stopped(f"{stage}: only {ok}/{checked} {what}; see {path}")


def final_sanity(data_dir, stage, what, ok, checked, need, size, examples=()):
    """The smoke run's end-of-stage check, for stages with fewer items than check_after. Only items
    processed in this run count: zero means nothing to do, or all done before (a resumed run)."""
    if not size.get("final_checks") or checked == 0:
        return
    if checked < size["check_after"]:
        sanity(data_dir, stage, what, ok, checked, need, dict(size, check_after=checked), examples)


def warn_if_low(stage, what, ok, checked, need):
    """For optional stages: say so when few items worked, but never stop the run."""
    if checked and ok / checked < need:
        print(f"[{stage}] note: only {ok}/{checked} {what}; carrying on without the rest (this stage is optional)",
              file=sys.stderr, flush=True)


def round_robin(items, key):
    """Interleave items by key (sorted), so the first few of a stage cover every category."""
    groups = {}
    for it in items:
        groups.setdefault(key(it), []).append(it)
    names = sorted(groups)
    out = []
    while any(groups[n] for n in names):
        for n in names:
            if groups[n]:
                out.append(groups[n].pop(0))
    return out
