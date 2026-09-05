"""Reading the dropped prompt file.

A job is one markdown file in the inbox, filled from PROMPT_TEMPLATE.md. A few things
have to be extracted from it deterministically before any model is involved: which
evidence corpora to gather, which claims the paper intends to make, the target venue
and its word limit, and how many papers this job is. All of them feed gates, so all of
them are parsing — not judgement — and all of them are unit-tested.

Deliberately separate from the gathering stage: this is "what did the human ask for",
which the coverage gate, the planner, the length gates and the delivery folder layout
all need to agree on, and none of them should be reaching into a stage module for it.

**On why the parsers are narrow.** Every value here becomes a denominator or a
threshold somewhere. A claim that no evidence could ever match is a free penalty
against a perfectly good job, and a mis-parsed word limit is a manuscript planned to
the wrong length. So each parser reads one section, takes the shape it is documented
to take, and refuses to guess — a job that omits a field gets the documented default,
which is always the permissive one.
"""

import re

_HEADER_RE = re.compile(r"^\s*#+\s*(.+?)\s*$", re.MULTILINE)

# Markdown formatting and list markers sit between a boundary and the text after it,
# so they have to be looked through, not at.
_FORMATTING = "*_`#>-•+ \t"


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


def _clean(line):
    """One line with markdown emphasis and list markers stripped."""
    return re.sub(r"[*_`]", "", line).strip().strip(_FORMATTING).strip()


def _bullets(body):
    """The bullet or numbered list items in a section body, in order.

    Wrapped continuation lines are folded into the item above them, because these
    sections are hard-wrapped prose as often as not and half a claim on its own line
    is a claim no evidence can cover."""
    items, current = [], None
    for raw in (body or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            if current:
                items.append(current)
                current = None
            continue
        if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line):
            if current:
                items.append(current)
            current = _clean(re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line))
        elif current is not None and line.startswith((" ", "\t")):
            current = f"{current} {_clean(line)}".strip()
        elif current is not None:
            current = f"{current} {_clean(line)}".strip()
    if current:
        items.append(current)
    return [i for i in items if i]


def corpora(prompt_text):
    """The evidence corpus name(s) this job draws on.

    Read from the 'Evidence' section's first non-empty line, split only on `+` and
    `/`. NOT on commas, newlines, or " and ", all of which occur inside ordinary
    prose — a prose-y section body shredded into eight junk corpora is eight evidence
    directories and eight gathering calls.

    A job that names none gets one corpus named after nothing in particular, because
    a paper written against unnamed evidence is still a paper and the coverage gate
    will say so more usefully than a parse error would."""
    body = section_matching(sections(prompt_text), "evidence", "data source",
                            "analysis")
    first = ""
    for line in body.splitlines():
        if line.strip():
            first = line.strip()
            break
    first = re.sub(r"[*_`]", "", first)
    first = re.sub(r"\(.*?\)", "", first)          # drop a parenthetical abbreviation
    seen, out = set(), []
    for part in re.split(r"[+/]", first):
        name = re.split(r"\s[—–-]\s", part.strip())[0].strip().strip(".").strip()
        if len(name) >= 3 and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out or (["primary"] if prompt_text.strip() else [])


def intended_claims(prompt_text):
    """The claims the job says the paper will make, one per bullet.

    These are the denominator of the evidence coverage gate. Read only from the
    'Claims' section and only as list items, because a paragraph of context about why
    the work matters is not a claim, and counting it as one penalises a well-written
    brief."""
    body = section_matching(sections(prompt_text), "claim", "what the paper argues",
                            "findings to report")
    return [c for c in _bullets(body) if len(c.split()) >= 3]


_VENUE_LIMIT_RE = re.compile(
    r"(\d[\d,]{2,})\s*(?:-|\s)?\s*word", re.IGNORECASE)


def venue(prompt_text):
    """The target journal or conference, as a name, or "".

    The journal name, without the submission rules that follow it. Journals state the
    name and the word limit in one breath — "JMIR Mental Health. 4,000 word limit" —
    and the name is what goes into a brief and onto a title page. A venue that carries
    its own submission rules around reads, in every prompt it is quoted into, as though
    the rules were part of the journal's name.

    The cut is made at the first sentence that STARTS WITH A NUMBER, rather than at the
    first full stop. A full stop is not a sentence boundary in a journal name — `J. Am.
    Med. Inform. Assoc.` is five of them and one name — and a limit clause always opens
    on its figure."""
    body = section_matching(sections(prompt_text), "venue", "target journal",
                            "journal")
    for line in body.splitlines():
        cleaned = _clean(line)
        if not cleaned:
            continue
        cleaned = re.split(r"\s[—–-]\s", cleaned)[0].strip()
        match = re.search(r"(?<=[.!?;])\s+(?=\d)", cleaned)
        return (cleaned[:match.start()] if match else cleaned).strip()
    return ""


def word_limit(prompt_text):
    """The venue's total word limit, or None.

    Read from anywhere in the Venue section, because journals state it in prose and
    the sentence it lives in varies. The first number followed by "word" wins, which
    is the documented shape and the only one worth supporting: a limit stated two
    different ways in one section is a job that needs a human, not a cleverer parser.
    """
    body = section_matching(sections(prompt_text), "venue", "target journal",
                            "journal", "length")
    match = _VENUE_LIMIT_RE.search(body or "")
    if not match:
        return None
    try:
        value = int(match.group(1).replace(",", ""))
    except ValueError:
        return None
    # A "word limit" under 250 is an abstract's, not a manuscript's, and enforcing it
    # on the whole paper would plan a four-paragraph submission.
    return value if value >= 250 else None


_PAPER_COUNT_RE = re.compile(r"\b(\d+)\s+papers?\b", re.IGNORECASE)


def paper_count(prompt_text):
    """How many papers this job is. One unless it says otherwise.

    A single paper is the normal case and a one-paper project is the degenerate case
    of the general machinery, exactly as a standalone book is a one-book series. There
    is no separate code path and there must not be one."""
    body = section_matching(sections(prompt_text), "paper", "scope", "deliverable")
    match = _PAPER_COUNT_RE.search(body or "")
    if match:
        try:
            count = int(match.group(1))
            return count if 1 <= count <= 12 else 1
        except ValueError:
            return 1
    return 1


def reference_docx(prompt_text):
    """A path to the journal's reference .docx, if the job names one, else ""."""
    body = section_matching(sections(prompt_text), "venue", "target journal",
                            "format", "template")
    match = re.search(r"(\S+\.docx)", body or "")
    return match.group(1) if match else ""


def checklist(prompt_text):
    """The reporting checklist this job declares, or "".

    Named rather than inferred. Inferring it from the study design is a guess that
    produces an outline placing the wrong obligations, and the cost of asking is one
    line in a template."""
    body = section_matching(sections(prompt_text), "checklist", "reporting",
                            "guideline")
    for line in (body or "").splitlines():
        cleaned = _clean(line)
        if cleaned:
            return cleaned
    return ""


def title(prompt_text):
    """The working title, from the first heading or the Title section."""
    body = section_matching(sections(prompt_text), "title", "working title")
    for line in (body or "").splitlines():
        cleaned = _clean(line)
        if cleaned:
            return cleaned
    match = _HEADER_RE.search(prompt_text or "")
    return match.group(1).strip() if match else ""
