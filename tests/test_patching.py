"""Revision as exact edits: the mechanism that makes "surgery" real.

The instruction has said *surgery, not authorship* since 2026-08-05; the mechanism was
a full rewrite, and across ~4,700 words a rewrite drifts. Chapter 3 of the first real
run went 3 -> 3 -> 4 -> 1 -> 2 -> 1 -> 1 -> 1 -> 1 and parked: six consecutive
attempts holding exactly one blocking issue, a DIFFERENT one each time, because every
pass fixed what was named and broke something else in the prose it was leaving alone.

These pin the property that fixes it — text nobody named is not rewritten by anything.
"""

import support                                                    # noqa: F401

import unittest                                                   # noqa: E402

from paperwriter.stages import patching                               # noqa: E402

CHAPTER = ("The birds stopped first. She held the door and did not move.\n\n"
           "Anne left the spoon on the desk and went down to let her in.\n\n"
           "The spoon was still in her hand when she reached the landing.\n")


class ApplyingEdits(unittest.TestCase):
    def test_a_unique_anchor_is_replaced_and_nothing_else_moves(self):
        out, applied, rejected = patching.apply_edits(CHAPTER, [
            {"find": "The spoon was still in her hand when she reached the landing.",
             "replace": "The desk was empty when she came back up."}])
        self.assertEqual(len(applied), 1)
        self.assertEqual(rejected, [])
        self.assertIn("The desk was empty", out)
        self.assertIn("The birds stopped first.", out,
                      "untouched prose must survive character for character")
        self.assertNotIn("still in her hand", out)

    def test_an_anchor_that_does_not_appear_is_rejected_not_guessed(self):
        _out, applied, rejected = patching.apply_edits(
            CHAPTER, [{"find": "a sentence that is not in the chapter",
                       "replace": "x"}])
        self.assertEqual(applied, [])
        self.assertIn("does not appear", rejected[0][1])

    def test_an_ambiguous_anchor_is_refused(self):
        """Two identical sentences in a chapter is ordinary; picking one is a guess,
        and guessing silently corrupts prose that already passed."""
        text = "She waited.\n\nSomething moved.\n\nShe waited.\n"
        out, applied, rejected = patching.apply_edits(
            text, [{"find": "She waited.", "replace": "She ran."}])
        self.assertEqual(applied, [])
        self.assertEqual(out, text, "an ambiguous edit must change nothing")
        self.assertIn("appears 2 times", rejected[0][1])

    def test_an_empty_replace_deletes(self):
        """Deleting a clause is the right fix for an impossible-knowledge problem."""
        out, applied, _ = patching.apply_edits(
            CHAPTER, [{"find": " and did not move", "replace": ""}])
        self.assertEqual(len(applied), 1)
        self.assertIn("She held the door.", out)

    def test_a_missing_replace_field_is_rejected(self):
        _out, applied, rejected = patching.apply_edits(
            CHAPTER, [{"find": "The birds stopped first."}])
        self.assertEqual(applied, [])
        self.assertIn("no `replace`", rejected[0][1])

    def test_good_edits_land_even_when_one_is_bad(self):
        """A critique naming three defects that gets two fixed has made progress;
        refusing the whole patch over one bad anchor spends an attempt on nothing."""
        out, applied, rejected = patching.apply_edits(CHAPTER, [
            {"find": "The birds stopped first.", "replace": "The birds went quiet."},
            {"find": "not in the chapter", "replace": "x"}])
        self.assertEqual(len(applied), 1)
        self.assertEqual(len(rejected), 1)
        self.assertIn("The birds went quiet.", out)

    def test_the_rejection_brief_names_the_anchor(self):
        _o, _a, rejected = patching.apply_edits(
            CHAPTER, [{"find": "nope", "replace": "x"}])
        brief = patching.rejection_brief(rejected)
        self.assertIn("nope", brief)
        self.assertIn("exactly once", brief)



if __name__ == "__main__":
    unittest.main()
