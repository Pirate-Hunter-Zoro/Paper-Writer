"""The readability gate — Flesch reading ease and Flesch-Kincaid grade level.

The junior partner to `gates/sentences.py`, and worth keeping for one reason: it
measures the half of readability that sentence statistics do not, which is word
length. A section of short sentences made entirely of polysyllabic nominalizations
passes every check in `sentences.py` and is still hard to read.

    reading ease   = 206.835 - 1.015 * (words/sentences) - 84.6 * (syllables/words)
    FK grade level =   0.39  * (words/sentences) + 11.8 * (syllables/words) - 15.59

The band is academic, not general-audience: FK 10-16. Below that a paper reads as a
press release; above it the reviewer is re-reading sentences. Reading ease is gated
loosely on purpose — a Methods section full of necessarily long clinical nouns scores
badly however well it is written, and punishing it for that would teach the writer to
swap precise words for vague ones.

Syllable counting has no perfect closed form. The standard vowel-group heuristic is
used: count runs of vowels, drop a silent trailing 'e', floor at one. It is wrong on
individual words and stable in aggregate, which is all a band gate needs.

**On why both this and `sentences.py` exist.** They overlap on words-per-sentence and
diverge on everything else, and the divergence is what makes both worth running. This
one produces a single number that is comparable across papers and journals.
`sentences.py` produces a list of specific sentences to repair. A gate that only gives
you a score tells the writer they failed; a gate that gives you the fifteen worst
sentences tells them what to do about it.
"""

import re
from dataclasses import dataclass

from .. import config
from . import prose

_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")


def count_syllables(word):
    """Heuristic syllable count for a single word. Floors at 1."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    count = len(_VOWEL_GROUP_RE.findall(w))
    # Silent trailing 'e' (but not "-le" as in "table", where the e carries a beat).
    if w.endswith("e") and not w.endswith("le") and count > 1:
        count -= 1
    return max(1, count)


@dataclass
class ReadabilityReport:
    words: int
    sentences: int
    syllables: int
    flesch_ease: float
    fk_grade: float
    passed: bool
    reasons: list           # human-readable reasons it failed the band (empty on pass)


def score(text):
    """Compute the readability metrics for a block of prose and gate them against
    the configured band. Returns a ReadabilityReport."""
    body = prose.strip_structure(text)
    words = prose.words(body)
    n_words = len(words)
    n_sentences = max(1, len(prose.sentences(body)))
    n_syllables = sum(count_syllables(w) for w in words)

    if n_words == 0:
        return ReadabilityReport(
            words=0, sentences=n_sentences, syllables=0,
            flesch_ease=0.0, fk_grade=0.0, passed=False,
            reasons=["empty draft: no words to score"])

    words_per_sentence = n_words / n_sentences
    syllables_per_word = n_syllables / n_words

    flesch_ease = round(206.835 - 1.015 * words_per_sentence
                        - 84.6 * syllables_per_word, 2)
    fk_grade = round(0.39 * words_per_sentence + 11.8 * syllables_per_word - 15.59, 2)

    reasons = []
    if fk_grade < config.READABILITY_FK_GRADE_MIN:
        reasons.append(
            f"too simple for the venue: FK grade {fk_grade} < floor "
            f"{config.READABILITY_FK_GRADE_MIN}. This is not usually a defect worth "
            f"fixing by adding words — check that the section has not dropped the "
            f"precision its claims need.")
    if fk_grade > config.READABILITY_FK_GRADE_MAX:
        reasons.append(
            f"too dense: FK grade {fk_grade} > ceiling "
            f"{config.READABILITY_FK_GRADE_MAX}. Only two things move this number: "
            f"sentence length and syllables per word. Split the longest sentences, "
            f"and swap a Latinate word for the plain one wherever the plain one is "
            f"just as precise.")
    if flesch_ease < config.READABILITY_FLESCH_EASE_MIN:
        reasons.append(
            f"reading ease {flesch_ease} < floor "
            f"{config.READABILITY_FLESCH_EASE_MIN}. The words are long, not just the "
            f"sentences. Prefer a verb to a nominalization: \"the model did worse\", "
            f"not \"a decrement in model discrimination was observed\".")

    return ReadabilityReport(
        words=n_words, sentences=n_sentences, syllables=n_syllables,
        flesch_ease=flesch_ease, fk_grade=fk_grade,
        passed=not reasons, reasons=reasons)
