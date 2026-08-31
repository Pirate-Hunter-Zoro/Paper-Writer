#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# check-browser.sh -- prove the picture driver still works.
#
#   scripts/check-browser.sh          fixture battery + a live selector probe
#   scripts/check-browser.sh --live   three real renders (needs the session)
#
# Run the first form after touching tools/gemini_art.js. Run the second after
# `scripts/gemini-login.sh`, and whenever pictures start coming back wrong --
# it is the only thing that can tell you whether Google has moved a selector.
#
# WHAT EACH FORM ACTUALLY PROVES, because the difference is the whole point:
#
#   fixture  Chrome launches, the CDP plumbing works, the signed-in/signed-out
#            state machine is right, a prompt reaches a rich-text composer,
#            references upload, generation is waited out, all three download
#            fallbacks work, the kind->exception contract holds, and the sanity
#            floor rejects what it should. Everything that is not Google's markup.
#
#   probe    that six of the eight selector groups still match the REAL app --
#            composer, send, sign-in CTA, upload menu, response container and the
#            stop-generating control. gemini.google.com serves guests a working
#            chat, so this needs no account, and it is the only thing here that
#            can catch Google reshipping the page.
#
#   live     the last two groups -- the file input and a generated image -- plus
#            the only question that matters: is the art any good. Needs the
#            session. The fixture passing is not evidence for any of this.
# ---------------------------------------------------------------------------
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || { echo "cannot enter $ROOT"; exit 1; }

MODE="${1:-fixture}"
PROFILE="${GEMINI_PROFILE_DIR:-$HOME/.config/fanfic/chrome-gemini}"
PYTHON="$(command -v python3)"

node --check tools/gemini_art.js || { echo "gemini_art.js does not parse"; exit 1; }

if [ "$MODE" != "--live" ]; then
  echo "==> driver battery against the local fixture"
  FANFIC_BROWSER_TESTS=1 "$PYTHON" -m unittest discover -s tests \
      -p 'test_browser_driver.py' 2>&1 | tail -8
  battery=${PIPESTATUS[0]}

  echo
  echo "==> selector probe against the real gemini.google.com (no account needed)"
  # Deliberately a separate throwaway profile: probing must never disturb, and can
  # never depend on, the signed-in session the fleet draws with.
  GEMINI_PROFILE_DIR="$(mktemp -d)" node tools/probe_selectors.js --send 2>&1 | tail -24
  probe=${PIPESTATUS[0]}

  echo
  if [ "$battery" -eq 0 ] && [ "$probe" -eq 0 ]; then
    echo "Everything testable without an account passes."
    echo "Still unverified: the file input and a generated image. Run --live for those."
  fi
  [ "$battery" -ne 0 ] && exit "$battery"
  exit "$probe"
fi

# --- live -----------------------------------------------------------------

if [ ! -d "$PROFILE" ]; then
  echo "No signed-in profile at $PROFILE"
  echo "Run scripts/gemini-login.sh first."
  exit 1
fi

OUT="$(mktemp -d)"
DIAG="$ROOT/state/image-diagnostics"
mkdir -p "$DIAG"

echo "==> live render 1/3: plain prompt"
if ! GEMINI_PROFILE_DIR="$PROFILE" GEMINI_ART_DIAG_DIR="$DIAG" \
     node tools/gemini_art.js --out "$OUT/plain.png" --aspect "2:3" --timeout 420 \
     --prompt "A vertical portrait illustration: a red-cloaked young woman standing on a cliff at dusk, cel-shaded anime style, dramatic rim lighting, no text or lettering anywhere in the image."; then
  echo "   FAILED -- see $DIAG for a screenshot and the page text."
  exit 1
fi

echo "==> live render 2/3: same prompt, conditioned on that render as a reference"
# The reference path is the load-bearing half of visual consistency. A render that
# silently loses its references looks fine and is wrong, so it gets its own check.
if ! GEMINI_PROFILE_DIR="$PROFILE" GEMINI_ART_DIAG_DIR="$DIAG" \
     node tools/gemini_art.js --out "$OUT/ref.png" --aspect "2:3" --timeout 420 \
     --ref "$OUT/plain.png" \
     --prompt "The person in the attached reference picture, same face and same outfit, now sitting at a campfire in a pine forest at night. Cel-shaded anime style. No text or lettering."; then
  echo "   FAILED on the reference path -- see $DIAG."
  exit 1
fi

echo "==> live render 3/3: through the Python seam, with the sanity floor"
GEMINI_PROFILE_DIR="$PROFILE" "$PYTHON" - "$OUT/seam.png" <<'PY'
import sys, pathlib
sys.path.insert(0, ".")
from fanfic.models import images
out = pathlib.Path(sys.argv[1])
images.generate(
    "A wide landscape illustration of a rain-slick neon street at night, no people, "
    "cel-shaded anime style, no text or lettering.",
    out, aspect="3:2", log_fn=lambda m: print("   " + m))
print(f"   wrote {out} ({out.stat().st_size // 1024} KB)")
PY
status=$?
[ $status -ne 0 ] && { echo "   FAILED through the seam."; exit $status; }

echo
echo "All three landed. Open them and judge the ART, which is the only thing"
echo "no test can check:"
for f in "$OUT"/*.png; do echo "  $f"; done
command -v open >/dev/null && open "$OUT"
exit 0
