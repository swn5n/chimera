#!/usr/bin/env python3
"""A Head made with Chimera's Head maker (Settings → Heads → Make a Head).

Every made Head has this same file. It reads what to do from the "maker" block
of the plugin.json next to it and does one of two things:
  program  runs a command line on this computer, with {{placeholders}} filled
           in from the request: {{input}} (the picture's file), {{prompt}} (the
           words), {{out}} (the folder to save results in), {{name}}, {{cache}},
           {{blender}}, {{seed}} and the Head's own settings, e.g. {{strength}}
  server   calls a server on this computer over HTTP, with the same
           placeholders in its address and JSON, plus {{input_base64}} and
           {{input_data_url}} for the picture, and saves the file it returns
Change a made Head in Chimera rather than here: saving it there writes
Chimera's current copy of this file again. The contract with Chimera (stdin
JSON, output folder, progress on stderr, a JSON line on stdout, --probe) is in
heads/README.md. Standard library only.
"""
import base64, json, os, random, re, shlex, shutil, subprocess, sys, tempfile, threading, time
import urllib.error, urllib.parse, urllib.request
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
PERCENT = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s?%")
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
TEXT_KEYS = ("text", "response", "result", "output", "content", "message", "answer", "caption", "transcript", "transcription")
CTYPE_EXT = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif",
    "model/gltf-binary": ".glb", "model/gltf+json": ".gltf", "model/obj": ".obj", "model/stl": ".stl",
    "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
    "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav", "audio/mpeg": ".mp3", "audio/ogg": ".ogg",
    "audio/flac": ".flac", "application/pdf": ".pdf", "application/zip": ".zip", "application/json": ".json",
    "text/plain": ".txt", "text/markdown": ".md",
}


class Fail(Exception):
    """A run that can't finish: the message is shown to the person who asked."""

    def __init__(self, message, code=1, retryable=False):
        Exception.__init__(self, message)
        self.code, self.retryable = code, retryable


_progress_lock = threading.Lock()


def progress(fraction, message):
    line = json.dumps({"event": "progress", "fraction": max(0.0, min(1.0, fraction)), "message": message}) + "\n"
    with _progress_lock:  # the heartbeat thread writes too
        sys.stderr.write(line)
        sys.stderr.flush()


class Beat:
    """Sends a progress line every few seconds while the work runs, so the asker
    sees it's alive: the program's own percentage when it prints one, otherwise
    a guess from how long a run usually takes."""

    def __init__(self, what, typical):
        self.what, self.typical, self.t0 = what, max(5.0, float(typical or 60)), time.time()
        self.fraction, self.line = None, ""
        self.done = threading.Event()
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while not self.done.wait(5):
            el = time.time() - self.t0
            f = self.fraction if self.fraction is not None else min(0.9, 0.9 * el / self.typical)
            msg = "%s… %ds" % (self.what, el)
            if self.line:
                msg += " · " + self.line[:100]
            progress(0.05 + 0.9 * f, msg)

    def stop(self):
        self.done.set()


def load():
    with open(os.path.join(HERE, "plugin.json"), encoding="utf-8") as f:
        m = json.load(f)
    return m, m.get("maker") or {}


# ---------- placeholders ----------

def text_of(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if v is None:
        return ""
    return str(v)


def setting_values(cfg, req):
    """The Head's settings: defaults first, then what Chimera read from the request."""
    known = {}
    for o in cfg.get("options") or []:
        known[o.get("name")] = o
    vals = {}
    for name, o in known.items():
        d = o.get("default")
        if d is None:
            d = False if o.get("type") == "boolean" else ""
        vals[name] = d
    for k, v in (req.get("options") or {}).items():
        o = known.get(k)
        if o is None:
            continue
        t = o.get("type")
        if t == "boolean" and not isinstance(v, bool):
            continue
        if t in ("number", "integer") and (isinstance(v, bool) or not isinstance(v, (int, float))):
            continue
        if t in ("choice", "text") and not isinstance(v, str):
            continue
        vals[k] = int(round(v)) if t == "integer" else v
    return vals, known


def fill_text(s, vals):
    return PLACEHOLDER.sub(lambda mm: text_of(vals.get(mm.group(1), "")), s)


def fill_json(obj, vals):
    """Fills placeholders in a JSON template. A string that is only a placeholder
    becomes the value itself, so "{{steps}}" turns into the number 30."""
    if isinstance(obj, str):
        m = PLACEHOLDER.fullmatch(obj.strip())
        if m and m.group(1) in vals:
            return vals[m.group(1)]
        return fill_text(obj, vals)
    if isinstance(obj, list):
        return [fill_json(x, vals) for x in obj]
    if isinstance(obj, dict):
        return {k: fill_json(v, vals) for k, v in obj.items()}
    return obj


def split_command(cmd):
    lex = shlex.shlex(cmd, posix=True)
    lex.whitespace_split = True
    lex.commenters = ""
    if os.name == "nt":
        lex.escape = ""  # backslashes are path separators there
    return list(lex)


# ---------- finding things on this computer ----------

def search_path():
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    extra = ["/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin", os.path.expanduser("~/.local/bin")]
    if os.name == "nt":
        extra = []
    return os.pathsep.join(parts + [p for p in extra if p not in parts])


def find_blender():
    p = os.environ.get("CHIMERA_BLENDER")
    if p and os.path.isfile(p):
        return p
    for c in ["/Applications/Blender.app/Contents/MacOS/Blender", "/usr/bin/blender", "/snap/bin/blender"]:
        if os.path.isfile(c):
            return c
    return shutil.which("blender", path=search_path()) or ""


def find_program(name):
    """The program's full path, or None. A Mac app bundle means the program inside it."""
    if not name:
        return None
    name = os.path.expanduser(name)
    if name.endswith(".app") and os.path.isdir(name):
        inner = os.path.join(name, "Contents", "MacOS")
        want = os.path.join(inner, os.path.basename(name)[:-4])
        if os.path.isfile(want):
            return want
        found = [os.path.join(inner, f) for f in sorted(os.listdir(inner))] if os.path.isdir(inner) else []
        found = [f for f in found if os.path.isfile(f)]
        return found[0] if len(found) == 1 else None
    if os.path.isabs(name) or os.sep in name or (os.altsep and os.altsep in name):
        return name if os.path.isfile(name) and (os.name == "nt" or os.access(name, os.X_OK)) else None
    return shutil.which(name, path=search_path())


def blender_config():
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Blender")
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA", ""), "Blender Foundation", "Blender")
    return os.path.expanduser("~/.config/blender")


def program_home(path):
    """The folder a program's own files live in: its .app bundle, the folder above
    bin/ (a Python venv, a Homebrew prefix), or the folder it sits in."""
    real = os.path.realpath(path)
    i = real.find(".app/")
    if i >= 0:
        return real[:i + 4]
    d = os.path.dirname(real)
    up = os.path.dirname(d)
    return up if os.path.basename(d).lower() in ("bin", "scripts") and up != os.path.dirname(up) else d  # /bin/cp: /bin, not /


def path_in(token):
    """An absolute path written in a command argument (also after --flag=)."""
    t = token.split("=", 1)[1] if token.startswith("-") and "=" in token else token
    if PLACEHOLDER.search(t):
        return None
    t = os.path.expanduser(t)
    if os.path.isabs(t):
        return t
    return None


SCRIPT_EXT = (".py", ".sh", ".blend", ".js", ".rb", ".pl", ".lua", ".json", ".ckpt", ".safetensors", ".pt", ".pth", ".onnx")


def probe_program(cfg):
    missing, reads = [], []
    for key in ("command", "command_no_input"):
        cmd = (cfg.get(key) or "").strip()
        if not cmd:
            continue
        try:
            toks = split_command(cmd)
        except ValueError as e:
            missing.append("The command can't be read (%s). Check its quotes." % e)
            continue
        first = toks[0].strip()
        ph = PLACEHOLDER.fullmatch(first)
        if ph and ph.group(1) != "blender":
            missing.append("The command must start with the program to run, not {{%s}}." % ph.group(1))
            continue
        prog = find_blender() if ph else find_program(first)
        if not prog:
            if ph:
                missing.append("Blender isn't installed on this computer.")
            else:
                missing.append("Can't find the program %s on this computer. Install it, or write its full path in the command (for example /opt/homebrew/bin/%s)." % (first, os.path.basename(first)))
            continue
        reads += [program_home(prog), prog]
        if "blender" in os.path.basename(prog).lower():
            reads.append(blender_config())
        for t in toks[1:]:
            p = path_in(t)
            if not p:
                continue
            if os.path.isdir(p):
                reads.append(p)
            elif os.path.isfile(p):
                reads += [os.path.dirname(p), p]
            elif p.lower().endswith(SCRIPT_EXT):
                missing.append("Can't find %s on this computer." % p)
    return missing, reads


def extra_reads(cfg):
    """The folders the Head's owner listed under "Folders it reads"."""
    missing, reads = [], []
    for r in cfg.get("reads") or []:
        r = os.path.expanduser(r)
        if os.path.exists(r):
            reads.append(r)
        else:
            missing.append("The folder %s it reads isn't on this computer." % r)
    return missing, reads


def local_url(u):
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    return p.scheme in ("http", "https") and (host in LOCAL_HOSTS or host.startswith("127."))


def opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never a system proxy for this computer's servers


def base_of(u):
    p = urllib.parse.urlsplit(u)
    return "%s://%s/" % (p.scheme, p.netloc)


def probe_server(cfg):
    url = (cfg.get("url") or "").strip()
    check = (cfg.get("health_url") or "").strip() or (base_of(url) if url else "")
    if not url or not local_url(url) or not local_url(check):
        return ["The server's address must be on this computer (http://127.0.0.1:…)."], []
    try:
        with opener().open(urllib.request.Request(check, method="GET"), timeout=4) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        reason = getattr(e, "reason", e)
        return ["Nothing answers at %s (%s). Start the server first." % (check, reason)], []
    if code >= 500 and cfg.get("health_url"):
        return ["The server at %s isn't ready (HTTP %d)." % (check, code)], []
    return [], []


def probe(m, cfg):
    kind = cfg.get("kind")
    caps = list(cfg.get("output") or [])
    if kind == "program":
        missing, reads = probe_program(cfg)
    elif kind == "server":
        missing, reads = probe_server(cfg)
    else:
        missing, reads = ["plugin.json has no maker settings this file understands; open the Head in Chimera's Head maker again."], []
    more_missing, more_reads = extra_reads(cfg)
    missing, reads = missing + more_missing, reads + more_reads
    seen, keep = set(), []
    for r in reads:
        if r and r not in seen:
            seen.add(r)
            keep.append(r)
    return {"have": not missing, "caps": caps, "missing": missing, "sandbox": {"read": keep}}


# ---------- results ----------

def sniff_ext(data, ctype=""):
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return ".wav"
    if data[4:8] == b"ftyp":
        return ".mov" if data[8:10] == b"qt" else ".mp4"
    for sig, ext in ((b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"), (b"GIF8", ".gif"), (b"glTF", ".glb"),
                     (b"%PDF", ".pdf"), (b"OggS", ".ogg"), (b"fLaC", ".flac"), (b"ID3", ".mp3"), (b"\xff\xfb", ".mp3"),
                     (b"PK\x03\x04", ".zip"), (b"BLENDER", ".blend"), (b"ply\n", ".ply"), (b"\x1a\x45\xdf\xa3", ".webm")):
        if data.startswith(sig):
            return ext
    ct = (ctype or "").split(";")[0].strip().lower()
    if ct in CTYPE_EXT:
        return CTYPE_EXT[ct]
    head = data[:4096]
    try:
        txt = head.decode("utf-8")
    except UnicodeDecodeError:
        return ".bin"
    if re.search(r"(?m)^v -?\d", txt) and re.search(r"(?m)^(f|vn|vt|o|g|mtllib) ", txt):
        return ".obj"
    if txt.lstrip().startswith("solid "):
        return ".stl"
    return ".txt"


def b64_bytes(s):
    """The bytes in a base64 string or data: URL, or None when it isn't one."""
    s = s.strip()
    if s.startswith("data:") and ";base64," in s[:200]:
        s = s.split(",", 1)[1]
    if len(s) < 16 or len(s) % 4 == 1:
        return None
    try:
        return base64.b64decode(s + "=" * (-len(s) % 4), validate=True)
    except Exception:
        try:
            return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        except Exception:
            return None


def dig(obj, path):
    for part in path.replace("[", ".").replace("]", "").split("."):
        if part == "":
            continue
        if isinstance(obj, list) and part.lstrip("-").isdigit():
            i = int(part)
            if -len(obj) <= i < len(obj):
                obj = obj[i]
                continue
            return None
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
            continue
        return None
    return obj


def blobs_in(obj, out):
    """Long base64 strings (or data: URLs) anywhere in a JSON answer: the files in it."""
    if isinstance(obj, str):
        if len(obj) >= 256:
            b = b64_bytes(obj)
            if b and (sniff_ext(b) not in (".bin", ".txt") or len(b) > 2048):
                out.append(b)
    elif isinstance(obj, list):
        for x in obj:
            blobs_in(x, out)
    elif isinstance(obj, dict):
        for x in obj.values():
            blobs_in(x, out)
    return out


def short(j, n=300):
    s = j if isinstance(j, str) else json.dumps(j)
    return s if len(s) <= n else s[:n] + "…"


def http(url, method="GET", data=None, headers=None, timeout=60):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with opener().open(req, timeout=timeout) as r:
            return r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        body = e.read()[:2000].decode("utf-8", "replace").strip()
        raise Fail("The server said HTTP %d%s" % (e.code, (": " + body) if body else "."), 1, e.code >= 500)
    except urllib.error.URLError as e:
        raise Fail("Couldn't reach the server at %s (%s). Is it running?" % (base_of(url), e.reason), 3, True)


def results_from(value, base, timeout):
    """Turns the value found in a JSON answer into (files, text)."""
    if isinstance(value, list):
        files, texts = [], []
        for x in value:
            f, t = results_from(x, base, timeout)
            files += f
            if t:
                texts.append(t)
        return files, "\n\n".join(texts)
    if isinstance(value, dict):
        return [(b, "") for b in blobs_in(value, [])], ""
    if not isinstance(value, str):
        return [], text_of(value)
    v = value.strip()
    if len(v) < 2000 and os.path.isabs(v) and os.path.isfile(v):  # a server that answers with where it saved the file
        try:
            with open(v, "rb") as f:
                return [(f.read(), "")], ""
        except OSError:
            raise Fail("The server saved its result at %s, which this Head can't read. Add that folder under Folders it reads." % v)
    if v.startswith("http://") or v.startswith("https://") or (v.startswith("/") and len(v) < 2000):
        u = urllib.parse.urljoin(base, v)
        if local_url(u):
            data, ctype = http(u, timeout=timeout)
            return [(data, ctype)], ""
    b = b64_bytes(v) if len(v) >= 64 else None
    if b and sniff_ext(b) != ".txt":
        return [(b, "")], ""
    return [], value


def take_answer(cfg, body, ctype, url, timeout):
    """The files (and text) in a server's answer."""
    ct = (ctype or "").split(";")[0].strip().lower()
    field = (cfg.get("result_field") or "").strip()
    # By its label, or by its look: plenty of servers send JSON labelled text/plain or text/html.
    is_json = ct == "application/json" or ct.endswith("+json") or body.lstrip()[:1] in (b"{", b"[")
    if is_json:
        try:
            j = json.loads(body.decode("utf-8"))
        except Exception:
            j = None
        if j is not None:
            if field:
                val = dig(j, field)
                if val is None:
                    raise Fail("The server's answer has no %r in it. It answered: %s" % (field, short(j)))
                return results_from(val, url, timeout)
            blobs = blobs_in(j, [])
            if blobs:
                return [(b, "") for b in blobs], ""
            if isinstance(j, str):
                return results_from(j, url, timeout)
            if isinstance(j, dict):
                for k in TEXT_KEYS:
                    if isinstance(j.get(k), str):
                        return [], j[k]
            return [], json.dumps(j, indent=2)
    if ct.startswith("text/") and ct != "text/html":
        return [], body.decode("utf-8", "replace")
    return [(body, ctype)], ""


def multipart(fields, file_field, filename, data, mime):
    boundary = "----chimera%016x" % random.getrandbits(64)
    q = lambda s: str(s).replace('"', "%22").replace("\r", "").replace("\n", "")
    parts = []
    for k, v in (fields.items() if isinstance(fields, dict) else []):
        val = json.dumps(v) if isinstance(v, (dict, list)) else text_of(v)
        parts += [b"--" + boundary.encode(), ('Content-Disposition: form-data; name="%s"' % q(k)).encode(), b"", val.encode()]
    parts += [b"--" + boundary.encode(), ('Content-Disposition: form-data; name="%s"; filename="%s"' % (q(file_field), q(filename))).encode(),
              ("Content-Type: " + mime).encode(), b"", data]
    parts += [b"--" + boundary.encode() + b"--", b""]
    return b"\r\n".join(parts), "multipart/form-data; boundary=" + boundary


# ---------- running ----------

def safe_name(name, fallback):
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(name or "")).strip("._")
    return base[:80] or fallback


def picture(req):
    """(file name, bytes, MIME type) of the attached picture, or None."""
    img = req.get("image")
    if not img or not img.get("data_base64"):
        return None
    try:
        data = base64.b64decode(img["data_base64"])
    except Exception:
        raise Fail("The picture didn't arrive in one piece.", 2)
    name = safe_name(img.get("name"), "picture")
    ext = os.path.splitext(name)[1].lower()
    if not ext:
        ext = sniff_ext(data)
        name += ext
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
            ".heic": "image/heic", ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff"}.get(ext, "application/octet-stream")
    return name, data, mime


def common_values(m, cfg, req, pic):
    vals, known = setting_values(cfg, req)
    base = {"prompt": req.get("request") or "", "name": os.path.splitext(pic[0])[0] if pic else m.get("id", "result")}
    if "seed" not in known:
        base["seed"] = random.randint(0, 2**31 - 1)
    base.update(vals)
    return base, known


def save(out_dir, stem, items):
    """Writes (bytes, content type) pairs into the output folder; returns their names."""
    names = []
    for i, (data, ctype) in enumerate(items):
        name = "%s%s%s" % (stem, "_%d" % (i + 1) if len(items) > 1 else "", sniff_ext(data, ctype))
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(data)
        names.append(name)
    return names


def run_server(m, cfg, req, out_dir):
    pic = picture(req)
    if cfg.get("input") == "picture" and not pic:
        raise Fail("Attach a picture for %s to work on." % m.get("name", "this Head"), 2)
    vals, _ = common_values(m, cfg, req, pic)
    if pic:
        b64 = base64.b64encode(pic[1]).decode()
        vals["input_base64"], vals["input_data_url"] = b64, "data:%s;base64,%s" % (pic[2], b64)
    else:
        vals["input_base64"] = vals["input_data_url"] = ""
    url = PLACEHOLDER.sub(lambda mm: urllib.parse.quote(text_of(vals.get(mm.group(1), "")), safe=""), cfg.get("url") or "")
    if not local_url(url):
        raise Fail("The server's address must be on this computer (http://127.0.0.1:…).", 2)
    method = (cfg.get("method") or "POST").upper()
    timeout = max(30, int(m.get("timeout_s") or 1800))
    data, headers = None, {"Accept": "*/*"}
    if method != "GET":
        filled = fill_json(cfg.get("body"), vals) if cfg.get("body") is not None else {}
        if cfg.get("upload_field") and pic:
            data, headers["Content-Type"] = multipart(filled, cfg["upload_field"], pic[0], pic[1], pic[2])
        else:
            data, headers["Content-Type"] = json.dumps(filled).encode(), "application/json"
    progress(0.05, "Sending the request to %s" % base_of(url))
    beat = Beat("Waiting for the server", cfg.get("typical_s"))
    t0 = time.time()
    try:
        body, ctype = http(url, method, data, headers, timeout)
        files, text = take_answer(cfg, body, ctype, url, timeout)
    finally:
        beat.stop()
    return finish(m, cfg, out_dir, files, text, vals["name"], time.time() - t0)


def run_program(m, cfg, req, out_dir):
    pic = picture(req)
    mode = cfg.get("input")
    if mode == "picture" and not pic:
        raise Fail("Attach a picture for %s to work on." % m.get("name", "this Head"), 2)
    cmd = cfg.get("command") or ""
    if not pic and mode == "either" and cfg.get("command_no_input"):
        cmd = cfg["command_no_input"]
    vals, known = common_values(m, cfg, req, pic)
    run_dir = os.path.dirname(os.path.abspath(out_dir))
    try:
        work = tempfile.mkdtemp(prefix="work-", dir=run_dir)
    except OSError:
        work = tempfile.mkdtemp(prefix="chimera-head-")
    vals["out"] = os.path.abspath(out_dir)
    vals["cache"] = os.environ.get("CHIMERA_CACHE") or work
    vals["blender"] = find_blender()
    vals["input"] = ""
    if pic:
        vals["input"] = os.path.join(work, pic[0])
        with open(vals["input"], "wb") as f:
            f.write(pic[1])
    flags = {}  # a yes/no setting written alone in the command adds its own text
    for name, o in known.items():
        if o.get("type") == "boolean":
            flags[name] = (o.get("yes") if o.get("yes") is not None else "true", o.get("no") if o.get("no") is not None else "false")
    try:
        toks = split_command(cmd)
    except ValueError as e:
        raise Fail("The command can't be read (%s). Check its quotes." % e, 2)
    argv = []
    for t in toks:
        if t.startswith("~"):
            t = os.path.expanduser(t)
        whole = PLACEHOLDER.fullmatch(t.strip())
        if whole and whole.group(1) in flags:
            argv += split_command(flags[whole.group(1)][0 if vals.get(whole.group(1)) else 1] or "")
        else:
            argv.append(fill_text(t, vals))
    if not argv:
        raise Fail("This Head has no command to run.", 2)
    if PLACEHOLDER.fullmatch(toks[0].strip()) and not vals["blender"]:
        raise Fail("Blender isn't installed on this computer.", 3, True)
    prog = find_program(argv[0])
    if not prog:
        raise Fail("Can't find the program %s on this computer." % argv[0], 3, True)
    argv[0] = prog
    env = dict(os.environ)
    env["PATH"] = search_path()
    env["PYTHONUNBUFFERED"] = "1"
    what = "Running " + os.path.splitext(os.path.basename(prog))[0]
    progress(0.03, what)
    beat = Beat(what, cfg.get("typical_s"))
    t0 = time.time()
    try:
        proc = subprocess.Popen(argv, cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=0x08000000 if os.name == "nt" else 0)  # no console window on Windows
    except OSError as e:
        beat.stop()
        raise Fail("Couldn't start %s: %s" % (prog, e), 3, True)
    tail, out_bytes = deque(maxlen=40), []

    def note(raw):
        piece = raw.decode("utf-8", "replace").strip()
        if not piece:
            return
        tail.append(piece)
        beat.line = piece
        pm = PERCENT.findall(piece)
        if pm and float(pm[-1]) <= 100:
            beat.fraction = float(pm[-1]) / 100

    def read(stream, keep):
        # In chunks, not lines: progress bars redraw one line with \r and no newline.
        buf, size = b"", 0
        while True:
            chunk = stream.read1(4096)
            if not chunk:
                break
            if keep and size < (2 << 20):
                out_bytes.append(chunk)
                size += len(chunk)
            pieces = re.split(rb"[\r\n]", buf + chunk)
            buf = pieces.pop()
            for p in pieces:
                note(p)
            if len(buf) > 8192:
                note(buf)
                buf = b""
        note(buf)
        stream.close()

    readers = [threading.Thread(target=read, args=(proc.stdout, True), daemon=True),
               threading.Thread(target=read, args=(proc.stderr, False), daemon=True)]
    for r in readers:
        r.start()
    code = proc.wait()
    for r in readers:
        r.join(10)
    beat.stop()
    if code != 0:
        said = "\n".join(list(tail)[-12:])
        raise Fail("%s stopped with exit code %d.%s" % (os.path.basename(prog), code, ("\n" + said) if said else ""), 1)
    # Results go in {{out}}. A program that saved next to its input or in the folder
    # it ran in still counts: what it made there moves into the output folder.
    if not list_files(out_dir):
        for root, _, names in os.walk(work):
            for n in names:
                p = os.path.join(root, n)
                if p != vals["input"] and not n.startswith("."):
                    shutil.move(p, os.path.join(out_dir, n))
    text = b"".join(out_bytes).decode("utf-8", "replace").strip()
    return finish(m, cfg, out_dir, [], text, vals["name"], time.time() - t0)


def list_files(out_dir):
    found = []
    for root, dirs, names in os.walk(out_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for n in sorted(names):
            if not n.startswith("."):
                found.append(os.path.relpath(os.path.join(root, n), out_dir))
    return found


def finish(m, cfg, out_dir, items, text, stem, seconds):
    """Saves what came back and writes the summary the asker sees."""
    hid = m.get("id", "result")
    save(out_dir, safe_name(stem if stem == hid else stem + "_" + hid, "result"), items)
    names = list_files(out_dir)
    wants_text = "text" in (cfg.get("output") or [])
    if not names and text.strip():
        if not wants_text:
            hint = " Set Where the result is to the field that holds the file." if cfg.get("kind") == "server" else ""
            raise Fail("%s finished but saved no file.%s It said: %s" % (m.get("name", "The Head"), hint, short(text.strip())), 1)
        names = ["%s.txt" % safe_name(stem, "result")]
        with open(os.path.join(out_dir, names[0]), "w", encoding="utf-8") as f:
            f.write(text.strip() + "\n")
    if not names:
        hint = " Put {{out}} in the command where the program should save its result." if cfg.get("kind") == "program" else ""
        raise Fail("%s finished but made nothing.%s" % (m.get("name", "The Head"), hint), 1)
    if len(names) > 20:
        names = names[:20]
    progress(1.0, "Done")
    if wants_text:
        for n in names:
            if n.lower().endswith((".txt", ".md")):
                with open(os.path.join(out_dir, n), encoding="utf-8", errors="replace") as f:
                    said = f.read(4000).strip()
                if said:
                    return {"ok": True, "summary": said, "files": [{"path": n} for n in names]}
    size = sum(os.path.getsize(os.path.join(out_dir, n)) for n in names)
    what = names[0] if len(names) == 1 else "%d files" % len(names)
    return {"ok": True, "summary": "%s made %s (%s) in %ds." % (m.get("name", "The Head"), what, human(size), int(seconds)),
            "files": [{"path": n} for n in names]}


def human(n):
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "bytes" else ("%.1f %s" % (n, unit))
        n /= 1000.0


def main():
    try:
        m, cfg = load()
    except Exception as e:
        if sys.argv[1:2] == ["--probe"]:
            print(json.dumps({"have": False, "caps": [], "missing": ["plugin.json can't be read: %s" % e], "sandbox": {"read": []}}))
            return 3
        print(json.dumps({"ok": False, "error": "plugin.json can't be read: %s" % e}))
        return 3
    if sys.argv[1:2] == ["--probe"]:
        print(json.dumps(probe(m, cfg)))
        return 0
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CHIMERA_OUT", ".")
    os.makedirs(out_dir, exist_ok=True)
    try:
        req = json.load(sys.stdin)
    except Exception as e:
        print(json.dumps({"ok": False, "error": "bad input: %s" % e}))
        return 2
    try:
        if cfg.get("kind") == "server":
            result = run_server(m, cfg, req, out_dir)
        elif cfg.get("kind") == "program":
            result = run_program(m, cfg, req, out_dir)
        else:
            raise Fail("plugin.json has no maker settings this file understands.", 3)
    except Fail as e:
        print(json.dumps({"ok": False, "error": str(e), "retryable": e.retryable}))
        return e.code
    except Exception as e:
        print(json.dumps({"ok": False, "error": "%s: %s" % (type(e).__name__, e), "retryable": False}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
