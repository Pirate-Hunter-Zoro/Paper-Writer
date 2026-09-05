"""The three-layer memory — the answer to coherence across a whole manuscript.

Coherence cannot live in a model's context window, so it lives on disk as
structured state:

  * evidence       — cited facts, frozen after gathering. IMMUTABLE ground truth,
                     and the only place a number in the manuscript may come from.
  * project ledger — the terminology lock, the claim ledger, the reference list, the
                     prose conventions, and the open-question register. MUTABLE, but
                     only through the gatekeeper, and only all-or-nothing.
  * paper ledger   — a derived working slice, reconstructable from the project
                     ledger and the accepted sections.

`ledger` holds the schemas and the merge gatekeeper. `digest` is the other half of
the idea: the writer is never handed the whole memory, only a tight slice of it, and
the slice is exhaustive about the one thing that must not be improvised — which
numbers this section is allowed to write.
"""
