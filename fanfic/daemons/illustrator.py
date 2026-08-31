"""illustrator — the parallel image worker. Self-looping, low-priority I/O.

Drains the same scene queue the engine drains, using the same `render_scene`
primitive, so the two can never disagree about what "accepted" means. The drain is
idempotent — an entry whose slot is already resolved is skipped — so both working it
at once is safe. This daemon is a throughput accelerator: book 1 gets illustrated
while book 2 is still being written.

One image per cycle on purpose. It yields to the sibling fleets on the shared mini,
and it means a stuck entry costs one cycle rather than wedging the queue.

    python3 -m fanfic.daemons.illustrator
"""

from .. import clock, config, states
from ..errors import QuotaExceeded
from ..infra import locks, log as logging
from ..infra import journal, storage
from .. import paths, jobspec
from ..stages import illustration
from . import loop

LABEL = "illustrator"

# Statuses past the point where another picture could reach the reader. Binding has
# already assembled the epub, so topping a chapter up there would spend money on art
# nothing would print.
_PAST_ILLUSTRATION = {states.BINDING, states.BOUND, states.DELIVERING,
                      states.DELIVERED, states.COMPLETED}


def cycle(log):
    # Vision critique is a Claude call, so this worker observes the same quiet hours
    # as the engine. Drawing itself no longer costs the owner anything — the pictures
    # come out of a browser session, not the shared seat — but a scene is not accepted
    # until it has been critiqued, so pausing the whole cycle is simpler and cannot
    # half-finish a slot.
    blocked, nap, reason = clock.blackout()
    if blocked:
        log(reason)
        return nap

    # ANCHORS BEFORE SHEETS. A sheet drawn from a paragraph rather than from the show's
    # own art is a bad anchor propagated to every render its character appears in, and
    # it is invisible on disk — the `.png` is there and looks like somebody. Repairing
    # one costs a sheet and the pictures it anchored; leaving it costs the book's whole
    # look. This runs before locking new sheets so the repair is not queued behind
    # forty chapters of fresh work.
    if _relock_a_blind_sheet(log):
        return config.POLL_INTERVAL_SEC

    # SHEETS BEFORE SCENES, and this daemon owns that now.
    #
    # Reference sheets used to be generated only by the scribe, on the book's way into
    # ILLUSTRATING. That was survivable while all the pictures were drawn at the end;
    # it is a deadlock now that chapters queue their art the moment they are accepted,
    # because `render_scene` refuses to draw anyone who has no locked sheet and the
    # scribe is busy writing chapter 9. So the worker builds its own anchors.
    if _lock_a_missing_sheet(log):
        return config.POLL_INTERVAL_SEC

    # TOP-UP BEFORE DRAINING, and this daemon owns it.
    #
    # A chapter directed under a lower per-chapter ceiling is short of pictures for
    # the rest of its life unless something re-visits it, and the scribe will not:
    # a chapter is directed once, at acceptance, and the book does not reach
    # ILLUSTRATING until the last chapter is written. Eight chapters of the live book
    # sat at two pictures against five and six settings for exactly that reason.
    #
    # It belongs here rather than in the scribe because this daemon has the spare
    # cycles and because ownership has to be single: the queue is an append-only file
    # with no lock, and two processes topping up the same chapter would duplicate
    # slots and pay for both. The scribe writes chapters that have no entries; this
    # writes the ones that have too few.
    if _top_up_a_short_chapter(log):
        return config.POLL_INTERVAL_SEC

    pending = illustration.due_scene_entries()
    if not pending:
        return config.IDLE_INTERVAL_SEC
    try:
        # Walk the queue rather than insisting on its head. A scene can legitimately
        # DEFER — its cast has no locked sheet yet — and taking `pending[0]` every
        # cycle turns one deferred entry into a total stop for the image pipeline. It
        # did: an art director named "Ford Pines" where the bible says "Stanford
        # Pines", the sheet for that name could never exist, and the drainer sat on
        # that one scene every five seconds while twenty-four later ones waited.
        dest = None
        for entry in pending[:config.IMAGE_QUEUE_SCAN]:
            dest = illustration.render_scene(entry, log_fn=log)
            if dest:
                log(f"rendered {dest.name}")
                break
    except QuotaExceeded as quota:
        wait = max(config.IMAGE_QUOTA_BACKOFF_SEC, int(quota.retry_after or 0) + 1)
        log(f"image quota/rate limit; sleeping {wait}s")
        return wait
    except RuntimeError as exc:
        # One scene failing costs this cycle. The slot keeps its place in the queue and
        # its rung on the ladder, and comes back.
        log(f"scene render failed (parked for retry): {exc}")
    return config.POLL_INTERVAL_SEC


def _relock_a_blind_sheet(log):
    """Re-lock one sheet that was drawn without the show's own art. True if it did.

    One per cycle, like everything else here. It settles quickly: every character is
    examined once and then carries a recorded provenance, so a book whose sheets are
    all source-backed pays one bible read a cycle for this."""
    records = journal.load_records()
    for sid, book_num in illustration.queued_books():
        series_rec = records.get(journal.series_key(sid))
        if not series_rec:
            continue
        book_rec = records.get(journal.book_key(sid, book_num), {})
        if book_rec.get("status") in _PAST_ILLUSTRATION:
            continue                # bound already; a better sheet cannot reach it
        try:
            if illustration.relock_blind_sheet(series_rec, book_num, log_fn=log):
                return True
        except (RuntimeError, ValueError, KeyError, OSError) as exc:
            log(f"sheet re-lock check for book {book_num} of {sid} did not run "
                f"({exc}); the queue is drained as normal")
    return False


def _top_up_a_short_chapter(log):
    """Direct the pictures one chapter is short of, for any book still being made.

    Every book with a queue, not just the ones with something left to render — the
    chapters this exists for are precisely the ones whose two pictures both came out
    fine and which are therefore invisible to any "what is still pending" question.

    One chapter per cycle, like everything else here. Returns True if it did work."""
    from ..engine import illustrating

    records = journal.load_records()
    for sid, book_num in illustration.queued_books():
        series_rec = records.get(journal.series_key(sid))
        if not series_rec:
            continue
        book_rec = records.get(journal.book_key(sid, book_num), {})
        if book_rec.get("status") in _PAST_ILLUSTRATION:
            continue                # already bound; new pictures would never reach it
        try:
            if illustrating.top_up(records, series_rec, book_num, log_fn=log):
                return True
        except (RuntimeError, ValueError, KeyError, OSError) as exc:
            # Art direction is a model call. It failing must never cost the cycle that
            # would have drawn something already chosen.
            log(f"top-up for book {book_num} of {sid} did not run ({exc}); "
                f"draining what is already queued")
    return False


def _lock_a_missing_sheet(log):
    """Generate ONE missing reference sheet for any series with queued art.

    One per cycle, like everything else here: it keeps the daemon responsive, it paces
    against rate limits, and it means a stuck character costs a cycle rather than the
    book. Returns True if it did work."""
    records = journal.load_records()
    for entry in illustration.pending_scene_entries():
        sid, book_num = entry["series_id"], entry["book_num"]
        series_rec = records.get(journal.series_key(sid))
        if not series_rec:
            continue
        bible = storage.load_json(paths.series_bible_path(sid), {})
        style = jobspec.art_direction(series_rec.get("prompt_text", ""))
        for name in entry.get("characters", []):
            spec = (bible.get("characters") or {}).get(name)
            if not spec or not illustration.due(
                    paths.sheet_path(sid, book_num, name)):
                continue
            log(f"locking reference sheet for {name} before any scene uses it")
            got = illustration.generate_reference_sheet(
                series_rec, book_num, spec, log_fn=log, style=style)
            bible = storage.load_json(paths.series_bible_path(sid), {})
            bible["characters"][name]["ref_sheet_locked"] = bool(got)
            storage.save_json(bible, paths.series_bible_path(sid))
            return True
    return False


def main():
    log = logging.logger(LABEL)
    lock = locks.acquire(LABEL, log_fn=log)
    loop(LABEL, lambda: cycle(log), log, config.IDLE_INTERVAL_SEC)
    lock.close()


if __name__ == "__main__":
    main()
