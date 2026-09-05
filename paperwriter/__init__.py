"""Paper-Writer — a manuscript factory for academic writing.

One sentence holds the whole design up:

    the model proposes; a deterministic harness disposes.

The package is layered so that sentence is enforced by the import graph, not by
good intentions. Every layer may import the ones above it and never the ones
below:

    config, paths, errors     what and where. No I/O, no logic.
    infra/                    durable plumbing: journal, atomic storage, locks,
                              budget, logging. Knows nothing about papers.
    memory/                   the three-layer memory (evidence / project ledger /
                              paper ledger) and the writer's digest.
    gates/                    the deterministic validators — evidence coverage,
                              outline structure, sentence and paragraph shape,
                              terminology, citations, numbers. Pure arithmetic and
                              set logic; no model, no I/O.
    models/                   THE ONLY place an external model is reached.
                              Every call writes an artifact to a file we read.
    stages/                   one module per stage of the pipeline. Each stage
                              proposes (via models/), validates (via gates/ and
                              memory/), then applies atomically (via infra/).
    engine/                   the nested project -> paper -> section state machine.
    daemons/                  the two long-running entry points. Thin: a lock, a
                              loop, and a call into engine/.

`models/` is therefore the only layer that can be wrong in an interesting way,
and nothing in it has the authority to mutate committed state.

Why a harness at all, for prose a person could write themselves. Two reasons, and
neither is speed.

The first is that a language model asked for a Methods section will invent a
number. Not often, and never obviously: it will round 0.712 to 0.71, promote a
subgroup AUC to the headline, or describe a cohort of 42,579 as "approximately
forty thousand" three paragraphs after stating the exact figure. Every number in
a drafted section is checked against the evidence ledger by `gates/numbers.py`,
and one that is not in the ledger is a blocking defect. A model cannot argue with
arithmetic.

The second is that good prose is measurable in the specific ways it usually goes
wrong. Mean sentence length, the share of sentences past thirty-five words, the
semicolon and em-dash rate, a paragraph with no topic sentence, a second name for
something already named — these are countable, and counting them is how the
one-read rule stops being a slogan. `gates/sentences.py`, `gates/paragraphs.py`
and `gates/terminology.py` do that counting, and the editorial loop repairs what
they find, one anchored edit at a time.
"""
