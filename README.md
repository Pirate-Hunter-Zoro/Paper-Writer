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
3. [The support ladder, and why it is the only gate that refuses correct work](#the-support-ladder-and-why-it-is-the-only-gate-that-refuses-correct-work)
4. [Architecture: the propose/dispose spine](#architecture-the-proposedispose-spine)
5. [The three-layer memory](#the-three-layer-memory)
6. [The gates](#the-gates)
7. [The editorial loop — the feedback mechanic](#the-editorial-loop--the-feedback-mechanic)
8. [The final sweep — every gate, on the thing that ships](#the-final-sweep--every-gate-on-the-thing-that-ships)
9. [State machines](#state-machines)
10. [The stages, end to end](#the-stages-end-to-end)
11. [Robustness: nothing fails, everything stalls](#robustness-nothing-fails-everything-stalls)
12. [Running it](#running-it)
13. [The workflow: "here are results, write me a paper"](#the-workflow-here-are-results-write-me-a-paper)
14. [What comes out](#what-comes-out)
15. [Configuration reference](#configuration-reference)
16. [Watching a run](#watching-a-run)
17. [Working in this repository](#working-in-this-repository)
18. [Code layout](#code-layout)
19. [Known limits and honest caveats](#known-limits-and-honest-caveats)

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
| Semicolons and em-dashes per 1,000 words, ceiling 2 each | Both are almost always two sentences pretending to be one. Rationed, not banned, and **not counted inside a caption or a parenthesis** — "(held-out test set; primary Qwen3-Embedding-8B encoder)" is a label, and nothing inside a parenthetical can be welding two independent clauses. |
| Empty openers | "It is worth noting", "Importantly", "Taken together" — a sentence whose only job is to introduce another one. |
| Stacked hedges | Two qualifications on one claim is a claim the author does not want to be held to. |
| Mean words per sentence **inside one paragraph**, ceiling 26 | The section average is bought with easy sentences elsewhere. A real Methods section passed at 20.8 while carrying a four-sentence paragraph at 27.2, and a reader does not read the average. |
| Anticipatory rebuttals | "And not only a limitation", "it might be objected", "far from being a". The paper arguing with a reviewer who has not spoken yet. It is hard to read because it asks you to hold an objection nobody made. |
| A threshold with no value | "Below the conventional events-per-variable threshold." Below what? The number — 10 — was in a supplement the sentence does not point at. Numbers elsewhere in the sentence do not excuse it: those are the measurements, and the bar is what is missing. |
| A forecast with no source | "That constraint is a property of the tooling and is likely to move." Move which way, by when, on what evidence? A reader can act on "future work should test X" and can only wait for "X will improve". Recommendations pass; predictions about capability do not, unless cited. |
| The same word twice | "None exceeds 0.012 ROC ROC AUC", three times in one manuscript. A hard wrap hides it from every reader and from no machine. |
| A hedge stacked behind a full stop | "This is consistent with X. It does not establish X." The first sentence establishes nothing by construction, so the second spends 25 words un-claiming what nobody claimed — the stacked-hedge defect, moved where the per-sentence check cannot see it. |
| A ratio stated in words, in a sentence with no number | "Roughly a third the width of the marginal ones" is a measurement, and it was wrong: the intervals two sentences above were 0.029 and 0.030 against a paired 0.022. The `numbers` gate looks up numerals and there was no numeral to look up. |
| Equivalence claimed without an equivalence test | Whole-document. A paper whose Methods say no margin was prespecified, and whose Discussion then calls the result "parity" sixteen times, is arguing with itself in the reader's hands. Silent unless the paper itself supplies the disclaimer, and silent on the sentence that correctly *refuses* the word. |
| Unreported analyses | "Available from the corresponding author", "data not shown", "reported separately". A sentence that describes an analysis and then declines to report it advertises a result nobody can check. Report it or do not mention it — a data- or code-availability statement is different, and is required. |
| Tallied comparisons with no axis | "Ten of the eleven favour the narrative" asserts eleven comparative judgements and defines none of them. The count reads as evidence, which is why it survives a read that a vague sentence would not. |

### What is measured, at the paragraph

A paragraph is a claim, its support, and its consequence. A reader who reads only the
first and last sentence of every paragraph should come away with the argument, because
that is how a reviewer under time pressure actually reads.

The gate cannot tell whether a topic sentence is *good*. It catches every structural
way a paragraph fails to have one, and that turns out to be most of the failures: it
opens on a citation, on a number, on a connective, or on a subordinate clause that
delays the claim past a comma; it is one sentence long; it runs past nine; it ends on a
citation, or on a signpost, rather than on what the paragraph means.

A signpost is a closing citation in different clothes. "The full encoding rules are
described in Supplement M5 and two example narratives are reproduced in Supplement S5"
tells the reader where to go instead of what the paragraph established. A
cross-reference is support, and support belongs under the claim rather than in the
position the claim should hold. A pointer hanging off a sentence that states its
finding — "as shown in Figure 3" — is not this, and the gate does not touch it.

**The floor is two sentences, and it was three.** Three is the right shape for a
paragraph that *argues* — a claim, its support, what follows. It is the wrong floor for
the other paragraphs a paper is made of, and reading a real manuscript against it
settled that: of eight paragraphs it refused, seven were correct at two sentences. An
attrition statement with nothing more to say. A lead-in before a run of bolded
subsections. A claim and the consequence it licenses. The compact findings a
Conclusions section is made of.

Exactly one was a real defect, and it was **one** sentence — a fact left floating
between two paragraphs after a compression pass. That is the line. A single sentence
cannot be a claim plus anything. Whether two are enough is a question about the
section, and the outline answers it by naming a topic sentence for every planned
paragraph; counting sentences was standing in for that judgement and getting it wrong
seven times in eight.

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

**And the synonym nobody thought to ban.** A lock can only forbid what somebody listed,
so that rule is blind by construction to the second name invented during drafting. The
same manuscript went on to carry four names for one arm — the *typed feature
representation*, the *feature representation*, the *feature matrix*, the
*feature-vector* — through every gate, because only "rule-based approach" had ever been
declared. So the whole-manuscript pass also looks for **drift**: a phrase that shares a
locked term's modifier, ends in a different role noun, and is used more than once.
"Feature matrix" against a locked "feature representation" is a candidate second name.
"Feature selection" is not, because selection is not a thing the paper names. Pointed at
that manuscript it finds six undeclared names for two arms.

---

## The support ladder, and why it is the only gate that refuses correct work

Every other gate here checks that a piece of the paper is well made. One checks that
the piece *belongs*, and it is the only one that can refuse a section which is correct,
well written, fully evidenced and beside the point.

```
points   (1-3)      what the paper is FOR
  ^ serves
claims   (many)     what the paper ASSERTS
  ^ rests on
evidence (many)     what the analysis PRODUCED
```

`gates/claims.py` already owned the bottom join. `gates/ladder.py` owns the top one.

**The failure it was written from.** A finished manuscript from this harness had three
stated objectives, which were three things the analysis had done rather than three
things the paper argued. Two were support for the first: an encoder sweep showing the
headline null was not an artifact, and an ablation showing why the two arms tied. The
genuinely separate question was buried sixth of nine subsections with its motivation
stated nowhere. Every gate passed, every number traced, the prose was clean — and a
reader who stopped after the Results could not say what the paper claimed, because
nothing in the pipeline had ever asked.

The same manuscript carried a whole supplement section — a rubric, two verbatim
prompts, four worked examples, a re-judging experiment — in service of a null result
about a weighting scheme layered on a predictor that was not competitive. Complete,
correct, irrelevant. Nothing refused it, because nothing was counting what the paper
was for.

### What it enforces

| Check | Why |
|---|---|
| One to three points, each a sentence | One is the ordinary case and the degenerate case at once — the `headline` boolean this replaced was this gate with the count fixed at one. Three is the most a reader carries out of the room. Four is the count at which the author has stopped choosing. |
| Every claim serves a point, or declares a role | A claim that does neither is refused, and the honest answer is often to drop it. |
| Two roles only: `setup`, `reporting` | There is deliberately **no `validity` role**. A check that would have undermined a point and did not *serves* that point, and should name it — often more than one. Given a role instead, validity material drifts to the front of the Results, which is exactly where the real manuscript had put three of them, ahead of its own finding. |
| At most a third of claims may hold a role | An unbounded exemption turns the ladder into decoration, and "setup" is the easiest label in the world to reach for. |
| Every point carried by ≥2 claims, not all limitations | A point served by one claim *is* that claim. A point whose whole support is a caveat is not a finding. |
| Exactly one claim per point marked `headline` | It is the sentence the abstract and the conclusions both reuse. |
| **The word budget** | The share of planned words in sections that serve no point, warned at 15% and refused at 30%. |
| **The word budget, from the other side** | What ONE claim holds. Warned over 25%. A `limitation` that is both over 12% and longer than the headline claim of the point it qualifies is refused, because at that length a caveat has stopped qualifying the finding and started competing with it. |

**The budget is the check that matters**, and the reason is that a graph check only
asks whether every claim has a parent — which a determined writer satisfies by
attaching claims loosely. Length cannot be argued with. Front matter, references, and
any section the argument map gave *no* claims are exempt, because an Introduction that
sets up every point without asserting one is the ordinary case and counting its words
as serving nothing would fire on every well-built paper. What is not exempt is a
complete, well-evidenced section that nothing in the paper needs.

One rung lower, `gates/structure.py` asks the same question of paragraphs: every
paragraph advances a claim its section carries or says what it is doing instead, and
every claim a section carries is advanced by at least one of its paragraphs. A section
that carries three claims and plans nine paragraphs touching two of them drafts
cleanly, passes its prose gates, traces its numbers, and simply does not make the
third — and no gate after the outline can tell.

**Points are decided at planning time** and nowhere else, because that is the only
stage that sees all the evidence at once. Left to the argument map they would be
inferred from the claims, which inverts the ladder: claims exist to serve points, so a
point derived from the claims is whatever the claims happened to be.

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
| `claims` | An argument map that is not an argument: a claim resting on nothing, kinds that do not vary, no limitation planned, the same thing claimed twice. |
| `ladder` | **A paper with no spine, and material that serves nothing.** No declared points or more than three, a claim serving neither a point nor a stated role, a point carried by one claim or by nothing but caveats, and — the check that matters — too many of the planned words sitting in sections that serve no point, or on any one claim. |
| `structure` | An outline that does not hold together: non-contiguous numbering, Results before Methods, budgets over the venue's limit, a claim placed twice or not at all, a paragraph with no declared topic sentence, and a claim the section carries that no paragraph advances. |
| `numbers` | **A figure in the prose that the analysis never produced.** The most valuable gate here. A bibliographic number is not a finding, so the reference list is not scanned; the abstract is. |
| `terminology` | A forbidden synonym for a locked term; an undeclared near-variant of one; an abbreviation used before it is expanded, or expanded twice. A locked term now says which second names are *approved* as well as which are banned. |
| `citations` | A marker that resolves to nothing; a reference nobody cites; a borrowed claim carrying no source; two citation styles in one section; **and a reference list not numbered in order of first appearance.** |
| `crossrefs` | **A pointer the paper makes to itself that resolves to nothing, a gap in the numbering, and a pointer that names no target at all.** Whole-document, because a pointer is the one defect no per-section gate can see. |
| `procedures` | **A named procedure whose defining parameter the paper never states.** Benjamini-Hochberg without its false discovery rate; a bootstrap without its resample count. Both numbers existed in the analysis code and neither reached the paper. Whole-document, because a caption should not restate what the Methods stated. |
| `repetition` | **One point restated in three sections or more.** Two is a Discussion picking up what the Results said. Three is a paper that does not trust its reader. Front matter and captions exempt. |
| `sentences` | The one-read rule, measured at the section and again inside each paragraph. See the table above. |
| `paragraphs` | Every structural way a paragraph fails to open on its claim, or closes on a citation or a signpost instead of what it means. A standalone label is not a paragraph, and a methods paragraph may close on a pointer. |
| `readability` | Flesch and Flesch-Kincaid, banded for an academic venue. Measures word length, which sentence statistics do not — so it is measured everywhere and **banded only where the vocabulary is a choice.** |
| `venue` | The journal's own stated limits, plus four that hold whatever the journal says: **a title too long to read, a short title too long to be a running head, a heading marker swallowed into the middle of a line, and a missing IMRaD section.** A venue that states a character limit wins. Most state none, which meant nothing checked a title at all — one manuscript reached 34 words and 272 characters with every word of it accurate. |
| `length` | A section outside the band around its planned budget. The ceiling is the half that matters: over the venue's limit is a desk rejection before a reviewer reads a sentence. It also **warns** on a Results section spending too many words per number reported. |

Everything there is trivially testable, which is the point. `tests/test_gates.py` is
the largest module in the suite for exactly that reason.

### The pointers a paper makes to itself

`citations` asks whether `[27]` has a reference behind it. `crossrefs` asks the same of
"Supplement S10", "Table S12", "Figure 4" — and it is the same defect with a different
cause. A citation goes stale when a reference is added or dropped. A cross-reference
goes stale when a section is *cut*, and cutting a section is a thing that happens to
every paper on the way to submission.

Three supplement sections came out of one manuscript in a single afternoon. Each
removal renumbered everything below it, in two documents; one pass ran twice by
mistake, and the Methods ended up pointing at the subgroup analysis instead of the
field-level crosswalk. Every gate passed. Every gate looked at one section at a time,
and a pointer is the one defect that cannot be seen from inside the section that makes
it.

So the gate checks two things at whole-document scope. Every pointer resolves. And the
numbering is contiguous from 1 — because a supplement that skips S4 tells a reader a
section was lost, which is exactly what did happen and exactly what the renumber is
supposed to hide. It does **not** check that a pointer aims at the *right* thing;
nothing can, short of reading the paper. Resolution catches the renumber, contiguity
catches the excision.

Pointed at the manuscript immediately after a by-hand renumbering pass, it found one
dangling reference that three careful reads had missed.

**And the pointer that names nothing.** A resolver can only follow a pointer that has
an identifier in it, so a pointer without one was invisible by construction. "Full
table in supporting material" sat in a Table 1 caption of a finished manuscript. There
is no such document; the full table did not exist anywhere in the packet; and the
caption's own body sentence two lines above read "Table 1 gives every selected
characteristic". Every gate passed. It is the "data not shown" defect wearing a
cross-reference's clothes — a reader is sent somewhere and there is nowhere to go.

The check is narrow, because the phrase is common and usually fine. A pointer that
names its target passes however awkwardly it reads: "in Supplement M6", "the
supplement (Table S9)", "Appendix 1", "the Discussion, *Limitations*". What fails is a
bare gesture at the paper's own material with no number, label or section title
attached to it.

### The order a reference list is numbered in

`citations` already asked whether `[27]` resolves and whether reference 27 is cited
anywhere. It did not ask whether 27 is the right number, and Vancouver — with every
journal that uses it — numbers by **order of first appearance**.

That rule is pure copyediting, which is exactly why nothing catches it. A finished
manuscript from this project asserted the rule in its own header comment, and opened
its Introduction with `[23-25]` three paragraphs before it first cited `[4]`. The true
order of first appearance ran 1, 19, 10, 2, 3, 23, 24, 25, 26, 27, 28, 29, 20, 21, 9,
17, 18, 4 ... Every marker resolved. Every entry was cited. The list was contiguous
from 1 to 30. Three gates said yes and a copyeditor would have sent it back.

So the whole-manuscript pass walks the markers in reading order and reports the first
number that is not the one a list numbered by appearance would have there. Only numeric
markers can be out of order; a manuscript using author-year or pandoc keys has no
ordering to check and is skipped rather than passed. Repairing it is a remap of every
marker in the manuscript and the supplement at once, which is why the gate says so in
the message: renumbering one document and not the other is worse than not renumbering
at all.

### The heading that stopped being a heading

Markdown makes a heading out of `#` only when it opens the line. Anywhere else it is
four literal characters, and pandoc prints them.

One missing newline is the whole failure. An edit left `...is documented in Supplement
S8. # Methods` at the end of an Introduction paragraph. The built `.docx` carried
"# Methods" as body text and had no Methods heading anywhere in it — a fifteen-hundred
word Methods section rendered as a continuation of the Introduction. Every gate in this
project passed, and the reason is structural rather than careless: a gate handed one
section at a time cannot notice that a section boundary has stopped existing. The
outline had a Methods section. The splitter, which reads `# Methods` wherever it finds
it, produced a correct Methods part file. Only the assembled document was wrong, and
the assembled document is the artifact.

`venue` now refuses a `#` run that sits inside a line rather than opening one, and
separately checks that the assembled manuscript carries the five IMRaD headings at
all. The venue gate is the right home for both: this is the gate that asks whether the
file will be accepted, and a paper with no Methods heading will not be.

### Measuring how much of a Results section is reporting

A Results section's job is to give numbers. How many words it spends per number is
therefore a measure of how much of it reports and how much of it talks about the
reporting, and `length.density` is that ratio.

It was calibrated the way everything here is calibrated: by compressing a real Results
section by hand and checking whether the number followed. It did, everywhere —
discrimination 8.9 to 6.8, calibration 12.9 to 10.9, the ablation 13.8 to 12.5, the
validity checks 15.8 to 14.9.

It **warns** and never blocks, and the exception is the reason why. "What each
representation reads" scores 21 and is correct: it names its predictors — suicidality,
insomnia, obsessive-compulsive disorder — rather than measuring them, so it reports in
words. Blocking would tell that section to invent numbers.

### Two checks that were built, measured, and not shipped

Both were written for real defects, both looked obviously right, and both failed
against the manuscript. They are recorded because the next person to have the idea
should not have to rediscover the answer.

**Readability, in a methods section.** Not unshipped — shipped, and then scoped, which
makes it the third instance of the same lesson rather than a fourth idea. Flesch reading
ease and Flesch-Kincaid grade are driven by sentence length, which `sentences` already
measures directly and far better, and by syllables per word, which is the part this gate
is for. In a Methods section the syllables are not a choice. "Psychiatric and
substance-use comorbidity, medical comorbidity, prior antidepressant exposure and
medication burden, health-care utilization, and sociodemographic characteristics" is the
list of domains the study used, every word required, and nothing done to that sentence
improves it.

Pointed at a finished manuscript the band refused nine sections — the main Methods and
eight of thirteen Supplementary Methods, at reading ease 5 to 19 against a floor of 20 —
and all nine were correct. The lowest scored **-1.0**, and it is a list of clinical
domains. So the gate now measures every section and bands only the ones where the
vocabulary is chosen: Introduction, Results, Discussion, Conclusions, which pass at 30
to 38. An exempt section still records its numbers, because the record should show what
a section scored; what it does not get is a repair that does not exist.

**Nominalization density.** The contract says *verbs, not nominalizations*, and a
paragraph that passed every gate was unreadable for exactly that reason. Counting words
ending in *-tion, -ment, -ance, -ity* flags 44 sentences in this manuscript at four or
more, and the densest are "Domains included depression characteristics, psychiatric and
substance-use comorbidity, medical comorbidity, and social determinants of health" and
"Performance in the held-out test set was characterized using ROC AUC, calibration
slope and intercept, and precision-recall". Both correct. In a paper whose subject
matter IS discrimination, calibration, representation and distribution, the measure
tracks the topic rather than the prose.

**Captions that restate the body.** Two real instances existed — a figure caption
repeating a finding the body had just made, another repeating "385 of 4,096" verbatim.
Near-duplicate detection between a section's captions and its own body found neither,
because a restating caption reworded as it went, and returned two false positives
instead: a caption restating the index-date definition, and a panel list naming the
same three proxies the body names. A caption restating the setup is what makes it
self-contained.

The pattern in both: a measure that is right about prose in general is wrong about
prose whose subject is the thing being measured. What survives is always the narrower
check — a threshold with no value, a ratio spelled as a word, a comparison tallied with
no axis, a ratio of words to figures in the one phase whose job is figures.

### One thing the contract asks for and no gate measures

The prose contract says **verbs, not nominalizations** — "the model did worse when the
chart said unspecified", never "discrimination decreased for patients coded
unspecified". `prompts/draft.md` says it, `memory/digest.py` says it, and nothing
counts it. That is not an oversight, it is a decision, and it was taken by measuring.

A paragraph that passed every gate — mean 20.4 words, nothing past 35, correct shape —
was unreadable for exactly this reason: "validation of the label against chart-reviewed
or symptom-confirmed non-response" is ten words with no verb among them. So the obvious
check is nominalization density, counting words ending in *-tion, -ment, -ance, -ity*.

Run against the manuscript, that check flags 44 sentences at four or more. The densest
are these:

> Domains included depression characteristics, psychiatric and substance-use
> comorbidity, medical comorbidity, and social determinants of health.

> Performance in the held-out test set was characterized using ROC AUC, calibration
> slope and intercept, and precision–recall.

Both are correct. In a paper whose subject matter *is* discrimination, calibration,
representation and distribution, nominalization density measures the topic rather than
the prose, and a gate that fires on every Methods section is a gate somebody switches
off — the same failure the dash ration and the tallied-comparison check were both
narrowed to avoid.

What is checkable is the narrow case, and it is the one that carries the defect: a
threshold named without its value, a ratio spelled out as a word, a comparison tallied
without an axis. Each of those is a nominalization doing damage in a way arithmetic can
see. The general rule stays in the prompt, where a writer reads it, and out of the
gates, where it would only teach a writer to rename the analysis.

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

### And the revision sweep

Two things in this project are called a sweep and they are not the same thing, so both
carry their adjective. The **revision** sweep is here: model-driven, over the sections
that shipped flawed, before the manuscript is assembled. The **final** sweep is the next
chapter: pure arithmetic, over every document, after it is assembled. One re-edits
prose; the other measures what shipped.

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

The revision sweep stops on **blocking yield** rather than on "the editor still
found something". A demanding editor asked "is this perfect?" always says no, so polish must
never buy another round.

---

## The final sweep — every gate, on the thing that ships

Everything above happens to a *section*. The final sweep happens to the **packet**, it
happens after assembly, and it is the last thing that runs before a person reads the
paper.

That distinction sounds procedural. It is the difference between a manuscript with a
Methods section and one without.

**The failure it was written from.** A finished manuscript went out for its author's
read carrying nine defects. Every section had passed its editorial loop. The
whole-manuscript audit had passed. And a missing newline had left `# Methods` inside the
last sentence of the Introduction, so pandoc printed four literal characters and the
built `.docx` ran fifteen hundred words of Methods on as a continuation of the
Introduction. The outline had a Methods section. The splitter, which finds `# Methods`
wherever it sits, produced a correct part file. Only the assembled document was wrong —
and the assembled document is the artifact.

**Three gaps, and each one is a scope the old audit did not have.**

*It read one document.* `audit` opened `manuscript.md` and nothing else. The same packet
shipped a 75,000-word supplement carrying an undeclared third name for one study arm, a
section contradicting its own earlier subsection, an analysis advertised and never
reported, a small-cell rule defined two ways, and thirty-six table cells spelling one
term differently from the rest of the paper. None of it had ever been measured.

*It measured the manuscript as one block.* `sentences.score` over eleven thousand words
returns a mean, and a mean over a whole paper is the section-average problem one level
up: a tight Results buys an unreadable Methods. The prose contract is measured at the
section and again inside each paragraph for exactly that reason, and the audit threw
both resolutions away.

*It ran five gates of thirteen.* No `paragraphs`, no `readability`, no `crossrefs`, no
`procedures`, no `repetition`, no `length`. Three of those only exist at document scope,
which is to say the one place they could have run was the place that was not running
them.

### What it does, and what it refuses to do

Every gate, over every `#` section of every document the paper produced, plus every
check that only exists across a whole document or across the pair. Pointed at the packet
as it stood before that final review it returns **25 blocking findings**; pointed at the
same packet after, **0**.

**It does not block delivery.** A paper that is finished except for one uncited
reference reaches its author rather than sitting in a queue — the same rule that governs
a missing pandoc and the same rule that lets a section ship holding its notes. What the
sweep produces is a *list*: what is wrong, in which document, in which section, from
which gate, with the offending sentence quoted so it is a find-and-replace rather than a
hunt.

**That list leads `report.md`, and the position is the deliverable.** The point of the
sweep is that the reader sees the defects before they start reading, not after. A list
at the bottom of a report is read once the damage is done.

**Blocking and advisory are separated, and the split is not severity.** It is whether
arithmetic can be argued with. A number that is not in the ledger, a pointer that
resolves to nothing, a heading that will not render, a forbidden synonym: facts. A
borrowed-claim heuristic, a repetition count, a words-per-figure ratio: judgements the
gate is offering and the author may overrule. Mixing them is how a list stops being
read.

### The bug class it created, and the fix that generalised

Running gates section by section immediately broke four exemptions, all the same way: a
gate that keys an exemption on a **heading** cannot see one when it is handed a
section's **body**. The reference list's numbers came back as 58 findings. Two
reference titles came back as this paper's vocabulary. And the supplement was told to
expand TRD again, which is the same as telling the manuscript to expand it twice.

So `numbers.check` and `terminology.check` now take a `section_name`, the way
`sentences`, `paragraphs` and `readability` already did, and
`terminology.check_manuscript` takes `first_use=False` for a companion document. The
general rule the final sweep forced into the open: **an exemption keyed on document structure has to be reachable by name, or it
switches off silently the moment somebody measures at a finer grain.**

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
| `planning` | Which papers, what each is FOR, which claims serve it | `gates.claims`, `gates.ladder` | The plan, and the seeded ledger |
| `argument` | Claim → section → evidence, and what a reader must accept first | `gates.claims`, `gates.ladder`, plus a dependency-order check | `argument.json`, chunk by chunk |
| `outlining` | Sections, budgets, and a paragraph plan with topic sentences | `gates.structure`, `gates.ladder` (the word budget) | `outline.json` |
| `drafting` | One section's prose | The gates, via the editorial loop | A draft in staging |
| `review` | Every defect *with its repair* | `gates.*` computed before the call | An edit list |
| `patching` | — (pure) | Anchor uniqueness | The repaired prose |
| `surgery` | Replacement prose for one anchored passage | Anchor uniqueness, shrink floor | A splice |
| `ledger_update` | What this section settled | `memory.ledger.merge_ledger_update` | The merged ledger |
| `reporting` | — (pure) | — | `report.md`: the ladder, the measurements, what shipped holding |
| `sweep` | — (pure) | — (it *is* the validation) | Nothing. It returns findings, and they lead `report.md` |
| `building` | — (pure, then pandoc) | The final sweep | `manuscript.md` and `report.md`, then a `.docx` of each |
| `delivery` | — (pure) | Content hash | The output folder, atomically |
| `shipping` | — (pure, then git) | A refusal check on the working tree | A commit, and a push if asked |

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

**Pandoc is usually installed and usually not on `PATH`.** It ships inside conda
distributions, inside RStudio Server, inside Quarto, and `which pandoc` finds none of
them. Believing it absent on that evidence is a mistake this project made once and
paid for: conversion is optional, so the run reported success, and the `.docx` beside
each Markdown file quietly went on being an old file that still looked like an
artifact. Stale is worse than missing, because nothing announces it.

So `config.PANDOC_BIN` **searches** rather than guessing a name. `PAPER_PANDOC_BIN`
first and unquestioned, then `PATH`, then the usual install locations, then
`$CONDA_PREFIX/bin`, and only then the bare name — which at least fails loudly. On the
machine this was written on it resolves inside the Anaconda tree, whose `condabin/` is
on `PATH` and whose `bin/` is not.

**To rebuild the documents of a paper by hand**, after editing the Markdown, stand in
the paper's repository and say:

```bash
rebuild
```

That is the loop, and one word is the point of it. `rebuild` is a shell function defined
in `config/rebuild-alias.sh` and sourced from `~/.bashrc`:

```bash
if [ -r "$HOME/Paper-Writer/config/rebuild-alias.sh" ]; then
    . "$HOME/Paper-Writer/config/rebuild-alias.sh"
fi
```

The definition lives in the repository rather than in the profile so it stays tracked,
for the plain reason that a profile is the one file on a machine nobody has a copy of.
Arguments pass straight through — `rebuild --all`, `rebuild --list`, `rebuild --strict`,
`rebuild some/paper`, `rebuild path/to/one.md`.

**A function rather than an alias, and the default lives in the script.** An alias
cannot both default to the current directory and pass a path through: `alias
rebuild='rebuild-docs.sh .'` turns `rebuild some/paper` into two targets and quietly
rebuilds the whole repository alongside the folder you named. Putting the default in
the *function* is the same trap one layer up, and it is the one I walked into —
`"${@:-.}"` supplies nothing when an argument is present, so `rebuild --list` ran with
no path at all and fell through to the output folder. The default belongs where the
argument parser is.

The script is fine to call directly, and takes the same arguments:

```bash
scripts/rebuild-docs.sh ~/Research-Journey            # or a paper, or one file
```

With no path it walks the repository you are standing in. Failing that it falls back to
`PAPER_DOCS_DIRS`, colon-separated, and then to `OUT_DIR`. **The current directory
outranks the environment variable**, which reads oddly and is right: typing a bare
`rebuild` while standing in a paper repository is an instruction about *that*
repository, and a variable set once in a profile should not silently redirect it
somewhere else. `PAPER_DOCS_DIRS` is for the runs made from somewhere else — a cron
job, a home directory — and is the only variable in the table below that `config.py`
does not read.

That is the loop the script exists for. Open a `.md`, cut the clause that was bothering
you, run this, ship the repository. The Markdown is the source and the `.docx` is built
from it, so editing the `.docx` instead is how the two stop agreeing.

It walks the tree, builds every `.docx` that is missing or older than its `.md`, and
leaves the rest alone — a `.docx` younger than its source is already the document, and
rebuilding it churns a binary file in git for nothing. `--all` overrides that when a
styles template changed and no timestamp can see it. `--list` says what it would do and
does nothing.

**What is not a paper is not built.** A `README.md` describes the folder it sits in and
nobody submits it, so the script walks past it and its kin — the list is `SKIP_NAMES` at
the top of the script, and it is meant to be edited. Everything else under the tree is
paper prose. Every run says how many documents it walked past, because a policy nobody
can see is a policy nobody can correct.

The template and the figure paths are resolved against the enclosing **repository**,
not against the path typed on the command line. Both are properties of the paper:
`../results/roc.png`, in a section under `parts/manuscript/`, was written relative to
the paper folder. Deriving either from the argument would make rebuilding one file
produce a different document from rebuilding all of them, which is the one thing a
rebuild script must not do.

Conversion goes through `building.convert_one` rather than a bare pandoc line, so a
document rebuilt by hand is the document the pipeline would have produced. That
includes the resource path — see below, because it is the reason the parts used to
build clean and arrive empty.

### The figure that resolves in the whole and not in the part

`convert_one` puts the document's own directory on pandoc's `--resource-path`, and for
a while that was all it put there. It is right for a manuscript, whose
`![](../results/roc.png)` is written relative to the folder the manuscript sits in. It
is wrong for every section `stages/splitting` cuts out of that manuscript, because the
part inherits the path verbatim and now sits one directory deeper. Pandoc resolved it
to `parts/results/roc.png`, found nothing, **warned on stderr and exited 0**, and wrote
a `.docx` with twenty figures missing.

Nothing downstream could tell that document from a section that never had a figure. So
a caller that knows the root those paths were written against now names it —
`convert_all` passes the paper root, and `rebuild-docs.sh` passes the repository — and
the part converts the way the whole does.

A bare `pandoc x.md -o x.docx` has the same failure and no caller to fix it.

**The pipeline's own builds needed a knob, not a search.** The harness converts inside
the state tree, and `../results/roc.png` resolves to nothing from there. The fix cannot
be "put the analysis tree on the resource path", because the `..` is doing the work:
what pandoc needs is a directory whose *sibling* is the results folder, not the results
folder itself. Only the author knows which directory that is, so `PAPER_BUILD_RESOURCE_DIRS`
names it and every conversion picks it up:

```
PAPER_BUILD_RESOURCE_DIRS=$HOME/Research-Journey/paper1-trd-prediction
```

Empty is the right setting for a paper this harness wrote on its own. It has no way to
emit an image reference — "figure" in every one of its prompts means a number, and no
stage writes Markdown image syntax. This is for the manuscript a person has since put
figures into, which is every manuscript, eventually.

**And the build is checked against its own output.** A resolved path is not something
to take on trust, because the failure mode is a warning and a zero exit status.
`figures_lost` opens the built `.docx`, counts the images actually in it, subtracts any
the reference template brought along, and compares that to the distinct images the
Markdown asks for. A document that came up short is named in the log with its count.
`rebuild-docs.sh` fails the run on it, because you were about to ship it.

It found two on its first full pass over a real repository — two reserve documents that
had been committed carrying none of their nine figures between them, built at some point
by something that gave pandoc neither a resource path nor a template. Nothing had ever
said so.

### The figure that fits on the page

A figure can resolve, embed, and still ruin the page, and `gates/figures.py` measures the
two ways. A figure with no `{width=...in}` is imported at full page width, because pandoc
honours absolute widths in a `.docx` and silently ignores percentages. And a row of panels
wider than the printable column is not refused by Word — it is shrunk, until the panels
stop lining up with the labels above them, which is the failure the two-column table
layout existed to prevent.

The printable column is measured from the venue's own reference document rather than
assumed: page width less margins, in twips, from its `document.xml`. US Letter at 1.25in
margins is the fallback when that cannot be read, because checking against a conventional
page beats declining to check.

Both warn and neither blocks. They are properties of a document somebody wrote, not of
today's conversion, and a figure that has always been too wide is not a reason to refuse
to rebuild the paper. `rebuild-docs.sh --strict` is the run to make before submitting.

This gate is a port. It came from `Research-Journey/tooling/build_docx.py`, which is
where the failures were learned and which it replaced — everything else that tool did,
`rebuild-docs.sh` already did better, and its own missing-file check resolved paths from
the document's own directory and so reported 56 false alarms on a tree with none. The
port catches one thing the original could not: a captioned figure with no width, which
its pattern was blind to because it required the alt text to be empty.

**Prerequisites**

- Python 3.9 or newer.
- The `claude` CLI, logged in. There is no API key anywhere in this project.
- `pandoc`, if you want a `.docx`. Check for it with `config.PANDOC_BIN` rather
  than `which pandoc` — see above.

**One-off setup**

```bash
git clone https://github.com/Pirate-Hunter-Zoro/Paper-Writer
cd Paper-Writer
git config core.hooksPath .githooks        # strips assistant attribution from commits
cp service/paperwriter.env{,.local}        # optional: keep your machine's config apart
$EDITOR service/paperwriter.env            # set PAPER_SOURCE_DIRS and PAPER_OUT_DIR

# and, for the `rebuild` command, one guarded block in ~/.bashrc:
#   if [ -r "$HOME/Paper-Writer/config/rebuild-alias.sh" ]; then
#       . "$HOME/Paper-Writer/config/rebuild-alias.sh"
#   fi
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

**5. Assemble, then run the final sweep.** Every gate, over every section of every
document in the packet, on the assembled text rather than on the drafts. Assembly and
the hand edits after it are where a manuscript acquires the defects no per-section pass
can see: a heading that stopped rendering, a pointer to a section that was cut, a
reference list that drifted out of order, a supplement nobody re-read. It does not block
delivery, and its findings lead the author's report — the reader should see the list
before they start reading rather than after.

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

**A final review of that manuscript found four more, and all four were the same
shape.** A gate scoping rule that was right about prose in general and wrong about the
part of a paper it was pointed at.

The `numbers` gate scanned the reference list. A Vancouver entry is a dense block of
numbers and not one of them is a result — a volume, an issue, a page range, a DOI
prefix, an arXiv id — and no evidence ledger will ever contain
`doi:10.1145/3626772.3657878`. The gate returned 58 unsupported numbers, all 58
bibliographic, against 288 real figures every one of which traced. That is not a gate
reporting a defect, it is a gate nobody can read. The reference list is now out of
scope and **the abstract emphatically is not**, because an abstract rounding 0.712 to
0.71 while the results say 0.712 is the defect the gate exists for.

The `terminology` gate flagged two reference titles. A lock forbidding "resistant
depression" in favour of "TRD" matched inside "Treatment resistant depression in
electronic health records: definitions matter", which is somebody else's published
title. You cannot rename another author's paper, and the only repair on offer was to
misquote a citation. The same gate also flagged the term's own approved expansion,
because "treatment-resistant depression" contains "resistant depression" — the same
false positive the code already handled one level out for "AUC" inside "ROC AUC".

The weld ration's parenthesis exemption silently switched off whenever the parenthetical
was hard-wrapped. Drafted prose arrives hard-wrapped as a matter of course, so a
parenthetical starting two thirds of the way along a line is routinely split across two
of them; excluding the newline from the exemption meant those were counted. One wrapped
pointer pair scored a supplement section at 2.5 semicolons per thousand words against a
ration of 2, and the only repair available was to damage the cross-reference.

The mean-sentence-length **floor** counted captions. A caption's length is set by
convention, not by the writer's rhythm: "***Table A1.** Quantitative predictors (15;
continuous, standardized).*" is eight words because that is what a table label is. A
predictor-inventory appendix of five tables and one lead-in paragraph measured 10.8
words per sentence against a floor of 12, on prose that averages twenty. The ceiling
still counts captions, because a caption a reader cannot parse on one pass is a real
defect. The floor cannot.

**And two paragraph-shape rules were narrowed by the same measurement.** A block that
is nothing but a bold label — `**TRD-positive example.**` above a fenced narrative — is
not a paragraph, and neither is a `---` rule; a supplement reproducing two example
narratives reported three too-short paragraphs out of six, on two labels and a
horizontal rule. And the closing-signpost rule does not run in a methods section. A
methods paragraph's job is to specify a procedure, and when the fuller specification
lives in a supplement the pointer *is* the rest of that paragraph's content: "Full
index-selection rules are given in Supplement M2" is where the paragraph goes and there
is nothing else for it to close on. Pointed at a real Methods section the rule refused
eight of twenty-one paragraphs and all eight were correct as written. The narrowing is
by section name, so a supplementary methods section counts as one, and everything else
about a methods paragraph — including its opener — is still checked.

## What comes out

Every document the pipeline produces is converted and delivered, not just the
manuscript. The set is discovered from disk rather than listed, so a stage that starts
emitting another document gets it built and shipped without anybody remembering to come
back and add it.

| Document | What it is |
|---|---|
| `manuscript.md` | the paper. The artifact; everything else is built from it or about it |
| `report.md` | **the author's report.** Led by the final sweep — every gate, every section, every document — then what the paper was for, how the prose measures against every band, what shipped unresolved, and where the numbers came from |
| `<each>.docx` | one per Markdown document, through pandoc against the venue's reference document |

**Why the report is a document and not a log.** All of it was already true and none of
it was readable: the ladder was in the plan, the gate measurements were in
`state/decisions.log`, the issues a section shipped holding were in the journal, and a
person wanting all three read three files in two formats and joined them by hand. The
pipeline's job is not finished when the prose is written. It is finished when the author
can see what was checked.

Nothing in the report is generated. Every line is read off state the pipeline already
committed, because a report that *summarised* the paper would be a second opinion about
it, and this is a record.

### And then it can commit

If the delivery folder is a git working tree, `infra/shipping.py` will commit the
delivered files and — separately opted into — push them. Both halves are off by
default, because pushing to a remote is the only outward-facing thing this harness does.

It is deliberately narrow:

- **It stages the delivered files by path.** Never `git add -A`. A daemon that swept the
  working tree would eventually commit half of an unrelated edit under a message about a
  manuscript.
- **It refuses rather than forces.** A detached HEAD, a merge or rebase in progress,
  changes already staged by somebody else, or a failing push all stop it with an
  explanation. The paper is delivered by then, so stopping costs one commit made by
  hand and the alternative costs history.
- **It never raises into the engine.** A git problem must not be the reason a finished
  paper's status stays unfinished — the same rule that governs a missing pandoc.

```bash
PAPER_SHIP_REPO=/path/to/analysis-repo    # commit delivered papers here
PAPER_SHIP_PUSH=1                         # and push them
```

---

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
| `PAPER_BUILD_FORMATS` | `docx` | What pandoc is asked for, for every document. Markdown is always kept. |
| `PAPER_PANDOC_BIN` | searched | The pandoc to use. Unset means: `PATH`, then the usual conda/RStudio/Quarto locations, then the bare name. |
| `PAPER_BUILD_RESOURCE_DIRS` | none | Extra directories pandoc looks in for a figure. Set it to the folder the delivered paper will sit in, not to the results tree — see below. |
| `PAPER_POINTS_MAX` | `3` | How many points a paper may be about. Four is the count at which the author has stopped choosing. |
| `PAPER_UNLADDERED_WORDS_MAX` | `0.30` | Share of planned words allowed in sections that serve no point. |
| `PAPER_SWEEP_LOG_FINDINGS` | `10` | Blocking findings the final sweep prints to the log. The full list always reaches `report.md`. |
| `PAPER_SHIP_REPO` | off | A git working tree to commit delivered papers into. |
| `PAPER_SHIP_PUSH` | off | Whether to push after committing. |
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
             `ladder.py` is the only one that can refuse correct work;
             `figures.py` is the only one about the page rather than the prose.
  models/    THE ONLY place an external model is reached.
  stages/    one module per stage. Propose, validate, apply atomically.
             `sweep.py` is the only one whose scope is the whole delivered packet.
  engine/    the nested project → paper → section state machine.
  daemons/   the two entry points. Thin: a lock, a loop, a call into engine/.
prompts/     the committed base prompts. Load-bearing non-code artifacts.
service/     systemd units, the launcher, and the deployed configuration.
scripts/     what a person runs by hand: rebuild the .docx of a tree, commit and push.
config/      shell profile fragments, sourced not run. `rebuild` lives here.
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
