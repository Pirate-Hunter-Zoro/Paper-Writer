"""The deterministic gates — the "dispose" half of propose/dispose.

No models, no I/O, no network. Given a proposal and the ground truth it must respect,
each returns a verdict a human can check by hand:

  * `coverage`     — did research actually cite facts about the entities this story
                     needs? Thin canon parks the job before a word is drafted.
  * `structure`    — does this outline hold together? Monotonic timeline, no payoff
                     without a setup, no orphaned thread, contiguous numbering, and
                     every planned escalation placed in exactly one chapter.
  * `interactions` — does the meta plan actually put these casts in a room together?
                     Everyone used enough, no subset twice, sizes varied, and a real
                     majority of the collisions crossing universes.
  * `readability`  — is this chapter in the Deathly Hallows band? Arithmetic, not a
                     model's opinion, because "reads like Harry Potter" is
                     measurable and should be measured.
  * `length`       — is this a chapter, or a scene? A floor, and only a floor.
  * `segments`     — did the writer mark its changes of place and time? Everything
                     per-scene downstream is defined over those breaks.

Everything here is trivially testable, which is the point: these are the rules a
confidently wrong model is not allowed to talk its way past.
"""
