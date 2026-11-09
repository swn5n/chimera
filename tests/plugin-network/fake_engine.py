#!/usr/bin/env python3
"""A stand-in for an engine's server (like InferSSD serving DeepSeek), for tests:
GET /health, and POST /v1/chat/completions streaming OpenAI-style chunks with
reasoning_content (the thinking) before content, then usage and llama.cpp-style
timings. It records every request it gets in --log (one JSON per line).

The reply depends on the last user message (its own words, not the list of
attached files Chimera adds after them):
  "page"    an answer with a whole HTML page in a code block (and an image it links
            to: the first attached picture, when the message has pictures attached)
  files     with files attached and none of these words, a list of the paths it got
  "slow"    a long stream (one chunk every 0.2 s for a minute): for cancelling
  "ponder"  with thinking on, thinks for 30 s before answering
  "long"    finishes with finish_reason "length"
  "crash"   the server exits mid-reply
  anything  a short answer with a table and a Python block
Usage: fake_engine.py --port N [--log FILE] [--start-delay S]"""
import argparse, html, json, os, re, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--log", default="")
ap.add_argument("--start-delay", type=float, default=0.5)
ap.add_argument("--context", default="")
a = ap.parse_args()
time.sleep(a.start_delay)  # a real engine takes a while to load its model

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Fake page</title>
<style>body{font-family:sans-serif;background:#111;color:#eee} .hero{color:#ff6a00}</style></head>
<body><h1 class="hero">Hello from the fake engine</h1><img id="pic" src="assets/pixel.png" alt="pixel">
<p id="where"></p>
<p id="checks"></p>
<script>
document.getElementById('where').textContent = 'origin=' + self.origin + ' hash=' + location.hash;
var out = [];
try { out.push('parent: ' + (parent.document ? 'READABLE' : '?')); } catch (e) { out.push('parent: blocked'); }
try { localStorage.setItem('x', '1'); out.push('storage: READABLE'); } catch (e) { out.push('storage: blocked'); }
fetch('/api/state').then(function (r) { return r.json(); }).then(function () { out.push('api: READABLE'); }, function () { out.push('api: blocked'); })
  .then(function () { return fetch('/api/quit', {method: 'POST', headers: {'X-Chimera': '1'}}); })
  .then(function (r) { out.push('quit: SENT ' + r.status); }, function () { out.push('quit: blocked'); })
  .then(function () { document.getElementById('checks').textContent = out.join(' | '); document.title = 'checks:' + out.join(' | '); });
</script>
</body></html>"""


PAGE_FILES = """<!doctype html>
<html><head><meta charset="utf-8"><title>Your picture</title>
<style>body{font-family:sans-serif;background:#111;color:#eee} img{max-width:320px;background:#333}</style></head>
<body><h1>Built from your files</h1><img id="pic" src="{src}" alt="your picture">
<p id="state">loading</p>
<script>
var img = document.getElementById('pic');
img.onload = function () { document.getElementById('state').textContent = 'loaded ' + img.naturalWidth + 'x' + img.naturalHeight; document.title = 'pic:loaded'; };
img.onerror = function () { document.getElementById('state').textContent = 'failed'; document.title = 'pic:failed'; };
</script>
</body></html>"""


def split_note(text):
    """A message's own words, and the list of attached files Chimera put after them."""
    if text.startswith("Attached file"):
        return "", text
    i = text.find("\n\nAttached file")
    if i >= 0:
        return text[:i], text[i + 2:]
    return text, ""


def answer_for(text):
    words, note = split_note(text)
    t = words.lower()
    pics = re.findall(r"^- `([^`]+)`: picture", note, re.M)
    if "page" in t and pics:
        return "Here's the page with your picture:\n\n```html\n" + PAGE_FILES.replace("{src}", html.escape(pics[0])) + "\n```\n"
    if "page" in t:
        return "Here's the page:\n\n```html\n" + PAGE + "\n```\n\nOpen it in the preview."
    if note:
        return "I got these files: " + ", ".join(re.findall(r"^- `([^`]+)`", note, re.M)) + "."
    return ("Short answer.\n\n| Part | Size |\n|---|---:|\n| Boom | 45 ft |\n| Deck | 19 ft |\n\n"
            "```python\nprint('hello')\n```\n\n- one\n  - nested\n- [x] done\n")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def chunk(self, obj):
        data = ("data: " + json.dumps(obj) + "\n\n").encode()
        self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
        self.wfile.flush()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        req = json.loads(self.rfile.read(n) or b"{}")
        if a.log:
            with open(a.log, "a") as f:
                f.write(json.dumps(req) + "\n")
        last = ""
        for m in req.get("messages", []):
            if m.get("role") == "user":
                last = m.get("content", "")
        words = split_note(last)[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        think = (req.get("chat_template_kwargs") or {}).get("enable_thinking", False)
        n_out = 0
        try:
            if think and "ponder" in words.lower():  # a long think, for the thinking clock
                for i in range(150):
                    self.chunk({"choices": [{"delta": {"reasoning_content": "step %d. " % i}}]})
                    n_out += 1
                    time.sleep(0.2)
            if think:
                for w in ["Let me ", "think about ", "this ", "carefully. "]:
                    self.chunk({"choices": [{"delta": {"reasoning_content": w}}]})
                    n_out += 1
                    time.sleep(0.05)
            if "slow" in words.lower():
                for i in range(300):
                    self.chunk({"choices": [{"delta": {"content": "word%d " % i}}]})
                    n_out += 1
                    time.sleep(0.2)
            if "crash" in words.lower():
                self.chunk({"choices": [{"delta": {"content": "about to "}}]})
                os._exit(3)
            text = answer_for(last)
            for i in range(0, len(text), 40):
                self.chunk({"choices": [{"delta": {"content": text[i:i + 40]}}]})
                n_out += 1
                time.sleep(0.01)
            finish = "length" if "long" in words.lower() else "stop"
            self.chunk({"choices": [{"delta": {}, "finish_reason": finish}]})
            self.chunk({"choices": [], "usage": {"prompt_tokens": 42, "completion_tokens": n_out},
                        "timings": {"prompt_n": 42, "prompt_per_second": 30.5, "predicted_n": n_out, "predicted_per_second": 4.25}})
            done = b"data: [DONE]\n\n"
            self.wfile.write(b"%x\r\n%s\r\n0\r\n\r\n" % (len(done), done))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            if a.log:
                with open(a.log, "a") as f:
                    f.write(json.dumps({"cancelled_after": n_out}) + "\n")


ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
