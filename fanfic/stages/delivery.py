"""Stage 8 — Delivery. Copy the finished `.epub` into the iCloud Books folder using
stage-then-atomic-rename, so iCloud never begins syncing a partial file.

Sub-organisation inside Books/ is `<fandom>/<series>/<file>`. Delivery is idempotent:
a target already present with identical content makes this a verified no-op rather
than a redundant copy — verify before commit, at the very last boundary.

The `~` in the Books path only resolves on the mini; FANFIC_BOOKS_DIR redirects it
everywhere else.
"""

from .. import config, paths
from ..infra import storage


def deliver(series_rec, book_num, epub_path, fandom=None, series_name=None):
    """Deliver a bound epub to iCloud Books. Returns the delivered path."""
    fandom = paths.slug(fandom or (series_rec.get("universes") or ["misc"])[0])
    series_name = paths.slug(series_name or series_rec["series_id"])
    dest = config.ICLOUD_BOOKS_DIR / fandom / series_name / epub_path.name

    if storage.already_delivered(epub_path, dest):
        return dest                                     # verified no-op

    # Stage a copy on the destination volume, prove it is byte-identical, then rename
    # into place, so no partial file is ever visible to iCloud's sync.
    staged = storage.staging_dir_for(dest.parent) / epub_path.name
    storage.atomic_write_bytes(epub_path.read_bytes(), staged)
    if storage.sha256_file(staged) != storage.sha256_file(epub_path):
        raise RuntimeError("delivery: staged copy does not match source")
    storage.atomic_place(staged, dest)
    return dest
