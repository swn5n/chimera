"""A small headless-Chrome driver over the DevTools protocol, standard library only (a minimal WebSocket client)."""
import base64, json, os, shutil, signal, socket, struct, subprocess, time, urllib.parse, urllib.request

CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


class WS:
    def __init__(self, url, timeout=120):
        u = urllib.parse.urlparse(url)
        self.s = socket.create_connection((u.hostname, u.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (u.path, u.hostname, u.port, key)).encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.s.recv(4096)
            if not chunk:
                raise EOFError("no handshake")
            buf += chunk
        head, self.buf = buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise RuntimeError("websocket handshake refused: " + head.decode(errors="replace")[:200])

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(1 << 20)
            if not chunk:
                raise EOFError("closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text):
        payload = text.encode()
        n = len(payload)
        hdr = bytearray([0x81])
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            hdr += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        hdr += mask
        self.s.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def recv(self):
        data = b""
        while True:
            b1, b2 = self._read(2)
            fin, op, n = b1 & 0x80, b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            if op == 8:
                raise EOFError("closed")
            if op in (9, 10):
                continue
            data += payload
            if fin:
                return data.decode()


class Chrome:
    def __init__(self, workdir, port=19222, size=(1340, 860), scale=1.2):
        self.size, self.scale, self.id = size, scale, 0
        self.profile = os.path.join(workdir, "chrome-profile")
        shutil.rmtree(self.profile, ignore_errors=True)
        self.proc = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=%d" % port, "--user-data-dir=" + self.profile,
                                      "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "--mute-audio",
                                      "--disable-features=Translate", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        url = None
        for _ in range(60):
            try:
                pages = json.load(urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=2))
                url = next(p["webSocketDebuggerUrl"] for p in pages if p["type"] == "page")
                break
            except Exception:
                time.sleep(0.5)
        if not url:
            self.close()
            raise RuntimeError("Chrome did not come up")
        self.ws = WS(url)
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.resize(*size, scale)

    def call(self, method, params=None):
        self.id += 1
        self.ws.send(json.dumps({"id": self.id, "method": method, "params": params or {}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.id:
                if "error" in m:
                    raise RuntimeError("%s: %s" % (method, m["error"]))
                return m.get("result", {})

    def resize(self, w, h, scale=None):
        self.size = (w, h)
        self.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": scale or self.scale, "mobile": False})

    def eval(self, expr, wait=False):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": wait})
        if "exceptionDetails" in r:
            raise RuntimeError("JS error: %s" % json.dumps(r["exceptionDetails"])[:400])
        return r["result"].get("value")

    def goto(self, url, ready="document.readyState === 'complete'", timeout=30):
        self.call("Page.navigate", {"url": url})
        self.until(ready, timeout)

    def until(self, expr, timeout=30, what=""):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if self.eval(expr):
                    return True
            except RuntimeError:
                pass
            time.sleep(0.25)
        raise RuntimeError("timed out waiting for: " + (what or expr))

    def shot(self, path, clip=None):
        p = {"format": "png"}
        if clip:  # x, y, w, h in CSS pixels
            p["clip"] = {"x": clip[0], "y": clip[1], "width": clip[2], "height": clip[3], "scale": 1}
        data = self.call("Page.captureScreenshot", p)["data"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        return path

    def close(self):
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
