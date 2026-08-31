"""Stage 1 — Research. Mine the source wikis into a cited canon reference, gate its
coverage, and freeze it.

The judgment model, granted web search and fetch, writes a canon JSON proposal per
universe. Deterministic code validates the structure, then the coverage gate checks
the facts actually cover the entities the prompt implies. Thin coverage raises: the
series parks rather than drafting on sand, which is the "whole book drafted on thin
canon" failure the README designs against.

Canon is frozen once written and is idempotent to rebuild, so a crash mid-research
costs one re-run and nothing else.
"""

from .. import config, jobspec, paths
from ..gates import coverage
from ..infra import storage
from ..memory.bible import new_canon, validate_canon
from ..models import prompts, text


def propose_canon(prompt_text, universe, out_path, log_fn=None):
    """Model seam: research one universe, writing canon JSON to out_path."""
    return text.produce(
        prompts.template("research"),
        [f"Source universe to research now: {universe}",
         "",
         "Full job prompt (for context on what the story needs canon to cover):",
         prompt_text],
        out_path,
        role="research",
        artifact="the cited canon reference as strict JSON",
        tail="Then reply with a one-paragraph note on coverage gaps you could not fill.",
        log_fn=log_fn)


def _frozen_canon(universe):
    """An already-frozen canon for this universe, or None if there isn't a usable one.

    Only a document that both claims `frozen` and still passes structural validation
    counts — a half-written or hand-edited file must not be trusted just because it
    exists on disk."""
    doc = storage.load_json(paths.canon_path(universe))
    if not isinstance(doc, dict) or not doc.get("frozen") or not doc.get("facts"):
        return None
    ok, _errors = validate_canon(doc)
    return doc if ok else None


def _mine(prompt_text, universe, log_fn=None):
    """Run the model, validate its proposal, and return the canon to freeze."""
    proposal_path = paths.canon_proposal_path(universe)
    propose_canon(prompt_text, universe, proposal_path, log_fn=log_fn)
    proposal = storage.load_json(proposal_path)
    if not isinstance(proposal, dict):
        raise RuntimeError(f"research: canon for {universe!r} is not a JSON object")

    doc = new_canon(universe)
    doc["facts"] = proposal.get("facts", [])
    ok, errors = validate_canon(doc)
    if not ok:
        raise RuntimeError(f"research: canon for {universe!r} invalid: {errors[:3]}")
    doc["frozen"] = True
    return doc


def run(series_rec, log_fn=None):
    """Research every universe, validate and freeze each canon, and gate coverage.

    Returns {"universes": [...], "coverage": ratio}. Raises RuntimeError on a
    structural or coverage failure — a deterministic park."""
    prompt_text = series_rec["prompt_text"]
    unis = jobspec.universes(prompt_text)
    if not unis:
        raise RuntimeError("research: no source universe named in the prompt")

    merged_facts = []
    for uni in unis:
        canon_doc = _frozen_canon(uni)
        if canon_doc is not None:
            # Canon is immutable once frozen, so re-mining the wikis would spend
            # 15-40 minutes to arrive at the same file. The design promises a revive
            # resumes rather than restarts; this is what makes that true of research.
            # To force a fresh dig, delete state/canon/<universe>/canon.json.
            if log_fn:
                log_fn(f"canon for {uni!r} is already frozen "
                       f"({len(canon_doc['facts'])} facts); reusing it")
        else:
            canon_doc = _mine(prompt_text, uni, log_fn=log_fn)
            storage.save_json(canon_doc, paths.canon_path(uni))
        merged_facts.extend(canon_doc["facts"])

    combined = {"universe": ", ".join(unis), "facts": merged_facts}
    report = coverage.check(combined, jobspec.implied_entities(prompt_text))
    if not report.passed:
        raise RuntimeError(
            f"research: canon coverage {report.ratio:.0%} below "
            f"{config.CANON_COVERAGE_MIN:.0%} floor; missing {report.missing[:8]}")
    return {"universes": unis, "coverage": report.ratio}
