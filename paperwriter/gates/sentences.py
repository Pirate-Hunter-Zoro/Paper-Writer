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
  * **local density** — the mean inside one paragraph. Every measurement above is a
    section average, and an average hides the paragraph that earns it. A real
    manuscript passed its Methods at a mean of 20.8 carrying a paragraph at 27.2, and
    a reader does not read the average.
  * **anticipatory rebuttals** — "and not only a limitation", "this should not be read
    as". The paper arguing with a reviewer who has not spoken yet. It is hard to read
    because it asks you to hold an objection nobody made.
  * **undefined comparisons** — "ten of the eleven favour the narrative". A count of a
    comparison whose dimension is never stated. The number looks precise and the
    sentence says nothing, which is worse than vagueness because it does not read as
    vague.
  * **unreported analyses** — "available from the corresponding author", "data not
    shown", "reported separately". A sentence that describes an analysis and then
    declines to report it. It advertises a result the reader cannot check, and it
    spends the paper's credibility on work that is not in the paper.
  * **equivalence claimed without an equivalence test** — a whole-document check
    rather than a sentence one. A paper whose Methods say no equivalence margin was
    prespecified, and whose Discussion then calls the result "parity" sixteen times,
    is arguing with itself in the reader's hands. See `equivalence_overclaim`.

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

# The paper arguing with a reviewer who has not spoken yet.
#
# Found in a Methods paragraph that ended "it is the evidence for the scope statement
# above and not only a limitation". The clause is unreadable on one pass for a specific
# reason: it asks the reader to hold an objection that has not been raised, decide it
# is wrong, and only then take the point. Every one of these can be deleted with the
# claim left standing, which is the test — the same test the empty openers pass.
#
# The pre-emptive concession ("while it is true that", "we acknowledge that") belongs
# here too. A Limitations section states a limitation; it does not negotiate one.
# What is NOT here matters as much as what is. "This parity should not be read as
# evidence that the embedding found structure unaided" was in the first draft of this
# list and came straight back out: bounding what a result means is the job of a
# Discussion, and a gate that refuses it teaches the writer to overclaim. The list is
# the pre-emptive DEFENCE — the paper insisting it has not made a mistake — not the
# scope statement, which is the paper saying what it did not measure.
_ANTICIPATORY = (
    "and not only a", "and not merely a", "and not just a",
    "and not only an", "and not merely an", "and not just an",
    "rather than merely a", "rather than simply a", "rather than just a",
    "is not a limitation", "far from being a", "far from being merely",
    "it might be objected", "one might object", "some may argue",
    "some might argue", "we would argue that", "it could be argued that",
    "while it is true that", "lest it be thought", "this is not to say",
)

# A figure written as a word, which is how a quantity gets past the numbers gate.
#
# "That interval is roughly a third the width of the marginal ones" is a measurement.
# It is a ratio of two reported quantities, it is load-bearing — the sentence uses it
# to argue the null is precise rather than blurry — and it is wrong: the intervals
# printed two sentences above are 0.029 and 0.030 wide against a paired 0.022, which is
# three quarters, not a third. No gate saw it, because `numbers` looks up numerals in
# the evidence ledger and there is no numeral here.
#
# So a ratio stated in words, in a sentence carrying no measured value, is refused. The
# repair is to write the number, at which point the numbers gate can do its job.
_RATIO_WORDS = (
    r"an?\s+(?:third|quarter|fifth|half)\s+(?:the|as)",
    r"(?:twice|thrice|double|triple|quadruple)\s+(?:the|as)",
    r"(?:two|three|four|five|six|seven|eight|nine|ten)\s+times\s+(?:the|as|wider|"
    r"narrower|larger|smaller|longer|higher|lower)",
    r"orders?\s+of\s+magnitude",
    r"an?\s+(?:order)\s+of\s+magnitude",
    # The unquantified magnitude comparison, which is the same defect without the
    # arithmetic. "The two effects are of comparable magnitude" sat one paragraph
    # below +0.028 against -0.013 to -0.022, which is not comparable by any reading.
    # "order" is deliberately absent from the nouns below. "The six specifications
    # ordered in the same order as Table 4" is a sequence, not a magnitude, and it was
    # the one false positive this check produced on a real supplement. "The same order
    # of magnitude" is already covered by the pattern above.
    r"(?:comparable|similar|equivalent|the\s+same)\s+(?:in\s+)?"
    r"(?:magnitude|size|scale)",
    r"(?:roughly|approximately|about)\s+(?:equal|the\s+same\s+size)",
    r"(?:far|much|vastly|substantially)\s+"
    r"(?:larger|smaller|wider|narrower|greater|higher|lower)\s+than",
)
_RATIO_RE = re.compile("|".join(_RATIO_WORDS), re.IGNORECASE)

# What makes the sentence self-checking: an actual measured value in it. A bare "two"
# inside "two orders of magnitude" is part of the idiom, not a measurement, so the
# numeral has to look like data — a decimal, a percentage, or a thousands-grouped count.
_MEASURED_VALUE_RE = re.compile(r"\d+\.\d|\d+\s?%|\d{1,3}(?:,\d{3})+|\bCI\b")


def _wordy_ratio(sentence):
    """A ratio asserted in words by a sentence that reports no number, or "".

    The gate is not against the phrase. It is against the phrase standing alone: write
    "0.022 against 0.029" and the same sentence passes, and the numbers gate can then
    check both figures against the evidence."""
    match = _RATIO_RE.search(sentence)
    if not match:
        return ""
    if _MEASURED_VALUE_RE.search(sentence):
        return ""
    return " ".join(match.group(0).split()).lower()


# Work the paper describes and then declines to report.
#
# "Two further weightings derived from an outcome-blind clinical-similarity score were
# also evaluated. They added no discrimination and are reported separately, available
# from the corresponding author." Two sentences, one whole analysis, no numbers, and a
# reader who cannot check any of it.
#
# This is the "data not shown" defect, which journals have objected to for decades,
# wearing politer phrases. The rule that makes it checkable is simple and the repair
# is always one of exactly two things: report it, or do not mention it. There is no
# third option in which the sentence stays and the result does not, because a claim
# whose evidence is a mailing address is not a claim the paper can make.
#
# The narrow reading matters. "Code is available from the corresponding author" is a
# DATA-AVAILABILITY statement, not an unreported analysis, and journals require it. So
# the phrase alone is not the defect: it is the defect when the sentence is about a
# result. That is why the check looks for the availability phrase together with a verb
# of analysis in the same sentence.
_UNREPORTED_PHRASES = (
    "available from the corresponding author", "available on request",
    "available upon request", "data not shown", "results not shown",
    "not shown here", "not reported here", "reported separately",
    "are reported elsewhere", "is reported elsewhere", "omitted for brevity",
    "in a forthcoming", "in preparation",
)

# What makes the sentence about a RESULT rather than about a file.
_ANALYSIS_WORDS = (
    "analys", "evaluat", "estimat", "compar", "test", "fit", "model", "result",
    "discrimination", "auc", "finding", "experiment", "ablation", "sensitivity",
    "re-run", "rerun", "weighting", "arm", "contrast",
)

# What makes it a data-availability statement, which is required rather than refused.
_AVAILABILITY_SUBJECTS = (
    "code", "data", "dataset", "script", "software", "materials", "protocol",
    "questionnaire", "instrument", "source code", "repository",
)


def _unreported_analysis(sentence):
    """The phrase by which this sentence declines to report an analysis, or "".

    Both halves are required. A sentence saying the code is available on request is a
    data-availability statement and a journal asks for it; a sentence saying an
    evaluation was run and its numbers are available on request is the paper spending
    credibility on work nobody can see."""
    low = sentence.lower()
    phrase = next((p for p in _UNREPORTED_PHRASES if p in low), "")
    if not phrase:
        return ""
    if not any(w in low for w in _ANALYSIS_WORDS):
        return ""
    # A data-availability sentence names what is available before the phrase.
    head = low.split(phrase)[0]
    if any(re.search(r"(?<![a-z])" + s + r"s?(?![a-z])", head)
           for s in _AVAILABILITY_SUBJECTS):
        return ""
    return phrase


# A comparison with no dimension.
#
# "10 of those 11 favour the narrative" was the sentence this came from. It carries two
# exact counts and does not say what favouring IS — more fields, finer values, free
# text where the other side has a code. The precision of the number disguises the fact
# that the relation is undefined, so it survives a read the way a vague sentence would
# not.
#
# The rule that makes this checkable: a comparison verb has to be told what axis it
# runs on. That axis reaches the sentence as a preposition ("in granularity", "on
# discrimination", "by AUC"), as an explicit comparison ("recall over precision"), or
# as a clause saying what the winner gets. A comparison verb with none of those is a
# claim the reader has to guess at.
_COMPARISON_VERBS = (
    "favour", "favours", "favoured", "favor", "favors", "favored", "favouring",
    "favoring", "outperform", "outperforms", "outperformed", "outperforming",
    "beat", "beats", "surpass", "surpasses", "surpassed", "exceed", "exceeds",
    "exceeded", "win", "wins", "lose", "loses", "dominate", "dominates",
)

# The COUNT is what makes it checkable, and narrowing to the count is what makes the
# gate usable. "The embedding did not beat the feature vector" is a plain claim whose
# axis the section around it has already fixed, and an earlier version of this check
# refused it — along with "Retrieval works, and loses" and "none exceeds 0.05". Every
# one of those was correct prose.
#
# What survives the narrowing is the construction that actually failed: a tally of
# comparisons. "Ten of the eleven favour the narrative" asserts eleven separate
# comparative judgements and defines none of them. The count is doing the work of an
# argument the sentence never makes, and the reader cannot tell, because a number
# reads as evidence.
_TALLIED_COMPARISON_RE = re.compile(
    r"(?<![a-z])(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|most|many|several|all|both|half)\s+(?:of\s+)"
    r"(?:those|these|them|the|its|which)?\s*[\w,\s-]{0,40}?"
    r"(?<![a-z])(" + "|".join(_COMPARISON_VERBS) + r")(?![a-z])", re.IGNORECASE)

# What counts as naming the axis. Deliberately generous: this gate refuses a sentence,
# so it must not refuse one that already answers the question in any ordinary way. A
# number after the verb counts too — "exceeds 0.05" names its axis by stating it.
_DIMENSION_CUE_RE = re.compile(
    r"(?<![a-z])(?:in|on|by|for|across|with|over|under|at|per|through|"
    r"in terms of|with respect to|as measured by|when|where|because|since|"
    r"which|that|whose|only|because)(?![a-z])|\d", re.IGNORECASE)


def _undefined_comparison(sentence):
    """The tallied comparison this sentence makes without saying on what axis, or "".

    Only the text AFTER the verb is searched for the axis. "In the youngest subgroup
    six of the ten favour the feature arm" names a stratum, not a dimension, and the
    sentence still does not say what favouring means."""
    match = _TALLIED_COMPARISON_RE.search(sentence)
    if not match:
        return ""
    tail = sentence[match.end():]
    if _DIMENSION_CUE_RE.search(tail):
        return ""
    return match.group(1).lower()


# A weld is a semicolon INSIDE a line. One at the end of a line is list punctuation —
# the conventional way to separate the items of an enumeration — and counting it drives
# a writer away from the bulleted list that fixes the long sentence in the first place.
_SEMICOLON_RE = re.compile(r";(?![ \t]*(?:\n|$))")

# A dash weld joins two CLAUSES, and that is the only thing this ration is about. The
# en-dash has two other jobs in a quantitative paper and neither of them is a weld:
#
#   * a RANGE, between numbers — "0.643–0.672", "12–22 words", "2016–2024". Every
#     confidence interval, percentage band, year span, page range and quintile
#     boundary contains one. Counting them measured the density of the RESULTS rather
#     than of the prose, so a section reporting forty intervals scored as forty welds
#     and could not be brought under the ration by any amount of rewriting.
#   * a COMPOUND, tight between two words — "precision–recall curve",
#     "nearest–farthest fusion", "anchor–neighbor pair". The dash makes one term out of
#     two coordinate ones. Renaming the analysis to satisfy the gate is not a prose
#     improvement.
#
# Both were found by pointing the gate at a real manuscript, and both are the same
# defect: a gate that fires on correct text teaches the writer to damage it.
#
# What remains is the aside, and the rule that separates it is typographic rather than
# semantic, which is what makes it checkable. An EM-dash is always a weld, spaced or
# not, because the aside is the only job it has. An EN-dash is a weld only when it is
# spaced, because tight en-dashes are the range and the compound above. A spaced double
# hyphen is an em-dash somebody could not type.
_NUMERIC_RANGE_RE = re.compile(
    r"(?<![\w])[−+-]?[\d][\d,.]*\s?%?\s?[—–]\s?[−+-]?[\d][\d,.]*\s?%?")
_TIGHT_ENDASH_RE = re.compile(r"(?<=\w)–(?=\w)")
_EMDASH_RE = re.compile(r"[—–]|(?<=\s)--(?=\s)")


def _dash_welds(text):
    """Dashes that join two clauses. Ranges and tight compounds are not welds."""
    body = _NUMERIC_RANGE_RE.sub(" ", text)
    body = _TIGHT_ENDASH_RE.sub("", body)
    return _EMDASH_RE.findall(body)


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


# Words that assert the two things are the SAME, as against words that say no
# difference was found. The distinction is the whole of the check: "the two tie", "a
# null result", "no advantage was detected" are all honest reports of a wide interval.
# "Parity", "equivalent", "as good as", "no different from" are claims about the world,
# and a claim about the world needs a test designed to support it.
_EQUIVALENCE_WORDS = (
    "parity", "equivalent", "equivalence", "equally good", "as good as",
    "no different from", "no different than", "statistically equivalent",
    "identical performance", "the same performance", "interchangeable",
    "on par with", "on a par with", "noninferior", "non-inferior",
)
_EQUIVALENCE_RE = re.compile(
    r"(?<![a-z])(?:" + "|".join(w.replace(" ", r"\s+") for w in _EQUIVALENCE_WORDS) +
    r")(?![a-z])", re.IGNORECASE)

# The sentence a careful paper writes, and the reason this check can exist at all: it
# is the paper telling us, in its own Methods, that the vocabulary above is unavailable
# to it. Without this disclaimer the gate has no ground to stand on and stays silent —
# a paper that DID prespecify a margin is entitled to every word in the list.
_NO_MARGIN_RE = re.compile(
    r"no\s+(?:formal\s+)?(?:equivalence|noninferiority|non-inferiority)"
    r"(?:\s+or\s+(?:equivalence|noninferiority|non-inferiority))?\s+"
    r"(?:margin|bound|threshold|test)\w*\s+(?:was|were|is|are)?\s*"
    r"(?:pre-?specified|specified|set|defined|declared|prespecified)",
    re.IGNORECASE)

# A sentence may name the word in order to REFUSE it. "Absence of an advantage is not
# equivalence" is the correct sentence, and refusing it would be the gate demanding the
# paper stop saying the true thing.
# The window is generous, and generous is the right direction here. "It is not that
# the two representations are equivalent" puts five words between the negation and the
# word. A false negative leaves one overclaim standing; a false positive tells an
# author to delete the sentence that correctly refuses the overclaim.
_DISAVOWAL_RE = re.compile(
    r"(?:not|never|cannot|can\s*not|rather\s+than|no)\b[^.;:]{0,70}?"
    r"(?:parity|equivalen\w*|noninferior\w*|non-inferior\w*|on\s+a?\s*par\b)"
    r"|(?:parity|equivalen\w*)[^.;:]{0,40}?(?:was|were|is|are)\s+not",
    re.IGNORECASE)


def equivalence_overclaim(text):
    """Sentences claiming equivalence in a document that disclaims an equivalence test.

    A whole-document check, not a per-sentence one, because the licence lives in the
    Methods and the claim lives in the Discussion. It returns nothing unless the
    document itself says no margin was prespecified — which is the paper handing over
    the evidence against its own vocabulary.

    The failure this was written from: a manuscript whose Methods said "no equivalence
    or noninferiority margin was prespecified" and whose Limitations carried the
    heading "Absence of an advantage is not equivalence", while the word "parity"
    appeared sixteen times in between. The analysis was right and the vocabulary
    asserted something the analysis could not support, and no gate could see it because
    every sentence was individually defensible.

    Returns a list of (sentence, word)."""
    body = prose.strip_structure(text)
    if not _NO_MARGIN_RE.search(body):
        return []
    out = []
    for sentence in prose.sentences(body):
        match = _EQUIVALENCE_RE.search(sentence)
        if not match:
            continue
        if _DISAVOWAL_RE.search(sentence):
            continue                    # the paper refusing the word, correctly
        out.append((sentence, match.group(0).lower()))
    return out


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
    dense_paragraphs: list = field(default_factory=list)  # (opening sentence, mean, n)
    anticipatory: list = field(default_factory=list)    # (sentence, phrase)
    undefined_comparisons: list = field(default_factory=list)  # (sentence, verb)
    unreported: list = field(default_factory=list)      # (sentence, phrase)
    wordy_ratios: list = field(default_factory=list)     # (sentence, phrase)
    passed: bool = True
    reasons: list = field(default_factory=list)

    def brief(self):
        """One line of measurements, for a log."""
        return (f"{self.count} sentences, mean {self.mean:.1f} words "
                f"(sd {self.stdev:.1f}), longest {self.longest}, "
                f"{self.long_share:.0%} over {config.SENTENCE_LONG_WORDS}, "
                f"{self.semicolons_per_kword:.1f} semicolons and "
                f"{self.emdashes_per_kword:.1f} dashes per 1,000 words")


def _dense_paragraphs(text):
    """Paragraphs whose own mean is over the local ceiling, worst first.

    A section mean is an average over every sentence in the section, so twenty easy
    sentences buy one unreadable paragraph. This is the same measurement taken where
    the reader actually takes it. List blocks are skipped: a bulleted enumeration is
    not a paragraph and its items are not sentences."""
    out = []
    for block in prose.paragraphs(text):
        if prose.is_list_item(block):
            continue
        sents = prose.sentences(block)
        if len(sents) < config.PARAGRAPH_DENSITY_MIN_SENTENCES:
            continue
        mean = statistics.fmean(len(s.split()) for s in sents)
        if mean > config.PARAGRAPH_MEAN_WORDS_MAX:
            out.append((sents[0], round(mean, 2), len(sents)))
    return sorted(out, key=lambda row: row[1], reverse=True)


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
    dashes = len(_dash_welds(body)) * per_kword

    openers = [(s, phrase) for s in sents if (phrase := _empty_opener(s))]
    hedged = [s for s in sents if _hedge_count(s) >= 2]
    dense = _dense_paragraphs(text)
    defensive = [(s, phrase) for s in sents
                 if (phrase := next((a for a in _ANTICIPATORY if a in s.lower()), ""))]
    vague = [(s, verb) for s in sents if (verb := _undefined_comparison(s))]
    unreported = [(s, phrase) for s in sents
                  if (phrase := _unreported_analysis(s))]
    ratios = [(s, phrase) for s in sents if (phrase := _wordy_ratio(s))]
    welded = [s for s in sents
              if _SEMICOLON_RE.search(s) or _dash_welds(s)]

    report = SentenceReport(
        words=n_words, count=len(sents), mean=round(mean, 2),
        median=round(median, 1), stdev=round(stdev, 2), longest=longest,
        long_share=round(long_share, 4),
        semicolons_per_kword=round(semis, 2), emdashes_per_kword=round(dashes, 2),
        over_hard_max=over_hard, long_sentences=long_ones,
        empty_openers=openers, stacked_hedges=hedged, welded=welded,
        dense_paragraphs=dense, anticipatory=defensive,
        undefined_comparisons=vague, unreported=unreported,
        wordy_ratios=ratios)

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
    if dense:
        worst_open, worst_mean, worst_n = dense[0]
        reasons.append(
            f"{len(dense)} paragraph(s) average over "
            f"{config.PARAGRAPH_MEAN_WORDS_MAX:.0f} words per sentence, the worst at "
            f"{worst_mean:.1f} across {worst_n} sentences. The section average hides "
            f"it and the reader does not read the average. It opens "
            f"\"{worst_open[:70]}...\"")
    if defensive:
        reasons.append(
            f"{len(defensive)} sentence(s) argue with a reviewer who has not spoken "
            f"({', '.join(sorted({p for _, p in defensive})[:3])}). Make the claim "
            f"and let it stand.")
    if unreported:
        phrases = ', '.join(sorted({p for _, p in unreported})[:3])
        reasons.append(
            f"{len(unreported)} sentence(s) describe an analysis and then decline to "
            f"report it ({phrases}). Report it or do not mention it. A result whose "
            f"evidence is a mailing address is not a result the paper can claim.")
    if ratios:
        phrases = ', '.join(sorted({p for _, p in ratios})[:3])
        reasons.append(
            f"{len(ratios)} sentence(s) state a ratio in words and no number "
            f"({phrases}). Write the two figures. A quantity spelled out is still a "
            f"quantity, and spelled out is how it gets past the numbers gate.")
    if vague:
        verbs = ', '.join(sorted({v for _, v in vague})[:3])
        reasons.append(
            f"{len(vague)} comparison(s) never say on what axis ({verbs}). Name the "
            f"dimension the comparison runs on, or the number in front of it is "
            f"precision about nothing.")

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
    for sentence, _ in report.anticipatory:
        scored[sentence] = scored.get(sentence, 0) + 2
    for sentence, _ in report.undefined_comparisons:
        scored[sentence] = scored.get(sentence, 0) + 2
    for sentence, _ in report.unreported:
        scored[sentence] = scored.get(sentence, 0) + 3
    for sentence, _ in report.wordy_ratios:
        scored[sentence] = scored.get(sentence, 0) + 2
    for sentence, _, _ in report.dense_paragraphs:
        scored[sentence] = scored.get(sentence, 0) + 2
    ranked = sorted(scored.items(),
                    key=lambda kv: (kv[1], len(kv[0].split())), reverse=True)
    return [s for s, _ in ranked[:count]]
