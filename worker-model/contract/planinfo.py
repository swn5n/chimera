"""What the contract reads off a cleaned plan: positional step names, dependencies, users, and each step's mode.

Chimera names steps by position, s1 to s8 (cleanPlan allows 8), so build_s2 is always valid Python; the
planner's own ids only link depends_on to steps. Modes (the plan's "Modes, chosen by Chimera from the content"):
- blender: a step of kind blender, or a code step in a plan whose goal, summary or instructions mention
  Blender, bpy or one of Blender's own names (bmesh, Geometry Nodes, a .blend, EEVEE, …) (the fallback
  planner mislabels these);
- python-script: other code steps in a Python plan that names no file paths;
- files: code plans that name paths, or other languages;
- section: writing, research and general steps.
The word lists below are this prototype's reading of "names file paths" and "other languages"; the eval
measures them, and the Go version copies whatever is kept (RE2 has no lookarounds, so Go needs the
boundary and exception checks written out).
"""
from __future__ import annotations

import re
from typing import Optional

# Blender's own module and feature names: a plan that never says "Blender" can still be one ("a Geometry Nodes
# setup from Python", "for every .blend in a folder"). EEVEE only in capitals (Eevee is a Pokémon).
_BLENDER = re.compile(r"\b(?:blender|bpy|bmesh|mathutils|geometry nodes|principled bsdf|pointiness)\b|\.blend\b"
                      r"|\b(?-i:EEVEE)\b", re.I)
# Source files only: a Python script that reads data.csv or writes report.json is still one script.
CODE_EXTS = ("py|pyi|pyw|js|mjs|cjs|ts|tsx|jsx|go|rs|java|kt|kts|swift|cpp|cc|cxx|hpp|cs|rb|php|html|htm|css|scss|"
             "sass|less|vue|svelte|lua|dart|sh|bash|zsh|ps1|toml|gradle|sql")
PATH_RE = re.compile(r"(?<![\w/.-])(?:[\w.-]+/)*[\w-]+\.(?:%s)\b|\b(?:Dockerfile|Makefile|package\.json|go\.mod|"
                     r"Cargo\.toml|requirements\.txt|pyproject\.toml)\b" % CODE_EXTS)

# "Other languages", in three kinds (Oct 29 review: "angular velocity", "react to chat messages", "rust patches",
# "a swift Python solver" and "an HTML report" made Python plans files plans, while "my Express API" and a Fabric
# mod's NullPointerException, which name no language, stayed Python):
# 1. names that are seldom anything else, in any case, plus tools and frameworks that imply a language;
_LANG_NAMES = re.compile(
    r"(?<![\w.])(?:javascript|typescript|node\.?js|deno|golang|kotlin|haskell|perl|powershell|objective-c|php|scala|"
    r"lua|java|jquery|next\.js|nuxt|vue\.?js|react\.?js|reactjs|react native|angularjs|sveltekit|swiftui|spring boot|"
    r"gradle|npm|webpack|html5|bash script|shell script|zsh script|minecraft mod|fabric mod|forge mod|neoforge|"
    r"spigot|bukkit|nullpointerexception|chrome extension|browser extension|firefox add-on|userscript|android app|"
    r"xcode|c\+\+|c#|csharp|dotnet)(?![\w+#])|(?-i:\.NET)\b", re.I)  # ".NET", "ASP.NET"
# 2. names that are also English words, capitalised and next to a programming word: "in Rust", "a Swift
#    package", "React component", "my Express API" (not "rust patches", "react to", "angular velocity");
_TECH_NOUNS = (r"program|programs|code|codebase|app|apps|application|project|crate|crates|library|module|modules|"
               r"package|packages|gem|gems|component|components|hook|hooks|server|service|backend|frontend|front end|"
               r"front-end|API|CLI|tool|binary|script|scripts|compiler|toolchain|page|pages|site|website|template|"
               r"templates|UI|widget|widgets|route|routes|middleware|plugin|extension|test|tests|on Rails|Native|"
               r"router|controller|file|files|function|functions|struct|structs|trait|traits|macro|macros|form|forms")
_BEFORE = r"(?:[Ii]n|[Uu]sing|[Ww]ritten in)"
_BEFORE_WITH = r"(?:[Ii]n|[Uu]sing|[Ww]ritten in|[Ww]ith)"
_WORD_NAMES = r"Rust|Swift|Ruby|Rails|Dart|Flutter|Elixir|React|Angular|Vue|Svelte|Electron|Jest|Node|Express"
_WORD_LANGS = re.compile(
    r"\b(?:%s (?:%s)|%s Express|(?:%s)\s+(?:%s))\b(?!-)"  # not "with Express shipping"
    % (_BEFORE_WITH, _WORD_NAMES.replace("|Express", ""), _BEFORE, _WORD_NAMES, _TECH_NOUNS))
#    Go keeps its narrower rule: "Go file by file" and "Go page by page" are instructions, not Go code;
_GO = re.compile(r"\b(?:Go\s+(?:program|module|code|package|service|server|binary|CLI|tool|app)s?|%s Go)\b(?!-)"
                 % _BEFORE)
# 3. HTML and CSS: paired ("HTML/CSS", "HTML and JavaScript"), or "in HTML", or before a web word, unless the
#    sentence says a program reads or writes it ("scrape HTML pages", "generates an HTML page", "an HTML report").
_WEB_PAIR = re.compile(r"\b(?:HTML|CSS)\s*(?:/|and|&|\+|,)\s*(?:HTML|CSS|JS|JavaScript)\b")
_WEB = re.compile(r"\b(?:%s (?:HTML|CSS)|(?:HTML|CSS)\s+(?:page|pages|file|files|site|website|"
                  r"frontend|front end|front-end|UI|form|forms|template|templates|markup|stylesheet|stylesheets|"
                  r"styles|selector|selectors|grid|layout|animation|animations))\b" % _BEFORE)
_WEB_DATA = re.compile(r"(?i)\b(?:scrap\w*|pars\w*|crawl\w*|fetch\w*|download\w*|extract\w*|generat\w*|render\w*|"
                       r"export\w*|outputs?|convert\w*|sav(?:e|es|ing)|prints?|printing|emails?|reads?|reading)\b")


def other_language(text) -> Optional[str]:
    """The words that make text name a language other than Python (or an implied one), else None."""
    for rx in (_LANG_NAMES, _WORD_LANGS, _GO, _WEB_PAIR):
        m = rx.search(text)
        if m:
            return m.group(0)
    for m in _WEB.finditer(text):
        start = max(text.rfind(c, 0, m.start()) for c in ".!?\n") + 1  # the sentence so far
        if not _WEB_DATA.search(text[start:m.start()]):
            return m.group(0)
    return None


def names(plan):
    """[s1, s2, …]: each step's positional name."""
    return ["s%d" % (i + 1) for i in range(len(plan["steps"]))]


def index_of(plan):
    """plan id -> index of the first step with that id."""
    out = {}
    for i, s in enumerate(plan["steps"]):
        out.setdefault(s["id"], i)
    return out


def dep_indexes(plan, i):
    """Indexes of the steps step i depends on: earlier steps only (cleanPlan), deduplicated, in plan order."""
    idx = index_of(plan)
    return sorted({idx[d] for d in plan["steps"][i].get("depends_on") or [] if d in idx and idx[d] < i})


def dep_names(plan, i):
    return ["s%d" % (j + 1) for j in dep_indexes(plan, i)]


def user_names(plan, i):
    """The steps that use step i's piece."""
    return ["s%d" % (j + 1) for j in range(len(plan["steps"])) if i in dep_indexes(plan, j)]


def plan_text(plan, goal=""):
    """Everything mode selection reads: the goal, title, summary and every step's title and instructions."""
    parts = [goal or "", plan.get("title") or "", plan.get("summary") or ""]
    for s in plan["steps"]:
        parts += [s.get("title") or "", s.get("instructions") or ""]
    return "\n".join(parts)


def code_mode(plan, goal=""):
    """The mode a code step of this plan gets: blender, python-script or files."""
    text = plan_text(plan, goal)
    if _BLENDER.search(text):
        return "blender"
    if PATH_RE.search(text) or other_language(text):
        return "files"
    return "python-script"


def step_mode(plan, i, goal=""):
    """The contract mode of step i."""
    kind = plan["steps"][i].get("kind")
    if kind == "blender":
        return "blender"
    if kind == "code":
        return code_mode(plan, goal)
    return "section"


def one_line(s):
    """Whitespace squashed to single spaces (for the outline's one-line entries)."""
    return " ".join((s or "").split())
