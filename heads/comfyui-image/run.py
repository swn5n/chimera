#!/usr/bin/env python3
"""ComfyUI image generation Head for Chimera.

Talks to a ComfyUI server on THIS computer (default http://127.0.0.1:8188) over its HTTP API:
  GET  /system_stats                     is it up? (probe)
  GET  /object_info/CheckpointLoaderSimple  which checkpoints it has
  POST /prompt  {"prompt": <workflow>}   queue a workflow -> {"prompt_id"}
  GET  /history/<prompt_id>              finished? which files
  GET  /view?filename=&subfolder=&type=  fetch a result
  GET  /queue                            how many jobs are ahead (progress)

Workflow: by default a plain text-to-image graph (CheckpointLoaderSimple -> CLIPTextEncode x2 ->
EmptyLatentImage -> KSampler -> VAEDecode -> SaveImage) that works with SD 1.5 / SDXL checkpoints.
For Flux or anything custom, export your own graph from ComfyUI with "Save (API format)" as
workflow_api.json next to this file; these placeholders are filled in wherever they appear as string
values: {{prompt}} {{negative}} {{seed}} {{steps}} {{cfg}} {{width}} {{height}} {{count}} {{checkpoint}}.

Environment: COMFYUI_URL (default http://127.0.0.1:8188), COMFYUI_CHECKPOINT (default: the first one
ComfyUI lists; the "checkpoint" option overrides both). Standard library only.
"""
import copy, json, os, random, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")


def progress(fraction, message):
    sys.stderr.write(json.dumps({"event": "progress", "fraction": max(0.0, min(1.0, fraction)), "message": message}) + "\n")
    sys.stderr.flush()


def get(path, timeout=10):
    with urllib.request.urlopen(URL + path, timeout=timeout) as r:
        return r.read()


def get_json(path, timeout=10):
    return json.loads(get(path, timeout).decode())


def post_json(path, body, timeout=30):
    req = urllib.request.Request(URL + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def checkpoints():
    try:
        info = get_json("/object_info/CheckpointLoaderSimple")
        return info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    except Exception:
        return []


def probe():
    missing = []
    try:
        get_json("/system_stats", timeout=4)
    except Exception as e:
        missing.append("ComfyUI isn't answering at %s (%s). Start ComfyUI, or set COMFYUI_URL." % (URL, type(e).__name__))
        return {"have": False, "caps": [], "missing": missing, "sandbox": {"read": []}}
    cks = checkpoints()
    if not cks and not os.path.exists(os.path.join(HERE, "workflow_api.json")):
        missing.append("ComfyUI has no checkpoints (put one in ComfyUI/models/checkpoints) and there is no workflow_api.json here")
    return {"have": not missing, "caps": ["image-gen"], "missing": missing, "sandbox": {"read": []}}


def default_workflow(p):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": p["checkpoint"]}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": p["prompt"], "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": p["negative"], "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": p["width"], "height": p["height"], "batch_size": p["count"]}},
        "5": {"class_type": "KSampler", "inputs": {"seed": p["seed"], "steps": p["steps"], "cfg": p["cfg"], "sampler_name": "euler",
                                                   "scheduler": "normal", "denoise": 1.0, "model": ["1", 0], "positive": ["2", 0],
                                                   "negative": ["3", 0], "latent_image": ["4", 0]}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "chimera", "images": ["6", 0]}},
    }


def fill(obj, p):
    """Replace {{name}} placeholders in a custom API-format workflow; numbers stay numbers."""
    if isinstance(obj, dict):
        return {k: fill(v, p) for k, v in obj.items()}
    if isinstance(obj, list):
        return [fill(v, p) for v in obj]
    if isinstance(obj, str) and obj.startswith("{{") and obj.endswith("}}"):
        return p.get(obj[2:-2].strip(), obj)
    if isinstance(obj, str) and "{{" in obj:
        out = obj
        for k, v in p.items():
            out = out.replace("{{" + k + "}}", str(v))
        return out
    return obj


def run(req, out_dir):
    opts = req.get("options") or {}
    text = (req.get("request") or "").strip()
    if not text:
        return {"ok": False, "error": "Say what the picture should show.", "retryable": False}, 2
    cks = checkpoints()
    ck = opts.get("checkpoint") or os.environ.get("COMFYUI_CHECKPOINT") or (cks[0] if cks else "")
    if cks and ck not in cks:
        close = [c for c in cks if ck.lower() in c.lower()]
        ck = close[0] if close else cks[0]
    p = {
        "prompt": text, "negative": opts.get("negative", "blurry, low quality, watermark, text"),
        "width": int(opts.get("width", 1024)) // 8 * 8, "height": int(opts.get("height", 1024)) // 8 * 8,
        "steps": int(opts.get("steps", 25)), "cfg": float(opts.get("cfg", 6.0)),
        "seed": int(opts.get("seed", random.randint(0, 2**32 - 1))), "count": int(opts.get("count", 1)),
        "checkpoint": ck,
    }
    custom = os.path.join(HERE, "workflow_api.json")
    if os.path.exists(custom):
        with open(custom) as f:
            wf = fill(json.load(f), p)
        how = "your workflow_api.json"
    else:
        if not ck:
            return {"ok": False, "error": "ComfyUI has no checkpoints to generate with.", "retryable": True}, 3
        wf = default_workflow(p)
        how = ck
    progress(0.05, "Queueing in ComfyUI (%s)" % how)
    try:
        q = post_json("/prompt", {"prompt": wf, "client_id": "chimera-%d" % os.getpid()})
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        return {"ok": False, "error": "ComfyUI refused the workflow: %s" % detail, "retryable": False}, 1
    pid = q.get("prompt_id")
    if not pid:
        return {"ok": False, "error": "ComfyUI gave no prompt id: %s" % json.dumps(q)[:200], "retryable": True}, 1
    t0 = time.time()
    last = ""
    while True:
        time.sleep(1.0)
        hist = get_json("/history/" + pid)
        if pid in hist:
            break
        try:
            qs = get_json("/queue")
            ahead = len(qs.get("queue_pending", []))
            msg = "Rendering" if not ahead else "Waiting behind %d job(s)" % ahead
        except Exception:
            msg = "Rendering"
        elapsed = time.time() - t0
        frac = 0.1 + 0.8 * min(1.0, elapsed / max(10.0, p["steps"] * 1.5))
        if msg != last or int(elapsed) % 5 == 0:
            progress(frac, "%s… %ds" % (msg, int(elapsed)))
            last = msg
    outputs = hist[pid].get("outputs", {})
    status = hist[pid].get("status", {})
    if status.get("status_str") == "error":
        msgs = status.get("messages", [])
        return {"ok": False, "error": "ComfyUI failed: %s" % json.dumps(msgs)[:400], "retryable": False}, 1
    files = []
    for node in outputs.values():
        for im in node.get("images", []):
            qs = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""), "type": im.get("type", "output")})
            data = get("/view?" + qs, timeout=60)
            name = "image_%d_%s.png" % (len(files) + 1, p["seed"])
            with open(os.path.join(out_dir, name), "wb") as f:
                f.write(data)
            files.append({"path": name})
    if not files:
        return {"ok": False, "error": "ComfyUI finished but saved no images (does the workflow end in SaveImage?).", "retryable": False}, 1
    progress(1.0, "Done")
    return {"ok": True, "summary": "ComfyUI made %d picture(s) with %s: %dx%d, %d steps, seed %d, in %ds."
            % (len(files), ck or "your workflow", p["width"], p["height"], p["steps"], p["seed"], int(time.time() - t0)),
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
    except urllib.error.URLError as e:
        result, code = {"ok": False, "error": "Couldn't reach ComfyUI at %s: %s" % (URL, e), "retryable": True}, 3
    except Exception as e:
        result, code = {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "retryable": False}, 1
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    sys.exit(main())
