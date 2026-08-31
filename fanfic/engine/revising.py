"""The REVISING sweep — a second editorial pass over the chapters that shipped flawed.

A chapter that could not be made clean inside its own budget is not parked and is not
thrown away: it ships, carrying a list of what is still wrong with it, and lands here.
The sweep runs once every chapter in the book exists, which buys three things the
per-chapter loop could not have:

  * **The defect may have stopped being one.** A chapter flagged for a dangling thread
    is often fine once the chapter that picks the thread up has been written. Judging
    chapter 22 against a book that stopped at chapter 22 is judging it against a
    cliff-edge.
  * **The editor can see the whole book.** Contradictions between two chapters are
    invisible from inside either one, and a fix chosen without the other chapter in
    view is the reason the same defect kept coming back in a different costume.
  * **It is cheap.** Only flagged chapters are re-read, and each gets an anchored
    repair rather than a redraft, so a sweep over a book with six flagged chapters
    costs about what two chapters of the old revision loop cost.

The sweep advances one chapter per engine cycle, like every other unit of work here, so
it can be interrupted, resumed, and watched.
"""

from .. import config, paths, states
from ..infra import journal, storage
from ..memory import store
from ..stages import editing, surgery


def flagged(records, series_id, book_num):
    """Chapters the sweep still owes a pass, in order.

    Two reasons a chapter is here, and they get different budgets because they are
    different claims.

      * **Known defects.** Its editorial budget ran out with blocking issues still in
        the text. Worth up to `REVISION_SWEEPS` rounds, because the sweep may well
        resolve them — half of these are dangling-thread complaints that stop being
        true once the chapter that picks the thread up exists.

      * **Unverified repairs.** Its last pass found defects, repaired them all, and was
        the last pass, so nothing has re-read those repairs. Worth a first round.

      * **The last round found blocking defects in it.** Worth another, and this is the
        rule that actually earns its keep.

    That third condition is the stopping rule, and it is deliberately about *blocking
    yield* rather than about edits applied. Two reasons, and they are the two traps
    this project has already paid for.

    "Sweep until nothing is unread" does not terminate: every pass that applies an edit
    leaves that edit unread, so a chapter the editor keeps finding polish in would sweep
    forever. And "sweep while the editor still finds something" is the critic-who-can-
    never-be-satisfied trap in a new costume — a demanding editor asked "is this
    perfect?" always says no, so polish must never buy another round.

    Blocking yield is neither. It is measurable, it falls, and it is about the thing the
    project exists to protect. Measured on this book's first sweep round: 24 chapters
    re-read against the finished novel turned up **18 blocking defects, three of them
    canon violations** — Polly given an age she cannot be, Eda knowing the Titan origin
    of glyph magic years before canon reveals it, Bill claiming he has no legs. Every
    one had survived the per-chapter loop, and every one is the kind of thing a fan
    notices on page one. A round that yields that is worth its ~$1.50 a chapter. A round
    that yields only polish is not, and stops."""
    out = []
    for rec in journal.chapters_of(records, series_id, book_num):
        sweeps = int(rec.get("sweeps") or 0)
        if sweeps >= config.REVISION_SWEEPS:
            continue
        if rec.get("outstanding_issues"):
            out.append(rec)
        elif sweeps == 0 and rec.get("unverified_repairs"):
            out.append(rec)
        elif sweeps and rec.get("sweep_found_blocking"):
            out.append(rec)
    return out


def advance(records, series_rec, book_rec, log_fn=print):
    """Re-edit the next flagged chapter. Returns True when the sweep is finished.

    The caller owns the transition out of REVISING, because leaving ILLUSTRATING is
    entered by exactly one code path that also seeds the image queue, and a second
    entry point would seed it twice."""
    sid = series_rec["series_id"]
    book_num = book_rec["book_num"]

    pending = flagged(records, sid, book_num)
    if not pending:
        remaining = sum(1 for rec in journal.chapters_of(records, sid, book_num)
                        if rec.get("outstanding_issues"))
        log_fn(f"book {book_num}: revision sweep complete "
               f"({remaining} chapter(s) still carrying notes)")
        return True

    _resweep(records, series_rec, book_num, pending[0], log_fn=log_fn)
    return False


def _resweep(records, series_rec, book_num, chapter_rec, log_fn=print):
    """One chapter, re-edited against the finished book."""
    sid = series_rec["series_id"]
    n = chapter_rec["chapter_num"]
    sweeps = int(chapter_rec.get("sweeps") or 0) + 1

    outline = storage.load_json(paths.outline_path(sid, book_num), {"chapters": []})
    chapter_outline = next((c for c in outline["chapters"] if c["number"] == n), None)
    path = paths.chapter_path(sid, book_num, n)
    if chapter_outline is None or not path.exists():
        journal.set_status(records, chapter_rec, chapter_rec["status"], sweeps=sweeps,
                           outstanding_issues=[])
        return

    prose = path.read_text(encoding="utf-8")
    before = list(chapter_rec.get("outstanding_issues") or [])
    log_fn(f"book {book_num} ch {n}: revision sweep {sweeps} "
           f"({len(before)} outstanding issue(s))")

    try:
        report = editing.review(series_rec, book_num, chapter_outline, prose,
                                pass_num=100 + sweeps, log_fn=log_fn)
    except RuntimeError as exc:
        # The sweep is a bonus pass over prose that is already committed and already
        # readable. A failure here must never cost the book, so it counts as a sweep
        # spent and the chapter keeps its notes.
        journal.log_decision(chapter_rec["key"], f"sweep {sweeps} failed", str(exc))
        journal.set_status(records, chapter_rec, chapter_rec["status"], sweeps=sweeps)
        log_fn(f"book {book_num} ch {n}: sweep failed ({exc}); leaving the chapter as is")
        return

    prose, applied, rejected = editing.apply_report(prose, report)
    spliced = 0
    if report["structural"]:
        prose, spliced = surgery.run(
            series_rec, book_num, chapter_outline, prose, report["structural"],
            style_guide=store.load(series_rec, book_num).style_guide, log_fn=log_fn)

    outstanding = [f"{i['kind'].upper()}: {i['issue']}"
                   for i in editing.unrepaired(report, applied)]
    outstanding += list(report["gate_failures"])

    if applied or spliced:
        storage.atomic_write_text(prose, path)

    journal.log_decision(
        chapter_rec["key"], f"revision sweep {sweeps}",
        f"{len(before)} issue(s) on entry, {len(applied)} edit(s) applied, "
        f"{len(rejected)} rejected, {spliced} passage(s) replaced, "
        f"{len(outstanding)} still open.\n"
        + "\n".join(f"  - {i}" for i in outstanding))
    # A sweep that found nothing is the verification this chapter was queued for; one
    # that applied edits has left its own repairs unread, and stops here anyway — see
    # `flagged` on why that budget is a count rather than a condition.
    # Whether THIS round found real defects is what decides if there is another one.
    # Recorded rather than recomputed, because by the next round the text has moved.
    found_blocking = bool(report["blocking"]) or bool(report["gate_failures"])
    journal.set_status(records, chapter_rec, chapter_rec["status"], sweeps=sweeps,
                       outstanding_issues=outstanding,
                       unverified_repairs=bool(applied or spliced),
                       sweep_found_blocking=found_blocking,
                       readability=report["readability"])
    log_fn(f"book {book_num} ch {n}: sweep {sweeps} — {len(report['blocking'])} "
           f"blocking, {len(applied)} edit(s) applied, {len(outstanding)} still open"
           + ("; another round" if found_blocking
              and sweeps < config.REVISION_SWEEPS else ""))
