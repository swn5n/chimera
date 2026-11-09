"""How much a data-generation run makes (DESIGN.md, "run.py and sizes.py"): which seeds it takes and how often each
variant of a step is made.

A size is a dict:
- name;
- new_calls: {target: (calls, k)}, the teacher's seed calls per target (topics.TARGETS), k requests each;
- pick: {pick name: n | "all"} and helper: {category: n | "all"}, how many kept seeds of each pick name it uses
  (seeds.wanted: blender, python and mixed for new seeds, helper_<category> or helper[category] for the helper's);
- gpt_oss_planner: the share of seeds whose round-1 plan comes from gpt-oss:120b (the rest from hydra:1.0);
- failed_dep, mixed_pool: the share of steps with a kept piece and a dependency that get each variant;
- round2: the share of seeds that get a second round;
- prose_second: the share of sections the prose judge keeps that qwen3.8:27b judges as well (the plan's check on
  self-preference);
- seeds_parallel: seeds run at once (the gate serialises their model calls);
- early_stop: None, or {"after": seeds, "min_kept": share}: stop when that many seeds are done and fewer than that
  share of their tried steps kept a piece;
- hours: what the run is expected to take, for the start line.

smoke is the 20-seed run that measures the costs first (its variant shares are higher than night's, so every path
runs); night is the overnight run over every kept seed; tiny is for tests and a quick look (three seeds).
"""
from __future__ import annotations

_NIGHT_HELPER = {"blender": "all", "coding": "all", "research_draft": "all", "planning": "all", "batch": "all",
                 "small_task": 60}

SIZES = {
    "tiny": {
        "name": "tiny",
        "new_calls": {"blender": (1, 1), "python": (1, 1)},
        "pick": {"blender": "all", "python": "all"},
        "helper": {"small_task": 1},
        "gpt_oss_planner": 0.0,
        "failed_dep": 1.0, "mixed_pool": 1.0, "round2": 1.0, "prose_second": 1.0,
        "seeds_parallel": 2,
        "early_stop": None,
        "hours": "a few minutes with real models",
    },
    "smoke": {
        "name": "smoke",
        "new_calls": {"blender": (3, 3), "python": (2, 3), "mixed": (1, 2)},
        "pick": {"blender": 6, "python": 3, "mixed": 1},
        "helper": {"blender": 2, "coding": 3, "research_draft": 2, "planning": 1, "small_task": 2},
        "gpt_oss_planner": 0.3,
        "failed_dep": 0.25, "mixed_pool": 0.25, "round2": 0.2, "prose_second": 0.2,
        "seeds_parallel": 6,
        "early_stop": None,
        "hours": "about 4-6 h (the smoke measures it)",
    },
    "night": {
        "name": "night",
        "new_calls": {"blender": (60, 5), "python": (30, 5), "mixed": (10, 5)},
        "pick": {"blender": "all", "python": "all", "mixed": "all"},
        "helper": dict(_NIGHT_HELPER),
        "gpt_oss_planner": 0.3,
        "failed_dep": 0.1, "mixed_pool": 0.1, "round2": 0.1, "prose_second": 0.2,
        "seeds_parallel": 6,
        "early_stop": {"after": 25, "min_kept": 0.3},
        "hours": "about 35-45 h of model time, over 3-4 nights (resumable)",
    },
}


def get(name) -> dict:
    """A copy of the size called name (KeyError lists the sizes there are)."""
    if name not in SIZES:
        raise KeyError(f"no size {name!r}; pick one of {', '.join(sorted(SIZES))}")
    out = dict(SIZES[name])
    out["new_calls"] = dict(out["new_calls"])
    out["pick"] = dict(out["pick"])
    out["helper"] = dict(out["helper"])
    return out
