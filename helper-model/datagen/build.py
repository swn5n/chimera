"""Stage 7: collect the accepted examples into MLX-LM chat files, drop anything close to the eval
set, split by group (a seed task, or a Head, never straddles train and valid) and write STATS.md."""
from __future__ import annotations

import copy
import json
import os
import re
from collections import Counter, defaultdict

from .common import Store, parse_obj, read_jsonl, rng, stable_int, write_jsonl
from .plans import judge_plan
from .reviews import judged_reviews

from helper import chimera_port as cp
from helper import evalset
from helper.validate import VALIDATORS
from tools.check_overlap import build_index, check_line

VALID_PCT = 5
MAX_TOKENS = 7500   # rough estimate; train with --max-seq-length 8192
DONE_REPEAT = 2     # "done" reviews appear this many times in train (the teacher says "not done" ~4 times as often)

# A plan step whose job is to make a binary file (Chimera's workers return text, so they can't).
_FILE_TERM = re.compile(r"\b(pdf|docx|word (document|doc|file)|xlsx|excel (file|workbook|spreadsheet)|pptx|powerpoint|"
                        r"google (docs?|sheets?|slides)|base64)\b", re.I)
_MAKE_VERB = re.compile(r"\b(generat|creat|export|render|convert|compil|assembl|produc|build|encod|sav|format|packag|fill|"
                        r"populat|lay ?out|typeset|output|finali[sz]|deliver)\w*", re.I)
# Words that mark a step as Blender work.
_BLENDER = re.compile(r"\b(bpy|blender|geometry nodes?|shader|materials?|mesh(es)?|modifiers?|keyframes?|render(s|ing)?|scene|"
                      r"objects?|camera|lights?|lighting|compositor|rig|armature|uvs?|node(s| tree| group)?|\.blend)\b", re.I)


def file_making_steps(plan):
    """Titles of steps that only make a PDF, Word, Excel or PowerPoint file (fine in a coding job: that's a feature)."""
    return [s["title"] for s in plan["steps"] if _FILE_TERM.search(s["title"]) and _MAKE_VERB.search(s["title"])]


def relabel_blender(plan):
    """A Blender job's plan, with the kind Chimera gives bpy work: the plan, and every code step that is Blender work."""
    q = copy.deepcopy(plan)
    q["kind"] = "blender"
    for s in q["steps"]:
        if s["kind"] == "code" and _BLENDER.search(s["title"] + " " + s["instructions"]):
            s["kind"] = "blender"
    return q


def recovered_blender(data_dir):
    """Blender plans the teacher wrote well but labelled `code` (rejected for that reason alone)."""
    from helper.validate import tidy_plan
    seeds = {s["seed_id"]: s for s in read_jsonl(os.path.join(data_dir, "seeds.jsonl"))}
    by = defaultdict(list)
    for r in Store(os.path.join(data_dir, "raw", "plans.jsonl")).all():
        by[r["seed_id"]].append(r)
    out = []
    for sid, rs in sorted(by.items()):
        rs.sort(key=lambda r: r["attempt"])
        last = rs[-1]
        if any(r["accepted"] for r in rs) or last["category"] != "blender" or last["reasons"] != ["kind:code"] or sid not in seeds:
            continue
        obj = parse_obj(last.get("reply"))
        if not obj:
            continue
        ok, _, target, _ = judge_plan("blender", json.dumps(relabel_blender(tidy_plan(obj)), ensure_ascii=False))
        if ok:
            s = seeds[sid]
            out.append(_example("planner", sid, cp.planner_messages(s["text"], s.get("history")), target,
                                source="plan", category="blender", relabelled=True))
    return out


def _example(job, group, messages, target, **meta):
    return {"messages": [dict(m) for m in messages] + [{"role": "assistant", "content": target}],
            "meta": dict(meta, job=job, group=group)}


def collect(data_dir, notes=None):
    notes = notes if notes is not None else {}
    ex, planner = [], []
    for name, source in (("plans.jsonl", "plan"), ("replans.jsonl", "replan")):
        for r in Store(os.path.join(data_dir, "raw", name)).all():
            if r["accepted"]:
                planner.append(_example("planner", r["seed_id"], r["messages"], r["target"], source=source, category=r["category"]))
    rec = recovered_blender(data_dir)
    notes["blender_relabelled"] = len(rec)
    notes["file_steps_dropped"] = []
    for e in planner + rec:
        steps = file_making_steps(json.loads(e["messages"][-1]["content"]))
        if steps and e["meta"]["category"] != "coding":
            notes["file_steps_dropped"].append(steps[0])
            continue
        ex.append(e)
    for j in judged_reviews(data_dir):
        if j["accepted"]:
            ex.append(_example("reviewer", j["seed_id"], cp.review_messages(j["task"], j["result"]), j["target"],
                               source="review", variant=j["variant"], category=j["category"], done=j["target_obj"]["done"]))
    heads = {h["id"]: h for h in read_jsonl(os.path.join(data_dir, "gate_heads.jsonl"))}
    answers = Store(os.path.join(data_dir, "raw", "gate_answers.jsonl"))
    for q in read_jsonl(os.path.join(data_dir, "gate_requests.jsonl")):
        a = answers.get(q["req_id"])
        if a and a["valid"] and a["use"] == q["label"] and q["head_id"] in heads:
            ex.append(_example("gate", "head:" + q["head_id"], cp.gate_messages(heads[q["head_id"]], q["text"]),
                               json.dumps({"use": q["label"]}), source="gate", type=q["type"], use=q["label"],
                               reaches=q["reaches"]))
    return ex


def tokens(ex):
    return sum(len(m["content"].encode("utf-8")) for m in ex["messages"]) / 3.5  # a rough estimate


def split_groups(kept):
    """Valid groups: about VALID_PCT% of each job's groups, at least 2, so every job is measured."""
    by_job = defaultdict(set)
    for e in kept:
        by_job[e["meta"]["job"]].add(e["meta"]["group"])
    valid = set()
    for job, groups in sorted(by_job.items()):
        groups = sorted(groups, key=lambda g: stable_int("split", g))
        n = max(2, round(len(groups) * VALID_PCT / 100)) if len(groups) >= 4 else min(1, len(groups) - 1)
        valid |= set(groups[:n])
    return valid


def run(data_dir, size=None):
    notes = {}
    examples = collect(data_dir, notes)
    es = evalset.load()
    index = build_index(es, 8)
    kept, leaked, broken, too_long = [], [], [], []
    for e in examples:
        if tokens(e) > MAX_TOKENS:
            too_long.append(e)
            continue
        user = "\n".join(m["content"] for m in e["messages"] if m["role"] == "user")
        if check_line(user + "\n" + e["messages"][-1]["content"], es, index, 8, 0.5):
            leaked.append(e)
            continue
        if not VALIDATORS[e["meta"]["job"]](e["messages"][-1]["content"]).valid:  # targets must be strictly valid
            broken.append(e)
            continue
        kept.append(e)
    valid_groups = split_groups(kept)
    train = [e for e in kept if e["meta"]["group"] not in valid_groups]
    valid = [e for e in kept if e["meta"]["group"] in valid_groups]
    extra = [dict(e, meta=dict(e["meta"], repeat=True)) for e in train
             if e["meta"]["job"] == "reviewer" and e["meta"]["done"] for _ in range(DONE_REPEAT - 1)]
    notes["done_repeated"] = len(extra)
    notes["too_long"] = len(too_long)
    train += extra
    rng("shuffle").shuffle(train)
    sft = os.path.join(data_dir, "sft")
    for name, rows in (("train", train), ("valid", valid)):
        write_jsonl(os.path.join(sft, name + ".jsonl"), [{"messages": e["messages"]} for e in rows])
        write_jsonl(os.path.join(sft, name + ".meta.jsonl"), [e["meta"] for e in rows])
    # For the embedding-classifier experiments (gate, and task kind).
    seeds = read_jsonl(os.path.join(data_dir, "seeds.jsonl"))
    write_jsonl(os.path.join(data_dir, "classifier", "kinds.jsonl"),
                [{"text": s["text"], "category": s["category"], "seed_id": s["seed_id"]} for s in seeds])
    answers = Store(os.path.join(data_dir, "raw", "gate_answers.jsonl"))
    heads = {h["id"]: h for h in read_jsonl(os.path.join(data_dir, "gate_heads.jsonl"))}
    gate_rows = []
    for q in read_jsonl(os.path.join(data_dir, "gate_requests.jsonl")):
        a = answers.get(q["req_id"]) or {}
        if q["head_id"] in heads:
            gate_rows.append(dict(q, head=cp.head_description(heads[q["head_id"]]), teacher_valid=a.get("valid"),
                                  teacher_use=a.get("use"), split="valid" if "head:" + q["head_id"] in valid_groups else "train"))
    write_jsonl(os.path.join(data_dir, "classifier", "gate.jsonl"), gate_rows)
    stats = write_stats(data_dir, train, valid, leaked, broken, size, notes)
    return stats


def _pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "–"


def _q(xs, q):
    xs = sorted(xs)
    return int(xs[min(len(xs) - 1, int(q * len(xs)))]) if xs else 0


def write_stats(data_dir, train, valid, leaked, broken, size, notes=None):
    notes = notes or {}
    raw = lambda n: Store(os.path.join(data_dir, "raw", n)).all()  # noqa: E731
    seed_calls, plans, replans = raw("seed_calls.jsonl"), raw("plans.jsonl"), raw("replans.jsonl")
    results, flaws, reviews = raw("results.jsonl"), raw("flaws.jsonl"), raw("reviews.jsonl")
    head_calls, req_calls, answers = raw("gate_head_calls.jsonl"), raw("gate_request_calls.jsonl"), raw("gate_answers.jsonl")
    seeds = read_jsonl(os.path.join(data_dir, "seeds.jsonl"))
    dropped = read_jsonl(os.path.join(data_dir, "raw", "seeds_dropped.jsonl"))
    judged = judged_reviews(data_dir)
    reqs = read_jsonl(os.path.join(data_dir, "gate_requests.jsonl"))
    heads = read_jsonl(os.path.join(data_dir, "gate_heads.jsonl"))
    allx = [e for e in train + valid if not e["meta"].get("repeat")]
    L = ["# Synthetic training data", "",
         "Every request, plan, result, review and gate message here was written by gpt-oss:120b (the teacher) or by "
         "the Qwen workers. The only fixed text in each example is Chimera's own prompt templates (`helper/prompts.py`), "
         "which the helper has to answer. The instructions that steered the teacher are in `datagen/teacher_prompts.py` "
         "and are not part of the data. Nothing was taken from the eval set, and everything was checked against it.", "",
         f"Training files: `sft/train.jsonl` ({len(train)} lines) and `sft/valid.jsonl` ({len(valid)}), MLX-LM chat format "
         "(`{\"messages\": [system, user, assistant]}`); `*.meta.jsonl` line up with them.", "",
         "## Build rules", "",
         f"- Plans with a step that only makes a PDF, Word, Excel or PowerPoint file (outside coding jobs): "
         f"{len(notes.get('file_steps_dropped', []))} dropped, e.g. {', '.join(repr(t) for t in notes.get('file_steps_dropped', [])[:3]) or 'none'}. "
         "Chimera's workers return text, so such steps can't be done.",
         f"- Blender plans the teacher labelled `code` (their only problem): {notes.get('blender_relabelled', 0)} kept with the plan kind "
         "set to `blender` and every code step that is Blender work relabelled too (plain-Python steps stay `code`).",
         f"- Examples over about {MAX_TOKENS} tokens dropped: {notes.get('too_long', 0)}.",
         f"- \"Done\" reviews appear {DONE_REPEAT}x in train ({notes.get('done_repeated', 0)} repeats), since the teacher says "
         "\"not done\" about four times as often. The counts below are unique examples.", ""]
    jobs = Counter(e["meta"]["job"] for e in allx)
    L += ["## Examples", "", "| job | train | valid | detail |", "|---|---|---|---|"]
    for job in ("planner", "reviewer", "gate"):
        tr = sum(1 for e in train if e["meta"]["job"] == job and not e["meta"].get("repeat"))
        va = sum(1 for e in valid if e["meta"]["job"] == job)
        xs = [e["meta"] for e in allx if e["meta"]["job"] == job]
        if job == "planner":
            det = ", ".join(f"{k} {v}" for k, v in sorted(Counter(m["category"] for m in xs).items())) + \
                  f"; re-plans {sum(1 for m in xs if m['source'] == 'replan')}; relabelled {sum(1 for m in xs if m.get('relabelled'))}"
        elif job == "reviewer":
            d = Counter(m["done"] for m in xs)
            det = f"done {d[True]}, not done {d[False]}; " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(m["variant"] for m in xs).items()))
        else:
            u = Counter(m["use"] for m in xs)
            det = f"use {u[True]}, no {u[False]}; reach Chimera's gate {sum(1 for m in xs if m['reaches'])}"
        L.append(f"| {job} | {tr} | {va} | {det} |")
    L += ["", f"Dropped at the end: {len(leaked)} too close to the eval set, {len(broken)} targets not strictly valid.", ""]
    vj = Counter(e["meta"]["job"] for e in valid)
    L += ["Valid split: " + ", ".join(f"{j} {vj[j]}" for j in ("planner", "reviewer", "gate")) + " (whole seeds and Heads, none also in train).", ""]
    toks = defaultdict(list)
    for e in allx:
        toks[e["meta"]["job"]].append(tokens(e))
    L += ["## Length (rough token estimate)", "", "| job | median | 95th percentile | longest |", "|---|---|---|---|"]
    for job, xs in sorted(toks.items()):
        L.append(f"| {job} | {_q(xs, 0.5)} | {_q(xs, 0.95)} | {_q(xs, 1.0)} |")
    longest = max((t for xs in toks.values() for t in xs), default=0)
    seq = next((s for s in (2048, 4096, 8192, 16384) if s >= longest * 1.15), 16384)
    seq = 8192 if longest <= MAX_TOKENS else seq
    L += ["", f"Train with `--max-seq-length {seq}` or more so nothing is cut.", ""]
    # How each stage went.
    pa = {}
    for r in plans:
        pa.setdefault(r["seed_id"], []).append(r)
    plan_ok = sum(1 for rs in pa.values() if any(r["accepted"] for r in rs))
    reasons = Counter(x for rs in pa.values() if not any(r["accepted"] for r in rs) for x in rs[-1]["reasons"])
    first_try = sum(1 for rs in pa.values() if any(r["accepted"] and r["attempt"] == 0 for r in rs))
    rv_why = Counter(j["why"] for j in judged if not j["accepted"])
    variants = Counter(j["variant"] for j in judged)
    ans = {a["key"]: a for a in answers}
    agree_by_type = defaultdict(lambda: [0, 0])
    for q in reqs:
        a = ans.get(q["req_id"])
        if a and a["valid"]:
            agree_by_type[q["type"]][1] += 1
            agree_by_type[q["type"]][0] += a["use"] == q["label"]
    L += ["## Stages", "",
          f"- Seeds: {len(seed_calls)} teacher calls, {len(seeds)} seeds kept, {len(dropped)} dropped "
          f"({', '.join(f'{k} {v}' for k, v in Counter(d['dropped'].split(':')[0] for d in dropped).most_common()) or 'none'}). "
          f"By category: {', '.join(f'{k} {v}' for k, v in sorted(Counter(s['category'] for s in seeds).items()))}.",
          f"- Plans: {plan_ok} of {len(pa)} seeds got an accepted plan ({_pct(plan_ok, len(pa))}; {first_try} on the first try). "
          f"Most common reasons for the rest: {', '.join(f'{k} {v}' for k, v in reasons.most_common(6)) or 'none'}.",
          f"- Re-plans: {sum(1 for r in replans if r['accepted'])} of {len(replans)} accepted.",
          f"- Results: {len(results)} worker answers ({', '.join(f'{k} {v}' for k, v in sorted(Counter(r['worker'] for r in results).items()))}); "
          f"{sum(1 for r in results if r.get('done_reason') == 'length')} hit the length cap; "
          f"{sum(1 for f in flaws if f['ok'])} of {len(flaws)} flawed copies usable.",
          f"- Reviews: {len(judged)} items ({', '.join(f'{k} {v}' for k, v in sorted(variants.items()))}); "
          f"{sum(1 for j in judged if j['accepted'])} accepted; rejected: {', '.join(f'{k} {v}' for k, v in rv_why.most_common()) or 'none'}.",
          f"- Gate: {len(heads)} Heads from {len(head_calls)} calls; {len(reqs)} messages from {len(req_calls)} calls; "
          f"{sum(1 for a in answers if a['valid'])} valid answers; kept {sum(1 for e in allx if e['meta']['job'] == 'gate')}.",
          "", "Teacher's gate answers matching the message type:", "", "| type | should use | matched |", "|---|---|---|"]
    from . import taxonomy as tx
    for t in list(tx.GATE_YES) + list(tx.GATE_NO):
        m, n = agree_by_type.get(t, [0, 0])
        L.append(f"| {t} | {'yes' if t in tx.GATE_YES else 'no'} | {m}/{n} ({_pct(m, n)}) |")
    wall = {"seeds": seed_calls, "plans": plans, "replans": replans, "results": results, "flaws": flaws, "reviews": reviews,
            "gate": head_calls + req_calls + answers}
    def dur(v):
        s = sum(r.get("wall_s") or 0 for r in v)
        return f"{s / 3600:.1f} h" if s >= 3600 else f"{s / 60:.0f} min"
    L += ["", "Model time spent: " + ", ".join(f"{k} {dur(v)}" for k, v in wall.items()), ""]
    with open(os.path.join(data_dir, "STATS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return {"train": len(train), "valid": len(valid), "by_job": dict(jobs), "leaked": len(leaked), "broken": len(broken)}


# ---------------------------------------------------------------- v2 (Oct 28): sft-v2/ and STATS-v2.md

V2_DIR = "sft-v2"
DONE_SHARE = 0.4  # "done" reviews are repeated in train until they're about this share of the reviewer's examples


def collect2(data_dir, notes=None):
    """v1's planner and gate examples, plus the hinted plans; the reviewer's examples all come from the
    check-first reviews (v1's verdicts without a check would teach two different formats)."""
    from .reviews import judged_checked_reviews
    notes = notes if notes is not None else {}
    ex = [e for e in collect(data_dir, notes) if e["meta"]["job"] != "reviewer"]
    added = 0
    for r in Store(os.path.join(data_dir, "raw", "plans2.jsonl")).all():
        if not r["accepted"]:
            continue
        e = _example("planner", r["seed_id"], r["messages"], r["target"], source="plan2", category=r["category"],
                     hinted=bool(r["hints"]), new_seed=r["new_seed"])
        steps = file_making_steps(json.loads(r["target"]))
        if steps and r["category"] != "coding":
            notes["file_steps_dropped"].append(steps[0])
            continue
        ex.append(e)
        added += 1
    notes["plans2"] = added
    for j in judged_checked_reviews(data_dir):
        if j["accepted"]:
            ex.append(_example("reviewer", j["seed_id"], cp.review_messages(j["task"], j["result"]), j["target"],
                               source="review2", variant=j["variant"], category=j["category"], done=j["target_obj"]["done"],
                               flaw_kind=j.get("flaw_kind")))
    return ex


def done_repeat(train):
    """How many times each "done" review appears in train, so they make up about DONE_SHARE (1 to 3)."""
    rv = [e for e in train if e["meta"]["job"] == "reviewer"]
    done = sum(1 for e in rv if e["meta"]["done"])
    if not done:
        return 1
    want = DONE_SHARE / (1 - DONE_SHARE) * (len(rv) - done) / done
    return max(1, min(3, round(want)))


def _target_ok(e):
    t = e["messages"][-1]["content"]
    if e["meta"]["job"] == "reviewer":
        return VALIDATORS["reviewer"](t, require=("check",)).valid
    return VALIDATORS[e["meta"]["job"]](t).valid


def run2(data_dir, size=None):
    """Stage build2: the v2 training files in data/sft-v2/ (v1's data/sft/ is left as it is)."""
    notes = {}
    examples = collect2(data_dir, notes)
    train, valid, leaked, broken = write_split(data_dir, examples, V2_DIR, "shuffle2", notes)
    return write_stats2(data_dir, train, valid, leaked, broken, notes)


def write_split(data_dir, examples, out_dir, shuffle_key, notes):
    """Drop what's too long, close to the eval set or not strictly valid; split by group; repeat "done"
    reviews; write <out_dir>/train.jsonl, valid.jsonl and their .meta.jsonl. Returns train, valid, leaked, broken."""
    es = evalset.load()
    index = build_index(es, 8)
    kept, leaked, broken, too_long = [], [], [], []
    for e in examples:
        if tokens(e) > MAX_TOKENS:
            too_long.append(e)
            continue
        user = "\n".join(m["content"] for m in e["messages"] if m["role"] == "user")
        if check_line(user + "\n" + e["messages"][-1]["content"], es, index, 8, 0.5):
            leaked.append(e)
            continue
        if not _target_ok(e):
            broken.append(e)
            continue
        kept.append(e)
    valid_groups = split_groups(kept)
    train = [e for e in kept if e["meta"]["group"] not in valid_groups]
    valid = [e for e in kept if e["meta"]["group"] in valid_groups]
    rep = done_repeat(train)
    extra = [dict(e, meta=dict(e["meta"], repeat=True)) for e in train
             if e["meta"]["job"] == "reviewer" and e["meta"]["done"] for _ in range(rep - 1)]
    notes.update(done_repeat=rep, done_repeated=len(extra), too_long=len(too_long))
    train += extra
    rng(shuffle_key).shuffle(train)
    sft = os.path.join(data_dir, out_dir)
    for name, rows in (("train", train), ("valid", valid)):
        write_jsonl(os.path.join(sft, name + ".jsonl"), [{"messages": e["messages"]} for e in rows])
        write_jsonl(os.path.join(sft, name + ".meta.jsonl"), [e["meta"] for e in rows])
    return train, valid, leaked, broken


def write_stats2(data_dir, train, valid, leaked, broken, notes):
    from .reviews import judged_checked_reviews
    raw = lambda n: Store(os.path.join(data_dir, "raw", n)).all()  # noqa: E731
    allx = [e for e in train + valid if not e["meta"].get("repeat")]
    judged = judged_checked_reviews(data_dir)
    plans2, answers, flaws2, reviews2 = raw("plans2.jsonl"), raw("answers.jsonl"), raw("flaws2.jsonl"), raw("reviews2.jsonl")
    seeds2 = read_jsonl(os.path.join(data_dir, "seeds2.jsonl"))
    L = ["# Synthetic training data, v2", "",
         "What changed from v1 (`STATS.md`, `sft/`): every reviewer example now starts with a `check` of each requirement "
         "before the verdict (written by the teacher when asked for one; the example's request is Chimera's exact one, "
         "so the helper learns to check first unprompted, and Chimera ignores the extra field); more review material "
         "(the teacher's own answers, and a second round of deliberately flawed copies, mostly flaws you only see by "
         "checking); and plans for tasks v1's teacher plans got wrong in a way a one-line hint fixes, plus batch jobs "
         "with 8 to 15 items. As in v1, everything was written by gpt-oss:120b or the Qwen workers, never by Claude, "
         "and checked against the eval set.", "",
         f"Training files: `{V2_DIR}/train.jsonl` ({len(train)} lines) and `{V2_DIR}/valid.jsonl` ({len(valid)}).", "",
         "## Examples", "", "| job | train | valid | detail |", "|---|---|---|---|"]
    for job in ("planner", "reviewer", "gate"):
        tr = sum(1 for e in train if e["meta"]["job"] == job and not e["meta"].get("repeat"))
        va = sum(1 for e in valid if e["meta"]["job"] == job)
        xs = [e["meta"] for e in allx if e["meta"]["job"] == job]
        if job == "planner":
            det = ", ".join(f"{k} {v}" for k, v in sorted(Counter(m["category"] for m in xs).items())) + \
                  f"; hinted {sum(1 for m in xs if m.get('hinted'))}; long batches {sum(1 for m in xs if m.get('new_seed'))}" + \
                  f"; re-plans {sum(1 for m in xs if m['source'] == 'replan')}"
        elif job == "reviewer":
            d = Counter(m["done"] for m in xs)
            det = f"done {d[True]}, not done {d[False]}; " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(m["variant"] for m in xs).items()))
        else:
            u = Counter(m["use"] for m in xs)
            det = f"use {u[True]}, no {u[False]}"
        L.append(f"| {job} | {tr} | {va} | {det} |")
    rv_train = [e for e in train if e["meta"]["job"] == "reviewer"]
    L += ["", f"\"Done\" reviews appear {notes.get('done_repeat', 1)}x in train ({notes.get('done_repeated', 0)} repeats), "
          f"so they are {_pct(sum(1 for e in rv_train if e['meta']['done']), len(rv_train))} of the reviewer's lines. "
          f"Dropped at the end: {len(leaked)} too close to the eval set, {len(broken)} targets not strictly valid, "
          f"{notes.get('too_long', 0)} over about {MAX_TOKENS} tokens.", ""]
    checks = [len(j["target_obj"]["check"]) for j in judged if j["accepted"]]
    rv_why = Counter(j["why"] for j in judged if not j["accepted"])
    acc_by = defaultdict(lambda: [0, 0])
    for j in judged:
        acc_by[j["variant"]][1] += 1
        acc_by[j["variant"]][0] += j["accepted"]
    done_by = Counter(j["variant"] for j in judged if j["accepted"] and j["target_obj"]["done"])
    p2 = {}
    for r in plans2:
        p2.setdefault(r["seed_id"], []).append(r)
    p2_ok = sum(1 for rs in p2.values() if any(r["accepted"] for r in rs))
    p2_new = sum(1 for rs in p2.values() if rs[0]["new_seed"])
    p2_new_ok = sum(1 for rs in p2.values() if rs[0]["new_seed"] and any(r["accepted"] for r in rs))
    L += ["## Stages", "",
          f"- Long-batch seeds: {len(seeds2)} kept.",
          f"- Hinted plans: {p2_ok} of {len(p2)} seeds got an accepted plan ({p2_new_ok} of {p2_new} long-batch seeds); "
          f"{notes.get('plans2', 0)} kept after the build rules.",
          f"- The teacher's own answers: {len(answers)} ({sum(1 for a in answers if a.get('done_reason') == 'length')} hit the length cap).",
          f"- Second-round flawed copies: {sum(1 for f in flaws2 if f['ok'])} of {len(flaws2)} usable "
          f"({', '.join(f'{k[:40]} {v}' for k, v in Counter(f['flaw_kind'] for f in flaws2 if f['ok']).most_common())}).",
          f"- Check-first reviews: {len(judged)} items, {sum(1 for j in judged if j['accepted'])} accepted; rejected: "
          f"{', '.join(f'{k} {v}' for k, v in rv_why.most_common()) or 'none'}. Checks: median {_q(checks, 0.5)} characters, "
          f"95th percentile {_q(checks, 0.95)}.", "",
          "| review material | accepted | of which done |", "|---|---|---|"]
    for v, (a, n) in sorted(acc_by.items()):
        L.append(f"| {v} | {a}/{n} ({_pct(a, n)}) | {done_by.get(v, 0)} |")
    wall = {"seeds2": raw("seed_calls2.jsonl"), "plans2": plans2, "answers": answers, "flaws2": flaws2, "reviews2": reviews2}
    def dur(v):
        s = sum(r.get("wall_s") or 0 for r in v)
        return f"{s / 3600:.1f} h" if s >= 3600 else f"{s / 60:.0f} min"
    L += ["", "Model time spent: " + ", ".join(f"{k} {dur(v)}" for k, v in wall.items()), ""]
    with open(os.path.join(data_dir, "STATS-v2.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    jobs = Counter(e["meta"]["job"] for e in allx)
    return {"train": len(train), "valid": len(valid), "by_job": dict(jobs), "leaked": len(leaked), "broken": len(broken),
            "done_repeat": notes.get("done_repeat")}
