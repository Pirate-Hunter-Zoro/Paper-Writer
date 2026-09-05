"""The gates. Pure arithmetic over strings and dicts, so these tests need no fixtures
beyond the strings themselves.

This is the largest test module in the project on purpose. The gates are the only thing
standing between a confidently wrong model and a published manuscript, and every one of
them is cheap enough to test exhaustively.
"""

import support                                                      # noqa: F401
import unittest                                                     # noqa: E402

from paperwriter import config                                      # noqa: E402
from paperwriter.gates import (citations, claims, coverage,         # noqa: E402
                               length, numbers, paragraphs, prose,
                               readability, sentences, structure,
                               terminology)


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

    def test_headings_and_tables_are_not_prose(self):
        text = "# Results\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nThe model did better."
        self.assertEqual(prose.sentences(text), ["The model did better."])

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

    def test_semicolons_are_rationed(self):
        text = " ".join(["The model did better; the gap was small."] * 6)
        report = sentences.score(text)
        self.assertFalse(report.passed)
        self.assertTrue(any("semicolon" in r for r in report.reasons))

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
        report = terminology.check("Patients with TRD were included.", self.LOCK)
        self.assertIn("undefined-abbreviation", {d.kind for d in report.defects})

    def test_an_expansion_across_a_line_break_still_counts(self):
        """Drafted prose arrives hard-wrapped. A gate that misses the expansion
        reports a defect the editor cannot repair, because nothing is wrong."""
        report = terminology.check(
            "Patients with treatment-resistant\ndepression (TRD) were included.",
            self.LOCK)
        self.assertTrue(report.passed, [d.detail for d in report.defects])

    def test_expanding_twice_is_a_defect(self):
        report = terminology.check(
            "Treatment-resistant depression (TRD) is common. We studied "
            "treatment-resistant depression again.", self.LOCK)
        self.assertIn("redefined", {d.kind for d in report.defects})

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
