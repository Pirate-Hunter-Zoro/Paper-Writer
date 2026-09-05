"""Delivery. Copy the finished manuscript and its builds into the output folder,
using stage-then-atomic-rename so a sync client never begins uploading a partial file.

Sub-organisation is `<project>/<paper>/<file>`. Delivery is idempotent: a target
already present with identical content makes this a verified no-op rather than a
redundant copy — verify before commit, at the very last boundary.

The Markdown manuscript is delivered alongside every built format, always. It is the
source, it is the thing an author edits, and it is the one artifact that exists even
when pandoc does not.
"""

from .. import config, paths
from ..infra import storage


def deliver_one(source, dest):
    """Deliver one file atomically. Returns the destination path."""
    if storage.already_delivered(source, dest):
        return dest                                     # verified no-op

    # Stage a copy on the destination volume, prove it is byte-identical, then rename
    # into place, so no partial file is ever visible to a sync client.
    staged = storage.staging_dir_for(dest.parent) / source.name
    storage.atomic_write_bytes(source.read_bytes(), staged)
    if storage.sha256_file(staged) != storage.sha256_file(source):
        raise RuntimeError(f"delivery: staged copy of {source.name} does not match "
                           f"its source")
    storage.atomic_place(staged, dest)
    return dest


def deliver(project_rec, paper_num, artifacts, project_name=None, paper_name=None):
    """Deliver a finished paper's artifacts. Returns the list of delivered paths."""
    project_name = paths.slug(project_name or project_rec["project_id"])
    paper_name = paths.slug(paper_name or f"paper-{paper_num}")
    folder = config.OUT_DIR / project_name / paper_name

    delivered = []
    for source in artifacts:
        if source is None or not source.exists():
            continue
        delivered.append(deliver_one(source, folder / source.name))
    return delivered
