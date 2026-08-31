"""Revive on re-drop: a FAILED series resumes from its last good state.

FAILED is terminal and never auto-retried, so the retry gesture is a human moving the
prompt back into inbox/. What must NOT happen then is a restart: the frozen canon, the
plan, the outline, and every accepted chapter are durable, and re-drafting them would
burn a day of budget to arrive back where we already were.

The subtle part is *which* state to rewind to. A unit that died during a transient
in-progress status (BINDING, RESEARCHING, DELIVERING) has no handler for that status,
so the rewind has to reach back past it to the last stable dispatch entry point.
"""

import unittest

import support

from fanfic import states                                         # noqa: E402
from fanfic.engine import admission                               # noqa: E402
from fanfic.infra import journal                                  # noqa: E402


class RecoverStaleTests(unittest.TestCase):
    """A unit abandoned mid-stage — killed, crashed, power-cut, launchd restart — sits
    in an in-progress status that nothing dispatches on: not terminal so nothing
    reports it, not resumable so nothing advances it, not FAILED so a re-drop cannot
    revive it. It would wedge forever."""

    def setUp(self):
        support.wipe_state()

    def _series_mid_research(self, sid):
        records = {}
        series = journal.write_record(
            journal.new_series(sid, f"/inbox/{sid}.md", "p"))
        records[series["key"]] = series
        journal.set_status(records, records[series["key"]], states.RESEARCHING)
        return records

    def test_a_series_killed_mid_research_is_rewound_to_prompt_dropped(self):
        sid = "killed-in-research"
        self._series_mid_research(sid)
        self.assertEqual(dict(journal.recover_stale())[journal.series_key(sid)],
                         states.PROMPT_DROPPED)
        after = journal.load_records()[journal.series_key(sid)]
        self.assertEqual(after["status"], states.PROMPT_DROPPED)
        self.assertIsNone(after["error"])

    def test_a_book_killed_mid_binding_is_rewound_to_illustrated(self):
        sid = "killed-in-binding"
        records = {}
        book = journal.write_record(journal.new_book(sid, 1, "Book One"))
        records[book["key"]] = book
        for status in (states.OUTLINED, states.DRAFTING, states.DRAFTED,
                       states.ILLUSTRATING, states.ILLUSTRATED, states.BINDING):
            journal.set_status(records, records[book["key"]], status)
        self.assertEqual(dict(journal.recover_stale())[journal.book_key(sid, 1)],
                         states.ILLUSTRATED)

    def test_settled_and_terminal_units_are_left_alone(self):
        sid = "not-stale"
        records = {}
        series = journal.write_record(
            journal.new_series(sid, f"/inbox/{sid}.md", "p"))
        records[series["key"]] = series
        journal.set_status(records, records[series["key"]], states.BOOKS_IN_PROGRESS)
        failed = journal.write_record(journal.new_book(sid, 1))
        records[failed["key"]] = failed
        journal.set_status(records, records[failed["key"]], states.FAILED, error="x")

        self.assertEqual(journal.recover_stale(), [])
        after = journal.load_records()
        self.assertEqual(after[journal.series_key(sid)]["status"],
                         states.BOOKS_IN_PROGRESS)
        self.assertEqual(after[journal.book_key(sid, 1)]["status"], states.FAILED)

    def test_recovery_is_idempotent(self):
        sid = "twice"
        self._series_mid_research(sid)
        self.assertEqual(len(journal.recover_stale()), 1)
        self.assertEqual(journal.recover_stale(), [],
                         "a recovered unit is no longer stale")

    def test_a_recovered_series_then_runs_to_completion(self):
        """The whole point: a restart mid-stage costs that stage, not the job."""
        support.stub_model_seams()
        sid = "restart-survivor"
        support.drop(sid)
        records = journal.load_records()
        admission.register_inbox(records, log_fn=lambda _m: None)
        journal.set_status(records, records[journal.series_key(sid)],
                           states.RESEARCHING)              # simulate the kill

        journal.recover_stale()
        self.assertEqual(support.run_engine(sid), states.SERIES_COMPLETE)


class AStallRewindsToTheRightStage(unittest.TestCase):
    """A stall happens the instant a stage raises, so it cannot consult journal history
    the way `recover_stale` does — it needs the entry point of the status it died in.

    The fallback used to be one guess for a whole level: "a book rewinds to DRAFTING".
    For a book that stalled while outlining that means resuming with no outline, finding
    no chapters to draft, and walking straight through DRAFTED and REVISING to bind an
    empty novel. Every transient status now names its own entry point."""

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()

    def test_a_book_that_dies_while_outlining_resumes_before_outlining(self):
        from fanfic.stages import outlining

        def boom(series_rec, book_num, out_path, log_fn=None, feedback=""):
            raise RuntimeError("provider died mid-outline")
        outlining.propose_outline = boom

        support.drop("stall-outline")
        support.run_engine("stall-outline", limit=12)

        book = journal.load_records()[journal.book_key("stall-outline", 1)]
        self.assertEqual(book["status"], states.STALLED)
        self.assertEqual(book["stall_resume_to"], states.META_PLANNED,
                         "not DRAFTING — there is no outline to draft from")

    def test_every_transient_status_has_somewhere_to_go_back_to(self):
        for status in states.TRANSIENT:
            self.assertIn(status, states.REWIND_TO, status)
            self.assertIn(states.REWIND_TO[status], states.RESUMABLE, status)


class ReviveTests(unittest.TestCase):
    def setUp(self):
        support.wipe_state()

    def test_rewinds_past_a_transient_status_to_the_last_resumable_one(self):
        sid = "revive-unit"
        records = {}
        series = journal.write_record(
            journal.new_series(sid, f"/inbox/{sid}.md", "p"))
        records[series["key"]] = series
        for status in (states.RESEARCHED, states.SERIES_PLANNED,
                       states.BOOKS_IN_PROGRESS):
            journal.set_status(records, records[series["key"]], status)

        book = journal.write_record(journal.new_book(sid, 1, "Book One"))
        records[book["key"]] = book
        for status in (states.OUTLINED, states.DRAFTING, states.DRAFTED,
                       states.ILLUSTRATING, states.ILLUSTRATED, states.BINDING):
            journal.set_status(records, records[book["key"]], status)

        # The book dies inside the transient BINDING step; the series follows it down.
        journal.set_status(records, records[book["key"]], states.FAILED,
                           error="binding boom")
        journal.set_status(records, records[series["key"]], states.FAILED,
                           error="book failed")

        revived = dict(journal.revive_series(sid))
        self.assertEqual(revived[journal.book_key(sid, 1)], states.ILLUSTRATED)
        self.assertEqual(revived[journal.series_key(sid)], states.BOOKS_IN_PROGRESS)

        after = journal.load_records()
        self.assertEqual(after[journal.book_key(sid, 1)]["status"],
                         states.ILLUSTRATED)
        self.assertIsNone(after[journal.book_key(sid, 1)]["error"])
        self.assertEqual(after[journal.series_key(sid)]["status"],
                         states.BOOKS_IN_PROGRESS)

    def test_redropping_a_failed_prompt_revives_instead_of_ignoring_it(self):
        sid = "redrop-me"
        records = {}
        series = journal.write_record(
            journal.new_series(sid, f"/inbox/{sid}.md", "p"))
        records[series["key"]] = series
        journal.set_status(records, records[series["key"]], states.RESEARCHED,
                           universes=["RWBY"])
        journal.set_status(records, records[series["key"]], states.FAILED,
                           error="park")

        support.drop(sid)                                     # the retry gesture
        records = journal.load_records()
        admission.register_inbox(records, log_fn=lambda _m: None)

        self.assertEqual(records[journal.series_key(sid)]["status"],
                         states.RESEARCHED)
        self.assertNotEqual(
            journal.load_records()[journal.series_key(sid)]["status"], states.FAILED)

    def test_a_parked_chapter_is_un_parked_by_a_re_drop(self):
        """A re-drop must un-park FAILED_CHAPTER, or the gesture is a no-op.

        Leaving it parked was the original behaviour and it made re-dropping useless:
        the book rewound to DRAFTING, met the same parked chapter on the next cycle,
        and re-failed in five seconds — filing the prompt straight back into failed/.
        A re-drop only ever happens because a human moved a file, so honouring it is
        not an auto-retry loop."""
        sid = "keep-parked"
        records = {}
        series = journal.write_record(
            journal.new_series(sid, f"/inbox/{sid}.md", "p"))
        records[series["key"]] = series
        journal.set_status(records, records[series["key"]], states.BOOKS_IN_PROGRESS)
        journal.set_status(records, records[series["key"]], states.FAILED, error="x")

        chapter = journal.write_record(journal.new_chapter(sid, 1, 1))
        records[chapter["key"]] = chapter
        journal.set_status(records, records[chapter["key"]], states.FAILED_CHAPTER,
                           error="critics unhappy", revisions=4)

        journal.revive_series(sid)
        after = journal.load_records()
        chapter_after = after[journal.chapter_key(sid, 1, 1)]
        self.assertEqual(chapter_after["status"], states.PENDING)
        self.assertIsNone(chapter_after["error"])
        self.assertEqual(chapter_after["revisions"], 0,
                         "the revision budget must be fresh, or the un-park is a lie")
        self.assertEqual(after[journal.series_key(sid)]["status"],
                         states.BOOKS_IN_PROGRESS)

    def test_a_revived_parked_chapter_actually_drafts_again(self):
        """The end-to-end version of the above: the whole point is that the next cycle
        makes progress instead of re-failing the book within seconds."""
        sid = "unpark-and-run"
        records = {}
        series = journal.write_record(
            journal.new_series(sid, f"/inbox/{sid}.md", "p"))
        records[series["key"]] = series
        journal.set_status(records, records[series["key"]], states.BOOKS_IN_PROGRESS)
        journal.set_status(records, records[series["key"]], states.FAILED,
                           error="book 1 failed")

        book = journal.write_record(journal.new_book(sid, 1))
        records[book["key"]] = book
        journal.set_status(records, records[book["key"]], states.DRAFTING)
        journal.set_status(records, records[book["key"]], states.FAILED,
                           error="chapter 1 parked")

        chapter = journal.write_record(journal.new_chapter(sid, 1, 1))
        records[chapter["key"]] = chapter
        journal.set_status(records, records[chapter["key"]], states.FAILED_CHAPTER,
                           error="critics unhappy", revisions=4)

        revived = dict(journal.revive_series(sid))
        self.assertEqual(revived[journal.series_key(sid)], states.BOOKS_IN_PROGRESS)
        self.assertEqual(revived[journal.book_key(sid, 1)], states.DRAFTING)
        self.assertEqual(revived[journal.chapter_key(sid, 1, 1)], states.PENDING)

        records = journal.load_records()
        book_rec = records[journal.book_key(sid, 1)]
        self.assertIsNone(
            journal.first_incomplete_chapter(records, sid, 1)["error"])
        self.assertNotEqual(book_rec["status"], states.FAILED)

    def test_documentation_in_the_inbox_is_not_a_job(self):
        """inbox/README.md was once admitted as a series called "readme", failed
        research for naming no universe, and got filed into inbox/failed/. The folder
        ate its own instructions."""
        support.config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        for name in ("README.md", "_scratch.md"):
            (support.config.INBOX_DIR / name).write_text("notes", encoding="utf-8")
        support.drop("real-job")

        records = journal.load_records()
        admission.register_inbox(records, log_fn=lambda _m: None)

        admitted = {r["series_id"] for r in records.values()
                    if r.get("level") == "series"}
        self.assertEqual(admitted, {"real-job"})
        self.assertTrue((support.config.INBOX_DIR / "README.md").exists(),
                        "documentation must be left where it is")

    def test_nothing_to_rewind_to_leaves_it_failed(self):
        """A series that failed on its very first step has no prior resumable status.
        Reviving must be a no-op rather than inventing one."""
        sid = "born-failed"
        records = {}
        series = journal.write_record(
            journal.new_series(sid, f"/inbox/{sid}.md", "p"))
        records[series["key"]] = series
        journal.set_status(records, records[series["key"]], states.RESEARCHING)
        journal.set_status(records, records[series["key"]], states.FAILED,
                           error="no universe named")

        # PROMPT_DROPPED is itself resumable, so this one rewinds to the start.
        revived = dict(journal.revive_series(sid))
        self.assertEqual(revived[journal.series_key(sid)], states.PROMPT_DROPPED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
