"""The training files (DESIGN.md, "build.py"): every kept piece and repair example in tasks.jsonl as an MLX-LM chat
example, filtered, split by seed group, and checked for eval text before anything is published.

    stats = build(data_dir, size)     # sft/train.jsonl, valid.jsonl, train.meta.jsonl, valid.meta.jsonl, STATS.md

From tasks.jsonl only (task.examples): one example per kept step or variant, its request (Chimera's, as the binary
printed it) plus the kept piece, and one per repair example, its own repair request plus the repair. An example is
dropped, in this order, when its seed was made by another version of the data generator (task.record_format isn't
task.DATAGEN_FORMAT: old_format; the first smoke run's records are format 1, checked and judged by rules since fixed),
when its seed was made with other requests than this start's (a fingerprint is given and the record's isn't it, or it
has none), when its step was kept only as a dependency (no_example: below), when it is over 12,288 estimated tokens,
when any of its messages (the system prompt too, as the last check reads the line) overlap an eval text
(tools/check_overlap.EvalIndex at 0.5, which also catches the canaries and the test-fixture mark), when its target
echoes a teacher note (hints.echoed_note) or, for a Blender example, names a Blender version its own request doesn't
(hints.version_leak) or uses the notes' words for the Blenders and the sandbox (hints.notes_leak), when it comes from a
code step whose piece was kept without ever passing the teacher's tests (tests "unconfirmed"), whose piece couldn't run
for a package outside the standard library ("none:third_party") or whose tests writer's replies were refused
("none:tests_refused"; all three kept with keep_untested), when one of the facts filters below finds a fault, when its
messages repeat another example's exactly, when a dependency failed in the run itself and such examples are already
10% of its mode's (failed_dep_share, below), or when it is a repair that would take repairs over 15% of the Blender and
code examples (both caps drop in an order stable_int gives, the last first). 5% of the seed groups (a group is the
teacher call the seed came from, at least one group once there are 4) go to valid, by stable_int("split", group),
plus, once any do, the first group of every mode that has two or more and none there yet (a mode with one group stays
in train, where it teaches), so no group is in both files and the valid loss covers every mode: the smoke run's valid
was three Blender pieces of one seed.

The facts filters (fact_drops, after the second smoke run's audit, DATAGEN-SMOKE.md "Second smoke run"): facts about
the example itself, read from the record, so they cost no model time, change no request and cascade nowhere (a gate on
a first step rewrites every later step's request; a filter only leaves the one example out), and they reach records
made before the gates that now check the same things. In this order, each example dropped by the first that fires
(STATS.md counts every one that fires): dep_claimed (dep_honesty.check on the stored request and the target: a
handoff whose uses line claims output of a dependency the request says failed, or whose assumed line is none with one
failed; on the audit's grades it caught 13 of the 15 bad examples written with a dependency missing, 3 of 4 weak and
0 of 16 ok), validator_warning (the kept candidate's stored verdict carries Chimera's own handoff_long,
uses_undeclared or provides_missing: 4 bad and 3 weak of the graded, 0 ok), unchecked_code (lang_check.build_drop: an
unverified files example with a code file, by its File: extension, that no parser here read and passed, such as the
second run's PowerShell; the kept gate's "parse" says which were read, code_gate putting every parser's result there,
the local ones' too), and for a Blender example ctx_channel and dead_output_key (blender_gate's facts on the piece's
code: a top-level ctx key other than blender_gate.CTX_CONTRACT's scene, collection, objects and values, written or
read, a channel the contract doesn't have, ctx["values"] being the contract's since Nov 4; an output-like
SETTINGS_sN key other than "output", which Chimera never reads, given the plan step, plan_step, so a step that asks
to set the output path itself keeps a piece that applies it). The last two rest on hydra:1.0's values-only first
steps of three new Blender seeds (6-11 of 51 passing pieces, none ok): check them on the next smoke, one by one
(stats.json's facts_examples), before trusting them at night. Rebuilt from the two smoke runs' records (format check
bypassed), they drop 21 and 20 examples, none of the audit's 16 ok ones: of the second run's 47, its 10 bad and 10
weak (X10, X32, X44, X45, X58, X12, X67 dep_claimed; X15, X19 validator_warning; X17, X74, X54 unchecked_code; X13,
X18, X27, X38, X77, X79 ctx_channel; X20, X65 dead_output_key) and one the cap dropped before; of the first's, 11
bad, 3 weak and 6 ungraded.

ctx_channel is a backstop since DATAGEN_FORMAT 4: blender_gate fails every try with such a key at the alone stage
(piece_check's ctx_channel reason, told to the next try), and task.py keeps one only as a dependency (no_example, on
a step a later step depends on: task.SOFT_IF_USED) or drops it, so no format-4 example should carry one, and on
format-4 records the filter should fire on none. A firing there is a hole in the gate (the gate reads the Go
validator's code, the filter the target's python blocks: task.piece_code; on the 457 stored tries with Blender code
they give the same keys): read it in stats.json's facts_examples. It still filters what it always did on older
records rebuilt with the format check bypassed (the offline comparisons), which is why it and FACT_DROPS' order stay
as they were. Since the fourth smoke validator_warning and dead_output_key are backstops the same way: blender_gate
fails a Blender try with either at the alone stage (build_facts, told), but for one case left as it was, Chimera's
handoff_long on a values-only step's provides line, in any form (the user's open contract question; a plain list of
names only from Nov 5 until the decision of Nov 6), which only this filter drops, so on a record made with these gates
it fires on such pieces alone.

A step kept only as a dependency (task.SOFT_REASONS: its best try failed only on faults that leave the piece usable by
later steps, so its piece fed them and the join, step["no_example"] the reasons) gives no example: task.examples
leaves it out, and the build counts it as dropped "no_example" (its example is read here from a copy of the record
without the mark, through task.examples, so the meta is the same as any other's). One kept from a failed repair is
not counted: it would give no example anyway, as a repair example has to pass (REPORT.md counts every such step).

The failed-dependency share (FAILED_DEP_CAP) stays a ceiling, not a target: the plan wants about 10% of examples
written with a dependency missing, and the first smoke run's natural ones were 22% (the worst of them sections that
claimed a failed research step's output). dep_claimed now drops the dishonest ones before the cap counts. Rebuilt
with today's filters, the first run keeps 5 of its 20 examples written with a dependency missing (2 natural, 3
failed_dep variants: 13% of 39, against 32% of the 63 its own build kept) and the cap drops none; the second keeps 1
of its 8 (17% of 47 before), an honest section the cap then drops because its mode kept only 2. So the cap binds
again only in a tiny mode or when honest ones pile up (a seed whose early step failed under many dependents), and
the share now runs under the plan's ~10% until the gate's retries (task.py's dep_honesty stage) replace what the
filter drops. failed_dep variants are drawn at the size's own share and left as they are; STATS.md gives both
shares by mode, so a night shows whether the ~10% is met.

A code example nothing confirmed is kept, since such steps are real, but its meta says "unverified" and STATS.md
counts them by mode: its kept gate ran neither tests nor an import run (task.ran_nothing, the step's "nothing_ran"),
so nothing but a compile and code_gate's parse check of its files looked at it, or its tests could never reach its
code ("none:tests_unreachable": they failed on the sandbox or on another step's module, code_gate.tests_fault; the
false-drops audit found three such steps dropped as unconfirmed whose pieces were right). That is every files example
with no Python file to run ("none:no_python": a page, a JS project, a config), and a Python project's step that got no
tests and wrote only a docs page, or only .py files that do things when imported. The meta also says which generator
format made the example ("format", task.record_format).

The files are written to sft/staging/ first, and tools/check_overlap.py runs on both as a last check. Only when it
passes are they moved into sft/; otherwise they go to sft/flagged/ with its output in OVERLAP.txt, the published
files are removed, and OverlapFound is raised (the run exits 1).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections import Counter, defaultdict

from datagen import blender_gate, dep_honesty, hints, lang_check, task
from datagen.common import HERE, Store, msgs_tokens, stable_int, write_json, write_jsonl

SFT = "sft"
VALID_SHARE = 0.05
MIN_GROUPS_FOR_VALID = 4
REPAIR_CAP = 0.15  # repairs' share of the Blender and code examples
FAILED_DEP_CAP = 0.10  # a ceiling on natural failed-dependency examples' share of their mode's (the plan's ~10%)
UNTESTED = {"unconfirmed": "tests_unconfirmed", "none:third_party": "third_party",
            "none:tests_refused": "tests_refused"}  # tests_status -> drop reason
# kept, marked: no Python to run, only the parse check (records before nothing_ran); tests that couldn't reach the code
UNVERIFIED = ("none:no_python", "none:tests_unreachable")
# in this order; ctx_channel a backstop since format 4 (the gate fails such tries first), kept for older records
FACT_DROPS = ("dep_claimed", "validator_warning", "unchecked_code", "ctx_channel", "dead_output_key")
WARNINGS = frozenset({"handoff_long", "uses_undeclared", "provides_missing"})  # Chimera's validator issue codes
EVAL_THRESHOLD = 0.5
CODE_LIKE = ("blender", "python-script", "files")
FILES = ("train.jsonl", "valid.jsonl", "train.meta.jsonl", "valid.meta.jsonl")
CHECK_OVERLAP = os.path.join(HERE, "tools", "check_overlap.py")
# The plan's mix for v1 (docs/hydra-worker-plan.md, "3. TRAINING DATA"), by the step's kind.
PLAN_MIX = {"blender": 640, "code": 540, "writing": 300, "research": 130, "general": 90}


def mix_kind(mode, kind):
    """The plan's mix an example counts toward: blender, code, or (a section) its step's writing, research or general
    kind."""
    if mode == "blender":
        return "blender"
    if mode in CODE_LIKE:
        return "code"
    return kind if kind in ("writing", "research", "general") else "general"


class OverlapFound(RuntimeError):
    """tools/check_overlap.py flagged a built file: nothing was published (sft/flagged/ holds the files)."""


def _eval_text(messages):
    """What the per-example eval check reads: every message, the system prompt (the plan's title and summary, the
    other steps' outline) included, the same text check_overlap's last run reads in the line, so a hit drops the one
    example instead of failing the whole build."""
    return "\n".join(m.get("content") or "" for m in messages)


def _teacher_note(messages, mode=None):
    """The teacher note a target echoes (hints.echoed_note on each assistant message), or for a Blender example
    (mode) "version_leak" when it names a Blender version the example's own request doesn't (hints.version_leak:
    every other message, a repair's naming the Blender that crashed) and "notes_leak" when it uses the notes' words for
    the Blenders or the sandbox that the request doesn't (hints.notes_leak), or None. Only a Blender step's notes name
    the Blenders: "Django==5.0.1" in a requirements file is no leak."""
    request = "\n".join(m.get("content") or "" for m in messages if m["role"] != "assistant")
    for m in messages:
        if m["role"] == "assistant":
            text = m.get("content") or ""
            note = hints.echoed_note(text) or (mode == "blender" and (
                hints.version_leak(text, request) or hints.notes_leak(text, request))) or None
            if note is not None:
                return note
    return None


def _without_no_example(rec):
    """(rec, {(round, sid, variant): reasons}): a copy of the record whose steps kept only as a dependency
    (step["no_example"]) lose that mark, so task.examples gives their examples as any other's, and those steps'
    reasons; the record itself when it has none. The copy shares everything but the rounds' step lists."""
    soft = {(rnd["round"], s["sid"], s.get("variant")): list(s["no_example"])
            for rnd in rec.get("rounds") or [] for s in (rnd.get("steps") or []) + (rnd.get("variants") or [])
            if s.get("no_example")}
    if not soft:
        return rec, soft

    def plain(steps):
        return [{k: v for k, v in s.items() if k != "no_example"} for s in steps or []]
    return dict(rec, rounds=[dict(rnd, steps=plain(rnd.get("steps")), variants=plain(rnd.get("variants")))
                             for rnd in rec.get("rounds") or []]), soft


def _round_step(rec, info):
    """(round, step) records an example comes from, either None when the record has no such."""
    rnd = next((r for r in rec.get("rounds") or [] if r.get("round") == info["round"]), None)
    step = next((s for s in ((rnd or {}).get("steps") or []) + ((rnd or {}).get("variants") or [])
                 if s.get("sid") == info["sid"] and s.get("variant") == info["variant"]), None)
    return rnd, step


def plan_step(rec, info):
    """The round's plan step an example was written for (its title and instructions, for dead_output_key's step
    excuse), or None."""
    rnd, step = _round_step(rec, info)
    steps = ((rnd or {}).get("plan") or {}).get("steps") or []
    k = (step or {}).get("index")
    return steps[k] if isinstance(k, int) and 0 <= k < len(steps) else None


def kept_item(rec, info):
    """The candidate or repair record an example's target comes from (its stored verdict and gate), or None: a
    repair example's own repair, else the step's kept candidate (task.kept_target's)."""
    _, step = _round_step(rec, info)
    if step is None:
        return None
    if info.get("repaired"):
        return next((rp for rp in step.get("repairs") or [] if rp.get("example") and rp.get("turn") == info["turn"]),
                    None)
    k = step.get("kept")
    items = (step.get("repairs") if k and k.get("from") == "repair" else step.get("candidates")) or []
    return items[k["index"]] if k and k.get("index") is not None and k["index"] < len(items) else None


def collect(data_dir, keep_plan_failed=False):
    """Every example of every finished seed, in tasks.jsonl order: [(messages, meta, item, step)] (meta carries the
    record's fingerprint and format, and for a step kept only as a dependency its reasons as "no_example"; item is
    kept_item's record and step plan_step's, for the facts filters), plus counts of what was left out before the
    filters."""
    recs = Store(os.path.join(data_dir, "tasks.jsonl")).all()
    out, notes = [], Counter()
    for rec in recs:
        notes["seeds " + rec.get("status", "?")] += 1
        if rec.get("status") != "done":
            continue
        rec, soft = _without_no_example(rec)
        every = task.examples(rec, keep_plan_failed=True)
        for msgs, info in every:
            if info["plan_failed"] and not keep_plan_failed:
                notes["plan_failed"] += 1
                continue
            meta = dict(info, fingerprint=rec.get("fingerprint"), format=task.record_format(rec))
            why = soft.get((info["round"], info["sid"], info["variant"]))
            if why and not info.get("repaired"):
                meta["no_example"] = why
            out.append((msgs, meta, kept_item(rec, info), plan_step(rec, info)))
    return out, notes


def fact_drops(msgs, meta, item, step=None) -> list:
    """[(reason, detail)] of every facts filter that fires on an example (FACT_DROPS' order; the build drops it by
    the first): dep_claimed (dep_honesty.check's reasons on the stored request and the target), validator_warning
    (the WARNINGS codes on the kept item's stored verdict), unchecked_code (lang_check.build_drop on the meta, the
    target and the kept gate's "parse": code_gate puts every parser's result there, the local parsers' too; detail:
    [(path, language)]), and for a Blender example ctx_channel and dead_output_key (blender_gate's, on the piece's
    code: the keys, ctx["values"] not among them, as blender_gate.CTX_CONTRACT has it; step, the plan step, lets
    dead_output_key excuse a step that asks to set the output path itself). ctx_channel is a backstop since format 4,
    whose gate fails such a try at the alone stage: on a format-4 record a firing is a hole in the gate. A record
    without a verdict or a gate counts as nothing found there, and one without "parse" as nothing parsed."""
    out = []
    request, target = msgs[:-1], msgs[-1].get("content") or ""
    dep = dep_honesty.check(request, target)
    if dep.get("reasons"):
        out.append(("dep_claimed", sorted(dep["reasons"])))
    item = item or {}
    codes = sorted({x.get("code") for x in (item.get("verdict") or {}).get("issues") or []} & WARNINGS)
    if codes:
        out.append(("validator_warning", codes))
    gate = item.get("gate") or {}
    parse = gate.get("parse")
    if lang_check.build_drop(meta, target, parse):
        out.append(("unchecked_code", sorted(lang_check.unchecked_code(target, parse))))
    if meta["mode"] == "blender":
        code = task.piece_code(target)
        for reason, keys in (("ctx_channel", blender_gate.ctx_channel(code)),
                             ("dead_output_key", blender_gate.dead_output_key(code, meta["sid"], step))):
            if keys:
                out.append((reason, sorted(keys)))
    return out


def _allowed(cap, base):
    """How many capped examples base others allow: the most r with r <= cap * (base + r)."""
    return int(cap * base / (1 - cap) + 1e-9)


def _key(name, m):
    return stable_int(name, m["seed_id"], m["round"], m["sid"], m["variant"] or "", m["turn"])


def _cap_repairs(kept, dropped):
    """Drop repairs, the last in stable_int order first, until they are at most REPAIR_CAP of the Blender and code
    ones."""
    base = sum(1 for _, m in kept if m["mode"] in CODE_LIKE and not m["repaired"])
    reps = [k for k, (_, m) in enumerate(kept) if m["mode"] in CODE_LIKE and m["repaired"]]
    reps.sort(key=lambda k: _key("repair-cap", kept[k][1]))
    gone = set(reps[_allowed(REPAIR_CAP, base):])
    for k in sorted(gone):
        dropped.append(("repair_cap", kept[k][1]))
    return [e for k, e in enumerate(kept) if k not in gone]


def natural_failed_dep(m):
    """An example written with a dependency that failed in the run itself (not a failed_dep variant, which leaves one
    out on purpose)."""
    return bool(m.get("missing_deps")) and m.get("variant") != "failed_dep"


def _cap_failed_deps(kept, dropped):
    """Drop natural failed-dependency examples of each mode, the last in stable_int order (by seed and step) first,
    until they are at most FAILED_DEP_CAP of the mode's examples (failed_dep_share)."""
    gone = set()
    for mode in sorted({m["mode"] for _, m in kept}):
        idx = [k for k, (_, m) in enumerate(kept) if m["mode"] == mode]
        nat = sorted((k for k in idx if natural_failed_dep(kept[k][1])), key=lambda k: _key("failed-dep", kept[k][1]))
        gone.update(nat[_allowed(FAILED_DEP_CAP, len(idx) - len(nat)):])
    for k in sorted(gone):
        dropped.append(("failed_dep_share", kept[k][1]))
    return [e for k, e in enumerate(kept) if k not in gone]


def split_groups(groups, modes=None):
    """The valid groups: VALID_SHARE of them by stable_int("split", group), at least one once there are
    MIN_GROUPS_FOR_VALID; then, once any are, for every mode (modes: {group: its examples' modes}) with two groups or
    more and none in valid yet, the first of its groups in that order whose move leaves every mode a group in train."""
    order = sorted(set(groups), key=lambda g: (stable_int("split", g), g))
    n = round(VALID_SHARE * len(order))
    if len(order) >= MIN_GROUPS_FOR_VALID:
        n = max(1, n)
    valid = set(order[:n])
    if not valid or not modes:
        return valid
    by_mode = defaultdict(list)
    for g in order:
        for mode in modes.get(g) or ():
            by_mode[mode].append(g)

    def keeps_train(g):
        return all(set(gs) - valid - {g} for gs in by_mode.values() if set(gs) - valid)
    for mode in sorted(by_mode):
        gs = by_mode[mode]
        if len(gs) >= 2 and not valid.intersection(gs):
            pick = next((g for g in gs if keeps_train(g)), None)
            if pick is not None:
                valid.add(pick)
    return valid


def check_file(path):
    """(exit, output) of tools/check_overlap.py on a file, run as its own process."""
    p = subprocess.run([sys.executable, "-B", CHECK_OVERLAP, path], capture_output=True, text=True, timeout=1800,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    return p.returncode, (p.stdout + p.stderr).strip()


def build(data_dir, size=None, keep_plan_failed=False, *, index=None, check=True, keep_untested=False,
          fingerprint=None) -> dict:
    """Build the training files from tasks.jsonl. size: the size (only its name is recorded). index: an EvalIndex
    (tools/check_overlap.EvalIndex(8) when None). check: run tools/check_overlap.py on the files before publishing
    them (always, except in this module's own tests of the steps before it). keep_untested: keep code examples whose
    tests are "unconfirmed", "none:third_party" or "none:tests_refused". fingerprint: this start's request fingerprint
    (run.py's); examples of seeds made with another, or with none, are dropped as old_fingerprint, after those of
    another task.DATAGEN_FORMAT (old_format). Returns the stats (also STATS.md and sft/stats.json); raises
    OverlapFound when the last check flags anything."""
    if index is None:
        from tools.check_overlap import EvalIndex
        index = EvalIndex(8)
    examples, notes = collect(data_dir, keep_plan_failed)
    kept, dropped, seen, facts = [], [], set(), []
    for msgs, meta, item, step in examples:
        meta = dict(meta, tokens=msgs_tokens(msgs),
                    unverified=meta.get("tests") in UNVERIFIED or bool(meta.get("nothing_ran")))
        if meta["format"] != task.DATAGEN_FORMAT:
            dropped.append(("old_format", meta))
            continue
        if fingerprint is not None and meta.get("fingerprint") != fingerprint:
            dropped.append(("old_fingerprint", meta))
            continue
        if meta.get("no_example"):
            dropped.append(("no_example", meta))
            continue
        if meta["tokens"] > task.MAX_EXAMPLE_TOKENS:
            dropped.append(("too_long", meta))
            continue
        hits = index.check(_eval_text(msgs), EVAL_THRESHOLD)
        if hits:
            dropped.append(("eval_overlap", dict(meta, hits=[h[0] for h in hits][:5])))
            continue
        note = _teacher_note(msgs, meta["mode"])
        if note is not None:
            dropped.append(("teacher_note", dict(meta, note=note)))
            continue
        if meta.get("tests") in UNTESTED and not keep_untested:
            dropped.append((UNTESTED[meta["tests"]], meta))
            continue
        found = fact_drops(msgs, meta, item, step)
        if found:
            facts.append((found, meta))
            dropped.append((found[0][0], dict(meta, facts=found)))
            continue
        dup = json.dumps(msgs, ensure_ascii=False, sort_keys=True)
        if dup in seen:
            dropped.append(("duplicate", meta))
            continue
        seen.add(dup)
        kept.append((msgs, meta))
    kept = _cap_repairs(_cap_failed_deps(kept, dropped), dropped)
    modes = defaultdict(set)
    for _, m in kept:
        modes[m["group"]].add(m["mode"])
    valid_groups = split_groups(modes, modes)
    rows = {"train": [], "valid": []}
    for msgs, meta in kept:
        rows["valid" if meta["group"] in valid_groups else "train"].append((msgs, meta))

    sft = os.path.join(data_dir, SFT)
    staging = os.path.join(sft, "staging")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    for name in ("train", "valid"):
        write_jsonl(os.path.join(staging, name + ".jsonl"), [{"messages": m} for m, _ in rows[name]])
        write_jsonl(os.path.join(staging, name + ".meta.jsonl"), [_meta(m) for _, m in rows[name]])
    stats = _stats(size, examples, kept, dropped, rows, valid_groups, notes, keep_plan_failed, keep_untested,
                   fingerprint, facts)
    flagged = []
    if check:
        for name in ("train", "valid"):
            code, out = check_file(os.path.join(staging, name + ".jsonl"))
            stats["overlap_check"][name] = {"exit": code, "output": out[-4000:]}
            if code != 0:
                flagged.append(name)
    if flagged:
        bad = os.path.join(sft, "flagged")
        shutil.rmtree(bad, ignore_errors=True)
        os.replace(staging, bad)
        with open(os.path.join(bad, "OVERLAP.txt"), "w", encoding="utf-8") as f:
            for name in flagged:
                f.write(f"== {name}.jsonl\n{stats['overlap_check'][name]['output']}\n\n")
        for name in FILES:
            p = os.path.join(sft, name)
            if os.path.exists(p):
                os.remove(p)
        stats["published"], stats["checked"] = False, True
        _write_stats(data_dir, stats)
        raise OverlapFound(f"tools/check_overlap.py flagged {', '.join(f + '.jsonl' for f in flagged)}: nothing was "
                           f"published; see {os.path.join(bad, 'OVERLAP.txt')}")
    for name in FILES:
        os.replace(os.path.join(staging, name), os.path.join(sft, name))
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(os.path.join(sft, "flagged"), ignore_errors=True)
    stats["published"], stats["checked"] = True, check
    _write_stats(data_dir, stats)
    return stats


META_KEYS = ("group", "seed_id", "sid", "round", "kind", "mode", "variant", "model", "names", "repaired",
             "request_tokens", "target_tokens", "lone", "missing_deps", "source", "turn", "category", "seed_source",
             "tests", "unverified", "format")


def _meta(m):
    return {k: m.get(k) for k in META_KEYS}


def _detail(reason, detail):
    """What a facts filter found, as STATS.md counts it, once per example: dep_honesty's reason names (dep_claimed,
    dep_unlisted; dep_claimed once however many steps it was claimed from), a file's language, a validator code or a
    key."""
    if reason == "dep_claimed":
        return sorted({d.split(":")[0] for d in detail})
    if reason == "unchecked_code":
        return sorted({lang for _, lang in detail})
    return sorted(set(detail))


def _label(m):
    """An example's name in stats.json's facts_examples: seed, round, step, variant, repair turn."""
    return f"{m['seed_id']} r{m['round']} {m['sid']}" + (f" {m['variant']}" if m.get("variant") else "") + \
        (f" repair {m['turn']}" if m.get("repaired") else "")


def _failed_dep_share(kept):
    """{mode: {"natural", "variants", "of"}} for the modes with any example written with a dependency missing."""
    out = defaultdict(Counter)
    for _, m in kept:
        out[m["mode"]]["of"] += 1
        out[m["mode"]]["natural"] += natural_failed_dep(m)
        out[m["mode"]]["variants"] += m.get("variant") == "failed_dep"
    return {k: {"natural": c["natural"], "variants": c["variants"], "of": c["of"]} for k, c in sorted(out.items())
            if c["natural"] or c["variants"]}


def _stats(size, examples, kept, dropped, rows, valid_groups, notes, keep_plan_failed, keep_untested, fingerprint,
           facts=()):
    def count(items, key):
        return dict(sorted(Counter(key(m) for _, m in items).items(), key=lambda kv: (-kv[1], str(kv[0]))))
    groups = {m["group"] for _, m in kept}
    fired = {r: {"dropped": 0, "fired": 0, "found": Counter(), "by_mode": Counter(), "examples": []}
             for r in FACT_DROPS}
    for found, m in facts:
        for k, (reason, detail) in enumerate(found):
            f = fired[reason]
            f["fired"] += 1
            f["found"].update(_detail(reason, detail))
            f["examples"].append(_label(m) + ("" if k == 0 else " (dropped by %s)" % found[0][0]))
            if k == 0:
                f["dropped"] += 1
                f["by_mode"][m["mode"]] += 1
    soft = [m for r, m in dropped if r == "no_example"]
    return {"size": (size or {}).get("name"), "keep_plan_failed": keep_plan_failed, "keep_untested": keep_untested,
            "fingerprint": fingerprint,
            "examples": len(examples), "kept": len(kept), "train": len(rows["train"]), "valid": len(rows["valid"]),
            "groups": len(groups), "valid_groups": sorted(valid_groups),
            "dropped": dict(Counter(r for r, _ in dropped)),
            "seeds": {k.split(" ", 1)[1]: v for k, v in notes.items() if k.startswith("seeds ")},
            "left_out": {k: v for k, v in notes.items() if not k.startswith("seeds ")},
            "eval_hits": dict(Counter(h for r, m in dropped if r == "eval_overlap" for h in m.get("hits") or [])),
            "teacher_notes": dict(Counter(m["note"] for r, m in dropped if r == "teacher_note")),
            "by_kind": count(kept, lambda m: mix_kind(m["mode"], m["kind"])),
            "by_mode": count(kept, lambda m: m["mode"]),
            "by_variant": count(kept, lambda m: m["variant"] or ("lone" if m["lone"] else "build")),
            "by_model": count(kept, lambda m: m["model"]), "by_names": count(kept, lambda m: m["names"] or "none"),
            "by_source": count(kept, lambda m: m["source"]), "round2": sum(1 for _, m in kept if m["round"] > 1),
            "by_tests": count([e for e in kept if e[1]["mode"] in task.CODE_MODES],
                              lambda m: m.get("tests") or "none"),
            "valid_by_mode": count(rows["valid"], lambda m: m["mode"]),
            "unverified_by_mode": count([e for e in kept if e[1]["unverified"]], lambda m: m["mode"]),
            "unverified_by_why": count([e for e in kept if e[1]["unverified"]],
                                       lambda m: m["tests"] if m.get("tests") in UNVERIFIED else "nothing_ran"),
            "facts": {r: {"dropped": f["dropped"], "fired": f["fired"], "by_mode": dict(sorted(f["by_mode"].items())),
                          "found": dict(sorted(f["found"].items()))} for r, f in fired.items() if f["fired"]},
            # every example each fired on, so smoke3's ctx_channel and dead_output_key firings can be read one by one
            "facts_examples": {r: f["examples"] for r, f in fired.items() if f["fired"]},
            "no_example": dict(sorted(Counter(r.split(":")[0] for m in soft for r in m["no_example"]).items())),
            "no_example_by_mode": dict(sorted(Counter(m["mode"] for m in soft).items())),
            "failed_dep_natural": sum(1 for _, m in kept if natural_failed_dep(m)),
            "failed_dep_share": _failed_dep_share(kept),
            # the examples the cap dropped: report.projection counts back the share a night's build would keep
            "failed_dep_capped": [{"mode": m["mode"], "kind": m["kind"], "example": _label(m)}
                                  for r, m in dropped if r == "failed_dep_share"],
            "repairs": sum(1 for _, m in kept if m["repaired"]),
            "long_input": sum(1 for _, m in kept if m["request_tokens"] >= 5000),
            "tokens": _spread([m["tokens"] for _, m in kept]),
            "target_tokens": _spread([m["target_tokens"] for _, m in kept]),
            "overlap_check": {}}


def _spread(xs):
    xs = sorted(xs)
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "median": xs[len(xs) // 2], "p90": xs[min(len(xs) - 1, int(0.9 * len(xs)))], "max": xs[-1]}


def _table(rows):
    from runner.common import md_table
    return md_table(rows)


def _write_stats(data_dir, stats):
    sft = os.path.join(data_dir, SFT)
    os.makedirs(sft, exist_ok=True)
    write_json(os.path.join(sft, "stats.json"), stats)
    lines = [f"# Hydra Worker training data: {stats['size'] or ''}", ""]
    if not stats.get("published"):
        lines += ["**Not published:** tools/check_overlap.py flagged the files (sft/flagged/OVERLAP.txt).", ""]
    elif not stats.get("checked"):
        lines += ["**Not checked:** tools/check_overlap.py wasn't run on these files (a test build).", ""]
    seeds = ", ".join(f"{k} {v}" for k, v in sorted(stats["seeds"].items())) or "none"
    lines += [f"{stats['kept']} examples kept of {stats['examples']} ({stats['train']} train, {stats['valid']} valid, "
              f"{len(stats['valid_groups'])} of {stats['groups']} seed groups in valid), from the seeds in "
              f"tasks.jsonl: {seeds}.", ""]
    lines += ["Dropped: " + (", ".join(f"{k} {v}" for k, v in sorted(stats["dropped"].items())) or "none") + ".",
              "Left out before the filters: " + (", ".join(f"{k} {v}" for k, v in sorted(stats["left_out"].items()))
                                                 or "none") + ".", ""]
    have = stats["by_kind"]
    lines += ["## By kind, against the plan's mix", "",
              _table([["kind", "examples", "plan"]] + [[k, have.get(k, 0), PLAN_MIX.get(k, "")] for k in
                                                       sorted(set(PLAN_MIX) | set(have), key=str)]), ""]
    for title, key in (("mode", "by_mode"), ("variant", "by_variant"), ("model", "by_model"),
                       ("names sheet", "by_names"), ("source", "by_source"), ("code tests", "by_tests"),
                       ("mode, in valid", "valid_by_mode"),
                       ("mode, unverified (only compiled and parse-checked, or tests that couldn't reach the code)",
                        "unverified_by_mode"),
                       ("why unverified", "unverified_by_why")):
        if stats.get(key):
            lines += [f"## By {title}", "", _table([[title, "examples"]] + [[k, v] for k, v in stats[key].items()]),
                      ""]
    lines += ["## Spread", "",
              _table([["", "examples"], ["round 2", stats["round2"]], ["repairs", stats["repairs"]],
                      ["a dependency failed in the run itself", stats["failed_dep_natural"]],
                      ["long input (5K+ request tokens)", stats["long_input"]]]), "",
              f"Tokens per example: {stats['tokens']}; per target: {stats['target_tokens']}.", ""]
    share = stats.get("failed_dep_share") or {}
    if share:
        lines += ["Written with a dependency missing, by mode (the plan wants about 10%; natural ones are capped at "
                  f"{FAILED_DEP_CAP:.0%} after dep_claimed drops the dishonest): " +
                  "; ".join(f"{k} {v['natural']} natural and {v['variants']} failed_dep variants of {v['of']} "
                            f"({(v['natural'] + v['variants']) / v['of']:.0%})" for k, v in share.items()) + ".", ""]
    elif stats["kept"]:  # said, so a night under the plan's ~10% shows it
        lines += [f"Written with a dependency missing: none of the {stats['kept']} kept (the plan wants about 10%).",
                  ""]
    if stats.get("facts"):
        rows = [["filter", "dropped", "fired", "by mode (dropped)", "found"]]
        for reason in FACT_DROPS:
            f = stats["facts"].get(reason)
            if f:
                rows.append([reason, f["dropped"], f["fired"], ", ".join(f"{k} {v}" for k, v in f["by_mode"].items()
                                                                          if v) or "-",
                             ", ".join(f"{k} {v}" for k, v in f["found"].items())])
        lines += ["## The facts filters", "", "Facts about the example itself, read from the record (no model time, "
                  "no cascade). An example is dropped by the first that fires and counted under every one that "
                  "does.", "", _table(rows), ""]
    if stats.get("no_example"):
        lines += [f"{stats['dropped'].get('no_example', 0)} steps were kept only as a dependency (no_example: their "
                  "pieces fed the later steps and the join, but their best try failed on " +
                  ", ".join(f"{k} {v}" for k, v in stats["no_example"].items()) + "), by mode: " +
                  ", ".join(f"{k} {v}" for k, v in stats["no_example_by_mode"].items()) + ".", ""]
    if stats["eval_hits"]:
        lines += ["## Eval overlap drops", "", _table([["eval text", "examples"]] +
                                                      [[k, v] for k, v in sorted(stats["eval_hits"].items())]), ""]
    if stats["teacher_notes"]:
        lines += ["## Teacher-note drops", "", _table([["note", "examples"]] +
                                                      [[k, v] for k, v in sorted(stats["teacher_notes"].items())]), ""]
    if stats["dropped"].get("old_format"):
        lines += [f"{stats['dropped']['old_format']} examples were dropped as old_format: their seeds were made by "
                  f"another version of the data generator than this one (format {task.DATAGEN_FORMAT}), whose checks "
                  "and judges have changed since.", ""]
    if stats["dropped"].get("old_fingerprint"):
        lines += [f"{stats['dropped']['old_fingerprint']} examples were dropped as old_fingerprint: their seeds were "
                  f"made with other requests (another Chimera or names sheet) than this start's "
                  f"({stats['fingerprint']}).", ""]
    for name, rec in stats["overlap_check"].items():
        last = rec["output"].splitlines()[-1] if rec["output"] else ""
        lines += [f"Last check, {name}.jsonl: exit {rec['exit']}: {last}"]
    with open(os.path.join(sft, "STATS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")
