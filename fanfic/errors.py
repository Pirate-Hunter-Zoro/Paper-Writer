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
    """A backend hit a rate limit / quota and wants us to come back later.

    Deliberately NOT a RuntimeError: a RuntimeError out of an illustration stage
    parks the unit, but a quota hit must never fail a book. It means 'come back
    later' — the engine defers the remaining images, keeps the book in
    ILLUSTRATING, backs off, and retries, so a limited tier just means images
    trickle in over time. Carries the API's retry-after hint in seconds when one
    is supplied.

    `source` says WHICH backend, and it is a field rather than something the reader
    infers from the message. `engine/cycle.py` has to tell them apart — an image
    ceiling thins a book while a model ceiling stops it, and only the second is worth
    telling a human about — and it used to do that by testing for the substring
    "spend/quota limit" in the message. No raise site has ever produced that string:
    the text backend raises "... allowance ceiling: ...". So the model-side branch was
    dead code, and every Claude session limit was announced as "image quota/rate limit
    reached; deferring remaining images ... writing unaffected" — naming the wrong
    backend, taking the wrong backoff, and omitting the one line that says a human may
    need to act. Seen live on 2026-09-01: 44 minutes of that message while the thing
    actually waiting was the writer.

    Two modules agreeing on a substring is not a contract. This is."""

    def __init__(self, reason, retry_after=None, source="image"):
        super().__init__(reason)
        self.retry_after = retry_after
        self.source = source
