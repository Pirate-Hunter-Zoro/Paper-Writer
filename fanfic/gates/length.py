"""The length gate — a hard, deterministic floor under what counts as a chapter.

Short is the failure nothing else here can see. A 1,400-word chapter can be
word-perfect on canon, clean on continuity, and sit dead centre of the readability
band; a book of them is half a book with every gate green and no record anywhere of
what went wrong. So there is a floor, and it blocks.

**It is a floor and not a target, and that distinction is the whole point of this
module's current shape.** It used to be a ratio against a per-chapter word target
derived from the book's total — 198,000 words over 37 chapters, so 5,351 each, pass at
75% of that. The gate worked exactly as designed and the design was wrong. Asked for
5,351 words in one call the writer returns about 2,681 good ones, so the gate fired on
chapter after chapter and sent each one back for a continuation pass to make up the
difference; and for a model that has already told the story it planned to tell, the
cheapest way to reach a word count is a character reflecting on what she just said.
The target did not fail to produce depth. It produced interiority, at length, on
purpose, because that is what it asked for.

What is left is the one claim worth enforcing: this is a chapter rather than a scene.
Nothing above the floor is the gate's business, and there is no ceiling — a chapter
that runs long is a chapter.
"""

from dataclasses import dataclass

from .. import config


@dataclass
class LengthReport:
    words: int
    floor: int
    passed: bool
    reason: str


def check(words, floor=None):
    """Gate a chapter's word count against the absolute floor.

    `words` is the count already computed by the readability pass, so this costs
    nothing. `floor` is overridable for tests; a floor of zero disables the gate."""
    floor = config.CHAPTER_MIN_WORDS if floor is None else floor
    if not floor or floor <= 0:
        return LengthReport(words, 0, True, "")

    if words >= floor:
        return LengthReport(words, floor, True, "")

    return LengthReport(
        words, floor, False,
        f"the chapter is {words:,} words and the floor is {floor:,}. This is the one "
        f"rejection that is NOT surgery on existing prose: the chapter is not too "
        f"wordy, it is missing material. Find the beats it summarised in a sentence "
        f"and play them out as scenes — dialogue, action, physical detail, another "
        f"character in the room having their own reaction. Do not pad sentences, add "
        f"adjectives, or give the POV character a paragraph about how she feels "
        f"about what she just said; that is the failure this floor replaced a word "
        f"target to stop producing. Every word you add should be something the "
        f"reader gets to watch.")
