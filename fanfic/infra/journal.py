"""The append-only journal — the single source of truth for crash-resume.

A JSON-lines file where each line is a full snapshot of one unit's record, keyed
hierarchically (`series/<id>`, `series/<id>/book/<n>`, `.../chapter/<n>`). The
*last* line for a key wins, so recovering current state is "replay the file,
last-writer-wins", exactly as Torrent-Ingest recovers per-torrent state.

Why append-and-replay rather than rewriting a dict: an append is atomic enough
that a crash mid-write loses at most the line being written, never the history. On
restart we can see how far every unit got and resume from the first non-terminal
one. Every stage action is written to be idempotent, so a resume never re-writes
an accepted chapter or double-applies a merged bible fact.

Alongside it, `decisions.log` is the human-readable audit of every model call and
verdict — the first place to look when a unit parks, because the reason is written
there verbatim.
"""

import json
from datetime import datetime, timezone

from .. import paths, states


def _now():
    return datetime.now(timezone.utc).isoformat()


# --- Hierarchical keys -------------------------------------------------------

def series_key(series_id):
    return f"series/{series_id}"


def book_key(series_id, book_num):
    return f"series/{series_id}/book/{book_num}"


def chapter_key(series_id, book_num, chapter_num):
    return f"series/{series_id}/book/{book_num}/chapter/{chapter_num}"


# --- Read --------------------------------------------------------------------

def iter_history():
    """Every record ever written, in file (chronological) order — NOT collapsed to
    last-writer-wins. `revive` needs the full history to find the state a unit held
    just before it failed."""
    history = []
    path = paths.journal_file()
    if not path.exists():
        return history
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                history.append(json.loads(line))
            except json.JSONDecodeError:
                continue          # tolerate a torn final line from a crash
    return history


def load_records():
    """Replay the journal into {key: record}, last-writer-wins."""
    records = {}
    for rec in iter_history():
        key = rec.get("key")
        if key:
            records[key] = rec
    return records


# --- Write -------------------------------------------------------------------

def write_record(record):
    """Append a full snapshot of one unit's record. Returns the written record."""
    record = dict(record)
    record["updated_at"] = _now()
    path = paths.journal_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def set_status(records, record, status, **fields):
    """Update a record's status (and optional fields), append it, and keep the
    in-memory `records` map in step so a single cycle sees its own writes."""
    record = dict(record)
    record["status"] = status
    record.update(fields)
    written = write_record(record)
    records[written["key"]] = written
    return written


def log_decision(key, label, text):
    """Append a human-readable block to decisions.log for audit."""
    path = paths.decisions_log()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n===== {_now()}  [{label}]  ({key}) =====\n")
        fh.write((text or "").rstrip() + "\n")


# --- Record constructors -----------------------------------------------------

def new_series(series_id, prompt_path, prompt_text):
    return {
        "key": series_key(series_id),
        "level": "series",
        "series_id": series_id,
        "status": states.PROMPT_DROPPED,
        "created_at": _now(),
        "prompt_path": str(prompt_path),
        "prompt_text": prompt_text,
        "universes": [],        # filled at research
        "book_count": None,     # filled at series planning
        "error": None,
    }


def new_book(series_id, book_num, title=None):
    return {
        "key": book_key(series_id, book_num),
        "level": "book",
        "series_id": series_id,
        "book_num": book_num,
        "title": title or "",
        "status": states.QUEUED,
        "created_at": _now(),
        "chapter_count": None,  # filled at outline
        "error": None,
    }


def new_chapter(series_id, book_num, chapter_num):
    return {
        "key": chapter_key(series_id, book_num, chapter_num),
        "level": "chapter",
        "series_id": series_id,
        "book_num": book_num,
        "chapter_num": chapter_num,
        "status": states.PENDING,
        "created_at": _now(),
        "revisions": 0,         # how many times the critique loop bounced it
        "readability": None,    # last computed {fk_grade, flesch_ease, ...}
        "error": None,
    }


# --- Resume helpers ----------------------------------------------------------

def books_of(records, series_id):
    """Every book record under a series, ordered by book number."""
    prefix = series_key(series_id) + "/book/"
    books = [r for r in records.values()
             if r.get("level") == "book" and r["key"].startswith(prefix)]
    return sorted(books, key=lambda r: r["book_num"])


def chapters_of(records, series_id, book_num):
    """Every chapter record under a book, ordered by chapter number."""
    prefix = book_key(series_id, book_num) + "/chapter/"
    chapters = [r for r in records.values()
                if r.get("level") == "chapter" and r["key"].startswith(prefix)]
    return sorted(chapters, key=lambda r: r["chapter_num"])


def first_incomplete_chapter(records, series_id, book_num):
    """The first chapter still to be written — where DRAFTING resumes after a crash.

    Accepted chapters and their bible merges are already durable, so the engine never
    redoes them, and a RETIRED record is a chapter number the book turned out not to
    have. None when every chapter is done."""
    for ch in chapters_of(records, series_id, book_num):
        if ch["status"] not in states.CHAPTER_DONE:
            return ch
    return None


def _replay_with_prior_resumable():
    """Replay history into ({key: current record}, {key: last resumable status}).

    Both rewind paths need the same two things: where a unit is now, and the last
    status it held that the machine actually dispatches on."""
    current = {}
    prior_resumable = {}
    for rec in iter_history():                 # chronological: last assignment wins
        key = rec.get("key")
        if not key:
            continue
        previous = current.get(key, {}).get("status")
        if previous in states.RESUMABLE:
            prior_resumable[key] = previous
        current[key] = rec
    return current, prior_resumable


def _rewind(record, target):
    """Append a copy of `record` at `target`, error cleared."""
    rewound = dict(record)
    rewound["status"] = target
    rewound["error"] = None
    write_record(rewound)


def recover_stale():
    """Rewind every unit abandoned in an in-progress status back to its last resumable
    one, so a killed or crashed stage is retried instead of wedging forever.

    Safe to call only while holding the daemon lock: that is what makes "in a transient
    status" mean "abandoned" rather than "someone else is working on it". Called once
    at engine startup, before the first cycle.

    Returns a list of (key, new_status)."""
    current, prior_resumable = _replay_with_prior_resumable()
    recovered = []
    for key, rec in current.items():
        if rec.get("status") not in states.TRANSIENT:
            continue
        target = prior_resumable.get(key)
        if not target:
            continue                          # nothing sensible to rewind to
        _rewind(rec, target)
        recovered.append((key, target))
    return recovered


def revive_series(series_id):
    """Rewind every stuck unit under a series so it dispatches again immediately.

    Two callers, one behaviour. A re-dropped prompt calls this to say "try again now",
    and the engine calls it on a series carrying statuses from the build that had
    terminal failures. Both mean the same thing: nothing here is abandoned, so put it
    back on a status the machine has a handler for.

    Durable artifacts — frozen canon, the plan, the outline, accepted chapters, merged
    bible facts, locked sheets, accepted images — are all keyed on disk and untouched,
    so the engine picks up exactly where it stopped (an image failure resumes at
    ILLUSTRATING and re-drains the queue idempotently).

    What gets rewound:

      * A **stalled** unit is resumed at once and its stall counter is cleared. That is
        the whole content of the human gesture: the engine would have retried on its
        own schedule, and a person moving the file is asking for it to happen now and
        for the backoff to start over.
      * A unit holding a **legacy terminal status** — FAILED, FAILED_CHAPTER — is
        rewound to its last resumable status, or for a chapter to PENDING, which is the
        entry point of a loop that is idempotent.

    Returns a list of (key, new_status) for what was revived (possibly empty)."""
    current, prior_resumable = _replay_with_prior_resumable()
    prefix = series_key(series_id)
    stuck = states.DEAD_ENDS | {states.STALLED}
    revived = []
    for key, rec in current.items():
        if key != prefix and not key.startswith(prefix + "/"):
            continue
        status = rec.get("status")
        if status not in stuck:
            continue

        if rec.get("level") == "chapter":
            target = states.PENDING
        else:
            target = (rec.get("stall_resume_to") if status == states.STALLED else None)
            target = target or prior_resumable.get(key)
        if not target:
            continue                          # nothing sensible to rewind to

        fresh = dict(rec)
        fresh["status"] = target
        fresh["error"] = None
        fresh["stall_count"] = 0
        fresh["stalled_at"] = None
        if rec.get("level") == "chapter":
            fresh["revisions"] = 0
            fresh["stage_errors"] = 0
        write_record(fresh)
        revived.append((key, target))
    return revived
