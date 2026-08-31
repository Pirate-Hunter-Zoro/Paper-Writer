"""The three deterministic gates.

These are the rules a confidently wrong model is not allowed to talk its way past,
so they are tested by asserting on the failure cases, not the happy path.
"""

import support                                                    # noqa: F401

import unittest                                                   # noqa: E402

from fanfic import config, paths, states                          # noqa: E402
from fanfic.gates import coverage, length, readability, structure  # noqa: E402
from fanfic.engine import book as book_level                      # noqa: E402
from fanfic.infra import journal, storage                         # noqa: E402
from fanfic.memory import bible, store                            # noqa: E402
from fanfic.stages import planning                                # noqa: E402


class ReadabilityTests(unittest.TestCase):
    def test_syllable_heuristic(self):
        self.assertEqual(readability.count_syllables("cat"), 1)
        self.assertEqual(readability.count_syllables("table"), 2)   # -le keeps a beat
        self.assertEqual(readability.count_syllables("make"), 1)    # silent e
        self.assertEqual(readability.count_syllables("hero"), 2)

    def test_simple_prose_scores_easy(self):
        text = ("The cat sat on the mat. The dog ran to the man. "
                "She saw the sun. He ate the ham. ") * 20
        report = readability.score(text)
        self.assertLess(report.fk_grade, config.READABILITY_FK_GRADE_MAX)
        self.assertGreater(report.flesch_ease, 80)

    def test_dense_prose_fails_the_ceiling(self):
        text = ("The extraordinarily sophisticated bureaucratic infrastructure "
                "necessitated unprecedented administrative reorganization, "
                "consequently precipitating considerable institutional "
                "consternation throughout the interconnected organizational "
                "hierarchies. ") * 20
        report = readability.score(text)
        self.assertFalse(report.passed)
        self.assertTrue(any("too dense" in r for r in report.reasons))

    def test_empty_draft_fails(self):
        self.assertFalse(readability.score("   ").passed)


class CoverageTests(unittest.TestCase):
    def _canon(self, *facts):
        doc = bible.new_canon("RWBY")
        doc["facts"] = list(facts)
        return doc

    def test_full_coverage_passes(self):
        doc = self._canon(
            {"id": "1", "category": "char", "subject": "Ruby",
             "text": "Ruby Rose leads.", "citation": "x"},
            {"id": "2", "category": "loc", "subject": "Vacuo",
             "text": "Vacuo is a desert kingdom.", "citation": "y"})
        report = coverage.check(doc, ["Ruby", "Vacuo"])
        self.assertTrue(report.passed)
        self.assertEqual(report.missing, [])

    def test_thin_coverage_parks_and_names_what_is_missing(self):
        doc = self._canon({"id": "1", "category": "char", "subject": "Ruby",
                           "text": "Ruby leads.", "citation": "x"})
        report = coverage.check(doc, ["Ruby", "Weiss", "Blake", "Yang"])
        self.assertFalse(report.passed)
        self.assertIn("Weiss", report.missing)


class StructureTests(unittest.TestCase):
    def _chapter(self, n, idx, **kw):
        base = {"number": n, "title": f"Chapter Title {n}",
                "beats": f"beats {n}", "entry_state": "",
                "exit_state": "", "characters": [], "depends_on": [],
                "establishes": [], "sets_up": [], "pays_off": [],
                "timeline_index": idx}
        base.update(kw)
        return base

    def test_valid_outline_passes(self):
        outline = {"chapters": [
            self._chapter(1, 0, establishes=["f.a"], sets_up=["t.x"]),
            self._chapter(2, 1, depends_on=["f.a"]),
            self._chapter(3, 2, pays_off=["t.x"]),
        ]}
        report = structure.check(outline)
        self.assertTrue(report.passed, report.errors)

    def test_backwards_timeline_fails(self):
        report = structure.check(
            {"chapters": [self._chapter(1, 5), self._chapter(2, 2)]})
        self.assertFalse(report.passed)
        self.assertTrue(any("backwards" in e for e in report.errors))

    def test_orphaned_thread_fails(self):
        report = structure.check(
            {"chapters": [self._chapter(1, 0, sets_up=["t.x"]),
                          self._chapter(2, 1)]})
        self.assertFalse(report.passed)
        self.assertTrue(any("orphaned thread" in e for e in report.errors))

    def test_payoff_before_setup_fails(self):
        report = structure.check(
            {"chapters": [self._chapter(1, 0, pays_off=["t.x"]),
                          self._chapter(2, 1, sets_up=["t.x"])]})
        self.assertFalse(report.passed)

    def test_dependency_on_a_seed_fact_passes(self):
        report = structure.check(
            {"chapters": [self._chapter(1, 0, depends_on=["canon.ruby"])]},
            seed_facts={"canon.ruby"})
        self.assertTrue(report.passed, report.errors)

    def test_noncontiguous_numbering_fails(self):
        report = structure.check(
            {"chapters": [self._chapter(1, 0), self._chapter(3, 1)]})
        self.assertFalse(report.passed)

    def test_empty_outline_fails(self):
        self.assertFalse(structure.check({"chapters": []}).passed)



class CoverageAliasTests(unittest.TestCase):
    """Canon refers to people the way canon refers to them, not the way a prompt does.

    On 2026-08-04 a genuinely good canon of 207 cited facts was rejected at 84.2%
    because the gate demanded the literal strings "Sergeant Rusk", "Sith Emperor
    Vitiate", and "Old Republic" while canon — correctly — wrote "Rusk", "Vitiate",
    and "Republic". That parked a novel."""

    def _canon(self, *texts):
        doc = bible.new_canon("SWTOR")
        doc["facts"] = [{"id": str(i), "category": "lore", "subject": "x",
                         "text": t, "citation": "wiki"}
                        for i, t in enumerate(texts)]
        return doc

    def test_a_title_prefixed_name_matches_the_bare_name(self):
        doc = self._canon("Rusk served in the Republic military.")
        self.assertTrue(coverage.check(doc, ["Sergeant Rusk"]).passed)

    def test_identifying_words_may_be_spread_across_facts(self):
        doc = self._canon("Vitiate ruled for centuries.",
                          "The Sith Emperor consumed a world.")
        self.assertTrue(coverage.check(doc, ["Sith Emperor Vitiate"]).passed)

    def test_a_short_leading_qualifier_is_ignored(self):
        doc = self._canon("The Republic signed the Treaty of Coruscant.")
        self.assertTrue(coverage.check(doc, ["Old Republic"]).passed)

    def test_an_entity_canon_never_mentions_still_fails(self):
        """The fallback is accuracy, not slack — the gate must still catch real gaps."""
        doc = self._canon("Rusk served in the Republic military.")
        report = coverage.check(doc, ["Hutt Cartel"])
        self.assertFalse(report.passed)
        self.assertEqual(report.missing, ["Hutt Cartel"])

    def test_a_single_word_entity_gets_no_second_chance(self):
        doc = self._canon("Tython is the Jedi homeworld.")
        self.assertFalse(coverage.check(doc, ["Balmorra"]).passed)


class NarrativeStopwordTests(unittest.TestCase):
    """Words describing the shape of the story are not fandom entities. Leaving "Act"
    and "Rise" in the entity list was a third of the shortfall that parked a run."""

    def test_structure_words_are_not_entities(self):
        from fanfic import jobspec
        entities = jobspec.implied_entities(
            "## Main characters\nKira Carsen is a Padawan.\n\n"
            "## Canon anchor point\nthe close of the Knight's Act 3, before the "
            "events of Rise of the Hutt Cartel\n")
        self.assertIn("Kira Carsen", entities)
        for word in ("Act", "Rise", "Part", "Arc", "Scene"):
            self.assertNotIn(word, entities)

if __name__ == "__main__":
    unittest.main(verbosity=2)


class ChapterTitles(unittest.TestCase):
    """Titles are gated because nothing downstream can recover a missing one.

    Three independent places dropped this field: the outline prompt never asked for a
    title, this gate never required one, and the binder hardcoded "Chapter N". The
    first book was on course for 37 numbered chapters and nobody would have noticed
    until they opened the epub."""

    def _outline(self, titles):
        return {"chapters": [
            {"number": i, "title": t, "beats": f"beats {i}", "entry_state": "",
             "exit_state": "", "characters": [], "depends_on": [], "sets_up": [],
             "pays_off": [], "timeline_index": i}
            for i, t in enumerate(titles, 1)]}

    def test_a_titled_outline_passes(self):
        report = structure.check(self._outline(["The Gnarls", "The Carved Hand"]))
        self.assertTrue(report.passed, report.errors)

    def test_a_missing_title_fails_and_names_the_chapter(self):
        report = structure.check(self._outline(["The Gnarls", ""]))
        self.assertFalse(report.passed)
        self.assertTrue(any("chapter 2" in e and "title" in e for e in report.errors),
                        report.errors)

    def test_a_whitespace_title_counts_as_missing(self):
        report = structure.check(self._outline(["The Gnarls", "   "]))
        self.assertFalse(report.passed)

    def test_duplicate_titles_fail(self):
        """A table of contents with the same entry twice is worse than none."""
        report = structure.check(self._outline(["The Gnarls", "the gnarls"]))
        self.assertFalse(report.passed)
        self.assertTrue(any("duplicates" in e for e in report.errors), report.errors)

    def test_a_summary_masquerading_as_a_title_fails(self):
        long = "The Chapter Where Elira Decides To Hold The Line Against The Raiders"
        report = structure.check(self._outline(["The Gnarls", long + " Forever And Ever"]))
        self.assertFalse(report.passed)
        self.assertTrue(any("not a summary" in e for e in report.errors), report.errors)


if __name__ == "__main__":
    unittest.main()


class GateRejectionsAreRetriedWithTheErrors(unittest.TestCase):
    """A deterministic gate must show the proposer what it rejected.

    Planning and outlining each face a strict structural gate and each used to get
    exactly one attempt, with a rejection parking the entire series. That is the
    chapter loop's original defect at series scale: the revision loop could not
    converge while the writer was never handed the thing it was revising, and a
    planner never told why its plan was rejected is in the same position. It leaves
    only two options, and both are bad — a gate loose enough to always pass, or a coin
    flip on a whole novel.
    """

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self.sid = "gate-retry"
        self.rec = journal.new_series(self.sid, f"/inbox/{self.sid}.md",
                                      support.PROMPT)

    def test_a_plan_missing_a_voice_is_rejected_then_corrected(self):
        seen = []

        def flaky(series_rec, out_path, log_fn=None, feedback=""):
            seen.append(feedback)
            char = {"name": "Ruby", "appearance": "red cloak", "origin": "RWBY",
                    "age": 17, "ref_sheet_spec": "full body"}
            if len(seen) > 1:                       # corrected on the second pass
                char["voice"] = "bright, fast, over-eager"
            villain = {
                "name": "The Hollow Marshal", "origin": "original",
                "voice": "flat, courteous, never raises it", "age": 400,
                "palette": ["#8a8a8a"],
                "distinguishing_feature": "one orange band at the collar",
                "appearance": (
                    "A tall narrow figure built like a surveyor's tripod: long "
                    "straight legs, a coat that hangs to the ankle without folding, "
                    "and a smooth pale oval head with no features but a horizontal "
                    "seam. Moves in straight lines only. Slate grey and bone white, "
                    "with one band of surveyor's orange at the collar.")}
            storage.save_json({
                "title": "T", "book_count": 1, "per_book_words": 1600,
                "style_guide": "third-person limited, past tense",
                "arc": {"beginning": "a", "end": "b"},
                "books": [{"num": 1, "title": "T", "premise": "p",
                           "entry_state": "e", "exit_state": "x", "role": "opener"}],
                "characters": [char, villain], "relationships": [],
                "antagonists": [{"name": "The Hollow Marshal", "primary": True,
                                 "threat": "unmakes the roads between places"}],
                "progressions": [
                    {"id": "p.1", "who": "Ruby", "starts": "s", "ends": "e"},
                    {"id": "p.2", "who": "The Hollow Marshal",
                     "starts": "s", "ends": "e"}],
            }, out_path)
        planning.propose_plan = flaky

        result = planning.run(self.rec, log_fn=lambda _m: None)

        self.assertEqual(result["book_count"], 1)
        self.assertEqual(len(seen), 2, "the rejection must trigger exactly one retry")
        self.assertEqual(seen[0], "", "the first attempt carries no feedback")
        self.assertIn("voice", seen[1],
                      "the retry must name the field the validator objected to")
        bible = storage.load_json(paths.series_bible_path(self.sid))
        self.assertIn("bright", bible["characters"]["Ruby"]["voice"])

    def test_a_plan_that_never_validates_still_parks(self):
        """Bounded. A proposal failing repeatedly WITH the errors in hand is failing
        for a reason another roll will not reach."""
        calls = []

        def hopeless(series_rec, out_path, log_fn=None, feedback=""):
            calls.append(1)
            storage.save_json({"book_count": 1, "books": []}, out_path)
        planning.propose_plan = hopeless

        with self.assertRaises(RuntimeError):
            planning.run(self.rec, log_fn=lambda _m: None)
        self.assertEqual(len(calls), config.GATE_MAX_ATTEMPTS)


class LengthGate(unittest.TestCase):
    """A FLOOR, and only a floor.

    A short chapter is invisible to every other gate: it can be perfect on canon,
    clean on continuity, and dead centre of the readability band. So there is a floor.

    What there is no longer is a target. The gate used to be a ratio against a
    per-chapter word count derived from the book's total, and it worked — toward a
    number that made the prose worse. Asked for 5,351 words the writer returns about
    2,681 good ones, so the gate fired constantly and sent each chapter back for
    padding, and the cheapest padding available to a model that has finished its story
    is the POV character reflecting on her own dialogue. The gate manufactured the
    exact prose the book was criticised for.
    """

    def test_a_chapter_under_the_floor_blocks(self):
        report = length.check(2400, floor=3000)
        self.assertFalse(report.passed)
        self.assertIn("2,400", report.reason)
        self.assertIn("3,000", report.reason)

    def test_the_short_verdict_asks_for_scenes_not_padding(self):
        """The editorial brief otherwise says 'change nothing else', which is the
        opposite of what a short chapter needs. If this rejection did not say so
        explicitly, the editor would obey the wrong rule."""
        reason = length.check(2400, floor=3000).reason
        self.assertIn("NOT surgery", reason)
        self.assertIn("missing material", reason)
        self.assertIn("Do not pad", reason)

    def test_the_verdict_forbids_the_padding_the_old_target_produced(self):
        """Naming it, because "add material" is exactly the instruction that produced
        interiority the last time round."""
        reason = length.check(2400, floor=3000).reason
        self.assertIn("how she feels about what she just said", reason)

    def test_anything_at_or_over_the_floor_passes(self):
        for words in (3000, 4300, 5350, 12000):
            self.assertTrue(length.check(words, floor=3000).passed, words)

    def test_running_long_is_not_a_defect_and_not_even_a_note(self):
        """There is no ceiling at all now — not even an advisory one. A chapter that
        runs long is a chapter, and a note saying so is one more nudge toward a
        target."""
        report = length.check(12000, floor=3000)
        self.assertTrue(report.passed)
        self.assertEqual(report.reason, "")

    def test_the_floor_defaults_to_config(self):
        self.assertFalse(length.check(config.CHAPTER_MIN_WORDS - 1).passed)
        self.assertTrue(length.check(config.CHAPTER_MIN_WORDS).passed)

    def test_a_zero_floor_disables_the_gate(self):
        """Zero means off. None means "use the configured floor" — the two are
        deliberately different, so a caller passing nothing gets the gate rather than
        silently switching it off."""
        self.assertTrue(length.check(300, floor=0).passed)
        self.assertFalse(length.check(300, floor=None).passed)


class TheChapterFloorIsAbsolute(unittest.TestCase):
    """`store.load` used to derive a per-chapter word target from the plan, and had to
    carry a `target_planned` flag saying whether that number was real — because a
    fabricated target is how "there is no plan on disk" turns into "every chapter is
    too short".

    The whole apparatus is gone with the target. A floor in words needs no plan, no
    outline, and no chapter count to be meaningful, so there is nothing left to be
    wrong about."""

    def setUp(self):
        support.wipe_state()
        self.sid = "target-series"
        self.rec = journal.new_series(self.sid, f"/inbox/{self.sid}.md", "p")

    def test_the_floor_holds_with_no_plan_at_all(self):
        self.assertEqual(store.load(self.rec, 1).chapter_floor,
                         config.CHAPTER_MIN_WORDS)

    def test_the_floor_does_not_move_with_the_book_size(self):
        storage.save_json({"per_book_words": 198000}, paths.plan_path(self.sid))
        storage.save_json({"chapters": [{"number": n} for n in range(1, 38)]},
                          paths.outline_path(self.sid, 1))
        self.assertEqual(store.load(self.rec, 1).chapter_floor,
                         config.CHAPTER_MIN_WORDS)


class TheBookLengthFloorIsMeasuredAndReported(unittest.TestCase):
    """`BOOK_MIN_WORDS` was added as a floor, written into the config table as a floor,
    and read by nothing at all — the exact failure the picture budget had, one section
    away in the same README. It is measured now, at DRAFTED, and recorded rather than
    enforced: by then the book is written, and refusing it would only throw away a novel
    that exists."""

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self.sid = "length-report"
        self.rec = journal.write_record(
            journal.new_series(self.sid, f"/inbox/{self.sid}.md", "p"))
        self.book = journal.write_record(journal.new_book(self.sid, 1, "B"))
        storage.save_json({"chapters": [{"number": 1}, {"number": 2}]},
                          paths.outline_path(self.sid, 1))

    def _run(self, words_each):
        for n in (1, 2):
            storage.atomic_write_text(" ".join(["word"] * words_each),
                                      paths.chapter_path(self.sid, 1, n))
        lines = []
        records = journal.load_records()
        book_level._report_book_length(records, {"series_id": self.sid},
                                       records[self.book["key"]], log_fn=lines.append)
        return lines, journal.load_records()[self.book["key"]]

    def test_the_measured_length_lands_on_the_record(self):
        _lines, record = self._run(100)
        self.assertEqual(record["book_words"], 200)

    def test_a_short_book_is_reported_and_still_ships(self):
        lines, record = self._run(100)
        self.assertIn("UNDER", lines[0])
        self.assertEqual(record["status"], states.QUEUED,
                         "reporting must not move the book's status")

    def test_a_long_enough_book_just_states_the_number(self):
        lines, _record = self._run(config.BOOK_MIN_WORDS)
        self.assertNotIn("UNDER", lines[0])
        self.assertIn("words across 2 chapters", lines[0])


class ChapterCountIsTheStorysDecision(unittest.TestCase):
    """It used to be a ±15% band around a specified count, and the specified count was
    what set the per-chapter word target that manufactured the filler. The count is now
    the outliner's; the only thing gated is that a novel did not come back as a
    novella."""

    def _outline(self, n):
        return {"chapters": [
            {"number": i, "title": f"Chapter Title {i}", "beats": f"beats {i}",
             "entry_state": "", "exit_state": "", "characters": [],
             "depends_on": [], "establishes": [], "sets_up": [], "pays_off": [],
             "timeline_index": i - 1}
            for i in range(1, n + 1)]}

    def test_at_the_floor_passes(self):
        self.assertTrue(structure.check(self._outline(32), min_chapters=32).passed)

    def test_below_the_floor_fails(self):
        report = structure.check(self._outline(18), min_chapters=32)
        self.assertFalse(report.passed)
        self.assertTrue(any("18 chapters" in e for e in report.errors))

    def test_there_is_no_upper_limit(self):
        """A longer book is not a defect. The band used to reject 60 chapters, and
        rejecting a story that needs sixty chapters is not a thing a gate should do."""
        for n in (40, 60, 90):
            self.assertTrue(structure.check(self._outline(n),
                                            min_chapters=32).passed, n)

    def test_no_floor_means_no_check(self):
        self.assertTrue(structure.check(self._outline(3)).passed)

    def test_the_book_declares_its_own_floor_before_the_default(self):
        from fanfic.stages import outlining
        self.assertEqual(outlining.min_chapters({"per_book_chapters": 12}), 12)
        self.assertEqual(outlining.min_chapters({}), config.MIN_CHAPTERS)
