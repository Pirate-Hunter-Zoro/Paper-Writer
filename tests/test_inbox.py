"""The drop folder may be on a mount, so the local filesystem is not always prompt.

Two silent failure modes, both of which would look like "nothing happened":

  * a prompt is observed mid-write, and admitting it truncated would freeze evidence
    against half a brief while looking perfectly successful;
  * a directory listing hangs rather than failing, which is worse than an error
    because there is nothing in the log to notice.

The eviction machinery this module used to test — iCloud placeholder files and
`brctl` — is gone with the Mac mini it was written for. See `infra/inbox.py`.
"""

import os
import time
import unittest
from pathlib import Path

import support

from paperwriter import config, states                                 # noqa: E402
from paperwriter.engine import admission                               # noqa: E402
from paperwriter.infra import inbox, journal                          # noqa: E402


class SettleTests(unittest.TestCase):
    def setUp(self):
        support.wipe_state()
        config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        self.path = config.INBOX_DIR / "job.md"

    def _age(self, path, seconds):
        """Backdate mtime so the file reads as having settled `seconds` ago."""
        stamp = time.time() - seconds
        os.utime(path, (stamp, stamp))

    def test_a_fresh_write_is_not_yet_settled(self):
        self.path.write_text("content", encoding="utf-8")
        self.assertFalse(inbox.is_settled(self.path))

    def test_an_aged_nonempty_file_is_settled(self):
        self.path.write_text("content", encoding="utf-8")
        self._age(self.path, config.INBOX_SETTLE_SEC + 5)
        self.assertTrue(inbox.is_settled(self.path))

    def test_an_empty_file_never_settles(self):
        """A zero-byte file is the classic shape of a sync that has not delivered."""
        self.path.write_text("", encoding="utf-8")
        self._age(self.path, config.INBOX_SETTLE_SEC + 60)
        self.assertFalse(inbox.is_settled(self.path))

    def test_a_missing_file_is_not_settled(self):
        self.assertFalse(inbox.is_settled(config.INBOX_DIR / "absent.md"))

    def test_admission_waits_for_a_prompt_to_settle(self):
        support.drop("still-arriving", settled=False)          # written just now
        records = journal.load_records()
        admission.register_inbox(records, log_fn=lambda _m: None)
        self.assertEqual(records, {}, "a mid-write prompt must not be admitted")

        self._age(config.INBOX_DIR / "still-arriving.md", config.INBOX_SETTLE_SEC + 5)
        admission.register_inbox(records, log_fn=lambda _m: None)
        self.assertIn(journal.project_key("still-arriving"), records)
        self.assertEqual(records[journal.project_key("still-arriving")]["status"],
                         states.PROMPT_DROPPED)


class ScanDeadlineTests(unittest.TestCase):
    """The worst failure this design can have: a listing that blocks forever — no
    error, no log, no progress, lock still held. Everything else here fails loudly.
    An unresponsive mount fails in silence, which is why the listing has a deadline."""

    def setUp(self):
        support.wipe_state()
        config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        inbox.reset_scan_backoff()
        self.addCleanup(inbox.reset_scan_backoff)

    def test_a_readable_folder_returns_its_jobs(self):
        support.drop("real")
        listing = inbox.scan(config.INBOX_DIR, ".md")
        self.assertEqual([p.name for p in listing.jobs], ["real.md"])

    def test_an_empty_folder_and_an_unreadable_one_are_distinguishable(self):
        """`[]` means no work; `None` means the question is still open. Conflating them
        is how a permission problem gets mistaken for an idle queue."""
        self.assertEqual(inbox.scan(config.INBOX_DIR, ".md").jobs, [])

        walled = Path(config.STATE_DIR) / "walled-off"
        walled.mkdir(parents=True, exist_ok=True)
        walled.chmod(0o000)
        self.addCleanup(lambda: walled.chmod(0o700))
        if os.access(walled, os.R_OK):
            self.skipTest("running with rights that ignore directory permissions")
        messages = []
        self.assertIsNone(inbox.scan(walled, ".md", log_fn=messages.append))
        self.assertTrue(any("could not be listed" in m for m in messages))

    def test_a_hung_listing_times_out_instead_of_wedging(self):
        messages = []
        original_timeout, inbox.SCAN_TIMEOUT_SEC = inbox.SCAN_TIMEOUT_SEC, 1
        original_glob = inbox.os.listdir

        def hang(_directory):
            time.sleep(30)                       # the blocked syscall, simulated
            return []

        inbox.os.listdir = hang
        try:
            started = time.time()
            self.assertIsNone(
                inbox.scan(config.INBOX_DIR, ".md", log_fn=messages.append))
            self.assertLess(time.time() - started, 10, "scan must not wait it out")
        finally:
            inbox.os.listdir = original_glob
            inbox.SCAN_TIMEOUT_SEC = original_timeout
        self.assertTrue(any("hung filesystem" in m for m in messages),
                        "the operator must be told this is a hang, not an empty queue")

    def test_a_timeout_backs_off_rather_than_retrying_every_cycle(self):
        original_timeout, inbox.SCAN_TIMEOUT_SEC = inbox.SCAN_TIMEOUT_SEC, 1
        original_glob = inbox.os.listdir
        calls = {"n": 0}

        def hang(_directory):
            calls["n"] += 1
            time.sleep(30)
            return []

        inbox.os.listdir = hang
        try:
            inbox.scan(config.INBOX_DIR, ".md")
            self.assertEqual(calls["n"], 1)
            inbox.scan(config.INBOX_DIR, ".md")     # inside the backoff window
            self.assertEqual(calls["n"], 1, "must not spawn a thread per cycle")
        finally:
            inbox.os.listdir = original_glob
            inbox.SCAN_TIMEOUT_SEC = original_timeout

    def test_an_unreadable_folder_does_not_disturb_work_already_journaled(self):
        """A permission problem must cost new drops only, never the running job."""
        support.stub_model_seams()
        support.drop("already-running")
        records = journal.load_records()
        admission.register_inbox(records, log_fn=lambda _m: None)
        self.assertIn(journal.project_key("already-running"), records)

        original = inbox.scan
        inbox.scan = lambda *a, **k: None           # folder goes unreadable
        try:
            self.assertEqual(support.run_engine("already-running"),
                             states.PROJECT_COMPLETE)
        finally:
            inbox.scan = original


