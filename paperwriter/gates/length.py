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

from dataclasses import dataclass

from .. import config


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
