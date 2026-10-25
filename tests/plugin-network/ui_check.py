"""Drives Chimera's real interface in a headless browser: attach a picture in the chat, send it, and
check the plugin's picture shows in the reply. Usage: python3 ui_check.py <chimera binary> <workdir>"""
import http.client, json, os, shutil, signal, subprocess, sys, time
from playwright.sync_api import sync_playwright

BIN, WORK = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
HERE = os.path.dirname(os.path.abspath(__file__))
A_UI, B_UI, HUB, OLLAMA = 7581, 7582, 7590, 11565
procs = []


def api(port, method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.request(method, path, json.dumps(body).encode() if body is not None else None, {"X-Chimera": "1", "Content-Type": "application/json"})
    r = c.getresponse()
    return r.status, json.loads(r.read() or b"null")


def wait_for(fn, what, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit("timed out: " + what)


def start(args, extra, name):
    env = dict(os.environ, CHIMERA_NO_AUTOPOOL="1", CHIMERA_SYSINFO=os.path.join(WORK, "sysinfo.json"), **extra)
    procs.append(subprocess.Popen([BIN] + args, stdout=open(os.path.join(WORK, name + ".out"), "w"), stderr=subprocess.STDOUT, env=env, start_new_session=True))


shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)
json.dump({"os": "Linux", "os_version": "test", "arch": "amd64", "chip": "Test CPU", "ram_gb": 64, "cores": 8,
           "gpus": [{"name": "NVIDIA RTX test", "vram_gb": 24}]}, open(os.path.join(WORK, "sysinfo.json"), "w"))
shutil.copytree(os.path.join(HERE, "plugins_src", "demo-shadow"), os.path.join(WORK, "B", "plugins", "demo-shadow"))
try:
    procs.append(subprocess.Popen([sys.executable, os.path.join(HERE, "fake_ollama.py"), str(OLLAMA)], start_new_session=True))
    oll = "http://127.0.0.1:%d" % OLLAMA
    start(["--data-dir", os.path.join(WORK, "A"), "--ui-port", str(A_UI), "--hub-port", str(HUB), "--no-open", "--ollama", oll], {}, "A")
    start(["--data-dir", os.path.join(WORK, "B"), "--ui-port", str(B_UI), "--no-open", "--ollama", oll], {"IT_SECRET_FILE": "/nonexistent"}, "B")
    for p in (A_UI, B_UI):
        wait_for(lambda: api(p, "GET", "/api/state")[1]["ollama"]["status"] == "running", "ollama")
    api(A_UI, "POST", "/api/settings", {"auto_join": False, "setup_done": True})
    _, hv = api(A_UI, "POST", "/api/network/host", {"enabled": True, "owner": "Alice", "device_name": "Alice's laptop", "name": "Studio network"})
    api(B_UI, "POST", "/api/settings", {"setup_done": True})
    api(B_UI, "POST", "/api/network/join", {"address": "127.0.0.1:%d" % HUB, "invite": hv["invite"], "owner": "Andrews", "device_name": "Studio Mac"})
    wait_for(lambda: any(t["id"] == "plugin:demo-shadow" and t["have"] for t in api(B_UI, "GET", "/api/state")[1]["profile"]["tools"]), "plugin scan", 90)
    api(B_UI, "POST", "/api/connect")
    wait_for(lambda: any(d["name"] == "Studio Mac" and d["lending"] and d["profile"].get("plugins") for d in api(A_UI, "GET", "/api/state")[1]["network"]["devices"]), "B lending")

    with sync_playwright() as pw:
        br = pw.chromium.launch()
        page = br.new_page(viewport={"width": 1280, "height": 900})
        page.goto("http://127.0.0.1:%d/" % A_UI)
        page.wait_for_timeout(1500)
        page.screenshot(path=os.path.join(WORK, "ui_0_start.png"))
        # go to the chat
        btn = page.locator('button.mode[data-view="chat"]')
        if btn.count():
            btn.first.click()
        page.wait_for_timeout(800)
        page.set_input_files("#file-attach", os.path.join(HERE, "machine.png"))
        page.wait_for_selector("#attachments:not([hidden]) .attachment img", timeout=5000)
        page.fill("#prompt", "Put this on white with a soft studio shadow, light from the left")
        page.screenshot(path=os.path.join(WORK, "ui_1_attached.png"))
        page.click("#btn-send")
        page.wait_for_selector(".msg.assistant .files img", timeout=60000)
        page.wait_for_function("() => { const i = document.querySelector('.msg.assistant .files img'); return i && i.complete && i.naturalWidth > 0; }", timeout=15000)
        page.wait_for_timeout(800)
        page.screenshot(path=os.path.join(WORK, "ui_2_result.png"))
        info = page.evaluate("""() => { const i = document.querySelector('.msg.assistant .files img');
            const m = document.querySelector('.msg.assistant');
            return {w: i.naturalWidth, h: i.naturalHeight, src: i.getAttribute('src'), meta: m.querySelector('.meta').textContent,
                    note: m.querySelector('.note').textContent, body: m.querySelector('.body p') ? m.querySelector('.body p').textContent : '',
                    stars: m.querySelectorAll('.star').length, sent_img: !!document.querySelector('.msg.user .files img')}; }""")
        print(json.dumps(info, indent=1))
        # rate it 5 stars from the UI
        page.locator(".msg.assistant .star").nth(4).click()
        page.wait_for_selector(".msg.assistant .rate-note", timeout=5000)
        page.fill(".msg.assistant .rate-note input", "Clean edges, shadow sits under the wheels")
        page.click(".msg.assistant .rate-note button[type=submit]")
        page.wait_for_timeout(1500)
        page.screenshot(path=os.path.join(WORK, "ui_3_rated.png"))
        # B's settings: the plugins section
        pb = br.new_page(viewport={"width": 1280, "height": 1000})
        pb.goto("http://127.0.0.1:%d/" % B_UI)
        pb.wait_for_timeout(1200)
        sb = pb.locator('button.mode[data-view="settings"]')
        if sb.count():
            sb.first.click()
        pb.wait_for_timeout(800)
        sec = pb.locator("#settings-library")
        sec.scroll_into_view_if_needed()
        sec.screenshot(path=os.path.join(WORK, "ui_4_worker_settings.png"))
        # A's library: the plugin entry with its rating
        page.locator('button.mode[data-view="library"]').first.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=os.path.join(WORK, "ui_5_library.png"))
        br.close()
    lib = api(A_UI, "GET", "/api/library?q=shadow")[1]
    ent = next(e for e in lib["entries"] if e.get("plugin") == "demo-shadow")
    print("library entry:", json.dumps({k: ent.get(k) for k in ("status", "rated", "stars", "uses")}))
    ok = info["w"] == 256 and info["sent_img"] and info["stars"] == 5 and ent["rated"] == 1 and ent["stars"] == 5
    print("UI CHECK", "PASS" if ok else "FAIL")
finally:
    for p in reversed(procs):
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except Exception:
            pass
