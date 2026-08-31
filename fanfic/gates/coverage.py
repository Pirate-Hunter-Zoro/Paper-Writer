"""Canon coverage gate — refuse to draft on a shaky foundation.

Hard problem 2 is canon fidelity, and the first line of defence is refusing to
start a book whose canon is thin. After research writes a cited canon reference,
this gate checks that the facts actually cover the entities the prompt implies —
the named characters, locations, and events. Below the configured floor the series
parks rather than drafting a fic on lore it never gathered (an anticipated failure
the README calls out: "a whole book drafted on thin canon").

Coverage is deliberately a blunt, deterministic measure: for each implied entity,
is there at least one canon fact that names it? Whether the *depth* is adequate is
a judgment call for a model critic; this is the cheap arithmetic floor beneath
that, and it needs no model to test.
"""

import re
from dataclasses import dataclass

from .. import config


def _haystack(fact):
    return " ".join(str(fact.get(k, "")) for k in ("subject", "text", "category"))


def _names(text, entity):
    """Whether `text` contains `entity` as a whole word or phrase."""
    return re.search(r"\b" + re.escape(entity) + r"\b", text, re.IGNORECASE) is not None


def _mentions(fact, entity):
    """Whether a single canon fact names an entity, as an exact phrase."""
    return _names(_haystack(fact), entity)


# Words that prefix a name without being part of how canon usually refers to someone.
_TITLES = {"sergeant", "master", "grand", "lord", "darth", "sith", "jedi", "emperor",
           "captain", "general", "admiral", "doctor", "doc", "padawan", "the", "of",
           "old", "new", "high", "dark", "light"}


def _significant_tokens(entity):
    """The parts of a multi-word entity that actually identify it — the words canon has
    to contain somewhere for the entity to be considered covered."""
    return [w for w in entity.split()
            if len(w) >= 4 and w.lower() not in _TITLES]


def _covered_by(canon_text, facts, entity):
    """Whether canon covers an entity.

    Exact phrase first. Failing that, for a multi-word entity, whether every one of its
    identifying words appears *somewhere* in canon — not necessarily adjacent, and not
    necessarily in one fact.

    That fallback is not slack, it is accuracy. On 2026-08-04 a genuinely good canon of
    207 cited facts was rejected at 84.2% because the gate wanted the literal strings
    "Sergeant Rusk", "Sith Emperor Vitiate", "Hutt Cartel", and "Old Republic", while
    canon — correctly — wrote "Rusk", "Vitiate", "Hutt", and "Republic". Demanding the
    prompt's exact phrasing penalises research for using canonical naming, which is the
    opposite of what this gate is for. Canon that mentions none of an entity's
    identifying words still fails, which is the case the gate exists to catch."""
    if any(_mentions(fact, entity) for fact in facts):
        return True
    if " " not in entity.strip():
        return False            # a single word had its one chance above
    tokens = _significant_tokens(entity)
    if not tokens:
        return False            # nothing but titles: the phrase was all we had
    return all(_names(canon_text, token) for token in tokens)


@dataclass
class CoverageReport:
    total: int
    covered: int
    ratio: float
    missing: list          # implied entities with no covering fact
    passed: bool


def check(canon, implied_entities):
    """Fraction of implied entities that have at least one covering canon fact,
    gated against config.CANON_COVERAGE_MIN. Returns a CoverageReport."""
    entities = [e for e in dict.fromkeys(implied_entities) if e and e.strip()]
    facts = canon.get("facts", [])
    canon_text = " ".join(_haystack(f) for f in facts)
    missing = [e for e in entities if not _covered_by(canon_text, facts, e)]
    total = len(entities)
    covered = total - len(missing)
    ratio = 1.0 if total == 0 else covered / total
    return CoverageReport(
        total=total, covered=covered, ratio=round(ratio, 4),
        missing=missing, passed=ratio >= config.CANON_COVERAGE_MIN,
    )
