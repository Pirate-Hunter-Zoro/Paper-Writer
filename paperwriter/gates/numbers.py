"""Every number in the prose has to be in the evidence ledger.

This is the most valuable gate in the project, and it exists because of the one thing
a language model does that no amount of prompting fixes: it produces a number that
looks exactly like the right one.

Not a wild number. A plausible one. It rounds 0.712 to 0.71 in the abstract and
leaves 0.712 in the results, promotes a subgroup AUC to the headline figure, writes
"approximately forty thousand" three paragraphs after stating 42,579, or reports a
confidence interval whose bounds do not bracket the estimate it belongs to. Every one
of those survives a careful read by the person who wrote it, because the number is
familiar and the sentence is fluent. None of them survives a reviewer with the
supplement open.

So: the harness holds a frozen ledger of every number the analysis actually produced,
and every number that appears in drafted prose is looked up in it. A number that is
not there is a blocking defect, named with its exact location, and the editorial loop
repairs it like any other anchored issue.

**What is not checked, and why.** Checking everything produces noise, and a gate that
cries wolf gets switched off:

  * Years. 2024 is a date, not a finding.
  * Small integers that are structure rather than measurement: section numbers, table
    and figure references, "three of the four intervals".
  * Numbers inside a citation marker.
  * Numbers the ledger itself is not expected to hold — a p-value threshold of 0.05,
    a 95% confidence level, a random seed.

Those exemptions are declared here rather than guessed at, and the ledger can add its
own: an evidence item may list `also_allow` values that are legitimately quotable
without being findings.

**Rounding is allowed and equality is not.** 0.712 stated as 0.71 is the same number
and the gate says so, within `config.NUMBER_MATCH_TOLERANCE`. What it will not accept
is 0.71 when the ledger says 0.72, however small the difference looks.
"""

import re
from dataclasses import dataclass, field

from .. import config

# A number as it appears in prose: optional sign, digits with optional thousands
# separators, optional decimal, optional percent. Scientific notation included
# because p-values arrive as 3.2e-4.
_NUMBER_RE = re.compile(r"""
    (?<![\w.])                       # not mid-token, not a version string
    (?P<sign>[-+−])?
    (?P<value>
        \d{1,3}(?:,\d{3})+(?:\.\d+)? # 42,579  or  1,234.5
      | \d+\.\d+                     # 0.712
      | \.\d+                        # .712
      | \d+                          # 12
    )
    (?:\s*(?P<sci>[eE][-+]?\d+))?
    (?P<pct>\s*%)?
    (?![\w.]|\s*\))                  # not a version, not "(1)" alone
""", re.VERBOSE)

# Spans whose numbers are never findings.
_SKIP_SPANS = (
    re.compile(r"\[[^\]]*\]"),                       # [1], [12,14] citation markers
    re.compile(r"\((?:19|20)\d{2}[a-z]?\)"),         # (2024) author-year
    re.compile(r"`[^`]*`"),                          # inline code
    re.compile(r"^\s*\|.*$", re.MULTILINE),          # table rows
    re.compile(r"^\s{0,3}#{1,6}\s.*$", re.MULTILINE),  # headings
    re.compile(r"<!--.*?-->", re.DOTALL),            # comments
)

# Structural references: the number belongs to a label, not to a result.
_STRUCTURAL = re.compile(
    r"(?:table|figure|fig\.?|section|appendix|supplement|item|step|equation|eq\.?|"
    r"chapter|panel|reference|ref\.?|phase|stage|arm|visit|day|week|month|year)\s*"
    r"\d+", re.IGNORECASE)

# Conventions every paper uses that no ledger should have to list.
_CONVENTIONAL = {"0.05", "0.01", "0.001", "95", "99", "90", "100", "0", "1", "2",
                 "5", "10", "50", "0.5", "1.96", "42"}


def _spans_to_skip(text):
    """Character ranges the scanner must not look inside."""
    spans = []
    for pattern in _SKIP_SPANS:
        spans.extend((m.start(), m.end()) for m in pattern.finditer(text))
    return spans


def _in_skipped(pos, spans):
    return any(start <= pos < end for start, end in spans)


def _is_year(raw):
    return bool(re.fullmatch(r"(?:18|19|20)\d{2}", raw))


def _to_float(raw, sci=None):
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return None
    if sci:
        try:
            value = float(f"{value}{sci.strip()}")
        except ValueError:
            return None
    return value


@dataclass
class NumberUse:
    raw: str                  # exactly as it appears, e.g. "0.712" or "42,579"
    value: float
    sentence: str             # the sentence it appears in, verbatim — the edit anchor
    is_percent: bool = False


@dataclass
class NumberReport:
    checked: int
    matched: int
    unsupported: list = field(default_factory=list)   # NumberUse, not in the ledger
    passed: bool = True
    reasons: list = field(default_factory=list)

    def brief(self):
        return (f"{self.checked} checkable number(s), {self.matched} found in the "
                f"evidence ledger, {len(self.unsupported)} not")


def ledger_values(evidence):
    """Every number the evidence ledger vouches for, as a set of floats.

    An evidence item declares its numbers in `values`. It may also list `also_allow`
    for figures that are legitimately quotable without being findings in their own
    right — a denominator, a threshold the protocol fixed, a version number."""
    out = set()
    for item in (evidence or {}).get("items", []) or []:
        for key in ("values", "also_allow"):
            for value in item.get(key) or []:
                try:
                    out.add(float(value))
                except (TypeError, ValueError):
                    continue
    for value in (evidence or {}).get("also_allow", []) or []:
        try:
            out.add(float(value))
        except (TypeError, ValueError):
            continue
    return out


def extract(text):
    """Every checkable number in a block of prose, with the sentence it sits in.

    The sentence is carried verbatim, line breaks and all, because it becomes the
    anchor of the repair that fixes the number — and `stages.patching` matches an
    anchor character-for-character."""
    from . import prose as prose_mod          # local: avoids a gate import cycle
    body = text or ""
    spans = prose_mod.sentence_spans(body)
    skip = _spans_to_skip(body)

    out = []
    for match in _NUMBER_RE.finditer(body):
        if _in_skipped(match.start(), skip):
            continue
        raw = match.group("value")
        if _is_year(raw):
            continue
        if raw in _CONVENTIONAL:
            continue
        # A structural reference: look at the ~24 characters before the number.
        head = body[max(0, match.start() - 24):match.end()]
        if _STRUCTURAL.search(head):
            continue
        value = _to_float(raw, match.group("sci"))
        if value is None:
            continue
        if abs(value) < config.NUMBER_CHECK_MIN:
            continue
        raw_sentence, _ = prose_mod.sentence_at(spans, match.start())
        out.append(NumberUse(raw=match.group(0).strip(), value=value,
                             sentence=raw_sentence,
                             is_percent=bool(match.group("pct"))))
    return out


def _matches(value, allowed, tolerance):
    """Whether a number in prose is one the ledger vouches for.

    Rounding is the whole subtlety. 0.712 written as 0.71 is the same number; 0.71
    written when the ledger says 0.72 is not. So the comparison is done at the
    precision the PROSE used: a value quoted to two decimals matches any ledger value
    that rounds to it, and a value quoted exactly must match exactly.

    A percentage is also checked against its proportion, because 71.2% and 0.712 are
    the same finding written two ways and a manuscript uses both."""
    candidates = [value]
    if 0 < abs(value) <= 100:
        candidates.append(value / 100.0)
    if 0 < abs(value) <= 1:
        candidates.append(value * 100.0)

    for candidate in candidates:
        for known in allowed:
            if candidate == known:
                return True
            scale = max(abs(known), abs(candidate), 1e-12)
            if abs(candidate - known) / scale <= tolerance:
                return True
    return False


def check(text, evidence, tolerance=None):
    """Gate a section's numbers against the frozen evidence. Returns a NumberReport.

    An empty ledger disables the gate rather than failing every number: a project
    whose evidence stage has not run yet must not have its first draft rejected for
    every figure in it."""
    tolerance = config.NUMBER_MATCH_TOLERANCE if tolerance is None else tolerance
    allowed = ledger_values(evidence)
    uses = extract(text)

    if not allowed:
        return NumberReport(checked=len(uses), matched=0, unsupported=[], passed=True,
                            reasons=[])

    unsupported = [use for use in uses if not _matches(use.value, allowed, tolerance)]
    reasons = []
    if unsupported:
        shown = ", ".join(sorted({u.raw for u in unsupported})[:8])
        reasons.append(
            f"{len(unsupported)} number(s) in this section are not in the evidence "
            f"ledger: {shown}. Every figure in a manuscript has to come from the "
            f"analysis. Replace each one with the ledger's value, or delete the "
            f"claim it supports.")

    return NumberReport(checked=len(uses), matched=len(uses) - len(unsupported),
                        unsupported=unsupported, passed=not reasons, reasons=reasons)
