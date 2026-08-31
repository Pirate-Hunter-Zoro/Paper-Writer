"""Scene segmentation, and the one interaction that had to be checked before it
landed: whether break markers cost the editorial loop its repair anchors.

That check is first in this file for the same reason it was first in the work order.
The editor's entire mechanism is a `find` copied character-for-character out of the
chapter and applied only when it matches exactly once. If break lines made anchors
ambiguous, repairs would start being refused and the editorial loop would degrade
silently — a chapter getting worse with every pass and nothing in the log saying why.
"""

import unittest

import support                                                   # noqa: F401
from fanfic import paths
from fanfic.gates import segments
from fanfic.stages import binding, illustration, patching


class BreakMarkersDoNotCostTheEditorItsAnchors(unittest.TestCase):
    """The highest-risk interaction in the scene-break change, checked directly."""

    CHAPTER = ("Luz set the plate down and did not look at him.\n"
               "\n"
               "* * *\n"
               "\n"
               "The workshop smelled of sawdust and cold iron.\n"
               "\n"
               "* * *\n"
               "\n"
               "By morning the storm had taken the fence.\n")

    def test_an_ordinary_prose_anchor_still_applies(self):
        prose, applied, rejected = patching.apply_edits(self.CHAPTER, [
            {"find": "smelled of sawdust", "replace": "smelled of sawdust, varnish"}])
        self.assertEqual(len(applied), 1)
        self.assertEqual(rejected, [])
        self.assertIn("sawdust, varnish", prose)
        self.assertEqual(prose.count(segments.MARKER), 2,
                         "and the breaks are untouched")

    def test_an_anchor_spanning_a_break_applies_when_it_is_unique(self):
        """Whitespace and marker text are ordinary characters to the patcher."""
        find = "did not look at him.\n\n* * *\n\nThe workshop"
        prose, applied, rejected = patching.apply_edits(
            self.CHAPTER, [{"find": find,
                            "replace": "did not look at him.\n\n* * *\n\nThe shed"}])
        self.assertEqual(len(applied), 1)
        self.assertIn("The shed smelled", prose)

    def test_a_bare_marker_anchor_is_refused_rather_than_guessed_at(self):
        """The protection every repeated sentence already had, doing its job here.

        A marker appears many times, so an edit anchored on one alone is ambiguous —
        and ambiguous is refused, never applied to the first match. That is the
        property that makes break lines safe to introduce."""
        prose, applied, rejected = patching.apply_edits(
            self.CHAPTER, [{"find": "* * *", "replace": ""}])
        self.assertEqual(applied, [])
        self.assertEqual(len(rejected), 1)
        self.assertIn("appears 2 times", rejected[0][1])
        self.assertEqual(prose, self.CHAPTER, "and nothing moved")

    def test_a_break_can_be_added_by_an_ordinary_edit(self):
        """Which is what lets an unsegmented chapter be repaired instead of redrafted."""
        flat = "She closed the door.\n\nThe hall was colder than the room.\n"
        prose, applied, _ = patching.apply_edits(flat, [
            {"find": "She closed the door.",
             "replace": "She closed the door.\n\n* * *"}])
        self.assertEqual(len(applied), 1)
        self.assertEqual(len(segments.split(prose)), 2)


class WhatCountsAsABreak(unittest.TestCase):

    def test_the_conventional_forms_are_accepted(self):
        for line in ("* * *", "***", "   ***   ", "---", "###", "~~~", "* * * *"):
            self.assertTrue(segments.is_marker(line), line)

    def test_prose_and_markup_are_not_breaks(self):
        for line in ("", "*", "**", "**bold**", "She said *nothing*.",
                     "— he began", "# Chapter One", "-- wait"):
            self.assertFalse(segments.is_marker(line), repr(line))


class SplittingAChapter(unittest.TestCase):

    def test_segments_are_the_text_between_the_marks(self):
        parts = segments.split("one\n\n* * *\n\ntwo\n\n***\n\nthree")
        self.assertEqual(parts, ["one", "two", "three"])

    def test_doubled_and_edge_markers_make_no_empty_segments(self):
        parts = segments.split("* * *\none\n* * *\n* * *\ntwo\n* * *\n")
        self.assertEqual(parts, ["one", "two"])

    def test_an_unmarked_chapter_is_one_segment(self):
        self.assertEqual(segments.split("just prose"), ["just prose"])

    def test_stripping_leaves_the_prose_alone(self):
        self.assertEqual(segments.strip_markers("a\n* * *\nb"), "a\nb")


class TheSegmentGate(unittest.TestCase):

    def test_an_unsegmented_chapter_fails(self):
        report = segments.check("Five settings, no separators, one block of prose.")
        self.assertFalse(report.passed)
        self.assertEqual(report.segments, 1)
        self.assertIn("* * *", report.reason)

    def test_a_segmented_chapter_passes(self):
        report = segments.check("one\n* * *\ntwo")
        self.assertTrue(report.passed)
        self.assertEqual(report.segments, 2)


class ChoosingWhichSegmentsGetDrawn(unittest.TestCase):

    def test_every_segment_when_the_budget_allows(self):
        self.assertEqual(illustration.segments_to_draw(4, 5), [0, 1, 2, 3])

    def test_a_tight_cap_spreads_across_the_chapter_rather_than_the_front(self):
        picked = illustration.segments_to_draw(8, 3)
        self.assertEqual(len(picked), 3)
        self.assertEqual(picked[0], 0)
        self.assertEqual(picked[-1], 7, "the end of the chapter is not left bare")

    def test_a_required_segment_survives_the_cap(self):
        """A chapter delivering a character's escalation owes that picture; dropping
        it to stay under a ceiling defeats the reason it was mandatory."""
        picked = illustration.segments_to_draw(9, 2, required=[7])
        self.assertIn(7, picked)
        self.assertEqual(len(picked), 2)

    def test_nothing_to_draw_is_not_an_error(self):
        self.assertEqual(illustration.segments_to_draw(0, 3), [])


class PicturesArePlacedInTheirOwnScene(unittest.TestCase):
    """The placement half. Every figure used to be concatenated after the chapter's
    last paragraph, so the reader met the dinner twelve pages after the dinner."""

    def setUp(self):
        support.wipe_state()
        self.sid = "placement"
        self.prose = "ONE\n\n* * *\n\nTWO\n\n* * *\n\nTHREE"
        directory = paths.images_dir(self.sid, 1)
        directory.mkdir(parents=True, exist_ok=True)
        for k in (1, 3):
            (directory / f"ch01_{k}.png").write_bytes(support.PNG)

    def test_each_figure_lands_at_the_end_of_its_own_segment(self):
        body = binding._chapter_body(self.sid, 1, 1, self.prose, {}, [])
        self.assertLess(body.index("<p>ONE</p>"), body.index("ch01_1.png"))
        self.assertLess(body.index("ch01_1.png"), body.index("<p>TWO</p>"))
        self.assertLess(body.index("<p>THREE</p>"), body.index("ch01_3.png"))

    def test_a_segment_with_no_picture_simply_has_none(self):
        body = binding._chapter_body(self.sid, 1, 1, self.prose, {}, [])
        self.assertNotIn("ch01_2.png", body)

    def test_a_slot_past_the_last_segment_falls_to_the_end(self):
        """Total by construction, so a chapter delivered without break lines keeps
        its pictures instead of losing every one past the first."""
        body = binding._chapter_body(self.sid, 1, 1, "ONLY ONE SEGMENT", {}, [])
        self.assertIn("ch01_1.png", body)
        self.assertIn("ch01_3.png", body)
        self.assertLess(body.index("<p>ONLY ONE SEGMENT</p>"),
                        body.index("ch01_1.png"))

    def test_every_scene_change_is_visible_to_the_reader(self):
        """The splitter strips the markers, so without something in their place a
        reader goes from the kitchen at dinner to a clearing the next morning mid-page
        with nothing between the paragraphs.

        An illustration IS the separator where there is one; a boundary with no picture
        gets a typographic ornament instead. Either way the break is never invisible."""
        body = binding._chapter_body(self.sid, 1, 1, self.prose, {}, [])
        after_one = body[body.index("<p>ONE</p>"):body.index("<p>TWO</p>")]
        after_two = body[body.index("<p>TWO</p>"):body.index("<p>THREE</p>")]
        self.assertIn("ch01_1.png", after_one, "segment 1 is separated by its picture")
        self.assertIn("scene-break", after_two,
                      "segment 2 has no picture, so it needs the ornament")

    def test_the_raw_marker_never_survives_as_body_text(self):
        """It is an instruction to the harness, not something a reader should meet as a
        stray paragraph of asterisks in the middle of the prose."""
        body = binding._chapter_body(self.sid, 1, 1, self.prose, {}, [])
        self.assertNotIn("<p>* * *</p>", body)

    def test_the_end_of_the_last_scene_is_not_an_ornament(self):
        """The chapter ending is a break already."""
        body = binding._chapter_body(self.sid, 1, 1, "ONLY\n\n* * *\n\nTWO", {}, [])
        self.assertFalse(body.rstrip().endswith("</p>")
                         and "scene-break" in body.rsplit("<p>TWO</p>", 1)[-1])


class TheCoverFillsThePageAndCarriesItsTitle(unittest.TestCase):
    """The art used to inherit the body's page margin and the 5%-inset image rule, so
    on anything wider than the picture it sat in the middle of a white page — and the
    book's title appeared on it nowhere at all."""

    def test_the_page_is_its_own_layout(self):
        page = binding._cover_page("The Hinge Worlds", "Fanfiction-Writer")
        self.assertIn('class="cover-body"', page)
        self.assertIn('class="cover-art"', page)
        self.assertIn("The Hinge Worlds", page)
        self.assertIn("Fanfiction-Writer", page)

    def test_the_art_covers_and_the_title_has_something_to_sit_against(self):
        self.assertIn("object-fit:cover", binding._CSS)
        self.assertIn("height:100vh", binding._CSS)
        self.assertIn("linear-gradient", binding._CSS)

    def test_a_long_title_steps_down_rather_than_overflowing(self):
        short = binding._cover_page("Hinge", "A")
        long = binding._cover_page(
            "The Hinge Worlds and the Very Long Subtitle That Nobody Asked For", "A")
        self.assertIn("font-size:2.6em", short)
        self.assertIn("font-size:1.7em", long)

    def test_the_title_is_escaped(self):
        page = binding._cover_page("Bill & Ford", "A")
        self.assertIn("Bill &amp; Ford", page)


if __name__ == "__main__":
    unittest.main()
