"""Planning. Turn the job and the frozen evidence into a project plan and a seeded
ledger.

A project is one or more papers off one body of evidence. The plan says how many, what
each one is for, which venue it goes to, and — the part that matters — what each paper
is FOR and which claims serve it.

**Points are planned here because this is the only place they can be.** A paper's one
to three points are what its claims add up to, and choosing them needs the whole body
of evidence in view at once, which is what this stage has and no later stage does. Left
to the argument map they would be inferred from the claims, and that inverts the
ladder: claims exist to serve points, so a point derived from the claims is whatever
the claims happened to be.

The claims then say which point each one serves. A programme whose two papers both argue the headline finding is
two papers that will be desk-rejected as duplicate submission, and nothing downstream
can notice that, because each paper's own gates see a coherent argument.

The plan also seeds the project ledger: the terminology lock comes across from the
grounding document, the reference list is initialised from the evidence, and the claim
records are created in `planned` status. From here on the ledger is only ever changed
by the gatekeeper in `memory/ledger.py`.

**A single paper is the normal case and is not a special case.** A one-paper project
is the degenerate general case, exactly as a standalone novel is a one-book series.
Building the general case costs nothing on the single-paper path and means "write this
paper" and "write these three papers off one analysis" are the same machinery with a
different count.

The gate here is structural and it is strict, because everything downstream inherits
it: a plan with two headline claims, a paper with no venue, or a claim assigned to a
paper that does not exist would each produce an outline that looks fine and a
manuscript that is wrong.
"""

from .. import config, jobspec, paths
from . import correction_brief, grounding
from ..gates import claims as claims_gate
from ..gates import ladder as ladder_gate
from ..infra import storage
from ..memory.ledger import (evidence_ids, new_evidence, new_project_ledger,
                             validate_project_ledger)
from ..models import prompts, text


def evidence_block(project_rec, limit=400):
    """Every frozen evidence item, quoted. One planning call reads all of it."""
    lines = []
    for corpus in project_rec.get("corpora", []):
        doc = storage.load_json(paths.evidence_path(corpus), new_evidence(corpus))
        items = doc.get("items", [])
        lines.append(f"--- EVIDENCE: {corpus} ({len(items)} cited items) ---")
        for item in items[:limit]:
            values = ", ".join(str(v) for v in (item.get("values") or []))
            lines.append(f"  [{item.get('id','')}] {item.get('statement','')}"
                         + (f"  (values: {values})" if values else "")
                         + f"  <- {item.get('source','')}")
        if len(items) > limit:
            lines.append(f"  ... and {len(items) - limit} more")
        lines.append("")
    return "\n".join(lines) or "(no evidence on file)"


def all_evidence_ids(project_rec):
    """Every id the frozen evidence holds, across corpora."""
    out = set()
    for corpus in project_rec.get("corpora", []):
        doc = storage.load_json(paths.evidence_path(corpus), new_evidence(corpus))
        out |= evidence_ids(doc)
    return out


def propose_plan(project_rec, out_path, log_fn=None, feedback=""):
    """Model seam: produce the project plan JSON at out_path."""
    pid = project_rec["project_id"]
    return text.produce_json(
        prompts.template("project_plan") + feedback,
        ["THE JOB PROMPT:",
         project_rec["prompt_text"],
         "",
         grounding.block(pid),
         "",
         "=" * 70,
         "FROZEN EVIDENCE — every claim you plan must name the ids that support it, "
         "and every id must be one of these:",
         "=" * 70,
         evidence_block(project_rec),
         "",
         f"This job asks for {jobspec.paper_count(project_rec['prompt_text'])} "
         f"paper(s)."],
        out_path,
        role="planning",
        artifact="the project plan as strict JSON",
        log_fn=log_fn)


def _validate(plan, known_evidence, want_papers):
    """Structural invariants of a project plan. Returns a list of errors."""
    errors = []

    papers = plan.get("papers") or []
    if not papers:
        return ["plan: no papers"]
    if len(papers) != want_papers:
        errors.append(
            f"plan: {len(papers)} paper(s) planned and the job asks for "
            f"{want_papers}. The count is the job's decision, not the plan's.")

    numbers = [p.get("number") for p in papers]
    if numbers != list(range(1, len(papers) + 1)):
        errors.append(f"plan: paper numbers must be 1..{len(papers)} contiguous; "
                      f"got {numbers}")

    for paper in papers:
        n = paper.get("number")
        for field in ("title", "venue", "one_line"):
            if not str(paper.get(field) or "").strip():
                errors.append(f"paper {n}: missing `{field}`")
        limit = paper.get("word_limit")
        if limit is not None and (not isinstance(limit, int) or limit < 250):
            errors.append(f"paper {n}: `word_limit` is {limit!r}. Give the venue's "
                          f"total in words, or omit it.")

    # The claim map. This is the half that matters and the half nothing downstream
    # can second-guess.
    all_claims = plan.get("claims") or []
    all_points = plan.get("points") or []
    report = claims_gate.check(all_claims, evidence_ids=known_evidence,
                               points=all_points or None)
    errors.extend(f"plan: {e}" for e in report.errors)

    # Every claim belongs to exactly one paper, and every paper has claims.
    known_papers = {p.get("number") for p in papers}
    load = {}
    for claim in all_claims:
        cid = claim.get("id")
        where = claim.get("paper")
        if where is None:
            errors.append(f"claim {cid!r}: no `paper`. Every claim belongs to exactly "
                          f"one paper; two papers arguing one finding is a duplicate "
                          f"submission and no later gate can see it.")
            continue
        if where not in known_papers:
            errors.append(f"claim {cid!r}: assigned to paper {where!r}, which the "
                          f"plan does not have.")
            continue
        load.setdefault(where, []).append(claim)

    # Every point belongs to exactly one paper too, and for the same reason: one
    # finding assigned to two papers is one finding submitted twice.
    point_load = {}
    for point in all_points:
        pid = str(point.get("id") or "")
        where = point.get("paper")
        if where is None:
            errors.append(f"point {pid!r}: no `paper`. Every point belongs to exactly "
                          f"one paper.")
            continue
        if where not in known_papers:
            errors.append(f"point {pid!r}: assigned to paper {where!r}, which the "
                          f"plan does not have.")
            continue
        point_load.setdefault(where, []).append(point)

    for paper in papers:
        n = paper.get("number")
        mine = load.get(n, [])
        if not mine:
            errors.append(f"paper {n}: no claims assigned. A paper with no claims is "
                          f"not a paper.")
            continue
        my_points = point_load.get(n, [])

        # The ladder, per paper. Run per paper rather than across the plan because a
        # claim serving another paper's point is the duplicate-submission failure, and
        # scoped this way it surfaces as an unknown point id, which says so.
        if my_points:
            _p, laddered = ladder_gate.migrated(my_points, mine)
            ladder = ladder_gate.check(my_points, laddered)
            errors.extend(f"paper {n}: {e}" for e in ladder.errors)
        elif all_points:
            errors.append(f"paper {n}: no points assigned. A paper with claims and no "
                          f"point is a list of findings.")
        else:
            # No points anywhere in the plan: a pre-ladder plan, held to the rule the
            # ladder replaced. `gates/support.legacy_points` is the same allowance one
            # stage down.
            headlines = [c for c in mine if c.get("headline")]
            if len(headlines) != 1:
                errors.append(
                    f"paper {n}: {len(headlines)} headline claim(s) and no declared "
                    f"points. Declare what this paper is for, as one to "
                    f"{config.POINTS_MAX} points, and say which point each claim "
                    f"serves.")

    return errors


def _seed_ledger(project_id, plan, project_rec, log_fn=None):
    """Create the project ledger from the plan, the grounding and the evidence.

    Written directly rather than through `merge_ledger_update`, and that is the one
    place in the project where the gatekeeper is bypassed. It is safe because there is
    nothing to contradict yet: the gatekeeper's job is protecting committed state, and
    this is the commit that creates it. Every change after this one goes through the
    gate."""
    ledger = storage.load_json(paths.ledger_path(project_id),
                               new_project_ledger(project_id))
    ledger["terminology"] = grounding.terminology(project_id)
    ledger["conventions"] = dict(ledger.get("conventions") or {},
                                 **grounding.conventions(project_id))

    # The points first: claims reference them, and a claim serving a point the ledger
    # does not hold is the one shape the section brief cannot render.
    for point in plan.get("points") or []:
        pid = str(point.get("id"))
        ledger["points"][pid] = {
            "id": pid,
            "point": str(point.get("point") or point.get("statement") or ""),
            "paper": point.get("paper"),
        }

    for claim in plan.get("claims") or []:
        cid = str(claim.get("id"))
        ledger["claims"][cid] = {
            "id": cid,
            "claim": str(claim.get("claim") or claim.get("statement") or ""),
            "kind": claim.get("kind", "descriptive"),
            "evidence": [str(e) for e in (claim.get("evidence") or [])],
            "paper": claim.get("paper"),
            "section": claim.get("section", ""),
            "serves": ladder_gate.serves_of(claim),
            "role": ladder_gate.role_of(claim) or "",
            "headline": bool(claim.get("headline")),
            "status": "planned",
        }

    for key, entry in (plan.get("references") or {}).items():
        ledger["references"].setdefault(key, entry)

    checklist = (storage.load_json(paths.grounding_path(project_id), {})
                 .get("checklist") or {})
    for item in checklist.get("items") or []:
        name = item if isinstance(item, str) else item.get("item")
        if not name:
            continue
        ledger["checklist"].setdefault(str(name), {
            "requirement": item.get("requirement", "") if isinstance(item, dict)
            else "",
            "section": "", "satisfied": False})

    ok, errors = validate_project_ledger(ledger)
    if not ok:
        raise RuntimeError(f"planning: the seeded ledger is invalid: {errors[:4]}")
    storage.save_json(ledger, paths.ledger_path(project_id))
    if log_fn:
        log_fn(f"{project_id}: ledger seeded — {len(ledger['claims'])} claim(s), "
               f"{len(ledger['terminology'])} locked term(s)")
    return ledger


def run(project_rec, log_fn=None):
    """Produce and gate the project plan, persist it, and seed the ledger."""
    pid = project_rec["project_id"]
    proposal = paths.plan_proposal_path(pid)
    known = all_evidence_ids(project_rec)
    want = jobspec.paper_count(project_rec.get("prompt_text", ""))
    attempts = max(1, config.GATE_MAX_ATTEMPTS)
    feedback, errors, plan = "", [], None

    for attempt in range(1, attempts + 1):
        propose_plan(project_rec, proposal, log_fn=log_fn, feedback=feedback)
        plan, why = storage.load_proposal(proposal)
        errors = ([why or "the plan is not a JSON object"]
                  if not isinstance(plan, dict)
                  else _validate(plan, known, want))
        if not errors:
            break
        if log_fn:
            log_fn(f"planning: rejected (attempt {attempt}/{attempts}): {errors[:3]}")
        feedback = correction_brief(errors, attempt, attempts)

    if errors:
        raise RuntimeError(f"planning: invalid after {attempts} attempts: {errors[:4]}")

    storage.save_json(plan, paths.plan_path(pid))
    _seed_ledger(pid, plan, project_rec, log_fn=log_fn)
    if log_fn:
        log_fn(f"{pid}: planned — {len(plan.get('papers', []))} paper(s), "
               f"{len(plan.get('claims', []))} claim(s)")
    return plan
