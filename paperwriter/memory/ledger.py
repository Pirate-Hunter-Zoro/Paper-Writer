"""The three-layer memory: schemas, invariants, and the gatekeeper that merges into
it.

Coherence in a manuscript cannot live in a model's context. A paper does not fit in
one, a paper plus its supplement and its reference library certainly does not, and the
failure mode of asking a model to "just keep writing" is not that it forgets — it is
that it *reinvents*. The abstract says 0.74 and the Results say 0.7429. The Methods
call it the feature representation and the Discussion calls it the rule-based
approach. The Introduction promises a subgroup analysis the paper never does.

So coherence lives on disk, in three layers, and only slices of it are fed into any
one prompt:

  * **Evidence** — cited facts, frozen after the gathering stage. Every number the
    analysis produced, every source the paper cites, every requirement of the
    reporting checklist. Immutable. Any prose that contradicts it is a hard failure.
  * **Project ledger** — what the paper has committed to. The terminology lock, the
    claim ledger, the open-question register, the reference list. Mutable, but only
    through the gatekeeper below, and only where the new state contradicts neither
    the evidence nor what was already committed.
  * **Paper ledger** — a working slice of the project ledger plus paper-local detail.
    Derived, and reconstructable from the project ledger and the accepted sections.

This module is schemas and rules. It reads no files — `store.py` does that — and it
decides nothing about what a given model is shown, which is `digest.py`. That
separation is what makes the gatekeeper testable with fixtures and nothing else.

**The gatekeeper's one job.** `merge_ledger_update` takes a model's proposed additions
and either applies all of them or none. A proposal that would introduce a claim with
no evidence, an alias for a locked term, a citation to a reference that does not
exist, or a second definition of a number already fixed is refused whole, and the
committed ledger is returned unchanged. Partial application is the failure that makes
a ledger untrustworthy: half of a bad proposal is worse than none of it, because
nothing downstream can tell which half landed.
"""

import copy
import re


# --- Evidence ----------------------------------------------------------------

def new_evidence(corpus):
    return {"corpus": corpus, "frozen": False, "items": [], "also_allow": []}


def validate_evidence(evidence):
    """Structural check on an evidence reference. Returns (ok, errors).

    The citation requirement is the load-bearing one. An evidence item with no source
    is a number somebody remembered, and a number somebody remembered is exactly what
    this whole layer exists to keep out of the manuscript."""
    errors = []
    if not evidence.get("corpus"):
        errors.append("evidence: missing corpus name")
    seen = set()
    for i, item in enumerate(evidence.get("items", [])):
        where = f"evidence item #{i}"
        eid = item.get("id")
        if not eid:
            errors.append(f"{where}: missing id")
        elif eid in seen:
            errors.append(f"{where}: duplicate id {eid!r}")
        else:
            seen.add(eid)
        if not item.get("statement"):
            errors.append(f"{where} ({eid}): missing statement")
        if not item.get("source"):
            errors.append(f"{where} ({eid}): missing source. Every item has to be "
                          f"traceable to a file, a table, or a citation — a number "
                          f"with no provenance is a number somebody remembered.")
        values = item.get("values")
        if values is not None and not isinstance(values, list):
            errors.append(f"{where} ({eid}): `values` must be a list of numbers")
        else:
            for v in values or []:
                try:
                    float(v)
                except (TypeError, ValueError):
                    errors.append(f"{where} ({eid}): value {v!r} is not a number")
    return (not errors, errors)


def evidence_ids(evidence):
    return {i["id"] for i in evidence.get("items", []) if i.get("id")}


# --- Terminology -------------------------------------------------------------

def new_term(term, aliases=None, first_use="", definition=""):
    """One locked term.

    `aliases` are FORBIDDEN spellings, not permitted ones. That inversion catches
    people out and is the right way round: the lock exists to name the words that must
    not appear, because the word that must appear is `term` and there is only one."""
    return {
        "term": term,
        "aliases": list(aliases or []),
        "first_use": first_use,        # expansion required at the first appearance
        "definition": definition,      # one sentence, for the writer's brief
    }


_ALIAS_OF_ITSELF = "an alias may not be the term it is an alias for"


def validate_terminology(lock):
    """Structural invariants of the terminology lock. Returns (ok, errors)."""
    errors = []
    seen, alias_owner = {}, {}
    for i, entry in enumerate(lock or []):
        term = str(entry.get("term") or "").strip()
        if not term:
            errors.append(f"terminology entry #{i}: missing term")
            continue
        key = term.lower()
        if key in seen:
            errors.append(f"term {term!r} is locked twice")
        seen[key] = term
        for alias in entry.get("aliases") or []:
            alias_key = str(alias).strip().lower()
            if not alias_key:
                continue
            if alias_key == key:
                errors.append(f"term {term!r}: {_ALIAS_OF_ITSELF}")
            elif alias_key in alias_owner and alias_owner[alias_key] != term:
                # The same forbidden word claimed by two terms is a lock that cannot
                # be satisfied: whichever term the writer uses, the other one's gate
                # fires. Better caught here than in a loop that never converges.
                errors.append(
                    f"alias {alias!r} is forbidden on behalf of both "
                    f"{alias_owner[alias_key]!r} and {term!r}. One of them has to "
                    f"give it up.")
            else:
                alias_owner[alias_key] = term
    # A locked term that is itself another term's forbidden alias is the same
    # unsatisfiable lock wearing a different hat.
    for alias_key, owner in alias_owner.items():
        if alias_key in seen and seen[alias_key] != owner:
            errors.append(
                f"{seen[alias_key]!r} is a locked term and also a forbidden alias of "
                f"{owner!r}. Nothing can satisfy both.")
    return (not errors, errors)


# --- Project ledger ----------------------------------------------------------

def new_project_ledger(project_id):
    return {
        "project_id": project_id,
        # The vocabulary, fixed before drafting. See `gates/terminology.py` for the
        # manuscript this cost two review rounds.
        "terminology": [],
        # Every claim the project has committed to making, keyed by id. Sections
        # reference these; nothing invents one at drafting time.
        "claims": {},
        # The reference list: key -> {authors, year, title, venue, doi}. A citation
        # marker with no entry here is a source the reader cannot check.
        "references": {},
        # Questions raised and not yet settled — the paper's own open ledger. Same
        # shape and tracking as a claim: {id, question, status, raised_in,
        # settled_in}. A question that is never settled is one the Discussion has to
        # concede, and knowing that at drafting time is the whole value.
        "questions": [],
        # What the reporting checklist requires and where it is satisfied.
        # {item: {requirement, section, satisfied}}
        "checklist": {},
        # Prose decisions that have to hold across sections: the tense of the
        # Methods, whether the paper says "we" or "the authors", how a confidence
        # interval is written. Small, and every one of them drifts without a record.
        "conventions": {},
        # Facts established by the paper's own prose as it is written: a definition
        # given in the Methods that the Results relies on.
        "facts": [],
    }


def new_claim(cid, statement, kind="descriptive", evidence=None, section="",
              headline=False):
    return {
        "id": cid,
        "claim": statement,
        "kind": kind,
        "evidence": list(evidence or []),
        "section": section,
        "headline": bool(headline),
        "status": "planned",       # planned -> drafted -> supported
    }


def validate_project_ledger(ledger):
    """Structural invariants of the project ledger. Returns (ok, errors)."""
    errors = []

    ok, term_errors = validate_terminology(ledger.get("terminology"))
    if not ok:
        errors.extend(term_errors)

    claims = ledger.get("claims", {})
    for cid, claim in claims.items():
        if claim.get("id") != cid:
            errors.append(f"claim {cid!r}: id field {claim.get('id')!r} does not "
                          f"match its key")
        if not str(claim.get("claim") or "").strip():
            errors.append(f"claim {cid!r}: no statement")

    references = ledger.get("references", {})
    for key, entry in references.items():
        if not isinstance(entry, dict):
            errors.append(f"reference {key!r}: entry is not a record")
            continue
        for field_name in ("title", "year"):
            if not entry.get(field_name):
                errors.append(f"reference {key!r}: missing {field_name}")

    fact_ids = set()
    for fact in ledger.get("facts", []):
        fid = fact.get("id")
        if not fid:
            errors.append("ledger fact: missing id")
        elif fid in fact_ids:
            errors.append(f"ledger fact: duplicate id {fid!r}")
        else:
            fact_ids.add(fid)

    question_ids = set()
    for question in ledger.get("questions", []):
        qid = question.get("id")
        if not qid:
            errors.append("open question: missing id")
        elif qid in question_ids:
            errors.append(f"open question: duplicate id {qid!r}")
        else:
            question_ids.add(qid)
        status = question.get("status")
        if status not in ("open", "settled"):
            errors.append(f"question {qid!r}: bad status {status!r}")
        if status == "settled" and not question.get("settled_in"):
            errors.append(f"question {qid!r}: marked settled without saying where")
    return (not errors, errors)


def open_questions(ledger):
    """Questions the paper has raised and not yet answered."""
    return [q for q in ledger.get("questions", []) if q.get("status") == "open"]


def unsupported_claims(ledger):
    """Claims the paper has committed to and not yet made in prose."""
    return [c for c in ledger.get("claims", {}).values()
            if c.get("status") != "supported"]


# --- The gatekeeper: merge a proposed update ---------------------------------

def merge_ledger_update(ledger, evidence, update):
    """Validate a model-proposed ledger update against the evidence and the prior
    ledger, and, only if every structural invariant holds, return the merged ledger.

    Returns (ok, errors, new_ledger). On failure new_ledger is the ORIGINAL ledger,
    unchanged — nothing is committed on a rejected proposal, and nothing is applied
    in part.

    An `update` may carry any of:
      * new_facts      : [{id, text, source}]        established by this section
      * new_claims     : [claim records]             claims this section introduced
      * support        : [claim id, ...]             claims now made in prose
      * new_questions  : [{id, question, raised_in}] raised here, not yet settled
      * settled        : [{id, settled_in}]          questions this section answered
      * new_references : {key: reference record}     sources cited for the first time
      * conventions    : {name: value}               prose decisions to hold onwards
      * checklist      : {item: {section, satisfied}}
    """
    errors = []
    known_evidence = evidence_ids(evidence)
    existing_fact_ids = {f["id"] for f in ledger.get("facts", []) if f.get("id")}
    existing_questions = {q["id"]: q for q in ledger.get("questions", [])
                          if q.get("id")}
    locked_terms = ledger.get("terminology") or []

    draft = copy.deepcopy(ledger)

    # 1. New facts: unique ids, and a source.
    for fact in update.get("new_facts", []) or []:
        fid = fact.get("id")
        if not fid or not fact.get("text"):
            errors.append(f"new fact missing id/text: {fact!r}")
            continue
        if fid in existing_fact_ids:
            errors.append(f"new fact {fid!r} collides with an existing ledger fact")
            continue
        existing_fact_ids.add(fid)
        draft["facts"].append({"id": fid, "text": fact["text"],
                               "source": fact.get("source", "")})

    # 2. New claims. Every one has to rest on evidence that exists, and it may not
    #    silently redefine a claim already committed — the ledger is what the outline
    #    placed sections against, and a claim that changes meaning after placement
    #    leaves a section arguing for something else.
    for record in update.get("new_claims", []) or []:
        cid = record.get("id")
        if not cid:
            errors.append("new claim missing id")
            continue
        statement = str(record.get("claim") or record.get("statement") or "").strip()
        if not statement:
            errors.append(f"claim {cid!r}: no statement")
            continue
        prior = draft["claims"].get(cid)
        if prior and prior.get("claim") != statement:
            errors.append(
                f"claim {cid!r} is already committed as {prior['claim']!r} and this "
                f"update restates it as {statement!r}. A claim the outline has "
                f"already placed cannot change meaning; give the new claim a new id.")
            continue
        cited = [str(e) for e in (record.get("evidence") or [])]
        if not cited:
            errors.append(f"claim {cid!r} rests on no evidence")
            continue
        unknown = [e for e in cited if known_evidence and e not in known_evidence]
        if unknown:
            errors.append(f"claim {cid!r} cites evidence that does not exist: "
                          f"{', '.join(unknown[:5])}")
            continue
        draft["claims"][cid] = new_claim(
            cid, statement, kind=record.get("kind", "descriptive"), evidence=cited,
            section=record.get("section", ""),
            headline=bool(record.get("headline")))

    # 3. Support: a claim is marked made-in-prose. It has to exist first.
    for cid in update.get("support", []) or []:
        claim = draft["claims"].get(str(cid))
        if claim is None:
            errors.append(f"cannot mark unknown claim {cid!r} as supported")
            continue
        claim["status"] = "supported"

    # 4. New questions: unique ids, opened only.
    for question in update.get("new_questions", []) or []:
        qid = question.get("id")
        if not qid:
            errors.append("new question missing id")
            continue
        if qid in existing_questions:
            errors.append(f"question {qid!r} collides with an existing question")
            continue
        existing_questions[qid] = question
        draft["questions"].append({
            "id": qid,
            "question": question.get("question", ""),
            "status": "open",
            "raised_in": question.get("raised_in"),
            "settled_in": None,
        })

    # 5. Settling: a settled question must reference an EXISTING open one, and may
    #    not be settled twice. Same guarantee as a payoff needing a setup.
    draft_questions = {q["id"]: q for q in draft["questions"] if q.get("id")}
    for entry in update.get("settled", []) or []:
        qid = entry.get("id")
        prior = existing_questions.get(qid)
        if prior is None or qid not in draft_questions:
            errors.append(f"settles unknown question {qid!r} (never raised)")
            continue
        if draft_questions[qid].get("status") == "settled":
            errors.append(f"question {qid!r} is already settled")
            continue
        if not entry.get("settled_in"):
            errors.append(f"question {qid!r}: settled without saying where")
            continue
        draft_questions[qid]["status"] = "settled"
        draft_questions[qid]["settled_in"] = entry["settled_in"]

    # 6. References: a key may be added, never silently redefined. Two different
    #    papers under one key is a citation that points at whichever one was written
    #    last, and nothing downstream can see that it happened.
    for key, entry in (update.get("new_references") or {}).items():
        if not isinstance(entry, dict):
            errors.append(f"reference {key!r}: entry is not a record")
            continue
        prior = draft["references"].get(key)
        if prior and prior.get("title") and entry.get("title") \
                and prior["title"] != entry["title"]:
            errors.append(
                f"reference {key!r} already points at {prior['title']!r} and this "
                f"update points it at {entry['title']!r}. Give the second source its "
                f"own key.")
            continue
        draft["references"][key] = {**(prior or {}), **entry}

    # 7. Conventions: a prose decision may be recorded once and then holds. Changing
    #    one mid-manuscript is how half a paper says "we" and half says "the authors".
    for name, value in (update.get("conventions") or {}).items():
        prior = draft["conventions"].get(name)
        if prior is not None and prior != value:
            errors.append(
                f"convention {name!r} is already fixed as {prior!r} and this update "
                f"changes it to {value!r}. Sections written under the old one would "
                f"have to be revised; change it deliberately, not in a merge.")
            continue
        draft["conventions"][name] = value

    # 8. Checklist coverage.
    for item, record in (update.get("checklist") or {}).items():
        current = dict(draft["checklist"].get(item) or {})
        current.update(record or {})
        draft["checklist"][item] = current

    # 9. Nothing may introduce a term that is already somebody's forbidden alias.
    #    Caught here rather than at the next gate run, because a ledger holding an
    #    unsatisfiable lock makes every later section fail for a reason the section
    #    did not cause.
    for entry in update.get("terminology", []) or []:
        draft["terminology"] = list(draft.get("terminology") or []) + [entry]
    ok, term_errors = validate_terminology(draft.get("terminology") or locked_terms)
    if not ok:
        errors.extend(term_errors)

    if errors:
        return (False, errors, ledger)   # reject: original ledger untouched
    return (True, [], draft)


# --- Small helpers the digest and the stages share ----------------------------

_SENTENCE_TAIL = re.compile(r"\s+")


def one_line(text, limit=160):
    """A record's text on one line, truncated. Used everywhere a brief has to list
    twenty things without becoming twenty paragraphs."""
    flat = _SENTENCE_TAIL.sub(" ", str(text or "")).strip()
    return flat if len(flat) <= limit else flat[:limit - 1].rstrip() + "…"
