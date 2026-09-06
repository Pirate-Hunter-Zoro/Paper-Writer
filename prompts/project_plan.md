# Planning — what each paper is FOR, and which claims serve it

You are deciding the shape of the work: how many papers come out of this evidence, what
each one is for, where it goes, and — the part that matters — what each paper's POINTS
are and which claim serves which.

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

## Points — what each paper is for

**This is the most important field in the plan, and it is the one that has no obvious
place to come from later.** A point is what several claims add up to. It is what a
reader repeats to a colleague a week after reading the paper. Decide it here, because
this is the only stage that sees all the evidence at once; every later stage sees a
slice and would have to infer the points from the claims, which inverts the whole
thing.

One entry per point. Each carries:

- `id` — short and unique (`p.1`, `p.2`). Claims name their point by id.
- `point` — one sentence, as a reader would repeat it. "The embedding does not
  outperform the feature vector on this outcome" is a point. "Representation
  comparison" is a topic and the gate refuses it.
- `paper` — which paper number makes it. Exactly one.

**One to three per paper.** One is the ordinary case. Two is common, and is usually a
comparison plus what the comparison rules out. Three is the most a reader carries out
of the room. Four means you have stopped choosing, and the gate refuses it.

**A point is not an objective.** Objectives are things the analysis did. Points are
things the paper argues. If you find yourself writing three points where two of them
exist to show that the first is not an artifact, you have one point and two supporting
claims — and writing it the other way produces a paper with no spine, which is the
specific failure this field was added to prevent.

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
- `serves` — the point id (or ids) this claim serves. **Every claim either serves a
  point or declares a `role`, never both.** A claim that genuinely bears on two points
  names both; that is common and it is not a problem.
- `role` — for a claim that serves no point, one of:
  - `setup` — what a reader must know before any point can be made. The cohort, the
    data source, the temporal design. Not a finding.
  - `reporting` — required by the venue or a reporting checklist and by nothing else.

  There is deliberately **no role for a validity check**. A check that would have
  undermined a point and did not *serves* that point, and it should say which — often
  more than one. Given a role instead, validity material drifts to the front of the
  Results, ahead of the finding it is there to protect.
- `headline` — `true` for the one claim per point that states that point outright. It
  is the sentence the abstract and the conclusions both reuse. Exactly one per point.

## The rules the gate enforces

**Every claim ladders to a point, or says why it does not.** A claim that serves no
point and declares no role is refused. The honest answer is often to drop it: a finding
the paper does not need is a finding that belongs in supplementary material, and the
gate exists because a complete, correct, irrelevant section passes every other check
in this harness.

**Exactly one headline claim per point.** It is the sentence the abstract and the
conclusions reuse. Two claims marked headline on one point is a reader who cannot tell
which is the finding.

**Every point is carried by at least two claims, and not only by limitations.** A point
served by one claim is that claim, and calling it a point promises more than the paper
delivers. A point whose whole support is a caveat is not a finding — either the finding
it qualifies is missing from the map, or this is not a point.

**At most a third of the claims may declare a role.** A paper cannot be all argument,
but at that share the ladder is decoration and most of the paper is doing something
other than making its case.

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

Strict JSON with `papers`, `points`, `claims`, and `references`, written to exactly the
path you are given.
