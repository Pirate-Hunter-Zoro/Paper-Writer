"""The nested project -> paper -> section state machine.

Split by level, because that is how the machine is actually reasoned about:

    admission   inbox -> a project unit (and reviving a stuck one on re-drop).
    project     PROMPT_DROPPED -> ... -> PROJECT_COMPLETE.
    paper       QUEUED -> ... -> COMPLETED, one step per call.
    section     the bounded editorial loop for a single section.
    revising    the whole-manuscript sweep over the sections that shipped flawed.
    stalling    what happens instead of failing: record, wait, retry, forever.
    cycle       one turn of the engine: admit, budget-gate, advance one project.

The invariants the whole design rests on live in this layer, not in the stages:

  * budget-gated — nothing starts if the allowance is exhausted; the engine idles.
  * one meaningful step per cycle, so a runaway can never silently drain spend.
  * verify before commit, and journal the verified state. A stage validates and
    applies atomically before its record advances, so a crash resumes at the first
    incomplete unit with no double work.
  * **nothing is terminal.** A unit that cannot advance stalls, and a stalled unit is
    retried on a doubling backoff indefinitely. A section that cannot be made clean
    ships holding its notes rather than parking. There is no state a person has to
    clear by hand, and re-dropping a prompt is a "try again now" rather than a repair.
"""
