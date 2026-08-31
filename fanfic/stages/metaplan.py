"""Stage 3b — the meta plan. The chapter breakdown, and who is in a room with whom.

    plan -> META PLAN -> outline -> draft

It sits between planning and outlining and it owns one thing completely: **which
chapter each character scene happens in.** For every chapter it produces a one-line
premise, the cast present, and the four or five interactions that fire there.

Why it exists is a measurement rather than a theory. The interaction ledger used to
live in the series plan and be sized against the cast — `min(cast-1, max(8, cast//2))`,
which for a cast of 26 is 13. The model produced 23 entries across 37 chapters, so
**fourteen chapters owed nothing to anybody**, and chapter 1 was one of them: six
people at a dinner table, one of whom talked. The floor was sized to the cast when the
thing it has to cover is the book.

Three numbers line up here and the alignment is the design:

    one scene segment = one setting = one interaction = one illustration

A chapter is four or five segments, so it gets four or five interactions, and each of
them has a place to happen and a picture of it. At ~45 chapters that is ~180 entries
against 23 last time.

**Built in chunks, ten chapters at a time.** One call will not produce 180 entries —
the same measurement that governs the length floor says a model asked for a large
artifact returns a third of it and declares victory. So each call is shown everything
already committed *and* where the coverage currently falls short, and each accepted
chunk is written to disk before the next is asked for. Propose, validate, apply,
persist, next chunk: the same four beats as every other stage.

**The outliner does not get a vote.** It inherits this assignment and expands it into
beats. If both documents could place a scene, two documents would own the same fact —
the failure this project's stories record three separate times, which always looks like
a stubborn model rather than a missing input.
"""

import json
from collections import Counter

from .. import config, paths
from ..gates import interactions as ledger_gate
from ..infra import storage
from ..memory import store
from ..models import prompts, text
from . import anchoring, correction_brief


def min_chapters(plan):
    """The FLOOR on this book's chapter count.

    Not a target. The count used to be specified in the plan, gated to ±15%, and used
    to derive the per-chapter word target — which is the chain that manufactured the
    book's filler, because a specified size for a chapter is an instruction to pad one
    that has finished its story. The meta plan picks the count now; this only stops a
    novel from being delivered as a novella.

    It lives here rather than in `outlining` because this is the stage that makes the
    decision, and `outlining` imports it from here so there is exactly one copy."""
    value = plan.get("per_book_chapters")
    return int(value) if isinstance(value, int) and value > 0 else config.MIN_CHAPTERS


def load(series_id, book_num):
    """The committed meta plan, or an empty shell if it has not been built yet."""
    return storage.load_json(paths.metaplan_path(series_id, book_num),
                             {"book_num": book_num, "chapter_count": 0,
                              "chapters": []})


def cast_origins(plan):
    """{character name: the world they come from}, out of the series plan.

    `origin` is what makes the coverage gate arithmetic rather than judgement: without
    it there is no way to count whether an interaction crosses universes, and counting
    that is the whole point. A character with no origin is treated as their own world
    rather than silently folded into someone else's."""
    out = {}
    for spec in plan.get("characters") or []:
        name = spec.get("name")
        if name:
            out[name] = (spec.get("origin") or "").strip() or name
    return out


def ledger(meta):
    """Every interaction in the meta plan, flattened, each carrying its chapter."""
    out = []
    for chapter in meta.get("chapters") or []:
        for entry in chapter.get("interactions") or []:
            out.append({"id": entry.get("id", ""),
                        "who": list(dict.fromkeys(entry.get("who") or [])),
                        "promise": entry.get("promise", ""),
                        "register": entry.get("register", ""),
                        "chapter": chapter.get("number")})
    return out


def _renumber(meta):
    """Give every interaction a unique id, assigned by the harness.

    The model proposes ids per chunk and has no way to know what the previous chunks
    used, so two chunks will eventually both call something `x.7`. Colliding ids would
    quietly merge two different scenes into one ledger entry, and the outline would
    then deliver one of them twice and the other never. Deterministic renumbering makes
    that impossible instead of unlikely."""
    n = 0
    for chapter in meta.get("chapters") or []:
        for entry in chapter.get("interactions") or []:
            n += 1
            entry["id"] = f"x.{n}"
    return meta


def _validate_chunk(chunk, first_number, plan_names, want_count, used_counts=None):
    """Local, per-chunk checks. Returns a list of errors.

    Mostly the things a chunk can be judged on alone: coverage across the whole book is
    a property of the finished ledger and is checked once, at the end, by
    `gates.interactions`, with each chunk *steered* toward it by a running shortfall
    brief.

    The exception is `used_counts`, and it earns its place by being the one whole-book
    rule that a late repair cannot fix. Under-use and thin pairings are closable by
    writing more scenes; a grouping over its budget in chapter 4 is not something
    re-planning chapter 40 will remove. Caught here, in the chunk that introduces it, it
    costs one re-proposal — caught only at the end it costs a repair round that cannot
    succeed.

    It is a BUDGET rather than a ban, and the difference is a book. Forbidding any
    repeat outright is satisfiable for a 52-character crossover and not for an
    18-character novelization: the real Star Wars book planned 30 chapters with every
    grouping unique and then failed three straight attempts on chapters 31-40, every
    failure being the protagonist plus the same small pool of Jedi Masters — the scenes
    the source is actually made of. See `config.META_SUBSET_MAX_REPEATS`."""
    errors = []
    used_counts = Counter(used_counts or {})
    seen_here = Counter()
    chapters = chunk.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        return ["the chunk has no `chapters` list"]

    expected = list(range(first_number, first_number + len(chapters)))
    got = [c.get("number") for c in chapters]
    if got != expected:
        errors.append(f"chapter numbers must continue the book: expected "
                      f"{expected[0]}..{expected[-1]}, got {got}")
    if first_number + len(chapters) - 1 > want_count:
        errors.append(f"this chunk runs past the book's {want_count} chapters")

    lo, hi = config.META_INTERACTIONS_MIN, config.META_INTERACTIONS_MAX
    for chapter in chapters:
        n = chapter.get("number")
        if not (chapter.get("premise") or "").strip():
            errors.append(f"chapter {n}: no premise")
        cast = list(dict.fromkeys(chapter.get("cast") or []))
        if not cast:
            errors.append(f"chapter {n}: no cast")
        for name in cast:
            if name not in plan_names:
                errors.append(f"chapter {n}: {name!r} is not in the plan's cast")
        entries = chapter.get("interactions") or []
        if not lo <= len(entries) <= hi:
            errors.append(
                f"chapter {n}: {len(entries)} interaction(s); every chapter needs "
                f"{lo}-{hi}. One per scene segment — a chapter is {lo}-{hi} segments, "
                f"each is a setting, each gets one collision and one picture.")
        for i, entry in enumerate(entries, 1):
            who = list(dict.fromkeys(entry.get("who") or []))
            if len(who) < 2:
                errors.append(f"chapter {n} interaction {i}: needs at least two people")
            for name in who:
                if name not in plan_names:
                    errors.append(f"chapter {n} interaction {i}: {name!r} is not in "
                                  f"the plan's cast")
                elif name not in cast:
                    errors.append(f"chapter {n} interaction {i}: {name!r} is in the "
                                  f"interaction but not in the chapter's cast")
            if not (entry.get("promise") or "").strip():
                errors.append(f"chapter {n} interaction {i}: no `promise` — say what "
                              f"this specific scene does")
            if ledger_gate.register_of(entry) == ledger_gate.UNSET:
                errors.append(
                    f"chapter {n} interaction {i}: `register` must be one of "
                    f"{', '.join(ledger_gate.REGISTERS)}, got "
                    f"{entry.get('register')!r}")
            group = frozenset(who)
            cap = max(1, config.META_SUBSET_MAX_REPEATS)
            if len(who) >= 2 and used_counts[group] + seen_here[group] >= cap:
                errors.append(
                    f"chapter {n} interaction {i}: {' + '.join(sorted(who))} have "
                    f"already shared {cap} scene(s) in this book, which is all this "
                    f"grouping gets — vary it by at least one person. A core party is "
                    f"allowed to recur; it is not allowed to be most of the book.")
            seen_here[group] += 1
    return errors


def _committed_block(meta):
    """The chapters already committed, compactly, so a chunk can see the whole book so
    far without being handed it twice over."""
    chapters = meta.get("chapters") or []
    if not chapters:
        return "(nothing committed yet — this is the opening chunk)"
    lines = []
    for chapter in chapters:
        lines.append(f"  ch {chapter.get('number')}: {chapter.get('premise', '')}")
        for entry in chapter.get("interactions") or []:
            lines.append(f"      - {' + '.join(entry.get('who') or [])}: "
                         f"{entry.get('promise', '')}")
    return "\n".join(lines)


def propose_chunk(series_rec, book_num, meta, first_number, last_number, out_path,
                  log_fn=None, feedback=""):
    """Model seam: produce one chunk of the meta plan at out_path."""
    sid = series_rec["series_id"]
    memory = store.load(series_rec, book_num)
    this_book = next((b for b in memory.plan.get("books", [])
                      if b.get("num") == book_num), {})
    origins = cast_origins(memory.plan)
    opening = not (meta.get("chapters") or [])

    facts = [
        f"Meta-planning book {book_num}: {this_book.get('title', '')}",
        f"  premise: {this_book.get('premise', '')}",
        f"  it must end at: {this_book.get('exit_state', '')}",
        "",
        f"THE BOOK IS {meta.get('chapter_count') or '(you decide — see below)'} "
        f"CHAPTERS. Produce chapters {first_number} to {last_number} in this call, and "
        f"only those.",
    ]
    if opening:
        facts += [
            "",
            f"This is the first chunk, so you also decide the chapter count. Pick the "
            f"number this story needs, at least {min_chapters(memory.plan)}. There is no "
            f"upper limit and no word target — a chapter is however long its scenes "
            f"are. Put it in `chapter_count`, and do not change it afterwards.",
        ]
    facts += [
        "",
        "THE CAST, AND WHICH WORLD EACH COMES FROM (use these names exactly):",
        "\n".join(f"  {name} — {origin}" for name, origin in sorted(origins.items())),
        "",
        anchoring.block(sid),
        "",
        "THE SERIES PLAN:",
        json.dumps(memory.plan, indent=1, ensure_ascii=False),
        "",
        "=" * 70,
        "THE BOOK SO FAR — every chapter already committed. Do not repeat, revise or "
        "renumber any of it; continue from the end of it.",
        "=" * 70,
        _committed_block(meta),
        "",
        "=" * 70,
        "WHERE THE COVERAGE STANDS. These are the gates the finished ledger is checked "
        "against, so steer toward them now rather than leaving them to the last "
        "chunk — a shortfall discovered at the end costs the whole ledger.",
        "=" * 70,
        ledger_gate.shortfall_brief(
            ledger(meta), origins, series_rec.get("universes", []),
            config.PLAN_MIN_APPEARANCES, config.META_CROSS_UNIVERSE_SHARE,
            config.META_MIN_PAIRING_SHARE,
            physical_share=config.META_MIN_PHYSICAL_SHARE,
            front_physical_share=config.META_FRONT_PHYSICAL_SHARE,
            back_physical_share=config.META_BACK_PHYSICAL_SHARE),
    ]
    return text.produce_json(
        prompts.template("meta_plan") + feedback, facts, out_path,
        role="planning",
        artifact="this chunk of the meta plan as strict JSON",
        shape='{"chapter_count": int, "chapters": [{"number": int, '
              '"premise": str, "cast": [str, ...], "interactions": '
              '[{"who": [str, ...], "promise": str, "register": '
              '"physical"|"conflict"|"investigation"|"comic"|"tender"}, ...]}, ...]}',
        log_fn=log_fn)


def run(series_rec, book_num, log_fn=None):
    """Build, gate, and persist the meta plan. Returns it.

    Resumable by construction: each accepted chunk is written to disk before the next
    is asked for, so an interrupted run picks up at the next chunk rather than paying
    for a 180-entry ledger twice."""
    sid = series_rec["series_id"]
    memory = store.load(series_rec, book_num)
    origins = cast_origins(memory.plan)
    plan_names = set(origins)
    if not plan_names:
        raise RuntimeError("meta plan: the series plan has no cast to work with")

    meta = load(sid, book_num)
    floor = min_chapters(memory.plan)
    attempts = max(1, config.GATE_MAX_ATTEMPTS)
    step = max(1, config.META_CHUNK_CHAPTERS)

    for round_num in range(1, attempts + 1):
        meta = _build_out(series_rec, book_num, meta, floor, plan_names, origins,
                          step, attempts, log_fn=log_fn)
        report = ledger_gate.check(
            ledger(meta), origins, series_rec.get("universes", []),
            min_appearances=config.PLAN_MIN_APPEARANCES,
            cross_share=config.META_CROSS_UNIVERSE_SHARE,
            pairing_share=config.META_MIN_PAIRING_SHARE,
            physical_share=config.META_MIN_PHYSICAL_SHARE,
            front_physical_share=config.META_FRONT_PHYSICAL_SHARE,
            back_physical_share=config.META_BACK_PHYSICAL_SHARE,
            register_ceiling=config.META_REGISTER_CEILING)
        if report.passed:
            break
        if round_num == attempts:
            raise RuntimeError(
                f"meta plan: coverage gate failed after {attempts} repair rounds: "
                f"{report.errors[:4]}")
        if log_fn:
            log_fn(f"meta plan: coverage gate rejected the ledger "
                   f"(round {round_num}/{attempts}): {report.errors[:3]}")
        # Widen the window each round. A duplicate subset or a size shortfall between
        # chapters 3 and 17 is untouchable by a repair that only ever rewrites the last
        # ten chapters, so every round would fail identically and the book would stall
        # forever on a state nothing could reach — "never give up" turned into a loop
        # that cannot win, which is the shape of the phantom-chapter defect this
        # project has already paid for once.
        meta = _discard_tail(meta, step * round_num, log_fn=log_fn)

    storage.save_json(meta, paths.metaplan_path(sid, book_num))
    _seed_bible(sid, meta, book_num, log_fn=log_fn)
    if log_fn:
        log_fn(f"{sid}: meta plan for book {book_num} — {len(meta['chapters'])} "
               f"chapters, {len(ledger(meta))} interactions, "
               f"{report.stats['cross_share']:.0%} cross-universe")
    return meta


def _discard_tail(meta, count, log_fn=None):
    """Throw away the last `count` chapters so they can be re-planned.

    Never all of them: chapter 1 is where the book's opening lives and rebuilding from
    nothing would spend the whole ledger's worth of calls again."""
    keep = max(1, len(meta.get("chapters") or []) - count)
    if log_fn:
        log_fn(f"meta plan: re-planning chapters {keep + 1}-{len(meta['chapters'])} "
               f"to close the coverage shortfall")
    return dict(meta, chapters=meta["chapters"][:keep])


def _build_out(series_rec, book_num, meta, floor, plan_names, origins, step,
               attempts, log_fn=None):
    """Fill the meta plan up to its own chapter count, a chunk at a time.

    Re-entered after a coverage repair, which is what guarantees the book ends up with
    the number of chapters it says it has. The repair used to append one chunk and hand
    straight back to the gate, so a re-proposal that returned six chapters where ten
    were discarded left `chapter_count` at 45 against 41 actual chapters — journalled as
    the book's chapter count and four chapters silently missing."""
    sid = series_rec["series_id"]

    while True:
        done = len(meta.get("chapters") or [])
        want = int(meta.get("chapter_count") or 0)
        if want and done >= want:
            break
        first = done + 1
        last = (min(done + step, want) if want else done + step)
        chunk_index = (done // step) + 1

        feedback, errors, chunk = "", [], None
        for attempt in range(1, attempts + 1):
            out_path = paths.metaplan_proposal_path(sid, book_num, chunk_index)
            propose_chunk(series_rec, book_num, meta, first, last, out_path,
                          log_fn=log_fn, feedback=feedback)
            chunk, why = storage.load_proposal(out_path)
            if not isinstance(chunk, dict):
                errors = [why or "the chunk is not a JSON object"]
            else:
                if not want:
                    proposed = int(chunk.get("chapter_count") or 0)
                    if proposed < floor:
                        errors = [f"chapter_count is {proposed}; the floor is "
                                  f"{floor}"]
                        feedback = correction_brief(errors, attempt, attempts)
                        continue
                    want = proposed
                    last = min(done + step, want)
                errors = _validate_chunk(
                    chunk, first, plan_names, want,
                    used_counts=Counter(frozenset(e["who"]) for e in ledger(meta)))
            if not errors:
                break
            if log_fn:
                log_fn(f"meta plan: chunk {first}-{last} rejected "
                       f"(attempt {attempt}/{attempts}): {errors[:3]}")
            feedback = correction_brief(errors, attempt, attempts)

        if errors:
            raise RuntimeError(
                f"meta plan: chunk starting at chapter {first} invalid after "
                f"{attempts} attempts: {errors[:4]}")

        meta["book_num"] = book_num
        meta["chapter_count"] = want
        meta["chapters"] = (meta.get("chapters") or []) + chunk["chapters"]
        _renumber(meta)
        storage.save_json(meta, paths.metaplan_path(sid, book_num))
        if log_fn:
            log_fn(f"meta plan: {len(meta['chapters'])}/{want} chapters, "
                   f"{len(ledger(meta))} interaction(s) so far")

    return meta


def _seed_bible(series_id, meta, book_num, log_fn=None):
    """Merge this book's ledger into the series bible, chapter assignments and all.

    The bible is what the writer's brief and the editor's ground truth read, so this is
    the point at which "who is in a room with whom" becomes visible to everything
    downstream. The chapter is filled in here rather than by the outliner, because the
    meta plan is the document that owns it.

    **Merged rather than assigned**, and the distinction only shows up on book 2. The
    bible spans a series and a meta plan covers one book, so a whole-list assignment
    would erase every collision book 1 promised and delivered — leaving the editor
    judging book 2 against a ledger that says none of book 1's scenes ever happened.
    Each entry therefore records its book, and only this book's are replaced."""
    path = paths.series_bible_path(series_id)
    bible = storage.load_json(path, {})
    others = [e for e in (bible.get("interactions") or [])
              if e.get("book") not in (None, book_num)]
    mine = [{"id": entry["id"], "who": entry["who"], "promise": entry["promise"],
             "book": book_num, "chapters": [entry["chapter"]], "status": "owed"}
            for entry in ledger(meta)]
    bible["interactions"] = others + mine
    storage.save_json(bible, path)
    if log_fn:
        log_fn(f"{series_id}: {len(mine)} interactions written to the series bible "
               f"for book {book_num}"
               + (f" ({len(others)} kept from earlier books)" if others else ""))
