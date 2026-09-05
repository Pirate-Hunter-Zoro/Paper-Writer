"""Applying a revision as exact text edits instead of a rewrite.

The editorial instruction has always been *surgery, not authorship*: fix what the
review named and leave every other sentence verbatim. The obvious mechanism is a full
rewrite — the writer re-emits the whole section and we hope the rest comes back
unchanged. Across a few thousand words it does not.

The receipt: one unit's blocking count went 3 -> 3 -> 4 -> 1 -> 2 -> 1 -> 1 -> 1 -> 1.
It converged to a single issue by attempt three and then sat at one for six more
attempts, and **the issue was different every time**. Each revision fixed the named
defect and introduced a fresh one somewhere in the prose it was supposedly leaving
alone. An accumulated "do not reintroduce" list cannot help: it guards against old
issues returning, not against new drift.

So the model stops writing prose and starts proposing **edits**: exact find/replace
pairs. The harness applies them. Text nobody named cannot change, because nothing
rewrites it — which is the same reason the rest of this project has the model propose
and deterministic code dispose.

Pure functions, no I/O and no model: what an edit is, and whether it applies.
"""

# An edit whose `find` is not unique is ambiguous, and applying it to the first match
# is a guess. Two identical sentences in a section is ordinary; picking the wrong one
# is a silent corruption of prose that already passed.
UNIQUE, MISSING, AMBIGUOUS, EMPTY = "unique", "missing", "ambiguous", "empty"


def classify(prose, find):
    """How an edit's anchor matches the text: uniquely, not at all, or too often."""
    if not find:
        return EMPTY
    count = prose.count(find)
    if count == 0:
        return MISSING
    if count > 1:
        return AMBIGUOUS
    return UNIQUE


def apply_edits(prose, edits):
    """Apply exact find/replace edits. Returns (new_prose, applied, rejected).

    `applied` is the list of edits that landed; `rejected` is a list of
    (edit, reason) so the writer can be told precisely which anchors did not match
    rather than being asked to guess.

    All-or-nothing is deliberately NOT the rule: a review that names three defects
    and gets two of them fixed has made progress, and the third comes back on the next
    pass with its anchor problem named. Refusing the whole patch over one bad anchor
    would throw away good work and spend an attempt on nothing.

    Edits are applied in order against the evolving text, and each is re-checked
    against the text as it stands — so an edit whose anchor an earlier edit destroyed
    is rejected rather than silently skipped."""
    applied, rejected = [], []
    for edit in edits or []:
        if not isinstance(edit, dict):
            rejected.append((edit, "not an object with find/replace"))
            continue
        find = edit.get("find") or ""
        replace = edit.get("replace")
        if replace is None:
            rejected.append((edit, "no `replace` field (use \"\" to delete)"))
            continue
        status = classify(prose, find)
        if status == UNIQUE:
            prose = prose.replace(find, replace, 1)
            applied.append(edit)
        elif status == EMPTY:
            rejected.append((edit, "`find` was empty"))
        elif status == MISSING:
            rejected.append((
                edit, "`find` does not appear in the section — it must be copied "
                      "EXACTLY from the text, including punctuation and whitespace"))
        else:
            rejected.append((
                edit, f"`find` appears {prose.count(find)} times — extend it with "
                      f"surrounding text until it is unique"))
    return prose, applied, rejected


def rejection_brief(rejected):
    """What the writer is told about edits that did not apply."""
    if not rejected:
        return ""
    lines = ["Some of your edits could not be applied. For each one, the `find` text "
             "must be copied character-for-character from the section and must "
             "appear exactly once:"]
    for edit, reason in rejected[:8]:
        anchor = (edit.get("find") if isinstance(edit, dict) else str(edit)) or ""
        lines.append(f"  - {reason}\n      find was: {anchor[:160]!r}")
    return "\n".join(lines)
