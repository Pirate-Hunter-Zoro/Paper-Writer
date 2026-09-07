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

**And the synonym nobody thought to ban.** A lock can only forbid what somebody
listed, so the gate above is blind by construction to the second name that was
invented during drafting. The manuscript this gate was written from went on to carry
four names for one arm — the *typed feature representation*, the *feature
representation*, the *feature matrix* and the *feature-vector* — through every gate,
because only "rule-based approach" had ever been declared.

So `check_manuscript` also looks for **drift**: a phrase that shares a locked term's
modifier and ends in a different role noun. "Feature matrix" against a locked "feature
representation" is a candidate second name. "Feature selection" is not, because
selection is not a thing the paper names. It runs at manuscript scope only, for the
same reason the abbreviation rules do — a phrase used once in each of four sections is
a name, and no section can see that from inside itself.

**What it deliberately does not do.** It does not object to a pronoun, a shortened
form the lock declares acceptable, or the term appearing inside a quotation. Vocabulary
policing that fires on ordinary English is vocabulary policing that gets turned off.
"""

import re
from dataclasses import dataclass, field

from .. import config
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


def _quoted_spans(text, headings_in=None):
    """Character ranges where the wording is somebody else's, so a locked term does
    not govern it: a quotation, a blockquote, and the reference list.

    **A BIBLIOGRAPHIC TITLE IS THE CASE THAT WAS MISSING.** A lock that forbids
    "resistant depression" in favour of "TRD" flagged two reference entries whose
    published titles are "Treatment resistant depression in electronic health records:
    definitions matter" and "Treatment resistant depression: socio-demographic
    characteristics...". Both were correct. You cannot rename somebody else's paper,
    and the only repair the gate offered was to misquote a citation.

    The list is `config.TERM_BORROWED_SECTIONS` and it holds exactly one section. The
    ABSTRACT is deliberately not on it: an abstract is the author's own prose and the
    part of the paper most people read, so a forbidden synonym there is a defect in the
    worst place there is. Sections are found by heading, read off the UNSTRIPPED text,
    because `prose.strip_structure` blanks a heading and a blanked heading cannot be
    matched — blanking preserves offsets, so a span found in the original is the same
    span in the stripped copy."""
    spans = []
    for pattern in (re.compile(r'"[^"]{0,400}"'), re.compile(r'“[^”]{0,400}”'),
                    re.compile(r"^\s{0,3}>.*$", re.MULTILINE)):
        spans.extend((m.start(), m.end()) for m in pattern.finditer(text))
    spans.extend(_borrowed_sections(headings_in if headings_in is not None else text))
    return spans


def _borrowed_sections(text):
    """The sections whose words are not the author's, as character ranges."""
    spans, start, cutting = [], 0, False
    for match in _SECTION_RE.finditer(text or ""):
        if cutting:
            spans.append((start, match.start()))
        cutting = (match.group(1).strip().lower()
                   in config.TERM_BORROWED_SECTIONS)
        start = match.end()
    if cutting:
        spans.append((start, len(text or "")))
    return spans


def check(text, lock, whole_manuscript=False, section_name=""):
    """Gate a section against the terminology lock. Returns a TerminologyReport.

    `lock` is the grounding document's `terminology` list. An empty lock disables the
    gate — a project whose grounding has not run has nothing to enforce.

    **`whole_manuscript` decides whether the first-use rules run, and they must not run
    at section scope.** An abbreviation is expanded once in a manuscript, at its first
    appearance. Which section that is cannot be known from inside one section, so a
    per-section check has to demand the expansion in every section — and then the
    expanded-twice rule fires on the manuscript that obeys it. The two rules contradict
    each other at section scope, and a writer told to satisfy both will oscillate.

    So the alias rules run everywhere, because a forbidden synonym is a defect wherever
    it appears, and the first-use rules run only against the assembled manuscript. The
    same split `citations.check` and `citations.check_manuscript` already make, for the
    same reason: some defects only exist at whole-document scope.

    **`section_name` is what makes the borrowed-wording exemption work at section
    scope.** `_borrowed_sections` finds the reference list by its heading, which is no
    use when one section's BODY is handed over — the heading is not in it. The final
    sweep measures section by section on purpose, and without this every reference
    whose published title contains a banned synonym is reported as this paper's
    vocabulary."""
    if section_name and section_name.strip().lower() in config.TERM_BORROWED_SECTIONS:
        return TerminologyReport(locked=len(lock or []), passed=True)
    terms = [t for t in (lock or []) if isinstance(t, dict) and t.get("term")]
    if not terms:
        return TerminologyReport(locked=0, passed=True)

    body = prose.strip_structure(text)
    spans = prose.sentence_spans(body)
    # The section scan reads the UNSTRIPPED text: `strip_structure` blanks headings, so
    # "# References" is invisible in `body`. Blanking preserves every offset, so a span
    # found in the original is the same span in the stripped copy.
    quoted = _quoted_spans(body, text or "")
    defects = []

    for entry in terms:
        term = str(entry["term"]).strip()
        # Where the TERM itself appears. An alias that falls inside one of these is not
        # a violation, and this is the common case rather than an edge case: an
        # abbreviation is usually a substring of the full term it abbreviates. A lock
        # that forbids the bare "AUC" in favour of "ROC AUC" would otherwise flag every
        # correct use of "ROC AUC", because the correct phrase contains the forbidden
        # one. The editor is then handed a repair that replaces "AUC" with "ROC AUC"
        # inside "ROC AUC", which is both wrong and unrepairable.
        own = [(m.start(), m.end()) for m in _whole_phrase(term).finditer(body)]
        # And where its DECLARED EXPANSION appears. An alias nested inside the
        # approved long form is the same false positive one level out: a lock that
        # abbreviates "treatment-resistant depression" to "TRD" and forbids "resistant
        # depression" flags every correct first use, because the approved phrase
        # contains the forbidden one. The editor is then handed a repair that replaces
        # two words inside the expansion the lock itself requires.
        expansion_text = str(entry.get("first_use") or "").strip()
        if expansion_text:
            own += [(m.start(), m.end())
                    for m in _whole_phrase(expansion_text).finditer(body)]
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
                if any(s <= match.start() and match.end() <= e for s, e in own):
                    continue                  # inside the term itself; not a second name
                claimed.append((match.start(), match.end()))
                raw, _ = prose.sentence_at(spans, match.start())
                defects.append(TermDefect(
                    kind="alias", term=term, found=match.group(0), sentence=raw,
                    detail=f"\"{' '.join(match.group(0).split())}\" is a second name "
                           f"for {term}. A reader takes a second name for a second "
                           f"thing. Use \"{term}\" here and everywhere else."))

        if whole_manuscript:
            defects.extend(_drift(body, spans, entry, quoted))

        expansion = str(entry.get("first_use") or "").strip()
        if expansion and whole_manuscript:
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


def _drift(body, spans, entry, quoted):
    """Undeclared near-variants of a locked term, by shared modifier.

    "Feature representation" splits into the modifier "feature" and the head
    "representation". Any other phrase built from that modifier and a role noun —
    matrix, vector, approach, arm — is a second name for the same thing wearing a
    different head, and the lock never heard of it. Hyphenation is ignored, because
    "feature-vector" and "feature vector" are the same defect.

    A single use is ordinary English and is not reported. A phrase used
    `TERM_DRIFT_MIN_USES` times is a name whether or not anybody declared it one.

    **`aliases` FORBIDS AND `also_called` PERMITS, AND BOTH ARE NEEDED.** Before
    `also_called` existed the only way to silence drift was to ban the phrase, which is
    the opposite of what an approved second head means. A real packet's naming rule
    reads "the FEATURE representation (feature vector, typed feature vector,
    feature-vector XGBoost)": three approved names for one arm, deliberately, because
    the paper needs a word for the per-patient vector and a word for the concept. The
    gate reported all thirty-one uses of "feature vector" as drift and offered "declare
    it as a separate locked term", which would have made the lock assert two arms where
    there is one. Meanwhile the genuinely undeclared name in the same manuscript —
    "feature matrix", eleven uses — was reported identically and got lost in the noise.

    A phrase in neither list is still drift, which is the whole point: the lock has to
    say out loud which second names it means."""
    term = str(entry["term"]).strip()
    parts = re.split(r"[\s-]+", term.lower())
    if len(parts) < 2:
        return []                    # a one-word term has no modifier to share
    modifier, head = parts[-2], parts[-1]
    if modifier in config.TERM_ROLE_NOUNS:
        return []                    # "regression model" — the modifier is itself a role
    declared = {str(a).strip().lower() for a in entry.get("aliases") or []}
    approved = {" ".join(str(a).strip().lower().replace("-", " ").split())
                for a in entry.get("also_called") or []}

    alternatives = "|".join(n for n in config.TERM_ROLE_NOUNS if n != head)
    pattern = re.compile(r"(?<![A-Za-z])" + re.escape(modifier) + r"[\s-]+(" +
                         alternatives + r")(?:s)?(?![A-Za-z])", re.IGNORECASE)

    seen = {}
    for match in pattern.finditer(body):
        if any(s <= match.start() < e for s, e in quoted):
            continue
        phrase = " ".join(match.group(0).split()).lower().replace("-", " ")
        if phrase in declared:
            continue                 # already banned; the alias rule owns it
        if phrase in approved:
            continue                 # declared as an approved second name
        seen.setdefault(phrase, []).append(match.start())

    out = []
    for phrase, hits in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        if len(hits) < config.TERM_DRIFT_MIN_USES:
            continue
        raw, _ = prose.sentence_at(spans, hits[0])
        out.append(TermDefect(
            kind="drift", term=term, found=phrase, sentence=raw,
            detail=f"\"{phrase}\" appears {len(hits)} times and is not in the lock. "
                   f"It shares \"{modifier}\" with the locked term \"{term}\" and "
                   f"ends somewhere else, which is what a second name looks like. "
                   f"Either use \"{term}\" throughout, or declare \"{phrase}\" as a "
                   f"separate locked term if it really is a separate thing."))
    return out


_SECTION_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

# The defect kinds that are claims about a WHOLE manuscript rather than about a piece
# of text: an abbreviation used before it is expanded, and one expanded twice. They are
# the two `check_manuscript` drops for a companion document — see `first_use` there.
_FIRST_USE_KINDS = ("undefined-abbreviation", "redefined")


def body_of(text):
    """The manuscript minus the sections that expand their own abbreviations.

    An abstract is read on its own, detached from the paper, by anyone scanning a
    table of contents or a search result. Journals therefore expect it to expand its
    own abbreviations, and the body to expand them again at its own first use. A
    first-use check that spans both reports every correctly written manuscript as
    having defined everything twice.

    So the front and back matter are dropped before the first-use scan, using the same
    list of not-body-prose sections the paragraph and sentence gates use. Aliases are
    still checked everywhere: a forbidden synonym in an abstract is a defect in the
    part of the paper most people read."""
    keep, cutting = [], False
    for line in (text or "").splitlines():
        match = _SECTION_RE.match(line)
        if match:
            cutting = (match.group(1).strip().lower()
                       in config.PARAGRAPH_EXEMPT_SECTIONS)
        keep.append("" if cutting else line)
    return "\n".join(keep)


def check_manuscript(text, lock, first_use=True):
    """The whole-manuscript pass, where "expanded once" is finally a checkable claim.

    Run against the assembled manuscript. Everything `check` reports, plus drift, plus
    the first-use rules: an abbreviation used before it is expanded, and an
    abbreviation expanded more than once. The abstract and the other stand-alone
    sections are excluded from the first-use scan — see `body_of`.

    **`first_use=False` is for a companion document rather than a degraded mode.** A
    supplement, a reporting checklist and a cover letter are each delivered as their
    own file and each legitimately reuses the abbreviations the manuscript expanded.
    Demanding that a supplement expand TRD again is demanding the manuscript expand it
    twice, which is the contradiction this function's own docstring warns about one
    level down. Drift still runs, because a second name for one method is a defect
    wherever in the packet it appears."""
    aliases = check(text, lock, whole_manuscript=False)
    drift = check(body_of(text), lock, whole_manuscript=True)
    kept = [d for d in drift.defects
            if d.kind != "alias"
            and (first_use or d.kind not in _FIRST_USE_KINDS)]
    defects = aliases.defects + kept
    reasons = []
    if defects:
        kinds = sorted({d.kind for d in defects})
        reasons.append(
            f"{len(defects)} terminology violation(s): {', '.join(kinds)}. The "
            f"vocabulary was fixed before drafting for a reason — a second name for "
            f"one thing reads as a third thing.")
    return TerminologyReport(locked=aliases.locked, defects=defects,
                             passed=not defects, reasons=reasons)
