#!/bin/bash
# startup.sh — install or reinstall the Fanfiction-Writer launchd fleet on the mini.
#
# Copies each plist into ~/Library/LaunchAgents and bootstraps it into the user's GUI
# launchd domain. Idempotent (bootout-then-bootstrap), so re-run it after editing any
# plist to reload. Mini-only: nothing here runs anywhere else.
#
#   ./launchd/startup.sh
set -euo pipefail

LAUNCHD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$LAUNCHD_DIR/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"

UNITS=(scribe illustrator binder)

mkdir -p "$AGENTS" "$HOME/Library/Logs"
chmod +x "$LAUNCHD_DIR/run.sh"

# The plists hardcode an absolute path to run.sh, so a clone anywhere else would
# install units that silently run nothing. Fail loudly instead.
EXPECTED="/Users/mikeyferguson/Developer/Fanfiction-Writer"
if [ "$REPO" != "$EXPECTED" ]; then
    echo "!! This clone is at $REPO but the plists point at $EXPECTED."
    echo "!! Either clone to $EXPECTED or update ProgramArguments in all three plists."
    exit 1
fi

for unit in "${UNITS[@]}"; do
    label="com.mikeyferguson.$unit"
    plist="$LAUNCHD_DIR/$label.plist"
    target="$AGENTS/$label.plist"

    if [ ! -f "$plist" ]; then
        echo "!! missing $plist — skipping"
        continue
    fi

    echo "==> installing $label"
    cp "$plist" "$target"
    # Ignore bootout failure when the unit is not yet loaded.
    launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$target"
    launchctl enable "$DOMAIN/$label"
    echo "    loaded."
done

echo
echo "Fleet installed. Routing comes from launchd/fleet.env — see it for what each"
echo "role costs and why. Drop a filled copy of PROMPT_TEMPLATE.md into the drop"
echo "folder, which lives in iCloud so it works from a phone:"
echo "    ~/Library/Mobile Documents/com~apple~CloudDocs/Books/_inbox/"
echo "scribe admits it on the next cycle and writes _STATUS.md beside it."
echo "Logs: ~/Library/Logs/Fanfiction*.log and $REPO/state/<daemon>.log"
