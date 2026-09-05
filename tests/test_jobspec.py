"""Parsing the dropped prompt file.

Every value here becomes a denominator or a threshold somewhere downstream, so a
parser that is too generous is a free penalty against a good job and a parser that is
too literal is a job that cannot be submitted. Both directions are tested.
"""

import support                                                      # noqa: F401
import unittest                                                     # noqa: E402

from paperwriter import jobspec                                     # noqa: E402


class SectionTests(unittest.TestCase):

    def test_sections_are_split_on_headings(self):
        secs = jobspec.sections("# Title\nbody one\n\n## Venue\nbody two\n")
        self.assertEqual(secs["title"], "body one")
        self.assertEqual(secs["venue"], "body two")

    def test_section_matching_finds_a_partial_header(self):
        secs = jobspec.sections("## Target journal\nJMIR\n")
        self.assertEqual(jobspec.section_matching(secs, "journal"), "JMIR")


class CorpusTests(unittest.TestCase):

    def test_one_corpus_from_the_first_line(self):
        self.assertEqual(jobspec.corpora(support.PROMPT), ["fixture analysis"])

    def test_prose_after_the_first_line_is_ignored(self):
        """A prose-y section body shredded into eight junk corpora is eight evidence
        directories and eight gathering calls."""
        text = ("## Evidence\n\nTRD-EHR primary analysis\n\nThis is the extract we "
                "pulled in June, and it covers everything, plus the reference PDFs.\n")
        self.assertEqual(jobspec.corpora(text), ["TRD-EHR primary analysis"])

    def test_a_plus_splits_a_genuine_second_corpus(self):
        text = "## Evidence\n\nTRD-EHR + PSYCH-ASR pilot\n"
        self.assertEqual(jobspec.corpora(text), ["TRD-EHR", "PSYCH-ASR pilot"])

    def test_commas_do_not_split(self):
        text = "## Evidence\n\nTRD-EHR, all locales\n"
        self.assertEqual(jobspec.corpora(text), ["TRD-EHR, all locales"])

    def test_a_job_naming_none_still_gets_a_corpus(self):
        """A paper written against unnamed evidence is still a paper, and the coverage
        gate says something more useful about it than a parse error would."""
        self.assertEqual(jobspec.corpora("# Title\n\nsome text\n"), ["primary"])


class ClaimTests(unittest.TestCase):

    def test_bullets_become_claims(self):
        self.assertEqual(len(jobspec.intended_claims(support.PROMPT)), 3)

    def test_a_wrapped_bullet_is_one_claim(self):
        """Half a claim on its own line is a claim no evidence can cover, and it is a
        free penalty in the coverage gate's denominator."""
        claims = jobspec.intended_claims(support.PROMPT)
        self.assertIn("held-out split", claims[0])

    def test_context_prose_is_not_a_claim(self):
        text = ("## Claims\n\nThis paper matters because nobody has done it.\n\n"
                "- The model discriminates well on held-out data.\n")
        self.assertEqual(len(jobspec.intended_claims(text)), 1)


class VenueTests(unittest.TestCase):

    def test_the_venue_is_the_first_line(self):
        self.assertEqual(jobspec.venue(support.PROMPT), "Journal of Fixtures.")

    def test_the_word_limit_is_parsed(self):
        self.assertEqual(jobspec.word_limit(support.PROMPT), 4000)

    def test_a_thousands_separator_is_handled(self):
        text = "## Venue\n\nJMIR. 4,000 word limit for an Original Paper.\n"
        self.assertEqual(jobspec.word_limit(text), 4000)

    def test_an_abstract_limit_is_not_a_manuscript_limit(self):
        """A 'word limit' under 250 is an abstract's, and enforcing it on the whole
        paper plans a four-paragraph submission."""
        text = "## Venue\n\nJMIR. 200 word structured abstract.\n"
        self.assertIsNone(jobspec.word_limit(text))

    def test_no_limit_is_none_rather_than_a_guess(self):
        self.assertIsNone(jobspec.word_limit("## Venue\n\nJMIR Mental Health.\n"))

    def test_a_reference_docx_is_found(self):
        self.assertEqual(jobspec.reference_docx(
            "## Venue\n\nJMIR. Use formats/JMIR_template.docx.\n"),
            "formats/JMIR_template.docx")


class ScopeTests(unittest.TestCase):

    def test_one_paper_is_the_default(self):
        self.assertEqual(jobspec.paper_count("# Title\n\nnothing else\n"), 1)

    def test_the_fixture_asks_for_one(self):
        self.assertEqual(jobspec.paper_count(support.PROMPT), 1)

    def test_a_stated_count_is_honoured(self):
        self.assertEqual(jobspec.paper_count("## Scope\n\n3 papers off one analysis.\n"),
                         3)

    def test_an_absurd_count_falls_back_to_one(self):
        self.assertEqual(jobspec.paper_count("## Scope\n\n90 papers.\n"), 1)


class ChecklistTests(unittest.TestCase):

    def test_the_checklist_is_read_not_inferred(self):
        self.assertEqual(jobspec.checklist(support.PROMPT), "TRIPOD+AI")

    def test_an_absent_checklist_is_empty(self):
        self.assertEqual(jobspec.checklist("# Title\n\nnothing\n"), "")


class TitleTests(unittest.TestCase):

    def test_the_first_heading_is_the_title(self):
        self.assertEqual(jobspec.title(support.PROMPT),
                         "Does narrative text beat structured features")


if __name__ == "__main__":
    unittest.main()
