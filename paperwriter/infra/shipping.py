"""Shipping — commit and push the repository a finished paper was delivered into.

Delivery puts the documents on disk. If that disk is a git working tree, the work is
not actually anywhere until somebody commits it, and "somebody commits it" is the step
that gets forgotten for a week while the author believes the paper is filed.

So the pipeline can finish the job. This module is the narrowest possible version of
that, because pushing to a remote is the only outward-facing thing this harness does
and the blast radius of getting it wrong is somebody else's repository.

**It is off by default.** `PAPER_SHIP_REPO` names the working tree to commit in and
nothing happens without it. `PAPER_SHIP_PUSH` is a second switch, because committing is
local and reversible and pushing is neither.

**It stages the delivered files by path and nothing else.** Never `git add -A`. A
daemon that swept the working tree would commit whatever the author had open at the
time, and the first time that happens it commits half an edit to an unrelated file
under a message about a manuscript.

**It refuses rather than forces.** A detached HEAD, a merge or rebase in progress,
already-staged changes it did not stage, or a remote that has moved ahead all stop it
with an explanation. The paper is already delivered at that point, so stopping costs a
commit somebody makes by hand, and the alternative costs history.

**It never raises into the engine.** Returns a note describing what happened. Delivery
has already succeeded by the time this runs, and a git problem must not be the reason a
finished paper's status stays unfinished — the same rule that governs pandoc.
"""

import subprocess
from pathlib import Path

from .. import config


def _git(repo, *args, timeout=120):
    """Run one git command in `repo`. Returns (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=timeout)
        return result.returncode, (result.stdout or "").strip(), \
            (result.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)


def _repo_of(paths_):
    """The configured ship repo, if the delivered paths are inside it.

    Delivering outside the repo and committing inside it would produce an empty
    commit under a message claiming a paper had shipped, which is worse than not
    committing at all."""
    root = config.SHIP_REPO
    if not root:
        return None, "PAPER_SHIP_REPO is not set, so nothing is committed."
    root = Path(root).expanduser().resolve()
    if not (root / ".git").exists():
        return None, f"{root} is not a git working tree; nothing was committed."
    inside = [p for p in paths_ if _is_within(p, root)]
    if not inside:
        return None, (f"none of the delivered files are inside {root}, so there is "
                      f"nothing for it to commit.")
    return root, ""


def _is_within(path, root):
    try:
        Path(path).resolve().relative_to(root)
        return True
    except (ValueError, OSError):
        return False


def _blocked(repo):
    """Why this repository must not be committed to right now, or ""."""
    code, head, _ = _git(repo, "symbolic-ref", "--quiet", "HEAD")
    if code != 0 or not head:
        return ("HEAD is detached. A commit here would be unreachable from any "
                "branch.")
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD",
                   "rebase-merge", "rebase-apply"):
        if (repo / ".git" / marker).exists():
            return (f"a {marker} is present, so an operation is already in progress. "
                    f"Finish it and commit the delivered files by hand.")
    code, staged, _ = _git(repo, "diff", "--cached", "--name-only")
    if code == 0 and staged:
        return (f"{len(staged.splitlines())} file(s) are already staged by somebody "
                f"else. Committing now would include them under this message.")
    return ""


def ship(delivered, message, log_fn=None):
    """Stage, commit and optionally push the delivered files. Returns a note.

    `delivered` is the exact list of paths delivery wrote. Nothing else is staged, ever.
    """
    note = _ship(delivered, message, log_fn=log_fn)
    if log_fn:
        log_fn(f"shipping: {note}")
    return note


def _ship(delivered, message, log_fn=None):
    paths_ = [Path(p) for p in (delivered or []) if p]
    if not paths_:
        return "nothing was delivered, so nothing was committed."

    repo, why = _repo_of(paths_)
    if repo is None:
        return why

    blocked = _blocked(repo)
    if blocked:
        return f"refused: {blocked}"

    inside = [p for p in paths_ if _is_within(p, repo)]
    rel = [str(Path(p).resolve().relative_to(repo)) for p in inside]

    code, _out, err = _git(repo, "add", "--", *rel)
    if code != 0:
        return f"could not stage the delivered files: {err[:200]}"

    code, staged, _ = _git(repo, "diff", "--cached", "--name-only")
    if code != 0:
        return f"could not read the index: {staged[:200]}"
    if not staged:
        return (f"the {len(rel)} delivered file(s) are already committed and "
                f"unchanged; nothing to do.")

    # The hook path matters: this repository's sibling projects strip assistant
    # attribution in `commit-msg`, and a daemon bypassing that would be the one
    # committer in the project that does.
    code, _out, err = _git(repo, "commit", "-m", message)
    if code != 0:
        return f"the commit was refused: {err[:300]}"
    _code, sha, _ = _git(repo, "rev-parse", "--short", "HEAD")

    if not config.SHIP_PUSH:
        return (f"committed {len(staged.splitlines())} file(s) as {sha}. "
                f"PAPER_SHIP_PUSH is off, so it was not pushed.")

    code, _out, err = _git(repo, "push", timeout=300)
    if code != 0:
        return (f"committed as {sha} but the push failed: {err[:300]} The commit is "
                f"local and safe; push it by hand.")
    return f"committed {len(staged.splitlines())} file(s) as {sha} and pushed."


def message_for(project_rec, paper_num, title, delivered):
    """The commit message. Says what shipped and what it is, in that order."""
    names = sorted({Path(p).name for p in (delivered or [])})
    body = "\n".join(f"  {n}" for n in names)
    return (f"{title}: delivered by Paper-Writer\n\n"
            f"Project {project_rec.get('project_id')}, paper {paper_num}. "
            f"{len(names)} file(s):\n\n{body}\n\n"
            f"Written and gated by the harness. The author's report beside the "
            f"manuscript records what was checked, how the prose measures, and any "
            f"issue a section shipped still holding.\n")
