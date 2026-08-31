"""Stage 5a — Drafting. Hand the writer a focused digest; get a chapter draft.

The writer receives only the digest — the relevant canon slice, the cast with their
locked voices, open threads, the interactions this chapter owes, where the previous
chapter actually ended, this chapter's beats, and the style and length constraints —
never the whole memory. The draft lands at `paths.draft_path`, which is a proposal and
nothing more.

**A chapter is drafted exactly once.** Everything after that is repair: anchored
find/replace edits from `stages/editing`, or an anchored passage replacement from
`stages/surgery`. There is no rewrite path here and there must never be one again.

That is not a stylistic preference, it is the finding that this module used to embody
the opposite of. A revision that re-emits five thousand words changes words it was
told to leave alone — not out of disobedience, but because regenerating prose is a
different operation from preserving it. Measured across a real book, chapters whose
defects were repaired by rewriting random-walked (2 -> 10 -> 6 -> 14) and cost twenty
attempts; the same defects repaired by anchored edits fall monotonically and cost two
or three. The instruction "change nothing else" was in the prompt the whole time. An
instruction is not a mechanism.

The one thing that legitimately produces more prose is a *continuation*: a first draft
that stopped short is handed back and asked for what comes next. That is additive and
touches nothing already written, which is why it is safe and why it is here.
"""

from .. import config, paths
from ..gates import readability
from ..memory import store
from ..memory.digest import build_chapter_digest
from ..models import prompts, text
from . import anchoring


def generate(prompt, out_path, log_fn=None, role="drafting"):
    """Model seam: write chapter prose to out_path.

    ONE seam for the first draft and any continuation pass — `role` selects which
    budget the call is charged to. Splitting them into two functions immediately broke
    the test suite: every test stubs this one name, so the continuation went straight
    to the live provider and the suite started making real API calls and hanging. A
    stage's model calls have to funnel through a single replaceable function or the
    seam is not a seam."""
    return text.run(prompt, out_path, role=role, log_fn=log_fn)


def _words(prose):
    return readability.score(prose).words


def _continue_prompt(prose, chapter, floor, have, style_guide):
    """Ask for the REST of a chapter that stopped short — not a rewrite of it.

    The harness concatenates, so the model is asked for only the new text. Asking it
    instead to reproduce everything so far plus more would pay for the same prose
    again on every pass and invite it to quietly revise what was already written.

    What it is told to add matters as much as that it is additive. Asked simply for
    more words, a model that has finished its story writes the POV character thinking
    about her own dialogue — which is how a word target manufactured the exact prose
    this book was criticised for. So the instruction names what "more" is allowed to
    be: unplayed beats, and other people in the room."""
    return (
        "You are continuing a chapter of a novel that is not finished yet.\n\n"
        "Below is the chapter SO FAR. It stops short of being a chapter. Your job is "
        f"to write what comes next — and ONLY what comes next.\n\n"
        f"It currently runs {have:,} words. A chapter is at least {floor:,}, so it is "
        f"about {max(floor - have, 0):,} words short of being one.\n\n"
        "THE BEATS THIS CHAPTER MUST STILL COVER (skip any already fully played out "
        f"in the text below):\n{chapter.get('beats', '')}\n\n"
        "IT MUST END AT THIS STATE:\n"
        f"{chapter.get('exit_state', '')}\n\n"
        f"STYLE (unchanged):\n{style_guide}\n\n"
        + "=" * 70 + "\nTHE CHAPTER SO FAR\n" + "=" * 70 + f"\n{prose}\n"
        + "=" * 70 + "\n\n"
        "Rules:\n"
        "- Do NOT repeat, summarise, or rewrite any of the text above. It is already "
        "written and it is staying exactly as it is.\n"
        "- Begin at the precise moment it stops. If it ends mid-scene, stay in that "
        "scene; your first sentence should read as the next sentence of the book.\n"
        "- Match the voice, tense, and POV exactly. A reader must not be able to find "
        "the join.\n"
        "- Keep the same reading level: clear, propulsive sentences, plain words.\n"
        "- Mark every change of place or time with `* * *` on its own line.\n"
        "- Dramatise the remaining beats as scenes. Do not rush to the ending or "
        "summarise your way to the exit state — you have room, so use it.\n"
        "- **The extra words are for other people.** Do NOT add interiority: no "
        "paragraph of the POV character reacting to her own dialogue, weighing how she "
        "feels about what she just said, or noticing the significance of a moment. If "
        "you need more chapter, put another character in the room and give them "
        "something to want, something to say, and something to do about it. That is "
        "what a scene is made of and it is what is missing.\n"
        "- End the chapter on a line worth turning the page for.\n")


def _extend_to_length(prose, out_path, series_rec, chapter, memory, log_fn=None):
    """Grow a draft that came in under the floor, by continuation rather than padding.

    A single completion reliably lands short of a full chapter — measured at ~2,681
    words asked for 5,351 — because a chapter this size is three or four scenes and
    gets written the way a person writes it, a scene at a time. Without a path from
    "too short" to "long enough" the length gate would simply reject and there would be
    nothing to send anywhere.

    What changed is what it aims at. This used to chase a per-chapter word *target*
    derived from the book's total, so it fired on roughly half of all drafts and pushed
    every one of them toward a number. It now fires only when the draft is genuinely
    below the floor — not a chapter yet — and stops the moment it is one. A chapter
    that tells its story in 3,400 words is finished, and asking it for two thousand
    more is asking for filler."""
    floor = memory.chapter_floor
    if floor <= 0:
        return prose

    for pass_num in range(1, config.DRAFT_MAX_CONTINUATIONS + 1):
        have = _words(prose)
        if have >= floor:
            break
        cont_path = paths.continuation_path(
            series_rec["series_id"], chapter.get("number", 0), pass_num)
        if log_fn:
            log_fn(f"draft is {have:,} words, under the {floor:,} floor; continuation "
                   f"pass {pass_num}/{config.DRAFT_MAX_CONTINUATIONS}")
        prompt = text.compose(
            "", _continue_prompt(prose, chapter, floor, have, memory.style_guide),
            cont_path, artifact="ONLY the continuation prose (Markdown)",
            role_name="continuation")
        generate(prompt, cont_path, log_fn=log_fn, role="continuation")
        addition = cont_path.read_text(encoding="utf-8").strip()
        if not addition:
            break
        grown = prose.rstrip() + "\n\n" + addition + "\n"
        # A continuation that adds nothing is a loop that will not terminate; stop
        # rather than spend the remaining passes discovering that again.
        if _words(grown) <= have:
            break
        prose = grown
        out_path.write_text(prose, encoding="utf-8")
    return prose


def draft_chapter(series_rec, book_num, chapter_outline, prev_exit, prev_tail="",
                  log_fn=None):
    """Draft one chapter into staging, extending it to length. Returns (text, path)."""
    memory = store.load(series_rec, book_num)
    digest = build_chapter_digest(
        chapter_outline, prev_exit, memory.bible, memory.canon, memory.style_guide,
        memory.chapter_floor, prev_chapter_tail=prev_tail,
        anchor_slice=anchoring.for_characters(
            series_rec["series_id"], chapter_outline.get("characters", [])))

    sid = series_rec["series_id"]
    n = chapter_outline["number"]
    out_path = paths.draft_path(sid, book_num, n)

    prompt = text.compose(
        prompts.template("draft"), digest, out_path,
        artifact="ONLY the chapter prose (Markdown)", role_name="drafting")
    generate(prompt, out_path, log_fn=log_fn)
    prose = out_path.read_text(encoding="utf-8")
    prose = _extend_to_length(prose, out_path, series_rec, chapter_outline, memory,
                              log_fn=log_fn)
    return prose, out_path
