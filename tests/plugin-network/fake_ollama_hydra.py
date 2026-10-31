"""A fake Ollama for hydra_test.py: several models, each answering Chimera's jobs the way the test needs, plus
enough of /api/blobs and /api/create to take Hydra 1.0 from the host. Every chat call is logged with the model
and the job (from the system prompt), so the test can tell which model did what.
Usage: python3 fake_ollama_hydra.py <port> <log file> <config json>
Config: {"models": [{"name", "size", "params", "arch", "loaded"}], "show": {model: {"modelfile", "template",
"parameters", "license"}}, "blob_dir": folder for pushed files}. POST /test/models {"models": [...]} replaces the
list; GET /test/state returns the files pushed (and how many times) and the models created.
Goal markers for the result check (section 10 of hydra_test.py): BLENDERCRASH, BLENDERSAME, BLENDERSAVE, BLENDERSCENE,
BLENDERRENDER, BLENDERSLOW, CUTOFF, CUTALWAYS and CUTONCE get a two-step "blender" plan, PYCRASH and PYINPUT a two-step
"code" plan, titled "Studio v1" (or "Studio v2" once the planner is shown a previous attempt); the combine then writes
one ```python script chosen by marker and version (see SCRIPTS). A cut combine ends part-way, with done_reason
"length" and eval_count 4096. Each call's log line also has the request's num_predict and num_ctx and, for the
planner, the critique it was given."""
import hashlib, json, os, sys, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT, LOG, CONF = int(sys.argv[1]), sys.argv[2], json.load(open(sys.argv[3]))
lock = threading.Lock()
models = list(CONF["models"])
show = dict(CONF.get("show", {}))
blob_dir = CONF.get("blob_dir")
blobs, creates, pushes = {}, [], {}

PLAN = {"title": "Tea guide", "kind": "writing", "summary": "A short guide in two parts.",
        "steps": [{"id": "s1", "title": "Green tea", "kind": "writing", "instructions": "Write about green tea.", "depends_on": []},
                  {"id": "s2", "title": "Black tea", "kind": "writing", "instructions": "Write about black tea.", "depends_on": []}]}

# The result check's scripts. Blender: "crash" stops at line 7 on mathutils.radians (the real mathutils has none).
SCRIPTS = {
    "crash": """import bpy
import mathutils

scene = bpy.context.scene
bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 1.0))
backdrop = bpy.data.objects.new("chimera_backdrop", None)
backdrop.rotation_euler = (mathutils.radians(180), 0.0, 0.0)  # flip normal
scene.collection.objects.link(backdrop)
print("chimera_backdrop ready")""",
    "fixed": """import bpy
import math

scene = bpy.context.scene
bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 1.0))
backdrop = bpy.data.objects.new("chimera_backdrop", None)
backdrop.rotation_euler = (math.radians(180), 0.0, 0.0)  # flip normal
scene.collection.objects.link(backdrop)
print("chimera_backdrop ready")""",
    "save": """import bpy

scene = bpy.context.scene
bpy.ops.mesh.primitive_cube_add(size=2.0)
backdrop = bpy.data.objects.new("chimera_backdrop", None)
scene.collection.objects.link(backdrop)
bpy.ops.wm.save_as_mainfile(filepath="/var/tmp/chimera-check-escape.blend")
print("saved the studio")""",
    "scene": """import bpy

scene = bpy.context.scene
hero = bpy.data.objects['Hero']
hero.location = (0.0, 0.0, 1.0)
key = bpy.data.objects.new("chimera_key", None)
scene.collection.objects.link(key)
print("lit the hero")""",
    "render": """import bpy

scene = bpy.context.scene
bpy.ops.mesh.primitive_cube_add(size=2.0)
backdrop = bpy.data.objects.new("chimera_backdrop", None)
scene.collection.objects.link(backdrop)
bpy.ops.render.render(write_still=False)
print("rendered the studio")""",
    "slow": """import bpy
import time

scene = bpy.context.scene
backdrop = bpy.data.objects.new("chimera_backdrop", None)
scene.collection.objects.link(backdrop)
time.sleep(300)
print("waited")""",
    "py_crash": """def average(values):
    total = 0
    for v in values:
        total += v
    return total / len(values)

numbers = [3, 5, 8, 13]
print("average:", averge(numbers))""",
    "py_fixed": """def average(values):
    total = 0
    for v in values:
        total += v
    return total / len(values)

numbers = [3, 5, 8, 13]
print("average:", average(numbers))""",
    "py_input": """def greet(name):
    return "Hello, " + name + "!"

name = input("Your name: ")
print(greet(name))
print("Nice to meet you.")
print("Bye.")""",
}
# Marker -> the script for round 1 and for later rounds ("cut": the combine stops at its output limit).
BLENDER_MARKS = {"BLENDERCRASH": ("crash", "fixed"), "BLENDERSAME": ("crash", "crash"), "BLENDERSAVE": ("save", "save"),
                 "BLENDERSCENE": ("scene", "scene"), "BLENDERRENDER": ("render", "render"), "BLENDERSLOW": ("slow", "slow"),
                 "CUTOFF": ("cut", "fixed"), "CUTALWAYS": ("cut", "cut"), "CUTONCE": ("cut", "cut")}
CODE_MARKS = {"PYCRASH": ("py_crash", "py_fixed"), "PYINPUT": ("py_input", "py_input")}


def marker(user):
    return next((m for m in list(BLENDER_MARKS) + list(CODE_MARKS) if m in user), None)


def studio_plan(mark, user):
    kind = "code" if mark in CODE_MARKS else "blender"
    version = 2 if "The previous attempt produced this result:" in user else 1
    return {"title": "Studio v%d" % version, "kind": kind, "summary": "A small studio script in two parts.",
            "steps": [{"id": "s1", "title": "Studio part one", "kind": kind, "instructions": "Write the first part.", "depends_on": []},
                      {"id": "s2", "title": "Studio part two", "kind": kind, "instructions": "Write the second part.", "depends_on": []}]}


def studio_combine(mark, user):
    """The combined result for a marker: (text, done_reason)."""
    later = "Project: Studio v2" in user
    name = (BLENDER_MARKS.get(mark) or CODE_MARKS[mark])[1 if later else 0]
    if name == "cut":
        body = "\n".join("cube_%d = bpy.data.objects.new(\"chimera_cube_%d\", None)\nscene.collection.objects.link(cube_%d)" % (i, i, i)
                         for i in range(12))
        return ("Here is the combined Blender script.\n\n```python\nimport bpy\n\nscene = bpy.context.scene\n" + body +
                "\nfor i in range(", "length")
    if mark in CODE_MARKS:
        return ("Here is the finished program.\n\n```python\n%s\n```\n\nRun it with:\n\n```bash\npython3 studio.py\n```\n" % SCRIPTS[name], "stop")
    return ("Here is the combined Blender script.\n\n```python\n%s\n```\n\nRun it headless:\n\n```bash\nblender -b --python studio.py\n```\n"
            % SCRIPTS[name], "stop")


ARCH = {"llama": {"llama.context_length": 32768, "llama.block_count": 32, "llama.attention.head_count": 32,
                  "llama.attention.head_count_kv": 8, "llama.embedding_length": 4096},
        "qwen3": {"qwen3.context_length": 262144, "qwen3.block_count": 36, "qwen3.attention.head_count": 32,
                  "qwen3.attention.head_count_kv": 8, "qwen3.attention.key_length": 128, "qwen3.embedding_length": 2560}}


def job_of(body):
    sys_msg = next((m["content"] for m in body.get("messages", []) if m["role"] == "system"), "")
    for prefix, job in (("You are Hydra, the planner", "planner"), ("You are Hydra's reviewer", "reviewer"),
                        ("You are one worker in Chimera", "worker"), ("You are Hydra's final editor", "combine"),
                        ("You decide whether a request should be handled by a tool", "gate"),
                        ("You maintain the shared library", "library"), ("You check entries before", "library")):
        if sys_msg.startswith(prefix):
            return job
    return "options" if "format" in body else "chat"


def reply(model, job, body):
    user = "\n".join(m["content"] for m in body.get("messages", []) if m["role"] == "user")
    helper = model.startswith("hydra:")
    if job == "planner":
        if helper and "GARBLE" in user:
            return "First I would look at the teas, then write it up."  # not JSON: Chimera must ask again
        mark = marker(user)
        if mark:
            return json.dumps(studio_plan(mark, user))
        return json.dumps(PLAN)
    if job == "reviewer":
        if helper and "BADREVIEW" in user:
            return "Looks good to me overall."
        if helper:
            return json.dumps({"check": "1. Covers green and black tea: yes.", "done": True, "score": 90, "critique": ""})
        return json.dumps({"done": True, "score": 88, "critique": ""})
    if job == "worker":
        return "A paragraph about tea, written by %s." % model
    if job == "combine":
        mark = marker(user)
        if mark:
            return studio_combine(mark, user)
        return "The finished guide, combined by %s." % model
    if job == "gate":
        req = user.split("Request:")[-1].split("Should this tool")[0].lower()
        return json.dumps({"use": any(v in req for v in ("make", "draw", "create")) and "?" not in req})
    if job == "options":
        return "{}"
    if job == "library":
        return json.dumps({"skip": True})
    return "Hello from %s." % model


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_HEAD(self):
        if self.path.startswith("/api/blobs/"):
            d = self.path[len("/api/blobs/"):]
            self.send_response(200 if d in blobs else 404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/version":
            return self.send({"version": "0.40.1"})
        if self.path == "/api/tags":
            with lock:
                ms = [{"name": m["name"], "model": m["name"], "size": m["size"], "digest": "dg-" + m["name"],
                       "details": {"family": m.get("arch", "llama"), "parameter_size": m["params"], "quantization_level": "Q5_K_M"}}
                      for m in models]
            return self.send({"models": ms})
        if self.path == "/api/ps":
            with lock:
                return self.send({"models": [{"name": m["name"], "model": m["name"]} for m in models if m.get("loaded")]})
        if self.path == "/test/state":
            with lock:
                return self.send({"blobs": dict(blobs), "pushes": dict(pushes), "creates": creates, "models": [m["name"] for m in models]})
        self.send({"error": "not found"}, 404)

    def do_POST(self):
        if self.path.startswith("/api/blobs/"):
            d = self.path[len("/api/blobs/"):]
            n = int(self.headers.get("Content-Length", 0) or 0)
            h, left = hashlib.sha256(), n
            path = os.path.join(blob_dir, d.replace(":", "-"))
            with open(path, "wb") as f:
                while left > 0:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    h.update(chunk)
                    f.write(chunk)
                    left -= len(chunk)
            with lock:
                pushes[d] = pushes.get(d, 0) + 1
            if "sha256:" + h.hexdigest() != d or left:
                return self.send({"error": "digest mismatch"}, 400)
            with lock:
                blobs[d] = n
            self.send_response(201)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = self.body()
        if self.path == "/test/models":
            with lock:
                models[:] = body["models"]
            return self.send({"ok": True})
        if self.path == "/api/show":
            name = body.get("model", "")
            with lock:
                m = next((x for x in models if x["name"] == name), None)
                extra = show.get(name, {})
            if not m:
                return self.send({"error": "model '%s' not found" % name}, 404)
            arch = m.get("arch", "llama")
            out = {"capabilities": ["completion"], "model_info": dict(ARCH[arch], **{"general.architecture": arch})}
            out.update(extra)
            return self.send(out)
        if self.path == "/api/create":
            with lock:
                for d in (body.get("files") or {}).values():
                    if d not in blobs:
                        return self.send({"error": "file %s not found" % d}, 400)
                creates.append(body)
                size = sum(blobs[d] for d in body["files"].values())
                models.append({"name": body["model"], "size": size, "params": "4.0B", "arch": "qwen3"})
                show[body["model"]] = {"template": body.get("template", ""), "license": body.get("license", "")}
            lines = [{"status": "using existing layer"}, {"status": "writing manifest"}, {"status": "success"}]
            data = "".join(json.dumps(l) + "\n" for l in lines).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/api/chat":
            model, job = body.get("model", ""), job_of(body)
            opts = body.get("options") or {}
            user = "\n".join(m["content"] for m in body.get("messages", []) if m["role"] == "user")
            critique = None
            if job == "planner" and "What still needs work:\n" in user:
                critique = user.split("What still needs work:\n", 1)[1].split("\n\nPlan the steps", 1)[0][:600]
            with open(LOG, "a") as f:
                f.write(json.dumps({"t": time.time(), "model": model, "job": job, "format": "format" in body,
                                    "num_ctx": opts.get("num_ctx"), "num_predict": opts.get("num_predict"),
                                    "critique": critique, "user": user[:300]}) + "\n")
            text, reason = reply(model, job, body), "stop"
            if isinstance(text, tuple):
                text, reason = text
            chunks = [text[i:i + 16] for i in range(0, len(text), 16)] or [""]
            out = b"".join((json.dumps({"message": {"role": "assistant", "content": c}, "done": False}) + "\n").encode() for c in chunks)
            out += (json.dumps({"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": reason,
                                "eval_count": 4096 if reason == "length" else 30,
                                "prompt_eval_count": 60, "eval_duration": 100000000, "prompt_eval_duration": 50000000,
                                "total_duration": 200000000, "load_duration": 1000000}) + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        if self.path == "/api/generate":
            return self.send({"done": True})
        self.send({"error": "not found"}, 404)


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
