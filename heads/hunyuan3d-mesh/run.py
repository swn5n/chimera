#!/usr/bin/env python3
"""Hunyuan3D mesh Head for Chimera: one picture in, a GLB (or OBJ) out.

It talks to the Hunyuan3D 2 / 2.1 API server on THIS computer. From the Hunyuan3D-2 repo:
    python api_server.py --host 127.0.0.1 --port 8080            # add --enable_tex for textures
Its HTTP API (the Head tries the async pair first, then the one-shot call):
  GET  /healthcheck                      {"status": "healthy"}                 (probe)
  POST /send      {image, ...}           {"uid"}                               (queue a job)
  GET  /status/<uid>                     {"status": "processing"|"completed"|"error", "model_base64"}
  POST /generate  {image, ...}           the mesh file's bytes                 (one shot)
The picture goes as base64; the server removes the background itself.

Environment: HUNYUAN3D_URL (default http://127.0.0.1:8080). Standard library only.
"""
import base64, json, os, random, sys, time, urllib.error, urllib.request

URL = os.environ.get("HUNYUAN3D_URL", "http://127.0.0.1:8080").rstrip("/")


def progress(fraction, message):
    sys.stderr.write(json.dumps({"event": "progress", "fraction": max(0.0, min(1.0, fraction)), "message": message}) + "\n")
    sys.stderr.flush()


def get_json(path, timeout=10):
    with urllib.request.urlopen(URL + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


def post(path, body, timeout=3600):
    req = urllib.request.Request(URL + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")


def probe():
    try:
        h = get_json("/healthcheck", timeout=4)
        ok = str(h.get("status", "")).lower() in ("healthy", "ok")
    except Exception as e:
        return {"have": False, "caps": [], "sandbox": {"read": []},
                "missing": ["Hunyuan3D's API server isn't answering at %s (%s). Start it: python api_server.py --port 8080, or set HUNYUAN3D_URL." % (URL, type(e).__name__)]}
    return {"have": ok, "caps": ["mesh-gen", "image-to-3d"], "missing": [] if ok else ["server reports %s" % h], "sandbox": {"read": []}}


def run(req, out_dir):
    img = req.get("image")
    if not img or not img.get("data_base64"):
        return {"ok": False, "error": "Attach a picture of the object to turn into a mesh.", "retryable": False}, 2
    opts = req.get("options") or {}
    fmt = opts.get("format", "glb")
    body = {
        "image": img["data_base64"],
        "texture": bool(opts.get("texture", False)),
        "seed": int(opts.get("seed", random.randint(0, 2**31 - 1))),
        "octree_resolution": int(opts.get("octree_resolution", 256)),
        "num_inference_steps": int(opts.get("steps", 30)),
        "guidance_scale": float(opts.get("guidance", 7.5)),
        "type": fmt,
    }
    t0 = time.time()
    data = None
    # Async path: progress while it works.
    try:
        progress(0.05, "Sending the picture to Hunyuan3D")
        raw, _ = post("/send", body, timeout=60)
        uid = json.loads(raw.decode()).get("uid")
        if uid:
            est = 90.0 + (240.0 if body["texture"] else 0.0)
            while True:
                time.sleep(2.0)
                st = get_json("/status/" + uid, timeout=30)
                s = str(st.get("status", "")).lower()
                if s == "completed":
                    data = base64.b64decode(st["model_base64"])
                    break
                if s == "error":
                    return {"ok": False, "error": "Hunyuan3D failed: %s" % st.get("message", st), "retryable": False}, 1
                el = time.time() - t0
                progress(0.1 + 0.8 * min(1.0, el / est), "Building the mesh… %ds%s" % (int(el), " (texturing too)" if body["texture"] else ""))
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        # Older server without /send: one-shot /generate.
    if data is None:
        progress(0.1, "Building the mesh (this server answers when it's done)")
        data, ctype = post("/generate", body)
        if "json" in ctype:
            try:
                j = json.loads(data.decode())
                return {"ok": False, "error": "Hunyuan3D: %s" % j, "retryable": False}, 1
            except Exception:
                pass
    if not data or len(data) < 64:
        return {"ok": False, "error": "Hunyuan3D returned an empty mesh.", "retryable": True}, 1
    base = os.path.splitext(os.path.basename(img.get("name") or "object"))[0] or "object"
    name = "%s_mesh.%s" % (base, fmt)
    with open(os.path.join(out_dir, name), "wb") as f:
        f.write(data)
    progress(1.0, "Done")
    return {"ok": True, "summary": "Hunyuan3D made %s (%.1f MB) at octree %d, %d steps%s, in %ds. Open it in Blender with File → Import → glTF."
            % (name, len(data) / 1e6, body["octree_resolution"], body["num_inference_steps"], ", textured" if body["texture"] else "", int(time.time() - t0)),
            "files": [{"path": name}]}, 0


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
        result, code = {"ok": False, "error": "Couldn't reach Hunyuan3D at %s: %s" % (URL, e), "retryable": True}, 3
    except Exception as e:
        result, code = {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "retryable": False}, 1
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    sys.exit(main())
