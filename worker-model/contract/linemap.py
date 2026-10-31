"""Which step a line of a joined script came from, and what a check's crash line means for repair.

    lm = joined.linemap                  # from join.join(), or LineMap.load("linemap.json")
    lm.locate(23)                        # {"line": 23, "step": "s2", "part": "build", "function": "build_s2", …}
    locate_check(check_json, lm)         # the same for the JSON `chimera --check-result script.py` prints

Each joined line has an origin [sid, part, function, piece_line] or None (a line Chimera wrote, like the
header). part is one of:
- build: inside def build_sN (or a function nested in it)
- helper: a top-level _sN_ helper, class or constant (blender) / code: any top-level statement of the step
  (python-script); function is its name (a constant's first name)
- settings: the step's SETTINGS_sN dict (function "SETTINGS_sN")
- import: a deduplicated import. Each joined import line is one import statement of one piece, less the names
  an earlier step already imported, so it belongs to the step that wrote the names on it.
- main / output: Chimera's main() and _chimera_output (step None: a crash there is a seam, not one step's)
piece_line is the line in the step's own python block, the numbering the repair message uses.

A crash counts for step repair ("repair": sid) when it is in that step's build function, helpers, code,
settings or imports (an ImportError on a name only that step imported). The check reports the innermost line
of script.py in the traceback, so a crash inside a helper of s1 that s3 called with bad arguments is placed
in s1: a limit of a one-line check.
"""
from __future__ import annotations

import json

REPAIRABLE = ("build", "helper", "code", "settings", "import")


class LineMap:
    def __init__(self, origins, titles=None, kind=""):
        self.origins = list(origins)  # index 0 is line 1
        self.titles = dict(titles or {})
        self.kind = kind  # blender / python-script

    def __len__(self):
        return len(self.origins)

    def locate(self, line):
        """Where joined-script line `line` (1-based) came from."""
        out = {"line": line, "step": None, "title": None, "part": None, "function": None, "piece_line": None,
               "repair": None}
        if not isinstance(line, int) or line < 1 or line > len(self.origins):
            out["part"] = "outside"
            return out
        o = self.origins[line - 1]
        if o is None:
            out["part"] = "chimera"
            return out
        sid, part, function, piece_line = o
        out.update(step=sid, title=self.titles.get(sid) if sid else None, part=part, function=function,
                   piece_line=piece_line, repair=sid if sid and part in REPAIRABLE else None)
        return out

    def lines_of(self, sid):
        """The joined lines that came from step sid."""
        return [i + 1 for i, o in enumerate(self.origins) if o and o[0] == sid]

    def to_dict(self):
        return {"kind": self.kind, "titles": self.titles, "origins": self.origins}

    @classmethod
    def from_dict(cls, d):
        return cls(d["origins"], d.get("titles"), d.get("kind", ""))

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


def locate_check(check, lm, script=None):
    """Read a check's verdict (the whole JSON --check-result prints, or its "check" part) against the line map.

    Returns locate()'s fields plus outcome, error, source, runner, definite (the check says the script itself
    crashed: outcome "failed") and, when the joined script is given, source_matches (the check's source line
    is that line of the script, a guard against checking a different file than the map is for)."""
    c = check.get("check", check) if isinstance(check, dict) else {}
    out = lm.locate(c.get("line") or 0) if c.get("line") else dict(lm.locate(0), part=None)
    out.update(outcome=c.get("outcome"), error=c.get("error", ""), source=c.get("source", ""),
               runner=c.get("runner", ""), definite=c.get("outcome") == "failed")
    if script is not None and c.get("line"):
        lines = script.split("\n")
        src = lines[c["line"] - 1].strip() if 0 < c["line"] <= len(lines) else ""
        out["source_matches"] = bool(src) and (src == out["source"].strip() or
                                               (out["source"].endswith("…") and src.startswith(out["source"][:-1])))
    if not out["definite"]:
        out["repair"] = None  # only a definite crash gets a step repair
    return out
