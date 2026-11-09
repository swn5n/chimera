"""One seed, start to end (DESIGN.md, "task.py"): its plan, every step's training request and the teacher's pieces for
it, the checks they went through, repairs, the second sampler, drops, the variants, the plan check and round 2.

    rec = run_seed(env, seed)      # {"key", "seed", "status", "error", "rounds", "round2", "seconds", "finished"}

What a step's worker gets is always Chimera's own request (chimera.worker_request, the Go binary), stored as it is:
that is the training input. The teacher is sent a copy with teacher-only notes added to its system message
(hints.teacher_copy), which never reaches the record's request. A step's request is built from the pieces kept for
the earlier steps; a dropped step is left out, so Chimera tells the steps that use it that it failed.

A step's candidates are drawn in rounds (Blender 2 then 2 more, code 2 then 1, sections 1, 1 and 1), the later
rounds' notes naming what the earlier candidates failed on: the validator's messages, lint errors, crashes, a
section's plain lines and every gate's own "tell" lines (_failures). A reply whose form is only decorated is made
plain first (a bold File line, a stand-in marker with another hyphen: normalised; the raw reply stays in the call
cache). Then each goes through, stopping at the first that fails: the reply itself (no runaway, not cut at the length
limit, not empty), harmony leftovers, the teacher's notes repeated (hints.echoed_note, less what Chimera's request
says too) or, for a Blender step, a Blender version only the notes name (hints.version_leak) or the notes' words for
the Blenders and the sandbox (hints.notes_leak), the Go validator (the contract's exact form, 3,500 tokens at most),
the example's size (12,288 estimated tokens with its request), then its mode's gate (blender_gate, code_gate or
prose_gate), then dep_honesty (a handoff that claims a failed dependency's output, or assumes nothing while one
failed). The passing candidates go to the judge (the scene judge for Blender, variants included, the prose judge
for sections, none for code) in order, fewest validator warnings and then shortest first; the first it accepts is
kept and the rest are alternates. A section written with a dependency missing is kept only if qwen3.8:27b keeps it
too, whatever gpt-oss's score. A code step's tests are written once, before its first candidate is checked (none
while its candidates have no Python file, its own words ask for none and no earlier piece of the round is Python:
"none:no_python"; a reply refused for a rule it breaks (a process started, names guessed, code that doesn't compile,
no assert reached) is asked again once, and a step whose tests stay refused is "none:tests_refused", which the build
drops, unless the retry obeyed the writer's own rule and gave empty tests for a step that names nothing to call),
and judged on that batch; tests that fail on the stub and on every candidate are unconfirmed and gate every later
candidate too, until one passes them. If none ever does, the teacher rewrites them once, told the failing asserts
and errors (never the code), and the new ones count only if they pass tests_check on those candidates; else a piece
is kept without them (tests_status "unconfirmed", or "none:tests_unreachable" / "none:third_party" when
code_gate.tests_fault finds the failure wasn't the pieces'). A piece kept with no tests that ran is "none:third_party"
too when its import run missed a package outside the standard library (code_gate.import_fault), and a piece on which
nothing ran at all (no tests, no import run) is marked so the build calls it unverified. With nothing kept, the
candidate that got furthest with a crash in its own piece (never a failure of the tests) gets up to two repair turns
through Chimera's own repair request (an example only if it changes at most 30% of the piece's code lines, comments,
docstrings and blank lines left out: code_lines); then qwen3.8:27b gets two samples (num_predict 12,288 on a Blender
step, SECOND_OPTIONS, and 8,192 on a code step, SECOND_OPTIONS_CODE), except on a Blender step all of whose teacher
samples failed only on Blender API names, which the two models share (api_only: step["sampler"]; a format-5 record's
step["sampler"]["third"] says a third told batch was drawn when its second batch heard the notes, which since the fifth
smoke no step gets: heard is still recorded); then the step is dropped,
unless a try failed only on SOFT_REASONS (a failed dependency claimed, no output handed over, no camera made the
scene's, an error the piece's own except hid, an input looked up by a wrong name, geometry against its step's
numbers) or, on a step some later step depends on, SOFT_IF_USED (values handed on
through a ctx key Chimera's contract doesn't have, a guard that skipped the linear keys the step asks for; since the
fourth smoke also what the build would drop the piece for, Chimera's validator warnings and a dead output key, and the
stand-in marker's faults, blender_gate.build_facts, each told to the next try): the furthest such the judge accepts is
kept for the later steps and the join, as a pass is, and gives no example (step["no_example"]). A step kept from a
repair gives only its
repair example. A variant (a failed dependency, or a dependency written by another open model under today's prompt)
is an extra request of a step that has a kept piece, checked alone, never fed to a later step. A plan that repeats
the eval (eval_plan) is no plan.

Everything is a function of the caches: model calls (llm.LLM), Blender and Python runs (the gates) and the round-2
result check (cache/runs.jsonl here). A resumed run replays a seed from them to where it stopped. A model call that
fails (Ollama's error, after its tries) raises CallFailed, so the seed is recorded as an error and run again next
time instead of being finished with its steps dropped. Every record says the pipeline's DATAGEN_FORMAT it was made
in: run.py makes a seed of another format again and the build drops it (old_format).
"""
from __future__ import annotations

import ast
import dataclasses
import io
import json
import os
import re
import shutil
import tempfile
import time
import tokenize
import traceback

from contract import planinfo, today
from contract.goport import code_blocks, python_lang
from contract.join import find_part
from contract.validate import FORM_CODES, validate_piece
from datagen import code_gate as CG
from datagen import dep_honesty as DH
from datagen import hints as H
from datagen import judges as J
from datagen import normalise as N
from datagen import prose_gate
from datagen.blender_gate import dep_indexes, step_index
from datagen.chimera import ChimeraError
from datagen.common import chance, est_tokens, key_of, log_line, msgs_tokens, now_iso, rng, StopRequested
from datagen.llm import FIXED_CTX
from runner import common as rc
from runner.score import lines_changed

TEACHER = "gpt-oss:120b"
HELPER = "hydra:1.0"
SECOND = "qwen3.8:27b"
SMALL = "qwen3:8b"
MODELS = {"teacher": TEACHER, "helper": HELPER, "second": SECOND, "small": SMALL}
ROUNDS = {"blender": (2, 2), "python-script": (2, 1), "files": (2, 1), "section": (1, 1, 1)}
CODE_MODES = ("python-script", "files")
REPAIR_TURNS = 2
SECOND_SAMPLES = 2
# thinking and reply together (Ollama's num_predict counts both). It was 8,192 until the fourth smoke: a passing
# qwen3.8 Blender reply of the third smoke used 8,118 of it, and 9 of the 60 stored Blender calls of smoke2-4 ran out
# at 8,192 while still thinking (6,499-7,399 thinking tokens, 0-797 of content). The prompt plus this fits the model's
# fixed num_ctx (llm.FIXED_CTX, 32,768), and it stays under the client's runaway guard (16,384). Blender steps only: a
# code step keeps 8,192 (SECOND_OPTIONS_CODE), as before the round, so its calls keep their cache keys and seeds (none
# of the 58 stored code-mode qwen3.8 calls of smoke2-4 ran out at 8,192; the independent checks found the 12,288 had
# reached them too, Nov 6).
SECOND_OPTIONS = {"num_predict": 12288}
SECOND_OPTIONS_CODE = {"num_predict": 8192}
# THIRD_BATCH (2: one more told gpt-oss batch on a Blender step whose second batch heard its notes, before qwen3.8) was
# retired after the fifth smoke (Nov 6): it fired on 3 steps there, 6 calls and 195 s, with no gate pass; replays of
# smoke2-4 couldn't judge one (where it would fire there, no stored reply answers it). A format-5 record keeps
# step["sampler"]["third"] (2 where it ran); from then on it is 0, and heard is recorded as before.
MAX_TARGET_TOKENS = 3500  # the validator's max_tokens (maxPieceTokens)
MAX_EXAMPLE_TOKENS = 12288  # request plus target, est_tokens
REPAIR_SHARE = 0.30  # a repair example changes at most this share of the failed piece's code lines (code_lines)
REPAIR_SHRINK = 0.10  # ... and leaves out at most this share of them, net (repair_measures)
ALTERNATES = 3  # more joins the plan check tries with the culprit's alternates
NAMES = (("5.2.2", 0.75), ("5.0.1", 0.15), (None, 0.10))  # which sheet a step's request gets (names_gate decides)
HARMONY = re.compile(r"<\|[a-z_]{1,24}\|>|<\|channel>|<channel\|>|assistantfinal|</?think>")
NAMES_HEAD = rc.NAMES_HEAD  # contractNamesHead (app/hydra_contract.go): the sheet follows it
CHECK_FORMAT = 1  # bump when the round-2 check's record changes, so old cached checks aren't reused
FAILS_ROUND2 = ("failed", "wrong_scene")  # a check outcome that skips the review (Chimera's looping mode)
VOLATILE = frozenset({"seconds", "finished", "cached", "waited_s"})  # differ when a run replays from the caches
EVAL_PLAN = 0.5  # share of an eval text's 8-grams a plan's text may not reach (build's per-example threshold)
UNCONFIRMED = ("no_candidate_passed", "no_candidates")  # tests that failed on the stub and no candidate passed yet
REFUSED = ("name_guess", "subprocess", "tests_syntax", "no_asserts")  # judges.parse_tests_why: a reply broke a rule
# The pipeline's format: bump it when what a record holds or how it was judged changes, so run.py makes older seeds
# again and the build drops them (old_format). 1: the first smoke run's (Nov 3; its records carry none), 2: after it
# (the second smoke run's, Nov 4), 3: after the second (the dependency honesty, layout, output and camera checks, the
# soft keep, the newest failure lines), 4: after the third smoke (ctx["values"], ctx_channel a gate with a tell, the
# values-step note, the names sheet and facts without never-available sockets, the repair share on code lines, step
# 6's hidden-error and geometry checks, the uses reader (contract question 4) with round 8's rules, all Nov 5:
# SETTINGS_sN names and keys judged against sN wherever they are in the line, "<id>'s name" pairs after a lead, and a
# list broken by plus after "with its" or "with their"; round 8's other rules came out the same day; no format-4
# record existed before them), 5: after the fourth smoke (Nov 5: what the build drops told and failed at the gate,
# blender_gate.build_facts' validator_warning, dead_output_key, marker_misused and silent_default; attr_miss and
# doubled_depth as reasons; the lint's guarded reads; the scene judge without the goal, with labelled locations, a new
# rubric paragraph and its overrule; the handoff fence made plain at precheck; the third told batch, qwen3.8 skipped
# on API-only steps and its num_predict 12,288; the Blender 5 facts, the camera and output notes and the tells' fixes
# in the teacher's copies), 6: after the fifth smoke (Nov 6: the keyframe slot named in the Blender 5 fact and its
# fix, the handoff note for every Blender step that isn't a values step, a missing input file's plain print in the
# Blender note and the marker's file tell, the third told batch retired, a section's python blocks compiled
# (code_syntax), and a module-level read of a global ctx (global_ctx) told and failed at the gate).
DATAGEN_FORMAT = 6
# Faults that leave a piece usable by the later steps (a reason starts with one of them): its handoff claims a failed
# dependency's output or lists nothing it assumed (dep_honesty), or it hands Chimera no output, makes no camera the
# scene's, hides an error behind its own except, looks an input up by a wrong name (step 6a: swallowed,
# skipped_input) or builds geometry against its step's numbers (step 6b: place_mismatch, flat_extrusion, nested;
# doubled_depth since Nov 5; blender_gate). When no try of a step passes but one failed only on these, its piece is
# kept for the later steps and the join as a pass would be (judged too), but gives no example (step["no_example"]):
# dropping it would give every later step a failed dependency of its own, and Chimera's real flow passes such a piece
# on as it is. They stay soft
# whether or not a later step depends on the step, as output_missing always has.
SOFT_REASONS = frozenset({"dep_claimed", "dep_unlisted", "output_missing", "camera_not_active", "swallowed",
                          "skipped_input", "place_mismatch", "flat_extrusion", "nested", "doubled_depth"})
# Soft only on a step some later step depends on (Round.used): a piece that hands its values on through a ctx key
# Chimera's contract doesn't have (blender_gate's ctx_channel, a gate reason since format 4) is kept so its dependents
# keep it, and with none, dropping it costs nothing. A variant, which nothing depends on, never soft-keeps anyway.
# attr_miss too (Nov 5, datagen/silent.missed_keys): a guard on the way to the keys found nothing, so they stayed
# unlike the linear ones the step asks for; the piece still builds what its dependents use.
# Since the fourth smoke the same for blender_gate.build_facts' reasons (FACT_REASONS): what the build drops
# (validator_warning:<code>, dead_output_key) and the stand-in marker's faults (marker_misused, silent_default), whose
# pieces work for their dependents as they are.
SOFT_IF_USED = frozenset({"ctx_channel", "attr_miss", "validator_warning", "dead_output_key", "marker_misused",
                          "silent_default"})
SOFT_JUDGED = 2  # a soft keep's tries the judge is asked about, furthest first (soft_keep)
# names_callable: parse_line(line), main(), def tally, class Store; not "file(s)"
_CALLABLE = re.compile(r"\b[A-Za-z_]\w*\((?!e?s\))|\b(?:def|class)\s+[A-Za-z_]\w*")
_titles = None  # seeds.TitleMatch over the eval's titles, built on first use


class CallFailed(RuntimeError):
    """A model call failed (Ollama's error, after its tries): the seed is an error, run again on resume."""


@dataclasses.dataclass
class Env:
    """What a seed needs: the models (llm.LLM), the binary (chimera.Chimera), the gates (blender_gate.BlenderGate or
    None, code_gate.CodeGate), Blender's API facts for the hints (rna_lint.Facts or None), the names sheets
    ({version: sheet}), the size, the data folder, a scratch folder for result checks, the run cache (common.Cache,
    cache/runs.jsonl), the helper's accepted gpt-oss plans ({seed_id: {"reply", "key", "wall_s", "file"}}) and the
    EvalIndex a plan is checked against (tools/check_overlap.EvalIndex, or None for no check)."""

    llm: object
    chimera: object
    blender: object
    code: object
    facts: object
    names: dict
    size: dict
    data_dir: str
    work: str
    runs: object
    raw_plans: dict = dataclasses.field(default_factory=dict)
    models: dict = dataclasses.field(default_factory=lambda: dict(MODELS))
    log_path: str | None = None
    eval_index: object = None


# ---------------------------------------------------------------- small helpers

def group_of(seed_id) -> str:
    """A seed's group: the teacher call it came from (its id without the last part), as seeds.pick spreads them."""
    return seed_id.rsplit("-", 1)[0] if "-" in seed_id else seed_id


def names_for(seed_id, sid):
    """The names sheet a step draws: 5.2.2 for 75%, 5.0.1 for 15%, none for 10%."""
    x = rng("names", seed_id, sid).random()
    acc = 0.0
    for v, p in NAMES:
        acc += p
        if x < acc:
            return v
    return None


def stable(obj):
    """obj without what differs when a run replays from the caches (VOLATILE keys, at any depth)."""
    if isinstance(obj, dict):
        return {k: stable(v) for k, v in obj.items() if k not in VOLATILE}
    if isinstance(obj, list):
        return [stable(v) for v in obj]
    return obj


def result_text(j) -> str:
    """The joined result as the person gets it: the text, then the Assumptions note (task_eval.result_text)."""
    note = j.get("assumptions_note") or ""
    return (j.get("text") or "") + ("\n" + note + "\n" if note else "")


def piece_code(content):
    """The code a repair is measured on: every closed python block of the reply, in order (a Blender or
    python-script piece has one; a files piece one per file), read the same way before and after."""
    return "\n".join(b.body for b in code_blocks(content or "") if b.closed and python_lang(b.lang))


def code_lines(code) -> list[str]:
    """The lines a repair's share counts (Round.repair): each line of code (piece_code's) cut where tokenize finds
    its comment, then right-stripped, leaving out blank lines, comment-only lines and every line of a statement that
    is only a string (an ast.Expr of a str Constant, lineno to end_lineno: a docstring, or a bare string used as one).
    Indents count, so a re-indented line is a changed one. Code that doesn't tokenize or parse loses only its blank and
    comment-only lines. Counted on every line, as until format 4, a teacher that rewords the comments around the line
    it fixes looked like one that rewrote the piece: of the three smoke runs' 37 stored repairs (all Blender, every
    one parses), the 5 that passed had shares of 0.079, 0.196, 0.347, 0.368 and 0.318 on every line and 0.055, 0.14,
    0.282, 0.22 and 0.175 on code lines, so 3 come under REPAIR_SHARE (smoke3 blender-0002-02 s2, 34 of whose 107
    lines changed but only 10 of its 57 code lines, smoke2 n-blender-0002-01 s3 and blender-0002-02 s4) and none goes
    over; of the 32 that didn't pass, 2 cross each way."""
    return _read_code(code)[0]


def repair_lines(before, after):
    """(code_lines of before, of after), read the same way, as piece_code reads both sides: when either doesn't
    tokenize or parse, both lose only their blank and comment-only lines, so a fix that makes a broken piece parse
    isn't charged for the comments and docstrings only its own side lost."""
    (b, b_read), (a, a_read) = _read_code(before), _read_code(after)
    return (b, a) if b_read and a_read else (_plain_lines(before), _plain_lines(after))


def _read_code(code):
    """(code_lines, whether it tokenized and parsed)."""
    code = code or ""
    cut, doc = {}, set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(code + "\n").readline):
            if tok.type == tokenize.COMMENT:
                cut[tok.start[0]] = tok.start[1]
        for n in ast.walk(ast.parse(code)):
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                doc.update(range(n.lineno, n.end_lineno + 1))
    except (tokenize.TokenError, SyntaxError, ValueError, RecursionError, MemoryError):
        return _plain_lines(code), False
    out = []
    for k, line in enumerate(code.split("\n"), 1):
        line = (line[:cut[k]] if k in cut else line).rstrip()
        if line.strip() and k not in doc:
            out.append(line)
    return out, True


def repair_measures(before, after):
    """(lines_changed, share, shrink) of a repair's code (piece_code's, before and after), counted on code_lines
    (repair_lines): the lines it changes, their share of before's, and the share of before's it leaves out net (less
    than 0 when it grows), each None when before has no code line. Round.repair makes a passed repair an example only
    when share is at most REPAIR_SHARE and shrink at most REPAIR_SHRINK. Why the shrink: counted on code lines, smoke2
    blender-0002-02 r1 s4 ("Configure Camera & Render", crashed in 5.2.2 on `scene.node_tree`) came under the share
    (0.347 on every line, 0.282 on code lines) with a repair that doesn't port the compositor to 5.x but deletes the
    21-line block of Render Layers, Composite and File Output nodes its step asks for (78 code lines to 58, 25.6%),
    and the judge said ok, so the worker would be taught to delete the feature that fails. Of the 37 stored repairs it
    is the only one that leaves out more than 6.2% of its code lines; the other 4 that passed grow (by 1.8% to 14%)."""
    b, a = repair_lines(before, after)
    if not b:
        return None, None, None
    changed = lines_changed("\n".join(b), "\n".join(a))
    return changed, round(changed / len(b), 3), round((len(b) - len(a)) / len(b), 3)


def _plain_lines(code):
    """code's lines, right-stripped, less its blank and comment-only ones: code_lines for code that doesn't parse."""
    return [x.rstrip() for x in (code or "").split("\n") if x.strip() and not x.lstrip().startswith("#")]


def kept_target(step):
    """(content, model, source) of a step's kept piece, or None."""
    k = step.get("kept")
    if not k:
        return None
    items = step["repairs"] if k["from"] == "repair" else step["candidates"]
    c = items[k["index"]]
    return c["content"], c["model"], k["from"]


def _call(r):
    return {"model": r.model, "key": r.key, "sample": r.sample, "wall_s": round(r.wall_s or 0.0, 3), "cached": r.cached,
            "done_reason": r.done_reason}


def _verdict_rec(v):
    return {"ok": v.get("ok"), "form_ok": v.get("form_ok"), "contract_ok": v.get("contract_ok"),
            "issues": [{"level": x.get("level"), "code": x.get("code"), "message": (x.get("message") or "")[:200],
                        "line": x.get("line")} for x in v.get("issues") or []],
            "handoff": v.get("handoff")}


def ask(env, model, messages, *, purpose, **kw):
    """One model call through the gate and the cache; CallFailed when the call itself failed (a runaway doesn't)."""
    r = env.llm.call(model, messages, purpose=purpose, **kw)
    if r.error is not None and not r.runaway:
        raise CallFailed(f"{model} ({purpose}): {r.error}")
    return r


def _ctx(model, need_ctx):
    """Chimera's num_ctx for a call it sizes itself (the planner, the reviewer); None for a big model, whose fixed
    num_ctx (llm.FIXED_CTX) keeps it from reloading."""
    return None if model in FIXED_CTX else rc.ctx_bucket(need_ctx)


# ---------------------------------------------------------------- the planner and the reviewer

def raw_plans(paths):
    """{seed_id: {"reply", "key", "wall_s", "file"}}: the first accepted plan per seed in helper-model's
    raw/plans*.jsonl (read only), the gpt-oss:120b plans a helper seed that draws gpt-oss reuses. The helper keeps an
    accepted plan as its tidied JSON in "target" (its "reply" is null; only rejected ones keep theirs), which
    plan_round reads through Go again. A record with "hints" was asked with the helper's teacher notes, not with
    Chimera's exact planner request, so it isn't reused."""
    from datagen.common import read_jsonl
    out = {}
    for path in paths:
        for r in read_jsonl(path):
            sid = r.get("seed_id")
            if not r.get("accepted") or not sid or sid in out or "hints" in r:
                continue
            text = r["reply"] if isinstance(r.get("reply"), str) else r.get("target")
            if isinstance(text, str):
                out[sid] = {"reply": text, "key": r.get("key"), "wall_s": r.get("wall_s"),
                            "file": os.path.basename(path)}
    return out


def eval_plan(env, plan):
    """What of the worker eval a cleaned plan repeats, as the eval indexes a plan (evalset.plan_texts): the eval ids
    its head (title and summary), each step's title and instructions, or the whole of it reach at EVAL_PLAN of
    env.eval_index, and "eval_title:<title>" for an eval scenario its head names (seeds.TitleMatch, as the seeds are
    checked). [] without an index. Every worker request carries the head and the outline, so such a plan can give no
    example."""
    global _titles
    if env.eval_index is None or not plan:
        return []
    head = "\n".join(x for x in (plan.get("title"), plan.get("summary")) if isinstance(x, str))
    steps = ["\n".join(x for x in (s.get("title"), s.get("instructions")) if isinstance(x, str))
             for s in plan.get("steps") or [] if isinstance(s, dict)]
    hits = []
    for text in [head] + steps + ["\n".join([head] + steps)]:
        hits += [h[0] for h in env.eval_index.check(text, EVAL_PLAN) if h[0] not in hits]
    if _titles is None:
        from datagen import seeds
        _titles = seeds.TitleMatch(seeds.eval_titles())
    title = _titles.find(head)
    return hits + (["eval_title:" + title] if title else [])


def _ask_planner(env, planner, model, req):
    r = ask(env, model, req["messages"], purpose="plan", fmt=req.get("format"), num_ctx=_ctx(model, req["need_ctx"]))
    got = {"ok": False, "plan": None} if r.runaway else env.chimera.read_plan(r.content)
    planner["tries"].append(dict(_call(r), ok=bool(got["ok"])))
    planner.update(model=model, key=r.key, wall_s=round(planner["wall_s"] + (r.wall_s or 0.0), 3))
    return got["plan"] if got["ok"] else None


def plan_round(env, seed, n, prior="", critique=""):
    """(planner record, cleaned plan or None) for round n. Round 1: gpt-oss:120b for a share of seeds
    (size["gpt_oss_planner"]), reusing a helper seed's accepted gpt-oss plan when there is one, else hydra:1.0, unless
    the request is too long for it (helper_fits, Chimera's rule). Round 2: hydra:1.0 if it fits, else gpt-oss:120b.
    A hydra:1.0 plan that can't be read is asked of gpt-oss:120b once, as Chimera does. A plan that repeats the eval
    (eval_plan) is no plan: the record says reason "eval_plan" and its hits."""
    planner, plan = _plan_round(env, seed, n, prior, critique)
    hits = eval_plan(env, plan)
    if hits:
        planner.update(reason="eval_plan", eval_hits=hits)
        return planner, None
    return planner, plan


def _plan_round(env, seed, n, prior, critique):
    req = env.chimera.plan_request(seed["text"], history=seed.get("history"), prior=prior, critique=critique)
    planner = {"model": None, "key": None, "wall_s": 0.0, "fell_back": False, "reused": False, "drew": None,
               "need_ctx": req["need_ctx"], "helper_fits": req["helper_fits"], "tries": []}
    teacher, helper = env.models["teacher"], env.models["helper"]
    if n == 1:
        gpt = chance(env.size.get("gpt_oss_planner", 0.3), "planner", seed["seed_id"])
        planner["drew"] = teacher if gpt else helper
        raw = env.raw_plans.get(seed["seed_id"]) if gpt and seed.get("source") == "helper" else None
        if raw:
            got = env.chimera.read_plan(raw["reply"])
            if got["ok"]:
                planner.update(model=teacher, key=raw.get("key"), reused=True, orig_wall_s=raw.get("wall_s"),
                               file=raw.get("file"))
                return planner, got["plan"]
            planner["reuse_unreadable"] = True
        model = teacher if gpt or not req["helper_fits"] else helper
    else:
        model = helper if req["helper_fits"] else teacher
    plan = _ask_planner(env, planner, model, req)
    if plan is None and model == helper:
        planner["fell_back"] = True
        plan = _ask_planner(env, planner, teacher, req)
    return planner, plan


def review(env, goal, result):
    """The looping reviewer on a round's result: hydra:1.0 if the request fits it, else gpt-oss:120b, which also gets
    an unreadable hydra:1.0 review once. {"model", "key", "wall_s", "fell_back", "ok", "done", "score", "critique",
    "need_ctx", "helper_fits", "tries"}."""
    req = env.chimera.review_request(goal, result)
    teacher, helper = env.models["teacher"], env.models["helper"]
    out = {"model": None, "key": None, "wall_s": 0.0, "fell_back": False, "ok": False, "done": None, "score": None,
           "critique": "", "need_ctx": req["need_ctx"], "helper_fits": req["helper_fits"], "tries": []}
    model = helper if req["helper_fits"] else teacher
    while True:
        r = ask(env, model, req["messages"], purpose="review", fmt=req.get("format"),
                num_ctx=_ctx(model, req["need_ctx"]))
        got = {"ok": False} if r.runaway else env.chimera.read_review(r.content)
        out["tries"].append(dict(_call(r), ok=bool(got.get("ok"))))
        out.update(model=model, key=r.key, wall_s=round(out["wall_s"] + (r.wall_s or 0.0), 3))
        if got.get("ok"):
            out.update(ok=True, done=bool(got.get("done")), score=got.get("score"), critique=got.get("critique") or "")
            return out
        if model != helper:
            return out
        out["fell_back"] = True
        model = teacher


def result_check(env, result, goal):
    """Chimera's result check of a round's result as a reply (.md), with the goal and the look off, as looping mode
    runs it before the review; cached in cache/runs.jsonl. {"outcome", "summary", "error", "line", "critique",
    "runner", "exit", "stated", "key"}; outcome "skipped" when Chimera finds no script in it."""
    blender = None
    if env.blender is not None:
        blender = next(iter(env.blender.versions.values()))
    key = key_of("round-check", result, goal, blender, env.chimera.sha256(), CHECK_FORMAT)
    hit = env.runs.get(key) if env.runs is not None else None
    if hit is not None:
        return dict(hit, key=key, cached=True)
    os.makedirs(env.work, exist_ok=True)
    d = tempfile.mkdtemp(prefix="dg-round-", dir=env.work)
    try:
        path = os.path.join(d, "result.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(result)
        try:
            rec = env.chimera.check_result(path, goal=goal, work_dir=d, blender=blender)
        except ChimeraError as e:
            if "no script to check" not in str(e):
                raise
            rec = {"check": {"outcome": "skipped", "summary": "no script to check"}, "exit": 2}
    finally:
        shutil.rmtree(d, ignore_errors=True)
    c = rec.get("check") or {}
    value = {"kind": "round-check", "outcome": c.get("outcome"), "summary": c.get("summary"), "error": c.get("error"),
             "line": c.get("line"), "runner": c.get("runner"), "critique": rec.get("critique") or "",
             "exit": rec.get("exit"), "stated": rec.get("stated"), "t": now_iso()}
    if env.runs is not None:
        env.runs.put(key, value)
    return dict(value, key=key, cached=False)


# ---------------------------------------------------------------- a round

class Round:
    """One round of a seed: its plan, the pieces kept so far ({plan id: text}), and its step and variant records."""

    def __init__(self, env, seed, n, plan, planner, prior=None, critique=""):
        self.env, self.seed, self.n, self.plan, self.planner = env, seed, n, plan, planner
        self.goal = seed["text"]
        self.prior, self.critique = prior, critique
        self.kept = {}
        self.steps, self.variants = [], []
        self.rec = {"round": n, "planner": planner, "plan": plan, "steps": self.steps, "variants": self.variants,
                    "plan_check": {}, "join": None, "result": None, "check": None, "review": None, "critique": None}
        if n > 1:
            self.rec.update(prior=prior, critique_in=critique)

    @property
    def seed_id(self):
        return self.seed["seed_id"]

    def log(self, line):
        log_line(self.env.log_path, f"{self.seed_id} r{self.n} {line}")

    # ---- requests

    def request(self, inputs):
        """Chimera's request for inputs ({"index", "outputs", "names", "prev_result", "critique", "piece",
        "crash"}), exactly as --hydra-worker-request prints it."""
        env = self.env
        return env.chimera.worker_request(
            self.plan, inputs["index"], inputs["outputs"], goal=self.goal, names=env.names.get(inputs["names"]) or "",
            names_gate=True, prev_result=inputs.get("prev_result"), critique=inputs.get("critique") or "",
            piece=inputs.get("piece"), crash=inputs.get("crash"))

    def step_record(self, i, outputs, variant=None):
        st = self.plan["steps"][i]
        sid = f"s{i + 1}"
        drawn = names_for(self.seed_id, sid)
        inputs = {"index": i, "outputs": outputs, "names": drawn if drawn in self.env.names else None,
                  "prev_result": self.prior, "critique": self.critique or ""}
        req = self.request(inputs)
        deps = [self.plan["steps"][j]["id"] for j in dep_indexes(self.plan, i)]
        applied = bool(inputs["names"]) and NAMES_HEAD in req["messages"][0]["content"]
        return {"sid": sid, "index": i, "id": st["id"], "title": st.get("title") or "", "kind": st.get("kind") or "",
                "mode": req["mode"], "variant": variant, "lone": req["lone"], "deps": req["deps"],
                "missing_deps": [d for d in deps if d not in outputs], "names": inputs["names"] if applied else None,
                "names_drawn": drawn, "inputs": inputs,
                "request": {"messages": req["messages"], "need_ctx": req["need_ctx"]},
                "request_tokens": msgs_tokens(req["messages"]), "round2_matched": req.get("round2_matched"),
                "tests": None, "candidates": [], "repairs": [], "kept": None, "alternates": [], "drop": None,
                "plan_failed": False, "seconds": {"teacher": 0.0, "judge": 0.0, "tests": 0.0, "checks": 0.0}}

    # ---- the steps

    def run(self):
        """Every step in plan order (and its variants), then the plan check and the round's joined result."""
        for i, st in enumerate(self.plan["steps"]):
            step = self.step_record(i, self.earlier(i))
            self.steps.append(step)
            self.solve(step)
            if step["mode"] in CODE_MODES:
                self.settle_tests(step)
            got = kept_target(step)
            if got:
                self.kept[st["id"]] = got[0]
            soft_note = f", no example: {', '.join(step['no_example'])}" if step.get("no_example") else ""
            self.log(f"{step['sid']} {step['mode']}: " + (f"kept from {got[2]} ({len(step['candidates'])} samples, "
                                                         f"{len(step['repairs'])} repairs{soft_note})" if got else
                                                         "dropped: " + ", ".join(step["drop"] or [])))
            if got and not step.get("no_example"):  # no variants for a soft keep: no try of its passed, and such a
                self.make_variants(step)            # step was dropped, with none, before soft keeps
        self.plan_checks()
        j = self.env.chimera.join(self.plan, self.kept, goal=self.goal)
        self.rec["join"] = {"fallback": bool(j.get("fallback")), "reasons": (j.get("reasons") or [])[:5],
                            "seams": sorted({s.get("code") for s in j.get("seams") or []}),
                            "failed": j.get("failed") or [], "script_kind": j.get("script_kind") or ""}
        self.rec["result"] = None if j.get("fallback") else result_text(j)
        return self.rec

    def earlier(self, i):
        """{plan id: text} of the kept pieces of the steps before i."""
        return {s["id"]: self.kept[s["id"]] for s in self.plan["steps"][:i] if s["id"] in self.kept}

    def used(self, step):
        """Whether some later step of the plan depends on this step record's (contract.planinfo.user_names), so
        SOFT_IF_USED's faults are soft on its tries: never on a variant's, which feeds no step."""
        return not step.get("variant") and bool(planinfo.user_names(self.plan, step["index"]))

    def earlier_sections(self, i):
        """{sid: text} of the kept pieces of the section steps before i."""
        return {s["sid"]: kept_target(s)[0] for s in self.steps[:i]
                if s["mode"] == "section" and s["index"] < i and kept_target(s)}

    def solve(self, step, alone=False):
        """Draw, check and keep a piece for a step record (alone: a variant, checked alone, no tests, repairs or
        second sampler), or drop it with the reasons of the candidate that got furthest. A Blender step that gets past
        its ROUNDS batches records step["sampler"] ({"heard", "third", "second", and "why", "api" when it was
        skipped}): heard says whether its second batch heard the notes (no fault in common, and it got at least as
        far), which until the fifth smoke drew a third told batch ("third": 2) and since then is only recorded
        ("third": 0); qwen3.8 isn't asked when every teacher sample failed only on Blender API names (api_only:
        "second" "skipped", why "api_faults"); else "second" says "asked". A step's (never a variant's)
        try that failed only on SOFT_REASONS (or SOFT_IF_USED too, when a later step depends on it: used) is kept for
        the later steps instead, with no example (soft_keep), once nothing else passed. A code step whose tests
        failed on the stub and on every candidate so far gates every later candidate with them too; when none ever
        passes them, the teacher rewrites them once (rewrite_tests), and only if that doesn't count either is one
        kept without them (untested)."""
        env, mode, i = self.env, step["mode"], step["index"]
        req = step["request"]
        failures = []
        purpose = "variant" if alone else "worker"
        batches = []
        for n in ROUNDS.get(mode, (1, 1)):
            if self.teacher_batch(step, n, failures, purpose, alone):
                return
            batches.append(step["candidates"][-n:])
        if alone:
            return self.drop(step)
        if mode == "blender":  # the second sampler's budget (api_only: no qwen3.8); heard only recorded since Nov 6
            step["sampler"] = {"heard": heard(*batches[-2:]) if len(batches) > 1 else False, "third": 0,
                               "second": None}
        groups = (("cand", list(step["candidates"])),)
        if mode == "blender" or mode in CODE_MODES:
            if self.repair(step, failures):
                return
            first = list(step["candidates"])
            if mode == "blender" and api_only(first):
                step["sampler"].update(second="skipped", why="api_faults",
                                       api=sorted(set().union(*(api_names(c) for c in first))))
            else:
                if mode == "blender":
                    step["sampler"]["second"] = "asked"
                msgs = H.teacher_copy(req["messages"], H.hints_for(self.plan, i, mode, env.facts, failures))
                told = H.teacher_lines(mode, failures)
                options = SECOND_OPTIONS if mode == "blender" else SECOND_OPTIONS_CODE
                new = [self.draw(step, env.models["second"], msgs, "second", k, options=options)
                       for k in range(SECOND_SAMPLES)]
                self.check_batch(step, new, req, told, False)
                if self.pick(step, new, "second"):
                    return
                groups = (("cand", first), ("second", new))
                if mode in CODE_MODES and (self.rewrite_tests(step, groups) or self.untested(step, groups)):
                    return
        if not self.soft_keep(step, groups):
            self.drop(step)

    def teacher_batch(self, step, n, failures, purpose, alone):
        """One batch of n teacher samples for a step, its notes naming the earlier tries' failures, checked
        (check_batch) and judged (pick); their failures are added to failures (after the judge, whose reasons a
        section's next try is told). True when one was kept."""
        env, mode, i, req = self.env, step["mode"], step["index"], step["request"]
        msgs = H.teacher_copy(req["messages"], H.hints_for(self.plan, i, mode, env.facts, failures))
        told = H.teacher_lines(mode, failures)
        new = [self.draw(step, env.models["teacher"], msgs, purpose, len(step["candidates"])) for _ in range(n)]
        self.check_batch(step, new, req, told, alone)
        if self.pick(step, new, "cand"):
            return True
        failures += _failures(new, mode)
        return False

    def check_batch(self, step, new, req, told, alone):
        """precheck on a batch of new candidates, then a code step's tests when they are due (tests_due), then the
        gate on those that passed precheck."""
        ready = [c for c in new if self.precheck(step, c, req, told)]
        if step["mode"] in CODE_MODES and not alone and self.tests_due(step, ready):
            self.write_tests(step, ready)
        for c in ready:
            self.gate(step, c, alone)

    def draw(self, step, model, msgs, purpose, sample, options=None):
        r = ask(self.env, model, msgs, purpose=purpose, worker=True, sample=sample, options=options)
        step["seconds"]["teacher"] += r.wall_s or 0.0
        c = dict(_call(r), content=r.content or "", stats=r.stats, thinking_chars=r.thinking_chars,
                 runaway=r.runaway, verdict=None, gate=None, judge=None, crash=None, reasons=[], stage="reply",
                 mech=False, passed=False)
        step["candidates"].append(c)
        c["index"] = len(step["candidates"]) - 1
        return c

    def precheck(self, step, c, req, told=()):
        """The checks before the gate, after the reply's decorated form is made plain (normalised): the reply,
        harmony leftovers and the teacher's notes repeated (told: what of the failures only the teacher's notes
        listed, hints.teacher_lines, less what req itself says: hints.echoed_note) or, for a Blender step, a Blender
        version req doesn't name (hints.version_leak: c["echoed"] "version_leak") or the notes' words for the
        Blenders and the sandbox (hints.notes_leak: "notes_leak"), which the build asks too, all teacher_note; then
        the Go validator and the example's size. Keeps the whole verdict on c["_verdict"] for the gate, which takes
        it off before the record is written."""
        normalised(step["mode"], c, lone=bool(step.get("lone")))
        text = c["content"]
        if c["runaway"]:
            c["reasons"].append("runaway")
        elif c["done_reason"] == "length":
            c["reasons"].append("length")
        elif not text.strip():
            c["reasons"].append("empty")
        if c["reasons"]:
            return False
        c["stage"] = "harmony"
        if HARMONY.search(text):
            c["reasons"].append("harmony")
            return False
        asked = "\n".join(m.get("content") or "" for m in req["messages"])
        note = H.echoed_note(text, told, request=asked) or \
            (step["mode"] == "blender" and (H.version_leak(text, asked) or H.notes_leak(text, asked))) or None
        if note:
            c["reasons"].append("teacher_note")
            c["echoed"] = note
            return False
        c["stage"] = "validator"
        v = self.validate(step, text, c["done_reason"])
        c["verdict"] = _verdict_rec(v)
        if not v.get("form_ok"):
            issues = v.get("issues") or []
            codes = [x["code"] for x in issues if x.get("level") == "error"] if not v.get("ok") else \
                [x["code"] for x in issues if x.get("level") == "warn"]  # a near miss of the written form
            c["reasons"].append("validator:" + ",".join(sorted(set(codes))))
            return False
        c["stage"] = "size"
        if msgs_tokens(req["messages"]) + est_tokens(text) > MAX_EXAMPLE_TOKENS:
            c["reasons"].append("too_big")
            return False
        c["stage"] = "gate"
        c["_verdict"] = v  # the whole verdict, for the gate (which takes it off again)
        return True

    def validate(self, step, text, done_reason):
        """The Go validator's whole verdict on a step's piece, as precheck asks it."""
        st = self.plan["steps"][step["index"]]
        return self.env.chimera.validate([{"text": text, "mode": step["mode"], "sid": step["sid"],
                                           "deps": step["deps"], "lone": step["lone"], "step": st,
                                           "done_reason": done_reason or "stop", "reject_cut": True,
                                           "max_tokens": MAX_TARGET_TOKENS}])[0]

    def gate(self, step, c, alone, untested=False):
        """The mode's gate on a candidate that passed precheck, then dep_honesty on one it passed (honest);
        c["mech"] says whether it passed both. A Blender run takes its crash from the Blender whose sheet the request
        (a repair's own) carries first. A code step's tests are those it has (tests_for), none when untested; a
        candidate that passes unconfirmed ones confirms them unless its hollow copy passes them too (tests_check on
        it, kept as tests["confirm"])."""
        env, i, mode = self.env, step["index"], step["mode"]
        v = c.pop("_verdict")
        t0 = time.monotonic()
        if mode == "blender":
            if env.blender is None:
                g = {"ok": False, "reasons": ["no_blender"], "crash": None}
            else:
                prefer = (c.get("inputs") or step["inputs"])["names"]
                g = env.blender.piece_check(self.plan, i, c["content"], v, {} if alone else self.earlier(i),
                                            self.goal, joined=not alone, prefer=prefer)
        elif mode in CODE_MODES:
            tests = None if alone or untested else tests_for(step)
            # the layout stage reads the piece's imports against the pieces its request was built from: a variant's
            # inputs too, though it is otherwise checked alone
            project = (c.get("inputs") or step["inputs"])["outputs"] if mode == "files" else None
            g = env.code.piece_check(self.plan, i, c["content"], v, {} if alone else self.earlier(i), mode,
                                     tests=tests, goal=self.goal, project=project)
            t = step["tests"]
            if tests is not None and not t["valid"] and (g.get("tests") or {}).get("passed"):
                # passing isn't enough: tests that only name this step's symbols pass a hollow piece too
                tc = env.code.tests_check(self.plan, i, t["code"], self.earlier(i), [c["content"]], mode,
                                          goal=self.goal)
                t.update(valid=tc["valid"], why=tc["why"], unconfirmed=tc["why"] in UNCONFIRMED, confirm=tc)
                if tc["valid"]:
                    t["confirmed_by"] = {"repair" if "turn" in c else "cand": c["index"]}
        else:  # the dependencies' kept pieces, as the judge is shown them, those that failed, last round's part
            g = prose_gate.section_check(self.plan, i, c["content"], v, self.earlier_sections(i),
                                         dep_texts=self.dep_outputs(step), missing_deps=tuple(step["missing_deps"]),
                                         prev_result=self.prev_part(step))
        step["seconds"]["checks"] += time.monotonic() - t0
        c["gate"] = g
        c["crash"] = g.get("crash")
        c["reasons"].extend(g.get("reasons") or [])
        if mode == "section":
            c["stage"] = "gate:prose"
        else:  # the code gate says where it stopped; the Blender gate's reasons do
            c["stage"] = "gate:" + (g.get("stage") or _blender_stage(g.get("reasons") or []))
        c["mech"] = bool(g.get("ok"))
        if c["mech"]:
            c["mech"] = self.honest(step, c)
        elif soft(c["reasons"], self.used(step)):  # failed only softly: may be kept as a dependency, so held to it too
            self.honest(step, c, stage=False)
        if c["mech"]:
            c["stage"] = "judge"
        return c["mech"]

    def honest(self, step, c, stage=True):
        """dep_honesty on a candidate its mode's gate passed, before the judge (in every mode; it saves the judge's
        call): its handoff mustn't claim the output of a dependency its request says failed, nor list nothing under
        assumed then. The request is Chimera's own for that candidate (a repair's own, else the step's), never the
        teacher's copy. On a fault its reasons join the candidate's (stage DEP_STAGE, past every gate stage), and its
        tell lines go into the gate's, which _failures gives the next try's notes. The result is kept on the gate
        ("dep_honesty") whenever a dependency failed. True when it passed. Also on a candidate whose gate failed it
        only softly (stage False: its stage stays the gate's, so soft_keep still ranks it by its gate): such a try may be
        kept as a dependency (soft_keep), so its claims belong in its no_example, the report's after_audit counts
        them, and the next batch hears of them with its output or camera line, not a batch later (of the 12 stored
        Blender tries that fail only softly today, 7 were written with a dependency missing and 4 of those claim it
        or list nothing; X58 needs both lines)."""
        req = c.get("request") or step["request"]
        got = DH.check(req["messages"], c["content"])
        if got["missing"]:
            c["gate"]["dep_honesty"] = {k: got[k] for k in ("ok", "reasons", "claims", "missing", "unlisted")}
        if got["ok"]:
            return True
        c["reasons"].extend(got["reasons"])
        c["gate"]["tell"] = list(c["gate"].get("tell") or []) + list(got["tell"])
        if stage:
            c["stage"] = DEP_STAGE
        return False

    def tests_due(self, step, ready):
        """Whether a code step's tests are written now, with ready (the batch's candidates that passed precheck): at
        the first batch that has any, so a step none of whose tries gets that far asks for none, and again at the
        first later batch with a Python file when the earlier one had none (why "no_python")."""
        t = step["tests"]
        if not ready or (t is not None and t.get("why") != "no_python"):
            return False
        return t is None or not CG.no_python([c["content"] for c in ready], step["mode"],
                                             words=step_words(self.plan, step["index"]),
                                             python_project=self.python_project(step))

    def write_tests(self, step, ready):
        """The teacher's tests for a code step, written before its first candidate is checked (tests_due) and judged
        on that batch's candidates (code_gate.tests_check). Tests that fail on the stub but on every one of them too
        are unconfirmed, not invalid: what failed them may be the candidates (tests_for). None are asked for while
        the batch has no Python file, the step's own title and instructions don't ask for one and the round isn't a
        Python project (code_gate.no_python with python_project: files of other languages can't be imported; a
        Python step whose tries left their .py files out keeps its tests), and a reply the reader refuses for a rule
        it breaks (judges.TESTS_REFUSED, every why of REFUSED: a process started, names guessed, code that doesn't
        compile, no assert reached) is answered once with why, after it in the same conversation
        (judges.tests_retry_messages, t["refused"]); a reply that gives no tests leaves the reader's reason as why
        (judges.parse_tests_why: "subprocess" for one refused again, "no_tests" for an empty one). What the retry
        gave is t["retry"] (_retry_gave, and whether the step's words name a callable): an empty retry is no
        refusal, so only one refused again joins t["refused"], and without its call's key and time, which t's own
        fields already are (a key twice in a record would have the report take its time off the step twice)."""
        env, i, mode = self.env, step["index"], step["mode"]
        if CG.no_python([c["content"] for c in ready], mode, words=step_words(self.plan, i),
                        python_project=self.python_project(step)):
            step["tests"] = {"model": None, "key": None, "code": None, "valid": False, "why": "no_python",
                             "check": None, "unconfirmed": False}
            return
        msgs = J.tests_messages(self.goal, self.plan, i, mode, self.dep_pieces(i))
        r = ask(env, env.models["teacher"], msgs, purpose="tests", fmt=J.FMT, options=J.OPTIONS)
        step["seconds"]["tests"] += r.wall_s or 0.0
        code, why = _read_tests(r)
        refused, retry = [], None
        if code is None and why in J.TESTS_REFUSED:
            refused.append(dict(_call(r), why=why))
            r = ask(env, env.models["teacher"], J.tests_retry_messages(msgs, r.content, why), purpose="tests",
                    fmt=J.FMT, options=J.OPTIONS)
            step["seconds"]["tests"] += r.wall_s or 0.0
            code, why = _read_tests(r)
            retry = {"why": why or "", "gave": _retry_gave(r, code, why),
                     "callable": names_callable(step_words(self.plan, i))}
            if retry["gave"] == "refused":
                refused.append({"model": r.model, "why": why, "retry": True})
        t = dict(_call(r), code=code, valid=False, why="" if code else (why or "no_tests"), check=None,
                 unconfirmed=False)
        if refused:
            t["refused"] = refused
        if retry:
            t["retry"] = retry
        step["tests"] = t
        if code:
            tc = env.code.tests_check(self.plan, i, code, self.earlier(i), [c["content"] for c in ready], mode,
                                      goal=self.goal)
            t.update(valid=tc["valid"], why=tc["why"], check=tc, unconfirmed=tc["why"] in UNCONFIRMED)

    def dep_pieces(self, i):
        """{sid: text or None} of step i's dependencies' kept pieces, as the tests writer is shown them."""
        return {f"s{j + 1}": self.kept.get(self.plan["steps"][j]["id"]) for j in dep_indexes(self.plan, i)}

    def dep_outputs(self, step):
        """{sid: text or None} of a step record's dependencies as its own request got them (a variant's outputs, a
        failed dependency's None), as the prose judge and the prose gate are shown them."""
        outputs = step["inputs"]["outputs"]
        return {f"s{j + 1}": outputs.get(self.plan["steps"][j]["id"]) for j in dep_indexes(self.plan, step["index"])}

    def mode_of(self, j):
        """Step j's mode as Chimera gives it (contract.planinfo.step_mode, Go's stepMode: every code step of a plan
        has the plan's one code mode), so a step's earlier steps need no records of their own."""
        return planinfo.step_mode(self.plan, j, self.goal)

    def project_pieces(self, step):
        """The earlier pieces of the project a step record stands in, by plan id: the round's earlier kept pieces,
        and those its request was built from over them (a variant's inputs: a mixed_pool's dependency rewritten
        under today's prompt). A failed_dep variant's left-out dependency is still the project's."""
        return dict(self.earlier(step["index"]), **{k: v for k, v in step["inputs"]["outputs"].items() if v})

    def given(self, step):
        """The texts of project_pieces, for code_gate.import_fault's written: what they write is the project's. A
        variant is checked alone, so its import run can't see them (a mixed_pool's dependency, rewritten under
        today's prompt, may name its module as no step does; a failed_dep variant's left-out one wrote the module
        its piece imports)."""
        return list(dict.fromkeys(self.project_pieces(step).values()))

    def dropped_code(self, step):
        """The plan ids of the earlier code steps (files or python-script) whose piece the step's request didn't
        carry: those the round dropped and, for a failed_dep variant, the one left out. Only their words may excuse a
        bare module name in code_gate.import_fault and tests_fault (outside_project): a dropped one may have been
        the step to write it, while a kept one is in the project, so the import run already shows it didn't. Real:
        an earlier writing step's "Keep the data so that `openpyxl` can read it later" would keep a piece that never
        got past `import openpyxl`."""
        i, have = step["index"], step["inputs"]["outputs"]
        return tuple(st["id"] for j, st in enumerate(self.plan["steps"][:i])
                     if self.mode_of(j) in CODE_MODES and st["id"] not in have)

    def python_project(self, step):
        """Whether the step's round is a Python project, for code_gate.no_python: an earlier kept piece of the round,
        or a dependency piece the step's request carried, is Python (a python-script step's piece, or a files piece
        with a .py file). Most steps of such a project never say Python themselves ("Implement the `find`
        sub-command": 11 of the smoke's 22 code steps of Python projects), so a try that writes only its docs page
        would otherwise ask for no tests."""
        index = {st["id"]: j for j, st in enumerate(self.plan["steps"])}
        return any(_is_python(text, self.mode_of(index[pid])) for pid, text in self.project_pieces(step).items()
                   if pid in index)

    def prev_part(self, step):
        """The previous round's result as a round-2+ step's request gives it, for prose_gate.section_check's
        prev_result: the step's own part (contract.join.find_part, Go's findPart byte for byte), or the result cut
        to 6,000 bytes when that isn't found; the whole result if the request somehow doesn't hold that text. "" in
        round 1."""
        prev = step["inputs"].get("prev_result")
        if not prev:
            return ""
        part = find_part(prev, self.plan, step["index"], step["mode"])[0]
        asked = "\n".join(m.get("content") or "" for m in step["request"]["messages"])
        return part if part in asked else prev

    def settle_tests(self, step):
        """A code step's tests_status, once it is solved. A piece kept with no tests that ran on it (none were
        written, they were refused and not replaced, or they didn't count; a variant, checked alone) is asked
        code_gate.import_fault first: "third_party" when its import run ended on a package outside the standard
        library that nothing in the project provides (python-docx, openpyxl: research_draft-0009-04 s4 and
        planning-0002-08 s6 in the smoke), since such a piece never ran here; kept as step["import_fault"], so
        tests_status says "none:third_party" and the build drops it. Its dropped are the earlier code steps the
        request lacked (dropped_code), and its written the round's earlier pieces with those the request was built
        from (given). A piece kept untested has tests_fault's reading already (untested). Then step["nothing_ran"]:
        whether the kept gate ran nothing on the piece, neither tests nor an import run (ran_nothing; a files piece
        with no .py file, or whose modules do things when imported, and no tests), which the build marks
        unverified, as none:no_python. Asked again when the plan check swaps an alternate in (try_alternates): both
        readings are of the kept piece's own gate."""
        got = step.get("kept")
        t = step.get("tests") or {}
        step.pop("import_fault", None)
        if got:
            item = (step["repairs"] if got["from"] == "repair" else step["candidates"])[got["index"]]
            gate = item.get("gate") or {}
            if not t.get("kept_untested") and not gate.get("tests"):
                step["import_fault"] = CG.import_fault(gate, self.plan, step["index"],
                                                       [c["content"] for c in step["candidates"] + step["repairs"]],
                                                       dropped=self.dropped_code(step), written=self.given(step))
            step["nothing_ran"] = ran_nothing(gate)
        step["tests_status"] = tests_status(step)

    def rewrite_tests(self, step, groups):
        """One rewrite of unconfirmed tests that failed every candidate whose only fault they were: the teacher is
        shown, for each such candidate, the failing assert line of its own tests, the error's last line and the
        candidate's provides line (never its code: _tests_failure), and the new tests are judged on those candidates
        as the first were (tests_check: they fail on the stub, pass on one, fail on its hollow copy). If they count,
        they are the step's tests from then on (the old ones under tests["rewrite"]["old"]) and those candidates are
        gated with them again and picked as usual, the teacher's first; else the old ones stay. The attempt is
        tests["rewrite"], and the error the new tests gave each of those candidates tests["rewrite_errors"]
        ([{"from", "index", "error"}], those they failed); none is asked when code_gate.tests_fault already says
        "third_party" (every run misses a package outside the standard library that the candidates import, which no
        tests can change: {"skipped": "third_party"}). groups: [(source, candidates)]. True when a piece was kept."""
        env, i, mode = self.env, step["index"], step["mode"]
        t = step["tests"]
        if not t or not t.get("unconfirmed") or not t.get("code"):
            return False
        failed = [(source, c) for source, cands in groups for c in cands if c["reasons"] == ["tests_failed"]]
        if not failed:
            return False
        errors, run_errors, texts = _tests_ran(step)
        if CG.tests_fault(dict(t, errors=errors, run_errors=run_errors), self.plan, i, candidates=texts,
                          dropped=self.dropped_code(step)) == "third_party":
            t["rewrite"] = {"skipped": "third_party"}
            return False
        told = [_tests_failure(t["code"], c) for _, c in failed]  # one each: the writer is told how many shared one
        r = ask(env, env.models["teacher"],
                J.tests_rewrite_messages(self.goal, self.plan, i, mode, self.dep_pieces(i), t["code"], told),
                purpose="tests", fmt=J.FMT, options=J.OPTIONS)
        step["seconds"]["tests"] += r.wall_s or 0.0
        code, why = _read_tests(r)
        rw = dict(_call(r), code=code, failures=told, valid=False, why="" if code else (why or "no_tests"),
                  check=None)
        t["rewrite"] = rw
        if not code:
            return False
        tc = env.code.tests_check(self.plan, i, code, self.earlier(i), [c["content"] for _, c in failed], mode,
                                  goal=self.goal)
        rw.update(valid=tc["valid"], why=tc["why"], check=tc)
        # what the new tests said of each candidate they failed, for the report: code_gate.tests_fault may still find
        # the old tests unreachable (another step's module) when the new ones reached the piece and failed it
        t["rewrite_errors"] = [{"from": source, "index": c["index"], "error": e}
                               for (source, c), e in zip(failed, tc.get("errors") or []) if e]
        if not tc["valid"]:
            return False
        rw["old"] = {k: t[k] for k in ("code", "why", "check") if k in t}
        t.update(code=code, valid=True, why="", check=tc, unconfirmed=False)
        for _, c in failed:
            c["before_rewrite"] = {"gate": c["gate"], "reasons": c["reasons"], "stage": c["stage"]}
            c.update(reasons=[], crash=None, mech=False, stage="gate",
                     _verdict=self.validate(step, c["content"], c["done_reason"]))
            self.gate(step, c, False)
        for source, _ in groups:
            if self.pick(step, [c for s, c in failed if s == source], source):
                return True
        return False

    def judge(self, step, c):
        """The judge on a candidate that passed the gate: the scene judge (Blender), the prose judge (sections, with
        qwen3.8:27b's second opinion on a share of those it keeps), none for code. True when accepted. A section
        written with a dependency missing (missing_deps, a failed_dep variant) always gets the second opinion when
        gpt-oss keeps it, and is kept only if qwen3.8 keeps it too, whatever gpt-oss's score (rule "missing_dep"), as
        a sampled second opinion decides for any section: in the smoke, such sections invented the facts the missing
        step was to give, a resample was kept at 4 on one judge's word, and of those gpt-oss gave 5, one sent a road
        trip's fuel stops past its destination and one made up part numbers.

        A scene judge's rejection whose only reasons are a size, a position or an output form the step names
        (judges.overruled) is overruled (judge["rule"] "overruled", "overruled": its kinds) when it rests on a
        measurement (decided Nov 6): each size or position claim names a thing the gate's readers read a value for (a
        size with every side given, blender_gate.asked_sizes; a point, geometry.asked_places), its words all among the
        reading's and no other object of the try's listing (its gate "scene") going by them, which size_mismatch and
        place_mismatch measured before the judge was asked, or, naming none, every object of the listing is one they
        read; a claim on a single dimension, a relative place, a variable's side or another thing sharing a word with
        a read one ("the side table" beside the coffee table read) stands.
        The contract's shape replaces any output form, so that claim needs no measurement. The fourth smoke's 4
        Blender rejections all rested on such claims, and two cost yield (DATAGEN-SMOKE.md, "Why Blender still yields
        little", item 4). Overruled, not asked again: a second opinion from qwen3.8 means swapping it in for gpt-oss
        (the gate keeps them apart)."""
        env, i, mode = self.env, step["index"], step["mode"]
        if mode in CODE_MODES:
            return True
        if mode == "blender":
            msgs = J.scene_messages(self.goal, self.plan, i, (c.get("verdict") or {}).get("handoff"),
                                    (c.get("gate") or {}).get("scene"))
            parse, keep = J.parse_scene, (lambda p: bool(p) and p["ok"])
        else:
            msgs = J.prose_messages(self.goal, self.plan, i, c["content"], self.dep_outputs(step))
            parse, keep = J.parse_prose, J.prose_kept
        r = ask(env, env.models["teacher"], msgs, purpose="judge", fmt=J.FMT, options=J.OPTIONS)
        step["seconds"]["judge"] += r.wall_s or 0.0
        parsed = None if r.runaway else parse(r.content)
        ok = keep(parsed)
        c["judge"] = dict(_call(r), verdict=parsed, ok=ok, second=None)
        kinds = J.overruled(parsed, self.plan, i, (c.get("gate") or {}).get("scene")) \
            if mode == "blender" and not ok else []
        if kinds:
            ok = True
            c["judge"].update(ok=True, rule="overruled", overruled=kinds)
        missing = mode == "section" and (bool(step["missing_deps"]) or step["variant"] == "failed_dep")
        if ok and mode == "section" and (missing or chance(env.size.get("prose_second", 0.0), "prose2", self.seed_id,
                                                           self.n, step["sid"], step["variant"] or "", c["index"])):
            r2 = ask(env, env.models["second"], msgs, purpose="judge", fmt=J.FMT, options=J.OPTIONS)
            step["seconds"]["judge"] += r2.wall_s or 0.0
            p2 = None if r2.runaway else parse(r2.content)
            c["judge"]["second"] = dict(_call(r2), verdict=p2, ok=keep(p2))
            ok = keep(p2)
            if missing:
                c["judge"]["rule"] = "missing_dep"
            c["judge"]["ok"] = ok
        if not ok:
            c["reasons"].append("judge")
        return ok

    def pick(self, step, new, source):
        """Keep the first of new's gated candidates the judge accepts (fewest validator warnings, then shortest,
        first); the passing ones after it are the step's alternates. A variant is judged too (a Blender one on the
        scene its alone run made)."""
        ok = sorted((c for c in new if c["mech"]), key=lambda c: (_warnings(c), len(c["content"]), c["index"]))
        for k, c in enumerate(ok):
            if not self.judge(step, c):
                continue
            c["passed"] = True
            step["kept"] = {"from": source, "index": c["index"]}
            seen = {c["content"]}
            for a in ok[k + 1:]:
                if a["content"] not in seen:
                    seen.add(a["content"])
                    step["alternates"].append(a["index"])
            return True
        return False

    def repair(self, step, failures):
        """Up to REPAIR_TURNS repairs of the candidate that got furthest with a crash in its own piece, through
        Chimera's own repair request; a turn that crashes again is repaired in the next. The gates take a crash only
        from what Chimera's own check could show (a compile, the import run, a Blender run), never from a failure of
        the teacher's tests. True when one passed; it is an example (rp["example"]) only if Chimera could send its
        request (repair_names; a files piece has no line map, so never), it changes at most REPAIR_SHARE of the
        piece's code lines (rp["share"], rp["lines_changed"]: code_lines, since format 4, so comments, docstrings and
        blank lines it rewords or adds don't count) and it leaves out at most REPAIR_SHRINK of them net (rp["shrink"]:
        a repair that deletes what fails isn't one to learn from; repair_measures)."""
        env, i, mode = self.env, step["index"], step["mode"]
        crashed = [c for c in step["candidates"] if c.get("crash")]
        if not crashed:
            return False
        base = max(crashed, key=lambda c: (_progress(c), -len(c["reasons"]), -c["index"]))
        ref = {"cand": base["index"]}
        for turn in range(1, REPAIR_TURNS + 1):
            names, sendable = self.repair_names(step, base["crash"])
            inputs = dict(step["inputs"], names=names, piece=base["content"], crash=base["crash"])
            req = self.request(inputs)
            lint = (base.get("gate") or {}).get("lint") or []
            told = [base["crash"]] + [f for f in lint if f.get("level") == "error"]
            # its own crash and lint last: the notes list the newest failure lines, and its names' facts go first
            msgs = H.teacher_copy(req["messages"], H.hints_for(self.plan, i, mode, env.facts, failures + told))
            r = ask(env, env.models["teacher"], msgs, purpose="repair", worker=True, sample=0)
            step["seconds"]["teacher"] += r.wall_s or 0.0
            rp = dict(_call(r), turn=turn, **{"from": ref}, crash=base["crash"], inputs=inputs,
                      request={"messages": req["messages"], "need_ctx": req["need_ctx"]},
                      request_tokens=msgs_tokens(req["messages"]), content=r.content or "", stats=r.stats,
                      thinking_chars=r.thinking_chars, runaway=r.runaway, verdict=None, gate=None, judge=None,
                      reasons=[], stage="reply", mech=False, passed=False, lines_changed=None, share=None,
                      shrink=None, example=False, sendable=sendable and mode != "files")
            step["repairs"].append(rp)
            rp["index"] = len(step["repairs"]) - 1
            if self.precheck(step, rp, req, H.teacher_lines(mode, failures + told, sent=[base["crash"]])):
                self.gate(step, rp, False)
            rp["lines_changed"], rp["share"], rp["shrink"] = repair_measures(piece_code(base["content"]),
                                                                             piece_code(rp["content"]))
            if rp["mech"] and self.judge(step, rp):
                rp["passed"] = True
                rp["example"] = rp["sendable"] and rp["share"] is not None and rp["share"] <= REPAIR_SHARE and \
                    rp["shrink"] <= REPAIR_SHRINK
                step["kept"] = {"from": "repair", "index": rp["index"]}
                return True
            failures += _failures([rp], mode)
            if not rp.get("crash"):
                return False
            base, ref = rp, {"repair": rp["index"]}
        return False

    def repair_names(self, step, crash):
        """(names, sendable): the sheet a Blender repair's request carries, and whether Chimera could send it.
        Chimera prints the sheet with the Blender its check runs, so the sheet is the crashed Blender's (its runner,
        "Blender 5.0.1") when the step drew one; if that version has no sheet here, the step's stays and the request
        isn't one Chimera sends. A step that drew no sheet keeps none."""
        drawn = step["inputs"]["names"]
        if step["mode"] != "blender" or drawn is None:
            return drawn, True
        v = (crash.get("runner") or "").split()[-1:]
        if v == [drawn]:
            return drawn, True
        if v and v[0] in self.env.names:
            return v[0], True
        return drawn, False

    def untested(self, step, groups):
        """Tests that failed on the stub and on every candidate stay unconfirmed: the candidates that failed nothing
        but them are gated again without them (the import run decides; the tests' gate is kept on c["with_tests"])
        and one is kept. Its step's tests_status is "unconfirmed", unless code_gate.tests_fault finds the tests could
        never have passed for a reason that isn't the pieces' ("tests_unreachable": a sandbox refusal, a module no
        step names, another step's module that none this one depends on names while the kept piece wrote its own
        file; "third_party": a module outside the standard library the candidates import), read from the tests'
        record with every error they and the import runs after them gave on a gate (t["errors"], t["run_errors"]),
        the texts they ran on, the earlier code steps the request lacked (dropped_code) and the kept piece, and kept
        as t["fault"]. groups: [(source, candidates)], tried in order. True when one was kept."""
        t = step["tests"]
        if not t or not t.get("unconfirmed"):
            return False
        for source, cands in groups:
            again = [c for c in cands if c["reasons"] == ["tests_failed"]]
            for c in again:
                c["with_tests"] = {"gate": c["gate"], "reasons": c["reasons"], "stage": c["stage"]}
                c.update(reasons=[], crash=None, mech=False, stage="gate",
                         _verdict=self.validate(step, c["content"], c["done_reason"]))
                self.gate(step, c, False, untested=True)
            if self.pick(step, again, source):
                t["kept_untested"] = True
                t["errors"], t["run_errors"], texts = _tests_ran(step)
                t["fault"] = CG.tests_fault(t, self.plan, step["index"], candidates=texts,
                                            dropped=self.dropped_code(step), kept=kept_target(step)[0])
                return True
        return False

    def drop(self, step):
        """No piece: the step is dropped with the reasons of the candidate (or repair) that got furthest."""
        every = step["candidates"] + step["repairs"]
        best = max(every, key=lambda c: (_progress(c), -c["index"])) if every else None
        step["drop"] = list(best["reasons"]) if best else ["no_candidates"]

    def soft_keep(self, step, groups):
        """No try of a step passed: of those that failed only on SOFT_REASONS (soft; on SOFT_IF_USED's too when a later
        step depends on this one: used), the furthest (then the one with the fewest kinds of soft fault, so an honest
        handoff goes before one that also claims a failed dependency, then the first drawn: candidates in their
        groups' order, then repairs) that the judge accepts, of the first SOFT_JUDGED, is kept for the later steps and
        the join, as a pass is (step["kept"], its source and index), and gives no example: step["no_example"] is its
        reasons, sorted, which examples() and the build read. It is judged as a pass is (the scene judge, the prose
        judge and, with a dependency missing, qwen3.8's word; code has none), since its piece becomes the later steps'
        given material:
        replayed on the second smoke run's records unjudged, three sections the judge had rightly dropped for invented
        benchmarks and part numbers (the audit's D03, D05, D08) came back as soft keeps, because dep_honesty now stops
        them before the judge. It has no alternates and gets no variants (run). Never for a variant, which nothing
        depends on (solve drops it). Of the two smoke runs' 22 kept pieces dep_honesty flags, 14 are a plan's own
        steps, and dropping them would give three later steps a failed dependency of their own (the first run's
        research_draft-0009-04 s3 and n-blender-0002-00 s2, the second's blender-0008-00 s5). ctx_channel is soft only
        on a used step: of the second and third smoke runs' kept Blender pieces, 17 use a ctx key outside the
        contract (blender_gate.ctx_channel, ctx["values"] left out), 13 on a step a later one depends on, which stay
        soft keeps, 3 on a step nothing depends on, which are dropped (smoke2's n-blender-0000-01 r2 s4, smoke3's r2
        s3 and s4: those rounds' joins change), and 1 a variant's; the 8 the audits graded were weak or bad, and the
        build's ctx_channel filter (or one before it) already drops them all. groups: [(source, candidates)] as solve
        drew them; the repairs are "repair"'s. True when one was kept."""
        used = self.used(step)
        tries = [(source, c) for source, cands in tuple(groups) + (("repair", step["repairs"]),) for c in cands
                 if soft(c["reasons"], used)]
        tries.sort(key=lambda x: (-_progress(x[1]), len({r.split(":")[0] for r in x[1]["reasons"]})))  # stable
        for source, c in tries[:SOFT_JUDGED]:
            why = sorted(set(c["reasons"]))
            if self.judge(step, c):
                step["kept"] = {"from": source, "index": c["index"]}
                step["no_example"] = why
                return True
        return False

    # ---- variants

    def make_variants(self, step):
        """The variants of a step with a kept piece (not a soft keep's: run asks only for those) and a dependency it
        got: failed_dep (one such dependency left out) and mixed_pool (one such dependency's output written by
        qwen3.8:27b or qwen3:8b under today's prompt, from the inputs that step had). Each is checked alone and never
        fed to a later step."""
        env, i = self.env, step["index"]
        have = [self.plan["steps"][j]["id"] for j in dep_indexes(self.plan, i)
                if self.plan["steps"][j]["id"] in step["inputs"]["outputs"]]
        if not have:
            return
        sid = step["sid"]
        if chance(env.size.get("failed_dep", 0.0), "failed_dep", self.seed_id, self.n, sid):
            d = rng("failed_dep", self.seed_id, self.n, sid).choice(have)
            outputs = {k: v for k, v in step["inputs"]["outputs"].items() if k != d}
            v = self.variant(step, "failed_dep", outputs)
            v["left_out"] = d
        if chance(env.size.get("mixed_pool", 0.0), "mixed_pool", self.seed_id, self.n, sid):
            pick = rng("mixed_pool", self.seed_id, self.n, sid)
            d = pick.choice(have)
            model = pick.choice([env.models["second"], env.models["small"]])
            j = step_index(self.plan, d)
            dep_step = next(s for s in self.steps if s["index"] == j)
            tm = today.worker_messages(self.plan, j, dep_step["inputs"]["outputs"])
            r = ask(env, model, tm["messages"], purpose="today", worker=True)
            tod = dict(_call(r), dep=d, sid=f"s{j + 1}", content=r.content or "", runaway=r.runaway)
            if r.runaway or not (r.content or "").strip():
                self.variants.append({"sid": sid, "index": i, "variant": "mixed_pool", "today": tod,
                                      "skipped": "today_reply", "kept": None, "candidates": [], "repairs": []})
                return
            outputs = dict(step["inputs"]["outputs"], **{d: r.content})
            v = self.variant(step, "mixed_pool", outputs)
            v["today"] = tod

    def variant(self, step, kind, outputs):
        v = self.step_record(step["index"], outputs, variant=kind)
        self.variants.append(v)
        self.solve(v, alone=True)
        if v["mode"] in CODE_MODES:
            self.settle_tests(v)
        self.log(f"{v['sid']} {kind}: " + ("kept" if v["kept"] else "dropped: " + ", ".join(v["drop"] or [])))
        return v

    # ---- the plan check

    def plan_checks(self):
        """blender_gate.plan_check for a plan with kept Blender pieces, code_gate.plan_check for one with kept code
        pieces. On a failure the culprit's alternates are tried (when no later step depends on it, up to ALTERNATES
        more joins), and a code step that gets one is settled again (settle_tests: an alternate that ran clean after a
        piece whose import missed openpyxl is no longer "none:third_party"); still failing, that kind's steps (and
        their variants and repairs) are plan_failed."""
        env = self.env
        for kind, gate, modes in (("blender", env.blender, ("blender",)), ("code", env.code, CODE_MODES)):
            mine = [s for s in self.steps if s["mode"] in modes]
            if gate is None or not any(s["kept"] for s in mine):
                continue
            res = gate.plan_check(self.plan, self.kept, self.goal)
            pc = {"ok": res["ok"], "result": res, "tries": [], "swapped": None}
            if not res["ok"]:
                self.try_alternates(kind, gate, res, pc)
            if not pc["ok"]:
                for s in mine:
                    s["plan_failed"] = True
                for v in self.variants:
                    if v.get("mode") in modes:
                        v["plan_failed"] = True
            self.rec["plan_check"][kind] = pc

    def try_alternates(self, kind, gate, res, pc):
        k = step_index(self.plan, res.get("culprit") or "") if res.get("culprit") else None
        if k is None:
            return
        later = [m for m in range(k + 1, len(self.plan["steps"])) if k in dep_indexes(self.plan, m)]
        step = next((s for s in self.steps if s["index"] == k), None)
        if later or step is None or not step["alternates"]:
            return
        pid = self.plan["steps"][k]["id"]
        for a in list(step["alternates"])[:ALTERNATES]:
            c = step["candidates"][a]
            if kind == "blender" and c.get("judge") is None and not self.judge(step, c):
                continue
            trial = dict(self.kept, **{pid: c["content"]})
            r2 = gate.plan_check(self.plan, trial, self.goal)
            pc["tries"].append({"alternate": a, "ok": r2["ok"], "reasons": r2["reasons"], "culprit": r2.get("culprit")})
            if r2["ok"]:
                old = step["kept"]  # alternates come only from a round of samples, so this is a candidate too
                step["candidates"][old["index"]]["passed"] = False
                c["passed"] = True
                step["kept"] = {"from": old["from"], "index": a, "swapped_from": old}
                step["alternates"].remove(a)
                self.kept[pid] = c["content"]
                pc.update(ok=True, result=r2, swapped={"sid": step["sid"], "from": old, "to": a})
                if step["mode"] in CODE_MODES:  # import_fault and nothing_ran were the old piece's
                    self.settle_tests(step)
                return


def soft(reasons, used=False):
    """Whether a try's reasons are all soft (each starts with one of SOFT_REASONS, or of SOFT_IF_USED when used: some
    later step depends on its step, Round.used): it failed, but only on them."""
    allowed = tuple(SOFT_REASONS | (SOFT_IF_USED if used else frozenset()))
    return bool(reasons) and all(r.startswith(allowed) for r in reasons)


# ---------------------------------------------------------------- the second sampler's budget (Blender)

# rna_lint's kinds for a name Blender lacks in every version checked (its errors; "syntax" is the script's own)
API_LINT = frozenset({"attr", "socket", "enum", "module", "node_type", "op", "op_arg", "arg", "class"})
# The crashes Blender raises for a name it doesn't have, in the forms the stored smoke runs show (for a line the lint
# can't type: logo.animation_data.action.fcurves): an attribute of one of its types, of a collection or of one of its
# modules, a bmesh operator, an enum value or a collection key. A crash Blender raises for a wrong value (a vector of
# 4 for 3, a read-only attribute, a spline that takes no points) is the script's, not the API's.
_API_CRASH = re.compile(
    r"^AttributeError: '(?!NoneType')(?P<type>[A-Z]\w*)' object has no attribute '(?P<attr>\w+)'"
    r"|^AttributeError: bpy_prop_collection: attribute \"(?P<coll>\w+)\" not found"
    r"|^AttributeError: module '(?:bpy|mathutils|bmesh|bpy_extras)(?:\.\w+)*' has no attribute '(?P<mod>\w+)'"
    r"|^AttributeError: \w+: operator \"(?P<op>\w+)\" doesn't exist"
    r"|^TypeError: [\w.]+\(\): error with keyword argument \"\w+\" - +enum \"(?P<kwenum>[^\"]+)\" not found"
    r"|^TypeError: bpy_struct: item\.attr = val: enum \"(?P<enum>[^\"]+)\" not found"
    r"|^KeyError: 'bpy_prop_collection\[key\]: key \"(?P<key>[^\"]+)\" not found'")
_STRICT = ("alone_strict", "joined_strict")


def _api_word(name):
    """A name as api_names keys it: the last dotted part ("bmesh.ops.create_cylinder": create_cylinder), or the whole
    of a call's keyword ("new_from_object(preserve_all_data=)")."""
    return name if "(" in name else name.rsplit(".", 1)[-1]


def _api_crash(error):
    """The name a crash says Blender doesn't have (_API_CRASH), or None."""
    m = _API_CRASH.match(error or "")
    return _api_word(next(g for k, g in m.groupdict().items() if g and k != "type")) if m else None


def api_names(c) -> set:
    """The Blender API names a try failed on: its lint errors of API_LINT's kinds and its crash's (_api_crash)."""
    g = c.get("gate") or {}
    out = {_api_word(f.get("name") or "") for f in g.get("lint") or []
           if f.get("level") == "error" and f.get("kind") in API_LINT and f.get("name")}
    name = _api_crash((c.get("crash") or {}).get("error"))
    return out | ({name} if name else set())


def api_fault(c) -> bool:
    """Whether a try failed only on Blender API names (api_names): each reason a lint error of API_LINT's kinds or
    a strict run whose crash names one; a try that also failed on anything else (the validator, a crash of its own,
    a check after the run) is not."""
    rs = c.get("reasons") or []
    if not rs or not api_names(c):
        return False
    crash_api = bool(_api_crash((c.get("crash") or {}).get("error")))
    return all((r.startswith("lint:") and r[5:] in API_LINT) or (r.startswith(_STRICT) and crash_api) for r in rs)


def api_only(draws) -> bool:
    """Whether every one of a Blender step's teacher samples failed only on Blender API names (api_fault): then the
    second sampler isn't asked. On the 30 stored Blender steps of smoke2-4 that reached qwen3.8 the two models fail
    on such names about as often (38 of gpt-oss's 120 tries, 21 of qwen3.8's 60), in the same families (an action's
    fcurves, the compositor's tree, video output, SVG import). Where every gpt-oss sample failed so (4 steps with
    the handoff fence fixed, 2 without), qwen3.8's 8 tries gave 2 gate passes, both at one step (an action's fcurves
    reached through getattr probes; in one the keys stay Bezier) and neither an example. A repair doesn't count: it
    shows Chimera's crash and dodges the name (hasattr, deleting the line), which says nothing of what a new sample
    writes."""
    return bool(draws) and all(api_fault(c) for c in draws)


def fault_keys(c) -> frozenset:
    """What a failed try failed on, for telling one batch's faults from another's (heard): each Blender API name
    (api_names), each other lint error and validator code, its crash's error (a strict run with no traceback: its
    first tell line), the label of a teacher note it repeated, and its other reasons as they are; and, for a Blender
    try, the gate's build facts, ctx_channel and global_ctx, which the next batch is told whatever else fails
    (blender_gate.tell_lines) though they join the reasons only once lint and the alone run pass (the independent
    checks, Nov 6: a told fact that came back on a try that crashed was missed, so batches looked disjoint)."""
    g = c.get("gate") or {}
    keys = {"api:" + n for n in api_names(c)}
    keys |= set((g.get("facts") or {}).get("reasons") or ())
    if g.get("ctx_channel"):
        keys.add("ctx_channel")
    if g.get("global_ctx"):  # told whatever else fails too (since the fifth smoke)
        keys.add("global_ctx")
    keys |= {f"lint:{f.get('kind')}:{f.get('name') or ''}" for f in g.get("lint") or []
             if f.get("level") == "error" and f.get("kind") not in API_LINT}
    for r in c.get("reasons") or []:
        if r.startswith("lint:"):
            continue  # its findings, above
        if r.startswith(_STRICT):
            err = (c.get("crash") or {}).get("error") or ""
            if not _api_crash(err):
                keys.add("run:" + (err or next(iter(g.get("tell") or []), r.split(":")[0]))[:160])
        elif r.startswith("validator:"):
            keys.update("validator:" + x for x in r[len("validator:"):].split(","))
        elif r == "teacher_note":
            keys.add("teacher_note:" + str(c.get("echoed") or ""))
        else:
            keys.add(r)
    return frozenset(keys)


def heard(earlier=(), later=()) -> bool:
    """Whether a batch heard its notes: neither batch is empty, none of the earlier batch's faults (fault_keys) came
    back in the later's, so the later tries failed on something new, and the later batch got at least as far (its
    best try's _progress is at least the earlier's best; decided Nov 6: a batch stopped short of where the earlier
    failed, smoke4's n-blender-0000-01 r1 s4 whose first batch reached the joined runs and whose second the validator
    stopped at too_long, says nothing of the notes, and its new faults are only its own). Until the fifth smoke a
    Blender step whose second batch heard its notes got one more told batch before qwen3.8 (a told batch had kept 9 of
    41 Blender steps whose first batch failed); that batch gave no gate pass in the fifth smoke's 6 calls or in the
    replays, so it was retired (Nov 6) and heard is only recorded (step["sampler"]["heard"])."""
    a = set().union(*(fault_keys(c) for c in earlier)) if earlier else set()
    b = set().union(*(fault_keys(c) for c in later)) if later else set()
    if not (a and b) or a & b:
        return False
    return max(_progress(c) for c in later) >= max(_progress(c) for c in earlier)


def tests_for(step):
    """The tests a code step's candidates are gated with: valid ones (tests_check's record), unconfirmed ones as
    their code (a plain string, which piece_check applies), else None."""
    t = step["tests"]
    if not t or not t.get("code"):
        return None
    if t.get("valid"):
        return t
    return t["code"] if t.get("unconfirmed") else None


def tests_status(step):
    """A code step's tests as build and the report read them: "valid" (the kept piece passed tests that count),
    "unconfirmed" (they failed on the stub, no candidate ever passed them, and the piece was kept without them),
    "none:tests_unreachable" or "none:third_party" for such a piece when the tests' failure was their own or the
    sandbox's (untested, code_gate.tests_fault: tests_unreachable also when they reached only another step's module,
    one no step this one depends on names, which the build keeps marked unverified), "none:third_party" also for a
    piece kept with no tests that ran whose import run missed such a package (step["import_fault"],
    Round.settle_tests), "none:tests_refused" when the writer's reply broke a rule the reader refuses (refused_tests:
    its retry, if any, gave none usable either, unless it gave the empty tests TESTS_SYSTEM asks for on a step that
    names nothing to call: "none:no_tests"), else "none:<why>" (why they don't count: "no_python" for a files step
    whose pieces have no Python file and whose own words ask for none, "no_tests" when the writer gave none,
    "variant" for a variant, which is checked alone). The build drops "unconfirmed", "none:third_party" and
    "none:tests_refused" unless --keep-untested."""
    t = step.get("tests")
    if step.get("import_fault"):
        return "none:" + step["import_fault"]
    if step.get("variant"):
        return "none:variant"
    if t and t.get("valid"):
        return "valid"
    if t and t.get("kept_untested"):
        return "none:" + t["fault"] if t.get("fault") else "unconfirmed"
    if refused_tests(t):
        return "none:tests_refused"
    return "none:" + ((t or {}).get("why") or "no_tests")


def refused_tests(t):
    """Whether a step's tests record (write_tests') holds no tests because the writer's reply broke a rule the reader
    refuses (REFUSED: names guessed, a process started, code that doesn't compile, no assert reached) and its one
    retry (t["refused"]; judges.TESTS_REFUSED words each why) gave no usable tests either: such a step is untested
    for the tests' fault, not because there was nothing to test. A why of REFUSED with no retry recorded counts too.
    In the smoke 9 of the 40 stored tests replies would be refused, and one of them was all that caught a broken
    piece (n-python-0001-01 s3). Not refused: a retry that obeyed TESTS_SYSTEM's own rule, a well-formed
    {"tests": ""} (t["retry"]["gave"] "empty") for a step whose words name nothing to call (its "callable" False).
    That step had nothing to test, like one whose first reply was empty ("none:no_tests"), and whether it is kept
    mustn't hang on the writer first breaking a rule (small_task-0014-09 s1's stored tests would be refused today).
    A retry refused again, a runaway, an empty or unreadable reply that isn't that object, or an empty one for a
    step that names a callable (n-python-0001-01 s3) stays refused."""
    t = t or {}
    retry = t.get("retry") or {}
    if t.get("code") or (retry.get("gave") == "empty" and retry.get("callable") is False):
        return False
    return bool(t.get("refused")) or t.get("why") in REFUSED


def step_words(plan, i):
    """Step i's title and instructions, the words code_gate.no_python reads for a Python file the step asks for."""
    st = (plan.get("steps") or [])[i]
    return f"{st.get('title') or ''}\n{st.get('instructions') or ''}"


def names_callable(words):
    """Whether a step's words name something that can be called (_CALLABLE: parse_line(line), main(), a def or a
    class), for the report (a step kept "none:no_tests" whose words do was one the tests writer passed over) and for
    a tests retry that came back empty (refused_tests)."""
    return bool(_CALLABLE.search(words or ""))


def ran_nothing(gate):
    """Whether a code gate's result shows nothing ran on the piece: no tests ("tests" None) and no import run ("run"
    None: a files piece with no .py module that only defines things). Such a piece was only compiled and its other
    files parsed, so the build marks its example unverified, as none:no_python (a page step that got no tests, or a
    Python project's step that wrote only its docs page and was given empty ones)."""
    g = gate or {}
    return not g.get("tests") and not g.get("run")


def _is_python(text, mode):
    """A kept piece of a code step is Python: a python-script piece, or a files piece with a .py file among the File
    lines contract.validate reads (as code_gate reads them)."""
    if mode == "python-script":
        return True
    if mode != "files" or not text:
        return False
    try:
        files = validate_piece(text, "files", reject_cut=False, max_tokens=None).files
    except Exception:  # noqa: BLE001 - a piece the validator can't read writes nothing
        return False
    return any(fp.path.endswith(".py") for fp in files)


def _retry_gave(r, code, why):
    """What the tests writer's one retry gave (write_tests' t["retry"]["gave"]): "tests", "refused" (refused again:
    a why of REFUSED), "runaway", "empty" (the well-formed {"tests": ""} TESTS_SYSTEM asks for when the step names
    nothing to call and no file to check: _empty_tests) or "none" (no tests otherwise: an empty or unreadable reply,
    an object without them)."""
    if code:
        return "tests"
    if r.runaway:
        return "runaway"
    if why in REFUSED:
        return "refused"
    return "empty" if _empty_tests(r.content) else "none"


def _empty_tests(content):
    """content is one JSON object whose "tests" is an empty string, the writer's way to say there is nothing to
    test."""
    try:
        obj = json.loads((content or "").strip())
    except ValueError:
        return False
    return isinstance(obj, dict) and isinstance(obj.get("tests"), str) and not obj["tests"].strip()


def record_format(rec):
    """The DATAGEN_FORMAT a task record was made in: its "format", 1 for the first smoke run's, which carry none."""
    return (rec or {}).get("format") or 1


def _warnings(c):
    return sum(1 for x in (c.get("verdict") or {}).get("issues") or [] if x.get("level") == "warn")


# blender_gate's reasons by prefix, and the gate stage each is found at (_blender_stage's names): ctx_channel,
# build_facts' (validator_warning:<code>, dead_output_key, marker_misused, silent_default) and step 6a's and 6b's
# alone checks (swallowed, skipped_input, attr_miss, place_mismatch, flat_extrusion, doubled_depth) at the alone run,
# nested at the joined one, and global_ctx (since the fifth smoke) there too: read from the code, it is the joined
# script's fault, which a try that passed every alone check reaches
_BLENDER_STAGES = (("lint:", 1), ("alone_strict", 2), ("no_code", 0), ("provides_missing", 3), ("no_probe", 3),
                   ("dupes", 3), ("output_not_asked", 3), ("output_missing", 3), ("camera_not_active", 3),
                   ("ctx_channel", 3), ("attr_miss", 3), ("validator_warning", 3), ("dead_output_key", 3),
                   ("marker_misused", 3), ("silent_default", 3), ("size_mismatch", 3), ("aim_mismatch", 3),
                   ("swallowed", 3), ("skipped_input", 3), ("place_mismatch", 3), ("flat_extrusion", 3),
                   ("doubled_depth", 3), ("join_", 4), ("seam:", 4),
                   ("joined_", 5), ("stand_in", 5), ("removes_earlier", 5), ("nested", 5), ("global_ctx", 5))
# the code gate's stages in order: layout_import (files mode) comes after the symbols and before any run
_CODE_STAGES = {"join": 1, "compile": 2, "symbols": 3, "layout_import": 4, "run": 5, "done": 6}
_PRE = {"reply": 0, "harmony": 1, "validator": 2, "size": 3}
DEP_STAGE = "gate:dep_honesty"  # past the mode's gate, stopped before the judge (dep_honesty)
_DEP_REASONS = ("dep_claimed", "dep_unlisted")  # dep_honesty's: its tell line says them


def _blender_stage(reasons):
    """The furthest Blender gate step a candidate reached, by its reasons' names."""
    names = {1: "lint", 2: "alone", 3: "alone", 4: "join", 5: "joined", 0: "code"}
    worst = None
    for r in reasons:
        for prefix, rank in _BLENDER_STAGES:
            if r.startswith(prefix):
                worst = rank if worst is None else min(worst, rank)
                break
    return names.get(worst, "done")


def _progress(c):
    """How far a candidate got: precheck stages, then its gate's, then dep_honesty's past the whole gate, then the
    judge (higher is further)."""
    st = c.get("stage") or "reply"
    if st in _PRE:
        return _PRE[st]
    if st == "judge":
        return 20 if not c.get("passed") else 30
    if st == DEP_STAGE:
        return 19
    if st.startswith("gate:"):
        g = st[5:]
        if g in _CODE_STAGES:
            return 10 + _CODE_STAGES[g]
        return 10 + {"code": 0, "lint": 1, "alone": 2, "join": 4, "joined": 5, "prose": 1, "done": 6}.get(g, 0)
    return 4


def _failures(cands, mode=""):
    """What hints_for is told about failed candidates. For a Blender or code candidate: the validator's messages for
    the issues that failed it (_validator_lines), its lint errors and crash (rna_lint's and Go's dicts), then its
    gate's tell lines (but one that repeats the crash's error: the crash says it with its line); for a section, a
    plain line for each reason it was dropped (_section_failures), then its gate's tell lines. In the smoke 77 of
    gpt-oss's 86 files pieces failed the validator's form rule and 27 of 28 later tries did again, never told why.
    The tell lines and the validator's messages are hints.Tell lines, paired with the candidate's own content, so the
    echo check leaves out what they quote of it (its handoff's names, say)."""
    out = []
    for c in cands:
        g = c.get("gate") or {}
        own = c.get("content") or ""
        tell = [H.Tell(x, own) for x in g.get("tell") or [] if isinstance(x, str) and x.strip()]
        if mode == "section":
            out += _section_failures(c) + tell
            continue
        out += [H.Tell(x, own) for x in _validator_lines(c)]
        out += [f for f in g.get("lint") or [] if f.get("level") == "error"]
        crash = c.get("crash")
        if crash:
            out.append(crash)
        said = (crash or {}).get("error")  # a code gate's tell line for a crash says it again, without the line
        out += [x for x in tell if not (said and said in x)]
    return out


def _validator_lines(c):
    """The Go validator's messages, in its order, for the issues that failed a candidate in precheck: its errors and
    the form warnings (contract.validate.FORM_CODES) that keep form_ok false. [] for a candidate it passed."""
    v = c.get("verdict") or {}
    if not v or v.get("form_ok"):
        return []
    return [x.get("message") or x.get("code") for x in v.get("issues") or []
            if (x.get("level") == "error" or (x.get("level") == "warn" and x.get("code") in FORM_CODES))
            and (x.get("message") or x.get("code"))]


def normalised(mode, c, lone=False):
    """Make a candidate's decorated form plain before precheck reads it (datagen/normalise): a decorated File line
    ("**File: x**") for the code modes, a stand-in marker whose hyphen is another character (U+2011) for Blender, and
    in every code mode, a step that isn't lone (lone: the contract gives it no handoff), the handoff block at the
    reply's end put in its fence (an untagged fence whose first line is "handoff", a closing fence glued to the
    assumed line: N.handoff_fence). c["content"] becomes the plain text and c["normalised"] says how many lines
    changed ("handoff_fence" only when it fixed something, so a record without it reads as before); the raw reply
    stays in the call cache. Nothing when no line changed."""
    text, files, dashes, fence = c["content"], 0, 0, 0
    if not lone and (mode in CODE_MODES or mode == "blender"):
        text, fence = N.handoff_fence(text)  # first: a handoff block is never a file's block
    if mode in CODE_MODES:
        text, files = N.file_lines(text)
    elif mode == "blender":
        text, dashes = N.marker_dashes(text)
    if files or dashes or fence:
        c["content"] = text
        c["normalised"] = {"file_lines": files, "marker_dashes": dashes}
        if fence:
            c["normalised"]["handoff_fence"] = fence


# ---------------------------------------------------------------- the teacher's tests

def _read_tests(r):
    """(code, why) from a tests writer's reply: judges.parse_tests' code, or None and judges.parse_tests_why's reason
    (None for a runaway, which says nothing about the tests)."""
    if r.runaway:
        return None, None
    code = J.parse_tests(r.content)
    return code, (None if code else J.parse_tests_why(r.content))


def _tests_failure(code, c):
    """What the tests writer's rewrite is told about a candidate its tests (code) failed: {"assert": the failing
    assert line of the tests or "", "error": the error's last line, "provides": the candidate's handoff provides
    line, which names what it made}. Never the candidate's code, so the new tests can't simply fit it."""
    err = ((c.get("gate") or {}).get("tests") or {}).get("error") or ""
    h = (c.get("verdict") or {}).get("handoff")
    provides = (h.get("provides") if isinstance(h, dict) else "") or ""
    return {"assert": failing_assert(code, err), "error": err, "provides": " ".join(str(provides).split())[:300]}


def _tests_ran(step):
    """(errors, run_errors, texts) of the step's candidates and repairs whose gate ran its tests (a candidate gated
    again without them keeps that gate in "with_tests"): every distinct error the tests gave, in order, every
    distinct error of the import run that followed, and those candidates' texts, for code_gate.tests_fault."""
    errors, runs, texts = [], [], []
    for c in step["candidates"] + step["repairs"]:
        g = (c.get("with_tests") or {}).get("gate") or c.get("gate") or {}
        if not g.get("tests"):
            continue
        texts.append(c["content"])
        for out, e in ((errors, g["tests"].get("error")), (runs, (g.get("run") or {}).get("error"))):
            if e and e not in out:
                out.append(e)
    return errors, runs, texts


_PCT = re.compile(r"%(?:\([^)]*\))?[-#0 +]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[diouxXeEfFgGcrsa%]")
_BRACES = re.compile(r"\{[^{}]*\}")


def failing_assert(code, error):
    """The assert line of the tests (code) that a run's last error line (error) most likely came from: an
    AssertionError's message matched against each assert's own (its fixed text, in order: a string, an f-string,
    "..." % x or "...".format(x)), one with no message against the asserts that give none, else the only assert
    there is. "" when that can't be told, and for any other error (its own line says what failed)."""
    if not (error or "").startswith("AssertionError"):
        return ""
    try:
        tree = ast.parse(code or "")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return ""
    asserts = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Assert)), key=lambda n: n.lineno)
    msg = error.split(":", 1)[1].strip() if ":" in error else ""
    if msg:
        hits = [n for n in asserts if n.msg is not None and _says(n.msg, msg)]
    else:
        hits = [n for n in asserts if n.msg is None]
    pick = hits[0] if len(hits) == 1 else asserts[0] if len(asserts) == 1 else None
    if pick is None:
        return ""
    return code.split("\n")[pick.lineno - 1].strip()[:300]


def _says(node, msg):
    """An assert's message (node) could have printed msg: its fixed parts are all in msg, in order."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        parts = [node.value]
    elif isinstance(node, ast.JoinedStr):
        parts = [v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Constant) and \
            isinstance(node.left.value, str):
        parts = _PCT.split(node.left.value)
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format" and \
            isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str):
        parts = _BRACES.split(node.func.value.value)
    else:
        return False
    parts = [p.strip() for p in parts if p.strip()]
    at = 0
    for p in parts:
        k = msg.find(p, at)
        if k < 0:
            return False
        at = k + len(p)
    return bool(parts)


# The fixed wording of a dropped section's lines (ours: hints.echoed_note looks for it in a reply)
HEADING_FAILED = "the heading line wasn't the step's title or a heading its instructions give"
FRAMING_FAILED = "a paragraph about the whole document"
_SECTION_WHY = {"placeholder": "a placeholder (TODO, TBD, [insert ...])",
                "ai_talk": "it mentions being an AI, a model or other workers",
                "unmarked_link": "a link not marked (unverified)"}
_JUDGE_RUNS = H.runs(J.HEADING_LINE) | H.runs(J.HANDOFF_HEAD) | H.runs(J.PROSE_SYSTEM) | \
    H.runs(J.GOAL_HEAD)  # the prose judge's prompt


def _section_failures(c):
    """Plain lines saying why a section candidate was dropped, for the next try's notes: its length against the
    step's own words (and how far to cut, to the note's band), that its heading line wasn't the title or a heading
    the instructions give (HEADING_FAILED; not which it was: the model's words aren't ours to repeat), the framing
    phrases, an earlier section it repeats, the problems of the verdict that turned it down (_rejecting: the judge's
    own words, teacher-only like every note; one that shares a run of words with the judge's prompt only parrots
    ours and is left out) and the validator's own messages for the rest. A reason whose tell line says it (the prose
    gate's, dep_honesty's) gets no line here."""
    g, out = c.get("gate") or {}, []
    issues = {x.get("code"): x.get("message") for x in (c.get("verdict") or {}).get("issues") or []}
    for r in c.get("reasons") or []:
        t = g.get("target")
        if r == "words_over" and t:
            aim = prose_gate.target_band(t) or (0, t["high"])
            out.append(f"length: {g.get('words')} words, too long (the step asks for {t['phrase']}): cut it to "
                       f"about {(aim[0] + aim[1]) // 2 if aim[0] else aim[1]} words")
        elif r == "words_under" and t:
            out.append(f"length: {g.get('words')} words, too short (at least {t['low']})")
        elif r == "heading_not_title":
            out.append(HEADING_FAILED)
        elif r in ("intro", "outro"):
            out.append(f"{FRAMING_FAILED} ({', '.join(g.get('framing') or []) or r})")
        elif r.startswith("overlap:"):
            out.append(f"it repeats much of {r.split(':', 1)[1]}'s section")
        elif r.startswith("validator:"):
            out += [issues.get(code) or code for code in r.split(":", 1)[1].split(",")]
        elif r == "judge":
            problems = [p for p in (_rejecting(c.get("judge")) or {}).get("problems") or []
                        if not H.runs(p) & _JUDGE_RUNS][:3]
            out += [f"a grader found: {p[:200]}" for p in problems] or ["a grader turned it down"]
        elif r in _SECTION_WHY:
            out.append(_SECTION_WHY[r])
        elif r in prose_gate.TELL_REASONS or r.startswith(_DEP_REASONS):  # the gate's tell line says it, quoting
            continue                                                       # the model (_failures adds it)
        elif r not in ("teacher_note", "harmony"):  # about our notes and the reply's tokens, nothing to write better
            out.append(r)
    return out


def _rejecting(judge):
    """The verdict that turned a section down: qwen3.8's second opinion when gpt-oss's own kept it, else gpt-oss's
    (None when unreadable)."""
    j = judge or {}
    second = j.get("second") or {}
    if J.prose_kept(j.get("verdict")) and second and not second.get("ok"):
        return second.get("verdict")
    return j.get("verdict")


# ---------------------------------------------------------------- a seed

def run_seed(env, seed) -> dict:
    """Everything that happens to one seed: {"key", "format" (DATAGEN_FORMAT), "seed", "status" ("done", "no_plan"
    or "error"), "error", "rounds", "round2", "seconds", "finished"}. StopRequested (STOP) passes through: the seed
    isn't finished."""
    t0 = time.monotonic()
    rec = {"key": seed["seed_id"], "format": DATAGEN_FORMAT, "seed": seed, "status": "done", "error": None,
           "rounds": [], "round2": None}
    try:
        planner, plan = plan_round(env, seed, 1)
        if plan is None:
            rec["status"] = "no_plan"
            rec["rounds"].append({"round": 1, "planner": planner, "plan": None})
        else:
            r1 = Round(env, seed, 1, plan, planner)
            rec["rounds"].append(r1.rec)
            r1.run()
            rec["round2"] = second_round(env, seed, r1, rec)
    except StopRequested:
        raise
    except Exception as e:  # noqa: BLE001 - recorded; the seed runs again on resume
        rec["status"] = "error"
        rec["error"] = f"{type(e).__name__}: {e}"[:1000]
        rec["traceback"] = traceback.format_exc()[-3000:]
    rec["seconds"] = round(time.monotonic() - t0, 2)
    rec["finished"] = now_iso()
    return rec


def second_round(env, seed, r1, rec):
    """Round 2, for a share of seeds whose round 1 kept a piece of a plan of 2+ steps: the result check (a failed
    or wrong scene skips the review and is the critique), else the review (done ends the seed), then the planner
    with the result and the critique, and the round's steps as in round 1. Returns why it stopped or "ran"."""
    if not chance(env.size.get("round2", 0.0), "round2", seed["seed_id"]):
        return "not_drawn"
    if len(r1.plan["steps"]) < 2:
        return "one_step"
    if not r1.kept:
        return "nothing_kept"
    result = r1.rec["result"]
    if result is None:
        return "join_fallback"
    if r1.rec["join"]["script_kind"]:
        check = result_check(env, result, seed["text"])
    else:
        check = {"outcome": "skipped", "summary": "the result has no script"}
    r1.rec["check"] = check
    if check.get("outcome") in FAILS_ROUND2:
        critique = check.get("critique") or ""
    else:
        rv = review(env, seed["text"], result)
        r1.rec["review"] = rv
        if not rv["ok"]:
            return "review_unreadable"
        if rv["done"]:
            return "review_done"
        critique = rv["critique"]
    r1.rec["critique"] = critique
    planner, plan = plan_round(env, seed, 2, prior=result, critique=critique)
    if plan is None:
        rec["rounds"].append({"round": 2, "planner": planner, "plan": None, "prior": result, "critique_in": critique})
        return "no_plan"
    r2 = Round(env, seed, 2, plan, planner, prior=result, critique=critique)
    rec["rounds"].append(r2.rec)
    r2.run()
    return "ran"


# ---------------------------------------------------------------- reading records

def examples(rec, keep_plan_failed=False):
    """The training examples a finished seed record gives, before build's filters: one per kept step or variant (its
    request plus the kept piece) and one per repair example (its own request plus the repair). A step kept from a
    repair gives only the repair example: its piece answers the crash message, not the first request (it still
    feeds the later steps and the join). A step kept only for the later steps (step["no_example"]: Round.soft_keep)
    gives none, as a plan_failed one doesn't (even with keep_plan_failed). Each is (messages, info) with info for
    build's meta; a code step's info has its tests_status as "tests" and whether nothing ran on its kept piece as
    "nothing_ran" (settle_tests), which the build marks unverified."""
    out = []
    if rec.get("status") != "done":
        return out
    seed = rec["seed"]
    for rnd in rec.get("rounds") or []:
        for step in (rnd.get("steps") or []) + (rnd.get("variants") or []):
            if not step.get("request") or (step.get("plan_failed") and not keep_plan_failed) or \
                    step.get("no_example"):
                continue
            got = kept_target(step)
            base = {"seed_id": seed["seed_id"], "group": group_of(seed["seed_id"]), "sid": step["sid"],
                    "round": rnd["round"], "kind": step["kind"], "mode": step["mode"], "variant": step["variant"],
                    "names": step["names"], "lone": step["lone"], "missing_deps": len(step["missing_deps"]),
                    "plan_failed": bool(step.get("plan_failed")), "category": seed.get("category"),
                    "seed_source": seed.get("source")}
            if step["mode"] in CODE_MODES:
                base["tests"] = step.get("tests_status")
                base["nothing_ran"] = bool(step.get("nothing_ran"))
            if got and got[2] != "repair":
                content, model, source = got
                out.append((step["request"]["messages"] + [{"role": "assistant", "content": content}],
                            dict(base, model=model, source=source, repaired=False, turn=0,
                                 request_tokens=step["request_tokens"], target_tokens=est_tokens(content))))
            for rp in step.get("repairs") or []:
                if rp.get("example"):
                    out.append((rp["request"]["messages"] + [{"role": "assistant", "content": rp["content"]}],
                                dict(base, model=rp["model"], source="repair", repaired=True, turn=rp["turn"],
                                     names=(rp.get("inputs") or {}).get("names") if step["names"] else None,
                                     request_tokens=rp["request_tokens"], target_tokens=est_tokens(rp["content"]))))
    return out
