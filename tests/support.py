"""Shared test scaffolding. Import this FIRST from every test module.

Importing it redirects all runtime state — the journal, canon, bibles, staging,
locks, logs — and the inbox and the "iCloud" Books folder into throwaway temp
directories, before `fanfic.config` is ever imported. Nothing in the suite touches a
real path, so the whole deterministic half runs anywhere, on stdlib only.

That redirect is not a convenience, it is a safety interlock, and it is asserted
rather than assumed. The previous suite redirected `FANFIC_STATE_DIR` but forgot
`FANFIC_INBOX_DIR`, so `config.INBOX_DIR` stayed pointed at the real drop folder —
and a `shutil.rmtree` in one test's cleanup deleted a real parked job prompt out of
`inbox/failed/` (2026-08-04). `_assert_redirected` below makes that class of mistake
impossible instead of merely unlikely.

It also owns the model-seam stubs. Every test that drives the engine uses the same
`stub_model_seams()`, so a stub signature drifting from the real seam breaks loudly
in one place instead of silently in five.
"""

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Must happen before the first `fanfic.config` import.
os.environ.setdefault("FANFIC_STATE_DIR",
                      tempfile.mkdtemp(prefix="fanfic-test-state-"))
os.environ.setdefault("FANFIC_INBOX_DIR",
                      tempfile.mkdtemp(prefix="fanfic-test-inbox-"))
os.environ.setdefault("FANFIC_BOOKS_DIR",
                      tempfile.mkdtemp(prefix="fanfic-test-books-"))

# The suite must not depend on what time of day it runs.
#
# `run_engine` drives REAL cycles, and a real cycle consults the real clock: inside the
# owner's quiet hours the engine correctly refuses to start work, so every end-to-end
# test hangs until its cycle budget runs out and then fails. The suite passed at 03:00
# and failed at 11:00 on the same commit, which sends you hunting through the change you
# just made rather than the clock.
#
# Quiet hours are behaviour worth testing — `test_clock.py` tests them directly, with
# an injected `now` — but they are not behaviour any *other* test wants switched on
# underneath it.
os.environ.setdefault("FANFIC_QUIET_HOURS", "0")

# The fixture book is two chapters and six characters. The interaction coverage gate is
# sized for a 45-chapter crossover with a cast of 52, so its appearance floor is the one
# threshold a fixture this size cannot meet on merit — six appearances out of ten
# interactions is not a thing a two-chapter book can offer.
#
# Lowered rather than switched off, and only this one: the suite still runs the real
# gate, on real fixture data, and every other rule it enforces (no subset twice, sizes
# varied, both ends of the cross-universe arithmetic) holds at fixture scale. The
# threshold itself is covered directly in `test_gates.py`, which is where a number
# belongs.
os.environ.setdefault("FANFIC_PLAN_MIN_APPEARANCES", "3")

# The other threshold a ten-interaction fixture cannot express, and for the same
# reason. The ceiling stops any one register being more than half a *book*; with ten
# entries the smallest step is 10%, so a distribution that clears all three physical
# floors with any margin at all necessarily sits on or over a 50% line. The floors
# themselves are left at their production values and the fixture meets them on merit —
# it is only the ceiling that is loosened, and only because a two-chapter book is not
# the thing it was written to measure.
os.environ.setdefault("FANFIC_META_REGISTER_CEILING", "0.60")

from fanfic import config, paths, states                          # noqa: E402
from fanfic.engine import cycle                                   # noqa: E402
from fanfic.infra import journal, storage                         # noqa: E402
from fanfic.models import images                                  # noqa: E402
from fanfic.stages import (anchoring, bible_update, drafting,      # noqa: E402
                           editing, illustration, metaplan, outlining, planning,
                           refart, research)


def _assert_redirected():
    """Refuse to run at all if any tunable the suite deletes from still points inside
    the repo. Checked at import, so a missing redirect fails collection rather than
    quietly eating the real state tree."""
    for name, directory in (("FANFIC_STATE_DIR", config.STATE_DIR),
                            ("FANFIC_INBOX_DIR", config.INBOX_DIR),
                            ("FANFIC_BOOKS_DIR", config.ICLOUD_BOOKS_DIR)):
        resolved = Path(directory).resolve()
        if resolved == _ROOT or _ROOT in resolved.parents:
            raise RuntimeError(
                f"{name} resolves to {resolved}, inside the repo at {_ROOT}. "
                f"The suite deletes from these directories — refusing to run.")


_assert_redirected()

# A minimal 1x1 PNG, so an epub embeds real image bytes.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080200000090"
    "7753de0000000c4944415408d763f8cfc0f01f0005000155a2b4e40000000049454e44ae426082")

# Prose deliberately inside the readability band AND over the length floor, so all
# three deterministic gates pass on merit rather than by being switched off.
#
# Scene breaks included, because a chapter without them now fails a gate and every
# per-segment mechanism — which moments get drawn, where each picture is placed —
# needs something to be defined over. Three segments, which is what a real chapter of
# this size looks like.
_BLOCK = ("The morning came slowly over the ruined city. Ruby walked along the "
          "broken wall and looked at the grey sky. She was tired, but she would not "
          "stop now. Her friends were waiting for her beyond the river, and the "
          "enemy was close behind. She gripped her weapon and took a steady breath. "
          "There was still a long road ahead of them all. ")
PROSE = "\n\n* * *\n\n".join([_BLOCK * 17] * 3)      # ~3,200 words: over the floor

PROMPT = ("# Job\n\n## Source universe(s)\nRWBY\n\n"
          "## Canon anchor point\nafter the finale\n\n"
          "## Main characters to feature\nRuby\n\n"
          "## Tone\nhopeful adventure\n")

# Six characters, one of them invented for the book — enough for the interaction
# coverage gate to have something real to count, and enough for `refart` to have an
# original it must NOT go looking up on a wiki.
CAST = (("Ruby", "RWBY"), ("Weiss", "RWBY"), ("Blake", "RWBY"), ("Yang", "RWBY"),
        ("Oscar", "RWBY"), ("The Hollow Marshal", "original"))

# Ten distinct subsets across the two chapters, with the group sizes deliberately
# varied — the coverage gate refuses a ledger that is all two-handers or all ensembles,
# and a fixture that could not satisfy that would be testing the gate switched off.
#
# Each one also declares its register, and the distribution is real rather than
# decorative: two of chapter 1's five are physical and three of chapter 2's, so the
# fixture clears the front-half floor, the back-half floor and the whole-book floor on
# merit and with margin, and a regression in any of the three fails the suite here as
# well as in `test_metaplan.py`.
_SUBSETS = {
    1: [(["Ruby", "Weiss"], "physical"),
        (["Blake", "Yang"], "conflict"),
        (["Ruby", "Blake", "Oscar"], "comic"),
        (["Weiss", "Yang", "Oscar", "Blake"], "investigation"),
        (["Ruby", "Weiss", "Blake", "Yang", "Oscar"], "physical")],
    2: [(["Ruby", "Yang"], "physical"),
        (["Weiss", "Oscar", "Blake"], "tender"),
        (["Ruby", "Oscar", "The Hollow Marshal"], "physical"),
        (["Ruby", "Weiss", "Oscar", "The Hollow Marshal"], "comic"),
        (["Ruby", "Weiss", "Blake", "Yang", "Oscar", "The Hollow Marshal"],
         "physical")],
}


def _character(name, origin):
    """One plan cast entry. Originals carry the fuller design the plan gate demands of
    them, because they have no source art to anchor on."""
    spec = {"name": name, "canon_ref": "wiki", "origin": origin,
            "age": 17,
            "appearance": "red cloak, silver eyes, black-red hair",
            "voice": "bright, fast, over-eager; talks about weapons the way other "
                     "people talk about friends",
            "costumes": ["huntress"], "palette": ["#b30000"],
            "ref_sheet_spec": "full body + face"}
    if origin == "original":
        spec["appearance"] = (
            "A tall, narrow figure built like a surveyor's tripod: long straight legs, "
            "a coat that hangs to the ankle without folding, and a head that is a "
            "smooth pale oval with no features except a horizontal seam where a mouth "
            "would be. Moves in straight lines only. Slate grey and bone white "
            "throughout, with one band of surveyor's orange at the collar.")
        spec["distinguishing_feature"] = (
            "the orange collar band, readable as a single bright stripe even at "
            "thumbnail size")
    return spec


# --- Model-seam stubs --------------------------------------------------------

# The genuine implementation of every seam this module replaces, keyed by
# (module name, attribute). Stubbing is a module-level rebinding that outlives the
# test that asked for it, so a test wanting to exercise the real thing needs a way to
# get it back — otherwise whether it passes depends on what ran before it.
_REAL_SEAMS = {}


def _stub(module, name, replacement):
    _REAL_SEAMS.setdefault((module.__name__, name), getattr(module, name))
    setattr(module, name, replacement)


def real_seam(module, name):
    """The unstubbed implementation of one seam. For a test that means to call it."""
    return _REAL_SEAMS.get((module.__name__, name), getattr(module, name))


def stub_model_seams():
    """Replace every model seam with a fixture writer. Everything else — the
    journal, the gates, the bible merge, atomic staging, the epub build and its
    validator, delivery — runs for real, which is the point: this proves the harness
    wiring independent of the models."""

    def canon_proposal(prompt_text, universe, out_path, log_fn=None):
        from fanfic import jobspec
        entities = jobspec.implied_entities(prompt_text) or ["Ruby"]
        storage.save_json({"universe": universe, "facts": [
            {"id": f"c.{i}", "category": "character", "subject": entity,
             "text": f"{entity} is an established character.", "citation": "wiki"}
            for i, entity in enumerate(entities)]}, out_path)
        return "stub canon"
    research.propose_canon = canon_proposal

    def anchor_proposal(series_rec, out_path, log_fn=None, feedback=""):
        from fanfic import jobspec
        names = jobspec.main_characters(series_rec.get("prompt_text", "")) or ["Ruby"]
        storage.save_json({
            "anchor_summary": "One year after the finale.",
            "characters": [
                {"name": n, "age": "17", "where": "Vacuo", "doing": "hunting",
                 "wears": "red cloak, silver eyes", "changed": "Atlas fell",
                 "gaps": ""} for n in names]}, out_path)
        return "stub anchor"
    anchoring.propose_anchor = anchor_proposal

    def plan_proposal(series_rec, out_path, log_fn=None, feedback=""):
        storage.save_json({
            "title": "The Vacuo War", "book_count": 1, "per_book_words": 1600,
            # A deliberately tiny two-chapter book, and it says so. Chapter count is
            # now a FLOOR rather than a target, so this is what keeps the fixture from
            # owing config.MIN_CHAPTERS (32) chapters.
            "per_book_chapters": 2,
            "style_guide": "third-person limited, past tense, PG-13 adventure",
            "arc": {"beginning": "Atlas has fallen", "end": "Vacuo holds"},
            "books": [{"num": 1, "title": "The Vacuo War",
                       "premise": "They rally Vacuo.",
                       "entry_state": "Atlas fallen", "exit_state": "Relic recovered",
                       "role": "opener"}],
            "characters": [_character(name, origin) for name, origin in CAST],
            "relationships": [],
            "antagonists": [{"name": "The Hollow Marshal", "primary": True,
                             "threat": "Unmakes the roads between places."}],
            "progressions": [
                {"id": f"p.{i}", "who": name,
                 "starts": "cannot hold a line alone",
                 "ends": "holds one, and knows why"}
                for i, (name, _origin) in enumerate(CAST, 1)],
        }, out_path)
        return "stub plan"
    planning.propose_plan = plan_proposal

    def meta_chunk(series_rec, book_num, meta, first, last, out_path, log_fn=None,
                   feedback=""):
        storage.save_json({"chapter_count": 2, "chapters": [
            {"number": n, "premise": f"chapter {n} happens",
             "cast": [name for name, _ in CAST],
             "interactions": [{"who": who, "promise": f"ch{n} scene {i}",
                               "register": register}
                              for i, (who, register) in enumerate(_SUBSETS[n], 1)]}
            for n in range(first, min(last, 2) + 1)]}, out_path)
        return "stub meta plan"
    metaplan.propose_chunk = meta_chunk

    def outline_proposal(series_rec, book_num, out_path, log_fn=None,
                         feedback=""):
        everyone = [name for name, _ in CAST]
        half = len(CAST) // 2
        storage.save_json({"chapters": [
            {"number": 1, "title": "The Ruined City",
             "beats": "Ruby scouts the ruined city at dawn.",
             "entry_state": "Atlas fallen", "exit_state": "Ruby finds the trail",
             "characters": everyone, "depends_on": [], "establishes": ["f.trail"],
             "sets_up": ["t.relic"], "pays_off": [], "timeline_index": 0,
             "delivers_progression": [f"p.{i}" for i in range(1, half + 1)]},
            {"number": 2, "title": "What the Trail Held",
             "beats": "Ruby follows the trail and recovers the Relic.",
             "entry_state": "Ruby finds the trail", "exit_state": "Relic recovered",
             "characters": everyone, "depends_on": ["f.trail"], "establishes": [],
             "sets_up": [], "pays_off": ["t.relic"], "timeline_index": 1,
             "delivers_progression": [f"p.{i}"
                                      for i in range(half + 1, len(CAST) + 1)]},
        ]}, out_path)
        return "stub outline"
    outlining.propose_outline = outline_proposal

    def draft(prompt, out_path, log_fn=None, role="drafting"):
        out_path.write_text(PROSE, encoding="utf-8")
        return "stub draft"
    drafting.generate = draft

    def edit_review(series_rec, book_num, chapter_num, prose, truth, gate_brief,
                    pass_num, log_fn=None):
        return {"issues": [], "structural": []}
    editing.model_review = edit_review


    def updates(series_rec, book_num, chapter_num, prose, ledger, log_fn=None):
        return {}                       # no bible changes; the merge is a valid no-op
    bible_update.propose_updates = updates

    def render(prompt, out_path, references=None, log_fn=None, aspect=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(PNG)
    illustration.render = render

    # The illustration stage refuses to draw at all without a signed-in browser
    # profile, which is correct in production and would stop every end-to-end test on
    # a machine that has never run `scripts/gemini-login.sh`. Stubbed alongside the
    # render seam rather than by creating a fake profile directory, because "is the
    # session live" is exactly the kind of question a test of the harness should not
    # be asking. The gate itself is covered directly in `test_images.py`.
    _stub(images, "unconfigured_reason", lambda: None)
    _stub(images, "is_configured", lambda: True)

    # The wiki lookup is a network seam like any other, and it is stubbed here for the
    # ordinary reason plus a specific one: reference art is fetched at the point a
    # sheet is drawn, so leaving it live would put every test that renders anything on
    # the far side of four HTTP round trips per character.
    def no_source_art(series_rec, book_num, name, origin=None, log_fn=None):
        return []
    _stub(refart, "ensure", no_source_art)
    _stub(refart, "gather", lambda series_rec, book_num, log_fn=None: {})

    def vision(image_path, spec_text, references=(), log_fn=None):
        return {"passed": True, "issues": []}
    illustration.vision_verdict = vision

    def scenes(series_rec, book_num, chapter_num, prose_text, n, log_fn=None,
               scope="", must_show="", slot=0):
        return [{"description": f"chapter {chapter_num} moment {k}",
                 "characters": ["Ruby"], "orientation": "portrait"}
                for k in range(1, n + 1)]
    illustration.propose_scenes = scenes


# --- Driving the engine ------------------------------------------------------

def wipe_state():
    """Reset the journal, decisions log, series tree, image queue, and inbox, so a
    test class starts from nothing without touching the other classes' temp dirs."""
    # The two meters belong here as much as the journal does. They are append-only and
    # keyed by series, so without clearing them the picture ledger accumulates across
    # every test in the session and `images_generated` reports whatever the tests before
    # this one happened to spend — a test whose result depends on how many ran before it
    # is not a test. Same reason the state directory is redirected at all.
    for path in (paths.journal_file(), paths.decisions_log(), paths.img_queue(),
                 paths.image_spend_log(), paths.usage_log()):
        if path.exists():
            path.unlink()
    for directory in (config.STATE_DIR / "series", config.INBOX_DIR):
        if directory.exists():
            shutil.rmtree(directory)


def drop(series_id, prompt=PROMPT, settled=True):
    """Drop a job into the inbox — the only way work enters the system.

    Backdates the mtime by default, because admission deliberately ignores a file that
    has not settled for `INBOX_SETTLE_SEC` (a prompt can be observed mid-write or
    mid-iCloud-sync). In production that wait just happens; in a test it would mean
    every drop needed a real sleep. Pass `settled=False` to exercise the wait itself —
    `test_icloud_inbox.py` does."""
    config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
    path = config.INBOX_DIR / f"{series_id}.md"
    path.write_text(prompt, encoding="utf-8")
    if settled:
        stamp = time.time() - (config.INBOX_SETTLE_SEC + 5)
        os.utime(path, (stamp, stamp))
    return path


def prompt_fixture(name):
    """A real job prompt, wherever it currently lives — the drop folder, or filed away
    under finished/ or failed/.

    Real prompts are gitignored runtime input, so a test built on one is an
    opportunistic guard: it protects the live job on this machine and skips on a fresh
    clone. That is a deliberate trade, not an oversight — the parsing rules it pins are
    also covered by synthetic cases that always run."""
    # The suite redirects INBOX_DIR to a temp path, so the real drop folder has to be
    # named outright rather than read from config — that redirect is exactly what made
    # an earlier version of this lookup skip silently.
    real_inbox = Path("~/Library/Mobile Documents/com~apple~CloudDocs/Books/_inbox"
                      ).expanduser()
    roots = (real_inbox, real_inbox / "failed", real_inbox / "finished",
             config.INBOX_DIR, config.INBOX_FAILED_DIR, config.INBOX_FINISHED_DIR)
    for root in roots:
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def run_engine(series_id, limit=80, log_fn=lambda _msg: None):
    """Drive real engine cycles until this series terminates or the bound is hit.
    Bounded so a regression that spins forever fails the test instead of hanging."""
    key = journal.series_key(series_id)
    for _ in range(limit):
        cycle.run(log_fn=log_fn)
        status = journal.load_records().get(key, {}).get("status")
        if status in (states.SERIES_COMPLETE, states.STALLED):
            return status
    return journal.load_records().get(key, {}).get("status")
