"""A fake Ollama for Chimera's integration test: one small chat model. Structured-output
requests (format = a JSON schema) get options derived from the words in the request."""
import json, sys, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

MODEL = {"name": "fake-llm:8b", "model": "fake-llm:8b", "size": 4920000000, "digest": "f00d",
         "details": {"family": "llama", "parameter_size": "8.0B", "quantization_level": "Q4_K_M"}}
LOG = sys.argv[2] if len(sys.argv) > 2 else None

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/api/version": return self.send({"version": "0.12.6"})
        if self.path == "/api/tags": return self.send({"models": [MODEL]})
        if self.path == "/api/ps": return self.send({"models": []})
        self.send({"error": "not found"}, 404)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/show":
            return self.send({"capabilities": ["completion"], "model_info": {
                "general.architecture": "llama", "llama.context_length": 32768, "llama.block_count": 32,
                "llama.attention.head_count": 32, "llama.attention.head_count_kv": 8, "llama.embedding_length": 4096}})
        if self.path == "/api/chat":
            if LOG:
                with open(LOG, "a") as f:
                    f.write(json.dumps({"format": "format" in body, "last": body["messages"][-1]["content"][-200:]}) + "\n")
            if "format" in body and "should this tool handle the request" in body["messages"][-1]["content"].lower():
                # The Head gate: yes when the person asks to make something, no for questions/chat.
                req = body["messages"][-1]["content"].split("Request:")[-1].split("Should this tool")[0].lower()
                verbs = ("make", "generate", "create", "draw", "render", "paint", "produce")
                text = json.dumps({"use": any(v in req for v in verbs) and "?" not in req})
            elif "format" in body:
                req = body["messages"][-1]["content"].split("Request:")[-1].lower()
                out = {}
                if "left" in req: out["style"] = "left"
                if "right" in req: out["style"] = "right"
                if "dark" in req: out["darkness"] = 0.95
                if "slow" in req: out["delay_s"] = 40
                if "huge" in req: out["darkness"] = 7      # out of range: Chimera must clamp it
                for c in ("red", "green", "blue"):
                    if c in req: out["colour"] = c
                text = json.dumps(out)
            else:
                text = "Hello from the fake model."
            self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.end_headers()
            for i in range(0, len(text), 8):
                self.wfile.write((json.dumps({"message": {"role": "assistant", "content": text[i:i+8]}, "done": False}) + "\n").encode())
                self.wfile.flush(); time.sleep(0.01)
            self.wfile.write((json.dumps({"message": {"role": "assistant", "content": ""}, "done": True, "eval_count": 20,
                "prompt_eval_count": 50, "eval_duration": 100000000, "prompt_eval_duration": 50000000,
                "total_duration": 200000000, "load_duration": 1000000}) + "\n").encode())
            return
        self.send({"error": "not found"}, 404)

ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
