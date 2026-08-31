"""The interaction coverage gate — arithmetic over the meta plan's ledger.

A crossover is bought for its collisions. Nothing downstream would ever ask for one on
its own: a beat sheet optimises for plot, and "Dipper finally works a problem with
Entrapta" is not a plot beat, it is the reason somebody opened the book. So the
collisions are planned up front, one per scene segment, and this module checks that the
plan is actually a crossover rather than four casts taking turns.

Every check here is counting. No model, no I/O, no judgement — which matters because
this is the gate a 180-entry ledger has to clear, and a gate that needed judgement at
that size would be another model call arguing with the first one.

What it enforces, and why each one exists:

  * **Nobody is a guest star.** Every locked character appears in at least
    `PLAN_MIN_APPEARANCES` interactions. The last attempt listed characters who then
    went the whole book without a scene anybody had asked for.
  * **Groupings vary.** A core party may recur, up to a budget; past that a repeat
    is not a payoff. The same three people having a
    second scene is the book doing something it has already done.
  * **Sizes vary.** A ledger of nothing but two-handers is as broken as one of nothing
    but ensembles — the first is a book with no crowd scenes and the second is a book
    where nobody ever gets a conversation.
  * **Most of it crosses universes.** Chapter 1 of the last attempt was 100% Owl
    House, and nothing anywhere checked.
  * **Every pairing of worlds gets a real share.** Six cross-show pairings, and one
    token scene each is not the book that was promised.
  * **Enough of it is physical, and it escalates.** Every check above counts *who* is
    in a scene. None of them counts what the scene does, and a ledger can satisfy all
    of them while being two hundred conversations — which is exactly what the last
    book was. See `REGISTERS`.

Exhaustive pairing coverage is neither achievable nor desirable and is not attempted:
52 characters is 1,326 possible pairs and most of them are worthless. At ~180
interactions averaging three people, roughly 500–600 distinct pairs are realised — 40%
of the space — and every character shares real page time with about fifteen others.
"""

from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations

from .. import config


@dataclass
class LedgerReport:
    passed: bool
    errors: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


ORIGINAL = "original"

# What a scene DOES, as opposed to who is in it.
#
# Every other rule in this module counts people. A ledger can put the right characters
# in the right rooms in the right numbers across the right worlds and still be two
# hundred conversations, because nothing was ever counted about the event itself. That
# is not a hypothetical: the previous book cleared every coverage gate here and shipped
# with ~2 physical verbs per chapter across its first forty chapters, with the fighting
# scheduled into the last five. The register is the missing dimension.
#
# Kept to five, and deliberately unambiguous, because this is a label a model assigns
# ~200 times and a taxonomy with fine distinctions collects everything in whichever bin
# is easiest to justify.
REGISTERS = ("physical", "conflict", "investigation", "comic", "tender")

# The gated one. `physical` means bodies at risk or at work: a fight, a chase, a
# rescue, an escape, a hard physical task under time pressure. An argument is not
# physical however loud it gets — that is `conflict`, and letting the two blur is how
# the floor gets satisfied on paper by more people shouting in rooms.
PHYSICAL = "physical"

UNSET = "(unset)"


def register_of(entry):
    """One entry's declared register, normalised. `UNSET` when absent or unknown.

    Tolerant rather than strict because `stats` is also used to *steer* a half-built
    ledger, and a chunk that has just come back malformed still has to be countable
    enough to describe. `check` is where an unset register becomes an error."""
    value = str(entry.get("register") or "").strip().lower()
    return value if value in REGISTERS else UNSET


def _origins(who, cast_origins):
    return {cast_origins.get(name, "") for name in who if cast_origins.get(name)}


def is_cross_universe(who, cast_origins):
    """Whether one interaction puts people from different worlds together.

    Originals count as their own world: a new antagonist meeting Adora is exactly the
    kind of collision this book is being written for, and calling it a within-cast
    scene would be wrong in both directions."""
    return len(_origins(who, cast_origins)) >= 2


def halfway(entries):
    """The last chapter number that counts as this book's front half.

    Derived from the ledger rather than passed in, because the meta plan owns the
    chapter count and picks it in its own first chunk — asking a caller for it would
    mean two documents holding the same number. A ledger still being built reports the
    halfway point of what exists so far, which is the correct thing to steer against:
    the front half of ten committed chapters is the first five of them."""
    chapters = [e.get("chapter") for e in entries
                if isinstance(e.get("chapter"), int)]
    return (max(chapters) + 1) // 2 if chapters else 0


def stats(entries, cast_origins, universes):
    """Everything the gate counts, so a proposer can be told where it stands.

    Separate from `check` on purpose: this is what steers each chunk of the meta plan
    as it is written, and a coverage gate that can only speak at the end is a gate that
    can only reject."""
    total = len(entries)
    appearances = Counter()
    sizes = Counter()
    pairings = Counter()
    registers = Counter()
    cross = 0
    mid = halfway(entries)
    front = front_physical = back = back_physical = 0
    for entry in entries:
        who = list(dict.fromkeys(entry.get("who") or []))
        for name in who:
            appearances[name] += 1
        sizes[len(who)] += 1
        origins = _origins(who, cast_origins)
        if len(origins) >= 2:
            cross += 1
        sources = sorted(o for o in origins if o != ORIGINAL)
        for pair in combinations(sources, 2):
            pairings[pair] += 1
        register = register_of(entry)
        registers[register] += 1
        chapter = entry.get("chapter")
        if isinstance(chapter, int):
            if chapter <= mid:
                front += 1
                front_physical += register == PHYSICAL
            else:
                back += 1
                back_physical += register == PHYSICAL
    physical = registers[PHYSICAL]
    return {
        "total": total,
        "appearances": appearances,
        "sizes": sizes,
        "pairings": pairings,
        "cross": cross,
        "cross_share": (cross / total) if total else 0.0,
        "registers": registers,
        "physical": physical,
        "physical_share": (physical / total) if total else 0.0,
        "halfway": mid,
        "front": front,
        "front_physical": front_physical,
        "front_physical_share": (front_physical / front) if front else 0.0,
        "back": back,
        "back_physical": back_physical,
        "back_physical_share": (back_physical / back) if back else 0.0,
        "universes": list(universes),
    }


def shortfall_brief(entries, cast_origins, universes, min_appearances,
                    cross_share, pairing_share, physical_share=0.0,
                    front_physical_share=0.0, back_physical_share=0.0):
    """Where the ledger currently falls short, as instructions rather than complaints.

    Handed to the next chunk so it can steer, which is what makes the final gate a
    check rather than a coin toss on a 180-entry artifact."""
    seen = stats(entries, cast_origins, universes)
    lines = []
    # First, because it is the one a proposer will otherwise never optimise for. Every
    # other line here is about who is in a room; this is the only one about what
    # happens in it, and a ledger that reads its brief top-down should meet it first.
    if physical_share:
        lines.append(
            f"PHYSICAL SHARE SO FAR: {seen['physical_share']:.0%} "
            f"({seen['physical']}/{seen['total']}) against a floor of "
            f"{physical_share:.0%} — front half {seen['front_physical_share']:.0%} "
            f"(floor {front_physical_share:.0%}), back half "
            f"{seen['back_physical_share']:.0%} (floor {back_physical_share:.0%}). "
            f"`physical` means bodies at risk or at work — a fight, a chase, a rescue, "
            f"an escape, a hard physical task against a clock. An argument is "
            f"`conflict`, however loud.")
        if seen["registers"][UNSET]:
            lines.append(
                f"  {seen['registers'][UNSET]} interaction(s) have no valid "
                f"`register`. Every one needs one of: {', '.join(REGISTERS)}.")
        spread = ", ".join(f"{name} x{seen['registers'][name]}"
                           for name in REGISTERS if seen["registers"][name])
        if spread:
            lines.append(f"  REGISTER SPREAD: {spread}.")
    thin = sorted((name for name in cast_origins
                   if seen["appearances"][name] < min_appearances),
                  key=lambda n: seen["appearances"][n])
    if thin:
        lines.append(
            "UNDER-USED SO FAR — every one of these needs to be in more scenes before "
            "the book ends (current count in brackets); favour them when a chapter "
            "could plausibly include them:")
        lines.append("  " + ", ".join(
            f"{name} [{seen['appearances'][name]}]" for name in thin[:40]))
    if seen["total"]:
        lines.append(
            f"CROSS-UNIVERSE SHARE SO FAR: {seen['cross_share']:.0%} "
            f"({seen['cross']}/{seen['total']}). The floor is {cross_share:.0%}.")
    wanted = max(1, round(pairing_share * max(seen["total"], 1)))
    sources = sorted({o for o in cast_origins.values() if o and o != ORIGINAL})
    thin_pairs = [pair for pair in combinations(sources, 2)
                  if seen["pairings"][pair] < wanted]
    if thin_pairs:
        lines.append(
            "WORLD PAIRINGS STILL THIN (each needs a real share of the book, not one "
            "token scene):")
        lines.append("  " + "; ".join(
            f"{a} x {b} [{seen['pairings'][(a, b)]}]" for a, b in thin_pairs))
    if seen["sizes"]:
        shape = ", ".join(f"{size} people x{count}"
                          for size, count in sorted(seen["sizes"].items()))
        lines.append(f"SUBSET SIZES SO FAR: {shape}. Keep varying these — some "
                     "two-handers, some threes, some real ensembles.")
    # The groups already used, because this is the one rule a later chunk cannot
    # repair. Under-use and a thin pairing are both closable by writing more scenes; a
    # group already used in chapter 4 is a duplicate no amount of re-planning chapter
    # 40 will remove. The proposer needs to see it while it can still avoid it.
    if entries:
        recent = [" + ".join(sorted(e.get("who") or [])) for e in entries[-40:]]
        lines.append(f"GROUPS ALREADY USED (each may recur at most "
                     f"{config.META_SUBSET_MAX_REPEATS}x — vary by at least "
                     "one person; the most recent are listed):")
        lines.append("  " + "; ".join(recent))
    return "\n".join(lines)


def check(entries, cast_origins, universes, min_appearances=6, cross_share=0.60,
          subset_cap=None, distinct_share=None,
          pairing_share=0.04, physical_share=0.30, front_physical_share=0.20,
          back_physical_share=0.45, register_ceiling=0.50):
    """Validate the whole interaction ledger. Returns a LedgerReport.

    `entries` are {"id", "who", "chapter", "register"}; `cast_origins` maps every
    locked character to their world, or to "original" for a character invented for
    this book."""
    errors = []
    # Defaults come from config rather than the signature, so a caller that does not
    # care gets the deployed numbers and a test can still pin one explicitly.
    if subset_cap is None:
        subset_cap = config.META_SUBSET_MAX_REPEATS
    if distinct_share is None:
        distinct_share = config.META_DISTINCT_GROUP_SHARE
    seen = stats(entries, cast_origins, universes)
    total = seen["total"]
    if not total:
        return LedgerReport(False, ["the interaction ledger is empty"], seen)

    # 0. What the scenes DO.
    #
    # Deliberately first, because it is the rule the rest of this module made
    # necessary: five checks that count people are five checks a book of pure
    # conversation passes. The floors are separate for the two halves rather than one
    # whole-book number, and that is the whole design — a single 30% floor is satisfied
    # by a book that talks for forty chapters and then fights for eight, which is
    # precisely the book this gate exists to stop being written again. The front-half
    # floor buys action early; the back-half floor buys escalation.
    unset = seen["registers"][UNSET]
    if unset:
        errors.append(
            f"{unset}/{total} interaction(s) have no valid `register`. Every one needs "
            f"exactly one of: {', '.join(REGISTERS)}. Without it nothing in this book "
            f"counts what a scene does, which is how the last one came out as two "
            f"hundred conversations.")
    if seen["physical_share"] < physical_share:
        errors.append(
            f"only {seen['physical']}/{total} interactions ({seen['physical_share']:.0%}) "
            f"are `physical`; the floor is {physical_share:.0%}. Bodies at risk or at "
            f"work — fights, chases, rescues, escapes, hard physical work against a "
            f"clock. Convert scenes that are already about a problem into scenes where "
            f"the problem is happening to somebody.")
    if seen["front"] and seen["front_physical_share"] < front_physical_share:
        errors.append(
            f"the front half (chapters 1-{seen['halfway']}) is only "
            f"{seen['front_physical_share']:.0%} physical "
            f"({seen['front_physical']}/{seen['front']}); the floor is "
            f"{front_physical_share:.0%}. A book that saves its action for the back "
            f"half has asked the reader to wait for it.")
    if seen["back"] and seen["back_physical_share"] < back_physical_share:
        errors.append(
            f"the back half (chapters {seen['halfway'] + 1}+) is only "
            f"{seen['back_physical_share']:.0%} physical "
            f"({seen['back_physical']}/{seen['back']}); the floor is "
            f"{back_physical_share:.0%}. The second half must escalate, not level off.")
    dominant_register, register_count = seen["registers"].most_common(1)[0]
    if dominant_register != UNSET and register_count > register_ceiling * total:
        errors.append(
            f"{register_count}/{total} interactions are `{dominant_register}` "
            f"({register_count/total:.0%}); no single register may exceed "
            f"{register_ceiling:.0%}. A ledger of one register is one note played two "
            f"hundred times.")

    # 1. Nobody is a guest star.
    thin = sorted((name for name in cast_origins
                   if seen["appearances"][name] < min_appearances),
                  key=lambda n: (seen["appearances"][n], n))
    if thin:
        errors.append(
            f"{len(thin)} character(s) appear in fewer than {min_appearances} "
            f"interactions: " + ", ".join(
                f"{name} ({seen['appearances'][name]})" for name in thin[:12])
            + (f" and {len(thin) - 12} more" if len(thin) > 12 else "")
            + ". Every locked character is a principal; one with almost no scenes is a "
              "name on a list.")

    # 2. Groupings vary. A core party may recur; it may not BE the book.
    #
    # This was an absolute uniqueness rule, and it is the only gate here that has made
    # a book unplannable rather than merely rejecting a bad proposal — see
    # `config.META_SUBSET_MAX_REPEATS` for the measurement that changed it. Two clauses
    # now carry the same intent between them, and both are needed: the cap stops one
    # grouping dominating, and the distinct floor stops a book that is a small rotation
    # of groupings each used up to the cap.
    subsets = Counter(frozenset(e.get("who") or []) for e in entries if e.get("who"))
    cap = max(1, subset_cap)
    over = sorted(((n, s) for s, n in subsets.items() if n > cap), reverse=True)
    if over:
        shown = "; ".join(f"{' + '.join(sorted(s))} ({n}x)" for n, s in over[:6])
        errors.append(
            f"{len(over)} grouping(s) exceed the {cap}-scene budget: {shown}. A core "
            f"party is allowed to recur, but a grouping past its budget is the ledger "
            f"leaning on one combination — vary it by at least one person.")
    distinct = len(subsets)
    want_distinct = round(distinct_share * total)
    if total and distinct < want_distinct:
        errors.append(
            f"only {distinct}/{total} interactions ({distinct/total:.0%}) are a fresh "
            f"combination of people; the floor is {distinct_share:.0%}. Most scenes "
            f"should put people together who have not been together before.")

    # 3. Sizes vary.
    sizes = seen["sizes"]
    if len(sizes) < 3:
        errors.append(
            f"the interactions use only {len(sizes)} distinct group size(s). A ledger "
            f"of all two-handers is as broken as one of all ensemble scenes — mix "
            f"pairs, threes, fours, and a few larger.")
    dominant, count = sizes.most_common(1)[0]
    if count > 0.6 * total:
        errors.append(
            f"{count}/{total} interactions are {dominant}-person groups ({count/total:.0%}). "
            f"No single group size may be more than 60% of the book.")
    pairs = sizes.get(2, 0)
    big = sum(n for size, n in sizes.items() if size >= 4)
    if pairs < 0.10 * total:
        errors.append(
            f"only {pairs}/{total} interactions are two-handers. A book with no "
            f"two-person scenes has no conversations in it.")
    if big < 0.10 * total:
        errors.append(
            f"only {big}/{total} interactions have four or more people. Several should "
            f"be groups doing something hard together — the joy of a crossover is "
            f"watching incompatible skill sets combine.")

    # 4 and 5 are about crossovers, and only apply to one.
    #
    # A standalone novel has one source world, so every scene in it is within-cast by
    # construction — demanding that 60% of them cross universes would make a
    # single-universe book unplannable, which is a gate rejecting the correct answer.
    # The whole project treats a standalone as a one-book series and this is the same
    # principle one level down.
    sources = sorted({o for o in cast_origins.values() if o and o != ORIGINAL})
    if len(sources) < 2:
        return LedgerReport(not errors, errors, seen)

    # 4. Most of it crosses universes.
    if seen["cross_share"] < cross_share:
        errors.append(
            f"only {seen['cross']}/{total} interactions ({seen['cross_share']:.0%}) "
            f"cross universes; the floor is {cross_share:.0%}. A crossover where most "
            f"scenes are one cast talking to itself is not a crossover.")

    # 5. Every pairing of worlds gets a real share.
    wanted = max(1, round(pairing_share * total))
    for pair in combinations(sources, 2):
        got = seen["pairings"][pair]
        if got < wanted:
            errors.append(
                f"{pair[0]} x {pair[1]} share only {got} interaction(s); each pairing "
                f"of worlds needs at least {wanted}. One token scene is not a share.")

    return LedgerReport(not errors, errors, seen)
