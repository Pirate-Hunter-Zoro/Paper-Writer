"""Build the focused digest handed to the writer for one chapter.

This is the operational heart of hard problem 1. The writer is NEVER handed the
whole three-layer memory — that neither fits a context window nor stays coherent.
It is handed a tight, relevant slice: the canon facts touching this chapter's
characters and setting, the currently open foreshadow threads (so promises get
paid and none are dropped), the previous chapter's exit state (so continuity is
literally carried forward), this chapter's beat sheet, and the locked visual and
style constraints. This mirrors Torrent-Ingest's `build_library_digest`, which
assembles a tight context for the decision at hand rather than dumping everything.

Pure function of already-loaded state, so it is deterministic and testable: same
inputs, same digest, no model call.
"""


def _canon_slice(canon_by_universe, characters):
    """Canon facts that name any of this chapter's characters, across universes."""
    wanted = [c.lower() for c in characters]
    out = []
    for universe, canon in canon_by_universe.items():
        for fact in canon.get("facts", []):
            hay = " ".join(str(fact.get(k, "")) for k in ("subject", "text")).lower()
            if any(name in hay for name in wanted):
                out.append(f"  [{universe}] ({fact.get('citation','')}) {fact['text']}")
    return out


def build_chapter_digest(chapter, prev_chapter_exit, series_bible,
                         canon_by_universe, style_guide, min_words,
                         prev_chapter_tail="", anchor_slice=""):
    """Assemble the writer's digest as a single text block.

    * chapter            — the outline chapter dict (beats, entry/exit, characters,
                           depends_on, sets_up, pays_off)
    * prev_chapter_exit  — the exit_state string of the previous chapter, or "" for
                           the first chapter
    * prev_chapter_tail  — the closing prose of the previous *accepted* chapter. The
                           planned exit_state is a summary of facts established; this
                           is where the story physically is. They are not the same
                           thing and the difference parked chapter 4 (see below).
    * series_bible       — the current series bible (for open threads + character
                           appearances)
    * canon_by_universe  — {universe: canon dict}
    * style_guide        — the tone/voice/rating block from the plan
    * min_words          — the floor beneath which this is not a chapter. A floor and
                           not a target, on purpose: see `gates/length.py`.
    """
    n = chapter.get("number")
    chars = chapter.get("characters", [])
    parts = []
    parts.append(f"CHAPTER {n} — WRITING BRIEF")
    parts.append("")
    parts.append("WHERE WE ARE (facts the previous chapter established — do not "
                 "contradict these):")
    parts.append(f"  {prev_chapter_exit or '(this is the opening chapter)'}")
    parts.append("")
    if prev_chapter_tail:
        # The outline's exit_state says what became TRUE; it does not say where the
        # characters are standing or what they were in the middle of doing. Chapter 3's
        # planned exit was "Bengel Morr is named, Elira carries her own lightsaber,
        # Kaleth is identified" — while the accepted prose ended with her *running to
        # tell Orgus*. Chapter 4 was written from the summary, opened three days later
        # with that errand silently completed, and the continuity guardian — which reads
        # the real chapter — objected to a dropped handoff the writer had never been
        # shown. Four redrafts could not fix it, because the gap was in the brief.
        parts.append("HOW THE PREVIOUS CHAPTER ACTUALLY ENDED (its real closing prose "
                     "— this is the narrative moment you are continuing FROM. Pick up "
                     "whatever it left mid-motion: an errand begun, a question asked, "
                     "someone being run toward. Do not skip past it or assume it "
                     "resolved offstage):")
        parts.append(f"  {prev_chapter_tail.strip()}")
        parts.append("")
    parts.append("THIS CHAPTER MUST END AT (its planned exit state):")
    parts.append(f"  {chapter.get('exit_state', '(agent to resolve within the beats)')}")
    parts.append("")
    parts.append("BEAT SHEET (hit these, in order):")
    parts.append(f"  {chapter.get('beats', '')}")
    parts.append("")

    parts.append("CHARACTERS IN THIS CHAPTER (write them exactly as canon and the "
                 "locked reference sheets describe — appearance is frozen, and the "
                 "VOICE line is how this person actually talks):")
    for name in chars:
        rec = series_bible.get("characters", {}).get(name)
        if rec:
            lock = " [LOCKED]" if rec.get("ref_sheet_locked") else ""
            parts.append(f"  {name}{lock}: {rec.get('appearance','')}")
            # The single most useful line in a crossover brief. Four casts written by
            # four different writers' rooms sound alike the moment one model writes
            # all of them, and "each character sounds distinct" is unactionable as a
            # critique note if the writer was never told what distinct sounds like.
            if rec.get("voice"):
                parts.append(f"      VOICE: {rec['voice']}")
        else:
            parts.append(f"  {name}")
    parts.append("")

    if anchor_slice:
        parts.append("WHERE THESE PEOPLE ARE IN THEIR LIVES RIGHT NOW (this is the "
                     "present; it overrides how they looked or lived during their own "
                     "series, and it is what the illustrations are drawn from):")
        parts.append(anchor_slice)
        parts.append("")

    canon_lines = _canon_slice(canon_by_universe, chars)
    parts.append("RELEVANT CANON (immutable ground truth — never contradict; every "
                 "line is cited):")
    parts.extend(canon_lines or ["  (no character-specific canon facts on file)"])
    parts.append("")

    open_threads = [t for t in series_bible.get("foreshadowing", [])
                    if t.get("status") == "open"]
    parts.append("OPEN THREADS (promises already made to the reader — pay off the "
                 "ones this chapter is planned to, keep the rest alive, drop none):")
    due = set(chapter.get("pays_off", []))
    for t in open_threads:
        tag = "  >> PAY OFF HERE: " if t["id"] in due else "  (keep open) "
        parts.append(f"{tag}{t['id']}: {t.get('description','')}")
    if not open_threads:
        parts.append("  (none yet)")
    parts.append("")

    # THE WRITER SEES WHAT THE CRITIC JUDGES. Both of these were in the judge's ground
    # truth and absent from the writer's brief, and chapter 7 paid for it: eight
    # attempts, and nearly every blocking issue was relative-time arithmetic —
    # "Soos's welts came up two days after the storm" against a chapter that said
    # otherwise, "the storm's age contradicts the established four-day figure", "six
    # years after Weirdmageddon". The writer was inventing durations because it had
    # never been told them, and the guardian was checking them against a ledger the
    # writer could not read.
    #
    # This project already has this failure written down from 2026-08-05, about the
    # previous chapter's exit state: whenever a generator and its judge read different
    # sources for the same fact, the loop between them cannot converge, and the
    # symptom looks like a stubborn model rather than a missing input. Same lesson,
    # different field — worth checking the two documents against each other whenever a
    # class of defect keeps coming back.
    timeline = series_bible.get("timeline") or []
    if timeline:
        parts.append("STORY TIMELINE SO FAR (when things happened; your chapter must "
                     "agree with this and advance it — do not invent a duration that "
                     "contradicts a figure already on the record):")
        parts += [f"  b{e.get('book')}c{e.get('chapter')}: {e.get('event','')}"
                  for e in timeline]
        parts.append("")

    facts = series_bible.get("facts") or []
    if facts:
        parts.append("ESTABLISHED FACTS (invented earlier in this story and now "
                     "binding — counts, distances, dates, injuries, who owns what):")
        parts += [f"  {f.get('id')}: {f.get('text','')}" for f in facts]
        parts.append("")

    _interaction_lines(parts, chapter, series_bible)

    parts.append("STYLE:")
    parts.append(f"  {style_guide}")
    parts.append("")
    # A floor, said as a floor. The previous line here named a word target, and a
    # target is an instruction to reach a number — which, for a model that has finished
    # its story, is an instruction to write filler. The filler it chose was the POV
    # character reflecting on her own dialogue, at length, in the chapter the operator
    # read first.
    parts.append(f"LENGTH: at least {min_words:,} words — a floor, not a target. There "
                 "is no upper limit and no number to hit. Write the chapter the beats "
                 "and the interactions need, at whatever length that is, and then "
                 "stop. If it comes out short, the fix is never more reflection or "
                 "more description: it is another character in the room with something "
                 "to want, or a beat you summarised in a sentence played out as a "
                 "scene.")
    parts.append("")
    parts.append("Write the chapter as Markdown prose only — no headings, no notes, "
                 "just the chapter, with `* * *` on its own line at every change of "
                 "place or time.")
    return "\n".join(parts)


def _interaction_lines(parts, chapter, series_bible):
    """The character collisions this chapter is responsible for delivering.

    A crossover is bought for its collisions and a chapter-by-chapter beat sheet does
    not produce them: beats optimise for plot, and "Dipper finally works a problem with
    Entrapta" is not a plot beat, it is the reason somebody picked the book up. So the
    pairings are planned once, up front, and each chapter is told which ones are its
    job — and which are still owed, so a natural opportunity is taken rather than
    saved for a chapter that never comes."""
    ledger = series_bible.get("interactions") or []
    if not ledger:
        return
    n = chapter.get("number")
    owed_here = [i for i in ledger if n in (i.get("chapters") or [])]
    still_open = [i for i in ledger
                  if i.get("status") != "delivered" and i not in owed_here]
    if owed_here:
        parts.append("CHARACTER INTERACTIONS THIS CHAPTER OWES THE READER (these are "
                     "why someone is reading a crossover; give each one a real scene "
                     "with its own turn, not a line of acknowledgement in passing):")
        for entry in owed_here:
            parts.append(f"  >> {' + '.join(entry.get('who', []))}: "
                         f"{entry.get('promise', '')}")
        parts.append("")
    if still_open:
        parts.append("STILL OWED LATER (do not force these, but if the scene you are "
                     "writing gives one of them a natural opening, take it):")
        for entry in still_open[:12]:
            parts.append(f"  {' + '.join(entry.get('who', []))}: "
                         f"{entry.get('promise', '')}")
        parts.append("")


def build_ground_truth(chapter, series_bible, canon_by_universe, anchor_block=""):
    """The memory a *judge* needs, quoted inline rather than left on disk to be read.

    The critique and bible-merge stages used to be handed two file paths and the
    instruction "read the draft and the bible", which on a turn-based provider is the
    most expensive way to move information that the harness already has in memory:
    every turn re-sends every prior tool result, so a bible fetched on turn 3 is paid
    for again on turns 4 through 60. Quoted once into the prompt it costs one turn.

    Deliberately *wider* than the writer's digest. The writer is given a focused slice
    so it is not overwhelmed; the judge has to catch a contradiction with something
    the writer was never shown, so it gets the whole cast, the whole open ledger, and
    every invented fact — bounded only by canon, which is filtered to this chapter's
    characters because canon is the one layer large enough to matter.

    Pure function of already-loaded state, like the rest of this module."""
    chars = chapter.get("characters", [])
    parts = ["GROUND TRUTH — the series memory, quoted in full. Judge against THIS; "
             "do not go looking for files."]
    if anchor_block:
        # Where everyone is when the book opens. It sits above canon deliberately: for
        # anything a finale changed, the anchor is the present tense and canon is the
        # past, and a chapter that gives a character their most iconic look instead of
        # their current one is wrong in the way readers notice first.
        parts += ["", anchor_block]

    parts.append("")
    parts.append("CAST (appearance is frozen once [LOCKED]; VOICE is how they talk):")
    for name, rec in sorted((series_bible.get("characters") or {}).items()):
        lock = " [LOCKED]" if rec.get("ref_sheet_locked") else ""
        parts.append(f"  {name}{lock}: {rec.get('appearance','')}")
        if rec.get("voice"):
            parts.append(f"      VOICE: {rec['voice']}")
    if not series_bible.get("characters"):
        parts.append("  (cast not yet seeded)")

    rels = series_bible.get("relationships") or []
    if rels:
        parts.append("")
        parts.append("RELATIONSHIPS:")
        parts += [f"  {r.get('a')} — {r.get('b')}: {r.get('type','')}" for r in rels]

    parts.append("")
    parts.append("FORESHADOWING LEDGER (open = a promise the reader is still owed; "
                 "paid = already resolved and must not be resolved again):")
    for thread in series_bible.get("foreshadowing") or []:
        parts.append(f"  [{thread.get('status')}] {thread.get('id')}: "
                     f"{thread.get('description','')}")
    if not series_bible.get("foreshadowing"):
        parts.append("  (none yet)")

    facts = series_bible.get("facts") or []
    if facts:
        parts.append("")
        parts.append("ESTABLISHED SERIES FACTS (invented earlier in this story and "
                     "now binding):")
        parts += [f"  {f.get('id')}: {f.get('text','')}" for f in facts]

    timeline = series_bible.get("timeline") or []
    if timeline:
        parts.append("")
        parts.append("TIMELINE SO FAR (must advance, never contradict):")
        parts += [f"  b{e.get('book')}c{e.get('chapter')}: {e.get('event','')}"
                  for e in timeline]

    ledger = series_bible.get("interactions") or []
    if ledger:
        parts.append("")
        parts.append("INTERACTION LEDGER (character collisions this book promised the "
                     "reader; a chapter that was supposed to deliver one and merely "
                     "mentions it in passing has not delivered it):")
        for entry in ledger:
            chapters = ", ".join(str(c) for c in entry.get("chapters") or []) or "-"
            parts.append(f"  [{entry.get('status', 'owed')}] ch {chapters}: "
                         f"{' + '.join(entry.get('who', []))} — "
                         f"{entry.get('promise', '')}")

    parts.append("")
    parts.append("RELEVANT CANON (immutable; a contradiction here is always "
                 "blocking):")
    parts += _canon_slice(canon_by_universe, chars) or [
        "  (no character-specific canon facts on file)"]

    parts.append("")
    parts.append("THIS CHAPTER WAS OUTLINED AS:")
    parts.append(f"  number: {chapter.get('number')}  title: "
                 f"{chapter.get('title','')}")
    # The cast list, spelled out, because one of the editor's blocking checks is now
    # about it: everyone the outline places in a chapter must speak or act in it.
    # Without this line the editor could not tell "present and silent" from "not in
    # this chapter", which is exactly how Hooty ended up as furniture — mentioned as
    # present, given nothing to say, and no gate able to see the difference.
    parts.append(f"  PRESENT IN THIS CHAPTER (every one of these must speak or act; "
                 f"being mentioned is not being present): "
                 f"{', '.join(chapter.get('characters') or []) or '(unlisted)'}")
    parts.append(f"  entry state: {chapter.get('entry_state','')}")
    parts.append(f"  beats: {chapter.get('beats','')}")
    parts.append(f"  exit state: {chapter.get('exit_state','')}")
    parts.append(f"  pays off: {', '.join(chapter.get('pays_off', [])) or 'nothing'}")
    parts.append(f"  sets up: {', '.join(chapter.get('sets_up', [])) or 'nothing'}")
    return "\n".join(parts)
