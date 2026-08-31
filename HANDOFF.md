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
  **The pattern half is not fixed, deliberately:** one occurrence each, and the change
  is a regex in `tools/gemini_art.js`, the riskiest file here and the one whose tests
  are opt-in and need Chrome — with the illustrator booted out first, because a Chrome
  profile opens in one process at a time (§3). Worth doing if it recurs, and then
  `scripts/check-browser.sh` is the thing to run.

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
  **Residual risk, small and known:** his locked sheet still *shows* the bolt, so from
  ch4 the sheet and the costume text disagree about it. The critic follows the text it
  is given — that is exactly what the ch06 rejection demonstrated — so this should be
  right, but if bolt complaints reappear after chapter 4, re-render his sheet.

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

    illustrated      9 of 46 chapters, 5.1 scene images each, plus 22 sheets
    still needed     ~189 pictures
    budget left      ~1333

      keep rate   renders needed   margin
        35%             540          +793
        26%             727          +606   <- cumulative rate for the run so far
        20%             945          +388
        15%           1,260           +73   <- the rate since the 12:42Z baseline
        14%           1,350           -17   <- goes short

**Comfortable at the run's cumulative rate, thin at the rate it is currently running
at.** I first wrote this off as "comfortable at every plausible keep rate" against a
22–35% band; the marginal rate then fell to 15% and the honest margin at that rate is
73 renders, about 6%. It is not short, and 15% rests on only ~47 renders, but the
direction is the wrong one and the whole band is bounded by the refusal rate rather
than by anything about picture quality.

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
