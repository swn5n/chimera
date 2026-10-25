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
