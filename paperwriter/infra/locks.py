"""Single-instance locks, one per daemon.

Every daemon takes an exclusive `flock` on its own lock file at startup and holds
it for the process lifetime, so a service manager restarting a unit that is alive
can never run two copies over the same state. Same pattern as the sibling repos'
`acquire_lock`.
"""

import fcntl
import os
import sys

from .. import paths


def acquire(label, log_fn=print):
    """Take the exclusive lock for `label`, or exit(0) if another instance holds
    it. Returns the open file handle, which the caller MUST keep alive — letting
    it be garbage-collected releases the lock."""
    path = paths.lock_file(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log_fn(f"Another {label} instance holds the lock; exiting.")
        sys.exit(0)
    fh.write(str(os.getpid()))
    fh.flush()
    return fh
