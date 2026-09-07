"""The final sweep — every gate, every section, every document, on the built packet.

**This is the last thing that happens before a human reads the paper, and it exists
because the per-section loop cannot see the artifact.** Every gate in this project is
cheap, deterministic and already written. The sweep's whole contribution is *when* and
*over what* they run: after assembly, over the assembled documents rather than the
staged drafts, and over the whole packet rather than the manuscript alone.

That sounds like a formality. It is not, and the manuscript this was written from is the
argument.

**The failure it was written from.** A finished manuscript went out for its author's
read carrying nine defects. Every section had passed its editorial loop. The
whole-manuscript audit had passed. And:

  * **The Methods heading had stopped existing.** A missing newline left `# Methods`
    inside the last sentence of the Introduction, so pandoc printed four literal
    characters and the built `.docx` ran fifteen hundred words of Methods on as a
    continuation of the Introduction. The outline had a Methods section. The splitter,
    which finds `# Methods` wherever it sits, produced a correct part file. Only the
    assembled document was wrong — and the assembled document is the artifact.
  * **The references were not in order of first appearance**, while the manuscript's
    own header asserted that they were.
  * **The supplement was never checked at all.** Seventy-five thousand words of it: an
    undeclared third name for one study arm used seven times, a section contradicting
    its own earlier subsection, an analysis advertised and not reported, a small-cell
    rule defined two ways, and thirty-six table cells spelling one term differently
    from the rest of the packet.

Not one of those is subtle on a read-through. All of them survived, and the reason is
structural rather than careless.

**Three gaps, and each one is a scope the old audit did not have.**

*It read one document.* `audit` opened `manuscript.md` and nothing else. A supplement,
a reporting checklist, a cover letter and an author's report are all delivered, and
none of them was measured. A supplement is where a paper keeps the material nobody has
re-read.

*It measured the manuscript as one block.* `sentences.score` over eleven thousand words
returns a mean, and a mean over a whole paper is the section-average problem one level
up: a tight Results buys an unreadable Methods. The prose contract is measured at the
section and again inside each paragraph for exactly that reason, and the audit threw
both resolutions away.

*It ran five gates of thirteen.* No `paragraphs`, no `readability`, no `crossrefs`, no
`procedures`, no `repetition`, no `length`. Three of those only exist at document scope,
which is to say the one place they could have run was the place that was not running
them.

**What it does not do is block.** A paper that is finished except for one uncited
reference reaches its author rather than sitting in a queue — the same rule that governs
a missing pandoc, and the same rule that lets a section ship holding its notes. The
sweep's product is a *list*: what is wrong, in which document, in which section, from
which gate, with the offending sentence quoted verbatim so it is a find-and-replace
rather than a hunt. That list leads the author's report, because the point is that the
reader sees it before they start reading rather than after.

**Blocking and advisory are separated, and the split is not about severity.** It is
about whether arithmetic can be argued with. A number that is not in the evidence
ledger, a pointer that resolves to nothing, a heading that will not render, a forbidden
synonym: those are facts. A borrowed-claim heuristic, a repetition count, a
words-per-figure ratio: those are judgements the gate is offering and the author may
overrule. Mixing them is how a list stops being read.

No models, no network. It is thirteen pure functions run in a loop.
"""

import re
from dataclasses import dataclass, field

from .. import config, paths
from ..gates import (citations, crossrefs, length, numbers, paragraphs, procedures,
                     prose, readability, repetition, sentences, terminology, venue)
from ..infra import storage
from ..memory import store

# Comments are blanked rather than deleted so the line numbering and every offset
# survive, which is the same reason `prose.strip_structure` blanks. The gates strip
# comments themselves; the sweep needs it one step earlier, because a `#` inside a
# decision-record comment block would otherwise be read as a section heading and split
# the document in a place it does not divide.
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$")


def _blank_comments(text):
    body = list(text or "")
    for match in _COMMENT_RE.finditer(text or ""):
        for i in range(match.start(), match.end()):
            if body[i] != "\n":
                body[i] = " "
    return "".join(body)


def sections(text):
    """A document as [(heading, body)], split on top-level headings only.

    Anything before the first heading — front matter, a preamble, a decision-record
    comment block — is returned under the empty heading, because a document that is
    all preamble is still a document and dropping it would exempt it silently."""
    out, name, current = [], "", []
    for line in _blank_comments(text).splitlines():
        match = _HEADING_RE.match(line)
        if match:
            if name or any(l.strip() for l in current):
                out.append((name, "\n".join(current)))
            name, current = match.group(1).strip(), []
        else:
            current.append(line)
    if name or any(l.strip() for l in current):
        out.append((name, "\n".join(current)))
    return out


@dataclass
class Finding:
    document: str             # "manuscript.md", or "" when the finding spans the packet
    section: str              # the heading it sits under, or "" at document scope
    gate: str                 # which gate said so
    severity: str             # "blocking" or "advisory"
    detail: str               # one sentence a person can act on
    anchor: str = ""          # the offending text verbatim, when there is some

    def label(self):
        where = " / ".join(p for p in (self.document, self.section) if p)
        return f"{where or 'packet'} — {self.gate}"

    def line(self):
        return f"{self.label()}: {self.detail}"


@dataclass
class SweepReport:
    documents: list = field(default_factory=list)   # names swept, in order
    checked: int = 0                                # sections measured
    findings: list = field(default_factory=list)
    passed: bool = True                             # no BLOCKING findings

    def blocking(self):
        return [f for f in self.findings if f.severity == "blocking"]

    def advisory(self):
        return [f for f in self.findings if f.severity == "advisory"]

    def brief(self):
        return (f"{len(self.documents)} document(s), {self.checked} section(s), "
                f"{len(self.blocking())} blocking and {len(self.advisory())} advisory "
                f"finding(s)")

    def notes(self):
        """The flat list of strings the journal and the report already carry.

        Blocking first. A list nobody can act on in order is a list nobody reads in
        order."""
        return ([f"BLOCKING {f.line()}" for f in self.blocking()]
                + [f"advisory {f.line()}" for f in self.advisory()])


def _add(out, document, section, gate, severity, detail, anchor=""):
    out.append(Finding(document=document, section=section, gate=gate,
                       severity=severity, detail=str(detail), anchor=anchor))


def _section_scope(out, document, heading, body, evidence, lock, references, budget):
    """Every gate that measures one section, run on one section of a built document."""
    report = sentences.score(body, section_name=heading)
    worst = sentences.worst_offenders(report, count=1)
    for reason in report.reasons:
        _add(out, document, heading, "sentences", "blocking", reason,
             worst[0] if worst else "")

    shape = paragraphs.check(body, section_name=heading)
    for reason in shape.reasons:
        _add(out, document, heading, "paragraphs", "blocking", reason)
    if shape.passed:
        # Under the share ceiling the individual defects are still worth naming, and
        # they are advisory because the gate has already decided the section holds
        # together. An author fixing three of four is the normal outcome.
        for defect in shape.defects:
            _add(out, document, heading, "paragraphs", "advisory", defect.detail,
                 defect.anchor)

    read = readability.score(body, section_name=heading)
    for reason in read.reasons:
        _add(out, document, heading, "readability", "blocking", reason)

    # `section_name` is load-bearing: without it a reference list handed over as a
    # BODY has no heading in it, the gate's reference exemption cannot fire, and 58
    # bibliographic figures come back as findings.
    #
    # One finding per section rather than one per number. The gate's own `reasons`
    # already names up to eight of them, and a hundred separate lines saying the same
    # thing is how a list stops being read; the first offender's sentence is the anchor
    # because that is where a person starts.
    figures = numbers.check(body, evidence, section_name=heading)
    for reason in figures.reasons:
        _add(out, document, heading, "numbers", "blocking", reason,
             figures.unsupported[0].sentence if figures.unsupported else "")

    # Alias rules only. "Expanded once" is a claim about a whole document and is
    # checked at packet scope, where it is the only place it can be true.
    terms = terminology.check(body, lock, section_name=heading)
    for defect in terms.defects:
        _add(out, document, heading, "terminology", "blocking", defect.detail,
             defect.sentence)

    cites = citations.check(body, references)
    for key in cites.unresolved:
        _add(out, document, heading, "citations", "blocking",
             f"citation marker [{key}] resolves to no reference.")
    for defect in cites.missing:
        _add(out, document, heading, "citations", "advisory", defect.detail,
             defect.anchor)
    if len(cites.styles) > 1:
        _add(out, document, heading, "citations", "blocking",
             f"this section mixes {len(cites.styles)} citation styles "
             f"({', '.join(cites.styles)}).")

    if budget:
        band = length.check(prose.word_count(prose.strip_structure(body)), budget)
        if not band.passed and band.reason:
            _add(out, document, heading, "length", "advisory", band.reason)

    density = length.density(body, section_name=heading)
    for warning in density.warnings or ():
        _add(out, document, heading, "length", "advisory", warning)

    return not (report.reasons or shape.reasons or read.reasons
                or figures.unsupported or terms.defects)


def _packet_scope(out, texts, evidence, lock, references, where):
    """The checks that only exist across a whole document, or across the packet.

    `texts` is {name: text}, manuscript first. The supplement is found by name because
    that is what it is called; a packet without one passes the pointer check against
    the manuscript alone, which is correct rather than a degraded mode."""
    manuscript_name = next(iter(texts), "")
    manuscript = texts.get(manuscript_name, "")
    supplement = ""
    for name, text in texts.items():
        if "supplement" in name.lower():
            supplement = text
            break

    pointers = crossrefs.check(manuscript, supplement)
    for defect in pointers.defects:
        _add(out, "", "", "crossrefs", "blocking", defect.detail, defect.sentence)

    named = procedures.check(*texts.values())
    for defect, reason in zip(named.defects, named.reasons):
        _add(out, "", "", "procedures", "blocking", reason, defect.sentence)

    echoes = repetition.check(manuscript)
    for reason in echoes.reasons:
        _add(out, manuscript_name, "", "repetition", "advisory", reason)

    # Drift and first-use. Both are properties of a whole document and neither can be
    # judged from inside one section of it.
    #
    # First-use runs on the MANUSCRIPT only. A supplement, a checklist and a cover
    # letter each legitimately reuse the abbreviations the manuscript expanded, and
    # demanding that a supplement expand TRD again is demanding the manuscript expand
    # it twice — the contradiction the terminology gate exists to avoid, one document
    # further out. Drift runs on all of them, because a second name for one method is a
    # defect wherever in the packet it appears.
    for name, text in texts.items():
        terms = terminology.check_manuscript(text, lock,
                                             first_use=(name == manuscript_name))
        for defect in terms.defects:
            if defect.kind == "alias":
                continue          # already reported at section scope, with its anchor
            _add(out, name, "", "terminology", "blocking", defect.detail,
                 defect.sentence)

    cites = citations.check_manuscript(manuscript, references)
    for key in cites.uncited:
        _add(out, manuscript_name, "", "citations", "blocking",
             f"reference {key} is never cited. Cite it or remove it.")
    if cites.misordered:
        position, found, expected = cites.misordered
        _add(out, manuscript_name, "", "citations", "blocking",
             f"the reference numbering is not in order of first appearance: the "
             f"reference at position {position} is [{found}] where a list numbered by "
             f"appearance would have [{expected}]. Renumber and remap every marker in "
             f"the manuscript and the supplement together.")

    # The venue, last, because it is the only check here about whether the journal will
    # accept the file rather than about whether the paper is any good. It is also where
    # a swallowed heading and a missing IMRaD section are caught.
    report = venue.check(manuscript, where)
    for error in report.errors:
        _add(out, manuscript_name, "", "venue", "blocking", error)
    for warning in report.warnings:
        _add(out, manuscript_name, "", "venue", "advisory", warning)
    return report


def run(project_rec, paper_num, log_fn=None):
    """Sweep every built document of one paper. Returns a SweepReport.

    Never raises. A sweep that fell over would be a sweep that stopped a finished
    paper from reaching its author, which is the one thing this stage must not do."""
    pid = project_rec["project_id"]
    memory = store.load(project_rec, paper_num)
    evidence = memory.evidence_document()
    lock = memory.terminology
    references = memory.references

    plan = storage.load_json(paths.plan_path(pid), {})
    where, budgets = "", {}
    for paper in plan.get("papers") or []:
        if paper.get("number") == paper_num:
            where = paper.get("venue", "")
    outline = storage.load_json(paths.outline_path(pid, paper_num), {"sections": []})
    for entry in outline.get("sections") or []:
        if entry.get("heading"):
            budgets[str(entry["heading"]).strip().lower()] = entry.get("words")

    texts, findings, checked = {}, [], 0
    for path in paths.documents(pid, paper_num):
        if path.name == paths.report_path(pid, paper_num).name:
            continue              # the report is about the sweep; it is not swept
        try:
            texts[path.name] = path.read_text(encoding="utf-8")
        except OSError as exc:
            _add(findings, path.name, "", "sweep", "blocking",
                 f"could not be read ({exc}), so nothing in it was checked.")

    if not texts:
        _add(findings, "", "", "sweep", "blocking",
             "no documents on disk to sweep. The build produced nothing readable.")
        return SweepReport(documents=[], checked=0, findings=findings, passed=False)

    for name, text in texts.items():
        parts = sections(text)
        # **Everything before the first heading is front matter, unless there are no
        # headings at all.** A manuscript opens on a YAML metadata block, a title, an
        # author list and a set of ORCIDs, none of which is prose and all of which
        # arrives under the empty heading because it precedes the first real one. No
        # exemption can key on a heading that does not exist, so measuring it reports
        # a title block as clipped prose with a one-sentence paragraph — three
        # findings, on the one part of the document nobody writes in sentences.
        #
        # A document with NO headings is the other case and must not be skipped: a
        # cover letter is one block of prose from top to bottom, it is delivered, and
        # it is exactly the kind of document that goes unread.
        if len(parts) > 1:
            parts = [(h, b) for h, b in parts if h]
        for heading, body in parts:
            if not prose.sentences(body):
                continue          # a heading with a table under it and no prose
            checked += 1
            _section_scope(findings, name, heading, body, evidence, lock, references,
                           budgets.get(heading.strip().lower()))

    _packet_scope(findings, texts, evidence, lock, references, where)

    report = SweepReport(documents=list(texts), checked=checked, findings=findings,
                         passed=not any(f.severity == "blocking" for f in findings))
    if log_fn:
        log_fn(f"paper {paper_num} final sweep — {report.brief()}")
        for finding in report.blocking()[:config.SWEEP_LOG_FINDINGS]:
            log_fn(f"paper {paper_num} final sweep — BLOCKING {finding.line()}")
    return report
