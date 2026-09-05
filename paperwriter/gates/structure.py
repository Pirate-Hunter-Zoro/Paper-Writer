"""Outline structure gate — validate a paper's section plan before drafting.

An outline expands a paper's slot in the project plan into an ordered section list.
Each section carries its heading, its word budget, the claims it makes, the evidence
those claims rest on, and a paragraph-by-paragraph plan in which every paragraph
declares its own topic sentence. Before a word of prose is written the outline is
validated for the properties that cannot be repaired later:

  * sections are numbered contiguously from 1, with distinct headings;
  * the argument order is IMRaD: nothing in Results before Methods, no Discussion
    before Results;
  * every claim in the argument map lands in exactly one section;
  * every claim a section makes rests on evidence the frozen reference holds;
  * every paragraph declares a topic sentence, and the section's paragraph budgets
    add up to its word budget.

**Why the topic sentence is gated at the outline and not at the draft.** By the time
prose exists, a paragraph with no claim is repaired by inventing one, and an invented
claim is the thing this whole harness exists to prevent. Asked for it at the outline,
the writer has to decide what each paragraph is *for* before writing it — and a
paragraph nobody could write a topic sentence for is a paragraph that should not be in
the paper. The paragraph gate downstream checks that the drafted prose still has the
shape the outline promised; this one checks that a shape was promised at all.

**The argument map is inherited, not renegotiated.** When `argument_claims` is
supplied the outline must place every one of them and invent none. Two documents that
can both decide where a claim goes is a loop that cannot converge, and the symptom
always looks like a stubborn model rather than a missing input.

All deterministic, all testable here without a model.
"""

from dataclasses import dataclass, field

# The IMRaD spine, in the order a reader meets it. A heading is matched to a phase by
# the first keyword it contains; anything unrecognised is unordered and free to sit
# anywhere, which is what front matter, declarations and appendices need.
_PHASE_KEYWORDS = (
    ("front", ("title", "abstract", "keywords", "highlights", "summary")),
    ("intro", ("introduction", "background")),
    ("methods", ("method", "materials", "data and", "study design", "participants",
                 "statistical analysis", "procedure")),
    ("results", ("result", "findings", "outcome")),
    ("discussion", ("discussion", "interpretation", "limitation", "implication",
                    "comparison with prior")),
    ("conclusion", ("conclusion",)),
    ("back", ("declaration", "reference", "acknowledg", "appendix", "supplement",
              "multimedia", "abbreviation", "funding", "ethics",
              "conflict", "availability")),
)

_PHASE_ORDER = {"front": 0, "intro": 1, "methods": 2, "results": 3,
                "discussion": 4, "conclusion": 5, "back": 6}


def phase_of(heading):
    """Which part of the IMRaD spine a heading belongs to, or "" when it is free."""
    low = str(heading or "").strip().lower()
    for phase, keywords in _PHASE_KEYWORDS:
        if any(k in low for k in keywords):
            return phase
    return ""


@dataclass
class OutlineReport:
    passed: bool
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def check(outline, evidence_ids=None, argument_claims=None, word_limit=None):
    """Validate a paper outline. Returns an OutlineReport.

    `evidence_ids` is the set of ids the frozen evidence holds, so a section may rest
    a claim on one without inventing it.

    `argument_claims` is the argument map's claim list. When supplied, the outline
    must place every claim exactly once and may not introduce a claim the map does
    not hold.

    `word_limit` is the venue's total. The section budgets must fit inside it, which
    is the one length check that has to happen before drafting: a plan that adds up to
    6,000 words for a 4,000-word journal produces four sections that each pass their
    own length gate and a manuscript that is rejected unread.
    """
    errors, warnings = [], []
    sections = outline.get("sections") or []
    if not sections:
        return OutlineReport(passed=False, errors=["outline has no sections"])

    # 1. Contiguous numbering from 1.
    numbers = [s.get("number") for s in sections]
    if numbers != list(range(1, len(sections) + 1)):
        errors.append(f"section numbers must be 1..{len(sections)} contiguous; "
                      f"got {numbers}")

    # 2. Headings: present and distinct. A duplicated heading in a manuscript is
    #    worse than a missing one — the reader cannot tell which section they are in
    #    and the build produces two identical table-of-contents entries.
    seen = {}
    for section in sections:
        n = section.get("number")
        heading = str(section.get("heading") or "").strip()
        if not heading:
            errors.append(f"section {n}: missing heading")
            continue
        if len(heading) > 80:
            errors.append(f"section {n}: heading is {len(heading)} characters. A "
                          f"heading, not a sentence — keep it under 80.")
        key = heading.lower()
        if key in seen:
            errors.append(f"section {n}: heading {heading!r} duplicates section "
                          f"{seen[key]}")
        else:
            seen[key] = n

    # 3. IMRaD order.
    last_phase, last_heading = None, ""
    for section in sections:
        phase = phase_of(section.get("heading"))
        if not phase:
            continue
        rank = _PHASE_ORDER[phase]
        if last_phase is not None and rank < last_phase:
            errors.append(
                f"section {section.get('number')} ({section.get('heading')!r}) comes "
                f"after {last_heading!r} and belongs before it. The order is title, "
                f"abstract, introduction, methods, results, discussion, conclusions, "
                f"declarations.")
        else:
            last_phase, last_heading = rank, section.get("heading")

    # 4. Word budgets.
    total = 0
    for section in sections:
        n = section.get("number")
        budget = section.get("words")
        if not isinstance(budget, int) or budget <= 0:
            errors.append(f"section {n}: missing or non-positive `words` budget. "
                          f"Every section is planned to a length, because the "
                          f"journal's total is fixed and the sections have to share "
                          f"it.")
            continue
        total += budget
    if word_limit and total > word_limit:
        errors.append(
            f"the section budgets total {total:,} words against a limit of "
            f"{word_limit:,}. Cut a claim rather than shaving every section: a plan "
            f"that fits only after compression produces prose that has to be read "
            f"twice.")

    # 5. Evidence exists.
    known_evidence = set(str(i) for i in (evidence_ids or ()))
    if known_evidence:
        for section in sections:
            n = section.get("number")
            for eid in section.get("evidence") or []:
                if str(eid) not in known_evidence:
                    errors.append(
                        f"section {n}: rests on evidence {eid!r}, which the frozen "
                        f"evidence does not hold. Every number in this paper comes "
                        f"from the analysis, not from memory.")

    # 6. The argument map is inherited.
    if argument_claims is not None:
        planned = {str(c.get("id")): c for c in argument_claims if c.get("id")}
        placed = {}
        for section in sections:
            n = section.get("number")
            for cid in section.get("claims") or []:
                cid = str(cid)
                if cid not in planned:
                    errors.append(
                        f"section {n}: claim {cid!r} is not in the argument map. The "
                        f"map owns what this paper claims; the outline places those "
                        f"claims and invents none.")
                elif cid in placed:
                    errors.append(
                        f"section {n}: claim {cid!r} is already placed in section "
                        f"{placed[cid]}. A claim made twice reads as two claims.")
                else:
                    placed[cid] = n
        for cid, claim in planned.items():
            if cid not in placed:
                errors.append(
                    f"claim {cid!r} ({str(claim.get('claim'))[:60]}) is in the "
                    f"argument map and no section makes it.")

    # 7. Paragraph plans.
    #
    # This is the gate the whole prose contract rests on. A paragraph that cannot be
    # given a topic sentence at plan time is a paragraph with no claim, and it will be
    # written anyway unless something refuses it here.
    for section in sections:
        n = section.get("number")
        plans = section.get("paragraphs") or []
        if not plans:
            errors.append(
                f"section {n}: no paragraph plan. Every section is planned paragraph "
                f"by paragraph, and every paragraph declares the one claim it makes.")
            continue
        for i, para in enumerate(plans, start=1):
            topic = str(para.get("topic") or "").strip()
            if not topic:
                errors.append(
                    f"section {n}, paragraph {i}: no topic sentence. Write the "
                    f"sentence the paragraph opens on. If you cannot, the paragraph "
                    f"has no claim and does not belong in the paper.")
                continue
            if len(topic.split()) < 4:
                errors.append(
                    f"section {n}, paragraph {i}: the topic sentence is "
                    f"{len(topic.split())} words. That is a label, not a claim.")
            if topic.rstrip().endswith("?"):
                warnings.append(
                    f"section {n}, paragraph {i}: the topic sentence is a question. "
                    f"A paragraph opens on what it is going to show, not on what it "
                    f"is going to ask.")

    return OutlineReport(passed=not errors, errors=errors, warnings=warnings)
