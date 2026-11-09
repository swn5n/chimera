"""What of a files piece no check here read, and the parse checks for the other languages this computer can read
(results/DATAGEN-SMOKE.md, "Second smoke run": the audit's unverified-languages cause and its skeptic's
extension-only variant).

    unchecked_code(text, parse=gate.get("parse"))       # [(path, language)]: own code files no check read and passed
    build_drop(meta, text, parse=gate.get("parse"))      # "unchecked_code" or None
    LocalParsers(cache, work).check("Go", body, "x.go")  # {"ok", "error", "line"} or {"skipped": why}

Why: smoke2's coding-0015-05 round 1 wrote PowerShell only (s1-s3, X54 weak, X74 and X17 bad). No .ps1 parser, no .py
file (so no compile and no import run), tests none:no_python, and code has no judge: all three were kept on the
validator's form check, the seams and a symbols check that takes any word of a non-Python body. X74 and X17 end inside
an unterminated double-quoted string (three backtick-quote escapes each swallow a closing quote: a lexer's reading and
ours, not pwsh's, which this computer doesn't have).

The build filter (build_drop): a files example the build marks unverified (meta["unverified"]: nothing ran on it) is
dropped as "unchecked_code" when one of the piece's own code files is in a language no check read and passed. The
language is the File: path's extension alone (language), as code_gate.parse_file reads a file: Python counts as
checked (compiled; tests or the import run where there are any), JSON, TOML, YAML and JavaScript count when
parse_file passed them, and Go, shell, Ruby, Swift and XML when the local parsers did (they run through parse_file
too, so both land in the gate's "parse"). Docs, configs, data and markup (md, txt, csv, env, ini, html, css, ...)
never count: nothing could fail them. A file with no extension (Dockerfile, Makefile, bin/deploy) or one nothing here
knows (go.mod, .proto, .jsonc) is no fact either way, and the fence's language is never read, so what counts as
unchecked is exactly what parse_file could have parsed (the analyst's fence fallback made bin/deploy fenced as bash
checked in the measurement and unchecked in the pipeline, and its Dockerfile and Makefile names would have dropped
about 43 night steps that are otherwise JavaScript, Go or shell).

Measured on both runs' records (no model calls): of the 56 files candidates that passed every other check (24 in the
first run, 32 in the second) it flags 6: smoke2's three kept PowerShell pieces (X54, X74, X17) and s1's alternate
(cand 1: it reads DATA_TYPE_NAME, which the OLEDB Columns schema table doesn't have, so no column is ever a date), and
the first run's config.lua (a 9-line return table as the plan wrote it) and queries.sql (five plain SELECTs), which
look right: they are its cost. Graded: 2 of the 4 bad files examples (the other two, X80 and X32, are Python), 1
of the 8 weak (X54, whose own faults no parser sees: it goes only because nothing checked it), 0 of the 5 ok, and
never a python-script example or a Python file (0 of the 51 passing python-script candidates). The skeptic's
rebuild of smoke2 with the filter kept 44 of 47, and valid lost its files mode (those three were its only files
examples).

LocalParsers: the parsers found here that only parse, each run through pysandbox.run_tool (the script profile, which
lets only that program start, the watchdog, a copy in a fresh run folder, 10 s) and cached like node --check:
- Go: gofmt -e (go/parser: syntax only, so an unused import or an unknown name passes);
- shell: bash -n, zsh -n for a zsh script (#! zsh, or .zsh), and /bin/bash --posix -n for #!/bin/sh: that is what
  this Mac's /bin/sh runs (bash in POSIX mode), dash -n refuses bash arrays and `function f {`, which run under
  #!/bin/sh here, and /bin/sh itself can't start in the sandbox (its exec of /bin/bash is denied). bash 4 grammar
  (|&, ;;&, ;&, coproc), which the system bash 3.2 can't read, and a #! line for another program are skipped;
- Ruby: ruby --disable-gems -c (rubygems' rbconfig runs uname, which the sandbox refuses; the system Ruby is 2.6,
  so Ruby 3 syntax, _RUBY_NEW, is skipped, never failed);
- XML (.xml, .plist, .svg, .csproj): xmllint --noout --nonet;
- Swift: swift-frontend -frontend -parse (no type checks; it starts nothing else).
Each gives {"ok", "error", "line"}, or {"skipped": why} for a run that says nothing: an error, a timeout, an exit with
no error line of the tool's own shape (_ERROR_LINE), no such tool here. Only a verdict is cached. On 287 fenced bash,
sh, zsh, Go, Ruby, Swift and XML blocks of the helper's stored gpt-oss:120b and qwen3 answers they failed 12, all
read: 8 go.mod files fenced as go (files mode reads them by path and parses no go.mod), 2 shell transcripts with
prompts and <placeholders>, 1 multi-root XML fragment and 1 real XML error ("--" inside a comment of a Tableau .twb).
This module's parsers fail the same 12 (and skip one gpt-oss block fenced as bash that starts #!/usr/bin/env node).
So in files mode about 0 false alarms and about 0 catches: what they do is keep those languages from being dropped.
No Go, shell, Ruby, Swift or XML file appears in either smoke run, so they change no stored candidate.

Not here: pwsh (PowerShell), shellcheck, lua/luac, php, rustc, dotnet, kotlinc, tsc or deno (TypeScript); installing
any of them is the user's call. C and C++ through Xcode's toolchain clang (-fintegrated-cc1 -fsyntax-only -isysroot,
"file not found" as a skip: 7 ok, 3 skipped, 0 failed on the corpus's 10 blocks, about 29 night steps) is the
skeptic's option, not built.
"""
from __future__ import annotations

import os
import re
import shutil

from contract import validate as cv
from datagen import pysandbox
from datagen.common import key_of

# extension -> language. A code language is one a parser could fail; MARKUP_EXT is what nothing can fail.
CODE_EXT = {"py": "Python", "pyw": "Python", "pyi": "Python",
            "js": "JavaScript", "mjs": "JavaScript", "cjs": "JavaScript", "jsx": "JSX", "ts": "TypeScript",
            "tsx": "TypeScript", "go": "Go", "rs": "Rust", "lua": "Lua", "php": "PHP", "cs": "C#", "csx": "C#",
            "fs": "F#", "vb": "VB.NET", "c": "C", "h": "C", "cpp": "C++", "cc": "C++", "cxx": "C++", "hpp": "C++",
            "hh": "C++", "m": "Objective-C", "mm": "Objective-C", "java": "Java", "kt": "Kotlin", "kts": "Kotlin",
            "scala": "Scala", "swift": "Swift", "rb": "Ruby", "sh": "Shell", "bash": "Shell", "zsh": "Shell",
            "ps1": "PowerShell", "psm1": "PowerShell", "psd1": "PowerShell", "bat": "Batch", "cmd": "Batch",
            "sql": "SQL", "r": "R", "pl": "Perl", "pm": "Perl", "dart": "Dart", "ex": "Elixir", "exs": "Elixir",
            "erl": "Erlang", "hs": "Haskell", "clj": "Clojure", "groovy": "Groovy", "gradle": "Groovy",
            "vue": "Vue", "svelte": "Svelte", "zig": "Zig", "nim": "Nim", "jl": "Julia", "vbs": "VBScript",
            "bas": "VBA", "gs": "Apps Script", "tf": "Terraform", "hcl": "Terraform", "sol": "Solidity",
            "json": "JSON", "ipynb": "JSON", "toml": "TOML", "yaml": "YAML", "yml": "YAML", "xml": "XML",
            "plist": "XML", "csproj": "XML", "svg": "XML"}
MARKUP_EXT = frozenset(["md", "markdown", "txt", "rst", "csv", "tsv", "env", "ini", "cfg", "conf", "gitignore",
                        "dockerignore", "editorconfig", "html", "htm", "css", "scss", "sass", "less", "log", "example",
                        "sample", "lock", "properties", "service", "desktop", "nginx", "template", "tmpl", "j2",
                        "jinja", "hbs", "ejs"])
LOCAL = frozenset(["Go", "Shell", "Ruby", "Swift", "XML"])  # the languages LocalParsers reads
LOCAL_EXT = {ext: lang for ext, lang in CODE_EXT.items() if lang in LOCAL}  # what parse_file sends to LocalParsers

_SWIFT = "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/swift-frontend"
# Ruby 2.6 can't read these; a file that has them is skipped (never failed): endless defs, numbered parameters,
# pattern matching's `in` at a line's start, hash shorthand {x:, y:}.
_RUBY_NEW = re.compile(r"^\s*def\s+[\w?!]+(?:\([^)]*\))?\s*=\s|\b_[1-9]\b|"
                       r"^\s*in\s+[\[{A-Z\w]|[{,(]\s*\w+:\s*[,})]", re.M)
_BASH4 = re.compile(r"\|&|;;&|;&|^\s*coproc\b", re.M)  # bash 4 grammar the system bash (3.2) refuses
_SHEBANG = re.compile(r"#!\s*(\S+)(?:\s+(\S+))?")
_ERROR_LINE = {
    "Go": re.compile(r"^wm_check\.go:(\d+):\d+: (.+)$", re.M),
    "Shell": re.compile(r"^(?:wm_check\.\w+|bash|zsh|\S+):\s?(?:line )?(\d+): (.+)$", re.M),
    "Ruby": re.compile(r"^wm_check\.rb:(\d+): (.+)$", re.M),
    "XML": re.compile(r"^wm_check\.xml:(\d+): (.+)$", re.M),
    "Swift": re.compile(r"^wm_check\.swift:(\d+):\d+: error: (.+)$", re.M),
}


def language(path) -> str | None:
    """The language of a file by its File: path's extension alone, as code_gate.parse_file reads it: a CODE_EXT name,
    "" for markup, docs, configs and data nothing could fail (and a dotfile such as .gitignore or .env), None for no
    extension (Dockerfile, Makefile, bin/deploy) or one nothing here knows (go.mod, .proto): no fact either way."""
    base = os.path.basename(path or "")
    if base.startswith(".") and base.count(".") == 1:
        return ""
    ext = base.rsplit(".", 1)[-1].lower() if "." in base.lstrip(".") else ""
    if ext in CODE_EXT:
        return CODE_EXT[ext]
    return "" if ext in MARKUP_EXT else None


def own_files(text):
    """[(path, fence language, body, part)] of a files piece's own File: blocks, as the contract's validator reads
    them; [] when it can't read the piece."""
    try:
        files = cv.validate_piece(text, "files", reject_cut=False, max_tokens=None).files
    except Exception:  # noqa: BLE001 - a reply the validator can't read writes nothing
        return []
    return [(f.path, f.lang, f.body, f.part) for f in files]


def _norm(path):
    try:
        return pysandbox.safe_path(path)
    except ValueError:
        return path


def unchecked_code(text, parse=None, local=None) -> list:
    """[(path, language)] of the piece's own code files no check read and passed, by their extension (language):
    not Python, and neither in parse (code_gate's gate["parse"]: every parse_file result, the local parsers' too,
    {"path", "kind", "ok"} or {"path", "kind", "skipped"}) nor in local ({path: LocalParsers result}, for a caller
    that ran check_piece itself) with a pass. A skipped parse (a template, JSX, bash 4 grammar) read nothing."""
    passed = {_norm(p["path"]) for p in parse or () if p.get("ok") and not p.get("skipped") and p.get("path")}
    passed |= {_norm(k) for k, v in (local or {}).items() if v.get("ok") and not v.get("skipped")}
    out, seen = [], set()
    for path, _lang, _body, _part in own_files(text):
        sp = _norm(path)
        if sp in seen:
            continue
        seen.add(sp)
        lg = language(path)
        if lg and lg != "Python" and sp not in passed:
            out.append((path, lg))
    return out


def build_drop(meta, text, parse=None, local=None):
    """The build filter: "unchecked_code" for an unverified files example (meta["mode"] "files", meta["unverified"]:
    nothing ran on it) with a code file no check read and passed (unchecked_code), else None. parse: the kept
    candidate's stored gate["parse"] (None for a record without one: nothing was parsed)."""
    if meta.get("mode") != "files" or not meta.get("unverified"):
        return None
    return "unchecked_code" if unchecked_code(text, parse, local) else None


# ---------------------------------------------------------------- the local parsers

def _which(path_or_name):
    p = path_or_name if os.path.isabs(path_or_name) else shutil.which(path_or_name)
    return p if p and os.path.exists(p) else None


def _shell_for(body, path=""):
    """Which shell reads a script: "zsh" (#! zsh, or a .zsh file), "sh" (#!/bin/sh or env sh: bash --posix), "bash"
    (no #! line, bash, dash, ksh), or None for a #! line naming another program (python, fish): skipped."""
    first = (body or "").lstrip("﻿").split("\n", 1)[0]
    m = _SHEBANG.match(first)
    if m:
        prog = os.path.basename(m.group(1))
        if prog == "env":
            prog = os.path.basename(m.group(2) or "")
        if prog == "zsh":
            return "zsh"
        if prog == "sh":
            return "sh"
        if prog not in ("bash", "dash", "ksh"):
            return None
        return "bash"
    return "zsh" if (path or "").lower().endswith(".zsh") else "bash"


def _stamp(program):
    """What tells one build of a program from another for the cache: its real path, size and modification time."""
    real = os.path.realpath(program)
    try:
        st = os.stat(real)
        return [real, st.st_size, st.st_mtime_ns]
    except OSError:
        return [real]


class LocalParsers:
    """The parsers this computer has (found once), run sandboxed and cached like code_gate's node_check. cache: a
    common.Cache (None: nothing cached); work: where run folders go."""

    def __init__(self, cache=None, work=None):
        self.cache, self.work = cache, work
        self.tools = {"Go": _which("gofmt"), "bash": _which("/bin/bash"), "zsh": _which("/bin/zsh"),
                      "Ruby": _which("/usr/bin/ruby"), "XML": _which("/usr/bin/xmllint"), "Swift": _which(_SWIFT)}

    def has(self, lang) -> bool:
        return bool(self.tools.get("bash" if lang == "Shell" else lang))

    def check(self, lang, body, path="") -> dict:
        """The parse of body (a whole file, as merged) in lang: {"ok", "error" (the tool's message, at most 300
        characters), "line"} or {"skipped": why} (cached only when it is a verdict)."""
        body = body or ""
        if lang == "Shell":
            sh = _shell_for(body, path)
            if sh is None:
                return {"skipped": "a #! line for another program"}
            if sh != "zsh" and _BASH4.search(body):
                return {"skipped": "bash 4 syntax, which the system bash 3.2 can't read"}
            program = self.tools["zsh" if sh == "zsh" else "bash"]
            ext, args = "sh", (["--posix", "-n", "wm_check.sh"] if sh == "sh" else ["-n", "wm_check.sh"])
        elif lang == "Go":
            program, ext, args = self.tools["Go"], "go", ["-e", "-l", "wm_check.go"]
        elif lang == "Ruby":
            if _RUBY_NEW.search(body):
                return {"skipped": "Ruby 3 syntax, which ruby 2.6 can't read"}
            program, ext, args = self.tools["Ruby"], "rb", ["--disable-gems", "-c", "wm_check.rb"]
        elif lang == "XML":
            program, ext, args = self.tools["XML"], "xml", ["--noout", "--nonet", "wm_check.xml"]
        elif lang == "Swift":
            program, ext, args = self.tools["Swift"], "swift", ["-frontend", "-parse", "wm_check.swift"]
        else:
            return {"skipped": f"no parser for {lang} here"}
        if not program:
            return {"skipped": f"no parser for {lang} here"}
        key = key_of("local-parse", lang, ext, args, body, _stamp(program))
        if self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                return dict(hit, cached=True)
        run = pysandbox.run_tool({"wm_check." + ext: body}, program, args, work=self.work)
        out = run.get("output") or ""
        if run.get("error") or run.get("timed_out"):
            return {"skipped": run.get("error") or "timed out"}
        if run.get("exit") == 0:
            got = {"ok": True, "error": None, "line": 0}
        else:
            m = _ERROR_LINE[lang].search(out)
            if not m:
                return {"skipped": f"exit {run.get('exit')} with no error line"}
            got = {"ok": False, "error": m.group(2).strip()[:300], "line": int(m.group(1))}
        if self.cache is not None:
            self.cache.put(key, got)
        return dict(got, cached=False)

    def check_piece(self, text) -> dict:
        """{path: result, with "language"} for each of the piece's own files in a language a parser here reads, its
        block's body alone (the gate parses the file as merged: this is for measuring stored pieces)."""
        out = {}
        for path, _lang, body, _part in own_files(text):
            lg = language(path)
            if lg in LOCAL and self.has(lg) and path not in out:
                out[path] = dict(self.check(lg, body + "\n", path), language=lg)
        return out
