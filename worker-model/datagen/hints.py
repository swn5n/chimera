"""Teacher-only hints: notes added to the teacher's copy of a worker request, never to the stored training request
(DESIGN.md, "hints.py"; the plan's "Teacher-only hints").

    hints = hints_for(plan, i, mode, facts, failures)    # facts: tools.rna_lint.Facts (both versions' dumps)
    messages = teacher_copy(request["messages"], hints)  # a copy; the request itself is left as Go made it

The notes are the plan's line that format rules win over the instructions' wording about files; for a files step,
that each path goes on a plain File: line (77 of gpt-oss's 86 files pieces in the smoke run bolded them, which the
validator refuses) and only the step's own files are written; and for a Blender step, that no files outside the
script's folder exist when it is checked, so it guards files and falls back to something built in code without the
stand-in marker (which is only for a missing dependency's key, as the gate reads it), three habits the smoke run's
targets got wrong (a size=1 cube's scale, which way a light points, Follow Path's offset) and not to name Blender
versions, and for a step whose values later steps use (values_step, by its title), that they go in ctx["values"]
under their SETTINGS_ keys (VALUES_NOTE, the contract's channel since Nov 4); since Nov 5 (after the fourth smoke,
step_notes), for a step that adds a camera of its own, that it is to be the scene's camera (CAMERA_NOTE), for one that
asks Chimera to render or save, that Chimera's rule on that wins over the step's wording (OUTPUT_NOTE), and for one
whose words or earlier failures name one of the Blender 5 traps the fourth smoke hit, that trap's fact (BLENDER5:
keyframes, video, the compositor, SVG import, a curve's extrude, the Subsurface Scattering node's Weight), each checked
in both Blenders, while a failure line on such a name ends with its replacement (fix_for); since Nov 6 (after the
fifth smoke), BLENDER_NOTE says what to print for a missing input file (a plain line of the piece's own that names
it), the keyframes fact and its fix name the slot (the animated ID's animation_data.action_slot, after its first
keyframe_insert), and a Blender step that isn't a values step, in a plan of more than one step, is told the handoff
lines' form, names only on provides and uses and each line within Chimera's limit (HANDOFF_NOTE; a values step's
provides line is the user's open question, so it hears nothing of it); then Blender's own API facts
for what the step names: for every node whose label or idname appears in the step's title or instructions, its inputs
and outputs per version, less those no script can reach (the shaders' Weight) and with the settings that show one a
fresh node hides ("W [float] (with noise_dimensions 1D or 4D)"); for every RNA class named there, its properties
(names, enum items) per version, differences marked; and always the render engine and file-format values. The facts are
mechanical, read from tools/rna_dump.py's dumps, which Blender 5.2.2 and 5.0.1 made themselves; only the matching of
a step's words to nodes and classes is ours. They are capped at 6,000 characters, most-mentioned first. After a
failed candidate, `failures` (lint findings, crashes and the gates' plain lines) are listed under FAILED_ON in every
mode, and for a Blender step put the nodes and classes they name first, so the hints get sharper after a failure and
stay mechanical. The newest FAILURES_KEEP failure lines are listed, and the newest failure's names get the facts first:
the later tries' lines are the ones the gates' tell lines add (Nov 4, after the second smoke run).

No note names a version: the facts' marks say "[newer only]" and "[older only]", and failure lines put the versions
in words (unversioned), since Chimera's request names none of them (its rules say "Blender 5.0 or newer"; a
repair's names the Blender that crashed) and 4 of qwen3.8's 13 targets in the smoke run repeated the notes' 5.2.2
and 5.0.1. version_leak finds a reply that names one its request doesn't, and notes_leak one that uses the notes'
own words for them and for the checks ("[newer only]", "the older Blender", "both Blenders", "sandboxed": 10 of the
smoke's 258 distinct Blender replies cite "the sandbox", which no request mentions, 6 of them naming no version);
task.py's precheck and the build drop both, for Blender steps only (no other mode's notes carry them, and
"Django==5.0.1" is no leak). So BLENDER_NOTE no longer says "sandboxed" or "two Blender versions" (Nov 4): every
Blender teacher copy opened with them, and with notes_leak a reply that picked one up would be dropped before its
gate; the facts head still says the facts come from more than one Blender.

Matching is precision first, since every wrong match takes room: a label of several words matches as a phrase in
any case ("Principled BSDF", "noise texture"); a one-word label only as "<label> node" or "compositor <label>"
("Glare node", "compositor glare"), because most are ordinary words (Mix, Value, Image, Cube); a label several
node trees share keeps the trees the step speaks of (compositor, geometry nodes, material or shader) when it names
any. A class matches by its identifier, or by its name in words when that has several ("bevel modifier", "sun
light", "render settings"), plus a few names a class's own doesn't give (ALIASES: "Subdivision Surface modifier",
"Cycles", "depth of field", "compositor"). Classes others derive from (Modifier, Light, NodeTree) and the old
texture classes (NoiseTexture, whose noise_scale is a classic wrong guess for the node) only match by identifier.

For a section step the notes give the heading line to start with (prose_gate.section_heading: the heading the
instructions give outright, else the title without its instruction verb and bracketed notes; when the instructions
speak of a heading prose_gate can't read, that the piece starts with ## and their heading, else this line),
the length band (prose_gate.note_band, inside the band the check allows; none when the step names two different
counts and none for the whole section) and, when the check looks for them, that the first and last paragraphs don't
frame the whole document ("other steps do that" only when another section's title is an introduction or a
conclusion); after a dropped try, what it was dropped for (plain lines from task.py, listed under FAILED_ON).
gpt-oss's first smoke seed lost every section to these rules (Nov 3).

The notes are ours, so a reply that repeats them can't be a target (echoed_note, which task.py's precheck and the
build ask): it would teach the worker to cite what Chimera never sends. What of a failure line the step's own request
says too (a size the step gives, the names of its provides line) is Chimera's, not ours, so precheck gives echoed_note
the request and such a run of words doesn't count; nor does one that is mostly numbers (a measured size), nor one the
failed candidate a line describes holds itself (Tell: its handoff's names, quoted back by a gate's tell line, are the
model's words, and that candidate passed the echo check).
"""
from __future__ import annotations

import re

from contract import planinfo
from contract.validate import HANDOFF_LINE_MAX
from tools import blenders, rna_lint

HEAD = "Notes for you, the teacher (Chimera doesn't send these):"
FORMAT_NOTE = "Format rules win over the instructions' wording about files."
FILES_NOTE = ("Put each path on a plain line right before its block, File: src/x.py, with no **, # or backticks around "
              "it; write only the files your step owns.")
# Since the fifth smoke (Nov 6): what to print instead of the marker for a missing input file. The marker stood for an
# SVG, an HDRI or a font on 9 of smoke5's 12 marker_misused tries and 11 of its 23 gated tries with a misused marker (5
# of 10 told retries repeated it), and the note said only what not to print. Chimera's rule makes the marker a
# missing dependency's ctx key; a file is no such key.
BLENDER_NOTE = ("When the script is checked, no files outside its folder exist, so guard any file the task names "
                "(os.path.exists) and fall back to something built in code, without the stand-in marker: print a "
                "plain line of the piece's own that names the missing file instead, since print(\"chimera: "
                "stand-in\", key) is only for a key a missing dependency was to provide.")
# Since the fifth smoke (Nov 6): for a Blender step that isn't a values step (values_step) in a plan of more than one
# step (a lone step's reply has no handoff), the handoff lines' form, before any sampler: Chimera warns past
# HANDOFF_LINE_MAX characters on any of the three lines (app/hydra_piece.go, handoff_long), and the build drops such a
# piece. qwen3.8, the last sampler, wrote 339- and 309-character provides lines with a note in brackets after each name
# (smoke5's blender-0008-00 s2 and s3), which no tell could reach; with names-only lines (provides 111 and 67, uses 40
# and 84 characters) both pass the gate in both Blenders and dep_honesty. The
# assumed line is held only to the length: it says what was guessed, in words. A ctx key goes bare, as Chimera's rule
# has later steps find in ctx what a dependency lists under provides, so the note doesn't push a key out for an
# object's name. A values step's provides line is the user's open question (blender_gate.warning_faults), so it gets
# no word of this.
HANDOFF_NOTE = ("Handoff lines: give provides and uses as exact names only, comma-separated, a ctx key bare (sofa, not "
                "ctx[\"objects\"][\"sofa\"]) with no note or size in brackets after it, and on uses the step each came "
                "from (sofa from s2); keep each of the three lines within %d characters." % HANDOFF_LINE_MAX)
BLENDER_HABITS = (  # what the smoke run's kept targets got wrong (three cubes, a ceiling light, a path)
    "Sizes: primitive_cube_add(size=1) makes a 1 m cube, so scale it by the size you want, not by half of it (the "
    "default, size=2, makes a 2 m cube).",
    "Lights and cameras: at rotation (0, 0, 0) they point down their local -Z, so turning one 180° about X points it "
    "up.",
    "A Follow Path constraint adds the object's own location to the path as an offset: leave the object at the origin "
    "unless the step wants that offset.")
VERSIONS_NOTE = "Don't name Blender versions your request doesn't."
# For a Blender step whose values later steps use (values_step): how they get there, the contract's ctx["values"] (the
# user's decision of Nov 4). The smoke runs' 7 values-only steps all had dependents, and in 21 of their 45 tries the
# teacher made up ctx["variables"] or ctx["settings"], as did 7 of the 10 pieces kept for them: a key outside the
# contract, which 35 of the 40 stored tries that only read such a key took from the dependency code their request
# showed.
VALUES_NOTE = ('Later steps use the values this step defines: keep them in SETTINGS_{sid} and, in build_{sid}, put '
               'each one they use in ctx["values"] under the same key; list those keys under provides. ctx has no '
               'other key for them.')
# values_step's title test: it opens with define, declare or specify and names values, or it is the script's header
_VALUES_NOUNS = (r"(?:variables?|dimensions?|parameters?|params|constants?|measurements?|sizes?|settings|values|"
                 r"colou?rs|config(?:uration)?)")
VALUES_TITLE = re.compile(r"^\W*(?:define|declare|specify)\b[^\n]{0,80}?\b" + _VALUES_NOUNS + r"\b", re.I)
HEADER_TITLE = re.compile(r"\bscript\s+header\b|\bheader\s*(?:and|&)\s*imports\b", re.I)
# After the fourth smoke (Nov 5): two habits and Blender's own API, each given only when the step's words call for it
# (step_notes). For a step that adds a camera of its own (blender_gate.asks_camera, the clause camera_not_active reads,
# which already passes over one the step's words let an existing camera do, or leave to another step): of the 14 tries
# of n-blender-0000-01's two camera steps 11 never made their camera the scene's, so the factory camera rendered and the
# new one, named "Camera", became Camera.001 behind it (dupes).
CAMERA_NOTE = ("Cameras: a render uses scene.camera, and the start-up scene already has a camera there, so make the "
               "camera this step adds the scene's camera (scene.camera = that object) unless the step says otherwise.")
# For a step whose words ask Chimera to render or save (blender_gate.asked_outputs, what output_missing reads): every
# one of the 12 stored saves_or_renders tries is on such a step (the step says "call bpy.ops.render.render(...)", the
# teacher calls it, and three tries running did after the validator's line). FORMAT_NOTE says it of files; Chimera's
# own rule says where the path goes, in other words (no 8-word run shared with its Blender rule).
OUTPUT_NOTE = ('Chimera\'s mode rule on renders and saves wins over the step\'s wording: a step that says to render '
               'or save hands its path and settings over in SETTINGS_{sid}["output"], and the piece itself never calls '
               'bpy.ops.render.render or a save operator, even where the step names the call.')
# Blender's own API for what the fourth smoke's teacher kept getting wrong (results/DATAGEN-SMOKE.md, "Why Blender
# still yields little", item 1), each checked in both sandboxed Blenders (Nov 5): a fact is given when the step's
# words name its topic ("words") or an earlier try's failure does ("fails", or a fix's pattern), and a failure line
# its fix's pattern hits ends with the fix, which names the replacement (failure_lines). No version is named.
# - keyframes: Action has no fcurves in either Blender (16 of the fourth smoke's 123 Blender tries crashed or were
#   linted on it, on all 4 animation steps, and every repair dodged it); the channelbag path works in both, a slot is
#   None until a key is inserted, and the preferences' new-key interpolation doesn't reach keyframe_insert. Since the
#   fifth smoke (Nov 6) the note and the fix name the slot, the animated ID's animation_data.action_slot, read after
#   its first keyframe_insert, which sets it (an object's, a camera data's, a node tree's; an action assigned by hand
#   has none until then), and the note no longer says "None": 6 of smoke5's 121 Blender tries took the channelbag path
#   with a slot of None (4), the action (1) or a function that doesn't exist (1), as "(action, slot)" and "(None
#   before its first key)" read; the fix also ends those tries' failure lines (a None or the action passed as the
#   slot, the made-up name).
# - video: file_format = "FFMPEG" raises TypeError until media_type is "VIDEO", which sets FFMPEG itself; ffmpeg.format
#   (MKV by default, MPEG4 for .mp4) is the container, there is no ffmpeg.container (all 8 tries of blender-0008-00 s5).
# - compositor: scene.node_tree is gone and CompositorNodeComposite undefined; scene.compositing_node_group's Group
#   Output (a socket from interface.new_socket) is what a render gets, with use_nodes on or off; film_transparent with
#   a fresh scene's PNG (RGBA; a switch to VIDEO and back leaves RGB) gives alpha 0 (all 6 tries of blender-0002-02 s4
#   missed it).
# - SVG: bpy.ops.import_curve.svg imports with --factory-startup, into a collection named after the file, 80 SVG px at
#   0.0226 m; bpy.ops.wm.svg_import "could not be found".
# - extrude: a curve's (and a text's) extrude 0.08 spans -0.08 to 0.08, -0.08 is clamped to 0; extrude 0.04 with the
#   object at z -0.04, or a Solidify of 0.08 at offset -1 (either winding, an imported SVG too), spans -0.08 to 0 (the
#   third smoke's blender-0002-02 s1 went flat on a negative value, the fourth's audit's bad example is 0.16 m thick).
# - the Subsurface Scattering node: inputs["Weight"] raises KeyError ("Weight" in inputs is False, keys() lists it),
#   as on the Principled BSDF, whose subsurface is "Subsurface Weight" (the third smoke's one Weight crash).
# The keyframes fix (since Nov 6): the slot named (the fact, which comes with every line the fix ends, says when to
# read it). No 8-word run of it is code that does what it says: its one run is "use" and the call's 7 words ("for fc
# in anim_utils...action_slot).fcurves:" shares 7 with it, "curves = ..." too). At 93 characters a hidden-error tell
# (silent.SWALLOWED_ATTR, 166 fixed) keeps its end beside it in silent.TELL_CHARS (hints._line); 101 is the most.
KEYFRAMES_FIX = "use anim_utils.action_get_channelbag_for_slot(action, obj.animation_data.action_slot).fcurves"
# The checks of Nov 6: under --factory-startup a plain "import bpy_extras" loads no anim_utils in either Blender, so the
# fact's dotted name after it raises "module 'bpy_extras' has no attribute 'anim_utils'", which no fix ended; this
# one says how to import it. The import alone is 4 words, under NOTE_MIN, so the words before it make the fix a run
# of ours, and a piece that writes the import repeats none of it.
ANIM_UTILS_FIX = "import the submodule first: from bpy_extras import anim_utils"
BLENDER5 = (
    {"name": "keyframes",
     "words": re.compile(r"\bkey[\s‐‑-]?fram\w*|\bf[\s‐‑-]?curves?\b|\bfcurves?\b|\bgraph\s+editor\b|"
                         r"\borbit(?:s|ing|ed)?\b|\bturntable\b|\binterpolation\b", re.I),
     "fails": None,
     "note": "Keyframes: an Action has no fcurves. After an ID's first keyframe_insert, its F-curves are in the "
             "channelbag that bpy_extras.anim_utils.action_get_channelbag_for_slot(action, slot) gives, slot being "
             "that ID's animation_data.action_slot (obj.animation_data.action_slot for an object obj), which that "
             "first key sets; the channelbag's fcurves hold the keyframe_points, whose interpolation can be set.",
     "fixes": ((re.compile(r"\bAction'?(?: object)? has no attribute '?fcurves\b|"
                           r"\bNoneType'?(?: object)? has no attribute '?fcurves\b|"
                           r"\bexpected an? ActionSlot type\b|\baction_get_channelbag_for_action\b"),
                KEYFRAMES_FIX),
               (re.compile(r"\bmodule '?bpy_extras'? has no attribute '?anim_utils\b"), ANIM_UTILS_FIX))},
    {"name": "video",
     "words": re.compile(r"\bffmpeg\b|\bmp4\b|\bh\.?\s?264\b|\bmpeg[\s‐‑-]?4\b|\bvideo\b(?!\s+sequen)|\bmovie\b|"
                         r"\.(?:mov|mkv|avi|webm)\b", re.I),
     "fails": None,
     "note": "Video: set render.image_settings.media_type to 'VIDEO' first, which turns file_format to FFMPEG "
             "(file_format = 'FFMPEG' alone raises TypeError); the container is render.ffmpeg.format ('MPEG4' for an "
             ".mp4) and the codec render.ffmpeg.codec ('H264'); there is no ffmpeg.container.",
     "fixes": ((re.compile(r'enum "FFMPEG" not found'),
                "set image_settings.media_type to 'VIDEO' first, which makes file_format FFMPEG"),
               (re.compile(r"\bFFmpegSettings'?(?: object)? has no attribute '?container\b"),
                "the container is ffmpeg.format ('MPEG4' for an .mp4)"))},
    {"name": "compositor",
     "words": re.compile(r"\bcompositor\b|\bcompositing\b|\bcomposite\b|\brender\s+layers?\s+node\b|\balpha\s+over\b|"
                         r"\bfile\s+output\s+node\b|\bfilm_transparent\b|"
                         r"\btransparent\s+(?:background|png|film|render)\b", re.I),
     "fails": None,
     "note": "Compositor: a scene has no node_tree. Its compositor is the node group in scene.compositing_node_group "
             "(one made with bpy.data.node_groups.new(name, 'CompositorNodeTree')), and there is no Composite node: "
             "the result is what reaches the group's Group Output node, whose socket the group's interface makes "
             "(new_socket, in_out 'OUTPUT'). A transparent PNG needs only render.film_transparent = True (with the "
             "PNG's color_mode at its default, RGBA), no compositor.",
     "fixes": ((re.compile(r"\bScene'?(?: object)? has no attribute '?node_tree\b"),
                "the compositor is scene.compositing_node_group, a 'CompositorNodeTree' node group"),
               (re.compile(r"\bCompositorNodeComposite\b"),
                "there is no Composite node: a compositor group's result goes to its Group Output node"))},
    {"name": "svg",
     "words": re.compile(r"\bsvg\b|\bscalable\s+vector\b", re.I),
     "fails": None,
     "note": "SVG import as curves is bpy.ops.import_curve.svg(filepath=...), not a wm operator: it adds curve "
             "objects, about 0.28 mm per SVG pixel, in a new collection named after the file.",
     "fixes": ((re.compile(r"\bsvg_import\b|\bimport_svg\b"),
                "SVG import is bpy.ops.import_curve.svg(filepath=...)"),)},
    {"name": "extrude",
     "words": re.compile(r"\bextru\w*", re.I),
     "also": re.compile(r"\b(?:curves?|b[eé]ziers?|texts?|fonts?|letters?|logos?|svg|paths?|outlines?)\b", re.I),
     "fails": None,
     "note": "A curve's extrude (a text's too) thickens it both ways from its plane, to twice the value in all (0.08 "
             "spans -0.08 to 0.08 in local Z), and a negative value is taken as 0. For a depth d on one side, set "
             "extrude to d/2 and move the object d/2 that way, or give it a Solidify modifier of thickness d (offset "
             "-1 puts it on the -Z side of a flat filled curve).",
     "fixes": ()},
    {"name": "subsurface",
     "words": re.compile(r"\bsubsurface\b|\bsss\b", re.I),
     "fails": re.compile(r"input 'Weight' on ShaderNodeSubsurfaceScattering\b"),
     "note": "The Subsurface Scattering node has no Weight input a script can reach (inputs['Weight'] raises "
             "KeyError); a Principled BSDF's subsurface amount is its Subsurface Weight input.",
     "fixes": ((re.compile(r'key "Weight" not found'),
                "no shader node's Weight input can be looked up by a script: leave it out"),)},
)
# OUTPUT_NOTE's fixed wording for echoed_note, as VALUES_NOTE's: the parts either side of the step's SETTINGS_ name,
# and the note filled for s1 to s8 (PLAN_STEPS)
OUTPUT_FORMS = tuple(p.strip(" :,.") for p in OUTPUT_NOTE.split("SETTINGS_{sid}") if len(re.findall(r"\w+", p)) >= 5)
PLAN_STEPS = 8  # the most steps Chimera's cleanPlan keeps (app/hydra.go), so the most a note's {sid} can be filled for
OUTPUT_FILLED = tuple(OUTPUT_NOTE.format(sid="s%d" % k) for k in range(1, PLAN_STEPS + 1))
# Notes earlier runs gave (still ours: a record made with them may be built again)
RETIRED = (("blender_note", "The script is checked in Blender 5.2.2 and 5.0.1, sandboxed: no files outside its folder "
                            "exist, so guard any file the task names (os.path.exists) and fall back to something "
                            "built in code."),
           ("facts_head", "Blender's own API facts for this step, printed by Blender 5.2.2 and 5.0.1 (a name marked "
                          "[5.2.2 only] doesn't exist in 5.0.1):"),
           ("blender_note", "The script is checked in two Blender versions, sandboxed: no files outside its folder "
                            "exist, so guard any file the task names (os.path.exists) and fall back to something "
                            "built in code, without the stand-in marker: print(\"chimera: stand-in\", key) is only for "
                            "a key a missing dependency was to provide."),
           # until the fifth smoke's round (Nov 6): the Blender note without the plain print, the keyframes fact and
           # its fix without the slot named
           ("blender_note", "When the script is checked, no files outside its folder exist, so guard any file the "
                            "task names (os.path.exists) and fall back to something built in code, without the "
                            "stand-in marker: print(\"chimera: stand-in\", key) is only for a key a missing dependency "
                            "was to provide."),
           ("blender_fact", "Keyframes: an Action has no fcurves. The F-curves keyframe_insert makes are in a "
                            "channelbag, which bpy_extras.anim_utils.action_get_channelbag_for_slot(action, slot) "
                            "gives, slot being the animated ID's animation_data.action_slot (None before its first "
                            "key); the channelbag's fcurves hold the keyframe_points, whose interpolation can be set."),
           ("blender_fact", "its F-curves are in anim_utils.action_get_channelbag_for_slot(action, slot).fcurves"))
FAILED_ON = "Earlier tries of this step failed on:"
SECTION_NOTE = ("Start your piece with this heading line, even when your step asks for JSON, a table or a list (put "
                "those under it):")
SECTION_GIVEN_NOTE = ("Start your piece with ## and the heading your step's instructions give for it, even when it "
                      "asks for JSON, a table or a list (put those under it); if they give none, use this one:")
LENGTH_NOTE = "Write {low} to {high} words of prose; the heading line and code blocks don't count."
LENGTH_MIN_NOTE = "Write at least {low} words of prose; the heading line and code blocks don't count."
LENGTH_MAX_NOTE = "Write at most {high} words of prose; the heading line and code blocks don't count."
LENGTH_TAIL = "words of prose; the heading line and code blocks don't count."
FRAMING_NOTE = ("Don't {ends} with a paragraph about the whole document (no \"In this report\", \"In summary\" or "
                "\"In conclusion\").")
FRAMING_OTHERS_NOTE = FRAMING_NOTE[:-1] + ": other steps do that."  # when another section is the intro or conclusion
FRAMING_ENDS = {("intro", "outro"): "open or close", ("intro",): "open", ("outro",): "close"}
NOTE_N = 8  # echoed_note's run of words: tools/check_overlap.py's n-grams
NOTE_MIN = 5  # a note of fewer words is too ordinary to tell an echo by
NUMERIC_RUN = 4  # an extra run with this many numeric words is mostly numbers (a size), not our wording
# VALUES_NOTE's fixed wording for echoed_note: the parts between the step's own names, of NOTE_MIN words or more (a
# reply's SETTINGS_s1 and build_s1 are Chimera's names, and the words between them, "and, in", are too few)
VALUES_FORMS = tuple(p.strip(" :,.") for p in re.split(r"SETTINGS_\{sid\}|build_\{sid\}", VALUES_NOTE)
                     if len(re.findall(r"\w+", p)) >= NOTE_MIN)
# ... and the note filled for the steps a plan can have (cleanPlan keeps up to 8, PLAN_STEPS; s8 was missing until the
# independent checks of Nov 6), whose runs that cross the step's names ("keep them in SETTINGS_s1 and, in build_s1,
# put each one") the parts alone missed: 11 of its 32 runs (the integrity check)
VALUES_FILLED = tuple(VALUES_NOTE.format(sid="s%d" % k) for k in range(1, PLAN_STEPS + 1))
# The notes' own words for the Blenders and the checks (notes_leak): no request of Chimera's says them
NOTES_WORDS = (re.compile(r"\[(?:newer|older|middle)(?:,\s*(?:newer|older|middle))*\s+only\]", re.I),
               re.compile(r"\bthe (?:newer|older|middle) Blender\b(?!\s+(?:versions?|releases?|builds?)\b)", re.I),
               re.compile(r"\bboth Blenders\b", re.I),
               re.compile(r"\beither Blender\b", re.I),
               re.compile(r"\btwo Blender versions\b", re.I),
               re.compile(r"\bsandbox\w*", re.I))
FACTS_CAP = 6000
FAILURES_KEEP = 6  # failure lines listed: the newest (failure_lines)
FAILURE_CHARS = 240
LEFT_OUT_ROOM = 48  # kept free for the "left out" line
TREES = {"ShaderNodeTree": r"\b(?:materials?|shaders?|shading)\b", "GeometryNodeTree": r"\bgeometry[\s-]+nodes?\b",
         "CompositorNodeTree": r"\b(?:compositor|compositing)\b"}  # texture nodes' labels are left out
NODE_PREFIXES = ("ShaderNode", "GeometryNode", "CompositorNode", "FunctionNode", "TextureNode", "NodeSocket",
                 "NodeTreeInterface")
# Bases whose properties a class's entry leaves out (every node, modifier and ID has them).
STOP_BASES = {"bpy_struct", "ID", "Node", "NodeInternal", "ShaderNode", "GeometryNode", "CompositorNode",
              "TextureNode", "FunctionNode", "Modifier"}
TOO_WIDE = {"bpy_struct", "bpy_prop_collection", "ID", "Struct", "Node", "NodeSocket", "Property"}
# Names a step uses for a class (or one property) that the class's own name doesn't give.
ALIASES = {
    "subdivision surface modifier": ["SubsurfModifier"],
    "subsurf": ["SubsurfModifier"],
    "geometry nodes modifier": ["NodesModifier"],
    "cycles": ["CyclesRenderSettings"],
    "eevee": ["SceneEEVEE"],
    "color management": ["ColorManagedViewSettings"],
    "colour management": ["ColorManagedViewSettings"],
    "view transform": ["ColorManagedViewSettings"],
    "depth of field": ["CameraDOFSettings"],
    "rigid body": ["RigidBodyObject"],
    "particle system": ["ParticleSettings"],
    "keyframe": ["Keyframe"],
    "keyframes": ["Keyframe"],
    "f-curve": ["FCurve"],
    "fcurve": ["FCurve"],
    "camera": ["Camera"],
    "sun lamp": ["SunLight"],
    "compositor": ["Scene.compositing_node_group", "Scene.use_nodes"],
    "compositing": ["Scene.compositing_node_group", "Scene.use_nodes"],
}
ALWAYS = [("RenderSettings", ["engine"]), ("ImageFormatSettings", ["file_format", "media_type"])]

TREE_WORDS = re.compile(r"(?:geometry|shader|compositor|texture)\s+nodes?$", re.I)  # a tree, not a node
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|[A-Z]+|\d+")
_STYPE = re.compile(r"\d+[A-Z]?|[A-Z][a-z]+|[A-Z]+(?![a-z])|[a-z]+")
_IDENT = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_QUOTED = re.compile(r"""['"]([^'"\n]{2,60})['"]""")
_OP = re.compile(r"\bbpy\.ops\.([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)")
_WORD = re.compile(r"\w+", re.U)  # words() of check_overlap (helper-model/tools/check_overlap.py), lower-cased
_index = {}  # id(facts) -> (facts, index): built once per Facts
_notes = None  # [(label, n, shingles)] of the fixed notes, built on first use (assigned whole: seeds run in threads)


# ---------------------------------------------------------------- the notes

class Tell(str):
    """A plain failure line (a gate's tell line, the validator's message) with the content of the failed candidate
    it describes (own), as task._failures pairs them; a str everywhere else. echoed_note leaves out of the line's runs
    every run own holds: that candidate passed the echo check, so what the line quotes from it (its handoff's
    provides names, the symbols it says it defines) is the model's, not ours. A provides line naming five objects
    shares an 8-word run with the tell line that quotes it, so without the pairing a retry that fixed the code and
    kept its handoff would be dropped as "extra" whenever the request didn't give those names itself (no tell line of
    the smoke's quoted that many)."""

    def __new__(cls, text, own=""):
        line = super().__new__(cls, text)
        line.own = own or ""
        return line


def hints_for(plan, i, mode, facts, failures=()) -> str:
    """The teacher's notes for step i of a cleaned plan in its worker mode ("blender", "python-script", "files",
    "section"). facts: an rna_lint.Facts, or None for no API facts. failures: lint findings (rna_lint's dicts),
    crashes (Go's workerCrash dicts) or plain lines (a gate's "tell", a section's reasons), from earlier candidates
    for this step, listed under FAILED_ON in every mode."""
    lines = [FORMAT_NOTE]
    failures = list(failures or ())
    told = failure_lines(failures, mode)
    if mode == "files":
        lines.append(FILES_NOTE)
    if mode == "section":
        from datagen import prose_gate
        st = plan["steps"][i]
        lines += [SECTION_GIVEN_NOTE if prose_gate.unread_heading(st) else SECTION_NOTE,
                  "## " + prose_gate.section_heading(st)]
        band = prose_gate.note_band(st)
        if band and band[1] is None:
            lines.append(LENGTH_MIN_NOTE.format(low=band[0]))
        elif band and band[0] == 0:
            lines.append(LENGTH_MAX_NOTE.format(high=band[1]))
        elif band:
            lines.append(LENGTH_NOTE.format(low=band[0], high=band[1]))
        ends = tuple(prose_gate.framing_checks(plan, i))
        if ends:
            note = FRAMING_OTHERS_NOTE if prose_gate.framed_elsewhere(plan, i, ends) else FRAMING_NOTE
            lines.append(note.format(ends=FRAMING_ENDS[ends]))
    if mode == "blender":
        lines += [BLENDER_NOTE, *BLENDER_HABITS, VERSIONS_NOTE]
        if values_step(plan, i):
            lines.append(VALUES_NOTE.format(sid="s%d" % (i + 1)))
        elif len(plan["steps"]) > 1:  # a lone step has no handoff (Chimera's Lone: one step)
            lines.append(HANDOFF_NOTE)
        lines += step_notes(plan, i, failures)
    if told:
        lines.append(FAILED_ON)
        lines.extend("- " + t for t in told)
    if mode == "blender" and facts is not None:
        st = plan["steps"][i]
        lines.append(blender_facts((st.get("title") or "") + "\n" + (st.get("instructions") or ""), facts, failures))
    return "\n".join(lines)


def values_step(plan, i) -> bool:
    """Whether step i of a cleaned plan defines values that later steps use, so its notes say how ctx hands them on
    (VALUES_NOTE): its title opens with define, declare or specify and names variables, dimensions, settings, colours
    and the like (VALUES_TITLE: "Define variables and render settings", "Define dimensions, colours, and scene
    settings"), or it is the script's header (HEADER_TITLE: "Script Header & Imports"), and some step depends on it
    (planinfo.user_names). The title only, and no "set": on the 770 distinct Blender steps of the helper's raw plans
    and the three smoke runs it finds 10, 8 by their title and 2 header steps, every one a values-first step with
    dependents; blender_gate's broader _VARIABLES_STEP finds 12, 4 of them "Set (up) ... render settings" steps that
    make or apply things, and reading the instructions too would add 5 steps with dependents, none of them values-only
    (whole scripts that define constants on the way, a node group "as defined in the variables")."""
    title = plan["steps"][i].get("title") or ""
    return bool(VALUES_TITLE.search(title) or HEADER_TITLE.search(title)) and bool(planinfo.user_names(plan, i))


def step_notes(plan, i, failures=()):
    """The notes a Blender step's own words, or its earlier tries' failures, call for (Nov 5, after the fourth smoke):
    CAMERA_NOTE when it adds a camera of its own (blender_gate.asks_camera), OUTPUT_NOTE when it asks Chimera to
    render or save (blender_gate.asked_outputs), then the API facts it names (api_facts), in BLENDER5's order."""
    from datagen import blender_gate  # it imports this module
    out = []
    if blender_gate.asks_camera(plan, i):
        out.append(CAMERA_NOTE)
    asked = blender_gate.asked_outputs(plan, i)
    if asked["blend"] or asked["render"]:
        out.append(OUTPUT_NOTE.format(sid="s%d" % (i + 1)))
    st = plan["steps"][i]
    return out + [f["note"] for f in api_facts((st.get("title") or "") + "\n" + (st.get("instructions") or ""),
                                               failures)]


def api_facts(text, failures=()):
    """BLENDER5's facts for a step's text and its failures: those whose words the text has (and, for one with
    "also", that too), and those an earlier try's failure hits (its "fails" pattern, or one of its fixes'), on the
    failure's text (_failure_text: a lint finding's message and name, a crash's source and error, a plain line)."""
    said = [_failure_text(f) for f in failures or ()]
    out = []
    for fact in BLENDER5:
        hit = fact["words"].search(text or "") and (fact.get("also") is None or fact["also"].search(text or ""))
        pats = ([fact["fails"]] if fact.get("fails") else []) + [rx for rx, _ in fact["fixes"]]
        if hit or any(rx.search(s) for rx in pats for s in said):
            out.append(fact)
    return out


def fix_for(f):
    """The fix a Blender failure line ends with (BLENDER5's first whose pattern its text hits: the replacement for a
    name the fourth smoke's tries kept using), or "". _line asks it only in Blender mode: a code step's crash in its
    own import_svg is no Blender name."""
    text = _failure_text(f)
    for fact in BLENDER5:
        for rx, fix in fact["fixes"]:
            if rx.search(text):
                return fix
    return ""


def teacher_copy(messages, hints) -> list:
    """A copy of messages with the hints added to the system message under HEAD (a system message is put first if
    there is none). The messages passed in are left as they are: they are the stored training request."""
    out = [dict(m) for m in messages or ()]
    if not hints:
        return out
    note = HEAD + "\n" + hints
    for m in out:
        if m.get("role") == "system":
            m["content"] = (m.get("content") or "").rstrip("\n") + "\n\n" + note
            return out
    return [{"role": "system", "content": note}] + out


def failure_lines(failures, mode="blender"):
    """One short line per failure, once each, the newest FAILURES_KEEP of them in the order they came (a line said
    again counts where it was said last): "line 12: error: <lint message>"; for a crash "line 30 in build_s2:
    <source>: <exception> (the newer Blender)"; a plain string as it is. Blender versions are put in words
    (unversioned). The newest, since failures come oldest first (each batch's after the last) and the later lines are
    the ones a gate's tell lines add: keeping the first six, 13 of the 146 lines the second smoke run's newest batches
    gave were left out of the next batch's notes, in 5 of its 75 later batches (4 steps); keeping the newest, 4, in 1.
    In the first smoke run 75 of 347 against 45 (19 batches against 9). Keeping the tell lines first instead left
    out about as many as today (13 and 74). A repair passes its own crash and lint last (task.Round.repair), so its
    crash stays listed (in all 10 stored repairs; passed first, as it was before, the newest six would have left it
    out of 2). mode: the step's worker mode; only a Blender step's lines end with a fix (fix_for)."""
    return [line for line, _ in _kept(failures, mode)]


def _line(f, mode="blender"):
    """failure_lines' line for one failure ("" when it says nothing): at most FAILURE_CHARS, cut at the end, and in
    Blender mode with its fix (fix_for) after it, the line cut before the fix to make room. A gate's tell line of
    silent's hidden-error forms, whose end says what the piece's own except did and what to do, keeps that end: its
    quoted error and then its source are cut instead (silent.refit), in up to silent.TELL_CHARS with the fix (the
    independent checks, Nov 6: cutting its end took away the instruction the fix belongs to)."""
    if isinstance(f, dict) and "message" in f:
        t = f"line {f.get('line') or '?'}: {f.get('level', 'error')}: {f['message']}"
    elif isinstance(f, dict):
        where = f.get("function") or ("SETTINGS_" + f["step"] if f.get("part") == "settings" and f.get("step")
                                      else f.get("part") or "")
        t = f"line {f.get('piece_line') or f.get('line') or '?'}" + (f" in {where}" if where else "") + \
            (f": {f['source']}" if f.get("source") else "") + (f": {f['error']}" if f.get("error") else "") + \
            (f" ({f['runner']})" if f.get("runner") else "")
    else:
        t = str(f)
    t = unversioned(" ".join(t.split()))
    fix = fix_for(f) if t and mode == "blender" else ""
    if fix and fix not in t:  # the replacement for a name the fourth smoke's tries kept using (BLENDER5)
        tail = "; " + fix
        if len(t) + len(tail) > FAILURE_CHARS:
            from datagen import silent  # it imports this module
            fit = None if isinstance(f, dict) else silent.refit(t, silent.TELL_CHARS - len(tail))
            if fit is not None:
                return fit + tail
            t = t[:FAILURE_CHARS - len(tail) - 1] + "…"
        return t + tail
    if len(t) > FAILURE_CHARS:
        t = t[:FAILURE_CHARS - 1] + "…"
    return t


def _kept(failures, mode="blender"):
    """[(line, failure)] of the lines failure_lines lists: each line once, at its last failure, the newest
    FAILURES_KEEP in order."""
    last = {}
    for f in failures or ():
        t = _line(f, mode)
        if t:
            last.pop(t, None)  # said again: it moves to where it was said last
            last[t] = f
    return list(last.items())[-FAILURES_KEEP:]


def _failure_text(f):
    if isinstance(f, dict):
        return "\n".join(str(f.get(k) or "") for k in ("message", "name", "source", "error", "function", "critique"))
    return str(f)


def teacher_lines(mode, failures, sent=()):
    """What of the failures hints_for lists (failure_lines' newest FAILURES_KEEP lines, each at its last failure) only
    the teacher sees, for echoed_note's extra, in every mode but a section's: each lint finding's message, each crash's
    error and each plain line (a gate's "tell"), as the notes word them (unversioned). A crash's source line is the
    model's own code, and a crash in sent (the one a repair request shows), or another with the same error, is in
    Chimera's own request, so neither counts. A plain line paired with its candidate (Tell) stays paired, so
    echoed_note can leave that candidate's own words out. A section's lines give none: what they quote is not ours
    (the model's own framing phrases and the judge's words, which quote the model and the step back), and their fixed
    wording is among echoed_note's own notes, so as extra they would only drop a next try that keeps the model's own
    words."""
    if mode == "section":
        return []
    out = []
    sent_errors = {s.get("error") for s in sent or () if isinstance(s, dict) and "message" not in s} - {None}
    for _, f in _kept(failures, mode):
        if f in sent or (isinstance(f, dict) and "message" not in f and f.get("error") in sent_errors):
            continue
        text = (f["message"] if "message" in f else f.get("error")) if isinstance(f, dict) else str(f)
        if text:
            out.append(Tell(unversioned(text), f.own) if isinstance(f, Tell) else unversioned(text))
    return out


def runs(text, n=NOTE_N):
    """text's runs of n words in check_overlap's words()."""
    w = _WORD.findall((text or "").lower())
    return {tuple(w[k:k + n]) for k in range(len(w) - n + 1)}


def _shingles(text, n=NOTE_N):
    """(n, shingles): text's runs of n words in check_overlap's words(), or the whole text as one run when it is
    shorter (NOTE_MIN words at least; else no runs)."""
    w = _WORD.findall((text or "").lower())
    if len(w) < NOTE_MIN:
        return n, set()
    n = min(n, len(w))
    return n, runs(text, n)


def echoed_note(text, extra=(), request=""):
    """A short label when text repeats one of the teacher's notes, which are ours (Claude-written) and never in
    Chimera's request: a run of NOTE_N words (any case and punctuation, as check_overlap reads text) of HEAD,
    FORMAT_NOTE, FILES_NOTE, BLENDER_NOTE, HANDOFF_NOTE (label "handoff_note"), BLENDER_HABITS and CAMERA_NOTE,
    VERSIONS_NOTE, VALUES_NOTE's fixed parts
    (VALUES_FORMS, the words between the step's SETTINGS_ and build_ names) and the note filled for s1 to s8
    (VALUES_FILLED, PLAN_STEPS), OUTPUT_NOTE's the same way (OUTPUT_FORMS, OUTPUT_FILLED), BLENDER5's facts and fixes,
    the facts header, FAILED_ON (a note shorter than NOTE_N
    words counts as a whole), the notes earlier runs gave (RETIRED), the section notes
    (SECTION_NOTE, SECTION_GIVEN_NOTE, LENGTH_TAIL, both wordings of FRAMING_NOTE), the fixed wording of a dropped
    section's lines (task.py's HEADING_FAILED, FRAMING_FAILED and _SECTION_WHY, prose_gate.TELL_NOTES) and of the
    gates' tell lines (dep_honesty.TELL_FORMS, layout.TELL_FORMS, blender_gate.TELL_FORMS: a failed dependency
    claimed, a file imported from where the project doesn't put it, an output or camera not handed over; and
    silent.MISSED_FORMS, attr_miss's line), the judges'
    lines about the format and the goal (judges.HEADING_LINE, HANDOFF_HEAD, GOAL_HEAD, TESTS_GOAL_HEAD), whose words
    a grader's problem can carry into the notes, or a string of extra (teacher_lines, say); else None. Of extra, a
    run that request (Chimera's request, as precheck passes it) holds too is Chimera's words, not ours, and one with
    NUMERIC_RUN numeric words is mostly a size or a count, so neither counts: a size line quotes the step's own triple
    ("sofa_length=2.2, sofa_width=0.9 ... in s1"), and a retry that copies those values, or says "The island
    measures 2.4 × 0.9 × 0.92 m", does what it was asked (1 of the 6 tries of the three steps whose size check fired
    on the smoke's replies was dropped for it). Nor does a run of a Tell line that its own failed candidate holds:
    those words are the model's (a provides line of five names the tell line quotes back). A version the notes no
    longer name is version_leak's, their words for it notes_leak's."""
    global _notes
    if _notes is None:
        from datagen import blender_gate, dep_honesty, judges, layout, prose_gate, silent, task
        tells = [form for mod in (dep_honesty, layout, blender_gate) for form in mod.TELL_FORMS] + \
            list(silent.MISSED_FORMS)
        _notes = [(label,) + _shingles(note) for label, note in [
            ("head", HEAD), ("format_note", FORMAT_NOTE), ("files_note", FILES_NOTE), ("blender_note", BLENDER_NOTE),
            ("handoff_note", HANDOFF_NOTE)] +
            [("blender_habit", note) for note in BLENDER_HABITS + (CAMERA_NOTE,)] + [
            ("versions_note", VERSIONS_NOTE)] + [("values_note", part) for part in VALUES_FORMS + VALUES_FILLED] +
            [("output_note", part) for part in OUTPUT_FORMS + OUTPUT_FILLED] +
            [("blender_fact", fact["note"]) for fact in BLENDER5] +
            [("blender_fact", fix) for fact in BLENDER5 for _, fix in fact["fixes"]] + [
            ("facts_head", facts_head(list(blenders.VERSIONS))),
            ("failed_on", FAILED_ON), *RETIRED,
            ("section_note", SECTION_NOTE), ("section_note", SECTION_GIVEN_NOTE), ("length_note", LENGTH_TAIL)] +
            [("framing_note", note.format(ends=e)) for note in (FRAMING_NOTE, FRAMING_OTHERS_NOTE)
             for e in FRAMING_ENDS.values()] +
            [("failure_line", line) for line in [task.HEADING_FAILED, task.FRAMING_FAILED] +
             list(task._SECTION_WHY.values()) + list(prose_gate.TELL_NOTES) + tells] +
            [("judge_line", line) for line in (judges.HEADING_LINE, judges.HANDOFF_HEAD, judges.GOAL_HEAD,
                                               judges.TESTS_GOAL_HEAD)]]
    asked, own = {}, {}  # n -> request's runs of n words; (candidate text, n) -> its runs
    notes = _notes + [("extra",) + _extra_runs(x, request, asked, own) for x in extra or ()]
    w = _WORD.findall((text or "").lower())
    have = {}  # n -> text's runs of n words
    for label, n, sh in notes:
        if not sh:
            continue
        if n not in have:
            have[n] = {tuple(w[k:k + n]) for k in range(len(w) - n + 1)}
        if have[n] & sh:
            return label
    return None


def _extra_runs(text, request, asked, own=None):
    """(n, runs) of one extra line for echoed_note: _shingles', less those request holds too (asked caches request's
    runs by n), those the failed candidate of a Tell line holds (own caches its runs by text and n) and those mostly
    numbers (NUMERIC_RUN words that start with a digit: 2, 92m, 1080p)."""
    n, sh = _shingles(text)
    if sh and request:
        if n not in asked:
            asked[n] = runs(request, n)
        sh = sh - asked[n]
    mine = getattr(text, "own", "")
    if sh and mine:
        own = {} if own is None else own
        if (mine, n) not in own:
            own[(mine, n)] = runs(mine, n)
        sh = sh - own[(mine, n)]
    return n, {r for r in sh if sum(1 for x in r if x[:1].isdigit()) < NUMERIC_RUN}


def notes_leak(reply, request_text):
    """"notes_leak" when reply uses the notes' own words for the Blenders the script is checked in, or for the checks
    (NOTES_WORDS: a facts mark "[newer only]", "the older Blender", "both Blenders", "either Blender", "two Blender
    versions", "sandbox" and "sandboxed"), and request_text doesn't, else None. Only the teacher's notes say them:
    Chimera's request says "Blender 5.0 or newer" and never mentions a sandbox, so a reply that does ("# Thin Wall
    [newer only]: guard it", "assumed: forest.blend is absent in the sandbox") would teach the worker to cite what it
    was never told. Plain "newer Blender versions" is left alone, as models write it on their own. For Blender steps:
    no other mode's notes have these words."""
    text = request_text or ""
    for rx in NOTES_WORDS:
        if rx.search(reply or "") and not rx.search(text):
            return "notes_leak"
    return None


# ---------------------------------------------------------------- versions

_VER = r"\d+\.\d+(?:\.\d+)?(?:\+|\.x)?"  # 5.2, 5.2.2, 5.0+, 5.x isn't one
_CMP = r"(?:[<>≥≤]=?\s*|=\s*)?"
_SEP = r"\s*(?:/|&|,|[-‐‑‒–—]|\bto\b|\band\b|\bor\b|\bvs\.?)\s*"
# a version list that "Blender" starts: "Blender 5.0 / 5.2", "Blender v5.2+", "Blender >= 5.0, 5.1 and 5.2"
_AFTER_BLENDER = re.compile(r"\bblender['’]?s?\s*(?:v(?:ersions?)?\.?\s*|versions?\s+)?" + _CMP + "(" + _VER +
                            "(?:" + _SEP + _CMP + _VER + ")*)", re.I)
# two versions or more on their own, joined as a range or a choice ("both 5.0 and 5.2", "5.0‑5.2"), never by a
# spaced ASCII minus, a slash or a comma, which join floats in code (5.2 - 5.0, 5.0/5.2, (5.0, 5.2))
_BARE_SEP = r"(?:\s+(?:and|or|to|vs\.?|&)\s+|\s*[‐‑‒–—]\s*|-)"
_BARE = re.compile(r"(?<![\w.])(" + _VER + "(?:" + _BARE_SEP + _VER + r")+)(?![\w.]*\d)")


def _token(v):
    """A regex for v as a version on its own: not inside 15.2.2, 5.2.21 or 5.2.2.1."""
    return re.compile(r"(?<![\d.])" + re.escape(v) + r"(?!\d|\.\d)")


def _minor(v):
    return ".".join(v.split(".")[:2])


def versions_named(text, versions=None) -> set:
    """The Blender versions of versions (tools.blenders.VERSIONS) text names, each as written: a full version
    anywhere ("5.2.2"), a major.minor ("5.2") only where it reads as a version, after "Blender" or in a list of two
    or more ("between 5.0 and 5.2"), since 5.0 and 5.2 are also floats in code."""
    vs = list(versions or blenders.VERSIONS)
    out = {v for v in vs if _token(v).search(text or "")}
    minors = {_minor(v) for v in vs}
    for rx in (_AFTER_BLENDER, _BARE):
        for m in rx.finditer(text or ""):
            items = [re.sub(r"(?:\+|\.x)$", "", x) for x in re.findall(_VER, m.group(1))]
            out.update(x for x in items if x in minors)
    return out


def version_leak(reply, request_text, versions=None):
    """"version_leak" when reply names a Blender version of versions (tools.blenders.VERSIONS), or its major.minor
    (versions_named), that request_text doesn't contain, else None. Only the teacher's notes ever carried the checks'
    versions (Chimera's request says "Blender 5.0 or newer", a repair's also the Blender that crashed), so a reply
    naming one would teach the worker to cite what it was never told: 4 of qwen3.8's 13 targets in the smoke run did
    ("safe for Blender 5.0.1 & 5.2.2", "Blender 5.0 / 5.2 renamed ..."). The request is read loosely: a major.minor
    counts as there when any version of it is ("5.2" in "5.2.2"), and a float of the same digits counts too. For
    Blender steps: elsewhere the notes name no Blender, and "Django==5.0.1" or "5.0-5.2 GHz" is no leak."""
    text = request_text or ""
    for v in sorted(versions_named(reply, versions)):
        here = _token(v).search(text) if v.count(".") > 1 else \
            re.search(r"(?<![\d.])" + re.escape(v) + r"(?!\d)", text)
        if not here:
            return "version_leak"
    return None


def unversioned(text, versions=None) -> str:
    """text with the Blender versions of versions (tools.blenders.VERSIONS, the newest first) in words, as the facts'
    marks put them: "Blender 5.2.2 or 5.0.1" is "either Blender" ("and": "both Blenders"), "Blender 5.2.2" or a bare
    5.2.2 "the newer Blender", 5.0.1 "the older Blender", and a major.minor after "Blender" ("Blender 5.2") the
    version's word too (a bare 5.2 may be a float). For the failure lines (rna_lint's messages, a crash's runner,
    Blender's and Chimera's text a gate's tell line quotes) in the teacher's notes."""
    vs = list(versions or blenders.VERSIONS)
    if not text or not vs:
        return text
    alt = "|".join(re.escape(v) for v in vs)
    text = re.sub(rf"(?:\b(?:both|either) )?\bBlender (?:{alt}) (or|and) (?:{alt})(?!\d|\.\d)",
                  lambda m: "either Blender" if m.group(1) == "or" else "both Blenders", text)
    text = re.sub(rf"(?:\bBlender )?(?<![\d.])({alt})(?!\d|\.\d)", lambda m: f"the {_word(m.group(1), vs)} Blender",
                  text)
    minors = {}
    for v in vs:
        minors.setdefault(_minor(v), v)
    alt = "|".join(re.escape(m) for m in minors)
    return re.sub(rf"\bBlender ({alt})(?!\d|\.\d)", lambda m: f"the {_word(minors[m.group(1)], vs)} Blender", text)


# ---------------------------------------------------------------- what a text names

def _words(name):
    return " ".join(w.lower() for w in _CAMEL.findall(name))


def _phrase(text, tail=""):
    """A regex for a phrase as words: any case, any spacing, not inside a longer word."""
    return re.compile(r"(?<![\w-])" + r"\s+".join(re.escape(p) for p in text.split()) + tail + r"(?![\w-])", re.I)


def index(facts):
    """What matching needs, built once per Facts: node labels by tree, class names, the compiled phrases."""
    hit = _index.get(id(facts))
    if hit is not None and hit[0] is facts:
        return hit[1]
    labels = {}  # label -> [(tree, idname)]
    for v in facts.versions:
        for tree in TREES:
            for idname, n in (facts.dumps[v]["nodes"].get(tree) or {}).items():
                if (tree, idname) not in labels.setdefault(n["label"], []):
                    labels[n["label"]].append((tree, idname))
    classes, bases = set(), set()
    for v in facts.versions:
        for c, k in facts.dumps[v]["classes"].items():
            classes.add(c)
            bases.add(k["base"])
    legacy = facts.subclasses("Texture")
    multi, single = [], []
    for label, where in labels.items():
        if len(re.findall(r"[A-Za-z0-9]+", label)) >= 2:
            multi.append((_phrase(label), where))
        else:
            single.append((_phrase(label, r"\s+nodes?"), re.compile(
                r"\b(?:compositor|compositing)\s+" + re.escape(label) + r"(?![\w-])", re.I), where))
    phrases = []  # (regex, class) for classes named in words
    for c in sorted(classes):
        if c.startswith(NODE_PREFIXES) or c in facts.node_ids or c in bases or c in TOO_WIDE or c in legacy:
            continue
        words = _words(c)
        if len(words.split()) >= 2 and not any(ch.isdigit() for ch in words):
            phrases.append((_phrase(words), c))
    idx = {"labels": labels, "multi": multi, "single": single, "classes": classes, "phrases": phrases,
           "aliases": [(_phrase(a), targets) for a, targets in ALIASES.items()],
           "trees": {t: re.compile(rx, re.I) for t, rx in TREES.items()}}
    _index[id(facts)] = (facts, idx)
    return idx


def mentions(text, facts, failure=False):
    """What text names, as {key: [count, first position]}; keys are ("node", idname), ("class", name),
    ("prop", "Class.attr") and, in a failure's text, ("op", "group.name"). failure: also a quoted label, an
    operator, and a one-word class as Python's errors and the lint name it ('Mesh' object has no attribute ...,
    Mesh has no attribute ...)."""
    idx = index(facts)
    text = text or ""
    trees = {t for t, rx in idx["trees"].items() if rx.search(text)}
    hits = []  # (start, end, [keys], how)

    def nodes(where, only=None):
        if only is not None:
            where = [w for w in where if w[0] == only]
        elif len({t for t, _ in where}) > 1 and trees & {t for t, _ in where}:
            where = [w for w in where if w[0] in trees]  # a label several trees share: the trees the step names
        return [("node", i) for i in dict.fromkeys(i for _, i in where)]
    for m in _IDENT.finditer(text):
        w = m.group(0)
        if w in facts.node_ids:
            hits.append((m.start(), m.end(), [("node", w)], "ident"))
        elif w in idx["classes"] and w not in TOO_WIDE and not w.startswith("NodeSocket"):
            several = len(_CAMEL.findall(w)) >= 2
            typed = text[max(0, m.start() - 10):m.start()] == "bpy.types."
            quoted = failure and m.start() > 0 and text[m.start() - 1] in "'\"" and \
                text[m.end():m.end() + 8] in ("' object", '" object')
            lint = failure and text[m.end():m.end() + 8] == " has no "
            if several or typed or quoted or lint:
                hits.append((m.start(), m.end(), [("class", w)], "ident"))
    for rx, where in idx["multi"]:
        for m in rx.finditer(text):
            if not re.match(r"\s+modifiers?\b", text[m.end():], re.I):  # "Subdivision Surface modifier": the modifier
                hits.append((m.start(), m.end(), nodes(where), "label"))
    for rx, rx_comp, where in idx["single"]:
        hits.extend((m.start(), m.end(), nodes(where), "word") for m in rx.finditer(text)
                    if not TREE_WORDS.match(m.group(0)))
        hits.extend((m.start(), m.end(), nodes(where, "CompositorNodeTree"), "qualified")
                    for m in rx_comp.finditer(text))
    if not failure:  # words in Python's error messages aren't names ("operator properties")
        for rx, c in idx["phrases"]:
            hits.extend((m.start(), m.end(), [("class", c)], "words") for m in rx.finditer(text))
        for rx, targets in idx["aliases"]:
            keys = [("prop", t) if "." in t else ("class", t) for t in targets]
            hits.extend((m.start(), m.end(), keys, "words") for m in rx.finditer(text))
    else:
        for m in _QUOTED.finditer(text):
            if m.group(1) in idx["labels"]:
                hits.append((m.start(1), m.end(1), nodes(idx["labels"][m.group(1)]), "label"))
        hits.extend((m.start(), m.end(), [("op", m.group(1) + "." + m.group(2))], "ident") for m in _OP.finditer(text))
    found = {}
    for a, b, keys, how in hits:
        # a match inside a longer one is part of that name ("surface modifier" in "Subdivision Surface modifier"),
        # but "compositor glare" names the compositor too; and a one-word label that a longer label overlaps is that
        # label's ("Value node" in "Random Value node")
        if any((a2 <= a and b <= b2 and (b2 - a2) > (b - a) and how2 != "qualified") or
               (how in ("word", "qualified") and how2 == "label" and a2 < b and a < b2) for a2, b2, _, how2 in hits):
            continue
        for key in keys:
            if key in found:
                found[key][0] += 1
                found[key][1] = min(found[key][1], a)
            else:
                found[key] = [1, a]
    return found


# ---------------------------------------------------------------- the facts, written out

def _word(v, versions):
    """What the notes call version v of versions (the newest first): "newer" for the first, "older" for the last
    ("middle" between them), never its number (version_leak)."""
    k = list(versions).index(v)
    return "newer" if k == 0 else "older" if k == len(versions) - 1 else "middle"


def _mark(have, versions):
    """"" when every one of versions has it, else " [newer only]" or " [older only]" (those that do)."""
    if all(v in have for v in versions):
        return ""
    return " [" + ", ".join(_word(v, versions) for v in versions if v in have) + " only]"


def _merge(per_version, versions):
    """The items of several versions' lists, the first version's order first: [(item, {versions that have it})]."""
    order, have = [], {}
    for v in versions:
        for x in per_version.get(v) or ():
            if x not in have:
                order.append(x)
                have[x] = set()
            have[x].add(v)
    return [(x, have[x]) for x in order]


def _stype(t):
    t = t[len("NodeSocket"):] if t.startswith("NodeSocket") else t
    return " ".join(w.lower() for w in _STYPE.findall(t)) or t


def _sockets(facts, idname, side):
    """A node's sockets on one side, each "Name [type]", with its identifier when that differs and marks: the settings
    that show one a fresh node hides (_shown: "W [float] (with noise_dimensions 1D or 4D)") and the versions that have
    it. A socket no script can reach is left out (tools.rna_lint.usable on Facts.node's entry, the lint's own rule:
    in 5.2.2 and 5.0.1 the Weight input of 22 shader nodes, which inputs["Weight"] never finds whatever the script
    sets): the facts gave "Weight [float]" on the Principled BSDF, Emission, Glass and the other shaders, and both
    stored replies that read it (on Subsurface Scattering) crashed with KeyError in real Blender. A dump from before
    availability (three fields, no reveal) gives what it gave."""
    per, types, hidden = {}, {}, {}
    for v in facts.versions:
        n = facts.node(idname, v)
        if n is None:
            continue
        per[v] = []
        reveal = (n.get("reveal") or {}).get(side) or {}
        for s in n[side]:
            if not rna_lint.usable(n, side, s):
                continue
            key = (s[0], s[1])
            per[v].append(key)
            types.setdefault(key, {})[v] = s[2] if len(s) > 2 else ""
            if len(s) > 3 and not s[3] and s[0] in reveal:
                hidden.setdefault(key, {})[v] = reveal[s[0]]
    vs = list(per)
    out = []
    for (name, ident), have in _merge(per, vs):
        label = name if ident in (name, "") else f'{name} (or "{ident}")'
        ts = types[(name, ident)]
        first = next(ts[v] for v in vs if v in ts)
        other = [f"{_stype(ts[v])} in the {_word(v, vs)}" for v in vs if v in ts and ts[v] != first]
        if first:
            label += " [" + "; ".join([_stype(first)] + other) + "]"
        out.append(label + _shown(hidden.get((name, ident)), have, vs) + _mark(have, vs))
    return out


def _shown(hidden, have, versions):
    """" (with ...)" for a socket a fresh node hides, from the settings tools/rna_dump_blender.py measured to show its
    name (a node's "reveal"; hidden: {version: those settings}), as the first of versions that hides it gives them:
    one property's values together ("noise_dimensions=1D", "noise_dimensions=4D": "noise_dimensions 1D or 4D"), a
    pair as "mode END_POINTS and count_mode RESOLUTION", all joined with " or " ("sky_type PREETHAM or HOSEK_WILKIE or
    sun_disc False"); " in the older" (newer) after them when another version that has it (have) shows it on a fresh
    node (5.0.1's String to Curves hides Text Box Height until overflow is SCALE_TO_FIT or TRUNCATE, 5.2.2's
    doesn't). "" for a socket no version hides, or one hidden only where another of its name shows (Mix's A_Color:
    inputs["A"] is A_Float on a fresh node)."""
    if not hidden:
        return ""
    groups = {}  # a property -> its values; a pair's text -> None
    for setting in hidden[next(v for v in versions if v in hidden)]:
        if "&" in setting:
            groups[" and ".join(p.replace("=", " ", 1) for p in setting.split("&"))] = None
        else:
            prop, _, value = setting.partition("=")
            groups.setdefault(prop, []).append(value)
    text = " or ".join(k if vals is None else k + " " + " or ".join(vals) for k, vals in groups.items())
    if any(v not in hidden for v in versions if v in have):
        text += " in the " + " and the ".join(_word(v, versions) for v in versions if v in hidden)
    return f" (with {text})"


def _chain(facts, cls, v, stop=True):
    """cls and its bases in v, up to the first of STOP_BASES (stop) or to the root."""
    classes = facts.dumps[v]["classes"]
    out, c = [], cls
    while c and c in classes and c not in out and (c == cls or not stop or c not in STOP_BASES):
        out.append(c)
        c = classes[c]["base"]
    return out


def _enum(facts, cls, attr, v):
    """(values, others) of an enum property in v: the values measured on a live instance (in their order) and the
    static values a live instance didn't take in its state; the static values alone when nothing was measured.
    None when it isn't an enum there."""
    p = facts.prop(cls, attr, v)
    if not p or p.get("type") != "ENUM":
        return None
    static = list(p.get("items") or [])
    d = facts.dumps[v]
    for c in _chain(facts, cls, v, stop=False):
        if f"{c}.{attr}" in (d.get("dynamic_enums") or {}):  # its static items are only a placeholder
            return list(d["dynamic_enums"][f"{c}.{attr}"]), []
        live = (d.get("live_enums") or {}).get(f"{c}.{attr}")
        if live and not p.get("flag"):
            return list(live), [x for x in static if x not in live]
    return static, []


def _prop_text(facts, cls, attr, versions):
    """One property: its name, with its enum values and differences marked."""
    vals, others = {}, {}
    for v in versions:
        e = _enum(facts, cls, attr, v)
        if e is not None:
            vals[v], others[v] = e
    if not vals or not any(vals.values()):
        return attr
    vs = list(vals)
    text = ", ".join(x + _mark(h, vs) for x, h in _merge(vals, vs))
    rest = [x + _mark(h, vs) for x, h in _merge(others, vs) if not any(x in vals[v] for v in vs)]
    if rest:
        text += "; in another state also " + ", ".join(rest)
    return f"{attr} ({text})"


def _class_entry(facts, cls):
    vs = facts.versions
    have = [v for v in vs if cls in facts.dumps[v]["classes"]]
    if not have:
        return ""
    parts, seen = [], set()
    for owner in _chain(facts, cls, have[0]):
        per = {v: sorted(facts.dumps[v]["classes"][owner]["props"]) for v in have if owner in facts.dumps[v]["classes"]}
        attrs = [(a, h) for a, h in _merge(per, have) if a not in seen and a != "rna_type"]
        seen.update(a for a, _ in attrs)
        if attrs:
            text = ", ".join(_prop_text(facts, owner, a, [v for v in vs if v in h]) + _mark(h, have) for a, h in attrs)
            parts.append(text if owner == cls else f"from {owner}: {text}")
    return f"- {cls}{_mark(have, vs)}: " + "; ".join(parts) if parts else ""  # nothing to say: no line


def _node_entry(facts, idname):
    vs = facts.versions
    have = [v for v in vs if facts.node(idname, v) is not None]
    if not have:
        return ""
    n = facts.node(idname, have[0])
    parts = [f"inputs: {', '.join(_sockets(facts, idname, 'inputs')) or 'none'}",
             f"outputs: {', '.join(_sockets(facts, idname, 'outputs')) or 'none'}"]
    per = {v: sorted(facts.dumps[v]["classes"][idname]["props"]) for v in have if idname in facts.dumps[v]["classes"]}
    props = [_prop_text(facts, idname, a, [v for v in vs if v in h]) + _mark(h, list(per))
             for a, h in _merge(per, list(per))]
    if props:
        parts.append("properties: " + ", ".join(props))
    dyn = " (some sockets are made at run time)" if n.get("dynamic") else ""
    return f"- node {n['label']} ({idname}){_mark(have, vs)}{dyn}: " + "; ".join(parts)


def _prop_entry(facts, ref):
    cls, _, attr = ref.partition(".")
    vs = facts.versions
    have = [v for v in vs if facts.prop(cls, attr, v) is not None]
    if not have:
        return ""
    p = facts.prop(cls, attr, have[0])
    if p.get("type") == "ENUM":
        return f"- {cls}.{_prop_text(facts, cls, attr, have)}{_mark(have, vs)}"
    kind = f"a {p['fixed']}" if p.get("fixed") else (p.get("type") or "").lower()
    return f"- {cls}.{attr}: {kind}{' (read-only)' if p.get('ro') else ''}{_mark(have, vs)}"


def _op_entry(facts, op):
    vs = facts.versions
    per = {v: sorted(facts.op_props(op, v)) for v in vs if facts.op_props(op, v) is not None}
    if not per:
        return ""
    keys = [k + _mark(h, list(per)) for k, h in _merge(per, list(per))]
    return f"- bpy.ops.{op}{_mark(list(per), vs)} keywords: {', '.join(keys) or 'none'}"


def _always(facts):
    out = []
    for cls, attrs in ALWAYS:
        vs = [v for v in facts.versions if cls in facts.dumps[v]["classes"]]
        texts = [_prop_text(facts, cls, a, vs) for a in attrs if any(facts.prop(cls, a, v) for v in vs)]
        if texts:
            out.append(f"- {cls}." + "; ".join(texts))
    return out


def entry(facts, key) -> str:
    """One fact line for a key of mentions() ("" when the dumps don't know it)."""
    kind, name = key
    return {"node": _node_entry, "class": _class_entry, "prop": _prop_entry, "op": _op_entry}[kind](facts, name)


def facts_head(versions) -> str:
    """The facts block's first line, for those versions (the newest first), without their numbers: the marks say
    which has a name (_word)."""
    if len(versions) < 2:
        return "Blender's own API facts for this step, printed by the Blender the script is checked in:"
    return ("Blender's own API facts for this step, printed by the Blender versions the script is checked in (a name "
            "marked [newer only] doesn't exist in the older one, one marked [older only] not in the newer one):")


def blender_facts(text, facts, failures=(), cap=FACTS_CAP) -> str:
    """The facts block for a step's text: what the failures name first (the newest failure's first, as failure_lines
    keeps the newest: a repair's own crash comes last in its failures), then what the text names, most-mentioned first
    (ties: the first named), then the engine and file-format values, which always fit. At most cap characters: entries
    that don't fit are left out and counted on the last line. Newest first, the entries the stored runs' newest batches
    named were left out 12 times in 125 later Blender batches, against 17 oldest first, and a repair's crash kept its
    entries in all 10 stored repairs."""
    named = mentions(text, facts)
    first = {}
    for k, f in enumerate(reversed(list(failures or ()))):
        for key, (_, pos) in mentions(_failure_text(f), facts, failure=True).items():
            first.setdefault(key, (k, pos))
    keys = sorted(first, key=lambda key: first[key])
    keys += sorted((key for key in named if key not in first), key=lambda key: (-named[key][0], named[key][1]))
    head = facts_head(facts.versions)
    tail = _always(facts)
    room = cap - len(head) - sum(len(t) + 1 for t in tail) - LEFT_OUT_ROOM
    body, left = [], 0
    for key in keys:
        e = entry(facts, key)
        if not e:
            continue
        if len(e) + 1 > room:
            if not body and room > 200:  # a first entry longer than the room is cut, not dropped
                e = e[:room - 2] + "…"
            else:
                left += 1
                continue
        body.append(e)
        room -= len(e) + 1
    lines = [head] + body + tail
    if left:
        lines.append(f"({left} more named in the step, left out for room)")
    return "\n".join(lines)
