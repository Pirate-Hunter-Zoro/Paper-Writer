"""The length gate — a band around what a section was budgeted to be.

Academic length is a CEILING, and that is where this inverts from every length gate
written for fiction. A journal that says 4,000 words means it, and a manuscript over
the limit is desk-rejected before a reviewer reads a sentence. So the ceiling blocks,
and it blocks hard.

The floor blocks too, for the opposite reason. A section at 55% of its planned length
has not been written concisely; it has dropped a claim. The outline said this section
carries four claims and this many words of support, and prose that comes in far under
that is prose where one of the four was asserted in a clause and never supported.

**Both ends are relative to the outline's budget, not to a constant.** A Methods
section and a Conclusions section have nothing in common except that both were
planned. The planner sets the number; this gate holds the plan to it.

**On what the failure means, and why the gate says so.** Over-budget and under-budget
need opposite repairs, and an editor told only "wrong length" will pick the cheap one
— which is padding when it should be cutting. So the reason names the repair:
over-budget is cut a claim or tighten sentences; under-budget is support a claim that
was only asserted, and specifically NOT add adjectives.
"""

import re
from dataclasses import dataclass

from .. import config
from . import prose
from .structure import phase_of


@dataclass
class LengthReport:
    words: int
    budget: int
    floor: int
    ceiling: int
    passed: bool
    reason: str


def check(words, budget=None):
    """Gate a section's word count against its planned budget.

    `words` is the count already computed by another gate, so this costs nothing.
    `budget` is the outline's plan for this section; absent, only the absolute floor
    applies, because a section nobody budgeted has no ceiling to break."""
    absolute = config.SECTION_MIN_WORDS

    if not budget or budget <= 0:
        if words >= absolute:
            return LengthReport(words, 0, absolute, 0, True, "")
        return LengthReport(
            words, 0, absolute, 0, False,
            f"the section is {words:,} words and the absolute floor is {absolute:,}. "
            f"This is not a section yet. It is missing support, not carrying bad "
            f"support: find the claims it states in a clause and give each one its "
            f"evidence, its number, and what follows from it. Do not add adjectives.")

    floor = max(absolute, int(budget * config.SECTION_UNDER_BUDGET_RATIO))
    ceiling = int(budget * config.SECTION_OVER_BUDGET_RATIO)

    if words > ceiling:
        return LengthReport(
            words, budget, floor, ceiling, False,
            f"the section is {words:,} words against a budget of {budget:,} "
            f"(ceiling {ceiling:,}). It is {words - budget:,} words over, and the "
            f"journal's limit is not negotiable. Cut, do not compress: find the claim "
            f"that is least load-bearing and delete it whole. Squeezing every "
            f"sentence to make room is how a section ends up needing to be read "
            f"three times.")

    if words < floor:
        return LengthReport(
            words, budget, floor, ceiling, False,
            f"the section is {words:,} words against a budget of {budget:,} "
            f"(floor {floor:,}). A section this far under its plan has dropped a "
            f"claim rather than said it briefly. Find the claim that is asserted in "
            f"a clause and never supported, and give it its evidence and its "
            f"consequence. Do not pad sentences and do not add hedges.")

    return LengthReport(words, budget, floor, ceiling, True, "")


# A figure the prose actually reports: a bare number, a percentage, a count with
# thousands separators. Not a section number and not a citation marker, both of which
# are addressing rather than reporting.
_REPORTED_NUMBER_RE = re.compile(r"(?<![\w.])[-+\u2212]?\d[\d,]*(?:\.\d+)?%?")

# A caption reports the figure, not the finding, and it is measured by its own rules.
_CAPTION_BLOCK_RE = re.compile(r"^\*\*\*.*?\*\s*$", re.MULTILINE | re.DOTALL)


@dataclass
class DensityReport:
    words: int
    numbers: int
    ratio: float
    passed: bool = True
    warnings: list = None

    def brief(self):
        return (f"{self.words} words of body prose, {self.numbers} reported figures, "
                f"{self.ratio:.1f} words per figure")


def density(text, section_name="", ceiling=None, phase=None):
    """How many words a Results section spends per number it reports.

    A Results section reports figures. The ratio of words to figures is therefore a
    measure of how much of it is reporting and how much is talking about the reporting,
    and it fell on every section of a real manuscript that was compressed by hand.

    It WARNS. A section that names its predictors rather than measuring them —
    suicidality, insomnia, obsessive-compulsive disorder — reports in words, scores
    around 20 here, and is correct; blocking would tell it to invent numbers. Captions
    are excluded because a caption describes a figure rather than reporting a result.

    Pass `phase` when the caller knows it. A results subsection is named "Model
    discrimination" and names no phase on its own, so the heading alone cannot
    distinguish it from a Discussion subsection named "Principal findings".

    Returns a DensityReport. Sections outside the results phase return an empty one."""
    ceiling = (config.RESULTS_WORDS_PER_NUMBER_WARN if ceiling is None else ceiling)
    # A results SUBSECTION is named "Model discrimination", not "Results", so
    # `phase_of` returns "" for almost every heading this needs to measure. Skipping on
    # anything but a positive match would skip the whole section. So the rule inverts:
    # measure unless the heading names a phase that is definitely not results.
    # A caller that knows the parent phase passes it, and it wins. "Principal
    # findings" is a Discussion subsection whose heading names no phase, so inferring
    # from the subsection alone would measure it and warn about prose that is meant to
    # carry no numbers.
    phase = phase if phase is not None else (phase_of(section_name) if section_name
                                             else "")
    if phase and phase != "results":
        return DensityReport(words=0, numbers=0, ratio=0.0, warnings=[])

    body = _CAPTION_BLOCK_RE.sub("", text or "")
    body = prose.strip_structure(body)
    words = len(body.split())
    if words < config.RESULTS_DENSITY_MIN_WORDS:
        return DensityReport(words=words, numbers=0, ratio=0.0, warnings=[])

    numbers = len(_REPORTED_NUMBER_RE.findall(body))
    ratio = words / max(numbers, 1)
    warnings = []
    if ratio > ceiling:
        warnings.append(
            f"{ratio:.0f} words per reported figure, over a soft ceiling of "
            f"{ceiling:.0f}. Not refused — a section that names its predictors rather "
            f"than measuring them reads this way and is right to. Worth a look if this "
            f"one reports numbers: at this ratio most of it is talking about the "
            f"results rather than giving them.")
    return DensityReport(words=words, numbers=numbers, ratio=round(ratio, 2),
                         passed=True, warnings=warnings)
