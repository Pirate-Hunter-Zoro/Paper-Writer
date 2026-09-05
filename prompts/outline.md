# Outlining — expand the argument into sections and paragraphs

The argument map is fixed: which sections exist, and which claim lands in which. You
are turning that into a document — a budget for every section, and a plan for every
paragraph in it.

## The paragraph plan is the job

Every section gets a list of paragraphs, in order, and **every paragraph declares the
sentence it opens on.**

- `topic` — the sentence this paragraph opens with. Write it properly, in the paper's
  own voice, as a claim. The writer will use it. A label is not a topic sentence:
  "cohort characteristics" is a heading, "The cohort was younger and more female than
  the source population" is a topic sentence.
- `supports` — the claim ids this paragraph makes or supports.
- `evidence` — the evidence ids it cites.
- `closes` — what the last sentence says this paragraph means.

**A paragraph you cannot write a topic sentence for is a paragraph with no claim, and
it does not belong in the paper.** That is the whole reason this is decided here rather
than at drafting time: deleting a planned paragraph costs nothing, and deleting a
written one costs the writing. Worse, a writer asked to fix a paragraph with no claim
will invent one, and an invented claim is exactly what the evidence ledger exists to
keep out.

Three to nine sentences per paragraph is the shape. Plan accordingly: a paragraph
carrying four claims is three paragraphs.

## Budgets

Every section gets a `words` budget, and the budgets must total at most the venue's
limit. That is a hard ceiling — over it, the manuscript is desk-rejected before a
reviewer reads a sentence.

**Give each section the length its claims actually need, then cut a claim if the total
does not fit.** Do not shave every section to make room. A plan that only fits after
compression produces prose that has to be read twice, which is the specific failure this
whole harness exists to prevent. If the argument genuinely does not fit the venue, say
so in your reply — that is a real finding and the authors need it.

Rough shapes, for a 4,000-word clinical or methodological paper: abstract 300,
introduction 500, methods 1,200, results 1,000, discussion 900, conclusions 150. Adjust
to what this paper actually is.

## Also, per section

- `heading` — as it appears in the manuscript. Distinct from every other, under 80
  characters.
- `number` — contiguous from 1, in reading order.
- `evidence` — every evidence id the section draws on.
- `exit_state` — one line: what a reader now accepts, having read this section. The
  next section's writer is shown it, so it stops the manuscript restating itself.

## What you may not do

**Do not move a claim.** The argument map owns section assignment. You expand it.

**Do not add or drop a section.** The map's section list is the paper's shape.

**Do not put Results before Methods**, or a Discussion before its Results. The order is
checked.

## Output

Strict JSON in the shape given, written to exactly the path you are given.
