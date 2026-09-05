"""Gathering. Mine the results and the sources into a cited evidence reference, gate
its coverage, and freeze it.

The model, granted read access to the analysis trees and the web, writes an evidence
JSON proposal per corpus: one item per fact the paper might use, each carrying the
exact numbers it licenses and the file, table or citation it came from. Deterministic
code validates the structure, then the coverage gate checks the items actually cover
the claims the job intends to make. Thin coverage raises, and the project parks rather
than drafting a Results section on numbers nobody has.

**Freezing is the point, and it is not about caching.** Once an evidence document is
frozen it is the manuscript's ground truth, and it stops tracking the analysis. That
sounds like a bug and is the single most important property here: an analysis rerun
mid-draft that shifts an AUC from 0.7429 to 0.7511 must not silently change what the
Methods section claims, because half the manuscript was written against the old
number and nothing would tell you which half. Re-freezing is a deliberate act, and it
invalidates every section that cited the changed item.

## Frozen is not the same as finished

Evidence is keyed on the CORPUS, not the project, so every job naming the same corpus
shares one file. That is deliberate: a programme of three papers off one analysis
mines it once.

It also used to be a trap. An absolute freeze meant a second job in the same corpus
reused the file unconditionally, while the coverage gate still ran against *that job's*
claims — so a second paper about a subgroup analysis would park at 0% coverage, with an
error that says "gathering" and a cause that is "the freeze".

So evidence **grows**. A frozen file that does not cover a new job is topped up for
exactly the claims it is missing and merged back, rather than re-mined from scratch or
refused. The overlap stays free, only what is genuinely new is paid for, and — because
a top-up appends and never rewrites — a number already cited by a written section
cannot change underneath it.
"""

from .. import config, jobspec, paths
from ..gates import coverage
from ..infra import storage
from ..memory.ledger import new_evidence, validate_evidence
from ..models import prompts, text


def propose_evidence(prompt_text, corpus, out_path, log_fn=None, focus=(),
                     sources=()):
    """Model seam: gather one corpus, writing evidence JSON to out_path.

    `focus` turns this into a TOP-UP: the corpus already has evidence, and what is
    wanted is the claims it does not yet cover. Passing them explicitly matters —
    told only "gather this corpus again", the model produces another broad sweep that
    is mostly what is already on disk, which costs a full call to move coverage by a
    few points."""
    where = "\n".join(f"  - {s}" for s in sources) or "  (none configured)"
    facts = [f"Corpus to gather now: {corpus}",
             "",
             "WHERE TO LOOK. These directories are read-only ground truth. Read the "
             "result files, the tables, and the reference PDFs under them. Do not "
             "write anything into them:",
             where,
             "",
             "Full job prompt (for context on what the paper needs evidence to "
             "support):",
             prompt_text]
    if focus:
        facts = [
            f"Corpus to gather now: {corpus}",
            "",
            "THIS IS A TOP-UP, NOT A FRESH SURVEY. This corpus already has an "
            "evidence reference on file. What it does NOT yet cover is the list "
            "below, and that list is the whole job: find the numbers and sources for "
            "THESE claims.",
            "",
            "Claims still uncovered:",
            "\n".join(f"  - {name}" for name in focus),
            "",
            "Anything already covered elsewhere is wasted effort here. If one of "
            "these is not supportable from the available data, say so in your reply "
            "and write no item for it rather than inventing one.",
            "",
            "WHERE TO LOOK:",
            where,
            "",
            "Full job prompt (for context):",
            prompt_text,
        ]
    return text.produce(
        prompts.template("evidence"), facts, out_path,
        role="evidence",
        artifact="the cited evidence reference as strict JSON",
        tail="Then reply with a one-paragraph note on the claims you could not "
             "support, and why.",
        log_fn=log_fn)


def _frozen_evidence(corpus):
    """An already-frozen evidence document for this corpus, or None.

    Only a document that both claims `frozen` and still passes structural validation
    counts — a half-written or hand-edited file must not be trusted just because it
    exists on disk."""
    doc = storage.load_json(paths.evidence_path(corpus))
    if not isinstance(doc, dict) or not doc.get("frozen") or not doc.get("items"):
        return None
    ok, _errors = validate_evidence(doc)
    return doc if ok else None


def _mine(prompt_text, corpus, log_fn=None, focus=(), sources=()):
    """Run the model, validate its proposal, and return the evidence to freeze."""
    proposal_path = paths.evidence_proposal_path(corpus)
    propose_evidence(prompt_text, corpus, proposal_path, log_fn=log_fn, focus=focus,
                     sources=sources)
    proposal = storage.load_json(proposal_path)
    if not isinstance(proposal, dict):
        raise RuntimeError(f"gathering: evidence for {corpus!r} is not a JSON object")

    doc = new_evidence(corpus)
    doc["items"] = proposal.get("items", [])
    doc["also_allow"] = proposal.get("also_allow", [])
    ok, errors = validate_evidence(doc)
    if not ok:
        raise RuntimeError(f"gathering: evidence for {corpus!r} invalid: {errors[:3]}")
    doc["frozen"] = True
    return doc


def _fingerprint(item):
    """What makes two evidence items the same fact: what it says and where it came
    from. Deliberately not the id, because a top-up numbers its own items from scratch
    and every one of them would otherwise look new."""
    return (" ".join(str(item.get("statement") or "").split()).lower(),
            str(item.get("source") or "").strip().lower())


def merge_evidence(existing, addition):
    """Fold a top-up into a frozen evidence document. Pure; returns a new document.

    New items are appended under FRESH IDS rather than their proposed ones, and an
    existing item is never modified. A top-up call has no idea what is already on
    disk, so it numbers its items from `e.1` like every other call — and a duplicate
    id both fails validation and, far worse, would let a top-up silently redefine a
    number a written section has already cited. Renumbering here is what makes the
    merge safe to run any number of times and safe to run mid-manuscript.

    An item the document already holds is DROPPED rather than appended under a new id.
    Without that, a coverage gate that cannot be satisfied grows the evidence forever:
    the project stalls, retries, tops up with the same four items, and does that on
    every retry until somebody looks. One corpus reached 328 copies of eight facts that
    way, and every one of them was a legitimate id the number gate would honour."""
    items = list(existing.get("items") or [])
    seen = {item.get("id") for item in items}
    already = {_fingerprint(item) for item in items}
    counter = len(items)
    for item in (addition.get("items") or []):
        if _fingerprint(item) in already:
            continue
        already.add(_fingerprint(item))
        eid = item.get("id")
        if not eid or eid in seen:
            counter += 1
            eid = f"e.{counter}"
            while eid in seen:
                counter += 1
                eid = f"e.{counter}"
            item = dict(item, id=eid)
        seen.add(eid)
        items.append(item)
    merged = dict(existing)
    merged["items"] = items
    merged["also_allow"] = list(dict.fromkeys(
        list(existing.get("also_allow") or []) + list(addition.get("also_allow") or [])))
    return merged


def _coverage_of(items, claims):
    """The coverage report for a set of items against the job's intended claims."""
    return coverage.check({"corpus": "(all)", "items": items}, claims)


def run(project_rec, log_fn=None):
    """Gather every corpus, validate and freeze each document, and gate coverage.

    Returns {"corpora": [...], "coverage": ratio}. Raises RuntimeError on a
    structural or coverage failure — a deterministic park, retried by the engine."""
    prompt_text = project_rec["prompt_text"]
    corpora = jobspec.corpora(prompt_text)
    if not corpora:
        raise RuntimeError("gathering: no evidence corpus named in the prompt")

    def note(message):
        if log_fn:
            log_fn(message)

    claims = jobspec.intended_claims(prompt_text)
    sources = [str(p) for p in config.SOURCE_DIRS]
    documents = {}
    for corpus in corpora:
        doc = _frozen_evidence(corpus)
        if doc is not None:
            # Re-mining would spend a long call arriving at the same file, and the
            # design promises a revive resumes rather than restarts. To force a fresh
            # dig, delete state/evidence/<corpus>/evidence.json.
            note(f"evidence for {corpus!r} is already frozen "
                 f"({len(doc['items'])} items); reusing it")
        else:
            doc = _mine(prompt_text, corpus, log_fn=log_fn, sources=sources)
            storage.save_json(doc, paths.evidence_path(corpus))
        documents[corpus] = doc

    def combined_items():
        return [item for c in corpora for item in documents[c]["items"]]

    report = _coverage_of(combined_items(), claims)

    # TOP UP RATHER THAN PARK. Frozen evidence that does not cover this job is not a
    # failure, it is an out-of-date file — and the cheapest thing to do about it is
    # ask for exactly what is missing. One top-up per corpus at most, so a genuinely
    # unsupportable claim costs one call and not a loop.
    if not report.passed:
        for corpus in corpora:
            if report.passed:
                break
            missing = list(report.missing)
            note(f"evidence for {corpus!r} covers {report.ratio:.0%} of this job's "
                 f"{len(claims)} claims; topping up for {len(missing)} missing "
                 f"({'; '.join(m[:40] for m in missing[:4])}"
                 f"{'...' if len(missing) > 4 else ''})")
            addition = _mine(prompt_text, corpus, log_fn=log_fn, focus=missing,
                             sources=sources)
            merged = merge_evidence(documents[corpus], addition)
            ok, errors = validate_evidence(merged)
            if not ok:
                raise RuntimeError(
                    f"gathering: topped-up evidence for {corpus!r} invalid: "
                    f"{errors[:3]}")
            gained = len(merged["items"]) - len(documents[corpus]["items"])
            documents[corpus] = merged
            storage.save_json(merged, paths.evidence_path(corpus))
            report = _coverage_of(combined_items(), claims)
            note(f"evidence for {corpus!r} grew by {gained} item(s); coverage now "
                 f"{report.ratio:.0%}")

    if not report.passed:
        raise RuntimeError(
            f"gathering: evidence coverage {report.ratio:.0%} below "
            f"{config.EVIDENCE_COVERAGE_MIN:.0%} floor after topping up; still "
            f"unsupported: {report.missing[:6]}")
    return {"corpora": corpora, "coverage": report.ratio}
