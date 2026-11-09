"""The seed stage: the requests every training task starts from (DESIGN.md, "topics.py and seeds.py").

Seeds come from two sources:
- new: the teacher (gpt-oss:120b) writes k requests per call from topics.py's labels. Each call's record goes to
  seed_calls.jsonl under f"{target}-{i:04d}", with the cache key of the request it answers, so a resumed run only
  asks the calls it has no answer for, or whose request has changed since (a changed instruction or k).
- helper: the helper's teacher seeds (helper-model/data/seeds.jsonl, seeds2.jsonl and seeds3.jsonl, read only),
  by their category. Their ids are kept, since task.py looks up the helper's plans by them.

A seed of either source is kept only if it is 15 to 8,000 characters long, has no eval overlap
(tools/check_overlap.EvalIndex at 0.3, which also catches the canaries and the test-fixture mark), doesn't name one
of the worker eval's scenarios (eval_titles(), as a phrase), and isn't a repeat or near repeat (5-word shingles,
Jaccard 0.5) of a seed kept before it. The helper's seeds are offered first, so which of them are kept never depends
on how many new calls a size makes, and new seeds follow in call order, so a longer run keeps what a shorter one
kept. Each size then picks its share of each category with rng("pick", size, name) (name: the category, or
helper_<category> for the helper's), spread over the calls the seeds came from, so one call's topic doesn't fill a
category.

Writes seeds.jsonl (the seeds the size uses), seeds_dropped.jsonl (every dropped seed with its reason) and
seeds_stats.json (counts for the report), all rewritten on each run.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import threading
from collections import Counter

import evalset
from datagen import topics
from datagen.common import (Progress, StopRequested, Store, check_stop, log_line, now_iso, read_jsonl, rng,
                            write_json, write_jsonl)

TEACHER = "gpt-oss:120b"
NUM_PREDICT = 7000  # the helper's seed calls' limit: k long requests plus the teacher's reasoning
MIN_CHARS, MAX_CHARS = 15, 8000
SHINGLE_N = 5
NEAR = 0.5  # Jaccard of 5-word shingles at which a seed repeats one kept before it
EVAL_THRESHOLD = 0.3  # share of an eval text's 8-grams (EvalIndex.check)

HELPER_DATA = os.path.join(evalset.HELPER, "data")
HELPER_FILES = tuple(os.path.join(HELPER_DATA, n) for n in ("seeds.jsonl", "seeds2.jsonl", "seeds3.jsonl"))
HELPER_CATEGORIES = ("blender", "coding", "research_draft", "planning", "batch", "small_task")

CALLS_FILE = "seed_calls.jsonl"
SEEDS_FILE = "seeds.jsonl"
DROPPED_FILE = "seeds_dropped.jsonl"
STATS_FILE = "seeds_stats.json"

# The order the picked seeds come out in, one of each in turn, so a run limited to its first seeds still gets a mix.
PICK_ORDER = topics.TARGETS + tuple("helper_" + c for c in HELPER_CATEGORIES)
# Which of the eval's plan kinds each target's instruction lists as subjects to stay away from.
AVOID_KINDS = {"blender": ("blender",), "python": ("code", "general"), "mixed": ("blender",)}
REASONS = ("length", "eval_overlap", "eval_title", "repeat", "near_repeat")

_WORDS = re.compile(r"\w+", re.U)


class SeedError(RuntimeError):
    """Most of the teacher's seed calls failed (Ollama down, say): the records so far are kept for a rerun."""


def words(text):
    return _WORDS.findall((text or "").lower())


def shingles(text, n=SHINGLE_N):
    """The text's n-word shingles (helper-model's seeds.shingles): a text shorter than n words is one shingle."""
    w = words(text)
    return {tuple(w[i:i + n]) for i in range(max(1, len(w) - n + 1))}


# ---------------------------------------------------------------- the eval's scenarios

def eval_titles(kinds=None, *, multi_word=True, eval_dir=evalset.EVAL_DIR):
    """The titles of every plan in the worker eval (eval/*.json and eval/frozen/), lower-cased, distinct, sorted.
    kinds: only plans of these kinds (blender, code, writing, research, general). multi_word: only titles of two
    words or more, the ones matched as phrases (a one-word title such as "windmill" would drop every seed that
    names one). Read at run time, so the eval's text is never copied into code."""
    out = set()

    def walk(v):
        if isinstance(v, dict):
            if evalset._is_plan(v) and (kinds is None or v.get("kind") in kinds):
                t = " ".join(v["title"].split()).lower()
                if t and (len(words(t)) >= 2 or not multi_word):
                    out.add(t)
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    for name in evalset.json_files(eval_dir):
        with open(os.path.join(eval_dir, name), encoding="utf-8") as f:
            walk(json.load(f))
    return sorted(out)


class TitleMatch:
    """Finds an eval title named in a text as a phrase: the title's words, in order, between word boundaries."""

    def __init__(self, titles):
        self.phrases = [(" " + " ".join(words(t)) + " ", t) for t in titles if len(words(t)) >= 2]

    def find(self, text):
        """The first title the text names, or None."""
        padded = " " + " ".join(words(text)) + " "
        return next((t for p, t in self.phrases if p in padded), None)


# ---------------------------------------------------------------- the teacher's calls

def build_call(target, i, k, avoid=()):
    """(messages, params) of seed call i of a target: topics.py's instruction with its topic, style and length."""
    topic, area = topics.topic_for(target, i)
    style, length = topics.style_for(target, i), topics.length_for(target, i)
    user = topics.seed_user(target, topic, style, length, k, avoid)
    messages = [{"role": "system", "content": topics.SEED_SYSTEM}, {"role": "user", "content": user}]
    return messages, {"target": target, "index": i, "topic": topic, "area": area, "style": style,
                      "length": length, "k": k}


def plan_calls(size, *, eval_dir=evalset.EVAL_DIR):
    """Every seed call a size makes: [{"key", "target", "index", "messages", "params"}], taking the targets in turn
    (blender 0, python 0, mixed 0, blender 1, ...) so an early stop leaves some of each."""
    new = size.get("new_calls") or {}
    unknown = sorted(set(new) - set(topics.TARGETS))
    if unknown:
        raise ValueError(f"size {size.get('name')!r}: unknown seed targets {unknown} (one of {topics.TARGETS})")
    per = {}
    for target in topics.TARGETS:
        if target not in new:
            continue
        calls, k = new[target]
        avoid = eval_titles(AVOID_KINDS[target], multi_word=False, eval_dir=eval_dir)
        per[target] = []
        for i in range(int(calls)):
            messages, params = build_call(target, i, int(k), avoid)
            per[target].append({"key": f"{target}-{i:04d}", "target": target, "index": i, "messages": messages,
                                "params": params})
    out, depth = [], max((len(v) for v in per.values()), default=0)
    for d in range(depth):
        out += [v[d] for v in per.values() if d < len(v)]
    return out


def _json_value(text):
    """The JSON object (or list) in a reply: the whole of it, inside a code fence, or between its outer braces."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0].strip()
    cands = [t]
    for a, b in (("{", "}"), ("[", "]")):
        if a in t and b in t:
            cands.append(t[t.find(a):t.rfind(b) + 1])
    for c in cands:
        try:
            v = json.loads(c)
        except ValueError:
            continue
        if isinstance(v, (dict, list)):
            return v
    return None


def parse_tasks(content):
    """The requests in a teacher reply, stripped, or None when the reply can't be read. Lenient the way the
    helper's reader was: {"tasks": [...]}, else the first list of strings or objects in the object, else a bare
    list; an item may be an object with its text under task, text, request, message or prompt. Length isn't judged
    here: a request that is too short or too long is dropped later, with its reason."""
    v = _json_value(content)
    if isinstance(v, dict):
        items = v.get("tasks")
        if not isinstance(items, list):
            items = next((x for x in v.values() if isinstance(x, list) and x
                          and all(isinstance(y, (str, dict)) for y in x)), None)
        v = items
    if not isinstance(v, list):
        return None
    out = []
    for it in v:
        if isinstance(it, dict):
            it = next((it[k] for k in ("task", "text", "request", "message", "prompt") if isinstance(it.get(k), str)),
                      None)
        if isinstance(it, str) and it.strip():
            out.append(it.strip())
    return out


def _options():
    return {"num_predict": NUM_PREDICT}  # temperature left to the model, as the plan says


def request_key(llm, call):
    """The cache key of a call's first try: what a seed_calls.jsonl record must have answered to be reused."""
    return llm.request(TEACHER, call["messages"], options=_options(), fmt="json", sample=0)[0]


def ask(llm, call, data_dir):
    """Make one seed call; returns its seed_calls.jsonl record. A reply with no readable tasks (bad JSON, or a
    runaway) is asked once more as sample 1. A failed call stops there; its record has the error and a rerun asks
    again (the LLM doesn't cache failures)."""
    tries, tasks, last = [], None, None
    for sample in (0, 1):
        check_stop(data_dir)
        last = llm.call(TEACHER, call["messages"], purpose="seed", options=_options(), fmt="json", sample=sample)
        failed = last.error is not None and not last.runaway
        tasks = None if last.error is not None else parse_tasks(last.content)
        tries.append({"sample": sample, "key": last.key, "done_reason": last.done_reason, "error": last.error,
                      "wall_s": round(last.wall_s or 0.0, 2), "cached": last.cached,
                      "tasks": None if tasks is None else len(tasks)})
        if failed or tasks:
            break
    error = last.error if last.error is not None and not last.runaway else None
    return {"key": call["key"], "target": call["target"], "index": call["index"], "params": call["params"],
            "model": TEACHER, "request_key": tries[0]["key"], "call_key": last.key, "items": tasks or [],
            "unreadable": error is None and not tasks, "error": error, "tries": tries,
            "wall_s": round(sum(t["wall_s"] for t in tries), 2),
            "reply": None if tasks else (last.content or "")[:4000], "t": now_iso()}


def run_calls(llm, store, calls, data_dir, log_path=None):
    """Make every call that store has no good record for, in threads when the gate allows parallel calls.
    Returns (made, failed). StopRequested (STOP, through check_stop or the gate) ends the stage after the calls
    in flight; so does Ctrl-C, which leaves at once and starts no call that was waiting (the ones in flight end on
    their own)."""
    prog = Progress("seeds", len(calls), log_path)
    todo = []
    for c in calls:
        rec = store.get(c["key"])
        if rec and rec.get("error") is None and rec.get("request_key") == request_key(llm, c):
            prog.step(c["key"], "done before", skipped=True)
        else:
            todo.append(c)
    if not todo:
        return 0, 0
    made = failed = 0
    halt = threading.Event()  # set on the first exception or Ctrl-C: a call taken off the queue doesn't start

    def one(c):
        if halt.is_set():
            raise StopRequested("the seed calls were stopped")
        rec = ask(llm, c, data_dir)
        store.add(rec)
        status = f"{len(rec['items'])}/{c['params']['k']} tasks"
        if rec["error"]:
            status += f" ERROR {rec['error']}"
        elif rec["unreadable"]:
            status += " unreadable"
        prog.step(c["key"], status, rec["wall_s"])
        return rec

    workers = max(1, int(getattr(getattr(llm, "gate", None), "parallel", 1) or 1))
    if workers == 1:
        for c in todo:
            rec = one(c)
            made += 1
            failed += rec["error"] is not None
    else:
        first = None
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        futs = []
        try:
            futs = [ex.submit(one, c) for c in todo]
            for f in concurrent.futures.as_completed(futs):
                try:
                    rec = f.result()
                except Exception as e:  # noqa: BLE001 - re-raised below, once the calls in flight are done
                    if first is None:
                        first = e
                        halt.set()
                        for g in futs:
                            g.cancel()
                    continue
                made += 1
                failed += rec["error"] is not None
        except BaseException:  # Ctrl-C: don't wait for the calls in flight (a `with` block would run every call)
            halt.set()
            for g in futs:
                g.cancel()
            ex.shutdown(wait=False, cancel_futures=True)
            raise
        ex.shutdown(wait=True)
        if first is not None:
            raise first
    return made, failed


# ---------------------------------------------------------------- the seeds

def new_seeds(records):
    """The seeds in seed_calls.jsonl records, in call order (targets in topics.TARGETS order, then call index)."""
    out = []
    for rec in sorted(records, key=lambda r: (topics.TARGETS.index(r["target"]), r["index"])):
        for j, text in enumerate(rec.get("items") or []):
            sid = f"n-{rec['target']}-{rec['index']:04d}-{j:02d}"
            out.append({"key": sid, "seed_id": sid, "source": "new", "category": rec["target"], "text": text,
                        "history": None, "params": dict(rec["params"]), "call_key": rec.get("call_key")})
    return out


def helper_seeds(paths=HELPER_FILES):
    """The helper's seeds from its files, in file and line order, as seeds of source "helper" (ids, categories,
    history and the helper's params kept; params also say which file and which of its calls each came from)."""
    out = []
    for path in paths:
        name = os.path.basename(path)
        for r in read_jsonl(path):
            if not isinstance(r.get("text"), str) or not r.get("seed_id") or not r.get("category"):
                continue
            params = dict(r.get("params") or {}, file=name)
            params["from"] = r.get("from")
            out.append({"key": r["seed_id"], "seed_id": r["seed_id"], "source": "helper", "category": r["category"],
                        "text": r["text"], "history": r.get("history"), "params": params, "call_key": None})
    return out


def pick_name(seed):
    """The name a size's pick uses for the seed's category: blender, python and mixed for new seeds,
    helper_<category> for the helper's."""
    return seed["category"] if seed["source"] == "new" else "helper_" + seed["category"]


def _full(seed):
    """The seed's text with its history (a follow-up's earlier turns), for the eval checks."""
    hist = [m.get("content") for m in seed.get("history") or [] if isinstance(m, dict)]
    return "\n".join([seed["text"]] + [h for h in hist if isinstance(h, str)])


class Pool:
    """The kept seeds so far, and why each other one was dropped. offer() judges one seed against the eval sets and
    every seed kept before it."""

    def __init__(self, index, titles):
        self.index, self.titles = index, TitleMatch(titles)
        self.kept, self.dropped = [], []
        self._exact = {}  # normalised text -> seed id
        self._inv = {}  # shingle -> [kept position]
        self._sizes = []

    def offer(self, seed):
        """Keep the seed, or drop it with its reason; returns (reason, detail), (None, None) when kept."""
        reason, detail, sh = self._judge(seed)
        if reason:
            self.dropped.append(dict(seed, reason=reason, detail=detail))
            return reason, detail
        k = len(self.kept)
        self.kept.append(seed)
        self._exact[" ".join(words(seed["text"]))] = seed["seed_id"]
        self._sizes.append(len(sh))
        for s in sh:
            self._inv.setdefault(s, []).append(k)
        return None, None

    def _judge(self, seed):
        text = seed["text"]
        if not MIN_CHARS <= len(text) <= MAX_CHARS:
            return "length", f"{len(text)} characters", None
        full = _full(seed)
        hits = self.index.check(full, EVAL_THRESHOLD)
        if hits:
            return "eval_overlap", [h[0] for h in hits], None
        title = self.titles.find(full)
        if title:
            return "eval_title", title, None
        same = self._exact.get(" ".join(words(text)))
        if same:
            return "repeat", same, None
        sh = shingles(text)
        near = self._near(sh)
        if near:
            return "near_repeat", near, None
        return None, None, sh

    def _near(self, sh):
        shared = Counter()
        for s in sh:
            for k in self._inv.get(s, ()):
                shared[k] += 1
        best = None
        for k, c in shared.items():
            j = c / (len(sh) + self._sizes[k] - c)
            if j >= NEAR and (best is None or j > best[1]):
                best = (self.kept[k]["seed_id"], round(j, 3))
        return None if best is None else {"seed_id": best[0], "jaccard": best[1]}


def wanted(size, name):
    """How many seeds of a pick name a size uses: size["pick"][name]; None (or "all") means every kept seed, and a
    name the size doesn't list means none. size["helper"][category] is read for a helper name pick doesn't list."""
    pick = size.get("pick") or {}
    if name in pick:
        v = pick[name]
    elif name.startswith("helper_") and name[len("helper_"):] in (size.get("helper") or {}):
        v = size["helper"][name[len("helper_"):]]
    else:
        return 0
    return None if v is None or v == "all" else max(0, int(v))


def pick(kept, n, size_name, name):
    """n seeds (None: all) of one pick name, chosen by rng("pick", size_name, name): the calls the seeds came from
    are put in a shuffled order and so are each call's seeds, then one seed is taken from each call in turn."""
    groups = {}
    for s in kept:
        groups.setdefault(s["seed_id"].rsplit("-", 1)[0], []).append(s)
    r = rng("pick", size_name, name)
    order = sorted(groups)
    r.shuffle(order)
    for g in order:
        r.shuffle(groups[g])
    spread, depth = [], max((len(v) for v in groups.values()), default=0)
    for d in range(depth):
        spread += [groups[g][d] for g in order if d < len(groups[g])]
    return spread if n is None else spread[:n]


def choose(kept, size):
    """(the size's seeds, interleaved one pick name at a time in PICK_ORDER, then {name: (wanted, picked, kept)})."""
    by = {}
    for s in kept:
        by.setdefault(pick_name(s), []).append(s)
    names = list(PICK_ORDER) + sorted((set(size.get("pick") or {}) | set(by)) - set(PICK_ORDER))
    lists, counts = {}, {}
    for name in names:
        n = wanted(size, name)
        lists[name] = pick(by.get(name, []), n, size.get("name", ""), name) if n != 0 else []
        if n != 0 or name in by:
            counts[name] = {"wanted": n, "picked": len(lists[name]), "kept": len(by.get(name, []))}
    out, depth = [], max((len(v) for v in lists.values()), default=0)
    for d in range(depth):
        out += [lists[nm][d] for nm in names if d < len(lists[nm])]
    return out, counts


def make_seeds(llm, data_dir, size, *, index=None, eval_dir=evalset.EVAL_DIR, helper_files=None, log_path=None):
    """The seed stage for a size: make the teacher calls it still needs, then judge every seed and pick the size's
    share. Returns the seeds it uses (also written to seeds.jsonl), each {"key", "seed_id", "source", "category",
    "text", "history", "params", "call_key"} (call_key: the cache key of the teacher reply a new seed came from).

    size: {"name", "new_calls": {target: (calls, k)}, "pick": {name: n | None}} with pick names from pick_name().
    index: an EvalIndex (built here by default). helper_files: the helper's seed files (HELPER_FILES by default);
    one that is missing is an error only when the size picks helper seeds. llm may be None for a size that makes
    no new calls. Raises StopRequested on STOP and SeedError when more than half of the size's calls (all of them,
    not only this start's) have no answer; fewer failed calls are logged and the stage goes on with the seeds there
    are (the next start asks them again)."""
    log_path = log_path or os.path.join(data_dir, "progress.log")
    calls = plan_calls(size, eval_dir=eval_dir)
    if calls and llm is None:
        raise ValueError("make_seeds: this size makes teacher calls, but no llm was given")
    store = Store(os.path.join(data_dir, CALLS_FILE))
    made, failed = run_calls(llm, store, calls, data_dir, log_path) if calls else (0, 0)
    answered = sum(1 for c in calls if (r := store.get(c["key"])) and r.get("error") is None)
    failed_keys = [c["key"] for c in calls if (store.get(c["key"]) or {}).get("error") is not None]
    if failed_keys and answered * 2 < len(calls):
        last = next(r["error"] for r in reversed(store.all()) if r.get("error"))
        raise SeedError(f"seeds: {len(failed_keys)} of {len(calls)} teacher calls failed (last: {last}); rerun to ask "
                        "them again")
    if failed_keys:
        log_line(log_path, f"seeds: {len(failed_keys)} of {len(calls)} teacher calls failed "
                           f"({', '.join(failed_keys)}); going on with the seeds there are (the next start asks them "
                           "again)")

    paths = HELPER_FILES if helper_files is None else tuple(helper_files)
    missing = [p for p in paths if not os.path.exists(p)]
    if missing and any(wanted(size, "helper_" + c) != 0 for c in HELPER_CATEGORIES):
        raise FileNotFoundError("the helper's seed files are missing: " + ", ".join(missing))
    if index is None:
        from tools.check_overlap import EvalIndex
        index = EvalIndex(8, worker_dir=eval_dir)
    pool = Pool(index, eval_titles(eval_dir=eval_dir))
    helper = helper_seeds([p for p in paths if p not in missing])
    for s in helper:
        pool.offer(s)
    records = [r for r in (store.get(c["key"]) for c in calls) if r]
    for s in new_seeds(records):
        pool.offer(s)
    chosen, counts = choose(pool.kept, size)

    write_jsonl(os.path.join(data_dir, SEEDS_FILE), chosen)
    write_jsonl(os.path.join(data_dir, DROPPED_FILE), pool.dropped)
    stats = _stats(size, calls, store, made, failed, failed_keys, paths, missing, helper, pool, counts, chosen)
    write_json(os.path.join(data_dir, STATS_FILE), stats)
    drops = ", ".join(f"{r} {n}" for r, n in stats["dropped"].items() if n) or "none"
    short = [f"{nm} {c['picked']}/{c['wanted']}" for nm, c in counts.items()
             if c["wanted"] is not None and c["picked"] < c["wanted"]]
    log_line(log_path, f"seeds: {len(chosen)} seeds for {size.get('name')}; kept {len(pool.kept)} of "
                       f"{stats['offered']}, dropped: {drops}" + (f"; short: {', '.join(short)}" if short else ""))
    return chosen


def _stats(size, calls, store, made, failed, failed_keys, paths, missing, helper, pool, counts, chosen):
    """seeds_stats.json: the calls per target (and the keys of those with no answer), the helper's seeds read, drops
    by reason (and by pick name), and the picks against what the size wanted."""
    per_target = {}
    for c in calls:
        rec = store.get(c["key"]) or {}
        t = per_target.setdefault(c["target"], {"calls": 0, "k": c["params"]["k"], "answered": 0, "errors": 0,
                                                "unreadable": 0, "retried": 0, "tasks": 0, "wall_s": 0.0})
        t["calls"] += 1
        t["answered"] += bool(rec) and rec.get("error") is None
        t["errors"] += rec.get("error") is not None
        t["unreadable"] += bool(rec.get("unreadable"))
        t["retried"] += len(rec.get("tries") or []) > 1
        t["tasks"] += len(rec.get("items") or [])
        t["wall_s"] = round(t["wall_s"] + (rec.get("wall_s") or 0.0), 2)
    dropped = Counter(d["reason"] for d in pool.dropped)
    dropped_by = {}
    for d in pool.dropped:
        by = dropped_by.setdefault(pick_name(d), {})
        by[d["reason"]] = by.get(d["reason"], 0) + 1
    return {"size": size.get("name"), "t": now_iso(), "calls": per_target, "made_now": made, "failed_now": failed,
            "failed_calls": failed_keys,
            "helper": {"files": [os.path.basename(p) for p in paths], "missing": missing, "read": len(helper),
                       "by_category": dict(Counter(s["category"] for s in helper))},
            "offered": len(pool.kept) + len(pool.dropped), "kept": len(pool.kept),
            "dropped": {r: dropped.get(r, 0) for r in REASONS}, "dropped_by": dropped_by, "pick": counts,
            "seeds": len(chosen)}
