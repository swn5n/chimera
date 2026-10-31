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
planner, the critique it was given.
Repairs and later rounds (section 11): a repair (job "mend") answers with edits for BLENDERMEND (one crash), BLENDERMEND2
(two crashes in turn), BLENDERMENDBAD (the first repair breaks the script, the second is right), BLENDERMENDFAR (a new
crash each time), BLENDERSTUCK (edits that leave the crash where it was), BLENDERWHOLE (the script written out) and PYMEND;
everything else gets no edits, so its crash goes on to the next round as in section 10. BLENDEREDIT, BLENDERONE,
BLENDERWORSE, BLENDERGONE, BLENDERGONE3, BLENDERSTOP, BLENDERLIMIT and BLENDERMISS start from a script that runs and which
the reviewer sends back; their later combine answers with edits: a fill light (BLENDERONE's later plan has one step), a
crash, or for BLENDERMISS a FIND that's nowhere. BLENDERGONE's later plan is unreadable, whichever model is asked, as is
BLENDERGONE3's third. BLENDERSTOP's repair takes 4 s, for cancelling it, as does BLENDERSTOPCUT's, whose first result was cut
off. BLENDERUNCH crashes and its edits never land. BLENDERBADLATER goes from a crash to a script that doesn't start. BLENDERPROSE's first combine has no script. BLENDERLONG has six steps, the first with a long output.
BLENDERNAMES crashes on a misspelt attribute of one of bpy's objects. BLENDEROFFSHOT prints a scene its camera can't see, as the check's measuring would, and a repair moves the camera; BLENDERSTAYSOFF's repairs change nothing. BLENDERUNSURE is sent back with a script the check is unsure of. PYKIND's later plan is labelled general. TEALOOP is a guide, with no script, that the reviewer sends back once."""
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
    "crash2": """import bpy
import mathutils

scene = bpy.context.scene
backdrop = bpy.data.objects.new("chimera_backdrop", None)
backdrop.rotation_euler = (mathutils.radians(180), 0.0, 0.0)  # flip normal
scene.collection.objects.link(backdrop)
backdrop.scale = (mathutils.degrees(1.0), 1.0, 1.0)
print("chimera_backdrop ready")""",
    "far": """import bpy
import mathutils

scene = bpy.context.scene
a = mathutils.step_1
b = mathutils.step_2
c = mathutils.step_3
d = mathutils.step_4
e = mathutils.step_5
f = mathutils.step_6
g = mathutils.step_7
h = mathutils.step_8
i = mathutils.step_9
j = mathutils.step_10
print("ran to the end")""",
    "names": """import bpy

scene = bpy.context.scene
backdrop = bpy.data.objects.new("chimera_backdrop", None)
scene.collection.objects.link(backdrop)
spot = backdrop.locaton
print(spot)
print("chimera_backdrop ready")""",
    "offshot": """import bpy

scene = bpy.context.scene
backdrop = bpy.data.objects.new("chimera_backdrop", None)
scene.collection.objects.link(backdrop)
seen = 0
print('chimera-check: scene {"camera": {"name": "chimera_cam", "at": [0, -5, 2], "ahead": [0, 1, 0], "lens": 50, "type": "PERSP"}, "objects": [{"name": "chimera_backdrop", "at": [9, 9, 9], "size": [2, 2, 2], "hits": %d, "frame": %s}], "total": 1, "seen": %d, "out": %d, "filled": %s, "cube": false, "empty": [], "animated": false, "span": [[8, 8, 8], [10, 10, 10]], "pose": {"at": [9, -3, 9], "rotation": [1.5708, 0, 0], "sees": 1}}' % (seen * 500, "true" if seen else "false", seen, 1 - seen, seen * 0.3))""",
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
                 "CUTOFF": ("cut", "fixed"), "CUTALWAYS": ("cut", "cut"), "CUTONCE": ("cut", "cut"),
                 "BLENDERMEND2": ("crash2", "crash2"), "BLENDERMENDBAD": ("crash", "crash"), "BLENDERMENDFAR": ("far", "far"),
                 "BLENDERMEND": ("crash", "crash"), "BLENDEREDIT": ("fixed", "fixed"), "BLENDERONE": ("fixed", "fixed"),
                 "BLENDERWORSE": ("fixed", "fixed"), "BLENDERGONE": ("fixed", "fixed"), "BLENDERGONE3": ("fixed", "fixed"),
                 "BLENDERSTOP": ("fixed", "fixed"), "BLENDERLIMIT": ("fixed", "fixed"), "BLENDERMISS": ("fixed", "fixed"),
                 "BLENDERSTUCK": ("crash", "crash"), "BLENDERWHOLE": ("crash", "crash"), "BLENDERBADLATER": ("crash", "crash"),
                 "BLENDERPROSE": ("crash", "crash"), "BLENDERLONG": ("fixed", "fixed"), "BLENDERUNCH": ("crash", "crash"),
                 "BLENDERSTOPCUT": ("cut", "crash"), "BLENDERUNSURE": ("scene", "scene"), "BLENDERNAMES": ("names", "names"),
                 "BLENDEROFFSHOT": ("offshot", "offshot"), "BLENDERSTAYSOFF": ("offshot", "offshot")}
CODE_MARKS = {"PYCRASH": ("py_crash", "py_fixed"), "PYINPUT": ("py_input", "py_input"), "PYMEND": ("py_crash", "py_crash"),
              "PYKIND": ("py_crash", "py_crash")}
SENT_BACK = ("BLENDEREDIT", "BLENDERONE", "BLENDERWORSE", "BLENDERGONE", "BLENDERGONE3", "BLENDERSTOP", "BLENDERMISS",
             "BLENDERUNSURE")


# Edits for the later round's combine.
FILL_EDIT = """<<<<<<< FIND
scene.collection.objects.link(backdrop)
=======
scene.collection.objects.link(backdrop)
fill = bpy.data.objects.new("chimera_fill", None)
scene.collection.objects.link(fill)
>>>>>>> END"""
CRASH_EDIT = """<<<<<<< FIND
scene.collection.objects.link(backdrop)
=======
scene.collection.objects.link(backdrop)
fill = bpy.data.objects.new("chimera_fill", None)
fill.scale = mathutils.make_it_bigger(2.0)
>>>>>>> END"""
RADIANS_EDIT = """<<<<<<< FIND
import mathutils
=======
import mathutils
import math
>>>>>>> END

<<<<<<< FIND
backdrop.rotation_euler = (mathutils.radians(180), 0.0, 0.0)  # flip normal
=======
backdrop.rotation_euler = (math.radians(180), 0.0, 0.0)  # flip normal
>>>>>>> END"""
SYNTAX_EDIT = "<<<<<<< FIND\nimport mathutils\n=======\nimport mathutils(\n>>>>>>> END"
PY_EDIT = """<<<<<<< FIND
print("average:", averge(numbers))
=======
print("average:", average(numbers))
>>>>>>> END"""
MISS_EDIT = "<<<<<<< FIND\nthis line is in no script\n=======\nfill = 1\n>>>>>>> END"
mends, plans, combines = {}, {}, {}  # calls so far of each job, per goal marker


def marker(user):
    # Longest first: BLENDERMEND is inside BLENDERMEND2.
    return next((m for m in sorted(list(BLENDER_MARKS) + list(CODE_MARKS), key=len, reverse=True) if m in user), None)


def mend_reply(mark, user):
    """A repair's reply: edits, or none for the crash to go on to the next round."""
    with lock:
        mends[mark] = n = mends.get(mark, 0) + 1
    if mark in ("BLENDERSTOP", "BLENDERSTOPCUT"):
        time.sleep(4)
    if mark == "PYMEND":
        return PY_EDIT
    if mark == "BLENDERWHOLE":
        return "```python\n%s\n```" % SCRIPTS["fixed"]
    if mark == "BLENDEROFFSHOT":
        return "<<<<<<< FIND\nseen = 0\n=======\nseen = 1\n>>>>>>> END"
    if mark == "BLENDERSTUCK":
        old, new = ('print("chimera_backdrop ready")', 'print("ready")') if n == 1 else ('print("ready")', 'print("ok")')
        return "<<<<<<< FIND\n%s\n=======\n%s\n>>>>>>> END" % (old, new)
    if mark not in ("BLENDERMEND", "BLENDERMEND2", "BLENDERMENDBAD", "BLENDERMENDFAR"):
        return "I can't see what's wrong with it."
    if mark == "BLENDERMENDBAD" and n == 1:
        return SYNTAX_EDIT
    if mark == "BLENDERMENDFAR":
        if n > 10:
            return "I can't see what's wrong with it."
        return "<<<<<<< FIND\n%s = mathutils.step_%d\n=======\n%s = 1\n>>>>>>> END" % ("abcdefghij"[n - 1], n, "abcdefghij"[n - 1])
    if "has no attribute 'degrees'" in user:
        return "<<<<<<< FIND\nbackdrop.scale = (mathutils.degrees(1.0), 1.0, 1.0)\n=======\nbackdrop.scale = (math.degrees(1.0), 1.0, 1.0)\n>>>>>>> END"
    return RADIANS_EDIT


def later_plan(mark, user):
    return "The previous attempt produced this result:" in user


def studio_plan(mark, user):
    version = 2 if "The previous attempt produced this result:" in user else 1
    kind = "code" if mark in CODE_MARKS else "blender"
    if mark == "PYKIND" and version == 2:
        kind = "general"
    steps = [{"id": "s1", "title": "Studio part one", "kind": kind, "instructions": "Write the first part.", "depends_on": []},
             {"id": "s2", "title": "Studio part two", "kind": kind, "instructions": "Write the second part.", "depends_on": []}]
    if mark == "BLENDERONE" and version == 2:
        steps = steps[:1]
    if mark == "BLENDERLONG":
        steps = [dict(steps[0], instructions="Write the long part.")] + [
            dict(steps[1], id="s%d" % i, title="Studio part %d" % i) for i in range(2, 7)]
    return {"title": "Studio v%d" % version, "kind": kind, "summary": "A small studio script in two parts.", "steps": steps}


def studio_combine(mark, user):
    """The combined result for a marker: (text, done_reason)."""
    later = "Project: Studio v2" in user
    with lock:
        combines[mark] = n = combines.get(mark, 0) + 1
    if later and mark in ("BLENDEREDIT", "BLENDERONE"):
        return (FILL_EDIT, "stop")
    if later and mark in ("BLENDERWORSE", "BLENDERSTOP", "BLENDERGONE3"):
        return (CRASH_EDIT, "stop")
    if later and mark == "BLENDERLIMIT":
        return (CRASH_EDIT if n == 6 else FILL_EDIT, "stop")
    if later and mark in ("BLENDERMISS", "BLENDERUNCH"):
        return (MISS_EDIT, "stop")
    if later and mark == "BLENDERBADLATER":
        return (SYNTAX_EDIT, "stop")
    if later and mark == "PYKIND":
        return (PY_EDIT, "stop")
    if not later and mark == "BLENDERPROSE":
        return ("I would build the studio from a backdrop, a floor and three lights.", "stop")
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
                        ("You repair one script in Chimera", "mend"),
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
        if mark == "BLENDERGONE" and later_plan(mark, user):
            return "I would rather not plan this one."
        if mark == "BLENDERGONE3" and later_plan(mark, user):
            with lock:
                plans[mark] = plans.get(mark, 0) + 1
                if plans[mark] > 1:
                    return "I would rather not plan this one."
        if mark:
            return json.dumps(studio_plan(mark, user))
        return json.dumps(PLAN)
    if job == "reviewer":
        if helper and "BADREVIEW" in user:
            return "Looks good to me overall."
        if marker(user) in SENT_BACK and "chimera_fill" not in user:
            return json.dumps({"check": "1. A fill light: no.", "done": False, "score": 60, "critique": "Add a fill light."})
        if marker(user) == "BLENDERLIMIT":
            return json.dumps({"check": "1. More lights: no.", "done": False, "score": 60, "critique": "Add another light."})
        if marker(user) == "BLENDERPROSE" and "```python" not in user:
            return json.dumps({"check": "1. A script: no.", "done": False, "score": 10, "critique": "There is no script."})
        if "TEALOOP" in user and "Second draft" not in user:
            return json.dumps({"check": "1. Black tea: no.", "done": False, "score": 60, "critique": "Say more about black tea."})
        if helper:
            return json.dumps({"check": "1. Covers green and black tea: yes.", "done": True, "score": 90, "critique": ""})
        return json.dumps({"done": True, "score": 88, "critique": ""})
    if job == "worker":
        if "Write the long part." in user:
            return "# filler line for a long piece of work\n" * 500 + "# TAILMARK"
        return "A paragraph about tea, written by %s." % model
    if job == "mend":
        return mend_reply(marker(user), user)
    if job == "combine":
        mark = marker(user)
        if mark:
            return studio_combine(mark, user)
        if "TEALOOP" in user and "The result so far:" in user:
            return "Second draft of the guide, combined by %s." % model
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
            sysmsg = next((m["content"] for m in body.get("messages", []) if m["role"] == "system"), "")
            with open(LOG, "a") as f:
                f.write(json.dumps({"t": time.time(), "model": model, "job": job, "format": "format" in body,
                                    "num_ctx": opts.get("num_ctx"), "num_predict": opts.get("num_predict"),
                                    "critique": critique, "user": user[:300], "user_all": user if job in ("worker", "combine", "mend", "planner") else "",
                                    "edits": "<<<<<<< FIND" in sysmsg}) + "\n")
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
