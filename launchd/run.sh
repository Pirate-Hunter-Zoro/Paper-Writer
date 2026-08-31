#!/bin/bash
# One launcher for all three units. launchd passes the unit name as the single
# argument; the plists differ only in that name, their schedule, and their log paths.
#
# Three near-identical run_*.sh scripts used to live here. They drifted, because three
# copies of the same eleven lines always do.
#
#   ./run.sh scribe | illustrator | binder
#
# Self-updates with `git pull --ff-only` on every (re)launch, so pushing to the
# deployed branch is the deploy. A pull failure is logged and ignored — a launcher
# that refuses to start because GitHub is unreachable is worse than a stale one.
set -euo pipefail

UNIT="${1:?usage: run.sh <scribe|illustrator|binder>}"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

stamp() { date '+%Y-%m-%d %H:%M:%S'; }

# Name the branch explicitly. A bare `git pull --ff-only` resolves origin/HEAD as a
# second merge head alongside the tracked branch and dies with "Cannot fast-forward to
# multiple branches" — every launch, silently, because the failure is caught and
# logged. A deploy mechanism that has never once succeeded looks exactly like one that
# works, since the daemon starts either way and runs the code already on disk.
GIT="$(command -v git || true)"
if [ -n "$GIT" ] && [ -d "$REPO/.git" ]; then
    BRANCH="$("$GIT" -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
    echo "[$(stamp)] git pull --ff-only origin $BRANCH..."
    "$GIT" -C "$REPO" pull --ff-only --no-rebase origin "$BRANCH" 2>&1 ||
        echo "[$(stamp)] git pull failed; using local files."
fi

# The deployed configuration — the model, the picture session, the ceilings, quiet
# hours. Sourced rather than baked into three plists so all three units cannot disagree
# about it, and so a change is one edit plus a restart. `set -a` exports every
# assignment; an absent file is fine, since every value has a default in config.py.
ENV_FILE="$REPO/launchd/fleet.env"
if [ -f "$ENV_FILE" ]; then
    echo "[$(stamp)] sourcing $(basename "$ENV_FILE")"
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
fi

# Prefer the pinned conda env; fall back to the system python3. Nothing outside the
# standard library is imported, so the env is a convenience, not a requirement.
CONDA_PY="/opt/homebrew/Caskroom/miniconda/base/envs/fanfic_env/bin/python3"
if [ -x "$CONDA_PY" ]; then PYTHON="$CONDA_PY"; else PYTHON="$(command -v python3)"; fi

# -m from the repo root, so `import fanfic` resolves with no PYTHONPATH games.
exec "$PYTHON" -m "fanfic.daemons.$UNIT"
