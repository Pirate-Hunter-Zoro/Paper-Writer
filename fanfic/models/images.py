"""The single seam every stage uses to get an image drawn.

Thin by design: it forwards to `providers/image_browser.py`, which asks Gemini for the
picture through a real signed-in browser session rather than a billed API key. Stages
know none of that; they name a prompt, a path and some reference sheets.

Three outcomes, and each means something different to the book:

  * an image on disk that passed the sanity checks,
  * `QuotaExceeded` — the engine defers and comes back; a picture must never block a
    book,
  * `RuntimeError` — this attempt will not come out, so the caller drops a rung down
    the simplification ladder. `NotSignedIn` is the subclass that needs a human, and
    it is re-exported here so the engine can say so precisely instead of retrying a
    thing that cannot succeed.
"""

from .. import providers
from ..providers.image_browser import NotSignedIn  # noqa: F401  (re-exported)


def is_configured():
    """Whether the browser session is ready to draw.

    The inert-until-the-session-exists contract: the engine calls this to give a
    precise reason before burning a render attempt."""
    return providers.image().is_configured()


def unconfigured_reason():
    """A sentence naming what is missing, or None. Names the script that fixes it."""
    return providers.image().missing_prerequisite()


def generate(prompt, out_path, references=None, timeout=None, log_fn=None,
             aspect=None):
    """Draw one image and write it to `out_path`.

    `references` are the locked reference-sheet paths and the source art that keep
    recurring characters consistent — the whole answer to the project's visual-drift
    problem. They are uploaded to the chat as real attachments, so they condition the
    render exactly as they did over the API."""
    return providers.image().generate(
        prompt, out_path, references=references, timeout=timeout, log_fn=log_fn,
        aspect=aspect)
