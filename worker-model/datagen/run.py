#!/usr/bin/env python3
"""Make Hydra Worker 1.0's training data (DESIGN.md, "run.py and sizes.py"): seeds, then every seed's task through
Chimera's own requests, then the training files and the report.

    python3 -m datagen.run --size smoke --data-dir data/gen/smoke6   # a smoke run, in a folder of its own
    python3 -m datagen.run --size night                              # the overnight run, resumable, in data/gen/night/
    python3 -m datagen.run --size night --stages build,report        # rebuild the training files and the report only
    touch data/gen/night/STOP                                        # stop after the calls in flight (exit 3)

Every stage is resumable: run the same command again and it carries on where it stopped, replaying unfinished seeds
from the caches. Exit codes: 0 done; 1 the build found eval text in the training files (sft/flagged/) or something
else failed; 2 Ollama, a model, the Chimera binary, a Blender or Python in the sandbox is missing (or most seed calls
failed), or Chimera's requests have changed since the last start that ran the tasks stage here (--new-binary-ok
carries on and makes the seeds made with the old ones again); 3 stopped (STOP, or an early stop: STOPPED.md says
why); 4 every stage ran, but some seeds ended in an error (run again to retry them); 130 Ctrl-C.

Each start that runs the tasks or build stage takes Chimera's fingerprint: a hash of the requests the binary makes
for fixed inputs and of the names sheets its Blenders print now. Every task record carries it, and the build keeps
only the records with the current one, so the training input is always what this Chimera sends. Every record also
carries the data generator's own DATAGEN_FORMAT (task.py's, 6 since the fifth smoke run): a seed made by an older one
(the first smoke run's records, which have none, count as 1; the second's are 2, the third's 3, the fourth's 4, the
fifth's 5) is made again by the tasks stage and dropped by the build (old_format), since its pieces were checked and
judged by rules that have changed since, while Chimera's requests may not have.

A start whose data folder holds a run that has finished, made by another data generator format (the first five
smoke runs'), is refused (exit 2, unless --new-binary-ok), whatever its size and whether the folder is the default or
given as --data-dir: every start there would change that run's folder (the tasks stage would make its seeds again,
the build would drop all its records and replace sft/ with nothing, the report rewrite REPORT.md, and RUN.json would
record the start), and this generator can't rebuild it. Re-running the second smoke's own command, --data-dir
data/gen/smoke2, would have done just that after the bump to format 3 (on a scratch copy: 16 model calls and its sft/
replaced), and so would the third's, --data-dir data/gen/smoke3, after the bump to 4, and the fourth's, --data-dir
data/gen/smoke4, after the bump to 5, and the fifth's, --data-dir data/gen/smoke5, after the bump to 6: the sixth
smoke run goes into data/gen/smoke6. run_datagen.sh refuses such a folder too, and any finished smoke in
data/gen/smoke/.

Nothing is written outside --data-dir but the Blender and Python run folders under $WM_SCRATCH, which are removed
after each run. Unset, it is a folder in $TMPDIR (else /tmp) outside the home folder, as run_datagen.sh sets it
(scratch_default; tools/blender_check's own default, data/scratch, is under /Users), since the sandbox can't read
/Users and node's check of a .js file can't start in a run folder there: such files' examples would then all be
dropped as unchecked_code. One set under /Users or /Volumes is used as it is, with a warning. Nothing is pulled: a
missing model is an exit 2 with the command to pull it.
"""
from __future__ import annotations

import argparse
import glob
import os
import queue
import sys
import threading
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from datagen import build as build_mod  # noqa: E402
from datagen import report as report_mod  # noqa: E402
from datagen import seeds as seeds_mod  # noqa: E402
from datagen import sizes, task  # noqa: E402
from datagen.common import (DATA_ROOT, RUN_FILE, STOPPED_FILE, Cache, Progress, Stopped, StopRequested,  # noqa: E402
                            Store, key_of, log_line, now_iso, read_json, read_jsonl, run_record, stop_path,
                            write_json, write_stopped)

STAGES = ("seeds", "tasks", "build", "report")
BIN_DEFAULT = os.path.join(DATA_ROOT, "bin", "chimera")  # where run_datagen.sh builds it
HELPER_RAW = os.path.join(HERE, "..", "helper-model", "data", "raw")
TASKS_FILE = "tasks.jsonl"
EARLY_FILE = "early_stop.json"  # the early stop's point was reached here: it's checked once per data folder
FINISHED = ("done", "no_plan")  # a seed with one of these statuses is skipped on resume; errors run again
ERRORS_IN_A_ROW = 6  # seeds that end in an error one after another before the run stops (Ollama gone, say)
ERRORED = 4  # main's exit code when every stage ran but some seeds ended in an error
CANARY = "wm-canary"  # what the sandbox check's script prints
DATAGEN_FORMAT = task.DATAGEN_FORMAT  # 6: a record of another (the five smoke runs' are 1-5) is made again

# The fixed inputs of fingerprint(): a Blender plan and a code plan of two steps each, with their goals, a names text,
# a result to review and improve, a critique, and a piece with its crash for a repair. Only the requests Chimera makes
# from them are hashed; nothing here is stored or trained on.
FP_NAMES = "Names sheet for the fingerprint."
FP_RESULT = "The result so far, for the fingerprint."
FP_CRITIQUE = "What still needs work, for the fingerprint."
FP_PIECE = "The piece that crashed, for the fingerprint."
FP_CRASH = {"step": "s2", "part": "", "function": "build_s2", "piece_line": 2, "line": 12,
            "source": "x = missing", "error": "NameError: name 'missing' is not defined"}
FP_PLANS = (
    ("Make a small room with a lamp in Blender.",
     {"title": "Lamp room", "kind": "blender", "summary": "A floor and a lamp above it.", "steps": [
         {"id": "s1", "title": "Floor", "kind": "blender", "depends_on": [],
          "instructions": "Make a 4 m floor plane and register it as ctx['objects']['floor']."},
         {"id": "s2", "title": "Lamp", "kind": "blender", "depends_on": ["s1"],
          "instructions": "Hang a point lamp 2.5 m above s1's floor."}]}),
    ("Write a Python tool that totals a line of numbers.",
     {"title": "Tally tool", "kind": "code", "summary": "A tool that totals a line of numbers.", "steps": [
         {"id": "s1", "title": "Parser", "kind": "code", "depends_on": [],
          "instructions": "Write tool/parse.py with parse_line(line), which splits a comma-separated line."},
         {"id": "s2", "title": "Totals", "kind": "code", "depends_on": ["s1"],
          "instructions": "Write tool/totals.py with total(line), using parse_line from s1."}]}),
    ("Write a Python script that prints the first 10 primes.",  # python-script mode
     {"title": "Primes", "kind": "code", "summary": "A script that prints the first 10 primes.", "steps": [
         {"id": "s1", "title": "Prime test", "kind": "code", "depends_on": [],
          "instructions": "Write is_prime(n) and primes(n), which returns the first n primes."},
         {"id": "s2", "title": "Main", "kind": "code", "depends_on": ["s1"],
          "instructions": "Write main(), which prints primes(10) from s1, and call it."}]}),
    ("Write a short guide to watering houseplants.",  # section mode
     {"title": "Watering guide", "kind": "writing", "summary": "A short guide to watering houseplants.", "steps": [
         {"id": "s1", "title": "How often", "kind": "writing", "depends_on": [],
          "instructions": "Write a section on how often to water."},
         {"id": "s2", "title": "Signs", "kind": "writing", "depends_on": ["s1"],
          "instructions": "Write a section on signs of over- and under-watering."}]}),
    ("Write a haiku about rain.",  # a one-step plan: the lone opening
     {"title": "Rain haiku", "kind": "writing", "summary": "A haiku about rain.", "steps": [
         {"id": "s1", "title": "Haiku", "kind": "writing", "depends_on": [],
          "instructions": "Write a haiku about rain."}]}),
)


class Stopper:
    """The gate's stop check: raises StopRequested when data_dir/STOP exists or the run has asked to stop (an early
    stop, errors in a row, Ctrl-C)."""

    def __init__(self, data_dir):
        self.path = stop_path(data_dir)
        self.event = threading.Event()
        self.why = None

    def stop(self, why):
        if not self.event.is_set():
            self.why = why
            self.event.set()

    def requested(self):
        if self.event.is_set():
            return True
        if os.path.exists(self.path):
            self.stop(f"{self.path} exists")
            return True
        return False

    def __call__(self):
        if self.requested():
            raise StopRequested(self.why)


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", choices=sorted(sizes.SIZES), default="smoke")
    ap.add_argument("--data-dir", help="default: worker-model/data/gen/<size>")
    ap.add_argument("--stages", default=",".join(STAGES), help="comma-separated, from " + ", ".join(STAGES))
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "127.0.0.1:11434"))
    ap.add_argument("--chimera", default=os.environ.get("CHIMERA_BIN") or BIN_DEFAULT,
                    help="the Chimera binary (default $CHIMERA_BIN, else data/gen/bin/chimera)")
    ap.add_argument("--limit", type=int, help="only the first N seeds of the size (seeds come interleaved by kind)")
    ap.add_argument("--keep-plan-failed", action="store_true", help="build: keep the examples of plans whose joined "
                    "result failed its plan check")
    ap.add_argument("--parallel", type=int, default=1, help="model calls in flight at once (OLLAMA_NUM_PARALLEL "
                    "must allow it; default 1)")
    ap.add_argument("--keep-untested", action="store_true", help="build: keep the code examples whose tests failed "
                    "on the stub and that were kept without them (tests unconfirmed), those that couldn't run for a "
                    "package outside the standard library (none:third_party), and those whose tests writer's replies "
                    "were refused (none:tests_refused)")
    ap.add_argument("--no-early-stop", action="store_true", help="carry on even when few steps keep a piece")
    ap.add_argument("--new-binary-ok", action="store_true", help="carry on although Chimera's requests have changed "
                    "since the last start here; the seeds made with the old ones are made again (a build-only start: "
                    "build although some records are of other requests or another data generator format; a smoke "
                    "start without --data-dir: start in data/gen/smoke/ although a finished smoke of another format "
                    "is there)")
    ap.add_argument("--timeout", type=float, default=900.0, help="seconds per model call")
    a = ap.parse_args(argv)
    a.stages = [s.strip() for s in a.stages.split(",") if s.strip()]
    bad = [s for s in a.stages if s not in STAGES]
    if bad:
        ap.error(f"unknown stage(s) {bad}; pick from {', '.join(STAGES)}")
    return a


SCRATCH_NAME = "chimera-wm-scratch"  # run_datagen.sh's folder in $TMPDIR
_HOME_LIKE = ("/Users/", "/Volumes/")  # the sandbox reads neither (run_datagen.sh's rule for $TMPDIR)


def scratch_default(env=os.environ):
    """Sets WM_SCRATCH in env as run_datagen.sh does when it isn't set (a folder in $TMPDIR, or /tmp when that is
    unset or in the home folder or on another volume), so a direct start's run folders are outside /Users too. A
    warning (str) when the one given is under /Users or /Volumes, else None."""
    given = env.get("WM_SCRATCH")
    if not given:
        tmp = (env.get("TMPDIR") or "").rstrip("/")
        env["WM_SCRATCH"] = os.path.join("/tmp" if not tmp or (tmp + "/").startswith(_HOME_LIKE) else tmp,
                                         SCRATCH_NAME)
        return None
    if (os.path.realpath(given) + "/").startswith(_HOME_LIKE):
        return (f"WM_SCRATCH is {given}, which the sandbox can't read: node can't check a .js file there, so such "
                "files' examples are dropped as unchecked_code. Unset it, or set one outside the home folder.")
    return None


def say(msg, log=None):
    print(msg, file=sys.stderr, flush=True)
    log_line(log, msg)


# ---------------------------------------------------------------- what a run needs

def models_needed(stages):
    need = []
    if "seeds" in stages or "tasks" in stages:
        need.append(task.TEACHER)
    if "tasks" in stages:
        need += [task.HELPER, task.SECOND, task.SMALL]
    return need


def check_ollama(host, need):
    """(Ollama's version, None) or (None, why it can't be used)."""
    from runner import common as rc
    client = rc.Ollama(host, 30)
    try:
        version = client.version()
        have = set()
        for m in client.tags():
            have.update(x for x in (m.get("name"), m.get("model")) if x)
    except rc.OllamaError as e:
        return None, str(e)
    missing = []
    for m in need:
        if m in have or (":" not in m and m + ":latest" in have):
            continue
        try:
            client.show(m)
        except rc.OllamaError:
            missing.append(m)
    if missing:
        return None, "not in Ollama: " + ", ".join(missing) + " (ollama pull " + " ".join(missing) + ")"
    return version, None


def names_sheets(ch, versions, data_dir, scratch):
    """{version: sheet}, printed by that Blender (chimera --blender-names) at every start and written to
    names/<version>.txt for the record. Never read back: a changed Chimera, or a Blender updated in place, prints
    another sheet, and the requests (and the fingerprint) must carry the one they print now."""
    out = {}
    for v, path in versions.items():
        sheet = ch.blender_names(path, scratch)
        f = os.path.join(data_dir, "names", v + ".txt")
        os.makedirs(os.path.dirname(f), exist_ok=True)
        tmp = f + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(sheet + "\n")
        os.replace(tmp, f)
        out[v] = sheet
    return out


def fingerprint(ch, names) -> str:
    """What this Chimera sends, as one hash (common.key_of): the worker request of every step of FP_PLANS (the
    earlier steps done, FP_NAMES as the names text, names_gate on), and for the last step: its request with every
    earlier step failed (a plan of several), its repair request (FP_PIECE and FP_CRASH; not for writing) and its
    round-2 request (FP_RESULT and FP_CRITIQUE); the planner's requests for round 1 and round 2, the reviewer's
    request, and the names sheets ({version: sheet}). FP_PLANS covers every mode (blender, files, python-script,
    section) and the lone opening. A record made under another fingerprint holds requests this binary doesn't send.
    (The binary's sha would be too strict: it changes with every commit.)"""
    parts = []
    for goal, plan in FP_PLANS:
        for i in range(len(plan["steps"])):
            done = {s["id"]: f"The piece of {s['id']}, done." for s in plan["steps"][:i]}
            parts.append(ch.worker_request(plan, i, done, goal=goal, names=FP_NAMES, names_gate=True))
        if i:
            parts.append(ch.worker_request(plan, i, {}, goal=goal, names=FP_NAMES, names_gate=True))
        if plan["kind"] != "writing":
            crash = dict(FP_CRASH, runner="Blender 5.2.2" if plan["kind"] == "blender" else "Python 3.13.0")
            parts.append(ch.worker_request(plan, i, done, goal=goal, names=FP_NAMES, names_gate=True,
                                           piece=FP_PIECE, crash=crash))
        parts.append(ch.worker_request(plan, i, done, goal=goal, names=FP_NAMES, names_gate=True,
                                       prev_result=FP_RESULT, critique=FP_CRITIQUE))
        parts.append(ch.plan_request(goal))
        parts.append(ch.plan_request(goal, prior=FP_RESULT, critique=FP_CRITIQUE))
        parts.append(ch.review_request(goal, FP_RESULT))
    return key_of("fingerprint", parts, names)


def last_fingerprint(data):
    """The fingerprint the last start that ran the tasks stage here recorded in RUN.json (None: no such start, or
    one from before fingerprints)."""
    run = read_json(os.path.join(data, RUN_FILE), None)
    if not isinstance(run, dict):
        return None
    for st in [run] + list(reversed(run.get("starts") or [])):
        if isinstance(st, dict) and "tasks" in (st.get("stages") or ()):
            return st.get("fingerprint")
    return None


def changed_requests(data, store, fp):
    """Why the tasks stage mustn't carry on here (a message for an exit 2), or None: tasks.jsonl has records and the
    last start that ran the tasks stage had another fingerprint (or none)."""
    if not len(store):
        return None
    last = last_fingerprint(data)
    if last == fp:
        return None
    old = sum(1 for r in store.all() if r.get("fingerprint") != fp)
    return (f"Chimera's requests have changed since the last start here (fingerprint {last or 'not recorded'} then, "
            f"{fp} now): {old} of the {len(store)} seeds in {TASKS_FILE} were made with requests this Chimera doesn't "
            "send, so their examples wouldn't be its own. Run again with --new-binary-ok to make those seeds again "
            "with this binary (the build keeps only records with the current fingerprint), or go back to the binary "
            "that made them, or give another --data-dir.")


def other_formats(records):
    """The formats of the finished records another version of the data generator made (task.record_format isn't
    DATAGEN_FORMAT), one per record: the tasks stage makes those seeds again, the build drops them (old_format)."""
    return [task.record_format(r) for r in records
            if r.get("status") in FINISHED and task.record_format(r) != DATAGEN_FORMAT]


def finished_run(data):
    """Why a start mustn't touch data (a message for an exit 2), or None: data, the size's default folder or the one
    --data-dir gives, holds a run that has finished (REPORT.md written, every seed of seeds.jsonl done or no_plan, a
    seed's last record winning, as run_datagen.sh reads it) and whose finished records another data generator format
    made, every one of them (task.record_format: the first smoke run's are 1, the second's 2, the third's 3, the
    fourth's 4, the fifth's 5). A folder of this format, an unfinished one and a new one are left alone. Read only:
    Store would mend the file's tail."""
    if not os.path.isfile(os.path.join(data, "REPORT.md")):
        return None
    last = {}
    for r in read_jsonl(os.path.join(data, TASKS_FILE)):
        if isinstance(r, dict) and "key" in r:
            last[r["key"]] = r
    seeds = [s.get("seed_id") for s in read_jsonl(os.path.join(data, seeds_mod.SEEDS_FILE)) if isinstance(s, dict)]
    if not seeds or not all((last.get(s) or {}).get("status") in FINISHED for s in seeds):
        return None
    formats = {task.record_format(last[s]) for s in seeds}
    if DATAGEN_FORMAT in formats:
        return None
    return (f"{data} holds a run that has finished, made by another version of the data generator (format "
            f"{', '.join(map(str, sorted(formats)))}, {DATAGEN_FORMAT} now). A start there would change it: the tasks "
            "stage would make its seeds again, the build would drop all its records (old_format) and replace sft/ "
            "with nothing, the report would rewrite REPORT.md, and RUN.json would record the start. This generator "
            "can't rebuild that folder's files. Give a new run its own folder (--data-dir data/gen/smoke6, say; "
            "--limit N for fewer seeds), or --new-binary-ok to go ahead anyway.")


def sandbox_canary(work):
    """None when python3 starts in the sandbox the code gate runs it in and prints CANARY; else why not. Without this
    an interpreter that can't start there (/usr/bin/python3, the Xcode shim: exit 71) makes every Python run a
    failure with no traceback, cached as the script's: no tests ever valid, and every import run passing."""
    from datagen import pysandbox
    got = pysandbox.run({"canary.py": f"import sys\nprint({CANARY!r}, sys.version_info[:2])\n"}, "canary.py",
                        work=work)
    out = got.get("output") or ""
    if got.get("exit") == 0 and any(line.startswith(CANARY + " (") for line in out.splitlines()):
        return None
    last = got.get("error") or next((l.strip() for l in reversed(out.splitlines()) if l.strip()), "no output")
    return (f"python3 doesn't run in the sandbox ({pysandbox.python3()}: exit {got.get('exit')}, {last}). Put a "
            "working python3 first on PATH (not /usr/bin/python3, the Xcode shim), then run this again.")


def make_env(a, size, data, stopper, log, chimera_bin, gate_kw=None, tasks=True, eval_index=None):
    """The models, the binary, the gates and everything else a seed needs (task.Env, plus env.fingerprint); with
    tasks=False only the models (the seeds stage needs no Blender, and its env has no fingerprint). gate_kw:
    llm.Gate keywords on top of the defaults (tests shorten idle_switch_s); eval_index: the run's EvalIndex. Raises
    ValueError without the RNA dumps or when Python doesn't run in the sandbox (sandbox_canary), ChimeraError when a
    Blender can't print its names."""
    from datagen import blender_gate, code_gate, llm
    from datagen.chimera import Chimera
    from tools import blender_check, blenders, rna_lint
    scratch = blender_check.scratch_root()
    ch = Chimera(chimera_bin, env={"OLLAMA_HOST": a.host})
    gate = llm.Gate(**dict({"parallel": a.parallel, "log_path": os.path.join(data, "gate.jsonl"), "stop": stopper},
                           **(gate_kw or {})))
    models = llm.LLM(a.host, gate, Cache(os.path.join(data, "cache", "calls.jsonl")), timeout=a.timeout)
    runs = Cache(os.path.join(data, "cache", "runs.jsonl"))
    if not tasks:
        env = task.Env(llm=models, chimera=ch, blender=None, code=None, facts=None, names={}, size=size,
                       data_dir=data, work=scratch, runs=runs, log_path=log, eval_index=eval_index)
        env.fingerprint = None
        return env
    why = sandbox_canary(scratch)
    if why:
        raise ValueError(why)
    facts = rna_lint.Facts.load()
    # the lint's guarded-read rule is data generation's (rna_lint.Linter's guards, decided Nov 6)
    bg = blender_gate.BlenderGate(ch, runs, versions=blenders.VERSIONS, linter=rna_lint.Linter(facts, guards=True),
                                  work=scratch)
    cg = code_gate.CodeGate(ch, runs, work=scratch)
    names = names_sheets(ch, blenders.VERSIONS, data, scratch)
    raw = task.raw_plans(sorted(glob.glob(os.path.join(HELPER_RAW, "plans*.jsonl"))))
    env = task.Env(llm=models, chimera=ch, blender=bg, code=cg, facts=facts, names=names, size=size,
                   data_dir=data, work=scratch, runs=runs, raw_plans=raw, log_path=log, eval_index=eval_index)
    env.fingerprint = fingerprint(ch, names)
    return env


# ---------------------------------------------------------------- the tasks stage

def kept_share(records):
    """(seeds done, round-1 steps tried, steps that kept a piece) over finished records. A step kept only as a
    dependency (no_example: task.SOFT_REASONS) isn't counted as kept: the early stop asks whether the teacher's pieces
    give examples, and those give none."""
    seeds = tried = kept = 0
    for r in records:
        if r.get("status") != "done":
            continue
        seeds += 1
        steps = ((r.get("rounds") or [{}])[0].get("steps")) or []
        tried += len(steps)
        kept += sum(1 for s in steps if s.get("kept") and not s.get("no_example"))
    return seeds, tried, kept


def _summary(rec):
    if rec["status"] != "done":
        return rec["status"] + (f" {rec['error']}" if rec.get("error") else "")
    steps = [s for r in rec["rounds"] for s in r.get("steps") or []]
    kept = sum(1 for s in steps if s.get("kept") and not s.get("no_example"))
    soft = sum(1 for s in steps if s.get("kept") and s.get("no_example"))
    return f"{kept}/{len(steps)} steps kept" + (f" ({soft} more only as a dependency)" if soft else "") + \
        f", {len(rec['rounds'])} round(s)"


def run_tasks(env, seeds, store, stopper, size, *, log=None, early_stop=True):
    """Every seed that has no finished record, size["seeds_parallel"] at a time, in daemon threads (Ctrl-C ends the
    process at once; the caches keep what finished). Returns {"done", "skipped", "errors", "stopped"}; raises
    StopRequested after the seeds in flight when the run is asked to stop (STOP, an early stop, errors in a row).

    Every record gets env.fingerprint and DATAGEN_FORMAT, and a finished record with another fingerprint is made
    again (main only gets here with such records after --new-binary-ok), as is one of another format (made by an
    older data generator: task.record_format). A seed that ends in the same error as on the last start (its cached
    calls and runs replay it in seconds) is stored and counted, but neither adds to the errors in a row nor resets
    them: those are for what this start sees go wrong. The early stop is checked once per data folder, the first time
    size["early_stop"]["after"] seeds are done: it stops the run, or it passed (or early_stop is False, as with
    --no-early-stop) and early_stop.json says so, after which it's never checked again."""
    prog = Progress("tasks", len(seeds), log)
    fp = getattr(env, "fingerprint", None)
    todo, before = [], {}
    for s in seeds:
        rec = store.get(s["seed_id"])
        if rec and rec.get("status") in FINISHED and (fp is None or rec.get("fingerprint") == fp) and \
                task.record_format(rec) == DATAGEN_FORMAT:
            prog.step(s["seed_id"], "done before", skipped=True)
            continue
        if rec and rec.get("status") == "error":
            before[s["seed_id"]] = rec.get("error")
        todo.append(s)
    out = {"done": 0, "skipped": len(seeds) - len(todo), "errors": 0, "stopped": None}
    if not todo:
        return out
    jobs, results = queue.Queue(), queue.Queue()
    for s in todo:
        jobs.put(s)
    workers = max(1, int(size.get("seeds_parallel") or 1))

    def worker():
        try:
            while not stopper.event.is_set():
                try:
                    seed = jobs.get_nowait()
                except queue.Empty:
                    break
                t0 = time.monotonic()
                try:
                    if stopper.requested():
                        break
                    rec = task.run_seed(env, seed)
                except StopRequested:
                    results.put(("stopped", seed, None, 0.0))
                    break
                results.put(("rec", seed, rec, time.monotonic() - t0))
        except BaseException as e:  # noqa: BLE001 - a bug here mustn't leave the main thread waiting for this one
            stopper.stop(f"a seed thread died: {type(e).__name__}: {e}")
        finally:
            results.put(("exit", None, None, 0.0))

    threads = [threading.Thread(target=worker, name=f"seed-{k}", daemon=True) for k in range(workers)]
    for t in threads:
        t.start()
    alive, in_a_row = len(threads), 0
    early = size.get("early_stop")
    early_path = os.path.join(os.path.dirname(os.path.abspath(store.path)), EARLY_FILE)
    if os.path.exists(early_path):
        early = None
    while alive:
        try:
            kind, seed, rec, wall = results.get(timeout=0.5)
        except queue.Empty:
            stopper.requested()  # notices a STOP file while every thread is in a long Blender run
            continue
        if kind == "exit":
            alive -= 1
            continue
        if kind == "stopped":
            continue
        rec["fingerprint"], rec["format"] = fp, DATAGEN_FORMAT
        store.add(rec)
        out["done"] += 1
        note = ""
        if rec["status"] == "error":
            out["errors"] += 1
            if seed["seed_id"] in before and rec.get("error") == before[seed["seed_id"]]:
                note = " (same error as the last start)"
            else:
                in_a_row += 1
                if in_a_row >= ERRORS_IN_A_ROW:
                    stopper.stop(f"{in_a_row} seeds in a row ended in an error (last: {rec['error']})")
        else:
            in_a_row = 0
        prog.step(seed["seed_id"], _summary(rec) + note, wall)
        if early and not stopper.event.is_set():
            n, tried, kept = kept_share(store.all())
            if n >= early["after"]:
                if early_stop and tried and kept / tried < early["min_kept"]:
                    stopper.stop(f"early stop: after {n} seeds only {kept} of {tried} tried steps kept a piece "
                                 f"({100 * kept / tried:.0f}%, under {100 * early['min_kept']:.0f}%)")
                else:
                    write_json(early_path, {"early_stop": "passed" if early_stop else "off", "seeds": n,
                                            "tried": tried, "kept": kept, "min_kept": early["min_kept"],
                                            "t": now_iso()})
                early = None
    if stopper.event.is_set():
        out["stopped"] = stopper.why
        raise StopRequested(stopper.why)
    return out


# ---------------------------------------------------------------- main

def main(argv=None, *, index=None, gate=None) -> int:
    """The command line. index: the EvalIndex the seeds, tasks and build stages use (tools/check_overlap.EvalIndex(8)
    when None); gate: llm.Gate keywords on top of the defaults. Both are for tests."""
    a = parse_args(argv)
    size = sizes.get(a.size)
    data = os.path.abspath(a.data_dir or os.path.join(DATA_ROOT, a.size))
    why = finished_run(data)
    if why and not a.new_binary_ok:
        say(f"error: {why}")  # not into that folder's progress.log either
        return 2
    os.makedirs(data, exist_ok=True)
    log = os.path.join(data, "progress.log")
    warn = scratch_default()
    if warn:
        say(f"warning: {warn}", log)
    makes = [s for s in a.stages if s in ("seeds", "tasks")]
    needs_fp = "tasks" in a.stages or "build" in a.stages  # Chimera's fingerprint: the binary and the Blenders
    if makes:
        for leftover in (stop_path(data), os.path.join(data, STOPPED_FILE)):
            if os.path.exists(leftover):  # a new start carries on
                os.remove(leftover)
    from tools import blender_check, blenders
    need = models_needed(a.stages)
    ollama = None
    if need:
        ollama, why = check_ollama(a.host, need)
        if why:
            say(f"error: Ollama at {a.host}: {why}")
            return 2
    chimera_bin = os.path.abspath(a.chimera)
    ch = None
    from datagen.chimera import Chimera, ChimeraError
    if os.path.isfile(chimera_bin) and os.access(chimera_bin, os.X_OK):
        ch = Chimera(chimera_bin, env={"OLLAMA_HOST": a.host})
        try:
            ch.version()
        except ChimeraError as e:
            if makes or needs_fp:
                say(f"error: {e}")
                return 2
            ch = None
    if (makes or needs_fp) and ch is None:
        say(f"error: no Chimera binary at {chimera_bin} (run_datagen.sh builds one; or give --chimera)")
        return 2
    if needs_fp:
        bad = {v: blenders.check_path(p) for v, p in blenders.VERSIONS.items() if blenders.check_path(p)}
        if bad:
            say("error: " + "; ".join(f"Blender {v}: {why}" for v, why in bad.items()))
            return 2
    stopper = Stopper(data)
    env = None
    errored = 0
    t_all = time.monotonic()
    try:
        idx = index
        if idx is None and any(s in a.stages for s in ("seeds", "tasks", "build")):
            from tools.check_overlap import EvalIndex
            idx = EvalIndex(8)
        fp = store = None
        try:
            if makes:
                env = make_env(a, size, data, stopper, log, chimera_bin, gate, tasks="tasks" in a.stages,
                               eval_index=idx)
                fp = env.fingerprint
            if fp is None and needs_fp:
                fp = fingerprint(ch, names_sheets(ch, blenders.VERSIONS, data, blender_check.scratch_root()))
        except (ValueError, ChimeraError) as e:
            say(f"error: {e}", log)
            return 2
        if "tasks" in a.stages:
            store = Store(os.path.join(data, TASKS_FILE))
            why = changed_requests(data, store, fp)
            if why and not a.new_binary_ok:
                say(f"error: {why}", log)
                return 2
            if why:
                say("Chimera's requests have changed since the last start here; --new-binary-ok: the seeds made "
                    "with the old ones are made again.", log)
            other = other_formats(store.all())
            if other:
                say(f"{len(other)} finished seeds in {TASKS_FILE} were made by another version of the data generator "
                    f"(format {', '.join(map(str, sorted(set(other))))}, {DATAGEN_FORMAT} now): they are made again.",
                    log)
        elif "build" in a.stages and not a.new_binary_ok:  # a build alone would drop them all and publish the rest
            recs = Store(os.path.join(data, TASKS_FILE)).all()
            old = sum(1 for r in recs if r.get("fingerprint") != fp)
            if old:
                say(f"error: {old} seeds in {TASKS_FILE} were made with requests this Chimera doesn't send "
                    f"(fingerprint {fp} now), so the build would drop their examples and replace sft/ with what is "
                    "left. Build with the binary that made them, or give --new-binary-ok to build anyway.", log)
                return 2
            other = other_formats(recs)
            if other:
                say(f"error: {len(other)} finished seeds in {TASKS_FILE} were made by another version of the data "
                    f"generator (format {', '.join(map(str, sorted(set(other))))}, {DATAGEN_FORMAT} now), so the "
                    "build would drop their examples (old_format) and replace sft/ with what is left. Make them again "
                    "(--stages tasks), or give another --data-dir, or --new-binary-ok to build anyway.", log)
                return 2
        run_record(data, size=a.size, stages=a.stages, host=a.host, ollama=ollama,
                   models={"teacher": task.TEACHER, "helper": task.HELPER, "second": task.SECOND,
                           "small": task.SMALL},
                   chimera={"path": chimera_bin, "sha256": ch.sha256() if ch else None,
                            "version": ch.version() if ch else None},
                   fingerprint=fp, blender=dict(blenders.VERSIONS), parallel=a.parallel, limit=a.limit,
                   argv=list(argv or sys.argv[1:]),
                   size_settings={k: v for k, v in size.items() if k not in ("new_calls", "pick", "helper")})
        say(f"Hydra Worker data, size {a.size} ({size.get('hours')}), stages {','.join(a.stages)}, into {data}", log)
        seeds = None
        for st in a.stages:
            t0 = time.monotonic()
            say(f"== {st}", log)
            if st == "seeds":
                seeds = seeds_mod.make_seeds(env.llm, data, size, index=idx, log_path=log)
                got = {"seeds": len(seeds)}
            elif st == "tasks":
                if seeds is None:
                    seeds = read_jsonl(os.path.join(data, seeds_mod.SEEDS_FILE))
                    if not seeds:
                        say("error: no seeds.jsonl here yet; run the seeds stage first", log)
                        return 1
                if a.limit:
                    seeds = seeds[:a.limit]
                got = run_tasks(env, seeds, store, stopper, size, log=log, early_stop=not a.no_early_stop)
                errored = got["errors"]
            elif st == "build":
                got = build_mod.build(data, size, keep_plan_failed=a.keep_plan_failed, index=idx,
                                      keep_untested=a.keep_untested, fingerprint=fp)
                got = {k: got[k] for k in ("train", "valid", "dropped") if k in got}
            else:
                got = report_mod.report(data)
                got = {"report": os.path.join(data, report_mod.REPORT_FILE)}
            say(f"== {st} done in {(time.monotonic() - t0) / 60:.1f} min: {got}", log)
    except (StopRequested, Stopped) as e:
        why = str(e) or stopper.why or "stopped"
        lines = [f"Stopped at {time.strftime('%Y-%m-%d %H:%M')}: {why}.", "",
                 "Run the same command again to carry on where it stopped (finished seeds are skipped, the rest replay "
                 "from the caches)."]
        if why.startswith("early stop"):
            lines += ["", "The early stop is a smoke check that the teacher keeps enough pieces: look at the drop "
                          f"reasons in REPORT.md (`python3 -m datagen.run --size {a.size} --stages report`) "
                          "before carrying on with --no-early-stop (`bash run_datagen.sh --no-early-stop`). It is "
                          f"checked once per data folder: when it passes, or a start carries on past it with "
                          f"--no-early-stop, {EARLY_FILE} says so and later starts don't check it again."]
        write_stopped(data, "Data generation stopped", lines)
        say(f"STOPPED: {why}", log)
        return 3
    except KeyboardInterrupt:
        stopper.stop("Ctrl-C")
        say("\nStopped (Ctrl-C). Run the same command again to carry on where it left off.", log)
        return 130
    except build_mod.OverlapFound as e:
        say(f"error: {e}", log)
        return 1
    except seeds_mod.SeedError as e:
        say(f"error: {e}", log)
        return 2
    finally:
        if env is not None and not stopper.event.is_set():
            env.llm.close()
    if errored:
        say(f"Every stage ran, but {errored} seed(s) ended in an error this start (progress.log says which and why). "
            f"Run the same command again to retry them: finished seeds are skipped. "
            f"See {os.path.join(data, report_mod.REPORT_FILE)}", log)
        return ERRORED
    say(f"All done in {(time.monotonic() - t_all) / 3600:.2f} h. See {os.path.join(data, report_mod.REPORT_FILE)}",
        log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
