"""A point the paper makes over and over, in section after section.

`claims` refuses the same thing asserted twice in the argument MAP. Nothing looked at
the drafted prose, and the map cannot see this: three sections can each carry a
different claim and still spend a paragraph each restating the same background fact,
because each writer was told to make the point and none of them could see the others.

**The failure this was written from.** One manuscript said, in five places, that both
representations were built from the same hand-picked field inventory and that the
feature engineering had been relocated rather than removed. Abstract, Introduction,
Methods, Discussion, Conclusions. Every instance was true, well written and relevant.
Read end to end it reads as a paper that does not trust its reader, and the sixth
instance — a whole Limitations subsection — was cut only because a person noticed.

**What it measures.** Sentences in different body sections that carry nearly the same
content words. Two is normal and is not reported: a Discussion is supposed to pick up
what the Results said. Three or more sections saying one thing is the pattern, and it
is the count rather than the wording that makes it visible, because a writer restating
a point never uses the same words twice.

**What it deliberately excludes.**

  * Front and back matter, and the conclusions. An abstract restates the paper and
    so does a conclusions section; that is their job, and one that introduced new
    material would be the defect. Note this is a different list from the one the
    paragraph gate uses — a conclusions section is prose and its shape is still
    checked; only its echoes are forgiven.
  * Captions. "Discrimination of the four classifiers on each representation (held-out
    test set). 95% CIs are bootstrap percentile intervals." is boilerplate by design,
    shared across every table in the paper, and counting it flagged three clusters of
    perfectly correct captions on the first run.
  * Short sentences. Under a floor of content words, two sentences can overlap
    heavily and still say different things.

No models, no I/O. Set overlap over a bag of words.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field

from .. import config
from . import prose

# Words carrying no topic. Kept small on purpose: a longer list starts removing the
# terms that make two sentences the same sentence.
_STOPWORDS = frozenset("""
a an the of to in on for with by from as at is are was were be been being and or but
not no nor so that this these those it its their his her they them we our us he she
which who whom whose than then there here into over under about above each both all
any some more most other such only own same very can will just do does did than one
two three had has have if when while because
""".split())

_WORD_RE = re.compile(r"[a-z][a-z-]+")

# A caption or a panel label. Shares its wording with every other caption in the paper
# by design, which is the whole reason a table caption is readable.
_CAPTION_RE = re.compile(r"\*{2,3}\s*(?:Table|Figure|Fig\.?|Panel)\b"
                         r"|\*\*\([A-Za-z0-9]+\)", re.IGNORECASE)

_SECTION_RE = re.compile(r"^(#{1,2})\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class Echo:
    sections: list                # the section names it appears in, in order
    sentences: list               # (section, sentence) pairs


@dataclass
class RepetitionReport:
    echoes: list = field(default_factory=list)
    checked: int = 0              # sentences compared
    passed: bool = True
    reasons: list = field(default_factory=list)

    def brief(self):
        return (f"{self.checked} body sentences, {len(self.echoes)} point(s) restated "
                f"in three or more sections")


def _bag(sentence):
    return {w for w in _WORD_RE.findall(sentence.lower()) if w not in _STOPWORDS}


def _body_sentences(text):
    """Every body-prose sentence with the section it sits in. Front matter, back
    matter and captions are dropped."""
    exempt = {s.lower() for s in config.ECHO_EXEMPT_SECTIONS}
    parts = _SECTION_RE.split(text or "")
    out = []
    # split() yields [preamble, hashes, name, body, hashes, name, body, ...]
    for i in range(1, len(parts), 3):
        name = parts[i + 1].strip()
        body = parts[i + 2] if i + 2 < len(parts) else ""
        if name.lower() in exempt:
            continue
        for sentence in prose.sentences(prose.strip_structure(body)):
            if _CAPTION_RE.search(sentence):
                continue
            out.append((name, sentence))
    return out


def check(text, min_sections=None, similarity=None, min_words=None):
    """Find points restated across three or more body sections.

    `similarity` is Jaccard overlap of content words. `min_words` is the floor below
    which a sentence is too short for overlap to mean anything."""
    min_sections = config.ECHO_MIN_SECTIONS if min_sections is None else min_sections
    similarity = config.ECHO_SIMILARITY if similarity is None else similarity
    min_words = config.ECHO_MIN_CONTENT_WORDS if min_words is None else min_words

    entries = [(name, s, bag) for name, s in _body_sentences(text)
               if len(bag := _bag(s)) >= min_words]

    parent = list(range(len(entries)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            if entries[i][0] == entries[j][0]:
                continue                      # within one section is not this defect
            a, b = entries[i][2], entries[j][2]
            if len(a & b) / len(a | b) >= similarity:
                parent[find(i)] = find(j)

    groups = defaultdict(list)
    for i in range(len(entries)):
        groups[find(i)].append(i)

    echoes = []
    for members in groups.values():
        sections = []
        for i in members:
            if entries[i][0] not in sections:
                sections.append(entries[i][0])
        if len(sections) >= min_sections:
            echoes.append(Echo(
                sections=sections,
                sentences=[(entries[i][0], entries[i][1]) for i in members]))
    echoes.sort(key=lambda e: -len(e.sections))

    reasons = []
    for echo in echoes:
        first = echo.sentences[0][1]
        reasons.append(
            f"one point is restated in {len(echo.sections)} sections "
            f"({', '.join(echo.sections)}). It opens \"{first[:70]}...\". Make it "
            f"once, where the reader needs it, and cut the rest.")

    return RepetitionReport(echoes=echoes, checked=len(entries),
                            passed=not reasons, reasons=reasons)
