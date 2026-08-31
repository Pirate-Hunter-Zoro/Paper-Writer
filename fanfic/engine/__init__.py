"""The nested series -> book -> chapter state machine.

Split by level, because that is how the machine is actually reasoned about:

    admission     inbox -> a series unit (and reviving a FAILED one on re-drop).
    series        PROMPT_DROPPED -> ... -> SERIES_COMPLETE.
    book          QUEUED -> ... -> COMPLETED, one step per call.
    chapter       the bounded revision loop for a single chapter.
    illustrating  driving the image queue for a book; no slot is ever given up on.
    cycle         one turn of the engine: admit, budget-gate, advance one series.

The invariants the whole design rests on live in this layer, not in the stages:

  * budget-gated — nothing starts if the API budget is exhausted; the engine idles.
  * one meaningful step per cycle, so a runaway can never silently drain spend.
  * verify before commit, and journal the verified state. A stage validates and
    applies atomically before its record advances, so a crash resumes at the first
    incomplete unit with no double work.
  * FAILED is terminal and never auto-retried. Retry is a human gesture: move the
    prompt back into inbox/, which revives the series from its last good state.
"""
