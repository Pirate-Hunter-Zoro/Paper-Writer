"""Scene surgery — replace one anchored passage with new prose, and nothing else.

Some defects cannot be repaired by a find/replace: a scene the beat sheet treats as
important but the draft *reports* rather than plays, a beat missing outright, a chapter
that came in under length because a whole sequence was summarised in a sentence. The
fix is new prose, not changed prose.

The old answer was to rewrite the chapter. That is the single most damaging operation
this pipeline had. Asked to re-emit 4,700 words and change only the flagged parts, a
model changes other parts too — not out of disobedience, but because regenerating prose
is not the same operation as preserving it. Chapter 8's issue count went 2 -> 10 -> ...
-> 14 across rewrites that were each individually told to change almost nothing.

So the chapter is never re-emitted. A structural defect names an exact span; the writer
is shown the span, the prose on either side of it, and what the replacement must do;
and the harness splices the result back in. Everything outside the span is not passed
through a model at all, so it is bit-identical afterwards by construction rather than
by instruction.

Two properties make the splice safe:

  * The anchor must appear **exactly once**, checked by `patching.classify` before any
    model call is made. An ambiguous anchor costs nothing rather than corrupting a
    passage that was fine.
  * The replacement is placed by string substitution, not by regeneration. A writer
    that ignores its instructions can produce a bad *scene*; it cannot produce a
    different *chapter*.
"""

from .. import config, paths
from ..models import text
from . import drafting, patching

_CONTEXT_CHARS = 1500


def _surroundings(prose, find):
    """The prose immediately before and after the span being replaced.

    Without these the writer has no idea what it is joining onto and produces a passage
    that reads as a transplant: a scene that re-establishes where everyone is standing,
    re-introduces a character who has been on the page for two pages, or ends on a beat
    the next paragraph then repeats."""
    start = prose.find(find)
    if start < 0:
        return "", ""
    before = prose[max(0, start - _CONTEXT_CHARS):start]
    after = prose[start + len(find):start + len(find) + _CONTEXT_CHARS]
    return before, after


def _prompt(entry, before, after, chapter, style_guide):
    """The brief for one surgical replacement."""
    return "\n".join([
        "You are replacing ONE passage inside a chapter of a novel that is otherwise "
        "finished. Everything outside this passage is staying exactly as it is — it "
        "will not pass through you or any other model — so write a replacement that "
        "slots into the prose around it without a seam.",
        "",
        "WHAT IS WRONG WITH THE CURRENT PASSAGE:",
        f"  {entry['issue']}",
        "",
        "WHAT THE REPLACEMENT MUST DO:",
        f"  {entry['instruction']}",
        "",
        "=" * 70,
        "THE PROSE IMMEDIATELY BEFORE THE PASSAGE (do not repeat or rewrite this; your "
        "first sentence follows directly from its last):",
        "=" * 70,
        before.strip() or "(the passage is at the very start of the chapter)",
        "",
        "=" * 70,
        "THE PASSAGE TO REPLACE:",
        "=" * 70,
        entry["find"],
        "",
        "=" * 70,
        "THE PROSE IMMEDIATELY AFTER THE PASSAGE (do not repeat or rewrite this; it "
        "follows directly from your last sentence, so do not resolve anything it is "
        "about to resolve or re-establish anything it assumes):",
        "=" * 70,
        after.strip() or "(the passage is at the very end of the chapter)",
        "",
        "=" * 70,
        "THIS CHAPTER'S BEATS (for orientation only — you are writing this passage, "
        "not the chapter):",
        "=" * 70,
        chapter.get("beats", ""),
        "",
        "STYLE (unchanged, and non-negotiable):",
        style_guide,
        "",
        "Rules:",
        "- Write ONLY the replacement passage. No heading, no notes, no summary of what "
        "you changed.",
        "- Match the voice, tense, and point of view of the prose around it exactly. A "
        "reader must not be able to find either join.",
        "- Dramatise. If you are here because something was reported rather than played, "
        "the fix is dialogue, physical action, and what the room is doing — not a longer "
        "report.",
        "- Do not introduce new facts, characters, injuries, times, distances or props "
        "that the surrounding prose does not already support. A new invented detail here "
        "is a new contradiction for the next editorial pass to find.",
        "- Do not resolve anything the passage after yours resolves.",
        f"- Aim for roughly {entry.get('target_words') or 'a similar number of'} words "
        "unless the instruction above says otherwise.",
    ])


def replace_passage(series_rec, book_num, chapter, prose, entry, index=0,
                    style_guide="", log_fn=None):
    """Replace one anchored passage. Returns (prose, applied: bool, reason: str).

    Never raises on a bad anchor — an unusable structural entry is reported and the
    prose is returned untouched, because a structural note is the least reliable thing
    the editor produces and it must not be able to cost a chapter its progress."""
    find = entry.get("find") or ""
    status = patching.classify(prose, find)
    if status != patching.UNIQUE:
        return prose, False, f"anchor {status}"
    if not entry.get("instruction"):
        return prose, False, "no instruction"

    before, after = _surroundings(prose, find)
    out_path = paths.surgery_path(series_rec["series_id"], book_num,
                                  chapter["number"], index)
    prompt = text.compose(
        "", _prompt(entry, before, after, chapter, style_guide), out_path,
        artifact="ONLY the replacement passage (Markdown prose)",
        role_name="drafting")
    # Through `drafting.generate` rather than the provider directly. Every test
    # replaces that one name, so a stage model call that bypasses it goes straight to
    # the live API — which has happened twice in this project, both times discovered
    # by the suite hanging on real requests.
    drafting.generate(prompt, out_path, log_fn=log_fn, role="drafting")

    replacement = out_path.read_text(encoding="utf-8").strip()
    if not replacement:
        return prose, False, "writer produced nothing"
    # A replacement radically shorter than what it replaces is the failure mode here:
    # the writer summarised instead of dramatising, and splicing it in would delete
    # prose the editor never asked to lose.
    if len(replacement) < len(find) * config.SURGERY_MIN_RATIO:
        return prose, False, (f"replacement is {len(replacement)} chars against "
                              f"{len(find)} replaced — refusing to shrink the scene")
    return prose.replace(find, replacement, 1), True, "replaced"


def run(series_rec, book_num, chapter, prose, entries, style_guide="", log_fn=None):
    """Apply up to `config.SURGERY_MAX_PER_PASS` structural replacements.

    Bounded because each one is a model call producing prose that no editor has seen
    yet, and because an editor returning six structural entries has almost certainly
    mistaken "I would have written this differently" for "this scene does not exist".
    Blocking entries go first; the cap is a budget, not a queue."""
    ordered = sorted(entries or [],
                     key=lambda e: 0 if e.get("severity") == "blocking" else 1)
    applied = 0
    for index, entry in enumerate(ordered[:config.SURGERY_MAX_PER_PASS]):
        prose, ok, reason = replace_passage(
            series_rec, book_num, chapter, prose, entry, index=index,
            style_guide=style_guide, log_fn=log_fn)
        if log_fn:
            log_fn(f"scene surgery {index + 1}: {reason} — {entry.get('issue', '')[:90]}")
        applied += 1 if ok else 0
    return prose, applied
