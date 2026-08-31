"""Loading the three layers off disk, in one place.

`bible.py` is schemas and rules; `digest.py` is pure assembly of already-loaded
state. Neither of them reads a file, deliberately — that is what makes the gatekeeper
and the writer's brief testable with fixtures and nothing else.

Which leaves the reading itself, and it was being done three times: drafting loaded
the plan, the bible, and every universe's canon to build its digest; critique and the
bible merge each did their own partial version, or worse, handed the model a path and
told it to go and read the file itself. Three copies of "which files are the memory"
is three chances for one of them to be reading a stale or different set.

So: one loader, returning one record. It reads, it does not interpret — every rule
about what the memory *means* stays in `bible.py`, and every decision about what a
given model is shown stays in `digest.py`.
"""

from .. import config, paths
from ..infra import storage
from .bible import new_canon


class Memory:
    """Everything on disk about one series, loaded once.

    Attributes are the three layers plus the plan-derived writing targets:

      * `bible`        — the series bible (cast, ledger, timeline, invented facts)
      * `canon`        — {universe: canon document}, immutable ground truth
      * `plan`         — the series plan
      * `style_guide`  — the voice/tone/rating block the writer works inside
      * `chapter_floor` — the fewest words that count as a chapter

    There is deliberately no per-chapter word *target* here any more. There was one,
    derived from the book's total words over its chapter count, and it was handed to
    the writer as the size to hit and to the length gate as the number to enforce.
    Both of those were mistakes in the same direction: a model asked for a specific
    large number of words, having already told its story, pads — and the cheapest
    padding is the POV character reflecting on her own dialogue. The floor is the only
    number worth keeping, it is absolute, and it lives in config.
    """

    def __init__(self, bible, canon, plan, style_guide, chapter_floor):
        self.bible = bible
        self.canon = canon
        self.plan = plan
        self.style_guide = style_guide
        self.chapter_floor = chapter_floor


def load(series_rec, book_num=None):
    """Load one series' memory. `book_num` selects the book for per-book state."""
    sid = series_rec["series_id"]
    plan = storage.load_json(paths.plan_path(sid), {})
    bible = storage.load_json(paths.series_bible_path(sid), {})
    canon = {u: storage.load_json(paths.canon_path(u), new_canon(u))
             for u in series_rec.get("universes", [])}

    return Memory(plan=plan, bible=bible, canon=canon,
                  style_guide=plan.get("style_guide",
                                       "third-person limited, past tense"),
                  chapter_floor=config.CHAPTER_MIN_WORDS)
