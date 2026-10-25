#!/usr/bin/env python3
"""Demo words-only Head for Chimera's tests: a coloured card from a description. It needs no input
picture, and it talks to a server on this computer (DEMO_LOCAL_PORT) to show that a Head with
"network": "localhost" can reach local servers inside its sandbox."""
import json, os, socket, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pngkit import write_png

MANIFEST = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin.json")))
COLOURS = {"red": (200, 40, 40), "green": (40, 160, 70), "blue": (40, 80, 200), "grey": (128, 128, 128)}

def progress(f, msg):
    sys.stderr.write(json.dumps({"event": "progress", "fraction": f, "message": msg}) + "\n"); sys.stderr.flush()

def main():
    if sys.argv[1:2] == ["--probe"]:
        print(json.dumps({"have": True, "caps": ["image-gen"], "missing": [], "sandbox": {"read": []}}))
        return 0
    out = sys.argv[1]
    req = json.load(sys.stdin)
    opts = req.get("options") or {}
    had_image = "image" in req
    progress(0.1, "Checking what I can reach")
    local = "unreachable"
    port = os.environ.get("DEMO_LOCAL_PORT")
    if port:
        try:
            with urllib.request.urlopen("http://127.0.0.1:%s/hello" % port, timeout=3) as r:
                local = "reached (%s)" % r.read().decode().strip()
        except Exception as e:
            local = "unreachable (%s)" % type(e).__name__
    try:
        s = socket.create_connection(("1.1.1.1", 80), timeout=2); s.close(); internet = "OPEN"
    except Exception:
        internet = "blocked"
    progress(0.5, "Painting the card")
    colour = opts.get("colour", "grey")
    n = int(opts.get("size_px", 64) or 64)
    rgb = COLOURS.get(colour, COLOURS["grey"])
    rows = [list(rgb + (255,)) * n for _ in range(n)]
    name = "poster_%s.png" % colour
    write_png(os.path.join(out, name), n, n, rows)
    print(json.dumps({"ok": True, "summary": "Demo poster maker: a %s card, %dx%d. Local server: %s. Internet: %s. Input picture: %s."
                      % (colour, n, n, local, internet, "yes" if had_image else "none"), "files": [{"path": name}]}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
