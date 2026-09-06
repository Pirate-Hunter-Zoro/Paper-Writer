"""Splitting — the assembled document, also written one file per section.

The whole manuscript is the artifact. It is also the wrong unit for almost everything a
person does with it after it is written: sending the Methods to a coauthor who only
wrote the Methods, diffing one section across two drafts, pasting the Discussion into a
reply to a reviewer, or handing a statistician the Results without the other eleven
thousand words around it. Every one of those was previously a scroll-and-select.

So the pipeline writes both. The assembled document stays the artifact and nothing
downstream reads the parts; the parts are an output, produced from the whole, and a
split that disagrees with its source is a bug in this module rather than a second
version of the paper.

**One file per top-level section, and only top-level.** A `##` subsection stays inside
its parent, because the useful unit is the one a coauthor is responsible for and nobody
is responsible for *Model calibration* alone. The exception is a document with no `#`
headings at all, which is split on `##` instead so a supplement of `## S1.1`-style
subsections does not come out as one file.

**Numbered in reading order, named after the heading.** `04-methods.md` sorts the way
the paper reads, which a directory listing otherwise destroys the moment a section is
called *Abstract* and another *Results*. The number is the position, not an id: it
changes when a section moves, and that is correct, because these are derived files.

**Every part carries a header saying what it is part of.** A section file that arrives
by email with no indication that it is one section of one draft of one paper is a
document somebody will edit and hand back, and then there are two sources of truth. The
header says which document, which position, and that edits belong upstream.
"""

import re

from .. import paths
from ..infra import storage

# A top-level heading, and its text. Setext headings are not used anywhere in this
# project's documents and are deliberately not supported: a splitter that guesses is a
# splitter that produces a file nobody expected.
_H1 = re.compile(r"^#\s+(.+?)\s*$", re.M)
_H2 = re.compile(r"^##\s+(.+?)\s*$", re.M)


def _slug(text, limit=48):
    """A filename fragment: lowercase, hyphenated, no punctuation, bounded."""
    out = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return (out[:limit].rstrip("-") or "section")


def _fence_mask(text):
    """Character positions inside a fenced code block, which are not headings.

    A supplement reproduces verbatim prompts and patient narratives inside fences, and
    one of them opens a line with `#`. Splitting there cuts a document in half at a
    comment character."""
    spans, open_at = [], None
    for m in re.finditer(r"^```.*$", text, re.M):
        if open_at is None:
            open_at = m.start()
        else:
            spans.append((open_at, m.end()))
            open_at = None
    if open_at is not None:
        spans.append((open_at, len(text)))
    return spans


def _outside(pos, spans):
    return not any(lo <= pos < hi for lo, hi in spans)


def split(text, level=None):
    """A document as [(heading, body)], in reading order.

    `level` forces `#` or `##`; by default a document with `#` headings splits on those
    and one without splits on `##`."""
    text = text or ""
    fences = _fence_mask(text)
    pattern = _H1 if level in (None, 1) else _H2
    marks = [m for m in pattern.finditer(text) if _outside(m.start(), fences)]
    if not marks and level is None:
        marks = [m for m in _H2.finditer(text) if _outside(m.start(), fences)]
    if not marks:
        return []

    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(1).strip(), text[m.start():end].rstrip() + "\n"))
    return out


def _header(document_name, index, total, heading):
    """The comment every part carries, so a part cannot be mistaken for a whole."""
    return (f"<!--\n"
            f"Section {index} of {total} of {document_name}.md, split out by the\n"
            f"Paper-Writer pipeline. DERIVED FILE: the assembled document is the\n"
            f"source of truth and this is produced from it, so an edit made here is\n"
            f"lost the next time the paper is built. Edit {document_name}.md.\n"
            f"\n"
            f"Section heading: {heading}\n"
            f"-->\n\n")


def write(source, out_dir, log_fn=None):
    """Split one Markdown document into `out_dir`. Returns the paths written.

    The directory is cleared of previously written parts first, so a section that was
    renamed or removed upstream does not survive as an orphan file that still looks
    current."""
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        return []

    parts = split(text)
    # One part is not a split, it is a copy under a worse name. A cover letter has no
    # top-level headings at all and a checklist has exactly one, and neither is helped
    # by a `parts/` directory holding a duplicate of itself.
    if len(parts) < 2:
        return []

    name = source.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in list(out_dir.glob("*.md")) + list(out_dir.glob("*.docx")):
        stale.unlink()

    written = []
    for i, (heading, body) in enumerate(parts, start=1):
        path = out_dir / f"{i:02d}-{_slug(heading)}.md"
        storage.atomic_write_text(_header(name, i, len(parts), heading) + body, path)
        written.append(path)
    if log_fn:
        log_fn(f"split {source.name} into {len(written)} part(s) under "
               f"parts/{out_dir.name}/")
    return written


def run(project_id, paper_num, log_fn=None):
    """Split every document this paper produced. Returns the paths written."""
    written = []
    for source in paths.documents(project_id, paper_num):
        written += write(source, paths.parts_dir(project_id, paper_num, source.stem),
                         log_fn=log_fn)
    return written
