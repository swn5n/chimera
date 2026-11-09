"""Mechanical fixes of a model's reply before it is checked: characters and lines rewritten by code, never words
added (results/DATAGEN-SMOKE.md, items 1 and 5). task.py's precheck calls them before every other check, keeps the
fixed text as the candidate's content and records how many lines changed; the raw reply stays in the call cache.

    text, n = file_lines(reply)       # files and python-script modes
    text, m = marker_dashes(reply)    # blender
    text, k = handoff_fence(reply)    # every code mode (blender, python-script, files), a step that isn't lone

file_lines: gpt-oss wrote 160 of its 163 File lines in the smoke as "**File: path**", which Chimera joins but the
validator calls file_line_decorated, a near miss of the written form a target may not have; made plain, 84 of its 97
files candidates pass the validator instead of 3. A decorated File line ("**File: x**", "`File: x`", "### File: x",
"*File:* x", "**File:** x (part)") becomes the contract's "File: x" or "File: x (part)", and so does one Go passes
that isn't quite that form ("File: `x`", "File:x"), so every target teaches one form. Only the line the validator
reads as a block's File line is touched: the last non-blank line before an opening fence (blank lines between are
skipped, as Go's _files_piece skips them), which is never inside a block. A File line inside a block is the block's
text and stays; so does one with other words after the path ("File: x.py, the store"), since only decoration
characters (* _ # > ` - and spaces) are ever dropped, and a line the validator doesn't read as a File line at all.
The path is the one the validator reads (contract.validate.file_line), and so is whether it is a part, so the join sees
the same file: " (part)" is written only when Go read the line as a part. Go reads "**File: x (part)**" and
"`File: x (part)`" as the whole file x (the "(part)" sits inside the decoration), so such a line stays as it is and
the candidate fails on form, as it did before this module: written plain as a part it would change the join, and
without its "(part)" it would lose the model's word (3 lines in the smoke; one gained a part_not_mergeable seam).

marker_dashes: the contract's stand-in marker is print("chimera: stand-in", key), and the gates look for it with
an ASCII hyphen; 76 of gpt-oss's 120 Blender pieces with the marker wrote it with U+2011. In a line whose marker has
U+2010, U+2011, U+2012 or U+2212 for its hyphen, those characters become "-" (in that line only: elsewhere they are
the model's typography). U+2013, which gpt-oss puts after the marker as a separator ("stand\u2011in \u2013 SVG not
found"), is left alone.

handoff_fence: the contract ends a piece with a ```handoff block; gpt-oss often writes the block's language as its
first line instead, an untagged fence whose first line is just "handoff", then the provides:, uses: and assumed:
lines and the closing fence, which the validator doesn't read as a handoff at all (handoff_missing: 11 of the 12
such Blender tries of the fourth smoke, 8 of 9 in the third, 9 of 10 in the second; no other mode wrote it). Two forms
are fixed, and only at the very end of the reply (nothing but blank lines after): that block becomes a
```handoff block (the fence line tagged, the "handoff" line dropped), and a closing fence glued to the end of the
assumed: line, the reply's last line, of that block or of a ```handoff one ("assumed: none```", which the validator
calls handoff_unclosed_end) goes on a line of its own. The block must hold the three key lines and nothing else, each
once; anything more, another language (```text), a label written above the fence or inside the code block (a
docstring), another handoff block, or text after it stays as it is and fails as before, and the fix is kept only when
the validator then reads the contract's fenced block, closed and last, with no handoff issue (contract.validate).
task.normalised leaves a lone step's reply alone: the contract gives a lone step no handoff, so a block there isn't
one to make. On the stored tries of smoke2-4 it changes 30 (9, 9 and 12, every one gpt-oss's Blender), and 28 of them
then pass the validator (two are too long or save the file). Through the integrated gate and Round.gate (dep_honesty
after it), as the round was joined and checked (DESIGN.md, "After the fourth smoke", Integrated and Independent
checks), 2 then pass: smoke4's blender-0002-02 s3 c3, in a step its batch kept anyway, and smoke2's n-blender-0002-01
s3 c3, in a step kept from a repair that gave no example; smoke3's blender-0008-00 s1 c3 fails marker_misused,
softly, and smoke3's failed-dependency variant of n-blender-0000-01 r2 s3 (c1) passes the gate but fails
dep_claimed:s2, so the fence wins no smoke3 example.
"""
from __future__ import annotations

import re

from contract import validate as cv
from contract.goport import code_blocks, go_trim_space

_DECOR = "*_#>`- \t"  # what a decorated File line adds around "File:" and its path (the validator's pre/mid/post)
_PART = re.compile(r"\(part\)", re.I)
_DASHES = "\u2010\u2011\u2012\u2212"
_MARKER = re.compile(r"chimera:\s*stand[" + _DASHES + r"]in", re.I)
_DASH_MAP = str.maketrans({c: "-" for c in _DASHES})
_KEY_LINE = re.compile(r"^\s*(provides|uses|assumed)\s*:", re.I)  # contract.validate's _HANDOFF_KEY, the key only
_GLUED = re.compile(r"^(\s*assumed\s*:.*?)[ \t]*(?<!`)```[ \t]*$", re.I)  # "assumed: none```"
_HANDOFF_CODES = ("handoff_",)  # the validator's handoff issues: missing, many, unclosed, shape, not_last, the forms


def plain_file_line(line):
    """The contract's exact form of a File line ("File: x" or "File: x (part)"), or None when line isn't a File line
    the validator reads, is already in that form, has words after its path other than "(part)", or says "(part)"
    where Go reads a whole file ("**File: x (part)**"). Lines Go passes but that aren't the exact form ("File: `x`",
    "File:x", "File: x:") are written plain too, so every target teaches one form."""
    cr = "\r" if line.endswith("\r") else ""
    body = line[:-1] if cr else line
    got = cv.file_line(body)
    if got is None or not got[0]:
        return None
    path, part = got[0], got[1]
    tail = body.split("File:", 1)[1]
    k = tail.find(path)
    if k < 0 or tail[:k].strip(_DECOR) or (k and tail[k - 1] not in " \t*`"):
        return None  # "File: _config.yml": Go reads config.yml, but the _ may be the name's, so it stays
    after = tail[k + len(path):].strip(_DECOR + ":")
    if after and not _PART.fullmatch(after):
        return None  # other words after the path: not ours to drop
    if bool(after) != part:
        return None  # "**File: x (part)**": the model says part, Go joins the whole file
    new = "File: " + path + (" (part)" if part else "")
    return new + cr if new != body else None


def file_lines(text):
    """(text with every decorated File line of a block made plain, the number of lines changed)."""
    text = text or ""
    lines = text.split("\n")
    n = 0
    for b in code_blocks(text):
        if b.lang == "handoff":
            continue
        j = b.open_line - 1
        while j >= 0 and go_trim_space(lines[j].rstrip("\r")) == "":
            j -= 1
        if j < 0:
            continue
        new = plain_file_line(lines[j])
        if new is not None:
            lines[j] = new
            n += 1
    return ("\n".join(lines), n) if n else (text, 0)


def marker_dashes(text):
    """(text with the stand-in marker's lines written with an ASCII hyphen, the number of lines changed)."""
    text = text or ""
    lines = text.split("\n")
    n = 0
    for k, line in enumerate(lines):
        if _MARKER.search(line):
            lines[k] = line.translate(_DASH_MAP)
            n += 1
    return ("\n".join(lines), n) if n else (text, 0)


def _three_keys(lines):
    """Whether the non-blank lines are the three key lines, each once (blank lines between are fine)."""
    keys = []
    for line in lines:
        if go_trim_space(line.rstrip("\r")) == "":
            continue
        m = _KEY_LINE.match(line)
        if not m:
            return False
        keys.append(m.group(1).lower())
    return sorted(keys) == ["assumed", "provides", "uses"]


def _fenced_last(text):
    """Whether the validator reads text's handoff as the contract's: one ```handoff block, closed, nothing after it
    but blank lines, and no handoff issue (contract.validate.parse_handoff)."""
    handoff, blocks, issues = cv.parse_handoff(text)
    if handoff is None or len(blocks) != 1 or cv.handoff_blocks(text)[1] != "fenced" or not blocks[0].closed:
        return False
    if any(i.code.startswith(_HANDOFF_CODES) for i in issues):
        return False
    return go_trim_space("\n".join(text.split("\n")[blocks[0].close_line + 1:])) == ""


def handoff_fence(text):
    """(text with the handoff block at its end put in the contract's fence, the number of fixes: 1 for a tagged fence,
    1 for a closing fence moved off the assumed line). See the module's docstring for the two forms; (text, 0) for
    anything else."""
    text = text or ""
    blocks = code_blocks(text)
    if not blocks:
        return text, 0
    b = blocks[-1]
    if b.lang == "handoff" and b.closed:
        return text, 0  # the contract's form already, or a fault the validator names
    lines = text.split("\n")
    if b.closed and go_trim_space("\n".join(lines[b.close_line + 1:])) != "":
        return text, 0  # text after the last block: not the end of the reply
    new, n = list(lines), 0
    first = b.open_line + 1
    if b.lang == "" and lines[b.open_line].strip(" \t\r") == "```" and first < len(lines) and \
            lines[first].strip(" \t\r") == "handoff":
        cr = "\r" if lines[b.open_line].endswith("\r") else ""
        new[b.open_line] = lines[b.open_line].rstrip(" \t\r") + "handoff" + cr
        del new[first]
        n += 1
    elif b.lang != "handoff":
        return text, 0
    if b.closed:
        close = b.close_line - 1  # the "handoff" line is gone
        if any(line.rstrip(" \t\r").endswith("`") for line in new[b.open_line + 1:close]):
            return text, 0  # a fence glued to a line of a block closed after it: not one of the two forms
    else:  # an open block runs to the end of the reply: its closing fence may be glued to the assumed line
        end = len(new) - 1
        while end > b.open_line and go_trim_space(new[end].rstrip("\r")) == "":
            end -= 1
        m = _GLUED.match(new[end].rstrip("\r"))
        if not m:
            return text, 0
        cr = "\r" if new[end].endswith("\r") else ""
        new[end:end + 1] = [m.group(1).rstrip(" \t") + cr, "```" + cr]
        n += 1
        close = end + 1
    if not _three_keys(new[b.open_line + 1:close]):
        return text, 0
    out = "\n".join(new)
    return (out, n) if _fenced_last(out) else (text, 0)
