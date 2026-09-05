"""The project-level machine: PROMPT_DROPPED -> ... -> PROJECT_COMPLETE.

Papers are written sequentially within a project, because paper N may cite paper
N-1 and because both share one ledger. A single paper is a one-paper project, so
there is no separate path for it and there must not be one.

**A project does not fail.** The alternative is a cascade: a section parks, which
fails its paper, which fails the project, which files the prompt away and stops —
leaving every finished section on disk and requiring a person to notice and move a
file before anything happens again. That cascade exists to prevent a token-burn retry
loop, which is a real hazard with a much cheaper answer: stall, wait, and try again on
a doubling backoff. See `engine.stalling`.

So the only ways out of this machine are PROJECT_COMPLETE and "waiting to try again",
and no human gesture is required for the second one.
"""

from .. import config, states
from ..infra import journal
from ..stages import evidence, grounding, planning
from . import admission
from . import paper as paper_level
from . import stalling


def advance(records, project_rec, log_fn=print):
    """Advance one project by exactly one step."""
    status = project_rec["status"]
    key = project_rec["key"]

    if status == states.STALLED:
        stalling.wake(records, project_rec, log_fn=log_fn)
        return

    try:
        if status in states.DEAD_ENDS:
            journal.set_status(records, project_rec, states.PAPERS_IN_PROGRESS,
                               error=None)
            log_fn(f"{project_rec['project_id']}: clearing a legacy FAILED status; "
                   f"resuming")
            return

        if status == states.PROMPT_DROPPED:
            journal.set_status(records, project_rec, states.GATHERING)
            result = evidence.run(records[key], log_fn=log_fn)
            journal.set_status(records, records[key], states.GATHERED,
                               corpora=result["corpora"])
            log_fn(f"{project_rec['project_id']}: evidence frozen for "
                   f"{result['corpora']} (coverage {result['coverage']:.0%})")
            return

        if status == states.GATHERED:
            # Evidence is frozen; now fix what everything downstream has to agree on.
            # Between gathering and planning on purpose: the grounding is derived from
            # frozen ground truth rather than from the prompt's summary of it, and the
            # plan then locks its vocabulary from the grounding rather than picking a
            # word per section — which is how one method acquires three names.
            journal.set_status(records, project_rec, states.GROUNDING)
            ground = grounding.run(records[key], log_fn=log_fn)
            journal.set_status(records, records[key], states.GROUNDED,
                               terms=len(ground.get("terminology", [])))
            return

        if status == states.GROUNDED:
            journal.set_status(records, project_rec, states.PROJECT_PLANNING)
            plan = planning.run(records[key], log_fn=log_fn)
            for spec in plan["papers"]:
                record = journal.new_paper(project_rec["project_id"], spec["number"],
                                           spec.get("title"))
                journal.write_record(record)
                records[record["key"]] = record
            journal.set_status(records, records[key], states.PROJECT_PLANNED,
                               paper_count=len(plan["papers"]),
                               title=plan.get("title", ""))
            journal.set_status(records, records[key], states.PAPERS_IN_PROGRESS)
            log_fn(f"{project_rec['project_id']}: planned "
                   f"{len(plan['papers'])} paper(s)")
            return

        if status == states.PAPERS_IN_PROGRESS:
            _advance_papers(records, project_rec, log_fn=log_fn)
            return
    except RuntimeError as exc:
        stalling.stall(records, records.get(key, project_rec), str(exc), log_fn=log_fn)


def _advance_papers(records, project_rec, log_fn=print):
    """Advance the first not-yet-complete paper, or close out the project.

    A stalled paper is *skipped over* rather than blocking the project, and only for
    as long as its wait has to run. That matters for a multi-paper project: paper 2
    stalled on a provider outage must not stop paper 1 from being built and delivered.
    Papers are still written in order — a stalled paper is retried before any later
    one is started, because `paper_level.advance` on a STALLED record either wakes it
    or returns."""
    stalled = []
    for paper_rec in journal.papers_of(records, project_rec["project_id"]):
        if paper_rec["status"] == states.COMPLETED:
            continue
        if paper_rec["status"] == states.STALLED and not stalling.due(paper_rec):
            stalled.append(paper_rec)
            continue
        paper_level.advance(records, project_rec, paper_rec, log_fn=log_fn)
        return

    if stalled:
        # Everything left is waiting out a backoff. Say so rather than looking idle.
        first = stalled[0]
        log_fn(f"{project_rec['project_id']}: {len(stalled)} paper(s) waiting to "
               f"retry; paper {first['paper_num']}: {first.get('error', '')[:120]}")
        return

    journal.set_status(records, project_rec, states.PROJECT_COMPLETE)
    admission.file_prompt(project_rec, config.INBOX_FINISHED_DIR, log_fn=log_fn)
    log_fn(f"{project_rec['project_id']}: PROJECT_COMPLETE")
