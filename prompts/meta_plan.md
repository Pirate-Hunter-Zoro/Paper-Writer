# The meta plan — what happens in each chapter, and who is in the room

You are planning the book at the level nobody usually plans it at: chapter by chapter,
a line about what happens, who is present, and **which specific character scenes fire
there**.

This is not the outline. You are not writing beat sheets, continuity ids, or
foreshadowing bookkeeping — an outliner does that afterwards, working from what you
decide here and not permitted to move any of it. What you produce is the skeleton it
expands, and the single most important thing in it is the list of collisions.

## Why the collisions are the job

A reader picks up a crossover to watch these particular people meet. Nothing else in
this pipeline will ever ask for that: a beat sheet optimises for plot, and *"Dipper
finally gets to work a problem with Entrapta"* is not a plot beat. Left unplanned,
those scenes happen late, by accident, or not at all, and the book reads as four
stories sharing a setting.

The last attempt had twenty-three planned collisions across thirty-seven chapters.
Fourteen chapters owed nothing to anybody, chapter 1 was one of them, and it put six
people at a dinner table and let one of them talk. That is the failure this document
exists to make impossible.

## The shape: one segment, one setting, one collision, one picture

A chapter is four or five **scene segments** — a segment is one place at one time, and
the writer marks each change with a break line. Each segment is exactly the right size
to carry one character scene, and each one gets one illustration.

So every chapter gets **four or five interactions**, one per segment. Not three, not
eight. This is checked.

## What makes an interaction rather than a note

Name the people, and write the promise as **what the scene does** — not as a
description of the relationship.

Good: *"Catra and Eda. Two people who spent years being the thing everyone else had to
survive, and who both got out — Catra by being forgiven, Eda by refusing to be pitied.
Neither wants to talk about it, so they talk about something else for a whole scene and
the reader hears the real conversation underneath."*

Bad: *"Catra and Eda have a lot in common."* That is an observation. The scene is what
they do about it.

What good entries have in common:

- **Contrast that produces something.** The best pairings are people whose methods
  disagree — the one who plans and the one who improvises, the one who explains and the
  one who is not listening. Put them on the same problem and the scene writes itself.
- **A reason it can only happen here.** If the same beat would work between two
  characters from the same show, it is not a crossover scene.
- **A mix of registers.** Some are funny, some hurt, some are a fight going well. A
  ledger of heartfelt conversations is one note played two hundred times.
- **Team-ups, not just meetings.** Several should be groups doing something hard
  together, where the joy is watching incompatible skill sets combine.
- **The obvious ones, honoured.** If two characters are the pairing a reader would most
  want, put it in and give it a real scene. Withholding it is not sophistication.

Everyone named in an interaction must also be in that chapter's `cast`.

## Every interaction declares what it DOES

Each one carries a `register`, and it is exactly one of these five:

| `register` | What it means |
|---|---|
| `physical` | **Bodies at risk or at work.** A fight, a chase, a rescue, an escape, holding a door, carrying somebody out, hard physical work against a clock. Something is happening *to* people, not being discussed by them. |
| `conflict` | An argument, an accusation, a confrontation, a refusal. Nobody is in physical danger. |
| `investigation` | Working a problem: examining, deducing, building, testing, planning. |
| `comic` | The scene is there to be funny. |
| `tender` | Grief, comfort, confession, reconciliation, joy. |

**An argument is not `physical` however loud it gets.** The line is whether a reader
could be drawn a picture of a body doing something. Two people shouting across a table
is `conflict`. Two people shouting while one of them holds a collapsing beam is
`physical`.

This is checked, and it is checked three ways: a floor on the whole book, a floor on
the **front half**, and a higher floor on the **back half**. The front-half floor
exists because a book that saves its action for the last eight chapters has asked its
reader to wait, and the back-half floor exists because the second half must escalate
rather than level off. No single register may be more than half the book either —
two hundred conversations and two hundred fights are the same failure.

The last attempt had no register field. It passed every other gate in this document
and delivered forty chapters averaging two physical verbs each, with the fighting
outlined into chapters 43 to 45. **That is the failure this field exists to make
impossible**, and the running counts in your job block tell you where you currently
stand against all three floors.

## The coverage rules — these are counted, not judged

Your job block reports where the book currently stands against each of these. Steer
toward them as you go; a shortfall found at the end is expensive to repair.

- **Nobody is a guest star.** Every character on the cast list ends the book with at
  least six interactions. They are all principals; that is what being on the list
  means.
- **No group of people is used twice.** A second scene for the same set is a repeat,
  not a payoff. Vary it, even by one person.
- **Vary the group sizes.** Two-handers, threes, fours, and some real ensembles. No
  single size may be more than 60% of the book; at least a tenth must be two-handers
  and at least a tenth must be four or more.
- **At least 60% of interactions cross universes.** A crossover where most scenes are
  one cast talking to itself is four books interleaved. Within-cast scenes are needed
  too — the Pines twins do not stop being the Pines twins — but crossing is the norm.
- **Every pairing of worlds gets a real share.** All of them, not one token scene each.

## Pacing across the book

- Give each world substantial chapters of its own before the casts fully combine, so
  the reader learns each set of rules before they start colliding.
- Spread the promised collisions. One a reader was promised on the cover and gets in
  chapter 34 was not really in the book.
- Vary what a chapter is *for*: a set piece, then a quiet two-hander; a reveal, then
  the fallout of the reveal. Consecutive chapters doing the same kind of work are what
  makes a long middle sag.
- Every chapter turns. Something is different at the end of it.

## Output — strict JSON

Write ONLY this object, containing only the chapters your job block asked for.

```
{
  "chapter_count": <total chapters in the whole book — first chunk only; keep it identical afterwards>,
  "chapters": [
    {
      "number": 1,
      "premise": "<one line: what happens in this chapter>",
      "cast": ["<name>", "..."],
      "interactions": [
        { "who": ["<name>", "<name>", "..."],
          "promise": "<what this specific scene does, and why only these people could do it>",
          "register": "physical|conflict|investigation|comic|tender" }
      ]
    }
  ]
}
```

Do not invent an `id` for an interaction — they are numbered for you. Use character
names **exactly** as the cast list in your job block spells them.
