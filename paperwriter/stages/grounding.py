"""Grounding. What this paper is called, what it estimates, and who reads it.

Evidence gathering collects what is *true*. A paper needs what is *fixed* — the
decisions that have to be the same in every section and cannot be made twice. Those
are different documents and only one of them gets written by default, which is how a
manuscript ends up with three names for two methods, a Methods section describing an
association and a Discussion describing an effect, and an abstract pitched at a
methods audience under a clinical journal's masthead.

Five things are pinned here, before a word is planned:

  * **The terminology lock.** Every entity the paper names, the one string that names
    it, and the strings that must never appear. This is the most valuable field and
    the one nobody writes down. A manuscript compared two representations, called one
    of them "the rule-based approach" in a single sentence, and spent a review round
    explaining that there were two methods rather than three.
  * **The estimand.** What quantity the paper reports, in one sentence, in the
    language of the analysis rather than of the conclusion. "Discrimination of a
    twelve-month TRD label on a held-out split" is an estimand. "Whether the model
    works" is not. Written down here, it is the sentence the Discussion cannot drift
    away from.
  * **The reader.** Which journal, and what that reader already knows. It sets what
    the Introduction may assume, how much of the method belongs in the body, and
    whether "AUC" needs expanding.
  * **The reporting checklist.** TRIPOD+AI, CONSORT, STROBE, PRISMA — whichever
    governs. Its items become obligations the outline has to place, rather than a form
    somebody fills in the night before submission.
  * **The conventions.** Tense of the Methods, "we" or "the authors", how an interval
    is written. Each one is trivial and each one drifts, and half a manuscript in one
    voice is a thing reviewers notice and authors do not.

**A gate cannot check a fact nobody wrote down.** The terminology gate can only refuse
a synonym it was told to refuse. That is why this stage exists and why it is gated for
completeness rather than for correctness: this gate cannot tell a right answer from a
wrong one, only a present one from an absent one. What it buys is that the absent
field — the one that silently becomes whatever the model felt like on page nine —
cannot happen quietly.

It runs between gathering and planning: the evidence is frozen first, so the grounding
is derived from ground truth rather than from the prompt's summary of it, and the
project ledger is seeded from the grounding rather than from the evidence directly.
"""

from .. import config, paths
from . import correction_brief
from ..infra import storage
from ..memory.ledger import new_evidence, validate_terminology
from ..models import prompts, text

# What has to be present before planning may start.
REQUIRED_TOP = ("estimand", "reader", "venue")


def evidence_block(project_rec, limit=400):
    """Every frozen evidence item, quoted. One grounding call reads all of it."""
    lines = []
    for corpus in project_rec.get("corpora", []):
        doc = storage.load_json(paths.evidence_path(corpus), new_evidence(corpus))
        items = doc.get("items", [])
        lines.append(f"--- EVIDENCE: {corpus} ({len(items)} cited items) ---")
        for item in items[:limit]:
            values = ", ".join(str(v) for v in (item.get("values") or []))
            lines.append(f"  [{item.get('id','')}] {item.get('statement','')}"
                         + (f"  (values: {values})" if values else "")
                         + f"  <- {item.get('source','')}")
        if len(items) > limit:
            lines.append(f"  ... and {len(items) - limit} more")
        lines.append("")
    return "\n".join(lines) or "(no evidence on file)"


def propose_grounding(project_rec, out_path, log_fn=None, feedback=""):
    """Model seam: produce the grounding JSON at out_path."""
    return text.produce_json(
        prompts.template("grounding") + feedback,
        ["THE JOB PROMPT — its target venue and its statement of what the paper "
         "claims are literal. Read it before anything else:",
         project_rec["prompt_text"],
         "",
         "=" * 70,
         "FROZEN EVIDENCE — every term you lock must be a thing this evidence is "
         "actually about, and the estimand must be a quantity it actually contains:",
         "=" * 70,
         evidence_block(project_rec)],
        out_path,
        role="grounding",
        artifact="the grounding document as strict JSON",
        log_fn=log_fn)


def _validate(grounding):
    """Completeness of a proposed grounding. Returns a list of errors."""
    errors = []

    for field in REQUIRED_TOP:
        if not str(grounding.get(field) or "").strip():
            errors.append(
                f"grounding: no `{field}`. Every one of {', '.join(REQUIRED_TOP)} has "
                f"to be fixed before planning, because each of them is a decision "
                f"every section makes and none of them may be made twice.")

    estimand = str(grounding.get("estimand") or "").strip()
    if estimand and len(estimand.split()) < 8:
        errors.append(
            f"grounding: the estimand is {len(estimand.split())} words. That is a "
            f"topic, not an estimand. Say what quantity is reported, in what "
            f"population, over what window, from what data — in the language of the "
            f"analysis rather than of the conclusion.")

    lock = grounding.get("terminology") or []
    if not lock:
        errors.append(
            "grounding: no terminology lock. Name every entity this paper refers to "
            "more than twice: each method, each representation, each cohort, each "
            "outcome. For each one give the single string that names it and the "
            "plausible synonyms that must never appear. A second name for one thing "
            "reads as a second thing, and this is the only place it can be stopped.")
    else:
        for i, entry in enumerate(lock, 1):
            term = str(entry.get("term") or "").strip()
            if not term:
                errors.append(f"grounding: terminology entry {i} has no `term`")
                continue
            if not (entry.get("aliases") or entry.get("definition")):
                errors.append(
                    f"grounding: term {term!r} declares neither forbidden aliases nor "
                    f"a definition. A lock with no aliases enforces nothing — name "
                    f"the words a writer would reach for instead.")
        ok, term_errors = validate_terminology(lock)
        if not ok:
            errors.extend(f"grounding: {e}" for e in term_errors)

    checklist = grounding.get("checklist") or {}
    if not checklist.get("name"):
        errors.append(
            "grounding: no reporting checklist named. Say which one governs "
            "(TRIPOD+AI, STROBE, CONSORT, PRISMA, or `none` with a reason). Its items "
            "become obligations the outline places, rather than a form filled in the "
            "night before submission.")

    conventions = grounding.get("conventions") or {}
    for required in ("person", "tense"):
        if not str(conventions.get(required) or "").strip():
            errors.append(
                f"grounding: conventions has no `{required}`. Half a manuscript in "
                f"one voice is a thing reviewers notice and authors do not.")

    return errors


def existing(project_id):
    """A grounding already on disk that still passes the gate, or None.

    **Grounding is reused, not re-derived**, and that matters more than it looks.
    Terminology and an estimand are frequently settled by people rather than by this
    harness — a coauthor rules on what the outcome is called, a supervisor fixes the
    estimand, a journal dictates the reader. Re-proposing them on the next run gives
    the model a chance to drift away from a decision that was already made and already
    agreed, and nothing downstream would notice: every section would be internally
    consistent with a vocabulary nobody approved.

    So a valid grounding on disk is ground truth, exactly as frozen evidence is. To
    re-derive one, delete `state/project/<id>/grounding.json` — which is a deliberate
    act, and should be, because it invalidates every section written under the old
    vocabulary.

    Hand-writing the file is therefore a supported workflow rather than a hack. For a
    paper whose vocabulary and estimand already exist, it is the right one."""
    doc = storage.load_json(paths.grounding_path(project_id))
    if not isinstance(doc, dict) or not doc:
        return None
    errors = _validate(doc)
    if errors:
        return None
    return doc


def run(project_rec, log_fn=None):
    """Produce and gate the grounding, then persist it. Returns the grounding dict."""
    pid = project_rec["project_id"]

    committed = existing(pid)
    if committed is not None:
        if log_fn:
            log_fn(f"{pid}: grounding already on file and still valid — "
                   f"{len(committed.get('terminology', []))} locked term(s), "
                   f"reusing rather than re-deriving")
        return committed

    proposal = paths.grounding_proposal_path(pid)
    attempts = max(1, config.GATE_MAX_ATTEMPTS)
    feedback, errors, grounding = "", [], None

    for attempt in range(1, attempts + 1):
        propose_grounding(project_rec, proposal, log_fn=log_fn, feedback=feedback)
        grounding, why = storage.load_proposal(proposal)
        errors = ([why or "the grounding is not a JSON object"]
                  if not isinstance(grounding, dict) else _validate(grounding))
        if not errors:
            break
        if log_fn:
            log_fn(f"grounding: rejected (attempt {attempt}/{attempts}): {errors[:3]}")
        feedback = correction_brief(errors, attempt, attempts)

    if errors:
        raise RuntimeError(f"grounding: incomplete after {attempts} attempts: "
                           f"{errors[:4]}")

    storage.save_json(grounding, paths.grounding_path(pid))
    if log_fn:
        log_fn(f"{pid}: grounded — {len(grounding.get('terminology', []))} term(s) "
               f"locked, checklist {grounding.get('checklist', {}).get('name', '?')}")
    return grounding


def block(project_id):
    """The grounding as one inline block, for the prompts that need it."""
    grounding = storage.load_json(paths.grounding_path(project_id), {})
    if not grounding:
        return ""
    lines = ["WHAT THIS PAPER IS (fixed before drafting; every section obeys it):"]
    lines.append(f"  Estimand: {grounding.get('estimand', '')}")
    lines.append(f"  Venue:    {grounding.get('venue', '')}")
    lines.append(f"  Reader:   {grounding.get('reader', '')}")
    checklist = grounding.get("checklist") or {}
    if checklist.get("name"):
        lines.append(f"  Reporting: {checklist['name']}")
    conventions = grounding.get("conventions") or {}
    if conventions:
        lines.append("  Conventions: "
                     + "; ".join(f"{k} = {v}" for k, v in sorted(conventions.items())))
    limits = grounding.get("out_of_scope") or []
    if limits:
        lines.append("  OUT OF SCOPE — this paper does not claim any of these, and a "
                     "sentence that does is a defect:")
        lines += [f"      {item}" for item in limits]
    return "\n".join(lines)


def terminology(project_id):
    """The locked vocabulary, for the gates and the digest."""
    return storage.load_json(paths.grounding_path(project_id), {}).get(
        "terminology") or []


def conventions(project_id):
    """The prose conventions the whole manuscript holds to."""
    return storage.load_json(paths.grounding_path(project_id), {}).get(
        "conventions") or {}
