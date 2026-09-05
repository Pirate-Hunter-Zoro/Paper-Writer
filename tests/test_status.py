"""The status document — the only thing a person reads while a run is in flight.

A pure function of journal records, so it is testable with fixtures and nothing else.
The property worth protecting is that liveness comes from the DATA rather than from
who wrote the file: any process can publish this, so a heartbeat based on "when was
this written" would tick cheerfully while the engine was hung.
"""

import support                                                      # noqa: F401
import unittest                                                     # noqa: E402
from datetime import datetime, timedelta, timezone                  # noqa: E402

from paperwriter import states, status                              # noqa: E402


NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


def _project(status_name, **extra):
    record = {"key": "project/p", "level": "project", "project_id": "p",
              "status": status_name, "created_at": "2026-09-05T10:00:00+00:00",
              "updated_at": "2026-09-05T11:30:00+00:00"}
    record.update(extra)
    return record


def _paper(status_name, **extra):
    record = {"key": "project/p/paper/1", "level": "paper", "project_id": "p",
              "paper_num": 1, "status": status_name,
              "created_at": "2026-09-05T10:05:00+00:00",
              "updated_at": "2026-09-05T11:30:00+00:00"}
    record.update(extra)
    return record


def _section(n, status_name, **extra):
    record = {"key": f"project/p/paper/1/section/{n}", "level": "section",
              "project_id": "p", "paper_num": 1, "section_num": n,
              "status": status_name, "created_at": "2026-09-05T10:06:00+00:00",
              "updated_at": "2026-09-05T11:30:00+00:00"}
    record.update(extra)
    return record


class StatusTests(unittest.TestCase):

    def test_an_empty_journal_says_nothing_is_running(self):
        text = status.render({}, NOW)
        self.assertIn("Nothing running", text)
        self.assertIn("_TEMPLATE.md", text)

    def test_a_long_gap_is_explained_by_the_stage(self):
        """Gathering journals nothing while it runs. Without this the reader sees a
        growing silence and reads it as a hang."""
        records = {"project/p": _project(states.GATHERING)}
        text = status.render(records, NOW)
        self.assertIn("GATHERING EVIDENCE", text)
        self.assertIn("journals nothing while it runs", text)

    def test_progress_is_counted_from_durable_sections(self):
        records = {
            "project/p": _project(states.PAPERS_IN_PROGRESS),
            "project/p/paper/1": _paper(states.DRAFTING, section_count=5),
            "project/p/paper/1/section/1": _section(1, states.LEDGER_MERGED),
            "project/p/paper/1/section/2": _section(2, states.ACCEPTED),
            "project/p/paper/1/section/3": _section(3, states.PENDING),
        }
        self.assertIn("2 of 5 sections written", status.render(records, NOW))

    def test_a_flagged_section_reads_as_progress_not_damage(self):
        records = {
            "project/p": _project(states.PAPERS_IN_PROGRESS),
            "project/p/paper/1": _paper(states.DRAFTING, section_count=2),
            "project/p/paper/1/section/1": _section(
                1, states.LEDGER_MERGED, outstanding_issues=["NUMBER: 0.99"]),
        }
        self.assertIn("awaiting the revision sweep", status.render(records, NOW))

    def test_a_stall_says_no_action_is_needed(self):
        records = {"project/p": _project(states.STALLED, error="provider timed out")}
        text = status.render(records, NOW)
        self.assertIn("RETRYING", text)
        self.assertIn("provider timed out", text)
        self.assertIn("no action is needed", text)

    def test_a_pause_is_distinguished_from_a_hang(self):
        text = status.render({"project/p": _project(states.PAPERS_IN_PROGRESS)}, NOW,
                             paused_reason="quiet hours until 17:00")
        self.assertIn("Paused", text)
        self.assertIn("Nothing has failed", text)

    def test_liveness_comes_from_the_newest_journal_write(self):
        stale = _project(states.DRAFTING,
                         updated_at=(NOW - timedelta(hours=6)).isoformat())
        text = status.render({"project/p": stale}, NOW)
        self.assertIn("hours ago", text)

    def test_a_finished_project_names_where_the_manuscript_is(self):
        text = status.render({"project/p": _project(states.PROJECT_COMPLETE)}, NOW)
        self.assertIn("DELIVERED", text)
        self.assertIn("output folder", text)


if __name__ == "__main__":
    unittest.main()
