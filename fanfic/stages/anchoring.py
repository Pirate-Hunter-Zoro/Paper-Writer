"""Stage 1b — the anchor state. Where everyone actually is when the book opens.

Canon research collects what is true of a *series*. A story needs what is true at the
*moment it starts*. Those are different documents and only one of them was ever being
written, which is how a crossover set after four finales put Dipper Pines in his
pine-tree cap and Wendy Corduroy in her ushanka — the way they look for the whole show,
and the exact opposite of how they look afterwards, because they trade hats in the last
episode.

The receipt is worth keeping: thirty-one researched Gravity Falls facts, ten of them
mentioning Wendy or a hat, and the swap in none of them. Planning wrote the appearance
from the show's default. The continuity editor checked the prose against the canon file
and found nothing wrong, because the fact it needed had never been collected. Every
illustration in the book then drew it. A reader spotted it from the pictures.

No gate could have caught that, and that is the point: **a gate cannot check a fact
nobody wrote down.** The coverage gate verifies that canon *mentions* the entities the
prompt implies; nothing verified that anyone knew where those entities were standing,
what they were doing with their lives, or what they were wearing on page one.

So this stage produces that document, and gates it for completeness before a word is
planned. Four fields per principal — `where`, `doing`, `wears`, `changed` — and a
missing one is a hard rejection, because the absent field is always the one that turns
up wrong three hundred pages later.

It runs between research and planning: canon is frozen first, so the anchor is derived
from ground truth rather than from the prompt's summary of it, and the series bible is
seeded from the anchor rather than from canon directly.
"""

from .. import config, paths
from . import correction_brief
from ..infra import storage
from ..memory.bible import new_canon
from ..models import prompts, text

# The four things a story needs to know about a person before it can start, and the
# four this project has now been bitten by not knowing. `gaps` is deliberately not
# required: an honest blank is a different thing from a missing field.
REQUIRED = ("where", "doing", "wears", "changed")


def canon_block(series_rec):
    """Every frozen canon fact, quoted. One anchoring call reads all of it."""
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


def propose_anchor(series_rec, out_path, log_fn=None, feedback=""):
    """Model seam: produce the anchor-state JSON at out_path."""
    return text.produce_json(
        prompts.template("anchor_state") + feedback,
        ["THE JOB PROMPT — its 'Canon anchor point' section is the moment you are "
         "pinning, and it is literal. Read it before anything else:",
         series_rec["prompt_text"],
         "",
         "=" * 70,
         "FROZEN CANON — every field you write must be supportable from this:",
         "=" * 70,
         canon_block(series_rec)],
        out_path,
        role="anchoring",
        artifact="the anchor state as strict JSON",
        log_fn=log_fn)


def parse_age(value):
    """A plain count of years, or None if this is not one.

    The one field in this stage that is checked for *shape* rather than mere presence,
    because it is the only one an image model consumes as a number and the only one
    prose reliably states as a comparison. Every anchored principal of the first book
    carried an age, and every one of them read like "Young adult, four years on from
    the fourteen-year-old who first fell into the Demon Realm" — which names a
    direction and never a distance, so the model started at fourteen and guessed how
    far to travel. It guessed about a decade too far, on every page Luz Noceda appears.

    Accepted: `18`, `"18"`, `"18 years old"`. Refused: a life stage, a range, a cohort,
    and anything phrased relative to how old somebody used to be.

    `planning` imports this rather than writing its own, so the anchor and the plan
    cannot disagree about what an age is."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value or "").strip().lower()
    for suffix in ("years old", "year old", "yrs old", "yr old", "years", "year"):
        if text.endswith(suffix):
            text = text[:-len(suffix)].strip()
            break
    if not text.isdigit():
        return None
    number = int(text)
    return number if number > 0 else None


def _validate(anchor, expected_names):
    """Completeness of a proposed anchor state. Returns a list of errors.

    Strict about coverage and about empty fields, and deliberately not strict about
    content: this gate cannot tell a right answer from a wrong one, only a present one
    from an absent one. What it buys is that the absent field — the one that silently
    becomes the show's default and ships wrong — cannot happen quietly."""
    errors = []
    if not anchor.get("anchor_summary"):
        errors.append("anchor: no anchor_summary; say what moment in time this is")

    records = anchor.get("characters") or []
    if not records:
        return errors + ["anchor: no character records at all"]

    seen = set()
    for i, rec in enumerate(records, 1):
        name = (rec.get("name") or "").strip()
        if not name:
            errors.append(f"anchor: record {i} has no name")
            continue
        seen.add(name)
        for field in REQUIRED:
            if not (rec.get(field) or "").strip():
                errors.append(
                    f"anchor: {name} has no `{field}`. Every principal needs all four "
                    f"of {', '.join(REQUIRED)} — a missing one is the field that turns "
                    f"up wrong three hundred pages later.")
        if parse_age(rec.get("age")) is None:
            errors.append(
                f"anchor: {name} has no usable `age` — got {rec.get('age')!r}. It must "
                f"be a plain number of years at this moment, like 18. Not a life "
                f"stage, not a range, and above all not a comparison to how old they "
                f"used to be: an image model reads an age as a number, and a "
                f"comparison gives it a direction with no distance. For a being that "
                f"does not age, give the age they read as.")

    # Coverage against the cast the prompt actually named. A principal with no record
    # is precisely the hole this stage exists to close.
    missing = [n for n in expected_names if n not in seen]
    if missing:
        errors.append(
            f"anchor: no record for {', '.join(missing[:8])}"
            + (f" (and {len(missing) - 8} more)" if len(missing) > 8 else "")
            + ". The job prompt names them, so the story needs to know where they are.")
    return errors


def run(series_rec, log_fn=None):
    """Produce and gate the anchor state, then persist it. Returns the anchor dict."""
    from ..jobspec import main_characters

    sid = series_rec["series_id"]
    proposal = paths.anchor_proposal_path(sid)
    expected = main_characters(series_rec.get("prompt_text", ""))
    attempts = max(1, config.GATE_MAX_ATTEMPTS)
    feedback, errors, anchor = "", [], None

    for attempt in range(1, attempts + 1):
        propose_anchor(series_rec, proposal, log_fn=log_fn, feedback=feedback)
        anchor, why = storage.load_proposal(proposal)
        errors = ([why or "the anchor state is not a JSON object"]
                  if not isinstance(anchor, dict) else _validate(anchor, expected))
        if not errors:
            break
        if log_fn:
            log_fn(f"anchoring: rejected (attempt {attempt}/{attempts}): {errors[:3]}")
        feedback = correction_brief(errors, attempt, attempts)

    if errors:
        raise RuntimeError(f"anchoring: incomplete after {attempts} attempts: "
                           f"{errors[:4]}")

    storage.save_json(anchor, paths.anchor_path(sid))
    if log_fn:
        log_fn(f"{sid}: anchor state pinned for "
               f"{len(anchor.get('characters', []))} character(s)")
    return anchor


def block(series_id):
    """The anchor state as one inline block, for the prompts that need it."""
    anchor = storage.load_json(paths.anchor_path(series_id), {})
    records = anchor.get("characters") or []
    if not records:
        return ""
    lines = ["WHERE EVERYONE IS WHEN THIS STORY OPENS (the anchor state — this is the "
             "present, and it OVERRIDES how a character looked or lived during their "
             "series):",
             f"  {anchor.get('anchor_summary', '')}",
             ""]
    for rec in sorted(records, key=lambda r: r.get("name", "")):
        # Rendered as "(18)" rather than the raw field, so the planner copying this
        # block into the plan's `age` copies a number. The gate guarantees one exists.
        lines.append(f"  {rec.get('name')} ({parse_age(rec.get('age'))})")
        lines.append(f"      where:   {rec.get('where', '')}")
        lines.append(f"      doing:   {rec.get('doing', '')}")
        lines.append(f"      wears:   {rec.get('wears', '')}")
        lines.append(f"      changed: {rec.get('changed', '')}")
        if (rec.get("gaps") or "").strip():
            lines.append(f"      (canon does not settle: {rec['gaps']})")
    return "\n".join(lines)


def for_characters(series_id, names):
    """The anchor slice for just these characters, for a per-chapter brief."""
    anchor = storage.load_json(paths.anchor_path(series_id), {})
    wanted = set(names)
    lines = []
    for rec in anchor.get("characters") or []:
        if rec.get("name") in wanted:
            lines.append(f"  {rec['name']}: {rec.get('wears', '')} "
                         f"| {rec.get('doing', '')}")
    return "\n".join(lines)
