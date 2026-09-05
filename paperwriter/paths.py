"""Every path the harness reads or writes, derived from config.STATE_DIR.

One module describes the whole shape of the state tree, so redirecting STATE_DIR
relocates all of it and no stage ever hand-joins a path. Pure computation — no
I/O, no model calls, no mkdir except where a caller is about to write.

    state/
      journal.jsonl                     append-only journal (the source of truth)
      decisions.log                     human-readable audit of every model call
      <daemon>.log                      per-daemon log mirror
      usage.jsonl                       per-call usage, valued at list price
      locks/<daemon>.lock               single-instance flock per daemon
      evidence/<corpus>/evidence.json   cited evidence, frozen after gathering
      project/<pid>/
        plan.json                       the validated project plan
        grounding.json                  terminology lock, estimand, reader
        ledger.json                     the mutable, append-validated claim ledger
        paper/<n>/
          argument.json                 every claim, its evidence, its section
          outline.json                  validated section list + paragraph plans
          paper_ledger.json             derived working slice
          sections/s<NN>.md             ACCEPTED section prose
          manuscript.md                 the assembled manuscript
          <slug>.docx                   the built manuscript
      tmp/                              proposals, drafts, verdicts before validation
"""

import re

from . import config


def slug(text):
    """Filesystem- and id-safe form of any label. The project id is the slug of the
    dropped prompt's filename, so this is load-bearing for job identity."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-").lower()
    return s or "untitled"


# --- Top-level state files ---------------------------------------------------

def journal_file():
    return config.STATE_DIR / "journal.jsonl"


def decisions_log():
    return config.STATE_DIR / "decisions.log"


def log_file(daemon):
    """Each daemon mirrors its stdout here, so a log survives the service manager
    rotating its own and is readable from inside the state tree."""
    return config.STATE_DIR / f"{slug(daemon)}.log"


def lock_file(daemon):
    return config.STATE_DIR / "locks" / f"{slug(daemon)}.lock"


def status_file():
    """The phone-readable status document, in the drop folder beside the jobs. None
    when the operator has turned it off."""
    if not config.STATUS_FILENAME:
        return None
    return config.INBOX_DIR / config.STATUS_FILENAME


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


# --- Evidence ----------------------------------------------------------------

def evidence_dir(corpus):
    return config.STATE_DIR / "evidence" / slug(corpus)


def evidence_path(corpus):
    return evidence_dir(corpus) / "evidence.json"


# --- Project -----------------------------------------------------------------

def project_root(project_id):
    return config.STATE_DIR / "project" / slug(project_id)


def plan_path(project_id):
    return project_root(project_id) / "plan.json"


def ledger_path(project_id):
    return project_root(project_id) / "ledger.json"


def grounding_path(project_id):
    """The frozen grounding: what each term is called, what the estimand is, who the
    reader is, and which reporting checklist governs. Fixed once, before drafting."""
    return project_root(project_id) / "grounding.json"


# --- Paper -------------------------------------------------------------------

def paper_root(project_id, paper_num):
    return project_root(project_id) / "paper" / str(paper_num)


def argument_path(project_id, paper_num):
    """The argument map: every claim the paper makes, the evidence it rests on, and
    the section it lands in. Committed state rather than a proposal — it is built a
    chunk of sections at a time, and each accepted chunk is persisted so a crash
    resumes at the next chunk instead of rebuilding the whole map."""
    return paper_root(project_id, paper_num) / "argument.json"


def argument_proposal_path(project_id, paper_num, chunk=0):
    return tmp_path(f"arg_{slug(project_id)}_p{paper_num}_c{int(chunk)}.json")


def outline_path(project_id, paper_num):
    return paper_root(project_id, paper_num) / "outline.json"


def paper_ledger_path(project_id, paper_num):
    return paper_root(project_id, paper_num) / "paper_ledger.json"


def sections_dir(project_id, paper_num):
    return paper_root(project_id, paper_num) / "sections"


def section_path(project_id, paper_num, section_num):
    return sections_dir(project_id, paper_num) / f"s{int(section_num):02d}.md"


def manuscript_path(project_id, paper_num):
    """The assembled manuscript: every accepted section, in order, with front matter.
    This is the artifact. Everything built from it is a convenience."""
    return paper_root(project_id, paper_num) / "manuscript.md"


def built_path(project_id, paper_num, title, fmt):
    return paper_root(project_id, paper_num) / f"{slug(title)}.{fmt}"


# --- Scratch: proposals before validation ------------------------------------
#
# Named, not ad-hoc: the drafting stage writes the section here and the review and
# ledger-merge stages hand the same path to their models. Before these functions
# existed each stage rebuilt the filename by convention, which is a coupling that
# breaks silently the moment one of them is edited.

def tmp_path(name):
    d = config.STATE_DIR / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def evidence_proposal_path(corpus):
    return tmp_path(f"evid_{slug(corpus)}.json")


def grounding_proposal_path(project_id):
    return tmp_path(f"ground_{slug(project_id)}.json")


def plan_proposal_path(project_id):
    return tmp_path(f"plan_{slug(project_id)}.json")


def outline_proposal_path(project_id, paper_num):
    return tmp_path(f"outline_{slug(project_id)}_p{paper_num}.json")


def draft_path(project_id, paper_num, section_num):
    """Where a section draft lives while it is still a proposal. Nothing downstream
    of the editorial loop reads this — the accepted prose goes to section_path."""
    return tmp_path(
        f"draft_{slug(project_id)}_p{paper_num}_s{int(section_num):02d}.md")


def pass_snapshot_path(project_id, paper_num, section_num, pass_num):
    """The prose as one editorial pass left it. Written, never read by the pipeline.

    The loop keeps only the LAST version of a section, and that is measurably not
    always the best one. Whether to ship the better-measured version instead turns on
    a comparison that cannot be made if the better version was overwritten the moment
    the next pass ran.

    So: keep it. This changes NOTHING about what ships — it exists so the comparison
    can be made from real text rather than argued from defect counts."""
    return tmp_path(f"pass_{slug(project_id)}_p{paper_num}"
                    f"_s{int(section_num):02d}_x{int(pass_num):02d}.md")


def patch_path(project_id, paper_num, section_num):
    """Where a revision proposes its edit list, before the harness applies it."""
    return tmp_path(f"patch_{slug(project_id)}_p{paper_num}"
                    f"_s{int(section_num):02d}.json")


def continuation_path(project_id, section_num, pass_num):
    """Where one continuation pass proposes the NEXT stretch of a short section.

    Its own path, not the draft path: `draft_path` is unlinked before every model run
    so that a file being present proves this run wrote it, and a continuation must not
    destroy the prose it is continuing from."""
    return tmp_path(f"cont_{slug(project_id)}_s{int(section_num):02d}"
                    f"_x{int(pass_num)}.md")


def prev_draft_path(project_id, paper_num, section_num):
    """The draft a revision is revising.

    `draft_path` is deleted before every model run, so that "a file is there" means
    "this run wrote it". A revision therefore needs the prior attempt snapshotted
    somewhere that deletion cannot reach, or it has nothing to revise and writes a
    brand-new section instead."""
    return tmp_path(
        f"prev_{slug(project_id)}_p{paper_num}_s{int(section_num):02d}.md")


def edit_path(project_id, paper_num, section_num, pass_num=0):
    """Where one editorial pass proposes its issues-with-repairs.

    Per pass, rather than one path reused: a pass that produces an unparseable artifact
    is diagnosed by reading what it actually wrote, and overwriting the previous pass's
    list destroys the only record of how a section converged."""
    return tmp_path(f"edit_{slug(project_id)}_p{paper_num}"
                    f"_s{int(section_num):02d}_x{int(pass_num)}.json")


def surgery_path(project_id, paper_num, section_num, index=0):
    """Where surgery proposes the replacement prose for one anchored passage."""
    return tmp_path(f"surg_{slug(project_id)}_p{paper_num}"
                    f"_s{int(section_num):02d}_{int(index)}.md")


def ledger_update_path(project_id, paper_num, section_num):
    return tmp_path(f"lupd_{slug(project_id)}_p{paper_num}"
                    f"_s{int(section_num):02d}.json")
