"""Figure layout — the two ways a figure that exists still ruins the page.

Neither is about whether the image is there. `stages.building.figures_lost` answers
that, by opening the built .docx and counting. This gate is about what the image does
to the page once it arrives, and it is arithmetic against one number: the printable
width of the venue's reference document.

**A figure with no width.** Pandoc honours absolute widths in a .docx and ignores
percentages, so an image with no `{width=...in}` attribute is imported at full page
width. One such figure pushes a section's text off its own page, and it looks like a
formatting accident rather than a missing attribute.

**A row of panels wider than the page.** Multi-panel figures are laid out as borderless
two-column tables, so each panel's label sits above its own panel. Word does not refuse
a row that does not fit — it shrinks the columns, and the panels stop lining up with the
labels that name them. Which is exactly the failure the table layout existed to prevent.

Images on one LINE are one row, because that is what the two-column table puts side by
side. This gate is pure: the caller measures the reference document and passes the
number in.
"""

import re

# `![alt](target)` with an optional attribute block. The alt text is almost always
# empty in this project's documents, but a gate that only matched the empty form would
# be silent on the first figure somebody captions.
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]*)\)(?:\{([^}]*)\})?")

_WIDTH_RE = re.compile(r"width=([0-9.]+)in")

# Word's default cell margin is 0.08in a side, so a two-column figure table spends this
# much of the printable width on padding rather than on image.
CELL_PADDING_IN = 0.32

# US Letter with 1.25in margins. Used when the reference document cannot be measured,
# which is a wrong answer but a conventional one, and better than declining to check.
DEFAULT_TEXT_WIDTH_IN = 6.0


def widths_on(line):
    """(image target, declared width in inches or None) for every image on one line."""
    return [(target.strip(), _declared_width(attrs))
            for target, attrs in _IMAGE_RE.findall(line)]


def _declared_width(attrs):
    match = _WIDTH_RE.search(attrs or "")
    return float(match.group(1)) if match else None


def check(text, name, text_width_in=DEFAULT_TEXT_WIDTH_IN):
    """Every figure-layout problem in one document, as lines a person can act on.

    `name` is what to call the document in the message, and the line number is the
    line in `text`. Returns an empty list for a document with no figures, which is
    most of them."""
    problems = []
    for lineno, line in enumerate(text.split("\n"), start=1):
        images = widths_on(line)
        if not images:
            continue
        for target, width in images:
            if width is None:
                problems.append(
                    f"{name}:{lineno}: figure has no width= attribute, so it is "
                    f"imported at full page width: {target}")
        declared = [w for _, w in images if w is not None]
        if len(declared) != len(images):
            continue                    # already reported; the sum would be a lie
        budget = text_width_in - (CELL_PADDING_IN if len(images) > 1 else 0.0)
        total = sum(declared)
        if total > budget + 1e-9:
            problems.append(
                f"{name}:{lineno}: figure row is {total:.2f}in wide but only "
                f"{budget:.2f}in fits ({len(images)} panel(s))")
    return problems
