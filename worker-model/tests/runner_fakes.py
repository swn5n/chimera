"""TEST FIXTURES ONLY, NEVER TRAINING DATA: stand-ins for the runners' tests (a fake Blender, a mock Ollama per test).

Written by Claude to test runner/ (Anthropic's terms bar training on Claude outputs).
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from tests import _paths  # noqa: F401
from runner import mock_ollama


class FakeBlender:
    """Answers like runner.blender_run.Blender without running anything. strict: what every check says;
    strict_full: what the direct run's whole output says (default: strict); stand_in: the direct run printed a
    stand-in, stand_in_tail: the check's tail shows it (default: stand_in); calls records what was asked (kind, text)."""

    def __init__(self, strict=True, stand_in=False, versions=("5.2.2", "5.0.1"), strict_full=None, stand_in_tail=None):
        self.strict, self.stand_in = strict, stand_in
        self.strict_full = strict if strict_full is None else strict_full
        self.stand_in_tail = stand_in if stand_in_tail is None else stand_in_tail
        self.versions = {v: "/fake/" + v for v in versions}
        self.sandbox = True
        self.calls = []

    def check(self, text, name="script.py", goal=None):
        self.calls.append(("check", name, text))
        return {v: {"outcome": "passed" if self.strict else "failed", "strict": self.strict,
                    "strict_why": "" if self.strict else "check failed", "line": None if self.strict else 3,
                    "error": None if self.strict else "AttributeError: fake", "runner": "Blender " + v,
                    "stand_in_tail": self.stand_in_tail}
                for v in self.versions}

    def probe(self, script):
        self.calls.append(("probe", "script.py", script))
        return {v: {"exit": 0 if self.strict else 1, "strict_full": self.strict_full,
                    "bad_lines": [] if self.strict_full else ["Error: fake, early in the output"],
                    "blender": v, "version_ok": True, "stand_in": self.stand_in,
                    "exception": "", "stopped_at_render": False, "seconds": 0.1,
                    "names": ["chimera_s1"], "ctx_keys": ["s1"], "dupes": [],
                    "probe": {"objects": [], "materials": [], "scene": {}, "duplicates": []}}
                for v in self.versions}

    def run(self, script):
        return {"check": self.check(script), "probe": self.probe(script)}

    def check_python(self, text, name="result.md", goal=None):
        self.calls.append(("check_python", name, text))
        return {"outcome": "passed" if self.strict else "failed", "runner": "Python 3"}


class MockOllamaCase(unittest.TestCase):
    """A mock Ollama per test, a temp folder, and helpers to read what was sent."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wm-runner-")
        self.log = os.path.join(self.tmp, "requests.jsonl")
        self.srv, self.url = mock_ollama.serve(0, self.log)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def requests(self, path="/api/chat"):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as f:
            return [json.loads(l)["body"] for l in f if json.loads(l)["path"] == path]

    def quiet(self, fn, *a, **k):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = fn(*a, **k)
        return code, err.getvalue()

    def run_dirs(self, sub):
        root = os.path.join(self.tmp, sub)
        return sorted(os.path.join(root, d) for d in os.listdir(root)) if os.path.isdir(root) else []

    def read_jsonl(self, path):
        with open(path, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
