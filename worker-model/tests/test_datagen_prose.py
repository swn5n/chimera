"""datagen/prose_gate.py: word targets in their common phrasings (and the ones that aren't the section's), the
validator's warnings that fail a target, placeholders, the intro and outro rule and its exemptions, sibling overlap,
what counts as a word, claimed sources, tests and measurements, plan step ids in the text, CSV rows that don't match
their header, python blocks that don't compile (after the fifth smoke: a Blender script's also with Python 3.11's
f-strings, checked in both Blenders' own compile() where they are), and the lines a failed check tells the next try.
Every section here ends with the fixture mark in a code block, which no count sees.

The cases marked "real" are shaped on steps of gpt-oss's stored plans (helper-model/data/raw/plans*.jsonl) and the
smoke seeds' candidates (data/gen/smoke), written here as fixtures that carry the mark (fx); none is eval text."""
import unittest

from tests import _paths  # noqa: F401
from datagen import prose_gate as G
from datagen import pysandbox
from runner.mock_ollama import MARK
from tools import blenders

TAIL = f"\n\n```\n{MARK}\n```"
HANDOFF = "\n\n```handoff\nprovides: the section\nuses: none\nassumed: none\n```"


def plan_of(*steps):
    return {"title": "Garden guide", "kind": "writing", "summary": "A guide to a small vegetable garden. " + MARK,
            "steps": [{"id": f"s{k + 1}", "title": t, "kind": kind, "instructions": ins, "depends_on": []}
                      for k, (t, kind, ins) in enumerate(steps)]}


PLAN = plan_of(("Soil", "writing", "Explain how to prepare the soil."),
               ("Planting", "writing", "Explain when and how to plant."),
               ("Watering", "writing", "Explain how much to water."))


def fx(s):
    """A fixture line: s with the mark after it (the mark names no length and no heading)."""
    return s + " " + MARK


def words(n, start=0):
    """n distinct words, so no two texts share a shingle by accident."""
    return " ".join(f"w{k}" for k in range(start, start + n))


def section(title, *paras):
    return f"## {title}\n\n" + "\n\n".join(paras) + TAIL


def verdict(text, *codes):
    return {"mode": "section", "section": text, "body": text,
            "issues": [{"level": "warn", "code": c, "message": c, "line": 1} for c in codes]}


def check(text, i=1, plan=PLAN, earlier=None, codes=()):
    return G.section_check(plan, i, text, verdict(text, *codes), earlier or {})


class TargetTests(unittest.TestCase):
    def target(self, text):
        t = G.word_target(text)
        return None if t is None else (t["kind"], t["low"], t["high"])

    def test_about(self):
        for s in ("Write about 300 words on it.", "around 300 words", "roughly 300 words", "approximately 300 words",
                  "~300 words", "Write 300 words.", "Say it in 300 words.", "a 300-word introduction",
                  "some 300 words", "Aim for about 300 words or so."):
            self.assertEqual(self.target(s), ("about", 210, 390), s)

    def test_ranges(self):
        for s in ("200-400 words", "200 to 400 words", "between 200 and 400 words", "200–400 words",
                  "a 200-400 word overview"):
            self.assertEqual(self.target(s), ("range", 140, 520), s)

    def test_at_most(self):
        for s in ("under 150 words", "no more than 150 words", "at most 150 words", "fewer than 150 words",
                  "150 words or fewer", "150 words or less", "150 words max", "up to 150 words",
                  "a maximum of 150 words"):
            self.assertEqual(self.target(s), ("max", 0, 195), s)

    def test_at_least(self):
        for s in ("at least 500 words", "no fewer than 500 words", "500+ words", "500 words or more",
                  "a minimum of 500 words", "more than 500 words"):
            self.assertEqual(self.target(s), ("min", 350, None), s)

    def test_numbers(self):
        self.assertEqual(self.target("about 1,000 words"), ("about", 700, 1300))
        self.assertEqual(self.target("about 1.5k words"), ("about", 1050, 1950))

    def test_targets_that_arent_the_sections(self):
        for s in ("Keep each bullet under 20 words.", "Give three tips of about 20 words each.",
                  "Write five points, 15 words per point.", "Explain it clearly.", "Use 3 examples."):
            self.assertIsNone(G.word_target(s), s)
        self.assertEqual(self.target("Write about 300 words; keep each bullet under 20 words."),
                         ("about", 210, 390))
        self.assertEqual(self.target("Each of the 5 tips should be under 30 words; the section around 200 words."),
                         ("about", 140, 260))
        self.assertIsNone(G.word_target("Write 3 paragraphs of about 100 words."))
        self.assertEqual(self.target("Write one paragraph of about 100 words."), ("about", 70, 130))
        self.assertEqual(self.target("Explain how each plant grows in about 200 words."), ("about", 140, 260))
        self.assertEqual(self.target("Summarize the 2,000-word report in 200 words."), ("about", 140, 260))

    def test_gpt_oss_dashes_and_about_signs(self):
        # real: gpt-oss writes U+2011 between the number and "word", and "≈" for about
        self.assertEqual(self.target(fx("Write a 400‑word section that lists and compares the specs.")),
                         ("about", 280, 520))
        self.assertEqual(self.target(fx("Write a brief (150‑200 word) summary of the soil types.")),
                         ("range", 105, 260))
        self.assertEqual(self.target(fx('Write the "Feature list" section (~650‑700 words).')), ("range", 455, 910))
        for dash in ("‐", "‒", "−"):
            self.assertEqual(self.target(fx(f"Write 200{dash}400 words.")), ("range", 140, 520), dash)
        self.assertEqual(self.target(fx("A short overview (≈300 words).")), ("about", 210, 390))
        self.assertEqual(self.target(fx("Keep it ≤ 120 words.")), ("max", 0, 156))
        self.assertEqual(G.word_target(fx("Write a 400‑word section."))["phrase"], "400-word section")

    def test_a_part_doesnt_set_the_sections_length(self):
        # real: a headline's limit inside a 2,200-word article, a closing paragraph's range in a ~600-word section
        article = fx("Using the quotes from step s1, draft a 2,200‑word article with:\n- A compelling headline "
                     "(max 10 words).\n- A brief overview (150‑200 words).\n- Three sections, each with a "
                     "sub‑headline and ~300‑word description.")
        self.assertEqual(self.target(article), ("about", 1540, 2860))
        self.assertTrue(G.word_target(article)["whole"])
        priced = fx('Write a ~600‑word section titled "Pricing & Value" comparing the costs. End the section '
                    "with a concise recommendation paragraph (≈100‑150 words).")
        self.assertEqual(self.target(priced), ("about", 420, 780))
        self.assertEqual(self.target(fx("Combine s1-s3 into a single ~1,800‑word guide. Write a concluding "
                                        "paragraph (≈100 words).")), ("about", 1260, 2340))
        self.assertEqual(self.target(fx("Write two subsections (≈70‑80 words each). Total for the section "
                                        "≈150‑160 words.")), ("range", 105, 208))
        self.assertEqual(G.word_target(fx("Write three subsections of about 600 words."),
                                       fx("Compose Core Sections (≈1,800 words total)"))["n"], [1800])
        # real: one description is the section; a description of each item is not
        self.assertEqual(self.target(fx("From step s1, write a polished product description of approximately "
                                        "250 words.")), ("about", 175, 325))
        for s in ("For each, write a brief (≈50‑60 words) recommendation.",
                  "List 30 question‑answer pairs (≤80 words each).\n**A:** <answer (≤80 words)>",
                  "Craft a single‑paragraph (max 80 words) summary for each ticket.",
                  "Each section should be ~550‑words.",
                  "For each knife gather:\n- Brand and model\n- A concise 120‑word promotional copy.",
                  "Produce a brief outline (bullet points) for a ~400‑word article on ads.",
                  "Output `description` (exactly 120 words) for each knife."):
            self.assertIsNone(G.word_target(fx(s)), s)

    def test_a_document_noun_after_n_word_is_the_whole(self):
        # real: a memo's length beside its first section's, and a press release's, which the pattern didn't read
        memo = fx("Write a 2,000‑word decision memo titled *Render_Memo_2024.pdf* with the following sections:\n"
                  "- Executive Brief (≈250 words)\n- Technical Performance Comparison (embed tables from s3)\n"
                  "- Cost Projection (embed table from s4)")
        self.assertEqual(self.target(memo), ("about", 1400, 2600))
        self.assertTrue(G.word_target(memo)["whole"])
        self.assertEqual(self.target(fx("Write a 450-word press release for the lamp. Include:\n- A headline.\n"
                                        "- An opening paragraph.")), ("about", 315, 585))
        for s, n in (("Write a 500‑word German blog article about bread.", 500),
                     ("Write a 1,500-word white paper on soil.", 1500), ("Write an 800‑word newsletter.", 800),
                     ("Create a 600‑word analysis of the audio tests.", 600)):
            got = G.word_target(fx(s))
            self.assertEqual((got["n"], got["whole"]), ([n], True), s)

    def test_a_total_is_the_lengths_and_another_steps_text_isnt_this_ones(self):
        # "total" marks the section's number only beside its length, not "the total cost"
        self.assertIsNone(G.word_target(fx("Write ~600 words comparing the plans, show the total cost in a table "
                                           "and close with a paragraph of about 100 words.")))
        for s, want in (("Keep the total word count around 1500‑1800 words.", ("range", 1050, 2340)),
                        ("Ensure the total word count does not exceed 800 words.", ("max", 0, 1040)),
                        ("Total length for this step should be about 500 words.", ("about", 350, 650)),
                        ("Write the essay, 900 words in total, with a 100-word conclusion.", ("about", 630, 1170))):
            self.assertEqual(self.target(fx(s)), want, s)
            self.assertTrue(G.word_target(fx(s))["whole"], s)
        # an N-word document another step wrote is that one's length
        self.assertEqual(self.target(fx("Shorten the 1,200-word article from s2 to about 400 words.")),
                         ("about", 280, 520))
        self.assertEqual(self.target(fx("Using the 2,000-word report from s1, write a 300-word summary.")),
                         ("about", 210, 390))
        self.assertEqual(self.target(fx("Turn the 800-word article produced in s2 into about 300 words.")),
                         ("about", 210, 390))
        self.assertEqual(self.target(fx("Write a 300-word summary of s1's findings.")), ("about", 210, 390))

    def test_one_item_a_sentence_asks_for_is_the_section(self):
        # real: a blurb step and a JSON summary step whose own limit the item rule had set aside
        self.assertEqual(self.target(fx('Write a blurb (max 120 words) for the blues concept "Rain Riffs".')),
                         ("max", 0, 156))
        self.assertEqual(self.target(fx('Produce a JSON object with keys Title and Summary. Use Title: "Canvas", and '
                                        "write a single‑paragraph description (max 150 words) of its style.")),
                         ("max", 0, 195))
        self.assertEqual(self.target(fx("Develop a sales package description (≈450 words) outlining the "
                                        "playbook.")), ("about", 315, 585))
        for s in ("Write five tips (max 30 words).", "List the ideas:\n- Write a blurb (max 120 words)\n- Write a "
                  "tagline"):
            self.assertIsNone(G.word_target(fx(s)), s)  # several items, or an item of a list
        # a title's bracket is always the section's
        self.assertEqual(G.word_target(fx("Answer the questions."), "FAQ Answers (≈600 words)")["n"], [600])

    def test_plurals_after_n_word_are_items_and_a_bullet_may_give_the_whole(self):
        # real shapes: a guide's parts listed with their counts; gpt-oss's last requirements bullet giving the length
        self.assertEqual(self.target(fx("Produce the complete guide text (≈2,500 words). Include:\n- 500‑word "
                                        "Introduction\n- Three 600‑word core sections\n- 300‑word FAQ")),
                         ("about", 1750, 3250))
        for s in ("Write three 200‑word product descriptions.", "Write 4 x 250‑word posts."):
            self.assertIsNone(G.word_target(fx(s)), s)
        self.assertEqual(self.target(fx("Write the pricing section.\n- Cover the tiers.\n- Use a table.\n- Approx. 2 "
                                        "pages (≈ 900 words).")), ("about", 630, 1170))
        self.assertEqual(self.target(fx("Write the timeline.\n- Show it as a markdown table and a brief narrative. "
                                        "Aim for ~1.5 pages (≈ 600 words).\n- Mark the milestones.")),
                         ("about", 420, 780))

    def test_a_part_in_one_item_of_a_list_is_that_parts(self):
        # real: a blog step's introductory paragraph beside two tables, a memo whose second item has its own count
        for s in ("Compose:\n1. A 250‑word introductory paragraph on the plans.\n2. A pro/contra table.\n3. A cost "
                  "table.", "Create a plain‑text email containing:\n- Subject line\n- Body copy (≈150‑200 words) "
                  "introducing the batch.\n- Send time."):
            self.assertIsNone(G.word_target(fx(s)), s)
        self.assertEqual(self.target(fx("Draft the full memo (≈2,400 words) with the following sections:\n1. Title "
                                        "page\n2. Executive Summary (≈200 words)\n3. Cost Analysis")),
                         ("about", 1680, 3120))
        self.assertEqual(self.target(fx("Write ~1,000 words of page copy. Include:\n- A short paragraph (50‑80 "
                                        "words)\n- Button text (max 5 words)")), ("about", 700, 1300))
        self.assertEqual(self.target(fx("Write the note:\n- A 250‑word introductory paragraph.")),
                         ("about", 175, 325))  # a list of one
        self.assertEqual(self.target(fx("Include:\n- A 300‑word section on pricing.\n- A table.")),
                         ("about", 210, 390))  # whole: a section
        self.assertEqual(self.target(fx("Include:\n- Two subsections (≈70 words each).\n- A wrap‑up (≈150 words "
                                        "total).")), ("about", 105, 195))  # whole: a total

    def test_two_counts_and_none_for_the_whole_set_none(self):
        # a wrong band is worse than none: the check and the teacher's note would aim at a part
        for s in ("Write the Introduction (≈250 words) and Key Features (≈300 words) sections.",
                  "Write ~1,000 words of page copy. Add a short paragraph (50‑80 words) and button text."):
            self.assertIsNone(G.word_target(fx(s)), s)
        self.assertIsNone(G.word_target(fx("End with a summary paragraph of about 100 words."),
                                        "Write Current workflow audit (≈600 words)"))
        self.assertEqual(G.word_target(fx("Explain the audit."), "Write Current workflow audit (≈600 words)")
                         ["n"], [600])
        self.assertEqual(G.word_target(fx("Write about 300 words."), "Soil (≈300 words)")["n"], [300])  # one
        self.assertIsNone(G.note_band({"title": "Write Soil (≈600 words)",
                                       "instructions": fx("End with a paragraph of about 100 words.")}))


class SectionTests(unittest.TestCase):
    def test_a_plain_section_passes(self):
        got = check(section("Planting", words(40), words(30, 40)))
        self.assertEqual((got["ok"], got["reasons"], got["words"], got["target"]), (True, [], 70, None), got)

    def test_words_leave_out_the_heading_code_and_handoff(self):
        text = section("Planting", words(10), "```python\nprint('not words at all here')\n```", words(5, 10))
        self.assertEqual(G.section_check(PLAN, 1, text + HANDOFF, None, {})["words"], 15)
        self.assertEqual(G.words("## A heading\n\ndon't over-water: 10 cm, well-drained."),
                         ["don't", "over-water", "10", "cm", "well-drained"])

    def test_a_word_target_within_30_percent(self):
        plan = plan_of(("Soil", "writing", "Explain the soil."),
                       ("Planting", "writing", "Explain planting in about 100 words."))
        self.assertTrue(check(section("Planting", words(100)), plan=plan)["ok"])
        self.assertTrue(check(section("Planting", words(71)), plan=plan)["ok"])
        got = check(section("Planting", words(60)), plan=plan)
        self.assertEqual((got["reasons"], got["words"], got["target"]["low"]), (["words_under"], 60, 70))
        self.assertEqual(check(section("Planting", words(140)), plan=plan)["reasons"], ["words_over"])

    def test_a_ceiling_and_a_floor(self):
        plan = plan_of(("Soil", "writing", "x"), ("Planting", "writing", "Keep it under 50 words."))
        self.assertTrue(check(section("Planting", words(64)), plan=plan)["ok"])
        self.assertEqual(check(section("Planting", words(70)), plan=plan)["reasons"], ["words_over"])
        plan = plan_of(("Soil", "writing", "x"), ("Planting", "writing", "Write at least 100 words."))
        self.assertTrue(check(section("Planting", words(400)), plan=plan)["ok"])
        self.assertEqual(check(section("Planting", words(50)), plan=plan)["reasons"], ["words_under"])

    def test_the_validators_warnings_that_fail_a_target(self):
        text = section("Planting", words(20))
        for code in ("ai_talk", "unmarked_link", "placeholder"):
            self.assertEqual(check(text, codes=[code])["reasons"], [code], code)
        self.assertEqual(check(section("Seed spacing", words(20)), codes=["heading_not_title"])["reasons"],
                         ["heading_not_title"])
        got = check(text, codes=["handoff_long", "extra_block"])
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["warnings"], ["handoff_long", "extra_block"])

    def test_without_a_verdict_the_prototype_reads_it(self):
        text = section("Planting", "As an AI, I suggest " + words(10)) + HANDOFF
        got = G.section_check(PLAN, 1, text, None, {})
        self.assertIn("ai_talk", got["reasons"])
        self.assertEqual(G.section_check(PLAN, 1, section("Seeds", words(10)) + HANDOFF, None, {})["reasons"],
                         ["heading_not_title"])

    def test_placeholders_in_prose(self):
        for filler in ("[insert statistic here]", "TODO: finish this", "Lorem ipsum dolor", "TBD", "{{ name }}"):
            got = check(section("Planting", words(20) + " " + filler))
            self.assertEqual(got["reasons"], ["placeholder"], filler)
        self.assertTrue(check(section("Planting", words(20) + " [1]"))["ok"])

    def test_no_intro_or_outro_for_the_whole_project(self):
        got = check(section("Planting", "In this guide we look at " + words(20), words(20, 20)))
        self.assertEqual((got["reasons"], got["framing"]), (["intro"], ["In this guide"]))
        got = check(section("Planting", words(20), "In conclusion, " + words(20, 20)))
        self.assertEqual(got["reasons"], ["outro"])
        got = check(section("Planting", words(20), "This guide will " + words(5, 20), words(20, 30)))
        self.assertTrue(got["ok"], got)  # only the first and last paragraphs are looked at
        # "In summary" and its kin close a section as often as the whole, so only beside words for the whole
        got = check(section("Planting", words(20), "To summarize, this guide has " + words(20, 20)))
        self.assertEqual((got["reasons"], got["framing"]), (["outro"], ["To summarize"]))
        self.assertEqual(check(section("Planting", words(20), "In summary, the sections above " + words(9, 20)))
                         ["reasons"], ["outro"])
        got = check(section("Planting", words(20), "In summary, the licensing economics present a near-parity "
                            "scenario, so weigh render speed against these modest differences."))
        self.assertTrue(got["ok"], got)  # gpt-oss's own last paragraph in the first smoke seed: about its section

    def test_an_introduction_or_conclusion_step_may(self):
        plan = plan_of(("Introduction", "writing", "Introduce the guide."), ("Soil", "writing", "x"),
                       ("Conclusion", "writing", "Wrap up the guide."))
        self.assertTrue(check(section("Introduction", "In this guide we look at " + words(20)), 0, plan)["ok"])
        self.assertTrue(check(section("Conclusion", words(20), "In conclusion, " + words(9, 20)), 2, plan)["ok"])
        got = check(section("Introduction", words(20), "In conclusion, " + words(9, 20)), 0, plan)
        self.assertEqual(got["reasons"], ["outro"])  # an introduction still doesn't sum it all up

    def test_a_lone_or_only_section_may_frame_the_project(self):
        lone = plan_of(("Guide", "writing", "Write the guide."))
        self.assertTrue(check(section("Guide", "In this guide " + words(20)), 0, lone)["ok"])
        with_code = plan_of(("Code", "code", "Write water.py."), ("README", "writing", "Explain the tool."))
        self.assertTrue(check(section("README", "This document describes " + words(20)), 1, with_code)["ok"])

    def test_overlap_with_an_earlier_sibling(self):
        sibling = section("Soil", words(60), words(40, 60)) + HANDOFF
        copied = section("Planting", words(30, 15), words(40, 200))
        got = check(copied, earlier={"s1": sibling})
        self.assertEqual(got["reasons"], ["overlap:s1"])
        self.assertGreater(got["overlap"]["s1"], 0.2)
        fresh = section("Planting", words(60, 300), words(5, 15))
        got = check(fresh, earlier={"s1": sibling})
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["overlap"], {"s1": 0.0})

    def test_overlap_counts_shingles_of_eight(self):
        mine, theirs = G.shingles(G.words(words(20))), G.shingles(G.words(words(20, 13)))
        self.assertEqual((len(mine), len(mine & theirs)), (13, 0))  # 7 words in common: no shingle
        self.assertEqual(len(mine & G.shingles(G.words(words(20, 12)))), 1)

    def test_a_title_without_its_instruction_words(self):
        for title, bare in (("Analyse juridique des garanties", "Analyse juridique des garanties"),
                            ("Research Associate – Biotech", "Research Associate – Biotech"),
                            ("Research Los Angeles venues", "Los Angeles venues"),
                            ("Write Current workflow audit (≈600 words)", "Current workflow audit"),
                            ("Create a side‑by‑side comparison table", "Side‑by‑side comparison table"),
                            ("Research mid‑range cordless drill", "Mid‑range cordless drill"),
                            ("Draft the cover letter section", "Cover letter"),
                            ("Write up the findings [short]", "Findings"),
                            ('Write the "Executive Summary" section', "Executive Summary"),
                            ("Write 500‑word comparative guide", "500‑word comparative guide"),  # the plan named it so
                            ("Introduction", "Introduction"), ("Write", "Write"), ("Plan overview", "Plan overview")):
            self.assertEqual(G.bare_title(title), bare, title)
        self.assertEqual(G.norm_title("Side‑by‑side 8K (resolution\u202f8K)!"), "side by side 8k resolution 8k")

    def test_a_title_stays_whole_when_the_strip_is_unsure(self):
        # real: a joining word or a second verb after the strip, a noun that looks like a verb, a title not in English
        for title in ("Research and outline content", "Finalize and deliver the PDF", "Make vs Buy Analysis",
                      "Build final binary and provide build instructions", "Draft outline and gather reference data",
                      "Research Scientist – AI", "Present Day Challenges", "Research Findings", "Draft proposal",
                      "Analyse des garanties", "Rédiger le texte de la lettre", "Write la présentation"):
            self.assertEqual(G.bare_title(title), title, title)
        self.assertEqual(G.bare_title("Research Scientist – AI (≈300 words)"), "Research Scientist – AI")
        # real: a plain verb before a Title Case name, and a capitalised foreign word that starts a name
        for title, bare in (("Research Windows Developer Laptop", "Windows Developer Laptop"),
                            ("Draft Product Description", "Product Description"),
                            ("Draft Recommendation Memo (≈300 words)", "Recommendation Memo"),
                            ("Draft day‑by‑day itinerary", "Day‑by‑day itinerary"),
                            ("Research Los Angeles venues", "Los Angeles venues"),
                            ("Write Las Vegas itinerary", "Las Vegas itinerary")):
            self.assertEqual(G.bare_title(title), bare, title)
        # real: a name keeps its case; only a plain lower-case word after a stripped verb is capitalised
        for title, bare in (("Write fetchData Flow tests", "fetchData Flow tests"),
                            ("Create items.toml data file", "items.toml data file"),
                            ("macOS bundle and sample PDF", "macOS bundle and sample PDF"),
                            ("Research sub‑$300 printer", "Sub‑$300 printer")):
            self.assertEqual(G.bare_title(title), bare, title)

    def test_the_heading_the_instructions_give(self):
        given = (('Write a markdown section titled **"Budget Smartwatch"** comparing three watches.',
                  "Budget Smartwatch"),
                 ("Write a markdown section titled `## 1. Installation`. Include the comment `# install python`.",
                  "1. Installation"),
                 ('Write a ~600‑word section titled "CPU Load" that compares the plugins.', "CPU Load"),
                 ('Output the summary as plain text under the heading "Financial Highlights".',
                  "Financial Highlights"),
                 ('Produce a markdown section titled "## Introduction – why soil matters" (≈130 words).',
                  "Introduction – why soil matters"),
                 ('Start the section with the heading "Watering:" and list the days.', "Watering"),
                 ("Use a markdown list under a level‑2 heading `## How Drip Lines Work (Step‑by‑Step)`.",
                  "How Drip Lines Work (Step‑by‑Step)"),
                 ('Write the "Owner\'s Guide" section for the manual.', "Owner's Guide"),
                 ("Write the “What’s New” section.", "What’s New"),
                 ('Write a section titled "Getting Started with Node.js".', "Getting Started with Node.js"),
                 ('Write a section titled "Migrating to ASP.NET".', "Migrating to ASP.NET"),
                 ('Write the guide. Include:\n1. A setup section titled "Install".\n2. A usage part.', "Install"))
        for ins, want in given:
            self.assertEqual(G.given_heading(fx(ins)), want, ins)
            self.assertEqual(G.section_heading({"title": "Write Soil notes", "instructions": fx(ins)}), want)
            self.assertFalse(G.unread_heading({"instructions": fx(ins)}), ins)
        for ins in ('Using the "Market data" section from s1, write the pricing part.',
                    'Write the pricing part from the "Market data" section of s1.',
                    "Write the setup section titled `config.lua`. Save as config.lua.",
                    'Write a table titled "Specs" with three rows.',
                    "Return it as plain text in a Markdown code block titled `Release.md`.",
                    "Explain how to prepare the soil.",
                    # only Chimera's level: a code comment and sub-headings aren't the piece's heading
                    "Write the README usage part. It starts with `# clone the repository`.",
                    "Use `### Pros` and `### Cons`.",
                    # real: a part's heading in a later item of a step that writes the whole document
                    "Combine s1 and s2 into a single Markdown document. Include:\n1. A table of the systems.\n2. A "
                    'final recommendation section titled "Recommendation" that picks one.\nOutput the complete '
                    "Markdown text only."):
            self.assertIsNone(G.given_heading(fx(ins)), ins)
            self.assertFalse(G.unread_heading({"instructions": fx(ins)}), ins)  # no heading of its own to give
        for ins in ("Format as a Markdown heading (## Introduction) followed by the text.",
                    "Use level‑2 headings (## Soil, ## Water)."):
            self.assertTrue(G.unread_heading({"instructions": fx(ins)}), ins)
        self.assertFalse(G.unread_heading({"instructions": fx("Format each day as a sub‑heading (### Day X).")}))

    def test_a_given_heading_fits_and_the_bare_title_no_longer_does(self):
        # real: told "## Social Media Tactics" against 'titled "Social Media Promotion"', which Go warns on
        step = {"title": "Social Tactics (Part 1)",
                "instructions": fx('Write an 800‑word section titled "Social Promotion".')}
        self.assertTrue(G.heading_fits("Social Promotion", step))
        self.assertTrue(G.heading_fits("Social Tactics (Part 1)", step))  # the title always does
        self.assertFalse(G.heading_fits("Social Tactics", step))
        self.assertTrue(G.heading_fits("Social Tactics", {"title": "Social Tactics (Part 1)", "instructions": "x"}))
        self.assertTrue(G.heading_fits("Research Scientist – AI", {"title": "Research Scientist – AI"}))
        self.assertFalse(G.heading_fits("Scientist – AI", {"title": "Research Scientist – AI"}))
        # real: a given heading that shares no word with the title may name a part, so the bare title still fits
        memo = {"title": "Draft Recommendation Memo",
                "instructions": fx('Write a 3‑page recommendation memo titled "Backpack 2024 Marketing Strategy".')}
        for heading in ("Backpack 2024 Marketing Strategy", "Recommendation Memo", "Draft Recommendation Memo"):
            self.assertTrue(G.heading_fits(heading, memo), heading)
        doc = {"title": "Create Markdown comparison document",
               "instructions": fx("Produce a single Markdown document. Include:\n1. A table.\n2. A final section "
                                  'titled "Recommendation".')}
        self.assertTrue(G.heading_fits("Markdown comparison document", doc))
        self.assertFalse(G.heading_fits("Recommendation", doc))  # a part's, not the piece's
        # real: a heading cue the reader can't read: the title and the bare title both fit
        cue = {"title": "Craft Tagline", "instructions": fx("Return the tagline as a markdown heading (e.g., "
                                                            "`# <tagline>`).")}
        self.assertTrue(G.unread_heading(cue))
        self.assertEqual(G.section_heading(cue), "Tagline")
        for heading in ("Tagline", "Craft Tagline"):
            self.assertTrue(G.heading_fits(heading, cue), heading)

    def test_a_heading_go_doesnt_warn_on_still_has_to_fit(self):
        # real: Go's substring test passes an empty heading, "***" and part of a word
        plan = plan_of(("Soil", "writing", "x"),
                       ("Write License cost breakdown", "writing", fx("Present the breakdown in a table.")))
        for heading in ("", "***", "ent the break"):
            got = check(section(heading, words(20)), i=1, plan=plan)
            self.assertEqual(got["reasons"], ["heading_not_title"], repr(heading))
            self.assertFalse(got["bare_heading"])
        for heading in ("License cost breakdown", "Write License cost breakdown", "Table", "The breakdown"):
            self.assertTrue(check(section(heading, words(20)), i=1, plan=plan)["ok"], heading)

    def test_a_heading_that_fits_the_bare_title_passes(self):
        # Chimera's validator warns on any heading but the exact title or a part of the instructions; a target may
        # also carry the bare title, in any case and with or without articles, or the name the instructions quote.
        plan = plan_of(("Write Soil preparation (about 30 words)", "writing", "Explain how to prepare the soil."),
                       ("Write License cost breakdown for team of 5 (≈30 words)", "writing", "Add up the costs."),
                       ("Watering plan", "writing", 'Write the "How much to water" section.'))
        for i, heading in ((0, "Soil Preparation"), (1, "License Cost Breakdown for a Team of 5"),
                           (2, "How much to water")):
            got = check(section(heading, words(30)), i=i, plan=plan, codes=["heading_not_title"])
            self.assertTrue(got["ok"], (heading, got))
            self.assertTrue(got["bare_heading"])
            self.assertEqual(got["heading"], heading)
        for i, heading in ((0, "Preparing your soil"), (1, "Costs"), (2, "Watering")):
            got = check(section(heading, words(30)), i=i, plan=plan, codes=["heading_not_title"])
            self.assertEqual(got["reasons"], ["heading_not_title"], heading)
        self.assertTrue(check(section("Planting", words(20)))["ok"])  # no warning, nothing to excuse
        self.assertEqual(G.section_heading(plan["steps"][2]), "How much to water")  # the quoted name first
        self.assertEqual(G.section_heading(plan["steps"][1]), "License cost breakdown for team of 5")

    def test_the_teachers_band_is_inside_the_checks(self):
        st = lambda ins: {"title": "Soil", "instructions": ins}  # noqa: E731
        # aimed below the target (gpt-oss overshoots), never outside what the check allows
        self.assertEqual(G.note_band(st("Write about 600 words.")), (450, 540))
        self.assertEqual(G.note_band(st("Write 200-400 words.")), (150, 360))
        self.assertEqual(G.note_band(st("Keep it under 150 words.")), (0, 128))
        self.assertEqual(G.note_band(st("Write at least 500 words.")), (500, None))
        self.assertEqual(G.note_band(st("Write 10-11 words.")), (8, 10))
        self.assertIsNone(G.note_band(st("Explain the soil.")))
        self.assertEqual(G.note_band({"title": "Write Soil (≈300 words)", "instructions": "Explain."}), (225, 270))
        for ins in ("Write about 600 words.", "Write 200-400 words.", "Keep it under 150 words."):
            t, (lo, hi) = G.word_target(ins), G.note_band(st(ins))
            self.assertTrue(t["low"] <= lo and hi <= t["high"], ins)

    def test_which_ends_are_checked(self):
        self.assertEqual(G.framing_checks(PLAN, 1), ["intro", "outro"])
        intro = plan_of(("Introduction", "writing", "Introduce the guide."), ("Planting", "writing", "Explain."))
        self.assertEqual(G.framing_checks(intro, 0), ["outro"])
        self.assertEqual(G.framing_checks(plan_of(("Note", "writing", "Write a note.")), 0), [])

    def test_a_step_that_asks_for_its_own_framing(self):
        # real: a full-article step whose points ask for an introduction and a conclusion, after two research steps
        article = fx("Compose a beginner‑friendly article (≈800‑1000 words) that:\n1. Introduces why the right "
                     "camera matters.\n2. Presents the table from s2.\n3. Concludes with a short tip on next steps.")
        plan = plan_of(("Research camera specs", "research", fx("List the specs as JSON.")),
                       ("Build comparison table", "writing", fx("Make a markdown table.")),
                       ("Write the full explainer article", "writing", article))
        self.assertEqual(G.framing_checks(plan, 2), [])
        got = check(section("Full explainer article", "In this article we look at " + words(400),
                            "In conclusion, " + words(400, 400)), i=2, plan=plan)
        self.assertEqual((got["ok"], got["framing"]), (True, []), got)
        asks = plan_of(("Soil", "writing", fx("Explain.")),
                       ("Planting", "writing", fx("Open with a short opening paragraph, then explain.")),
                       ("Watering", "writing", fx("Explain it, then add a closing paragraph.")))
        self.assertEqual((G.framing_checks(asks, 1), G.framing_checks(asks, 2)), (["outro"], ["intro"]))
        for title in ("Draft Recommendation Memo", "Write the complete guide", "Write all sections"):
            self.assertEqual(G.framing_checks(plan_of(("Soil", "writing", "x"), (title, "writing", "x")), 1), [],
                             title)

    def test_the_memo_seed_keeps_its_framing_checks(self):
        # real: smoke seed research_draft-0007-04, its titles; the instructions are short fixtures
        memo = plan_of(("Draft outline and gather reference data", "research", fx("Outline the memo as JSON.")),
                       ("Write Current workflow audit (≈600 words)", "writing",
                        fx('Write the "Current workflow audit" section. Format as plain text with markdown headings.')),
                       ("Write Side‑by‑side 8K render quality comparison (≈600 words)", "writing",
                        fx('Compose the "Side‑by‑side render quality comparison (resolution 8K)" section.')),
                       ("Write License cost breakdown for team of 5 (≈400 words)", "writing",
                        fx("Present the breakdown in a clear table and give a short analysis.")),
                       ("Write Recommendation and migration timeline (≈300 words)", "writing",
                        fx("Craft a concise recommendation and a phased migration timeline.")))
        for k in range(5):
            self.assertEqual(G.framing_checks(memo, k), ["intro", "outro"], k)
            self.assertFalse(G.framed_elsewhere(memo, k, ("intro", "outro")))
        self.assertEqual([G.section_heading(st) for st in memo["steps"]],
                         ["Draft outline and gather reference data", "Current workflow audit",
                          "Side‑by‑side render quality comparison (resolution 8K)",
                          "License cost breakdown for team of 5", "Recommendation and migration timeline"])
        intro = plan_of(("Introduction", "writing", "x"), ("Soil", "writing", "x"))
        self.assertTrue(G.framed_elsewhere(intro, 1, ("intro", "outro")))
        self.assertFalse(G.framed_elsewhere(intro, 1, ("outro",)))

    def test_not_a_section(self):
        got = G.section_check(PLAN, 1, "x", {"mode": "files", "issues": [], "section": "", "body": "x"}, {})
        self.assertIn("not_section", got["reasons"])


class ClaimTests(unittest.TestCase):
    def claims(self, *paras):
        return G.source_claims(section("Planting", *paras))

    def test_tests_and_measurements_it_never_ran(self):
        # real: smoke seed research_draft-0007-04's s3, written with its research step failed (U+202F, U+2011 kept)
        got = check(section("Planting", "Tests were run on an identical workstation (two GPUs, 64 GB RAM). "
                            "Measured noise levels (average per‑pixel variance) were 0.0018 % for one bed and "
                            "0.0021 % for the other.", words(20)))
        self.assertEqual((got["ok"], got["reasons"]), (False, ["claims_source"]))
        self.assertEqual(got["claims"], ["Tests were run",
                                         "Measured noise levels (average per-pixel variance) were 0.0018"])
        for text, phrase in (
                ("To compare them we ran an identical benchmark scene of 2 M polygons.",
                 "we ran an identical benchmark"),
                ("Both renderers were tested on the same workstation.", "were tested on the same"),
                ("Both were evaluated on the same machine, with matched settings.", "were evaluated on the same"),
                ("The comparison draws on a controlled benchmark that rendered one scene.",
                 "a controlled benchmark that rendered"),
                ("| Residual noise | 0.78 % (measured by NIQE) | 0.52 % |", "(measured by"),
                ("Subtle colour shifts were measured at < 0.2 % ΔE.", "were measured at"),
                ("Overall, the side-by-side benchmark indicates a clear lead.", "benchmark indicates"),
                ("Recent benchmarks show a 12 % gain.", "benchmarks show"),
                ("Our tests show the clay holds water longer.", "Our tests show"),
                ("In our testing the beds drained in a day.", "In our testing"),
                ("We surveyed 200 gardeners last spring.", "We surveyed"),
                ("Testing was carried out over three weeks.", "Testing was carried out")):
            self.assertEqual(self.claims(text), [phrase], text)

    def test_sources_it_never_read(self):
        # real: research_draft-0007-04's s4: prices "taken from" a vendor's site and "publicly listed"
        got = self.claims("Both sell a seat at roughly $495 a year. This figure was taken from the publicly listed "
                          "subscription rates on each company’s website (2024 pricing).")
        self.assertEqual(got, ["figure was taken from", "publicly listed subscription rates"])
        for text, phrase in (
                ("Prices were sourced from the manufacturer's catalogue.", "Prices were sourced from"),
                ("All figures taken from the official price list.", "figures taken from the official"),
                ("The rates come from the vendor's website.", "from the vendor's website"),
                ("According to the 2024 market report, sales rose 8 %.", "According to the 2024 market report"),
                ("Sales rose 8 %, according to industry analysts.", "according to industry analysts"),
                ("According to Gartner, the market doubled.", "According to Gartner"),
                ("- **According to the vendor**, it ships in May.", "According to the vendor")):
            self.assertEqual(self.claims(text), [phrase], text)

    def test_what_isnt_a_claim(self):
        for text in (
                # marked (not a run: test_a_mark_never_clears_a_run), or a condition
                "Assumed: prices were taken from each vendor's 2024 list.",
                "Measured noise levels were 0.002 % (an assumption for this comparison).",
                "Re-run the comparison if benchmarks show a gap.",
                # the request's own sources, or what a program reads
                "These figures were taken from the provided CSV.",
                "The data was taken from s1's outline.",
                "Default values were taken from `config.yaml`.",
                "Data is pulled from the Sheets API every hour.",
                "Prices were pulled from the database at start-up.",
                # not provenance
                "All parts should be sourced from OEM-approved suppliers.",
                "A license is taken from the pool, so the farm stalls.",
                "Download Blender from the official website.",
                "Use equipment according to manufacturer instructions.",
                "Prices vary according to the season.",
                "Large publicly listed companies report quarterly.",
                "A measured, phased rollout was chosen.",
                "Distances were measured in kilometres.",
                "Her patience was tested by the long wait.",
                "We tested the ice before crossing the lake.",
                "Add a case in our tests folder.",
                "Run the `tests were run` check and `we measured` nothing."):
            self.assertEqual(self.claims(text), [], text)
        self.assertEqual(G.source_claims(section("Planting", words(10), "```text\nTests were run on it.\n```")), [])
        got = G.section_check(PLAN, 1, section("Planting", words(20)) + "\n\n```handoff\nprovides: the section\nuses: "
                              "none\nassumed: prices were taken from each vendor's website\n```", None, {})
        self.assertNotIn("claims_source", got["reasons"])  # the handoff isn't the text

    def test_more_shapes_of_an_invented_source_test_or_result(self):
        # real: three of the smoke's sections written with their research step failed passed the first patterns
        # ("based on the latest vendor catalogues", "observed in the benchmark", "In the 8K test ... (subjective score
        # based on a panel of senior artists)"); the rest are the rewordings a teacher could reach for
        for text, phrase in (
                ("Seed prices are per packet and based on the latest supplier catalogues.",
                 "based on the latest supplier catalogues"),
                ("Costs are based on each supplier's 2025 price list.", "based on each supplier's 2025 price"),
                ("Based on our testing, the raised bed drains faster.", "Based on our testing"),
                ("The small edge observed in the trial (about 8 % more yield) settles it.", "observed in the trial"),
                ("In the 4K test the photos showed every leaf.", "In the 4K test"),
                ("In side-by-side test renders of the bed, the mulch looked darker.", "In side-by-side test renders"),
                ("It scored 7/10 (rated by a panel of local growers).", "a panel of local growers"),
                ("Research shows that mulch keeps soil 3 °C cooler.", "Research shows"),
                ("Many gardeners mulch, and surveys indicate 60 % of them use straw.", "surveys indicate"),
                ("Industry data suggests that 40 % of plots are raised.", "Industry data suggests"),
                ("A 2022 study found that kale tolerates frost.", "A 2022 study found"),
                ("The latest RHS members survey reports that 55 % grow tomatoes.",
                 "The latest RHS members survey reports"),
                ("Per Suttons' published pricing, a packet costs £2.", "Per Suttons' published pricing"),
                ("Source: Suttons price page, 2025.", "Source: Suttons price page, 2025"),
                ("A packet costs £2.49 (Suttons pricing, 2025).", "(Suttons pricing, 2025)"),
                ("Our trial produced 4 kg in the first month.", "Our trial produced"),
                ("We found that yields rose 20 % with compost.", "We found"),
                ("Supplier quotes put the total at £340.", "Supplier quotes put"),
                ("Soil moisture fell from 40 % to 22 %, as logged by the sensors.", "as logged by the sensors")):
            self.assertEqual(self.claims(fx(text)), [phrase], text)

    def test_what_still_isnt_a_claim(self):
        for text in (
                # a denial, which is what the tell asks for, and advice
                "No trials were run for this guide, so yields aren't given.",
                "We ran no tests, so the yields below are only estimates.",
                "Update the prices based on the latest supplier list each spring.",
                # everyday "based on", "found" without a number, a test environment, a report that a program writes
                "Water based on how dry the top inch feels.",
                "Adjust the plan based on the root-cause hypothesis.",
                "We found the spot that gets the most sun.",
                "Run it in a test environment first.",
                "The weekly report shows each bed's total.",
                "Source code lives in the repo.",
                "A solar panel of 400 W runs the pump."):
            self.assertEqual(self.claims(fx(text)), [], text)

    def test_a_mark_must_qualify_the_claim(self):
        for text in ("Yields were measured at 2 kg a bed (unverified).", "Prices were taken from each supplier's list "
                     "(assumed).", "Assumed: prices were taken from each supplier's list.",
                     "**Assumption** – prices were taken from each supplier's list.",
                     "That prices were taken from each supplier's list is an assumption.",
                     "Prices were taken from each supplier's list, as an assumed estimate.",
                     "Readings were measured at 15-minute intervals [assumed for this guide]."):
            self.assertEqual(self.claims(fx(text)), [], text)
        # real: a plain "assuming ..." cleared a sentence that claimed each company's website
        self.assertEqual(self.claims(fx("Assuming a two-bed plot, prices were taken from each supplier's website.")),
                         ["prices were taken from"])

    def test_a_mark_never_clears_a_run(self):
        # A research step's tell once said "mark anything uncertain (unverified)", and a next try could keep "Tests were
        # run on an identical workstation" with the mark added: no mark makes a run true.
        for text, phrase in (
                ("Tests were run on an identical workstation (unverified).", "Tests were run"),
                ("Trials were run on two plots (unverified).", "Trials were run"),
                ("We ran a trial of both mulches (unverified), and straw won.", "We ran a trial"),
                ("Our tests show the clay holds water longer (unverified).", "Our tests show"),
                ("We tested five hoses (assumed figures): the green one lasted 4 years.", "We tested"),
                ("Assumed: trials were run on two plots.", "trials were run")):
            self.assertEqual(self.claims(fx(text)), [phrase], text)
        # ... while a mark still qualifies a result, a measurement or a source
        for text in ("Benchmarks show a 12 % gain (unverified).", "Measurements were taken every hour (unverified).",
                     "Yields were measured at 2 kg a bed (assumed).", "Prices were taken from each supplier's list "
                     "(unverified)."):
            self.assertEqual(self.claims(fx(text)), [], text)

    def test_how_to_and_event_prose_isnt_a_claim(self):
        # The shapes that invented claims took, said where a how-to, a plan or an event programme says them: an
        # instruction "per" the maker's specs, a panel or a taste test still to come, advice experts give, "based on"
        # something that is no data, a place in an app's settings.
        for text in (
                "Torque the wheel nuts per the manufacturer's specifications.",
                "Install the drip line per the official documentation.",
                "Configure the timer per the vendor's documentation before the first run.",
                "Per the supplier's published specs, set the pump to 2 bar.",
                "A panel of three judges will score each entry in the show.",
                "The fair closes with a panel of local growers on compost.",
                "The vegetable show is judged by a panel of three local chefs.",
                "In a blind taste test, visitors will compare the two tomatoes and vote.",
                "Most experts suggest watering early in the morning.",
                "The route is based on public transport between the towns.",
                "Times are based on the 2025 summer timetable, so check them first.",
                "The lesson is based on the official curriculum for plants.",
                "The schedule is based on the manufacturer's recommendations.",
                "In the 4K render settings, set the samples to 256."):
            self.assertEqual(self.claims(fx(text)), [], text)
        # ... and the same shapes where they claim a result or cite a source
        for text, phrase in (
                ("In a blind taste test, 7 of 10 visitors preferred the yellow tomato.", "In a blind taste test"),
                ("It was rated 8/10 by a panel of local growers.", "a panel of local growers"),
                ("Experts suggested that raised beds drain faster.", "Experts suggested"),
                ("Experts estimate that 40 % of plots are raised.", "Experts estimate"),
                ("A packet costs £2, per the supplier's published pricing.", "per the supplier's published pricing"),
                ("Costs are based on official 2025 figures.", "based on official 2025 figures"),
                ("In the 4K test the photos showed every leaf.", "In the 4K test")):
            self.assertEqual(self.claims(fx(text)), [phrase], text)

    def test_a_mark_never_clears_a_first_person_measurement_or_survey(self):
        # Chimera measures, surveys and interviews nothing for a section: "We surveyed 40 artists (unverified)" is
        # never true, and the research tell once steered a next try to add the mark (r2-prose-1's failure moved from
        # runs to measurements). In a research step and a writing step alike.
        for kind in ("research", "writing"):
            plan = plan_of(("Soil", "writing", "Explain how to prepare the soil."),
                           ("Planting", kind, "Find out when to plant."))
            for text, phrase in (
                    ("We surveyed 40 gardeners (unverified): 70 % sow in April.", "We surveyed"),
                    ("We measured 3 of the 8 beds waterlogged (unverified).", "We measured"),
                    ("We interviewed 12 growers (assumed), and most use straw.", "We interviewed"),
                    ("We recorded soil temperatures of 11 C and 14 C (unverified).", "We recorded"),
                    ("We polled 300 allotment holders (unverified): 64 % mulch.", "We polled"),
                    ("I observed 4 of 10 seedlings wilting (assumed).", "I observed"),
                    ("We found that 3 of 5 beds drain slowly (assumed figures).", "We found")):
                got = G.section_check(plan, 1, section("Planting", fx(text)), None, {})
                self.assertEqual(got["claims"], [phrase], (kind, text))
            # ... while a mark still qualifies a measurement nobody says they took
            for text in ("Measurements were taken every hour (unverified).",
                         "Yields were measured at 2 kg a bed (assumed)."):
                self.assertEqual(G.section_check(plan, 1, section("Planting", fx(text)), None, {})["claims"], [],
                                 (kind, text))
        # the person's own "we measured", restated, is still their data
        plan = plan_of(("Readings", "writing", fx("Write up our readings: we measured 11.2 C at 09:00 and 17.5 C at "
                                                  "09:30.")), ("Advice", "writing", "Say what to do next."))
        got = G.section_check(plan, 0, section("Readings", fx("We measured 11.2 C at 09:00 (unverified).")), None, {})
        self.assertEqual((got["claims"], got["claims_given"]), ([], ["We measured"]))

    def test_present_tense_results_that_compare(self):
        # A comparison section writes invented results in the present tense: a soft shape with nothing still to come
        # counts when it compares what it names (than, ahead of, outperforms, a majority that prefers, a quality's
        # comparative), as a score does
        for text, phrase in (
                ("In the 4K test, Bed A shows finer root growth than Bed B.", "In the 4K test"),
                ("In side-by-side test renders, the Kale bed shows more noise in the shadows.",
                 "In side-by-side test renders"),
                ("In a blind comparison test, most growers prefer Suttons' seed.", "In a blind comparison test"),
                ("A panel of senior growers rates Suttons' seed higher.", "A panel of senior growers"),
                ("In head-to-head trials, Suttons' kale sprouts sooner.", "In head-to-head trials"),
                ("In controlled tests, Bed A uses less memory on the logger.", "In controlled tests"),
                ("In the blind comparison test, 7 of 10 growers favour Suttons.", "In the blind comparison test"),
                ("A panel of senior growers ranks Suttons ahead of Thompson.", "A panel of senior growers"),
                ("In side-by-side tests, Bed A scores 8.3/10 for yield.", "In side-by-side tests")):
            self.assertEqual(self.claims(fx(text)), [phrase], text)
        # ... not a question it leaves open, a comparison that names nothing, "more than 20", "rather than", a
        # purpose ("for better yields"), or one still to come
        for text in ("In a side-by-side test, pupils check which soil drains better.",
                     "In a blind taste test, visitors choose the tomato they like better.",
                     "A panel of more than 20 growers judges the show.",
                     "A panel of chefs talks about cooking with less salt rather than more.",
                     "A panel of growers shares tips for better yields.",
                     "A panel of judges picks the better marrow in each round.",
                     "In a side-by-side test bake, you'll see the Suttons loaf rise higher."):
            self.assertEqual(self.claims(fx(text)), [], text)

    def test_analysts_and_experts(self):
        # Analysts are a source, as industry data is; experts who estimate, report, indicate, find or show are too;
        # experts' advice is how-to prose (round 2 fired on "Most experts suggest watering early")
        for text, phrase in (
                ("Analysts estimate the raised-bed market will reach $1.2 billion by 2028.", "Analysts estimate"),
                ("Industry analysts estimate that 40 % of growers will mulch by 2027.", "Industry analysts estimate"),
                ("Analysts report strong demand for peat-free compost.", "Analysts report"),
                ("Market analysts suggest garden centres should stock more seed.", "Market analysts suggest"),
                ("Analysts expect seed sales to double by 2030.", "Analysts expect"),
                ("Experts indicate that buyers now expect peat-free compost.", "Experts indicate"),
                ("Experts find that growers compare yields first.", "Experts find")):
            self.assertEqual(self.claims(fx(text)), [phrase], text)
        for text in ("Experts suggest watering the seedlings before a hot day.",
                     "Experts recommend arriving early for the guided tour.",
                     "Experts advise sowing kale after the last frost.",
                     "Junior analysts report to the head of research."):
            self.assertEqual(self.claims(fx(text)), [], text)

    def test_an_adjective_in_ed_isnt_a_verb_in_the_past(self):
        # Event and lesson prose describes with -ed words after a preposition, "and", a wh-word or a verb; read as past
        # verbs, they failed the panel or the taste test the person asked for (r2-prose-3, round 3's leftover)
        for text in ("A panel of experts compares sourdough with yeasted bread in the afternoon talk.",
                     "The day closes with a panel of chefs on fermented foods.",
                     "A panel of growers talks about raised beds and mulch.",
                     "A panel of experts discusses recycled packaging for plant pots.",
                     "On Sunday, a panel of farmers explains how cured meats are made.",
                     "In a blind taste test of smoked and unsmoked cheese, visitors vote for a favourite.",
                     "Experts suggest using labelled diagrams for younger pupils.",
                     "Most experts suggest booking tickets for guided tastings early.",
                     "A panel of designers presents recycled and upcycled planters.",
                     "A panel of experts focused on soil health talks about compost.",
                     "In a side-by-side test, pupils measure how far each seed travelled."):
            self.assertEqual(self.claims(fx(text)), [], text)
        # ... while a verb after its subject, a pronoun or a name, or before what it did, still says a result came out
        for text, phrase in (
                ("A panel of five growers preferred the Suttons kale.", "A panel of five growers"),
                ("In a blind test, the judges tasted and rated each marrow.", "In a blind test"),
                ("In the 4K test it reproduced every leaf.", "In the 4K test"),
                ("In the 4K test, the kale bed looked noticeably greener.", "In the 4K test")):
            self.assertEqual(self.claims(fx(text)), [phrase], text)

    def test_market_and_research_sources_in_the_shapes_gpt_oss_writes(self):
        # real: gpt-oss:120b's research_draft results for the helper's night seeds cite firms, surveys and studies it
        # never had, in brackets, in a survey table's heading line and in a Sources column (rewritten here for a
        # garden centre); none matched a pattern before the fourth check (round 4's mend)
        for text, phrase in (
                ("The peat-free compost market will reach £2.1 bn by 2027 (Grand View Research).",
                 "(Grand View Research)"),
                ("Some 78 % of new growers say they pay more for peat-free compost (Nielsen 2023).", "(Nielsen 2023)"),
                ("Raised beds reach 68 % of the target market (per Nielsen).", "(per Nielsen)"),
                ("Mulched beds hold 20 % more water (Puget Systems, 2024).", "(Puget Systems, 2024)"),
                ("Short watering spells save 15 % of water (Smith et al., 2021).", "(Smith et al., 2021)"),
                ("Statista reports that 62 % of allotment holders buy seed online.", "Statista reports"),
                ("Mordor Intelligence estimates the seed market at $4 billion.", "Mordor Intelligence estimates"),
                ("| Seed spend per plot | £45 | RHS Gardening Survey 2025 |", "RHS Gardening Survey 2025"),
                ("Allotment Barometer 2024 data points the same way.", "Allotment Barometer 2024"),
                ("Studies have shown that mulch keeps soil cooler.", "Studies have shown"),
                ("Studies consistently show that raised beds drain faster.", "Studies consistently show"),
                ("Recent research by Kew suggests that clover feeds the soil.", "Recent research by Kew suggests"),
                ("Data from the Allotment Association shows 40 % growth since 2019.",
                 "Data from the Allotment Association shows"),
                ("Industry figures put the raised-bed market at $1.2 billion.", "Industry figures put"),
                ("A survey of 2,000 growers found that 40 % mulch.", "A survey of 2,000 growers found"),
                ("Nearly 70 % of respondents said they water in the evening.", "70 % of respondents"),
                ("Respondents cited slugs as the main pest.", "Respondents cited"),
                ("62 % of growers surveyed prefer straw.", "growers surveyed"),
                ("Plot sentiment (Survey - n=1,200, UK only) is upbeat.", "- n=1"),
                ("In a 2024 poll of 500 growers, 62 % preferred straw.", "In a 2024 poll of"),
                ("Analysts say the raised-bed market will double by 2028.", "Analysts say"),
                ("Market researchers estimate the market will reach $1.2 billion by 2028.",
                 "Market researchers estimate"),
                ("Experts warn that cheap hoses split within a year.", "Experts warn"),
                ("Suttons' website lists the packet at £2.49.", "Suttons' website lists"),
                ("As listed on Suttons' website, a packet costs £2.49.", "As listed on Suttons' website"),
                ("Suttons' published pricing puts kale at £2.49 a packet.", "Suttons' published pricing puts"),
                ("Per a 2024 RHS Members survey, 55 % grow tomatoes.", "Per a 2024 RHS Members survey")):
            self.assertEqual(self.claims(fx(text)), [phrase], text)
        # a citation outside the sentences' own words: a Sources list, a footnote, a table's Source column
        for paras, phrase in (
                (("Mulch keeps beds 3 °C cooler.", "**Sources**", "- Grow Well Trust, *Mulch trials*, 2024\n"
                  "- Seed firm price page, accessed March 2025"),
                 ["Grow Well Trust, Mulch trials, 2024", "Seed firm price page, accessed March 2025"]),
                (("Mulch keeps beds 3 °C cooler [1].", "[1] Grow Well Trust, Mulch trials, 2024."),
                 ["Grow Well Trust, Mulch trials, 2024."]),
                (("| Bed | Water saved | Source |\n|---|---|---|\n| Straw | 20 % | Grow Well Trust trial, 2024 |",),
                 ["Grow Well Trust trial, 2024"])):
            self.assertEqual(self.claims(*paras, fx("")), phrase, paras)
        # ... not a unit's "(Per Plot)", an atom count's "(N=250)", the year of an event with no figure, a mapping
        # table's Source column, further reading, or the request's own source
        for paras in (("### Costs (Per Plot)", "Seed costs £2 a packet."),
                      ("Simulate 250 argon atoms (N=250) for 500 steps.",),
                      ("The flower show (Chelsea, 2024) had a rose theme.",),
                      ("| Source | Target |\n|---|---|\n| seeds.csv | the order sheet |",),
                      ("**Further reading**", "- Grow Well Trust, *Mulch trials*, 2024"),
                      ("**Sources**", "- the brief", "- the provided CSV")):
            self.assertEqual(self.claims(*paras, fx("")), [], paras)

    def test_test_and_benchmark_result_shapes(self):
        # real: the smoke's s3 sections were caught by one or two phrases each, and a next try that phrased the run
        # another way passed: "In our assumed tests", "in the assumed benchmark", "The following evaluation pits ...
        # using a standardized 8 K (7680 × 4320) test scene" (the stored sentences), and the common shapes
        for text, phrase in (
                ("In our assumed tests, straw kept 4.5 / 5 of the moisture.", "In our assumed tests"),
                ("In our side-by-side tests, straw was 17 % better.", "In our side-by-side tests"),
                ("Straw holds 3 % more water in the assumed benchmark (48 % vs 45 %).", "in the assumed benchmark"),
                ("Tests show straw beats bark at 30 °C.", "Tests show"),
                ("Testing revealed that bark dries the soil.", "Testing revealed"),
                ("Independent trials have shown that clover feeds the soil.", "Independent trials have shown"),
                ("Third-party benchmarks put straw ahead of bark.", "benchmarks put"),
                ("The benchmark found straw 12 % better than bark.", "benchmark found"),
                ("A blind test found that 7 of 10 growers preferred straw.", "A blind test found"),
                ("The side-by-side test showed that straw holds more water.", "The side-by-side test showed"),
                ("The test renders showed more weeds under bark.", "The test renders showed"),
                ("When tested on a clay bed, straw lasted 3 days longer.", "When tested on"),
                ("We benchmarked both hoses, and the green one came out ahead.", "We benchmarked"),
                ("We tested both mulches on the same bed, and straw did better.", "We tested both"),
                ("We surveyed the club, and most members prefer straw.", "We surveyed"),
                ("Measured soil temperatures favour straw on every bed.", "Measured soil temperatures favour"),
                ("The following evaluation pits straw against bark using a standard (2 m × 1 m) test bed setup.",
                 "evaluation pits straw against bark using a standard (2 m × 1 m) test bed setup")):
            self.assertEqual(self.claims(fx(text)), [phrase], text)
        # ... not a code README's unit tests, a how-to's test with a meter, a comparison that describes the section
        for text in ("In our unit tests, the parser reads each bed's row.",
                     "When tested with a meter, a healthy battery reads 12.6 V.",
                     "This comparison shows how the two mulches differ.",
                     "Compare straw with bark using the club's test bed.",
                     "We tested the ice before crossing the lake."):
            self.assertEqual(self.claims(fx(text)), [], text)

    def test_a_mark_qualifies_its_own_clause(self):
        # A mark anywhere in a sentence once cleared every claim in it; it qualifies its own clause, and a label for
        # the whole sentence ("Assumed: ...") all of it
        self.assertEqual(self.claims(fx("Kale costs £2 a packet (assumed), and benchmarks show it grows 12 % faster.")),
                         ["benchmarks show"])
        for text in ("Benchmarks show kale grows 12 % faster (assumed), and it costs £2.",
                     "Assumed: benchmarks show kale grows 12 % faster; it costs £2."):
            self.assertEqual(self.claims(fx(text)), [], text)
        # ... and "It's no secret that ..." denies nothing
        for text, phrase in (("It's no secret that surveys indicate most growers mulch.", "surveys indicate"),
                             ("There is no question that research shows mulch helps.", "research shows")):
            self.assertEqual(self.claims(fx(text)), [phrase], text)

    def test_present_and_past_results_of_a_panel_or_a_test(self):
        # round 4's -ed rule read a verb after a plural subject and before a plain noun as an adjective: an -ed word
        # right after a plural noun for people is their verb; and a result in the present tense counts with no
        # comparison where a name wins, leads, handles or struggles, or a panel picks a name
        for text, phrase in (
                ("In a blind test, growers preferred kale from Suttons.", "In a blind test"),
                ("In side-by-side test renders, reviewers flagged mildew in Bed B.", "In side-by-side test renders"),
                ("A panel of senior growers praised the leaves in Bed A.", "A panel of senior growers"),
                ("In the 4K test, Bed A clearly wins on colour.", "In the 4K test"),
                ("A panel of senior growers picks Suttons every time.", "A panel of senior growers"),
                ("In a blind comparison test, Suttons' kale is the clear favourite.", "In a blind comparison test"),
                ("In controlled tests, Bed B struggles with slugs.", "In controlled tests"),
                ("In side-by-side tests, the Suttons kale looks more convincing.", "In side-by-side tests")):
            self.assertEqual(self.claims(fx(text)), [phrase], text)
        # ... not an event's present tense, a verb in a clause about someone, the object of a preposition or a
        # noun's own -ed word
        for text in ("A panel of three judges picks the Best in Show at 4 pm.",
                     "A panel of chefs, including Tom Kerridge, who opened The Hand and Flowers in 2005, judges the "
                     "final.",
                     "A panel of local growers, all of whom exhibited at Malvern last year, judges the marrows.",
                     "In the blind taste test, each visitor tastes the Victoria sponges and marks the one they enjoyed "
                     "most.",
                     "In a controlled test, pupils record the distance the car travelled on each surface.",
                     "Most experts recommend a lower pressure than the maximum printed on the Schwalbe sidewall."):
            self.assertEqual(self.claims(fx(text)), [], text)

    def test_analysts_and_experts_who_say_nothing_came_out(self):
        # Analysts and experts are a source only where what they say came out follows them (a that-clause, a market
        # figure, a forecast, a trend): event programmes and process memos have experts demonstrate and analysts
        # estimate tickets (round 4 failed them, as round 2 did)
        for text in ("At 11:00 in the marquee, experts demonstrate how to shape a sourdough boule.",
                     "In the afternoon session, experts show visitors how to prune apple trees.",
                     "Bring your old tools along, and experts estimate their value on the spot.",
                     "During Monday planning, analysts estimate each ticket in story points.",
                     "Each Friday, analysts show the dashboard to the sales leads.",
                     "Analysts forecast next month's demand from the CRM pipeline.",
                     "Experts estimate the full loop takes two to three hours."):
            self.assertEqual(self.claims(fx(text)), [], text)
        for text, phrase in (("Analysts forecast that seed sales will double by 2030.", "Analysts forecast"),
                             ("Experts estimate 40 % of plots are raised.", "Experts estimate"),
                             ("Analysts report rising demand for peat-free compost.", "Analysts report")):
            self.assertEqual(self.claims(fx(text)), [phrase], text)

    def test_comparisons_in_how_to_event_and_travel_prose_are_no_results(self):
        # The comparison rule (round 4) read ordinary prose as results: "than" before a number of two digits or more,
        # "behind" a place, a test render followed by what to do, experts' advice that compares, and a comparison in a
        # clause about what something is called
        for text in ("In the blind taste test, visitors sample more than 12 cheeses from Neal's Yard.",
                     "In the blind taste test, entries aged longer than 12 months go first.",
                     "In a controlled test, each group moves the torch more than 30 cm from the Lego figure.",
                     "A panel of chefs meets in the marquee behind Ludlow Castle.",
                     "In the test render, make the Rim light brighter than the Key so the edge reads.",
                     "In the 1080p test render, keep Samples lower than the final render's 512.",
                     "Experts suggest visiting the Louvre on a Wednesday evening, when it is quieter than at weekends.",
                     "Experts recommend replacing a Shimano chain at 0.5% wear, sooner than most riders do.",
                     "A panel of judges from Great Taste picks the winner, and entries that score higher than 80 get a "
                     "gold star.",
                     "In the blind taste test at 2 pm, the loaf most visitors prefer wins the People's Choice ribbon."):
            self.assertEqual(self.claims(fx(text)), [], text)
        # ... while a comparison of results still counts
        for text, phrase in (("In the blind test, Bed A yields more than Bed B.", "In the blind test"),
                             ("A panel of growers ranks Suttons ahead of Thompson.", "A panel of growers"),
                             ("In the 4K test, Bed A comes out ahead of Bed B.", "In the 4K test")):
            self.assertEqual(self.claims(fx(text)), [phrase], text)

    def test_sentences_split_after_a_full_stop_and_a_space(self):
        self.assertEqual(G.sentences(section("Planting", "It held 0.0018 % (about 1.5k ppm). Then it rose!",
                                             "- one item\n  that carries on", "| a | b |")),
                         ["It held 0.0018 % (about 1.5k ppm).", "Then it rose!", "- one item that carries on",
                          "| a | b |"])


class GivenDataTests(unittest.TestCase):
    """A measurement, result or source the step was given is its data restated, not an invented claim (K5): the
    checkers' fixture had a step's own instructions list pump readings, and the gate failed "were measured at"."""

    # shaped on a pasted-material seed: the readings ride in the step's own instructions
    READINGS = plan_of(("Readings summary", "writing", fx(
        "Write a short summary of these bed temperatures, taken every 15 minutes on 3 June: 09:00 11.2 C, 09:15 "
        "13.8 C, 09:30 17.5 C. Frost cloth comes off above 15 C.")),
                       ("Advice", "writing", "Say what to do next."))
    SUMMARY = section("Readings summary", "Bed temperatures were measured at 15-minute intervals on 3 June. They "
                      "rose from 11.2 C at 09:00 to 17.5 C at 09:30, past the 15 C mark.")

    def plan_with_dep(self, kind="research"):
        p = plan_of(("Yield data", kind, "Gather yields for the two beds."),
                    ("Yield section", "writing", "Using the yields from s1, compare the beds."))
        p["steps"][1]["depends_on"] = ["s1"]
        return p

    DEP = fx("## Yield data\n\nThe yield analysis: bed A gave 4.2 kg, bed B 3.1 kg, 35 % more for A. The soil survey "
             "found clay in bed B.") + HANDOFF

    def check(self, text, plan, i, deps=(), missing=()):
        return G.section_check(plan, i, text, None, {}, deps, missing)

    def test_the_steps_own_readings(self):
        got = self.check(self.SUMMARY, self.READINGS, 0)
        self.assertEqual((got["reasons"], got["claims"], got["claims_given"]), ([], [], ["were measured at"]))
        # figures the instructions don't give are still invented
        got = self.check(section("Readings summary", "Bed temperatures were measured at 20-minute intervals."),
                         self.READINGS, 0)
        self.assertEqual(got["claims"], ["were measured at"])

    def test_a_dependencys_piece(self):
        plan = self.plan_with_dep()
        for text, phrase in (("According to the yield analysis, bed A gave 35 % more.", "According to the yield "
                              "analysis"), ("The soil survey found clay in bed B.", None),
                             ("The figures were taken from the yield analysis: 4.2 kg and 3.1 kg.", "figures were taken from")):
            got = self.check(section("Yield section", fx(text)), plan, 1, {"s1": self.DEP})
            self.assertEqual(got["claims"], [], text)
            if phrase:
                self.assertEqual(got["claims_given"], [phrase], text)
        # a figure it doesn't hold, and a name it doesn't give
        for text in ("According to the yield analysis, bed A gave 50 % more.",
                     "According to the county survey, clay beds yield less."):
            self.assertTrue(self.check(section("Yield section", fx(text)), plan, 1, {"s1": self.DEP})["claims"], text)

    def test_with_a_dependency_missing_only_the_pieces_there_count(self):
        # real: all 9 of the smoke's firings were written with s1 failed, in the plan's own words and figures
        # ("Based on the benchmark data from s1, ... (resolution 8K)"); the summary here carries readings too
        plan = self.plan_with_dep()
        plan["summary"] = fx("Compare two beds; readings taken every 15 minutes on 3 June: 11.2 C, 13.8 C, "
                             "17.5 C.")
        text = section("Yield section", fx("The bed temperatures were measured at 15-minute intervals on 3 June."))
        self.assertEqual(self.check(text, plan, 1, {"s1": self.DEP})["claims"], [])
        for deps, missing in (({"s1": None}, ["s1"]), ({"s1": None}, ()), ({}, ()), ((), ["s1"])):
            self.assertEqual(self.check(text, plan, 1, deps, missing)["claims"], ["were measured at"], (deps, missing))
        self.assertEqual(G.section_check(plan, 1, text, None, {})["claims"], ["were measured at"])  # deps not passed

    def test_a_run_is_never_given(self):
        dep = fx("## Yield data\n\nTrials were run on both beds; our tests show bed A ahead.")
        for text in ("Trials were run on both beds.", "Our tests show bed A ahead."):
            got = self.check(section("Yield section", fx(text)), self.plan_with_dep(), 1, {"s1": dep})
            self.assertEqual(len(got["claims"]), 1, text)

    def test_a_label_in_the_steps_own_words_is_no_data(self):
        plan = plan_of(("Photo comparison", "writing", "Compare the two beds' photos at 4K using benchmarks."))
        for text in ("The 4K benchmark shows bed A greener.", "Benchmarks show bed A greener."):
            self.assertEqual(self.check(section("Photo comparison", fx(text)), plan, 0)["claims"],
                             [text.split(" bed")[0].replace("The 4K ", "")], text)

    def test_a_name_outside_the_request_needs_its_words_and_a_figure(self):
        plan = self.plan_with_dep()
        dep = fx("## Yield data\n\nFrom each supplier's website: kale £2.49, beet £1.99.")
        for text, fires in (("Prices were taken from each supplier's website: kale £2.49.", False),
                            ("Prices were taken from each supplier's website.", True),
                            ("Prices were taken from each grower's catalogue: kale £2.49.", True)):
            got = self.check(section("Yield section", fx(text)), plan, 1, {"s1": dep})
            self.assertEqual(bool(got["claims"]), fires, text)

    def test_given_material(self):
        plan = self.plan_with_dep()
        own, pieces = G.given_material(plan, 1, {"s1": self.DEP})
        self.assertIn("Using the yields from s1", own)
        self.assertIn(plan["summary"], own)
        self.assertIn("4.2 kg", pieces)
        self.assertNotIn("provides:", pieces)  # the handoff's "assumed" holds guesses
        self.assertEqual(G.given_material(plan, 1, {"s1": None}), ("", ""))
        self.assertEqual(G.given_material(plan, 1, {"s1": self.DEP}, ["s1"])[0], "")
        self.assertEqual(G.given_material(plan, 1, [self.DEP])[1], pieces)  # the texts themselves
        self.assertEqual(G.given_material(plan, 1, [("s1", self.DEP)])[1], pieces)
        self.assertEqual(G.given_material(plan, 1)[0], "")  # a dependency nobody passed counts as missing
        self.assertTrue(G.given_material(plan, 0)[0])  # a step with no dependency has its own words
        plan["steps"][0]["id"] = "yields"  # keyed by plan id as well as sid
        plan["steps"][1]["depends_on"] = ["yields"]
        self.assertTrue(G.given_material(plan, 1, {"yields": self.DEP})[0])

    def test_a_piece_that_says_the_data_wasnt_there_gives_none(self):
        # An honest research step says what it lacked; read whole, its piece made an invented claim look given.
        plan = self.plan_with_dep()
        for piece, text in (
                ("No soil survey results were available, so none are given (unverified).",
                 "Surveys indicate that clay beds yield less."),
                ("No soil survey results were available, so none are given (unverified).",
                 "According to the soil survey, bed B is clay."),
                ("I couldn't find a published yield study for these beds.",
                 "According to the yield study, bed A is ahead."),
                ("Nothing was measured: there were no sensor readings.",
                 "The readings were measured at the bed's edge."),
                ("Supplier price lists weren't available; prices are left out.",
                 "Prices were taken from the supplier price lists.")):
            got = self.check(section("Yield section", fx(text)), plan, 1, {"s1": fx("## Yield data\n\n" + piece)})
            self.assertTrue(got["claims"], (piece, text))
        # A heading names what its piece is about, but not when the piece then says it wasn't there.
        text = section("Yield section", fx("According to the soil survey, bed B is clay."))
        self.assertEqual(self.check(text, plan, 1, {"s1": fx("## Soil survey\n\nNo soil survey results were "
                                                              "available.")})["claims"],
                         ["According to the soil survey"])
        self.assertEqual(self.check(text, plan, 1, {"s1": fx("## Soil survey\n\nBed B is clay; bed A is loam.")})[
            "claims"], [])
        # A denial reaches only its own words: "no drainage pipe, and the yield analysis ..." denies no analysis.
        got = self.check(section("Yield section", fx("According to the yield analysis, bed A gave 35 % more.")),
                         plan, 1, {"s1": fx("## Yield data\n\nBed A has no drainage pipe, and the yield analysis "
                                            "put it 35 % ahead.")})
        self.assertEqual((got["claims"], got["claims_given"]), ([], ["According to the yield analysis"]))

    def test_label_numbers_are_no_data(self):
        # real: in the smoke's research_draft-0007-04 plan "8K", "Redshift 3.6", "≈600 words" and "a team of 5" gave
        # a section's own words four figures and more, and a dependency's piece that only shared a label passed "The
        # 8K benchmark shows Octane ahead by 12%" by the half rule
        self.assertEqual(G._figs(fx("1. Bed A at 4K: Kale 3.6 seed, week 1 12 kg, an RTX 4090 rig, ≈600 words, a 3D "
                                    "plan, version (2.1), log_202311.csv, 1080p photos, 09:15 and 2025-06-03.")),
                         [("12", "kg"), ("9:15", "clock"), ("2025-06-03", "date")])
        # ... and what stays data, each with its unit or sign
        self.assertEqual(G._figs(fx("Kale costs $5/month or £2.49, 62 % sprout, 24 mm/s of water for 15-minute spells "
                                    "at 47.5 °C, 4 min 12 s on 3 June; Bed B 3.1 kg, 250 seeds, 2 times faster.")),
                         [("5", "$"), ("2.49", "£"), ("62", "%"), ("24", "mm/s"), ("15", "min"), ("47.5", "c"),
                          ("4", "min"), ("12", "s"), ("3", "june"), ("3.1", "kg"), ("250", ""), ("2", "x")])
        plan = self.plan_with_dep()
        plan["title"] = "Bed comparison for a team of 5"
        plan["steps"][1]["instructions"] += " About 400 words."
        self.assertTrue({("5", ""), ("400", "")} <= G._labels(plan, 1))
        # (unmarked: a marked piece gives a result no words, test_a_marked_guess_restated_without_its_mark)
        dep = fx("## Yield data\n\nThe benchmark covered the 4K photos of bed A and bed B, Kale 3.6 seed.")
        for text in ("The 4K benchmark shows bed A ahead by 12 %.",
                     "Benchmarks show bed A 2 times greener than the Kale 3.6 bed.",
                     "The benchmark shows 5 beds ahead by 12 %."):
            self.assertTrue(self.check(section("Yield section", fx(text)), plan, 1, {"s1": dep})["claims"], text)
        # with no figure left, the sentence has none: the piece's word is enough
        got = self.check(section("Yield section", fx("The 4K benchmark shows bed A greener.")), plan, 1, {"s1": dep})
        self.assertEqual((got["claims"], got["claims_given"]), ([], ["benchmark shows"]))
        # a title's year still says which year the plan is about
        text = section("Yield section", fx("According to the 2025 yield analysis, bed A is ahead."))
        self.assertTrue(self.check(text, plan, 1, {"s1": self.DEP})["claims"])
        plan["title"] += " (2025)"
        self.assertEqual(self.check(text, plan, 1, {"s1": self.DEP})["claims"], [])

    def test_the_steps_own_figures_count_with_their_unit(self):
        # Pasted material with one to three figures: four were once needed before the step's own words counted.
        plan = plan_of(("Survey summary", "writing", fx(
            "Summarise this survey of the allotment: 62 % water in the evening and 38 % in the morning; pump "
            "readings peaked at 47.5 C at 14:30.")), ("Advice", "writing", "Say what to do next."))
        for text, given in (("According to the survey, 62 % water in the evening and 38 % in the morning.", True),
                            ("According to the survey, 70 % water in the evening.", False),
                            ("The pump readings were measured at 47.5 C at 14:30.", True),
                            ("The pump was measured at 47.5 % load.", False)):
            got = self.check(section("Survey summary", fx(text)), plan, 0)
            self.assertEqual(not got["claims"], given, text)
        # a bare count or a title's number gives nothing; a decimal, three digits or a unit do
        plan = plan_of(("Bed trial for a team of 5", "writing", fx(
            "Compare the 3 beds using benchmarks; packs hold 250 seeds, the bed is 1.5 m wide.")),
                       ("Advice", "writing", "Say what to do next."))
        for text, given in (("Benchmarks show bed A ahead on all 3 beds.", False),
                            ("Benchmarks show bed A greener.", False),
                            ("The benchmark shows a pack of 250 seeds fills the 1.5 m bed.", True)):
            got = self.check(section("Bed trial for a team of 5", fx(text)), plan, 0)
            self.assertEqual(not got["claims"], given, text)
        # a piece's figure with another unit is another figure ("12 s" isn't "12 %")
        dep = fx("## Yield data\n\nThe yield analysis: bed A soaked in 4 min 12 s, bed B in 5 min.")
        for text, given in (("According to the yield analysis, bed A soaked in 4 min 12 s.", True),
                            ("According to the yield analysis, bed A soaks 12 % faster.", False)):
            got = self.check(section("Yield section", fx(text)), self.plan_with_dep(), 1, {"s1": dep})
            self.assertEqual(not got["claims"], given, text)

    def test_a_claim_with_no_figure_by_the_steps_own_words(self):
        # Instructions that give the data next to its word, or make the claim themselves, excuse it; instructions that
        # only ask for a benchmark or a survey don't (test_a_label_in_the_steps_own_words_is_no_data).
        for ins, text, given in (
                ("Summarise the waste weighed at closing: week 1 12 kg, week 2 9 kg, week 3 14 kg.",
                 "Waste was measured by weight at closing each week.", True),
                ("Explain that research shows mulch keeps the soil cool.",
                 "Research shows that mulch keeps soil cool.", True),
                ("Find out whether research shows mulch keeps the soil cool.",
                 "Research shows that mulch keeps soil cool.", False),
                ("Compare the 3 beds using benchmarks; packs hold 250 seeds.", "Benchmarks show bed A greener.", False),
                ("Summarise the soil survey results.", "Surveys indicate that clay beds yield less.", False)):
            plan = plan_of(("Findings", "writing", fx(ins)), ("Advice", "writing", "Say what to do next."))
            self.assertEqual(not self.check(section("Findings", fx(text)), plan, 0)["claims"], given, (ins, text))
        # ... and only with nothing missing: the missing step was what would have given it
        plan = self.plan_with_dep()
        plan["steps"][1]["instructions"] = fx("Summarise the waste weighed at closing: week 1 12 kg, week 2 9 kg.")
        text = section("Yield section", fx("Waste was measured by weight at closing each week."))
        self.assertEqual(self.check(text, plan, 1, {"s1": self.DEP})["claims"], [])
        self.assertTrue(self.check(text, plan, 1, {"s1": None}, ["s1"])["claims"])

    HONEST = fx("## Yield data\n\nNo yield figures or soil survey results were available for these beds "
                "(unverified).") + HANDOFF

    def test_own_words_that_point_at_another_step_give_nothing(self):
        # About half of the smoke's dependent sections name a dependency's data ("Based on the benchmark data from s1,
        # ..."): those words don't give it; that step's piece has to (here an honest one that had none)
        plan = self.plan_with_dep()
        for ins in ("Based on the yield analysis and the soil survey from s1, compare the beds.",
                    "Using s1's yield analysis and soil survey, compare the beds.",
                    "Using the yield analysis and soil survey of step s1, compare the beds.",
                    "Compare the beds using the yield analysis and soil survey from the previous step."):
            plan["steps"][1]["instructions"] = fx(ins)
            for text in ("According to the yield analysis, bed A is ahead.",
                         "According to the soil survey, bed B is clay.", "Surveys indicate that clay beds yield less."):
                got = self.check(section("Yield section", fx(text)), plan, 1, {"s1": self.HONEST})
                self.assertTrue(got["claims"], (ins, text))
            # ... while a piece that has the data gives it, with figures or without
            for text in ("According to the yield analysis, bed A gave 35 % more.",
                         "According to the soil survey, bed B is clay."):
                got = self.check(section("Yield section", fx(text)), plan, 1, {"s1": self.DEP})
                self.assertEqual(got["claims"], [], (ins, text))

    def test_the_smoke_plans_shape_with_an_honest_research_step(self):
        # real: smoke seed research_draft-0007-04's round-1 titles and the start of its instructions, as if its
        # research step had worked and said outright that it found no data (the round-2 checker's s1)
        steps = [("Draft outline and gather reference data", "research", "Produce a concise outline for the memo, "
                  "with benchmark results for 8K renders and current licensing prices."),
                 ("Write Side-by-side 8K render quality comparison (≈600 words)", "writing", "Based on the benchmark "
                  "data from s1, compose the side-by-side comparison section."),
                 ("Write License cost breakdown for team of 5 (≈400 words)", "writing", "Using the license_prices "
                  "from s1, calculate total annual costs for five users. Present the breakdown in a clear table.")]
        plan = plan_of(*[(t, k, fx(ins)) for t, k, ins in steps])
        for st in plan["steps"][1:]:
            st["depends_on"] = ["s1"]
        s1 = fx("## Outline and reference data\n\n- Current workflow audit\n- License cost breakdown\n\nNo benchmark "
                "results for 8K renders or current license prices were available to me; Redshift 3.6 and OctaneRender "
                "2024 both render on the GPU (unverified).") + HANDOFF
        for i, text in ((1, "According to the benchmark data, Octane produces cleaner reflections than Redshift."),
                        (2, "According to the license cost data, Octane is the cheaper option for a small team."),
                        (2, "These prices were taken from the license cost breakdown.")):
            got = self.check(section(G.section_heading(plan["steps"][i]), fx(text)), plan, i, {"s1": s1})
            self.assertEqual(got["claims_given"], [], text)
            self.assertTrue(got["claims"], text)

    def test_a_piece_that_only_names_the_data_gives_no_result(self):
        # An honest research step that had no data mentions it all the same: a modal, a recommendation, a label whose
        # value says none, what is missing, a tool or a publisher. A claim with no figure isn't its data.
        plan = self.plan_with_dep()
        for piece in ("The club should run its own soil survey before choosing a bed (unverified).",
                      "A soil survey would be needed to compare the beds; none is given here.",
                      "Recommended next step: survey both beds.",
                      "- Soil survey: none found\n- Yields: see the seed firms' pages (unverified)",
                      "- Soil survey: n/a",
                      "Missing data: soil survey results, yields per bed.",
                      "Not available: the soil survey, yields per bed.",
                      "Both seed firms publish soil survey guides, but no survey of these beds was found.",
                      "SoilScan is the county's own survey tool (unverified).",
                      "A soil survey of both beds is planned for next month."):
            dep = fx("## Yield data\n\n" + piece) + HANDOFF
            for text in ("Surveys indicate that bed B is clay.", "According to the soil survey, bed B is clay."):
                got = self.check(section("Yield section", fx(text)), plan, 1, {"s1": dep})
                self.assertTrue(got["claims"], (piece, text))
        # ... and one that gives it does, with a result verb, after a colon, or in words that hold what the claim says
        for piece in ("The soil survey shows bed B is clay.", "Soil survey: bed B is clay, bed A loam (unverified).",
                      "The soil survey covers both beds; bed B is clay and bed A loam."):
            dep = fx("## Yield data\n\n" + piece) + HANDOFF
            got = self.check(section("Yield section", fx("According to the soil survey, bed B is clay.")), plan, 1,
                             {"s1": dep})
            self.assertEqual((got["claims"], got["claims_given"]), ([], ["According to the soil survey"]), piece)

    def test_a_heading_gives_only_what_its_piece_says(self):
        # A piece's heading is its step's title, which names the data asked for: it gives a claim with no figure only
        # where the piece's text holds what the claim says (all of it), or has figures when the claim says nothing more
        plan = self.plan_with_dep()
        honest = fx("## Soil survey\n\nBoth beds get full sun and drain into the same ditch (unverified).") + HANDOFF
        given = fx("## Soil survey\n\nBed B is clay and holds water; bed A is loam.") + HANDOFF
        for text, dep, excused in (("Surveys indicate that bed B holds water.", honest, False),
                                   ("According to the soil survey, bed B is clay.", honest, False),
                                   ("Surveys indicate that bed B holds water.", given, True),
                                   ("According to the soil survey, bed B is clay.", given, True),
                                   ("According to the soil survey, bed B drains fastest.", given, False)):
            got = self.check(section("Yield section", fx(text)), plan, 1, {"s1": dep})
            self.assertEqual(not got["claims"], excused, (text, dep))
        costs = fx("## Seed costs\n\nKale £2.49 a packet, beet £1.99.") + HANDOFF
        for dep, excused in ((costs, True), (honest.replace("Soil survey", "Seed costs"), False)):
            got = self.check(section("Yield section", fx("These prices were taken from the seed costs.")), plan, 1,
                             {"s1": dep})
            self.assertEqual(not got["claims"], excused, dep)

    def test_a_datasets_size_or_a_budget_is_no_data(self):
        # The step's own words give a claim with no figure its data only with a figure after a colon or after a word
        # that says what the data is: not the survey's size, a budget or an "(n = 340)"
        for ins, text, given in (
                ("Compare the beds' soil surveys for a club with a £500 budget.", "Surveys indicate bed B is clay.",
                 False),
                ("Summarise the soil survey of 120 plots and recommend a bed.", "Surveys indicate most plots are clay.",
                 False),
                ("Write up the 2025 soil survey (n = 340) for the club.",
                 "The 2025 soil survey found that most plots are clay.", False),
                ("Summarise the soil survey of 120 plots and recommend a bed.",
                 "According to the soil survey, most plots are clay.", False),
                ("Write up the soil survey for the club.", "According to the soil survey, most plots are clay.", False),
                ("Find out what the soil survey found about the plots.",
                 "According to the soil survey, most plots are clay.", False),
                ("Summarise the soil survey, which found 62 % of plots are clay.", "Surveys indicate most plots are clay.",
                 True),
                ("Summarise the soil survey: 62 % of plots are clay.", "Surveys indicate most plots are clay.", True),
                ("Summarise the soil survey, which found that most plots are clay.",
                 "According to the soil survey, most plots are clay.", True),
                ("Summarise what Dan, the head grower, said: most plots are clay.",
                 "According to Dan, the head grower, most plots are clay.", True)):
            plan = plan_of(("Findings", "writing", fx(ins)), ("Advice", "writing", "Say what to do next."))
            self.assertEqual(not self.check(section("Findings", fx(text)), plan, 0)["claims"], given, (ins, text))

    def test_the_previous_result_is_given(self):
        # Chimera's request gives a round-2+ step the previous round's result: restating it is no claim, and it is
        # there whichever dependency is missing.
        prev = fx("## Yield section\n\nThe yield analysis: bed A gave 4.2 kg, bed B 3.1 kg.")
        plan = self.plan_with_dep()
        text = section("Yield section", fx("According to the yield analysis, bed A gave 4.2 kg."))
        self.assertTrue(self.check(text, plan, 1, {"s1": None}, ["s1"])["claims"])
        got = G.section_check(plan, 1, text, None, {}, {"s1": None}, ["s1"], prev_result=prev)
        self.assertEqual((got["claims"], got["claims_given"]), ([], ["According to the yield analysis"]))
        self.assertEqual(G.given_material(plan, 1, {"s1": None}, ["s1"], prev), ("", G.cv.strip_handoff(prev)))
        got = G.section_check(plan, 1, section("Yield section", fx("According to the yield analysis, bed A gave "
                                                                   "5 kg.")), None, {}, {"s1": None}, ["s1"],
                              prev_result=prev)
        self.assertEqual(got["claims"], ["According to the yield analysis"])

    def test_a_piece_gives_a_claim_with_no_figure_only_where_its_sentence_says_it(self):
        # An honest piece that says something about the survey (its scope, its cost, what it scores) gave every claim
        # with no figure about it (the fourth check's B2); a sentence that says the data has to hold half of what the
        # claim says, with the one after it on its line
        plan = self.plan_with_dep()
        honest = ("The only soil survey covered the north beds in 2019, not bed B.",
                  "Running a soil survey takes about 2 days.",
                  "The county's soil survey gives a score per field; it says nothing about drainage.")
        for piece in honest:
            dep = fx("## Yield data\n\n" + piece) + HANDOFF
            for text in ("Surveys indicate that bed B holds water after rain.",
                         "According to the soil survey, bed B stays wet after rain."):
                self.assertTrue(self.check(section("Yield section", fx(text)), plan, 1, {"s1": dep})["claims"],
                                (piece, text))
        for piece in ("The soil survey found that bed B holds water and stays wet after rain.",
                      "The soil survey covered 12 beds. Bed B held water longest after rain, at 4 hours."):
            dep = fx("## Yield data\n\n" + piece) + HANDOFF
            for text in ("Surveys indicate that bed B holds water after rain.",
                         "According to the soil survey, bed B stays wet after rain."):
                self.assertEqual(self.check(section("Yield section", fx(text)), plan, 1, {"s1": dep})["claims"], [],
                                 (piece, text))
        # ... and a long previous result that names every topic gives nothing it doesn't say
        prev = fx("## Yield section\n\nThe soil survey covers 12 beds over 2 weeks: clay beds, loam beds and the "
                  "raised bed.\n\nBed B holds water and the raised bed drains fast.")
        got = G.section_check(plan, 1, section("Yield section", fx("According to the soil survey, the raised bed "
                                                                   "yields twice as much kale.")), None, {},
                              {"s1": self.HONEST}, (), prev_result=prev)
        self.assertEqual(got["claims"], ["According to the soil survey"])

    def test_a_pointing_clause_or_a_figure_from_elsewhere_gives_no_claim_with_figures(self):
        # real: on the smoke's plan a claim with one figure the honest s1 gave and one it invented was excused by the
        # half rule and the own words' "Based on the benchmark data from s1" (the fourth check's B1): a pointing clause
        # names data its step has to give, and the blocks that hold what the claim is about have to give its figures
        plan = self.plan_with_dep()
        plan["steps"][1]["title"] = "Soil survey section"
        plan["steps"][1]["instructions"] = fx("Based on the soil survey from s1, compare the beds.")
        dep = fx("## Yield data\n\nNo soil survey results were available. Both beds are 1.5 m wide.") + HANDOFF
        for text in ("The soil survey found bed B is 1.5 m wide and drains 40 % slower.",
                     "According to the soil survey, bed B is 1.5 m wide and drains 40 % slower."):
            self.assertTrue(self.check(section("Soil survey section", fx(text)), plan, 1, {"s1": dep})["claims"], text)
        # ... while the step's piece that holds both still gives them
        dep = fx("## Yield data\n\nThe soil survey: both beds are 1.5 m wide, and bed B drains 40 % slower.") + HANDOFF
        self.assertEqual(self.check(section("Soil survey section", fx("According to the soil survey, bed B drains 40 % "
                                                                      "slower.")), plan, 1, {"s1": dep})["claims"], [])

    def test_own_words_that_set_a_target_or_ask_give_no_data(self):
        for ins, text in (
                ("Check whether the soil survey is under 5 % clay, and recommend a bed.",
                 "Surveys indicate bed B suits kale."),
                ("The survey target is 200 replies by Friday. Write up what members want.",
                 "Surveys show members want more Tuesday sessions."),
                ("Find out if the survey is above 60 % for Tuesdays, then write up the schedule.",
                 "The survey indicates most members want Tuesdays."),
                ("The target trial yield is 4 kg a bed; recommend the bed that meets it.",
                 "Trials show bed A meets the target comfortably."),
                ("Summarise the survey for the newsletter.\nSurvey details:\n- Sent to: 340 members\n- Closes: 14 March",
                 "According to the survey, most members prefer Tuesday evenings."),
                ("Write up the survey, which went to 340 members last month.",
                 "According to the survey, most members prefer Tuesday evenings.")):
            plan = plan_of(("Findings", "writing", fx(ins)), ("Advice", "writing", "Say what to do next."))
            self.assertTrue(self.check(section("Findings", fx(text)), plan, 0)["claims"], (ins, text))
        # ... while the data they give, in a later sentence, in rows under a results label or as readings, is given
        for ins, text in (
                ("Summarise the staff survey for the memo. In the survey, 62 % want hybrid working and 38 % the office.",
                 "According to the survey, a clear majority want hybrid working."),
                ("Summarise the staff survey for the memo.\nSurvey results:\n- Hybrid working: 62 %\n- Office: 38 %",
                 "According to the staff survey, most staff want hybrid working."),
                ("Summarise the pump readings.\nReadings (taken hourly on 3 June):\n09:00 41.2 C\n10:00 44.8 C",
                 "Temperatures were measured at the outlet every hour.")):
            plan = plan_of(("Findings", "writing", fx(ins)), ("Advice", "writing", "Say what to do next."))
            self.assertEqual(self.check(section("Findings", fx(text)), plan, 0)["claims"], [], (ins, text))

    def test_a_name_given_only_as_a_place_to_get_data_or_someone_to_act(self):
        # real: the helper's plan for research_draft-0012-05 says "using data from statista and cnet"; a name the own
        # words give only as where to look has to be given or said what it found, and one given only as someone to act
        # is no source
        plan = plan_of(("Market analysis", "research", fx("Produce a market analysis of raised beds for 2024, using "
                                                          "data from Statista and the RHS.")),
                       ("Advice", "writing", "Say what to do next."))
        for text in ("According to Statista, raised beds were the fastest-growing kind in 2024.",
                     "Statista reports that raised beds led sales growth in 2024."):
            self.assertTrue(self.check(section("Market analysis", fx(text)), plan, 0)["claims"], text)
        plan = plan_of(("Letter", "writing", fx("Write the letter to members. Ask Dan, the head grower, to sign it.")),
                       ("Advice", "writing", "Say what to do next."))
        self.assertTrue(self.check(section("Letter", fx("According to Dan, the head grower, members double their "
                                                        "yields.")), plan, 0)["claims"])

    def test_a_marked_guess_restated_without_its_mark(self):
        # real: the smoke's s1 for research_draft-0007-04 marked its invented timings "(unverified)"; once it passes,
        # an s3 that restates them without the mark presents a guess as a result. A marked sentence gives no figures
        # and no words to a result or a measurement; a section that keeps the mark passes, and a source's name is
        # still given
        plan = self.plan_with_dep()
        dep = fx("## Yield data\n\n- Bed A gave about 4.2 kg in the trial (unverified).\n- Trials show bed A about "
                 "35 % ahead (unverified).\n- The yield analysis puts bed A ahead (unverified).") + HANDOFF
        for text, phrase in (("Trials show bed A about 35 % ahead of bed B.", "Trials show"),
                             ("Trials show bed A ahead of bed B.", "Trials show"),
                             ("In the side-by-side trial, bed A gave about 4.2 kg.", "In the side-by-side trial")):
            got = self.check(section("Yield section", fx(text)), plan, 1, {"s1": dep})
            self.assertEqual((got["claims"], got["claims_why"]), ([phrase], {phrase: "mark"}), text)
            self.assertEqual(got["tell"], [G.CLAIMS_TELL_MARK.format(quotes=f'"{phrase}"')])
        for text in ("Trials show bed A about 35 % ahead of bed B (unverified).",
                     "According to the yield analysis, bed A is ahead."):
            self.assertEqual(self.check(section("Yield section", fx(text)), plan, 1, {"s1": dep})["claims"], [], text)
        # ... and the previous round's marked guess the same way
        prev = fx("## Yield section\n\nTrials show bed A about 35 % ahead (unverified), so grow kale there.")
        got = G.section_check(plan, 1, section("Yield section", fx("Trials show bed A about 35 % ahead, so grow kale "
                                                                   "there.")), None, {}, {"s1": None}, ["s1"],
                              prev_result=prev)
        self.assertEqual(got["claims_why"], {"Trials show": "mark"})

    def test_given_data_in_hedged_words_rows_or_a_later_sentence(self):
        # The fourth check's precision side: honest restatements of data the step was given, with no figure, failed
        # where the data clause had a modal, the data sat in rows under a label of the piece's body, or the word was
        # in the sentence before the data
        plan = self.plan_with_dep()
        text = section("Yield section", fx("According to the survey, most members prefer Tuesday evenings."))
        for piece in ("In the survey, 64 % of the 120 members who replied said they would prefer Tuesday evenings.",
                      "The survey suggests most members may prefer Tuesday evenings (64 % of 120 replies).",
                      "Survey results:\n\n| Slot | Share |\n|---|---|\n| Tuesday evening | 64 % |\n| Thursday | 28 % |",
                      "The survey had 120 replies. Tuesday evening was the clear favourite at 64 %."):
            got = self.check(text, plan, 1, {"s1": fx("## Member survey\n\n" + piece) + HANDOFF})
            self.assertEqual((got["claims"], got["claims_given"]), ([], ["According to the survey"]), piece)
        # ... not a modal with a figure that isn't the data, nor rows under a label that names no results
        for piece in ("A survey of the members would take about 3 hours.",
                      "Survey details:\n- Sent to: 340 members\n- Closes: 14 March"):
            self.assertTrue(self.check(text, plan, 1, {"s1": fx("## Member survey\n\n" + piece) + HANDOFF})["claims"],
                            piece)

    def test_according_to_the_data(self):
        # "According to the data" names nothing to look for: the step's given data is what it cites (it failed even
        # with the exact figure given, from round 2 on)
        plan = self.plan_with_dep()
        dep = fx("## Yield data\n\n```json\n{\"moisture_max\": 42, \"moisture_min\": 18}\n```\n\nSoil moisture fell "
                 "from 42 % to 18 %, crossing 25 % at 15:00.") + HANDOFF
        for text in ("According to the data, moisture fell to 18 %.",
                     "According to the data, soil moisture fell through the day before the storm."):
            got = self.check(section("Yield section", fx(text)), plan, 1, {"s1": dep})
            self.assertEqual((got["claims"], got["claims_given"]), ([], ["According to the data"]), text)
        for text in ("According to the data, bed A is the better bed.", "According to the data, moisture fell to 9 %."):
            self.assertEqual(self.check(section("Yield section", fx(text)), plan, 1, {"s1": dep})["claims"],
                             ["According to the data"], text)
        self.assertTrue(self.check(section("Yield section", fx("According to the data, moisture fell to 18 %.")),
                                   plan, 1, {"s1": self.HONEST})["claims"])

    def test_a_count_the_own_words_claim_is_theirs(self):
        # The person's own "We surveyed 40 plot holders in May", restated, failed on its bare count; a count that a
        # claim of the own words makes with the word it counts is theirs, as a label is, and excuses no other figure
        plan = plan_of(("What we found", "writing", fx("Write the findings for our newsletter. We surveyed 40 plot "
                                                       "holders in May and interviewed 12 of them.")),
                       ("Advice", "writing", "Say what to do next."))
        for text in ("We surveyed 40 plot holders in May.", "We surveyed 40 plot holders and interviewed 12 of them."):
            self.assertEqual(self.check(section("What we found", fx(text)), plan, 0)["claims"], [], text)
        for text in ("We surveyed 40 plot holders in May, and 70 % want a second water butt.",
                     "We surveyed 50 plot holders in May."):
            self.assertTrue(self.check(section("What we found", fx(text)), plan, 0)["claims"], text)

    def test_figures(self):
        self.assertEqual(G.figures("Bed s1 gave 4.20 kg, 1,200 g and 09:30 of x264 at 0.0018 % on W-2295 (2025)."),
                         ["4.2", "1200", "9", "30", "0.0018", "2295", "2025"])


class StepIdTests(unittest.TestCase):
    PLAN7 = plan_of(*[(f"Part {k}", "writing", "x") for k in range(1, 8)])

    def ids(self, *paras, plan=None):
        return G.step_mentions(plan or self.PLAN7, section("Part 7", *paras))

    def test_a_plan_step_named_in_the_text(self):
        # real: smoke seed coding-0012-01's README step, "generated in step s2" with U+202F, and a "step 6" of its own
        text = section("Part 7", "6. Paste the contents of `manifest.yaml` (generated in step s2) and click Create.",
                       "7. Deploy: this runs the script defined in `package.json` by step s6 (see step 6).")
        got = G.section_check(self.PLAN7, 6, text, None, {})
        self.assertEqual((got["reasons"], got["step_ids"]), (["step_id_leak"], ["step s2", "step s6"]))
        for text, phrase in (("The JSON summary from **s1** shows a rise.", "s1"),
                             ("The hypothesis (assumed from Step S2) blames the bearing.", "Step S2"),
                             ("It runs nightly (see s4).", "s4"),
                             ("s3’s list is short.", "s3"),
                             ("Built on step⁠s5.", "step s5"),
                             ("- based on s1's 8-16 GB for a batch of 2", "s1")):
            self.assertEqual(self.ids(text), [phrase], text)

    def test_what_isnt_a_step_id(self):
        for text in ("Follow step 6 of the setup.", "It needs s9 and s12, which this plan doesn't have.",
                     "Run `aws s3 cp` or `s2`.", "Upload it to an s3 bucket.", "Copy s3://bucket/s2 there.",
                     "See docs/s2/notes and s1.py and $s1.", "Mode S2 is uppercase."):
            self.assertEqual(self.ids(text), [], text)
        self.assertEqual(self.ids("Plain words.", "```python\nprint('step s2')\n```"), [])
        got = G.section_check(PLAN, 1, section("Planting", words(20)) + HANDOFF.replace("none", "s1 (soil)", 1),
                              None, {})
        self.assertNotIn("step_id_leak", got["reasons"])  # the handoff names steps by design
        self.assertEqual(self.ids("It builds on s3.", plan=PLAN), ["s3"])
        self.assertEqual(self.ids("It builds on s4.", plan=PLAN), [])  # PLAN has three steps


class CsvTests(unittest.TestCase):
    def fault(self, *paras):
        return G.csv_fault(section("Routes", *paras))

    def test_rows_that_dont_match_their_header(self):
        # real: smoke seed planning-0002-08's s2: a location written as "BC,49.10,-122.82" under a 6-column header
        rows = "\n".join(["ConcertID,Route,FuelStopName,Location,FuelQty,Distance (km)",
                          "1,Base → Vancouver,Surrey,BC,49.1060,-122.8250,10,30",
                          "1,Base → Vancouver,Hope,BC,49.3800,-121.4400,15,50"])
        plan = plan_of(("Schedule", "writing", "x"), ("Routes", "writing", "Output as CSV."))
        got = G.section_check(plan, 1, section("Routes", rows), None, {})
        self.assertEqual((got["reasons"], got["csv"]), (["csv_fields"], {
            "row": 1, "fields": 8, "header": 6, "line": "1,Base → Vancouver,Surrey,BC,49.1060,-122.8250,10,30"}))
        block = "```csv\nTool,Metric\nhtop,CPU use\niostat,Disk I/O\nGlances,Health (CPU, memory, disk)\n```"
        self.assertEqual(self.fault("Two columns:", block)["row"], 3)
        self.assertEqual(self.fault("```text\nname,kind,price\nkale,leaf,2\nbeet,root\n```")["row"], 2)

    def test_whole_csvs_and_what_isnt_one(self):
        for text in ("```csv\nname,note,price\nkale,\"leafy, hardy\",2\nbeet,root,3\n```",
                     "```csv\ndate,description,amount\n2026-09-01,SHOP,-42.17\n...\n```",
                     "```csv\nname,kind,price\n```",
                     "name,kind,price\nkale,leaf,2\nbeet,root,3",
                     "| name | note |\n|---|---|\n| kale | leafy, hardy, green |",
                     "Sow kale early, water it well, and thin it.\nBeets, by contrast, want space.",
                     "Every day, at closing time, follow this simple, five-minute checklist:\n- 4:15 pm: cut prices, "
                     "sign it\n- 5:00 pm: record waste",
                     "2100 ft², 12th Street, Suite 5\nDenver, CO 80202",
                     "```\nx = f(a, b, c)\ny = g(d, e)\n```",
                     "```python\nrows = ['a,b,c', 'd,e']\n```"):
            self.assertIsNone(self.fault(text), text)


# After the fifth smoke (Nov 6): a section's python blocks. V08 (smoke5's blender-0008-00 s6, the audit's bad section
# example) was a packaging script whose README f-string opened a key with " and closed it with '; these are fixtures
# of that shape and of the f-string forms only Python 3.12+ reads, each with the mark.
PACKAGING = (MARK + '\nimport bpy\nimport zipfile\n\nctx = {"values": {"render_resolution": (1920, 1080)}}\n'
             'readme = f"""Render settings:\n- Resolution: {ctx["values"]["render_resolution\'][0]} x 1080\n"""\n'
             'print(readme)\n')
REUSED = MARK + '\nimport bpy\n\nvalues = {"fps": 30}\nprint(f"fps: {values["fps"]}")\n'
OLDER = {"quote": REUSED,
         "backslash": MARK + "\nimport bpy\n\nnames = ['a', 'b']\nprint(f\"{'\\n'.join(names)}\")\n",
         "hash": MARK + '\nimport bpy\n\nn = 3\nprint(f"""{n  # the count\n}""")\n',
         "break": MARK + '\nimport bpy\n\nn = 3\nprint(f"{n +\n 1}")\n'}
# what Python 3.11 reads too: another quote inside, a # in a string in a field, a triple-quoted f-string with " inside,
# a nested f-string with other quotes, an escaped quote and a backslash-newline in the f-string's own text
ELEVEN = [MARK + '\nimport bpy\n\nvalues = {"fps": 30}\nprint(f"fps: {values[\'fps\']}")\n',
          MARK + "\nimport bpy\n\nprint(f\"{'#'} tag\")\n",
          MARK + '\nimport bpy\n\nvalues = {"fps": 30}\nprint(f"""fps: {values["fps"]}""")\n',
          MARK + "\nimport bpy\n\nn = 3\nprint(f\"{f'{n}'}\")\n",
          MARK + '\nimport bpy\n\nn = 3\nprint(f"say \\" {n}")\n',
          MARK + '\nimport bpy\n\nn = 3\nprint(f"abc\\\ndef {n}")\n',
          MARK + '\nimport bpy\n\nn = 3\nprint(f"{n!r:>{n}}")\n']

# The checks of Nov 6: what 5.0.1 refuses in a nested f-string, which only the outermost one's text was read for (its
# own quote reused in a nested f-string, also inside a triple-quoted one or a format spec; a line break in a nested
# single-quoted one), and a line continuation in a field, which is no token
NESTED = {"quote": MARK + "\nimport bpy\n\nd = {'k': 1}\nprint(f\"{f'{d['k']}'}\")\n",
          "quote_in_triple": MARK + "\nimport bpy\n\nd = {'k': 1}\nprint(f\"\"\"{f'{d['k']}'}\"\"\")\n",
          "quote_in_spec": MARK + "\nimport bpy\n\nd = {'k': 1}\nx = 3\nprint(f\"{x:{f'{d['k']}'}}\")\n",
          "break": MARK + "\nimport bpy\n\nx = 3\nprint(f\"\"\"{f'{x +\n1}'}\"\"\")\n",
          "backslash": MARK + "\nimport bpy\n\nx = 3\nprint(f'{x +\\\n1}')\n",
          "backslash_in_triple": MARK + '\nimport bpy\n\nx = 3\nprint(f"""{x +\\\n1}""")\n'}


def fenced(code, tag="python"):
    return f"```{tag}\n{code}```"


class CodeTests(unittest.TestCase):
    """code_syntax (after the fifth smoke): a section's python block must compile; a Blender script's also without the
    f-string forms Python 3.12 added, since Blender 5.0.1 runs Python 3.11."""

    def check(self, *paras):
        plan = plan_of(("Render", "blender", "Set the render."), ("Deliver Files", "general", "Package the files."))
        return G.section_check(plan, 1, section("Deliver Files", *paras), None, {})

    def test_the_packaging_script_that_doesnt_parse(self):
        got = self.check(fx("The script below makes the archive."), fenced(PACKAGING))
        self.assertEqual(got["reasons"], ["code_syntax"])
        self.assertEqual(len(got["code"]), 1)
        fault = got["code"][0]
        self.assertEqual((fault["block"], fault["line"], fault["bpy"], fault["older"]), (0, 7, True, None))
        self.assertTrue(fault["source"].startswith('- Resolution: {ctx["values"]["render_resolution\'][0]}'))
        self.assertEqual(got["tell"], [G.code_tell(fault)])
        self.assertTrue(got["tell"][0].startswith("its python block doesn't compile, so none of it can run: fix its "
                                                  "line 7 (\"- Resolution:"))
        self.assertLessEqual(len(got["tell"][0]), 240)  # hints.FAILURE_CHARS
        fixed = PACKAGING.replace("render_resolution']", 'render_resolution"]')
        self.assertEqual(self.check(fx("The script below makes the archive."), fenced(fixed))["reasons"], [])

    def test_python_312_f_strings_in_a_blender_script(self):
        for kind, code in OLDER.items():
            with self.subTest(kind):
                compile(code, "x", "exec")  # this Python reads it ...
                got = self.check(fx("The script:"), fenced(code))
                self.assertEqual(got["reasons"], ["code_syntax"])
                self.assertEqual((got["code"][0]["older"], got["code"][0]["error"]), (kind, G.OLDER_FSTRING[kind]))
                self.assertEqual(G.older_fstring(code)[1], kind)
                # ... and a script that isn't Blender's is read with this Python's grammar
                plain = code.replace("import bpy\n", "import os\n")
                self.assertEqual(self.check(fx("The script:"), fenced(plain))["reasons"], [])
        for code in ELEVEN:
            with self.subTest(code=code):
                self.assertIsNone(G.older_fstring(code))
                self.assertEqual(self.check(fx("The script:"), fenced(code))["reasons"], [])

    def test_a_nested_f_string_and_a_continuation_in_a_field(self):
        """The checks of Nov 6: each form of NESTED passed code_syntax in a Blender script, though 5.0.1 refuses it
        (CodeInBlenderTests); without bpy it is read with this Python's grammar, as before."""
        for name, code in NESTED.items():
            with self.subTest(name):
                compile(code, "x", "exec")  # this Python reads it
                want = name.split("_")[0]
                self.assertEqual(G.older_fstring(code)[1], want)
                got = self.check(fx("The script:"), fenced(code))
                self.assertEqual((got["reasons"], got["code"][0]["older"]), (["code_syntax"], want))
                plain = code.replace("import bpy\n", "import os\n")
                self.assertEqual(self.check(fx("The script:"), fenced(plain))["reasons"], [])

    def test_what_counts_as_a_sections_code(self):
        broken = MARK + "\nimport os\nprint(os.getcwd(\n"
        for tag in ("python", "py", "python3", "bpy", "make_zip.py"):
            with self.subTest(tag):
                self.assertEqual(self.check(fx("Run:"), fenced(broken, tag))["reasons"], ["code_syntax"])
        # never an untagged block (a listing, a README's text), a shell, JSON, nor an interactive session's prompts
        for text in (fenced("Acme Logo – 3D Build & Render\nFiles: Acme_Logo.blend, Acme_Logo.mp4\n" + MARK + "\n",
                            ""),
                     fenced("Acme_Logo_Export.zip\n├── Acme_Logo.blend\n└── README.txt\n", ""),
                     fenced("blender -b Acme_Logo.blend -a  # " + MARK + "\n", "bash"),
                     fenced('{"fps": 30, "note": "' + MARK + '"}\n', "json"),
                     fenced(">>> import bpy\n>>> bpy.app.version\n... \n", "python"),
                     # a session with its output, as a doctest shows it (the checks of Nov 6)
                     fenced(">>> import zipfile  # " + MARK + "\n>>> zipfile.ZipFile(\"delivery.zip\").namelist()\n"
                            "['scene.blend', 'render.png', 'README.txt']\n", "python")):
            with self.subTest(text=text):
                self.assertEqual(self.check(fx("Here:"), text)["reasons"], [])
        # parsed, not compiled (as approved; the main session's decision, Nov 6): an excerpt from inside a function or
        # loop passes; the indent a whole block shares is taken off
        for excerpt in ("return 1", "if not path.exists():\n    return None", "break", "await job()"):
            with self.subTest(excerpt=excerpt):
                self.assertEqual(self.check(fx("Here:"), fenced(MARK + "\n" + excerpt + "\n"))["reasons"], [])
        indented = "".join("    " + line + "\n" for line in (MARK, "import os", "print(os.getcwd())"))
        self.assertEqual(self.check(fx("Here:"), fenced(indented))["reasons"], [])
        # an unclosed block is the validator's to judge; a second block that fails is recorded, the first told
        two = self.check(fx("Two:"), fenced(broken), fenced(MARK + "\nif True print(1)\n"))
        self.assertEqual([f["block"] for f in two["code"]], [0, 1])
        self.assertEqual(two["tell"], [G.code_tell(two["code"][0])])

    def test_the_lines_wording_is_ours_and_known_to_the_echo_check(self):
        from datagen import hints as H
        from datagen import task as T
        notes = [G.CODE_TELL.split("{line}")[0].strip(" :,")] + list(G.OLDER_FSTRING.values())
        for note in notes:
            self.assertIn(note, G.TELL_NOTES)
            self.assertGreaterEqual(len(H._WORD.findall(note)), H.NOTE_MIN)
            self.assertNotRegex(note, r"\d")  # no version in the notes
            self.assertEqual(H.echoed_note(section("Deliver Files", fx("So: " + note + "."))), "failure_line", note)
        self.assertIn("code_syntax", G.TELL_REASONS)  # its line is the gate's tell, so task.py adds none of its own
        c = {"reasons": ["code_syntax"], "gate": {"tell": ["a line"]}, "content": ""}
        self.assertEqual(T._section_failures(c), [])
        self.assertEqual([str(x) for x in T._failures([c], "section")], ["a line"])
        long = dict(line=12, source="x" * 200, error="y" * 300, older=None, block=0, bpy=False)
        self.assertLessEqual(len(G.code_tell(long)), 240)


@unittest.skipUnless(all(not blenders.check_path(p) for p in blenders.VERSIONS.values()) and
                     pysandbox.can_sandbox(), "needs Blender " + " and ".join(blenders.VERSIONS) + " and sandbox-exec")
class CodeInBlenderTests(unittest.TestCase):
    """older_fstring against each Blender's own compile(), sandboxed as the data generator runs a tool: Blender 5.0.1
    (its Python 3.11) refuses each form it reads and reads the rest, 5.2.2 (3.13) reads them all, and both refuse the
    packaging script. compile() only reads the code. About 3 s."""

    def compiled(self, binary, sources):
        import json
        main = ("import json\nbad = []\nfor k, src in enumerate(json.load(open('blocks.json'))):\n    try:\n"
                "        compile(src, 'block', 'exec', dont_inherit=True)\n    except SyntaxError as e:\n"
                "        bad.append(k)\nprint('DG-BAD', json.dumps(bad))\n")
        r = pysandbox.run_tool({"main.py": main, "blocks.json": json.dumps(sources)}, binary,
                               ["-b", "--factory-startup", "--python-exit-code", "1", "--python", "main.py"],
                               timeout=120)
        line = next((x for x in r["output"].split("\n") if x.startswith("DG-BAD ")), None)
        self.assertIsNotNone(line, r["output"][-1500:])
        return json.loads(line[7:])

    def test_older_fstring_is_what_each_blender_compiles(self):
        sources = list(OLDER.values()) + list(NESTED.values()) + ELEVEN + [PACKAGING]
        refused = [k for k, src in enumerate(sources) if G.code_faults(fenced(src))]
        self.assertEqual(refused, list(range(len(OLDER) + len(NESTED))) + [len(sources) - 1])
        for version, binary in blenders.VERSIONS.items():
            with self.subTest(version):
                bad = self.compiled(binary, sources)
                if version.startswith("5.0"):
                    self.assertEqual(bad, refused)
                else:  # Python 3.13: only the packaging script
                    self.assertEqual(bad, [len(sources) - 1])


class TellTests(unittest.TestCase):
    def test_a_line_for_each_new_check(self):
        text = section("Planting", "This figure was taken from the vendor's 2024 list (see s2).",
                       "```csv\nname,kind,price\nkale,leaf,2,extra\nbeet,root,3\n```")
        got = check(text)
        self.assertEqual(got["reasons"], ["claims_source", "step_id_leak", "csv_fields"])
        self.assertEqual(got["tell"], [
            G.CLAIMS_TELL.format(quotes='"figure was taken from"'),
            G.STEP_ID_TELL.format(quotes='"s2"'),
            "CSV row 1 has 4 fields where its header has 3: give every row the header's fields, and quote a field "
            "that holds a comma"])
        self.assertIn('("figure was taken from")', got["tell"][0])

    def test_no_line_when_it_passes_or_for_the_older_reasons(self):
        self.assertEqual(check(section("Planting", words(20)))["tell"], [])
        got = check(section("Planting", words(20)), codes=["ai_talk"])
        self.assertEqual((got["reasons"], got["tell"]), (["ai_talk"], []))  # task.py's _section_failures says those

    def test_quotes_are_cut_and_at_most_two(self):
        self.assertEqual(G._quotes(["a" * 80, "b", "c"]), '"' + "a" * 39 + '…", "b"')
        longest = G.CLAIMS_TELL.format(quotes=G._quotes(["a" * 80, "b" * 80]))
        self.assertLessEqual(len(longest), 240)  # hints.FAILURE_CHARS: a longer line loses its advice
        got = check(section("Planting", "Tests were run twice. We measured 3 beds. Benchmarks show a gain."))
        self.assertEqual(got["claims"], ["Tests were run", "We measured", "Benchmarks show"])
        self.assertEqual(got["tell"], [G.CLAIMS_TELL.format(quotes='"Tests were run", "We measured"')])

    def test_tell_notes_are_the_fixed_wording(self):
        self.assertEqual(G.TELL_NOTES, (
            "it presents a source, test or measurement it never had as fact",
            "leave the figure out and say the data wasn't available (list it under assumed)",
            "omit any test, measurement or survey it says was done; mark unsure figures (unverified)",
            "it states as fact what its given material marks unverified",
            "keep that mark (unverified) on it",
            "it states a result without the figure from its given data that shows it",
            "give that figure, or leave the result out",
            "which the person reading the result never sees: say what that step made instead",
            "fields where its header has",
            "give every row the header's fields, and quote a field that holds a comma",
            # code_syntax's (after the fifth smoke): its head, and its messages for the f-string forms
            "its python block doesn't compile, so none of it can run: fix its line",
            "inside an f-string's braces it uses that f-string's own quote mark; use the other quote there",
            "a backslash inside an f-string's braces; work that part out before the f-string",
            "a # comment inside an f-string's braces; move the comment out of the f-string",
            "a line break inside the braces of an f-string written in single quotes; keep that field on one line"))
        for note in G.TELL_NOTES:
            self.assertNotIn("{", note)

    def test_a_claims_line_asks_for_the_one_route_the_judge_and_chimera_accept(self):
        # The old "or call the figure an assumed estimate" kept made-up figures, which the judge then scored 2.
        for tell in (G.CLAIMS_TELL, G.CLAIMS_TELL_RESEARCH):
            self.assertNotIn("assumed estimate", tell)
            self.assertLessEqual(len(tell.format(quotes=G._quotes(["a" * 80, "b" * 80]))), 240)
        self.assertIn("say the data wasn't available (list it under assumed)", G.CLAIMS_TELL)
        self.assertNotIn("unverified", G.CLAIMS_TELL)
        # a research step's mark is for figures only: "mark anything uncertain" brought back "Tests were run on an
        # identical workstation (unverified)", which no mark makes true, and "leave out any test or benchmark it says
        # was run" told a "We surveyed 40 artists" to add the mark (a survey is neither): no mark makes either true
        self.assertIn("omit any test, measurement or survey it says was done", G.CLAIMS_TELL_RESEARCH)
        self.assertIn("mark unsure figures (unverified)", G.CLAIMS_TELL_RESEARCH)
        self.assertNotIn("anything uncertain", G.CLAIMS_TELL_RESEARCH)
        text = section("Planting", "Tests were run on two beds over a week.")
        plan = plan_of(("Soil", "research", "Find out how soils differ."),
                       ("Planting", "writing", "Explain when and how to plant."))
        self.assertEqual(G.section_check(plan, 1, text, None, {})["tell"],
                         [G.CLAIMS_TELL.format(quotes='"Tests were run"')])
        self.assertEqual(G.section_check(plan_of(("Planting", "research", "Find out when to plant.")), 0, text, None,
                                         {})["tell"], [G.CLAIMS_TELL_RESEARCH.format(quotes='"Tests were run"')])

    def test_a_claim_the_given_data_has_gets_its_own_line(self):
        # Where the material has the claim's data but the claim leaves out the figure (a survey's rows under its
        # heading), "say the data wasn't available" would steer a next try to drop real data: its line asks for the
        # figure; where the material marks it unverified, its line asks to keep the mark
        plan = plan_of(("Member survey", "research", "Summarise the members' survey."),
                       ("Recommendation", "writing", "Using the survey from s1, recommend a night."))
        plan["steps"][1]["depends_on"] = ["s1"]
        dep = fx("## Member survey\n\n- Replies: 120 of 180 members\n- Tuesday evening: 64 %\n- Thursday: 28 %") + HANDOFF
        text = section("Recommendation", fx("According to the survey, most members prefer Tuesday evenings."),
                       fx("Tests were run on two nights."))
        got = G.section_check(plan, 1, text, None, {}, {"s1": dep})
        self.assertEqual(got["claims_why"], {"According to the survey": "cite", "Tests were run": "plain"})
        self.assertEqual(got["tell"], [G.CLAIMS_TELL.format(quotes='"Tests were run"'),
                                       G.CLAIMS_TELL_CITE.format(quotes='"According to the survey"')])
        got = G.section_check(plan, 1, section("Recommendation", fx("According to the survey, 64 % of members prefer "
                                                                    "Tuesday evenings.")), None, {}, {"s1": dep})
        self.assertEqual(got["claims"], [])  # the figure route the line asks for
        for line in (G.CLAIMS_TELL_MARK, G.CLAIMS_TELL_CITE):
            self.assertLessEqual(len(line.format(quotes=G._quotes(["a" * 80, "b" * 80]))), 240)
            self.assertNotIn("data wasn't available", line)

    def test_a_reply_that_does_what_the_line_asks_is_no_teacher_note(self):
        from datagen import hints as H
        for text in ("The yield data wasn't available, so no weights are given here; they are listed under assumed.",
                     "Exact yields weren't available (unverified figures are left out)."):
            reply = section("Planting", fx(text))
            self.assertIsNone(H.echoed_note(reply), text)
            self.assertEqual(G.source_claims(reply), [], text)
        for note in G.TELL_NOTES[1:3]:  # the advice itself, copied, is ours
            self.assertEqual(H.echoed_note(section("Planting", fx("So: " + note + "."))), "failure_line", note)


if __name__ == "__main__":
    unittest.main()
