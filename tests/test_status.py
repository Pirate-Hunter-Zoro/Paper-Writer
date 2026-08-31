"""The phone-readable status file.

The drop folder already answers "did it stop?" by itself — a prompt in `failed/`. What
it could not answer is the case you are in most of the time: still running, hours from
done, with no way to tell "writing chapter 12" from "wedged since midnight".
"""

import unittest
from datetime import datetime, timedelta, timezone

import support

from fanfic import config, paths, states, status                   # noqa: E402
from fanfic.engine import cycle                                    # noqa: E402
from fanfic.infra import icloud, journal                           # noqa: E402

NOW = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)


def _at(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


class RenderTests(unittest.TestCase):
    """`render` is a pure function of journal records, so every state is cheap to pin."""

    def _series(self, status_name, **fields):
        record = journal.new_series("swtor", "/x/swtor.md", "p")
        record.update({"status": status_name, "updated_at": _at(3)})
        record.update(fields)
        return {record["key"]: record}

    def test_liveness_comes_from_the_journal_not_the_writer(self):
        """The whole point: any daemon can write this file, so a "last written"
        heartbeat would tick along happily while the engine was hung."""
        records = self._series(states.RESEARCHING)
        records["series/swtor"]["updated_at"] = _at(240)
        text = status.render(records, NOW)
        self.assertIn("4.0 hours ago", text)

    def test_a_long_gap_in_research_is_explained_not_alarming(self):
        text = status.render(self._series(states.RESEARCHING), NOW)
        self.assertIn("RESEARCHING", text)
        self.assertIn("mining the source wikis", text)
        self.assertIn("journals nothing while it runs", text)
        self.assertIn("it is working", text)

    def test_a_stall_names_the_reason_and_says_no_action_is_needed(self):
        """A stall is a wait, not a stop, and the status file has to read that way —
        the old wording told the reader to go and move a file, which is now a thing
        the engine does for itself."""
        text = status.render(
            self._series(states.STALLED, error="canon coverage 61% below 85% floor"),
            NOW)
        self.assertIn("RETRYING", text)
        self.assertIn("coverage 61%", text)
        self.assertIn("no action is needed", text)
        self.assertIn("retries by itself", text)
        self.assertNotIn("STOPPED", text)

    def test_chapter_progress_is_the_headline_while_drafting(self):
        records = self._series(states.BOOKS_IN_PROGRESS)
        book = journal.new_book("swtor", 1, "Hero of Tython")
        book.update({"status": states.DRAFTING, "chapter_count": 37,
                     "updated_at": _at(2)})
        records[book["key"]] = book
        for n in range(1, 38):
            chapter = journal.new_chapter("swtor", 1, n)
            chapter["status"] = (states.BIBLE_MERGED if n <= 12 else states.PENDING)
            chapter["updated_at"] = _at(2)
            records[chapter["key"]] = chapter

        text = status.render(records, NOW)
        self.assertIn("12 of 37 chapters written", text)

    def test_a_chapter_awaiting_the_sweep_is_surfaced_as_progress(self):
        """A chapter that shipped holding notes is written, on disk, and queued for
        the revision sweep. Calling that "parked" described a machine that no longer
        exists and read as damage."""
        records = self._series(states.BOOKS_IN_PROGRESS)
        book = journal.new_book("swtor", 1)
        book.update({"status": states.DRAFTING, "chapter_count": 3})
        records[book["key"]] = book
        for n, st in enumerate((states.BIBLE_MERGED, states.BIBLE_MERGED,
                                states.PENDING), start=1):
            chapter = journal.new_chapter("swtor", 1, n)
            chapter["status"] = st
            if n == 2:
                chapter["outstanding_issues"] = ["CONTINUITY: the clock slips"]
            records[chapter["key"]] = chapter
        text = status.render(records, NOW)
        self.assertIn("2 of 3 chapters written", text)
        self.assertIn("1 awaiting the revision sweep", text)

    def test_delivery_says_where_the_book_is(self):
        text = status.render(self._series(states.SERIES_COMPLETE), NOW)
        self.assertIn("DELIVERED", text)
        self.assertIn("<fandom>/<series>", text)

    def test_an_empty_journal_invites_a_drop(self):
        text = status.render({}, NOW)
        self.assertIn("Nothing running", text)
        self.assertIn("_TEMPLATE.md", text)


class PublishTests(unittest.TestCase):
    def setUp(self):
        support.wipe_state()
        config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        icloud.reset_scan_backoff()
        self.addCleanup(icloud.reset_scan_backoff)

    def test_it_lands_in_the_drop_folder_and_is_never_a_job(self):
        from fanfic.engine import admission
        cycle.publish_status(journal.load_records(), log_fn=lambda _m: None)
        path = paths.status_file()
        self.assertTrue(path.exists())
        self.assertEqual(path.parent, config.INBOX_DIR)
        self.assertFalse(admission.is_job_file(path),
                         "the status file must never be admitted as a novel")

    def test_an_unchanged_status_is_not_rewritten(self):
        """It lands in iCloud, so rewriting identical bytes every few seconds would
        churn sync for nothing."""
        path = paths.status_file()
        text = status.render({}, NOW)
        self.assertTrue(icloud.publish(path, text))
        self.assertFalse(icloud.publish(path, text), "identical write must be skipped")
        self.assertTrue(icloud.publish(path, text + "\nchanged\n"))

    def test_a_blocked_write_never_breaks_the_cycle(self):
        original = icloud.SCAN_TIMEOUT_SEC
        icloud.SCAN_TIMEOUT_SEC = 1
        messages = []

        class Wedged:
            parent = config.INBOX_DIR

            def exists(self):
                import time
                time.sleep(30)                    # the blocked syscall, simulated
                return False

        try:
            self.assertFalse(icloud.publish(Wedged(), "text", log_fn=messages.append))
        finally:
            icloud.SCAN_TIMEOUT_SEC = original
        self.assertTrue(any("did not respond" in m for m in messages))

    def test_the_status_survives_a_real_run_end_to_end(self):
        support.stub_model_seams()
        support.drop("status-demo")
        self.assertEqual(support.run_engine("status-demo"), states.SERIES_COMPLETE)
        text = paths.status_file().read_text(encoding="utf-8")
        self.assertIn("status-demo", text)
        self.assertIn("DELIVERED", text)



class WaypointTests(unittest.TestCase):
    """A headline with nothing under it is a bad answer to "what is happening" — and it
    is what the reader sees whenever the engine is one step ahead of the last published
    snapshot, which is every long stage."""

    def test_every_non_terminal_series_state_says_something(self):
        for name in (states.PROMPT_DROPPED, states.RESEARCHING, states.RESEARCHED,
                     states.SERIES_PLANNING, states.SERIES_PLANNED,
                     states.BOOKS_IN_PROGRESS):
            record = journal.new_series("swtor", "/x/swtor.md", "p")
            record.update({"status": name, "updated_at": _at(1)})
            text = status.render({record["key"]: record}, NOW)
            self.assertIn("Currently ", text,
                          f"{name} renders with an empty body")
            self.assertIn("expect ", text)

if __name__ == "__main__":
    unittest.main(verbosity=2)
