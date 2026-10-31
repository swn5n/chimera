# Chimera 0.7.0

Share idle GPUs — and the tools on them — with friends through Ollama, SheepIt style. One person hosts the pool; everyone else's Chimera finds it and joins on its own — on the same Wi-Fi automatically, and across the internet once you point it at the host's address. Press Connect to lend your GPU: prompts from the pool run on your models, and you earn credits for the work.

## New in 0.7

- **Hydra 1.0, the network's own helper model.** Planning a long task, the review in **Keep going until done**, and the "should a Head do this?" check now run on **Hydra 1.0** (`hydra:1.0`, 2.9 GB): a small model trained for exactly those three jobs, small enough for every computer to run. Long tasks no longer wait for the biggest model to plan or review, and the Head check gets the model that was trained for it. When no computer the task may use has Hydra 1.0, or a task is too big for it (roughly 13,000 characters going into a plan, 16,000 into a review), these go to the biggest model, as before. If Chimera can't read Hydra's plan or review, it asks once more without it. Hydra 1.0 never answers chats or works on steps, and the chat's model picker doesn't list it. The task card says which computer and model planned, combined and reviewed.
- **Get it from the host, inside Chimera.** On each computer: **Models → Helper → Get from host**. It copies the host's Hydra 1.0 straight into that computer's Ollama; nothing is downloaded from the internet. The host needs Chimera 0.7.0 and Hydra 1.0 in its own Ollama. Only install it on computers that run 0.7.0: an older Chimera treats it as an ordinary chat model.
- **Or download it.** Hydra 1.0 is also on the [v0.7.0 release](https://github.com/swn5n/chimera/releases/tag/v0.7.0), for a first computer with no host to copy from. It comes in two parts because GitHub limits a release file to 2 GB. Put both parts and `Modelfile` in one folder, then run these two commands (on Windows, replace the first with `copy /b hydra-1.0-q5_k_m.gguf.part-aa + hydra-1.0-q5_k_m.gguf.part-ab hydra-1.0-q5_k_m.gguf`):

  ```bash
  cat hydra-1.0-q5_k_m.gguf.part-* > hydra-1.0-q5_k_m.gguf
  ollama create hydra:1.0 -f Modelfile
  ```
- **Long tasks check their own scripts.** In **Keep going until done**, a round's Blender or Python script now runs before the review, in a sandbox on the computer that started the task. If it crashes or the result was cut off, the next round is told exactly what went wrong. Turn it off with **Settings → Lending → Run my long tasks' scripts here to check them**. Not on Windows.
- **Make a Head without code.** **Settings → Heads → Make a Head** turns a program or a local server on your computer into a Head from a form, and **Try** runs it once the way the pool would. Start from an example, or follow `heads/MAKE-A-HEAD.md`.

## New in 0.6

- **Heads: your tools, callable by the whole pool.** Chimera has many heads. A *Head* is a tool installed on one computer — Perspective's studio shadows on the laptop, image generation in ComfyUI on the Nvidia PC, Hunyuan3D meshes on the Studio — that anyone in the pool can use without installing anything. Ask in Chat the way you'd ask a person: attach a picture and say *"put this on white with a soft studio shadow"*, or just type *"generate an image of a red pickup on a dirt road"* or attach a chair and ask for *"a 3D model of this"*. Chimera prefers a Head over an AI model when a Head does that job, because a real render beats a model's guess. Results come back into your chat with a Save link (meshes download as GLB; open them in Blender with File → Import → glTF).
  - **Words alone work now.** Before, a tool was only considered when a picture was attached. Now a request in plain words goes to a Head when it's clearly asking for what that Head makes — the pool's fastest model double-checks, so *"how does image generation work?"* stays a conversation and *"generate an image of…"* becomes one. Picking a specific model in the composer always uses that model.
  - **Ratings decide, and Heads earn.** When several Heads could do a job, the best-rated one is picked — so rate results. The Head's owner earns **bonus credits** every time their Head does a job for someone else (half the run's charge again, at least 0.1), **plus 1 credit** each time someone else rates the result 4 or 5 stars. That's the reward for bridging a gap with a real tool instead of a model.
  - **Heads that wrap a local server** (ComfyUI, a 3D model server) can reach it from inside the sandbox when they say so; the internet stays blocked on a Mac.
  - **Ready to install:** the `heads/` folder next to the app has `comfyui-image` (text → picture, any checkpoint you have; your own exported workflow for Flux), `hunyuan3d-mac` (picture → textured GLB with Hunyuan3D 2.1 on a Mac's GPU, about 3 minutes on the Studio; tested for real), `hunyuan3d-mesh` (picture → GLB through Hunyuan3D 2's API server, for Nvidia PCs), a `TEMPLATE` to copy, and `heads/README.md` on how to write one. `comfyui-image` and `hunyuan3d-mesh` were tested against fake servers that speak the real API, not yet against real ComfyUI/Hunyuan3D — tell me what trips. `perspective-shadow` lives on the laptop (see its handoff).
- **Quit really quits, and opening Chimera again brings the window back (Mac).** Chimera lives in the background with no Dock icon; closing its window never quit it. On a Mac, double-clicking the app while it was running did *nothing* — macOS won't start a second copy and the running one couldn't hear the "show yourself" signal — which looked like "it says it's already running" with no way back in. Now opening Chimera again always brings the window back, and **Settings → Quit Chimera** ends it for real (it did before too; the confusing part was the reopen).
- **Bigger model list.** More curated models in **Models** — small fast ones, coders for 16 GB cards, vision, reasoning, big ones for 48–96 GB — and a note on what an Nvidia/CUDA PC adds. Picture and 3D generation aren't Ollama models; they're Heads (above).

## New in 0.5 (built on the laptop, merged here)

- **Plugins: tools the network can call.** Install one on your computer (Settings → Heads → Open heads folder, then drop its folder in) and anyone in the pool can use it: attach a picture in Chat (**+ Picture**, or paste or drop it), say what you want, and the result comes back into your chat with a Save link. The first one is **Perspective studio shadow**: send a picture of a machine and get it back on white with a realistic shadow, rendered in Blender on the computer that has Perspective.
- **Ratings pick the plugin.** If several could do a job, Chimera uses the best-rated one. Rate the result and your stars count toward it.
- **Plugins run sandboxed.** No network, your home folder and Chimera's own data hidden except the plugin's own folders, writes only to a throwaway folder (on Linux, install bubblewrap for that). Turn lending them off under Settings → Heads.
- Chimera now uses the newest Blender on a Mac with more than one installed.

## New in 0.4.1

- **Opening a new version now actually runs it.** Chimera lives in the background and only quits from Settings, so until now opening a newer Chimera while an old one was still running just brought the old one's window back — you'd think you were on the new version and nothing would have changed. Now the new one tells the old one to quit and takes its place. **Check it worked: Settings shows "Chimera 0.4.1" at the bottom.** (Do this once on every computer.)
- **Two hosts on one Wi-Fi become one pool.** If both your computers ended up hosting — the "let anyone join" switch only shows when you're hosting, so it's easy to do on both — they used to sit there as two separate pools that couldn't see each other. Now any open host that finds another open host on the network merges into the better-established one (the one a person started wins over one that started itself; then the one with more computers online; then the one that's been up longer). It checks every 20 seconds, so a laptop that wakes up later still merges.
- **Lost the host? It finds the pool again.** A computer that can't reach its hub for a minute (the host moved, changed address, or went away) looks for the pool again — the pool address, then an open host on the Wi-Fi — and if there's nothing, it starts a pool so the others aren't stranded. When the original host comes back, they merge.

## New in 0.4

- **One open pool — anyone, any network, joins automatically.** You don't pass around codes anymore. The host leaves the pool **open** (Settings → Network → "Let anyone join this pool"), and every other computer lands in it by itself: first by a **pool address** if one is set (works across the internet), then by finding the host on the local Wi-Fi, and if nobody is hosting yet, one computer elects itself the host so the pool always exists. Credits — not codes — stop anyone from just asking questions without contributing: run out and you can't use other people's GPUs, though your own stay free. (Prompts aren't encrypted or hidden from the host yet; that's a later job. For now the goal is simply that everyone's in and helping.)
- **Pool address, set once.** For friends in other houses, the host runs on an address reachable from anywhere — the simplest is Tailscale — and everyone puts that address in Settings → Network → **Pool address** (`100.x.x.x:7480`). After that their Chimera joins the pool on every launch with nothing typed, wherever they are. (I can bake your Studio's address in as the built-in default so even that one field is pre-filled — see the note at the bottom.)
- **Fix: computers on the same Wi-Fi now actually see each other.** Discovery was silently dropping its "who's hosting?" broadcasts. That's fixed. If two Macs still don't find each other, it's almost always the macOS **Local Network** permission — see "Opening it the first time" below.

## New in 0.3

- **Auto-join on the same Wi-Fi.** No more passing around an address and code. The host leaves "Let devices on this Wi-Fi join automatically" on (Settings → Network), and other computers find the network and join by themselves. The invite code still works for friends in other houses (over Tailscale), and you can turn auto-join off to require it.
- **Keep going until done (looping tasks).** In Chat, turn on **Long task** and then **Keep going until done**. After each round the biggest model reviews the result against your goal and runs another round to improve it — up to six — stopping as soon as it's good enough. The card shows the round it's on.
- **Your devices pitch in.** When you start a long task, your other computers connect on their own to help, then stand down when it's finished (Settings → Lending → "Let my devices help my long tasks").
- **Add to Dock.** Chimera is still a local web app, but you can install it so it sits in your Dock with the Chimera icon, in its own window with no browser tabs: Settings → App → **Add to Dock** (Chrome or Edge).
- **Testing credits.** Everyone starts with **1,000,000 credits** so credits stay out of the way while you try things. (This drops back to 100 for real use — say the word.) Running out now actually stops you using other people's GPUs; your own devices stay free.

## New in 0.2

- **Models tab.** Shows how much memory this computer has for models, where each installed model sits on that gauge, and a recommended download for each job (planning, coding, vision, and so on). Recommendations only include models that fit with room to spare, because a model that barely fits spills onto the CPU, slows to a crawl and times out. Models too big for a computer aren't lent at all.
- **Context limits.** Each model's longest context that fits on its computer is worked out from the model's architecture, and steps only go to devices with room for them.
- **Tools.** Each computer lists what it can do beyond chat: vision, audio, image, video, 3D mesh and audio generation (through Ollama or ComfyUI), Blender, and computer use (shown, but never lent to the network).
- **Runs anyway.** If nobody is lending, a chat runs on your own best model and says so.
- **Help wanted.** The Network tab compares what the network waited for in the last hour with what your computer has, and suggests connecting, sharing a model, or downloading one that fits.
- **Long tasks (Hydra).** Turn on Long task in Chat. The biggest model on the network plans the work as a few small steps, the steps run at the same time on different computers (each worker is told it's one piece of a bigger project, with instructions that suit the kind of task), and the biggest model combines the results.
- **Ratings and the library.** Rate any reply out of 5 stars. For 4 or 5 stars Chimera asks what worked, and the network's biggest model turns it into a reusable library entry: code, a Blender script, a lesson or a prompt. Long tasks reuse checked entries instead of asking a model again.
- **Checking the library.** When a lending computer has been idle for a while (10 minutes by default), the network re-checks entries with its biggest model. The host can let their own computer test-run Python and Blender scripts. Anything that fails or looks like spam waits in the host's Library tab for review.
- **Export ratings.** The host can export every rated reply as a JSON lines file: the network's own best answers, ready for fine-tuning a small model later.

## Update every computer

Everyone in a pool should run the same version. Device cards show a warning next to anyone on an older one.

## Opening it the first time

- **Mac:** Chimera isn't signed with an Apple developer account. Since 0.2 the app is signed properly for that case, so a Mac that receives it should no longer say it's "damaged". Instead macOS says it can't verify the developer: click Done, open System Settings → Privacy & Security, scroll down and click Open Anyway.
  - **Say Allow to the "find devices on your local network" prompt.** This appears the first time Chimera looks for the pool, and it's how it reaches other computers on your Wi-Fi. If you miss it or click Don't Allow, two Macs won't see each other no matter what — turn it back on under System Settings → Privacy & Security → **Local Network** → Chimera. (Joining by a pool address / Tailscale doesn't need this.)
  - **Firewall on?** macOS's firewall is off by default, but if you turned it on (System Settings → Network → Firewall), click Allow when it asks whether Chimera can accept incoming connections, or add Chimera under Options. With "Block all incoming connections" on, nobody can reach your hub.
  - Still says "damaged"? In Terminal: `xattr -dr com.apple.quarantine /Applications/Chimera.app` (use the folder you put it in), then open it again.
- **Windows:** SmartScreen may say "Windows protected your PC". Click More info, then Run anyway. The host computer may also get a firewall prompt; allow it on private networks.
- Chimera runs in the background with no Dock icon. Its window opens in Chrome or Edge as an app window if one is installed, otherwise in your browser. **Closing the window doesn't quit Chimera** — it keeps lending. Open Chimera again (double-click the app, or click its Dock icon if you added one) to bring the window back. To really stop it: **Settings → Quit Chimera**. (Disconnect only stops lending; with a step running it offers to finish it first.)

## First test: your two Macs

1. Install Ollama on both computers from ollama.com/download and open it.
2. Open the new Chimera on both (from `dist/Chimera.app` — or wherever you keep it). **Open Settings and confirm it says Chimera 0.7.0** on each; if it says anything older, the old one was still running — just open the new app once more.
3. Enter your name. You don't have to choose Host or Join: on the same Wi-Fi they find each other on their own within about 20 seconds — one hosts, the other joins. If you *did* click Host on both, that's fine now; they merge.
4. Still not seeing each other after ~30 seconds? Go down the list in **"Still can't see each other?"** below.
5. On each computer open **Models**, press **Get from host** next to Hydra 1.0 (the host has it already), and download the recommended picks you want.
6. Press **Connect** on both. Both computers show up under your pool as Lending.
7. In **Chat**, send something, or turn on **Long task** and describe a bigger job. Each reply says which computer and model wrote it.
8. Rate a good reply 5 stars and say what worked. It shows up in **Library** once it's checked.

## Still can't see each other? (same Wi-Fi)

In order, most common first:

1. **Is it really 0.7.0?** Settings shows the version at the bottom. If not, open the new app once more; it replaces the old one.
2. **macOS Local Network permission.** System Settings → Privacy & Security → **Local Network** → Chimera must be on, on *both* Macs. If Chimera isn't listed, quit it from Settings, open it again and say **Allow** to the prompt.
3. **Same Wi-Fi, really?** Some routers put 2.4 GHz and 5 GHz on separate networks, or have a "guest"/"isolated" mode that stops devices talking to each other. Both Macs should show the same network name, and the laptop should be able to open `http://<studio's address>:7480/v1/ping` in a browser (the Studio's address is under Settings → Network → Addresses on the Studio) and see `{"app":"chimera-hub"…}`. If that page doesn't load, it's the network, not Chimera — try a different Wi-Fi, or join by typing that address in the Network tab.
4. **Firewall.** See "Opening it the first time".
5. **Send me the log.** It's at `~/Library/Application Support/Chimera/chimera.log` on each Mac (Finder → Go → Go to Folder, paste that path). Drop both files in the chat and I can see exactly what each computer did.

## Friends in other houses (and your own laptop when it's out)

Straight answer: **two computers on different networks can't find each other on their own** — nothing can; there's no "the internet" to shout into. They need one address they can both reach. Two ways, pick one:

- **Tailscale (private, recommended).** Free. Install it on the Studio and on each friend's computer, share the Studio with them, then put the Studio's Tailscale address (`100.x.x.x:7480`) in **Settings → Network → Pool address** on each computer. From then on their Chimera joins the pool automatically on every launch, from anywhere — no code, no Join step. Tell me the Studio's Tailscale address and I'll build it in as the default so nobody has to type even that.
- **Tailscale Funnel (public — friends install nothing).** On the Studio: `tailscale funnel 7480` gives it a public `https://<studio>.<your-tailnet>.ts.net` address; friends just put that in Pool address (or I bake it in). Anyone on the internet who has the address can then join and use the pool — that's the trade: zero setup for friends, zero privacy, and credits are the only brake. Your call; given you've said privacy isn't the goal right now, it's the fastest route to "anyone, anywhere".

Never port-forward 7480 straight from your router: that exposes the hub with no encryption at all.

## How it works

- Each computer runs Chimera next to Ollama. Ollama stays private on that computer; only Chimera talks to the network.
- **Connected** means lending. When you disconnect in the middle of a step, Chimera asks whether to finish it first or stop now. Stop now hands the step to another device that has the same model.
- Lending pauses by itself if Ollama closes or the host goes away, and picks back up when they're back.
- Chats are saved only on the computer that sent them. The library and ratings live on the host.
- **Credits:** for testing, everyone starts with **1,000,000** (normally 100). When your GPU runs a step for someone, credits move from them to you: 1 per 1,000 tokens from an 8B model, more for bigger models. Using your own devices is free, and so are library checks. If you run out, you can't send work to other people's GPUs until you earn more — but your own devices (or "Only my devices") still work.

## The library, safely

- Only the hosting computer reviews the library and only it can test-run scripts, and only if you turn on Settings → Library → Test library scripts on this computer. Names aren't passwords, so these rights follow the machine, not the name.
- Scripts run in an empty temporary folder with a time limit and none of your settings. Scripts that delete files, use the network or start other programs are refused and flagged instead. On a Mac they also run in a sandbox with no network and no access to your home folder.
- Long tasks only reuse entries that passed the checks, so a new entry can't slip instructions to the AI workers.
- Test-run output is only shown on the host.

## Not in 0.7 yet

- **A real sandbox for Heads on Windows.** Macs and Linux run Heads sandboxed. Windows has no sandbox Chimera trusts, so Heads are off there by default — but you can switch them on under Settings → Heads → **Run Heads without a sandbox on this computer**. That's how the Nvidia PC hosts ComfyUI for the pool today: the Head runs with your normal permissions, so only install Heads you trust. (Head code is always installed by hand; the pool only sends it pictures and words.)
- **One picture per message; long tasks don't call Heads yet; no video/audio player inline** (those files download).
- The `comfyui-image` and `hunyuan3d-mesh` reference Heads haven't met a real ComfyUI / Hunyuan3D server yet.

- **Privacy.** The pool is open and unencrypted: the host can see prompts, and anyone you let in can too. Fine for friends; not for anything sensitive. Encrypting traffic and hiding prompts from the host is something we are working on.
- Chimera finds and links tools like Blender and ComfyUI but doesn't install them; Ollama models it downloads itself.
- The library stores text (code, scripts, lessons). Generated 3D meshes and images aren't stored yet.

## Where things are saved

Settings, chats, the log (`chimera.log`), measured model speeds (`perf.json`) and, on the host, the network's ledger (`hub.json`) and library (`library.json`):

- Mac: `~/Library/Application Support/Chimera`
- Windows: `%AppData%\Chimera`

## Ports

- `7470`: Chimera's window. Only reachable from the same computer.
- `7480`: the hub. Only open on the host.
- `7479` (UDP): LAN discovery, so devices on the same Wi-Fi find the host. Only answers the local network.

## Rebuilding

Install Go 1.24 or newer, then run `app/build.sh`. To remake the icons from `chimera_icon.png`, run `python3 app/packaging/make_icons.py chimera_icon.png` (needs Pillow).
