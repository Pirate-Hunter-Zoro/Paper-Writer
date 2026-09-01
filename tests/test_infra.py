"""The journal and atomic storage — the two things a crash lands on.

If either of these is wrong, every other guarantee in the system is decoration.
"""

import json
import unittest
from pathlib import Path

import support                                                    # noqa: F401

from fanfic import config, paths, states                                  # noqa: E402
from fanfic.engine import cycle                                   # noqa: E402
from fanfic.errors import QuotaExceeded                           # noqa: E402
from fanfic.infra import journal, storage                         # noqa: E402


class JournalTests(unittest.TestCase):
    def setUp(self):
        if paths.journal_file().exists():
            paths.journal_file().unlink()

    def test_append_and_replay_last_writer_wins(self):
        record = journal.new_series("swtor-01", "/inbox/job.md", "prompt body")
        journal.write_record(record)
        records = journal.load_records()
        self.assertEqual(records[record["key"]]["status"], states.PROMPT_DROPPED)

        journal.set_status(records, record, states.RESEARCHING)
        journal.set_status(records, records[record["key"]], states.RESEARCHED,
                           universes=["SWTOR"])
        replayed = journal.load_records()
        self.assertEqual(replayed[record["key"]]["status"], states.RESEARCHED)
        self.assertEqual(replayed[record["key"]]["universes"], ["SWTOR"])

    def test_torn_final_line_is_tolerated(self):
        record = journal.new_series("rwby-01", "/inbox/j.md", "p")
        journal.write_record(record)
        with paths.journal_file().open("a", encoding="utf-8") as fh:
            fh.write('{"key": "series/rwby-01", "status": "resear')   # crash mid-write
        records = journal.load_records()                             # must not raise
        self.assertEqual(records[record["key"]]["status"], states.PROMPT_DROPPED)

    def test_first_incomplete_chapter_is_where_drafting_resumes(self):
        records = {}
        for n in (1, 2, 3):
            chapter = journal.new_chapter("s", 1, n)
            journal.write_record(chapter)
            records[chapter["key"]] = chapter
        for n in (1, 2):                              # 1-2 durable, 3 still pending
            key = journal.chapter_key("s", 1, n)
            journal.set_status(records, records[key], states.BIBLE_MERGED)
        resume_at = journal.first_incomplete_chapter(journal.load_records(), "s", 1)
        self.assertEqual(resume_at["chapter_num"], 3)

    def test_children_come_back_ordered(self):
        records = {}
        for n in (2, 1, 3):
            book = journal.new_book("s", n)
            journal.write_record(book)
            records[book["key"]] = book
        books = journal.books_of(journal.load_records(), "s")
        self.assertEqual([b["book_num"] for b in books], [1, 2, 3])


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(support.config.STATE_DIR)

    def test_atomic_write_leaves_no_temp_files(self):
        dest = self.root / "series" / "s" / "ch1.md"
        storage.atomic_write_text("Chapter one.\n", dest)
        self.assertEqual(dest.read_text(), "Chapter one.\n")
        leftovers = [p for p in dest.parent.iterdir() if p.name.startswith(".tmp-")]
        self.assertEqual(leftovers, [])

    def test_place_then_redelivery_is_a_verified_noop(self):
        src = self.root / "book.epub"
        storage.atomic_write_bytes(b"EPUBDATA", src)
        target = self.root / "delivered" / "book.epub"
        self.assertFalse(storage.already_delivered(src, target))

        staged = storage.staging_dir_for(target.parent) / "book.epub"
        storage.atomic_write_bytes(src.read_bytes(), staged)
        storage.atomic_place(staged, target)
        self.assertTrue(target.exists())
        self.assertTrue(storage.already_delivered(src, target))

    def test_json_roundtrip(self):
        path = self.root / "doc.json"
        storage.save_json({"a": [1, 2], "b": "x"}, path)
        self.assertEqual(storage.load_json(path), {"a": [1, 2], "b": "x"})
        self.assertEqual(storage.load_json(self.root / "absent.json", {"d": 1}),
                         {"d": 1})



class TheDaemonLoopNamesAStuckDaemon(unittest.TestCase):
    """A swallowed error that repeats identically is not a blip, and it used to look
    exactly like one: a config attribute that did not exist raised every cycle and
    logged one tidy "cycle error (continuing)" line every thirty seconds — a daemon
    doing nothing, in a log that reads like a daemon working."""

    def _run(self, cycle_fn, cycles):
        from fanfic import daemons
        lines = []
        calls = {"n": 0}

        def counted():
            calls["n"] += 1
            if calls["n"] > cycles:
                raise KeyboardInterrupt
            return cycle_fn()

        real_sleep = daemons.time.sleep
        daemons.time.sleep = lambda _s: None
        try:
            daemons.loop("t", counted, lines.append, idle_sec=30)
        finally:
            daemons.time.sleep = real_sleep
        return lines

    def test_the_same_error_repeated_is_called_a_bug(self):
        def always():
            raise AttributeError("module 'config' has no attribute 'X'")
        lines = self._run(always, 5)
        self.assertTrue(any(l.startswith("cycle error (continuing)") for l in lines))
        stuck = [l for l in lines if l.startswith("STUCK:")]
        self.assertTrue(stuck, "an error that never changes has to stop reading as noise")
        self.assertIn("not a blip", stuck[0])

    def test_a_one_off_blip_is_still_just_a_blip(self):
        state = {"n": 0}

        def flaky():
            state["n"] += 1
            if state["n"] == 2:
                raise RuntimeError("connection reset")
            return 30
        lines = self._run(flaky, 5)
        self.assertFalse([l for l in lines if l.startswith("STUCK:")])

    def test_a_success_clears_the_streak(self):
        state = {"n": 0}

        def alternating():
            state["n"] += 1
            if state["n"] % 2:
                raise RuntimeError("same words every time")
            return 30
        lines = self._run(alternating, 8)
        self.assertFalse([l for l in lines if l.startswith("STUCK:")],
                         "work is getting done between failures; that is not stuck")


class AMalformedProposalIsARejectionNotACrash(unittest.TestCase):
    """A truncated artifact is exactly what the retry-with-feedback loop is for.

    Every gated stage has a branch for "this is not a JSON object" that hands the
    errors back and asks again — and that branch was unreachable, because `load_json`
    raised `JSONDecodeError` first. A `JSONDecodeError` is not a `RuntimeError`, so it
    sailed past the engine's stall handler and surfaced as a bare cycle error, leaving
    the series in a transient status nothing dispatches on. Seen live: a 52-character
    plan cut off mid-array at 114,090 characters."""

    def setUp(self):
        support.wipe_state()
        self.path = paths.tmp_path("proposal.json")

    def test_a_truncated_artifact_returns_a_reason_rather_than_raising(self):
        self.path.write_text('{"characters": [{"name": "Luz"', encoding="utf-8")
        value, why = storage.load_proposal(self.path)
        self.assertIsNone(value)
        self.assertIn("TRUNCATION", why)
        self.assertIn("30 characters long", why)

    def test_a_missing_artifact_says_so(self):
        value, why = storage.load_proposal(paths.tmp_path("nothing-here.json"))
        self.assertIsNone(value)
        self.assertIn("no artifact", why)

    def test_an_empty_artifact_says_so(self):
        self.path.write_text("   \n", encoding="utf-8")
        value, why = storage.load_proposal(self.path)
        self.assertIsNone(value)
        self.assertIn("empty", why)

    def test_a_good_artifact_comes_back_with_no_complaint(self):
        self.path.write_text('{"ok": true}', encoding="utf-8")
        value, why = storage.load_proposal(self.path)
        self.assertEqual(value, {"ok": True})
        self.assertEqual(why, "")

    def test_committed_state_still_raises_on_corruption(self):
        """The opposite posture, deliberately: a corrupt bible is not something to
        paper over with a default, because that silently discards a book's memory."""
        self.path.write_text("{ broken", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            storage.load_json(self.path)


class TheTruncatedPlanIsRetriedWithTheReason(unittest.TestCase):

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self.sid = "truncated-plan"
        self.rec = journal.new_series(self.sid, f"/inbox/{self.sid}.md",
                                      support.PROMPT)

    def test_the_stage_retries_and_the_feedback_names_the_truncation(self):
        from fanfic.stages import planning
        seen = []
        good = planning.propose_plan

        def flaky(series_rec, out_path, log_fn=None, feedback=""):
            seen.append(feedback)
            if len(seen) == 1:
                out_path.write_text('{"characters": [{"nam', encoding="utf-8")
                return "truncated"
            return good(series_rec, out_path, log_fn=log_fn, feedback=feedback)
        planning.propose_plan = flaky

        result = planning.run(self.rec, log_fn=lambda _m: None)
        self.assertEqual(result["book_count"], 1)
        self.assertEqual(len(seen), 2, "the malformed artifact must trigger a retry")
        self.assertIn("TRUNCATION", seen[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class AQuotaSaysWhichBackendHitIt(unittest.TestCase):
    """An image ceiling thins a book; a model ceiling stops it. Only the second is
    worth telling a human about, and the two need different backoffs.

    `cycle` used to tell them apart by testing for the substring "spend/quota limit"
    in the exception message. Neither backend has ever raised that string — the text
    provider raises "... allowance ceiling: ..." — so the model-side branch was dead
    code and every Claude session limit was announced as "image quota/rate limit
    reached; deferring remaining images ... writing unaffected". Live on 2026-09-01
    that ran for 44 minutes: the wrong backend named, the image backoff taken, and no
    sign of the one line saying a human may need to act."""

    def setUp(self):
        support.wipe_state()

    def _deferral(self, quota):
        """Run one cycle whose only work raises `quota`, and return (wait, log)."""
        series_id = support.drop("quota-probe")
        logged = []

        def boom(_records, _record, log_fn=None):
            raise quota
        original = cycle.series.advance
        cycle.series.advance = boom
        try:
            wait = cycle.run(log_fn=logged.append)
        finally:
            cycle.series.advance = original
        return wait, " ".join(logged), series_id

    def test_a_model_ceiling_is_named_as_the_model(self):
        wait, log, _sid = self._deferral(
            QuotaExceeded("claude allowance ceiling: You've hit your session limit",
                          source="model"))
        self.assertIn("MODEL", log,
                      f"a Claude ceiling must not be reported as an image one: {log}")
        self.assertNotIn("writing unaffected", log,
                         "writing is exactly what IS affected")
        self.assertEqual(wait, config.MODEL_QUOTA_BACKOFF_SEC)

    def test_profile_contention_waits_briefly_and_says_what_it_is(self):
        """The two daemons share one Chrome profile, which can only be open once.

        This used to arrive as `setup` -> NotSignedIn -> a STALL with a DOUBLING
        backoff. That is the worst available response: the loser retreats
        exponentially while the winner renders continuously and never yields, and the
        loser is the process that eventually binds the book. Seen live on 2026-09-01,
        the scribe sat in "waiting to retry" for eight minutes after the revision sweep
        finished, with the illustrator holding the profile throughout.

        It is not a ceiling either, so it must not claim to be one — the fixed short
        wait and an honest line, not the quota message."""
        wait, log, _sid = self._deferral(
            QuotaExceeded("the Chrome profile is in use by pid 123",
                          retry_after=config.IMAGE_BUSY_BACKOFF_SEC, source="busy"))
        # `cycle` waits one second past any retry_after hint, deliberately.
        self.assertGreaterEqual(wait, config.IMAGE_BUSY_BACKOFF_SEC)
        self.assertLessEqual(wait, config.IMAGE_BUSY_BACKOFF_SEC + 2)
        self.assertLess(wait, config.IMAGE_QUOTA_BACKOFF_SEC,
                        "contention must clear faster than a real rate limit")
        self.assertIn("browser is not available", log)
        self.assertNotIn("image quota/rate limit reached", log,
                         "contention is not a ceiling and must not claim to be one")

    def test_an_image_ceiling_still_reads_as_images(self):
        wait, log, _sid = self._deferral(
            QuotaExceeded("gemini session limit: come back later"))
        self.assertIn("image quota", log)
        self.assertEqual(wait, config.IMAGE_QUOTA_BACKOFF_SEC)


if __name__ == "__main__":
    unittest.main()
