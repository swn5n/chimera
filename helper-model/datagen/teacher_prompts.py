"""The instructions the generator gives the teacher (gpt-oss:120b) to write seed requests,
conversations, Heads, gate messages and flawed copies of results.

These steer what the teacher writes; they are never training data themselves. The training
inputs are Chimera's own prompts wrapped around what the teacher writes here, and the training
targets are the teacher's answers to those prompts."""

SEED_SYSTEM = ("You write realistic messages that people send to an AI assistant. Each one must sound like a real "
               "person with a real need, in their own words. Reply with JSON only.")
HEADS_SYSTEM = "You design tools for a home AI network. Reply with JSON only."
GATE_SYSTEM = "You write realistic messages that people send to an AI assistant. Reply with JSON only."
FLAW_SYSTEM = "You prepare test material for checking AI reviewers. Reply with JSON only."


def seed_user(k, category_desc, topic, style, length, language, extra=()):
    rules = ["Each message must ask for a job big enough to split into several parts that separate helpers could do, "
             "some of them at the same time, and must ask for the finished result, not for advice on how to do it.",
             "Make each message concrete and self-contained, with the names, numbers, versions, file names and "
             "constraints a real person would give.",
             "Ask for the content itself (text, code, tables, data) as people usually do; only now and then name a "
             "file format such as PDF or Word.",
             f"Make the {k} messages clearly different from each other in subject, size and wording."] + list(extra)
    return (f"Write {k} different messages that people might send to an AI assistant. Each asks for {category_desc}.\n\n"
            f"Topic area: {topic}\nHow they write: {style}\nHow long: {length}\nLanguage: {language}\n\n"
            + "\n".join("- " + r for r in rules)
            + '\n\nReply with JSON only: {"messages": ["...", "..."]}')


def small_user(k, kind, topic, style, language):
    return (f"Write {k} different small requests that people might send to an AI assistant. Each must be answerable in "
            "full in one reply, with an answer someone could check.\n\n"
            f"Kind of request: {kind}\nTopic area: {topic}\nHow they write: {style}\nLanguage: {language}\n\n"
            "- State every requirement the answer must meet: names, numbers, limits, and the language or format wanted.\n"
            f"- Make the {k} requests clearly different from each other.\n\n"
            'Reply with JSON only: {"messages": ["...", "..."]}')


def followup_user(k, category_desc, topic, language):
    return (f"Write {k} short conversations between a person and an AI assistant. In each, the person first asks a "
            "question or asks for something small; the assistant answers it well (50 to 200 words, with a short code "
            "block if it fits); then the person sends a follow-up that builds on that answer and asks for "
            f"{category_desc}. The follow-up must only make full sense together with the earlier messages.\n\n"
            f"Topic area: {topic}\nLanguage: {language}\n\n"
            f"Make the {k} conversations about clearly different things.\n\n"
            'Reply with JSON only: {"conversations": [{"user": "...", "assistant": "...", "follow_up": "..."}]}')


def heads_user(k, kind):
    return ("Chimera is a network of home computers that run AI models. People add \"Heads\": tools that make "
            "something (a picture, a sound, a 3D model, a file) and run instead of a chat model when someone asks for "
            "exactly what the tool makes.\n\n"
            f"Invent {k} different Heads of this kind: {kind}. Each must make its result from a text description "
            "alone, with no file needed.\n\n"
            "For each, give:\n"
            "- \"id\": a short lowercase id with dashes\n"
            "- \"name\": a short display name\n"
            "- \"summary\": one sentence: what it makes, and with which model or program on its owner's computer\n"
            "- \"when_to_use\": concrete cases, in the words people use when they want what it makes\n"
            "- \"when_not_to_use\": what it must not take: questions about it, requests that want text back, and "
            "similar jobs it can't do\n"
            "- \"tags\": 4 to 10 lowercase keywords\n\n"
            f"Make the {k} Heads clearly different from each other (different outputs, styles or uses).\n\n"
            'Reply with JSON only: {"heads": [{"id": "...", "name": "...", "summary": "...", "when_to_use": "...", '
            '"when_not_to_use": "...", "tags": ["..."]}]}')


def gate_user(k, head, language, yes, no):
    def block(types):
        return "\n".join(f"- \"{t}\": {d.format(language=language)}" for t, d in types.items())
    return (f"Here is a tool someone added to an AI assistant:\n\n{head['name']}: {head['summary']}\n"
            f"Use it when: {head['when_to_use']}\nNot for: {head['when_not_to_use']}\n\n"
            f"Write {k} different messages a person might send to the assistant: about half where they want this tool "
            "to make its thing, and about half where they don't. Give each message one of these types.\n\n"
            "Wants the tool's result:\n" + block(yes) +
            "\n\nDoesn't want the tool to run:\n" + block(no) +
            "\n\nUse as many different types as you can, give each message a different subject, and make them sound "
            "like real people.\n\n"
            'Reply with JSON only: {"messages": [{"type": "...", "text": "..."}]}')


def flaw_user(task, result, flaw_kind):
    return ("Here is a task someone gave an AI assistant, and the assistant's response.\n\n"
            f"Task:\n{task}\n\nResponse:\n{result}\n\n"
            f"Rewrite the response so that it has exactly one realistic flaw of this kind: {flaw_kind}. Keep everything "
            "else as it is, and don't point out or hint at the flaw anywhere in the response.\n\n"
            'Reply with JSON only: {"response": "...", "flaw": "one sentence saying what the flaw is"}')


# ---------------------------------------------------------------- v2 (Oct 28)
# Added to the teacher's copy of Chimera's own request only; the training example keeps Chimera's exact
# request, so the helper learns to do these things unprompted.

CHECK_NOTE = (
    "\n\nBefore the verdict, write a \"check\" field as the first key of the JSON: one short line per requirement of "
    "the task, saying what the result does about it and whether that is met. Where the task gives counts, numbers, "
    "limits or calculations, show the count or the working briefly (for example: 5 asked, 4 given). For code, say "
    "whether it would run and do what was asked. At most 8 lines. Then give done, score and critique so that they "
    "follow from the check:\n"
    '{"check": "...", "done": true | false, "score": 0 to 100, "critique": "..."}')

PLAN_HINTS = {
    "one_step": "Use at least 2 steps: give each step its own share of the items, or its own part or section of the result.",
    "too_many": "Use at most 7 steps: put several items or parts in each step.",
    "not_parallel": "Make the steps independent of each other (empty depends_on), so they all run at the same time, each "
                    "doing its own share of the items.",
    "meta_step": "Don't add a step that reviews, checks, combines, merges, integrates or assembles the other steps' work: "
                 "that happens automatically at the end.",
    "blender_kind": "This is Blender work done with bpy scripts: use the kind \"blender\" for the plan and for every step "
                    "that is Blender work.",
}
PLAN_HINT_INTRO = "\n\nFor this task in particular: "

BATCH_LARGE_DESC = "a job that does the same thing to every item in a list the message includes (8 to 15 items)"


# ---------------------------------------------------------------- v3 (Oct 28 night)
# v2's helper copied the check's format but not the checking: "each conversion correct" without converting,
# "about 60 words" for a much longer text, a list of what the result contains instead of what the task asked.
# So v3's checks start from the task's requirements and redo the counts and arithmetic in the open.
# (The examples below are made up; none comes from the eval set.)
CHECK_NOTE3 = (
    "\n\nBefore the verdict, write a \"check\" field as the first key of the JSON. First list what the task requires: "
    "every part, item, number, count, limit, filter, date, format and name it states. Then check each one against the "
    "result, one short line each, ending in met or not met. Redo every count and calculation in the check and show "
    "it (for example: 3 of the 4 items given; 7 × 12 = 84, the result says 74). For a length limit, estimate the "
    "length from the sentences or lines (for example: 2 paragraphs, about 120 words, asked about 50). For code, say "
    "whether it would run and do what was asked. At most 10 lines. Then give done, score and critique so that they "
    "follow from the check:\n"
    '{"check": "...", "done": true | false, "score": 0 to 100, "critique": "..."}')

PLAN_HINTS["group"] = ("Use 3 to 5 steps: split the items into groups of about the same size, one group per step, "
                       "all running at the same time.")
