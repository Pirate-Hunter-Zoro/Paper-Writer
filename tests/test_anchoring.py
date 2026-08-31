"""The anchor state: where everyone is when the book opens.

Canon research collects what is true of a *series*. A story needs what is true at the
*moment it starts*, and only one of those documents was ever being written — which is
how a crossover set after four finales put Dipper Pines in his pine-tree cap and Wendy
Corduroy in her ushanka. They trade hats in the last episode. Thirty-one researched
Gravity Falls facts, ten mentioning one of the two, and the swap in none of them.

No gate could have caught it, because a gate cannot check a fact nobody collected.
These pin the stage that collects it.
"""

import support                                                    # noqa: F401

import unittest                                                   # noqa: E402

from fanfic import jobspec, paths, states                         # noqa: E402
from fanfic.infra import journal, storage                         # noqa: E402
from fanfic.stages import anchoring                               # noqa: E402

PROMPT = ("# Job\n\n## Source universe(s)\nGravity Falls\n\n"
          "## Canon anchor point\nAt the epilogue.\n\n"
          "## Main characters to feature\n"
          "Dipper Pines, Mabel Pines, Wendy Corduroy, Polly\nPlantar\n\n"
          "## Tone\nwarm\n")


def _record(name, **over):
    rec = {"name": name, "age": "17", "where": "Piedmont",
           "doing": "back at school", "wears": "Wendy's ushanka",
           "changed": "traded hats with Wendy", "gaps": ""}
    rec.update(over)
    return rec


class TheCastListItParsesFrom(unittest.TestCase):
    def test_a_name_wrapped_across_a_line_is_still_one_person(self):
        """"Polly\\nPlantar" split on newlines gives two characters, neither of whom
        exists. `implied_entities` was fixed for this exact defect once already."""
        names = jobspec.main_characters(PROMPT)
        self.assertIn("Polly Plantar", names)
        self.assertNotIn("Polly", names)
        self.assertNotIn("Plantar", names)

    def test_the_last_name_survives_the_full_stop_that_ends_the_list(self):
        """The final entry in every roster used to be dropped, silently and always.

        A cast list ends with a sentence, so the last chunk after the last comma is
        "Swift Wind." — which fails the name pattern on the trailing period and is
        discarded. It looks exactly like a deliberate omission, and the live crossover
        lost Swift Wind to it: named in the prompt, absent from the anchor gate's
        coverage check, so never gated for having a starting position at all."""
        prompt = PROMPT.replace("Polly\nPlantar\n", "Polly\nPlantar, Swift Wind.\n")
        names = jobspec.main_characters(prompt)
        self.assertIn("Swift Wind", names)
        self.assertNotIn("Swift Wind.", names)

    def test_it_stops_before_the_prose_that_follows_the_list(self):
        prompt = PROMPT.replace(
            "Dipper Pines, Mabel Pines, Wendy Corduroy, Polly\nPlantar\n",
            "Dipper Pines, Mabel Pines\n\nHonour every canon relationship exactly as "
            "the shows left it, and give each a real place in the book.\n")
        self.assertEqual(jobspec.main_characters(prompt),
                         ["Dipper Pines", "Mabel Pines"])


class TheGateThatWouldHaveCaughtTheHats(unittest.TestCase):
    def _errors(self, anchor, expected=("Dipper Pines",)):
        return anchoring._validate(anchor, list(expected))

    def test_a_complete_record_passes(self):
        anchor = {"anchor_summary": "Four years on.",
                  "characters": [_record("Dipper Pines")]}
        self.assertEqual(self._errors(anchor), [])

    def test_a_missing_field_is_rejected_by_name(self):
        """The absent field is always the one that turns up wrong three hundred pages
        later, so absence is the thing this gate is for."""
        for field in anchoring.REQUIRED:
            anchor = {"anchor_summary": "s",
                      "characters": [_record("Dipper Pines", **{field: ""})]}
            errors = self._errors(anchor)
            self.assertTrue(any(f"`{field}`" in e for e in errors),
                            f"a missing {field} must be named in the rejection")

    def test_a_principal_with_no_record_at_all_is_rejected(self):
        anchor = {"anchor_summary": "s", "characters": [_record("Dipper Pines")]}
        errors = self._errors(anchor, ("Dipper Pines", "Wendy Corduroy"))
        self.assertTrue(any("Wendy Corduroy" in e for e in errors))

    def test_an_empty_gaps_field_is_fine(self):
        """An honest blank is a different thing from a missing field: a recorded gap is
        something a human can fix, an invented fact is something nobody finds."""
        anchor = {"anchor_summary": "s",
                  "characters": [_record("Dipper Pines", gaps="")]}
        self.assertEqual(self._errors(anchor), [])

    def test_no_summary_is_rejected(self):
        anchor = {"anchor_summary": "", "characters": [_record("Dipper Pines")]}
        self.assertTrue(any("anchor_summary" in e for e in self._errors(anchor)))


class AnAgeIsANumberNotAComparison(unittest.TestCase):
    """The one anchor field checked for shape rather than presence.

    Every principal of the first book carried an age and not one was usable — "Young
    adult, four years on from the fourteen-year-old who first fell into the Demon
    Realm", "the same cohort as Luz". A comparison names a direction and never a
    distance, so an image model starts at the thing compared to and guesses how far to
    go. It guessed a decade too far on every page Luz Noceda appears."""

    def test_a_plain_number_is_accepted_in_every_shape_it_arrives_in(self):
        for value, want in ((18, 18), ("18", 18), ("18 years old", 18), (" 42 ", 42)):
            self.assertEqual(anchoring.parse_age(value), want, repr(value))

    def test_a_comparison_is_refused(self):
        for value in ("Young adult, four years on from the fourteen-year-old",
                      "the same cohort as Luz",
                      "four years older than the Owl Lady of the series proper"):
            self.assertIsNone(anchoring.parse_age(value), repr(value))

    def test_a_life_stage_or_a_range_is_refused(self):
        for value in ("Adult", "young adult", "teens", "17-19", "", None, 0):
            self.assertIsNone(anchoring.parse_age(value), repr(value))

    def test_the_gate_names_the_character_and_shows_what_it_got(self):
        anchor = {"anchor_summary": "after the finales",
                  "characters": [_record("Dipper Pines", age="Young adult, four "
                                         "years on from the boy who left")]}
        errors = anchoring._validate(anchor, ["Dipper Pines"])
        self.assertTrue(any("Dipper Pines" in e and "usable `age`" in e
                            for e in errors), errors)

    def test_a_numeric_age_clears_the_gate(self):
        anchor = {"anchor_summary": "after the finales",
                  "characters": [_record("Dipper Pines", age=17)]}
        self.assertEqual(anchoring._validate(anchor, ["Dipper Pines"]), [])

    def test_the_block_the_planner_reads_carries_the_number(self):
        """Planning copies this block into the plan's own `age`, and the plan gate
        demands a number — so the block must render one rather than the raw field."""
        import support
        from fanfic import paths
        from fanfic.infra import storage
        support.wipe_state()
        storage.save_json(
            {"anchor_summary": "s",
             "characters": [_record("Dipper Pines", age="17 years old")]},
            paths.anchor_path("age-block"))
        self.assertIn("Dipper Pines (17)", anchoring.block("age-block"))


class ItReachesTheStagesThatNeedIt(unittest.TestCase):
    def setUp(self):
        support.wipe_state()
        self.sid = "anchored"
        storage.save_json(
            {"anchor_summary": "Four years after the finale.",
             "characters": [
                 _record("Dipper Pines", wears="Wendy's blue-grey ushanka; "
                                               "taller than Mabel now"),
                 _record("Wendy Corduroy", wears="Dipper's pine-tree hat")]},
            paths.anchor_path(self.sid))

    def test_the_block_carries_every_field_and_says_it_outranks_canon(self):
        block = anchoring.block(self.sid)
        self.assertIn("ushanka", block)
        self.assertIn("pine-tree hat", block)
        self.assertIn("OVERRIDES", block)
        self.assertIn("Four years after the finale.", block)

    def test_a_chapter_slice_carries_only_its_own_cast(self):
        one = anchoring.for_characters(self.sid, ["Wendy Corduroy"])
        self.assertIn("pine-tree hat", one)
        self.assertNotIn("ushanka", one)

    def test_a_series_with_no_anchor_degrades_silently(self):
        """Older series predate the stage; they must fall back to the previous brief
        rather than growing an empty section that reads as a missing promise."""
        self.assertEqual(anchoring.block("never-anchored"), "")
        self.assertEqual(anchoring.for_characters("never-anchored", ["X"]), "")


class ItRunsBeforePlanning(unittest.TestCase):
    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()

    def test_the_series_machine_pins_the_anchor_then_plans(self):
        sid = "ordering"
        support.drop(sid)
        self.assertEqual(support.run_engine(sid), states.SERIES_COMPLETE)
        # The anchor is on disk and the plan came after it.
        self.assertTrue(paths.anchor_path(sid).exists())
        seen = [r["status"] for r in journal.iter_history()
                if r.get("key") == journal.series_key(sid)]
        self.assertIn(states.ANCHORED, seen)
        self.assertLess(seen.index(states.ANCHORED), seen.index(states.SERIES_PLANNED))


if __name__ == "__main__":
    unittest.main()
