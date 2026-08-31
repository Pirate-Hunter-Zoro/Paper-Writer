#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# keep-rate.sh -- the MARGINAL keep rate, not the cumulative one.
#
#   scripts/keep-rate.sh            # print the current reading and the delta
#   scripts/keep-rate.sh --mark     # record a baseline to measure from
#
# `grep 'of renders kept' state/scribe.log` reports kept/billed over the WHOLE
# run. That is the right number for sizing the picture budget and the wrong one
# for answering "did the change I just shipped help?", because a few hundred
# renders of history swamp the few dozen drawn since. On the morning of the 31st
# it read 28% while every render in the recent window had been drawn by three
# different versions of the prompt builder, and there was no way to separate them.
#
# So: mark a baseline when you deploy, and read the delta afterwards. Billed
# renders come from the append-only picture ledger; kept pictures are the files
# on disk. Both are the same two records `illustration.keep_rate` divides.
#
# A delta over a small number of renders is a hypothesis, not a finding. The
# reading prints the sample size first for that reason.
# ---------------------------------------------------------------------------
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

SID="${FANFIC_SERIES_ID:-$(ls state/series 2>/dev/null | head -1)}"
[ -n "$SID" ] || { echo "no series in state/series"; exit 1; }

LEDGER="state/image_spend.jsonl"
MARK="state/.keep-rate-baseline"

billed="$(grep -c "\"series_id\": \"$SID\"" "$LEDGER" 2>/dev/null || echo 0)"
kept="$(find "state/series/$SID/book" \( -path '*/images/*.png' -o -path '*/sheets/*.png' \) \
        -type f 2>/dev/null | wc -l | tr -d ' ')"

pct() { [ "$2" -gt 0 ] && awk "BEGIN{printf \"%.0f%%\", 100*$1/$2}" || echo "n/a"; }

if [ "${1:-}" = "--mark" ]; then
  printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$billed" "$kept" > "$MARK"
  echo "baseline marked: $billed billed, $kept kept ($(pct "$kept" "$billed") cumulative)"
  exit 0
fi

echo "series      $SID"
echo "cumulative  $kept kept / $billed billed = $(pct "$kept" "$billed")"

if [ -r "$MARK" ]; then
  read -r when b0 k0 < "$MARK"
  db=$((billed - b0)); dk=$((kept - k0))
  echo "baseline    $when ($b0 billed, $k0 kept)"
  if [ "$db" -le 0 ]; then
    echo "since then  no renders yet"
  else
    echo "since then  $dk kept / $db billed = $(pct "$dk" "$db")"
    [ "$db" -lt 40 ] && echo "            (only $db renders — a hypothesis, not a finding)"
  fi
else
  echo "baseline    none; run --mark to start measuring a deploy"
fi

# --- where the losses went ---------------------------------------------------
#
# A billed render is not the same kind of failure every time, and the keep rate
# alone cannot tell you which you have. `billed_render` counts the attempt BEFORE
# it calls `render`, deliberately -- an attempt that dies mid-flight still spent
# the wall-clock, and over-counting is the safe direction for a runaway stop. So
# the denominator holds three unrelated things:
#
#   rejected   the vision critic refused the picture -- identity or craft. This is
#              the one that means OUR prompts regressed.
#   refused    Gemini's IP classifier declined to draw. Says nothing about the
#              composition, and §5's untested painterly-sheet experiment is aimed
#              squarely at this number.
#   timed out  the page hung and produced nothing.
#
# These will not always sum to the billed delta, and the gap is not a bug. A hang
# is logged when it gives up, up to 600s after `billed_render` counted it, so a
# timeout can be billed in one window and reported in the next.
#
# "Sustained below 30%" reads very differently depending on which of these is
# moving, so print them rather than making the reader guess.
LOG="state/illustrator.log"
if [ -r "$LOG" ] && [ -r "$MARK" ]; then
  read -r when _ _ < "$MARK"
  since="$(printf '%s' "$when" | tr 'T' ' ' | tr -d 'Z')"
  awk -v since="$since" '
    match($0, /^\[[0-9-]+ [0-9:]+\]/) {
      stamp = substr($0, 2, RLENGTH - 2)
      if (stamp < since) next
      # PARKED lines are excluded FIRST: a park is a summary of the attempts that
      # preceded it and repeats their "declined to draw" text, so counting it as
      # well double-counts every refusal. With it excluded the arithmetic closes --
      # 11 refused + 3 drew = 14 billed, over the window this was checked against.
      if (/PARKED/)                                    next
      if (/rejected \(attempt/)                       rej++
      else if (/declined to draw|refused at simplify/) ref++
      else if (/no image after/)                       hung++
    }
    END {
      if (rej + ref + hung == 0) { print "losses      none recorded since the baseline"; exit }
      printf "losses      %d critic-rejected, %d refused by the classifier, %d hung\n",
             rej, ref, hung
      if (ref > rej) print "            refusals dominate — that is the classifier, not the prompts (see §5)"
      else if (rej > ref) print "            critic rejections dominate — look at identity, not the classifier"
    }' "$LOG"
fi
