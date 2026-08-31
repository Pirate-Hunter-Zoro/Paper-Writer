"""scribe — the engine daemon. Self-looping; launchd only restarts it if it dies.

Every stage of the pipeline is a stage *inside this one process*, exactly as
identify/stage/verify fold into one Torrent-Ingest process. It also drains the image
queue and binds and delivers, so scribe alone is sufficient for correctness — the
illustrator and binder units are throughput, not dependencies.

    python3 -m fanfic.daemons.scribe
"""

from .. import config
from ..engine import cycle
from ..infra import journal, locks, log as logging
from . import loop

LABEL = "scribe"


def main():
    log = logging.logger(LABEL)
    lock = locks.acquire(LABEL, log_fn=log)     # held for the process lifetime

    # We hold the lock, so any unit still sitting in an in-progress status was
    # abandoned by a kill, crash, or launchd restart. Rewind it before the first
    # cycle, or it would sit there forever — nothing dispatches on those statuses.
    for key, status in journal.recover_stale():
        journal.log_decision(key, "RECOVERED",
                             f"found abandoned mid-stage at startup; rewound to "
                             f"{status}")
        log(f"RECOVERED {key}: abandoned mid-stage -> {status}")

    loop(LABEL, lambda: cycle.run(log_fn=log), log, config.IDLE_INTERVAL_SEC)
    lock.close()


if __name__ == "__main__":
    main()
