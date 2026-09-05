"""The argument-map gate — arithmetic over what the paper says it will claim.

A paper is bought for its argument. Nothing downstream ever asks for one: a section
outline optimises for structure, a draft optimises for prose, and both will happily
produce a beautifully organised manuscript that never states what it found. So the
argument is planned up front, claim by claim, and this module checks that the plan is
an argument rather than a list of things that happened.

Every check here is counting. No model, no I/O, no judgement — which matters, because
this is the gate a claim map has to clear before a word is drafted, and a gate that
needed judgement would be a second model arguing with the first.

What it enforces, and why each one exists:

  * **Every claim rests on evidence.** A claim with no evidence id is an assertion.
    This is the only check here that is never waived.
  * **Every evidence item is used.** Evidence gathered and never cited means the
    gathering stage went looking for the wrong things, or the argument dropped a
    finding that cost real compute to produce.
  * **There is exactly one headline claim.** A paper with three headline claims has
    three papers in it, and reviewers will say so. A paper with none has a reader who
    finishes the abstract not knowing what was found.
  * **The claim types vary.** A map of nothing but descriptive claims is a report,
    not a paper: something has to be compared, explained, or qualified. And a map with
    no limitation claim is a paper whose Discussion will be written defensively at the
    last minute.
  * **Nothing is claimed twice.** The same finding stated as two claims becomes two
    paragraphs saying one thing, and a reader who wonders what the difference is.
  * **Every claim is falsifiable enough to check.** A claim that names no evidence and
    no comparison is a sentence of throat-clearing that will be drafted as a paragraph.

**On the limitation claim specifically.** It is required, and requiring it is not
box-ticking. A limitation planned at argument time is one the paper can answer; a
limitation discovered at submission is one the paper has to concede. The manuscript
this harness was built from spent two review rounds on a limitation that had been
visible in the study design from the first week.
"""

from collections import Counter
from dataclasses import dataclass, field

from .. import config

# What a claim DOES. Kept to six and deliberately unambiguous, because this is a label
# assigned dozens of times and a taxonomy with fine distinctions collects everything in
# whichever bin is easiest to justify.
KINDS = ("descriptive", "comparative", "mechanistic", "methodological",
         "limitation", "implication")

# The one the paper is about. Exactly one.
HEADLINE = "headline"

UNSET = "(unset)"


@dataclass
class ArgumentReport:
    passed: bool
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def kind_of(claim):
    """One claim's declared kind, normalised. `UNSET` when absent or unrecognised."""
    raw = str(claim.get("kind") or "").strip().lower()
    return raw if raw in KINDS else UNSET


def _text(claim):
    return str(claim.get("claim") or claim.get("statement") or "").strip()


def _normalised(text):
    """A claim's text reduced to what makes two claims the same claim."""
    return " ".join(w for w in text.lower().split()
                    if w.strip(".,;:()") not in
                    {"the", "a", "an", "of", "in", "is", "are", "was", "were",
                     "that", "this", "and", "to", "for", "on", "with"})


def stats(claims, evidence_ids):
    """The counts every check below reads. Separated so a report can show them even
    when the map passes — a passing map with one comparative claim is worth seeing."""
    kinds = Counter(kind_of(c) for c in claims)
    used = set()
    for claim in claims:
        used.update(str(e) for e in (claim.get("evidence") or []))
    known = {str(e) for e in (evidence_ids or ())}
    return {
        "claims": len(claims),
        "kinds": dict(kinds),
        "headline": sum(1 for c in claims if c.get("headline")),
        "unsupported": sum(1 for c in claims if not (c.get("evidence") or [])),
        "evidence_used": len(used & known) if known else len(used),
        "evidence_total": len(known),
        "evidence_unused": sorted(known - used) if known else [],
    }


def check(claims, evidence_ids=None, sections=None):
    """Validate a paper's argument map. Returns an ArgumentReport.

    `evidence_ids` is what the frozen evidence holds. `sections` is the planned
    section headings, so a claim can be checked for landing somewhere that exists."""
    claims = [c for c in (claims or []) if isinstance(c, dict) and _text(c)]
    if not claims:
        return ArgumentReport(passed=False,
                              errors=["the argument map has no claims"])

    known = {str(e) for e in (evidence_ids or ())}
    counts = stats(claims, known)
    errors, warnings = [], []

    # 1. Ids, present and distinct. Everything downstream addresses a claim by id.
    seen_ids = {}
    for claim in claims:
        cid = str(claim.get("id") or "").strip()
        if not cid:
            errors.append(f"claim {_text(claim)[:60]!r} has no id. The outline places "
                          f"claims by id and cannot place one that has none.")
        elif cid in seen_ids:
            errors.append(f"claim id {cid!r} is used twice.")
        else:
            seen_ids[cid] = claim

    # 2. Every claim rests on evidence.
    for claim in claims:
        cid = claim.get("id") or _text(claim)[:40]
        evidence = [str(e) for e in (claim.get("evidence") or []) if str(e).strip()]
        if not evidence:
            errors.append(
                f"claim {cid!r} rests on no evidence. Name the evidence ids that "
                f"support it, or drop the claim — a claim with nothing under it "
                f"becomes a paragraph of assertion.")
            continue
        if known:
            unknown = [e for e in evidence if e not in known]
            if unknown:
                errors.append(
                    f"claim {cid!r} cites evidence the frozen reference does not "
                    f"hold: {', '.join(unknown[:5])}.")

    # 3. Every evidence item is used.
    if known and counts["evidence_unused"]:
        unused = counts["evidence_unused"]
        warnings.append(
            f"{len(unused)} evidence item(s) are used by no claim: "
            f"{', '.join(unused[:8])}. Either the argument dropped a finding, or the "
            f"evidence stage gathered something this paper does not need.")

    # 4. Exactly one headline claim.
    if counts["headline"] == 0:
        errors.append(
            "no claim is marked `headline`. Exactly one claim is what this paper is "
            "about, and the abstract, the title and the conclusion all say it.")
    elif counts["headline"] > 1:
        headlines = [str(c.get("id")) for c in claims if c.get("headline")]
        errors.append(
            f"{counts['headline']} claims are marked `headline` "
            f"({', '.join(headlines[:5])}). A paper makes one central claim. Two is "
            f"two papers, and a reviewer will say so.")

    # 5. Kinds are declared, and they vary.
    unset = [str(c.get("id")) for c in claims if kind_of(c) == UNSET]
    if unset:
        errors.append(
            f"{len(unset)} claim(s) declare no kind ({', '.join(unset[:5])}). One of: "
            f"{', '.join(KINDS)}.")
    kinds_present = {k for k in counts["kinds"] if k != UNSET}
    if len(claims) >= 4 and len(kinds_present) < 2:
        errors.append(
            f"every claim is {next(iter(kinds_present), 'the same kind')}. A paper "
            f"that only describes is a report. Something has to be compared, "
            f"explained, or qualified.")
    if len(claims) >= 4 and "limitation" not in kinds_present:
        errors.append(
            "no claim is a limitation. A limitation planned now is one the paper can "
            "answer; a limitation found at submission is one it has to concede.")

    # 6. Nothing claimed twice.
    by_text = {}
    for claim in claims:
        key = _normalised(_text(claim))
        if not key:
            continue
        if key in by_text:
            errors.append(
                f"claims {by_text[key]!r} and {str(claim.get('id'))!r} say the same "
                f"thing. Two paragraphs will be written for one finding, and a reader "
                f"will spend a minute looking for the difference.")
        else:
            by_text[key] = str(claim.get("id"))

    # 7. Claims land in sections that exist.
    if sections:
        headings = {str(h).strip().lower() for h in sections}
        for claim in claims:
            where = str(claim.get("section") or "").strip().lower()
            if where and where not in headings:
                errors.append(
                    f"claim {str(claim.get('id'))!r} is assigned to section "
                    f"{claim.get('section')!r}, which the plan does not have.")

    # 8. Section load. A section carrying one claim is a paragraph.
    if sections:
        load = Counter(str(c.get("section") or "").strip().lower() for c in claims)
        for heading in sections:
            key = str(heading).strip().lower()
            if key in load and load[key] < config.SECTION_MIN_CLAIMS:
                warnings.append(
                    f"section {heading!r} carries {load[key]} claim(s); the floor is "
                    f"{config.SECTION_MIN_CLAIMS}. Fold it into a neighbour or give "
                    f"it the claim it is missing.")

    return ArgumentReport(passed=not errors, errors=errors, warnings=warnings,
                          stats=counts)
