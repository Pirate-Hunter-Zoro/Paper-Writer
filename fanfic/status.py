"""Render the fleet's state as something readable on a phone.

The drop folder answers two questions by itself — a prompt in `failed/` means it
stopped, one in `finished/` means it delivered — but says nothing about the case you
are actually in most of the time: still in the folder, hours from done, and no way to
tell "writing chapter 12" from "wedged since midnight".

This module is the answer, and it is deliberately a pure function of journal records.
No I/O, no clock of its own, no process inspection. Two consequences worth stating:

**Liveness is derived from the data, not from who wrote the file.** The status names the
newest journal timestamp and how long ago that was. Any daemon can publish this file, so
a heartbeat based on "when was this written" would go on ticking cheerfully while the
engine was hung — the exact silent failure this project has already been bitten by. The
newest journal write cannot lie in that direction.

**A long gap is not automatically alarm.** Research and each chapter draft are single
blocking model calls that journal nothing while they run, so the reader is told what is
normal for the stage they are in rather than left to guess.
"""

from . import clock, states

# What a stage does and roughly how long it is entitled to take, so a quiet gap can be
# read correctly.
#
# Waypoint statuses get an entry too, not just the long blocking ones. A status file
# whose headline is "RESEARCH DONE" and whose body is empty is a bad answer to "what is
# happening" — and the reader sees exactly that state whenever the engine is one step
# ahead of the last published snapshot, which is every long stage.
_STAGE_NOTES = {
    states.PROMPT_DROPPED: ("queued and about to start", "moments"),
    states.RESEARCHING: ("mining the source wikis for cited canon",
                         "15-40 minutes, and it journals nothing while it runs"),
    states.RESEARCHED: ("done with canon; the series plan is next", "moments"),
    states.SERIES_PLANNED: ("planned; outlining the first book is next", "moments"),
    states.BOOKS_IN_PROGRESS: ("working through the books", "hours"),
    states.DRAFTED: ("done writing; illustrations are next", "moments"),
    states.ILLUSTRATED: ("done illustrating; binding the .epub is next", "moments"),
    states.BOUND: ("bound; delivering to this Books folder is next", "moments"),
    states.SERIES_PLANNING: ("planning the series", "a few minutes"),
    states.OUTLINING: ("outlining the book", "a few minutes"),
    states.DRAFTING: ("writing chapters",
                      "each chapter is one draft plus a few editorial passes"),
    states.REVISING: ("re-editing the chapters that shipped with notes",
                      "a few minutes per flagged chapter"),
    states.STALLED: ("waiting to retry something that did not work",
                     "it retries by itself, on a doubling backoff"),
    states.ILLUSTRATING: ("rendering illustrations",
                          "paced; a slot that will not draw waits and retries, so this "
                          "can be slow and is never stuck"),
    states.BINDING: ("assembling the .epub", "seconds"),
    states.DELIVERING: ("delivering to this Books folder", "seconds"),
}

_HEADLINE = {
    states.PROMPT_DROPPED: "QUEUED",
    states.RESEARCHING: "RESEARCHING",
    states.RESEARCHED: "RESEARCH DONE",
    states.SERIES_PLANNING: "PLANNING",
    states.SERIES_PLANNED: "PLANNED",
    states.BOOKS_IN_PROGRESS: "WRITING",
    states.SERIES_COMPLETE: "DELIVERED",
    states.STALLED: "RETRYING",
    states.FAILED: "RETRYING",
}


def _ago(seconds):
    """A duration a human reads at a glance."""
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes} min ago"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f} hours ago"
    return f"{hours / 24:.1f} days ago"


def _parse(stamp):
    """An ISO timestamp from the journal as a naive epoch-comparable value."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


def _newest_activity(records):
    """The most recent journal write across every unit, as (datetime, key)."""
    newest, where = None, None
    for key, rec in records.items():
        when = _parse(rec.get("updated_at"))
        if when and (newest is None or when > newest):
            newest, where = when, key
    return newest, where


def _series_records(records):
    return sorted((r for r in records.values() if r.get("level") == "series"),
                  key=lambda r: r.get("created_at", ""))


def _book_lines(records, series_id):
    """Per-book progress: which book, and how many chapters are durable."""
    from .infra import journal
    lines = []
    for book in journal.books_of(records, series_id):
        number = book["book_num"]
        chapters = journal.chapters_of(records, series_id, number)
        total = book.get("chapter_count") or len(chapters) or None
        done = sum(1 for c in chapters
                   if c["status"] in (states.BIBLE_MERGED, states.ACCEPTED))
        flagged = sum(1 for c in chapters if c.get("outstanding_issues"))

        if book["status"] == states.COMPLETED:
            lines.append(f"- Book {number}: delivered.")
            continue
        if book["status"] in (states.STALLED, states.FAILED):
            lines.append(
                f"- Book {number}: retrying — "
                f"{book.get('error') or 'no reason recorded'}")
            continue
        if total:
            progress = f"{done} of {total} chapters written"
        else:
            progress = "not yet outlined"
        # Flagged chapters are written and on disk; they are queued for the revision
        # sweep, which is progress rather than damage. Saying "parked" here was the
        # status file describing a machine that no longer exists.
        note = (f" ({flagged} awaiting the revision sweep)" if flagged else "")
        lines.append(f"- Book {number}: {book['status'].replace('_', ' ')}"
                     f" — {progress}{note}.")
    return lines


def render(records, now, paused_reason=None):
    """The status document. `records` is the replayed journal, `now` a datetime.

    `paused_reason` is passed in rather than computed, so this module stays a pure
    function of its arguments: deciding whether the fleet is paused is the engine's
    job, and a renderer that reaches for the clock is a renderer nobody can test."""
    out = ["# Fanfiction-Writer — status", ""]

    newest, _where = _newest_activity(records)
    if newest is not None:
        gap = (now - newest).total_seconds()
        out.append(f"Engine last wrote to its journal **{_ago(gap)}** "
                   f"({newest.strftime('%Y-%m-%d %H:%M')} UTC).")
    else:
        out.append("The journal is empty — nothing has been submitted yet.")
    out.append("")

    # A long gap is alarming unless the reader knows work is *deliberately* paused.
    # Without this line the status file says "last wrote 6 hours ago" all afternoon and
    # looks exactly like a wedged engine.
    reason = paused_reason
    if reason is None:
        quiet, _nap = clock.quiet_window(now)
        reason = clock.describe(now) if quiet else None
    if reason:
        pricing = "peak pricing" in reason
        headline = ("⏸ **Paused — peak pricing.**" if pricing
                    else "⏸ **Paused — working hours.**")
        why = ("The configured model provider charges double during this window, so "
               "the fleet waits it out."
               if pricing else
               "The fleet stays off the shared Claude session during the working day.")
        out += ["", f"{headline} {reason}", "",
                f"Nothing has failed and nothing is parked. {why} It picks up again by "
                f"itself.", ""]
    out.append(f"_This file is rewritten by the fleet itself; generated "
               f"{now.strftime('%Y-%m-%d %H:%M')} UTC._")
    out.append("")

    series = _series_records(records)
    if not series:
        out += ["## Nothing running", "",
                "Drop a filled copy of `_TEMPLATE.md` in this folder to start a novel.",
                ""]
        return "\n".join(out)

    for rec in series:
        status = rec["status"]
        sid = rec["series_id"]
        out.append(f"## {sid} — {_HEADLINE.get(status, status.upper())}")
        out.append("")

        if status in (states.STALLED, states.FAILED):
            out += [f"**Waiting to retry:** {rec.get('error') or 'no reason recorded'}",
                    "",
                    "Nothing has been discarded and no action is needed. The engine "
                    "retries by itself, waiting longer between each attempt, until it "
                    "gets past this. Everything already written is on disk.", ""]
        elif status == states.SERIES_COMPLETE:
            out += ["Finished. The `.epub` is in this Books folder, under "
                    "`<fandom>/<series>/`.", ""]
        else:
            doing, expect = _STAGE_NOTES.get(status, (None, None))
            if doing:
                out.append(f"Currently {doing} — expect {expect}.")
                out.append("")
            book_lines = _book_lines(records, sid)
            if book_lines:
                out += book_lines + [""]

    if any(r["status"] in (states.STALLED, states.FAILED) for r in series):
        out += ["---", "",
                "A novel is never abandoned. Anything it cannot get past is retried on "
                "a widening backoff until it works, so the only thing a long wait "
                "needs from you is patience.", ""]
    else:
        out += ["---", "",
                "Nothing to do — it is working. A long quiet gap during research or a "
                "chapter draft is normal; those are single model calls that journal "
                "nothing until they finish.", ""]
    return "\n".join(out)
