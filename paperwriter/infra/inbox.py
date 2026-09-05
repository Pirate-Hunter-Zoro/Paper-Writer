"""Reading the drop folder, which something else may own.

A job arrives as one markdown file in the inbox. That folder is often not a plain local
directory — a network mount, a shared filesystem, a synced tree — so two things that
would be trivially safe on local disk are not:

**Partial arrival.** A file being written by an editor, or landing over a network, can
be observed mid-write. Admitting a truncated prompt is worse than not seeing it: the
gathering stage would freeze evidence against half a brief and the job would look
successful. So a candidate must be non-empty and unchanged for `INBOX_SETTLE_SEC`
before anyone is allowed to read it.

**A listing that never returns.** A directory on an unresponsive mount does not fail,
it hangs, and a hang inside `os.listdir` is the worst failure this design can have: no
error, no log line, no progress, and the lock still held. Every other failure mode here
is loud. So the drop folder is treated like any other untrusted external resource and
given a deadline.

Neither guard needs anything exotic — an editor writing in place on local disk hits the
first one too — but a mount is where they stop being theoretical.

**There is no eviction machinery here any more.** This module once knew about iCloud
placeholder files (`.foo.md.icloud`) and shelled out to `brctl` to request them back.
That was real on a Mac mini and it is dead weight everywhere else: the binary does not
exist, the placeholders never appear, and the code was one more thing to read before
believing the drop folder works. If a future host needs it, it is in the history.
"""

import os
import threading
import time
from pathlib import Path

from .. import config

# How long to let a directory listing run before giving up on it, and how long to stop
# trying afterwards.
#
# A blocked syscall cannot be cancelled, so on timeout the worker thread is abandoned
# as a daemon thread. That is why a timeout must also back off: without it, a wedged
# mount leaks one thread per cycle instead of one per backoff window.
SCAN_TIMEOUT_SEC = int(os.environ.get("PAPER_SCAN_TIMEOUT_SEC", "15"))
SCAN_BACKOFF_SEC = int(os.environ.get("PAPER_SCAN_BACKOFF_SEC", "300"))

_blocked_until = 0.0


def is_settled(path, now=None):
    """Whether a file is safe to read: present, non-empty, and unchanged for long
    enough that we are not looking at a partial write."""
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return False
    if stat.st_size == 0:
        return False
    age = (now if now is not None else time.time()) - stat.st_mtime
    return age >= config.INBOX_SETTLE_SEC


def reset_scan_backoff():
    """Forget that a directory was unreadable. For tests, and for a caller that knows
    something has changed."""
    global _blocked_until
    _blocked_until = 0.0


def _with_deadline(work, timeout):
    """Run `work()` in a daemon thread and give it `timeout` seconds.

    Returns ("ok", value), ("timeout", None), or ("error", exception). A blocked
    syscall cannot be cancelled, so on timeout the thread is abandoned — which is why
    every caller must also back off rather than starting a fresh one each cycle."""
    result = {}

    def run():
        try:
            result["value"] = work()
        except OSError as exc:
            result["error"] = exc

    worker = threading.Thread(target=run, daemon=True, name="inbox-io")
    worker.start()
    worker.join(timeout)

    if worker.is_alive():
        return "timeout", None
    if "error" in result:
        return "error", result["error"]
    return "ok", result.get("value")


class Listing:
    """One enumeration of the drop folder: the job files in it.

    Dot-prefixed names are skipped. An editor's swap file and a partial download both
    look like work otherwise, and neither is."""

    def __init__(self, directory, names, suffix=".md"):
        directory = Path(directory)
        self.jobs = sorted(directory / n for n in names
                           if n.endswith(suffix) and not n.startswith("."))


def scan(directory, suffix=".md", log_fn=None):
    """Enumerate `directory` under a deadline.

    Returns a `Listing`, or **None** meaning "could not read it, and you have learned
    nothing about what is in there". None is deliberately distinct from an empty
    Listing: an empty folder means there is no work, an unreadable one means the
    question is still open, and conflating those is how a permission problem gets
    mistaken for an idle queue.

    Uses `os.listdir` rather than `Path.glob` on purpose — pathlib's globbing swallows
    `OSError` and yields nothing, so a denied directory is indistinguishable from an
    empty one through it. `listdir` raises, which is the whole point.

    On timeout, backs off for SCAN_BACKOFF_SEC and says so once rather than every
    cycle."""
    global _blocked_until

    now = time.time()
    if now < _blocked_until:
        return None

    outcome, value = _with_deadline(lambda: os.listdir(directory), SCAN_TIMEOUT_SEC)

    if outcome == "timeout":
        _blocked_until = now + SCAN_BACKOFF_SEC
        if log_fn:
            log_fn(f"drop folder {directory} did not respond within "
                   f"{SCAN_TIMEOUT_SEC}s. That is a hung filesystem rather than an "
                   f"empty queue — most likely an unresponsive mount. Not retrying "
                   f"for {SCAN_BACKOFF_SEC}s; everything already journaled keeps "
                   f"running.")
        return None

    if outcome == "error":
        if log_fn:
            log_fn(f"drop folder {directory} could not be listed: {value!r}")
        return None
    return Listing(directory, value, suffix)


def publish(path, text, log_fn=None):
    """Write `text` to `path` if it differs from what is there, under a deadline.

    Returns True if it wrote. Skipping an unchanged write matters because this file is
    rewritten every cycle and may land on a watched or synced directory: rewriting
    identical bytes every few seconds churns for nothing.

    Never raises. A status file that cannot be written is worth one log line and no
    more — it is a convenience, and taking the engine down over it would be absurd."""
    global _blocked_until

    now = time.time()
    if now < _blocked_until:
        return False

    def work():
        from . import storage
        try:
            if path.exists() and path.read_text(encoding="utf-8") == text:
                return False
        except OSError:
            pass                                  # unreadable: just overwrite it
        storage.atomic_write_text(text, path)
        return True

    outcome, value = _with_deadline(work, SCAN_TIMEOUT_SEC)

    if outcome == "timeout":
        _blocked_until = now + SCAN_BACKOFF_SEC
        if log_fn:
            log_fn(f"status file {path} did not respond within {SCAN_TIMEOUT_SEC}s; "
                   f"not retrying for {SCAN_BACKOFF_SEC}s")
        return False
    if outcome == "error":
        if log_fn:
            log_fn(f"could not write status file {path}: {value!r}")
        return False
    return bool(value)
