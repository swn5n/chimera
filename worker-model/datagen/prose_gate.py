"""The prose gate: deterministic checks on a section piece before it can be a training target or go to the prose judge
(DESIGN.md, "prose_gate.py"; the plan's "Checks every candidate goes through", Prose).

    got = section_check(plan, i, text, verdict, earlier_sections, dep_texts, missing_deps, prev_result)
    # {"ok", "reasons", "words", "target", "overlap", "framing", "warnings", "claims", "tell", ...}

The rules come from the section mode's own words ("Write only your section, starting with ## and the heading your
step gives (else its title). No introduction, conclusion or summary of the whole project unless that is your step;
don't repeat what other steps cover; ... match any tone and length your step gives; don't mention that you're an AI
or that there are other workers.") and research's ("never invent sources, links ...; mark anything uncertain"):
- the Go validator's warnings that a target must not have: ai_talk, unmarked_link, placeholder (the validator only
  looks for placeholders in code, so a section's TODO, TBD, [insert ...] or lorem ipsum is looked for here too) and
  heading_not_title, since a target teaches the heading, unless the heading fits the step (heading_fits): the
  heading its instructions give outright (given_heading: 'section titled "CPU Load"', 'under the heading "X"', a
  backticked `## 1. Installation`, the '"X" section' it names), else the title without the instruction words around
  it ("Write Current workflow audit (≈600 words)" gives "Current workflow audit"; nearly half of gpt-oss's section
  titles start with a verb, and a target that prints "## Write ..." teaches a heading nobody wants in the result).
  bare_title strips only when it's sure: "Research and outline content", "Research Scientist – AI" and "Analyse
  des garanties" stay whole, "Research Windows Developer Laptop" and "Research Los Angeles venues" don't. Go accepts
  any heading that is a substring of the instructions, so a heading it doesn't warn on still fails here when its
  key is empty ("***") or it is only part of a phrase there ("ent the break"): it has to fit the step or be a whole
  phrase of the instructions;
- a word target in the step's instructions or title (about 300 words, 200-400 words, under 150 words, at least 500
  words, a 300-word introduction, in 200 words, ≈600 words, ...; U+2010-2012 and U+2212 read as "-") met within
  30%: about n is 0.7n to 1.3n, a range a-b is 0.7a to 1.3b, "under n" is up to 1.3n, "at least n" is 0.7n or more.
  A target for items (each bullet, the five tips, three paragraphs of, a headline (max 10 words), (≤80 words each),
  "For each, ..." and the list under it; a part in one item of a list, "1. A 250-word introductory paragraph",
  "- Executive Brief (≈250 words)") is each item's, not the section's, unless a sentence asks for that one item
  ("Write a blurb (max 120 words)"); so is the "2,000-word report" in "summarize the 2,000-word report", "an outline
  for a 700-word article" or "the 2,000-word report from s1". A number for the whole section (a total of its length,
  "total word count of 2,000 words", "1,800 words in total"; "a 600-word section/article/memo/press release/...",
  a title's "(≈1,800 words total)") outranks the rest; without one, instructions that name two different counts
  set none, since the teacher's note and the check would then aim at a part ("End with a recommendation paragraph
  (≈100-150 words)" in a ~600-word section): a wrong band is worse than none;
- the first and last paragraphs may not introduce or sum up the whole project ("In this document", "This guide
  will", "In conclusion"; "In summary" and "To sum up" only beside words for the whole, like "this report" or "the
  sections above", since they close a section as often) unless the step's title says it is the introduction, the
  conclusion or a summary, its instructions ask for an introduction or a conclusion, its title names the whole
  deliverable ("Write the full explainer article", "Draft Recommendation Memo"), or the section is the plan's only
  one (then it is the whole written result);
- no more than 20% of its 8-word shingles may appear in an earlier sibling section of the same plan;
- no claim of a source, a test or a measurement the worker can't have had (claims_source; research's "never invent
  sources"): a run ("tests were run", "were tested on the same workstation", "we ran a benchmark", "our tests show",
  "our benchmark rendered", "in our testing", "in our side-by-side tests", "in our assumed tests", "based on our
  testing", "we benchmarked", "we tested both", "we tested" with a number in the sentence), a measurement ("we
  measured", "we found" with a number, "we surveyed", "we interviewed", "measured ... were 0.2 %", "were measured at",
  "(measured by ...)", "as logged by the sensors", "measured render times favour", "62% of respondents", "respondents
  cited", "62% of artists surveyed", a survey's "n = 1,200", an image metric's or a render time's figure: "an SSIM of
  0.98", "| Total render time (8 K) | 12 min 02 s |", not a target, a limit or what to expect), a result ("benchmarks
  show", "tests show", "testing revealed", "studies have shown", "studies consistently show", "research from MIT
  shows", "recent data suggests", "industry figures put", "the benchmark found", "a blind test found", "a survey of
  2,000 campers found", "the benchmark indicates", "observed in the benchmark", "in the assumed benchmark", "research
  shows", "surveys indicate", "a 2023 study found", "the latest Steam hardware survey reports", "the following
  evaluation pits X against Y using a standardized test scene"; analysts, market researchers and observers, and experts
  who estimate, report, find, say or warn, only where what they say came out follows them: a that-clause, a market
  figure, a forecast or a trend, not "analysts estimate each ticket in story points" or "experts demonstrate how to
  shape a boule"; "in the 8K test", "in side-by-side test renders", "when tested on", "in a 2024 poll of", "a panel of
  senior artists" and experts who suggest, recommend or advise only where the sentence says a result came out: a verb
  in the past (not an -ed word that describes: "a panel of chefs on fermented foods", "discusses recycled packaging";
  nor one in a clause about someone, "judges, who between them founded ..."), or a score, a comparison of what it
  names ("Octane resolves finer detail than Redshift", "most artists prefer Octane's glass"; not "more than 12
  cheeses", "behind Ludlow Castle", "the loaf most visitors prefer") or a result in the present ("Octane clearly wins
  on glass", "picks Octane every time", "is the clear favourite") with nothing still to come, and not an instruction
  after its comma ("In the test render, make the Rim light brighter than the Key"): not "A panel of three judges will
  score each entry", "In a blind taste test, visitors will compare ...", "pupils check which soil drains better" or
  "Most experts suggest watering early", and for experts' advice only a verb in the past or a rating), and a source:
  figures that "were taken from" or "sourced from" somewhere outside the request (or taken from an official or
  published list), "according to" a report, an audit, a comparison or a name where it cites one ("According to the
  data" cites the step's given data), "publicly listed" prices, "from the vendor's website", "based on" the latest,
  official, public, a dated or a vendor's data, prices, list or catalogue ("based on the latest vendor catalogues",
  "each vendor's 2024 price list"; not "based on public transport" or "the 2024 summer timetable"), "per Autodesk's
  published pricing" or "per a 2024 Puget Systems benchmark" where it cites (at the start or after a comma, not
  instructing), "vendor quotes put", a vendor's site or price page that says a price ("Otoy's website lists the
  licence at $699", "as listed on Otoy's website", "Maxon's current list price"), a publisher of figures in brackets
  after them ("(Grand View Research)", "(Nielsen 2023)", "(per Nielsen)", "(Puget Systems, 2024)", "(Smith et al.,
  2021)") or saying what it found ("Statista reports", "Gartner predicts"), a study's own title with its year
  ("Bankrate Survey 2025", "Backlinko 2024 Content Length Study"), a "Source: ..." line, an "(Otoy pricing, 2024)",
  and a citation outside the sentences (_source_items: the items under a Sources or References heading, a footnote's
  line, a table's Source column, each only where it reads as one: a year, a link, a publisher, a study's noun). A mark
  qualifies the claims of its own clause ("(unverified)", "(assumed)", "is an assumption", "assumed estimate"; a label
  for the whole sentence, "Assumed: ..."; not a plain "assuming a five-seat plan"; "Octane costs $699 (assumed), and
  benchmarks show ..." marks the price), unless the claim is a run or a first-person measurement or survey: no mark
  makes "Tests were run (unverified)" or "We surveyed 40 artists (unverified)" true, and the research tell once brought
  a run back so marked. So do a condition ("if benchmarks show"), a denial ("No benchmarks were run", which the tell
  asks for; not "It's no secret that surveys indicate ..."), advice and a how-to's steps ("Update prices based on the
  latest vendor list", "Torque the wheel nuts per the manufacturer's specifications", "Per the manual, set ..."), a
  place in an app ("In the 4K render settings"), a source the request gives (the provided CSV, the brief, a step, the
  table above, this comparison) or a program reads (a file, an API: "data is pulled from the Sheets API"), "publicly
  listed companies", parts "sourced from" a supplier, "download it from the official website", "her patience was
  tested", a story's "we tested the ice" and a README's "in our unit tests". A measurement, result or source that the
  step's given data holds (given_material: its own words, its dependencies' pieces and the previous round's result;
  not the own words when a dependency is missing) is that data restated, not a claim; a run never is (_restates says
  how: label numbers are no data, a figure of the own words counts with its unit, a sentence with a mark gives no
  figures and no words to a result, a clause that says the data wasn't there, asks for it, points at another step or
  sets a target gives none, the blocks that hold what a claim with figures is about give its figures, and a claim with
  no figure needs a sentence of the material that says the data and half of what the claim says, not only its word).
  The smoke kept two sections at the judge's 4, with only their length named, that claimed a workstation's test runs
  and a vendor's website, and its checkers found pasted readings ("measured at 15-minute intervals") failed as
  invented;
- no plan step's id in the text (step_id_leak): "step s2", "s3's", "(see s4)", "from **s1**", also with U+202F or
  another no-break space; ids the plan doesn't have, an "s3 bucket", inline code, code blocks and the handoff
  aside. The joined result is read by the person, who never sees the plan;
- every row of a CSV (a ```csv block, a plain block that looks like one, or a run of comma lines under a header of
  three or more short fields) has its header's number of fields, quoted fields read as Python's csv module reads
  them (csv_fields: a smoke target had 8 fields a row under a 6-column header);
- every python block (a closed block tagged as Python, Chimera's pythonLang: what its result check could run) compiles
  (code_syntax, code_faults; since the fifth smoke, whose bad section example's packaging script didn't parse), a
  Blender script's also without the f-string forms only Python 3.12+ reads (older_fstring), since Blender 5.0.1 runs
  Python 3.11. Untagged blocks, shells and interactive sessions aren't read as code.

Words are counted in the section without its heading line, its code blocks and its handoff. For each of the last
four a failing check also gives a plain line for the next try's notes ("tell"; the other reasons get theirs from
task.py's _section_failures), quoting the model's own words (a python block's line that doesn't compile with
Python's message, or OLDER_FSTRING's for the f-string forms); a claim's says to leave the figure out and say the data
wasn't available (a research step's to omit any test, measurement or survey it says was done and mark unsure
figures (unverified): CLAIMS_TELL_RESEARCH), but a claim the given material makes only with a mark is told to keep the
mark (CLAIMS_TELL_MARK) and a claim with no figure whose data the material has is told to give the figure
(CLAIMS_TELL_CITE: _why); claims_why says which line each got. TELL_NOTES is their fixed wording, ours, for
hints.echoed_note.
"""
from __future__ import annotations

import ast
import collections
import csv
import functools
import io
import re
import sys
import textwrap
import tokenize
import warnings

from contract import planinfo
from contract import validate as cv
from contract.goport import BPY_IMPORT, code_blocks, python_lang

FAIL_WARNINGS = ("ai_talk", "unmarked_link", "placeholder", "heading_not_title")
TOLERANCE = 0.3
SHINGLE = 8
OVERLAP_MAX = 0.2

_WORDS = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_PLACEHOLDER = re.compile(r"\bTODO\b|\bTBD\b|\bFIXME\b|\blorem ipsum\b|\[\s*(?:insert|add|your|name of|link|url|"
                          r"citation needed|source|todo|tbd|placeholder)\b[^\]\n]*\]|<\s*insert\b[^>\n]*>|\{\{[^}\n]+\}\}",
                          re.I)

# Word targets. A number is 300, 1,000, 1.5k; "to" or a dash makes a range. gpt-oss writes "400‑word" and
# "≈70‑80 words" with U+2011 (453 of the 712 section steps in its stored plans have one), so U+2010-2012 and U+2212
# are read as "-".
_DASHES = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2212": "-"})
_N = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?\s?[kK]?)"
_W = r"[\s-]*words?\b"
# The nouns of a whole piece: "a 600-word section", "a 2,000-word decision memo" is the section's own length.
_WHOLE_NOUN = (r"(?:section|article|memo|guide|document|report|post|piece|essay|newsletter|overview|summary|letter|"
               r"press release|write-?up|explainer|chapter|handbook|manual|proposal|white ?paper|analysis)")
_PART_NOUN = r"(?:paragraph|intro(?:duction)?|conclusion|summary)"  # in one item of a list, a part's
_TARGETS = [  # (priority: lower wins, kind, pattern)
    (0, "range", re.compile(r"\bbetween\s+" + _N + r"\s+and\s+" + _N + _W, re.I)),
    (0, "range", re.compile(_N + r"\s*(?:-|–|—|to)\s*" + _N + _W, re.I)),
    (1, "max", re.compile(r"(?:\b(?:under|fewer than|less than|no more than|not more than|at most|up to|no longer than|"
                          r"shorter than|below|within|a maximum of|maximum of|maximum|max\.?|"
                          r"(?:not|never) exceed(?:ing)?)\s+|n't exceed\s+|(?:≤|<=)\s*)(?:of\s+)?" + _N + _W, re.I)),
    (1, "max", re.compile(_N + _W + r"\s+(?:or (?:less|fewer)|max(?:imum)?\b|at most|tops\b)", re.I)),
    (1, "max", re.compile(r"(?<![\w-])" + _N + r"-words?\s+(?:\w+\s+)?(?:limit|maximum|max|cap)\b", re.I)),
    (1, "min", re.compile(r"(?:\b(?:at least|no fewer than|no less than|a minimum of|minimum of|minimum|min\.?|"
                          r"more than|over|upwards of)\s+|(?:≥|>=)\s*)(?:of\s+)?" + _N + _W, re.I)),
    (1, "min", re.compile(_N + r"\s*\+" + _W + r"|" + _N + _W + r"\s+(?:or more|minimum|at least)\b", re.I)),
    (2, "about", re.compile(r"(?:\babout|\baround|\broughly|\bapproximately|\bapprox\.?|\bcirca|~|≈|\bsome|"
                            r"\bnearly|\bclose to)\s*" + _N + _W, re.I)),
    (2, "about", re.compile(r"(?<![\w-])" + _N + r"\s*±\s*\d+\s*words?\b", re.I)),  # "350 ±5 words"
    (2, "about", re.compile(r"\bin\s+(?:just\s+|only\s+)?" + _N + _W, re.I)),
    (3, "about", re.compile(r"(?<![\w±-])" + _N + r"\s+words?\b(?!-)", re.I)),
    (4, "about", re.compile(r"(?<![\w-])" + _N + r"-words?,?\s+(?:[\w-]+,?\s+){0,2}?(?:" + _WHOLE_NOUN +
                            r"|intro(?:duction)?|paragraph|description|explanation|answer|response|blurb|bio|"
                            r"abstract|note|review|conclusion|text|draft|story|email|update|statement|pitch|outline|"
                            r"primer|copy)\b", re.I)),  # not plurals: "three 600-word core sections" are items
]
# A target in a clause about items (each bullet, five tips, the captions) is each item's, not the section's.
_ITEM = (r"(?:bullets?|bullet points?|items?|entry|entries|sentences?|lines|captions?|tweets?|headlines?|titles?|"
         r"points?|tips?|questions?|answers?|examples?|descriptions?|cards?|slides?|rows?|labels?|paragraphs|"
         r"definitions?|blurbs?)")
_EACH = re.compile(r"\b(?:each|every|per)\s+(?:\w+\s+){0,3}?" + _ITEM + r"\b", re.I)
_ITEM_BEFORE = re.compile(r"\b(" + _ITEM + r")\s+((?:\w+\s+){0,3})$", re.I)
_A_THE = re.compile(r"\b(?:a|an|the)\s+(?:[\w-]+,?\s+){0,3}$", re.I)  # "a polished product " before "description of"
# "A compelling headline (max 10 words)", "`description` (exactly 120 words)"
_ITEM_BRACKET = re.compile(r"\b" + _ITEM + r"[`'\"*]*\s*[(\[](?:\s*[^\W\d]+\.?){0,2}$", re.I)
# ... but one item a sentence asks for is the section: "Write a blurb (max 120 words) for ...", "..., and write a
# single-paragraph description (max 150 words)"
_ONE_ITEM = re.compile(r"(?:^\s*|\b(?:and|then)\s+)(?:write|draft|develop|produce|compose|create|craft|prepare)\s+"
                       r"(?:a|an|the)\s+(?:[\w-]+,?\s+){0,3}?(" + _ITEM + r")[`'\"*]*\s*[(\[](?:\s*[^\W\d]+\.?){0,2}$",
                       re.I)
_EACH_JUST = re.compile(r"\b(?:each|every|per)$", re.I)  # "(each ~30-40 words)"
# "For each, write ...", "Then, for each tool, ...": a clause that starts so (not "code blocks for each snippet")
_FOR_EACH = re.compile(r"^\s*(?:[-*•]\s*|\d+[.)]\s*)?(?:\w+,?\s+)?for\s+(?:each|every)\b", re.I)
# "Each section should be ~550 words", "Ensure each summary does not exceed 150 words": a clause about each one
_EACH_SUBJECT = re.compile(r"^\s*(?:[-*•]\s*|\d+[.)]\s*)?(?:(?:ensure|make sure|keep|limit|cap)\s+(?:that\s+)?)?"
                           r"(?:each|every)\s+[\w-]+", re.I)
_CLAUSE = re.compile(r"[.;:!?\n]")
_EACH_AFTER = re.compile(r"^[\s)\]]*(?:each|apiece|per\b|for each|a (?:bullet|item|point|line|sentence|paragraph)|"
                         r"(?:[\w-]+\s+){1,2}for (?:each|every)\b)", re.I)
_LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s")
# A number for the whole section: a total of its length ("total word count of 2,000 words", "the total length should
# be about 500 words", "1,800 words in total", "(≈1,800 words total)"; not "the total cost"), or "a 600-word section"
# (a document noun after "N-word").
_TOTAL_BEFORE = re.compile(r"\b(?:total|overall)\s+(?:word[\s-]*count|length)\b[^.;!?\n]{0,60}$", re.I)
_TOTAL_AFTER = re.compile(r"^[\s)\]]*(?:in\s+)?(?:total|overall)\b", re.I)
_WHOLE_NW = re.compile(r"(?<![\w-])" + _N + r"-words?,?\s+(?:[\w-]+,?\s+){0,2}?(?P<noun>" + _WHOLE_NOUN + r")\b",
                       re.I)
_PART_NW = re.compile(r"(?<![\w-])" + _N + r"-words?,?\s+(?:[\w-]+,?\s+){0,2}?" + _PART_NOUN + r"s?\b", re.I)
# ... unless what it describes is something else: "summarize the 2,000-word report", "an outline for a 700-word
# article", "shorten the 1,200-word article", "the 2,000-word report from s1", "the 1,200-word article produced in s2"
_NAMES_OTHER = re.compile(r"\b(?:for|of|from|summari[sz](?:e|es|ed|ing)|outlin(?:e|es|ed|ing)|condens(?:e|es|ed|ing)|"
                          r"shorten(?:s|ed|ing)?|expand(?:s|ed|ing)?|rewrit(?:e|es|ing|ten)|rewrote|"
                          r"translat(?:e|es|ed|ing)|turn(?:s|ed|ing)?)"
                          r"\s+(?:(?:a|an|the|this|that|its|their|your|our|single|whole|full)\s+)*[~≈]?\s*$", re.I)
_THE_BEFORE = re.compile(r"\bthe\s+[~≈]?\s*$", re.I)
_MADE_IN_STEP = re.compile(r"^\s*(?:(?:that|which)\s+(?:was\s+)?)?(?:produced|written|drafted|created|generated|"
                           r"made)\s+(?:in|by)\s+(?:step\s+)?s\d+\b", re.I)

_INTRO = re.compile(r"\b(?:in this (?:document|article|guide|report|paper|post|tutorial|essay|write-?up|handbook|"
                    r"manual|proposal|book|e-?book|white ?paper|piece)\b|this (?:document|article|guide|report|paper|"
                    r"post|tutorial|essay|write-?up|handbook|manual|proposal|white ?paper) (?:will|aims|explores|"
                    r"covers|describes|outlines|examines|presents|provides|walks|looks|discusses|introduces|sets out)\b"
                    r"|the following sections\b|in the (?:sections|chapters|pages) (?:below|that follow|ahead)\b|"
                    r"welcome to (?:this|our|the)\b|without further ado\b|let'?s (?:dive in|get started)\b)", re.I)
_OUTRO = re.compile(r"\b(?:in conclusion|to conclude|this (?:document|article|guide|report|paper|post|tutorial|essay|"
                    r"memo) has (?:shown|covered|explored|described|outlined|presented))\b", re.I)
# These sum up a section as often as a whole document (gpt-oss ends sections with "In summary, ..."), so they count
# only in a paragraph that speaks of the whole: the document, the report, the sections above.
_WEAK_OUTRO = re.compile(r"\b(?:to summari[sz]e|to sum (?:it |this )?up|in summary|summing up|in closing|all in all|"
                         r"to wrap (?:it |this )?up|wrapping up)\b", re.I)
_WHOLE = re.compile(r"\b(?:this|the|our) (?:document|report|memo|guide|article|paper|post|tutorial|essay|proposal|"
                    r"write-?up|handbook|manual|white ?paper|e-?book|book)\b|\b(?:sections|chapters|parts) (?:above|"
                    r"before)\b|\b(?:above|previous|preceding) (?:sections|chapters|parts)\b", re.I)
_INTRO_TITLE = re.compile(r"\b(?:intro(?:duction|ductory)?|preface|foreword|opening|background|getting started|"
                          r"welcome|overview|abstract|executive summary|tl;?dr|summary)\b", re.I)
_OUTRO_TITLE = re.compile(r"\b(?:conclusions?|concluding|closing|wrap[- ]?up|final (?:thoughts|words|remarks)|"
                          r"summary|summari[sz]ing|recap|takeaways?|next steps|outlook|epilogue|afterword)\b", re.I)


# The words around a title that ask for the section rather than name it: a leading instruction verb (with "up" or
# "out" and an article), notes in brackets ("(≈600 words)") and a trailing "section".
_VERBS = (r"write|draft|compose|create|produce|prepare|summari[sz]e|describe|explain|add|give|provide|build|make|craft|"
          r"develop|generate|research|gather|find|identify|analy[sz]e|compare|propose|assemble|compile|collect|define|"
          r"translate|polish|finali[sz]e|proofread|rewrite|expand|present")
_LEAD = re.compile(r"^(" + _VERBS + r")\s+(?:(?:up|out)\s+)?((?:a|an|the)\s+)?", re.I)
_BRACKETS = re.compile(r"\s*[(\[][^()\[\]\n]*[)\]]")
_SECTION_WORD = re.compile(r"\s+section$", re.I)
_ARTICLES = {"a", "an", "the"}
# When bare_title isn't sure the verb asks rather than names, it keeps the title: what follows starts with a joining
# word ("Research and outline content"), still has a verb of its own ("Build final binary and provide build
# instructions"), the title isn't English (an accented letter, or a foreign article or function word in lower case
# right after the verb: "Analyse des garanties", not "Research Los Angeles venues"), or the verb is a word that is
# often a noun and the next word makes a role or compound noun with it ("Research Scientist – AI", "Present Day
# Challenges"; not "Research Windows Developer Laptop").
_JOINER = re.compile(r"^(?:(?:and|or|nor|vs|versus|of|to|for|with|in|on|by)\b|[&,/])", re.I)
_AND_VERB = re.compile(r"(?:\band|&)\s+(?:" + _VERBS + r"|outline|deliver|format|design|build|test|review|list|export|"
                       r"save|zip|refine|structure|convert|render|publish|upload|include|insert|combine|merge|check|"
                       r"verify|validate|edit|update|recommend|select|rank|evaluate|assess|calculate|estimate|plan|"
                       r"schedule|send|share|print|attach|summari[sz]e|contrast)\b", re.I)
# Articles and function words of French, Spanish, Italian, Portuguese or German, in lower case: a capitalised one
# right after the verb starts a name (Los Angeles, La Marzocco, Del Monte).
_FOREIGN_LEAD = re.compile(r"^(?:l['’]|(?:le|la|les|un|une|des|du|del|della|delle|dei|degli|el|los|las|die|der|das|"
                           r"dem|ein|eine|il|lo|gli|o|os|as|und|et|pour|avec|für|mit|sur|dans|para|por|con)\b)")
# ... and the same words in lower case anywhere after it ("Analyse juridique des garanties"), less the ones English
# has too (as, die, o, con, lo, il)
_FOREIGN_ANY = re.compile(r"(?<![\w'’])(?:le|la|les|un|une|des|du|del|della|delle|dei|degli|el|los|las|der|das|dem|ein|"
                          r"eine|gli|os|und|et|pour|avec|für|mit|sur|dans|para|por)(?![\w'’])")
_NOUNISH = {"research", "present", "make", "draft", "polish", "build", "analyse", "analyze"}
_ROLE = {"scientist", "scientists", "assistant", "associate", "engineer", "analyst", "lead", "manager", "director", "day",
         "findings", "paper", "papers", "question", "questions", "proposal", "results"}


def norm_title(s) -> str:
    """Go's normTitle (app/hydra_contract.go): lower-cased, anything but word and space characters made a space,
    spaces collapsed. As in the prototype (contract/validate.py), Python's lower() maps a few letters to more than
    one (İ to i and a combining dot) and lowers a final Σ to ς, where Go maps one letter to one: only those differ."""
    return " ".join(re.sub(r"[^\w\s]", " ", (s or "").lower()).split())


def _key(s) -> str:
    return " ".join(w for w in norm_title(s).split() if w not in _ARTICLES)


def _unsure(title, m) -> bool:
    """True when stripping lead verb match m off title (brackets gone) might cut a name."""
    rest = title[m.end():]
    if _JOINER.match(rest) or _AND_VERB.search(rest):
        return True
    if any(c.isalpha() and not c.isascii() for c in title) or _FOREIGN_LEAD.match(title[m.end(1):].lstrip()) or \
            _FOREIGN_ANY.search(rest):
        return True
    nxt = (rest.split(None, 1) or [""])[0].strip(".,:;!?\"'“”‘’*").lower()  # "day-by-day" is no "Day"
    return m.group(1).lower() in _NOUNISH and not m.group(2) and nxt in _ROLE


def _unquote(t) -> str:
    """t without the quotes or ** around all of it."""
    while True:
        t = t.strip()
        if len(t) > 4 and t.startswith("**") and t.endswith("**"):
            t = t[2:-2]
        elif len(t) > 2 and (t[0], t[-1]) in (('"', '"'), ("“", "”"), ("'", "'"), ("‘", "’"), ("`", "`")):
            t = t[1:-1]
        else:
            return t


def _plain_lower(word) -> bool:
    """A word of lower-case letters, or such words and numbers joined by dashes or a slash ("side‑by‑side",
    "sub‑$300", "encrypt/decrypt"); not "macOS", "items.toml" or "fetchData"."""
    parts = re.split("[-\u2010\u2011\u2012\u2013\u2014/]", word)
    return word[:1].isalpha() and word[:1].islower() and all(
        (p.isalpha() and p.islower()) or not any(ch.isalpha() for ch in p) for p in parts)


def bare_title(title) -> str:
    """The title without the words that ask for the section: "Write Current workflow audit (≈600 words)" gives
    "Current workflow audit", "Create a side-by-side comparison table" gives "Side-by-side comparison table". When
    it isn't sure (_unsure) it keeps the title without its bracketed notes; the title itself when the strip leaves
    nothing. Quotes and ** around the result go; the first letter is capitalised only after a verb was stripped and
    only on a plain lower-case word (macOS, items.toml and fetchData keep theirs). An inline "N-word" stays: the plan
    named the section so ("30-Word Summaries")."""
    whole = _BRACKETS.sub("", title or "").strip()
    m = _LEAD.match(whole)
    if m and _unsure(whole, m):
        t, stripped = whole, False
    else:
        t, stripped = (whole[m.end():] if m else whole), bool(m)
        t = _SECTION_WORD.sub("", t).strip(" \t:-–—")
    t = _unquote(t)
    if not _key(t):
        return (title or "").strip()
    first = t.split(None, 1)[0]
    if stripped and _plain_lower(first):
        t = t[:1].upper() + t[1:]
    return t


# A heading the instructions give outright. The name is quoted ("", “”, '', ‘’), backticked, or in ** or *, with
# ** around quotes allowed; a single quote closes only before a non-word character, so 'Owner's Guide' reads whole.
_Q = (r"""(?:\*\*)?(?:"([^"\n]{1,120})"|“([^”\n]{1,120})”|'([^\n]{1,120}?)'(?!\w)|‘([^\n]{1,120}?)’(?!\w)|"""
      r"""`([^`\n]{1,120})`)(?:\*\*)?|\*\*([^*\n]{1,120})\*\*|\*([^*\n]{1,120})\*""")
_GIVEN = [
    # 'Write the "Current workflow audit" section': paired quotes only, the opening one not after a letter
    re.compile(r"""(?<!\w)(?:\*\*)?(?:"([^"\n]{2,120})"|“([^”\n]{2,120})”|'([^\n]{2,120}?)'(?!\w)|"""
               r"""‘([^\n]{2,120}?)’(?!\w))(?:\*\*)?\s+section\b""", re.I),
    re.compile(r"\b(?:section|article|memo|piece|chapter|guide|post|report|write-?up|summary|introduction|conclusion|"
               r"heading|header)\s+(?:titled|entitled|headed|called|named)\s*:?\s*(?:" + _Q + ")", re.I),
    re.compile(r"\bunder\s+(?:the|a)\s+heading\s*:?\s*(?:" + _Q + ")", re.I),
    re.compile(r"\b(?:with|use|start with|begin with)\s+(?:the|a)\s+(?:markdown\s+)?heading\s*:?\s*(?:" + _Q + ")",
               re.I),
]
# `## 1. Installation`, anywhere, at Chimera's level only (not `# install python` or `### Pros`); only when the rest
# find none
_HASHED = re.compile(r"`\s*##\s+([^`\n]{1,120})`")
_ANOTHER = (re.compile(r"^\s*(?:from|of|in)\s+(?:step\s+)?s\d+\b", re.I),  # "the "X" section from s1": another step's
            re.compile(r"\b(?:using|from|based on)\s+(?:(?:the|a|an)\s+)?(?:\*\*)?$", re.I))
# a file (one word with a file's extension: config.lua, not "Getting Started with Node.js" or ASP.NET), an
# identifier, a <slot>
_NOT_A_NAME = re.compile(r"^\S+\.(?:md|txt|json|csv|pdf|docx|xlsx|py|js|ts|toml|yaml|yml|html|css|sh|lua|sql|ini|cfg)$|"
                         r"/$|\w_\w|<[^>]*>|\{[^}]*\}", re.I)
# A "section titled" in item 2 or later of a numbered list names a part when the step writes the whole document
_LATER_ITEM = re.compile(r"^\s*(\d+)[.)]\s")
_WHOLE_DOC = re.compile(r"\b(?:single|complete|full|entire|whole)\s+(?:[\w`.-]+\s+){0,2}?(?:document|markdown|text|"
                        r"content|file|memo|report|article|guide|readme)\b", re.I)
_CUE = re.compile(r"\btitled\b|(?<![\w-])heading\b|(?<!#)##(?!#)", re.I)  # not a sub-heading or "### Day X"
_NOT_A_CUE = re.compile(r"\b(?:table|list|matrix|file|sheet|spreadsheet|chart|column|tab)\s+titled\b|"
                        r"""\btitled\s*:?\s*\**[`"'“‘]?[^\s`"'”’*]+\.[A-Za-z][A-Za-z0-9]{0,5}(?![\w.])""", re.I)


def _name(raw) -> str:
    t = re.sub(r"^#+\s*", "", _unquote(raw or ""))
    t = re.sub(r"\s*:$", "", t.strip("* \t")).strip()
    return "" if not _key(t) or _NOT_A_NAME.search(t) else t


def _given(instructions):
    """(name or None, [spans of the names read and dropped as not a heading]). The patterns see the dashes made
    "-"; the name keeps the instructions' own characters."""
    raw = instructions or ""
    text = raw.translate(_DASHES)  # one character for one, so spans are the same in both
    hits, dropped = [], []
    whole = _WHOLE_DOC.search(text)
    for k, rx in enumerate(_GIVEN + [_HASHED]):
        if k == len(_GIVEN) and hits:
            break
        for m in rx.finditer(text):
            if k == 0 and (_ANOTHER[0].match(text[m.end():]) or _ANOTHER[1].search(text[:m.start()])):
                continue
            g = next(n for n in range(1, len(m.groups()) + 1) if m.group(n) is not None)
            name = _name(raw[m.start(g):m.end(g)])
            item = _LATER_ITEM.match(text[text.rfind("\n", 0, m.start()) + 1:])
            if k == 1 and whole and item and int(item.group(1)) >= 2:
                name = ""  # "2. A final recommendation section titled "Recommendation"": a part of the document
            (hits if name else dropped).append((m.start(), name, m.span()))
    hits.sort()
    return (hits[0][1] if hits else None), [d[2] for d in dropped]


def given_heading(instructions) -> str | None:
    """The heading the instructions give outright, else None: the first of '"X" section' (not another step's: 'the
    "X" section from s1', 'using the "X" section'), '<section, article, memo, ... heading> titled/entitled/headed/
    called/named "X"' (not in item 2 or later of a numbered list when the step writes the whole document: that
    names a part), 'under the heading "X"', 'with/use/start with the (markdown) heading "X"' and, when none of
    those, a backticked `## X`. Leading #s and *s and a trailing colon go; a file or identifier (config.lua, src/,
    snake_case) or a <slot> is no heading."""
    return _given(instructions)[0]


def unread_heading(step) -> bool:
    """True when the step's instructions speak of a heading ("titled", "heading", "##") that given_heading can't
    read: then the teacher is told to use the heading they give for the piece, and section_heading's only if they
    give none ("headings (##)" and "the park name as a level-2 heading" give the piece none).
    A table, list or file titled something, and the names given_heading read and dropped, aren't such a cue."""
    text = (step.get("instructions") or "").translate(_DASHES)
    name, dropped = _given(text)
    if name:
        return False
    for a, b in sorted(dropped, reverse=True):
        text = text[:a] + " " + text[b:]
    return bool(_CUE.search(_NOT_A_CUE.sub(" ", text)))


def section_heading(step) -> str:
    """The heading the teacher is asked to start with: the one the instructions give outright, else the bare title."""
    return given_heading(step.get("instructions")) or bare_title(step.get("title"))


def heading_fits(heading, step) -> bool:
    """A heading the step's own words give, articles and case aside: its title, the heading its instructions give
    outright, and its bare title when that differs from the title ("License Cost Breakdown for a Team of 5" for
    "Write License cost breakdown for team of 5 (≈400 words)"). When the instructions give a heading that shares a
    word with the title, the bare title no longer fits: a target with it would teach the worker to pass over the
    heading it was given. One that shares none may name a part, so the bare title still fits then."""
    k = _key(heading)
    title = step.get("title") or ""
    given = given_heading(step.get("instructions"))
    names = [title] + ([given] if given else [])
    if not given or not (_stems(given) & _stems(title)):
        names += [b for b in [bare_title(title)] if b != title]
    return bool(k) and any(n and k == _key(n) for n in names)


def _stems(s):
    """The first four letters of each word of four letters or more in s, lower-cased."""
    return {w[:4] for w in re.findall(r"[^\W\d_]{4,}", (s or "").lower())}


def _whole_phrase(heading, text) -> bool:
    return (" " + norm_title(heading) + " ") in (" " + norm_title(text) + " ")


def _num(s) -> float:
    s = s.replace(",", "").replace(" ", "")
    if s[-1:] in "kK":
        return float(s[:-1]) * 1000
    return float(s)


def _per_item(text, start, end, source=0) -> bool:
    """True when the length phrase at text[start:end] is each item's, not the section's (source 1: the title, whose
    "(≈600 words)" is always the section's)."""
    before = _CLAUSE.split(text[:start])[-1]
    tight = before.rstrip(" \t~≈")
    lines = text[:start].split("\n")
    m = _ITEM_BEFORE.search(before)
    if m and not (m.group(1)[-1:].lower() != "s" and m.group(2).lower().startswith("of ") and
                  _A_THE.search(before[:m.start()])):  # "a polished product description of about 250 words": one
        return True
    one = _ONE_ITEM.search(tight)  # "Write a blurb (max 120 words)": one, outside a list
    bracket = source == 0 and _ITEM_BRACKET.search(tight) and not (
        one and one.group(1)[-1:].lower() != "s" and not _LIST_ITEM.match(lines[-1]))
    if (_EACH.search(before) or _FOR_EACH.match(before) or _EACH_SUBJECT.match(before) or bracket or
            _EACH_JUST.search(tight.rstrip("( \t")) or _EACH_AFTER.match(text[end:end + 40])):
        return True
    # a list item under "For each knife, gather:"
    if len(lines) > 1 and _LIST_ITEM.match(lines[-1]):
        k = len(lines) - 2
        while k >= 0 and _LIST_ITEM.match(lines[k]):
            k -= 1
        return k >= 0 and bool(_FOR_EACH.match(_CLAUSE.split(lines[k].rstrip(" \t:"))[-1]))
    return False


def _lengths(text, source):
    """The length phrases of text, one per mention (overlapping matches are one, its kind and numbers from the match
    that ranks first, its phrase their whole span), each item's left out: [(prio, source, start, kind, nums, phrase,
    whole)]; whole when it is the whole section's."""
    found = []
    for prio, kind, rx in _TARGETS:
        for m in rx.finditer(text):
            nums = [_num(g) for g in m.groups() if g]
            if nums and all(n > 0 for n in nums):
                found.append((m.start(), m.end(), prio, kind, nums))
    groups = []
    for f in sorted(found):
        if groups and f[0] < groups[-1][1]:
            groups[-1][1] = max(groups[-1][1], f[1])
            groups[-1][2].append(f)
        else:
            groups.append([f[0], f[1], [f]])
    out = []
    for start, end, ms in groups:
        if _per_item(text, start, end, source):
            continue
        nw = _WHOLE_NW.search(text, start, min(len(text), end + 80))
        noun = nw is not None and nw.start() < end
        if noun and (_NAMES_OTHER.search(text[:nw.start()]) or _MADE_IN_STEP.match(text[nw.end():]) or (
                _THE_BEFORE.search(text[:nw.start()]) and _ANOTHER[0].match(text[nw.end():]))):
            continue  # "summarize the 2,000-word report", "the 2,000-word report from s1": not this section's
        total = bool(_TOTAL_BEFORE.search(text[max(0, start - 100):start]) or _TOTAL_AFTER.match(text[end:end + 20]))
        if not total and _list_part(text, start, end) and not (noun and nw.group("noun").lower() != "summary"):
            continue  # "1. A 250-word introductory paragraph", "- Executive Brief (≈250 words)": a part's
        _, _, prio, kind, nums = min(ms, key=lambda f: (f[2], f[0]))
        out.append((prio, source, start, kind, nums, text[start:end].strip(), noun or total))
    return out


# A requirements bullet that gives the whole piece's length: "- Approx. 2 pages (≈ 900 words).", "- Aim for ~1.5 pages
# (≈ 600 words)."
_WHOLE_ITEM = re.compile(r"\b(?:pages?|approx\.?|approximately|aim(?:ing)? for|length|in total|total|overall)\b", re.I)


def _list_part(text, start, end) -> bool:
    """True when the length phrase at text[start:end] is a part's ("N-word <paragraph, intro, conclusion,
    summary>", "X (N words)") in one item of a numbered or bulleted list of two or more items, unless the item gives
    the whole piece's length (_WHOLE_ITEM)."""
    part = _PART_NW.search(text, start, min(len(text), end + 80))
    if not ((part is not None and part.start() < end) or text[:start].rstrip(" \t~≈").endswith(("(", "["))):
        return False
    lines = text.split("\n")
    k = text.count("\n", 0, start)
    if not _LIST_ITEM.match(lines[k]) or _WHOLE_ITEM.search(lines[k]):
        return False
    n, a, b = 1, k - 1, k + 1
    while a >= 0 and (_LIST_ITEM.match(lines[a]) or not lines[a].strip()):
        n, a = n + bool(lines[a].strip()), a - 1
    while b < len(lines) and (_LIST_ITEM.match(lines[b]) or not lines[b].strip()):
        n, b = n + bool(lines[b].strip()), b + 1
    return n >= 2


def word_target(text, title=""):
    """The word target a step's instructions (text) and title set for its section: {"kind": about|range|max|min, "n":
    [numbers], "phrase", "low", "high", "whole"} with the 30% leeway applied (high None for no upper bound), or None.
    A whole-section number (whole: a total, a document noun after "N-word", a title's "(≈N words total)") wins; else
    the one count named, however it's phrased, or None when they name two or more different counts."""
    found = _lengths((text or "").translate(_DASHES), 0) + _lengths((title or "").translate(_DASHES), 1)
    if not found:
        return None
    whole = [f for f in found if f[6]]
    if not whole and len({tuple(sorted(set(f[4]))) for f in found}) > 1:
        return None  # a wrong band is worse than none
    _, _, _, kind, nums, phrase, is_whole = min(whole or found, key=lambda f: f[:3])  # the most exact kind first
    lo, hi = min(nums), max(nums)
    low, high = {"about": (lo * (1 - TOLERANCE), lo * (1 + TOLERANCE)),
                 "range": (lo * (1 - TOLERANCE), hi * (1 + TOLERANCE)),
                 "max": (0, hi * (1 + TOLERANCE)),
                 "min": (lo * (1 - TOLERANCE), None)}[kind]
    return {"kind": kind, "n": [int(n) if n == int(n) else n for n in nums], "phrase": phrase,
            "low": round(low), "high": None if high is None else round(high), "whole": is_whole}


def step_target(step):
    """word_target of a step: its instructions and its title."""
    return word_target(step.get("instructions") or "", step.get("title") or "")


NOTE_LOW, NOTE_HIGH = 0.75, 0.9  # the teacher's band, below the target: gpt-oss writes 1.15-1.45 times what it's told


def target_band(target):
    """(low, high) words for the teacher's note on a word_target, aimed below it because gpt-oss overshoots (stored
    replies and the first smoke seed: 1.16 to 1.44 times the target, also when told a band): about n is 0.75n to
    0.9n, a range a-b is 0.75a to 0.9b, under n is up to 0.85n (low 0), at least n is n or more (high None); never
    outside the band the check allows. None for no target."""
    if not target:
        return None
    lo, hi = min(target["n"]), max(target["n"])
    if target["kind"] == "max":
        return 0, round(hi * 0.85)
    if target["kind"] == "min":
        return round(lo), None
    low = max(target["low"], round(lo * NOTE_LOW))
    return low, max(low, min(target["high"], round(hi * NOTE_HIGH)))


def note_band(step):
    """target_band of the step's target (step_target), or None when it sets none."""
    return target_band(step_target(step))


# A step that asks for its own opening or closing, or whose title names the whole deliverable, may frame it.
_ASKS_INTRO = re.compile(r"\bintroduc(?:e|es|ing|tion|tory)\b|\bopening paragraph\b|\bopen with\b", re.I)
_ASKS_OUTRO = re.compile(r"\bconclu(?:de|des|ding|sion)\b|\bclosing paragraph\b|\bwrap-?up\b|\bfinal recommendation\b",
                         re.I)
_WHOLE_TITLE = re.compile(r"\b(?:full|complete|entire|whole)\b|\b(?:article|guide|report|memo|letter|post|newsletter|"
                          r"press release)s?\b|\ball sections\b", re.I)


def framing_checks(plan, i):
    """Which of "intro" and "outro" section_check looks for in step i's first and last paragraphs: none for a plan's
    only section or a step whose title names the whole deliverable (full, complete, entire, whole; article, guide,
    report, memo, letter, post, newsletter, press release; all sections), else those neither its title makes its job
    nor its instructions ask for (an introduction or opening, a conclusion, closing, wrap-up or final
    recommendation)."""
    steps = plan.get("steps") or []
    sections = [k for k, st in enumerate(steps) if st.get("kind") not in ("blender", "code")]
    if len(steps) < 2 or len(sections) < 2:
        return []
    title = (steps[i].get("title") or "").translate(_DASHES)
    asked = (steps[i].get("instructions") or "").translate(_DASHES)
    if _WHOLE_TITLE.search(title):
        return []
    return [why for why, rx, ask in (("intro", _INTRO_TITLE, _ASKS_INTRO), ("outro", _OUTRO_TITLE, _ASKS_OUTRO))
            if not rx.search(title) and not ask.search(asked)]


def framed_elsewhere(plan, i, ends) -> bool:
    """True when another section step's title makes one of ends ("intro", "outro") its job: only then do other
    steps open or close the document."""
    rxs = [{"intro": _INTRO_TITLE, "outro": _OUTRO_TITLE}[e] for e in ends]
    for k, st in enumerate(plan.get("steps") or []):
        if k != i and st.get("kind") not in ("blender", "code") and any(rx.search(st.get("title") or "") for rx in rxs):
            return True
    return False


def prose_lines(section):
    """The section's lines without its heading line and its fenced code blocks."""
    lines = (section or "").split("\n")
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    out, fence = [], None
    for l in lines:
        m = _FENCE.match(l)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not l.strip()[len(m.group(1)):]:
                fence = None
            continue
        if m:
            fence = m.group(1)
            continue
        out.append(l)
    return out


def words(section):
    """The section's words, lower-cased, as counted for its length and its shingles."""
    return [w.lower() for w in _WORDS.findall("\n".join(prose_lines(section)))]


def paragraphs(section):
    """The section's paragraphs (blank-line separated, headings left out), code blocks removed."""
    paras, cur = [], []
    for l in prose_lines(section) + [""]:
        if not l.strip() or re.match(r"^\s{0,3}#{1,6}\s", l):
            if cur:
                paras.append(" ".join(x.strip() for x in cur))
            cur = []
        else:
            cur.append(l)
    return paras


def shingles(ws, n=SHINGLE):
    return {tuple(ws[k:k + n]) for k in range(len(ws) - n + 1)}


# ---------------------------------------------------------------- claims, step ids and CSV rows

# The fixed wording of the lines a failed check gives the next try (ours, never a target: hints.echoed_note looks for
# TELL_NOTES in a reply). Each line quotes the model's own words, never ours. A claim's line gives the one route the
# prose judge (PROSE_SYSTEM: saying so and leaving the values under "assumed" counts; making them up doesn't) and
# Chimera's request (a failed dependency's "assume what you need and list it under assumed"; research's "never invent
# sources, links, numbers or quotes; mark anything uncertain (unverified)") both accept: the earlier "or call the
# figure an assumed estimate" kept the made-up figures, which the judge then marked down. A research step's line
# keeps its mark for figures only: "mark anything uncertain" brought back an invented test run with "(unverified)"
# added, and no mark makes a run true (_claims); "leave out any test or benchmark it says was run" left a "We
# surveyed 40 artists" to be marked, and no mark makes that true either. Never sent before round 4's wording (no
# stored record has a claims tell), so hints.RETIRED needn't keep the old ones.
CLAIMS_TELL = ("it presents a source, test or measurement it never had as fact ({quotes}): leave the figure out and "
               "say the data wasn't available (list it under assumed)")
CLAIMS_TELL_RESEARCH = ("it presents a source, test or measurement it never had as fact ({quotes}): omit any test, "
                        "measurement or survey it says was done; mark unsure figures (unverified)")
# A claim its given material has, but only marked unverified, keeps the mark; one whose data the material has (a
# survey's rows, a benchmark table) but that leaves out the figure it rests on gives that figure: "say the data wasn't
# available" would steer a next try to drop data the step was given.
CLAIMS_TELL_MARK = ("it states as fact what its given material marks unverified ({quotes}): keep that mark "
                    "(unverified) on it")
CLAIMS_TELL_CITE = ("it states a result without the figure from its given data that shows it ({quotes}): give that "
                    "figure, or leave the result out")
STEP_ID_TELL = ("it names plan steps ({quotes}), which the person reading the result never sees: say what that "
                "step made instead")
CSV_TELL = ("CSV row {row} has {fields} fields where its header has {header}: give every row the header's fields, "
            "and quote a field that holds a comma")
# A python block of the section that doesn't compile (code_faults; after the fifth smoke, whose bad section example,
# blender-0008-00 s6, was a packaging script with a key opened by " and closed by ' inside an f-string): {error} is
# Python's own message, or for a Blender script one of OLDER_FSTRING's (ours) when only the f-string forms Python 3.12
# added stop it (Blender 5.0.1 runs Python 3.11, 5.2.2 runs 3.13, and the gate runs Blender pieces in both).
CODE_TELL = "its python block doesn't compile, so none of it can run: fix its line {line} ({quote}): {error}"
OLDER_FSTRING = {"quote": "inside an f-string's braces it uses that f-string's own quote mark; use the other quote "
                          "there",
                 "backslash": "a backslash inside an f-string's braces; work that part out before the f-string",
                 "hash": "a # comment inside an f-string's braces; move the comment out of the f-string",
                 "break": "a line break inside the braces of an f-string written in single quotes; keep that field on "
                          "one line"}
TELL_NOTES = tuple(dict.fromkeys([p.strip(" :,") for t in (CLAIMS_TELL, CLAIMS_TELL_RESEARCH, CLAIMS_TELL_MARK,
                                                              CLAIMS_TELL_CITE, STEP_ID_TELL, CSV_TELL, CODE_TELL)
                                  for p in re.split(r"\(\{\w+\}\)|\{\w+\}", t) if len(p.split()) >= 5] +
                                 list(OLDER_FSTRING.values())))
TELL_REASONS = ("claims_source", "step_id_leak", "csv_fields", "code_syntax")  # the reasons whose line is the gate's
# own "tell"
CODE_ERROR_CHARS = 100  # of Python's message a code_syntax line quotes, so the line fits hints.FAILURE_CHARS (240)
QUOTE_CHARS = 40  # of each phrase quoted, so the longest line fits hints.FAILURE_CHARS (240)
QUOTES_KEEP = 2

_HIDDEN = re.compile("[\u200b-\u200d\u2060\ufeff]")  # zero-width characters, read as a space ("step\u2060s2")
_INLINE_CODE = re.compile(r"(`+)[^`\n]*?\1")
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"'”’)\]*_]*\s+")
# A mark that qualifies the claim: "(unverified)", "(assumed)", "(an assumption for this memo)", an "Assumed:" label,
# "is an assumption", "were assumed", "assumed estimate(s)", "assumed figures". A plain "assuming a five-seat plan"
# qualifies nothing, and cleared a sentence that claimed a vendor's website.
_MARKED = re.compile(r"\bunverified\b|\bassumed\s+estimates?\b|"
                     r"[(\[]\s*(?:an?\s+)?(?:assumed|assumptions?)\b[^()\[\]]*[)\]]|"
                     r"^[\W_]*assum(?:ed|ptions?)[\s*_]*[:–—-]|"
                     r"\b(?:is|are|was|were|be|been|being)\s+(?:(?:an?|our|my|only|all)\s+)?(?:assumed|assumptions?)\b|"
                     r"\bassumed\s+(?:figures?|values?|numbers?|prices?|pricing|rates?|costs?|data|totals?|amounts?)\b",
                     re.I)
# A claim inside "if", "whether" or "until" is a condition, not a claim: "Re-run if benchmarks show a gap".
_CONDITION = re.compile(r"\b(?:if|whether|unless|until|in case|to see)\b[^,;:()]{0,50}$", re.I)
# ... and one denied says what wasn't done ("No benchmarks were run", "we ran no tests"), as the tell asks
_NEGATED = re.compile(r"(?:\b(?:no|not|never|without|nor|neither|none)\b|n['’]t\b)[^,;:()]{0,30}$", re.I)
_NEGATION = re.compile(r"\b(?:no|not|never|none)\b", re.I)
# What a figure is: "This figure was taken from ...", "Prices were sourced from ..." (not "parts sourced from OEM
# suppliers" or "a license is taken from the pool")
_DATA = (r"(?:figures?|numbers?|data|prices?|pricing|costs?|rates?|fees?|values?|statistics|stats|results?|scores?|"
         r"measurements?|estimates?|quotes?|specs?|specifications|information|info|details|totals?|amounts?|"
         r"salar(?:y|ies)|ratings?|rankings?|percentages?|counts?|metrics?|readings?|timings?|benchmarks?|"
         r"citations?)")
_TAKEN = r"(?:taken|sourced|obtained|pulled|drawn|gathered|collected|copied|quoted|compiled|scraped|retrieved)"
# Who or what "according to" may cite (not "according to the schedule", "according to your needs")
_SOURCE = (r"(?:reports?|stud(?:y|ies)|surveys?|data|figures|statistics|stats|research|analys[ie]s|benchmarks?|"
           r"reviews?|tests?|testing|estimates?|sources?|records|listings?|price\s+lists?|datasheets?|"
           r"spec(?:ification)?\s+sheets?|filings?|polls?|census|websites?|site|press\s+releases?|announcements?|"
           r"experts?|analysts?|researchers?|scientists?|vendors?|manufacturers?|makers?|publishers?|insiders?|"
           r"audits?|comparisons?|evaluations?)")
_TEST = r"(?P<key>tests?|testing|trials?|benchmarks?|benchmarking|measurements?|experiments?)"
# "in our tests folder", "In the 4K render settings, set ...": a place, not a test
_NOT_A_FOLDER = (r"(?!\s*(?:/|folders?|director(?:y|ies)|dir|suites?|files?|modules?|environments?|settings?|"
                 r"options?|panels?|tabs?|propert(?:y|ies)|menus?|dialogs?|preferences|presets?)\b)")
# What "based on" a public, official, dated or vendor's something has to be to claim a source: "based on official
# 2024 figures", "based on the latest vendor catalogues" (not "based on public transport", "the 2024 summer
# timetable" or "the official curriculum")
_SOURCED = (r"(?:" + _DATA + r"|catalogu?es?|catalogs?|lists?|listings?|datasheets?|websites?|sites?|pages?|"
            r"sheets?|reports?|surveys?|stud(?:y|ies)|research|filings?|records|sources?)")
_VENDOR = r"(?:vendors?|manufacturers?|suppliers?|compan(?:y|ies)|developers?|makers?|publishers?)(?:['’]s|s['’]|['’])?"
_RESULT_VERBS = (r"shows?|showed|demonstrate[sd]?|suggests?|suggested|indicates?|indicated|finds?|found|"
                 r"reveal(?:s|ed)?|confirm(?:s|ed)?|prove[sd]?|reports?|reported|estimates?|estimated")
_ADVICE = r"suggest(?:s|ed)?|recommend(?:s|ed)?|advise[sd]?"
# Where "analysts" or "experts" start what they say, and the words that may come first ("Industry analysts estimate")
_WHO_LEAD = (r"(?P<lead>^|[,;:(]\s*|\b(?:that|and|but|as|while|since|because|yet)\s+)(?:(?:recent|latest|new|"
             r"independent|industry|market|academic|several|many|multiple|most|some|numerous|external|third-party|"
             r"leading)\s+)*")
_NOT_TO = r"(?!\s+(?:to|directly|into)\b)"  # "Analysts report to the head of research" is who they answer to
# Who else says how a market or a field stands, as analysts do ("Market researchers estimate", "Industry observers
# expect"), and the verbs they say it with
_SAYERS = r"(?:analysts|economists|forecasters|strategists|observers|researchers|commentators|insiders)"
_SAYS = (r"say|said|says|note[sd]?|believe[sd]?|warn(?:s|ed)?|agree[sd]?|think|thinks|thought|argue[sd]?|"
         r"predict(?:s|ed)?|expect(?:s|ed)?|anticipate[sd]?")
# Adverbs between a study and its verb ("Studies consistently show"), and what it has shown ("Research has shown")
_ADV = (r"(?:(?:also|consistently|clearly|repeatedly|increasingly|generally|often|now|further|even|independently|"
        r"largely|broadly|overwhelmingly)\s+)?")
_SHOWN = r"(?:shown|found|demonstrated|indicated|suggested|revealed|confirmed|proven|proved|established)"
_FOUND = (r"(?:showed|found|revealed|indicated|confirmed|demonstrated|proved|concluded|reported|measured|recorded|"
          r"put|placed|gave|rated|ranked|(?:has|have)\s+(?:also\s+)?" + _SHOWN + r")")
_FINDS = r"(?:shows|finds|reveals|indicates|confirms|demonstrates|proves|concludes|puts|places|suggests|suggested)"
# The start of "The benchmark found", "A blind test found that ...", "Puget Systems' 2024 benchmark found", what may
# follow its noun ("A survey of 2,000 campers found", "A study published in Nature found"), a word that says which test
# (not a unit or an integration test), and what a finding mustn't be followed by ("The test shows how to ...")
_THE = r"\b(?:a|an|the|this|that|one|their|its|(?-i:[A-Z])[\w&.-]*(?:\s+(?-i:[A-Z])[\w&.-]*)?['’]s?)\s+"
_BY = (r"(?:(?:by|of|from|at|in|across|published\s+in|conducted\s+by|run\s+by|commissioned\s+by|carried\s+out\s+by)"
       r"\s+(?:[\w&.,'’-]+\s+){1,6}?)?")
_QUAL = (r"(?:(?!(?:unit|integration|regression|smoke|e2e|end-to-end|automated|ci|pregnancy|blood|eye|driving)\b)"
         r"[\w&.'’-]+\s+)")
_NOT_HOW = r"(?!\s+(?:how|you|users|readers|whether|if|to|where|what|which|when)\b)"
# Publishers of market and research figures, and a name ending in a research body's word ("Grand View Research",
# "Mordor Intelligence", "Pew Research Center"): a source the request rarely gives
_FIRM = (r"(?:(?-i:Statista|Gartner|IDC|Forrester|Nielsen|McKinsey|Deloitte|PwC|KPMG|Accenture|Euromonitor|Mintel|Pew|"
         r"YouGov|Ipsos|Kantar|eMarketer|Insider\s+Intelligence|IBISWorld|Bankrate|Morningstar|Moody['’]s|"
         r"Puget\s+Systems|Comscore|GfK|Circana|NPD|Counterpoint|Canalys|Omdia|Technavio|MarketsandMarkets|"
         r"Frost\s+&\s+Sullivan|Bloomberg\s+Intelligence|Chartable|Backlinko|SHRM|CFPB|Gallup|Edison\s+Research)|"
         r"(?-i:[A-Z])[\w&.'’-]*(?:\s+(?-i:[A-Z])[\w&.'’-]*){0,3}\s+(?-i:Research|Insights|Intelligence|Analytics|"
         r"Institute|Consulting|Bureau|Agency)(?:\s+(?-i:Center|Centre|Group))?)")
# A study's own title, capitalised, with its year ("Bankrate Survey 2025", "CFPB Financial Well-Being Survey 2024",
# "Backlinko 2024 Content Length Study", "Nielsen Total Audience Report (2024 Q2)")
_TITLED = r"(?-i:Survey|Study|Report|Index|Census|Poll|Barometer|Outlook|Tracker)"
# People a survey asks ("62% of artists surveyed", "Of the 500 artists polled")
_ASKED = (r"(?:people|adults|users|customers|clients|artists|members|consumers|buyers|shoppers|campers|participants|"
          r"employees|staff|workers|students|parents|teachers|developers|designers|readers|visitors|owners|households|"
          r"businesses|companies|firms|retailers|travell?ers|millennials|teens|respondents|those|gardeners|growers|"
          r"homeowners|drivers|riders|players|gamers|viewers|listeners|patients|managers|leaders|executives|"
          r"professionals|freelancers|nomads|creators|americans|britons|europeans|adults|women|men)")
# Each claim's kind: "ran" says a test, benchmark or trial was run, which no material a step is given can make true
# (Chimera runs nothing for a section) and no mark qualifies, so it is always a claim; "measure" (a measurement
# taken), "results" (what a benchmark, study or survey showed) and "source" (figures from somewhere) may be the step's
# given data (_restates). Named groups say more: key names what the claim is about, for _restates, and kw_<word> adds
# <word> ("62% of respondents" is about a survey: kw_survey); src marks where a source's name starts and name where
# it is (else _cited reads on to the first punctuation); self marks a first-person measurement or survey ("We surveyed
# 40 artists"), which no mark qualifies either; soft marks a shape that how-to and event prose use too (a panel of
# judges, a blind taste test, "experts suggest"), a claim only where the sentence says a result came out (_done), and
# advice one that experts' advice is (_done without comparisons); said a measured figure, not a target, a limit or
# advice (_matches); outcome a source that names people who also plan,
# teach or estimate tickets (analysts, experts), a claim only where what they say came out follows (_OUTCOME); needfig
# a bracket that cites only after a figure; survey an "n = 1,200" only beside a survey's words (_SURVEYISH).
_CLAIMS = [(kind, re.compile(p, re.I)) for kind, p in (
    ("ran", r"\b" + _TEST + r"\s+(?:were|was|have\s+been|had\s+been)\s+(?:run|conducted|performed|carried\s+out|done|"
            r"executed|made|taken|recorded)\b"),  # "Tests were run on an identical workstation"
    # with a number in the sentence: "We tested five laptops: the X lasted 14 h", not a story's "we tested the ice";
    # "benchmarked" and "profiled" say a run in any sentence, and so does testing or rendering both, each or the same
    ("ran", r"\b(?:we|I)\s+(?:(?:have|had|also|then|first|recently|independently|personally)\s+)*(?:tested|"
            r"timed)\b(?=.*\d)"),
    ("ran", r"\b(?:we|I)\s+(?:(?:have|had|also|then|first|recently|independently|personally)\s+)*(?:benchmarked|"
            r"profiled)\b"),
    ("ran", r"\b(?:we|I)\s+(?:(?:have|had|also|then|first|recently|independently|personally)\s+)*(?:tested|timed|"
            r"rendered|compared|measured)\s+(?:both|each|all|every|the\s+same|an?\s+identical|identical|"
            r"two|three|four|five|six|several|multiple)\b"),
    # first-person ("self"): no mark clears it, as none clears a run (_claims); a survey or an interview says one in
    # any sentence, the rest with a number
    ("measure", r"\b(?P<self>)(?:we|I)\s+(?:(?:have|had|also|then|first|recently|independently|personally)\s+)*"
                r"(?P<key>measured|found|observed|recorded|logged)\b(?=.*\d)"),
    ("measure", r"\b(?P<self>)(?:we|I)\s+(?:(?:have|had|also|then|first|recently|independently|personally)\s+)*"
                r"(?P<key>surveyed|polled|interviewed|questioned)\b(?P<kw_survey>)"),
    ("measure", r"\b(?P<self>)(?:we|I)\s+(?:(?:have|had|also|then|first|recently|independently|personally)\s+)*"
                r"(?P<key>measured)\s+(?:the\s+|our\s+|their\s+)?(?:[\w-]+\s+)?(?:times?|speeds?|performance|"
                r"throughput|latency|noise)\b"),  # "We measured render times on the studio's workstation"
    ("ran", r"\b(?:we|I)\s+ran\s+(?:[\w-]+\s+){0,3}?(?:tests?|benchmarks?|trials?|experiments?|renders?|"
            r"simulations?)\b"),
    ("ran", r"\b(?:were|was|have\s+been|had\s+been)\s+(?:benchmarked|profiled)\b"),  # not "her patience was tested"
    ("ran", r"\b(?:were|was|have\s+been|had\s+been)\s+(?:evaluated|compared|rendered|run|tested|benchmarked|timed|"
            r"measured)\s+(?:on|using|with|against)\s+(?:the\s+same|an?\s+identical|identical)\b"),
    # "draws on a controlled benchmark that rendered the same scene"
    ("ran", r"\b(?:a|an|the|our)\s+(?:[\w-]+\s+){0,2}?(?:benchmarks?|tests?|trials?)\s+(?:that|which)\s+(?:rendered|"
            r"ran|measured|tested|compared|timed)\b"),
    # "Our tests show", "Our benchmark rendered the scene in 4 min 12 s"
    ("ran", r"\b(?:our|my)\s+(?:own\s+|internal\s+|in-house\s+)?(?:[\w-]+\s+)?" + _TEST + r"\s+(?:" + _RESULT_VERBS +
            r"|find|rendered|ran|took|recorded|measured|timed|clocked|gave|put|produced|completed|finished)\b"),
    # "In our testing", "In our 8K tests", "In our side-by-side tests", "In our assumed tests" (a run no mark makes
    # true; not "in our unit tests", which a README's testing section means)
    ("ran", r"\bin\s+(?:our|my)\s+(?:(?:own|internal|in-house|\d+(?:\.\d+)?\s?[KkMm]|side-by-side|head-to-head|blind|"
            r"controlled|pilot|assumed|hypothetical|illustrative|initial|preliminary|recent|latest|lab|field|render|"
            r"quality|speed|real-world|informal|quick|early|first|earlier|limited|small|comparison|benchmark)\s+)"
            r"{0,2}" + _TEST + r"\b" + _NOT_A_FOLDER),
    ("ran", r"\bbased\s+on\s+(?:our|my)\s+(?:own\s+|internal\s+|in-house\s+)?(?:tests?|testing|benchmarks?|"
            r"benchmarking|trials?|experiments?|measurements?)\b"),  # "Based on our testing, ..."
    # "In the 8K test it reproduced ...", "In side-by-side test renders of a brushed aluminium case", "In head-to-head
    # benchmarks, ..." (not "In a blind taste test, visitors will compare ...")
    ("results", r"\bin\s+(?:(?:the|a|an|these|those)\s+)?(?:\d+(?:\.\d+)?\s?[KkMm]|side-by-side|head-to-head|"
                r"controlled|blind|identical)\s+(?:[\w-]+\s+)?(?P<key>tests?|benchmarks?|trials?|test\s+renders?|"
                r"renders?)\b" + _NOT_A_FOLDER + r"(?P<soft>)"),
    ("results", r"\b(?:in|from|across)\s+(?:the\s+|these\s+)?(?:[\w-]+\s+){0,2}?(?P<key>test)\s+(?:renders?|shots?)\b"
                r"(?P<soft>)"),
    # "in the assumed benchmark (48 dB vs 45 dB)": a result the section made up and named so
    ("results", r"\bin\s+(?:the|this|these|an?)\s+(?:assumed|hypothetical|illustrative|representative|simulated|"
                r"notional|imagined)\s+(?:[\w-]+\s+)?(?P<key>tests?|benchmarks?|trials?|comparisons?|runs?)\b" +
                _NOT_A_FOLDER),
    # "When tested on an RTX 4090, Octane rendered ..." (where a result came out: not "When tested with a meter, a good
    # battery reads 12.6 V")
    ("results", r"\b(?:when|once|as)\s+(?:tested|benchmarked|timed|measured|profiled)\s+(?:on|with|against|using|at|"
                r"in|under|side\s+by\s+side)\b(?P<kw_test>)(?P<soft>)"),
    # "(subjective score based on a panel of senior artists)" (not "A panel of three judges will score each entry")
    ("results", r"\b(?:a|an|our|the)\s+(?P<key>panel)\s+of\s+(?:[\w-]+\s+){0,2}?(?:artists|experts|judges|reviewers|"
                r"users|testers|engineers|designers|specialists|professionals|evaluators|raters|participants|"
                r"customers|viewers|critics|people|members|developers|students|chefs|tasters|colleagues|staff|growers|"
                r"gardeners|farmers|buyers|readers|listeners|players|volunteers)\b(?P<soft>)"),
    # "Measured noise levels (average per-pixel variance) were 0.0018 %" (a number after: not "a measured rollout was")
    ("measure", r"\b(?P<key>measured)\b[^.!?;\n]{0,80}?\s(?:was|were)\s+(?:(?:about|around|roughly|approximately|only|"
                r"just|consistently)\s+)?[<>≤≥~≈]?\s*[$€£]?\d(?:[\d,]*\d)?(?:\.\d+)?"),
    ("measure", r"\b(?:was|were|been)\s+(?P<key>measured)\s+(?:at|as|to\s+be|by|with|using|on|against|over)\b"),
    ("measure", r"\(\s*(?P<key>measured)\s+(?:by|with|using|on|at|against)\b"),  # "0.78 % (measured by NIQE)"
    # "as logged by the sensors"
    ("measure", r"\b(?:as\s+)?(?P<key>logged|recorded|measured|monitored|captured|metered)\s+by\s+(?:the|our|a|an|its|"
                r"their|each)\s+(?:[\w-]+\s+){0,2}?(?:sensors?|loggers?|meters?|gauges?|probes?|thermometers?|"
                r"monitors?|instruments?|devices?|equipment)\b"),
    # "Measured render times favour Octane on every scene"
    ("measure", r"\b(?P<key>measured)\s+(?:[\w-]+\s+){0,2}?(?:times?|values?|speeds?|levels?|scores?|results?|"
                r"figures?|temperatures?|readings?|noise|rates?|yields?|data)\s+(?:\w+ly\s+)?(?:show(?:s|ed)?|"
                r"favou?r(?:s|ed)?|suggest(?:s|ed)?|indicate[sd]?|confirm(?:s|ed)?|puts?|gave|give|reveal(?:s|ed)?|"
                r"point)\b"),
    # A measured result with no test word: an image metric with its figure ("an SSIM of 0.98 at 48 SPP", "| SNR | 32 dB
    # |") and a render time ("render times of 30-45 minutes per frame", "| Total render time (8 K) | 12 min 02 s |"),
    # restated only where the material holds the metric
    ("measure", r"\b(?P<key>(?-i:SSIM|PSNR|SNR|NIQE|LPIPS)|signal[\s-]to[\s-]noise)\b[^.;|)\n]{0,40}?\d(?P<said>)"),
    ("measure", r"\b(?P<key>render(?:ing)?)[\s-]+times?\b[^.;\n]{0,60}?\b\d+(?:\.\d+)?\s*(?:min|mins|minutes|s|sec|"
                r"secs|seconds|h|hrs|hours)\b(?P<said>)"),
    # ... and a noise level in dB ("| Noise (dB) at 64 SPP | -22 dB |")
    ("measure", r"\b(?P<key>noise)\b[^.;\n]{0,40}?[-‑−]?\d+(?:\.\d+)?\s*dB\b(?P<said>)"),
    ("results", r"\b(?P<key>benchmarks?)\s+(?:results?\s+|data\s+|tests?\s+|runs?\s+|scores?\s+)?" + _ADV +
                r"(?:show(?:s|ed)?|demonstrate[sd]?|reveal(?:s|ed)?|indicate[sd]?|confirm(?:s|ed)?|prove[sd]?|"
                r"found|finds|puts?|place[sd]?|suggest(?:s|ed)?|(?:have|has)\s+(?:also\s+)?" + _SHOWN + r")\b"),
    # "Tests show", "Testing revealed", "Independent trials have shown", "Benchmarking by Puget Systems shows" (with a
    # lead, as research's: not "the tests show how to call it"; not unit, integration or regression tests)
    ("results", r"(?P<lead>^|[,;:(]\s*|\b(?:that|and|but|as|while|since|because|yet)\s+)(?:(?:independent|third-party|"
                r"recent|lab|laboratory|real-world|field|blind|controlled|side-by-side|head-to-head|extensive|"
                r"repeated|multiple|several|many|published|industry)\s+)*(?P<key>tests|testing|trials|experiments|"
                r"benchmarking)\s+(?:(?:by|from|at|of)\s+(?:[\w&.,'’-]+\s+){1,5}?)?" + _ADV + r"(?:show(?:s|ed)?|"
                r"demonstrate[sd]?|reveal(?:s|ed)?|indicate[sd]?|confirm(?:s|ed)?|prove[sd]?|found|finds|puts?|"
                r"suggest(?:s|ed)?|(?:have|has)\s+(?:also\s+)?" + _SHOWN + r")\b(?!\s+(?:how|you|where|when)\b)"),
    # "The modest performance edge observed in the benchmark"
    ("results", r"\b(?:observed|measured|recorded|found)\s+in\s+(?:the|our|a|an|these|those|both)\s+(?:[\w-]+\s+){0,2}?"
                r"(?P<key>benchmarks?|tests?|trials?|experiments?)\b" + _NOT_A_FOLDER),
    # "Research shows", "Surveys indicate", "Industry data suggests", "Studies have shown", "Studies consistently
    # show" (not "the weekly report shows")
    ("results", r"(?P<lead>^|[,;:(]\s*|\b(?:that|and|but|as|while|since|because|yet)\s+)(?:(?:recent|latest|new|"
                r"independent|industry|market|academic|several|many|multiple|most|some|numerous|external|third-party|"
                r"published|peer-reviewed|scientific)\s+)*(?P<key>research|stud(?:y|ies)|surveys|polls|reports|"
                r"industry\s+data|market\s+data)\s+(?:(?:of|among|across)\s+(?:[\w&.,'’-]+\s+){1,4}?)?" + _ADV +
                r"(?:" + _RESULT_VERBS + r"|puts?|(?:have|has)\s+(?:also\s+|consistently\s+|repeatedly\s+)?" + _SHOWN +
                r")\b"),
    # "Data shows 40% of campers own a power bank", "Statistics show that ..." (with a figure or a that-clause)
    ("results", r"(?P<lead>^|[,;:(]\s*|\b(?:that|and|but|as|while|since|because|yet)\s+)(?P<key>data|statistics|"
                r"stats)\s+(?:shows?|suggests?|indicates?|reveals?|confirms?)\b(?=\s+that\b|[^.!?]*\d)"),
    # "Recent data suggests", "Industry figures put the market at $1.2 billion" (figures with a word that says whose)
    ("results", r"(?P<lead>^|[,;:(]\s*|\b(?:that|and|but|as|while|since|because|yet)\s+)(?:(?:recent|latest|new|"
                r"industry|market|official|government|national|published|independent|historical|public|census|sales|"
                r"global|available)\s+)+(?P<key>data|figures|statistics|stats|numbers|evidence)\s+" + _ADV + r"(?:" +
                _RESULT_VERBS + r"|puts?|(?:have|has)\s+" + _SHOWN + r")\b"),
    # Analysts and those like them are a source, as industry data is, where what they say came out follows: "Analysts
    # estimate the market will reach ...", "Analysts report strong demand", "Market researchers estimate the market
    # will reach ..." (not "Analysts report to the head of research", "analysts estimate each ticket in story points")
    ("results", _WHO_LEAD + r"(?P<key>" + _SAYERS + r")\s+(?:\w+ly\s+)?(?:" + _RESULT_VERBS + r"|" + _ADVICE + r"|" +
                _SAYS + r"|forecast(?:s|ed)?|project(?:s|ed)?|see|saw)\b" + _NOT_TO + r"(?P<outcome>)"),
    # ... and so are experts who estimate, report, indicate, find, show, say or warn ("Experts indicate that buyers
    # expect ...", not "experts demonstrate how to shape a boule")
    ("results", _WHO_LEAD + r"(?P<key>experts)\s+(?:\w+ly\s+)?(?!(?:" + _ADVICE + r")\b)(?:" + _RESULT_VERBS + r"|" +
                _SAYS + r"|consider(?:s|ed)?)\b" + _NOT_TO + r"(?P<outcome>)"),
    # ... while experts' advice is how-to prose: "Experts suggested ..." (not "Most experts suggest watering early")
    ("results", _WHO_LEAD + r"(?P<key>experts)\s+(?:" + _ADVICE + r")\b(?P<soft>)(?P<advice>)"),
    # "A 2023 study found", "The latest Steam hardware survey reports" (its first word says which)
    ("results", r"\b(?:a|an|the|one|this)\s+(?:recent|latest|new|independent|\d{4}|(?-i:[A-Z])[\w&.'’-]*|industry|"
                r"market|global|national|annual|academic|peer-reviewed|published|large|major)\s+(?:[\w&.'’-]+\s+){0,2}?"
                r"(?P<key>study|survey|poll|report|paper|analysis|review)\s+(?:" + _RESULT_VERBS + r")\b"),
    # "The benchmark found", "A blind test found that 7 of 10 artists ...", "The side-by-side test showed", "A survey of
    # 2,000 campers found", "Puget Systems' 2024 benchmark found", "A study published in Nature found"; a comparison or
    # an evaluation only in the past ("This comparison shows how the plans differ" describes the section)
    ("results", _THE + r"(?:[\w&.'’-]+\s+){0,3}?(?P<key>benchmarks?|stud(?:y|ies)|surveys?|polls?|census)\s+" + _BY +
                _ADV + r"(?:" + _FOUND + r"|" + _FINDS + r")\b" + _NOT_HOW),
    # ... and a test, trial or experiment, in the present only with a word that says which ("The side-by-side test
    # shows"; not "The test shows the parser handles empty rows"), never a unit or an integration test
    ("results", _THE + _QUAL + r"{0,3}?(?P<key>tests?(?:\s+renders?)?|trials?|experiments?)\s+" + _BY + _ADV +
                r"(?:" + _FOUND + r")\b" + _NOT_HOW),
    ("results", _THE + _QUAL + r"{1,3}?(?P<key>tests?(?:\s+renders?)?|trials?|experiments?)\s+" + _BY + _ADV +
                r"(?:" + _FINDS + r")\b" + _NOT_HOW),
    ("results", r"\b(?:a|an|the|this|that|one|their|its)\s+(?:[\w&.'’-]+\s+){0,3}?(?P<key>comparisons?|evaluations?|"
                r"audits?)\s+(?:(?:by|of|from|at|in|published\s+in|conducted\s+by|run\s+by|carried\s+out\s+by)\s+"
                r"(?:[\w&.,'’-]+\s+){1,6}?)?" + _ADV + r"(?:" + _FOUND + r"|finds|reveals|indicates|confirms|"
                r"concludes)\b(?!\s+(?:how|you|users|readers|whether|if|to|where|what|which|when)\b)"),
    # "The following evaluation pits Redshift 3.6 against OctaneRender 2024 using a standardized 8 K test scene"
    ("results", r"\b(?:evaluation|comparison|benchmark|test|analysis|review)\s+(?:pits|pitted|puts|sets|compares|"
                r"compared|contrasts|contrasted)\s+(?:[^.;!?\n]|\.\d){1,80}?\b(?:against|versus|vs\.?|with|and)\b"
                r"(?:[^.;!?\n]|\.\d){1,80}?\b(?:using|on|with|in|when\s+rendering|rendering)\s+(?:a|an|the|one|our)\s+"
                r"(?=(?:[^.;!?\n]|\.\d){0,60}?\b(?:test|benchmark|reference|standard(?:i[sz]ed)?)\b)"
                r"(?:[\w-]+\s+|\([^()]{0,30}\)\s+){0,6}?(?:scenes?|suites?|files?|images?|setups?|rigs?|projects?|"
                r"frames?)\b(?P<kw_test>)"),
    # "62% of respondents", "Respondents cited ...", "62% of artists surveyed preferred Octane", "Brand Sentiment
    # (Survey - n=1,200)": a survey's results, restated only where the step was given that survey (kw_survey)
    ("measure", r"(?<![\d.,])\d[\d.,]*\s*%\s+of\s+(?:all\s+|the\s+)?(?P<key>respondents|participants|interviewees|"
                r"those\s+(?:surveyed|polled|asked))\b(?P<kw_survey>)"),
    ("measure", r"\b(?P<key>respondents|interviewees)\s+(?:\w+ly\s+)?(?:said|reported|cited|chose|preferred|rated|"
                r"favou?red|indicated|agreed|named|picked|selected|wanted|ranked|listed|mentioned|identified|voted)\b"
                r"(?P<kw_survey>)"),
    ("measure", r"\b" + _ASKED + r"\s+(?P<key>surveyed|polled|interviewed|questioned)\b(?P<kw_survey>)(?P<hasfig>)"),
    # "In a 2024 poll of 500 artists, 62% preferred Octane" (where a result came out)
    ("results", r"\bin\s+(?:a|an|the|one|our|their|its)\s+(?:[\w-]+\s+){0,2}?(?P<key>poll|survey|study|census)\s+of\b"
                r"(?P<soft>)"),
    ("measure", r"(?:[(\[–—,-]|\b(?:survey|poll|sample))\s*(?P<kw_survey>)(?-i:n|N)\s*=\s*\d(?P<survey>)"),
    # in the past ("This figure was taken from ..."); "Data is pulled from the Sheets API" says what a program does
    ("source", r"\b" + _DATA + r"\b[^.!?;\n]{0,60}?\b(?:was|were|been)\s+(?:\w+ly\s+|all\s+)?" + _TAKEN +
               r"\s+(?:directly\s+)?from\b(?P<src>)"),
    # ... or from somewhere published: "figures taken from the official price list"
    ("source", r"\b" + _DATA + r"\b[^.!?;\n]{0,60}?\b" + _TAKEN + r"\s+(?:directly\s+)?from\s+(?P<src>)(?:the\s+|"
               r"each\s+|their\s+|its\s+|both\s+|a\s+)?(?:publicly|public|official|published|vendors?['’]?s?|"
               r"manufacturers?['’]?s?|compan(?:y|ies)['’]?s?|\d{4}|recent|latest|industry|market|independent)\b"),
    ("source", r"\bfrom\s+(?P<src>)(?:the\s+|each\s+|their\s+|its\s+|both\s+)(?:(?:company|vendor|manufacturer|"
               r"developer|maker|publisher|official|companies|vendors|manufacturers)(?:['’]s|s['’]|['’])?\s+)+"
               r"(?:official\s+)?websites?\b"),
    ("source", r"\b(?P<src>)publicly\s+(?:listed|posted|published|advertised|quoted)\s+(?:[\w-]+\s+){0,2}?" + _DATA +
               r"\b"),
    # "based on the latest vendor catalogues", "based on each vendor's 2024 price list" (not "based on demand", "based
    # on public transport")
    ("source", r"\bbased\s+on\s+(?P<src>)(?:(?:the|each|a|an|their|its|both)\s+)?(?:latest|official|published|"
               r"public|publicly|" + _VENDOR + r"|\d{4})(?![\w-])(?:\s+[\w'’-]+){0,2}?\s+" + _SOURCED + r"\b"),
    # "Per Autodesk's published pricing, ...", "..., per the vendor's website" (where it cites: not "Torque the nuts
    # per the manufacturer's specifications")
    ("source", r"\bper\s+(?P<src>)(?:(?:the|each|their)\s+)?(?:(?-i:[A-Z])[\w&.-]*|" + _VENDOR + r"|official)"
               r"(?:['’]s|s['’])?\s+(?:(?:own|official|published|public|latest|current|online)\s+)*(?:pricing|"
               r"price\s+lists?|prices|rates|websites?|site|figures|data|spec(?:ification)?s?|datasheets?|"
               r"documentation|docs)\b"),
    ("source", r"\bper\s+(?P<src>)(?:a|an|the|one)\s+(?:(?:recent|latest|\d{4})\s+)*(?:(?-i:[A-Z])[\w&.'’-]*\s+){1,3}"
               r"(?:benchmark|survey|study|report|test|analysis|poll|review)\b"),
    ("source", r"\b(?P<src>)(?:vendor|supplier|manufacturer|dealer|contractor)s?['’]?s?\s+quotes?\s+(?:put|place[sd]?|"
               r"show(?:s|ed)?|give[sn]?|gave|came\s+to|come\s+to|list(?:s|ed)?|total(?:led|s)?)\b"),
    # A vendor's site or price page that says a price: "Otoy's website lists the annual licence at $699 per seat", "The
    # official pricing page shows $699", "As listed on Otoy's website, ...", "Otoy's published pricing puts Octane at
    # $699", "Maxon's current list price for Redshift is $264"
    ("source", r"\b(?P<src>)(?:(?-i:[A-Z])[\w&.-]*(?:['’]s?)?|(?:the|its|their|each)(?:\s+(?:official|vendor['’]?s?|"
               r"company['’]?s?|manufacturer['’]?s?|maker['’]?s?|developer['’]?s?|publisher['’]?s?|own))*)\s+"
               r"(?:(?:official|online|own|current|public|published)\s+)?(?:websites?|site|pricing\s+pages?|"
               r"price\s+(?:lists?|pages?|sheets?)|store\s+pages?|product\s+pages?|online\s+store)\s+(?:currently\s+)?"
               r"(?:lists?|listed|shows?|showed|puts?|gives?|gave|quotes?|quoted|states?|stated|says|said|"
               r"advertises|advertised|prices?|priced)\b(?=[^.!?]*\d)"),
    ("source", r"\bas\s+(?:listed|shown|advertised|quoted|published|posted|stated)\s+(?:on|in|at|by)\s+(?P<src>)"
               r"(?:(?:the|each|their|its)\s+)?(?:[\w&.'’-]+\s+){0,2}?(?:websites?|site|pricing|price\s+lists?|pages?|"
               r"store|catalogu?es?|catalogs?)\b"),
    ("source", r"\b(?P<src>)(?-i:[A-Z])[\w&.-]*['’]s?\s+(?:(?:published|official|current|public|latest|list|"
               r"online)\s+)+(?:pricing|prices?|rates?|price\s+lists?)\s+(?:puts?|lists?|shows?|gives?|sets?|is|are|"
               r"starts?)\b"),
    ("source", r"\b(?P<src>)(?:(?-i:[A-Z])[\w&.-]*['’]s?\s+)?(?:current|official|published|standard|full|latest)\s+"
               r"list\s+prices?\b[^.!?]{0,40}?\b(?:is|was|are|were|of|at|stands\s+at)\s+[$€£]?\d"),
    # "Source: Maxon pricing page, 2024." and "(Otoy pricing, 2024)", also in a table's cell
    ("source", r"(?:^(?:[-*•]\s+)?|[(\[|]\s*)[*_]*(?:data\s+)?sources?[*_]*\s*:[*_]*\s*(?P<src>)[^\s.;|]"
               r"[^.;|\n]{0,38}"),
    ("source", r"\((?P<src>)\s*(?-i:[A-Z])[\w&.'’-]*(?:\s+[\w&.'’-]+){0,2}?\s+(?:pricing|prices|price\s+list|website|"
               r"site|data|figures|datasheet|survey|report|benchmark|study|tests?|analysis|review|index|poll)\s*,\s*"
               r"(?:(?-i:[A-Z])[a-z]{2,8}\.?\s+)?\d{4}\s*\)"),
    # A publisher of figures named in brackets after one ("(Grand View Research)", "(Nielsen 2023)", "(per Nielsen)",
    # "(Puget Systems, 2024)", "(Smith et al., 2021)"), or saying what it found ("Statista reports", "Grand View
    # Research estimates"), and a study's own title with its year ("Bankrate Survey 2025")
    ("source", r"\(\s*(?:per\s+|source:\s*|sources:\s*|via\s+|data:\s*)?(?P<src>)(?P<name>" + _FIRM + r")(?:,?\s*"
               r"(?:\d{4}|Q[1-4]\s+\d{4}|\d{4}\s+Q[1-4]|(?-i:[A-Z])[a-z]{2,8}\.?\s+\d{4}))?\s*\)"),
    ("source", r"\((?P<src>)(?P<name>(?-i:[A-Z])[\w&.'’-]*(?:\s+(?-i:[A-Z&])[\w&.'’-]*){0,3}),\s*\d{4}\s*\)"
               r"(?P<needfig>)"),
    ("source", r"\((?P<src>)(?P<name>(?-i:[A-Z])[\w'’-]+)\s+et\s+al\.?,?\s*\d{4}\s*\)"),
    ("source", r"\b(?P<src>)(?P<name>" + _FIRM + r")(?:['’]s?)?\s+(?:(?:\d{4}|latest|recent|new|annual|global|own)\s+)?"
               r"(?:(?:report|survey|study|data|forecast|analysis|index|benchmark)\s+)?(?:estimates?|estimated|"
               r"reports?|reported|predicts?|predicted|forecasts?|forecasted|projects?|projected|found|finds|says|said|"
               r"notes?|noted|shows?|showed|values?|valued|puts?|expects?|expected|ranks?|ranked|suggests?|suggested|"
               r"indicates?|indicated)\b"),
    ("source", r"(?P<src>)(?P<name>(?<![\w&.'’-])(?-i:[A-Z])[\w&.'’-]*(?:[\s-]+(?-i:[A-Z&])[\w&.'’-]*){0,4}[\s-]+" +
               _TITLED + r")\s*\(?\s*(?:\d{4}|Q[1-4]\s+\d{4})\b"),
    ("source", r"(?P<src>)(?P<name>(?<![\w&.'’-])(?-i:[A-Z])[\w&.'’-]*\s+\d{4}\s+(?:(?-i:[A-Z])[\w'’-]*\s+){0,3}" +
               _TITLED + r")\b"),
    # "Research from MIT shows", "Data from the Outdoor Industry Association shows"
    ("source", r"(?P<lead>^|[,;:(]\s*|\b(?:that|and|but|as|while|since|because|yet)\s+)(?:(?:recent|new|latest|"
               r"published|independent|academic|official|government)\s+)*(?:research|data|figures|statistics|stats|"
               r"evidence|numbers)\s+(?:from|by|at|published\s+by|compiled\s+by|released\s+by)\s+"
               r"(?P<src>)(?:[\w&.'’-]+\s+){1,5}?(?:" + _RESULT_VERBS + r"|puts?)\b(?!\s+(?:how|you|where|when)\b)"),
    ("source", r"\baccording\s+to\b(?P<src>)\s+(?:(?:the|a|an|their|its|his|her|recent|latest|official|published|"
               r"public|independent|industry|market|online|internal|several|many|multiple|most|current|\d{4})\s+)*"
               r"(?:[\w&.’'-]+\s+){0,3}?" + _SOURCE + r"\b"),
)] + [("source", re.compile(r"\b[Aa]ccording\s+to\s+(?P<src>)(?!(?:Step|Table|Figure|Fig|Section|Appendix|Chapter|Part|"
                            r"Phase|Plan|Schedule|Option|Rule|Article|Clause|Annex|Exhibit|Item)\b)[A-Z][\w&.-]*"))]
# What an analyst's or an expert's words must go on to say for a claim: that something is so, a figure of the market
# (a share, a price, millions), a forecast, or a trend ("Analysts report strong demand", "Analysts expect seed sales to
# double by 2030"; not "analysts estimate each ticket in story points" or "experts demonstrate how to shape a boule")
_OUTCOME = re.compile(r"^\s*(?:,\s*)?that\b|[$€£¥]\s?\d|\d[\d,.]*\s*(?:%|per\s*cent\b|percent\b|million\b|billion\b|"
                      r"bn\b|trillion\b)|\b(?:will|would|to\s+(?:reach|grow|rise|fall|double|triple|halve|hit|exceed|"
                      r"top|decline|slow|increase|decrease|drop|climb|surge|shrink|expand|overtake|outpace|outgrow|"
                      r"recover|rebound)|by\s+(?:the\s+end\s+of\s+)?(?:\d{4}|next\s+year))\b|\b(?:strong|stronger|"
                      r"strongest|growing|rising|falling|slowing|weak|weaker|record|surging|soaring|declining|"
                      r"shrinking|booming|steady|more|most|fewer|less|least|higher|highest|lower|lowest|increasing|"
                      r"decreasing|growth|decline|shift|trend|boom|slump|recovery|downturn|rebound|surge|majority|"
                      r"standard|best|worst|better|worse|likely|unlikely|faster|slower|cheaper|safer)\b", re.I)
_SURVEYISH = re.compile(r"\b(?:surve\w*|polls?|polled|respondents?|samples?|participants?|replies|responses|"
                        r"interview\w*|questionnaires?)\b", re.I)
# "It's no secret that ...", "Not surprisingly, ...": no denial of what follows
_NOT_A_DENIAL = re.compile(r"\b(?:it['’]s\s+|it\s+is\s+|there\s+is\s+|there['’]s\s+)?no\s+(?:secret|surprise|wonder|"
                           r"doubt|question|coincidence|exaggeration)\b|\bnot\s+surprisingly\b", re.I)
# ... unless what it cites (after the pattern's src group) is the request's own ("taken from the provided CSV",
# "according to the brief", "from s1") or what a program reads: inline code (blanked, so nothing or punctuation
# follows), a file name, a config, an API
_OWN_SOURCE = re.compile(r"^\s*(?:$|[.,;:)]|\S+\.[A-Za-z][A-Za-z0-9]{0,4}\b|(?:the\s+|your\s+|this\s+|that\s+|our\s+)?"
                         r"(?:provided|given|supplied|attached|above|below|earlier|previous|preceding|following|input|"
                         r"inputs|brief|instructions?|plan|outline|steps?\b|s\d+\b|sections?|table|list|csv|"
                         r"spreadsheet|sheet|file|log|dataset|schedule|api|apis|endpoint|database|config(?:uration)?|"
                         r"environment|env|settings|command\s+line|arguments?|cache|server|repo(?:sitory)?|script|"
                         r"template|form|request|response)\b|"
                         r"(?:the\s+|this\s+)?(?:[\w-]+\s+){0,3}(?:above|below|here)\b|"
                         r"this\s+(?:[\w-]+\s+){0,2}(?:comparison|evaluation|analysis|breakdown|overview|review)\b)",
                         re.I)
# "According to X, ..." or "..., according to X" cites X; "Use it according to manufacturer instructions" doesn't
_CITES_AT = re.compile(r"(?:^|[,(:;–—-])[\s*_\"“]*$")
# "Download it from the official website" sends the reader there; it claims nothing
_SENDS = re.compile(r"\b(?:download|install|get|grab|buy|purchase|order|visit|check|see|available|find|request|book|"
                    r"register|sign\s+up|subscribe|contact|read|learn|consult|refer)\b[^.!?;\n]{0,50}$", re.I)
# "Update the prices based on the latest vendor list" is advice, not a claim, and "Torque the wheel nuts per the
# manufacturer's specifications" or "Per the manual, set the pressure ..." a how-to's step: a sentence (or what follows
# the cited name) that starts with one of these verbs (not those that start a noun phrase as often: test, record,
# report, log, service)
_IMPERATIVE = re.compile(r"^[\W_]*(?:update|adjust|revise|recalculate|refresh|review|re-?check|check|confirm|verify|"
                         r"set|choose|pick|compare|budget|plan|price|quote|torque|tighten|loosen|install|configure|"
                         r"follow|apply|use|fit|mount|connect|attach|fill|inflate|replace|clean|mix|cut|store|dispose|"
                         r"handle|operate|maintain|inspect|calibrate|wear|keep|water|feed|prune|plant|sow|cook|bake|"
                         r"heat|cool|add|remove|open|close|turn|press|hold|place|put|insert|select|enable|disable|"
                         r"run|measure|wash|dry|label|seal|lubricate|grease|align|paint|sand|drill|screw|bolt|pack|"
                         r"wrap|serve|season|stir|boil|fry|roast|grill|chill|freeze|thaw|dilute|spray|download|get|"
                         r"buy|order|visit|see|find|book|register|contact|read|consult|refer|ask|make|give|bring|"
                         r"take|leave|allow|avoid|ensure|start|stop|begin|finish|let|try)\b", re.I)
# A soft shape (a panel of judges, a blind test, "experts suggest") claims a result only where the sentence says one
# came out: a verb in the past, or a score or a comparison with nothing in the sentence still to come (_done)
_MODAL = re.compile(r"\b(?:will|would|should|can|could|may|might|must|shall)\b|['’]ll\b", re.I)
_SCORE = re.compile(r"\d(?:[\d.]*\d)?\s*(?:/|out\s+of)\s*\d|\d\s*%|\b\d+(?:\.\d+)?\s*(?:points?|stars?)\b", re.I)
_PAST = re.compile(r"\b(?:was|were|had|did|showed|shown|found|gave|beat|won|lost|took|ran|came|chose|picked|felt|"
                   r"saw|got|fell|rose|drew)\b", re.I)  # not "made up of", "held in the hall"
_ED = re.compile(r"(?<![\w'’-])([^\W\d_]{2,}ed)(?![\w'’-])", re.I)
# -ed words that describe rather than report: "the panel is based at", "a panel of experienced bakers"
_NOT_PAST = {"based", "located", "called", "named", "scheduled", "planned", "expected", "invited", "designed",
             "intended", "required", "needed", "allowed", "supposed", "advised", "recommended", "aimed", "seated",
             "dedicated", "detailed", "advanced", "experienced", "skilled", "qualified", "trained", "certified",
             "renowned", "respected", "selected", "assigned", "appointed", "hundred", "sacred", "beloved", "learned",
             "aged", "talented", "interested", "limited", "mixed", "varied", "related", "united", "added", "focused",
             "geared", "centred", "centered", "devoted", "themed", "tailored", "packed", "filled", "priced"}
# ... nor one after these: "a brushed aluminium case", "is judged by", "to be scored"
_NOT_BEFORE_PAST = {"a", "an", "the", "its", "their", "our", "this", "these", "those", "each", "every", "well",
                    "more", "most", "less", "least", "fully", "highly", "his", "her", "my", "your", "is", "are", "be",
                    "being", "to", "get", "gets", "am"}
# ... nor one after a preposition, "and", "or" or a wh-word, where an -ed word is the adjective of what follows: "with
# yeasted bread", "a panel of chefs on fermented foods", "of smoked and unsmoked cheese", "how cured meats are made"
_BEFORE_ADJ = {"with", "on", "about", "of", "for", "in", "at", "from", "into", "onto", "over", "under", "between",
               "among", "without", "like", "unlike", "via", "through", "across", "around", "toward", "towards",
               "against", "during", "after", "before", "near", "including", "plus", "per", "than", "versus", "vs", "as",
               "and", "or", "nor", "how", "what", "why", "whether"}
# A past verb's subject right before it: a pronoun ("it reproduced") or a name ("Octane produced"); after another word
# ("discusses recycled packaging", "using labelled diagrams", "visitors preferred the sourdough") the next word says
# which: a plain word after it is the noun an adjective describes
_NOT_BEFORE_ED = _NOT_BEFORE_PAST | _BEFORE_ADJ
_PRONOUNS = {"it", "they", "we", "i", "he", "she", "you", "who", "which", "that", "everyone", "everybody", "nobody",
             "everything", "nothing", "someone", "something", "one"}
_COMPARATIVE = (r"better|worse|higher|lower|faster|slower|quicker|sooner|cleaner|sharper|finer|clearer|crisper|"
                r"smoother|richer|truer|noisier|grainier|brighter|darker|cheaper")
_AFTER_PAST = {"the", "a", "an", "its", "their", "his", "her", "our", "my", "your", "this", "that", "these", "those",
               "each", "every", "both", "all", "some", "no", "any", "it", "them", "him", "us", "me", "one", "to", "in",
               "on", "at", "by", "with", "from", "for", "over", "than", "against", "across", "into", "about", "as",
               "after", "before", "during", "through", "up", "down", "out", "off", "well", "first", "last", "and", "or",
               "but", "most", "more", "less", "fewer", "much", "far", "only", "just", "even", "again", "ahead",
               "behind", "best", "worst", "top", "highest", "lowest"} | set(_COMPARATIVE.split("|"))
# A comparison says a result came out as a score does ("In the 8K test, Octane resolves finer detail than Redshift",
# "most artists prefer Octane's glass", "A panel of senior artists rates Octane's materials higher"): "than" (not
# "rather than", "more than 20 chefs", "lighter than 400 g"), ahead or behind after a verb, "ahead of" a name (not
# "the marquee behind Ludlow Castle"), outperforms, a majority that prefers, and a quality's comparative (not "for
# better results", "the better loaf", "to get higher yields")
_COMPARES = re.compile(
    r"(?<!\brather )(?<!\bother )(?<!\bno later )(?<!\bno more )(?<!\bno less )\bthan\b"
    r"(?!\s+(?:[$€£¥]?\d|(?:ever|usual)\b))|"
    r"\b(?:well|far|clearly|slightly|comfortably|narrowly|comes?|finish(?:es)?|ranks?|stays?|pulls?|edges?)\s+"
    r"(?:ahead|behind)\b|\b(?:falls?|lags?|trails?)\s+(?:well\s+|far\s+)?behind\b|"
    r"\b(?:puts?|ranks?|rates?|places?)\s+[\w'’]+(?:\s+[\w'’]+)?\s+(?:ahead|behind)\b|"
    r"\bahead\s+of\s+(?-i:[A-Z])|"
    r"\bout(?:perform|pace|score|shine|class|run|render)(?:s|ed)?\b|\bedges?\s+out\b|\bbeats\b|"
    r"(?P<most>\b(?:most|many|nearly\s+all|almost\s+all|the\s+majority\s+of|a\s+majority\s+of|\d+\s*%\s+of|"
    r"\d+\s+(?:of|in|out\s+of)\s+(?:the\s+)?\d+)\s+"
    r"(?:[\w'’-]+\s+){0,3}?(?:prefer(?:s|red)?|favou?r(?:s|ed)?)\b)|\bprefers?\s+(?:[\w'’-]+\s+){1,4}?over\b|"
    r"(?<!\bfor )(?<!\bto )(?<!\ba )(?<!\ban )(?<!\bthe )(?<!\bon )(?<!\bof )(?<!\bget )(?<!\bgets )"
    r"(?<!\bmake )(?<!\bmakes )(?<!\bmaking )(?<!\bgetting )(?<!\bachieve )(?<!\bensure )(?<!, )(?<!\band )(?<!\bor )"
    r"\b(?:" + _COMPARATIVE +
    r"|(?:more|less)\s+(?:accurate(?:ly)?|realistic(?:ally)?|natural(?:ly)?|faithful(?:ly)?|consistent(?:ly)?|"
    r"stable|reliabl[ey]|detailed|noise|detail|grain|artefacts?|artifacts?|vram|memory|convincing(?:ly)?|"
    r"believabl[ey]|lifelike|polished|refined|appealing|pleasing|accurate))\b", re.I)
# ... unless the comparison is part of what something is called rather than a result: "the one they like better",
# "whichever entry scores higher", "the loaf most visitors prefer wins the ribbon", "the cheese they rate better"
_RELATIVE = re.compile(r"\bthe\s+ones?\b|\bwhichever\b|\bwhoever\b|\b(?:they|you|we|people|visitors|guests|judges|"
                       r"pupils|children|students|customers|diners|tasters|members)\s+(?:\w+\s+)?(?:like[sd]?|"
                       r"prefer(?:s|red)?|enjoy(?:s|ed)?|rate[sd]?|find|found)\s+(?:\w+\s+)?$", re.I)
_THE_NOUN = re.compile(r"\b(?:the|a|an|each|every|any|this|that)\s+(?:[a-z][\w'’-]*\s+){1,2}$")
_ASKS = re.compile(r"\b(?:which|whether|how|what|if)\b", re.I)  # "pupils see which plant grows taller than the other"
_OPEN = re.compile(r"\b(?:whether|how|what|if)\b")  # ... and in the own words ("Find out what the survey found")
# A name, a word with a capital that doesn't start the sentence: what a comparison of results compares ("Octane",
# "Redshift's", "VRAM"), where an event's "visitors pick the loaf they like better" names nothing
_NAMED = re.compile(r"(?<=\s)(?!I\b)(?-i:[A-Z])[\w'’-]*")
# A result told in the present tense: a name that wins, leads, handles or struggles ("In the 8K test, Octane clearly
# wins on glass", "Redshift struggles with caustics"), a panel or a test that picks or favours a name ("picks Octane
# every time"), and "is the clear favourite"; not "A panel of three judges picks the Best in Show at 4 pm"
_NOW_RESULT = re.compile(
    r"(?-i:[A-Z])[\w'’-]*(?:['’]s\s+[a-z][\w-]*)?\s+(?:\w+ly\s+)?(?:wins|leads|handles|struggles|excels|shines|"
    r"dominates|prevails|copes|falters|stumbles|suffers|impresses|holds\s+up)\b|"
    r"\b(?:picks|chooses|favou?rs|prefers|backs)\s+(?-i:[A-Z])|"
    r"\b(?:is|are)\s+(?:the\s+|a\s+)?(?:clear|obvious|unanimous|overall|consistent|runaway|outright)\s+(?:favou?rite|"
    r"winner|leader|choice|pick|preference)\b", re.I)
# Plural nouns for people: an -ed word right after one is their verb ("artists preferred renders from Octane",
# "reviewers flagged banding"), where after another word it may describe what follows ("discusses recycled packaging")
_PEOPLE = {"artists", "experts", "judges", "reviewers", "users", "testers", "engineers", "designers", "specialists",
           "professionals", "evaluators", "raters", "participants", "customers", "viewers", "critics", "people",
           "members", "developers", "students", "chefs", "tasters", "colleagues", "staff", "growers", "gardeners",
           "farmers", "buyers", "readers", "listeners", "players", "volunteers", "visitors", "respondents", "pupils",
           "attendees", "guests", "panellists", "panelists", "jurors", "diners", "shoppers", "editors", "photographers",
           "animators", "teams"}


def _past_ed(s, m) -> bool:
    """Is the -ed word m (an _ED match in sentence s) a verb in the past? Not one of _NOT_PAST, nor after an article,
    "is" or the like, a preposition, "and" or a wh-word, nor before "by"; after a pronoun, a name or a plural noun for
    people (_PEOPLE: "artists preferred renders") it is; after any other word, unless a plain word follows it (the noun
    it describes: "discusses recycled packaging")."""
    w = m.group(1).lower()
    before = list(re.finditer(r"[\w'’-]+", s[:m.start()]))
    words = re.findall(r"[\w'’-]+", re.split(r"[,;:()]", s[:m.start()])[-1].lower())  # of its clause
    prev = before[-1].group(0) if before else ""
    if w in _NOT_PAST or w.endswith("eed") or prev.lower() in _NOT_BEFORE_ED or \
            re.match(r"\s+by\b", s[m.end():], re.I) or _ASKS.search(s[:m.start()]) or _named_part(s, m.start()):
        return False
    # before a preposition, the object of a preposition is no subject ("than the maximum printed on the sidewall"), nor
    # is a noun right after another's ("the distance the car travelled on each surface": what it travelled is the
    # distance); "the judges of the show preferred Suttons" still says a result
    nxt = re.match(r"\s*([\w'’-]+|[,;:.!?)]|$)", s[m.end():])
    if len(words) >= 3 and words[-2] in _ARTICLES | {"its", "their", "each", "every"} and \
            (words[-3] in _BEFORE_ADJ or (len(words) >= 4 and words[-4] in _ARTICLES)) and \
            (not nxt.group(1) or nxt.group(1).lower() in _BEFORE_ADJ | {"by", ",", ";", ":", ".", "!", "?", ")"}):
        return False
    if prev.lower() in _PRONOUNS or prev.lower() in _PEOPLE or (prev[:1].isupper() and len(before) > 1):
        return True
    return not _describes(s[m.end():])


def _describes(rest) -> bool:
    """Does a plain word (the noun an adjective describes) start rest, what follows an -ed word? Across "and" or "or"
    to the next -ed word's ("recycled and upcycled furniture", not "tasted and rated each loaf")."""
    after = re.match(r"\s+([^\W\d_][\w'’-]*)", rest)
    nxt = (after.group(1) if after else "").lower()
    if nxt in ("and", "or"):
        more = re.match(r"\s+([^\W\d_][\w'’-]*ed)\b", rest[after.end():], re.I)
        return _describes(rest[after.end() + more.end():]) if more else True
    return nxt[:1].isalpha() and after.group(1)[:1].islower() and nxt not in _AFTER_PAST and not nxt.endswith("ly")


# Verbs a "that" after which starts what was said, not a relative clause ("found that Octane is cleaner")
_SAY_VERBS = {"found", "finds", "find", "says", "said", "say", "shows", "showed", "show", "agree", "agrees", "agreed",
              "notes", "noted", "thinks", "think", "thought", "believe", "believes", "believed", "reports", "reported",
              "suggests", "suggested", "indicates", "indicated", "confirms", "confirmed", "concluded", "concludes",
              "feel", "feels", "felt", "know", "knew", "argue", "argued", "claims", "claimed", "so", "such", "now"}
_REL_AFTER = re.compile(r"(?:^|\b)([\w'’-]+)\s+(?:that|which|who|whom|whose)\s+(?:[\w'’-]+\s+){0,3}$", re.I)
_REL_ANY = re.compile(r"\b(?:who|whom|whose|all\s+of\s+whom|including)\b", re.I)


def _named_part(s, start) -> bool:
    """Is the comparison, the verb or the result at s[start:] part of what something is called or a clause about
    someone, not a result: _RELATIVE ("the one they like better"), a relative clause after a noun ("entries that score
    higher", "judges, who between them founded ..."), or a majority that prefers right after "the <noun>" ("the loaf
    most visitors prefer")? Only its clause counts."""
    clause = re.split(r"[,;:()]", s[:start])[-1]
    rel = _REL_AFTER.search(clause)
    return bool(_RELATIVE.search(clause)) or bool(_REL_ANY.search(clause)) or bool(
        rel and rel.group(1).lower() not in _SAY_VERBS) or bool(
        _THE_NOUN.search(clause) and _COMPARES.match(s, start) and _COMPARES.match(s, start).group("most"))


def _compares(s) -> bool:
    """Does sentence s compare (_COMPARES) what it names (_NAMED), not inside a question it leaves open ("see which
    ... grows taller") and not as part of what something is called (_named_part)?"""
    return bool(_NAMED.search(s)) and any(not _ASKS.search(s[:m.start()]) and not _named_part(s, m.start())
                                          for m in _COMPARES.finditer(s))


def _now_result(s) -> bool:
    """Does sentence s tell a result in the present tense (_NOW_RESULT), not inside a question it leaves open, not as
    part of what something is called and not what each one does ("each visitor picks Hobbs House or Gail's")?"""
    return any(not _ASKS.search(s[:m.start()]) and not _named_part(s, m.start()) and
               not re.search(r"\b(?:each|every|any)\s+[\w'’-]+\s+$", s[:m.start()], re.I)
               for m in _NOW_RESULT.finditer(s))


def _done(s, advice=False, skip=(0, 0)) -> bool:
    """True when sentence s says a result came out: a verb in the past ("Octane reproduced", "visitors preferred", "was
    the favourite"; not an -ed word that describes: _past_ed), or, where nothing is still to come (will, should, can,
    ...), a score ("8.3/10", "7 out of 10", "40 %", "9 points"), a comparison ("finer detail than Redshift", "rates
    Octane's materials higher": _compares) or a result in the present tense ("Octane clearly wins on glass",
    _now_result); a verb in a clause about someone (_named_part: "judges, who between them founded Ludlow's first
    bakery, score ...") says nothing came out. For experts' advice (advice) only a verb in the past or a rating:
    "Experts suggest visiting the Louvre on a Wednesday, when it is quieter than at weekends" compares, and "Experts
    recommend replacing a chain at 0.5% wear" gives a threshold, and both are still advice. An -ed word in skip (the
    claim's own span: "When tested with a meter") is none of the sentence's verbs."""
    if any(not _named_part(s, m.start()) for m in _PAST.finditer(s)) or \
            any(_past_ed(s, m) for m in _ED.finditer(s) if not skip[0] <= m.start() < skip[1]):
        return True
    if _MODAL.search(s):
        return False
    if advice:  # a rating, not a threshold: "Experts recommend replacing a chain at 0.5% wear" is still advice
        return any(not re.search(r"%", m.group(0)) for m in _SCORE.finditer(s))
    return bool(_SCORE.search(s)) or _compares(s) or _now_result(s)


def _after_comma(s, end) -> str:
    """What follows the first comma at or after end in s ("Per the manual, set ..." gives "set ..."), else ""."""
    k = s.find(",", end)
    return s[k + 1:] if k >= 0 else ""


def _units(section):
    """The section's text outside code as units a claim can't run past: each paragraph (its lines joined), list item
    (with the lines that carry it on), table row and sub-heading, inline code blanked out, zero-width characters
    made spaces."""
    units, cur = [], []
    for l in prose_lines(section) + [""]:
        s = _INLINE_CODE.sub(" ", _HIDDEN.sub(" ", l)).strip()
        if not s or s.startswith(("|", "#")) or _LIST_ITEM.match(l):
            if cur:
                units.append(" ".join(cur))
            cur = [s] if s and _LIST_ITEM.match(l) else []
            if s and not cur:
                units.append(s)
            continue
        cur.append(s)
    return units


def sentences(section):
    """The section's sentences outside code: _units split after ., ! or ? and a space (so not 0.0018 or 1.5k)."""
    return [x for u in _units(section) for x in _SENTENCE_END.split(u) if x.strip()]


# ---- the step's given data
#
# A measurement, result or source claim may restate the step's own data: in the smoke's plans pasted readings ride in
# a step's instructions ("taken every 15 minutes on 3 June: 09:00 41.2 C ..."), a section built on a research step
# that worked writes "According to the analysis, sales rose 12%", and a round-2 section restates the previous result.
# _restates takes it as such when the material the step was given (given_material) holds both its figures and its
# words, read so (_material):
# - Label numbers are no data, in the sentence or the material (_figs): list numbering, "week 1" or "step 3", a
#   version after a name ("Redshift 3.6"), a resolution ("8K", "1080p"), "3D", a model number ("RTX 4090"), a word
#   count ("≈600 words"), and what the plan's and its steps' titles and the step's word target say (_labels). In the
#   smoke's stored plans 9 of 13 section steps with dependencies reached four figures in their own words that way,
#   so a count of figures can't tell data from labels.
# - A clause of the material that denies the data ("No benchmark results were available", "I couldn't find a
#   survey", "Nothing was measured") gives none of it, and a word after a "no" or a "not" in its clause isn't held:
#   an honest research step's piece says what it lacked, and read whole that made invented claims look given.
# - A sentence with a mark ("(unverified)", "Assumed: ...") gives no figures, and no words to a result or a
#   measurement: a dependency's marked guess, or the previous round's, restated without its mark is the smoke's
#   invented benchmark laundered through s1 (its tell asks to keep the mark: CLAIMS_TELL_MARK).
# - Its figures: at least half of the sentence's numbers that aren't years, each held by a dependency's piece or the
#   previous result, or by the step's own words with the same unit or sign ("62%", "47.5 C", "$699", "24 mm/s", "3
#   June", "12 May"; a bare number there only where it can't be a count, a decimal or three digits or more: "a team of
#   5" gives no 5); two units that differ never match ("12 s" isn't "12%"); and every year when it has no others
#   ("According to a 2023 study": a year nothing gave). A bare count the own words give with the word it counts ("We
#   surveyed 40 plot holders", "4 of the 9 laptops") is theirs, as a label is, and leaves the claim to its words.
# - Its words: what the claim is about (the benchmark, the survey, the measuring) or, for a source, every word of the
#   name it cites ("the county survey" isn't "the soil survey"), held by the blocks that give at least half of its
#   figures between them (_tied: an honest s1's "8 GB of VRAM" doesn't make "Benchmarks show Octane needs 8 GB and
#   renders 40% faster" a benchmark's), and not in the own words' clause that points at another step, unless the
#   pieces give every figure (_pointed); a name outside the request (a website, an official or published list, a
#   vendor) needs a given figure too. "According to the data" cites the given data itself (_bare_data).
# - A sentence with no figure of its own is the step's data by a piece that gives its word (_piece_gives): a clause
#   that holds it, doesn't deny it or ask for it (a modal, "recommended", "next step", "would be needed", "planned";
#   "Benchmarks: none found", "Missing data: ..."; a modal beside a result verb and a figure still gives: "64% ...
#   said they would prefer"), and says the data where the word is data (a figure, a result verb, a comparison, "the
#   benchmark covered ...") in a sentence that, with the one after it on its line, holds half of what the claim says
#   (_content, _window); or a label of the piece's body over rows with figures ("Survey results:" over "- Tuesday
#   evening: 64%"); else only where the piece holds all of what the sentence says. An honest research step that found
#   nothing still names the benchmark ("should run its own benchmark", "OctaneBench is Otoy's own benchmark tool",
#   "Running a benchmark takes about 2 days"), and its heading is its step's title, which names the data asked for:
#   a heading over a piece's rows gives no claim with no figure, and the claim's tell asks for the figure instead
#   (CLAIMS_TELL_CITE). By the step's own words only where a clause holds the word with a figure of data after a
#   colon, in rows under a results label or after the word in its clause ("Waste weighed at closing: week 1 12 kg,
#   ...", "Survey results:" over "- Hybrid: 62%", "In the survey, 62% want hybrid working", "the survey, which found
#   62% ..."; not "the survey of 120 members", "a $5,000 budget", "(n = 340)", "Survey details:" over "- Sent to: 340
#   members", "The target benchmark time is 4 minutes", "Check whether the benchmark is under 5 minutes"), or they make
#   the same claim ("Explain that research shows short breaks help"), since instructions that ask for a benchmark
#   ("Compare render quality at 8K using benchmarks") don't give one; a source's name the step's own words give is
#   enough ("According to Dan, the head baker"), a name that is data, or one they give only as a place to get data
#   ("using data from Statista and CNET"), only where they say what it found, and one given only as someone to act
#   ("Ask Dan to sign it") not at all. A title names a topic, not data, and a clause that points at another step
#   ("Based on the benchmark data from s1", "s1's survey", "from the previous step") names data that step's piece has
#   to give: about half of the smoke's dependent sections name their dependency's data so.
# When a dependency is missing only the pieces that are there and the previous result count: the missing step was
# what would have given the data, and the step's instructions still name it ("Based on the benchmark data from s1,
# ... (resolution 8K)"), so every one of the smoke's 9 firings, all written with s1 failed, used the plan's own words
# and figures.
_FIG = re.compile(r"(?<![^\W\d_])(?<![\d.,])(\d{1,3}(?:,\d{3})+(?!\d)|\d+(?:\.\d+)?)")
_CLOCK = re.compile(r"(?<![\d:.])(\d{1,2}):(\d{2})(?![\d:])")  # 09:15, one figure
_DATE = re.compile(r"(?<![\d-])\d{4}-\d{2}-\d{2}(?![\d-])")  # 2023-08-05, one figure
_STOP = {"the", "a", "an", "each", "every", "their", "its", "his", "her", "our", "your", "my", "this", "that", "these",
         "those", "both", "all", "some", "any", "own", "latest", "recent", "current", "above", "below", "previous",
         "earlier", "following", "preceding", "result", "results", "data", "figure", "figures", "number", "numbers",
         "information", "info", "details", "values", "findings"}
_CUT = {"on", "in", "for", "at", "by", "with", "between", "during", "from", "to", "that", "which", "who", "and", "or",
        "but", "as", "when", "where", "while", "so", "because", "since", "than", "after", "before", "over", "under",
        "per", "via", "put", "puts", "show", "shows", "showed", "came", "come", "gave", "give", "gives", "list",
        "lists", "total", "totals", "is", "are", "was", "were"}
# A name outside the request: words that put a source on the web or in print, or with a vendor
_OUTSIDE = re.compile(r"(?:web|websites?|sites?|online|official|published|public|publicly|vendors?|manufacturers?|"
                      r"suppliers?|catalogu?es?|catalogs?|datasheets?|press|listed|advertised|pages?|internet)")
# What a measurement may be called in the material ("readings, taken every 15 minutes")
_MEASURING = ("measur", "readi", "recor", "logge", "sampl", "taken", "track", "monit", "weigh", "meter")

# A figure's unit, each written one way: its currency sign (or code) before it, else the unit right after it. A
# count's noun ("5 seats") is no unit; "word" marks a word count, a label. The month of a date is its unit ("3 June").
_SIGNS = {"$": "$", "€": "€", "£": "£", "¥": "¥", "₹": "₹"}
_CODES = {"usd": "$", "eur": "€", "gbp": "£", "jpy": "¥", "inr": "₹", "cad": "cad", "aud": "aud", "nzd": "nzd",
          "chf": "chf", "sek": "sek", "nok": "nok", "dkk": "dkk", "cny": "cny"}
_UNITS = {alias: unit for unit, aliases in {
    "%": "% percent pct", "‰": "‰", "x": "x × times fold", "°": "° degree degrees", "c": "c °c celsius",
    "f": "f °f fahrenheit", "kg": "kg kgs kilo kilos kilogram kilograms", "g": "g gram grams", "mg": "mg",
    "lb": "lb lbs pound pounds", "oz": "oz ounce ounces", "t": "t tonne tonnes ton tons", "mm": "mm", "cm": "cm",
    "m": "m metre metres meter meters", "km": "km", "mi": "mi mile miles", "ft": "ft foot feet",
    "inch": "inch inches", "m2": "m2 m² sqm", "ml": "ml", "l": "l litre litres liter liters",
    "gal": "gal gallon gallons", "ms": "ms millisecond milliseconds", "s": "s sec secs second seconds",
    "min": "min mins minute minutes", "h": "h hr hrs hour hours", "day": "day days", "week": "week weeks wk wks",
    "month": "month months", "year": "year years yr yrs", "hz": "hz", "khz": "khz", "mhz": "mhz", "ghz": "ghz",
    "kb": "kb", "mb": "mb", "gb": "gb", "tb": "tb", "mbps": "mbps", "gbps": "gbps", "w": "w watt watts", "kw": "kw",
    "kwh": "kwh", "v": "v volt volts", "ma": "ma", "mah": "mah", "db": "db", "fps": "fps", "px": "px pixel pixels",
    "mp": "mp", "rpm": "rpm", "psi": "psi", "bar": "bar", "kpa": "kpa", "nm": "nm", "mm/s": "mm/s", "m/s": "m/s",
    "km/h": "km/h kmh kph", "mph": "mph", "kcal": "kcal", "cal": "cal calorie calories", "k": "k",
    "sample": "sample samples spp", "point": "point points pt pts", "star": "star stars", "word": "word words",
    "clock": "am pm", "january": "jan january", "february": "feb february", "march": "march",
    "april": "apr april", "june": "jun june", "july": "jul july", "august": "aug august",
    "september": "sep sept september", "october": "oct october", "november": "nov november",
    "december": "dec december"}.items() for alias in aliases.split()}
_UNIT_AFTER = re.compile(r"[ \u00a0\u202f]?(?:-[ ]?)?(°\s?[CcFf](?![^\W\d_])|°|%|‰|×|m²|[^\W\d_]+(?:/[^\W\d_]+)?)"
                         r"(?!\w)")  # a whole word: not the "MP" of "1080 MP4"
# Label numbers, the number in a group: list numbering ("1. ", "(2) ", "- 3) "), a numbered part ("week 1", "Step 3",
# "Year 5"), a version so called ("version (3.6)"), digits in a file's name ("g45_vibration_202311.csv"), a
# resolution ("8K", "1080p"), "3D"; and, when no unit follows, a version after a name ("Redshift 3.6", "LuaExcel
# (1.2)") and a model number ("RTX 4090")
_LABELS = (re.compile(r"^[ \t]*(?:[-*•][ \t]+)?\(?(\d{1,2})[.)](?=\s)", re.M),
           re.compile(r"\b(?:versions?|ver\.|release)\s*[(#]?\s*(\d+(?:\.\d+)*)", re.I),
           re.compile(r"(?<=_)(\d+)|(?<![\d.,])(\d+)(?=_|\.[A-Za-z]{2,5}\b)|(?<=[A-Za-z]/)(\d+)"),
           re.compile(r"\b(?:steps?|weeks?|days?|phases?|sections?|parts?|options?|tables?|figs?\.?|chapters?|items?|"
                      r"stages?|rounds?|tiers?|levels?|scenarios?|appendix|slides?|pages?|questions?|lessons?|year|"
                      r"grade|session|module|episode|season)\s*#?(\d{1,3})(?![\d.,])", re.I),
           re.compile(r"(?<![$€£¥₹\w.,])(\d{1,2})[ ]?K\b"),
           re.compile(r"(?<![\w.,])(\d{3,4})p\b"),
           re.compile(r"(?<![\w.,])(\d)[Dd]\b"))
_VERSION = re.compile(r"(?<![\w.])(?P<name>[A-Z][\w+-]*)[ \u00a0]\(?(\d+\.\d+(?:\.\d+)*)(?![\d.])")
_MODEL = re.compile(r"(?<![\w.])(?P<name>(?!(?:MSRP|RRP|VAT|TCO|ROI|KPI|AVG|MAX|MIN|USD|EUR|GBP|JPY|INR|CAD|AUD|"
                    r"NZD|CHF|SEK|NOK|DKK|CNY)\b)[A-Z]{2,})[- ]?(\d{3,5})(?![\d.,])")
# Words a figure follows that aren't a product's name ("Average 24.5", "Score 8.3 for Octane", "In 2.5 seconds")
_NOT_A_PRODUCT = {"in", "at", "about", "around", "roughly", "approximately", "approx", "nearly", "almost", "over",
                  "under", "only", "just", "average", "averaging", "total", "score", "scores", "scored", "peak",
                  "mean", "median", "max", "min", "maximum", "minimum", "up", "down", "from", "to", "by", "with", "for",
                  "and", "or", "but", "the", "a", "an", "of", "on", "after", "before", "between", "below", "above",
                  "overall", "rating", "rated", "ratio", "ior", "index", "value", "level", "grade", "weight", "height",
                  "length", "width", "depth", "size", "price", "cost", "costs", "speed", "time", "temperature", "temp",
                  "est", "circa", "ca", "each", "every", "all", "both", "it", "its", "this", "that", "these", "those",
                  "we", "they", "was", "were", "is", "are", "be", "per", "vs", "versus", "than", "then", "now", "also",
                  "fell", "rose", "dropped", "reached", "hit", "yes", "no", "note"}


def _digits(s):
    """A figure's digits written one way: no thousands commas, no leading zeros, no trailing decimal zeros."""
    s = s.replace(",", "")
    a, _, b = s.partition(".")
    b = b.rstrip("0")
    return (a.lstrip("0") or "0") + ("." + b if b else "")


def figures(text):
    """The numbers in text (not those glued to a letter, like s1 or x264), each as _digits writes it."""
    return [_digits(m.group(1)) for m in _FIG.finditer(text or "")]


def _year(n):
    return len(n) == 4 and n.isdigit() and 1900 <= int(n) <= 2099


def _unit(text, start, end) -> str:
    """The unit of the figure at text[start:end]: its sign or currency code before it, else the unit right after it
    (_UNITS), else ""."""
    before = text[max(0, start - 5):start].rstrip(" \u00a0\u202f")
    if before[-1:] in _SIGNS:
        return _SIGNS[before[-1]]
    code = re.search(r"(?<![^\W\d_])([A-Za-z]{3})$", before)
    if code and code.group(1).lower() in _CODES:
        return _CODES[code.group(1).lower()]
    m = _UNIT_AFTER.match(text, end)
    if m and m.group(1) == "May":  # the month ("12 May"), not the modal
        return "may"
    return _UNITS.get(re.sub(r"\s", "", m.group(1).lower()), "") if m else ""


def _figs(text, labels=frozenset()):
    """The figures of text that may be data, in order, each as (digits, unit): a clock time ("9:15", "clock") and a
    date ("2023-08-05", "date") are one figure each; label numbers (_LABELS, a version or a model number with no unit
    after it, a word count) and the plan's labels ((digits, unit) pairs: _labels) are left out."""
    return [f for _, f in _figs_at(text, labels)]


def _figs_at(text, labels=frozenset()):
    """_figs' figures, each as (where it starts in text, figure)."""
    text = text or ""
    found, skip = [], []
    for m in _CLOCK.finditer(text):
        skip.append(m.span())
        found.append((m.start(), (f"{int(m.group(1))}:{m.group(2)}", "clock")))
    for m in _DATE.finditer(text):
        skip.append(m.span())
        found.append((m.start(), (m.group(0), "date")))
    for rx in _LABELS:
        skip += [m.span(g) for m in rx.finditer(text) for g in range(1, rx.groups + 1) if m.group(g)]
    for rx in (_VERSION, _MODEL):
        skip += [m.span(2) for m in rx.finditer(text)
                 if m.group("name").lower() not in _NOT_A_PRODUCT and not _unit(text, *m.span(2))]
    for m in _FIG.finditer(text):
        if any(a <= m.start(1) < b for a, b in skip):
            continue
        f = (_digits(m.group(1)), _unit(text, *m.span(1)))
        if f[1] != "word" and f not in labels:
            found.append((m.start(), f))
    return sorted(found)


def _labels(plan, i):
    """The plan's labels as _figs reads figures: those of its title and its steps' titles but years ("Write License
    cost breakdown for team of 5" gives ("5", "")), and step i's word target's numbers, bare."""
    steps = plan.get("steps") or []
    out = set()
    for t in [plan.get("title")] + [st.get("title") for st in steps]:
        out.update(f for f in _figs((t or "").translate(_DASHES)) if not _year(f[0]))
    target = step_target(steps[i]) if 0 <= i < len(steps) else None
    out.update((_digits(str(n)), "") for n in (target or {}).get("n") or ())
    return frozenset(out)


def _data_fig(f) -> bool:
    """A figure of the step's own words that can be data: not a year, and with a unit or sign, or bare but a decimal
    or three digits or more (a bare 5 may be "a team of 5")."""
    d, u = f
    return not _year(d) and bool(u or "." in d or len(d) >= 3)


def _bare(word):
    """word lower-cased without a possessive ("vendor's", "vendors'")."""
    return re.sub(r"['’]s?$", "", word.lower())


def _root(word):
    """The start of word that its other forms share: five letters of a long word (catalogues: catal), else the word
    without a plural s or its y (study: stud, so studies matches)."""
    w = _bare(word)
    if len(w) >= 6:
        return w[:5]
    w = w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
    return w[:-1] if len(w) > 3 and w.endswith("y") else w


# A clause of the material: its sentences split at a semicolon, a colon (not 09:15's), a dash between spaces or a
# comma before "but", "while", ...
_CLAUSE_SPLIT = re.compile(r";|(?<!\d):(?!\d)|\s[–—]\s|,\s+(?=(?:but|while|whereas|although|though|yet|so)\b)", re.I)
# ... that denies the data: "No benchmark results for 8K renders were available", "Vendor price lists weren't
# available", "I couldn't find a published survey", "Nothing was measured", "unknown", "none found", a lone "none" or
# "n/a" (a "no" reaches its verb across "or", not past a comma or an "and": "Octane has no free tier, and the benchmark
# found it 12% faster" denies nothing)
_NO_REACH = r"\b(?:no|none|nothing|neither)\b(?:(?!\b(?:and|but|while|whereas|yet)\b)[^,()]){0,80}?"
_UNAVAILABLE = re.compile(
    r"\bun(?:available|obtainable|known)\b|" +
    _NO_REACH + r"\b(?:(?:was|were|is|are|has\s+been|have\s+been|had\s+been)\s+(?:\w+\s+)?)?(?:available|given|"
    r"provided|published)\b|" +
    _NO_REACH + r"\b(?:was|were|is|are|has\s+been|have\s+been|had\s+been)\s+(?:\w+\s+)?(?:run|conducted|performed|"
    r"measured|recorded|collected|taken|done|carried\s+out|found)\b|"
    r"(?:n['’]t|\bnot)\s+(?:be\s+|been\s+)?(?:\w+\s+)?(?:available|found|located|obtained|accessed|accessible|verified|"
    r"confirmed|given|provided|published)\b|"
    r"(?:n['’]t|\bnot|\bunable\s+to|\bfailed\s+to)\s+(?:\w+\s+)?(?:find|locate|obtain|access|verify|confirm|"
    r"retrieve)\b|\bfound\s+no(?:thing)?\b|"
    r"\bnone\s+(?:was\s+|were\s+|has\s+been\s+|could\s+be\s+)?(?:found|located|identified|available|given|published)\b|"
    r"^[\W_]*(?:none|n/a|nil|tb[dc])[\W_]*$")
# ... and a word after a "no" or a "not" in its clause, up to 30 characters on and not past an "and": "there were no
# sensor readings"
_DENIED_BEFORE = re.compile(r"(?:\b(?:no|not|never|without|nor|neither|none|nothing|lacks?|lacking)\b|n['’]t\b)"
                            r"(?:(?!\b(?:and|but|while|whereas|yet|so|which|that)\b)[^,()]){0,30}$")
# A label before a colon that lists what is missing ("Missing data: render times at 8K, benchmark scores", "Still
# needed: ..."): it and what follows deny the data, as "Benchmarks: none found" does
_GAP_LABEL = re.compile(r"^[\W_]*(?:(?:still\s+)?missing(?:\s+\w+)?|(?:data\s+)?gaps?|unknowns?|open\s+questions?|"
                        r"not\s+(?:yet\s+)?(?:available|found|known|verified|confirmed)|(?:still\s+)?needed|"
                        r"to\s+(?:find|gather|collect|confirm|verify|check))[\W_]*$")
# A clause that asks for data or says it would help rather than giving it: a modal or a recommendation ("The studio
# should run its own benchmark", "would be needed", "Recommended next step: benchmark both engines")
_IDLE = re.compile(r"\b(?:will|would|should|could|might|must|shall|can)\b|\bmay\b(?!\s+\d)|['’]ll\b|\brecommend\w*|"
                   r"\b(?:i|we)\s+(?:would\s+)?(?:suggest|propose|advise)\b|\bnext\s+steps?\b|\bneeds?\s+to\b|"
                   r"\b(?:needed|required|planned|proposed|scheduled|requested|pending|ideally|tb[dc])\b|"
                   r"\bconsider(?:ing)?\b|\bworth\s+\w+ing\b|\bto\s+be\s+(?:confirmed|determined|verified|measured|"
                   r"tested|run|done|gathered|collected|checked)\b")
# A clause of the own words that points at another step's output ("Based on the benchmark data from s1", "the outputs
# of steps s1-s3", "s1's survey", "from the previous step"): it names data it doesn't give
_AWAY = re.compile(r"(?<![\w/.$@#:\\-])(?:steps?\s*)?s\d{1,2}(?![\w/@#\\-]|:/|\.\w)|\bsteps?\s+\d{1,2}\b|"
                   r"\b(?:previous|prior|earlier|preceding)\s+(?:steps?|sections?|parts?)\b|\bresearch\s+steps?\b",
                   re.I)
# A clause of material: lower-cased (low), its text (raw), where it starts in its sentence (at), denies the data,
# asks for it (idle), points at another step (away), ends in a colon, its figures, and whether its sentence carries a
# mark (marked); a sentence of material: its text, its clauses, the figures of those that don't deny the data, is a
# label, and its line's number (line)
_Clause = collections.namedtuple("_Clause", "low raw at denies idle away colon figs marked")
_Sent = collections.namedtuple("_Sent", "text clauses figs label line")


def _read(text, labels, title=False, marks=True, base=0):
    """Material text as sentences (_Sent). A clause's figures are left out when it denies the data, and a sentence's
    when it carries a mark (_MARKED; marks False reads them as data, to tell a dropped mark from a made-up claim): a
    dependency's "(unverified)" guess is no data, and restated without its mark it is the smoke's invented benchmark.
    A clause that ends in a colon and the one after it deny the data when either does or the first lists what is
    missing (_GAP_LABEL), and are idle when either is. A heading line, or every line when title (the plan's or the
    step's title), is a label, whose figures but years are left out ("OctaneRender 2024"). Lines count from base."""
    out = []
    for n, line in enumerate(_HIDDEN.sub(" ", (text or "").translate(_DASHES)).split("\n")):
        label = title or line.lstrip().startswith("#")
        for s in _SENTENCE_END.split(line):
            if not s.strip():
                continue
            marked = marks and bool(_MARKED.search(s))
            clauses, at = [], 0
            for m in list(_CLAUSE_SPLIT.finditer(s)) + [None]:
                c = s[at:m.start() if m else len(s)]
                low = " ".join(c.lower().split())
                clauses.append(_Clause(low, c, at, bool(_UNAVAILABLE.search(low)), bool(_IDLE.search(low)),
                                       bool(_AWAY.search(c)), bool(m) and m.group(0) == ":",
                                       [] if marked else [f for f in _figs(c, labels) if not label or _year(f[0])],
                                       marked))
                at = m.end() if m else len(s)
            for k in range(len(clauses) - 1):
                a, b = clauses[k], clauses[k + 1]
                if a.colon:
                    denies = a.denies or b.denies or bool(_GAP_LABEL.search(a.low))
                    idle = a.idle or b.idle
                    clauses[k], clauses[k + 1] = (x._replace(denies=x.denies or denies, idle=x.idle or idle)
                                                  for x in (a, b))
            clauses = [c._replace(figs=[]) if c.denies else c for c in clauses]
            out.append(_Sent(s, clauses, [f for c in clauses for f in c.figs], label, base + n))
    return out


def _material(own, pieces, labels, marks=True):
    """What _restates reads in the step's given material: own, the step's own words as [(text, is a title)] (or one
    text), and pieces, the dependencies' pieces and the previous result (a list, or one text). Its blocks of sentences
    ("own": one block, "pieces": one a piece; _read), each block with whether it is the own words and the units each of
    its figures comes with ("blocks"), the units of all figures ("figs": the pieces' all, the own words' only where
    _data_fig), the own words' bare counts, each with the word it counts ("counts": "We surveyed 40 plot holders"
    gives ("40", "plot"); _restates), its years, and the claims the own words' sentences make themselves, not in a
    sentence with a mark, a clause that points at another step or a question they ask ("Find out what the soil survey
    found": "own_claims": (kind, key root))."""
    own = [(own, False)] if isinstance(own, str) else list(own or ())
    pieces = [pieces] if isinstance(pieces, str) else list(pieces or ())
    o = [x for k, (text, title) in enumerate(own) for x in _read(text, labels, title, marks, 100000 * k)]
    p = [_read(text, labels, marks=marks) for text in pieces if text]
    blocks, figs = [], {}
    for block, own_words in ([(o, True)] if o else []) + [(b, False) for b in p]:
        bf = {}
        for x in block:
            for f in x.figs:
                if not _year(f[0]) and (not own_words or _data_fig(f)):
                    bf.setdefault(f[0], set()).add(f[1])
                    figs.setdefault(f[0], set()).add(f[1])
        blocks.append((block, own_words, bf))
    counts = {(f[0], _next_root(c.raw, at)) for x in o if not x.label for c in x.clauses
              if not (c.denies or c.marked or c.away) for at, f in _figs_at(c.raw, labels) if not f[1]}
    return {"own": [o] if o else [], "pieces": p, "blocks": blocks, "labels": labels, "figs": figs, "counts": counts,
            "years": {f[0] for block in [o] + p for x in block for f in x.figs if _year(f[0])},
            "own_claims": {(kind, k) for x in o if not x.label and not any(c.marked for c in x.clauses)
                           for kind, m, _ in _matches(x.text) if not _clause_at(x.clauses, m.start()).away and
                           not _OPEN.search(x.text[:m.start()].lower()) for k in _keys(m)}}


def _next_root(text, at) -> str:
    """The root of the word right after the figure that starts at text[at:] ("40 plot holders": plot), else ""."""
    w = re.match(r"[\d.,:]*\s*([^\W\d_][\w'’-]*)", text[at:])
    return _root(w.group(1)) if w else ""


def _clause_at(clauses, at):
    """The clause of a sentence's clauses that holds the character at position at."""
    return [c for c in clauses if c.at <= at][-1]


def _given_fig(f, figs) -> bool:
    """Does the material give figure f: the same digits, with the same unit, or with no unit on one side ("12 s"
    isn't "12%")?"""
    units = figs.get(f[0])
    return bool(units) and (not f[1] or "" in units or f[1] in units)


@functools.lru_cache(maxsize=512)
def _word_rx(root, flags=0):
    tail = "" if len(root) >= 5 else r"(?:s|es|ies|y|ing|ed|er|ers|ly)?\b"
    return re.compile(r"(?<![^\W\d_])" + re.escape(root) + tail, flags)


def _holds(root, block, own=False, results=False) -> bool:
    """Does block (one of _material's) hold a word that starts with root (a short root: one of its own forms)? Only in
    a clause that doesn't deny the data and not after a "no" or a "not" in it; in the own words (own) not in a clause
    that points at another step ("Based on the benchmark data from s1": that step's piece has to hold it); for a result
    or a measurement (results) not in a sentence with a mark; and in a label (a heading, a title) only when the block's
    other sentences don't deny it: a piece headed "## Survey" that says "No survey results were available" gives no
    survey. For a claim with figures, which they have to give too (_tied)."""
    if not root:
        return False
    rx = _word_rx(root)
    said = labelled = denied = False
    for x in block:
        for c in x.clauses:
            if (own and c.away) or (results and c.marked):
                continue
            for m in rx.finditer(c.low):
                ok = not c.denies and not _DENIED_BEFORE.search(c.low[:m.start()])
                if x.label:
                    labelled = labelled or ok
                else:
                    said, denied = said or ok, denied or not ok
    return said or (labelled and not denied)


def _pointed(mat, roots, data) -> bool:
    """For a claim with figures whose words the own words hold only in a clause that points at another step ("Based on
    the yield analysis from s1"): given when every root is held there or by a piece, a piece holds one, and the pieces
    give every one of its figures, not half ("According to the yield analysis, bed A gave 4.2 kg" over s1's "Bed A gave
    4.2 kg"; not "Benchmarks show Octane needs 8 GB and renders 40% faster" over an honest s1's "8 GB")."""
    pieces = [(b, bf) for b, own, bf in mat["blocks"] if not own]
    return bool(mat["own"] and pieces) and all(_holds(r, mat["own"][0]) or any(_holds(r, b) for b, _ in pieces)
                                               for r in roots) and \
        any(_holds(r, b) for r in roots for b, _ in pieces) and \
        all(any(_given_fig(f, bf) for _, bf in pieces) for f in data)


def _tied(blocks, data, holds) -> bool:
    """For a claim with figures: do the blocks of the material (_material's "blocks") that hold what it is about
    (holds(block, is the own words)) give at least half of its figures (data) between them? A figure that another
    block gives (a spec, a price) doesn't make "Benchmarks show Octane needs 8 GB of VRAM and renders 40% faster" a
    benchmark's."""
    held = [bf for b, own, bf in blocks if holds(b, own)]
    return bool(held) and 2 * sum(any(_given_fig(f, bf) for bf in held) for f in data) >= len(data)


def _keys(m):
    """The roots of what claim m is about: its key group's first word, and each kw_<word> group's word (a survey for
    "62% of respondents")."""
    out = [_root(x) for x in re.findall(r"[^\W\d_]+", m.groupdict().get("key") or "")[:1]]
    out += [_root(g[3:]) for g, v in m.groupdict().items() if g.startswith("kw_") and v is not None]
    return list(dict.fromkeys(out))


def _cited(s, m):
    """The words of the name a source claim cites: its name group when it has one ("Grand View Research"), else from
    its src group to the first punctuation, joining word or article after a word of it ("the price list the team
    supplied": price, list), four at most, articles, numbers and the like left out."""
    out = []
    named = m.groupdict().get("name")
    text = named if named is not None else re.split(r"[.,;:()\[\]!?|\"“”]", s[m.end("src"):], maxsplit=1)[0]
    for w in _WORDS.findall(text)[:8]:
        lw = _bare(w)
        if out and (lw in _CUT or lw in _ARTICLES or len(out) == 4):
            break
        if lw not in _STOP and lw not in _CUT and not lw[:1].isdigit():
            out.append(lw)
    return out


# What a piece's clause says when it gives data, not only the word: a result verb ("The tool audit found ...", "Dan
# says ..."), or the word with a verb in the past after it ("The benchmark covered the 4K photos")
_GIVING = re.compile(r"\b(?:shows?|showed|shown|found|finds|findings?\s+that|says|said|indicates?|indicated|"
                     r"suggests|suggested|confirms?|confirmed|reveals?|revealed|puts?|rated|ranked|scored|gives|gave|"
                     r"measured|recorded|logged|reported|estimated|totall?ed|came\s+to|prefers?|preferred)\b")
_SUBJECT_PAST = re.compile(r"[\w'’-]*(?:\s+(?!(?:was|were|is|are|be|been|being|has|have|had)\b)[\w'’-]+)?\s+"
                           r"([^\W\d_]{2,}ed|showed|found|gave|took|ran|beat|won|came|drew|rose|fell)\b")
# ... and what the step's own words say before the figures that are the data ("Summarise the survey, which found 62%
# prefer ...", "the benchmark result is 1.8 s"; not "the survey of 120 members", "benchmarks for a $5,000 budget")
_GIVES_AFTER = re.compile(r"\b(?:shows?|showed|shown|found|finds|says|said|reports?|reported|recorded|measured|logged|"
                          r"gave|gives|puts?|reads|came\s+to|totals?|totall?ed|reached|peaked|averaged|averages|was|"
                          r"were|is|are)\b", re.I)
# A cited name that is data ("the benchmark", "the license cost data", "the survey"), which a clause has to give, not
# only name; a person's or a document's name ("Dan, the head baker") a clause need only name
_DATA_WORD = re.compile(_SOURCE + "|" + _DATA + "|" + _SOURCED + r"|tests?|testing|trials?|benchmarking|"
                        r"measurements?|experiments?|readings?|findings?|analys[ie]s|audits?|polls?")
# Words of a sentence that say nothing of what it claims, for _content
_PLAIN = (_STOP | _CUT | _ARTICLES | _PRONOUNS | {
    "be", "been", "being", "has", "have", "had", "does", "did", "do", "them", "there", "also", "more", "most", "very",
    "then", "into", "out", "about", "any", "other", "such", "only", "just", "not", "can", "will", "would", "should",
    "could", "may", "might", "must", "here", "two", "three", "four", "five", "according", "section", "sections",
    "part", "document", "table", "list", "step", "steps", "previous", "above", "below", "earlier", "following",
    "preceding", "taken", "sourced", "drawn", "pulled", "per", "based", "through", "throughout", "across", "around",
    "among", "against", "toward", "towards", "upon", "onto", "within", "without", "while", "near", "beyond"})


_CONTENT_SPLIT = re.compile(r";|\s[–—]\s|,\s+(?=(?:so|but|while|whereas|yet|which|therefore|hence|thus|meaning|"
                            r"making|and\s+so)\b)", re.I)
# The words that make a claim of a sentence rather than say what it claims: a claim's verbs, its test and source
# nouns, its leads ("According to", "In our", "A panel of")
_CLAIM_WORD = re.compile(
    r"(?:show|indicat|suggest|reveal|confirm|demonstrat|report|estimat|believ|predict|anticipat|forecast|project|"
    r"argu|consider|measur|record|logg|monitor|captur|benchmark|experiment|conduct|perform|execut|according|sourc|"
    r"obtain|gather|collect|compil|scrap|retriev|publish|advertis|research|survey|analys|statist|observ|independent|"
    r"industry|official|pricing|percent|rating|ranking|reading|timing|salar|citation|quot)\w*$|"
    r"(?:prov(?:e|es|ed|en)|find|finds|found|put|puts|place[sd]?|gave|give[sn]?|say|says|said|note[sd]?|warn(?:s|ed)?|"
    r"agree[sd]?|expect(?:s|ed)?|think|thinks|thought|see|sees|saw|test(?:s|ed|ing)?|trials?|runs?|ran|carried|done|"
    r"made|taken|based|pulled|drawn|copied|public|publicly|lists?|listed|posts?|posted|has|have|had|been|was|were|"
    r"stud(?:y|ies)|polls?|reviews?|data|figures?|stats?|panel|recent|latest|market|prices?|costs?|rates?|fees?|"
    r"values?|numbers?|totals?|amounts?|counts?|metrics?|specs?|specifications?|details?|info|information|results?|"
    r"scores?|websites?|site|pages?)$")
# Words in -ly that aren't adverbs (_content leaves out "steadily", "clearly")
_LY_NOUNS = {"supply", "family", "assembly", "reply", "apply", "italy", "july", "rally", "belly", "jelly", "holly",
             "anomaly", "monopoly", "butterfly", "firefly", "dragonfly", "lily", "comply", "multiply", "doily"}


def _data_word(w) -> bool:
    return bool(_DATA_WORD.fullmatch(w))


def _content(s, m, names=()):
    """The roots of what sentence s says beside what claim m is about and the name it cites (names): the words of the
    claim's clause (to a semicolon, a dash or a comma before "so", "which", ...: "..., so the club should train then"
    is what follows from it) of three letters or more but numbers, adverbs in -ly and _PLAIN's, outside the claim and
    inside it but for its key and the words that only make it a claim (_CLAIM_WORD: "Measured render times favour
    Octane" says render, times, favou and octan; "According to the research summary, both engines support out-of-core
    textures": engines, suppo, out-o, textu)."""
    out = []
    key = m.span("key") if m.groupdict().get("key") is not None else (0, 0)
    inner = s[m.start():key[0]] + " " + s[key[1]:m.end()] if key[1] else s[m.start():m.end()]
    a = max([x.end() for x in _CONTENT_SPLIT.finditer(s, 0, m.start())] or [0])
    b = next((x.start() for x in _CONTENT_SPLIT.finditer(s, m.end())), len(s))
    for w in _WORDS.findall(s[a:m.start()] + " " + s[m.end():b]) + [w for w in _WORDS.findall(inner)
                                                                    if not _CLAIM_WORD.match(_bare(w))]:
        lw = _bare(w)
        if len(lw) >= 3 and lw not in _PLAIN and lw not in names and not lw[:1].isdigit() and \
                not (len(lw) > 4 and lw.endswith("ly") and lw not in _LY_NOUNS):
            out.append(_root(lw))
    return list(dict.fromkeys(out))


def _window(block, j) -> str:
    """Sentence j of block with the one after it on the same line, lower-cased: what a piece's sentence that gives the
    data says ("The survey had 120 replies. Tuesday evening was the clear favourite at 64%.")."""
    x = block[j]
    text = x.text
    if j + 1 < len(block) and block[j + 1].line == x.line:
        text += " " + block[j + 1].text
    return text.lower()


def _shares(content, text) -> bool:
    """Does text hold at least half of content (_content's roots)? True for no content."""
    return not content or 2 * sum(bool(_word_rx(r).search(text)) for r in content) >= len(content)


# A label of a body's own (not a heading) over the rows that hold the data: a clause that ends its sentence with a
# colon and names a results noun ("Survey results:", "Readings (taken hourly on 3 June):", "Benchmark scores:"); not
# "Survey details:", whose rows ("- Sent to: 340 members") are no data
_RESULTS_NOUN = re.compile(r"\b(?:results?|scores?|findings|figures|data|readings?|measurements?|times|timings?|"
                           r"responses|answers|votes|ratings?|rankings?|totals?|numbers|counts?|shares|breakdown|stats|"
                           r"statistics|percentages?|summary|prices|costs|rates|yields|levels|values)\b")
_ROW = re.compile(r"^\s*(?:[-*•+]\s|\d{1,2}[.)](?:\s|$)|\||\d)")  # a list item's, a table row's or a reading's line
_ROWS_MAX = 24


def _rows_under(block, j, k, own=False):
    """(figures, text) of the list or table rows under clause k of sentence j of block when that clause is such a
    label (above), the own words' figures only where _data_fig; else ([], "")."""
    x = block[j]
    c = x.clauses[k]
    if x.label or not c.colon or any(r.low.strip() for r in x.clauses[k + 1:]) or not _RESULTS_NOUN.search(c.low):
        return [], ""
    figs, text, line = [], [], x.line
    for y in block[j + 1:]:
        if y.line != line:
            if y.label or not _ROW.match(y.text) or len(text) >= _ROWS_MAX:
                break
            line = y.line
        figs += [f for f in y.figs if not _year(f[0]) and (not own or _data_fig(f))]
        text.append(y.text)
    return figs, " ".join(text).lower()


def _rows_after(block, j) -> bool:
    """Do list or table rows with figures of data follow sentence j of the own words' block, under no label ("Summarise
    the staff survey." over "| Hybrid | 62% |")? For the tell only (_cite_fits): rows under no label give no claim."""
    line, rows = block[j].line, 0
    for y in block[j + 1:]:
        if y.line != line:
            if y.label or not _ROW.match(y.text) or rows >= _ROWS_MAX:
                return False
            line, rows = y.line, rows + 1
        if any(_data_fig(f) for f in y.figs):
            return True
    return False


def _hedged(c) -> bool:
    """Does clause c, which has a modal, still give data: a result verb and a figure ("64% of the 120 members who
    replied said they would prefer Tuesday evenings", "The survey shows 64% of members can make Tuesday")?"""
    return bool(_GIVING.search(c.low)) and any(not _year(f[0]) for f in c.figs)


def _piece_gives(root, block, need, content, results=False):
    """For a claim with no figure: does a piece (a block of _read's) give root? A clause that holds it, doesn't deny
    the data and doesn't ask for it (_IDLE, unless _hedged), and, when need (the word is data: a benchmark, a survey),
    says the data: a figure, after its colon too, a result verb (_GIVING), the word with a verb in the past after it,
    or a comparison (_compares); and the sentence that says it (with the one after it on its line: _window) holds at
    least half of what the claim says (content, _content's roots): "Both vendors' benchmarks show only GPU speed scores"
    or "Running a benchmark takes about 2 days" gives no "Benchmarks show Octane produces cleaner reflections", and a
    long previous result that names every topic gives nothing it doesn't say. Or a label of the piece's body that holds
    it over rows with figures that hold one of those roots (_rows_under: "Survey results:" over "- Tuesday evening:
    64%"). For a result or a measurement (results) a sentence with a mark gives nothing. Else, where the piece names
    the word (its heading too) and never denies or asks for it, only when its text holds all of what the claim says,
    or has figures when the claim says nothing more: an honest piece headed "## Benchmark findings" that says
    "OctaneBench is Otoy's own benchmark tool" or only "both engines render on the GPU" gives no "Octane is faster",
    while "## Soil survey" over "Bed B is clay" gives "According to the soil survey, bed B is clay"."""
    rx = _word_rx(root)
    held = against = False
    for j, x in enumerate(block):
        for k, c in enumerate(x.clauses):
            if results and c.marked:
                continue
            for m in rx.finditer(c.low):
                ok = not c.denies and not _DENIED_BEFORE.search(c.low[:m.start()])
                if x.label or (ok and (not c.idle or _hedged(c))):
                    if not x.label:
                        after = x.clauses[k + 1:k + 2] if c.colon else []
                        if not need or (_says_data(c, after, m) and _shares(content, _window(block, j))):
                            return True
                        figs, rows = _rows_under(block, j, k)
                        if figs and (not content or any(_word_rx(r).search(rows + " " + c.low) for r in content)):
                            return True
                    held = held or ok
                else:
                    against = True
    if not held or against:
        return False
    body = [c for x in block if not x.label for c in x.clauses if not c.denies and not (results and c.marked)]
    if not content:
        return any(not _year(f[0]) for c in body for f in c.figs)
    return all(any(_word_rx(r).search(c.low) for c in body) for r in content)


def _says_data(c, after, m) -> bool:
    """Does clause c (with the clause after its colon, after: "Survey: most members prefer Tuesday") say data next to
    word m (a match in c.low)?"""
    return _past_after(c.low, m) or any(any(not _year(f[0]) for f in x.figs) or _GIVING.search(x.low) or
                                        _compares(x.raw) for x in [c] + after)


def _past_after(low, m) -> bool:
    """Is word m of low the subject of a verb in the past ("the benchmark covered", "benchmark results showed")?"""
    v = _SUBJECT_PAST.match(low, m.end())
    return bool(v) and v.group(1) not in _NOT_PAST and not v.group(1).endswith("eed")


# A name the own words give only as a place to get data ("using data from Statista and CNET", "check Otoy's site"),
# which they have to give or say what it found, as a name that is data; and one they give only as someone to act ("Ask
# Dan, the head of sales, to sign it", "mention our partner Grand View Research"), which names no source
_FETCH = re.compile(r"\b(?:from|using|use|via|consult(?:ing)?|check(?:ing)?|search(?:ing)?|brows(?:e|ing)|"
                    r"pull(?:ing)?|draw(?:ing)?|cit(?:e|ing)|referenc(?:e|ing)|such\s+as|like|e\.g\.)\s+"
                    r"(?:[\w'’&.-]+\s+){0,8}$")
_ACTS = re.compile(r"\b(?:ask|tell|invite|thank|remind|have|get|let|email|e-mail|call|phone|cc|introduce|welcome|"
                   r"congratulate|mention|credit|tag|contact|meet|brief|copy)\s+(?:(?:our|my|the|your)\s+"
                   r"(?:[\w'’-]+\s+){0,2})?$")


def _own_names(root, block, need, content=()) -> bool:
    """For a source claim with no figure: do the step's own words (a block of _read's) name root, in a clause that
    isn't a label (a title names a topic), doesn't point at another step and doesn't deny it, and not only as someone
    to act (_ACTS)? When need (the name is data) or the own words name it only as a place to get data (_FETCH), only
    where they give it (_own_gives) or say what it found ("Summarise the survey, which found that most members prefer
    Tuesday"; not "Summarise the survey of 120 members", "Write up the customer survey", "using data from Statista")."""
    if _own_gives(root, block, content):
        return True
    rx = _word_rx(root)
    for x in block:
        if x.label:
            continue
        for c in x.clauses:
            if c.denies or c.away:
                continue
            for m in rx.finditer(c.low):
                pre = c.low[:m.start()]
                if _DENIED_BEFORE.search(pre) or _ACTS.search(pre):
                    continue
                said = _GIVING.search(c.low, m.end())
                if not (need or _FETCH.search(pre)) or (said and not _OPEN.search(c.low[:said.start()]) and
                                                        re.search(r"[^\W\d_]", c.low[said.end():])):
                    return True
    return False


_BARE = re.compile(r"^\s*(?:the\s+)?(?:data|figures|numbers|statistics|stats)\b", re.I)


def _bare_data(s, m, mat, data) -> bool:
    """For "according to the data" (or "the figures"), which names nothing to look for: the step's given data. With
    figures, those it gives (the half _restates checked); with none, a sentence of the material that says data (a
    figure, or in a piece a result verb), doesn't deny it, ask for it, carry a mark or point at another step, and holds
    half of what the claim says (_window, _shares)."""
    if "src" not in m.re.groupindex or not _BARE.match(s[m.end("src"):]):
        return False
    if data:
        return True
    content = _content(s, m)
    for block, own, _ in mat["blocks"]:
        for j, x in enumerate(block):
            if not x.label and any(
                    not (c.denies or c.idle or c.marked or c.away) and
                    (any(not _year(f[0]) and (not own or _data_fig(f)) for f in c.figs) or
                     (not own and _GIVING.search(c.low))) for c in x.clauses) and _shares(content, _window(block, j)):
                return True
    return False


def _restates(kind, s, m, mat):
    """True when claim m (of kind, in sentence s) is the step's given data: mat is _material's reading of it, or None
    when it was given nothing. See the notes above."""
    if kind == "ran" or not mat:
        return False
    # a bare count the own words give with the word it counts ("We surveyed 40 plot holders", "the 3 beds") is theirs,
    # as a label is: neither data the claim adds nor a figure that excuses it, which leaves the claim to its words
    nums = [f for p, f in _figs_at(s, mat["labels"])
            if f[1] or _year(f[0]) or (f[0], _next_root(s, p)) not in mat["counts"]]
    data = [f for f in nums if not _year(f[0])]
    figs, blocks = mat["figs"], mat["blocks"]
    if data and 2 * sum(_given_fig(f, figs) for f in data) < len(data):
        return False
    if not data and any(f[0] not in mat["years"] for f in nums):
        return False  # "According to a 2023 study": a year nothing gave
    if kind == "source":
        names = _cited(s, m)
        if not names:
            return _bare_data(s, m, mat, data)
        if not data and any(_OUTSIDE.fullmatch(w) for w in names):
            return False
        if data:
            return (all(any(_holds(_root(w), b, own) for b, own, _ in blocks) for w in names) and
                    _tied(blocks, data, lambda b, own: any(_holds(_root(w), b, own) for w in names))) or \
                _pointed(mat, [_root(w) for w in names], data)
        content = _content(s, m, names)
        return all(any(_own_names(_root(w), b, _data_word(w), content) for b in mat["own"]) or
                   any(k == _root(w) for _, k in mat["own_claims"]) or
                   any(_piece_gives(_root(w), b, _data_word(w), content) for b in mat["pieces"]) for w in names)
    keys = _keys(m) + (list(_MEASURING) if kind == "measure" else [])
    if data:
        return _tied(blocks, data, lambda b, own: any(_holds(k, b, own, True) for k in keys)) or \
            any(_pointed(mat, [k], data) for k in keys)
    content = _content(s, m)
    return any(any(_piece_gives(k, b, True, content, True) for b in mat["pieces"]) or (kind, k) in mat["own_claims"]
               for k in keys) or any(_own_gives(k, block, content) for k in keys for block in mat["own"])


# What the own words say about the data that isn't the data: a target or a limit ("The target benchmark time is 4
# minutes", "The survey target is 200 responses"), a bound before a figure ("under 5 minutes"), a question or a
# condition ("Check whether the benchmark is ...", "Find out if the survey is above 60%"), and a size or a time before
# a figure ("the survey of 120 members", "a $5,000 budget", "(n = 340)", "at 7:30 pm")
_TARGET = re.compile(r"\b(?:targets?|goals?|aims?|budgets?|limits?|caps?|maximum|minimum|required|requirements?|"
                     r"thresholds?|deadlines?|quotas?)\b", re.I)
_BOUND = re.compile(r"\b(?:under|over|above|below|at\s+least|at\s+most|up\s+to|within|less\s+than|more\s+than|"
                    r"fewer\s+than|no\s+more\s+than|no\s+less\s+than|exceeds?|exceeding|beyond)\s*[~≈]?\s*[$€£¥]?$",
                    re.I)
_IF_BEFORE = re.compile(r"\b(?:if|whether|unless|until|in\s+case|to\s+see)\b", re.I)
_SIZE_BEFORE = re.compile(r"(?:\b(?:of|for|with|among|from|across|to|a|an|the|our|their|its|his|her|my|your|all|"
                          r"budget|sample|n|at|on|by|until|before|after|in|per|every|each|than|within|under|over|"
                          r"above|below|this|next|last|since)\s*[=:]?\s*[~≈]?\s*[$€£¥]?|\(\s*[nN]\s*=\s*)$", re.I)


def _own_gives(root, block, content=()) -> bool:
    """Do the step's own words (a block of _read's) give the data a claim with no figure is about: a clause that holds
    root (not a label, not denied, not after a "no", not pointing at another step, not asking whether or setting a
    target: _OPEN, _IF_BEFORE, _TARGET) with figures of data after a colon ("Summarise this customer survey: 62% prefer
    ..."), in the rows under it when it is a label (_rows_under: "Survey results:" over "- Hybrid working: 62%"), or
    after it in its clause ("In the survey, 62% want hybrid working", "the survey, which found 62% ...", "the benchmark
    result is 1.8 s"), where what sits before the figure isn't a size, a bound or a time (_SIZE_BEFORE, _BOUND: "the
    survey of 120 members", "benchmarks for a studio with a $5,000 budget", "(n = 340)", "under 5 minutes"), unless a
    word that says what the data is comes between; and the sentence holds half of what the claim says (content)?"""
    rxi = _word_rx(root, re.I)
    for j, x in enumerate(block):
        if x.label:
            continue
        window = _window(block, j)
        for k, c in enumerate(x.clauses):
            if c.denies or c.away or c.marked:
                continue
            for m in rxi.finditer(c.raw):
                pre = c.raw[:m.start()]
                if _DENIED_BEFORE.search(pre.lower()) or _OPEN.search(pre.lower()) or _IF_BEFORE.search(pre) or \
                        _TARGET.search(pre[-25:]) or _TARGET.search(c.raw[m.end():m.end() + 15]):
                    continue
                if c.colon and k + 1 < len(x.clauses) and any(_data_fig(f) for f in x.clauses[k + 1].figs) and \
                        _shares(content, window):
                    return True
                figs, rows = _rows_under(block, j, k, own=True)
                if figs and (not content or any(_word_rx(r).search(rows + " " + c.low) for r in content)):
                    return True
                for p, f in _figs_at(c.raw, frozenset()):
                    if p < m.end() or p - m.end() > 80 or f not in c.figs or not _data_fig(f):
                        continue
                    between = c.raw[m.end():p]
                    if _BOUND.search(c.raw[:p]) or _TARGET.search(between) or _OPEN.search(between.lower()) or \
                            _IF_BEFORE.search(between):
                        continue
                    if (_GIVES_AFTER.search(between) or not _SIZE_BEFORE.search(c.raw[:p])) and \
                            _shares(content, window):
                        return True
    return False


def given_material(plan, i, dep_texts=(), missing_deps=(), prev_result=""):
    """(the step's own words, the pieces it was given): the text section step i was given to draw its facts from. Its
    own words are the plan's title and summary and the step's title and instructions, or "" when a dependency is
    missing (missing_deps names it, its piece in dep_texts is empty, or dep_texts doesn't hold it); the pieces are its
    dependencies' that are there, each without its handoff (whose "assumed" holds guesses), and prev_result, the
    previous round's result that Chimera's request gives a round-2+ step ("" in round 1), whichever is missing.
    dep_texts: {sid or plan id: text or None}, as task.py builds them for the prose judge, or the texts themselves."""
    own, pieces = _given_blocks(plan, i, dep_texts, missing_deps, prev_result)
    return "\n\n".join(x for x, _ in own), "\n\n".join(pieces)


def _given_blocks(plan, i, dep_texts=(), missing_deps=(), prev_result=""):
    """given_material's two parts as _material reads them: the own words as [(text, is a title)] ([] when a dependency
    is missing), and the pieces as a list of texts."""
    steps = plan.get("steps") or []
    st = steps[i]
    deps = planinfo.dep_indexes(plan, i)
    if isinstance(dep_texts, dict):
        have = {k for k, v in dep_texts.items() if v}
        pieces = [dep_texts[k] for k in dep_texts if k in have]
        missing = any(f"s{j + 1}" not in have and steps[j].get("id") not in have for j in deps)
    else:
        pieces = [t for t in (x[1] if isinstance(x, (tuple, list)) else x for x in dep_texts or ()) if t]
        missing = len(pieces) < len(deps)
    own = [] if missing or missing_deps else [(x, title) for x, title in (
        (plan.get("title"), True), (plan.get("summary"), False), (st.get("title"), True),
        (st.get("instructions"), False)) if x]
    return own, [x for x in [cv.strip_handoff(p) for p in pieces] + [prev_result or ""] if x]


def _matches(s):
    """Each claim the patterns find in sentence s (dashes made "-"), once: (kind, match, phrase), with what isn't one
    left out (source_claims says what) but for a mark, which _claims reads. "Measurements were taken every hour" is
    a measure, data a step may be given; "Tests were run" never is."""
    spans = []
    plain = _NOT_A_DENIAL.sub(lambda x: " " * len(x.group(0)), s)  # "It's no secret that ..." denies nothing
    for kind, rx in _CLAIMS:
        for m in rx.finditer(s):
            start = m.end("lead") if "lead" in rx.groupindex else m.start()
            before, phrase = s[:start], s[start:m.end()]
            if _CONDITION.search(before) or _NEGATED.search(plain[:start]) or _NEGATION.search(phrase) or \
                    any(a < m.end() and start < b for a, b in spans):
                continue
            if "src" in rx.groupindex and _OWN_SOURCE.match(s[m.end("src"):]):
                continue
            low, lead = phrase.lower(), _LIST_ITEM.sub("", before)
            if low.startswith("according") and not _CITES_AT.search(lead):
                continue
            if low.startswith("from") and _SENDS.search(before):
                continue
            if low.startswith("based") and _IMPERATIVE.match(lead):
                continue
            if low.startswith("per") and (not _CITES_AT.search(lead) or _IMPERATIVE.match(lead) or
                                          _SENDS.search(before) or _IMPERATIVE.match(_after_comma(s, m.end()))):
                continue
            # a soft shape where a result came out, and not an instruction after its comma ("In the test render, make
            # the Rim light brighter than the Key")
            if "soft" in rx.groupindex and (not _done(s, "advice" in rx.groupindex, m.span()) or
                                            _IMPERATIVE.match(_after_comma(s, m.end()))):
                continue
            if "outcome" in rx.groupindex and not _OUTCOME.search(re.split(r"[;:]|\bwhich\b", s[m.end():])[0]):
                continue
            if "needfig" in rx.groupindex and not any(not _year(f[0]) for f in _figs(s[:m.start()])):
                continue
            if "hasfig" in rx.groupindex and not any(not _year(f[0]) for f in _figs(s)):
                continue
            if "survey" in rx.groupindex and not _SURVEYISH.search(s):
                continue
            # a measured figure, not a target, a limit, advice or what to expect ("Keep render times under 5 minutes",
            # "Render times should stay below 10 min", "an SSIM target of 0.98", "Expect render times of about 2 min")
            if "said" in rx.groupindex and (_MODAL.search(s) or _IMPERATIVE.match(s) or _TARGET.search(s) or
                                            re.match(r"[\W_]*(?:expect|allow|plan\s+for|reckon\s+on)\b", s, re.I) or
                                            _BOUND.search(re.sub(r"\d[\d.,]*\s*\S*$", "", s[:m.end()]).rstrip())):
                continue
            spans.append((start, m.end()))
            measured = kind == "ran" and (m.groupdict().get("key") or "").lower().startswith("measur")
            yield ("measure" if measured else kind), m, " ".join(phrase.split())


# A mark that labels the whole sentence ("Assumed: ...", "**Assumption** - ...", "Unverified: ..."); any other
# qualifies only its own clause ("Octane costs $699 a seat (assumed), and benchmarks show it is 12% faster" marks the
# price, not the benchmark)
_LEAD_MARK = re.compile(r"^[\W_]*(?:assum(?:ed|ptions?)|unverified|estimated?|estimates)[\s*_]*[:–—-]", re.I)
_MARK_SPLIT = re.compile(r";|\s[–—]\s|,\s+(?=(?:and|but|while|whereas|yet)\b)", re.I)


def _qualified(s, at) -> bool:
    """Does a mark (_MARKED) qualify the claim that starts at s[at:]: one that labels the sentence, or one in the
    claim's own clause (split at a semicolon, a dash between spaces, a comma before "and", "but", ...)?"""
    if not _MARKED.search(s):
        return False
    if _LEAD_MARK.match(s):
        return True
    a = 0
    for mm in _MARK_SPLIT.finditer(s):
        if at < mm.start():
            return bool(_MARKED.search(s[a:mm.start()]))
        a = mm.end()
    return bool(_MARKED.search(s[a:]))


# Citations outside the sentences' own words: the items under a Sources or References heading or label, a footnote's
# line ("[1] Puget Systems, Octane vs Redshift at 8K, 2024."), and the cells of a table's Source column ("| Render time
# | 4 m 12 s | Puget Systems benchmark, 2024 |"); not "Further reading", nor a "| Source | Target |" mapping
_CITE_HEAD = re.compile(r"^(?:#{1,6}\s*)?[*_]*\s*(?:sources?|references?|bibliography|works\s+cited|citations?|"
                        r"sources\s+(?:and|&)\s+(?:notes|references))\s*[*_]*\s*:?\s*[*_]*\s*$", re.I)
# ... each only where it reads as a citation (a year, a link, a publisher, a study's or a page's noun), not a system a
# plan's data comes from ("ERP (SAP)", "Survey platform (Qualtrics)") or a setting's origin ("collection (created
# automatically)")
_CITATION = re.compile(r"\b(?:19|20)\d{2}\b|https?://|\bwww\.|" + _FIRM + r"|\b(?:survey|study|report|benchmark|"
                       r"website|pricing|price\s+(?:list|page)|index|census|poll|press\s+release|datasheet|"
                       r"white\s*paper|journal|et\s+al|accessed|retrieved|trial)\b", re.I)
_SYSTEM = re.compile(r"\b(?:platform|system|database|db|api|tool|portal|service|server|app|crm|erp|sql|warehouse|lake|"
                     r"feed|export|connector|sheet|spreadsheet|tracker|dashboard)s?\b", re.I)
_FOOTNOTE = re.compile(r"^\s*(?:\[\^?\d{1,2}\]|\^\d{1,2})\s*:?\s+(?=\S)")
_CITE_COL = re.compile(r"^[*_\s]*(?:data\s+)?(?:sources?|references?|citations?)[*_\s]*$", re.I)
_MAP_COL = re.compile(r"^[*_\s]*(?:targets?|destinations?|sinks?|outputs?|to|maps?\s+to)[*_\s]*$", re.I)
_NO_SOURCE = re.compile(r"^[\W_]*(?:n/?a|none|nil|tb[dc]|unknown|assumed|assumptions?|estimated?|estimates?|"
                        r"unverified|own\s+estimate|internal|(?:the\s+)?(?:brief|request|instructions?|plan))?[\W_]*$",
                        re.I)
_MD_LINK = re.compile(r"\[([^\]\n]*)\]\([^)\n]*\)")


def _source_items(section):
    """The section's citations (above) outside code that read as one (_CITATION, not _SYSTEM), each as its text with
    links made their words and *, _ and ` left out."""
    items, under, listed, col = [], False, False, None
    for raw in prose_lines(section):
        s = _INLINE_CODE.sub(" ", _HIDDEN.sub(" ", raw)).strip()
        if not s:
            continue
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if col is None:
                hit = [k for k, c in enumerate(cells) if _CITE_COL.match(c)]
                col = hit[0] if hit and not any(_MAP_COL.match(c) for c in cells) else -1
            elif col >= 0 and not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c) and col < len(cells) and \
                    not _NO_SOURCE.match(cells[col]):
                items.append(cells[col])
            continue
        col = None
        if s.startswith("#") or (s.startswith(("**", "__")) and not _LIST_ITEM.match(raw)):
            under, listed = bool(_CITE_HEAD.match(s)), False
            if under:
                continue
        if under and listed and not _LIST_ITEM.match(s):
            under = False  # a paragraph after the list
        if under:
            listed = listed or bool(_LIST_ITEM.match(s))
            items.append(_LIST_ITEM.sub("", s) if _LIST_ITEM.match(s) else s)
        elif _FOOTNOTE.match(s):
            items.append(_FOOTNOTE.sub("", s))
    items = [" ".join(_MD_LINK.sub(r"\1", x).replace("*", "").replace("_", " ").replace("`", "").split())
             for x in items if x.strip()]
    return [x for x in items if _CITATION.search(x) and
            not any(m.group(0) != "Systems" for m in _SYSTEM.finditer(x))]  # "Puget Systems" is a publisher


def _cite_fits(kind, s, m, mat) -> bool:
    """For a claim with no figure that the material doesn't excuse: does a block of it hold what the claim is about
    beside figures of data: in a piece in a sentence that shares a word with the claim (a survey's rows, a benchmark
    table), in the own words in the clause that holds the word, after its colon or in the rows under it or after its
    sentence (the person's pasted readings or table; not "Compare render quality using benchmarks; the budget is
    $5,000")? Then the material has the
    data and the claim leaves out the figure it rests on: its tell asks for that figure."""
    if kind == "ran" or not mat or any(not _year(f[0]) for f in _figs(s, mat["labels"])):
        return False
    if kind == "source":
        names = _cited(s, m)
        content = _content(s, m, names)
        roots = [_root(w) for w in names]
        holds = lambda b, own: all(_holds(r, b, own) for r in roots)  # noqa: E731 ("the data": any block)
    else:
        keys = _keys(m) + (list(_MEASURING) if kind == "measure" else [])
        content = _content(s, m)
        holds = lambda b, own: any(_holds(k, b, own) for k in keys)  # noqa: E731
    roots = roots if kind == "source" else keys
    for b, own, bf in mat["blocks"]:
        if not bf or not holds(b, own):
            continue
        if own:
            for j, x in enumerate(b):
                for k, c in enumerate(x.clauses):
                    if not x.label and not c.away and (not roots or any(_word_rx(r).search(c.low) for r in roots)) and (
                            any(_data_fig(f) for y in x.clauses[k:k + 2] for f in y.figs) or
                            _rows_under(b, j, k, own=True)[0] or _rows_after(b, j)):
                        return True
        elif any(not x.label and any(not _year(f[0]) for f in x.figs) and
                 any(_word_rx(r).search(x.text.lower()) for r in content) for x in b):
            return True
    return False


def _why(kind, s, m, mat, unmarked) -> str:
    """Which tell an unexcused claim gets: "mark" when the material gives it only in a sentence with a mark (unmarked:
    the material read with marks as data), "cite" when the material has its data but it leaves the figure out
    (_cite_fits), else "plain"."""
    if unmarked and kind != "ran" and _restates(kind, s, m, unmarked):
        return "mark"
    return "cite" if _cite_fits(kind, s, m, mat) else "plain"


def _claims(section, given=None, labels=frozenset(), why=None):
    """(claimed, given) phrases of source_claims: those it counts, and those the given material holds (given:
    given_material's pair or _given_blocks'). why, a dict, gets each claimed phrase's tell (_why)."""
    mat = _material(given[0], given[1], labels) if given and any(given) else None
    unmarked = []  # the material with marks read as data, made when a claim needs it
    out, excused = [], []

    def count(kind, s, m, phrase):
        if _restates(kind, s, m, mat):
            if phrase not in excused:
                excused.append(phrase)
            return
        if phrase not in out:
            out.append(phrase)
        if why is not None and phrase not in why:
            if not unmarked:
                unmarked.append(_material(given[0], given[1], labels, marks=False) if mat else None)
            why[phrase] = _why(kind, s, m, mat, unmarked[0])

    for s in sentences(section):
        s = s.translate(_DASHES)
        for kind, m, phrase in _matches(s):
            if kind != "ran" and "self" not in m.re.groupindex and _qualified(s, m.start()):
                continue  # no mark makes a run, or "we surveyed", true
            count(kind, s, m, phrase)
    for item in _source_items(section):
        item = item.translate(_DASHES)
        if _MARKED.search(item) or _OWN_SOURCE.match(item) or next(_matches(item), None):
            continue  # marked, the request's own, or a claim the sentences above already read
        count("source", item, re.match(r"\s*(?P<src>)", item), item)
    return out, [p for p in excused if p not in out]


def source_claims(section, given=None, labels=frozenset()):
    """The phrases in which the section claims a source, a test or a measurement it can't have had (the module's
    docstring), in order, once each: not, but for a run, in a sentence with a mark that qualifies them (_MARKED); not
    inside a condition ("if benchmarks show") or a denial ("No benchmarks were run"), not for a source the request
    gives (_OWN_SOURCE), "according to" and "per" only where they cite (_CITES_AT: the sentence's start or after a
    comma), not sending the reader to a website (_SENDS) or advising or instructing ("Update prices based on the
    latest list", "Torque the nuts per the manufacturer's specifications", "Per the manual, set ..."), a soft shape
    only where a result came out (_done), and not the step's given data (_restates; given: given_material's pair, None
    for nothing given; labels: _labels' for the plan). Where two patterns find the same words the first is kept."""
    return _claims(section, given, labels)[0]


# "step s2", "Step S2", "steps s2-s6" (any space between, a no-break one too); a bare lower-case "s3's", "(see s4)",
# "**s1**" (not in a path, a URL, a $s1, an "s3://" or an "s3 bucket")
_STEP_WORD = re.compile(r"\bsteps?\s*(s\d{1,2})\b", re.I)
_BARE_ID = re.compile(r"(?<![\w/.$@#:\\-])(s\d{1,2})(?![\w/@#\\-]|:/|\.\w|\s+(?:buckets?|storage|objects?|api|"
                      r"class|tier|endpoints?)\b)")


def step_mentions(plan, section):
    """The phrases of the section, outside code and its handoff, that name one of the plan's step ids (s1 to sN for
    its N steps), in order, once each."""
    n = len(plan.get("steps") or [])
    ids = {f"s{k + 1}" for k in range(n)}
    out = []
    for u in _units(section):
        spans = []
        for rx in (_STEP_WORD, _BARE_ID):
            for m in rx.finditer(u):
                if m.group(1).lower() in ids and not any(a <= m.start() < b for a, b in spans):
                    spans.append(m.span())
        for a, b in sorted(spans):
            phrase = " ".join(u[a:b].split())
            if phrase not in out:
                out.append(phrase)
    return out


_CSV_FIELD_MAX = 40  # characters of a header field, so a sentence with commas isn't read as a header
_CSV_WORDS_MAX = 5
_NOT_CSV = re.compile(r"[=;{}\[\]<>]")  # code: "x = f(a, b)", JSON
# A field that starts so is a clause of a sentence: "Every day, at closing time, follow this simple checklist:"
_CLAUSE_START = re.compile(r"^(?:and|or|but|nor|so|then|which|that|who|while|because|although|though|when|where|if|"
                           r"at|in|on|to|for|with|from|by|as|of|into|the|a|an|this|these|it|we|you|they|i)\b", re.I)
_ELLIPSIS = re.compile(r"^\s*(?:\.{3,}|…)\s*$")  # "..." for the rows left out of an example
_PLAIN_INFO = ("", "text", "txt", "plain", "plaintext")  # a block with one of these may hold a CSV


def _fields(line):
    return next(csv.reader([line], skipinitialspace=True), [])


def _header(line) -> bool:
    """True when line reads as a CSV header: three or more fields, each short (_CSV_FIELD_MAX characters, five
    words), none ending in a sentence's punctuation or starting a clause (_CLAUSE_START), no code's characters,
    brackets balanced."""
    s = line.strip()
    if not s or s.startswith(("|", "#", ">", "-", "*", "•")) or _LIST_ITEM.match(line):
        return False
    f = _fields(s)
    return len(f) >= 3 and all(
        x.strip() and len(x.strip()) <= _CSV_FIELD_MAX and len(x.split()) <= _CSV_WORDS_MAX and
        not x.strip().endswith((".", ":", "!", "?")) and not _CLAUSE_START.match(x.strip()) and
        not _NOT_CSV.search(x) and x.count("(") == x.count(")") for x in f)


def _rows(lines):
    """csv's rows of lines (quoted fields may hold a comma or a line break), blank rows left out, each with the
    number of the line it starts on."""
    out, k = [], 0
    reader = csv.reader(io.StringIO("\n".join(lines)), skipinitialspace=True)
    try:
        for row in reader:
            if any(x.strip() for x in row):
                out.append((k, row))
            k = reader.line_num
    except csv.Error:
        pass
    return out


def _csv_blocks(section):
    """The section's CSVs, each as its lines: a ```csv block, a plain one (``` or ```text) whose first line reads as
    a header, and outside code a run of lines with a comma each (no list item, table row, heading or quote) whose
    first reads as a header, with two rows at least under it (a letter's address block can look like one header and
    a row)."""
    lines = (section or "").split("\n")
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    blocks, fence, info, cur, run = [], None, "", [], []
    for l in lines + [""]:
        m = _FENCE.match(l)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not l.strip()[len(m.group(1)):]:
                body = [x for x in cur if x.strip()]
                if info == "csv" or (info in _PLAIN_INFO and body and _header(body[0])):
                    blocks.append(cur)
                fence, cur = None, []
            else:
                cur.append(l)
            continue
        if m:
            fence, info, cur = m.group(1), l.strip()[len(m.group(1)):].strip().split(" ")[0].lower(), []
        row = not m and "," in l and not l.lstrip().startswith(("|", "#", ">")) and not _LIST_ITEM.match(l)
        if row and (run or _header(l)):
            run.append(l)
            continue
        if len(run) >= 3:
            blocks.append(run)
        run = []
    return blocks


def csv_fault(section):
    """The first CSV row whose number of fields isn't its header's: {"row" (1 for the first under the header),
    "fields", "header", "line" (the row's first line, stripped)}; None when every CSV of the section is whole. A
    row of only "..." stands for rows left out of an example, and is no row."""
    for block in _csv_blocks(section):
        rows = [(k, r) for k, r in _rows(block) if not (len(r) == 1 and _ELLIPSIS.match(r[0]))]
        if len(rows) < 2:
            continue
        head = len(rows[0][1])
        for n, (k, row) in enumerate(rows[1:], 1):
            if len(row) != head:
                return {"row": n, "fields": len(row), "header": head, "line": block[k].strip()}
    return None


_SESSION = re.compile(r"^\s*(?:>>>|\.\.\.)(?:\s|$)")  # an interactive session's prompts: a listing, not a script
_SESSION_START = re.compile(r"^\s*>>>(?:\s|$)")  # its first line (the lines after a prompt are its output)


def code_faults(section):
    """The python blocks of a section that don't parse, in order: [{"block" (0 for the section's first python
    block), "line" (in the block), "error", "source" (that line, stripped), "older" (OLDER_FSTRING's kind, or None),
    "bpy"}]. A section's code is what Chimera's own result check could pick as a script (pickScript): a closed block
    tagged python, py, python3, bpy or a .py name (contract.goport.python_lang), with the indent all its lines share
    taken off; never an untagged block (the 15 stored ones of the smoke runs and the eval are listings and prose), a
    shell, JSON or other block, nor an interactive session (its first line a >>> prompt, the lines after a prompt its
    output, as a doctest shows them; or every line a >>> or ... prompt). It is parsed (ast.parse), neither compiled
    nor run, as the approved item says (the main session's decision, Nov 6), so an excerpt from inside a function or
    loop ("return None", "break") passes; with this Python's grammar, and a block that imports bpy also with the
    f-string forms
    Python 3.12 added refused (older_fstring), since Blender 5.0.1 runs Python 3.11 and the gate runs Blender pieces
    in it too."""
    out = []
    blocks = [b for b in code_blocks(section or "") if b.closed and python_lang(b.lang)]
    for k, b in enumerate(blocks):
        src = textwrap.dedent(b.body)
        lines = [x for x in src.split("\n") if x.strip()]
        if not lines or _SESSION_START.match(lines[0]) or all(_SESSION.match(x) for x in lines):
            continue
        bpy = bool(BPY_IMPORT.search(src))
        got = None
        try:
            with warnings.catch_warnings():  # a SyntaxWarning ("'int' object is not subscriptable") is no fault
                warnings.simplefilter("ignore")
                ast.parse(src, "block")
        except SyntaxError as e:
            got = (e.lineno or 0, e.msg or type(e).__name__, None)
        except (ValueError, RecursionError, MemoryError, OverflowError) as e:
            got = (0, f"{type(e).__name__}: {e}", None)
        if got is None and bpy:
            older = older_fstring(src)
            if older:
                got = (older[0], OLDER_FSTRING[older[1]], older[1])
        if got:
            line = src.split("\n")[got[0] - 1].strip() if 0 < got[0] <= src.count("\n") + 1 else ""
            out.append({"block": k, "line": got[0], "error": got[1], "source": line, "older": got[2], "bpy": bpy})
    return out


def code_tell(fault):
    """code_syntax's line for the first of code_faults'."""
    return CODE_TELL.format(line=fault["line"], quote=_quotes([fault["source"]]) if fault["source"] else "no code",
                            error=fault["error"][:CODE_ERROR_CHARS])


def _delimiter(start):
    """An f-string's quote from its FSTRING_START token ('rf"""' gives '"""')."""
    q = start.lstrip("rRbBuUfF")
    return q[:3] if q[:3] in ('"""', "'''") else q[:1]


def _reused(inner, quote):
    """Whether an f-string's text between its quotes holds its own quote unescaped, as Python 3.11's tokenizer scans
    a string for its end."""
    k = 0
    while k < len(inner):
        if inner[k] == "\\":
            k += 2
        elif inner.startswith(quote, k):
            return True
        else:
            k += 1
    return False


def older_fstring(src):
    """(line, kind) of the first f-string of src, a nested one included, that only Python 3.12's grammar reads (PEP
    701), or None: its own quote reused inside it ("quote"), a backslash in a field ("backslash", a nested
    f-string's own text there and a line continuation included), a comment in a field ("hash"), or a line break in a
    field of an f-string in single quotes ("break"). A # inside a string in a field is fine in 3.11, and so are an
    escaped quote and a backslash-newline in the f-string's own text. Read with the tokenizer's FSTRING tokens, so
    None on a Python before 3.12 (whose own compile() refuses these already) and for code that doesn't tokenize.
    Measured equal to Blender 5.0.1's own compile() on the stored records' and the eval's 2,028 distinct python
    blocks and on hand-made cases of each form (the checks of Nov 6 added the nested ones and the continuation: 48 of
    50 cases, all but the two type-parameter forms)."""
    if sys.version_info < (3, 12):
        return None
    lines = src.split("\n")

    def text(a, b):
        (l1, c1), (l2, c2) = a, b
        if l1 == l2:
            return lines[l1 - 1][c1:c2]
        return "\n".join([lines[l1 - 1][c1:]] + lines[l1:l2 - 1] + [lines[l2 - 1][:c2]])
    stack = []  # the open f-strings: [quote, fields open, start]
    prev = None  # the end of the token before
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if stack and stack[-1][1] > 0 and prev:  # in a field: a line continuation there is no token
                gap = text(prev, tok.start)
                if "\\" in gap:
                    return tok.start[0] - gap.count("\n"), "backslash"
            prev = tok.end
            if tok.type == tokenize.FSTRING_START:
                stack.append([_delimiter(tok.string), 0, tok.start])
                continue
            if not stack:
                continue
            top = stack[-1]
            if tok.type == tokenize.FSTRING_END:
                # each f-string, a nested one too, with its own quote: its text as 3.11's tokenizer would scan it,
                # the outermost's in the code, a nested one's in the field 3.11 reads it from (the checks of Nov 6:
                # f"{f'{d['k']}'}" passed, which 5.0.1 refuses)
                quote, _, start = stack.pop()
                raw = text(start, tok.end)
                inner = raw[raw.index(quote) + len(quote):len(raw) - len(quote)]
                if _reused(inner, quote):
                    return start[0], "quote"
                if len(quote) == 1 and any(not inner[:k].endswith("\\") for k, ch in enumerate(inner)
                                           if ch == "\n"):
                    return start[0], "break"
            elif tok.type == tokenize.FSTRING_MIDDLE:
                if len(stack) > 1 and "\\" in tok.string:  # a nested f-string's own text, in an outer field
                    return tok.start[0], "backslash"
            elif tok.type == tokenize.OP and tok.string in "{}":
                top[1] += 1 if tok.string == "{" else -1
            elif top[1] > 0:
                if tok.type == tokenize.COMMENT:
                    return tok.start[0], "hash"
                if "\\" in tok.string:
                    return tok.start[0], "backslash"
    except (tokenize.TokenError, SyntaxError):
        return None
    return None


def _quotes(phrases):
    return ", ".join('"' + (p if len(p) <= QUOTE_CHARS else p[:QUOTE_CHARS - 1] + "…") + '"'
                     for p in phrases[:QUOTES_KEEP])


def _section_text(text, verdict):
    if verdict:
        return verdict.get("section") or verdict.get("body") or ""
    return cv.strip_handoff(text or "")


def section_check(plan, i, text, verdict, earlier_sections, dep_texts=(), missing_deps=(), prev_result="") -> dict:
    """The deterministic checks on candidate text for section step i of plan (cleaned). verdict: the Go validator's
    for it (when None, contract.validate's prototype stands in). earlier_sections: {sid: text} of the kept pieces of
    earlier section steps. dep_texts: the kept pieces of the step's dependencies ({sid: text or None}, as task.py
    builds them for the prose judge); missing_deps: the ids of those that failed; prev_result: the previous round's
    result as the step's request gives it ("" in round 1). They only say what the step was given (given_material), so
    that a claim restating it isn't counted; a dependency they don't hold counts as missing. Returns {"ok",
    "reasons" (each of FAIL_WARNINGS found, placeholder, claims_source, step_id_leak, csv_fields, code_syntax,
    words_under, words_over, intro, outro, overlap:<sid>), "words", "target" (word_target's, or None),
    "overlap" ({sid: share}), "framing" (the intro or outro phrases found), "warnings" (every validator warning's
    code), "heading" (its heading line's text), "bare_heading" (the validator warned heading_not_title, but
    heading_fits), "claims" (source_claims'), "claims_given" (the claims its given material holds, not counted),
    "step_ids" (step_mentions'), "csv" (csv_fault's), "code" (code_faults': since the fifth smoke a python block
    that doesn't compile fails the section, code_syntax), "tell" (a line for the next try's notes for each of
    claims_source, step_id_leak, csv_fields and code_syntax, a research step's claims with CLAIMS_TELL_RESEARCH; empty
    when it passed)}. Where the validator didn't warn, a heading still fails heading_not_title when its key is empty
    or it neither fits the step nor is a whole phrase of its instructions."""
    steps = plan.get("steps") or []
    step = steps[i]
    sid = f"s{i + 1}"
    if verdict is None:
        p = cv.validate_piece(text, "section", sid=sid, lone=len(steps) == 1, step=step, reject_cut=False,
                              max_tokens=None)
        verdict = {"mode": "section", "issues": [x.to_dict() for x in p.issues], "section": p.section or "",
                   "body": p.body}
    reasons = []
    if verdict.get("mode") not in (None, "section"):
        reasons.append("not_section")
    warnings = [x.get("code") for x in verdict.get("issues") or []]
    section = _section_text(text, verdict)
    heading = re.sub(r"^#+\s*", "", section.split("\n", 1)[0]).strip() if section.startswith("#") else ""
    fits = heading_fits(heading, step)
    bare = "heading_not_title" in warnings and fits
    if "heading_not_title" in warnings:
        bad_heading = not fits
    else:  # Go's substring test passes "", "***" and part of a word
        bad_heading = section.startswith("#") and (not _key(heading) or not (
            fits or _whole_phrase(heading, step.get("instructions") or "")))
    for code in FAIL_WARNINGS:
        if code not in reasons and (bad_heading if code == "heading_not_title" else code in warnings):
            reasons.append(code)
    if "placeholder" not in reasons and _PLACEHOLDER.search("\n".join(prose_lines(section))):
        reasons.append("placeholder")
    tell = []
    claim_why = {}
    claims, claims_given = _claims(section, _given_blocks(plan, i, dep_texts, missing_deps, prev_result),
                                   _labels(plan, i), claim_why)
    if claims:
        reasons.append("claims_source")
        how = CLAIMS_TELL_RESEARCH if step.get("kind") == "research" else CLAIMS_TELL  # contract/prompt.mode_rules
        for kind, line in (("plain", how), ("mark", CLAIMS_TELL_MARK), ("cite", CLAIMS_TELL_CITE)):
            these = [p for p in claims if claim_why.get(p, "plain") == kind]
            if these:
                tell.append(line.format(quotes=_quotes(these)))
    ids = step_mentions(plan, section)
    if ids:
        reasons.append("step_id_leak")
        tell.append(STEP_ID_TELL.format(quotes=_quotes(ids)))
    bad_csv = csv_fault(section)
    if bad_csv:
        reasons.append("csv_fields")
        tell.append(CSV_TELL.format(**bad_csv))
    bad_code = code_faults(section)
    if bad_code:
        reasons.append("code_syntax")
        tell.append(code_tell(bad_code[0]))

    ws = words(section)
    target = step_target(step)
    if target:
        if len(ws) < target["low"]:
            reasons.append("words_under")
        elif target["high"] is not None and len(ws) > target["high"]:
            reasons.append("words_over")

    framing = []
    checks = [(why, {"intro": _INTRO, "outro": _OUTRO}[why]) for why in framing_checks(plan, i)]
    if checks:
        paras = paragraphs(section)
        ends = paras[:1] + paras[1:][-1:]  # the first and the last
        for why, rx in checks:
            for p in ends:
                m = rx.search(p) or (why == "outro" and _WHOLE.search(p) and _WEAK_OUTRO.search(p))
                if m:
                    framing.append(m.group(0))
                    if why not in reasons:
                        reasons.append(why)

    mine = shingles(ws)
    overlap = {}
    for other_sid, other in sorted((earlier_sections or {}).items()):
        if other_sid == sid or not other:
            continue
        theirs = shingles(words(cv.strip_handoff(other)))
        share = len(mine & theirs) / len(mine) if mine else 0.0
        overlap[other_sid] = round(share, 3)
        if share > OVERLAP_MAX:
            reasons.append("overlap:" + other_sid)
    return {"ok": not reasons, "reasons": reasons, "words": len(ws), "target": target, "overlap": overlap,
            "framing": framing, "warnings": warnings, "heading": heading, "bare_heading": bare, "claims": claims,
            "claims_given": claims_given, "claims_why": {p: claim_why.get(p, "plain") for p in claims}, "step_ids": ids,
            "csv": bad_csv, "code": bad_code, "tell": tell}
