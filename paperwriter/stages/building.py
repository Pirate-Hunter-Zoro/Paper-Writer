"""Building. Assemble the accepted sections into a manuscript, then convert everything.

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

**Conversion is verified against its own output.** Pandoc reports a figure it could
not find as a warning and exits 0, so a document can convert successfully and arrive
with every figure missing. `figures_lost` opens the built .docx and counts what is
actually in it, because the tool's account of its own work is the one thing this
repository never accepts.

**The final sweep runs here**, between assembly and conversion, and it is
`stages.sweep`. Every gate, every section, every document the paper produced — on the
ASSEMBLED text rather than on the staged drafts, because assembly and the hand edits
after it are where a manuscript acquires the defects no per-section loop can see. It is
reported and recorded and, like conversion, it does not block: a paper that is finished
except for one uncited reference should reach its author rather than sit in a queue.

`audit` is what the sweep replaced and is kept as a thin wrapper, because it is the name
on the journal record of every paper this harness has already built.
"""

import os
import re
import subprocess
import zipfile

from pathlib import Path

from .. import config, paths
from ..gates import prose
from ..infra import storage
from ..memory import store
from . import reporting, splitting, sweep


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
    """The final sweep, as the flat list of notes the journal record carries.

    A thin wrapper on `stages.sweep.run`, kept under this name because it is what every
    already-built paper's journal record calls its findings. New code should call the
    sweep and read its structured findings; this is the string view."""
    return sweep.run(project_rec, paper_num, log_fn=log_fn).notes()


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
               "--from", "markdown", "--standalone",
               "--resource-path", _resource_path(source,
                                                 config.BUILD_RESOURCE_DIRS)]
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
    _report_lost_figures(source, out_path, reference, log_fn,
                         prefix=f"paper {paper_num}: ")
    return out_path


# `![alt](target)`, with the target either bare or in angle brackets, and whatever
# pandoc attributes or title follow it. Reference-style images are not used anywhere in
# this project's documents and are deliberately not matched: a check that guesses is a
# check nobody can act on.
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*(<[^>]*>|[^)\s]+)")

_REMOTE_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//|^data:", re.IGNORECASE)


def _image_targets(text):
    """Every distinct local image a document refers to, in order of first appearance.

    Distinct, because pandoc embeds one copy of a file referenced twice and counting
    the references would then read as a loss. Local, because a remote image is
    pandoc's problem and not the resource path's."""
    seen, out = set(), []
    for raw in _IMAGE_RE.findall(text):
        target = raw.strip("<>").strip()
        if not target or _REMOTE_RE.match(target) or target in seen:
            continue
        seen.add(target)
        out.append(target)
    return out


def _media_count(docx):
    """How many image files a .docx actually carries. -1 if it cannot be read."""
    try:
        with zipfile.ZipFile(docx) as archive:
            return sum(1 for name in archive.namelist()
                       if name.startswith("word/media/"))
    except (OSError, zipfile.BadZipFile):
        return -1


def figures_lost(source, built, reference_docx=None):
    """How many of a document's figures did not reach the built file.

    Returns the count, or None when there is nothing to check or no way to check it.

    **Why this is counted from the result rather than read off pandoc's stderr.** A
    figure whose path does not resolve is a warning and a zero exit status. The build
    succeeds, the document is written, the file is a plausible size, and twenty figures
    are simply not in it — and nothing downstream can tell that document from a section
    that never had one. Trusting the tool's own account of its work is the failure this
    whole repository is arranged against, so the check opens the .docx and counts.

    The reference document's own images are subtracted, because a template carrying a
    journal logo would otherwise cover for exactly as many lost figures as it has."""
    if built is None or built.suffix.lower() != ".docx":
        return None
    try:
        referenced = len(_image_targets(source.read_text(encoding="utf-8")))
    except OSError:
        return None
    if not referenced:
        return None
    embedded = _media_count(built)
    if embedded < 0:
        return None
    if reference_docx:
        template = _media_count(Path(reference_docx))
        if template > 0:
            embedded -= template
    return max(0, referenced - embedded)


def _report_lost_figures(source, built, reference, log_fn, prefix=""):
    """Say it, loudly, when figures did not make it into the built document.

    This is the whole point of the check. Conversion is a convenience and does not
    block delivery, so the alternative to a loud line here is a .docx that looks
    finished and is missing its evidence."""
    lost = figures_lost(source, built, reference_docx=reference)
    if not lost or not log_fn:
        return lost
    referenced = len(_image_targets(source.read_text(encoding="utf-8")))
    log_fn(f"{prefix}{lost} of {referenced} figure(s) in {source.name} did not reach "
           f"{built.name}. Their paths are relative to a directory pandoc was not "
           f"given: name it in PAPER_BUILD_RESOURCE_DIRS.")
    return lost


def _resource_path(source, extra_roots):
    """Where pandoc looks for a figure, nearest first: the document's own directory,
    then whatever roots the caller added.

    The second half exists because of the split parts. `parts/manuscript/05-results.md`
    inherits `![](../results/roc.png)` verbatim from the manuscript it was cut out of,
    and that path was written relative to the PAPER. With only the part's own directory
    on the resource path pandoc resolves it to `parts/results/roc.png`, finds nothing,
    warns on stderr, and writes a .docx with every figure missing and a zero exit
    status. Nothing downstream can tell that document from one that had no figures.

    So a caller that knows the root those paths were written against passes it, and the
    part converts the way the whole does."""
    seen, out = set(), []
    for root in (source.parent, *extra_roots):
        text = str(root)
        if text not in seen:
            seen.add(text)
            out.append(text)
    return os.pathsep.join(out)


def convert_one(source, fmt, reference_docx=None, resource_roots=(), log_fn=None):
    """Convert one Markdown document to one format, beside its source.

    Returns the path, or None on any failure that is not the document's fault. The
    Markdown is the deliverable and this is a convenience, so a missing pandoc must
    never be the reason a finished paper is not delivered.

    A document that converted but lost figures still returns its path, and says so.
    The .docx is worth delivering with a hole in it and a line naming the hole; it is
    not worth delivering silently."""
    if not source.exists():
        return None
    out_path = paths.built_document_path(source, fmt)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    roots = tuple(resource_roots) + config.BUILD_RESOURCE_DIRS
    command = [config.PANDOC_BIN, str(source), "-o", str(out_path),
               "--from", "markdown", "--standalone",
               "--resource-path", _resource_path(source, roots)]
    reference = reference_docx or config.REFERENCE_DOCX
    if fmt == "docx" and reference:
        command += ["--reference-doc", str(reference)]

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        if log_fn:
            log_fn(f"could not run pandoc on {source.name} ({exc}). The Markdown is "
                   f"complete and converts with one command.")
        return None
    if result.returncode != 0 or not out_path.exists():
        if log_fn:
            log_fn(f"pandoc failed on {source.name} ({result.returncode}): "
                   f"{(result.stderr or '').strip()[:300]}")
        return None
    if log_fn:
        log_fn(f"built {out_path.name} ({out_path.stat().st_size:,} bytes)")
    _report_lost_figures(source, out_path, reference, log_fn)
    return out_path


def convert_all(project_rec, paper_num, reference_docx=None, log_fn=None):
    """Convert every document this paper produced AND every section of each, in every
    configured format.

    Discovered from disk rather than listed, so a stage that starts emitting another
    document gets it converted and delivered without anybody remembering to come back
    here. The manuscript used to be the only thing converted, which meant the author's
    report and anything else the pipeline wrote arrived as Markdown beside a .docx and
    read as an afterthought — which it was."""
    pid = project_rec["project_id"]
    # The paper root goes on every document's resource path, because the parts carry
    # the whole document's figure paths and those were written relative to the paper.
    root = paths.paper_root(pid, paper_num)
    built = []
    for source in (list(paths.documents(pid, paper_num))
                   + list(paths.part_documents(pid, paper_num))):
        for fmt in config.BUILD_FORMATS:
            path = convert_one(source, fmt, reference_docx=reference_docx,
                               resource_roots=(root,), log_fn=log_fn)
            if path:
                built.append(path)
            elif config.BUILD_REQUIRED:
                raise RuntimeError(
                    f"building: could not produce {fmt} for {source.name} and "
                    f"PAPER_BUILD_REQUIRED is set")
    return built


def build(project_rec, paper_num, title, log_fn=None):
    """Assemble, audit, report, split, and convert everything.

    Returns (manuscript_path, [built paths], notes). Raises only if assembly itself
    fails, which means a filesystem problem rather than a manuscript problem.

    The sweep runs after assembly and before the report, so the report leads with what
    the sweep found. That ordering is the deliverable: the reader sees the list of
    defects before they start reading the paper, rather than discovering them."""
    pid = project_rec["project_id"]
    manuscript = assemble(project_rec, paper_num, log_fn=log_fn)

    # The sweep runs on the assembled documents, which is the whole point of it being
    # here rather than in the editorial loop: assembly, and the hand edits after it,
    # are where a manuscript acquires the defects no single section can see.
    swept = sweep.run(project_rec, paper_num, log_fn=log_fn)
    notes = swept.notes()

    # The report is written before conversion so it is converted with everything
    # else. It reads only committed state, so it cannot fail in a way that should
    # cost the manuscript its build.
    try:
        reporting.write(project_rec, paper_num, audit_notes=notes, sweep=swept,
                        log_fn=log_fn)
    except (OSError, KeyError, ValueError) as exc:
        notes = list(notes) + [f"REPORT: could not be written ({exc}). The manuscript "
                               f"is unaffected."]

    # And the parts, before conversion, so each one is converted with everything else.
    # Derived from the assembled documents rather than from the accepted sections on
    # disk: those exist only for the manuscript, and a split that came from a different
    # source than the whole would be a second version of the paper.
    splitting.run(pid, paper_num, log_fn=log_fn)

    from ..jobspec import reference_docx as job_reference
    reference = job_reference(project_rec.get("prompt_text", "")) or None
    built = convert_all(project_rec, paper_num, reference_docx=reference,
                        log_fn=log_fn)
    return manuscript, built, notes
