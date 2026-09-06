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
  * Clinical and terminology codes. ICD-9 296.2 names a diagnosis; a Methods section
    lists dozens of them and not one is a finding.
  * Numbers the ledger itself is not expected to hold — a p-value threshold of 0.05,
    a 95% confidence level, a random seed.

Those exemptions are declared here rather than guessed at, and the ledger can add its
own: an evidence item may list `also_allow` values that are legitimately quotable
without being findings.

**Rounding is allowed and equality is not, and it is judged at the precision the prose
used.** 0.712 stated as 0.71 is the same number and the gate says so. A delta of
0.007939 written as 0.008 is the same number too. What it will not accept is 0.71 when
the ledger says 0.72, however small the difference looks. See `_matches`: a flat
relative tolerance cannot express this, and gets small effect sizes wrong in the
direction that matters.
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
    (?![\w]|\.\d)                    # not a word, and not "1.2.3" — a version string
""", re.VERBOSE)
#
# **The trailing lookahead is the single most consequential line in this module, and
# an earlier version of it was silently switching the gate off.** It read
# `(?![\w.]|\s*\))`, meaning "reject a match followed by a word character, a full stop,
# or a closing bracket". Two things followed, and both are invisible:
#
#   * A number that ENDS A SENTENCE is followed by a full stop, so it was never
#     checked. "Discrimination reached 0.812." went straight past.
#   * A number that closes a parenthetical is followed by ")", so the upper bound of
#     every confidence interval was never checked either.
#
# Between them that is most of the figures in a results section — precisely the ones
# a reader trusts most. The gate reported a clean section and meant "I looked at the
# numbers in the middle of sentences".
#
# What the exclusion was actually for is a version string, and `\.\d` says that
# exactly: `1.2.3` matches `1.2` and is then rejected because `.3` follows.

# Spans whose numbers are never findings.
_SKIP_SPANS = (
    re.compile(r"\[[^\]]*\]"),                       # [1], [12,14] citation markers
    re.compile(r"\(\s*\d{1,2}\s*\)"),                 # "(1)" — a list marker
    re.compile(r"\((?:19|20)\d{2}[a-z]?\)"),         # (2024) author-year
    re.compile(r"`[^`]*`"),                          # inline code
    re.compile(r"^\s*\|.*$", re.MULTILINE),          # table rows
    re.compile(r"^\s{0,3}#{1,6}\s.*$", re.MULTILINE),  # headings
    re.compile(r"<!--.*?-->", re.DOTALL),            # comments
)

# A run of digits joined by hyphens: an ORCID, a grant number, a trial registration.
# Not a measurement, and checking one produces noise on every title page.
_IDENTIFIER = re.compile(r"\d[\d-]{6,}\d")

# A clinical or terminology CODE is an identifier, not a measurement. ICD-9 296.2 is
# the name of a diagnosis, and a manuscript's Methods section lists dozens of them. The
# keyword may sit several words back — "ICD-9 codes 296.2, 296.3, 300.4, and 311" — so
# this looks at a window of preceding text rather than demanding adjacency, which is
# what `_STRUCTURAL` does and why it cannot cover this case.
_CODE_KEYWORD = re.compile(
    r"\b(?:icd|icd-9|icd-10|cpt|hcpcs|loinc|rxnorm|snomed|ndc|atc|drg|"
    r"codes?|version|seed|port)\b", re.IGNORECASE)

# A sentence boundary. The exemption must not survive one, or a results sentence
# following a Methods sentence would inherit it.
_BOUNDARY = re.compile(r"[.!?]\s+(?=[A-Z])")


def _in_code_list(before):
    """Whether the text immediately before a number puts it in a code list.

    The keyword can sit several words back — "ICD-9 codes 296.2, 296.3, 300.4, and
    311" — so this cannot demand adjacency the way `_STRUCTURAL` does. It also cannot
    simply forbid full stops in between, because the codes themselves contain them."""
    matches = list(_CODE_KEYWORD.finditer(before))
    if not matches:
        return False
    return not _BOUNDARY.search(before[matches[-1].end():])

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
    places: int = 0           # decimals the prose wrote, so rounding is judged fairly
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
    # Structure is blanked rather than deleted, so offsets and raw substrings still
    # line up with the original. Scanning the blanked text is what keeps an ORCID in a
    # table, a TRIPOD item number in a comment, and a figure number in a heading from
    # being read as findings.
    body = prose_mod.strip_structure(text or "")
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
        # A code list: look further back, and stop at the previous sentence.
        if _in_code_list(body[max(0, match.start() - 120):match.start()]):
            continue
        value = _to_float(raw, match.group("sci"))
        if value is None:
            continue
        if abs(value) < config.NUMBER_CHECK_MIN:
            continue
        # An identifier is a string of digits with internal hyphens — an ORCID, a grant
        # number, an NCT registration. It is not a measurement and checking it produces
        # noise. Judged by what surrounds the match rather than by its value.
        around = body[max(0, match.start() - 1):match.end() + 1]
        if "-" in around.replace(match.group(0), "", 1) and _IDENTIFIER.search(
                body[max(0, match.start() - 20):match.end() + 20]):
            continue
        raw_sentence, _ = prose_mod.sentence_at(spans, match.start())
        out.append(NumberUse(raw=match.group(0).strip(), value=value,
                             sentence=raw_sentence, places=_decimals(raw),
                             is_percent=bool(match.group("pct"))))
    return out


def _decimals(raw):
    """How many decimal places the prose actually wrote."""
    cleaned = raw.replace(",", "").strip()
    return len(cleaned.split(".")[1]) if "." in cleaned else 0


def _matches(value, allowed, tolerance, places=None):
    """Whether a number in prose is one the ledger vouches for.

    **Rounding is the whole subtlety, and it is checked at the precision the prose
    used** rather than against a flat relative tolerance. A ledger value matches when
    it rounds to the written figure at the number of decimals the author wrote. So
    0.712 may be written 0.71, and a delta of 0.007939 may be written 0.008 — but 0.71
    against a ledger value of 0.72 is refused, and so is 0.008 against 0.009.

    A flat relative tolerance cannot do this, and the failure is asymmetric in the
    worst direction. At 0.005 relative, 0.74 against 0.7429 passes comfortably while
    0.008 against 0.007939 fails, because the same rounding is a larger fraction of a
    smaller number. Every legitimately rounded effect size in a manuscript is small.

    The relative tolerance is kept as a floor beneath the rounding rule, for a figure
    written at full precision with a trailing digit lost somewhere.

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
            if places is not None and round(known, places) == round(candidate, places):
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

    unsupported = [use for use in uses
                   if not _matches(use.value, allowed, tolerance, places=use.places)]
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
