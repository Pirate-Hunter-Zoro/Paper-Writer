"""What a paper consumes, computed rather than guessed. Pure arithmetic, no I/O.

Run it:

    python3 -m paperwriter.cost              # the current configuration
    python3 -m paperwriter.cost --presets    # the levers, side by side
    python3 -m paperwriter.cost --measured   # what the measurements are, and their age

## What this is for

Text is Claude at `config.MODEL` and nothing else, for the reasons in
`providers/__init__.py`, and it runs on a logged-in seat rather than an API key.
**There is no bill to shop for.** What there is, is an allowance: the seat is shared
with the person who owns it, and a run that consumes a week of it is a real cost to a
real person even though no invoice appears. The numbers here are list-price valuations
of token usage — a meter, not a bill.

## The finding that dominates everything

A section draft is a few thousand output tokens. The **agentic** path can spend two
hundred thousand *input* tokens producing it, and an agentic editorial pass more.

The reason is structural, not wasteful: an agentic CLI works in turns, and every turn
re-sends the whole conversation. Eighty turns with a 25,000-token ledger in context
re-sends that ledger eighty times. A **one-shot** role inlines its brief once and
writes the section in a single call.

That is roughly a tenfold reduction on drafting and more on review **at the same
model**, which is larger than any lever ever available from switching vendors. It is a
property of the ROLE, not of the provider: see `oneshot` in `config.TEXT_ROLES`.

## Prices, and one correction worth keeping

`config.PRICES` holds $/million-tokens per model. A model with no price prints "price
not set" rather than a guess — a cost model that invents prices is worse than one that
admits what it does not know.

That honesty was once doing the wrong job: an early version of this table held one
vendor's prices and left everything else `None`, and concluded on that basis that a
cheap run "needs local inference". The arithmetic was right and the conclusion was
wrong, because the comparison had never been made. Refusing to invent a number is
right; declining to go and look one up is not the same thing.
"""

import sys

from . import config

# How many sections a projection assumes when the caller does not say.
#
# NOT a target and not a setting the pipeline reads — the outliner produces the
# sections the argument needs. This is purely an estimator's stand-in, sized to what a
# full IMRaD manuscript with front matter and declarations comes out at.
PROJECTION_SECTIONS = 14

# Token volumes per call, by role and by transport.
#
# `agentic` figures are back-solved from metered production calls on a comparable
# pipeline; `one_shot` are computed from what the artifacts actually are (a section is
# a few thousand tokens; the brief is a slice of evidence and plan, not the whole
# memory). Both are estimates with very different provenance, and the difference
# between them is the whole point.
VOLUMES = {
    #                   agentic (in, out)   one-shot (in, out)
    "evidence":      ((400_000, 20_000),   (30_000, 20_000)),
    "grounding":     (( 80_000,  4_000),   (20_000,  4_000)),
    "planning":      ((120_000,  8_000),   (25_000,  8_000)),
    "argument":      ((140_000, 10_000),   (28_000, 10_000)),
    "outlining":     ((150_000, 14_000),   (30_000, 14_000)),
    "drafting":      ((120_000,  1_400),   (20_000,  1_400)),
    "continuation":  (( 60_000,    700),   (12_000,    700)),
    "review":        ((180_000,  4_000),   (22_000,  4_000)),
    "ledger_merge":  (( 90_000,  2_000),   (18_000,  2_000)),
}

# What one call of each role ACTUALLY cost, in USD at list price, measured from
# `state/usage.jsonl`.
#
# These override the token arithmetic wherever the measured model matches the
# configured one, because the arithmetic is wrong by about 5x and wrong for a reason it
# cannot see. `VOLUMES` counts the tokens of the *artifact and its digest* — the things
# this repo writes. It cannot count the CLI's own system prompt and tool definitions,
# which are large and re-sent every turn, nor the model's reasoning tokens, which bill
# as output. A "one-shot" role still spends two or three turns thinking before its
# single Write, and pays the fixed overhead on each.
#
# So a projection can say $0.12 for a draft that costs $0.82, and a whole run come out
# five times light.
#
# **THIS TABLE IS EMPTY, and that is honest rather than lazy.** Every figure that used
# to be here was measured on a different pipeline writing a different kind of document,
# and a stale measurement is worse than none: it is believed. `render` flags every line
# that fell back to arithmetic, so an unmeasured projection announces that it is one.
#
# Fill it from a real run: `python3 -m paperwriter.cost --measured` reads
# `state/usage.jsonl` and prints what each role actually cost. Re-measure after any
# prompt or role change.
MEASURED_USD = {}

# How often a short first draft needs a continuation pass. A section is small enough
# that one completion usually reaches its budget, which is the main reason a paper is
# cheaper than a novel per unit of prose. Placeholder until measured.
CONTINUATION_RATE = 0.25

# How often a section ships holding known defects, and is therefore re-read by the
# paper's REVISION sweep for up to `REVISION_SWEEPS` rounds. A placeholder, and exactly
# the kind of assumption to re-measure rather than believe.
SWEEP_RATE = 0.5

# How often a section's editorial loop ends on a pass that *repaired* something rather
# than one that found nothing — leaving those last repairs unread, and buying the
# section exactly one verification round in the sweep.
#
# This is the coarsest number in the file. 0.6 is a deliberately pessimistic
# placeholder so the projection does not flatter itself; re-measure from the
# `unverified_repairs` field once a manuscript's worth exists.
UNVERIFIED_RATE = 0.6


def call_counts(sections, passes):
    """{role: how many calls one paper makes}.

    `passes` is the average number of EDITORIAL passes a section needs — not attempts,
    because a section is drafted once. That distinction is the whole shape of the
    bill. A critique-then-redraft loop pays for a draft and a critique on every one of
    several rounds; this one pays for a draft once, and for two or three editorial
    passes that repair rather than rewrite. Modelling it the old way overstates a paper
    several times over and, worse, points the optimisation at the wrong thing."""
    return {
        "evidence": 1,
        "grounding": 1,
        "planning": 1,
        "argument": 1,
        "outlining": 1,
        # ONCE. Every later change to a section is an anchored repair, not a redraft.
        "drafting": sections,
        "continuation": round(sections * CONTINUATION_RATE),
        # Plus the sweep: up to REVISION_SWEEPS rounds for a section with known
        # defects, and exactly one verification round for a section whose last pass
        # repaired something and was then the last pass.
        "review": round(sections * passes
                        + sections * SWEEP_RATE * config.REVISION_SWEEPS
                        + sections * UNVERIFIED_RATE),
        "ledger_merge": sections,
    }


def price(model):
    """(input, output) $/MTok for a model, or None when it is not known.

    Deliberately returns None rather than a plausible guess: a cost model that
    fabricates a price is worse than one that admits it cannot answer."""
    return config.PRICES.get(model)


def estimate(sections=None, passes=3, one_shot=None, model=None):
    """Project one paper's allowance consumption. Returns a dict.

    `one_shot` defaults to None, meaning "whatever each role is configured to do" —
    the `oneshot` flag in `config.TEXT_ROLES`. Pass True or False to force one
    transport for every role, which is how the presets show what that lever is
    worth."""
    sections = sections or PROJECTION_SECTIONS
    model = model or config.MODEL
    counts = call_counts(sections, passes)

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
        # any measurement that exists may have been taken at a model this no longer runs.
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

    return {"sections": sections, "passes": passes, "one_shot": one_shot,
            "model": model, "lines": lines,
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
    "8 sections (a short report)":    dict(sections=8),
    "22 sections (with a supplement)": dict(sections=22),
}


def levers(sections=None, passes=3):
    """What each lever is worth, as a delta against the configured baseline.

    The useful question is not "which model should I buy" — the model is decided — but
    "which of the knobs I still have actually moves the number", and it is answered by
    running them rather than reasoned about."""
    base = estimate(sections=sections, passes=passes)["total"]
    out = []
    for name, kwargs in PRESETS.items():
        kwargs = dict(kwargs)
        kwargs.setdefault("sections", sections)
        kwargs.setdefault("passes", passes)
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
    out.append(f"{result['sections']} sections x {result['passes']} editorial "
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
    out.append("")
    out.append("This is a METER, NOT A BILL: list-price valuation of tokens spent on "
               "a seat.")
    if modelled:
        out.append("Rows marked ~ are modelled from token volumes, not measured. The "
                   "arithmetic runs")
        out.append("several times light — it cannot see the CLI's own system prompt or "
                   "the model's")
        out.append("reasoning tokens — so treat those rows as a floor. See --measured.")
    if result["unpriced"]:
        out.append("")
        out.append("Unpriced, so excluded from the total — set these in config.PRICES:")
        for model in result["unpriced"]:
            out.append(f"  - {model}")
    return "\n".join(out)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--measured" in argv:
        if not MEASURED_USD:
            print("No measurements on file, so every projection is token arithmetic —")
            print("which runs several times light, because it cannot see the CLI's own")
            print("system prompt or the model's reasoning tokens.\n")
            print("Fill the table from a real run: read state/usage.jsonl and put the")
            print("per-call figures into MEASURED_USD, keyed by (role, model).")
            return 0
        print("Measured per-call usage, in USD at list price (state/usage.jsonl):\n")
        for (role, model), usd in sorted(MEASURED_USD.items()):
            stale = "" if model == config.MODEL else f"   STALE — not {config.MODEL}"
            print(f"  {role:<14}{model:<18}${usd:>5.2f}{stale}")
        print(f"\nEvery role runs on {config.MODEL}. A line marked STALE was measured "
              f"on a different")
        print("model and its role is projected from token arithmetic instead, which "
              "runs light.")
        return 0

    if "--presets" in argv:
        print(f"One {PROJECTION_SECTIONS}-section paper on {config.MODEL}, "
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
