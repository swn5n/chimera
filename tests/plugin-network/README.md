# Plugin network test

Runs the plugin feature end to end on one computer: a host (A, also the one asking) and a worker (B) as
two real Chimera processes, a fake Ollama with one small model, and two demo plugins installed on B
only, so every plugin step has to cross the network.

```
cd ../../app && go build -o /tmp/chimera . && cd ../tests/plugin-network
python3 run_it.py /tmp/chimera /tmp/chimera-it
```

It checks (27 checks; exit code 0 when all pass): B's probe turns its plugins into tools; a chat message
with a picture picks the relevant plugin, runs it on B and the picture comes back and is saved with the
chat; the options come from the request through a model with structured output on B, and out-of-range
values are clamped; A lends its own already-loaded model too (so the hub would pick A as "the fastest"),
yet A's own Ollama gets no call during the Head jobs; inside the plugin the home folder and Chimera's data folder are hidden and the network is
blocked, even though the demo plugins' probes ask to read the folder that holds B's data folder and
the data folder itself (`DEMO_READ`; the worker refuses the second); a 1-star rating moves the choice to the other relevant plugin; cancelling stops the plugin's
process on B; a request no plugin fits gets a clear answer; and turning off "Let the network use my
plugins" on B stops it being used. It plants `~/chimera-it-secret.txt` for the sandbox check and removes
it afterwards. Uses ports 7571, 7572, 7580, 11555 and 11556 (A's own fake Ollama).

`heads_text_test.py` (16 checks, same arguments) does words-only Heads: a request to make something goes
to B's Head, a question stays a chat, and A's own Ollama stays idle for the Head job: the "should this
tool handle it?" check and the options run on B. Ports 7591, 7592, 7595, 7596, 11575 and 11576.

Safe to run beside a real Chimera: its own ports, data folders and a closed pool, and the worker is
stopped before the hub.

`hydra_test.py` (66 checks, same arguments) does Hydra 1.0, the helper model, with its own fake Ollamas
(`fake_ollama_hydra.py`, which says which model got which job): A hosts and lends big:70b and hydra:1.0, B lends
mid:14b and the demo-poster Head. A looping long task plans and reviews on hydra:1.0 and works and combines on the
other models; a chat never lands on it; B gets hydra:1.0 from the host (a 3 MB stand-in file, with the host's
template, parameters and licence) through `/api/helper/install`; the Head check runs on B's own model before and on
B's hydra:1.0 after (never on the asker); an unreadable plan or review is asked again without the helper; a task
too long for it plans on the biggest model; with no hydra:1.0 anywhere planning goes back to the biggest model.
Section 10 checks long tasks' results the way looping mode does, on the asker (A): a crash in the result's Blender
script skips the review and reaches the next round's planner as its critique (error, line, Blender version), and the
fix passes; the same crash twice stops, with a note on the saved reply; a write outside the sandbox
(`/var/tmp/chimera-check-escape.blend`, which must not exist afterwards), an object a fresh scene lacks and typed
input are "unsure" and go to the reviewer; a render ends the run cleanly; cancelling during the check leaves no
process behind; a plain Python script in a coding plan runs on A's own Python; with "check_results" off nothing runs.
A combine cut off at its output limit (done_reason "length") is another round with `num_predict` 8192 and the 32K
context, twice stops, and in single-pass mode it's a note on the saved reply. The fake Ollama picks plans and scripts
by goal markers: BLENDERCRASH, BLENDERSAME, BLENDERSAVE, BLENDERSCENE, BLENDERRENDER, BLENDERSLOW, CUTOFF, CUTALWAYS,
CUTONCE (a "blender" plan), PYCRASH, PYINPUT (a "code" plan); a later round's plan is "Studio v2" and its combine
writes that round's script. Its log also records each call's `num_ctx`, `num_predict` and the planner's critique.

`fake_blender/` is the Blender for section 10: `blender.py` (enough of `blender -b --factory-startup
--python-exit-code N --python-expr … --python script.py --`, reporting a failed script the way Blender 5 does), a
tiny `bpy/` and a `mathutils.py` without `radians`. The test copies it to a new `/var/tmp/chimera-fake-blender-*`
folder, writes an executable `blender` there (`#!<system python> -I`, then `blender.py`) and puts that folder first
on A's PATH only, so A finds "Blender 5.0.1". It can't stay in the repo: the script sandbox hides `/Users`. The
sandbox lets only the program and its `#!` interpreter (that path, its resolved path and its install prefix) run,
so the interpreter is the first of `/usr/local/bin/python3`, `/opt/homebrew/bin/python3`, `/usr/bin/python3` and
the test's own Python whose real path isn't under `/Users`, `/home`, `/tmp` or `/private/tmp`. The folder and the
escape file are removed when the test ends. On a computer that can't sandbox scripts (`can_test` false), 10.1 to
10.9 print SKIP and 10.10 doesn't check that round 2's script passed.
Ports 7611, 7612, 7615, 11591 and 11592. `hydra_ui_check.py` (needs Python Playwright) runs the same setup through
the interface: Models → Get from host on B, the chat picker without the helper, "Installed, shared" on the host,
and a looping task's card saying it planned and reviewed with hydra:1.0; screenshots land in the work folder.

`ui_check.py` does the same through the real interface in headless Chromium (needs Python Playwright):
attach a picture, send, the picture shows in the reply, 5 stars land on the plugin. Ports 7581, 7582,
7590, 11565.

`plugins_src/demo-shadow` is also the smallest example of a plugin: `plugin.json`, `run.py`, a probe.
Its `DEMO_READ` variable is only for this test.

`real_plugin_test.py` runs a real plugin the same way on one computer (two Chimera instances, a stub
Ollama): `CHIMERA_BIN=<chimera binary> PLUGINS_DIR=<folder holding the plugin> python3 real_plugin_test.py
<picture> "<request>" <outdir>`. It checks that the step ran on the worker, a PNG came back, the asker's
app serves it, a 5-star rating lands on the plugin and the worker ran it sandboxed (exit code 0 when all
pass). With Perspective on mac-lan it passed 10 of 10, the picture back in about 18 s.

Both tests stop their processes before they exit, so they can run one after the other.
