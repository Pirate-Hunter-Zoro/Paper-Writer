"""The state vocabulary of the nested project -> paper -> section machine.

Pure names and a few sets over them — no I/O, no logic — so the engine's dispatch
and the journal's persistence agree on one spelling of every state, and a reader
can see the whole machine in one screen.

Project:
    PROMPT_DROPPED -> GATHERING -> GATHERED -> GROUNDING -> GROUNDED
                   -> PROJECT_PLANNING -> PROJECT_PLANNED -> PAPERS_IN_PROGRESS
                   -> PROJECT_COMPLETE
Paper:
    QUEUED -> ARGUING -> ARGUED -> OUTLINING -> OUTLINED -> DRAFTING -> DRAFTED
           -> REVISING -> BUILDING -> BUILT -> DELIVERING -> DELIVERED -> COMPLETED
Section (inside DRAFTING):
    PENDING -> SEC_DRAFTED -> SEC_EDITING -> ACCEPTED -> LEDGER_MERGED

**A unit never quits.** There is no terminal failure state for a project, a paper, or
a section. That is not optimism; it is the correction of a design that discarded work.

What replaces it is not "retry the same thing forever", which is the reasonable fear
that motivates a failure state. It is:

  * A section that cannot be made clean **ships anyway**, carrying a recorded list of
    what is still wrong with it, and the paper moves on. Nothing is thrown away.
  * The sections that shipped holding defects are revisited in the paper's REVISING
    sweep, once every section exists and the editor can see the whole manuscript.
    Half the defects a Discussion carries are only visible against a finished Results.
  * Infrastructure that keeps failing lands in STALLED, which is *not terminal*: the
    engine retries it on an escalating backoff, indefinitely, because an API outage,
    an allowance ceiling, and a full disk all resolve on their own or when a person
    acts, and none of them is a reason to abandon a manuscript.
"""

# --- Project -----------------------------------------------------------------
PROMPT_DROPPED = "prompt_dropped"       # a prompt file admitted from the inbox
GATHERING = "gathering"                 # building the cited evidence reference
GATHERED = "gathered"                   # evidence coverage passed; evidence frozen
GROUNDING = "grounding"                 # fixing terminology, estimand, reader
GROUNDED = "grounded"                   # grounding complete and gated
PROJECT_PLANNING = "project_planning"   # producing the plan + seed ledger
PROJECT_PLANNED = "project_planned"     # plan + seeded ledger validated
PAPERS_IN_PROGRESS = "papers_in_progress"
PROJECT_COMPLETE = "project_complete"

# --- Paper -------------------------------------------------------------------
QUEUED = "queued"                       # paper unit spawned, awaiting its argument
ARGUING = "arguing"                     # building the claim -> evidence -> section map
ARGUED = "argued"                       # argument map complete and coverage-gated
OUTLINING = "outlining"
OUTLINED = "outlined"                   # section list + paragraph plans validated
DRAFTING = "drafting"
DRAFTED = "drafted"                     # every section ACCEPTED
REVISING = "revising"                   # whole-manuscript sweep over flagged sections
BUILDING = "building"
BUILT = "built"                         # manuscript assembled and converted
DELIVERING = "delivering"
DELIVERED = "delivered"                 # artifacts atomically copied to the out folder
COMPLETED = "completed"

# --- Section -----------------------------------------------------------------
PENDING = "pending"
SEC_DRAFTED = "sec_drafted"             # draft written to staging
SEC_EDITING = "sec_editing"             # editorial passes running
ACCEPTED = "accepted"                   # editorial passes finished
LEDGER_MERGED = "ledger_merged"         # proposed ledger updates validated and merged

# A section record with no section behind it. Outlining runs up to GATE_MAX_ATTEMPTS
# times and the paper spawns one record per section of whichever outline passed — but
# a re-outline that lands on a different section count leaves the surplus records
# behind, and they are indistinguishable from work still to do. Retired means "this
# number is not a section", which is a third thing from finished and from pending.
RETIRED = "retired"

# A section the paper no longer has anything to do with.
SECTION_DONE = {LEDGER_MERGED, RETIRED}

# --- Non-terminal trouble ----------------------------------------------------
# STALLED means "this unit hit something the engine could not get past on this
# attempt". It is retried with escalating backoff, forever. It exists so that a
# problem has somewhere to be recorded that is NOT an abandonment.
STALLED = "stalled"

# Retained so an existing journal replays without a KeyError. Nothing writes them any
# more; `revive`/`recover_stale` rewind any unit found holding one.
FAILED = "failed"
FAILED_SECTION = "failed_section"

DEAD_ENDS = {FAILED, FAILED_SECTION}

TERMINAL = {COMPLETED, PROJECT_COMPLETE}

# Project statuses the engine still has work to do on. The dead ends are in here
# deliberately: a project left holding one by an older build is work the engine should
# pick up and clear, not a tombstone it should walk past.
ACTIVE_PROJECTS = {PROMPT_DROPPED, GATHERED, GROUNDED, PROJECT_PLANNED,
                   PAPERS_IN_PROGRESS, STALLED, FAILED}

# Paper statuses the builder one-shot owns.
BUILDING_STATES = {DRAFTED, BUILDING, BUILT, DELIVERING}

# Statuses the engine can resume FROM directly — the dispatch entry points of the
# project and paper machines.
RESUMABLE = {PROMPT_DROPPED, GATHERED, GROUNDED, PROJECT_PLANNED, PAPERS_IN_PROGRESS,
             QUEUED, ARGUED, OUTLINED, DRAFTING, DRAFTED, REVISING, BUILT}

# In-progress statuses: written just before a long stage starts, cleared just after it
# ends, and with NO standalone handler in the machine. Two consequences.
#
# A revive must rewind PAST them to the last stable entry point, or it would land a
# unit on a status nothing dispatches on.
#
# And a unit found in one of these at startup is *abandoned* — the only process that
# could have been working it is the one that holds the lock, so if it is not us, the
# work died with a kill, a crash, a power cut, or a service restart. Left alone it
# would sit here forever: not terminal, so nothing reports it; not resumable, so
# nothing advances it. `recover_stale` rewinds them at startup, which is what makes
# restarting mid-stage safe.
TRANSIENT = {GATHERING, GROUNDING, PROJECT_PLANNING, ARGUING, OUTLINING,
             BUILDING, DELIVERING}

# Where a unit interrupted in a transient status has to go back to.
#
# `recover_stale` derives this from journal history, which is exact. A *stall* cannot:
# it happens the instant a stage raises, and a single fallback guess is how a paper
# that stalled while outlining resumes with no outline, finds no sections to draft,
# and walks straight through DRAFTED to build an empty manuscript. Every transient
# status therefore names its own entry point.
REWIND_TO = {
    GATHERING: PROMPT_DROPPED,
    GROUNDING: GATHERED,
    PROJECT_PLANNING: GROUNDED,
    ARGUING: QUEUED,
    OUTLINING: ARGUED,
    BUILDING: DRAFTED,
    DELIVERING: BUILT,
}
