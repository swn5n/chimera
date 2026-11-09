"""Geometry: what a Blender piece built against the places, depths and relations its own step gives in numbers (step
6b; results/DATAGEN-SMOKE.md, "Third smoke run", and DESIGN.md, "blender_gate.py").

    places = asked_places(plan, i)                          # [{"phrase", "kind", "point", "words", "quoted"}]
    place_states(places, probe)                             # per place: ("fits" | "fault" | "unmatched" | "floor", x)
    depth_states(asked_depths(plan, i), probe)              # flat_extrusion's
    relation_states(asked_relations(plan, i), probe, keys)  # nested's; keys: the run's stand_in_keys

A piece Chimera's check passes can still have built the wrong thing in a way the step says in numbers. The second
smoke run kept X27 (a sofa "centered at origin" whose box runs from z 0.4 to 1.2, its origin left outside it by a
transform applied after the move), X01 (an island, a fridge and a stove all lifted off the points their step gives)
and X39 (the third run's Y46: a "Pulse_Curve" the step extrudes by 0.08 m, left a flat path of 0 faces), all bad, and
X06 (a backplate "behind the logo" buried at z -0.01 inside the logo's z -0.15..0). probe is one version's direct
run record: its "geom" (blender_gate.GEOM_EPILOGUE's line: per object of a GEOMETRY type its exact world box from the
evaluated mesh, faces, vertices, curve settings, depsgraph instances, and the objects whose place moves) and its
"measure" (lights', cameras' and empties' locations, the factory's own). blender_gate.measured_check counts a fault
only when every version shows it, and only from a version that printed both lines.

The readers take the step's own instructions, clause by clause (blender_gate._CLAUSE), and claim little: only a thing
this step makes (blender_gate._made_elsewhere, the sizes' rule), named in quotes ('named "Sun_Lamp"', "name it
`Backplate`", a list item's "`Spot_A`:") or by the clause's telling words before the phrase (a parenthesis of words
only, "Key Light (Spot) at", is part of them), matched to the run's objects by exact name when quoted, else by the
most shared name words (at least one), never an animated or moving one:
- asked_places: a point (x, y, z) right after at, to, location, located, positioned, placed, moved or centred at, and
  "at (or centred at) the (world) origin"; not one after a target, rotation, colour, keyframe, scale or direction
  word, not a hedged one ("e.g.", "about", "near"), not where a row starts or ends ("starting at"), nothing in a
  clause that keyframes or animates. place_mismatch
  (alone): no matched object has its box centre, the middle of its bottom, or its own origin (when that lies inside
  its box, within the tolerance) within max(5 cm, 10% of the side) on every axis; a light, a camera or an empty by
  its location; nor, for two or more matched geometry objects, the box round them all (a table of a top and four
  legs, a word of letters, placed or centred as a whole: its centre or the middle of its bottom). On an alone run
  that printed a stand-in it is recorded, with the line it would have told, and judged on the joined run instead,
  where the dependencies are real (a thing stood on its dependency's object stands on the stand-in alone). "On the
  floor / on the ground" is recorded (on its bottom at z = 0 or a floor's top), never a reason.
- asked_depths: a clause asking to extrude, solidify, give a thickness, "thick" or a bevel depth (a plain bevel is a
  width), with a length within 50 characters after the word, of 2 mm or more either way (a thinner one can't be told
  from flat at the geometry line's 1 mm). flat_extrusion (alone): every candidate (the matched objects,
  else every curve and text object, else every geometry object) has 0 faces or is under 1 mm at its thinnest, and
  none is instanced (a curve's own evaluated mesh, which the depsgraph lists as an instance of itself, isn't one).
- asked_relations: behind, in front of, beside, next to, and above, on top of, below, under, beneath (recorded only),
  A the thing before the word (this step's), B the one after it (often a dependency's, so judged on the joined run;
  on the alone run only for a piece that won't be joined, a variant). nested: for every matched pair one is flat
  (under 5 mm), the other solid, and the flat one is buried in the solid one (strictly inside its range on the flat
  axis, overlapping it on the other two); a light, a camera or an empty is never flat (it has no geometry to bury).
  A relation is skipped when the run printed a stand-in for one of its matched objects (a stand_in_keys entry equal to
  its name, or one whose words are all in it): D29's plate sits inside the cube that stands in for its missing logo,
  the stand-in's fault, not the step's.

The held-out check (round 6, Nov 4): the readers over every Blender step of the helper's stored plans
(helper-model/data/raw/*plans*.jsonl, the plan in "target", else "reply") outside the smoke runs' seeds, 261 steps of
62 seeds, every extraction read; a misread is a point that isn't the thing's place, a hedged, animated or relative
place read as absolute, a thing the step doesn't make, or a depth that isn't the piece's own extrusion, and a reader
with more than MISREADS misreads gives no reason this round (GATED), though its facts are still recorded (HELD_OUT).
Places: 22 read, 1 misread (a camera parented to a rotating empty: right at frame 1 only; the geometry line's
"moving" keeps it unmatched), 5 more with words that name no object (harmless: unmatched). Depths: 17 read, 2
misread (s2 extruding s1's "Leaf", which alone would judge a stand-in; a step that only records a text's extrusion
value). Relations: 15 read, 8 misread ("under the Film panel", "the above layers", A read from a light's settings or
from adverbs, the HDRI's sun), 2 of them among nested's own 8; so nested is recorded, never a reason, this round. The
first pass (the prototype's readers with this round's changes) read 24, 17 and 16 with 1, 2 and 9 misreads; the
parenthesis rule, the ordinals and verbs among the stop words, and the animated-clause skip for relations came after
reading it, so those numbers aren't fully held out.

Measured (round 6, sandboxed, both Blenders, through the gate's own direct run with binary B's alone harness and the
mapper's joins, no model): of the 118 distinct gate-passing stored pieces, 31 ask 65 places (51 points, 10 origins, 4
floors; 59 matched to an object), 4 ask a depth, 9 a relation (12 relations, joined). place_mismatch fires on 2 (X01,
X27 = Y30) and on 2 tries that failed a later check (building_a at z 3..9 against (5, 0, 1), a halved island);
flat_extrusion on 1 (X39 = Y46); nested would fire on 3 (X06 = Y08 and its two sibling tries, the first smoke's
repair and the second's cand1, all three also skipped_input), and skips D29 by the stand-in rule. Of the audits' 55
graded Blender entries none graded ok or weak is flagged, by the gated readers or by all three. Every geometry line was
printed; the longest was 1,050 characters, and none was cut.

TELL_FORMS is the tell lines' fixed wording (ours, teacher-only; numbers and names, never the step's own phrase), for
hints.echoed_note through blender_gate.TELL_FORMS. It is defined before this module imports blender_gate, whose own
TELL_FORMS reads it as blender_gate itself is imported.
"""
from __future__ import annotations

import re

from datagen.hints import unversioned

# The tell lines (teacher-only, numbers and names only, never the step's own phrase: the echo check would find it in a
# next try that does the step right). Defined before blender_gate is imported, since its TELL_FORMS reads ours as it
# is imported itself.
PLACE_TELL = ("the step puts the %s at (%s), but %s's box runs from (%s) to (%s): neither its centre, the middle of "
              "its bottom nor its origin is there")
DEPTH_TELL = "the step asks for a depth of %s m, but %s has %d faces and is %s m at its thinnest"
NESTED_TELL = "the step puts the %s %s the %s, but %s (box %s to %s) lies inside %s's box (%s to %s)"
# doubled_depth's (Nov 5): Blender's extrude of a curve or a text goes both ways from it (5.2.2 and 5.0.1, sandboxed:
# extrude 0.08 gives z -0.08..0.08), the fault of the fourth smoke's bad example
DOUBLED_TELL = ("the step asks for a depth of %s m, but %s is %s m at its thinnest, twice that: a curve's or a text's "
                "extrude value goes both ways from it, so the depth is twice the value")
# ... and for a thing that is no curve or text (a mesh, a plane's faces), which the curve's fact doesn't explain (the
# independent checks, Nov 6)
DOUBLED_MESH_TELL = ("the step asks for a depth of %s m, but %s is %s m at its thinnest, twice that: its whole depth, "
                     "from one side to the other, is to be the step's value")
TELL_CHARS = 299  # blender_gate.TELL_KEEP's 300, less one
NAME_CHARS = (60, 24)  # a slot's names and words in a tell line, then shorter when the line would pass TELL_CHARS
# The fixed runs of 5 words or more between the forms' slots, for hints.echoed_note (through blender_gate.TELL_FORMS):
# NESTED_TELL has none (its fixed words are at most four in a row between names and numbers)
TELL_FORMS = tuple(dict.fromkeys(p.strip(" :,()'") for f in (PLACE_TELL, DEPTH_TELL, NESTED_TELL, DOUBLED_TELL,
                                                              DOUBLED_MESH_TELL)
                                  for p in re.split(r"%[sdr]", f) if len(re.findall(r"\w+", p)) >= 5))

from datagen import blender_gate as bg  # noqa: E402  (after TELL_FORMS: see above)

# The held-out check's counts per reader (its reason: the extractions read, and misread, of the readers as they are),
# and the readers that may fail a piece this round: those with at most MISREADS misreads
MISREADS = 2
HELD_OUT = {"place_mismatch": {"read": 22, "misread": 1}, "flat_extrusion": {"read": 17, "misread": 2},
            "nested": {"read": 15, "misread": 8}, "doubled_depth": {"read": 9, "misread": 1}}
GATED = frozenset(r for r, c in HELD_OUT.items() if c["misread"] <= MISREADS)

NUM = r"[-+\u2212]?\d+(?:\.\d+)?"
POINT = re.compile(r"\(\s*(%s)\s*,\s*(%s)\s*,\s*(%s)\s*\)" % (NUM, NUM, NUM))
# What says the point is where the thing is, right before it: "at", "to", "location", "located", "positioned",
# "placed", "moved", "centred at"
_PLACE_BEFORE = re.compile(r"(?:\bat|\bto|\blocations?|\blocated|\bposition(?:ed|s)?|\bplaced?|\bmoved?|"
                           r"\bcent(?:er|re)d?(?:\s+(?:at|on))?)\s*(?:=|:)?\s*(?:location\s*(?:=|:)?\s*)?$", re.I)
# What says the point is something else, in the 40 characters before it: a target, a rotation, a colour, a keyframe,
# a scale, a direction, an offset or a point relative to something
_NOT_PLACE = re.compile(r"\b(?:look\w*|point(?:ing|s|ed)\b|aim\w*|fac(?:e|es|ing)|track\w*|toward\w*|target\w*|"
                        r"rotat\w*|euler|scal\w*|colou?r\w*|rgb\w*|frames?|keyframe\w*|direction\w*|normal\w*|"
                        r"offset\w*|size\w*|dimension\w*|resolution|vector|velocity|force|gravity|relative|from)\b",
                        re.I)
# A point given as an example or a guess, in the 25 characters before it
_HEDGE = re.compile(r"\b(?:e\.\s?g\b|for example|for instance|such as|like|say|roughly|approximately|about|around|"
                    r"somewhere|near|e\.\s?g\.)", re.I)
# A point that is where a row or a path starts or ends, not where the thing is ("starting at (0, 0, 0)": the step-6
# checker's Array fence of 10 posts 0.5 m apart, whose box centre is at x 2.25), right before it
_ROW_END = re.compile(r"\b(?:start(?:s|ed|ing)?|begin(?:s|ning)?|end(?:s|ed|ing)?)\s+(?:at|from)\s*$", re.I)
_ANIMATED = re.compile(r"\bkeyframe|\bframe\s+\d|\banimat", re.I)
_ORIGIN = re.compile(r"\b(?:(?:at|on|to)\s+(?:the\s+)?(?:world\s+)?origin|cent(?:er|re)d?\s+(?:at|on)\s+(?:the\s+)?"
                     r"(?:world\s+)?origin)\b(?!\s*\()", re.I)
_FLOOR = re.compile(r"(?<!centered )(?<!centred )\b(?:on|onto)\s+(?:the\s+)?(?:floor|ground)(?:\s+plane)?\b"
                    r"(?!\s*lamp)", re.I)
# A plain "bevel" is a Bevel modifier's width or a corner's rounding, not a depth (the checker's business card with a
# "vertex bevel of 0.004 m" failed flat_extrusion); a curve's bevel depth is one
_DEPTH = re.compile(r"\b(?:extru\w*|solidif\w*|thickness|thick\b|bevel(?:_depth|\s+depth))", re.I)
_LEN = re.compile(r"(%s)\s*(mm|cm|m|met(?:er|re)s?|millimet(?:er|re)s?|centimet(?:er|re)s?)\b" % NUM, re.I)
_REL = re.compile(r"\b(behind|in\s+front\s+of|beside|next\s+to|above|on\s+top\s+of|below|under(?:neath)?|beneath)\s+"
                  r"(?:the\s+|a\s+|an\s+)?((?:[`\"']?[A-Za-z][\w.-]*[`\"']?\s*){1,3})", re.I)
SEPARATE = {"behind", "in front of", "beside", "next to"}  # a reason (nested)
ABOVE = {"above", "on top of"}  # recorded only
BELOW = {"below", "under", "underneath", "beneath"}  # recorded only
_QUOTED = re.compile(r"[`\"']([A-Za-z][\w. -]{0,40}?)[`\"']")
_NAMED = re.compile(r"(?:\bnamed|\bname\s+it|\bcalled|\bname\s*=)\s*[`\"']([A-Za-z][\w. -]{0,40}?)[`\"']|"
                    r"^\W*[`\"']([A-Za-z][\w. -]{0,40}?)[`\"']\s*:", re.I)
_IT = re.compile(r"\b(?:it|them|its|each|every)\b", re.I)
# Words that never tell one thing from another here, on top of blender_gate._name_words' own (_PLAIN_WORDS). "light"
# is a colour word too: a light is matched by its other words ("key", "rim") or not at all.
_STOP = {"place", "places", "placed", "position", "positions", "positioned", "move", "moves", "located", "location",
         "ensure", "all", "appropriately", "created", "world", "origin", "centered", "centred", "center", "centre",
         "then", "also", "it", "them", "this", "that", "applies", "apply", "using", "use", "material", "materials",
         "assign", "give", "sets", "set", "named", "name", "call", "called", "symmetrically", "around", "near", "from",
         "will", "should", "must", "into", "onto", "inside", "top", "built", "new", "scene", "light", "lights", "lamp",
         "primitive", "primitives", "powered", "power", "sure", "sits", "base", "centers", "centres", "put", "puts",
         "insert", "inserts", "import", "imports", "lay", "lays", "first", "second", "third", "fourth", "last",
         "other"}
# A parenthesis of words only ("Key Light (Spot) at ...") is part of what it follows, not a part of its own
_WORDS_ONLY = re.compile(r"\(\s*([A-Za-z][A-Za-z ]{0,24})\)")
POINTS = ("LIGHT", "CAMERA", "EMPTY")  # judged by their location, from the measuring line
FLAT = 0.005  # a box side under this is flat (nested's plate)
THIN = 0.001  # flat_extrusion's thinnest side
# A depth asked of less than this asks nothing: the geometry line rounds to 1 mm and THIN is 1 mm, so a thinner
# extrusion can't be told from none (the checker's 0.76 mm credit card failed flat_extrusion in both versions)
MIN_DEPTH = 0.002


def _f(x):
    return float(x.replace("\u2212", "-"))


def _clauses(text):
    """(start, clause) of each clause of text: blender_gate._CLAUSE's split, keeping offsets."""
    out, start = [], 0
    for m in bg._CLAUSE.finditer(text):
        out.append((start, text[start:m.start()]))
        start = m.end()
    out.append((start, text[start:]))
    return out


def _telling(text):
    return [x for x in bg._name_words(text) if x not in _STOP]


def _thing_words(clause, pos, after=False):
    """What a phrase at pos in clause is about: (words, quoted). A name the clause gives ('named "Sun_Lamp"', "name it
    `Backplate`", a list item's "`Spot_A`:"), the nearest before pos, else the first after it; else, when the words
    just before say "it", "them" or "each", the clause's first part that has telling words; else the last such part
    before pos; else (after=True) the words just after pos ("Extrude the curve by 0.08 m")."""
    names = [(m.start(), m.group(1) or m.group(2)) for m in _NAMED.finditer(clause)]
    if names:
        before = [n for at, n in names if at < pos]
        return [before[-1] if before else names[0][1]], True
    parts = re.split(r"[,()]|\band\b|\bwith\b", _WORDS_ONLY.sub(r" \1 ", clause[:pos]))
    tell = [_telling(p) for p in parts]
    if _IT.search(parts[-1] if parts else ""):
        for w in tell:
            if w:
                return w, False
    for w in reversed(tell):
        if w:
            return w, False
    if after:
        return _telling(re.split(r"[,(]|\bby\b|\bto\b", clause[pos:pos + 60])[0]), False
    return [], False


def _mine(plan, i, words, quoted):
    """Whether the thing these words name is step i's own: no other step makes it (blender_gate._made_elsewhere, the
    sizes' rule), whether the step names it in quotes or not."""
    thing = words[-1] if quoted else " ".join(words[-2:])
    return bool(thing) and not bg._made_elsewhere(plan, i, thing)


def asked_places(plan, i):
    """The places step i's own instructions put a thing of its own at: [{"phrase", "kind": "point" | "origin" |
    "floor", "point": [x, y, z] or None, "words", "quoted"}]. A point right after "at", "to", "location", "located",
    "positioned", "placed", "moved" or "centred at" (_PLACE_BEFORE), and "at (or centred at) the (world) origin"; not
    one after a target, rotation, colour, keyframe, scale or direction word (_NOT_PLACE: "looking at the origin (0, 0,
    0)"), not a hedged one (_HEDGE: "e.g., at (...)", "about", "near"), not where a row or a path starts or ends
    (_ROW_END: "starting at"), nothing in a clause that keyframes or animates, and nothing of a thing another step
    makes (_mine). "On the floor" is read too (kind "floor"), recorded, never a
    reason."""
    text = plan["steps"][i].get("instructions") or ""
    out = []
    for _, clause in _clauses(text):
        if _ANIMATED.search(clause):
            continue
        found = [(m, "point", [_f(m.group(k)) for k in (1, 2, 3)]) for m in POINT.finditer(clause)
                 if _PLACE_BEFORE.search(clause[max(0, m.start() - 30):m.start()])
                 and not _ROW_END.search(clause[max(0, m.start() - 30):m.start()])]
        found += [(m, "origin", [0.0, 0.0, 0.0]) for m in _ORIGIN.finditer(clause)]
        found += [(m, "floor", None) for m in _FLOOR.finditer(clause)]
        for m, kind, point in sorted(found, key=lambda f: f[0].start()):
            if _NOT_PLACE.search(clause[max(0, m.start() - 40):m.start()]) or \
                    _HEDGE.search(clause[max(0, m.start() - 25):m.start()]):
                continue
            words, quoted = _thing_words(clause, m.start())
            if not words or not _mine(plan, i, words, quoted):
                continue
            out.append({"phrase": clause[max(0, m.start() - 30):m.end()].strip(), "kind": kind, "point": point,
                        "words": words, "quoted": quoted})
    return out


def asked_depths(plan, i):
    """The extrusion, solidify, thickness or bevel depths step i's instructions ask of a thing of its own: [{"phrase",
    "depth": metres, "words", "quoted", "one_way"}], a length (with its unit) within 50 characters after the word, at
    least MIN_DEPTH either way (its size taken). None of these limits changes a held-out reading or a stored verdict.
    one_way (_one_way): what makes the length the thing's whole depth ("side", "mesh", "whole"), or None when it may
    be the value of a curve's or a text's extrude, which Blender applies both ways (doubled_depth reads only the
    one-way ones)."""
    text = plan["steps"][i].get("instructions") or ""
    out = []
    for _, clause in _clauses(text):
        m = _DEPTH.search(clause)
        n = _LEN.search(clause, m.start(), m.end() + 50) if m else None
        if not n:
            continue
        depth = bg._metres(_f(n.group(1)), n.group(2))
        if abs(depth) < MIN_DEPTH:
            continue
        words, quoted = _thing_words(clause, m.start(), after=True)
        if words and not _mine(plan, i, words, quoted):
            continue
        out.append({"phrase": clause[m.start():n.end()].strip(), "depth": abs(depth), "words": words,
                    "quoted": quoted, "one_way": _one_way(clause, m, n)})
    return out


# doubled_depth's reading (Nov 5): when a depth the step asks is the thing's whole depth, one way, and not the value
# Blender's extrude of a curve or a text takes, which it applies on both sides (extrude 0.08 makes 0.16, centred; 5.2.2
# and 5.0.1 alike, fill mode and offset changing neither). A side the step gives right after the number ("in the
# negative Z direction", "downward", "one way": the fourth smoke's bad example, a logo extruded 0.08 both ways where
# its step says 0.08 in negative Z), the mesh, its faces or a plane being what is extruded (nearest the extrusion
# word: "Convert the curve to a mesh and extrude it by 0.12 m", never "Set the Text curve's extrude to 0.1 m"), or a
# whole depth or thickness asked of anything but a curve or a text ("to a block depth of 0.2 m", "Solidify ... 0.05").
# Never a range, a random depth, a value to record, or a bevel depth (a bevel's depth isn't a thickness).
_SIDE = re.compile(r"\b(?:negative|positive)\s+[xyz]\b|(?<![\w.])[-+−]\s?[xyz]\b|\bdown(?:ward)?s?\b|"
                   r"\bupwards?\b|\bone\s+(?:side|direction|way)\b", re.I)
# Since the independent checks (Nov 6) the side must follow the length directly ("0.08 m in the negative Z direction",
# "0.1 m downward", "0.05 m along -Z"): a rotation's axis ("and rotate it 90 degrees about +X") or a later move ("and
# move it down to z = 0.5") said the side of no extrusion. Since the second checks (the same day) a comma or a bracket
# and a word that is no verb of its own may come between ("0.08 m, only in the negative Z direction", "0.08 m (in the
# negative Z direction)", "0.08 m straight down", "0.08 m going downward"), never "and" or "then"
_SIDE_AFTER = re.compile(r"\s*[,(]?\s*(?:(?:only|straight|directly|pointing|going|extending|running)\s+)?"
                         r"(?:(?:in|along|towards?|to|into|on)\s+(?:the\s+)?)?(?:" + _SIDE.pattern + ")", re.I)
# Both ways: "0.05 m in both directions", "on each side", within the length's own phrase: not a later bevel's ("0.1 m
# downward, then bevel each side by 2 mm"; the second checks)
_BOTH = re.compile(r"\bboth\s+(?:directions|ways|sides)\b|\b(?:each|either)\s+(?:side|direction|way)\b", re.I)
_PHRASE_END = re.compile(r";|\.(?=\s|$)|,?\s*\b(?:then|and|but|while|before|after|so)\b", re.I)
_EXTRUDED = re.compile(r"\b(?P<mesh>mesh(?:es)?|faces?|planes?|extrude[_ ]region)\b|"
                       r"\b(?P<curve>curves?|texts?|fonts?|letters?|svg|beziers?)\b", re.I)
# A mesh word that only says where a thing stands or which way it looks, so no mesh is extruded: "on the board plane",
# "above the ground plane", "lying on the plane", "rotate it to face the camera"
_STANDS_ON = re.compile(r"\b(?:on|onto|upon|above|below|over|under|beneath|atop|across)\s+"
                        r"(?:(?:the|a|an|its|their)\s+)?(?:[\w-]+\s+){0,2}$", re.I)
_FACING = re.compile(r"\s+(?:the|a|an|toward|towards|forward|forwards|up|upward|down|outward|out|front|away|camera|"
                     r"viewer)\b", re.I)
_WHOLE = re.compile(r"\bdepth\b|\bthick(?:ness)?\b|\bsolidif\w*", re.I)
_NOT_ONE_WAY = re.compile(r"\bbetween\b|\brandom\w*|\bvalues?\b|\brecord\w*|\bbevel(?:_depth|\s+depth)\b", re.I)


def _extruded(clause, start, end):
    """The _EXTRUDED matches in clause[start:end] that may name what is extruded: not a mesh word a thing stands on or
    a facing verb (_STANDS_ON, _FACING)."""
    out = []
    for x in _EXTRUDED.finditer(clause, start, end):
        if x.group("mesh") and (_STANDS_ON.search(clause[max(0, x.start() - 40):x.start()]) or
                                x.group("mesh").lower() in ("face", "faces") and
                                _FACING.match(clause, x.end())):
            continue
        out.append(x)
    return out


def _one_way(clause, m, n):
    """Why the depth at m (the extrusion word) .. n (its length) in clause is the thing's whole depth one way: "side",
    "mesh" or "whole" (see above), or None. A side counts only right after the length (_SIDE_AFTER), "both
    directions" or "each side" in the length's phrase never (_BOTH, _PHRASE_END), and a mesh word a thing stands on
    or a facing verb is no mesh extruded (_extruded; the independent checks, Nov 6)."""
    if _NOT_ONE_WAY.search(clause[m.start():n.end()]) or re.search(r"\brandom\w*|\brecord\w*", clause, re.I):
        return None
    end = _PHRASE_END.search(clause, n.end(), n.end() + 40)
    if _BOTH.search(clause[m.start():end.start() if end else n.end() + 40]):
        return None
    if _SIDE_AFTER.match(clause, n.end()):
        return "side"
    found = _extruded(clause, m.end(), n.start()) or _extruded(clause, 0, m.start())[-1:]
    kind = ("mesh" if found[0].group("mesh") else "curve") if found else None
    if kind == "mesh":
        return "mesh"
    if kind != "curve" and _WHOLE.search(clause[m.start():n.end()]):
        return "whole"
    return None


def asked_relations(plan, i):
    """The places step i's instructions give one thing against another: [{"phrase", "rel", "a": words, "a_quoted",
    "b": words, "b_quoted"}]: behind, in front of, beside, next to (nested's), above, on top of, below, under,
    underneath, beneath (recorded only). A, the thing before the word, is step i's own (_mine); B, after it, may be
    a dependency's."""
    text = plan["steps"][i].get("instructions") or ""
    out = []
    for _, clause in _clauses(text):
        if _ANIMATED.search(clause):  # as for places: where a thing is at one frame says nothing of the step
            continue
        for m in _REL.finditer(clause):
            rel = re.sub(r"\s+", " ", m.group(1).lower())
            bq = _QUOTED.findall(m.group(2))
            b = bq or _telling(m.group(2))[:2]
            a, aq = _thing_words(clause, m.start())
            if not a or not b or not _mine(plan, i, a, aq):
                continue
            out.append({"phrase": clause[max(0, m.start() - 30):m.end()].strip(), "rel": rel, "a": a,
                        "a_quoted": aq, "b": b, "b_quoted": bool(bq)})
    return out


# ---------------------------------------------------------------- the measured side

def _moving(probe):
    """Whether a name (the measuring cuts long ones to 45 characters and "...") is one the geometry line says moves."""
    names = ((probe or {}).get("geom") or {}).get("moving") or []
    return lambda n: n in names or (n.endswith("...") and any(x.startswith(n[:-3]) for x in names))


def geom_rows(probe):
    """One version's direct run (probe: its record, with "geom" and "measure"): the geometry objects with a world box
    from the geometry line, "moving" marked, the factory's untouched ones left out (the measuring's own_rows; the
    factory cube by its box when the measuring cut it)."""
    g = (probe or {}).get("geom") or {}
    m = (probe or {}).get("measure") or {}
    own = {r["n"] for r in bg.own_rows(m)}
    factory = {r["n"] for r in m.get("objects") or [] if r.get("f") and r["n"] not in own}
    moving = _moving(probe)
    out = []
    for r in g.get("objects") or []:
        if "lo" not in r or "hi" not in r or r.get("n") in factory:
            continue
        if r.get("n") == "Cube" and r["lo"] == [-1.0, -1.0, -1.0] and r["hi"] == [1.0, 1.0, 1.0]:
            continue
        out.append(dict(r, moving=1) if moving(r.get("n") or "") else r)
    return out


def point_rows(probe):
    """Lights, cameras and empties as zero-size boxes at their location (the measuring line's), the factory's
    untouched ones left out, "moving" marked from the geometry line."""
    moving = _moving(probe)
    return [{"n": r["n"], "t": r["t"], "lo": r["loc"], "hi": r["loc"], "loc": r["loc"], "anim": r.get("anim"),
             "moving": 1 if moving(r["n"]) else None}
            for r in bg.own_rows((probe or {}).get("measure")) if r.get("t") in POINTS and r.get("loc")]


def _match(rows, words, quoted, still=True):
    """The rows a thing's words name: by exact name when quoted (a .001 copy too), else those sharing the most name
    words with it (at least one); with still, never an animated or moving one, whose place at this frame says
    nothing."""
    rows = [r for r in rows if not (still and (r.get("anim") or r.get("moving")))]
    if not words:
        return []
    if quoted:
        exact = [r for r in rows if any(r["n"].lower() == w.lower() or r["n"].lower().startswith(w.lower() + ".")
                                        for w in words)]
        if exact:
            return exact
        words = [x for w in words for x in bg._name_words(w)]
    want = set(words)
    scored = [(len(want & bg._words(r["n"])), r) for r in rows]
    best = max((s for s, _ in scored), default=0)
    return [r for s, r in scored if s and s == best]


def _tol(side):
    return max(0.05, 0.1 * side)


def _at(row, point):
    """Whether a box is at a point, within max(5 cm, 10% of its side) on every axis: its centre, or the middle of its
    bottom, or its own origin when that lies in its box (a text, an SVG import or a corner-origin mesh placed by its
    location); an origin outside its box (a transform applied after the move, X27's) doesn't count."""
    lo, hi = row["lo"], row["hi"]
    tol = [_tol(hi[k] - lo[k]) for k in range(3)]
    c = [(lo[k] + hi[k]) / 2 for k in range(3)]
    for p in (c, [c[0], c[1], lo[2]]):
        if all(abs(p[k] - point[k]) <= tol[k] for k in range(3)):
            return True
    o = row.get("loc")
    return bool(o) and all(abs(o[k] - point[k]) <= tol[k] and lo[k] - tol[k] <= o[k] <= hi[k] + tol[k]
                           for k in range(3))


def _on_floor(rows, cands):
    """Whether a matched solid's bottom is at z = 0 or on a floor object's top (the floor reading, recorded only)."""
    tops = [r["hi"][2] for r in rows if re.search(r"floor|ground", r["n"], re.I) and r["hi"][2] - r["lo"][2] < 0.5]
    return any(abs(r["lo"][2] - t) <= max(0.02, 0.05 * (r["hi"][2] - r["lo"][2])) for t in tops or [0.0]
               for r in cands if r["t"] not in POINTS)


def _corner(v):
    return ", ".join(bg._num(x) for x in v)


def _cut(text, n):
    text = str(text)
    return text if len(text) <= n else text[:n - 1] + "\u2026"


def _line(form, slots, numbers):
    """form filled with the text slots (names, words) and number slots in their order (slots: [(index, text)],
    numbers: {index: text}), the text slots cut to NAME_CHARS[0], or to NAME_CHARS[1] when the line would pass
    TELL_CHARS."""
    n = len(slots) + len(numbers)
    for keep in NAME_CHARS:
        args = [None] * n
        for k, t in slots:
            args[k] = _cut(t, keep)
        for k, t in numbers.items():
            args[k] = t
        line = unversioned(form % tuple(args))
        if len(line) <= TELL_CHARS:
            break
    return line[:TELL_CHARS]


def _together(cands):
    """The box round every matched geometry object (not a light, a camera or an empty) when there are two or more
    (a table of a top and four legs, letters spelling a word), else None. It has no origin of its own, so _at takes
    only its centre or the middle of its bottom."""
    parts = [r for r in cands if r["t"] not in POINTS]
    if len(parts) < 2:
        return None
    return {"lo": [min(r["lo"][k] for r in parts) for k in range(3)],
            "hi": [max(r["hi"][k] for r in parts) for k in range(3)]}


def _off(row, point):
    """How far a row's nearest anchor (its centre or the middle of its bottom) is from a point: which matched object
    a fault's tell names."""
    lo, hi = row["lo"], row["hi"]
    c = [(lo[k] + hi[k]) / 2 for k in range(3)]
    return min(sum((p[k] - point[k]) ** 2 for k in range(3)) for p in (c, [c[0], c[1], lo[2]]))


def place_states(asked, probe, stood_in=False):
    """For each place asked, in order: ("fits", None) when a matched object is at it (_at; a light, a camera or an
    empty by its location) or two or more matched geometry objects are together (_together: a thing built of
    separate parts, placed or centred as a whole), ("fault", tell line) when none is, ("unmatched", None) when no
    object of the run's is named like the thing, or ("floor", on_floor) for "on the floor" (_on_floor: recorded,
    never a fault). With stood_in (the run printed a stand-in), a fault is ("stand_in", tell line) instead: alone, a
    careful piece that stands its thing on its dependency's object stands it on the stand-in, which isn't where the
    step says (a vase "on the table top at (1, 0, 0.75)" lands at (0, 0, 1) on the 1 m cube at the origin, in both
    versions), so blender_gate judges such a place on the joined run. A fault's tell names the matched object
    nearest the point (_off).

    Why the parts: a table of a top and four unparented legs centred at (1, 0, 0), a chair of parts and letters
    Word_E..Word_O "centred at the origin" as a word all failed place_mismatch in both versions (the step-6
    checker's fixtures, sandboxed), each part judged on its own, and the tell named an arbitrary leg; the same table
    parented to an empty passed. On the stored runs 115 of 126 matched places match one object and 1 matches two, all
    8 stored faults are single objects, and neither change alters any of the 191 stored alone verdicts. Of the 25
    stored alone runs that printed a stand-in and ask a place (59 places), the 12 that reached a joined run fit there
    (23 places) or match nothing (4)."""
    rows = geom_rows(probe)
    pts = point_rows(probe)
    out = []
    for a in asked:
        cands = _match(rows + pts, a["words"], a["quoted"])
        whole = _together(cands)
        if not cands:
            out.append(("unmatched", None))
        elif a["kind"] == "floor":
            out.append(("floor", _on_floor(rows, cands) if any(r["t"] not in POINTS for r in cands) else None))
        elif any(_at(r, a["point"]) for r in cands) or whole is not None and _at(whole, a["point"]):
            out.append(("fits", None))
        else:
            r = min(cands, key=lambda r: _off(r, a["point"]))
            out.append(("stand_in" if stood_in else "fault",
                        _line(PLACE_TELL, [(0, " ".join(a["words"])), (2, r["n"])],
                              {1: _corner(a["point"]), 3: _corner(r["lo"]), 4: _corner(r["hi"])})))
    return out


def place_faults(asked, probe, stood_in=False):
    """[(index into asked, tell line)] for each place asked that no matched object is at (place_states)."""
    return [(k, line) for k, (state, line) in enumerate(place_states(asked, probe, stood_in)) if state == "fault"]


def _thinnest(r):
    return min(r["hi"][j] - r["lo"][j] for j in range(3))


def _depth(x):
    """A depth as a tell line writes it, to the millimetre under 5 cm (blender_gate._num's two decimals wrote "a
    depth of 0 m" for anything under 5 mm)."""
    return bg._num(x) if x >= 0.05 else ("%.3f" % x).rstrip("0").rstrip(".")


def depth_states(asked, probe):
    """For each depth asked: ("fits", None) or ("fault", tell line) on its candidates (the objects named like the
    thing, else every curve and text object, else every geometry object), a fault when every candidate has no faces or
    is under THIN at its thinnest and none is instanced (a curve that only places instances is no extrusion);
    ("unmatched", None) when the run has no geometry."""
    rows = geom_rows(probe)
    out = []
    for a in asked:
        cands = _match(rows, a["words"], a["quoted"], still=False) or \
            [r for r in rows if r["t"] in ("CURVE", "FONT")] or rows
        if not cands:
            out.append(("unmatched", None))
            continue

        def flat(r):
            return not r.get("inst") and (r.get("faces") == 0 or _thinnest(r) < THIN)
        if not all(flat(r) for r in cands):
            out.append(("fits", None))
            continue
        r = cands[0]
        out.append(("fault", _line(DEPTH_TELL, [(1, r["n"])], {0: _depth(a["depth"]), 2: int(r.get("faces") or 0),
                                                             3: _depth(_thinnest(r))})))
    return out


def depth_faults(asked, probe):
    """[(index into asked, tell line)] for each depth asked that every candidate lacks (depth_states)."""
    return [(k, line) for k, (state, line) in enumerate(depth_states(asked, probe)) if state == "fault"]


def asked_doubled(plan, i):
    """The depths of asked_depths that are the thing's whole depth one way (their "one_way"): doubled_depth's."""
    return [a for a in asked_depths(plan, i) if a.get("one_way")]


def _thickness(r):
    """A row's thickness as its extrusion makes it: its thinnest side, less a curve's or a text's bevel on both sides
    (the geometry line's curve settings)."""
    bevel = float(((r.get("curve") or {}).get("bevel")) or 0.0)
    return max(0.0, _thinnest(r) - 2 * bevel)


def doubled_states(asked, probe):
    """For each one-way depth asked (asked_doubled): ("fault", tell line) when every candidate (depth_states' own:
    the objects named like the thing, else every curve and text object, else every geometry object) is twice the
    depth thick (within 10% of it, or MIN_DEPTH) where once would do, none instanced or flat (a flat one is
    flat_extrusion's); ("fits", None) otherwise; ("unmatched", None) when the run has no geometry. Its thickness is
    the thinnest side less a curve's bevel on both sides (_thickness). The fourth smoke's bad example (blender-0002-02
    s1, a text "Pulse_Curve" with extrude 0.08: z -0.08..0.08) fails in both versions; the same step's pieces that
    extrude 0.04 and move it down, or put a Solidify of 0.08 on a flat curve, pass, and so do a piece of any other
    thickness: a 1 m stand-in, a 0.15 m logo asked 0.15. The tell explains Blender's both-ways extrude only for a
    curve or a text (DOUBLED_TELL); another thing gets DOUBLED_MESH_TELL."""
    rows = geom_rows(probe)
    out = []
    for a in asked:
        cands = _match(rows, a["words"], a["quoted"], still=False) or \
            [r for r in rows if r["t"] in ("CURVE", "FONT")] or rows
        if not cands:
            out.append(("unmatched", None))
            continue
        want, tol = 2 * a["depth"], max(MIN_DEPTH, 0.2 * a["depth"])

        def doubled(r):
            return not r.get("inst") and r.get("faces") != 0 and _thinnest(r) >= THIN and \
                abs(_thickness(r) - want) <= tol
        if not all(doubled(r) for r in cands):
            out.append(("fits", None))
            continue
        r = cands[0]
        form = DOUBLED_TELL if r["t"] in ("CURVE", "FONT") else DOUBLED_MESH_TELL
        out.append(("fault", _line(form, [(1, r["n"])], {0: _depth(a["depth"]), 2: _depth(_thinnest(r))})))
    return out


def _inside(a, b, k, tol):
    """Whether box a's interval on axis k overlaps b's by more than tol, a flat one lying strictly inside the other's
    (its middle more than tol from either end)."""
    alo, ahi, blo, bhi = a["lo"][k], a["hi"][k], b["lo"][k], b["hi"][k]
    if ahi - alo < tol:
        return blo + tol < (alo + ahi) / 2 < bhi - tol
    if bhi - blo < tol:
        return alo + tol < (blo + bhi) / 2 < ahi - tol
    return min(ahi, bhi) - max(alo, blo) > tol


def buried(a, b):
    """Whether one of two boxes is flat (a side under FLAT), the other solid, and the flat one lies inside the solid
    one: strictly inside its range on the flat axis, overlapping it on the other two (X06's plate in its logo). A
    light, a camera or an empty is neither: it has no geometry to bury (a lamp inside a curved backdrop's box stands
    in front of it)."""
    if a["t"] in POINTS or b["t"] in POINTS or (_thinnest(a) < FLAT) == (_thinnest(b) < FLAT):
        return False
    tol = [max(0.005, 0.05 * min(a["hi"][k] - a["lo"][k], b["hi"][k] - b["lo"][k]) or 0.005) for k in range(3)]
    return all(_inside(a, b, k, tol[k]) for k in range(3))


def _stood_in(row, keys):
    """Whether the run printed a stand-in for this object: a key equal to its name, or one whose words are all in it
    (D29's plate sits inside the cube that stands in for its missing logo, a fault of the stand-in, not the step's)."""
    words = bg._words(row["n"])
    return any(k == row["n"] or (bg._words(k) and bg._words(k) <= words) for k in keys)


def relation_states(asked, probe, stand_in_keys=()):
    """For each relation asked: ("fits", None), ("fault", tell line) for behind, in front of, beside or next to when
    every pair of the objects named like A and like B has one flat and buried in the other (buried), ("recorded",
    holds) for above, on top of, below and under (A's centre over B's top less a tolerance, or under its bottom),
    ("unmatched", None) when either side names no object of the run's, or ("stand_in", None) when the run printed a
    stand-in for one of the matched objects (_stood_in)."""
    rows = geom_rows(probe) + point_rows(probe)
    out = []
    for a in asked:
        B = _match(rows, a["b"], a["b_quoted"])
        A = [r for r in _match(rows, a["a"], a["a_quoted"]) if r not in B]
        if not A or not B:
            out.append(("unmatched", None))
            continue
        if any(_stood_in(r, stand_in_keys) for r in A + B):
            out.append(("stand_in", None))
            continue
        if a["rel"] not in SEPARATE:
            def holds(x, y):
                tol = max(0.01, 0.05 * (y["hi"][2] - y["lo"][2]))
                cz = (x["lo"][2] + x["hi"][2]) / 2
                return cz >= y["hi"][2] - tol if a["rel"] in ABOVE else cz <= y["lo"][2] + tol
            out.append(("recorded", all(holds(x, y) for x in A for y in B)))
            continue
        bad = [(x, y) for x in A for y in B if buried(x, y)]
        if len(bad) < len(A) * len(B):
            out.append(("fits", None))
            continue
        flat, solid = sorted(bad[0], key=lambda r: _thinnest(r) >= FLAT)
        out.append(("fault", _line(NESTED_TELL, [(0, " ".join(a["a"])), (1, a["rel"]), (2, " ".join(a["b"])),
                                                 (3, flat["n"]), (6, solid["n"])],
                                   {4: _corner(flat["lo"]), 5: _corner(flat["hi"]), 7: _corner(solid["lo"]),
                                    8: _corner(solid["hi"])})))
    return out


def relation_faults(asked, probe, stand_in_keys=()):
    """[(index into asked, tell line)] for each relation that every matched pair breaks (relation_states)."""
    return [(k, line) for k, (state, line) in enumerate(relation_states(asked, probe, stand_in_keys))
            if state == "fault"]
