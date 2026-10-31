#!/usr/bin/env python3
"""Hunyuan3D textured-model Head for Chimera, for Macs: one picture in, a textured GLB out.

It runs the Hunyuan3D 2.1 Mac/MPS port (github.com/VladimirTalyzin/hunyuan3d-2.1-mac), which
scripts/chimera-studio-install.sh puts in ~/chimera-tools/hunyuan3d-2.1-mac. No server: each job
starts the port's own Python on job.py, which cuts the object out (rembg), builds the shape, frees
that model, paints a PBR texture ("Safe" preset: 6 views at 256 px, the only one MPS can run) and
renders a turntable preview. This file is the part Chimera runs; it needs the standard library only.

Environment: HUNYUAN3D_MAC_DIR (default ~/chimera-tools/hunyuan3d-2.1-mac), HF_HUB_CACHE (where
facebook/dinov2-giant is cached, default ~/.cache/huggingface/hub), U2NET_HOME (rembg's model,
default ~/.u2net).
"""
import base64, json, os, queue, random, re, shutil, subprocess, sys, threading, time

HOME = os.path.expanduser("~")
PORT = os.path.expanduser(os.environ.get("HUNYUAN3D_MAC_DIR") or "~/chimera-tools/hunyuan3d-2.1-mac")
PY = os.path.join(PORT, "venv", "bin", "python")
WEIGHTS = os.path.join(PORT, "weights", "Hunyuan3D-2.1")
PAINT = os.path.join(PORT, "Hunyuan3D-2.1", "hy3dpaint")
HUB = os.path.expanduser(os.environ.get("HF_HUB_CACHE") or "~/.cache/huggingface/hub")
DINO = os.path.join(HUB, "models--facebook--dinov2-giant")
U2NET = os.path.expanduser(os.environ.get("U2NET_HOME") or "~/.u2net")
JOB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "job.py")

# Where each stage sits on the progress bar, (start, end), with and without texturing.
SPANS = {True: {"load": (0.02, 0.06), "cutout": (0.06, 0.08), "shape": (0.08, 0.45), "texture": (0.45, 0.95), "preview": (0.95, 0.99)},
         False: {"load": (0.02, 0.08), "cutout": (0.08, 0.12), "shape": (0.12, 0.92), "texture": (0.92, 0.92), "preview": (0.92, 0.99)}}
TQDM = re.compile(r"(\d+)/(\d+) \[")
OOM = ("out of memory", "invalid buffer size", "failed to allocate", "mtlbuffer")


def progress(fraction, message):
    sys.stderr.write(json.dumps({"event": "progress", "fraction": max(0.0, min(1.0, fraction)), "message": message}) + "\n")
    sys.stderr.flush()


def link_dirs(path):
    """The folders a chain of symlinks passes through, ending with the real Python install it points at."""
    dirs, p = [], path
    for _ in range(16):
        dirs.append(os.path.dirname(p))
        if not os.path.islink(p):
            break
        t = os.readlink(p)
        p = os.path.normpath(t if os.path.isabs(t) else os.path.join(os.path.dirname(p), t))
    real = os.path.realpath(path)
    dirs.append(os.path.dirname(os.path.dirname(real)))  # .../cpython-3.11.x/bin/python3.11 -> .../cpython-3.11.x
    return dirs


def texture_missing():
    dr = os.path.join(PAINT, "DifferentiableRenderer")
    esr = os.path.join(PAINT, "ckpt", "RealESRGAN_x4plus.pth")
    if not os.path.isdir(os.path.join(WEIGHTS, "hunyuan3d-paintpbr-v2-1")):
        return "the paint weights (hunyuan3d-paintpbr-v2-1) aren't downloaded"
    built = os.path.isdir(dr) and any(n.startswith("mesh_inpaint_processor") and n.endswith(".so") for n in os.listdir(dr))
    if not built:
        return "mesh_inpaint_processor isn't built: run %s scripts/build_extensions.py in %s" % (PY, PORT)
    if not os.path.isfile(esr) or os.path.getsize(esr) < 20 << 20:
        return "RealESRGAN_x4plus.pth is missing or truncated at %s" % esr
    if not os.path.isdir(os.path.join(DINO, "snapshots")):
        return "facebook/dinov2-giant isn't in the Hugging Face cache (%s): run %s -c \"from huggingface_hub import snapshot_download as s; s('facebook/dinov2-giant')\"" % (HUB, PY)
    return ""


def probe():
    missing = []
    if not os.path.isfile(os.path.join(PORT, "paint.py")):
        missing.append("the Hunyuan3D 2.1 Mac port isn't at %s: run scripts/chimera-studio-install.sh from the Chimera folder, or set HUNYUAN3D_MAC_DIR" % PORT)
    elif not os.path.exists(PY):
        missing.append("the port has no venv at %s: re-run its install.sh" % os.path.dirname(os.path.dirname(PY)))
    elif not os.path.isfile(os.path.join(WEIGHTS, "hunyuan3d-dit-v2-1", "model.fp16.ckpt")):
        missing.append("the shape weights (hunyuan3d-dit-v2-1) aren't downloaded: re-run the port's install.sh")
    if not os.path.isfile(os.path.join(U2NET, "u2net.onnx")):
        missing.append("rembg's background model isn't downloaded: run %s -c \"from rembg import new_session; new_session('u2net')\"" % PY)
    reads = [PORT, os.path.realpath(PORT), DINO, U2NET]
    if os.path.exists(PY):
        reads += link_dirs(PY)
    reads = sorted(set(d for d in reads if os.path.isabs(d) and d.startswith(HOME + os.sep) and os.path.exists(d)))
    have = not missing
    tex = texture_missing() if have else ""
    caps = ["mesh-gen", "image-to-3d"] + (["pbr-texture"] if have and not tex else [])
    if tex:
        missing.append("texturing: " + tex)  # shapes still work
    return {"have": have, "caps": caps, "missing": missing, "sandbox": {"read": reads}}


def job_env(cache):
    env = {k: v for k, v in os.environ.items() if k in ("HOME", "PATH", "TMPDIR", "LANG")}
    hf = os.path.join(cache, "hf")
    env.update({
        "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
        # No downloads at run time (the sandbox has no network anyway): fail fast instead of retrying.
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
        # The model cache stays read-only; anything the libraries write goes to Chimera's cache for this Head.
        "HF_HOME": hf, "HF_HUB_CACHE": HUB, "HF_MODULES_CACHE": os.path.join(hf, "modules"),
        "U2NET_HOME": U2NET, "XDG_CACHE_HOME": os.path.join(cache, "xdg"), "TORCH_HOME": os.path.join(cache, "torch"),
        "MPLCONFIGDIR": os.path.join(cache, "mpl"), "GRADIO_ANALYTICS_ENABLED": "False", "TQDM_MININTERVAL": "2",
        # rembg -> pymatting compiles with numba's cache=True, which otherwise writes beside the venv's sources.
        "NUMBA_CACHE_DIR": os.path.join(cache, "numba"),
    })
    return env


def log_tail(path, n=4000, start=0):
    """The last n bytes of the log, but nothing from before byte `start`."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(start, f.tell() - n))
            return f.read().decode("utf-8", "replace").replace("\r", "\n")
    except OSError:
        return ""


def log_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def stage_fraction(stage, text, steps):
    """How far into a stage the libraries' progress bars say it is, and a note for the message."""
    bars = [(int(k), int(n)) for k, n in TQDM.findall(text) if int(n) > 0]
    if stage == "shape":
        diffusion = [b for b in bars if b[1] == steps]
        if diffusion and bars[-1][1] != steps:  # the steps are done; the bar after them decodes the volume
            return 0.9, " (turning it into a mesh)"
        if diffusion:
            k, n = diffusion[-1]
            return 0.85 * k / n, " (step %d/%d)" % (k, n)
    elif stage == "texture" and bars:  # the views' diffusion; baking the texture comes after it
        k, n = bars[-1]
        return 0.6 * k / n, " (%d/%d)" % (k, n)
    return 0.0, ""


def clock(s):
    s = int(s)
    return "%dm%02ds" % (s // 60, s % 60) if s >= 60 else "%ds" % s


def run(req, out_dir):
    img = req.get("image")
    if not img or not img.get("data_base64"):
        return {"ok": False, "error": "Attach a picture of the object to turn into a 3D model.", "retryable": False}, 2
    p = probe()
    if not p["have"]:
        return {"ok": False, "error": "Hunyuan3D can't run on this computer: " + "; ".join(p["missing"]), "retryable": True}, 3
    opts = req.get("options") or {}
    texture = bool(opts.get("texture", True))
    if texture and "pbr-texture" not in p["caps"]:
        return {"ok": False, "error": "Texturing can't run on this computer: " + texture_missing() + ". Ask again for an untextured mesh, or fix that first.", "retryable": True}, 3
    job = {
        "texture": texture,
        "octree": int(opts.get("octree_resolution", 256)),
        "steps": int(opts.get("steps", 30)),
        "guidance": float(opts.get("guidance", 5.0)),
        "seed": int(opts.get("seed", random.randint(0, 2**31 - 1))),
        "remove_bg": bool(opts.get("remove_background", True)),
    }
    work = os.path.join(out_dir, ".work")
    os.makedirs(work, exist_ok=True)
    ext = os.path.splitext(img.get("name") or "")[1].lower() or ".png"
    job["input"] = os.path.join(work, "input" + ext)
    job["work"] = work
    with open(job["input"], "wb") as f:
        f.write(base64.b64decode(img["data_base64"]))
    cache = os.environ.get("CHIMERA_CACHE") or os.path.join(work, "cache")
    env = job_env(cache)
    for k in ("HF_HOME", "XDG_CACHE_HOME", "TORCH_HOME", "MPLCONFIGDIR", "NUMBA_CACHE_DIR"):
        os.makedirs(env[k], exist_ok=True)

    logpath = os.path.join(work, "job.log")
    rfd, wfd = os.pipe()
    t0 = time.time()
    with open(logpath, "wb") as log:
        proc = subprocess.Popen([PY, JOB, str(wfd), PORT], stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                                cwd=work, env=env, pass_fds=(wfd,), close_fds=True)
    os.close(wfd)
    proc.stdin.write(json.dumps(job).encode())
    proc.stdin.close()
    events = queue.Queue()

    def read_events():
        with os.fdopen(rfd, "r", encoding="utf-8", errors="replace") as r:
            for line in r:
                try:
                    events.put(json.loads(line))
                except ValueError:
                    pass
        events.put(None)

    threading.Thread(target=read_events, daemon=True).start()
    spans = SPANS[texture]
    stage, message, done, error = "load", "Loading Hunyuan3D", None, None
    progress(0.01, "Starting Hunyuan3D 2.1 on this Mac's GPU")
    last, since = 0.0, 0
    while True:  # until job.py closes its end of the pipe, i.e. exits
        try:
            ev = events.get(timeout=1.0)
        except queue.Empty:
            ev = {}
        if ev is None:
            break
        if "stage" in ev:
            stage, message, last, since = ev["stage"], ev.get("message", ""), 0.0, log_size(logpath)
        elif "done" in ev:
            done = ev["done"]
        elif "error" in ev:
            error = ev
        if time.time() - last >= 10:  # Chimera wants a line at least every 20 s
            a, b = spans.get(stage, (0.0, 1.0))
            frac, note = stage_fraction(stage, log_tail(logpath, 4000, since), job["steps"])
            progress(a + (b - a) * frac, "%s%s, %s so far" % (message, note, clock(time.time() - t0)))
            last = time.time()
    code = proc.wait()
    try:  # the run folder is thrown away; keep the last log where the owner can read it
        shutil.copyfile(logpath, os.path.join(cache, "last-job.log"))
    except OSError:
        pass

    if error or not done:
        tail = log_tail(logpath, 6000)
        if error and error.get("bad_input"):
            return {"ok": False, "error": error["error"], "retryable": False}, 2
        why = error["error"] if error else "Hunyuan3D stopped (exit %d) without a result" % code
        if any(s in tail.lower() for s in OOM):
            return {"ok": False, "error": why + ". It ran out of GPU memory: try again once big models are unloaded, or at a lower octree_resolution.", "retryable": True}, 1
        lines = [l for l in tail.splitlines() if l.strip() and not TQDM.search(l)][-12:]
        return {"ok": False, "error": why + ". Last lines of its log:\n" + "\n".join(lines), "retryable": False}, 1

    base = re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.splitext(os.path.basename(img.get("name") or "object"))[0]).strip("_") or "object"
    files = []
    name = "%s_%s.glb" % (base, "textured" if texture else "mesh")
    shutil.move(done["glb"], os.path.join(out_dir, name))
    files.append({"path": name})
    if done.get("preview") and os.path.isfile(done["preview"]):
        shutil.move(done["preview"], os.path.join(out_dir, base + "_preview.png"))
        files.append({"path": base + "_preview.png"})
    size = os.path.getsize(os.path.join(out_dir, name))
    shutil.rmtree(work, ignore_errors=True)
    t = done.get("times", {})
    parts = ["shape %s at octree %d, %d steps" % (clock(t.get("shape", 0)), job["octree"], job["steps"])]
    if texture:
        parts.append("PBR texture %s (%s)" % (clock(t.get("texture", 0)), done.get("texture_note", "6 views at 256 px")))
    progress(1.0, "Done")
    return {"ok": True, "summary": "Hunyuan3D 2.1 made %s (%.1f MB, %s faces%s) in %s: %s, seed %d. Open it in Blender with File > Import > glTF 2.0."
            % (name, size / 1e6, "{:,}".format(done.get("faces", 0)), ", textured" if texture else ", untextured",
               clock(time.time() - t0), "; ".join(parts), job["seed"]),
            "files": files}, 0


def main():
    if sys.argv[1:2] == ["--probe"]:
        print(json.dumps(probe()))
        return 0
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CHIMERA_OUT", ".")
    try:
        req = json.load(sys.stdin)
    except Exception as e:
        print(json.dumps({"ok": False, "error": "bad input: %s" % e}))
        return 2
    try:
        result, code = run(req, out_dir)
    except Exception as e:
        result, code = {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "retryable": False}, 1
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    sys.exit(main())
