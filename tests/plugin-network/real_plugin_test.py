"""A real plugin through a Chimera network on one computer, end to end.

Two Chimera 0.5.0 instances with their own data folders and ports (they never touch a Chimera you
already run): A hosts a closed network and asks; B joins it, has the plugins in PLUGINS_DIR, lends.
A sends a picture with a request, the hub routes the step to B, B runs the plugin in its sandbox, and
the file comes back to A's chat. A stub Ollama on port 11555 answers the option-choosing prompt.

Safety: A's pool is closed (auto_join off) so it never merges with, or is merged into, another pool on
the network, and B is always stopped before A (a worker that loses its hub for a minute looks for
another one). Ports 7571, 7572, 7580, 11555.

    CHIMERA_BIN=/path/to/chimera PLUGINS_DIR=~/Desktop/chimera-plugins \
      python3 real_plugin_test.py <picture> "<request>" <outdir>

Used on mac-lan on Oct 24, 2026 with the perspective-shadow plugin and the SkyTrak 3042 picture: 10 of 10.
"""
import base64
import http.client
import json
import os
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.expanduser(os.environ.get("CHIMERA_BIN") or os.path.join(HERE, "chimera"))
PIC, REQUEST, OUT = os.path.abspath(sys.argv[1]), sys.argv[2], os.path.abspath(sys.argv[3])
PLUGINS = os.path.expanduser(os.environ.get("PLUGINS_DIR") or "~/Desktop/chimera-plugins")
A_UI, B_UI, HUB, OLLAMA = 7571, 7572, 7580, 11555
procs = {}
results = []
T0 = time.time()


def log(*a):
    print("[%6.1fs]" % (time.time() - T0), *a, flush=True)


def check(name, ok, detail=""):
    results.append({"check": name, "ok": bool(ok), "detail": detail})
    log(("PASS " if ok else "FAIL ") + name + (": " + detail if detail else ""))


def api(port, method, path, body=None, timeout=30):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    c.request(method, path, json.dumps(body).encode() if body is not None else None,
              {"X-Chimera": "1", "Content-Type": "application/json"})
    r = c.getresponse()
    raw = r.read()
    try:
        return r.status, json.loads(raw or b"null")
    except ValueError:
        return r.status, raw


def wait_for(fn, what, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            v = fn()
            if v:
                return v
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    raise RuntimeError("timed out waiting for " + what)


def start(name, args, extra):
    env = {"HOME": os.path.expanduser("~"), "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
           "LANG": "en_US.UTF-8", "TMPDIR": os.environ.get("TMPDIR", "/tmp"), "CHIMERA_NO_AUTOPOOL": "1"}
    env.update(extra)
    f = open(os.path.join(OUT, name + ".out"), "w")
    procs[name] = subprocess.Popen(args, stdout=f, stderr=subprocess.STDOUT, env=env, start_new_session=True)


def stop_all():
    for name in ("B", "A", "ollama"):  # the worker first, always
        p = procs.get(name)
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
                p.wait(timeout=15)
            except Exception:  # noqa: BLE001
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except Exception:  # noqa: BLE001
                    pass


def watchdog():
    while True:
        time.sleep(1)
        a = procs.get("A")
        if a is not None and a.poll() is not None:
            b = procs.get("B")
            if b and b.poll() is None:
                os.killpg(b.pid, signal.SIGTERM)  # never leave the worker without its hub
            return


def main():
    os.makedirs(OUT, exist_ok=True)
    start("ollama", [sys.executable, os.path.join(HERE, "fake_ollama.py"), str(OLLAMA), os.path.join(OUT, "ollama_chats.jsonl")], {})
    oll = "http://127.0.0.1:%d" % OLLAMA
    start("A", [BIN, "--data-dir", os.path.join(OUT, "A"), "--ui-port", str(A_UI), "--hub-port", str(HUB), "--no-open", "--ollama", oll], {})
    threading.Thread(target=watchdog, daemon=True).start()
    wait_for(lambda: api(A_UI, "GET", "/api/ping")[0] == 200, "A")
    # A: a closed pool, before hosting
    st, _ = api(A_UI, "POST", "/api/settings", {"auto_join": False})
    st, hv = api(A_UI, "POST", "/api/network/host", {"enabled": True, "owner": "Requester", "device_name": "Requester (test)", "name": "Perspective test net"})
    s = api(A_UI, "GET", "/api/state")[1]
    check("A hosts a closed test network", st == 200 and hv.get("enabled") and not s["settings"].get("auto_join"), "port %s" % hv.get("port"))

    start("B", [BIN, "--data-dir", os.path.join(OUT, "B"), "--ui-port", str(B_UI), "--no-open", "--ollama", oll], {"CHIMERA_PLUGINS": PLUGINS})
    wait_for(lambda: api(B_UI, "GET", "/api/ping")[0] == 200, "B")
    for port in (A_UI, B_UI):
        wait_for(lambda: api(port, "GET", "/api/state")[1]["ollama"]["status"] == "running", "Ollama seen as running", 40)
    st, out = api(B_UI, "POST", "/api/network/join", {"address": "127.0.0.1:%d" % HUB, "invite": hv["invite"], "owner": "Worker", "device_name": "This Mac (worker)"})
    check("B joins", st == 200, str(out))
    tool = wait_for(lambda: next((t for t in api(B_UI, "GET", "/api/state")[1]["profile"]["tools"] if t["id"] == "plugin:perspective-shadow" and t["have"]), None),
                    "B's plugin scan", 150)
    check("B found the perspective-shadow plugin", tool, json.dumps(tool))  # change the id for another plugin
    st, out = api(B_UI, "POST", "/api/connect")
    check("B lends", st == 200, str(out)[:200])
    wait_for(lambda: any(d["name"] == "This Mac (worker)" and d["lending"] and d["profile"].get("plugins")
                         for d in api(A_UI, "GET", "/api/state")[1]["network"]["devices"]), "B lending with plugins", 60)

    # A asks: a picture and a request
    with open(PIC, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    body = {"message": REQUEST, "images": [{"name": os.path.basename(PIC), "data": data}]}
    c = http.client.HTTPConnection("127.0.0.1", A_UI, timeout=1900)
    c.request("POST", "/api/chat", json.dumps(body).encode(), {"X-Chimera": "1", "Content-Type": "application/json"})
    r = c.getresponse()
    evs, last = [], ""
    while True:
        line = r.fp.readline()
        if not line:
            break
        line = line.decode().strip()
        if not line.startswith("data: "):
            continue
        ev = json.loads(line[6:])
        evs.append(ev)
        if ev["type"] == "status":
            msg = "%s (%d%%)" % (ev.get("reason"), round(100 * (ev.get("fraction") or 0)))
            if msg != last:
                log("  status:", msg)
                last = msg
        elif ev["type"] != "delta":
            log("  event:", json.dumps({k: v for k, v in ev.items() if k not in ("gen_id",)})[:300])
        if ev["type"] in ("done", "error", "cancelled"):
            break
    files = [e["file"] for e in evs if e["type"] == "file"]
    assigned = next((e for e in evs if e["type"] == "assigned"), {})
    sid = next((e.get("session_id") for e in evs if e["type"] == "started"), None)
    content = "".join(e.get("content", "") for e in evs if e["type"] == "delta")
    check("the plugin step ran on B", assigned.get("device_name") == "This Mac (worker)" and not assigned.get("local"), json.dumps(assigned))
    check("the step finished", evs and evs[-1]["type"] == "done", json.dumps(evs[-1]) if evs else "no events")
    check("a PNG came back", files and files[0]["mime"] == "image/png", json.dumps(files))
    log("summary:", content)
    if files:
        c = http.client.HTTPConnection("127.0.0.1", A_UI, timeout=30)
        c.request("GET", "/api/files/%s/%s" % (sid, files[0]["id"]))
        rr = c.getresponse()
        png = rr.read()
        with open(os.path.join(OUT, "result_" + files[0]["name"]), "wb") as f:
            f.write(png)
        check("A's app serves the returned picture", rr.status == 200 and png[:8] == b"\x89PNG\r\n\x1a\n", "%d bytes" % len(png))
        st, out = api(A_UI, "POST", "/api/feedback", {"session_id": sid, "index": 1, "rating": 5, "send": True})
        lib = api(A_UI, "GET", "/api/library?q=shadow&limit=20")[1]
        ent = next((e for e in lib.get("entries", []) if e.get("plugin") == "perspective-shadow"), {})
        check("a 5-star rating lands on the plugin", ent.get("rated") == 1 and ent.get("stars") == 5 and ent.get("status") == "verified",
              json.dumps({k: ent.get(k) for k in ("status", "rated", "stars", "uses", "version")}))
    blog = open(os.path.join(OUT, "B", "chimera.log")).read()
    lines = [l for l in blog.splitlines() if "plugin" in l]
    check("B ran it sandboxed", any("sandboxed: no network" in l for l in lines), lines[-1] if lines else "")


try:
    main()
except Exception as e:  # noqa: BLE001
    check("ran to the end", False, repr(e))
finally:
    stop_all()
    n = sum(r["ok"] for r in results)
    log("%d of %d checks passed" % (n, len(results)))
    json.dump(results, open(os.path.join(OUT, "report.json"), "w"), indent=1)
    sys.exit(0 if results and n == len(results) else 1)
