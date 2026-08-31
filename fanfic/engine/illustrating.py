"""Driving the image queue for a book.

Pictures never block *writing* — the queue is drained alongside drafting and a slow
render costs nobody a chapter. What they do block is the epub, and deliberately: a
book is illustrated when every slot holds a picture, and there is no other way for it
to be illustrated. Three scheduling rules hold that, and they live here rather than in
the illustration stage because they are scheduling decisions:

  * PACED — at most config.IMAGES_PER_CYCLE renders per cycle, then return. The
    engine stays responsive and paces against rate limits instead of hammering.
  * DEFERRED, not failed — a QuotaExceeded is deliberately not caught here. It
    bubbles to the cycle, which backs off and leaves the book in ILLUSTRATING.
  * PARKED, not abandoned — a slot that will not render waits, and comes back a rung
    plainer. Nothing here writes a picture off, and the spend ceiling is a wait too:
    hitting it holds the book in ILLUSTRATING until somebody raises it, which is the
    honest behaviour for a ceiling once a hole in the book is not on the menu.

Text-only builds short-circuit the whole stage. That is an explicit, logged config
choice and is deliberately distinguishable in the audit log from an image *failure*.
"""

from .. import config, jobspec, paths, states
from ..gates import segments
from ..infra import budget, journal, storage
from ..models import images
from ..stages import illustration


def _style_for(series_rec):
    """This job's art direction, from its own prompt, falling back to
    config.IMAGE_STYLE. Read here rather than in the illustration stage because the
    engine is what holds the series record — and read per job rather than from global
    config because otherwise a Star Wars novelization is illustrated as cel-shaded
    anime for no better reason than that being the last fic's style."""
    return jobspec.art_direction(series_rec.get("prompt_text", ""))


def images_per_chapter(series_rec, book_num, log_fn=None):
    """The per-chapter image ceiling, DERIVED from the remaining picture budget.

    This used to be `config.IMAGES_PER_CHAPTER`, a constant, and that was fine while
    the chapter count was fixed at 37: the two multiplied to a predictable total.
    Freeing the chapter count is what forces this change — chapter count used to
    multiply the picture count and now has to divide it instead, because the render
    ceiling is the fixed quantity and the number of chapters is not.

    Three things go into it, and all three are measured rather than assumed:

      * how many renders the ceiling still allows;
      * how many of those renders actually produce a kept picture, from this series'
        own observed reject rate — a rejected render still spends one, so a cap
        computed on keepers alone overruns by exactly that rate;
      * what still has to be reserved for reference sheets and the cover, which are the
        consistency anchors and must not be crowded out by scene art.

    Spread over the chapters whose pictures are not all chosen yet, so it adapts as the
    run goes rather than being decided once on the first chapter's information. "Not
    all chosen" rather than "not queued at all", because a chapter directed under an
    older, lower ceiling is still owed pictures: counting it as finished divides the
    budget by too few chapters and hands every later chapter a cap the money cannot
    actually cover once the short ones are topped up."""
    sid = series_rec["series_id"]
    ceiling = max(1, config.IMAGES_PER_CHAPTER)
    renders_left = budget.image_budget_remaining(sid)
    if renders_left == float("inf"):
        return ceiling

    outline = storage.load_json(paths.outline_path(sid, book_num), {"chapters": []})
    chapters = outline.get("chapters") or []
    counts = illustration.queued_counts(sid, book_num)
    remaining_chapters = max(1, len([c for c in chapters
                                     if counts.get(c.get("number"), 0) < ceiling]))

    bible = storage.load_json(paths.series_bible_path(sid), {})
    reserve = sum(1 for name in (bible.get("characters") or {})
                  if not paths.sheet_path(sid, book_num, name).exists())
    if not paths.cover_path(sid, book_num).exists():
        reserve += 1

    keep = illustration.keep_rate(sid)
    usable = max(0.0, (renders_left - reserve)) * keep
    derived = int(usable // remaining_chapters)
    cap = max(1, min(ceiling, derived))
    if log_fn:
        log_fn(f"book {book_num}: picture budget allows {renders_left} more render(s); "
               f"{reserve} reserved for sheets and the cover, {keep:.0%} of renders "
               f"kept so far, {remaining_chapters} chapter(s) left -> cap {cap} "
               f"image(s) per chapter")
    return cap


def _progression_brief(series_rec, chapter):
    """What a chapter's escalation obliges its pictures to show, if it has one.

    A progression the prose merely states is a blocking editorial defect, and one the
    book never shows is worse. The chapter that delivers it owes a picture of it.

    The honest limitation: the harness cannot know WHICH scene segment the escalation
    lands in without another judgement call over the prose, so it does two cheaper
    things instead — it tells every segment's art director what must be visible if the
    moment belongs to that segment, and it buys the chapter one extra picture so a
    tight budget cannot squeeze the mandatory one out."""
    plan = storage.load_json(paths.plan_path(series_rec["series_id"]), {})
    by_id = {p.get("id"): p for p in (plan.get("progressions") or [])}
    wanted = [by_id[pid] for pid in chapter.get("delivers_progression") or []
              if pid in by_id]
    if not wanted:
        return ""
    return "; ".join(f"{p.get('who')} reaching: {p.get('ends')}" for p in wanted)


def enqueue_chapter(records, series_rec, book_num, chapter_num, chapter,
                    log_fn=print):
    """Choose and queue one chapter's illustrations, from its own accepted prose.

    Called at chapter acceptance so the picture work runs alongside the writing, and
    again by `top_up` for a chapter whose pictures were chosen under a lower ceiling.

    **Idempotent per SEGMENT, not per chapter**, and the difference is the whole
    reason this signature exists. It used to return early if the chapter had any queue
    entry at all, which is the right guard against paying for art direction twice and
    the wrong one for a chapter that is genuinely short: the live book's first eight
    chapters were directed while `IMAGES_PER_CHAPTER` was 2, the ceiling was raised to
    6, and eight chapters of five and six settings stayed on two pictures because the
    only question anybody asked was "is this chapter in the queue".

    The segments already queued are subtracted, so a top-up pays only for the moments
    nobody has chosen yet."""
    if not config.IMAGES_ENABLED:
        return 0
    sid = series_rec["series_id"]
    prose_path = paths.chapter_path(sid, book_num, chapter_num)
    prose = (prose_path.read_text(encoding="utf-8") if prose_path.exists()
             else chapter.get("beats", ""))
    style = _style_for(series_rec)
    cap = images_per_chapter(series_rec, book_num, log_fn=log_fn)
    owed = _progression_brief(series_rec, chapter)
    if owed:
        cap = min(max(1, config.IMAGES_PER_CHAPTER), cap + 1)
    already = illustration.queued_segments(sid, book_num, chapter_num)
    scenes = illustration.scenes_for_chapter(
        series_rec, book_num, chapter_num, prose, cap, log_fn=log_fn,
        already=already,
        must_show=(f"This chapter delivers {owed}. If the moment it actually happens "
                   f"is in the text below, THAT is the picture — draw the instant it "
                   f"lands, not a reaction to it afterwards." if owed else ""))
    if not scenes:
        return 0
    illustration.enqueue_chapter(series_rec, book_num, chapter_num, scenes,
                                 style=style)
    log_fn(f"book {book_num} ch {chapter_num}: queued "
           f"{len(scenes)} illustration(s)"
           + (f" (topping up {len(already)} already chosen)" if already else "")
           + (f"; owes a picture of {owed}" if owed else ""))
    return len(scenes)


def chapters_short_of_cap(series_rec, book_num):
    """Accepted chapters holding fewer pictures than their own scene count allows.

    Measured against the chapter's real segment count, not against the ceiling, so a
    three-scene chapter with three pictures is finished and a six-scene chapter with
    two is not. Reads each accepted chapter's prose, which is why the caller does this
    once a cycle rather than per render.

    THE CAP HERE MUST BE THE ONE THE ENQUEUER WILL APPLY, and for a while it was not.
    This compared against the static `IMAGES_PER_CHAPTER` ceiling while
    `enqueue_chapter` applies the budget-derived cap, so a six-segment chapter holding
    five pictures under a derived cap of five was reported short, handed to the
    enqueuer, and refused — every cycle, forever. It cost no model calls, which is why
    it was easy to miss, but it printed three confident lines about work it could never
    do every thirty seconds, and a log that says that is a log nobody reads.

    Using the derived cap keeps the behaviour that matters: when the keep rate improves
    and the cap rises, the shortfall reappears and those chapters are topped up — which
    is exactly what `ARaisedCeilingReachesChaptersAlreadyWritten` pins."""
    sid = series_rec["series_id"]
    ceiling = max(1, min(config.IMAGES_PER_CHAPTER,
                         images_per_chapter(series_rec, book_num)))
    counts = illustration.queued_counts(sid, book_num)
    short = []
    for chapter_num, have in sorted(counts.items()):
        if have >= ceiling:
            continue
        prose_path = paths.chapter_path(sid, book_num, chapter_num)
        if not prose_path.exists():
            continue
        parts = segments.split(prose_path.read_text(encoding="utf-8"))
        if have < min(ceiling, max(1, len(parts))):
            short.append(chapter_num)
    return short


def top_up(records, series_rec, book_num, log_fn=print):
    """Direct the earliest chapter that is short of pictures. Returns True if it did.

    ONE chapter per call, for the same reason everything else here is one per cycle:
    it paces the art-direction calls and keeps a worker responsive.

    Ownership is deliberately narrow — this is the ONLY path that adds entries to a
    chapter that already has some, and `enqueue_book` is the only path that adds them
    to a chapter that has none. The queue is an append-only file with no lock, so two
    processes appending to the same chapter would duplicate slots and pay for them
    twice; splitting the two cases by who has already written to the chapter is what
    makes the lock unnecessary."""
    if not config.IMAGES_ENABLED:
        return False
    outline = storage.load_json(paths.outline_path(series_rec["series_id"], book_num),
                                {"chapters": []})
    by_number = {c.get("number"): c for c in outline.get("chapters") or []}
    for chapter_num in chapters_short_of_cap(series_rec, book_num):
        chapter = by_number.get(chapter_num)
        if chapter is None:
            continue
        log_fn(f"book {book_num} ch {chapter_num}: short of pictures for its own "
               f"scene count; directing the segments nobody has chosen yet")
        return bool(enqueue_chapter(records, series_rec, book_num, chapter_num,
                                    chapter, log_fn=log_fn))
    return False


def enqueue_book(records, series_rec, book_num, log_fn=print):
    """Choose and enqueue scene illustrations for every accepted chapter — grounded in
    the chapter's own accepted prose, not just its outline beats — then write the
    reviewable prompt pack.

    Idempotent per chapter, and it has to be. This used to run once, on the transition
    into ILLUSTRATING, which left a window: a crash between the status write and this
    call produced a book in ILLUSTRATING with an empty queue, so the drain found
    nothing pending, concluded the images were complete, and shipped an `.epub` with a
    cover and no illustrations — silently, with every gate green. Now it runs on every
    ILLUSTRATING cycle and skips the chapters already queued, so the window closes
    without paying for the art direction twice.

    Chapters with NO entries only. A chapter that has some but too few is `top_up`'s,
    and the split is what keeps two unsynchronised processes off the same chapter of an
    append-only queue file."""
    if not config.IMAGES_ENABLED:
        return
    sid = series_rec["series_id"]
    outline = storage.load_json(paths.outline_path(sid, book_num), {"chapters": []})
    already = illustration.queued_chapters(sid, book_num)

    queued = 0
    for chapter in outline["chapters"]:
        n = chapter["number"]
        if n in already:
            continue
        enqueue_chapter(records, series_rec, book_num, n, chapter, log_fn=log_fn)
        queued += 1

    # The pack is written even when nothing new was queued. It is a pure re-render of
    # the queue rather than a record of this call, and chapters now queue themselves at
    # acceptance — so "nothing new here" is the normal case, and returning early meant
    # the reviewable artifact was never written at all.
    pack = illustration.write_prompt_pack(series_rec, book_num)
    log_fn(f"book {book_num}: {queued} chapter(s) queued this pass; "
           f"prompt pack -> {pack.name}")
    log_fn(f"book {book_num}: art style -> "
           f"{illustration.style_block(_style_for(series_rec))[:80]}…")


def advance(records, series_rec, book_rec, log_fn=print):
    """Lock reference sheets, render the pending queue and the cover, and advance to
    ILLUSTRATED once every slot for this book holds a picture."""
    sid = series_rec["series_id"]
    book_num = book_rec["book_num"]
    if config.IMAGES_ENABLED:
        # Cheap when the queue is already written (one file read), and the only thing
        # standing between a crash at the wrong instant and a book with no pictures.
        enqueue_book(records, series_rec, book_num, log_fn=log_fn)
        # And fill in any chapter directed under an older, lower ceiling before
        # deciding this book's pictures are chosen.
        top_up(records, series_rec, book_num, log_fn=log_fn)

    if not config.IMAGES_ENABLED:
        journal.log_decision(
            book_rec["key"], "IMAGES_DISABLED",
            "FANFIC_IMAGES_ENABLED=0: building text-only, no images.")
        log_fn(f"book {book_num}: images DISABLED by config -> building text-only")
        journal.set_status(records, book_rec, states.ILLUSTRATED)
        return

    # THE SESSION IS CHECKED BEFORE ANY RENDER IS ATTEMPTED, and this is the one gate
    # that replaced the old "is the API key on disk" check.
    #
    # A signed-out browser profile is not a failure and must never be treated as one:
    # every slot is still owed, nothing is skipped, and the fix is a human running one
    # script. So the book HOLDS in ILLUSTRATING with its queue intact and says exactly
    # what to do, rather than burning a render attempt per slot per cycle discovering
    # the same thing — which is what an unattended fleet does with a problem it is not
    # told about up front.
    unready = images.unconfigured_reason()
    if unready:
        journal.log_decision(book_rec["key"], "IMAGES_WAITING", unready)
        log_fn(f"book {book_num}: pictures on hold — {unready} Nothing is skipped and "
               f"nothing is lost; the queue resumes by itself once the session is back.")
        return

    bible = storage.load_json(paths.series_bible_path(sid), {})
    outline = storage.load_json(paths.outline_path(sid, book_num), {"chapters": []})
    cast = sorted({name for chapter in outline["chapters"]
                   for name in chapter.get("characters", [])
                   if name in bible.get("characters", {})})

    slots = max(1, config.IMAGES_PER_CYCLE)
    used = 0
    style = _style_for(series_rec)

    # 1. Reference sheets first: a scene render is only as consistent as the sheets
    #    it can reference.
    for name in cast:
        sheet = paths.sheet_path(sid, book_num, name)
        if sheet.exists():
            bible["characters"][name]["ref_sheet_locked"] = True
            continue
        if not illustration.due(sheet):              # parked; waiting out its backoff
            continue
        if used >= slots:
            storage.save_json(bible, paths.series_bible_path(sid))
            return
        if _picture_budget_spent(sid, "character sheet", log_fn):
            continue
        if illustration.generate_reference_sheet(
                series_rec, book_num, bible["characters"][name], log_fn=log_fn,
                style=style):
            bible["characters"][name]["ref_sheet_locked"] = True
        used += 1
    storage.save_json(bible, paths.series_bible_path(sid))

    # 2. Cover (decorative).
    cover = paths.cover_path(sid, book_num)
    if (illustration.due(cover) and used < slots
            and not _picture_budget_spent(sid, "cover", log_fn)):
        illustration.render_cover(series_rec, book_num,
                                  book_rec.get("title") or sid, log_fn=log_fn,
                                  style=style)
        used += 1

    # 3. Scene queue, bounded for this cycle. `due_scene_entries` rather than every
    #    pending one: a parked slot is still owed and still counted below, but handing
    #    it to a worker before its backoff elapses would turn the backoff into a spin.
    for entry in illustration.due_scene_entries():
        if entry["series_id"] != sid or entry["book_num"] != book_num:
            continue
        if used >= slots:
            return                  # more remain; next cycle picks up where we left
        # A deferred scene (no locked sheet for its cast yet) must not stop the ones
        # behind it — `render_scene` returns None for that, and continuing is what
        # keeps one unrenderable entry from halting the whole book's art.
        if _picture_budget_spent(sid, "scene", log_fn):
            break
        illustration.render_scene(entry, log_fn=log_fn)
        used += 1

    remaining = [e for e in illustration.pending_scene_entries()
                 if e["series_id"] == sid and e["book_num"] == book_num]
    if not remaining:
        journal.set_status(records, book_rec, states.ILLUSTRATED)
        log_fn(f"book {book_num}: images complete -> ILLUSTRATED")


def _picture_budget_spent(series_id, what, log_fn):
    """Whether this series has spent its picture budget. Declines the work; it does
    NOT resolve the slot.

    The old behaviour was to leave a skip marker so the book could still reach
    ILLUSTRATED with a hole in it. That was coherent while a missing picture was an
    acceptable outcome and it is not one any more, so a spent ceiling now does what
    every other ceiling in this fleet does: it waits. The book holds in ILLUSTRATING,
    the slots keep their place in the queue, and raising `FANFIC_IMAGE_RENDER_BUDGET`
    resumes the run by itself with no re-drop and nothing lost.

    That makes the ceiling a genuine runaway stop rather than a quality setting — it
    can cost time now, but it can no longer cost a picture."""
    if budget.image_budget_remaining(series_id) > 0:
        return False
    log_fn(f"{what} waiting: this series has spent its render ceiling of "
           f"{config.IMAGE_RENDER_BUDGET} pictures. Nothing is skipped and nothing is "
           f"lost — raise FANFIC_IMAGE_RENDER_BUDGET and restart the fleet, and the "
           f"remaining pictures draw themselves.")
    return True
