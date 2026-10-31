"""Shared plumbing for the runners: paths, Chimera's request shape, the Ollama client, run folders.

The Ollama client and the planner/reviewer request builders are helper-model's (runner/ollama_client.py,
helper/chimera_port.py), loaded by path: both folders have runner/ and tools/ packages, so helper-model is
never put on sys.path here. Everything a worker step sends is built the way Chimera 0.7.0 builds it:

    runStep (app/hydra.go)   NeedCtx = historyTokens(msgs) + room (4096), no format
    runPrompt / hub          options.num_ctx = ctxBucket(NeedCtx, the model's CtxMax) (app/hub.go)
    ChatStream (ollama.go)   stream true, keep_alive "15m", only role and content per message

No seed, temperature or think field: Chimera sends none, so the model's own defaults apply.
"""
from __future__ import annotations

import datetime
import importlib
import importlib.util
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # worker-model/
if HERE not in sys.path:
    sys.path.insert(0, HERE)
REPO = os.path.dirname(HERE)
HELPER = os.path.join(REPO, "helper-model")
RESULTS = os.path.join(HERE, "results")
STEP_RUNS = os.path.join(RESULTS, "runs")  # step_eval: results/runs/<time>-<model>-<prompt>/
TASK_RUNS = os.path.join(RESULTS, "runs-tasks")  # task_eval: one folder per arm (raw.jsonl gitignored too)

STEP_ROOM = 4096  # runStep's room (app/hydra.go)
SYNTH_ROOM = 4096  # synthRoom (app/hydra_check.go): the combine's room in round 1
KEEP_ALIVE = "15m"  # ChatStream's keep_alive (app/ollama.go)
CHIMERA_VERSION = "0.7.0"  # the app/ these requests were ported from (CLAUDE.md)

_loaded = {}


class _no_bytecode:
    """Don't write __pycache__ into helper-model/ while loading its modules (this folder only reads it)."""

    def __enter__(self):
        self.was, sys.dont_write_bytecode = sys.dont_write_bytecode, True

    def __exit__(self, *exc):
        sys.dont_write_bytecode = self.was


def load_by_path(name, path):
    """A module loaded from a file without touching sys.path (cached under name)."""
    if name in _loaded:
        return _loaded[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    with _no_bytecode():
        spec.loader.exec_module(mod)
    _loaded[name] = mod
    return mod


def helper_port():
    """helper-model's helper/chimera_port.py (Chimera's planner and reviewer requests, extractJSON, cleanPlan).

    The helper package is registered under its own name from its folder, so its relative imports work and
    nothing in worker-model is shadowed."""
    if "helper" not in sys.modules:
        pkg = os.path.join(HELPER, "helper")
        spec = importlib.util.spec_from_file_location("helper", os.path.join(pkg, "__init__.py"),
                                                      submodule_search_locations=[pkg])
        mod = importlib.util.module_from_spec(spec)
        sys.modules["helper"] = mod
        with _no_bytecode():
            spec.loader.exec_module(mod)
    with _no_bytecode():
        return importlib.import_module("helper.chimera_port")


_client = load_by_path("helper_ollama_client", os.path.join(HELPER, "runner", "ollama_client.py"))
OllamaError, normalize_host = _client.OllamaError, _client.normalize_host

MAX_REPLY_TOKENS = 16384  # the runaway guard on every call (thinking included): the combine, planner and reviewer too
# The reply cap, on a worker step's reply only: 6,144 tokens of CONTENT, the num_predict the plan gives Hydra
# Worker's Modelfile as its runaway guard (docs/hydra-worker-plan.md, Modelfile). Thinking doesn't count toward it
# (decided Oct 30: in the verifier's smoke run qwen3:8b's ordinary, non-looping thinking filled the whole 6,144 on 3
# of 6 replies, so a cap with thinking in it measured the cap, not the model); a thinking model's whole reply is
# held to the guard instead. Chimera 0.7.0 sends no num_predict and no think field for a step and has no cap at all.
REPLY_CAP = 6144
RUNNER_CUT = "runner_cut"  # done_reason when the cap or the guard stopped reading


class Ollama(_client.Ollama):
    """helper-model's client, plus two limits: chat() counts streamed chunks (about one token each), content and
    thinking apart, stops reading at a limit and closes the stream, which makes Ollama stop generating.
    - the runaway guard (max_tokens, 16,384): every call, thinking included;
    - the reply cap (content_cap, 6,144; a worker step's reply only, see ask(worker=True)): content tokens alone.
    The request is unchanged; the reply is marked done_reason "runner_cut", error "runaway: ...", and stats
    "runner_limit" (the number), "runner_limit_kind" ("cap" or "guard"), "runaway_in" ("thinking": the guard hit
    while the model was still thinking; "content": over the content cap, or the guard hit while writing content),
    plus "content_tokens" and "thinking_tokens". Without a limit a small model that loops runs until the time
    limit: qwen3:4b-instruct-2507 wrote 73,000 tokens (Ollama shifting its 8K context) on one W2 case on Oct 29
    before the first smoke run was stopped."""

    max_tokens = MAX_REPLY_TOKENS
    reply_cap = REPLY_CAP

    def chat(self, body, total_timeout=0.0, content_cap=None):
        """content_cap: this call's cap on content tokens (a worker step's reply cap; 0 or None: none). The guard
        (self.max_tokens) holds content and thinking together."""
        import socket
        import urllib.error
        import urllib.request
        guard = self.max_tokens or 0
        cap = content_cap or 0
        if not guard and not cap:
            return super().chat(body, total_timeout)
        limit = total_timeout or self.timeout
        t0 = time.monotonic()
        out = {"content": "", "thinking": "", "stats": {}, "error": None, "format_dropped": False,
               "wall_s": None, "first_token_s": None, "first_content_s": None}
        req = urllib.request.Request(self.base + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            resp = urllib.request.urlopen(req, timeout=min(limit, 120.0))
        except urllib.error.HTTPError as e:
            out.update(error=_client._err_text(e), wall_s=time.monotonic() - t0)
            return out
        except (urllib.error.URLError, OSError) as e:
            out.update(error=f"can't reach Ollama: {getattr(e, 'reason', e)}", wall_s=time.monotonic() - t0)
            return out
        content, thinking, n, n_content, n_thinking = [], [], 0, 0, 0
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
                    now_s = time.monotonic() - t0
                    if (c or th) and out["first_token_s"] is None:
                        out["first_token_s"] = now_s
                    if c and out["first_content_s"] is None:
                        out["first_content_s"] = now_s
                    content.append(c)
                    thinking.append(th)
                    if chunk.get("done"):
                        done = True
                        out["stats"] = {k: chunk.get(k) for k in ("prompt_eval_count", "eval_count", "total_duration",
                                                                   "load_duration", "prompt_eval_duration",
                                                                   "eval_duration", "done_reason")}
                        out["stats"].update(content_tokens=n_content, thinking_tokens=n_thinking)
                        break
                    if c or th:
                        n += 1
                        if c:
                            n_content += 1
                        else:
                            n_thinking += 1
                        hit = None
                        if cap and n_content >= cap:
                            hit = (cap, "cap", "content")
                        elif guard and n >= guard:
                            hit = (guard, "guard", "content" if c else "thinking")
                        if hit:
                            what = (f"the reply cap, {n_content} content tokens" if hit[1] == "cap" else
                                    f"the runaway guard, while {'thinking' if hit[2] == 'thinking' else 'writing content'}")
                            out["error"] = f"runaway: the runner stopped reading after {n} tokens ({what})"
                            out["stats"] = {"eval_count": n, "done_reason": RUNNER_CUT, "runner_limit": hit[0],
                                            "runner_limit_kind": hit[1], "runaway_in": hit[2],
                                            "content_tokens": n_content, "thinking_tokens": n_thinking,
                                            "eval_duration": int((time.monotonic() - t0) * 1e9)}
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


def ctx_bucket(need: int, max_ctx: int = 0) -> int:
    """ctxBucket (app/hub.go): the num_ctx Chimera asks Ollama for."""
    b = 8192
    if need > 65536:
        b = 131072
    elif need > 30000:
        b = 65536
    elif need > 7000:
        b = 32768
    if max_ctx > 0 and b > max_ctx:
        b = max_ctx
    return b


def chat_body(model, messages, need_ctx, ctx_max=0, options=None, fmt=None, keep_alive=KEEP_ALIVE):
    """The /api/chat body Chimera sends for a step (ChatStreamKeep, app/ollama.go). options are added on top of
    num_ctx (runStep's num_predict after a cut-off); fmt only for JSON jobs (the planner and reviewer)."""
    opts = {"num_ctx": ctx_bucket(need_ctx, ctx_max)}
    opts.update(options or {})
    body = {"model": model, "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
            "stream": True, "keep_alive": keep_alive, "options": opts}
    if fmt is not None:
        body["format"] = fmt
    return body


def ask(client, body, timeout, attempts=2, worker=False):
    """One call as runStep makes it: up to two tries when the call itself fails (not for a bad reply). worker: a
    worker step's reply, its content held to the client's reply cap (and the whole reply, thinking included, to
    the runaway guard, which is all other calls get). A reply the cap or the guard cut isn't tried again (it is a
    runaway, not a failed call). Returns the client's call dict plus "attempts" and "errors" (the earlier tries')."""
    errors = []
    call = None
    cap = getattr(client, "reply_cap", 0) if worker else None
    for n in range(1, attempts + 1):
        call = client.chat(body, timeout, content_cap=cap) if cap else client.chat(body, timeout)
        if not call["error"] or runaway(call):
            break
        errors.append(call["error"])
    call["attempts"], call["errors"] = n, errors[:-1] if call["error"] else errors
    return call


def runaway(call):
    """The reply cap or the runaway guard stopped this reply (done_reason "runner_cut")."""
    return (call.get("stats") or {}).get("done_reason") == RUNNER_CUT


def runaway_in(call_or_stats):
    """Where a runaway was cut: "thinking" (the guard hit while the model was still thinking) or "content" (over the
    content cap, or the guard hit while it wrote content); None when it wasn't a runaway."""
    st = call_or_stats.get("stats") if "stats" in call_or_stats else call_or_stats
    st = st or {}
    if st.get("done_reason") != RUNNER_CUT:
        return None
    return st.get("runaway_in") or "content"


def tok_s(stats):
    """Output tokens a second from Ollama's own eval counters (None when it didn't say)."""
    n, d = (stats or {}).get("eval_count"), (stats or {}).get("eval_duration")
    return round(n / (d / 1e9), 1) if n and d else None


def call_fields(call):
    """What a raw.jsonl record keeps of one call."""
    st = call.get("stats") or {}
    return {"stats": st, "done_reason": st.get("done_reason"), "tok_s": tok_s(st),
            "wall_s": round(call["wall_s"], 3) if call.get("wall_s") is not None else None,
            "first_token_s": call.get("first_token_s"), "first_content_s": call.get("first_content_s"),
            "error": call.get("error"), "attempts": call.get("attempts", 1), "errors": call.get("errors", []),
            "thinking_chars": len(call.get("thinking") or ""), "content_chars": len(call.get("content") or ""),
            "runaway_in": runaway_in(call)}


def model_info(client, model):
    """Details, context length, digest and size of a model in the local Ollama (raises OllamaError)."""
    info = {"model": model}
    show = client.show(model)
    info["details"] = show.get("details") or {}
    mi = show.get("model_info") or {}
    ctx = [v for k, v in mi.items() if k.endswith(".context_length")]
    info["context_length"] = int(ctx[0]) if ctx else 0
    info["capabilities"] = show.get("capabilities") or []
    want = model if ":" in model else model + ":latest"
    for t in client.tags():
        if t.get("name") == want or t.get("model") == want:
            info["digest"] = t.get("digest", "")
            info["size"] = t.get("size")
    return info


def loaded_models(client):
    """Names Ollama has loaded right now (/api/ps), so a run unloads only what it loaded itself."""
    try:
        return {m.get("name") or m.get("model") for m in client._json("GET", "/api/ps").get("models", [])}
    except OllamaError:
        return set()


def warm_up(client, model, num_ctx):
    """Load the model at the context the run starts with (a changed num_ctx reloads it), so the first case's
    timing isn't the load. Returns the call dict."""
    return client.chat({"model": model, "messages": [{"role": "user", "content": "Reply with OK."}], "stream": True,
                        "keep_alive": KEEP_ALIVE, "options": {"num_ctx": num_ctx}}, 600)


def slug(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s or "").strip("-")


def now():
    return datetime.datetime.now().astimezone()


def new_run_dir(out, *labels):
    """out/<time>-<label>-<label>…, made unique when two runs start in the same second."""
    run_dir = os.path.join(out, now().strftime("%Y%m%d-%H%M%S") + "".join("-" + slug(x) for x in labels if x))
    base, n = run_dir, 1
    while os.path.exists(run_dir):
        n += 1
        run_dir = f"{base}-{n}"
    os.makedirs(run_dir)
    return run_dir


def write_json(path, obj):
    """Write JSON atomically (a crash mid-write never leaves half a file, which matters for resumable runs)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def rel(path):
    """A path relative to worker-model/ when it is inside it (for messages)."""
    try:
        r = os.path.relpath(path, HERE)
        return path if r.startswith("..") else r
    except ValueError:
        return path


def pct(n, d):
    return None if not d else round(100.0 * n / d, 1)


def fmt_pct(v):
    return "–" if v is None else f"{v:.0f}%"


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def timer():
    t0 = time.monotonic()
    return lambda: round(time.monotonic() - t0, 2)


def md_table(rows):
    """A Markdown table from a header row and data rows."""
    rows = [[("–" if c is None or c == "" else str(c)).replace("|", "/").replace("\n", " ") for c in r] for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "|".join("---" for _ in rows[0]) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)
