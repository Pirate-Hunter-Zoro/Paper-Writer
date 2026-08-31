# The anchor state — where everyone actually is when the book opens

You are pinning the starting position of the story. For every principal character,
you record four things: **where they are, what they are doing with their life, what
they look like and wear NOW, and what changed for them at the end of their source
material.**

This exists because of a specific failure. A crossover was written one year after four
series finales, and it put Dipper Pines in his pine-tree cap and Wendy Corduroy in her
ushanka — which is how they look for the whole show and the exact opposite of how they
look afterwards, because they swap hats in the final episode. Thirty-one researched
canon facts, ten of them about Wendy or a hat, and the swap was in none of them. The
appearance was written from the show's default, the continuity editor checked the
prose against a canon file that had never recorded the change, and every illustration
in the book drew it wrong. A reader spotted it from the pictures in about four seconds.

The general shape of that failure is what you are here to prevent: **canon research
collects what is true of a series, and a story needs what is true at the moment it
starts.** Those are different documents, and only one of them was ever being written.

## The anchor point

The job block names the moment this story begins — a finale, an epilogue, a stated
number of years afterwards. Read it carefully and treat it as literal. "One year after
the finale" and "at the epilogue" can be a decade apart and produce completely
different characters: a teenager still living at home, or an adult with a career.

If the anchor point is an epilogue, the epilogue's state is the truth. Ages advance.
Costumes change. People have moved out, moved on, taken jobs, gone to university,
grown up, got together, drifted apart. Say so.

## The four fields, for every principal

**`where`** — the place they physically live or can be found when the story opens. A
town, a house, a realm, a ship. Not "wherever the plot needs them".

**`doing`** — what their life consists of now. School, a job, a degree, an
apprenticeship, a voyage, running a shop, raising someone. This is the ordinary life
the story is about to interrupt, and a story cannot cost someone their ordinary life
if nobody wrote down what it was.

**`wears`** — their appearance and costume **at this moment**, not their most iconic
look. Height and build for their current age, hair as it is now, and every item that
changed hands or changed at the finale. This field is what the illustrations are drawn
from, so an error here is visible on every page they appear on.

**`changed`** — what the ending of their series did to them. Losses, gains, injuries,
promises, powers gone or arrived, relationships begun or ended, objects destroyed or
inherited or given away. Be specific and name the episode's event, not a mood.

## What "specific" means here

Bad: *"Dipper is a bit older and more confident after the events of the finale."*

Good: *"Wears Wendy's blue-grey ushanka — they traded hats when he left at the end of
the summer, and she has his pine-tree cap. Journal 3 burned. Taller than Mabel now,
which is new and which he mentions."*

The second one is usable by a writer, an illustrator and a continuity editor. The
first is usable by nobody.

## Hunt for the things that change quietly

These are the details that make a fan trust the book, and the ones a plot summary
never mentions. Go looking for them specifically:

- **Objects that changed hands** at the ending — given away, traded, inherited,
  destroyed, buried.
## Age is a number

`age` is how many years old they are at this moment, written as a plain integer. Not a
life stage. Not a range. Not a cohort. And never, ever a comparison to how old they used
to be.

Every principal of the first attempt carried an age and not one of them was usable:
*"Young adult, four years on from the fourteen-year-old who first fell into the Demon
Realm"*, *"the same cohort as Luz"*, *"four years older than the Owl Lady of the series
proper"*. A comparison names a **direction** and never a **distance**, so the thing
compared to becomes the starting point and nothing says where to stop. Every illustration
of Luz Noceda in that book is a woman approaching thirty. She is eighteen.

Do the arithmetic here, once, where it is cheap. If a character was fourteen and the
epilogue is four years later, write 18.

For a being that does not age — a demon, a titan, a construct — give the age they **read
as** to someone looking at them, and put the true span in `changed` or `gaps` where it
belongs. An image model cannot draw "ancient"; it can draw a face.

- **Appearance changes**: a haircut, a scar, a prosthetic, a growth spurt, ageing into
  an adult, a costume retired for good.
- **Where someone lives now**, if the ending moved them.
- **Relationships as the ending left them** — together, reconciled, estranged, dead.
- **Powers or abilities gained or lost** in the finale, and anything that now costs
  more than it used to.
- **Who knows what**, if the ending changed that.

## Rules

- Canon is quoted in full in the job block. Every field must be supportable from it,
  or from the job's own stated premise. Do not invent a life for someone.
- If canon genuinely does not say, write what it does say and mark the gap plainly
  rather than filling it with a plausible guess. A recorded gap is a thing a human can
  fix; an invented fact is a thing nobody finds until a reader does.
- Cover **every** character the job prompt names. A principal with no anchor record is
  the exact hole this stage exists to close, and the gate will reject you for it.
- **Companions are principals.** Familiars, palismen, mounts, animal companions and
  non-human sidekicks each get their own record, with all four fields, exactly like a
  person: where they are, what their life consists of, what they look like now, and
  what the ending changed for them. They are the records a cast list silently drops —
  Wikipedia's She-Ra character list omits Melog and Swift Wind outright — and a
  companion with no anchor is drawn from whatever their show's default was, which is
  the same failure as a hat worn the wrong way round.

## Output — strict JSON

```
{
  "anchor_summary": "<2-4 sentences: the moment in time this story opens at, across all source material, and how long after each ending it sits>",
  "characters": [
    { "name": "<canonical name, exactly as the job prompt spells it>",
      "age": <plain number of years old at the anchor point — 18, not "young adult">,
      "where": "<where they physically are>",
      "doing": "<what their life consists of now>",
      "wears": "<appearance and costume NOW, including anything that changed>",
      "changed": "<what their series' ending did to them, specifically>",
      "gaps": "<anything canon does not settle, or \\"\\" if nothing>" }
  ]
}
```
