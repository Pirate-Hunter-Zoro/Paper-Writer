"""The ledger update. Validate an accepted section's proposed ledger changes against
the evidence and the prior ledger, then merge them.

A section that clears the editorial loop has usually also settled something: it made a
claim the ledger had only planned, cited a reference for the first time, established a
definition later sections will rely on, raised a question the Discussion will have to
answer, or satisfied a checklist item. Those proposed updates are model output and
therefore untrusted, so they go through `memory.ledger.merge_ledger_update`, the
structural gatekeeper: a claim may not cite evidence that does not exist, a question
may not be settled without having been raised, a reference key may not be repointed at
a different paper, and a convention may not be changed after sections were written
under it.

A rejected update is a RevisionNeeded, not a failure: the writer contradicted the
ledger and gets told which rule it broke. The committed ledger is untouched either
way, because the merge returns a new document rather than editing in place.

**Why this runs before the prose is placed.** The ordering is the most important
sequencing decision in the engine and it is deliberately counter-intuitive: merge the
ledger first, then commit the section. A contradiction found here is one more
editorial pass. A contradiction found after the prose is on disk is a corrupt ledger
with a matching section beside it, and nothing downstream can tell which of the two
is wrong.
"""

from .. import paths
from ..errors import RevisionNeeded
from ..infra import storage
from ..memory import store
from ..memory.ledger import merge_ledger_update
from ..models import prompts, text

_LEDGER_SHAPE = (
    '{"new_facts": [{"id": str, "text": str, "source": str}],\n'
    '  "new_claims": [{"id": str, "claim": str, "kind": str,\n'
    '                  "evidence": [str], "section": str}],\n'
    '  "support": ["<claim id this section actually made in prose>"],\n'
    '  "new_questions": [{"id": str, "question": str, "raised_in": str}],\n'
    '  "settled": [{"id": str, "settled_in": str}],\n'
    '  "new_references": {"<key>": {"title": str, "year": int,\n'
    '                               "authors": str, "venue": str}},\n'
    '  "conventions": {"<name>": "<value>"},\n'
    '  "checklist": {"<item>": {"section": str, "satisfied": true}}}')


def propose_updates(project_rec, paper_num, section_num, prose, ledger_block,
                    log_fn=None):
    """Model seam: extract this section's proposed ledger updates as JSON.

    The section and the current ledger arrive inline for the same reason they do in
    the review pass: this is extraction from a document the harness is already
    holding, and making the model fetch it turns one turn of input into several."""
    pid = project_rec["project_id"]
    out_path = paths.ledger_update_path(pid, paper_num, section_num)
    return text.produce_json(
        prompts.template("ledger_merge"),
        [f"This section is paper {paper_num}, section {section_num}.",
         "",
         ledger_block,
         "",
         "=" * 70,
         "THE ACCEPTED SECTION:",
         "=" * 70,
         prose],
        out_path,
        role="ledger_merge",
        artifact="the proposed ledger updates as strict JSON",
        shape=_LEDGER_SHAPE,
        log_fn=log_fn)


def merge(project_rec, paper_num, section_num, prose="", log_fn=None):
    """Extract, validate, and merge this section's ledger updates, persisting the new
    ledger atomically on success. Raises RevisionNeeded if the update is rejected.

    `prose` is the accepted section text. It is a parameter rather than a re-read of
    the draft path because the caller already has it in hand and the draft path is
    scratch state that the next attempt deletes."""
    pid = project_rec["project_id"]
    if not prose:
        prose = paths.draft_path(pid, paper_num, section_num).read_text(
            encoding="utf-8")
    memory = store.load(project_rec, paper_num)
    updates = propose_updates(project_rec, paper_num, section_num, prose,
                              _ledger_block(memory.ledger), log_fn=log_fn)

    ok, errors, merged = merge_ledger_update(memory.ledger,
                                             memory.evidence_document(), updates)
    if not ok:
        raise RevisionNeeded("ledger update rejected",
                             feedback="LEDGER: " + "; ".join(errors[:6]))
    storage.save_json(merged, paths.ledger_path(pid))
    return updates


def _ledger_block(ledger):
    """The parts of the ledger an extractor has to see to avoid proposing an illegal
    update: which ids are taken, which questions are open, and what is already fixed.

    Not the whole ledger. The gatekeeper enforces every one of these rules anyway, so
    this is not a safety mechanism — it is how the model avoids spending a revision
    discovering a rule it could simply have been told."""
    lines = ["THE CURRENT LEDGER — do not collide with any id here.", ""]

    claims = ledger.get("claims") or {}
    lines.append("Claims already committed (mark one as `support` when this section "
                 "actually makes it; propose `new_claims` only for something genuinely "
                 "new, and it will need evidence ids):")
    lines += [f"  [{c.get('status', '?')}] {cid}: {c.get('claim', '')}"
              for cid, c in sorted(claims.items())] or ["  (none yet)"]
    lines.append("")

    questions = ledger.get("questions") or []
    lines.append("Open questions (settle only an OPEN one; never re-settle a SETTLED "
                 "one; never reuse an id):")
    lines += [f"  [{q.get('status')}] {q.get('id')}: {q.get('question', '')}"
              for q in questions] or ["  (none yet)"]
    lines.append("")

    conventions = ledger.get("conventions") or {}
    lines.append("Conventions already fixed. Do NOT propose a different value for one "
                 "of these — sections written under the old value would have to be "
                 "revised, and a merge is not where that decision gets made:")
    lines += [f"  {k} = {v}" for k, v in sorted(conventions.items())] or \
             ["  (none yet)"]
    lines.append("")

    references = ledger.get("references") or {}
    lines.append("Reference keys already taken (a key points at one paper forever; "
                 "give a second source its own key):")
    lines.append("  " + (", ".join(sorted(references)) if references else "(none yet)"))
    lines.append("")

    taken = [f.get("id") for f in ledger.get("facts") or [] if f.get("id")]
    lines.append("Ledger fact ids already taken:")
    lines.append("  " + (", ".join(taken) if taken else "(none yet)"))
    return "\n".join(lines)
