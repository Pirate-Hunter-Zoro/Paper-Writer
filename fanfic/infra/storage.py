"""Atomic storage: the physical half of "apply, then verify".

Every artifact the fleet commits — chapter prose, a reference sheet, a scene
image, the `.epub`, the iCloud delivery, a bible — is written into a hidden
staging path and then atomically renamed into its final location, so no
downstream watcher (including iCloud's own sync) ever observes a half-written
file. Same stage-then-rename discipline the sibling repos use for library files.

`os.replace` is atomic within a filesystem and overwrites any prior target, which
gives idempotent re-application for free: re-running a stage that already landed
just rewrites identical bytes. Across filesystems it raises, so the fallback
copies into a temp file *on the destination volume* and renames there, keeping the
final swap atomic where it matters.

JSON lives here too rather than in its own module: "write this document durably"
is one concern, and splitting it left a three-line wrapper module whose only job
was to call into this one.
"""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from .. import config


# --- Staging -----------------------------------------------------------------

def staging_dir_for(final_dir):
    """The hidden staging subdir beside a final directory. Dot-prefixed so no
    scanner treats in-flight artifacts as committed."""
    d = Path(final_dir) / config.STAGING_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def atomic_write_bytes(data, dest):
    """Write bytes to `dest` atomically: temp file on the destination's own
    filesystem, fsync, then atomic rename over the target."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent), prefix=".tmp-")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()
    return dest


def atomic_write_text(text, dest, encoding="utf-8"):
    return atomic_write_bytes(text.encode(encoding), dest)


def atomic_place(staged_path, dest):
    """Move an already-staged file into its final location atomically. Falls back
    to copy-then-rename when staging and destination are on different filesystems
    (EXDEV), keeping the final swap atomic on the destination volume."""
    staged_path = Path(staged_path)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(staged_path, dest)
    except OSError:
        fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent), prefix=".tmp-")
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            shutil.copyfile(staged_path, tmp)
            os.replace(tmp, dest)
        finally:
            if tmp.exists():
                tmp.unlink()
        staged_path.unlink()
    return dest


# --- JSON documents ----------------------------------------------------------

def load_json(path, default=None):
    """Read committed state. Raises on malformed JSON, deliberately.

    A corrupt bible or outline is not something to paper over with a default — that
    would silently discard a whole book's memory and carry on."""
    if not Path(path).exists():
        return default
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_proposal(path):
    """Read a model's proposed artifact. Returns None if it is missing or malformed.

    The opposite posture to `load_json`, and the difference is what the file *is*. A
    proposal is untrusted model output at a scratch path; every gated stage already has
    a branch for "this is not a JSON object", which hands the errors back and asks
    again. That branch was unreachable: `load_json` raised `JSONDecodeError` first, and
    a `JSONDecodeError` is not a `RuntimeError`, so it sailed past the engine's stall
    handler and surfaced as a bare cycle error with the series left sitting in a
    transient status nothing dispatches on.

    Truncation is the common case and it is exactly what a retry is for — a model that
    runs out of output tokens halfway through a large artifact needs to be told so, not
    to have the run wedge. Returns `(None, reason)`; the reason goes into the feedback
    so the next attempt knows what happened rather than guessing."""
    p = Path(path)
    if not p.exists():
        return None, "no artifact was written at all"
    raw = p.read_text(encoding="utf-8")
    if not raw.strip():
        return None, "the artifact is empty"
    try:
        return json.loads(raw), ""
    except json.JSONDecodeError as exc:
        return None, (
            f"the artifact is not valid JSON: {exc.msg} at line {exc.lineno}, and it "
            f"is {len(raw):,} characters long. This is almost always TRUNCATION — the "
            f"document was cut off mid-write. Produce it again, complete and closed, "
            f"and if it is too large to finish in one go then say less per entry "
            f"rather than stopping partway: every entry must be present and the JSON "
            f"must end with its closing brace.")


def save_json(obj, path):
    """Atomically write a JSON document, so a crash never leaves a half-written
    bible where the next cycle would read it."""
    return atomic_write_text(json.dumps(obj, ensure_ascii=False, indent=2), path)


# --- Content addressing ------------------------------------------------------

def sha256_file(path):
    """Content hash — makes image acceptance content-addressed and delivery a
    verifiable no-op when the target already matches."""
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def already_delivered(src, dest):
    """True when `dest` exists and matches `src` byte for byte, so re-delivery is a
    verified no-op rather than a redundant copy."""
    dest = Path(dest)
    if not dest.exists():
        return False
    return sha256_file(src) == sha256_file(dest)
