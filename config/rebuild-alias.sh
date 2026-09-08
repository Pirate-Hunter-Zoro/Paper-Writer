# ---------------------------------------------------------------------------
# rebuild-alias.sh -- the `rebuild` command, for a shell profile.
#
# SOURCED, not run. Add this to ~/.bashrc:
#
#   if [ -r "$HOME/Paper-Writer/config/rebuild-alias.sh" ]; then
#       . "$HOME/Paper-Writer/config/rebuild-alias.sh"
#   fi
#
# Then, from anywhere inside a paper repository, after editing a Markdown file:
#
#   rebuild                 rebuild what changed, in the repository you are in
#   rebuild --all           rebuild every document in it
#   rebuild --list          say what would be rebuilt, do nothing
#   rebuild path/to/one.md  rebuild one document
#
# It lives in the repository rather than in the profile so it stays tracked in
# git, which is the same reason `libr-local-llm/config/opencode-guard.sh` does.
# A profile is the one file on a machine nobody has a copy of.
#
# **A function, not an alias.** An alias cannot both default to the current
# directory and pass a path through: `alias rebuild='rebuild-docs.sh .'` turns
# `rebuild some/paper` into two targets, and quietly rebuilds the whole
# repository alongside the folder you named.
#
# Rename it by editing the one word below. It is defined unconditionally
# because defining a function costs nothing and writes nothing, but it names
# the problem rather than reporting "no such file" if this checkout moves.
# ---------------------------------------------------------------------------

rebuild() {
    local script="$HOME/Paper-Writer/scripts/rebuild-docs.sh"
    if [ ! -x "$script" ]; then
        echo "rebuild: not found or not executable: $script" >&2
        echo "rebuild: edit \$HOME/Paper-Writer/config/rebuild-alias.sh if the" \
             "checkout moved." >&2
        return 127
    fi
    # Arguments pass straight through. The script defaults to the repository
    # you are standing in, which is the only reason this can be one word --
    # and putting that default HERE instead was wrong: `rebuild --list` has an
    # argument, so nothing would have supplied the missing path.
    "$script" "$@"
}
