"""The final sweep — every gate, every section, every document, on the built packet.

The gates themselves are tested in `test_gates.py`. What is tested here is the thing
the sweep contributes, which is scope: that it reads every document rather than the
manuscript, that it measures section by section rather than as one block, and that
handing a gate one section's BODY does not switch off an exemption the gate keys on a
heading. That last one is the whole class of bug this file exists for.
"""
import unittest

import support                                                      # noqa: F401
from paperwriter.stages import sweep

# A locked vocabulary with one banned alias, one approved second name, and one
# abbreviation, which is enough to reach every branch that matters.
LOCK = [
    {"term": "feature representation",
     "aliases": ["rule-based approach", "feature matrix"],
     "also_called": ["feature vector"]},
    {"term": "TRD", "first_use": "treatment-resistant depression",
     "aliases": ["resistant depression"]},
]
EVIDENCE = {"items": [{"id": "e.1", "statement": "discrimination",
                       "values": [0.657, 0.649]}]}
REFERENCES = {"1": {}, "2": {}}


class SectionSplittingTests(unittest.TestCase):

    def test_it_splits_on_top_level_headings_only(self):
        text = ("# Methods\n\nWe did the thing.\n\n"
                "## Participants\n\nThey were people.\n\n"
                "# Results\n\nIt worked.\n")
        self.assertEqual([h for h, _ in sweep.sections(text)],
                         ["Methods", "Results"])
        self.assertIn("Participants", sweep.sections(text)[0][1])

    def test_a_hash_inside_a_comment_block_is_not_a_heading(self):
        """The packet's decision records live in HTML comment blocks and routinely
        quote a heading. Splitting on one divides the document in a place it does not
        divide, and every section after it is measured under the wrong name."""
        text = ("<!--\nDO NOT re-add this:\n# Methods\n-->\n\n"
                "# Introduction\n\nThe question is open.\n")
        self.assertEqual([h for h, _ in sweep.sections(text)], ["Introduction"])

    def test_a_preamble_before_the_first_heading_is_not_dropped(self):
        text = "Front matter nobody gave a heading.\n\n# Results\n\nIt worked.\n"
        self.assertEqual([h for h, _ in sweep.sections(text)], ["", "Results"])


class SectionScopeExemptionTests(unittest.TestCase):
    """A gate handed one section's BODY cannot see the heading it keys an exemption
    on. Every one of these was a live false positive when the sweep was first run."""

    def _findings(self, heading, body):
        out = []
        sweep._section_scope(out, "manuscript.md", heading, body, EVIDENCE, LOCK,
                             REFERENCES, None)
        return out

    def test_a_reference_lists_numbers_are_not_findings(self):
        """A Vancouver entry is a dense block of numbers and not one is a result. The
        exemption is keyed on the `References` heading, which is not in the body."""
        body = ("1. Al-Harbi KS. Treatment-resistant depression. Patient Prefer "
                "Adherence. 2012;6:369-388. doi:10.2147/PPA.S29716.\n")
        self.assertEqual([f for f in self._findings("References", body)
                          if f.gate == "numbers"], [])

    def test_the_same_numbers_are_findings_in_a_results_section(self):
        body = ("Discrimination reached 0.883 in the held-out set. The interval was "
                "wide. Nothing else moved.")
        self.assertTrue([f for f in self._findings("Results", body)
                         if f.gate == "numbers"])

    def test_a_reference_titles_banned_synonym_is_not_a_finding(self):
        """You cannot rename somebody else's paper."""
        body = ("1. Iveson MH. Treatment resistant depression in electronic health "
                "records: definitions matter. BMC Psychiatry. 2026.\n")
        self.assertEqual([f for f in self._findings("References", body)
                          if f.gate == "terminology"], [])

    def test_the_same_synonym_is_a_finding_in_the_body(self):
        body = ("Patients with resistant depression switched more often. The pattern "
                "held in both arms. Nothing else separated them.")
        self.assertTrue([f for f in self._findings("Discussion", body)
                         if f.gate == "terminology"])

    def test_one_finding_per_section_not_one_per_number(self):
        """The gate's own reason already names up to eight offenders. A hundred lines
        saying the same thing is how a list stops being read."""
        body = ("Discrimination reached 0.883, then 0.912, then 0.945 across the "
                "three runs. The fourth reached 0.971. The fifth reached 0.988.")
        numbers = [f for f in self._findings("Results", body) if f.gate == "numbers"]
        self.assertEqual(len(numbers), 1)
        self.assertTrue(numbers[0].anchor, "the first offender is the edit anchor")


class PacketScopeTests(unittest.TestCase):

    MANUSCRIPT = (
        "# Abstract\n\nTreatment-resistant depression (TRD) was the outcome. It was "
        "a proxy.\n\n"
        "# Introduction\n\nThe question is open. Nobody has answered it [1].\n\n"
        "# Methods\n\nWe built a feature vector. It carried ninety-two columns.\n\n"
        "# Results\n\nThe model reached 0.657. The other reached 0.649 [2].\n\n"
        "# Discussion\n\nNeither beat the other. The comparison was paired.\n\n"
        "# References\n\n1. Someone. A paper. Journal. 2024.\n\n"
        "2. Another. A second paper. Journal. 2025.\n")

    def _findings(self, texts, where=""):
        out = []
        sweep._packet_scope(out, texts, EVIDENCE, LOCK, REFERENCES, where)
        return out

    def test_a_companion_document_is_not_asked_to_expand_again(self):
        """A supplement is delivered as its own file and legitimately reuses the
        abbreviations the manuscript expanded. Demanding it expand TRD again is
        demanding the manuscript expand it twice."""
        texts = {"manuscript.md": self.MANUSCRIPT,
                 "supplement.md": ("# Supplement M1. Sources\n\nTRD was assigned on "
                                   "the switch count. Nothing was refit.\n")}
        kinds = [f.detail for f in self._findings(texts)
                 if f.gate == "terminology" and f.document == "supplement.md"]
        self.assertEqual(kinds, [])

    def test_drift_still_runs_on_a_companion_document(self):
        """A second name for one method is a defect wherever in the packet it is.

        An UNDECLARED variant, because a declared alias is reported at section scope
        with its own anchor and the packet pass deliberately skips those to avoid
        printing the same defect twice."""
        texts = {"manuscript.md": self.MANUSCRIPT,
                 "supplement.md": ("# Supplement M1. Sources\n\nThe feature pipeline "
                                   "held the columns. The feature pipeline was "
                                   "typed.\n")}
        found = [f for f in self._findings(texts)
                 if f.gate == "terminology" and f.document == "supplement.md"]
        self.assertTrue(found)
        self.assertIn("feature pipeline", found[0].detail)

    def test_an_unnamed_pointer_is_a_packet_finding(self):
        texts = {"manuscript.md": self.MANUSCRIPT.replace(
            "The comparison was paired.", "The rest is in supporting material.")}
        self.assertTrue([f for f in self._findings(texts) if f.gate == "crossrefs"])

    def test_references_out_of_order_are_a_packet_finding(self):
        texts = {"manuscript.md": self.MANUSCRIPT.replace(
            "Nobody has answered it [1].", "Nobody has answered it [2].")}
        self.assertTrue([f for f in self._findings(texts) if f.gate == "citations"])


class SeverityTests(unittest.TestCase):

    def test_blocking_leads_the_notes(self):
        """A list nobody can act on in order is a list nobody reads in order."""
        report = sweep.SweepReport(findings=[
            sweep.Finding("m.md", "Results", "length", "advisory", "wordy"),
            sweep.Finding("m.md", "Results", "numbers", "blocking", "0.883 is not in "
                          "the ledger"),
        ])
        notes = report.notes()
        self.assertTrue(notes[0].startswith("BLOCKING"))
        self.assertTrue(notes[1].startswith("advisory"))

    def test_only_blocking_decides_whether_it_passed(self):
        report = sweep.SweepReport(findings=[
            sweep.Finding("m.md", "Results", "length", "advisory", "wordy")])
        self.assertEqual(report.blocking(), [])
        self.assertEqual(len(report.advisory()), 1)

    def test_a_finding_says_where_it_is(self):
        finding = sweep.Finding("supplement.md", "Supplement S7. Subgroups",
                                "sentences", "blocking", "too dense")
        self.assertIn("supplement.md", finding.label())
        self.assertIn("Supplement S7", finding.label())
        self.assertIn("sentences", finding.label())

    def test_a_packet_wide_finding_says_so(self):
        self.assertIn("packet",
                      sweep.Finding("", "", "crossrefs", "blocking", "x").label())


if __name__ == "__main__":
    unittest.main()
