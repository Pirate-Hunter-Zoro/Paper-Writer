# Ledger merge — what this section settled

A section that has cleared the editorial loop has usually also settled something. Read
it and extract what changed, as structured data. This is extraction from a document
already in front of you, not judgement: report what the section did, not what it should
have done.

## What to report

- `support` — the claim ids this section actually made in prose. Only the ones it made.
  A claim the section merely mentioned is not supported by it.
- `new_claims` — a claim the section makes that the ledger does not hold. Rare, and it
  needs `evidence` ids that exist. If the section asserts something with no evidence
  behind it, that is a defect the review pass should have caught — report it as a claim
  with no evidence rather than inventing support for it, and the gatekeeper will refuse
  it.
- `new_facts` — a definition or a derived quantity this section established that later
  sections will rely on. `{id, text, source}`.
- `new_questions` — a question this section raises and does not answer. The Discussion
  will have to, and knowing that now is the whole value.
- `settled` — a question the ledger has open that this section answers, with
  `settled_in` naming where.
- `new_references` — a source cited here for the first time.
- `conventions` — a prose decision this section established that later sections must
  follow.
- `checklist` — reporting-checklist items this section satisfies.

## What the gatekeeper will refuse

Know these, because a refused merge costs a pass:

- A claim citing evidence that does not exist.
- A claim id that already exists with a different statement. Give a genuinely new claim
  a new id.
- Settling a question that was never raised, or one already settled.
- A reference key already pointing at a different paper.
- **A different value for a convention that is already fixed.** Sections written under
  the old value would have to be revised. If the section really does break a convention,
  that is a defect, not a new convention.

## Output

Strict JSON in the shape given, written to exactly the path you are given. Empty lists
are a real answer: a section that settled nothing reports nothing.
