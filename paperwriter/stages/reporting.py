"""The author's report — what the harness did, what it measured, what it could not fix.

The manuscript is the product. This is the document that says whether to trust it, and
until it existed that information was real but unreadable: the ladder was in the plan,
the gate measurements were in `state/decisions.log`, the issues a section shipped
holding were in the journal, and a person wanting all three read three files in two
formats and joined them by hand.

So it is assembled into one document and converted alongside the manuscript, because
the pipeline's job is not finished when the prose is written. It is finished when the
author can see what was checked.

**Why it leads on the support ladder.** A reader of the manuscript can check its
numbers and its prose themselves. What they cannot recover from the manuscript is what
the paper was FOR and which claim was supposed to serve which point — that lived only
in the plan, and it is the first thing to look at when a section reads as though it
belongs to a different paper.

**Nothing here is generated.** Every line is read off state the pipeline already
committed: the plan, the ledger, the outline, the journal and the assembled prose. No
model call, and no judgement — a report that summarised the paper would be a second
opinion about it, and this is a record.
"""

from .. import config, paths
from ..gates import ladder as ladder_gate, prose, sentences
from ..infra import journal, storage
from ..memory import store


def _ladder_block(plan, paper_num, argument):
    points = [p for p in (plan.get("points") or []) if p.get("paper") == paper_num]
    claims = argument.get("claims") or []
    if not points:
        points, claims = ladder_gate.migrated(points, claims)
    if not points:
        return ["_No points are recorded for this paper, so the ladder cannot be "
                "shown. A plan written before the support ladder existed looks like "
                "this._", ""]

    lines = ["## What this paper is for", "",
             "The support ladder as the plan committed it. Every claim either serves "
             "a point or declares the role it plays instead.", ""]
    for point in points:
        pid = str(point.get("id"))
        serving = [c for c in claims if pid in ladder_gate.serves_of(c)]
        lines.append(f"**{pid}. {ladder_gate.point_text(point)}**")
        lines.append("")
        for claim in serving:
            states = " _(states it)_" if claim.get("headline") else ""
            where = claim.get("section") or "(unplaced)"
            lines.append(f"- `{claim.get('id')}` ({claim.get('kind', '?')}, "
                         f"{where}){states}: {claim.get('claim', '')}")
        if not serving:
            lines.append("- _nothing serves this point_")
        lines.append("")

    for role in ladder_gate.ROLES:
        holding = [c for c in claims if ladder_gate.role_of(c) == role]
        if not holding:
            continue
        lines.append(f"**Role: {role}** — the argument needs these in place and does "
                     f"not rest on them.")
        lines.append("")
        for claim in holding:
            lines.append(f"- `{claim.get('id')}` "
                         f"({claim.get('section') or '(unplaced)'}): "
                         f"{claim.get('claim', '')}")
        lines.append("")

    report = ladder_gate.check(points, claims)
    if report.warnings:
        lines.append("The ladder gate passed with notes:")
        lines.append("")
        lines += [f"- {w}" for w in report.warnings]
        lines.append("")
    return lines


def _prose_block(manuscript_text):
    score = sentences.score(manuscript_text)
    verdict = "within every band" if score.passed else "outside at least one band"
    lines = ["## How it reads", "",
             f"Measured over the assembled manuscript, {verdict}.", "",
             "| Measurement | Value | Band |",
             "| --- | ---: | --- |",
             f"| Words | {score.words:,} | — |",
             f"| Sentences | {score.count:,} | — |",
             f"| Mean words per sentence | {score.mean:.1f} | "
             f"{config.SENTENCE_MEAN_WORDS_MIN:g}–"
             f"{config.SENTENCE_MEAN_WORDS_MAX:g} |",
             f"| Standard deviation | {score.stdev:.1f} | "
             f"floor {config.SENTENCE_STDEV_MIN:g} |",
             f"| Longest sentence | {score.longest} | "
             f"ceiling {config.SENTENCE_HARD_MAX_WORDS} |",
             f"| Share over {config.SENTENCE_LONG_WORDS} words | "
             f"{score.long_share:.1%} | ceiling "
             f"{config.SENTENCE_LONG_SHARE_MAX:.0%} |",
             f"| Semicolons per 1,000 words | {score.semicolons_per_kword:.2f} | "
             f"ceiling {config.SEMICOLONS_PER_KWORD_MAX:g} |",
             f"| Clause-joining dashes per 1,000 words | "
             f"{score.emdashes_per_kword:.2f} | ceiling "
             f"{config.EMDASHES_PER_KWORD_MAX:g} |",
             ""]
    if score.reasons:
        lines.append("What is outside its band:")
        lines.append("")
        lines += [f"- {r}" for r in score.reasons]
        lines.append("")
    return lines


def _held_block(records, project_id, paper_num):
    """Every issue a section shipped still carrying.

    A section that could not be made clean inside its budget ships anyway, holding a
    recorded list of what is still wrong, because one stubborn paragraph must not
    discard a finished manuscript. That list is the most important thing in this
    report and it was previously only in the journal."""
    prefix = journal.paper_key(project_id, paper_num) + "/section/"
    lines = []
    for key, record in sorted(records.items(),
                              key=lambda kv: str(kv[1].get("section") or kv[0])):
        if not key.startswith(prefix):
            continue
        held = record.get("outstanding_issues") or []
        if not held:
            continue
        where = record.get("heading") or f"section {record.get('section', '?')}"
        lines.append(f"**{where}**")
        lines.append("")
        lines += [f"- {issue}" for issue in held]
        lines.append("")
    if not lines:
        return ["## What shipped unresolved", "",
                "Nothing. Every section was made clean inside its editorial budget.",
                ""]
    return ["## What shipped unresolved", "",
            "These sections ship carrying issues the editorial loop could not repair "
            "inside its budget. Nothing was discarded to reach that state, and each "
            "line below is a defect a person still has to decide about.", ""] + lines


def write(project_rec, paper_num, audit_notes=None, log_fn=None):
    """Assemble the author's report. Returns its path."""
    pid = project_rec["project_id"]
    plan = storage.load_json(paths.plan_path(pid), {})
    argument = storage.load_json(paths.argument_path(pid, paper_num),
                                 {"claims": [], "points": []})
    outline = storage.load_json(paths.outline_path(pid, paper_num), {"sections": []})
    records = journal.load_records()

    paper = {}
    for entry in plan.get("papers") or []:
        if entry.get("number") == paper_num:
            paper = entry
    title = paper.get("title") or f"{pid} paper {paper_num}"

    try:
        manuscript_text = paths.manuscript_path(pid, paper_num).read_text(
            encoding="utf-8")
    except OSError:
        manuscript_text = ""

    parts = [f"# {title} — what the harness checked", "",
             "_The manuscript is the product. This is the record of how it was built: "
             "what the paper was for, how the prose measures, and what shipped "
             "unresolved. Nothing here is written by a model; every line is read off "
             "state the pipeline committed._", ""]

    parts += _ladder_block(plan, paper_num, argument)

    sections = outline.get("sections") or []
    if sections:
        planned = sum(int(s.get("words") or 0) for s in sections)
        actual = prose.word_count(prose.strip_structure(manuscript_text))
        limit = paper.get("word_limit")
        parts += ["## Length, planned against delivered", "",
                  "| | Words |", "| --- | ---: |",
                  f"| Planned across {len(sections)} sections | {planned:,} |",
                  f"| Delivered | {actual:,} |",
                  f"| Venue limit | {f'{limit:,}' if limit else '(none stated)'} |",
                  ""]

    if manuscript_text:
        parts += _prose_block(manuscript_text)

    parts += _held_block(records, pid, paper_num)

    if audit_notes:
        parts += ["## The whole-manuscript audit", "",
                  "Checks that only exist at document scope: a reference cited "
                  "nowhere, an abbreviation expanded twice, the prose statistics for "
                  "the paper as a whole.", ""]
        parts += [f"- {note}" for note in audit_notes]
        parts.append("")

    memory = store.load(project_rec, paper_num)
    evidence = memory.evidence_document()
    parts += ["## Where the numbers came from", "",
              f"Every figure in the manuscript was checked against a frozen evidence "
              f"ledger of {len(evidence.get('items') or []):,} items. The ledger stops "
              f"tracking the analysis once frozen, so a rerun mid-draft cannot "
              f"silently change what a written section claims.", ""]

    out_path = paths.report_path(pid, paper_num)
    storage.atomic_write_text("\n".join(parts) + "\n", out_path)
    if log_fn:
        log_fn(f"paper {paper_num}: report written -> {out_path.name}")
    return out_path
