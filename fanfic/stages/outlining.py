"""Stage 4 — Outlining. A book's slot in the series plan -> a gated chapter list.

Each chapter carries a beat sheet, entry/exit state, its cast, the continuity facts
it depends on and establishes, the threads it sets up and pays off, and a timeline
index. The structure gate then runs before a word is drafted: monotonic timeline, no
payoff without a prior setup, no orphaned thread, contiguous numbering, and no
dependency on a fact established nowhere.

Seed facts — canon fact ids plus the series bible's fact ids — are passed to the
gate so a chapter may lean on established ground truth without an in-book setup.
"""

import json

from .. import config, paths
from . import correction_brief, metaplan
from ..gates import structure
from ..infra import storage
from ..memory import store
from ..memory import bible as bible_rules
from ..memory.bible import canon_fact_ids, new_canon
from ..models import prompts, text


# The chapter-count floor lives with the stage that decides the chapter count. Re-
# exported here because this module reads it too, and because two copies of a
# two-line rule is how a plan and its judge end up disagreeing about a number.
min_chapters = metaplan.min_chapters


def _seed_facts(series_rec):
    """Fact ids already true coming into the book: all canon, plus whatever the
    series bible has accumulated from earlier books."""
    ids = set()
    for universe in series_rec.get("universes", []):
        canon_doc = storage.load_json(paths.canon_path(universe), new_canon(universe))
        ids |= canon_fact_ids(canon_doc)
    bible = storage.load_json(paths.series_bible_path(series_rec["series_id"]), {})
    ids |= {f["id"] for f in bible.get("facts", []) if f.get("id")}
    return ids


def _meta_block(meta):
    """The meta plan's chapters, as the outliner's non-negotiable input."""
    lines = []
    for chapter in meta.get("chapters") or []:
        lines.append(f"  CHAPTER {chapter.get('number')}: {chapter.get('premise','')}")
        lines.append(f"      present: {', '.join(chapter.get('cast') or [])}")
        for entry in chapter.get("interactions") or []:
            lines.append(f"      scene [{entry.get('id')}]: "
                         f"{' + '.join(entry.get('who') or [])} — "
                         f"{entry.get('promise','')}")
    return "\n".join(lines) or "(no meta plan on file)"


def _progression_block(plan):
    """The capability changes the plan promised, for the outliner to place."""
    entries = plan.get("progressions") or []
    if not entries:
        return "  (none planned)"
    return "\n".join(
        f"  {entry.get('id')} — {entry.get('who')}: {entry.get('starts','')} "
        f"-> {entry.get('ends','')}"
        + (f" [changes their appearance from the chapter it lands in]"
           if entry.get("costume") else "")
        for entry in entries)


def propose_outline(series_rec, book_num, out_path, log_fn=None, feedback=""):
    """Model seam: produce the book outline JSON at out_path.

    The plan and the bible are quoted as JSON rather than named as paths: one
    outlining call needs all of both, so there is nothing to fetch selectively, and
    inlining costs one turn where fetching costs a turn per file plus a re-send of
    each on every turn that follows."""
    sid = series_rec["series_id"]
    memory = store.load(series_rec)
    this_book = next((b for b in memory.plan.get("books", [])
                      if b.get("num") == book_num), {})
    floor = min_chapters(memory.plan)
    meta = metaplan.load(sid, book_num)
    return text.produce(
        prompts.template("outline") + feedback,
        [f"Outlining book {book_num} of {memory.plan.get('book_count', 1)}: "
         f"{this_book.get('title', '')}",
         f"  THE META PLAN BELOW HAS ALREADY DECIDED THE CHAPTERS. There are "
         f"{len(meta.get('chapters') or [])} of them. Expand each one into beats and "
         f"continuity bookkeeping. Do not merge, split, add, drop or reorder a "
         f"chapter, and do not move a character scene into a chapter you would rather "
         f"have it in — that assignment is already made and everything downstream "
         f"reads it from there.",
         f"  (The floor, for reference, is {floor} chapters; the meta plan is already "
         f"above it. There is no upper limit and no word target — write the book the "
         f"story needs.)",
         f"  role in the series: {this_book.get('role', '')}",
         f"  premise: {this_book.get('premise', '')}",
         f"  entry state: {this_book.get('entry_state', '')}",
         f"  exit state it MUST reach: {this_book.get('exit_state', '')}",
         "",
         "=" * 70,
         "THE META PLAN — THE CHAPTERS, ALREADY DECIDED. Expand each one. Its `cast` "
         "must all appear in your `characters` list for that chapter, and the scenes "
         "listed under it are what that chapter is FOR: build the beats so each one "
         "gets a real scene with its own turn.",
         "=" * 70,
         _meta_block(meta),
         "",
         "PLANNED PROGRESSIONS — every one must be delivered by exactly one chapter, "
         "named in that chapter's `delivers_progression`. Put each where the character "
         "earns it, and write beats that DEMONSTRATE it rather than announcing it:",
         _progression_block(memory.plan),
         "",
         "THE FULL SERIES PLAN:",
         json.dumps(memory.plan, indent=1, ensure_ascii=False),
         "",
         "THE SERIES BIBLE AS IT STANDS (cast, voices, open threads, timeline):",
         json.dumps(memory.bible, indent=1, ensure_ascii=False)],
        out_path,
        role="outlining",
        artifact=f"the chapter outline for book {book_num} as strict JSON",
        log_fn=log_fn)


def _stamp_interactions(outline, meta_chapters):
    """Copy each chapter's promised collisions out of the meta plan onto the outline.

    Not merged with whatever the outliner proposed — overwritten. The meta plan owns
    this fact, so an outline that came back with its own idea of which scene belongs
    where is simply corrected before the gate ever sees it, and no gate attempt is
    spent on an argument the outliner was never entitled to have."""
    if not meta_chapters:
        return outline
    by_number = {c.get("number"): c for c in meta_chapters}
    for chapter in outline.get("chapters") or []:
        planned = by_number.get(chapter.get("number"))
        chapter["delivers"] = [entry.get("id") for entry
                               in ((planned or {}).get("interactions") or [])
                               if entry.get("id")]
    return outline


def _lock_costume_variants(sid, outline, progressions, log_fn=None):
    """Record, per character, the chapter from which an appearance change is in force.

    This is the first time the visual anchor is not constant across a book, and it is
    the highest-risk item in the rebuild after the repair anchors. A progression that
    changes how somebody looks invalidates their locked reference sheet for every
    chapter after it: draw the mantle in chapter 3 and it is a continuity error, omit
    it in chapter 40 and so is that.

    The chapter number is only knowable here, because the outliner is what places each
    escalation — so the variant is stamped now, keyed to the chapter that delivers it,
    and `illustration.costume_for_chapter` selects between them at render time.

    Only progressions that declare a `costume` produce one. Most do not: Hop Pop
    learning to stop deferring changes nothing an artist can draw."""
    by_id = {p.get("id"): p for p in progressions if p.get("id")}
    landing = {}
    for chapter in outline.get("chapters") or []:
        for pid in chapter.get("delivers_progression") or []:
            landing[pid] = chapter.get("number")

    path = paths.series_bible_path(sid)
    bible = storage.load_json(path, {})
    characters = bible.get("characters") or {}
    added = 0
    for pid, chapter_num in sorted(landing.items(), key=lambda kv: kv[1] or 0):
        entry = by_id.get(pid) or {}
        costume = (entry.get("costume") or "").strip()
        who = entry.get("who")
        if not costume or who not in characters:
            continue
        # A dated entry means "this is what they wear from chapter N", and
        # `illustration.costume_for_chapter` hands it to every later chapter whole. A
        # costume describing several changes cannot mean that at any chapter, so it is
        # refused rather than stamped: the character keeps their base wardrobe, which is
        # at least a single coherent outfit, and the plan gate now rejects the shape at
        # source so new runs never reach here. Loud, because the anchor it would have
        # written is wrong in a way no later gate looks for — the picture just quietly
        # shows the wrong clothes.
        if bible_rules.describes_multiple_transitions(costume):
            if log_fn:
                log_fn(f"{who}: NOT stamping the chapter-{chapter_num} costume from "
                       f"{pid} — it describes more than one change of look, so it "
                       f"cannot be what they wear from any single chapter. Keeping the "
                       f"base wardrobe; split {pid} into one progression per change.")
            continue
        variants = characters[who].setdefault("costumes", [])
        if any(isinstance(v, dict) and v.get("from_chapter") == chapter_num
               and v.get("text") == costume for v in variants):
            continue                                   # idempotent on a re-outline
        variants.append({"from_chapter": chapter_num, "text": costume,
                         "because": pid})
        added += 1
        if log_fn:
            log_fn(f"{who}: appearance changes from chapter {chapter_num} ({pid})")
    if added:
        storage.save_json(bible, path)


def run(series_rec, book_num, log_fn=None):
    """Produce and gate the outline, then derive the book bible.

    Returns {"chapter_count"}. Raises RuntimeError on a structure-gate failure — a
    deterministic park."""
    sid = series_rec["series_id"]
    proposal_path = paths.outline_proposal_path(sid, book_num)
    seed = _seed_facts(series_rec)
    memory = store.load(series_rec, book_num)
    floor = min_chapters(memory.plan)
    meta = metaplan.load(sid, book_num)
    meta_chapters = meta.get("chapters") or None
    ledger = memory.bible.get("interactions") or []
    # None, not [], when the plan has none — the gate treats an empty list as "there
    # are zero valid progression ids", so a plan written before progressions existed
    # would fail every `delivers_progression` the outline prompt still asks for, burn
    # all its attempts, and stall the book. Same normalisation `meta_chapters` gets.
    progressions = memory.plan.get("progressions") or None
    attempts = max(1, config.GATE_MAX_ATTEMPTS)
    feedback, errors, outline = "", [], None
    for attempt in range(1, attempts + 1):
        propose_outline(series_rec, book_num, proposal_path, log_fn=log_fn,
                        feedback=feedback)
        outline, why = storage.load_proposal(proposal_path)
        if not isinstance(outline, dict) or "chapters" not in outline:
            errors = [why or "the outline has no `chapters` list"]
        else:
            # The interaction assignment is STAMPED from the meta plan rather than read
            # off the outline. The outliner is not asked for it and cannot change it,
            # which is the only way to be certain two documents never both claim
            # authority over which chapter a scene happens in — the failure this
            # project's stories record three separate times, and which always presents
            # as a stubborn model rather than a missing input.
            _stamp_interactions(outline, meta_chapters)
            errors = list(structure.check(
                outline, seed_facts=seed, min_chapters=floor, interactions=ledger,
                meta_chapters=meta_chapters, progressions=progressions).errors)
        if not errors:
            break
        if log_fn:
            log_fn(f"outlining: structure gate rejected book {book_num} "
                   f"(attempt {attempt}/{attempts}): {errors[:4]}")
        feedback = correction_brief(errors, attempt, attempts)
    if errors:
        raise RuntimeError(
            f"outlining: structure gate failed after {attempts} attempts: "
            f"{errors[:5]}")

    _lock_costume_variants(sid, outline, progressions or [], log_fn=log_fn)
    storage.save_json(outline, paths.outline_path(sid, book_num))
    # The book bible is a derived working slice: chapters and their entry/exit
    # states. Reconstructable, so it is written for convenience, not as truth.
    storage.save_json({
        "series_id": sid,
        "book_num": book_num,
        "chapters": [{"number": c["number"],
                      "entry_state": c.get("entry_state", ""),
                      "exit_state": c.get("exit_state", ""),
                      "characters": c.get("characters", [])}
                     for c in outline["chapters"]],
    }, paths.book_bible_path(sid, book_num))
    return {"chapter_count": len(outline["chapters"])}
