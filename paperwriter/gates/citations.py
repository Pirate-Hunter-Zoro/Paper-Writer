"""Citations resolve, and claims that need one have one.

Three failures, in rising order of how much they cost:

  * **A marker with no reference.** `[27]` in a manuscript with 24 references. Caught
    by a person only at proof stage, when the numbering has already been renumbered
    once and nobody is sure which source was meant.
  * **A reference nobody cites.** It sat in the library folder, it looked relevant, it
    never made it into a sentence. Harmless to a reader and embarrassing to an author.
  * **A borrowed claim with no citation.** A sentence that says what prior work found,
    what a guideline recommends, or what is established in the field, carrying no
    marker. This is the one that matters, and it is the only one here the gate has to
    guess at.

The third is a heuristic and is reported as such: it flags sentences whose *shape* is
a claim about somebody else's work — "prior studies have shown", "the consensus
definition requires", "X is associated with Y in the literature" — that carry no
citation marker. A false positive costs one editorial pass. A false negative is a
manuscript asserting somebody else's finding as its own.

Markers are recognised in the three styles a manuscript here uses: numbered `[12]`,
author-year `(Smith et al., 2024)`, and pandoc `@smith2024`. Which style a project
uses is not configured — the gate reads whichever appear, because a manuscript that
mixes two styles has a defect this gate should report rather than a setting it should
be told about.
"""

import re
from dataclasses import dataclass, field

from . import prose

_NUMERIC_MARKER = re.compile(r"\[(\d+(?:\s*[,–-]\s*\d+)*)\]")
_PANDOC_MARKER = re.compile(r"(?<![\w@])@([A-Za-z][\w:.#$%&+?<>~/-]*)")
_AUTHOR_YEAR = re.compile(
    r"\(\s*[A-Z][A-Za-z'’-]+(?:\s+(?:et\s+al\.?|and\s+[A-Z][A-Za-z'’-]+))?"
    r"\s*,?\s*(?:19|20)\d{2}[a-z]?\s*\)")
_NARRATIVE_CITE = re.compile(
    r"[A-Z][A-Za-z'’-]+\s+(?:et\s+al\.?|and\s+[A-Z][A-Za-z'’-]+)\s*"
    r"[\(\[]\s*(?:19|20)\d{2}")

# Sentence shapes that assert somebody else's finding.
_BORROWED = (
    r"prior (?:work|studies|research|literature)",
    r"previous (?:work|studies|research|reports?)",
    r"(?:has|have) been (?:shown|reported|demonstrated|described|associated|"
    r"validated|proposed)",
    r"(?:is|are) (?:widely|well|commonly|generally) (?:known|accepted|established|"
    r"reported|used)",
    r"(?:the|a) (?:consensus|standard|conventional|accepted|established) "
    r"(?:definition|approach|criterion|criteria|guideline)",
    r"(?:studies|trials|analyses|authors|investigators) (?:have |had )?"
    r"(?:found|reported|shown|concluded|estimated)",
    r"according to",
    r"(?:guidelines?|recommendations?) (?:recommend|require|state|advise)",
    r"it (?:is|has been) (?:estimated|reported|suggested|proposed) that",
    r"as (?:reported|described|defined|shown) (?:by|in)",
)
_BORROWED_RE = re.compile("|".join(_BORROWED), re.IGNORECASE)

# ...unless the sentence says it is talking about THIS paper.
_OUR_WORK = re.compile(
    r"\b(?:we|our|this (?:study|paper|analysis|work|manuscript|report)|the present "
    r"(?:study|analysis|work))\b", re.IGNORECASE)


@dataclass
class CitationDefect:
    kind: str                 # "unresolved", "uncited", "missing"
    detail: str
    anchor: str = ""          # the sentence to repair, when there is one


@dataclass
class CitationReport:
    markers: int              # distinct citation keys used in the text
    references: int           # entries in the reference list
    unresolved: list = field(default_factory=list)   # keys with no reference
    uncited: list = field(default_factory=list)      # references never cited
    missing: list = field(default_factory=list)      # CitationDefect, borrowed claims
    styles: list = field(default_factory=list)       # which marker styles appeared
    passed: bool = True
    reasons: list = field(default_factory=list)

    def brief(self):
        return (f"{self.markers} citation key(s) against {self.references} "
                f"reference(s); {len(self.unresolved)} unresolved, "
                f"{len(self.uncited)} uncited, {len(self.missing)} claim(s) "
                f"needing a source")


def keys_used(text):
    """Every citation key the text refers to, and which styles it used.

    Returns (keys, styles). Numeric markers expand their ranges: `[3-5]` is three
    keys, and a manuscript whose reference list stops at four should be told about
    five."""
    body = prose.strip_structure(text)
    keys, styles = set(), set()

    for match in _NUMERIC_MARKER.finditer(body):
        styles.add("numeric")
        for part in re.split(r"\s*,\s*", match.group(1)):
            bounds = re.split(r"\s*[–-]\s*", part)
            if len(bounds) == 2 and all(b.strip().isdigit() for b in bounds):
                lo, hi = int(bounds[0]), int(bounds[1])
                if 0 < hi - lo < 200:
                    keys.update(str(n) for n in range(lo, hi + 1))
                    continue
            if part.strip().isdigit():
                keys.add(part.strip())

    for match in _PANDOC_MARKER.finditer(body):
        styles.add("pandoc")
        keys.add(match.group(1))

    if _AUTHOR_YEAR.search(body) or _NARRATIVE_CITE.search(body):
        styles.add("author-year")
        for match in _AUTHOR_YEAR.finditer(body):
            keys.add(" ".join(match.group(0).strip("()").split()))

    return keys, sorted(styles)


def _has_marker(sentence):
    return bool(_NUMERIC_MARKER.search(sentence) or _PANDOC_MARKER.search(sentence)
                or _AUTHOR_YEAR.search(sentence) or _NARRATIVE_CITE.search(sentence))


def borrowed_without_source(text):
    """Sentences asserting somebody else's finding with no citation on them."""
    out = []
    for sentence in prose.sentences(text):
        if _has_marker(sentence):
            continue
        match = _BORROWED_RE.search(sentence)
        if not match:
            continue
        if _OUR_WORK.search(sentence):
            continue
        out.append(CitationDefect(
            kind="missing",
            detail=f"this sentence reports somebody else's finding "
                   f"(\"{match.group(0)}\") and carries no citation. Cite the source "
                   f"or rewrite it as a claim this paper's own evidence supports.",
            anchor=sentence))
    return out


def check(text, references=None, require_sources=True):
    """Gate a section's citations. Returns a CitationReport.

    `references` is the project's reference list: a mapping of key to entry, or a
    list of keys. Absent, the resolve/uncite checks are skipped and only the
    borrowed-claim heuristic runs — which is the right behaviour for a section drafted
    before the bibliography exists.

    `uncited` is reported but never blocks at section level. A reference cited only in
    the Discussion is not uncited when the Methods is being gated; that check belongs
    to the whole manuscript, and `check_manuscript` is where it blocks."""
    used, styles = keys_used(text)
    known = set()
    if isinstance(references, dict):
        known = {str(k) for k in references}
    elif references:
        known = {str(k) for k in references}

    unresolved = sorted(used - known) if known else []
    missing = borrowed_without_source(text) if require_sources else []

    reasons = []
    if unresolved:
        reasons.append(
            f"{len(unresolved)} citation marker(s) do not resolve to a reference: "
            f"{', '.join(unresolved[:8])}. A marker with no entry behind it is a "
            f"source the reader cannot check.")
    if missing:
        reasons.append(
            f"{len(missing)} sentence(s) report prior work with no citation.")
    if len(styles) > 1:
        reasons.append(
            f"this section mixes {len(styles)} citation styles ({', '.join(styles)}). "
            f"Pick the one the target journal wants and use it throughout.")

    return CitationReport(markers=len(used), references=len(known),
                          unresolved=unresolved, uncited=[], missing=missing,
                          styles=styles, passed=not reasons, reasons=reasons)


def check_manuscript(text, references):
    """The whole-manuscript pass, where "cited nowhere" is finally a real defect.

    Run once the manuscript is assembled. Everything `check` reports plus the
    uncited-reference sweep, which cannot be run against one section because a
    reference cited only in the Discussion is legitimately absent from the Methods."""
    report = check(text, references)
    used, _ = keys_used(text)
    known = {str(k) for k in (references or {})}
    report.uncited = sorted(known - used)
    if report.uncited:
        report.reasons.append(
            f"{len(report.uncited)} reference(s) are never cited: "
            f"{', '.join(report.uncited[:8])}. Cite them or remove them.")
        report.passed = False
    return report
