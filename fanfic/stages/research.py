"""Stage 1 — Research. Mine the source wikis into a cited canon reference, gate its
coverage, and freeze it.

The judgment model, granted web search and fetch, writes a canon JSON proposal per
universe. Deterministic code validates the structure, then the coverage gate checks
the facts actually cover the entities the prompt implies. Thin coverage raises: the
series parks rather than drafting on sand, which is the "whole book drafted on thin
canon" failure the README designs against.

Canon is frozen once written and idempotent to rebuild, so a crash mid-research costs
one re-run and nothing else.

## Frozen is not the same as finished

Canon is keyed on the UNIVERSE, not the series, so every job naming the same universe
shares one file. That is deliberate and it is worth 15-40 minutes a book — a thirteen
-book programme set in one universe mines its wikis once.

It also used to be a trap, and a bad one. The freeze was absolute: a second job in the
same universe reused the file unconditionally, while the coverage gate still ran
against *that job's* cast. So a Star Wars programme whose first book mined Jedi Knight
canon would park every later book at 0% coverage — the Bounty Hunter's companions are
simply not in a file about the Jedi Order — with an error that says "research" and a
cause that is "the freeze", which are three steps apart.

So canon **grows**. A frozen file that does not cover a new prompt is topped up for
exactly the entities it is missing and merged back, rather than re-mined from scratch
or refused. The overlap stays free, only what is genuinely new is paid for, and the
shared spine the design wants is actually shared.
"""

from .. import config, jobspec, paths
from ..gates import coverage
from ..infra import storage
from ..memory.bible import new_canon, validate_canon
from ..models import prompts, text


def propose_canon(prompt_text, universe, out_path, log_fn=None, focus=()):
    """Model seam: research one universe, writing canon JSON to out_path.

    `focus` turns this into a TOP-UP: the universe already has canon, and what is
    wanted is the entities it does not yet cover. Passing them explicitly matters —
    told only "research this universe again", the model produces another broad sweep
    that is mostly what is already on disk, which costs a full research call to move
    coverage by a few points."""
    facts = [f"Source universe to research now: {universe}",
             "",
             "Full job prompt (for context on what the story needs canon to cover):",
             prompt_text]
    if focus:
        facts = [
            f"Source universe to research now: {universe}",
            "",
            "THIS IS A TOP-UP, NOT A FRESH SURVEY. This universe already has a canon "
            "reference on file. What it does NOT yet cover is the list below, and that "
            "list is the whole job: research these specific entities and write facts "
            "about THEM.",
            "",
            "Entities still uncovered:",
            "\n".join(f"  - {name}" for name in focus),
            "",
            "Anything already well covered elsewhere is wasted effort here. If one of "
            "these is not a real entity in this universe, say so in your reply and "
            "write no fact for it rather than inventing one.",
            "",
            "Full job prompt (for context):",
            prompt_text,
        ]
    return text.produce(
        prompts.template("research"), facts, out_path,
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


def _mine(prompt_text, universe, log_fn=None, focus=()):
    """Run the model, validate its proposal, and return the canon to freeze."""
    proposal_path = paths.canon_proposal_path(universe)
    propose_canon(prompt_text, universe, proposal_path, log_fn=log_fn, focus=focus)
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


def merge_canon(existing, addition):
    """Fold a top-up into a frozen canon. Pure; returns a new document.

    New facts are appended under FRESH IDS rather than their proposed ones. A top-up
    call has no idea what is already on disk, so it numbers its facts from `c.1` like
    every other research call — and a duplicate id fails `validate_canon`, which would
    turn a successful top-up into a parked job. Renumbering here is what makes the
    merge safe to run any number of times."""
    facts = list(existing.get("facts") or [])
    seen = {fact.get("id") for fact in facts}
    counter = len(facts)
    for fact in (addition.get("facts") or []):
        fid = fact.get("id")
        if not fid or fid in seen:
            counter += 1
            fid = f"c.{counter}"
            while fid in seen:
                counter += 1
                fid = f"c.{counter}"
            fact = dict(fact, id=fid)
        seen.add(fid)
        facts.append(fact)
    merged = dict(existing)
    merged["facts"] = facts
    return merged


def _coverage_of(facts, entities, universes):
    """The coverage report for a set of facts against the prompt's entities."""
    return coverage.check({"universe": ", ".join(universes), "facts": facts}, entities)


def run(series_rec, log_fn=None):
    """Research every universe, validate and freeze each canon, and gate coverage.

    Returns {"universes": [...], "coverage": ratio}. Raises RuntimeError on a
    structural or coverage failure — a deterministic park."""
    prompt_text = series_rec["prompt_text"]
    unis = jobspec.universes(prompt_text)
    if not unis:
        raise RuntimeError("research: no source universe named in the prompt")

    def note(message):
        if log_fn:
            log_fn(message)

    entities = jobspec.implied_entities(prompt_text)
    canons = {}
    for uni in unis:
        canon_doc = _frozen_canon(uni)
        if canon_doc is not None:
            # Re-mining would spend 15-40 minutes arriving at the same file, and the
            # design promises a revive resumes rather than restarts. To force a fresh
            # dig, delete state/canon/<universe>/canon.json.
            note(f"canon for {uni!r} is already frozen "
                 f"({len(canon_doc['facts'])} facts); reusing it")
        else:
            canon_doc = _mine(prompt_text, uni, log_fn=log_fn)
            storage.save_json(canon_doc, paths.canon_path(uni))
        canons[uni] = canon_doc

    def combined_facts():
        return [fact for uni in unis for fact in canons[uni]["facts"]]

    report = _coverage_of(combined_facts(), entities, unis)

    # TOP UP RATHER THAN PARK. A frozen canon that does not cover this prompt is not a
    # failure, it is an out-of-date file — and the cheapest thing to do about it is ask
    # for exactly what is missing. One top-up per universe at most, so a genuinely
    # uncoverable entity costs one call and not a loop.
    if not report.passed:
        for uni in unis:
            if report.passed:
                break
            missing = list(report.missing)
            note(f"canon for {uni!r} covers {report.ratio:.0%} of this job's "
                 f"{len(entities)} entities; topping up for {len(missing)} missing "
                 f"({', '.join(missing[:6])}{'...' if len(missing) > 6 else ''})")
            addition = _mine(prompt_text, uni, log_fn=log_fn, focus=missing)
            merged = merge_canon(canons[uni], addition)
            ok, errors = validate_canon(merged)
            if not ok:
                raise RuntimeError(
                    f"research: topped-up canon for {uni!r} invalid: {errors[:3]}")
            gained = len(merged["facts"]) - len(canons[uni]["facts"])
            canons[uni] = merged
            storage.save_json(merged, paths.canon_path(uni))
            report = _coverage_of(combined_facts(), entities, unis)
            note(f"canon for {uni!r} grew by {gained} fact(s); coverage now "
                 f"{report.ratio:.0%}")

    if not report.passed:
        raise RuntimeError(
            f"research: canon coverage {report.ratio:.0%} below "
            f"{config.CANON_COVERAGE_MIN:.0%} floor after topping up; still missing "
            f"{report.missing[:8]}")
    return {"universes": unis, "coverage": report.ratio}
