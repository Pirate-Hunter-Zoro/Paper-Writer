"""Paragraph shape — a claim, its support, and its consequence.

A paragraph in a paper does one job: it makes a single claim, supports it, and says
what follows. A reader who has read only the first and last sentence of every
paragraph should come away with the argument. That is not a style preference, it is
how a paper gets read: a reviewer under time pressure reads openers, and an author who
buried the claim in sentence four has written a paper nobody read.

**What this gate can and cannot do.** It cannot tell whether a topic sentence is
*good*. It can catch every structural way a paragraph fails to have one, and that
turns out to be most of the failures:

  * **It opens on a citation.** "Smith et al. found that..." begins with somebody
    else's authority instead of this paper's claim.
  * **It opens on a number or a statistic.** "Of the 42,579 patients, 3,105..." is a
    result looking for the sentence that should have introduced it.
  * **It opens on a connective.** "However," "Furthermore," "In addition," — a
    paragraph that opens on a hinge is a continuation of the one before it, and the
    two should be one paragraph or two claims.
  * **It opens on a subordinate clause.** "Because the cohort was retrospective,
    ..." delays the claim past the comma. The claim goes first.
  * **It is one sentence long.** A single sentence has no structure to check. It is
    occasionally right — the last line of a Discussion — and usually a fragment that
    escaped from the paragraph above it.
  * **It runs past nine sentences.** That is two claims, and the reader is being asked
    to work out where one ended.
  * **It ends on a citation or a bare number.** The last sentence should say what the
    paragraph means, not cite one more source.

**The share, not the count.** A section fails when too *many* of its paragraphs break
shape, not when one does. A one-sentence paragraph is right at the end of a
Discussion; a bulleted list is a paragraph to the parser and has no topic sentence by
design. Gating on any single defect would produce a gate that fires on every section
and is therefore ignored.

Pure arithmetic and pattern matching. No model.
"""

import re
from dataclasses import dataclass, field

from .. import config
from . import prose

# A citation marker in any of the three styles a manuscript here uses: a numbered
# marker, an author-year parenthetical, or a pandoc-style @key.
_CITATION_OPENERS = (
    re.compile(r"^\s*\[\s*\d"),                          # [1], [12,14]
    re.compile(r"^\s*\(\s*[A-Z][A-Za-z'’-]+[,\s]"),      # (Smith, 2024)
    re.compile(r"^\s*@[A-Za-z]"),                        # @smith2024
    re.compile(r"^\s*[A-Z][A-Za-z'’-]+\s+(?:et\s+al\.?|and\s+[A-Z][A-Za-z'’-]+)"
               r"\s+(?:\(\d{4}\)|\[\d)"),                # Smith et al. (2024)
)

_NUMBER_OPENER = re.compile(r"^\s*[\(\[]?[-+]?\d")

# Connectives that make a sentence a hinge rather than a claim.
_CONNECTIVES = (
    "however", "furthermore", "moreover", "in addition", "additionally",
    "nevertheless", "nonetheless", "therefore", "thus", "hence", "consequently",
    "on the other hand", "by contrast", "in contrast", "similarly", "likewise",
    "that said", "meanwhile", "also", "second", "third", "finally", "lastly",
    "next", "then",
)

# Openers that delay the claim past a comma.
_SUBORDINATORS = (
    "because", "although", "though", "while", "whereas", "since", "given that",
    "if", "unless", "when", "after", "before", "as ", "in order to", "to assess",
    "to evaluate", "to determine", "having",
)


def _starts_with(sentence, phrases):
    low = sentence.lower().lstrip("\"'“‘([ ")
    for phrase in phrases:
        if low.startswith(phrase):
            # A whole word, not a prefix: "thus" matches, "thusly" does not, and
            # "as " already carries its own boundary.
            rest = low[len(phrase):]
            if not rest or not rest[0].isalpha():
                return phrase
    return ""


def _opens_on_citation(sentence):
    return any(pattern.match(sentence) for pattern in _CITATION_OPENERS)


def _delays_the_claim(sentence):
    """Whether the sentence buries its claim behind a subordinate clause.

    Only counts when the clause actually runs long enough to be in the way. "If so,
    the estimate is biased" puts the claim three words in and is fine."""
    phrase = _starts_with(sentence, _SUBORDINATORS)
    if not phrase:
        return ""
    head, _, tail = sentence.partition(",")
    if not tail.strip():
        return ""                       # no comma: it is one clause, not two
    return phrase if len(head.split()) >= 6 else ""


@dataclass
class ParagraphDefect:
    index: int                # 1-based position in the section
    kind: str                 # what is wrong
    detail: str               # one sentence a person can act on
    anchor: str               # the exact sentence to repair, or "" when it is shape


@dataclass
class ParagraphReport:
    total: int
    checked: int              # paragraphs the shape rules applied to
    defects: list = field(default_factory=list)
    share: float = 0.0
    passed: bool = True
    reasons: list = field(default_factory=list)

    def brief(self):
        return (f"{self.total} paragraphs, {len(self.defects)} shape defect(s) "
                f"across {self.checked} checked ({self.share:.0%})")


def _check_one(index, paragraph):
    """Every shape defect in one paragraph."""
    out = []
    sents = prose.sentences(paragraph)
    if not sents:
        return out

    first, last = sents[0], sents[-1]

    if len(sents) < config.PARAGRAPH_MIN_SENTENCES:
        out.append(ParagraphDefect(
            index, "too short",
            f"paragraph {index} is {len(sents)} sentence(s). A paragraph is a claim, "
            f"its support, and what follows from it, which takes at least "
            f"{config.PARAGRAPH_MIN_SENTENCES}. Either fold it into the paragraph it "
            f"belongs to or give the claim its support.",
            first))
    elif len(sents) > config.PARAGRAPH_MAX_SENTENCES:
        out.append(ParagraphDefect(
            index, "too long",
            f"paragraph {index} runs {len(sents)} sentences against a ceiling of "
            f"{config.PARAGRAPH_MAX_SENTENCES}. It is carrying two claims. Find where "
            f"the second one starts and break there.",
            first))

    if _opens_on_citation(first):
        out.append(ParagraphDefect(
            index, "no topic sentence",
            f"paragraph {index} opens on a citation. Open on this paper's claim and "
            f"cite the support underneath it.",
            first))
    elif _NUMBER_OPENER.match(first):
        out.append(ParagraphDefect(
            index, "no topic sentence",
            f"paragraph {index} opens on a number. A statistic is support, not a "
            f"claim. Say what it shows, then give it.",
            first))
    elif (phrase := _starts_with(first, _CONNECTIVES)):
        out.append(ParagraphDefect(
            index, "hinge opener",
            f"paragraph {index} opens on \"{phrase}\", which makes it a continuation "
            f"of the paragraph before it. Either merge the two or open on the claim "
            f"this paragraph is making.",
            first))
    elif (phrase := _delays_the_claim(first)):
        out.append(ParagraphDefect(
            index, "buried claim",
            f"paragraph {index} opens \"{phrase}...\" and does not reach its claim "
            f"until after the comma. Put the claim first and the condition second.",
            first))

    if len(sents) >= config.PARAGRAPH_MIN_SENTENCES:
        if _opens_on_citation(last):
            out.append(ParagraphDefect(
                index, "no concluding sentence",
                f"paragraph {index} ends on a citation. The last sentence should say "
                f"what the paragraph means for this paper.",
                last))
        elif _NUMBER_OPENER.match(last) and len(last.split()) < 12:
            out.append(ParagraphDefect(
                index, "no concluding sentence",
                f"paragraph {index} ends on a bare number. Close on what it means.",
                last))
    return out


def check(text, section_name=""):
    """Gate a section's paragraph shape. Returns a ParagraphReport.

    `section_name` exempts the sections where the rules do not apply: an abstract is
    one structured block, a declarations section is a list, and references are not
    prose at all."""
    if section_name and section_name.strip().lower() in config.PARAGRAPH_EXEMPT_SECTIONS:
        return ParagraphReport(total=0, checked=0, passed=True)

    blocks = prose.paragraphs(text)
    checkable = [(i + 1, p) for i, p in enumerate(blocks)
                 if not prose.is_list_item(p)]

    defects = []
    for index, paragraph in checkable:
        defects.extend(_check_one(index, paragraph))

    checked = len(checkable)
    # One paragraph can carry two defects; the share is of paragraphs, not of defects,
    # because that is the question — how much of this section is mis-shaped.
    bad = len({d.index for d in defects})
    share = 0.0 if not checked else bad / checked

    reasons = []
    if checked and share > config.PARAGRAPH_DEFECT_SHARE_MAX:
        kinds = sorted({d.kind for d in defects})
        reasons.append(
            f"{bad} of {checked} paragraphs are mis-shaped ({share:.0%}); the ceiling "
            f"is {config.PARAGRAPH_DEFECT_SHARE_MAX:.0%}. What is wrong: "
            f"{', '.join(kinds)}.")

    return ParagraphReport(total=len(blocks), checked=checked, defects=defects,
                           share=round(share, 4), passed=not reasons, reasons=reasons)
