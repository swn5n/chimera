"""Scoring one worker reply, and the summaries.

Per sample (score_step):
- contract: contract/validate.validate_piece in the step's mode (also for today's prompt, where it shows how far
  today's replies are from the contract's shape): contract_ok (what Chimera can join: since Oct 30 that includes
  the two near-miss handoff forms, handoff_unlabelled and handoff_unfenced), form_ok (no errors and the exact
  written form: what data generation keeps), ok, the error and warning codes, the handoff.
- runaway: the runner stopped reading the reply (runner/common.py): "in content" when its content passed the reply
  cap (REPLY_CAP, 6,144 content tokens) or the guard hit while it wrote content, "in thinking" when the runaway
  guard (MAX_REPLY_TOKENS, 16,384, thinking included) hit while it was still thinking. A failure of its own either
  way: it never counts as a strict pass, a fix or a scene, and it is counted apart from cut_off (Ollama itself
  stopping at a length limit).
- blender: the step's script (runner/blender_run.script_for_step: joined with its dependencies when it can be)
  through Chimera's check in 5.2.2 and 5.0.1 (outcome, strict, the line and error), the probes run directly and out
  of band (the scene assertions, strict_full over the whole output, stand-in, ctx["objects"] keys, names), the
  counted strict per version (blender_run.counted_strict: the check's strict and strict_full), API errors from
  tools/rna_lint.py on the reply's own script, and the provides probe (names the handoff provides that the scene or
  ctx["objects"] has).
- expect: the eval's word and pattern checks (needles, must_mention, must_match, must_not_match, assumed_mentions,
  uses_mentions; each word group passes when any of its words is there, case-insensitive).
- repair (W3): fixed in the crash's version, fixed in every version it crashed in (a reply with no script, or a
  runaway, is not fixed), the fix patterns, and the share of the broken block's lines changed (each changed line
  once: a replaced line is one line, not a removal plus an addition). "changed" keeps the eval's own convention
  (removed plus added, as its changed_lines counts them) for comparing with the reference fix.

Summaries (aggregate) count every Blender sample: a reply with no script Chimera's check would run, or a runaway,
counts as a fail in the strict and scene rates, and is reported apart (no_script, runaway, unchecked). Two crash
rates, both the share whose check outcome was "failed" (a definite crash):
- crash_<v>: over every Blender sample (blender_n). A sample with no script, or a runaway Blender never ran, is
  not a crash, so the more of them, the lower this looks;
- crash_checked_<v>: over the samples Blender checked (blender_checked): the plan's "definite crashes at most 10%".
"""
from __future__ import annotations

import difflib
import hashlib
import re

from runner import blender_run
from runner.common import RUNNER_CUT, fmt_pct, md_table, median, pct

import evalset  # noqa: E402
from contract.goport import estimate_tokens  # noqa: E402
from contract.validate import MAX_PIECE_TOKENS, validate_piece  # noqa: E402

VERSIONS = ("5.2.2", "5.0.1")
_QUOTED = re.compile(r"""\[\s*['"]([\w.-]+)['"]\s*\]|\b(chimera_\w+)""")


def groups_hit(text, groups):
    """[(group, hit)] for word groups: a group is hit when any of its words is in text (case-insensitive)."""
    t = (text or "").lower()
    return [(g, any(w.lower() in t for w in g)) for g in groups or []]


def expect_checks(reply, piece, expect):
    """The eval's word and pattern checks on a reply. Returns {name: {"ok", "missed"}} for the checks the case has."""
    out = {}
    h = piece.handoff
    for name, text in (("needles", reply), ("must_mention", reply),
                       ("assumed_mentions", h.assumed if h else ""), ("uses_mentions", h.uses if h else "")):
        gs = expect.get(name)
        if gs:
            hits = groups_hit(text, gs)
            out[name] = {"ok": all(x for _, x in hits), "missed": [g for g, x in hits if not x]}
    for name, want in (("must_match", True), ("must_not_match", False)):
        pats = expect.get(name) or []
        if pats:
            bad = [p for p in pats if bool(re.search(p, reply or "")) != want]
            out[name] = {"ok": not bad, "missed": bad}
    return out


def provided_names(provides):
    """Names a handoff's provides line gives: ctx["objects"]["key"] keys and chimera_ names."""
    out = []
    for m in _QUOTED.finditer(provides or ""):
        n = m.group(1) or m.group(2)
        if n and n not in ("objects", "scene", "collection") and n not in out:
            out.append(n)
    return out


def provides_probe(handoff, probe):
    """{named, missing}: provided names that neither ctx["objects"] nor the scene's names have (probe: one version's
    record from the direct run, with the tools probe's ctx_keys and names). None when that probe didn't run."""
    if not handoff or probe.get("names") is None:
        return None
    named = provided_names(handoff.provides)
    have = set(probe.get("ctx_keys") or []) | set(probe.get("names") or [])
    return {"named": named, "missing": [n for n in named if n not in have]}


def _opcodes(before, after):
    return [op for op in difflib.SequenceMatcher(None, before.split("\n"), after.split("\n")).get_opcodes()
            if op[0] != "equal"]


def changed_lines(before, after):
    """Lines removed plus lines added between two blocks (a replaced line counts twice): the eval's changed_lines."""
    return sum((i2 - i1) + (j2 - j1) for _, i1, i2, j1, j2 in _opcodes(before, after))


def lines_changed(before, after):
    """Lines changed between two blocks, each once: a replaced line is one, a removed or an added line is one, and a
    hunk of 2 lines replaced by 3 is 3 (the larger side of each hunk). The plan's "share of lines changed"."""
    return sum(max(i2 - i1, j2 - j1) for _, i1, i2, j1, j2 in _opcodes(before, after))


def lint_counts(linter, script):
    if linter is None or not script:
        return None
    found = linter.lint(script)
    return {"errors": sum(1 for x in found if x["level"] == "error"), "warns": sum(1 for x in found if x["level"] == "warn"),
            "findings": [{"line": x["line"], "level": x["level"], "message": x["message"][:200]} for x in found[:8]]}


def own_script(piece, reply):
    """The reply's own Blender code: the contract piece's block, else what Chimera's check would pick."""
    return piece.code if piece.code and piece.mode == "blender" else blender_run.reply_script(reply)


def score_step(case, prompt_name, reply, call, blender=None, linter=None, reuse=None):
    """Everything measured about one reply. blender: a runner.blender_run.Blender (None: no Blender runs). reuse:
    {"script", "blender"}, an earlier score's Blender results and the script they were for (runner/rescore.py),
    kept when the step's script is still that one."""
    stats = call.get("stats") or {}
    done_reason = stats.get("done_reason") or ""
    runaway = done_reason == RUNNER_CUT  # the reply cap (or the runaway guard) cut it: a failure of its own
    if runaway:
        done_reason = "length"  # to the validator, a reply cut at a limit, like Ollama's own "length"
    # The length rule (3,500 tokens) is the data filter's, not a reason a piece can't be joined: kept apart here.
    piece = validate_piece(reply or "", case.mode, sid=case.sid, deps=case.deps, lone=case.lone, step=case.step,
                           done_reason=done_reason, reject_cut=True, max_tokens=None)
    rec = {"contract": {"contract_ok": piece.contract_ok, "form_ok": piece.form_ok, "ok": piece.ok,
                        "errors": sorted({i.code for i in piece.errors}), "warns": sorted({i.code for i in piece.warnings}),
                        "too_long": estimate_tokens(reply or "") > MAX_PIECE_TOKENS,
                        "handoff": piece.handoff.to_dict() if piece.handoff else None},
           "runaway": runaway, "runner_limit": stats.get("runner_limit") if runaway else None,
           "runaway_in": (stats.get("runaway_in") or "content") if runaway else None,
           "cut_off": done_reason == "length" and not runaway, "expect": expect_checks(reply, piece, case.expect)}
    if case.mode == "blender":
        script = own_script(piece, reply)
        rec["lint"] = lint_counts(linter, script)
        rec["blender"] = run_blender(case, reply, blender, piece, reuse)
        if case.expect.get("stand_in") and rec["blender"].get("probe"):  # W4f: a failed dependency needs a stand-in
            stood = any(p.get("stand_in") for p in rec["blender"]["probe"].values())
            rec["expect"]["stand_in"] = {"ok": stood, "missed": [] if stood else ["chimera: stand-in"]}
    if case.repair:
        rec["repair"] = repair_score(case, reply, rec.get("blender"), runaway)
    return rec


def script_sha(script):
    return hashlib.sha256(script.encode("utf-8")).hexdigest()[:20]


def run_blender(case, reply, blender, piece, reuse=None):
    kind, script, notes = blender_run.script_for_step(case.plan, case.index, case.outputs, reply or "", case.goal)
    asserts = case.expect.get("assertions") or []
    out = {"run": kind, "notes": notes, "lines": script.count("\n") + 1 if script else 0, "assertions_n": len(asserts)}
    if script:
        out["script_sha"] = script_sha(script)  # what the Blender results are for (runner/rescore.py reuses them)
    if reuse and script and reuse.get("script") in (script, out["script_sha"]) and (reuse.get("blender") or {}).get("check"):
        old = reuse["blender"]
        out.update({k: old[k] for k in ("check", "probe") if k in old})
        out["strict"] = {v: blender_run.counted_strict(c, out["probe"].get(v)) for v, c in out["check"].items()}
        out["provides"] = provides_probe(piece.handoff, next(iter(out["probe"].values()), {}))
        return out
    if not script or blender is None:
        if blender is None and script:
            out["notes"] = notes + ["Blender not run (--no-blender)"]
            out["not_run"] = True
        return out
    out["check"] = blender.check(script)
    probe = blender.probe(script)
    out["probe"] = {}
    for v, r in probe.items():
        p = {k: r.get(k) for k in ("exit", "strict_full", "bad_lines", "blender", "version_ok", "stand_in", "exception",
                                   "stopped_at_render", "seconds", "ctx_keys", "names")}
        if asserts:
            p["assert_fails"] = evalset.check_assertions(r["probe"], asserts) if r.get("probe") else ["no probe output"]
        p["dupes"] = (r.get("probe") or {}).get("duplicates")
        out["probe"][v] = p
    out["strict"] = {v: blender_run.counted_strict(c, out["probe"].get(v)) for v, c in out["check"].items()}
    first = next(iter(out["probe"].values()), {})
    out["provides"] = provides_probe(piece.handoff, first)
    return out


def repair_score(case, reply, brec, runaway=False):
    c = case.case
    before = (blender_run.reply_script(case.repair["piece"]) or "").strip("\n")
    after = (blender_run.reply_script(reply or "") or "").strip("\n")
    fx = c.get("fix") or {}
    out = {"changed": changed_lines(before, after) if after else None,  # removed plus added: the eval's convention
           "lines_changed": lines_changed(before, after) if after else None,  # each changed line once
           "piece_lines": len(before.split("\n")), "reference_changed": fx.get("changed_lines")}
    out["changed_share"] = round(out["lines_changed"] / max(1, out["piece_lines"]), 3) \
        if out["lines_changed"] is not None else None
    out["patterns"] = {"must_match": [p for p in fx.get("must_match") or [] if not re.search(p, after)],
                       "must_not_match": [p for p in fx.get("must_not_match") or [] if re.search(p, after)]}
    if brec is None or brec.get("not_run"):
        return out  # Blender not run: fixed is unknown
    if brec.get("check") and not runaway:
        crash_v = c["crash"]["version"]
        crashed_in = c["crash"].get("crashes_in") or [crash_v]
        counted = brec.get("strict") or {}
        out["fixed"] = bool(counted.get(crash_v))
        out["fixed_all"] = all(counted.get(v) for v in crashed_in if v in brec["check"])
    else:  # no script Chimera's check would run, or a runaway: not fixed
        out["fixed"] = out["fixed_all"] = False
    return out


# ---------------------------------------------------------------- one sample's verdict, for the log line and the table

def _blender(rec):
    return ((rec.get("score") or {}).get("blender")) or {}


def strict(rec, v):
    """The strict pass that counts, in one version: not a runaway, and blender_run.counted_strict (Chimera's check
    strict, with a clean whole output in the direct run)."""
    if (rec.get("score") or {}).get("runaway"):
        return False
    b = _blender(rec)
    return blender_run.counted_strict((b.get("check") or {}).get(v), (b.get("probe") or {}).get(v))


def blender_ran(rec):
    return bool(_blender(rec).get("check"))


def blender_status(rec):
    """A Blender-mode sample: "error" (the call or the scoring failed: left out of the rates), "not_run" (Blender
    wasn't run: --no-blender), "runaway" (the reply cap cut it), "no_script" (nothing Chimera's check would run),
    or "checked". runaway, no_script and checked all count in the rates; the first two never pass."""
    if rec.get("error"):
        return "error"
    if (rec.get("score") or {}).get("runaway"):
        return "runaway"
    b = _blender(rec)
    if b.get("check"):
        return "checked"
    if b.get("not_run"):
        return "not_run"
    return "no_script"


def verdict(rec, v):
    """One version's word for the log and the table: pass, runaway, the check's outcome (failed, unsure, …),
    "not strict" (the check passed, but the output has a Traceback or Error: line), or "–" (no check)."""
    if (rec.get("score") or {}).get("runaway"):
        return "runaway"
    b = _blender(rec)
    ck = (b.get("check") or {}).get(v)
    if ck is None:
        return "–"
    if strict(rec, v):
        return "pass"
    if ck.get("outcome") != "passed":
        return ck.get("outcome") or "FAIL"
    return "not strict"


def assertions_ok(rec, v):
    p = (_blender(rec).get("probe") or {}).get(v)
    if not p or "assert_fails" not in p:
        return None
    return not p["assert_fails"]


def has_assertions(rec):
    b = _blender(rec)
    return bool(b.get("assertions_n")) or any("assert_fails" in p for p in (b.get("probe") or {}).values())


def brief(rec):
    """One short line for the progress log."""
    if rec.get("error"):
        return "ERROR " + rec["error"][:80]
    sc = rec["score"]
    parts = ["contract " + ("ok" if sc["contract"]["contract_ok"] else "BROKEN " + ",".join(sc["contract"]["errors"][:3]))]
    if sc.get("runaway"):
        parts.append(f"RUNAWAY in {sc.get('runaway_in') or 'content'} (cut at {sc.get('runner_limit') or '?'} tokens)")
    b = sc.get("blender")
    if b:
        if b.get("check"):
            parts.append(" ".join(f"{v} {verdict(rec, v)}" for v in b["check"]))
            a = [assertions_ok(rec, v) for v in b["check"]]
            if any(x is not None for x in a):
                parts.append("assertions " + "/".join("-" if x is None else ("ok" if x else "FAIL") for x in a))
        else:
            parts.append("run " + b.get("run", "?") + (" (no script: a fail)" if blender_status(rec) == "no_script" else ""))
        if sc.get("lint"):
            parts.append(f"lint {sc['lint']['errors']}e")
    if sc.get("repair") and "fixed" in sc["repair"]:
        parts.append("fixed" if sc["repair"]["fixed"] else "NOT fixed")
    ex = [k for k, v in sc.get("expect", {}).items() if not v["ok"]]
    if ex:
        parts.append("missed " + ",".join(ex))
    return "; ".join(parts)


# ---------------------------------------------------------------- summaries

def aggregate(records):
    """Totals over every sample, and by part and by mode.

    The Blender rates (strict, crash, no_script, joined, assertions) are over every Blender-mode sample whose call
    and scoring went through ("blender_n"): a reply with no script Chimera's check would run and a runaway count as
    fails, not as left out, and "unchecked" says how many of each there were; crash_checked_<v> is over the samples
    Blender checked ("blender_checked") instead. When Blender wasn't run (--no-blender) they are None. "runaway"
    (split into runaway_thinking_n and runaway_content_n), "cut_off", "contract_ok" and "form_ok" are over every
    sample whose call went through."""
    def agg(rs):
        n = len(rs)
        ok = [r for r in rs if not r.get("error")]
        sc = [r["score"] for r in ok]
        fo = [s for s in sc if "form_ok" in s["contract"]]  # records from before Oct 30 have no form_ok
        run_in = [(s.get("runaway_in") or "content") for s in sc if s.get("runaway")]
        out = {"n": n, "errors": n - len(ok),
               "contract_ok": pct(sum(1 for s in sc if s["contract"]["contract_ok"]), len(ok)),
               "form_ok": pct(sum(1 for s in fo if s["contract"]["form_ok"]), len(fo)) if fo else None,
               "piece_ok": pct(sum(1 for s in sc if s["contract"]["ok"]), len(ok)),
               "cut_off": pct(sum(1 for s in sc if s.get("cut_off")), len(ok)),
               "runaway": pct(sum(1 for s in sc if s.get("runaway")), len(ok)),
               "runaway_n": sum(1 for s in sc if s.get("runaway")),
               "runaway_thinking_n": run_in.count("thinking"), "runaway_content_n": run_in.count("content"),
               "tokens_median": median([(r.get("stats") or {}).get("eval_count") for r in ok]),
               "prompt_tokens_median": median([(r.get("stats") or {}).get("prompt_eval_count") for r in ok]),
               "tok_s_median": median([r.get("tok_s") for r in ok]),
               "wall_s_median": median([r.get("wall_s") for r in ok]),
               "wall_s_total": round(sum(r.get("wall_s") or 0 for r in rs), 1)}
        bl_all = [r for r in ok if r.get("mode") == "blender"]
        status = [blender_status(r) for r in bl_all]
        bl = [r for r, st in zip(bl_all, status) if st != "not_run"]
        if bl_all:
            n_bl = len(bl)
            out["blender_n"] = n_bl
            out["blender_checked"] = sum(1 for st in status if st == "checked") + \
                sum(1 for r, st in zip(bl_all, status) if st == "runaway" and blender_ran(r))
            out["unchecked"] = {"no_script": status.count("no_script"),
                                "runaway": sum(1 for r, st in zip(bl_all, status) if st == "runaway" and not blender_ran(r))}
            out["no_script"] = pct(status.count("no_script"), n_bl)
            if "not_run" in status:
                out["blender_not_run"] = status.count("not_run")
        if bl_all and "not_run" not in status:
            for v in VERSIONS:
                out[f"strict_{v}"] = pct(sum(1 for r in bl if strict(r, v)), n_bl)
                # the check's own verdict alone (its 1,500-character tail only), to show what the whole output adds
                out[f"strict_tail_{v}"] = pct(sum(1 for r in bl if (((_blender(r).get("check") or {}).get(v) or {})
                                                                    .get("strict")) and not r["score"].get("runaway")), n_bl)
                crashed = sum(1 for r in bl if ((_blender(r).get("check") or {}).get(v) or {}).get("outcome") == "failed")
                out[f"crash_{v}"] = pct(crashed, n_bl)  # over every Blender sample: no script isn't a crash
                out[f"crash_checked_{v}"] = pct(crashed, out["blender_checked"])  # over the samples Blender checked
            out["strict_both"] = pct(sum(1 for r in bl if all(strict(r, v) for v in VERSIONS)), n_bl)
            out["joined"] = pct(sum(1 for r in bl if _blender(r).get("run") == "joined"), n_bl)
            asr = [r for r in bl if has_assertions(r)]  # no scene (no script, a runaway) fails them
            out["assertions_5.2.2"] = pct(sum(1 for r in asr if not r["score"].get("runaway")
                                              and assertions_ok(r, VERSIONS[0])), len(asr)) if asr else None
            # strict and the scene the case asks for: a script that runs clean but skips the job doesn't count
            out["strict_scene_5.2.2"] = pct(sum(1 for r in asr if strict(r, VERSIONS[0])
                                                and assertions_ok(r, VERSIONS[0])), len(asr)) if asr else None
            out["scene_n"] = len(asr)
            lints = [r["score"]["lint"] for r in bl if r["score"].get("lint")]
            out["lint_errors_mean"] = round(sum(l["errors"] for l in lints) / len(lints), 2) if lints else None
            out["lint_any"] = pct(sum(1 for l in lints if l["errors"]), len(lints)) if lints else None
            prov = [_blender(r).get("provides") for r in bl]
            prov = [x for x in prov if x and x["named"]]
            out["provides_found"] = pct(sum(1 for x in prov if not x["missing"]), len(prov)) if prov else None
        reps = [r["score"]["repair"] for r in ok if (r["score"].get("repair") or {}).get("fixed") is not None]
        if reps:
            out["repair_fixed"] = pct(sum(1 for x in reps if x["fixed"]), len(reps))
            out["repair_changed_median"] = median([x["changed_share"] for x in reps])
        exp = [r["score"]["expect"] for r in ok if r["score"].get("expect")]
        if exp:
            out["expect_ok"] = pct(sum(1 for e in exp if all(v["ok"] for v in e.values())), len(exp))
        return out

    by_part, by_mode = {}, {}
    for r in records:
        by_part.setdefault(r["part"], []).append(r)
        by_mode.setdefault(r["mode"], []).append(r)
    return {"all": agg(records), "by_part": {k: agg(v) for k, v in by_part.items()},
            "by_mode": {k: agg(v) for k, v in by_mode.items()}}


def _runaway_cell(a):
    """"33% (1 thinking, 0 content)": the runaway rate and where the runaways were cut."""
    if not a.get("runaway_n"):
        return fmt_pct(a.get("runaway"))
    return f"{fmt_pct(a.get('runaway'))} ({a.get('runaway_thinking_n', 0)} thinking, {a.get('runaway_content_n', 0)} content)"


def _row(name, a):
    return [name, a["n"], fmt_pct(a["contract_ok"]), fmt_pct(a.get("form_ok")), a.get("blender_n"),
            fmt_pct(a.get("strict_5.2.2")), fmt_pct(a.get("strict_5.0.1")), fmt_pct(a.get("strict_both")),
            fmt_pct(a.get("crash_checked_5.2.2")), fmt_pct(a.get("crash_5.2.2")),
            fmt_pct(a.get("no_script")), fmt_pct(a.get("assertions_5.2.2")), a.get("lint_errors_mean"),
            fmt_pct(a.get("repair_fixed")), fmt_pct(a.get("expect_ok")), _runaway_cell(a), fmt_pct(a["cut_off"]),
            a["tokens_median"], a["tok_s_median"], a["wall_s_median"]]


HEAD = ["", "n", "contract kept", "form ok", "Blender n", "strict 5.2.2", "strict 5.0.1", "both",
        "crash 5.2.2 (checked)", "crash 5.2.2 (all)", "no script", "assertions", "API errors", "repaired", "expect",
        "runaway", "cut off", "tokens", "tok/s", "s"]


def render_md(meta, summary, records):
    """summary.md: the totals, by part and mode, then one row per sample."""
    lines = [f"# {meta['model']}, {meta['prompt']} prompt, on the worker eval ({meta['eval_version']})", "",
             f"{meta['started']} · Ollama {meta.get('ollama_version', '?')} · digest `{(meta.get('digest') or '')[:12]}` · "
             f"samples {meta['samples']} (prose {meta['prose_samples']}) · unseeded · Blender "
             f"{', '.join(meta.get('blender_versions') or []) or 'not run'}", "",
             "EVAL ONLY: model replies to eval cases; never training data.", ""]
    if meta.get("differences_from_chimera"):
        lines += ["Differences from what Chimera 0.7.0 sends: " + "; ".join(meta["differences_from_chimera"]) + ".", ""]
    rows = [HEAD, _row("all", summary["all"])]
    rows += [_row(k, v) for k, v in sorted(summary["by_part"].items())]
    rows += [_row(k, v) for k, v in sorted(summary["by_mode"].items())]
    cap, guard = meta.get("reply_cap"), meta.get("max_reply_tokens")
    al = summary["all"]
    un = al.get("unchecked") or {}
    lines += [md_table(rows), "",
              "contract kept: the piece keeps the contract's shape, so Chimera can join it; since Oct 30 that includes "
              "the two near-miss handoff forms the validator reads (an unlabelled fence, or the three lines unfenced at "
              "the end). form ok: no errors and the contract's exact written form (a ```handoff fence, a bare File: "
              "line): what data generation keeps. "
              "Blender n: the Blender samples the rates are over; a reply with no script Chimera's check would run "
              f"(no script: {un.get('no_script', 0)}) and a runaway ({al.get('runaway_n', 0)}, of which "
              f"{un.get('runaway', 0)} had no script) count as fails, not as left out. strict: not a runaway; "
              "Chimera's check passed with no Traceback or Error: line in the 1,500 characters of output it shows "
              "(tools/blender_check.py, no probe appended); and the direct run's whole output has none either (the same "
              "rule; the probes run there). crash: the check's outcome was failed (a definite crash); \"checked\" is over "
              f"the {al.get('blender_checked', 0)} samples Blender checked (the plan's \"definite crashes at most 10%\"), "
              "\"all\" over every Blender sample, where a reply with no script or a runaway Blender never ran is not a "
              "crash. no script: the "
              "reply had no Blender script Chimera's check would run. assertions: the eval's scene assertions in 5.2.2 "
              "(no scene fails them). API errors: tools/rna_lint.py errors per reply. expect: every word and pattern "
              "check the case has. runaway: the runner stopped reading the reply, in content (its content passed the "
              + (f"reply cap of {cap} tokens, thinking not counted" if cap else "runaway guard") +
              ", or the guard hit while it wrote content) or in thinking (the runaway guard"
              + (f", {guard} tokens with thinking," if guard else "") +
              " hit while the model was still thinking); both count as fails. Chimera 0.7.0 sends no num_predict and "
              "no think field and has neither limit. cut off: Ollama itself stopped at a length limit. "
              "The plan's cut-off bar counts both.", "",
              "## Samples", ""]
    rows = [["case", "sample", "mode", "contract", "run", "5.2.2", "5.0.1", "assert", "lint", "tokens", "s", "first problem"]]
    for r in records:
        if r.get("error"):
            rows.append([r["id"], r["sample"], r["mode"], "–", "–", "–", "–", "–", "–", "–", r.get("wall_s"), r["error"][:80]])
            continue
        sc = r["score"]
        b = sc.get("blender") or {}
        ck = b.get("check") or {}
        pr = b.get("probe") or {}
        a = assertions_ok(r, VERSIONS[0])
        problem = ""
        if sc.get("runaway"):
            problem = f"runaway in {sc.get('runaway_in') or 'content'}: cut at {sc.get('runner_limit') or '?'} tokens"
        elif r["mode"] == "blender" and blender_status(r) == "no_script":
            problem = "no script: " + "; ".join(b.get("notes") or [])
        for v in VERSIONS:
            if problem:
                break
            if v in ck and not strict(r, v):
                c, p = ck[v], pr.get(v) or {}
                if not c.get("strict"):
                    problem = f"{v}: " + (f"line {c['line']}: {c.get('error')}" if c.get("line") else (c.get("strict_why") or ""))
                elif p.get("version_ok") is False:
                    problem = f"{v}: the direct run was in Blender {p.get('blender')}"
                else:
                    problem = f"{v}: the direct run printed " + ((p.get("bad_lines") or ["?"])[0])[:100]
        if not problem and sc["contract"]["errors"]:
            problem = "contract: " + ", ".join(sc["contract"]["errors"][:4])
        if not problem:
            miss = [k for k, v in sc.get("expect", {}).items() if not v["ok"]]
            problem = ("missed " + ", ".join(miss)) if miss else ""
        kept = sc["contract"]["contract_ok"]
        rows.append([r["id"], r["sample"], r["mode"],
                     ("ok" if sc["contract"].get("form_ok", True) else "ok, near miss") if kept else "broken", b.get("run", "–"),
                     verdict(r, "5.2.2"), verdict(r, "5.0.1"), "–" if a is None else ("ok" if a else "FAIL"),
                     (sc.get("lint") or {}).get("errors", "–"), (r.get("stats") or {}).get("eval_count"), r.get("wall_s"),
                     problem[:120]])
    lines += [md_table(rows), ""]
    return "\n".join(lines)
