"""Control-flow exceptions shared across the fleet.

Three failure classes, and which one a stage raises decides what happens to the
unit of work:

  * `RevisionNeeded` — bounded loop. The draft is wrong but the machine is fine;
    the chapter goes back through the writer with feedback, up to the cap.
  * `QuotaExceeded` — come back later. Never a failure; the engine backs off and
    retries on a later cycle.
  * `RuntimeError` (plain, from anywhere) — a stall. The unit records what went
    wrong, waits, and is retried on a doubling backoff, indefinitely. It used to be
    a terminal park, on the argument that retrying a confidently wrong proposal only
    burns budget — which is true of retrying it *immediately*, and is the whole
    reason the backoff exists rather than the reason to abandon a novel.
"""


class RevisionNeeded(Exception):
    """A chapter should be redrafted. Carries human-readable feedback that is fed
    back to the writer verbatim on the next attempt."""

    def __init__(self, reason, feedback=""):
        super().__init__(reason)
        self.feedback = feedback


class QuotaExceeded(Exception):
    """The image backend hit a rate limit / quota (HTTP 429, RESOURCE_EXHAUSTED).

    Deliberately NOT a RuntimeError: a RuntimeError out of an illustration stage
    parks the unit, but a quota hit must never fail a book. It means 'come back
    later' — the engine defers the remaining images, keeps the book in
    ILLUSTRATING, backs off, and retries, so a limited tier just means images
    trickle in over time. Carries the API's retry-after hint in seconds when one
    is supplied."""

    def __init__(self, reason, retry_after=None):
        super().__init__(reason)
        self.retry_after = retry_after
