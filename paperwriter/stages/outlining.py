"""Outlining. Expand the argument map into sections, and every section into
paragraphs.

The argument map says what this paper claims and which section each claim lands in.
The outline turns that into a document: an ordered section list, a word budget for
each, and — the part the whole prose contract rests on — one entry per paragraph,
carrying the topic sentence that paragraph will open on.

**Why the topic sentence is decided here and not at drafting time.** A paragraph with
no claim is repaired, once prose exists, by inventing one; and an invented claim is
precisely what the evidence ledger exists to keep out. Asked for the topic sentence at
outline time, the writer has to decide what each paragraph is *for* before writing it,
and a paragraph nobody can write a topic sentence for is a paragraph that does not
belong in the paper. It is also the cheapest place to fix: deleting a planned
paragraph costs nothing, and deleting a written one costs the writing.

**The argument map is inherited, not renegotiated.** Section assignment comes from the
map, stamped in by this stage rather than proposed by the model. The outliner expands
the assignment into paragraphs; it does not move a claim it would rather have
somewhere else. One document owns each fact.

The budgets are the other half of the job, and they are a ceiling. The venue's limit
is fixed, the sections share it, and a plan that adds up to 6,000 words for a
4,000-word journal produces four sections that each pass their own length gate and a
manuscript that is rejected unread.
"""

from .. import config, paths
from . import argument as argument_stage, correction_brief, grounding
from ..gates import structure
from ..infra import storage
from ..memory.ledger import new_evidence, evidence_ids
from ..models import prompts, text

_OUTLINE_SHAPE = (
    '{"sections": [{"number": 1, '
    '"heading": "<the heading as it appears in the manuscript>", '
    '"words": <int budget>, '
    '"claims": ["<claim id>", ...], '
    '"evidence": ["<evidence id>", ...], '
    '"exit_state": "<one line: what a reader now accepts>", '
    '"paragraphs": [{"topic": "<the sentence this paragraph opens on>", '
    '"supports": ["<claim id>", ...], '
    '"evidence": ["<evidence id>", ...], '
    '"closes": "<what the last sentence says this means>"}, ...]}, ...]}')


def _known_evidence(project_rec):
    out = set()
    for corpus in project_rec.get("corpora", []):
        doc = storage.load_json(paths.evidence_path(corpus), new_evidence(corpus))
        out |= evidence_ids(doc)
    return out


def _argument_block(argument):
    """The map, as the outliner must inherit it."""
    by_section = {}
    for claim in argument.get("claims") or []:
        by_section.setdefault(claim.get("section", ""), []).append(claim)
    lines = []
    for heading in argument.get("sections") or []:
        lines.append(f"  {heading}")
        for claim in by_section.get(heading, []):
            marker = "  [HEADLINE]" if claim.get("headline") else ""
            lines.append(f"      {claim.get('id')}{marker}: {claim.get('claim')}")
            if claim.get("evidence"):
                lines.append(f"          evidence: "
                             f"{', '.join(str(e) for e in claim['evidence'])}")
            if claim.get("depends_on"):
                lines.append(f"          the reader must already accept: "
                             f"{', '.join(str(d) for d in claim['depends_on'])}")
        if not by_section.get(heading):
            lines.append("      (no claims — this section is structural)")
    return "\n".join(lines)


def propose_outline(project_rec, paper_num, out_path, log_fn=None, feedback=""):
    """Model seam: produce the section-and-paragraph outline JSON at out_path."""
    pid = project_rec["project_id"]
    plan = storage.load_json(paths.plan_path(pid), {})
    paper = argument_stage.paper_record(plan, paper_num)
    argument = argument_stage.load(pid, paper_num)
    limit = paper.get("word_limit")

    return text.produce_json(
        prompts.template("outline") + feedback,
        ["THE PAPER:",
         f"  Title (working): {paper.get('title', '')}",
         f"  Venue:           {paper.get('venue', '')}",
         f"  Word limit:      {limit or '(none stated — plan to about 4,000)'}",
         f"  In one line:     {paper.get('one_line', '')}",
         "",
         grounding.block(pid),
         "",
         "=" * 70,
         "THE ARGUMENT MAP. The sections and the claim placement are FIXED. Expand "
         "each section into paragraphs; do not move a claim, do not add a section, "
         "and do not drop one:",
         "=" * 70,
         _argument_block(argument),
         "",
         "=" * 70,
         "THE BUDGET",
         "=" * 70,
         f"The section budgets must total at most {limit or 4000:,} words. That is a "
         f"hard ceiling: over it, the manuscript is desk-rejected before a reviewer "
         f"reads a sentence. Give each section the length its claims actually need "
         f"and cut a claim if the total does not fit — do not shave every section to "
         f"make room, because a plan that only fits after compression produces prose "
         f"that has to be read twice.",
         "",
         "Every paragraph carries the sentence it opens on. Write that sentence "
         "properly: it is the claim the paragraph makes, in the paper's own voice, "
         "and the writer will use it. A label is not a topic sentence."],
        out_path,
        role="outlining",
        artifact="the outline as strict JSON",
        shape=_OUTLINE_SHAPE,
        log_fn=log_fn)


def _stamp_claims(outline, argument):
    """Stamp each section's claim list from the argument map.

    Placement belongs to the map, so it is copied in rather than trusted from the
    proposal. The outliner still declares which claims each of its *paragraphs*
    supports, which is a finer-grained decision the map does not make."""
    by_section = {}
    for claim in argument.get("claims") or []:
        by_section.setdefault(str(claim.get("section", "")).strip().lower(), []) \
            .append(str(claim.get("id")))
    for section in outline.get("sections") or []:
        key = str(section.get("heading", "")).strip().lower()
        section["claims"] = by_section.get(key, [])
    return outline


def run(project_rec, paper_num, log_fn=None):
    """Produce and gate this paper's outline, then persist it."""
    pid = project_rec["project_id"]
    plan = storage.load_json(paths.plan_path(pid), {})
    paper = argument_stage.paper_record(plan, paper_num)
    argument = argument_stage.load(pid, paper_num)
    if not argument.get("claims"):
        raise RuntimeError(f"outlining: paper {paper_num} has no argument map")

    known = _known_evidence(project_rec)
    limit = paper.get("word_limit")
    proposal = paths.outline_proposal_path(pid, paper_num)
    attempts = max(1, config.GATE_MAX_ATTEMPTS)
    feedback, errors, outline = "", [], None

    for attempt in range(1, attempts + 1):
        propose_outline(project_rec, paper_num, proposal, log_fn=log_fn,
                        feedback=feedback)
        outline, why = storage.load_proposal(proposal)
        if not isinstance(outline, dict):
            errors = [why or "the outline is not a JSON object"]
        else:
            outline = _stamp_claims(outline, argument)
            report = structure.check(outline, evidence_ids=known,
                                     argument_claims=argument["claims"],
                                     word_limit=limit)
            errors = report.errors
            for warning in report.warnings:
                if log_fn:
                    log_fn(f"outlining (warning): {warning}")
        if not errors:
            break
        if log_fn:
            log_fn(f"outlining: rejected (attempt {attempt}/{attempts}): {errors[:3]}")
        feedback = correction_brief(errors, attempt, attempts)

    if errors:
        raise RuntimeError(f"outlining: invalid after {attempts} attempts: "
                           f"{errors[:4]}")

    storage.save_json(outline, paths.outline_path(pid, paper_num))
    total = sum(int(s.get("words") or 0) for s in outline["sections"])
    if log_fn:
        log_fn(f"paper {paper_num}: outlined — {len(outline['sections'])} section(s), "
               f"{total:,} words planned"
               + (f" against a {limit:,}-word limit" if limit else ""))
    return outline
