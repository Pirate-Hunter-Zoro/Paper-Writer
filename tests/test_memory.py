"""The three-layer memory: the schemas, the gatekeeper, and the writer's brief.

The gatekeeper is the part worth testing hardest. It is the only thing that decides
whether a model's proposal becomes committed state, and its one non-negotiable property
is that it applies all of a proposal or none of it — a half-applied bad proposal is
worse than a rejected one, because nothing downstream can tell which half landed.
"""

import support                                                      # noqa: F401
import unittest                                                     # noqa: E402

from paperwriter.memory import digest, ledger                       # noqa: E402


def _evidence():
    return {"corpus": "fixture", "frozen": True, "items": [
        {"id": "e.1", "statement": "AUC was 0.7429", "values": [0.7429],
         "source": "results/metrics.json"},
        {"id": "e.2", "statement": "the cohort held 8516 patients", "values": [8516],
         "source": "results/cohort.json"},
    ], "also_allow": []}


def _ledger():
    doc = ledger.new_project_ledger("fixture")
    doc["terminology"] = [
        ledger.new_term("feature representation", aliases=["rule-based"],
                        definition="The typed feature vector."),
    ]
    doc["claims"]["c.1"] = ledger.new_claim(
        "c.1", "text beats features", kind="comparative", evidence=["e.1"],
        headline=True)
    doc["conventions"] = {"person": "we"}
    doc["references"] = {"1": {"title": "A prior study", "year": 2024}}
    return doc


class EvidenceSchemaTests(unittest.TestCase):

    def test_a_valid_document_passes(self):
        ok, errors = ledger.validate_evidence(_evidence())
        self.assertTrue(ok, errors)

    def test_an_item_with_no_source_is_refused(self):
        doc = _evidence()
        doc["items"][0].pop("source")
        ok, errors = ledger.validate_evidence(doc)
        self.assertFalse(ok)
        self.assertTrue(any("provenance" in e for e in errors))

    def test_a_duplicate_id_is_refused(self):
        doc = _evidence()
        doc["items"][1]["id"] = "e.1"
        self.assertFalse(ledger.validate_evidence(doc)[0])

    def test_a_non_numeric_value_is_refused(self):
        doc = _evidence()
        doc["items"][0]["values"] = ["about 0.74"]
        self.assertFalse(ledger.validate_evidence(doc)[0])


class TerminologyLockTests(unittest.TestCase):

    def test_a_lock_nothing_can_satisfy_is_refused(self):
        """One word forbidden on behalf of two terms means whichever term the writer
        uses, the other one's gate fires. Better caught here than in a loop that never
        converges."""
        lock = [ledger.new_term("A", aliases=["x"]), ledger.new_term("B", aliases=["x"])]
        ok, errors = ledger.validate_terminology(lock)
        self.assertFalse(ok)
        self.assertTrue(any("has to give it up" in e for e in errors))

    def test_a_term_that_is_another_terms_alias_is_refused(self):
        lock = [ledger.new_term("A", aliases=["B"]), ledger.new_term("B")]
        self.assertFalse(ledger.validate_terminology(lock)[0])

    def test_an_alias_of_itself_is_refused(self):
        self.assertFalse(
            ledger.validate_terminology([ledger.new_term("A", aliases=["a"])])[0])


class GatekeeperTests(unittest.TestCase):

    def test_a_clean_update_merges(self):
        ok, errors, merged = ledger.merge_ledger_update(_ledger(), _evidence(), {
            "support": ["c.1"],
            "new_facts": [{"id": "f.1", "text": "the split was drawn once",
                           "source": "Methods"}],
        })
        self.assertTrue(ok, errors)
        self.assertEqual(merged["claims"]["c.1"]["status"], "supported")
        self.assertEqual(len(merged["facts"]), 1)

    def test_the_original_is_untouched_on_rejection(self):
        """The property everything else rests on: a refused proposal changes nothing,
        and it changes nothing in part."""
        before = _ledger()
        ok, _errors, after = ledger.merge_ledger_update(before, _evidence(), {
            "new_facts": [{"id": "f.1", "text": "good", "source": "x"}],
            "settled": [{"id": "q.9", "settled_in": "Discussion"}],
        })
        self.assertFalse(ok)
        self.assertIs(after, before)
        self.assertEqual(before["facts"], [])

    def test_a_claim_citing_evidence_that_does_not_exist_is_refused(self):
        ok, errors, _ = ledger.merge_ledger_update(_ledger(), _evidence(), {
            "new_claims": [{"id": "c.2", "claim": "something", "evidence": ["e.9"]}]})
        self.assertFalse(ok)
        self.assertTrue(any("does not exist" in e for e in errors))

    def test_a_claim_with_no_evidence_is_refused(self):
        ok, errors, _ = ledger.merge_ledger_update(_ledger(), _evidence(), {
            "new_claims": [{"id": "c.2", "claim": "something", "evidence": []}]})
        self.assertFalse(ok)
        self.assertTrue(any("rests on no evidence" in e for e in errors))

    def test_a_committed_claim_cannot_change_meaning(self):
        """The outline placed sections against these claims. A claim that changes
        meaning after placement leaves a section arguing for something else."""
        ok, errors, _ = ledger.merge_ledger_update(_ledger(), _evidence(), {
            "new_claims": [{"id": "c.1", "claim": "features beat text",
                            "evidence": ["e.1"]}]})
        self.assertFalse(ok)
        self.assertTrue(any("new id" in e for e in errors))

    def test_settling_a_question_that_was_never_raised_is_refused(self):
        ok, _errors, _ = ledger.merge_ledger_update(_ledger(), _evidence(), {
            "settled": [{"id": "q.1", "settled_in": "Discussion"}]})
        self.assertFalse(ok)

    def test_a_question_cannot_be_settled_twice(self):
        doc = _ledger()
        _ok, _e, doc = ledger.merge_ledger_update(doc, _evidence(), {
            "new_questions": [{"id": "q.1", "question": "does it transfer",
                               "raised_in": "Methods"}]})
        ok, _e, doc = ledger.merge_ledger_update(doc, _evidence(), {
            "settled": [{"id": "q.1", "settled_in": "Discussion"}]})
        self.assertTrue(ok)
        ok, errors, _ = ledger.merge_ledger_update(doc, _evidence(), {
            "settled": [{"id": "q.1", "settled_in": "Conclusions"}]})
        self.assertFalse(ok)
        self.assertTrue(any("already settled" in e for e in errors))

    def test_a_reference_key_cannot_be_repointed(self):
        """Two different papers under one key is a citation that points at whichever
        was written last, and nothing downstream can see it happen."""
        ok, errors, _ = ledger.merge_ledger_update(_ledger(), _evidence(), {
            "new_references": {"1": {"title": "A different study", "year": 2025}}})
        self.assertFalse(ok)
        self.assertTrue(any("own key" in e for e in errors))

    def test_a_reference_may_be_extended(self):
        ok, errors, merged = ledger.merge_ledger_update(_ledger(), _evidence(), {
            "new_references": {"1": {"doi": "10.1/xyz"}}})
        self.assertTrue(ok, errors)
        self.assertEqual(merged["references"]["1"]["title"], "A prior study")
        self.assertEqual(merged["references"]["1"]["doi"], "10.1/xyz")

    def test_a_convention_cannot_be_changed_in_a_merge(self):
        """Half a manuscript in one voice is a thing reviewers notice and authors do
        not. Changing it is a decision, not a side effect of extracting a section."""
        ok, errors, _ = ledger.merge_ledger_update(_ledger(), _evidence(), {
            "conventions": {"person": "the authors"}})
        self.assertFalse(ok)
        self.assertTrue(any("already fixed" in e for e in errors))

    def test_an_unchanged_convention_is_not_a_conflict(self):
        ok, _errors, _ = ledger.merge_ledger_update(_ledger(), _evidence(), {
            "conventions": {"person": "we", "tense": "past"}})
        self.assertTrue(ok)

    def test_supporting_a_claim_that_does_not_exist_is_refused(self):
        ok, _errors, _ = ledger.merge_ledger_update(_ledger(), _evidence(),
                                                    {"support": ["c.9"]})
        self.assertFalse(ok)


class BriefTests(unittest.TestCase):
    """The writer's brief. Everything the gates later enforce has to be IN it — a gate
    that refuses something the brief never mentioned is a gate that costs a pass to
    teach."""

    SECTION = {
        "number": 4, "heading": "Results", "words": 600,
        "claims": ["c.1"], "evidence": ["e.2"],
        "paragraphs": [{"topic": "The embedded representation did better.",
                        "evidence": ["e.1"], "closes": "what that means"}],
        "exit_state": "the reader accepts the gap",
    }

    def _brief(self):
        return digest.build_section_brief(
            self.SECTION, "the Methods described the split", _ledger(), _evidence())

    def test_the_exact_numbers_are_quoted(self):
        self.assertIn("0.7429", self._brief())

    def test_the_forbidden_alias_is_named(self):
        self.assertIn("rule-based", self._brief())

    def test_the_paragraph_plan_carries_its_topic_sentence(self):
        self.assertIn("The embedded representation did better.", self._brief())

    def test_the_budget_is_stated_as_a_ceiling(self):
        brief = self._brief()
        self.assertIn("600 words", brief)
        self.assertIn("ceiling", brief)

    def test_a_missing_evidence_id_is_named_rather_than_silently_dropped(self):
        section = dict(self.SECTION, evidence=["e.9"])
        brief = digest.build_section_brief(section, "", _ledger(), _evidence())
        self.assertIn("MISSING", brief)
        self.assertIn("Do not invent", brief)

    def test_ground_truth_carries_the_open_questions(self):
        doc = _ledger()
        doc["questions"] = [{"id": "q.1", "question": "does it transfer",
                             "status": "open"}]
        truth = digest.build_ground_truth(self.SECTION, doc, _evidence())
        self.assertIn("does it transfer", truth)
        self.assertIn("may not assert an answer", truth)


if __name__ == "__main__":
    unittest.main()
