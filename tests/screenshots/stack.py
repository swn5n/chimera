"""Brings up a small made-up Chimera pool for documentation screenshots: three computers (A hosts, B and C
join) with different owners, names, hardware and models, each with its own fake Ollama, plus a fourth,
fresh computer (D) for the first-run screen. Everything uses its own ports, data folders and HOME, the pool
is closed (it never merges with a real one nearby), and on the way out the workers stop before the host.
Used by screenshots.py (up() and down()). On its own, `python3 stack.py <chimera binary> <empty or new workdir>` keeps
the pool up until <workdir>/STOP exists, or Ctrl-C or SIGTERM, so a person can look around in it. Ports: the four
computers' interfaces on 18470 to 18473, the hub on 18480, their fake Ollamas on 18434 to 18437."""
import http.client, json, os, signal, subprocess, sys, time

BIN = WORK = STOP = None  # set by up()
HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(HERE, "fake_ollama_shots.py")
HUB = 18480
procs = []  # (label, Popen), in start order

MODELS = {
    "qwen3:32b": dict(size_gb=20.2, params="32.8B", arch="qwen3", layers=64, heads=64, kv=8, emb=5120, ctx=40960, tps=24, caps=["completion", "tools", "thinking"]),
    "gpt-oss:20b": dict(size_gb=13.8, params="20.9B", arch="gptoss", layers=24, heads=64, kv=8, emb=2880, ctx=131072, tps=62, caps=["completion", "tools", "thinking"]),
    "qwen3:14b": dict(size_gb=9.3, params="14.8B", arch="qwen3", layers=40, heads=40, kv=8, emb=5120, ctx=40960, tps=48, caps=["completion", "tools", "thinking"]),
    "gemma3:12b": dict(size_gb=8.1, params="12.2B", arch="gemma3", layers=48, heads=16, kv=8, emb=3840, ctx=131072, tps=34, caps=["completion", "vision"]),
    "llama3.2:3b": dict(size_gb=2.0, params="3.2B", arch="llama", layers=28, heads=24, kv=8, emb=3072, ctx=131072, tps=95, caps=["completion", "tools"]),
    "hydra:1.0": dict(size_gb=2.9, params="4.0B", arch="qwen3", layers=36, heads=32, kv=8, emb=2560, ctx=262144, tps=110, caps=["completion"]),
}
MAC_M4PRO = {"os": "macOS", "os_version": "15.6", "arch": "arm64", "chip": "Apple M4 Pro", "ram_gb": 24, "cores": 12, "gpus": [{"name": "16-core GPU", "vram_gb": 24}]}
DEVICES = [
    dict(key="A", owner="Maya", name="Maya's MacBook", ui=18470, ollama=18434, step_seconds=5,
         sysinfo={"os": "macOS", "os_version": "15.6", "arch": "arm64", "chip": "Apple M4 Max", "ram_gb": 64, "cores": 16, "gpus": [{"name": "40-core GPU", "vram_gb": 64}]},
         models=[("qwen3:32b", True), ("gpt-oss:20b", False), ("hydra:1.0", False), ("llama3.2:3b", False)]),
    dict(key="B", owner="Leo", name="Gaming PC", ui=18471, ollama=18435, step_seconds=3,
         sysinfo={"os": "Windows", "os_version": "Windows 11 Pro", "arch": "amd64", "chip": "Intel(R) Core(TM) i9-13900K", "ram_gb": 64, "cores": 24,
                  "gpus": [{"name": "NVIDIA GeForce RTX 4090", "vram_gb": 24}]},
         models=[("qwen3:14b", True), ("gemma3:12b", False)]),
    dict(key="C", owner="Priya", name="Mac mini", ui=18472, ollama=18436, step_seconds=6, sysinfo=MAC_M4PRO,
         models=[("gemma3:12b", True), ("llama3.2:3b", False)]),
    dict(key="D", owner="", name="", ui=18473, ollama=18437, step_seconds=1, sysinfo=MAC_M4PRO, models=[("gemma3:12b", True)]),
]


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
    raise RuntimeError("timed out waiting for " + what)


def spawn(label, argv, env=None, log=None):
    f = open(os.path.join(WORK, log or (label + ".out")), "w")
    p = subprocess.Popen(argv, stdout=f, stderr=subprocess.STDOUT, env=env, start_new_session=True)
    procs.append((label, p))
    return p


def stop(label_prefixes):
    """Stop the processes whose label starts with one of the prefixes, newest first."""
    for label, p in reversed(procs):
        if p.poll() is None and any(label.startswith(x) for x in label_prefixes):
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    t0 = time.time()
    for label, p in procs:
        if any(label.startswith(x) for x in label_prefixes):
            try:
                p.wait(max(0.1, 6 - (time.time() - t0)))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def shutdown():
    # workers first, then the host, so a worker never sees its hub vanish and goes looking for another pool
    stop(["chimera-D", "chimera-C", "chimera-B"])
    stop(["ollama-D", "ollama-C", "ollama-B"])
    stop(["chimera-A"])
    stop(["ollama-A"])


def up(binary, work):
    """Start the made-up pool and return once its three computers are lending. If that fails part-way it stops
    what it started and raises; after it succeeds, call down()."""
    global BIN, WORK, STOP
    BIN, WORK = os.path.abspath(binary), os.path.abspath(work)
    STOP = os.path.join(WORK, "STOP")
    os.makedirs(WORK, exist_ok=True)
    if os.listdir(WORK):
        raise SystemExit("the work folder must be empty or new: " + WORK)
    try:
        for d in DEVICES:
            json.dump(d["sysinfo"], open(os.path.join(WORK, d["key"] + "-sysinfo.json"), "w"))
            ms = [dict(MODELS[n], name=n, loaded=loaded) for n, loaded in d["models"]]
            json.dump({"models": ms, "step_seconds": d["step_seconds"]}, open(os.path.join(WORK, d["key"] + "-ollama.json"), "w"))
            spawn("ollama-" + d["key"], [sys.executable, FAKE, str(d["ollama"]), os.path.join(WORK, d["key"] + "-ollama.json")])
        for d in DEVICES:
            home = os.path.join(WORK, "home-" + d["key"])
            os.makedirs(home)
            env = dict(os.environ, CHIMERA_NO_AUTOPOOL="1", CHIMERA_NO_DAEMON="1", HOME=home,
                       CHIMERA_SYSINFO=os.path.join(WORK, d["key"] + "-sysinfo.json"))
            args = [BIN, "--data-dir", os.path.join(WORK, d["key"]), "--ui-port", str(d["ui"]), "--no-open",
                    "--ollama", "http://127.0.0.1:%d" % d["ollama"]]
            if d["key"] == "A":
                args += ["--hub-port", str(HUB)]
            spawn("chimera-" + d["key"], args, env)
        for d in DEVICES:
            wait_for(lambda: api(d["ui"], "GET", "/api/ping")[0] == 200, "chimera " + d["key"])
        for d in DEVICES:
            wait_for(lambda: api(d["ui"], "GET", "/api/state")[1]["ollama"].get("models"), "models listed on " + d["key"], 40)
        for d in DEVICES[:3]:
            api(d["ui"], "POST", "/api/settings", {"owner": d["owner"], "device_name": d["name"], "setup_done": True})
        A, B, C = DEVICES[:3]
        api(A["ui"], "POST", "/api/settings", {"auto_join": False})  # a closed pool: never merged with a real one
        st, hv = api(A["ui"], "POST", "/api/network/host", {"enabled": True, "owner": A["owner"], "device_name": A["name"], "name": "Friends"})
        if st != 200:
            raise RuntimeError("host failed: %s %s" % (st, hv))
        for d in (B, C):
            st, out = api(d["ui"], "POST", "/api/network/join", {"address": "127.0.0.1:%d" % HUB, "invite": hv["invite"], "owner": d["owner"], "device_name": d["name"]})
            if st != 200:
                raise RuntimeError("join failed: %s %s" % (st, out))
        for d in (B, C, A):
            api(d["ui"], "POST", "/api/connect")
        print("pool up; waiting for everyone to be lending", flush=True)
        wait_for(lambda: len([m for m in (api(A["ui"], "GET", "/api/state")[1].get("network") or {}).get("devices", []) if m.get("lending")]) >= 3,
                 "three lending devices", 60)
        print("READY " + json.dumps({"ui": {d["key"]: d["ui"] for d in DEVICES}, "hub": HUB}), flush=True)
    except BaseException:
        down()
        raise


def down():
    """Stop everything up() started: the workers first, then the host."""
    print("shutting down", flush=True)
    shutdown()
    left = [l for l, p in procs if p.poll() is None]
    print("still running after shutdown: %s" % (left or "nothing"), flush=True)


def main():
    signal.signal(signal.SIGTERM, lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        up(sys.argv[1], sys.argv[2])
        while not os.path.exists(STOP):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        down()


if __name__ == "__main__":
    main()
