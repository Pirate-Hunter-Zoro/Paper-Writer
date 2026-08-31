"""Fanfiction-Writer — an illustrated-novel factory.

One sentence holds the whole design up:

    the model proposes; a deterministic harness disposes.

The package is layered so that sentence is enforced by the import graph, not by
good intentions. Every layer may import the ones above it and never the ones
below:

    config, paths, errors     what and where. No I/O, no logic.
    infra/                    durable plumbing: journal, atomic storage, locks,
                              budget, logging. Knows nothing about novels.
    memory/                   the three-layer memory (canon / series bible /
                              book bible) and the writer's digest.
    gates/                    the deterministic validators — canon coverage,
                              outline structure, readability. Pure arithmetic
                              and set logic; no model, no I/O.
    models/                   THE ONLY place an external model is reached.
                              Every call writes an artifact to a file we read.
    stages/                   one module per stage of the pipeline. Each stage
                              proposes (via models/), validates (via gates/ and
                              memory/), then applies atomically (via infra/).
    engine/                   the nested series -> book -> chapter state machine.
    daemons/                  the four launchd entry points. Thin: a lock, a
                              loop, and a call into engine/.

`models/` is therefore the only layer that can be wrong in an interesting way,
and nothing in it has the authority to mutate committed state.
"""
