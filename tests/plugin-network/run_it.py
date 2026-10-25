"""End-to-end test of Chimera plugins: a host/requester (A) and a worker with plugins (B), as two
real Chimera processes with a fake Ollama. Safe beside a running Chimera: its own ports and data
folders, a closed pool, and the worker stopped before the hub.
Usage: python3 run_it.py <chimera binary> <workdir>"""
import base64, http.client, json, os, shutil, signal, subprocess, sys, time, threading

BIN, WORK = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
HERE = os.path.dirname(os.path.abspath(__file__))
A_UI, B_UI, HUB, OLLAMA, OLLAMA_A = 7571, 7572, 7580, 11555, 11556
SECRET = os.path.join(os.path.expanduser("~"), "chimera-it-secret.txt")
results, procs = [], []


def check(name, ok, detail=""):
    results.append({"check": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + (": " + detail if detail else ""), flush=True)


def api(port, method, path, body=None, timeout=30):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    data = json.dumps(body).encode() if body is not None else None
    c.request(method, path, data, {"X-Chimera": "1", "Content-Type": "application/json"})
    r = c.getresponse()
    raw = r.read()
    try:
        return r.status, json.loads(raw or b"null")
    except ValueError:
        return r.status, raw


def chat(port, body, on_event=None, timeout=300):
    """POST /api/chat and read its event stream to the end. Returns all events."""
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    c.request("POST", "/api/chat", json.dumps(body).encode(), {"X-Chimera": "1", "Content-Type": "application/json"})
    r = c.getresponse()
    if r.status != 200:
        return [{"type": "http_error", "status": r.status, "body": r.read().decode()}]
    events = []
    while True:
        line = r.fp.readline()
        if not line:
            break
        line = line.decode().strip()
        if not line.startswith("data: "):
            continue
        ev = json.loads(line[6:])
        events.append(ev)
        if on_event:
            on_event(ev)
        if ev["type"] in ("done", "error", "cancelled"):
            break
    return events


def wait_for(fn, what, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            v = fn()
            if v:
                return v
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit("timed out waiting for " + what)


def start(name, args, env_extra):
    env = dict(os.environ, CHIMERA_NO_AUTOPOOL="1", CHIMERA_SYSINFO=os.path.join(WORK, "sysinfo.json"), **env_extra)
    log = open(os.path.join(WORK, name + ".out"), "w")
    p = subprocess.Popen([BIN] + args, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
    procs.append(p)
    return p


def ollama_calls(log):
    """The chat calls a fake Ollama has answered so far (its log in WORK)."""
    try:
        return [json.loads(l) for l in open(os.path.join(WORK, log))]
    except FileNotFoundError:
        return []


def image_body(text, name="machine.png"):
    data = base64.b64encode(open(os.path.join(HERE, "machine.png"), "rb").read()).decode()
    return {"message": text, "images": [{"name": name, "data": data}]}


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    json.dump({"os": "Linux", "os_version": "test", "arch": "amd64", "chip": "Test CPU", "ram_gb": 64, "cores": 8,
               "gpus": [{"name": "NVIDIA RTX test", "vram_gb": 24}]}, open(os.path.join(WORK, "sysinfo.json"), "w"))
    with open(SECRET, "w") as f:
        f.write("this must never be readable from a plugin\n")
    # B has the plugins; A has none, so plugin steps must cross the network.
    for pid in ("demo-shadow", "demo-shadow-b"):
        shutil.copytree(os.path.join(HERE, "plugins_src", pid), os.path.join(WORK, "B", "plugins", pid))
    procs.append(subprocess.Popen([sys.executable, os.path.join(HERE, "fake_ollama.py"), str(OLLAMA),
                                   os.path.join(WORK, "ollama_chats.jsonl")], start_new_session=True))
    # A (the asker) has an Ollama of its own, so the test can tell whether Head work ever touches it; its
    # model is already loaded, so for "the fastest model" the hub would pick A over B
    procs.append(subprocess.Popen([sys.executable, os.path.join(HERE, "fake_ollama.py"), str(OLLAMA_A),
                                   os.path.join(WORK, "ollama_chats_A.jsonl"), "--loaded"], start_new_session=True))
    oll = "http://127.0.0.1:%d" % OLLAMA
    start("A", ["--data-dir", os.path.join(WORK, "A"), "--ui-port", str(A_UI), "--hub-port", str(HUB), "--no-open",
                "--ollama", "http://127.0.0.1:%d" % OLLAMA_A], {})
    start("B", ["--data-dir", os.path.join(WORK, "B"), "--ui-port", str(B_UI), "--no-open", "--ollama", oll], {"IT_SECRET_FILE": SECRET,
        # the demo plugins' probes ask to read the folder above B's data folder, and the data folder
        # itself: config.json must stay hidden
        "DEMO_READ": os.pathsep.join([WORK, os.path.join(WORK, "B")])})
    wait_for(lambda: api(A_UI, "GET", "/api/ping")[0] == 200, "A")
    wait_for(lambda: api(B_UI, "GET", "/api/ping")[0] == 200, "B")
    for port in (A_UI, B_UI):  # the fake Ollama may come up after the apps' first check; lending needs its model listed
        wait_for(lambda: api(port, "GET", "/api/state")[1]["ollama"]["status"] == "running", "Ollama seen as running", 30)
        wait_for(lambda: api(port, "GET", "/api/state")[1]["ollama"].get("models"), "the fake model listed", 30)

    # ---- network: A hosts a closed pool (never merges with a real one nearby), B joins and lends ----
    api(A_UI, "POST", "/api/settings", {"auto_join": False})
    st, hv = api(A_UI, "POST", "/api/network/host", {"enabled": True, "owner": "Alice", "device_name": "Host laptop", "name": "IT net"})
    check("A hosts a network", st == 200 and hv.get("enabled"), str(hv)[:200])
    st, out = api(B_UI, "POST", "/api/network/join", {"address": "127.0.0.1:%d" % HUB, "invite": hv["invite"], "owner": "Bob", "device_name": "Studio Mac"})
    check("B joins", st == 200, str(out))
    wait_for(lambda: any(t["id"] == "plugin:demo-shadow" and t["have"] for t in api(B_UI, "GET", "/api/state")[1]["profile"]["tools"]), "B's plugin scan", 90)
    tools = {t["id"]: t for t in api(B_UI, "GET", "/api/state")[1]["profile"]["tools"]}
    check("B's tools list its plugins", tools.get("plugin:demo-shadow", {}).get("have") and tools.get("plugin:demo-shadow-b", {}).get("have"),
          json.dumps({k: v for k, v in tools.items() if k.startswith("plugin:")})[:300])
    st, out = api(B_UI, "POST", "/api/connect")
    check("B starts lending", st == 200, str(out)[:200])

    def b_ready():
        devs = api(A_UI, "GET", "/api/state")[1]["network"]["devices"]
        return any(d["name"] == "Studio Mac" and d["online"] and d["lending"] and d["profile"].get("plugins") for d in devs)
    wait_for(b_ready, "B lending with plugins", 60)
    # A lends its own model too, like a laptop that's connected: the hub could pick it as the fastest
    st, out = api(A_UI, "POST", "/api/connect")
    check("A lends its own model too", st == 200, str(out)[:200])
    wait_for(lambda: any(d["name"] == "Host laptop" and d["online"] and d["lending"]
                         for d in api(A_UI, "GET", "/api/state")[1]["network"]["devices"]), "A lending", 60)
    a_before = len(ollama_calls("ollama_chats_A.jsonl"))

    # ---- 1: a picture with a request runs the best plugin on B, and the picture comes back ----
    t0 = time.time()
    evs = chat(A_UI, image_body("add a soft studio shadow with the light from the left"))
    types = [e["type"] for e in evs]
    plugin_ev = next((e for e in evs if e["type"] == "plugin"), {})
    assigned = next((e for e in evs if e["type"] == "assigned"), {})
    files = [e["file"] for e in evs if e["type"] == "file"]
    done = evs[-1]
    content = "".join(e.get("content", "") for e in evs if e["type"] == "delta")
    sid = next((e.get("session_id") for e in evs if e["type"] == "started"), None)
    check("1. request picks the relevant plugin", plugin_ev.get("plugin") == "demo-shadow", json.dumps(plugin_ev))
    check("1. it runs on the worker (B), not the requester", assigned.get("device_name") == "Studio Mac" and not assigned.get("local"), json.dumps(assigned))
    check("1. the picture comes back", len(files) == 1 and files[0]["mime"] == "image/png" and files[0]["width"] == 256, json.dumps(files))
    check("1. finished", done["type"] == "done", json.dumps(done))
    notes = [e.get("reason", "") for e in evs if e["type"] == "note"]
    check("1. options came from the request (model, structured output)", "left light" in content and any("style left" in n for n in notes),
          content + " | " + " / ".join(notes))
    check("1. sandbox: home folder hidden, data folder hidden (even inside a folder the plugin reads), no network",
          "home folder hidden" in content and "data folder hidden" in content and "network blocked" in content, content)
    check("1. credits charged for the worker's time", done.get("credits", 0) >= 0 and not done.get("local"), json.dumps(done))
    sess = api(A_UI, "GET", "/api/sessions/" + sid)[1]
    reply = sess["messages"][1]
    check("1. saved with the chat", reply.get("plugin") == "demo-shadow" and len(reply.get("files", [])) == 1 and len(sess["messages"][0].get("files", [])) == 1,
          json.dumps({k: reply.get(k) for k in ("plugin", "files", "model", "device")})[:300])
    c = http.client.HTTPConnection("127.0.0.1", A_UI, timeout=10)
    c.request("GET", "/api/files/%s/%s" % (sid, reply["files"][0]["id"]))
    r = c.getresponse()
    png = r.read()
    check("1. the local app serves the picture", r.status == 200 and png[:8] == b"\x89PNG\r\n\x1a\n" and r.getheader("Content-Type") == "image/png",
          "%d bytes, %s" % (len(png), r.getheader("Content-Type")))
    with open(os.path.join(WORK, "result_1.png"), "wb") as f:
        f.write(png)
    print("   took %.1fs" % (time.time() - t0))

    # ---- 2: one star for that plugin ----
    st, out = api(A_UI, "POST", "/api/feedback", {"session_id": sid, "index": 1, "rating": 1, "send": True})
    check("2. rating sent", st == 200 and out.get("sent"), json.dumps(out))
    lib = api(A_UI, "GET", "/api/library?q=shadow&limit=50")[1]
    ent = {e.get("plugin"): e for e in lib.get("entries", []) if e.get("kind") == "plugin"}
    check("2. the stars landed on the plugin's library entry", ent.get("demo-shadow", {}).get("rated") == 1 and ent["demo-shadow"].get("stars") == 1,
          json.dumps({k: {f: v.get(f) for f in ("status", "rated", "stars", "uses", "version")} for k, v in ent.items()}))
    check("2. the plugin was verified by its first run", ent.get("demo-shadow", {}).get("status") == "verified", ent.get("demo-shadow", {}).get("status"))

    # ---- 3: the rating now decides between the two relevant plugins ----
    evs = chat(A_UI, dict(image_body("add a soft studio shadow"), session_id=sid))
    plugin_ev = next((e for e in evs if e["type"] == "plugin"), {})
    check("3. the better-rated relevant plugin is picked", plugin_ev.get("plugin") == "demo-shadow-b" and evs[-1]["type"] == "done",
          json.dumps(plugin_ev) + " / " + " ".join(e.get("reason", "") for e in evs if e["type"] == "note"))

    # ---- 4: an out-of-range option from the model is clamped ----
    evs = chat(A_UI, image_body("a soft studio shadow but huge darkness"))
    content = "".join(e.get("content", "") for e in evs if e["type"] == "delta")
    check("4. out-of-range options are clamped to the schema", "darkness 1.00" in content, content)
    a_calls = ollama_calls("ollama_chats_A.jsonl")[a_before:]
    check("4. the asker's own Ollama stayed idle: the worker read every Head job's options", not a_calls,
          "%d call(s) on A: %s" % (len(a_calls), [c["last"][-60:] for c in a_calls]))

    # ---- 5: cancelling stops the plugin on the worker ----
    gen = {"status": []}
    def on_ev(e):
        if e["type"] == "started":
            gen["id"] = e["gen_id"]
        if e["type"] == "status":
            gen["status"].append((e.get("reason"), e.get("fraction")))
        if e["type"] == "status" and "slowly" in e.get("reason", "") and not gen.get("cancelled"):
            gen["cancelled"] = True
            threading.Thread(target=lambda: api(A_UI, "POST", "/api/chat/%s/cancel" % gen["id"])).start()
    evs = chat(A_UI, image_body("a soft studio shadow, do it slowly"), on_ev)
    check("5. the plugin's progress streams back while it runs", any(f and f > 0 for _, f in gen["status"]), str(gen["status"][:4]))
    check("5. a cancelled plugin step ends as cancelled", evs[-1]["type"] == "cancelled", json.dumps(evs[-1]))
    def no_plugin_process():
        out = subprocess.run(["pgrep", "-f", "plugins/demo-shadow"], capture_output=True, text=True).stdout.strip()
        return out == ""
    gone = False
    try:
        gone = wait_for(no_plugin_process, "the plugin process to stop", 30)
    except SystemExit:
        pass
    check("5. the plugin's process stopped on the worker", gone)

    # ---- 6: nothing fits ----
    evs = chat(A_UI, image_body("translate the label into French"))
    check("6. a request no plugin fits gets a clear answer", evs[-1]["type"] == "error" and "No Head" in evs[-1].get("error", ""), json.dumps(evs[-1]))

    # ---- 7: the worker's owner turns lending plugins off ----
    api(B_UI, "POST", "/api/settings", {"lend_plugins": False})
    def off():
        devs = api(A_UI, "GET", "/api/state")[1]["network"]["devices"]
        tools = [t for d in devs if d["name"] == "Studio Mac" for t in d["profile"]["tools"] if t["id"].startswith("plugin:")]
        return tools and not any(t["lendable"] for t in tools)
    wait_for(off, "B's plugins to stop being lent", 30)
    time.sleep(4)
    evs = chat(A_UI, image_body("add a soft studio shadow"))
    check("7. plugins aren't lent when the owner says no", evs[-1]["type"] == "error", json.dumps(evs[-1]))
    api(B_UI, "POST", "/api/settings", {"lend_plugins": True})

    # ---- 8: hub log shows sandboxing ----
    blog = open(os.path.join(WORK, "B", "chimera.log")).read()
    check("8. the worker ran plugins sandboxed, refusing to let them read its data folder",
          "sandboxed: no network, home folder hidden" in blog and "(inside Chimera's data folder)" in blog,
          [l for l in blog.splitlines() if "plugin" in l][-1] if "plugin" in blog else "no plugin lines")
    chats = [json.loads(l) for l in open(os.path.join(WORK, "ollama_chats.jsonl"))]
    check("8. the options step used structured output", any(c["format"] for c in chats), "%d chat calls" % len(chats))


if __name__ == "__main__":
    try:
        main()
    finally:
        for p in reversed(procs):  # the worker before the hub: a worker without its hub looks for another
            try:
                os.killpg(p.pid, signal.SIGTERM)
                p.wait(timeout=15)  # gone before another test takes the same ports
            except Exception:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except Exception:
                    pass
        try:
            os.remove(SECRET)
        except OSError:
            pass
        passed = sum(r["ok"] for r in results)
        print("\n%d of %d checks passed" % (passed, len(results)))
        json.dump(results, open(os.path.join(WORK, "report.json"), "w"), indent=1)
        sys.exit(0 if results and passed == len(results) else 1)
