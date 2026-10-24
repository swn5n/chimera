# Chimera source

One Go program (standard library only) plus a plain HTML/CSS/JS interface embedded in it.

## Files

| File | What it does |
|---|---|
| `main.go` | Startup, logging, `--hub-only` mode; single-instance check that **replaces an older running build** (asks it to quit via `/api/quit`, then takes the port) so updates take effect without the person quitting from Settings |
| `app.go` | Ties everything together; joining, hosting, settings; `autoPool` (zero-config: pool address → LAN discovery → auto-host election) |
| `config.go` | `config.json` in the data folder |
| `ollama.go` | Talks to the local Ollama (`/api/version`, `tags`, `show`, `ps`, `chat`, `pull`) |
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
| `runner.go` | Test-runs library scripts on the host (opt-in, sandboxed on macOS, no network on Linux) |
| `runprompt.go` | Sends a prompt to the network, or runs it on this computer's best model when nobody is lending |
| `hydra.go` | Long tasks: plan, run steps in parallel, reuse the library, combine; iterate-until-done loop with a review step |
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
- `POST /v1/steps` submits a prompt (`model`, `prefer` largest/fastest, `need_caps`, `need_ctx`, `format`, `purpose`); `GET /v1/steps/{id}/events` streams it back (server-sent events).
- Library: `GET /v1/library`, `GET /v1/library/{id}`, `POST /v1/library`, `POST /v1/library/{id}/review` (host), `POST /v1/library/{id}/used`, `POST /v1/feedback`, `GET /v1/library/export` (host), `POST /v1/admin/settings` (host).

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

## Testing without real models

Set `CHIMERA_SYSINFO` to a JSON file with a `SysInfo` to pretend to be other hardware, and point `--ollama` at a fake Ollama. Run a second copy on the same computer with `--data-dir /tmp/chimera2 --ui-port 7490 --no-open`.

## Building

`./build.sh` cross-compiles the Mac app (signed ad-hoc with `codesign`, or `packaging/sign_macos.py` elsewhere), the Windows exe (with `rsrc_windows_amd64.syso` for the icon) and Linux into `../dist`.
