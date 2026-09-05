"""Building. Assemble the accepted sections into a manuscript, then convert it.

Two steps, and the order matters because only one of them is allowed to fail.

**Assembly** concatenates the accepted sections in outline order under their headings,
prepends the front matter, and appends the reference list. It is pure string work
against files already on disk, it cannot fail for an external reason, and its output —
`manuscript.md` — *is* the deliverable. Everything after this point is a convenience.

**Conversion** hands that Markdown to pandoc, with the journal's reference document
supplying the styles when the job named one. It can fail for a dozen reasons that have
nothing to do with the manuscript: pandoc is not installed, the reference .docx is on
a volume that is not mounted, the filter is missing. So by default it does not block
delivery. A missing pandoc must never be the reason a finished paper is not delivered,
and the author can convert a Markdown file themselves in one command.

Set `PAPER_BUILD_REQUIRED=1` to invert that, for a workflow where the .docx is the
only artifact anyone will look at.

**The whole-manuscript checks run here.** Two gates cannot be run against a single
section and are run against the assembled document instead: a reference cited nowhere,
and a citation marker that resolves in one section against a reference list assembled
from all of them. They are reported and recorded, and — like conversion — they do not
block, because a paper that is finished except for one uncited reference should reach
its author rather than sit in a queue.
"""

import re
import subprocess

from .. import config, paths
from ..gates import citations, numbers, prose, sentences
from ..infra import storage
from ..memory import store


def _front_matter(plan, paper_num, ledger):
    """Title, authors, and the abstract's home, as a YAML block pandoc understands."""
    paper = {}
    for entry in plan.get("papers") or []:
        if entry.get("number") == paper_num:
            paper = entry
            break
    lines = ["---",
             f"title: \"{paper.get('title', 'Untitled')}\""]
    authors = plan.get("authors") or paper.get("authors")
    if authors:
        lines.append("author:")
        lines += [f"  - \"{a}\"" for a in (authors if isinstance(authors, list)
                                           else [authors])]
    if paper.get("venue"):
        lines.append(f"subtitle: \"Prepared for {paper['venue']}\"")
    keywords = paper.get("keywords") or []
    if keywords:
        lines.append("keywords: [" + ", ".join(f"\"{k}\"" for k in keywords) + "]")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _reference_list(ledger, used):
    """The reference list, numbered in order of first appearance in the manuscript.

    Numbered by first appearance rather than alphabetically because that is what a
    numbered-marker manuscript requires, and because renumbering at proof stage is
    where citations get detached from the sentences that meant them."""
    references = ledger.get("references") or {}
    if not references:
        return ""
    lines = ["", "# References", ""]
    for i, key in enumerate(used, start=1):
        entry = references.get(key)
        if not entry:
            continue
        bits = [entry.get("authors", ""), entry.get("title", ""),
                entry.get("venue", ""), str(entry.get("year", ""))]
        lines.append(f"{i}. " + ". ".join(b for b in bits if b)
                     + (f". doi:{entry['doi']}" if entry.get("doi") else ""))
    for key in sorted(set(references) - set(used)):
        entry = references[key]
        lines.append(f"- [UNCITED] {entry.get('title', key)} "
                     f"({entry.get('year', '')})")
    return "\n".join(lines) + "\n"


_ORDER_RE = re.compile(r"\[(\d+)\]")


def _citation_order(text):
    """Citation keys in order of first appearance."""
    seen, out = set(), []
    for match in _ORDER_RE.finditer(text):
        key = match.group(1)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def assemble(project_rec, paper_num, log_fn=None):
    """Concatenate the accepted sections into `manuscript.md`. Returns its path.

    A section that is missing from disk is written as a visible placeholder rather
    than skipped silently. A manuscript with a gap in it is obvious to the author and
    fixable; a manuscript that quietly omits its Methods reads as complete."""
    pid = project_rec["project_id"]
    plan = storage.load_json(paths.plan_path(pid), {})
    outline = storage.load_json(paths.outline_path(pid, paper_num), {"sections": []})
    memory = store.load(project_rec, paper_num)

    body = []
    missing = []
    for section in outline.get("sections") or []:
        n = section.get("number")
        heading = section.get("heading", f"Section {n}")
        path = paths.section_path(pid, paper_num, n)
        try:
            text_ = path.read_text(encoding="utf-8").strip()
        except OSError:
            text_ = ""
        body.append(f"# {heading}\n")
        if text_:
            body.append(text_ + "\n")
        else:
            missing.append(heading)
            body.append(f"<!-- MISSING: section {n} ({heading}) was never written to "
                        f"disk. This gap is deliberate and visible; a manuscript that "
                        f"quietly omits a section reads as complete. -->\n")
        body.append("")

    manuscript = _front_matter(plan, paper_num, memory.ledger) + "\n".join(body)
    manuscript += _reference_list(memory.ledger, _citation_order(manuscript))

    out_path = paths.manuscript_path(pid, paper_num)
    storage.atomic_write_text(manuscript, out_path)
    if log_fn:
        words = prose.word_count(prose.strip_structure(manuscript))
        log_fn(f"paper {paper_num}: assembled — {len(outline.get('sections') or [])} "
               f"section(s), {words:,} words"
               + (f"; MISSING {', '.join(missing)}" if missing else ""))
    return out_path


def audit(project_rec, paper_num, log_fn=None):
    """The whole-manuscript checks no single section can run. Returns a list of notes.

    Never raises and never blocks. These are findings for the author, recorded on the
    journal beside the delivered paper — a manuscript that is finished except for one
    uncited reference should reach its author rather than sit in a queue."""
    pid = project_rec["project_id"]
    memory = store.load(project_rec, paper_num)
    try:
        text_ = paths.manuscript_path(pid, paper_num).read_text(encoding="utf-8")
    except OSError:
        return ["audit: no manuscript on disk"]

    notes = []
    cites = citations.check_manuscript(text_, memory.references)
    notes += [f"CITATIONS: {reason}" for reason in cites.reasons]

    nums = numbers.check(text_, memory.evidence_document())
    if not nums.passed:
        notes += [f"NUMBERS: {reason}" for reason in nums.reasons]

    sent = sentences.score(text_)
    notes.append(f"PROSE: {sent.brief()}")
    if not sent.passed:
        notes += [f"PROSE: {reason}" for reason in sent.reasons]

    for note in notes:
        if log_fn:
            log_fn(f"paper {paper_num} audit — {note}")
    return notes


def convert(project_rec, paper_num, title, fmt, reference_docx=None, log_fn=None):
    """Convert the assembled manuscript to one format. Returns the path, or None.

    Returns None rather than raising on any failure that is not the manuscript's
    fault, because the Markdown is the deliverable and this is a convenience."""
    pid = project_rec["project_id"]
    source = paths.manuscript_path(pid, paper_num)
    if not source.exists():
        return None
    out_path = paths.built_path(pid, paper_num, title, fmt)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    command = [config.PANDOC_BIN, str(source), "-o", str(out_path),
               "--from", "markdown", "--standalone"]
    reference = reference_docx or config.REFERENCE_DOCX
    if fmt == "docx" and reference:
        command += ["--reference-doc", str(reference)]

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        if log_fn:
            log_fn(f"paper {paper_num}: could not run pandoc ({exc}). The manuscript "
                   f"Markdown is complete at {source} and converts with one command.")
        return None

    if result.returncode != 0 or not out_path.exists():
        if log_fn:
            log_fn(f"paper {paper_num}: pandoc failed ({result.returncode}): "
                   f"{(result.stderr or '').strip()[:300]}")
        return None
    if log_fn:
        log_fn(f"paper {paper_num}: built {out_path.name} "
               f"({out_path.stat().st_size:,} bytes)")
    return out_path


def build(project_rec, paper_num, title, log_fn=None):
    """Assemble, audit, and convert. Returns (manuscript_path, [built paths], notes).

    Raises only if assembly itself fails, which means a filesystem problem rather than
    a manuscript problem."""
    manuscript = assemble(project_rec, paper_num, log_fn=log_fn)
    notes = audit(project_rec, paper_num, log_fn=log_fn)

    from ..jobspec import reference_docx as job_reference
    reference = job_reference(project_rec.get("prompt_text", "")) or None

    built = []
    for fmt in config.BUILD_FORMATS:
        path = convert(project_rec, paper_num, title, fmt, reference_docx=reference,
                       log_fn=log_fn)
        if path:
            built.append(path)
        elif config.BUILD_REQUIRED:
            raise RuntimeError(f"building: could not produce {fmt} and "
                               f"PAPER_BUILD_REQUIRED is set")
    return manuscript, built, notes
