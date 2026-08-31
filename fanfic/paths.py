"""Every path the fleet reads or writes, derived from config.STATE_DIR.

One module describes the whole shape of the state tree, so redirecting STATE_DIR
relocates all of it and no stage ever hand-joins a path. Pure computation — no
I/O, no model calls, no mkdir except where a caller is about to write.

    state/
      journal.jsonl                     append-only journal (the source of truth)
      decisions.log                     human-readable audit of every model call
      <daemon>.log                      per-daemon log mirror
      imgqueue.jsonl                    scene-image work queue
      usage.jsonl                       per-call usage, valued at list price
      locks/<daemon>.lock               single-instance flock per daemon
      canon/<universe>/canon.json       cited canon, frozen after research
      series/<sid>/
        plan.json                       the validated series plan
        series_bible.json               the mutable, append-validated bible
        book/<n>/
          outline.json                  validated chapter list + beat sheets
          book_bible.json               derived working slice
          image_prompts.md              reviewable prompt pack for the book
          chapters/ch<NN>.md            ACCEPTED chapter prose
          sheets/<character>.png        LOCKED visual reference sheets
          images/ch<NN>_<k>.png         ACCEPTED scene illustrations
          images/cover.png              the cover
          <slug>.epub                   the bound book
      tmp/                              proposals, drafts, verdicts before validation
"""

import re

from . import config


def slug(text):
    """Filesystem- and id-safe form of any label. The series id is the slug of the
    dropped prompt's filename, so this is load-bearing for job identity."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-").lower()
    return s or "untitled"


# --- Top-level state files ---------------------------------------------------

def journal_file():
    return config.STATE_DIR / "journal.jsonl"


def decisions_log():
    return config.STATE_DIR / "decisions.log"


def log_file(daemon):
    """Each daemon mirrors its stdout here, so a log survives launchd rotating
    ~/Library/Logs and is readable from inside the state tree."""
    return config.STATE_DIR / f"{slug(daemon)}.log"


def lock_file(daemon):
    return config.STATE_DIR / "locks" / f"{slug(daemon)}.lock"


def status_file():
    """The phone-readable status document, in the drop folder beside the jobs. None
    when the operator has turned it off."""
    if not config.STATUS_FILENAME:
        return None
    return config.INBOX_DIR / config.STATUS_FILENAME


def img_queue():
    return config.STATE_DIR / "imgqueue.jsonl"


# --- Canon -------------------------------------------------------------------

def canon_dir(universe):
    return config.STATE_DIR / "canon" / slug(universe)


def canon_path(universe):
    return canon_dir(universe) / "canon.json"


# --- Series ------------------------------------------------------------------

def series_root(series_id):
    return config.STATE_DIR / "series" / slug(series_id)


def plan_path(series_id):
    return series_root(series_id) / "plan.json"


def series_bible_path(series_id):
    return series_root(series_id) / "series_bible.json"


# --- Book --------------------------------------------------------------------

def book_root(series_id, book_num):
    return series_root(series_id) / "book" / str(book_num)


def outline_path(series_id, book_num):
    return book_root(series_id, book_num) / "outline.json"


def book_bible_path(series_id, book_num):
    return book_root(series_id, book_num) / "book_bible.json"


def metaplan_path(series_id, book_num):
    """The meta plan: every chapter's premise, its cast, and the character collisions
    that fire in it. Committed state rather than a proposal — it is built ten chapters
    at a time, and each accepted chunk is persisted here so a crash resumes at the next
    chunk instead of rebuilding a 180-entry ledger from nothing."""
    return book_root(series_id, book_num) / "metaplan.json"


def metaplan_proposal_path(series_id, book_num, chunk=0):
    return tmp_path(f"meta_{slug(series_id)}_b{book_num}_c{int(chunk)}.json")


def prompt_pack_path(series_id, book_num):
    return book_root(series_id, book_num) / "image_prompts.md"


def chapters_dir(series_id, book_num):
    return book_root(series_id, book_num) / "chapters"


def chapter_path(series_id, book_num, chapter_num):
    return chapters_dir(series_id, book_num) / f"ch{int(chapter_num):02d}.md"


def refart_dir(series_id, book_num, character):
    """Source-material reference pictures for one character, downloaded from the
    fandom wiki. Distinct from `sheets_dir`: those are OUR generated model sheets in
    the book's unified style, these are the show's own art, and the second is what
    settles a face."""
    return book_root(series_id, book_num) / "refart" / slug(character)


def sheets_dir(series_id, book_num):
    return book_root(series_id, book_num) / "sheets"


def sheet_path(series_id, book_num, character):
    return sheets_dir(series_id, book_num) / f"{slug(character)}.png"


def images_dir(series_id, book_num):
    return book_root(series_id, book_num) / "images"


def scene_image_path(series_id, book_num, chapter_num, k):
    return images_dir(series_id, book_num) / f"ch{int(chapter_num):02d}_{int(k)}.png"


def cover_path(series_id, book_num):
    return images_dir(series_id, book_num) / "cover.png"


def epub_path(series_id, book_num, title):
    return book_root(series_id, book_num) / f"{slug(title)}.epub"


# --- Scratch: proposals before validation ------------------------------------
#
# Named, not ad-hoc: the drafting stage writes the chapter here and the critique
# and bible-merge stages hand the same path to their models. Before these
# functions existed each stage rebuilt the filename by convention, which is a
# coupling that breaks silently the moment one of them is edited.

def tmp_path(name):
    d = config.STATE_DIR / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def canon_proposal_path(universe):
    return tmp_path(f"canon_{slug(universe)}.json")


def anchor_path(series_id):
    """Where the frozen anchor state lives: where every principal is, what they are
    doing, and what they wear when the book opens."""
    return series_root(series_id) / "anchor.json"


def anchor_proposal_path(series_id):
    return tmp_path(f"anchor_{slug(series_id)}.json")


def plan_proposal_path(series_id):
    return tmp_path(f"plan_{slug(series_id)}.json")


def outline_proposal_path(series_id, book_num):
    return tmp_path(f"outline_{slug(series_id)}_b{book_num}.json")


def usage_log():
    """Append-only record of how much model capacity each call consumed, expressed as
    its **list-price valuation in USD**.

    NOT a bill. The `claude` CLI authenticates through its logged-in session — there is
    no API key anywhere in this project — so nothing here is money debited from anyone.
    The CLI reports `total_cost_usd` regardless of how it authenticates, and on a seat
    that figure is what the tokens *would* cost at API list rates. It is a usage meter
    with a dollar sign on it: useful because it is proportional to the allowance a run
    burns, misleading if read as spend.

    Alongside the journal rather than inside it: the journal is the source of truth for
    state and must stay replayable, while this is bookkeeping."""
    return config.STATE_DIR / "usage.jsonl"


def image_spend_log():
    """The picture ledger: one line per generated image, per series. Separate from
    `usage_log` because these are different currencies — that file meters allowance
    consumed on a seat, this one counts money actually spent."""
    return config.STATE_DIR / "image_spend.jsonl"


def draft_path(series_id, book_num, chapter_num):
    """Where a chapter draft lives while it is still a proposal. Nothing downstream
    of the critique battery reads this — the accepted prose goes to chapter_path."""
    return tmp_path(f"draft_{slug(series_id)}_b{book_num}_ch{int(chapter_num):02d}.md")


def patch_path(series_id, book_num, chapter_num):
    """Where a revision proposes its edit list, before the harness applies it."""
    return tmp_path(f"patch_{slug(series_id)}_b{book_num}"
                    f"_ch{int(chapter_num):02d}.json")


def continuation_path(series_id, chapter_num, pass_num):
    """Where one continuation pass proposes the NEXT stretch of a short chapter.

    Its own path, not the draft path: `draft_path` is unlinked before every model run
    so that a file being present proves this run wrote it, and a continuation must not
    destroy the prose it is continuing from."""
    return tmp_path(f"cont_{slug(series_id)}_ch{int(chapter_num):02d}"
                    f"_p{int(pass_num)}.md")


def prev_draft_path(series_id, book_num, chapter_num):
    """The draft a revision is revising.

    `draft_path` is deleted before every model run, so that "a file is there" means
    "this run wrote it". A revision therefore needs the prior attempt snapshotted
    somewhere that deletion cannot reach, or it has nothing to revise and writes a
    brand-new chapter instead — which is exactly what happened until 2026-08-05."""
    return tmp_path(
        f"prev_{slug(series_id)}_b{book_num}_ch{int(chapter_num):02d}.md")


def verdict_path(series_id, book_num, chapter_num):
    return tmp_path(f"verdict_{slug(series_id)}_b{book_num}_ch{int(chapter_num):02d}.json")


def edit_path(series_id, book_num, chapter_num, pass_num=0):
    """Where one editorial pass proposes its issues-with-repairs.

    Per pass, rather than one path reused: a pass that produces an unparseable artifact
    is diagnosed by reading what it actually wrote, and overwriting the previous pass's
    list destroys the only record of how a chapter converged."""
    return tmp_path(f"edit_{slug(series_id)}_b{book_num}"
                    f"_ch{int(chapter_num):02d}_p{int(pass_num)}.json")


def surgery_path(series_id, book_num, chapter_num, index=0):
    """Where scene surgery proposes the replacement prose for one anchored passage."""
    return tmp_path(f"surg_{slug(series_id)}_b{book_num}"
                    f"_ch{int(chapter_num):02d}_{int(index)}.md")


def bible_update_path(series_id, book_num, chapter_num):
    return tmp_path(f"bupd_{slug(series_id)}_b{book_num}_ch{int(chapter_num):02d}.json")


def scenes_proposal_path(series_id, book_num, chapter_num, slot=0):
    """Where art direction proposes one segment's illustration.

    Per slot, because art direction now runs once per scene segment rather than once
    per chapter: a shared path would leave only the last segment's proposal on disk,
    and the one thing a malformed proposal needs is to still be readable afterwards."""
    return tmp_path(f"scenes_{slug(series_id)}_b{book_num}"
                    f"_ch{int(chapter_num):02d}_s{int(slot)}.json")


def vision_verdict_path(image_path):
    return tmp_path(f"vision_{image_path.stem}.json")
