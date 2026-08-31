"""One turn of the engine: admit new work, check the budget, advance one series.

Returns how long to nap, so the daemon loop stays a three-liner and the decision
about pacing lives with the decision about work. Exactly one series advances per
cycle: that is the ceiling that makes a runaway impossible to hide, since every unit
of spend is one journal line and one log line.
"""

from datetime import datetime, timezone

from .. import clock, config, paths, states, status
from ..errors import QuotaExceeded
from ..infra import budget, icloud, journal
from . import admission, series, stalling


def publish_status(records, log_fn=print, paused_reason=None):
    """Refresh the phone-readable status file in the drop folder.

    Best-effort by construction: it is a convenience, and `icloud.publish` skips an
    unchanged write, bounds itself with a deadline, and never raises. Called before the
    work rather than after, so a stage that blocks for forty minutes has already
    published what it is about to do."""
    path = paths.status_file()
    if path is None:
        return
    icloud.publish(path, status.render(records, datetime.now(timezone.utc),
                                      paused_reason=paused_reason),
                   log_fn=log_fn)


def run(log_fn=print):
    """Advance the fleet by one step. Returns the number of seconds to sleep."""
    records = journal.load_records()
    admission.register_inbox(records, log_fn=log_fn)
    publish_status(records, log_fn=log_fn)

    # Blackout windows gate the START of work only, and sit AFTER admission and the
    # status publish on purpose: a prompt dropped from the phone at lunchtime should
    # still be admitted and still show up in `_STATUS.md`, it just does not get drafted
    # until the window closes. Nothing parks; this is a pause.
    #
    # One reason left: the owner's quiet hours. There used to be a second — a vendor's
    # peak-pricing window — and both it and the vendor are gone; see `clock.blackout`.
    blocked, nap, reason = clock.blackout()
    if blocked:
        log_fn(reason)
        # Republish saying *why*, so the phone shows "paused for quiet hours" rather
        # than a growing silence that reads as a hang.
        publish_status(records, log_fn=log_fn, paused_reason=reason)
        return nap

    if not budget.can_start_unit():
        log_fn("API budget exhausted; idling.")
        return config.IDLE_INTERVAL_SEC

    active = sorted(
        (r for r in records.values()
         if r.get("level") == "series" and r["status"] in states.ACTIVE_SERIES),
        key=lambda r: r.get("created_at", ""))
    # A stalled series waiting out its backoff is not idle and is not finished; it is
    # simply not this cycle's work. Stepping over it lets a second novel keep running,
    # and — because nothing else here is dispatchable either when it is the only job —
    # keeps the engine from spinning at the fast poll interval doing nothing.
    ready = [r for r in active if stalling.due(r)]
    if not ready:
        if active:
            log_fn(f"{len(active)} series waiting to retry; nothing else to do.")
        return config.IDLE_INTERVAL_SEC

    try:
        series.advance(records, ready[0], log_fn=log_fn)
    except QuotaExceeded as quota:
        # Never a failure, from either backend. Nothing is parked, no status changes,
        # and the unit is picked up again on a later cycle — so the run resumes by
        # itself the moment the ceiling lifts, with no re-drop and no lost work.
        model_side = "spend/quota limit" in str(quota)
        wait = (config.MODEL_QUOTA_BACKOFF_SEC if model_side
                else config.IMAGE_QUOTA_BACKOFF_SEC)
        if quota.retry_after:
            wait = max(wait, int(quota.retry_after) + 1)
        if model_side:
            # The prose/judgment backend. This stops the book rather than thinning it,
            # so say plainly that a human has to lift the ceiling — and that waiting is
            # the correct behaviour, not a hang.
            log_fn(f"MODEL spend/quota ceiling reached; nothing parked, deferring and "
                   f"retrying every {wait}s until it lifts. Raise the limit (or wait "
                   f"for the period to roll over) and the run continues on its own: "
                   f"{quota}")
        else:
            log_fn(f"image quota/rate limit reached; deferring remaining images, "
                   f"retrying in {wait}s (book stays ILLUSTRATING, writing unaffected)")
        return wait
    finally:
        # Publish the outcome as well as the intent. The snapshot taken before the work
        # cannot show a transition that has only just happened, and DELIVERED — or a
        # failure and its reason — is the line the reader most wants to see. In a
        # `finally` so it is published even when a stage raises.
        publish_status(journal.load_records(), log_fn=log_fn)
    return config.POLL_INTERVAL_SEC
