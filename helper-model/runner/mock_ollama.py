#!/usr/bin/env python3
"""A stand-in for Ollama's HTTP API, for testing the runner without a model.

    python3 runner/mock_ollama.py --port 11435 --log /tmp/requests.jsonl

Answers /api/version, /api/tags, /api/show, /api/chat (streamed NDJSON), /api/generate and
/api/embed. Chat replies are canned by job (it recognises Chimera's system prompts); every
third reply is deliberately messy (a code fence, a float score, "Yes") so the scoring paths
for Chimera-rejected and lenient replies get exercised too. Every request body is logged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from helper import prompts  # noqa: E402


def plan_reply(user, n):
    steps = [
        {"id": "s1", "title": "Work out the parts", "kind": "general", "instructions": "List the pieces the task needs and the names they share: " + user[:80], "depends_on": []},
        {"id": "s2", "title": "Build the first part", "kind": "code", "instructions": "Write the first piece in full, using the names from the plan summary.", "depends_on": []},
        {"id": "s3", "title": "Build the second part", "kind": "code", "instructions": "Write the second piece in full, using the names from step 1.", "depends_on": ["s1"]},
    ]
    plan = {"title": "Mock plan", "kind": "code", "summary": "A mock plan. It has three steps.", "steps": steps}
    if n % 3 == 2:
        return "```json\n" + json.dumps(plan) + "\n```"
    return json.dumps(plan)


def review_reply(user, n):
    result = user.split("The result so far:\n", 1)[-1]
    bad = "TODO" in result or len(result) < 400
    if n % 3 == 2:
        return '{"done": false, "score": 72.5, "critique": "Not sure."}'
    if bad:
        return json.dumps({"done": False, "score": 40, "critique": "It is incomplete: finish the missing parts and add tests."})
    return json.dumps({"done": True, "score": 85, "critique": ""})


def gate_reply(user, n):
    req = user.split("Request: ", 1)[-1].split("\n\nShould this tool", 1)[0].lower()
    use = any(w in req for w in ("generate", "draw", "render", "compose", "picture", "image", "beat", "poster", "3d model")) and not req.rstrip().endswith("?")
    if n % 3 == 2:
        return "Yes" if use else "No"
    return json.dumps({"use": use})


class Handler(BaseHTTPRequestHandler):
    counter = 0
    lock = threading.Lock()
    log_path = None
    think = True
    extra = []  # responders tried first: fn(system, user, messages, body, n) -> text or None

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
        self._send(404, {"error": "not found"})

    def do_POST(self):
        b = self._body()
        if self.path == "/api/show":
            if not str(b.get("model", "")).startswith("mock"):
                return self._send(404, {"error": f"model '{b.get('model')}' not found"})
            return self._send(200, {"details": {"family": "mock", "parameter_size": "0B", "quantization_level": "none"},
                                    "model_info": {"mock.context_length": 32768}, "capabilities": ["completion"]})
        if self.path == "/api/generate":
            return self._send(200, {"done": True})
        if self.path == "/api/embed":
            vecs = []
            for text in b.get("input", []):
                v = [0.0] * 64
                for w in text.lower().split():
                    v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
                vecs.append(v)
            return self._send(200, {"embeddings": vecs})
        if self.path != "/api/chat":
            return self._send(404, {"error": "not found"})
        msgs = b.get("messages") or []
        system = msgs[0]["content"] if msgs and msgs[0]["role"] == "system" else ""
        user = msgs[-1]["content"] if msgs else ""
        with Handler.lock:
            Handler.counter += 1
            n = Handler.counter
        text = None
        for fn in Handler.extra:
            text = fn(system, user, msgs, b, n)
            if text is not None:
                break
        if text is None:
            if system == prompts.HYDRA_PLANNER_PROMPT:
                text = plan_reply(user, n)
            elif system == prompts.HYDRA_REVIEW_PROMPT:
                text = review_reply(user, n)
            elif system == prompts.HEAD_GATE_PROMPT:
                text = gate_reply(user, n)
            else:
                text = "OK"
        done_reason = "stop"
        cap = (b.get("options") or {}).get("num_predict")
        if cap and len(text) > cap * 4:  # about 4 characters a token
            text, done_reason = text[:cap * 4], "length"
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        chunks = []
        if Handler.think and b.get("think") is not False:
            chunks.append({"message": {"role": "assistant", "content": "", "thinking": "Let me think. "}, "done": False})
        third = max(1, len(text) // 3)
        for i in range(0, len(text), third):
            chunks.append({"message": {"role": "assistant", "content": text[i:i + third]}, "done": False})
        chunks.append({"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": done_reason,
                       "prompt_eval_count": len(user) // 4, "eval_count": len(text) // 4 + 3,
                       "total_duration": 1000000, "load_duration": 1000, "prompt_eval_duration": 1000, "eval_duration": 100000})
        for ch in chunks:
            self.wfile.write((json.dumps(ch) + "\n").encode())
            self.wfile.flush()


def serve(port=0, log_path=None, think=True):
    """Start the mock in a background thread; returns (server, base_url)."""
    Handler.log_path, Handler.think, Handler.counter = log_path, think, 0
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=11435)
    ap.add_argument("--log")
    a = ap.parse_args()
    srv, url = serve(a.port, a.log)
    print("mock Ollama on", url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
