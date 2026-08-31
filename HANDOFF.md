# Handoff — the live SWTOR run

Written 2026-08-31 midday, mid-run, for whoever picks up the monitoring next.

The README describes the design. **This file describes the run in progress and the
things that only became true last night**, which is the half the README does not have.
Read the README first for how the machine works; read this for what it is currently
doing, what broke, and what to watch.

---

## 1. What is running right now

A full novelization of the **Star Wars: The Old Republic Jedi Knight class story**,
book 1 of a planned 13-book programme (see the artifact linked in §8). Protagonist is
named **Alyn Tenar** — a light-side Jedi Knight, nineteen, female.

    series id   swtor-jedi-knight
    prompt      ~/Library/Mobile Documents/com~apple~CloudDocs/Books/_inbox/swtor-jedi-knight.md
    state       state/series/swtor-jedi-knight/
    outline     46 chapters
    at handoff  9 chapters accepted (~44k words), 22 reference sheets, 39 scene images
                (ch10 was mid-edit when the daemons were restarted on the morning of
                 the 31st to deploy fix 13; it resumes from the draft on disk)
    allowance   ~$179 of list-price-equivalent usage (a meter, not a bill)

Three launchd units are loaded and running: `scribe`, `illustrator`, `binder`.

**The single most useful command:**

    tail -f state/scribe.log state/illustrator.log

**Restart ONE unit** (this matters — `launchd/startup.sh` reinstalls all three and
will interrupt a chapter mid-draft):

    launchctl bootout gui/$(id -u)/com.mikeyferguson.illustrator
    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.mikeyferguson.illustrator.plist

Drafting resumes from the draft on disk after an interruption, so a restart costs
minutes, not a chapter. It is still worth avoiding.

---

## 2. Standing instruction from the owner

> *"If any issues come up, don't ask me — just make your own calls in how to fix them."*

Act, then report what you changed and why. The owner is not necessarily around. That
autonomy is real, and so is its other half: **say plainly when you were wrong.** Several
of last night's confident findings had to be retracted (§6), and the retraction was
always more useful than the original claim.

---

## 3. The picture path, which is where nearly every bug was

Pictures are drawn by driving a **real signed-in Gemini session** in headless Chrome
(`tools/gemini_art.js`). There is no API key anywhere in this project.

    scripts/check-browser.sh          fixture battery + a live selector probe
    scripts/check-browser.sh --live   three real renders (needs the session)
    scripts/gemini-login.sh           re-sign the profile in when it expires

**The session directory IS the credential:** `~/.config/fanfic/chrome-gemini`. If
renders start failing with "not signed in", that script is the whole fix, and books
hold in ILLUSTRATING meanwhile — nothing is lost.

### Failure signatures you will see in the log, and what each means

| log line | what it is | what to do |
|---|---|---|
| `declined to draw this prompt … third-party content providers` | Gemini's IP classifier firing. **Probabilistic, not deterministic** — the identical prompt often succeeds on a later try. | Nothing. The ladder holds its rung and re-asks. |
| `can't depict some public figures` | Same classifier, different wording. It reads SWTOR's photoreal art as photographs of real people. | Nothing. |
| `Gemini refused N reference picture(s) — likely read as photographs of real people` | An uploaded reference was rejected. Handled: the render retries with references dropped, prose-anchored. | Nothing. Recorded in the `.sources` sidecar. |
| `[WRONG CHARACTER]` | The vision critic caught an identity failure. **This critic is good** — it catches species errors, missing scars, wrong ages, in background figures. | Read it. It is usually right, and it is usually pointing at a defect in the harness, not the model. |
| `no image after Ns` / `stayed in a working state` | The page hung. Bounded now. | Nothing. |

### Never do this

Do not run a render (`gemini_art.js`, `check-browser.sh --live`) while the illustrator
is running. **A Chrome profile can only be open in one process at a time.** Bootout the
illustrator first, or you will get confusing failures in both.

---

## 4. What changed last night, and why (16 commits)

Every one of these came from watching a real book fail, not from review. They are in
`git log` with full reasoning in the code comments; this is the index.

**The refactor itself** (before the run): Claude Opus for every text role, no tiers,
no provider registry; pictures moved from a billed API to the browser session; git
history purged; `scripts/save-and-push.sh` + `.githooks/commit-msg` for attribution-free
commits.

**Found by going live — the harness was wrong, not the model:**

1. `Ask the wiki for the character, not for a page about them` — the lookup resolved
   "Vitiate" to **"Vitiate's palace"**, a building, and returned nothing at all for
   "T7-O1" because a droid designation has no word over two letters. Now asks the wiki
   directly and follows redirects; refuses possessive and disambiguation pages.
2. `A cached prompt cannot be repaired` — **the most important one.** Queue entries
   carried a prompt built at enqueue time and rendering used it verbatim, so no
   correction to a character's design could ever reach art already queued. Kaedan's
   design was corrected and his scenes kept failing identically for an hour because of
   this. Prompts are now always rebuilt at render time.
3. `A species is a category, not a likeness` / `The protagonist is a woman; say so` —
   anchored prompts drop the appearance paragraph (right: prose and pictures disagree
   about a face). But species and sex are **categories**, prose states them exactly, and
   the model does not read them off a picture. A Togruta was drawn human, a Kel Dor was
   drawn human, and Alyn was drawn as a boy three times. Both now survive the trim.
4. `Give the wrong face the references, and let a scar stay in words` — the critic now
   reports `wrong_who`, and those characters are **promoted to the front** of the cast
   so they get the reference set and survive the next rung's trim. Discrete markings
   (a scar, a buzz cut) also survive into the prompt — a marking is not a likeness.
5. `A refusal is not a verdict on the composition` — a content refusal no longer costs a
   ladder rung. It is a classifier firing, not a judgement that the picture is too hard,
   and burning rungs on it landed four scenes on the empty-room rung for no reason.
6. `Never let the upload cap delete a character's only anchor` — references were built
   per character then truncated from the front, so in a four-hander the **trailing
   characters' sheets were deleted entirely**. Sheets now come first for everyone.
7. `Trimming the cast has to trim the description too` — at rung 2 the cast is cut to
   one but the staging line still named the others, so they were drawn with no identity
   at all. Rung 3 already countermanded this; rung 2 now does too.
8. `A rung and a visit count are not the same number` — **a bug I introduced** with (5).
   `defer()` stored one number meaning both; floored at 1, so a refused slot crept a
   rung per visit anyway, and the backoff stopped growing. Now stored separately.
9. Driver robustness: a dead download arm (`frameId` vs `id`), the reference saved
   instead of the render, a refusal believed before the page settled, an empty reply
   waited out for ten minutes, a page stuck "working" forever.
10. `Let canon grow instead of starving every book after the first` — canon is frozen
    per universe; a second book with a different cast parked at 0% coverage. It is now
    topped up for exactly the missing entities and merged.
11. `Give a core party a scene budget instead of banning it` — "no group of characters
    twice in a book" is satisfiable for a 52-character crossover and **not** for an
    18-character novelization. It stalled the book at chapter 31. Now a budget of 3.
12. `Let a novelization keep the source's own villain` — the planner is required to
    invent the biggest bad, which is right for a crossover and wrong for a novelization.
    It had invented a Sith Lord outranking Darth Angral. Declared with
    `Original characters: none.` in the prompt.

**Found on the morning of the 31st, monitoring the run:**

13. `A costume is one outfit, not an itinerary` — the protagonist wore three outfits at
    once for thirty-four chapters and nothing noticed. A progression's `costume` is
    stamped by the outliner at the ONE chapter that delivers it, and
    `costume_for_chapter` then hands it verbatim to every later chapter. Alyn's `p.1`
    was a whole arc in one paragraph — "From the Forge onward a blue-bladed
    lightsaber ...; from Carrick Station onward ... Guardian robes; from Orgus Din's
    funeral onward ... burnt orange cloth" — whose three changes land in chapters 9, 18
    and 37, *not in that order*. The lot was stamped at chapter 9, so from chapter 9 to
    42 every render was told about robes and a forearm wrap she does not own yet, with
    her reference sheet attached. Three parts: `bible.describes_multiple_transitions`
    names the shape, the plan gate rejects it at source so new runs cannot produce one,
    and `_lock_costume_variants` refuses to stamp one that already exists on disk (which
    also stops a re-outline undoing the repair). Alyn's bible entry was split by hand
    into the three correct dated entries; the only change to `series_bible.json` is her
    `costumes` list, verified by diffing against a pre-repair copy.

    Watch out for `ch17 "Six Hours After the Funeral"` — that is **Tarnis's** funeral on
    the Imperial side. Orgus Din dies in ch36 and is buried in ch37. I nearly anchored
    the orange wrap twenty chapters early on the strength of a chapter title.

14. `An editorial trajectory has to survive a restart` — and this one is mine: I caused
    it, watching for it. `trajectory` lived only in `_edit_to_clean`'s frame. The draft
    on disk is reused across a restart, so the passes already spent on it are part of
    the chapter's history — but the list was started empty every time. Chapter 10 went
    `5 -> 2` blocking, I restarted the daemons to deploy fix 13, and it was journaled
    `revisions: 1` and logged **`ACCEPTED (0) — its last pass found no defects`**, which
    reads as a chapter that arrived clean. It was three passes deep.
    Three consequences, in rising order of seriousness: the log line is untrue;
    `EDIT_MAX_PASSES` stops being a cap, because a restart hands back a full budget; and
    `_still_improving` cannot see a loop that has stopped converging, which is the whole
    mechanism that stops paying for a stalled chapter. It also corrupts the evidence §5
    rests on — the decision to keep `EDIT_MAX_PASSES` at 3 is argued from observed
    trajectories, and every restart resets one to look cleaner than it was.
    The trajectory is now journaled as it grows and restored on resume; a *fresh* draft
    explicitly clears it, so a redrafted chapter cannot inherit counts belonging to
    prose that no longer exists.
    **`ch10`'s record is wrong and I left it wrong** — its real trend was `5 -> 2 -> 0`.
    Rewriting an append-only journal to make my own mistake invisible is worse than the
    inaccurate row. `ch02` looks like a second instance (12 `ch_editing` records against
    3 journaled revisions); it predates me.

---

## 5. Open items — decided, with reasons

Nothing here is blocking. These are judgements already made; revisit only with evidence.

- **`EDIT_MAX_PASSES` stays at 3.** I recommended cutting it to 2 on six chapters, then
  withdrew that: chapter 9 went `3 → 7 → 2 → 1 → 0` and would have shipped holding
  seven defects under a two-pass cap. Pass 2 does most of the work; later passes are
  high-variance with a slight positive mean.
- **Render ceiling raised 800 → 1600.** The book runs at ~3 renders per kept picture,
  not the assumed 2. Hitting the ceiling stops the book dead until a person notices,
  and pictures cost nothing but wall-clock.
  **It was not actually in effect until 07:29 on the 31st, and that is the lesson.**
  `FANFIC_IMAGE_RENDER_BUDGET=1600` landed in `launchd/fleet.env` in `2744c8e` at
  07:13, but the scribe had restarted at 07:08 — *before* that commit — and `run.sh`
  only sources `fleet.env` at launch. So the engine went on enforcing 800 for another
  twenty minutes while the file on disk said 1600, and the budget line in the log was
  the only place the difference was visible. At 188/800 spent with 45 chapters left
  needing roughly 600 more renders, the book was on course to hit the ceiling and hold
  in ILLUSTRATING. Restarting the daemons applied it (612 remaining → 1381, and the
  per-chapter cap recovered 4 → 6).
  **An env change is not deployed until the unit that reads it restarts.** Pushing is
  the deploy for *code*, because `run.sh` pulls; it is not the deploy for `fleet.env`
  of a process already running. Check `grep 'picture budget allows' state/scribe.log |
  tail -1` against the cap you think is live.
- **T7-O1 wears a restraining bolt for the whole book, and I left it that way.** Same
  defect as (13) from the other side: `costume_for_chapter` takes the base look to be
  the FIRST undated entry, and T7's is `"Captive: grey chassis with the red Flesh Raider
  restraining bolt on the chest (first scene only)"`. So every chapter but 46 is drawn
  from a first-scene prop, and the parenthetical is an instruction no renderer can act
  on. It has already set: his **locked reference sheet was drawn with the bolt**, and
  the vision critic now enforces it book-wide — `ch06_1` was rejected in part for
  showing "no restraining bolt — a different, instantly recognisable droid".
  Reordering his wardrobe is a two-line data fix, but it invalidates that sheet, and
  that sheet cost 4+ refusals to win. Re-rendering it is the coupled half I could not
  verify without spending renders on a running book, so I stopped at documenting it.
  **If you take it on, do the data fix and the sheet re-render together, or the prompts
  and the sheet will disagree and the critic will reject on the difference.**
- **The painterly-sheet experiment is aimed at the wrong failure mode.** The theory
  was that photoreal source art trips the "real people" classifier, to be tried if
  refusals stayed high. Refusals did stay high — they roughly doubled across the
  morning, per hour `28% → 51% → 49% → 65% → 62% → 73%` of attempts (n=25..49 an hour,
  so not noise) while successful renders halved from 24/hr to 12/hr. So the trigger
  fired, and I went to run it, and the numbers say not to:

  | | count |
  |---|---|
  | `third-party content providers` (franchise IP) | 50 |
  | `can't depict some public figures` (real people) | **2** |
  | reference uploads rejected by Gemini | 55 |
  | references dropped by our own upload cap | 46 |

  The real-people classifier fires **twice in the whole run**. What actually parks a
  slot is the franchise-IP refusal, which is about the prompt naming Star Wars, and no
  change to the reference pictures touches it. The direct test agrees: when the
  references are shed and the same composition is re-asked with none, it succeeds
  23 times and is refused again 29 — barely better than a coin toss, which is what you
  would expect if the references were never the main problem.
  It would probably still reduce the 55 rejected uploads. But it also removes the
  photoreal art the vision critic uses to judge identity — the thing sixteen commits
  were spent getting right — so it trades a measurable identity anchor for an
  unmeasured refusal gain on a secondary failure mode. **Not worth it on this evidence.
  If someone runs it anyway, mark a keep-rate baseline first and watch
  `critic-rejected`, not the headline number.**
  Where the theory came from is worth knowing: the driver logged every rejected upload
  as *"likely read as photographs of real people"* — a guess, asserted in the log line
  itself, which became a finding by repetition. Three of the four
  `BAD_REFERENCE_PATTERNS` say nothing about people. That line now reports what the
  page actually said.

- **What is actually driving the refusal climb is not established, and two obvious
  explanations are already ruled out.** Worth reading before anyone spends a day on it.
  *Not the reference pictures* — see above. *Not our prompts getting wordier*, which was
  my own first guess, since the morning's fixes each added a line to the identity block:
  the refused-prompt dumps in `state/image-diagnostics/*refused.txt` carry the full
  prompt, and their median length is flat at 1733–1984 characters across hours 07–11
  **while the refusal rate went 28% → 65% over exactly those hours.** It only grows to
  ~2350 at hour 12, well after the climb was underway. So terser prompts are unlikely
  to buy anything.
  What is left is a property of the session or the classifier rather than of what we
  send — consistent with the thing §3 already says, that the identical prompt often
  succeeds on a later try. **Do not go re-authenticating on that hunch**: the session
  directory *is* the credential, it is not expired, and a working profile is not worth
  risking on a theory. If you want to test it, the cheap version is to note whether the
  rate falls after the fleet has been idle for a while.
  Caveat on all of the above: the dumps only exist for renders that FAILED, so this is a
  selected sample compared against itself hour by hour. It is enough to rule things out,
  not enough to name a cause.

---

## 6. Errors I made, so you can avoid the same shape

Worth reading. The pattern in all of them is the same.

- **I stated confident conclusions from tiny samples, three times, and had to retract
  all three.** "Gemini will not draw lightsabers" (five renders — false; it draws them
  routinely). "The editorial loop converges monotonically" (two chapters — false; four
  of nine do not). "Cut editorial passes to two" (six chapters — withdrawn on the
  seventh). **Treat the first coherent explanation as a hypothesis, not a finding.**
- **I wrote a test that passed against deliberately-broken code.** Its fixture never
  created the condition it claimed to test. Now, after fixing a bug, I break the fix
  deliberately and confirm the new test *fails*. Do this every time.
- **I pushed with a failing test** by running the suite and the push in one command and
  reading the wrong output.
- **A scripted string-replace hit two sites** and made a function call itself
  infinitely. Check how many places a replacement matches.
- **Stale `__pycache__` made a test report old behaviour against new source** and cost
  twenty minutes of confusion. If source and behaviour disagree, clear it first.
- **`git checkout <file>` reverted an uncommitted fix** along with the deliberate break
  I was testing.

---

## 7. Watching the run: what actually matters

- **Keep rate** (`grep 'of renders kept' state/scribe.log | tail -1`). It has ranged
  31–42%. Below ~30% and sustained means something regressed in identity or refusals.
  **Read the timestamps before you conclude anything from it.** It fell 42 → 38 → 37 →
  32% across the morning of the 31st, which looks like a regression and is not one I
  can attribute: every render in that window was drawn by code that predates the last
  two fixes of the night (`cd99b84` 07:07 and `d027835` 07:16), and the illustrator only
  picked those up when it restarted at 07:16:29. The number is a lagging average over
  mostly-old renders. Let a few hundred accumulate on current code before reading it as
  a trend — this is exactly the small-sample trap of §6.
  **Use `scripts/keep-rate.sh` instead of reading the cumulative number.** It divides
  the same two records the engine does (its cumulative figure agrees with the log line
  exactly), but it also reports the rate *since a marked baseline*, which is the number
  that answers "did what I just deployed help?". Run `scripts/keep-rate.sh --mark` as
  part of every deploy; a baseline was marked at 2026-08-31T12:42Z on 219 billed / 62
  kept. It prints the sample size and says so out loud below 40 renders, because a
  delta over a dozen renders is a hypothesis.
  It also splits the losses into **critic-rejected / refused / hung**, which is the
  distinction the number badly needs: `billed_render` counts an attempt before it
  calls `render`, so the denominator holds all three, and "sustained below 30%" means
  something completely different depending on which is moving. A critic rejection says
  our prompts regressed; a classifier refusal says nothing about the composition at all
  and is what the painterly-sheet experiment below is aimed at.
  First reading after the 12:42Z baseline: **0 critic-rejected, 11 refused, 3 kept.**
  Read that carefully before drawing the obvious conclusion — a refused attempt never
  reaches the vision critic, so this is not "14 renders with no identity failures", it
  is **3 renders that reached the critic and all passed**. n=3.
- **Chapter trajectories** (`grep ACCEPTED state/scribe.log`). Four of nine reach zero
  defects; the rest ship with recorded issues and are queued for the REVISION sweep.
  **That sweep has never run.** It is the mechanism that makes shipping a flawed
  chapter defensible, and it is still an untested design argument.
- **The four prose-anchored sheets** — `alyn-tenar`, `tarnis`, `captain-vurr`, `prell`.
  No wiki has them (Alyn is a player character; the others are minor). These are the
  weakest anchors and the source of most identity failures. **Alyn is in ~55% of the
  book, and her sheet was invented from prose.** If her face needs changing, do it
  before more chapters are illustrated — every later render conditions on it.

---

## 8. Deliverables the owner is watching

- **epub preview in iCloud:** `Books/Star Wars The Old Republic/Tempered/`.
  **`scripts/preview-epub.sh` now does this** — run it whenever you want the preview
  caught up; it takes the series id and book number, defaulting to the only series and
  book 1. The recipe used to live only in a session transcript, which is a bad place
  for something meant to run repeatedly.
  It does what the recipe did: snapshot `state/series` to a temp dir, trim the
  snapshot's `outline.json` to the chapters that actually have prose, point
  `FANFIC_STATE_DIR` at it, build, and place one .epub in Books. **It does not weaken
  `build_epub`'s refusal to bind a book with missing chapters** — that check is what
  stops a half-written novel being delivered as finished; the snapshot is simply
  complete on its own terms. Nothing it does touches the live run.
  Two details worth keeping: the outline is trimmed to a *contiguous* run from
  chapter 1, because a preview with a hole in it is confusing; and the filename uses
  the short book name (`Tempered`), not the full title, whose colon Finder renders as
  a slash. Last built at chapters 1-10 — validated as a real epub, not just a
  zero exit code: zip intact, `mimetype` stored first, 10 chapters, 45 images, nav
  present, no manifest entry without a file. No cover yet; none has been rendered.
- **Review artifact** (chapters + art, refreshed as it grows):
  https://claude.ai/code/artifact/805255cd-2494-47aa-bdde-1ddc7cfb913f
- **The 13-book programme plan:**
  https://claude.ai/code/artifact/47c0a433-80b3-42a8-9fbe-6d4b70eccc34

---

## 9. Is the README still true?

Mostly. It was updated for the refactor — one model, the browser picture path, no
credentials, canon growth, the test suite. **It does not describe items 2–8 of §4**,
which were all found after it was last edited. Where the README and this file disagree
about the picture path, this file is newer.

The test suite is the other source of truth and it is honest: 526 fast tests plus 21
opt-in browser tests, and every bug above has a test named after the failure it
prevents.

    python3 -m unittest discover -s tests          # 5 seconds
    scripts/check-browser.sh                       # ~2 minutes, needs Chrome
