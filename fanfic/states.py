"""The state vocabulary of the nested series -> book -> chapter machine.

Pure names and a few sets over them — no I/O, no logic — so the engine's dispatch
and the journal's persistence agree on one spelling of every state, and a reader
can see the whole machine in one screen.

Series:
    PROMPT_DROPPED -> RESEARCHING -> RESEARCHED -> ANCHORING -> ANCHORED
                   -> SERIES_PLANNING -> SERIES_PLANNED -> BOOKS_IN_PROGRESS
                   -> SERIES_COMPLETE
Book:
    QUEUED -> META_PLANNING -> META_PLANNED -> OUTLINING -> OUTLINED -> DRAFTING
           -> DRAFTED -> REVISING -> ILLUSTRATING -> ILLUSTRATED -> BINDING -> BOUND
           -> DELIVERING -> DELIVERED -> COMPLETED
Chapter (inside DRAFTING):
    PENDING -> CH_DRAFTED -> CH_EDITING -> ACCEPTED -> BIBLE_MERGED

**A unit never quits.** There is no terminal failure state for a series, a book, or a
chapter, and that is the correction of the design this project shipped with. The old
machine parked a chapter that would not converge, failed the book that contained it,
failed the series that contained that, and filed the prompt away — so one stubborn
chapter out of thirty-seven discarded 113,000 words of accepted prose and required a
human to notice and act before anything moved again.

What replaces it is not "retry the same thing forever", which is the reasonable fear
that motivated the old design. It is:

  * A chapter that cannot be made clean **ships anyway**, carrying a recorded list of
    what is still wrong with it, and the book moves on. Nothing is thrown away.
  * The chapters that shipped holding defects are revisited in the book's REVISING
    sweep, once every chapter exists and the editor can see the whole book.
  * Infrastructure that keeps failing lands in STALLED, which is *not terminal*: the
    engine retries it on an escalating backoff, indefinitely, because an API outage,
    an allowance ceiling, and a full disk all resolve on their own or when a person
    acts, and none of them is a reason to abandon a novel.
"""

# --- Series ------------------------------------------------------------------
PROMPT_DROPPED = "prompt_dropped"     # a prompt file admitted from inbox/
RESEARCHING = "researching"           # building the cited canon reference
RESEARCHED = "researched"             # canon coverage passed; canon frozen
ANCHORING = "anchoring"               # pinning where everyone is when the book opens
ANCHORED = "anchored"                 # anchor state complete and gated
SERIES_PLANNING = "series_planning"   # producing the series plan + seed bible
SERIES_PLANNED = "series_planned"     # plan + seeded bible validated
BOOKS_IN_PROGRESS = "books_in_progress"
SERIES_COMPLETE = "series_complete"

# --- Book --------------------------------------------------------------------
QUEUED = "queued"                     # book unit spawned, awaiting its meta plan
META_PLANNING = "meta_planning"       # chapter breakdown + the interaction ledger
META_PLANNED = "meta_planned"         # ledger complete and coverage-gated
OUTLINING = "outlining"
OUTLINED = "outlined"                 # chapter list + beat sheets validated
DRAFTING = "drafting"
DRAFTED = "drafted"                   # every chapter ACCEPTED
REVISING = "revising"                 # second-pass sweep over flagged chapters
ILLUSTRATING = "illustrating"
ILLUSTRATED = "illustrated"           # every image slot resolved
BINDING = "binding"
BOUND = "bound"                       # .epub built and validated
DELIVERING = "delivering"
DELIVERED = "delivered"               # .epub atomically copied to iCloud
COMPLETED = "completed"

# --- Chapter -----------------------------------------------------------------
PENDING = "pending"
CH_DRAFTED = "ch_drafted"             # draft written to staging
CH_EDITING = "ch_editing"             # editorial passes running
CRITIQUED = "critiqued"               # retained: older journals hold this status
ACCEPTED = "accepted"                 # editorial passes finished
BIBLE_MERGED = "bible_merged"         # proposed updates validated and merged
# A chapter record with no chapter behind it. Outlining runs up to GATE_MAX_ATTEMPTS
# times and the book spawns one record per chapter of whichever outline passed — but a
# re-outline that lands on a different chapter count leaves the surplus records behind,
# and they are indistinguishable from work still to do. Retired means "this number is
# not a chapter", which is a third thing from finished and from pending.
RETIRED = "retired"

# A chapter the book no longer has anything to do with.
CHAPTER_DONE = {BIBLE_MERGED, RETIRED}

# --- Non-terminal trouble ----------------------------------------------------
# STALLED means "this unit hit something the engine could not get past on this
# attempt". It is retried with escalating backoff, forever. It exists so that a
# problem has somewhere to be recorded that is NOT an abandonment.
STALLED = "stalled"

# Retained so an existing journal replays without a KeyError. Nothing writes them any
# more; `revive`/`recover_stale` rewind any unit found holding one.
FAILED = "failed"
FAILED_CHAPTER = "failed_chapter"

DEAD_ENDS = {FAILED, FAILED_CHAPTER}

TERMINAL = {COMPLETED, SERIES_COMPLETE}

# Series statuses the engine still has work to do on. The dead ends are in here
# deliberately: a series left holding one by the build that had terminal failures is
# work the engine should pick up and clear, not a tombstone it should walk past.
ACTIVE_SERIES = {PROMPT_DROPPED, RESEARCHED, ANCHORED, SERIES_PLANNED,
                 BOOKS_IN_PROGRESS, STALLED, FAILED}

# Book statuses the binder one-shot owns.
BINDING_STATES = {ILLUSTRATED, BINDING, BOUND, DELIVERING}

# Statuses the engine can resume FROM directly — the dispatch entry points of the
# series and book machines.
RESUMABLE = {PROMPT_DROPPED, RESEARCHED, ANCHORED, SERIES_PLANNED, BOOKS_IN_PROGRESS,
             QUEUED, META_PLANNED, OUTLINED, DRAFTING, DRAFTED, REVISING,
             ILLUSTRATING, ILLUSTRATED, BOUND}

# In-progress statuses: written just before a long stage starts, cleared just after it
# ends, and with NO standalone handler in the machine. Two consequences.
#
# A revive must rewind PAST them to the last stable entry point, or it would land a
# unit on a status nothing dispatches on.
#
# And a unit found in one of these at startup is *abandoned* — the only process that
# could have been working it is the one that holds the lock, so if it is not us, the
# work died with a kill, a crash, a power cut, or a launchd restart. Left alone it
# would sit here forever: not terminal, so nothing reports it; not resumable, so
# nothing advances it. `recover_stale` rewinds them at startup, which is what makes
# restarting the fleet mid-stage safe.
TRANSIENT = {RESEARCHING, ANCHORING, SERIES_PLANNING, META_PLANNING, OUTLINING,
             BINDING, DELIVERING}

# Where a unit interrupted in a transient status has to go back to.
#
# `recover_stale` derives this from journal history, which is exact. A *stall* cannot:
# it happens the instant a stage raises, and the fallback it used was "a book rewinds
# to DRAFTING" — which for a book that stalled while outlining means resuming a book
# with no outline, finding no chapters to draft, and walking straight through DRAFTED
# and REVISING to bind an empty novel. Every transient status therefore names its own
# entry point, rather than one guess standing in for all of them.
REWIND_TO = {
    RESEARCHING: PROMPT_DROPPED,
    ANCHORING: RESEARCHED,
    SERIES_PLANNING: ANCHORED,
    META_PLANNING: QUEUED,
    OUTLINING: META_PLANNED,
    BINDING: ILLUSTRATED,
    DELIVERING: BOUND,
}
