"""The venue gate — the journal's own rules, checked before anybody submits.

Every other gate here asks whether the manuscript is good. This one asks whether the
journal will accept the file at all, which is a different question and is answered by
an editorial assistant in about ninety seconds.

**The failure it was written from.** A manuscript went through two full redrafts, every
gate in this project passing on both, carrying an abstract of 810 words against a
venue ceiling of 450. It had been over the ceiling before either redraft and got 41%
worse during them, because nothing was counting. It also carried four URLs in its body
against a checklist that says all URLs are cited as references, and it was missing a
mandatory Abbreviations section outright. None of those is a hard problem to fix. All
of them are desk rejections or fee letters, and all of them were invisible to a
pipeline whose only notion of a venue was one integer called `word_limit`.

**What this gate does not do.** It does not judge. Nothing here is a matter of taste
or of quality; every check is "the venue said a number and the manuscript is on the
wrong side of it". That is what makes the gate cheap to trust and cheap to update: when
a journal changes a rule, one number moves in `venues.py` and the reasoning is a URL.

**Advisory limits are reported, not enforced.** A venue that *recommends* 10,000 words
and charges a fee above it has not set a ceiling, and a gate that blocked there would
refuse legitimate manuscripts. It warns, and it says what the consequence is, because
"you will be invoiced" is the information the author actually needs.

**An unknown venue fails.** Not silently, and not with a pass. Writing to a journal
nobody has profiled is ordinary; doing it while being told the manuscript is compliant
is how the 810-word abstract survived.
"""

import re
from dataclasses import dataclass, field

from .. import venues
from . import prose


@dataclass
class VenueReport:
    venue: str
    passed: bool
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


# A manuscript's own top-level headings, so the gate can find its abstract and its
# body without being handed them separately. `prose.strip_structure` is not used here:
# this gate wants the structure.
_HEADING = re.compile(r"^(#{1,2})\s+(.+?)\s*$", re.M)

# Sections that are not body prose for the purpose of a word count. The venue counts
# what a reader reads, and a reference list is not that.
_NOT_BODY = ("title page", "references", "abbreviations")


def sections(text):
    """The manuscript as {heading: body}, in order, comments and code fences gone."""
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
    text = re.sub(r"^```.*?^```\s*$", "", text, flags=re.S | re.M)
    out, last, start = {}, None, 0
    for m in _HEADING.finditer(text):
        if last is not None:
            out[last] = text[start:m.start()]
        last, start = m.group(2).strip(), m.end()
    if last is not None:
        out[last] = text[start:]
    return out


def abstract_of(parts):
    for heading, body in parts.items():
        if heading.strip().lower() == "abstract":
            return body
    return ""


def body_of(parts):
    """Everything a reader reads, which is not the same as everything in the file."""
    keep = []
    for heading, body in parts.items():
        low = heading.strip().lower()
        if any(low.startswith(x) for x in _NOT_BODY):
            continue
        if low.startswith("multimedia appendix"):
            continue
        keep.append(body)
    return "\n".join(keep)


def _abstract_words(abstract, headings):
    """The abstract's own words, with the venue's structural labels removed.

    The labels are the venue's, not the author's, so counting them against the
    author's allowance is charging them for the form."""
    stripped = abstract
    for h in headings or ():
        stripped = stripped.replace(f"**{h}.**", "").replace(f"**{h}:**", "")
    stripped = re.sub(r"^\*\*Keywords\.\*\*.*", "", stripped, flags=re.S | re.M)
    return len(stripped.split())


def check(text, venue, profile=None, today=None):
    """Check a manuscript against its venue's stated requirements.

    `text` is the assembled manuscript. `venue` is what the plan says the venue is.
    `profile` overrides the lookup, for a venue the library does not hold."""
    profile = profile or venues.profile_for(venue)
    errors, warnings, stats = [], [], {}

    if profile is None:
        return VenueReport(
            venue=str(venue or "(none stated)"), passed=False,
            errors=[f"no venue profile for {venue!r}. The journal's own limits are "
                    f"therefore unchecked, and an abstract over its ceiling is a desk "
                    f"rejection no other gate here can see. Add a profile to "
                    f"`paperwriter/venues.py` with the URL you read it from and the "
                    f"date, or pass one explicitly."])

    defects = venues.profile_defects(profile)
    if defects:
        return VenueReport(venue=profile.get("name", str(venue)), passed=False,
                           errors=[f"the venue profile is unusable: {d}"
                                   for d in defects])

    age = venues.staleness_days(profile, today=today)
    if age is not None and age > venues.PROFILE_STALE_DAYS:
        warnings.append(
            f"the profile for {profile['name']} was read {age} days ago from "
            f"{profile['source'].split(',')[0]}. Journals revise their instructions on "
            f"no schedule; re-read it before submitting.")

    parts = sections(text)
    abstract = abstract_of(parts)
    body = body_of(parts)

    # 1. The abstract: length, then structure.
    if profile["abstract_max_words"] is not None:
        n = _abstract_words(abstract, profile["abstract_headings"])
        stats["abstract_words"] = n
        limit = profile["abstract_max_words"]
        if not abstract.strip():
            errors.append("the manuscript has no Abstract section.")
        elif n > limit:
            errors.append(
                f"the abstract runs {n:,} words against this venue's ceiling of "
                f"{limit:,}. This is checked by an editorial assistant before a "
                f"reviewer sees the paper.")

    for heading in profile["abstract_headings"] or ():
        if f"**{heading}.**" not in abstract and f"**{heading}:**" not in abstract:
            errors.append(
                f"the abstract has no `{heading}` heading. This venue requires a "
                f"structured abstract with "
                f"{', '.join(profile['abstract_headings'])}, in that order.")

    # 2. Keywords.
    kw = re.search(r"\*\*Keywords\.?\*\*(.*?)(?:\n\n|\Z)", text, re.S)
    count = len([k for k in kw.group(1).split(";") if k.strip()]) if kw else 0
    stats["keywords"] = count
    lo, hi = profile["keywords_min"], profile["keywords_max"]
    if lo is not None and count < lo:
        errors.append(f"{count} keyword(s); this venue asks for {lo} to {hi}.")
    elif hi is not None and count > hi:
        errors.append(f"{count} keywords; this venue allows at most {hi}.")

    # 3. The body. Hard limits block; advisory ones warn and say what they cost.
    if profile["body_max_words"] is not None:
        n = prose.word_count(prose.strip_structure(body))
        stats["body_words"] = n
        limit = profile["body_max_words"]
        if n > limit:
            note = (f"the body runs {n:,} words against this venue's "
                    f"{limit:,}. {profile['body_limit_consequence']}")
            (errors if profile["body_limit_is_hard"] else warnings).append(note)

    # 4. Everything the venue counts, when it states a count at all.
    for key, label, pattern in (
            ("references_max", "references", r"^\d+\.\s+\S"),
            ("figures_max", "figures", r"\*\*\*Figure \d+\.\*\*"),
            ("tables_max", "tables", r"\*\*\*Table \d+\.\*\*")):
        found = len(re.findall(pattern, text, re.M))
        stats[label] = found
        cap = profile[key]
        if cap is not None and found > cap:
            errors.append(f"{found} {label} against this venue's limit of {cap}.")

    # 5. Required sections, where the venue requires them.
    for label, pattern, where in profile["required_sections"] or ():
        haystack = text
        if where == venues.IN_METHODS:
            haystack = "\n".join(b for h, b in parts.items()
                                 if h.strip().lower().startswith("method"))
        elif where == venues.IN_DECLARATIONS:
            haystack = "\n".join(b for h, b in parts.items()
                                 if h.strip().lower().startswith("declaration"))
        if not re.search(pattern, haystack):
            errors.append(
                f"no `{label}` section" + ("" if where == venues.ANYWHERE
                                           else f" in the {where}")
                + f". This venue lists it as mandatory.")

    # 6. URLs in the body. The commonest way to break this is a Methods section that
    #    names its own code repository, which reads as good practice and is not what
    #    the venue asked for.
    if not profile["urls_in_body_allowed"]:
        found = re.findall(r"https?://[^\s)\]>]+", body)
        stats["body_urls"] = len(found)
        if found:
            shown = ", ".join(sorted(set(found))[:4])
            errors.append(
                f"{len(found)} URL(s) in the body: {shown}. This venue requires every "
                f"URL to be cited as a reference instead.")

    # 7. Title length, when the venue states one.
    if profile["title_max_chars"] is not None:
        m = re.search(r"\*\*Title\.?\*\*\s*(.+?)(?:\n\n|\Z)", text, re.S)
        if m:
            title = " ".join(m.group(1).split())
            stats["title_chars"] = len(title)
            if len(title) > profile["title_max_chars"]:
                errors.append(
                    f"the title is {len(title)} characters against this venue's "
                    f"{profile['title_max_chars']}.")

    return VenueReport(venue=profile["name"], passed=not errors, errors=errors,
                       warnings=warnings, stats=stats)
