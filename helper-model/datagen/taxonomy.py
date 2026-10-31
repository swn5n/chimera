"""What the generator asks the teacher to write about: categories, topics and styles.

These are short labels that steer the teacher, never example requests: every request in the
training data is written by the teacher itself (and checked against the eval set)."""

PLANNER_CATS = ("coding", "research_draft", "blender", "batch", "planning")

CATEGORY_DESC = {
    "coding": "a programming job: building or changing a program, script, app, game mod, API, tool or test suite",
    "research_draft": "a research or writing job: a comparison, recommendation, explainer, guide, report, article, product copy, letter or other document",
    "blender": "a Blender job done with a Python (bpy) script: building or changing a scene, models, materials, lighting, cameras, animation, geometry nodes, rigs, renders or the compositor",
    "batch": "a job that does the same thing to every item in a list the message includes (4 to 12 items)",
    "planning": "a planning or organising job that ends in a finished plan: an event, a trip itinerary, a study or training plan, a project plan with milestones, a schedule or a checklist",
}

# The Chimera plan kinds a good plan can have for each category.
EXPECT_KIND = {
    "coding": {"code"},
    "research_draft": {"research", "writing"},
    "blender": {"blender"},
    "batch": {"code", "writing", "research", "general"},
    "planning": {"general", "research", "writing"},
}

TOPICS = {
    "coding": {
        "langs": ["Python", "JavaScript (Node.js)", "TypeScript with React", "Go", "Rust", "Java, as a Minecraft Fabric mod",
                  "C#", "Swift", "Bash or zsh", "SQL with a bit of Python", "Lua", "PHP", "Kotlin", "C++",
                  "HTML, CSS and plain JavaScript"],
        "areas": ["a web app", "a command-line tool", "a small game", "a data-processing script", "home or desktop automation",
                  "a REST or WebSocket API", "a browser extension", "a Discord or Slack bot", "audio or music software",
                  "image or video processing", "a test suite for existing code", "fixing a bug in pasted code",
                  "refactoring pasted code", "a file converter or importer", "a mobile or desktop app",
                  "a plugin for a tool they use", "a small server or networking tool", "a report or spreadsheet generator",
                  "a scheduling or reminder tool", "a database schema and migrations"],
    },
    "research_draft": {
        "areas": ["buying tech or tools", "a home lab or self-hosting", "running a small business", "industrial or railway equipment",
                  "travel", "learning a new skill", "personal budgeting basics", "gaming or game design", "music production",
                  "3D art and rendering", "hobby electronics", "gardening or DIY", "cooking", "a science or history topic",
                  "careers and job hunting", "software and AI tools", "a club, team or community", "marketing a product"],
        "docs": ["a comparison ending in a recommendation", "a decision memo", "an explainer", "a blog post", "a how-to guide",
                 "product copy", "a cover letter or application", "a report", "an FAQ", "an onboarding guide", "a newsletter",
                 "a proposal", "a checklist", "a lesson plan"],
    },
    "blender": {
        "areas": ["procedural modelling", "materials and shader nodes", "lighting a scene", "cameras and animation", "geometry nodes",
                  "rigging with drivers or constraints", "physics simulation", "rendering and batch jobs", "the compositor",
                  "importing, exporting and scene clean-up", "an add-on panel or operator", "audio-driven animation",
                  "3D text and logos", "product visualisation", "architecture and interiors", "looping motion graphics",
                  "particles and scattering", "UVs and texturing"],
    },
    "batch": {
        "ops": ["translate each item", "summarise each item", "label or classify each item", "write a description for each item",
                "rewrite each item in a given style", "convert each item to another format", "pull out fields from each item",
                "write a test for each function", "write a query or formula for each report", "write alt text or captions for each item",
                "write quiz questions for each topic", "draft a reply to each message"],
        "items": ["products", "support emails", "functions or code snippets", "articles or abstracts", "database reports",
                  "song or album ideas", "game items or mods", "recipes", "meeting notes", "job postings", "app interface strings",
                  "log lines", "places to visit", "customer reviews"],
    },
    "planning": {
        "areas": ["a wedding or party", "a week-long trip", "a conference or meetup", "a study plan for an exam", "a training plan for a race",
                  "moving house", "launching a product", "a renovation", "a semester of lessons", "a game jam", "a band tour",
                  "a garden for the year", "a small-business opening", "a hackathon"],
    },
}

SMALL_KINDS = [
    "a short function or method with clearly stated behaviour",
    "a shell command or one-liner",
    "a SQL query against a table the request describes",
    "a regular expression, with examples of what it must and must not match",
    "a calculation or unit conversion with several values",
    "a short piece of writing with an explicit length, form or tone",
    "a translation of a few lines into a named language",
    "a small Blender Python snippet that does one thing",
    "an explanation or definition in a set number of words or sentences",
    "a list with a set number of items that must follow stated rules",
]

STYLES = [
    ("casual and short, mostly lowercase, with a typo or two", 2),
    ("plain and direct", 3),
    ("detailed, like a spec, with bullet points", 2),
    ("polite and chatty", 1),
    ("terse, like a ticket or a note to self", 1),
]

LENGTHS = [
    ("one or two sentences", 0.35, False),
    ("a short paragraph of 3 to 6 sentences", 0.40, False),
    ("a short request followed by pasted material it needs (code, data, a log, notes or part of a document, 10 to 40 lines)", 0.25, True),
]

LANGUAGES = [("English", 82), ("Spanish", 3), ("German", 3), ("French", 3), ("Portuguese", 2), ("Italian", 2),
             ("Dutch", 1), ("Japanese", 2), ("Chinese", 2)]
OTHER_LANGUAGES = [l for l, _ in LANGUAGES if l != "English"]

HEAD_KINDS = [
    "images from a description (photo-real, illustrated, anime or painted styles)", "logos and icons",
    "pixel art and game sprites", "songs and instrumental music", "sound effects", "speech in different voices (text to speech)",
    "3D models or meshes", "short video clips", "animated GIFs or stickers", "diagrams and flowcharts from a description",
    "charts from numbers given in the message", "QR codes and barcodes", "textures and PBR materials",
    "printable documents (certificates, labels, cards)", "maps and terrain heightmaps", "Minecraft skins or builds",
    "lettering and font images", "avatars and profile pictures", "wallpapers and backgrounds", "posters and flyers",
]

# Message types for the gate, with the answer each one implies.
GATE_YES = {
    "direct": "asks for it plainly",
    "no_verb": "only describes the thing they want, with no verb or question",
    "question_form": "asks for it politely, phrased as a question",
    "detailed": "asks for it with specifics such as sizes, styles, lengths or counts",
    "other_language": "asks for it in {language}",
    "casual": "asks for it in a short, lowercase message with a typo",
}
GATE_NO = {
    "how_it_works": "asks how this kind of tool or technology works",
    "wants_text": "wants words back about the thing: a prompt for it, a description, lyrics, a script, code or advice",
    "best_options": "asks which settings, models, apps or prices are best for it",
    "edit_their_file": "asks to change or convert a file of their own, without attaching it",
    "capability": "asks whether the assistant can make this kind of thing at all",
    "same_words": "uses the tool's words for a different job, such as working on something they already have",
    "small_talk": "chats about the topic without asking for anything to be made",
}

FLAW_KINDS = [  # (what to break, only for results with code)
    ("a factual or numeric mistake", False),
    ("a bug that makes the code give wrong results or fail", True),
    ("one thing the task asked for is left out", False),
    ("the wrong length, format or language for what was asked", False),
    ("a destructive or unsafe step nobody asked for, like deleting or overwriting things", False),
    ("a placeholder or TODO where real content should be", False),
]

# v2: flaw kinds for the second round of flawed copies, weighted towards the ones a reviewer has to check
# to see (a count, a number, a condition), which v1 missed on the eval. (what to break, only for code, weight)
FLAW_KINDS2 = [
    ("a factual or numeric mistake, such as one wrong value in a calculation or conversion", False, 3),
    ("a bug that makes the code give wrong results or fail", True, 3),
    ("one thing the task asked for is left out", False, 2),
    ("one of the items the task lists is skipped while the rest are done well", False, 3),
    ("a condition or limit the task set (a filter, a date range, a count, a word limit) is ignored", False, 3),
    ("the wrong length, format or language for what was asked", False, 2),
    ("a destructive or unsafe step nobody asked for, like deleting or overwriting things", False, 1),
    ("a placeholder or TODO where real content should be", False, 1),
]

# v3: the flaws v2's helper still let through on the eval: a wrong value, a wrong count, a broken length
# limit, an ignored condition. (what to break, only for code, weight)
FLAW_KINDS3 = [
    ("a wrong value in a calculation, conversion or total, with everything else right", False, 4),
    ("a wrong count: one of the items the task lists is skipped or done twice", False, 3),
    ("a length limit the task set is clearly broken: far too long or far too short", False, 3),
    ("a condition the task set (a filter, a date range, a unit, a format rule) is ignored", False, 3),
    ("a bug that makes the code give wrong results or fail", True, 2),
    ("one thing the task asked for is left out", False, 1),
    ("a destructive or unsafe step nobody asked for, like deleting or overwriting things", False, 1),
]
