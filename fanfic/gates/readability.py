"""The readability gate — a hard, deterministic numeric gate on chapter prose.

"Make it read like Harry Potter" is measurable, so we measure it in code rather
than asking a model for a vibe. Each drafted chapter's Flesch reading ease and
Flesch–Kincaid grade level are computed here and gated to the Deathly Hallows band
declared in config. A chapter outside the band fails the critique battery and goes
back through the bounded revision loop, exactly like any other critique failure —
but this verdict is arithmetic, not judgment, so it is cheap, reproducible, and
un-arguable.

The two formulas (standard):
    reading ease  = 206.835 - 1.015 * (words/sentences) - 84.6 * (syllables/words)
    FK grade level =   0.39  * (words/sentences) + 11.8 * (syllables/words) - 15.59

Syllable counting is a well-known hard sub-problem with no perfect closed form; we
use the standard vowel-group heuristic (count runs of vowels, drop a silent
trailing 'e', floor at one syllable per word). It is not perfect on every word, but
over a chapter of many thousands of words the per-word error averages out and the
aggregate score is stable — which is all a band gate needs.
"""

import re
from dataclasses import dataclass

from .. import config

_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
# Sentence terminators: ., !, ?, and the ellipsis/emdash-as-terminator cases,
# collapsed so a run of "?!" or "..." counts as one sentence end, not several.
_SENTENCE_RE = re.compile(r"[.!?]+(?:['\")\]]+)?\s")
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")


def count_syllables(word):
    """Heuristic syllable count for a single word. Floors at 1."""
    w = word.lower()
    w = re.sub(r"[^a-z]", "", w)
    if not w:
        return 0
    groups = _VOWEL_GROUP_RE.findall(w)
    count = len(groups)
    # Silent trailing 'e' (but not "-le" as in "table", where the e carries a beat).
    if w.endswith("e") and not w.endswith("le") and count > 1:
        count -= 1
    return max(1, count)


def _count_sentences(text):
    """Number of sentences. A terminator run counts once; a final unterminated
    clause still counts as one sentence so a chapter can't dodge the gate by
    omitting its closing period."""
    # Ensure the tail is caught by appending a boundary space.
    n = len(_SENTENCE_RE.findall(text + " "))
    return max(1, n)


@dataclass
class ReadabilityReport:
    words: int
    sentences: int
    syllables: int
    flesch_ease: float
    fk_grade: float
    passed: bool
    reasons: list  # human-readable reasons it failed the band (empty on pass)


def score(text):
    """Compute the readability metrics for a block of prose and gate them against
    the configured band. Returns a ReadabilityReport."""
    words = _WORD_RE.findall(text)
    n_words = len(words)
    n_sentences = _count_sentences(text)
    n_syllables = sum(count_syllables(w) for w in words)

    if n_words == 0:
        return ReadabilityReport(
            words=0, sentences=n_sentences, syllables=0,
            flesch_ease=0.0, fk_grade=0.0, passed=False,
            reasons=["empty draft: no words to score"],
        )

    words_per_sentence = n_words / n_sentences
    syllables_per_word = n_syllables / n_words

    flesch_ease = 206.835 - 1.015 * words_per_sentence - 84.6 * syllables_per_word
    fk_grade = 0.39 * words_per_sentence + 11.8 * syllables_per_word - 15.59

    flesch_ease = round(flesch_ease, 2)
    fk_grade = round(fk_grade, 2)

    reasons = []
    if fk_grade < config.READABILITY_FK_GRADE_MIN:
        reasons.append(
            f"too simple: FK grade {fk_grade} < floor {config.READABILITY_FK_GRADE_MIN}")
    if fk_grade > config.READABILITY_FK_GRADE_MAX:
        reasons.append(
            f"too dense: FK grade {fk_grade} > ceiling {config.READABILITY_FK_GRADE_MAX}")
    if flesch_ease < config.READABILITY_FLESCH_EASE_MIN:
        reasons.append(
            f"reading ease {flesch_ease} < floor {config.READABILITY_FLESCH_EASE_MIN}")

    return ReadabilityReport(
        words=n_words, sentences=n_sentences, syllables=n_syllables,
        flesch_ease=flesch_ease, fk_grade=fk_grade,
        passed=not reasons, reasons=reasons,
    )
