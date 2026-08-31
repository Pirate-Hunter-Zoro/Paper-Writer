"""The three-layer memory — the answer to hard problem 1 (novel-length coherence).

Coherence cannot live in a model's context window, so it lives on disk as
structured state:

  * canon        — cited facts, frozen after research. IMMUTABLE ground truth.
  * series bible — cross-book arcs, the relationship graph, the foreshadowing ->
                   payoff ledger, the master timeline, and the LOCKED visual
                   reference sheets. MUTABLE but append-validated.
  * book bible   — a derived working slice, reconstructable from the series bible.

`bible` holds the schemas and the merge gatekeeper. `digest` is the other half of
the idea: the writer is never handed the whole memory, only a tight slice of it.
"""
