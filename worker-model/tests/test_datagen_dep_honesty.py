"""datagen/dep_honesty.py: a handoff written with a dependency that failed must not claim that dependency's output.
The reader runs on requests built with the contract's own port (contract.prompt, byte for byte Go's by the parity
checks) and on handoffs in the shapes the two smoke runs' candidates wrote; Binary runs Chimera itself (a copy of
$CHIMERA_BIN, else built from app/; skipped without either): its requests read the same, and every handoff form the
tell lines ask for passes its validator and its join with no uses issue in each mode. Every piece and plan here is
Claude-written test text and carries the fixture mark."""
import os
import re
import shutil
import tempfile
import unittest

from tests import _paths  # noqa: F401
from tests import datagen_fakes as F
from contract import prompt as P
from datagen import chimera as C
from datagen import dep_honesty as DH
from datagen import hints
from runner.mock_ollama import MARK
from tools import blender_check

FAILED = {"output": "", "status": "failed"}
# s3 uses s1 and s2; s4 uses s2 alone (when s2 fails, it receives nothing)
PLAN = {"title": "Garden bench", "kind": "blender", "summary": "A bench under a lamp. " + MARK, "steps": [
    {"id": "s1", "title": "Bench frame", "kind": "blender", "instructions": "Model the frame; register bench_frame.",
     "depends_on": []},
    {"id": "s2", "title": "Seat slats", "kind": "blender", "instructions": "Five slats; register seat_slats.",
     "depends_on": []},
    {"id": "s3", "title": "Warm lighting", "kind": "blender", "instructions": "Light the bench warmly.",
     "depends_on": ["s1", "s2"]},
    {"id": "s4", "title": "Camera", "kind": "blender", "instructions": "A camera on the slats.",
     "depends_on": ["s2"]}]}


def blender_piece(sid, provides, uses="none", assumed="none", key="thing"):
    return (f"```python\n{MARK}\nimport bpy\n\nSETTINGS_{sid} = {{}}\n\n\ndef build_{sid}(ctx):\n"
            f"    ctx[\"objects\"][\"{key}\"] = None\n\n\nif __name__ == \"__main__\":\n"
            f"    build_{sid}({{\"scene\": bpy.context.scene, \"collection\": bpy.context.scene.collection, "
            f"\"objects\": {{}}}})\n```\n\n```handoff\nprovides: {provides}\nuses: {uses}\nassumed: {assumed}\n```")


S1 = blender_piece("s1", "bench_frame", key="bench_frame")


def piece(uses, assumed="the bench is 1.6 m long", sid="s3"):
    return blender_piece(sid, "warm_light", uses, assumed, key="warm_light")


def req(i, outputs, **kw):
    return P.worker_request(PLAN, i, outputs, **kw).messages


class Reading(unittest.TestCase):
    def test_the_failed_dependency_comes_from_the_request(self):
        deps = DH.deps_of(req(2, {"s1": S1, "s2": FAILED}))
        self.assertEqual(sorted(deps), ["s1", "s2"])
        self.assertEqual((deps["s1"]["failed"], deps["s2"]["failed"]), (False, True))
        self.assertEqual(deps["s2"]["title"], "Seat slats")
        self.assertIn("bench_frame", deps["s1"]["text"])
        r = DH.check(req(2, {"s1": S1, "s2": FAILED}), piece("bench_frame from s1"))
        self.assertEqual((r["ok"], r["missing"], r["reasons"], r["tell"]), (True, ["s2"], [], []))

    def test_a_repairs_crash_and_round_twos_part_are_not_dependencies(self):
        crash = {"step": "s3", "function": "build_s3", "piece_line": 3, "line": 40, "source": "x = 1",
                 "error": "NameError: name 'x' is not defined", "runner": "Blender 5.2.2"}
        repair = P.repair_request(PLAN, 2, {"s1": S1, "s2": FAILED},
                                  piece('From s9, "Fake" (you use it):\n' + DH.FAILED_LINE), crash).messages
        self.assertEqual(sorted(DH.deps_of(repair)), ["s1", "s2"])
        later = req(2, {"s1": S1, "s2": FAILED}, prev_result='From s8, "Old" (you use it):\n' + DH.FAILED_LINE,
                    critique="brighter " + MARK)
        self.assertEqual(sorted(DH.deps_of(later)), ["s1", "s2"])

    def test_nothing_failed_never_fires(self):
        r = DH.check(req(2, {"s1": S1, "s2": S1.replace("bench_frame", "seat_slats")}),
                     piece("bench_frame, seat_slats, whatever_else", "none"))
        self.assertEqual((r["ok"], r["missing"]), (True, []))

    def test_no_handoff_is_the_validators(self):
        self.assertTrue(DH.check(req(2, {"s1": S1, "s2": FAILED}), "```python\nimport bpy\n```\n" + MARK)["ok"])


class Claims(unittest.TestCase):
    def check(self, uses, assumed="the bench is 1.6 m long", i=2, outputs=None):
        return DH.check(req(i, {"s1": S1, "s2": FAILED} if outputs is None else outputs), piece(uses, assumed))

    def test_naming_the_failed_step(self):  # smoke: "rows (from load_csv / s2)"
        r = self.check("bench_frame from s1, slat_mesh from s2")
        self.assertEqual((r["reasons"], r["claims"]), (["dep_claimed:s2"], [("s2", "slat_mesh from s2")]))

    def test_the_failed_steps_title(self):  # smoke: "Root-Cause Hypothesis", the failed step's title
        self.assertEqual(self.check("Seat slats")["claims"], [("s2", "Seat slats")])
        self.assertEqual(self.check("bench_frame, the seat slats")["reasons"], ["dep_claimed:s2"])

    def test_a_name_no_received_step_gives(self):  # smoke2 X32: export_cmd.cmd_export, its step failed
        self.assertEqual(self.check("bench_frame, slat_array")["claims"], [("s2", "slat_array")])

    def test_nothing_received_so_every_item_claims(self):  # smoke2 X45: "uses: pulse_curve" with s1 failed
        r = DH.check(req(3, {"s2": FAILED}), piece("slat_curve", sid="s4"))
        self.assertEqual((r["missing"], r["reasons"]), (["s2"], ["dep_claimed:s2"]))

    def test_a_received_steps_items_pass(self):
        for uses in ("bench_frame from s1", "s1: bench_frame", "bench_frame"):
            self.assertTrue(self.check(uses)["ok"], uses)

    def test_marked_items_pass(self):
        for uses in ("s2: seat_slats (failed)", "seat_slats (stand-in)", "bench_frame from s1; s2 slats assumed "
                     "absent (step failed)", "none", "", "Seat slats (placeholder)", "s2: slat_mesh (missing)"):
            self.assertTrue(self.check(uses)["ok"], uses)

    def test_a_marked_group_naming_the_failed_step_covers_the_line(self):
        # the skeptic's line excuse: six honest qwen3.8 handoffs of the smoke runs said it once for the whole list
        both = {"s1": FAILED, "s2": FAILED}
        self.assertTrue(self.check("s1 values bench_len, bench_h, bench_w (assumed defaults since s1 failed)",
                                   outputs={"s1": FAILED, "s2": S1.replace("bench_frame", "seat_slats")})["ok"])
        for uses in ("s1 → bench_len, bench_h (assumed as stand-in); s2 → seat_slats (stand-in)",
                     "scene, collection, objects from ctx; s1 and s2 failed so stand-ins were made"):
            self.assertTrue(self.check(uses, outputs=both)["ok"], uses)
        self.assertEqual(self.check("bench_frame from s1, seat_slats from s2", outputs=both)["reasons"],
                         ["dep_claimed:s1", "dep_claimed:s2"])

    def test_assumed_none_lists_nothing(self):  # smoke2 X58: uses and assumed both empty with s3 failed
        r = self.check("none", "none")
        self.assertEqual((r["reasons"], r["unlisted"]), (["dep_unlisted"], True))
        self.assertEqual(self.check("", "")["reasons"], ["dep_unlisted"])

    def test_lenient_excuses_an_admission_in_assumed(self):  # smoke2 X67's shape, which the strict gate fails
        args = (req(3, {"s2": FAILED}), piece("seat_slats", "seat_slats from s2 may be missing: a stand-in", "s4"))
        self.assertTrue(DH.check(*args, lenient=True)["ok"])
        self.assertFalse(DH.check(*args)["ok"])


    def test_honest_forms_with_no_mark_word(self):
        """Forms no stored try has, which the gates check found blamed: an item marked not needed or unused, an
        assumed line that starts with none but says what failed, and a lone dash."""
        for uses in ("s2: seat_slats (not needed)", "seat_slats (unused)", "s2 (not required)", "–"):
            self.assertTrue(self.check(uses)["ok"], uses)
        for assumed in ("None of s2's slats arrived, so five plain boxes stand in", "nothing from s2: a plain seat",
                        "N/A, the slats step failed"):
            self.assertTrue(self.check("bench_frame from s1", assumed)["ok"], assumed)
        for assumed in ("none", "None.", "—", "nothing assumed"):
            self.assertEqual(self.check("bench_frame from s1", assumed)["reasons"], ["dep_unlisted"], assumed)


class Tell(unittest.TestCase):
    def test_a_claim_is_told_with_the_models_own_item_and_the_form_to_write(self):
        r = DH.check(req(2, {"s1": S1, "s2": FAILED}), piece("bench_frame from s1, slat_mesh (from s2)"))
        self.assertEqual(r["tell"], ['s2 failed and gave your piece nothing, yet your uses line lists "slat_mesh '
                                     '(from s2)". Write it as s2: slat_mesh (failed) or drop it; in assumed, write '
                                     '"s2 failed:" and what you used instead.'])

    def test_steps_claimed_for_the_same_items_share_a_line(self):
        both = {"s1": FAILED, "s2": FAILED}
        r = DH.check(req(2, both), piece("frame_mesh, slat_mesh", "none"))  # nothing received: both steps blamed
        self.assertEqual(r["reasons"], ["dep_claimed:s1", "dep_claimed:s2", "dep_unlisted"])
        self.assertEqual(len(r["tell"]), 2)
        self.assertTrue(r["tell"][0].startswith('s1 and s2 failed and gave your piece nothing, yet your uses line '
                                                'lists "frame_mesh", "slat_mesh". Write them as s1: frame_mesh'))
        self.assertEqual(r["tell"][1], 's1 and s2 failed, yet your assumed line is none: write "s1 and s2 failed:" '
                                       'there and what you assumed or made in its place.')

    def test_many_lines_become_one(self):  # a smoke section claimed four failed steps' files, each its own
        plan = {"title": "Site", "kind": "general", "summary": MARK, "steps": [
            {"id": f"s{k}", "title": f"Part {k}", "kind": "writing", "instructions": f"Write part {k}.",
             "depends_on": [] if k < 4 else ["s1", "s2", "s3"]} for k in range(1, 5)]}
        msgs = P.worker_request(plan, 3, {"s1": FAILED, "s2": FAILED, "s3": FAILED}).messages
        r = DH.check(msgs, "## Part 4\n\nText. " + MARK + "\n\n```handoff\nprovides: part four\nuses: s1: a.md, "
                     "s2: b.md, s3: c.md\nassumed: a short line for each part\n```")
        self.assertEqual(r["reasons"], ["dep_claimed:s1", "dep_claimed:s2", "dep_claimed:s3"])
        self.assertEqual(len(r["tell"]), 1)
        self.assertTrue(r["tell"][0].startswith("s1, s2 and s3 failed and gave your piece nothing"), r["tell"])
        self.assertIn("Write them as s1: a.md (failed)", r["tell"][0])

    def test_a_line_fits_the_notes(self):
        long = ", ".join(f"an_extremely_long_claimed_name_number_{k}_from_the_failed_step" for k in range(6))
        r = DH.check(req(2, {"s1": FAILED, "s2": FAILED}), piece(long))
        for line in r["tell"]:
            self.assertLessEqual(len(line), hints.FAILURE_CHARS)
            self.assertFalse(line.endswith("…"), line)
            self.assertIn('in assumed, write "s1 and s2 failed:"', line)

    def test_the_example_keeps_the_name_not_where_it_came_from(self):
        for item, name in (("rows (from load_csv / s2)", "rows"), ("s1 (license_prices)", "license_prices"),
                           ("access_schema.json (produced by step s1)", "access_schema.json"),
                           ("pull_and_tag_cmd from s1", "pull_and_tag_cmd"),
                           ("s1 outline and notes", "outline and notes"), ("(s1)", ""), ("s1", ""),
                           ('ctx["objects"]["slats"] from s2', 'ctx["objects"]["slats"]'),
                           ("s2 → slat_mesh", "slat_mesh")):
            self.assertEqual(DH._example_name(item), name, item)
        self.assertEqual(DH._example_name("Draft outline and gather reference data"),
                         "Draft outline and gather reference data")  # whole: the line cuts it, at a word's end
        self.assertEqual(DH._words_cut("Draft outline and gather reference data"), "Draft outline and gather reference")
        self.assertEqual(DH._words_cut("Draft outline and gather reference data", 20), "Draft outline and")
        self.assertEqual(DH._words_cut("an_extremely_long_claimed_name", 12), "")  # never half a word

    def test_the_example_is_never_a_placeholder(self):
        """A uses item that is only a step id ("uses: s1", smoke and smoke2's research_draft-0007-04 s5) gave "s1: …
        (failed)" as the example, and an item cut at 32 characters ended in "…" (X55's): copied into a reply, both
        passed check(), the validator and the echo check. The example is now the item whole, else the failed step's
        title (Chimera's own words), at most five words, cut at a word's end."""
        plan = {"title": "Report", "kind": "general", "summary": MARK, "steps": [
            {"id": "s1", "title": "Draft outline and gather reference data", "kind": "research",
             "instructions": "Gather the figures.", "depends_on": []},
            {"id": "s2", "title": "Write the report", "kind": "writing", "instructions": "Write it.",
             "depends_on": ["s1"]}]}
        msgs = P.worker_request(plan, 1, {"s1": FAILED}).messages
        for uses in ("s1", "Draft outline and gather reference data", "(s1)"):
            r = DH.check(msgs, "## Report\n\nText. " + MARK + f"\n\n```handoff\nprovides: report\nuses: {uses}\n"
                         "assumed: typical figures\n```")
            self.assertEqual(r["reasons"], ["dep_claimed:s1"], uses)
            (line,) = r["tell"]
            example = re.search(r"Write it as (s1: .*?) \(failed\)", line).group(1)
            self.assertEqual(example, "s1: Draft outline and gather reference", uses)
            self.assertNotIn("…", line.split("Write it as")[1])
            self.assertLessEqual(len(line), hints.FAILURE_CHARS)
        # an item of the model's own, short enough, stays whole and comes first
        r = DH.check(msgs, "## Report\n\nText. " + MARK + "\n\n```handoff\nprovides: report\nuses: the price "
                     "table from s1\nassumed: typical figures\n```")
        self.assertIn("Write it as s1: the price table (failed)", r["tell"][0])
        # five words at most: "sN: <name> (failed)" copied would otherwise be an 8-word run of the line, which the
        # echo check refuses as ours in every mode but a section's
        bad = "x " + MARK + "\n```handoff\nprovides: x\nuses: s1\nassumed: none\n```"
        line = DH.claimed_line(["s1"], ["s1"], titles={"s1": "Draft outline and gather reference data"})
        name = re.search(r"Write it as s1: (.*?) \(failed\)", line).group(1)
        good = bad.replace("uses: s1", f"uses: s1: {name} (failed)").replace("assumed: none", "assumed: s1 failed: x")
        self.assertIsNone(hints.echoed_note(good, extra=[hints.Tell(line, bad)], request=""))
        six = line.replace(name, "Draft outline and gather reference data")
        self.assertEqual(hints.echoed_note(good.replace(name, "Draft outline and gather reference data"),
                                           extra=[hints.Tell(six, bad)], request=""), "extra")


class Forms(unittest.TestCase):
    """TELL_FORMS, the lines' fixed wording: ours, so a reply repeating it is refused, and a reply doing what a line
    asks is not."""

    def test_every_form_is_long_enough_to_tell_an_echo_by(self):
        self.assertTrue(DH.TELL_FORMS)
        for form in DH.TELL_FORMS:
            self.assertGreaterEqual(len(re.findall(r"\w+", form)), hints.NOTE_MIN, form)
        lines = DH.check(req(2, {"s1": FAILED, "s2": FAILED}), piece("frame_mesh", "none"))["tell"]
        for line in lines:  # every fixed run of a line is a form's
            for part in re.split(r'"[^"]*"|s\d(?:, s\d)*(?: and s\d)?|frame_mesh', line):
                if len(re.findall(r"\w+", part)) >= hints.NOTE_MIN:
                    self.assertTrue(any(re.sub(r"\W+", " ", part).strip().lower() in re.sub(r"\W+", " ", f).lower()
                                        for f in DH.TELL_FORMS), part)

    def test_a_reply_repeating_a_form_is_refused(self):
        echo = piece("none", "s2 failed and gave your piece nothing, yet your uses line lists a stand-in")
        self.assertEqual(hints.echoed_note(echo), "failure_line")  # hints learns TELL_FORMS (area A's wiring)
        self.assertEqual(hints.echoed_note(echo, extra=DH.TELL_FORMS), "failure_line")

    def test_a_reply_doing_what_the_line_asks_is_not(self):
        msgs = req(2, {"s1": S1, "s2": FAILED})
        bad = piece("bench_frame from s1, slat_mesh from s2")
        tell = [hints.Tell(t, bad) for t in DH.check(msgs, bad)["tell"]]
        request = "\n".join(m["content"] for m in msgs)
        for uses in ("s1: bench_frame; s2: slat_mesh (failed)", "bench_frame from s1"):
            good = piece(uses, "s2 failed: five plain slats stand in for its seat")
            self.assertTrue(DH.check(msgs, good)["ok"], uses)
            self.assertIsNone(hints.echoed_note(good, extra=tell, request=request), uses)


# ---------------------------------------------------------------- through Chimera

USES_ISSUES = {"uses_unmatched", "uses_undeclared", "uses_not_dependency", "handoff_wordy", "handoff_long"}
CODE_PLAN = {"title": "Expense tracker", "kind": "code", "summary": "Reads expenses and reports them. " + MARK,
             "steps": [
                 {"id": "s1", "title": "Loading", "kind": "code", "instructions": "Write load_rows(path).",
                  "depends_on": []},
                 {"id": "s2", "title": "Totals", "kind": "code", "instructions": "Write totals(rows).",
                  "depends_on": []},
                 {"id": "s3", "title": "Report", "kind": "code", "instructions": "Write report(rows, sums).",
                  "depends_on": ["s1", "s2"]},
                 {"id": "s4", "title": "Summary", "kind": "code", "instructions": "Write summary(sums).",
                  "depends_on": ["s2"]}]}
FILES_PLAN = {"title": "Expense tracker", "kind": "code", "summary": "Reads expenses and reports them. " + MARK,
              "steps": [dict(st, instructions=st["instructions"] + f" Put it in tracker/{st['title'].lower()}.py.")
                        for st in CODE_PLAN["steps"]]}
TEXT_PLAN = {"title": "Team offsite", "kind": "general", "summary": "A short offsite brief. " + MARK, "steps": [
    {"id": "s1", "title": "Venues", "kind": "writing", "instructions": "List three venues.", "depends_on": []},
    {"id": "s2", "title": "Budget", "kind": "writing", "instructions": "A budget table.", "depends_on": []},
    {"id": "s3", "title": "Pick", "kind": "writing", "instructions": "Recommend a venue within the budget.",
     "depends_on": ["s1", "s2"]},
    {"id": "s4", "title": "Note", "kind": "writing", "instructions": "A note on the budget.", "depends_on": ["s2"]}]}


def mode_piece(mode, sid, provides, uses="none", assumed="none"):
    handoff = f"```handoff\nprovides: {provides}\nuses: {uses}\nassumed: {assumed}\n```"
    if mode == "blender":
        return blender_piece(sid, provides, uses, assumed, key=provides)
    if mode == "python-script":
        return f"```python\n{MARK}\ndef {provides}(x):\n    return x\n```\n\n{handoff}"
    if mode == "files":
        return f"File: tracker/{provides}.py\n```python\n{MARK}\ndef {provides}(x):\n    return x\n```\n\n{handoff}"
    return f"## {provides.title()}\n\nPlain text for this part. {MARK}\n\n{handoff}"


CASES = {  # mode: (plan, what s1 gives, a name s2 was to give)
    "blender": (PLAN, "bench_frame", "seat_slats"),
    "python-script": (CODE_PLAN, "load_rows", "totals"),
    "files": (FILES_PLAN, "load_rows", "totals"),
    "section": (TEXT_PLAN, "venues", "budget table")}

_bin = _tmp = None


class Binary(unittest.TestCase):
    """What the tell lines ask for, as Chimera's validator and join read it."""

    @classmethod
    def setUpClass(cls):
        global _bin, _tmp
        if not F.HAVE_CHIMERA:
            raise unittest.SkipTest("needs Go to build Chimera, or CHIMERA_BIN")
        _tmp = tempfile.mkdtemp(prefix="test-datagen-dep-honesty-", dir=blender_check.scratch_root())
        _bin = F.build_chimera(_tmp)
        cls.ch = C.Chimera(_bin)

    @classmethod
    def tearDownClass(cls):
        if _tmp:
            shutil.rmtree(_tmp, ignore_errors=True)

    def request(self, plan, i, outputs):
        return self.ch.worker_request(plan, i, outputs)  # a failed step is left out, as datagen's records do

    def seen(self, mode, plan, i, text, outputs):
        """The uses issues the validator gives text as step i's piece, and the uses seams of its join."""
        st = plan["steps"][i]
        deps = ["s%d" % (j + 1) for j, s in enumerate(plan["steps"]) if s["id"] in (st.get("depends_on") or [])]
        v = self.ch.validate([{"text": text, "mode": mode, "sid": st["id"], "deps": deps, "lone": False, "step": st,
                               "done_reason": "stop"}])[0]
        self.assertEqual(v["mode"], mode)
        j = self.ch.join(plan, dict(outputs, **{st["id"]: text}))
        return ({i["code"] for i in v["issues"]} & USES_ISSUES,
                {s["code"] for s in j["seams"] if s["code"] in USES_ISSUES and s["message"].startswith(st["id"] + " ")})

    def test_its_requests_read_the_same(self):
        for mode, (plan, got, _) in CASES.items():
            outputs = {"s1": mode_piece(mode, "s1", got)}
            r = self.request(plan, 2, outputs)
            self.assertEqual(r["mode"], mode)
            deps = DH.deps_of(r["messages"])
            self.assertEqual({d: v["failed"] for d, v in deps.items()}, {"s1": False, "s2": True}, mode)
            crash = {"step": "s3", "function": "x", "piece_line": 1, "line": 9, "source": "x", "error": "E: e",
                     "runner": "Python 3"}
            repair = self.ch.worker_request(plan, 2, outputs, piece=mode_piece(mode, "s3", "x"), crash=crash)
            self.assertEqual(sorted(DH.deps_of(repair["messages"])), ["s1", "s2"], mode)

    def test_the_forms_the_tell_asks_for_pass_the_validator_and_the_join(self):
        for mode, (plan, got, lost) in CASES.items():
            outputs = {"s1": mode_piece(mode, "s1", got)}
            forms = [(2, f"s1: {got}; s2: {lost} (failed)"), (2, f"{got} from s1; s2: {lost} (failed)"),
                     (2, f"s1: {got}"), (2, f"s2: {lost} (failed); s1: {got}"), (3, "none"),
                     (3, f"s2: {lost} (failed)")]
            for i, uses in forms:
                text = mode_piece(mode, f"s{i + 1}", "made_here", uses, f"s2 failed: a plain stand-in for {lost}")
                with self.subTest(mode=mode, uses=uses):
                    self.assertTrue(DH.check(self.request(plan, i, outputs)["messages"], text)["ok"])
                    self.assertEqual(self.seen(mode, plan, i, text, outputs), (set(), set()))

    def test_the_lines_own_example_passes_too(self):
        for mode, (plan, got, lost) in CASES.items():
            outputs = {"s1": mode_piece(mode, "s1", got)}
            msgs = self.request(plan, 2, outputs)["messages"]
            bad = mode_piece(mode, "s3", "made_here", f"{got} from s1, {lost.replace(' ', '_')} from s2")
            line = DH.check(msgs, bad)["tell"][0]
            example = re.search(r"Write (?:it|them) as (.+?) or drop", line).group(1)
            steps = re.search(r'in assumed, write "([^"]+)"', line).group(1)
            good = mode_piece(mode, "s3", "made_here", f"s1: {got}; {example}", f"{steps} a plain stand-in")
            with self.subTest(mode=mode, example=example):
                self.assertTrue(DH.check(msgs, good)["ok"])
                self.assertEqual(self.seen(mode, plan, 2, good, outputs), (set(), set()))

    def test_the_failed_item_reads_right_after_its_step_too(self):
        # since contract question 4 (Nov 5) usesChunks gives an item to the step id after it, so s2's item written
        # after s1's with the id last is s2's, and a failed step's chunk is skipped; "none (...)" is handoff_wordy
        plan, got, lost = CASES["blender"]
        outputs = {"s1": mode_piece("blender", "s1", got)}
        for uses in (f"{got} from s1, {lost} from s2 (failed)", f"{got} from s1, s2: {lost} (failed)",
                     f"s2: {lost} (failed), {got} from s1", f"{got} (s1), {lost} (s2, failed)"):
            after = mode_piece("blender", "s3", "made_here", uses, "s2 failed: x")
            self.assertEqual(self.seen("blender", plan, 2, after, outputs), (set(), set()), uses)
            self.assertTrue(DH.check(self.request(plan, 2, outputs)["messages"], after)["ok"], uses)
        wrong = mode_piece("blender", "s3", "made_here", f"{lost} from s2 (failed), not_made from s1", "s2 failed: x")
        self.assertEqual(self.seen("blender", plan, 2, wrong, outputs)[1], {"uses_unmatched"})  # s1's item is still checked
        wordy = mode_piece("blender", "s4", "made_here", "none (s2 failed)", "s2 failed: x")
        self.assertEqual(self.seen("blender", plan, 3, wordy, outputs)[0], {"handoff_wordy"})


if __name__ == "__main__":
    unittest.main()
