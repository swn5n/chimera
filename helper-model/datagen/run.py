#!/usr/bin/env python3
"""Generate synthetic training data for the helper model with the teacher (gpt-oss:120b) and the
Qwen workers, through Chimera's exact prompts.

    python3 -m datagen.run --size smoke --data-dir data/smoke     # every stage on a few items (~15 min)
    python3 -m datagen.run --size night                            # the overnight run (~7-8 h) into data/
    python3 -m datagen.run --size night --stages build             # rebuild the training files only
    python3 -m datagen.run --size night --stages v2                # v2's stages, on top of a finished v1 run
    python3 -m datagen.run --size night --stages v3                # v3's stages, on top of v1 and v2

Every stage is resumable: run the same command again and it continues where it stopped.
Stages: seeds, plans, results, reviews, replans, gate, build; v2 adds seeds2, plans2, answers, flaws2,
reviews2, build2 (into data/sft-v2/ and STATS-v2.md); v3 adds seeds3, plans3, answers3, flaws3, reviews3,
build3 (into data/sft-v3/ and STATS-v3.md). See datagen/README.md.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from datagen import build, gate, plans, results, reviews, seeds, v3  # noqa: E402
from datagen.common import TEACHER, WORKERS, Models, Stopped  # noqa: E402
from datagen.sizes import SIZES  # noqa: E402
from helper import evalset, prompts  # noqa: E402
from runner.ollama_client import OllamaError  # noqa: E402

STAGES = ("seeds", "plans", "results", "reviews", "replans", "gate", "build")
V2_STAGES = ("seeds2", "plans2", "answers", "flaws2", "reviews2", "build2")
V3_STAGES = ("seeds3", "plans3", "answers3", "flaws3", "reviews3", "build3")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", choices=sorted(SIZES), default="smoke")
    ap.add_argument("--data-dir", default=os.path.join(HERE, "data"))
    ap.add_argument("--stages", default=",".join(STAGES), help="comma-separated, or v2 / v3 for all of that version's stages")
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "127.0.0.1:11434"))
    ap.add_argument("--teacher", default=TEACHER)
    ap.add_argument("--workers", default=",".join(WORKERS))
    ap.add_argument("--effort", choices=["low", "medium", "high"], help="the teacher's reasoning effort (default: its own)")
    ap.add_argument("--timeout", type=float, default=300.0, help="seconds per model call")
    a = ap.parse_args(argv)
    stages = [s.strip() for s in a.stages.split(",") if s.strip()]
    stages = [x for s in stages for x in {"v2": V2_STAGES, "v3": V3_STAGES}.get(s, (s,))]
    bad = [s for s in stages if s not in STAGES + V2_STAGES + V3_STAGES]
    if bad:
        ap.error(f"unknown stage(s) {bad}; pick from {STAGES + V2_STAGES + V3_STAGES}, v2 or v3")
    if any(s in V2_STAGES[:-1] + V3_STAGES[:-1] for s in stages) and not os.path.exists(os.path.join(os.path.abspath(a.data_dir), "seeds.jsonl")):
        ap.error("v2's and v3's stages build on a finished v1 run; there's no seeds.jsonl in " + a.data_dir)
    size = SIZES[a.size]
    workers = tuple(w.strip() for w in a.workers.split(",") if w.strip())
    data = os.path.abspath(a.data_dir)
    os.makedirs(os.path.join(data, "raw"), exist_ok=True)
    log = os.path.join(data, "progress.log")
    stop = os.path.join(data, "STOPPED.md")
    if os.path.exists(stop):
        os.remove(stop)
    models = Models(a.host, a.timeout, a.effort)
    if any(s not in ("build", "build2", "build3") for s in stages):
        try:
            have = {m.get("name") for m in models.client.tags()} | {m.get("model") for m in models.client.tags()}
        except OllamaError as e:
            print("error:", e, file=sys.stderr)
            return 2
        need = [a.teacher] + (list(workers) if any(s in ("results",) for s in stages) else [])
        missing = [m for m in need if m not in have and (m + ":latest") not in have]
        missing = [m for m in missing if not _shows(models, m)]
        if missing:
            print("error: not installed: " + ", ".join(missing) + " (ollama pull " + " ".join(missing) + ")", file=sys.stderr)
            return 2
    run_info = {"size": a.size, "teacher": a.teacher, "workers": list(workers), "effort": a.effort or "model default",
                "stages": stages, "eval_version": evalset.load().version, "chimera_prompts": prompts.CHIMERA_VERSION,
                "started": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    gen = "3" if any(s in V3_STAGES for s in stages) else ("2" if any(s in V2_STAGES for s in stages) else "")
    run_path = os.path.join(data, f"RUN-v{gen}.json" if gen else "RUN.json")  # each version keeps its own record
    if stages in (["build"], ["build2"], ["build3"]) and os.path.exists(run_path):  # a rebuild keeps the generation run's record
        with open(run_path, encoding="utf-8") as f:
            prev = json.load(f)
        prev.setdefault("rebuilt", []).append(run_info["started"])
        run_info = prev
    with open(run_path, "w", encoding="utf-8") as f:
        json.dump(run_info, f, indent=2)
    print(f"Generating {a.size} data{f' (v{gen})' if gen else ''} ({size['hours' + gen]}) into {data}", file=sys.stderr)
    t_all = time.monotonic()
    try:
        for st in stages:
            t0 = time.monotonic()
            print(f"== {st}", file=sys.stderr)
            if st == "seeds":
                out = seeds.run(models, size, data, a.teacher, log)
            elif st == "plans":
                out = plans.run(models, size, data, a.teacher, log)
            elif st == "results":
                out = results.run_workers(models, size, data, workers, log)
                out["flaws"] = results.run_flaws(models, size, data, a.teacher, log)
                out["review_items"] = len(results.review_items(data, size))
            elif st == "reviews":
                out = reviews.run(models, size, data, a.teacher, log)
            elif st == "replans":
                out = plans.run_replans(models, size, data, a.teacher, log)
            elif st == "gate":
                out = gate.run(models, size, data, a.teacher, log)
            elif st == "build":
                out = build.run(data, size)
            elif st == "seeds2":
                out = seeds.run_large_batches(models, size, data, a.teacher, log)
            elif st == "plans2":
                out = plans.run_hinted(models, size, data, a.teacher, log)
            elif st == "answers":
                out = results.run_teacher_answers(models, size, data, a.teacher, log)
            elif st == "flaws2":
                out = results.run_flaws2(models, size, data, a.teacher, log)
            elif st == "reviews2":
                out = reviews.run_checked(models, size, data, a.teacher, log)
            elif st == "build2":
                out = build.run2(data, size)
            elif st == "seeds3":
                out = v3.run_seeds3(models, size, data, a.teacher, log)
            elif st == "plans3":
                out = v3.run_plans3(models, size, data, a.teacher, log)
            elif st == "answers3":
                out = v3.run_answers3(models, size, data, a.teacher, log)
            elif st == "flaws3":
                out = v3.run_flaws3(models, size, data, a.teacher, log)
            elif st == "reviews3":
                out = v3.run_reviews3(models, size, data, a.teacher, log)
            else:
                out = v3.run_build3(data, size)
            msg = f"== {st} done in {(time.monotonic() - t0) / 60:.1f} min: {json.dumps(out)}"
            print(msg, file=sys.stderr)
            with open(log, "a", encoding="utf-8") as f:
                f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except Stopped as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\nStopped. Run the same command again to continue where it left off.", file=sys.stderr)
        return 130
    finally:
        models.close()
    stats = "STATS-v3.md" if "build3" in stages else ("STATS-v2.md" if "build2" in stages else "STATS.md")
    print(f"All done in {(time.monotonic() - t_all) / 3600:.1f} h. See {os.path.join(data, stats)}", file=sys.stderr)
    return 0


def _shows(models, name):
    try:
        models.client.show(name)
        return True
    except OllamaError:
        return False


if __name__ == "__main__":
    sys.exit(main())
