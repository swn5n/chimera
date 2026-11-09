"""A fake Ollama for Chimera's documentation screenshots.

It lists a few realistic models and answers Chimera's jobs (chat, the planner, workers, the combine,
the reviewer) with made-up text, so the screenshots show a believable pool without any real data.
Usage: python3 fake_ollama_shots.py <port> <config json>
Config: {"models": [{"name", "size_gb", "params", "arch", "layers", "heads", "kv", "emb", "ctx", "tps",
"caps", "loaded"}], "step_seconds": 4}. tps is the speed the reply claims; the text itself streams faster."""
import hashlib, json, sys, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT, CONF = int(sys.argv[1]), json.load(open(sys.argv[2]))
MODELS = CONF["models"]
STEP_SECONDS = float(CONF.get("step_seconds", 4))

PLAN = {
    "title": "Maple Street Bakery site",
    "kind": "code",
    "summary": "A one-page site for a neighbourhood bakery, built as four small pieces that join into one HTML file.",
    "steps": [
        {"id": "s1", "title": "Page structure", "kind": "code", "depends_on": [],
         "instructions": "Write the HTML skeleton: a header with the bakery's name, then sections for the menu, the opening hours and the contact details, with clear class names."},
        {"id": "s2", "title": "Styling", "kind": "code", "depends_on": [],
         "instructions": "Write the CSS: a warm cream and brown palette, a centred column, card styling for the menu items and a layout that works on phones."},
        {"id": "s3", "title": "Menu items", "kind": "writing", "depends_on": [],
         "instructions": "Write six menu items, each with a name, a one-line description and a price: breads, pastries and a seasonal special."},
        {"id": "s4", "title": "Hours and contact", "kind": "writing", "depends_on": [],
         "instructions": "Write the opening hours, the address, a phone number and a two-sentence welcome."},
    ],
}

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Maple Street Bakery</title>
  <style>
    :root { --cream: #fbf4e8; --brown: #5a3a22; --accent: #c8702a; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Georgia, serif; background: var(--cream); color: var(--brown); line-height: 1.6; }
    header { text-align: center; padding: 4rem 1rem 3rem; background: var(--brown); color: var(--cream); }
    header h1 { margin: 0 0 .4rem; font-size: 2.6rem; }
    main { max-width: 42rem; margin: 0 auto; padding: 2rem 1rem; }
    h2 { color: var(--accent); border-bottom: 2px solid var(--accent); padding-bottom: .2rem; }
    .item { display: flex; justify-content: space-between; gap: 1rem; padding: .8rem 1rem; margin: .6rem 0; background: #fff; border-radius: 8px; }
    .item p { margin: 0; font-size: .95rem; opacity: .8; }
    .price { font-weight: bold; white-space: nowrap; }
    footer { text-align: center; padding: 2rem 1rem; font-size: .9rem; }
    @media (max-width: 480px) { header h1 { font-size: 2rem; } }
  </style>
</head>
<body>
  <header>
    <h1>Maple Street Bakery</h1>
    <p>Fresh bread and pastries, baked every morning.</p>
  </header>
  <main>
    <section id="menu">
      <h2>Menu</h2>
      <div class="item"><div><strong>Sourdough loaf</strong><p>Slow-risen, with a crisp crust.</p></div><span class="price">$7.00</span></div>
      <div class="item"><div><strong>Butter croissant</strong><p>Flaky, golden and still warm.</p></div><span class="price">$3.75</span></div>
      <div class="item"><div><strong>Cinnamon roll</strong><p>Brown sugar, cinnamon and cream cheese icing.</p></div><span class="price">$4.25</span></div>
      <div class="item"><div><strong>Seeded rye</strong><p>Dense, nutty and good with soup.</p></div><span class="price">$6.50</span></div>
      <div class="item"><div><strong>Almond tart</strong><p>Frangipane in a short pastry case.</p></div><span class="price">$4.50</span></div>
      <div class="item"><div><strong>Pumpkin loaf</strong><p>This month's special, with toasted pecans.</p></div><span class="price">$5.50</span></div>
    </section>
    <section id="hours">
      <h2>Opening hours</h2>
      <p>Tuesday to Saturday, 7 am to 4 pm. Sunday, 8 am to 1 pm. Closed Monday.</p>
    </section>
  </main>
  <footer>
    <p>12 Maple Street &middot; 555-0142 &middot; hello@maplestreetbakery.example</p>
  </footer>
</body>
</html>"""

PIECES = {
    "s1": "```html\n<header>\n  <h1>Maple Street Bakery</h1>\n  <p>Fresh bread and pastries, baked every morning.</p>\n</header>\n<main>\n  <section id=\"menu\"><h2>Menu</h2></section>\n  <section id=\"hours\"><h2>Opening hours</h2></section>\n</main>\n<footer><p>12 Maple Street</p></footer>\n```",
    "s2": "```css\n:root { --cream: #fbf4e8; --brown: #5a3a22; --accent: #c8702a; }\nbody { font-family: Georgia, serif; background: var(--cream); color: var(--brown); }\nheader { text-align: center; padding: 4rem 1rem 3rem; background: var(--brown); color: var(--cream); }\n.item { display: flex; justify-content: space-between; background: #fff; border-radius: 8px; }\n@media (max-width: 480px) { header h1 { font-size: 2rem; } }\n```",
    "s3": "- Sourdough loaf, slow-risen with a crisp crust, $7.00\n- Butter croissant, flaky, golden and still warm, $3.75\n- Cinnamon roll, with cream cheese icing, $4.25\n- Seeded rye, dense and nutty, $6.50\n- Almond tart, frangipane in a short pastry case, $4.50\n- Pumpkin loaf, this month's special, $5.50",
    "s4": "Welcome to Maple Street Bakery. We bake everything on the premises, every morning.\n\nOpen Tuesday to Saturday, 7 am to 4 pm, and Sunday, 8 am to 1 pm. Closed Monday.\n12 Maple Street, 555-0142.",
}

CHATS = [
    (("cpu", "gpu"), "A CPU has a few powerful cores that work through tasks one after another very quickly, which makes it good at general-purpose work. A GPU has thousands of smaller cores that do many simple calculations at the same time, which is why it is so much faster at graphics and at running AI models."),
    (("names", "bakery"), "Here are five ideas:\n\n1. **Maple Street Bakery**, plain and friendly\n2. **The Daily Crumb**, for a place with regulars\n3. **Rise & Shine Bread Co.**, for early mornings\n4. **Golden Hour Bakehouse**, warm and a little bit fancy\n5. **Flour & Folk**, community first\n\nIf you tell me the neighbourhood and what you bake best, I can narrow it down."),
    (("heat pump",), "A heat pump moves heat instead of making it. A refrigerant circulates between two coils: it picks up heat where it is cooler, gets compressed so it becomes hot, and gives that heat up where you want it. Because it only moves heat that already exists, it can deliver three or four units of warmth for every unit of electricity it uses. Run in reverse, the same machine cools a room."),
]


def job_of(body):
    sys_msg = next((m["content"] for m in body.get("messages", []) if m["role"] == "system"), "")
    for prefix, job in (("You are Hydra, the planner", "planner"), ("You are Hydra's reviewer", "reviewer"),
                        ("You are one worker in Chimera", "worker"), ("You are Hydra's final editor", "combine"),
                        ("You repair one script in Chimera", "mend"), ("You check a rendered picture", "look"),
                        ("You decide whether a request should be handled by a tool", "gate"),
                        ("You maintain the shared library", "library"), ("You check entries before", "library")):
        if sys_msg.startswith(prefix):
            return job
    return "options" if "format" in body else "chat"


def piece_for(user):
    text = user.lower()
    for sid, needle in (("s1", "html skeleton"), ("s2", "write the css"), ("s3", "six menu items"), ("s4", "opening hours")):
        if needle in text:
            return PIECES[sid]
    return "Done."


def reply(job, body, helper):
    user = "\n".join(m["content"] for m in body.get("messages", []) if m["role"] == "user")
    last = next((m["content"] for m in reversed(body.get("messages", [])) if m["role"] == "user"), "").lower()
    if job == "planner":
        return json.dumps(PLAN)
    if job == "reviewer":
        if helper:
            return json.dumps({"check": "1. Menu, hours and styling are all there: yes.", "done": True, "score": 90, "critique": ""})
        return json.dumps({"done": True, "score": 90, "critique": ""})
    if job == "worker":
        return piece_for(user)
    if job == "combine":
        return ("Here is the finished page. Save it as `index.html` and open it in a browser.\n\n```html\n" + PAGE +
                "\n```\n\nThe menu comes from step 3 and the hours and contact details from step 4. The styling from step 2 sits in one `<style>` block, so the whole site is a single file.")
    if job == "gate":
        return json.dumps({"use": False})
    if job == "options":
        return "{}"
    if job == "library":
        return json.dumps({"skip": True})
    for words, text in CHATS:
        if all(w in last for w in words):
            return text
    return "Happy to help. Could you tell me a little more about what you would like to do?"


def digest(name):
    return hashlib.sha256(name.encode()).hexdigest()


def show_of(m):
    arch = m["arch"]
    info = {"general.architecture": arch, "general.parameter_count": int(float(m["params"].rstrip("B")) * 1e9),
            arch + ".context_length": m["ctx"], arch + ".block_count": m["layers"],
            arch + ".attention.head_count": m["heads"], arch + ".attention.head_count_kv": m["kv"],
            arch + ".embedding_length": m["emb"]}
    return {"license": "", "modelfile": "FROM " + m["name"], "parameters": "", "template": "{{ .Prompt }}",
            "details": {"family": arch, "parameter_size": m["params"], "quantization_level": "Q4_K_M"},
            "model_info": info, "capabilities": m.get("caps", ["completion"])}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/api/version":
            return self.send({"version": "0.40.1"})
        if self.path == "/api/tags":
            return self.send({"models": [{"name": m["name"], "model": m["name"], "size": int(m["size_gb"] * 1e9),
                                          "digest": digest(m["name"]), "modified_at": "2026-11-02T10:00:00Z",
                                          "details": {"family": m["arch"], "parameter_size": m["params"], "quantization_level": "Q4_K_M"}}
                                         for m in MODELS]})
        if self.path == "/api/ps":
            return self.send({"models": [{"name": m["name"], "model": m["name"], "size": int(m["size_gb"] * 1e9)} for m in MODELS if m.get("loaded")]})
        self.send({"error": "not found"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/show":
            m = next((x for x in MODELS if x["name"] == body.get("model")), None)
            return self.send(show_of(m)) if m else self.send({"error": "model not found"}, 404)
        if self.path == "/api/chat":
            return self.chat(body)
        self.send({"error": "not found"}, 404)

    def chat(self, body):
        m = next((x for x in MODELS if x["name"] == body.get("model")), MODELS[0])
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        if not body.get("messages"):  # a load or unload request
            self.wfile.write((json.dumps({"model": m["name"], "done": True, "done_reason": "unload"}) + "\n").encode())
            return
        job = job_of(body)
        if job == "worker":
            time.sleep(STEP_SECONDS)
        text = reply(job, body, m["name"].startswith("hydra:"))
        step = 6
        for i in range(0, len(text), step):
            self.wfile.write((json.dumps({"model": m["name"], "message": {"role": "assistant", "content": text[i:i + step]}, "done": False}) + "\n").encode())
            self.wfile.flush()
            time.sleep(step / 4.0 / m["tps"] / 8)
        tokens = max(8, len(text) // 4)
        self.wfile.write((json.dumps({"model": m["name"], "message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop",
                                      "eval_count": tokens, "eval_duration": int(tokens / m["tps"] * 1e9),
                                      "prompt_eval_count": 120, "prompt_eval_duration": 90000000,
                                      "total_duration": int((tokens / m["tps"] + 0.3) * 1e9), "load_duration": 40000000}) + "\n").encode())


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
