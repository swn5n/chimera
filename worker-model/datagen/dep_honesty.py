"""A piece written with a dependency that failed must not claim that dependency's output (results/DATAGEN-SMOKE.md,
"Second smoke run": the failed-dependency cause, and its skeptic's line excuse).

    r = check(messages, text)   # {"ok", "reasons", "tell", "claims": [(sid, item)], "missing": [sid], "unlisted"}

Chimera's request says, under the header of a dependency that failed, "(that step failed; assume what you need and
list it under assumed)": the piece got nothing from that step. Its handoff's uses line is "what you took from which
step", so a uses item that claims the failed step's output is a claim on something it never had, and an assumed line
of none lists nothing where the request asked for a list. Nothing else compares them: the validator's
uses_not_dependency and uses_undeclared fire only for steps outside depends_on, and a failed one stays in it; Go's
uses_unmatched seam (usesChunks) skips a failed step's chunk on purpose; the scene judge is asked only what exists,
and the prose judge is told not to grade the handoff. So gpt-oss's habit of writing uses as if the failed step had
delivered ("rows (from load_csv / s2)", "s1 (license_prices)", the failed step's title, the names it was to provide)
passed every check: 86 of its 131 first tries with a failed dependency and a readable handoff in the two smoke runs
did it (90 of 138 with repairs).

Facts only, from what Chimera sent and what the piece wrote, no model and no run: which dependencies failed is in
messages (Chimera's stored request for that candidate, step["request"]'s or a repair's own, never the teacher's
copy), and so are the received ones' handoffs and pieces as the worker saw them; the handoff is read with the
contract's own parser. The uses line is split into items at commas and semicolons outside brackets; an item after
"sN:" in the same ;-group belongs to sN. An item claims a failed step sN when it names sN, holds sN's whole title or is
2 or more content words all in that title, or (with no step id of its own) names a code-like name
(contract.join.uses_names, Go's port) that no received dependency's handoff or piece holds, or when nothing at all was
received. It is no claim when the item itself is marked (failed, missing, absent, unavailable, not supplied, stand-in,
placeholder, assumed, guessed, fallback, default, none, ...), when its "sN:" lead's ;-group is, or when any ;-group of
the uses line names sN and is marked ("a, b from s1 (assumed since s1 failed)", "scene, collection; s1 and s2 failed so
stand-ins were made"): without that last excuse 6 honest handoffs, of qwen3.8's 22 written with a failed dependency,
were flagged; with it none is, and no real claim is lost. The only words read are the marks on the piece's own uses
line; it never fires without a failed dependency (0 of the 562 candidates of both runs that had none).

Measured on both smoke runs' 737 candidates and repairs (175 written with a failed dependency, hand-labelled: 95
claims, 65 honest, 15 with no handoff): 91 flagged, all claims, 4 claims missed (two excused by an "(assumed)" in the
item itself, as the weak X70; a CSV named by a word its step's title lacks; "assumed helpers" in brackets). Of the 42
that passed every other check, 31 flagged, each a real claim (1 missed). Of the audit's grades it flags 13 of the 15
bad written with a failed dependency (X10, X14, X32, X36, X44, X45, X53, X55, X56, X58, X59, X69, X76; X20 and X30 are
bad for other reasons with honest handoffs), 3 of the 4 weak (X12, X67, X75; the grader named the same claim) and none
of the 16 ok, none of which had a failed dependency. The eval's reference handoffs for failed dependencies pass. The
analyst's lenient variant (lenient=True: an admission in the assumed line excuses the item) misses X56 and X67, so the
gates use the strict one. On the built examples (the stored request and the target) it drops 7 of the second run's 47
(5 bad, 2 weak) and 13 of the first run's 63 (8 bad, 1 weak, 4 ungraded that each claim a failed step's output).

reasons: "dep_claimed:<sid>" (a uses item claims sid's output), "dep_unlisted" (assumed is none while a dependency
failed). tell: one teacher-only line per group of failed steps the same items were claimed from (one for them all past
CLAIMED_LINES), and one for an assumed line of none, each quoting the model's own items (QUOTE_CHARS each, QUOTES_KEEP
at most) and at most hints.FAILURE_CHARS long. A claimed item is to be written step first and marked, "sN: item
(failed)", or left out, and assumed to start "sN failed:". Until contract question 4 (Nov 5) Go's usesChunks read each
step id as the start of that step's part, so "table from s1, lamp from s2 (failed)" put lamp in s1's part (a false
uses_unmatched in a joined Blender gate); since then each item goes to the step id after it, so that form reads right
too, and the asked-for "s2: lamp (failed)" is still s2's part, which a failed step's skip leaves alone; "none (s2
failed)" is the validator's handoff_wordy.
Through the binary every form the lines ask for passes the validator with no uses_unmatched, uses_undeclared,
uses_not_dependency, handoff_wordy or handoff_long, and the join with no uses seam, in every mode
(tests/test_datagen_dep_honesty.py); and each of the 91 flagged candidates of the smoke runs, rewritten both ways its
lines ask (marked, dropped), passes check(), gains no such issue or seam, and echoes nothing of the notes or its
lines. TELL_FORMS is the lines' fixed wording (ours, never a target), for hints.echoed_note; no stored reply of either
run holds a run of it.

After the integration check (Nov 4) three honest forms no stored try has are no longer blamed: an item marked "not
needed", "not required", "not used", "unused" or "unneeded" ("s1 (not needed)"), an assumed line that starts with none
but names a failed step or says it failed ("None of s1's output arrived, so ..."; a bare "none" still counts), and a
lone dash (any of -, – or —) as uses or assumed. Over the 737 stored tries nothing changes.

A stray "(assumed)" on an item games the check, as X70's does, and the title rule could blame an item that echoes a
generic title a received step shares; the name rule could blame a failed step for a name from an undeclared earlier
step (17 of 412 code-like items, in 5 of 316 candidates, where no dependency failed).
"""
from __future__ import annotations

import re

from contract import join as cj
from contract import validate as cv

FAILED_LINE = "(that step failed; assume what you need and list it under assumed)"  # Go's contractUserDepFailed
_DEP_HEAD = re.compile(r'^From (s[1-9]\d?), "(.*)" \(you use it\):$', re.M)  # Go's contractUserDepHead
# What Chimera puts after the dependencies: a repair's crash (contractRepair) and round 2's part (contractRound2Part)
_TAILS = ("\n\nYour piece crashed when Chimera ran", "\n\nLast round's result for your part:")
_STEP = re.compile(r"\bs([1-9]\d?)\b", re.I)
# What a uses item may say to show it didn't get the thing: the item's own words only
_MARK = re.compile(r"\b(?:fail\w*|missing|absent|unavailable|not\s+(?:available|supplied|provided|given|received|"
                   r"there|needed|required|used)|unused|unneeded|stand[\s-]?ins?|placeholders?|assum\w*|guess\w*|"
                   r"fallbacks?|defaults?|inferred|hypothetical|none|nothing|no\s+output)\b", re.I)
_NONE = re.compile(r"^\s*(?:(?:none|nothing|n/?a)\b|[-–—]\s*$)", re.I)
_STOP = frozenset(["a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "with", "from", "by", "s", "step",
                   "its", "it", "data", "output", "outputs", "result", "results"])
# The lenient variant's admission in the assumed line (failure words only)
_ADMIT = re.compile(r"\b(?:fail\w*|missing|absent|unavailable|not\s+(?:available|supplied|provided|given|received|"
                    r"there)|stand[\s-]?ins?|placeholders?)\b", re.I)

# The tell lines, teacher-only: {steps} "s2" or "s2 and s3", {quotes} the model's items, {name} the first of them
# without where it says it came from, {it} "it" or "them", {first} the step that item was claimed from.
CLAIMED_TELL = ("{steps} failed and gave your piece nothing, yet your uses line lists {quotes}. Write {it} as "
                "{first}: {name} (failed) or drop {it}; in assumed, write \"{steps} failed:\" and what you used "
                "instead.")
UNLISTED_TELL = ("{steps} failed, yet your assumed line is none: write \"{steps} failed:\" there and what you "
                 "assumed or made in its place.")
# Their fixed wording, for hints.echoed_note: the runs of 5 words or more between the parts that are the model's
# (steps, quotes, name), with {it} as each of its words.
TELL_FORMS = tuple(dict.fromkeys(
    p.strip(" :;,.\"") for t in (CLAIMED_TELL, UNLISTED_TELL) for it in ("it", "them")
    for p in re.split(r"\{(?:steps|quotes|first|name)\}", t.replace("{it}", it)) if len(re.findall(r"\w+", p)) >= 5))
QUOTE_CHARS = 40  # of each item quoted (prose_gate's)
QUOTES_KEEP = 2
NAME_CHARS = 32  # of the item in the example
LINE_CHARS = 240  # hints.FAILURE_CHARS: a longer line would be cut where the next try reads it
CLAIMED_LINES = 2  # lines for claims at most: a smoke section claimed four failed steps' files


def _norm(s):
    return " ".join(re.sub(r"[^0-9a-z]+", " ", (s or "").lower()).split())


def _words(s):
    return {w for w in _norm(s).split() if w not in _STOP and not re.fullmatch(r"s\d+", w)}


def deps_of(messages):
    """{sid: {"title", "failed", "text"}} for every dependency block of the request's user message (the first one),
    text being what the worker was shown of it (its handoff lines and its piece, as Chimera cut it). A repair's crash
    and round 2's part come after the dependencies, so the message is read only up to them."""
    user = next((m.get("content") or "" for m in messages or () if m.get("role") == "user"), "")
    for tail in _TAILS:
        if tail in user:
            user = user[:user.index(tail)]
    heads = list(_DEP_HEAD.finditer(user))
    out = {}
    for k, m in enumerate(heads):
        body = user[m.end():heads[k + 1].start() if k + 1 < len(heads) else len(user)]
        out[m.group(1)] = {"title": m.group(2), "failed": body.lstrip("\n").startswith(FAILED_LINE), "text": body}
    return out


def _split(s, sep):
    """s split at sep outside brackets."""
    parts, depth, cur = [], 0, ""
    for ch in s:
        depth += ch in "([{"
        depth -= ch in ")]}" and depth > 0
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def _items(uses):
    """[(item, lead, group)]: the uses line's items, split at ; and , outside brackets, each with the step its ;-group
    starts with ("s1: a, b; s2: c", "from s1 - a"), if any, and that group."""
    out = []
    for g in _split(uses or "", ";"):
        lead = re.match(r"\s*(?:from\s+)?(s[1-9]\d?)\s*[:\-–—]", g, re.I)
        out += [(p.strip(), lead.group(1).lower() if lead else None, g.strip()) for p in _split(g, ",") if p.strip()]
    return out


def _groups(uses):
    """The uses line's ;-groups (outside brackets), once each."""
    return list(dict.fromkeys(g for _, _, g in _items(uses)))


def _names_in(names, text):
    return [n for n in names if all(re.search(r"\b%s\b" % re.escape(x), text, re.I) for x in n.split("."))]


def _title_hit(item, title):
    """The item names the step by its title: the whole title in it, or an item of 2+ content words all in the title."""
    it, ti = _norm(item), _norm(title)
    if ti and ti in it:
        return True
    w = _words(item)
    return len(w) >= 2 and w <= _words(title)


def _admitted(assumed, d, title, item):
    """The assumed line says d's output wasn't there: a clause of it names d (its id, its title, or a name of the item)
    and says failed, missing, stand-in, ... (the lenient variant only)."""
    for clause in re.split(r"[;.]\s+|\s+[–—-]\s+(?=\w)", assumed or ""):
        if not _ADMIT.search(clause):
            continue
        if re.search(r"\b%s\b" % d, clause, re.I) or _title_hit(clause, title) or _norm(title) in _norm(clause):
            return True
        if _names_in(cj.uses_names(item), clause) or (_words(item) and _words(item) <= _words(clause)):
            return True
    return False


def check(messages, text, lenient=False) -> dict:
    """Does text's handoff claim output of a dependency messages says failed, or list nothing under assumed? ok,
    reasons ("dep_claimed:<sid>" in sid order, then "dep_unlisted"), tell (the lines for the next try), claims
    [(sid, item)], missing (the failed dependencies, in the request's order), unlisted. A text with no handoff, or a
    request with no failed dependency, is ok: the validator judges a missing handoff."""
    deps = deps_of(messages)
    missing = [d for d, v in deps.items() if v["failed"]]
    res = {"ok": True, "reasons": [], "tell": [], "claims": [], "missing": missing, "unlisted": False}
    if not missing:
        return res
    h, _, _ = cv.parse_handoff(text or "")
    if h is None:
        return res
    got = [v for v in deps.values() if not v["failed"]]
    uses = (h.uses or "").strip()
    excused = {d for g in _groups(uses) if _MARK.search(g) for d in missing if re.search(r"\b%s\b" % d, g, re.I)}
    if uses and not _NONE.match(uses):
        for item, lead, group in _items(uses):
            ids = {"s" + m.group(1) for m in _STEP.finditer(item)} | ({lead} if lead else set())
            to = {d for d in missing if d in ids or _title_hit(item, deps[d]["title"])}
            if not to and not ids:
                names = cj.uses_names(item)
                if not got:  # nothing was received: whatever it says it took came from a failed step
                    to = set(missing)
                elif names and not any(_names_in(names, v["text"]) or _title_hit(item, v["title"]) for v in got):
                    to = set(missing)
            to -= excused
            if to and not _MARK.search(item) and not (lead and _MARK.search(group)):
                for d in sorted(to, key=_num):
                    if not (lenient and _admitted(h.assumed, d, deps[d]["title"], item)):
                        res["claims"].append((d, item))
    claimed = sorted({d for d, _ in res["claims"]}, key=_num)
    res["reasons"] = ["dep_claimed:" + d for d in claimed]
    by_items = {}  # the claimed items -> the failed steps they were claimed from
    for d in claimed:
        by_items.setdefault(tuple(dict.fromkeys(i for x, i in res["claims"] if x == d)), []).append(d)
    titles = {d: v["title"] for d, v in deps.items()}
    if len(by_items) > CLAIMED_LINES:  # one line for them all, so the next try's notes keep room for other faults
        res["tell"] = [claimed_line(claimed, list(dict.fromkeys(i for _, i in res["claims"])), res["claims"][0][0],
                                    titles)]
    else:
        res["tell"] = [claimed_line(ds, list(items), titles=titles) for items, ds in by_items.items()]
    assumed = (h.assumed or "").strip()
    if not assumed or (_NONE.match(assumed) and not _ADMIT.search(assumed) and
                       not any(re.search(r"\b%s\b" % d, assumed, re.I) for d in missing)):
        res["unlisted"] = True
        res["reasons"].append("dep_unlisted")
        res["tell"].append(unlisted_line(missing))
    res["ok"] = not res["reasons"]
    return res


def _num(sid):
    return int(sid[1:])


def _steps(ds):
    return ds[0] if len(ds) == 1 else ", ".join(ds[:-1]) + " and " + ds[-1]


def _quote(s, n):
    s = " ".join((s or "").split())
    return '"' + (s if len(s) <= n else s[:n - 1] + "…") + '"'


_ATTRIBUTION = re.compile(r"\s+(?:from|by|produced|made|created|provided|given|written)\b.*$", re.I | re.S)
_LEAD_STEP = re.compile(r"^(?:steps?\s+)?s[1-9]\d?\b(?:['’]s)?\s*[:\-–—→]?\s*", re.I)


def _example_name(item):
    """What of a claimed item the example writes after "sN: ", whole: the item before a bracketed aside, without what
    says where it came from ("from s1", "produced by step s1") or a step id it starts with ("rows (from load_csv /
    s2)": rows; 'ctx["objects"]["sofa"] from s2' keeps its subscripts); for an item that is only a step id before the
    aside, the aside's words ("s1 (license_prices)": license_prices); else "" (an item that is only "s1")."""
    for s in (re.split(r"(?:^|\s)[(\[{]", item, maxsplit=1)[0], re.sub(r"[()]", " ", item)):
        s = _LEAD_STEP.sub("", " ".join(_ATTRIBUTION.sub("", s).split())).strip(" :;,.-–—/")
        if s:
            return s
    return ""


def _words_cut(s, n=None):
    """s cut at a word's end to at most n characters (any, when None) and NAME_WORDS words, with no "…" (a model
    copies the example as it is); "" when its first word alone is longer: half a word would be copied as a name."""
    out = ""
    for tok in (s or "").split():
        more = (out + " " + tok) if out else tok
        if (n is not None and len(more) > n) or len(_WORD.findall(more)) > NAME_WORDS:
            break
        out = more
    return out.rstrip(" :;,.-–—/")


# (items quoted, characters of each), tried in turn for each example name until the line fits
_QUOTE_FITS = [(2, n) for n in (QUOTE_CHARS, 32, 24)] + [(1, n) for n in (QUOTE_CHARS, 32, 24, 16, 12)]
NAME_CUTS = (None, NAME_CHARS, 24, 16, 12)  # an example name too long for the line is cut to these, at a word's end
# Words of the example's name at most: "sN: <name> (failed)" copied into a reply would be an 8-word run of the tell
# line with 6 (echoed_note's extra refuses a reply that holds one, in every mode but a section's)
NAME_WORDS = 5
_WORD = re.compile(r"\w+", re.U)  # hints._WORD (check_overlap's words)


def claimed_line(ds, items, first=None, titles=None):
    """The line for the failed steps ds whose output the uses items claim, at most LINE_CHARS long: the items quoted
    (fewer and shorter until it fits), and the example, step first and marked, under first (the step it was claimed
    from; ds[0] when every one of ds had all the items claimed). The example's name is the first item's, whole;
    for an item that is only a step id ("uses: s1", 3 of the 108 lines of the smoke runs had "…" there), or one too
    long for the line, the failed step's title (titles: {sid: title}, Chimera's own words from the request's
    header), whole; then either cut at a word's end; never more than NAME_WORDS words, and never a "…": a model that
    copies the example would write "s1: … (failed)" into a target, which check() and the validator pass. On the
    smoke runs' 108 lines this changes those 3 alone ("s1: Draft outline and gather reference (failed)", s1's title
    cut at five words; the item's own name, cut at 32 characters, ended in "…" before)."""
    first = first or ds[0]
    title = (titles or {}).get(first) or ""
    whole = _example_name(items[0])
    whole_ones = [x for x in (whole, " ".join(title.split())) if x and len(_WORD.findall(x)) <= NAME_WORDS]
    names = list(dict.fromkeys(x for x in whole_ones + [_words_cut(x, m) for m in NAME_CUTS for x in (whole, title)]
                               if x))

    def line(k, n, name):
        quotes = ", ".join(_quote(i, n) for i in items[:k]) + (" and more" if len(items) > k else "")
        return CLAIMED_TELL.format(steps=_steps(ds), quotes=quotes, it="it" if len(items) == 1 else "them",
                                   first=first, name=name)

    for name in names:
        for k, n in _QUOTE_FITS:
            if k <= len(items) and len(line(k, n, name)) <= LINE_CHARS:
                return line(k, n, name)
    return line(1, 12, names[-1] if names else first)[:LINE_CHARS - 1] + "…"


def unlisted_line(missing):
    """The line for an assumed line of none while the steps missing failed."""
    return UNLISTED_TELL.format(steps=_steps(missing))
