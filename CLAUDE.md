# Chimera

Personal app: "SheepIt for agents." Split the task, not the model. Each step runs whole on one node with a model (or a Head/tool) that fits. General-purpose, not Blender-specific (Blender is just one thing to test with).

Current version: **0.6.1** (Oct 25, 2026; 0.6.0 was Oct 24). All computers on the pool must run 0.6.1: from 0.6.1 the computer running a Head reads its options, and the hub honours `not_here`. A 0.6.0 worker runs such Heads on their defaults, and the hub says so in the reply. Update the hub host and the Head computers first. Not enforced in code: `hubProto` (app/hub.go) is still 1, so a 0.5 device can still join. To bump the version, change `const Version` in app/main.go (build.sh fills in Info.plist) plus the README.md title.

## Layout
- `app/` source (one Go program, stdlib only; HTML/CSS/JS UI embedded). `app/headkit/run.py` is the runner every Head maker Head gets (embedded, copied into the Head's folder on each save).
- `dist/` build outputs, gitignored: `Chimera.app` (ad-hoc signed), `Chimera-mac.zip`, `Chimera-windows.zip`, `Chimera-linux.tar.gz` (amd64)
- `heads/` reference Heads: `TEMPLATE/`, `comfyui-image/`, `hunyuan3d-mesh/`, `README.md`, `MAKE-A-HEAD.md` (the no-code guide for users). Source only; build.sh doesn't ship them. Install a Head by copying its folder into `~/Library/Application Support/Chimera/plugins/` or listing it in `CHIMERA_PLUGINS`.
- `tests/` incl. `tests/plugin-network/` (`run_it.py`, `heads_text_test.py`, `ui_check.py` (needs Playwright), `real_plugin_test.py` (written for Perspective on mac-lan)), `tests/plugin-network/plugins_src/` (incl. `demo-poster`)
- `docs/` incl. `CHIMERA-PLUGINS-HANDOFF-0.5.0.md`, `chimera-3d-head-handoff.md` (Hunyuan3D mesh Head, for mac-lan), `chimera-dev-notes-1.txt` (the user's idea list)
- `scripts/chimera-studio-install.sh` (Studio install lineup, see Fleet)
- `hydra1/README.md`, `README.md`
- Root: brand assets (`chimera_icon.png`, logo PNGs/PSD; `app/packaging/make_icons.py` regenerates the icons). `Claude outputs/` is gitignored, holding old builds from the Co-Work chat; not current.

## Build and test
- Needs Go 1.24+. The Studio has Go 1.27 from Homebrew (`/opt/homebrew/bin/go`; add it to PATH if `go` isn't found). Go 1.27 binaries need macOS 13+, which Info.plist now says. Build everything with `app/build.sh`; run Go tests from `app/` with `go test ./...`.
- Cross-compiled: macOS arm64, Windows amd64 (GUI, embedded icon), Linux amd64. macOS bundle gets a full ad-hoc signature (`codesign`, or `app/packaging/sign_macos.py` off-Mac).
- End-to-end tests: `cd app && go build -o <tmp>/chimera .`, then from `tests/plugin-network/`: `python3 run_it.py <tmp>/chimera <tmp>/chimera-it` and `python3 heads_text_test.py <tmp>/chimera <tmp>/chimera-ht`. Use a darwin build, never `dist/linux/chimera`. Each takes about a minute (give Bash a long timeout; macOS has no `timeout` command).
- Test instances aren't fully isolated from the real pool: they bind the real UDP discovery port 7479, and `staleHubWatch`/`rejoinSomewhere` ignore `CHIMERA_NO_AUTOPOOL`, so a leftover test worker whose hub dies can join a real open pool on the LAN. Don't run them while (re)starting the Studio's real Chimera, and kill leftovers after an interrupted run.
- Last known-good, on the Studio (macOS 26.2), Oct 25 2026, 0.6.1 plus the Head maker: Go tests 36/36; `run_it.py` 27/27 and `heads_text_test.py` 16/16, with Head steps under real `sandbox-exec`. In both, A (the asker) lends its own already-loaded model on its own fake Ollama, and the tests check that it gets no call during Head jobs. The 0.6.0 build fails exactly those checks. 0.5.0's sandbox and `run_it.py` also passed on mac-lan. Only in the Linux container, ad hoc with no checked-in script: 3-device pool convergence and takeover of a 0.5.0 build (`CHIMERA_HANDOVER_TEST` is read by main.go but no test sets it).
- Go tests worth knowing: `TestLocalhostNetworkSandbox`, `TestMacPluginSandboxProfile`, `TestPluginTermsWithAndWithoutInput`, `TestMeshFilesKeepTheirType`, `TestVersionLess`. All Go tests are string/HTTP-recorder checks; none runs `sandbox-exec` for real.

## Ports
- 7470 local UI (127.0.0.1; falls back to 7471-7474, `--ui-port`)
- 7480 hub (host only, all interfaces, `--hub-port`)
- 7479 UDP discovery (needs SO_BROADCAST; on macOS also the Local Network permission)
- Ollama at 127.0.0.1:11434 (`$OLLAMA_HOST` / `--ollama`)
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
- Heads run off the computer that hosts them and just return results to the asker via the chat. The asker's own computer (its GPU) is used for Head work only when the Head is its own (installed there). Applies to all future Heads.

## Architecture notes
- Routing: `need_caps` / `need_ctx` / `prefer`; context buckets 8K/32K/64K/128K; local fallback with a note. Stalled/offline steps retried elsewhere (3 tries).
- Long tasks (Hydra, `hydra.go`): biggest model plans 2-7 JSON steps, parallel workers (max 4) with per-kind prompts, verified library entries reused, biggest model combines. Only in looping mode ("Keep going until done", off by default) does it then review (`{done, score, critique}`) and re-plan, up to 6 passes (`hydraMaxRounds`). `score` is unused, and a non-integer score fails the parse and ends the loop as if done.
- Hosting: open pools run `mergeLoop` (sweep discovery every 20 s; step down and join an outranking open host). `staleHubWatch` rejoins or re-enters `autoPool` when the hub is unreachable; "neither joined nor hosting" is never a resting state. `autoPool` order: pool address, LAN discovery (joins only if exactly one open host answers), auto-host election. Known gap: after about a minute without its pool-address hub, a device auto-hosts and never retries the pool address (Hosting persists across relaunch).
- Updates: `takeOverOlder` makes a newer build quit an older running one via `/api/quit` (needs `X-Chimera: 1` header). On macOS, `handOverOnMac` (main.go) spawns a detached daemon (`CHIMERA_DAEMON=1`, Setsid) so a second double-click reaches `main` and opens the window. `CHIMERA_NO_DAEMON=1` disables; `--no-open` also skips the handover (tests use it; use it to keep Chimera in the foreground from a terminal). `CHIMERA_HANDOVER_TEST=1` is the Linux test hook.
- Heads: sandboxed worker, hub registry. A message with a picture always goes to a Head (`choosePlugin`), whatever model is picked. Words-only messages with "Best available" go through `headForText` / `runWordsOrHead` with `headGatePrompt` (`{"use": bool}`, temp 0); an explicit model skips Heads for words-only messages. Manifest fields: `accepts`, `optional_input`, `network: "localhost"`. macOS sandbox-exec; Linux bubblewrap or user+mount+net namespace (localhost Head gets the whole network there). Where no sandbox exists (always on Windows; Linux without bwrap/unshare), Heads are refused unless the owner enables `unsandboxed_heads`. A Head's `--probe` runs unsandboxed everywhere; only step runs are sandboxed.
- Head work stays off the asker (0.6.1): the asker sends a `run_plugin` input with no `options` key. The computer running the Head fills them in (`withPluginOptions`, plugin_chat.go) with the model that answers soonest (`eta`). That's a *shared* model, or any model for its owner's own steps. It unloads that model afterwards if nothing was using it (`modelInUse` asks Ollama live; `ChatStreamKeep` with `keep_alive` "0s"), sends the "Options from your request" line back as a step `note` (cleared on requeue), and counts the time in the Head charge.
- The words-only gate is submitted with `not_here` unless the Head runs on the asker (`headRunsHere`: installed *and* its probe passes). With `not_here`, the hub excludes the asking device and `runPrompt` never falls back to local. If no other computer takes the gate within 8 s (`gateWaitElsewhere`), the word-match rule decides. An input that already has `options` (from an older build) is run as it is; a pre-0.6.1 worker gets a hub note instead (`optionsOnWorkerSince`).
- Head maker (`headmaker.go`, Settings → Heads → Make a Head): a form makes a Head with no code, of kind `program` (a command line, run without a shell, with `{{input}} {{prompt}} {{out}} {{name}} {{cache}} {{blender}} {{seed}}` and settings) or `server` (an HTTP call to 127.0.0.1 only, JSON template, `{{input_base64}}`/`{{input_data_url}}` or multipart upload, result found by itself or via `result_field`). The answers live in plugin.json's `maker` block; `headkit/run.py` reads them. Only Heads with a `maker` block can be changed in the form (`POST /api/heads` with `replace`, bumps the patch version). `POST /api/heads/{id}/try` runs any Head installed here once (re-probes, options read by a local model, the real sandbox) and streams SSE; files are kept in `head-tries/<id>/`. Tried for real on the Studio under sandbox-exec with `say`, Blender 5.2 (user add-ons load), `cp` and a fake local server; never yet against rembg, A1111 or a real Hunyuan3D server.
- **Known bug (macOS):** a `network: "localhost"` Head gets the whole network (internet, LAN). `(allow network* (local ip "localhost:*"))` in `macPluginSandboxProfile` (app/plugins.go) also matches outbound connects. Splitting it into `network-outbound (remote ip ...)` plus `network-bind network-inbound (local ip ...)` fixed it in direct sandbox-exec tests. `TestLocalhostNetworkSandbox` only string-matches, and `heads_text_test.py` prints "Internet: OPEN" without failing.
- Credits: 1 credit = 1,000 output tokens from a reference ~8B model; weight = total params/8 for larger (MoE models are charged by total, not active, params); prompt tokens count 10%; Head steps 2 credits/min of worker time (capped by the hub's own clock). Zero-sum between people; own devices free; library jobs free. Network mints: starter credits, Head run bonus `max(0.1, 50% of charge)`, Head star bonus 1.0 per 4-5 stars from someone else (`pluginBonusShare/pluginBonusMin/pluginStarBonus` in `hub_plugins.go`). Below 0 the hub refuses (402) any submission that could use others' devices; only "Only my devices" work goes through. The check runs at submit, so in-flight steps can push a balance lower; the -50 soft floor only moves your queued steps behind everyone else's.
- Library (`library.json`) and ledger (`hub.json`) live with the hosting computer; only the host (joined over loopback) is admin and runs scripts (opt-in, sandboxed). Chats are stored only on the sending computer, except rated replies: their prompt and response go to the host's `library.json` (`feedback`, last 500) for curation.
- Catalog (`catalog.go`): 40 models; `NoMac` marks Nvidia/AMD/CPU-only, `MacOnly` marks Apple-only. As of Oct 2026 Ollama image generation and TTS are Apple-only; image/3D generation on CUDA PCs lives in ComfyUI / Hunyuan3D / TRELLIS, i.e. Heads.

## Fleet
| Machine | Role |
|---|---|
| M3 Ultra, 96 GB (the Studio; this Claude Code project runs here) | Planner, reviewer, synthesis; network host; Hunyuan3D / z-image / ACE-Step tools (`~/chimera-tools`) as Heads |
| M4 Max (mac-lan) | Second big head / coder; Perspective shadow Head (Blender 5.2.2). The Perspective Head source lives there, not in this repo |
| M4 Pro | Small parallel workers |
| Nvidia PC (RTX 3080 Ti laptop, 16 GB, Windows likely) | Fast worker; ComfyUI image-gen Head (needs the Windows unsandboxed-Heads opt-in) |
| AMD GPU | Worker; ROCm or Vulkan |

Studio install lineup: `scripts/chimera-studio-install.sh` (`--dry-run` previews; re-running resumes). It ran once on the Studio, Oct 24 (log: `~/chimera-tools/install-20261024-022651.log`): z-image-turbo and qwen3.8:27b ok; Hunyuan3D 2.1 Mac port FAILED; ACE-Step FAILED (needs `brew install uv`); phonon SKIPPED (needs Ollama 0.40.9+, the Studio has 0.40.1); gpt-oss:120b never finished (not in `ollama list`).

## Not yet verified (expect fixes)
1. 0.6.1 on real machines: Settings shows 0.6.1; double-click while running brings the window back; Local Network prompt still attributed to "Chimera" for the detached daemon; two Macs discover each other.
2. macOS sandbox profile: file rules hold on the Studio (`run_it.py` under sandbox-exec), but the localhost network rule is broken (see Known bug above).
3. First real Head runs: ComfyUI Head on the Nvidia PC. Done by the user on Oct 25, with 0.6.0: a Hunyuan3D picture-to-GLB Head and Perspective 0.5.4 studio shadows both returned results over the network, running on the computer named FX2. The user built that Hunyuan3D Head from another Claude account on another computer; neither its source nor Perspective's is in this repo. The repo's reference Heads (`heads/`) still only ran against fake servers. The Studio's Hunyuan3D is the 2.1 Mac port, but `heads/hunyuan3d-mesh` was written for the 2.0 API. 2.1 serves `/health`, not `/healthcheck`. It defaults to port 8081, `--host 0.0.0.0` and `--device cuda` (start it with `--host 127.0.0.1 --port 8080 --device mps`), has no `--enable_tex`, and always textures. Fix `run.py` and heads/README first, after the install itself succeeds.
4. Cross-network: user still has to choose Tailscale (private) or Tailscale Funnel (public, no friend setup). `defaultPoolAddr` is still `""`.
5. Log for debugging: `~/Library/Application Support/Chimera/chimera.log`.

## Reminders
- **Starter credits are 1,000,000 for testing** (`starterCredits` in `app/hub.go`). Revert to 100 when testing ends. Bumping `starterMigration` alone won't revert anything: the migration in `NewHub` only raises balances below the starter amount, so existing 1M balances would stay and debts would be forgiven. Change it to clamp existing balances too. The open pool plus a Funnel address makes the 1M starter a meaningless brake.
- Never expose Ollama or the hub with a port-forward; traffic is unencrypted. Use Tailscale.

## Next
1. Retest 0.6 on the real machines (above).
2. First real Head runs (above).
3. Pick Tailscale vs Funnel; bake the Studio address into `defaultPoolAddr` (fix the pool-address gap under Hosting first).
4. Revert starter credits to 100 (with the migration change in Reminders).
5. Heads follow-ups: fix the localhost sandbox bug; img2img ComfyUI Head (`optional_input`), long tasks calling Heads, several pictures per message, hash-pinned Head identity, a proper Windows sandbox (AppContainer), inline GLB/video viewers. The Head maker can't do async servers (send, then poll); those need a hand-written Head.
6. Later: encryption and prompt privacy from the host, Intel Mac build, maybe a native Mac window.
