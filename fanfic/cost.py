"""What a book consumes, computed rather than guessed. Pure arithmetic, no I/O.

Run it:

    python3 -m fanfic.cost              # the current configuration
    python3 -m fanfic.cost --presets    # the levers that are left, side by side
    python3 -m fanfic.cost --measured   # what the measurements are, and their age

## What this module is now, and what it stopped being

It used to be a shopping tool. It priced eleven models across five vendors, projected
a book against each, and reported which combinations brought one in under $5 — and
that work paid for itself once, by correcting a confident wrong conclusion (that a
cheap book required local inference; it did not).

That question is settled and closed. Text is Claude at `config.MODEL` and nothing
else, for the reasons in `providers/__init__.py`. Pictures are drawn through a
signed-in browser and cost nothing at all. **There is no bill left to shop for.**

So this projects the one thing still worth knowing: how much ALLOWANCE a book eats.
The mini shares one seat with the person who owns it, and a run that consumes a
week of it is a real cost to a real person even though no invoice appears. The
numbers below are list-price valuations of token usage — a meter, not a bill.

## The finding that still dominates everything

A chapter draft is ~7,200 output tokens. The **agentic** path spent ~227,000 *input*
tokens producing it, and the agentic editorial pass ~363,000. Both are back-solved
from real metered calls, not modelled.

The reason is structural, not wasteful: an agentic CLI works in turns, and every turn
re-sends the whole conversation. Eighty turns with a 25,000-token bible in context
re-sends that bible eighty times. A **one-shot** role inlines its digest once — call
it 22,000 tokens — and writes the chapter in a single call.

That is a ~10x reduction on drafting and ~15x on editing **at the same model**, which
is larger than any lever that was ever available from switching vendors. It is a
property of the ROLE, not of the provider: see `oneshot` in `config.TEXT_ROLES`.

## Prices, and one correction worth keeping

`config.PRICES` holds $/million-tokens per model. A model with no price prints "price
not set" rather than a guess — a cost model that invents prices is worse than one that
admits what it does not know.

That honesty was, for a day, doing the wrong job: the table originally held only
Anthropic prices and everything else `None`, and on that basis the module concluded
that a cheap book "needs local inference". The arithmetic was right and the conclusion
was wrong, because the comparison had never been made. Refusing to invent a number is
right; declining to go and look one up is not the same thing. The lesson outlived the
table it was learned from, which is why it is still written down here.
"""

import sys

from . import config

# How many chapters a projection assumes when the caller does not say.
#
# NOT a target and not a setting the pipeline reads — the outliner picks the count the
# story needs, and the only number config carries is `MIN_CHAPTERS`, a floor. This is
# purely an estimator's stand-in, sized to the shape a full-length crossover of this
# kind actually comes out at.
PROJECTION_CHAPTERS = 45

# Token volumes per call, by role and by transport.
#
# `agentic` figures are back-solved from metered production calls; `one_shot` are
# computed from the artifacts on disk (a chapter is 7,210 tokens; the digest is a
# slice of canon + bible + beats, not the whole memory). Both are estimates with very
# different provenance, and the difference between them is the whole point.
VOLUMES = {
    #                   agentic (in, out)   one-shot (in, out)
    "research":      ((400_000, 20_000),   (30_000, 20_000)),
    "anchoring":     (( 80_000,  4_000),   (20_000,  4_000)),
    "planning":      ((120_000,  8_000),   (25_000,  8_000)),
    "outlining":     ((150_000, 14_000),   (30_000, 14_000)),
    "drafting":      ((227_000,  7_200),   (22_000,  7_200)),
    "continuation":  (( 60_000,  3_000),   (12_000,  3_000)),
    "editing":       ((363_000,  6_000),   (24_000,  6_000)),
    "bible_merge":   (( 90_000,  2_000),   (18_000,  2_000)),
    "art_direction": (( 30_000,  1_000),   (10_000,  1_000)),
    "vision":        (( 20_000,    500),   ( 8_000,    500)),
}

# What one call of each role ACTUALLY cost, in USD at list price, measured from
# `state/usage.jsonl` on the 2026-08-08 run (the-hinge-worlds).
#
# These override the token arithmetic wherever the measured model matches the
# configured one, because the arithmetic is wrong by about 5x and wrong for a reason it
# cannot see. `VOLUMES` counts the tokens of the *artifact and its digest* — the things
# this repo writes. It cannot count the CLI's own system prompt and tool definitions,
# which are large and re-sent every turn, nor the model's reasoning tokens, which bill
# as output. A "one-shot" role still spends two or three turns thinking before its
# single Write, and pays the fixed overhead on each.
#
# So the projection said $0.12 for a draft that cost $0.82, and a whole book came out
# at $65 against a real ~$310.
#
# THESE ARE STALE IN ONE SPECIFIC WAY, and it is stated rather than papered over: the
# roles marked `claude-sonnet-5` were measured under the two-tier split that no longer
# exists. Every role is Opus now, and Opus is 2.5x Sonnet's rate, so a book costs more
# allowance than this table implies until someone re-measures. `render` flags every
# line that fell back to arithmetic for exactly this reason — a projection that
# silently mixed a measured Sonnet draft into an Opus run would be wrong in the
# direction that flatters it.
#
# Re-measure with `python3 -m fanfic.cost --measured` after any prompt or role change.
MEASURED_USD = {
    ("drafting", "claude-sonnet-5"):     0.82,
    ("continuation", "claude-sonnet-5"): 0.34,
    ("editing", "claude-opus-5"):        1.50,
    ("research", "claude-sonnet-5"):     0.92,
    ("planning", "claude-opus-5"):       1.30,
    ("outlining", "claude-opus-5"):      2.18,
}

# How often a short first draft needs a continuation pass. Measured: 2 of the first 3
# real drafts came in under the 85% mark, so this is not an edge case, it is the norm.
CONTINUATION_RATE = 0.7

# How often a chapter ships holding known defects, and is therefore re-read by the
# book's REVISION sweep for up to `REVISION_SWEEPS` rounds. Measured on the crossover's
# first 22 chapters under the old loop: 11 of 22. Expected to fall as the editorial
# loop converges, which is exactly the kind of assumption to re-measure rather than
# believe.
SWEEP_RATE = 0.5

# How often a chapter's editorial loop ends on a pass that *repaired* something rather
# than one that found nothing — leaving those last repairs unread, and buying the
# chapter exactly one verification round in the sweep.
#
# This is the coarsest number in the file. Live evidence is three chapters, which is
# not a rate, it is an anecdote. 0.6 is a deliberately pessimistic placeholder so the
# projection does not flatter itself; re-measure from the `unverified_repairs` field
# once a book's worth exists.
UNVERIFIED_RATE = 0.6


def call_counts(chapters, passes, images_per_chapter=1, character_sheets=6):
    """{role: how many calls one book makes}, and how many pictures it draws.

    `passes` is the average number of EDITORIAL passes a chapter needs — not attempts,
    because a chapter is drafted once. That distinction is the whole shape of the
    modern bill. The old loop paid for a draft, a continuation and a critique on every
    one of ~7 rounds; this one pays for a draft and a continuation once, and for 2-3
    editorial passes. Modelling it the old way overstates a book by about 4x and,
    worse, points the optimisation at the wrong thing."""
    scenes = chapters * images_per_chapter
    pictures = scenes + character_sheets + 1
    return {
        "research": 1,
        "anchoring": 1,
        "planning": 1,
        "outlining": 1,
        # ONCE. Every later change to a chapter is an anchored repair, not a redraft.
        "drafting": chapters,
        # A continuation is a second model call on the same draft, not a retry: one
        # completion produces ~2,700-4,600 words against a 5,351 target, so most
        # first drafts need one.
        "continuation": round(chapters * CONTINUATION_RATE),
        # Plus the sweep: up to REVISION_SWEEPS rounds for a chapter with known
        # defects, and exactly one verification round for a chapter whose last pass
        # repaired something and was then the last pass.
        "editing": round(chapters * passes
                         + chapters * SWEEP_RATE * config.REVISION_SWEEPS
                         + chapters * UNVERIFIED_RATE),
        "bible_merge": chapters,
        "art_direction": chapters,
        # One vision critique per rendered image, plus the sheets and the cover. This
        # is the only role the pictures still cost anything for: drawing them is free,
        # judging them is a Claude call.
        "vision": pictures,
    }, pictures


def price(model):
    """(input, output) $/MTok for a model, or None when it is not known.

    Deliberately returns None rather than a plausible guess: a cost model that
    fabricates a price is worse than one that admits it cannot answer."""
    return config.PRICES.get(model)


def estimate(chapters=None, passes=3, one_shot=None, model=None,
             images_per_chapter=None, character_sheets=6):
    """Project one book's allowance consumption. Returns a dict.

    `one_shot` defaults to None, meaning "whatever each role is configured to do" —
    the `oneshot` flag in `config.TEXT_ROLES`. Pass True or False to force one
    transport for every role, which is how the presets show what that lever is worth.

    There is no `image_price` argument any more, and no image line in the total.
    Pictures are drawn through a signed-in browser session: they cost wall-clock and
    a vision critique each, and nothing else."""
    chapters = chapters or PROJECTION_CHAPTERS
    model = model or config.MODEL
    if images_per_chapter is None:
        images_per_chapter = (config.IMAGES_PER_CHAPTER
                              if config.IMAGES_ENABLED else 0)

    counts, pictures = call_counts(chapters, passes, images_per_chapter,
                                   character_sheets)
    if not images_per_chapter:
        pictures = 0
        counts["vision"] = 0

    lines, unpriced, total = [], set(), 0.0
    for role, count in counts.items():
        if not count:
            continue
        oneshot = (config.TEXT_ROLES.get(role, {}).get("oneshot", False)
                   if one_shot is None else one_shot)
        in_tok, out_tok = VOLUMES[role][1 if oneshot else 0]
        # A measurement beats the arithmetic whenever one exists for this exact
        # (role, model) pair — see MEASURED_USD for why the arithmetic runs ~5x light.
        # When it does not, the line is flagged rather than quietly modelled, because
        # the measurements that exist were taken at a model this fleet no longer runs.
        measured = MEASURED_USD.get((role, model))
        rate = price(model)
        if measured is not None:
            cost = count * measured
            total += cost
        elif rate is None:
            unpriced.add(model)
            cost = None
        else:
            cost = count * (in_tok * rate[0] + out_tok * rate[1]) / 1e6
            total += cost
        lines.append({"role": role, "calls": count, "model": model,
                      "in_tok": in_tok * count, "out_tok": out_tok * count,
                      "cost": cost, "measured": measured is not None})

    return {"chapters": chapters, "passes": passes, "one_shot": one_shot,
            "model": model, "lines": lines, "pictures": pictures,
            "total": total, "unpriced": sorted(unpriced)}


# The levers that are left, and the point of listing them together is that the
# ordering is not intuitive. Every one of these is a real configuration you can set
# with an env var — no vendor comparisons, because there is no vendor decision.
PRESETS = {
    "as configured":                  dict(),
    "forced agentic (the old way)":   dict(one_shot=False),
    "forced one-shot everywhere":     dict(one_shot=True),
    "2 editorial passes":             dict(passes=2),
    "4 editorial passes":             dict(passes=4),
    "text-only (no pictures)":        dict(images_per_chapter=0),
    "30 chapters":                    dict(chapters=30),
    "60 chapters":                    dict(chapters=60),
}


def levers(chapters=None, passes=3, character_sheets=6):
    """What each lever is worth, as a delta against the configured baseline.

    This replaces the old `price_point_for`, which answered "what model do I need to
    buy to hit $5". That question no longer exists — the model is decided and the
    pictures are free — so the useful question became "which of the knobs I still
    have actually moves the number", and it is answered by running them."""
    base = estimate(chapters=chapters, passes=passes,
                    character_sheets=character_sheets)["total"]
    out = []
    for name, kwargs in PRESETS.items():
        kwargs = dict(kwargs)
        kwargs.setdefault("chapters", chapters)
        kwargs.setdefault("passes", passes)
        kwargs.setdefault("character_sheets", character_sheets)
        total = estimate(**kwargs)["total"]
        out.append((name, total, total - base))
    return out


def _fmt(cost):
    return "  (price not set)" if cost is None else f"${cost:,.2f}"


def render(result):
    """A human-readable breakdown of one estimate."""
    out = []
    flag = result["one_shot"]
    mode = ("as configured (per-role transport)" if flag is None
            else "one-shot, forced" if flag else "agentic everywhere, forced")
    out.append(f"{result['chapters']} chapters x {result['passes']} editorial "
               f"pass(es), {mode}")
    out.append(f"every call on {result['model']}")
    out.append("")
    out.append(f"{'role':<15}{'calls':>7}{'in tok':>14}{'out tok':>11}{'usage':>12}"
               f"{'':>3}")
    out.append("-" * 62)
    modelled = False
    for line in result["lines"]:
        mark = "" if line["measured"] else " ~"
        modelled = modelled or not line["measured"]
        out.append(f"{line['role']:<15}{line['calls']:>7,}"
                   f"{line['in_tok']:>14,}{line['out_tok']:>11,}"
                   f"{_fmt(line['cost']):>12}{mark:>3}")
    out.append("-" * 62)
    out.append(f"{'TOTAL':<15}{'':>7}{'':>14}{'':>11}{_fmt(result['total']):>12}")
    if result["pictures"]:
        out.append("")
        out.append(f"{result['pictures']:,} pictures, drawn through the browser "
                   f"session at no charge. Their cost to")
        out.append("this table is the vision critique each one gets, which is the "
                   "`vision` row.")
    out.append("")
    out.append("This is a METER, NOT A BILL: list-price valuation of tokens spent on "
               "a seat.")
    if modelled:
        out.append("Rows marked ~ are modelled from token volumes, not measured. The "
                   "arithmetic runs")
        out.append("about 5x light — it cannot see the CLI's own system prompt or the "
                   "model's reasoning")
        out.append("tokens — so treat those rows as a floor. Re-measure with "
                   "--measured.")
    if result["unpriced"]:
        out.append("")
        out.append("Unpriced, so excluded from the total — set these in config.PRICES:")
        for model in result["unpriced"]:
            out.append(f"  - {model}")
    return "\n".join(out)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--measured" in argv:
        print("Measured per-call usage, in USD at list price "
              "(state/usage.jsonl, run of 2026-08-08):\n")
        for (role, model), usd in sorted(MEASURED_USD.items()):
            stale = "" if model == config.MODEL else f"   STALE — not {config.MODEL}"
            print(f"  {role:<14}{model:<18}${usd:>5.2f}{stale}")
        print(f"\nThe fleet now runs every role on {config.MODEL}. Any line above "
              f"marked STALE was")
        print("measured under the two-tier split that no longer exists, and its role "
              "is projected")
        print("from token arithmetic instead — which runs light. Re-measure after a "
              "full book.")
        return 0

    if "--presets" in argv:
        print(f"One {PROJECTION_CHAPTERS}-chapter book on {config.MODEL}, "
              f"by lever\n")
        for name, total, delta in levers():
            sign = "" if abs(delta) < 0.005 else f"   {delta:+,.2f}"
            print(f"  {name:<32}{_fmt(total):>12}{sign}")
        print("\nRun without --presets for the per-role breakdown of the current "
              "configuration.")
        return 0

    print(render(estimate()))
    return 0


if __name__ == "__main__":                                       # pragma: no cover
    raise SystemExit(main())
