"""The bible merge gatekeeper.

This is the one function that stands between a confidently wrong model and a
corrupted ledger, so every invariant it enforces gets its own failing case — and
every rejection is checked to leave the committed bible untouched.
"""

import unittest

import support                                                    # noqa: F401

from fanfic.memory import bible                                   # noqa: E402
from fanfic.memory import digest                                  # noqa: E402
from fanfic.memory.digest import build_chapter_digest             # noqa: E402


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.canon = bible.new_canon("RWBY")
        self.canon["facts"] = [
            {"id": "c.silver_eyes", "category": "power", "subject": "Ruby",
             "text": "Silver-eyed warriors can petrify Grimm.",
             "citation": "RWBY wiki: Silver-Eyed Warriors"},
        ]
        self.bible = bible.new_series_bible("rwby-01")
        self.bible["characters"]["Ruby"] = bible.new_character(
            "Ruby", appearance="red cloak, silver eyes", palette=["#b30000"])

    def test_valid_update_merges_without_touching_the_original(self):
        ok, errors, merged = bible.merge_bible_update(self.bible, self.canon, {
            "new_facts": [{"id": "f.vacuo_rally", "text": "RWBY rallied Vacuo.",
                           "source": "book1/ch3"}],
            "new_threads": [{"id": "t.relic", "description": "The last Relic",
                             "setup_book": 1, "setup_chapter": 3}],
            "character_locks": ["Ruby"],
        })
        self.assertTrue(ok, errors)
        self.assertTrue(merged["characters"]["Ruby"]["ref_sheet_locked"])
        self.assertEqual(len(bible.open_threads(merged)), 1)
        self.assertFalse(self.bible["characters"]["Ruby"]["ref_sheet_locked"])

    def test_new_fact_cannot_collide_with_canon(self):
        ok, _, returned = bible.merge_bible_update(self.bible, self.canon, {
            "new_facts": [{"id": "c.silver_eyes", "text": "wrong", "source": "x"}]})
        self.assertFalse(ok)
        self.assertIs(returned, self.bible)      # rejected: original, unchanged

    def test_payoff_without_setup_is_rejected(self):
        ok, errors, _ = bible.merge_bible_update(self.bible, self.canon, {
            "pay_offs": [{"id": "t.ghost", "payoff_book": 1, "payoff_chapter": 9}]})
        self.assertFalse(ok)
        self.assertTrue(any("no prior setup" in e for e in errors))

    def test_a_thread_cannot_be_paid_twice(self):
        _, _, with_setup = bible.merge_bible_update(self.bible, self.canon, {
            "new_threads": [{"id": "t.relic", "setup_book": 1, "setup_chapter": 3}]})
        payoff = {"pay_offs": [{"id": "t.relic", "payoff_book": 1,
                                "payoff_chapter": 8}]}
        ok, _, paid = bible.merge_bible_update(with_setup, self.canon, payoff)
        self.assertTrue(ok)
        ok, errors, _ = bible.merge_bible_update(paid, self.canon, payoff)
        self.assertFalse(ok)
        self.assertTrue(any("already paid" in e for e in errors))

    def test_a_locked_character_cannot_be_redescribed(self):
        ok, _, locked = bible.merge_bible_update(
            self.bible, self.canon, {"character_locks": ["Ruby"]})
        self.assertTrue(ok)
        ok, errors, _ = bible.merge_bible_update(locked, self.canon, {
            "new_characters": [bible.new_character(
                "Ruby", appearance="BLONDE hair now", palette=["#ffffff"])]})
        self.assertFalse(ok)
        self.assertTrue(any("locked" in e for e in errors))


class DigestTests(unittest.TestCase):
    """The writer must be handed a slice, not the library: the previous chapter's exit
    state, this chapter's beats, only the canon that names its cast, and the payoffs
    actually due."""

    def setUp(self):
        self.series_bible = bible.new_series_bible("rwby-01")
        self.series_bible["characters"]["Ruby"] = bible.new_character(
            "Ruby", appearance="red cloak, silver eyes")
        self.series_bible["foreshadowing"] = [
            {"id": "t.relic", "description": "The last Relic", "status": "open"},
            {"id": "t.other", "description": "An unrelated promise", "status": "open"},
        ]
        self.canon = {"RWBY": {"facts": [
            {"id": "c.1", "subject": "Ruby", "text": "Ruby wields Crescent Rose.",
             "citation": "wiki"},
            {"id": "c.2", "subject": "Jaune", "text": "Jaune leads JNPR.",
             "citation": "wiki"},
        ]}}

    def _digest(self, **overrides):
        chapter = {"number": 4, "beats": "Ruby reaches the vault.",
                   "exit_state": "Relic in hand", "characters": ["Ruby"],
                   "pays_off": ["t.relic"]}
        chapter.update(overrides)
        return build_chapter_digest(chapter, "Ruby entered the tunnels",
                                    self.series_bible, self.canon,
                                    "third-person limited", 4000)

    def test_carries_continuity_forward_and_scopes_canon_to_the_cast(self):
        digest = self._digest()
        self.assertIn("Ruby entered the tunnels", digest)     # previous exit state
        self.assertIn("Relic in hand", digest)                # this chapter's target
        self.assertIn("Crescent Rose", digest)                # canon naming the cast
        self.assertNotIn("JNPR", digest)                      # canon that does not

    def test_marks_only_the_payoffs_due_here(self):
        digest = self._digest()
        due = next(line for line in digest.splitlines() if "t.relic" in line)
        keep = next(line for line in digest.splitlines() if "t.other" in line)
        self.assertIn("PAY OFF HERE", due)
        self.assertIn("keep open", keep)

    def test_opening_chapter_says_so_rather_than_leaving_a_blank(self):
        digest = build_chapter_digest(
            {"number": 1, "beats": "b", "characters": []}, "",
            self.series_bible, self.canon, "style", 4000)
        self.assertIn("opening chapter", digest)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TheWriterSeesWhatTheCriticJudges(unittest.TestCase):
    """A generator and its judge reading different sources for the same fact is a
    loop that cannot converge.

    The project recorded this on 2026-08-05 about the previous chapter's exit state.
    It recurred on 2026-08-09 in a different field: the judge's ground truth carried
    the story timeline and the established series facts, and the writer's brief
    carried neither. Chapter 7 took eight attempts, and nearly every blocking issue
    was relative-time arithmetic the writer had no way to get right — how many days
    since the storm, when the welts appeared, how long since Weirdmageddon.
    """

    def _bible(self):
        return {
            "characters": {},
            "foreshadowing": [],
            "timeline": [{"index": 0, "book": 1, "chapter": 2,
                          "event": "the boiling-rain storm begins over Gravity Falls"}],
            "facts": [{"id": "f.welts",
                       "text": "Soos's welts appeared four days after the storm"}],
        }

    def _digest(self):
        return digest.build_chapter_digest(
            {"number": 7, "beats": "b", "exit_state": "e", "characters": [],
             "pays_off": []},
            "prev exit", self._bible(), {}, "past tense", 5351)

    def test_the_timeline_reaches_the_writer(self):
        self.assertIn("the boiling-rain storm begins", self._digest())

    def test_established_facts_reach_the_writer(self):
        self.assertIn("Soos's welts appeared four days", self._digest())

    def test_both_documents_agree_on_these_fields(self):
        """The invariant, stated directly: anything the critic checks a chapter
        against must be visible to whoever wrote the chapter."""
        chapter = {"number": 7, "beats": "b", "exit_state": "e", "characters": [],
                   "pays_off": []}
        bible = self._bible()
        writer = digest.build_chapter_digest(chapter, "prev", bible, {},
                                             "past tense", 5351)
        judge = digest.build_ground_truth(chapter, bible, {})
        for fact in (bible["facts"][0]["text"], bible["timeline"][0]["event"]):
            self.assertIn(fact, judge)
            self.assertIn(fact, writer,
                          "the writer is judged on this and must be shown it")
