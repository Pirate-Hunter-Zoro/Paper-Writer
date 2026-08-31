"""The series-level machine: PROMPT_DROPPED -> ... -> SERIES_COMPLETE.

Books draft sequentially within a series, because book N needs book N-1's ending
world-state. A standalone novel is a one-book series, so there is no separate path
for it.

**A series does not fail.** It used to, and the cascade was the single most expensive
defect this project has had: a chapter parked, which failed its book, which failed the
series, which filed the prompt into `_inbox/failed/` and stopped — leaving twenty-one
finished chapters on disk and requiring a human to notice and move a file before
anything could happen again. The whole cascade existed to prevent a token-burn retry
loop, which is a real hazard with a much cheaper answer: stall, wait, and try again on
a doubling backoff. See `engine.stalling`.

So the only ways out of this machine are SERIES_COMPLETE and "waiting to try again",
and no human gesture is required for the second one.
"""

from .. import config, states
from ..infra import journal
from ..stages import anchoring, planning, research
from . import admission
from . import book as book_level
from . import stalling


def advance(records, series_rec, log_fn=print):
    """Advance one series by exactly one step."""
    status = series_rec["status"]
    key = series_rec["key"]

    if status == states.STALLED:
        stalling.wake(records, series_rec, log_fn=log_fn)
        return

    try:
        if status in states.DEAD_ENDS:
            journal.set_status(records, series_rec, states.BOOKS_IN_PROGRESS,
                               error=None)
            log_fn(f"{series_rec['series_id']}: clearing a legacy FAILED status; "
                   f"resuming")
            return

        if status == states.PROMPT_DROPPED:
            journal.set_status(records, series_rec, states.RESEARCHING)
            result = research.run(records[key], log_fn=log_fn)
            journal.set_status(records, records[key], states.RESEARCHED,
                               universes=result["universes"])
            log_fn(f"{series_rec['series_id']}: canon frozen for "
                   f"{result['universes']} (coverage {result['coverage']:.0%})")
            return

        if status == states.RESEARCHED:
            # Canon is frozen; now pin where everyone actually IS. Between research
            # and planning on purpose: the anchor is derived from frozen ground truth
            # rather than from the prompt's summary of it, and planning then writes
            # appearances from the anchor rather than from the source material's
            # defaults — which is how a character's most iconic look gets written down
            # instead of the one they have on page one.
            journal.set_status(records, series_rec, states.ANCHORING)
            anchor = anchoring.run(records[key], log_fn=log_fn)
            journal.set_status(records, records[key], states.ANCHORED,
                               anchored=len(anchor.get("characters", [])))
            return

        if status == states.ANCHORED:
            journal.set_status(records, series_rec, states.SERIES_PLANNING)
            plan = planning.run(records[key], log_fn=log_fn)
            for spec in plan["books"]:
                record = journal.new_book(series_rec["series_id"], spec["num"],
                                          spec.get("title"))
                journal.write_record(record)
                records[record["key"]] = record
            journal.set_status(records, records[key], states.SERIES_PLANNED,
                               book_count=plan["book_count"],
                               title=plan.get("title", ""))
            journal.set_status(records, records[key], states.BOOKS_IN_PROGRESS)
            log_fn(f"{series_rec['series_id']}: planned {plan['book_count']} book(s)")
            return

        if status == states.BOOKS_IN_PROGRESS:
            _advance_books(records, series_rec, log_fn=log_fn)
            return
    except RuntimeError as exc:
        stalling.stall(records, records.get(key, series_rec), str(exc), log_fn=log_fn)


def _advance_books(records, series_rec, log_fn=print):
    """Advance the first not-yet-complete book, or close out the series.

    A stalled book is *skipped over* rather than blocking the series, and only for as
    long as its wait has to run. That matters for a multi-book series: book 2 stalled
    on a provider outage must not stop book 1's illustrations from finishing. Books
    still draft in order — a stalled book is retried before any later book is started,
    because `book_level.advance` on a STALLED record either wakes it or returns."""
    stalled = []
    for book_rec in journal.books_of(records, series_rec["series_id"]):
        if book_rec["status"] == states.COMPLETED:
            continue
        if book_rec["status"] == states.STALLED and not stalling.due(book_rec):
            stalled.append(book_rec)
            continue
        book_level.advance(records, series_rec, book_rec, log_fn=log_fn)
        return

    if stalled:
        # Everything left is waiting out a backoff. Say so rather than looking idle.
        first = stalled[0]
        log_fn(f"{series_rec['series_id']}: {len(stalled)} book(s) waiting to retry; "
               f"book {first['book_num']}: {first.get('error', '')[:120]}")
        return

    journal.set_status(records, series_rec, states.SERIES_COMPLETE)
    admission.file_prompt(series_rec, config.INBOX_FINISHED_DIR, log_fn=log_fn)
    log_fn(f"{series_rec['series_id']}: SERIES_COMPLETE")
