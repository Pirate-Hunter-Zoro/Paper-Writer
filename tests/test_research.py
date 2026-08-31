"""Research, and the one thing that makes a multi-book programme in one universe work.

Canon is keyed on the UNIVERSE, not the series, so every job naming the same source
shares one file. That is worth 15-40 minutes a book and it is the reason a thirteen-book
programme set in one universe mines its wikis once.

It was also, until this module existed, a trap that would have stalled every book after
the first. The freeze was absolute — a second job in the same universe reused the file
unconditionally — while the coverage gate still ran against *that job's* cast. A Star
Wars programme whose first book mined Jedi Knight canon parks its Bounty Hunter book at
0%: Mako and Torian Cadera are simply not in a file about the Jedi Order. The error says
"research", the cause is "the freeze", and the two are three steps apart.

So canon grows. These tests pin that it grows *correctly* — additively, without
duplicate ids, without re-mining what is already there, and without looping forever on
an entity no wiki can cover.
"""

import support                                    # noqa: F401  (redirects state first)

import unittest

from fanfic import config, paths
from fanfic.infra import storage
from fanfic.memory.bible import validate_canon
from fanfic.stages import research

UNIVERSE = "Star Wars: The Old Republic"


def _fact(n, subject):
    return {"id": f"c.{n}", "category": "character", "subject": subject,
            "text": f"{subject} is an established character.", "citation": "wiki"}


def _prompt(characters, anchor="The Great Hunt on Hutta."):
    return (f"## Source universe(s)\n{UNIVERSE}\n\n"
            f"## Main characters to feature\n{characters}\n\n"
            f"## Canon anchor point\n{anchor}\n")


class CanonGrowsRatherThanStalling(unittest.TestCase):
    """The regression that would have hit at book 2 of a thirteen-book programme."""

    def setUp(self):
        support.wipe_state()
        self.mined = []
        self._real = research.propose_canon

        def fake_propose(prompt_text, universe, out_path, log_fn=None, focus=()):
            # Record what each call was asked for, which is the whole point: a top-up
            # that re-surveys the universe costs a full research call to move coverage
            # a few points, and looks identical to one that did the right thing.
            self.mined.append(list(focus))
            # A full survey covers everything the prompt implies — including the
            # entities the *anchor* section contributes, like "Jedi Order" and
            # "Tython", which real research would also cover. A stub that covered only
            # the character list would trigger a top-up on the very first job.
            from fanfic import jobspec
            names = list(focus) or jobspec.implied_entities(prompt_text)
            storage.save_json(
                {"universe": universe,
                 "facts": [_fact(i, name) for i, name in enumerate(names)]},
                out_path)
            return "stubbed research"
        research.propose_canon = fake_propose

    def tearDown(self):
        research.propose_canon = self._real

    def _run(self, prompt_text):
        return research.run({"prompt_text": prompt_text}, log_fn=lambda _m: None)

    def _canon(self):
        return storage.load_json(paths.canon_path(UNIVERSE), {})

    def test_the_first_book_mines_the_universe_and_freezes_it(self):
        result = self._run(_prompt("Kira Carsen, Darth Angral.",
                                   anchor="The Jedi Order on Tython."))
        self.assertEqual(result["universes"], [UNIVERSE])
        self.assertEqual(self.mined, [[]], "the first dig is a full survey, not a top-up")
        self.assertTrue(self._canon().get("frozen"))

    def test_a_second_book_with_the_same_cast_re_mines_nothing(self):
        """The saving that makes one shared canon worth having at all."""
        prompt = _prompt("Kira Carsen, Darth Angral.", anchor="The Jedi Order on Tython.")
        self._run(prompt)
        self.mined.clear()
        self._run(prompt)
        self.assertEqual(self.mined, [], "a covered prompt must not spend a research call")

    def test_a_second_book_with_a_different_cast_tops_up_instead_of_parking(self):
        """THE regression. Book 1 is the Jedi Knight; book 5 is the Bounty Hunter, and
        none of its companions are in a file about the Jedi Order. Before canon could
        grow, this raised `canon coverage 0% below 85% floor`."""
        self._run(_prompt("Kira Carsen, Darth Angral.", anchor="The Jedi Order on Tython."))
        self.mined.clear()

        result = self._run(_prompt("Mako, Torian Cadera, Gault Rennow, Blizz."))

        self.assertEqual(len(self.mined), 1, "exactly one top-up call")
        asked_for = set(self.mined[0])
        self.assertIn("Torian Cadera", asked_for)
        self.assertIn("Gault Rennow", asked_for)
        self.assertNotIn("Kira Carsen", asked_for,
                         "a top-up must not re-request what canon already covers")
        self.assertGreaterEqual(result["coverage"], config.CANON_COVERAGE_MIN)

    def test_the_top_up_is_merged_and_the_old_facts_survive(self):
        """Merged, not replaced. Book 1's canon has to still be there for book 1's
        chapters, which are drafted long after book 5 has run."""
        self._run(_prompt("Kira Carsen, Darth Angral.", anchor="The Jedi Order on Tython."))
        before = {f["subject"] for f in self._canon()["facts"]}

        self._run(_prompt("Mako, Torian Cadera, Gault Rennow, Blizz."))
        after = {f["subject"] for f in self._canon()["facts"]}

        self.assertTrue(before <= after, "topping up discarded earlier canon")
        self.assertIn("Torian Cadera", after)

    def test_merged_canon_keeps_unique_ids_and_stays_valid(self):
        """A top-up numbers its facts from `c.1` like every research call, with no idea
        what is on disk. A duplicate id fails `validate_canon`, which would turn a
        successful top-up into a parked job — so the merge renumbers."""
        self._run(_prompt("Kira Carsen, Darth Angral.", anchor="The Jedi Order on Tython."))
        self._run(_prompt("Mako, Torian Cadera, Gault Rennow, Blizz."))

        doc = self._canon()
        ids = [f["id"] for f in doc["facts"]]
        self.assertEqual(len(ids), len(set(ids)), f"duplicate fact ids: {ids}")
        ok, errors = validate_canon(doc)
        self.assertTrue(ok, errors)

    def test_canon_stays_frozen_across_a_top_up(self):
        self._run(_prompt("Kira Carsen, Darth Angral.", anchor="The Jedi Order on Tython."))
        self._run(_prompt("Mako, Torian Cadera, Gault Rennow, Blizz."))
        self.assertTrue(self._canon().get("frozen"))

    def test_an_uncoverable_entity_costs_one_call_and_then_parks(self):
        """The top-up is bounded. An entity no wiki has must not become a loop that
        spends a research call every cycle forever — it should cost one attempt and
        then park with a message naming what is missing."""
        self._run(_prompt("Kira Carsen, Darth Angral.", anchor="The Jedi Order on Tython."))
        self.mined.clear()

        def barren(prompt_text, universe, out_path, log_fn=None, focus=()):
            self.mined.append(list(focus))
            storage.save_json({"universe": universe, "facts": []}, out_path)
            return "found nothing"
        research.propose_canon = barren

        with self.assertRaises(RuntimeError) as caught:
            self._run(_prompt("Grubnar the Entirely Invented, Fnord Blapp."))
        self.assertEqual(len(self.mined), 1, "one top-up attempt, not a loop")
        message = str(caught.exception)
        self.assertIn("coverage", message)
        self.assertIn("topping up", message)


class MergeCanon(unittest.TestCase):
    """The merge itself, as pure arithmetic on documents."""

    def test_new_facts_are_appended_under_fresh_ids(self):
        existing = {"universe": UNIVERSE, "frozen": True,
                    "facts": [_fact(0, "Kira Carsen"), _fact(1, "Darth Angral")]}
        addition = {"facts": [_fact(0, "Mako"), _fact(1, "Blizz")]}
        merged = research.merge_canon(existing, addition)

        ids = [f["id"] for f in merged["facts"]]
        self.assertEqual(len(ids), 4)
        self.assertEqual(len(set(ids)), 4)
        self.assertEqual([f["subject"] for f in merged["facts"]][:2],
                         ["Kira Carsen", "Darth Angral"], "existing order preserved")

    def test_it_does_not_mutate_the_document_it_was_given(self):
        existing = {"universe": UNIVERSE, "frozen": True, "facts": [_fact(0, "Kira")]}
        research.merge_canon(existing, {"facts": [_fact(0, "Mako")]})
        self.assertEqual(len(existing["facts"]), 1)

    def test_an_empty_top_up_changes_nothing(self):
        existing = {"universe": UNIVERSE, "frozen": True, "facts": [_fact(0, "Kira")]}
        merged = research.merge_canon(existing, {"facts": []})
        self.assertEqual(merged["facts"], existing["facts"])

    def test_a_fact_with_no_id_is_given_one(self):
        """Not hypothetical: a model that omits an id would otherwise fail
        `validate_canon` and park a job over a missing field the merge can supply."""
        existing = {"universe": UNIVERSE, "frozen": True, "facts": [_fact(0, "Kira")]}
        merged = research.merge_canon(
            existing, {"facts": [{"category": "character", "subject": "Mako",
                                  "text": "Mako is a slicer.", "citation": "wiki"}]})
        self.assertTrue(all(f.get("id") for f in merged["facts"]))
        ok, errors = validate_canon(merged)
        self.assertTrue(ok, errors)


if __name__ == "__main__":
    unittest.main()
