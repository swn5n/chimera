"""Words-only Heads, end to end: a host/asker (A) and a worker (B) with the demo-poster Head, two real
Chimera processes and the fake Ollama (which answers the Head gate). Checks that a request to MAKE
something routes to the Head and a picture comes back, that a QUESTION stays a normal chat, that a
hand-picked model is respected, that a "network": "localhost" Head reaches a local server from inside
its sandbox, and that the Head's owner earns the run bonus and the star bonus.
Usage: python3 heads_text_test.py <chimera binary> <workdir>"""
import json, os, shutil, subprocess, sys, time, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_it as it  # reuse its helpers (api, chat, wait_for, start, check)

BIN, WORK = it.BIN, it.WORK
HERE = it.HERE
A_UI, B_UI, HUB, OLLAMA, LOCAL = 7591, 7592, 7595, 11575, 7596

class Hello(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        b = b"hello from the local server"
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

def balances(port):
    return {k.lower(): v for k, v in api(port, "GET", "/api/state")[1]["network"]["balances"].items()}

api, chat, wait_for, start, check = it.api, it.chat, it.wait_for, it.start, it.check

def main():
    shutil.rmtree(WORK, ignore_errors=True); os.makedirs(WORK)
    json.dump({"os": "Linux", "os_version": "test", "arch": "amd64", "chip": "Test CPU", "ram_gb": 64, "cores": 8,
               "gpus": [{"name": "NVIDIA RTX test", "vram_gb": 24}]}, open(os.path.join(WORK, "sysinfo.json"), "w"))
    shutil.copytree(os.path.join(HERE, "plugins_src", "demo-poster"), os.path.join(WORK, "B", "plugins", "demo-poster"))
    srv = HTTPServer(("127.0.0.1", LOCAL), Hello); threading.Thread(target=srv.serve_forever, daemon=True).start()
    it.procs.append(subprocess.Popen([sys.executable, os.path.join(HERE, "fake_ollama.py"), str(OLLAMA),
                                      os.path.join(WORK, "ollama_chats.jsonl")], start_new_session=True))
    oll = "http://127.0.0.1:%d" % OLLAMA
    start("A", ["--data-dir", os.path.join(WORK, "A"), "--ui-port", str(A_UI), "--hub-port", str(HUB), "--no-open", "--ollama", oll], {})
    start("B", ["--data-dir", os.path.join(WORK, "B"), "--ui-port", str(B_UI), "--no-open", "--ollama", oll], {"DEMO_LOCAL_PORT": str(LOCAL)})
    wait_for(lambda: api(A_UI, "GET", "/api/ping")[0] == 200, "A")
    wait_for(lambda: api(B_UI, "GET", "/api/ping")[0] == 200, "B")
    for port in (A_UI, B_UI):
        wait_for(lambda: api(port, "GET", "/api/state")[1]["ollama"]["status"] == "running", "Ollama seen as running", 30)
    api(A_UI, "POST", "/api/settings", {"auto_join": False})
    st, hv = api(A_UI, "POST", "/api/network/host", {"enabled": True, "owner": "Alice", "device_name": "Host laptop", "name": "Heads net"})
    check("A hosts", st == 200 and hv.get("enabled"))
    st, out = api(B_UI, "POST", "/api/network/join", {"address": "127.0.0.1:%d" % HUB, "invite": hv["invite"], "owner": "Bob", "device_name": "Nvidia PC"})
    check("B joins", st == 200, str(out))
    wait_for(lambda: any(t["id"] == "plugin:demo-poster" and t["have"] for t in api(B_UI, "GET", "/api/state")[1]["profile"]["tools"]), "B's Head scan", 90)
    api(B_UI, "POST", "/api/connect")
    wait_for(lambda: any(d["name"] == "Nvidia PC" and d["online"] and d["lending"] and d["profile"].get("plugins")
                         for d in api(A_UI, "GET", "/api/state")[1]["network"]["devices"]), "B lending with its Head", 60)
    before = balances(A_UI)

    # 1. words only, asking to MAKE something -> the Head runs on B, a picture comes back
    evs = chat(A_UI, {"message": "make me a red poster please", "model": ""})
    kinds = [e["type"] for e in evs]
    plug = next((e for e in evs if e["type"] == "plugin"), None)
    check("1. a request to make something routes to the Head", plug and plug["plugin"] == "demo-poster", json.dumps(plug))
    asg = next((e for e in evs if e["type"] == "assigned"), None)
    check("1. it runs on the worker", asg and asg.get("device_name") == "Nvidia PC", json.dumps(asg))
    files = [e["file"] for e in evs if e["type"] == "file"]
    check("1. a picture comes back", files and files[0]["mime"] == "image/png" and files[0]["name"] == "poster_red.png", json.dumps(files))
    summary = "".join(e.get("content", "") for e in evs if e["type"] == "delta")
    check("1. options came from the words (red)", "a red card" in summary, summary)
    check("1. localhost Head reached its local server inside the sandbox", "Local server: reached (hello from the local server)" in summary, summary)
    check("1. no input picture was needed", "Input picture: none" in summary, summary)
    check("1. finished", kinds[-1] == "done", json.dumps(evs[-1]))
    gen_id = evs[-1].get("gen_id")
    step = next((e.get("step_id") for e in evs if e.get("step_id")), None)

    # 2. a QUESTION about posters stays an ordinary chat (the gate says no)
    evs = chat(A_UI, {"message": "what is a poster?", "model": ""})
    check("2. a question is answered by a model, not the Head", not any(e["type"] == "plugin" for e in evs)
          and "Hello from the fake model" in "".join(e.get("content", "") for e in evs if e["type"] == "delta"), json.dumps([e["type"] for e in evs]))

    # 3. a hand-picked model is respected even for a 'make' request
    evs = chat(A_UI, {"message": "make me a blue poster", "model": "fake-llm:8b"})
    check("3. an explicitly chosen model is used instead of a Head", not any(e["type"] == "plugin" for e in evs), json.dumps([e["type"] for e in evs]))

    # 4. the gate really was asked (a structured call mentioning the tool decision)
    log = [json.loads(l) for l in open(os.path.join(WORK, "ollama_chats.jsonl"))]
    gate_calls = [l for l in log if l["format"] and "should this tool handle" in l["last"].lower()]
    check("4. the fastest model was asked whether the Head should handle it", len(gate_calls) >= 2, "%d gate calls" % len(gate_calls))

    # 5. credits: whatever Alice paid Bob for model steps (the gate, the options) moved between them; on top
    #    of that the network minted Bob the Head's run bonus (0.1 for a run too quick to charge by time)
    time.sleep(4)  # the balance snapshot refreshes with the heartbeat
    mid = balances(A_UI)
    bob_gain = round(mid.get("bob", 0) - before.get("bob", 0), 2)
    alice_paid = round(before.get("alice", 0) - mid.get("alice", 0), 2)
    minted = round(bob_gain - alice_paid, 2)
    check("5. the Head's owner earned the run bonus from the network on top of what the asker paid", minted == 0.1,
          "Bob +%s, Alice -%s, minted %s" % (bob_gain, alice_paid, minted))

    # 6. a 5-star rating by someone else pays the star bonus to the Head's owner
    sid, idx = None, None
    for summ in api(A_UI, "GET", "/api/sessions")[1]:
        full = api(A_UI, "GET", "/api/sessions/%s" % summ["id"])[1]
        msgs = full.get("messages", full)
        for i, m in enumerate(msgs):
            if m.get("plugin") == "demo-poster":
                sid, idx = summ["id"], i
    check("6. the Head's reply is saved with its chat", sid is not None, str(sid))
    st, out = api(A_UI, "POST", "/api/feedback", {"session_id": sid, "index": idx, "rating": 5, "note": "great card", "send": True})
    time.sleep(4)
    after = balances(A_UI)
    minted2 = round((after.get("bob", 0) - mid.get("bob", 0)) - (mid.get("alice", 0) - after.get("alice", 0)), 2)
    check("6. a 5-star rating from someone else pays the Head's owner the star bonus", st == 200 and minted2 == 1.0, "feedback %s %s; minted %s" % (st, out, minted2))

    ok = all(r["ok"] for r in it.results)
    print("\n%d of %d checks passed" % (sum(r["ok"] for r in it.results), len(it.results)))
    return 0 if ok else 1

if __name__ == "__main__":
    try:
        code = main()
    finally:
        for p in reversed(it.procs):
            try: os.killpg(os.getpgid(p.pid), 15)
            except Exception: pass
        time.sleep(1)
    sys.exit(code)
