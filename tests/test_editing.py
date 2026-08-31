"""The editorial loop: the editor finds a defect and fixes it in the same breath.

These pin the two properties the whole rebuild rests on.

**Repair is anchored.** Every issue arrives with an exact find/replace, deterministic
code applies it, and prose nobody named is not passed through a model at all. The loop
this replaced re-emitted the whole chapter on every revision and drifted every time —
chapter 8 of the first real novel went 15 -> 4 -> 3 -> 4 -> 2 -> 3 -> 3 -> 3 -> 2 -> 10
-> 7 -> 6 -> 6 -> 8 -> 6 -> 14 across twenty-four attempts, each fixing what it was
told to and breaking something else.

**Nothing quits.** A chapter that cannot be made clean ships holding its defects and is
queued for the book's revision sweep; a stage that keeps failing stalls the book on a
doubling backoff. There is no path from "this is hard" to "the novel stopped", which is
what discarded 113,000 words of accepted prose on 2026-08-09.
"""

import support                                                    # noqa: F401

import unittest                                                   # noqa: E402
from datetime import datetime, timedelta, timezone                # noqa: E402

from fanfic import config, paths, states                          # noqa: E402
from fanfic.engine import book as book_level                      # noqa: E402
from fanfic.engine import chapter as chapter_level                # noqa: E402
from fanfic.engine import revising, stalling                      # noqa: E402
from fanfic.infra import journal, storage                         # noqa: E402
from fanfic.memory.bible import new_series_bible                  # noqa: E402
from fanfic.stages import drafting, editing, surgery              # noqa: E402

# Inside the readability band and over the length floor. Every sentence is unique,
# because an anchor that appears twice is refused by design — a fixture built from a
# repeated paragraph would be testing the ambiguity guard, not the loop.
def _block(k):
    return (f"The morning came slowly over the ruined city on day {k}. Ruby walked "
            f"along the broken wall and looked at the grey sky above sector {k}. "
            f"She was tired, but she would not stop at post {k}. Her friends were "
            f"waiting beyond the river at camp {k}, and the enemy was close behind "
            f"them. She gripped her weapon and took her {k}th steady breath. There "
            f"was still a long road ahead of all of them. ")


BLOCK = _block(0)
BODY = "".join(_block(k) for k in range(1, 45))

# Three scene segments and ~3,300 words: over the length floor and past the scene-break
# gate, so a chapter this loop is asked to judge is not fighting a deterministic
# rejection that has nothing to do with the defect under test. Both of those gates now
# report into `gate_failures`, so a fixture that failed either would make every test in
# this file assert on the wrong thing.
_SEGMENTS = ["The spoon was still on the desk when she reached the landing. "
             + "".join(_block(k) for k in range(1, 16)),
             "".join(_block(k) for k in range(16, 31)),
             "".join(_block(k) for k in range(31, 45))
             + "She had been walking for four days by then. "]
CHAPTER = "\n\n* * *\n\n".join(_SEGMENTS)

OUTLINE = {"number": 1, "title": "The Ruined City", "beats": "Ruby scouts at dawn.",
           "entry_state": "Atlas fallen", "exit_state": "Ruby finds the trail",
           "characters": ["Ruby"], "depends_on": [], "establishes": [],
           "sets_up": [], "pays_off": [], "timeline_index": 0}


def _issue(find, replace, kind="continuity", severity="blocking", text="wrong"):
    return {"kind": kind, "severity": severity, "issue": text,
            "find": find, "replace": replace}


class LoopHarness(unittest.TestCase):
    """A single chapter driven through the real engine with scripted editorial passes."""

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self.sid = "edit-series"
        self.series = journal.write_record(
            journal.new_series(self.sid, f"/inbox/{self.sid}.md", "p"))
        self.book = journal.write_record(journal.new_book(self.sid, 1, "B"))
        self.chapter = journal.write_record(journal.new_chapter(self.sid, 1, 1))
        storage.save_json({"per_book_words": 1600, "per_book_chapters": 2,
                           "style_guide": "past tense"}, paths.plan_path(self.sid))
        storage.save_json(new_series_bible(self.sid),
                          paths.series_bible_path(self.sid))
        storage.save_json({"chapters": [OUTLINE, dict(OUTLINE, number=2)]},
                          paths.outline_path(self.sid, 1))
        records = journal.load_records()
        journal.set_status(records, records[self.book["key"]], states.DRAFTING,
                           chapter_count=2)
        self.drafted = 0

        def draft(prompt, out_path, log_fn=None, role="drafting"):
            self.drafted += 1 if role == "drafting" else 0
            out_path.write_text(CHAPTER, encoding="utf-8")
            return "stub draft"
        drafting.generate = draft

    def script(self, *passes):
        """Feed the editor a fixed sequence of payloads, one per pass."""
        self.reviews = 0
        sequence = list(passes)

        def review(series_rec, book_num, chapter_num, prose, truth, gate_brief,
                   pass_num, log_fn=None):
            self.reviews += 1
            self.last_gate_brief = gate_brief
            self.last_prose = prose
            payload = sequence[min(self.reviews - 1, len(sequence) - 1)]
            if isinstance(payload, Exception):
                raise payload
            return payload
        editing.model_review = review

    def run_chapter(self):
        records = journal.load_records()
        chapter_level.run(records, records[self.series["key"]],
                          records[self.book["key"]],
                          records[self.chapter["key"]], log_fn=lambda _m: None)
        return journal.load_records()[self.chapter["key"]]

    def prose_on_disk(self):
        return paths.chapter_path(self.sid, 1, 1).read_text(encoding="utf-8")


class ACleanChapter(LoopHarness):
    def test_one_pass_is_enough(self):
        self.script({"issues": [], "structural": []})
        rec = self.run_chapter()
        self.assertEqual(rec["status"], states.BIBLE_MERGED)
        self.assertEqual(rec["outstanding_issues"], [])
        self.assertEqual(self.reviews, 1,
                         "a clean chapter must not buy a second opinion")


class RepairIsAnchored(LoopHarness):
    def test_the_named_text_changes_and_nothing_else_does(self):
        self.script(
            {"issues": [_issue("She had been walking for four days by then.",
                               "She had been walking for two days by then.")],
             "structural": []},
            {"issues": [], "structural": []})
        self.run_chapter()
        prose = self.prose_on_disk()
        self.assertIn("two days", prose)
        self.assertNotIn("four days", prose)
        self.assertIn("The spoon was still on the desk", prose,
                      "prose the editor did not name must survive verbatim")

    def test_the_chapter_is_drafted_exactly_once_however_many_passes_run(self):
        """The whole point. A revision that re-emits the chapter is what made the old
        loop random-walk; here the writer is called once and never again."""
        self.script(
            {"issues": [_issue("She had been walking for four days by then.",
                               "She had been walking for two days by then.")],
             "structural": []},
            {"issues": [_issue("The spoon was still on the desk when she reached "
                               "the landing.", "The desk was bare.")],
             "structural": []},
            {"issues": [], "structural": []})
        self.run_chapter()
        self.assertGreaterEqual(self.reviews, 3)
        self.assertEqual(self.drafted, 1)

    def test_polish_edits_are_applied_even_though_they_do_not_block(self):
        """Severity decides whether the chapter is finished, never whether a fix is
        worth applying. A book gets better by accumulating the small ones."""
        self.script({"issues": [_issue("She was tired, but she would not stop at "
                                       "post 3.",
                                       "She was tired. She did not stop.",
                                       kind="craft", severity="polish")],
                     "structural": []})
        rec = self.run_chapter()
        self.assertIn("She was tired. She did not stop.", self.prose_on_disk())
        self.assertEqual(rec["outstanding_issues"], [],
                         "polish alone must not hold a chapter open")
        self.assertEqual(self.reviews, 1,
                         "with only polish left there is nothing to re-judge")

    def test_an_unanchorable_defect_is_not_silently_dropped(self):
        self.script({"issues": [{"kind": "canon", "severity": "blocking",
                                 "issue": "Ruby's weapon is wrong", "find": "",
                                 "replace": None}],
                     "structural": []})
        rec = self.run_chapter()
        self.assertEqual(rec["status"], states.BIBLE_MERGED)
        self.assertTrue(any("Ruby's weapon" in i
                            for i in rec["outstanding_issues"]))

    def test_an_anchor_that_does_not_match_leaves_the_prose_alone(self):
        self.script({"issues": [_issue("a sentence that is not in the chapter", "x")],
                     "structural": []})
        rec = self.run_chapter()
        self.assertEqual(self.prose_on_disk(), CHAPTER)
        self.assertTrue(rec["outstanding_issues"])


class NothingQuits(LoopHarness):
    def test_a_chapter_that_cannot_be_repaired_still_ships(self):
        """It used to park, which failed the book, which failed the series. Twenty-one
        finished chapters were discarded that way over chapter 22 of 37."""
        self.script({"issues": [_issue("not in the chapter", "x", kind="canon")],
                     "structural": []})
        rec = self.run_chapter()
        self.assertEqual(rec["status"], states.BIBLE_MERGED)
        self.assertNotIn(rec["status"], states.DEAD_ENDS)
        self.assertTrue(paths.chapter_path(self.sid, 1, 1).exists())
        self.assertTrue(rec["outstanding_issues"])

    def test_a_shipped_chapter_does_not_stop_the_book(self):
        self.script({"issues": [_issue("not in the chapter", "x", kind="canon")],
                     "structural": []})
        self.run_chapter()
        records = journal.load_records()
        book_level.advance(records, records[self.series["key"]],
                           records[self.book["key"]], log_fn=lambda _m: None)
        after = journal.load_records()[self.book["key"]]
        self.assertNotIn(after["status"], states.DEAD_ENDS)

    def test_a_repeatedly_failing_editor_ships_the_draft_it_has(self):
        self.script(*[RuntimeError("provider died")] *
                    (config.CHAPTER_STAGE_ERROR_RETRIES + 2))
        rec = self.run_chapter()
        self.assertEqual(rec["status"], states.BIBLE_MERGED)
        self.assertTrue(any("EDITOR UNAVAILABLE" in i
                            for i in rec["outstanding_issues"]))

    def test_a_repeatedly_failing_writer_stalls_the_book_rather_than_failing_it(self):
        def broken(prompt, out_path, log_fn=None, role="drafting"):
            raise RuntimeError("claude exited 1")
        drafting.generate = broken
        self.script({"issues": [], "structural": []})

        records = journal.load_records()
        book_level.advance(records, records[self.series["key"]],
                           records[self.book["key"]], log_fn=lambda _m: None)
        after = journal.load_records()[self.book["key"]]
        self.assertEqual(after["status"], states.STALLED)
        self.assertEqual(after["stall_count"], 1)
        self.assertEqual(after["stall_resume_to"], states.DRAFTING)

    def test_a_stage_error_does_not_discard_the_draft_it_already_paid_for(self):
        """A cut editorial call is infrastructure noise. It must not cost the five
        thousand words already on disk, which is a dollar of allowance."""
        self.script(RuntimeError("verdict was not JSON"),
                    {"issues": [], "structural": []})
        self.run_chapter()
        self.assertEqual(self.drafted, 1)


class TheLoopTerminates(LoopHarness):
    def test_it_stops_when_the_editor_can_repair_nothing(self):
        """An identical unanchorable pass twice tells us nothing new; paying for a
        third is how the old loop spent eighteen attempts on one chapter."""
        self.script({"issues": [_issue("not in the chapter", "x")],
                     "structural": []})
        self.run_chapter()
        self.assertEqual(self.reviews, 1)

    def test_it_keeps_going_while_the_count_is_still_falling(self):
        anchors = [
            "The spoon was still on the desk when she reached the landing.",
            "She had been walking for four days by then.",
        ]
        passes = [
            {"issues": [_issue(anchors[0], "The desk was bare."),
                        _issue("not in the chapter", "x"),
                        _issue("also not in the chapter", "y")],
             "structural": []},
            {"issues": [_issue(anchors[1], "She had walked two days."),
                        _issue("not in the chapter", "x")],
             "structural": []},
            {"issues": [], "structural": []},
        ]
        self.script(*passes)
        rec = self.run_chapter()
        self.assertEqual(self.reviews, 3)
        self.assertEqual(rec["outstanding_issues"], [])

    def test_it_will_not_run_past_the_hard_ceiling(self):
        """Every pass applies one real edit and reports two more, forever. Without a
        ceiling this is an infinite loop that bills for every turn of it."""
        counter = {"n": 0}

        def review(series_rec, book_num, chapter_num, prose, truth, gate_brief,
                   pass_num, log_fn=None):
            counter["n"] += 1
            marker = f"MARKER{counter['n']}"
            return {"issues": [
                _issue(f"her {counter['n']}th steady breath",
                       f"her {marker} breath"),
                _issue("nowhere A", "x"), _issue("nowhere B", "y")],
                "structural": []}
        editing.model_review = review
        self.run_chapter()
        self.assertLessEqual(counter["n"], config.EDIT_HARD_MAX_PASSES)


class DeterministicGatesReachTheEditor(LoopHarness):
    def test_a_dense_chapter_is_handed_its_longest_sentences_as_anchors(self):
        """Readability is the one defect that is not located anywhere, and it used to
        be the only thing that ordered a full rewrite. Quoting the worst sentences
        turns it into ordinary anchored edits."""
        dense = "".join(
            f"Notwithstanding the extraordinary circumstances precipitating the "
            f"aforementioned confrontation at location {k}, the reconnaissance "
            f"detachment proceeded methodically through the devastated metropolitan "
            f"infrastructure, cataloguing anomalous manifestations. " for k in range(40))
        self.script({"issues": [], "structural": []})
        editing.review({"series_id": self.sid}, 1, OUTLINE, dense, pass_num=1)
        brief = self.last_gate_brief
        self.assertIn("READABILITY GATE — FAILED", brief)
        self.assertIn("words per sentence", brief)
        self.assertIn("Notwithstanding", brief,
                      "the offending sentences have to be quoted to be anchors")

    def test_a_short_chapter_is_told_to_raise_it_structurally(self):
        self.script({"issues": [], "structural": []})
        editing.review({"series_id": self.sid}, 1, OUTLINE, BLOCK, pass_num=1)
        self.assertIn("LENGTH GATE — FAILED", self.last_gate_brief)
        self.assertIn("`structural`", self.last_gate_brief)

    def test_a_gate_failure_keeps_the_chapter_open_even_with_no_model_issues(self):
        def short_draft(prompt, out_path, log_fn=None, role="drafting"):
            out_path.write_text(BLOCK, encoding="utf-8")
            return "short"
        drafting.generate = short_draft
        self.script({"issues": [], "structural": []})
        rec = self.run_chapter()
        self.assertTrue(any(i.startswith("LENGTH") for i in rec["outstanding_issues"]))


class TheLastPassIsStillChecked(LoopHarness):
    """Whatever the final pass changed is committed without another judgement call.
    Most of that is unverifiable by construction — but the two gates are arithmetic and
    free, and an editor splitting sentences to escape "too dense" can overshoot into
    "too simple" in a way the pass that did it cannot see."""

    def test_an_edit_that_breaks_a_gate_is_caught_after_it_is_applied(self):
        wrecker = _issue(
            "She had been walking for four days by then.",
            "She " + "walked and walked and walked and " * 400 + "stopped.",
            kind="craft", severity="polish")
        self.script({"issues": [wrecker], "structural": []})
        rec = self.run_chapter()
        self.assertEqual(rec["status"], states.BIBLE_MERGED)
        self.assertTrue(any(i.startswith("READABILITY") for i in
                            rec["outstanding_issues"]),
                        f"expected a late gate failure, got {rec['outstanding_issues']}")

    def test_the_journaled_readability_describes_the_prose_that_shipped(self):
        self.script({"issues": [_issue("She had been walking for four days by then.",
                                       "She had walked two days.")],
                     "structural": []},
                    {"issues": [], "structural": []})
        rec = self.run_chapter()
        # Scored against the file, not the draft the last pass was handed. The record
        # has to describe the prose that shipped.
        from fanfic.gates import readability
        shipped = readability.score(self.prose_on_disk())
        self.assertEqual(rec["readability"]["words"], shipped.words)
        self.assertEqual(rec["readability"]["fk_grade"], shipped.fk_grade)


class SceneSurgery(unittest.TestCase):
    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()

    def test_a_replacement_that_shrinks_the_scene_is_refused(self):
        """The failure mode is the writer summarising instead of dramatising, and the
        usual reason for surgery is that something was summarised already."""
        prose = "Alpha. " + ("They argued for an hour and agreed. " * 20) + "Omega."
        span = "They argued for an hour and agreed. " * 20

        def tiny(prompt, out_path, log_fn=None, role="drafting"):
            out_path.write_text("They argued.", encoding="utf-8")
            return "ok"
        drafting.generate = tiny
        out, ok, reason = surgery.replace_passage(
            {"series_id": "s"}, 1, {"number": 1, "beats": "b"}, prose,
            {"find": span, "instruction": "play it out", "issue": "summarised"})
        self.assertFalse(ok)
        self.assertIn("shrink", reason)
        self.assertEqual(out, prose)

    def test_an_ambiguous_anchor_costs_nothing(self):
        """Checked before any model call, so a bad structural note is free."""
        prose = "She waited.\n\nSomething moved.\n\nShe waited.\n"
        out, ok, reason = surgery.replace_passage(
            {"series_id": "s"}, 1, {"number": 1}, prose,
            {"find": "She waited.", "instruction": "x", "issue": "y"})
        self.assertFalse(ok)
        self.assertEqual(out, prose)
        self.assertIn("ambiguous", reason)


class CleanMeansVerified(LoopHarness):
    """"A pass read this and found nothing" and "the last pass fixed what it found"
    are different states, and the second is not clean.

    Chapter 24 of the live run ended 5 -> 2 -> 2 -> 2 with its final pass repairing a
    wrong attribution and a POV slip, and reported ACCEPTED clean — because every
    defect it found had a repair that landed. Nothing had re-read those repairs."""

    def test_a_pass_that_finds_nothing_is_verified(self):
        self.script({"issues": [_issue("She had been walking for four days by then.",
                                       "She had walked two days.")],
                     "structural": []},
                    {"issues": [], "structural": []})
        rec = self.run_chapter()
        self.assertFalse(rec["unverified_repairs"])
        self.assertEqual(rec["outstanding_issues"], [])

    def test_a_last_pass_that_repaired_something_is_not(self):
        anchors = ["The spoon was still on the desk when she reached the landing.",
                   "She had been walking for four days by then."]
        repairs = [_issue(anchors[0], "The desk was bare."),
                   _issue(anchors[1], "She had walked two days.")]
        # Every pass finds and fixes one thing, so the count never reaches zero and the
        # loop ends on a pass that applied an edit.
        self.script({"issues": [repairs[0]], "structural": []},
                    {"issues": [repairs[1]], "structural": []},
                    {"issues": [_issue("The desk was bare.", "The desk was empty.")],
                     "structural": []},
                    {"issues": [_issue("The desk was empty.", "Nothing was on it.")],
                     "structural": []})
        rec = self.run_chapter()
        self.assertEqual(rec["outstanding_issues"], [])
        self.assertTrue(rec["unverified_repairs"],
                        "nothing re-read the repairs the last pass applied")

    def test_a_pass_with_only_polish_left_is_unverified_but_defect_free(self):
        """Chapter 27 finished 5 -> 4 -> 1 -> 0 with a last pass of 0 blocking and 7
        polish. It is unverified — a polish edit can quietly assert a new fact, and
        several in this book have — but it did not end holding defects, and the log
        must not read as though it did."""
        self.script({"issues": [_issue("She had been walking for four days by then.",
                                       "She had walked two days.")],
                     "structural": []},
                    {"issues": [_issue("She gripped her weapon and took her 4th "
                                       "steady breath.",
                                       "She took a steady breath.",
                                       kind="craft", severity="polish")],
                     "structural": []})
        rec = self.run_chapter()
        self.assertEqual(rec["outstanding_issues"], [])
        self.assertTrue(rec["unverified_repairs"])
        self.assertEqual(rec["revisions"], 2)

    def _set(self, **fields):
        records = journal.load_records()
        journal.set_status(records, records[self.chapter["key"]],
                           states.BIBLE_MERGED, **fields)
        return journal.load_records()

    def test_an_unverified_chapter_earns_a_first_round(self):
        records = self._set(unverified_repairs=True, outstanding_issues=[])
        self.assertEqual(
            [r["chapter_num"] for r in revising.flagged(records, self.sid, 1)], [1])

    def test_a_round_that_found_only_polish_ends_the_sweeping(self):
        """The stopping rule, and the reason it is blocking-yield rather than
        edits-applied. Every pass that applies an edit leaves that edit unread, so
        "sweep until verified" never terminates; and a demanding editor always finds
        polish, so polish must never buy another round."""
        records = self._set(sweeps=1, unverified_repairs=True,
                            sweep_found_blocking=False, outstanding_issues=[])
        self.assertEqual(revising.flagged(records, self.sid, 1), [])

    def test_a_round_that_found_a_real_defect_buys_another(self):
        """Measured on the live book: the first sweep round turned up 18 blocking
        defects across 24 chapters, three of them canon violations that had survived
        the per-chapter loop. A round with that yield is worth its cost."""
        records = self._set(sweeps=1, sweep_found_blocking=True,
                            outstanding_issues=[])
        self.assertEqual(
            [r["chapter_num"] for r in revising.flagged(records, self.sid, 1)], [1])

    def test_the_ceiling_still_stops_a_pathological_chapter(self):
        records = self._set(sweeps=config.REVISION_SWEEPS,
                            sweep_found_blocking=True,
                            outstanding_issues=["CANON: still wrong"])
        self.assertEqual(revising.flagged(records, self.sid, 1), [])

    def test_a_chapter_with_known_defects_still_gets_the_full_budget(self):
        records = journal.load_records()
        journal.set_status(records, records[self.chapter["key"]],
                           states.BIBLE_MERGED, sweeps=1,
                           outstanding_issues=["CONTINUITY: the clock slips"])
        records = journal.load_records()
        self.assertTrue(revising.flagged(records, self.sid, 1))


class TheRevisionSweep(LoopHarness):
    def _ship_with_issues(self):
        self.script({"issues": [_issue("not in the chapter", "x")],
                     "structural": []})
        self.run_chapter()

    def test_a_flagged_chapter_is_revisited_against_the_finished_book(self):
        self._ship_with_issues()
        self.script({"issues": [_issue("She had been walking for four days by then.",
                                       "She had walked two days.")],
                     "structural": []})
        records = journal.load_records()
        done = revising.advance(records, records[self.series["key"]],
                                dict(records[self.book["key"]],
                                     status=states.REVISING),
                                log_fn=lambda _m: None)
        self.assertFalse(done, "there was a flagged chapter, so the sweep is not done")
        rec = journal.load_records()[self.chapter["key"]]
        self.assertEqual(rec["sweeps"], 1)
        self.assertIn("She had walked two days.", self.prose_on_disk())
        self.assertEqual(rec["outstanding_issues"], [])

    def test_the_sweep_stops_after_its_allowance(self):
        self._ship_with_issues()
        self.script({"issues": [_issue("not in the chapter", "x")],
                     "structural": []})
        book_rec = dict(journal.load_records()[self.book["key"]],
                        status=states.REVISING)
        for _ in range(config.REVISION_SWEEPS + 2):
            records = journal.load_records()
            done = revising.advance(records, records[self.series["key"]], book_rec,
                                    log_fn=lambda _m: None)
            if done:
                break
        rec = journal.load_records()[self.chapter["key"]]
        self.assertEqual(rec["sweeps"], config.REVISION_SWEEPS)
        self.assertTrue(done, "the sweep has to terminate")

    def test_a_failing_sweep_never_costs_the_committed_chapter(self):
        self._ship_with_issues()
        before = self.prose_on_disk()
        self.script(RuntimeError("editor died"))
        records = journal.load_records()
        revising.advance(records, records[self.series["key"]],
                         dict(records[self.book["key"]], status=states.REVISING),
                         log_fn=lambda _m: None)
        self.assertEqual(self.prose_on_disk(), before)
        self.assertEqual(journal.load_records()[self.chapter["key"]]["sweeps"], 1)


class Stalling(unittest.TestCase):
    def test_a_later_stall_resumes_from_where_the_unit_actually_is(self):
        """A unit that stalled at DRAFTING, recovered, and reached REVISING still
        carries `stall_resume_to: drafting`. Preferring the stored value would send it
        back three stages on its next, unrelated stall."""
        records = {}
        rec = {"key": "series/s/book/1", "level": "book", "book_num": 1,
               "status": states.REVISING, "stall_count": 1,
               "stall_resume_to": states.DRAFTING}
        stalling.stall(records, rec, "something else broke", log_fn=lambda _m: None)
        self.assertEqual(records[rec["key"]]["stall_resume_to"], states.REVISING)
        self.assertEqual(records[rec["key"]]["stall_count"], 2)

    def test_the_escalation_starts_over_after_a_long_clean_stretch(self):
        """The counter has to mean "recent trouble", not "trouble ever". A record
        carries it forward through every later write, so a book that stalled four times
        during research and then wrote thirty clean chapters must not wait an hour
        before retrying its first unrelated hiccup months later."""
        long_ago = (datetime.now(timezone.utc)
                    - timedelta(seconds=config.STALL_BACKOFF_MAX_SEC * 3))
        records = {}
        rec = {"key": "series/s/book/1", "level": "book", "book_num": 1,
               "status": states.DRAFTING, "stall_count": 4,
               "stalled_at": long_ago.isoformat()}
        stalling.stall(records, rec, "a fresh problem", log_fn=lambda _m: None)
        self.assertEqual(records[rec["key"]]["stall_count"], 1)

    def test_a_stall_hard_on_the_heels_of_another_escalates(self):
        records = {}
        rec = {"key": "series/s/book/1", "level": "book", "book_num": 1,
               "status": states.DRAFTING, "stall_count": 4,
               "stalled_at": datetime.now(timezone.utc).isoformat()}
        stalling.stall(records, rec, "the same problem", log_fn=lambda _m: None)
        self.assertEqual(records[rec["key"]]["stall_count"], 5)

    def test_the_wait_doubles_and_is_capped(self):
        waits = [stalling.backoff_seconds(n) for n in range(1, 12)]
        self.assertEqual(waits[0], config.STALL_BACKOFF_BASE_SEC)
        self.assertEqual(waits[1], config.STALL_BACKOFF_BASE_SEC * 2)
        self.assertTrue(all(w <= config.STALL_BACKOFF_MAX_SEC for w in waits))
        self.assertEqual(waits[-1], config.STALL_BACKOFF_MAX_SEC)

    def test_a_unit_is_not_retried_before_its_wait_elapses(self):
        now = datetime.now(timezone.utc)
        rec = {"status": states.STALLED, "stall_count": 1,
               "stalled_at": now.isoformat()}
        self.assertFalse(stalling.due(rec, now=now))
        self.assertTrue(stalling.due(
            rec, now=now + timedelta(seconds=config.STALL_BACKOFF_BASE_SEC + 1)))

    def test_anything_not_stalled_is_always_due(self):
        self.assertTrue(stalling.due({"status": states.DRAFTING}))


class LegacyTerminalRecords(LoopHarness):
    """A journal written by the build that had terminal failures must self-heal.

    This is not hypothetical housekeeping: it is how the run that lost its book on
    2026-08-09 gets picked back up, with the twenty-one accepted chapters intact."""

    def test_a_parked_chapter_is_resumed_rather_than_honoured(self):
        records = journal.load_records()
        journal.set_status(records, records[self.chapter["key"]],
                           states.FAILED_CHAPTER, error="revision budget exhausted")
        records = journal.load_records()
        book_level.advance(records, records[self.series["key"]],
                           records[self.book["key"]], log_fn=lambda _m: None)
        after = journal.load_records()[self.chapter["key"]]
        self.assertEqual(after["status"], states.PENDING)
        self.assertIsNone(after["error"])

    def test_a_failed_book_is_resumed_rather_than_honoured(self):
        records = journal.load_records()
        journal.set_status(records, records[self.book["key"]], states.FAILED,
                           error="chapter 22 parked")
        records = journal.load_records()
        book_level.advance(records, records[self.series["key"]],
                           records[self.book["key"]], log_fn=lambda _m: None)
        self.assertEqual(journal.load_records()[self.book["key"]]["status"],
                         states.DRAFTING)


class PhantomChapters(LoopHarness):
    """A record for a chapter number the outline does not have.

    Not hypothetical: the live crossover carried 23 of them. A 60-chapter outline was
    rejected by the structure gate and replaced with the specified 37, and chapters
    38-60 stayed in the journal as PENDING forever. They are the one input that turns
    "never give up" into a useless loop — nothing can draft a chapter that does not
    exist, so the book would stall, wait, retry, and repeat until somebody looked."""

    def _finish_the_real_chapters(self):
        """Chapters 1 and 2 are the whole outline; 3 is the phantom."""
        journal.write_record(journal.new_chapter(self.sid, 1, 2))
        for n in (1, 2):
            records = journal.load_records()
            journal.set_status(records,
                               records[journal.chapter_key(self.sid, 1, n)],
                               states.BIBLE_MERGED)

    def test_a_chapter_outside_the_outline_is_retired_not_drafted(self):
        extra = journal.write_record(journal.new_chapter(self.sid, 1, 3))
        self._finish_the_real_chapters()

        records = journal.load_records()
        book_level.advance(records, records[self.series["key"]],
                           records[self.book["key"]], log_fn=lambda _m: None)
        after = journal.load_records()[extra["key"]]
        self.assertEqual(after["status"], states.RETIRED)
        self.assertEqual(self.drafted, 0, "nothing may be drafted for it")

    def test_the_book_finishes_drafting_once_the_phantoms_are_retired(self):
        journal.write_record(journal.new_chapter(self.sid, 1, 3))
        self._finish_the_real_chapters()
        for _ in range(4):
            records = journal.load_records()
            book_level.advance(records, records[self.series["key"]],
                               records[self.book["key"]], log_fn=lambda _m: None)
            if journal.load_records()[self.book["key"]]["status"] == states.DRAFTED:
                break
        self.assertEqual(journal.load_records()[self.book["key"]]["status"],
                         states.DRAFTED)


class Normalising(unittest.TestCase):
    def test_an_unknown_severity_defaults_by_kind(self):
        """Asymmetric on purpose: the expensive mistake differs. A missed canon breach
        ships a wrong book; a missed polish note costs nothing."""
        issues, _ = editing.normalise({"issues": [
            {"kind": "canon", "issue": "a", "find": "x", "replace": "y"},
            {"kind": "craft", "issue": "b", "find": "x", "replace": "y"}]})
        self.assertEqual(issues[0]["severity"], "blocking")
        self.assertEqual(issues[1]["severity"], "polish")

    def test_an_unknown_kind_becomes_continuity(self):
        issues, _ = editing.normalise({"issues": [
            {"kind": "vibes", "issue": "a", "find": "x", "replace": "y"}]})
        self.assertEqual(issues[0]["kind"], "continuity")

    def test_an_empty_replace_is_a_deletion_not_a_missing_field(self):
        issues, _ = editing.normalise({"issues": [
            {"kind": "craft", "issue": "explained joke", "find": "x",
             "replace": ""}]})
        self.assertTrue(issues[0]["anchored"])
        self.assertEqual(issues[0]["replace"], "")

    def test_nested_anchors_apply_longest_first(self):
        """Two edits where one anchor contains the other is the only way a well-formed
        list fights itself. Longest first means the specific edit lands."""
        prose = "The tall grey wall stood at the edge of the field."
        report = {"issues": [
            {"kind": "craft", "severity": "polish", "issue": "", "anchored": True,
             "find": "grey", "replace": "green"},
            {"kind": "craft", "severity": "polish", "issue": "", "anchored": True,
             "find": "The tall grey wall", "replace": "The wall"}]}
        out, applied, _rejected = editing.apply_report(prose, report)
        self.assertEqual(len(applied), 1)
        self.assertTrue(out.startswith("The wall"))


class LongestSentences(unittest.TestCase):
    def test_they_come_back_longest_first_and_unique(self):
        prose = ("Short one. " + "A rather considerably longer sentence with many "
                 "more words in it indeed. " + "Short one. " + "Middling length "
                 "sentence here.")
        picked = editing.longest_sentences(prose, 5)
        self.assertTrue(picked[0].startswith("A rather considerably"))
        self.assertNotIn("Short one.", picked,
                         "a repeated sentence is unusable as an anchor")


class TheInteractionLedger(unittest.TestCase):
    """A crossover is bought for its collisions, and nothing else in the pipeline
    would ever ask for one — a beat sheet optimises for plot, and "these two finally
    share a scene" is not a plot beat. So they are planned once and then enforced."""

    CAST = [{"name": f"C{k}"} for k in range(1, 11)]

    def _entries(self, n):
        return [{"id": f"x.{k}", "who": ["C1", "C2"], "promise": "they collide",
                 "chapter": k} for k in range(1, n + 1)]

    def test_the_ledger_is_no_longer_the_plans_business(self):
        """It moved to the meta plan, and the move is the fix.

        Sized against the CAST it was 13 for a cast of 26; the model produced 23
        across 37 chapters and fourteen chapters owed nothing to anybody. The thing it
        has to cover is the book, so it is now built chapter by chapter — and a plan
        carrying no `interactions` field at all is correct rather than incomplete."""
        from fanfic.stages import planning
        plan = {"book_count": 1,
                "books": [{"num": 1, "title": "T", "premise": "p", "role": "r",
                           "exit_state": "e"}],
                "arc": {"beginning": "b", "end": "e"},
                "style_guide": "past tense",
                "characters": [dict(c, appearance="a", voice="v", origin="Show",
                                    age=17)
                               for c in self.CAST],
                "antagonists": [{"name": "C10", "primary": True, "threat": "t"}],
                "progressions": [{"id": f"p.{k}", "who": f"C{k}",
                                  "starts": "s", "ends": "e"}
                                 for k in range(1, 11)]}
        plan["characters"][9]["origin"] = "original"
        plan["characters"][9]["palette"] = ["#000000"]
        plan["characters"][9]["distinguishing_feature"] = "one orange band"
        plan["characters"][9]["appearance"] = "x" * 220
        self.assertEqual(planning._validate(plan), [])

    def test_a_guest_star_is_rejected(self):
        """Everyone on the cast list is a principal. That is what being on it means."""
        from fanfic.gates import interactions as gate
        origins = {f"C{k}": "Show" for k in range(1, 11)}
        report = gate.check(self._entries(9), origins, ["Show"], min_appearances=3)
        self.assertFalse(report.passed)
        self.assertTrue(any("fewer than 3 interactions" in e for e in report.errors))

    def test_a_grouping_past_its_budget_is_rejected(self):
        """A core party may recur; it may not be most of the book. Four scenes for one
        pair is past the budget in `config.META_SUBSET_MAX_REPEATS`."""
        from fanfic.gates import interactions as gate
        origins = {"C1": "Show", "C2": "Show"}
        report = gate.check(self._entries(4), origins, ["Show"], min_appearances=1,
                            subset_cap=3)
        self.assertFalse(report.passed)
        self.assertTrue(any("budget" in e for e in report.errors), report.errors)

    def test_a_ledger_that_is_a_small_rotation_is_rejected(self):
        """The cap alone permits monotony: 200 scenes could be 67 groupings used three
        times each. The distinct floor is the other half of the same intent."""
        from fanfic.gates import interactions as gate
        origins = {f"C{k}": "Show" for k in range(1, 5)}
        # Three groupings, each used three times — every one inside the cap.
        groups = [["C1", "C2"], ["C2", "C3"], ["C3", "C4"]]
        entries = [{"id": f"x.{i}", "who": g, "chapter": i // 3 + 1}
                   for i, g in enumerate(groups * 3)]
        report = gate.check(entries, origins, ["Show"], min_appearances=1,
                            subset_cap=3)
        self.assertFalse(report.passed)
        self.assertTrue(any("fresh combination" in e for e in report.errors),
                        report.errors)

    def test_a_ledger_of_only_two_handers_is_rejected(self):
        """As broken as one of only ensemble scenes: a book with no crowd in it."""
        from fanfic.gates import interactions as gate
        origins = {f"C{k}": "Show" for k in range(1, 9)}
        entries = [{"id": f"x.{k}", "who": [f"C{k}", f"C{k+1}"], "chapter": k}
                   for k in range(1, 8)]
        report = gate.check(entries, origins, ["Show"], min_appearances=1)
        self.assertFalse(report.passed)
        self.assertTrue(any("four or more people" in e for e in report.errors))

    def test_a_standalone_is_not_asked_to_be_a_crossover(self):
        """One source world means every scene is within-cast by construction. Demanding
        60% of them cross universes would make a single-universe book unplannable —
        a gate rejecting the only correct answer."""
        from fanfic.gates import interactions as gate
        origins = {f"C{k}": "Show" for k in range(1, 7)}
        # The register rules are not relaxed for a standalone, and should not be: a
        # one-world book still owes its reader something happening. Only the two
        # crossover rules are skipped.
        entries = [{"id": "x.1", "who": ["C1", "C2"], "chapter": 1,
                    "register": "physical"},
                   {"id": "x.2", "who": ["C3", "C4"], "chapter": 2,
                    "register": "conflict"},
                   {"id": "x.3", "who": ["C1", "C3", "C5"], "chapter": 3,
                    "register": "comic"},
                   {"id": "x.4", "who": ["C2", "C4", "C6"], "chapter": 4,
                    "register": "physical"},
                   {"id": "x.5", "who": ["C1", "C2", "C3", "C4"], "chapter": 5,
                    "register": "tender"},
                   {"id": "x.6", "who": ["C3", "C4", "C5", "C6"], "chapter": 6,
                    "register": "physical"}]
        report = gate.check(entries, origins, ["Show"], min_appearances=1)
        self.assertTrue(report.passed, report.errors)

    def test_a_crossover_that_never_crosses_is_rejected(self):
        """Chapter 1 of the last attempt was 100% Owl House, and nothing checked."""
        from fanfic.gates import interactions as gate
        origins = {"A1": "Alpha", "A2": "Alpha", "A3": "Alpha",
                   "B1": "Beta", "B2": "Beta", "B3": "Beta"}
        entries = [{"id": "x.1", "who": ["A1", "A2"], "chapter": 1},
                   {"id": "x.2", "who": ["A2", "A3"], "chapter": 2},
                   {"id": "x.3", "who": ["A1", "A3"], "chapter": 3},
                   {"id": "x.4", "who": ["B1", "B2", "B3"], "chapter": 4},
                   {"id": "x.5", "who": ["A1", "A2", "A3", "B1"], "chapter": 5}]
        report = gate.check(entries, origins, ["Alpha", "Beta"], min_appearances=1)
        self.assertFalse(report.passed)
        self.assertTrue(any("cross universes" in e for e in report.errors))

    def test_an_outline_that_delivers_none_of_them_is_rejected(self):
        from fanfic.gates import structure
        outline = {"chapters": [
            {"number": 1, "title": "One", "timeline_index": 0},
            {"number": 2, "title": "Two", "timeline_index": 1}]}
        report = structure.check(outline, interactions=self._entries(2))
        self.assertFalse(report.passed)
        self.assertTrue(any("delivered by no chapter" in e for e in report.errors))

    def test_delivering_the_same_interaction_twice_is_rejected(self):
        """Twice is as wrong as never: a scene the book already had is a repeat, not
        the payoff of a promise."""
        from fanfic.gates import structure
        outline = {"chapters": [
            {"number": 1, "title": "One", "timeline_index": 0, "delivers": ["x.1"]},
            {"number": 2, "title": "Two", "timeline_index": 1, "delivers": ["x.1"]}]}
        report = structure.check(outline, interactions=self._entries(1))
        self.assertTrue(any("already delivered" in e for e in report.errors))

    def test_a_fully_delivered_outline_passes(self):
        from fanfic.gates import structure
        outline = {"chapters": [
            {"number": 1, "title": "One", "timeline_index": 0, "delivers": ["x.1"]},
            {"number": 2, "title": "Two", "timeline_index": 1, "delivers": ["x.2"]}]}
        self.assertTrue(structure.check(outline,
                                        interactions=self._entries(2)).passed)

    def test_the_writer_is_told_which_collisions_this_chapter_owes(self):
        from fanfic.memory.digest import build_chapter_digest
        bible = {"characters": {}, "foreshadowing": [], "interactions": [
            {"id": "x.1", "who": ["Dipper Pines", "Entrapta"],
             "promise": "two researchers, one problem, no shared vocabulary",
             "chapters": [7], "status": "owed"},
            {"id": "x.2", "who": ["Catra", "Eda Clawthorne"],
             "promise": "neither wants to talk about it",
             "chapters": [19], "status": "owed"}]}
        digest = build_chapter_digest(
            {"number": 7, "beats": "b", "characters": []}, "", bible, {}, "s", 5000)
        self.assertIn("THIS CHAPTER OWES", digest)
        self.assertIn("Dipper Pines + Entrapta", digest)
        self.assertIn("STILL OWED LATER", digest)
        self.assertIn("Catra + Eda Clawthorne", digest)

    def test_the_editor_can_see_the_whole_ledger(self):
        from fanfic.memory.digest import build_ground_truth
        bible = {"characters": {}, "foreshadowing": [], "interactions": [
            {"id": "x.1", "who": ["Luz Noceda", "Adora"], "promise": "p",
             "chapters": [12], "status": "owed"}]}
        truth = build_ground_truth({"number": 12}, bible, {})
        self.assertIn("INTERACTION LEDGER", truth)
        self.assertIn("Luz Noceda + Adora", truth)

    def test_a_bible_with_no_ledger_says_nothing_about_one(self):
        """Older series predate the ledger. They must degrade to the previous brief
        rather than growing an empty section that reads as a missing promise."""
        from fanfic.memory.digest import build_chapter_digest
        digest = build_chapter_digest(
            {"number": 1, "beats": "b", "characters": []}, "",
            {"characters": {}, "foreshadowing": []}, {}, "s", 5000)
        self.assertNotIn("OWES", digest)


if __name__ == "__main__":
    unittest.main()


class TheTrajectorySurvivesARestart(LoopHarness):
    """A restart mid-chapter used to throw the editorial history away.

    Chapter 10 of the live SWTOR run went 5 -> 2 blocking, the daemons were restarted
    to deploy an unrelated fix, and it was journaled `revisions: 1` and logged
    `ACCEPTED (0) — its last pass found no defects`. That reads as a chapter that
    arrived clean. It was a chapter three passes deep.

    The draft on disk is reused across a restart, so those passes are part of this
    chapter's history. Losing them made the log untrue, handed the chapter a fresh
    `EDIT_MAX_PASSES` budget, and blinded `_still_improving` to a stalled loop."""

    def _resume_mid_edit(self, trajectory):
        """The state a restart leaves behind: a draft on disk, status CH_EDITING, and
        the passes already spent recorded against the chapter."""
        paths.draft_path(self.sid, 1, 1).parent.mkdir(parents=True, exist_ok=True)
        paths.draft_path(self.sid, 1, 1).write_text(CHAPTER, encoding="utf-8")
        records = journal.load_records()
        journal.set_status(records, records[self.chapter["key"]], states.CH_EDITING,
                           trajectory=list(trajectory))

    def test_the_earlier_passes_are_counted(self):
        self._resume_mid_edit([5, 2])
        self.script({"issues": [], "structural": []})
        rec = self.run_chapter()
        self.assertEqual(rec["revisions"], 3,
                         "the two passes spent before the restart were forgotten")
        self.assertEqual(rec["trajectory"], [5, 2, 0])

    def test_the_draft_is_not_rewritten(self):
        """Guards the premise: this is a resume, so the drafter is never called."""
        self._resume_mid_edit([5, 2])
        self.script({"issues": [], "structural": []})
        self.run_chapter()
        self.assertEqual(self.drafted, 0)

    def test_a_restart_does_not_refresh_the_pass_budget(self):
        """`EDIT_MAX_PASSES` is 3 and `_still_improving` compares the last two passes
        against the best before them. Resuming at [4, 4, 4] is a loop that has stopped
        converging and has already spent the soft cap, so it gets no further pass."""
        self._resume_mid_edit([4, 4, 4])
        self.script({"issues": [{"find": "nope", "replace": "nope",
                                 "why": "x", "blocking": True}], "structural": []})
        rec = self.run_chapter()
        self.assertEqual(self.reviews, 0,
                         "a restart handed the chapter a fresh editorial budget")
        self.assertEqual(rec["status"], states.BIBLE_MERGED,
                         "it must still ship rather than stall")

    def test_a_fresh_draft_starts_a_fresh_trajectory(self):
        """The other half. A redrafted chapter must not inherit blocking counts
        belonging to prose that no longer exists — that would spend its budget on a
        draft they were never about."""
        records = journal.load_records()
        journal.set_status(records, records[self.chapter["key"]], states.PENDING,
                           trajectory=[9, 9, 9])
        self.script({"issues": [], "structural": []})
        rec = self.run_chapter()
        self.assertEqual(self.drafted, 1, "this should be a fresh draft")
        self.assertEqual(rec["trajectory"], [0])
        self.assertEqual(rec["revisions"], 1)


class EveryPassLeavesItsProseBehind(unittest.TestCase):
    """The loop keeps only its LAST version, and on the first real book that is
    measurably not always its best: three of nineteen chapters shipped carrying about
    nine blocking defects an earlier pass had already cleared.

    Whether to ship the better-measured version instead could not be answered, because
    the better version was overwritten the moment the next pass ran. These snapshots
    exist so the comparison can be made from real prose. **Nothing reads them and
    nothing about what ships changes** — that is the point of keeping the two apart."""

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self.sid = "snap-series"
        self.series = journal.write_record(
            journal.new_series(self.sid, f"/inbox/{self.sid}.md", "p"))
        self.book = journal.write_record(journal.new_book(self.sid, 1, "B"))
        self.chapter = journal.write_record(journal.new_chapter(self.sid, 1, 1))
        storage.save_json({"per_book_words": 1600, "per_book_chapters": 2,
                           "style_guide": "past tense"}, paths.plan_path(self.sid))
        storage.save_json(new_series_bible(self.sid),
                          paths.series_bible_path(self.sid))
        storage.save_json({"chapters": [OUTLINE, dict(OUTLINE, number=2)]},
                          paths.outline_path(self.sid, 1))
        records = journal.load_records()
        journal.set_status(records, records[self.book["key"]], states.DRAFTING,
                           chapter_count=2)

        def draft(prompt, out_path, log_fn=None, role="drafting"):
            out_path.write_text(CHAPTER, encoding="utf-8")
            return "stub draft"
        drafting.generate = draft

    def _run(self, *passes):
        self.reviews = 0
        seq = list(passes)

        def review(series_rec, book_num, chapter_num, prose, truth, gate_brief,
                   pass_num, log_fn=None):
            self.reviews += 1
            return seq[min(self.reviews - 1, len(seq) - 1)]
        editing.model_review = review
        records = journal.load_records()
        chapter_level.run(records, records[self.series["key"]],
                          records[self.book["key"]],
                          records[self.chapter["key"]], log_fn=lambda _m: None)

    # Anchors must be UNIQUE in the fixture or the repair is refused as ambiguous and
    # the loop stops on "could not anchor any repair" after one pass. Note that a
    # NUMBERED anchor is not unique here even though the paragraph it names is:
    # `_block(k)` runs k=1..44, so "sector 1" also matches sectors 10-19 — eleven hits.
    # These two sentences bracket the fixture and appear exactly once.
    FIX_ONE = ("The spoon was still on the desk",
               "The spoon lay untouched on the desk")
    FIX_TWO = ("She had been walking for four days",
               "She had been walking for five days")

    def test_one_snapshot_per_pass(self):
        self._run({"issues": [_issue(*self.FIX_ONE)], "structural": []},
                  {"issues": [_issue(*self.FIX_TWO)], "structural": []},
                  {"issues": [], "structural": []})
        self.assertGreaterEqual(self.reviews, 2, "needed at least two applied passes")
        for n in (1, 2):
            self.assertTrue(paths.pass_snapshot_path(self.sid, 1, 1, n).exists(),
                            f"pass {n} left no snapshot")

    def test_the_snapshot_holds_that_pass_s_text(self):
        self._run({"issues": [_issue(*self.FIX_ONE)], "structural": []},
                  {"issues": [], "structural": []})
        first = paths.pass_snapshot_path(self.sid, 1, 1, 1).read_text(encoding="utf-8")
        self.assertIn(self.FIX_ONE[1], first,
                      "the snapshot should hold the text AFTER that pass's edits")

    def test_what_ships_is_the_last_pass_not_the_best(self):
        """The whole point: this observes, it does not steer.

        A pass that finds nothing returns before writing a snapshot — it applied no
        edits, so there is no new text to keep — which is why this drives one applied
        pass and then a clean one, and compares against the snapshot that exists."""
        self._run({"issues": [_issue(*self.FIX_ONE)], "structural": []},
                  {"issues": [], "structural": []})
        shipped = paths.chapter_path(self.sid, 1, 1).read_text(encoding="utf-8")
        last = paths.pass_snapshot_path(self.sid, 1, 1, 1).read_text(encoding="utf-8")
        self.assertEqual(shipped.strip(), last.strip(),
                         "snapshotting must not change what ships")
        self.assertIn(self.FIX_ONE[1], shipped)
