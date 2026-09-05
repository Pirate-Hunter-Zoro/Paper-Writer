# Grounding — fix what every section has to agree on

Before a word is planned, five things get decided once. Each of them is a decision every
section makes, and none of them may be made twice.

You are deciding them from the frozen evidence and the job prompt. Not from what would
be nice — from what the analysis actually supports and what the job actually asks for.

## 1. The terminology lock

**This is the most valuable field here and the one nobody writes down.**

Name every entity the paper refers to more than twice: each method, each
representation, each cohort, each outcome, each model. For each one:

- `term` — the single string that names it, everywhere in the manuscript.
- `aliases` — the strings that must **never** appear. These are forbidden, not
  permitted. That inversion is the whole point: the lock exists to name the words a
  writer would reach for instead.
- `first_use` — for an abbreviation, the expansion required at its first appearance.
- `definition` — one sentence, so the writer knows what it is.

Fill `aliases` properly. A lock with an empty alias list enforces nothing. Ask yourself
what a fluent writer would say instead, on a sentence where the locked term feels
repetitive, and forbid that. A manuscript once compared two patient representations and
called one of them "the rule-based approach" in a single sentence, because that sentence
was about the absence of a generative model. A reviewer read three methods where there
were two, and it cost a review round.

Two aliases may not be claimed by two different terms, and a locked term may not be
another term's forbidden alias. Either produces a lock nothing can satisfy.

## 2. The estimand

One sentence saying what quantity this paper reports: in what population, over what
window, from what data, measured how.

In the language of the analysis, not of the conclusion. "Discrimination of a
twelve-month treatment-resistance label on a held-out split of 8,516 patients, measured
by area under the ROC curve" is an estimand. "Whether the model works" is a topic.

Write it properly, because it is the sentence the Discussion cannot drift away from.

## 3. The reader

The target venue, and what its reader already knows. This sets what the Introduction may
assume, how much method belongs in the body rather than a supplement, and whether a
given abbreviation needs expanding at all.

## 4. The reporting checklist

Which one governs — TRIPOD+AI, STROBE, CONSORT, PRISMA — or `none` with a reason. List
its items if you can name them. They become obligations the outline has to place, which
is the difference between a checklist that shapes the paper and a form filled in the
night before submission.

## 5. The conventions

The small decisions that drift. At minimum:

- `person` — "we" or "the authors" or impersonal.
- `tense` — what tense the Methods is in, and the Results.

Add any others the paper needs: how a confidence interval is written, whether p-values
are reported with a leading zero, how a model is named on second reference.

Every one of these is trivial and every one of them drifts. Half a manuscript in one
voice is a thing reviewers notice and authors do not.

## Also

`out_of_scope` — a short list of claims this paper does **not** make. A sentence that
makes one of them is then a defect the review pass can catch, rather than an
over-claim nobody flagged until peer review.

## Output

Strict JSON with `terminology`, `estimand`, `venue`, `reader`, `checklist`,
`conventions` and `out_of_scope`, written to exactly the path you are given.
