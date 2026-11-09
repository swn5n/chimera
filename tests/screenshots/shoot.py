"""Takes the README screenshots from the made-up pool that stack.py is running (screenshots.py does both).
Usage: python3 shoot.py <outdir>
All names, hardware and text on screen are made up. Two things the real app would show are replaced before each
capture: this computer's LAN address and the invite code (with the examples the app's own join form uses), and
the real computer name that the first-run card prefills."""
import http.client, json, os, re, shutil, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Chrome

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = None  # set by run()
A, D = "http://127.0.0.1:18470/", "http://127.0.0.1:18473/"
W, SCALE = 1100, 1.5  # css pixels wide, and the pixel density of the saved PNGs
READY = "document.readyState === 'complete' && document.querySelector('#state-word') && document.querySelector('#state-word').textContent.length > 0"
GOAL = "Build a one-page website for a neighbourhood bakery: a header with its name, a menu with six items and prices, and the opening hours."
QUESTION = "What's the difference between a CPU and a GPU? Two sentences, please."

SCRUB = r"""(() => {
  const box = document.querySelector('#invite'); if (!box) return false;
  const fix = () => { const w = document.createTreeWalker(box, NodeFilter.SHOW_TEXT); const nodes = []; while (w.nextNode()) nodes.push(w.currentNode);
    for (const n of nodes) { const t = n.nodeValue; const u = t.replace(/\d{1,3}(\.\d{1,3}){3}:\d+/g, '192.168.1.20:7480').replace(/\b[A-Z0-9]{4}[-\u2010-\u2015][A-Z0-9]{4}\b/g, 'K7QM-4TXP'); if (u !== t) n.nodeValue = u; } };
  const watch = new MutationObserver(() => { watch.disconnect(); fix(); watch.observe(box, {childList: true, subtree: true, characterData: true}); });
  fix(); watch.observe(box, {childList: true, subtree: true, characterData: true}); return true; })()"""


def seed_chat(message):
    c = http.client.HTTPConnection("127.0.0.1", 18470, timeout=120)
    c.request("POST", "/api/chat", json.dumps({"message": message, "model": "", "session_id": ""}).encode(), {"X-Chimera": "1", "Content-Type": "application/json"})
    r = c.getresponse()
    while True:
        line = r.fp.readline()
        if not line or (line.startswith(b"data: ") and json.loads(line[6:]).get("type") in ("done", "error", "cancelled")):
            break


def open_view(c, view, size):
    c.resize(*size)
    c.goto(A, ready=READY)
    c.eval("document.fonts.ready.then(() => true)", wait=True)
    c.eval("document.querySelector('button.mode[data-view=%s]').click()" % view)
    time.sleep(1.5)


def type_and_send(c, text, long_task=False, device=None):
    c.eval("document.querySelector('#btn-new-chat').click()")
    time.sleep(0.8)
    # "Run on": one chosen computer, or Any device (a long task must not be pinned to one computer)
    c.eval("""(() => { const s = document.querySelector('#sel-device'); const want = %s; const o = want ? [...s.options].find(o => o.textContent.includes(want)) : s.options[0];
      s.value = o.value; s.dispatchEvent(new Event('change', {bubbles: true})); })()""" % json.dumps(device or ""))
    c.eval("""(() => { const ta = document.querySelector('#prompt'); ta.focus(); ta.value = %s; ta.dispatchEvent(new Event('input', {bubbles: true}));
      const t = document.querySelector('#chk-task'); if (%s && !t.checked) t.click(); })()""" % (json.dumps(text), "true" if long_task else "false"))
    time.sleep(0.4)
    c.eval("document.querySelector('#btn-send').click()")


def run(out):
    """Take the six screenshots into the folder `out`."""
    global OUT
    OUT = os.path.abspath(out)
    os.makedirs(OUT, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="chimera-shots-chrome-")
    c = Chrome(profile, size=(W, 960), scale=SCALE)
    try:
        # 1. Network
        open_view(c, "network", (1340, 930, 1.2))   # wide: keeps the two-column layout
        c.until("document.querySelectorAll('#rack > *').length >= 3 && document.querySelector('#rack').innerText.split('Lending').length >= 4", 40, "three lending computers")
        c.eval(SCRUB)
        time.sleep(1.2)
        shown = c.eval("document.querySelector('#invite').innerText")
        addresses = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}:\d+", shown)
        assert addresses == ["192.168.1.20:7480"], "the real address may still be on screen: " + shown
        c.shot(os.path.join(OUT, "network.png"))
        print("network ok")

        # 2. Models (the Tools block is left out: it lists what this real Mac happens to have installed)
        open_view(c, "models", (1340, 900, 1.2))
        c.until("document.querySelectorAll('#picks > *').length >= 5", 30, "the picks")
        c.eval("""(() => { const h = [...document.querySelectorAll('#view-models h2')].find(h => h.textContent.trim() === 'Tools');
          let el = h && h.parentElement; while (el) { const next = el.nextElementSibling; el.style.display = 'none'; el = next; } })()""")
        time.sleep(1)
        bottom = c.eval("(() => { const rows = document.querySelectorAll('#picks > *'); const r = rows[Math.min(8, rows.length - 1)].getBoundingClientRect(); return r.bottom + scrollY; })()")
        c.shot(os.path.join(OUT, "models.png"), clip=(0, 0, 1340, bottom + 5))  # ends cleanly under a row of the list
        print("models ok")

        # 3. ordinary chats: two through the API so the chat list looks used, then one in the UI, run on another computer
        for m in ("Explain how a heat pump works in plain words.", "Give me five names for a neighbourhood bakery."):
            seed_chat(m)
            time.sleep(1.1)
        open_view(c, "chat", (W, 700))
        type_and_send(c, QUESTION, device="Gaming PC")
        c.until("document.querySelector('#messages').innerText.includes('Rate this reply')", 60, "the reply")
        time.sleep(1.5)
        print("reply line:", c.eval("document.querySelector('#messages').innerText").replace("\n", " | ")[-260:])
        c.shot(os.path.join(OUT, "chat.png"))
        print("chat ok")

        # 4. a long task, as a person would start it
        c.resize(W, 820)
        type_and_send(c, GOAL, long_task=True)
        mid = ("(() => { const t = document.querySelector('#messages').innerText; return t.includes('Working') && (t.match(/\\bOn \\S/g) || []).length >= 3 && t.includes('tokens'); })()")
        try:
            c.until(mid, 40, "a mid-run frame with three computers")
            time.sleep(0.2)
            c.shot(os.path.join(OUT, "long-task.png"))
            print("long task (mid-run) ok")
        except RuntimeError as e:
            print("no mid-run frame:", e)
        c.until("document.querySelector('#messages').innerText.includes('finished page') && document.querySelector('#messages').innerText.includes('Rate this reply')", 120, "the finished task")
        time.sleep(1.5)
        c.resize(W, 1000)
        time.sleep(0.8)
        c.eval("(() => { const m = document.querySelector('#messages'); const card = m.querySelector('.msg.assistant.task') || m.children[1]; m.scrollTop += card.getBoundingClientRect().top - m.getBoundingClientRect().top - 14; })()")
        time.sleep(1)
        c.shot(os.path.join(OUT, "long-task-done.png"))
        print("long task (done) ok")

        # 5. the first-run card, on a fresh computer (its prefilled computer name is replaced)
        c.resize(W, 800)
        c.goto(D, ready=READY)
        c.until("!document.querySelector('#setup').hidden", 20, "the setup card")
        c.eval("""(() => { const o = document.querySelector('#su-owner'), d = document.querySelector('#su-device');
          o.value = 'Maya'; o.dispatchEvent(new Event('input', {bubbles: true})); d.value = "Maya's MacBook"; d.dispatchEvent(new Event('input', {bubbles: true})); })()""")
        time.sleep(1)
        r = c.eval("(() => { const b = document.querySelector('#setup .setup-card').getBoundingClientRect(); return [b.x, b.y, b.width, b.height]; })()")
        pad = 1
        c.shot(os.path.join(OUT, "setup.png"), clip=(r[0] - pad, r[1] - pad, r[2] + 2 * pad, r[3] + 2 * pad))
        print("setup ok", r)
    finally:
        c.close()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "out"))
