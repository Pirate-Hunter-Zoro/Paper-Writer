"""Render the harness's state as something readable on a phone.

The drop folder answers two questions by itself — a prompt in `failed/` means it
stopped, one in `finished/` means it delivered — but says nothing about the case you
are actually in most of the time: still in the folder, an hour from done, and no way to
tell "writing the Discussion" from "wedged since midnight".

This module is the answer, and it is deliberately a pure function of journal records.
No I/O, no clock of its own, no process inspection. Two consequences worth stating:

**Liveness is derived from the data, not from who wrote the file.** The status names the
newest journal timestamp and how long ago that was. Any daemon can publish this file, so
a heartbeat based on "when was this written" would go on ticking cheerfully while the
engine was hung — the exact silent failure this project has already been bitten by. The
newest journal write cannot lie in that direction.

**A long gap is not automatically alarm.** Evidence gathering and each section draft
are single blocking model calls that journal nothing while they run, so the reader is
told what is normal for the stage they are in rather than left to guess.
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
    states.GATHERING: ("reading the results and the sources into cited evidence",
                       "10-40 minutes, and it journals nothing while it runs"),
    states.GATHERED: ("evidence frozen; fixing the terminology is next", "moments"),
    states.GROUNDING: ("fixing the vocabulary, the estimand and the reader",
                       "a few minutes"),
    states.GROUNDED: ("grounded; planning the paper is next", "moments"),
    states.PROJECT_PLANNING: ("planning the project", "a few minutes"),
    states.PROJECT_PLANNED: ("planned; mapping the argument is next", "moments"),
    states.PAPERS_IN_PROGRESS: ("working through the papers", "an hour or two"),
    states.ARGUING: ("mapping every claim onto a section", "a few minutes"),
    states.OUTLINING: ("outlining the sections, paragraph by paragraph",
                       "a few minutes"),
    states.DRAFTING: ("writing sections",
                      "each section is one draft plus a few editorial passes"),
    states.DRAFTED: ("done writing; the revision sweep is next", "moments"),
    states.REVISING: ("re-editing the sections that shipped with notes",
                      "a few minutes per flagged section"),
    states.BUILDING: ("assembling and converting the manuscript", "seconds"),
    states.BUILT: ("built; delivering is next", "moments"),
    states.STALLED: ("waiting to retry something that did not work",
                     "it retries by itself, on a doubling backoff"),
    states.DELIVERING: ("delivering to the output folder", "seconds"),
}

_HEADLINE = {
    states.PROMPT_DROPPED: "QUEUED",
    states.GATHERING: "GATHERING EVIDENCE",
    states.GATHERED: "EVIDENCE FROZEN",
    states.GROUNDING: "GROUNDING",
    states.GROUNDED: "GROUNDED",
    states.PROJECT_PLANNING: "PLANNING",
    states.PROJECT_PLANNED: "PLANNED",
    states.PAPERS_IN_PROGRESS: "WRITING",
    states.PROJECT_COMPLETE: "DELIVERED",
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


def _project_records(records):
    return sorted((r for r in records.values() if r.get("level") == "project"),
                  key=lambda r: r.get("created_at", ""))


def _paper_lines(records, project_id):
    """Per-paper progress: which paper, and how many sections are durable."""
    from .infra import journal
    lines = []
    for paper in journal.papers_of(records, project_id):
        number = paper["paper_num"]
        sections = journal.sections_of(records, project_id, number)
        total = paper.get("section_count") or len(sections) or None
        done = sum(1 for s in sections
                   if s["status"] in (states.LEDGER_MERGED, states.ACCEPTED))
        flagged = sum(1 for s in sections if s.get("outstanding_issues"))

        if paper["status"] == states.COMPLETED:
            lines.append(f"- Paper {number}: delivered.")
            continue
        if paper["status"] in (states.STALLED, states.FAILED):
            lines.append(
                f"- Paper {number}: retrying — "
                f"{paper.get('error') or 'no reason recorded'}")
            continue
        progress = (f"{done} of {total} sections written" if total
                    else "not yet outlined")
        # Flagged sections are written and on disk; they are queued for the revision
        # sweep, which is progress rather than damage.
        note = (f" ({flagged} awaiting the revision sweep)" if flagged else "")
        lines.append(f"- Paper {number}: {paper['status'].replace('_', ' ')}"
                     f" — {progress}{note}.")
    return lines


def render(records, now, paused_reason=None):
    """The status document. `records` is the replayed journal, `now` a datetime.

    `paused_reason` is passed in rather than computed, so this module stays a pure
    function of its arguments: deciding whether the harness is paused is the engine's
    job, and a renderer that reaches for the clock is a renderer nobody can test."""
    out = ["# Paper-Writer — status", ""]

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
        out += ["", f"⏸ **Paused — working hours.** {reason}", "",
                "Nothing has failed and nothing is parked. The harness stays off the "
                "shared Claude session during the working day. It picks up again by "
                "itself.", ""]
    out.append(f"_This file is rewritten by the harness itself; generated "
               f"{now.strftime('%Y-%m-%d %H:%M')} UTC._")
    out.append("")

    projects = _project_records(records)
    if not projects:
        out += ["## Nothing running", "",
                "Drop a filled copy of `_TEMPLATE.md` in this folder to start a paper.",
                ""]
        return "\n".join(out)

    for rec in projects:
        status = rec["status"]
        sid = rec["project_id"]
        out.append(f"## {sid} — {_HEADLINE.get(status, status.upper())}")
        out.append("")

        if status in (states.STALLED, states.FAILED):
            out += [f"**Waiting to retry:** {rec.get('error') or 'no reason recorded'}",
                    "",
                    "Nothing has been discarded and no action is needed. The engine "
                    "retries by itself, waiting longer between each attempt, until it "
                    "gets past this. Everything already written is on disk.", ""]
        elif status == states.PROJECT_COMPLETE:
            out += ["Finished. The manuscript and everything built from it are in the "
                    "output folder, under `<project>/<paper>/`.", ""]
        else:
            doing, expect = _STAGE_NOTES.get(status, (None, None))
            if doing:
                out.append(f"Currently {doing} — expect {expect}.")
                out.append("")
            paper_lines = _paper_lines(records, sid)
            if paper_lines:
                out += paper_lines + [""]

    if any(r["status"] in (states.STALLED, states.FAILED) for r in projects):
        out += ["---", "",
                "A paper is never abandoned. Anything it cannot get past is retried on "
                "a widening backoff until it works, so the only thing a long wait "
                "needs from you is patience.", ""]
    else:
        out += ["---", "",
                "Nothing to do — it is working. A long quiet gap during evidence "
                "gathering or a section draft is normal; those are single model calls "
                "that journal nothing until they finish.", ""]
    return "\n".join(out)
