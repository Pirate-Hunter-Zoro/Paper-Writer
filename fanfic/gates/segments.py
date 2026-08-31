"""Scene segmentation — splitting a chapter at its changes of place and time.

A chapter is not one continuous stretch of prose. It moves: a kitchen at dinner, then
a workshop after dark, then a clearing the next morning. Those are the units the rest
of the pipeline needs, and until now nothing in this project could see them, because
nothing asked the writer to mark them. Chapter 1 of the first attempt had five distinct
settings and zero separators, so every downstream stage had a single undifferentiated
block to work with — which is why its illustrations were chosen from the chapter as a
whole and stacked at the end of it.

The harness cannot split what the writer never separated. So the writer emits an
explicit break line at every change of place or time, and this module turns those into
segments. Everything per-scene downstream — which moments get drawn, where each picture
is placed in the epub, which interaction belongs where — is defined over them.

Pure functions: no I/O, no model, no config beyond a threshold. What a marker is, and
whether a chapter has enough of them.

**On the marker and the repair anchors.** The editorial loop's whole mechanism is a
`find` copied character-for-character out of the chapter, applied only when it matches
exactly once. Break lines are ordinary text to that mechanism, so they cost nothing:
an anchor drawn from prose is unaffected, and an anchor that swallowed a marker would
be refused as ambiguous rather than misapplied — the same protection every repeated
sentence already gets. Adding a break is itself an ordinary edit, which is what lets a
chapter that arrives unsegmented be repaired rather than redrafted.
"""

from dataclasses import dataclass

from .. import config

# What the writer is asked to emit. Three asterisks on their own line: the oldest
# scene-break convention in print, unambiguous in Markdown, and impossible to produce
# by accident in prose.
MARKER = "* * *"

# Accepted on input, though. A model asked for `* * *` will sometimes give `***` or a
# rule of dashes, and rejecting a chapter over which divider it chose would spend an
# editorial pass on nothing.
_SYMBOLS = "*#-~=•_"


def is_marker(line):
    """Whether one line is a scene break rather than prose.

    A line of at least three copies of a single divider symbol, spaces ignored. The
    single-symbol rule is what keeps `**bold**` and an em-dashed aside out: those carry
    letters, so the set of characters is not one."""
    core = "".join(line.split())
    if len(core) < 3:
        return False
    return len(set(core)) == 1 and core[0] in _SYMBOLS


def split(prose):
    """A chapter's prose as its list of scene segments, markers removed.

    Empty stretches are dropped, so a doubled break or a marker at either end is
    harmless rather than an empty segment nothing can illustrate."""
    segments, current = [], []
    for line in (prose or "").splitlines():
        if is_marker(line):
            chunk = "\n".join(current).strip()
            if chunk:
                segments.append(chunk)
            current = []
        else:
            current.append(line)
    chunk = "\n".join(current).strip()
    if chunk:
        segments.append(chunk)
    return segments


def strip_markers(prose):
    """The prose with its break lines removed — for anything counting or rendering
    words rather than scenes."""
    return "\n".join(line for line in (prose or "").splitlines()
                     if not is_marker(line))


@dataclass
class SegmentReport:
    segments: int
    passed: bool
    reason: str


def check(prose):
    """Gate a chapter on having scene breaks at all.

    A floor rather than a count: how many times a chapter changes place is a story
    decision. Zero is not — a chapter that never separates its settings is one the
    writer did not mark up, and every per-scene mechanism downstream silently degrades
    to treating the whole chapter as one moment."""
    found = len(split(prose))
    floor = max(1, config.CHAPTER_MIN_SEGMENTS)
    if found >= floor:
        return SegmentReport(found, True, "")
    return SegmentReport(
        found, False,
        f"the chapter has {found} scene segment(s) and needs at least {floor}. Every "
        f"change of place or time must be separated by a line containing exactly "
        f"`{MARKER}`. This is a mechanical omission, not a prose defect: fix it with "
        f"anchored edits that append the break line to the last sentence before each "
        f"shift. Do not rewrite the scenes. The segments are what the illustrations "
        f"are chosen from and where they are placed in the finished book, so a "
        f"chapter with none of them gets its pictures chosen from an average of "
        f"everything that happens in it.")
