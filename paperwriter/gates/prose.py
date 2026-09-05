"""Splitting prose into the units every other gate counts: words, sentences,
paragraphs.

One module, because three gates were about to grow three slightly different sentence
splitters and then disagree about how many sentences a section has. A gate that
reports "eleven sentences" and another that reports "nine" over the same text is a
gate nobody trusts, and an editor handed both is being asked to repair a contradiction.

Pure functions. No config, no I/O, no model — everything here is a fact about a
string.

**On abbreviations.** A naive split on `[.!?]` cuts "et al." and "vs." and "Fig. 3"
into extra sentences, and in academic prose those are everywhere. Every extra false
boundary shortens the measured mean sentence length, which is the one number the
density gate turns on — so a Methods section thick with abbreviations would measure
as crisp prose while reading like a wall. The abbreviation list below is not
exhaustive and does not need to be: it covers what actually appears in a manuscript,
and a missed one costs a fraction of a word on a mean computed over hundreds of
sentences.
"""

import re

_WORD_RE = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*")

# Abbreviations whose full stop does not end a sentence. Lowercased, without the dot.
_ABBREVIATIONS = {
    # scholarly
    "et al", "e.g", "i.e", "cf", "viz", "vs", "etc", "ibid", "op. cit", "n.b",
    # structural references
    "fig", "figs", "tab", "eq", "eqs", "ref", "refs", "sec", "ch", "no", "nos",
    "vol", "p", "pp", "suppl", "app",
    # titles and names
    "dr", "prof", "mr", "mrs", "ms", "st", "jr", "sr", "mt",
    # units and statistics that carry a stop
    "approx", "min", "max", "avg", "std", "sd", "se", "ci", "df", "ns",
}

# A stop that is part of a number (3.14), an initial (J. R. Smith), or an ellipsis is
# never a boundary either.
_SENTENCE_END = re.compile(r"""
    (?<=[.!?])                # a terminator
    ["'’”)\]]*      # closing quotes or brackets ride with it
    \s+                       # whitespace is what makes it a boundary
    (?=[\"'‘“(\[]*[A-Z0-9])   # the next sentence starts capitalised
""", re.VERBOSE)


def words(text):
    """The word tokens of a string. Numbers are not words — they are measured by
    `gates.numbers`, and counting them here would let a results table full of figures
    inflate a section's word count."""
    return _WORD_RE.findall(text or "")


def word_count(text):
    return len(words(text))


def _ends_on_abbreviation(chunk):
    """Whether a candidate sentence ends on something that is not a sentence end."""
    tail = chunk.rstrip()
    if not tail.endswith("."):
        return False
    # The token before the stop, lowercased and stripped of everything but letters
    # and interior dots ("e.g." -> "e.g").
    last = re.split(r"[\s(\[]", tail[:-1])[-1].lower().strip("\"'“‘([")
    if last in _ABBREVIATIONS:
        return True
    # A single letter followed by a stop is an initial: "J. R. Smith".
    if len(last) == 1 and last.isalpha():
        return True
    # A number followed by a stop is a decimal that lost its fraction, or a list
    # marker. Either way it is not the end of a sentence.
    if last.replace(".", "").isdigit():
        return True
    return False


def sentence_spans(text):
    """Every sentence of a block, as (start, end, raw, tidy).

    `raw` is the substring exactly as it appears in `text`, line breaks and all.
    `tidy` is the same sentence with whitespace collapsed.

    Both are needed and they are not interchangeable. Every measurement wants `tidy`,
    because a sentence hard-wrapped across three lines is one sentence. Every edit
    ANCHOR wants `raw`, because `stages.patching` applies a repair by finding the
    anchor in the draft character-for-character and refuses one that does not match.
    Handing the editor a tidied sentence as an anchor produces a repair that is
    silently rejected, and a defect that is reported every pass and never fixed.

    Offsets are into `text` as given, so a caller that passed the stripped body can
    map a match position back to the sentence it fell in."""
    if not (text or "").strip():
        return []
    body = text
    bounds = [0] + [m.end() for m in _SENTENCE_END.finditer(body)] + [len(body)]
    spans, start = [], None
    for i in range(len(bounds) - 1):
        lo, hi = bounds[i], bounds[i + 1]
        if start is None:
            start = lo
        chunk = body[start:hi]
        if not chunk.strip():
            start = None
            continue
        if _ends_on_abbreviation(chunk) and i + 2 < len(bounds):
            continue                # glue the next piece on and keep looking
        raw = chunk.strip()
        offset = start + (len(chunk) - len(chunk.lstrip()))
        spans.append((offset, offset + len(raw), raw, " ".join(raw.split())))
        start = None
    return spans


def sentences(text):
    """A block of prose as its list of sentences, whitespace collapsed.

    Markdown structure is skipped rather than counted: a heading, a table row, a
    fenced code block and a bare citation line are not sentences, and letting them in
    would let a Results section full of tables measure as short, punchy prose."""
    return [tidy for _, _, _, tidy in sentence_spans(strip_structure(text))]


def sentence_at(spans, pos):
    """The (raw, tidy) sentence containing a character offset, or ("", "")."""
    for start, end, raw, tidy in spans:
        if start <= pos < end:
            return raw, tidy
    return "", ""


def collapse_pattern(phrase):
    """A regex matching a phrase as whole words, whatever whitespace runs through it.

    Drafted prose arrives hard-wrapped as often as not, so "treatment-resistant
    depression" appears in the file with a newline in the middle of it. A pattern
    built from the phrase verbatim does not match, and the gate that was looking for
    it reports the term as never defined. That failure is invisible on a read-through
    and produces a defect the editor cannot repair, because there is nothing wrong."""
    parts = [re.escape(p) for p in phrase.strip().split()]
    return re.compile(r"(?<![\w-])" + r"\s+".join(parts) + r"(?![\w-])",
                      re.IGNORECASE)


_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
_TABLE_RE = re.compile(r"^\s*\|")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def strip_structure(text):
    """The prose of a Markdown block: no headings, tables, fences, or comments.

    Everything that measures prose measures this, so a section is judged on the
    sentences a reader actually reads."""
    body = _HTML_COMMENT_RE.sub("", text or "")
    kept, in_fence = [], False
    for line in body.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or _HEADING_RE.match(line) or _TABLE_RE.match(line):
            continue
        kept.append(line)
    return "\n".join(kept)


def paragraphs(text):
    """A section as its list of paragraphs: blank-line separated blocks of prose.

    List items are one paragraph each. A run of them is not a paragraph, and treating
    it as one would report a Declarations section as a single 40-sentence monster."""
    blocks, current = [], []
    for line in strip_structure(text).splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                blocks.append(" ".join(current))
                current = []
            continue
        if _is_list_item(stripped) and current:
            blocks.append(" ".join(current))
            current = [stripped]
            continue
        current.append(stripped)
    if current:
        blocks.append(" ".join(current))
    return [" ".join(b.split()) for b in blocks if b.strip()]


_LIST_ITEM_RE = re.compile(r"^([-*+]\s|\d+[.)]\s)")


def _is_list_item(line):
    return bool(_LIST_ITEM_RE.match(line))


def is_list_item(paragraph):
    """Whether a paragraph is really a list entry. Exempt from paragraph shape rules:
    a bullet has no topic sentence and is not supposed to."""
    return _is_list_item(paragraph.strip())


def anchorable(text, sentence):
    """Whether a sentence can be used as an edit anchor in `text`.

    It can when it appears exactly once. The editorial loop repairs by anchored
    find/replace and `stages.patching` refuses an anchor that matches twice rather
    than guessing which one was meant, so a repeated sentence is not usable and
    offering one to the editor wastes a slot."""
    return bool(sentence) and (text or "").count(sentence) == 1


def unique_sentences(text):
    """Sentences that appear exactly once in the text, longest first, verbatim.

    Verbatim matters: these become edit anchors, and an anchor is matched
    character-for-character against the draft."""
    body = text or ""
    counts = {}
    for _, _, raw, _ in sentence_spans(strip_structure(body)):
        counts[raw] = counts.get(raw, 0) + 1
    unique = [s for s, n in counts.items() if n == 1 and body.count(s) == 1]
    unique.sort(key=lambda s: len(s.split()), reverse=True)
    return unique
