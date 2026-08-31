"""The drop folder lives in iCloud, so the filesystem is no longer the authority.

Two silent failure modes, both of which would look like "nothing happened":

  * iCloud evicts a prompt's contents, so a `*.md` glob stops seeing a job that is
    definitely still there;
  * a prompt is observed mid-write or mid-sync, and admitting it truncated would
    freeze canon against half a brief while looking perfectly successful.
"""

import os
import time
import unittest
from pathlib import Path

import support

from fanfic import config, states                                 # noqa: E402
from fanfic.engine import admission                               # noqa: E402
from fanfic.infra import icloud, journal                          # noqa: E402


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
        self.assertFalse(icloud.is_settled(self.path))

    def test_an_aged_nonempty_file_is_settled(self):
        self.path.write_text("content", encoding="utf-8")
        self._age(self.path, config.INBOX_SETTLE_SEC + 5)
        self.assertTrue(icloud.is_settled(self.path))

    def test_an_empty_file_never_settles(self):
        """A zero-byte file is the classic shape of a sync that has not delivered."""
        self.path.write_text("", encoding="utf-8")
        self._age(self.path, config.INBOX_SETTLE_SEC + 60)
        self.assertFalse(icloud.is_settled(self.path))

    def test_a_missing_file_is_not_settled(self):
        self.assertFalse(icloud.is_settled(config.INBOX_DIR / "absent.md"))

    def test_admission_waits_for_a_prompt_to_settle(self):
        support.drop("still-arriving", settled=False)          # written just now
        records = journal.load_records()
        admission.register_inbox(records, log_fn=lambda _m: None)
        self.assertEqual(records, {}, "a mid-write prompt must not be admitted")

        self._age(config.INBOX_DIR / "still-arriving.md", config.INBOX_SETTLE_SEC + 5)
        admission.register_inbox(records, log_fn=lambda _m: None)
        self.assertIn(journal.series_key("still-arriving"), records)
        self.assertEqual(records[journal.series_key("still-arriving")]["status"],
                         states.PROMPT_DROPPED)


class ScanDeadlineTests(unittest.TestCase):
    """The worst failure this system has produced: enumerating the iCloud drop folder
    from a launchd agent blocked in `open()` forever — no error, no log, no progress,
    lock still held — because macOS denies it in a way Homebrew Python waits on rather
    than raising. Everything else in this design fails loudly; that failed in silence."""

    def setUp(self):
        support.wipe_state()
        config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        icloud.reset_scan_backoff()
        self.addCleanup(icloud.reset_scan_backoff)

    def test_a_readable_folder_returns_its_jobs(self):
        support.drop("real")
        listing = icloud.scan(config.INBOX_DIR, ".md")
        self.assertEqual([p.name for p in listing.jobs], ["real.md"])
        self.assertEqual(listing.evicted, [])

    def test_an_empty_folder_and_an_unreadable_one_are_distinguishable(self):
        """`[]` means no work; `None` means the question is still open. Conflating them
        is how a permission problem gets mistaken for an idle queue."""
        self.assertEqual(icloud.scan(config.INBOX_DIR, ".md").jobs, [])

        walled = Path(config.STATE_DIR) / "walled-off"
        walled.mkdir(parents=True, exist_ok=True)
        walled.chmod(0o000)
        self.addCleanup(lambda: walled.chmod(0o700))
        if os.access(walled, os.R_OK):
            self.skipTest("running with rights that ignore directory permissions")
        messages = []
        self.assertIsNone(icloud.scan(walled, ".md", log_fn=messages.append))
        self.assertTrue(any("could not be listed" in m for m in messages))

    def test_a_hung_listing_times_out_instead_of_wedging(self):
        messages = []
        original_timeout, icloud.SCAN_TIMEOUT_SEC = icloud.SCAN_TIMEOUT_SEC, 1
        original_glob = icloud.os.listdir

        def hang(_directory):
            time.sleep(30)                       # the blocked syscall, simulated
            return []

        icloud.os.listdir = hang
        try:
            started = time.time()
            self.assertIsNone(
                icloud.scan(config.INBOX_DIR, ".md", log_fn=messages.append))
            self.assertLess(time.time() - started, 10, "scan must not wait it out")
        finally:
            icloud.os.listdir = original_glob
            icloud.SCAN_TIMEOUT_SEC = original_timeout
        self.assertTrue(any("Full Disk Access" in m for m in messages),
                        "the operator must be told the actual cause")

    def test_a_timeout_backs_off_rather_than_retrying_every_cycle(self):
        original_timeout, icloud.SCAN_TIMEOUT_SEC = icloud.SCAN_TIMEOUT_SEC, 1
        original_glob = icloud.os.listdir
        calls = {"n": 0}

        def hang(_directory):
            calls["n"] += 1
            time.sleep(30)
            return []

        icloud.os.listdir = hang
        try:
            icloud.scan(config.INBOX_DIR, ".md")
            self.assertEqual(calls["n"], 1)
            icloud.scan(config.INBOX_DIR, ".md")     # inside the backoff window
            self.assertEqual(calls["n"], 1, "must not spawn a thread per cycle")
        finally:
            icloud.os.listdir = original_glob
            icloud.SCAN_TIMEOUT_SEC = original_timeout

    def test_an_unreadable_folder_does_not_disturb_work_already_journaled(self):
        """A permission problem must cost new drops only, never the running job."""
        support.stub_model_seams()
        support.drop("already-running")
        records = journal.load_records()
        admission.register_inbox(records, log_fn=lambda _m: None)
        self.assertIn(journal.series_key("already-running"), records)

        original = icloud.scan
        icloud.scan = lambda *a, **k: None           # folder goes unreadable
        try:
            self.assertEqual(support.run_engine("already-running"),
                             states.SERIES_COMPLETE)
        finally:
            icloud.scan = original


class EvictionTests(unittest.TestCase):
    def setUp(self):
        support.wipe_state()
        config.INBOX_DIR.mkdir(parents=True, exist_ok=True)

    def test_placeholder_naming_matches_what_iCloud_writes(self):
        self.assertEqual(icloud.placeholder_for(Path("/x/foo.md")).name,
                         ".foo.md.icloud")

    def test_an_evicted_job_is_seen_and_requested_not_ignored(self):
        """The real filename is what the caller cares about, not the stub."""
        (config.INBOX_DIR / ".swtor-jedi-knight.md.icloud").write_text(
            "stub", encoding="utf-8")
        self.assertEqual(icloud.evicted_names(config.INBOX_DIR),
                         ["swtor-jedi-knight.md"])

        asked = []
        original = icloud.request_download
        icloud.request_download = lambda p, log_fn=None: asked.append(Path(p).name) or True
        try:
            requested = icloud.materialise_evicted(config.INBOX_DIR, ".md")
        finally:
            icloud.request_download = original
        self.assertEqual(asked, ["swtor-jedi-knight.md"])
        self.assertEqual(requested, ["swtor-jedi-knight.md"])

    def test_a_stub_is_never_itself_admitted_as_a_job(self):
        """`.foo.md.icloud` is dot-prefixed, so `is_job_file` rejects it even if a
        glob ever reached it — a job named ".swtor" would be nonsense."""
        stub = config.INBOX_DIR / ".swtor-jedi-knight.md.icloud"
        stub.write_text("stub", encoding="utf-8")
        self.assertFalse(admission.is_job_file(stub))

        records = journal.load_records()
        admission.register_inbox(records, log_fn=lambda _m: None)
        self.assertEqual(records, {})

    def test_a_missing_brctl_is_patience_not_a_crash(self):
        original = icloud.BRCTL
        icloud.BRCTL = "/nonexistent/brctl"
        try:
            self.assertFalse(
                icloud.request_download(config.INBOX_DIR / "x.md",
                                        log_fn=lambda _m: None))
        finally:
            icloud.BRCTL = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
