"""Outline structure gate — validate a book's chapter list before drafting.

An outline expands a book's slot in the series plan into an ordered chapter list.
Each chapter carries a beat sheet, its entry/exit state, which characters appear,
which continuity facts it depends on and which it establishes, which foreshadow
threads it sets up and which it pays off, and a monotonically advancing timeline
index. Before a word of prose is written the outline is validated for the three
structural properties the README names:

  * the timeline advances monotonically (no chapter set before an earlier one);
  * every payoff has a prior setup (you cannot resolve a thread never planted);
  * no orphaned threads (every thread set up is eventually paid off).

Plus the mechanical floor: chapters numbered contiguously from 1, and every fact a
chapter depends on is established by an earlier chapter or seeded from canon/the
series bible. All deterministic, all testable here without a model.

A chapter dict is expected to carry:
    number, beats, entry_state, exit_state, characters,
    depends_on (fact ids), establishes (fact ids),
    sets_up (thread ids), pays_off (thread ids), timeline_index
Missing list fields default to empty; a missing number/timeline_index is an error.
"""

from dataclasses import dataclass, field


@dataclass
class OutlineReport:
    passed: bool
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def check(outline, seed_facts=None, min_chapters=None, interactions=None,
          meta_chapters=None, progressions=None):
    """Validate a book outline. `seed_facts` is the set of fact ids already true
    coming into the book (from canon and the series bible), so a chapter may depend
    on them without an in-book establishing chapter.

    `min_chapters` is a FLOOR, not a target, and the difference is the point. This
    used to be a ±15% band around a specified count, and the specified count was what
    set the per-chapter word target that manufactured the book's filler. The count is
    now the outliner's decision — however many chapters the story needs — and the only
    thing gated is that it did not deliver a novella.

    `meta_chapters` is the meta plan's chapter list. When it is supplied the outline
    must match it: same count, and each chapter's cast covering the people the meta
    plan put in that chapter. **The outliner inherits the chapter assignment and does
    not get a vote on it.** Two documents that can both assign the same fact is the
    failure this project's stories record three separate times — the loop between a
    generator and its judge cannot converge when they read different sources, and the
    symptom always looks like a stubborn model rather than a missing input.

    Returns an OutlineReport."""
    seed = set(seed_facts or ())
    errors = []
    chapter_list = outline.get("chapters", [])
    if min_chapters:
        count = len(chapter_list)
        if count < min_chapters:
            errors.append(
                f"outline has {count} chapters and the floor is {min_chapters}. How "
                f"many chapters this book needs is your decision and there is no "
                f"upper limit — but this is a deep, rich novel rather than a novella, "
                f"and {count} chapters cannot carry the story that was planned. Do "
                f"not pad: split the chapters that are doing two jobs, and give the "
                f"beats you compressed into a sentence their own chapters.")
    warnings = []
    chapters = outline.get("chapters", [])
    if not chapters:
        return OutlineReport(passed=False, errors=["outline has no chapters"])

    # 1. Contiguous numbering from 1.
    numbers = [ch.get("number") for ch in chapters]
    if numbers != list(range(1, len(chapters) + 1)):
        errors.append(f"chapter numbers must be 1..{len(chapters)} contiguous; "
                      f"got {numbers}")

    # 2. Titles: present, distinct, and not a summary.
    #
    # Gated because nothing downstream can recover a missing one — the binder has to
    # fall back to "Chapter 7", and a 37-chapter book of numbered headings is what
    # shipped the first time nobody checked. Distinctness matters as much as presence:
    # duplicated titles in a table of contents are worse than none.
    seen_titles = {}
    for ch in chapters:
        n = ch.get("number")
        title = str(ch.get("title") or "").strip()
        if not title:
            errors.append(f"chapter {n}: missing title")
            continue
        if len(title) > 80:
            errors.append(f"chapter {n}: title is {len(title)} chars; a title, "
                          f"not a summary (keep it under 80)")
        key = title.lower()
        if key in seen_titles:
            errors.append(f"chapter {n}: title {title!r} duplicates chapter "
                          f"{seen_titles[key]}")
        else:
            seen_titles[key] = n

    # 3. Monotonic timeline.
    last_idx = None
    for ch in chapters:
        idx = ch.get("timeline_index")
        n = ch.get("number")
        if idx is None:
            errors.append(f"chapter {n}: missing timeline_index")
            continue
        if last_idx is not None and idx < last_idx:
            errors.append(f"chapter {n}: timeline_index {idx} goes backwards "
                          f"(previous was {last_idx})")
        last_idx = idx

    # 4. Fact dependencies: depends_on must be established earlier or seeded.
    established = set(seed)
    for ch in chapters:
        n = ch.get("number")
        for fid in ch.get("depends_on", []):
            if fid not in established:
                errors.append(f"chapter {n}: depends on fact {fid!r} not yet "
                              "established (orphaned dependency)")
        for fid in ch.get("establishes", []):
            established.add(fid)

    # 5. Threads: every payoff has a prior setup; no thread is orphaned (set up but
    #    never paid off within the book).
    setup_at = {}     # thread id -> chapter number where set up
    for ch in chapters:
        n = ch.get("number")
        for tid in ch.get("sets_up", []):
            if tid in setup_at:
                errors.append(f"chapter {n}: thread {tid!r} set up again "
                              f"(already set up in chapter {setup_at[tid]})")
            else:
                setup_at[tid] = n
        for tid in ch.get("pays_off", []):
            if tid not in setup_at:
                errors.append(f"chapter {n}: pays off thread {tid!r} with no prior "
                              "setup")
            elif setup_at[tid] >= n:
                errors.append(f"chapter {n}: pays off thread {tid!r} in the same or "
                              f"an earlier chapter than its setup ({setup_at[tid]})")

    paid = {tid for ch in chapters for tid in ch.get("pays_off", [])}
    for tid, n in setup_at.items():
        if tid not in paid:
            errors.append(f"thread {tid!r} set up in chapter {n} is never paid off "
                          "(orphaned thread)")

    # 6. Interactions: every collision the meta plan promised is delivered exactly once.
    #
    # The outliner does not choose these any more — `stages.outlining` stamps each
    # chapter's `delivers` straight from the meta plan, which is the document that owns
    # chapter assignment. This check therefore guards the stamping rather than the
    # model: twice is as wrong as never, and an interaction nothing delivers is a scene
    # the book promised and does not contain.
    delivered_at = {}
    for ch in chapters:
        n = ch.get("number")
        for iid in ch.get("delivers", []):
            if iid in delivered_at:
                errors.append(f"chapter {n}: interaction {iid!r} is already "
                              f"delivered in chapter {delivered_at[iid]}")
            else:
                delivered_at[iid] = n
    for entry in interactions or ():
        iid = entry.get("id")
        if iid and iid not in delivered_at:
            errors.append(
                f"interaction {iid!r} ({' + '.join(entry.get('who', []))}) is "
                f"promised by the meta plan and delivered by no chapter.")

    # 7. The meta plan is inherited, not renegotiated.
    #
    # Same count, and every person the meta plan put in a chapter is in that chapter's
    # cast. The outliner expands the assignment into beats; it does not get to move a
    # scene it would rather have somewhere else.
    if meta_chapters is not None:
        if len(chapters) != len(meta_chapters):
            errors.append(
                f"the outline has {len(chapters)} chapters and the meta plan has "
                f"{len(meta_chapters)}. The meta plan owns the chapter breakdown — "
                f"expand each of its chapters into beats, do not merge, split, add or "
                f"drop any.")
        by_number = {c.get("number"): c for c in meta_chapters}
        for ch in chapters:
            n = ch.get("number")
            planned = by_number.get(n)
            if not planned:
                continue
            cast = set(ch.get("characters") or [])
            missing = [w for w in (planned.get("cast") or []) if w not in cast]
            if missing:
                errors.append(
                    f"chapter {n}: the meta plan places {', '.join(missing[:6])} in "
                    f"this chapter but the outline's `characters` list omits them. "
                    f"Everyone the meta plan puts in a chapter appears in it.")

    # 8. Progressions: every planned escalation lands in exactly one chapter.
    #
    # Placement is the outliner's job here, unlike the interactions above, and the two
    # do not overlap — one document owns each fact. Nothing in this pipeline has ever
    # tracked a character getting stronger, so without this a progression declared in
    # the plan simply never happens and no gate notices.
    # Truthy, not `is not None`: an empty list means "this plan declares none", which is
    # the same thing as not being asked to check. Treating it as "there are zero valid
    # ids" turns every `delivers_progression` the outline prompt asks for into an
    # unknown-id error, burns all the gate attempts, and stalls a book whose outline is
    # fine — which is what a plan written before progressions existed would produce.
    if progressions:
        placed_at = {}
        known = {p.get("id") for p in progressions if p.get("id")}
        for ch in chapters:
            n = ch.get("number")
            for pid in ch.get("delivers_progression", []):
                if pid not in known:
                    errors.append(f"chapter {n}: unknown progression {pid!r}")
                elif pid in placed_at:
                    errors.append(f"chapter {n}: progression {pid!r} already delivered "
                                  f"in chapter {placed_at[pid]}")
                else:
                    placed_at[pid] = n
        for entry in progressions:
            pid = entry.get("id")
            if pid and pid not in placed_at:
                errors.append(
                    f"progression {pid!r} ({entry.get('who', '?')}: "
                    f"{entry.get('ends', '')}) is planned and delivered by no chapter. "
                    f"Give it to the chapter where they earn it — the chapter that "
                    f"delivers it also owes the picture of it.")

    return OutlineReport(passed=not errors, errors=errors, warnings=warnings)
