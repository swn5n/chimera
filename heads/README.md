# Heads: tools the whole pool can call

A **Head** is a tool installed on one computer that anyone in the Chimera pool can use. Chimera has
many heads — that's the point. Perspective's studio shadows on the laptop, an image generator in
ComfyUI on the Nvidia PC, Hunyuan3D meshes on the Studio: each one lives where its models and programs
are, and the pool routes requests to it. The person asking needs nothing installed.

When someone asks for what a Head makes, Chimera prefers the Head over an AI model — a deterministic
tool that does one job well beats a general model guessing (a real shadow render beats an image model's
idea of a shadow). Star ratings decide between Heads that could all do a job, and **the Head's owner
earns credits for bridging the gap**: half the run's charge again, never less than 0.1 per run for
someone else, plus 1 credit each time someone else rates the result 4 or 5 stars.

(Technically a Head is a *plugin*: its folder holds a `plugin.json`, and the code and API say
`plugin`. Same thing.)

## Install one

1. Settings → **Heads** → **Open heads folder** (`~/Library/Application Support/Chimera/plugins/` on a
   Mac, `%AppData%\Chimera\plugins\` on Windows).
2. Copy the Head's folder in (for example `comfyui-image/`).
3. Within a minute **Tools** lists it. If it says *Can't run here*, the note says what's missing — usually
   a server to start or a program to install. Check by hand with `python3 <folder>/run.py --probe`.
4. Leave **Let the pool use my Heads** on and press **Connect**. (Lending needs Ollama running with at
   least one shared model, for now. The fastest shared model also reads each job's options from the
   request, on this computer, so keep a small fast one shared.)

Heads run **sandboxed**: no internet, your home folder hidden except the Head's own folder and the
folders its probe asks for, writes only into a throwaway folder and the Head's cache. A Head that
declares `"network": "localhost"` may talk to servers on your own computer (ComfyUI, a model server) —
on a Mac still nothing beyond the computer; on Linux that means the normal network, so the log says so.
Windows has no sandbox Chimera trusts, so Heads are off there by default; the owner can allow them
anyway under Settings → Heads → **Run Heads without a sandbox on this computer** (then a Head runs with
your normal permissions — install only Heads you trust). That's the switch for an Nvidia PC that hosts
ComfyUI for the pool.

## The Heads in this folder

| Folder | What it does | Needs on that computer | Input |
|---|---|---|---|
| `TEMPLATE/` | A skeleton to copy for a new Head | — | either |
| `comfyui-image/` | Pictures from words via ComfyUI's API (SD 1.5 / SDXL / Flux, any checkpoint you have; or your own exported `workflow_api.json`) | ComfyUI running (default `http://127.0.0.1:8188`) with a checkpoint | words |
| `hunyuan3d-mesh/` | A 3D mesh (GLB/OBJ) from one picture via Hunyuan3D 2's API server, optionally textured | `python api_server.py --port 8080` from the Hunyuan3D-2 repo (`--enable_tex` for textures) | picture |
| *(on the laptop)* `perspective-shadow/` | Studio shadows for pictures of machines (Perspective in Blender) — see the laptop's handoff | Blender 5 + Perspective | picture |

The two reference Heads were tested through Chimera's real sandboxed runner against servers that speak
the same API; they have **not** been run against real ComfyUI / Hunyuan3D yet. If one trips on your
setup, run it alone (below) and send the output.

### ComfyUI notes

- The default graph is plain text-to-image and suits SD 1.5 / SDXL checkpoints. For Flux or a tuned
  pipeline: in ComfyUI, enable dev mode, build your graph, **Save (API format)**, and put it next to
  `run.py` as `workflow_api.json`. Placeholders are filled wherever they appear as values:
  `{{prompt}} {{negative}} {{seed}} {{steps}} {{cfg}} {{width}} {{height}} {{count}} {{checkpoint}}`.
- `COMFYUI_URL` and `COMFYUI_CHECKPOINT` can be set in the environment Chimera is launched with
  (`launchctl setenv COMFYUI_URL http://127.0.0.1:8188` on a Mac before opening it).
- This is where an **Nvidia PC** shines: SDXL and Flux with CUDA are several times faster than on a Mac,
  and that computer's Head serves the whole pool.

## Try a Head alone (exactly as a worker runs it, sandbox included)

```sh
# words only
echo '{"options":{"width":768},"request":"a red car at sunset","return":"files"}' \
  | /Applications/Chimera.app/Contents/MacOS/chimera --plugin-test ~/Library/Application\ Support/Chimera/plugins/comfyui-image --plugin-out /tmp/out

# with a picture
python3 -c 'import base64,json,sys; print(json.dumps({"image":{"name":"chair.png","data_base64":base64.b64encode(open(sys.argv[1],"rb").read()).decode()},"options":{},"request":"a 3d model of this","return":"files"}))' chair.png \
  | /Applications/Chimera.app/Contents/MacOS/chimera --plugin-test ~/Library/Application\ Support/Chimera/plugins/hunyuan3d-mesh --plugin-out /tmp/out
```

## Write one

Copy `TEMPLATE/`, rename the folder to your id, edit `plugin.json` and fill in `run()` in `run.py`.

`plugin.json`:

| Field | Meaning |
|---|---|
| `id` | `^[a-z0-9][a-z0-9-]{1,47}$`, unique in the pool |
| `name`, `summary` | Shown to people; also matched against requests (the name weighs most) |
| `when_to_use`, `tags`, `task_kinds` | Matched against requests. The fastest model also reads `when_to_use` to decide whether a words-only request is a job for this Head, so write the cases in the words people use |
| `when_not_to_use` | Shown in the Library ("Not for: …") |
| `accepts` | MIME types of a picture the Head takes (`image/*` works). **Empty = words only**, no file needed |
| `optional_input` | `true`: works both with a picture and from words alone |
| `produces` | MIME types it returns — the asker keeps only these (`image/png`, `model/gltf-binary`, `model/obj`, …) |
| `entry`, `interpreter` | the script inside the folder; `python3` (default) or `sh` |
| `network` | leave out, or `"localhost"` to reach servers on the same computer |
| `options` | a JSON-schema object: the fastest shared model on the Head's computer fills it from the request's words, Chimera checks the values |
| `env` | environment variable names passed through (never `CHIMERA_*`) |
| `timeout_s` | 30–7200, default 1800 |

The entry script's contract:

| | |
|---|---|
| stdin | one JSON object: `{"image": {"name", "data_base64"}, "options": {…}, "request": "the words", "return": "files"}` — `image` is **absent** for a words-only request |
| `argv[1]` / `CHIMERA_OUT` | the output folder; write results there |
| stdout | the last JSON line: `{"ok": true, "summary": "…", "files": [{"path": "a.png"}]}` or `{"ok": false, "error": "…", "retryable": true}` |
| stderr | progress, one JSON line each: `{"event": "progress", "fraction": 0.4, "message": "…"}` (send one at least every 20 s during long work) |
| exit | 0 done, 1 failed, 2 bad input, 3 not installed on this computer |
| `--probe` | print `{"have": true, "caps": [...], "missing": [...], "sandbox": {"read": [absolute folders it needs]}}` |
| `CHIMERA_CACHE` | a folder kept between runs (models, analyses) |

How a request reaches a Head: with a picture attached, the hub lists Heads that accept that picture
type and match the words, best rated first, and the top one runs. With words only, the same list is
made from Heads that need no picture; then the pool's fastest model is asked, with the Head's own
description in front of it, *should this tool handle the request?* — so "generate an image of a red
car" goes to the image Head and "how does image generation work?" stays a conversation. Picking a
specific model in the composer keeps a words-only message away from Heads.

The asker's computer only sends the request and shows what comes back. The computer that has the Head
reads the options from the words with its own model and runs the Head, and the *should this tool
handle it?* question goes to another computer's model. The asker's own computer does Head work only
when the Head is installed on it: then it's the person's own Head.

## Ideas for more Heads

- **Image → image** in ComfyUI (upscale, inpaint, style transfer): add `"accepts": ["image/*"]` and
  `"optional_input": true`, upload the picture with `POST /upload/image`, and use a LoadImage node.
- **TRELLIS / other image-to-3D** servers: same shape as `hunyuan3d-mesh`.
- **Video**: Wan / CogVideo in ComfyUI, `produces: ["video/mp4"]` (files download; no inline player yet).
- **Audio**: music or speech generation (ACE-Step, a TTS server) — `produces: ["audio/wav"]`.
- **Blender**: anything a headless `blender -b --python` can do; `CHIMERA_BLENDER` has the path.
- **Deterministic utilities**: ffmpeg conversions, OCR, mesh repair, photogrammetry. These are exactly
  the "regular pre-deterministic techniques" worth more than a model's guess.
