"""Hydra 1.0, the helper model, end to end: a host/asker (A) whose Ollama has big:70b and hydra:1.0, and a worker
(B) with mid:14b and the demo-poster Head, as two real Chimera processes with fake Ollamas (fake_ollama_hydra.py).
A also has a fake Blender (fake_blender/, copied to /var/tmp and put first on A's PATH only).
Checks that long tasks plan and review on hydra:1.0 and work and combine on the other models; that chats never
land on it; that a plan or a review it gets wrong goes to the biggest model; that a task too big for it plans on
the biggest model; that B gets hydra:1.0 from the host inside Chimera (the host's file, template, parameters and
licence); that the Head check runs on B's fastest model before and on B's hydra:1.0 after; and that with no
hydra:1.0 anywhere planning goes back to the biggest model.
Section 10 checks long tasks' results the way looping mode does: the asker (A) runs a Blender script from the result
in its sandbox (the fake Blender) or a Python one (A's own Python), a crash skips the review and goes to the next
round's planner as its critique, the same crash twice stops, anything the check can't be sure of (a write outside
the sandbox, a missing object, typed input) is left to the reviewer, a render ends the run cleanly, cancelling stops
the script, and the setting turns it all off; a combine cut off at its output limit is another round with more room
(looping) or a note on the saved reply (single pass).
Section 11 checks repairs and later rounds: a crash is repaired by edits inside its round, one crash after another,
a repair that breaks the script is taken back, a repair that writes the script out leaves the rest of the result alone,
two tries that get nowhere end it, and the repairs a round gets are limited; a later round's workers and combine see the
result so far, the combine's edits go into it, even with a one-step plan or a plan of another kind; edits that never land
stop the loop; and the person gets the best round, with the note and the card describing that one, whether the loop ran
out, stopped, was cancelled, or a later round couldn't finish. Long worker output reaches the combine whole.
Usage: python3 hydra_test.py <chimera binary> <workdir>"""
import hashlib, http.client, json, os, shutil, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_it as it  # reuse its helpers (api, chat, wait_for, start, check)

BIN, WORK, HERE = it.BIN, it.WORK, it.HERE
A_UI, B_UI, HUB, OLLAMA_A, OLLAMA_B = 7611, 7612, 7615, 11591, 11592
api, chat, wait_for, start, check = it.api, it.chat, it.wait_for, it.start, it.check

PARAMS = ("stop                           \"<|im_start|>\"\nstop                           \"<|im_end|>\"\n"
          "temperature                    0.7\ntop_k                          20\ntop_p                          0.8\n"
          "repeat_penalty                 1\nnum_predict                    4096")
ESCAPE = "/var/tmp/chimera-check-escape.blend"  # what BLENDERSAVE's script tries to write, outside its sandbox
FAKE = None  # the fake Blender's folder (setup)
BIG = {"name": "big:70b", "size": 43000000000, "params": "70.6B", "arch": "llama", "loaded": True}
MID = {"name": "mid:14b", "size": 9000000000, "params": "14.8B", "arch": "llama"}


def fake_ollama(port, name, conf):
    path = os.path.join(WORK, name + ".json")
    json.dump(conf, open(path, "w"))
    it.procs.append(subprocess.Popen([sys.executable, os.path.join(HERE, "fake_ollama_hydra.py"), str(port),
                                      os.path.join(WORK, name + "_chats.jsonl"), path], start_new_session=True))


def calls(name):
    try:
        return [json.loads(l) for l in open(os.path.join(WORK, name + "_chats.jsonl"))]
    except FileNotFoundError:
        return []


def fake_state(port):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/test/state")
    return json.loads(c.getresponse().read())


def set_models(port, models):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("POST", "/test/models", json.dumps({"models": models}), {"Content-Type": "application/json"})
    c.getresponse().read()


def sse(port, path, body, timeout=300, on_event=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    c.request("POST", path, json.dumps(body).encode(), {"X-Chimera": "1", "Content-Type": "application/json"})
    r = c.getresponse()
    if r.status != 200:
        return [{"type": "http_error", "status": r.status, "body": r.read().decode()}]
    events = []
    while True:
        line = r.readline()  # through the chunked encoding: a big event can span chunks
        if not line:
            break
        line = line.decode().strip()
        if line.startswith("data: "):
            ev = json.loads(line[6:])
            events.append(ev)
            if on_event:
                on_event(ev)
            if ev["type"] in ("done", "error", "cancelled"):
                break
    return events


def task(goal, loop=False):
    """Runs a long task on A; returns its final record (or the last event when it fails to start)."""
    evs = sse(A_UI, "/api/task", {"goal": goal, "loop": loop})
    last = evs[-1] if evs else {}
    return last.get("task") or {}, last


def mark():
    """Where both fake Ollamas' logs are now, for since()."""
    return len(calls("ollama_A")), len(calls("ollama_B"))


def since(m):
    """The chat calls both fake Ollamas got after mark() returned m, in the order they came."""
    new = [dict(c, at="A") for c in calls("ollama_A")[m[0]:]] + [dict(c, at="B") for c in calls("ollama_B")[m[1]:]]
    return sorted(new, key=lambda c: c["t"])


def state(port):
    return api(port, "GET", "/api/state")[1]


def system_python():
    """A Python for the fake Blender's #! line that the script sandbox lets run: not in a home or temporary folder."""
    for p in ("/usr/local/bin/python3", "/opt/homebrew/bin/python3", "/usr/bin/python3", sys.executable):
        if not p or not os.path.exists(p):
            continue
        real = os.path.realpath(p)
        if not any(real == d or real.startswith(d + "/") for d in ("/Users", "/home", "/tmp", "/private/tmp")):
            return p
    raise SystemExit("no Python outside the home and temporary folders for the fake Blender")


def make_fake_blender():
    """Copies fake_blender/ to /var/tmp (the sandbox hides /Users) and writes its `blender` program there."""
    global FAKE
    FAKE = tempfile.mkdtemp(prefix="chimera-fake-blender-", dir="/var/tmp")
    shutil.copytree(os.path.join(HERE, "fake_blender"), FAKE, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    src = open(os.path.join(FAKE, "blender.py")).read()
    prog = os.path.join(FAKE, "blender")
    with open(prog, "w") as f:
        f.write("#!%s -I\n%s" % (system_python(), src))
    os.chmod(prog, 0o755)
    return FAKE


def setup():
    """Two computers in one network, both lending: A (host, asker) with big:70b and hydra:1.0, B with mid:14b and
    the demo-poster Head. Returns the stand-in model file's bytes and digest."""
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    os.makedirs(os.path.join(WORK, "blobs_A"))
    if os.path.exists(ESCAPE):
        os.remove(ESCAPE)
    make_fake_blender()
    os.makedirs(os.path.join(WORK, "blobs_B"))
    # Plenty of graphics memory on both, so big:70b fits on A.
    json.dump({"os": "Linux", "os_version": "test", "arch": "amd64", "chip": "Test CPU", "ram_gb": 128, "cores": 16,
               "gpus": [{"name": "NVIDIA RTX test", "vram_gb": 96}]}, open(os.path.join(WORK, "sysinfo.json"), "w"))
    shutil.copytree(os.path.join(HERE, "plugins_src", "demo-poster"), os.path.join(WORK, "B", "plugins", "demo-poster"))
    weights = os.urandom(3 << 20)  # a stand-in for the 2.9 GB model file
    digest = "sha256:" + hashlib.sha256(weights).hexdigest()
    blob = os.path.join(WORK, "blobs_A", digest.replace(":", "-"))
    open(blob, "wb").write(weights)
    hydra = {"name": "hydra:1.0", "size": len(weights), "params": "4.0B", "arch": "qwen3"}
    fake_ollama(OLLAMA_A, "ollama_A", {"models": [BIG, hydra], "blob_dir": os.path.join(WORK, "blobs_A"), "show": {"hydra:1.0": {
        "modelfile": "# Modelfile generated by \"ollama show\"\n# FROM hydra:1.0\n\nFROM %s\nTEMPLATE \"\"\"{{ .Prompt }}\"\"\"\n" % blob,
        "template": "{{- range .Messages }}<|im_start|>{{ .Role }}\n{{ .Content }}<|im_end|>\n{{ end }}<|im_start|>assistant\n",
        "parameters": PARAMS, "license": "Apache License 2.0 (test copy)"}}})
    fake_ollama(OLLAMA_B, "ollama_B", {"models": [MID], "blob_dir": os.path.join(WORK, "blobs_B")})
    start("A", ["--data-dir", os.path.join(WORK, "A"), "--ui-port", str(A_UI), "--hub-port", str(HUB), "--no-open",
                "--ollama", "http://127.0.0.1:%d" % OLLAMA_A], {"PATH": FAKE + os.pathsep + os.environ.get("PATH", "")})
    start("B", ["--data-dir", os.path.join(WORK, "B"), "--ui-port", str(B_UI), "--no-open", "--ollama", "http://127.0.0.1:%d" % OLLAMA_B], {})
    wait_for(lambda: api(A_UI, "GET", "/api/ping")[0] == 200, "A")
    wait_for(lambda: api(B_UI, "GET", "/api/ping")[0] == 200, "B")
    wait_for(lambda: any(t["id"] == "blender" and t["have"] and t.get("via") == "Blender 5.0.1" for t in state(A_UI)["profile"]["tools"]),
             "A finding the fake Blender", 60)
    for port in (A_UI, B_UI):
        wait_for(lambda: state(port)["ollama"]["status"] == "running", "Ollama seen as running", 30)
        wait_for(lambda: state(port)["ollama"].get("models"), "the fake models listed", 30)
    api(A_UI, "POST", "/api/settings", {"auto_join": False})
    st, hv = api(A_UI, "POST", "/api/network/host", {"enabled": True, "owner": "Alice", "device_name": "Studio", "name": "Hydra net"})
    check("A hosts", st == 200 and hv.get("enabled"), str(hv)[:200])
    st, out = api(B_UI, "POST", "/api/network/join", {"address": "127.0.0.1:%d" % HUB, "invite": hv["invite"], "owner": "Bob", "device_name": "Laptop"})
    check("B joins", st == 200, str(out))
    wait_for(lambda: any(t["id"] == "plugin:demo-poster" and t["have"] for t in state(B_UI)["profile"]["tools"]), "B's Head scan", 90)
    api(B_UI, "POST", "/api/connect")
    api(A_UI, "POST", "/api/connect")
    wait_for(lambda: {d["name"] for d in state(A_UI)["network"]["devices"] if d["online"] and d["lending"]} >= {"Studio", "Laptop"}, "both lending", 60)
    return weights, digest


# ---------- section 10: checking a long task's result ----------

def run_task(goal, loop=False, on_event=None):
    """Runs a long task on A; returns its final record, its last event, all its events and how long it took."""
    t0 = time.time()
    evs = sse(A_UI, "/api/task", {"goal": goal, "loop": loop}, on_event=on_event)
    last = evs[-1] if evs else {}
    return last.get("task") or {}, last, evs, time.time() - t0


def poll(fn, timeout):
    """fn's first truthy value within timeout seconds, else None."""
    t0 = time.time()
    while True:
        try:
            v = fn()
            if v:
                return v
        except Exception:
            pass
        if time.time() - t0 > timeout:
            return None
        time.sleep(0.25)


def saved(evs):
    """The task's chat message as A saved it, once it's no longer pending (the final save follows the done event)."""
    started = next((e for e in evs if e["type"] == "started"), {})

    def get():
        sess = api(A_UI, "GET", "/api/sessions/" + started["session_id"])[1]
        m = next((m for m in sess.get("messages", []) if m.get("task_id") == started["task_id"]), None)
        return m if m and m.get("status") != "pending" else None
    return poll(get, 15) or {}


def saved_any(evs):
    """The task's chat message as A saved it, whatever its status, once it isn't pending."""
    return saved(evs)


def by_round(cs):
    """Chat calls split into rounds: each one starts with a planner call."""
    rounds = []
    for c in cs:
        if c["job"] == "planner" or not rounds:
            rounds.append([])
        rounds[-1].append(c)
    return rounds


def jobs(cs, job):
    return [c for c in cs if c["job"] == job]


def fake_running():
    """Processes still running the fake Blender (not the tool scan's quick --version)."""
    out = subprocess.run(["ps", "-A", "-o", "args="], capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if os.path.basename(FAKE) in l and "--version" not in l]


def checks_of(rec):
    cs = rec.get("checks") or []
    return cs, (cs[0] if cs else {}), (cs[1] if len(cs) > 1 else {})


def brief(rec, last):
    return "%s, round %s, checks %s" % (last.get("type"), rec.get("round"), json.dumps(
        [{k: c.get(k) for k in ("round", "outcome", "runner", "error", "line", "model", "tokens", "stopped")} for c in rec.get("checks") or []])[:600])


def section10():
    can_test = state(A_UI)["profile"].get("can_test")
    goal = "%s: write a Blender script that builds a small photo studio with a backdrop"
    if not can_test:
        print("SKIP 10.1-10.9: A's profile says it can't sandbox scripts (can_test false)", flush=True)
    else:
        # ---- 10.1: with the setting off, the script isn't run ----
        st, _ = api(A_UI, "POST", "/api/settings", {"check_results": False})
        check("10.1 the setting turns off", st == 200 and state(A_UI)["settings"]["check_results"] is False)
        n0 = mark()
        rec, last, evs, _ = run_task(goal % "BLENDERCRASH", loop=True)
        cs, c0, _ = checks_of(rec)
        chk = cs[-1] if cs else {}
        check("10.1 with it off: one round, the script skipped, and the summary points to Settings",
              last.get("type") == "done" and rec.get("round") == 1 and chk.get("outcome") == "skipped" and "Settings" in chk.get("summary", ""),
              brief(rec, last) + " " + chk.get("summary", ""))
        check("10.1 with it off the reviewer decides, once", len(jobs(since(n0), "reviewer")) == 1, str([c["job"] for c in since(n0)]))
        st, _ = api(A_UI, "POST", "/api/settings", {"check_results": True})
        check("10.1 the setting turns back on", st == 200 and state(A_UI)["settings"]["check_results"] is True)

        # ---- 10.2: a crash goes to the next round's planner, and the fix passes ----
        n0 = mark()
        rec, last, evs, _ = run_task(goal % "BLENDERCRASH", loop=True)
        cs, c0, c1 = checks_of(rec)
        rs = by_round(since(n0))
        check("10.2 a script that crashes takes 2 rounds", last.get("type") == "done" and rec.get("round") == 2 and len(cs) == 2, brief(rec, last))
        check("10.2 round 1's check failed in Blender 5.0.1 on the AttributeError at line 7",
              c0.get("outcome") == "failed" and c0.get("runner") == "Blender 5.0.1" and c0.get("line") == 7 and
              "module 'mathutils' has no attribute 'radians'" in c0.get("error", ""), json.dumps(c0)[:500])
        check("10.2 the crash skipped round 1's review; round 2 was reviewed once",
              len(rs) == 2 and not jobs(rs[0], "reviewer") and len(jobs(rs[1], "reviewer")) == 1, str([[c["job"] for c in r] for r in rs]))
        crit = (rs[1][0].get("critique") or "") if len(rs) > 1 else ""
        check("10.2 round 2's planner got the error, its line and the Blender version as the critique",
              "module 'mathutils' has no attribute 'radians'" in crit and "line 7" in crit and "Blender 5.0.1" in crit, crit[:400])
        check("10.2 round 2's fixed script passed", c1.get("outcome") == "passed" and c1.get("round") == 2, json.dumps(c1)[:300])
        check("10.2 the task is done", rec.get("phase") == "done", str(rec.get("phase")))
        m = saved(evs)
        check("10.2 the saved reply has no note", m and not m.get("status") and not m.get("note"),
              json.dumps({k: m.get(k) for k in ("status", "note")}))

        # ---- 10.3: the same crash twice stops ----
        n0 = mark()
        rec, last, evs, _ = run_task(goal % "BLENDERSAME", loop=True)
        cs, c0, c1 = checks_of(rec)
        check("10.3 the same crash twice stops after 2 rounds", last.get("type") == "done" and rec.get("round") == 2 and len(cs) == 2, brief(rec, last))
        check("10.3 round 2's check failed the same way and stopped the loop",
              c1.get("outcome") == "failed" and c1.get("stopped") and c1.get("error") == c0.get("error"), json.dumps(c1)[:400])
        check("10.3 neither round was reviewed", not jobs(since(n0), "reviewer"), str([c["job"] for c in since(n0)]))
        m = saved(evs)
        check("10.3 the saved reply's note says the script still crashes", "still crashes" in (m.get("note") or ""), str(m.get("note")))

        # ---- 10.4: a write outside the sandbox is blocked, and left to the reviewer ----
        n0 = mark()
        rec, last, evs, _ = run_task(goal % "BLENDERSAVE", loop=True)
        cs, c0, _ = checks_of(rec)
        check("10.4 a script that saves outside its folder: one round, unsure, then the review",
              last.get("type") == "done" and rec.get("round") == 1 and c0.get("outcome") == "unsure" and len(jobs(since(n0), "reviewer")) == 1,
              brief(rec, last) + " " + c0.get("summary", ""))
        check("10.4 the sandbox kept it from writing " + ESCAPE, not os.path.exists(ESCAPE) and "Cannot open file" in c0.get("error", ""),
              str(c0.get("error")))

        # ---- 10.5: an object a fresh scene doesn't have ----
        n0 = mark()
        rec, last, evs, _ = run_task(goal % "BLENDERSCENE", loop=True)
        cs, c0, _ = checks_of(rec)
        check("10.5 a script that needs your own scene: one round, unsure, then the review",
              last.get("type") == "done" and rec.get("round") == 1 and c0.get("outcome") == "unsure" and "Hero" in c0.get("summary", "") and
              len(jobs(since(n0), "reviewer")) == 1, brief(rec, last) + " " + c0.get("summary", ""))

        m = saved(evs)
        check("10.5 the saved reply says the script stopped and the check couldn't tell", "couldn't tell" in (m.get("note") or "") and "Hero" in (m.get("note") or ""),
              str(m.get("note")))

        # ---- 10.6: a render ends the run cleanly ----
        rec, last, evs, secs = run_task(goal % "BLENDERRENDER", loop=True)
        cs, c0, _ = checks_of(rec)
        check("10.6 a script that renders passes, stopped at its render", last.get("type") == "done" and rec.get("round") == 1 and
              c0.get("outcome") == "passed" and "render" in c0.get("summary", ""), brief(rec, last) + " " + c0.get("summary", ""))
        check("10.6 the render didn't hold the task up (%.1f s)" % secs, secs < 20)

        # ---- 10.7: cancelling while the script runs stops it ----
        seen = {}

        def on_event(ev):
            if ev["type"] == "task" and (ev.get("task") or {}).get("phase") == "checking" and "at" not in seen:
                seen["running"] = poll(fake_running, 10) or []
                seen["at"] = time.time()
                seen["cancel"] = api(A_UI, "POST", "/api/task/%s/cancel" % ev["task_id"])[0]
        rec, last, evs, _ = run_task(goal % "BLENDERSLOW", loop=True, on_event=on_event)
        took = time.time() - seen["at"] if "at" in seen else None
        check("10.7 the slow script was running in the fake Blender when the task was cancelled", seen.get("running") and seen.get("cancel") == 200,
              "%s; cancel %s" % (str(seen.get("running"))[:200], seen.get("cancel")))
        check("10.7 the task ended cancelled within 10 s", last.get("type") == "cancelled" and took is not None and took < 10,
              "%s after %s s" % (last.get("type"), took and round(took, 1)))
        left = poll(lambda: not fake_running(), 5)
        check("10.7 nothing of the fake Blender is left running", left, str(fake_running())[:300])

        # ---- 10.8: plain Python in a coding plan, with A's own Python ----
        rec, last, evs, _ = run_task("PYCRASH: write a small Python program that prints the average of some numbers", loop=True)
        cs, c0, c1 = checks_of(rec)
        check("10.8 a Python script that crashes takes 2 rounds", last.get("type") == "done" and rec.get("round") == 2 and len(cs) == 2, brief(rec, last))
        check("10.8 round 1's check failed in A's Python on the NameError", c0.get("outcome") == "failed" and
              (c0.get("runner") or "").startswith("Python 3.") and "NameError" in c0.get("error", ""), json.dumps(c0)[:400])
        check("10.8 round 2's fixed script passed", c1.get("outcome") == "passed", json.dumps(c1)[:300])

        # ---- 10.9: typed input is left to the reviewer ----
        n0 = mark()
        rec, last, evs, _ = run_task("PYINPUT: write a small Python program that greets you by name", loop=True)
        cs, c0, _ = checks_of(rec)
        check("10.9 a script waiting for typed input: one round, unsure (EOFError), then the review",
              last.get("type") == "done" and rec.get("round") == 1 and c0.get("outcome") == "unsure" and "EOFError" in c0.get("error", "") and
              len(jobs(since(n0), "reviewer")) == 1, brief(rec, last) + " " + c0.get("summary", ""))

    # ---- 10.10: a combine cut off at its output limit is another round, with more room ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "CUTOFF", loop=True)
    cs, c0, c1 = checks_of(rec)
    rs = by_round(since(n0))
    check("10.10 a cut-off result takes 2 rounds", last.get("type") == "done" and rec.get("round") == 2 and len(cs) == 2, brief(rec, last))
    check("10.10 round 1 was cut off: big:70b, 4096 tokens", c0.get("outcome") == "cut_off" and c0.get("model") == "big:70b" and c0.get("tokens") == 4096,
          json.dumps(c0)[:300])
    check("10.10 round 1 had no review and its script wasn't run", len(rs) == 2 and not jobs(rs[0], "reviewer") and
          [c for c in cs if c.get("round") == 1] == [c0], str([[c["job"] for c in r] for r in rs]))
    crit = (rs[1][0].get("critique") or "") if len(rs) > 1 else ""
    check("10.10 round 2's planner was told it was cut off", "cut off" in crit, crit[:300])
    comb = [jobs(r, "combine") for r in rs] + [[], []]
    c1st, c2nd = (comb[0] or [{}])[-1], (comb[1] or [{}])[-1]
    check("10.10 round 1's combine had the 8K context and no output limit set", c1st.get("num_ctx") == 8192 and c1st.get("num_predict") is None,
          "num_ctx %s, num_predict %s" % (c1st.get("num_ctx"), c1st.get("num_predict")))
    check("10.10 round 2's combine got more room: num_predict 8192, 32K context", c2nd.get("num_predict") == 8192 and c2nd.get("num_ctx") == 32768,
          "num_ctx %s, num_predict %s" % (c2nd.get("num_ctx"), c2nd.get("num_predict")))
    check("10.10 a result that was cut off is written out again, not edited", "The result so far:" in c2nd.get("user_all", "") and not c2nd.get("edits"),
          str(c2nd.get("edits")))
    if can_test:
        check("10.10 round 2's complete script passed", c1.get("outcome") == "passed", json.dumps(c1)[:300])

    # ---- 10.11: cut off twice in a row stops ----
    rec, last, evs, _ = run_task(goal % "CUTALWAYS", loop=True)
    cs, c0, c1 = checks_of(rec)
    check("10.11 cut off twice stops after 2 rounds: [cut_off, cut_off and stopped]", last.get("type") == "done" and rec.get("round") == 2 and
          [c.get("outcome") for c in cs] == ["cut_off", "cut_off"] and not c0.get("stopped") and c1.get("stopped"), brief(rec, last))

    # ---- 10.12: single pass: a cut-off result gets a note ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "CUTONCE", loop=False)
    cs, c0, _ = checks_of(rec)
    check("10.12 single pass: one round, checks [cut_off], no review", last.get("type") == "done" and rec.get("round") == 1 and
          [c.get("outcome") for c in cs] == ["cut_off"] and not jobs(since(n0), "reviewer"), brief(rec, last))
    m = saved(evs)
    check("10.12 the saved reply's note says it was cut off", "cut off" in (m.get("note") or ""), str(m.get("note")))


def section11():
    goal = "%s: write a Blender script that builds a small photo studio with a backdrop"
    goalc = goal + ", and a camera that frames everything"
    if not state(A_UI)["profile"].get("can_test"):
        print("SKIP 11: A's profile says it can't sandbox scripts (can_test false)", flush=True)
        return

    # ---- 11.1: a crash is repaired inside the round ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "BLENDERMEND", loop=True)
    cs, c0, c1 = checks_of(rec)
    cc = since(n0)
    check("11.1 a crash a repair can fix takes one round: [failed, passed in repair 1]", last.get("type") == "done" and rec.get("round") == 1 and
          [(c.get("outcome"), c.get("mend", 0)) for c in cs] == [("failed", 0), ("passed", 1)], brief(rec, last))
    check("11.1 no second planner, and the review came after the repair", len(jobs(cc, "planner")) == 1 and len(jobs(cc, "mend")) == 1 and
          [c["job"] for c in cc][-1] == "reviewer", str([c["job"] for c in cc]))
    m0 = (jobs(cc, "mend") or [{}])[0]
    check("11.1 the repair got the script, the error and the goal, and was asked for edits", m0.get("edits") and
          "module 'mathutils' has no attribute 'radians'" in m0.get("user_all", "") and "scene.collection.objects.link(backdrop)" in m0.get("user_all", "") and
          "small photo studio" in m0.get("user_all", ""), str(m0.get("user_all"))[:300])
    m = saved(evs)
    body = m.get("content", "")
    check("11.1 the saved reply is the repaired script, with what surrounded it, and no note", "math.radians(180)" in body and
          "mathutils.radians" not in body and "Run it headless" in body and "<<<<<<<" not in body and not m.get("note"), body[:300] + " note " + str(m.get("note")))
    check("11.1 the card names who repaired it", rec.get("mend_model") == "big:70b" and rec.get("mend_device"), str(rec.get("mend_model")))

    # ---- 11.2: one crash after another ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "BLENDERMEND2", loop=True)
    cs, c0, c1 = checks_of(rec)
    check("11.2 two crashes, two repairs, one round", last.get("type") == "done" and rec.get("round") == 1 and
          [(c.get("outcome"), c.get("mend", 0)) for c in cs] == [("failed", 0), ("failed", 1), ("passed", 2)], brief(rec, last))
    check("11.2 the second repair worked on the first one's script", "math.radians" in (jobs(since(n0), "mend") + [{}, {}])[1].get("user_all", ""),
          str([c.get("user_all", "")[:80] for c in jobs(since(n0), "mend")]))

    # ---- 11.3: a repair that breaks the script is taken back ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "BLENDERMENDBAD", loop=True)
    cs, c0, c1 = checks_of(rec)
    check("11.3 [failed, repair 1 failed to start and taken back, repair 2 passed]", last.get("type") == "done" and rec.get("round") == 1 and
          [(c.get("outcome"), c.get("mend", 0), bool(c.get("undone"))) for c in cs] == [("failed", 0, False), ("failed", 1, True), ("passed", 2, False)], brief(rec, last))
    check("11.3 the failed try's error is a SyntaxError", "SyntaxError" in c1.get("error", ""), json.dumps(c1)[:300])
    ms = jobs(since(n0), "mend")
    check("11.3 the second repair started from the script before the bad one", len(ms) == 2 and "import mathutils(" not in ms[1].get("user_all", ""),
          str([c.get("user_all", "")[:80] for c in ms]))
    m = saved(evs)
    check("11.3 the reply has no trace of the bad repair", "import mathutils(" not in m.get("content", "") and "math.radians(180)" in m.get("content", ""), m.get("content", "")[:300])

    # ---- 11.4: repairs are limited ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "BLENDERMENDFAR", loop=True)
    cc = since(n0)
    first = by_round(cc)[0]
    check("11.4 a round gets 8 repairs", len(jobs(first, "mend")) == 8, str([c["job"] for c in first]))
    check("11.4 the next round worked from the repaired script", len(by_round(cc)) > 1 and "a = 1" in by_round(cc)[1][0].get("user_all", ""),
          str(len(by_round(cc))))

    # ---- 11.5: a later round's combine edits the result ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "BLENDEREDIT", loop=True)
    cs, c0, c1 = checks_of(rec)
    rs = by_round(since(n0))
    check("11.5 a script the reviewer sends back takes 2 rounds, both passed", last.get("type") == "done" and rec.get("round") == 2 and
          [c.get("outcome") for c in cs] == ["passed", "passed"], brief(rec, last))
    w2 = jobs(rs[1], "worker") if len(rs) > 1 else []
    check("11.5 round 1's workers saw nothing earlier", not any("The result so far" in c.get("user_all", "") for c in jobs(rs[0], "worker")))
    check("11.5 round 2's workers got the script and the critique", w2 and all("The result so far:" in c["user_all"] and "chimera_backdrop" in c["user_all"] and
          "Add a fill light." in c["user_all"] and "only the code your step adds or changes" in c["user_all"] for c in w2), str([c.get("user_all", "")[:200] for c in w2]))
    c2 = (jobs(rs[1], "combine") if len(rs) > 1 else [{}])[-1]
    check("11.5 round 2's combine got the script and was asked for edits; round 1's wasn't", c2.get("edits") and "The result so far:" in c2.get("user_all", "") and
          not jobs(rs[0], "combine")[-1].get("edits"), str(c2.get("user_all"))[:300])
    m = saved(evs)
    body = m.get("content", "")
    check("11.5 the saved reply is round 1's reply with the edit in it", "chimera_fill" in body and "chimera_backdrop" in body and "math.radians(180)" in body and
          "Run it headless" in body and "<<<<<<<" not in body, body[:400])
    typed = "".join(e.get("content", "") for e in evs if e.get("type") == "delta")
    check("11.5 the edits were never shown as the reply", "<<<<<<<" not in typed, typed[:200])

    # ---- 11.6: a one-step later plan still edits ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "BLENDERONE", loop=True)
    rs = by_round(since(n0))
    m = saved(evs)
    check("11.6 a one-step later plan goes through the combine, and the script stays whole", last.get("type") == "done" and rec.get("round") == 2 and
          len(rs) == 2 and len(jobs(rs[1], "combine")) == 1 and "chimera_fill" in m.get("content", "") and "chimera_backdrop" in m.get("content", ""),
          brief(rec, last) + m.get("content", "")[:200])

    # ---- 11.7: a round that comes out worse doesn't replace a better one ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "BLENDERWORSE", loop=True)
    cs, c0, c1 = checks_of(rec)
    rs = by_round(since(n0))
    check("11.7 the task keeps round 1's result: [passed, failed, failed]", last.get("type") == "done" and rec.get("kept") == 1 and
          [c.get("outcome") for c in cs] == ["passed", "failed", "failed"], brief(rec, last) + " kept " + str(rec.get("kept")))
    check("11.7 round 3 worked from round 1's script and critique, not the crash", len(rs) == 3 and rs[2][0].get("critique") == "Add a fill light." and
          "make_it_bigger" not in rs[2][0].get("user_all", ""), str([r[0].get("critique") for r in rs]))
    m = saved(evs)
    check("11.7 the saved reply is round 1's, says so, and isn't marked as crashing", "make_it_bigger" not in m.get("content", "") and "chimera_backdrop" in m.get("content", "") and
          "round 1's result" in (m.get("note") or "") and "still crashes" not in (m.get("note") or ""), str(m.get("note")) + " " + m.get("content", "")[:200])
    check("11.7 the task shows round 1's plan", rec.get("title") == "Studio v1", str(rec.get("title")))

    # ---- 11.8: a later round that can't finish keeps the best one ----
    rec, last, evs, _ = run_task(goal % "BLENDERGONE", loop=True)
    m = saved(evs)
    check("11.8 a later round without a plan keeps round 1's result, and says so", last.get("type") == "done" and rec.get("kept") == 1 and
          "Round 2 couldn't finish" in (m.get("note") or "") and "chimera_backdrop" in m.get("content", ""), brief(rec, last) + " " + str(m.get("note")))

    # ---- 11.9: plain Python is repaired too ----
    rec, last, evs, _ = run_task("PYMEND: write a small Python program that prints the average of some numbers", loop=True)
    cs, c0, c1 = checks_of(rec)
    check("11.9 a Python crash is repaired in its round", last.get("type") == "done" and rec.get("round") == 1 and
          [(c.get("outcome"), c.get("mend", 0)) for c in cs] == [("failed", 0), ("passed", 1)], brief(rec, last))

    # ---- 11.9b: a wrong name comes with the real ones ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "BLENDERNAMES", loop=True)
    cc = since(n0)
    ms = jobs(cc, "mend")
    us = (ms or [{}])[0].get("user_all", "")
    check("11.9b the repair is told what the object really has, closest first", "Object has no locaton. What it does have: location," in us, us[-400:])
    rs = by_round(cc)
    crit = (rs[1][0].get("critique") or "") if len(rs) > 1 else ""
    check("11.9b so is the next round's planner, in its critique", "What it does have: location," in crit, crit[-300:])
    cs, c0, _ = checks_of(rec)
    check("11.9b the check is still a plain failure, and the names aren't on the card", c0.get("outcome") == "failed" and c0.get("line") == 6 and
          "chimera-check" not in c0.get("output", ""), json.dumps(c0)[:400])

    # ---- 11.9c: a script that runs but builds the wrong scene ----
    n0 = mark()
    rec, last, evs, _ = run_task(goalc % "BLENDEROFFSHOT", loop=True)
    cs, c0, c1 = checks_of(rec)
    cc = since(n0)
    check("11.9c a scene the camera can't see goes to a repair, in its round: [wrong_scene, passed]", last.get("type") == "done" and rec.get("round") == 1 and
          [(c.get("outcome"), c.get("mend", 0)) for c in cs] == [("wrong_scene", 0), ("passed", 1)], brief(rec, last))
    check("11.9c it wasn't reviewed until the scene was right", [c["job"] for c in cc].index("mend") < [c["job"] for c in cc].index("reviewer"), str([c["job"] for c in cc]))
    us = (jobs(cc, "mend") or [{}])[0].get("user_all", "")
    check("11.9c the repair got what was wrong and the measurements", "The camera sees none of the 1 objects." in us and "location = (9.00, -3.00, 9.00)" in us and
          "chimera_backdrop at (9.00, 9.00, 9.00)" in us, us[-500:])
    check("11.9c the card says what was measured, and the reply has no note", "1 of its 1 objects are in the camera's frame." in c1.get("summary", "") and not saved(evs).get("note"),
          c1.get("summary", "") + " note " + str(saved(evs).get("note")))

    n0 = mark()
    rec, last, evs, _ = run_task("%s: create a blender scene of a mug on a table" % "BLENDERUNSHOWN", loop=True)
    cs, c0, c1 = checks_of(rec)
    us = (jobs(since(n0), "mend") or [{}])[0].get("user_all", "")
    check("11.9c a task that never mentions a camera still has to show what it names: [wrong_scene, passed]", last.get("type") == "done" and
          [(c.get("outcome"), c.get("mend", 0)) for c in cs] == [("wrong_scene", 0), ("passed", 1)] and "doesn't show chimera_mug" in us, brief(rec, last) + us[-300:])

    n0 = mark()
    rec, last, evs, _ = run_task(goalc % "BLENDERSTAYSOFF", loop=True)
    m = saved(evs)
    rs = by_round(since(n0))
    crit = (rs[1][0].get("critique") or "") if len(rs) > 1 else ""
    check("11.9c a scene repairs can't fix goes to the next round's planner with the measurements", "The camera sees none" in crit and "location = (9.00" in crit, crit[:300])
    check("11.9c the same scene twice stops, and the reply says what's wrong", last.get("type") == "done" and "its scene is wrong" in (m.get("note") or "") and
          "The camera sees none" in (m.get("note") or ""), brief(rec, last) + " " + str(m.get("note")))

    # ---- 11.10: two replies that change nothing end the repairs ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "BLENDERCRASH", loop=True)
    first = by_round(since(n0))[0]
    ms = jobs(first, "mend")
    check("11.10 a repair that changes nothing is tried once more, then the round ends", len(ms) == 2 and rec.get("round") == 2, str([c["job"] for c in first]))
    check("11.10 the second try is told the first changed nothing", len(ms) == 2 and "changed nothing" in ms[1].get("user_all", "") and
          "changed nothing" not in ms[0].get("user_all", ""), str([c.get("user_all", "")[-120:] for c in ms]))

    # ---- 11.11: the same error on the same line twice ends the repairs ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "BLENDERSTUCK", loop=True)
    first = by_round(since(n0))[0]
    check("11.11 edits that leave the crash where it was stop after 2", len(jobs(first, "mend")) == 2, str([c["job"] for c in first]))

    # ---- 11.12: a repair that writes the script out only replaces the script ----
    rec, last, evs, _ = run_task(goal % "BLENDERWHOLE", loop=True)
    m = saved(evs)
    check("11.12 the repaired script went in, and the rest of the reply stayed", last.get("type") == "done" and rec.get("round") == 1 and
          "math.radians(180)" in m.get("content", "") and "Run it headless" in m.get("content", ""), brief(rec, last) + " " + m.get("content", "")[:200])

    # ---- 11.13: stopping a later round leaves the best result ----
    seen = {}

    def on_event(ev):
        if ev["type"] == "task" and (ev.get("task") or {}).get("phase") == "mending" and "cancel" not in seen:
            seen["card"] = ev["task"]
            seen["cancel"] = api(A_UI, "POST", "/api/task/%s/cancel" % ev["task_id"])[0]
    rec, last, evs, _ = run_task(goal % "BLENDERSTOP", loop=True, on_event=on_event)
    m = saved_any(evs)
    check("11.13 the task stopped during round 2's repair", seen.get("cancel") == 200 and last.get("type") == "cancelled", brief(rec, last))
    check("11.13 the reply is round 1's, says so, and the task keeps it", rec.get("kept") == 1 and "make_it_bigger" not in m.get("content", "") and
          "chimera_backdrop" in m.get("content", "") and "round 1's result" in (m.get("note") or ""), str(m.get("note")) + " " + m.get("content", "")[:200])

    # ---- 11.13b: a round better than the best so far counts, even if it's stopped during its repair ----
    seen = {}

    def on_event(ev):
        if ev["type"] == "task" and (ev.get("task") or {}).get("phase") == "mending" and "cancel" not in seen:
            seen["cancel"] = api(A_UI, "POST", "/api/task/%s/cancel" % ev["task_id"])[0]
    rec, last, evs, _ = run_task(goal % "BLENDERSTOPCUT", loop=True, on_event=on_event)
    m = saved_any(evs)
    check("11.13b stopped during round 2's repair: the reply is round 2's whole script, not round 1's cut-off one", seen.get("cancel") == 200 and last.get("type") == "cancelled" and
          not rec.get("kept") and "chimera_backdrop" in m.get("content", "") and "chimera_cube" not in m.get("content", ""), brief(rec, last) + " " + m.get("content", "")[:160])

    # ---- 11.14: a kept round that still crashes says so ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "BLENDERBADLATER", loop=True)
    cs, c0, c1 = checks_of(rec)
    m = saved(evs)
    check("11.14 a script that runs part-way beats one that doesn't start", last.get("type") == "done" and rec.get("kept") == 1 and "import mathutils(" not in m.get("content", ""),
          brief(rec, last) + " kept " + str(rec.get("kept")))
    check("11.14 the note names the round and the crash that's left", "round 1's result" in (m.get("note") or "") and "still crashes" in (m.get("note") or "") and
          "radians" in (m.get("note") or ""), str(m.get("note")))

    # ---- 11.15: the last round allowed comes out worse ----
    rec, last, evs, _ = run_task(goal % "BLENDERLIMIT", loop=True)
    cs, c0, c1 = checks_of(rec)
    m = saved(evs)
    check("11.15 six rounds, the last one worse: the task keeps round 5", last.get("type") == "done" and rec.get("round") == 6 and rec.get("kept") == 5 and
          [c.get("outcome") for c in cs] == ["passed"] * 5 + ["failed"] and "make_it_bigger" not in m.get("content", "") and "round 5's result" in (m.get("note") or ""),
          brief(rec, last) + " kept " + str(rec.get("kept")) + " " + str(m.get("note")))

    # ---- 11.16: a round that can't finish, with the best further back ----
    rec, last, evs, _ = run_task(goal % "BLENDERGONE3", loop=True)
    m = saved(evs)
    check("11.16 round 3 couldn't finish, and round 2 was worse: the task keeps round 1", last.get("type") == "done" and rec.get("kept") == 1 and
          "Round 3 couldn't finish" in (m.get("note") or "") and "round 1's result" in (m.get("note") or "") and "make_it_bigger" not in m.get("content", ""),
          brief(rec, last) + " " + str(m.get("note")))

    # ---- 11.17: a crash beats no script ----
    rec, last, evs, _ = run_task(goal % "BLENDERPROSE", loop=True)
    m = saved(evs)
    check("11.17 a script that crashes isn't thrown away for words with no script", last.get("type") == "done" and "chimera_backdrop" in m.get("content", "") and
          "still crashes" in (m.get("note") or ""), brief(rec, last) + " " + str(m.get("note")))

    # ---- 11.18: edits that never land ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "BLENDERMISS", loop=True)
    cc = since(n0)
    rs = by_round(cc)
    m = saved(evs)
    check("11.18 edits that change nothing stop after 2 rounds and keep round 1", last.get("type") == "done" and len(rs) == 3 and rec.get("kept") == 1, brief(rec, last) + " rounds " + str(len(rs)))
    check("11.18 the same text wasn't reviewed again", len(jobs(cc, "reviewer")) == 1, str([c["job"] for c in cc]))
    c3 = (jobs(rs[2], "combine") if len(rs) > 2 else [{}])[-1]
    check("11.18 the next combine is told its edits changed nothing; the planner's text isn't", "changed nothing" in c3.get("user_all", "") and
          "changed nothing" not in (rs[2][0].get("user_all", "") if len(rs) > 2 else ""), c3.get("user_all", "")[-200:])
    check("11.18 the note says so", "didn't improve on it" in (m.get("note") or ""), str(m.get("note")))

    # ---- 11.18b: edits that never land on a crashing script get their second try ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "BLENDERUNCH", loop=True)
    rs = by_round(since(n0))
    c3 = (jobs(rs[2], "combine") if len(rs) > 2 else [{}])[-1]
    check("11.18b the same crash in the same text doesn't stop the loop at once: 3 rounds, and round 3's combine is told", last.get("type") == "done" and len(rs) == 3 and
          "changed nothing" in c3.get("user_all", ""), brief(rec, last) + " rounds " + str(len(rs)))

    # ---- 11.19: a later plan labelled something else ----
    rec, last, evs, _ = run_task("PYKIND: write a small Python program that prints the average of some numbers", loop=True)
    cs, c0, c1 = checks_of(rec)
    m = saved(evs)
    check("11.19 a later plan of another kind still gets its edits in and its script checked", last.get("type") == "done" and rec.get("round") == 2 and
          [c.get("outcome") for c in cs] == ["failed", "passed"] and "average(numbers)" in m.get("content", "") and "averge(" not in m.get("content", ""), brief(rec, last))

    # ---- 11.19b: an error the check couldn't judge goes on to the next round ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "BLENDERUNSURE", loop=True)
    rs = by_round(since(n0))
    crit = (rs[1][0].get("critique") or "") if len(rs) > 1 else ""
    check("11.19b the next planner gets the review's critique and the error that stopped the script", "Add a fill light." in crit and "Hero" in crit and "line 4" in crit, crit[:300])

    # ---- 11.20: a long worker output reaches the combine whole ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "BLENDERLONG", loop=True)
    comb = jobs(since(n0), "combine")
    check("11.20 six steps, one of 19,000 characters: nothing cut", len(comb) == 1 and "TAILMARK" in comb[0].get("user_all", "") and "(cut)" not in comb[0].get("user_all", ""),
          str(len(comb)))

    # ---- 11.20b: steps in a chain leave the biggest model ----
    n0 = mark()
    rec, last, evs, _ = run_task(goal % "BLENDERCHAIN", loop=True)
    ws = jobs(since(n0), "worker")
    check("11.20b a chain of three runs one at a time, and the biggest model doesn't get them all just for its size", last.get("type") == "done" and len(ws) == 3 and
          any(c.get("model") != "big:70b" for c in ws), str([(c.get("at"), c.get("model")) for c in ws]))

    # ---- 11.21: words get the result so far too, and are written out ----
    n0 = mark()
    rec, last, evs, _ = run_task("TEALOOP: write a short guide to brewing green and black tea", loop=True)
    rs = by_round(since(n0))
    m = saved(evs)
    w2 = jobs(rs[1], "worker") if len(rs) > 1 else []
    c2 = (jobs(rs[1], "combine") if len(rs) > 1 else [{}])[-1]
    check("11.21 a guide the reviewer sends back: round 2's workers and combine see it, and nobody's asked for edits", last.get("type") == "done" and rec.get("round") == 2 and
          w2 and all("The finished guide" in c["user_all"] and "Say more about black tea." in c["user_all"] and "Keep what already works." in c["user_all"] for c in w2) and
          "The result so far:" in c2.get("user_all", "") and not c2.get("edits"), brief(rec, last))
    check("11.21 the second draft replaced the first", m.get("content", "").startswith("Second draft"), m.get("content", "")[:100])


def main():
    weights, digest = setup()

    # ---- 0: the host shares its Hydra 1.0; B sees it offered ----
    wait_for(lambda: state(A_UI)["helper"]["sharing"], "A sharing its hydra:1.0", 30)
    hb = wait_for(lambda: (lambda h: h if h["offered"] else None)(state(B_UI)["helper"]), "B seeing the offer", 30)
    check("0. B sees the host's Hydra 1.0 on offer, not yet installed", hb["offered"] and not hb["installed"] and hb["model"] == "hydra:1.0", json.dumps(hb))

    # ---- 1: a looping long task plans and reviews on hydra:1.0, works and combines elsewhere ----
    n0 = mark()
    rec, last = task("Write a short guide to brewing green and black tea", loop=True)
    check("1. the task finished", last.get("type") == "done", json.dumps(last)[:300])
    check("1. planned on hydra:1.0", rec.get("planner_model") == "hydra:1.0", "%s on %s" % (rec.get("planner_model"), rec.get("planner_device")))
    check("1. reviewed on hydra:1.0", rec.get("reviewer_model") == "hydra:1.0", "%s on %s" % (rec.get("reviewer_model"), rec.get("reviewer_device")))
    check("1. combined on the biggest model", rec.get("synth_model") == "big:70b", str(rec.get("synth_model")))
    step_models = [s.get("model") for s in rec.get("steps", [])]
    check("1. the steps ran on ordinary models, never the helper", step_models and not any((m or "").startswith("hydra") for m in step_models), str(step_models))
    jobs = [(c["model"], c["job"]) for c in since(n0)]
    check("1. hydra:1.0 only planned and reviewed", {j for m, j in jobs if m.startswith("hydra")} == {"planner", "reviewer"}, str(jobs))
    plan_ctx = [c["num_ctx"] for c in since(n0) if c["model"].startswith("hydra")]
    check("1. the helper ran with the 8K context", plan_ctx and all(n == 8192 for n in plan_ctx), str(plan_ctx))
    check("1. the tea writing task in looping mode has no checks", not rec.get("checks"), json.dumps(rec.get("checks")))

    # ---- 2: an ordinary chat never lands on the helper ----
    n0 = mark()
    evs = chat(A_UI, {"message": "What is the capital of France", "model": ""})
    asg = next((e for e in evs if e["type"] == "assigned"), {})
    check("2. a chat runs on an ordinary model", evs[-1]["type"] == "done" and asg.get("model") in ("big:70b", "mid:14b"), json.dumps(asg))
    check("2. no chat reached the helper", not any(c["model"].startswith("hydra") for c in since(n0)), str(since(n0)))

    # ---- 3: the Head check, before B has the helper: B's fastest model (A is the asker, so never A) ----
    n0 = mark()
    evs = chat(A_UI, {"message": "make me a red poster please", "model": ""})
    plug = next((e for e in evs if e["type"] == "plugin"), None)
    gates = [c for c in since(n0) if c["job"] == "gate"]
    check("3. a request to make something goes to the Head", plug and plug["plugin"] == "demo-poster" and evs[-1]["type"] == "done", json.dumps(evs[-1])[:200])
    check("3. the Head check ran on B's own model (no helper there, and never on the asker)",
          gates and all(g["at"] == "B" and g["model"] == "mid:14b" for g in gates), str([(g["at"], g["model"]) for g in gates]))

    # ---- 4: B gets Hydra 1.0 from the host, inside Chimera ----
    evs = sse(B_UI, "/api/helper/install", {})
    prog = [e for e in evs if e["type"] == "progress"]
    check("4. the install finished", evs and evs[-1]["type"] == "done", json.dumps(evs[-3:])[:300])
    copying = [e for e in prog if e.get("status") == "Copying from the host"]
    check("4. it reported the copy's progress", copying and copying[-1].get("completed") == copying[-1].get("total") == len(weights),
          str(copying[-3:])[:300])
    fs = fake_state(OLLAMA_B)
    check("4. the host's model file arrived whole", fs["blobs"].get(digest) == len(weights), str(fs["blobs"]))
    cr = fs["creates"][0] if fs["creates"] else {}
    check("4. B's Ollama made hydra:1.0 from it", cr.get("model") == "hydra:1.0" and cr.get("files") == {"hydra-1.0.gguf": digest}, json.dumps(cr)[:300])
    check("4. with the host's template, parameters and licence", cr.get("template", "").startswith("{{- range .Messages }}") and
          cr.get("parameters", {}).get("stop") == ["<|im_start|>", "<|im_end|>"] and cr.get("parameters", {}).get("num_predict") == 4096 and
          cr.get("parameters", {}).get("temperature") == 0.7 and cr.get("license") == "Apache License 2.0 (test copy)", json.dumps(cr.get("parameters")))
    wait_for(lambda: state(B_UI)["helper"]["installed"], "B listing hydra:1.0", 30)
    wait_for(lambda: any(d["name"] == "Laptop" and any(m["name"] == "hydra:1.0" for m in d.get("models") or [])
                         for d in state(A_UI)["network"]["devices"]), "the hub seeing B's hydra:1.0", 30)
    check("4. B now shows it installed", state(B_UI)["helper"]["installed"])
    evs = sse(B_UI, "/api/helper/install", {})
    fs = fake_state(OLLAMA_B)
    check("4. asking again just sets it up again (the file isn't sent twice)",
          evs[-1]["type"] == "done" and len(fs["creates"]) == 2 and fs["pushes"].get(digest) == 1, json.dumps([evs[-1], fs["pushes"]]))

    # ---- 5: the Head check now runs on B's helper ----
    n0 = mark()
    evs = chat(A_UI, {"message": "make me a blue poster", "model": ""})
    gates = [c for c in since(n0) if c["job"] == "gate"]
    check("5. the Head check ran on B's hydra:1.0", gates and all(g["at"] == "B" and g["model"] == "hydra:1.0" for g in gates) and
          any(e["type"] == "plugin" for e in evs), str([(g["at"], g["model"]) for g in gates]))
    opts = [c for c in since(n0) if c["job"] == "options"]
    check("5. the Head's options were still read by an ordinary model", opts and all(not c["model"].startswith("hydra") for c in opts), str([(c["at"], c["model"]) for c in opts]))

    # ---- 6: a plan the helper gets wrong goes to the biggest model ----
    n0 = mark()
    rec, last = task("GARBLE: write two short paragraphs about oolong tea")
    planners = [c["model"] for c in since(n0) if c["job"] == "planner"]
    check("6. an unreadable plan from the helper is asked again, routed as before (not the helper)",
          last.get("type") == "done" and len(planners) == 2 and planners[0].startswith("hydra") and not planners[1].startswith("hydra")
          and rec.get("planner_model") == planners[1], "%s; planners %s" % (json.dumps(last)[:160], planners))

    # ---- 7: a review the helper gets wrong goes to the biggest model ----
    n0 = mark()
    rec, last = task("BADREVIEW: write a haiku about rooibos", loop=True)
    reviewers = [c["model"] for c in since(n0) if c["job"] == "reviewer"]
    check("7. an unreadable review from the helper is asked again, routed as before (not the helper)",
          last.get("type") == "done" and len(reviewers) == 2 and reviewers[0].startswith("hydra") and not reviewers[1].startswith("hydra")
          and rec.get("reviewer_model") == reviewers[1], "reviewer %s; reviewers %s" % (rec.get("reviewer_model"), reviewers))

    # ---- 8: a task too big for the helper plans on the biggest model ----
    n0 = mark()
    long_goal = "LONGGOAL Summarise these notes into a guide: " + ("Notes about tea harvesting and processing. " * 360)
    rec, last = task(long_goal)
    planners = [c["model"] for c in since(n0) if c["job"] == "planner"]
    check("8. a %d-character task plans on the biggest model, not the helper" % len(long_goal),
          last.get("type") == "done" and planners == ["big:70b"], str(planners))

    # ---- 9: nobody has the helper: planning goes back to the biggest model ----
    set_models(OLLAMA_A, [BIG])
    set_models(OLLAMA_B, [MID])
    wait_for(lambda: not any(m["name"].startswith("hydra") for d in state(A_UI)["network"]["devices"] for m in d.get("models") or []),
             "the hub forgetting hydra:1.0", 40)
    wait_for(lambda: not state(B_UI)["helper"]["offered"], "the host's offer gone", 30)
    n0 = mark()
    rec, last = task("Write a short guide to brewing white tea", loop=True)
    check("9. with no helper anywhere it plans on the biggest model and reviews as before",
          last.get("type") == "done" and rec.get("planner_model") == "big:70b" and rec.get("reviewer_model") in ("big:70b", "mid:14b"),
          "%s / %s" % (rec.get("planner_model"), rec.get("reviewer_model")))
    evs = sse(B_UI, "/api/helper/install", {})
    check("9. getting it from a host without it says so", evs[-1]["type"] == "error" and "doesn't have hydra:1.0" in evs[-1].get("error", ""), json.dumps(evs[-1]))

    # ---- 10: checking a long task's result (A runs its script, sandboxed; facts before the review) ----
    section10()
    section11()

    ok = all(r["ok"] for r in it.results)
    print("\n%d of %d checks passed" % (sum(r["ok"] for r in it.results), len(it.results)))
    return 0 if ok else 1


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        for p in reversed(it.procs):  # the worker before the hub
            try:
                os.killpg(os.getpgid(p.pid), 15)
                p.wait(timeout=15)
            except Exception:
                pass
        json.dump(it.results, open(os.path.join(WORK, "report.json"), "w"), indent=1)
        if FAKE:
            shutil.rmtree(FAKE, ignore_errors=True)
        if os.path.exists(ESCAPE):
            os.remove(ESCAPE)
    sys.exit(code)
