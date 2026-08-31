"""The book-level machine: QUEUED -> ... -> COMPLETED, one step per call.

Chapters draft sequentially inside a book, because chapter N needs chapter N-1's exit
state. Illustration pipelines in parallel, which is what makes an overnight novel
plausible rather than fantasy.

**A book does not fail.** It used to: one chapter that could not satisfy the critics
parked, and a parked chapter failed the book, and a failed book failed the series, and
the prompt was filed away. On the first real novel that mechanism discarded 113,000
words of accepted prose over chapter 22 of 37 — twenty-one good chapters stopped dead
because the twenty-second was stubborn, with no path back that did not require a person
to notice and move a file.

So the two ways a book used to stop are both gone:

  * A chapter that will not come clean **ships holding its defects** and is revisited in
    the REVISING sweep. `engine.chapter` guarantees every chapter lands.
  * A stage that raises **stalls** the book rather than failing it — recorded, retried
    on an escalating backoff, forever. See `engine.stalling`.

What is left is a machine whose only exits are COMPLETED and "waiting to try again".
"""

from pathlib import Path

from .. import config, paths, states
from ..infra import journal, storage
from ..stages import binding, delivery, metaplan, outlining
from . import chapter as chapter_level
from . import illustrating, revising, stalling


def advance(records, series_rec, book_rec, log_fn=print):
    """Advance one book by exactly one step."""
    status = book_rec["status"]
    book_num = book_rec["book_num"]
    key = book_rec["key"]

    if status == states.STALLED:
        stalling.wake(records, book_rec, log_fn=log_fn)
        return

    try:
        if status in states.DEAD_ENDS:
            # A record left behind by the build that had terminal failures. Rewind it
            # rather than honouring a verdict the machine no longer issues.
            journal.set_status(records, book_rec, states.DRAFTING, error=None)
            log_fn(f"book {book_num}: clearing a legacy FAILED status; resuming")
            return

        if status == states.QUEUED:
            # The meta plan first: the chapter breakdown and, with it, every character
            # collision the book promises. The outliner inherits that assignment and
            # expands it — it does not get to move a scene into a chapter it would
            # rather have it in, because two documents owning the same fact is the
            # failure this project's stories record three separate times.
            journal.set_status(records, book_rec, states.META_PLANNING)
            meta = metaplan.run(series_rec, book_num, log_fn=log_fn)
            journal.set_status(records, records[key], states.META_PLANNED,
                               chapter_count=meta.get("chapter_count"),
                               interactions=len(metaplan.ledger(meta)))
            log_fn(f"book {book_num}: meta plan — {meta.get('chapter_count')} "
                   f"chapters, {len(metaplan.ledger(meta))} interactions")
            return

        if status == states.META_PLANNED:
            journal.set_status(records, book_rec, states.OUTLINING)
            result = outlining.run(series_rec, book_num, log_fn=log_fn)
            for n in range(1, result["chapter_count"] + 1):
                record = journal.new_chapter(series_rec["series_id"], book_num, n)
                journal.write_record(record)
                records[record["key"]] = record
            journal.set_status(records, records[key], states.OUTLINED,
                               chapter_count=result["chapter_count"])
            log_fn(f"book {book_num}: outlined {result['chapter_count']} chapters")
            return

        if status == states.OUTLINED:
            journal.set_status(records, book_rec, states.DRAFTING)
            return

        if status == states.DRAFTING:
            _advance_drafting(records, series_rec, book_rec, log_fn=log_fn)
            return

        if status == states.DRAFTED:
            _report_book_length(records, series_rec, book_rec, log_fn=log_fn)
            journal.set_status(records, book_rec, states.REVISING)
            return

        if status == states.REVISING:
            if revising.advance(records, series_rec, book_rec, log_fn=log_fn):
                journal.set_status(records, book_rec, states.ILLUSTRATING)
            return

        if status == states.ILLUSTRATING:
            illustrating.advance(records, series_rec, book_rec, log_fn=log_fn)
            return

        if status == states.ILLUSTRATED:
            journal.set_status(records, book_rec, states.BINDING)
            title = (book_rec.get("title")
                     or f"{series_rec['series_id']} Book {book_num}")
            epub = binding.build_epub(series_rec, book_num, title)
            journal.set_status(records, records[key], states.BOUND,
                               epub_path=str(epub))
            log_fn(f"book {book_num}: bound + validated -> {epub.name}")
            return

        if status == states.BOUND:
            journal.set_status(records, book_rec, states.DELIVERING)
            epub = Path(book_rec.get("epub_path") or paths.epub_path(
                series_rec["series_id"], book_num,
                book_rec.get("title") or f"book{book_num}"))
            dest = delivery.deliver(series_rec, book_num, epub,
                                    series_name=book_rec.get("title"))
            journal.set_status(records, records[key], states.DELIVERED,
                               delivered_path=str(dest))
            journal.set_status(records, records[key], states.COMPLETED)
            log_fn(f"book {book_num}: DELIVERED -> {dest}")
            return
    except RuntimeError as exc:
        # Stall, never fail. The record remembers where to come back to, and the wait
        # doubles each time, so a persistent bug is retried hourly rather than being
        # retried in a hot loop or abandoned.
        stalling.stall(records, records.get(key, book_rec), str(exc), log_fn=log_fn)


def _report_book_length(records, series_rec, book_rec, log_fn=print):
    """Measure the finished book against `BOOK_MIN_WORDS` and record the number.

    Reported, never blocking, and the distinction is the whole point. By the time this
    runs the book is written; refusing it would achieve nothing except stopping a novel
    that exists, and the one thing this project will not do is add a way for a finished
    book to be thrown away. What a floor can honestly buy here is that somebody finds
    out — in the log and on the journal record — rather than discovering it by opening
    the epub.

    It exists because the constant did not, in any meaningful sense. `BOOK_MIN_WORDS`
    was added as "a minimum of roughly 150,000", written into the config table as a
    floor, and then read by nothing at all. That is precisely the failure recorded one
    section above it in the README: a documented invariant with no code behind it is a
    wish, and this file's own picture budget spent a run being wrong for the same
    reason."""
    sid = series_rec["series_id"]
    book_num = book_rec["book_num"]
    outline = storage.load_json(paths.outline_path(sid, book_num), {"chapters": []})
    words = 0
    for chapter in outline.get("chapters") or []:
        path = paths.chapter_path(sid, book_num, chapter.get("number"))
        if path.exists():
            words += len(path.read_text(encoding="utf-8").split())

    floor = config.BOOK_MIN_WORDS
    journal.set_status(records, book_rec, book_rec["status"], book_words=words)
    if floor and words < floor:
        journal.log_decision(
            book_rec["key"], "BOOK UNDER THE LENGTH FLOOR",
            f"{words:,} words against a floor of {floor:,}. Nothing is blocked and the "
            f"book ships; this is recorded so it is known before the epub is opened. "
            f"If it matters, the lever is the chapter count at meta-plan time, never a "
            f"per-chapter word target — that is what produced the padding this floor "
            f"replaced.")
        log_fn(f"book {book_num}: {words:,} words, UNDER the {floor:,} floor — "
               f"shipping anyway, recorded on the record")
    else:
        log_fn(f"book {book_num}: {words:,} words across "
               f"{len(outline.get('chapters') or [])} chapters")


def _advance_drafting(records, series_rec, book_rec, log_fn=print):
    """Run the next unfinished chapter, or close out DRAFTING."""
    sid = series_rec["series_id"]
    book_num = book_rec["book_num"]

    chapter_rec = journal.first_incomplete_chapter(records, sid, book_num)
    if chapter_rec is None:
        journal.set_status(records, book_rec, states.DRAFTED)
        log_fn(f"book {book_num}: all chapters accepted")
        return

    if _retire_phantom(records, sid, book_num, chapter_rec, log_fn=log_fn):
        return

    if chapter_rec["status"] in states.DEAD_ENDS:
        # Left behind by the build that parked chapters. Un-park it: the chapter loop
        # no longer has an outcome that requires this to be honoured.
        journal.set_status(records, chapter_rec, states.PENDING, error=None,
                           revisions=0, stage_errors=0)
        log_fn(f"book {book_num} ch {chapter_rec['chapter_num']}: "
               f"clearing a legacy parked status; resuming")
        return

    chapter_level.run(records, series_rec, book_rec, chapter_rec, log_fn=log_fn)


def _retire_phantom(records, sid, book_num, chapter_rec, log_fn=print):
    """Retire a chapter record the current outline has no entry for. Returns True if
    it did.

    These are real and they are not rare. Outlining re-proposes up to
    `GATE_MAX_ATTEMPTS` times when the structure gate rejects it, and the book spawns
    one record per chapter of whichever attempt passed — but an *earlier* build may
    already have spawned records against a longer outline, and nothing ever removed
    them. The live crossover carried 23 such records: a 60-chapter outline was rejected
    and replaced with the specified 37, and chapters 38-60 sat in the journal as
    PENDING forever, indistinguishable from work still to do.

    They cannot be drafted, because there is nothing to draft. Left alone they are the
    one input that turns "never give up" into a genuinely useless loop: the book
    finishes chapter 37, meets chapter 38, cannot outline it, stalls, waits, retries,
    and does that until somebody looks. So the record is retired rather than run, which
    says the thing that is actually true — this number is not a chapter."""
    n = chapter_rec["chapter_num"]
    if chapter_rec["status"] in states.CHAPTER_DONE:
        return False
    outline = storage.load_json(paths.outline_path(sid, book_num), {"chapters": []})
    chapters = outline.get("chapters") or []
    if not chapters:
        return False              # no outline at all is a different problem entirely
    if any(c.get("number") == n for c in chapters):
        return False

    journal.log_decision(
        chapter_rec["key"], "RETIRED",
        f"the outline for book {book_num} has {len(chapters)} chapters and no entry "
        f"for chapter {n}. This record is left over from a superseded outline, so it "
        f"is retired rather than drafted.")
    journal.set_status(records, chapter_rec, states.RETIRED, error=None)
    log_fn(f"book {book_num} ch {n}: retired — not in the {len(chapters)}-chapter "
           f"outline")
    return True
