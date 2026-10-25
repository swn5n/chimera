#!/usr/bin/env python3
"""Template for a Chimera Head (plugin). Copy this folder, rename it to your id, and fill in run().

Contract (see heads/README.md):
  --probe            print JSON {"have": bool, "caps": [...], "missing": [...], "sandbox": {"read": [...]}} and exit 0
  normal run         stdin:  {"image": {"name", "data_base64"} (absent for words-only requests),
                              "options": {...}, "request": "the person's words", "return": "files"}
                     argv[1] / $CHIMERA_OUT: folder to write results into
                     stderr: progress lines {"event": "progress", "fraction": 0..1, "message": "..."}
                     stdout: last line {"ok": true, "summary": "...", "files": [{"path": "name.ext"}]}
                             or        {"ok": false, "error": "...", "retryable": bool}
                     exit:   0 done, 1 failed, 2 bad input, 3 not installed on this computer
Environment you get: HOME PATH TMPDIR LANG, your manifest's "env" names, CHIMERA_OUT, CHIMERA_CACHE
(kept between runs), CHIMERA_BLENDER (path, if found), CHIMERA_STEP.
The sandbox: no internet; servers on this computer only if plugin.json says "network": "localhost";
your home folder hidden except this folder, the folders your probe lists, CHIMERA_OUT and CHIMERA_CACHE.
"""
import base64, json, os, sys


def progress(fraction, message):
    sys.stderr.write(json.dumps({"event": "progress", "fraction": fraction, "message": message}) + "\n")
    sys.stderr.flush()


def probe():
    missing = []
    # Check what you need: a program, a model file, a server. For example:
    # if shutil.which("ffmpeg") is None: missing.append("ffmpeg")
    return {"have": not missing, "caps": ["example"], "missing": missing,
            # Folders (absolute, specific) you must read besides your own. Never a whole home folder.
            "sandbox": {"read": []}}


def run(req, out_dir):
    opts = req.get("options") or {}
    text = req.get("request", "")
    image = req.get("image")  # None when the person asked in words only
    progress(0.1, "Starting")
    if image:
        data = base64.b64decode(image["data_base64"])  # the picture they attached
    # ... do the work, writing results into out_dir ...
    name = "result.txt"
    with open(os.path.join(out_dir, name), "w") as f:
        f.write("replace me\n")
    progress(1.0, "Done")
    return {"ok": True, "summary": "My Head did the thing.", "files": [{"path": name}]}


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
        result = run(req, out_dir)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e), "retryable": False}))
        return 1
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
