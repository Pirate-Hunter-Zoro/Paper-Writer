"""binder — the one-shot that binds and delivers finished books, then exits.

A book that reaches ILLUSTRATED needs deterministic assembly and atomic delivery.
scribe does this inline too; this unit exists so the work can run on its own
schedule and stay off the drafting critical path.

It drives each book by calling `engine.book.advance` — the same function scribe
calls — rather than reimplementing the transitions, so the two can never disagree.
Binding validates before placing and delivery is content-addressed, so running
alongside a scribe that also handles these states is idempotent and safe.

    python3 -m fanfic.daemons.binder
"""

from .. import states
from ..engine import book as book_level, cycle
from ..infra import journal, locks, log as logging

LABEL = "binder"

# ILLUSTRATED -> BINDING -> BOUND -> DELIVERING -> DELIVERED -> COMPLETED is five
# transitions; the cap is a backstop against a state that somehow never settles.
MAX_STEPS = 6


def run_once(log=print):
    records = journal.load_records()

    # Refresh the status file on the way past. scribe publishes it every cycle, but a
    # cycle can be a forty-minute model call, and this one-shot re-execs fresh every
    # five minutes — so the folder keeps saying something current even mid-stage. The
    # liveness figure in it is derived from journal timestamps, not from who wrote the
    # file, so this cannot paper over a wedged engine.
    cycle.publish_status(records, log_fn=log)

    pending = [r for r in records.values()
               if r.get("level") == "book" and r["status"] in states.BINDING_STATES]

    for book_rec in pending:
        series_rec = records.get(journal.series_key(book_rec["series_id"]))
        if not series_rec:
            log(f"{book_rec['key']}: no series record; skipping")
            continue
        for _ in range(MAX_STEPS):
            records = journal.load_records()
            book_rec = records.get(book_rec["key"], book_rec)
            if book_rec["status"] not in states.BINDING_STATES:
                break
            book_level.advance(records, series_rec, book_rec, log_fn=log)


def main():
    log = logging.logger(LABEL)
    locks.acquire(LABEL, log_fn=log)
    log("one-shot: scanning for books to bind/deliver.")
    run_once(log=log)
    log("one-shot: done.")


if __name__ == "__main__":
    main()
