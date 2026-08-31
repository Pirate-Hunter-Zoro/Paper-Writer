# Fanfiction-Writer

> **A run is in progress.** See [HANDOFF.md](HANDOFF.md) for what is currently running,
> the sixteen fixes that came out of watching it fail, and what to watch. This README is
> the design; that file is the state of play, and where the two disagree about the
> picture path, that file is newer.

An AI-driven, human-out-of-the-loop **illustrated-novel factory** that runs as a fleet of
`launchd` daemons on a Mac mini. You drop a prompt into a folder — from your phone, if you like,
because the folder is in iCloud. The fleet researches the source universe, plans a series, writes
each book chapter by chapter while continuously critiquing itself for canon fidelity, continuity,
and prose quality, generates matching illustrations, binds the result to `.epub`, and delivers it
back into that same iCloud folder. New prompt, new novel.

It is the third project in the same fleet as **Torrent-Ingest** and **Media-Syncer**, and it
inherits their spine deliberately:

> **The model proposes; a deterministic harness disposes.**

The language model never has the authority to mutate anything. It writes a *proposal* to a file.
Dumb, testable Python validates that proposal against ground truth, applies it atomically,
verifies the result, and only then records success in an append-only journal. Everything below
is in service of that one sentence, because it is the only reason a system built on a confidently
wrong model survives contact with reality.

---

## Table of contents

1. [The core problem and its three hard sub-problems](#the-core-problem-and-its-three-hard-sub-problems)
2. [Architecture: the propose/dispose spine](#architecture-the-proposedispose-spine)
3. [The three-layer memory: canon, series bible, book bible](#the-three-layer-memory-canon-series-bible-book-bible)
4. [The fleet](#the-fleet)
5. [State machines](#state-machines)
6. [The stages, end to end](#the-stages-end-to-end)
7. [Visual consistency](#visual-consistency)
8. [AI usage: one model for the words, a browser for the pictures](#ai-usage-one-model-for-the-words-a-browser-for-the-pictures)
9. [Robustness](#robustness)
10. [State, persistence, and the journal](#state-persistence-and-the-journal)
11. [Configuration and secrets](#configuration-and-secrets)
12. [Code layout: the layers](#code-layout-the-layers)
13. [Running it: the mini vs anywhere else](#running-it-the-mini-vs-anywhere-else)
14. [Failure stories](#failure-stories)
15. [Known limits and honest caveats](#known-limits-and-honest-caveats)

**Operations manual (the part you need on the mini):**

16. [Module map: what is actually built](#module-map-what-is-actually-built)
17. [Prerequisites on the mini](#prerequisites-on-the-mini)
18. [Install and operate the fleet](#install-and-operate-the-fleet)
19. [Configuration reference (every env override)](#configuration-reference-every-env-override)
20. [The model contract (what the fleet calls out to)](#the-model-contract-what-the-fleet-calls-out-to)
21. [Watching a run: logs, journal, decisions](#watching-a-run-logs-journal-decisions)
22. [Troubleshooting and recovery](#troubleshooting-and-recovery)
23. [Deviations and gaps in the current build](#deviations-and-gaps-in-the-current-build)

---

## The core problem and its three hard sub-problems

The goal is a finished book that reads as easily as *Harry Potter and the Deathly Hallows* — a
deep, long novel at a reading ease in the upper-elementary-to-middle-grade band, with a plot as
fulfilling as that book's — but that reads as though it were written by a die-hard human fan of the
source universe. Note what that sentence does *not* contain: a word count. It used to name one, and
the number turned into a target the length gate enforced, which turned into padding. Length is a
floor now (see [The stages](#the-stages-end-to-end)) and the plot is the specification. A previous
attempt at this a year ago collapsed. It collapsed for three specific reasons, and those three
reasons define the entire design:

**Hard problem 1 — novel-length coherence.** A full novel does not fit in a context window, and a
series fits even less. A model asked to "just keep writing" forgets what it established ten
chapters ago: eye colour drifts, a character knows a secret they were never told, a subplot is
abandoned, a promised confrontation never happens. Coherence cannot live in the model's context.
It has to live on disk, as structured state that grows as the book is written and is fed back to
the writer in focused slices.

**Hard problem 2 — canon fidelity.** For *Star Wars: The Old Republic* class stories and the
KOTFE/KOTET expansions, for an Owl House / Gravity Falls / Amphibia / She-Ra crossover, for a
post-Volume-9 RWBY continuation — the lore *matters*. A fan notices instantly when a Force power
works wrong, when a character is in two places at once relative to canon events, when a costume is
from the wrong season. Canon is ground truth, and it has to be gathered from the source wikis and
frozen *before* a word of prose is written, then enforced as a hard constraint.

**Hard problem 3 — visual consistency.** Illustrations have to show the *same* character across
the whole book: the same face, the same hair, the same canon costume. General-purpose image models
have no memory across requests and drift badly on recurring characters. Consistency is the
harness's job, not the image model's.

Every design decision below maps back to one of these three.

---

## Architecture: the propose/dispose spine

Each unit of creative work follows the same four-beat cycle, borrowed directly from
Torrent-Ingest's identify→validate→apply→verify loop:

1. **Propose.** A language model is given a focused prompt and told to write its output to a known
   file path — a chapter draft, a critique verdict, a set of proposed bible updates, an image.
   We read the *file*, never the model's stdout. (Torrent-Ingest learned this the hard way: stdout
   is chatty and unreliable; a file at a known path is a contract.)
2. **Validate.** Deterministic code checks the proposal against ground truth — canon, the current
   bible, the outline, hard numeric gates. This is the gatekeeper. It can reject, and rejection is
   cheap and reversible because nothing has been committed.
3. **Apply.** On a passing proposal, the harness writes the artifact into place *atomically* —
   into a hidden staging directory first, then an atomic rename into its final location — so no
   downstream stage ever observes a half-written chapter or a partial image.
4. **Verify, then journal.** The harness confirms the artifact actually landed, records the new
   state in the append-only journal, and only then advances. Verified state is journaled *before*
   anything irreversible (like deleting a staging copy) happens.

The model has zero authority. The worst a confidently wrong draft can do is get rejected and
retried; it can never corrupt the bible, overwrite a good chapter, or ship a broken book.

---

## The three-layer memory: canon, series bible, book bible

This is the answer to hard problem 1, and it is the heart of the system. Coherence is a
persistent, structured, on-disk memory in three layers. Because it lives on disk and only *slices*
of it are fed into any given prompt, it scales past any context-window limit and across an entire
series.

| Layer | Lifetime | What it holds | Ground-truth role |
|---|---|---|---|
| **Canon** | Per source universe. Frozen after research. | Cited facts scraped from the source wikis: world rules, established characters and their canonical appearance, timeline, factions, powers/magic/technology systems, the events the fic must respect. Every fact carries its source citation. | **Immutable.** Any prose or image that contradicts canon is a hard failure. |
| **Series bible** | Spans every book in the series. Grows as books are written. | Cross-book character arcs; the relationship graph; the **foreshadowing → payoff ledger** (a setup in Book 1 may pay off in Book 3, and the ledger tracks every open promise); the master timeline of invented story events; and the **locked visual reference sheets** for each character, reused in every book so a character looks identical across the whole series. | **Mutable, append-validated.** New facts are merged only if they contradict neither canon nor prior bible. |
| **Book bible** | One book. | The subplots opened and closed within this book, and each chapter's entry/exit state. A working slice of the series bible plus book-local detail. | Derived. Reconstructable from the series bible plus the book's chapters. |

When a chapter is drafted, the writer is not handed the whole memory. It is handed a **focused
digest**: the slice of canon relevant to this chapter's characters and setting, the current
open threads and payoffs due, the ending state of the previous chapter, this chapter's beat sheet,
and the style guide. This mirrors Torrent-Ingest's `build_library_digest`, which never dumps the
whole library at the model but assembles a tight, relevant context for the decision at hand.

A standalone novel is simply a **one-book series**. Building the general (series) case first costs
us nothing on the single-novel path and means "plan a trilogy" and "write one book" are the same
machinery with a different book count.

---

## The fleet

Three `launchd` units, following the two launch shapes the sibling repos established: **self-loopers**
(run at load, kept alive, the process runs its own cycle loop and `launchd` only restarts it if it
dies) and **scheduled one-shots** (run on an interval and exit). Names are provisional and prefixed
`com.mikeyferguson.` to match the fleet.

| Daemon | Shape | Watches | Does |
|---|---|---|---|
| **scribe** (the engine) | Self-looper | The iCloud drop folder and the journal | The core state machine. Advances one unit of work per cycle through research → plan → outline → draft → critique → merge. Research, outlining, drafting, and critique are *stages inside this one engine*, exactly as Torrent-Ingest folds identify/stage/verify into one process. Budget-gated. |
| **illustrator** | Self-looper (parallel worker) | An image work-queue fed by accepted chapters | Renders character reference sheets and scene illustrations through the image API, then runs each image through a vision critic. Runs *concurrently* with drafting so Book 1 can be illustrated while Book 2 is still being written. Low-priority I/O so it never starves the sibling fleets. |
| **binder** | Triggered stage / one-shot | Books that reach the illustrated state | Assembles chapter markdown + images + front matter + cover into a validated `.epub`, then delivers it atomically to the iCloud Books folder. |

A fourth unit, **doctor** — a periodic, never-destructive audit that re-opens finished books to
confirm the epub is valid, images are all present, and no late-detected continuity drift slipped
past the per-chapter gates — is planned but deferred until the core pipeline is proven, the same
way `media_doctor` was a later addition to Torrent-Ingest.

**There is no backup unit, and that is a decision rather than an omission.** `state/series/` is
the only copy of a run's plan, meta plan, outlines, bibles, and accepted chapters. What the fleet
has written and drawn *is* the artifact; crash-resume is the journal's job, not a snapshot's; and
the versioned hourly tarball that used to exist was 380 MB of images out of every 388 MB it
copied, retained 48 deep, for an intended ~18 GB of near-identical duplicates of files nothing
had ever lost. The consequence is real and was accepted deliberately: lose `state/series/` and
the run is gone.

The heavy compute is entirely API-side (Claude for prose and judgment, an image API for
illustrations). The mini only orchestrates and does file I/O — so a base-M mini already running two
other fleets can host this without GPU or memory pressure.

---

## State machines

Three nested levels, three journal key levels: **series → book → chapter**. Books draft
sequentially within a series (Book *N* needs Book *N-1*'s ending world-state). Chapters draft
sequentially within a book. But research, outlining, and illustration **pipeline in parallel** —
which is what makes an overnight novel plausible rather than fantasy.

**Series level:**

```
PROMPT_DROPPED → RESEARCHING → RESEARCHED → ANCHORING → ANCHORED
                                                            │
                                              SERIES_PLANNING → SERIES_PLANNED
                                                            │
                                                  (spawn N book units)
                                                            ↓
                                          BOOKS_IN_PROGRESS → SERIES_COMPLETE
        (any step) ──────────────────────→ STALLED ──(wait, doubling)──→ retry
```

**Book level:**

```
QUEUED → META_PLANNING → META_PLANNED → OUTLINING → OUTLINED → DRAFTING → DRAFTED
       → REVISING → ILLUSTRATING → ILLUSTRATED
                                                                                    ↓
                                              BINDING → BOUND → DELIVERING → DELIVERED → COMPLETED
   (any step) ──────────────────────────────→ STALLED ──(wait, doubling)──→ back to the last step
```

**Chapter level (inside DRAFTING):**

```
PENDING → CH_DRAFTED → CH_EDITING ──clean──→ ACCEPTED → BIBLE_MERGED
                            │  ↑
                            └──┘   editorial passes: find defects AND apply their exact repairs
                            │
                            └──(still carrying defects)──→ ACCEPTED, with them recorded
                                                              ↓
                                                  revisited in the book's REVISING sweep
```

| State | Entered when | Action | Resume behaviour after a crash |
|---|---|---|---|
| RESEARCHING | A new prompt is admitted | Build the cited canon reference | Re-run research; frozen canon files are idempotent to rebuild |
| SERIES_PLANNED | Canon coverage passes | Series plan + seeded bible written and validated | Replay from the journaled plan |
| DRAFTING | A book's outline passes | Chapters advance one at a time through the critique loop | Resume at the first non-ACCEPTED chapter; accepted chapters and their bible merges are already durable |
| ILLUSTRATED | All images vision-checked | Book ready to bind | Idempotent; accepted images are content-addressed |
| DELIVERED | `.epub` atomically copied to iCloud | Journal COMPLETED | Re-deliver is a no-op if the target already matches |
| REVISING | Every chapter accepted | Chapters that shipped holding defects are re-edited against the finished book | Idempotent; each chapter's sweep count is on its record |
| STALLED | A stage raised something the engine could not get past | Unit waits, then retries from its last resumable status | It **is** the resume behaviour; nothing else is needed |

### Nothing is terminal except success

There is no failure state. That is a correction, and the argument it corrects was a real one:
auto-retrying a deterministic failure burns allowance to learn the same thing repeatedly, which is
why the sibling repos refuse to auto-retry a failed identify. The conclusion drawn from it was
wrong, because it treated "retry immediately, forever" as the only alternative to quitting.

`STALLED` is the third option. A unit that hits something it cannot get past records the reason,
waits `STALL_BACKOFF_BASE_SEC`, and tries again — with the wait doubling to a one-hour cap. After a
few attempts the retries are hours apart, which costs nothing and means a provider outage, an
allowance ceiling, and a bug somebody fixes tomorrow all resume by themselves, unattended.

The cost of getting this wrong was paid in full on 2026-08-09. A chapter that would not converge
parked; a parked chapter failed its book; a failed book failed the series; the prompt was filed into
`_inbox/failed/`. Chapter 22 of 37 stopped a novel with **113,000 words of accepted prose already on
disk**, and nothing would move again until a person noticed and dragged a file. Every link in that
chain is gone. A chapter that will not come clean ships holding a recorded list of its defects, and
the book carries on and comes back to it.

The legacy statuses remain in `states.py` so an existing journal still replays, and any unit found
holding one is rewound and resumed rather than honoured.

---

## The stages, end to end

**Input drop.** A prompt is a single markdown file dropped into the iCloud drop folder,
`Books/_inbox/`. It declares the source universe(s), the premise, the intended series length and
per-book target length, tone, art direction, and any must-hit beats — fill a copy of
`PROMPT_TEMPLATE.md`. For a crossover, it names every universe involved. The filename, slugified,
is the job's identity for its whole life, including a retry.

The folder living in iCloud rather than in the repo is what makes the whole system drivable from a
phone: drop a prompt from the iOS Files app, and the finished `.epub` appears in the same `Books/`
folder hours later. It also means the local filesystem is no longer the authority on what is there,
so admission is defensive about it — see [Robustness](#robustness).

### Before the drop: write the book plan

**Every novel starts with a plan document, agreed with the operator, before a prompt is dropped.**
It lives beside that novel's own state, at `state/series/<slug>/<NAME>_PLAN.md`, and the drop prompt
is written *from* it rather than the other way round.

It is deliberately **not** in git. A plan is about one book — its villain, its chapters, its cast —
and belongs with that book's canon and bibles and chapters rather than with the machinery that writes
any book. The repo carries the requirement and the shape; the state directory carries the instance.
`state/series/the-hinge-worlds/` holds a worked example alongside its `REWRITE_PLAN.md` work order.
The usual consequence applies and is accepted: `state/series/` is the only copy of anything in it.

It must cover, in this order: the villain's motive; why the central conflict is believable, stated as
a mechanism rather than an assertion; the arc map with chapter ranges; every chapter's premise **and
its four or five character collisions**; whatever ledgers the book turns on — which pairings fight,
which team-ups are built where and paid off where; and the ending, including who dies and what the
last page costs.

The argument for it is that the first full-length book was written without one, and every defect the
operator found was a planning defect that only became visible as 200,000 words of finished prose.
Chapters 34 to 40 were a briefing, a carving class, a contract negotiation, a harvest visit and a
rehearsal, with the fighting outlined into 43 to 45 — a shape nobody would have approved if they had
been shown it as a list, and which cost a fortnight of run time and about a thousand dollars to
discover as a book. A plan is a page the operator reads in ten minutes and a hundred lines the
machine can be steered by. **The plan is cheap and the book is not.**

Three practical consequences:

- **It is a local markdown file, never a published artifact.** It is working reference that changes
  as the book is discussed, and it must be readable by a session that starts cold.
- **The gates cannot replace it.** They enforce arithmetic — coverage, registers, group sizes — which
  is what stops a plan being *malformed*. Nothing in this repo has an opinion about whether the story
  is worth reading, and nothing should; that is the one judgement that stays with a person.
- **Structure first, collisions second.** Settle the arcs and the chapter premises before writing the
  ~200 interaction promises, because if the structure moves, all of them move with it.

**1 — Research (canon).** Headless Claude, granted web search and fetch, mines the source wikis
(Wookieepedia for SWTOR/KOTFE/KOTET; the Owl House, Gravity Falls, Amphibia, and She-Ra wikis; the
RWBY wiki) and writes a cited canon reference. A coverage critic then checks the canon actually
covers the characters, locations, and events the prompt implies; thin coverage blocks progress
rather than letting the book proceed on a shaky foundation. Canon is then frozen.

**1b — The anchor state.** Canon research collects what is true of a *series*. A story
needs what is true at the *moment it starts*, and those are different documents. So
before anything is planned, `stages/anchoring.py` pins, for every principal the prompt
names: **where** they are, what their life **consists of** now, what they **wear** at
this moment, and what their series' ending **changed** for them. Gated for completeness
— a missing field is a hard rejection — and for coverage against the prompt's own cast
list.

It exists because of one defect. A crossover set after four finales put Dipper Pines in
his pine-tree cap and Wendy Corduroy in her ushanka: how they look for the whole show,
and the exact opposite of how they look afterwards, because they trade hats in the last
episode. Thirty-one researched Gravity Falls facts, ten of them mentioning Wendy or a
hat, and the swap in none of them. Planning wrote the appearance from the show's
default, the continuity editor checked the prose against a canon file that had never
recorded the change, and every illustration drew it. **A gate cannot check a fact nobody
collected.**

The anchor outranks canon everywhere it applies: for anything a finale changed, the
anchor is the present tense and canon is the past. Planning writes appearances from it,
the writer's brief carries the slice for its scene, and the editor's ground truth
carries the whole thing.

**`age` is the one field checked for shape rather than presence, and it must be a plain
number of years.** Not a life stage, not a range, and above all not a comparison to how
old somebody used to be. Every principal of the first book carried an age and not one was
usable: *"Young adult, four years on from the fourteen-year-old who first fell into the
Demon Realm"*, *"the same cohort as Luz"*, *"four years older than the Owl Lady of the
series proper"*. A comparison names a **direction** and never a **distance**, so the
thing compared to becomes the starting point and nothing says where to stop — every
illustration of Luz Noceda in that book is a woman approaching thirty, and she is
eighteen. The arithmetic is done once, here, where it is cheap. `anchoring.parse_age` is
the single definition of what an age is, and the planning gate imports it rather than
writing a second one, so the anchor and the plan cannot disagree. For a being that does
not age, the anchor gives the age it **reads as**: an image model cannot draw "ancient",
it can draw a face.

**2 — Series planning.** From canon and the prompt, the engine produces a series plan — the book
breakdown, each book's premise and entry/exit world-state, and the arc that spans them — and seeds
the series bible with the main cast, the relationship graph, and the specifications for each
character's visual reference sheet. Validated for structural completeness: every book has a defined
role, every arc has a beginning and an end.

**3 — Visual reference sheets.** Before any scene is drawn, the illustrator generates one locked
reference sheet per major character — canonical appearance drawn from canon, each costume variant,
and a fixed colour palette — and vision-checks each against the canon description. Once accepted,
these are frozen and become the anchor for every later illustration.

**3b — The meta plan (per book).** Between planning and outlining sits the document that owns
**which chapter each character scene happens in**: for every chapter, a one-line premise, the cast
present, and the four or five character collisions that fire there.

It exists because the interaction ledger used to live in the series plan and be sized against the
*cast* — `min(cast-1, max(8, cast//2))`, which for a cast of 26 is 13. The model produced 23
entries across 37 chapters, so **fourteen chapters owed nothing to anybody**, and chapter 1 was one
of them: six people at a dinner table and one of them talking. The floor was sized to the cast when
the thing it has to cover is the book.

Three numbers line up, and the alignment is the design: **one scene segment = one setting = one
interaction = one illustration.** A chapter is four or five segments, so it gets four or five
collisions, each with a place to happen and a picture of it. At ~45 chapters that is ~180 entries.

Built ten chapters at a time, because one call will not produce 180 of anything — each call is
shown everything already committed and where the coverage still falls short, and each accepted
chunk is persisted before the next is asked for. A closing arithmetic gate (`gates/interactions.py`)
then checks the whole ledger: everyone in at least six scenes, no group of people used twice, group
sizes genuinely varied, at least 60% of collisions crossing universes, and every pairing of source
worlds given a real share rather than one token scene. Nothing had ever checked the last two, and
chapter 1 was 100% Owl House.

**And every interaction declares what it *does*, not only who is in it.** Each carries a `register` —
one of `physical`, `conflict`, `investigation`, `comic`, `tender` — and the gate enforces a floor on
the physical share three ways: over the whole book, over its front half, and higher over its back
half. No single register may exceed half the ledger in either direction.

The five rules above this one all count people, and a ledger can satisfy every one of them while
being two hundred conversations. That is not a hypothesis. The first full-length book cleared all of
them and delivered forty chapters averaging **two physical verbs each**, with the fighting outlined
into chapters 43 to 45 — because a model optimises for what is measured and nothing measured this.
`physical` means bodies at risk or at work: a fight, a chase, a rescue, an escape, hard work against
a clock. An argument is `conflict` however loud it gets, and letting the two blur is how the floor
gets satisfied on paper by more people shouting in rooms.

Three numbers rather than one, because a single whole-book floor is satisfied by a book that talks
for forty chapters and then fights for eight. The front-half floor is what buys action early; the
back-half floor is what buys escalation.

**4 — Outlining (per book).** The book's slot in the plan is expanded into a chapter list. Each
chapter carries a beat sheet, its entry and exit state, which characters appear, and which
continuity facts it depends on and which it establishes. Validated: no orphaned threads, every
payoff has a prior setup, the timeline advances monotonically.

**The outliner inherits the meta plan and does not get a vote on it.** Its chapter count must
match, its cast must cover what the meta plan placed, and each chapter's delivered interactions are
*stamped* from the meta plan rather than proposed. If both documents could assign a scene, two
documents would own the same fact — the failure recorded three separate times in the stories below,
which always presents as a stubborn model rather than a missing input. What the outliner does own
is where each **progression** lands, and every one must land in exactly one chapter.

**5 — Drafting (per chapter, sequential).** The writer receives the focused digest and writes the
chapter to a staging file. **It is drafted exactly once.** Everything after that is repair. It
marks every change of place or time with a `* * *` break line; the stretches between those marks
are the **scene segments**, and they are the unit for everything per-scene downstream.

Three deterministic gates run first, because they are arithmetic and therefore free:

- **Readability gate.** Flesch / Flesch–Kincaid computed in code and gated to the *Deathly Hallows*
  band. "Make it read like Harry Potter" is measurable and should be measured.
- **Length gate — a floor, and only a floor.** A chapter under ~3,000 words blocks: that is the one
  failure every other gate is blind to, since a short chapter can be word-perfect on canon, clean
  on continuity, and dead centre of the readability band. There is no ceiling and no target.

  There used to be a target, derived from ~198,000 words over 37 chapters, and **it manufactured
  the book's filler.** Asked for 5,351 words in one call the writer returns about 2,681 good ones,
  so the gate fired constantly and sent each chapter back for a continuation pass — and for a model
  that has already told the story it planned to tell, the cheapest available padding is interior
  monologue. A character reflecting on what she just said. The gate worked; it worked toward a
  number that made the prose worse. Do not restore it, and do not justify its removal as a saving:
  continuation was 60 calls and $15.73 of a $1,003 run, 1.6%, measured rather than reasoned about.
  The argument is the prose.
- **Scene-break gate.** A chapter must separate its settings. Zero breaks means the writer never
  marked the chapter up, and every per-scene mechanism silently degrades to treating a whole
  chapter as one moment — which is how five settings in chapter 1 produced illustrations of nowhere
  in particular, stacked at the end. The repair is an ordinary anchored edit, not a rewrite.

**5b — The editorial pass.** Then the editor runs, and this is the part that is unlike most of what
an "AI critic" does. It is handed the chapter and the whole series memory at once, and **every issue
it raises must arrive with its own exact repair** — a `find` copied character-for-character out of
the chapter and the `replace` it becomes. Deterministic code applies them (`stages/patching.py`), an
anchor that matches twice is refused rather than guessed at, and text nobody named is not passed
through a model at all.

It covers six things, in priority order: **canon** (the book must never be wrong about its source
material), **continuity** (it must not contradict the ledger or itself), **voice** (cover the
dialogue tags — can you still tell who is speaking?), **interiority**, **presence**, and **craft**
(where the prose is not wrong but flat, write the better line). Craft edits are marked `polish`,
and they are applied exactly like blocking ones: severity decides whether the chapter is
*finished*, never whether a fix is worth making. A book gets better by accumulating the small ones.

**Interiority and presence are blocking, and they are here because the editor is the only thing in
this pipeline that can enforce a prose rule.** `prompts/draft.md` has said in bold, since the
beginning, that "she felt a wave of grief" is worth nothing. Chapter 1 of the first attempt spent
paragraphs on how its POV character felt about the words coming out of her own mouth. An
instruction is not a mechanism; the editor holds the pen and writes the repair that gets applied
verbatim.

- **Interiority** is a paragraph of the POV character reacting to her own dialogue. The repair is
  **another character's line** — not a trimmed reflection, a person. Those words belong to the
  other people in the room, which is what the reader came for.
- **Presence**: every character the outline places in a chapter must speak or act. Mentioned is not
  present. Six people at a dinner table and one of them talking is the defect, and it was invisible
  before because nothing distinguished "present" from "named". Ensemble scenes have a floor: if the
  outline says the household is at dinner, the household is at dinner and it talks.

Three defects genuinely cannot be a find/replace, and only those go in a separate `structural` list
with an anchor and an instruction: a scene that is summarised where it should be dramatised, a
beat missing outright, a scene with no turn. `stages/surgery.py` replaces exactly that span and
splices it back. Even here the chapter is never re-emitted.

Readability is the interesting case, because it is the one defect that is not *located* anywhere —
Flesch–Kincaid is a function of every sentence, so "too dense" cannot be anchored. It used to be the
one thing that ordered a rewrite. But the score is driven by only two quantities and one of them,
words per sentence, is a property of specific sentences the harness can compute: the fifteen longest
are quoted to the editor verbatim, which turns an un-anchorable gate into fifteen ordinary anchored
edits.

Passes repeat until nothing blocks, bounded by `EDIT_MAX_PASSES` — and a chapter still shedding
defects keeps going to `EDIT_HARD_MAX_PASSES`, because the useful signal in an iterative process is
never the count, it is whether the count is still moving. On acceptance the writer's proposed bible
updates are validated against canon and prior bible, merged, and the chapter is journaled ACCEPTED
*before* the engine advances. Verify before commit.

**A chapter always lands.** If the budget runs out with defects still in it, it is accepted anyway
with them recorded on its journal record and written out in full to `decisions.log`, and the book
moves on.

**5c — The revision sweep (per book).** Once every chapter exists, the chapters that shipped holding
defects are re-edited, one per cycle, against the finished book. That buys three things the
per-chapter loop could not have: the defect may have stopped being one (a dangling thread is often
fine once the chapter that picks it up exists — judging chapter 22 against a book that stops at
chapter 22 is judging it against a cliff edge); the editor can see contradictions between two
chapters, which are invisible from inside either; and it is cheap, because only flagged chapters are
re-read and each gets an anchored repair rather than a redraft.

**6 — Illustration (alongside the writing).** A chapter queues its own illustrations the
moment its prose is committed, and the illustrator daemon locks any missing reference
sheet before drawing a scene that needs one. Drawing *with* the prose rather than after
it buys three things: the image workers stop idling through the whole drafting window;
each accepted picture becomes a reference for the ones after it, so the book's look
converges instead of being a hundred independent guesses; and a bad picture surfaces on
chapter 2 rather than after the last chapter lands — the difference between fixing the
recipe and re-rendering a book.

**Art direction runs per scene segment, and a picture is printed where its scene ends.** The
art director is handed one segment's text rather than the whole chapter, so the moment it picks is
guaranteed to be in that setting; the image slot number *is* the segment number; and the binder
splices each figure at the end of that stretch of prose. Before this, every figure was concatenated
after the chapter's last paragraph — the only placement the binder had ever had — so a reader met
the dinner scene twelve pages after the dinner, and the two moments chosen from a five-setting
chapter were whichever two read most dramatically out of context.

How many pictures a chapter gets is therefore **how many times it changes scene**, bounded by a cap
that is *derived* rather than configured: remaining picture budget ÷ chapters not yet queued, less
what must be reserved for reference sheets and the cover, times this series' own observed keep rate
(the vendor bills for a render the critic rejects, so a cap computed on keepers alone overruns by
exactly the reject rate). Freeing the chapter count is what forces that — chapter count used to
multiply the picture bill and now has to divide it. `IMAGES_PER_CHAPTER` survives only as a ceiling.

A chapter that delivers a character's escalation **owes a picture of it**, and gets an extra slot so
a tight budget cannot squeeze the mandatory one out. Each render reuses the locked character sheets
so recurring characters stay identical, lands as a file, and is vision-checked against the sheets
and the scene description before acceptance.

**The picture count is a property of the prose, so a raised ceiling has to reach chapters that are
already written.** Art direction is idempotent per *segment*, not per chapter: a chapter is short by
exactly the segments nobody has chosen a moment for, and those are directed and only those. The
illustrator daemon owns that top-up and does one chapter a cycle. Ownership is single on purpose —
the queue is an append-only file with no lock, so the scribe writes chapters that have no entries and
the illustrator writes the ones that have too few, and the two can never append to the same chapter.

### No picture is given up on

The prose half of this pipeline has no failure state, and the picture half now has none either. A
slot is resolved by an image existing, and by nothing else. A render that will not come out is
**parked**: it records the rung it reached, waits `IMAGE_RETRY_BACKOFF_BASE_SEC` doubling to an hour,
and comes back — the identical shape as `STALLED`, and for the identical reason. A rate limit still
defers rather than failing, and writing never waits on pictures.

What makes "retry forever" *terminate* rather than spin is that each retry asks for **less**. The
rung is stored with the slot, so a restart cannot reset it back to the elaborate composition that has
already been refused three times:

| Rung | The request |
|---|---|
| 0 | the moment as the art director framed it, full cast |
| 1 | its opening clause, two characters |
| 2 | one character, a single clear portrait |
| 3 | **the place, empty** — no people at all, drawn from the locked location |
| 4 | the same, cut to one clause |

Rung 3 is the reason this converges. Every bottom-of-the-ladder failure this project has actually
seen is an identity failure or a crowd failure — the wrong face, two characters merged, one
character wearing another's hat — and a picture of the room they are in has neither. It is a real
illustration of a real place in the book. Dropping the cast list is not sufficient on its own,
because the staging line is still a sentence about people doing things and a model handed that draws
them; the instruction countermands the description explicitly, and the vision critic is told there
are no named characters so that generator and judge are not reading different documents.

Two consequences worth stating plainly, because they are the cost of the rule:

- **A book does not bind until every slot holds a picture.** ILLUSTRATED means what it says. A book
  that cannot draw waits in ILLUSTRATING rather than shipping around the gap, because a delivered
  book with holes in it is the one outcome nobody can undo, and waiting only costs time.
- **The render ceiling costs time, not pictures.** Hitting `FANFIC_IMAGE_RENDER_BUDGET` used to skip the
  slot, which quietly made a low ceiling a quality setting nobody had agreed to. It now holds the
  book with every slot still queued; raising it resumes the run by itself, with no re-drop and
  nothing lost. Set it where a whole book fits underneath.

**7 — Binding.** Deterministic assembly of chapter markdown, accepted images, front matter, and a
generated cover into an `.epub`. The epub is validated — it opens, the mimetype is right, the OPF
resolves, every manifest item is embedded, every spine item exists — before it is considered bound.

The cover is the one page that is not reflowable text and gets its own layout: no page margin, the
art absolutely positioned and covering the full page, and **the book's title typeset over it** in
real type against a gradient scrim, stepping down a size as the title gets longer. The title is
HTML rather than part of the generated picture on purpose — image models cannot letter, which is
why every image prompt in this project ends by forbidding it, so the art stays wordless and the
typography is done where it can actually be typography.

**8 — Delivery.** The finished `.epub` is copied into `~/Library/Mobile Documents/com~apple~CloudDocs/Books`
using the stage-then-atomic-rename discipline, so iCloud never begins syncing a partial file.
Sub-organisation inside `Books/` (by fandom, by series, numbered within a series) is left to the
agent. Delivery is journaled COMPLETED.

---

## Visual consistency

This is the answer to hard problem 3, and it is worth stating plainly because it is where the last
attempt died. The image model has **no memory across requests** and drifts on recurring characters.
We do not fight that by hoping; we engineer around it:

- **Draw the sheet from the show's own art, not from a paragraph about it.** `stages/refart.py`
  fetches the character's real pictures off their source wiki and hands them to the image model as
  reference input. Prose gets identity roughly right and proportion consistently wrong — there is no
  wording for "this exact jaw", and the more words you spend the more the model averages.
- **Lock a reference sheet per character, once.** Generated from that art plus the canon appearance,
  then frozen in the series bible and reused for the entire series.
- **Feed the sheet back on every render.** Scene illustrations are produced with the relevant
  character sheets supplied as inputs, and a fixed prompt template (identical style block and
  constraint block every time). Since the move to the browser these are *uploaded to the chat as
  real attachments* rather than passed as inline API parts — same mechanism, same effect, and the
  driver treats a failed attach as a hard error rather than quietly rendering without them, because
  a render that lost its references looks fine and is wrong.
- **The foreground gets the references; the background gets its sheet.** A model divides one budget
  of attention across its references, so fidelity per face falls as their number rises — a
  four-character scene sending twelve pictures makes all four faces worse. `IMAGE_REFERENCE_CHARACTERS`
  (2) is how many get the full set. The art director is already required to compose with one or two
  people in front and the rest staged behind; this is the renderer agreeing with it.
- **Where a reference exists, the words stop describing the face.** A scene prompt carries each
  character's age and this chapter's costume, and *not* their appearance paragraph. Prose and pictures
  always disagree — there is no wording for a particular jaw — and a model handed both averages them,
  so a description sitting on top of a photograph erodes the face rather than reinforcing it. That is
  this project's own argument for fetching real art, applied at the point it was being contradicted six
  times a chapter. Age survives the trim because it is the one identity fact a reference can be
  actively wrong about: source art is drawn from a whole series, and this book starts after its
  epilogue. The exact prompt for every image is written to `image_prompts.md` beside the book, so the
  mechanism is reviewable rather than a black box.
- **Take the style from the job, not from global config.** The style block is read from the prompt's
  `## Illustrations` section (`jobspec.art_direction`), falling back to `FANFIC_IMAGE_STYLE`. A Star
  Wars novelization asking for painterly key art must not be drawn as cel-shaded anime merely because
  that was the previous fic's house style.
- **Vision-critique every image, against the same pictures the generator got.** The critic is handed
  the render *and the reference art and locked sheet as files*, and told to open them and compare. It
  rejects and regenerates on a bounded loop, same propose/critique/dispose contract as the prose.

  Giving it the pictures is the whole of it, and it was missing. The critic used to receive the render
  and a prose paragraph, so it was answering "is this a heavyset young man in a green shirt with a
  question mark on it" — which a moustached stranger in a headlamp cap satisfies completely. It passed
  that picture correctly, against the document it had. The signature is what survived: every character
  who came out wrong was an ordinary-looking human (Soos, Anne, Perfuma, Pacifica) and every one who
  came out right had an unmistakable silhouette (Bow's crop top, Dipper's ushanka, Raine's green hair).
  **Prose checks a costume. Only a picture checks a face.** This is the same generator/judge document
  mismatch recorded three times elsewhere in this README, one layer further down, and it is why the
  vision role is not one-shot: it has `Read` and twenty turns so it can open every reference.

Consistency is thus a property the harness *enforces*, never a property we assume the model has.

### Fetching the reference art: two rules, both learned the hard way

**It is asked per character, at the moment their sheet is drawn.** Not swept over the bible in one
pass, because a one-pass sweep is correct exactly once: the cast of a crossover grows chapter by
chapter as the bible merges new people in, so everybody introduced after the sweep is stranded with
no source art and *nothing looks wrong* — a sheet drawn from prose alone is still a `.png` of a
character. The lazy fetch is what makes "which characters have anchors" a question that cannot drift
out of date, however late somebody joins the book.

**A hit has to earn the character, because a wiki search never returns nothing.** This is the
dangerous half. Asked for "Waddles", the Owl House wiki answers `Dee Bradley Baker` — the voice
actor's page. Asked for "Perfuma" it answers `Luz Noceda`. Take the top hit and a pig is anchored to
a photograph of a man and a flower princess is anchored to Luz, silently, and the pictures simply
come out wrong in a way that reads as the image model being bad at its job. So:

- **Each character is looked up on *their own* wiki first**, from the `origin` the bible records.
  Walking the series' universes in order and keeping whichever answered first meant, for a four-way
  crossover, the same wiki for every character in the book.
- **An exact title wins; otherwise a hit must share a real word with the name**; a `Waddles/Gallery`
  subpage resolves to its article, where the infobox portrait is. Anything else is **None**, and no
  art is unambiguously better than another show's art — without it the sheet falls back to the locked
  prose description, which is merely imprecise rather than actively depicting somebody else. This is
  also what protects the *originals*: an invented antagonist has no page, and a matcher that guesses
  would anchor them to whoever it found.
- **A confirmed miss is recorded** (`.no-source-art` in the character's refart directory) so four
  wikis are not re-searched every cycle for an answer that will not change. A *failed* lookup records
  nothing, because "the wikis do not have them" and "the network was down" must not be the same state.

**Sheets carry their provenance, and a blind one is repaired.** Each locked sheet gets a `.sources`
sidecar saying how many real pictures it was drawn from, because "the sheet exists" was being read as
"the anchor is good" for twenty-three of this book's cast. When art turns up for a sheet that was
drawn without any, the sheet is discarded and re-locked — *and every rendered picture that sheet
anchored is discarded with it*, because repairing the anchor without repairing what it anchored
leaves the book exactly as wrong. Only pictures containing that character, so a book's good art is
never thrown away to fix one face. The pass is one-way and self-limiting: art already on disk when a
sheet was drawn means the sheet used it, provenance is recorded either way, and a recorded sheet is
never examined again.

### The one place the anchor deliberately moves

Characters get stronger across a book, and some of those changes are visible. A progression that
alters how somebody looks would otherwise invalidate their locked sheet for every chapter after it:
draw the mantle in chapter 3 and it is a continuity error, omit it in chapter 40 and so is that.

So an appearance-changing progression adds a **costume variant tagged with the chapter it starts
in**, and scene rendering selects the variant by chapter number. The plan declares the change; only
the outliner knows which chapter it lands in, so the variant is stamped at outline time and read at
render time by `illustration.costume_for_chapter`. A plain string is the base look, current from
page one, which is what every bible already holds and what a reference sheet is always drawn from —
a sheet exists to settle a face, not to catalogue a wardrobe.

This is the only case where the visual anchor is not constant across a book, and it is worth
knowing about before debugging a picture: "wrong costume" may mean the chapter number reaching the
render is wrong rather than the design being wrong.

---

## AI usage: one model for the words, a browser for the pictures

Two backends, and in both cases the model writes its result to a file the harness reads — never
parsed stdout:

- **Claude Opus, through the `claude` CLI**, run as a subprocess: *all* prose and *all* judgment.
  Research, anchoring, series planning, outlining, drafting, continuation, the editorial pass,
  scene surgery, bible merging, art direction, and vision critique. Authenticated through its own
  logged-in session on the mini — there is no API key for text and never has been.
- **Gemini, through a real signed-in browser session**: all image generation.
  `tools/gemini_art.js` drives Chrome over the DevTools protocol on a profile a human signed in to
  once. There is **no API key anywhere in this project**, and pictures cost nothing.

### Why there are no model tiers

There used to be two. Sonnet drafted, Opus judged, and a per-role table could send any individual
role somewhere else again — including to a different vendor entirely, behind a five-provider
registry with capability declarations and a price table spanning eleven models.

All of it is gone, and each piece of it was removed for a reason that had already cost something:

- **Two tiers meant two suspects for every quality problem.** Prose quality is the entire product
  here. When a chapter came out flat, the first question was always "was that the tier?", and the
  answer was always another experiment rather than a fix. Worse, the tiers kept being wrong in
  ways that were only discovered by reading the output: `art_direction` was moved to the cheap
  tier as an obvious saving, spent a run choosing moments no image model could render — "three
  girls with glowing scars facing three strangers" — and had to be moved back after every one of
  those slots was rejected and skipped. The saving bought empty pages.
- **The swappability was theatre.** Research needs live web access and only the CLI has it, so the
  "provider-agnostic" pipeline had one role that could never move. Every prompt in `prompts/` is
  written against Claude's habits. No alternate backend was ever run on a real book.
- **The generic contract layer existed for providers that no longer exist.** An HTTP completion
  endpoint has no filesystem, so the delivery instruction had to differ by transport, and handing
  the wrong one to either side failed every call it made.

One model, one prompt style, one set of habits to write against. The knob that actually moves the
number is below, and it is not a model.

### Why the picture API was deleted rather than kept as a fallback

The original build called the Gemini Images API over HTTPS with a billed key. It worked, in the
narrow sense that a PNG came back for every request. The pictures were the weakest thing in the
finished books: samey between renders, flat, and often enough distracting enough that a chapter
read better with the slot empty. Judged against the only question that matters — *does this
picture make the book better* — the answer was no often enough that the money was buying a defect.

The same model, asked the same thing at gemini.google.com, does not have that problem. That is not
a prompt difference and not a model difference; it is the difference between a bare endpoint and
the product built around it.

So the fleet drives the product. What that buys beyond the art itself:

- **No credential on disk.** No key file, no `GEMINI_API_KEY`, nothing to leak and nothing to
  rotate. The credential is a cookie jar in a directory owned by the person whose account it is.
- **No bill.** Pictures were the only line item this fleet genuinely paid for, which is why the
  picture budget used to be denominated in dollars. It counts renders now: a runaway stop, not a
  wallet.

What it costs is honesty about two new failures, both visible and both recoverable. A browser
session expires, and the fix is one run of `scripts/gemini-login.sh`; the illustration stage checks
for it **before** spending an attempt and holds the book with its queue intact rather than
discovering it once per slot per cycle. And Google reships this app constantly, so every selector
in the driver is a guess about somebody else's markup — which is why a failed render dumps a
screenshot and the page text to `state/image-diagnostics/`, and why `FANFIC_IMAGE_HEADFUL=1` shows
you the render happening in a visible window.

One trap is worth naming because it was walked into during bring-up: **a composer is not proof of a
session.** A signed-out visitor gets a working Gemini chat on a cut-down model that answers text and
politely declines every picture — "I can try to find an image like that for you, but can't create it
right now". That is indistinguishable from a content refusal, so the retry ladder would have burned
every rung on it and quietly taken the book text-only. The driver checks for the *account*, not the
composer, and re-checks after any refusal.

### One-shot roles: the largest lever in the project

How a stage talks to its model matters more than which model it is — which is the whole reason
losing the ability to change models cost this project nothing. An agentic CLI works in **turns**,
and every turn re-sends the entire conversation, including every prior tool *result*.
So a writer told "the draft is at this path, the bible is at that one, go and read them" pays for
those files again on every turn that follows. Measured on the first real novel: a chapter draft
consumed **~227,000 input tokens** to produce ~7,200 of prose, and a critique **~363,000** to
produce ~4,000 of verdict.

None of that was information the harness did not already have in memory. So every role except
research now declares `oneshot`: its whole input is **quoted inline** in the prompt, it is granted
`Write` and nothing else, and it is told to read nothing and produce the artifact in exactly one
call. Same model, same artifacts, roughly a tenth of the input tokens.

This is the largest lever left in the project by a wide margin, and it is bigger than any vendor
swap ever was. `python3 -m fanfic.cost --presets` prints it against the alternatives.

Research is the sole exception, and necessarily: its entire job is to go and find input that is not
on disk yet. It stays agentic, with web tools and an 80-turn budget.

Two consequences worth stating, because they are what makes this safe rather than merely cheap:

- The propose/dispose spine is untouched. It is still one artifact at one known path, still
  validated by deterministic code before anything is committed. Only the *route the bytes take*
  changed.
- The judge sees **more**, not less. Because quoting the memory is now cheap, the critique is handed
  the whole cast, the full foreshadowing ledger, every invented fact, and the timeline — where
  before it had to spend turns fetching whatever it thought to look for.

All model output is treated as untrusted: every proposed bible fact is validated against canon
before it is allowed to persist, every image is vision-checked, and every stage fails soft.

### Voices are locked like faces are

The series bible pins each character's `voice` — how they actually talk — beside their locked
appearance, and the planning gate rejects a plan that omits one. It is the prose counterpart of a
reference sheet, and it exists for the identical reason: identity the model has no memory of drifts
unless it is written down.

In a crossover it is load-bearing rather than nice. Four casts written by four different writers'
rooms have four different comic rhythms and four different registers of sincerity; one model
writing all of them flattens them into a single clever narrator within a few chapters, each line
individually fine. The writer's brief carries the voice line for everyone in the scene, and the
editor is told to cover the dialogue tags and check whether it can still tell who is speaking —
and, where it cannot, to write the line back into that character's mouth rather than filing a note
about it.

---

## Robustness

The patterns are lifted wholesale from the two sibling repos, because they were paid for in real
outages:

- **Quiet hours — the mechanism, currently switched OFF.** The mini shares **one** `claude` session
  with the person who owns it, so a fleet drafting novels through the working day is spending capacity
  that person needs. Enabled, the engine and the illustrator start no new work between 09:00 and
  17:00 US Central, Monday to Friday.

  `launchd/fleet.env` sets `FANFIC_QUIET_HOURS=0`, deliberately: a full-length book is days of run
  time, and blanking out the weekday working hours leaves 9 run-hours a weekday against 17 at the
  weekend. The owner would rather have the book sooner and feel the contention. The cost is paid by a
  person rather than by the fleet — while a run is in progress the owner's own use of the same seat
  is slower, and an allowance ceiling hit mid-afternoon is one they hit too. Set it to 1 to get the
  working day back.

  It is a pause, never a failure: nothing parks, no status changes, admission and the status file keep working, and
  the run resumes by itself afterwards. The window gates the *start* of work, not work already
  running — a call twenty minutes into drafting is not killed at 09:00, because throwing it away
  would not give back capacity already spent. Central Time is derived from **UTC**, never from the
  host's local clock, so a VPN or a mis-set timezone cannot move the window; `fanfic/clock.py` prefers
  the tz database and falls back to explicit US DST arithmetic if it is unavailable.
- **A capacity ceiling is a wait, not a failure.** Any allowance message from the model backend —
  session cap, five-hour cap, weekly cap, monthly spend cap — raises `QuotaExceeded` on first sight
  and the engine defers, re-checking every `MODEL_QUOTA_BACKOFF_SEC` **with no attempt limit**. A
  rejected call costs about two seconds, so re-checking every five minutes recovers a session cap
  almost as soon as it resets and costs nothing across a multi-day wait for an administrator.
- **Peak-pricing windows.** Some vendors charge more at certain hours — DeepSeek doubles **all billing
  items** during 01:00–04:00 and 06:00–10:00 UTC daily. Paying twice for the same tokens is avoidable by
  not starting work then, so the fleet doesn't. These are kept separate from quiet hours rather than
  merged into one list, because they are different in kind: quiet hours protect the *owner's* shared
  allowance on a weekday schedule in the owner's timezone, while a peak window protects the *wallet*,
  applies every day, is defined in UTC by the vendor, and **only matters while that vendor is
  configured**. A merged list would keep blocking work after you had switched away from the provider
  that had the surcharge. `clock.blackout` composes both and reports which one is in force, and the
  status file says `⏸ Paused — peak pricing` so a quiet stretch reads as intent rather than a hang.
  With DeepSeek plus quiet hours that would leave **9 run-hours a weekday and 17 at the weekend** —
  worth knowing before wondering why an overnight run is not overnight. Both are switched off on this
  machine, so the fleet currently runs around the clock.
- **Budget gating.** The engine checks remaining API budget before starting a unit of work and
  advances one unit per cycle, so a runaway can never silently drain the enterprise spend. If
  budget is exhausted, the engine idles rather than failing.
- **Bounded retries, transient only.** Transient failures (a dropped web fetch, a timed-out render)
  retry with backoff up to a cap. A deterministic failure does not loop and does not quit either: it
  stalls, and the wait doubles. The two kinds never share a counter — a chapter's editorial budget is
  spent only on passes an editor actually rendered, so a flaky subprocess cannot starve the chapter
  of its repairs.
- **Verify before commit; journal the verified state first.** Nothing irreversible happens until
  the artifact is confirmed present and its success is recorded.
- **Atomic staging everywhere.** Chapters, images, epubs, and the final iCloud delivery are all
  written into a hidden staging path and atomically renamed into place, so no watcher — including
  iCloud's own sync — ever sees partial state.
- **Append-only journal, crash-resume by replay.** Keyed by series/book/chapter id; every stage
  action is idempotent, so a mid-run crash resumes at the first incomplete unit with no double work
  and no lost progress.
- **Circuit breakers that slow work down, never stop it.** A chapter whose defect count has stopped
  falling does not get the rest of its budget — another identical pass buys a fresh set of opinions,
  not a better book — so it ships with what is left recorded, and the sweep comes back to it. Canon
  coverage is the one gate that blocks *before* the work: thin canon stalls the series rather than
  letting a whole book be drafted on a shaky foundation, and the stall retries, so re-running
  research later is automatic rather than a gesture somebody has to make.
- **Single-instance lock** per daemon, and a **load/concurrency gate** so this fleet yields to
  Torrent-Ingest and Media-Syncer on the shared mini.
- **Stale-unit recovery at startup.** A unit found in an in-progress status when the engine takes
  the lock was abandoned — killed, crashed, power-cut, or restarted by launchd — because the only
  process that could have been working it is the one holding the lock. Those statuses have no
  handler, so left alone the unit would sit there forever: not terminal, so nothing reports it; not
  resumable, so nothing advances it; not `FAILED`, so a re-drop cannot revive it. `recover_stale`
  rewinds each one to its last resumable status before the first cycle, which is what makes
  restarting the fleet mid-stage cost that stage rather than the job.
- **A synced drop folder is treated as untrusted.** The drop folder is in iCloud, so a job can be
  *evicted* (contents replaced by a `.foo.md.icloud` stub, invisible to a `*.md` glob) or observed
  *mid-arrival*. Admission requests evicted files back via `brctl` and refuses to read a prompt
  until it is non-empty and unchanged for `INBOX_SETTLE_SEC`. Admitting a truncated prompt is worse
  than not seeing it: canon would be frozen against half a brief, and the job would look fine.

---

## State, persistence, and the journal

No relational database — JSONL and structured files on disk, the same choice the sibling repos
made. Everything runtime-generated lives under a gitignored `state/` tree:

- The **journal** — an append-only, last-writer-wins record of every unit's state transitions; the
  single source of truth for crash-resume.
- The **canon** store — per universe, cited, frozen after research.
- The **series tree** — per series: the series bible, each book's bible, the accepted chapter
  drafts, the locked character sheets, and the accepted images.
- **Staging** — hidden `.staging/` directories beside each destination, which never contain committed
  state, and a `tmp/` tree holding proposals (drafts, verdicts, plans) before they are validated.
- The **image queue** — an append-only JSONL of scene entries, drained idempotently by re-reading it
  rather than tracking a cursor, so the engine and the illustrator daemon can both work it without
  coordinating.
- A human-readable **decisions log** — every model call, verdict, revive, and failure reason, for
  audit — mirroring Torrent-Ingest's `decisions.log`.

None of it is backed up anywhere. `state/series/` is the only copy — see the note under
[The fleet](#the-fleet) for why, and for what that costs if the disk goes.

---

## Configuration and secrets

- **One config module, `fanfic/config.py`,** holds every tunable — paths, the model, the readability
  band, revision and retry caps, images-per-chapter, budget thresholds, the iCloud target — the way
  both sibling repos centralise config. It contains no logic and no I/O, and nearly every value is
  env-overridable so `launchd/fleet.env` can change behaviour without a code edit.
- **There are no secrets, and that is now literally true.** It used to be *nearly* true: prose and
  judgment needed none, because `claude` authenticates through its own logged-in session, but the
  image API key was a real credential in a real file. Deleting the image API deleted the last one.
  What replaces it is a **Chrome profile directory** that a human signed in to once — a cookie jar,
  owned by the person whose account it is, that this repo knows the path of and nothing else. There
  is nothing to leak, nothing to rotate, and nothing that could be committed by accident.

  The feature still stays **inert until that session exists** (the Media-Syncer pattern), reporting
  precisely what is missing and naming the script that fixes it, rather than failing obscurely. That
  check now runs *before* the illustration stage spends a single render attempt.

  Nothing sensitive goes in a plist or in git, explicitly correcting the weakness called out in
  Torrent-Ingest's own README, where a Jellyfin API key sits hardcoded in plist XML.
- **A test enforces it.** `test_providers.NoCredentialsAnywhere` fails the build if any module reads
  an API key out of the environment, or if a `*_KEY_FILE` path reappears in config. A key file
  creeps back in one convenience at a time, and nothing else would notice.

---

## Code layout: the layers

The code is one package, `fanfic/`, layered so the propose/dispose spine is enforced by the import
graph rather than by good intentions. **Every layer may import the ones above it and never the ones
below.**

```
Fanfiction-Writer/
├── PROMPT_TEMPLATE.md          fill a copy, drop it in inbox/
├── prompts/                    the engineered base prompts — the load-bearing non-code artifacts
│                            (the drop folder is NOT here — it is in iCloud, see below)
├── launchd/                    3 plists + one shared run.sh + startup.sh installer + fleet.env
├── tools/                      gemini_art.js — the headless-Chrome picture driver (Node, no deps)
├── scripts/                    gemini-login.sh (sign the profile in) and save-and-push.sh
├── .githooks/                  commit-msg — strips assistant attribution from every commit
├── tests/                      stdlib unittest; support.py owns the fixtures and the seam stubs
├── state/                      gitignored runtime tree
└── fanfic/
    ├── config.py               every tunable. No logic, no I/O.
    ├── paths.py                every path in the state tree. Pure computation.
    ├── states.py               the state vocabulary of the whole machine, on one screen.
    ├── errors.py               the three failure classes (revise / defer / park).
    ├── jobspec.py              parsing the dropped prompt file.
    ├── status.py               the phone-readable status document (pure render).
    ├── infra/                  durable plumbing. Knows nothing about novels.
    │     log, journal, storage, locks, budget, icloud
    ├── memory/                 the three-layer memory.
    │     bible (schemas + the merge gatekeeper), digest (the slice each model
    │     is shown), store (loading the three layers off disk)
    ├── gates/                  the deterministic validators. No models, no I/O.
    │     coverage, structure, interactions, readability, length, segments
    ├── models/                 THE ONLY layer that reaches an external model.
    │     prompts (assembly), text (Claude via subprocess), images (browser)
    ├── stages/                 one module per pipeline stage.
    │     research, anchoring, planning, metaplan, outlining, drafting,
    │     editing, surgery, patching, bible_update, refart, illustration,
    │     binding, delivery
    ├── engine/                 the nested state machine.
    │     admission, series, book, chapter, revising, illustrating,
    │     stalling, cycle
    └── daemons/                the three launchd entry points. Thin by design.
          scribe, illustrator, binder
```

Three properties fall out of that ordering, and they are the reason for it:

- **`models/` is the only layer that can be wrong in an interesting way**, and nothing in it can
  mutate committed state. It returns proposals; `gates/` and `memory/` decide; `infra/storage`
  applies atomically. That is the spine, made structural.
- **`gates/` and `memory/` import no model and no network**, so the rules a confidently wrong model
  is not allowed to argue past are all testable with fixtures and arithmetic.
- **A stage never writes the journal** and never decides what state a unit moves to. That belongs to
  `engine/`, which is what keeps a stage a function you can call from a test.

Nothing outside the standard library is imported anywhere, so the fleet runs under a bare system
Python. A dependency that has to be installed is a dependency that will be missing at 2 a.m. The
same rule holds for the Node half: `tools/gemini_art.js` uses Node's built-in `WebSocket` and
nothing from npm, so there is no `node_modules`, no lockfile, and nothing to install on the mini
beyond Chrome and Node themselves.

---

## Running it: the mini vs anywhere else

The repo is **developed and tested anywhere** but **only runs in production on the Mac mini**, the
only host with the logged-in `claude` session, `launchd`, and the iCloud Books folder. That split is
deliberate and matches how the sibling repos treat the mini as the sole production host.

The entire deterministic half is exercisable off the mini: the state machine and every transition,
the journal and crash-resume replay, all three gates, the bible merge, atomic staging, the epub build
and its validator, and delivery — with fixtures in place of live model calls. This is not a
nice-to-have; it is why the layering exists. `gates/` and `memory/` import no model and no network,
`models/` is nine named seams, and `tests/support.py` replaces all nine at once, so the half of the
system that can be proven correct *is* proven correct before it ever touches an API.

What cannot be exercised elsewhere: the live `launchd` fleet, the logged-in `claude` session, real
image generation, and iCloud delivery. Those are validated on the mini, and the first live run of any
of them should be treated as bring-up rather than a smoke test.

---

## Failure stories

Following the sibling repos' signature convention: every hard-won lesson gets recorded here, dated,
as a symptom → cause → fix entry, so a design decision is never mistaken for an arbitrary one. This
section is seeded with the failures we are designing *against* from day one, and will grow with
real incidents.

- **The year-ago collapse (visual drift + continuity rot).** The prior attempt let the model hold
  the whole story in its head and let the image model invent each character afresh. Prevention:
  the three-layer on-disk memory (hard problem 1) and harness-enforced reference sheets (hard
  problem 3).
- **Anticipated: stdout parsing.** Torrent-Ingest and Media-Syncer both suffered from trusting a
  CLI's stdout. Prevention: models write to a known file; we read the file.
- **Anticipated: a whole book drafted on thin canon.** A fic that violates lore is worse than no
  fic. Prevention: canon coverage is gated before drafting begins.

- **2026-08-04 — `codex image` does not exist.** *Symptom:* every image call failed on first
  contact. *Cause:* the design assumed `codex` was an image CLI ("gpt-image-2 via `$imagegen`"). It
  is OpenAI's *coding agent*: no `image` subcommand, no `imagegen` binary, and its session auth
  cannot reach the Images API. *Fix:* image generation goes straight to an image API over HTTPS
  (`models/images.py`, stdlib only); vision critique stayed on `claude`, which can read an image
  file. `codex` is no longer used anywhere.

- **2026-08-04 — a prose paragraph became eight universes.** *Symptom:* one job produced eight junk
  canon directories and eight research calls. *Cause:* the universe parser split the whole "Source
  universe(s)" section on commas, newlines, and " and ", so a descriptive paragraph shredded into
  fragments. *Fix:* `jobspec.universes` reads only the first non-empty line and splits on `+` and
  `/` only — crossover connectors, not prose punctuation. Six tests pin it.

- **2026-08-04 — a retryable blip parked a whole novel.** *Symptom:* the SWTOR Jedi Knight run died
  ten minutes into research and went terminally `FAILED`: `claude exited 1: API Error: Connection
  closed mid-response`. *Cause:* transient-versus-deterministic classification is a substring match
  against `TRANSIENT_SIGNATURES`, and that list had `connection reset`, `connection error`, and
  `stream closed` but not `connection closed`. A mid-stream network blip was therefore treated as a
  confidently-wrong proposal and never retried. *Fix:* the list now covers `connection closed`,
  `connection aborted`, `mid-response`, `server disconnected`, and `eof occurred`. The lesson is
  the general one — that list is a denylist of network reality, and it will need adding to again.

- **2026-08-04 — the coverage gate was being fed junk it could never satisfy.** *Symptom:* the SWTOR
  prompt yielded 44 "implied entities", among them `This`, `Stay`, `Grim`, `Act`, and — worse —
  `Jedi\nOrder` with an embedded newline from a hard-wrapped line. *Cause:* the name pattern matched
  any run of capitalised words, so prose that opened a sentence or a bold run became an entity, and
  `\s+` between words happily spanned a line break. Every one of those is a denominator term in the
  85% canon-coverage floor, and an entity no fact can ever match is a free penalty — enough of them
  and a perfectly good job parks at research. *Fix:* whitespace inside a name is collapsed, and a
  lone capitalised word opening a sentence, line, or bold run is dropped while a multi-word span in
  the same position is kept. 44 → 38 entities, all real names. The real prompt is now a regression
  fixture, because guessing at this cost a run once.

- **2026-08-04 — the art style was global when it needed to be per job.** *Symptom:* a SWTOR
  novelization was about to be illustrated as cel-shaded anime. *Cause:* `config.IMAGE_STYLE` was
  stamped on every image prompt unconditionally, and its default is an anime block; the config
  comment promised "a fic may override via its prompt's art-direction", but nothing read the prompt.
  The previous hand-launched run papered over it with a `FANFIC_IMAGE_STYLE` env override, which
  bakes one job's art direction into a daemon. *Fix:* `jobspec.art_direction` reads the prompt's
  `## Illustrations` section and the engine threads it through every render; config is the fallback.

- **2026-08-04 — the coverage gate rejected good canon over phrasing.** *Symptom:* the SWTOR run
  parked at research with `canon coverage 84% below 85% floor`, listing `Sergeant Rusk`, `Hutt
  Cartel`, `Old Republic`, `Sith Emperor Vitiate`, `Act`, and `Rise` as missing — from a canon of
  **207 cited facts**. *Cause:* two compounding errors. The gate matched each implied entity as an
  exact phrase, so canon that correctly wrote "Rusk", "Vitiate", and "Republic" did not count as
  covering "Sergeant Rusk", "Sith Emperor Vitiate", and "Old Republic" — it penalised research for
  using canonical naming. And `Act` (from "the Knight's Act 3") and `Rise` (from "Rise of the Hutt
  Cartel") were junk entities knowingly left in the list on the reasoning that a couple would fit
  inside the gate's slack; they were a third of the shortfall. *Fix:* an entity now also counts as
  covered when every one of its identifying words — titles and short qualifiers stripped — appears
  somewhere in canon, and narrative-structure words are stopwords. The same canon now scores 97.2%,
  with `Hutt Cartel` correctly still missing, because canon never says "Cartel". The floor was **not**
  lowered: junk in the denominator is not free, and a gate that fails good work is not a strict gate,
  it is a broken one.

- **2026-08-04 — a revive redid twenty minutes of research.** *Symptom:* every re-drop of a series
  that had already produced frozen canon re-mined the wikis from scratch. *Cause:* `research.run`
  called the model unconditionally, even though canon is immutable once frozen. The design promises a
  revive resumes rather than restarts, and research was quietly exempt. *Fix:* a frozen canon that
  still passes validation is reused and the reuse is logged; delete
  `state/canon/<universe>/canon.json` to force a fresh dig.

- **2026-08-04 — the test suite deleted a real job prompt.** *Symptom:* a parked
  `inbox/failed/swtor-jedi-knight.md` vanished after a routine test run. *Cause:*
  `test_images_revive.py` redirected `FANFIC_STATE_DIR` but not `FANFIC_INBOX_DIR`, so
  `config.INBOX_DIR` still pointed at the real drop folder — and its cleanup helper called
  `shutil.rmtree` on it. A test that deletes directories inherited one real path out of three.
  *Fix:* `tests/support.py` owns all three redirects and `_assert_redirected()` refuses to run at
  all if any of them resolves inside the repo. The general lesson: a test that deletes must prove
  its sandbox, not assume it.

- **2026-08-04 — a stage error spent a revision and erased the critique.** *Symptom:* SWTOR chapter
  1 parked `FAILED_CHAPTER` "revision budget exhausted" after five attempts, but `decisions.log`
  held only **two** critique verdicts — attempts 0 and 4. Attempts 1, 2, and 3 left nothing but a
  bare `ch_drafted` line in the journal. *Cause:* the chapter loop caught a `RuntimeError` from
  drafting or critique, set `feedback = f"draft/critique error: {exc}"`, and continued — spending a
  revision on a subprocess failure *and* overwriting what the critics had said. So attempt 4 was
  re-drafted with no knowledge of attempt 0's issues, produced a completely different set of
  problems, and parked. The chapter never got four revisions; it got two, and the second was
  amnesiac. Worse, the branch logged nothing at all, so the three underlying errors are gone
  forever. *Fix:* stage errors are counted separately against `CHAPTER_STAGE_ERROR_RETRIES`, never
  spend a revision, never touch the accumulated feedback, and are written to `decisions.log` as
  `stage error N`. The general lesson: a retry loop must not let its two failure modes share one
  counter, and an `except` branch that logs nothing is a branch that will happen invisibly.

- **2026-08-04 — the revision loop had no memory, so it oscillated.** *Symptom:* successive drafts of
  the same chapter fixed the last verdict's issues and introduced fresh ones — the parked chapter's
  final draft contradicted itself about whether initiates carry a pack, and about whether the guard
  post was six or twelve kilometres away. *Cause:* only the *most recent* critique was fed back, so
  nothing stopped a rewrite from reintroducing a defect an earlier critique had already caught. With
  a budget of four, trading A for B for A is a park. *Fix:* blocking issues accumulate across
  attempts and the revision brief carries them as an explicit "previously flagged — do not
  reintroduce" list.

- **2026-08-04 — the quality critic could never be satisfied.** *Symptom:* the same chapter's
  blocking verdict included "thin the similes by half", "consider letting the gap actually break",
  and "Minor prose tic: 'extremely'". *Cause:* the verdict had one boolean per critic and no
  severity per issue, so a demanding editor's polish notes were indistinguishable from a defect.
  The prompt asked for `passed: false` only for "problems worth a rewrite", but that judgement was
  unbounded and the critic is *supposed* to always find something. At 37 chapters a critic that
  blocks nine times out of ten never ships a book. *Fix:* every issue carries `blocking` or
  `advisory`; only blocking fails. Continuity blocks by default, quality is advisory by default, and
  advisory notes are still logged and still ride along in a revision brief. The floor was **not**
  lowered — the same fix shape as the coverage gate: stop counting things that were never defects.

- **2026-08-04 — a re-drop of a parked chapter was a guaranteed no-op.** *Symptom:* moving
  `swtor-jedi-knight.md` back into `_inbox/` revived the series, and five seconds later the journal
  read `FAILED book: chapter 1 parked` / `FAILED series: book 1 failed` and the prompt was filed
  straight back into `_inbox/failed/`. Zero progress, and the only available human action was a
  gesture the engine had already decided to ignore. *Cause:* `revive_series` deliberately skipped
  `FAILED_CHAPTER` on the reasoning that reviving cannot fix bad writing — but
  `book._advance_drafting` parks the whole book the moment the first incomplete chapter is
  `FAILED_CHAPTER`, so the revive rewound the book to `DRAFTING` only to walk straight back into the
  same wall. *Fix:* a re-drop un-parks parked chapters to `PENDING` with a fresh revision budget.
  This is not an auto-retry — nothing but a person moving a file triggers it — and the whole point of
  `FAILED` being terminal is that a *machine* never retries it. The general lesson: if the only
  documented recovery gesture provably cannot change the outcome, it is not a deliberate design, it
  is a dead end with a rationale attached.

- **2026-08-05 — `claude exited 1:` and nothing after the colon.** *Symptom:* with stage errors finally
  being logged (previous story), chapter 1's very next two attempts recorded `claude exited 1:` with
  an empty message. Visible, and still undiagnosable. *Cause:* `claude.py`'s `_rationale` read only
  the envelope's `result` field, but on a failure the CLI leaves `result` **null** and puts the reason
  in `subtype`, `terminal_reason`, and `api_error_status`. Every CLI failure of that kind therefore
  rendered as silence — and because `is_transient("")` is false, an unexplained failure was also
  confidently classified as a bad proposal and never retried. *Fix:* when `result` is empty the
  envelope's own diagnostic fields are reported instead, and an empty detail is now **retryable** —
  the classification is expensive in one direction only, so a failure that explains nothing does not
  get the confident reading. Verified by probing the real CLI: an exhausted turn budget exits 1 with
  `result: null, subtype: "error_max_turns", terminal_reason: "max_turns"`.

- **2026-08-05 — the stage that writes the most had the smallest turn budget.** *Symptom:* the above,
  decoded: chapter drafting was running out of agent turns. *Cause:* `drafting.generate` passed
  `max_turns=8` — the **lowest** of every substantive stage, against research's 80, outlining's and
  planning's 40, critique's 30, and the bible merge's 20 — while producing by far the largest
  artifact, five thousand-odd words of prose. A writer that lays a chapter down in sections spends a
  turn per section, so the cap was marginal: some attempts fit inside it and some did not, which is
  why the same chapter both succeeded and failed under it on 2026-08-04. A nondeterministic cap is
  worse than a wrong one, because it looks like flakiness rather than a limit. *Fix:*
  `config.DRAFT_MAX_TURNS`, default 30, `FANFIC_DRAFT_MAX_TURNS` to override. The general lesson:
  every per-stage limit should be sized against that stage's *output*, and this one had never been
  looked at since it was typed.

- **2026-08-05 — the exit code overruled the artifact, and nine minutes of judgment went in
  the bin.** *Symptom:* with the turn budget decoded and raised, chapter 1's next attempts still
  failed — `subtype=error_max_turns, num_turns=31`. But this time the failing stage was the
  **critique**, whose cap was 30, and `state/tmp/verdict_…json` was sitting on disk: valid JSON, a
  complete verdict, eight blocking continuity issues and eight advisory quality notes, written seven
  minutes before the CLI gave up. The harness deleted it and called the stage a failure. *Cause:*
  `run_to_file` checked `proc.returncode` **before** checking whether the artifact had landed. This
  entire module exists because stdout is unreliable and a file at a known path is a contract —
  and testing the exit code first quietly reinstated the exact dependency we were avoiding. *Fix:* a
  non-zero exit **whose cause is turn exhaustion** and which left the artifact on disk returns the
  artifact, with a logged note. That is safe here specifically: every stage grants only `Read`,
  `Write`, and `Grep`, and `Write` overwrites whole documents, so a file present is a *complete* last
  write and the overrun happened in the epilogue. Any other non-zero exit is still a failure, because
  "the last write was complete" is not a claim you can make about a model cut off mid-thought. The
  critic's budget also went to 60 (`CRITIQUE_MAX_TURNS`) — reading a chapter and the whole bible to
  produce sixteen line-cited issues is turn-hungry work, and a budget should not be the thing that
  decides whether a critic finishes thinking. Drafting then went to 80 on measurement rather than
  guesswork: the first real chapter came in at 5,122 words and *still* overran 40 turns, so the
  writer lays prose down at roughly 130 words a turn. A safety net you land in on every single
  call is not a net, it is the floor — and then a genuine mid-chapter cut-off would look exactly
  like the routine case. *The general lesson is the sharpest one in this file:*
  a founding principle is only as good as the line of code that checks it first.

- **2026-08-05 — the revision loop was a lottery with four tickets.** *Symptom:* with the critics
  finally discriminating properly, chapter 1's four attempts produced blocking continuity counts of
  **3 → 4 → 3 → 6**. Not converging — random-walking. And the defects were *entirely different every
  time*: attempt 0 flagged stormtrooper-style armour, an unspecified jaw-scar side, and a Lothal
  loth-cat on Tython; attempt 3 flagged an evacuation running the wrong way through the Throat, a
  self-contradicting raider count, and a doubled aftermath scene. Word counts jumped 3,474 → 5,182 →
  5,213 → 5,122. *Cause:* **a "revision" was never given the draft it was revising.**
  `drafting.draft_chapter` built the revision prompt from the digest plus the rejection reasons and
  nothing else, and `run_to_file` deletes the draft path before every run, so the writer could not
  have read the prior attempt even if it had thought to. `prompts/draft.md` instructed it to "fix
  exactly those and preserve what already worked" — an instruction it was **physically unable to
  follow**. So every attempt wrote a fresh five-thousand-word chapter, each roll independently
  generating three to six new continuity defects, and `CHAPTER_MAX_REVISIONS` bounded not a revision
  loop but a four-ticket lottery on a fresh draft coming out clean. *Fix:* the rejected draft is
  snapshotted to `paths.prev_draft_path` — outside the pre-run delete's reach — and the brief names
  it, orders the writer to read it first, and frames the task as surgery: fix only what the listed
  reasons implicate, every other sentence survives verbatim, do not restructure or start over. The
  prompt template says the same, and adds the line that matters: *a revision that reads as a
  different chapter has failed even if every listed issue is gone.* *The general lesson:* the three
  earlier fixes all made the loop's **accounting** honest — budgets, severities, carried-forward
  issues — and none of them could have worked, because the loop had no mechanism for incremental
  improvement at all. Bounding a process assumes the process converges. Check that it does before
  tuning the bound.

- **2026-08-05 — the loop converged, and the cap cut it off one pass from clean.** *Symptom:* with
  revisions made surgical, chapter 1's blocking-issue count fell **6 → 6 → 3 → 2 → 1** with readability
  tightening alongside (FK 7.69 → 6.86 → 6.20 → 6.11 → 6.12) — and then hit
  `CHAPTER_MAX_REVISIONS = 4` and parked **holding one issue**. Compare the pre-fix run's 3 → 4 → 3 → 6.
  The loop was working; the bound was wrong. *Cause:* the cap was chosen before anything was known
  about how fast the loop descends, and 4 is simply below where convergence lands when a first draft
  arrives with ~6 defects. Worse, a fixed attempt count is the wrong *instrument*: it cannot
  distinguish "one pass from clean" from "going nowhere", and those deserve opposite treatment — the
  first needs one more attempt, the second should not get one. *Fix:* the ceiling went to 8, sized
  from the measured descent. More importantly the real circuit breaker now watches the **derivative**:
  `_stalled` parks a chapter whose best blocking count has not improved for
  `CHAPTER_STALL_ATTEMPTS` (3) consecutive attempts. An ordinary plateau survives — the observed run's
  worst was a single flat pass — while the old random walk (3 → 4 → 3 → 6) is now cut off early
  instead of burning the full budget. Both park reasons print the whole trajectory, so a human can see
  at a glance whether a re-drop is worth paying for. *The general lesson:* a limit set before you have
  measured the thing it limits is a guess wearing a number, and the useful signal in an iterative
  process is almost never the count — it is whether the count is still moving.

- **2026-08-05 — the new circuit breaker's first real firing was a false positive.** *Symptom:*
  chapter 2 descended **5 → 5 → 1** and then hovered **2 → 2 → 1** — each pass fixing one defect and
  introducing another — and the stall breaker added an hour earlier parked it holding a **single**
  blocking issue, with two attempts still unspent. *Cause:* "the best count has not improved for three
  attempts" is a sound test of whether work is progressing and a meaningless one near zero, because at
  one remaining issue there is almost nothing left to improve *by*. The measure treated "hovering at
  the finish line" and "stuck going nowhere" identically, which is the same category error the fixed
  cap made, one level up. *Fix:* `CHAPTER_NEARLY_CLEAN` (2) — the stall breaker is suspended once a
  chapter's best count is at or below it, and the full revision budget is spent, because a chapter one
  lucky pass from clean is exactly what the remaining budget is for. The exemption is deliberately
  narrow: a chapter flat at 3 still parks. *The lesson, since this is now the second breaker in a row
  to get it wrong:* a threshold on a converging quantity needs a floor as well as a slope, and any
  heuristic that has never fired in production has not been tested, only written.

- **2026-08-05 — the writer was briefed from the plan while the critic judged the prose.** *Symptom:*
  chapters 1–3 were accepted, then chapter 4 random-walked **8 → 3 → 4 → 6 → 3** and the convergence
  breaker parked it (correctly, this time). Its dominant blocking issue never changed: *"Chapter 3's
  exit state is never resolved."* Chapter 4 opened three days after chapter 3 with the errand it ended
  on silently completed offstage. *Cause:* `chapter.run` derived `prev_exit` from the **outline's**
  `exit_state` for the previous chapter — a summary of what became *true* ("Bengel Morr is named, Elira
  carries her own lightsaber, Kaleth is identified as his seat"). The **accepted prose** ended
  somewhere quite different: mid-motion, with Elira running up out of the canyon to tell Orgus. The
  digest labelled the summary "continue from exactly here", the continuity guardian judged against the
  real chapter, and after several revisions the plan and the prose had diverged enough that the two
  disagreed. Four redrafts could not close a gap that existed **in the brief**, which is why the
  trajectory bounced instead of falling. *Fix:* the brief now carries both — the planned exit_state as
  *facts not to contradict*, and the previous accepted chapter's real closing
  `DIGEST_PREV_TAIL_WORDS` (400) of prose as *the narrative moment you are continuing from*, with the
  instruction to pick up whatever it left mid-motion rather than assume it resolved offstage. Missing
  or empty (a parked predecessor, an older series) degrades to the old behaviour instead of raising.
  *The general lesson, and it is the third time tonight in a different costume:* whenever a generator
  and its judge read different sources for the same fact, the loop between them cannot converge — and
  the symptom looks like a stubborn model rather than a missing input.

- **2026-08-05 — a billing ceiling parked a novel in nine seconds.** *Symptom:* five chapters in, the
  CLI returned `You've hit your org's monthly spend limit · run /usage-credits to ask your admin for a
  higher limit`. Chapter 6 burned **all four** stage-error retries between 09:37:38 and 09:37:47, parked
  `FAILED_CHAPTER`, failed the book, failed the series, and filed the prompt into `failed/`. *Cause:*
  the message was just another `RuntimeError`. The project already had exactly the right failure class
  for this — `QuotaExceeded`, documented in `errors.py` as "come back later", handled as a deferral in
  `cycle.py`, and never a failure — but **only `models/images.py` ever raised it**. The whole prose and
  judgment path, which is every stage that matters, had no concept of it, so an administrative ceiling
  was indistinguishable from a confidently wrong proposal. Worse, "rate limit" *is* in
  `TRANSIENT_SIGNATURES`, so a near-miss of this class would have been retried fast and then parked
  anyway. *Fix:* `config.QUOTA_SIGNATURES` and `claude.is_quota`, checked **before** the transient list,
  raise `QuotaExceeded` on first sight — no retry storm — and every engine handler on the path up
  catches `RuntimeError` specifically, so the deferral reaches `cycle.py` untouched. Nothing is parked,
  no status changes, and the engine re-checks every `MODEL_QUOTA_BACKOFF_SEC` (1800s, far longer than
  the image backoff because a monthly limit lifts when a person acts, not on its own). The run resumes
  by itself when the ceiling lifts, with no re-drop. *The general lesson:* having the right abstraction
  is not the same as having it wired in everywhere it applies, and the place it is missing will be the
  place that is actually load-bearing.

- **2026-08-05 — the fleet was competing with its own owner for one session.** *Symptom:* the owner
  needed Claude during the working day and found the allowance gone; the fleet had been drafting since
  midnight. The spend-ceiling story above is the same incident from the machine's side. *Cause:* there
  was no notion of *when* the fleet was allowed to spend capacity — only *whether*, via a hand-managed
  budget file nobody had populated. A shared resource with no schedule goes to whoever polls it in a
  loop. *Fix:* `fanfic/clock.py` and quiet hours — 09:00–17:00 US Central, Mon–Fri, no new work for the
  engine or the illustrator. Three details that matter more than the feature: it gates the *start* of
  work rather than killing a call in flight (interrupting a draft gives back no capacity already
  spent); admission and the status file keep running so a prompt dropped at lunchtime is still picked
  up, just not drafted; and the window is derived from **UTC** rather than the host's local clock,
  because a VPN or a mis-set timezone must not be able to move "9am Central". The status document says
  `⏸ Paused — working hours` so an eight-hour journal gap reads as intent rather than as the wedged
  engine this project has been bitten by before.

- **2026-08-05 — a usage meter was labelled as a bill.** *Symptom:* after the spend-ceiling incident,
  the fleet started recording each `claude` call's reported `total_cost_usd` to `state/spend.jsonl` as
  "what this cost", and the operator was told a probe call "cost $0.094". The operator objected
  correctly: this project **has no API key**, the CLI authenticates through its logged-in session, and
  the seat is billed per seat, not per token. *Cause:* the CLI reports `total_cost_usd` regardless of
  how it authenticates, and the field name was taken at face value. On a session-authenticated CLI it
  is a *list-price valuation of the tokens used* — a meter reading, not money moved. Verified: the
  probe returned a figure with no `ANTHROPIC_API_KEY` in the environment, none in any plist, and no
  `apiKeyHelper` configured. *Fix:* the file is `state/usage.jsonl`, the field is `list_price_usd`,
  the accessors are `record_usage` / `usage_valued`, and the log line reads `usage ~$X at list price
  (a meter, not a bill — no API key is in use)`. A test asserts the recorded field is not named `usd`,
  because that name is what invited the misreading. *The number is still worth having* — it is
  proportional to the allowance a run consumes, which is the thing that actually runs out, and it
  immediately quantified the run: ~$0.80-equivalent per draft, ~$1.90 per critique, ~$13 per accepted
  chapter, ~$500 for a novel. *The general lesson:* a field name is the unit the reader will assume,
  so a metric whose name overstates what it measures will be over-trusted in exactly one direction.

- **2026-08-05 — "I cannot verify that" became a way of not looking.** *Symptom:* the cost model shipped
  with Anthropic's prices filled in and every other vendor's left `None`, and concluded from that table
  that bringing a book under $5 "needs a very cheap hosted model or local inference — not a frontier
  model", with local inference presented as the realistic path. The operator disbelieved it and said to
  go and check. *Cause:* the refusal to invent a price was correct and had quietly turned into a refusal
  to *find* one. The arithmetic was sound; the input set was one vendor wide, so the comparison the
  conclusion rested on had never actually been made. *Fix:* published rates for eleven models, cross-checked
  across two aggregators. **DeepSeek V4 Flash at $0.09/$0.18 and GPT-5.6 Luna at $0.10/$0.60 both clear
  the required ceiling of ~$0.29 in / ~$1.14 out comfortably**, bringing a whole 37-chapter book with
  illustrations to $4.15 and $5.11 — no local inference anywhere. Against Claude Opus at $5/$25 that is
  55x on input and 139x on output; the Anthropic tier really is the premium end of this market. Two
  second-order corrections came with it: once text costs ~$1.20 a book the **images** are the larger half
  (~$2.95 of 44 pictures), which inverts where to optimise next; and a per-image price is a scalar, so
  keeping it in a dict of `(input, output)` tuples type-checked fine and read badly. *The general lesson:*
  "I can't verify this from here" is an honest thing to say and a dishonest thing to conclude from. If a
  number is load-bearing and findable, the correct move is to go and find it.

- **2026-08-05 — three places dropped the chapter title, so the book had none.** *Symptom:* five chapters
  accepted, and every heading in the forthcoming epub would have read "Chapter 1", "Chapter 2". The
  outline's 37 entries all carried `title: ""`. *Cause:* three independent omissions of the same field,
  each individually harmless and collectively fatal — `prompts/outline.md` never asked for a title,
  `gates/structure.py` never required one, and `binding.py` hardcoded `f"<h1>Chapter {n}</h1>"` and
  never read the field at all. Fixing any one or two of them would have changed nothing in the output:
  the prompt could produce titles the gate ignored and the binder discarded. *Fix:* the prompt asks for
  a short, spoiler-free, distinct title with worked good and bad examples; the gate requires one,
  rejects duplicates (a table of contents with the same entry twice is worse than none), and rejects a
  summary masquerading as a title; the binder renders it as a two-line heading and uses
  "Chapter N: Title" as the nav label. The binder also keeps a **fallback**, because an outline
  generated before the fix is durable state and a plainer book beats a binder that refuses to build.
  *The general lesson:* when a field is optional at every point it passes through, it is not optional —
  it is absent, and nobody finds out until the artifact ships.

- **2026-08-05 — one vendor was welded into eight stages.** *Symptom:* the operator asked how hard it
  would be to write with something other than Claude, or draw with something other than Gemini. The
  honest answer was: edit eight files. Every stage hand-tuned its own `max_turns`, `timeout`, and tool
  grant at its own call site, named `config.JUDGE_MODEL` directly, and called a vendor-specific
  `run_to_file`. *Cause:* the model contract was never given a seam — it was distributed across the
  callers, so "which service, which model, how much may it spend, and how is the artifact delivered"
  were eight separate answers that had to agree and did not. Drafting sat at `max_turns=8` — the
  smallest budget in the fleet against the largest artifact in the pipeline — for as long as those
  numbers lived apart; nobody spotted it until they were written down in one column. *Fix:*
  `fanfic/providers/` holds two contracts and a registry; `config.TEXT_ROLES` is one table of what each
  *kind of work* may spend; `models/text.py` is the single seam. A stage now says `role="critique"` and
  nothing else. *The subtle part, and the reason this is a real abstraction rather than a rename:* the
  **delivery contract belongs to the provider**. An agentic CLI holds tools and is told to write the
  path; an HTTP completion endpoint has no filesystem and is told to reply with only the artifact,
  which the harness then writes. That instruction used to be hardcoded as the path form inside
  `prompts.build`, which silently made every non-agentic provider impossible — told to write a file it
  cannot write, such a model reports success and the stage fails on a missing artifact with a symptom
  pointing nowhere near the cause. Capabilities are declared for the same reason: research needs live
  web access, so `check_role` refuses it on a provider that lacks it, naming both, instead of letting
  the coverage gate report mysteriously thin canon three steps later. *The general lesson:* a seam that
  exists in the documentation but not in the import graph is not a seam, and you find out which kind
  you have the first time you try to swap something.

  > **Postscript, and the reason this entry is worth keeping.** The registry, the second delivery
  > contract and `check_role` are all gone; see "Why there are no model tiers". The seam was built
  > correctly and then never used — no alternate backend was ever run on a real book, and research
  > could never move regardless because only the CLI has web access. *The half that was actually
  > load-bearing survived untouched:* `config.TEXT_ROLES`, one table of what each kind of work may
  > spend. That is the half that caught `max_turns=8`. **The lesson has a second half, then: the
  > abstraction that pays for itself is usually not the one you built it for.** Being able to swap
  > vendors was worth nothing; being able to see eight budgets in one column was worth a novel.

- **2026-08-04 — the inbox ate its own documentation.** *Symptom:* an `inbox/README.md` explaining
  the drop folder was admitted as a series called "readme", failed research for naming no source
  universe, and was filed away into `inbox/failed/`. *Cause:* admission globbed `inbox/*.md` and
  treated every match as a job. *Fix:* `engine.admission.is_job_file` skips `README.md` and any
  `_`- or `.`-prefixed file. Cheap, and the alternative is a folder you cannot document.

- **2026-08-08 — the model was being made to fetch what the harness was already holding.**
  *Symptom:* a novel consumed ~$484 of list-price-equivalent allowance, which is more than a
  month's seat, and an org ceiling had already stopped one run six chapters in. *Cause:* every
  stage handed the model *paths* — "the draft is here, the bible is there, read them" — and an
  agentic provider works in turns that each re-send the entire prior conversation, tool results
  included. So a bible fetched on turn 3 was paid for again on turns 4 through 60. Metered: a
  chapter draft spent ~227,000 input tokens to produce ~7,200 of prose; a critique ~363,000 to
  produce ~4,000 of verdict. Every one of those bytes was already in memory in the Python process
  that built the prompt. *Fix:* `oneshot` on every role but research — the input is quoted inline,
  the tool grant drops to `Write` alone, and the model is told to read nothing and produce the
  artifact in one call. Same models, same artifacts, ~$65. Two details make it more than a
  saving: the tool grant is the only part of "do not read" the harness can actually *enforce*, so
  it is narrowed rather than trusted; and because quoting is now cheap the critic is handed the
  **whole** memory — full cast, full ledger, every invented fact — where before it fetched
  whatever it happened to think of. *The general lesson:* the previous write-up of this had the
  finding right and the cause wrong. It concluded the fix was a different kind of *provider*,
  when it was a different kind of *prompt* — so the lever sat behind a vendor migration nobody
  wanted to make, for months, when it was always a property of what we were asking for.

- **2026-08-08 — "She-Ra" was three entities, none of them real.** *Symptom:* the crossover job's
  implied-entity list came back with `She`, `Princesses`, `Power`, and four copies of
  `From <show name>` — six junk terms in a 44-term denominator against an 85% coverage floor,
  enough on their own to park the job at research. *Cause:* two separate defects in one regex.
  The name pattern was `[A-Z][A-Za-z]+(\s+[A-Z][A-Za-z]+)*`, which has no hyphen, so a hyphenated
  name scans as its first syllable and abandons the rest — and hyphenated names are *ordinary*
  here (She-Ra, Obi-Wan, Spider-Man). And a list header, "From Gravity Falls: Dipper Pines, …",
  was captured whole, because the rule that drops a lone capitalised word opening a line does not
  fire on a multi-word span. *Fix:* the pattern admits internal hyphens and apostrophes; leading
  stopwords are stripped off a span rather than the span being discarded; `from`/`of`/`in`/`by`
  joined the stopword set. 44 junk-laden entities became 32 clean ones. *The trap in the fix:*
  stripping "From" off "From She-Ra" leaves a single word, which the lone-word rule then threw
  away — so the prose check has to judge the span **as it appeared in the text**, not what is left
  after the scaffolding comes off. *The general lesson, and this is the third coverage-gate story:*
  every entity is a denominator term, so a parser bug is not a parsing bug here, it is a false
  rejection of good research.

- **2026-08-08 — a twenty-cent saving was buying a seven-hour outage.** *Symptom:* routing two
  cheap mechanical roles to DeepSeek would have handed DeepSeek's peak-pricing windows —
  01:00–04:00 and 06:00–10:00 UTC — veto power over the *entire* fleet, on top of quiet hours.
  *Cause:* `cycle.run` passed `providers.role_assignments().values()` to the blackout check, so any
  vendor serving any role at all could pause everything. That was correct when one vendor served
  every role and nonsense the moment the point of the seam — hybrid routing — was actually used.
  *Fix:* `config.PEAK_SENSITIVE_ROLES` lists the high-volume roles, and only providers carrying one
  of those are consulted. *The general lesson:* a guard sized against "this vendor is the whole
  bill" keeps firing at full strength after the vendor becomes 2% of it, and the cost of the guard
  is not on the same ledger as the thing it guards.

  > **Postscript.** Peak-pricing avoidance is gone entirely, along with the vendor it was for. It
  > was fixed twice (see the 2026-08-10 entry) and never once paid for itself, because the fleet's
  > high-volume roles were always on a seat where no surcharge applies. `clock.blackout` takes no
  > provider argument any more, and a test asserts that it cannot.

- **2026-08-08 — a price that was real, published, and for the wrong model.** *Symptom:* the cost
  model valued images at $0.067 each and every "a book for $5" total was built on it. *Cause:* that
  is Nano Banana **Pro**'s batch rate. The configured model is Gemini 2.5 Flash Image, published at
  **$0.039** — 72% lower, on the single number the whole budget claim rests on, in a table whose
  own comment says to re-check the prices. It survived because it was not a guess: it had a source,
  and it was cited, and it was about something else. *Fix:* 0.039, verified twice over — against
  Google's pricing page, and against a live call on this key that returns exactly the 1,290 output
  tokens the page says a 1K image costs. *The general lesson:* "where did this number come from" is
  a weaker question than "what is it a number *for*", and a sourced wrong figure resists correction
  far better than an obvious guess would have.

- **2026-08-08 — the writer wrote half a book, beautifully.** *Symptom:* a live probe of the
  one-shot drafting path, given a real digest and a 5,351-word target, returned **2,681 words**.
  Not bad words: distinct character voices, comedy landing on the beat, Flesch–Kincaid 6.76 and
  reading ease 76.8, both dead centre of the band. Exactly half a book. *Cause:* nothing was wrong.
  A single completion asked for five thousand words of prose produces two to three thousand,
  reliably, because a chapter that long is three or four scenes and a model writes one sitting's
  worth per call. The brief said "about 5,351 words" and the model did what models do with that.
  *Why it mattered so much:* the length gate had been added an hour earlier, which turned a quiet
  shortfall into the most expensive failure the pipeline could have. Every chapter would fail on
  attempt one, burn all eight revisions being told it was short — and the revision brief
  simultaneously orders the writer to *change nothing that was not objected to*, so the two
  instructions actively fight. Thirty-seven chapters, thirty-seven parks, several hundred model
  calls, and a `FAILED` novel. *Fix:* a short draft is **continued**, not nagged. The writer is
  handed what exists and asked for what comes next — only what comes next, since the harness
  concatenates — with the outstanding beats, the exit state, and an instruction that a reader must
  not be able to find the join. Bounded at two passes, and it stops early if a pass adds nothing.
  *The general lesson:* a gate and the process it judges have to be designed together. This gate
  was correct, the measurement behind it was correct, and adding it alone would have destroyed the
  run — because a gate does not just measure a process, it decides what happens to everything that
  fails it, and there was no path from "too short" to "long enough" for it to send anything down.

- **2026-08-08 — surgery and appending, fighting over the same chapter.** *Symptom:* chapter 1's
  blocking-issue count went **5 → 2 → 2 → 1 → 4 → 2 → 4** across seven critiqued attempts. It
  reached a single remaining issue and then bounced, and the quality critic's standing complaint
  never changed: the chapter "spends its best scene twice" and left the reader unsure whether the
  crossing had happened once or twice. *Cause:* the continuation pass, added hours earlier to fix
  short first drafts, was running on **revisions** too. A revision is surgery on a chapter that
  already has an ending; asked afterwards for "what comes next", the writer wrote a second one. The
  two instructions contradict each other by construction — one says preserve every sentence you
  were not asked to change, the other says write more — and the chapter oscillated between obeying
  them. *Fix:* continuation is first-drafts-only. A short revision is a revision defect, and the
  critic is the thing that should say so. *The general lesson, and it is the same one as the length
  gate one entry up:* a mechanism added to fix one stage has to be checked against every *other*
  state that stage can be in. Both defects were introduced the same afternoon by fixes that were
  individually correct.

- **2026-08-08 — the cost model could not see the bill it was estimating.** *Symptom:* the projection
  said $65 of allowance for a book; the meter recorded $0.82 per draft against a predicted $0.12 and
  $0.70 per critique against $0.18, putting the real figure near **$339**. *Cause:* `VOLUMES` counts
  the tokens this repo *writes* — the digest, the artifact — and is structurally blind to everything
  the CLI adds: its system prompt, its tool definitions, and the model's reasoning tokens, which
  bill as output and are re-sent on every turn. A one-shot role still spends two or three turns
  thinking before its single Write and pays that overhead on each. The model was not mis-tuned; it
  was measuring a different thing from the one being billed. *Fix:* `cost.MEASURED_USD` overrides
  the arithmetic wherever a real per-call figure exists, `continuation` became a named role so its
  cost stops hiding inside drafting's, and two claims flipped — writing now outweighs judging.
  *The general lesson:* this file already records "a price you derived is not a price you looked
  up". The same sentence is true of token counts, and it took a second incident to notice that the
  first lesson had a wider scope than the one it was written about.

- **2026-08-08 — I killed the production run with my own cleanup.** *Symptom:* chapter 1 recorded
  `claude exited 143: subtype=error_during_execution, terminal_reason=aborted_streaming`, and its
  status went to `CH_DRAFTED` with a stage error, at revision 7 of 8. *Cause:* 143 is SIGTERM. A
  test run had hung after a bad edit and was killed with `pkill -f "claude -p … --max-turns 10"` —
  a pattern that also matched the *daemon's* live drafting call, because they are the same command
  line. *Fix:* nothing in the code; the harness already handled it perfectly, counting a stage error
  rather than a revision and preserving the accumulated critique feedback, which is precisely the
  2026-08-04 fix doing its job. *The lesson is operational:* on a host running a production fleet,
  a `pkill` pattern that matches the fleet's own subprocesses is indistinguishable from an outage,
  and "I only meant to kill my test" is not a property the pattern has.

- **2026-08-08 — the loop said surgery and did a rewrite, so it played whack-a-mole for six
  attempts and lost the book.** *Symptom:* chapter 3's blocking count went
  **3 → 3 → 4 → 1 → 2 → 1 → 1 → 1 → 1** and parked, which failed book 1, which failed the series.
  It converged to a single issue by attempt 3 and then held at exactly one for six consecutive
  attempts. *Cause:* the issue was a **different one every time** — a spoon left on a desk and then
  held two paragraphs later, a house that became an apartment building, a notch given a scaling
  rule that contradicted the bible, an impossible-knowledge POV break in one paragraph. The
  instruction has been *surgery, not authorship* since 2026-08-05, but the mechanism was the writer
  re-emitting all ~4,700 words, and a rewrite of that length drifts however firmly it is told not
  to. Every pass fixed what was named and broke something else in the prose it was supposedly
  leaving alone; a critic this sharp finds the new damage each time. The accumulated
  "do not reintroduce" list is no help — it guards against old issues returning, not new ones
  appearing. And the `_stalled` breaker is deliberately suspended near zero
  (`CHAPTER_NEARLY_CLEAN`), so the chapter was allowed to spend its entire budget doing this.
  *Fix:* at or below `PATCH_REVISION_MAX_ISSUES` the model proposes **exact find/replace edits**
  and `stages/patching.py` applies them. Untouched text is not rewritten by anything, so it cannot
  drift. An anchor matching twice is refused rather than applied to the first hit, because two
  identical sentences in a chapter is ordinary and guessing silently corrupts prose that already
  passed; good edits still land when a sibling edit is rejected; an unusable edit list falls back
  to a rewrite rather than costing the attempt. *The general lesson:* every other stage in this
  project already had the model propose and deterministic code dispose — the revision loop was the
  one place where the model was trusted to apply its own change, and it is the one place that could
  not converge. An instruction is not a mechanism, and the gap between them is invisible until
  something downstream is strict enough to measure it.

- **2026-08-09 — the writer was judged on a ledger it had never been shown.** *Symptom:* chapter 7
  took eight attempts (12 → 5 → 3 → 6 → 1 → 2 → 3 → 0), and nearly every blocking issue was the same
  kind of thing: relative-time arithmetic. "Soos's welts had come up two days after the storm"
  against a chapter that said four. "The storm's age contradicts the established four-day figure."
  "Six years after Weirdmageddon." *Cause:* `build_ground_truth` — the **critic's** document —
  carries the story timeline and every established series fact. `build_chapter_digest` — the
  **writer's** document — carried neither. So the writer invented durations, because nothing had
  ever told it any, and the continuity guardian checked those inventions against a ledger the
  writer could not read. *Fix:* both sections now go into the writing brief, with the instruction
  not to invent a duration that contradicts a figure already on the record. *The general lesson,
  and this project has now paid for it twice:* whenever a generator and its judge read different
  sources for the same fact, the loop between them cannot converge, and the symptom looks like a
  stubborn model rather than a missing input. The 2026-08-05 entry says exactly that about the
  previous chapter's exit state. The lesson was recorded and the *check* was never generalised —
  so when a class of defect keeps recurring, diff the two documents rather than tuning the loop.
  A test now asserts the two agree on these fields.

- **2026-08-08 — the deploy mechanism had never once run.** *Symptom:* `run.sh` self-updates with
  `git pull --ff-only` on every launch, and the first line of every daemon log was
  `fatal: Cannot fast-forward to multiple branches` followed by `using local files`. *Cause:* a
  bare `git pull` resolved `origin/HEAD` as a second merge head beside the tracked branch. The
  failure was caught and logged by design — a launcher that refuses to start because GitHub is
  unreachable is worse than a stale one — so the daemon came up every time and nobody looked at
  line one. *Fix:* name the branch explicitly. *The general lesson:* a fallback that is indistin-
  guishable from success will be mistaken for it, so the thing worth logging is not that the
  fallback fired but that the primary path never has.

---

- **2026-08-10 — the loop was a courier service, and the parcel got damaged in transit.**
  *Symptom:* twenty-one chapters accepted, and the blocking-issue count per attempt looked like
  this, book-wide:

  ```
  ch  1  5 -> 2 -> 2 -> 1 -> 4 -> 2 -> 4 -> 5 -> 2 -> 3 -> 2 -> 2 -> 0
  ch  8  15 -> 4 -> 3 -> 4 -> 2 -> 3 -> 3 -> 3 -> 2 -> 10 -> 7 -> 6 -> 6 -> 8 -> 6 -> 14 -> 6 -> 2 -> 4 -> 4 -> 3 -> 2 -> 4 -> 5
  ch 14  13 -> 10 -> 6 -> 8 -> 5 -> 6 -> 4 -> 15 -> 8 -> 7 -> 4 -> 5 -> 6 -> 3 -> 2 -> 4 -> 5 -> 4
  ch 22  13 -> 3 -> 6 -> 4 -> 5 -> 5 -> 2 -> 4 -> 3 -> 3   (parked)
  ```

  Twenty-four attempts on chapter 8, at roughly $1.75 an attempt, and attempt 24 was worse than
  attempt 5. Eleven of twenty-one chapters shipped holding defects anyway. Chapter 22 then exhausted
  its budget, parked, failed its book, failed the series, and the run stopped with 113,000 words of
  good prose on disk and no path forward that did not involve a person dragging a file.
  *Cause:* the loop moved a conclusion between two heads. A judge read the chapter with the whole
  bible in front of it, located a defect exactly, and wrote a **prose description** of it. A
  *writer* then read that description, went looking for the text it referred to, and re-emitted the
  chapter. Everything about that is lossy, but the fatal part is the re-emission: asked for 4,700
  words with only the flagged parts changed, a model changes other parts too — not out of
  disobedience, but because regenerating prose is a different operation from preserving it. A sharp
  critic then finds the new damage, correctly, and the count goes back up. Every previous fix in
  this file made the loop's *accounting* honest — severities, separate budgets, carried-forward
  issues, a stall breaker watching the derivative — and every one of them was tuning a bound on a
  process that does not converge.
  *Fix:* the editor holds the pen. `stages/editing.py` is one call that finds each defect **and
  writes its exact find/replace repair**, which deterministic code applies; `stages/surgery.py`
  covers the narrow case where the fix is genuinely new prose, by replacing one anchored span. There
  is no rewrite path anywhere any more, and a chapter is drafted exactly once. On the first live
  chapter through it: **13 repairs proposed, 13 anchored, 13 applied, 0 rejected**, in a single
  $1.49 call, against a $1.75 round that used to deliver four.
  *The general lesson:* this project's founding principle is that the model proposes and
  deterministic code disposes. The revision loop looked like it obeyed that — there was a critic and
  there was a harness — but the thing actually being disposed of was a *description* of a change,
  re-derived by a second model that had to guess where it went. Check what is crossing the seam, not
  whether there is one.

- **2026-08-10 — one stubborn chapter threw away twenty-one good ones.**
  *Symptom:* `FAILED_CHAPTER` on chapter 22, then `FAILED book: chapter 22 parked`, then
  `FAILED series: book 1 failed`, in ten seconds, and the status file told the operator to go and
  move a file. *Cause:* `FAILED` was terminal by design, and the design was defended by a genuinely
  correct argument — auto-retrying a deterministic failure burns allowance to learn the same thing
  repeatedly. The error was treating "retry immediately, forever" as the only alternative to
  quitting, and then propagating the verdict upwards: a chapter's failure was allowed to be a book's
  failure, and a book's a series'. *Fix:* three separate things, because it was three separate
  mistakes. A chapter that will not come clean **ships** holding a recorded list of its defects, and
  the book's new REVISING sweep revisits it once every chapter exists and the editor can see the
  whole book. A stage that raises **stalls** the unit — recorded, and retried on a wait that doubles
  from five minutes to an hour, indefinitely — so an outage, an allowance ceiling, and a bug fixed
  tomorrow all resume unattended. And nothing propagates a failure upward, because there is no
  longer such a thing to propagate. *The general lesson:* "we must not retry this forever" and "we
  must abandon this" are different claims, and the first one does not imply the second. A backoff is
  the whole distance between them, and it was two hours of work that had been sitting behind a
  three-word design principle for the life of the project.

- **2026-08-10 — the same guard, fixed once, in two places.** *Symptom:* the illustrator
  daemon was restarted and its second log line read `paused for peak pricing: 01:00-04:00
  UTC costs double on this provider`. It renders through Gemini and critiques through the
  CLI; neither has a peak window. *Cause:* `illustrator.cycle` passed
  `{IMAGE_PROVIDER} | set(providers.role_assignments().values())` to the blackout check —
  *every* configured provider, including DeepSeek, which serves exactly one role
  (`art_direction`) that this daemon never calls and which costs a fraction of a dollar a
  book. So a twenty-cent routing choice held a veto over seven hours a day of
  illustrating. This is written up two entries above as a 2026-08-08 fix to `cycle.run`,
  and it *was* fixed there; the identical line in the illustrator was never touched.
  *Fix:* consult the image provider and whatever serves `vision`, which is the complete
  set of things this daemon actually calls. *(Both copies are now moot — the whole guard was
  deleted with the vendor; see the postscript two entries above.)* *The general lesson:* the failure
  story for the first copy is not a fix for the second, and a guard that composes a set from "every
  provider we have" will keep being wrong every time the set grows. `grep` for the shape
  of a bug, not only for the file it was found in.

- **2026-08-10 — "clean" meant two different things, and only one of them was true.**
  *Symptom:* chapter 24 went `5 -> 2 -> 2 -> 2` and the engine logged
  `ACCEPTED clean`. Its final pass had found a cape attributed to a character who was
  four worlds away and a POV slip into the wrong head, repaired both, and stopped —
  because the count had plateaued and the budget said so. *Cause:* the loop reported
  clean whenever `outstanding` was empty, and `outstanding` means "defects whose repair
  did not land". Every defect the last pass found had a repair that landed, so the list
  was empty, so the chapter was clean. Nothing had re-read those repairs. Chapters 22
  and 23 ended on a pass that found **zero** and were clean in the strong sense; 24 was
  clean in a sense that only means "we stopped". *Fix:* the loop returns whether it
  ended on a pass that found nothing, the record carries `unverified_repairs`, and the
  log says which of the two it is. A chapter with unread repairs is queued for exactly
  **one** sweep round. One, and expressed as a count rather than a condition, because
  "sweep until verified" does not terminate: any pass that applies an edit leaves that
  edit unread, so a chapter the editor keeps finding something in would sweep forever.
  *The general lesson, and this file already records it about a field called
  `total_cost_usd`:* a name is the claim the reader will act on. "Clean" was doing
  double duty for "nothing is wrong with this" and "we ran out of budget while fixing
  it", and the second is the one that needed saying out loud.

- **2026-08-10 — the vision critic had never been shown a single character's face.**
  *Symptom:* the operator looked at the illustrations and said the people in them were
  "just off", and often that it was not even clear who they were meant to be. Thirteen
  slots had no picture at all. The rejection reasons read: *"the mug is not empty"*,
  *"the fez is on a hook rather than in Stan's hand"*, *"the tail is trailing rather
  than coiled"*, *"the threads run parallel instead of braiding"*. *Cause:*
  `render_scene` called `vision_verdict(staged, entry["scene"])` — it passed the
  **one-sentence staging line** as the spec, and the critic's instructions told it to
  check "correct character, correct costume, correct palette". It had never been given
  any character's locked appearance. So it could not check identity at all, and
  checked the only document it had: the furniture. Meanwhile nothing anywhere in the
  loop was verifying the one thing the loop exists for, which is that the person in the
  picture is recognisably the right person. Three regenerations of a staging complaint
  and the slot was skipped — and because the binder stopped at the first gap, a chapter
  whose slot 1 was skipped silently lost slot 2 as well.
  *Fix:* the critic gets the locked designs of everyone in frame, and half of
  `prompts/vision.md` is now devoted to what is **not** its business — prop placement,
  pose, figure count, furniture, composition — with the test stated as "would a reader
  be confused about who this is, or notice the drawing is broken". Alongside it:
  `art_direction` moved to the judge tier, because what it decides is what every
  picture in the book is *of*, and on the cheap tier it chose six- and eight-figure
  compositions no image model renders; a hard ceiling of three named characters is
  enforced in code; the prompt is rebuilt subject-first the way an image model reads,
  with the hex palettes removed, since a model handed `#b30000` does not paint with it;
  each retry asks for *less* rather than repeating itself; and an image that rendered
  but never satisfied the critic is now kept with the complaint in a `.note` sidecar,
  because a slightly-off illustration beats a hole. Verified live: a Luz reference
  sheet and a two-hander scene, both instantly recognisable, both passed, 7 seconds and
  $0.039 each.
  *The general lesson — and this is the THIRD time this file records it, which is the
  actual finding:* when a generator and its judge read different documents for the same
  fact, the loop between them cannot converge. It was written down about a chapter's
  exit state, then about the story timeline, and both times the fix was applied to that
  one pair of documents and the *check* was never generalised. Two layers away, the
  image critic had the same disease and nobody looked, because prose and pictures felt
  like different problems. They are the same problem. Diff the two documents.

- **2026-08-10 — thirty-one canon facts about a show, and not the one that mattered.**
  *Symptom:* the operator looked at the illustrations of a crossover set after four
  finales and said the book had not taken the endings into account at all. He was
  half right, and the half he was right about was exact: Dipper Pines was drawn in his
  pine-tree cap and Wendy Corduroy in her ushanka. They trade hats in the final episode
  of Gravity Falls. It was backwards in the series bible and in every illustration, and
  in three places in the prose.
  *Cause:* **the fact was never collected.** Thirty-one researched Gravity Falls facts,
  ten of them mentioning Wendy or a hat, and the swap in none of them. Everything
  downstream then behaved correctly and produced the wrong book: planning wrote the
  appearance from the show's default because that is what canon described; the
  continuity editor checked the prose against canon and found nothing wrong, because
  the fact it needed was not there; the vision critic checked the pictures against the
  bible and passed them, because the bible agreed with itself. No gate failed. **A gate
  cannot check a fact nobody wrote down.**
  The deeper shape: canon research collects what is true of a *series*. A story needs
  what is true at the *moment it starts*. Those are different documents, and only one of
  them was ever being written. The coverage gate had verified that canon *mentions* the
  entities the prompt implies — never that anyone knew where those entities were
  standing, what they were doing with their lives, or what they had in their hands.
  *Fix:* `stages/anchoring.py`, gated, between research and planning. Four fields per
  principal — `where`, `doing`, `wears`, `changed` — with a missing one a hard
  rejection, because the absent field is always the one that turns up wrong three
  hundred pages later. Research is separately told to mine endings for exactly this
  class of fact, with the hat swap named as the worked example. And the anchor outranks
  canon wherever they disagree, because for anything a finale changed the anchor is the
  present tense and canon is the past.
  *The general lesson:* every gate in this project was built from a defect, so between
  them they cover every way the book can be *wrong* and had nothing to say about whether
  anybody had established what was *true* to begin with. When a class of error survives
  a full pipeline untouched, check whether the input it needed was ever gathered before
  you go looking at the checks.

- **2026-08-10 — I kept a picture of the wrong person because I had just written the
  rule that said to.** *Symptom:* chapter 1's diner illustration is Luz sitting opposite
  a second, identical Luz in a matching hoodie, holding her own hand. It is meant to be
  her mother. *Cause:* three faults stacked, and two were mine from that same hour.
  **No reference sheets existed at all** — 0 of 31 locked — so every face in every scene
  was being invented from prose; the sheets are generated by the scribe and the
  illustrator drains scenes independently, so nothing enforced the ordering and the
  worker raced ahead drawing anchorless pictures. **Camila was never named** in the
  scene's character list, so she arrived with no design attached and the model filled
  the gap from the only description present, which was Luz's. And I had just added
  "keep an imperfect picture rather than leave a hole", which kept it after the critic
  said in three separate verdicts that a reader could not tell who she was.
  *Fix:* the sheets-first check moved into `render_scene`, the one function both
  drainers call, and a missing sheet *defers* rather than skipping. Scene descriptions
  are scanned against the bible's cast so a name in the text gets its design attached
  deterministically. And the critic now raises `wrong_character` separately from its
  notes: "a slightly-off illustration beats a hole" is true of a hair shade and false of
  a picture of somebody else, which does not merely fail to inform a reader but
  misinforms them about a face, in a book whose whole visual promise is that faces stay
  put. *The general lesson:* a rule that is right about the common case still needs its
  boundary stated, and the fastest way to find that boundary is to ask what the rule
  would do with the worst input rather than the typical one.

- **2026-08-10 — the test suite passed at 3am and failed at 11am on the same commit.**
  *Symptom:* fifteen tests failed immediately after an unrelated edit to an image
  prompt, including the full end-to-end pipeline. *Cause:* `run_engine` drives REAL
  cycles, and a real cycle consults the real clock. Inside the owner's quiet hours the
  engine correctly refuses to start work, so every end-to-end test spun out its cycle
  budget doing nothing and failed. The suite had only ever been run in the evening.
  *Fix:* `tests/support.py` switches quiet hours and peak windows off for the suite, and
  the tests that are genuinely *about* those windows turn them back on for their own
  duration with an injected `now`. *The general lesson:* a test that consults the wall
  clock is a test whose result depends on when you run it, and the cost is not the
  failure — it is that the failure points at whatever you changed most recently instead
  of at the clock. The state-directory interlock in this same file exists for the
  identical reason: a suite must not inherit ambient facts about the machine it is on.

- **2026-08-10 — a daemon spent a minute doing nothing, in a log that read like work.**
  *Symptom:* `cycle error (continuing): AttributeError("module 'fanfic.config' has no
  attribute 'IMAGE_MAX_CHARACTERS'")`, once every thirty seconds, tidily. *Cause:* a
  config knob written against an anchor comment that did not exist in the file, so the
  edit silently did nothing — and `daemons.loop` swallows every exception to stop a
  transient blip becoming a restart storm, which is correct and which makes a
  deterministic bug look identical to one. *Fix:* consecutive identical failures are
  counted; past three, the line says `STUCK: the same cycle error N times in a row —
  this is a bug, not a blip, and no work is getting done`, and the nap backs off
  geometrically so it stops scrolling. The daemon still never exits, because launchd
  would only restart it into the same bug. *The general lesson:* this project's whole
  argument is that a problem needs somewhere to be recorded that is not silence — and a
  log line indistinguishable from noise is silence with extra steps.

- **2026-08-10 — the crossover had no plan for its crossings.**
  *Symptom:* four casts, twenty-nine locked characters, thirty-seven chapters — and no document
  anywhere naming a single pairing the book was supposed to deliver. Whether Dipper ever got to work
  a problem with Entrapta was left to whichever chapter's beat sheet happened to put them in a room.
  *Cause:* every ledger in this project tracks something the *plot* needs — a foreshadowed thread, a
  timeline entry, an invented fact — and the outliner thinks in plot, so it optimises for those and
  gets them right. "These two finally share a scene" is not a plot beat. It is the reason somebody
  picked up a crossover, and nothing in the pipeline had a field for it, so nothing asked for it and
  nothing checked. *Fix:* an interaction ledger, planned in the series plan alongside the cast and
  gated like `voice` was: roughly one entry per two characters, capped at cast-1 so a one-POV
  standalone stays plannable, each naming the people and what makes that specific scene worth the
  page. The outliner must assign every entry to exactly one chapter — an unplaced interaction fails
  the structure gate like an orphaned thread, and delivering one twice fails it too, because a scene
  the book already had is a repeat rather than a payoff. The writer's brief then names what this
  chapter owes, and the editor's ground truth carries the whole ledger so it can tell a delivered
  promise from a mentioned one. *The general lesson:* the gates in this project all grew out of
  defects, so they cover every way the book can be *wrong* and had nothing to say about whether it
  was the book anyone wanted. A specification needs entries for what a reader came for, not only for
  what a reader would complain about.

- **2026-08-12 — the ledger was sized to the cast when it had to cover the book.**
  *Symptom:* the interaction ledger above shipped, worked exactly as designed, and the finished book
  still had chapters where nobody met anybody. Twenty-three entries across thirty-seven chapters
  left **fourteen chapters owing nothing to anyone**, and chapter 1 was one of them — six people at
  a dinner table, one of whom talked, the other five furniture. *Cause:* the floor was
  `min(cast-1, max(8, cast//2))`, a function of how many characters exist. Nothing in it knows how
  many chapters there are, so a longer book got no more collisions than a short one, and the
  surplus chapters were simply not covered. *Fix:* a **meta plan** — its own gated stage between
  planning and outlining — that walks the book chapter by chapter and gives each one four or five
  collisions, one per scene segment, built ten chapters to a call. ~180 entries instead of 23, with
  an arithmetic gate over the finished ledger: everyone in at least six, no group used twice, sizes
  varied, 60% crossing universes, every pairing of worlds given a share. *The general lesson:* when
  a gate is satisfied and the defect it was written for still happens, check what the threshold is a
  function of before rewriting the thing being gated.

- **2026-08-13 — the age was written as a comparison, so the pictures picked their own.**
  *Symptom:* Luz Noceda is drawn as a woman approaching thirty in every illustration of the first
  book. *Cause:* her locked appearance read "grown into adult height and build rather than the
  fourteen-year-old who fell in, broad shoulders, hair cropped shorter" — three pushes away from a
  number nobody supplied. It came from the anchor stage, whose schema asked for "age or life stage"
  and whose gate checked every other field for presence and this one not at all; all 48 anchored
  principals carried a comparison, and planning copied them faithfully. **A comparison names a
  direction and never a distance**, so the model started at fourteen and guessed how far to travel.
  *Fix:* `age` is a plain integer, checked by shape at the anchor gate and again at the planning
  gate through the same parser, and rendered as a number into the block the planner copies from.
  *The general lesson:* a field every stage passes along unexamined is a field with no owner — and
  the near-miss is the instructive part, because requiring an age at the planning gate alone would
  have produced a run that stalled at stage two forever, since the only document upstream of it could
  not supply one.

- **2026-08-13 — the judge was reading a paragraph while the generator looked at a photograph.**
  *Symptom:* the operator could not identify people in finished illustrations. Soos Ramirez rendered
  as a moustached stranger in a headlamp cap; King as a grey wolf with a tail; Anne Boonchuy as a
  small pale child in a cloak; a scene naming three characters that drew two. Every one had passed
  the vision critic. *Cause:* the critic was handed the render and a **prose description**, so it was
  checking "heavyset young man, green shirt, question mark" — which the stranger satisfies. It passed
  correctly against the document it had. The reference art was on disk the whole time, fetched and
  good; nobody had ever given the critic the paths. The tell was in which characters failed: the
  casualties were all ordinary-looking humans, while everyone with an unmistakable silhouette came
  out fine, because prose can specify a crop top and cannot specify a jaw. *Fix:* the critic opens
  the same pictures the generator was given and compares faces; `vision.md` rewritten to be strict on
  identity and unchanged on staging; the appearance paragraph dropped from scene prompts that carry
  references, since prose and picture average rather than reinforce; foreground-only reference
  attachment. *The general lesson:* the third recorded instance of one rule — **when a generator and
  its judge read different documents for the same fact, the loop between them cannot converge**, and
  it always presents as a bad model rather than a missing input.

- **2026-08-13 — five gates counted who was in the room and none counted what happened in it.**
  *Symptom:* thirty-nine chapters and ~200,000 words in, the operator asked why there were no
  action-packed illustrations. There were none because there was no action: chapters 20–39 average
  about two physical verbs each, and the outline scheduled the fighting into chapters 43–45.
  *Cause:* the interaction ledger is gated on appearances, repeated groups, group sizes,
  cross-universe share and world-pair share — all of which count *people*. A ledger can satisfy every
  one of them and be two hundred conversations, and a model optimises for what is measured. The
  drop prompt's loudest instruction, *"scenes are built out of people talking to each other"*, was
  written to kill interiority padding and did, and then kept going. And the one line in the whole
  brief that asked for action lived in the `## Illustrations` section, which only the illustrator
  reads — delivered exclusively to the stage that can draw pictures and cannot cause events.
  *Fix:* every interaction declares a `register`, with floors on the physical share over the whole
  book, the front half and the back half, plus a per-register ceiling. Verified against the shipped
  ledger, classified as generously as the text allows: rejected. *The general lesson:* a gate that
  counts the participants of a scene has not looked at the scene, and **what is not counted is not
  optimised** — the same shape as the length target one entry down, arriving from the opposite
  direction.

- **2026-08-12 — the length target was manufacturing the filler.**
  *Symptom:* the reader's first complaint about the finished book was that chapter 1 was boring, and
  specifically that it spent paragraphs on how its POV character felt about her own dialogue. That
  is exactly the prose `prompts/draft.md` forbids in bold. *Cause:* the book was specified at
  ~198,000 words over 37 chapters, giving a 5,351-word per-chapter target that the length gate
  enforced at a 0.75 floor. Measured on this project's own logs, one completion asked for 5,351
  words returns about 2,681 — so the gate fired on roughly half of all drafts and each one went back
  for a continuation pass. For a model that has already told the story it planned to tell, the
  cheapest available way to reach a word count is interior monologue. The gate did not merely fail
  to produce depth; it asked for padding and got the only padding available. *Fix:* floors replace
  targets everywhere — an absolute 3,000-word chapter floor with no ceiling, a 150,000-word book
  floor, a 32-chapter floor, and the outliner picks the count the story needs. The continuation
  prompt now names what "more" may consist of: unplayed beats and other people in the room, never
  reflection. *The general lesson, and the second half of it matters:* the first draft of this
  change was justified as a cost saving, which was checked against `state/usage.jsonl` and turned
  out to be false — continuation was 60 calls and $15.73 of a $1,003 run, 1.6%. The change is right
  for a reason that has nothing to do with money, and a correct change resting on a wrong reason is
  one revert away from coming back.

- **2026-08-12 — the pictures were chosen from an average of everything.**
  *Symptom:* too few illustrations, all of them appended after a chapter's last paragraph, and the
  two scenes a reader most wanted drawn — a character carving at his workbench, a family dinner —
  drawn not at all. *Cause:* two things, and the second made the first unfixable. Art direction was
  handed the whole chapter and asked for two moments out of it, so it picked the two that read most
  dramatically and ignored where in the chapter they happened. And `_chapter_images` concatenated
  every figure after the last paragraph, which is the only placement the binder has ever had. But
  the real blocker was upstream of both: **chapter 1 contained no scene-break markers at all** —
  five distinct settings, zero separators — and the harness cannot split what the writer never
  separated. *Fix:* the writer marks every change of place or time, a deterministic splitter turns
  those into segments, art direction runs per segment on that segment's text, the image slot number
  *is* the segment number, and the binder splices each figure at the end of its own scene. A gate
  blocks a chapter with no breaks, and its repair is an ordinary anchored edit rather than a
  redraft. *The general lesson:* before fixing where an artifact is placed, check whether anything
  in the pipeline knows where it belongs.

- **2026-08-12 — the picture budget counted slots, not renders, and the README said
  otherwise.**
  *Symptom:* none, which is the point. Every counter read green. *Cause:* `record_image`
  was called once per image *slot* by the engine, after `render_scene` had already made
  up to `IMAGE_MAX_REGENERATIONS` real render calls inside its retry loop. The vendor
  bills each of those. So the meter recorded 1 where three had been charged for,
  `image_budget_remaining` was over-optimistic by the regeneration factor, and a run
  with an unlucky vision critic could bill several times the picture budget
  without any ceiling noticing. A derived per-chapter cap computed from that number
  inherited the same error, and a "keep rate" divided by it measured how many slots
  produced a file — a skip rate, near 1.0 on a healthy run — rather than the reject rate
  it was documented as measuring. *Fix:* `illustration.billed_render` counts each
  attempt as it is made, before the call, and the engine no longer counts slots at all.
  *The general lesson:* this paragraph of the README already claimed the budget counted
  "every render rather than every keeper". It was written as a design intention and read
  ever after as a description, and the one number in this project that is actual money
  was wrong for as long as nobody checked it against the code. A documented invariant
  with no test is a wish.

- **2026-08-13 — the reference-art gatherer was never called by anything.**
  *Symptom:* the operator said Waddles looked off, and asked whether the character
  beside Hooty was meant to be Eda's sister. Both were drawn correctly *to their written
  descriptions* — Waddles from "a pink pig, originally billed at fifteen pounds". Twenty
  of the cast were in the same state and nothing anywhere said so. *Cause:*
  `refart.gather` had a call site in a test and **nowhere else in the package**. The
  twenty-seven characters who did have art got it from a one-off run by hand on the day
  the module landed; every character the bible merged in afterwards — which in a
  crossover is most of them, arriving chapter by chapter — got none. A sheet drawn from
  prose is still a `.png` of a character, so there was no symptom until somebody looked
  at a pig. *Fix:* the fetch happens per character at the moment their sheet is drawn,
  so the question is asked once per character however late they join; sheets record how
  much real art they used; and a sheet drawn blind is re-locked, with the pictures it
  anchored discarded so they redraw. *The general lesson:* a stage nothing calls is
  indistinguishable from a stage that works, and this one had a passing test. `gather`
  was tested, was correct, and was dead. Grep for the call site, not for the function.

- **2026-08-13 — a wiki search always answers, and the answer was Dee Bradley Baker.**
  *Symptom:* none yet, and only by luck. The art on disk was fetched ten minutes before
  the search-based resolver was written, so the bug had never once run. Wiring the
  gatherer in would have fired it across the whole cast. *Cause:* `resolve_title` was
  built to fix a real problem — the bible says "Stanford Pines", the wiki says "Ford
  Pines" — by searching and taking the best hit, falling back to `hits[0]`. But a
  MediaWiki search does not have a concept of "no". "Waddles" on the Owl House wiki
  returns the voice actor's page; "Perfuma" returns Luz Noceda; "Dipper Pines" returns
  an Owl House episode. And the fetcher walked the series' universes in order and kept
  whichever answered first, which for a four-way crossover is the *same* wiki for every
  character in the book. Every render of Perfuma would have been anchored to pictures of
  Luz. *Fix:* look each character up on the wiki their own `origin` names first; require
  an exact title or a shared word; resolve a gallery subpage to its article; return None
  otherwise. *The general lesson:* a fuzzy lookup with a fallback is a lookup that cannot
  fail, and one that cannot fail cannot tell you it did not find anything. The fallback
  was the bug, and it was written to be helpful.

- **2026-08-12 — the fix landed, and eight chapters that were already written never got
  it.**
  *Symptom:* raising the per-chapter ceiling from 2 to 6 gave chapter 9 five pictures,
  one per scene segment, exactly as designed. Chapters 1 to 8 stayed on two apiece
  against four, five and six settings, and would have stayed there for the life of the
  book. *Cause:* art direction was idempotent per **chapter** — `if chapter_num in
  queued_chapters(...): return 0`. That is the correct guard against paying for a
  chapter's art direction twice and the wrong resolution entirely for a chapter that is
  genuinely short, because the thing a ceiling bounds is segments. And nothing would
  ever have revisited them: a chapter is directed once, at acceptance, and the pass that
  sweeps every chapter does not run until the last one is written. *Fix:* the unit of
  "already done" is the segment. `queued_segments` answers the question at the
  resolution the answer lives at, `scenes_for_chapter` takes what is already queued and
  directs only the rest, and the illustrator daemon tops up one short chapter a cycle so
  the fix reaches prose that already exists rather than prose written after it. *The
  general lesson:* a config change is not deployed when the config is deployed. Anything
  derived from it and **persisted** — a queue entry, a plan, a cached decision — is a
  copy of the old value, and the question to ask of every tunable is not "what does this
  change from now on" but "what has already been written down from it".

- **2026-08-12 — a picture was skipped, and skipping was never an outcome anybody
  wanted.**
  *Symptom:* `ch05_1.png.skipped`, holding three real complaints: Dipper in the pine-tree
  cap the anchor had given to Wendy, Mabel's sweater lettered `MABEY`, a name badge
  reading `Pcition`. Three renders, three rejections, slot abandoned, book carries on
  with a hole in chapter 5. *Cause:* "images are best-effort" was written into this
  design at the start and never revisited after the prose half stopped being allowed to
  fail. The prose rule is that nothing is terminal; a chapter that will not come clean
  ships holding its defects and is come back to. A picture has no equivalent of shipping
  holding defects — a hole is a hole — so best-effort quietly meant the picture half kept
  the give-up the prose half had deleted. Worse, the retry loop *reset* each visit: three
  attempts down a simplification ladder, then a permanent marker, so the escalation could
  never continue past rung 2 no matter how long the run had. *Fix:* a slot is resolved by
  an image existing and by nothing else. A render that will not come out parks with the
  rung it reached and retries on a doubling backoff, the ladder resumes rather than
  restarting, and a new bottom rung asks for the room with nobody in it — which has no
  identity to get wrong and no crowd to merge, and is what makes "retry forever"
  terminate. Legacy `.skipped` markers are read as "tried, due now", so a run that gave
  up heals itself without anybody deleting files. *The general lesson:* the two halves of
  this pipeline had the same problem and only one of them got the answer. When a rule is
  worth stating as loudly as "nothing is terminal", the next question is which other
  subsystem is still quietly exempt from it.

## What a book consumes, and the levers that matter

Run the numbers rather than guessing — `python3 -m fanfic.cost`, `--presets` for the
levers side by side, `--measured` for the per-call figures and how stale they are.

**This section used to be a shopping guide**, and the shopping is over. It priced eleven
models across five vendors, solved for "which model brings a book in under $5", and
concluded — correctly, and usefully — that the earlier claim about needing local
inference was wrong. That work is done and the answer is settled: text is Claude Opus,
pictures come out of a browser session, and there is no vendor decision left to make.

**So there is no bill.** Prose and judgment run on the `claude` CLI's logged-in **seat**,
billed per seat rather than per token. Pictures are drawn through a signed-in browser and
cost nothing at all — they used to be the only real money this fleet moved, at about $3.94
a book, and that line item is now zero.

What is left is **allowance**, and it is worth measuring because it is finite and shared.
The mini's seat belongs to a person, an org ceiling has already stopped one run six
chapters in, and a book is days of it.

| Configuration | allowance consumed (list-price valuation) |
|---|---|
| Before one-shot roles (token arithmetic, unmeasured) | ~$464 |
| One-shot, Sonnet draft + Opus judge — MEASURED, the old two-tier build | ~$339 |
| **As deployed: one-shot, Opus everywhere** | **~$375, and modelled rather than measured** |

> **That last row is honest about being uncertain, and the uncertainty is new.** The
> measurements in `cost.MEASURED_USD` were taken under the two-tier split: `drafting`,
> `continuation` and `research` were metered on Sonnet, and every role is Opus now at
> 2.5x the rate. Silently reusing those figures would understate a book by exactly what
> the tier change cost, in the direction that flatters the decision — so those rows fall
> back to token arithmetic and are printed with a `~`. The arithmetic runs about 5x
> light (it cannot see the CLI's own system prompt, its tool definitions, or the model's
> reasoning tokens), so treat them as a floor and re-measure after the next full book.

Three things fall out.

**1. The transport dominates everything else.** A chapter draft is ~7,200 output tokens.
The agentic path spent **~227,000 input tokens** producing it, and the agentic editorial
pass ~363,000 — both back-solved from real metered calls. A turn-based provider re-sends
the whole conversation each turn, so a 25,000-token bible fetched on turn 3 is paid for
again on turns 4 through 60. Inlining the same content and demanding one write costs one
turn. That is ~10x on drafting and ~15x on editing **at the same model**.

This used to be described as something you bought by switching to an HTTP provider, which
was true and beside the point: it is a property of *how the prompt is written*, not of who
is on the other end. It is now the single largest lever in the project, by default,
because it is the only one left that moves the number by an order of magnitude.

**2. Editing is the bill, and the pass count is the knob.** This claim has flipped twice,
which is the part worth remembering. First it was "judgment is ~70%", from arithmetic that
counted only the digest and the artifact. Then measurement said writing was the larger
half, because every one of ~7 rounds bought a draft *and* a continuation *and* a critique.
Now a chapter is drafted **once** and edited two or three times, so writing is a fixed cost
per chapter and editing scales with `FANFIC_EDIT_MAX_PASSES`.

The lever moved with the loop, and the old advice — "drop the judge tier" — no longer
exists as an option. Two passes instead of three takes ~$67 off a projected book;
nothing else available is close.

**3. The picture knobs cost time now, not money.** `FANFIC_IMAGES_PER_CHAPTER` was once
the most expensive setting in the file, because it multiplied against chapter count. It is
a ceiling, and the real per-chapter cap is derived from the remaining render budget divided
by the chapters left — so the budget is the fixed quantity and the picture count bends to
it. About 300 renders a book however it is sliced.

What those renders now cost is **wall-clock**: eight seconds to two minutes each in a
browser, one at a time. Which is why `FANFIC_IMAGE_RENDER_BUDGET` (default `800`) still
exists as a hard per-series cap, counting every render rather than every keeper — a slot
that keeps failing burns renders, a book has hundreds of slots, and an unbounded fleet on a
bad night spends a day producing nothing.

**What it costs when it bites is time.** It is a runaway stop, not a per-book allowance: a
spent ceiling holds the book in ILLUSTRATING with every slot still queued, and raising it
resumes the run unattended. Set it where a whole book fits underneath — chapters × scene
segments, plus a sheet per cast member, plus a cover, times about two renders a slot. For a
48-chapter crossover at five segments a chapter with a cast of 54, that is ~300 slots and
~600 renders.

### What the vendor comparison was worth, and why it is gone

Keeping the receipt, because deleting the analysis should not delete what it taught:

- The comparison was **worth making once**. This module originally shipped with only the
  Anthropic prices filled in and everything else `None`, and concluded on that basis that a
  book under $5 "needs local inference, not a frontier model". The arithmetic was right and
  the conclusion was wrong, because the comparison had never been made — two hosted models
  cleared the ceiling comfortably. *Refusing to invent a number is right; declining to go
  and look one up is not the same thing.* That rule outlived the table it was learned on.
- It was **not worth maintaining**. What it never measured is the only thing that matters:
  whether a cheaper model writes prose the critics pass. The one time a role was actually
  moved down a tier on the strength of a price — `art_direction`, an obvious saving, four
  lines of JSON — it spent a run choosing image moments that could not be rendered, and
  every one of those slots came back empty. The saving bought blank pages.

## Known limits and honest caveats

- **Image consistency is mitigated, not solved.** The image model has no cross-request memory;
  reference sheets plus verbatim identity clauses plus vision critique make characters *recognisably*
  consistent, not pixel-identical. This is the ceiling of the cloud approach, chosen deliberately
  over local model-training to keep the mini free and avoid a LoRA-training pipeline.
- **A book that cannot draw waits instead of shipping.** No slot is ever written off, so "delivered"
  does guarantee "fully illustrated" — and the cost is the other way round: a picture nothing can
  render holds the book in ILLUSTRATING rather than costing it a page. The retry ladder is what keeps
  that from being a hang, and `state/series/<id>/book/<n>/images/*.retry` is where a parked slot says
  what it is stuck on and when it next tries.
- **Canon is only as good as the wikis.** Research caches cited wiki facts; a wrong or stale wiki
  becomes a wrong canon fact. Citations are kept so any dispute is traceable to a source.
- **"One night" is a target, not a guarantee.** Wall-clock depends on API latency, revision-loop
  depth, and how much the mini is yielding to the sibling fleets. The parallel pipeline (illustrate
  Book *N* while drafting Book *N+1*) is what makes it achievable, not assured.
- **Fully autonomous by choice.** There are no human approval gates; the critics are the safety
  net and `FAILED` parks anything that can't pass. That is the explicit trade for a hands-off
  overnight run.

---


# Operations manual

Everything above is the design. Everything below is how to actually run it on the mini, written so
a cold start needs nothing this file does not already contain.

The deterministic harness is built and green — **259 tests**, stdlib only. The live
model/image/launchd/iCloud path is the part that gets validated on the mini.

## Module map: what is actually built

One package, `fanfic/`, in dependency order. `prompts/` are code-adjacent but not code, and they are
the most important non-code artifacts in the project.

**Foundations** — no logic, no I/O, importable from anywhere.

| Module | Role |
|---|---|
| `fanfic/config.py` | Every tunable. All runtime paths root at `STATE_DIR`; nearly everything is env-overridable so a plist can change behaviour without touching code. |
| `fanfic/paths.py` | Every path in the state tree, including the scratch paths for proposals. Pure computation. |
| `fanfic/states.py` | The state vocabulary of the whole series→book→chapter machine, plus the sets the engine dispatches on (`ACTIVE_SERIES`, `RESUMABLE`, `TERMINAL`, `DEAD_ENDS`). Nothing is terminal but success. |
| `fanfic/errors.py` | The three failure classes: `RevisionNeeded` (revise), `QuotaExceeded` (defer), plain `RuntimeError` (stall and retry later). |
| `fanfic/jobspec.py` | Reading the dropped prompt: sections, source universes, implied entities, art direction. |
| `fanfic/status.py` | Renders the fleet's state as the phone-readable status document. A pure function of journal records. |
| `fanfic/cost.py` | What a book costs, computed from measured token volumes and a price table. `python3 -m fanfic.cost [--presets|--budget N]`. Pure arithmetic. |
| `fanfic/clock.py` | The operating window: whether the fleet may start work right now. Central Time derived from UTC, never from the host's local clock. Pure computation. |

**`fanfic/infra/`** — durable plumbing; knows nothing about novels.

| Module | Role |
|---|---|
| `log.py` | `logger(label)` → a timestamped sink that prints and mirrors to `state/<label>.log`. Stages take it as an argument rather than reaching for a global. |
| `journal.py` | Append-only JSONL journal; hierarchical keys; last-writer-wins replay; `first_incomplete_chapter`; `revive_series`; `recover_stale`; `decisions.log`. |
| `storage.py` | Atomic write / place (stage-then-`os.replace`, with an EXDEV fallback), JSON documents, content hashing, and the no-op delivery check. |
| `icloud.py` | Talking to a folder iCloud owns, always under a deadline: enumerate, spot evicted files and ask `brctl` for them back, refuse to read a prompt until it has settled, and publish the status file. |
| `locks.py` | One `flock` per daemon, so launchd can never run two copies over the same state. |
| `budget.py` | The hand-managed spend ceiling the engine checks before starting work. |

**`fanfic/memory/`** — the three-layer memory (hard problem 1).

| Module | Role |
|---|---|
| `bible.py` | Canon and series-bible schemas — cast, relationships, the foreshadowing ledger, the **interaction ledger**, the timeline, invented facts — and `merge_bible_update`, the structural gatekeeper that no proposal gets past. |
| `digest.py` | Builds the slice each model is shown: `build_chapter_digest` is the writer's focused per-chapter brief — the previous accepted chapter's real closing prose (not just its planned exit_state), every character's locked voice, and the character collisions this chapter owes. `build_ground_truth` is the editor's wider one: the whole cast, both ledgers, the timeline, and every invented fact, quoted inline. Pure functions of already-loaded state. |
| `store.py` | Loading the three layers off disk into one record. The reading used to be done three times in three stages, or delegated to the model by handing it a path. |

**`fanfic/gates/`** — the deterministic validators. No models, no I/O, no network.

| Module | Role |
|---|---|
| `coverage.py` | `check(canon, entities)` — the canon-coverage floor. |
| `structure.py` | `check(outline, seed_facts, min_chapters, interactions, meta_chapters, progressions)` — timeline monotonicity, setups/payoffs, orphans, contiguous numbering, fact dependencies, chapter titles, the chapter-count floor, the meta plan inherited unchanged, and every promised interaction and progression delivered by exactly one chapter. |
| `interactions.py` | `check(entries, cast_origins, universes)` — the meta plan's ledger: everyone used enough, no subset twice, group sizes varied, a real majority crossing universes, every pairing of worlds given a share. Pure counting. |
| `segments.py` | `split(prose)` / `check(prose)` — the scene breaks the writer marks, which are the unit for illustration choice and placement. |
| `readability.py` | `score(text)` — Flesch / Flesch–Kincaid against the Deathly Hallows band. |
| `length.py` | `check(words, floor)` — the absolute per-chapter word floor. No target and no ceiling; free, since the count is already computed by the readability pass. |

**`fanfic/providers/`** — the two external services. One each, named rather than registered.

| Module | Role |
|---|---|
| `base.py` | The `Capability` declaration, shared transient/quota classification, and the **delivery contract** — "write EXACTLY this path", plus the one-shot discipline that is the largest lever in the project. |
| `__init__.py` | `text()`, `image()`, and the **role table** (`role(name)`) — what each kind of work may spend. Also the argument, written down, for why the five-provider registry and the two model tiers were deleted. |
| `text_cli.py` | Claude via the `claude` CLI as a subprocess. Every text call in the fleet. |
| `image_browser.py` | Pictures, by driving `tools/gemini_art.js`. Turns the driver's `kind` into the exception the engine is written against, and applies the sanity floor — is this an image at all, before a Claude call is spent asking whether it is the *right* image. |

**`tools/`** — the browser half, in Node, with zero npm dependencies.

| File | Role |
|---|---|
| `gemini_art.js` | Launches Chrome on the signed-in profile, opens a fresh chat, uploads the reference sheets, sends the prompt, waits for the picture, downloads it. Prints one line of JSON. Every selector in it is a guess about somebody else's markup, so a failure dumps a screenshot and the page text. |

**`fanfic/models/`** — the two seams the stages call. Thin.

| Module | Role |
|---|---|
| `prompts.py` | `template(name)` reads a committed base prompt; `build(...)` composes base + THIS JOB block + the delivery contract the provider supplied. |
| `text.py` | `produce` / `produce_json` / `compose` + `run` — **the one seam for all prose and judgment.** Resolves the configured provider and role; stages name a role, never a model or a turn budget. |
| `images.py` | `generate(...)`, plus `unconfigured_reason()` — the check that holds a book rather than burning a render attempt against a signed-out browser profile. |

**`fanfic/stages/`** — one module per pipeline stage, in pipeline order:

| Module | Role |
|---|---|
| `research.py` | Mines the source wikis for cited canon, then freezes it. The one agentic stage. |
| `planning.py` | The series plan and the seeded bible: cast with origins, antagonists (the primary must be original), and a progression for every character. |
| `metaplan.py` | The chapter breakdown and the interaction ledger, built ten chapters a call and coverage-gated. Owns which chapter each character scene happens in. |
| `outlining.py` | A book's chapter list, expanded from the meta plan it may not renegotiate, plus the chapter each progression lands in and the costume variants that follow from it. |
| `drafting.py` | The chapter, written **once**, plus continuation passes if it stopped short. There is no rewrite path here and there must never be one again. |
| `editing.py` | The editorial pass: one call that finds every defect **and writes its exact repair**. Computes the deterministic gates first and hands them to the editor as facts rather than asking for opinions. |
| `patching.py` | Pure: applying find/replace edits, and refusing an ambiguous anchor rather than guessing. |
| `surgery.py` | Replacing one anchored passage with new prose, for the narrow class of defect where the fix is new prose rather than changed prose. |
| `bible_update.py` | The chapter's proposed ledger changes, validated and merged. |
| `illustration.py`, `binding.py`, `delivery.py` | Pictures, the `.epub`, and the atomic hand-off to iCloud. |

Each isolates its model call in one named seam that a test can replace — and every prose call funnels
through `drafting.generate` specifically, because a stage call that bypasses the stubbed seam goes
straight to the live API, which has happened twice in this project and both times was discovered by
the suite hanging on real requests. None of them writes the journal.

**`fanfic/engine/`** — the state machine.

| Module | Role |
|---|---|
| `admission.py` | Inbox → a series unit; revive on re-drop; filing a prompt away; `is_job_file`. |
| `series.py` | `PROMPT_DROPPED → … → SERIES_COMPLETE`, one step per call. |
| `book.py` | `QUEUED → … → COMPLETED`. Cannot fail: a stage that raises stalls the book instead. |
| `chapter.py` | The editorial loop: draft once → edit → edit → bible merge → place prose → journal. Every chapter lands. |
| `revising.py` | The per-book sweep over chapters that shipped holding defects, re-edited against the finished book. |
| `stalling.py` | `STALLED` and its doubling backoff — where a unit goes instead of being abandoned. |
| `illustrating.py` | Driving the image queue: paced, deferrable, parked-never-abandoned; and topping up chapters directed under a lower ceiling. |
| `cycle.py` | One turn: admit, budget-gate, advance one series, return a nap length. |

**`fanfic/daemons/`** — `scribe`, `illustrator`, `binder`. Thin: take the lock, loop,
call into `engine/`. `binder` drives books by calling `engine.book.advance`, the same function
`scribe` calls, so the two cannot disagree.

**Elsewhere:** `prompts/*.md` (the base prompts: research, series_plan, outline, draft, edit,
bible_merge, image); `launchd/` (4 plists, one shared `run.sh`, `startup.sh`); `tests/`.

## The test suite

445 fast tests, stdlib `unittest`, no network, no external binary. Every module also passes run on
its own, not merely in suite order — `tests/support.py`'s state redirect is a safety interlock, and
an import placed above it silently points the suite at the real state tree it then deletes from.
Run the whole thing from the repo root:

```
python3 -m unittest discover -s tests
```

Any single file also runs on its own (`python3 tests/test_gates.py`).

**Plus 18 opt-in browser tests**, which spawn a real headless Chrome and take ~70 seconds:

```
FANFIC_BROWSER_TESTS=1 python3 -m unittest discover -s tests
scripts/check-browser.sh          # the same battery, with the reason it exists
scripts/check-browser.sh --live   # three real renders against the signed-in session
```

The picture driver is the least testable thing in the project by construction: it drives somebody
else's web app over a session only a human can create. The temptation is to call it untestable and
ship it on one manual look — which would leave Chrome launch, the CDP plumbing, the
signed-in/signed-out state machine, prompt insertion, reference upload, the three download
fallbacks, the `kind`→exception contract and the sanity floor all unverified. **None of that is
Google-specific. Only the selectors are.** So `tests/fixtures/gemini_page.py` serves a page with the
same *shape* — same element roles, same account chip, same `model-response` container, same hidden
file input, same asynchronous think-then-image behaviour — and `GEMINI_ART_URL` points the driver at
it. `test_browser_driver.py` then runs the whole contract, including one class that goes all the way
through with **no mocks at all**: `models.images.generate` → the provider → a real Node process → a
real Chrome → the fixture → a file on disk.

They are opt-in because 70 seconds does not belong in a 5-second suite, and because a machine
without Chrome should not be failing tests about something it cannot run. That is a real trade — an
opt-in test is a test that does not run — so `scripts/check-browser.sh` is the documented thing to
run after touching the driver.

**What the fixture cannot prove** is that the selectors still match Google's markup — a fixture
written alongside the selectors will always agree with them. `tools/probe_selectors.js` asks the
real page instead, and needs **no account**: gemini.google.com serves signed-out visitors a working
composer, send button, response container and stop-generating control, so six of the eight selector
groups are verifiable by anyone. It reports which *arm* of each selector list matched, so a group
surviving only on its last fallback is visible before the rest rot away. `check-browser.sh` runs it
after the battery.

> It caught its own bug first, which is the useful kind of story. The probe reported `send` MISSING
> against an app where the selector was fine — because the send control only renders once the
> composer has content, and the probe was asking an empty page. A probe that cries wolf gets
> ignored, so it now puts the page into the state the driver puts it in before asking what is
> there. The live label, for the record, is `Send message`, and the upload menu is `Upload & tools`.

The two groups a guest cannot reach are the **file input** and a **generated image** — both need an
account, because guests are served Flash-Lite, which declines every picture. Hence `--live`, which
draws three real pictures — a plain one, one conditioned on a reference to prove the
upload path, and one through the Python seam — and then opens them, because whether the *art* is any
good is the one question no test can ask.

> One finding from building it, kept because it is the kind of thing a fixture is for. The first
> version filled its images with a flat colour, and a flat 1024×1536 PNG compresses to under 8 KB —
> below the sanity floor. The floor was not wrong; the fixture was easier than reality, and would
> have passed a test about "does a real render clear the floor" using a file nothing like a real
> render. The fixture emits noise now (~4.7 MB at full size, which is the right order of magnitude).

| File | Covers |
|---|---|
| `tests/support.py` | Not a test: redirects all state to temp dirs *before* `fanfic.config` is imported, and owns the model-seam stubs. One place for a stub signature to drift from a real seam, instead of five. |
| `test_jobspec.py` | Prompt parsing — universes, implied entities, art direction, plus a regression class pinning the real parked SWTOR prompt. |
| `test_infra.py` | Journal replay, torn-line tolerance, resume point, ordering; atomic write/place, no-op delivery, JSON. |
| `test_gates.py` | All three gates, asserting on the failure cases. |
| `test_memory.py` | The bible merge gatekeeper (every invariant) and the writer's digest. |
| `test_pipeline.py` | End to end: inbox prompt → delivered `.epub` through the real machine; idempotent re-run; text-only build; the prompt pack's locked identities. |
| `test_browser_driver.py` | **Opt-in.** The picture driver against a real Chrome and a fake Gemini: the happy path, waiting out generation rather than saving a half-drawn image, picking the biggest candidate, `blob:` download, reference upload, and every failure `kind` — including the guest session that must not be mistaken for a refusal. Plus the whole two-language seam with no mocks. |
| `tests/fixtures/gemini_page.py` | Not a test: a local page shaped like Gemini's, with a scenario per query string, so everything about the driver that is not Google's markup is testable. |
| `test_images.py` | The image backend with `subprocess` patched (every `kind`, reference passing, driver noise, the sanity floor); the no-give-up promise (quota defers, a failing render parks and the book waits, the ladder resumes at the rung it reached, a raised ceiling finishes the run); and art direction topping up chapters directed under a lower ceiling. |
| `test_editing.py` | The editorial loop, and the two properties the rebuild rests on. That repair is **anchored**: the named text changes and nothing else does, the chapter is drafted exactly once however many passes run, polish edits are applied even though they do not block, an unanchorable defect is recorded rather than silently dropped, and nested anchors apply longest-first. That **nothing quits**: a chapter that cannot be repaired still ships and does not stop its book, a repeatedly failing editor ships the draft it already has, a repeatedly failing writer stalls the book instead of failing it, and a journal holding legacy terminal statuses self-heals. Plus loop termination (it stops when it can repair nothing, keeps going while the count falls, and never runs past the hard ceiling), the deterministic gates reaching the editor as anchors, scene surgery refusing to shrink a scene or guess an ambiguous anchor, the revision sweep, the backoff arithmetic, and the interaction ledger end to end. |
| `test_patching.py` | The pure edit applier: a unique anchor replaced with nothing else moving, a missing anchor rejected rather than guessed, an ambiguous one refused outright, `""` as a deletion, and good edits landing even when a sibling is bad. |
| `test_revive.py` | Rewind-past-transient, re-drop revival, a parked chapter being un-parked with a fresh budget *and* actually drafting again, documentation in the inbox not being eaten, and `recover_stale` un-wedging a unit abandoned mid-stage. |
| `test_providers.py` | The swap seam: registry resolution and unknown-name errors, the role table (every `role=` a stage names exists; tool grants stay narrow), the per-provider delivery contract, capability refusal for research, and an HTTP provider still landing the artifact as a file with tokens metered. |
| `test_cost.py` | The cost model reproducing the metered run (~$500 agentic), single-shot being an order of magnitude cheaper at the same models, the judge tier dominating, unpriced models reported rather than guessed, and the budget solver. |
| `test_clock.py` | The operating window (both DST boundaries, the no-tzdata fallback agreeing with the tz database, weekends, window edges, no local-clock dependence) and the usage meter, including that its recorded field is named for what it measures. |
| `test_status.py` | The status document: every state rendered, liveness derived from the journal rather than the writer, unchanged writes skipped, a blocked write never breaking the cycle. |
| `test_icloud_inbox.py` | The synced drop folder: settle-before-read, empty and missing files, evicted jobs being requested back rather than ignored, and a missing `brctl` being patience instead of a crash. |

If `test_pipeline.py` passes on the mini, the harness wiring is intact and any remaining failure is
in a model seam, not the engine.

## Prerequisites on the mini

- **Clone location matters.** The plists hardcode `/Users/mikeyferguson/Developer/Fanfiction-Writer`.
  Clone there, or edit `ProgramArguments` in all three plists. `startup.sh` refuses to install from
  anywhere else rather than silently loading units that run nothing.
- **Python.** `launchd/run.sh` prefers a conda env at
  `/opt/homebrew/Caskroom/miniconda/base/envs/fanfic_env`, and falls back to the system `python3`.
  Nothing outside the standard library is imported, so the env is a convenience, not a requirement.
  Python 3.9+.
- **`claude` CLI, logged in.** Every text call in the fleet. Must honour the invocation in the
  model contract below, and its session must be able to reach `FANFIC_MODEL` (`claude-opus-5`).
- **Google Chrome and Node 22+**, if you want pictures. Both are checked before a render is
  attempted, and both are named by `providers.describe()` in the first two lines of every daemon
  log. Chrome is the standard macOS install; Node is `brew install node`. Nothing is installed from
  npm — the driver uses Node's built-in WebSocket and nothing else.
- **A signed-in Gemini profile**, once:

  ```bash
  scripts/gemini-login.sh
  ```

  This opens a visible Chrome on a profile of the fleet's own — **not** your everyday profile, so
  nothing here touches your bookmarks or your other logins, and the fleet cannot be logged out by
  something you do in your own browser. Sign in, ask it for one picture to prove the app really
  works, close the window. The script then runs a test render to confirm before it exits.

  That directory (`~/.config/fanfic/chrome-gemini`) **is the credential.** There is no API key
  anywhere in this project. Re-run the script whenever renders start reporting "not signed in" —
  Google expires a session eventually, and re-signing in is the entire fix. Until you do, books
  hold in ILLUSTRATING with every slot queued; nothing is skipped and nothing is lost.

  Note that a signed-out profile does **not** produce an obvious error on its own: Gemini serves
  guests a working chat on a cut-down model that answers text and declines every picture. The
  driver checks for the account rather than the composer precisely because of this.

  To skip images entirely and still get a real book, set `FANFIC_IMAGES_ENABLED=0`.
- **No pandoc, no `codex`.** The epub is built in pure Python; `codex` is not used.
- **git remote.** `run.sh` does `git pull --ff-only` on every (re)launch, so pushing to the deployed
  branch is the deploy. Make sure the clone tracks it.
- **iCloud.** `~/Library/Mobile Documents/com~apple~CloudDocs/Books` must exist and be signed in,
  and it holds the drop folder `_inbox/` (with `finished/` and `failed/` under it). `brctl` at
  `/usr/bin/brctl` pulls back evicted prompts; it ships with macOS, and its absence degrades to
  patience rather than failure. Keep the mini awake and logged in — GUI-domain launchd agents pause
  when it sleeps, and a sleeping mini writes no novels.

## Install and operate the fleet

- **Sign the picture session in, once:** `scripts/gemini-login.sh`. Nothing else needs a
  credential. See Prerequisites for what this does and why it is a browser profile rather than a
  key.
- **Install / reinstall:** run `launchd/startup.sh`. It copies each plist into
  `~/Library/LaunchAgents`, boots out any prior copy, bootstraps and enables all three units into the
  GUI launchd domain, and makes the launcher executable. Idempotent — re-run it after editing any
  plist to reload.
- **The three units:** `scribe` (self-looper, the engine), `illustrator` (self-looper, low-priority
  parallel image worker), `binder` (one-shot every 5 min). All three
  run `launchd/run.sh <unit>`, which self-updates and then execs `python3 -m fanfic.daemons.<unit>`.
  **`scribe` alone is sufficient for correctness** — it drains the image queue and binds and delivers
  itself. The other two only add throughput.
- **Submit a job, from anywhere:** fill a copy of `PROMPT_TEMPLATE.md` and save it as a single
  `.md` file in the iCloud drop folder,
  `~/Library/Mobile Documents/com~apple~CloudDocs/Books/_inbox/`. On a phone that is
  **Files → iCloud Drive → Books → _inbox**. The filename, slugified, becomes the series id.
  `scribe` admits it on the next cycle, once it has settled for `FANFIC_INBOX_SETTLE_SEC`. A copy of
  the template and a short how-to live in that folder as `_TEMPLATE.md` and `_README.md`; both are
  `_`-prefixed, so admission ignores them.
- **A finished job** moves its prompt to `_inbox/finished/`; a failed one to `_inbox/failed/`.
  Neither is re-scanned. No job input or output lives in the repo at all.
- **Retry a failed job:** move its prompt from `_inbox/failed/` back up into `_inbox/` — which you
  can do from the phone. The engine **revives** the series — rewinds it to its last resumable state,
  error cleared — rather than restarting it, so frozen canon, the plan, outlines, accepted chapters,
  merged bible facts, locked sheets, and accepted images are all kept. A **parked chapter is
  un-parked too**, with a fresh revision budget: a re-drop only ever happens because a person moved
  a file, so it is a human decision, not an auto-retry loop, and the engine honours it. The park
  reason is in `decisions.log` so you can decide whether it is worth the spend before you do.
- **Watch it from the phone: `_STATUS.md`.** The fleet rewrites this file in the drop folder every
  cycle, and the `binder` one-shot refreshes it every five minutes as well — so it stays current even
  while scribe is inside a forty-minute model call. It names the current stage, chapter progress
  (`12 of 45 chapters written`), the reason for any stop, and what to do about it.

  Its liveness figure is deliberately **derived from journal timestamps, not from when the file was
  written**. Any daemon can publish it, so a "last written" heartbeat would tick along happily while
  the engine was hung — the exact silent failure this project has already been bitten by. What it
  says is "engine last wrote to its journal 4.0 hours ago", which cannot lie in that direction. A
  long quiet gap is *explained* rather than alarming, because research and each chapter draft are
  single blocking calls that journal nothing while they run.
- The delivered `.epub` also appears under `Books/<fandom>/<series>/`, so the folder answers the
  three questions that matter without touching the mini: still working, stopped, or done.
- **Commit and push your work:** `scripts/save-and-push.sh "what changed"`. It stages everything,
  commits under `git config user.name`, and pushes. `run.sh` does a `git pull --ff-only` on every
  daemon (re)launch, so pushing to the deployed branch **is** the deploy.

  The commit carries **no trailers, no co-authors, and no attribution to any assistant**, and that
  is enforced by `.githooks/commit-msg` rather than requested politely. Assistants are instructed by
  their own harnesses to sign commits with a `Co-Authored-By` line naming the model, and GitHub
  counts a co-author as a contributor — so the graph on a repository the owner wrote ends up listing
  a language model. Asking an assistant not to is a rule it has to choose to follow; the hook is a
  rule git enforces. It *edits* the message rather than rejecting it, because a stripped trailer
  should never cost anybody a commit, and a hook that blocks is a hook people bypass with
  `--no-verify`. `save-and-push.sh` sets `core.hooksPath` on first run so a fresh clone is covered
  without anyone remembering. This is lifted directly from the `~/Learning` repos, which solved it
  first.
- **Expect drop latency, and expect queueing.** The engine advances one unit per cycle and a stage is
  a single blocking model call, so a new prompt is noticed only *between* cycles — during a research
  call or a chapter draft that can be tens of minutes. And a second novel dropped while one is
  running does not run in parallel: series are advanced oldest-first, so it sits at `prompt_dropped`
  until the first finishes. Both are the budget-gating design working as intended, not a fault, but
  neither is obvious from the phone, where nothing appears to happen.
- **Run a daemon by hand** (for a bring-up or a one-off): `python3 -m fanfic.daemons.scribe` from the
  repo root. It takes the same lock as the launchd unit, so the two will not collide — but that also
  means a stray hand-run process will make the launchd one exit immediately. Check with
  `ps aux | grep fanfic.daemons` before wondering why nothing is happening.

## Configuration reference (every env override)

Defaults live in `fanfic/config.py`; each of these can be overridden by an environment variable.

**To make one stick, put it in `launchd/fleet.env`.** `run.sh` sources that file with `set -a`
before starting any daemon, so all three units share one answer and a change is one edit plus
a fleet restart. It is also where the deployed configuration explains *itself* — what it runs on
and why that is the choice it is. Prefer it to the plists' `EnvironmentVariables` dicts, which are
three places to disagree.

Redirecting `FANFIC_STATE_DIR` is what lets the whole system run against a scratch tree.

| Env var | Default | Purpose |
|---|---|---|
| `FANFIC_STATE_DIR` | `<repo>/state` | Root of all runtime state (journal, canon, series, tmp, locks, logs). |
| `FANFIC_INBOX_DIR` | `<Books>/_inbox` | Drop folder scanned for new jobs. In iCloud by default, so a phone can drive the fleet. |
| `FANFIC_STATUS_FILE` | `_STATUS.md` | Name of the status document written into the drop folder. Empty string turns it off. |
| `FANFIC_SCAN_TIMEOUT_SEC` | `15` | Deadline on any drop-folder read or write. |
| `FANFIC_SCAN_BACKOFF_SEC` | `300` | How long to stop touching the drop folder after a timeout. |
| `FANFIC_INBOX_SETTLE_SEC` | `10` | A prompt must be unchanged this long before it is admitted (guards against a partial write or a partial iCloud sync). |
| `FANFIC_BOOKS_DIR` | `~/…/CloudDocs/Books` | iCloud delivery target, and the parent of the drop folder. |
| `FANFIC_MODEL` | `claude-opus-5` | **The model. Every text call in the fleet.** There are no tiers and no per-role overrides; see "Why there are no model tiers". |
| `FANFIC_CLI_BIN` | `claude` | Binary the text provider drives (`FANFIC_CLAUDE_BIN` still honoured). |
| `FANFIC_DIGEST_PREV_TAIL_WORDS` | `400` | Words of the previous accepted chapter's closing prose put into the next chapter's brief. |
| `FANFIC_IMAGES_ENABLED` | `1` | `0` builds a deliberate, logged text-only book. |
| `FANFIC_GEMINI_PROFILE_DIR` | `~/.config/fanfic/chrome-gemini` | **The Chrome profile holding the signed-in Gemini session. This directory is the credential** — there is no API key. Created by `scripts/gemini-login.sh`. Absent ⇒ books hold in ILLUSTRATING and the log names the script. |
| `FANFIC_CHROME_BIN` | `/Applications/Google Chrome.app/…` | The browser the driver launches. |
| `FANFIC_NODE_BIN` | `node` | Node 22+, for `tools/gemini_art.js`. No npm packages are used. |
| `FANFIC_IMAGE_HEADFUL` | `0` | `1` renders in a visible window. The only practical way to debug a selector Google has moved. |
| `FANFIC_IMAGE_DIAG_DIR` | `<state>/image-diagnostics` | A failed render dumps a screenshot and the page text here. Set it to the **empty string** to turn dumps off — this is the one tunable where "off" is a real choice rather than the absence of one, so it does not follow the usual "empty means unset" rule. |
| `FANFIC_IMAGE_RENDER_TIMEOUT_SEC` | `420` | Wall-clock for one render inside the browser. Generous on purpose: a picture takes 8s to 2min depending on what the account is queued behind. |
| `FANFIC_IMAGE_MAX_UPLOADS` | `6` | Reference pictures attached to one render. They compete for a fixed budget of attention, and uploading is slower than an API part was. |
| `FANFIC_IMAGE_MIN_BYTES` / `FANFIC_IMAGE_MIN_EDGE` | `20000` / `512` | The sanity floor: what a download must clear to count as art at all. A web page can hand you a spinner, and a spinner is `<img>`-shaped. |
| `FANFIC_IMAGE_ASPECT_PORTRAIT` / `_LANDSCAPE` | `2:3` / `3:2` | Requested aspect per scene orientation — asked for in words now, since a chat window has no aspect parameter. |
| `FANFIC_IMAGE_STYLE` | (cel-shaded anime block) | **Fallback** art-style block, used only when a job's prompt has no `## Illustrations` style of its own. |
| `FANFIC_IMAGES_PER_CHAPTER` | `6` | **Ceiling**, not a count. A chapter gets one picture per scene segment; the real per-chapter cap is derived from remaining render budget ÷ chapters left. |
| `FANFIC_CHAPTER_MIN_SEGMENTS` | `2` | A chapter must mark its changes of place and time. Blocks. |
| `FANFIC_IMAGE_RENDER_BUDGET` | `800` | Hard per-series ceiling on **renders** — a runaway stop, not a wallet; the pictures are free and cost wall-clock. Exhaustion *holds* the book with its slots queued; it never skips a picture and never fails a book. Set it above a whole book's worth. Empty disables. |
| `FANFIC_DRAFT_MAX_CONTINUATIONS` | `2` | Continuation passes allowed to grow a short first draft. One completion produces ~2,700 words against a 5,351 target. |
| `FANFIC_CHAPTER_MIN_WORDS` | `3000` | Absolute length floor in words. Blocks. There is no ceiling. |
| `FANFIC_BOOK_MIN_WORDS` | `150000` | Floor on a book, so a novel is not delivered as a novella. |
| `FANFIC_MIN_CHAPTERS` | `32` | Floor on chapter count. The outliner picks the actual number. |
| `FANFIC_CHAPTER_MAX_LENGTH_RATIO` | `1.45` | Above this a chapter is flagged advisory, never blocked. |
| `FANFIC_IMAGES_PER_CYCLE` | `4` | Renders per ILLUSTRATING cycle, then yield. |
| `FANFIC_IMAGE_QUOTA_BACKOFF_SEC` | `120` | Nap after Gemini rate-limits the browser session. A throttled account just means pictures trickle in; writing never waits, because writing is a different service entirely. |
| `FANFIC_MODEL_QUOTA_BACKOFF_SEC` | `300` | Nap after the *model* backend reports any allowance ceiling, then retry — forever. Never a failure. |
| `FANFIC_QUIET_HOURS` | `1` | Observe the working-hours pause. `0` runs around the clock. |
| `FANFIC_QUIET_START_HOUR` / `_END_HOUR` | `9` / `17` | The daily no-work window, in **US Central**, derived from UTC and never from the host clock. |
| `FANFIC_QUIET_DAYS` | `0,1,2,3,4` | Weekdays the window applies to, Monday=0. Weekends run freely. |
| `FANFIC_QUIET_RECHECK_SEC` | `600` | Longest nap while paused, so the status file stays fresh. |
| `FANFIC_GATE_MAX_ATTEMPTS` | `3` | How many times planning/outlining may re-propose after a deterministic gate rejects them, with the validator's errors handed back. |
| `FANFIC_BUDGET_FILE` | `~/.config/fanfic/budget.json` | If present, `{"remaining_usd": N}`; the engine idles when ≤ 0. Absent ⇒ unlimited. |

Other tunables worth knowing, edited in `fanfic/config.py` rather than the environment: the
readability band (`READABILITY_FK_GRADE_MIN`/`MAX`, `READABILITY_FLESCH_EASE_MIN`),
`CANON_COVERAGE_MIN` (0.85), `DIGEST_PREV_TAIL_WORDS` (400),
`CHAPTER_STAGE_ERROR_RETRIES` (3), `IMAGE_MAX_REGENERATIONS` (3), the transient-retry cap and
backoff, and `TRANSIENT_SIGNATURES`.

**The editorial loop and the stall backoff**, all env-overridable:

| Variable | Default | What it does |
|---|---|---|
| `FANFIC_EDIT_MAX_PASSES` | `3` | Editorial passes a chapter gets by default. Pass 1 finds and repairs; pass 2 verifies pass 1's own edits against the whole chapter; pass 3 is slack. Beyond that a pass buys a fresh set of opinions about prose that is no longer defective. |
| `FANFIC_EDIT_HARD_MAX_PASSES` | `6` | A chapter still shedding defects at the soft cap keeps going to here. Cast size is what drives this in a crossover — a twelve-hander needs longer than a two-hander, and a fixed count cannot tell the difference. |
| `FANFIC_EDIT_STALL_PASSES` | `2` | Consecutive passes that may fail to beat the best count before the chapter is judged to have stopped improving. |
| `FANFIC_EDIT_LONG_SENTENCES` | `15` | How many of a chapter's longest sentences are quoted to the editor when the readability gate fails, turning an un-anchorable score into anchored edits. |
| `FANFIC_SURGERY_MAX_PER_PASS` | `2` | Passages one pass may replace wholesale. Surgery is the only mechanism that generates prose no editor has seen, so it is rationed. |
| `FANFIC_SURGERY_MIN_RATIO` | `0.6` | A replacement shorter than this fraction of what it replaces is refused — that is the writer summarising instead of dramatising. |
| `FANFIC_REVISION_SWEEPS` | `2` | Times the book's REVISING sweep may revisit a chapter that shipped holding defects. |
| `FANFIC_DRAFT_RESUME_MIN_WORDS` | `500` | A draft on disk this long for a chapter the journal says is mid-flight is reused rather than re-rolled. |
| `FANFIC_META_INTERACTIONS_MIN` / `_MAX` | `4` / `5` | Character collisions per chapter — one per scene segment. |
| `FANFIC_META_CHUNK_CHAPTERS` | `10` | How many chapters one meta-plan call produces. |
| `FANFIC_PLAN_MIN_APPEARANCES` | `6` | Fewest interactions a character may appear in across the book. |
| `FANFIC_META_CROSS_UNIVERSE_SHARE` | `0.60` | Fraction of collisions that must cross universes. |
| `FANFIC_META_MIN_PAIRING_SHARE` | `0.04` | Fraction each pairing of source worlds must get. |
| `FANFIC_META_MIN_PHYSICAL_SHARE` | `0.30` | Fraction of collisions that must be `physical` across the whole book. |
| `FANFIC_META_FRONT_PHYSICAL_SHARE` | `0.20` | The same floor over the front half — this is what buys action early. |
| `FANFIC_META_BACK_PHYSICAL_SHARE` | `0.45` | And over the back half — this is what buys escalation. |
| `FANFIC_META_REGISTER_CEILING` | `0.50` | No single register may exceed this share. 200 fights is as broken as 200 conversations. |
| `FANFIC_IMAGE_MAX_CHARACTERS` | `6` | Named characters a single illustration may contain. |
| `FANFIC_IMAGE_REFERENCE_CHARACTERS` | `2` | How many of them get the full reference set; the rest are anchored by their locked sheet alone. Raising it makes every face in the frame worse, not one of them better. |
| `FANFIC_REF_IMAGES` | `4` | Source pictures fetched and kept per character. |
| `FANFIC_REF_IMAGES_PER_RENDER` | `2` | How many of those accompany one render. |
| `FANFIC_STALL_BACKOFF_BASE_SEC` | `300` | First retry wait for a stalled unit. |
| `FANFIC_STALL_BACKOFF_MAX_SEC` | `3600` | Ceiling on the doubling wait. |

**Verify the model id first.** `claude-opus-5` is what every role runs on; if the installed CLI
names it differently, set `FANFIC_MODEL` in `launchd/fleet.env` rather than editing code.

## The model contract (what the fleet calls out to)

`fanfic/models/` is the only place an external model is reached, and it always reads a **file** the
model was told to write — never stdout.

- **`prompts.build`** composes every runtime prompt: the committed base template, a `THIS JOB` block
  of facts, and the instruction naming the exact output path. One shape for every stage, because
  slightly different wording per stage is exactly how one stage ends up mysteriously less reliable
  than the others.
- **`text.produce`** invokes the CLI headless with `-p`, `--output-format json`,
  `--dangerously-skip-permissions`, the role's `--allowedTools` list, `--max-turns`, and `--model`.
  A run that exits 0 but wrote no file is treated as a cut stream and retried. `produce_json` adds
  parsing, and turns "wrote the file but filled it with prose" into a normal proposal failure rather
  than a bare `JSONDecodeError`.
- **Transient vs deterministic** is a substring match against `config.TRANSIENT_SIGNATURES`. A
  transient failure retries with backoff up to `TRANSIENT_MAX_ATTEMPTS`; a deterministic one raises
  immediately. Getting this wrong is expensive in one direction only — see the 2026-08-04
  connection-closed story — so **add signatures freely**
  A failure whose message is **empty** is retried rather than classified, and a non-zero exit whose
  envelope has no `result` text is reported from its `subtype` / `terminal_reason` instead of
  rendering as silence — both paid for on 2026-08-05.
  And a non-zero exit caused by **turn exhaustion** that nonetheless left the artifact on disk
  returns the artifact: the file is the contract, and checking the exit code first was how that
  principle got quietly reversed.
- **`images.generate`** runs `tools/gemini_art.js`, which launches Chrome on the signed-in profile,
  opens a **fresh chat** (so no previous picture is in context to be averaged into this one),
  uploads the locked reference sheets as real attachments, sends the prompt, waits for the render,
  and downloads it. The driver prints one line of JSON whose `kind` field is the entire contract
  between the two languages, and each value has to land on the exception the engine above is written
  against:

  | `kind` | becomes | what it does to the book |
  |---|---|---|
  | *(success)* | — | an image on disk, once it clears the sanity floor |
  | `quota` | `QuotaExceeded` | the slot is deferred and retried; a picture never blocks a book |
  | `not_signed_in`, `setup` | `NotSignedIn` | the book **holds** with its queue intact; a human runs one script |
  | `refused` | `RuntimeError` | this wording will not render — drop a rung down the simplification ladder |
  | `transient` | `RuntimeError` | the same, and the diagnostics dump says what the page looked like |

  `NotSignedIn` is a `RuntimeError` subclass so nothing downstream leaks it as a cycle crash, and
  the render sites re-raise it alongside `QuotaExceeded` rather than catching it — neither is a
  defect in *this* prompt, so neither may consume a rung of the ladder.

  Getting the bytes is three fallbacks deep, because a picture visible on screen that could not be
  saved is the most annoying possible failure: an in-page `fetch` (works for `blob:` and same-origin,
  and inherits the session cookies), then Chrome's own copy of the resource via
  `Page.getResourceContent` (survives a cross-origin CDN with no CORS header), then a plain Node
  fetch with the session's cookies attached.

Every stage's model call is a named function seam, so a failing stage points at exactly one
function, and `tests/support.py` replaces all of them at once.

## Watching a run: logs, journal, decisions

- **launchd logs:** `~/Library/Logs/FanfictionScribe.log` / `.err`, and the matching
  `FanfictionIllustrator`, `FanfictionBinder` files. Each daemon also mirrors
  its own output to `state/<daemon>.log` — so `state/scribe.log`, `state/illustrator.log`, and so on,
  which survives launchd rotating its logs.
- **The journal, `state/journal.jsonl`, is the source of truth.** Each line is one unit's full
  snapshot; the **last** line for a given `key` wins. Keys are hierarchical: `series/<id>`,
  `series/<id>/book/<n>`, `series/<id>/book/<n>/chapter/<n>`. To see where anything is, read the last
  line for its key. Crash-resume is just replaying this file and continuing from the first
  non-terminal unit; drafting resumes at the first chapter not yet `bible_merged`.
- **`state/decisions.log`** is the human-readable audit: every model call, every critique verdict
  with its actual readability numbers, every revive, and every failure reason, timestamped and keyed.
  **This is the first place to look when a unit parks** — the reason is written there verbatim.
- **Artifacts land under `state/series/<id>/`:** `plan.json`, `series_bible.json`, and per book
  `book/<n>/` holding `outline.json`, `book_bible.json`, `image_prompts.md` (the reviewable prompt
  pack), `chapters/chNN.md` (accepted prose), `sheets/<char>.png` (locked reference sheets),
  `images/chNN_k.png` and `images/cover.png` (accepted images), any `*.png.retry` sidecars naming
  what a parked slot is stuck on and when it next tries, and the built `<slug>.epub`. Canon is under
  `state/canon/<universe>/canon.json`, frozen after research.

## Troubleshooting and recovery

| Symptom (in journal / decisions.log) | Cause | What to do |
|---|---|---|
| Series `STALLED` at research, "coverage X% below 85%" | Canon genuinely didn't cover the prompt's implied entities — or the entity list contains something canon would never say. | Read the `missing` list in the error. If those names look real and canon plainly discusses them under shorter names, that is a gate bug, not a research failure (see the failure stories). If they are prose fragments, add them to `jobspec._STOP`. Re-drop to revive; frozen canon is reused, so the retry is seconds rather than another dig. |
| `_STATUS.md` says the engine last journaled hours ago | Either it is inside one long model call, or it is wedged. | The status file names the stage and what is normal for it. If the stage is `researching` and the gap exceeds ~45 min, or a chapter draft exceeds ~30 min, it is wedged: restart `scribe` and `recover_stale` will rewind it. |
| Series `STALLED` with a `claude exited 1` network message | A mid-stream blip whose wording isn't in `TRANSIENT_SIGNATURES`, so it was misread as a bad proposal. | Add the signature to `config.TRANSIENT_SIGNATURES`, then re-drop the prompt to revive and resume. This is a *config* bug, not a story bug. |
| Series `STALLED` at planning/outlining, "invalid plan / structure gate failed" | The proposal violated a structural invariant (missing book role, non-monotonic timeline, orphaned thread, payoff without setup). | The exact failing rule is in the error string. A re-drop usually fixes it; a persistent failure means the prompt is under-specified or a prompt template needs tightening. |
| Chapter ships "ACCEPTED holding N issue(s)" | Its editorial budget ran out with defects still in it, so it shipped with them recorded rather than stopping the book. | Usually nothing: the book's REVISING sweep revisits it against the finished book, which is when most of these resolve. `decisions.log` lists every outstanding issue in full. If the same chapter survives both sweeps still holding a **CANON** issue, that is worth reading — canon is the one thing this project exists to protect. |
| Log says "editor could not anchor any repair" | The editor named defects and could not express any of them as a find/replace against the text. | Read the pass in `decisions.log`. Almost always the defect is genuinely structural (a scene that does not exist) and the editor should have used `structural` — if it recurs, that is a prompt fix in `prompts/edit.md`, not a loop fix. |
| Many edits "rejected" in a pass | The editor's anchors did not match the chapter character-for-character, or matched twice. | Rejection is the safe outcome — the alternative is guessing and silently corrupting prose that was fine. A high rejection rate across several chapters means the provider is mangling whitespace or smart quotes in the artifact; check the raw `state/tmp/edit_*.json`. |
| A book goes `STALLED` | A stage raised something the engine could not get past. Nothing has been discarded. | Read `error` on the record and the `STALLED` block in `decisions.log`. It retries by itself on a doubling wait, so the only reason to act is if the cause is something you can fix — fix it, and either wait or re-drop the prompt to retry immediately with the backoff reset. |
| Chapter logs "draft stage error N times" | Not a writing failure: the draft file kept failing to arrive (cut stream, provider died). | `decisions.log` has each error verbatim. If it is a network wording, add it to `TRANSIENT_SIGNATURES`. The book stalls and retries on its own. |
| Stage errors "claude binary not found" | The CLI isn't on the PATH the daemon sees. | Fix `PATH` in the unit's plist `EnvironmentVariables`, or set `FANFIC_CLAUDE_BIN` to the explicit path. |
| Log says "pictures on hold — no signed-in Chrome profile" | The browser session does not exist yet, or Google expired it. | Run `scripts/gemini-login.sh`, sign in, close the window. The book resumes by itself with every slot still queued — nothing was skipped and nothing needs re-dropping. Or set `FANFIC_IMAGES_ENABLED=0` to build text-only. |
| Every render comes back "Gemini declined to draw this prompt" | Most likely the profile is signed **out**, not a content refusal: a guest session gets a working chat that answers text and declines every picture. The driver reclassifies this when it can. | Run `scripts/gemini-login.sh`. If the profile really is signed in, read the dump in `state/image-diagnostics/` — it has the screenshot and the page text. |
| Renders time out with "no image after 420s" | Usually a selector Google has moved; occasionally an account queued behind a long job. | Watch one happen: `GEMINI_ART_HEADFUL=1 node tools/gemini_art.js --out /tmp/x.png --prompt 'a red circle'`. The dumps in `state/image-diagnostics/` show what the page looked like when it gave up. |
| Log says "the browser saved something that is not usable art" | The download passed as an `<img>` but failed the sanity floor — a spinner, a placeholder, or a 404 body. | Nothing, usually: the slot retries a rung plainer. If every render says it, the driver is picking the wrong image off the page; check a diagnostic screenshot. |
| "Chrome devtools did not start" / "a profile can only be open once" | Something else has the fleet's Chrome profile open — often a `gemini-login.sh` window still sitting there. | Close it. `pgrep -f chrome-gemini` finds the holder. |
| Log says "Gemini is rate-limiting this session" | The account has hit its own picture limit for now. | Nothing. Writing is unaffected — it is a different service on a different account — the book stays in `ILLUSTRATING`, and pictures resume when the limit lifts. |
| A book sits in `illustrating` and the count is not moving | One or more slots are parked, or the render ceiling is spent. | Read the `*.png.retry` sidecars in `images/`: each names what the render or the critic objected to and when it next tries. A spent ceiling says so in `illustrator.log` — raise `FANFIC_IMAGE_RENDER_BUDGET`, restart the fleet, and it finishes by itself. Nothing needs re-dropping and nothing has been lost. |
| Engine logs "API budget exhausted; idling" | `budget.json` says `remaining_usd ≤ 0`. | Raise it or delete the file. |
| Log says "MODEL spend/quota ceiling reached; nothing parked" | The `claude` CLI reported any allowance ceiling — session, five-hour, weekly, or monthly spend. | Nothing in the repo fixes this — raise the org limit (`/usage-credits` asks your admin) or wait for the billing period to roll over. **Nothing is parked and no work is lost**: the engine re-checks every `MODEL_QUOTA_BACKOFF_SEC` and the run resumes on its own, with no re-drop. |
| "Another scribe instance holds the lock; exiting" | A second copy started while one runs. | Normal launchd behaviour — but check `ps aux \| grep fanfic.daemons` for a stray hand-run process holding `state/locks/scribe.lock`. |
| A prompt dropped from the phone is not picked up | Most likely the engine is mid-stage: a research call or chapter draft blocks the cycle for tens of minutes, and admission only runs between cycles. Otherwise it has not settled, or iCloud has not delivered it. | Wait for the current stage to end. Check the file is non-empty on the mini and that no `.<name>.md.icloud` stub sits beside it. |
| A second novel dropped while one is running never starts | By design: series advance oldest-first, one unit per cycle. | Nothing. It starts when the first completes. |
| The scribe log says the drop folder "did not respond within 15s" | macOS privacy protection is denying directory enumeration to a launchd agent — and the Homebrew Python blocks on it rather than erroring. | Grant Full Disk Access to the Python that `launchd/run.sh` execs (System Settings → Privacy & Security → Full Disk Access). Until then the running job is unaffected; only new drops are invisible. |
| A job is definitely in the drop folder but the mini cannot see it | iCloud evicted its contents; the real name is replaced by a `.<name>.md.icloud` stub, which a `*.md` glob cannot see. | Nothing — admission requests it back via `brctl download` each cycle and admits it once materialised. The scribe log records the request. |
| A unit sits in `researching` / `binding` / `delivering` and never moves | It was abandoned mid-stage (kill, crash, power cut) and those statuses have no handler. | Restart `scribe`; `recover_stale` rewinds it at startup and logs `RECOVERED`. It should never need doing by hand. |
| A file you put in the drop folder vanished | Anything ending `.md` that isn't `README.md` or `_`-prefixed is a **job**. It was admitted, it failed, and it was filed into `_inbox/failed/`. | Move it back out. Prefix scratch files with `_`. |
| Something behaves like the old code after a reorganisation | A long-running daemon holds its modules in memory and does not notice files moving under it. | `launchctl kickstart -k gui/$(id -u)/com.mikeyferguson.scribe`, or kill a hand-run process and restart it. |

## Deviations and gaps in the current build

Stated plainly so nothing surprises you at 2 a.m.:

- **epub is pure Python, not pandoc.** `stages/binding.py` assembles a standards-shaped epub3 zip and
  validates it (mimetype stored-and-first, container resolves, every manifest item embedded, every
  spine item present) before placing it. Chosen so binding is deterministic and testable with no
  external binary. If you want pandoc's typography, `build_epub` is the one seam to replace; the
  validator stays.
- **Markdown→XHTML in binding is minimal** (blank-line-separated paragraphs). The drafting prompt
  constrains output to plain prose, so that is sufficient; if chapters start using richer Markdown,
  `binding._md_to_xhtml_body` needs to grow.
- **`codex` is gone.** The design's original image path did not exist. See the failure stories.
- **The browser picture path has been proven end-to-end against a signed-OUT session only.** The
  driver launches headless Chrome, loads the app, submits a prompt, reads the reply, classifies the
  outcome, and dumps diagnostics — all confirmed live. What has *not* been run here is a render on a
  signed-in account, because signing in requires the account holder. So treat the upload of
  reference sheets and the download of a finished picture as **bring-up rather than proven**: the
  selectors for the composer, the send button and the file input are educated guesses about markup
  that Google reships constantly.

  This is the intended first move after `scripts/gemini-login.sh`:

  ```bash
  GEMINI_ART_HEADFUL=1 node tools/gemini_art.js \
      --out /tmp/probe.png --prompt "a red fox in a snowy forest, painterly"
  ```

  Watch it work. If a selector has moved, the failing probe is named in the JSON and the page is
  dumped to `state/image-diagnostics/`, and the fix is a selector list in `gemini_art.js` — every
  probe in that file already tries several, precisely so this is an edit rather than a rewrite.
- **Canon grows; it is not immutable.** Canon is keyed on the *universe*, so every job
  naming the same source shares one file — worth 15-40 minutes a book, and the reason a
  multi-book programme in one universe mines its wikis once. It used to be frozen
  absolutely, which was a trap: the coverage gate still ran against each new job's cast,
  so a second book with a different cast parked at 0% with an error saying "research"
  and a cause three steps away in "the freeze". A frozen canon that does not cover a new
  prompt is now **topped up for exactly the entities it is missing** and merged back,
  under fresh fact ids. One top-up per universe per job, so a genuinely uncoverable
  entity costs one call and then parks rather than looping.
- **`doctor` is not built.** The deferred, never-destructive audit unit — re-open finished books,
  confirm the epub is valid, images are present, and no late continuity drift slipped past the
  per-chapter gates — remains deferred until the core pipeline is proven on the mini, the same way
  `media_doctor` was a later addition to Torrent-Ingest.
- **The live path has never completed a full novel.** The four-way crossover is the furthest any run
  has got: research, planning, a 37-chapter outline, and 22 accepted chapters at ~113,000 words. It
  has not yet reached illustration, binding, or delivery on real content, so treat those three as
  bring-up rather than proven.
- **The editorial loop has one chapter of live evidence, not a book's worth.** Chapter 22 — the one
  that had just burned ten attempts, parked, and taken the whole novel down with it — went through
  the new loop in **two passes**: 13 repairs proposed and 13 applied, then 0 blocking and 11 more
  polish edits, for $3.03. That is the mechanism working exactly as designed, and it is also a
  sample of one. The claim that matters ("the defect count falls monotonically instead of
  random-walking") needs a dozen chapters before it is a measurement rather than a prediction. The
  trajectories are in `decisions.log`, logged per pass, precisely so this can be checked rather than
  believed.
- **Binding is proven on real prose; delivery and illustration are not.** The `.epub`
  build was run against the 22 accepted chapters of the live crossover — 272 KB, 22
  chapter files, a nav document reading `Chapter 1: The Glass in Gravesfield`, and the
  two-line headings the binder was taught to render. That is the deterministic half of
  the tail confirmed on real content rather than on fixtures. Illustration at real scale
  (81 images) and the atomic hand-off into iCloud have still only run stubbed.
- **The revision sweep has never run.** It is the mechanism that makes shipping a flawed chapter
  defensible, and until it has swept a real book that defence is a design argument.
- **There is a usage meter, and it is not a bill.** Every `claude` call's reported
  `total_cost_usd` is appended to `state/usage.jsonl` with a running total. **Nothing here is money
  anyone was charged:** the CLI reports that field whether it authenticates by API key or by
  logged-in session, this project has no API key anywhere, and the seat is billed per seat rather
  than per token — so the number is a *list-price valuation of token usage*. It is recorded because
  it is the only available signal for how much allowance a run consumes, which is the thing that
  actually runs out. Measured on the live crossover: **~$0.80-equivalent per chapter
  draft (Sonnet) and ~$1.50 per editorial pass (Opus judging 5,600 words against the
  whole bible, and writing every repair out in full).** Under the old
  critique-then-redraft loop a round was ~$1.75 and chapters averaged seven of them —
  about $18 an accepted chapter, and **$388 for twenty-two**, which extrapolates to
  ~$650 for the book. `python3 -m fanfic.cost` now projects **$222 at two editorial
  passes a chapter and $310 at three** — $7 to $8.50 a chapter rather than $18, with
  better output. The expensive thing was never the judging; it was doing it eleven
  times to the same chapter.

  **And the lever moved with it.** Writing is a fixed cost per chapter, so
  `FANFIC_EDIT_MAX_PASSES` is what the total is sensitive to — one fewer pass is ~$67 a
  projected book, and it is now the *only* knob of that size, since there is no judge
  tier left to drop. Judging dominating the bill is not the regression it was the first
  time this was true: what it is buying is repairs, not re-reading. `budget.json`
  remains a hand-managed ceiling the engine reads and never writes back, so the meter is
  reporting, never enforcement. Pictures report nothing and cost nothing; what they
  spend is wall-clock, counted by `FANFIC_IMAGE_RENDER_BUDGET`.
