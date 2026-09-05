"""builder — the one-shot that builds and delivers finished papers, then exits.

A paper that reaches DRAFTED needs deterministic assembly and atomic delivery.
`author` does this inline too; this unit exists so the work can run on its own
schedule and stay off the drafting critical path.

It drives each paper by calling `engine.paper.advance` — the same function `author`
calls — rather than reimplementing the transitions, so the two can never disagree.
Assembly is a pure function of files on disk and delivery is content-addressed, so
running alongside an `author` that also handles these states is idempotent and safe.

    python3 -m paperwriter.daemons.builder
"""

from .. import states
from ..engine import cycle
from ..engine import paper as paper_level
from ..infra import journal, locks, log as logging

LABEL = "builder"

# DRAFTED -> BUILDING -> BUILT -> DELIVERING -> DELIVERED -> COMPLETED is five
# transitions; the cap is a backstop against a state that somehow never settles.
MAX_STEPS = 6


def run_once(log=print):
    records = journal.load_records()

    # Refresh the status file on the way past. `author` publishes it every cycle, but a
    # cycle can be a long model call, and this one-shot re-execs fresh every few
    # minutes — so the folder keeps saying something current even mid-stage. The
    # liveness figure in it is derived from journal timestamps, not from who wrote the
    # file, so this cannot paper over a wedged engine.
    cycle.publish_status(records, log_fn=log)

    pending = [r for r in records.values()
               if r.get("level") == "paper" and r["status"] in states.BUILDING_STATES]

    for paper_rec in pending:
        project_rec = records.get(journal.project_key(paper_rec["project_id"]))
        if not project_rec:
            log(f"{paper_rec['key']}: no project record; skipping")
            continue
        for _ in range(MAX_STEPS):
            records = journal.load_records()
            paper_rec = records.get(paper_rec["key"], paper_rec)
            if paper_rec["status"] not in states.BUILDING_STATES:
                break
            paper_level.advance(records, project_rec, paper_rec, log_fn=log)


def main():
    log = logging.logger(LABEL)
    locks.acquire(LABEL, log_fn=log)
    log("one-shot: scanning for papers to build and deliver.")
    run_once(log=log)
    log("one-shot: done.")


if __name__ == "__main__":
    main()
