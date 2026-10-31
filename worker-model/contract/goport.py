"""Small Python ports of Chimera's Go helpers that the contract code needs. Each names the Go it mirrors.

Kept here rather than imported from helper-model/helper/chimera_port.py so the two folders don't share
a package path; tests/test_contract_today.py checks clean_plan and truncate against that port.
"""
from __future__ import annotations

import copy
import re

KINDS = ("code", "writing", "research", "blender", "general")  # cleanPlan's kinds map (app/hydra.go)

# unicode.IsSpace, which strings.TrimSpace uses (str.strip() would also strip \x1c-\x1f).
_GO_SPACE = ("\t\n\v\f\r \x85\xa0        "
             "        　")


def go_trim_space(s: str) -> str:
    """strings.TrimSpace."""
    return s.strip(_GO_SPACE)


def truncate(s: str, n: int) -> str:
    """truncate (app/library.go 454-462): keep n bytes, never cutting through a UTF-8 character."""
    b = s.encode("utf-8")
    if len(b) <= n:
        return s
    while n > 0 and (b[n] & 0xC0) == 0x80:
        n -= 1
    return b[:n].decode("utf-8") + "\n…(cut)"


def cap_runes(s: str, n: int) -> str:
    """capRunes (app/hydra_check.go): at most n characters, the last one an ellipsis."""
    if len(s) <= n:
        return s
    return s[:n - 1] + "…"


def estimate_tokens(s: str) -> int:
    """estimateTokens (app/library.go)."""
    return len(s.encode("utf-8")) // 3 + 64


def history_tokens(msgs) -> int:
    """historyTokens (app/runprompt.go)."""
    return sum(estimate_tokens(m["content"]) for m in msgs)


def clean_plan(plan: dict) -> dict:
    """cleanPlan (app/hydra.go 799-841): what Chimera does to a decoded plan before running it."""
    p = copy.deepcopy(plan)
    steps = list(p.get("steps") or [])[:8]
    if p.get("kind") not in KINDS:
        p["kind"] = "general"
    ids = set()
    for i, s in enumerate(steps):
        s.setdefault("id", "")
        s.setdefault("title", "")
        s.setdefault("instructions", "")
        if s["id"] == "" or s["id"] in ids:
            s["id"] = f"s{i + 1}"
        ids.add(s["id"])
        if s.get("kind") not in KINDS:
            s["kind"] = p["kind"]
        if go_trim_space(s["title"]) == "":
            s["title"] = f"Step {i + 1}"
        if go_trim_space(s["instructions"]) == "":
            s["instructions"] = s["title"]
        s["status"] = "waiting"
    seen = set()  # keep only dependencies on earlier steps: that rules out cycles
    for s in steps:
        s["depends_on"] = [d for d in (s.get("depends_on") or []) if d in seen]
        seen.add(s["id"])
    if go_trim_space(p.get("title") or "") == "":
        p["title"] = "Long task"
    p.setdefault("summary", "")
    p["steps"] = steps
    return p


# ---------------------------------------------------------------- code blocks

_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


class Block:
    """One fenced block. open_line / close_line are 0-based line indexes of the fences in the reply
    (close_line is None for a block left open)."""

    __slots__ = ("lang", "body", "closed", "open_line", "close_line", "info")

    def __init__(self, lang, info, open_line):
        self.lang, self.info, self.open_line = lang, info, open_line
        self.body, self.closed, self.close_line = "", False, None

    def __repr__(self):
        return f"Block({self.lang!r}, lines {self.open_line}-{self.close_line}, closed={self.closed})"


def code_blocks(md: str):
    """codeBlocks (app/hydra_check.go 87-129): the fenced blocks of a reply (``` or ~~~), with line indexes."""
    out = []
    cur = None
    fence = ""
    body = []
    indent = 0  # the opening fence's, which its lines share (a fence in a list item)
    for i, line in enumerate(md.split("\n")):
        line = line.rstrip("\r")
        if cur is None:
            m = _FENCE_OPEN.match(line)
            if not m or (m.group(1)[0] == "`" and "`" in m.group(2)):
                continue
            f = m.group(2).split()
            lang = f[0].lower().strip("{}").removeprefix(".") if f else ""
            cur, fence, body = Block(lang, m.group(2).strip(), i), m.group(1), []
            indent = len(line) - len(line.lstrip(" "))
            continue
        t = line.lstrip(" ")
        if len(line) - len(t) <= 3 and t.startswith(fence[0]):
            run = len(t) - len(t.lstrip(fence[0]))
            if run >= len(fence) and go_trim_space(t[run:]) == "":
                cur.body, cur.closed, cur.close_line = "\n".join(body), True, i
                out.append(cur)
                cur = None
                continue
        for _ in range(indent):
            if not line.startswith(" "):
                break
            line = line[1:]
        body.append(line)
    if cur is not None:
        cur.body = "\n".join(body)
        out.append(cur)
    return out


def python_lang(lang: str) -> bool:
    """pythonLang (app/hydra_check.go)."""
    return lang in ("python", "py", "python3", "bpy") or lang.endswith(".py")


BPY_IMPORT = re.compile(r"(?m)^\s*(import\s+([\w.]+\s*,\s*)*bpy\b|from\s+bpy\b)")  # bpyImport
