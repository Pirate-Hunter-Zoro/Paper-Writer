"""The paper-level machine: QUEUED -> ... -> COMPLETED, one step per call.

Sections are drafted sequentially inside a paper, because section N is written against
what section N-1 established and because a Discussion written before its Results is a
Discussion of nothing.

**A paper does not fail.** The alternative is a cascade: one section that cannot
satisfy the gates parks, a parked section fails the paper, a failed paper fails the
project, and the prompt is filed away — leaving every finished section on disk and
requiring a person to notice and move a file. That mechanism can discard a nearly
complete manuscript over one stubborn Limitations paragraph.

So the two ways a paper could stop are both gone:

  * A section that will not come clean **ships holding its defects** and is revisited
    in the REVISING sweep. `engine.section` guarantees every section lands.
  * A stage that raises **stalls** the paper rather than failing it — recorded,
    retried on an escalating backoff, forever. See `engine.stalling`.

What is left is a machine whose only exits are COMPLETED and "waiting to try again".

**Why REVISING is a separate phase and not more passes per section.** Half the defects
in a manuscript are only visible against the finished document. A Discussion that
over-claims can only be caught beside the Results it over-claims about; a term used
inconsistently across two sections is invisible inside either one; an abstract written
first is wrong by the time the paper is finished. The sweep is where the editor sees
the whole thing.
"""

from .. import paths, states
from ..gates import prose
from ..infra import journal, shipping, storage
from ..stages import argument, building, delivery, outlining
from . import revising, stalling
from . import section as section_level


def advance(records, project_rec, paper_rec, log_fn=print):
    """Advance one paper by exactly one step."""
    status = paper_rec["status"]
    paper_num = paper_rec["paper_num"]
    key = paper_rec["key"]

    if status == states.STALLED:
        stalling.wake(records, paper_rec, log_fn=log_fn)
        return

    try:
        if status in states.DEAD_ENDS:
            # A record left behind by an older build. Rewind it rather than honouring
            # a verdict the machine no longer issues.
            journal.set_status(records, paper_rec, states.DRAFTING, error=None)
            log_fn(f"paper {paper_num}: clearing a legacy FAILED status; resuming")
            return

        if status == states.QUEUED:
            # The argument map first: which claim lands in which section, and what a
            # reader has to accept before each one. The outliner inherits that
            # assignment and expands it into paragraphs — it does not move a claim
            # into a section it would rather have it in, because two documents owning
            # the same fact is a loop that cannot converge.
            journal.set_status(records, paper_rec, states.ARGUING)
            mapped = argument.run(project_rec, paper_num, log_fn=log_fn)
            journal.set_status(records, records[key], states.ARGUED,
                               claim_count=len(mapped.get("claims") or []),
                               section_count=len(mapped.get("sections") or []))
            log_fn(f"paper {paper_num}: argument mapped — "
                   f"{len(mapped.get('claims') or [])} claim(s) across "
                   f"{len(mapped.get('sections') or [])} section(s)")
            return

        if status == states.ARGUED:
            journal.set_status(records, paper_rec, states.OUTLINING)
            outline = outlining.run(project_rec, paper_num, log_fn=log_fn)
            count = len(outline.get("sections") or [])
            for n in range(1, count + 1):
                record = journal.new_section(project_rec["project_id"], paper_num, n)
                journal.write_record(record)
                records[record["key"]] = record
            journal.set_status(records, records[key], states.OUTLINED,
                               section_count=count)
            return

        if status == states.OUTLINED:
            journal.set_status(records, paper_rec, states.DRAFTING)
            return

        if status == states.DRAFTING:
            _advance_drafting(records, project_rec, paper_rec, log_fn=log_fn)
            return

        if status == states.DRAFTED:
            _report_length(records, project_rec, paper_rec, log_fn=log_fn)
            journal.set_status(records, paper_rec, states.REVISING)
            return

        if status == states.REVISING:
            if revising.advance(records, project_rec, paper_rec, log_fn=log_fn):
                journal.set_status(records, paper_rec, states.BUILDING)
            return

        if status == states.BUILDING:
            title = (paper_rec.get("title")
                     or f"{project_rec['project_id']} paper {paper_num}")
            manuscript, built, notes = building.build(project_rec, paper_num, title,
                                                      log_fn=log_fn)
            journal.set_status(records, records[key], states.BUILT,
                               manuscript_path=str(manuscript),
                               built_paths=[str(p) for p in built],
                               audit_notes=notes)
            log_fn(f"paper {paper_num}: built -> {manuscript.name}"
                   + (f" + {', '.join(p.name for p in built)}" if built else ""))
            return

        if status == states.BUILT:
            journal.set_status(records, paper_rec, states.DELIVERING)
            # Every document the pipeline produced, in Markdown and in every built
            # format. The Markdown used to be the manuscript alone, which meant the
            # author's report arrived only as a .docx and read as an afterthought.
            artifacts = list(paths.documents(project_rec["project_id"], paper_num))
            artifacts += [_as_path(p) for p in (paper_rec.get("built_paths") or [])]
            dest = delivery.deliver(project_rec, paper_num, artifacts,
                                    paper_name=paper_rec.get("title"))
            journal.set_status(records, records[key], states.DELIVERED,
                               delivered_paths=[str(d) for d in dest])
            log_fn(f"paper {paper_num}: DELIVERED -> "
                   f"{dest[0].parent if dest else '(nothing to deliver)'}")

            # And commit it, if the delivery folder is a working tree and the operator
            # asked for that. Never raises: the paper is already delivered, and a git
            # problem must not be the reason a finished paper's status stays
            # unfinished. Same rule as a missing pandoc.
            title = paper_rec.get("title") or f"paper {paper_num}"
            note = shipping.ship(
                dest, shipping.message_for(project_rec, paper_num, title, dest),
                log_fn=log_fn)
            journal.set_status(records, records[key], states.COMPLETED,
                               shipped=note)
            return
    except RuntimeError as exc:
        # Stall, never fail. The record remembers where to come back to, and the wait
        # doubles each time, so a persistent bug is retried hourly rather than being
        # retried in a hot loop or abandoned.
        stalling.stall(records, records.get(key, paper_rec), str(exc), log_fn=log_fn)


def _as_path(value):
    from pathlib import Path
    return Path(value)


def _report_length(records, project_rec, paper_rec, log_fn=print):
    """Measure the finished manuscript against the venue's limit and record it.

    Reported here, and blocking nowhere. By the time this runs the paper is written,
    and refusing it would achieve nothing except stopping a manuscript that exists.
    What a measurement can honestly buy is that the author finds out — in the log and
    on the journal record — rather than discovering it from a desk rejection.

    The place a length problem is actually fixable is the outline, where the budgets
    are set and `gates/structure.py` refuses a plan that does not fit. This is the
    check that the plan was kept."""
    pid = project_rec["project_id"]
    paper_num = paper_rec["paper_num"]
    outline = storage.load_json(paths.outline_path(pid, paper_num), {"sections": []})

    words, planned = 0, 0
    for section in outline.get("sections") or []:
        planned += int(section.get("words") or 0)
        path = paths.section_path(pid, paper_num, section.get("number"))
        if path.exists():
            words += prose.word_count(
                prose.strip_structure(path.read_text(encoding="utf-8")))

    limit = None
    plan = storage.load_json(paths.plan_path(pid), {})
    for entry in plan.get("papers") or []:
        if entry.get("number") == paper_num:
            limit = entry.get("word_limit")
            break

    journal.set_status(records, paper_rec, paper_rec["status"], paper_words=words)
    if limit and words > limit:
        journal.log_decision(
            paper_rec["key"], "PAPER OVER THE VENUE'S LIMIT",
            f"{words:,} words against a limit of {limit:,}. Nothing is blocked and the "
            f"paper is built; this is recorded so it is known before submission. The "
            f"lever is the section budgets at outline time — cutting a claim, never "
            f"compressing every sentence, which is what produces prose that has to be "
            f"read twice.")
        log_fn(f"paper {paper_num}: {words:,} words, OVER the {limit:,} limit — "
               f"building anyway, recorded on the record")
    else:
        log_fn(f"paper {paper_num}: {words:,} words across "
               f"{len(outline.get('sections') or [])} sections "
               f"(planned {planned:,})")


def _advance_drafting(records, project_rec, paper_rec, log_fn=print):
    """Run the next unfinished section, or close out DRAFTING."""
    pid = project_rec["project_id"]
    paper_num = paper_rec["paper_num"]

    section_rec = journal.first_incomplete_section(records, pid, paper_num)
    if section_rec is None:
        journal.set_status(records, paper_rec, states.DRAFTED)
        log_fn(f"paper {paper_num}: all sections accepted")
        return

    if _retire_phantom(records, pid, paper_num, section_rec, log_fn=log_fn):
        return

    if section_rec["status"] in states.DEAD_ENDS:
        # Left behind by an older build that parked sections. Un-park it: the section
        # loop no longer has an outcome that requires this to be honoured.
        journal.set_status(records, section_rec, states.PENDING, error=None,
                           revisions=0, stage_errors=0)
        log_fn(f"paper {paper_num} s{section_rec['section_num']}: "
               f"clearing a legacy parked status; resuming")
        return

    section_level.run(records, project_rec, paper_rec, section_rec, log_fn=log_fn)


def _retire_phantom(records, pid, paper_num, section_rec, log_fn=print):
    """Retire a section record the current outline has no entry for. Returns True if
    it did.

    These are real and they are not rare. Outlining re-proposes up to
    `GATE_MAX_ATTEMPTS` times when the structure gate rejects it, and the paper spawns
    one record per section of whichever attempt passed — but an *earlier* build may
    already have spawned records against a longer outline, and nothing ever removed
    them. They then sit in the journal as PENDING forever, indistinguishable from work
    still to do.

    They cannot be drafted, because there is nothing to draft. Left alone they are the
    one input that turns "never give up" into a genuinely useless loop: the paper
    finishes its last real section, meets the phantom, cannot outline it, stalls,
    waits, retries, and does that until somebody looks. So the record is retired rather
    than run, which says the thing that is actually true — this number is not a
    section."""
    n = section_rec["section_num"]
    if section_rec["status"] in states.SECTION_DONE:
        return False
    outline = storage.load_json(paths.outline_path(pid, paper_num), {"sections": []})
    sections = outline.get("sections") or []
    if not sections:
        return False              # no outline at all is a different problem entirely
    if any(s.get("number") == n for s in sections):
        return False

    journal.log_decision(
        section_rec["key"], "RETIRED",
        f"the outline for paper {paper_num} has {len(sections)} sections and no entry "
        f"for section {n}. This record is left over from a superseded outline, so it "
        f"is retired rather than drafted.")
    journal.set_status(records, section_rec, states.RETIRED, error=None)
    log_fn(f"paper {paper_num} s{n}: retired — not in the {len(sections)}-section "
           f"outline")
    return True
