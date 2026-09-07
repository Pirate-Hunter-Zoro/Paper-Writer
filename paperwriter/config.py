"""Every tunable in the harness, in one module. No logic, no I/O.

The design is documented in full in README.md; this file is the knob panel, so
the stages stay declarative and a behaviour change is a one-line edit here (or an
environment variable, so a service file can override it without touching code).

Every runtime path is rooted at STATE_DIR, and STATE_DIR is env-overridable:
pointing PAPER_STATE_DIR at a temp tree relocates the journal, the evidence, the
ledgers, staging, and the logs in one move. That is what makes the deterministic
half testable anywhere.

Every environment variable is prefixed `PAPER_`.
"""

import os
import shutil
from pathlib import Path

# --- Roots -------------------------------------------------------------------

# The repo. `paperwriter/config.py` -> repo root is two levels up.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_path(var, default):
    """A path tunable overridable from the environment."""
    val = os.environ.get(var)
    return Path(val).expanduser() if val else default


def _env_flag(var, default=True):
    """A boolean tunable. Anything in the falsey set turns it off."""
    raw = os.environ.get(var)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


# --- The drop folder ---------------------------------------------------------

# Where finished manuscripts are delivered, and where the drop folder lives beneath
# it. Default to a directory in the repo's parent so a clone works with no setup;
# point PAPER_OUT_DIR at a synced folder to drive the whole thing from a phone.
OUT_DIR = _env_path("PAPER_OUT_DIR", PROJECT_ROOT.parent / "Manuscripts")

# One filled prompt-template markdown file here is one job. Finished and failed
# prompts move into subfolders that are NOT re-scanned — file it away, never delete.
#
# `_inbox` cannot collide with a delivered project folder: delivery names those with
# `paths.slug`, which maps every non-alphanumeric run to a hyphen and strips leading
# ones, so a slug can never begin with an underscore.
INBOX_DIR = _env_path("PAPER_INBOX_DIR", OUT_DIR / "_inbox")
INBOX_FINISHED_DIR = INBOX_DIR / "finished"
INBOX_FAILED_DIR = INBOX_DIR / "failed"

# A short human-readable status document written beside the jobs, so progress is
# legible without a terminal. Set to "" to turn it off.
STATUS_FILENAME = os.environ.get("PAPER_STATUS_FILE", "_STATUS.md")

# How long a dropped file must stop changing before it is admitted. A file being
# written or synced into place is not a job yet.
INBOX_SETTLE_SEC = int(os.environ.get("PAPER_INBOX_SETTLE_SEC", "10"))

# The committed base prompts. Load-bearing non-code artifacts; they live at the repo
# root so they are easy to find and hand-edit.
PROMPTS_DIR = PROJECT_ROOT / "prompts"

# The runtime state tree. Everything the harness writes lives under here.
STATE_DIR = _env_path("PAPER_STATE_DIR", PROJECT_ROOT / "state")

# Artifacts are written into a hidden sibling directory and then atomically renamed,
# so no stage ever observes a half-written section.
STAGING_DIRNAME = ".staging"

# --- Where the evidence comes from -------------------------------------------
#
# A paper is written against results that already exist. SOURCE_DIRS are read-only
# trees the evidence stage may mine: an analysis repository's `results/`, a
# `references/` folder of PDFs, a reporting checklist. Colon-separated.
#
# Nothing here is ever written to. The harness reads numbers and citations out of
# these trees and freezes them into `state/evidence/`, and from that point on the
# frozen copy is ground truth — so a rerun of the analysis mid-draft cannot silently
# change what the manuscript claims.
_SOURCES_RAW = os.environ.get("PAPER_SOURCE_DIRS", "").strip()
SOURCE_DIRS = tuple(Path(p).expanduser() for p in _SOURCES_RAW.split(":") if p.strip())

# --- Prose and judgment: Claude, and only Claude -----------------------------
#
# Every text call in this harness goes to the same model. Evidence gathering,
# planning, outlining, drafting, editing, ledger merges — one model, one prompt
# style, one set of habits to write against.
#
# This used to be a five-provider registry with a two-tier model split (a cheap model
# wrote, an expensive one judged) and a per-role routing table. All of it is gone, and
# the argument is in `paperwriter/providers/__init__.py`. The short version: the split
# gave every quality problem two suspects, and the roles routed to the cheap tier kept
# having to be routed back after one of them cost a run.
#
# Prose quality is the entire product. There is no volume argument that beats it.

# Which binary drives Claude. Headless, on a logged-in session — the harness holds no
# API key and never has.
CLI_BIN = os.environ.get("PAPER_CLI_BIN", "claude")

# The model. One line, and it is the most consequential line in this file.
MODEL = os.environ.get("PAPER_MODEL", "claude-opus-5")

# --- What that consumes ------------------------------------------------------
#
# $ per MILLION tokens, as (input, output). Consumed only by `paperwriter/cost.py`,
# which projects what a paper costs; nothing at runtime reads it.
#
# These are LIST PRICES, and on a seat you are not charged them (see
# `infra/budget.record_usage`) — so read them as a measure of allowance consumed,
# not as a bill.
#
# Re-check before trusting a total; published rates move.
PRICES = {
    "claude-opus-5":      (5.00, 25.00),    # what this harness runs
    "claude-fable-5":    (10.00, 50.00),
    "claude-opus-4-8":    (5.00, 25.00),
    "claude-sonnet-5":    (2.00, 10.00),
    "claude-haiku-4-5":   (1.00,  5.00),
}

# --- The role table: what each kind of work is allowed to spend ---------------
#
# One table instead of eight stages each hand-tuning `max_turns` and `timeout` at
# its own call site. That scatter is not hypothetical harm: drafting sat at the
# smallest budget in the pipeline against the largest artifact in it for as long as
# the numbers were not written down next to each other.
#
#   max_turns agent turns
#   timeout   seconds for one call
#   tools     tool grant, smallest that does the job — this runs unattended with
#             permissions skipped, so a narrow grant is a narrow blast radius
#   oneshot   the role's whole input is INLINED in the prompt, so the model reads
#             nothing and writes the artifact in one call. This is the single largest
#             lever in the project — bigger than any model choice. An agentic CLI
#             re-sends the whole conversation, including every tool result, on every
#             turn, so a writer that opens the previous draft and lays a section down
#             in eight appends pays for that transcript eight times. Inlined and
#             written once, the same work at the same model is two or three turns. A
#             one-shot role gets a Write-only tool grant, because granting Read to a
#             model told not to read is an invitation.
TEXT_ROLES = {
    # Mines the results trees, the reference PDFs, and the reporting checklist. The
    # only role that genuinely needs to go and find its own input, and therefore the
    # only one that cannot be one-shot.
    "evidence":     {"max_turns": 80, "timeout": 2400,
                     "tools": ("Read", "Write", "Grep", "Glob", "WebSearch",
                               "WebFetch")},
    # Fixing the terminology, the estimand, and the reader the paper is written for,
    # once, before a word is drafted. The failure it prevents is a wrong choice
    # repeated on every page — a representation called three different things in one
    # manuscript, which reads to a reviewer as three different methods.
    "grounding":    {"max_turns": 24, "timeout": 2400,
                     "oneshot": True, "tools": ("Write",)},
    # The project plan: which papers, which venues, which claims belong to which.
    "planning":     {"max_turns": 40, "timeout": 3600,
                     "oneshot": True, "tools": ("Write",)},
    # The argument map: every claim the paper makes, the evidence each rests on, and
    # the section it lands in. The largest structured artifact in the pipeline.
    "argument":     {"max_turns": 40, "timeout": 3600,
                     "oneshot": True, "tools": ("Write",)},
    # Paragraph-level outlines for every section: one entry per paragraph, carrying
    # its topic sentence and the evidence ids it uses.
    "outlining":    {"max_turns": 30, "timeout": 3000,
                     "oneshot": True, "tools": ("Write",)},
    # Writes one section. The turn budget is not a length allowance — one Write
    # carries the whole section — it is headroom for thinking before that write.
    "drafting":     {"max_turns": 10, "timeout": 2400,
                     "oneshot": True, "tools": ("Write",)},
    # Finishing a section that stopped short. Its own role rather than a second use
    # of `drafting`, because it is a different job with a different input, and
    # because it should be separately visible in the cost breakdown.
    "continuation": {"max_turns": 10, "timeout": 2400,
                     "oneshot": True, "tools": ("Write",)},
    # The editorial pass: reads a whole section against the whole ledger and writes
    # back every defect WITH its exact repair. The most leveraged call in the
    # pipeline, because it is not only deciding what is wrong, it is writing the
    # correction that gets applied verbatim.
    "review":       {"max_turns": 10, "timeout": 1800,
                     "oneshot": True, "tools": ("Write",)},
    # Schema extraction from prose that is already in the prompt. Mechanical, and
    # structurally validated afterwards by `memory.ledger.merge_ledger_update`, so a
    # bad proposal here costs a revision at worst, never a corrupt ledger.
    "ledger_merge": {"max_turns": 6, "timeout": 900,
                     "oneshot": True, "tools": ("Write",)},
}

# Extra PATH entries prepended for subprocess model calls.
EXTRA_PATH = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]

# How long to wait out a model-side allowance ceiling before trying again.
MODEL_QUOTA_BACKOFF_SEC = int(os.environ.get("PAPER_MODEL_QUOTA_BACKOFF_SEC", "300"))

# --- Length ------------------------------------------------------------------
#
# Academic length is a CEILING, and that is the one place this project's targets
# invert from the novel harness it grew out of. A journal that says 4,000 words means
# it, and a manuscript over the limit is desk-rejected before a reviewer reads a
# sentence. So sections carry a budget from the outline and the gate enforces both
# ends of it: too short means a claim was asserted rather than supported, too long
# means the section is padded and will be cut by someone who is not the author.
#
# The floor is deliberately loose and the ceiling deliberately tight.
SECTION_MIN_WORDS = int(os.environ.get("PAPER_SECTION_MIN_WORDS", "150"))

# How far over its outline budget a section may run before the gate blocks. 1.15 is
# one long paragraph of slack on a 1,000-word section.
SECTION_OVER_BUDGET_RATIO = float(
    os.environ.get("PAPER_SECTION_OVER_BUDGET_RATIO", "1.15"))

# And how far under, for the same reason in the other direction. A section at 55% of
# its planned length is not concise, it is missing a claim.
SECTION_UNDER_BUDGET_RATIO = float(
    os.environ.get("PAPER_SECTION_UNDER_BUDGET_RATIO", "0.6"))

# --- Readability -------------------------------------------------------------
#
# Not the children's-book band this code was born with. Academic prose in a clinical
# or methodological journal sits around FK grade 11-15: above that the reviewer is
# re-reading sentences.
#
# **The floor is deliberately generous, and it is the one threshold here that must
# never be tightened.** This whole harness exists to produce prose a reader
# understands on one pass, and short sentences made of plain words are how that is
# achieved — so a gate that penalises a well-written section for scoring 9.9 is a gate
# arguing against the project's entire purpose. It is here only to catch a section
# that has dropped the precision its claims need, which is a real failure and a rare
# one, and its own message says as much.
#
# Reading ease is gated loosely for the same reason in the other direction: a Methods
# section full of necessarily polysyllabic clinical nouns scores badly however well it
# is written, and `gates/sentences.py` measures the thing that actually goes wrong.
READABILITY_FK_GRADE_MIN = float(os.environ.get("PAPER_FK_GRADE_MIN", "8.0"))
READABILITY_FK_GRADE_MAX = float(os.environ.get("PAPER_FK_GRADE_MAX", "16.0"))
READABILITY_FLESCH_EASE_MIN = float(os.environ.get("PAPER_FLESCH_EASE_MIN", "20.0"))

# --- The one-read rule, measured ---------------------------------------------
#
# "The reader must understand every sentence the first time" is a slogan until it is
# counted. These are the counts, and every one of them was calibrated against a real
# manuscript whose reviewers complained about density: body text at a mean of 26.2
# words per sentence, 23% of sentences past 35 words, 74 semicolons and 34 em-dashes
# in 15,000 words. Nearly every one of those marks welded a second claim into a
# sentence that already carried one.
#
# The targets below are what that manuscript should have been.

# Mean words per sentence, across a section. The band, not a point: prose that is
# uniformly short is its own failure and reads like a machine wrote it.
SENTENCE_MEAN_WORDS_MAX = float(os.environ.get("PAPER_SENTENCE_MEAN_MAX", "22.0"))
SENTENCE_MEAN_WORDS_MIN = float(os.environ.get("PAPER_SENTENCE_MEAN_MIN", "12.0"))

# A sentence past this is doing two jobs. Some are legitimate; a section where many
# are is not.
SENTENCE_LONG_WORDS = int(os.environ.get("PAPER_SENTENCE_LONG_WORDS", "35"))
SENTENCE_LONG_SHARE_MAX = float(os.environ.get("PAPER_SENTENCE_LONG_SHARE_MAX", "0.08"))

# The hard ceiling. One sentence of 60 words is a defect wherever it appears.
SENTENCE_HARD_MAX_WORDS = int(os.environ.get("PAPER_SENTENCE_HARD_MAX", "55"))

# Sentence length must VARY. Standard deviation below this floor means every sentence
# is the same length, which is the loudest tell that a machine wrote the paragraph.
SENTENCE_STDEV_MIN = float(os.environ.get("PAPER_SENTENCE_STDEV_MIN", "4.0"))

# Welds, per 1,000 words. A semicolon or an em-dash is almost always two sentences
# pretending to be one. Not banned — occasionally one is exactly right — but rationed.
SEMICOLONS_PER_KWORD_MAX = float(os.environ.get("PAPER_SEMICOLON_RATE_MAX", "2.0"))
EMDASHES_PER_KWORD_MAX = float(os.environ.get("PAPER_EMDASH_RATE_MAX", "2.0"))

# The local density ceiling: mean words per sentence within ONE paragraph.
#
# Every measurement above is a section average, and an average hides the paragraph
# that earns it. A real manuscript from this harness passed its Methods section at a
# mean of 20.8 while carrying a four-sentence paragraph at 27.2 — the section's other
# nineteen sentences paid for it. Six such paragraphs sat in sections that passed. The
# reader does not read the average; they read the paragraph, and they read it twice.
#
# The ceiling is looser than the section ceiling on purpose. One paragraph is allowed
# to be the heavy one — a definition, a set of exclusions, a passage that genuinely
# carries more clauses than its neighbours. What is not allowed is a paragraph nobody
# can read hiding behind twenty sentences that carry it.
PARAGRAPH_MEAN_WORDS_MAX = float(os.environ.get("PAPER_PARAGRAPH_MEAN_MAX", "26.0"))

# Below this many sentences a paragraph mean is not a measurement. Two sentences, one
# of them a legitimate 40-word list of covariates, average 26 and mean nothing.
PARAGRAPH_DENSITY_MIN_SENTENCES = int(
    os.environ.get("PAPER_PARAGRAPH_DENSITY_MIN_SENTENCES", "3"))

# How many of the worst-offending sentences the editor is shown verbatim when the
# section fails a sentence gate. Readability is a whole-text statistic and cannot be
# anchored to a span; the longest sentences can be, which turns an un-anchorable gate
# into a list of ordinary anchored edits.
EDIT_LONG_SENTENCES = int(os.environ.get("PAPER_EDIT_LONG_SENTENCES", "15"))

# --- Paragraph shape ---------------------------------------------------------
#
# A paragraph is a claim, its support, and its consequence. The gate cannot judge
# whether a topic sentence is good, but it can catch every structural way a paragraph
# fails to have one: a paragraph that opens on a citation, opens on a number, opens
# with a connective, or is one sentence long and therefore has no structure at all.
PARAGRAPH_MIN_SENTENCES = int(os.environ.get("PAPER_PARAGRAPH_MIN_SENTENCES", "3"))
PARAGRAPH_MAX_SENTENCES = int(os.environ.get("PAPER_PARAGRAPH_MAX_SENTENCES", "9"))

# What share of a section's paragraphs may break the shape rules before it blocks.
# Not zero: a one-sentence paragraph is right at the end of a Discussion, and a table
# caption is a paragraph to the parser.
PARAGRAPH_DEFECT_SHARE_MAX = float(
    os.environ.get("PAPER_PARAGRAPH_DEFECT_SHARE_MAX", "0.15"))

# --- The point made over and over ---------------------------------------------
#
# Three sections each spending a paragraph on the same background fact. Every
# instance true, well written and relevant; end to end it reads as a paper that does
# not trust its reader. Two is normal — a Discussion picks up what the Results said —
# so the floor is three.
ECHO_MIN_SECTIONS = int(os.environ.get("PAPER_ECHO_MIN_SECTIONS", "3"))

# Jaccard overlap of content words. A writer restating a point never uses the same
# words twice, so this is deliberately loose; it was set by pointing the check at a
# real manuscript and walking it up until the table captions stopped matching.
ECHO_SIMILARITY = float(os.environ.get("PAPER_ECHO_SIMILARITY", "0.45"))

# Below this many content words, heavy overlap does not mean two sentences say the
# same thing.
ECHO_MIN_CONTENT_WORDS = int(os.environ.get("PAPER_ECHO_MIN_CONTENT_WORDS", "8"))

# Sections whose paragraph-shape rules are relaxed entirely. An abstract is one
# structured block, a declarations section is a list, and references are not prose.
# An abbreviations list joined this set on 2026-09-06, when a venue that requires one
# produced a 92-word "sentence" made of fourteen glossary entries. A definition list is
# not prose, for the same reason a reference list is not.
PARAGRAPH_EXEMPT_SECTIONS = ("abstract", "title page", "declarations", "references",
                             "acknowledgements", "keywords", "abbreviations")

# Sections a paper is SUPPOSED to restate itself in. The paragraph-shape rules still
# apply to a conclusions section — it is prose and it has topic sentences — so this is
# its own list rather than a reuse of PARAGRAPH_EXEMPT_SECTIONS. A conclusions that
# introduced new material would be the defect; one that repeats the Discussion is the
# section working, and counting it makes the normal arc of a paper look like a fault.
ECHO_EXEMPT_SECTIONS = tuple(sorted(set(PARAGRAPH_EXEMPT_SECTIONS) |
                                    {"conclusions", "conclusion", "summary"}))

# --- Terminology drift -------------------------------------------------------
#
# The terminology gate can only forbid the synonyms somebody thought to list. The
# manuscript that gate was written from went on to carry four names for one arm —
# "typed feature representation", "feature representation", "feature matrix" and
# "feature-vector" — because only "rule-based approach" had been banned. Nothing
# fired, because nothing was looking for a name the lock had never heard of.
#
# So the gate also looks for drift: a phrase sharing a locked term's modifier but
# ending in a different role noun. "Feature matrix" against a locked "feature
# representation" is a candidate second name; "feature selection" is not, because
# selection is not a thing the paper is naming.
TERM_ROLE_NOUNS = ("representation", "approach", "model", "matrix", "vector",
                   "method", "arm", "pipeline", "encoding", "framework", "scheme",
                   "predictor", "classifier", "embedding", "baseline", "variant")

# A one-off near-variant is usually ordinary English. A phrase used this many times is
# a name, whether or not anybody declared it one.
TERM_DRIFT_MIN_USES = int(os.environ.get("PAPER_TERM_DRIFT_MIN_USES", "2"))

# --- Gate thresholds ---------------------------------------------------------

# What fraction of the claims the paper plans to make must be backed by at least one
# frozen evidence item before drafting may start. Below this, the project parks and
# gathers more rather than drafting a paper on evidence it never assembled.
EVIDENCE_COVERAGE_MIN = float(os.environ.get("PAPER_EVIDENCE_COVERAGE_MIN", "0.85"))

# Numbers in prose are checked against the evidence ledger. A number that is not
# there is a blocking defect — this is the academic analogue of a canon breach, and
# it is the single most valuable gate in the project.
#
# Tolerance for a rounded restatement: 0.712 written as 0.71 is the same number.
# Expressed as a relative difference.
NUMBER_MATCH_TOLERANCE = float(os.environ.get("PAPER_NUMBER_TOLERANCE", "0.005"))

# Small integers, years, and section/figure/table numbers are not findings. Checking
# them produces noise and nothing else.
NUMBER_CHECK_MIN = float(os.environ.get("PAPER_NUMBER_CHECK_MIN", "0"))

# --- The editorial loop ------------------------------------------------------
#
# A section gets this many passes before the loop starts asking whether it is still
# improving. Three, because on measured trajectories the fourth pass rarely beat the
# third and the tenth was routinely worse than the fifth.
EDIT_MAX_PASSES = int(os.environ.get("PAPER_EDIT_MAX_PASSES", "3"))

# The absolute ceiling, however well it is converging.
EDIT_HARD_MAX_PASSES = int(os.environ.get("PAPER_EDIT_HARD_MAX_PASSES", "6"))

# How many recent passes have to beat the best count before them for the loop to
# count as still improving.
EDIT_STALL_PASSES = int(os.environ.get("PAPER_EDIT_STALL_PASSES", "2"))

# Structural repairs — a passage replaced wholesale rather than find/replaced — per
# pass. Capped because each one is new prose that nothing has read yet.
SURGERY_MAX_PER_PASS = int(os.environ.get("PAPER_SURGERY_MAX_PER_PASS", "2"))

# A replacement passage shorter than this fraction of what it replaced is a deletion
# wearing a rewrite's clothes. Refused.
SURGERY_MIN_RATIO = float(os.environ.get("PAPER_SURGERY_MIN_RATIO", "0.6"))

# How many whole-paper sweeps run after every section exists.
REVISION_SWEEPS = int(os.environ.get("PAPER_REVISION_SWEEPS", "2"))

# A draft on disk with at least this many words is resumed rather than re-rolled.
DRAFT_RESUME_MIN_WORDS = int(os.environ.get("PAPER_DRAFT_RESUME_MIN_WORDS", "120"))

# Continuation passes allowed on a section that came in under its floor.
DRAFT_MAX_CONTINUATIONS = int(os.environ.get("PAPER_DRAFT_MAX_CONTINUATIONS", "2"))

# --- The argument map --------------------------------------------------------

# Every claim must be placed in exactly one section, and every section must carry at
# least this many. A section with one claim is a paragraph.
SECTION_MIN_CLAIMS = int(os.environ.get("PAPER_SECTION_MIN_CLAIMS", "2"))

# --- The support ladder ------------------------------------------------------
#
# points -> claims -> evidence. `gates/ladder.py` checks the top join: that
# everything in the paper serves what the paper is for. These five numbers decide
# what "serves" is allowed to mean, so changing one changes what this harness will
# publish.

# How many points a paper may be about. One is the ordinary case and the degenerate
# case at once — the `headline` boolean this replaced was this gate with the count
# fixed at one. Two is common: a comparison, plus what the comparison rules out.
# Three is the most a reader carries out of the room. Four is the count at which the
# author has stopped choosing, and the manuscript that produced this gate had three
# stated objectives of which two were support for the first.
POINTS_MIN = int(os.environ.get("PAPER_POINTS_MIN", "1"))
POINTS_MAX = int(os.environ.get("PAPER_POINTS_MAX", "3"))

# A point stated in fewer words than this is a topic. "Representation comparison" is
# six characters short of being a heading; "the embedding does not outperform the
# feature vector" is a point. Six is the floor at which a sentence with a subject and
# a verb becomes possible.
POINT_MIN_WORDS = int(os.environ.get("PAPER_POINT_MIN_WORDS", "6"))

# Claims required to carry a point. A point served by one claim IS that claim, and
# promoting it promises the reader more than the paper delivers.
POINT_MIN_CLAIMS = int(os.environ.get("PAPER_POINT_MIN_CLAIMS", "2"))

# What share of claims may declare a `setup` or `reporting` role instead of serving a
# point. A paper cannot be all argument — the cohort has to be described before
# anything is claimed about it — but an unbounded exemption turns the ladder into
# decoration, and "setup" is the easiest label in the world to reach for. A third is
# generous for a clinical paper with a long Methods.
ROLE_CLAIM_SHARE_MAX = float(os.environ.get("PAPER_ROLE_CLAIM_SHARE_MAX", "0.34"))

# What share of the planned WORDS may sit in sections that serve no point. This is the
# check that catches the real failure, because a graph check only asks whether every
# claim has a parent and a determined writer satisfies that by attaching claims
# loosely. Length cannot be argued with. The warn threshold exists because this share
# grows quietly, one complete and irrelevant section at a time.
UNLADDERED_WORDS_WARN = float(os.environ.get("PAPER_UNLADDERED_WORDS_WARN", "0.15"))
UNLADDERED_WORDS_MAX = float(os.environ.get("PAPER_UNLADDERED_WORDS_MAX", "0.30"))

# The other half of the budget: how much of the paper ONE claim may consume.
#
# The unladdered budget above catches material attached to nothing. It does not catch
# material attached to something and then elaborated out of all proportion — a whole
# supplement section, with a rubric, two verbatim prompts, four worked examples and a
# re-judging experiment, in service of a single null result about a weighting scheme
# layered on a predictor the paper had already reported as not competitive. Every one
# of those words laddered. The section served a point. It was still four times the
# length its claim could carry.
#
# So a claim also has a ceiling. It WARNS rather than blocks, and the reason is worth
# stating: word share is a proxy for proportion, and a proxy that stalls a run is a
# proxy somebody raises until it stops firing. A headline claim legitimately owns a
# large share of a short paper. What the warning is for is the strand nobody decided
# to stop writing, surfaced where an author can look at it.
CLAIM_WORDS_WARN = float(os.environ.get("PAPER_CLAIM_WORDS_WARN", "0.25"))

# One case does block, because it is not a proxy for anything. A LIMITATION written at
# the length of a finding reads as a finding — the caveat stops qualifying the result
# and starts competing with it. A caveat is a paragraph. If it needs a section, it is
# not a caveat, and the honest repair is to promote it to a claim that serves a point
# or to cut it.
CLAIM_WORDS_MAX_MINOR = float(os.environ.get("PAPER_CLAIM_WORDS_MAX_MINOR", "0.12"))
CLAIM_MINOR_KINDS = ("limitation",)

# Paragraphs in a section that may advance no claim, as a share. A transition and a
# closing line are legitimate; a section of them is a section with no argument in it.
PARAGRAPH_ROLE_SHARE_MAX = float(
    os.environ.get("PAPER_PARAGRAPH_ROLE_SHARE_MAX", "0.34"))

# How many sections the argument stage plans per model call. A paper is small enough
# that this is usually the whole thing in one call; the chunking exists so a
# multi-paper project cannot produce an artifact too large to write in one turn.
ARGUMENT_CHUNK_SECTIONS = int(os.environ.get("PAPER_ARGUMENT_CHUNK_SECTIONS", "12"))

# --- Shipping ----------------------------------------------------------------
#
# Delivery puts the documents on disk. If that disk is a git working tree, the work is
# not anywhere until somebody commits it, and that is the step that gets forgotten for
# a week while the author believes the paper is filed. So the pipeline can finish the
# job — but pushing to a remote is the only outward-facing thing this harness does, so
# both halves are opt-in and the machinery is deliberately narrow. See
# `infra/shipping.py` for what it refuses and why.

# The git working tree to commit delivered papers into. Empty means never commit.
# Only files delivery actually wrote are staged, by path; there is no `git add -A`
# anywhere, because a daemon that swept the tree would eventually commit half of an
# unrelated edit under a message about a manuscript.
SHIP_REPO = _env_path("PAPER_SHIP_REPO", None) if os.environ.get("PAPER_SHIP_REPO") \
    else None

# Whether to push after committing. A separate switch from SHIP_REPO because a local
# commit is reversible by one command and a push is not.
SHIP_PUSH = _env_flag("PAPER_SHIP_PUSH", False)

# --- Building ----------------------------------------------------------------
#
# The manuscript is authored in Markdown and built to the format a journal actually
# accepts. Pandoc does the conversion; a reference .docx supplies the styles.
#
# **Why this is a search and not a string.** Pandoc is very often installed somewhere
# that is not on PATH — inside a conda distribution, inside an RStudio Server tree,
# inside a Quarto bundle. On the machine this harness was written on it lives in an
# Anaconda `bin/` whose `condabin/` is on PATH and whose `bin/` is not. Defaulting to
# the bare name "pandoc" then means conversion silently does not happen, the run
# reports success because the Markdown IS the deliverable, and the .docx beside it
# quietly goes stale. That is the worst of the three outcomes: not a failure, not a
# conversion, just an old file that still looks like an artifact.
#
# So the default resolves: PATH first, then the usual places, and only then the bare
# name, which at least produces a clear error. An explicit PAPER_PANDOC_BIN always
# wins and is never second-guessed.
_PANDOC_CANDIDATES = (
    "/opt/apps/easybuild/software/Anaconda3/2025.06-0/bin/pandoc",
    "/usr/lib/rstudio-server/bin/pandoc/pandoc",
    "/usr/lib/rstudio/bin/pandoc/pandoc",
    "/opt/quarto/bin/tools/pandoc",
    "/usr/local/bin/pandoc",
)


def _find_pandoc():
    explicit = os.environ.get("PAPER_PANDOC_BIN", "").strip()
    if explicit:
        return explicit
    found = shutil.which("pandoc")
    if found:
        return found
    for candidate in _PANDOC_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    for root in (os.environ.get("CONDA_PREFIX"), os.environ.get("CONDA_EXE")):
        if not root:
            continue
        base = Path(root)
        base = base.parent.parent if base.is_file() else base
        candidate = base / "bin" / "pandoc"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return "pandoc"


PANDOC_BIN = _find_pandoc()

# The output formats built for every finished paper, in order. Markdown is always
# kept — it is the source — so this is what is built FROM it.
BUILD_FORMATS = tuple(f.strip() for f in
                      os.environ.get("PAPER_BUILD_FORMATS", "docx").split(",")
                      if f.strip())

# A reference document supplying the journal's styles, if the project has one. The
# job prompt may name one per paper; this is the fallback.
_REFDOC_RAW = os.environ.get("PAPER_REFERENCE_DOCX", "").strip()
REFERENCE_DOCX = Path(_REFDOC_RAW).expanduser() if _REFDOC_RAW else None

# Whether a build failure blocks delivery. It does not: the Markdown IS the
# manuscript, and a missing pandoc must never be why a finished paper is not
# delivered.
BUILD_REQUIRED = _env_flag("PAPER_BUILD_REQUIRED", False)

# --- Stalling: what happens instead of failing -------------------------------
#
# Nothing in this harness has a terminal failure state. A unit that cannot advance
# stalls, and a stalled unit is retried on an escalating backoff, forever — because
# an API outage, an allowance ceiling, and a full disk all resolve on their own or
# when a person acts, and none of them is a reason to abandon a manuscript.
STALL_BACKOFF_BASE_SEC = int(os.environ.get("PAPER_STALL_BACKOFF_BASE_SEC", "300"))
STALL_BACKOFF_MAX_SEC = int(os.environ.get("PAPER_STALL_BACKOFF_MAX_SEC", "3600"))

# --- Retry caps --------------------------------------------------------------

# How many words of the previous section's closing prose the writer is shown, so the
# join between two sections reads as one document.
DIGEST_PREV_TAIL_WORDS = int(os.environ.get("PAPER_DIGEST_PREV_TAIL_WORDS", "300"))

# Infrastructure failures inside one section stage before the paper stalls.
SECTION_STAGE_ERROR_RETRIES = 3

# How many times a stage may re-propose after a GATE rejection. Distinct from the
# transient cap below: this counts a model that produced a real artifact the gates
# refused, which is judgement, not infrastructure.
GATE_MAX_ATTEMPTS = int(os.environ.get("PAPER_GATE_MAX_ATTEMPTS", "3"))

# Transient subprocess failures: a killed process, a dropped connection.
TRANSIENT_MAX_ATTEMPTS = 4
TRANSIENT_RETRY_BACKOFF_SEC = 20

# Substrings that identify a failure as transient rather than terminal.
TRANSIENT_SIGNATURES = (
    "connection reset", "connection refused", "connection aborted",
    "timed out", "timeout", "temporarily unavailable", "service unavailable",
    "bad gateway", "gateway timeout", "internal server error",
    "502", "503", "504", "econnreset", "etimedout", "socket hang up",
    "overloaded", "please try again", "stream closed", "broken pipe",
)

# Substrings that identify an allowance ceiling. Never a failure: the engine defers.
QUOTA_SIGNATURES = (
    "usage limit", "rate limit", "rate_limit", "quota", "429",
    "too many requests", "insufficient credit", "out of credit",
    "resource exhausted", "resource_exhausted",
)

# --- Budget gating -----------------------------------------------------------

# A JSON file the operator can edit to pause the harness or cap what it spends.
BUDGET_FILE = _env_path("PAPER_BUDGET_FILE", STATE_DIR / "budget.json")

# --- Loop cadence ------------------------------------------------------------

POLL_INTERVAL_SEC = 5      # brisk poll while any unit is active
IDLE_INTERVAL_SEC = 30     # slow poll when the inbox and journal are quiet

# --- Quiet hours: when the harness must not compete with its owner ------------
#
# Off by default here, unlike the novel factory this grew out of: a paper is a few
# hours of work rather than an overnight run, and an author waiting on a Methods
# section does not want it deferred until five o'clock.
QUIET_HOURS_ENABLED = _env_flag("PAPER_QUIET_HOURS", False)
QUIET_START_HOUR = int(os.environ.get("PAPER_QUIET_START_HOUR", "9"))
QUIET_END_HOUR = int(os.environ.get("PAPER_QUIET_END_HOUR", "17"))

QUIET_DAYS = tuple(
    int(d) for d in os.environ.get("PAPER_QUIET_DAYS", "0,1,2,3,4").split(",")
    if d.strip().isdigit())

QUIET_RECHECK_SEC = int(os.environ.get("PAPER_QUIET_RECHECK_SEC", "600"))
