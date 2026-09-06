"""Venue profiles — what each journal actually requires, with its source.

A manuscript can be true, well argued, well written, and desk-rejected before a
reviewer opens it because its abstract runs 810 words against a 450-word ceiling. That
happened to the paper this harness was built from, and it survived two rounds of
redrafting because nothing in the pipeline held the venue's rules anywhere a check
could reach them. The word limit lived in the plan as a single integer, `word_limit`,
and it was the only requirement the harness knew.

So the rules live here, one profile per venue, and `gates/venue.py` checks a built
manuscript against them.

**Every profile carries its source and the date it was read.** A journal's
requirements change, a profile written from memory is worse than no profile, and the
only defence against both is a URL and a date the next reader can check. A profile
older than `VENUE_PROFILE_STALE_DAYS` is reported as stale rather than trusted.

**`None` means the venue states no limit. A missing key means nobody looked.** That
distinction is the whole design. A gate that silently skips what it does not know
reports a clean manuscript and means "I checked the things I happened to have"; the
`REQUIRED_KEYS` check below refuses a profile that has not decided, so an unchecked
requirement is a visible hole rather than an invisible one.

**An unknown venue does not pass.** `profile_for` returns None and the gate says so.
Writing to a venue nobody has profiled is a normal thing to do, and doing it without
being told which rules are unverified is not.
"""

from datetime import date

# A profile older than this is reported as stale. Journals revise their instructions
# on no schedule at all, and a year is long enough that a limit may have moved without
# anybody noticing. Not an error: a stale profile is still better than none, and the
# gate says which it is.
PROFILE_STALE_DAYS = 400

# Where a required section has to appear. `anywhere` is the ordinary case; a venue that
# demands its ethics statement inside the Methods rather than in the back matter is
# making a structural requirement, and checking only for the words satisfies it wrongly.
ANYWHERE, IN_METHODS, IN_DECLARATIONS = "anywhere", "methods", "declarations"

# Every key a profile must decide. A profile missing one is a profile that has not been
# finished, and the gate refuses it rather than checking the subset it happens to hold.
REQUIRED_KEYS = (
    "name", "source", "checked",
    "abstract_max_words", "abstract_headings",
    "keywords_min", "keywords_max",
    "body_max_words", "body_limit_is_hard", "body_limit_consequence",
    "title_max_chars", "references_max", "figures_max", "tables_max",
    "required_sections", "urls_in_body_allowed",
)


JMIR = {
    "name": "JMIR (Journal of Medical Internet Research and sibling journals)",
    "source": "https://www.jmir.org/author-information/instructions-for-authors, "
              "https://www.jmir.org/author-information/submission-preparation-checklist, "
              "and the JMIR Publications support knowledge base "
              "(Manuscript Length and Word Count Guidelines; Guidelines for writing "
              "abstracts)",
    "checked": date(2026, 9, 6),

    # Structured, and the five headings are named in the venue's own order. The order
    # matters: JMIR calls this BOMRC and a reader of the abstract alone depends on it.
    "abstract_max_words": 450,
    "abstract_headings": ("Background", "Objective", "Methods", "Results",
                          "Conclusions"),

    "keywords_min": 5,
    "keywords_max": 10,

    # NOT a hard limit, and the profile says so rather than pretending. JMIR strongly
    # recommends 10,000 words for an original paper and charges additional editorial
    # and production fees above it. A gate that blocked here would refuse a legitimate
    # manuscript; one that said nothing would let an author discover the fee at
    # invoice.
    "body_max_words": 10000,
    "body_limit_is_hard": False,
    "body_limit_consequence": "JMIR strongly recommends 10,000 words for an original "
                              "paper and charges additional editorial and production "
                              "fees above it. This is a cost, not a rejection.",

    # Not stated by the venue. `None` here is a decision, not an omission.
    "title_max_chars": None,
    "references_max": None,
    "figures_max": None,
    "tables_max": None,

    # The submission checklist is explicit: no URLs in the body, all URLs cited as
    # references. This is the requirement most likely to be broken by a methods
    # section that names its own code repository, which is exactly how it was broken
    # in the manuscript that produced this module.
    "urls_in_body_allowed": False,

    # Mandatory sections, as the venue names them. The regexes are what the gate
    # matches, and they are deliberately loose about British/American spelling and
    # about "Author" against "Authors'", because refusing a manuscript over an
    # apostrophe is a gate nobody keeps.
    "required_sections": (
        ("Abbreviations", r"\bAbbreviations?\b", ANYWHERE),
        ("Conflicts of Interest", r"Conflicts? of [Ii]nterest", ANYWHERE),
        ("Data Availability", r"Data availability", ANYWHERE),
        ("Author Contributions", r"Authors?'? contributions", ANYWHERE),
        ("Funding Statement", r"\*\*Funding\.?\*\*|Funding [Ss]tatement", ANYWHERE),
        ("Ethical Considerations", r"Ethic(?:s|al)", ANYWHERE),
    ),
}


# Keyed by the lowercased venue name a plan or grounding document states. Substring
# matching, because "JMIR Mental Health" and "JMIR Formative Research" share one set of
# author instructions and a profile per sibling journal would be five copies to keep in
# step.
PROFILES = {
    "jmir": JMIR,
}


def profile_for(venue):
    """The profile for a stated venue, or None when nobody has written one.

    None is the honest answer and the gate reports it as one. Guessing a profile from
    the venue's name would produce exactly the failure this module exists to prevent:
    a manuscript reported as compliant against rules nobody checked."""
    name = str(venue or "").strip().lower()
    if not name:
        return None
    for key, profile in PROFILES.items():
        if key in name:
            return profile
    return None


def profile_defects(profile):
    """Why a profile cannot be trusted, as a list. Empty when it is well formed."""
    if not profile:
        return ["no profile"]
    missing = [k for k in REQUIRED_KEYS if k not in profile]
    if missing:
        return [f"the profile does not decide {', '.join(missing)}. A key that is "
                f"absent is a requirement nobody looked up; write `None` to record "
                f"that the venue states no limit."]
    return []


def staleness_days(profile, today=None):
    """How old the profile is, in days."""
    checked = profile.get("checked")
    if not isinstance(checked, date):
        return None
    return ((today or date.today()) - checked).days
