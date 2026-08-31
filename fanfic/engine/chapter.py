"""The editorial loop for one chapter — the innermost level of the machine.

    draft once -> edit -> edit -> ... -> BIBLE MERGE -> place prose -> journal

Two properties define it, and both are corrections of the design this project shipped
with.

**The chapter is drafted exactly once.** Every later change is an anchored repair:
find/replace edits from `stages.editing`, or a passage replacement from
`stages.surgery`. Nothing ever re-emits the whole chapter. The old loop asked a writer
to re-emit five thousand words with only the flagged parts changed, and it drifted
every time — ch 8 went 15 -> 4 -> 3 -> 4 -> 2 -> 3 -> 3 -> 3 -> 2 -> 10 -> 7 -> 6 -> 6
-> 8 -> 6 -> 14 across twenty-four attempts, each of which fixed what it was told to
and broke something it was not. With repairs anchored, the count falls monotonically
because untouched text is not passed through a model at all.

**A chapter never parks.** If it is still carrying defects when its editorial budget
runs out, it ships with those defects recorded on its journal record, and the book
carries on. It is then re-edited in the book's REVISING sweep, when every chapter
exists and the editor can see the whole book. The old machine parked such a chapter,
which failed its book, which failed the series — one chapter out of thirty-seven
discarding 113,000 words of accepted prose and stopping the run dead until a person
intervened. Shipping a flawed chapter and coming back to it is strictly better than
that in every case, including the ones where the chapter really is bad.

The ordering of the last three steps is unchanged and is still the most important
sequencing decision in the engine: merge the bible *before* placing the prose, so a
ledger contradiction is one more editorial pass rather than a corrupt bible with a
matching chapter on disk; and place the prose immediately before the journal writes,
with nothing in between, so the verified state is durable before the engine advances.
"""

from .. import config, paths, states
from ..errors import RevisionNeeded
from ..infra import journal, storage
from ..memory import store
from ..stages import bible_update, drafting, editing, surgery


def run(records, series_rec, book_rec, chapter_rec, log_fn=print):
    """Drive one chapter to ACCEPTED/BIBLE_MERGED. It always gets there."""
    sid = series_rec["series_id"]
    book_num = book_rec["book_num"]
    n = chapter_rec["chapter_num"]

    outline = storage.load_json(paths.outline_path(sid, book_num), {"chapters": []})
    chapters = outline["chapters"]
    chapter_outline = next((c for c in chapters if c["number"] == n), None)
    if chapter_outline is None:
        # Not a content failure and not the chapter's fault: the outline is missing an
        # entry the book claims exists. Stall the BOOK so the outline can be rebuilt,
        # rather than parking a chapter that was never given anything to write.
        journal.set_status(records, chapter_rec, states.PENDING,
                           error=f"no outline entry for chapter {n}")
        raise RuntimeError(f"outline has no entry for chapter {n}")

    prose, stage_errors = _obtain_draft(
        records, series_rec, book_rec, chapter_rec, chapter_outline, chapters,
        log_fn=log_fn)

    prose, trajectory, outstanding, verified = _edit_to_clean(
        records, series_rec, book_num, chapter_rec, chapter_outline, prose,
        log_fn=log_fn)

    _commit(records, series_rec, book_rec, chapter_rec, chapter_outline, prose,
            trajectory, outstanding, stage_errors, verified, log_fn=log_fn)


# --- drafting ----------------------------------------------------------------

def _obtain_draft(records, series_rec, book_rec, chapter_rec, chapter_outline,
                  chapters, log_fn=print):
    """The chapter's prose, drafted or recovered. Returns (prose, stage_errors).

    A draft already on disk for a chapter the journal says is mid-flight is *reused*,
    not re-rolled. Restarting the fleet during a chapter used to cost the draft — five
    thousand words and about a dollar of allowance — for no reason at all, since the
    file was sitting right there and nothing downstream had rejected it."""
    sid = series_rec["series_id"]
    book_num = book_rec["book_num"]
    n = chapter_rec["chapter_num"]
    draft_path = paths.draft_path(sid, book_num, n)

    if chapter_rec["status"] in (states.CH_DRAFTED, states.CH_EDITING):
        existing = _read(draft_path)
        if len(existing.split()) >= config.DRAFT_RESUME_MIN_WORDS:
            log_fn(f"book {book_num} ch {n}: resuming from the draft on disk "
                   f"({len(existing.split()):,} words)")
            return existing, int(chapter_rec.get("stage_errors") or 0)

    prev_exit, prev_tail = "", ""
    if n > 1:
        previous = next((c for c in chapters if c["number"] == n - 1), None)
        prev_exit = (previous or {}).get("exit_state", "")
        # The outline's exit_state is what the previous chapter was *planned* to
        # establish. The editor judges against the chapter that was actually accepted,
        # and after several repairs those diverge — so the writer gets the real closing
        # prose too. Absent (an older run, a chapter still to come) is fine: the digest
        # simply omits the section.
        prev_tail = _chapter_tail(sid, book_num, n - 1)

    stage_errors = int(chapter_rec.get("stage_errors") or 0)
    while True:
        try:
            prose, _ = drafting.draft_chapter(
                series_rec, book_num, chapter_outline, prev_exit,
                prev_tail=prev_tail, log_fn=log_fn)
        except RuntimeError as exc:
            # Infrastructure, not craft: a cut draft, a provider that died mid-stream.
            # Retried against its own cap, and when that runs out the *book* stalls
            # rather than the chapter parking — a subprocess that keeps dying is not
            # the writer failing to take direction, and it will resolve on its own or
            # when a person acts.
            stage_errors += 1
            journal.log_decision(chapter_rec["key"], f"draft stage error {stage_errors}",
                                 str(exc))
            log_fn(f"book {book_num} ch {n}: draft stage error {stage_errors}/"
                   f"{config.CHAPTER_STAGE_ERROR_RETRIES + 1}: {exc}")
            journal.set_status(records, records[chapter_rec["key"]], states.PENDING,
                               stage_errors=stage_errors)
            if stage_errors > config.CHAPTER_STAGE_ERROR_RETRIES:
                raise
            continue

        # `trajectory=[]` because this is NEW prose. The field is restored across a
        # restart (see `_edit_to_clean`), and a record that kept a redrafted chapter's
        # old blocking counts would spend its pass budget on a draft they were never
        # about — and would report a trend belonging to text that no longer exists.
        journal.set_status(records, records[chapter_rec["key"]], states.CH_DRAFTED,
                           stage_errors=stage_errors, trajectory=[])
        return prose, stage_errors


# --- editing -----------------------------------------------------------------

def _edit_to_clean(records, series_rec, book_num, chapter_rec, chapter_outline, prose,
                   log_fn=print):
    """Run editorial passes until the chapter is clean or the budget is spent.

    Returns (prose, trajectory, outstanding, verified).

    `outstanding` is what is still wrong when the loop stops. `verified` says whether
    the loop ended on a pass that *found nothing* — as opposed to one that found
    defects, repaired them all, and was then the last pass. Those are different states
    and conflating them is a lie of exactly the kind this file keeps paying for:
    chapter 24 ended 5 -> 2 -> 2 -> 2 with its final pass repairing a wrong attribution
    and a POV slip, and reported "ACCEPTED clean" because every defect it found had a
    repair that landed. Nothing had re-read those repairs.

    The budget bends the same way the old revision budget did, and for the same reason:
    the useful signal in an iterative process is not the count, it is whether the count
    is still moving. A chapter still shedding defects keeps its passes; one that has
    stopped improving does not get to spend the rest of the budget discovering that
    again."""
    sid = series_rec["series_id"]
    n = chapter_rec["chapter_num"]
    draft_path = paths.draft_path(sid, book_num, n)
    style_guide = store.load(series_rec, book_num).style_guide

    # RESTORED, not started empty. The draft on disk is reused across a restart
    # (`_obtain_draft`), so the passes already spent on it are part of this chapter's
    # history — but the trajectory used to live only in this function's frame, and a
    # restart mid-chapter silently threw it away. Chapter 10 went 5 -> 2 blocking, the
    # daemons were restarted to deploy a fix, and it was journaled `revisions: 1` and
    # logged `ACCEPTED (0) — its last pass found no defects`, which reads as a chapter
    # that was clean on arrival. It was not; it was a chapter three passes deep.
    #
    # Three things were wrong with that, in rising order of seriousness. The log line
    # is untrue. `EDIT_MAX_PASSES` stops being a cap, because a restart hands back a
    # full budget. And `_still_improving` cannot see a chapter that has stopped
    # converging, which is the whole mechanism that stops paying for a stalled loop.
    #
    # It also quietly corrupts the evidence: §5 of the handoff keeps EDIT_MAX_PASSES at
    # 3 on the strength of observed trajectories, and every restart resets one to look
    # cleaner than it was.
    live = records.get(chapter_rec["key"], chapter_rec)
    trajectory = [int(c) for c in (live.get("trajectory") or [])]
    if trajectory:
        log_fn(f"book {book_num} ch {chapter_rec['chapter_num']}: resuming the "
               f"editorial trajectory at {' -> '.join(str(c) for c in trajectory)}")
    outstanding = []
    verified = False
    stage_errors = int(chapter_rec.get("stage_errors") or 0)
    # Not 0: the passes in the restored trajectory were spent, and numbering them again
    # from 1 would re-run the budget as well as mislabel the pass in the audit log.
    pass_num = len(trajectory)

    while _may_edit(pass_num, trajectory):
        pass_num += 1
        journal.set_status(records, records[chapter_rec["key"]], states.CH_EDITING,
                           revisions=pass_num)
        try:
            report = editing.review(series_rec, book_num, chapter_outline, prose,
                                    pass_num=pass_num, log_fn=log_fn)
        except RuntimeError as exc:
            stage_errors += 1
            journal.log_decision(chapter_rec["key"],
                                 f"edit stage error {stage_errors}", str(exc))
            log_fn(f"book {book_num} ch {n}: edit stage error {stage_errors}/"
                   f"{config.CHAPTER_STAGE_ERROR_RETRIES + 1}: {exc}")
            if stage_errors > config.CHAPTER_STAGE_ERROR_RETRIES:
                # Out of editorial retries with a draft in hand. Ship what exists and
                # let the REVISING sweep try again later — the prose is real and the
                # failure is in the judging, not the writing.
                outstanding = ["EDITOR UNAVAILABLE: the editorial pass failed "
                               f"{stage_errors} times; last error: {exc}"]
                break
            pass_num -= 1        # an unjudged pass is not a pass
            continue

        blocking = list(report["blocking"]) + list(report["gate_failures"])
        trajectory.append(len(blocking))
        journal.log_decision(
            chapter_rec["key"], f"editorial pass {pass_num}",
            f"blocking={len(blocking)} polish={len(report['polish'])} "
            f"FK={report['readability']['fk_grade']} "
            f"ease={report['readability']['flesch_ease']} "
            f"words={report['readability']['words']}\n"
            + "\n".join(blocking + report["polish"]))
        journal.set_status(records, records[chapter_rec["key"]], states.CH_EDITING,
                           revisions=pass_num, readability=report["readability"],
                           trajectory=list(trajectory))

        if not blocking and not report["issues"] and not report["structural"]:
            log_fn(f"book {book_num} ch {n}: clean after {pass_num} editorial pass(es)")
            return prose, trajectory, [], True

        # Apply. Polish edits land alongside blocking ones — the severity decides
        # whether the chapter is finished, never whether a fix is worth applying.
        prose, applied, rejected = editing.apply_report(prose, report)
        if report["structural"]:
            prose, spliced = surgery.run(series_rec, book_num, chapter_outline, prose,
                                         report["structural"],
                                         style_guide=style_guide, log_fn=log_fn)
        else:
            spliced = 0
        storage.atomic_write_text(prose, draft_path)

        log_fn(f"book {book_num} ch {n}: pass {pass_num} — {len(blocking)} blocking, "
               f"{len(applied)} edit(s) applied, {len(rejected)} rejected, "
               f"{spliced} passage(s) replaced")

        # A gate failure is unrepaired by definition until the arithmetic says
        # otherwise, and it is not in `issues` — it is computed here, not proposed.
        # Leaving it out is how a chapter half its planned length shipped looking
        # clean, which is the exact hole the length gate was added to close.
        outstanding = ([f"{i['kind'].upper()}: {i['issue']}"
                        for i in editing.unrepaired(report, applied)]
                       + list(report["gate_failures"]))
        if not blocking:
            # Only polish was left, and it has now been applied. Done — running another
            # judgement pass over a chapter with no defects buys a fresh set of
            # opinions, not a better book. Not `verified`, though: the polish edits
            # themselves have not been read by anything.
            return prose, trajectory, [], False
        if not applied and not spliced:
            # The editor named defects and could repair none of them. Another identical
            # pass will do the same. Stop and hand the chapter to the sweep.
            log_fn(f"book {book_num} ch {n}: editor could not anchor any repair; "
                   f"deferring {len(outstanding)} issue(s) to the revision sweep")
            break

    return prose, trajectory, outstanding, verified


def _may_edit(pass_num, trajectory):
    """Whether this chapter gets another editorial pass.

    Below the soft cap, always. Above it, only while the blocking count is still
    falling — and never past the hard ceiling. A pass costs roughly a dollar of
    allowance, and the thing worth paying for is progress."""
    if pass_num < config.EDIT_MAX_PASSES:
        return True
    if pass_num >= config.EDIT_HARD_MAX_PASSES:
        return False
    return _still_improving(trajectory)


def _still_improving(trajectory):
    """Whether the last `EDIT_STALL_PASSES` passes beat the best count before them."""
    window = config.EDIT_STALL_PASSES
    if len(trajectory) <= window:
        return True
    return min(trajectory[-window:]) < min(trajectory[:-window])


# --- committing --------------------------------------------------------------

def _commit(records, series_rec, book_rec, chapter_rec, chapter_outline, prose,
            trajectory, outstanding, stage_errors, verified, log_fn=print):
    """Merge the bible, place the prose, journal it. The chapter always lands.

    `verified` separates "a pass read this chapter and found nothing" from "the last
    pass found things, fixed them, and was the last pass". Only the first is clean.
    The second is queued for one sweep round, which is what a sweep is for."""
    sid = series_rec["series_id"]
    book_num = book_rec["book_num"]
    n = chapter_rec["chapter_num"]
    trend = " -> ".join(str(c) for c in trajectory) or "clean on arrival"

    # The last pass's edits were applied and then nothing looked at the result. Most of
    # that cannot be checked without another judgement call — but the two gates are
    # arithmetic, they cost nothing, and an editor splitting sentences to escape "too
    # dense" can overshoot into "too simple" in a way the pass that did it cannot see.
    late, readability_now = editing.gate_failures(series_rec, book_num, prose)
    outstanding = list(outstanding)
    for failure in late:
        if failure not in outstanding:
            outstanding.append(failure)

    merge_note = _merge_bible(series_rec, book_num, n, prose, log_fn=log_fn)
    if merge_note:
        outstanding.append(merge_note)

    storage.atomic_write_text(prose, paths.chapter_path(sid, book_num, n))
    _close_interactions(sid, n, log_fn=log_fn)
    _enqueue_illustrations(records, series_rec, book_num, n, chapter_outline,
                           log_fn=log_fn)
    journal.set_status(records, records[chapter_rec["key"]], states.ACCEPTED,
                       revisions=len(trajectory), stage_errors=stage_errors,
                       readability=readability_now,
                       unverified_repairs=not verified,
                       outstanding_issues=outstanding)
    journal.set_status(records, records[chapter_rec["key"]], states.BIBLE_MERGED)

    if not outstanding and not verified:
        # Two ways to finish unverified, and they are not equally alarming. A last pass
        # that found blocking defects and fixed them is a chapter whose corrections are
        # unread; one that found only craft notes and applied them is a chapter in good
        # shape whose polish is unread. Both earn the sweep — a polish edit can quietly
        # assert a new fact, and several in this book have — but a log line that
        # describes the second as "repaired what it found" invites the reader to think
        # a clean chapter had defects at the end.
        last = trajectory[-1] if trajectory else 0
        what = (f"repaired the {last} defect(s) it found" if last
                else "found no defects and applied craft edits")
        log_fn(f"book {book_num} ch {n}: ACCEPTED ({trend}) — its last pass {what}, "
               f"and nothing has re-read that text; queued for one verification sweep")
    elif outstanding:
        journal.log_decision(
            chapter_rec["key"], "ACCEPTED WITH OUTSTANDING ISSUES",
            f"blocking issues per pass: {trend}. Shipped holding "
            f"{len(outstanding)} issue(s); the book's revision sweep will come back to "
            f"this chapter with the whole book in view.\n"
            + "\n".join(f"  - {i}" for i in outstanding))
        log_fn(f"book {book_num} ch {n}: ACCEPTED holding {len(outstanding)} "
               f"issue(s) ({trend}) — queued for the revision sweep")
    else:
        log_fn(f"book {book_num} ch {n}: ACCEPTED clean and verified ({trend})")


def _enqueue_illustrations(records, series_rec, book_num, n, chapter_outline,
                           log_fn=print):
    """Queue this chapter's pictures as soon as its prose is committed.

    Illustration used to wait until every chapter existed, which wasted the whole of
    the drafting window — hours in which the image workers had nothing to do — and then
    asked for a hundred pictures at once at the end.

    Drawing alongside the writing is better for more than throughput. Each accepted
    illustration becomes available as a reference for the ones after it, so the book's
    look converges instead of being a hundred independent guesses; and a bad picture
    shows up on chapter 2 rather than after the last chapter lands, which is the
    difference between fixing the recipe and re-rendering a book.

    Best-effort by construction: a failure here must never cost a chapter that is
    already written and committed."""
    try:
        from . import illustrating
        illustrating.enqueue_chapter(records, series_rec, book_num, n,
                                     chapter_outline, log_fn=log_fn)
    except Exception as exc:                                      # noqa: BLE001
        log_fn(f"book {book_num} ch {n}: could not queue illustrations ({exc}); "
               f"the book is unaffected and the sweep will queue them later")


def _close_interactions(sid, n, log_fn=print):
    """Mark this chapter's promised character collisions delivered.

    Without this the ledger only ever grows, so every later chapter's brief carries the
    whole book's worth of "still owed" — which reads as a list of things the book has
    failed to do rather than a list of things still coming, and buries the two or three
    that are actually this chapter's job."""
    path = paths.series_bible_path(sid)
    bible = storage.load_json(path, {})
    ledger = bible.get("interactions") or []
    closed = [entry for entry in ledger if n in (entry.get("chapters") or [])
              and entry.get("status") != "delivered"]
    if not closed:
        return
    for entry in closed:
        entry["status"] = "delivered"
    storage.save_json(bible, path)
    for entry in closed:
        log_fn(f"interaction delivered: {' + '.join(entry.get('who', []))}")


def _merge_bible(series_rec, book_num, n, prose, log_fn=print):
    """Merge this chapter's proposed bible updates. Returns a note if it could not.

    The merge is a gate on the *ledger*, not on the prose, and it must not be able to
    stop the book. A proposal that contradicts canon is refused — which is the whole
    point of the gatekeeper — and the chapter still ships, carrying a note saying its
    facts did not make it into the bible. The alternative, which this project used to
    do, is a chapter that cannot be committed at all and a book that stops."""
    try:
        bible_update.merge(series_rec, book_num, n, prose=prose, log_fn=log_fn)
        return ""
    except RevisionNeeded as needed:
        return f"BIBLE: proposed updates were refused by the merge gate: {needed.feedback}"
    except RuntimeError as exc:
        return f"BIBLE: could not merge this chapter's updates: {exc}"


# --- helpers -----------------------------------------------------------------

def _read(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _chapter_tail(sid, book_num, n):
    """The closing `config.DIGEST_PREV_TAIL_WORDS` words of an accepted chapter.

    Returns "" when that chapter is not on disk, so a first chapter or a series written
    by an older build degrades to the previous behaviour rather than raising."""
    words = _read(paths.chapter_path(sid, book_num, n)).split()
    if not words:
        return ""
    return " ".join(words[-config.DIGEST_PREV_TAIL_WORDS:])
