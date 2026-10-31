"""How much to generate. "smoke" checks every stage on a few items (about 15 minutes);
"night" is the overnight run (about 7 to 8 hours on the Studio); "tiny" is for the tests.
The v2 stages (seeds2 ... build2) use the keys after "v2:" and add about 5 to 6 hours to a night run; the v3
stages (seeds3 ... build3) the keys after "v3:", about 5 hours more."""

SIZES = {
    "tiny": {
        "per_call": 3, "followup_per_call": 2,
        "seed_calls": {"coding": 1, "research_draft": 1, "blender": 1, "batch": 1, "planning": 1, "small_task": 1, "followup": 1},
        "max_plan_seeds": None, "plan_attempts": 2,
        "review_planner_tasks": 3, "review_small_tasks": 2, "worker_predict_long": 400, "worker_predict_small": 200,
        "truncate_frac": 0.5, "drop_frac": 0.5, "flaw_frac": 0.5, "min_flaws": 1, "replans": 2,
        "head_calls": 1, "heads_per_call": 2, "gate_calls_per_head": 1, "gate_per_call": 6,
        "check_after": 3, "sanity": False, "final_checks": False, "hours": "seconds",
        # v2:
        "batch_large_calls": 1, "plan_hint_max": None, "teacher_small": 2, "teacher_planner": 2, "flaws2": 3, "hours2": "seconds",
        # v3:
        "batch_large_calls3": 1, "teacher_small3": 1, "teacher_planner3": 2, "flaws3": 3, "hours3": "seconds",
    },
    "smoke": {
        "per_call": 4, "followup_per_call": 2,
        "seed_calls": {"coding": 1, "research_draft": 1, "blender": 1, "batch": 1, "planning": 1, "small_task": 1, "followup": 1},
        "max_plan_seeds": 8, "plan_attempts": 2,
        "review_planner_tasks": 4, "review_small_tasks": 4, "worker_predict_long": 2500, "worker_predict_small": 800,
        "truncate_frac": 0.5, "drop_frac": 0.5, "flaw_frac": 0.25, "min_flaws": 1, "replans": 2,
        "head_calls": 1, "heads_per_call": 3, "gate_calls_per_head": 1, "gate_per_call": 8,
        "check_after": 4, "sanity": True, "final_checks": True, "hours": "about 15 minutes",
        # v2 (about 15 minutes more):
        "batch_large_calls": 1, "plan_hint_max": 4, "teacher_small": 2, "teacher_planner": 2, "flaws2": 3,
        "hours2": "about 15 minutes",
        # v3 (about 15 minutes more):
        "batch_large_calls3": 1, "teacher_small3": 1, "teacher_planner3": 2, "flaws3": 3, "hours3": "about 15 minutes",
    },
    "night": {
        "per_call": 10, "followup_per_call": 5,
        "seed_calls": {"coding": 18, "research_draft": 14, "blender": 12, "batch": 12, "planning": 6, "small_task": 18, "followup": 8},
        "max_plan_seeds": None, "plan_attempts": 2,
        "review_planner_tasks": 180, "review_small_tasks": 180, "worker_predict_long": 2500, "worker_predict_small": 800,
        "truncate_frac": 0.2, "drop_frac": 0.12, "flaw_frac": 0.15, "replans": 120,
        "head_calls": 9, "heads_per_call": 6, "gate_calls_per_head": 2, "gate_per_call": 10,
        "check_after": 20, "sanity": True, "final_checks": False, "hours": "about 7 to 8 hours",
        # v2 (about 5 to 6 hours more):
        "batch_large_calls": 5, "plan_hint_max": None, "teacher_small": 90, "teacher_planner": 60, "flaws2": 130,
        "hours2": "about 5 to 6 hours",
        # v3 (about 5 hours more):
        "batch_large_calls3": 10, "teacher_small3": 60, "teacher_planner3": 80, "flaws3": 150, "hours3": "about 5 hours",
    },
}
