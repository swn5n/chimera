#!/usr/bin/env python3
"""A stand-in for Ollama's HTTP API, for testing the worker runners without a model (helper-model's mock's approach).

    python3 runner/mock_ollama.py --port 11436 --log /tmp/requests.jsonl

TEST FIXTURE ONLY, NEVER TRAINING DATA: its canned replies are Claude-written test text. Every reply's code carries
the mark below, so a leak is easy to find.

Answers /api/version, /api/tags, /api/show (any model except names starting "missing"), /api/ps, /api/chat
(streamed NDJSON, with eval counters and done_reason; a test's responder may return {"thinking", "content", "chunk"}
to stream thinking first, in chunks of that many characters) and /api/generate. Chat replies are canned by job, recognised
from the system prompt: the contract's worker (a Blender piece in the contract's shape for the step it is told it
does, with its handoff), today's worker (a plain Blender script), the combine ("You are Hydra's final editor": one
script), the planner (a 2-step Blender plan as JSON) and the reviewer. Every request body is logged.
"""
from __future__ import annotations

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MARK = "# test fixture, never training data"
CONTRACT_OPENING = "You are one worker in Chimera: a sub-agent."
LONE_OPENING = "You are one worker in Chimera, and the only one on this task"
TODAY_OPENING = "You are one worker in Chimera, a group of AI models"
SYNTH_OPENING = "You are Hydra's final editor"
PLANNER_OPENING = "You are Hydra, the planner for Chimera"
REVIEW_OPENING = "You are Hydra's reviewer in Chimera"


def contract_piece(sid, deps):
    """A Blender piece in the contract's shape: SETTINGS_sN, build_sN registering ctx["objects"][sN], the guard."""
    uses = ", ".join(f'ctx["objects"]["{d}"] from {d}' for d in deps) or "none"
    reads = "".join(f'    if "{d}" not in ctx["objects"]:\n        print("chimera: stand-in", "{d}")\n' for d in deps)
    return f'''Here is my piece.

```python
{MARK}
import bpy

SETTINGS_{sid} = {{"size": 1.0}}


def build_{sid}(ctx):
{reads}    mesh = bpy.data.meshes.new("chimera_{sid}_mesh")
    h = SETTINGS_{sid}["size"] / 2
    mesh.from_pydata([(-h, -h, 0), (h, -h, 0), (h, h, 0), (-h, h, 0)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new("chimera_{sid}", mesh)
    ctx["collection"].objects.link(obj)
    ctx["objects"]["{sid}"] = obj


if __name__ == "__main__":
    build_{sid}({{"scene": bpy.context.scene, "collection": bpy.context.scene.collection, "objects": {{}}}})
```

```handoff
provides: chimera_{sid} as ctx["objects"]["{sid}"]
uses: {uses}
assumed: none
```
'''


def today_script(name):
    return f'''```python
{MARK}
import bpy

mesh = bpy.data.meshes.new("chimera_{name}_mesh")
mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
obj = bpy.data.objects.new("chimera_{name}", mesh)
bpy.context.scene.collection.objects.link(obj)
print("made", obj.name)
```

Assumed: the other steps make the rest.'''


PLAN = {"title": "Mock scene", "kind": "blender", "summary": "A mock Blender scene in two steps. " + MARK,
        "steps": [{"id": "s1", "title": "Floor", "kind": "blender", "instructions": "Make a floor plane.", "depends_on": []},
                  {"id": "s2", "title": "Box on the floor", "kind": "blender", "instructions": "Put a box on s1's floor.",
                   "depends_on": ["s1"]}]}


def reply_for(system, user):
    if system.startswith(CONTRACT_OPENING):
        m = re.search(r"You do step (s\d+) of (\d+)", system)
        sid = m.group(1) if m else "s1"
        mine = re.search(r"^→ s\d+\. .*?\(uses ([^)]*)\)", system, re.M)
        deps = [d.strip() for d in mine.group(1).split(",")] if mine else []
        return contract_piece(sid, deps)
    if system.startswith(LONE_OPENING):
        return contract_piece("s1", []).split("```handoff")[0]
    if system.startswith(TODAY_OPENING):
        m = re.search(r"^→ (\d+)\.", system, re.M)
        return today_script("step%s" % (m.group(1) if m else "1"))
    if system.startswith(SYNTH_OPENING):
        return today_script("combined")
    if system.startswith(PLANNER_OPENING):
        return json.dumps(PLAN)
    if system.startswith(REVIEW_OPENING):
        return json.dumps({"done": True, "score": 90, "critique": "Nothing left to fix. " + MARK})
    return "OK"


class Handler(BaseHTTPRequestHandler):
    lock = threading.Lock()
    log_path = None
    loaded = []  # what /api/ps reports
    extra = []  # responders tried first: fn(system, user, body) -> text or None

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        b = json.loads(self.rfile.read(n) or b"{}")
        if Handler.log_path:
            with Handler.lock, open(Handler.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"path": self.path, "body": b}) + "\n")
        return b

    def do_GET(self):
        if self.path == "/api/version":
            return self._send(200, {"version": "0.0.0-mock"})
        if self.path == "/api/tags":
            return self._send(200, {"models": [{"name": "mock:latest", "model": "mock:latest", "digest": "0123456789abcdef", "size": 1}]})
        if self.path == "/api/ps":
            return self._send(200, {"models": [{"name": n, "model": n} for n in Handler.loaded]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        b = self._body()
        if self.path == "/api/show":
            if str(b.get("model", "")).startswith("missing"):
                return self._send(404, {"error": f"model '{b.get('model')}' not found"})
            return self._send(200, {"details": {"family": "mock", "parameter_size": "0B", "quantization_level": "none"},
                                    "model_info": {"mock.context_length": 40960}, "capabilities": ["completion"]})
        if self.path == "/api/generate":
            if b.get("keep_alive") in (0, "0", "0s") and b.get("model") in Handler.loaded:
                Handler.loaded = [m for m in Handler.loaded if m != b.get("model")]  # unloaded: gone from /api/ps
            return self._send(200, {"done": True})
        if self.path != "/api/chat":
            return self._send(404, {"error": "not found"})
        if str(b.get("model", "")).startswith("missing"):
            return self._send(404, {"error": f"model '{b.get('model')}' not found"})
        msgs = b.get("messages") or []
        system = msgs[0]["content"] if msgs and msgs[0]["role"] == "system" else ""
        user = msgs[-1]["content"] if msgs else ""
        text = None
        for fn in Handler.extra:
            text = fn(system, user, b)
            if text is not None:
                break
        if text is None:
            text = reply_for(system, user)
        thinking, size = "", None
        if isinstance(text, dict):  # {"thinking": ..., "content": ..., "chunk": characters per chunk}
            thinking, size, text = text.get("thinking") or "", text.get("chunk"), text.get("content") or ""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        chunks = []
        for key, s in (("thinking", thinking), ("content", text)):
            step = size or max(1, len(s) // 3)
            chunks += [{"message": {"role": "assistant", "content": "", key: s[i:i + step]}, "done": False}
                       for i in range(0, len(s), step)]
        chunks.append({"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop",
                       "prompt_eval_count": sum(len(m["content"]) for m in msgs) // 4, "eval_count": len(text) // 4 + 3,
                       "total_duration": 2000000, "load_duration": 1000, "prompt_eval_duration": 1000,
                       "eval_duration": 1000000})
        try:
            for ch in chunks:
                self.wfile.write((json.dumps(ch) + "\n").encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):  # the client stopped reading (the runaway guard)
            pass


def serve(port=0, log_path=None):
    """Start the mock in a background thread; returns (server, base_url)."""
    Handler.log_path, Handler.extra, Handler.loaded = log_path, [], []
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=11436)
    ap.add_argument("--log")
    a = ap.parse_args()
    srv, url = serve(a.port, a.log)
    print("mock Ollama on", url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
