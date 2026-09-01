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

**A `send MISSING` line from the probe used to be a false alarm.** In `--send` mode the
probe sent the message, waited for the reply, and only then measured the selector
groups — by which point the composer is empty and no enabled send button exists. It
printed `send MISSING` on every run while the line directly above it said "sent via the
send button". Fixed by recording the match at click time, the way `busy` already was.
If you see `send MISSING` now, with `sent via Enter (no send button matched)` above it,
that is real.

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
| `no image after Ns` with `last response text: ""` | **Not a hang — the prompt was never submitted.** The dump shows it still in the composer under an idle greeting, with no `You said` on the page. | Nothing; the driver now verifies the send and re-tries. If it becomes frequent again, look at the send/Enter fallback in `gemini_art.js`. |

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

- **RETRACTED: "a third of chapters ship worse than their best". I misread the
  trajectory.**

  I spent several hours treating the last number in `ACCEPTED (6 -> 4 -> 1 -> 3 -> 4)`
  as "defects remaining in the shipped text", built a case that ~11 blocking defects had
  shipped that an earlier pass had already cleared, called it the biggest known quality
  leak in the pipeline, and specified an experiment to fix it.

  **The last number is what the final pass FOUND AND REPAIRED.** The log line says so in
  words — *"its last pass repaired the 9 defect(s) it found"* — and the journal confirms
  it: of 38 accepted chapters, **2** carry `outstanding_issues`; the other 36 carry only
  `unverified_repairs`, meaning every defect found was fixed and nothing has re-read the
  fix. A high final number means the last pass did a lot of work, not that the chapter
  shipped broken.

  So there is no "ship the best pass instead of the last" leak. The last version is the
  one with the most repairs applied to it; it is very likely the best version, and the
  earlier snapshot I proposed shipping instead is the one that still contains what the
  later pass found.

  **What is actually true, and much narrower:** the final repairs are unread. That is
  exactly and only what the REVISION sweep exists for, and every chapter is already
  queued for it. Nothing needs building.

  A caution for whoever reads a trajectory next: `6 -> 4 -> 1 -> 3 -> 4` describes what
  each pass found in the text it was given, and each pass then edits that text. It is a
  record of work done, not a quality curve, and the final figure is the size of the last
  repair rather than the size of the remaining problem.

  (The pass snapshots added tonight are still worth keeping — they make it possible to
  compare versions at all — but the question they were built to answer turned out to
  rest on a misreading.)

- **First clean evidence for the pass budget, now that restarts stop corrupting it.**
  Chapter 13 ran `6 -> 3 -> 2 -> 1 -> 2 -> 0` — six passes, the first chapter in the run
  to reach `EDIT_HARD_MAX_PASSES`, and it did so *across a daemon restart I performed
  mid-chapter*. Both halves matter. Under the old behaviour that restart would have
  reset the count and handed it a fresh budget on top of the three passes already
  spent; instead the ceiling held at six. And passes 4-6 took it from 1 defect to 0
  (via a bump back to 2), so a two-pass cap would have shipped it holding two — which
  is the same conclusion §5's withdrawn recommendation reached the hard way.
  It is also another non-monotonic trajectory: `2 -> 1 -> 2 -> 0`. Four of nine was the
  earlier count; this is not a loop that walks steadily downhill.

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
- **Timeouts cost ~9% of illustrator wall-clock, and some of that is avoidable.**
  Seven `no image after 600s` in the run's first seven hours — 70 minutes of a worker
  whose throughput is what decides when the book finishes. What the page had actually
  said, in each case:

      3x  "Creating your image"          genuinely still working; a real timeout
      1x  "I encountered an error doing what you asked. Could you try again?"
      1x  "...can't depict some public figures..."
      2x  empty, or the bare "Gemini said" label

  Only the first three earn their 600 seconds. The error message is a plain gap:
  nothing in `classifyText` matches it, so the driver waits ten minutes to learn
  something the page said at once — and the message literally asks us to try again.
  The public-figures one is stranger, because `REFUSAL_PATTERNS` has matched that
  wording since last night; it was at 07:36 and has not recurred in the five hours
  since, so it is likelier that the text rendered after the last check than that the
  pattern is broken.
  **`last response text: ""` does not mean Gemini said nothing. It means we never
  asked.** Five of these inside half an hour, and the saved page dumps settle it: the
  prompt is still sitting in the composer under an idle greeting ("Ready when you are",
  "Where should we start?") with no user turn on the page at all. Look at
  `state/image-diagnostics/*-timeout.png` before theorising — a dump with no
  `You said` in it was never submitted.
  Cause: nothing verified the send. The button selector requires `:not([disabled])`,
  and 400ms after inserting ~2KB into a rich-text composer it often is not enabled yet,
  so the code falls through to Enter — and if Enter does not register either, the
  driver waits out the whole deadline for a reply to a message that was never sent.
  **SOLVED, after three wrong explanations. A failed upload disables the send button.**

  When a reference upload fails, Gemini marks the attachment chip with an error icon and
  keeps the send control DISABLED. The prompt sits in the composer and can never go —
  clicking and Enter both do nothing, because there is nothing enabled to click. The
  driver waits out the full deadline and reports `no image after Ns; last response text:
  ""`, which reads as "Gemini said nothing" and means "we were never able to ask".

  The evidence, and it is a photograph rather than an inference:
  `state/image-diagnostics/2026-08-31T22-05-18Z-timeout.png` — five reference chips
  (valis, t7-o1, lord-scourge, ref1, ref2) each carrying an error icon, the prompt below
  them, the send arrow greyed out. Corroborated by the render counts that evening:

      hr    with references    without references
      15         12                    1
      16         11                    5
      18         10                    2
      19          1                    3
      20          3                    7
      21          0                    3

  Reference-conditioned renders went to zero while reference-free renders kept working.
  The model selector also read "Pro" at 17:32 and "Flash" at 22:05, so an account limit
  had probably been hit.

  **Three explanations were tried and all three were wrong**, which is worth knowing
  because each looked reasonable: a send-timing race (two retry schemes, both reverted —
  they were retrying a click against a disabled control, so neither could ever have
  worked); the 180s deadline (reverted, and the failure continued at 420s); and my own
  `prompt_without_refs` change (ruled out — 44 of 49 occurrences had no reference
  refusal anywhere near them).

  **The compounding part: REFERENCE SHEETS cannot be made either.** Sheet renders upload
  source art like everything else, so every character the story introduces during the
  outage is parked without a sheet. At 00:30Z that is **32 sheets against 47 characters**
  — Yulen Sabb, Hare'en, Corvo Deel and a dozen more. The engine tries to lock a sheet
  "before any scene uses it", fails, parks it, and moves on to the scenes anyway, which
  then draw those characters from prose with no sheet to anchor them.

  That outlives the outage. **When uploads recover:**
  1. Check `sheets/` against the bible's character list —
     `ls state/series/<sid>/book/1/sheets/*.png | wc -l` versus the `characters` key.
  2. Run **`scripts/unanchored-scenes.sh`** for the list of kept pictures that were
     drawn from prose alone, and redraw the ones that matter: `rm` the `.png` and its
     `.retry` and the illustrator picks the slot up again from rung 0.

  That script exists because **scene images carry no `.sources` sidecar** — sheets do,
  scenes do not — so nothing in the artifacts records whether a picture was conditioned
  on reference art. The log does ("conditioned on N reference picture(s)"), and the
  script reads it. At 00:40Z the count was **82 kept with reference art, 24 from prose
  alone**, most of the latter from this evening's outage.

  **What the outage looks like while it lasts, so you can recognise it:** each slot
  spends 3 attempts x 420s per ladder rung timing out, reaches rung 3 in about an hour,
  and then renders fine — rung 3 attaches no references, so nothing blocks the send. The
  result is an atmospheric establishing shot instead of the scene's cast (§6c: these are
  good pictures, just not the ones asked for). So the book keeps moving at roughly one
  picture per slot per hour, and the ~35 pending slots would all come out as
  establishing shots if this never clears.

  **APPLIED at ~01:30Z: `FANFIC_IMAGE_MAX_UPLOADS=0`. RESTORE IT TO 6 WHEN UPLOADS
  WORK AGAIN** — test with `scripts/check-browser.sh --live`, whose second render is the
  reference path. The reason I first held off, and what changed:

  I first left this alone because a temporary mitigation nobody reverts becomes
  permanent. What changed is that the outage was confirmed TOTAL rather than partial —
  a live check with ONE reference fails while the identical prompt with none succeeds —
  so the choice was no longer "wait a bit" but "35 peopleless establishing shots over
  ~12 hours, or prose-anchored pictures with the cast in them now".

  It needed one code change alongside it, which is a correct invariant regardless:
  `render_scene` now decides `anchored` from whether pictures will ACTUALLY be attached
  (`rung < 3 and IMAGE_MAX_UPLOADS > 0`), not merely from whether the ladder wants them.
  Without that, uploads-off would have trimmed the appearance paragraph out of a prompt
  with no picture to carry the face — the Kira-as-a-blonde failure exactly (§6z).

  **What it costs while it is on:** no picture is conditioned on a locked reference
  sheet. `scripts/unanchored-scenes.sh` lists every picture drawn this way; redraw the
  ones that matter once uploads return.

  **The mitigation, for the record:** Setting
  `FANFIC_IMAGE_MAX_UPLOADS=0` would skip attachment entirely and let renders through at
  once; it needs one correct-anyway code change alongside it, because `anchored` is
  currently `rung < 3` and would trim the appearance paragraph out of a prompt that has
  no pictures to carry the face (the Kira failure, §6z). Done properly it yields
  prose-anchored renders WITH the cast, which is strictly better than empty rooms.
  The reason not to: **nobody is here to turn it back on.** A temporary mitigation that
  is never reverted silently disables the whole reference-sheet apparatus — the answer
  to hard problem 3 — for the rest of the book. An hour-per-slot slowdown is
  recoverable; a book quietly finished without visual consistency is not. If you apply
  it, set a reminder to remove it.

  **The exact gap is one line in `attachRefs` (`tools/gemini_art.js`), and the machinery
  to handle it already exists.** That function waits until the number of preview chips
  reaches `refs.length` and then returns `true`. **A chip that APPEARED is not a chip
  that UPLOADED** — a failed upload still renders a chip, just with an error icon — so
  the count is satisfied, the driver believes the attach worked, and it walks into the
  disabled send.

  Note the driver already handles a *detected* attach failure correctly: it returns
  `bad_reference`, which sheds the references and re-asks with the prose-anchored
  prompt. That path fired once on this run at 23:06 (`could not attach 6 reference
  picture(s)`) and worked. Only the detection is missing.

  **The fix:** after the chips appear, test whether any is in an error state and, if so,
  return a message matching `/no attachment preview/` so it maps to `bad_reference`.

  **NOT SHIPPED, because it cannot be tested yet.** `tests/fixtures/gemini_page.py` has
  no failed-upload state, so a check written against a guessed error selector fires on
  healthy chips too — an earlier attempt did exactly that and broke 13 of the 21 browser
  tests. **Teach the fixture to serve an errored chip with a disabled send first.** The
  failure mode of getting this wrong is "every reference silently discarded", which
  looks like working software while destroying the visual consistency the reference
  sheets exist for.

    What is safe to say: the cost per occurrence is capped (180s, down from 600s), and
  attempt 1 of the same slot is often submitted fine — this is intermittent, not a dead
  path. **Measure over hours, not minutes,** before believing any fix here:
  `grep 'no image after' state/illustrator.log | grep -c 'text: \"\"'`.

  **The deadline was cut to 180s and put back to 420s, and the round trip is worth
  reading.** The case for 180 looked strong: 81 successful renders, median 29s, max 51s,
  and nothing at all between 51s and the deadline — so a render still going at 180s must
  be hung. **The flaw was in what got measured.** Those durations were paired from log
  lines that start when the PAGE begins working; they never included inserting a ~2KB
  prompt and getting it submitted. A slow send makes the whole driver call long while
  the render itself is quick.

  Share of all render attempts that ended `no image after Ns` with an empty page:

      hr 07-16   600s, then 420s      0-2%
      hr 17      420 -> 180          19%
      hr 18      180s                21%
      hr 19      180s                54%
      hr 20      180s                52%

  **I reverted to 420s on that correlation and it did NOT fix it — so the deadline is
  not the cause.** Hour 21 back at 420s still ran 3 unsent in 8 attempts (38%), which is
  nowhere near the 0% of hours 15-16. Pictures actually drawn, which is the metric that
  matters:

      hr 15   600s        13 drawn     0 min lost
      hr 16   600/420     16 drawn     0 min lost
      hr 18   180s        12 drawn    27 min lost
      hr 19   180s         4 drawn    57 min lost
      hr 20   180 -> 420  10 drawn    70 min lost
      hr 21   420s         3 drawn    21 min lost   (partial hour)

  **Throughput roughly halved around 17:00 and has stayed halved through four different
  deadline and driver configurations** — 600s, 420s, 180s, two driver retry schemes, and
  back again. Nothing I changed moved it, and it survived reverting all of it. On that
  evidence the cause is most likely environmental (a Gemini-side change or throttle that
  began around 17:00 UTC), not anything in this repo.

  Left at 420s, the code default. Note the tradeoff if you revisit: if the failure rate
  is deadline-independent, a SHORTER deadline is better for throughput because each
  failure costs less wall-clock — but do not re-derive 180s from render durations the
  way I did. **Measure the FULL driver call (insert, send, wait), not the page's own
  working time, and watch the share of attempts rather than the count per hour.**

    **The timeout half was a dead knob, and that is fixed.** `illustration.render` — the
  only path a scene or sheet render takes — hardcoded `timeout=600`, so
  `FANFIC_IMAGE_RENDER_TIMEOUT_SEC` had never applied to a single render in the run.
  Tuning it, restarting, and watching nothing happen is the same trap as an env change
  that never reaches a running daemon, one layer further in. The seam now passes the
  configured value, which restores the 420 the config comment argues for — and the
  measurement backs that comment exactly: successful renders on this book run a
  **median of 22s and a p90 of 51s**, so 420 is still eight times the p90 while 600 was
  spending ten minutes to discover that a hung page was hung.

- **T7-O1's restraining bolt is FIXED — and my reason for deferring it was wrong.**
  I first left this alone believing the data fix was coupled to re-rendering his sheet,
  which had cost 4+ refusals to win. That was wrong, and the code says so plainly:
  `spec_text = identity` — **"the critic is handed exactly what the generator was
  handed."** The vision critic judges against the same per-chapter costume line the
  prompt is built from, so correcting the costume corrects both at once. The ch06
  rejection for a *missing* bolt was the critic faithfully enforcing the stale text it
  had been given, not a sheet mismatch.
  What made it urgent was `ch11_1`, rejected `[WRONG CHARACTER]` for a glowing RED
  sensor eye against a sheet that gives him a BLUE one. His whole prompt line read
  `T7-O1 (200): grey chassis with the red Flesh Raider restraining bolt on the chest
  (first scene only).` — the **only colour word in it was "red"**, attached to a prop
  he lost in chapter 3, and nothing anywhere said blue. Two fixes:
  *Data.* His costumes now resolve properly: captive with the bolt through ch3 (he is
  found bolted to a cache floor in ch3 and Alyn pulls it in that same chapter), no bolt
  from ch4, and the Defender-class utility harness from ch18 where the corvette is
  assigned. The bogus `from_chapter: 46` entry — p.4's itinerary stamped at the chapter
  that *delivered* the progression rather than where the look changes — is gone, and the
  §4.13 guard stops a re-outline putting it back.
  *Code.* A droid's sensor eye is now a signature mark. Human eye colour stays out, and
  a test pins that — it is fine detail a reference carries well, and a bare `"eye"` in
  the marker list would drag it back into every anchored prompt. A droid's single eye is
  the opposite: the whole face, and a broad flat colour the model defaults.
  **The residual risk landed, and the remedy was not the one written here.** At 04:25
  `ch19_4` was rejected because the render showed the bolt in chapter 19 — the prompt
  said "chest plate clear", and the model followed the SHEET instead, which still had
  it. Re-rendering the sheet would not have helped: **a sheet is drawn from the BASE
  costume**, and his base was the bolted "Captive" state, so every re-render would put
  the bolt back.

  Fixed properly: the base is now the free state — what he looks like in 43 of 46
  chapters — and the bolted period is a dated entry `from_chapter 1`, which the ch4 entry
  then supersedes. The sheet was deleted so it re-locks bolt-free.

  **The general rule, worth knowing before repairing any other character:** the base
  costume is not just "chapter one's outfit", it is *what the reference sheet will show
  for the whole book*. Put the dominant state there and date the exceptions.

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

## 6z. The trim assumed the pictures arrive; on this book they often do not

**~40% of this book's renders are re-asked with every reference refused, and until now
they were re-asked with the prompt written for having references.**

`build_scene_prompt(anchored=True)` drops each character's appearance paragraph. That is
correct doctrine — "there is no wording for a particular jaw", and a model handed both
prose and a picture averages them into a stranger. It holds *while the picture is
attached*. Gemini refuses whole reference sets often (106 prose-anchored fallbacks so
far), and the driver's fallback quietly re-asked with the trimmed text and no pictures:
**nothing anchoring the face at all, from either direction.**

Kira Carsen is the case, and she is a principal from chapter 18 on. Her locked design is
dark red hair — the critic calls it "the single feature a reader identifies Kira by" —
and her anchored prompt says nothing about hair, deliberately. All six references were
refused and she came back a golden blonde three times running, at three different rungs.

The fix carries a second prompt down beside the first: `prompt_without_refs`, the same
scene with the appearance paragraphs intact, used only when the uploads are refused. The
doctrine is unchanged when references land; it stops applying when they do not.

**Note what this is NOT.** It is not "put hair colour back in anchored prompts". I was
about to argue for that off Kira's failures, and it would have been the wrong fix
addressing a real symptom: the anchored prompt is right, the fallback was wrong. Check
whether the references actually arrived before concluding the words are missing
something — `grep 'would not use' state/illustrator.log`.

---

## 6c. The empty-room rung is fine, and I was wrong to call it damage

I raised this as an urgent quality problem, wrote it up as a decision for the owner, and
then looked at the actual pictures. **They are good.**

**The situation.** A timeout advances the ladder rung; a refusal does not (§4.5). While
Gemini's uploads were failing (§3), every reference-carrying render timed out, so
`ch19_6` and `ch20_1` walked down to **rung 3 — the composition with no named characters
in it** — on compositions that were never at fault. I described the result as "a
permanent hole in the book" and "peopleless pictures", repeatedly, without opening one.

**What rung 3 actually produced:**

  * `ch19_6.png` — a derelict ship interior in near-darkness, a single blue holographic
    figure standing on a projector table, cables and grime everywhere. Atmospheric and
    entirely publishable.
  * `ch20_1.png` — an empty vaulted hall, a throne at the head of a stair, an open book
    abandoned on the floor. Reads as a deliberate establishing shot.

Neither is what the scene asked for, and neither is damage. A novel carries
establishing shots happily. **The ladder's bottom rung degrades gracefully, which is
what it was designed to do.**

**So the trade is much milder than I claimed, and the current behaviour is right.**
Descending on a timeout is also the only thing that rescues a slot when uploads are
blocked, because rung 3 attaches no references and therefore still draws.
`test_a_render_failure_still_advances_the_ladder` asserts this deliberately. Leave it.

If a specific chapter really needs its cast in frame, re-queue after uploads recover:
delete the image and its `.retry` and the illustrator redraws it from rung 0.

---

## 6d. Owner feedback on the art, 2026-09-01 — three real defects

Read chapter 1 and its pictures. The prose was fine; the art was not. All three
complaints were correct and all three had different causes.

**1. A foreground subject with no head.** `ch01_3`: Jaric Kaedan holds a blade up to
read the maker's mark, and the frame cuts him off at the shoulders. Perfect hands,
perfect blade, no face. **The vision critic passed it** — its craft list covered
generative anatomy failures (melted hands, fused bodies) and said nothing about a crop,
and a tight crop is legitimate in general. `prompts/vision.md` now fails a named
character whose face is not in frame, as a question separate from anatomy. It is
answerable from the image alone, so it does NOT require handing the critic the staging
description — which was removed for good reason and must stay removed (it nitpicked
props until slots were skipped).

**2. Satele Shan reads about thirty-five.** Her locked design is fifty-six. This was the
run's worst recurring identity failure — ten of twenty-one `WRONG CHARACTER` verdicts —
and it had **two causes, both now addressed**.

  * *The fringe half* was a negation: her appearance said "no side bangs appear at any
    point", which is how bangs got drawn. Rewritten positively (§6a).
  * *The age half* was a bare number. The whole of the anchored prompt's defence was
    `(woman, 56)` in a parenthetical — **and a number is not an instruction to draw
    anything.** An image model's prior for an adult sits near thirty and quietly
    overrules a photograph: her sheet is genuinely excellent (lined, heavy-jawed,
    braided, no fringe) and she still came back "late twenties to early thirties" with
    it attached. Orgus Din, sixty, came back "roughly 45".

  Age now gets the same emphatic line species already had, and for the same reason —
  a categorical fact the generator defaults wrong on that a reference picture does not
  settle: *"Age is NOT optional and NOT young by default: Grand Master Satele Shan is
  56, Master Orgus Din is 60. Draw each of them at that age ... A face that reads a
  decade younger than the number is the wrong person."* Threshold 45; younger cast
  members are left out, because below it the default and the number already agree and
  extra words only compete with the reference.

  **Unverified.** The mechanism is sound and matches four earlier fixes of the same
  shape (species, sex, skin tone, markings), but no render has tested it yet. Watch the
  next scenes containing Satele or Orgus.

  *One clean before-reading exists.* `ch01_3` was redrawn at 02:14, 40 seconds BEFORE
  the restart that made the age line live, so it shows the state without it: Kaedan has
  a head (the new critic rule), Satele has her braids and no fringe (the negation fix),
  and she still reads about **forty**.

  **ITERATION ONE FAILED, measured.** At 02:35 — twenty minutes AFTER the age line went
  live — `ch14_5` was rejected with Satele "roughly late twenties to mid thirties". I
  rebuilt that exact prompt to check, and the line was in it: *"Grand Master Satele Shan
  is 56."* So the instruction reached the model and the model ignored it.

  **Iteration two, and the reasoning behind it:** both mentions used the NUMERAL. A
  digit carries almost nothing to a diffusion model, and "fine lines at the eyes" — the
  only other age signal in her prompt — actively undersells fifty-six. The line now
  spells the age and hands over things that can be drawn:

      Age is NOT optional and NOT young by default: Grand Master Satele Shan is
      fifty-six — a lined face, heavier jaw, grey coming into the hair; Master Orgus
      Din is sixty — ...; Master Jaric Kaedan is forty-five — clear lines at the eyes
      and mouth, a settled middle-aged face. Draw each of them with that face. One that
      reads a decade younger is the wrong person.

  Banded at 45 / 55 / 65 so a forty-five-year-old and a sixty-five-year-old do not get
  the same description.

- **THE REAL MECHANISM, and it is not the wording: identity fails in CROWDED frames.**
  Found by looking at `ch14_5` rather than at counts. Its three attempts, in order:

      02:33  attempt 1, simplify=0, two named characters -> Kira drawn blonde
      02:35  attempt 2, simplify=1, two named characters -> Satele drawn thirty too young
      02:37  attempt 3, simplify=2, cast trimmed to ONE  -> both faces correct, kept

  Same slot, same prompt, same references. The only thing that changed was how many
  people were sharing them. And the picture that came out has Satele with grey-streaked
  hair and a lined fifty-something face — the exact thing three weeks of prompt wording
  had failed to produce.

  Across the whole run, by number of named characters in the slot:

      named   slots   judged   identity failures
        1       14       9            0
        2       70      67           18
        3       61      53            6
        4       22      17            4

  Nine single-character judgements, zero identity failures. The codebase already
  suspected this — *"fidelity per face falls as the reference count rises, so a crowded
  frame that attaches everything makes every face in it worse"* — but nothing acted on
  it. `prompts/art_direction.md` now targets one or two NAMED characters per picture and
  explains that unnamed figures in the background are free: a name in `characters` is a
  claim the render must reproduce a locked design, and every extra claim dilutes the
  rest.

- **A length cap was silently eating the colours it existed to carry.** Bela Kiwiiks is
  a Togruta: *"deep red skin marked with broad white bands across the montrals and down
  the front of each lek"* — ninety-four characters, against `colouring_of`'s
  sixty-character cap. So **her skin colour reached no prompt at all**, and `ch18_2`
  came back with "a pale, ashen white-grey face with the pattern effectively inverted".
  A filter that drops a fact for being described thoroughly is worse than no filter.

  Cap raised to 100, with a guard against clauses that are not present-tense
  description. The guard is not optional: at 100 without it, Vitiate's *"original
  red-skinned Sith body has been gone for over a millennium"* and Lord Nefarid's
  *"standing behind furniture and in doorways so he is rarely fully visible"* both
  arrived as their FIRST colour clause. Measured across all 47 characters, the pair
  recovers twelve real colour facts and admits zero junk — and it incidentally fixes
  Vitiate ("ashen-lilac skin over a narrow ridged skull") and Nefarid ("grey-white
  skin"), who were both being described by accident.

- **A worse bug I introduced tonight: I told the render to draw a droid as an old man.**
  T7-O1's `age` is 200, so the new age line said *"T7-O1 is 200 — deeply lined and
  weathered, grey or white hair, an old face"* — and `ch03_1` came back with the head of
  an elderly human man, white hair and wrinkles, grafted onto the astromech's dome. The
  model did exactly as instructed.

  Two guards now, because the number alone cannot tell you: `ages_visibly` reads the
  appearance for machine words (droid, astromech, chassis, sensor eye, dome), and ages
  past a human lifespan (110) are skipped because the number has stopped describing a
  face. Species is deliberately NOT the test — Tol Braga is a sixty-five-year-old Kel
  Dor and his face shows it, so he keeps the line.

  The lesson is the shape of the mistake, not the mistake: **a rule written from the
  characters in front of me, applied to a cast I did not re-check.** Ten characters
  matched `mature_cast`; nine were people and I only looked at those.

  *And then the fix had the same flaw, caught by finally doing the audit.* The first
  machine-word list included "dome" and "plating" — but Sella Voit is a human "dome
  administrator ... weathered by dome light", and plated armour is worn by people all
  through this book. Of that list only "astromech" and "sensor eye" ever matched
  anything real. Tightened to unambiguous machine words, and **an audit of all fifty
  identity lines now comes back clean.** Run that audit after touching the prompt
  builder; it is three lines of Python and it catches what reasoning does not.

- **T7-O1 was never declared a droid — in forty-seven illustrations.** He appears in
  more pictures than any other character, and **the word "droid" was in none of their
  prompts.** `species_of` declares a species by reading "Togruta female" out of the
  opening clause; it requires a sex word, and a droid has none. So T7 fell through every
  net at once: no species, no sex, just `T7-O1 (200)` and a costume line. The reference
  sheet was the only thing saying he was a machine, and when it was diluted across a
  crowded frame the model drew what the words implied — `ch23_5` came back with "a tall
  bald humanoid alien with a radiating crown" and no droid in the picture at all.

  Machines are now declared beside the species line: *"T7-O1 is a MACHINE, not a person:
  a droid chassis with no face, no skin and no human features of any kind."* The age
  parenthetical is dropped for them too — `T7-O1 (200)` was a number with no face
  attached, and it is what put an elderly human head on him earlier tonight.

  **The pattern across every identity fix tonight: the checks were all written for
  people.** Species needs a sex word. Age assumes a face. Skin and hair assume both. A
  droid satisfies none of those preconditions and so was silently exempt from all of
  them, in the character with the most screen time in the book.

- **Declaring the species was not enough: the alien ANATOMY was in nobody's prompt.**
  Once Scourge had his species (below), the failure simply moved — `ch20_5` gave him a
  smooth, spur-free face with ordinary ears, missing the braided tendril beard entirely.
  `signature_marks` had no words for non-human features, so montrals, lekku, tendrils,
  antennae and breath masks reached no prompt at all. That is **66 slot-appearances**:
  Lord Praven (29), Bela Kiwiiks (16), Scourge (10), Tol Braga (9), Nyriss (2).
  It explains the oldest identity failures in the run — Kiwiiks drawn as a human in a
  head-wrap, Braga as an elderly human in goggles — which were previously blamed on the
  model ignoring its references.

  **One of them backfired on a different character, which is worth knowing.** For Lord
  Scourge "tendrils" genuinely means a braided beard framing the jaw; for Lord Praven it
  means eyebrows and nothing else. Naming tendrils at all gave Praven the Sith
  tentacle-beard the model already expects — `ch30_2`, a failure mode he had never had
  before the markers went in (his earlier failure was a respirator plate, a different
  thing entirely). Fixed by making his own clause say **"tendrils ONLY where eyebrows
  would be"** rather than reverting the markers, which are carrying real weight for
  Kiwiiks, Braga and Scourge.
  The general point: a word that identifies one alien can mislead about another, because
  the model brings its own priors to it. Qualify the clause on the character it belongs
  to.

- **A phrase can fight the fact it qualifies, and Orgus Din's did for seven verdicts.**
  His mark reached the prompt as *"Short grey hair **grown out** from decades of a shaved
  scalp so that it stands up in an untidy brush"*. "Grown out" literally means "has grown
  longer", three words after "short" — and he was repeatedly rendered with "long, wavy
  grey hair falling several inches past the ear". Rewritten so the unambiguous facts lead
  and the history is dropped: the prompt now carries "short grey hair" and "standing up
  in a stiff untidy brush over a scalp shaved for decades" as separate clauses.

  **Audited the whole cast for the same shape and found no pattern** — Bengel Morr's
  "skin gone dull and patchy" and Nyriss's "tendrils thinned to string" both describe
  genuine current states, not contradictions. Orgus was the outlier. The only other hit
  was Prell's clause ending on a dangling "and", now stripped in code.

  A caution about auditing, learned twice in ten minutes: my first pass used substring
  matching and reported Satele Shan as having non-human anatomy, because "fin" is inside
  "fine lines". **Use word boundaries before believing an audit**, or it will hand you a
  list that is mostly noise and a conclusion that is mostly wrong.

- **Lord Scourge had no species at all in his prompt, and he is in ten illustrations.**
  `species_of` reads the opening clause of a locked appearance and required the SEX WORD
  TO BE ITS LAST WORD — the convention being "Togruta female, fifty-five…". Scourge
  opens *"Sith pureblood male who reads as a hard forty and has for three centuries"*,
  with no comma until well past "male", so he read as having no species. The emphatic
  "Species is NOT optional and NOT human by default" line never named him, and `ch20_4`
  came back giving him a Quarren's curtain of face tentacles.

  Now the sex word may appear anywhere in that clause. Four characters were affected —
  Scourge (10 slots), Darth Nyriss (2), Laotah and Vitiate (0 each).

  **And the fix immediately regressed three humans, which the audit caught.** Loosening
  the rule meant labels arrived with adjectives attached, and the old
  `startswith("human")` check let "Middle-aged human", "Small neat human" and "Old
  human" through as *species* — which would have put three ordinary people into the
  "must be drawn as that species" line. Now "human" anywhere disqualifies, and a leading
  descriptor is stripped so "Elderly Twi'lek" resolves to "Twi'lek".
  Final audit: eight characters carry a species, every human is blank.

- **Thinly-described minor characters drift, and it is NOT worth fixing in this book.**
  `ch20_3` failed on Lord Kelvath: the sheet shows a light-skinned man with dark hair
  swept back, the render gave a dark-skinned man with close-shorn hair. His entire
  locked design is *"Small neat human man, middle years, close-cut hair, clean-shaven"* —
  **no skin colour, no hair colour**. His sheet was invented from that, so nothing in
  words pins what a render must reproduce, and the sheet is the only anchor.

  **28 of 50 characters have no skin colour in their locked design**, which sounds
  systemic and is not. Measured by how often they actually appear: those 28 account for
  67 of 490 slot-appearances, and **47 of those 67 are T7-O1**, a droid with no skin to
  describe. Excluding him it is 20 appearances spread across 27 bit parts, one or two
  each. Enriching nineteen sheets by hand would buy almost nothing.

  What this does say: for a FUTURE book, a *principal* described this thinly would be a
  real problem, and the plan gate does not currently require a skin colour. Worth adding
  in the shape of the negation gate (§6a) — with a machine exemption, since `ages_visibly`
  already knows a droid when it sees one. Not built; the measurement says it is not
  urgent for this run.

- **A bug I introduced tonight: identity clauses said twice.** Adding "hair" to
  `colouring_of` made it overlap with `signature_marks`, because a hair clause that
  mentions a braid or a buzz cut matches both. Satele Shan, Orgus Din and Jaric Kaedan
  each carried the same sentence twice in their identity line, differing only in
  capitalisation — which is how it went unnoticed. Deduped case-insensitively.
  Repetition in a prompt is not emphasis; it is noise competing with the reference.

  **This is the lever to pull on before any more prompt wording.** The age and hair
  lines are cheap and stay, but if identity is still drifting in a week, look at cast
  size per picture first.

  **The catch: chapters 1-32 were art-directed under the OLD guidance, and 88 of their
  173 slots (51%) name three or more characters.** Scene briefs are chosen once, at
  chapter acceptance, and stored; re-rendering rebuilds the prompt but not the choice of
  moment or cast. So half the book's existing slots will keep failing identity on their
  first attempts.

  **That self-corrects, slowly and at a cost.** A crowded slot fails, descends the
  ladder, gets trimmed to one character at rung 2, and then renders correctly — which is
  exactly what `ch14_5` did. So those chapters end up with more single-figure pictures
  than their briefs intended, after burning two or three extra renders each. It is not
  wrong, just not what was composed.
  Re-art-directing ch1-32 would fix the compositions properly and costs roughly 500
  renders plus discarding ~170 existing pictures, many of them good. **Not done** — the
  budget could take it (1720 left) but it is a big destructive call and the self-
  correcting path is acceptable. Worth revisiting if the owner would rather have the
  intended two-hander compositions than the current ones.

- **Hair colour is a stated fact now too, and this reverses a documented decision.**
  `colouring_of` excluded hair because "hair and eye colour are the fine detail a
  reference carries well". **Eye colour still is. Hair colour is not**, and Kira Carsen
  proves it four times: her sheet is flawless — three views, a large head close-up, dark
  auburn, freckles, the cheek scar — it was attached (`conditioned on 6 reference
  picture(s)`), her prompt said nothing about hair, and she came back a golden blonde
  every time. The critic's words never varied: *"hair colour and cut are the two things
  a reader recognises Kira by, and neither is present."*

  A broad flat area of colour is not a jaw. It is the same argument that re-admitted
  skin tone — it does not compete with the reference for the shape of a face, it says
  which of the model's defaults to stop reaching for — and blonde is the default.
  `test_eye_colour_stays_out_but_hair_colour_no_longer_does` pins both halves.

  Three older tests used hair as their probe for "the appearance paragraph was trimmed"
  and now probe build or eye colour instead; the property they assert is unchanged.

**3. The pictures show the quiet moments and skip the action.** Chapter 1 opens with a
nineteen-year-old holding a breach against Flesh Raiders. Its five illustrations were:
the breach, her slumped against a fence post, four Masters around a table, her sitting
on a step, her holding a work lamp. **One action beat and four people sitting down.**

Two separate causes, and both are fixed:

  * *Selection.* `prompts/art_direction.md` opened with "a drawable good moment beats an
    undrawable better one every time" — written after undrawable briefs produced empty
    slots, and overcorrected into always choosing the safe moment. It now leads with
    choosing the chapter's peaks, requires that **a chapter containing action gets at
    least one illustration of that action**, and says drawability constrains HOW a peak
    is framed, never whether it is picked.
  * *Rendering.* The one action beat that WAS chosen, `ch01_1`, rendered as an empty
    yard — debris, no Alyn, no Flesh Raiders. It failed down the ladder to the
    empty-room rung. **19 of 106 pictures (18%) are empty rooms and every one of them
    had a brief naming characters.** I had earlier looked at two of those, found them
    atmospheric, and called them "fine, not damage" — that was generalising from two
    scenes that happened to work as establishing shots. `ch01_1` is a total loss.

**Redraw list.** The 19: ch01_1, ch01_4, ch03_1, ch03_2, ch06_5, ch08_2, ch14_5, ch18_1,
ch18_2, ch18_4, ch18_5, ch19_4, ch19_5, ch19_6, ch20_1, ch20_3, ch20_4, ch20_5, ch21_1.
Delete the `.png` and its `.retry` and the illustrator redraws from rung 0.

---

## 6e. RESULT: identity failures fell about fourfold

The one number this all had to move, measured against a baseline marked before the fix
set went live:

    before 2026-09-01 06:05    176 renders judged    35 identity failures    19.9%
    after                       41 renders judged     2 identity failures     4.9%

    P(<= 2 failures in 41 draws at the old 20% rate) = 0.007

**A 0.7% chance of seeing that by luck**, so something real happened. This is the first
genuine result of the session; everything before it was mechanism.

**What it does NOT establish, and the honest limits matter:**

  * *Not a controlled experiment.* Nine fixes landed in overlapping windows — cast size,
    species parsing, alien anatomy, the machine declaration, hair colour, spelled ages,
    the recovered colour cap, the clause dedupe, the face-in-frame critic rule. The drop
    cannot be attributed to any one of them from this data.
  * *Cast composition moved too.* Later chapters draw different people, and §6c shows
    failure rate tracks WHO is in frame. Some of the gain may be that rather than the
    fixes.
  * *41 renders is enough to say "real", not enough to rank causes.*

If you want attribution rather than a total, the way to get it is one fix at a time with
a marked baseline between each — expensive, and probably not worth it now that the rate
is where it is.

**Strongest independent evidence, for what it is worth:** the cast-size finding, because
it has a within-slot proof (`ch14_5` failed twice at two named characters and passed at
one, same prompt); and the droid declaration, because T7-O1 appears in 47 slots and the
word "droid" was in none of their prompts before it.

---

## 6f. The picture path stalled for hours, and BOTH of my first two theories were wrong

**Symptom, 2026-09-01 from about 11:57:** renders stopped. Every attempt carrying
references reported `no image after 420s; last response text: ""`, which reads as
"Gemini said nothing" and actually means **we were never able to ask**. Three attempts
per slot at 420 seconds each is 21 minutes to produce nothing, then a park. Reference-
free renders kept working the whole time.

### What it actually is

The upload fails. The attachment chip is optimistic: it appears immediately, sits in a
loading state, then flips to an error — and once any attachment is errored, Gemini
**ignores the send**. The prompt sits in the composer until the deadline expires.

Measured, not inferred:

    reference-free render      -> ok, 165 KB, ~20s
    179-byte valid PNG as ref  -> upload errored, no send, timed out

Same minute, same session. So it is the transfer — not the prompt, not the file, not
its format, not its size.

The error is visible in the DOM as
`<gem-attachment class="... gem-attachment-loading-error ...">` containing
`<gem-icon fonticonname="error">`.

### Two wrong theories, both of which I believed and one of which I nearly shipped

**Wrong theory 1: "a JPEG named `.png` is rejected by the uploader."** All 39 character
sheets really are JPEG bytes under a `.png` name (Gemini returns JPEG; `paths.py` names
everything `.png` on purpose, and `mime_of` exists for exactly this). It is a real
mismatch and it is a genuinely plausible cause — Chrome infers the upload's MIME type
from the extension. I wrote the normalizer, wrote four tests, proved they could fail,
and then tested it against the live page: **a mislabelled file uploaded fine, and a
correctly-named one failed.** Four alternating runs failed identically regardless of
extension. The change was reverted in full; nothing of it is in the tree. Had I shipped
on the tests alone it would have looked like a fix and changed nothing.

**Wrong theory 2, which had been written in this repo as fact for a day: "Gemini keeps
the send control DISABLED."** It does not. A DOM dump of the live failure shows the send
button with no `disabled`, no `aria-disabled` and no disabled class. The click lands and
is dropped. That sentence had been sitting in two long comment blocks in
`tools/gemini_art.js`, asserted as a diagnosis, and it sent two separate send-retry
schemes chasing a control that was never disabled. Both comments are now corrected.

The lesson is the one already in `memory/state-a-hypothesis-not-a-finding.md`, in its
sharpest form yet: **a guess written into a code comment becomes a finding by being read
back.** The fix here only arrived after dumping the actual DOM.

### What shipped

`dump()` now also writes `<stamp>-timeout.dom.json` — the outerHTML of the attachment
chips and the send button. The text dump could never show this: an errored chip
contributes only a filename, identical to a healthy one. That file is what ended the
investigation, and it took ten seconds to read.

Detection lives in the **wait-for-picture loop**, not in `attachRefs`. This matters and
it is the second thing I got wrong: a check made the instant the chips appear runs
*before* the upload has failed, sees two healthy-looking chips, and changes nothing —
which is exactly what my first version did live while its fixture test passed. The
fixture now models the real timing (`?scenario=uploadfail` errors after 2.5s), so the
test fails without the wait-loop check.

A failed transfer gets its own kind, `upload_failed`, and is **retried twice with the
references still attached** before anything is shed. That distinction is the whole point:

  * a *rejected picture* is permanent -> shed it, redraw from prose;
  * a *failed transfer* is transient  -> ask again, keep the face.

Shedding on the first failure would redraw the scene from prose and **keep it**, because
a slot that produced an image is done. A character would lose their locked face for the
rest of the book on the strength of one bad second. Detection now costs ~5s instead of
420s, so three anchored attempts cost ~15s against a 420s deadline.

Measured end to end, live, against the real page:

    before:  420s x 3 attempts -> nothing, slot parked
    after:   5.6s to detect; 3 anchored tries, then shed, then drew -> 37s total

### The open question: WHY do uploads fail?

Not answered, and I am not going to invent a reason. What is known: they worked earlier
on 2026-09-01, failed consistently for ~20 minutes, worked again, and were failing again
at 14:00. The account is on the free tier (the page shows an "Upgrade" button and the
`Flash` model), so a per-window upload limit is a candidate — **a candidate, not a
finding.** The fleet is now resilient to it either way: the cost of an upload outage is
prose-anchored pictures instead of anchored ones, rather than a stalled illustrator.

**If uploads stay broken, the book fills with prose-anchored art**, which is precisely
the identity weakness the owner asked to fix. That is the thing to watch, and
`scripts/unanchored-scenes.sh` counts it.

## 6g. A rung that forbids a face was attaching it

Found while reading a timeout dump for 6f, in the prompt itself. A rung-2 render said:

> Kira Carsen is the ONLY person in the picture. Master Bela Kiwiiks is mentioned only
> to say what is happening around them and **must NOT appear** — no second figure, no
> silhouette, no face in the background

with **Bela Kiwiiks's locked sheet attached to the request.** The prompt forbids the
face; the upload supplies it.

The cause is a straightforward drift. `build_scene_prompt` trims the cast as the ladder
simplifies — rung 1 keeps two characters, rung 2 keeps one — but the reference bundle
was built ONCE, before the loop, from the untrimmed cast, and never rebuilt. The prompt
got simpler each rung while the attachments stayed the same.

Two costs, and the second one bites hardest right now:

  * the model is handed a face it was just told not to draw, at the exact rung that
    exists to *rescue* a picture that already came out wrong;
  * it spends upload slots on it. Uploads fail intermittently (6f) and every attachment
    is another chance to fail — so the rung-2 retry was sending the MOST attachments to
    draw the FEWEST characters.

Fixed with one definition, `illustration.kept_at_rung`, used by both the prompt and the
bundle so they cannot drift again. The reference list is now rebuilt per rung, and the
vision critic is handed the same list the generator was — the project's standing rule
that the two must judge the same document.

Six tests, including one that walks rungs 0-2 and asserts that whoever the prompt still
costumes is exactly whoever keeps their reference pictures. Reverting either half of the
fix fails them.

## 6h. Every model ceiling was announced as an image one

At 14:32Z on 2026-09-01 the fleet began logging, every two minutes for 44 minutes:

    image quota/rate limit reached; deferring remaining images, retrying in 120s
    (book stays ILLUSTRATING, writing unaffected)

None of that was true. The line immediately above it said what had actually happened:

    model spend/quota ceiling reached: You've hit your session limit
    · resets 10:10am (America/Chicago)

The **writer** had hit its Claude session limit. Writing was the only thing affected,
and the illustrator was rendering happily throughout.

`engine/cycle.py` tells the two ceilings apart because they mean opposite things — an
image ceiling thins a book, a model ceiling stops it — and only the second is worth
telling a human about. It did so by testing `"spend/quota limit" in str(quota)`.
**Neither backend has ever raised that string.** The text provider raises
`"... allowance ceiling: ..."` and the image provider `"gemini session limit: ..."`, so
the model-side branch was dead code from the day it was written. Every model ceiling
took the image backoff (120s instead of 300s), named the wrong backend, and omitted the
line that says a human may need to lift the limit.

Fixed with a field: `QuotaExceeded(..., source="model"|"image")`, set at both raise
sites and read by `cycle`. Two modules agreeing on a substring is not a contract.

Two tests, and reverting to the substring fails the model one. This was found only
because the monitor surfaced 22 identical events and the message did not match what the
illustrator was visibly doing — **a log line that names a cause is a claim, and this one
had been false since it was written.** Same shape as the "send button is disabled"
comment in 6f, discovered the same afternoon.

The stall self-cleared at 15:16Z when the session limit rolled over, with no
intervention and nothing lost — that part worked exactly as designed.

## 6i. The OTHER empty-reply failure: the send is dropped and the prompt never goes

6f fixed failed reference uploads. It did not fix everything reporting
`no image after 420s; last response text: ""`, and the remainder is a separate fault
with the same symptom — which is exactly why the first one took so long to see.

**Today's cost, counted:** 65 renders died this way, 7.6 hours of wall-clock.

The timeout dump for one of them shows: **no attachments at all**, the prompt sitting in
the composer, and the send arrow **blue and enabled**. No error anywhere on the page —
the DOM sweep for tooltips, alerts and snackbars returns only "New chat", "Settings",
"Submit". The click lands and is silently dropped, and the driver then waits 420 seconds
for a reply to a question that was never asked.

### The signal, verified rather than assumed

A successful send CLEARS the composer. Checked against a dump of a *refused* render — so
the prompt definitely went — where the prompt text appears exactly twice, both times
under "You said" in the conversation, and never in the composer. So:

    idle + nothing answered + our prompt still in the composer  =  it never went

The driver now pushes send again after 25 seconds of that, and gives up quickly if the
second push also does nothing. **Re-sending usually works**, so this recovers renders
rather than merely failing faster.

### What the tests had to be taught, twice

The first version used a fixed 200-character floor for "the composer still holds our
prompt". Real prompts are ~2KB; the test harness passes `--prompt "a red fox"`, nine
characters. It could not fire, and the test failed. It is measured against what we
actually typed now.

Worse, the false-positive test was **vacuous and I nearly shipped it**. A double
submission bills a second render and can return a different picture than the one the
critic is about to judge — the dangerous direction — but against the plain `ok` fixture
a reply lands before the first poll, so `!hasResponse` alone carried the test and
deleting the composer check changed nothing. `?scenario=slowreply` now lands the send,
clears the composer, and stays silent for six seconds, which is the only shape where the
composer check is the sole guard. Deleting it now fails the test — and fails it by
ABORTING a healthy render as "never sent", not merely by sending twice.

Both directions are falsifiable: break the detection and the dropped send times out;
break the composer check and a healthy slow reply is killed.

## 6j. The revision sweep ran to completion — what it actually yielded

Finished 19:28Z on 2026-09-01. This was the last stage on this book that had never
run here end to end.

    46 chapters, 77 rounds
    80 blocking issues found
    301 edits applied
    2 chapters still carrying notes

1.7 blocking issues per chapter and 3.9 edits per round. The stopping rule held: every
round that reported "another round" had found something blocking, and no chapter ran
past its cap. **31 of 46 chapters needed a second round**, so a single sweep would have
left about two thirds of the found defects in place — the second pass is not ceremony.

Two chapters end with notes still open. That is the designed floor, not a failure: the
sweep repairs what it can defend and records what it cannot rather than forcing an edit
it does not believe in.

### One profile collision, and why it was left alone

Immediately after the sweep the scribe went to render a character sheet for Vitiate — a
character introduced late — and hit the illustrator holding the Chrome profile, which
can only be open in one process:

    STALLED: Chrome devtools never came up on port 9731. Is another Chrome already
    using the profile?

It recovered by itself five minutes later on stall attempt 1 and drew the sheet. The 57
alarming-looking log lines were one "waiting to retry" message every five seconds during
a single backoff — **one distinct stall event, ever.**

No lock was added. There is a real design tension here (two daemons, one credential) and
if it starts costing real time it deserves a proper file lock. On the strength of one
self-healed incident, adding cross-process locking to a working pipeline would risk a
deadlock to fix something the existing backoff already handles. Count the events before
building the mechanism.

## 6a. The single biggest cause of identity failures was our own prompts saying "no"

**Ten of the twenty-one `[WRONG CHARACTER]` verdicts in this run are Satele Shan's side
bangs.** Her locked appearance ended: *"the braided version is fixed for this entire
book and no side bangs appear at any point."* The most explicitly forbidden feature in
the whole cast is the one the model drew most often.

It is not mysterious. **An image model has no reliable negation.** "no side bangs" puts
*side bangs* in the prompt; there is no mechanism that reliably subtracts them, and the
noun is what gets drawn. The same shape, all over the bible:

    Satele    "no side bangs appear at any point"        -> bangs, 10 times
    Tarnis    "No robes, no hood, no lightsaber"         -> drawn with a lightsaber
    Alyn      "and no vibrosword"                        -> a vibrosword appeared,
                                                            attached to Tarnis
    T7-O1     "no restraining bolt"                      -> mine, from an hour earlier

Every one is now phrased as a positive statement of the same fact, which is the form a
renderer can act on — "both braids drawn back tight from a fully exposed hairline,
forehead and temples clear" rather than "no side bangs". Also fixed in the same pass:
Rusk's "no back-mounted weapon" and Prell's "no rank flashes". Only Darth Angral keeps
a "not", deliberately: *"the prosthetic does not change"* is a contrast describing how
his eyes behave, not an instruction to omit an object, so there is no noun to latch on
to.

**A claim I made here and then had to withdraw.** I wrote that negations corrupt the
vision critic too, citing Kaedan: his appearance said *"never blonde"*, and the first
verdict on him reported *"the design states blonde throughout this entire book"*. That
looked like the critic collapsing the negation. It was not. `illustration.py` records
what actually happened — *"His locked design was wrong (blonde, unscarred, against a
canon character with a dark buzz cut and a scar through the eyebrow); the bible was
corrected, his sheet re-locked"*. The design really was blonde at the time and the
critic was reporting it accurately. **There is no evidence a negation has ever misled
the critic.** The generator half stands on its own — Satele's ten, Tarnis's lightsaber —
and is why the rewrite and the gate are still right.

**The critic does not otherwise lose anything.** It is handed the same text *and* the
reference sheet, and the sheet shows the correct hair — every one of Satele's ten
complaints cites the sheet, not the prose.

**My first sweep was incomplete and I had to redo it.** I scanned only the rendered
costume line, which is one surface; the full `appearance` text is another, and it is
what reference-sheet generation and the sheet critic are handed. Kaedan's "never
blonde" lived there and my first pass sailed past it. A second sweep over the full text
found eight more that name a drawable noun — Satele's "never a green single blade",
Revan's "No mask, no armour" (he is a character *famous* for a mask), Alyn's "never
wears her hood up", Orgus's "must never be drawn ornate", Praven's "must not be
generalised into robes", Rusk's "no illustration ever helmets him", Corrin's insignia,
and two "no over-robe"s. All rephrased positively.
Deliberately left: "no visible sclera" (Scourge) and "no visible whites" (Morr) describe
an anatomical fact with no prop to reach for, and rewriting them risks losing what makes
those two faces alien.

**The identity-failure rate is driven by WHICH CHARACTERS are in frame, so comparing
time windows is misleading.** Measured per render that reached the vision critic:

    before any identity fix today   n=83   25% failed
    after negation sweep 1          n=10   10%
    after negation sweep 2 + T7     n=13   31%   <- WORSE than baseline
    after the refused-refs fallback n=18    0%

The 0% looks like a fix landing and the 31% looks like a regression. Neither is either.
**Three of window 3's four failures were Kira Carsen** — the same red-hair-drawn-blonde
defect, three times — and Kira does not appear in window 4 at all. The window that looks
cured is the window she is missing from. A cast with a hard-to-draw principal in it fails
more than a cast without one, whatever the prompts say.
So: before reading any window comparison here, check which characters were actually in
those renders. `grep -o "<name>" state/illustrator.log` per window is enough.

**None of this is confirmed yet, and the way it will look confirmed is a trap.** An
hour after the rewrite: 11 renders reached the critic, 1 identity failure, 0 complaints
about Satele's bangs. That reads like a fix landing. It is not — **Satele has not been
drawn once since the change**, nor has Tarnis, nor T7. The test has not run. The one
failure was Kira, it predates half the rewrite, and it is about hair colour that was
never in the prompt at all.
Worth internalising for anything prompt-level here: with ~85% of attempts refused and
the illustrator working chapters in order, a given character may not surface for hours.
Absence of a failure is mostly absence of a test. **Check that the character actually
appeared before reading anything into a clean stretch.**

**The rule is now a gate, because I could not apply it by hand.** Say what is in the
picture, never what is absent — and `bible.forbids_a_visible_thing` enforces it at plan
time over the appearance *and* every costume entry, so a new book cannot start with one.

I built the gate because three consecutive hand-sweeps each missed a surface. The same
negation gets written into three places, and I fixed them in three separate passes:
first the rendered costume line, then the full `appearance` (which is what reference-
sheet generation reads — Kaedan's "never blonde" was hiding there), then the plain
wardrobe strings, which still held Alyn's "no lightsaber", T7's "no restraining bolt"
and Morr's "no weapon" after both earlier passes. Each time I believed I was done.
That is what a deterministic check is for.

The rule is narrow on purpose, and the exclusions are the interesting part: `not` is
excluded, because it is nearly always a verb negation forbidding nothing ("a runner's
build, not a soldier's"); the noun must follow within two words, which is what stops
"his face does not move much, so the armour reads as the expression" matching across
the comma; and shadows, sclera and whites are not on the list, because those are
lighting and anatomy rather than props a model can reach for — "casting no shadow" is
the entire point of drawing a Force ghost. Validated against the bible as it stood
before today: 21 real hits, 0 false.

---

## 6b. Will it finish? — the arithmetic, as of 13:15Z on the 31st

Checked because the refusal climb makes it a fair question. **Budget is not the
constraint; wall-clock is.**

**Refreshed at 21:40Z** (the earlier figures below were taken at 9 illustrated
chapters and are superseded):

    illustrated      19 of 46 chapters, 5.5 images each
    drafted          22 of 46 chapters, ~40 min each
    still needed     ~148 pictures
    budget left      ~1802 renders  (needs ~670 at the 22% cumulative keep rate)

      illustration   ~21 h at the halved post-17:00 rate (~7 pictures/hr)
                     ~11 h at the earlier rate (~14/hr)
      drafting       ~16 h for the remaining 24 chapters

**It finishes, and roughly within a day, even at the halved rate.** Illustration and
drafting are now comparable rather than illustration trailing 2:1 — most of the gap
closed simply because 19 chapters are already done and the per-chapter count settled at
5.5. Budget is nowhere near binding: ~670 needed against ~1802 left.

Two earlier readings of this section were wrong in opposite directions and are worth not
repeating. "Comfortable at every plausible keep rate" was written against a 22-35% band
before the marginal rate fell to 15%; then "the margin is thin, +73 renders" was written
at the 1600 ceiling, before it was raised to 2400. **Recompute this from the live
counts rather than trusting any number in it — it has gone stale twice in a day.**

**DONE — the ceiling was raised 1600 → 2400 at 13:50Z and the daemons restarted.** The
rate held at 15% across three consecutive checks over 67 renders, which left a margin of
eight pictures out of 189. That is not a margin. At 2400 it is ~128.

I acted on 67 renders rather than the "few hundred" this section originally asked for,
and the asymmetry is the whole argument: unused ceiling costs nothing at all, while
hitting it stops the book dead with every slot queued waiting for a person — and with
the owner away that could be a day of idle fleet. **When one side of a bet is free, take
it early.** The threshold was written for confidence in the number; it should not have
been applied to a decision this lopsided.

If it needs raising again, the same reasoning applies, and **restart the daemons after**
— or the number sits inert exactly as the 800 → 1600 raise did (§5).

**This is also what the 800 → 1600 ceiling was worth, concretely.** Under the 800 cap
that was still in force until 07:29, the run had 549 renders left against a 675–860
need. It would have hit the ceiling and held in ILLUSTRATING with the book unfinished.
That was not a hypothetical stall.

What *is* slow is throughput. At ~12–15 renders an hour against a ~70% refusal rate the
illustrator lands roughly 3–4 pictures an hour, so ~189 pictures is on the order of two
days, against roughly one day of drafting for the remaining 36 chapters. Illustration
trails drafting by about 2x and is the thing that decides when the book is done.

**A permanently-refused slot is not a deadlock, and here is the measured reason.** A
refusal holds its ladder rung by design (§4.5), so a slot the classifier keeps declining
never simplifies and never reaches the empty-room rung — it retries on a backoff that
doubles 5m -> 10m -> 20m -> 40m and caps at an hour, indefinitely. That is survivable
only because refusals are probabilistic. **They are, and the tail is long:**

    ch11_1   4 parks -> resolved      ch10_2   6 parks -> still open
    ch06_5   6 parks -> resolved      ch09_1   7 parks -> still open
    ch10_1   6 parks -> resolved      ch08_5   9 parks -> still open

(A park is roughly three refused attempts, so `ch08_5` has been declined ~27 times.)

**I considered adding an escape hatch — after N refusals, let the rung advance — and
decided against it on this data.** Slots resolve at four and six parks, and six appears
on both sides of that table, so any threshold low enough to help would fire on slots
that were going to succeed anyway. That is precisely the failure §4.5 was written to
stop: four scenes landed on the empty-room rung for no reason. A threshold high enough
to be safe (say 12) would only fire after ~6 hours, by which time the slot has usually
resolved itself. The mechanism works; it is just slow, and slow is what the backoff is
for.
Revisit if a slot ever passes ~15 parks, which would be well outside anything observed.

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
- **Chapter trajectories** (`grep ACCEPTED state/scribe.log`). Roughly half reach zero
  defects on their last pass; the rest repair what they found and are queued for the
  REVISION sweep.

  **Two corrections to what this section used to say.** It claimed the sweep "has never
  run" and is "an untested design argument". Neither is right.

  *It has run, on the previous book.* `engine/revising.py`'s docstring records the
  measurement: 24 chapters re-read against the finished novel yielded **18 blocking
  defects, three of them canon violations** — Polly given an impossible age, Eda knowing
  the Titan origin of glyph magic years before canon reveals it, Bill claiming he has no
  legs. Every one had survived the per-chapter loop. It also has three unit tests. What
  is true is narrower and unalarming: it has not run *in this run*, and cannot, because
  it fires only once every chapter exists.

  *And nothing is shipping with known defects.* At 15 chapters: **0 carry
  `outstanding_issues`; all 15 are queued for the milder reason**, `unverified_repairs`
  — their last pass fixed everything it found and nothing re-read the fix. Per
  `flagged()` that buys one round each, with a second only if the first finds blocking
  defects (`REVISION_SWEEPS = 2`). So the tail cost is on the order of 46 re-edits at
  roughly $1.50 apiece, not a rescue operation.

  The stopping rule is worth understanding before anyone tunes it: it is **blocking
  yield**, never polish. "Sweep until nothing is unread" cannot terminate, because every
  edit leaves itself unread; "sweep while the editor still finds something" is the
  critic-who-can-never-be-satisfied trap wearing a new hat.
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
