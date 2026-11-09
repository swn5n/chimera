"""What the seed stage asks the teacher (gpt-oss:120b) to write about: topic labels, styles and lengths, and the
instructions it gets for writing seed requests.

Claude wrote these labels and instructions (DESIGN.md, "Rules that hold everywhere"). They steer the teacher and
are never training data: every seed text is the teacher's own, and seeds.py checks each one against the eval sets.

The labels are handed out in a fixed rotation, not drawn at random per call. The helper's 12 Blender seed calls
drew their areas at random and reached only 7 of its 18 (one area four times), so here the Blender labels are
ordered area by area: any ten calls in a row cover the plan's ten areas, and no label comes round again before all
the others have had a turn. Python's labels rotate the same way. Styles and lengths rotate on weighted cycles of
other lengths, so the pairs vary.
"""
from __future__ import annotations

from datagen.common import rng

TARGETS = ("blender", "python", "mixed")

# (area, labels): the plan's ten Blender areas (docs/hydra-worker-plan.md, "3. TRAINING DATA"), four labels each, so
# the rotation goes through the areas in the same order every ten calls. The subjects are left to the teacher; the
# labels name techniques, and none names a scene the eval uses.
BLENDER_AREAS = (
    ("modelling", (
        "furniture and household objects modelled from primitives with exact sizes",
        "simple architecture from code: buildings, walls with window openings, roofs and arches",
        "vehicles and machines from simple shapes: trains, carts, cranes, rockets, drones",
        "mechanical parts with exact dimensions: gears, bolts, pipes, brackets and hinges",
    )),
    ("modifiers", (
        "modifier stacks: array, mirror, bevel, solidify and subdivision surface together",
        "curve-based modelling: bevelled curves, pipes, cables, rails and screw or spin shapes",
        "boolean cut-outs and hard-surface props with clean shading",
        "deforming with modifiers: simple deform, lattice, wave, and displace driven by a procedural texture",
    )),
    ("geometry nodes from Python", (
        "a geometry nodes group built in Python, with its inputs exposed on the modifier",
        "geometry nodes patterns: grids, lines and circles of instances with per-instance variation",
        "parametric generators in geometry nodes driven by group inputs: tiles, panels, lattices, towers",
        "geometry nodes that animate: offsets, rotations or scales driven by the scene time",
    )),
    ("materials", (
        "procedural shader-node materials: wood grain, marble, brushed metal, fabric, terrazzo",
        "glass, liquids and see-through materials with the Principled BSDF's transmission and subsurface",
        "emission, glowing and colour-ramp gradient materials",
        "texture coordinates and mapping: object-space and generated patterns, checker, brick and wave textures",
    )),
    ("lighting", (
        "time-of-day lighting with a Sun light and a sky texture or world colour",
        "interior lighting with area, point and spot lights of set powers and colours",
        "world and atmosphere setups: gradient backgrounds, sky texture, volumetric fog",
        "animated lights: pulsing, colour-cycling or flickering, with keyframes or drivers",
    )),
    ("cameras and keyframes", (
        "camera moves: dolly, crane and orbit with a Track To constraint, and focus pulls with depth of field",
        "keyframed animation with f-curve interpolation, easing, cycles and seamless loops",
        "mechanical animation with drivers and constraints: pistons, clock hands, meshing gears",
        "several cameras and timeline markers for different shots in one scene",
    )),
    ("render and compositor", (
        "render settings: engine, samples, resolution, colour management, output format and path",
        "the Blender 5.x compositor built in Python: glare, blur, colour balance, lens distortion, vignette",
        "view layers, render passes and collections set up for compositing",
        "one script that sets up several named render variants: colour schemes, cameras or frame ranges",
    )),
    ("scatter", (
        "scattering objects on a surface from Python with a fixed random seed: crates, leaves, coins, debris",
        "geometry nodes scattering: points on faces, instancing a collection, random rotation and scale",
        "rings, spirals and grids of instances: stadium seats, city blocks, crowds of simple figures",
        "placing objects along a curve or path from Python: lamp posts along a road, beads on a wire, cars on a track",
    )),
    ("bmesh", (
        "bmesh modelling: building a mesh vertex by vertex and face by face",
        "bmesh operations from Python: extrude, inset, bevel, bridge and subdivide",
        "meshes from mathematical functions: surfaces, knots, spirals and wave patterns",
        "bmesh clean-up and queries: merging vertices, recalculating normals, deleting faces by a rule, face areas",
    )),
    ("simulations", (
        "rigid body simulations: stacks, domino runs, objects tumbling down a slope",
        "cloth and soft body: a flag in the wind, a tablecloth falling on a table, a cushion",
        "particle systems: emitters with lifetimes, velocities and instanced objects",
        "force fields acting on physics: wind, turbulence, vortex and changed gravity",
    )),
)

# Runnable programs a person asks for: standard library only, no network, no GUI, no one typing.
PYTHON_AREAS = (
    ("data", (
        "cleaning and summarising CSV or JSON data that the message pastes or the program generates",
        "a small sqlite3 database app: schema, inserts, queries and a printed report",
        "statistics from scratch on built-in sample data: averages, text histograms, a simple regression",
        "parsing log or event lines and reporting counts, rates and busy time windows",
    )),
    ("tools", (
        "a command-line tool with argparse sub-commands that keeps its data in a JSON file in its own folder",
        "a text-analysis tool: word counts, n-grams, readability scores or keyword extraction",
        "a converter between text formats: Markdown to HTML, CSV to JSON, INI to nested dictionaries",
        "a config or data validator that reports every problem with its line number",
    )),
    ("games and puzzles", (
        "a terminal game whose computer players play a whole game by themselves: cards, dice or a board game",
        "a puzzle solver: sudoku, mazes, word searches or sliding tiles",
        "board-game rules with an AI player that searches moves (minimax or Monte Carlo)",
    )),
    ("simulations and maths", (
        "a simulation with a fixed random seed: queues, traffic, an epidemic or an ecosystem",
        "finance maths: loan schedules, compound interest and savings plans, printed as tables",
        "physics or geometry calculations with a table of results: projectiles, orbits, areas and volumes",
        "unit conversion and measurement tools with exact rules and rounding",
    )),
    ("algorithms", (
        "graph algorithms: shortest routes, dependency ordering, connected groups",
        "data structures from scratch: a trie, an LRU cache, a priority queue, an interval tree",
        "scheduling: fitting tasks, shifts or meetings into a timetable under rules",
        "encoding and compression: run-length, Huffman codes, checksums, base conversions",
    )),
    ("text and formats", (
        "a tiny interpreter or calculator for a small expression or command language",
        "a template engine or static-site generator that writes HTML files into its own folder",
        "image files made with only the standard library (PPM, or PNG written with zlib), or ASCII art",
        "sound made as WAV files with the wave module: tones, chords, a short tune",
    )),
    ("structure and tests", (
        "a library module with a full unittest suite, edge cases included",
        "a state machine or workflow engine with events and a printed history",
        "date and time tools with zoneinfo and calendar: recurring events, working days, time-zone tables",
    )),
)

# The writing half of a mixed task; the scene half comes from a Blender label (topic_for).
MIXED_TOPICS = (
    "a README for the script: how to run it in the background and which variables at the top to change",
    "a shot list, a sentence per shot, with the frame range of each camera move",
    "a beginner's walkthrough of how the script builds the scene, part by part",
    "a short email to a client pitching the scene and the choices behind its look",
    "a short story or scene description that the scene illustrates",
    "a classroom worksheet about the 3D idea the scene shows, with questions",
    "a marketplace listing for the scene as an asset: description, features and specs",
    "a storyboard of the animation's beats in prose, a paragraph per beat",
    "a reference table of the scene's settings and what each one changes",
    "notes comparing EEVEE and Cycles settings for the scene, ending with which to use",
)


def _interleave(areas):
    """[(area, label)]: each area's first label, then each area's second, and so on."""
    out, depth = [], max(len(labels) for _, labels in areas)
    for d in range(depth):
        out += [(area, labels[d]) for area, labels in areas if d < len(labels)]
    return out


_BLENDER = _interleave(BLENDER_AREAS)
_PYTHON = _interleave(PYTHON_AREAS)
BLENDER_TOPICS = tuple(label for _, label in _BLENDER)
PYTHON_TOPICS = tuple(label for _, label in _PYTHON)
TOPIC_AREA = dict((label, area) for area, label in _BLENDER + _PYTHON)

# (how they write, weight) and (how long, weight); a call's pick comes from weighted cycles (rotation()).
STYLES = (
    ("casual and short-spoken, mostly lowercase, with a typo or two", 2),
    ("plain and direct", 3),
    ("precise, like a spec", 2),
    ("friendly and chatty, saying what it's for (a hobby, a class, a client, a game)", 1),
    ("terse, like a ticket or a note to self", 1),
)
LENGTHS = (
    ("two or three sentences", 3),
    ("a paragraph of 4 to 7 sentences", 4),
    ("a short request followed by a bullet list of 5 to 10 requirements", 2),
    ("a short request followed by data it needs pasted into the message (a table, a list of values or sample "
     "input, 5 to 30 lines)", 1),
)

SEED_SYSTEM = ("You write realistic requests that people type into Chimera, an AI assistant that splits a big job "
               "into parts, has several helpers write the parts, and puts their work together. Each request must "
               "sound like a real person with a real need, in their own words. Reply with JSON only.")

WHAT = {
    "blender": "a Python script for Blender 5.x that builds a scene",
    "python": "a working Python program",
    "mixed": "a Python script for Blender 5.x that builds a scene, together with a piece of writing about the scene",
}

_SCENE_RULES = [
    "The script starts from a new, empty Blender file and makes everything itself in code: every object, "
    "material, light, camera and animation.",
    "It must not need anything on disk: no existing .blend file, no image, HDRI, texture, font or model files, and "
    "no add-ons. Anything the scene needs, such as a texture or a curve, is made in code.",
    "The script runs in the background (blender -b), so nothing can depend on clicking, selecting things in the "
    "viewport or an open window. Asking for render settings or an output path is fine; it doesn't have to render.",
]

RULES = {
    "blender": _SCENE_RULES + [
        "Each request is big enough that a planner would split it into 2 to 6 parts that separate helpers write, "
        "such as the models, the materials, the lights and world, the camera and its animation, or the render and "
        "compositor settings, some of which could be written at the same time.",
        "Give the details a real person would: object names, sizes in metres, counts, colours, frame ranges, the "
        "render engine (EEVEE or Cycles), lens lengths, and which values they want in variables at the top.",
    ],
    "python": [
        "Each request asks for a program in Python 3 that uses only the standard library: no pip packages.",
        "It must run to the end on its own: no network or internet, no web server, no GUI window, and no waiting "
        "for someone to type. Its input comes from the message itself, from sample data the program makes first, "
        "or from command-line arguments that have defaults.",
        "It must not need files that already exist on the person's computer; it may write and read its own files "
        "in its own folder.",
        "Each request is big enough that a planner would split it into 2 to 6 parts that separate helpers write, "
        "such as the data model, the core logic, a command-line interface, a report and its tests. Some ask for "
        "one script, some for a small package of several files with tests.",
        "Give the details a real person would: names of functions, classes, files and options, the input format "
        "with an example, the exact output wanted, and the edge cases to handle.",
    ],
    "mixed": _SCENE_RULES + [
        "The writing is about this scene (what is in it, how it is made, how to change or use it), in the form "
        "named under Topic, with a length or shape the person states, such as about 300 words or six shots.",
        "Each request is big enough that a planner would split it into 2 to 6 parts: the script's parts and the "
        "writing go to separate helpers.",
        "Give the details a real person would: object names, sizes, counts, colours, frame ranges, the render "
        "engine, and who the writing is for.",
    ],
}


def rotation(pairs, i, *salt):
    """The i-th pick from [(value, weight)]: a cycle with each value weight times, shuffled once by salt, so the
    shares hold over any full cycle and a resumed or longer run picks the same values for the same i."""
    cycle = [v for v, w in pairs for _ in range(w)]
    rng("topics", *salt).shuffle(cycle)
    return cycle[i % len(cycle)]


def topic_for(target, i):
    """(topic, area) of call i of a target. A mixed call pairs a writing label with a Blender label, half the
    rotation away from the Blender call of the same number, so the two don't share a technique."""
    if target == "blender":
        area, label = _BLENDER[i % len(_BLENDER)]
        return label, area
    if target == "python":
        area, label = _PYTHON[i % len(_PYTHON)]
        return label, area
    if target == "mixed":
        area, label = _BLENDER[(i + len(_BLENDER) // 2) % len(_BLENDER)]
        return f"{MIXED_TOPICS[i % len(MIXED_TOPICS)]}; the scene uses {label}", area
    raise ValueError(f"unknown seed target {target!r} (one of {', '.join(TARGETS)})")


def style_for(target, i):
    return rotation(STYLES, i, "style", target)


def length_for(target, i):
    return rotation(LENGTHS, i, "length", target)


def seed_user(target, topic, style, length, k, avoid=()) -> str:
    """The teacher's user message for one seed call: k requests of a target on a topic. avoid: subjects the
    teacher must stay away from (seeds.py passes the eval's plan titles, read at run time)."""
    if target not in RULES:
        raise ValueError(f"unknown seed target {target!r} (one of {', '.join(TARGETS)})")
    rules = list(RULES[target]) + [
        "Ask for the finished thing itself (the script, the program, the text), not for advice on how to make it.",
        "Write each request the way the person would type it: don't number its parts as steps, and don't mention "
        "helpers or planners.",
        "Write in English.",
        f"Make the {k} requests clearly different from each other in subject, size and wording.",
    ]
    if avoid:
        rules.append("These subjects are covered elsewhere already, so don't write about them or close variations "
                     "of them: " + "; ".join(avoid) + ".")
    return (f"Write {k} different requests that people might type into Chimera. Each asks for {WHAT[target]}.\n\n"
            f"Topic: {topic}\nHow they write: {style}\nHow long: {length}\n\n"
            + "\n".join("- " + r for r in rules)
            + '\n\nReply with JSON only: {"tasks": ["...", "..."]}')
