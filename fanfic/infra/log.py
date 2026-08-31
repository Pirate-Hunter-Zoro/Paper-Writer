"""Timestamped logging, mirrored to a per-daemon file under state/.

Every stage takes a `log_fn` argument rather than reaching for a logger, so a
stage is a pure function of its inputs plus one injected sink — which is what
lets the tests run the whole engine with the output captured or discarded.
`logger(label)` builds that sink for a daemon; the label also names the file, so
scribe's lines never end up interleaved with the illustrator's.
"""

from datetime import datetime, timezone

from .. import paths


def logger(label):
    """Return a `log(msg)` callable for one daemon: prints and appends to
    state/<label>.log. A failure to write the mirror is never allowed to take the
    daemon down — the whole point of the file is diagnostics."""
    prefix = f"[{label}] " if label != "scribe" else ""
    path = paths.log_file(label)

    def log(msg):
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{stamp}] {prefix}{msg}"
        print(line, flush=True)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    return log
