"""Inbox admission: turning a dropped markdown file into a unit of work, and filing
it away again when the job ends.

Three cases, and the third is the one that matters:

  * unknown project id -> a brand-new project unit, PROMPT_DROPPED.
  * active or complete -> left alone. Re-scanning a running job would fork it.
  * stuck or FAILED    -> REVIVED. The project is rewound to its last resumable
    state, so a re-drop resumes rather than restarting.

That revive is why the project id is the slug of the filename: identity has to survive
the file being moved to inbox/failed/ and moved back. Durable artifacts — frozen
frozen evidence, the grounding, the plan, outlines, accepted sections, merged ledger
facts — are all keyed on disk, so nothing is redone that already landed.
"""

import shutil
from pathlib import Path

from .. import config, paths, states
from ..infra import inbox, journal


def is_job_file(path):
    """Whether a markdown file in inbox/ is a job rather than documentation.

    Earned on 2026-08-04: an `inbox/README.md` explaining the folder was admitted as
    a job named "readme", failed research for having no source universe, and was
    filed away into inbox/failed/ — the folder's own instructions, eaten by the
    folder. A leading underscore is the escape hatch for scratch files."""
    name = path.name.lower()
    return name != "readme.md" and not path.name.startswith(("_", "."))


def register_inbox(records, log_fn=print):
    """Admit or revive every prompt file currently in the drop folder.

    A file that is still settling is left for a later cycle, because a prompt observed
    mid-write is worse than a prompt not yet seen. Mutates `records`."""
    if not config.INBOX_DIR.exists():
        return
    revived_any = False

    # None means the folder could not be read at all — which is NOT the same as it being
    # empty, so we learn nothing and touch nothing. Everything already in the journal
    # keeps advancing; only new drops are invisible.
    listing = inbox.scan(config.INBOX_DIR, ".md", log_fn=log_fn)
    if listing is None:
        return

    for path in listing.jobs:
        if not is_job_file(path):
            continue
        if not inbox.is_settled(path):
            continue                    # mid-write; try again next cycle
        project_id = paths.slug(path.stem)
        existing = records.get(journal.project_key(project_id))

        if existing is None:
            text = path.read_text(encoding="utf-8", errors="replace")
            record = journal.write_record(
                journal.new_project(project_id, path, text))
            records[record["key"]] = record
            log_fn(f"admitted new prompt: {path.name} -> {project_id}")
            continue

        # A re-drop means "try again now". It applies to a stalled project waiting out
        # a backoff as much as to one holding a status from the build that had
        # terminal failures — in both cases the engine would eventually get there on
        # its own, and the human gesture asks for it immediately with the wait reset.
        if existing["status"] in (states.DEAD_ENDS | {states.STALLED}):
            revived = journal.revive_project(project_id)
            if revived:
                revived_any = True
                detail = ", ".join(f"{k.split('project/')[-1]}->{s}"
                                   for k, s in revived)
                journal.log_decision(
                    journal.project_key(project_id), "REVIVED",
                    f"re-dropped while {existing['status']}; resuming now: {detail}")
                log_fn(f"REVIVED {project_id} from inbox re-drop; resuming "
                       f"{len(revived)} unit(s): {detail}")

    if revived_any:                    # pick up the freshly-written statuses
        records.clear()
        records.update(journal.load_records())


def file_prompt(project_rec, dest_dir, log_fn=print):
    """Move a finished or failed job's prompt out of inbox/ so it is not re-scanned.

    It stays re-droppable: moving it back into inbox/ is the documented retry, and
    for a stuck project that means a revive, not a restart."""
    candidates = [Path(project_rec.get("prompt_path", "")),
                  config.INBOX_DIR / (paths.slug(project_rec["project_id"]) + ".md")]
    for path in candidates:
        if path and path.exists():
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(dest_dir / path.name))
            except OSError as exc:
                log_fn(f"could not file prompt away: {exc!r}")
            return
