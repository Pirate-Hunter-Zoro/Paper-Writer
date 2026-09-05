"""One module per stage of the pipeline, in pipeline order.

    evidence       mine the results and sources into cited evidence; gate coverage;
                   freeze.
    grounding      fix the terminology, the estimand, the reader, the checklist and
                   the prose conventions, before anything is planned.
    planning       evidence + grounding -> a validated project plan and a seeded
                   ledger.
    argument       one paper's claims -> a gated map of claim to section to evidence.
    outlining      the argument map -> a gated section list with a paragraph plan and
                   a topic sentence for every paragraph.
    drafting       a focused brief -> one section draft in staging.
    review         one editorial pass that finds defects AND writes their repairs.
    patching       apply those repairs as exact find/replace edits.
    surgery        replace one anchored passage when a repair needs new prose.
    ledger_update  an accepted section's proposed ledger updates, validated + merged.
    building       accepted sections -> manuscript.md, audited, then converted.
    delivery       the manuscript and its builds -> the output folder, atomically.

Every stage follows the same four beats and in the same order: propose (models/),
validate (gates/ and memory/), apply atomically (infra/storage), and leave the
journalling to the engine. A stage raises RuntimeError for a deterministic failure,
RevisionNeeded when the draft should go round again, and QuotaExceeded when it should
simply be tried later.

A stage never writes the journal and never decides what state a unit moves to — that
is the engine's job, and keeping it out of here is what makes a stage a function you
can test with fixtures.
"""


def correction_brief(errors, attempt, attempts):
    """What a model is told after its proposal failed a deterministic gate.

    Planning, the argument map and outlining are each judged by a strict structural
    gate — a plan needs exactly one headline claim per paper, an outline needs
    contiguous numbering, IMRaD order, budgets inside the venue's limit and a topic
    sentence for every paragraph. Each used to get exactly one attempt, and a
    rejection parked the whole project.

    That is the same mistake the editorial loop made and paid for: a rejection the
    proposer is never shown cannot be fixed, so the choice was between a gate loose
    enough to always pass and a coin flip on a manuscript. Neither is a gate. Here the
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
