"""Python ports of the parts of Chimera (app/*.go) that build the three helper jobs' requests
and decide what a model's reply means. Each function names the Go code it mirrors.

tools/check_prompts_sync.py fails if any Go line ported here changes, so a drift shows up as
a failing check instead of a quietly wrong eval or a filter that keeps bad training data.
Known approximations (none affects realistic replies) are marked "approx".
"""
from __future__ import annotations

import copy
import json
import math
import re

from . import prompts

KINDS = ("code", "writing", "research", "blender", "general")  # cleanPlan's kinds map

# ---------------------------------------------------------------- strings and sizes

# unicode.IsSpace, which strings.TrimSpace uses. Python's str.strip() would also strip
# \x1c-\x1f, which Go keeps.
_GO_SPACE = ("\t\n\v\f\r \x85\xa0         "
             "       　")


def go_trim_space(s: str) -> str:
    """strings.TrimSpace."""
    return s.strip(_GO_SPACE)


def truncate(s: str, n: int) -> str:
    """truncate (app/library.go): keep n bytes, never cutting through a UTF-8 character."""
    b = s.encode("utf-8")
    if len(b) <= n:
        return s
    while n > 0 and (b[n] & 0xC0) == 0x80:
        n -= 1
    return b[:n].decode("utf-8") + "\n…(cut)"


def estimate_tokens(s: str) -> int:
    """estimateTokens (app/library.go)."""
    return len(s.encode("utf-8")) // 3 + 64


def history_tokens(msgs) -> int:
    """historyTokens (app/runprompt.go)."""
    return sum(estimate_tokens(m["content"]) for m in msgs)


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

# ---------------------------------------------------------------- Go encoding/json

STRING, BOOL, INT, FLOAT, TIME = "string", "bool", "int", "float", "time"

# hydraStep (app/hydra.go). Chimera fills most of these itself, but they are decoded from the
# planner's reply too, so a wrong type in any of them (say "tokens": "a few") rejects the plan.
STEP_SPEC = {
    "id": STRING, "title": STRING, "kind": STRING, "instructions": STRING,
    "depends_on": ("slice", STRING), "status": STRING, "device": STRING, "owner": STRING,
    "model": STRING, "output": STRING, "tokens": INT, "tok_s": FLOAT, "credits": FLOAT,
    "free": BOOL, "local": BOOL, "note": STRING, "error": STRING, "from_library": STRING,
    "started": TIME, "finished": TIME,
}
PLAN_SPEC = {"title": STRING, "kind": STRING, "summary": STRING, "steps": ("slice", ("struct", STEP_SPEC))}
REVIEW_SPEC = {"done": BOOL, "score": INT, "critique": STRING}  # reviewVerdict (app/hydra.go)
GATE_SPEC = {"use": BOOL}  # the anonymous struct in headGate (app/plugin_chat.go)


class GoDecodeError(ValueError):
    pass


class _Obj(list):
    """A JSON object as its (key, value) pairs, in order, duplicates kept."""


def reject_constant(name):
    raise ValueError(f"{name} is not JSON")  # Go rejects NaN and Infinity; Python accepts them


def _loads_pairs(text):
    return json.loads(text, object_pairs_hook=_Obj, parse_constant=reject_constant)


_INT64 = (-(1 << 63), (1 << 63) - 1)
_RFC3339 = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?([Zz]|[+-](\d{2}):(\d{2}))$")


def _rfc3339_ok(s):  # time.Time.UnmarshalJSON (approx: Go's own range checks)
    m = _RFC3339.match(s)
    if not m:
        return False
    mo, d, h, mi, sec = (int(m.group(i)) for i in (2, 3, 4, 5, 6))
    return 1 <= mo <= 12 and 1 <= d <= 31 and h < 24 and mi < 60 and sec < 60


def _zero(t):
    if t == STRING:
        return ""
    if t == BOOL:
        return False
    if t == INT:
        return 0
    if t == FLOAT:
        return 0.0
    if t == TIME:
        return None
    if t[0] == "slice":
        return None  # a nil slice
    return {k: _zero(v) for k, v in t[1].items()}


def _kind(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number " + json.dumps(v)
    if isinstance(v, str):
        return "string"
    return "object" if isinstance(v, _Obj) else "array"


def _decode(v, t, path):
    """Decode one JSON value into a Go value of type t, as encoding/json would."""
    if v is None:
        return _zero(t)
    if t == STRING:
        if isinstance(v, str):
            return v
    elif t == BOOL:
        if isinstance(v, bool):
            return v
    elif t == INT:  # Go parses the literal with ParseInt: 85.0 and 1e2 fail
        if isinstance(v, int) and not isinstance(v, bool) and _INT64[0] <= v <= _INT64[1]:
            return v
    elif t == FLOAT:
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            return float(v)
    elif t == TIME:
        if isinstance(v, str) and _rfc3339_ok(v):
            return v
    elif t[0] == "slice":
        if isinstance(v, list) and not isinstance(v, _Obj):
            return [_decode(x, t[1], f"{path}[{i}]") for i, x in enumerate(v)]
    elif t[0] == "struct":
        if isinstance(v, _Obj):
            return _decode_struct(v, t[1], path)
    raise GoDecodeError(f"{path}: Go can't decode {_kind(v)} into {t}")


def _decode_struct(obj, spec, path):
    out = {k: _zero(t) for k, t in spec.items()}
    folded = {k.lower(): k for k in spec}
    for key, val in obj:
        # Exact match first, then case-insensitive, as encoding/json does (approx: ASCII
        # folding only). Unknown keys are ignored.
        name = key if key in spec else folded.get(key.lower())
        if name is None:
            continue
        t = spec[name]
        if val is None:  # null zeroes a slice and leaves anything else as it was
            if isinstance(t, tuple) and t[0] == "slice":
                out[name] = None
            continue
        # A repeated key wins over an earlier one (approx: Go decodes a repeated array into
        # the elements already there, merging them; that only matters for a repeated "steps").
        out[name] = _decode(val, t, f"{path}.{key}")
    return out


def go_unmarshal(text, spec):
    """json.Unmarshal(text, &struct). Returns (ok, value)."""
    try:
        raw = _loads_pairs(text)
    except ValueError:
        return False, None
    try:
        if raw is None:  # Unmarshal("null") succeeds and leaves the zero value
            return True, _zero(("struct", spec))
        if not isinstance(raw, _Obj):
            raise GoDecodeError(f"$: Go can't decode {_kind(raw)} into a struct")
        return True, _decode_struct(raw, spec, "$")
    except GoDecodeError:
        return False, None


def extract_json(s: str, spec: dict):
    """extractJSON (app/library.go) decoding into the Go struct described by spec.

    Returns (ok, value, text_used). value is the struct as a dict, with Go's zero values for
    missing fields: exactly what Chimera goes on to use."""
    s = go_trim_space(s)
    ok, v = go_unmarshal(s, spec)
    if ok:
        return True, v, s
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return False, None, None
    frag = s[start:end + 1]
    ok, v = go_unmarshal(frag, spec)
    return (True, v, frag) if ok else (False, None, None)

# ---------------------------------------------------------------- cleanPlan

def clean_plan(plan: dict) -> dict:
    """cleanPlan (app/hydra.go): what Chimera does to a decoded plan before running it."""
    p = copy.deepcopy(plan)
    steps = list(p.get("steps") or [])
    if len(steps) > 8:
        steps = steps[:8]
    if p["kind"] not in KINDS:
        p["kind"] = "general"
    ids = set()
    for i, s in enumerate(steps):
        if s["id"] == "" or s["id"] in ids:  # note: a renamed id isn't re-checked, so it can still clash
            s["id"] = f"s{i + 1}"
        ids.add(s["id"])
        if s["kind"] not in KINDS:
            s["kind"] = p["kind"]
        if go_trim_space(s["title"]) == "":
            s["title"] = f"Step {i + 1}"
        if go_trim_space(s["instructions"]) == "":
            s["instructions"] = s["title"]
        s["status"] = "waiting"
    seen = set()  # keep only dependencies on earlier steps: that rules out cycles
    for s in steps:
        s["depends_on"] = [d for d in (s["depends_on"] or []) if d in seen]
        seen.add(s["id"])
    if go_trim_space(p["title"]) == "":
        p["title"] = "Long task"
    p["steps"] = steps
    return p

# ---------------------------------------------------------------- Head word filter

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_+#.-]*")
_WORDS_ONLY_DROP = frozenset(["it", "just", "thing", "like", "want", "need"])
WORD_RULE_MIN = 0.75  # headForText: with no model to ask, only this strong a word match counts


def tokenize(s: str):
    """tokenize (app/library.go)."""
    seen, out = set(), []
    for w in _WORD_RE.findall(s.lower()):
        w = w.strip(".-")
        if len(w) < 2 or w in prompts.STOP_WORDS or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


def plugin_terms(q: str, with_input: bool = False):
    """pluginTerms (app/hub_plugins.go)."""
    out = []
    for t in tokenize(q):
        if with_input and t in prompts.PLUGIN_WEAK_WORDS:
            continue
        if not with_input and t in _WORDS_ONLY_DROP:
            continue
        out.append(t)
    return out


def _round2(v):  # round2 (app/util.go); math.Round rounds half away from zero
    return math.floor(v * 100 + 0.5) / 100 if v >= 0 else -math.floor(-v * 100 + 0.5) / 100


def plugin_relevance(terms, head: dict) -> float:
    """pluginRelevance (app/hub_plugins.go)."""
    if not terms:
        return 0.0
    name = (head["name"] + " " + head["id"]).lower()
    tags = " ".join(list(head.get("tags") or []) + list(head.get("task_kinds") or [])).lower()
    summary = (head.get("summary") or "").lower()
    when = (head.get("when_to_use") or "").lower()
    total = 0.0
    for t in terms:
        if t in name:
            total += 3
        elif t in tags:
            total += 2.5
        elif t in summary:
            total += 1.5
        elif t in when:
            total += 1
    return _round2(min(1.0, total / 6))


def reaches_gate(text: str, head: dict):
    """Would headForText put this Head in front of the gate for a message with no picture?

    Mirrors the word filter in localPluginCandidates / pluginCandidatesLocked for one Head
    (ratings, devices and other Heads aside). Returns (reaches, relevance, terms)."""
    if go_trim_space(text) == "":
        return False, 0.0, []
    terms = plugin_terms(text, False)
    if head.get("accepts") and not head.get("optional_input"):
        return False, 0.0, terms  # it needs a file and none was given
    rel = plugin_relevance(terms, head)
    if terms and rel < prompts.PLUGIN_MIN_RELEVANCE:
        return False, rel, terms
    return True, rel, terms

# ---------------------------------------------------------------- requests

def context_block(history) -> str:
    """contextBlock (app/hydra.go)."""
    if not history:
        return ""
    if len(history) > 6:
        history = history[-6:]
    parts = ["Earlier in this chat (for context only):\n"]
    for m in history:
        parts.append("\n[%s]\n%s\n" % (m["role"], truncate(m["content"], 2500)))
    parts.append("\n---\nThe task:\n")
    return "".join(parts)


def refs_block(refs) -> str:
    """refsBlock (app/hydra.go). refs: dicts with title, kind, summary, content."""
    if not refs:
        return ""
    parts = ["\n\nKnown-good references from your network's library, checked by the network "
             "(reuse them when they fit; ignore them when they don't):\n"]
    for e in refs:
        parts.append("\n--- %s (%s) ---\n%s\n%s\n" % (e["title"], e["kind"], e["summary"], truncate(e["content"], 3000)))
    return "".join(parts)


def planner_messages(goal, history=None, prior="", critique="", refs=None):
    """The planner's messages in onePass (app/hydra.go)."""
    user = context_block(history or []) + goal
    if prior:
        user += ("\n\n---\nThe previous attempt produced this result:\n" + truncate(prior, 12000) +
                 "\n\nWhat still needs work:\n" + critique +
                 "\n\nPlan the steps to improve it into a result that fully meets the task. "
                 "Reuse what already works; only redo what needs it.")
    user += refs_block(refs or [])
    return [{"role": "system", "content": prompts.HYDRA_PLANNER_PROMPT}, {"role": "user", "content": user}]


def review_messages(goal, result):
    """The reviewer's messages in review (app/hydra.go)."""
    return [{"role": "system", "content": prompts.HYDRA_REVIEW_PROMPT},
            {"role": "user", "content": "The task:\n" + goal + "\n\nThe result so far:\n" + truncate(result, 40000)}]


def head_description(head) -> str:
    """desc in headGate (app/plugin_chat.go). when_not_to_use is not part of it."""
    desc = head["name"] + ": " + head["summary"]
    if head.get("when_to_use"):
        desc += "\nUse it when: " + head["when_to_use"]
    return desc


def gate_messages(head, text):
    """The gate's messages in headGate (app/plugin_chat.go)."""
    return [{"role": "system", "content": prompts.HEAD_GATE_PROMPT},
            {"role": "user", "content": "Tool: " + head_description(head) + "\n\nRequest: " + text +
             "\n\nShould this tool handle the request?"}]


_EXTRA_CTX = {"planner": 2048, "reviewer": 1024, "gate": 256}


def chat_body(job, model, messages, ctx_max=0):
    """The /api/chat body Chimera sends for a job (runPrompt → ChatStream, app/ollama.go).

    Planner and reviewer: format "json", the model's own sampling defaults. Gate: the
    headGateSchema format and temperature 0. No "think" field: Chimera never sets one."""
    options = {"num_ctx": ctx_bucket(history_tokens(messages) + _EXTRA_CTX[job], ctx_max)}
    if job == "gate":
        fmt = json.loads(prompts.HEAD_GATE_SCHEMA)
        options["temperature"] = 0
    else:
        fmt = "json"
    return {"model": model, "messages": messages, "stream": True, "keep_alive": "15m",
            "options": options, "format": fmt}
