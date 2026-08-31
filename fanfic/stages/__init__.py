"""One module per stage of the pipeline, in pipeline order.

    research      mine the source wikis into cited canon; gate coverage; freeze.
    planning      canon + prompt -> a validated series plan and a seeded bible.
    outlining     a book's slot in the plan -> a gated chapter list.
    drafting      a focused digest -> one chapter draft in staging.
    critique      three critics; all three must pass or the chapter revises.
    bible_update  an accepted chapter's proposed bible updates, validated + merged.
    illustration  locked reference sheets, then scene renders that reuse them.
    binding       accepted chapters + images -> a validated .epub.
    delivery      the .epub -> iCloud Books, atomically.

Every stage follows the same four beats and in the same order: propose (models/),
validate (gates/ and memory/), apply atomically (infra/storage), and leave the
journalling to the engine. A stage raises RuntimeError for a deterministic failure,
RevisionNeeded when the draft should go round again, and QuotaExceeded when it
should simply be tried later.

A stage never writes the journal and never decides what state a unit moves to —
that is the engine's job, and keeping it out of here is what makes a stage a
function you can test with fixtures.
"""


def correction_brief(errors, attempt, attempts):
    """What a model is told after its proposal failed a deterministic gate.

    Planning and outlining are each judged by a strict structural gate — a plan needs
    a voice and an appearance for every character, an outline needs a monotonic
    timeline, contiguous numbering, no orphaned thread, and no payoff without a prior
    setup across all 37 chapters. Both used to get exactly one attempt, and a
    rejection parked the entire series.

    That is the same mistake the chapter loop made and paid for: a rejection the
    proposer is never shown cannot be fixed, so the choice was between a gate loose
    enough to always pass and a coin flip on a novel. Neither is a gate. Here the
    errors go back with the request, which is the cheapest possible fix — these are
    exactly the failures a model corrects on being told, because they are mechanical
    rather than matters of judgement.

    Bounded, and the bound is small on purpose: a proposal that fails three times with
    the errors in hand is failing for a reason re-rolling will not reach, and the park
    is then genuinely informative rather than a lost coin toss."""
    listed = "\n".join(f"  - {e}" for e in errors[:12])
    return (f"\n\n{'=' * 70}\nYOUR PREVIOUS ATTEMPT WAS REJECTED "
            f"(attempt {attempt} of {attempts})\n{'=' * 70}\n"
            f"A deterministic validator — not a matter of taste — found these "
            f"problems:\n{listed}\n\n"
            "Produce the whole document again, corrected. Keep everything the "
            "validator did not object to: it passed, and changing it risks breaking "
            "something that currently works. Fix precisely the listed problems.\n")
