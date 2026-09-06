"""The support-ladder gate — does everything in the paper serve what the paper is for?

Every other gate here checks that a piece of the paper is well made. This one checks
that the piece belongs. It is the only gate that can refuse a section which is
correct, well written, fully evidenced, and beside the point.

The ladder has three rungs and each one is checked against the one above it:

    points   (1-3)      what the paper is FOR
      ^ serves
    claims   (many)     what the paper ASSERTS
      ^ rests on
    evidence (many)     what the analysis PRODUCED

`gates.claims` already owns the bottom join: every claim rests on evidence that
exists. This module owns the top one.

**The failure it was written from.** A finished manuscript had three stated
objectives, which were three things the analysis had done rather than three things the
paper argued. Two of them were support for the first — an encoder sweep showing the
headline null was not an artifact, and an ablation showing why the two arms tied — and
the genuinely separate question was buried sixth of nine subsections with its
motivation stated nowhere. Every gate passed. Every number traced. The prose was
clean. And a reader who stopped after the Results could not say what the paper
claimed, because nothing in the pipeline had ever asked.

Along the way the same manuscript carried a whole supplement section, with a rubric,
two verbatim prompts, four worked examples and a re-judging experiment, in service of
a null result about a weighting scheme on top of a predictor that was not competitive.
It was complete, correct and irrelevant. Nothing refused it, because nothing was
counting what the paper was for.

**Why a point is not a claim.** A claim is one sentence the paper asserts and can
defend from a named evidence id. A point is what several claims add up to, and it is
what a reader repeats to a colleague a week later. A paper with six claims and no
points is a list of findings. A paper with six points is six papers.

**Why the ceiling is three and the floor is one.** One is the ordinary case and the
degenerate case at once, exactly as a one-paper project is a degenerate programme: the
old `headline` boolean was this gate with the count fixed at one. Two is common and is
usually a comparison plus what the comparison rules out. Three is the most a reader
carries. Four is the count at which the author has stopped choosing.

**What is allowed not to serve a point, and why the allowance is bounded.** A paper
cannot be all argument. The cohort has to be described before anything can be claimed
about it, and a venue's checklist requires rows that serve the venue rather than the
reader. Those are `setup` and `reporting`, they are declared rather than inferred, and
their share is capped — because an unbounded exemption turns the ladder into
decoration, and "setup" is the easiest label in the world to reach for.

The cap on words is the check that would have caught the real failure. A graph check
asks whether every claim has a parent, which a determined writer satisfies by
attaching claims loosely. A budget check asks how much of the paper's length is spent
on material that serves nothing, and that number cannot be argued with.

**On the name.** This is `ladder.py` and not `support.py` because `tests/support.py`
is the fixture module every test imports, and `from paperwriter.gates import support`
shadows it silently — four unrelated prose tests failed with an AttributeError on the
fixture the first time this module was called that. The concept is the support ladder
either way.

No models, no I/O. Arithmetic and set logic over two lists.
"""

from collections import Counter
from dataclasses import dataclass, field

from .. import config
from .claims import KINDS, kind_of                       # noqa: F401  (KINDS re-export)
from .structure import phase_of

# What a claim may do INSTEAD of serving a point. Two, deliberately, and neither of
# them is a place to put an argument.
#
#   setup     — what a reader must know before any point can be made. The cohort, the
#               data source, the temporal design. Not a finding.
#   reporting — required by the venue or a reporting checklist and by nothing else.
#               Declarations, data availability, the registration statement.
#
# There is deliberately no `validity` role. A check that would have undermined a point
# and did not SERVES that point, and it should say which one — often more than one.
# Given a role instead, a validity section drifts to the front of the Results, where
# the manuscript this gate came from had put three of them, ahead of its own finding.
ROLES = ("setup", "reporting")

UNSET = "(unset)"


@dataclass
class SupportReport:
    passed: bool
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def point_text(point):
    return str(point.get("point") or point.get("statement") or "").strip()


def points_of(document):
    """The declared points of a plan, argument map or paper record."""
    raw = document.get("points") if isinstance(document, dict) else None
    return [p for p in (raw or []) if isinstance(p, dict) and point_text(p)]


def serves_of(claim):
    """The point ids one claim serves, as a list. Accepts a string or a list.

    A single point is written as a string far more often than as a one-element list,
    and refusing the string form buys nothing except a rejected proposal."""
    raw = claim.get("serves")
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    return [str(x).strip() for x in raw if str(x).strip()]


def role_of(claim):
    """One claim's declared role, normalised. "" when it declares none."""
    raw = str(claim.get("role") or "").strip().lower()
    return raw if raw in ROLES else ("" if not raw else UNSET)


def legacy_points(claims):
    """One point synthesised from a pre-ladder claim map's `headline` claim.

    A migration, not a fallback to live on. Claim maps written before the ladder
    existed mark exactly one claim `headline` and declare no points, and refusing
    those outright would strand state that is otherwise fine. Everything else in this
    module treats the result as an ordinary one-point paper, which it is.

    Returns [] when there is no headline claim to build one from, and the caller then
    gets the ordinary "no points declared" error rather than a silent pass."""
    for claim in claims or []:
        if claim.get("headline") and str(claim.get("claim")
                                         or claim.get("statement") or "").strip():
            return [{"id": "p.1",
                     "point": str(claim.get("claim") or claim.get("statement")),
                     "derived_from": str(claim.get("id") or "")}]
    return []


def migrated(points, claims):
    """(points, claims) with a pre-ladder map filled in. Returns new lists.

    A claim map written before the ladder existed marks one claim `headline`, declares
    no points, and gives no claim a `serves`. Deriving the point without also deriving
    the serves would refuse every one of those maps for a field that did not exist
    when they were written, so the two halves of the migration travel together: one
    point from the headline claim, and every claim serving it.

    Declared points are returned untouched, and a claim that declares neither `serves`
    nor `role` under declared points stays an error — there the field exists and was
    skipped, which is a different thing from a map that predates it.

    Accepts an already-derived point set as well as an empty one, because the stages
    derive once and then hand the result down. What decides whether the claims get
    filled is whether the points were DERIVED, not whether the caller passed any."""
    derived = list(points) if points else legacy_points(claims)
    if not derived:
        return [], list(claims)
    if not all(p.get("derived_from") for p in derived):
        return derived, list(claims)          # somebody wrote these; nothing to fill
    pid = str(derived[0]["id"])
    filled = []
    for claim in claims:
        if serves_of(claim) or role_of(claim):
            filled.append(claim)
        else:
            filled.append(dict(claim, serves=[pid]))
    return derived, filled


def ladder(points, claims):
    """Which claims serve which point. Returns {point_id: [claim ids]}.

    Claims that declare a role appear under the role name instead, and claims that
    declare neither appear under "" — which is the set every error below is about."""
    out = {str(p.get("id")): [] for p in points}
    for role in ROLES:
        out[role] = []
    out[""] = []
    for claim in claims:
        cid = str(claim.get("id") or "")
        served = serves_of(claim)
        if served:
            for pid in served:
                out.setdefault(pid, []).append(cid)
        else:
            role = role_of(claim)
            out.setdefault(role if role in ROLES else "", []).append(cid)
    return out


def unladdered_sections(outline, claims, points):
    """The outline's sections that serve no point, with their word budgets.

    A section is laddered when at least one claim it carries serves at least one
    point. Two kinds of section are exempt.

    Front and back matter, because a title page serves the reader without asserting
    anything and a references list is not prose.

    And any section the argument map gave NO claims, because that is the map calling
    it structural — an Introduction that sets up every point without asserting one is
    the ordinary case, and counting its words as serving nothing would make the check
    fire on every well-built paper. The failure this measures is a section that
    carries findings which serve nothing, and a section with findings has claims.

    Returns (list of (heading, words), laddered_words, unladdered_words)."""
    known = {str(p.get("id")) for p in points}
    by_id = {str(c.get("id")): c for c in claims}
    exempt = {s.lower() for s in config.PARAGRAPH_EXEMPT_SECTIONS}

    unladdered, laddered_words, unladdered_words = [], 0, 0
    for section in outline.get("sections") or []:
        heading = str(section.get("heading") or "").strip()
        words = int(section.get("words") or 0)
        carried = [str(cid) for cid in (section.get("claims") or [])]
        if (not carried
                or heading.lower() in exempt
                or phase_of(heading) in ("front", "back")):
            continue
        serves_any = any(
            any(p in known for p in serves_of(by_id.get(str(cid), {})))
            for cid in carried)
        if serves_any:
            laddered_words += words
        else:
            unladdered.append((heading, words))
            unladdered_words += words
    return unladdered, laddered_words, unladdered_words


def stats(points, claims):
    rungs = ladder(points, claims)
    return {
        "points": len(points),
        "claims": len(claims),
        "per_point": {pid: len(rungs.get(pid, []))
                      for pid in (str(p.get("id")) for p in points)},
        "roles": {role: len(rungs.get(role, [])) for role in ROLES},
        "orphans": list(rungs.get("", [])),
    }


def check(points, claims, outline=None):
    """Validate the support ladder. Returns a SupportReport.

    `points` is the paper's declared points. `claims` is its claim list, each with
    either `serves` or `role`. `outline`, when supplied, adds the word-budget check,
    which is the one that measures how much of the paper serves nothing.
    """
    claims = [c for c in (claims or []) if isinstance(c, dict)]
    points = list(points or [])
    errors, warnings = [], []

    # 1. Points exist, are identified, and are sentences rather than headings.
    if not points:
        return SupportReport(
            passed=False,
            errors=["the paper declares no points. A point is what several claims add "
                    "up to and what a reader repeats a week later; without one, the "
                    "paper is a list of findings and nothing downstream can tell "
                    "which of them it is for."])

    seen = {}
    for point in points:
        pid = str(point.get("id") or "").strip()
        text = point_text(point)
        if not pid:
            errors.append(f"point {text[:50]!r} has no id. Claims name their point by "
                          f"id, and a point with none cannot be served.")
        elif pid in seen:
            errors.append(f"point id {pid!r} is used twice.")
        else:
            seen[pid] = point
        # A DERIVED point inherits its wording from the claim it was built out of, so
        # measuring its length measures that claim against a rule it never had to
        # meet. Exempted for the same reason the migration exists at all.
        if (not point.get("derived_from")
                and len(text.split()) < config.POINT_MIN_WORDS):
            errors.append(
                f"point {pid or text[:30]!r} is {len(text.split())} words. That is a "
                f"topic, not a point. Write the sentence a reader would repeat: "
                f"\"the embedding does not outperform the feature vector\", not "
                f"\"representation comparison\".")

    if len(points) < config.POINTS_MIN:
        errors.append(f"{len(points)} point(s) declared; the floor is "
                      f"{config.POINTS_MIN}.")
    if len(points) > config.POINTS_MAX:
        errors.append(
            f"{len(points)} points declared; the ceiling is {config.POINTS_MAX}. "
            f"More than that is not a paper with a spine, it is several papers "
            f"sharing a reference list, and a reader carries none of them.")

    known = set(seen)
    rungs = ladder(points, claims)
    counts = stats(points, claims)

    # 2. Every claim ladders: it serves a point, or it declares a role.
    for claim in claims:
        cid = str(claim.get("id") or str(claim.get("claim"))[:40])
        served = serves_of(claim)
        role = role_of(claim)
        if served and role:
            errors.append(
                f"claim {cid!r} both serves {', '.join(served)} and declares the role "
                f"{claim.get('role')!r}. It is one or the other: a claim that serves a "
                f"point is argument, and a claim with a role is what the argument "
                f"needs in place first.")
            continue
        if not served and not role:
            errors.append(
                f"claim {cid!r} serves no point and declares no role. Name the point "
                f"it serves, or mark it `setup` or `reporting` — or drop it, which is "
                f"the answer more often than it looks.")
            continue
        if role == UNSET:
            errors.append(
                f"claim {cid!r} declares the role {claim.get('role')!r}, which is not "
                f"one of: {', '.join(ROLES)}. There is deliberately no role for a "
                f"validity check: a check that would have undermined a point and did "
                f"not serves that point, and should name it.")
            continue
        unknown = [p for p in served if p not in known]
        if unknown:
            errors.append(
                f"claim {cid!r} serves point(s) the paper does not declare: "
                f"{', '.join(unknown[:4])}.")

    # 3. Every point is carried by enough claims to be a point.
    for pid in sorted(known):
        supporting = [c for c in claims if pid in serves_of(c)]
        if len(supporting) < config.POINT_MIN_CLAIMS:
            errors.append(
                f"point {pid!r} is served by {len(supporting)} claim(s); the floor is "
                f"{config.POINT_MIN_CLAIMS}. A point carried by one claim is that "
                f"claim, and calling it a point promises a reader more than the paper "
                f"delivers.")
            continue
        kinds = {kind_of(c) for c in supporting}
        if kinds and kinds <= {"limitation"}:
            errors.append(
                f"point {pid!r} is served only by limitation claims. A point whose "
                f"whole support is a caveat is not a finding; either the finding it "
                f"qualifies is missing from the map, or this is not a point.")

    # 4. Exactly one claim per point states it.
    for pid in sorted(known):
        headlines = [str(c.get("id")) for c in claims
                     if pid in serves_of(c) and c.get("headline")]
        if len(headlines) == 0:
            errors.append(
                f"point {pid!r} has no claim marked `headline`. One of the claims "
                f"serving a point states it outright, and that is the sentence the "
                f"abstract and the conclusions both use.")
        elif len(headlines) > 1:
            errors.append(
                f"point {pid!r} has {len(headlines)} claims marked `headline` "
                f"({', '.join(headlines[:4])}). One claim states a point; the rest "
                f"support it.")

    # 5. A headline claim serving nothing, or serving two points, is a mis-set flag
    #    rather than a structure the paper can carry.
    for claim in claims:
        if not claim.get("headline"):
            continue
        served = serves_of(claim)
        if len(served) > 1:
            errors.append(
                f"claim {str(claim.get('id'))!r} is marked `headline` and serves "
                f"{len(served)} points. The claim that states a point states one.")

    # 6. The role allowance is bounded. An unbounded one is decoration.
    role_claims = sum(counts["roles"].values())
    if claims:
        share = role_claims / len(claims)
        if share > config.ROLE_CLAIM_SHARE_MAX:
            errors.append(
                f"{role_claims} of {len(claims)} claims ({share:.0%}) declare a role "
                f"rather than serving a point; the ceiling is "
                f"{config.ROLE_CLAIM_SHARE_MAX:.0%}. At this share the ladder is "
                f"decoration: most of the paper is doing something other than making "
                f"its case.")

    # 7. The word budget, when there is an outline to measure.
    if outline:
        unladdered, laddered_words, unladdered_words = unladdered_sections(
            outline, claims, points)
        total = laddered_words + unladdered_words
        counts["laddered_words"] = laddered_words
        counts["unladdered_words"] = unladdered_words
        counts["unladdered_sections"] = [h for h, _ in unladdered]
        if total:
            share = unladdered_words / total
            counts["unladdered_share"] = round(share, 4)
            worst = ", ".join(f"{h} ({w:,}w)" for h, w in
                              sorted(unladdered, key=lambda x: -x[1])[:4])
            if share > config.UNLADDERED_WORDS_MAX:
                errors.append(
                    f"{unladdered_words:,} of {total:,} planned words ({share:.0%}) "
                    f"sit in sections that serve no point; the ceiling is "
                    f"{config.UNLADDERED_WORDS_MAX:.0%}. The largest are: {worst}. "
                    f"Either they serve a point nobody wrote down, or they belong in "
                    f"supplementary material rather than in the paper.")
            elif share > config.UNLADDERED_WORDS_WARN:
                warnings.append(
                    f"{share:.0%} of planned words serve no point ({worst}). Under "
                    f"the ceiling and worth a look: this is the share that grows "
                    f"quietly, one complete and irrelevant section at a time.")

    return SupportReport(passed=not errors, errors=errors, warnings=warnings,
                         stats=counts)


def brief(points, claims):
    """The ladder as a few lines, for a log or a report. No judgement, just the shape."""
    rungs = ladder(points, claims)
    by_id = {str(c.get("id")): c for c in claims}
    lines = []
    for point in points:
        pid = str(point.get("id"))
        served = rungs.get(pid, [])
        lines.append(f"{pid}: {point_text(point)}")
        for cid in served:
            claim = by_id.get(cid, {})
            marker = "  [states it]" if claim.get("headline") else ""
            lines.append(f"    {cid} ({kind_of(claim)}){marker}: "
                         f"{str(claim.get('claim') or '')[:96]}")
        if not served:
            lines.append("    (nothing serves this point)")
    for role in ROLES:
        ids = rungs.get(role, [])
        if ids:
            lines.append(f"{role}: {', '.join(ids)}")
    orphans = rungs.get("", [])
    if orphans:
        lines.append(f"serving nothing: {', '.join(orphans)}")
    return "\n".join(lines)
