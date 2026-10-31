"""The Blender versions the worker's scripts are checked in, and where they live on the Studio.

Always the app's own binary, never a symlink to it (Blender crashes when started from one).
"""
from __future__ import annotations

import os

# Newest first: 5.2.2 is the main number in the plan's eval, 5.0.1 the oldest version the contract allows.
VERSIONS = {
    "5.2.2": "/Applications/Blender 3.app/Contents/MacOS/Blender",
    "5.0.1": "/Applications/Blender.app/Contents/MacOS/Blender",
}


def parse_overrides(items):
    """["5.2.2=/path/Blender", ...] (from --blender) on top of VERSIONS."""
    out = dict(VERSIONS)
    for it in items or []:
        v, sep, path = it.partition("=")
        if not sep or not v or not path:
            raise ValueError(f"--blender wants VERSION=PATH, not {it!r}")
        out[v.strip()] = path.strip()
    return out


def pick(versions, wanted=None):
    """The (version, path) pairs to run, in VERSIONS order; wanted is "5.2.2,5.0.1" or a list."""
    if isinstance(wanted, str):
        wanted = [w.strip() for w in wanted.split(",") if w.strip()]
    names = list(wanted) if wanted else list(versions)
    missing = [w for w in names if w not in versions]
    if missing:
        raise ValueError(f"no path for Blender {', '.join(missing)} (add --blender VERSION=PATH)")
    return [(w, versions[w]) for w in names]


def check_path(path):
    """A reason the path can't be used, or ""."""
    if not os.path.isfile(path):
        return f"{path} isn't there"
    if os.path.islink(path):
        return f"{path} is a symlink; Blender crashes when started from one, give the app's own binary"
    if not os.access(path, os.X_OK):
        return f"{path} isn't executable"
    return ""
