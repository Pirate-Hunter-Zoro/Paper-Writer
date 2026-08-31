"""Every tunable in the fleet, in one module. No logic, no I/O.

The design is documented in full in README.md; this file is the knob panel, so
the stages stay declarative and a behaviour change is a one-line edit here (or an
environment variable, so a plist can override it without touching code).

Production runs only on the Mac mini — the only host with the logged-in `claude`
session, `launchd`, and the iCloud Books folder. The deterministic half is
developed and tested anywhere, which is why every runtime path is rooted at
STATE_DIR and STATE_DIR is env-overridable: pointing FANFIC_STATE_DIR at a temp
tree relocates the journal, canon, bibles, staging, and logs in one move.
"""

import os
from pathlib import Path

# --- Roots -------------------------------------------------------------------

# The repo. `fanfic/config.py` -> repo root is two levels up.
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


# --- The drop folder --------------------------------------------------------

# The iCloud Books folder: both where finished `.epub`s are delivered and where the
# drop folder lives. The `~` matters — this only resolves on the mini.
ICLOUD_BOOKS_DIR = _env_path(
    "FANFIC_BOOKS_DIR",
    Path("~/Library/Mobile Documents/com~apple~CloudDocs/Books").expanduser(),
)

# One filled prompt-template markdown file here is one job. Finished and failed
# prompts move into subfolders that are NOT re-scanned — the
# file-it-away-never-delete discipline the sibling repos use for sources.
#
# This lives *inside* iCloud on purpose: it makes the whole system controllable from
# a phone. Drop a prompt into Books/_inbox from the iOS Files app and the mini picks
# it up on its next cycle; the finished book lands back in the same Books folder. The
# repo holds no runtime input at all.
#
# `_inbox` cannot collide with a delivered fandom folder: delivery names those with
# `paths.slug`, which maps every non-alphanumeric run to a hyphen and strips leading
# ones, so a slug can never begin with an underscore.
INBOX_DIR = _env_path("FANFIC_INBOX_DIR", ICLOUD_BOOKS_DIR / "_inbox")
INBOX_FINISHED_DIR = INBOX_DIR / "finished"
INBOX_FAILED_DIR = INBOX_DIR / "failed"

# The fleet writes a human-readable status file into the drop folder so the folder
# answers "is it still working?" and not just "did it stop?". `_`-prefixed, so it is
# never mistaken for a job. Set FANFIC_STATUS_FILE empty to turn it off.
STATUS_FILENAME = os.environ.get("FANFIC_STATUS_FILE", "_STATUS.md")

# A prompt file is admitted only once it has been unchanged for this long. A file
# arriving over iCloud, or being written in place by an editor, can be observed
# mid-write; admitting a truncated prompt would freeze canon against half a brief.
INBOX_SETTLE_SEC = int(os.environ.get("FANFIC_INBOX_SETTLE_SEC", "10"))

# The engineered base prompt templates. Committed to git, and deliberately kept
# at the repo root rather than buried in the package: they are the single most
# important non-code artifacts in the project and get hand-edited.
PROMPTS_DIR = PROJECT_ROOT / "prompts"

# All runtime-generated state. Gitignored. Redirectable for testing.
STATE_DIR = _env_path("FANFIC_STATE_DIR", PROJECT_ROOT / "state")

# Hidden staging dirname used for every stage-then-atomic-rename. Dot-prefixed so
# no scanner (including iCloud's own sync) treats an in-flight artifact as
# committed state.
STAGING_DIRNAME = ".staging"

# --- Prose and judgment: Claude, and only Claude -----------------------------
#
# Every text call in this fleet goes to the same model. Research, planning, outlining,
# drafting, continuation, editing, bible merges, art direction, vision critique — one
# model, one prompt style, one set of habits to write against.
#
# This used to be a five-provider registry with a two-tier model split (Sonnet wrote,
# Opus judged) and a per-role routing table so the cheap roles could go to a cheap
# vendor. All of it is gone, and the argument for removing it is in
# `fanfic/providers/__init__.py`. The short version: the split gave every quality
# problem two suspects, the swappability was never exercised on a real book, and the
# roles that were routed away kept having to be routed back after the cheap tier cost
# a run — `art_direction` spent one choosing moments no image model could draw.
#
# Prose quality is the entire product. There is no volume argument that beats it.

# Which binary drives Claude. Headless, on the mini's logged-in session — the fleet
# holds no API key for text and never has.
CLI_BIN = os.environ.get("FANFIC_CLI_BIN",
                         os.environ.get("FANFIC_CLAUDE_BIN", "claude"))

# The model. One line, and it is the most consequential line in this file.
MODEL = os.environ.get("FANFIC_MODEL", "claude-opus-5")

# --- What that consumes ------------------------------------------------------
#
# $ per MILLION tokens, as (input, output). Consumed only by `fanfic/cost.py`, which
# projects what a book costs; nothing at runtime reads it.
#
# These are LIST PRICES, and on a seat you are not charged them (see
# `infra/budget.record_usage`) — so read them as a measure of allowance consumed, not
# as a bill. The fleet's only genuine bill used to be pictures, and pictures are free
# now too: they are drawn through a signed-in browser rather than a billed API.
#
# The table used to span eleven models across five vendors so the estimator could
# compare them. Comparing them was the thing this project stopped doing, so it holds
# the models it actually runs and the two neighbours worth knowing the price of when
# someone asks whether a cheaper one would do.
#
# Re-check before trusting a total — published rates move, and the point of the
# estimator is to be argued with rather than believed. Verified July-August 2026.
#   https://www.tldl.io/resources/llm-api-pricing
PRICES = {
    "claude-opus-5":      (5.00, 25.00),    # what this fleet runs
    "claude-fable-5":    (10.00, 50.00),
    "claude-opus-4-8":    (5.00, 25.00),
    "claude-sonnet-5":    (2.00, 10.00),
    "claude-haiku-4-5":   (1.00,  5.00),
}

# --- The role table: what each kind of work is allowed to spend ---------------
#
# One table instead of eight stages each hand-tuning `max_turns` and `timeout` at
# its own call site. That scatter is not hypothetical harm: drafting sat at
# `max_turns=8` — the smallest budget in the fleet against the largest artifact in
# the pipeline — for as long as the numbers were not written down next to each
# other. Seeing them in one column is what made it obvious.
#
#   max_turns agent turns
#   timeout   seconds for one call
#   tools     tool grant, smallest that does the job — this runs unattended with
#             permissions skipped, so a narrow grant is a narrow blast radius
#   oneshot   the role's whole input is INLINED in the prompt, so the model reads
#             nothing and writes the artifact in one call. This is the single largest
#             lever in the project — bigger than any model choice. An agentic CLI
#             re-sends the whole conversation, including every tool result, on every
#             turn, so a writer that opens the previous draft and lays a chapter down
#             in eight appends pays for that transcript eight times: ~227,000 input
#             tokens for a chapter, ~363,000 for a critique, both back-solved from
#             metered calls. Inlined and written once, the same work at the same model
#             is two or three turns. A one-shot role gets a Write-only tool grant,
#             because granting Read to a model told not to read is an invitation.
#
# There is no `tier` and no `provider` column any more. Every role runs on
# `MODEL` — see the block above, and `providers/__init__.py` for why.
TEXT_ROLES = {
    # Mines the source wikis. The only role that genuinely needs the live web, and the
    # only one that cannot be one-shot: its whole job is to go and find the input.
    # Eighty turns because it is reading a fandom wiki page by page.
    "research":     {"max_turns": 80, "timeout": 2400,
                     "tools": ("Read", "Write", "Grep", "WebSearch", "WebFetch")},
    # Pinning where every principal is when the book opens. It runs once per series
    # and everything downstream inherits it, and the failure it exists to prevent is a
    # wrong fact repeated on every page — a crossover shipped with two characters'
    # hats swapped the wrong way because nobody had written down what the finale did
    # to them.
    "anchoring":    {"max_turns": 24, "timeout": 2400,
                     "oneshot": True, "tools": ("Write",)},
    # The largest single artifact in the pipeline, and it overtook drafting when the
    # cast did. Fifty-two characters each carrying an appearance, a voice, costumes, a
    # palette and a sheet spec, plus a progression apiece and the antagonist list, is a
    # bigger document than a chapter — and at 12 turns it came back truncated mid-array
    # on a real run, which is not a proposal a gate can reject usefully, it is half a
    # file. The turn budget is not a length allowance (one Write carries the whole
    # document) but it is the headroom to finish that write and to correct it after a
    # rejection, and running out of it costs the entire planning stage.
    "planning":     {"max_turns": 40, "timeout": 3600,
                     "oneshot": True, "tools": ("Write",)},
    # Also grew with the book. Forty-five chapters of beat sheets, entry/exit states,
    # casts and continuity ids is the second-largest artifact in the pipeline now that
    # the chapter count is the story's decision rather than a fixed 37.
    "outlining":    {"max_turns": 30, "timeout": 3000,
                     "oneshot": True, "tools": ("Write",)},
    # Writes ~5,000 words: the largest artifact in the pipeline. The turn budget is
    # not a length allowance — one Write carries the whole chapter — it is headroom
    # for thinking before that write, plus slack so an epilogue turn is never what
    # decides whether a finished chapter counts.
    "drafting":     {"max_turns": 10, "timeout": 2400,
                     "oneshot": True, "tools": ("Write",)},
    # Finishing a chapter that stopped short. Its own role rather than a second use of
    # `drafting`, because it is a different job with a different input — it carries the
    # prose so far and the outstanding beats — and because a stage should name what
    # kind of work it is doing. Separately tunable, and separately visible in the cost
    # breakdown, where it turned out to be most of a call per attempt.
    "continuation": {"max_turns": 10, "timeout": 2400,
                     "oneshot": True, "tools": ("Write",)},
    # The editorial pass: reads a whole chapter against the whole bible and writes
    # back every defect WITH its exact repair. The most leveraged call in the
    # pipeline, because it is not only deciding what is wrong, it is writing the
    # correction that gets applied verbatim.
    "editing":      {"max_turns": 10, "timeout": 1800,
                     "oneshot": True, "tools": ("Write",)},
    # Schema extraction from prose that is already in the prompt. Mechanical, and
    # structurally validated afterwards by `memory.bible.merge_bible_update`, so a bad
    # proposal here costs a revision at worst, never a corrupt ledger.
    "bible_merge":  {"max_turns": 6, "timeout": 900,
                     "oneshot": True, "tools": ("Write",)},
    # Chooses which moments get drawn, and writes the sentence the image model is
    # handed. This role is the reason the tier split is gone: routed to a cheap model
    # it picked moments like "three girls with glowing scars facing three strangers" —
    # a six-figure standoff no image model renders — and every render of it was
    # rejected and then skipped, so the saving bought empty slots. Choosing a
    # *renderable* moment is a craft judgement about composition, not a summarisation
    # task.
    "art_direction": {"max_turns": 8, "timeout": 600,
                      "oneshot": True, "tools": ("Write",)},
    # The one role that must genuinely open a file: the image it is judging, plus the
    # reference pictures the generator was given. Not one-shot for that reason.
    #
    # Twenty turns, not six. Six was not enough: it read the PNG, thought, and hit
    # `error_max_turns` at seven, which the harness counted as a render failure and
    # skipped images that were fine.
    "vision":       {"max_turns": 20, "timeout": 420,
                     "tools": ("Read", "Write")},
}

# Extra PATH entries prepended for subprocess model calls on the mini.
EXTRA_PATH = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]

# --- Images: Gemini, through a signed-in browser ------------------------------
#
# THERE IS NO IMAGE API KEY IN THIS PROJECT, and its absence is a decision rather
# than an omission.
#
# The original build called the Gemini Images API over HTTPS on a billed key. It
# worked — a PNG came back every time — and the pictures were the weakest part of the
# finished books: samey between renders, flat, and often enough distracting enough
# that a chapter read better with the slot empty. The same model, asked the same
# thing at gemini.google.com, does not have that problem. That is not a prompt
# difference and not a model difference; it is the difference between a bare endpoint
# and the product built around it.
#
# So the fleet drives the product. `tools/gemini_art.js` opens Chrome on a profile a
# human signed in to once, asks for the picture, waits for it, and saves it. What
# that buys: better art, no credential on disk, and no bill at all — pictures were the
# only real money this fleet spent.

# Whether the illustration stage runs at all. FANFIC_IMAGES_ENABLED=0 builds a
# deliberate TEXT-ONLY book: the engine logs the choice loudly and skips straight
# to ILLUSTRATED, so the full research->plan->outline->draft->bind->deliver
# pipeline still produces a valid image-free `.epub`. That is an explicit, logged
# decision — distinct from a render that will not come out, which is never skipped:
# it parks and is retried a rung plainer until it lands.
IMAGES_ENABLED = _env_flag("FANFIC_IMAGES_ENABLED", True)

# The Chrome profile holding the signed-in Gemini session. This directory IS the
# credential: it is created and signed in by `scripts/gemini-login.sh`, it belongs to
# the person whose account it is, and it is not this repo's business beyond knowing
# where it lives. Absent => the illustration stage says so by name and names the
# script that fixes it, rather than failing obscurely on the first render.
#
# Deliberately NOT your everyday Chrome profile: the fleet must not be logged out by
# something you do in your own browser, and your own browsing must not be visible to
# a headless process running unattended at 3 a.m.
GEMINI_PROFILE_DIR = _env_path("FANFIC_GEMINI_PROFILE_DIR",
                               Path.home() / ".config" / "fanfic" / "chrome-gemini")

# The browser and the runtime that drives it.
CHROME_BIN = os.environ.get(
    "FANFIC_CHROME_BIN",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
NODE_BIN = os.environ.get("FANFIC_NODE_BIN", "node")

# Headless by default; set to 1 to watch a render happen in a visible window. That is
# not a curiosity — it is the only way to debug a selector Google has moved, and the
# driver's selectors are guesses about somebody else's markup by construction.
IMAGE_HEADFUL = _env_flag("FANFIC_IMAGE_HEADFUL", False)

# Where a failed render dumps a screenshot and the page text. "No image appeared" is
# unfixable without seeing what did appear, and a headless failure at 3 a.m. leaves no
# other trace at all.
#
# Set the variable to an empty string to turn it off — which `_env_path` cannot express,
# because it treats empty as unset and hands back the default. That distinction matters
# for exactly one kind of tunable: the ones where "off" is a real choice rather than the
# absence of one.
_diag_raw = os.environ.get("FANFIC_IMAGE_DIAG_DIR")
IMAGE_DIAG_DIR = (STATE_DIR / "image-diagnostics" if _diag_raw is None
                  else (Path(_diag_raw).expanduser() if _diag_raw.strip() else None))

# How long one render may take, end to end, inside the browser. Generous: a picture
# through the web app takes anywhere from eight seconds to two minutes depending on
# what the account is queued behind, and a timeout that bites early throws away a
# render that was about to arrive.
IMAGE_RENDER_TIMEOUT_SEC = int(
    os.environ.get("FANFIC_IMAGE_RENDER_TIMEOUT_SEC", "420"))

# Extra seconds the Python side waits past the driver's own deadline before killing
# it. The driver kills its own Chrome on the way out; this is the outer stop for a
# browser that hung so hard it never got there.
IMAGE_DRIVER_GRACE_SEC = 60

# How many reference pictures may be attached to one render. References compete for a
# fixed budget of the model's attention, and a chat window is slower to upload to than
# an API was, so this is both a quality and a wall-clock number.
IMAGE_MAX_UPLOADS = int(os.environ.get("FANFIC_IMAGE_MAX_UPLOADS", "6"))

# The sanity floor: what a downloaded file must clear to count as art at all.
#
# This is NOT "is it a good picture" — that is the vision critic's job, with the
# reference art in front of it. It is the far dumber question a browser makes newly
# necessary, because a page can hand you a spinner, a placeholder or a 404 body and
# all three are <img>-shaped. Cheap to check here, and a Claude call is not.
IMAGE_MIN_BYTES = int(os.environ.get("FANFIC_IMAGE_MIN_BYTES", "20000"))
IMAGE_MIN_EDGE = int(os.environ.get("FANFIC_IMAGE_MIN_EDGE", "512"))

# Aspect ratios requested per scene orientation. Asked for in words now rather than as
# an API parameter — see `providers.image_browser._instruction`.
IMAGE_ASPECT_PORTRAIT = os.environ.get("FANFIC_IMAGE_ASPECT_PORTRAIT", "2:3")
IMAGE_ASPECT_LANDSCAPE = os.environ.get("FANFIC_IMAGE_ASPECT_LANDSCAPE", "3:2")

# The fixed art-style block stamped on EVERY image prompt so the whole book reads
# as one artist's work. This is the *style* half of visual consistency; the locked
# per-character appearance from the series bible is the *identity* half.
IMAGE_STYLE = os.environ.get(
    "FANFIC_IMAGE_STYLE",
    "Vibrant cel-shaded anime/manga illustration in the style of the source "
    "material; dynamic composition, dramatic rim lighting and atmosphere, a "
    "high-contrast complementary colour palette, detailed particle and lighting "
    "effects, clean confident lineart over painterly backgrounds.")

# The CEILING on scene illustrations per chapter. Not a count.
#
# How many pictures a chapter gets is how many times it changes scene: the writer marks
# every change of place or time, and each of those segments is one setting, gets one
# picture, and carries one of the character collisions the chapter owes. One segment,
# one moment, one image. A chapter that moves four times gets four pictures and a
# chapter that stays in one room gets one, which is the right answer in both cases and
# is not a number anybody has to choose.
#
# What this constant does is stop that from being unbounded. The real per-chapter limit
# is tighter still and is *derived* rather than configured — remaining picture budget
# divided by the book's actual chapter count, see `engine.illustrating.images_per_chapter`
# — because freeing the chapter count means chapter count now divides the picture bill
# instead of multiplying it.
IMAGES_PER_CHAPTER = int(os.environ.get("FANFIC_IMAGES_PER_CHAPTER", "6"))

# A ceiling on named characters per illustration, and it is a BACKSTOP rather than a
# style rule — set high enough that an ensemble scene is allowed.
#
# It was three for about an hour, and three was the wrong answer to the right
# observation. Multi-character renders really were failing: merged figures, lost
# costumes, a limb from nowhere. But they were failing because **no reference sheets
# existed** — every face in every scene was being invented from a text description,
# and inventing six consistent faces from prose is a thing no image model does. The
# cap was a workaround for a pipeline that had its central mechanism switched off.
#
# With the sheets actually attached as reference inputs, cast size is what the
# reference path is *for*. An eight-hander is still harder than a two-hander, so the
# art director is told to compose for it — a clear foreground pair, the rest as
# midground shapes — but a crossover whose whole appeal is everyone in one room does
# not get told it may only draw three of them.
IMAGE_MAX_CHARACTERS = int(os.environ.get("FANFIC_IMAGE_MAX_CHARACTERS", "6"))

# How many pictures of the source material's own art to keep per character, and how
# many of them to hand a single render.
#
# Real reference art is the strongest anchor available and it is not close. A locked
# prose description gets identity roughly right and proportion consistently wrong —
# seventeen-year-old twins came out as a young adult and a child from the same two
# sentences, because there is no wording for "this exact jaw" and the more words you
# spend the more the model averages. A picture settles the face, the proportions, the
# age and the silhouette at once.
#
# Two per render rather than all of them: references compete, and a scene already
# carries one per character plus the locked sheet.
REF_IMAGES_PER_CHARACTER = int(os.environ.get("FANFIC_REF_IMAGES", "4"))
REF_IMAGES_PER_RENDER = int(os.environ.get("FANFIC_REF_IMAGES_PER_RENDER", "2"))

# How many characters in a frame get the full reference set. Everyone else is anchored
# by their locked sheet alone.
#
# A model has one budget of attention to divide across its references, so fidelity per
# face falls as their number rises: a four-character scene sending twelve pictures makes
# all four faces worse, not one of them better. The characters hurt most are the ones
# who need references most — the ordinary-looking humans, whose identity lives in a face
# rather than in a silhouette. Measured on the first book: Bow, Dipper and Raine came
# out right in crowded frames on costume alone, while Soos, Anne, Perfuma and Pacifica
# came out as strangers in the same pictures.
#
# Two, because the art director is already required to compose with one or two people in
# front and the rest staged behind. This is the renderer agreeing with the composition
# instead of flattening it: the foreground is identified by looking like itself, and the
# background by being where the scene puts it.
IMAGE_REFERENCE_CHARACTERS = int(
    os.environ.get("FANFIC_IMAGE_REFERENCE_CHARACTERS", "2"))

# How far down the image queue a worker looks for something it can actually draw.
#
# A scene defers when its cast has no locked reference sheet yet, which is a normal
# and temporary state — but a worker that only ever looks at the head of the queue
# turns one permanently-deferred entry into a total stop. That happened: a scene
# naming "Ford Pines" against a bible filed under "Stanford Pines" could never
# resolve, and the drainer sat on it every five seconds while everything behind it
# waited.
IMAGE_QUEUE_SCAN = int(os.environ.get("FANFIC_IMAGE_QUEUE_SCAN", "25"))

# The ceiling on how many renders one series may spend. Empty disables it.
#
# THIS USED TO BE A DOLLAR FIGURE, and it no longer can be: pictures are drawn through
# a signed-in browser session, so they cost nothing but time. What survives is the
# thing the ceiling was actually for — a runaway stop. A slot that keeps failing costs
# renders, a book has hundreds of slots, and an unbounded fleet on a bad night can
# spend a day of wall-clock producing nothing.
#
# WHAT THIS CEILING COSTS WHEN IT BITES IS TIME, NOT PICTURES. It used to skip the
# slot and let the epub omit it, which made a low ceiling a quality setting nobody had
# agreed to. A missing picture is not an outcome any more, so hitting this holds the
# book in ILLUSTRATING with every slot still queued; raising it resumes the run by
# itself, with no re-drop and nothing lost.
#
# Sized from what a book actually is: ~48 chapters at the ~5 scene segments the first
# nine delivered is ~240 scene slots, plus a sheet for each of a 54-strong crossover
# cast, plus a cover — call it ~300 slots. Renders per slot is the part no estimate
# can know in advance, because the vision critic rejects some, so budget two. 600 is
# that, and 800 is that with headroom.
_IMAGE_BUDGET_RAW = os.environ.get("FANFIC_IMAGE_RENDER_BUDGET", "800").strip()
IMAGE_RENDER_BUDGET = int(_IMAGE_BUDGET_RAW) if _IMAGE_BUDGET_RAW else None

# How many renders one visit to a slot may spend before the slot is parked and its
# turn passes to the next one. It is a PACING number, not a give-up count: the slot
# resumes at the rung it reached, so three here means "three tries, then let somebody
# else have the workers for a while", never "three tries, then a hole in the book".
IMAGE_MAX_REGENERATIONS = 3

# How long a parked image slot waits before its next attempt, doubling per visit to a
# one-hour ceiling — the same shape as STALL_BACKOFF, and for the same reason. A slot
# the vendor is refusing outright must not be retried in a hot loop, and one blocked
# by something a person fixes tomorrow has to resume without being asked.
IMAGE_RETRY_BACKOFF_BASE_SEC = int(
    os.environ.get("FANFIC_IMAGE_RETRY_BACKOFF_BASE_SEC", "300"))
IMAGE_RETRY_BACKOFF_MAX_SEC = int(
    os.environ.get("FANFIC_IMAGE_RETRY_BACKOFF_MAX_SEC", "3600"))

# Each ILLUSTRATING cycle renders at most this many, then yields, so the engine stays
# responsive and paces against rate limits instead of hammering.
IMAGES_PER_CYCLE = int(os.environ.get("FANFIC_IMAGES_PER_CYCLE", "4"))

# When Gemini rate-limits the session, the book stays in ILLUSTRATING and the engine
# naps this long before retrying. A throttled account just means images trickle in;
# writing never waits, because writing is a different service entirely.
IMAGE_QUOTA_BACKOFF_SEC = int(os.environ.get("FANFIC_IMAGE_QUOTA_BACKOFF_SEC", "120"))

# How long to idle after the *model* backend reports any allowance ceiling, then try
# again — forever, until it lifts. Five minutes rather than the half hour this started
# at, because the ceiling might be a five-hour session cap or a monthly spend cap and
# the engine cannot tell which: a rejected call costs about two seconds, so re-checking
# every five minutes is free, recovers a session cap almost as soon as it resets, and
# still amounts to nothing over a multi-day wait for an administrator. There is no
# attempt limit here on purpose — a ceiling is never a failure, only a wait.
MODEL_QUOTA_BACKOFF_SEC = int(os.environ.get("FANFIC_MODEL_QUOTA_BACKOFF_SEC", "300"))

# --- Length and readability targets ------------------------------------------

# FLOORS, NOT TARGETS. This is the correction, and it is about quality rather than
# cost.
#
# The book used to be specified at ~198,000 words over 37 chapters — Deathly Hallows'
# shape — and that number reached the writer as a per-chapter target the length gate
# then enforced. The gate worked. It worked toward a number that made the prose worse,
# which is the actual problem: asked for 5,351 words the writer reliably returns about
# 2,681 good ones, so the gate fired constantly and triggered a continuation pass to
# make up the difference — and for a model that has already finished the story it
# planned to tell, the cheapest available padding is **interior monologue**. A
# character reflecting on what she just said. The word target did not merely fail to
# produce depth; it manufactured the exact prose the operator read the book and called
# boring.
#
# Do not restore a target here, and do not justify this change as a saving. It is not
# one: continuation was 60 calls and $15.73 of a $1,003 run, 1.6%, measured from
# `state/usage.jsonl` rather than reasoned about. The argument is the prose.
#
# What is left is the floor beneath which the thing is not what was asked for. A
# novella is not a novel and a scene is not a chapter, so those two have numbers.
# Everything above them is the story's business.
BOOK_MIN_WORDS = int(os.environ.get("FANFIC_BOOK_MIN_WORDS", "150000"))

# The outliner picks the chapter count the story needs. This is only the floor that
# stops "as long as it needs to be" from becoming a novella.
MIN_CHAPTERS = int(os.environ.get("FANFIC_MIN_CHAPTERS", "32"))

# The readability gate — HARD, deterministic, computed in code, not a model
# opinion. A chapter's Flesch–Kincaid grade must sit inside this band and its
# reading ease at or above the floor. Deathly Hallows lands near grade 6 / ease
# ~75; the band is a little wider than one book so honest chapter-to-chapter
# variation is not punished, while a chapter that drifts into dense literary prose
# or into baby-talk is caught.
# --- Scene segments ----------------------------------------------------------
#
# The writer marks every change of place or time with a break line, and the segments
# between those marks are the unit for everything per-scene: which moments get drawn,
# where each picture is placed in the epub, which interaction lands where.
#
# Two is a floor on the *mechanism*, not on the storytelling. How often a chapter
# moves is a story decision; whether it says so is not. Zero means the writer did not
# mark the chapter up at all, and every per-scene stage then silently degrades to
# treating a whole chapter as one moment — which is what put five settings and no
# separators into chapter 1, and its illustrations into a stack at the end.
CHAPTER_MIN_SEGMENTS = int(os.environ.get("FANFIC_CHAPTER_MIN_SEGMENTS", "2"))

READABILITY_FK_GRADE_MIN = 4.0
READABILITY_FK_GRADE_MAX = 7.5
READABILITY_FLESCH_EASE_MIN = 68.0

# The length gate: an absolute floor, in words, and nothing else.
#
# It was a ratio against a per-chapter target, which meant the gate's verdict moved
# whenever the plan's word budget or the chapter count moved — and a chapter's real
# defect has nothing to do with either. Short is still the failure nothing else can
# see: a 1,400-word chapter can be perfect on canon, clean on continuity, and dead
# centre of the readability band. But 3,000 words is a chapter and 1,400 is a scene,
# and that is true whatever the book around it is doing.
#
# Only the floor blocks, and now there is no ceiling at all — not even an advisory one.
# A chapter that runs long is a chapter.
CHAPTER_MIN_WORDS = int(os.environ.get("FANFIC_CHAPTER_MIN_WORDS", "3000"))


# --- Gate thresholds ---------------------------------------------------------

# Research must cite facts covering at least this fraction of the entities the
# prompt implies before drafting may begin. Thin coverage parks the job rather
# than drafting on sand.
CANON_COVERAGE_MIN = 0.85

# --- The editorial loop ------------------------------------------------------

# How many editorial passes a chapter gets by default. A pass is ONE model call that
# both finds the defects and writes their exact repairs; the harness applies them.
#
# Three is sized from what the passes do rather than from taste. Pass 1 finds
# essentially everything a first draft is carrying and repairs it. Pass 2 exists
# because an edit can be wrong — a changed duration whose other mention was missed, a
# deleted clause that leaves a dangling pronoun — and it is the pass that verifies the
# first one's work against the whole chapter. Pass 3 is slack. Beyond that a pass is
# buying a fresh set of opinions about prose that is no longer defective, which is not
# the same thing as a better book.
#
# The number this replaces was 6 revisions with a hard ceiling of 12, and chapters
# routinely spent all of them: 24 attempts on chapter 8, 18 on chapter 14, at roughly
# $1.75 a round. That budget was not buying quality, it was paying for the drift a
# rewrite introduces — the counts random-walked (2 -> 10 -> 6 -> 14) rather than
# falling. With repairs anchored the counts fall monotonically and the budget stops
# being the binding constraint.
EDIT_MAX_PASSES = int(os.environ.get("FANFIC_EDIT_MAX_PASSES", "3"))

# ...but a chapter still shedding defects at the soft cap gets more passes, up to this
# ceiling. The soft cap exists to stop paying for a loop that has stopped working; it
# must never be the thing that cuts off one that is working. Cast size is what drives
# this in a crossover — chapter 14 carries twelve characters and needs longer than a
# two-hander — and a fixed count cannot tell the difference.
EDIT_HARD_MAX_PASSES = int(os.environ.get("FANFIC_EDIT_HARD_MAX_PASSES", "6"))

# How many consecutive passes may fail to beat the best blocking count before the
# chapter is judged to have stopped improving. Two, because with anchored repairs a
# flat pass is already unusual — the count only fails to fall when the editor could not
# anchor something, and that does not un-stick itself by being asked again.
EDIT_STALL_PASSES = int(os.environ.get("FANFIC_EDIT_STALL_PASSES", "2"))

# How many of a chapter's longest sentences are quoted to the editor when the
# readability gate fails.
#
# Readability is the one gate whose failure is not located anywhere: Flesch-Kincaid is
# a function of every sentence, so "too dense" cannot be anchored the way a
# contradiction can, and it used to be the one defect that ordered a full rewrite. But
# the score is driven by only two quantities and one of them — words per sentence — is
# a property of specific sentences the harness can compute and quote. Fifteen turns an
# un-anchorable gate into fifteen ordinary anchored edits.
EDIT_LONG_SENTENCES = int(os.environ.get("FANFIC_EDIT_LONG_SENTENCES", "15"))

# How many anchored passages one pass may replace wholesale via scene surgery.
#
# Surgery is the only mechanism in the pipeline that generates prose no editor has seen,
# so it is rationed. An editor returning six structural entries has almost certainly
# mistaken "I would have written this differently" for "this scene does not exist".
SURGERY_MAX_PER_PASS = int(os.environ.get("FANFIC_SURGERY_MAX_PER_PASS", "2"))

# A surgical replacement shorter than this fraction of what it replaces is refused.
# The failure mode being guarded is the writer summarising instead of dramatising:
# splicing that in would delete prose the editor never asked to lose, and the usual
# reason for surgery is that something was summarised in the first place.
SURGERY_MIN_RATIO = float(os.environ.get("FANFIC_SURGERY_MIN_RATIO", "0.6"))

# How many times the book's REVISING sweep may revisit a chapter that shipped holding
# issues. The sweep re-edits against the whole finished book, which is information the
# per-chapter loop could not have had.
REVISION_SWEEPS = int(os.environ.get("FANFIC_REVISION_SWEEPS", "2"))

# A draft already on disk for a chapter the journal says is mid-flight is reused rather
# than re-rolled, provided it has at least this many words. Restarting the fleet during
# a chapter used to discard five thousand words and about a dollar of allowance for no
# reason, since the file was sitting right there and nothing had rejected it.
DRAFT_RESUME_MIN_WORDS = int(os.environ.get("FANFIC_DRAFT_RESUME_MIN_WORDS", "500"))

# --- The meta plan: who is in a room with whom, chapter by chapter -----------
#
# The interaction ledger used to live in the series plan and be sized against the cast:
# `min(cast-1, max(8, cast//2))`, which for a cast of 26 is 13. The model produced 23,
# spread across 37 chapters, and that left **14 chapters owing nothing to anybody**.
# Chapter 1 was one of them: six people at a dinner table and one of them talked.
#
# The floor was sized to the CAST when the thing it has to cover is the BOOK. Every
# chapter needs its collisions, so the ledger is now built chapter by chapter and comes
# out an order of magnitude larger — at ~45 chapters and 4 a chapter, ~180 entries.

# One interaction per scene segment, and a chapter is four or five segments. That
# equality is the whole design: one segment = one setting = one interaction = one
# image. Chapter 1's dinner failed all three at once.
META_INTERACTIONS_MIN = int(os.environ.get("FANFIC_META_INTERACTIONS_MIN", "4"))
META_INTERACTIONS_MAX = int(os.environ.get("FANFIC_META_INTERACTIONS_MAX", "5"))

# How many chapters one meta-plan call produces.
#
# Ten, because one call will not produce 180 entries. This is the same measurement that
# governs the length floor: a model asked for a large artifact in one call returns
# about a third of it and declares victory. So the meta plan is built in chunks, each
# call shown everything already committed and where the coverage still falls short —
# propose, validate, apply, journal, next chunk, exactly like every other stage.
META_CHUNK_CHAPTERS = int(os.environ.get("FANFIC_META_CHUNK_CHAPTERS", "10"))

# Nobody is a guest star. With ~180 interactions over 52 characters, six appearances is
# a low bar that a character who exists at all will clear, and a bar that catches the
# one the plan quietly forgot — which is the failure this replaces, where a listed
# character could go the whole book without a scene anybody asked for.
PLAN_MIN_APPEARANCES = int(os.environ.get("FANFIC_PLAN_MIN_APPEARANCES", "6"))

# What fraction of interactions must cross universes.
#
# Nothing has ever checked this, and chapter 1 was 100% Owl House. A crossover in which
# most scenes are one cast talking to itself is four books sharing a setting. Sixty
# percent leaves real room for within-cast scenes — those are needed too, and the
# Pines twins do not stop being the Pines twins — while making the crossing the norm
# rather than the exception.
META_CROSS_UNIVERSE_SHARE = float(
    os.environ.get("FANFIC_META_CROSS_UNIVERSE_SHARE", "0.60"))

# Every pairing of source worlds gets a real share rather than one token scene. As a
# fraction of all interactions: with four universes there are six pairings, so an even
# split of the cross-universe 60% would be 10% each; 4% is a floor well under that,
# which allows the book to favour the pairings its plot is actually about without
# letting any of the six be a footnote.
META_MIN_PAIRING_SHARE = float(
    os.environ.get("FANFIC_META_MIN_PAIRING_SHARE", "0.04"))

# How much of the book is scenes where something physically happens, and how that is
# distributed across it.
#
# Every other meta-plan gate counts who is in a room. None of them counts what the room
# is for, and the consequence is measured rather than theorised: the previous book
# cleared all of them and came out with roughly two physical verbs per chapter across
# its first forty chapters, because a model optimises for what is checked and nothing
# checked this.
#
# Three numbers instead of one, and that is the design. A single whole-book floor is
# satisfied by a book that talks for forty chapters and fights for eight — which is the
# book being replaced. The front-half floor is what buys action early; the back-half
# floor is what buys escalation; the whole-book floor stops both halves sitting exactly
# on their minimums.
META_MIN_PHYSICAL_SHARE = float(
    os.environ.get("FANFIC_META_MIN_PHYSICAL_SHARE", "0.30"))
META_FRONT_PHYSICAL_SHARE = float(
    os.environ.get("FANFIC_META_FRONT_PHYSICAL_SHARE", "0.20"))
META_BACK_PHYSICAL_SHARE = float(
    os.environ.get("FANFIC_META_BACK_PHYSICAL_SHARE", "0.45"))

# No single register may exceed this share. The failure it prevents is the mirror of
# the one above: a ledger that is 80% `physical` is as broken as one that is 80%
# conversation, and a crossover whose every scene is the same kind of scene has one
# joke in it.
META_REGISTER_CEILING = float(
    os.environ.get("FANFIC_META_REGISTER_CEILING", "0.50"))

# How many times ONE exact grouping of characters may share a scene across a book.
#
# This was effectively 1 — an absolute uniqueness rule — and it is the only gate in the
# project that has ever made a book unplannable rather than merely rejecting a bad
# proposal. The reasoning was sound and the arithmetic was not: it was written for a
# 52-character crossover, where the supply of sensible groupings is enormous. Run
# against an 18-character novelization with a fixed core party, the supply runs out.
#
# Measured, on the real Star Wars book: 30 chapters and 148 interactions were planned
# with every grouping unique, and then chapter 31-40 failed three times in a row. Every
# failure was the protagonist plus one or two of the same small pool of Jedi Masters —
# the scenes the *source* is made of. The model was not being lazy; there was no
# unused, sensible combination left to give it.
#
# A cap keeps what the rule was for. What it was protecting against is a ledger that is
# the same four people over and over, and three occurrences of one grouping across two
# hundred scenes is not that. What it was costing was the core cast of a novelization
# being forbidden from meeting twice.
META_SUBSET_MAX_REPEATS = int(
    os.environ.get("FANFIC_META_SUBSET_MAX_REPEATS", "3"))

# And the other half of the same intent, checked over the finished ledger: MOST scenes
# must still be a fresh combination. The cap alone permits monotony in principle — 200
# interactions could be 67 groupings used three times each — so this is the floor that
# says a book is mostly new pairings rather than a rotation.
META_DISTINCT_GROUP_SHARE = float(
    os.environ.get("FANFIC_META_DISTINCT_GROUP_SHARE", "0.60"))

# --- Stalling: what happens instead of failing -------------------------------

# A unit that hits something it cannot get past waits this long before its first
# retry, and twice as long before each retry after that, capped. It is never
# abandoned.
#
# There is no terminal failure state in this machine any more. The argument for one was
# real — a deterministic failure retried in a hot loop burns allowance to learn the same
# thing repeatedly — and the conclusion was wrong, because it treated "retry
# immediately, forever" as the only alternative to quitting. Five minutes, then ten,
# then twenty, up to an hour, costs approximately nothing and means a provider outage,
# an allowance ceiling, or a bug somebody fixes tomorrow all resume by themselves.
STALL_BACKOFF_BASE_SEC = int(os.environ.get("FANFIC_STALL_BACKOFF_BASE_SEC", "300"))
STALL_BACKOFF_MAX_SEC = int(os.environ.get("FANFIC_STALL_BACKOFF_MAX_SEC", "3600"))

# --- Retry caps --------------------------------------------------------------

# How many words of the previous *accepted* chapter's closing prose go into the next
# chapter's writing brief. The outline's exit_state records what became true; it does
# not record that the heroine was last seen running up a canyon to tell someone. That
# gap parked chapter 4: it opened three days later with the errand silently done, and
# the continuity guardian — which reads the real chapter — kept objecting to a handoff
# the writer had never been shown. Enough to carry the closing scene, not so much that
# the writer starts pastiching the previous chapter's sentences.
DIGEST_PREV_TAIL_WORDS = int(os.environ.get("FANFIC_DIGEST_PREV_TAIL_WORDS", "400"))

# How many continuation passes may grow a short first draft.
#
# Measured, not guessed: asked for a 5,351-word chapter in one call, the writer
# produced 2,681 good words — dead centre of the readability band, and exactly half a
# book. That is not a bad prompt, it is what one completion does. A chapter this long
# is three or four scenes and gets written a scene at a time.
#
# Without this the length gate turns into the most expensive failure in the pipeline:
# every chapter burns its whole revision budget being told it is short, while the
# revision brief simultaneously orders it to change nothing that was not objected to.
#
# Two passes covers 2x-3x growth, which is the observed shortfall with headroom. Each
# pass is a cheap call against a prompt that is mostly prose already written.
DRAFT_MAX_CONTINUATIONS = int(os.environ.get("FANFIC_DRAFT_MAX_CONTINUATIONS", "2"))

# How many times a chapter's draft/critique stage may error out before the chapter
# parks. Separate from the revision budget on purpose: a flaky stage must not spend
# the writer's chances to actually improve the prose.
CHAPTER_STAGE_ERROR_RETRIES = 3



# How many times planning and outlining may re-propose after a deterministic gate
# rejects them, with the validator's complaints handed back.
#
# Both stages face strict structural gates — a plan needs an appearance and a voice for
# every character; an outline needs contiguous numbering, a monotonic timeline, no
# orphaned thread and no payoff without a prior setup, across all 37 chapters — and both
# used to get exactly one attempt, with a rejection parking the whole series. That is
# the chapter loop's original mistake at series scale: a proposer never shown its
# rejection cannot correct it, which leaves only a gate loose enough to always pass or a
# coin flip on a novel.
#
# Three, and deliberately not more. These failures are mechanical, so a model told about
# them fixes them on the next pass; a proposal that fails three times WITH the errors in
# hand is failing for a reason another roll will not reach, and the park is then worth
# reading rather than worth retrying.
GATE_MAX_ATTEMPTS = int(os.environ.get("FANFIC_GATE_MAX_ATTEMPTS", "3"))

# Transient failures retry with backoff up to this cap; a deterministic failure is
# terminal and is NOT retried.
TRANSIENT_MAX_ATTEMPTS = 4
TRANSIENT_RETRY_BACKOFF_SEC = 20

# Substrings that mark a model/CLI failure as a transient mid-stream blip
# (retryable) rather than a deterministic bad proposal (terminal).
#
# "connection closed" earns its place the hard way: on 2026-08-04 a ten-minute
# research call died with "API Error: Connection closed mid-response", which this
# list did not match, so a retryable blip parked the whole series as FAILED.
TRANSIENT_SIGNATURES = (
    "timeout", "timed out", "connection reset", "connection error",
    "connection closed", "connection aborted", "mid-response",
    "server disconnected", "eof occurred", "temporarily unavailable",
    "rate limit", "429", "502", "503", "504", "overloaded",
    "stream closed", "broken pipe",
)

# Substrings marking a model call as blocked by SPEND OR QUOTA rather than broken.
# These raise QuotaExceeded — "come back later" — instead of parking the unit, because
# a billing ceiling is not a wrong proposal and no amount of retrying is the fix.
#
# Earned 2026-08-05, six chapters into the first real novel: the CLI returned "You've
# hit your org's monthly spend limit" and, because that was just another RuntimeError,
# chapter 6 burned all four stage-error retries in NINE SECONDS and parked the book.
# The project already had the right failure class for this — QuotaExceeded, which the
# engine defers — but only the image backend ever raised it. The whole prose and
# judgment path, which is every stage that matters, had no concept of it.
#
# Checked BEFORE the transient list, which contains "rate limit": a rate limit clears
# on its own and deserves a fast retry, while a spend ceiling needs a human.
# Widened 2026-08-05 on the owner's instruction: ANY wording that means "you have run
# out of allowance for now" belongs here. A session cap, a five-hour cap, a weekly cap
# and a monthly spend cap all mean the same thing to this fleet — wait — and the only
# expensive mistake is treating one of them as a broken proposal. Over-matching costs a
# deferral that resolves on the next cycle; under-matching costs a novel.
QUOTA_SIGNATURES = (
    # spend / billing ceilings
    "spend limit", "monthly spend", "credit balance", "insufficient credits",
    "out of credits", "billing", "usage-credits", "upgrade your plan",
    "purchase more", "payment",
    # allowance / session / plan ceilings, which lift on their own with time
    "usage limit", "limit reached", "reached your limit", "quota exceeded",
    "resource_exhausted", "out of usage", "session limit", "5-hour limit",
    "five-hour limit", "weekly limit", "daily limit", "hourly limit",
    "limit will reset", "limit resets", "resets at", "try again later",
)
# Deliberately NOT here: "overloaded" and "capacity constraints". Those are genuine
# transient blips that clear in seconds and belong on the fast-retry path above.

# --- Budget gating -----------------------------------------------------------

# The engine checks remaining API budget before starting a unit of work and
# advances one unit per cycle, so a runaway can never silently drain spend. The
# ceiling lives in this file under the user config dir if present (again the
# inert-until-the-file-exists pattern); absent ⇒ unlimited, the right default for
# local testing. The daemons never write spend back — this is a hand-managed
# ceiling, not an accountant.
BUDGET_FILE = _env_path("FANFIC_BUDGET_FILE",
                        Path.home() / ".config" / "fanfic" / "budget.json")

# --- Loop cadence ------------------------------------------------------------

POLL_INTERVAL_SEC = 5      # brisk poll while any unit is active
IDLE_INTERVAL_SEC = 30     # slow poll when the inbox and journal are quiet

# --- Quiet hours: when the fleet must not compete with its owner --------------
#
# The mini shares ONE `claude` session with the person who owns it, so a fleet
# drafting novels through the working day is spending capacity that person needs.
# During this window the engine starts no new work: it is a pause, never a failure —
# nothing parks, nothing changes status, and the run resumes by itself afterwards.
#
# Times are US Central and are derived from UTC, never from the host's local clock,
# because a VPN or a mis-set timezone must not be able to move the window. See
# `fanfic/clock.py`.
QUIET_HOURS_ENABLED = _env_flag("FANFIC_QUIET_HOURS", True)
QUIET_START_HOUR = int(os.environ.get("FANFIC_QUIET_START_HOUR", "9"))    # 09:00 CT
QUIET_END_HOUR = int(os.environ.get("FANFIC_QUIET_END_HOUR", "17"))       # 17:00 CT

# Weekdays the window applies to, Monday=0. Default Mon-Fri; weekends run freely.
QUIET_DAYS = tuple(
    int(d) for d in os.environ.get("FANFIC_QUIET_DAYS", "0,1,2,3,4").split(",")
    if d.strip() != "")

# Longest nap taken while paused. Deliberately well short of a full eight-hour
# window: the daemon wakes up, republishes the status file so the phone stays honest,
# and re-derives the window — so a daylight-saving change or a corrected clock is
# noticed rather than slept through.
QUIET_RECHECK_SEC = int(os.environ.get("FANFIC_QUIET_RECHECK_SEC", "600"))
