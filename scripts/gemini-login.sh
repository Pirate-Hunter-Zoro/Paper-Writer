#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# gemini-login.sh -- sign the fleet's Chrome profile in to Gemini, once.
#
#   scripts/gemini-login.sh
#
# This is the whole credential story for pictures. There is no API key in this
# repository and no key file on disk: the illustrator draws by driving a real
# signed-in browser session, and this script is how that session comes to exist.
#
# It opens a normal, visible Chrome on a profile of its own -- NOT your everyday
# Chrome profile, so nothing here touches your bookmarks, your other logins, or
# your history, and the fleet cannot be logged out by something you do in your
# own browser. Sign in to the Google account whose Gemini you want the books
# drawn by, send it one message to confirm the app really opens, then close the
# window. That is it, permanently: the cookies live in the profile directory and
# every render from then on reuses them headlessly.
#
# Re-run it whenever renders start failing with "not signed in" -- Google expires
# a session eventually, and re-signing in is the entire fix.
# ---------------------------------------------------------------------------
set -uo pipefail

PROFILE="${GEMINI_PROFILE_DIR:-$HOME/.config/fanfic/chrome-gemini}"
CHROME="${CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

if [ ! -x "$CHROME" ]; then
  echo "Chrome not found at: $CHROME"
  echo "Install Google Chrome, or set CHROME_BIN to where yours lives."
  exit 1
fi

# A profile can only be open in one Chrome at a time. If the fleet is mid-render
# this would silently attach to nothing, so say so instead.
if pgrep -f -- "--user-data-dir=$PROFILE" >/dev/null 2>&1; then
  echo "Something is already using the profile at:"
  echo "  $PROFILE"
  echo "Stop the illustrator (or close that Chrome window) and run this again."
  exit 1
fi

mkdir -p "$PROFILE"

cat <<EOF
Opening Chrome on the fleet's own profile:
  $PROFILE

  1. Sign in to the Google account you want the books drawn by.
  2. Ask it for one picture, to prove the app is really working.
  3. Close the window.

Nothing else is needed. The session is reused headlessly from then on.
EOF

"$CHROME" \
  --no-first-run \
  --no-default-browser-check \
  --disable-features=Translate,MediaRouter \
  --window-size=1400,1100 \
  --user-data-dir="$PROFILE" \
  "https://gemini.google.com/app"

echo
echo "Chrome closed. Checking the session is usable..."

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$(mktemp -d)/login-check.png"

if GEMINI_PROFILE_DIR="$PROFILE" node "$ROOT/tools/gemini_art.js" \
     --out "$OUT" --timeout 240 \
     --prompt "Generate a single image: a simple flat vector icon of a fountain pen resting on an open book, plain background, no text." \
     >/dev/null 2>&1; then
  echo "Signed in and drawing. The illustrator is ready."
  rm -f "$OUT"
  exit 0
fi

echo "Signed in, but a test render did not come back."
echo "Try again with GEMINI_ART_HEADFUL=1 to watch what the page actually does:"
echo "  GEMINI_ART_HEADFUL=1 node tools/gemini_art.js --out /tmp/x.png --prompt 'a red circle'"
exit 1
