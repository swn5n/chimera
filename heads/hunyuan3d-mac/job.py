#!/usr/bin/env python3
"""One Hunyuan3D 2.1 job, run by run.py with the Mac port's own Python (its venv), in Chimera's sandbox.

    venv/bin/python job.py <event fd> <port folder>   < {"input", "work", "texture", "octree",
                                                         "steps", "guidance", "seed", "remove_bg"}

The libraries print freely to stdout/stderr (run.py keeps that as the log); this script's own
messages go to the event fd, one JSON object per line: {"stage", "message"}, then
{"done": {"glb", "preview", "faces", "times", "texture_note"}} or {"error", "bad_input"?}.

It does what the port's gradio_app.generate_3d and texture_3d_handler do, without importing
gradio_app: that builds the whole web UI and writes into the port's own outputs/ folder, which the
sandbox keeps read-only. Everything here is written into "work".
"""
import gc, json, os, sys, time, traceback

ev = os.fdopen(int(sys.argv[1]), "w", buffering=1)
PORT = sys.argv[2]
REPO = os.path.join(PORT, "Hunyuan3D-2.1")


def send(**kw):
    ev.write(json.dumps(kw) + "\n")


def stage(name, message):
    print("[chimera] " + message, flush=True)
    send(stage=name, message=message)


def main():
    job = json.load(sys.stdin)
    work = job["work"]
    times = {}
    # The same sys.path the port's gradio_app sets up, plus tests/ for its preview renderer.
    sys.path[:0] = [PORT, os.path.join(PORT, "tests")]
    for p in (REPO, os.path.join(REPO, "hy3dshape"), os.path.join(REPO, "hy3dpaint")):
        sys.path.insert(0, p)

    stage("load", "Loading Hunyuan3D")
    import backend  # before torch: it sets the MPS fallback and memory flags torch reads at start
    import compat_patches

    b = backend.detect()
    compat_patches.apply(b)
    print("[chimera] " + backend.describe(b), flush=True)
    import torch
    import trimesh
    from PIL import Image

    try:
        image = Image.open(job["input"])
        image.load()
    except Exception as e:
        send(error="That file isn't a picture Hunyuan3D can read (%s)." % type(e).__name__, bad_input=True)
        return 2

    # Cut-out and framing, as gradio_app.preprocess_image: RGBA, object centred on a square, 512 px.
    t = time.time()
    image = image.convert("RGBA")
    if job["remove_bg"]:
        stage("cutout", "Cutting the object out of its background")
        from rembg import new_session, remove

        image = remove(image, session=new_session("u2net"))
    w, h = image.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(image, ((side - w) // 2, (side - h) // 2), image)
    image = canvas.resize((512, 512), Image.LANCZOS)
    if image.getchannel("A").getbbox() is None:
        send(error="Nothing was left after cutting out the background: use a picture with one clear object in it.", bad_input=True)
        return 2
    times["cutout"] = time.time() - t

    stage("shape", "Building the shape")
    t = time.time()
    from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline

    compat_patches.patch_scheduler_timestep_lookup()
    pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        os.path.join(PORT, "weights", "Hunyuan3D-2.1"), subfolder="hunyuan3d-dit-v2-1",
        use_safetensors=False, variant="fp16", device=b.device, dtype=b.dtype)
    try:
        pipe.to(b.device)  # upstream's .to() returns None: called for its side effect only
    except Exception:
        for attr in ("model", "vae", "conditioner"):
            obj = getattr(pipe, attr, None)
            if obj is not None and hasattr(obj, "to"):
                obj.to(b.device)
    with torch.inference_mode():
        result = pipe(image=image, num_inference_steps=job["steps"], guidance_scale=job["guidance"],
                      octree_resolution=job["octree"], generator=torch.Generator(device="cpu").manual_seed(job["seed"]))
    mesh = result[0] if isinstance(result, (list, tuple)) else result
    if not isinstance(mesh, trimesh.Trimesh):
        mesh = getattr(mesh, "mesh", mesh)
    faces = int(len(mesh.faces))
    if faces == 0:
        send(error="Hunyuan3D made an empty shape from this picture.")
        return 1
    del pipe, result
    gc.collect()
    backend.empty_cache(b)
    times["shape"] = time.time() - t

    glb = os.path.join(work, "mesh.glb")
    note = ""
    if job["texture"]:
        stage("texture", "Painting the texture")
        t = time.time()
        import paint

        ok, why = paint.availability()
        if not ok:
            send(error="Texturing can't run: " + why)
            return 1
        src = os.path.join(work, "for_texture.obj")  # the paint pipeline reads its mesh from disk
        mesh.export(src)
        saved = paint.texture_mesh(mesh_path=src, image=image, b=b, preset="safe", use_remesh=True, output_dir=work,
                                   log=lambda m: print("[paint] " + m, flush=True))
        if not saved.get("glb") or not os.path.isfile(saved["glb"]):
            send(error="The paint step finished without a GLB (only %s)." % ", ".join(sorted(saved)))
            return 1
        glb = saved["glb"]
        params = paint.resolve_params("safe")
        note = "%d views at %d px, %d px texture" % (params["max_num_view"], params["resolution"], params["texture_size"])
        paint.unload()  # before reading the GPU again: the port saw a corrupt preview frame otherwise
        backend.empty_cache(b)
        times["texture"] = time.time() - t
    else:
        mesh.export(glb)

    stage("preview", "Rendering a preview")
    preview = ""
    try:
        import numpy as np
        import render_preview as rp

        verts, fs, uv, albedo = rp.load_mesh(glb)
        faces = int(len(fs))
        normals = rp.vertex_normals(verts, fs)
        device = rp.preview_device()
        tiles = [rp.render(verts, fs, normals, 360.0 * i / 4, 15.0, 384, device, uv=uv, albedo=albedo) for i in range(4)]
        preview = os.path.join(work, "preview.png")
        Image.fromarray(np.concatenate(tiles, axis=1)).save(preview)
    except Exception:
        print("[chimera] preview failed (the model is fine):\n" + traceback.format_exc(), flush=True)
        preview = ""
    send(done={"glb": glb, "preview": preview, "faces": faces, "times": times, "texture_note": note})
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:
        traceback.print_exc()
        send(error="%s: %s" % (type(e).__name__, str(e).splitlines()[0] if str(e) else ""))
        code = 1
    ev.close()
    sys.exit(code)
