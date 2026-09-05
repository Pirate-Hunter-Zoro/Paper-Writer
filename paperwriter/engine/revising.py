"""The REVISING sweep — a second editorial pass over the sections that shipped flawed.

A section that could not be made clean inside its own budget is not parked and is not
thrown away: it ships, carrying a list of what is still wrong with it, and lands here.
The sweep runs once every section of the paper exists, which buys three things the
per-section loop could not have:

  * **The defect may have stopped being one.** A section flagged for raising a
    question it never answers is often fine once the Discussion that answers it has
    been written. Judging the Methods against a manuscript that stopped at the Methods
    is judging it against a cliff-edge.
  * **The editor can see the whole manuscript.** A Discussion that over-claims can only
    be caught beside the Results it over-claims about; a term used two ways across two
    sections is invisible inside either one; an abstract written first is wrong by the
    time the paper is finished. A fix chosen without the other section in view is the
    reason the same defect keeps coming back in a different costume.
  * **It is cheap.** Only flagged sections are re-read, and each gets an anchored
    repair rather than a redraft.

The sweep advances one section per engine cycle, like every other unit of work here, so
it can be interrupted, resumed, and watched.
"""

from .. import config, paths
from ..infra import journal, storage
from ..stages import review, surgery


def flagged(records, project_id, paper_num):
    """Sections the sweep still owes a pass, in order.

    Three reasons a section is here, and they get different budgets because they are
    different claims.

      * **Known defects.** Its editorial budget ran out with blocking issues still in
        the text. Worth up to `REVISION_SWEEPS` rounds, because the sweep may well
        resolve them — a good share of these are open-question complaints that stop
        being true once the section that answers the question exists.

      * **Unverified repairs.** Its last pass found defects, repaired them all, and was
        the last pass, so nothing has re-read those repairs. Worth a first round.

      * **The last round found blocking defects in it.** Worth another, and this is the
        rule that actually earns its keep.

    That third condition is the stopping rule, and it is deliberately about *blocking
    yield* rather than about edits applied. Two reasons, and they are the two traps
    this project has already paid for.

    "Sweep until nothing is unread" does not terminate: every pass that applies an edit
    leaves that edit unread, so a section the editor keeps finding polish in would sweep
    forever. And "sweep while the editor still finds something" is the reviewer-who-can-
    never-be-satisfied trap in a new costume — a demanding editor asked "is this
    perfect?" always says no, so polish must never buy another round.

    Blocking yield is neither. It is measurable, it falls, and it is about the thing the
    project exists to protect: a wrong number, a broken citation, a second name for one
    method, a paragraph with no claim. A round that turns those up is worth its cost. A
    round that yields only style notes is not, and stops."""
    out = []
    for rec in journal.sections_of(records, project_id, paper_num):
        sweeps = int(rec.get("sweeps") or 0)
        if sweeps >= config.REVISION_SWEEPS:
            continue
        if rec.get("outstanding_issues"):
            out.append(rec)
        elif sweeps == 0 and rec.get("unverified_repairs"):
            out.append(rec)
        elif sweeps and rec.get("sweep_found_blocking"):
            out.append(rec)
    return out


def advance(records, project_rec, paper_rec, log_fn=print):
    """Re-edit the next flagged section. Returns True when the sweep is finished.

    The caller owns the transition out of REVISING, so there is exactly one code path
    into BUILDING and it cannot be entered twice."""
    pid = project_rec["project_id"]
    paper_num = paper_rec["paper_num"]

    pending = flagged(records, pid, paper_num)
    if not pending:
        remaining = sum(1 for rec in journal.sections_of(records, pid, paper_num)
                        if rec.get("outstanding_issues"))
        log_fn(f"paper {paper_num}: revision sweep complete "
               f"({remaining} section(s) still carrying notes)")
        return True

    _resweep(records, project_rec, paper_num, pending[0], log_fn=log_fn)
    return False


def _resweep(records, project_rec, paper_num, section_rec, log_fn=print):
    """One section, re-edited against the finished manuscript."""
    pid = project_rec["project_id"]
    n = section_rec["section_num"]
    sweeps = int(section_rec.get("sweeps") or 0) + 1

    outline = storage.load_json(paths.outline_path(pid, paper_num), {"sections": []})
    section = next((s for s in outline["sections"] if s["number"] == n), None)
    path = paths.section_path(pid, paper_num, n)
    if section is None or not path.exists():
        journal.set_status(records, section_rec, section_rec["status"], sweeps=sweeps,
                           outstanding_issues=[])
        return

    prose = path.read_text(encoding="utf-8")
    before = list(section_rec.get("outstanding_issues") or [])
    log_fn(f"paper {paper_num} s{n}: revision sweep {sweeps} "
           f"({len(before)} outstanding issue(s))")

    try:
        report = review.review(project_rec, paper_num, section, prose,
                               pass_num=100 + sweeps, log_fn=log_fn)
    except RuntimeError as exc:
        # The sweep is a bonus pass over prose that is already committed and already
        # readable. A failure here must never cost the paper, so it counts as a sweep
        # spent and the section keeps its notes.
        journal.log_decision(section_rec["key"], f"sweep {sweeps} failed", str(exc))
        journal.set_status(records, section_rec, section_rec["status"], sweeps=sweeps)
        log_fn(f"paper {paper_num} s{n}: sweep failed ({exc}); leaving it as is")
        return

    prose, applied, rejected = review.apply_report(prose, report)
    spliced = 0
    if report["structural"]:
        prose, spliced = surgery.run(
            project_rec, paper_num, section, prose, report["structural"],
            ground_truth=review.ground_truth(project_rec, paper_num, section),
            log_fn=log_fn)

    outstanding = [f"{i['kind'].upper()}: {i['issue']}"
                   for i in review.unrepaired(report, applied)]
    outstanding += list(report["gate_failures"])

    if applied or spliced:
        storage.atomic_write_text(prose, path)

    journal.log_decision(
        section_rec["key"], f"revision sweep {sweeps}",
        f"{len(before)} issue(s) on entry, {len(applied)} edit(s) applied, "
        f"{len(rejected)} rejected, {spliced} passage(s) replaced, "
        f"{len(outstanding)} still open.\n"
        + "\n".join(f"  - {i}" for i in outstanding))
    # A sweep that found nothing is the verification this section was queued for; one
    # that applied edits has left its own repairs unread, and stops here anyway — see
    # `flagged` on why that budget is a count rather than a condition.
    # Whether THIS round found real defects is what decides if there is another one.
    # Recorded rather than recomputed, because by the next round the text has moved.
    found_blocking = bool(report["blocking"]) or bool(report["gate_failures"])
    journal.set_status(records, section_rec, section_rec["status"], sweeps=sweeps,
                       outstanding_issues=outstanding,
                       unverified_repairs=bool(applied or spliced),
                       sweep_found_blocking=found_blocking,
                       measurements=report["measurements"])
    log_fn(f"paper {paper_num} s{n}: sweep {sweeps} — {len(report['blocking'])} "
           f"blocking, {len(applied)} edit(s) applied, {len(outstanding)} still open"
           + ("; another round" if found_blocking
              and sweeps < config.REVISION_SWEEPS else ""))
