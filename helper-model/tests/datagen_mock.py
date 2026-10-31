"""Canned teacher and worker replies for testing datagen/ against runner/mock_ollama.py.
Test data only: never train on it."""
import json
import random
import re

from datagen import taxonomy as tx
from datagen import teacher_prompts as tp
from helper import prompts

VOCAB = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec "
         "romeo sierra tango uniform victor whiskey xray yankee zulu amber basalt cobalt dune ember fjord garnet harbor "
         "iris jade koala lumen magma nectar onyx prism quartz ridge sable topaz umber vortex willow xenon yarrow zephyr").split()

KIND_FOR = {"coding": "code", "research_draft": "research", "blender": "blender", "batch": "writing", "planning": "general"}


def words(seed, n):
    r = random.Random(str(seed))
    return " ".join(r.choice(VOCAB) for _ in range(n))


def _k(user):
    m = re.search(r"Write (\d+)", user) or re.search(r"Invent (\d+)", user)
    return int(m.group(1)) if m else 3


def _category(user):
    if tp.BATCH_LARGE_DESC in user:
        return "batch"
    for c, d in tx.CATEGORY_DESC.items():
        if d in user:
            return c
    return "small_task"


def plan(user, n, system=""):
    m = re.search(r"\[(\w+)\]", user)
    kind = KIND_FOR.get(m.group(1) if m else "coding", "code")
    parallel = tp.PLAN_HINTS["not_parallel"] in system or tp.PLAN_HINTS["group"] in system  # v2's and v3's hints
    steps = [{"id": "s1", "title": "First part " + words((n, 1), 2), "kind": kind,
              "instructions": "Write the first part in full: " + words((n, 2), 8), "depends_on": []},
             {"id": "s2", "title": "Second part " + words((n, 3), 2), "kind": kind,
              "instructions": "Write the second part in full: " + words((n, 4), 8), "depends_on": []},
             {"id": "s3", "title": "Third part " + words((n, 5), 2), "kind": kind,
              "instructions": "Write the third part, using steps 1 and 2: " + words((n, 6), 8),
              "depends_on": [] if parallel else ["s1", "s2"]}]
    if "[long]" in user and tp.PLAN_HINTS["one_step"] not in system:
        steps = steps[:1]  # a long batch in one step: v2's hint fixes it
    first_round = "The previous attempt produced this result" not in user
    if "[research_draft]" in user and first_round and tp.PLAN_HINTS["meta_step"] not in system:
        steps = steps + [{"id": "s4", "title": "Review and combine everything", "kind": kind,
                          "instructions": "Merge the parts: " + words((n, 7), 6), "depends_on": ["s1", "s2", "s3"]}]
    if n % 4 == 0:
        for s in steps:
            s.pop("depends_on")  # a format-only slip the filter repairs
    body = json.dumps({"title": "Mock " + words(n, 2), "kind": kind, "summary": "A mock plan. It has three steps.", "steps": steps})
    return "```json\n" + body + "\n```" if n % 5 == 0 else body


def answer(n):
    parts = [f"## Part {i}\n\n" + words((n, i), 45) + "." for i in range(1, 5)]
    return "\n\n".join(parts) + "\n\nThat covers everything you asked for."


def respond(system, user, messages, body, n):
    if system == tp.SEED_SYSTEM:
        k = _k(user)
        if '"conversations"' in user:
            cat = _category(user)
            return json.dumps({"conversations": [{"user": "question " + words((n, i, "u"), 10),
                                                  "assistant": "answer " + words((n, i, "a"), 30),
                                                  "follow_up": f"[{cat}] now build on that: " + words((n, i, "f"), 18)}
                                                 for i in range(k)]})
        cat = _category(user)
        tag = f"[{cat}] [long]" if tp.BATCH_LARGE_DESC in user else f"[{cat}]"
        return json.dumps({"messages": [f"{tag} please " + words((n, i), 22) for i in range(k)]})
    if system == tp.HEADS_SYSTEM:
        k = _k(user)
        return json.dumps({"heads": [{"id": f"mock-head-{n}-{i}", "name": f"Mock Head {n}-{i}",
                                      "summary": "Makes " + words((n, i, "s"), 8), "when_to_use": "Someone asks for " + words((n, i, "w"), 6),
                                      "when_not_to_use": "Questions about it", "tags": ["mock", "make"]} for i in range(k)]})
    if system == tp.GATE_SYSTEM:
        k = _k(user)
        yes, no = list(tx.GATE_YES), list(tx.GATE_NO)
        types = [t for pair in zip(yes, no) for t in pair] + no[len(yes):]
        return json.dumps({"messages": [{"type": types[i % len(types)], "text": f"<{types[i % len(types)]}> " + words((n, i), 12)}
                                        for i in range(k)]})
    if system == tp.FLAW_SYSTEM:
        orig = user.split("\n\nResponse:\n", 1)[1].split("\n\nRewrite the response", 1)[0]
        return json.dumps({"response": orig + "\n\nTODO: fill in the rest.", "flaw": "a placeholder was left in"})
    if system.startswith(prompts.HYDRA_PLANNER_PROMPT):  # with a v2 hint after it, or not
        return plan(user, n, system)
    if system in (prompts.HYDRA_REVIEW_PROMPT + tp.CHECK_NOTE, prompts.HYDRA_REVIEW_PROMPT + tp.CHECK_NOTE3):  # v2, v3
        result = user.split("The result so far:\n", 1)[-1]
        bad = "TODO" in result or len(result) < 900
        lines = ["Asked for every part: " + ("not met, a part is unfinished" if bad else "met"), "Runs as asked: met"]
        check = lines if n % 3 == 0 else "\n".join(lines)  # gpt-oss sometimes writes the check as a list
        if bad:
            return json.dumps({"check": check, "done": False, "score": 40, "critique": "Parts are unfinished; complete them."})
        return json.dumps({"check": check, "done": True, "score": 90, "critique": ""})
    if system == prompts.HYDRA_REVIEW_PROMPT:
        result = user.split("The result so far:\n", 1)[-1]
        if "TODO" in result or len(result) < 900:
            return json.dumps({"done": False, "score": 40, "critique": "Parts are missing or unfinished; complete them."})
        return json.dumps({"done": True, "score": 90, "critique": ""})
    if system == prompts.HEAD_GATE_PROMPT:
        req = user.split("Request: ", 1)[-1]
        m = re.match(r"<(\w+)>", req)
        use = bool(m and m.group(1) in tx.GATE_YES)
        if n % 7 == 0:
            use = not use  # a teacher slip the filter drops
        return json.dumps({"use": use})
    if not system:  # a worker answering a task
        return answer(n)
    return None
