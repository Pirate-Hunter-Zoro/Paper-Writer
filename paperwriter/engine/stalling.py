"""STALLED — where a unit goes instead of being abandoned.

This project used to have a terminal `FAILED`, justified by a real argument: a
deterministic failure retried in a loop burns allowance to learn the same thing over
and over. The argument is sound and the conclusion was wrong, because it treated
"retry immediately, forever" as the only alternative to quitting. It is not.

A stalled unit records what went wrong, waits, and tries again — with the wait doubling
each time, from `STALL_BACKOFF_BASE_SEC` up to `STALL_BACKOFF_MAX_SEC`. After a handful
of attempts the retries are hours apart, which costs nothing and means:

  * a provider outage resolves itself and the run continues, unattended;
  * an allowance ceiling lifts when the month rolls over or an admin acts, and the run
    continues, unattended;
  * a genuine bug in the harness gets retried every few hours until somebody fixes it,
    at which point the run continues — instead of the job having been filed away weeks
    earlier and the accepted work sitting there unfinished.

The unit is never dropped, its artifacts are never discarded, and no human gesture is
required for any of it. The one thing a stall does cost is a line in the status file
saying what is wrong, which is the thing a human actually wanted from `FAILED`.
"""

from datetime import datetime, timezone

from .. import config, states
from ..infra import journal


def _now():
    return datetime.now(timezone.utc)


def _parse(stamp):
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


def backoff_seconds(count):
    """How long a unit waits before its `count`-th retry. Doubling, capped."""
    if count <= 0:
        return 0
    delay = config.STALL_BACKOFF_BASE_SEC * (2 ** (count - 1))
    return min(delay, config.STALL_BACKOFF_MAX_SEC)


def stall(records, record, reason, log_fn=print):
    """Park a unit in STALLED with an escalating retry clock. Never terminal.

    The unit's *last resumable status* is remembered on the record rather than derived
    later, because by the time the retry comes round the journal has more history and
    replaying it is both slower and ambiguous."""
    count = _consecutive(record) + 1
    # The CURRENT status first, and only then whatever a previous stall recorded. A
    # unit that stalled at DRAFTING, recovered, and reached REVISING still carries
    # `stall_resume_to: drafting` on its record — preferring the stored value would
    # send it back three stages on its next unrelated stall.
    status = record.get("status")
    resume_to = (status if status in states.RESUMABLE
                 else (record.get("stall_resume_to") or _resumable_status(record)))
    wait = backoff_seconds(count)
    journal.log_decision(record["key"], f"STALLED (attempt {count})",
                         f"{reason}\nRetrying in {wait}s, and again after that. "
                         f"Nothing has been discarded.")
    journal.set_status(records, record, states.STALLED,
                       error=str(reason)[:500],
                       stall_count=count,
                       stall_resume_to=resume_to,
                       stalled_at=_now().isoformat())
    log_fn(f"STALLED {record['key']}: {reason} — retry in {wait}s (attempt {count})")


def _consecutive(record, now=None):
    """How many times this unit has stalled *in a row*, for the escalation.

    The count is what makes each wait longer than the last, so it has to mean "recent
    trouble" rather than "trouble ever". A record carries its counter forward through
    every later write, so without this a paper that stalled four times while gathering
    and then wrote a dozen clean sections would wait an hour before retrying its first
    unrelated hiccup in October.

    Anything longer than the maximum backoff since the last stall counts as having got
    somewhere, and the escalation starts over. That is exactly the interval the counter
    exists to grow: if a unit ran for longer than its own worst wait, the previous
    trouble is not what is happening now."""
    count = int(record.get("stall_count") or 0)
    if not count:
        return 0
    since = _parse(record.get("stalled_at"))
    if since is None:
        return count
    if (now or _now()) - since > _delta(config.STALL_BACKOFF_MAX_SEC):
        return 0
    return count


def _resumable_status(record):
    """The status a stalled unit should be rewound to when its wait expires.

    A transient status names its own entry point. The level-wide fallback below is only
    for a status the map does not cover, and it used to be the whole answer — which
    sends a paper that stalled while outlining back to DRAFTING, where it finds no
    sections to draft and walks out the other side of the paper machine with an empty
    manuscript to build."""
    status = record.get("status")
    if status in states.RESUMABLE:
        return status
    if status in states.REWIND_TO:
        return states.REWIND_TO[status]
    level = record.get("level")
    if level == "project":
        return states.BOOKS_IN_PROGRESS
    if level == "paper":
        return states.DRAFTING
    return states.PENDING


def due(record, now=None):
    """Whether a stalled unit's wait has elapsed."""
    if record.get("status") != states.STALLED:
        return True
    since = _parse(record.get("stalled_at"))
    if since is None:
        return True
    wait = backoff_seconds(int(record.get("stall_count") or 1))
    return (now or _now()) - since >= _delta(wait)


def _delta(seconds):
    from datetime import timedelta
    return timedelta(seconds=seconds)


def resume(records, record, log_fn=print):
    """Rewind a stalled unit to its entry point so the machine dispatches on it again.

    The stall counter is deliberately NOT reset. It is the memory of how much trouble
    this unit has been, and it is what makes the next wait longer than the last; a unit
    that succeeds clears it on its own by advancing to a normal status."""
    target = record.get("stall_resume_to") or _resumable_status(record)
    log_fn(f"retrying {record['key']} from {target} "
           f"(stall attempt {record.get('stall_count')})")
    journal.set_status(records, record, target, error=None)


def wake(records, record, log_fn=print):
    """Give a stalled unit its retry if it is due. Returns True if it was resumed."""
    if not due(record):
        return False
    resume(records, record, log_fn=log_fn)
    return True
