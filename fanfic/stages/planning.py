"""Stage 2 — Series planning. Canon + the prompt -> a validated series plan and a
seeded series bible.

The judgment model proposes the book breakdown (each book's premise, role, and exit
world-state), the arc spanning them, the style guide, and the main cast with each
character's reference-sheet specification. Deterministic code then checks structural
completeness — every book has a role, the arc has a beginning and an end, there is a
cast to lock — and seeds the series bible from the cast and relationship graph.

A standalone novel is just a one-book series, so this one path covers both.
"""

from .. import config, jobspec, paths
from . import anchoring, correction_brief
from ..infra import storage
from ..memory import bible as bible_rules
from ..memory.bible import (new_canon, new_character, new_series_bible,
                            validate_series_bible)
from ..models import prompts, text


def canon_block(series_rec):
    """Every frozen canon fact, quoted. One planning call reads all of it, so there
    is no slice to take — and quoting it costs one turn where fetching it costs a
    turn per file plus a re-send of each on every turn after."""
    lines = []
    for universe in series_rec.get("universes", []):
        doc = storage.load_json(paths.canon_path(universe), new_canon(universe))
        lines.append(f"--- CANON: {universe} "
                     f"({len(doc.get('facts', []))} cited facts) ---")
        lines += [f"  ({f.get('citation','')}) [{f.get('category','')}] "
                  f"{f.get('subject','')}: {f.get('text','')}"
                  for f in doc.get("facts", [])]
        lines.append("")
    return "\n".join(lines) or "(no canon on file)"


def propose_plan(series_rec, out_path, log_fn=None, feedback=""):
    """Model seam: produce the series plan JSON at out_path.

    `feedback` carries the validator's complaints from a previous rejected attempt."""
    universes = series_rec.get("universes", [])
    prompt_text = series_rec["prompt_text"]

    # A declared novelization is told so up front rather than discovering it by being
    # rejected. The base template asks for an invented biggest bad; letting the model
    # propose one and then refusing it costs a full planning call and — worse — the
    # correction brief pushes it toward satisfying the gate rather than toward the
    # book the reader asked for.
    kind = []
    if jobspec.forbids_original_characters(prompt_text):
        kind = [
            "THIS JOB IS A NOVELIZATION, AND ITS CAST IS THE SOURCE'S CAST.",
            "It has declared that no original characters are to be invented. That "
            "overrides the instruction above to invent this book's biggest villain: "
            "the primary antagonist MUST be a canon character from the source, and "
            "every antagonist's `origin` must name their source universe rather than "
            "`original`. Do not add a Sith Lord, a conspiracy, or a hidden hand that "
            "the source does not have — an invented threat placed above the canon one "
            "is not escalation here, it is a different book than the one asked for.",
            "Escalation comes from the source's own structure: what the antagonist "
            "does, what it costs, and what the reader learns about a villain they "
            "thought they already understood.",
            "",
        ]

    return text.produce(
        prompts.template("series_plan") + feedback,
        kind + [f"Universes: {', '.join(universes)}",
         "",
         # The anchor comes FIRST and outranks canon for anything it covers. Canon
         # says what a character looks like across their series; the anchor says what
         # they look like on page one, and those differ exactly where a finale changed
         # something — which is where a fan looks first.
         anchoring.block(series_rec["series_id"]),
         "",
         "Each character's `appearance` MUST match their anchor `wears` line above. "
         "Where canon and the anchor disagree, the anchor is the present and canon is "
         "the past.",
         "",
         "FROZEN CANON — immutable ground truth for every universe involved:",
         canon_block(series_rec),
         "",
         "=" * 70,
         "THE JOB PROMPT (what the reader asked for):",
         "=" * 70,
         prompt_text],
        out_path,
        role="planning",
        artifact="the series plan as strict JSON",
        log_fn=log_fn)


def _validate(plan, allow_canon_primary=False):
    """Structural completeness of a proposed plan. Returns a list of errors.

    `allow_canon_primary` is set for a job that has declared itself a novelization —
    see `jobspec.forbids_original_characters`. It relaxes exactly one rule: that the
    book's biggest villain must be invented."""
    errors = []
    count = plan.get("book_count")
    books = plan.get("books", [])
    if not isinstance(count, int) or count < 1:
        errors.append("plan: book_count must be a positive integer")
    if len(books) != count:
        errors.append(f"plan: {len(books)} book entries but book_count={count}")
    for i, book in enumerate(books, 1):
        for field in ("num", "title", "premise", "role", "exit_state"):
            if not book.get(field):
                errors.append(f"plan: book {i} missing {field}")
    nums = sorted(b.get("num") for b in books if isinstance(b.get("num"), int))
    if nums and nums != list(range(1, len(books) + 1)):
        errors.append(f"plan: book numbers must be 1..{len(books)}; got {nums}")
    arc = plan.get("arc", {})
    if not arc.get("beginning") or not arc.get("end"):
        errors.append("plan: arc needs both a beginning and an end")
    if not plan.get("characters"):
        errors.append("plan: no characters to lock reference sheets for")
    # Appearance and voice are both required, and for the same reason. A field that is
    # optional at every point it passes through is not optional, it is absent — the
    # chapter titles came out empty for five accepted chapters because the prompt did
    # not ask, the gate did not require, and the binder did not read. Voice is the
    # field most likely to be quietly dropped here and the one a crossover cannot
    # survive without, so it is required at the gate rather than hoped for.
    for spec in plan.get("characters", []):
        name = spec.get("name") or "<unnamed>"
        if not spec.get("name"):
            errors.append("plan: a character entry has no name")
        if not spec.get("appearance"):
            errors.append(f"plan: character {name} has no appearance")
        # Age is required as a NUMBER, and comparative phrasing is refused.
        #
        # An image model is not told "older than she was", it is shown a face and asked
        # to draw one. Luz's locked appearance said "grown into adult height and build
        # rather than the fourteen-year-old who fell in, broad shoulders", which is
        # three separate pushes away from a number nobody supplied — and a comparison
        # makes the thing compared to the reference point, so "not fourteen" told the
        # model where to start and nothing told it where to stop. Every picture of her
        # in the first book is a woman approaching thirty. She is eighteen.
        if anchoring.parse_age(spec.get("age")) is None:
            errors.append(
                f"plan: character {name} has no usable `age` — got "
                f"{spec.get('age')!r}. A plain number of years at the moment this book "
                f"starts, like 18. The anchor state above already carries one for every "
                f"principal; copy it.")
        if not spec.get("voice"):
            errors.append(f"plan: character {name} has no voice description; every "
                          "character needs one or they will all sound alike")
        # `origin` is what makes the interaction coverage gate arithmetic instead of
        # judgement: without it there is no way to count whether a scene crosses
        # universes, and "at least 60% of this crossover is actually a crossover" is
        # the check nothing has ever performed.
        if not spec.get("origin"):
            errors.append(f"plan: character {name} has no `origin` — name the source "
                          f"universe they come from, or `original` if they were "
                          f"invented for this book")
    if not plan.get("style_guide"):
        errors.append("plan: no style_guide; the writer has no voice to work in")

    errors += _validate_antagonists(plan, allow_canon_primary=allow_canon_primary)
    errors += _validate_originals(plan)
    errors += _validate_progressions(plan)

    # The interaction ledger is NOT gated here any more, because it is not written
    # here any more. It lives in the meta plan, which builds it chapter by chapter —
    # the floor used to be sized against the cast (`min(cast-1, max(8, cast//2))`,
    # so 13 for a cast of 26) when the thing it has to cover is the book, and 23
    # entries across 37 chapters left fourteen chapters owing nothing to anybody.
    # See `stages/metaplan.py` and `gates/interactions.py`.
    return errors


def _validate_antagonists(plan, allow_canon_primary=False):
    """The book must know what it is up against.

    There was no antagonist concept anywhere in this pipeline — not in the plan
    schema, not in a gate, not in a prompt; the word did not appear. Bill Cipher was
    in the last plan only because he is on the Gravity Falls cast list, which is not
    the same thing as the book having decided what it is up against.

    For an original story the primary threat must also be **invented**. An existing
    villain may appear and may be excellent, but a crossover whose ceiling is a villain
    the reader already knows the limits of has no room to escalate past their canon.

    `allow_canon_primary` lifts that one requirement for a declared NOVELIZATION, where
    it is actively wrong: the canon villain is what the reader came for, and an
    invented antagonist placed above them is not escalation but a different book. The
    structural requirements — one primary, everyone named, everyone in the cast,
    everyone with a stated threat — hold either way, because they are about the plan
    being complete rather than about where the villain came from."""
    errors = []
    cast = {c.get("name"): c for c in plan.get("characters") or []}
    entries = plan.get("antagonists") or []
    if not entries:
        return ["plan: no `antagonists`. Name what this book is up against, and mark "
                "exactly one of them `primary`."]

    primary = [a for a in entries if a.get("primary")]
    if len(primary) != 1:
        errors.append(f"plan: {len(primary)} antagonists marked `primary`; there must "
                      f"be exactly one — the book's biggest bad.")
    for i, entry in enumerate(entries, 1):
        name = entry.get("name")
        if not name:
            errors.append(f"plan: antagonist {i} has no name")
            continue
        if name not in cast:
            errors.append(f"plan: antagonist {name!r} is not in `characters`; every "
                          f"antagonist needs a locked design and a voice like anyone "
                          f"else")
        if not entry.get("threat"):
            errors.append(f"plan: antagonist {name} has no `threat` — say what they "
                          f"want and what they can actually do about it")

    origins = {name: (spec.get("origin") or "") for name, spec in cast.items()}
    if allow_canon_primary:
        # A declared novelization. The cast is the source's cast, so requiring an
        # invented villain here would demand the one thing the job ruled out.
        return errors

    originals = [a for a in entries if origins.get(a.get("name")) == "original"]
    if not originals:
        errors.append(
            "plan: no antagonist is original. At least one villain must be invented "
            "for this book — a crossover assembled entirely out of other people's "
            "villains has nothing at stake that the source shows have not already "
            "settled.")
    if primary and origins.get(primary[0].get("name")) != "original":
        errors.append(
            f"plan: the primary antagonist {primary[0].get('name')!r} comes from "
            f"{origins.get(primary[0].get('name'))!r}. The biggest bad must be "
            f"original. An existing villain may appear and may be as dangerous as the "
            f"source material makes them — they may not be the ceiling.")
    return errors


def _validate_originals(plan):
    """A character with no source art needs a fuller design than one who has some.

    Every canon character's sheet is anchored on real pictures from their own wiki,
    which settles the face, the proportions and the silhouette in a way prose cannot.
    An original has none of that, so the words are the only anchor there will ever be —
    and a thin description is how a new antagonist comes out looking different in every
    picture of them."""
    errors = []
    for spec in plan.get("characters") or []:
        if (spec.get("origin") or "") != "original":
            continue
        name = spec.get("name") or "<unnamed>"
        appearance = (spec.get("appearance") or "").strip()
        if len(appearance) < 200:
            errors.append(
                f"plan: original character {name} has only {len(appearance)} "
                f"characters of appearance. An original has no reference art to lean "
                f"on, so the description is the ONLY anchor: give the silhouette, the "
                f"proportions, the palette, and how they are constructed.")
        if not spec.get("palette"):
            errors.append(f"plan: original character {name} has no `palette`")
        if not (spec.get("distinguishing_feature") or "").strip():
            errors.append(
                f"plan: original character {name} has no `distinguishing_feature` — "
                f"one thing that survives being drawn small and from behind, so a "
                f"reader recognises them in a picture where the face is two pixels.")
    return errors


def _validate_progressions(plan):
    """Everyone ends the book stronger in some way than they started it.

    Nothing in this pipeline has ever tracked a character getting stronger, so it never
    happened except by accident. Two guards are built into the shape rather than left
    to taste: a progression carries where it *starts* as well as where it ends, so it
    is a change rather than an assertion; and it is explicitly allowed to be a skill, a
    nerve, or standing rather than a power, because not everybody needs a new sword
    form. Hop Pop needs to stop deferring."""
    errors = []
    names = {c.get("name") for c in plan.get("characters") or []}
    entries = plan.get("progressions") or []
    if not entries:
        return ["plan: no `progressions`. Every principal ends this book stronger in "
                "some way than they started it; say how, for each of them."]

    seen_ids, covered = set(), set()
    for i, entry in enumerate(entries, 1):
        pid = entry.get("id")
        who = entry.get("who")
        if not pid:
            errors.append(f"plan: progression {i} has no id")
        elif pid in seen_ids:
            errors.append(f"plan: duplicate progression id {pid!r}")
        else:
            seen_ids.add(pid)
        if who not in names:
            errors.append(f"plan: progression {i} is for {who!r}, who is not in the "
                          f"cast")
        else:
            covered.add(who)
        for field in ("starts", "ends"):
            if not (entry.get(field) or "").strip():
                errors.append(
                    f"plan: progression {pid or i} has no `{field}`. Both ends are "
                    f"required — without the starting point it is an assertion about "
                    f"a character rather than a change the book has to earn.")
        # A progression's costume becomes a DATED anchor: the outliner stamps it at
        # the one chapter that delivers the progression, and every later chapter is
        # drawn from it verbatim. So it has to be one outfit, not an itinerary.
        costume = entry.get("costume")
        if costume and bible_rules.describes_multiple_transitions(costume):
            errors.append(
                f"plan: progression {pid or i} ({who}) has a `costume` describing more "
                f"than one change of look. A costume is stamped at the single chapter "
                f"that delivers its progression and is then drawn verbatim in every "
                f"later chapter, so it must name ONE outfit that is in force from that "
                f"point — not a sequence. Split it into a separate progression per "
                f"change, each with its own costume.")
    missing = sorted(names - covered)
    if missing:
        errors.append(
            f"plan: {len(missing)} character(s) have no progression: "
            + ", ".join(missing[:12])
            + (f" and {len(missing) - 12} more" if len(missing) > 12 else "")
            + ". Not everyone gets a new power — most should get one concrete change "
              "that is a skill, a nerve, or standing they did not have.")
    return errors


def run(series_rec, log_fn=None):
    """Produce and validate the plan, then seed the series bible.

    Returns {"book_count", "books", "title"}. Raises RuntimeError on a structural
    failure — a deterministic park."""
    sid = series_rec["series_id"]
    novelization = jobspec.forbids_original_characters(series_rec["prompt_text"])
    if novelization and log_fn:
        log_fn("planning: this job declares no original characters, so the primary "
               "antagonist may be a canon villain")
    proposal_path = paths.plan_proposal_path(sid)
    attempts = max(1, config.GATE_MAX_ATTEMPTS)
    feedback, errors = "", []
    for attempt in range(1, attempts + 1):
        propose_plan(series_rec, proposal_path, log_fn=log_fn, feedback=feedback)
        plan, why = storage.load_proposal(proposal_path)
        if not isinstance(plan, dict):
            errors = [why or "the plan is not a JSON object"]
        else:
            errors = _validate(plan, allow_canon_primary=novelization)
        if not errors:
            break
        if log_fn:
            log_fn(f"planning: proposal rejected (attempt {attempt}/{attempts}): "
                   f"{errors[:4]}")
        feedback = correction_brief(errors, attempt, attempts)
    if errors:
        raise RuntimeError(
            f"planning: invalid plan after {attempts} attempts: {errors[:4]}")

    bible = new_series_bible(sid)
    for spec in plan["characters"]:
        bible["characters"][spec["name"]] = new_character(
            spec["name"], canon_ref=spec.get("canon_ref", ""),
            appearance=spec.get("appearance", ""), age=str(spec.get("age", "")),
            costumes=spec.get("costumes", []),
            palette=spec.get("palette", []),
            ref_sheet_spec=spec.get("ref_sheet_spec", ""),
            voice=spec.get("voice", ""),
            origin=spec.get("origin", ""))
    bible["relationships"] = plan.get("relationships", [])
    bible["antagonists"] = plan.get("antagonists", [])
    bible["progressions"] = plan.get("progressions", [])
    # The interaction ledger is seeded by the meta plan, not here — it is built chapter
    # by chapter and there are no chapters yet at this point.
    bible["interactions"] = []
    ok, bible_errors = validate_series_bible(bible)
    if not ok:
        raise RuntimeError(f"planning: seeded bible invalid: {bible_errors[:4]}")

    storage.save_json(plan, paths.plan_path(sid))
    storage.save_json(bible, paths.series_bible_path(sid))
    return {"book_count": plan["book_count"], "books": plan["books"],
            "title": plan.get("title", "")}
