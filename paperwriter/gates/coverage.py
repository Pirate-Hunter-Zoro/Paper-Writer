"""Evidence coverage — refuse to draft on a foundation that is not there.

The first line of defence against a paper that asserts more than it can show. After
the evidence stage freezes a cited reference, this gate checks that the frozen facts
actually cover the claims the plan intends to make. Below the configured floor the
project parks and gathers more rather than drafting a Results section on numbers
nobody has.

Coverage is deliberately a blunt, deterministic measure: for each intended claim, is
there at least one evidence item that could support it? Whether the support is
*adequate* is a judgement call for the review pass; this is the cheap arithmetic floor
beneath it, and it needs no model to test.

**How a claim is matched to evidence.** Two ways, and the second one exists because
the first one is not always available.

A claim declares the evidence ids it rests on. If those ids exist in the frozen
evidence, the claim is covered and nothing further is asked. That is the normal path,
it is exact, and it is what the planner produces.

A claim with no declared ids falls back to naming. This is the path a job prompt takes:
the human writes claims as sentences, before any id exists. So the fallback measures
what SHARE of the claim's identifying words appear somewhere in the evidence, and calls
the claim covered above `_TOKEN_SHARE`.

A share, not all of them, and that is the correction that makes this gate usable.
Requiring every identifying word is reachable for a two-word entity name and
unreachable for a sentence: "The embedded representation discriminates better than the
feature representation on the held-out split" names seven identifying things, and
evidence that holds six of them plainly supports it. Demanding the seventh — the verb
"discriminates", which an evidence item would phrase as "AUC" — fails a perfectly
covered claim, and a coverage gate that reports 0% on good evidence is a gate that gets
switched off.
"""

import re
from dataclasses import dataclass

from .. import config

# Words that carry no identifying weight in a claim.
_STOP = {"the", "a", "an", "and", "or", "of", "in", "on", "for", "with", "to",
         "is", "are", "was", "were", "be", "been", "that", "this", "these",
         "those", "than", "then", "from", "by", "at", "as", "its", "their",
         "we", "our", "study", "paper", "analysis", "results", "shows", "show",
         "showed", "found", "finding", "findings", "which", "when", "more",
         "less", "most", "least", "also", "not", "no", "but"}


def _haystack(item):
    """Everything about one evidence item that a claim could name."""
    parts = [str(item.get(k, "")) for k in ("id", "label", "statement", "source",
                                            "category", "metric")]
    parts += [str(v) for v in (item.get("values") or [])]
    return " ".join(parts)


def _names(text, needle):
    """Whether `text` contains `needle` as a whole word or phrase."""
    return re.search(r"(?<![\w-])" + re.escape(needle) + r"(?![\w-])",
                     text, re.IGNORECASE) is not None


def _identifying_tokens(claim):
    """The words of a claim that actually identify what it is about."""
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*", claim)
    return [w for w in words if len(w) >= 4 and w.lower() not in _STOP]


# What share of a claim's identifying words the evidence has to name. Two thirds: high
# enough that a claim about something the evidence does not contain fails, low enough
# that the verb and one noun can be phrased differently without failing a claim the
# evidence plainly supports.
_TOKEN_SHARE = 0.6

# And a floor under that, so a two-word claim cannot be covered by one incidental word.
_TOKEN_FLOOR = 2


def _covered_by(evidence_text, items, claim):
    """Whether the frozen evidence covers one claim.

    Declared ids first, because that is exact. Failing that, what share of the claim's
    identifying words the evidence names."""
    declared = [str(i) for i in (claim.get("evidence") or []) if str(i).strip()]
    if declared:
        known = {str(item.get("id")) for item in items}
        return all(i in known for i in declared)

    statement = str(claim.get("claim") or claim.get("statement") or "").strip()
    if not statement:
        return False
    if any(_names(_haystack(item), statement) for item in items):
        return True
    tokens = _identifying_tokens(statement)
    if not tokens:
        return False
    hits = sum(1 for token in tokens if _names(evidence_text, token))
    if len(tokens) == 1:
        return hits == 1
    return hits >= max(_TOKEN_FLOOR, round(len(tokens) * _TOKEN_SHARE))


@dataclass
class CoverageReport:
    total: int
    covered: int
    ratio: float
    missing: list           # claims with no covering evidence
    passed: bool


def check(evidence, claims):
    """Fraction of intended claims with at least one covering evidence item, gated
    against config.EVIDENCE_COVERAGE_MIN. Returns a CoverageReport.

    `claims` is a list of claim dicts (`{"claim": ..., "evidence": [...]}`) or a list
    of plain strings, because the planner emits the first and an early prompt may
    supply the second."""
    normalised = []
    for entry in claims or []:
        if isinstance(entry, dict):
            if str(entry.get("claim") or entry.get("statement") or "").strip():
                normalised.append(entry)
        elif str(entry).strip():
            normalised.append({"claim": str(entry).strip()})

    items = (evidence or {}).get("items", []) or []
    evidence_text = " ".join(_haystack(item) for item in items)

    missing = [c for c in normalised if not _covered_by(evidence_text, items, c)]
    total = len(normalised)
    covered = total - len(missing)
    ratio = 1.0 if total == 0 else covered / total

    return CoverageReport(
        total=total, covered=covered, ratio=round(ratio, 4),
        missing=[str(c.get("claim") or c.get("statement")) for c in missing],
        passed=ratio >= config.EVIDENCE_COVERAGE_MIN)
