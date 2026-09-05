"""Control-flow exceptions shared across the harness.

Three failure classes, and which one a stage raises decides what happens to the unit
of work:

  * `RevisionNeeded` — bounded loop. The proposal is wrong but the machine is fine;
    it goes back through the model with feedback, up to the cap.
  * `QuotaExceeded` — come back later. Never a failure; the engine backs off and
    retries on a later cycle.
  * `RuntimeError` (plain, from anywhere) — a stall. The unit records what went wrong,
    waits, and is retried on a doubling backoff, indefinitely. The alternative is a
    terminal park, on the argument that retrying a confidently wrong proposal only
    burns budget — which is true of retrying it *immediately*, and is the whole reason
    the backoff exists rather than the reason to abandon a manuscript.
"""


class RevisionNeeded(Exception):
    """A proposal should be produced again. Carries human-readable feedback that is
    fed back to the model verbatim on the next attempt."""

    def __init__(self, reason, feedback=""):
        super().__init__(reason)
        self.feedback = feedback


class QuotaExceeded(Exception):
    """The model backend hit a rate limit or an allowance ceiling and wants us to come
    back later.

    Deliberately NOT a RuntimeError: a RuntimeError out of a stage stalls the unit and
    records an error, and a quota hit is neither an error nor a reason to record one.
    It means 'come back later' — the engine defers, backs off, and retries, so a
    ceiling costs time and nothing else. Carries the backend's retry-after hint in
    seconds when one is supplied.

    `source` says which backend, as a field rather than something a reader infers from
    the message. Two modules agreeing on a substring of an error string is not a
    contract; a field is.
    """

    def __init__(self, reason, retry_after=None, source="model"):
        super().__init__(reason)
        self.retry_after = retry_after
        self.source = source
