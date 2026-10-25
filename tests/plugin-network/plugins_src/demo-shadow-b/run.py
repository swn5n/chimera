#!/usr/bin/env python3
"""Demo plugin for Chimera's integration test: a soft elliptical shadow under a cut-out.
It also reports what its sandbox let it do (read the home folder, reach the network)."""
import base64, json, os, socket, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pngkit import read_png, write_png

MANIFEST = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin.json")))

def progress(f, msg):
    sys.stderr.write(json.dumps({"event": "progress", "fraction": f, "message": msg}) + "\n"); sys.stderr.flush()

def main():
    if sys.argv[1:2] == ["--probe"]:
        # DEMO_READ (testing): folders to ask the sandbox for, separated like PATH, such as the folder
        # above Chimera's data folder and the data folder itself
        extra = [d for d in os.environ.get("DEMO_READ", "").split(os.pathsep) if d]
        print(json.dumps({"have": True, "caps": [MANIFEST["id"]], "missing": [], "sandbox": {"read": extra}}))
        return 0
    out = sys.argv[1]
    req = json.load(sys.stdin)
    opts = req.get("options") or {}
    progress(0.05, "Checking the sandbox")
    secret = os.environ.get("IT_SECRET_FILE", "")
    try:
        open(secret).read(); secret_state = "READABLE"
    except Exception:
        secret_state = "hidden"
    try:
        s = socket.create_connection(("1.1.1.1", 80), timeout=2); s.close(); net = "OPEN"
    except Exception:
        net = "blocked"
    try:
        # Chimera's own config (with its network token): <data>/plugin-runs/<id>-…/out -> <data>/config.json
        with open(os.path.join(os.path.dirname(out), "..", "..", "config.json")) as f:
            f.read(); data_dir = "READABLE"
    except Exception:
        data_dir = "hidden"
    delay = int(opts.get("delay_s", 0) or 0)
    for i in range(delay):
        progress(0.1 + 0.6 * i / max(1, delay), "Taking it slowly (%d of %d s)" % (i + 1, delay)); time.sleep(1)
    progress(0.75, "Drawing the shadow")
    w, h, rows = read_png(base64.b64decode(req["image"]["data_base64"]))
    xs = [x for y in range(h) for x in range(w) if rows[y][4 * x + 3] > 0]
    ys = [y for y in range(h) for x in range(w) if rows[y][4 * x + 3] > 0]
    x0, x1, y1 = min(xs), max(xs), max(ys)
    style, dark = opts.get("style", "soft"), float(opts.get("darkness", 0.6))
    cx = (x0 + x1) / 2 + {"left": 0.15, "right": -0.15}.get(style, 0) * (x1 - x0)
    cy, rx, ry = y1 - 2, 0.6 * (x1 - x0), max(4.0, 0.07 * h)
    outrows = []
    for y in range(h):
        r = []
        for x in range(w):
            d = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
            shade = 1 - dark * max(0.0, 1 - d) ** 1.5
            bg = [255 * shade] * 3
            pr, pg, pb, pa = rows[y][4 * x:4 * x + 4]
            a = pa / 255
            r += [int(pr * a + bg[0] * (1 - a)), int(pg * a + bg[1] * (1 - a)), int(pb * a + bg[2] * (1 - a)), 255]
        outrows.append(r)
    stem = os.path.splitext(os.path.basename(req["image"].get("name") or "image.png"))[0]
    name = stem + "_" + MANIFEST["id"] + ".png"
    write_png(os.path.join(out, name), w, h, outrows)
    progress(1.0, "Done")
    print(json.dumps({"ok": True, "files": [{"path": name}],
        "summary": "%s (%s light, darkness %.2f). Sandbox: home folder %s, data folder %s, network %s." % (
            MANIFEST["name"], style, dark, secret_state, data_dir, net)}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
