"""Canon and series-bible schemas, plus the merge gatekeeper.

The layers themselves are described in `fanfic/memory/__init__.py`. This module is
their shape on disk and the rules that shape may never be argued out of.

The load-bearing function is `merge_bible_update`: when a chapter is accepted,
the writer's proposed bible updates are model output and therefore untrusted. This
function enforces the *structural* invariants deterministically before a single
fact is allowed to persist — new facts may not collide with a canon or prior-bible
id, a payoff may not be recorded without a prior setup, a thread may not be paid
twice, and a locked character's appearance may not be mutated. Semantic
contradiction ("she can't be in two places at once") is the continuity guardian's
job (model judgment); this module guarantees the ledger itself can never be
corrupted into an inconsistent shape, whatever the model proposes.

All records are plain dicts (JSON on disk), matching the sibling repos' no-database
choice. Every mutating function returns a NEW dict and never edits its input in
place, so a rejected merge leaves the committed bible untouched.
"""

import copy
import re


# --- What a costume entry may say --------------------------------------------

# Each of these introduces a point in time from which something is in force. A dated
# costume entry is allowed exactly one of them, because it means "this is what they
# wear from chapter N" — one state, one start.
_TRANSITION = re.compile(r"\bonwards?\b|\bafter (?:the|his|her|their|its)\b", re.I)


# --- What a locked appearance may not say -------------------------------------

# Objects that can be ADDED to a picture. Deliberately not "shadow", "sclera" or
# "whites": those are lighting and anatomy, properties of a thing already in frame
# rather than props a model can reach for, and "casting no shadow" is the entire point
# of drawing a Force ghost.
_ADDABLE = (r"mask|armour|armor|helmet|hood|robes?|blade|insignia|lightsaber|saber|"
            r"sword|bolt|weapon|cannon|rifle|bangs|fringe|beard|blonde|ornate|"
            r"flashes|cloak")

# "not" is excluded on purpose. It is overwhelmingly a verb negation — "a runner's
# build, not a soldier's", "his face does not move much, so the armour reads as the
# expression" — and including it made the check fire on prose that forbids nothing.
# The noun must also follow within two words, which is what keeps that second example
# from matching across the comma.
_FORBIDS = re.compile(
    rf"\b(?:no|never|without)\b\s+(?:\w+\s+){{0,2}}(?:{_ADDABLE})\b", re.I)


def forbids_a_visible_thing(text):
    """Phrases that tell a renderer to leave an object OUT. Returns what it found.

    An image model has no reliable negation: "no side bangs" puts *side bangs* in the
    prompt, and the noun is what gets drawn. On the first real book this was the single
    largest cause of identity failure — **ten of twenty-one `[WRONG CHARACTER]`
    verdicts were Satele Shan's side bangs**, forbidden in her locked appearance in
    those words. Tarnis, described as having "no lightsaber anywhere on him", was drawn
    holding one.

    It damages the JUDGE as well, which is worse and less obvious. Jaric Kaedan's
    appearance read "dark throughout this entire book, never blonde and never grey";
    the first verdict passed on him reported that "the design states blonde throughout
    this entire book" and rejected the render for not being blonde.

    Checked rather than left to review because the same negation is written into three
    separate places — the appearance, a plain wardrobe string, and a dated costume
    entry — and a person sweeping them by hand misses one. Three consecutive sweeps of
    the SWTOR bible each fixed one surface and left another."""
    return [" ".join(m.group(0).split()) for m in _FORBIDS.finditer(str(text or ""))]


def describes_multiple_transitions(text):
    """True when a costume names more than one point at which the look changes.

    A costume attached to a progression is stamped by the outliner as the wardrobe in
    force **from a single chapter** — `illustration.costume_for_chapter` picks the
    latest dated entry that has started and returns it whole. So a costume that
    describes a whole arc cannot be satisfied by that machinery: whichever chapter it
    is stamped at, every later chapter is handed a description of several outfits at
    once and left to choose.

    Alyn Tenar is the case, and she is the protagonist, in roughly half the book. Her
    p.1 read "From the Forge onward a blue-bladed lightsaber ...; from Carrick Station
    onward the sandcloth Padawan tunic is replaced by ... Guardian robes; from Orgus
    Din's funeral onward a band of burnt orange cloth ...". Those three changes land in
    chapters 9, 18 and 17 — not even in that order — and the whole paragraph was
    stamped at chapter 9. Every render from chapter 9 to 42 was then told about robes
    and a forearm wrap she does not own yet, with her reference sheet attached.

    The rule is deliberately narrow: ONE transition marker is the normal, correct shape
    ("From his surrender onward, plain undyed Jedi robes"), so only two or more are
    refused. Measured against the twenty-one progressions of the live SWTOR plan it
    fires on exactly two, p.1 and T7-O1's p.4, and both are genuinely multi-transition;
    the other thirteen costume-bearing progressions score zero or one."""
    return len(_TRANSITION.findall(str(text or ""))) >= 2


# --- Canon -------------------------------------------------------------------

def new_canon(universe):
    return {"universe": universe, "frozen": False, "facts": []}


def validate_canon(canon):
    """Structural check on a canon reference. Returns (ok, errors)."""
    errors = []
    if not canon.get("universe"):
        errors.append("canon: missing universe")
    seen = set()
    for i, fact in enumerate(canon.get("facts", [])):
        where = f"canon fact #{i}"
        fid = fact.get("id")
        if not fid:
            errors.append(f"{where}: missing id")
        elif fid in seen:
            errors.append(f"{where}: duplicate id {fid!r}")
        else:
            seen.add(fid)
        if not fact.get("text"):
            errors.append(f"{where} ({fid}): missing text")
        if not fact.get("category"):
            errors.append(f"{where} ({fid}): missing category")
        if not fact.get("citation"):
            errors.append(f"{where} ({fid}): missing citation (every canon fact "
                          "must be traceable to a source)")
    return (not errors, errors)


def canon_fact_ids(canon):
    return {f["id"] for f in canon.get("facts", []) if f.get("id")}


# --- Series bible ------------------------------------------------------------

def new_series_bible(series_id):
    return {
        "series_id": series_id,
        "characters": {},        # name -> character record
        "relationships": [],     # {a, b, type}
        "foreshadowing": [],     # ledger: {id, description, status, setup_*, payoff_*}
        # The interaction ledger: which specific people this book has promised to put
        # in a room together, and what makes each pairing worth the page. A crossover
        # is *bought* for these scenes — Dipper meeting Entrapta, Catra meeting Eda —
        # and without a ledger they happen by accident or not at all, because a beat
        # sheet written chapter by chapter optimises for plot and a reader came for
        # the collisions. Same shape as `foreshadowing` and tracked the same way:
        # {id, who, promise, when, status}.
        "interactions": [],
        # Locked descriptions of the places the book keeps returning to. The exact
        # counterpart of a character's locked appearance, and it was missing for the
        # same reason `voice` once was: nothing downstream asked for it, so nothing
        # produced it, so every illustration invented its setting from scratch. The
        # Mystery Shack has a totem pole, a fallen S on the roof sign, wood shingles
        # and a wall of bad taxidermy; an image model told only "a cabin in Oregon"
        # draws a cabin in Oregon. {name: {description, appears_in}}
        "locations": {},
        "timeline": [],          # [{index, book, chapter, event}]
        "facts": [],             # invented facts established during writing
    }


def new_character(name, canon_ref="", appearance="", costumes=None,
                  palette=None, ref_sheet_spec="", voice="", origin="", age=""):
    return {
        "name": name,
        "canon_ref": canon_ref,       # citation into canon for this character
        # Which world they come from, or "original" for a character invented for this
        # book. Two things read it, and neither can work without it: the interaction
        # coverage gate counts whether a scene crosses universes, and the reference-art
        # stage uses it to know there is no wiki to look this person up on.
        "origin": origin,
        "appearance": appearance,     # canonical appearance in words
        # How old they are on page one, as a plain number of years. Separate from
        # `appearance` because prose states age comparatively — "older than she was",
        # "not the child who fell in" — and a comparison makes an image model start
        # from the thing compared to and guess how far to travel. It guessed a decade
        # too far for every picture in the first book.
        "age": age,
        # How this person talks: rhythm, vocabulary, verbal tics, what they deflect
        # with, what they never say. The prose counterpart of `appearance`, and it
        # earns its place for the same reason: identity that a model has no memory of
        # has to be written down or it drifts. In a crossover it is load-bearing —
        # four casts from four different writers' rooms will converge into one
        # narrator's voice unless each is pinned, and "everyone sounds the same" is
        # a critique the writer cannot act on without knowing what different is.
        "voice": voice,
        "costumes": costumes or [],   # named costume variants
        "palette": palette or [],     # fixed colour palette
        "ref_sheet_spec": ref_sheet_spec,
        "ref_sheet_locked": False,    # once True, appearance/palette are frozen
    }


def validate_series_bible(bible):
    """Structural invariants of the series bible. Returns (ok, errors)."""
    errors = []
    chars = bible.get("characters", {})
    for name, rec in chars.items():
        if rec.get("name") != name:
            errors.append(f"character {name!r}: name field {rec.get('name')!r} "
                          "does not match its key")
    for rel in bible.get("relationships", []):
        for endpoint in ("a", "b"):
            who = rel.get(endpoint)
            if who not in chars:
                errors.append(f"relationship references unknown character {who!r}")

    fact_ids = set()
    for fact in bible.get("facts", []):
        fid = fact.get("id")
        if not fid:
            errors.append("series fact: missing id")
        elif fid in fact_ids:
            errors.append(f"series fact: duplicate id {fid!r}")
        else:
            fact_ids.add(fid)

    thread_ids = set()
    for thread in bible.get("foreshadowing", []):
        tid = thread.get("id")
        if not tid:
            errors.append("foreshadow thread: missing id")
        elif tid in thread_ids:
            errors.append(f"foreshadow thread: duplicate id {tid!r}")
        else:
            thread_ids.add(tid)
        status = thread.get("status")
        if status not in ("open", "paid"):
            errors.append(f"thread {tid!r}: bad status {status!r}")
        if status == "paid" and not (thread.get("payoff_book")
                                     and thread.get("payoff_chapter")):
            errors.append(f"thread {tid!r}: marked paid without payoff coordinates")
    return (not errors, errors)


def open_threads(bible):
    """Foreshadow threads still awaiting payoff — the 'open promises' ledger."""
    return [t for t in bible.get("foreshadowing", []) if t.get("status") == "open"]


# --- The gatekeeper: merge a proposed update ---------------------------------

def merge_bible_update(bible, canon, update):
    """Validate a model-proposed bible update against canon and the prior bible,
    and, only if every structural invariant holds, return the merged bible.

    Returns (ok, errors, new_bible). On failure new_bible is the ORIGINAL bible,
    unchanged — nothing is committed on a rejected proposal.

    An `update` may carry any of:
      * new_facts      : [{id, text, source}]         invented facts to append
      * new_characters : [character records]          cast introduced this chapter
      * new_threads    : [{id, description, setup_book, setup_chapter}]  setups
      * pay_offs       : [{id, payoff_book, payoff_chapter}]  threads now resolved
      * character_locks: [name, ...]                  ref sheets to freeze
      * timeline_add   : [{index, book, chapter, event}]
    """
    errors = []
    canon_ids = canon_fact_ids(canon)
    existing_fact_ids = {f["id"] for f in bible.get("facts", []) if f.get("id")}
    existing_thread_ids = {t["id"] for t in bible.get("foreshadowing", [])
                           if t.get("id")}
    thread_by_id = {t["id"]: t for t in bible.get("foreshadowing", [])
                    if t.get("id")}

    draft = copy.deepcopy(bible)

    # 1. New facts: an invented fact may never collide with a canon id (canon is
    #    immutable ground truth) nor re-use an existing series-fact id.
    for fact in update.get("new_facts", []):
        fid = fact.get("id")
        if not fid or not fact.get("text"):
            errors.append(f"new fact missing id/text: {fact!r}")
            continue
        if fid in canon_ids:
            errors.append(f"new fact {fid!r} collides with an immutable canon id")
            continue
        if fid in existing_fact_ids:
            errors.append(f"new fact {fid!r} collides with an existing series fact")
            continue
        existing_fact_ids.add(fid)
        draft["facts"].append({
            "id": fid, "text": fact["text"], "source": fact.get("source", ""),
        })

    # 2. New characters: unique names; a character already locked cannot be
    #    reintroduced with a mutated appearance/palette (the locked-sheet invariant
    #    that keeps a character identical across the whole series).
    for rec in update.get("new_characters", []):
        name = rec.get("name")
        if not name:
            errors.append("new character missing name")
            continue
        prior = bible.get("characters", {}).get(name)
        if prior and prior.get("ref_sheet_locked"):
            if (rec.get("appearance", prior["appearance"]) != prior["appearance"]
                    or rec.get("palette", prior["palette"]) != prior["palette"]):
                errors.append(f"character {name!r} is locked; appearance/palette "
                              "cannot be changed")
                continue
        draft["characters"][name] = rec

    # 3. New threads (setups): unique ids, opened only.
    for thread in update.get("new_threads", []):
        tid = thread.get("id")
        if not tid:
            errors.append("new thread missing id")
            continue
        if tid in existing_thread_ids:
            errors.append(f"new thread {tid!r} collides with an existing thread")
            continue
        existing_thread_ids.add(tid)
        draft["foreshadowing"].append({
            "id": tid,
            "description": thread.get("description", ""),
            "status": "open",
            "setup_book": thread.get("setup_book"),
            "setup_chapter": thread.get("setup_chapter"),
            "payoff_book": None,
            "payoff_chapter": None,
        })

    # 4. Payoffs: a payoff must reference an EXISTING open thread (prior setup) and
    #    may not re-pay an already-paid one. This is the foreshadowing->payoff ledger
    #    guarantee: no payoff without a setup, no double payoff.
    draft_threads = {t["id"]: t for t in draft["foreshadowing"]}
    for pay in update.get("pay_offs", []):
        tid = pay.get("id")
        thread = thread_by_id.get(tid)
        if thread is None:
            errors.append(f"payoff for unknown thread {tid!r} (no prior setup)")
            continue
        if thread.get("status") == "paid":
            errors.append(f"thread {tid!r} already paid; cannot pay off twice")
            continue
        if not (pay.get("payoff_book") and pay.get("payoff_chapter")):
            errors.append(f"payoff for {tid!r} missing payoff coordinates")
            continue
        dt = draft_threads[tid]
        dt["status"] = "paid"
        dt["payoff_book"] = pay["payoff_book"]
        dt["payoff_chapter"] = pay["payoff_chapter"]

    # 5. Character locks: freeze the named ref sheets.
    for name in update.get("character_locks", []):
        if name not in draft["characters"]:
            errors.append(f"cannot lock unknown character {name!r}")
            continue
        draft["characters"][name]["ref_sheet_locked"] = True

    # 6. Timeline additions.
    for entry in update.get("timeline_add", []):
        draft["timeline"].append(entry)

    if errors:
        return (False, errors, bible)   # reject: original bible untouched
    return (True, [], draft)
