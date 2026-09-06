"""The gates. Pure arithmetic over strings and dicts, so these tests need no fixtures
beyond the strings themselves.

This is the largest test module in the project on purpose. The gates are the only thing
standing between a confidently wrong model and a published manuscript, and every one of
them is cheap enough to test exhaustively.
"""

import support                                                      # noqa: F401
import unittest                                                     # noqa: E402

from paperwriter import config                                      # noqa: E402
from paperwriter.gates import (citations, claims, coverage, ladder,  # noqa: E402
                               length, numbers, paragraphs, prose,
                               readability, sentences, structure,
                               terminology, venue)


class ProseSplittingTests(unittest.TestCase):
    """Everything else counts what this module splits, so it has to be right."""

    def test_abbreviations_do_not_end_a_sentence(self):
        text = ("Smith et al. reported a similar gap. We used pandas vs. polars for "
                "the join. See Fig. 3 for the curve.")
        self.assertEqual(len(prose.sentences(text)), 3)

    def test_initials_do_not_end_a_sentence(self):
        self.assertEqual(len(prose.sentences("J. R. Smith ran the analysis. It held.")),
                         2)

    def test_decimals_do_not_end_a_sentence(self):
        self.assertEqual(len(prose.sentences("The AUC was 0.74 on the split. It held.")),
                         2)

    def test_a_sentence_ending_in_a_decimal_still_ends(self):
        """A results section reports figures at the ends of sentences. Gluing those to
        the sentence after is how such a section measures as long, welded prose when it
        is nothing of the kind."""
        self.assertEqual(
            prose.sentences("The range runs to 0.657. Discrimination is modest."),
            ["The range runs to 0.657.", "Discrimination is modest."])

    def test_a_bare_integer_and_a_stop_is_still_a_list_marker(self):
        self.assertEqual(len(prose.sentences("1. First item here. 2. Second one.")), 2)

    def test_headings_and_tables_are_not_prose(self):
        text = "# Results\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nThe model did better."
        self.assertEqual(prose.sentences(text), ["The model did better."])

    def test_a_list_item_starts_a_new_sentence(self):
        """A bulleted list is the standard repair for a sentence carrying six things,
        and its stem ends in a colon. Without this boundary the stem and every bullet
        merge into one enormous sentence, so the gate reports the repair as worse than
        the defect it fixes."""
        text = "A patient needed all three of:\n\n- one thing;\n- two thing;\n- three.\n"
        found = prose.sentences(text)
        self.assertEqual(len(found), 4, found)
        self.assertEqual(found[0], "A patient needed all three of:")

    def test_a_caption_ending_in_emphasis_still_closes(self):
        """A figure or table caption is written `***Table 3.** ... *` and ends in `.*`.
        Without emphasis as a closer the caption never terminates and swallows the
        paragraph beneath it, which on a supplement is most of the apparent long
        sentences."""
        text = "***Table 3.** The counts by group.*\n\nThe model did better here.\n"
        self.assertEqual(prose.sentences(text),
                         ["***Table 3.** The counts by group.*",
                          "The model did better here."])

    def test_a_cross_reference_ends_its_sentence(self):
        """"Table 2." at the end of a sentence is a reference, not a list marker.
        Reading it as a marker glued the sentence to the next one, so a paragraph of
        three ordinary sentences measured as one run-on and the long-sentence share
        was driven by the paper's own cross-references."""
        text = ("The values are tabulated in Table 2. A paired bootstrap followed. "
                "The ablation is Figure 9. It reproduced across encoders.")
        self.assertEqual(len(prose.sentences(text)), 4)

    def test_a_bare_numeral_is_still_a_list_marker(self):
        text = "A patient needed all of:\n\n1. one thing.\n2. another thing.\n"
        self.assertEqual(len(prose.sentences(text)), 3)

    def test_a_display_equation_is_not_prose(self):
        """Counting one produces a paragraph with no topic sentence on every
        derivation, and a sentence made of LaTeX.

        The stem and its continuation stay one sentence, which is correct: "The
        estimator is: [equation] where a is the sum" is one sentence in mathematical
        writing, and the equation is simply not words."""
        text = "The estimator is:\n\n$$\\hat{P} = \\frac{a}{b},$$\n\nwhere a is the sum.\n"
        self.assertEqual(prose.sentences(text), ["The estimator is: where a is the sum."])
        self.assertNotIn("frac", prose.strip_structure(text))

    def test_an_image_line_is_not_prose(self):
        """A results path is not a dozen words of writing."""
        text = "Before it.\n\n![](../results/a/very/long/path/to/figure_name.png)\n\nAfter."
        self.assertEqual(prose.sentences(text), ["Before it.", "After."])

    def test_a_blockquote_is_not_the_author_s_prose(self):
        """Quoted material — a verbatim model output, a reviewer's comment, an example
        narrative. The author cannot repair a sentence they did not write, and a
        supplement quoting a 170-word generated narrative would otherwise measure as
        though it contained a 170-word sentence."""
        text = "The example follows.\n\n> A very long quoted line goes here.\n\nIt ends."
        self.assertEqual(prose.sentences(text),
                         ["The example follows.", "It ends."])

    def test_fenced_code_is_not_prose(self):
        text = "Before it.\n\n```\nx = 1. y = 2. z = 3.\n```\n\nAfter it."
        self.assertEqual(len(prose.sentences(text)), 2)

    def test_a_hard_wrapped_sentence_is_one_sentence(self):
        text = "The embedded\nrepresentation did\nbetter than the other one."
        self.assertEqual(len(prose.sentences(text)), 1)

    def test_the_anchor_keeps_the_line_breaks(self):
        """A repair anchor is matched character for character against the draft, so a
        tidied sentence is an anchor that silently never applies."""
        text = "The embedded\nrepresentation did better."
        spans = prose.sentence_spans(text)
        self.assertEqual(spans[0][2], text)
        self.assertEqual(spans[0][3], "The embedded representation did better.")

    def test_list_items_are_separate_paragraphs(self):
        text = "Intro line.\n\n- first item\n- second item\n\nOutro line."
        self.assertEqual(len(prose.paragraphs(text)), 4)

    def test_collapse_pattern_crosses_a_line_break(self):
        pattern = prose.collapse_pattern("treatment-resistant depression")
        self.assertTrue(pattern.search("we studied treatment-resistant\ndepression here"))

    def test_collapse_pattern_will_not_match_inside_a_word(self):
        self.assertIsNone(prose.collapse_pattern("rule-based").search("non-rule-based"))

    def test_stripping_structure_preserves_every_offset(self):
        """Blanked, not deleted. An anchor drawn from stripped text has to be a
        substring of the original, or the repair it belongs to never applies."""
        text = "# Results\n\n| a | b |\n\nThe model did better.\n"
        stripped = prose.strip_structure(text)
        self.assertEqual(len(stripped), len(text))
        at = stripped.index("The model")
        self.assertEqual(text[at:at + 21], "The model did better.")

    def test_a_heading_does_not_join_the_paragraph_below_it(self):
        """A heading carries no terminator. Delete the line and it glues onto the
        first sentence beneath it — which on a real manuscript produced one 133-word
        sentence that was a title block plus everything after it."""
        text = "# Title page\n\nThe first real sentence. And a second one.\n"
        found = prose.sentences(text)
        self.assertEqual(found, ["The first real sentence.", "And a second one."])


class SentenceGateTests(unittest.TestCase):
    """The one-read rule, measured."""

    LONG = ("The embedded representation, which was produced by a pretrained encoder "
            "applied to the narrative sections of each record and then pooled across "
            "the whole of the encounter window rather than a fixed lookback, "
            "discriminated the outcome more sharply than the typed feature vector "
            "did, although the difference was smaller in the youngest subgroup and "
            "may possibly reflect sampling rather than any real signal.")

    def test_a_long_welded_sentence_fails(self):
        report = sentences.score(self.LONG)
        self.assertFalse(report.passed)
        self.assertTrue(any("35 words" in r for r in report.reasons))

    def test_the_hard_ceiling_fires_on_one_sentence(self):
        report = sentences.score(self.LONG)
        self.assertEqual(len(report.over_hard_max), 1)

    def test_stacked_hedges_are_counted(self):
        report = sentences.score(self.LONG)
        self.assertEqual(len(report.stacked_hedges), 1)

    def test_a_list_semicolon_is_punctuation_not_a_weld(self):
        """Semicolons end the items of an enumeration by convention. Counting them
        pushes a writer away from the list that fixes a long sentence."""
        text = ("The domains were three:\n\n- depression severity;\n"
                "- psychiatric comorbidity;\n- health-care utilisation.\n")
        self.assertEqual(sentences.score(text).semicolons_per_kword, 0.0)

    def test_semicolons_are_rationed(self):
        text = " ".join(["The model did better; the gap was small."] * 6)
        report = sentences.score(text)
        self.assertFalse(report.passed)
        self.assertTrue(any("semicolon" in r for r in report.reasons))

    def test_a_numeric_range_is_not_a_dash_weld(self):
        """A dash between two numbers is a range, not a second claim. Counting
        confidence intervals as welds measured the density of the results rather
        than of the prose, and no amount of rewriting could bring a Results
        section under the ration."""
        text = ("Discrimination reached 0.657 (95% CI 0.643-0.672) against 0.649 "
                "(0.634-0.664). The band spanned 0.645-0.657 across encoders. "
                "Index dates spanned 2016-2024 and the deltas ran -0.024 to -0.028.")
        text = text.replace("-0.672", "\u20130.672").replace("-0.664", "\u20130.664")
        text = text.replace("0.645-0.657", "0.645\u20130.657")
        text = text.replace("2016-2024", "2016\u20132024")
        report = sentences.score(text)
        self.assertEqual(report.emdashes_per_kword, 0.0)
        self.assertEqual(report.welded, [])

    def test_a_clause_joining_dash_is_still_a_weld(self):
        """The ration exists for asides. Excluding ranges must not excuse those."""
        text = " ".join(["The gap held \u2014 nobody expected that \u2014 across sites."] * 5)
        report = sentences.score(text)
        self.assertGreater(report.emdashes_per_kword, 2)
        self.assertFalse(report.passed)
        self.assertTrue(any("em-dash" in r for r in report.reasons))

    def test_a_tight_compound_dash_is_not_a_weld(self):
        """"precision\u2013recall" and "nearest\u2013farthest" are single terms made of two
        coordinate words. Counting them asked the writer to rename the analysis."""
        text = " ".join(["A nearest\u2013farthest fusion improved the precision\u2013recall "
                         "curve for every anchor\u2013neighbor pair we drew."] * 5)
        report = sentences.score(text)
        self.assertEqual(report.emdashes_per_kword, 0.0)

    def test_a_spaced_en_dash_is_still_a_weld(self):
        """Spacing is what separates the aside from the compound, and the aside is
        the whole reason the ration exists."""
        text = " ".join(["The gap held \u2013 nobody expected that \u2013 across sites."] * 5)
        self.assertGreater(sentences.score(text).emdashes_per_kword, 2)

    def test_empty_openers_are_named(self):
        text = ("It is worth noting that the gap was small. The cohort held. "
                "Importantly, the split was redrawn once. Nothing else moved.")
        report = sentences.score(text)
        phrases = {p for _s, p in report.empty_openers}
        self.assertEqual(phrases, {"it is worth noting", "importantly"})

    def test_uniform_length_fails_even_when_every_sentence_is_fine(self):
        """The one gate that fires on prose which is individually correct. Every
        sentence the same length is the loudest tell that nobody read it aloud."""
        text = " ".join(["The cohort held its shape across every one of the splits."]
                        * 8)
        report = sentences.score(text)
        self.assertFalse(report.passed)
        self.assertTrue(any("nearly the same length" in r for r in report.reasons))

    def test_good_prose_passes(self):
        self.assertTrue(sentences.score(support.CLEAN_PROSE).passed,
                        sentences.score(support.CLEAN_PROSE).reasons)

    def test_worst_offenders_are_ranked_by_how_badly_they_break_the_rule(self):
        text = (self.LONG + " " + "A short one. "
                + "This sentence runs on for a while and lists covariates such as age "
                  "and sex and site and year and season and payer and region and "
                  "index month without doing anything else at all with them.")
        worst = sentences.worst_offenders(sentences.score(text), count=2)
        self.assertIn(self.LONG, worst[0])

    def test_an_empty_section_fails_rather_than_scoring_zero(self):
        self.assertFalse(sentences.score("").passed)


class ParagraphGateTests(unittest.TestCase):

    def test_a_paragraph_opening_on_a_citation_has_no_topic_sentence(self):
        text = ("[12] reported a similar gap in a comparable cohort. Our estimate was "
                "close to theirs. The difference was not material.")
        report = paragraphs.check(text)
        self.assertIn("no topic sentence", {d.kind for d in report.defects})

    def test_a_paragraph_opening_on_a_number_has_no_topic_sentence(self):
        text = ("42579 patients entered the extract before filtering. Most of the loss "
                "came from the diagnosis window. The rest was missing data.")
        self.assertIn("no topic sentence",
                      {d.kind for d in paragraphs.check(text).defects})

    def test_a_hinge_opener_is_a_continuation(self):
        text = ("However, the gap narrowed in the youngest group. The interval was "
                "wide. Nothing about it changes the headline.")
        self.assertIn("hinge opener", {d.kind for d in paragraphs.check(text).defects})

    def test_a_buried_claim_is_flagged(self):
        text = ("Because the cohort was assembled retrospectively from a single health "
                "system, the estimate may not transfer. The case mix differs. That "
                "limits what it settles.")
        self.assertIn("buried claim", {d.kind for d in paragraphs.check(text).defects})

    def test_a_short_subordinate_opener_is_not_a_buried_claim(self):
        text = ("If so, the estimate is biased downward. The direction is known. The "
                "size is not.")
        self.assertNotIn("buried claim",
                         {d.kind for d in paragraphs.check(text).defects})

    def test_a_one_sentence_paragraph_is_too_short(self):
        self.assertIn("too short",
                      {d.kind for d in paragraphs.check("The model did better.").defects})

    def test_the_gate_blocks_on_a_share_not_on_one_defect(self):
        """A single mis-shaped paragraph in a long section is not a failing section.
        A gate that fires on every section is a gate nobody reads."""
        good = support.CLEAN_PROSE
        text = good + "\n\nHowever, one paragraph opens badly.\n\n" + good
        report = paragraphs.check(text)
        self.assertTrue(report.defects)
        self.assertTrue(report.passed, report.reasons)

    def test_a_list_stem_is_not_a_paragraph(self):
        """A block ending in a colon points at what comes next; its support is the
        list beneath it. Judging it as an unsupported paragraph would make the gate
        call the repair for a long sentence a defect."""
        text = "The domains were three:\n\n- one;\n- two;\n- three.\n"
        report = paragraphs.check(text)
        self.assertEqual(report.checked, 0)
        self.assertTrue(report.passed)

    def test_a_caption_is_not_a_paragraph(self):
        """A caption has no topic sentence and no concluding sentence by design, and is
        routinely one or two sentences. Judging it against paragraph shape produces a
        defect on every figure in a supplement."""
        text = "***Table S3.** Counts by group. Lower is better.*\n"
        self.assertEqual(paragraphs.check(text).checked, 0)
        self.assertEqual(paragraphs.check("**(A) Nearest retrieval**\n").checked, 0)

    def test_a_caption_s_sentences_are_still_measured(self):
        """Only shape is exempt. A caption a reader cannot parse is a real defect."""
        long_caption = "***Table 1.** " + " ".join(["word"] * 60) + ".*"
        self.assertFalse(sentences.score(long_caption).passed)

    def test_exempt_sections_are_not_checked(self):
        report = paragraphs.check("One sentence only.", section_name="Abstract")
        self.assertTrue(report.passed)
        self.assertEqual(report.checked, 0)

    def test_list_items_are_exempt(self):
        text = "- first bullet\n- second bullet\n- third bullet"
        report = paragraphs.check(text)
        self.assertEqual(report.checked, 0)

    def test_good_prose_passes(self):
        self.assertTrue(paragraphs.check(support.CLEAN_PROSE).passed)


class NumberGateTests(unittest.TestCase):

    EVIDENCE = {"items": [
        {"id": "e.1", "statement": "AUC", "values": [0.7429]},
        {"id": "e.2", "statement": "n", "values": [8516]},
    ]}

    def test_a_number_in_the_ledger_passes(self):
        self.assertTrue(numbers.check("The AUC was 0.7429 here.", self.EVIDENCE).passed)

    def test_a_rounded_restatement_is_the_same_number(self):
        self.assertTrue(numbers.check("The AUC was 0.74 here.", self.EVIDENCE).passed)

    def test_a_plausible_wrong_number_is_caught(self):
        """The failure this gate exists for. 0.75 is not 0.7429 and no amount of
        fluency makes it one."""
        report = numbers.check("The AUC was 0.75 here.", self.EVIDENCE)
        self.assertFalse(report.passed)
        self.assertEqual([u.raw for u in report.unsupported], ["0.75"])

    def test_a_percentage_matches_its_proportion(self):
        self.assertTrue(numbers.check("Accuracy reached 74.29%.", self.EVIDENCE).passed)

    def test_a_thousands_separator_is_the_same_number(self):
        self.assertTrue(numbers.check("We analysed 8,516 records.",
                                      self.EVIDENCE).passed)

    def test_years_are_not_findings(self):
        self.assertTrue(numbers.check("The extract covers 2019 to 2024.",
                                      self.EVIDENCE).passed)

    def test_structural_references_are_not_findings(self):
        self.assertTrue(numbers.check("See Table 3 and Figure 7 for the curves.",
                                      self.EVIDENCE).passed)

    def test_citation_markers_are_not_findings(self):
        self.assertTrue(numbers.check("A prior study found the same [27].",
                                      self.EVIDENCE).passed)

    def test_an_empty_ledger_disables_the_gate(self):
        """A first draft written before the evidence stage has run must not be
        rejected for every figure in it."""
        self.assertTrue(numbers.check("The AUC was 0.99.", {"items": []}).passed)

    def test_also_allow_exempts_a_quotable_non_finding(self):
        evidence = dict(self.EVIDENCE, also_allow=[32])
        self.assertTrue(numbers.check("We used 32 quantile bins.", evidence).passed)

    def test_rounding_is_judged_at_the_precision_the_prose_used(self):
        """A flat relative tolerance gets small effect sizes wrong in the direction
        that matters: 0.74 against 0.7429 passes while 0.008 against 0.007939 fails,
        because the same rounding is a larger fraction of a smaller number. Every
        legitimately rounded effect size in a manuscript is small."""
        evidence = {"items": [{"id": "e.1", "statement": "delta",
                               "values": [0.007939069768552076]}]}
        self.assertTrue(numbers.check("The gap was +0.008.", evidence).passed)
        self.assertFalse(numbers.check("The gap was +0.009.", evidence).passed)

    def test_a_sentence_final_number_is_checked(self):
        """It was not, for a while, and nothing said so. The trailing lookahead
        rejected a match followed by a full stop, so every figure that ended a
        sentence went unchecked — and the gate reported the section clean."""
        report = numbers.check("Discrimination reached 0.9999.", self.EVIDENCE)
        self.assertFalse(report.passed)
        self.assertEqual([u.raw for u in report.unsupported], ["0.9999"])

    def test_the_closing_bound_of_an_interval_is_checked(self):
        """Same lookahead, same silence: a number followed by ")" was skipped, so the
        upper bound of every confidence interval in the manuscript went unread."""
        report = numbers.check("AUC 0.7429 (95% CI 0.7100-0.9999).", self.EVIDENCE)
        self.assertIn("0.9999", [u.raw for u in report.unsupported])

    def test_a_version_string_is_still_not_a_finding(self):
        self.assertTrue(numbers.check("We used version 1.2.3 of it.",
                                      self.EVIDENCE).passed)

    def test_clinical_codes_are_not_findings(self):
        """A Methods section lists dozens of ICD codes and not one is a measurement.
        The keyword sits several words back from most of them, so adjacency is the
        wrong test."""
        text = ("Depression comprised ICD-9 codes 296.2, 296.3, 300.4, and 311 or "
                "ICD-10 codes F32 and F33.")
        report = numbers.check(text, self.EVIDENCE)
        self.assertTrue(report.passed, [u.raw for u in report.unsupported])

    def test_a_finding_after_a_code_list_is_still_checked(self):
        """The exemption stops at the sentence boundary, or a results sentence
        following a Methods sentence would inherit it."""
        text = ("Depression comprised ICD-9 codes 296.2 and 311. Discrimination "
                "reached 0.9999.")
        self.assertFalse(numbers.check(text, self.EVIDENCE).passed)

    def test_an_orcid_is_not_a_finding(self):
        text = "Mikey Ferguson 0009-0005-1365-5609 wrote this sentence down."
        self.assertTrue(numbers.check(text, self.EVIDENCE).passed,
                        [u.raw for u in numbers.check(text, self.EVIDENCE).unsupported])

    def test_numbers_in_a_heading_or_a_comment_are_not_findings(self):
        text = ("# Table 4 results for 9999 patients\n\n"
                "<!-- TRIPOD+AI item 7777 -->\n\n"
                "The AUC was 0.7429 on the split.\n")
        self.assertTrue(numbers.check(text, self.EVIDENCE).passed,
                        [u.raw for u in numbers.check(text, self.EVIDENCE).unsupported])

    def test_the_anchor_is_the_sentence_verbatim(self):
        text = "The cohort held.\nThe AUC was\n0.75 on the split.\n"
        report = numbers.check(text, self.EVIDENCE)
        anchor = report.unsupported[0].sentence
        self.assertEqual(text.count(anchor), 1)
        self.assertIn("\n", anchor)


class TerminologyGateTests(unittest.TestCase):

    LOCK = [
        {"term": "feature representation",
         "aliases": ["rule-based approach", "rule-based"]},
        {"term": "TRD", "first_use": "treatment-resistant depression"},
    ]

    def test_a_forbidden_alias_is_a_violation(self):
        report = terminology.check("The rule-based approach did worse.", self.LOCK)
        self.assertFalse(report.passed)
        self.assertEqual(report.defects[0].kind, "alias")

    def test_nested_aliases_are_reported_once(self):
        """A lock forbidding both 'rule-based' and 'rule-based approach' must not ask
        for two repairs on one span — the second could never apply."""
        report = terminology.check("The rule-based approach did worse.", self.LOCK)
        self.assertEqual(len(report.defects), 1)

    def test_an_alias_inside_a_quotation_is_allowed(self):
        report = terminology.check('The reviewer wrote "the rule-based approach is '
                                   'unclear" in their note.', self.LOCK)
        self.assertTrue(report.passed)

    def test_an_undefined_abbreviation_is_caught(self):
        report = terminology.check_manuscript("Patients with TRD were included.",
                                              self.LOCK)
        self.assertIn("undefined-abbreviation", {d.kind for d in report.defects})

    def test_an_expansion_across_a_line_break_still_counts(self):
        """Drafted prose arrives hard-wrapped. A gate that misses the expansion
        reports a defect the editor cannot repair, because nothing is wrong."""
        report = terminology.check_manuscript(
            "Patients with treatment-resistant\ndepression (TRD) were included.",
            self.LOCK)
        self.assertTrue(report.passed, [d.detail for d in report.defects])

    def test_expanding_twice_is_a_defect(self):
        report = terminology.check_manuscript(
            "Treatment-resistant depression (TRD) is common. We studied "
            "treatment-resistant depression again.", self.LOCK)
        self.assertIn("redefined", {d.kind for d in report.defects})

    def test_first_use_is_not_checked_at_section_scope(self):
        """Which section holds an abbreviation's first appearance cannot be known from
        inside one section. Demanding the expansion in every section is exactly the
        expanded-twice defect the same gate punishes, so the two rules contradict each
        other and a writer told to satisfy both oscillates."""
        section = "Patients with TRD were included in the analysis here."
        self.assertTrue(terminology.check(section, self.LOCK).passed)
        self.assertFalse(terminology.check_manuscript(section, self.LOCK).passed)

    def test_an_alias_still_blocks_at_section_scope(self):
        """A forbidden synonym is a defect wherever it appears."""
        self.assertFalse(
            terminology.check("The rule-based approach did worse.", self.LOCK).passed)

    def test_an_abbreviation_inside_its_own_term_is_not_an_alias(self):
        """The common case, not an edge case: an abbreviation is usually a substring of
        the term it abbreviates. A lock preferring "ROC AUC" over a bare "AUC" would
        otherwise flag every correct use, and the repair would replace "AUC" inside
        "ROC AUC" with "ROC AUC"."""
        lock = [{"term": "ROC AUC", "aliases": ["AUC", "AUROC"]}]
        self.assertTrue(terminology.check("Discrimination reached ROC AUC 0.65.",
                                          lock).passed)
        self.assertFalse(terminology.check("Discrimination reached AUC 0.65.",
                                           lock).passed)

    def test_an_abstract_may_expand_an_abbreviation_the_body_expands_again(self):
        """An abstract is read detached from its paper, so journals expect it to
        expand its own abbreviations and the body to expand them again. A first-use
        check spanning both reports every correctly written manuscript as having
        defined everything twice."""
        manuscript = (
            "# Abstract\n\nTreatment-resistant depression (TRD) is common.\n\n"
            "# Introduction\n\nTreatment-resistant depression (TRD) is common. "
            "TRD is the outcome here.\n")
        self.assertTrue(terminology.check_manuscript(manuscript, self.LOCK).passed,
                        [d.detail for d in
                         terminology.check_manuscript(manuscript, self.LOCK).defects])

    def test_expanding_twice_inside_the_body_is_still_a_defect(self):
        manuscript = ("# Introduction\n\nTreatment-resistant depression (TRD) is "
                      "common.\n\n# Discussion\n\nTreatment-resistant depression "
                      "recurs often.\n")
        self.assertFalse(terminology.check_manuscript(manuscript, self.LOCK).passed)

    def test_an_alias_in_the_abstract_is_still_a_defect(self):
        """Aliases are checked everywhere. A forbidden synonym in an abstract is a
        defect in the part of the paper most people read."""
        manuscript = "# Abstract\n\nThe rule-based approach did worse.\n"
        self.assertFalse(terminology.check_manuscript(manuscript, self.LOCK).passed)

    def test_an_empty_lock_disables_the_gate(self):
        self.assertTrue(terminology.check("Anything at all.", []).passed)


class CitationGateTests(unittest.TestCase):

    def test_an_unresolved_marker_fails(self):
        report = citations.check("A prior study found this [27].", {"1": {}, "2": {}})
        self.assertFalse(report.passed)
        self.assertEqual(report.unresolved, ["27"])

    def test_a_numeric_range_expands(self):
        keys, _styles = citations.keys_used("Several studies agree [3-5].")
        self.assertEqual(keys, {"3", "4", "5"})

    def test_an_interval_is_not_a_citation(self):
        """Reference numbering starts at 1, so `[0, 1]` is the unit interval. Any paper
        that mentions a probability writes it, and reading it as a citation invents an
        unresolved reference 0."""
        keys, _styles = citations.keys_used("α was chosen from a grid on [0, 1].")
        self.assertEqual(keys, set())
        self.assertTrue(citations.check("a value in [0, 1] here.", {"1": {}}).passed)

    def test_a_borrowed_claim_with_no_source_is_flagged(self):
        report = citations.check("Prior studies have shown the same pattern.", {})
        self.assertEqual(len(report.missing), 1)

    def test_a_claim_about_this_paper_needs_no_source(self):
        report = citations.check("We found the same pattern in this study.", {})
        self.assertEqual(report.missing, [])

    def test_a_borrowed_claim_with_a_marker_is_fine(self):
        report = citations.check("Prior studies have shown the same pattern [1].",
                                 {"1": {}})
        self.assertEqual(report.missing, [])

    def test_mixing_two_styles_is_a_defect(self):
        report = citations.check("One source says so [1]. Another (Smith, 2024) "
                                 "disagrees.", {"1": {}})
        self.assertTrue(any("mixes" in r for r in report.reasons))

    def test_uncited_references_only_block_at_manuscript_level(self):
        """A reference cited only in the Discussion is not uncited when the Methods is
        being gated."""
        section = citations.check("Nothing cited here at all.", {"1": {}})
        self.assertEqual(section.uncited, [])
        whole = citations.check_manuscript("Nothing cited here at all.", {"1": {}})
        self.assertEqual(whole.uncited, ["1"])
        self.assertFalse(whole.passed)


class LengthGateTests(unittest.TestCase):

    def test_over_budget_blocks_and_says_to_cut_a_claim(self):
        report = length.check(1400, budget=1000)
        self.assertFalse(report.passed)
        self.assertIn("Cut, do not compress", report.reason)

    def test_under_budget_blocks_and_says_to_support_a_claim(self):
        report = length.check(400, budget=1000)
        self.assertFalse(report.passed)
        self.assertIn("dropped a claim", report.reason)

    def test_inside_the_band_passes(self):
        for words in (620, 1000, 1140):
            self.assertTrue(length.check(words, budget=1000).passed, words)

    def test_with_no_budget_only_the_absolute_floor_applies(self):
        self.assertTrue(length.check(100_000).passed)
        self.assertFalse(length.check(10).passed)


class ReadabilityGateTests(unittest.TestCase):

    def test_syllable_counting_handles_the_silent_e(self):
        self.assertEqual(readability.count_syllables("make"), 1)
        self.assertEqual(readability.count_syllables("table"), 2)

    def test_an_empty_draft_fails(self):
        self.assertFalse(readability.score("").passed)

    def test_academic_prose_sits_in_the_band(self):
        report = readability.score(support.CLEAN_PROSE)
        self.assertGreaterEqual(report.fk_grade, 0)
        self.assertEqual(report.words, len(prose.words(support.CLEAN_PROSE)))


class CoverageGateTests(unittest.TestCase):

    EVIDENCE = {"items": [
        {"id": "e.1", "statement": "held-out AUC was 0.7429", "source": "x"},
        {"id": "e.2", "statement": "the cohort held 8516 patients", "source": "x"},
    ]}

    def test_declared_ids_are_the_exact_path(self):
        report = coverage.check(self.EVIDENCE,
                                [{"claim": "anything", "evidence": ["e.1"]}])
        self.assertTrue(report.passed)

    def test_a_declared_id_that_does_not_exist_is_uncovered(self):
        report = coverage.check(self.EVIDENCE,
                                [{"claim": "anything", "evidence": ["e.9"]}])
        self.assertFalse(report.passed)

    def test_naming_falls_back_to_identifying_words(self):
        """A claim need not quote the evidence: every identifying word appearing
        somewhere is enough. Demanding the claim's exact phrasing penalises evidence
        for using the abbreviation the paper itself locked."""
        report = coverage.check(self.EVIDENCE, ["patients in the cohort"])
        self.assertTrue(report.passed)

    def test_a_claim_about_nothing_in_the_evidence_is_uncovered(self):
        report = coverage.check(self.EVIDENCE, ["genotype interaction effects"])
        self.assertFalse(report.passed)
        self.assertEqual(report.missing, ["genotype interaction effects"])

    def test_no_claims_means_full_coverage(self):
        self.assertTrue(coverage.check(self.EVIDENCE, []).passed)


class ArgumentGateTests(unittest.TestCase):

    def _claims(self, **overrides):
        base = [
            {"id": "c.1", "claim": "text beats features", "kind": "comparative",
             "evidence": ["e.1"], "headline": True},
            {"id": "c.2", "claim": "the split is large enough", "kind": "descriptive",
             "evidence": ["e.2"]},
            {"id": "c.3", "claim": "discrimination is not benefit",
             "kind": "limitation", "evidence": ["e.1"]},
            {"id": "c.4", "claim": "a threshold must be chosen", "kind": "implication",
             "evidence": ["e.1"]},
        ]
        for cid, patch in overrides.items():
            for claim in base:
                if claim["id"] == cid.replace("_", "."):
                    claim.update(patch)
        return base

    IDS = {"e.1", "e.2"}

    def test_a_well_formed_map_passes(self):
        report = claims.check(self._claims(), evidence_ids=self.IDS)
        self.assertTrue(report.passed, report.errors)

    def test_a_claim_with_no_evidence_is_refused(self):
        report = claims.check(self._claims(c_2={"evidence": []}),
                              evidence_ids=self.IDS)
        self.assertFalse(report.passed)
        self.assertTrue(any("rests on no evidence" in e for e in report.errors))

    def test_two_headline_claims_is_two_papers(self):
        report = claims.check(self._claims(c_2={"headline": True}),
                              evidence_ids=self.IDS)
        self.assertFalse(report.passed)
        self.assertTrue(any("headline" in e for e in report.errors))

    def test_no_headline_claim_is_refused(self):
        report = claims.check(self._claims(c_1={"headline": False}),
                              evidence_ids=self.IDS)
        self.assertFalse(report.passed)

    def test_a_map_with_no_limitation_is_refused(self):
        report = claims.check(self._claims(c_3={"kind": "descriptive"}),
                              evidence_ids=self.IDS)
        self.assertFalse(report.passed)
        self.assertTrue(any("limitation" in e for e in report.errors))

    def test_the_same_claim_twice_is_refused(self):
        doubled = self._claims() + [
            {"id": "c.5", "claim": "the text beats the features", "kind": "comparative",
             "evidence": ["e.1"]}]
        report = claims.check(doubled, evidence_ids=self.IDS)
        self.assertFalse(report.passed)
        self.assertTrue(any("say the same thing" in e for e in report.errors))

    def test_unused_evidence_is_a_warning_not_a_failure(self):
        report = claims.check(self._claims(), evidence_ids={"e.1", "e.2", "e.9"})
        self.assertTrue(report.passed)
        self.assertTrue(any("e.9" in w for w in report.warnings))


class VenueGateTests(unittest.TestCase):
    """The journal's own rules. Every other gate asks whether the manuscript is good;
    this one asks whether the file will be accepted, which an editorial assistant
    settles in ninety seconds and which no other gate here can see."""

    GOOD = (
        "# Title page\n\n**Title.** A Study\n\n"
        "# Abstract\n\n"
        "**Background.** " + "word " * 40 + "\n\n"
        "**Objective.** " + "word " * 30 + "\n\n"
        "**Methods.** " + "word " * 40 + "\n\n"
        "**Results.** " + "word " * 30 + "\n\n"
        "**Conclusions.** " + "word " * 20 + "\n\n"
        "**Keywords.** one; two; three; four; five; six\n\n"
        "# Methods\n\nThe cohort was assembled from records. Nothing was refit.\n\n"
        "# Declarations\n\n**Funding.** None.\n\n"
        "**Conflicts of interest.** None declared.\n\n"
        "**Ethics and data handling.** Secondary analysis.\n\n"
        "**Authors' contributions.** MF did the work.\n\n"
        "**Data availability.** On request.\n\n"
        "**Abbreviations.** TRD: treatment-resistant depression.\n\n"
        "# References\n\n1. Someone. A paper. Journal. 2024.\n"
    )

    def test_a_compliant_manuscript_passes(self):
        report = venue.check(self.GOOD, "JMIR Mental Health")
        self.assertTrue(report.passed, report.errors)

    def test_an_unprofiled_venue_does_not_pass_silently(self):
        """Writing to a journal nobody has profiled is ordinary. Being told the
        manuscript is compliant against rules nobody checked is how an 810-word
        abstract survived two redrafts."""
        report = venue.check(self.GOOD, "Journal of Made Up Things")
        self.assertFalse(report.passed)
        self.assertTrue(any("no venue profile" in e for e in report.errors))

    def test_no_venue_at_all_does_not_pass_silently(self):
        self.assertFalse(venue.check(self.GOOD, "").passed)

    def test_an_over_length_abstract_is_refused(self):
        text = self.GOOD.replace("**Methods.** " + "word " * 40,
                                 "**Methods.** " + "word " * 400)
        report = venue.check(text, "JMIR")
        self.assertFalse(report.passed)
        self.assertTrue(any("against this venue's ceiling" in e
                            for e in report.errors))

    def test_the_venue_labels_are_not_charged_to_the_author(self):
        """The structured headings are the venue's own form. Counting them against
        the author's allowance is charging them for the boilerplate."""
        report = venue.check(self.GOOD, "JMIR")
        self.assertNotIn("Background", str(report.stats))
        self.assertLess(report.stats["abstract_words"], 450)

    def test_a_missing_structured_heading_is_refused(self):
        report = venue.check(self.GOOD.replace("**Objective.**", "**Aim.**"), "JMIR")
        self.assertFalse(report.passed)
        self.assertTrue(any("no `Objective` heading" in e for e in report.errors))

    def test_a_missing_mandatory_section_is_refused(self):
        report = venue.check(self.GOOD.replace("**Abbreviations.**", "**Notes.**"),
                             "JMIR")
        self.assertFalse(report.passed)
        self.assertTrue(any("`Abbreviations` section" in e for e in report.errors))

    def test_a_url_in_the_body_is_refused(self):
        """The commonest way to break this is a Methods section naming its own code
        repository, which reads as good practice and is not what the venue asked."""
        text = self.GOOD.replace("Nothing was refit.",
                                 "Code is at https://github.com/x/y.")
        report = venue.check(text, "JMIR")
        self.assertFalse(report.passed)
        self.assertTrue(any("URL(s) in the body" in e for e in report.errors))

    def test_a_url_in_the_reference_list_is_fine(self):
        text = self.GOOD.replace("1. Someone. A paper. Journal. 2024.",
                                 "1. Someone. A paper. https://example.org/x")
        self.assertTrue(venue.check(text, "JMIR").passed)

    def test_too_few_keywords_is_refused(self):
        report = venue.check(self.GOOD.replace(
            "one; two; three; four; five; six", "one; two"), "JMIR")
        self.assertFalse(report.passed)
        self.assertTrue(any("keyword" in e for e in report.errors))

    def test_an_advisory_limit_warns_and_says_what_it_costs(self):
        """A venue that recommends a length and charges above it has not set a
        ceiling. Blocking there refuses legitimate manuscripts; saying nothing lets
        the author find out at invoice."""
        long_body = self.GOOD.replace("The cohort was assembled from records.",
                                      "The cohort was assembled. " * 6000)
        report = venue.check(long_body, "JMIR")
        self.assertTrue(report.passed, report.errors)
        self.assertTrue(any("fees" in w for w in report.warnings))

    def test_a_profile_that_has_not_decided_a_key_is_refused(self):
        """A key that is absent is a requirement nobody looked up. `None` records
        that the venue states no limit; missing records that nobody checked."""
        from paperwriter import venues
        half = {k: v for k, v in venues.JMIR.items() if k != "references_max"}
        report = venue.check(self.GOOD, "JMIR", profile=half)
        self.assertFalse(report.passed)
        self.assertTrue(any("does not decide" in e for e in report.errors))

    def test_a_stale_profile_is_reported_rather_than_trusted(self):
        from datetime import date, timedelta
        from paperwriter import venues
        old = dict(venues.JMIR)
        report = venue.check(self.GOOD, "JMIR", profile=old,
                             today=old["checked"] + timedelta(days=900))
        self.assertTrue(report.passed, report.errors)
        self.assertTrue(any("re-read it before submitting" in w
                            for w in report.warnings))


class SupportLadderTests(unittest.TestCase):
    """The ladder: points <- claims <- evidence. The rung this gate owns is the top
    one, and the failure it was written from is a manuscript where every other gate
    passed and a reader still could not say what the paper claimed."""

    POINTS = [
        {"id": "p.1", "point": "The embedding does not outperform the feature vector "
                               "on this outcome."},
        {"id": "p.2", "point": "Retrieval over that embedding loses to a model fitted "
                               "on it."},
    ]

    def _claims(self, **overrides):
        base = [
            {"id": "c.1", "claim": "the two representations tie",
             "kind": "comparative", "serves": ["p.1"], "headline": True},
            {"id": "c.2", "claim": "the tie holds across four encoders",
             "kind": "descriptive", "serves": ["p.1"]},
            {"id": "c.3", "claim": "nearest retrieval beats random retrieval",
             "kind": "descriptive", "serves": ["p.2"], "headline": True},
            {"id": "c.4", "claim": "retrieval falls short of the trained model",
             "kind": "comparative", "serves": ["p.2"]},
            {"id": "c.5", "claim": "the cohort is one community health system",
             "kind": "descriptive", "role": "setup"},
        ]
        for cid, patch in overrides.items():
            for claim in base:
                if claim["id"] == cid.replace("_", "."):
                    claim.update(patch)
        return base

    def test_a_well_formed_ladder_passes(self):
        report = ladder.check(self.POINTS, self._claims())
        self.assertTrue(report.passed, report.errors)

    def test_no_points_is_a_list_of_findings(self):
        report = ladder.check([], self._claims())
        self.assertFalse(report.passed)
        self.assertTrue(any("declares no points" in e for e in report.errors))

    def test_too_many_points_is_several_papers(self):
        points = self.POINTS + [
            {"id": f"p.{i}", "point": f"a {i}th thing the paper is also about here"}
            for i in range(3, 6)]
        claims = self._claims() + [
            {"id": f"c.1{i}", "claim": f"support {i}", "kind": "descriptive",
             "serves": [f"p.{i}"], "headline": True} for i in range(3, 6)
        ] + [
            {"id": f"c.2{i}", "claim": f"more support {i}", "kind": "descriptive",
             "serves": [f"p.{i}"]} for i in range(3, 6)]
        report = ladder.check(points, claims)
        self.assertFalse(report.passed)
        self.assertTrue(any("the ceiling is" in e for e in report.errors))

    def test_a_point_that_is_a_topic_is_refused(self):
        points = [dict(self.POINTS[0], point="representation comparison"),
                  self.POINTS[1]]
        report = ladder.check(points, self._claims())
        self.assertFalse(report.passed)
        self.assertTrue(any("topic, not a point" in e for e in report.errors))

    def test_a_claim_serving_nothing_is_refused(self):
        report = ladder.check(self.POINTS, self._claims(c_2={"serves": []}))
        self.assertFalse(report.passed)
        self.assertTrue(any("serves no point and declares no role" in e
                            for e in report.errors))

    def test_a_claim_cannot_both_serve_and_have_a_role(self):
        report = ladder.check(self.POINTS, self._claims(c_2={"role": "setup"}))
        self.assertFalse(report.passed)
        self.assertTrue(any("both serves" in e for e in report.errors))

    def test_an_unknown_role_is_refused_and_names_the_valid_ones(self):
        report = ladder.check(self.POINTS,
                               self._claims(c_5={"role": "validity"}))
        self.assertFalse(report.passed)
        self.assertTrue(any("no role for a validity check" in e
                            for e in report.errors))

    def test_a_claim_serving_a_point_that_does_not_exist_is_refused(self):
        report = ladder.check(self.POINTS, self._claims(c_2={"serves": ["p.9"]}))
        self.assertFalse(report.passed)
        self.assertTrue(any("does not declare" in e for e in report.errors))

    def test_a_point_carried_by_one_claim_is_that_claim(self):
        report = ladder.check(self.POINTS, self._claims(c_2={"serves": ["p.2"]}))
        self.assertFalse(report.passed)
        self.assertTrue(any("is served by 1 claim" in e for e in report.errors))

    def test_a_point_supported_only_by_caveats_is_not_a_finding(self):
        claims = self._claims(c_3={"kind": "limitation"},
                              c_4={"kind": "limitation"})
        report = ladder.check(self.POINTS, claims)
        self.assertFalse(report.passed)
        self.assertTrue(any("only by limitation claims" in e
                            for e in report.errors))

    def test_every_point_has_one_claim_that_states_it(self):
        report = ladder.check(self.POINTS, self._claims(c_3={"headline": False}))
        self.assertFalse(report.passed)
        self.assertTrue(any("no claim marked `headline`" in e
                            for e in report.errors))

    def test_two_claims_cannot_both_state_one_point(self):
        report = ladder.check(self.POINTS, self._claims(c_2={"headline": True}))
        self.assertFalse(report.passed)
        self.assertTrue(any("claims marked `headline`" in e
                            for e in report.errors))

    def test_the_role_allowance_is_bounded(self):
        """An unbounded exemption turns the ladder into decoration, and `setup` is the
        easiest label in the world to reach for."""
        claims = self._claims()
        claims += [{"id": f"c.1{i}", "claim": f"more background {i}",
                    "kind": "descriptive", "role": "setup"} for i in range(4)]
        report = ladder.check(self.POINTS, claims)
        self.assertFalse(report.passed)
        self.assertTrue(any("the ladder is" in e for e in report.errors))


class SupportLadderBudgetTests(unittest.TestCase):
    """The word-budget half. A graph check asks whether every claim has a parent,
    which a writer satisfies by attaching claims loosely; length cannot be argued
    with, and it is the half that catches a complete and irrelevant section."""

    POINTS = [{"id": "p.1", "point": "The embedding does not outperform the feature "
                                     "vector on this outcome."}]
    CLAIMS = [
        {"id": "c.1", "claim": "the two tie", "kind": "comparative",
         "serves": ["p.1"], "headline": True},
        {"id": "c.2", "claim": "the tie holds across encoders", "kind": "descriptive",
         "serves": ["p.1"]},
        {"id": "c.9", "claim": "the judge rubric was mislabelled",
         "kind": "descriptive", "role": "reporting"},
    ]

    def _outline(self, aside_words):
        return {"sections": [
            {"number": 1, "heading": "Introduction", "words": 400, "claims": []},
            {"number": 2, "heading": "Results", "words": 1000, "claims": ["c.1", "c.2"]},
            {"number": 3, "heading": "A similarity judge nobody needed",
             "words": aside_words, "claims": ["c.9"]},
            {"number": 4, "heading": "References", "words": 300, "claims": []},
        ]}

    def test_a_small_aside_passes(self):
        report = ladder.check(self.POINTS, self.CLAIMS, outline=self._outline(120))
        self.assertTrue(report.passed, report.errors)

    def test_a_section_serving_nothing_is_refused_on_length(self):
        report = ladder.check(self.POINTS, self.CLAIMS, outline=self._outline(900))
        self.assertFalse(report.passed)
        self.assertTrue(any("serve no point" in e for e in report.errors))
        self.assertTrue(any("A similarity judge nobody needed" in e
                            for e in report.errors))

    def test_the_share_is_warned_about_before_it_blocks(self):
        report = ladder.check(self.POINTS, self.CLAIMS, outline=self._outline(250))
        self.assertTrue(report.passed, report.errors)
        self.assertTrue(any("grows quietly" in w for w in report.warnings))

    def test_a_section_with_no_claims_is_structural_not_unladdered(self):
        """An Introduction that sets up every point without asserting one is the
        ordinary case. Counting its words as serving nothing fires on every paper."""
        outline = self._outline(120)
        outline["sections"][0]["words"] = 4000        # an enormous claim-free section
        report = ladder.check(self.POINTS, self.CLAIMS, outline=outline)
        self.assertTrue(report.passed, report.errors)


class SupportLadderMigrationTests(unittest.TestCase):
    """A claim map written before the ladder existed marks one claim `headline`,
    declares no points, and gives no claim a `serves`. Refusing those would strand
    state that is otherwise fine, so both halves of the migration travel together."""

    LEGACY = [
        {"id": "c.1", "claim": "the embedded representation discriminates better",
         "kind": "comparative", "headline": True},
        {"id": "c.2", "claim": "the split is large enough to estimate the gap",
         "kind": "descriptive"},
        {"id": "c.3", "claim": "discrimination is not benefit", "kind": "limitation"},
    ]

    def test_a_pre_ladder_map_migrates_to_one_point(self):
        points, claims = ladder.migrated([], self.LEGACY)
        self.assertEqual([p["id"] for p in points], ["p.1"])
        self.assertEqual(points[0]["derived_from"], "c.1")
        self.assertTrue(all(c["serves"] == ["p.1"] for c in claims))
        self.assertTrue(ladder.check(points, claims).passed)

    def test_a_derived_point_is_not_measured_as_prose(self):
        """It inherits its wording from the claim it came from, so measuring its
        length measures that claim against a rule it never had to meet."""
        terse = [{"id": "c.1", "claim": "text wins", "kind": "comparative",
                  "headline": True},
                 {"id": "c.2", "claim": "twice over", "kind": "descriptive"}]
        points, claims = ladder.migrated([], terse)
        self.assertTrue(ladder.check(points, claims).passed)

    def test_declared_points_are_not_filled_in(self):
        """Under declared points a claim with no `serves` skipped a field that
        exists, which is a different thing from a map that predates it."""
        points = [{"id": "p.1", "point": "a thing this paper is genuinely about"}]
        _p, claims = ladder.migrated(points, self.LEGACY)
        self.assertFalse(any(c.get("serves") for c in claims))
        self.assertFalse(ladder.check(points, claims).passed)

    def test_a_map_with_no_headline_does_not_migrate_silently(self):
        points, _claims = ladder.migrated([], [dict(self.LEGACY[1])])
        self.assertEqual(points, [])


class OutlineParagraphLadderTests(unittest.TestCase):
    """The rung below the ladder: a section can carry three claims, plan nine
    paragraphs that touch two of them, and simply not make the third."""

    def _outline(self, paragraphs):
        return {"sections": [{
            "number": 1, "heading": "Results", "words": 600,
            "claims": ["c.1", "c.2"], "evidence": [],
            "paragraphs": paragraphs}]}

    def test_a_paragraph_advancing_a_claim_passes(self):
        outline = self._outline([
            {"topic": "The two representations discriminated alike.",
             "supports": ["c.1"]},
            {"topic": "That tie held across every encoder tested.",
             "supports": ["c.2"]},
        ])
        self.assertTrue(structure.check(outline).passed)

    def test_a_claim_no_paragraph_makes_is_refused(self):
        outline = self._outline([
            {"topic": "The two representations discriminated alike.",
             "supports": ["c.1"]},
            {"topic": "The interval was narrower than the marginal ones.",
             "supports": ["c.1"]},
        ])
        report = structure.check(outline)
        self.assertFalse(report.passed)
        self.assertTrue(any("no paragraph advances" in e for e in report.errors))

    def test_a_paragraph_cannot_advance_another_sections_claim(self):
        outline = self._outline([
            {"topic": "The two representations discriminated alike.",
             "supports": ["c.1"]},
            {"topic": "That tie held across every encoder tested.",
             "supports": ["c.2", "c.7"]},
        ])
        report = structure.check(outline)
        self.assertFalse(report.passed)
        self.assertTrue(any("which this section does not carry" in e
                            for e in report.errors))

    def test_a_section_of_transitions_has_no_argument_in_it(self):
        outline = self._outline([
            {"topic": "This paragraph sets the scene for what follows.",
             "role": "transition"},
            {"topic": "This paragraph also sets the scene for what follows.",
             "role": "transition"},
            {"topic": "The two representations discriminated alike.",
             "supports": ["c.1", "c.2"]},
        ])
        report = structure.check(outline)
        self.assertFalse(report.passed)
        self.assertTrue(any("no argument in it" in e for e in report.errors))

    def test_a_claimless_section_is_structural(self):
        outline = {"sections": [{
            "number": 1, "heading": "Declarations", "words": 200, "claims": [],
            "evidence": [], "paragraphs": [
                {"topic": "The funder had no role in the analysis."},
                {"topic": "The authors declare no competing interests."},
            ]}]}
        self.assertTrue(structure.check(outline).passed)


class OutlineStructureTests(unittest.TestCase):

    def _section(self, number, heading, words=500, claims_=(), paragraphs_=None):
        return {
            "number": number, "heading": heading, "words": words,
            "claims": list(claims_), "evidence": [],
            "paragraphs": paragraphs_ if paragraphs_ is not None else [
                {"topic": "This paragraph makes a claim about the cohort."},
                {"topic": "This paragraph makes a claim about the model."},
            ]}

    def _outline(self, headings=("Introduction", "Methods", "Results", "Discussion")):
        return {"sections": [self._section(i, h)
                             for i, h in enumerate(headings, start=1)]}

    def test_a_well_formed_outline_passes(self):
        self.assertTrue(structure.check(self._outline()).passed)

    def test_results_before_methods_is_refused(self):
        outline = self._outline(("Introduction", "Results", "Methods", "Discussion"))
        report = structure.check(outline)
        self.assertFalse(report.passed)
        self.assertTrue(any("belongs before it" in e for e in report.errors))

    def test_a_duplicate_heading_is_refused(self):
        outline = self._outline(("Methods", "Methods"))
        self.assertFalse(structure.check(outline).passed)

    def test_budgets_over_the_venue_limit_are_refused(self):
        report = structure.check(self._outline(), word_limit=1000)
        self.assertFalse(report.passed)
        self.assertTrue(any("Cut a claim" in e for e in report.errors))

    def test_a_paragraph_with_no_topic_sentence_is_refused(self):
        outline = self._outline()
        outline["sections"][0]["paragraphs"] = [{"topic": ""}]
        report = structure.check(outline)
        self.assertFalse(report.passed)
        self.assertTrue(any("no topic sentence" in e for e in report.errors))

    def test_a_topic_label_is_not_a_topic_sentence(self):
        outline = self._outline()
        outline["sections"][0]["paragraphs"] = [{"topic": "cohort characteristics"}]
        report = structure.check(outline)
        self.assertFalse(report.passed)
        self.assertTrue(any("label, not a claim" in e for e in report.errors))

    def test_a_section_with_no_paragraph_plan_is_refused(self):
        outline = self._outline()
        outline["sections"][0]["paragraphs"] = []
        self.assertFalse(structure.check(outline).passed)

    def test_a_claim_placed_twice_is_refused(self):
        outline = self._outline(("Methods", "Results"))
        outline["sections"][0]["claims"] = ["c.1"]
        outline["sections"][1]["claims"] = ["c.1"]
        report = structure.check(outline, argument_claims=[
            {"id": "c.1", "claim": "x"}])
        self.assertFalse(report.passed)
        self.assertTrue(any("already placed" in e for e in report.errors))

    def test_a_claim_the_map_does_not_hold_is_refused(self):
        outline = self._outline(("Results",))
        outline["sections"][0]["claims"] = ["c.9"]
        report = structure.check(outline, argument_claims=[
            {"id": "c.1", "claim": "x"}])
        self.assertFalse(report.passed)

    def test_an_unplaced_claim_is_refused(self):
        outline = self._outline(("Results",))
        report = structure.check(outline, argument_claims=[
            {"id": "c.1", "claim": "x"}])
        self.assertFalse(report.passed)
        self.assertTrue(any("no section makes it" in e for e in report.errors))

    def test_front_matter_and_back_matter_sort_correctly(self):
        self.assertEqual(structure.phase_of("Abstract"), "front")
        self.assertEqual(structure.phase_of("Statistical analysis"), "methods")
        self.assertEqual(structure.phase_of("Declarations"), "back")
        self.assertEqual(structure.phase_of("Something Else"), "")


class ConfigBandTests(unittest.TestCase):
    """The thresholds are the contract. A change to one of these is a change to what
    the harness will publish, so it should break a test and be argued about."""

    def test_the_sentence_band_is_academic(self):
        self.assertGreater(config.SENTENCE_MEAN_WORDS_MAX,
                           config.SENTENCE_MEAN_WORDS_MIN)
        self.assertLessEqual(config.SENTENCE_MEAN_WORDS_MAX, 24)

    def test_the_hard_ceiling_is_above_the_long_threshold(self):
        self.assertGreater(config.SENTENCE_HARD_MAX_WORDS, config.SENTENCE_LONG_WORDS)

    def test_the_paragraph_band_admits_a_real_paragraph(self):
        self.assertLessEqual(config.PARAGRAPH_MIN_SENTENCES, 3)
        self.assertGreaterEqual(config.PARAGRAPH_MAX_SENTENCES, 7)


if __name__ == "__main__":
    unittest.main()
