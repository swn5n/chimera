<p align="center">
  <img src="chimera_icon.png" width="120" alt="Chimera: three metal triangles on dark grey">
</p>

<h1 align="center">Chimera 0.9.0</h1>

<p align="center">
  <b>Split the task, not the model.</b><br>
  Agentic loops on a pool of local GPUs. Lend yours, borrow everyone's, SheepIt style.
</p>

<p align="center">
  <a href="https://github.com/swn5n/chimera/releases/latest"><b>Download</b></a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#long-tasks">Long tasks</a> ·
  <a href="#heads">Heads</a> ·
  <a href="#version-history">Version history</a> ·
  <a href="https://chimera.engineering/">Website</a>
</p>

## What is Chimera?

Chimera is a desktop app for macOS, Windows and Linux. It links computers that run [Ollama](https://ollama.com) into one **pool**, so friends, or just your own machines, can share their GPUs and the tools installed on them.

- **Lend.** Press **Connect** and the pool can run work on your models while you get on with your day. Every job earns you credits.
- **Borrow.** Ask in **Chat** and Chimera runs your message on the best model the pool has free, or the one you pick. If nobody is lending, it runs on your own best model and says so.
- **Split big jobs.** Switch on **Long task** and Chimera breaks the job into steps, runs them at the same time on different computers, and combines the results. Add **Keep going until done** and it also runs what came back, repairs what crashes, checks it against your goal, and goes another round until it's done.
- **Share tools, not just models.** A **Head** is a tool installed on one computer (an image generator, a 3D-model maker, a Blender render). Anyone in the pool can use it without installing anything.
- **Bring your own big model.** A model that runs outside Ollama, like DeepSeek V4.1 Flash from its own server, can join your chats on this computer, and you can hand it your files.

If you know [SheepIt](https://www.sheepit-renderfarm.com), the community render farm for Blender, this is the same deal for AI: lend your idle GPU, earn credits, spend them on other people's.

**Split the task, not the model.** Spreading one model across several computers needs very fast links between them. Chimera hands each step, whole, to one computer with a model (or a tool) that fits it, so ordinary Wi-Fi is plenty.

> [!NOTE]
> Chimera is an early, fast-moving project. Most testing has been on Apple-silicon Macs and one Windows PC; the Linux build passes the automated tests but hasn't had much real use. Read [Safety, privacy and limits](#safety-privacy-and-limits) before you invite anyone in.

## How it works

```text
┌────────────────────┐     ┌────────────────────┐     ┌────────────────────┐
│ Your computer      │     │ Host computer      │     │ Another computer   │
│ Chimera + Ollama   │ <-> │ Chimera + Ollama   │ <-> │ Chimera + Ollama   │
│ your models        │     │ + the hub: queue,  │     │ its own models     │
└────────────────────┘     │ credits, library   │     └────────────────────┘
                           └────────────────────┘
```

- Every computer runs Chimera next to Ollama. Ollama stays private on that computer; only Chimera talks to the network.
- One computer hosts the pool's **hub**. It matches each step to a computer and keeps the credits and the library. Any computer can host, and if nobody does, one volunteers itself, so the pool always exists.
- Other computers only ever dial out. Nobody but the host opens a port.
- Chimera works out what each computer can run (its memory, the biggest model that fits, how long a prompt it can take, which tools such as Blender are installed) and only sends a step where it fits. A step that stalls, or whose computer goes away, is retried on another one.
- Chats are saved only on the computer that sent them. Replies you rate highly are also copied to the host's library.

### Words you'll see

| Word | What it means |
|---|---|
| **Pool** (or network) | The computers working together. The **Network** tab shows it. |
| **Host** | The computer that runs the pool's hub. It matches work to computers and keeps the credits and the library. |
| **Connect** | The switch that lends this computer to the pool. While it's off, nobody else can use your computer. |
| **Credits** | What lending earns and asking spends. Your own computers are free to use. |
| **Long task** | A big job split into steps that run on several computers at once. Chimera's name for the system behind it is **Hydra**. |
| **Head** | A tool on one computer that the whole pool can call: an image generator, a 3D-model maker, a Blender render. |
| **Hydra 1.0** | A small helper model (2.9 GB) trained to plan long tasks, review their results and decide when a Head should answer. |
| **Library** | Code, Blender scripts and lessons saved from replies rated 4 or 5 stars. Long tasks reuse them. |
| **Engine** | A model that runs outside Ollama, from its own server. It's for your own chats on this computer, never the pool. |

## Quick start

### What you need

- **A computer.** A Mac with Apple silicon (macOS 13 or newer), a 64-bit Windows PC, or a 64-bit Linux PC. There is no Intel Mac build yet.
- **[Ollama](https://ollama.com/download)**, installed and open. Chimera needs it running before a computer can connect.
- **A GPU**, or an Apple-silicon Mac, for decent speed. Chimera suggests models that fit each computer's memory with room to spare.

### 1. Install Chimera

Download the file for your system from the [latest release](https://github.com/swn5n/chimera/releases/latest):

| System | File | Then |
|---|---|---|
| Mac | `Chimera-mac.zip` | Unzip it, move **Chimera.app** to your Applications folder and open it. |
| Windows | `Chimera-windows.zip` | Unzip it and run **Chimera.exe**. |
| Linux | `Chimera-linux.tar.gz` | Run `tar xzf Chimera-linux.tar.gz`, then `./chimera`. Install `bubblewrap` too if you want sandboxed Heads and script checks. |

<details>
<summary><b>The first time you open it: Mac and Windows warnings</b></summary>

- **Mac.** Chimera isn't signed with an Apple developer account, so macOS says it can't verify the developer. Click **Done**, open **System Settings → Privacy & Security**, scroll down and click **Open Anyway**.
  - **Say Allow** when macOS asks to find devices on your local network. That's how Chimera finds other computers on your Wi-Fi. If you missed it or clicked Don't Allow, two Macs won't see each other until you turn it back on under System Settings → Privacy & Security → **Local Network** → Chimera. (Joining by a pool address doesn't need it.)
  - **Firewall on?** Click Allow when macOS asks whether Chimera can accept incoming connections, or add Chimera under System Settings → Network → Firewall → Options. With "Block all incoming connections" on, nobody can reach your hub.
  - Still says "damaged"? In Terminal run `xattr -dr com.apple.quarantine /Applications/Chimera.app` (use the folder you put it in), then open it again.
- **Windows.** SmartScreen may say "Windows protected your PC". Click **More info**, then **Run anyway**. The computer that hosts the pool may also get a firewall prompt: allow it on private networks.

</details>

Chimera runs in the background. Its window opens as an app window in Chrome or Edge if you have one, otherwise in your browser. **Closing the window doesn't quit Chimera**, so it keeps lending. Open Chimera again to bring the window back. To really stop it, use **Settings → Quit Chimera**. (On a Mac it has no Dock icon; **Settings → App → Add to Dock** adds one in Chrome or Edge.)

### 2. Set up this computer

Type your name (friends see it next to your credits) and a name for this computer. You can ignore **Host a network** and **Join a network**: click **Skip for now** and Chimera looks for a pool on your Wi-Fi by itself. It joins one if it finds it, or starts one if there isn't one.

If you'd rather choose: **Host a network** starts a pool on this computer and shows the address and invite code to give friends. **Join a network** lists the pools it finds on your Wi-Fi, or takes an address and invite code.

### 3. Get a model

Open **Models**. It shows how much memory this computer has for models and recommends a download for each job (chat, coding, vision, planning). Press **Download** on the ones you want. The helper model, Hydra 1.0, has its own row: see [The helper model, Hydra 1.0](#the-helper-model-hydra-10).

### 4. Say hello

Open **Chat**, leave **Model** on **Best available** and send a message. Each reply says which computer and model wrote it. You don't need to be connected to chat: with nobody lending, Chimera answers with your own best model and says so. That makes one computer a fine first test.

### 5. Lend your computer

On **Network**, press **Connect**. Your models are now available to the pool, and you earn credits when they're used. Press **Disconnect** any time; if a step is running, Chimera offers to finish it first or stop now (a stopped step goes to another computer that has the same model).

### 6. Add more computers

Repeat steps 1 to 3 on each computer. On the same Wi-Fi they find each other within about 20 seconds: one hosts, the rest join. Press **Connect** on each, and they show up on the **Network** tab. For friends on other networks, see [Connecting over the internet](#connecting-over-the-internet).

### 7. Try a long task

In **Chat**, switch on **Long task**, describe a bigger job, and try **Keep going until done**. See [Long tasks](#long-tasks).

### 8. Rate the replies

Rate a good reply 5 stars and say what worked. Once it's been checked it appears in **Library**, and long tasks can reuse it.

## Using Chimera

Six tabs run along the top.

| Tab | What it's for |
|---|---|
| **Network** | The Connect switch, who's in the pool and what each computer is lending, Ollama's status, and this computer's models. |
| **Models** | The memory this computer has for models, a recommended download for each job, every model in the catalog, a box to download any Ollama model by name, and the helper model. |
| **Chat** | Talk to the pool, or to your own engine. Your saved chats are on the left, with search. |
| **Library** | Code, Blender scripts and lessons saved from well-rated replies. |
| **Activity** | Every step the network ran, and your credits. |
| **Settings** | Your name, lending limits, the network, Heads, and Quit. |

**Under the message box in Chat:**

| Control | What it does |
|---|---|
| **Model** | **Best available** lets Chimera choose, preferring bigger models that fit comfortably and are already loaded. Pick a model by name to use exactly that one. Engines are listed under **This computer's own**. |
| **Thinking** | Appears for a model that offers levels of thinking: more takes longer. |
| **Run on** | Any device, or one you pick. |
| **Only my devices** | Keep the work on your own computers. It's free. |
| **Long task** | Split the job into steps across computers. |
| **Keep going until done** | Appears with Long task: check, repair and repeat until the job is done. |
| **+ Picture** | Attach a picture for a Head to work on. You can also paste or drop one. With an engine picked it becomes **+ Files**. |

**In a chat.** Replies render as Markdown, with tables, lists, and code blocks that have **Copy** and **Download**. A model's thinking sits in a box that folds away when it answers. Replies have **Copy**, and **Write again** redoes the last reply with the model you've picked now; **Edit** changes one of your messages and asks again. Search your chats with Cmd-K (Ctrl-K on Windows and Linux), drag chats into groups, and select and delete old ones. If a model writes a web page or an SVG, you can show it right in the chat, sandboxed, and save it to the chat's folder.

**Lending limits** are in **Settings → Lending**: how many steps to run at once, the largest model you'll lend, whether Chimera opens Ollama when you connect, and whether it connects when it starts.

## Long tasks

Chat is for questions. A **long task** is for jobs too big for one reply: a small web app, a report, a Blender scene. Switch on **Long task** in Chat and describe the job.

1. **Plan.** A planner splits the job into 2 to 7 steps and says which steps need another step's output. It's the helper model (Hydra 1.0) when a computer has it, otherwise the biggest model in the pool.
2. **Work.** Steps that don't depend on each other run at the same time, up to four at once. Each goes to the computer that will finish it soonest, judged by how long steps have really taken there, not by who has the biggest model. Every worker is told it is one small piece of a larger project, with rules that suit the kind of job: code, writing, research, Blender or general.
3. **Combine.** The biggest model joins the pieces into one result.

Steps that match a checked entry in the [library](#the-library) reuse it instead of asking a model. You can watch every step in the chat: which computer and model is on it, and what it wrote. Your own idle computers connect on their own to help, then stand down (**Settings → Lending → Let my devices help my long tasks**).

### Keep going until done

Switch on **Keep going until done** and one pass isn't the end. Chimera checks the facts before anyone gives an opinion:

- **It runs the script.** A Blender or Python script in the result runs in a sandbox on your computer: no network, your home folder hidden, writes only to a throwaway folder. If it crashes, a model gets only the script, the error and Blender's real names for things, and fixes that spot, up to 8 repairs per round.
- **It checks the scene.** A task that asks for a scene needs a camera, and that camera has to show what you named. Empty objects and a leftover default cube are caught too.
- **A model looks at the picture.** Once everything else passes, a small render goes to a vision model on your computer (`qwen3.8`), which says what it can make out. If the picture is blank, or most of what you asked for can't be seen, the script goes back for repair.
- **Then it reviews.** Hydra 1.0 (or else the biggest model) reads the result against your goal and says whether it's done. If not, the next round starts from the best result so far and edits it instead of starting again. There are up to six rounds, and you get the best one.

A reply with no note on it has been run, measured and looked at. That doesn't make the picture good: nothing judges shape, scale or light yet, and a model that can't build a bicycle still can't.

**What the checks need.** They run on the computer that starts the task, on macOS or Linux, with Blender installed (Linux also needs `bubblewrap`). The look also needs `qwen3.8` on that computer (**Models**); without it that step is skipped and the task runs the same. Windows gets the routing but no script checks. To turn the checks off: **Settings → Lending → Run my long tasks' scripts here to check them**.

How it works in detail: [hydra1/README.md](hydra1/README.md). Real runs and their numbers: [docs/joint-task-oct31.md](docs/joint-task-oct31.md).

### The helper model, Hydra 1.0

Planning, reviewing and the "should a Head do this?" check run on **Hydra 1.0** (`hydra:1.0`): a small model (Qwen3-4B-Instruct-2507 with a trained LoRA, 2.9 GB) made for exactly those three jobs and small enough for every computer to run. Without it those jobs go to the biggest model in the pool, so it's recommended, not required. It never answers chats or works on steps, and the chat's model picker doesn't list it.

**To get it:**

- **From the host (easiest).** On each computer: **Models → Helper → Get from host**. It copies the host's Hydra 1.0 straight into that computer's Ollama. Nothing is downloaded from the internet. The host needs Chimera 0.7.0 or newer and Hydra 1.0 in its own Ollama.
- **From GitHub (for the first computer).** Download both `.part` files and `Modelfile` from the [v0.7.0 release](https://github.com/swn5n/chimera/releases/tag/v0.7.0) into one folder. It comes in two parts because GitHub limits a release file to 2 GB. Then, with Ollama running:

  ```bash
  cat hydra-1.0-q5_k_m.gguf.part-* > hydra-1.0-q5_k_m.gguf
  ollama create hydra:1.0 -f Modelfile
  ```

  On Windows, join the parts with `copy /b hydra-1.0-q5_k_m.gguf.part-aa + hydra-1.0-q5_k_m.gguf.part-ab hydra-1.0-q5_k_m.gguf` instead of `cat`. To check the download on a Mac, run `shasum -a 256 -c hydra-1.0-SHA256SUMS.txt`.

Only put Hydra 1.0 on computers running Chimera 0.7.0 or newer: an older Chimera treats it as an ordinary chat model. Hydra 1.0 is released under the Apache License 2.0 (`LICENSE-hydra-1.0.txt` on that release). How it was trained and measured: [helper-model/](helper-model/README.md).

## Heads

A **Head** is a tool installed on one computer that anyone in the pool can use. Chimera has many heads; that's the point. An image generator in ComfyUI on a PC with an Nvidia card, Hunyuan3D meshes on a Mac, studio shadows rendered in Blender on a laptop: each lives where its models and programs are, and the pool sends requests to it. Whoever asks needs nothing installed.

**Use one** by asking in Chat the way you'd ask a person:

- Attach a picture and say *"put this on white with a soft studio shadow"*.
- Type *"generate an image of a red pickup on a dirt road"*.
- Attach a picture of a chair and say *"a 3D model of this"*.

Results come back into your chat with a **Save** link. Meshes download as GLB; open them in Blender with File → Import → glTF.

- **Heads beat models when they fit the job.** A real render beats a model's guess, so when a Head does what you asked, Chimera uses it. A message with a picture always goes to a Head, whatever model is picked (unless an engine is picked: then the picture is a file for the engine). For words alone, the pool's fastest model double-checks first, so *"how does image generation work?"* stays a conversation and *"generate an image of…"* becomes a Head job. Picking a specific model in the message box always uses that model for words.
- **Ratings decide, and owners earn.** When several Heads could do a job, the best-rated one is used, so rate the results. The owner of a Head earns bonus credits each time it does a job for someone else, plus 1 credit each time someone else rates the result 4 or 5 stars.
- **Your Head, your computer.** A Head runs on the computer that hosts it and returns the result to the chat. Your own computer's GPU is used only for Heads installed on it.

### Install a Head

1. Open **Settings → Heads → Open heads folder** (`~/Library/Application Support/Chimera/plugins/` on a Mac, `%AppData%\Chimera\plugins\` on Windows, `~/.config/Chimera/plugins/` on Linux).
2. Copy the Head's folder in. (Internally a Head is a *plugin*: its folder holds a `plugin.json`.)
3. Within a minute it appears under **Settings → Heads**. If it says *Can't run here*, the note says what's missing, usually a server to start or a program to install.
4. Leave **Let the pool use my Heads** on and press **Connect**. Ollama must be running with at least one shared model, because the fastest shared model reads each job's settings out of the request. A small fast one is plenty.

### Make a Head without code

**Settings → Heads → Make a Head** turns a program or a server on your computer into a Head from a form. **Try** runs it once, the way the pool would. Start from an example, or follow the step-by-step guide in [heads/MAKE-A-HEAD.md](heads/MAKE-A-HEAD.md).

### Heads in this repository

The Heads below are in the [`heads/`](heads/) folder of this repository. They aren't part of the app download.

- **`comfyui-image/`** makes pictures from words through ComfyUI (SD 1.5, SDXL, Flux, any checkpoint you have). It needs ComfyUI running, with a checkpoint.
- **`hunyuan3d-mac/`** makes a textured 3D model (GLB) from one picture, with Hunyuan3D 2.1 on a Mac's GPU: about 3 minutes on an M3 Ultra. It needs the Hunyuan3D 2.1 Mac port. [scripts/chimera-studio-install.sh](scripts/chimera-studio-install.sh) installs it, along with other tools unless you set `SKIP=image,music,tts,vision,planner`, so read it before you run it.
- **`hunyuan3d-mesh/`** makes a 3D mesh (GLB or OBJ) from one picture through Hunyuan3D 2's API server. It's for Nvidia PCs and needs a Hunyuan3D 2 API server running (2.1's differs slightly).
- **`TEMPLATE/`** is a skeleton to copy for a Head written by hand.

`hunyuan3d-mac` has run for real. `comfyui-image` and `hunyuan3d-mesh` were tested only against stand-in servers that speak the same API, so if one trips on your setup, run it alone as described in [heads/README.md](heads/README.md) and [open an issue](https://github.com/swn5n/chimera/issues).

## Your own big model and files

An **engine** is a model that runs outside Ollama, from its own server: DeepSeek V4.1 Flash read from an SSD by InferSSD, for example. It's for your own chats on this computer only. It's never lent to the pool, and long tasks and Heads don't use it.

**Add one** by listing it in `engines.json` in Chimera's data folder (**Settings → App → Data folder → Open folder** opens it):

```json
[
  {
    "id": "my-model",
    "name": "My big model",
    "command": ["/path/to/llama-server", "-m", "{model}", "--port", "{port}", "-c", "{context}"],
    "model_paths": ["/path/to/model.gguf"],
    "port": 8080,
    "context": 32768
  }
]
```

The server has to answer `/health` on that port and speak the OpenAI chat API, streamed. Also there if you want them: `max_tokens`, `thinking` (its levels, `off` first) and `default_thinking`, `idle_minutes` (20), `start_seconds` (600), `free_ollama` (unload Ollama's idle models first), `dir` and `note`. Chimera reads the file again when it changes. Only InferSSD has been tried for real.

The engine then shows in the chat's model picker under **This computer's own**. It starts on your first message to it, and stops after a while unused, when you press Stop, or when Chimera quits. Long replies are saved as they're written.

**Attach files.** With an engine picked, attach files or whole folders (**+ Files**, drop them on the message box, or paste). Chimera copies them into the chat's folder (`~/Documents/Chimera/<chat title>` unless you pick another), keeping their paths, and gives the model a note of facts about each: sizes, see-through backgrounds, lengths, a 3D model's parts by name and its size, and the words of text files. Before the model reads them, Chimera makes what it can use:

- a **compressed GLB** of each OBJ, FBX, STL or PLY model, for web pages (an 82 MB OBJ became 2.6 MB);
- a **turntable** of each 3D model, 72 frames rendered with your Blender;
- a **line on what each picture shows**, from `qwen3.8` on your computer, since the engine itself may read only text.

Each has a switch by the attachments for that message. In the chat, a turntable's thumbnail is a 360° viewer of the frames the model got: rest the mouse on it, drag it, or click to open it large.

**What it needs.** Turntables and GLBs need Blender on the computer you chat from, and run in the same sandbox as the script checks, so macOS (or Linux with bubblewrap, not yet tried) and not Windows. The first turntable with a Blender version spends about 3 minutes preparing its GPU code. Picture lines need `qwen3.8` (**Models**) and, while the engine is running, memory to spare beside it.

## Credits

Credits keep an open pool fair. When your GPU runs a step for someone, credits move from them to you. One credit is about 1,000 output tokens (roughly 750 words) from an 8B model; bigger models cost more, and Head steps are charged by the minute of work. Using your own computers is free.

- If you run out, you can't send work to other people's GPUs until you earn more. Your own computers (or **Only my devices**) still work.
- While Chimera is being tested, everyone starts with **1,000,000 credits** so credits stay out of the way. That will go back to 100.
- Your balance is in the top bar. **Activity** shows every step the pool ran.

## The library

Rate any reply out of 5 stars. For 4 or 5 stars Chimera asks what worked, and the biggest model in the pool turns your answer into a reusable entry: code, a Blender script, a lesson or a prompt. Long tasks reuse checked entries instead of asking a model again. Over time the library becomes the pool's own memory of what works, built from its best answers.

- The biggest model checks new entries. When a lending computer has been idle for a while (10 minutes by default), the pool re-checks entries. Anything that fails or looks like spam waits in the host's **Library** tab for review.
- Only the host reviews the library, and only the host can test-run scripts, and only if it turns on **Settings → Library → Test library scripts on this computer**. Scripts run in an empty temporary folder with a time limit; on a Mac they also run in a sandbox with no network and no access to your home folder.
- Long tasks only reuse entries that passed the checks, so a new entry can't slip instructions to the workers.
- The host can export every rated reply as a JSON-lines file: the pool's best answers, ready for fine-tuning a small model.

## Connecting over the internet

Computers on the same Wi-Fi find each other on their own. Computers on different networks can't: they need one address they can both reach. Pick an always-on computer as the host, then use one of these:

- **Tailscale (private, recommended).** [Tailscale](https://tailscale.com) has a free plan for personal use. Install it on the host and on each friend's computer and share the host with them. On every computer, put the host's Tailscale address (`100.x.x.x:7480`) in **Settings → Network → Pool address**. From then on Chimera joins the pool on every launch, from anywhere.
- **Tailscale Funnel (public; friends install nothing).** On the host, run `tailscale funnel 7480`. It gives the hub a public `https://<host>.<your-tailnet>.ts.net` address, and friends put that in **Pool address**. Anyone on the internet who has the address can join and use the pool, so credits are the only brake.

Never port-forward `7480` from your router: that exposes the hub with no encryption at all.

## Troubleshooting

<details>
<summary><b>My computers can't see each other (same Wi-Fi)</b></summary>

In order, most common first:

1. **Same version?** The bottom of **Settings** shows the version. If a computer shows an older one than you installed, open the new app once more; it replaces the old one.
2. **macOS Local Network permission.** System Settings → Privacy & Security → **Local Network** → Chimera must be on, on every Mac. If Chimera isn't listed, quit it from Settings, open it again and say **Allow** to the prompt.
3. **Same Wi-Fi, really?** Some routers put 2.4 GHz and 5 GHz on separate networks, or have a guest or isolated mode that stops devices talking to each other. From the other computer, open `http://<host's address>:7480/v1/ping` in a browser. The host's address is under **Settings → Network → Addresses** on the host. You should see `{"app":"chimera-hub"…}`. If that page doesn't load, it's the network, not Chimera. Try a different Wi-Fi, or join by typing the address and invite code (**Settings → Network → Join a network**).
4. **Firewall.** See the warnings under [Quick start](#quick-start).
5. **Check the log.** `chimera.log` is in Chimera's data folder (below). If you [open an issue](https://github.com/swn5n/chimera/issues), attach the log from each computer.

</details>

<details>
<summary><b>Chimera says Ollama isn't running</b></summary>

Chimera needs Ollama open before a computer can connect. The **Network** tab shows Ollama's status and can open it for you. **Settings → Lending → Open Ollama when I connect** does it automatically.

</details>

<details>
<summary><b>A model isn't being lent</b></summary>

A model that barely fits in a computer's memory spills onto the CPU, slows to a crawl and times out, so Chimera doesn't lend models that are too big for the computer. The **Models** tab shows what fits comfortably. **Settings → Lending → Largest model to lend** sets a limit of your own.

</details>

<details>
<summary><b>Where Chimera keeps things</b></summary>

Settings, chats, the log (`chimera.log`), measured model speeds (`perf.json`), your engines (`engines.json`) and, on the host, the pool's ledger (`hub.json`) and library (`library.json`) are in Chimera's data folder (**Settings → App → Data folder → Open folder**):

- Mac: `~/Library/Application Support/Chimera`
- Windows: `%AppData%\Chimera`
- Linux: `~/.config/Chimera`

A chat's attached files go in a folder of its own, `~/Documents/Chimera/<chat title>` unless you pick another.

**Ports:** `7470` is Chimera's window (only reachable from the same computer; it falls back to 7471 to 7474 if taken). `7480` is the hub (only open on the host). `7479` (UDP) is how computers on the same Wi-Fi find the host.

</details>

## Safety, privacy and limits

**Privacy.** The pool is open and unencrypted. The host can see prompts, and anyone you let in can too. That's fine for friends, and not for anything sensitive. Encrypting traffic and hiding prompts from the host is something we're working on.

**What runs on your computer when you lend.** Prompts run on your Ollama models, and the pool can send words and pictures to a Head you installed yourself. The pool never sends code for your computer to run. (A host can choose to test-run library scripts in a sandbox; it's off unless they turn it on.) The scripts from your own long tasks run only on your own computer, in a sandbox. An engine is yours alone: Chimera starts the command you wrote in `engines.json`, and the pool never uses it.

**Heads and the sandbox.**

- A Head runs in a sandbox where Chimera can make one: macOS's `sandbox-exec`, or `bubblewrap` on Linux. It gets no network, your home folder hidden except its own folders, and writes only to a throwaway folder and its cache.
- A Head that declares `"network": "localhost"` may talk to servers on your own computer, such as ComfyUI. **Known issue on macOS:** the sandbox rule for this doesn't yet stop such a Head from also reaching the internet and your local network. A fix has been tested but isn't in the app. On Linux a localhost Head gets the normal network. Only install localhost Heads you trust.
- **Windows** has no sandbox Chimera trusts, so Heads are off there by default. **Settings → Heads → Run Heads without a sandbox on this computer** turns them on; then a Head runs with your normal permissions, so only install Heads you trust.

**Open pools.** Anyone who can reach the host's address can join an open pool. Credits, not codes, are what stop people asking without contributing. On the host, turn off **Settings → Network → Let anyone join this pool** to require the invite code instead.

**Limits today.**

- Macs: Apple silicon only, macOS 13 or newer. Chimera is a local web app in a Chrome or Edge app window (or your browser), not a native window.
- The script checks and the look have mostly run on Macs. They haven't run on Linux, and no long task has been started from Windows. On scenes it hadn't been tuned on, the look caught 15 of 27 bad results and flagged 0 of 13 good ones, a small sample, so expect it to miss things.
- Engines and attached files have only been used on one Mac, with one engine: DeepSeek V4.1 Flash on InferSSD. Turntables and GLBs have never been made on Linux. The chat page has only been checked in Chrome.
- Heads: one picture per message; long tasks don't call Heads yet; video and audio files from a Head download instead of playing in the chat.
- Chimera finds and links tools like Blender and ComfyUI but doesn't install them. It does download Ollama models itself.
- The library stores text (code, scripts, lessons), not generated meshes or images.

## Updating

**Every computer in a pool must run 0.6.1 or newer.** Above that, versions can mix, and each release's notes say which computers need it. As a rule, update the host first, because that's where routing lives, then the computers you chat from or start long tasks from; the others can wait. A device card shows a warning next to anyone on an older version.

Opening a newer Chimera replaces the older one that's still running. To check it worked, look at the bottom of **Settings**: it shows the version.

## Version history

Newest first. Dates are given where the project's history records them. Every release has its downloads on the [Releases page](https://github.com/swn5n/chimera/releases).

| Version | Released | What changed, in a line |
|---|---|---|
| **0.9.0** | Nov 9, 2026 | Engines (models outside Ollama), a new chat page, files and 3D turntables |
| **0.8.0** | Nov 1, 2026 | Long tasks spread across computers, scripts repaired, scene and render checked |
| **0.7.0** | Oct 30, 2026 | Hydra 1.0 helper model, script checks, Make a Head without code |
| **0.6.1** | Oct 25, 2026 | Heads run entirely on the computer that hosts them |
| **0.6.0** | Oct 24, 2026 | Heads: tools the whole pool can call; Quit really quits |
| **0.5.0** | | Plugins, later renamed Heads: the first tools the pool could call |
| **0.4.1** | | A new version replaces the running one; two hosts become one pool |
| **0.4.0** | | One open pool that anyone, on any network, joins automatically |
| **0.3.0** | | Auto-join on Wi-Fi, Keep going until done, your devices pitch in, Add to Dock |
| **0.2.0** | | Models tab, context limits, long tasks (Hydra), ratings and the library |

### 0.9.0: your own big model in the chat, and your files (Nov 9, 2026)

This release is about **your own big model in the chat**, and handing it your files.

- **Engines: models outside Ollama.** A model that runs from its own server, like DeepSeek V4.1 Flash read from an SSD by InferSSD, can be listed in `engines.json` in Chimera's data folder ([how](#your-own-big-model-and-files)). It shows in the chat's model picker under "This computer's own", starts on your first message to it, and stops after a while unused, when you press Stop, or when Chimera quits. Only this computer's own chats use it, never the pool, long tasks or Heads. Long replies are saved as they're written.
- **A new chat page.** Tables, lists and code blocks with Copy and Download; the model's thinking in a box that folds away when it answers; Write again and Edit; search (Cmd-K); groups to drag chats into; select and delete old chats. A web page or SVG the model writes can be shown right in the chat, sandboxed, and saved to the chat's folder.
- **Files for the engine.** With an engine picked, attach files or whole folders (**+ Files**, drop them, or paste). They're copied into the chat's folder, keeping their paths, and the model gets a note of facts about each: sizes, see-through backgrounds, lengths, a 3D model's parts by name and its size, and the words of text files. Before it reads them, Chimera makes a compressed GLB of each OBJ, FBX, STL or PLY model for web pages, a 72-frame turntable of each 3D model with your Blender, and a line on what each picture shows from `qwen3.8`, since the engine itself may read only text. Each has a switch by the attachments. In the chat, a turntable's thumbnail is a 360° viewer of the frames the model got.
- **Long tasks: Blender steps get Blender's real names.** Workers now see the names your Blender really has, so fewer scripts crash on a wrong one. In real tasks, the crashes it covers fell from 1.2 to 0.3 a task.

**Needs:** an engine needs its own server on the same computer, answering `/health` and speaking the OpenAI chat API, streamed. Turntables and GLBs need Blender on the computer you chat from, in the same sandbox as the script checks: macOS, or Linux with bubblewrap (not yet tried), not Windows. Picture lines need `qwen3.8`.

**Not tested:** engines and attached files have only been used on one Mac, with one engine. Dropping a folder from the Finder has only been tried against a stand-in folder tree. The chat page has only been checked in Chrome.

**Updating:** 0.9.0 shares a pool with computers on 0.6.1 or newer. Update the computers you chat from or start long tasks from; the others can wait.

### 0.8.0: long tasks that finish the job (Nov 1, 2026)

This release is about **Keep going until done**: long tasks that used to look finished without being finished.

- **Long tasks spread across your computers.** Each step now goes to the computer that will finish it soonest, going by how long steps have really taken there, not to the biggest model. Chats and the final combine work as before.
- **Scripts get repaired, not rewritten.** When a script crashes, a model gets the error and Blender's real names and fixes that spot, up to 8 times in a round. Later rounds edit the result instead of starting again, and the best round is the one you get.
- **The scene is checked as well as the script.** A task that asks for a scene needs a camera, and that camera has to show what you named, whether or not you mentioned a camera. Empty objects and a leftover default cube are caught too.
- **A model looks at the picture.** Once a scene passes everything else, a small render goes to a vision model on your computer, which says what it can make out. If the picture is blank or most of what you asked for can't be seen, the script goes back for repair. If it still can't be fixed, the reply says so in a note.

A reply with no note has been run, measured and looked at. It doesn't mean the picture is good.

**Needs:** script checks run on the computer that starts the task, on macOS or Linux, with Blender installed. The look also needs `qwen3.8` on that computer. Windows gets the routing but no script checks.

**Updating:** update the host first, because that's where routing lives. A computer needs 0.8.0 to get the new checks on tasks it starts, and computers on 0.6.1 or newer can stay in the same pool.

### 0.7.0: a helper model, script checks, Make a Head (Oct 30, 2026)

- **Hydra 1.0, the pool's own helper model.** Planning a long task, the review in Keep going until done, and the "should a Head do this?" check now run on Hydra 1.0, a small model trained for exactly those jobs. Long tasks no longer wait for the biggest model to plan or review. If no computer has it, or a task is too big for it (roughly 13,000 characters going into a plan, 16,000 into a review), the jobs go to the biggest model as before, and if Chimera can't read Hydra's answer it asks once more without it. The task card says which computer and model planned, combined and reviewed. [How to get it.](#the-helper-model-hydra-10)
- **Get it from the host, inside Chimera.** **Models → Helper → Get from host** copies the host's Hydra 1.0 into that computer's Ollama.
- **Long tasks check their own scripts.** In Keep going until done, a round's Blender or Python script runs before the review, in a sandbox on the computer that started the task. If it crashes, or the result was cut off, the next round is told exactly what went wrong. Turn it off with **Settings → Lending → Run my long tasks' scripts here to check them**. Not on Windows.
- **Make a Head without code.** **Settings → Heads → Make a Head** turns a program or a local server on your computer into a Head from a form, and **Try** runs it once, the way the pool would.
- **Fixes.** "Run on" and "Only my devices" now apply when Chimera picks a Head (before, a better-rated Head on a computer you hadn't allowed could win, and the step failed). Pressing Connect just after launch no longer says none of your models are shared.
- **Updating:** every computer needs 0.6.1 or newer. Only put Hydra 1.0 on computers running 0.7.0 or newer.

<details>
<summary><b>0.6.1: Heads run where they live (Oct 25, 2026)</b></summary>

- **Head work stays off the asking computer.** Before, the asking computer used a model to turn your request into a Head's settings (and to decide whether a Head should answer a words-only request). That call often went to the asker's own lending laptop, so its GPU spun up before the job was even handed off. Now the computer that runs the Head does it, with its own fastest model, unloads that model afterwards if nothing else was using it, and counts the time in the Head's charge.
- **Updating:** every computer in the pool needs 0.6.1 or newer. A 0.6.0 computer runs such Heads on their default settings, and the reply says so.

</details>

<details>
<summary><b>0.6.0: Heads (Oct 24, 2026)</b></summary>

- **Heads: your tools, callable by the whole pool.** A Head is a tool installed on one computer: studio shadows in Blender, image generation in ComfyUI, Hunyuan3D meshes. Anyone in the pool can use it without installing anything. Ask in Chat the way you'd ask a person. Chimera prefers a Head over an AI model when a Head does that job. Results come back into your chat with a Save link.
- **Words alone work.** Before, a Head was only considered when a picture was attached. Now a request in plain words goes to a Head when it's clearly asking for what that Head makes. The pool's fastest model double-checks, so *"how does image generation work?"* stays a conversation. Picking a specific model always uses that model.
- **Ratings decide, and Heads earn.** When several Heads could do a job, the best-rated one is picked. The owner earns bonus credits each time their Head does a job for someone else (half the run's charge again, at least 0.1), plus 1 credit each time someone else rates the result 4 or 5 stars.
- **Heads that wrap a local server** (ComfyUI, a 3D-model server) can reach it from inside the sandbox when they say so.
- **Ready to install:** `comfyui-image`, `hunyuan3d-mac`, `hunyuan3d-mesh` and a `TEMPLATE` in [`heads/`](heads/).
- **Quit really quits, and opening Chimera again brings the window back (Mac).** Chimera lives in the background and closing its window never quit it. On a Mac, double-clicking the app while it was running did nothing, which looked like "it says it's already running" with no way back in. Now opening Chimera again always brings the window back, and **Settings → Quit Chimera** ends it for real.
- **A bigger model list.** More curated models in **Models**: small fast ones, coders for 16 GB cards, vision, reasoning, and big ones for 48 to 96 GB, with a note on what an Nvidia/CUDA PC adds. Picture and 3D generation aren't Ollama models; they're Heads.

</details>

<details>
<summary><b>0.5.0: plugins, later renamed Heads</b></summary>

- **Tools the network can call.** Install one on your computer (**Settings → Heads → Open heads folder**, then drop its folder in) and anyone in the pool can use it: attach a picture in Chat (**+ Picture**, or paste or drop it), say what you want, and the result comes back into your chat with a Save link. The first one was **Perspective studio shadow**: send a picture of a machine and get it back on white with a realistic shadow, rendered in Blender on the computer that has Perspective. (That Head isn't in this repository.)
- **Ratings pick the plugin.** If several could do a job, Chimera uses the best-rated one. Your stars count toward it.
- **Plugins run sandboxed.** No network, your home folder and Chimera's own data hidden except the plugin's own folders, writes only to a throwaway folder. On Linux, install bubblewrap for that. Turn lending them off under Settings.
- Chimera now uses the newest Blender on a Mac with more than one installed.

</details>

<details>
<summary><b>0.4.1</b></summary>

- **Opening a new version now actually runs it.** Chimera lives in the background and only quits from Settings, so opening a newer Chimera while an old one was still running used to bring the old one's window back, and nothing changed. Now the new one tells the old one to quit and takes its place. Settings shows the version at the bottom.
- **Two hosts on one Wi-Fi become one pool.** If both computers ended up hosting, they used to sit there as two separate pools that couldn't see each other. Now any open host that finds another open host on the network merges into the better-established one. It checks every 20 seconds, so a laptop that wakes up later still merges.
- **Lost the host? It finds the pool again.** A computer that can't reach its hub for a minute looks for the pool again (the pool address, then an open host on the Wi-Fi), and if there's nothing, it starts a pool so the others aren't stranded. When the original host comes back, they merge.

</details>

<details>
<summary><b>0.4.0</b></summary>

- **One open pool: anyone, any network, joins automatically.** No more passing around codes. The host leaves the pool **open** (**Settings → Network → Let anyone join this pool**), and every other computer lands in it by itself: first by a **pool address** if one is set (works across the internet), then by finding the host on the local Wi-Fi, and if nobody is hosting yet, one computer elects itself the host so the pool always exists. Credits, not codes, stop anyone from asking questions without contributing.
- **Pool address, set once.** For friends in other houses, the host runs on an address reachable from anywhere (the simplest is Tailscale) and everyone puts it in **Settings → Network → Pool address** (`100.x.x.x:7480`). After that their Chimera joins the pool on every launch, wherever they are.
- **Fix: computers on the same Wi-Fi now actually see each other.** Discovery had been silently dropping its "who's hosting?" broadcasts.

</details>

<details>
<summary><b>0.3.0</b></summary>

- **Auto-join on the same Wi-Fi.** The host leaves auto-join on, and other computers find the network and join by themselves. The invite code still works for friends in other houses, and you can turn auto-join off to require it.
- **Keep going until done (looping tasks).** In Chat, turn on **Long task** and then **Keep going until done**. After each round the biggest model reviews the result against your goal and runs another round to improve it, up to six, stopping as soon as it's good enough. The card shows the round it's on.
- **Your devices pitch in.** When you start a long task, your other computers connect on their own to help, then stand down when it's finished (**Settings → Lending → Let my devices help my long tasks**).
- **Add to Dock.** Install Chimera so it sits in your Dock with the Chimera icon, in its own window with no browser tabs: **Settings → App → Add to Dock** (Chrome or Edge).
- **Testing credits.** Everyone starts with 1,000,000 credits so credits stay out of the way while you try things. Running out now actually stops you using other people's GPUs; your own devices stay free.

</details>

<details>
<summary><b>0.2.0</b></summary>

- **Models tab.** Shows how much memory this computer has for models, where each installed model sits on that gauge, and a recommended download for each job (planning, coding, vision and so on). Recommendations only include models that fit with room to spare. Models too big for a computer aren't lent at all.
- **Context limits.** Each model's longest context that fits on its computer is worked out from the model's architecture, and steps only go to devices with room for them.
- **Tools.** Each computer lists what it can do beyond chat: vision, audio, image, video, 3D mesh and audio generation (through Ollama or ComfyUI), Blender, and computer use (shown, but never lent to the network).
- **Runs anyway.** If nobody is lending, a chat runs on your own best model and says so.
- **Help wanted.** The Network tab compares what the pool waited for in the last hour with what your computer has, and suggests connecting, sharing a model, or downloading one that fits.
- **Long tasks (Hydra).** Turn on Long task in Chat. The biggest model plans the work as a few small steps, the steps run at the same time on different computers (each worker is told it's one piece of a bigger project), and the biggest model combines the results.
- **Ratings and the library.** Rate any reply out of 5 stars. For 4 or 5 stars Chimera asks what worked, and the pool's biggest model turns it into a reusable library entry. Long tasks reuse checked entries instead of asking a model again.
- **Checking the library, and exporting ratings.** When a lending computer has been idle for a while, the pool re-checks entries. The host can let their own computer test-run Python and Blender scripts, and can export every rated reply as a JSON-lines file for fine-tuning a small model later.

</details>

## Build from source

You need Go 1.24 or newer. From the repository folder:

```bash
cd app
./build.sh       # builds macOS (Apple silicon), Windows and Linux into ../dist
go test ./...    # the Go tests
```

`build.sh` writes `Chimera.app`, `Chimera-mac.zip`, `Chimera-windows.zip` and `Chimera-linux.tar.gz` to `dist/`. To rebuild the icons from `chimera_icon.png`, run `python3 app/packaging/make_icons.py chimera_icon.png` (needs Pillow).

Chimera is meant to be copied. It's one Go program that uses only the standard library, with a plain HTML, CSS and JavaScript interface embedded in it, so it's easy to read and to change. To remix it for your own setup, point your coding assistant at [app/README.md](app/README.md) (a file-by-file map and the network protocol) and [CLAUDE.md](CLAUDE.md) (the project's working notes: decisions, architecture and test results).

### What's in this repository

| Folder | What's in it |
|---|---|
| [`app/`](app/) | The app: one Go program, with its interface embedded. Start with [app/README.md](app/README.md). |
| [`heads/`](heads/) | Reference Heads and the [guide to making your own](heads/MAKE-A-HEAD.md). |
| [`hydra1/`](hydra1/) | How long tasks and the helper model work. |
| [`helper-model/`](helper-model/) | Training, evaluation and results for Hydra 1.0. |
| [`worker-model/`](worker-model/) | Work toward Hydra Worker 1.0, a model for the workers' steps. Research in progress. |
| [`tests/`](tests/) | End-to-end tests (Python) that start real Chimera copies against stand-in Ollama servers. The Go tests sit next to the code in `app/`. |
| [`docs/`](docs/) | Notes from real runs and design handoffs. |
| [`scripts/`](scripts/) | An install script one computer's set of tools was set up with. Read it before running it. |

Found a bug, or something in this README is confusing? [Open an issue](https://github.com/swn5n/chimera/issues).
