"""A small Ollama HTTP client (stdlib only) that streams the way Chimera's ChatStreamKeep does."""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request


class OllamaError(Exception):
    pass


def normalize_host(h: str) -> str:
    """OLLAMA_HOST style ("0.0.0.0", "127.0.0.1:11434", "http://box:11434") to a base URL."""
    h = (h or "").strip() or "127.0.0.1:11434"
    if "://" not in h:
        h = "http://" + h
    scheme, rest = h.split("://", 1)
    host = rest.strip("/")
    if host.startswith("0.0.0.0"):
        host = "127.0.0.1" + host[len("0.0.0.0"):]
    if ":" not in host.split("]")[-1]:
        host += ":11434"
    return f"{scheme}://{host}"


def _err_text(e: urllib.error.HTTPError) -> str:
    try:
        body = e.read().decode("utf-8", "replace")
        return json.loads(body).get("error") or body
    except Exception:  # noqa: BLE001
        return f"HTTP {e.code}"


class Ollama:
    def __init__(self, host: str, timeout: float = 600.0):
        self.base = normalize_host(host)
        self.timeout = timeout

    def _json(self, method, path, body=None, timeout=30.0):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise OllamaError(_err_text(e)) from None
        except (urllib.error.URLError, OSError) as e:
            raise OllamaError(f"can't reach Ollama at {self.base}: {getattr(e, 'reason', e)}") from None

    def version(self):
        return self._json("GET", "/api/version").get("version", "?")

    def tags(self):
        return self._json("GET", "/api/tags").get("models", [])

    def show(self, model):
        return self._json("POST", "/api/show", {"model": model})

    def embed(self, model, inputs):
        return self._json("POST", "/api/embed", {"model": model, "input": list(inputs)}, timeout=self.timeout)["embeddings"]

    def unload(self, model):
        try:  # what Chimera's Unload sends
            self._json("POST", "/api/generate", {"model": model, "keep_alive": 0, "stream": False}, timeout=60)
        except OllamaError:
            pass

    def chat(self, body: dict, total_timeout: float = 0.0) -> dict:
        """POST /api/chat and read the stream. Never raises: problems land in "error"."""
        limit = total_timeout or self.timeout
        t0 = time.monotonic()
        out = {"content": "", "thinking": "", "stats": {}, "error": None, "format_dropped": False,
               "wall_s": None, "first_token_s": None, "first_content_s": None}
        req = urllib.request.Request(self.base + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            resp = urllib.request.urlopen(req, timeout=min(limit, 120.0))
        except urllib.error.HTTPError as e:
            msg = _err_text(e)
            if "format" in body and "format" in msg.lower():
                # ChatStreamKeep: "Some models don't support structured output; our prompts ask
                # for JSON anyway, so try once more without it."
                b2 = dict(body)
                b2.pop("format")
                r = self.chat(b2, total_timeout)
                r["format_dropped"] = True
                return r
            out.update(error=msg, wall_s=time.monotonic() - t0)
            return out
        except (urllib.error.URLError, OSError) as e:
            out.update(error=f"can't reach Ollama: {getattr(e, 'reason', e)}", wall_s=time.monotonic() - t0)
            return out
        content, thinking = [], []
        try:
            with resp:
                done = False
                for line in resp:
                    if time.monotonic() - t0 > limit:
                        out["error"] = f"timed out after {limit:.0f} s"
                        break
                    line = line.strip()
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        out["error"] = chunk["error"]
                        break
                    msg = chunk.get("message") or {}
                    c, th = msg.get("content") or "", msg.get("thinking") or ""
                    now = time.monotonic() - t0
                    if (c or th) and out["first_token_s"] is None:
                        out["first_token_s"] = now
                    if c and out["first_content_s"] is None:
                        out["first_content_s"] = now
                    content.append(c)
                    thinking.append(th)
                    if chunk.get("done"):
                        done = True
                        out["stats"] = {k: chunk.get(k) for k in ("prompt_eval_count", "eval_count", "total_duration",
                                                                   "load_duration", "prompt_eval_duration",
                                                                   "eval_duration", "done_reason")}
                        break
                if not done and out["error"] is None:
                    out["error"] = "Ollama ended the reply early"
        except socket.timeout:
            out["error"] = f"timed out after {limit:.0f} s"
        except (OSError, ValueError) as e:
            out["error"] = f"{type(e).__name__}: {e}"
        out["content"], out["thinking"] = "".join(content), "".join(thinking)
        out["wall_s"] = time.monotonic() - t0
        return out
