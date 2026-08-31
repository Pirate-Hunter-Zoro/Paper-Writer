"""Reading the dropped prompt file.

A job is one markdown file in `inbox/`, filled from PROMPT_TEMPLATE.md. Two things
have to be extracted from it deterministically before any model is involved: which
source universe(s) to research, and which entities the canon must therefore cover.
Both feed gates, so both are parsing — not judgment — and both are unit-tested.

Deliberately separate from the research stage: this is "what did the human ask
for", which the coverage gate, the planner, and the delivery folder layout all
need to agree on, and none of them should be reaching into a stage module for it.
"""

import re

_HEADER_RE = re.compile(r"^\s*#+\s*(.+?)\s*$", re.MULTILINE)

# Words that are never a universe or a character on their own. Two groups: template
# scaffolding ("(agent's choice)") and ordinary prose; then words that describe the
# *shape of the story* rather than anything in the fandom.
#
# That second group is scar tissue. "Act" (from "the Knight's Act 3") and "Rise" (from
# "Rise of the Hutt Cartel") were left in as harmless on 2026-08-04, on the reasoning
# that a couple of junk entities fit inside the coverage gate's slack. They did not:
# the run parked at 84.2% against an 85% floor, and those two were a third of the
# shortfall. Junk in the denominator is not free.
_STOP = {"the", "and", "with", "for", "agent", "choice", "none", "his", "her",
         "their", "team", "core", "povs", "as", "antagonists",
         "act", "rise", "part", "arc", "scene", "chapter", "book", "volume",
         "prologue", "epilogue", "phase", "stage", "beat", "beats",
         # Prepositions that open a list header — "From Gravity Falls: ..." is a
         # heading, and "From Gravity Falls" is not a thing any wiki has a page for.
         "from", "in", "of", "by", "featuring"}

# Markdown formatting and list markers sit between a sentence boundary and the word
# that follows it, so they have to be looked through, not at.
_FORMATTING = "*_`#>-•+ \t"

# A capitalised name span, allowing internal hyphens and apostrophes.
#
# The hyphen is not a nicety. Without it "She-Ra" scans as the word "She" and then
# stops, so a She-Ra crossover produced the entities "She", "Princesses", and "Power"
# — three denominator terms in the 85% coverage gate that no canon fact can ever
# match, out of a section that named one show correctly. Hyphenated names are
# ordinary in this domain (She-Ra, Obi-Wan, Spider-Man, Hop Pop's world is full of
# them), so the pattern has to admit them or every such fandom pays a penalty for
# being spelled the way it is spelled.
_NAME_RE = r"\b[A-Z][A-Za-z]*(?:[-'][A-Za-z]+)*(?:\s+[A-Z][A-Za-z]*(?:[-'][A-Za-z]+)*)*\b"


def _opens_a_phrase(prefix):
    """Whether the text so far leaves the next word opening a sentence, line, or bold
    run — where a lone capitalised word is usually prose ("This is a central thread",
    "Stay strictly consistent", "**Act 1 —**") rather than a name."""
    trimmed = prefix.rstrip(_FORMATTING)
    return not trimmed or trimmed[-1] in ".!?:;—–\n"


def sections(prompt_text):
    """Split a filled prompt template into {header_lower: body_text}."""
    out = {}
    matches = list(_HEADER_RE.finditer(prompt_text))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(prompt_text)
        out[m.group(1).strip().lower()] = prompt_text[start:end].strip()
    return out


def section_matching(secs, *needles):
    """The body of the first section whose header contains any needle."""
    for header, body in secs.items():
        if any(nd in header for nd in needles):
            return body
    return ""


def universes(prompt_text):
    """The source universe(s) named in the prompt.

    Reads only the FIRST non-empty line of the 'source universe(s)' section — any
    following lines are description, not a list — and splits a crossover on '+' or
    '/' only. NOT on commas, newlines, or ' and ', all of which occur inside
    ordinary prose. A trailing qualifier after a spaced dash is dropped ("Star
    Wars: The Old Republic — Sith Warrior story" -> the title) but a colon is kept.

    The narrowness is scar tissue: on 2026-08-04 a prose-y section body was shredded
    into eight junk universes, and each one got its own canon directory and its own
    research call."""
    body = section_matching(sections(prompt_text), "source universe", "universe")
    first = ""
    for line in body.splitlines():
        if line.strip():
            first = line.strip()
            break
    first = re.sub(r"[*_`]", "", first)               # strip markdown emphasis
    first = re.sub(r"\(.*?\)", "", first)             # drop a parenthetical abbrev
    seen, out = set(), []
    for part in re.split(r"[+/]", first):            # crossover connectors only
        name = re.split(r"\s[—–-]\s", part.strip())[0]   # drop ' — qualifier'
        name = name.strip().strip(".").strip()
        if len(name) >= 3 and name.lower() not in seen and name.lower() not in _STOP:
            seen.add(name.lower())
            out.append(name)
    return out


def art_direction(prompt_text):
    """The art style this job asks for, from its 'Illustrations' section, or "" to
    fall back to config.IMAGE_STYLE.

    The style block is stamped on every image prompt, so getting it from the job
    rather than from global config is the difference between a Star Wars novelization
    illustrated as painterly key art and the same book illustrated as cel-shaded
    anime because that is what the last fic wanted. Reads from `Style:` onward when
    the section labels it, since the text before that is usually the image *count*.
    """
    body = section_matching(sections(prompt_text), "illustration")
    if not body:
        return ""
    body = re.sub(r"[*_`]", "", body)                  # strip markdown emphasis
    match = re.search(r"style\s*:\s*", body, re.IGNORECASE)
    if match:
        body = body[match.end():]
    return " ".join(body.split())                     # collapse wrapped lines


_NO_ORIGINALS_RE = re.compile(
    r"original\s+characters?\s*[:\-]\s*(none|no\b|nil|n/a)", re.IGNORECASE)


def forbids_original_characters(prompt_text):
    """Whether this job has declared that its cast is the source's cast, full stop.

    Written as an explicit declaration rather than inferred, because the two jobs it
    distinguishes want opposite things and guessing wrong ruins a book either way.

    The planning gate requires the book's biggest villain to be INVENTED, and its
    reasoning is sound for the job it was written for: a crossover whose ceiling is a
    villain the reader already knows the limits of has no room to escalate past their
    canon. Assembled entirely out of other people's antagonists, it has nothing at
    stake the source shows have not already settled.

    For a straight NOVELIZATION that reasoning inverts completely. The canon villain
    is the entire point, the canon limits are what the reader came for, and an invented
    Sith Lord placed above the Emperor is not escalation — it is the failure mode. A
    novelization of the Jedi Knight story planned under the crossover rule produced
    exactly that: a wholly original Darth outranking Darth Angral, in a book whose
    prompt said "Original characters: none."

    So the job says which kind it is, in its own words, in the section that already
    lists the cast:

        Original characters: none.

    Absent the declaration the crossover rule applies, which is the safe default — it
    is the stricter of the two, and it is what every job written before this existed
    was planned under."""
    body = section_matching(sections(prompt_text), "main character", "character")
    return bool(_NO_ORIGINALS_RE.search(body or ""))


def main_characters(prompt_text):
    """The named cast from the prompt's 'Main characters to feature' section.

    Used to gate the anchor state for coverage: a principal the job explicitly names
    and whose starting position nobody wrote down is the exact hole that stage exists
    to close. Deliberately reads only the comma-separated name list and stops at the
    first paragraph break, because these sections routinely continue into prose about
    how to handle the relationships, and a sentence is not a character."""
    body = section_matching(sections(prompt_text), "main character", "characters to")
    if not body:
        return []
    body = re.sub(r"[*_`]", "", body).strip()
    listing = body.split("\n\n", 1)[0]               # the names, not the notes after
    # Collapse the wrap BEFORE splitting. These sections are hard-wrapped prose, so a
    # two-word name lands across a line break as often as not — "Polly\nPlantar" split
    # on newlines gives two characters, neither of whom exists. This project has paid
    # for the same mistake in `implied_entities` already.
    listing = " ".join(listing.split())
    names = []
    for chunk in listing.split(","):
        name = chunk.strip().strip(_FORMATTING).strip()
        # The full stop that ends the sentence belongs to the sentence, not to the last
        # name in it. Without this the final entry in every roster fails the name
        # pattern and is dropped — silently, and always the same one, so it looks like
        # a deliberate omission rather than a parse failure. The live crossover lost
        # Swift Wind to it: named in the prompt, absent from the anchor gate's coverage
        # check, and therefore never gated for having a starting position at all.
        name = name.rstrip(".").strip()
        if not name or " " not in name and name.lower() in _STOP:
            continue
        # A real name is one or more capitalised words; anything with a verb in it is
        # a sentence that wandered in.
        if re.fullmatch(_NAME_RE, name) and len(name) < 40:
            names.append(name)
    seen, out = set(), []
    for name in names:
        if name not in seen:
            seen.add(name); out.append(name)
    return out


def implied_entities(prompt_text):
    """The characters and places the prompt implies canon must cover, pulled from the
    'main characters' and 'canon anchor point' sections as capitalised name spans.

    Blunt on purpose, but not sloppy: every name here becomes a denominator term in
    the canon-coverage gate, and an entity that no fact could ever match is a free
    penalty against a perfectly good job. So three things are enforced —

      * whitespace inside a name is collapsed, because the section text is hard
        wrapped and a name split across a line yielded "Jedi\\nOrder", which the
        coverage regex could never match against "Jedi Order";
      * sections are joined with a full stop rather than a space, so a name cannot
        glue onto the next section's opening word ("Weiss Schnee After");
      * a lone capitalised word that opens a sentence, line, or bold run is dropped,
        because that is prose ("This is a central thread" -> "This"). A multi-word
        span in the same position is kept — "Master Orgus Din" is a name wherever
        it appears.
    """
    secs = sections(prompt_text)
    body = " . ".join([
        section_matching(secs, "main character", "character"),
        section_matching(secs, "canon anchor", "anchor"),
    ])
    seen, out = set(), []
    for match in re.finditer(_NAME_RE, body):
        span = " ".join(match.group(0).split())        # collapse wrapped whitespace
        # A leading stopword is scaffolding, not part of the name: a section that
        # lists "From Gravity Falls: Dipper Pines, ..." yields the header as an
        # entity, and no wiki has a page for "From Gravity Falls". Strip and keep
        # what is left, rather than discarding a span that contains a real name.
        words = span.split()
        while words and words[0].lower() in _STOP:
            words.pop(0)
        name = " ".join(words)
        # A possessive is the same entity wearing an apostrophe. The name pattern admits
        # apostrophes on purpose — this domain is full of O'Briens and She-Ras — so
        # "Wendy Corduroy's ushanka" yields "Wendy Corduroy's" as an entity *distinct
        # from* "Wendy Corduroy", and no canon fact can ever match it. Every one of
        # those is a free penalty in the coverage gate's denominator, which is the same
        # arithmetic that parked a perfectly good run at 84% against an 85% floor.
        name = re.sub(r"['’]s?$", "", name).strip()
        low = name.lower()
        if not name or low in _STOP or low in seen or len(name) < 3:
            continue
        if all(word.lower() in _STOP for word in words):
            continue
        # The lone-capitalised-word rule is about what the SPAN looked like in the
        # text, not what is left after stripping. "From She-Ra" opening a line is a
        # list header containing a real name; judging the stripped "She-Ra" as a lone
        # word at the start of a line throws the name away with the scaffolding.
        if " " not in span and _opens_a_phrase(body[:match.start()]):
            continue                                   # prose, not a name
        seen.add(low)
        out.append(name)
    return out
