"""Stage 5c — the bible update. Validate an accepted chapter's proposed bible
changes against canon and the prior bible, then merge them.

A chapter that passes the critique battery has usually also established new facts,
opened or paid off threads, and advanced the timeline. Those proposed updates are
model output and therefore untrusted, so they go through
`memory.bible.merge_bible_update`, the structural gatekeeper: a new fact may not
collide with a canon id, a payoff may not land without a prior setup, a thread may
not be paid twice, a locked character may not mutate.

A rejected update is a RevisionNeeded, not a failure: the writer contradicted the
ledger and gets told which rule it broke. The committed bible is untouched either
way, because the merge returns a new document rather than editing in place.
"""

from .. import paths
from ..errors import RevisionNeeded
from ..infra import storage
from ..memory import store
from ..memory.bible import merge_bible_update, new_canon
from ..models import prompts, text

_LEDGER_SHAPE = (
    '{"new_facts": [{"id": str, "text": str, "source": str}],\n'
    '  "new_characters": [{"name": str, "appearance": str, "voice": str,\n'
    '                      "costumes": [str], "palette": [str],\n'
    '                      "ref_sheet_spec": str, "canon_ref": str}],\n'
    '  "new_threads": [{"id": str, "description": str, "setup_book": int,\n'
    '                   "setup_chapter": int}],\n'
    '  "pay_offs": [{"id": str, "payoff_book": int, "payoff_chapter": int}],\n'
    '  "character_locks": [str],\n'
    '  "timeline_add": [{"index": int, "book": int, "chapter": int,\n'
    '                    "event": str}]}')


def propose_updates(series_rec, book_num, chapter_num, prose, ledger,
                    log_fn=None):
    """Model seam: extract this chapter's proposed bible updates as JSON.

    The chapter and the current ledger arrive inline for the same reason they do in
    the critique: this is extraction from a document the harness is already holding,
    and making the model fetch it turns one turn of input into N."""
    sid = series_rec["series_id"]
    out_path = paths.bible_update_path(sid, book_num, chapter_num)
    return text.produce_json(
        prompts.template("bible_merge"),
        [f"This chapter is book {book_num}, chapter {chapter_num}.",
         "",
         ledger,
         "",
         "=" * 70,
         "THE ACCEPTED CHAPTER:",
         "=" * 70,
         prose],
        out_path,
        role="bible_merge",
        artifact="the proposed bible updates as strict JSON",
        shape=_LEDGER_SHAPE,
        log_fn=log_fn)


def merge(series_rec, book_num, chapter_num, prose="", log_fn=None):
    """Extract, validate, and merge this chapter's bible updates, persisting the new
    bible atomically on success. Raises RevisionNeeded if the update is rejected.

    `prose` is the accepted chapter text. It is a parameter rather than a re-read of
    the draft path because the caller already has it in hand and the draft path is
    scratch state that the next attempt deletes."""
    sid = series_rec["series_id"]
    if not prose:
        prose = paths.draft_path(sid, book_num, chapter_num).read_text(
            encoding="utf-8")
    memory = store.load(series_rec)
    ledger = _ledger_block(memory.bible)
    updates = propose_updates(series_rec, book_num, chapter_num, prose, ledger,
                              log_fn=log_fn)

    # Ground truth for the merge: the union of every universe's canon, whose ids are
    # immutable and may never be shadowed by an invented fact.
    canon = new_canon(", ".join(series_rec.get("universes", [])))
    for doc in memory.canon.values():
        canon["facts"].extend(doc.get("facts", []))

    ok, errors, merged = merge_bible_update(memory.bible, canon, updates)
    if not ok:
        raise RevisionNeeded("bible update rejected",
                             feedback="BIBLE: " + "; ".join(errors[:6]))
    storage.save_json(merged, paths.series_bible_path(sid))
    return updates


def _ledger_block(bible):
    """The parts of the bible an extractor has to see to avoid proposing an illegal
    update: which ids are taken, and which threads are already open or paid.

    Not the whole bible. The gatekeeper enforces every one of these rules anyway, so
    this is not a safety mechanism — it is how the model avoids spending a revision
    discovering a rule it could simply have been told."""
    lines = ["THE CURRENT LEDGER — do not collide with any id here."]
    lines.append("")
    lines.append("Known characters (propose new_characters ONLY for someone absent "
                 "from this list):")
    lines += [f"  {name}" + ("  [LOCKED — appearance and palette are frozen]"
                             if rec.get("ref_sheet_locked") else "")
              for name, rec in sorted((bible.get("characters") or {}).items())]
    lines.append("")
    lines.append("Foreshadow threads (pay off only an OPEN one; never re-pay a "
                 "PAID one; never reuse an id for a new thread):")
    lines += [f"  [{t.get('status')}] {t.get('id')}: {t.get('description','')}"
              for t in bible.get("foreshadowing") or []] or ["  (none yet)"]
    lines.append("")
    lines.append("Series fact ids already taken:")
    taken = [f.get("id") for f in bible.get("facts") or [] if f.get("id")]
    lines.append("  " + (", ".join(taken) if taken else "(none yet)"))
    return "\n".join(lines)
