"""Passage surgery — replace one anchored passage with new prose, and nothing else.

Some defects cannot be repaired by a find/replace: a paragraph with no topic sentence,
a claim the section asserts and never supports, a section over its budget that needs a
whole paragraph cut rather than every sentence squeezed. The fix is new prose, not
changed prose.

The obvious answer is to rewrite the section. That is the single most damaging
operation this pipeline can perform. Asked to re-emit a section and change only the
flagged parts, a model changes other parts too — not out of disobedience, but because
regenerating prose is not the same operation as preserving it. Issue counts under
rewriting go 2 -> 10 -> 14 across passes that were each individually told to change
almost nothing, and the new defects are new every time: a number rounded differently,
a term swapped for a synonym, a citation moved to the wrong sentence.

So the section is never re-emitted. A structural defect names an exact span; the
writer is shown the span, the prose on either side of it, and what the replacement
must do; and the harness splices the result back in. Everything outside the span is
not passed through a model at all, so it is bit-identical afterwards by construction
rather than by instruction.

Two properties make the splice safe:

  * The anchor must appear **exactly once**, checked by `patching.classify` before any
    model call is made. An ambiguous anchor costs nothing rather than corrupting a
    passage that was fine.
  * The replacement is placed by string substitution, not by regeneration. A writer
    that ignores its instructions can produce a bad *paragraph*; it cannot produce a
    different *section*.
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


def _prompt(entry, before, after, section, ground_truth=""):
    """The brief for one surgical replacement."""
    return "\n".join([
        "You are replacing ONE passage inside a section of an academic paper that is "
        "otherwise finished. Everything outside this passage is staying exactly as it "
        "is — it will not pass through you or any other model — so write a "
        "replacement that slots into the prose around it without a seam.",
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
        before.strip() or "(the passage is at the very start of the section)",
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
        after.strip() or "(the passage is at the very end of the section)",
        "",
        "=" * 70,
        "WHAT THIS SECTION IS FOR (orientation only — you are writing this passage, "
        "not the section):",
        "=" * 70,
        "\n".join(f"  - {p.get('topic', '')}"
                  for p in (section.get("paragraphs") or [])) or "(no plan on file)",
        "",
        ground_truth,
        "",
        "Rules:",
        "- Write ONLY the replacement passage. No heading, no notes, no summary of "
        "what you changed.",
        "- Match the tense, person and register of the prose around it exactly. A "
        "reader must not be able to find either join.",
        "- **Every number you write must appear in the ground truth above, character "
        "for character.** There is no exception to this and no rounding. If the "
        "passage needs a figure the ground truth does not hold, write the sentence "
        "without it.",
        "- Open the passage on its claim. Not on a citation, not on a number, not on "
        "\"However\", not on a subordinate clause that delays the claim past a comma.",
        "- One idea per sentence. Keep the mean under 22 words and let the lengths "
        "vary; no sentence past 55 words, and a semicolon is almost always a full "
        "stop that lost its nerve.",
        "- Use the locked vocabulary exactly. A synonym for a locked term is a defect, "
        "not a flourish.",
        "- Do not introduce a claim, a citation, or a caveat the surrounding prose "
        "does not already support. A new assertion here is a new defect for the next "
        "editorial pass to find.",
        "- Do not state anything the passage after yours is about to state.",
        f"- Aim for roughly {entry.get('target_words') or 'a similar number of'} "
        "words unless the instruction above says otherwise.",
    ])


def replace_passage(project_rec, paper_num, section, prose, entry, index=0,
                    ground_truth="", log_fn=None):
    """Replace one anchored passage. Returns (prose, applied: bool, reason: str).

    Never raises on a bad anchor — an unusable structural entry is reported and the
    prose is returned untouched, because a structural note is the least reliable thing
    the editor produces and it must not be able to cost a section its progress."""
    find = entry.get("find") or ""
    status = patching.classify(prose, find)
    if status != patching.UNIQUE:
        return prose, False, f"anchor {status}"
    if not entry.get("instruction"):
        return prose, False, "no instruction"

    before, after = _surroundings(prose, find)
    out_path = paths.surgery_path(project_rec["project_id"], paper_num,
                                  section["number"], index)
    prompt = text.compose(
        "", _prompt(entry, before, after, section, ground_truth), out_path,
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
    # the writer deleted rather than rewrote, and splicing it in would lose support
    # the editor never asked to cut. A genuine cut is asked for explicitly and arrives
    # with `target_words` set.
    floor = config.SURGERY_MIN_RATIO if not entry.get("target_words") else 0.0
    if floor and len(replacement) < len(find) * floor:
        return prose, False, (f"replacement is {len(replacement)} chars against "
                              f"{len(find)} replaced — refusing to delete support "
                              f"nobody asked to cut")
    return prose.replace(find, replacement, 1), True, "replaced"


def run(project_rec, paper_num, section, prose, entries, ground_truth="",
        log_fn=None):
    """Apply up to `config.SURGERY_MAX_PER_PASS` structural replacements.

    Bounded because each one is a model call producing prose that no editor has seen
    yet, and because an editor returning six structural entries has almost certainly
    mistaken "I would have written this differently" for "this paragraph has no
    claim".
    Blocking entries go first; the cap is a budget, not a queue."""
    ordered = sorted(entries or [],
                     key=lambda e: 0 if e.get("severity") == "blocking" else 1)
    applied = 0
    for index, entry in enumerate(ordered[:config.SURGERY_MAX_PER_PASS]):
        prose, ok, reason = replace_passage(
            project_rec, paper_num, section, prose, entry, index=index,
            ground_truth=ground_truth, log_fn=log_fn)
        if log_fn:
            log_fn(f"passage surgery {index + 1}: {reason} — "
                   f"{entry.get('issue', '')[:90]}")
        applied += 1 if ok else 0
    return prose, applied
