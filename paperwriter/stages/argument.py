"""The argument map. Which claims this paper makes, in which section, on what
evidence.

The plan says which claims belong to this paper. This stage decides how they become a
paper: which section each one lands in, what order the argument runs in, and — for
every claim — what a reader has to already believe before it lands. That last field is
the one that turns a list of findings into an argument, and it is the one a model
skips unless asked for it by name.

**Why this is a stage and not part of outlining.** Two documents that can both decide
where a claim goes is a loop that cannot converge. The outline expands this map into
sections and paragraphs; it does not get a vote on what the paper claims. When the two
disagree the symptom always looks like a stubborn model rather than a missing input,
and the fix is always the same: one document owns each fact.

The map is built in chunks and each accepted chunk is persisted, so a crash resumes at
the next chunk rather than rebuilding the whole map. For a normal single paper that is
one chunk and the machinery is invisible; it exists so a twelve-section manuscript
cannot produce an artifact too large to write in one turn.
"""

from .. import config, paths
from . import correction_brief, grounding
from ..gates import claims as claims_gate
from ..gates import ladder as ladder_gate
from ..infra import storage
from ..memory.ledger import new_evidence, evidence_ids
from ..models import prompts, text

_ARGUMENT_SHAPE = (
    '{"sections": ["Abstract", "Introduction", ...],\n'
    '  "claims": [{"id": "<from the plan, unchanged>", '
    '"claim": "<one sentence>", '
    '"kind": "descriptive"|"comparative"|"mechanistic"|"methodological"'
    '|"limitation"|"implication", '
    '"evidence": ["<evidence id>", ...], '
    '"section": "<one of the section headings above>", '
    '"depends_on": ["<claim ids the reader must already accept>"], '
    '"headline": true|false}, ...]}')


def load(project_id, paper_num):
    """The committed argument map, or an empty one."""
    return storage.load_json(paths.argument_path(project_id, paper_num),
                             {"sections": [], "claims": [], "points": []})


def paper_points(plan, paper_num):
    """The plan's points for one paper, in plan order.

    Falls back to a single point synthesised from the paper's `headline` claim when
    the plan declares none, which is what a plan written before the support ladder
    looks like. The fallback is a migration and says so; everything downstream sees
    an ordinary one-point paper."""
    declared = [p for p in (plan.get("points") or [])
                if p.get("paper") == paper_num]
    if declared:
        return declared
    points, _claims = ladder_gate.migrated([], paper_claims(plan, paper_num))
    return points


def paper_claims(plan, paper_num):
    """The plan's claims for one paper, in plan order."""
    return [c for c in (plan.get("claims") or []) if c.get("paper") == paper_num]


def paper_record(plan, paper_num):
    for paper in plan.get("papers") or []:
        if paper.get("number") == paper_num:
            return paper
    return {}


def all_evidence_ids(project_rec):
    out = set()
    for corpus in project_rec.get("corpora", []):
        doc = storage.load_json(paths.evidence_path(corpus), new_evidence(corpus))
        out |= evidence_ids(doc)
    return out


def _evidence_block(project_rec, wanted, limit=400):
    """The evidence items this paper's claims rest on, quoted."""
    lines = []
    wanted = {str(w) for w in wanted}
    for corpus in project_rec.get("corpora", []):
        doc = storage.load_json(paths.evidence_path(corpus), new_evidence(corpus))
        items = [i for i in doc.get("items", [])
                 if not wanted or str(i.get("id")) in wanted]
        for item in items[:limit]:
            values = ", ".join(str(v) for v in (item.get("values") or []))
            lines.append(f"  [{item.get('id','')}] {item.get('statement','')}"
                         + (f"  (values: {values})" if values else "")
                         + f"  <- {item.get('source','')}")
    return "\n".join(lines) or "(no evidence on file)"


def _committed_block(argument):
    """The chunk(s) already accepted, so a later chunk does not restate them."""
    placed = argument.get("claims") or []
    if not placed:
        return "(nothing committed yet — this is the first chunk)"
    lines = [f"  {c.get('id')} -> {c.get('section')}: {c.get('claim')}"
             for c in placed]
    return "\n".join(lines)


def propose_chunk(project_rec, paper_num, plan, argument, wanted_claims, out_path,
                  log_fn=None, feedback=""):
    """Model seam: map one chunk of claims onto sections."""
    pid = project_rec["project_id"]
    paper = paper_record(plan, paper_num)
    evidence_wanted = [e for c in wanted_claims for e in (c.get("evidence") or [])]

    return text.produce_json(
        prompts.template("argument") + feedback,
        ["THE PAPER:",
         f"  Title (working): {paper.get('title', '')}",
         f"  Venue:           {paper.get('venue', '')}",
         f"  Word limit:      {paper.get('word_limit') or '(none stated)'}",
         f"  In one line:     {paper.get('one_line', '')}",
         "",
         grounding.block(pid),
         "",
         "=" * 70,
         "THE CLAIMS THIS PAPER MAKES. These are fixed by the project plan. Do not "
         "add one, do not drop one, do not change an id, and do not reword a claim "
         "into a different claim:",
         "=" * 70,
         "\n".join(
             f"  {c.get('id')} ({c.get('kind', '?')})"
             + ("  [HEADLINE]" if c.get("headline") else "")
             + f": {c.get('claim') or c.get('statement')}"
               f"\n      evidence: {', '.join(str(e) for e in (c.get('evidence') or []))}"
             for c in wanted_claims),
         "",
         "=" * 70,
         "THE EVIDENCE those claims rest on:",
         "=" * 70,
         _evidence_block(project_rec, evidence_wanted),
         "",
         "=" * 70,
         "ALREADY COMMITTED (do not re-place these; they are done):",
         "=" * 70,
         _committed_block(argument)],
        out_path,
        role="argument",
        artifact="the argument map as strict JSON",
        shape=_ARGUMENT_SHAPE,
        log_fn=log_fn)


def _validate_chunk(chunk, expected_ids, known_evidence, sections):
    """Structural check on one proposed chunk. Returns a list of errors."""
    errors = []
    proposed = chunk.get("claims") or []
    if not proposed:
        return ["the chunk has no claims"]

    seen = {}
    for claim in proposed:
        cid = str(claim.get("id") or "")
        if not cid:
            errors.append(f"claim {str(claim.get('claim'))[:50]!r}: no id")
            continue
        if cid not in expected_ids:
            errors.append(
                f"claim {cid!r} is not one of this chunk's claims. The project plan "
                f"owns what this paper claims; this stage places them and invents "
                f"none.")
            continue
        if cid in seen:
            errors.append(f"claim {cid!r} appears twice in the chunk")
            continue
        seen[cid] = claim

        where = str(claim.get("section") or "").strip()
        if not where:
            errors.append(f"claim {cid!r}: no section")
        elif sections and where.lower() not in {s.lower() for s in sections}:
            errors.append(f"claim {cid!r}: section {where!r} is not in this paper's "
                          f"section list")

        cited = [str(e) for e in (claim.get("evidence") or [])]
        if not cited:
            errors.append(f"claim {cid!r}: no evidence")
        elif known_evidence:
            unknown = [e for e in cited if e not in known_evidence]
            if unknown:
                errors.append(f"claim {cid!r}: unknown evidence "
                              f"{', '.join(unknown[:4])}")

    missing = sorted(expected_ids - set(seen))
    if missing:
        errors.append(f"the chunk does not place {', '.join(missing[:6])}. Every "
                      f"claim handed to you lands in exactly one section.")

    # Dependencies point backwards, or they are not dependencies. A claim the reader
    # has to accept first, placed later in the paper, is an argument the reader cannot
    # follow — and it is invisible once the sections are drafted, because each section
    # reads fine on its own.
    order = {s.lower(): i for i, s in enumerate(sections or [])}
    for cid, claim in seen.items():
        here = order.get(str(claim.get("section") or "").lower())
        for dep in claim.get("depends_on") or []:
            other = seen.get(str(dep))
            if other is None:
                continue        # a dependency on an earlier chunk: checked at the end
            there = order.get(str(other.get("section") or "").lower())
            if here is not None and there is not None and there > here:
                errors.append(
                    f"claim {cid!r} depends on {dep!r}, which is placed later "
                    f"({other.get('section')} after {claim.get('section')}). A reader "
                    f"cannot accept a claim before its premise.")
    return errors


def run(project_rec, paper_num, log_fn=None):
    """Build and gate this paper's argument map. Returns the committed map."""
    pid = project_rec["project_id"]
    plan = storage.load_json(paths.plan_path(pid), {})
    mine = paper_claims(plan, paper_num)
    if not mine:
        raise RuntimeError(f"argument: the plan assigns no claims to paper {paper_num}")

    known = all_evidence_ids(project_rec)
    argument = load(pid, paper_num)
    placed = {str(c.get("id")) for c in argument.get("claims") or []}
    todo = [c for c in mine if str(c.get("id")) not in placed]
    if not todo:
        if log_fn:
            log_fn(f"paper {paper_num}: argument map already complete "
                   f"({len(placed)} claim(s))")
        return argument

    step = max(1, config.ARGUMENT_CHUNK_SECTIONS)
    attempts = max(1, config.GATE_MAX_ATTEMPTS)

    while todo:
        wanted = todo[:step]
        expected = {str(c.get("id")) for c in wanted}
        chunk_index = len(argument.get("claims") or []) // max(step, 1)
        proposal = paths.argument_proposal_path(pid, paper_num, chunk_index)
        feedback, errors, chunk = "", [], None

        for attempt in range(1, attempts + 1):
            propose_chunk(project_rec, paper_num, plan, argument, wanted, proposal,
                          log_fn=log_fn, feedback=feedback)
            chunk, why = storage.load_proposal(proposal)
            if not isinstance(chunk, dict):
                errors = [why or "the argument chunk is not a JSON object"]
            else:
                sections = (chunk.get("sections")
                            or argument.get("sections") or [])
                errors = _validate_chunk(chunk, expected, known, sections)
            if not errors:
                break
            if log_fn:
                log_fn(f"argument: rejected (attempt {attempt}/{attempts}): "
                       f"{errors[:3]}")
            feedback = correction_brief(errors, attempt, attempts)

        if errors:
            raise RuntimeError(f"argument: invalid after {attempts} attempts: "
                               f"{errors[:4]}")

        # Commit the chunk before asking for the next one. A crash between chunks
        # then costs the chunk in flight and nothing else.
        if chunk.get("sections"):
            argument["sections"] = chunk["sections"]
        argument["claims"] = list(argument.get("claims") or []) + list(chunk["claims"])
        storage.save_json(argument, paths.argument_path(pid, paper_num))
        if log_fn:
            log_fn(f"paper {paper_num}: argument map now places "
                   f"{len(argument['claims'])}/{len(mine)} claim(s)")
        todo = todo[step:]

    # The whole-map check, which no single chunk can run: kinds that vary, a
    # limitation planned rather than conceded, nothing claimed twice.
    points = paper_points(plan, paper_num)
    argument["points"] = points
    report = claims_gate.check(argument["claims"], evidence_ids=known,
                               sections=argument.get("sections"),
                               points=points or None)
    if not report.passed:
        raise RuntimeError(f"argument: the assembled map is not an argument: "
                           f"{report.errors[:4]}")
    for warning in report.warnings:
        if log_fn:
            log_fn(f"argument (warning): {warning}")

    # And the ladder. The plan already checked it, so a failure here means the map
    # dropped or re-served something on its way through — which is exactly the drift
    # this stage exists to make impossible.
    _points, laddered_claims = ladder_gate.migrated(points, argument["claims"])
    ladder = ladder_gate.check(points, laddered_claims)
    if not ladder.passed:
        raise RuntimeError(f"argument: the support ladder does not hold: "
                           f"{ladder.errors[:4]}")
    for warning in ladder.warnings:
        if log_fn:
            log_fn(f"argument (warning): {warning}")
    if log_fn:
        log_fn(f"paper {paper_num}: the ladder holds — {len(points)} point(s), "
               f"{len(argument['claims'])} claim(s)")

    storage.save_json(argument, paths.argument_path(pid, paper_num))
    return argument
