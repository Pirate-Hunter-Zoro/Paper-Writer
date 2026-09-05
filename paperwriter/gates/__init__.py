"""The deterministic gates — the "dispose" half of propose/dispose.

No models, no I/O, no network. Given a proposal and the ground truth it must respect,
each returns a verdict a person can check by hand:

  * `coverage`    — does the frozen evidence actually support the claims this paper
                    intends to make? Thin evidence parks the job before a word is
                    drafted.
  * `claims`      — is the argument map an argument? One headline claim, every claim
                    resting on evidence, kinds that vary, a limitation planned rather
                    than conceded, nothing said twice.
  * `structure`   — does this outline hold together? Contiguous numbering, IMRaD
                    order, budgets that fit the venue's limit, every claim placed
                    exactly once, and a declared topic sentence for every paragraph.
  * `sentences`   — the one-read rule, measured. Mean and variance of sentence length,
                    the long tail, semicolons and em-dashes per thousand words, empty
                    openers, stacked hedges. This is the gate the prose contract rests
                    on.
  * `paragraphs`  — does every paragraph open on its claim and close on what it means?
                    Catches the structural ways a topic sentence goes missing.
  * `terminology` — one name per thing. A locked vocabulary, enforced, because a
                    second name for one method reads as a third method.
  * `numbers`     — is every figure in the prose one the analysis actually produced?
                    The most valuable gate here, and the only defence against a model
                    that invents a number which looks exactly right.
  * `citations`   — do the markers resolve, are the references used, and does every
                    borrowed claim carry a source?
  * `readability` — Flesch and Flesch-Kincaid, banded for an academic venue. Measures
                    word length, which sentence statistics do not.
  * `length`      — is this section the length it was budgeted to be? A band, and the
                    ceiling is the half that matters.
  * `prose`       — the shared splitter. Words, sentences, paragraphs, once, so no two
                    gates can disagree about how many sentences a section has.

Everything here is trivially testable, which is the point: these are the rules a
confidently wrong model is not allowed to talk its way past. "Your prose is dense" is
an argument. "23% of your sentences run past 35 words, and here are the fifteen worst"
is not.
"""
