"""One name per thing.

A second name for something already named reads as a third thing. That is the whole
rule, and it is the single most expensive prose defect in a methods paper, because it
does not look like a defect — it looks like good writing. Varying your vocabulary is
what everyone was taught. In a paper it manufactures methods that do not exist.

The failure this gate was written from: a manuscript compared two patient
representations. One was the *feature representation*; the other was the *embedded
representation*. Somewhere in the drafting the feature representation also became
"the rule-based approach", because that sentence was about the absence of a
generative model and "rule-based" was the natural word. A reviewer read three methods
where there were two, asked which one the ablation was run on, and the answer took a
paragraph. The fix was one banned word.

So the grounding stage fixes the vocabulary before a word is drafted, and this gate
enforces it. A locked term has:

  * a `term`: the one string that names this thing, everywhere;
  * `aliases`: other strings that mean the same thing and are therefore FORBIDDEN;
  * an optional `first_use`: the expansion required the first time an abbreviation
    appears, so "TRD" is defined once and never again.

The gate also catches the abbreviation defects nobody catches by eye: an acronym used
before it is expanded, and an acronym expanded twice.

**What it deliberately does not do.** It does not object to a pronoun, a shortened
form the lock declares acceptable, or the term appearing inside a quotation. Vocabulary
policing that fires on ordinary English is vocabulary policing that gets turned off.
"""

import re
from dataclasses import dataclass, field

from . import prose


@dataclass
class TermDefect:
    kind: str                 # "alias", "undefined-abbreviation", "redefined"
    term: str                 # the locked term this is about
    found: str                # what actually appeared
    sentence: str             # verbatim, for the edit anchor
    detail: str


@dataclass
class TerminologyReport:
    locked: int
    defects: list = field(default_factory=list)
    passed: bool = True
    reasons: list = field(default_factory=list)

    def brief(self):
        return f"{self.locked} locked term(s), {len(self.defects)} violation(s)"


def _whole_phrase(needle):
    """A pattern matching a phrase as whole words, whatever whitespace runs through it.

    Word boundaries around a phrase that begins or ends in punctuation are not
    boundaries at all, so the pattern uses lookarounds on word characters instead of
    `\\b` — an alias like "rule-based" has a hyphen in the middle and would otherwise
    match inside "non-rule-based". Whitespace inside the phrase matches any run of it,
    because drafted prose arrives hard-wrapped and a term split across two lines is
    still that term."""
    return prose.collapse_pattern(needle)


def _quoted_spans(text):
    """Character ranges inside a quotation, where borrowed wording is allowed."""
    spans = []
    for pattern in (re.compile(r'"[^"]{0,400}"'), re.compile(r'“[^”]{0,400}”'),
                    re.compile(r"^\s{0,3}>.*$", re.MULTILINE)):
        spans.extend((m.start(), m.end()) for m in pattern.finditer(text))
    return spans


def check(text, lock):
    """Gate a section against the terminology lock. Returns a TerminologyReport.

    `lock` is the grounding document's `terminology` list. An empty lock disables the
    gate — a project whose grounding has not run has nothing to enforce."""
    terms = [t for t in (lock or []) if isinstance(t, dict) and t.get("term")]
    if not terms:
        return TerminologyReport(locked=0, passed=True)

    body = prose.strip_structure(text)
    spans = prose.sentence_spans(body)
    quoted = _quoted_spans(body)
    defects = []

    for entry in terms:
        term = str(entry["term"]).strip()
        # Longest alias first, and overlapping hits suppressed. Aliases nest — a lock
        # that forbids both "rule-based" and "rule-based approach" would otherwise
        # report one span twice, and the editor is then asked to repair the same four
        # words with two different edits, the second of which cannot match because the
        # first already changed the text.
        claimed = []
        for alias in sorted((str(a).strip() for a in entry.get("aliases") or []),
                            key=len, reverse=True):
            if not alias or alias.lower() == term.lower():
                continue
            for match in _whole_phrase(alias).finditer(body):
                if any(s <= match.start() < e for s, e in quoted):
                    continue
                if any(s < match.end() and match.start() < e for s, e in claimed):
                    continue
                claimed.append((match.start(), match.end()))
                raw, _ = prose.sentence_at(spans, match.start())
                defects.append(TermDefect(
                    kind="alias", term=term, found=match.group(0), sentence=raw,
                    detail=f"\"{' '.join(match.group(0).split())}\" is a second name "
                           f"for {term}. A reader takes a second name for a second "
                           f"thing. Use \"{term}\" here and everywhere else."))

        expansion = str(entry.get("first_use") or "").strip()
        if expansion:
            defects.extend(_check_abbreviation(body, spans, term, expansion, quoted))

    reasons = []
    if defects:
        kinds = sorted({d.kind for d in defects})
        reasons.append(
            f"{len(defects)} terminology violation(s): {', '.join(kinds)}. The "
            f"vocabulary was fixed before drafting for a reason — a second name for "
            f"one thing reads as a third thing.")

    return TerminologyReport(locked=len(terms), defects=defects, passed=not reasons,
                             reasons=reasons)


def _check_abbreviation(body, spans, term, expansion, quoted):
    """An abbreviation must be expanded exactly once, at its first appearance.

    Two failures, and both are invisible on a read-through of a section in isolation,
    which is exactly why they need arithmetic. Using `TRD` before defining it leaves
    the reader guessing. Defining it twice tells the reader they missed the first
    definition and sends them back up the page."""
    out = []
    uses = [m for m in _whole_phrase(term).finditer(body)
            if not any(s <= m.start() < e for s, e in quoted)]
    if not uses:
        return out
    expansions = [m for m in _whole_phrase(expansion).finditer(body)
                  if not any(s <= m.start() < e for s, e in quoted)]

    if not expansions:
        raw, _ = prose.sentence_at(spans, uses[0].start())
        out.append(TermDefect(
            kind="undefined-abbreviation", term=term, found=term, sentence=raw,
            detail=f"{term} is used without being expanded. Write it out in full "
                   f"(\"{expansion}\") at its first appearance and use the "
                   f"abbreviation alone after that."))
        return out

    if expansions[0].start() > uses[0].start():
        raw, _ = prose.sentence_at(spans, uses[0].start())
        out.append(TermDefect(
            kind="undefined-abbreviation", term=term, found=term, sentence=raw,
            detail=f"{term} is used before \"{expansion}\" appears. The expansion "
                   f"belongs at the first use, not later."))

    if len(expansions) > 1:
        raw, _ = prose.sentence_at(spans, expansions[1].start())
        out.append(TermDefect(
            kind="redefined", term=term, found=expansion, sentence=raw,
            detail=f"\"{expansion}\" is written out {len(expansions)} times. Expand "
                   f"it once, at the first use, then use {term} alone."))
    return out
