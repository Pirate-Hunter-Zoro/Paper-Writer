# The argument map — turn a list of claims into a paper

The plan says which claims this paper makes. You decide how they become an argument:
which section each one lands in, what order the argument runs in, and what a reader has
to already accept before each claim can land.

That last field is what turns a list of findings into an argument, and it is the one
that gets skipped unless it is asked for by name.

## Sections

An ordered list of headings, as they will appear in the manuscript. Use the venue's
conventions and the IMRaD spine: front matter, Introduction, Methods, Results,
Discussion, Conclusions, Declarations, References. Split Methods and Results into
subsections where the paper needs them.

Sections carrying no claims are fine and are expected — a Declarations section is
structural. Every section that *does* carry claims should carry at least two; one claim
is a paragraph, not a section.

## Claims

Re-emit every claim you were given, unchanged in id and in meaning, with two fields
added:

- `section` — one of the headings above. Exactly one.
- `depends_on` — the ids of claims a reader must already accept before this one lands.

`depends_on` is checked: a claim whose premise is placed later in the paper is an
argument the reader cannot follow, and it is invisible once the sections are drafted
because each section reads fine on its own. If a Discussion claim rests on a Results
claim, say so, and the gate will confirm the Results comes first.

## What you may not do

**Do not add a claim.** The plan owns what this paper claims. A claim invented here has
no evidence behind it and no place in the ledger.

**Do not drop a claim.** Every one you were given lands in exactly one section.

**Do not change an id, and do not reword a claim into a different claim.** Improving
the wording is fine. Changing what it asserts is not — the outline places sections
against these claims, and a claim that changes meaning after placement leaves a section
arguing for something else.

**Do not move the headline.** It is what the paper is about, and it belongs where the
paper says what it found.

## Placement, briefly

- A `methodological` claim belongs in Methods, even when it is interesting.
- A `descriptive` or `comparative` claim belongs in Results, stated without
  interpretation.
- The interpretation of that claim is a different claim, it is `implication`, and it
  belongs in the Discussion. If you find yourself wanting to interpret in Results, the
  plan is missing a claim and you should say so in your reply rather than inventing one.
- A `limitation` belongs in the Discussion, near the end, and it names what would
  change the conclusion.

## Output

Strict JSON with `sections` and `claims`, written to exactly the path you are given.
