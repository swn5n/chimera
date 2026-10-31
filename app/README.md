# Chimera source

One Go program (standard library only) plus a plain HTML/CSS/JS interface embedded in it.

## Files

| File | What it does |
|---|---|
| `main.go` | Startup, logging, `--hub-only` / `--plugin-test` / `--check-result` modes (`--check-result <reply.md or script.py> [--check-goal <text>]` checks a result the way looping mode does and prints the verdict as JSON; exit 0 passed, 1 the script crashed, 2 anything else); on macOS hands over to a detached copy of itself so opening the app again brings the window back (`handOverOnMac`); single-instance check that **replaces an older running build** (asks it to quit via `/api/quit`, then takes the port) so updates take effect without the person quitting from Settings |
| `app.go` | Ties everything together; joining, hosting, settings; `autoPool` (zero-config: pool address → LAN discovery → auto-host election) |
| `config.go` | `config.json` in the data folder |
| `ollama.go` | Talks to the local Ollama (`/api/version`, `tags`, `show`, `ps`, `chat`, `pull`, and `blobs` + `create` to set up the helper model) |
| `ollama_monitor.go` | Watches Ollama; models, capabilities, architecture (KV cache size, experts), what's loaded |
| `profile.go` | Usable memory, fit (comfortable, tight, too big), context limits, speed estimates, measured speeds (`perf.json`), "best for" |
| `catalog.go` | Curated Ollama models, rated for this computer, best pick per role |
| `tools.go` | Detects vision, audio, image/video/3D/audio generation, Blender, ComfyUI, ffmpeg, Whisper, Python |
| `launch.go` | Opens Ollama and the interface window on macOS, Windows, Linux |
| `node.go` | This computer in the network: heartbeats, Connected/Disconnected lending, running steps, library test runs, auto-help |
| `hub.go` | The hub: members, matching steps to devices, streaming replies back, credits, demand tracking, auto-join |
| `discovery.go` | UDP LAN discovery: host answers probes; devices find hosts and auto-join (no code/IP typed). `enableBroadcast` (SO_BROADCAST) is required or the OS silently drops the broadcast probes |
| `sockopt_unix.go`, `sockopt_windows.go` | Per-platform `enableBroadcast`: sets `SO_BROADCAST` on the discovery socket |
| `library.go` | The hub's library: entries, ratings, curation, review, idle checks, test runs, export |
| `runner.go` | Runs untrusted Python and Blender scripts in a sandbox: library test runs on the host (opt-in, with the `riskyScript` pre-filter) and the check of a looping long task's result on the asker. macOS profile: no network, home folder hidden, writes only in a throwaway folder, no other programs, no forking, no signals to other processes, no Apple Events; Linux: bubblewrap. A `/bin/sh` watchdog kills the run if the app dies |
| `hydra_check.go` | Looping mode's facts-before-opinions check: picks the Blender or Python script in a round's result, runs it here (`check_results`, default on), and a definite crash (or a combine cut off at its output limit, from `done_reason`) means not done: the review is skipped and the error is the next round's critique. Anything uncertain leaves it to the reviewer. Also the `--check-result` command (`checkresult_cli.go`) |
| `plugins.go` | Plugins installed on this computer: finding and probing them, running a plugin step in its sandbox, collecting the files it makes |
| `hub_plugins.go` | The hub's view of the network's plugins: one library entry per plugin, star ratings, and the search that picks a plugin (relevant ones, best rated first) |
| `plugin_chat.go` | A chat message with a picture: pick a plugin, turn the request into its options with a model, run it (on the network or here) and save the pictures it returns |
| `runprompt.go` | Sends a prompt to the network, or runs it on this computer's best model when nobody is lending |
| `hydra.go` | Long tasks: plan, run steps in parallel, reuse the library, combine; iterate-until-done loop with a check (`hydra_check.go`) and a review step; a later round that fails keeps the previous round's result. The plan and the review prefer the helper model and ask again without it when its answer can't be read |
| `helper.go` | Hydra 1.0, the helper model (`hydra:1.0`): its name, the size limit for what goes to it (the 8K context bucket), and the rule that it only plans, reviews and does the Head check |
| `helper_share.go` | Getting the helper onto every computer from the host: the host finds its Ollama's copy and serves it (`/v1/helper`), a member pushes it into its own Ollama (`/api/blobs`, `/api/create`); the Models page's "Get from host" |
| `prompts.go` | System prompts: planner, per-kind worker rules, combiner, curator, reviewer |
| `hubclient.go` | HTTP client for the hub |
| `chat.go`, `sessions.go` | Chats, stored on the computer that sent them |
| `api.go`, `api_more.go`, `state.go` | The local API the interface uses (127.0.0.1 only) |
| `sysinfo.go` | Chip, memory and GPU (NVIDIA through nvidia-smi, AMD through the registry on Windows and amdgpu on Linux) |
| `web/` | The interface (Archivo font, OFL licence in `web/fonts`) |
| `packaging/` | Icons, Info.plist, icon generator, `sign_macos.py` (ad-hoc bundle signing when `codesign` isn't available) |

## Fit and context

Usable memory: Macs get 67% of RAM (75% at 48 GB and up), GPUs their VRAM minus 0.5 GB, otherwise half the RAM. A model needs its weights, compute buffers (0.3 GB + 2%) and KV cache (`layers × kv heads × (key + value dims) × 2 bytes` per token, read from `/api/show`). Comfortable means the model plus an 8K context fits in 70% of usable memory; tight means it fits under 97%; past that it's too big and isn't lent. Each model's context limit is the largest power of two that fits. Steps ask for context in buckets (8K, 32K, 64K, 128K) so Ollama doesn't reload models for every prompt.

## Network protocol (hub, port 7480)

Devices only make outgoing requests, so nobody but the host opens a port.

- `POST /v1/join` with the invite code returns a device token. A device that joins over loopback is the hosting computer: only it gets admin rights.
- `POST /v1/heartbeat` every 3 s: lending state, shared models (with fit and context limits), hardware profile and tools. Returns the network snapshot, including demand and library counts.
- `GET /v1/work?wait=25` long-polls for a step to run (only while Connected).
- `POST /v1/steps/{id}/progress`, `/complete`, `/fail` stream a reply back. `fail` with `retryable` hands the step to another device.
- `POST /v1/steps` submits a prompt (`model`, `prefer` largest/fastest, `prefer_model`, `need_caps`, `need_ctx`, `format`, `purpose`); `GET /v1/steps/{id}/events` streams it back (server-sent events). `prefer_model` (0.7.0, the helper's three jobs): a device that has that model gets the step ahead of all others, the one that answers soonest first (a free one that hasn't polled yet gets up to 3 s; a busy one isn't waited for); with none, `prefer` decides. Older hubs ignore it. Outside those jobs the hub never picks the helper.
- Helper model: the snapshot's `network.helper` says the host hands out its helper model (name, size). `GET /v1/helper` gives its digest, template, parameters and licence; `GET /v1/helper/model` streams the file (two devices at a time).
- Library: `GET /v1/library`, `GET /v1/library/{id}`, `POST /v1/library`, `POST /v1/library/{id}/review` (host), `POST /v1/library/{id}/used`, `POST /v1/feedback`, `GET /v1/library/export` (host), `POST /v1/admin/settings` (host).
- Plugins: `GET /v1/plugins?q=…&accepts=image/png` lists the plugins online devices would run for you, relevant ones only, best rated first. `POST /v1/steps` with `kind: "run_plugin"`, `plugin` and `input` runs one; the worker sends `status` and `fraction` on `/progress`, and `files` (base64) on `/complete`, which reach the requester as `status` and `file` events. A rating with `plugin` set (`POST /v1/feedback`) goes to that plugin's library entry.

A step that gets no progress for 30 s, or whose device goes offline, is retried on another device (3 tries max). Library jobs queue behind people's requests and are free.

## Joining the pool with no setup (`autoPool`)

On launch a device that isn't already in a network and isn't hosting runs `autoPool` (skippable with `CHIMERA_NO_AUTOPOOL=1`, which scripted tests set so they can drive host/join themselves). It is a bounded retry loop so no device is ever left orphaned:

1. **Pool address** — if `pool_addr` is set (or `defaultPoolAddr` is baked in), join that hub directly. This is the only path that works across different networks, so point it at a hub reachable from anywhere — e.g. the Studio over Tailscale (`100.x.x.x:7480`). Open pools accept this code-less.
2. **LAN discovery** — otherwise broadcast for a host on the local network and auto-join a single one found.
3. **Auto-host election** — if nobody is hosting, wait a random moment and look again, then host the pool itself (`startHostingWith(elected=true)`). A device that loses the host-port race loops back and joins the winner instead.

**Open hosts merge (`mergeLoop`).** Every hub started by `startHostingWith` — whether the person clicked Host, hosting was restored from settings, or auto-pool elected it — runs a `mergeLoop` while it is an *open* pool: first after 3 s, then every 20 s, it sweeps discovery; if it finds another open host that `outranks` it, it steps down and joins that one (on a failed join it resumes hosting rather than sit orphaned). Ranking (`hostStanding`, advertised in the discovery reply): a host a person chose beats an auto-elected one; then more devices online; then up longer; then the smaller hub id as a strict tie-break, so both sides always agree. Closed (code-required) hosts never merge in either direction. This is what stops two people who both clicked Host on the same Wi-Fi from sitting in two islands — the exact v0.4.0 failure — and folds in a laptop that wakes up later. `pickMergeTarget` + `outranks` are unit-tested (`election_test.go`).

**Stale hub recovery (`staleHubWatch`).** A joined, non-hosting device whose hub has been unreachable for ~1 minute (4 × 15 s ticks, 90 s cooldown) runs `rejoinSomewhere`: the pool address, then the best open host on the Wi-Fi (never its current address); failing both it leaves the dead network and re-enters `autoPool`, which stands up a new pool so the remaining devices aren't stranded. When the original host returns, `mergeLoop` folds them back together (chosen beats elected, so a Studio restored from settings wins over a laptop that re-hosted meanwhile).

**Open pool (cross-network, any device joins).** When a hub's auto-join is on it is an *open pool*: `POST /v1/join` is accepted with no invite code (`hub.go` handleJoin). Credits, not codes, stop freeloading — a device that's out of credits can't submit to others (402). Privacy is deliberately not a goal yet; the aim is that anyone, on any network, lands in the pool and contributes. Toggle it live from settings (`/api/settings` `auto_join`, which calls `hub.SetAutoJoin`).

Discovery runs over UDP on `7479`: the host answers `CHIMERA-DISCOVER/1` probes with its name, port and (when auto-join is on) the invite code, so a device can join with nothing typed. `hubBase` accepts a full URL too, defaulting to 443 for `https://` so a Tailscale Funnel address works as a pool address. The discovery socket **must** set `SO_BROADCAST` (`enableBroadcast`) or the OS drops the broadcast probes — the symptom is two devices on the same Wi-Fi never seeing each other.

**macOS Local Network permission.** The first time Chimera sends a discovery broadcast, macOS prompts for Local Network access. If that prompt is dismissed or denied, discovery stays silently broken even with `SO_BROADCAST` set — this is the usual real-world reason two Macs don't find each other. Allow it under System Settings → Privacy & Security → Local Network. (Cross-network via a pool address / Tailscale doesn't use broadcast and isn't affected.)

`starterCredits` is set to 1,000,000 for testing (a one-time top-up via `starterMigration` bumps existing owners) — set it back to 100 and bump `starterMigration` for real use. Out of credits, a device can't submit to others' machines (402); its own stay free. Library review and run jobs are host-only; curation can run on any big model.

## Heads (plugins)

In the interface and docs a plugin is a **Head** — a tool installed on one computer that the whole pool can call; the code, manifest (`plugin.json`) and API keep the word `plugin`. A Head is a folder with a `plugin.json` and an entry script that a person installs on their own computer, in the data folder's `plugins/` (Settings → Heads → Open heads folder) or a folder listed in `CHIMERA_PLUGINS`. Head code never comes from the network. Each tool scan runs `<entry> --probe`; a Head that can run here becomes the tool `plugin:<id>`, and its manifest (name, summary, when to use, accepted input types, `optional_input`, options schema) travels in the heartbeat. Reference Heads and a template live in `../heads/`.

- **Picking one, with a picture.** A chat message with a picture asks the hub for Heads (`/v1/plugins`): only those relevant to the words (name, tags, summary, when to use; generic words like "picture" don't count) and able to take the picture, then **the best rated first** (average stars pulled toward 3.5 until a Head has a few ratings, so one lucky 5 doesn't win). A model then fills the Head's options from the request with structured output (`format` = the Head's schema), and the app keeps only options the schema allows.
- **Picking one, from words alone (0.6).** A message with no picture and "Best available" as the model goes through `headForText` (`plugin_chat.go`): the hub lists Heads that need no picture (empty `accepts`, or `optional_input`) and match the words — here "image"/"picture" *do* count (`pluginTerms(q, withInput=false)`) — and then the fastest model is asked, with the Head's description, *should this tool handle the request?* (`headGate`, structured `{"use": bool}`, temperature 0). Yes → the Head runs (the step input simply has no `image`); no → an ordinary chat. With no model reachable, only a relevance ≥ 0.75 counts. Choosing a specific model in the composer skips Heads. `tests/plugin-network/heads_text_test.py` covers: a "make me a poster" routes to the Head, "what is a poster?" doesn't, an explicit model is respected, the gate was asked.
- **Running it.** `run_plugin` steps go only to devices with the Head whose owner lends Heads (Settings → Heads, on by default), or to the asker's own devices. The worker runs the entry in a sandbox like library test runs (macOS `sandbox-exec`; Linux `bwrap`, or without it a namespace that hides the home folders and the data folder and blocks the network but leaves the rest of the file system as writable as it is for you, so install bubblewrap on Linux workers): no network; the home folder hidden except the Head's folder and the read paths its probe names (specific folders only: never `/`, a home folder or a folder above one, and nothing in Chimera's data folder outside the Head's own folder); Chimera's data folder (its network token, chats, other Heads) hidden even inside those, apart from the Head's own folder, the step's run folder and its cache; writes only to the step's output folder, the Head's cache (`plugin-cache/<id>`) and the system temp folders. Its stdout is a JSON result, its stderr JSON progress lines; files are read from the output folder, never from paths outside it.
- **`"network": "localhost"` (0.6).** A Head that wraps a server on the same computer (ComfyUI, a Hunyuan3D API server) declares it; `pluginSandboxed(…, localNet)` then allows loopback only on macOS (`(allow network* (remote ip "localhost:*"))` after the `(deny network*)`), and on Linux shares the network namespace (`bwrap --share-net`, or `unshare -rm` instead of `-rnm`) — which is the whole network there, so the log line says so. Unit-tested in `TestLocalhostNetworkSandbox`.
- **Credits (0.6).** A Head step charges the asker 2 credits a minute of the worker's time (hub clock), and on top the network mints the Head's owner a **run bonus** of half that charge, never less than 0.1 per run for someone else (`pluginBonusMin`), and a **star bonus** of 1 credit each time someone else rates the result 4–5 stars (`pluginStarBonus`, paid to the worker recorded for that run). Own devices stay free and earn nothing.
- **Coming back.** The hub keeps the files with the step for its 10 minutes after finishing and sends them as `file` events; the requester keeps only the types the Head said it `produces`, judged with `sniffMIME` (so a `.glb`, octet-stream by bytes, still counts as `model/gltf-binary`), saves them with the chat (`sessions/files/<chat>/`), served at `/api/files/<chat>/<file>` (images inline, everything else as a download).
- **The library.** Each Head gets a library entry (kind `plugin`, shown as *Head*) that collects star ratings and uses. It's verified by its first successful run for someone that returns a file (a new version proves itself again), never by LLM review, and a Head that keeps getting 1–2 stars is flagged for the host. Head entries never reach long tasks as text.

The contract an entry script follows is at the top of `plugins.go` and in `../heads/README.md`. `../tests/plugin-network/` runs a hub and a worker with demo Heads and a fake Ollama end to end (`run_it.py`: pictures; `heads_text_test.py`: words only, localhost network, bonuses).

## Testing without real models

Set `CHIMERA_SYSINFO` to a JSON file with a `SysInfo` to pretend to be other hardware, and point `--ollama` at a fake Ollama. Run a second copy on the same computer with `--data-dir /tmp/chimera2 --ui-port 7490 --no-open`.

## Building

`./build.sh` cross-compiles the Mac app (signed ad-hoc with `codesign`, or `packaging/sign_macos.py` elsewhere), the Windows exe (with `rsrc_windows_amd64.syso` for the icon) and Linux into `../dist`.
