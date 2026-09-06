"""The one-read rule, measured.

The rule is one sentence: **the reader must understand every sentence the first time
they read it.** If they have to go back over one, the sentence failed, however correct
its content.

That is a slogan until it is counted, and this module is the counting. Every threshold
here was calibrated against a real manuscript whose reviewers complained about
density. Its body text ran a mean of 26.2 words per sentence against a readable 18-20,
with 23% of sentences past 35 words, 74 semicolons and 34 em-dashes in 15,000 words.
Nearly every one of those marks welded a second claim into a sentence that already
carried one. The author had been told the prose was dense and could not see it,
because density is invisible from the inside and obvious in a table.

Seven measurements, and each one names a specific way a sentence stops being readable:

  * **mean length** — the aggregate. Over about 22 words a section reads as heavy.
  * **variance** — under a floor, every sentence is the same length, which is the
    loudest single tell that a machine wrote the paragraph. This is the only gate here
    that fires on prose which is individually fine.
  * **the long tail** — the share of sentences past 35 words. A few are legitimate; a
    section where one in five is has a systematic problem, not a few bad lines.
  * **the hard ceiling** — one sentence of 55 words is a defect wherever it appears
    and whatever the mean says.
  * **welds** — semicolons and em-dashes per thousand words. Both are almost always
    two sentences pretending to be one.
  * **empty openers** — "It is worth noting", "Importantly", "Taken together". A
    sentence whose only job is to introduce another one.
  * **stacked hedges** — two qualifications on one claim. One hedge is honest; two is
    a claim the author does not want to be held to.

Everything here is arithmetic over a string. No model, no I/O, no opinion — which is
the point, because "your prose is dense" is an argument and "23% of your sentences are
over 35 words" is not.

**Why the gate reports locations and not just numbers.** Mean sentence length is a
property of every sentence at once, so "too dense" cannot be anchored to a span the
way a wrong number can. But the mean is driven by specific sentences that can be
quoted, and the editorial loop repairs by anchored find/replace. So the report carries
the offending sentences verbatim, and an un-anchorable statistic becomes a list of
ordinary anchored edits.
"""

import re
import statistics
from dataclasses import dataclass, field

from .. import config
from . import prose

# Openers whose only job is to announce that a sentence is coming. Every one of these
# can be deleted with the rest of the sentence left intact, which is the test.
_EMPTY_OPENERS = (
    "it is worth noting", "it is important to note", "it should be noted",
    "it is interesting", "notably", "importantly", "significantly",
    "taken together", "in other words", "that said", "needless to say",
    "it bears mentioning", "as noted above", "as mentioned", "of note",
    "this highlights", "this underscores", "this suggests that it",
    "it is clear that", "it is evident that", "one might argue",
)

# Hedges. One is fine. Two on the same claim is the thing this counts.
_HEDGES = (
    "may", "might", "could", "possibly", "perhaps", "potentially", "appears to",
    "seems to", "suggests", "suggesting", "somewhat", "relatively", "arguably",
    "likely", "unlikely", "tends to", "in some cases", "to some extent",
    "it is possible", "cannot be ruled out", "we speculate", "conceivably",
)

# A weld is a semicolon INSIDE a line. One at the end of a line is list punctuation —
# the conventional way to separate the items of an enumeration — and counting it drives
# a writer away from the bulleted list that fixes the long sentence in the first place.
_SEMICOLON_RE = re.compile(r";(?![ \t]*(?:\n|$))")
_EMDASH_RE = re.compile(r"[—–]|(?<=\s)--(?=\s)")


def _hedge_count(sentence):
    low = " " + sentence.lower() + " "
    return sum(1 for h in _HEDGES if re.search(r"(?<![a-z])" + re.escape(h) +
                                               r"(?![a-z])", low))


def _empty_opener(sentence):
    """The filler phrase this sentence opens with, or "" if it opens on its point."""
    low = sentence.lower().lstrip("\"'“‘([ ")
    for opener in _EMPTY_OPENERS:
        if low.startswith(opener):
            return opener
    return ""


@dataclass
class SentenceReport:
    words: int
    count: int
    mean: float
    median: float
    stdev: float
    longest: int
    long_share: float               # fraction past SENTENCE_LONG_WORDS
    semicolons_per_kword: float
    emdashes_per_kword: float
    over_hard_max: list = field(default_factory=list)   # sentences past the ceiling
    long_sentences: list = field(default_factory=list)  # past SENTENCE_LONG_WORDS
    empty_openers: list = field(default_factory=list)   # (sentence, phrase)
    stacked_hedges: list = field(default_factory=list)  # sentences with 2+ hedges
    welded: list = field(default_factory=list)          # sentences with ; or —
    passed: bool = True
    reasons: list = field(default_factory=list)

    def brief(self):
        """One line of measurements, for a log."""
        return (f"{self.count} sentences, mean {self.mean:.1f} words "
                f"(sd {self.stdev:.1f}), longest {self.longest}, "
                f"{self.long_share:.0%} over {config.SENTENCE_LONG_WORDS}, "
                f"{self.semicolons_per_kword:.1f} semicolons and "
                f"{self.emdashes_per_kword:.1f} dashes per 1,000 words")


def score(text, section_name=""):
    """Measure a block of prose against the one-read rule. Returns a SentenceReport.

    `section_name` exempts the sections that are not prose, using the same list the
    paragraph gate uses. A keyword list is semicolon-separated by convention and would
    fail the weld check every time; a title page is one 100-word noun phrase; a
    reference list is neither sentences nor paragraphs. Measuring them produces noise,
    and a gate that fires on every manuscript is a gate somebody switches off."""
    if section_name and section_name.strip().lower() in config.PARAGRAPH_EXEMPT_SECTIONS:
        return SentenceReport(
            words=0, count=0, mean=0.0, median=0.0, stdev=0.0, longest=0,
            long_share=0.0, semicolons_per_kword=0.0, emdashes_per_kword=0.0,
            passed=True)
    body = prose.strip_structure(text)
    sents = prose.sentences(body)
    n_words = prose.word_count(body)

    if not sents:
        return SentenceReport(
            words=0, count=0, mean=0.0, median=0.0, stdev=0.0, longest=0,
            long_share=0.0, semicolons_per_kword=0.0, emdashes_per_kword=0.0,
            passed=False, reasons=["empty draft: no sentences to measure"])

    lengths = [len(s.split()) for s in sents]
    mean = statistics.fmean(lengths)
    median = statistics.median(lengths)
    stdev = statistics.pstdev(lengths) if len(lengths) > 1 else 0.0
    longest = max(lengths)

    long_ones = [s for s, n in zip(sents, lengths) if n > config.SENTENCE_LONG_WORDS]
    over_hard = [s for s, n in zip(sents, lengths)
                 if n > config.SENTENCE_HARD_MAX_WORDS]
    long_share = len(long_ones) / len(sents)

    per_kword = 1000.0 / max(n_words, 1)
    semis = len(_SEMICOLON_RE.findall(body)) * per_kword
    dashes = len(_EMDASH_RE.findall(body)) * per_kword

    openers = [(s, phrase) for s in sents if (phrase := _empty_opener(s))]
    hedged = [s for s in sents if _hedge_count(s) >= 2]
    welded = [s for s in sents if _SEMICOLON_RE.search(s) or _EMDASH_RE.search(s)]

    report = SentenceReport(
        words=n_words, count=len(sents), mean=round(mean, 2),
        median=round(median, 1), stdev=round(stdev, 2), longest=longest,
        long_share=round(long_share, 4),
        semicolons_per_kword=round(semis, 2), emdashes_per_kword=round(dashes, 2),
        over_hard_max=over_hard, long_sentences=long_ones,
        empty_openers=openers, stacked_hedges=hedged, welded=welded)

    reasons = []
    if mean > config.SENTENCE_MEAN_WORDS_MAX:
        reasons.append(
            f"sentences average {mean:.1f} words; the ceiling is "
            f"{config.SENTENCE_MEAN_WORDS_MAX:.0f}. Split the longest ones — a "
            f"sentence carrying two claims is two sentences.")
    if mean < config.SENTENCE_MEAN_WORDS_MIN:
        reasons.append(
            f"sentences average {mean:.1f} words; the floor is "
            f"{config.SENTENCE_MEAN_WORDS_MIN:.0f}. This reads as clipped rather "
            f"than clear. Let the sentences that carry a real claim run.")
    if len(lengths) >= 5 and stdev < config.SENTENCE_STDEV_MIN:
        reasons.append(
            f"every sentence is nearly the same length (sd {stdev:.1f} words, floor "
            f"{config.SENTENCE_STDEV_MIN:.0f}). Put a six-word sentence next to a "
            f"twenty-five-word one.")
    if long_share > config.SENTENCE_LONG_SHARE_MAX:
        reasons.append(
            f"{long_share:.0%} of sentences run past {config.SENTENCE_LONG_WORDS} "
            f"words; the ceiling is {config.SENTENCE_LONG_SHARE_MAX:.0%}. That is "
            f"{len(long_ones)} of {len(sents)}.")
    if over_hard:
        reasons.append(
            f"{len(over_hard)} sentence(s) run past the hard ceiling of "
            f"{config.SENTENCE_HARD_MAX_WORDS} words. No sentence that long is doing "
            f"one job.")
    if semis > config.SEMICOLONS_PER_KWORD_MAX:
        reasons.append(
            f"{semis:.1f} semicolons per 1,000 words; the ceiling is "
            f"{config.SEMICOLONS_PER_KWORD_MAX:.0f}. A semicolon is almost always a "
            f"full stop that lost its nerve.")
    if dashes > config.EMDASHES_PER_KWORD_MAX:
        reasons.append(
            f"{dashes:.1f} em-dashes per 1,000 words; the ceiling is "
            f"{config.EMDASHES_PER_KWORD_MAX:.0f}. An em-dashed aside is a second "
            f"claim wearing a disguise.")
    if openers:
        reasons.append(
            f"{len(openers)} sentence(s) open on filler "
            f"({', '.join(sorted({p for _, p in openers})[:4])}). Delete the opener "
            f"and make the point.")
    if hedged:
        reasons.append(
            f"{len(hedged)} sentence(s) carry two or more hedges. Keep the one that "
            f"changes what a reader would do and delete the rest.")

    report.reasons = reasons
    report.passed = not reasons
    return report


def worst_offenders(report, count=None):
    """The sentences most worth quoting to an editor, worst first.

    Ordered by how badly each one breaks the rule rather than by length alone: a
    45-word sentence with a semicolon and two hedges is a worse read than a 50-word
    sentence that simply lists six covariates."""
    count = config.EDIT_LONG_SENTENCES if count is None else count
    scored = {}
    for sentence in report.over_hard_max:
        scored[sentence] = scored.get(sentence, 0) + 3
    for sentence in report.long_sentences:
        scored[sentence] = scored.get(sentence, 0) + 2
    for sentence in report.welded:
        scored[sentence] = scored.get(sentence, 0) + 1
    for sentence in report.stacked_hedges:
        scored[sentence] = scored.get(sentence, 0) + 1
    for sentence, _ in report.empty_openers:
        scored[sentence] = scored.get(sentence, 0) + 1
    ranked = sorted(scored.items(),
                    key=lambda kv: (kv[1], len(kv[0].split())), reverse=True)
    return [s for s, _ in ranked[:count]]
