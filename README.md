# Paper-Writer

An AI-driven manuscript factory for academic writing. You drop a filled prompt into a
folder. The harness reads the analysis output and the reference library, freezes what
it finds as cited evidence, fixes the paper's vocabulary and its estimand, plans the
argument claim by claim, outlines every section paragraph by paragraph, drafts each
one, and then edits every section against arithmetic until the prose is something a
reader understands on one pass. It assembles the manuscript, converts it, and delivers
it back to the same folder.

It is built on one sentence, inherited from the sibling repositories it grew out of:

> **The model proposes; a deterministic harness disposes.**

The language model never has the authority to mutate anything. It writes a *proposal*
to a file. Dumb, testable Python validates that proposal against ground truth, applies
it atomically, verifies the result, and only then records success in an append-only
journal. Everything below is in service of that one sentence, because it is the only
reason a system built on a confidently wrong model survives contact with a manuscript
somebody will publish.

---

## Contents

1. [The two problems this exists to solve](#the-two-problems-this-exists-to-solve)
2. [The prose contract, and why it is arithmetic](#the-prose-contract-and-why-it-is-arithmetic)
3. [Architecture: the propose/dispose spine](#architecture-the-proposedispose-spine)
4. [The three-layer memory](#the-three-layer-memory)
5. [The gates](#the-gates)
6. [The editorial loop — the feedback mechanic](#the-editorial-loop--the-feedback-mechanic)
7. [State machines](#state-machines)
8. [The stages, end to end](#the-stages-end-to-end)
9. [Robustness: nothing fails, everything stalls](#robustness-nothing-fails-everything-stalls)
10. [Running it](#running-it)
11. [The workflow: "here are results, write me a paper"](#the-workflow-here-are-results-write-me-a-paper)
12. [Configuration reference](#configuration-reference)
13. [Watching a run](#watching-a-run)
14. [Working in this repository](#working-in-this-repository)
15. [Code layout](#code-layout)
16. [Known limits and honest caveats](#known-limits-and-honest-caveats)

---

## The two problems this exists to solve

Neither of them is speed. A person can write a Methods section faster than this
harness can, on the first attempt. What a person cannot reliably do is the two things
below, and they are the reasons the machinery is worth its complexity.

### Problem 1 — a model produces a number that looks exactly right

Not a wild number. A plausible one. It rounds 0.712 to 0.71 in the abstract and leaves
0.712 in the results. It promotes a subgroup AUC to the headline figure. It writes
"approximately forty thousand" three paragraphs after stating 42,579. It reports a
confidence interval whose bounds do not bracket the estimate they belong to.

Every one of those survives a careful read by the person who wrote it, because the
number is familiar and the sentence is fluent. None of them survives a reviewer with
the supplement open.

The answer is that the harness holds a **frozen ledger of every number the analysis
actually produced**, and every number that appears in drafted prose is looked up in it.
A figure that is not there is a blocking defect, named with its exact location, and the
editorial loop repairs it like any other anchored issue. A model cannot argue with
arithmetic.

### Problem 2 — good prose is invisible from the inside

Density is the specific failure. A researcher who knows the material reads their own
26-word sentences fluently, because they already hold every clause. A reviewer does
not, and says the paper is "hard to follow", and the author cannot see what they mean.

That failure is measurable, and this project measures it. The thresholds in
`config.py` were calibrated against a real manuscript whose reviewers complained: body
text at a **mean of 26.2 words per sentence** against a readable 18–20, **23% of
sentences past 35 words**, **74 semicolons and 34 em-dashes in 15,000 words**. Nearly
every one of those marks welded a second claim into a sentence that already carried
one.

"Your prose is dense" is an argument. "23% of your sentences run past 35 words, and
here are the fifteen worst, each quoted verbatim so you can repair it" is not.

---

## The prose contract, and why it is arithmetic

One rule holds the whole thing up:

> **The reader must understand every sentence the first time they read it. If they
> have to go back over one, the sentence failed, however correct its content.**

The contract lives in three places and says the same thing in each: `prompts/draft.md`
tells the writer, `memory/digest.py` puts the specific numbers for *this* section into
the brief, and `gates/sentences.py` and `gates/paragraphs.py` measure the result. The
repetition is deliberate. An instruction is not a mechanism — the draft template said
"one idea per sentence" from the beginning and the 60-word sentences happened anyway.

### What is measured, at the sentence

| Measurement | Why it is the thing that goes wrong |
|---|---|
| Mean words per sentence, banded 12–22 | The aggregate. Over about 22 a section reads as heavy; under 12 it reads as clipped. |
| Standard deviation of sentence length, floor 4 | Every sentence the same length is the single loudest tell that a machine wrote the paragraph. The only check here that fires on prose which is individually fine. |
| Share of sentences past 35 words, ceiling 8% | A few long sentences are legitimate. One in five is a systematic problem, not a few bad lines. |
| Hard ceiling of 55 words | No sentence that long is doing one job, whatever the mean says. |
| Semicolons and em-dashes per 1,000 words, ceiling 2 each | Both are almost always two sentences pretending to be one. Rationed, not banned. |
| Empty openers | "It is worth noting", "Importantly", "Taken together" — a sentence whose only job is to introduce another one. |
| Stacked hedges | Two qualifications on one claim is a claim the author does not want to be held to. |

### What is measured, at the paragraph

A paragraph is a claim, its support, and its consequence. A reader who reads only the
first and last sentence of every paragraph should come away with the argument, because
that is how a reviewer under time pressure actually reads.

The gate cannot tell whether a topic sentence is *good*. It catches every structural
way a paragraph fails to have one, and that turns out to be most of the failures: it
opens on a citation, on a number, on a connective, or on a subordinate clause that
delays the claim past a comma; it is one sentence long; it runs past nine; it ends on a
citation rather than on what the paragraph means.

**The topic sentence is decided at outline time, not at drafting time.** That is the
load-bearing design decision. Once prose exists, a paragraph with no claim gets
repaired by *inventing* one — and an invented claim is exactly what the evidence ledger
exists to keep out. Asked for the sentence at outline time, the writer has to decide
what each paragraph is *for* before writing it, and a paragraph nobody can write a
topic sentence for does not belong in the paper. It is also the cheapest place to fix:
deleting a planned paragraph costs nothing.

### And one name per thing

A second name for something already named reads as a third thing. It is the most
expensive prose defect in a methods paper and it does not look like a defect — varying
your vocabulary is what everyone was taught.

The failure this gate was written from: a manuscript compared two patient
representations, the *feature representation* and the *embedded representation*.
Somewhere in drafting the first also became "the rule-based approach", because that one
sentence was about the absence of a generative model. A reviewer read three methods
where there were two, asked which one the ablation was run on, and the answer took a
paragraph and a review round. The fix was one banned word.

So the grounding stage locks the vocabulary before a word is drafted — each term, and
the synonyms that must **never** appear — and `gates/terminology.py` enforces it.

---

## Architecture: the propose/dispose spine

Each unit of work follows the same four beats:

1. **Propose.** A model is given a focused prompt and told to write its output to a
   known file path. We read the *file*, never the model's stdout. Stdout is chatty and
   unreliable; a file at a known path is a contract.
2. **Validate.** Deterministic code checks the proposal against ground truth — the
   frozen evidence, the committed ledger, the outline, hard numeric gates. This is the
   gatekeeper. It can reject, and rejection is cheap and reversible because nothing has
   been committed.
3. **Apply.** On a passing proposal, the harness writes the artifact into place
   *atomically* — into a hidden staging directory first, then an atomic rename — so no
   downstream stage ever observes a half-written section.
4. **Verify, then journal.** The harness confirms the artifact landed, records the new
   state in the append-only journal, and only then advances.

The model has zero authority. The worst a confidently wrong proposal can do is get
rejected and retried; it can never corrupt the ledger, overwrite a good section, or
ship a manuscript with a number nobody produced.

---

## The three-layer memory

Coherence cannot live in a model's context window. A paper does not fit in one, and the
failure mode of asking a model to "just keep writing" is not that it forgets — it is
that it **reinvents**. The abstract says 0.74 and the Results say 0.7429. The Methods
call it the feature representation and the Discussion calls it the rule-based approach.
The Introduction promises a subgroup analysis the paper never does.

So coherence lives on disk, in three layers, and only *slices* of it are fed into any
one prompt.

| Layer | Lifetime | What it holds | Ground-truth role |
|---|---|---|---|
| **Evidence** | Per corpus. Frozen after gathering. | One item per fact the paper might use: a statement, the exact numbers it licenses, and the file or citation it came from. | **Immutable.** Any number in prose that is not here is a hard failure. |
| **Project ledger** | Spans every paper in the project. Grows as sections are accepted. | The terminology lock, the claim ledger, the reference list, the prose conventions, and the open-question register. | **Mutable, all-or-nothing.** Changed only through the gatekeeper, and only where the new state contradicts neither the evidence nor what was already committed. |
| **Paper ledger** | One paper. | A working slice plus paper-local detail. | Derived. Reconstructable from the project ledger and the accepted sections. |

**Freezing the evidence is the point, and it is not about caching.** Once frozen, an
evidence document stops tracking the analysis. That sounds like a bug and is the most
important property here: an analysis rerun mid-draft that shifts an AUC from 0.7429 to
0.7511 must not silently change what the Methods section claims, because half the
manuscript was written against the old number and nothing would tell you which half.
Re-freezing is a deliberate act.

Frozen is not the same as finished. Evidence is keyed on the **corpus**, so three
papers off one analysis mine it once — and a frozen file that does not cover a new
job is **topped up** for exactly the claims it is missing rather than re-mined or
refused. A top-up appends and never rewrites, so a number a written section already
cited cannot change underneath it.

When a section is drafted, the writer is not handed the whole memory. It gets a
**focused brief**: the evidence its claims rest on quoted verbatim with sources, the
locked vocabulary with its forbidden synonyms, the conventions the earlier sections
established, the paragraph plan with its topic sentences, where the previous section
actually ended, and the prose contract with *this section's* numbers in it.

---

## The gates

No models, no I/O, no network. Given a proposal and the ground truth it must respect,
each returns a verdict a person can check by hand.

| Gate | What it refuses |
|---|---|
| `coverage` | Drafting on evidence that cannot support the claims. Below the floor the project parks and gathers more. |
| `claims` | An argument map that is not an argument: no headline claim or two, a claim resting on nothing, kinds that do not vary, no limitation planned, the same thing claimed twice. |
| `structure` | An outline that does not hold together: non-contiguous numbering, Results before Methods, budgets over the venue's limit, a claim placed twice or not at all, a paragraph with no declared topic sentence. |
| `numbers` | **A figure in the prose that the analysis never produced.** The most valuable gate here. |
| `terminology` | A forbidden synonym for a locked term; an abbreviation used before it is expanded, or expanded twice. |
| `citations` | A marker that resolves to nothing; a reference nobody cites; a borrowed claim carrying no source; two citation styles in one section. |
| `sentences` | The one-read rule, measured. See the table above. |
| `paragraphs` | Every structural way a paragraph fails to open on its claim or close on what it means. |
| `readability` | Flesch and Flesch-Kincaid, banded for an academic venue. Measures word length, which sentence statistics do not. |
| `length` | A section outside the band around its planned budget. The ceiling is the half that matters: over the venue's limit is a desk rejection before a reviewer reads a sentence. |

Everything there is trivially testable, which is the point. `tests/test_gates.py` is
the largest module in the suite for exactly that reason.

**One design note that recurs.** Several gates measure a whole-text statistic that
cannot be anchored to a span — a mean sentence length is a property of every sentence
at once. But the statistic is *driven* by specific sentences that can be quoted, so
every report carries the offending sentences **verbatim**, exactly as they appear in
the draft. That turns an un-anchorable statistic into a list of ordinary find/replace
repairs. The sentences are carried with their line breaks intact, because a repair
anchor is matched character for character and a tidied sentence is an anchor that
silently never applies.

---

## The editorial loop — the feedback mechanic

This is the largest correctness idea in the project, and the reason is arithmetic.

The obvious design is **critique then redraft**: a judge reads the section and writes a
prose complaint; a writer then reads that complaint, goes looking for the offending
text, and re-emits a correction. Two model calls per round, and the second has to
re-derive from a description something the first had already located exactly.

What it actually does is drift. Measured across a real run, blocking-issue counts per
attempt looked like:

```
unit  8   15 → 4 → 3 → 4 → 2 → 3 → 3 → 3 → 2 → 10 → 7 → 6 → 6 → 8 → 6 → 14 → …
unit 14   13 → 10 → 6 → 8 → 5 → 6 → 4 → 15 → 8 → 7 → 4 → 5 → 6 → 3 → 2
```

Those are not convergence curves. They are random walks. A unit that reached 2 went
back to 14, because the "revision" re-emitted everything and the judge — correctly —
found the new damage. Twenty-four attempts on one unit, and the twenty-fourth was worse
than the fifth.

**The fix is to stop moving a conclusion between two heads.** The editor holds the
section and the ground truth at once, and every issue it raises arrives with its own
exact find/replace repair, which deterministic code applies. Text nobody named is not
rewritten by anything, so it cannot drift, so the issue count falls monotonically and
two or three passes finish a section instead of ten.

What stays out of the model's hands, deliberately:

- **The gates.** Numbers, terminology, sentences, paragraphs, citations, length and
  readability are all computed *before* the call and handed to the editor as facts.
  A model asked "is this prose dense?" says no about its own prose. A model handed
  "23% of your sentences run past 35 words, and here are the fifteen worst" fixes them.
- **Application.** The editor proposes; `stages/patching.py` disposes. An anchor that
  matches twice is refused rather than guessed at.
- **The verdict.** The stage returns a report. Whether a section is finished is the
  engine's decision.

When a repair genuinely needs new prose — a paragraph with no topic sentence, a claim
asserted and never supported — the editor raises a `structural` entry naming an exact
passage, and `stages/surgery.py` replaces only that span. Everything outside it is not
passed through a model at all, so it is bit-identical afterwards by construction rather
than by instruction.

### And the sweep

A section that could not be made clean inside its own budget **ships holding its
notes** and is revisited once every section exists. That buys three things the
per-section loop cannot have:

- **The defect may have stopped being one.** A section flagged for raising a question
  it never answers is fine once the Discussion that answers it has been written.
- **The editor can see the whole manuscript.** A Discussion that over-claims can only
  be caught beside the Results it over-claims about. A term used two ways across two
  sections is invisible inside either one. An abstract written first is wrong by the
  time the paper is finished.
- **It is cheap.** Only flagged sections are re-read, and each gets an anchored repair.

The sweep stops on **blocking yield** rather than on "the editor still found
something". A demanding editor asked "is this perfect?" always says no, so polish must
never buy another round.

---

## State machines

Three nested levels, three journal key levels: **project → paper → section**.

**Project:**

```
PROMPT_DROPPED → GATHERING → GATHERED → GROUNDING → GROUNDED
               → PROJECT_PLANNING → PROJECT_PLANNED → PAPERS_IN_PROGRESS
               → PROJECT_COMPLETE
   (any step) ─────────→ STALLED ──(wait, doubling)──→ retry
```

**Paper:**

```
QUEUED → ARGUING → ARGUED → OUTLINING → OUTLINED → DRAFTING → DRAFTED
       → REVISING → BUILDING → BUILT → DELIVERING → DELIVERED → COMPLETED
```

**Section (inside DRAFTING):**

```
PENDING → SEC_DRAFTED → SEC_EDITING → ACCEPTED → LEDGER_MERGED
```

A single paper is a one-paper project, and there is no separate code path for it.
Building the general case costs nothing on the single-paper path and means "write this
paper" and "write these three papers off one analysis" are the same machinery with a
different count.

---

## The stages, end to end

| Stage | Proposes | Validated by | Applies |
|---|---|---|---|
| `evidence` | One item per fact, with its exact numbers and its source | `memory.ledger.validate_evidence`, then `gates.coverage` | Frozen evidence per corpus |
| `grounding` | Terminology lock, estimand, reader, checklist, conventions | Completeness gate in the stage | `grounding.json` |
| `planning` | Which papers, which claims belong to which | `gates.claims` | The plan, and the seeded ledger |
| `argument` | Claim → section → evidence, and what a reader must accept first | `gates.claims`, plus a dependency-order check | `argument.json`, chunk by chunk |
| `outlining` | Sections, budgets, and a paragraph plan with topic sentences | `gates.structure` | `outline.json` |
| `drafting` | One section's prose | The gates, via the editorial loop | A draft in staging |
| `review` | Every defect *with its repair* | `gates.*` computed before the call | An edit list |
| `patching` | — (pure) | Anchor uniqueness | The repaired prose |
| `surgery` | Replacement prose for one anchored passage | Anchor uniqueness, shrink floor | A splice |
| `ledger_update` | What this section settled | `memory.ledger.merge_ledger_update` | The merged ledger |
| `building` | — (pure, then pandoc) | The whole-manuscript audit | `manuscript.md`, then `.docx` |
| `delivery` | — (pure) | Content hash | The output folder, atomically |

**One ordering decision is the most important in the engine**, and it is
counter-intuitive: the ledger is merged *before* the prose is placed. A contradiction
found there is one more editorial pass. A contradiction found after the prose is on
disk is a corrupt ledger with a matching section beside it, and nothing downstream can
tell which of the two is wrong.

---

## Robustness: nothing fails, everything stalls

**There is no terminal failure state for a project, a paper, or a section.**

That is not optimism. It is the correction of a design that discards work: a section
parks, which fails its paper, which fails its project, which files the prompt away and
stops — leaving every finished section on disk and requiring a person to notice and
move a file before anything moves again. One stubborn Limitations paragraph can discard
a finished Methods, Results and Discussion.

What replaces it is not "retry the same thing forever":

- A section that cannot be made clean **ships anyway**, carrying a recorded list of
  what is still wrong, and the paper moves on. Nothing is thrown away.
- Infrastructure that keeps failing lands in **STALLED**, which is *not terminal*: the
  engine retries on an escalating backoff, indefinitely. An API outage, an allowance
  ceiling and a full disk all resolve on their own or when a person acts, and none of
  them is a reason to abandon a manuscript.
- A unit found mid-stage at startup was **abandoned** by a kill, a crash or a restart —
  the only process that could have been working it holds the lock. `recover_stale`
  rewinds it to its own entry point, which is what makes restarting mid-stage safe.

An allowance ceiling is not a failure at all. `QuotaExceeded` means "come back later":
nothing is parked, no status changes, and the run resumes by itself the moment the
ceiling lifts.

---

## Running it

Nothing outside the Python standard library is required to run the harness. Pandoc is
optional — the Markdown manuscript is the deliverable, and a missing pandoc skips the
conversion and says so rather than blocking delivery.

**Prerequisites**

- Python 3.9 or newer.
- The `claude` CLI, logged in. There is no API key anywhere in this project.
- `pandoc`, if you want a `.docx`.

**One-off setup**

```bash
git clone https://github.com/Pirate-Hunter-Zoro/Paper-Writer
cd Paper-Writer
git config core.hooksPath .githooks        # strips assistant attribution from commits
cp service/paperwriter.env{,.local}        # optional: keep your machine's config apart
$EDITOR service/paperwriter.env            # set PAPER_SOURCE_DIRS and PAPER_OUT_DIR
```

**Run one cycle by hand**

```bash
python3 -m paperwriter.daemons.author      # the engine, self-looping
python3 -m paperwriter.daemons.builder     # a one-shot: build and deliver
python3 -m paperwriter.cost                # what a paper is projected to consume
python3 -m unittest discover -s tests      # the suite: 200+ tests, stdlib only
```

**Run it as a service (systemd, user units)**

```bash
mkdir -p ~/.config/systemd/user
cp service/paperwriter-*.service service/paperwriter-builder.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now paperwriter-author.service
systemctl --user enable --now paperwriter-builder.timer
journalctl --user -u paperwriter-author -f
```

**Submit a paper**

Copy `PROMPT_TEMPLATE.md` into `$PAPER_OUT_DIR/_inbox/`, fill it in, and wait. The
harness admits it on the next cycle once the file has stopped changing, and writes
`_STATUS.md` beside it so progress is legible without a terminal.

---

## The workflow: "here are results, write me a paper"

This is the section to point an assistant at. It is what was actually done to produce
`Research-Journey/paper1-trd-prediction/reserve/manuscript_reserve.md`, and it is
repeatable for a new set of results.

**Say this, or something like it:**

> Read the workflow in Paper-Writer's README. My results are in `<path>`. The target is
> `<journal>`. Write the paper.

### What happens, in order

**1. Freeze the evidence.** Every number the paper may use is harvested out of the
results tree into one ledger: a statement, the exact values it licenses, and the file it
came from. Full precision, never rounded — a section may round a ledger value, and the
gate cannot expand a rounded one back.

Numbers from the *literature* go in too, each sourced to its reference. A cited figure is
still a figure the reader will check.

The ledger then stops tracking the analysis. That is the point rather than a limitation:
a rerun mid-draft that moves an AUC must not silently change what a written Methods
section claims. Re-freezing is deliberate — delete the corpus directory under
`state/evidence/` and the next cycle re-mines it.

**2. Write the grounding by hand, if the decisions already exist.** Terminology, the
estimand, the reader, the reporting checklist, the prose conventions, and what the paper
explicitly does *not* claim. `state/project/<id>/grounding.json`.

The harness will propose one if there is none. Do not let it, when a coauthor has already
ruled on what the outcome is called: `stages.grounding.run` reuses a valid file on disk
and only proposes when there is nothing there.

Get the **aliases** right, because that is the half that does the work. They are the
words that must *never* appear, not the approved ones. Ask what a fluent writer would
reach for on a sentence where the locked term feels repetitive, and forbid that.

**3. Plan the argument before any prose.** Claims with ids, each resting on evidence ids
that exist, exactly one marked headline, kinds that vary, and at least one limitation.
Then a section list, then a paragraph plan in which **every paragraph declares the
sentence it opens on**. A paragraph nobody can write a topic sentence for does not belong
in the paper, and deleting it now costs nothing.

**4. Draft one section at a time, and gate each one before moving on.** The gates are
cheap, they take milliseconds, and a defect found in section three is a defect that does
not propagate into section four's assumptions.

**5. Assemble, then run the whole-manuscript audit.** Three checks only exist at document
scope: a reference cited nowhere, an abbreviation expanded twice in the body, and the
prose statistics for the paper as a whole.

**6. Deliver into the analysis repository**, alongside the evidence ledger and the
grounding that produced it. A draft nobody can trace back to its numbers is a draft
somebody has to re-check by hand.

### Gating a section by hand

The daemon shells out to `claude`, so a Claude session driving it end to end would be a
session calling itself. The honest arrangement is to split the spine: **the model's half
is done directly and the harness does the deterministic half.** Propose/dispose, with a
person or a session as the proposer.

```python
from paperwriter.gates import numbers, paragraphs, sentences, terminology, citations

text = open("draft/04-results.md").read()
sentences.score(text, section_name="Results")        # density, welds, filler, hedges
paragraphs.check(text, section_name="Results")       # topic and concluding sentences
numbers.check(text, evidence)                        # every figure traces to the ledger
terminology.check(text, lock)                        # one name per thing
citations.check(text, references)                    # markers resolve, claims sourced
```

Section scope for all five. At manuscript scope use `terminology.check_manuscript` and
`citations.check_manuscript`, which add the checks that only exist across a whole
document.

### What to expect the gates to catch

On a real redraft of a 15,000-word manuscript, in order of how much they were worth:

- **Nothing wrong with the numbers.** 192 figures, every one traceable. That is a real
  result and worth stating: the number gate is insurance, and this manuscript did not
  need to claim on it.
- **Density, everywhere.** The submitted draft ran a mean of 28.8 words per sentence with
  28% of sentences past 35 words and the longest at 133. The Results section was worst,
  at 36.1. The redraft runs 16.5 and 2%.
- **Welds.** 9.5 semicolons and 7.2 em-dashes per thousand words, against a ration of 2
  each. The redraft uses 0.2 and 0.
- **A borrowed claim with no citation**, twice, both of them back-references to work
  cited in an earlier paragraph. Both were right to flag: a sentence saying what prior
  work found carries its marker even when the marker appeared before.
- **A terminology lock that was itself wrong.** The lock forbade "treatment resistance"
  as an alias for TRD, and this paper turns on the distinction between the construct and
  the label. The fix was to the lock, not to the prose. Expect this: a lock written
  before drafting will have one or two entries that only look wrong once a sentence
  needs them.

### And when the gate is the thing that is broken

Writing this paper found six defects in the gates themselves, and a later redraft of it
found three more. They are worth knowing about because the class of failure repeats:

**A gate that is silently off is worse than no gate.** The number pattern rejected any
figure followed by a full stop or a closing bracket, so every sentence-final number and
every upper confidence bound went unchecked. The gate reported clean sections and meant
"I looked at the numbers in the middle of sentences".

**A gate that contradicts itself teaches oscillation.** Terminology demanded that every
section expand its abbreviations and that no manuscript expand one twice. Both cannot
hold at section scope. First-use is now a manuscript-scope check.

**A splitter's edge cases are the measurement.** A sentence ending in a decimal was glued
to the next one, which inflated measured sentence length across every results section in
the project. A heading with no terminator glued itself to the paragraph below.

**A gate that punishes correct notation teaches the writer to damage the paper.** Three
of the six were this, and a later redraft found three more of exactly the same kind.
The dash ration counted en-dashes, so every confidence interval, percentage band and
year span scored as a weld: a Results section reporting forty intervals measured at
three times the ration and could not be brought under it by any amount of rewriting,
because the only remaining repair is to delete the numbers. The same ration counted
tight compounds, so `precision–recall` and `nearest–farthest` read as asides and the
suggested fix was to rename the analysis. And the splitter read the integer in
`Table 2.` as a list marker, so a paragraph of three ordinary sentences measured as one
38-word run-on, driven by the paper's own cross-references.

All three are now scoped. A dash between two numbers is a range and a tight en-dash
between two words is a compound; an em-dash is a weld wherever it appears, and an
en-dash is a weld when it is spaced. An integer is a list marker only when it opens its
line, or when the line opens with emphasis and a caption label.

If a gate fires on something that is plainly correct, suspect the gate first. All nine
were found by pointing the gates at real prose, and not one of them would have shown up
on a fixture.

## Configuration reference

Every tunable lives in `paperwriter/config.py` with the reasoning next to it. Every one
is overridable with a `PAPER_`-prefixed environment variable. The ones worth knowing:

| Variable | Default | What it decides |
|---|---|---|
| `PAPER_SOURCE_DIRS` | — | Colon-separated read-only trees the gathering stage may mine. |
| `PAPER_OUT_DIR` | `../Manuscripts` | Where the drop folder lives and finished papers land. |
| `PAPER_STATE_DIR` | `state/` | The whole runtime tree. Redirect it and everything moves. |
| `PAPER_MODEL` | `claude-opus-5` | Every text call. There are no tiers. |
| `PAPER_SENTENCE_MEAN_MAX` | `22` | Mean words per sentence, ceiling. |
| `PAPER_SENTENCE_LONG_SHARE_MAX` | `0.08` | Share of sentences allowed past 35 words. |
| `PAPER_SEMICOLON_RATE_MAX` | `2` | Semicolons per 1,000 words. |
| `PAPER_NUMBER_TOLERANCE` | `0.005` | How much rounding counts as the same number. |
| `PAPER_EVIDENCE_COVERAGE_MIN` | `0.85` | How much of the intended argument the evidence must support before drafting starts. |
| `PAPER_EDIT_MAX_PASSES` | `3` | Editorial passes before the loop asks whether it is still improving. |
| `PAPER_BUILD_FORMATS` | `docx` | What pandoc is asked for. Markdown is always kept. |
| `PAPER_QUIET_HOURS` | off | Whether to stay off a shared seat during the working day. |

---

## Watching a run

- **`_STATUS.md`**, in the drop folder. A phone-readable summary: what stage each
  project is in, how many sections are durable, and — the part that matters — what is
  *normal* for the stage it is in, so a quiet gap during a long model call is not read
  as a hang. Liveness is derived from the newest journal timestamp rather than from who
  wrote the file, so it cannot paper over a wedged engine.
- **`state/journal.jsonl`**, the append-only source of truth. Every state transition,
  one line each. Replay it and you have the world.
- **`state/decisions.log`**, a human-readable audit of every model call: what was
  proposed, what the gates said, which repairs landed.
- **`state/usage.jsonl`**, a list-price valuation of every call's token usage. **A
  meter, not a bill** — the CLI runs on a logged-in seat, so this measures allowance
  consumed rather than money owed.

A section's journal record carries its whole editorial trajectory: the blocking count
per pass, the measurements each gate produced, and any issue it shipped holding. That
is the record to read when the question is "why does this section read like this".

---

## Working in this repository

`AI_INSTRUCTIONS.md` is the contract for how an assistant behaves here, and it is
model-agnostic. Read it before touching anything.

This repository is **tutor-compatible**: it declares itself in `tutorboard.json`, so
[Tutor-Board](https://github.com/Pirate-Hunter-Zoro/Tutor-Board) can open it as a
course and teach the work on a live typeset board rather than in a terminal. `live/` is
that board's scratch space and is never tracked.

Commits carry no assistant attribution. `.githooks/commit-msg` strips the trailer, and
`scripts/save-and-push.sh` enables the hook path on any clone that has not opted in, so
it holds from the first commit rather than from the first time somebody remembers.

---

## Code layout

Layered so the propose/dispose sentence is enforced by the import graph rather than by
good intentions. Every layer may import the ones above it and never the ones below.

```
paperwriter/
  config.py  paths.py  errors.py     what and where. No I/O, no logic.
  infra/     journal, storage, locks, budget, logging, inbox. Knows nothing about
             papers.
  memory/    the three layers, their schemas, the merge gatekeeper, and the brief.
  gates/     the deterministic validators. Pure arithmetic and set logic.
  models/    THE ONLY place an external model is reached.
  stages/    one module per stage. Propose, validate, apply atomically.
  engine/    the nested project → paper → section state machine.
  daemons/   the two entry points. Thin: a lock, a loop, a call into engine/.
prompts/     the committed base prompts. Load-bearing non-code artifacts.
service/     systemd units, the launcher, and the deployed configuration.
tests/       200+ tests, standard library only, no network.
```

`models/` is the only layer that can be wrong in an interesting way, and nothing in it
has the authority to mutate committed state.

---

## Known limits and honest caveats

**The gates catch shape, not truth.** `numbers` proves a figure came from the evidence;
it cannot prove the evidence is right. `paragraphs` proves a paragraph opens on a
sentence shaped like a claim; it cannot tell you the claim is a good one. `citations`
proves a marker resolves; it cannot tell you the source says what the sentence says it
says. Everything here narrows the space a wrong manuscript can hide in. None of it
replaces reading the paper.

**The borrowed-claim check is a heuristic and is reported as one.** It flags sentences
whose *shape* asserts somebody else's finding with no marker attached. A false positive
costs one editorial pass. A false negative is a manuscript asserting somebody else's
result as its own, which is why the check errs toward flagging.

**The cost table has no measurements in it.** Every projection is token arithmetic,
which runs several times light because it cannot see the CLI's own system prompt or the
model's reasoning tokens. `--measured` says so rather than pretending. Fill
`MEASURED_USD` from a real run's `state/usage.jsonl`.

**There is no backup unit.** `state/project/` is the only copy of a run's plan,
outlines, ledgers and accepted sections. That is deliberate: the manuscript on disk *is*
the artifact and crash-resume is the journal's job. The consequence is real — lose
`state/project/` and the run is gone.

**A paper this harness produces is a first draft that has been edited hard.** It is not
a submission. Nobody has read it for whether the argument is worth making.
