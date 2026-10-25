# Chimera

Personal app: "SheepIt for agents." Split the task, not the model. Each step runs whole on one node with a model (or a Head/tool) that fits. General-purpose, not Blender-specific (Blender is just one thing to test with).

Current version: **0.6.0** (Oct 24, 2026). All computers on the pool must run 0.6 (Heads protocol fields).

## Layout
- `app/` source (one Go program, stdlib only; HTML/CSS/JS UI embedded)
- `dist/` built, signed outputs (Chimera.app, Mac/Windows/Linux zips)
- `heads/` reference Heads: `TEMPLATE/`, `comfyui-image/`, `hunyuan3d-mesh/`, `README.md`
- `tests/` incl. `tests/plugin-network/` (`run_it.py`, `heads_text_test.py`), `tests/plugin-network/plugins_src/` (incl. `demo-poster`)
- `docs/` incl. `CHIMERA-PLUGINS-HANDOFF-0.5.0.md`
- `hydra1/README.md`, `README.md`

## Build and test
- Needs Go 1.24+ (`brew install go` if `go` isn't found). Build everything with `app/build.sh` (outputs to `dist/`, which is gitignored); run Go tests from `app/` with `go test ./...`.
- Cross-compiled: macOS arm64, Windows amd64 (GUI, embedded icon), Linux. macOS bundle gets a full ad-hoc signature (`codesign`, or `app/packaging/sign_macos.py` off-Mac).
- Last known-good 0.6.0 results: Go unit tests pass; `run_it.py` 25/25; `heads_text_test.py` 15/15; 3-device pool convergence; takeover of a 0.5.0 build.
- Go tests worth knowing: `TestLocalhostNetworkSandbox`, `TestPluginTermsWithAndWithoutInput`, `TestMeshFilesKeepTheirType`, `TestVersionLess`.
- Until now everything was verified from a Linux container. Real-Mac checks are the main reason to work in Claude Code (see "Not yet verified").

## Ports
- 7470 local UI (127.0.0.1)
- 7480 hub (host only)
- 7479 UDP discovery (needs SO_BROADCAST; on macOS also the Local Network permission)
- Devices only dial out. Heartbeat 3 s; long-poll `/v1/work`.

## Decided (from the user; don't relitigate)
- Lending is a manual Connected / Disconnected toggle (like SheepIt), no idle detection. Light use of the computer is fine while connected.
- Disconnecting mid-job offers "finish current step, then disconnect" and "stop now".
- Ollama must be running before a device can connect.
- General-purpose, not Blender-specific.
- Dark grey design using the chimera icon and logos.
- Download models from inside Chimera, picked to fit each device with headroom. Work out each device's context limits, model limits and installed tools.
- If nobody is lending, a chat runs on the user's own best model.
- Show what each device is best for and which waiting work it could help with.
- Long tasks get a system prompt telling each node it is one small piece of a larger project; the prompt varies by task type.
- Internal library of known-working mechanics, reused instead of calling models ("distilling ourselves"). 5-star rating after replies; 4-5 stars asks what worked; the network's largest GPU turns that into a central library entry. When spare compute is idle for a set time, test library entries for spam or mistakes; errors flag for the host.
- Web app, installable so it shows in the macOS Dock with the Chimera icon.
- Testing credits: everyone gets 1,000,000 starter credits; set back to 100 after testing. Going negative must actually limit you.
- Devices on the same Wi-Fi connect automatically (no code/IP sharing). A user's own devices auto-connect to help with their long tasks.
- Looping mode = iterate until done: parse (planner), sub-agents (workers), piece (combine), review, repeat.
- Open pool: anyone on any network can auto-join and contribute; credits (not codes) prevent freeloading. **Privacy is explicitly NOT a goal for now** ("ideally privacy is something we can do but for now lets just get it working"). Don't add encryption or privacy work unprompted.
- Tools are called **Heads** in the UI/docs (code, `plugin.json` and API keep `plugin`). A user's custom tool (e.g. the Perspective Blender plugin for studio shadows) should be called instead of an AI model when it does the job better. Rate Heads with the 5 stars. A Head owner whose tool gets called earns extra credits for bridging AI with deterministic techniques. Keep it open for future tools. Integrate other local AI models (mainly 3D mesh and picture generation) from the Nvidia PC.

## Architecture notes
- Routing: `need_caps` / `need_ctx` / `prefer`; context buckets 8K/32K/64K/128K; local fallback with a note. Stalled/offline steps retried elsewhere (3 tries).
- Long tasks (Hydra, `hydra.go`): biggest model plans 2-7 JSON steps, parallel workers (max 4) with per-kind prompts, verified library entries reused, biggest model combines, then reviews (`{done, score, critique}`) and re-plans up to 6 rounds.
- Hosting: open pools run `mergeLoop` (sweep discovery every 20 s; step down and join an outranking open host). `staleHubWatch` rejoins or re-enters `autoPool` when the hub is unreachable; "neither joined nor hosting" is never a resting state. `autoPool` order: pool address, LAN discovery, auto-host election.
- Updates: `takeOverOlder` makes a newer build quit an older running one via `/api/quit` (needs `X-Chimera: 1` header). On macOS, `handOverOnMac` (main.go) spawns a detached daemon (`CHIMERA_DAEMON=1`, Setsid) so a second double-click reaches `main` and opens the window. `CHIMERA_NO_DAEMON=1` disables; `CHIMERA_HANDOVER_TEST=1` is the Linux test hook.
- Heads: sandboxed worker, hub registry. Words-only Heads go through `headForText` / `runWordsOrHead` with `headGatePrompt` (`{"use": bool}`, temp 0); explicit model in the composer never uses a Head. Manifest fields: `accepts`, `optional_input`, `network: "localhost"`. macOS sandbox-exec; Linux bubblewrap or user+mount+net namespace (localhost Head gets the whole network there); Windows refuses unless the owner enables `unsandboxed_heads`.
- Credits: 1 credit = 1,000 output tokens from a reference ~8B model; weight = params/8 for larger; prompt tokens count 10%; Head steps 2 credits/min of worker time. Zero-sum between people; own devices free; library jobs free. Network mints: starter credits, Head run bonus `max(0.1, 50% of charge)`, Head star bonus 1.0 per 4-5 stars from someone else (`pluginBonusShare/pluginBonusMin/pluginStarBonus` in `hub_plugins.go`). Below 0 you can't send work to others' devices; soft floor at -50 also deprioritises.
- Library (`library.json`) and ledger (`hub.json`) live with the hosting computer; only the host (joined over loopback) is admin and runs scripts (opt-in, sandboxed). Chats are stored only on the sending computer.
- Catalog: 40 models, `NoMac` flag marks Nvidia/AMD-only. As of Oct 2026 Ollama image generation and TTS are Apple-only; image/3D generation on CUDA PCs lives in ComfyUI / Hunyuan3D / TRELLIS, i.e. Heads.

## Fleet
| Machine | Role |
|---|---|
| M3 Ultra, 96 GB (the Studio) | Planner, reviewer, synthesis; network host; Hunyuan3D / z-image / ACE-Step tools (`~/chimera-tools`) as Heads |
| M4 Max (mac-lan) | Second big head / coder; Perspective shadow Head (Blender 5.2.2). The Perspective Head source lives there, not in this repo |
| M4 Pro | Small parallel workers |
| Nvidia PC (RTX 3080 Ti laptop, 16 GB, Windows likely) | Fast worker; ComfyUI image-gen Head (needs the Windows unsandboxed-Heads opt-in) |
| AMD GPU | Worker; ROCm or Vulkan |

Studio install lineup (picks, ports, licences, swap variables) is a separate note; the install script has been tested on stubs only, never run on the Studio.

## Not yet verified (expect fixes)
1. 0.6 on real machines: Settings shows 0.6.0; double-click while running brings the window back; Local Network prompt still attributed to "Chimera" for the detached daemon; two Macs discover each other.
2. macOS sandbox profile on a real Mac (mac-lan reported Perspective running under it).
3. First real Head runs: Perspective over the network between two physical computers; ComfyUI Head on the Nvidia PC; Hunyuan3D Head on the Studio (`api_server.py --port 8080`). Reference Heads only ran against fake servers speaking the same APIs.
4. Cross-network: user still has to choose Tailscale (private) or Tailscale Funnel (public, no friend setup). `defaultPoolAddr` is still `""`.
5. Log for debugging: `~/Library/Application Support/Chimera/chimera.log`.

## Reminders
- **Starter credits are 1,000,000 for testing** (`starterCredits` in `app/hub.go`). Revert to 100 and bump `starterMigration` (same file) when testing ends. The open pool plus a Funnel address makes the 1M starter a meaningless brake.
- Never expose Ollama or the hub with a port-forward; traffic is unencrypted. Use Tailscale.

## Next
1. Retest 0.6 on the real machines (above).
2. First real Head runs (above).
3. Pick Tailscale vs Funnel; bake the Studio address into `defaultPoolAddr`.
4. Revert starter credits to 100.
5. Heads follow-ups: img2img ComfyUI Head (`optional_input`), long tasks calling Heads, several pictures per message, hash-pinned Head identity, a proper Windows sandbox (AppContainer), inline GLB/video viewers.
6. Later: encryption and prompt privacy from the host, Intel Mac build, maybe a native Mac window.
