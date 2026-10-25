# Chimera plugins handoff: Perspective studio shadows over the network

- **For:** the Chimera main project (the owner, and Claude on the main machine) to add plugins to the
  main app.
- **From:** the session on mac-lan (M4 Max, macOS 26.5), Oct 24, 2026, working from the Chimera 0.4.1
  source you sent (`chimera.zip`).
- **Goal:** another computer in a Chimera network sends a picture of a machine and asks for a shadow.
  The computer with Perspective (mac-lan) runs it, and the finished picture comes back to the asker.
- **Status:** built and tested on mac-lan, ready to merge. It has not yet been tried between two
  physical computers.

## In one minute

- **Chimera 0.5.0 adds plugins.** A plugin is a tool its owner installs on their own computer: a
  folder with `plugin.json` and an entry script. The network runs it for other people, and the files
  it makes come back into the asker's chat. Star ratings decide between plugins that could all do a job.
- **Perspective is packaged as the plugin `perspective-shadow`.** It drives Perspective's own batch
  runner in a background Blender, with no changes to Perspective.
- **Proven on mac-lan.** Two Chimera instances (one asking, one working) ran on mac-lan through a test
  hub. The SkyTrak 3042 picture came back as a 1080 x 1080 PNG about 18 s after sending, with 10 of
  10 checks passing. The run was repeated five times, the last with the shipped Mac build.
- **To ship:**
  1. Apply `chimera-0.5.0/chimera-plugins.patch` to the main app (it applies cleanly to 0.4.1) and
     build.
  2. Run 0.5.0 on every computer.
  3. Install the plugin on mac-lan and keep it Connected.

## 1. What's in the package

Everything is in `~/Desktop/chimera-plugins/` on mac-lan. Copy the whole folder to the main machine
(AirDrop or a USB stick is fine).

| Path | What it is |
|---|---|
| `CHIMERA-PLUGINS-HANDOFF.md` | This file |
| `INDEX.md` | Short index and plugin status table |
| `perspective-shadow/` | The plugin: `plugin.json`, `run.py`, the vendored Perspective 0.5.4 runtime files (`perspective/`), tests, README and licence |
| `chimera-0.5.0/CHANGES.md` | The full change description: design, decisions, tests and limits |
| `chimera-0.5.0/chimera-plugins.patch` | The change as a unified diff of `app/` against 0.4.1 (27 files) |
| `chimera-0.5.0/app/` | The patched source, the same as the patch applied to 0.4.1 |
| `chimera-0.5.0/tests/plugin-network/` | End-to-end tests: two real Chimera processes, a stub Ollama, demo plugins and a real-plugin test |
| `chimera-0.5.0/dist/` | 0.5.0 builds made with `build.sh`: `Chimera-mac.zip` (ad-hoc signed), `Chimera-windows.zip`, `Chimera-linux.tar.gz` |
| `test-runs/` | Logs, caches and outputs from the runs on mac-lan (about 620 MB, safe to delete) |

The installed Chimera on mac-lan (0.4.1, hosting "FX2's network") was not changed.

## 2. Add it to the main app

Run these from the project folder that holds `app/` (on the main machine, `~/Desktop/chimera`):

```sh
grep 'const Version' app/main.go        # expect 0.4.1, the base the patch was made against
patch -p1 --dry-run < /path/to/chimera-plugins/chimera-0.5.0/chimera-plugins.patch   # BSD patch: -C
patch -p1 < /path/to/chimera-plugins/chimera-0.5.0/chimera-plugins.patch
mkdir -p tests && cp -R /path/to/chimera-plugins/chimera-0.5.0/tests/plugin-network tests/
cd app && go vet ./... && go test ./...  # all pass; 17 of the tests are new
go build -o /tmp/chimera . && (cd ../tests/plugin-network && python3 run_it.py /tmp/chimera /tmp/chimera-it)
                                         # expect "25 of 25 checks passed"
./build.sh                               # dist/ for Mac, Windows and Linux
```

The patch was checked: applied to the 0.4.1 zip, it reproduces `chimera-0.5.0/app/` byte for byte.

- **If `app/` changed since 0.4.1 and the patch doesn't apply:** port it by hand using Appendix A. The
  four new files (`plugins.go`, `hub_plugins.go`, `plugin_chat.go`, `plugintest_cli.go`) drop in as
  they are. The existing files need small, local edits.
- **Release notes:** a paste-ready "New in 0.5" block for the top-level `README.md` is in Appendix C.
- **On mac-lan:** `run_it.py` is safe to run next to a real Chimera. It uses its own ports and data
  folders and a closed pool, and stops its worker before its hub.

## 3. Let another computer call it

### 3.1 Every computer: run 0.5.0

The host serves the new hub routes, the asker needs the new chat, and the worker needs the plugin
runner. With mixed versions, a 0.4.1 host refuses plugin steps, and a 0.4.1 computer can't attach a
picture or run plugins.

### 3.2 The computer that runs Perspective (mac-lan)

Already in place on mac-lan:
- Blender 5.2.2 (`/Applications/Blender 2.app`).
- Perspective's AI install in `~/Desktop/Perspective` (`ai_env/`, `models/`, plus `h3d/` for Accurate
  3D).

Steps:
1. Run Chimera 0.5.0 from `/Applications`. The 0.4.1 there now runs from a translocated download copy.
2. Settings > Plugins > **Open plugins folder**. That is
   `~/Library/Application Support/Chimera/plugins/`. Copy `perspective-shadow/` into it.
3. Within about a minute, Tools shows **Perspective studio shadow, Plugin 0.1.0**, and Settings >
   Plugins lists it with a lit dot. To check by hand:
   `python3 ~/Library/Application\ Support/Chimera/plugins/perspective-shadow/run.py --probe`
   should print `"have": true`.
4. Leave **Let the network use my plugins** on (the default) and press **Connect**. As with lending
   models, Ollama must be running with at least one shared model.
5. The first time Chimera runs the plugin, macOS may ask to let Chimera access the **Desktop** folder,
   because Perspective lives there. Allow it. With ad-hoc-signed builds it may ask again after an
   update. The way around that is to move Perspective out of Desktop/Documents/Downloads; see §12.

To try the plugin alone, exactly as a worker runs it (sandbox included), with no network:

```sh
python3 -c 'import base64,json,sys; print(json.dumps({"image":{"name":"p.png","data_base64":base64.b64encode(open(sys.argv[1],"rb").read()).decode()},"options":{"size":"square","square_px":512,"samples":32},"return":"files"}))' picture.png > /tmp/in.json
/Applications/Chimera.app/Contents/MacOS/chimera --plugin-test ~/Library/Application\ Support/Chimera/plugins/perspective-shadow --plugin-out /tmp/out < /tmp/in.json
```

### 3.3 The computer that asks

Use any 0.5.0 computer in the same pool. It doesn't need Blender or Perspective.
1. Open **Chat**, then press **+ Picture** (or paste or drop a picture): one PNG, JPEG or WebP, up
   to 25 MB.
2. Type what you want, for example *"put this on white with a soft studio shadow, light from the
   left"*, and press **Send**.
3. The reply says which plugin and computer are running it, with a progress bar ("On mac-lan: Reading
   the picture… (40%)"). Then the picture appears with its size and a **Save** link.
4. Rate it. The stars go to the plugin, and they decide which plugin is picked next time when several
   could do the job.

### 3.4 What to expect

All times are from mac-lan:

| Case | Time |
|---|---|
| A new picture, quick shadow, 1080 x 1080, 128 samples | ~16–20 s |
| The same picture again (analysis cached by its bytes) | a few seconds; 3.5 s at 512 px (not timed at 1080) |
| The very first run after installing (GPU kernels compile once) | ~1.5 min |
| `accurate_3d: true` on a new picture (Hunyuan3D model) | about 5 min more, 15–18 GB of memory |

- **Credits:** 2 credits per minute of the worker's time, measured by the hub, so about 0.5 for a
  quick shadow. Your own computers are free.
- **Step timeout:** 30 minutes (the plugin's `timeout_s`).

### 3.5 Checklist for the first two-computer test

1. Both computers run 0.5.0 and are in one pool. Settings shows "Chimera 0.5.0".
2. On mac-lan, Tools shows the plugin, and the computer is Connected.
3. On the asking computer's Network tab, mac-lan shows as lending.
4. Send a picture and a request from the other computer. The picture comes back.
5. On the asking computer's Library tab, **Perspective studio shadow** shows as *Plugin*, *Verified*
   after its first run. Its stars show once rated.
6. mac-lan's `~/Library/Application Support/Chimera/chimera.log` has a line `plugin
   perspective-shadow finished in …s (sandboxed: no network, home folder hidden except the plugin's
   own folders)`.

## 4. How it works

### 4.1 The flow

```
asker's app (0.5.0)              hub (host)                         worker (mac-lan)
 Chat: picture + words
 GET /v1/plugins?q=&accepts= ─▶  relevant plugins on online
                              ◀─ devices, best rated first
 model fills the plugin's        (an ordinary chat step, structured output = the plugin's options schema)
 options from the words
 POST /v1/steps                ─▶ queue; route only to devices
 {kind:run_plugin, plugin,        with tool plugin:<id>            ◀─ GET /v1/work (long poll)
  input}                          Assignment{plugin,input} ───────▶  run entry in sandbox
                                                                     stdin: input JSON, argv[1]: out dir
 SSE /v1/steps/{id}/events     ◀─ status {reason,fraction}      ◀── POST /progress {status,fraction} (1–6 s apart)
   status… file… done          ◀─ delta (summary), file events  ◀── POST /complete {stats, files[base64]}
 save files with the chat;        record the run; charge time;
 show them; rating → plugin       verify the plugin's entry
```

If nobody else can run it but the asker's own computer has the plugin, it runs there without the hub.

### 4.2 A computer's plugins: finding, probing, advertising (`plugins.go`, `tools.go`)

- **Where it looks:** every folder with a `plugin.json` in the data folder's `plugins/`, plus the
  folders listed in `CHIMERA_PLUGINS`. Plugin code is never received over the network.
- **Checks:** the manifest is validated. The id must match `^[a-z0-9][a-z0-9-]{1,47}$`, and the entry
  must be inside the folder. `timeout_s` is clamped to 30–7200 and defaults to 1800.
- **The probe:** the tool scan (every 60 s) runs `<entry> --probe`, unsandboxed and at most once per
  10 minutes per unchanged manifest. It answers whether the plugin can run here, which capabilities it
  has, and which folders it reads. A plugin that can run becomes the tool `plugin:<id>`.
- **Advertising:** the device's heartbeat carries each plugin's `PluginInfo` (name, summary, when to
  use, tags, accepted and produced types, options schema, capabilities) and `lend_plugins`.
- **No sandbox, no plugins:** on a computer that can't sandbox (Windows, or Linux without bwrap or
  unshare), plugins show as unable to run and aren't offered.

### 4.3 Choosing a plugin (`hub_plugins.go`: `pluginCandidatesLocked`, `GET /v1/plugins`)

Candidates are plugins on devices that are online, lending, not draining and have Ollama running. The
device must lend plugins, or belong to the asker, and its tool `plugin:<id>` must be ready. Then:

- **Relevance:** the request's words (minus stop words and generic words like *picture*, *image*,
  *photo*, *add*) are matched against the plugin. A hit in the name or id scores 3, in the tags or task
  kinds 2.5, in the summary 1.5, and in "when to use" 1. The total divided by 6, capped at 1, is the
  relevance. When the request has words left after that, a plugin needs at least **0.25**. A picture
  with no such words (no text, or only words like "add this picture") makes every plugin that accepts
  it a candidate, so the best rated one is picked. `when_not_to_use` is not matched.
- **Input type:** the plugin must accept the picture's type (wildcards like `image/*` work). A plugin
  that needs an input file is skipped when there is none, and flagged plugins are skipped.
- **Order:** best rating first, using **(stars + 3.5 × 2) / (ratings + 2)**, so one lucky 5 doesn't
  beat a long record of 4s. Ties go to relevance, then uses, then id. The asker takes the first.
- **Fallback:** if the hub can't be reached or has no candidate, the asker uses a plugin installed on
  its own computer, picked by relevance.

### 4.4 Options from the request (`plugin_chat.go`: `pluginOptions`, `cleanOptions`)

When the plugin has an options schema and the request has words, the app sends a small chat step: the
fastest model, temperature 0, `format` set to the plugin's schema. Only options the schema knows are
kept. Values are type-checked and checked against the enum, numbers are clamped to minimum and maximum,
and integers are rounded. The reply shows a note such as "Options from your request: style left." If
anything fails, the plugin uses its defaults and says so.

### 4.5 Routing and running a step (`hub.go`, `node.go`, `plugins.go`: `runPlugin`)

- **Submitting:** `POST /v1/steps` with `kind: "run_plugin"`, `plugin` and `input` (at most 48 MB).
  `target` and `private` work as they do for chats.
- **Picking a device (`fits`):** the device must have the plugin, lend plugins (or belong to the
  asker), and have the capabilities in `need_caps`. The asker's own computers score higher, and so do
  idle ones. The step's `RunModel` shows the plugin's name.
- **Running (`runPluginStep`):** the worker runs the entry with its interpreter (`python3 -E -s` by
  default, or `sh`). It forwards the plugin's progress as `status`, at most once a second and every
  5–6 s even when the plugin is quiet, so the hub's 30 s stall check never fires during a long render.
- **Cancel:** SIGTERM goes to the plugin's whole process group, which gets 20 s to stop. When it ends,
  whatever it left running is killed. That holds on macOS and in the Linux namespace sandbox. Under
  bwrap (not tested here) the plugin runs in its own session, so expect it to be killed at once.
- **Results:** a success completes with its files. Problems with the computer (not installed here, the
  sandbox didn't start, a timeout) fail as *retryable*, so the hub tries another device (3 tries in
  all). A bad input fails for good.

### 4.6 The sandbox (`plugins.go`: `macPluginSandboxProfile`, `linuxPluginSandbox`)

**macOS** (`sandbox-exec`), as generated for each run:

```
(version 1)
(allow default)
(deny network*)
(deny file-read* (subpath "/Users") (subpath "/Volumes") (subpath "/private/var/root"))
(allow file-read* (subpath <plugin folder>) (subpath <each read path from --probe>)
                  (subpath <interpreter's install>) (subpath <run folder>) (subpath <plugin cache>))
(deny file-read* (subpath <Chimera's data folder>))
(allow file-read* (subpath <plugin folder, when installed there>) (subpath <run folder>) (subpath <plugin cache>))
(allow file-read-metadata (literal <each folder above those>))
(deny file-write*)
(allow file-write* (subpath <run folder>) (subpath <plugin cache>) (subpath "/private/var/folders")
                   (subpath "/private/tmp") (literal "/dev/null") (regex #"^/dev/tty") (regex #"^/dev/fd/"))
(deny file-write* (subpath <Chimera's data folder>))
(allow file-write* (subpath <run folder>) (subpath <plugin cache>))
```

- **Later rules win, and the data folder comes last.** Chimera's data folder holds `config.json` (the
  network token), the chats and their files, other plugins and, on the host, the library and ledger.
  It is hidden after the plugin's read paths are allowed, so it stays hidden even when a read path
  contains it, and wherever it lives (including a `--data-dir` outside the home folder). Only the
  plugin's own folder, the step's run folder and the cache inside it come back.
- **Read paths must be specific.** A probe's read path is ignored if it is `/`, `/Users`, `/home`,
  `/root`, `/Volumes`, any home folder (a folder directly in `/Users` or `/home`, which includes
  `/Users/Shared`) or a folder above one, or if it is in Chimera's data folder outside the plugin's own
  folder. The log says `plugins: <id>: not letting it read <path> (too broad)` or `(inside Chimera's
  data folder)`.
- **Why the `file-read-metadata` line:** without it, Blender crashed inside Apple's Metal framework on
  mac-lan. Metal calls `realpath()` on its GPU-kernel cache, which needs to stat `/Users` and
  `/Users/<you>`. The rule lets the parent folders be stat-ed but not listed or read.
- **Linux:** bubblewrap (`bwrapArgs`): read-only root; empty `/home`, `/root` and `/tmp`; read paths
  bound read-only; then the data folder emptied; then the plugin's folder in it bound back read-only and
  the run and cache folders writable. **Install bubblewrap on Linux workers.** Without it, Chimera falls
  back, as 0.4.1's library test runs do, to a user/mount/network namespace. That blocks the network and
  hides the home folders and the data folder in the same order (if it can't hide the data folder, the
  plugin doesn't run), but the rest of the file system stays as writable as it is for your user,
  `/tmp` and `/var/tmp` included.
- **Folders:** each run gets `<data>/plugin-runs/<id>-…/out`, deleted afterwards. The cache,
  `<data>/plugin-cache/<id>/`, is kept between runs.
- **Environment:** a bare one: `HOME`, `PATH`, `TMPDIR`, `LANG`, the variables the manifest lists in
  `env` (never `CHIMERA_*`), plus `CHIMERA_OUT`, `CHIMERA_CACHE`, `CHIMERA_BLENDER` and `CHIMERA_STEP`.
- **Checked on macOS 26.5:** inside the sandbox, a file outside the plugin's folders was unreadable and
  the network was blocked. The same plugin unsandboxed could do both. `config.json` stayed unreadable
  with the data folder in `/tmp` and in the home folder, including when the probe named a folder that
  contains it or `config.json` itself, and through the `/System/Volumes/Data/Users/…` path. Probes
  asking for the whole home folder, another user's home folder or `/Users/Shared` were refused. The
  same checks pass on Linux with the namespace sandbox.

### 4.7 Files coming back

- **Collecting:** the worker takes the files the plugin listed, or else every regular file at the top
  of the output folder. Each file may be up to 32 MB, and all of them together up to 64 MB. Links are
  resolved, and anything outside the output folder is refused. The type comes from the bytes, and PNG,
  JPEG and WebP sizes are read.
- **Sending:** they go base64 in `POST /v1/steps/{id}/complete`. The hub emits a `file` event for each,
  replays them to an asker who reconnects, and drops them with the step 10 minutes after it finishes.
- **Saving:** the asker keeps only types in the plugin's `produces` and saves them in
  `<data>/sessions/files/<chat>/<random id>`. The chat message records `files`, `plugin` and `step_id`.
- **Serving:** `GET /api/files/<chat>/<id>` (127.0.0.1 only) shows only PNG, JPEG, WebP and GIF
  inline. Anything else downloads, under `Content-Security-Policy: default-src 'none'; sandbox` and
  `nosniff`, so a file from someone else's computer can never run as a page in your Chimera.

### 4.8 Ratings and the library (`hub_plugins.go`, `library.go`)

- **One entry per plugin:** each plugin gets one library entry with `kind: "plugin"`, created when a
  device that has it sends a heartbeat. It holds no code, only the description and when to use it.
- **Verification:** the first successful run for someone that returns a file **verifies** it, never a
  model review.
- **Ratings:** a rating counts only for a finished `run_plugin` step that the rater asked for, once per
  step. The hub keeps the last 2,000 such steps in `library.json` (`plugin_runs`). After 3 or more
  ratings averaging under 2 stars, the plugin is **flagged** for the host and no longer picked. The
  host's **Check again** clears the flag and makes the entry wait for its next run, so it can be picked
  again; while its average stays under 2, the next rating flags it again.
- **New versions:** a newer version keeps its ratings but must be verified again. Only the owner who
  first brought a plugin can rewrite its entry.
- **Caps:** a device may advertise at most 32 plugins, and the library keeps at most 200 plugin
  entries.
- **Separation from other library work:** plugin entries never reach long tasks as text, never get
  curated, and can't be added by hand.

### 4.9 Credits

A plugin step costs 2 credits per minute, using the smaller of the time the worker reports and the
time the hub saw between handing the step out and its end. Your own devices are free. A cancelled step
costs nothing, and plugin steps don't count as demand for models.

### 4.10 Interface (`web/`)

- **Chat:** **+ Picture**, paste or drop adds one picture to a message. Your message shows the picture.
  The reply shows plugin progress, then the returned pictures with name, size and **Save**. Rating
  confirms *"It counts toward the plugin's rating."* A picture with Long task on is refused with a
  message.
- **Settings > Plugins:** the **Let the network use my plugins** switch, the plugins found here, and
  **Open plugins folder**.
- **Tools:** one row per plugin.
- **Library:** plugin entries show *Plugin* and *★ average (count)*.

### 4.11 Settings, flags and environment

| | |
|---|---|
| `lend_plugins` (config, `/api/settings`) | let the network use this computer's plugins; on by default |
| `CHIMERA_PLUGINS` | extra plugin folders (a path list of plugin folders or folders of them) |
| `chimera --plugin-test <folder> [--plugin-out dir] < input.json` | run a plugin once exactly as a worker would, then exit |
| `<data>/plugins/` | where plugins are installed (Mac: `~/Library/Application Support/Chimera/plugins`) |
| `<data>/plugin-cache/<id>/` | a plugin's cache (Perspective keeps analyses and 3D models there) |

- **Newest Blender:** on macOS, Chimera now picks the newest `Blender*.app` in `/Applications` or
  `~/Applications`, by its Info.plist. mac-lan has 4.5.4 as `Blender.app` and 5.2.2 as
  `Blender 2.app`, and 0.4.1 used to pick 4.5.4.

## 5. The Perspective plugin (`perspective-shadow/`)

What `run.py` does (Python 3.8+, standard library only):

1. **Read the input.** It takes the picture as base64: PNG, JPEG or WebP, at most 40 MB and
   50 megapixels. Path inputs are refused unless `CHIMERA_PLUGIN_ALLOW_PATHS=1`, so a network request
   can never make it read a local file. Odd option values fall back to the default with a note, unless
   `"strict": true`.
2. **Find what it needs.** The Perspective install comes from `PERSPECTIVE_HOME`, or by default
   `~/Desktop/Perspective` (`ai_env/perspective_ai.json`, `h3d/perspective_h3d.json`). Blender is the
   newest 5.0+ among `CHIMERA_BLENDER`, `/Applications/Blender*.app`, `~/Applications/Blender*.app` and
   PATH.
3. **Run Perspective's own batch runner.** It writes the picture into its cache, keyed by the SHA-256
   of its bytes, so a picture sent again isn't analysed again. Then it writes a job and runs
   `Blender -b --factory-startup --python perspective/batch.py -- job.json`. That reads the picture with
   Perspective's AI models: BiRefNet cut-out, MoGe-2 depth, and Hunyuan3D 2.1 when `accurate_3d` is on.
   Then it builds the shadow scene and renders the chosen versions. The models load offline
   (`HF_HUB_OFFLINE`) from Perspective's own `models/` folder, which the sandbox lets it read but not
   change; other runtime caches go in the plugin cache.
4. **Report.** Perspective's progress lines become progress events, with a heartbeat after 4 s
   without one. The PNGs move to the output folder, and the result JSON gives the summary, the files (name,
   size, SHA-256), which stand-in cast the shadow (`relief` or `3d_model`), notes and the time per
   phase.

Options:

| Option | Values | Default |
|---|---|---|
| `style` | soft, match, overhead, left, right, back, contact | soft |
| `darkness` | 0.1–1 | 0.7 |
| `softness` | 0.3–3 (higher = softer edges) | 1 |
| `length` | 0.3–2 (how far the shadow runs) | 0.6 |
| `size` | square, same (picture's own framing), custom | square |
| `square_px`, `width`, `height` | 64–4096 | 1080, 1920, 1080 |
| `machine_size` | 0.2–1 (share of the frame) | 0.8 |
| `background` | `#rrggbb`, white, black, grey | white |
| `outputs` | background, transparent, shadow_only | background |
| `remove_background` | true / false | true |
| `accurate_3d` | true / false (about 5 min more) | **false** |
| `samples` | 16–1024 | 128 |

- **Outputs:** `<name>_shadow.png` (on the background), `<name>_shadow_transparent.png` and
  `<name>_shadow_only.png`.
- **Exit codes:** 0 done, 1 failed, 2 bad input, 3 not installed here.
- **Requirements:** macOS, Blender 5.0+, Perspective's AI install, and memory: 8 GB for the quick
  shadow, about 18 GB with Accurate 3D.
- **Vendored code:** `perspective/` holds Perspective 0.5.4's `batch.py`, `core.py`,
  `worker_moge.py`, `worker_h3d.py`, `shape_fit.py` and `h3d_compat.py`, unchanged. Their checksums
  are in `SHA256SUMS` and the version is in `VERSION`.
- **Moving to a newer Perspective:** copy those six files from `addon_src/perspective/`, update
  `VERSION` and `SHA256SUMS`, run the test and bump `version` in `plugin.json`.
- **Licence:** GPL-3.0-or-later, like Perspective. Hunyuan3D 2.1, used only with `accurate_3d`, has a
  community licence that excludes the EU, the UK and South Korea, which is why `accurate_3d` is off by
  default.
- **Test:** `python3 tests/run_test.py case-01` renders a synthetic loader
  (`tests/fixtures/loader.png`, made by `tests/make_fixture.py`) at 512 px and checks the PNGs.
  A clean white border is allowed a few pixels right at the frame's corners, as Perspective's own
  checks note. On mac-lan it passes in 8 s once warm. The very first run took 99 s while the GPU
  kernels compiled.

## 6. Writing another plugin

The smallest working example is `chimera-0.5.0/tests/plugin-network/plugins_src/demo-shadow/`.

`plugin.json`:

| Field | Meaning |
|---|---|
| `id` | `^[a-z0-9][a-z0-9-]{1,47}$`, unique in the network |
| `name`, `version`, `summary` | shown to people; the name (weighted most) and summary are also matched against requests |
| `when_to_use`, `tags`, `task_kinds` | matched against requests, so keep them concrete |
| `when_not_to_use` | shown in the plugin's library entry ("Not for: …"); not used for matching |
| `accepts`, `produces` | MIME types (wildcards allowed); `accepts` is what the asker's picture must be |
| `entry`, `interpreter` | the script inside the folder; `python3` (default) or `sh` |
| `options` | a JSON schema object, used both to have a model fill options and to clean them |
| `env` | environment variables passed through to the plugin |
| `timeout_s` | 30–7200, default 1800 |

The entry script follows this contract:

| | |
|---|---|
| stdin | one JSON object: `{"image": {"name", "data_base64"}, "options": {…}, "request": "the words", "return": "files"}` |
| argv[1] / `CHIMERA_OUT` | the output folder; write the finished files there |
| stdout | the last JSON line: `{"ok": true, "summary": "…", "files": [{"path": "a.png"}]}` or `{"ok": false, "error": "…", "retryable": true}` |
| stderr | progress, one JSON line each: `{"event": "progress", "fraction": 0.4, "message": "…"}` |
| exit | 0 done, 1 failed, 2 bad input, 3 not installed on this computer |
| `--probe` | `{"have": true, "caps": [...], "missing": [...], "sandbox": {"read": [absolute folders it needs]}}` |
| `CHIMERA_CACHE` | a folder kept between runs |

## 7. Security model

- **What crosses the network is data, not code.** Plugin code is installed by the computer's owner.
  What arrives from the network is the asker's picture and options going in, and the worker's files
  coming back.
- **The plugin runs sandboxed (§4.6).** That limits even a plugin that is fed a hostile input.
- **Chimera's own data is never readable by a plugin.** Its network token, chats and other plugins
  stay hidden whatever folders the plugin's probe asks for. A probe can't ask for anything in the data
  folder outside the plugin's own folder, nor for `/` or a home folder.
- **The probe runs unsandboxed,** like any program the owner installs. It never sees anything from the
  network, but it is the plugin's own code, so only install plugins you trust.
- **Chimera handles returned files as untrusted.** It collects only regular files inside the output
  folder after resolving links, after killing anything the plugin left running. The asker keeps only
  declared types, and the local app never serves them as a page.
- **Ratings, routing and charges can't be forged from outside.** Ratings must come from the person
  who asked, for a real run, once. Charges use the hub's clock. Library entries are capped, and only
  their owner can rewrite them.
- **An independent review of the change found five problems, all fixed and covered by tests:**
  forged ratings, a symlinked-folder escape from the sandbox, library-entry flooding and rewriting,
  worker-reported time setting the charge, and picture links pointing at the wrong chat while a reply
  was still arriving.
- **Found afterwards, also fixed and tested:** Chimera's data folder was readable from a plugin when
  it lived outside the home folder, when a folder the probe named contained it, and when the probe
  named a path inside it; and another user's home folder could be named as a read path. The first came
  to light once the demo plugin's data-folder check was corrected; it had been looking at the wrong
  path and passing without testing anything. The second came from reviewing that fix. The last two
  came from an independent fact-check of this document against the code.
- **Linux without bubblewrap** is weaker: see §4.6.
- **Open:** a plugin's identity is its id. As with model names today, nothing proves a device
  advertising `perspective-shadow` runs the real one. Pinning plugins by a hash of their files is the
  next step.

## 8. Tests

| Test | Where | Result |
|---|---|---|
| `go vet ./...` (Mac and Linux; also `GOOS=windows`) and `go test ./...` | `app/` | pass; 17 new tests: ranking, not lent, flagged by bad ratings, verified by first run, option cleaning, manifest checks, files stay in the output folder, symlinked folders refused, the macOS profile (data folder hidden after a read folder that contains it), files served safely, ratings need a real run, entry ownership and caps, charge follows the hub's clock, picture sizes, newest Blender first, read paths must be specific and outside the data folder, bwrap mount order |
| `run_it.py`: two Chimera processes, stub Ollama, two demo plugins | `tests/plugin-network/` | 25 of 25 on Linux, and on mac-lan with the shipped Mac build (`dist/Chimera-mac.zip`). Covers routing to the worker, the picture back and saved, options from words, clamping, sandbox (home hidden, data folder hidden even though the plugins' probes ask to read the folder holding it and the data folder itself, which the worker refuses, network blocked), a 1-star rating switching plugins, cancel stopping the plugin's process, no plugin fitting, and lending switched off |
| `ui_check.py`: the real interface in headless Chromium (needs Playwright) | `tests/plugin-network/` | pass: attach, send, picture shows, 5 stars land on the plugin, settings and library show correctly |
| `--plugin-test` with the demo plugin, in the real sandboxes | mac-lan (`sandbox-exec`) and Linux (namespace) | pass with the data folder in `/tmp` and in the home folder, and the probe naming nothing, `/tmp`, the folder holding the data folder, or (refused) `config.json` itself, the data folder, the whole home folder, another user's home folder or `/Users/Shared`: home hidden, data folder hidden, network blocked, `config.json` untouched |
| `--plugin-test` with Perspective, shipped Mac build | mac-lan | pass in 8–10 s: two 512 px PNGs |
| `real_plugin_test.py`: a real plugin through two instances on one computer | `tests/plugin-network/` | with Perspective on mac-lan: 10 of 10 five times, the last with the shipped Mac build straight after `run_it.py` |
| `perspective-shadow/tests/run_test.py case-01` | the plugin | pass on mac-lan |

## 9. What was done (work log)

1. **Read the 0.4.1 app and the source.** Perspective couldn't ride on the existing `blender` library
   entries. The script pre-filter refuses `subprocess` and file writes, the script sandbox hides
   `/Users` (where Perspective and its AI environments live), and step results could only be text.
2. **Packaged Perspective as a plugin.** `run.py` drives Perspective's own batch runner. The six
   runtime files are vendored unchanged, checked against the 0.5.4 release zip.
3. **Built plugin support as 0.5.0.** It covers the hub registry and search, `run_plugin` routing, the
   sandboxed worker runner, files over the protocol, picture attach and display, plugin library
   entries and ratings, and `--plugin-test`.
4. **Tested off the Mac:** unit tests, the two-process network test and the headless UI test.
5. **On mac-lan:**
   - The probe found Blender 5.2.2 and Perspective's AI on the Apple GPU.
   - The direct plugin test passed.
   - In Chimera's real sandbox, Blender crashed inside Metal. Fixed with the parent-folder stat rule,
     after which it rendered the same picture as the unsandboxed run (identical pixels on the
     background version; 4 of 262,144 pixels one level apart on the shadow-only one).
   - The sandbox boundary was confirmed.
   - Chimera would have used the old Blender 4.5.4. Fixed by picking the newest.
   - The full network run passed 10 of 10.
6. **Independent review:** five fixes (§7), then everything was re-run.
7. **Hardening:** the demo plugin's data-folder check had been looking at the wrong path. Corrected, it
   showed Chimera's data folder was readable when it lived outside the home folder. Reviewing that fix
   found it was also readable when a read path contained it. Both are fixed in all three sandboxes
   (§4.6), too-broad read paths are refused, and everything was re-verified on Linux (25 of 25) and on
   mac-lan (the demo plugin in four layouts, Perspective's `--plugin-test` and the network run).
   An independent fact-check of this document against the code then found that a probe could still
   name a path inside the data folder or another user's home folder, and some wording that didn't
   match the code (now corrected). Both code gaps were fixed and everything on mac-lan was run again
   with the shipped Mac build.
8. **Packaged:** the patch (verified to apply to 0.4.1 and reproduce `app/`), builds and checksums.
   Everything on the Desktop was checked against the tested files.

## 10. Decisions (the open questions from the earlier handoff)

- **Generated files** travel with the step result. They are not stored with library entries.
- **Visibility.** Plugins are library entries, picked by relevance then rating. The hub API can run one
  by id. The chat interface has no "pick a plugin by name" yet.
- **Plugins calling models:** no. A plugin is pure script, and the asker's app uses a model to fill the
  plugin's options.
- **I/O convention:** as in §6.
- **The earlier handoff said not to modify the Chimera app.** The owner then asked for the network to
  call the plugin, so 0.5.0 changes the app, delivered as a patch for the main project to merge.

## 11. Not done yet

- **Text-only plugins.** A plugin is only considered when a message comes with a picture. Text-only
  plugins need a "should a plugin handle this?" check first, so plugins don't take over ordinary chats.
- **Long tasks (Hydra)** don't call plugins yet.
- **One picture per message.**
- **Accurate 3D isn't routed by capability.** A device without it makes the quick shadow and says so.
- **Plugin-only computers.** Lending (models or plugins) needs Ollama running, so a computer that only
  runs plugins would need Connect and the lending loop relaxed.
- **Plugin identity.** Pin plugins by a hash of their files (§7).
- **Sandboxing the probe.** It runs unsandboxed today (§7). It could run with no network and no writes.
- **Linux without bubblewrap.** The fallback leaves the file system outside the home folders writable
  (§4.6). Requiring bwrap, or remounting the root read-only in the fallback, would close that.
- **Files in hub memory.** The hub holds a step's files in memory (up to 64 MB) for 10 minutes after it
  finishes.
- **Two physical computers, and cross-network.** Not tried yet. Over Tailscale it uses the same
  protocol as the rest of Chimera.
- **Option parsing with a real model.** The tests used a stub model, so check option parsing with a
  real one.
- **Library test runs.** The library test-run sandbox (`runner.go`) has the same shape. If a Blender
  kept in `~/Applications` fails there, the same parent-folder stat rule should fix it.

## 12. Troubleshooting

| Symptom | Look at |
|---|---|
| The plugin isn't in Tools | `python3 <plugin>/run.py --probe` (its `missing` says why); the plugin folder has `plugin.json` at its top; wait for the next tool scan (60 s) |
| "No plugin in the network can do that with a picture yet" | the worker is Connected (Ollama running), "Let the network use my plugins" is on, both run 0.5.0, the words match the plugin (try "shadow") |
| Fails with "needs Blender 5.0 or later" | a 5.x `Blender*.app` in `/Applications`; the probe shows which Blender it found |
| Blender crash inside the sandbox | the run log `<data>/plugin-cache/perspective-shadow/jobs/<time>/run.log`, `$TMPDIR/blender.crash.txt`, and `log show --last 10m --predicate 'eventMessage CONTAINS "Sandbox: Blender("'` |
| macOS keeps asking about the Desktop folder | move `~/Desktop/Perspective` out of Desktop/Documents/Downloads, set the add-on's Home preference to the new folder, and make `PERSPECTIVE_HOME` visible to Chimera (`launchctl setenv PERSPECTIVE_HOME <folder>` before opening it) |
| A plugin can't read a folder it needs | its probe must list the folder in `sandbox.read`; `/`, a home folder, anything above one, and anything in Chimera's data folder outside the plugin's own folder are refused (log: `not letting it read …`) |
| Worker logs | `~/Library/Application Support/Chimera/chimera.log` (lines starting `plugin`, `Running a step`, `Finished the`) |
| The cache grows | `<data>/plugin-cache/perspective-shadow/` (analyses and 3D models; safe to delete) |

## Appendix A. File-by-file changes (to port by hand)

New files:
- **`plugins.go`:** the manifest and limits; `pluginDirs`, `readManifest`, `scanPlugins` and
  `probePlugin`; `PluginInfos`; `pluginEnv`; `runPlugin`, the sandboxed run with progress, timeout,
  cancel and process-group kill; `collectPluginFiles`; `sniffMIME` and `imageSize`;
  `pluginReadPaths` (read paths must be specific); `pluginSandboxed`, `macPluginSandboxProfile`,
  `ancestors`, `within` and `outside`, `linuxPluginSandbox` and `bwrapArgs`.
- **`hub_plugins.go`:** the caps; `pluginRun`; `PluginCandidate`; `syncPluginEntriesLocked`;
  `pluginStepDoneLocked`; `ratePluginLocked`; `pluginRating`; `pluginTerms` and `pluginRelevance`;
  `acceptsType`; `pluginCandidatesLocked`; `handlePlugins` (`GET /v1/plugins`).
- **`plugin_chat.go`:** `GenManager.runPlugin`, `App.runPluginChat`, `runPluginHere`, `choosePlugin`,
  `localPluginCandidates`, `pluginOptions`, `cleanOptions` and `cleanValue`.
- **`plugintest_cli.go`:** `runPluginTest`, for `--plugin-test`.
- **Tests:** `plugins_test.go` and `blender_test.go`.

Changed files:
- **`hub.go`:**
  - `hubDevice.lendPlugins` and `plugin()`.
  - `hubEvent.Fraction` and `.File`; `hubStep.Plugin`, `Input`, `Files`, `StatusMsg` and `Fraction`.
  - Routes: adds `GET /v1/plugins`.
  - Heartbeat: takes `lend_plugins`, caps plugins at 32 and syncs plugin entries.
  - `fits`: a `run_plugin` branch.
  - `assignLocked`: plugin name as `RunModel`, no model demand.
  - `Assignment.Plugin` and `.Input`.
  - `progressReq.Status` and `.Fraction`, which emit `status`.
  - `completeReq.Files`, validated, which emit `file`.
  - `submitReq.Kind`, `Plugin` and `Input`, with validation and no demand for plugins.
  - `runnableLocked`: plugin messages.
  - `replayLocked`: status and files.
  - `requeueLocked`: clears plugin state.
  - `finishLocked`: calls `pluginStepDoneLocked`.
  - `chargeLocked`: time-based, by the hub's clock.
- **`node.go`:** the heartbeat sends `LendPlugins`; `runStep` adds a `run_plugin` branch, and adds
  models to `usedModels` only for chat steps. New: `runPluginStep`.
- **`chat.go`:**
  - `genEvent` gains `Plugin`, `Fraction`, `File` and the internal `raw`.
  - `generation` gains plugin, status and files.
  - `chatReq.Images` and `decodeChatImage`.
  - `Start` saves the picture and takes the plugin path.
  - `emit` and `Subscribe` handle `plugin`, `status` and `file`.
  - `saveResult` stores `Files`, `Plugin` and `StepID`.
- **`sessions.go`:** `SessionMessage` gains `Files`, `Plugin` and `StepID`; adds `SessionFile`,
  `SaveFile`, `FilePath` and `cleanFileName`; `Delete` removes a chat's files.
- **`api.go`:** `/api/open-folder` takes `{which: "plugins"}`; adds `fileRoutes` (`GET /api/files/…`);
  a larger chat body limit for pictures; the `lend_plugins` setting.
- **`api_more.go`:** `sendFeedback` sends `kind: plugin` and `step_id`, and skips local runs.
- **`library.go`:**
  - `LibEntry` gains `Plugin`, `Version`, `Stars` and `Rated`; adds `library.PluginRuns`.
  - `normalizeKind` turns a hand-added "plugin" into a lesson.
  - "Check again" handles plugins.
  - `feedbackReq` gains `Plugin` and `StepID`; `handleFeedback` gains the plugin rating path.
  - `libraryTickLocked` skips plugins.
- **`hydra.go`:** `librarySearch` leaves out plugin entries.
- **`tools.go`:** `ToolScanner.plugins`; `scan` calls `scanPlugins`; `List` adds one tool per plugin;
  `findBlender` picks the newest `.app`; adds `bundleVersion`.
- **Smaller changes:**
  - `profile.go`: `DeviceProfile.Plugins`.
  - `config.go`: `LendPlugins`, on by default through `PluginsInit`.
  - `state.go`: `SettingsView.LendPlugins`.
  - `hubclient.go`: `Status`, `CompleteWithFiles` and `Plugins`.
  - `runprompt.go`: `followStep` passes `Fraction` and the file through.
  - `main.go`: version 0.5.0, and the `--plugin-test` and `--plugin-out` flags.
  - `exec_unix.go` and `exec_windows.go`: `newProcessGroup`, `terminateGroup` and `killGroup`.
- **`web/`:**
  - `index.html`: an attachments row, **+ Picture** and a file input.
  - `app.js`: picture attach by button, paste or drop; `filesHTML` and `fileURL`; live `plugin`,
    `status` and `file` events; the progress bar; the rating text; Settings > Plugins; plugin library
    entries with stars.
  - `app.css`: styles for those.
- **`README.md` (app):** the files table, protocol lines and a Plugins section.

## Appendix B. API reference

Hub (port 7480, token auth as before):
- `GET /v1/plugins?q=<words>&accepts=<mime>&limit=10[&all=1]` returns
  `{"plugins": [{id, name, version, summary, when_to_use, accepts, produces, caps, options, devices,
  relevance, rating, rated, score, uses, entry_id, status}]}`.
- `POST /v1/steps` with `{"kind": "run_plugin", "plugin": "<id>", "input": {…}, "target": "",
  "private": false, "purpose": "Plugin: …"}` returns `{"id", "status"}`.
- **Worker poll:** `GET /v1/work` returns
  `{"step_id", "kind": "run_plugin", "model": "<plugin name>", "plugin", "input", "purpose",
  "requester", "requester_device"}`.
- **Status:** `POST /v1/steps/{id}/progress` with `{"status": "…", "fraction": 0.4}` (the summary text
  goes as `{"content": "…"}`) returns `{"cancel": bool}`.
- **Completion:** `POST /v1/steps/{id}/complete` with
  `{"stats": {"total_duration": ns}, "files": [{"name", "mime", "bytes", "sha256", "width", "height",
  "data": "<base64>"}]}`.
- **Events (SSE `/v1/steps/{id}/events`):** `assigned`, `status {reason, fraction}`,
  `delta {content}`, `file {file}`, `done {credits, free}`, `error`, `cancelled`, `requeued`.
- **Rating:** `POST /v1/feedback` with
  `{"rating", "note", "prompt", "response", "model", "kind": "plugin", "plugin", "step_id"}`.
- **Heartbeat:** carries `"lend_plugins": bool`, `profile.plugins: [PluginInfo]` and
  `profile.tools: [{id: "plugin:<id>", have, lendable, …}]`.

Local app (127.0.0.1:7470):
- `POST /api/chat` with `{"session_id", "message", "model", "target", "private",
  "images": [{"name", "data": "<base64>"}]}` streams events, including `plugin`,
  `status {reason, fraction}` and `file {file: {id, name, mime, bytes, width, height}}`.
- `GET /api/files/{chat}/{file}`.
- `POST /api/settings` with `{"lend_plugins": bool}`.
- `POST /api/open-folder` with `{"which": "plugins"}`.

## Appendix C. Paste-ready release notes for the top-level README

```markdown
## New in 0.5

- **Plugins: tools the network can call.** Install a plugin on your computer (Settings → Plugins →
  Open plugins folder, then drop its folder in) and anyone in the pool can use it: attach a picture in
  Chat (**+ Picture**, or paste or drop it), say what you want, and the result comes back into your
  chat with a Save link. The first plugin is **Perspective studio shadow**: send a picture of a machine
  and get it back on white with a realistic shadow, rendered in Blender on the computer that has
  Perspective.
- **Ratings pick the plugin.** If several plugins could do a job, Chimera uses the best-rated one.
  Rate the result and your stars count toward that plugin.
- **Plugins run sandboxed.** No network, your home folder and Chimera's own data hidden except the
  plugin's own folders, writes only to a throwaway folder (on Linux, install bubblewrap for that). Turn
  lending plugins off under Settings → Plugins.
- Chimera now uses the newest Blender on a Mac with more than one installed.
```
