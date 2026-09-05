# Planning — what papers, and which claims belong to which

You are deciding the shape of the work: how many papers come out of this evidence, what
each one is for, where it goes, and — the part that matters — which claim belongs to
which paper.

## Papers

One entry per paper, numbered from 1. Each carries:

- `number`, `title` (a working title, and it will change), `venue`.
- `word_limit` — the venue's total, in words, when the job states one. Omit it rather
  than guessing: a wrong limit plans a manuscript to the wrong length, and the outline
  gate enforces whatever you write here.
- `one_line` — what this paper is, in one sentence a colleague would understand.
- `keywords`, `authors` — if the job supplies them.

A single paper is the normal case. Do not manufacture a second one because the evidence
could support it; the job says how many, and a programme is a decision the authors make.

## Claims

This is the half that matters, and the half nothing downstream can second-guess.

One entry per claim the work makes. Each carries:

- `id` — short and unique (`c.1`, `c.2`, ...). Everything downstream addresses claims
  by id, so an id that changes is a claim that vanishes.
- `claim` — one sentence, stated as the paper will state it. Not a topic. "The embedded
  representation discriminates better than the feature representation on the held-out
  split" is a claim; "model comparison" is a heading.
- `kind` — one of `descriptive`, `comparative`, `mechanistic`, `methodological`,
  `limitation`, `implication`.
- `evidence` — the evidence ids that support it. **Every claim has at least one, and
  every id must exist in the frozen evidence.** A claim with nothing under it becomes a
  paragraph of assertion, and the gate refuses it.
- `paper` — which paper number makes it. Exactly one.
- `headline` — `true` for the one claim that paper is about, `false` for everything
  else.

## The rules the gate enforces

**Exactly one headline claim per paper.** It is the title, the last line of the
abstract, and the first line of the conclusions. Two headline claims is two papers, and
a reviewer will say so. None is a reader who finishes the abstract not knowing what was
found.

**Every claim belongs to exactly one paper.** Two papers arguing the same finding is a
duplicate submission, and it is invisible to every later gate because each paper looks
coherent on its own.

**The kinds vary.** A plan of nothing but `descriptive` claims is a report, not a
paper. Something has to be compared, explained, or qualified.

**At least one `limitation` claim.** A limitation planned now is one the paper can
answer. A limitation found at submission is one it has to concede, and the difference
is usually a review round. Look at the study design and name the thing a reviewer will
raise.

**Nothing is claimed twice.** Two claims saying the same thing become two paragraphs
saying one thing, and a reader who spends a minute looking for the difference.

**Every evidence item is used by something.** If the gathering stage produced a finding
no claim needs, either the argument dropped it or the gathering went looking for the
wrong thing. Both are worth knowing before drafting.

## Also

`references` — the reference list, as `{key: {title, year, authors, venue, doi}}`, for
every source the papers will cite. Take them from the evidence's `literature` items.
A key points at one paper forever, so give a second source its own key.

## Output

Strict JSON with `papers`, `claims`, and `references`, written to exactly the path you
are given.
