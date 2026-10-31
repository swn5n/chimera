# Make your own Head

A Head lets everyone in the pool use a tool on your computer: a script, Blender, a 3D or image model
server. Requests come in from the chat and the Head runs on your computer. What it makes goes back to the
person who asked, and you earn credits for each run.

There are two ways to make one:

- **Make a Head, in Chimera, no code.** Settings → Heads → **Make a Head**. This works whenever your
  tool is a **program** you can run from Terminal, or a **server** on your computer that takes one web
  request and answers with the result. Most tools are one of the two.
- **Write one by hand**, a `run.py` script. You need this only when the tool needs real logic between
  steps: a job queue you have to poll, several calls in a row, a ComfyUI workflow. See
  [Write one by hand](#write-one-by-hand).

---

## 1. Before you start: answer these

Write the answers down; the form asks for exactly these.

| Question | Example (background remover) |
|---|---|
| What does it make or do, in one sentence? | Cuts the subject out of a picture and makes the background transparent. |
| When should the pool use it? Use the words people would type. | Someone attaches a picture and asks to remove the background, cut out the subject, or make it transparent. |
| When should it **not** be used? | Changing what's in the picture. |
| What does it work on? | A picture / words only / a picture, or words alone |
| What does it give back? | Pictures, 3D models, video, sound, text, or any file |
| How do you run it today? | `rembg i photo.png cutout.png` in Terminal, so it's a **program** |
| Which settings might people ask for in words? | none (a shadow Head might have *strength*, *angle*) |
| Does it work with no internet? | It must. Heads have no internet, so download its models first. |

**Program or server?**

- If you can run it in Terminal with a file and get a file back, it's a **program** (rembg, ffmpeg,
  ImageMagick, `blender -b`, your own Python script, a compiled tool).
- If it's already running in the background and you use it through a web page or its API, it's a
  **server** (AUTOMATIC1111/Forge with `--api`, a Hunyuan3D or TRELLIS API server, a TTS server). Look up
  its API docs: you need the address (like `http://127.0.0.1:8080/generate`) and the JSON it expects.
- If it's only a button in an app (a Blender add-on, for example), it needs a few lines of script so it
  can run without the button. See [A Blender script or add-on](#a-blender-script-or-add-on).

**Run it by hand once first**, exactly as the Head will, so it downloads whatever it needs while it still
has internet.

---

## 2. Make it

1. Open **Settings → Heads → Make a Head**.
2. **Start from** an example close to yours (background remover, Blender script, ffmpeg clip, read
   aloud, AUTOMATIC1111 pictures, Hunyuan3D mesh), or start empty.
3. **What it is.** Fill in the name and the two sentences from step 1. *When the pool should use it*
   matters most: a model reads it to decide which requests go to your Head. Keywords help it get found.
4. **What goes in and comes out.** Pick what it works on and click every kind of thing it gives back.
   The person asking only keeps files of those kinds.
5. **How it runs.** Choose *A program* or *A server* and fill in the command or the address. Click the
   placeholder buttons to insert them; they're listed [below](#placeholders).
6. **Settings people can ask for** (optional). Add one for each thing people might ask for in words, with
   a default. The fastest model on your computer reads them from the request ("make the shadow softer" →
   softness 0.8). Use each one in the command or JSON as `{{its_name}}`.
7. **Timing.** About how long one run takes (it drives the progress bar) and when to give up.
8. **Save and try it.** Type what someone would ask, add a picture if it needs one, and press **Run it
   here**. It runs exactly as it would for the pool, sandbox included. If something's wrong, the message
   says what (see [When it doesn't work](#when-it-doesnt-work)). Press **Change it**, fix, save, try
   again.
9. Leave **Let the pool use my Heads** on and press **Connect**. Your Head appears for everyone.

To change it later: Settings → Heads → **Change** next to it. Every save is a new version (1.0.0, 1.0.1, …)
so the pool knows it changed. **Try** works on every Head, including ones written by hand.

---

## Placeholders

Chimera fills these in for each request.

**Program Heads** (in the command):

| Placeholder | Becomes |
|---|---|
| `{{input}}` | the attached picture, saved as a file (its full path) |
| `{{prompt}}` | the words of the request, as one argument |
| `{{out}}` | the folder to save results in. Save your files here |
| `{{name}}` | the picture's name without its extension (`chair`), or the Head's id without a picture |
| `{{cache}}` | a folder kept between runs (models, caches) |
| `{{blender}}` | Blender's full path on this computer |
| `{{seed}}` | a random number (unless you add a setting called `seed`) |
| `{{your_setting}}` | the setting's value, read from the request or its default |

The command runs the program directly, never through a shell, so a request's words can't run anything:
`{{prompt}}` is always one argument. Quote paths with spaces: `"/Applications/My Tool.app/Contents/MacOS/tool"`.
To use shell features (pipes, `&&`), write `/bin/sh -c "…"` yourself.

A **yes/no setting** written on its own in the command adds its own text: set *When yes, the command gets*
to `--texture` and *When no* to nothing, and `{{texture}}` becomes `--texture` or disappears.

**Server Heads** (in the address and the JSON): `{{prompt}}`, `{{name}}`, `{{seed}}`, your settings, and
for the picture `{{input_base64}}` (base64) or `{{input_data_url}}` (`data:image/png;base64,…`). Or send
the picture as a file upload by filling in *Upload the picture as a file named*.

Put every placeholder in the JSON in quotes. A value that is only a placeholder keeps its type:
`"steps": "{{steps}}"` sends the number `30`, `"texture": "{{texture}}"` sends `true`.

## How results come back

- **Program:** whatever it saves in `{{out}}`. If it saves next to the picture or in the folder it runs
  in instead, that counts too. For a Text Head, what it prints becomes the answer.
- **Server:** if it answers with a file, that's the result. If it answers with JSON, Chimera finds
  base64 files in it by itself. If it doesn't, set *Where the result is* to the field, like `images` or
  `images.0` or `data.mesh`. That field may also hold a link to the file on the same server, or the path
  where the server saved it. If that path is in your home folder, add its folder under *Folders it reads*.
  For a Text Head, a field like `text`, `response` or `caption` becomes the answer.

---

## Examples

### Background remover (program)

```sh
pipx install "rembg[cli]"          # or: pip install "rembg[cli]" in a venv
rembg i ~/Desktop/test.jpg ~/Desktop/out.png   # once by hand: downloads its model to ~/.u2net
which rembg                        # its full path, for the command
```

Command: `/Users/you/.local/bin/rembg i {{input}} {{out}}/{{name}}_cutout.png`
Works on: a picture. Gives back: pictures. Folders it reads: `~/.u2net` (where it keeps the model).

### A Blender script or add-on

Blender runs headless with `-b`. Pass the picture and the output folder after `--`:

Command: `{{blender}} -b --python /Users/you/heads-scripts/shadow.py -- {{input}} {{out}} {{softness}}`

`shadow.py` reads them from `sys.argv` and does the work, for example by calling your add-on's operator:

```python
import bpy, sys
args = sys.argv[sys.argv.index("--") + 1:]
picture, out_dir, softness = args[0], args[1], float(args[2])
# … load the picture, call your add-on (bpy.ops.your_addon.do_thing(...)), set up the render …
bpy.context.scene.render.filepath = out_dir + "/result.png"
bpy.ops.render.render(write_still=True)
```

Your Blender settings folder (where add-ons are installed) is readable automatically. Leave out
`--factory-startup`, which turns add-ons off. Add a `.blend` file to the command (`{{blender}} -b
/Users/you/scene.blend --python …`) to start from a prepared scene. Its folder becomes readable too.

### Pictures from words (AUTOMATIC1111 or Forge server)

Start the web UI with `--api`. Then: server, POST `http://127.0.0.1:7860/sdapi/v1/txt2img`,
JSON `{"prompt": "{{prompt}}", "steps": "{{steps}}", "width": "{{width}}", "height": "{{height}}", "seed": "{{seed}}"}`,
Where the result is: `images`. Works on: words only. Gives back: pictures. The example in the form has all
of this.

### 3D mesh from a picture (Hunyuan3D server)

Start the server on this computer only, for example (Hunyuan3D 2.1 on a Mac):
`python api_server.py --host 127.0.0.1 --port 8080 --device mps`. Then: server, POST
`http://127.0.0.1:8080/generate`, JSON `{"image": "{{input_base64}}", "seed": "{{seed}}", "type": "glb"}`,
Address that answers when the server is up: `http://127.0.0.1:8080/health` (2.0 uses `/healthcheck`).
Works on: a picture. Gives back: 3D models. Check your version's API for the field names; the form's
example uses Hunyuan3D 2.0's.

---

## When it doesn't work

Try it from the maker; the message says what happened.

| It says | Do this |
|---|---|
| Can't find the program *x* | Write its full path. In Terminal, `which x` prints it. Chimera opened from the Dock doesn't see your Terminal's PATH. |
| Nothing answers at http://127.0.0.1:… | Start the server, and check the port. |
| *x* stopped with exit code *n*, followed by its last lines | Run the same command in Terminal with a real file in place of `{{input}}` and a folder in place of `{{out}}`. |
| Permission denied / Operation not permitted, or a file it can't find in your home folder | The sandbox hides your home folder. Add the folder under **Folders it reads**. |
| It tries to download something and fails | No internet inside a Head. Run it once by hand so it downloads, and list where it saved under Folders it reads. |
| It can't write its settings or cache | A Head can only write to `{{out}}`, `{{cache}}` and temp folders. Point the tool's cache option at `{{cache}}`. |
| Left out: the Head says it makes … | Click the right kind under **It gives back**. |
| finished but saved no file | Program: put `{{out}}` where it saves. Server: set *Where the result is*. |
| Can't run here: this computer can't sandbox Heads | Windows: Settings → Heads → **Run Heads without a sandbox on this computer**. Then the Head runs with your own permissions, so only run tools you trust. |

For more detail, look in the log: `~/Library/Application Support/Chimera/chimera.log`.

## Share it

A made Head is an ordinary folder: `plugin.json` and `run.py`, in Settings → Heads → **Open heads
folder** (or **Try** → **Open its folder**). Copy it into another computer's heads folder. That computer
needs the same program or server, at the same paths, or open it there with **Change** and fix the paths.

---

## Write one by hand

For tools that need logic: an async API (send a job, poll for it), several requests in a row, files to
pick apart, a ComfyUI workflow (the `comfyui-image` Head here already takes your own exported workflow).

1. Copy `heads/TEMPLATE/` into the heads folder and rename it to your Head's id.
2. Edit `plugin.json` ([fields](README.md#write-one)) and fill in `run()` in `run.py`.
3. Test it: Settings → Heads → **Try**, or from Terminal with `chimera --plugin-test <folder>`
   ([how](README.md#try-a-head-alone-exactly-as-a-worker-runs-it-sandbox-included)).

The whole contract fits on one screen: [README.md → Write one](README.md#write-one). It's also what to
give an AI assistant (any of them, Claude or the pool's own models) if you'd rather have one write it:
paste the contract and the TEMPLATE, and describe your tool's command or API.

## Before you lend it

- [ ] *When the pool should use it* says the cases in people's words, and *Not for* rules out the near misses.
- [ ] Try works with a request that should use it, with the picture types people will send.
- [ ] Every setting has a sensible default.
- [ ] *Give up after* is long enough for the slowest run, but not hours more.
- [ ] Its server (if any) starts with your computer, or you start it before you Connect.
