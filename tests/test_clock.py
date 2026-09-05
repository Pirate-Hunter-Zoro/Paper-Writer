"""The operating window, and the usage meter.

Both exist because of one morning: the fleet consumed the owner's shared `claude`
allowance drafting a novel through a working day, hit a ceiling six chapters in, and
nobody could say how heavy the run had been.

Every case here is a fixed UTC instant, because the whole point of `clock` is that
the answer must not depend on the host's local timezone — a VPN or a mis-set clock
must not be able to move 9am Central.
"""

import support                                    # noqa: F401  (redirects state first)

import os
import unittest
from datetime import datetime, timezone

from paperwriter import clock, config
from paperwriter.infra import budget


def utc(iso):
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


class CentralTimeDerivation(unittest.TestCase):
    """Central Time is derived from UTC, never read from the host."""

    def test_summer_instant_is_cdt(self):
        self.assertEqual(clock.central(utc("2026-08-05T14:30:00")).hour, 9)

    def test_winter_instant_is_cst(self):
        self.assertEqual(clock.central(utc("2026-01-14T15:30:00")).hour, 9)

    def test_a_naive_datetime_is_read_as_utc_not_as_local(self):
        """The single most important property: no local-clock dependence anywhere."""
        naive = datetime.fromisoformat("2026-08-05T14:30:00")
        self.assertEqual(clock.central(naive).hour, clock.central(utc(
            "2026-08-05T14:30:00")).hour)

    def test_the_explicit_fallback_agrees_with_the_tz_database(self):
        """The no-tzdata path must not quietly disagree with the correct one."""
        for iso in ("2026-01-14T15:30:00", "2026-08-05T14:30:00",
                    "2026-03-08T09:00:00", "2026-11-01T06:00:00",
                    "2026-06-30T23:00:00", "2026-12-25T12:00:00"):
            moment = utc(iso)
            expected = clock.central(moment).utcoffset().total_seconds() / 3600
            self.assertEqual(clock._explicit_central_offset(moment), expected, iso)

    def test_dst_boundaries_land_on_the_right_side(self):
        # DST begins 2026-03-08 at 08:00 UTC; ends 2026-11-01 at 07:00 UTC.
        self.assertEqual(clock._explicit_central_offset(utc("2026-03-08T07:59:00")), -6)
        self.assertEqual(clock._explicit_central_offset(utc("2026-03-08T08:00:00")), -5)
        self.assertEqual(clock._explicit_central_offset(utc("2026-11-01T06:59:00")), -5)
        self.assertEqual(clock._explicit_central_offset(utc("2026-11-01T07:00:00")), -6)


class QuietWindow(unittest.TestCase):
    """The suite disables quiet hours globally so that no *other* test depends on what
    time of day it runs — see `support`. The tests that are actually about the window
    turn it back on for their own duration."""

    def setUp(self):
        self._prior = config.QUIET_HOURS_ENABLED
        config.QUIET_HOURS_ENABLED = True

    def tearDown(self):
        config.QUIET_HOURS_ENABLED = self._prior

    """09:00-17:00 Central, Monday to Friday: no new work."""

    def test_a_weekday_morning_inside_the_window_is_quiet(self):
        quiet, nap = clock.quiet_window(utc("2026-08-05T14:30:00"))   # Wed 09:30 CDT
        self.assertTrue(quiet)
        self.assertGreater(nap, 0)

    def test_one_minute_before_the_window_is_allowed(self):
        quiet, _ = clock.quiet_window(utc("2026-08-05T13:59:00"))     # Wed 08:59 CDT
        self.assertFalse(quiet)

    def test_the_closing_hour_itself_is_allowed(self):
        """17:00 is when work resumes, not the last minute of the ban."""
        quiet, _ = clock.quiet_window(utc("2026-08-05T22:00:00"))     # Wed 17:00 CDT
        self.assertFalse(quiet)

    def test_the_last_minute_of_the_window_is_still_quiet(self):
        quiet, _ = clock.quiet_window(utc("2026-08-05T21:59:00"))     # Wed 16:59 CDT
        self.assertTrue(quiet)

    def test_nights_are_allowed(self):
        for iso in ("2026-08-05T02:00:00", "2026-08-05T11:00:00",
                    "2026-08-06T05:00:00"):
            self.assertFalse(clock.quiet_window(utc(iso))[0], iso)

    def test_weekends_are_allowed_all_day(self):
        # Sat 2026-08-08 and Sun 2026-08-09, both 10:00 Central.
        for iso in ("2026-08-08T15:00:00", "2026-08-09T15:00:00"):
            quiet, _ = clock.quiet_window(utc(iso))
            self.assertFalse(quiet, iso)

    def test_winter_uses_the_same_central_wall_clock(self):
        """The ban is 9-5 Central year round, so the UTC hour it maps to must shift."""
        self.assertTrue(clock.quiet_window(utc("2026-01-14T15:30:00"))[0])   # 09:30 CST
        self.assertFalse(clock.quiet_window(utc("2026-01-14T14:30:00"))[0])  # 08:30 CST

    def test_the_nap_is_capped_so_the_status_file_stays_fresh(self):
        """A single eight-hour sleep would leave the phone status stale and would sleep
        through a corrected clock or a DST change."""
        _, nap = clock.quiet_window(utc("2026-08-05T14:00:00"))
        self.assertLessEqual(nap, config.QUIET_RECHECK_SEC)

    def test_disabling_it_opens_everything(self):
        original = config.QUIET_HOURS_ENABLED
        config.QUIET_HOURS_ENABLED = False
        try:
            self.assertFalse(clock.quiet_window(utc("2026-08-05T14:30:00"))[0])
        finally:
            config.QUIET_HOURS_ENABLED = original

    def test_describe_names_the_window_and_the_resume_time(self):
        text = clock.describe(utc("2026-08-05T14:30:00"))
        self.assertIn("paused", text)
        self.assertIn("17:00", text)


class UsageMeter(unittest.TestCase):
    """How much allowance a novel burns — a meter reading, never a bill.

    The `claude` CLI reports `total_cost_usd` whether it authenticates by API key or by
    logged-in session. This project has no API key anywhere, so the figure is a
    list-price valuation of token usage, not money charged. Recorded because it is the
    only available signal for run weight; named so nobody reads it as spend."""

    def setUp(self):
        support.wipe_state()
        path = support.paths.usage_log()
        if path.exists():
            path.unlink()

    def test_usage_accumulates_into_a_running_total(self):
        self.assertAlmostEqual(budget.record_usage(0.10, "draft"), 0.10, places=4)
        self.assertAlmostEqual(budget.record_usage(0.25, "critique"), 0.35, places=4)
        self.assertAlmostEqual(budget.usage_valued(), 0.35, places=4)

    def test_nothing_recorded_reads_as_zero_not_as_an_error(self):
        self.assertEqual(budget.usage_valued(), 0.0)

    def test_junk_and_zero_amounts_are_ignored(self):
        for bad in (None, "abc", 0, -1):
            self.assertIsNone(budget.record_usage(bad, "x"))
        self.assertEqual(budget.usage_valued(), 0.0)

    def test_a_torn_line_does_not_break_the_total(self):
        budget.record_usage(0.10, "good")
        with support.paths.usage_log().open("a", encoding="utf-8") as handle:
            handle.write('{"list_price_usd": 0.5, "label": "tor\n')     # truncated write
        budget.record_usage(0.10, "also good")
        self.assertAlmostEqual(budget.usage_valued(), 0.20, places=4)

    def test_the_meter_never_gates_work(self):
        """`remaining()` is still the hand-managed ceiling; metering is reporting only —
        and it must never be mistaken for a spend gate, since it measures no spend."""
        budget.record_usage(999.0, "heavy")
        self.assertTrue(budget.can_start_unit())

    def test_the_recorded_field_is_named_for_what_it_measures(self):
        """`usd` invited exactly the misreading this class exists to prevent."""
        import json
        budget.record_usage(0.42, "draft")
        entry = json.loads(support.paths.usage_log().read_text().splitlines()[0])
        self.assertIn("list_price_usd", entry)
        self.assertNotIn("usd", entry)


class ThePauseIsOnlyEverAboutThePerson(unittest.TestCase):
    """There used to be a second reason the fleet declined to start work: a vendor's
    peak-pricing window, when that vendor doubled its rates during its own business
    hours. It and the vendor are both gone, and this class holds the receipt.

    The guard was correctly implemented and still cost more than it saved. It only
    pays for itself while a surcharged vendor carries a HIGH-VOLUME role, and it was
    switched on while the only roles routed there were `bible_merge` and
    `art_direction` — a few cents a book. It handed that vendor a veto over seven
    hours a day of illustrating, to avoid a surcharge of about twenty cents.

    What survives is the pause that was always about a person rather than a wallet."""

    def setUp(self):
        self._prior = config.QUIET_HOURS_ENABLED
        config.QUIET_HOURS_ENABLED = True

    def tearDown(self):
        config.QUIET_HOURS_ENABLED = self._prior

    def test_blackout_takes_no_provider_argument_any_more(self):
        # The signature is the assertion: nothing can ask for a vendor to be waited
        # out, because there is no vendor to wait out. A datetime is the only argument
        # it takes, and a tuple of provider names is not one.
        with self.assertRaises((TypeError, AttributeError)):
            clock.blackout(("deepseek",))

    def test_a_weekend_is_open_at_every_hour_of_the_day(self):
        # Under the old arrangement 01:00-04:00 and 06:00-10:00 UTC were blocked every
        # single day, weekends included — seven hours a day, for a vendor this fleet no
        # longer has and a surcharge it never paid.
        for hour in range(24):
            blocked, _, _ = clock.blackout(utc(f"2026-08-08T{hour:02d}:30:00"))
            self.assertFalse(blocked, f"{hour:02d}:30 UTC on a Saturday")

    def test_quiet_hours_still_block_and_still_say_why(self):
        blocked, nap, why = clock.blackout(utc("2026-08-10T16:00:00"))  # Mon 11:00 CDT
        self.assertTrue(blocked)
        self.assertGreater(nap, 0)
        self.assertIn("quiet hours", why)


if __name__ == "__main__":
    unittest.main()
