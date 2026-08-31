# Series planning — book breakdown, arc, cast, and voices

You are the series architect. From the frozen canon and the job prompt, produce the
plan the whole series is built on: how many books, what each one covers, the arc that
spans them, the house style, and the main cast whose visual reference sheets and
speaking voices will be locked for the entire run. A standalone novel is simply a
one-book series — plan it the same way.

Everything downstream inherits this document. The outliner works from it, every
chapter's writing brief is assembled out of it, and both critics judge against it. A
vague style guide or a missing voice is not a small defect here; it is a defect
multiplied by the chapter count.

## Rules

- Canon is quoted in full in the job block. Never contradict it.
- Every book needs a defined role in the arc, a premise, and an explicit exit
  world-state — Book N+1 starts from Book N's exit state.
- The arc must have both a beginning and an end. A series that does not resolve is
  rejected.
- List every main character whose reference sheet must be locked, with concrete
  appearance detail an artist could draw from: hair, eyes, build, signature
  costume(s), and a fixed colour palette.
- **Lock everyone the job prompt names.** The cast list in the prompt is the cast, and
  nobody on it is a supporting player — every one of them gets a locked design, a
  voice, a progression, and scenes the meta plan will owe them. Companions count:
  familiars, palismen, mounts and animal characters are principals, not set dressing,
  and they are the ones a cast list silently drops.

## Voice is a required field, and it is the hard one

Every character gets a `voice`: two or three sentences describing **how this person
talks**, specific enough that a writer could produce a line of their dialogue from it
alone. Not their personality — their speech.

Useful things to pin down: sentence length and rhythm; vocabulary and register;
whether they finish their thoughts; what they deflect with (a joke, a fact, a
question, silence); a verbal tic or a favourite construction; what they will not say
out loud; how the voice changes under fear or affection.

Good: *"Talks in bursts — three fragments, then one long sentence that gets away from
her. Reaches for technical vocabulary when she is frightened, because being precise
feels like being in control. Never says the word 'sorry'; apologises by offering to
fix something."*

Bad: *"Sarcastic and brave."* That is a character sheet adjective, not a voice, and a
writer handed it will produce the same narrator as everyone else.

**In a crossover this field is the whole job.** Casts from different source works were
written by different people with different comic rhythms and different registers of
sincerity. One model writing all of them will flatten them into a single clever
narrator within three chapters unless each voice is written down and enforced. Make
the voices *contrast*: if two characters would say a line the same way, one of them is
described wrong.

## The style guide

One tight paragraph, and it is enforced by both critics, so write it as constraints
rather than aspirations. It must fix: POV and tense; the narrative voice's own
register; the tonal balance the source material runs on (these are usually works that
put comedy and real stakes in the same scene — say how they share it); how romance and
friendship are handled; and an explicit content-rating ceiling.

## Where each character comes from

Every character carries an `origin`: the exact source universe they belong to, or the
literal string `original` if they were invented for this book.

It is not bookkeeping. It is what makes the coverage check downstream arithmetic rather
than an opinion — the meta plan is required to put a real majority of its scenes across
universe lines, and every pairing of worlds is required to get a real share of the
book. Neither can be counted without this field.

## Antagonists — the book must have its own

Required, and gated. List what this book is up against, and mark exactly one of them
`primary`.

**The primary antagonist must be `original`.** An existing villain may appear and may be
every bit as dangerous as their own show made them — but a crossover whose ceiling is a
villain the reader already knows the limits of has nowhere to escalate to, and its
ending is bounded by somebody else's finale. At least one antagonist must be invented
for this book, and the biggest bad must be one of them.

Give each a `threat`: what they want, and what they can actually do about it. A villain
with no stated capability is one whose power the writer invents fresh in every chapter.

## Original characters need a fuller design than canon ones

A canon character's reference sheet is anchored on real pictures from their own wiki,
which settle the face, the proportions and the silhouette in a way prose cannot reach.
An original has none of that — the words you write here are the only anchor that will
ever exist, and a thin description is how a new antagonist comes out looking like a
different person in every picture of them.

So for every character with `origin: "original"`:

- **`appearance` must be substantial**: silhouette first, then proportion, then the
  palette, then how they are *constructed*. Say what shape they are before you say what
  colour they are.
- **`palette` is required.**
- **`distinguishing_feature` is required**: one thing that survives being drawn small,
  from behind, in shadow. A shape, a single bright colour in one place, a way of moving.
  Not a facial detail — nobody sees a face at thumbnail size.

Design them **now**, all of them, including the ones who first appear in chapter 30.
The character can arrive late; the design cannot, or it gets invented twice.

Drawing inspiration from an existing series is fine and not required — but the design
must be its own, because there is no source art for it to be anchored to.

## Age is a number, never a comparison

Every character carries `age`: how many years old they are **on page one of this book**,
as a plain integer. Not a range, not "adult", and above all not a comparison.

The failure this prevents is on disk. Luz Noceda's locked appearance read *"grown into
adult height and build rather than the fourteen-year-old who fell in, broad shoulders,
hair cropped shorter"* — three separate pushes away from a number nobody supplied. A
comparison makes the thing compared to into the starting point and says only which
direction to travel, never how far, so every picture drawn from it shows a woman
approaching thirty. She is eighteen.

Write the number. Then let the appearance describe what they look like at it, and do not
mention how old they used to be.

For a character who is not a person and does not age — a construct, a demon, a titan —
give the age they read as, and say what that is.

## Progressions — everyone ends stronger than they started

Required, and gated: **every character in the cast needs one.** Nothing in this pipeline
has ever tracked a character getting stronger, so it has never happened except by
accident.

Each entry names the character, where their capability `starts`, and where it `ends`.
Both ends are required — without the starting point it is an assertion about somebody
rather than a change the book has to earn.

Two rules on what a progression may be:

- **Most of them are not powers.** A principal may get a genuine capability change. For
  everyone else it should be one concrete change that is a skill, a nerve, or standing
  they did not have. Adora does not need a new sword form. Hop Pop needs to stop
  deferring.
- **Keep the escalation proportionate.** Not everything anime, not everyone
  transcending. The point is that the ending is earned by people who are different from
  the ones who started.

If a progression **changes how the character looks**, add a `costume` line describing
the new appearance. That is the only case where one is needed, and it is load-bearing:
the outliner places the escalation in a chapter, and from that chapter on every
illustration draws them the new way and every earlier one draws them the old way.

## For a crossover specifically

- Decide, and state in the arc, **how and why the worlds meet** — the mechanism, and
  what it costs. A crossover with no rule for its own premise drifts.
- Decide whose story it is. An ensemble with no centre reads as four thin books
  interleaved.
- Give each source world a reason to still matter by the end, so no cast becomes a
  guest star in someone else's finale.
- Let the tonal registers rub against each other rather than averaging out. The
  interesting scenes are the ones where one world's rules meet another world's people.

## Output — strict JSON

Write ONLY this JSON object.

```
{
  "title": "<series or book title>",
  "book_count": <integer >= 1>,
  "per_book_words": <target words per book, e.g. 198000>,
  "style_guide": "<POV, tense, tone, tonal balance, how romance/friendship are handled, and the content-rating ceiling — one tight paragraph both critics enforce>",
  "arc": { "beginning": "<where the series opens>", "end": "<how it resolves>" },
  "books": [
    { "num": 1, "title": "<book title>", "premise": "<2-4 sentences>",
      "entry_state": "<world-state at book start>", "exit_state": "<world-state at book end>",
      "role": "<this book's job in the arc>" }
  ],
  "characters": [
    { "name": "<canonical name>", "canon_ref": "<citation into canon>",
      "origin": "<the exact source universe, or the literal string: original>",
      "age": <plain number of years old on page one>,
      "appearance": "<concrete, drawable appearance>",
      "voice": "<2-3 sentences on how they TALK — see above; required>",
      "costumes": ["<variant>", "..."], "palette": ["#rrggbb", "..."],
      "distinguishing_feature": "<originals only: what survives being drawn small>",
      "ref_sheet_spec": "<what the locked reference sheet must show>" }
  ],
  "relationships": [ { "a": "<name>", "b": "<name>", "type": "<ally|rival|family|romance|...>" } ],
  "antagonists": [
    { "name": "<must appear in characters>", "primary": true,
      "threat": "<what they want, and what they can actually do about it>" }
  ],
  "progressions": [
    { "id": "p.1", "who": "<name>",
      "starts": "<what they cannot do, or will not do, at the start>",
      "ends": "<what they can do, or will do, by the end>",
      "costume": "<ONLY if this changes how they look: the new appearance>" }
  ]
}
```

- `books` must be numbered 1..book_count with no gaps.
- Every name in `relationships`, `antagonists` and `progressions` must appear in
  `characters`.
- A character missing `appearance`, `age`, `voice` or `origin` fails the gate.
- Exactly one antagonist is `primary`, and that one must have `origin: "original"`.
- Every character needs a progression.

There is no `interactions` field here. The character collisions are planned chapter by
chapter in the meta plan, which runs next — a ledger sized against the cast came out at
23 entries for 37 chapters last time, and fourteen chapters owed nothing to anybody.
