#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# rebuild-docs.sh -- rebuild the .docx of every paper document under a tree.
#
#   scripts/rebuild-docs.sh [options] [PATH ...]
#
# For the loop this exists to serve: open a .md, cut the clause that was
# bothering you, run this, ship the repository. The Markdown is the source and
# the .docx is built from it, so editing the .docx instead is how the two stop
# agreeing.
#
#   --all, -a               rebuild everything, not just what changed
#   --list, -n              say what would be built, build nothing
#   --strict, -s            fail the run on a figure-layout problem too
#   --reference-doc FILE    the .docx supplying the journal's styles
#   --format FMT            what to build (default docx; repeatable)
#   PATH ...                files or directories to walk
#
# With no PATH it walks the repository you are standing in, so the usual call
# from inside a paper repo is the bare command. Failing that it falls back to
# $PAPER_DOCS_DIRS (colon-separated) and then to the harness's own output
# folder, which is what a run from somewhere else needs.
#
# `config/rebuild-alias.sh` puts this on a shell profile as `rebuild`.
#
# **Only the stale are rebuilt.** A .docx younger than its .md is already the
# document, and rebuilding it would churn a binary file in git for nothing. A
# .docx that is missing or older than its source is rebuilt; --all overrides
# that when a template changed and the timestamps cannot see it.
#
# **What is not a paper is not built.** A README describes the folder it sits
# in and nobody submits it, so this walks past README.md and its kin -- the
# list is SKIP_NAMES below and is meant to be edited. Everything else under the
# tree is paper prose and is built. The run says how many it walked past, so
# the policy is visible rather than silent.
#
# Conversion goes through the harness's own converter rather than a bare pandoc
# line, so a document rebuilt by hand is the document the pipeline would have
# produced. That includes the resource path, which is what lets a split
# section's `../results/*.png` resolve; a bare `pandoc x.md -o x.docx` drops
# every figure and still exits 0.
#
# **Figure layout is checked, and warns.** A figure with no `{width=...in}` is
# imported by pandoc at full page width and pushes the text off its own page; a
# row of panels wider than the printable width is silently shrunk by Word until
# the panels stop lining up with their labels. Both are named with their line
# number. They warn rather than fail, because a figure that has always been too
# wide is not a reason to refuse to rebuild the paper today -- pass --strict on
# the run you make before submitting, and they fail it.
#
# **A figure that vanished is a failure here.** Pandoc reports an image it could
# not find as a warning and exits 0, so a document converts successfully and
# arrives with every figure missing. Each built .docx is opened and its images
# counted against the ones its Markdown asks for, and a document that came up
# short is named and fails the run -- you are about to ship it.
#
# Exits 0 when every document that needed building was built, with its figures.
# Any other exit means at least one was not, and the reason is on stdout.
# ---------------------------------------------------------------------------
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Documents about the repository, rather than documents that are the paper.
# Matched on the filename alone, case-insensitively, at any depth.
SKIP_NAMES=(
  README.md
  AI_INSTRUCTIONS.md
  CLAUDE.md
  CONTRIBUTING.md
  CHANGELOG.md
  LICENSE.md
  CODE_OF_CONDUCT.md
  PROMPT_TEMPLATE.md
  TEACHING.md
  MEMORY.md
)

# Directories that hold no paper, whatever is in them.
SKIP_DIRS=(.git node_modules .claude .venv __pycache__ live _inbox state)

FORCE=0
DRY=0
STRICT=0
REFDOC="${PAPER_REFERENCE_DOCX:-}"
FORMATS=()
TARGETS=()

while [ $# -gt 0 ]; do
  case "$1" in
    -a|--all)   FORCE=1; shift ;;
    -n|--list)  DRY=1; shift ;;
    -s|--strict) STRICT=1; shift ;;
    --reference-doc)
      [ $# -ge 2 ] || { echo "--reference-doc needs a file"; exit 2; }
      REFDOC="$2"; shift 2 ;;
    --format)
      [ $# -ge 2 ] || { echo "--format needs a format"; exit 2; }
      FORMATS+=("$2"); shift 2 ;;
    -h|--help)  sed -n '3,57p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)         echo "unknown option: $1"; exit 2 ;;
    *)          TARGETS+=("$1"); shift ;;
  esac
done

[ ${#FORMATS[@]} -gt 0 ] || FORMATS=(docx)

# --- Which tree a document belongs to ----------------------------------------
#
# The enclosing repository, and it has to be the repository rather than
# whatever path was typed on the command line. Both of the things resolved
# below -- the styles template, and where pandoc looks for a figure -- are
# properties of the PAPER, not of the argument: `../results/roc.png` in a
# section under `parts/manuscript/` was written relative to the paper folder,
# and it has to resolve the same way whether the run was pointed at the whole
# repository or at that one file. Deriving either from the argument makes
# rebuilding one file produce a different document from rebuilding all of them,
# which is the one thing a rebuild script must never do.

tree_of() {
  local dir
  dir="$(cd "$1" 2>/dev/null && pwd)" || return 1
  while [ "$dir" != "/" ]; do
    [ -e "$dir/.git" ] && { echo "$dir"; return 0; }
    dir="$(dirname "$dir")"
  done
  return 1
}

dir_of() {
  if [ -d "$1" ]; then echo "$1"; else dirname "$1"; fi
}

# --- Where to walk -----------------------------------------------------------
#
# A named path, then the directory you are standing in if it is inside a
# repository, then PAPER_DOCS_DIRS, then the harness's own output folder.
#
# **The current directory outranks the environment variable**, which is the
# order that reads oddly and is right. Typing a bare `rebuild` while standing in
# a paper repository is an instruction about THAT repository, and a variable set
# once in a profile should not silently redirect it to a different one.
# PAPER_DOCS_DIRS is for the runs made from somewhere else -- a cron job, a home
# directory -- which is the only time nothing better is known.

if [ ${#TARGETS[@]} -eq 0 ]; then
  here="$(tree_of . || true)"
  if [ -n "$here" ]; then
    TARGETS=("$here")
  elif [ -n "${PAPER_DOCS_DIRS:-}" ]; then
    IFS=: read -r -a TARGETS <<< "$PAPER_DOCS_DIRS"
  else
    out="$(cd "$ROOT" && python3 -c "
import sys; sys.path.insert(0, '.')
from paperwriter import config
print(config.OUT_DIR)" 2>/dev/null)"
    [ -n "$out" ] && TARGETS=("$out")
  fi
fi

if [ ${#TARGETS[@]} -eq 0 ]; then
  echo "nothing to walk: pass a path, or set PAPER_DOCS_DIRS"
  exit 2
fi

for t in "${TARGETS[@]}"; do
  [ -e "$t" ] || { echo "no such path: $t"; exit 2; }
done

# --- Pandoc, up front --------------------------------------------------------
#
# Resolved by the harness rather than by `which`, because pandoc is usually
# installed and usually not on PATH -- inside a conda tree, inside RStudio
# Server, inside Quarto. Checked once here so a missing one is one clear line
# instead of the same failure fifty times.

PANDOC="$(cd "$ROOT" && python3 -c "
import sys; sys.path.insert(0, '.')
from paperwriter import config
print(config.PANDOC_BIN)" 2>/dev/null)"

if [ -z "$PANDOC" ]; then
  echo "could not ask the harness where pandoc is; is $ROOT a Paper-Writer checkout?"
  exit 1
fi
if ! "$PANDOC" --version >/dev/null 2>&1; then
  echo "pandoc did not run: $PANDOC"
  echo "set PAPER_PANDOC_BIN to the one you want, or put pandoc on PATH."
  exit 1
fi

# --- The styles template -----------------------------------------------------
#
# An explicit --reference-doc wins, then PAPER_REFERENCE_DOCX, then a formats/
# directory holding exactly one .docx, looked for from the first target upward
# to the top of its repository. Two candidates is a question rather than a
# guess: a manuscript built against the wrong journal's styles is a plausible
# document nobody notices.

if [ -z "$REFDOC" ]; then
  dir="$(cd "$(dir_of "${TARGETS[0]}")" && pwd)"
  ceiling="$(tree_of "$dir" || echo /)"
  while : ; do
    if [ -d "$dir/formats" ]; then
      mapfile -t found < <(find "$dir/formats" -maxdepth 1 -name '*.docx' -type f | sort)
      if [ ${#found[@]} -eq 1 ]; then
        REFDOC="${found[0]}"
        break
      elif [ ${#found[@]} -gt 1 ]; then
        echo "more than one reference document in $dir/formats:"
        printf '  %s\n' "${found[@]}"
        echo "name the one you want with --reference-doc."
        exit 2
      fi
    fi
    if [ "$dir" = "$ceiling" ] || [ "$dir" = "/" ]; then
      break
    fi
    dir="$(dirname "$dir")"
  done
fi

if [ -n "$REFDOC" ] && [ ! -f "$REFDOC" ]; then
  echo "no such reference document: $REFDOC"
  exit 2
fi

# --- Discovery ---------------------------------------------------------------

prune=()
for d in "${SKIP_DIRS[@]}"; do
  prune+=(-name "$d" -o)
done
unset 'prune[${#prune[@]}-1]'          # drop the trailing -o

is_skipped_name() {
  local base
  base="$(basename "$1")"
  local name
  for name in "${SKIP_NAMES[@]}"; do
    [ "${base,,}" = "${name,,}" ] && return 0
  done
  return 1
}

echo "pandoc:     $PANDOC"
echo "template:   ${REFDOC:-(none; building unstyled)}"
echo "walking:    ${TARGETS[*]}"
echo

status=0

for target in "${TARGETS[@]}"; do
  base_dir="$(cd "$(dir_of "$target")" && pwd)"
  if [ -f "$target" ]; then
    sources=("$target")
  else
    mapfile -t sources < <(
      find "$base_dir" \( "${prune[@]}" \) -prune -o \
           -name '*.md' -type f -print | sort)
  fi
  # Figures resolve against the repository, not against what was typed.
  tree="$(tree_of "$base_dir" || echo "$base_dir")"

  for fmt in "${FORMATS[@]}"; do
    build=()
    fresh=0
    skipped=0
    skipped_names=()

    for src in "${sources[@]}"; do
      if is_skipped_name "$src"; then
        skipped=$((skipped + 1))
        skipped_names+=("${src#"$base_dir"/}")
        continue
      fi
      out="${src%.md}.$fmt"
      if [ "$FORCE" = 1 ] || [ ! -e "$out" ] || [ "$src" -nt "$out" ]; then
        build+=("$src")
      else
        fresh=$((fresh + 1))
      fi
    done

    if [ "$DRY" = 1 ]; then
      echo "$base_dir -> .$fmt"
      [ ${#build[@]} -gt 0 ] && printf '  build  %s\n' "${build[@]#"$base_dir"/}"
      [ "$fresh" -gt 0 ] && echo "  $fresh already current"
      [ "$skipped" -gt 0 ] && printf '  skip   %s\n' "${skipped_names[@]}"
      echo
      continue
    fi

    if [ ${#build[@]} -eq 0 ]; then
      echo "$base_dir: nothing to build ($fresh current, $skipped not paper prose)"
      continue
    fi

    # One interpreter for the whole batch, and the harness's own converter
    # inside it, so a hand rebuild and a pipeline build are the same call.
    PW_HARNESS="$ROOT" PW_ROOT="$tree" PW_FORMAT="$fmt" PW_REFDOC="$REFDOC" \
    PW_STRICT="$STRICT" \
      python3 - "${build[@]}" <<'PY'
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["PW_HARNESS"])
from paperwriter.stages import building

fmt = os.environ["PW_FORMAT"]
refdoc = os.environ.get("PW_REFDOC") or None
stop = Path(os.environ["PW_ROOT"]).resolve()

strict = os.environ.get("PW_STRICT") == "1"
failed = 0
holed = 0
skewed = 0
for raw in sys.argv[1:]:
    source = Path(raw)
    # Figures are looked for beside the document, then in each directory above
    # it up to the top of the repository. A split section carries the whole
    # document's figure paths, and those were written relative to the paper.
    here = source.parent.resolve()
    roots = []
    try:
        here.relative_to(stop)
    except ValueError:
        roots = [stop]
    else:
        walk = here
        while walk != stop:
            walk = walk.parent
            roots.append(walk)
    built = building.convert_one(source, fmt, reference_docx=refdoc,
                                 resource_roots=tuple(roots), log_fn=print)
    if built is None:
        failed += 1
        continue
    # convert_one has already named both of these and their counts. Re-asking here
    # only decides the exit status, because you are about to ship the thing.
    if building.figures_lost(source, built, reference_docx=refdoc):
        holed += 1
    if building.figure_layout_problems(source, reference_docx=refdoc):
        skewed += 1

if failed:
    print(f"{failed} document(s) did not convert")
if holed:
    print(f"{holed} document(s) built without all of their figures")
if skewed:
    print(f"{skewed} document(s) have a figure that will not sit on the page"
          + ("" if strict else " (--strict fails the run on these)"))
sys.exit(1 if failed or holed or (skewed and strict) else 0)
PY
    [ $? -eq 0 ] || status=1
    echo "$base_dir: ${#build[@]} built, $fresh already current," \
         "$skipped not paper prose"
  done
done

exit $status
