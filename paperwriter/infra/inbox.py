"""Reading the drop folder, which something else may own.

A job arrives as one markdown file in the inbox. That folder is normally inside a
synced tree — iCloud Drive, Dropbox, a network mount — so a paper can be commissioned
from a phone, and the local filesystem stops being the authority on what is there.
Two failure modes matter, and both are silent:

**Eviction.** A sync client reclaims space by replacing a file's contents with a
placeholder. `foo.md` disappears from the directory and `.foo.md.icloud` takes its
place, so a plain `*.md` glob simply stops seeing a job that is definitely still
there. The fix is to notice placeholders and ask for them back, then wait — the file
reappears under its real name once materialised.

**Partial arrival.** A file being written by an editor, or landing from a phone, can
be observed mid-write. Admitting a truncated prompt is worse than not seeing it: the
gathering stage would freeze evidence against half a brief and the job would look
successful. So a candidate must be non-empty and unchanged for `INBOX_SETTLE_SEC`
before anyone is allowed to read it.

Neither guard needs a sync client specifically — an editor writing in place on a local
disk hits the second one too — but a synced folder is where they stop being
theoretical. On a plain local directory the eviction machinery finds nothing and costs
one listing.
"""

import os
import subprocess
import threading
import time
from pathlib import Path

from .. import config

BRCTL = "/usr/bin/brctl"

# How long to let a directory listing run before giving up on it, and how long to stop
# trying afterwards.
#
# Earned on 2026-08-04, and the worst failure this system has produced. Enumerating a
# synced directory from a background agent is denied by macOS privacy protection — but
# where Apple's own `ls` gets a clean "Operation not permitted", a Homebrew Python
# *blocks in `open()` indefinitely*, apparently waiting on a consent decision that can
# never arrive for a background agent. The engine hung inside `glob()` on its very
# first cycle: no error, no log line, no progress, lock still held. Every failure mode
# in this design is loud, and this one was perfectly silent.
#
# So the drop folder is treated like any other untrusted external resource: give it a
# deadline. A blocked syscall cannot be cancelled, so the worker thread is left behind
# as a daemon thread — which is why a timeout also backs off, bounding the leak to one
# thread per backoff window rather than one per cycle.
SCAN_TIMEOUT_SEC = int(os.environ.get("PAPER_SCAN_TIMEOUT_SEC", "15"))
SCAN_BACKOFF_SEC = int(os.environ.get("PAPER_SCAN_BACKOFF_SEC", "300"))

_blocked_until = 0.0


def placeholder_for(path):
    """Where iCloud parks the stub when it evicts `path`'s contents."""
    path = Path(path)
    return path.with_name(f".{path.name}.icloud")


def _evicted_from(names, suffix=".md"):
    """The real filenames behind any `.foo.md.icloud` stubs in a listing.

    Returns what the files *would* be called (`foo.md`), not the stub names, because
    the caller cares about the job, not the storage detail."""
    tail = f"{suffix}.icloud"
    return sorted(n[1:-len(".icloud")] for n in names
                  if n.startswith(".") and n.endswith(tail))


def evicted_names(directory, suffix=".md"):
    """Real filenames whose contents iCloud has evicted from `directory`."""
    try:
        return _evicted_from(os.listdir(directory), suffix)
    except OSError:
        return []


def request_download(path, log_fn=None):
    """Ask iCloud to materialise a file, best-effort.

    Returns True if the request was issued. Deliberately does not wait: the daemon
    has a loop, and the file will be visible on a later cycle. A missing or failing
    `brctl` is logged and shrugged off — on a machine without iCloud there is nothing
    to materialise, and refusing to run would be worse than being patient."""
    path = Path(path)
    if not Path(BRCTL).exists():
        if log_fn:
            log_fn(f"{path.name}: evicted from iCloud but {BRCTL} is absent; waiting")
        return False
    try:
        subprocess.run([BRCTL, "download", str(path)], capture_output=True,
                       timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        if log_fn:
            log_fn(f"{path.name}: could not request iCloud download: {exc!r}")
        return False
    if log_fn:
        log_fn(f"{path.name}: evicted from iCloud; requested download")
    return True


def is_settled(path, now=None):
    """Whether a file is safe to read: present, non-empty, and unchanged for long
    enough that we are not looking at a partial write or a partial sync."""
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return False
    if stat.st_size == 0:
        return False
    age = (now if now is not None else time.time()) - stat.st_mtime
    return age >= config.INBOX_SETTLE_SEC


def materialise(directory, names, log_fn=None):
    """Ask iCloud for every named evicted file. Returns what was requested, so a caller
    can log that a job is known-but-not-yet-readable rather than absent."""
    requested = []
    for name in names:
        if request_download(Path(directory) / name, log_fn=log_fn):
            requested.append(name)
    return requested


def materialise_evicted(directory, suffix=".md", log_fn=None):
    """Enumerate and request in one step. Convenience for callers that do not already
    hold a `Listing`."""
    return materialise(directory, evicted_names(directory, suffix), log_fn=log_fn)


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
    """One enumeration of the drop folder: the jobs in it, and the jobs iCloud has
    evicted. Both come from a single `os.listdir`, because that call is the one that can
    hang and doing it twice doubles the exposure for no reason."""

    def __init__(self, directory, names, suffix=".md"):
        directory = Path(directory)
        self.jobs = sorted(directory / n for n in names
                           if n.endswith(suffix) and not n.startswith("."))
        self.evicted = _evicted_from(names, suffix)


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

    global _blocked_until

    now = time.time()
    if now < _blocked_until:
        return None

    outcome, value = _with_deadline(lambda: os.listdir(directory), SCAN_TIMEOUT_SEC)

    if outcome == "timeout":
        _blocked_until = now + SCAN_BACKOFF_SEC
        if log_fn:
            log_fn(f"drop folder {directory} did not respond within "
                   f"{SCAN_TIMEOUT_SEC}s — most likely blocked by macOS privacy "
                   f"protection, since a launchd agent cannot list an iCloud folder "
                   f"without Full Disk Access. Not retrying for {SCAN_BACKOFF_SEC}s; "
                   f"everything already journaled keeps running.")
        return None

    if outcome == "error":
        if log_fn:
            log_fn(f"drop folder {directory} could not be listed: {value!r}")
        return None
    return Listing(directory, value, suffix)


def publish(path, text, log_fn=None):
    """Write `text` to `path` if it differs from what is there, under a deadline.

    Returns True if it wrote. Skipping an unchanged write matters because this lands in
    iCloud: rewriting identical bytes every few seconds would churn sync for nothing.

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
