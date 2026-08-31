#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# preview-epub.sh -- rebuild the in-progress epub preview into iCloud Books.
#
#   scripts/preview-epub.sh [series_id] [book_num]
#
# The owner watches this file while the book is being written, so it wants
# rebuilding as chapters land. `binding.build_epub` refuses a book with a
# missing chapter -- correctly; that check is what stops a half-written novel
# being delivered as finished -- so a preview cannot simply be built from the
# live state directory.
#
# The way round it is NOT to weaken the check. It is to build against a
# throwaway SNAPSHOT whose outline has been trimmed to the chapters that
# actually have prose, so the book being bound is complete on its own terms.
# `FANFIC_STATE_DIR` exists for exactly this.
#
# This recipe used to live only in a session transcript, which is a bad place
# for something meant to run repeatedly.
#
# Nothing here writes to the live run: the snapshot is a copy, and the only
# thing that leaves this script is one .epub placed in iCloud.
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SID="${1:-$(ls state/series 2>/dev/null | head -1)}"
BOOK="${2:-1}"
[ -n "$SID" ] || { echo "no series in state/series"; exit 1; }

BOOKS="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Books"
SNAP="$(mktemp -d "${TMPDIR:-/tmp}/fanfic-preview.XXXXXX")"
trap 'rm -rf "$SNAP"' EXIT

mkdir -p "$SNAP/series"
cp -R "state/series/$SID" "$SNAP/series/$SID"

# Trim the snapshot's outline to the chapters that have prose, and report the
# title and range back to the shell.
IFS=$'\t' read -r COUNT SHORT TITLE <<EOF
$(FANFIC_STATE_DIR="$SNAP" python3 - "$SID" "$BOOK" <<'PY'
import json, sys
from fanfic import paths
from fanfic.infra import storage

sid, book = sys.argv[1], int(sys.argv[2])
outline_path = paths.outline_path(sid, book)
outline = storage.load_json(outline_path, {"chapters": []})

have = [c for c in outline.get("chapters", [])
        if paths.chapter_path(sid, book, c["number"]).exists()]
if not have:
    raise SystemExit("no chapters have prose yet")

# Contiguous from chapter 1 only: a preview with a hole in it is confusing, and
# the engine writes chapters in order anyway.
contiguous, expected = [], 1
for chapter in sorted(have, key=lambda c: c["number"]):
    if chapter["number"] != expected:
        break
    contiguous.append(chapter)
    expected += 1

outline["chapters"] = contiguous
storage.save_json(outline, outline_path)

plan = storage.load_json(paths.plan_path(sid), {})
books = plan.get("books") or []
entry = next((b for b in books if b.get("number") == book), None) or {}
title = (entry.get("title") or plan.get("title") or sid).strip()

# The full title goes INSIDE the epub; the filename gets the short name after the
# last dash. "Star Wars: The Old Republic - Tempered" already lives in a folder
# called .../Star Wars The Old Republic/Tempered, so repeating the series in the
# filename is noise -- and its colon is rendered as "/" by Finder.
short = title
for dash in ("\u2014", "\u2013", " - "):
    if dash in short:
        short = short.rsplit(dash, 1)[-1]
short = short.strip().replace(":", "").replace("/", "-") or sid
print(len(contiguous), short, title, sep="\t")
PY
)
EOF

echo "building '$TITLE' as '$SHORT' — chapters 1-$COUNT"

OUT="$(FANFIC_STATE_DIR="$SNAP" python3 - "$SID" "$BOOK" "$TITLE" <<'PY'
import sys
from fanfic.stages import binding
sid, book, title = sys.argv[1], int(sys.argv[2]), sys.argv[3]
print(binding.build_epub({"series_id": sid}, book, title))
PY
)"

DEST="$BOOKS/Star Wars The Old Republic/Tempered"
mkdir -p "$DEST"
FINAL="$DEST/$SHORT — chapters 1-$COUNT (preview).epub"

# Written to a temporary name in the destination and renamed, so a reader
# syncing the folder never opens a half-copied file.
cp "$OUT" "$FINAL.part"
mv -f "$FINAL.part" "$FINAL"

# Drop previews for a smaller range; the newest is the only one worth keeping.
find "$DEST" -maxdepth 1 -name "*chapters 1-*(preview).epub" ! -name "$(basename "$FINAL")" -delete

echo "delivered: $FINAL"
ls -la "$DEST"
