"""The editorial loop — the feedback mechanic.

Two things are worth testing here and they are different. One is that the gates reach
the editor as facts with anchors attached, rather than as opinions. The other is that
the loop converges: defects fall, repairs land, and a section that will not come clean
ships holding its notes instead of parking.
"""

import support                                                      # noqa: F401
import unittest                                                     # noqa: E402

from paperwriter import paths, states                               # noqa: E402
from paperwriter.engine import section as section_level             # noqa: E402
from paperwriter.infra import journal, storage                      # noqa: E402
from paperwriter.memory import store                                # noqa: E402
from paperwriter.stages import review                               # noqa: E402


SECTION = {
    "number": 4, "heading": "Results", "words": 200,
    "claims": ["c.1"], "evidence": ["e.1", "e.2", "e.3", "e.4"],
    "paragraphs": [{"topic": "The embedded representation did better."}],
}


class GateBriefTests(unittest.TestCase):
    """What the editor is told. A gate failure that reaches the model as prose it
    cannot anchor is a defect reported on every pass and repaired on none."""

    @classmethod
    def setUpClass(cls):
        support.stub_model_seams()
        support.wipe_state()
        support.drop("brief-paper")
        support.run_engine("brief-paper")
        cls.rec = journal.load_records()[journal.project_key("brief-paper")]
        cls.memory = store.load(cls.rec, 1)

    def _brief(self, prose):
        _failures, brief, _measured = review.run_gates(prose, SECTION, self.memory)
        return brief

    def test_a_wrong_number_is_named_with_its_anchor(self):
        prose = ("The embedded representation did better. Area under the curve "
                 "reached 0.9999 on the held-out split. That gap held across draws.")
        brief = self._brief(prose)
        self.assertIn("NUMBER GATE", brief)
        self.assertIn("0.9999", brief)
        self.assertIn("Area under the curve reached 0.9999 on the held-out split.",
                      brief)

    def test_a_forbidden_alias_is_named_with_its_anchor(self):
        prose = ("The embedded representation did better. The rule-based approach "
                 "reached less. The gap held across draws of the split.")
        brief = self._brief(prose)
        self.assertIn("TERMINOLOGY GATE", brief)
        self.assertIn("rule-based approach", brief)

    def test_a_dense_section_gets_its_worst_sentences_quoted(self):
        prose = (
            "The embedded representation, which was produced by a pretrained encoder "
            "applied to every narrative section of every record and then pooled over "
            "the whole encounter window rather than a fixed lookback period, "
            "discriminated the outcome rather more sharply than the typed feature "
            "vector managed to, although that difference was smaller in the youngest "
            "subgroup and may possibly reflect sampling. It held. The gap held.")
        brief = self._brief(prose)
        self.assertIn("SENTENCE GATE", brief)
        self.assertIn("pretrained encoder", brief)

    def test_a_clean_section_produces_no_brief(self):
        failures, brief, _m = review.run_gates(support.CLEAN_PROSE, SECTION,
                                               self.memory)
        self.assertEqual(failures, [], failures)
        self.assertEqual(brief.strip(), "")

    def test_the_measurements_are_recorded(self):
        _f, _b, measured = review.run_gates(support.CLEAN_PROSE, SECTION, self.memory)
        self.assertGreater(measured["words"], 0)
        self.assertGreater(measured["sentence_mean"], 0)
        self.assertEqual(measured["numbers_unsupported"], 0)


class NormalisationTests(unittest.TestCase):
    """What the editor returns, and what the harness makes of it."""

    def test_a_fact_defect_blocks_by_default(self):
        issues, _s = review.normalise({"issues": [
            {"kind": "number", "issue": "wrong", "find": "x", "replace": "y"}]})
        self.assertEqual(issues[0]["severity"], "blocking")

    def test_a_style_defect_is_polish_by_default(self):
        issues, _s = review.normalise({"issues": [
            {"kind": "style", "issue": "clumsy", "find": "x", "replace": "y"}]})
        self.assertEqual(issues[0]["severity"], "polish")

    def test_an_unrecognised_kind_becomes_a_claim(self):
        issues, _s = review.normalise({"issues": [
            {"kind": "vibes", "issue": "off", "find": "x", "replace": "y"}]})
        self.assertEqual(issues[0]["kind"], "claim")

    def test_an_issue_with_no_anchor_is_carried_rather_than_dropped(self):
        """The signal the engine escalates on. Silently discarding it makes a section
        holding a defect look clean."""
        issues, _s = review.normalise({"issues": [
            {"kind": "number", "issue": "somewhere in here"}]})
        self.assertFalse(issues[0]["anchored"])
        self.assertEqual(issues[0]["severity"], "blocking")

    def test_repairs_are_applied_longest_anchor_first(self):
        """Two edits where one anchor contains the other. Applying the containing one
        first destroys the nested anchor, and the specific edit is then correctly but
        pointlessly refused."""
        prose = "The model reached 0.99 on the split."
        report = {"issues": [
            {"kind": "number", "severity": "blocking", "issue": "broad",
             "find": "reached 0.99 on the split", "replace": "reached 0.74 on it",
             "anchored": True},
            {"kind": "number", "severity": "blocking", "issue": "narrow",
             "find": "0.99", "replace": "0.7429", "anchored": True},
        ]}
        out, applied, rejected = review.apply_report(prose, report)
        self.assertEqual(len(applied), 1)
        self.assertEqual(len(rejected), 1)
        self.assertIn("reached 0.74 on it", out)


class LoopTests(unittest.TestCase):
    """Convergence, and what happens when it does not come."""

    @classmethod
    def setUpClass(cls):
        support.stub_model_seams()

    def setUp(self):
        support.wipe_state()

    def test_a_section_the_editor_cannot_repair_still_ships(self):
        """A section that parks fails its paper, which fails its project. Shipping it
        with its notes recorded is strictly better in every case, including the ones
        where the section really is bad."""
        def unfixable(project_rec, paper_num, section_num, prose, truth, brief,
                      pass_num, log_fn=None):
            return {"issues": [{"kind": "claim", "severity": "blocking",
                                "issue": "this claim is not supported"}],
                    "structural": []}

        good = review.model_review
        review.model_review = unfixable
        try:
            support.drop("stubborn-paper")
            status = support.run_engine("stubborn-paper")
            self.assertEqual(status, states.PROJECT_COMPLETE)
            records = journal.load_records()
            sections = journal.sections_of(records, "stubborn-paper", 1)
            self.assertTrue(sections)
            for record in sections:
                self.assertEqual(record["status"], states.LEDGER_MERGED)
                self.assertTrue(record.get("outstanding_issues"),
                                f"section {record['section_num']} lost its notes")
                self.assertTrue(
                    paths.section_path("stubborn-paper", 1,
                                       record["section_num"]).exists())
        finally:
            review.model_review = good

    def test_the_pass_budget_is_bounded(self):
        from paperwriter import config

        def never_clean(project_rec, paper_num, section_num, prose, truth, brief,
                        pass_num, log_fn=None):
            return {"issues": [{"kind": "claim", "severity": "blocking",
                                "issue": f"pass {pass_num}", "find": "The gap held.",
                                "replace": "The gap held."}],
                    "structural": []}

        good = review.model_review
        review.model_review = never_clean
        try:
            support.drop("looping-paper")
            support.run_engine("looping-paper")
            records = journal.load_records()
            for record in journal.sections_of(records, "looping-paper", 1):
                self.assertLessEqual(record.get("revisions", 0),
                                     config.EDIT_HARD_MAX_PASSES)
        finally:
            review.model_review = good

    def test_still_improving_reads_the_trajectory(self):
        self.assertTrue(section_level._still_improving([5, 4, 3]))
        self.assertFalse(section_level._still_improving([5, 2, 3, 3]))
        self.assertTrue(section_level._still_improving([5, 4, 3, 1]))
        self.assertTrue(section_level._still_improving([9]))


if __name__ == "__main__":
    unittest.main()
