"""The operating window: when the harness is allowed to spend model capacity.

The machine shares one `claude` session with its owner, and a harness that drafts
all afternoon is competing with the human for the same limits. So the engine observes
**quiet hours** — a daily window, on chosen weekdays, during which it starts no new
work. It is a pause, never a failure: nothing parks, no status changes, and the run
resumes by itself the moment the window closes.

Pure computation, no I/O, so the whole thing is testable with fixed timestamps.

## Why this does not read the local clock

The machine's idea of "now" in local terms is not trustworthy here. A VPN, a travel
router, or a mis-set timezone can move the system's local time by hours, and the one
guarantee we need is that "9am Central" means 9am in Chicago regardless of what the
host thinks it is. So every decision starts from `datetime.now(timezone.utc)` — which
is unambiguous — and Central time is *derived* from it.

Two derivations, in order of preference:

1. `zoneinfo.ZoneInfo("America/Chicago")`, which is correct by construction and
   tracks any future change to US DST rules.
2. If the tz database is unavailable (a stripped container, a Python built without
   it), explicit arithmetic on the current US rules: CDT (UTC-5) from the second
   Sunday in March at 08:00 UTC to the first Sunday in November at 07:00 UTC, CST
   (UTC-6) otherwise.

The fallback exists because "the daemon crashed at 2am because tzdata was missing"
is a worse outcome than an offset that would need editing if Congress changes the
rules again.
"""

from datetime import date, datetime, timedelta, timezone

from . import config

CENTRAL_TZ = "America/Chicago"


def _nth_weekday(year, month, weekday, n):
    """The date of the `n`th `weekday` (Monday=0) in a month."""
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _explicit_central_offset(moment_utc):
    """Central Time's UTC offset in hours, from the current US DST rules.

    Fallback for hosts with no tz database. DST runs from the second Sunday in March
    at 02:00 local standard (08:00 UTC) to the first Sunday in November at 02:00 local
    daylight (07:00 UTC)."""
    year = moment_utc.year
    sunday = 6
    starts = datetime.combine(_nth_weekday(year, 3, sunday, 2),
                              datetime.min.time(), tzinfo=timezone.utc) \
        + timedelta(hours=8)
    ends = datetime.combine(_nth_weekday(year, 11, sunday, 1),
                            datetime.min.time(), tzinfo=timezone.utc) \
        + timedelta(hours=7)
    return -5 if starts <= moment_utc < ends else -6


def central(moment_utc=None):
    """`moment_utc` expressed in US Central Time, derived from UTC only.

    Accepts an aware or naive datetime (naive is read as UTC) and defaults to now."""
    if moment_utc is None:
        moment_utc = datetime.now(timezone.utc)
    elif moment_utc.tzinfo is None:
        moment_utc = moment_utc.replace(tzinfo=timezone.utc)
    else:
        moment_utc = moment_utc.astimezone(timezone.utc)

    try:                                    # correct by construction when available
        from zoneinfo import ZoneInfo
        return moment_utc.astimezone(ZoneInfo(CENTRAL_TZ))
    except Exception:                       # no tzdata: fall back to the US rules
        offset = timezone(timedelta(hours=_explicit_central_offset(moment_utc)))
        return moment_utc.astimezone(offset)


def quiet_window(moment_utc=None):
    """Whether new work is forbidden right now, and for how many seconds.

    Returns `(is_quiet, seconds_to_nap)`. When quiet, the nap is the time remaining in
    the window, capped at `QUIET_RECHECK_SEC` so the status file keeps refreshing and
    so a daylight-saving change or a corrected clock is noticed promptly rather than
    being slept through. When not quiet, the nap is 0 and the caller proceeds.

    This gates the *start* of work, not work already running. A model call that is
    twenty minutes into drafting a section is not killed at 9am — interrupting it
    would throw the call away and change nothing about capacity already spent. The
    window is a hiring freeze, not a layoff."""
    if not config.QUIET_HOURS_ENABLED:
        return False, 0

    now = central(moment_utc)
    if now.weekday() not in config.QUIET_DAYS:
        return False, 0
    if not config.QUIET_START_HOUR <= now.hour < config.QUIET_END_HOUR:
        return False, 0

    opens_at = now.replace(hour=config.QUIET_END_HOUR, minute=0, second=0,
                           microsecond=0)
    remaining = max(1, int((opens_at - now).total_seconds()))
    return True, min(remaining, config.QUIET_RECHECK_SEC)


def blackout(moment_utc=None):
    """Whether work may start right now. Returns `(blocked, nap_seconds, reason)`.

    One reason, and it is the one that was ever about a person: **quiet hours**. The
    machine shares one Claude seat with the person who owns it, and a harness drafting
    through their Monday afternoon spends capacity they need.

    This used to compose that with a second reason — provider peak pricing, because one
    vendor doubled its rates during its own business hours. Both that vendor and the
    machinery are gone. It is worth recording why, because the guard was correct and
    still cost more than it saved: a pricing blackout only pays for itself while the
    surcharged vendor carries a HIGH-VOLUME role, and it was switched on while the only
    roles routed there were two of the cheapest in the pipeline. It surrendered seven
    hours a day to avoid a surcharge of about twenty cents. A blackout that costs more
    than the thing it avoids is not thrift.

    **Quiet hours are off by default here**, which is the one setting that flips
    relative to the overnight-run harness this grew out of. A paper is an hour or two
    of work, and an author waiting on a Methods section does not want it deferred until
    five o'clock.

    A pause is never a failure. Nothing parks, no status changes, admission and the
    status file keep running, and the run resumes by itself. And it gates the *start*
    of work rather than killing a call in flight: interrupting a request does not
    un-spend what it already spent."""
    if moment_utc is None:
        moment_utc = datetime.now(timezone.utc)
    elif moment_utc.tzinfo is None:
        moment_utc = moment_utc.replace(tzinfo=timezone.utc)
    else:
        moment_utc = moment_utc.astimezone(timezone.utc)

    quiet, nap = quiet_window(moment_utc)
    if quiet:
        return True, nap, describe(moment_utc)
    return False, 0, ""


def describe(moment_utc=None):
    """One line for the log and the phone status file, in Central Time."""
    now = central(moment_utc)
    quiet, nap = quiet_window(moment_utc)
    days = "".join("MTWTFSS"[d] for d in sorted(config.QUIET_DAYS))
    window = (f"{config.QUIET_START_HOUR:02d}:00-{config.QUIET_END_HOUR:02d}:00 "
              f"Central on [{days}]")
    stamp = now.strftime("%a %H:%M %Z").strip() or now.strftime("%a %H:%M")
    if not config.QUIET_HOURS_ENABLED:
        return f"quiet hours disabled (now {stamp})"
    if quiet:
        opens = now.replace(hour=config.QUIET_END_HOUR, minute=0, second=0)
        return (f"paused for quiet hours {window}; now {stamp}, resuming at "
                f"{opens.strftime('%H:%M')} Central (rechecking every {nap}s)")
    return f"outside quiet hours {window}; now {stamp}"
