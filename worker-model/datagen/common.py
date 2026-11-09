"""Shared plumbing for Hydra Worker's data generator: keys and stable randomness, Chimera's token estimate, the
append-only stores and caches every stage resumes from, atomic writes, progress lines, and stopping.

The ideas are helper-model/datagen/common.py's (Store, stable_int, rng, Progress, STOPPED.md), copied rather than
imported: both folders have runner/ and tools/ packages, so helper-model is never put on sys.path. What is new is
the locking: seeds run in threads here (DESIGN.md, "Concurrency"), so every store, cache and log line is written
under a lock, and a line is always written whole by one call.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import random
import sys
import threading
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # worker-model/
if HERE not in sys.path:
    sys.path.insert(0, HERE)
DATA_ROOT = os.path.join(HERE, "data", "gen")  # gitignored with the rest of data/

STOP_FILE = "STOP"
STOPPED_FILE = "STOPPED.md"
RUN_FILE = "RUN.json"

_log_lock = threading.Lock()  # one lock for every appended log line in this process


def key_of(*parts) -> str:
    """The cache key of a call or run: sha256 over the parts as sorted JSON, first 24 hex characters. Raises
    TypeError for anything JSON can't write (a set, say), whose order would make the key unstable."""
    text = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def stable_int(*parts) -> int:
    """A number that depends only on parts (helper-model's): the same item always gets the same seed and sample."""
    return int(hashlib.sha256("\x1f".join(map(str, parts)).encode("utf-8")).hexdigest()[:8], 16)


def rng(*parts) -> random.Random:
    """A random.Random seeded by stable_int(*parts)."""
    return random.Random(stable_int(*parts))


def chance(p, *parts) -> bool:
    """True for about a share p of the parts given, the same answer for the same parts every time."""
    return stable_int(*parts) % 10000 < p * 10000


def est_tokens(text) -> int:
    """Chimera's estimateTokens (app/library.go): bytes / 3 + 64."""
    return len((text or "").encode("utf-8")) // 3 + 64


def msgs_tokens(messages) -> int:
    """Chimera's historyTokens (app/runprompt.go): est_tokens summed over the messages' content."""
    return sum(est_tokens(m.get("content")) for m in messages or ())


def now_iso() -> str:
    """The local time with its offset, to the second (RUN.json, STOPPED.md)."""
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def mend_tail(path):
    """Give a file that ends in a half-written line its newline back, so the next append starts a fresh line
    (the half line itself stays and is skipped by every reader). Nothing happens to a missing or empty file."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            if f.tell() == 0:
                return
            f.seek(-1, os.SEEK_END)
            last = f.read(1)
    except FileNotFoundError:
        return
    if last != b"\n":
        with open(path, "ab") as f:
            f.write(b"\n")


def _lines(data: bytes):
    """The JSON objects in JSONL bytes; a line that isn't one (the half-written last line of a killed run) is
    skipped. Lines end at b"\\n" only: str.splitlines also breaks at U+0085, U+2028 and U+2029, which
    json.dumps(ensure_ascii=False) leaves raw inside a string, and would cut such a record in two."""
    for raw in data.split(b"\n"):
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            yield obj


class Store:
    """An append-only JSONL file keyed by rec["key"] (helper-model's Store, made thread-safe). A rerun skips keys
    already written, so a stage can stop at any point and pick up where it left off. On load a half-written last
    line is skipped and the file gets its newline back; when a key appears twice, the later line wins. add() writes
    the whole line in one call and flushes it (no fsync: a lost last line only means that work is done again)."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self.rows = {}
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        if os.path.exists(path):
            with open(path, "rb") as f:
                data = f.read()
            mend_tail(path)
            for rec in _lines(data):
                if "key" in rec:
                    self.rows[rec["key"]] = rec

    def has(self, key) -> bool:
        with self._lock:
            return key in self.rows

    __contains__ = has

    def get(self, key):
        """The record stored under key, or None."""
        with self._lock:
            return self.rows.get(key)

    def add(self, rec):
        """Append rec (a dict with a "key") and keep it in memory; a key added again replaces the earlier record."""
        line = json.dumps(rec, ensure_ascii=False) + "\n"  # before the file is touched: a bad record writes nothing
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)
            self.rows[rec["key"]] = rec

    def all(self):
        """Every record, in the order its key was first written."""
        with self._lock:
            return list(self.rows.values())

    def keys(self):
        with self._lock:
            return list(self.rows)

    def __len__(self):
        with self._lock:
            return len(self.rows)


class Cache(Store):
    """A Store of {"key", "value"} lines: model calls (cache/calls.jsonl) and Blender or Python runs
    (cache/runs.jsonl), keyed by a hash of their full input."""

    def get(self, key):
        """The value cached under key, or None."""
        rec = super().get(key)
        return None if rec is None else rec.get("value")

    def put(self, key, value):
        self.add({"key": key, "value": value})


def write_jsonl(path, rows):
    """Write rows as JSONL atomically (a .tmp file, then os.replace): a crash never leaves half a file."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def read_jsonl(path):
    """The objects in a JSONL file ([] when it is missing). As in Store, a line that isn't JSON (the half-written
    line of a killed append) is skipped."""
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        return list(_lines(f.read()))


def append_jsonl(path, rec):
    """Append one JSON line to a log that isn't keyed (gate.jsonl), whole and under the log lock."""
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with _log_lock:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        mend_tail(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)


def write_json(path, obj):
    """Write JSON atomically (.tmp, then os.replace)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def log_line(log_path, line):
    """Append a time-stamped line to a log (progress.log); nothing when log_path is None."""
    if not log_path:
        return
    with _log_lock:
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + line + "\n")


class Progress:
    """helper-model's progress lines (stderr and progress.log) with an estimate of the time left; thread-safe, since
    seeds finish in any order."""

    def __init__(self, stage, total, log_path=None):
        self.stage, self.total, self.log_path = stage, total, log_path
        self.done, self.new, self.t0 = 0, 0, time.monotonic()
        self._lock = threading.Lock()

    def step(self, label, status, wall=None, skipped=False):
        """One item finished. skipped: it was done before (a resumed run), which counts but adds no line and
        doesn't enter the rate."""
        with self._lock:
            self.done += 1
            if skipped:
                return
            self.new += 1
            rate = (time.monotonic() - self.t0) / self.new
            left = max(0, self.total - self.done) * rate
            eta = f"{int(left // 3600)}h{int(left % 3600 // 60):02d}m" if left >= 60 else f"{int(left)}s"
            line = (f"[{self.stage} {self.done}/{self.total}] {label} {status}" + (f" {wall:.1f}s" if wall else "")
                    + f" (left ~{eta})")
            print(line, file=sys.stderr, flush=True)
            log_line(self.log_path, line)


class StopRequested(Exception):
    """data_dir/STOP exists: finish the calls in flight, start nothing new (the run exits 3)."""


def stop_path(data_dir):
    return os.path.join(data_dir, STOP_FILE)


def check_stop(data_dir):
    """Raise StopRequested when data_dir/STOP exists (touch it to stop a run after the calls in flight)."""
    p = stop_path(data_dir)
    if os.path.exists(p):
        raise StopRequested(f"{p} exists")


def write_stopped(data_dir, title, lines):
    """Write data_dir/STOPPED.md, the note an early stop leaves: a title, then the lines. Returns its path."""
    path = os.path.join(data_dir, STOPPED_FILE)
    os.makedirs(data_dir, exist_ok=True)
    text = "\n".join([f"# {title}", ""] + [str(x) for x in lines]) + "\n"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return path


class Stopped(SystemExit):
    """An early stop (STOPPED.md says why). Exits with code 3 if nothing catches it; str() is the reason."""

    def __init__(self, message=""):
        super().__init__(3)
        self.message = message

    def __str__(self):
        return self.message


def run_record(data_dir, **fields):
    """Write RUN.json for this start: fields (plus "started", now, unless given), and under "starts" the records of
    every earlier start, oldest first, so a resumed run keeps its history. Returns what was written."""
    path = os.path.join(data_dir, RUN_FILE)
    prev = read_json(path, None)
    starts = []
    if isinstance(prev, dict):
        starts = list(prev.get("starts") or [])
        starts.append({k: v for k, v in prev.items() if k != "starts"})
    rec = dict(fields)
    rec.setdefault("started", now_iso())
    rec["starts"] = starts
    write_json(path, rec)
    return rec
