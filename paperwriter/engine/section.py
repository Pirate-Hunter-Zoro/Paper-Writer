"""The editorial loop for one section — the innermost level of the machine.

    draft once -> review -> review -> ... -> LEDGER MERGE -> place prose -> journal

Two properties define it, and both are the corrections that make an automated writing
loop converge at all.

**The section is drafted exactly once.** Every later change is an anchored repair:
find/replace edits from `stages.review`, or a passage replacement from
`stages.surgery`. Nothing ever re-emits the whole section. A loop that asks a writer to
re-emit a section with only the flagged parts changed drifts every time — issue counts
go 15 -> 4 -> 3 -> 4 -> 2 -> ... -> 10 -> 7 -> 6 -> 14 across twenty-four attempts, each
of which fixes what it was told to and breaks something it was not. With repairs
anchored, the count falls monotonically because untouched text is not passed through a
model at all.

**A section never parks.** If it is still carrying defects when its editorial budget
runs out, it ships with those defects recorded on its journal record, and the paper
carries on. It is then re-edited in the paper's REVISING sweep, when every section
exists and the editor can see the whole manuscript. Parking a section fails its paper,
which fails its project — one stubborn Limitations paragraph discarding a finished
Methods, Results and Discussion, and stopping the run until a person intervenes.
Shipping a flawed section and coming back to it is strictly better than that in every
case, including the ones where the section really is bad.

The ordering of the last three steps is unchanged and is the most important sequencing
decision in the engine: merge the ledger *before* placing the prose, so a contradiction
is one more editorial pass rather than a corrupt ledger with a matching section on
disk; and place the prose immediately before the journal writes, with nothing in
between, so the verified state is durable before the engine advances.
"""

from .. import config, paths, states
from ..errors import RevisionNeeded
from ..gates import prose as prose_gate
from ..infra import journal, storage
from ..stages import ledger_update, drafting, review, surgery


def run(records, project_rec, paper_rec, section_rec, log_fn=print):
    """Drive one section to ACCEPTED/LEDGER_MERGED. It always gets there."""
    pid = project_rec["project_id"]
    paper_num = paper_rec["paper_num"]
    n = section_rec["section_num"]

    outline = storage.load_json(paths.outline_path(pid, paper_num), {"sections": []})
    sections = outline["sections"]
    section = next((s for s in sections if s["number"] == n), None)
    if section is None:
        # Not a content failure and not the section's fault: the outline is missing an
        # entry the paper claims exists. Stall the PAPER so the outline can be rebuilt,
        # rather than parking a section that was never given anything to write.
        journal.set_status(records, section_rec, states.PENDING,
                           error=f"no outline entry for section {n}")
        raise RuntimeError(f"outline has no entry for section {n}")

    text, stage_errors = _obtain_draft(
        records, project_rec, paper_rec, section_rec, section, sections, log_fn=log_fn)

    text, trajectory, outstanding, verified = _edit_to_clean(
        records, project_rec, paper_num, section_rec, section, text, log_fn=log_fn)

    _commit(records, project_rec, paper_rec, section_rec, section, text,
            trajectory, outstanding, stage_errors, verified, log_fn=log_fn)


# --- drafting ----------------------------------------------------------------

def _obtain_draft(records, project_rec, paper_rec, section_rec, section, sections,
                  log_fn=print):
    """The section's prose, drafted or recovered. Returns (text, stage_errors).

    A draft already on disk for a section the journal says is mid-flight is *reused*,
    not re-rolled. Restarting during a section used to cost the draft for no reason at
    all, since the file was sitting right there and nothing downstream had rejected
    it."""
    pid = project_rec["project_id"]
    paper_num = paper_rec["paper_num"]
    n = section_rec["section_num"]
    draft_path = paths.draft_path(pid, paper_num, n)

    if section_rec["status"] in (states.SEC_DRAFTED, states.SEC_EDITING):
        existing = _read(draft_path)
        if prose_gate.word_count(existing) >= config.DRAFT_RESUME_MIN_WORDS:
            log_fn(f"paper {paper_num} s{n}: resuming from the draft on disk "
                   f"({prose_gate.word_count(existing):,} words)")
            return existing, int(section_rec.get("stage_errors") or 0)

    prev_exit, prev_tail = "", ""
    if n > 1:
        previous = next((s for s in sections if s["number"] == n - 1), None)
        prev_exit = (previous or {}).get("exit_state", "")
        # The outline's exit_state is what the previous section was *planned* to
        # establish. The editor judges against the section that was actually accepted,
        # and after several repairs those diverge — so the writer gets the real closing
        # prose too. Absent (a first section, one still to come) is fine: the brief
        # simply omits it.
        prev_tail = _section_tail(pid, paper_num, n - 1)

    stage_errors = int(section_rec.get("stage_errors") or 0)
    while True:
        try:
            text, _ = drafting.draft_section(
                project_rec, paper_num, section, prev_exit, prev_tail=prev_tail,
                log_fn=log_fn)
        except RuntimeError as exc:
            # Infrastructure, not craft: a cut draft, a provider that died mid-stream.
            # Retried against its own cap, and when that runs out the *paper* stalls
            # rather than the section parking — a subprocess that keeps dying is not
            # the writer failing to take direction, and it will resolve on its own or
            # when a person acts.
            stage_errors += 1
            journal.log_decision(section_rec["key"],
                                 f"draft stage error {stage_errors}", str(exc))
            log_fn(f"paper {paper_num} s{n}: draft stage error {stage_errors}/"
                   f"{config.SECTION_STAGE_ERROR_RETRIES + 1}: {exc}")
            journal.set_status(records, records[section_rec["key"]], states.PENDING,
                               stage_errors=stage_errors)
            if stage_errors > config.SECTION_STAGE_ERROR_RETRIES:
                raise
            continue

        # `trajectory=[]` because this is NEW prose. The field is restored across a
        # restart (see `_edit_to_clean`), and a record that kept a redrafted section's
        # old blocking counts would spend its pass budget on a draft they were never
        # about — and would report a trend belonging to text that no longer exists.
        journal.set_status(records, records[section_rec["key"]], states.SEC_DRAFTED,
                           stage_errors=stage_errors, trajectory=[])
        return text, stage_errors


# --- editing -----------------------------------------------------------------

def _edit_to_clean(records, project_rec, paper_num, section_rec, section, text,
                   log_fn=print):
    """Run editorial passes until the section is clean or the budget is spent.

    Returns (text, trajectory, outstanding, verified).

    `outstanding` is what is still wrong when the loop stops. `verified` says whether
    the loop ended on a pass that *found nothing* — as opposed to one that found
    defects, repaired them all, and was then the last pass. Those are different states
    and conflating them is a specific lie: a section whose final pass repaired a wrong
    number and a mis-anchored citation reports "ACCEPTED clean", because every defect
    it found had a repair that landed. Nothing re-read those repairs.

    The budget bends on the same principle the whole loop runs on: the useful signal in
    an iterative process is not the count, it is whether the count is still moving. A
    section still shedding defects keeps its passes; one that has stopped improving
    does not get to spend the rest of the budget discovering that again."""
    pid = project_rec["project_id"]
    n = section_rec["section_num"]
    draft_path = paths.draft_path(pid, paper_num, n)

    # RESTORED, not started empty. The draft on disk is reused across a restart
    # (`_obtain_draft`), so the passes already spent on it are part of this section's
    # history — but a trajectory that lived only in this function's frame is silently
    # thrown away by a restart. Three things go wrong when it is: the log line is
    # untrue, `EDIT_MAX_PASSES` stops being a cap because a restart hands back a full
    # budget, and `_still_improving` cannot see a section that has stopped converging,
    # which is the whole mechanism that stops paying for a stalled loop.
    live = records.get(section_rec["key"], section_rec)
    trajectory = [int(c) for c in (live.get("trajectory") or [])]
    if trajectory:
        log_fn(f"paper {paper_num} s{n}: resuming the editorial trajectory at "
               f"{' -> '.join(str(c) for c in trajectory)}")
    outstanding = []
    verified = False
    stage_errors = int(section_rec.get("stage_errors") or 0)
    # Not 0: the passes in the restored trajectory were spent, and numbering them again
    # from 1 would re-run the budget as well as mislabel the pass in the audit log.
    pass_num = len(trajectory)

    while _may_edit(pass_num, trajectory):
        pass_num += 1
        journal.set_status(records, records[section_rec["key"]], states.SEC_EDITING,
                           revisions=pass_num)
        try:
            report = review.review(project_rec, paper_num, section, text,
                                   pass_num=pass_num, log_fn=log_fn)
        except RuntimeError as exc:
            stage_errors += 1
            journal.log_decision(section_rec["key"],
                                 f"review stage error {stage_errors}", str(exc))
            log_fn(f"paper {paper_num} s{n}: review stage error {stage_errors}/"
                   f"{config.SECTION_STAGE_ERROR_RETRIES + 1}: {exc}")
            if stage_errors > config.SECTION_STAGE_ERROR_RETRIES:
                # Out of editorial retries with a draft in hand. Ship what exists and
                # let the REVISING sweep try again later — the prose is real and the
                # failure is in the judging, not the writing.
                outstanding = ["EDITOR UNAVAILABLE: the editorial pass failed "
                               f"{stage_errors} times; last error: {exc}"]
                break
            pass_num -= 1        # an unjudged pass is not a pass
            continue

        blocking = list(report["blocking"]) + list(report["gate_failures"])
        trajectory.append(len(blocking))
        measured = report["measurements"]
        journal.log_decision(
            section_rec["key"], f"editorial pass {pass_num}",
            f"blocking={len(blocking)} polish={len(report['polish'])} "
            f"words={measured['words']} mean_sentence={measured['sentence_mean']} "
            f"bad_numbers={measured['numbers_unsupported']} "
            f"bad_paragraphs={measured['paragraph_defects']}\n"
            + "\n".join(blocking + report["polish"]))
        journal.set_status(records, records[section_rec["key"]], states.SEC_EDITING,
                           revisions=pass_num, measurements=measured,
                           trajectory=list(trajectory))

        if not blocking and not report["issues"] and not report["structural"]:
            log_fn(f"paper {paper_num} s{n}: clean after {pass_num} editorial pass(es)")
            return text, trajectory, [], True

        # Apply. Polish edits land alongside blocking ones — the severity decides
        # whether the section is finished, never whether a fix is worth applying.
        text, applied, rejected = review.apply_report(text, report)
        if report["structural"]:
            text, spliced = surgery.run(
                project_rec, paper_num, section, text, report["structural"],
                ground_truth=review.ground_truth(project_rec, paper_num, section),
                log_fn=log_fn)
        else:
            spliced = 0
        storage.atomic_write_text(text, draft_path)
        # Keep this pass's text as well as the running draft. Nothing reads it; it is
        # there so that "should the loop ship its best version rather than its last?"
        # can be answered by comparing real prose instead of arguing from defect
        # counts. The better version is otherwise overwritten by the next pass, which
        # is why the question stays open.
        storage.atomic_write_text(
            text, paths.pass_snapshot_path(pid, paper_num, n, pass_num))

        log_fn(f"paper {paper_num} s{n}: pass {pass_num} — {len(blocking)} blocking, "
               f"{len(applied)} edit(s) applied, {len(rejected)} rejected, "
               f"{spliced} passage(s) replaced")

        # A gate failure is unrepaired by definition until the arithmetic says
        # otherwise, and it is not in `issues` — it is computed, not proposed. Leaving
        # it out is how a section carrying two invented numbers ships looking clean.
        outstanding = ([f"{i['kind'].upper()}: {i['issue']}"
                        for i in review.unrepaired(report, applied)]
                       + list(report["gate_failures"]))
        if not blocking:
            # Only polish was left, and it has now been applied. Done — running another
            # judgement pass over a section with no defects buys a fresh set of
            # opinions, not a better paper. Not `verified`, though: the polish edits
            # themselves have not been read by anything.
            return text, trajectory, [], False
        if not applied and not spliced:
            # The editor named defects and could repair none of them. Another identical
            # pass will do the same. Stop and hand the section to the sweep.
            log_fn(f"paper {paper_num} s{n}: editor could not anchor any repair; "
                   f"deferring {len(outstanding)} issue(s) to the revision sweep")
            break

    return text, trajectory, outstanding, verified


def _may_edit(pass_num, trajectory):
    """Whether this section gets another editorial pass.

    Below the soft cap, always. Above it, only while the blocking count is still
    falling — and never past the hard ceiling. A pass costs a real amount of
    allowance, and the thing worth paying for is progress."""
    if pass_num < config.EDIT_MAX_PASSES:
        return True
    if pass_num >= config.EDIT_HARD_MAX_PASSES:
        return False
    return _still_improving(trajectory)


def _still_improving(trajectory):
    """Whether the last `EDIT_STALL_PASSES` passes beat the best count before them."""
    window = config.EDIT_STALL_PASSES
    if len(trajectory) <= window:
        return True
    return min(trajectory[-window:]) < min(trajectory[:-window])


# --- committing --------------------------------------------------------------

def _commit(records, project_rec, paper_rec, section_rec, section, text,
            trajectory, outstanding, stage_errors, verified, log_fn=print):
    """Merge the ledger, place the prose, journal it. The section always lands.

    `verified` separates "a pass read this section and found nothing" from "the last
    pass found things, fixed them, and was the last pass". Only the first is clean. The
    second is queued for one sweep round, which is what a sweep is for."""
    pid = project_rec["project_id"]
    paper_num = paper_rec["paper_num"]
    n = section_rec["section_num"]
    trend = " -> ".join(str(c) for c in trajectory) or "clean on arrival"

    # The last pass's edits were applied and then nothing looked at the result. Most of
    # that cannot be checked without another judgement call — but the gates are
    # arithmetic, they cost nothing, and an editor splitting sentences to escape "too
    # dense" can overshoot into "every sentence is the same length" in a way the pass
    # that did it cannot see.
    late, measured = review.gate_failures(project_rec, paper_num, section, text)
    outstanding = list(outstanding)
    for failure in late:
        if failure not in outstanding:
            outstanding.append(failure)

    merge_note = _merge_ledger(project_rec, paper_num, n, text, log_fn=log_fn)
    if merge_note:
        outstanding.append(merge_note)

    storage.atomic_write_text(text, paths.section_path(pid, paper_num, n))
    journal.set_status(records, records[section_rec["key"]], states.ACCEPTED,
                       revisions=len(trajectory), stage_errors=stage_errors,
                       measurements=measured,
                       unverified_repairs=not verified,
                       outstanding_issues=outstanding)
    journal.set_status(records, records[section_rec["key"]], states.LEDGER_MERGED)

    if not outstanding and not verified:
        # Two ways to finish unverified, and they are not equally alarming. A last pass
        # that found blocking defects and fixed them is a section whose corrections are
        # unread; one that found only style notes and applied them is a section in good
        # shape whose polish is unread. Both earn the sweep — a style edit can quietly
        # change a number, and a reworded sentence can lose a citation — but a log line
        # describing the second as "repaired what it found" invites the reader to think
        # a clean section had defects at the end.
        last = trajectory[-1] if trajectory else 0
        what = (f"repaired the {last} defect(s) it found" if last
                else "found no defects and applied style edits")
        log_fn(f"paper {paper_num} s{n}: ACCEPTED ({trend}) — its last pass {what}, "
               f"and nothing has re-read that text; queued for one verification sweep")
    elif outstanding:
        journal.log_decision(
            section_rec["key"], "ACCEPTED WITH OUTSTANDING ISSUES",
            f"blocking issues per pass: {trend}. Shipped holding "
            f"{len(outstanding)} issue(s); the paper's revision sweep will come back "
            f"to this section with the whole manuscript in view.\n"
            + "\n".join(f"  - {i}" for i in outstanding))
        log_fn(f"paper {paper_num} s{n}: ACCEPTED holding {len(outstanding)} "
               f"issue(s) ({trend}) — queued for the revision sweep")
    else:
        log_fn(f"paper {paper_num} s{n}: ACCEPTED clean and verified ({trend})")


def _merge_ledger(project_rec, paper_num, n, text, log_fn=print):
    """Merge this section's proposed ledger updates. Returns a note if it could not.

    The merge is a gate on the *ledger*, not on the prose, and it must not be able to
    stop the paper. A proposal that contradicts the evidence is refused — which is the
    whole point of the gatekeeper — and the section still ships, carrying a note saying
    its facts did not make it into the ledger. The alternative is a section that cannot
    be committed at all and a paper that stops."""
    try:
        ledger_update.merge(project_rec, paper_num, n, prose=text, log_fn=log_fn)
        return ""
    except RevisionNeeded as needed:
        return (f"LEDGER: proposed updates were refused by the merge gate: "
                f"{needed.feedback}")
    except RuntimeError as exc:
        return f"LEDGER: could not merge this section's updates: {exc}"


# --- helpers -----------------------------------------------------------------

def _read(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _section_tail(pid, paper_num, n):
    """The closing `config.DIGEST_PREV_TAIL_WORDS` words of an accepted section.

    Returns "" when that section is not on disk, so a first section or one still to
    come degrades to omitting the block rather than raising."""
    words = _read(paths.section_path(pid, paper_num, n)).split()
    if not words:
        return ""
    return " ".join(words[-config.DIGEST_PREV_TAIL_WORDS:])
