"""What a data-generation run did and what the rest would cost (DESIGN.md, "report.py"): REPORT.md and report.json.

    rep = report(data_dir)

From the data folder only: seeds_stats.json and seeds_dropped.jsonl (the seeds made, kept and dropped), tasks.jsonl
(plans by planner and how often they could be read; steps by mode, kept on the first round of samples, after more
samples, after repairs, from the second sampler, kept only as a dependency, or dropped and why; kept code steps by
their tests; what the changes after the first smoke run did (after_smoke), after the second's audit and after the
third smoke (after_audit: since format 4 also ctx_channel by whether a later step depends on the step, the soft
keeps by reason, the values-only steps and whether their pieces hand values on in ctx["values"], Chimera's
provides_missing warnings that are only a reader's own stand-ins, step 6's facts, the geometry readers' held-out
counts, and the passed repairs the code-line share admits or refuses against every line's); variants; plan checks;
round 2), the call cache (model time per model and purpose), gate.jsonl (model
switches, long waits, and models loaded in Ollama that the run never called), the run cache (Blender and Python
seconds), sft/stats.json (what the build kept and dropped) and RUN.json. Only finished seeds (done or no_plan) are
counted: an errored seed's partial steps would count as dropped and its time in the projection, though it gives no
examples until a later start finishes it, so errored seeds are a count of their own.

Model time counts only the calls the records use (used_calls: every task record, an errored one's too, since its
calls were made, and seed_calls.jsonl), each once, at the time it took when made, as the projection reads them. The
second smoke run's cache was seeded with the first run's 744 calls, and summing the whole cache put those in its
table; REPORT.md now says how many calls the records use that were made before the run's first start (an earlier
run's, answered from the cache) and how many cached calls no record uses (left out).

The projection is what the smoke run is for: the teacher's seconds per kept example of each kind (every model call a
step made, its judge and tests included, plus the seed's share of planning, reviewing and seed writing), and the
hours to reach the plan's 1,700 examples in its mix at one and at two parallel requests. Call times come from the
cache, so they are the times the calls took when they were made, also in a run that replayed them; a call a seed
makes twice (one judge prompt for two candidates that built the same scene, answered from the cache the second time)
counts once in that seed. A kind with no built examples is costed from its own tries: their model time each, over a
keep rate by Laplace's rule of succession, (kept + 1) / (tried + 2), since a few tries that kept nothing would
otherwise cost it nothing or everything (the smoke run's research kept 0 of 2), not at the other kinds' mean, which
priced research like Blender; a kind with no tries at all, at the plan-weighted mean of the measured kinds.
REPORT.md says which. Only one of the two parallel figures is measured (the one the run used); the other assumes
PARALLEL_SPEEDUP. Since the fourth smoke a measured kind also counts the share of the examples the failed-dependency
cap dropped that a night's build would keep (night_failed_deps: a smoke's 4 Blender examples allow none, a night's 640
about 71), and REPORT.md has a line per sampler (samplers: the teacher's first and told samples, the second sampler,
repairs, variants) with its gate passes and examples per 1,000 s of its own calls, and the second sampler's budget.

A model loaded in Ollama that this start hadn't called (gate.jsonl's "foreign") is told apart from what a restart
leaves: a model this run called itself (the call cache's, or a start's in RUN.json) that Ollama still holds within
keep_alive of that model's last call before this start. The smoke run's four "foreign" events were all that, not
Chimera lending.
"""
from __future__ import annotations

import ast
import bisect
import datetime
import os
import re
from collections import Counter, defaultdict

from contract import planinfo
from contract import validate as V
from datagen import blender_gate, geometry, hints, judges, stand_ins, task
from datagen.build import FAILED_DEP_CAP, PLAN_MIX, mix_kind, natural_failed_dep
from datagen.common import Cache, Store, read_json, read_jsonl, write_json
from runner.common import KEEP_ALIVE, md_table
from runner.score import lines_changed

REPORT_FILE = "REPORT.md"
JSON_FILE = "report.json"
PARALLEL_SPEEDUP = 1.3  # 2 parallel requests against 1: the plan's own estimate (52 h of calls in 35-45 h)
FINISHED = ("done", "no_plan")  # the statuses counted; run.py runs every other seed again
CODE_MODES = ("python-script", "files")  # the code modes whose steps have the teacher's tests (tests_status)
LEFT_SLACK_S = 60  # a model's expiry is keep_alive after its call ended, give or take Ollama's own bookkeeping


def _when(s):
    try:
        return datetime.datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _epoch(t):
    """A time as seconds since the epoch: gate.jsonl's float, or an ISO string (RUN.json, the call cache)."""
    if isinstance(t, (int, float)):
        return float(t)
    w = _when(t)
    return w.timestamp() if w else None


def _keep_alive_s(text=KEEP_ALIVE):
    """Ollama's keep_alive as seconds ("15m", "90s", "1h")."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([smh]?)", str(text).strip())
    if not m:
        return 900.0
    return float(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[m.group(2)]


def _steps(rec, variants=False):
    for rnd in rec.get("rounds") or []:
        for s in rnd.get("variants" if variants else "steps") or []:
            yield rnd, s


def _kept_how(step):
    k = step.get("kept")
    if not k:
        return "dropped"
    if step.get("no_example"):  # task.SOFT_REASONS: its piece fed the later steps, but gives no example
        return "dependency only"
    if k["from"] == "repair":
        return "repairs"
    if k["from"] == "second":
        return "second sampler"
    first = task.ROUNDS.get(step["mode"], (1, 1))[0]
    return "first samples" if k["index"] < first else "more samples"


def _step_seconds(step):
    s = step.get("seconds") or {}
    t = (s.get("teacher") or 0) + (s.get("judge") or 0) + (s.get("tests") or 0)
    if step.get("today"):
        t += step["today"].get("wall_s") or 0
    return t


def _calls_in(obj):
    """Every model call a step record holds, in order: a dict with the call's key and wall_s (a candidate, its judge
    and the judge's second opinion, the tests, a repair, the dependency today's prompt wrote)."""
    if isinstance(obj, dict):
        if "key" in obj and "wall_s" in obj:
            yield obj
        for v in obj.values():
            yield from _calls_in(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _calls_in(x)


def seed_steps(rec):
    """(round, step, model seconds) for every step and variant of a seed record, a call the seed already made
    counted once: its wall time is taken off the steps that use it again (the step's own seconds add every use,
    cached or not, as the call's wall_s is the time it took when made)."""
    seen = set()
    for rnd in rec.get("rounds") or []:
        for s in (rnd.get("steps") or []) + (rnd.get("variants") or []):
            again = 0.0
            for call in _calls_in(s):
                if call["key"] in seen:
                    again += call.get("wall_s") or 0.0
                seen.add(call["key"])
            yield rnd, s, max(0.0, _step_seconds(s) - again)


def _keys_in(obj):
    """Every string under a "key" field at any depth: the call keys a record holds (a candidate's, its judge's and
    second opinion's, the tests' and their rewrite's, a repair's, the planner's and its tries', the review's, today's
    dependency), with keys that aren't calls (the seed's id, a run's key) among them, for used_calls to sort out."""
    if isinstance(obj, dict):
        if isinstance(obj.get("key"), str):
            yield obj["key"]
        for v in obj.values():
            yield from _keys_in(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _keys_in(x)


def used_calls(data_dir, recs) -> set:
    """The call-cache keys the run's records use: every task record's (an errored seed's too: its calls were made,
    and the start that finishes it reuses them) and every seed-writing call of seed_calls.jsonl."""
    keys = set()
    for r in recs:
        keys.update(_keys_in(r.get("rounds")))
    keys.update(_keys_in(read_jsonl(os.path.join(data_dir, "seed_calls.jsonl"))))
    return keys


def model_time(calls, used, run) -> tuple:
    """({"<model> <purpose>": {"calls", "wall_s", "eval_tokens", "errors", "earlier", "earlier_s"}}, left_out): the
    calls the records use, each once, at the time it took when it was made ("earlier": made before this run's first
    start, by another run whose cache this one was seeded with; their time is in wall_s, as the projection counts it),
    and {"calls", "wall_s"} of the cached calls no record uses (another run's, or tries that no record keeps)."""
    starts = [t for t in (_epoch(s.get("started")) for s in (run.get("starts") or []) + [run]) if t is not None]
    first = min(starts) if starts else None
    out = defaultdict(lambda: {"calls": 0, "wall_s": 0.0, "eval_tokens": 0, "errors": 0, "earlier": 0,
                               "earlier_s": 0.0})
    left = {"calls": 0, "wall_s": 0.0}
    for key in calls.keys():
        v = calls.get(key) or {}
        wall = v.get("wall_s") or 0.0
        if key not in used:
            left["calls"] += 1
            left["wall_s"] = round(left["wall_s"] + wall, 1)
            continue
        m = out[f"{v.get('model')} {v.get('purpose')}"]
        m["calls"] += 1
        m["wall_s"] = round(m["wall_s"] + wall, 1)
        m["eval_tokens"] += (v.get("stats") or {}).get("eval_count") or 0
        m["errors"] += v.get("error") is not None
        t = _epoch(v.get("t"))
        if first is not None and t is not None and t < first:
            m["earlier"] += 1
            m["earlier_s"] = round(m["earlier_s"] + wall, 1)
    return dict(sorted(out.items())), left


def report(data_dir) -> dict:
    """Write REPORT.md and report.json for a data folder; returns what report.json holds."""
    every = Store(os.path.join(data_dir, "tasks.jsonl")).all()
    recs = [r for r in every if r.get("status") in FINISHED]
    run = read_json(os.path.join(data_dir, "RUN.json"), {}) or {}
    seeds = read_json(os.path.join(data_dir, "seeds_stats.json"), {}) or {}
    out = {"size": run.get("size"), "seeds": seeds, "status": dict(Counter(r.get("status") for r in every)),
           "errored": len(every) - len(recs)}

    # plans
    planners = Counter()
    read = Counter()
    for r in recs:
        for rnd in r.get("rounds") or []:
            p = rnd.get("planner") or {}
            label = f"round {rnd['round']}: " + ("reused gpt-oss plan" if p.get("reused") else (p.get("drew") or
                                                                                            p.get("model") or "?"))
            planners[label] += 1
            for t in p.get("tries") or []:
                read[(t["model"], bool(t.get("ok")))] += 1
            if p.get("fell_back"):
                planners[f"round {rnd['round']}: fell back to {task.TEACHER}"] += 1
            if p.get("reason") == "eval_plan":  # task.eval_plan: the plan repeated the eval, so the seed had none
                planners[f"round {rnd['round']}: repeated the eval (no plan)"] += 1
    out["plans"] = {"by_planner": dict(planners),
                    "read_rate": {m: {"asked": read[(m, True)] + read[(m, False)], "read": read[(m, True)]}
                                  for m in sorted({m for m, _ in read})}}

    # steps, variants
    steps = defaultdict(Counter)
    drops = defaultdict(Counter)
    tests = defaultdict(Counter)  # kept code steps by tests_status: valid, unconfirmed or none:<why>
    for r in recs:
        for _, s in _steps(r):
            steps[s["mode"]]["tried"] += 1
            how = _kept_how(s)
            steps[s["mode"]][how] += 1
            if how == "dropped":
                drops[s["mode"]][(s.get("drop") or ["?"])[0].split(":")[0]] += 1
            if s.get("plan_failed"):
                steps[s["mode"]]["plan_failed"] += 1
            if s.get("kept") and not s.get("no_example") and s["mode"] in CODE_MODES:
                tests[s["mode"]][s.get("tests_status") or "not recorded"] += 1
    variants = defaultdict(Counter)
    for r in recs:
        for _, v in _steps(r, variants=True):
            key = (v["variant"], v.get("mode") or "?")
            variants[key]["tried"] += 1
            variants[key]["kept" if v.get("kept") else ("skipped" if v.get("skipped") else "dropped")] += 1
    out["steps"] = {m: dict(c) for m, c in steps.items()}
    out["after_smoke"] = after_smoke(recs)
    out["after_audit"] = after_audit(recs)
    out["drops"] = {m: dict(c) for m, c in drops.items()}
    out["tests"] = {m: dict(c) for m, c in tests.items()}
    out["variants"] = {f"{k[0]} {k[1]}": dict(c) for k, c in variants.items()}

    # plan checks, round 2
    checks = Counter()
    for r in recs:
        for rnd in r.get("rounds") or []:
            for kind, pc in (rnd.get("plan_check") or {}).items():
                checks[(kind, "ok" if pc["ok"] and not pc.get("swapped") else "ok after an alternate"
                        if pc["ok"] else "failed: " + ",".join(pc["result"].get("reasons") or []))] += 1
    out["plan_checks"] = {f"{k} {v}": n for (k, v), n in checks.items()}
    out["round2"] = dict(Counter(r.get("round2") or "none" for r in recs if r.get("status") == "done"))

    # model time, gate, runs
    calls = Cache(os.path.join(data_dir, "cache", "calls.jsonl"))
    out["model_time"], out["calls_left_out"] = model_time(calls, used_calls(data_dir, every), run)
    gate = read_jsonl(os.path.join(data_dir, "gate.jsonl"))
    foreign = [g for g in gate if g.get("event") == "foreign"]
    left, other = left_loaded(foreign, calls, run)
    out["gate"] = {"switches": sum(1 for g in gate if g.get("event") == "switch"),
                   "by_why": dict(Counter(g.get("why") for g in gate if g.get("event") == "switch")),
                   "waits_over_60s": sum(1 for g in gate if g.get("event") == "wait"),
                   "drain_s": round(sum(g.get("drain_s") or 0 for g in gate), 1),
                   "foreign": len(foreign),
                   "foreign_models": sorted({m for g in foreign for m in g.get("models") or []}),
                   "left_loaded": len(left), "left_loaded_models": sorted({m for g in left for m in g["models"]}),
                   "other": len(other), "other_models": sorted({m for g in other for m in g["models"]}),
                   "keep_alive": KEEP_ALIVE}
    runs = Cache(os.path.join(data_dir, "cache", "runs.jsonl"))
    secs = Counter()
    for key in runs.keys():
        v = runs.get(key) or {}
        kind = v.get("kind") or ("python" if "exit" in v and "output" in v else "check")
        secs[kind] += v.get("seconds") or 0.0
        secs[kind + "_runs"] += 1
    out["runs"] = {k: round(v, 1) for k, v in secs.items()}

    # wall time
    starts = [_when(s.get("started")) for s in (run.get("starts") or [])] + [_when(run.get("started"))]
    starts = [s for s in starts if s]
    ends = [w for w in (_when(r.get("finished")) for r in recs) if w]
    out["wall"] = {"seed_seconds": round(sum(r.get("seconds") or 0 for r in recs), 1),
                   "first_start": min(starts).isoformat() if starts else None,
                   "last_finished": max(ends).isoformat() if ends else None,
                   "elapsed_h": round((max(ends) - min(starts)).total_seconds() / 3600, 2) if starts and ends else None}

    out["projection"] = projection(data_dir, recs, run, seeds)
    out["samplers"] = samplers(recs, calls, read_jsonl(os.path.join(data_dir, "sft", "train.meta.jsonl")) +
                               read_jsonl(os.path.join(data_dir, "sft", "valid.meta.jsonl")))
    out["build"] = build_stats(data_dir)
    write_json(os.path.join(data_dir, JSON_FILE), out)
    with open(os.path.join(data_dir, REPORT_FILE), "w", encoding="utf-8") as f:
        f.write(markdown(out))
    return out


def after_smoke(recs) -> dict:
    """What the changes made after the first smoke run (DESIGN.md, "After the smoke") did, counted over the steps
    and variants of finished seeds: candidates and repairs whose decorated form was made plain, by mode (normalised:
    "file_lines", "marker_dashes"); candidates dropped for naming a Blender version only the notes name
    (version_leak) or for the notes' words for the Blenders and the sandbox (notes_leak), by mode; tests replies
    refused and asked again (tests_refused: by why, only the whys task.REFUSED refuses, so a retry that gave no tests
    isn't a refusal), what those retries gave (tests_retries: gave tests, refused again, empty tests on a step that
    names nothing to call or on one that does, no tests otherwise, a runaway), tests rewrites (asked, counted, skipped
    for third_party); and sections judged by the missing-dependency rule (kept or not). Then, over kept code steps (not
    variants, nor steps kept only as a dependency, which give no example), by mode: those whose tests stayed refused
    (refused_untested, "none:tests_refused": the build drops them), those whose import run missed a package outside
    the standard library with no tests run (third_party_import, task.settle_tests), those the tests writer gave no
    tests although their words name a callable (no_tests_callable: task.names_callable, "none:no_tests" is kept), the
    share with no Python to test (no_python: {"steps", "of"} the kept code steps, "none:no_python": the build keeps
    them, marked unverified) and those on which nothing ran at all (nothing_ran: no tests and no import run,
    task.ran_nothing; the build marks them unverified too, none:no_python's among them)."""
    out = {"normalised": defaultdict(Counter), "version_leak": Counter(), "notes_leak": Counter(),
           "tests_refused": Counter(), "tests_retries": Counter(), "tests_rewrites": Counter(),
           "missing_dep_judged": Counter(), "refused_untested": Counter(), "third_party_import": Counter(),
           "no_tests_callable": Counter(), "no_python": defaultdict(Counter), "nothing_ran": Counter()}
    for r in recs:
        for rnd, s in list(_steps(r)) + list(_steps(r, variants=True)):
            for c in (s.get("candidates") or []) + (s.get("repairs") or []):
                for k, n in (c.get("normalised") or {}).items():
                    if n:
                        out["normalised"][s["mode"]][k] += 1
                if c.get("echoed") in ("version_leak", "notes_leak"):
                    out[c["echoed"]][s["mode"]] += 1
                j = c.get("judge") or {}
                if j.get("rule") == "missing_dep":
                    out["missing_dep_judged"]["kept" if j.get("ok") else "turned down"] += 1
            t = s.get("tests") or {}
            for x in t.get("refused") or []:
                if x.get("why") in task.REFUSED:  # older records kept a retry that gave none here too
                    out["tests_refused"][x["why"]] += 1
            retry = t.get("retry") or {}
            if retry.get("gave"):
                out["tests_retries"][_RETRY_GAVE.get(retry["gave"], retry["gave"]) +
                                     (_CALLABLE_SAID[bool(retry.get("callable"))] if retry["gave"] == "empty"
                                      else "")] += 1
            rw = t.get("rewrite")
            if rw:
                out["tests_rewrites"]["skipped: " + rw["skipped"] if rw.get("skipped") else
                                      "counted" if rw.get("valid") else "didn't count"] += 1
            if s.get("variant") or not s.get("kept") or s.get("no_example") or s.get("mode") not in CODE_MODES:
                continue
            status, mode = s.get("tests_status"), s["mode"]
            out["no_python"][mode]["of"] += 1
            if status == "none:no_python":
                out["no_python"][mode]["steps"] += 1
            elif status == "none:tests_refused":
                out["refused_untested"][mode] += 1
            elif status == "none:no_tests" and task.names_callable(_words(rnd, s)):
                out["no_tests_callable"][mode] += 1
            if s.get("import_fault") == "third_party":
                out["third_party_import"][mode] += 1
            if s.get("nothing_ran"):
                out["nothing_ran"][mode] += 1
    out["no_python"] = {m: {"steps": c["steps"], "of": c["of"]} for m, c in out["no_python"].items() if c["steps"]}
    return {k: ({m: dict(c) for m, c in v.items()} if k == "normalised" else dict(v)) for k, v in out.items()}


# The gates' reason names after_audit counts: the second smoke's audit's, then the third smoke's (format 4):
# ctx_channel (blender_gate's, a gate since then), step 6a's hidden errors and step 6b's geometry (nested only while
# geometry.GATED has it, so its count stays 0 this round), then the fourth smoke's: attr_miss (silent.missed_keys),
# doubled_depth (geometry's) and blender_gate.build_facts' reasons (FACT_REASONS: what the build drops, told at the
# gate, and the stand-in marker's faults)
NEW_GATES = ("dep_claimed", "dep_unlisted", "output_missing", "camera_not_active", "layout_import", "ctx_channel",
             "swallowed", "skipped_input", "place_mismatch", "flat_extrusion", "nested", "attr_miss", "doubled_depth"
             ) + blender_gate.FACT_REASONS + ("global_ctx", "code_syntax")  # the last two since the fifth smoke
BUILD_FACTS = ("dep_claimed", "validator_warning", "unchecked_code", "ctx_channel", "dead_output_key", "no_example")
ERROR_CHARS = 160  # of each rewrite error REPORT.md shows
_PROVIDES_MISSING = re.compile(r'^registers ctx\["(\w+)"\] key\(s\) (.+) that provides doesn\'t list$')
_WARNED_CHANNEL = re.compile(r'^registers ctx\["(\w+)"\]')
_GEOMETRY = (("places", "place_mismatch"), ("joined_places", "place_mismatch"), ("depths", "flat_extrusion"),
             ("relations", "nested"), ("doubled", "doubled_depth"))  # details' rows


def _outcome(step):
    """What became of a step: "kept" (an example), "dependency only" (no_example), "dropped"."""
    if not step.get("kept"):
        return "dropped"
    return "dependency only" if step.get("no_example") else "kept"


def _errors(x):
    """The error lines a tests record's rewrite_errors holds (task's rewrite_tests: [{"from", "index", "error"}], the
    candidates the new tests failed), each led by its candidate ("cand 0: ..."); strings, or {candidate: error}, as
    they are."""
    if isinstance(x, dict):
        x = [{"from": k, "error": v} for k, v in x.items()]
    out = []
    for e in x or []:
        if isinstance(e, dict):
            who = " ".join(str(e[k]) for k in ("from", "index") if e.get(k) is not None)
            e = e.get("error") and (who + ": " if who else "") + str(e["error"])
        if e:
            out.append(" ".join(str(e).split()))
    return out


def _users(plan, k):
    """The steps of a round's plan that use step k's piece (contract.planinfo.user_names), [] for a plan that isn't a
    cleaned one (no step ids: a hand-made record) or no step k."""
    try:
        return planinfo.user_names(plan, k) if isinstance(k, int) and 0 <= k < len(plan.get("steps") or []) else []
    except (KeyError, TypeError, AttributeError):
        return []


def _deps(plan, k):
    """The steps step k of a round's plan depends on (blender_gate.dep_indexes), [] for a plan that isn't a cleaned
    one (no step ids: a hand-made record), as _users."""
    try:
        return blender_gate.dep_indexes(plan, k)
    except (KeyError, TypeError, AttributeError, IndexError):
        return []


def _used(plan, step):
    """Whether some later step of the round's plan depends on a step record's (task.Round.used: never a variant's,
    which feeds no step), so ctx_channel is soft on its tries (task.SOFT_IF_USED)."""
    return not step.get("variant") and bool(_users(plan or {}, step.get("index")))


def _kept_item(step):
    """The candidate or repair a step kept (task.kept_target's), or None."""
    k = step.get("kept")
    items = (step.get("repairs") if k and k.get("from") == "repair" else step.get("candidates")) or []
    return items[k["index"]] if k and isinstance(k.get("index"), int) and k["index"] < len(items) else None


def _parse(code):
    try:
        return ast.parse(code or "")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


def writes_values(code) -> bool:
    """Whether a Blender piece's code hands a value on in ctx["values"] as the contract has it since Nov 4: a store
    under it (ctx["values"][k] = ..., any key), or setdefault or update on it, ctx by any name its build_sN gives it
    (blender_gate._ctx_names). Read, never run: a write through a name bound to ctx["values"] isn't seen (33 of the 72
    stored pieces with an improvised channel went through one), which hands_on, the alone run's own listing of
    ctx["values"], sees."""
    tree = _parse(code)
    if tree is None:
        return False
    names = blender_gate._ctx_names(tree)

    def values(n):
        return isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id in names and \
            isinstance(n.slice, ast.Constant) and n.slice.value == "values"
    for n in ast.walk(tree):
        if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store) and values(n.value):
            return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("setdefault", "update") \
                and values(n.func.value):
            return True
    return False


def values_in_objects(code) -> list:
    """The keys under which a Blender piece's code registers a plain value in ctx["objects"], the channel for objects:
    a constant, a tuple or list of them, or a value read from a SETTINGS dict (SETTINGS_sN[k], .get, a name bound to
    it), and "<loop over SETTINGS>" for a loop over a SETTINGS dict's items that stores into ctx["objects"]. Counted,
    never gated (the round's cut: too few cases, 9 distinct stored tries, 4 of them mechanical passes); since Nov 4
    such values belong in ctx["values"]. [] when the code doesn't parse."""
    tree = _parse(code)
    if tree is None:
        return []
    names = blender_gate._ctx_names(tree)
    settings = {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Name)
                and n.value.id.startswith("SETTINGS_") for t in n.targets if isinstance(t, ast.Name)}

    def is_settings(n):
        return isinstance(n, ast.Name) and (n.id.startswith("SETTINGS_") or n.id in settings)

    def plain(v):
        if isinstance(v, ast.Constant):
            return True
        if isinstance(v, (ast.Tuple, ast.List)):
            return all(plain(e) for e in v.elts)
        if isinstance(v, ast.UnaryOp):
            return plain(v.operand)
        if isinstance(v, ast.Subscript):
            return is_settings(v.value)
        return isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr == "get" and \
            is_settings(v.func.value)

    def objects_slot(t):
        return isinstance(t, ast.Subscript) and isinstance(t.value, ast.Subscript) and \
            isinstance(t.value.value, ast.Name) and t.value.value.id in names and \
            isinstance(t.value.slice, ast.Constant) and t.value.slice.value == "objects"
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and plain(n.value):
            out += [t.slice.value if isinstance(t.slice, ast.Constant) else "<expr>" for t in n.targets
                    if objects_slot(t)]
        if isinstance(n, ast.For) and isinstance(n.iter, ast.Call) and isinstance(n.iter.func, ast.Attribute) and \
                n.iter.func.attr == "items" and is_settings(n.iter.func.value) and \
                any(isinstance(m, ast.Assign) and any(objects_slot(t) for t in m.targets) for m in ast.walk(n)):
            out.append("<loop over SETTINGS>")
    return out


def _tested(tree, channel):
    """The literal keys a piece tests with in or not in against ctx[channel] (or its keys()): "floor" not in
    ctx["objects"], the reader's guard before it registers a stand-in."""
    def channel_sub(n):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "keys" and not n.args:
            n = n.func.value
        return isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == "ctx" and \
            isinstance(n.slice, ast.Constant) and n.slice.value == channel
    return {n.left.value for n in ast.walk(tree) if isinstance(n, ast.Compare) and isinstance(n.left, ast.Constant)
            and isinstance(n.left.value, str) and any(isinstance(op, (ast.In, ast.NotIn)) and channel_sub(x)
                                                      for op, x in zip(n.ops, n.comparators))}


def stand_in_warnings(c) -> list:
    """[(channel, keys, own)] for each provides_missing warning on a try's stored verdict (Chimera's validator: a
    ctx["objects"] or ctx["values"] key the code registers that provides doesn't list, one warning per channel): its
    channel, its keys (from the message, or from the code against the stored provides when the record cut the
    message at 200 characters), and own: whether every one is a key the piece also reads or tests (contract.validate
    .ctx_keys' reads, or "k" in / not in ctx[channel]), i.e. its own stand-in for a dependency's key, registered where
    it found none. Such a warning drops the example (build.py's validator_warning) though the piece is right: the
    contract mapper's count was 34 of the 54 stored pieces that warn (on ctx["objects"]), and a reader of
    ctx["values"] that writes its stand-in there warns the same way."""
    out, tree = [], None
    for x in (c.get("verdict") or {}).get("issues") or []:
        if x.get("code") != "provides_missing":
            continue
        msg = x.get("message") or ""
        m, ch = _PROVIDES_MISSING.match(msg), _WARNED_CHANNEL.match(msg)
        if ch is None:
            continue
        channel = ch.group(1)
        if tree is None:
            tree = _parse(task.piece_code(c.get("content"))) or ast.Module(body=[], type_ignores=[])
        written, read, _ = V.ctx_keys(tree, channel)
        if m:
            keys = m.group(2).split(", ")
        else:  # cut: worked out again as the validator does (a substring test on provides)
            provides = ((c.get("verdict") or {}).get("handoff") or {}).get("provides") or ""
            keys = [k for k in written if k not in provides]
        seen = set(read) | _tested(tree, channel)
        out.append((channel, keys, bool(keys) and all(k in seen for k in keys)))
    return out


def _every_line_share(before, after):
    """A repair's share as format 3 counted it, on every line of piece_code's (blank lines, comments and docstrings
    too), or None for no base: the share code_lines replaced."""
    n = len(before.split("\n")) if before else 0
    return round(lines_changed(before, after) / n, 3) if n else None


def _code_line_share(before, after):
    """A repair's share as task.Round.repair counts it since format 4 (task.repair_lines: code lines, read the same
    way on both sides), worked out from the record's own texts, so a record of any format reads alike; None when the
    base has no code lines."""
    b, a = task.repair_lines(before, after)
    return round(lines_changed("\n".join(b), "\n".join(a)) / len(b), 3) if b else None


def _reading(xs):
    """One recorded geometry reading (a row's "floor" or "holds", one per version): yes when every version says so,
    no when every one says not, else unread."""
    xs = list(xs or [])
    return "yes" if xs and all(x is True for x in xs) else "no" if xs and all(x is False for x in xs) else "unread"


def after_audit(recs) -> dict:
    """What the changes after the second smoke run's audit (DATAGEN-SMOKE.md, "Second smoke run") did, over the
    steps and variants of finished seeds: the new gates' firings (gates: NEW_GATES' reason names, dep_claimed:<sid>
    counted as dep_claimed, by mode over every candidate and repair whose reasons have one; their steps by what
    became of them: kept, dependency only, dropped), the steps kept only as a dependency (no_example: by mode and by
    the reasons that kept them out, task.SOFT_REASONS and SOFT_IF_USED, each reason by itself, ctx_channel among
    them), the kept code steps whose tests couldn't reach their code (tests_unreachable: kept, the build marks them
    unverified) and what each tests rewrite said of the candidates it failed (rewrite_errors: one row a step; task's
    rewrite_tests keeps them in the tests record, since tests_fault reads only the old tests, and D17's rewrite
    reached the code and failed it, which would otherwise be lost).

    After the third smoke (format 4), so the fourth shows whether each change works:
    - ctx_channel: {"used", "unused"}, each {"tries", "kept", "dependency only", "dropped"}: its tries, and their steps
      by what became of them, by whether a later step depends on the step (Round.used; a variant is unused, as it
      feeds no step). It is soft only on a used one, so "unused" should hold no "dependency only";
    - build_tells (after the fourth smoke): the same for each of blender_gate.FACT_REASONS (validator_warning,
      dead_output_key, marker_misused, silent_default), {reason: {"used", "unused"}}, soft the same way;
    - handoff_exempt: {"tries", "steps", "kept"}: Blender tries with Chimera's handoff_long on a values-only step's
      provides line, in any form (blender_gate.warning_faults' "exempt", worked out from the stored verdict, so older
      records count too; a plain list of names only until the decision of Nov 6), their steps, and the kept pieces
      among them that give an example: the user's open contract question, no reason and no tell, so the build still
      drops them (validator_warning);
    - keyless_markers: {"tries", "steps", "kept"}: Blender tries on a step with a dependency whose piece prints a
      stand-in marker with no key (stand_ins.keyless), their steps, and the kept pieces among them that give an
      example: such a marker is judged only on a step with no dependency (the second checks' decision, Nov 6);
    - soft_keeps: {reason: {"used", "unused"}}, the steps kept only as a dependency by each reason and that split;
    - values_steps: the Blender steps hints.values_step finds in each round's plan (their notes carry VALUES_NOTE):
      {"steps", "kept", "dependency only", "dropped", "writes_values", "hands_on"}, the last two of the kept pieces
      (an example or a dependency): those whose code writes ctx["values"] (writes_values), and those whose kept try's
      alone run listed ctx["values"] keys (hands_on: the names line's, the gate's scene "ctx_values");
    - provides_stand_in: {channel: {"fired", "own", "kept", "kept_own"}}: the tries with Chimera's provides_missing
      warning on that channel, those whose every key is the piece's own stand-in (stand_in_warnings), and of each, the
      kept pieces that give an example (the build drops them as validator_warning);
    - values_in_objects: {"tries", "kept"}: Blender tries that register a plain value in ctx["objects"]
      (values_in_objects), and the kept pieces among them that give an example: counted, never gated;
    - step6: facts of step 6 that are never reasons: the hidden errors excused, by why (silent.WHY), tries whose
      hasattr or getattr found no such attribute (attr_miss; since Nov 6 not those whose miss is the attr_miss reason,
      measured.silent.missed) and whose joined run found a hidden error at the piece's
      lines (joined_silent: recorded only), the "on the floor" and above/below readings (floor, holds: yes, no or
      unread across the versions), the would-be firings of the geometry readers not in geometry.GATED (off:
      {reason: rows with a fault}) and the place faults left unjudged because the alone run printed a stand-in
      (stood_in: {reason: rows with a stand_in_fault}; piece_check judges those places on the joined run);
    - readers: geometry.HELD_OUT's held-out counts, each with whether its reason is gated;
    - repair_share: {"repairs", "passed", "examples", "crossed_in", "crossed_out"}: the repairs with a share on code
      lines (task.code_lines, since format 4), those that passed, those that are examples, and the passed ones whose
      share on every line (format 3's) is on the other side of task.REPAIR_SHARE (crossed_in: over it on every line,
      under on code lines; crossed_out: the reverse), by name, to grade blind (the code-line count admits 3 of the
      stored passed repairs, two of them doubtful), and the passed ones that leave out more than task.REPAIR_SHRINK
      of their code lines net (shrunk: no example, whatever their share; one stored repair, the compositor block
      deleted), by name.

    After the fourth smoke:
    - scene_overruled: {"verdicts", "kept", kind: n}: the scene judge's rejections overruled because they rest only
      on a size, a position or an output form the step names (judges.overruled; the judge record's rule
      "overruled"), those on the try the step kept, and each kind (judges.OVERRULED)."""
    gates = {g: Counter() for g in NEW_GATES}
    outcomes = {g: Counter() for g in NEW_GATES}
    soft, soft_why, unreachable, rewrites = Counter(), Counter(), Counter(), []
    ctx = {"used": Counter(), "unused": Counter()}
    told = {g: {"used": Counter(), "unused": Counter()} for g in blender_gate.FACT_REASONS}
    exempt, keyless = Counter(), Counter()
    soft_by, values, stand, in_objects = defaultdict(Counter), Counter(), defaultdict(Counter), Counter()
    step6 = {"excused": Counter(), "attr_miss": 0, "joined_silent": 0, "floor": Counter(), "holds": Counter(),
             "off": Counter(), "stood_in": Counter()}
    shares = {"repairs": 0, "passed": 0, "examples": 0, "crossed_in": [], "crossed_out": [], "shrunk": []}
    overruled = Counter()
    for r in recs:
        for rnd, s in list(_steps(r)) + list(_steps(r, variants=True)):
            hit = set()
            tries = (s.get("candidates") or []) + (s.get("repairs") or [])
            for c in tries:
                names = {x.split(":")[0] for x in c.get("reasons") or []} & set(NEW_GATES)
                for g in names:
                    gates[g][s["mode"]] += 1
                hit |= names
            for g in hit:
                outcomes[g][_outcome(s)] += 1
            plan = rnd.get("plan") or {}
            used = "used" if _used(plan, s) else "unused"
            if "ctx_channel" in hit:
                ctx[used]["tries"] += sum(1 for c in tries if any(x.split(":")[0] == "ctx_channel"
                                                                  for x in c.get("reasons") or []))
                ctx[used][_outcome(s)] += 1
            for g in blender_gate.FACT_REASONS:
                if g in hit:
                    told[g][used]["tries"] += sum(1 for c in tries if any(x.split(":")[0] == g
                                                                          for x in c.get("reasons") or []))
                    told[g][used][_outcome(s)] += 1
            if s.get("no_example"):
                soft[s["mode"]] += 1
                soft_why.update(x.split(":")[0] for x in s["no_example"])
                for why in sorted({x.split(":")[0] for x in s["no_example"]}):
                    soft_by[why][used] += 1
            if s.get("kept") and not s.get("no_example") and s.get("tests_status") == "none:tests_unreachable":
                unreachable[s["mode"]] += 1
            errs = _errors((s.get("tests") or {}).get("rewrite_errors"))
            if errs:
                rewrites.append({"seed": r.get("key"), "round": rnd.get("round"), "sid": s.get("sid"),
                                 "mode": s.get("mode"), "tests": s.get("tests_status"), "errors": errs})
            kept = _kept_item(s)
            if s.get("mode") == "blender" and not s.get("variant") and _users(plan, s.get("index")) and \
                    hints.values_step(plan, s["index"]):
                values["steps"] += 1
                values[_outcome(s)] += 1
                if kept is not None:
                    values["writes_values"] += writes_values(task.piece_code(kept.get("content")))
                    values["hands_on"] += bool(((kept.get("gate") or {}).get("scene") or {}).get("ctx_values"))
            if s.get("mode") == "blender" and isinstance(s.get("index"), int) and \
                    0 <= s["index"] < len(plan.get("steps") or []):
                waived = [c for c in tries if any(w["exempt"] for w in blender_gate.warning_faults(
                    c.get("verdict"), plan, s["index"], task.piece_code(c.get("content"))))]
                exempt["tries"] += len(waived)
                exempt["steps"] += bool(waived)
                exempt["kept"] += any(c is kept for c in waived) and not s.get("no_example")
                bare = [c for c in tries if stand_ins.keyless(task.piece_code(c.get("content")))] \
                    if _deps(plan, s["index"]) else []
                if bare:
                    keyless["tries"] += len(bare)
                    keyless["steps"] += 1
                    keyless["kept"] += any(c is kept for c in bare) and not s.get("no_example")
            for c in tries:
                j = c.get("judge") or {}
                if j.get("rule") == "overruled":
                    overruled["verdicts"] += 1
                    overruled["kept"] += c is kept
                    overruled.update(j.get("overruled") or [])
                if s.get("mode") == "blender" and values_in_objects(task.piece_code(c.get("content"))):
                    in_objects["tries"] += 1
                    in_objects["kept"] += c is kept and not s.get("no_example")
                for channel, _, own in stand_in_warnings(c):
                    example = c is kept and not s.get("no_example")
                    stand[channel]["fired"] += 1
                    stand[channel]["own"] += own
                    stand[channel]["kept"] += example
                    stand[channel]["kept_own"] += example and own
                m = (c.get("gate") or {}).get("measured") or {}
                quiet = m.get("silent") or {}
                step6["excused"].update(x.get("why") or "?" for x in quiet.get("excused") or [])
                # a miss that became the attr_miss reason (measured.silent.missed) is a reason, not a fact only
                step6["attr_miss"] += bool(quiet.get("attr_miss")) and not quiet.get("missed") and \
                    "attr_miss" not in (c.get("reasons") or [])
                loud = m.get("joined_silent") or {}
                step6["joined_silent"] += bool(loud.get("swallowed") or loud.get("skipped"))
                for name, reason in _GEOMETRY:
                    for row in m.get(name) or []:
                        if "floor" in row:
                            step6["floor"][_reading(row["floor"])] += 1
                        if "holds" in row:
                            step6["holds"][_reading(row["holds"])] += 1
                        if row.get("fault") and reason not in geometry.GATED:
                            step6["off"][reason] += 1
                        if row.get("stand_in_fault"):
                            step6["stood_in"][reason] += 1
            for rp in s.get("repairs") or []:
                before = task.piece_code((rp.get("inputs") or {}).get("piece"))
                after = task.piece_code(rp.get("content"))
                share = _code_line_share(before, after)
                if share is None:
                    continue
                shares["repairs"] += 1
                if not rp.get("passed"):
                    continue
                shares["passed"] += 1
                shares["examples"] += bool(rp.get("example"))
                every = _every_line_share(before, after)
                label = f"{r.get('key')} r{rnd.get('round')} {s.get('sid')}" + \
                    (f" {s['variant']}" if s.get("variant") else "") + f" repair {rp.get('turn')}"
                if every is not None and every > task.REPAIR_SHARE >= share:
                    shares["crossed_in"].append(f"{label} ({every} -> {share})")
                elif every is not None and every <= task.REPAIR_SHARE < share:
                    shares["crossed_out"].append(f"{label} ({every} -> {share})")
                shrink = task.repair_measures(before, after)[2]
                if shrink > task.REPAIR_SHRINK:
                    shares["shrunk"].append(f"{label} ({shrink:.0%} of its code lines left out)")
    return {"gates": {g: dict(c) for g, c in gates.items() if c},
            "gate_steps": {g: dict(c) for g, c in outcomes.items() if c},
            "no_example": dict(soft), "no_example_why": dict(soft_why), "tests_unreachable": dict(unreachable),
            "rewrite_errors": rewrites,
            "ctx_channel": {k: dict(c) for k, c in ctx.items() if c},
            "build_tells": {g: {k: dict(c) for k, c in v.items() if c} for g, v in told.items()
                            if any(v.values())},
            "handoff_exempt": dict(exempt), "keyless_markers": dict(keyless),
            "soft_keeps": {k: dict(c) for k, c in sorted(soft_by.items())},
            "values_steps": dict(values),
            "provides_stand_in": {k: dict(c) for k, c in sorted(stand.items())},
            "values_in_objects": dict(in_objects),
            "step6": {k: dict(sorted(v.items())) if isinstance(v, Counter) else v for k, v in step6.items()},
            "readers": {k: dict(v, gated=k in geometry.GATED) for k, v in geometry.HELD_OUT.items()},
            "repair_share": shares, "scene_overruled": dict(overruled)}


def build_stats(data_dir):
    """What the build kept and dropped (sft/stats.json), the facts filters and no_example apart, or None before a
    build."""
    st = read_json(os.path.join(data_dir, "sft", "stats.json"), None)
    if not st:
        return None
    dropped = st.get("dropped") or {}
    return {"kept": st.get("kept"), "examples": st.get("examples"), "published": st.get("published"),
            "dropped": dropped, "new": {k: dropped[k] for k in BUILD_FACTS if dropped.get(k)},
            "facts": st.get("facts") or {}, "unverified_by_why": st.get("unverified_by_why") or {},
            "failed_dep_share": st.get("failed_dep_share") or {}}


_RETRY_GAVE = {"tests": "gave tests", "refused": "refused again", "empty": "empty tests", "none": "no tests",
               "runaway": "a runaway"}  # task._retry_gave
_CALLABLE_SAID = {False: " on a step with nothing to call (no refusal)",
                  True: " on a step that names a callable (still refused)"}


def _words(rnd, step):
    """A step's title and instructions, from its round's plan (task.step_words), "" when the plan isn't there."""
    plan = rnd.get("plan") or {}
    if not isinstance(step.get("index"), int) or step["index"] >= len(plan.get("steps") or []):
        return step.get("title") or ""
    return task.step_words(plan, step["index"])


def left_loaded(foreign, calls, run):
    """(left, other): the gate's foreign events split by what a restart explains, each as {"t", "models"} (an event
    whose models are some of each goes to both, with those models). A model is left loaded when this run called it
    itself (a call in the call cache, or a start's model in RUN.json) and the event comes within keep_alive
    of that model's last call made before the start the event falls in (the cache's "t"; with no times there, within
    keep_alive of that start, when an earlier start ran): Ollama keeps it that long, and a stopped start doesn't
    unload it. Everything else was loaded by someone else: Chimera lending, say, or another program."""
    keep = _keep_alive_s() + LEFT_SLACK_S
    starts = sorted(t for t in (_epoch(s.get("started")) for s in (run.get("starts") or []) + [run]) if t is not None)
    ours = {m for s in (run.get("starts") or []) + [run] for m in (s.get("models") or {}).values()}
    called = defaultdict(list)  # model -> sorted times its calls were made
    for key in calls.keys():
        v = calls.get(key) or {}
        if v.get("model"):
            ours.add(v["model"])
            t = _epoch(v.get("t"))
            if t is not None:
                called[v["model"]].append(t)
    for ts in called.values():
        ts.sort()
    left, other = [], []
    for g in foreign:
        t = _epoch(g.get("t"))
        k = bisect.bisect_right(starts, t) - 1 if t is not None else -1
        start = starts[k] if k >= 0 else None
        mine, theirs = [], []
        for m in g.get("models") or []:
            ts = called.get(m) or []
            before = ts[bisect.bisect_left(ts, start) - 1] if start is not None and ts and ts[0] < start else None
            if m in ours and start is not None and (
                    (before is not None and t - before <= keep) or (not ts and k > 0 and t - start <= keep)):
                mine.append(m)
            else:
                theirs.append(m)
        if mine:
            left.append({"t": g.get("t"), "models": mine})
        if theirs:
            other.append({"t": g.get("t"), "models": theirs})
    return left, other


SAMPLERS = ("first samples", "told samples", "second sampler", "repairs", "variants")
FAMILIES = (("blender", ("blender",)), ("code", CODE_MODES), ("section", ("section",)))


def _family(mode):
    return next((f for f, modes in FAMILIES if mode in modes), mode or "?")


def _sampler_of(c, step, calls, repair=False):
    """Which sampler drew a try: the teacher's first batch ("first samples"), its later, told batches ("told
    samples"), the second sampler, a repair, or a variant's draws (the call cache's purpose; the record's sample
    number against the mode's first batch, task.ROUNDS)."""
    if step.get("variant"):
        return "variants"
    if repair:
        return "repairs"
    purpose = (calls.get(c.get("key")) or {}).get("purpose") or ("worker" if c.get("model") == task.TEACHER
                                                                  else "second")
    if purpose == "second":
        return "second sampler"
    return "first samples" if (c.get("sample") or 0) < task.ROUNDS.get(step.get("mode"), (1,))[0] else "told samples"


def samplers(recs, calls, built) -> dict:
    """Per mode family (blender, code, section) and sampler (SAMPLERS): its calls and their model seconds (the call
    cache's time when made, each call once), its gate passes (tries that passed the mode's gate and dep_honesty:
    "mech"), the steps kept from it with an example to give (not a soft keep) and the built examples from it, and
    examples per 1,000 s of its own calls (the judge's and the tests' time is the step's, not a sampler's). Plus the
    second sampler's budget since the fourth smoke (task.Round.solve's step["sampler"], Blender): the steps whose
    second batch heard the notes (heard), those that got a third told batch for it and how many were kept from it (a
    format-5 record's: the third batch was retired after the fifth smoke), and those not sent to the second sampler
    because every teacher sample failed only on Blender API names, with the names."""
    rows = defaultdict(lambda: {"calls": 0, "model_s": 0.0, "gate_passes": 0, "kept": 0, "examples": 0})
    seen = set()
    steps = {}
    budget = {"recorded": 0, "heard": 0, "third": 0, "third_kept": 0, "skipped": 0, "skipped_api": Counter(),
              "asked": 0}
    for r in recs:
        sid0 = (r.get("seed") or {}).get("seed_id")
        for rnd in r.get("rounds") or []:
            for s in (rnd.get("steps") or []) + (rnd.get("variants") or []):
                if not s.get("mode"):
                    continue
                steps[(sid0, rnd.get("round"), s.get("sid"), s.get("variant"))] = s
                fam = _family(s["mode"])
                for c, rep in [(c, False) for c in s.get("candidates") or []] + \
                        [(c, True) for c in s.get("repairs") or []]:
                    row = rows[(fam, _sampler_of(c, s, calls, rep))]
                    if c.get("key") and c["key"] not in seen:
                        seen.add(c["key"])
                        row["calls"] += 1
                        row["model_s"] += (calls.get(c["key"]) or {}).get("wall_s") or c.get("wall_s") or 0.0
                    row["gate_passes"] += bool(c.get("mech"))
                k = s.get("kept")
                reps = s.get("repairs") or []
                if k and not s.get("no_example") and not (  # a repair kept but no example (over the share) gives none
                        k.get("from") == "repair" and not (reps[k["index"]] if k["index"] < len(reps) else {}).get(
                            "example")):
                    rows[(fam, _kept_sampler(s, calls))]["kept"] += 1
                sp = s.get("sampler") or {}
                budget["recorded"] += bool(sp)
                budget["heard"] += bool(sp.get("heard"))
                if sp.get("third"):  # its samples are numbered after the mode's ROUNDS batches'
                    budget["third"] += 1
                    c = s["candidates"][k["index"]] if k and k.get("from") == "cand" else {}
                    budget["third_kept"] += (c.get("sample") or 0) >= sum(task.ROUNDS.get(s["mode"], (1,)))
                if sp.get("second") == "skipped":
                    budget["skipped"] += 1
                    budget["skipped_api"].update(sp.get("api") or [])
                elif sp.get("second") == "asked":
                    budget["asked"] += 1
    for m in built:
        s = steps.get((m.get("seed_id"), m.get("round"), m.get("sid"), m.get("variant")))
        if s is not None:
            rows[(_family(m["mode"]), _kept_sampler(s, calls))]["examples"] += 1
    out = {}
    for (fam, name), row in sorted(rows.items(), key=lambda kv: (kv[0][0], SAMPLERS.index(kv[0][1]))):
        row["model_s"] = round(row["model_s"], 1)
        row["per_1000_s"] = round(1000 * row["examples"] / row["model_s"], 2) if row["model_s"] else None
        out.setdefault(fam, {})[name] = row
    budget["skipped_api"] = dict(sorted(budget["skipped_api"].items()))
    return {"by_family": out, "budget": budget}


def _kept_sampler(step, calls):
    """The sampler a step's kept piece came from (_sampler_of)."""
    k = step.get("kept") or {}
    if k.get("from") == "repair":
        return "repairs" if not step.get("variant") else "variants"
    cands = step.get("candidates") or []
    c = cands[k["index"]] if isinstance(k.get("index"), int) and k["index"] < len(cands) else {}
    if k.get("from") == "second" and not step.get("variant"):
        return "second sampler"
    return _sampler_of(c, step, calls)


def night_failed_deps(built, stats):
    """The failed-dependency cap as a night's build would apply it, for the projection: {"dropped": the examples the
    cap dropped here (build stats' failed_dep_capped), "by_mode": {mode: {"kept", "natural", "dropped", "allowed",
    "back"}}, "by_kind": {kind: examples counted back}}, or None when the build's stats don't list them (a build
    before they did). The cap (build.FAILED_DEP_CAP) keeps natural failed-dependency examples up to 10% of their mode's
    examples, the most r with r <= cap * (others + r), floored: a smoke's 4 Blender examples allow int(0.1 * 4 / 0.9) =
    0, so its two such examples were dropped, where a night's 640 would allow about 71. At a night's scale the floor
    is nothing, so a mode keeps min(natural, cap * others / (1 - cap)) of them, the same share of its examples; what
    that is above the natural ones built here is counted back, shared evenly over the dropped ones' kinds."""
    if "failed_dep_capped" not in stats:
        return None
    dropped = stats.get("failed_dep_capped") or []
    by_mode, by_kind = {}, Counter()
    for mode in sorted({d["mode"] for d in dropped}):
        mine = [d for d in dropped if d["mode"] == mode]
        n = sum(1 for m in built if m["mode"] == mode)
        nat = sum(1 for m in built if m["mode"] == mode and natural_failed_dep(m))
        allowed = FAILED_DEP_CAP * (n - nat) / (1 - FAILED_DEP_CAP)
        back = max(0.0, min(nat + len(mine), allowed) - nat)
        by_mode[mode] = {"kept": n, "natural": nat, "dropped": len(mine), "allowed": round(allowed, 3),
                         "back": round(back, 3)}
        for d in mine:
            by_kind[mix_kind(mode, d.get("kind"))] += back / len(mine)
    return {"dropped": [d["example"] for d in dropped], "by_mode": by_mode,
            "by_kind": {k: round(v, 3) for k, v in sorted(by_kind.items())}}


def projection(data_dir, recs, run, seeds):
    """Seconds of model time per kept example by the plan's kinds, and hours to the plan's mix (finished seeds
    only). Each kind is "measured" (its built examples), an "estimate" (none built: its tries' model time each over
    a keep rate by Laplace's rule of succession, (kept + 1) / (tried + 2), plus the overhead's share of an example)
    or the "mean" of the measured kinds (no tries), as per_kind's "costed" says. A measured kind's examples include
    the share of the failed-dependency examples the cap dropped here that a night's build would keep
    (night_failed_deps: per_kind's "capped_back"; "examples" stays the built count)."""
    recs = [r for r in recs if r.get("status") in FINISHED]
    kind_s = Counter()
    tried, kept = Counter(), Counter()
    examples = Counter()
    overhead = 0.0
    blender_s = 0.0
    for r in recs:
        for rnd in r.get("rounds") or []:
            p = rnd.get("planner") or {}
            overhead += 0.0 if p.get("reused") else (p.get("wall_s") or 0.0)
            overhead += (rnd.get("review") or {}).get("wall_s") or 0.0
        for _, s, secs in seed_steps(r):
            if not s.get("mode"):
                continue
            k = mix_kind(s["mode"], s.get("kind"))
            kind_s[k] += secs
            tried[k] += 1
            kept[k] += bool(s.get("kept")) and not s.get("no_example")
    overhead += sum((t.get("wall_s") or 0.0) for t in (seeds.get("calls") or {}).values())
    built = read_jsonl(os.path.join(data_dir, "sft", "train.meta.jsonl")) + \
        read_jsonl(os.path.join(data_dir, "sft", "valid.meta.jsonl"))
    capped = None
    if built:
        for m in built:
            examples[mix_kind(m["mode"], m["kind"])] += 1
        source = "built"
        capped = night_failed_deps(built, read_json(os.path.join(data_dir, "sft", "stats.json"), {}) or {})
    else:
        for r in recs:
            for _, m in task.examples(r):
                examples[mix_kind(m["mode"], m["kind"])] += 1
        source = "before the build's filters"
    # only into a kind with built examples: one with none is an estimate, whose keep rate counts those steps as kept
    back = {k: v for k, v in ((capped or {}).get("by_kind") or {}).items() if examples.get(k)}
    runs = Cache(os.path.join(data_dir, "cache", "runs.jsonl"))
    for key in runs.keys():
        v = runs.get(key) or {}
        if v.get("kind") == "blender":
            blender_s += v.get("seconds") or 0.0
    total_ex = sum(examples.values()) + sum(back.values())
    each = overhead / total_ex if total_ex else 0.0  # the overhead's share of one example
    per = {}
    for k in sorted(set(PLAN_MIX) | set(examples) | set(tried)):
        n, t = examples.get(k, 0), tried.get(k, 0)
        at = n + back.get(k, 0.0)  # with the failed-dependency examples a night's cap would keep
        per[k] = {"examples": n, "model_s": round(kind_s.get(k, 0.0), 1), "tried": t, "kept": kept.get(k, 0),
                  "s_per_example": round((kind_s.get(k, 0.0) + each * at) / at, 1) if at else None,
                  "costed": "measured" if at else None}
        if back.get(k):
            per[k]["capped_back"] = round(back[k], 3)
        if not at and t:
            rate = (kept.get(k, 0) + 1) / (t + 2)
            per[k].update(costed="estimate", s_per_try=round(kind_s.get(k, 0.0) / t, 1), keep_rate=round(rate, 3),
                          estimate_s=round(kind_s.get(k, 0.0) / t / rate + each, 1))
    parallel = int(run.get("parallel") or 1)
    known = [k for k in PLAN_MIX if per[k]["costed"] == "measured"]
    mean = sum(per[k]["s_per_example"] * PLAN_MIX[k] for k in known) / sum(PLAN_MIX[k] for k in known) if known \
        else None
    secs, costed = 0.0, True
    for k, want in PLAN_MIX.items():
        if per[k]["costed"] is None:
            per[k]["costed"] = "mean" if mean is not None else None
        spe = {"measured": per[k]["s_per_example"], "estimate": per[k].get("estimate_s"), "mean": mean}.get(
            per[k]["costed"])
        costed = costed and spe is not None
        secs += want * (spe or 0.0)
    measured = secs / 3600 / (1 if parallel == 1 else 2)  # two at once: each call's time was measured under the load
    hours = {"1": round(measured if parallel == 1 else measured * PARALLEL_SPEEDUP, 1),
             "2": round(measured / PARALLEL_SPEEDUP if parallel == 1 else measured, 1),
             "measured_at": parallel}
    blender_n = examples.get("blender", 0) + back.get("blender", 0.0)
    per_blender = blender_s / blender_n if blender_n else None
    return {"examples_counted": source, "per_kind": per, "failed_dep_cap": capped, "overhead_s": round(overhead, 1),
            "mean_s": round(mean, 1) if mean is not None else None,
            "hours_to_plan_mix": hours if costed else None, "plan_mix": PLAN_MIX,
            "blender_s_per_example": round(per_blender, 1) if blender_n else None,
            "blender_h_to_plan_mix": round(per_blender * PLAN_MIX["blender"] / 3600, 1) if blender_n else None}


def _times(n):
    return "once" if n == 1 else f"{n} times"


def _cost(v, pr):
    """A kind's seconds per example as the projection's table shows it, marked when it isn't measured."""
    if v.get("costed") == "estimate":
        return f"{v['estimate_s']} (estimate)"
    if v.get("costed") == "mean" and pr.get("mean_s") is not None:
        return f"{pr['mean_s']} (mean)"
    return v["s_per_example"]


def _audit_lines(a, b) -> list:
    """REPORT.md's lines for after_audit and the build's new drops (b: build_stats', or None)."""
    def said(c):
        return ", ".join(f"{k} {v}" for k, v in sorted(c.items())) or "none"
    lines = []
    gates = a.get("gates") or {}

    def fired(g):
        n, steps = sum(gates[g].values()), a["gate_steps"].get(g) or {}
        return (f"{g} on {n} {'try' if n == 1 else 'tries'} ({said(gates[g])}) of {sum(steps.values())} "
                f"{'step' if sum(steps.values()) == 1 else 'steps'} ({said(steps)})")
    if gates or a.get("no_example") or a.get("tests_unreachable"):
        lines += ["After the second smoke run's audit: the new gates fired, " +
                  ("; ".join(fired(g) for g in NEW_GATES if g in gates) or "never") +
                  f". Steps kept only as a dependency (no example): {said(a.get('no_example') or {})}, for "
                  f"{said(a.get('no_example_why') or {})}. Kept code steps whose tests couldn't reach their code "
                  f"(kept, unverified): {said(a.get('tests_unreachable') or {})}.", ""]
    lines += _format4_lines(a)
    rw = a.get("rewrite_errors") or []
    if rw:
        lines += [f"What the tests rewrites said of the candidates they failed ({len(rw)} "
                  f"{'step' if len(rw) == 1 else 'steps'}, rewrite_errors):", "",
                  md_table([["seed", "round", "step", "mode", "tests", "errors"]] +
                           [[x["seed"], x["round"], x["sid"], x["mode"], x["tests"],
                             f"{len(x['errors'])}: " + " / ".join(e[:ERROR_CHARS] for e in x["errors"][:3])]
                            for x in rw]), ""]
    if b and b.get("new"):
        facts = b.get("facts") or {}
        lines += [f"The build's new drops (of {b['examples']} examples, {b['kept']} kept): " +
                  ", ".join(f"{k} {v}" + (f" (fired on {facts[k]['fired']})" if facts.get(k, {}).get("fired", v) != v
                                          else "") for k, v in b["new"].items()) + ".", ""]
    return lines


def _format4_lines(a) -> list:
    """REPORT.md's lines for after_audit's counts since the third smoke (format 4), one a count, each only when it
    has something; the geometry readers' held-out counts with them, or with a geometry gate's firing."""
    def said(c):
        return ", ".join(f"{k} {v}" for k, v in sorted(c.items()) if v) or "none"

    def tries(n):
        return f"{n} {'try' if n == 1 else 'tries'}"
    lines = []
    cc = a.get("ctx_channel") or {}
    if cc:
        def part(key, where):
            c = cc.get(key) or {}
            steps = {k: c[k] for k in ("kept", "dependency only", "dropped") if c.get(k)}
            n = sum(steps.values())
            return f"{where}, {tries(c.get('tries', 0))} of {n} {'step' if n == 1 else 'steps'} ({said(steps)})"
        lines += ["ctx_channel (a ctx key Chimera's join doesn't make; a gate since format 4): " +
                  part("used", "on steps a later step depends on (soft there)") + "; " +
                  part("unused", "on the others, variants among them (hard)") + ".", ""]
    bt = a.get("build_tells") or {}
    if bt:
        def told_part(c, where):
            steps = {k: c[k] for k in ("kept", "dependency only", "dropped") if c.get(k)}
            n = sum(steps.values())
            return f"{where} {tries(c.get('tries', 0))} of {n} {'step' if n == 1 else 'steps'} ({said(steps)})"
        lines += ["What the build would drop, told at the gate, and the stand-in marker's faults (since the fourth "
                  "smoke; soft on steps a later step depends on): " + "; ".join(
                      f"{g} " + told_part(v.get("used") or {}, "used") + ", " + told_part(v.get("unused") or {},
                                                                                         "unused")
                      for g, v in bt.items()) + ".", ""]
    he = a.get("handoff_exempt") or {}
    if he.get("tries"):
        lines += [f"Chimera's handoff_long on a values-only step's provides line (the open contract question: "
                  f"no reason, no tell): {tries(he['tries'])} of {he.get('steps', 0)} "
                  f"{'step' if he.get('steps', 0) == 1 else 'steps'}, {he.get('kept', 0)} of them kept pieces that "
                  "give an example, which the build drops (validator_warning).", ""]
    km = a.get("keyless_markers") or {}
    if km.get("tries"):
        lines += [f"Stand-in markers with no key on a step with a dependency (neither judged nor any read's cover, "
                  f"left so after the second checks of Nov 6): {tries(km['tries'])} of {km.get('steps', 0)} "
                  f"{'step' if km.get('steps', 0) == 1 else 'steps'}, {km.get('kept', 0)} of them kept pieces that "
                  "give an example.", ""]
    sk = a.get("soft_keeps") or {}
    if sk:
        lines += ["Steps kept only as a dependency by each reason, on steps a later step depends on and on the "
                  "others: " + "; ".join(f"{k} {c.get('used', 0)} and {c.get('unused', 0)}" for k, c in sk.items()) +
                  ".", ""]
    vs = a.get("values_steps") or {}
    if vs.get("steps"):
        lines += [f"Values-only steps (hints.values_step: their notes carry the values note): {vs['steps']} ("
                  f"{said({k: vs.get(k, 0) for k in ('kept', 'dependency only', 'dropped')})}); of their kept pieces, "
                  f"{vs.get('writes_values', 0)} write ctx[\"values\"] and {vs.get('hands_on', 0)} handed "
                  "ctx[\"values\"] keys on when run alone.", ""]
    ps = a.get("provides_stand_in") or {}
    if ps:
        lines += ["Chimera's provides_missing warnings: " + "; ".join(
            f'ctx["{ch}"] on {tries(c.get("fired", 0))}, {c.get("own", 0)} of them only for the piece\'s own '
            f'stand-ins (keys it reads or tests too), {c.get("kept", 0)} on kept pieces that give an example '
            f'({c.get("kept_own", 0)} own stand-ins), which the build drops (validator_warning)'
            for ch, c in ps.items()) + ".", ""]
    so = a.get("scene_overruled") or {}
    if so.get("verdicts"):
        lines += [f"Scene-judge rejections overruled (they rest only on a size, a position or an output form the step "
                  f"names): {so['verdicts']} ({said({k: so.get(k, 0) for k in judges.OVERRULED})}), "
                  f"{so.get('kept', 0)} of them on the try kept.", ""]
    vo = a.get("values_in_objects") or {}
    if vo.get("tries"):
        lines += [f"Plain values registered in ctx[\"objects\"] (counted, not a gate; ctx[\"values\"] is theirs): "
                  f"{tries(vo['tries'])}, {vo.get('kept', 0)} of them kept pieces that give an example.", ""]
    s6 = a.get("step6") or {}
    if any(s6.values()):
        lines += [f"Step 6's facts (no reason of their own): hidden errors excused {said(s6.get('excused') or {})}; "
                  f"tries whose hasattr or getattr found no such attribute {s6.get('attr_miss', 0)}; tries whose "
                  f"joined run found a hidden error at the piece's lines (recorded only) "
                  f"{s6.get('joined_silent', 0)}; \"on the floor\" readings {said(s6.get('floor') or {})}; above or "
                  f"below readings {said(s6.get('holds') or {})}; faults of the geometry readers not gated (recorded "
                  f"only) {said(s6.get('off') or {})}; place faults on runs that printed a stand-in (recorded only) "
                  f"{said(s6.get('stood_in') or {})}.", ""]
    rd = a.get("readers") or {}
    if rd and (lines or set(a.get("gates") or {}) & {r for _, r in _GEOMETRY}):
        lines += ["The geometry readers on the held-out steps: " + "; ".join(
            f"{k} read {v.get('read')}, misread {v.get('misread')} ({'gated' if v.get('gated') else 'recorded only'})"
            for k, v in rd.items()) + f" (gated at {geometry.MISREADS} misreads or fewer).", ""]
    rs = a.get("repair_share") or {}
    if rs.get("repairs"):
        def named(xs):
            return f"{len(xs)}" + (f" ({'; '.join(xs)})" if xs else "")
        lines += [f"Repairs with a share on code lines: {rs['repairs']} ({rs.get('passed', 0)} passed, "
                  f"{rs.get('examples', 0)} examples); passed ones on the other side of {task.REPAIR_SHARE:.0%} "
                  f"counted on every line: in {named(rs.get('crossed_in') or [])}, out "
                  f"{named(rs.get('crossed_out') or [])}; passed ones that leave out more than "
                  f"{task.REPAIR_SHRINK:.0%} of their code lines (no example) {named(rs.get('shrunk') or [])}.", ""]
    return lines


def _sampler_lines(sm) -> list:
    """REPORT.md's lines for samplers() (nothing for a report.json made before it)."""
    if not sm or not sm.get("by_family"):
        return []
    rows = [["mode", "sampler", "calls", "model s", "gate passes", "kept", "examples", "examples per 1,000 s"]]
    for fam, by in sm["by_family"].items():
        for name, r in by.items():
            rows.append([fam, name, r["calls"], r["model_s"], r["gate_passes"], r["kept"], r["examples"],
                         "" if r["per_1000_s"] is None else r["per_1000_s"]])
    b = sm.get("budget") or {}
    api = ", ".join(f"{k} {v}" for k, v in (b.get("skipped_api") or {}).items())
    out = ["## Samplers", "",
           "Each sampler's own calls (each once, at the time they took when made), the tries of its that passed the "
           "gate and dep_honesty, the steps kept from it with an example to give, and the built examples from it "
           "(told samples: the teacher's batches after its first, which name the earlier tries' failures; the judge's "
           "and the tests' time is the step's, not in these):", "", md_table(rows), ""]
    if b.get("recorded"):  # records made before the fourth smoke's round have no step["sampler"]
        third = (f"{b['third']} got a third told batch because their second heard the notes ({b['third_kept']} kept "
                 "from it); ") if b.get("third") else (  # a format-5 record's; retired after the fifth smoke
            f"{b.get('heard', 0)} had a second batch that heard the notes, which draws no third batch since the fifth "
            "smoke; ")
        out += [f"The second sampler's budget (Blender, {b['recorded']} steps past their batches): " + third +
                f"{b['skipped']} weren't sent to the second sampler because every teacher sample failed only on "
                "Blender API names" + (f" ({api})" if api else "") + f"; {b['asked']} were.", ""]
    return out


def _n(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def _capped_lines(pr) -> list:
    """REPORT.md's line for the failed-dependency cap in the projection (night_failed_deps)."""
    fc = pr.get("failed_dep_cap")
    if pr.get("examples_counted") != "built":
        return []
    if fc is None:
        return ["The build's stats don't list what the failed-dependency cap dropped (a build before they did), so "
                "the projection counts only the built examples.", ""]
    if not fc.get("dropped"):
        return []
    modes = "; ".join(f"{m} {v['dropped']} of them, with {_n(v['kept'], 'example')} kept and {v['natural']} of "
                      f"those written so, where a night keeps {v['allowed']:.2f}" for m, v in fc["by_mode"].items())
    back = {k: v["capped_back"] for k, v in pr["per_kind"].items() if v.get("capped_back")}
    left = sorted(k for k in fc.get("by_kind") or {} if k not in back)
    return [f"The failed-dependency cap (natural ones at most {100 * FAILED_DEP_CAP:.0f}% of their mode's examples, "
            f"floored) dropped {_n(len(fc['dropped']), 'example')} here ({', '.join(fc['dropped'])}): {modes}. A "
            "night's hundreds of examples don't feel the floor, so the projection counts back what it would keep at "
            "the same share: " + (", ".join(f"{k} {v:.2f}" for k, v in back.items()) or "none") + "." +
            (f" Not {', '.join(left)}: with no built examples it is an estimate, whose keep rate already counts "
             "those steps as kept." if left else ""), ""]


def markdown(rep) -> str:
    s = rep.get("seeds") or {}
    lines = [f"# Hydra Worker data generation: {rep.get('size') or ''}", ""]
    w = rep["wall"]
    done = {k: v for k, v in rep["status"].items() if k in FINISHED}
    status = ", ".join(f"{k} {v}" for k, v in done.items())
    elapsed = f", {w['elapsed_h']} h from the first start to the last finished seed" if w["elapsed_h"] else ""
    lines += [f"Seeds finished: {sum(done.values())} ({status}); {w['seed_seconds'] / 3600:.2f} h of seed "
              f"time{elapsed}.", ""]
    if rep.get("errored"):
        lines += [f"**Errored seeds: {rep['errored']}.** They are left out of everything below (the projection too); "
                  "run the same command again to retry them.", ""]
    if s:
        lines += ["## Seeds", "",
                  f"{s.get('seeds', 0)} used of {s.get('kept', 0)} kept and {s.get('offered', 0)} offered. Dropped: " +
                  (", ".join(f"{k} {v}" for k, v in (s.get("dropped") or {}).items() if v) or "none") + ".", ""]
        rows = [["target", "calls", "answered", "errors", "unreadable", "tasks", "wall s"]]
        for t, c in (s.get("calls") or {}).items():
            rows.append([t, c.get("calls"), c.get("answered"), c.get("errors"), c.get("unreadable"), c.get("tasks"),
                         c.get("wall_s")])
        if len(rows) > 1:
            lines += [md_table(rows), ""]
    p = rep["plans"]
    lines += ["## Plans", "", md_table([["planner", "plans"]] + [[k, v] for k, v in sorted(p["by_planner"].items())]),
              "", md_table([["model", "asked", "read"]] + [[m, v["asked"], v["read"]] for m, v in
                                                           p["read_rate"].items()]), ""]
    hows = ["first samples", "more samples", "repairs", "second sampler", "dependency only", "dropped", "plan_failed"]
    lines += ["## Steps", "", md_table([["mode", "tried"] + hows] +
                                       [[m, c.get("tried", 0)] + [c.get(h, 0) for h in hows]
                                        for m, c in sorted(rep["steps"].items())]), ""]
    if rep["drops"]:
        lines += ["Dropped steps by the reason of the candidate that got furthest:", "",
                  md_table([["mode", "reason", "steps"]] + [[m, k, v] for m, c in sorted(rep["drops"].items())
                                                            for k, v in sorted(c.items(), key=lambda kv: -kv[1])]), ""]
    if rep.get("tests"):
        lines += ["Kept code steps by their tests (unconfirmed: the piece was kept without ever passing the teacher's "
                  "tests; none:third_party: it couldn't run for a package outside the standard library; "
                  "none:tests_refused: the tests writer's replies broke the reader's rules; the build leaves these "
                  "three out unless --keep-untested; none:tests_unreachable: the tests couldn't reach the step's "
                  "code, kept and marked unverified):", "",
                  md_table([["mode", "tests", "steps"]] + [[m, k, v] for m, c in sorted(rep["tests"].items())
                                                           for k, v in sorted(c.items(), key=lambda kv: -kv[1])]), ""]
    lines += _sampler_lines(rep.get("samplers"))
    a = rep.get("after_smoke") or {}
    if any(a.values()):
        def said(c):
            return ", ".join(f"{k} {v}" for k, v in sorted(c.items())) or "none"
        no_py = ", ".join(f"{m} {c['steps']} of {c['of']}" for m, c in sorted((a.get("no_python") or {}).items()))
        lines += ["After the smoke run's changes: replies made plain (" +
                  ("; ".join(f"{m}: {said(c)}" for m, c in sorted(a.get("normalised", {}).items())) or "none") +
                  f"); dropped for a Blender version only the notes name: {said(a.get('version_leak') or {})}; "
                  f"for the notes' words for the Blenders or the sandbox: {said(a.get('notes_leak') or {})}; "
                  f"tests refused and asked again: {said(a.get('tests_refused') or {})}; what those retries gave: "
                  f"{said(a.get('tests_retries') or {})}; tests rewrites: "
                  f"{said(a.get('tests_rewrites') or {})}; sections judged with a dependency missing: "
                  f"{said(a.get('missing_dep_judged') or {})}.", "",
                  "Kept code steps with no tests that ran: tests still refused after the retry (dropped): "
                  f"{said(a.get('refused_untested') or {})}; a package outside the standard library missing from the "
                  f"import run (dropped): {said(a.get('third_party_import') or {})}; no tests given although the step "
                  f"names a callable (kept): {said(a.get('no_tests_callable') or {})}; no Python to test (kept, "
                  f"unverified): {no_py or 'none'}; nothing ran on them at all, those among them (kept, unverified): "
                  f"{said(a.get('nothing_ran') or {})}.", ""]
    lines += _audit_lines(rep.get("after_audit") or {}, rep.get("build"))
    if rep["variants"]:
        lines += ["## Variants", "", md_table([["variant", "tried", "kept", "dropped", "skipped"]] +
                                              [[k, c.get("tried", 0), c.get("kept", 0), c.get("dropped", 0),
                                                c.get("skipped", 0)] for k, c in sorted(rep["variants"].items())]), ""]
    lines += ["## Plan checks and round 2", "",
              md_table([["plan check", "rounds"]] + [[k, v] for k, v in sorted(rep["plan_checks"].items())]) if
              rep["plan_checks"] else "No plan checks.", "",
              "Round 2: " + (", ".join(f"{k} {v}" for k, v in sorted(rep["round2"].items())) or "none") + ".", ""]
    lines += ["## Model time", "", md_table([["model and purpose", "calls", "wall s", "eval tokens", "errors"]] +
                                            [[k, v["calls"], v["wall_s"], v["eval_tokens"], v["errors"]]
                                             for k, v in rep["model_time"].items()]), ""]
    mt, left = rep["model_time"].values(), rep.get("calls_left_out") or {}
    earlier, earlier_s = sum(v.get("earlier", 0) for v in mt), round(sum(v.get("earlier_s", 0.0) for v in mt), 1)
    lines += [f"Only the calls the records use, each once ({sum(v['calls'] for v in mt)})." +
              (f" Of them, {earlier} ({earlier_s} s) came from a run whose cache this one was seeded with: made "
               "before this run's first start, answered from the cache here." if earlier else "") +
              (f" Left out of the table: {left['calls']} {'call' if left['calls'] == 1 else 'calls'} in the cache "
               f"that no record uses ({left['wall_s']} s)." if left.get("calls") else ""), "",
              f"Gate: {rep['gate']['switches']} model switches ({rep['gate']['by_why']}), "
              f"{rep['gate']['waits_over_60s']} waits of a minute or more. Runs: {rep['runs']}.", ""]
    g = rep["gate"]
    if g.get("left_loaded"):
        lines += [f"**Left loaded by this run's own earlier starts:** {_times(g['left_loaded'])} a model this "
                  f"start hadn't called yet was loaded ({', '.join(g['left_loaded_models'])}), within keep_alive "
                  f"({g.get('keep_alive') or KEEP_ALIVE}) of that model's last call by an earlier start of this run. "
                  "A stopped start doesn't unload its models, so these are the run's own, not Chimera lending.", ""]
    if g.get("other"):
        lines += [f"**Other models in Ollama:** {_times(g['other'])} a model was loaded that this start hadn't "
                  f"called and no earlier start of this run left ({', '.join(g['other_models'])}): Chimera lending, "
                  "say, or another program. Their loads and the waits for them are in the call times, so the model "
                  "time and the projection are too high.", ""]
    pr = rep["projection"]
    lines += ["## Projection", "",
              f"Examples counted: {pr['examples_counted']}. Seed writing, planning and reviewing "
              f"({pr['overhead_s']} s) are shared out by examples.", "",
              md_table([["kind", "tried", "kept", "examples", "model s", "s per example", "plan wants"]] +
                       [[k, v.get("tried", ""), v.get("kept", ""), v["examples"] if not v.get("capped_back") else
                         f"{v['examples']} (+{v['capped_back']:.2f})", v["model_s"], _cost(v, pr),
                         PLAN_MIX.get(k, "")] for k, v in pr["per_kind"].items()]), ""]
    lines += _capped_lines(pr)
    h = pr.get("hours_to_plan_mix")
    if h:
        lines += [f"Hours of model time to the plan's {sum(PLAN_MIX.values())} examples: {h['1']} at 1 parallel "
                  f"request, {h['2']} at 2 (measured at {h['measured_at']}; the other assumes {PARALLEL_SPEEDUP}x)."]
        for k, v in pr["per_kind"].items():
            if v.get("costed") == "estimate":
                lines += [f"{k} has no built examples, so it is costed from its own {v['tried']} tries "
                          f"({v['s_per_try']} s of model time each) at an estimated keep rate of "
                          f"{100 * v['keep_rate']:.0f}%, Laplace's rule (kept + 1) / (tried + 2) with {v['kept']} "
                          f"kept: {v['estimate_s']} s per example, the overhead's share included." +
                          (" So few tries make it rough." if v["tried"] < 10 else "")]
            elif v.get("costed") == "mean" and k in PLAN_MIX:
                lines += [f"{k} had no tries here, so it is costed at the plan-weighted mean of the measured kinds "
                          f"({pr['mean_s']} s per example)."]
    if pr.get("blender_h_to_plan_mix") is not None:
        lines += [f"Blender: {pr['blender_s_per_example']} s of runs per Blender example, about "
                  f"{pr['blender_h_to_plan_mix']} h for {PLAN_MIX['blender']} (they overlap the model calls)."]
    return "\n".join(lines).rstrip() + "\n"
