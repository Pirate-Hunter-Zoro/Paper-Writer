"""Every pointer inside the document resolves to something that exists.

`citations` asks whether `[27]` has a reference behind it. This asks the same question
of the pointers a paper makes to *itself* — "Supplement S10", "Table S12", "Figure 4" —
and it is the same defect with a different cause. A citation marker goes wrong when a
reference is added or dropped. A cross-reference goes wrong when a section is cut, and
cutting a section is a thing that happens to every paper on the way to submission.

**The failure this was written from.** Three supplement sections were removed from one
manuscript in a single afternoon. Each removal renumbered everything below it: sections,
tables, figures, and every pointer in two documents. Each pass was correct on its own
and one of them ran twice by mistake, which turned "Supplement S10" into "Supplement S8"
and left the Methods pointing at the subgroup analysis instead of the field-level
crosswalk. Nothing in the harness noticed. Every gate passed, because every gate looked
at one section at a time, and a pointer is the one defect that cannot be seen from
inside the section that makes it.

**What it checks, and what it deliberately does not.** It checks that every pointer
resolves, that every numbered item is contiguous from 1 — because a supplement that
skips S4 tells a reader a section was lost — and that no pointer is UNNAMED. It does
NOT check that a named pointer aims at the *right* thing; nothing can, short of reading
the paper. Contiguity is what catches the excision, resolution is what catches the
renumber, and the unnamed check is what catches the pointer that was never resolvable.

**The unnamed pointer.** "Full table in supporting material" appeared in a Table 1
caption of a finished manuscript. There is no such document. The full table did not
exist anywhere in the packet, the caption's own sentence two lines above said "Table 1
gives every selected characteristic", and every gate passed — because a pointer with no
number is not a pointer any resolver can follow, so nothing was looking for it. It is
the "data not shown" defect in a cross-reference's clothing: a reader is sent somewhere
and there is nowhere to go.

A pointer that names its target passes, however awkward. "described in Supplement M5",
"Table S9", "the Discussion, *Limitations*" all resolve for a reader. What fails is a
bare gesture at the paper's own material with no identifier attached.

Numbered items are recognised by their caption, in the form the manuscripts here use:
`***Table S3.** ...*` or `***Figure 4.** ...*`, and `# Supplement S3.` for a section.
Main-text and supplement numbering are separate sequences and are checked separately,
because "Table 2" and "Table S2" are two different objects.

No models, no I/O. Two passes over two strings.
"""

import re
from dataclasses import dataclass, field

from . import prose

# A caption DEFINES an item. The bold-italic form is what pandoc renders as a caption
# and what every document in this project uses.
_DEF_RE = re.compile(r"^\s*\*{2,3}\s*(Table|Figure)\s+(S?)(\d+)\s*\.", re.MULTILINE)
_SECTION_DEF_RE = re.compile(r"^#{1,2}\s+Supplement\s+(S|M)(\d+)\s*\.", re.MULTILINE)

# A pointer REFERS to one. "Tables 2 and 3" and "Figures S1-S3" both point at more than
# one item, so the pattern takes the trailing list as well as the first number.
_REF_RE = re.compile(
    r"(?<![A-Za-z])(Tables?|Figures?|Figs?\.?)\s+(S?)(\d+)"
    r"((?:\s*(?:,|and|to|through|[-–])\s*S?\d+)*)", re.IGNORECASE)
_SECTION_REF_RE = re.compile(
    r"(?<![A-Za-z])Supplements?\s+(S|M)(\d+)"
    r"((?:\s*(?:,|and|to|through|[-–])\s*[SM]?\d+)*)", re.IGNORECASE)

_TRAILING_NUM_RE = re.compile(r"[SM]?(\d+)")

# A gesture at the paper's own material with nothing named. The trailing lookahead is
# what makes it narrow: an identifier immediately after the phrase — a number, an
# S-or-M label, a section title in emphasis, a colon introducing one — means the
# pointer names its target and is somebody's ordinary prose.
#
# "in the supplement (Table S9)" passes. "in supporting material." does not.
_VAGUE_POINTER_RE = re.compile(
    r"(?<![A-Za-z])"
    r"(?:in|see|are\s+in|is\s+in|available\s+in|reported\s+in|given\s+in|"
    r"shown\s+in|provided\s+in|listed\s+in|found\s+in|detailed\s+in)\s+"
    r"(?:the\s+)?"
    r"(?:supp(?:orting|lementary|lement(?:al)?)\s+"
    r"(?:material|materials|information|file|files|data|appendix)"
    r"|supplement(?:ary)?|appendix|online\s+material)"
    r"(?![A-Za-z])"
    r"(?!\s*[,(]?\s*(?:[SM]\s?\d|\d|[Tt]able|[Ff]igure|[Ff]ig|[Ss]ection|[*_]))",
    re.IGNORECASE)


@dataclass
class CrossrefDefect:
    kind: str                 # "unresolved", "unnamed" or "gap"
    label: str                # "Table S12", "Supplement S4"
    detail: str
    sentence: str = ""        # verbatim, for the edit anchor


@dataclass
class CrossrefReport:
    defined: dict = field(default_factory=dict)   # kind -> sorted numbers
    defects: list = field(default_factory=list)
    passed: bool = True
    reasons: list = field(default_factory=list)

    def brief(self):
        parts = [f"{k} {v[0]}-{v[-1]}".replace(" S ", " S") if v else f"{k} none"
                 for k, v in sorted(self.defined.items())]
        return f"{', '.join(parts)}; {len(self.defects)} defect(s)"


def _expand(first, trailing):
    """Every number a pointer names. "Tables S1-S3" is three, not one.

    A range is expanded only when it runs upward and stays short. "Tables 2-40" in a
    paper with four tables is a page range or a typo, and inventing 39 references from
    it would bury the real defect under noise."""
    out = [first]
    nums = [int(n) for n in _TRAILING_NUM_RE.findall(trailing or "")]
    if not nums:
        return out
    if re.search(r"(?:to|through|[-–])\s*[SM]?\d+\s*$", trailing or ""):
        last = nums[-1]
        if first < last <= first + 40:
            out.extend(range(first + 1, last + 1))
            nums = nums[:-1]
    out.extend(nums)
    return sorted(set(out))


def check(manuscript, supplement=""):
    """Gate the pointers in a manuscript and its supplement. Returns a CrossrefReport.

    Both documents are scanned for pointers and both for definitions, because the
    manuscript points into the supplement constantly and the supplement points back."""
    man_body = prose.strip_structure(manuscript or "")
    sup_body = prose.strip_structure(supplement or "")
    both = man_body + "\n\n" + sup_body

    defined = {}
    for source in (manuscript or "", supplement or ""):
        for kind, star, num in _DEF_RE.findall(source):
            key = f"{kind.title()}{' S' if star else ' '}".strip()
            defined.setdefault(key, set()).add(int(num))
    for source in (manuscript or "", supplement or ""):
        for letter, num in _SECTION_DEF_RE.findall(source):
            defined.setdefault(f"Supplement {letter.upper()}", set()).add(int(num))

    spans = prose.sentence_spans(both)
    defects = []

    def _anchor(pos):
        raw, _ = prose.sentence_at(spans, pos)
        return raw

    for match in _REF_RE.finditer(both):
        word, star, first, trailing = match.groups()
        kind = "Table" if word.lower().startswith("table") else "Figure"
        key = f"{kind} S" if star else kind
        have = defined.get(key, set())
        if not have:
            continue                    # no captions of this kind at all; not our call
        for num in _expand(int(first), trailing):
            if num in have:
                continue
            label = f"{kind} {'S' if star else ''}{num}"
            defects.append(CrossrefDefect(
                "unresolved", label,
                f"{label} is referred to and never defined. The captions present run "
                f"{min(have)}-{max(have)}. A pointer to nothing is a reader sent to a "
                f"page that is not there.",
                _anchor(match.start())))

    for match in _SECTION_REF_RE.finditer(both):
        letter, first, trailing = match.groups()
        key = f"Supplement {letter.upper()}"
        have = defined.get(key, set())
        if not have:
            continue
        for num in _expand(int(first), trailing):
            if num in have:
                continue
            label = f"Supplement {letter.upper()}{num}"
            defects.append(CrossrefDefect(
                "unresolved", label,
                f"{label} is referred to and never defined. The sections present run "
                f"{min(have)}-{max(have)}.",
                _anchor(match.start())))

    # An unnamed pointer. Nothing downstream can resolve it, which is exactly why no
    # resolver was ever going to report it.
    for match in _VAGUE_POINTER_RE.finditer(both):
        phrase = " ".join(match.group(0).split())
        defects.append(CrossrefDefect(
            "unnamed", phrase,
            f"\"{phrase}\" points at the paper's own material and names nothing, so "
            f"there is no target to follow and no gate that can resolve it. Name the "
            f"section, table or figure, or drop the pointer and report the thing here.",
            _anchor(match.start())))

    # Contiguity. A gap is what a removed section leaves behind, and it is visible to a
    # reader as a missing page rather than as a broken link.
    for key, nums in sorted(defined.items()):
        ordered = sorted(nums)
        missing = [n for n in range(1, ordered[-1] + 1) if n not in nums]
        if missing:
            defects.append(CrossrefDefect(
                "gap", key,
                f"{key} numbering skips {', '.join(str(n) for n in missing[:6])}. The "
                f"sequence runs to {ordered[-1]}, so a reader counts a missing item "
                f"rather than a renumbered one. Renumber the rest down."))

    reasons = []
    unresolved = sorted({d.label for d in defects if d.kind == "unresolved"})
    if unresolved:
        reasons.append(
            f"{len(unresolved)} cross-reference(s) resolve to nothing: "
            f"{', '.join(unresolved[:6])}. Cutting a section renumbers everything "
            f"below it, and this is what is left when a pointer is missed.")
    unnamed = [d for d in defects if d.kind == "unnamed"]
    if unnamed:
        reasons.append(
            f"{len(unnamed)} pointer(s) name no target: "
            f"{', '.join(sorted({d.label for d in unnamed})[:6])}. A reader is sent "
            f"somewhere and there is nowhere to go.")
    gaps = [d for d in defects if d.kind == "gap"]
    if gaps:
        reasons.append(
            f"{len(gaps)} numbering sequence(s) have gaps: "
            f"{', '.join(d.label for d in gaps)}. A gap reads as a lost item.")

    return CrossrefReport(
        defined={k: sorted(v) for k, v in defined.items()},
        defects=defects, passed=not reasons, reasons=reasons)
