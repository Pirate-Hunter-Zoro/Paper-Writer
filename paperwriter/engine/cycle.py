"""One turn of the engine: admit new work, check the budget, advance one project.

Returns how long to nap, so the daemon loop stays a three-liner and the decision about
pacing lives with the decision about work. Exactly one project advances per cycle: that
is the ceiling that makes a runaway impossible to hide, since every unit of spend is one
journal line and one log line.
"""

from datetime import datetime, timezone

from .. import clock, config, paths, states, status
from ..errors import QuotaExceeded
from ..infra import budget, inbox, journal
from . import admission, project, stalling


def publish_status(records, log_fn=print, paused_reason=None):
    """Refresh the phone-readable status file in the drop folder.

    Best-effort by construction: it is a convenience, and `inbox.publish` skips an
    unchanged write, bounds itself with a deadline, and never raises. Called before the
    work rather than after, so a stage that blocks for twenty minutes has already
    published what it is about to do."""
    path = paths.status_file()
    if path is None:
        return
    inbox.publish(path, status.render(records, datetime.now(timezone.utc),
                                      paused_reason=paused_reason),
                  log_fn=log_fn)


def run(log_fn=print):
    """Advance the harness by one step. Returns the number of seconds to sleep."""
    records = journal.load_records()
    admission.register_inbox(records, log_fn=log_fn)
    publish_status(records, log_fn=log_fn)

    # Blackout windows gate the START of work only, and sit AFTER admission and the
    # status publish on purpose: a prompt dropped from a phone at lunchtime should still
    # be admitted and still show up in `_STATUS.md`, it just does not get drafted until
    # the window closes. Nothing parks; this is a pause. Off by default here — see
    # `config.QUIET_HOURS_ENABLED`.
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
         if r.get("level") == "project" and r["status"] in states.ACTIVE_PROJECTS),
        key=lambda r: r.get("created_at", ""))
    # A stalled project waiting out its backoff is not idle and is not finished; it is
    # simply not this cycle's work. Stepping over it lets a second project keep running,
    # and — because nothing else here is dispatchable either when it is the only job —
    # keeps the engine from spinning at the fast poll interval doing nothing.
    ready = [r for r in active if stalling.due(r)]
    if not ready:
        if active:
            log_fn(f"{len(active)} project(s) waiting to retry; nothing else to do.")
        return config.IDLE_INTERVAL_SEC

    try:
        project.advance(records, ready[0], log_fn=log_fn)
    except QuotaExceeded as quota:
        # Never a failure. Nothing is parked, no status changes, and the unit is picked
        # up again on a later cycle — so the run resumes by itself the moment the
        # ceiling lifts, with no re-drop and no lost work.
        wait = config.MODEL_QUOTA_BACKOFF_SEC
        if quota.retry_after:
            wait = max(wait, int(quota.retry_after) + 1)
        # Said plainly, because waiting here is the correct behaviour and not a hang,
        # and because the thing that lifts a spend ceiling is usually a person.
        log_fn(f"model spend/quota ceiling reached; nothing parked, deferring and "
               f"retrying every {wait}s until it lifts. Raise the limit (or wait for "
               f"the period to roll over) and the run continues on its own: {quota}")
        return wait
    finally:
        # Publish the outcome as well as the intent. The snapshot taken before the work
        # cannot show a transition that has only just happened, and DELIVERED — or a
        # failure and its reason — is the line the reader most wants to see. In a
        # `finally` so it is published even when a stage raises.
        publish_status(journal.load_records(), log_fn=log_fn)
    return config.POLL_INTERVAL_SEC
