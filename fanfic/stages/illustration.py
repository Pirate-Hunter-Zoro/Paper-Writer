"""Stages 3 & 6 — Illustration. Lock a reference sheet per character, then render
scenes that reuse those sheets so recurring characters stay identical.

This is the answer to hard problem 3, and the place the previous attempt at this
project died. The image model has no memory across requests and drifts badly on
recurring characters, so consistency is engineered rather than hoped for:

  * one LOCKED reference sheet per character, generated up front from the canon
    appearance, vision-checked, then frozen and reused for the whole series;
  * every scene render supplies the relevant sheets as reference inputs plus a fixed
    style block and each character's locked identity clause spelled out verbatim;
  * every render is vision-critiqued against its spec and regenerated on an
    ever-simplifying ladder — the same propose/critique/dispose contract as the prose.

**A picture is never given up on.** A slot is resolved by an image existing and by
nothing else: a render that will not come out defers, waits, and is retried a rung
further down the simplification ladder, exactly as a stalled unit of prose does. A
quota hit is the same kind of thing one layer up — it raises QuotaExceeded so the
engine comes back later.
"""

import json
import re
import time

from .. import config, paths
from ..errors import QuotaExceeded
from ..gates import segments
from ..infra import budget, storage
from ..models import images, prompts, text
from ..models.images import NotSignedIn, Refused
from . import refart


# --- Resolution bookkeeping --------------------------------------------------
#
# The engine needs to ask "is this slot done with?" without caring how, so these
# are public API, not internals borrowed across a module boundary.
#
# NOTHING HERE IS TERMINAL. This is the image half of the rule the prose half already
# lives by: a chapter that will not come clean is not thrown away, it ships carrying
# its defects and is come back to. An image slot has no equivalent of "ships carrying
# defects" — a hole in the book is a hole — so the whole of that rule lands on the
# retry: a slot that cannot be rendered now waits and is rendered later.
#
# What makes that terminate rather than spin is the ladder in `build_scene_prompt`
# and `_sheet_prompt`. Each deferral resumes one rung lower, asking for a plainer
# picture than the one that just failed, and the bottom rung is a picture of the
# setting with nobody in it — which has no identity to get wrong and no composition to
# fail at. The slot fills because the request eventually becomes trivial, not because
# we hoped the model would change its mind.

def retry_marker(dest):
    """Sidecar holding a deferred slot's attempt count and the time to try again.

    On disk beside the image, so the ladder's position survives a crash: without it
    every restart would re-ask for the elaborate composition that has already been
    rejected three times, and the escalation would never escalate."""
    return dest.with_name(dest.name + ".retry")


def _legacy_skip_marker(dest):
    """The `.skipped` sidecar an older build wrote to abandon a slot permanently.

    Read, never written. It is treated as a deferral that is due now, which is what
    revives a slot an earlier run gave up on without anybody having to go and delete
    files — the same rewind-rather-than-honour treatment `states.DEAD_ENDS` gets."""
    return dest.with_name(dest.name + ".skipped")


def is_resolved(dest):
    """A slot is resolved when the picture exists. There is no other way."""
    return dest.exists()


def _retry_state(dest):
    marker = retry_marker(dest)
    if marker.exists():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    if _legacy_skip_marker(dest).exists():
        return {"attempts": config.IMAGE_MAX_REGENERATIONS, "next_at": 0}
    return {}


def attempts_so_far(dest):
    """The ladder rung this slot has already reached, across every cycle.

    Read rather than restarting at zero, which is the difference between three
    escalating attempts and the same failing attempt forever.

    `attempts` is the legacy key: sidecars written before rung and visits were split
    stored one number meaning both, and reading it as a rung is the right reading of
    an old file — it is what the ladder used it for."""
    state = _retry_state(dest)
    for key in ("rung", "attempts"):
        if key in state:
            try:
                return max(0, int(state.get(key) or 0))
            except (TypeError, ValueError):
                return 0
    return 0


def visits_so_far(dest):
    """How many times this slot has been parked and come back. Drives the backoff."""
    state = _retry_state(dest)
    try:
        return max(0, int(state.get("visits") or state.get("attempts") or 0))
    except (TypeError, ValueError):
        return 0


def due(dest, now=None):
    """Whether a deferred slot's backoff has elapsed. Never-attempted slots are due."""
    if is_resolved(dest):
        return False
    try:
        next_at = float(_retry_state(dest).get("next_at") or 0)
    except (TypeError, ValueError):
        return True
    return (now if now is not None else time.time()) >= next_at


def defer(dest, reason, rung, now=None):
    """Park a slot that would not render, and say when to come back to it.

    TWO NUMBERS, NOT ONE, and conflating them was a bug worth spelling out. The ladder
    needs the RUNG this slot reached — how plain a picture it is now asking for. The
    backoff needs the number of VISITS — how many times we have come back. They used to
    be the same integer, which was true only while every failed attempt cost a rung.

    Once a refusal stopped costing a rung (see `images.Refused`), they diverged and the
    single number broke both halves. It was floored at 1, so a slot parked at rung 0
    resumed at rung 1 and crept up a rung per visit despite never being rejected. And
    the backoff exponent was `n - IMAGE_MAX_REGENERATIONS`, which with a rung in it is
    almost always zero — so a slot the vendor simply refuses was retried every five
    minutes forever instead of easing off toward an hour."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    rung = max(0, int(rung))
    visits = visits_so_far(dest) + 1
    wait = min(config.IMAGE_RETRY_BACKOFF_MAX_SEC,
               config.IMAGE_RETRY_BACKOFF_BASE_SEC * (2 ** max(0, visits - 1)))
    now = now if now is not None else time.time()
    storage.atomic_write_text(json.dumps(
        {"rung": rung, "visits": visits, "next_at": now + wait,
         "reason": (reason or "")[:500]}), retry_marker(dest))
    _legacy_skip_marker(dest).unlink(missing_ok=True)
    return wait


def clear_retry(dest):
    """Drop a slot's deferral record once the picture lands."""
    retry_marker(dest).unlink(missing_ok=True)
    _legacy_skip_marker(dest).unlink(missing_ok=True)


def sheet_sources_marker(dest):
    """Sidecar recording how many pieces of the show's own art a sheet was drawn from.

    It exists to answer one question nothing else on disk can: was this sheet drawn
    from pictures, or from a paragraph? Both produce a `.png` that looks like a
    character, so "the sheet exists" was being read as "the anchor is good" for
    twenty-three of this book's cast. A sheet is the reference image on every render
    its character appears in, so a blind one propagates for the whole book."""
    return dest.with_name(dest.name + ".sources")


def mark_sheet_sources(dest, count):
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet_sources_marker(dest).write_text(str(int(count)), encoding="utf-8")


def sheet_source_count(dest):
    """How much source art a locked sheet was drawn from. -1 when unrecorded.

    Unrecorded is deliberately distinct from zero: sheets locked before this was
    written have no marker, and the caller decides what to do about that rather than
    being told a number nobody measured."""
    marker = sheet_sources_marker(dest)
    try:
        return int(marker.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return -1


def mark_kept_with_note(dest, reason):
    """Sidecar recording that an image shipped carrying a critic's note.

    The image IS there and the book uses it. This is the audit trail for "which
    pictures is the critic still unhappy with", which is a list somebody can review
    rather than a quality claim nobody made."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.with_name(dest.name + ".note").write_text((reason or "")[:500],
                                                   encoding="utf-8")


def _locked(series_id, name):
    """One character's locked spec out of the series bible."""
    bible = storage.load_json(paths.series_bible_path(series_id), {})
    return (bible.get("characters") or {}).get(name, {})


def costume_for_chapter(spec, chapter_num=None):
    """Which of a character's costumes is current as of a given chapter.

    **This is the first time the visual anchor is not constant across a book**, and it
    exists because a progression that changes how somebody looks invalidates their
    locked reference sheet for every chapter after it. A character who gains a mantle
    of Titan light in chapter 28 must not be drawn wearing it in chapter 3, and must
    not be drawn without it in chapter 40.

    So a costume entry may carry the chapter it starts in, and the latest one that has
    started wins. Entries are either plain strings — the base look, current from page
    one — or `{"from_chapter": n, "text": ...}`. Plain strings are what every existing
    bible holds, so they keep working untouched.

    With no chapter given, the base costume is returned. That is the right answer for a
    reference sheet, which exists to settle a face rather than to catalogue a wardrobe.

    **A plain string is a wardrobe entry, not a timeline entry, and it can never
    displace another one.** A bible lists a character's looks the way a wardrobe holds
    them — several, in no particular order, all equally "current" — so the base look is
    the FIRST of them and the rest are alternatives a scene may call for. Only a dated
    entry moves the anchor, because only a dated entry is a claim about when.

    Getting that wrong is not theoretical. Ranking undated entries against each other
    and letting the last one win dressed 51 of 55 characters in the final item of their
    own wardrobe list for every chapter before their first dated variant: Eda in the
    hook Hunter has not carved yet, Hooty in his shed-skin skeleton form, Luz in the
    patched field kit of an organisation that does not exist on page one. Every one of
    those pictures is on disk and every one of them is wrong."""
    base, best, best_at = "", "", 0
    for entry in (spec or {}).get("costumes") or []:
        if isinstance(entry, dict):
            text = str(entry.get("text") or "").strip()
            starts = int(entry.get("from_chapter") or 1)
        else:
            text, starts = str(entry).strip(), 0
        if not text:
            continue
        if not starts and not base:
            base = text
        # `> best_at`, never `>=`, and undated entries carry 0 so they can never win
        # this comparison at all. The base look is chosen by position in the list, not
        # by surviving a tie.
        if (starts and chapter_num is not None
                and starts <= int(chapter_num) and starts > best_at):
            best, best_at = text, starts
    return best or base


def keep_rate(series_id):
    """The fraction of billed renders for this series that produced a kept picture.

    The vendor charges for a render the vision critic rejects, so a budget that counts
    only the keepers overruns by exactly the reject rate. This measures the real one off
    the two records that already exist — the picture ledger counts what was billed, the
    disk holds what was kept — rather than applying a guessed multiplier.

    That only means anything because the ledger counts **renders**, not slots. It used
    to be incremented once per slot by the engine, after up to `IMAGE_MAX_REGENERATIONS`
    renders inside `render_scene` had already been paid for — so this ratio measured
    how many slots produced a file, which is a skip rate and sits near 1.0 on a healthy
    run. See `billed_render`.

    Counted across every book in the series, because the ledger it is divided by is
    per-series. Comparing one book's files against the whole series' spend would report
    a falling keep rate on book 2 purely because book 1's renders are still in the
    denominator, and the cap would tighten for a reason that is not real.

    Returns 1.0 until there is something to measure, which is deliberate: the
    instruction is to measure the rate over the first chapters and let the cap adjust,
    not to pick a number in advance. A limit set before measuring the thing it limits is
    a guess wearing a number."""
    billed = budget.images_generated(series_id)
    if billed <= 0:
        return 1.0
    root = paths.series_root(series_id) / "book"
    kept = sum(1 for p in root.glob("*/images/*.png")) if root.exists() else 0
    kept += sum(1 for p in root.glob("*/sheets/*.png")) if root.exists() else 0
    return min(1.0, max(0.05, kept / billed))


def _scene_references(sid, book_num, names):
    """The pictures attached to one scene render, in priority order.

    SHEETS FIRST, FOR EVERYONE, THEN SOURCE ART FOR THE LEADS. Order is load-bearing
    because the list is truncated at `IMAGE_MAX_UPLOADS`, and truncation takes the
    front. Interleaved per character — lead's art, lead's sheet, second's art,
    second's sheet — a four-hander builds a list of eight and the cap of six silently
    removes the LAST characters' sheets. Those characters then arrive with no
    reference at all, which is the case the design says must never happen: everyone
    outside the lead is anchored by their locked sheet alone.

    It showed up as a background figure rendered as a completely different person — a
    leathery sixty-year-old with untidy grey hair came back as a clean-shaven man of
    forty-five — while the log reported eight references attached.

    A function rather than inline, because `render_scene` rebuilds this mid-loop when
    the critic names somebody as wrong and that person is promoted to the front."""
    lead = max(1, config.IMAGE_REFERENCE_CHARACTERS)
    sheets, extra_art = [], []
    for position, name in enumerate(names):
        sheet = paths.sheet_path(sid, book_num, name)
        if sheet.exists():
            sheets.append(sheet)
        if position < lead:
            extra_art += refart.for_character(
                sid, book_num, name)[:config.REF_IMAGES_PER_RENDER]
    return sheets + extra_art


def flagged_wrong(verdict, known_names):
    """Which of this scene's characters the critic says came out wrong.

    Reads `wrong_who` when the critic supplies it, and falls back to scanning the
    issue text for the scene's own cast names — older verdicts on disk predate the
    field, and a critic occasionally forgets it. Matching only against names already
    in this scene is what keeps the fallback safe: it cannot invent a character."""
    named = [n for n in (verdict.get("wrong_who") or []) if n in known_names]
    if named:
        return named
    blob = " ".join(str(i) for i in (verdict.get("issues") or []))
    return [n for n in known_names if n and n in blob]


def _locked_place(series_id, name):
    """One location's locked description out of the series bible."""
    bible = storage.load_json(paths.series_bible_path(series_id), {})
    return (bible.get("locations") or {}).get(name, {})


def _aspect_for(orientation):
    return (config.IMAGE_ASPECT_LANDSCAPE if orientation == "landscape"
            else config.IMAGE_ASPECT_PORTRAIT)


# --- Model seams -------------------------------------------------------------

def render(prompt, out_path, references=None, log_fn=None, aspect=None):
    """Model seam: one image generation."""
    images.generate(prompt, out_path, references=references, timeout=600,
                    log_fn=log_fn, aspect=aspect)


def billed_render(prompt, out_path, label, series_id, references=None, log_fn=None,
                  aspect=None):
    """One render, counted against the picture budget as it happens.

    **Every attempt is counted, including the ones a vision critic then rejects**, and
    that is the whole reason this wrapper exists. The count used to be incremented once
    per *slot* by the engine, after up to `IMAGE_MAX_REGENERATIONS` renders had already
    happened inside `render_scene` — so the meter recorded 1 where three had been spent,
    `image_budget_remaining` was over-optimistic by exactly the regeneration factor, and
    a run with an unlucky vision critic could blow several times through the ceiling with
    every counter reading green.

    The ceiling counts RENDERS now rather than dollars — the pictures come out of a
    browser session and cost nothing but wall-clock — which changes what over-counting
    protects and not whether it is right. A render that fails mid-flight still took the
    time, and the safe direction to be wrong about a runaway stop is over-counting."""
    budget.record_image(series_id, label)
    render(prompt, out_path, references=references, log_fn=log_fn, aspect=aspect)


def vision_verdict(image_path, spec_text, references=(), log_fn=None):
    """Model seam: critique one image. Returns {passed, issues}.

    `references` are the SAME pictures the generator was given — the character's real
    art off their source wiki, and their locked sheet. Without them this critic could
    not check identity at all, and the failure was invisible because it looked like it
    could.

    A prose paragraph cannot carry a face. That is not an opinion, it is the founding
    premise of `stages/refart.py`, which fetches real pictures precisely because "there
    is no wording for this exact jaw". The generator was given pictures and the judge
    was given the paragraph, so the judge was asking "is this a heavyset young man in a
    green shirt with a question mark on it" — and a moustached stranger in a headlamp
    cap satisfies that completely. It passed, correctly, against the document it had.

    The signature of the defect is what survived it: every character who came out wrong
    was an ordinary-looking human — Soos, Anne, Perfuma, Pacifica — and every one who
    came out right had an unmistakable silhouette, Bow's crop top, Dipper's ushanka,
    Raine's green hair. Prose checks costume. Only a picture checks a face.

    This is the same generator/judge document mismatch recorded three times elsewhere in
    this project, one layer further down, and it is why the critic is not one-shot: it
    has `Read` and a twenty-turn budget so it can open all of them.

    `spec_text` is the LOCKED IDENTITY of the characters who should be in frame — not
    the staging description. That distinction is the whole reason the image half of
    this project produced pictures nobody could identify.

    The critic used to be handed `entry["scene"]`, the one-sentence staging line, and
    told to check "correct character, correct costume, correct palette". It had no
    access to what any character was supposed to look like, so it could not check
    identity at all, and dutifully checked the only document it had: the staging. The
    verdicts are the receipt — "the mug is not empty", "the fez is on a hook rather
    than in Stan's hand", "the tail is trailing rather than coiled". Three
    regenerations of that and the slot was skipped.

    This is the same defect as the prose loop's, one layer down and recorded twice
    already in this project's failure stories: whenever a generator and its judge read
    different documents for the same fact, the loop between them cannot converge, and
    the symptom looks like a stubborn model rather than a missing input."""
    out_path = paths.vision_verdict_path(image_path)
    facts = [f"The image to judge is at: {image_path}",
             "Open it and look at it before answering.",
             ""]
    if references:
        facts += [
            "REFERENCE PICTURES OF WHO THESE PEOPLE ACTUALLY ARE. Open every one of "
            "them before you answer. These are the same pictures the image model was "
            "given, so you and it are looking at the same faces — compare the render "
            "against these, not against the words below:",
            "\n".join(f"  {path}" for path in references),
            ""]
    facts += [
        "THE LOCKED DESIGN OF EVERY CHARACTER WHO SHOULD BE IN FRAME — this is your "
        "ground truth for costume and colour. Where it and the reference pictures "
        "disagree about a FACE, the pictures win:",
        spec_text or "(no named characters; judge craft only)"]
    return text.produce_json(
        prompts.template("vision"), facts, out_path,
        role="vision",
        artifact="your verdict as strict JSON",
        shape='{"passed": bool, "wrong_character": bool, '
              '"wrong_who": [str, ...], "issues": [str, ...]}',
        log_fn=log_fn)


def propose_scenes(series_rec, book_num, chapter_num, prose_text, n, log_fn=None,
                   scope="", must_show="", slot=0):
    """Model seam: read accepted prose and pick the n most illustratable moments.

    Returns [{description, characters, orientation}].

    `prose_text` is normally **one scene segment**, not the whole chapter, which is the
    change that makes the chosen moment guaranteed to be in that setting. It used to be
    the whole chapter with a request for two moments out of it, and a model asked to
    summarise five settings into two pictures picks the two it found most dramatic and
    ignores where they happen — which is how a chapter with a dinner scene in it ended
    up with no picture of the dinner.

    `scope` says what the text is, `must_show` names anything this picture is obliged
    to contain, and `slot` keeps each segment's proposal file distinct so a failure is
    diagnosable by reading what was actually written."""
    out_path = paths.scenes_proposal_path(series_rec["series_id"], book_num,
                                          chapter_num, slot)
    facts = [f"Choose {n} illustration(s) for the text below.",
             scope or "This is one chapter of the book.",
             _locations_brief(series_rec),
             f"HARD MAXIMUM: {config.IMAGE_MAX_CHARACTERS} named characters in any one "
             f"image. Prefer one or two. Frame the moment smaller rather than exceeding "
             f"it — an image model handed more than this produces merged figures and "
             f"lost costumes, and the picture is thrown away."]
    if must_show:
        facts += ["",
                  "THIS PICTURE IS OBLIGED TO SHOW THE FOLLOWING, and that outranks "
                  "picking the prettiest moment. Find the instant in the text below "
                  "where it actually happens and draw that:",
                  f"  {must_show}"]
    facts += ["", "THE TEXT:", prose_text]
    data = text.produce_json(
        prompts.template("art_direction"), facts, out_path,
        role="art_direction",
        artifact="the scene list as strict JSON",
        shape='{"scenes": [{"description": str, "characters": [str, ...], '
              '"location": str, "orientation": "portrait"|"landscape"}, ...]}',
        log_fn=log_fn)
    return (data.get("scenes") or [])[:n]


def resolve_cast_name(known, name):
    """Map a name the art director used onto the one the bible actually uses.

    The director works from the chapter prose, which calls people what the prose calls
    them — "Ford Pines" for a bible entry filed as "Stanford Pines", "Stan Pines" for
    "Stanley Pines", "Eda" for "Eda Clawthorne". An unresolved name has no locked
    design, no reference art and no sheet that will ever exist, so the sheets-first
    gate defers that scene forever and the whole image queue stops behind it.

    Scored rather than first-match, because the interesting cases are the ambiguous
    ones: "Stan" is a prefix of both Stanley and Stanford, and getting it wrong swaps
    two brothers. Each query word must match a candidate word as a prefix or a
    substring, and among the candidates that qualify the closest in length wins —
    which puts "Stan" on Stanley and "Ford" on Stanford, both correctly.

    Returns None when nothing matches, which is the caller's cue to drop the name
    rather than wait forever on it."""
    if name in known:
        return name
    lowered = {k.lower(): k for k in known}
    if name.lower() in lowered:
        return lowered[name.lower()]

    words = [w.lower() for w in re.findall(r"[A-Za-z']+", name) if len(w) > 1]
    if not words:
        return None

    best, best_score = None, None
    for candidate in known:
        cand_words = [w.lower() for w in re.findall(r"[A-Za-z']+", candidate)]
        if not cand_words:
            continue
        distance = 0
        for word in words:
            hit = None
            for cand in cand_words:
                if cand == word:
                    hit = 0
                    break
                if cand.startswith(word) or word.startswith(cand):
                    hit = min(hit, abs(len(cand) - len(word))) if hit is not None \
                        else abs(len(cand) - len(word))
                elif word in cand or cand in word:
                    penalty = abs(len(cand) - len(word)) + 1
                    hit = min(hit, penalty) if hit is not None else penalty
            if hit is None:
                distance = None
                break
            distance += hit
        if distance is None:
            continue
        # Prefer the closer match, and break ties toward the shorter canonical name.
        score = (distance, len(candidate))
        if best_score is None or score < best_score:
            best, best_score = candidate, score
    return best


def vet_scenes(series_rec, chapter_num, scenes, log_fn=None):
    """Deterministic guards over whatever the art director came back with.

    Deliberately OUTSIDE the model seam. Both of these are about what a render will do
    with the list rather than about what a good scene is, so they have to hold for the
    fallback path and for a stubbed seam too — and the first version of this lived
    inside `propose_scenes`, where exactly one of those was true."""
    known = list((storage.load_json(
        paths.series_bible_path(series_rec["series_id"]), {}
    ).get("characters") or {}).keys())
    for scene in scenes:
        # A character described in the scene but absent from the list reaches the
        # image model with NO design attached, and the model fills the gap from
        # whatever description is nearest. That produced a diner scene with two
        # identical Luzes, one of whom was supposed to be her mother.
        described = scene.get("description", "")
        # Every listed name must be one the bible knows, or the scene waits forever on
        # a sheet that cannot exist.
        resolved = []
        for raw in (scene.get("characters") or []):
            canonical = resolve_cast_name(known, raw)
            if canonical is None:
                if log_fn:
                    log_fn(f"ch {chapter_num}: dropping {raw!r} from a scene — no such "
                           f"character in the bible, so nothing could anchor them")
                continue
            if canonical != raw and log_fn:
                log_fn(f"ch {chapter_num}: {raw!r} is {canonical!r} in the bible")
            resolved.append(canonical)
        names = list(dict.fromkeys(resolved))
        for who in known:
            if who in described and who not in names:
                names.append(who)
                if log_fn:
                    log_fn(f"ch {chapter_num}: {who} is in the scene text but was "
                           f"not listed; attaching their locked design")
        # Then the ceiling. An over-full cast is not a style disagreement, it is a
        # render that will fail — and the first names are the ones the director led
        # with, so trimming keeps its intent.
        if len(names) > config.IMAGE_MAX_CHARACTERS:
            if log_fn:
                log_fn(f"ch {chapter_num}: trimmed a scene from {len(names)} to "
                       f"{config.IMAGE_MAX_CHARACTERS} named characters")
            names = names[:config.IMAGE_MAX_CHARACTERS]
        scene["characters"] = names
    return scenes


def _locations_brief(series_rec):
    """The places this book has locked descriptions for, so the art director can name
    one exactly and have it attached."""
    bible = storage.load_json(paths.series_bible_path(series_rec["series_id"]), {})
    names = sorted((bible.get("locations") or {}).keys())
    if not names:
        return ""
    return ("LOCATIONS WITH LOCKED DESCRIPTIONS — name one of these EXACTLY as "
            "`location` when the scene happens there, and its full visual "
            "description is attached to the render:\n  "
            + "\n  ".join(names))


def segments_to_draw(count, cap, required=()):
    """Which segment indices (0-based) get a picture, given a per-chapter ceiling.

    Every segment when the budget allows it — one setting, one picture, which is the
    arrangement the whole per-segment change is for. When the ceiling bites, the
    segments are spread evenly across the chapter rather than taken from the front,
    because a book whose pictures all sit in the first half is worse than one with
    fewer pictures evenly placed.

    `required` segments are kept whatever the ceiling says: a chapter that delivers a
    character's escalation owes a picture of it, and dropping that one to stay under a
    budget defeats the reason it was mandatory."""
    if count <= 0:
        return []
    required = sorted({i for i in required if 0 <= i < count})
    if cap >= count:
        return list(range(count))
    keep = list(required[:cap])
    free = max(0, cap - len(keep))
    if free:
        # Evenly spaced picks across the whole chapter, skipping anything already kept.
        spread = [round(i * (count - 1) / max(1, free - 1)) if free > 1 else count // 2
                  for i in range(free)]
        for index in spread:
            for candidate in list(range(index, count)) + list(range(index, -1, -1)):
                if candidate not in keep:
                    keep.append(candidate)
                    break
    return sorted(keep)[:cap]


def scenes_for_chapter(series_rec, book_num, chapter_num, prose_text, cap,
                       log_fn=None, required=(), must_show="", already=()):
    """Choose this chapter's illustrations, **one per scene segment**.

    Each returned scene carries a `segment` number, which becomes its image slot — so
    picture 3 of a chapter is picture 3 *of segment 3*, and the binder places it at the
    end of that stretch of text rather than after the last paragraph of the chapter.
    That one identification is what turns `IMAGES_PER_CHAPTER` from a count into a
    ceiling: how many pictures a chapter gets is how many times it changes scene,
    bounded by what the budget allows.

    An unsegmented chapter — one a writer delivered without break lines, which the
    segments gate exists to prevent and which a chapter shipping with defects can still
    be — degrades to the old whole-chapter behaviour rather than to one picture.

    `must_show` is something this chapter's pictures are obliged to contain — an
    escalation the chapter delivers, say. It is given to EVERY segment's art director
    rather than to one, because which segment the moment lands in is not knowable
    without another judgement call over the prose; each is told to draw it if the moment
    is theirs. The caller compensates for the imprecision by buying the chapter an extra
    slot, so a tight budget cannot squeeze the obliged picture out.

    `already` is the segments this chapter has been directed for on an earlier pass,
    and it makes the whole function a TOP-UP rather than an all-or-nothing. A chapter
    directed under a lower ceiling is short by exactly the segments nobody chose a
    moment for, and this fills those and re-pays for none of the others — which is what
    lets a raised ceiling reach chapters that are already written."""
    parts = segments.split(prose_text)
    already = {int(k) for k in already or ()}

    if len(parts) < 2:
        if log_fn:
            log_fn(f"ch {chapter_num}: no scene breaks in the accepted prose; "
                   f"choosing {cap} moment(s) from the chapter as a whole")
        scenes = _propose_or_fallback(
            series_rec, book_num, chapter_num, prose_text, cap, log_fn=log_fn,
            scope="This is a whole chapter, delivered without scene breaks.",
            must_show=must_show)
        numbered = []
        for k, scene in enumerate(scenes, 1):
            scene["segment"] = k
            if k not in already:
                numbered.append(scene)
        return numbered

    scenes = []
    wanted = [i for i in segments_to_draw(len(parts), cap, required=required)
              if (i + 1) not in already]
    for index in wanted:
        got = _propose_or_fallback(
            series_rec, book_num, chapter_num, parts[index], 1, log_fn=log_fn,
            slot=index + 1,
            scope=f"This is scene {index + 1} of {len(parts)} in the chapter. Choose "
                  f"the moment from THIS scene — a moment from elsewhere in the "
                  f"chapter is the wrong picture, because this one is printed at the "
                  f"end of this stretch of text.",
            must_show=must_show)
        for scene in got[:1]:
            scene["segment"] = index + 1
            scenes.append(scene)
    if log_fn:
        log_fn(f"ch {chapter_num}: {len(parts)} scene segment(s), "
               f"{len(scenes)} newly illustrated (cap {cap}"
               + (f", {len(already)} already queued)" if already else ")"))
    return scenes


def _propose_or_fallback(series_rec, book_num, chapter_num, prose_text, n,
                         log_fn=None, scope="", must_show="", slot=0):
    """`propose_scenes` with a deterministic fallback: if scene selection fails for
    any reason, fall back to the text's own opening lines, so the chapter gets
    illustrations rather than silently none."""
    try:
        scenes = propose_scenes(series_rec, book_num, chapter_num, prose_text, n,
                                log_fn=log_fn, scope=scope, must_show=must_show,
                                slot=slot)
        if scenes:
            return vet_scenes(series_rec, chapter_num, scenes, log_fn=log_fn)
    except (RuntimeError, ValueError, KeyError) as exc:
        if log_fn:
            log_fn(f"scene selection fell back for ch {chapter_num}: {exc}")
    snippet = " ".join(prose_text.split()[:40])
    return vet_scenes(series_rec, chapter_num,
                      [{"description": snippet, "characters": [],
                        "orientation": "portrait"} for _ in range(n)],
                      log_fn=log_fn)


# --- Prompt construction (pure) ---------------------------------------------

def style_block(style=None):
    """The art-style block stamped on every image prompt for this book. A job's own
    art direction wins; config.IMAGE_STYLE is the fallback. This is the *style* half
    of visual consistency — the locked per-character appearance is the identity half,
    and both go into every prompt."""
    return (style or "").strip() or config.IMAGE_STYLE


def _sheet_prompt(character, style=None, simplify=0, from_source_art=False):
    """The reference sheet for one character — the anchor every scene render leans on.

    Two things this prompt fights, both learned the hard way.

    **It never says "model sheet".** That phrase names a real artistic convention, and
    the convention *includes captions*: panel labels, a name plate, costume titles. Ask
    for a model sheet and then forbid text and you are fighting the thing you just
    asked for — three sheets in a row came back captioned FULL BRIGHT MOON COURT DRESS
    and FINALE, and one was skipped entirely for it. Describing the layout instead of
    naming the format gets the same picture without the lettering.

    **No text at all, and it matters more here than anywhere.** A sheet is handed to the
    image model as a reference *image* on every scene its character appears in — around
    74 renders for a principal — so anything drawn on it conditions the whole book.

    `simplify` is the retry ladder, same idea as a scene: a layout the model just failed
    is not improved by asking again in the same words. Level 1 drops to two views, level
    2 to a single plain standing portrait, and level 3 and below to a head-and-shoulders
    face on a blank ground — the most reliable thing an image model renders, and still
    a perfectly good identity anchor, which is what a sheet is for. There is no rung
    beneath it because there does not need to be: a face on a plain background is a
    request nothing has ever failed, so the sheet lands rather than being abandoned."""
    costumes = character.get("costumes") or []
    outfit = (costumes[0] if costumes else "").strip().rstrip(".")
    if ":" in outfit[:24]:
        outfit = outfit.split(":", 1)[-1].strip()

    if simplify >= 3:
        layout = ("A head-and-shoulders portrait of one character, facing the viewer, "
                  "on a plain flat background.")
    elif simplify == 2:
        layout = ("A single full-body standing portrait of one character, facing the "
                  "viewer, on a plain flat background.")
    elif simplify == 1:
        layout = ("One character shown twice on a plain flat background: a full-body "
                  "standing view, and a head-and-shoulders close-up beside it.")
    else:
        layout = ("One character shown three times on a plain flat background: a "
                  "full-body view from the front, a full-body view from a three-quarter "
                  "angle, and a head-and-shoulders close-up of the face.")

    appearance = character.get("appearance", "")
    # The age leads. It was arriving halfway through a paragraph of hair and costume,
    # competing with a reference photograph, and losing.
    age = re.match(r"\s*([A-Z][a-z]+(?:[- ][a-z]+)?|\d{1,2})\b", appearance)
    headline = (f"The character is {age.group(1).lower()} years old. "
                if age and not age.group(1).lower() in ("a", "an", "the") else "")
    lines = [layout, "", f"{headline}The character: {appearance}"]
    if outfit:
        lines += ["", f"They are wearing: {outfit}."]
    # ONE outfit. Asking for costume variants is what was putting captions on these
    # sheets: a multi-outfit layout is a *chart*, and a chart wants labels — three
    # sheets in a row came back captioned FULL BRIGHT MOON COURT DRESS, University of
    # Wild Magic, Storm-soaked traveling gear, however firmly the prompt forbade text.
    # A sheet exists to settle a face, not to catalogue a wardrobe, and the outfit a
    # given scene needs is named in that scene's own prompt.
    if from_source_art:
        # Take the DESIGN from the reference and the AGE from the description.
        #
        # The first version of this said "match the apparent age to the pictures", and
        # it was exactly backwards for the thing this project writes. Reference art
        # shows a character at their series age; a book anchored at the epilogues is
        # years later. Told to match the pictures, the model drew a seventeen-year-old
        # Mabel Pines as the twelve-year-old the wiki has photographs of — which is the
        # complaint that started this whole rebuild, arriving from the opposite
        # direction.
        #
        # So the split has to be stated, because the two instructions genuinely pull
        # apart: the reference settles who this is, the text settles how old they are.
        lines += ["", "The attached pictures are this character as their own show "
                      "draws them. Take their DESIGN from those pictures — the face, "
                      "the features, the hair, the costume shapes, the colours, the "
                      "way they are constructed. That is who this person is.",
                  "",
                  "But the pictures show them YOUNGER than this book does. Draw them "
                  "at the age given in the description above, not the age in the "
                  "pictures: the same person, grown up, with the proportions and the "
                  "face of someone that age. Recognisably themselves, older."]
    lines += ["", style_block(style), "",
              "The image must contain NO text whatsoever: no name, no caption, no "
              "panel labels, no costume titles, no arrows, no annotations, no speech "
              "bubbles, no signature, no watermark, no borders or frames. Nothing but "
              "the character on a plain background."]
    return "\n".join(lines)


def _character_line(name, spec, chapter_num=None):
    """One character's LOCKED identity clause, spelled out verbatim because the
    image model cannot remember a face it has no memory of.

    The costume is selected by chapter, so a character who gains or loses something
    partway through the book is drawn correctly on both sides of it.

    The palette is deliberately NOT included as hex codes. An image model handed
    `#b30000, #2b2b2b, #f0e2c0` does not paint with them; it reads them as noise in
    the middle of a description and the sentence around them gets less attention. The
    reference sheet carries the colours, which is what a reference is for."""
    spec = spec or {}
    appearance = (spec.get("appearance", "").strip().rstrip(".")
                  or "as established in canon")
    # Age leads, as a bare number of years, before any adjective gets a chance to
    # modify it. "Grown into adult height rather than the fourteen-year-old who fell
    # in" is a sentence with no age in it — it is a direction of travel with no
    # distance — and every picture drawn from it aged Luz Noceda about a decade.
    age = str(spec.get("age") or "").strip()
    line = f"{name}: {age} years old. {appearance}" if age else f"{name}: {appearance}"
    costume = costume_for_chapter(spec, chapter_num).rstrip(".")
    if costume:
        # Bible costumes are often labelled ("Everyday: purple hoodie…"). The label is
        # bookkeeping for a human reading the bible; handed to an image model it reads
        # as part of the garment and turns up as lettering or confusion.
        costume = costume.split(":", 1)[-1].strip() if ":" in costume[:24] else costume
        line += f", wearing {costume}"
    return line + "."


def species_of(spec):
    """The character's species, when it is not human. "" for humans and unknowns.

    Locked appearances open with it by convention — "Togruta female, fifty-five…",
    "Kel Dor male, sixty-five…", "Human female, nineteen…" — so it is the first clause
    with any trailing sex word removed."""
    first = str((spec or {}).get("appearance") or "").split(",")[0].strip()
    words = [w for w in first.split() if w]
    # The clause must END in a sex word to count. That is the whole convention —
    # "Togruta female", "Kel Dor male", "Human female" — and requiring it is what stops
    # this guessing: an appearance opening "red cloak, hooded" or "brown hair, tall"
    # otherwise yields "red cloak" as a species and puts it in the prompt as one.
    if not words or words[-1].lower() not in ("male", "female", "man", "woman"):
        return ""
    label = " ".join(words[:-1]).strip(" .-")
    if not label or label.lower().startswith("human"):
        return ""
    return label if len(label.split()) <= 3 else ""


# Markings a reader identifies somebody by, which a model demonstrably does not read
# off a reference picture. Deliberately a short, concrete list: these are discrete
# FACTS about a face, not descriptions OF a face, and the difference is the whole
# reason it is safe to put them back in the prompt.
_SIGNATURE_MARKERS = (
    "scar", "tattoo", "birthmark", "brand", "burn",
    "prosthetic", "cybernetic", "implant", "eyepatch", "patch over",
    "buzz cut", "shaved", "bald", "braid", "topknot", "dreadlock",
    "missing", "blind", "horn", "tusk", "cravat", "monocle", "spectacles",
)

# How many of them reach the prompt. Two, because the point is a silhouette cue, not a
# second appearance paragraph — and the paragraph is exactly what a reference render
# must not be given back.
_SIGNATURE_LIMIT = 2


def signature_marks(spec):
    """One or two discrete identifying markings from a locked appearance.

    THIS DELIBERATELY BENDS "where a reference exists, the words stop describing the
    face", and the bend is narrow. That rule is right about descriptions: prose and
    pictures disagree about a jaw, and a model handed both averages them into a
    stranger. It is wrong about a discrete marking, which prose states exactly and
    which the model has repeatedly failed to take from the picture.

    Jaric Kaedan is the case. His sheet shows a tight dark buzz cut and a pale vertical
    scar through the left eyebrow — "the first thing anyone notices about his face" —
    and across chapters 6, 7 and 8 he was rendered with soft swept hair and no scar, at
    every rung including the one with every reference attached. Three attempts, three
    rejections, one slot lost to an empty room.

    A scar is not a likeness. Two of them at most, so this stays a silhouette cue."""
    text = str((spec or {}).get("appearance") or "")
    out = []
    # Em-dashes separate clauses here as often as commas do — the locked appearances
    # are written with them — and a clause that runs past ~110 characters has stopped
    # being a marking and started being a description again.
    for clause in re.split(r"[;,.—–]", text):
        c = " ".join(clause.split()).strip(" -")
        # Clauses inherit the conjunction that joined them ("and very short dark hair"),
        # which reads as a fragment in a list of facts.
        for lead in ("and ", "with ", "plus ", "but "):
            if c.lower().startswith(lead):
                c = c[len(lead):]
        c = c[:1].upper() + c[1:] if c else c
        if not c or len(c) > 110:
            continue
        if any(m in c.lower() for m in _SIGNATURE_MARKERS):
            out.append(c.rstrip("."))
        if len(out) >= _SIGNATURE_LIMIT:
            break
    return out


_SEX_WORDS = {"male": "man", "man": "man", "female": "woman", "woman": "woman"}


def sex_of(spec):
    """"man" / "woman" from a locked appearance, or "" when it does not say.

    Same convention the species reader uses — appearances open "Togruta female,
    fifty-five" — and the same justification, arrived at the same way. A sex is a
    category. Prose states it in one word. The model does not reliably take it from a
    picture, and when the prompt omits it the model fills the blank from whatever it
    finds likeliest.

    Alyn Tenar is the case, and she is the protagonist. Her appearance opens "Human
    female, nineteen", so the species reader strips "female" to isolate "Human" and
    then discards the whole thing as unremarkable — leaving her sex nowhere in the
    prompt. She was rendered three times as "a pale, flat-chested masculine build with
    a squared jaw" that "a reader would take for a boy", in scenes where her own
    reference sheet was attached."""
    first = str((spec or {}).get("appearance") or "").split(",")[0].strip()
    words = [w.lower().strip(" .-") for w in first.split() if w]
    for w in reversed(words):
        if w in _SEX_WORDS:
            return _SEX_WORDS[w]
    return ""


def _costume_line(name, spec, chapter_num=None):
    """Name and this chapter's costume, and nothing else.

    What goes in a prompt that already carries the person's real picture. The face is
    the reference's job; the wardrobe is the only thing a photograph of a character in
    one outfit cannot tell a model about a scene set in another."""
    costume = costume_for_chapter(spec or {}, chapter_num).rstrip(".")
    if costume and ":" in costume[:24]:
        costume = costume.split(":", 1)[-1].strip()
    age = str((spec or {}).get("age") or "").strip()
    # Age survives the trim even though the reference carries a face, because it is the
    # one identity fact a reference can be actively wrong about: the source art is
    # drawn from a whole series and this book starts after its epilogue.
    #
    # SPECIES SURVIVES IT TOO, for a different and more embarrassing reason: the model
    # does not reliably read it off the pictures, and its default is human. Two
    # non-human principals were drawn as humans within five minutes of each other —
    # Bela Kiwiiks, a Togruta with montrals and head-tails, rendered in a cloth
    # head-wrap; Tol Braga, a Kel Dor, rendered as an elderly human in goggles — both
    # with their reference sheet and source art attached.
    #
    # "Where a reference exists the words stop describing the face" is right about a
    # face. A species is not a face; it is a category, prose states it exactly, and
    # leaving it out lets the model fall back to the commonest option in its training.
    species = species_of(spec)
    # Species first when there is one — "Togruta woman" reads as a description of a
    # person, where "woman, Togruta" reads as a form being filled in.
    who_is = " ".join(b for b in (species, sex_of(spec)) if b)
    bits = [b for b in (who_is, age) if b]
    who = f"{name} ({', '.join(bits)})" if bits else name
    line = f"{who}: {costume}." if costume else f"{who}: as in the reference."
    marks = signature_marks(spec)
    if marks:
        line += f" Always: {'; '.join(marks)}."
    return line


def identity_block(cast_specs, chapter_num=None):
    """The locked designs of everyone in frame — the vision critic's ground truth."""
    return "\n".join(f"  {_character_line(n, s, chapter_num)}"
                     for n, s in cast_specs)


def _location_line(spec):
    """One place's locked description, for the prompt."""
    text = (spec or {}).get("description", "").strip().rstrip(".")
    return text + "." if text else ""


def build_scene_prompt(scene_desc, cast_specs, orientation="portrait", style=None,
                       simplify=0, location=None, chapter_num=None, anchored=False):
    """The prompt for one scene, written the way an image model reads best.

    Ordered subject-first: what is happening, then who these people are, then how it
    is drawn, then what must not appear. The previous version led with a paragraph of
    style, buried the action in the middle, and appended hex palettes — which is the
    order a *specification* is written in, not the order a picture is described in.

    `anchored` says reference pictures are attached to this request, which is true of
    every scene render below the empty-room rungs. When they are, **the appearance
    paragraph is dropped and only the costume survives.** Prose and pictures always
    disagree — there is no wording for a particular jaw — and a model given both
    averages them, so a paragraph of description sitting on top of a reference photo
    does not reinforce the face, it erodes it. That is the project's own founding
    argument for fetching real art, applied at the point where it was being contradicted
    six times a chapter. What the pictures cannot carry is which outfit this chapter
    wants, so that is what the text keeps.

    `simplify` is the retry ladder, and it is what lets this project refuse to skip a
    picture. A composition that has already been rejected is not improved by asking
    for it again in the same words; it is improved by asking for less. Level 1 drops
    the staging clause down to its subject and keeps the cast; level 2 keeps only the
    first character and the action.

    **Level 3 takes the people out entirely**, and that rung is the reason the loop
    terminates. Every failure this pipeline has actually seen at the bottom of the
    ladder is an identity failure or a crowd failure — the wrong face, two characters
    merged, a hat belonging to somebody else — and a picture of the room they are in
    has neither. It is a real illustration of a real place in the book, drawn from the
    locked location description, and it is unconditionally better than a hole. Level 4
    is the same thing stripped to a single clause, for a slot the vendor is refusing
    for reasons nobody can see.

    A pure string builder — no model, no I/O — so the exact prompt is deterministic,
    testable, and reviewable in the prompt pack."""
    frame = ("Vertical portrait composition for a book page"
             if orientation == "portrait" else
             "Wide horizontal composition, cinematic")
    cast = list(cast_specs)
    scene = " ".join(scene_desc.split()).strip().rstrip(".")

    if simplify >= 3:
        # Dropping the cast list is not enough on its own. The staging line is a
        # sentence about people doing things — "Pacifica presses a pricing gun down
        # while Mabel leans on the counter" — and a model handed that plus an empty
        # `characters` list draws the people anyway, which puts the identity failure
        # straight back into the picture this rung exists to get away from. So the
        # instruction has to countermand the description explicitly, and the
        # description is cut to a clause at the bottom rung.
        cast = []
        setting = (scene.split(",")[0].strip() or scene) if simplify >= 4 else scene
        scene = ("An establishing view of an EMPTY room or place, with nobody in it. "
                 "The place to draw is the setting of this moment: "
                 f"{setting}. Draw only the place itself — the architecture, the "
                 "light, the furniture and the objects. Any people this describes are "
                 "context for what the room looks like and must NOT appear in the "
                 "picture")
    elif simplify >= 2:
        cast = cast[:1]
        who = cast[0][0] if cast else "the character"
        scene = f"{who}, a single clear portrait, in the setting of: {scene}"
    elif simplify == 1:
        cast = cast[:2]
        # Keep the first clause of the staging — the subject and its action — and drop
        # the trailing detail, which is where the impossible instructions live.
        scene = scene.split(",")[0].strip() or scene

    lines = [f"{scene}."]
    place = _location_line(location)
    # The setting gets the same treatment as a face, and for the same reason. A
    # recurring location an image model is told nothing about is reinvented every
    # time, so the book's most familiar rooms come out generic — which is exactly
    # what "the Mystery Shack is missing details" means. Level 2 drops it to make room
    # for the one character it keeps; levels 3 and 4 bring it back because by then the
    # setting is the entire subject of the picture.
    if place and (simplify < 2 or simplify >= 3):
        lines += ["", f"The setting: {place}"]
    if cast:
        lines.append("")
        if anchored:
            non_human = sorted({species_of(s2) for _n, s2 in cast if species_of(s2)})
            lines.append("The people in this picture are the ones in the attached "
                         "reference pictures. Draw those faces. What each is wearing "
                         "in this scene:")
            if non_human:
                lines.append("Species is NOT optional and NOT human by default: "
                             + ", ".join(non_human)
                             + " must be drawn as that species, with the anatomy the "
                               "reference pictures show.")
            lines += [f"- {_costume_line(n, s, chapter_num)}" for n, s in cast]
        else:
            lines.append("The characters, drawn exactly as described and instantly "
                         "recognisable as themselves:")
            lines += [f"- {_character_line(n, s, chapter_num)}" for n, s in cast]
    lines += [
        "",
        f"{frame}. {style_block(style)}",
        "",
        "Do not include: any text, lettering, speech bubbles, captions, signatures, "
        "watermarks, panel borders, or "
        + ("any people or figures at all." if not cast
           else "extra people beyond those named above."),
    ]
    return "\n".join(lines)


# --- Reference sheets (stage 3) ---------------------------------------------

def generate_reference_sheet(series_rec, book_num, character, log_fn=None,
                             style=None):
    """Render and vision-check one character's locked reference sheet.

    Returns the accepted path, or None when this visit's renders are spent — in which
    case the sheet is PARKED, not abandoned, and the next visit resumes one rung
    further down the layout ladder. Propagates QuotaExceeded so the engine can defer."""
    sid = series_rec["series_id"]
    dest = paths.sheet_path(sid, book_num, character["name"])
    if dest.exists():
        return dest                              # content-addressed: already locked
    if not due(dest):
        return None                              # parked; its backoff has not elapsed

    # The sheet is drawn FROM the show's own art rather than from a paragraph describing
    # it, which is the difference between "a girl with brown hair" and this specific
    # girl. The prose description stays in the prompt to say what the sheet must show;
    # the pictures say who it is.
    #
    # Fetched HERE, at the point of use, rather than swept once over the bible. The
    # cast of a crossover grows as chapters are written, so a one-pass sweep is correct
    # exactly once and then silently strands everybody who joins later — which is how a
    # pig came to be drawn from the words "a pink pig, originally billed at fifteen
    # pounds", along with twenty-two other members of this book's cast.
    source_art = refart.ensure(
        series_rec, book_num, character["name"],
        origin=character.get("origin"),
        log_fn=log_fn)[:config.REF_IMAGES_PER_RENDER]
    attempts = max(1, config.IMAGE_MAX_REGENERATIONS)
    prior = attempts_so_far(dest)
    last, staged = "", storage.staging_dir_for(dest.parent) / dest.name
    # The rung the next attempt asks at. Resumes where the last visit left it —
    # restarting at zero is how a retry loop asks forever for a layout it has already
    # been refused — but a refusal does not advance it, because a refusal is not a
    # verdict on the layout.
    rung = prior
    for attempt in range(1, attempts + 1):
        spec = _sheet_prompt(character, style, simplify=rung,
                             from_source_art=bool(source_art))
        try:
            billed_render(spec, staged, f"sheet:{character['name']}:{rung + 1}", sid,
                          references=source_art or None, log_fn=log_fn,
                          aspect=config.IMAGE_ASPECT_PORTRAIT)
            # Same rule as scene rendering: the judge sees the source art the sheet was
            # drawn from. A sheet is the anchor every later picture is measured against,
            # so it is the single worst place in the pipeline to be checking a drawing
            # against a paragraph.
            verdict = vision_verdict(staged, character.get("appearance", ""),
                                     references=source_art or (), log_fn=log_fn)
        except (QuotaExceeded, NotSignedIn):
            # Neither is a defect in THIS prompt, so neither may consume a rung of the
            # ladder. A quota clears on its own and a signed-out profile needs a
            # human; both are waits, and the engine above knows how to wait.
            raise                                # defer: never a failure
        except Refused as exc:
            last = str(exc)
            if log_fn:
                log_fn(f"sheet {character['name']} refused at simplify={rung}; asking "
                       f"again for the same layout rather than a plainer one")
            continue
        except RuntimeError as exc:
            last = str(exc)
            if log_fn:
                log_fn(f"sheet {character['name']} attempt {attempt} error: {last}")
            rung += 1
            continue
        if verdict.get("passed"):
            storage.atomic_place(staged, dest)
            clear_retry(dest)
            mark_sheet_sources(dest, len(source_art))
            return dest
        last = "; ".join(verdict.get("issues", []))
        if log_fn:
            log_fn(f"sheet {character['name']} rejected (attempt {attempt}, "
                   f"simplify={rung}): {last}")
        rung += 1

    # A sheet the critic would not pass is still worth having, and by a wide margin.
    # Without one, every scene that character appears in draws them from prose alone —
    # which is the condition that produced a diner scene with two identical Luzes. A
    # caption in the corner of a reference is a far smaller problem than no reference.
    if staged.exists():
        storage.atomic_place(staged, dest)
        clear_retry(dest)
        mark_sheet_sources(dest, len(source_art))
        mark_kept_with_note(dest, f"kept despite: {last}")
        if log_fn:
            log_fn(f"sheet {character['name']!r} KEPT after {prior + attempts} tries — "
                   f"an imperfect anchor beats none: {last}")
        return dest

    wait = defer(dest, last, rung)
    if log_fn:
        log_fn(f"sheet {character['name']!r} PARKED (nothing rendered); retrying in "
               f"{wait}s at simplify={rung}: {last}")
    return None


# --- The scene queue (stage 6) ----------------------------------------------

def enqueue_chapter(series_rec, book_num, chapter_num, scenes, style=None):
    """Append one queue entry per scene illustration for an accepted chapter.

    Each entry carries its fully-built, consistency-locked prompt with character
    identities already resolved from the series bible, so the render and the
    human-readable prompt pack are guaranteed to use the same text."""
    sid = series_rec["series_id"]
    bible = storage.load_json(paths.series_bible_path(sid), {})
    characters = bible.get("characters", {})
    locations = bible.get("locations", {})

    queue = paths.img_queue()
    queue.parent.mkdir(parents=True, exist_ok=True)
    with queue.open("a", encoding="utf-8") as fh:
        for k, scene in enumerate(scenes, 1):
            # The slot number IS the scene segment number. That identification is what
            # lets the binder place a picture at the end of the stretch of text it
            # belongs to without carrying a second index anywhere: image 3 of a chapter
            # is the picture of scene 3.
            k = int(scene.get("segment") or k)
            names = scene.get("characters", [])
            orientation = scene.get("orientation", "portrait")
            entry = {
                "series_id": sid,
                "book_num": book_num,
                "chapter_num": chapter_num,
                "k": k,
                "segment": k,
                "scene": scene.get("description", ""),
                "characters": names,
                "orientation": orientation,
                # `anchored`, because a scene render always attaches the cast's
                # reference pictures. The stored prompt has to be built the same way
                # the render path rebuilds it, or the two disagree about whether a
                # face is described in words.
                "prompt": build_scene_prompt(
                    scene.get("description", ""),
                    [(n, characters.get(n, {})) for n in names],
                    orientation=orientation, style=style,
                    location=locations.get(scene.get("location", "")),
                    chapter_num=chapter_num, anchored=True),
                # The locked designs of everyone in frame, stored with the entry so a
                # retry can rebuild a simpler prompt and so the vision critic can be
                # given identity ground truth rather than the staging line. Resolved
                # AS OF THIS CHAPTER, so a costume a character does not have yet is not
                # something the critic rejects the picture for missing.
                "identity": identity_block(
                    [(n, characters.get(n, {})) for n in names], chapter_num),
                "location": scene.get("location", ""),
                "style": style_block(style),
                "universes": series_rec.get("universes", []),
            }
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def queued_chapters(series_id, book_num):
    """Chapter numbers this book has any queue entry for, resolved or not.

    Distinct from `pending_scene_entries` and the distinction is load-bearing: pending
    means "still to render", and a book whose queue was never written has none of those
    either. Asking "has this book been enqueued at all" needs a question that a fully
    rendered book and a never-enqueued one answer differently."""
    numbers = set()
    for entry in _all_entries():
        if entry.get("series_id") == series_id and entry.get("book_num") == book_num:
            numbers.add(entry.get("chapter_num"))
    return numbers


def queued_segments(series_id, book_num, chapter_num):
    """Which of a chapter's scene segments already have a queue entry.

    The unit of "already done" for art direction is the SEGMENT, not the chapter, and
    conflating the two is what left the live book's first eight chapters holding two
    pictures each against five and six settings. They were queued while the ceiling was
    2; the ceiling was then raised to 6; and every top-up was refused because the
    chapter appeared in the queue at all. `k` is the segment number, so asking the
    question at the resolution the answer lives at makes the shortfall visible and
    fillable without re-paying for the segments already directed."""
    return {entry.get("k") for entry in _all_entries()
            if entry.get("series_id") == series_id
            and entry.get("book_num") == book_num
            and entry.get("chapter_num") == chapter_num}


def scene_path(entry):
    """Where one queue entry's picture lives."""
    return paths.scene_image_path(entry["series_id"], entry["book_num"],
                                  entry["chapter_num"], entry["k"])


def redraw_scenes_with(series_id, book_num, name, log_fn=None):
    """Discard the rendered scenes anchored to one character, so they draw again.

    Deleting the picture is the whole mechanism: the queue entry is untouched and the
    slot goes back to pending, so it re-renders through the ordinary path with whatever
    anchors now exist. Nothing else has to know this happened.

    Only pictures containing THIS character, so a book's good art is not thrown away to
    fix one face."""
    dropped = 0
    for entry in _all_entries():
        if (entry.get("series_id") != series_id
                or entry.get("book_num") != book_num
                or name not in (entry.get("characters") or [])):
            continue
        dest = scene_path(entry)
        if not dest.exists():
            continue
        dest.unlink()
        dest.with_name(dest.name + ".note").unlink(missing_ok=True)
        clear_retry(dest)
        dropped += 1
    if dropped and log_fn:
        log_fn(f"{dropped} rendered scene(s) showing {name} discarded; they redraw "
               f"against the corrected sheet")
    return dropped


def relock_blind_sheet(series_rec, book_num, log_fn=None):
    """Re-lock ONE sheet that was drawn from prose when the show's own art was there.

    The repair half of the per-character fetch. A sheet drawn blind is not merely
    lower-quality — it is the reference image handed to every render its character
    appears in, so one bad anchor is a whole book of pictures that look almost right
    and read as machine-made. Redrawing the sheet without redrawing what it anchored
    would leave the book exactly as wrong.

    Strictly one-way and self-limiting: a sheet is only discarded once art is actually
    in hand, the new sheet records how much it used, and a sheet with a recorded count
    is never examined again. A character the wikis genuinely do not have keeps the
    sheet it has, because prose is the best anchor available for them and an unanchored
    redraw would be worse than what is already there.

    Returns the character's name if it did work."""
    sid = series_rec["series_id"]
    bible = storage.load_json(paths.series_bible_path(sid), {})
    for name, spec in sorted((bible.get("characters") or {}).items()):
        sheet = paths.sheet_path(sid, book_num, name)
        if not sheet.exists():
            continue                     # not locked yet; it will fetch on its own
        if sheet_source_count(sheet) >= 0:
            continue                     # provenance recorded: already reasoned about
        if (spec.get("origin") or "") == "original":
            mark_sheet_sources(sheet, 0)         # nothing to find; stop asking
            continue

        # ART ALREADY ON DISK MEANS THE SHEET WAS DRAWN FROM IT, and this test is what
        # keeps a repair from becoming a stampede. A sheet is only ever drawn after
        # whatever art is present has been read, so a character who already has
        # pictures has a sheet that used them — nothing to fix, and re-locking anyway
        # would discard two dozen good sheets and every picture they anchor to
        # reproduce them. Only art that was NOT there when the sheet was drawn implies
        # a blind sheet, and the only way to know that is to look before fetching.
        already = refart.for_character(sid, book_num, name)
        if already:
            mark_sheet_sources(sheet, len(already))
            continue

        art = refart.ensure(series_rec, book_num, name, origin=spec.get("origin"),
                            log_fn=log_fn)
        if not art:
            # Only settle this when the lookup actually ran and came back empty. A
            # failed fetch during a network blip must leave the question open, or one
            # bad minute would freeze a blind sheet for the life of the book.
            if refart.confirmed_missing(sid, book_num, name):
                mark_sheet_sources(sheet, 0)
            continue
        if log_fn:
            log_fn(f"sheet for {name} was drawn from the written description alone, "
                   f"and {len(art)} picture(s) of them exist — relocking it from the "
                   f"show's own art")
        sheet.unlink()
        sheet.with_name(sheet.name + ".note").unlink(missing_ok=True)
        clear_retry(sheet)
        (bible.get("characters") or {}).get(name, {})["ref_sheet_locked"] = False
        storage.save_json(bible, paths.series_bible_path(sid))
        redraw_scenes_with(sid, book_num, name, log_fn=log_fn)
        return name
    return None


def queued_books():
    """Every (series_id, book_num) with art in the queue, in first-seen order."""
    seen = []
    for entry in _all_entries():
        pair = (entry.get("series_id"), entry.get("book_num"))
        if pair not in seen and all(part is not None for part in pair):
            seen.append(pair)
    return seen


def queued_counts(series_id, book_num):
    """How many entries each of this book's chapters has. One queue read."""
    counts = {}
    for entry in _all_entries():
        if entry.get("series_id") == series_id and entry.get("book_num") == book_num:
            counts[entry.get("chapter_num")] = \
                counts.get(entry.get("chapter_num"), 0) + 1
    return counts


def _all_entries():
    queue = paths.img_queue()
    if not queue.exists():
        return []
    out = []
    for line in queue.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def pending_scene_entries():
    """Queue entries with no picture yet. Re-reading the queue rather than tracking
    cursors is what makes the drain idempotent, so the engine and the illustrator
    daemon can both work it without coordinating.

    This is the list the book waits on — a book is illustrated when it is empty — so
    it counts parked slots too. `due_scene_entries` is the list a *worker* should
    take from."""
    return [entry for entry in _all_entries() if not is_resolved(scene_path(entry))]


def due_scene_entries(now=None):
    """Pending entries whose backoff has elapsed — what a drainer should work on.

    Separate from `pending_scene_entries` because the two questions have different
    answers and both are needed: "is this book finished with pictures" counts a parked
    slot, "what should this cycle render" does not. Handing a worker a parked slot is
    how a backoff becomes a hot loop."""
    return [entry for entry in pending_scene_entries()
            if due(scene_path(entry), now)]


def write_prompt_pack(series_rec, book_num):
    """Write the human-readable prompt pack for a book: every image's target filename
    and its exact prompt, so the prompts are a first-class reviewable artifact (and
    usable by hand if a render has to be done manually)."""
    sid = series_rec["series_id"]
    entries = [e for e in pending_scene_entries()
               if e["series_id"] == sid and e["book_num"] == book_num]
    lines = [f"# Image prompts — {sid} book {book_num}", "",
             "Each block is one illustration: its target filename and the exact "
             "prompt.", ""]
    for entry in sorted(entries, key=lambda e: (e["chapter_num"], e["k"])):
        dest = paths.scene_image_path(sid, book_num, entry["chapter_num"], entry["k"])
        lines += [f"## Chapter {entry['chapter_num']} — image {entry['k']}",
                  f"**Save as:** `{dest}`", "",
                  "```", entry.get("prompt", "").strip(), "```", ""]
    pack = paths.prompt_pack_path(sid, book_num)
    storage.atomic_write_text("\n".join(lines), pack)
    return pack


def render_scene(entry, log_fn=None):
    """Render and vision-check one queued scene, reusing the relevant locked sheets.

    Returns the accepted path, or None when this visit's renders are spent or the
    scene's cast has no locked sheet yet. Both are "not yet", never "never": the slot
    is parked with the rung it reached and comes back plainer. Propagates
    QuotaExceeded to defer."""
    sid, book_num = entry["series_id"], entry["book_num"]
    dest = paths.scene_image_path(sid, book_num, entry["chapter_num"], entry["k"])
    if dest.exists():
        return dest
    if not due(dest):
        return None                              # parked; its backoff has not elapsed

    # Resolve names against the bible HERE as well as at enqueue time. A queue entry
    # is durable: one written before the resolver existed still carries whatever the
    # art director called somebody, and "Ford Pines" against a bible filed under
    # "Stanford Pines" waits on a sheet that can never exist. Doing it at the point of
    # use means old entries heal themselves instead of needing the queue rewritten.
    bible = storage.load_json(paths.series_bible_path(sid), {})
    known = list((bible.get("characters") or {}).keys())
    names = []
    for raw in entry.get("characters", []):
        canonical = resolve_cast_name(known, raw) if known else raw
        if canonical is None:
            if log_fn:
                log_fn(f"scene {dest.name}: dropping {raw!r} — not in the bible, so "
                       f"nothing could ever anchor them")
            continue
        names.append(canonical)
    names = list(dict.fromkeys(names))

    # THE SHEETS COME FIRST, AND THIS IS A HARD GATE.
    #
    # Reference sheets are the entire mechanism by which a recurring character stays
    # the same person across a book — the answer to the third of this project's three
    # hard problems. A scene rendered before they exist has nothing anchoring anyone,
    # and the image model does the only thing it can: it invents a face from whatever
    # description is nearest. The live book has the receipt. Chapter 1's diner scene
    # was Luz and her mother; it rendered with no sheets and Camila came out as a
    # second, identical Luz in a matching hoodie.
    #
    # The hole was structural rather than accidental. Sheets are generated by
    # `engine.illustrating.advance` — the scribe's job — while the illustrator daemon
    # drains the scene queue independently and never asked whether they existed. Two
    # processes, one ordering assumption, and nothing enforcing it. So the check lives
    # HERE, in the one function both drainers call.
    #
    # Deferring, not skipping: a missing sheet is a "not yet", and the slot is
    # rendered as soon as the sheet lands.
    missing = [name for name in names
               if not is_resolved(paths.sheet_path(sid, book_num, name))]
    if missing:
        if log_fn:
            log_fn(f"scene {dest.name} deferred: no locked reference sheet yet for "
                   f"{', '.join(missing)}")
        return None

    # REAL SOURCE ART FIRST, then our generated sheet.
    #
    # Order is deliberate: the show's own picture of a character settles the face, the
    # proportions and the age in a way no prose description reaches — which is the
    # failure that put seventeen-year-old twins on the page as a young adult and a
    # child. The generated sheet still goes in behind it, because that is what carries
    # this book's unified style; the source art carries who the person is.
    #
    # **The foreground gets the full reference set; everyone else gets their sheet.**
    # Fidelity per face falls as the reference count rises — the model has one budget of
    # attention to divide — so a four-character scene sending twelve pictures makes all
    # four faces worse, and the worst-hit are the ordinary-looking humans who need the
    # references most. The art-direction prompt already requires a composition with one
    # or two people in front and the rest staged behind; this is the renderer agreeing
    # with it. The people in front are identified by looking like people, and the ones
    # behind are identified by being where the scene says they are.
    references = _scene_references(sid, book_num, names)
    orientation = entry.get("orientation", "portrait")
    aspect = _aspect_for(orientation)
    # Identity ground truth for the critic. Stored at enqueue time; rebuilt from the
    # bible for an entry written before it was.
    identity = entry.get("identity") or identity_block(
        [(n, _locked(sid, n)) for n in names], entry.get("chapter_num"))

    attempts = max(1, config.IMAGE_MAX_REGENERATIONS)
    prior = attempts_so_far(dest)
    last, wrong_character = "", False
    staged = storage.staging_dir_for(dest.parent) / dest.name
    # The rung the NEXT attempt asks at. Advanced by a rejection — the picture came out
    # and was wrong, so ask for less — but NOT by a refusal, which is a classifier
    # firing rather than a verdict on the composition. See `images.Refused`.
    rung = prior
    for attempt in range(1, attempts + 1):
        # Ask for LESS each time, rather than asking for the same thing again. A
        # composition the model already failed at is not improved by repetition; the
        # thing that has to give is the composition.
        #
        # The rung continues across visits rather than restarting at zero. That is the
        # whole mechanism by which a slot that will not render can be retried forever
        # and still terminate: a loop that re-asked for the original composition every
        # cycle would repeat, not escalate, and "never give up" would mean "never
        # finish". Three rungs down, the request is a picture of the room with nobody
        # in it, which nothing has to identify and nothing can crowd.
        #
        # `rung` is tracked across the loop rather than derived from the attempt
        # number, because not every failed attempt should cost a rung — a refusal
        # holds its place. See `images.Refused`.
        # ALWAYS REBUILT, never taken from the queue entry.
        #
        # The entry carries a fully-built prompt from enqueue time, and using it at
        # rung 0 was a real optimisation — the human-readable pack and the render were
        # guaranteed to be the same text. It is also a snapshot of the series bible as
        # it was that minute, and a queue entry outlives a lot of corrections.
        #
        # Jaric Kaedan is the proof. His locked design was wrong (blonde, unscarred,
        # against a canon character with a dark buzz cut and a scar through the
        # eyebrow); the bible was corrected, his sheet re-locked, species and signature
        # markings added to the prompt builder — and his scenes kept failing
        # identically, because every one of them was still rendering from a prompt
        # built before any of it. A cached prompt cannot be repaired.
        #
        # The pack still shows the stored text, which is what it is for: a record of
        # what was asked at the time.
        prompt = (build_scene_prompt(
                      entry.get("scene", ""),
                      [(n, _locked(sid, n)) for n in names],
                      orientation=orientation, style=entry.get("style"),
                      simplify=rung,
                      location=_locked_place(sid, entry.get("location", "")),
                      chapter_num=entry.get("chapter_num"),
                      anchored=rung < 3))
        # From rung 3 the prompt has taken the people out, so the critic must be told
        # that too. Handing it the locked cast while the prompt asked for an empty room
        # is the generator/judge document mismatch this project has recorded three
        # times: the picture would be rejected for missing the very characters it was
        # told not to draw, and the loop could not converge.
        spec_text = "" if rung >= 3 else identity
        try:
            billed_render(prompt, staged,
                          f"scene:b{book_num}c{entry['chapter_num']}"
                          f"k{entry['k']}:{rung + 1}", sid,
                          references=(references if rung < 3 else None),
                          log_fn=log_fn, aspect=aspect)
            # The critic is handed exactly what the generator was handed. Anything
            # else and the two of them are judging different documents, which is the
            # one failure mode this pipeline reproduces at every layer it has.
            verdict = vision_verdict(staged, spec_text,
                                     references=(references if rung < 3 else ()),
                                     log_fn=log_fn)
        except (QuotaExceeded, NotSignedIn):
            # Neither is a defect in THIS prompt, so neither may consume a rung of the
            # ladder. A quota clears on its own and a signed-out profile needs a
            # human; both are waits, and the engine above knows how to wait.
            raise
        except Refused as exc:
            # A refusal says nothing about the composition, and it is not even stable:
            # the identical prompt is often drawn on a later try. Spend the attempt,
            # keep the rung, and ask for the same picture again.
            last = str(exc)
            if log_fn:
                log_fn(f"scene {dest.name} refused at simplify={rung}; asking again "
                       f"for the same composition rather than a plainer one")
            continue
        except RuntimeError as exc:
            last = str(exc)
            if log_fn:
                log_fn(f"scene {dest.name} attempt {attempt} error: {last}")
            rung += 1
            continue
        if verdict.get("passed"):
            storage.atomic_place(staged, dest)
            clear_retry(dest)
            return dest
        last = "; ".join(verdict.get("issues", []))
        wrong_character = bool(verdict.get("wrong_character"))
        if log_fn:
            log_fn(f"scene {dest.name} rejected (attempt {attempt}, "
                   f"simplify={rung})"
                   + (" [WRONG CHARACTER]" if wrong_character else "") + f": {last}")

        # PROMOTE WHOEVER CAME OUT WRONG, rather than simply asking for less.
        #
        # The ladder's answer to any failure is a plainer composition, and at rung 2
        # that means keeping only the FIRST character — whoever the art director
        # happened to list first. When the failure is "this specific person is not
        # himself", that is the wrong lever: it drops the person who needs the
        # reference pictures most and keeps someone who was already fine.
        #
        # Measured on Jaric Kaedan, who failed identity across chapters 6, 7 and 8 —
        # each time a non-lead, each time losing his sheet to the cast truncation, each
        # time drifting further until the slot landed on an empty room. Moving him to
        # the front gives him the full reference set and lets him survive the next
        # rung's trim.
        if wrong_character:
            culprits = flagged_wrong(verdict, names)
            if culprits:
                names = culprits + [n for n in names if n not in culprits]
                references = _scene_references(sid, book_num, names)
                if log_fn:
                    log_fn(f"scene {dest.name}: {', '.join(culprits)} came out wrong, "
                           f"so the next attempt puts them first and gives them the "
                           f"reference pictures")
        rung += 1

    # Out of attempts for this visit with a rendered image in hand. Keep it — UNLESS
    # the thing the critic cannot get past is that this is not the right person.
    #
    # "A slightly-off illustration beats a hole" is true and I over-applied it. It
    # holds for a shade of hair or the wrong shoes; it does not hold for a picture
    # that shows somebody else. Chapter 1 shipped a diner scene where Luz's mother was
    # drawn as a second Luz, after the critic said in three separate verdicts that a
    # reader could not tell who she was. A wrong picture does not merely fail to
    # inform the reader, it actively misinforms them about a character's face, in a
    # book whose whole visual claim is that faces stay put.
    if staged.exists() and not wrong_character:
        storage.atomic_place(staged, dest)
        clear_retry(dest)
        journalled = f"kept despite: {last}"
        mark_kept_with_note(dest, journalled)
        if log_fn:
            log_fn(f"scene {dest.name} KEPT after {prior + attempts} tries — "
                   f"{journalled}")
        return dest

    # Neither kept nor abandoned: PARKED. The wrong face is the case this exists for —
    # the picture must not ship, and the slot must not be given up on, so it waits and
    # comes back a rung plainer until it is a picture the critic has nothing to say
    # about. A hole in the book is not one of the outcomes on offer.
    wait = defer(dest, last, rung)
    if log_fn:
        why = ("shows the wrong character" if wrong_character else "nothing rendered")
        log_fn(f"scene {dest.name} PARKED ({why}); retrying in {wait}s at "
               f"simplify={rung}: {last}")
    return None


def render_cover(series_rec, book_num, title, log_fn=None, style=None):
    """The cover. Decorative, so no vision critique — a render that produces bytes is
    the cover. Returns the path, or None having parked the slot for a later retry.
    Propagates QuotaExceeded to defer."""
    dest = paths.cover_path(series_rec["series_id"], book_num)
    if dest.exists():
        return dest
    if not due(dest):
        return None

    prompt = (f"Book cover illustration for '{title}', an illustrated novel. "
              f"{style_block(style)} Portrait orientation, dramatic and evocative, "
              f"leaving clear space at the top for a title. No text, no lettering.")
    attempts = max(1, config.IMAGE_MAX_REGENERATIONS)
    prior = attempts_so_far(dest)
    last = ""
    for attempt in range(1, attempts + 1):
        staged = storage.staging_dir_for(dest.parent) / dest.name
        try:
            billed_render(prompt, staged, f"cover:{prior + attempt}",
                          series_rec["series_id"], references=None, log_fn=log_fn,
                          aspect=config.IMAGE_ASPECT_PORTRAIT)
        except (QuotaExceeded, NotSignedIn):
            # Neither is a defect in THIS prompt, so neither may consume a rung of the
            # ladder. A quota clears on its own and a signed-out profile needs a
            # human; both are waits, and the engine above knows how to wait.
            raise
        except RuntimeError as exc:
            last = str(exc)
            continue
        storage.atomic_place(staged, dest)
        clear_retry(dest)
        return dest

    wait = defer(dest, last, prior + attempts)
    if log_fn:
        log_fn(f"cover PARKED after {prior + attempts} tries; retrying in "
               f"{wait}s: {last}")
    return None
