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
  * **welds** — semicolons and em-dashes per thousand words, counted outside captions.
    Both are almost always two sentences pretending to be one, except in a caption,
    where a semicolon is a panel label and the convention is the journal's.
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

# A threshold invoked by name and never given a value.
#
# "The embedded representation runs below the conventional events-per-variable
# threshold by construction on three of the four encoders." Below WHAT? The reader is
# asked to accept a comparison against a number the sentence declines to state, and in
# this manuscript the number — 10 — was sitting in a supplement section the sentence
# does not point at. Every ingredient of a checkable claim was present except the one
# that makes it checkable.
#
# The pattern is narrow on purpose: a threshold noun, qualified by a word that appeals
# to convention rather than to a value, in a sentence carrying no number of its own. A
# threshold the paper defines elsewhere in the same sentence is fine, and a threshold
# stated outright is the thing this gate is asking for.
_VAGUE_THRESHOLD_RE = re.compile(
    r"(?<![a-z])(?:conventional|standard|accepted|usual|customary|typical|"
    r"recommended|traditional|nominal|established|common)\s+"
    r"(?:[a-z-]+\s+){0,3}"
    r"(?:threshold|cut-?off|criteri(?:on|a)|limit|floor|ceiling|bound|minimum|maximum)"
    r"|(?<![a-z])(?:threshold|cut-?off|criteri(?:on|a))\s+"
    r"(?:is\s+)?(?:conventionally|customarily|usually|typically)\s+"
    r"(?:used|applied|accepted|taken)",
    re.IGNORECASE)

# The value has to sit NEXT TO the threshold, not merely somewhere in the sentence.
# The version of this check that accepted any digit anywhere passed the sentence it was
# written for: "runs below the conventional events-per-variable threshold ... (EPV
# 1.5-2.3), whereas the feature-vector model comfortably exceeds it at 65" is full of
# numbers and states the bar nowhere. Those numbers are the measurements being
# compared, which is exactly the sentence shape that makes the missing bar invisible.
_NEARBY_NUMBER_AFTER = re.compile(r"^[^.]{0,28}?\d")
_NEARBY_NUMBER_BEFORE = re.compile(r"\d[^.]{0,28}?$")


def _vague_threshold(sentence):
    """A threshold appealed to by convention and never given, or ""."""
    match = _VAGUE_THRESHOLD_RE.search(sentence)
    if not match:
        return ""
    if _NEARBY_NUMBER_AFTER.search(sentence[match.end():]):
        return ""
    if _NEARBY_NUMBER_BEFORE.search(sentence[:match.start()]):
        return ""
    return " ".join(match.group(0).split()).lower()


# A prediction the paper cannot support, standing where a finding should be.
#
# "That constraint is a property of the tooling and is likely to move." Move which
# way, by when, on what evidence? It means context windows will get bigger, it carries
# no citation and no timeframe, and it closed the paragraph — the position where what
# a limitation MEANS is supposed to go. A methods paper asserting that technology will
# improve is speculation wearing the clothes of a result.
#
# The distinction that keeps this usable: a RECOMMENDATION is not a FORECAST. "Future
# work should test whether a longer context changes this" proposes an experiment and a
# reader can act on it. "Context lengths will improve" predicts the world and a reader
# can only wait. The first is what a Discussion is for; the second is what this
# refuses. So the check fires on predictive verbs about capability, and never on
# should/could/would proposals.
_FORECAST_RE = re.compile(
    r"(?<![a-z])(?:is|are|seems?)\s+(?:likely|expected|set|bound|certain)\s+to\s+"
    r"(?:move|improve|change|grow|increase|expand|shift|ease|fall|rise|close|narrow)"
    r"|(?<![a-z])will\s+(?:likely\s+|probably\s+|soon\s+|eventually\s+)?"
    r"(?:improve|change|move|grow|increase|expand|ease|close|narrow|resolve|disappear)"
    r"|(?<![a-z])as\s+(?:models|encoders|tooling|hardware|methods|context\s+windows|"
    r"these\s+tools)\s+(?:improve|mature|advance|grow)"
    r"|(?<![a-z])in\s+the\s+(?:coming|next\s+few)\s+(?:years|months)"
    r"|(?<![a-z])it\s+is\s+only\s+a\s+matter\s+of\s+time",
    re.IGNORECASE)

# A citation makes it somebody's forecast on the record rather than the authors' guess,
# which is a different sentence and not this gate's business.
_HAS_CITATION_RE = re.compile(r"\[\s*\d|@[A-Za-z]|\(\s*[A-Z][A-Za-z'\u2019-]+[,\s]")


def _forecast(sentence, previous=""):
    """A prediction about future capability, carrying no source, or "".

    The source may sit in the sentence before. "Context length has grown steadily
    across model generations [12]. It will likely improve further." is one citation
    covering a trend and the inference drawn from it, which is how a citation attaches
    in ordinary academic prose, so the window is two sentences rather than one."""
    match = _FORECAST_RE.search(sentence)
    if not match:
        return ""
    if _HAS_CITATION_RE.search(sentence) or _HAS_CITATION_RE.search(previous or ""):
        return ""
    return " ".join(match.group(0).split()).lower()


# The same word twice, which a hard-wrapped file hides at a line break.
#
# "none exceeds 0.012 ROC\nROC AUC" and "differed by at most 0.005 ROC\nROC AUC" both
# shipped in one manuscript, three of them in total. A doubled word is invisible on a
# read-through precisely because the reader's eye supplies the sentence it expected,
# and it is trivial to find by machine, which is the whole argument for machines.
#
# The list of exceptions is short and every entry is a word English really does
# double: "had had", "that that", "very very".
_DOUBLE_OK = {"had", "that", "very", "no", "so", "long"}
_DOUBLED_RE = re.compile(r"(?<![\w-])([A-Za-z][\w-]{1,})\s+\1(?![\w-])")


def _doubled_word(sentence):
    """The word this sentence says twice in a row, or "". Case-sensitive on purpose:
    "That that" opening a clause is ordinary and "the The" is a typo."""
    for match in _DOUBLED_RE.finditer(sentence):
        if match.group(1).lower() in _DOUBLE_OK:
            continue
        return match.group(1)
    return ""


# A hedge, then a sentence retracting what the hedge already declined to claim.
#
# "This pattern is consistent with a decision boundary efficiently captured by a
# regularized linear model. It does not establish that the latent clinical structure
# is intrinsically linear, since differences in regularization, dimensionality, and
# inductive bias provide alternative explanations."
#
# The first sentence says "consistent with", which by definition establishes nothing.
# The second spends twenty-five words un-claiming something nobody claimed. This is
# the stacked hedge again, split across a full stop so that the per-sentence check
# cannot see it, and the repair is always to delete the second sentence.
_SOFT_CLAIM_RE = re.compile(
    r"(?<![a-z])(?:consistent\s+with|compatible\s+with|suggests?|suggestive|may\s+"
    r"reflect|might\s+reflect|could\s+reflect|points?\s+toward|is\s+in\s+keeping"
    r"\s+with|appears?\s+to)(?![a-z])", re.IGNORECASE)
_RETRACTION_RE = re.compile(
    r"^\s*(?:it|this|that|the\s+\w+)\s+(?:does|do)\s+not\s+"
    r"(?:establish|prove|show|demonstrate|imply|mean|entail|confirm)"
    r"|^\s*(?:it|this|that)\s+is\s+not\s+evidence\b"
    r"|^\s*(?:none|neither)\s+of\s+(?:this|these|that)\s+(?:establishes|proves|"
    r"shows|demonstrates)", re.IGNORECASE)


def _stacked_across_sentences(sentences):
    """Sentences that retract a claim the sentence before them never made.

    Returns a list of (retracting sentence, the soft claim it follows)."""
    out = []
    for prev, cur in zip(sentences, sentences[1:]):
        if _RETRACTION_RE.match(cur) and _SOFT_CLAIM_RE.search(prev):
            out.append((cur, " ".join(_SOFT_CLAIM_RE.search(prev).group(0).split())))
    return out


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
    # "more" and "less" belong here. "Roughly three times more precise than comparing
    # the marginal intervals" sat in a figure caption, unsupported, and was the inverse
    # of a claim already cut from the body two sentences away.
    r"(?:two|three|four|five|six|seven|eight|nine|ten)\s+times\s+(?:the|as|more|less|"
    r"wider|narrower|larger|smaller|longer|higher|lower)",
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

# A caption's semicolons are labels, not welds.
#
# "Discrimination by representation and classifier (held-out test set, n = 8,516;
# primary Qwen3-Embedding-8B encoder)" and "(A) pre-index history length; (B)
# MDD-to-index gap; (C) encounter count" are the two shapes, and between them they
# accounted for every semicolon in a Results section that the ration refused. A caption
# is a labelled enumeration by convention, the convention is the journal's rather than
# the author's, and the only repair available to a writer is to damage the caption.
#
# So the RATION is counted over prose with the captions removed. Everything else about
# a caption is still measured — its sentence lengths, its openers, its hedges — because
# a caption a reader cannot parse is a real defect. Only the weld budget forgives it.
_CAPTION_BLOCK_RE = re.compile(
    r"^\s*\*{2,3}\s*(?:Table|Figure|Fig\.?|Panel)\b.*?\*\s*$",
    re.MULTILINE | re.DOTALL)


# A parenthetical is already a subordinate aside, so a semicolon inside one cannot be
# welding two independent clauses. It is separating items: "(236 carried 90%; Figure
# 7)", "(held-out test set; primary Qwen3-Embedding-8B encoder)". Blanking the contents
# rather than deleting them keeps every other measurement — word counts, sentence
# boundaries — exactly where it was.
#
# **A NEWLINE INSIDE THE PARENTHESIS IS STILL THE SAME PARENTHESIS.** Drafted prose
# arrives hard-wrapped, so a parenthetical that begins two thirds of the way along a
# line is routinely split across two of them. Excluding the newline from the contents
# switched the whole exemption off for exactly those, silently, and a supplement
# section scored 2.5 semicolons per thousand words on one wrapped pointer pair —
# "(Methods, *Predictors and patient representations*; Discussion, *Principal
# findings*)". The only repair available to a writer there is to damage the
# cross-reference. `prose.collapse_pattern` makes the same allowance for the same
# reason: whitespace is whitespace, and where the line happens to end is not a fact
# about the prose.
_PAREN_RE = re.compile(r"\(([^()]{0,200}?)\)", re.DOTALL)


def _weld_body(text):
    """The prose a weld ration applies to: not a caption, not inside a parenthesis."""
    body = _CAPTION_BLOCK_RE.sub(" ", text)
    return _PAREN_RE.sub(lambda m: "(" + m.group(1).replace(";", ",") + ")", body)

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
# The adverb slips past a word-boundary match: "the models perform EQUIVALENTLY
# across sexes" is the claim, and "equivalent" with a trailing letter class does not
# see it. An optional -ly is all it takes and it costs nothing.
_EQUIVALENCE_RE = re.compile(
    r"(?<![a-z])(?:" + "|".join(w.replace(" ", r"\s+") for w in _EQUIVALENCE_WORDS) +
    r")(?:ly)?(?![a-z])", re.IGNORECASE)

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


# "Equivalently, the outcome required at least 2 post-index antidepressant changes."
# That is a restatement connective — "put another way" — and it is the false positive
# the -ly widening bought. A performance claim never opens a sentence with the adverb
# and a comma; a restatement always does.
_RESTATEMENT_RE = re.compile(r"^\s*Equivalently\s*,", re.IGNORECASE)


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
        if _RESTATEMENT_RE.match(sentence):
            continue                    # "Equivalently, ..." is "put another way"
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
    doubled: list = field(default_factory=list)          # (sentence, word)
    split_hedges: list = field(default_factory=list)     # (sentence, claim)
    forecasts: list = field(default_factory=list)        # (sentence, phrase)
    vague_thresholds: list = field(default_factory=list)  # (sentence, phrase)
    passed: bool = True
    reasons: list = field(default_factory=list)

    def brief(self):
        """One line of measurements, for a log."""
        return (f"{self.count} sentences, mean {self.mean:.1f} words "
                f"(sd {self.stdev:.1f}), longest {self.longest}, "
                f"{self.long_share:.0%} over {config.SENTENCE_LONG_WORDS}, "
                f"{self.semicolons_per_kword:.1f} semicolons and "
                f"{self.emdashes_per_kword:.1f} dashes per 1,000 words")


def _floor_body(text):
    """The prose the mean-length FLOOR applies to: not a caption.

    A caption's length is set by convention rather than by the writer's rhythm.
    "***Table A1.** Quantitative predictors (15; continuous, standardized).*" is eight
    words because that is what a table label is, and no amount of writing makes it
    longer. The CEILING still counts captions, because a caption a reader cannot parse
    on one pass is a real defect. The floor cannot, because it exists to catch prose
    that has gone clipped, and a section that is mostly tables is nearly all caption.

    A predictor inventory in a real manuscript measured 10.8 words per sentence
    against a floor of 12, on five table captions plus five sentences of prose that
    average twenty. The only repair the gate left was to pad the captions."""
    return _CAPTION_BLOCK_RE.sub(" ", text)


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

    floor_sents = prose.sentences(_floor_body(body))
    floor_mean = (statistics.fmean(len(s.split()) for s in floor_sents)
                  if floor_sents else mean)

    ration_body = _weld_body(body)
    per_kword = 1000.0 / max(len(ration_body.split()), 1)
    semis = len(_SEMICOLON_RE.findall(ration_body)) * per_kword
    dashes = len(_dash_welds(ration_body)) * per_kword

    openers = [(s, phrase) for s in sents if (phrase := _empty_opener(s))]
    hedged = [s for s in sents if _hedge_count(s) >= 2]
    dense = _dense_paragraphs(text)
    defensive = [(s, phrase) for s in sents
                 if (phrase := next((a for a in _ANTICIPATORY if a in s.lower()), ""))]
    vague = [(s, verb) for s in sents if (verb := _undefined_comparison(s))]
    unreported = [(s, phrase) for s in sents
                  if (phrase := _unreported_analysis(s))]
    ratios = [(s, phrase) for s in sents if (phrase := _wordy_ratio(s))]
    doubled = [(s, w) for s in sents if (w := _doubled_word(s))]
    split_hedges = _stacked_across_sentences(sents)
    forecasts = [(s, ph) for prev, s in zip([""] + sents, sents)
                 if (ph := _forecast(s, prev))]
    thresholds = [(s, ph) for s in sents if (ph := _vague_threshold(s))]
    caption_free = _weld_body(body)
    welded = [s for s in sents
              if (_SEMICOLON_RE.search(s) or _dash_welds(s)) and s in caption_free]

    report = SentenceReport(
        words=n_words, count=len(sents), mean=round(mean, 2),
        median=round(median, 1), stdev=round(stdev, 2), longest=longest,
        long_share=round(long_share, 4),
        semicolons_per_kword=round(semis, 2), emdashes_per_kword=round(dashes, 2),
        over_hard_max=over_hard, long_sentences=long_ones,
        empty_openers=openers, stacked_hedges=hedged, welded=welded,
        dense_paragraphs=dense, anticipatory=defensive,
        undefined_comparisons=vague, unreported=unreported,
        wordy_ratios=ratios, doubled=doubled, split_hedges=split_hedges,
        forecasts=forecasts, vague_thresholds=thresholds)

    reasons = []
    if mean > config.SENTENCE_MEAN_WORDS_MAX:
        reasons.append(
            f"sentences average {mean:.1f} words; the ceiling is "
            f"{config.SENTENCE_MEAN_WORDS_MAX:.0f}. Split the longest ones — a "
            f"sentence carrying two claims is two sentences.")
    if floor_mean < config.SENTENCE_MEAN_WORDS_MIN:
        reasons.append(
            f"sentences average {floor_mean:.1f} words outside the captions; the "
            f"floor is {config.SENTENCE_MEAN_WORDS_MIN:.0f}. This reads as clipped "
            f"rather than clear. Let the sentences that carry a real claim run.")
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
    if doubled:
        words = ', '.join(sorted({f'"{w} {w}"' for _, w in doubled})[:3])
        reasons.append(
            f"{len(doubled)} sentence(s) repeat a word ({words}). A hard wrap hides "
            f"this from every reader and from no machine.")
    if thresholds:
        phrases = ', '.join(sorted({p for _, p in thresholds})[:3])
        reasons.append(
            f"{len(thresholds)} sentence(s) compare against a threshold and never "
            f"say what it is ({phrases}). Below what? Give the number in the sentence "
            f"that leans on it.")
    if forecasts:
        phrases = ', '.join(sorted({p for _, p in forecasts})[:3])
        reasons.append(
            f"{len(forecasts)} sentence(s) predict the future with no source "
            f"({phrases}). A reader can act on \"future work should test X\" and can "
            f"only wait for \"X will improve\". Say what the limitation means for "
            f"this paper instead.")
    if split_hedges:
        reasons.append(
            f"{len(split_hedges)} sentence(s) retract a claim the sentence before "
            f"them never made. The first already said '{split_hedges[0][1]}', which "
            f"establishes nothing. Delete the retraction rather than stacking a "
            f"second hedge behind a full stop.")
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
    for sentence, _ in report.doubled:
        scored[sentence] = scored.get(sentence, 0) + 3
    for sentence, _ in report.split_hedges:
        scored[sentence] = scored.get(sentence, 0) + 2
    for sentence, _ in report.forecasts:
        scored[sentence] = scored.get(sentence, 0) + 2
    for sentence, _ in report.vague_thresholds:
        scored[sentence] = scored.get(sentence, 0) + 2
    for sentence, _, _ in report.dense_paragraphs:
        scored[sentence] = scored.get(sentence, 0) + 2
    ranked = sorted(scored.items(),
                    key=lambda kv: (kv[1], len(kv[0].split())), reverse=True)
    return [s for s, _ in ranked[:count]]
