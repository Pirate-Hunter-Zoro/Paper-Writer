"""The image provider: Gemini, driven through a real signed-in browser.

## Why there is no image API in this repository any more

There was one. It called `generativelanguage.googleapis.com` with a billed key and
it worked, in the sense that a PNG came back for every request. The pictures were the
worst thing in the finished books: samey between renders, flat, and often enough
distracting enough that a chapter read better without them. Judged honestly against
the only question that matters — does this picture make the book better — the answer
was no often enough that the money was buying a defect.

The same model, asked the same thing at gemini.google.com, does not have that problem.
That is not a prompt difference and not a model difference; it is the difference
between a bare endpoint and the product built around it. So this fleet stopped paying
for the endpoint and drives the product: `tools/gemini_art.js` opens Chrome on a
profile that a human signed in to once, asks for the picture, waits, and saves it.

What that buys, beyond better art:

  * **No credential on disk.** No key file, no `GEMINI_API_KEY`, nothing to leak and
    nothing to rotate. The credential is a cookie jar in a directory owned by the
    person whose account it is.
  * **No bill.** Pictures used to be the only line item in this fleet that cost real
    money, and the picture budget was denominated in dollars. It is a count now —
    a runaway stop, not a wallet.

What it costs is honesty about a new failure: a browser session expires, and markup
moves under us. Both are visible and both are recoverable — see `NotSignedIn`.

## Three outcomes, and what each does to a book

Unchanged from the HTTP provider this replaces, because the engine above is written
against them:

  * success        -> an image at `out_path` that passed the sanity checks below.
  * QuotaExceeded  -> Gemini says come back later. The engine DEFERS the slot and
                      retries; a picture must never block a book.
  * RuntimeError   -> deterministic for this attempt: a refusal, a render we could
                      not download, a session that is not signed in. The caller drops
                      a rung down the simplification ladder and tries again.

## "Download them if they look okay"

Two different judgements, deliberately kept apart:

  * **Is this an image at all?** Decided here, cheaply and mechanically — real magic
    bytes, enough of them, and big enough to print. A one-kilobyte 300x300 spinner
    that got saved because it was `<img>`-shaped is the failure this catches, and it
    is worth catching here because it costs nothing and a Claude call does not.
  * **Is this the RIGHT picture?** Decided by `illustration.vision_verdict`, which is
    Claude looking at the render next to the reference art. That loop already exists
    and is unchanged.

Stdlib only, like everything else here: `subprocess` and `json`. The browser half is
Node with no dependencies either, so a fresh mini needs Chrome and nothing else.
"""

import json
import os
import struct
import subprocess

from .. import config
from ..errors import QuotaExceeded
from .base import Capability

NAME = "gemini-browser"

# References are attached to the chat as real uploaded files, so the locked sheets
# condition the render exactly as they did over the API. This is the load-bearing
# half of visual consistency and the reason a browser was worth the trouble at all —
# a driver that could not upload would have been a downgrade, not a change.
CAPABILITY = Capability(supports_references=True)


class NotSignedIn(RuntimeError):
    """The Chrome profile has no live Gemini session.

    Its own class because it is the one image failure a human has to clear, and the
    fix is thirty seconds long: run `scripts/gemini-login.sh`. Retrying cannot help,
    so the engine must not treat it as a transient blip and hammer it — it says so
    once, loudly, in a message that names the script."""


def driver_path():
    """The Node driver. Alongside the code so it moves with the repo."""
    return config.PROJECT_ROOT / "tools" / "gemini_art.js"


def is_configured():
    """Whether a render could plausibly work: Node, Chrome, and a profile directory
    that has been signed in at least once.

    The inert-until-the-session-exists contract, which is the same shape the key-file
    check had — the engine calls this to give a precise reason BEFORE burning a render
    attempt, rather than discovering the problem as a mysterious timeout."""
    return not missing_prerequisite()


def missing_prerequisite():
    """A sentence naming what is missing, or None if everything is in place.

    Ordered by how far it is from being fixed: a missing browser is an install, a
    missing profile is one script, and a signed-out profile is one sign-in."""
    if not driver_path().exists():
        return f"the browser driver is missing: {driver_path()}"
    if not _which(config.NODE_BIN):
        return (f"node is not on PATH (looked for {config.NODE_BIN!r}). The image "
                f"driver is a Node script; install Node 22+ or set FANFIC_NODE_BIN.")
    if not os.path.exists(config.CHROME_BIN):
        return (f"Chrome is not at {config.CHROME_BIN}. Install Google Chrome or set "
                f"FANFIC_CHROME_BIN.")
    if not config.GEMINI_PROFILE_DIR.exists():
        return (f"no signed-in Chrome profile at {config.GEMINI_PROFILE_DIR}. Run "
                f"scripts/gemini-login.sh once and pictures start drawing themselves.")
    return None


def _which(binary):
    """Whether a binary resolves on the fleet's PATH."""
    if os.path.sep in binary:
        return os.path.exists(binary)
    for directory in config.EXTRA_PATH + os.environ.get("PATH", "").split(":"):
        if directory and os.path.exists(os.path.join(directory, binary)):
            return True
    return False


def _env():
    """The driver's environment: the fleet's PATH, plus where the session lives."""
    env = os.environ.copy()
    env["PATH"] = ":".join(config.EXTRA_PATH) + ":" + env.get("PATH", "")
    env["GEMINI_PROFILE_DIR"] = str(config.GEMINI_PROFILE_DIR)
    env["CHROME_BIN"] = config.CHROME_BIN
    if config.IMAGE_HEADFUL:
        env["GEMINI_ART_HEADFUL"] = "1"
    if config.IMAGE_DIAG_DIR:
        env["GEMINI_ART_DIAG_DIR"] = str(config.IMAGE_DIAG_DIR)
    # Absent means the driver dumps nothing, which is a supported choice rather than a
    # misconfiguration — so it is simply not passed.
    return env


# --- Does it look like a picture? --------------------------------------------

def dimensions(blob):
    """(width, height) from an image's own header, or None if it has no readable one.

    Header parsing rather than a library, because the whole project runs on a bare
    system Python and a dependency that has to be installed is a dependency that will
    be missing at 2 a.m. Three formats is all Gemini serves."""
    try:
        if blob[:8] == b"\x89PNG\r\n\x1a\n" and blob[12:16] == b"IHDR":
            return struct.unpack(">II", blob[16:24])
        if blob[:3] == b"\xff\xd8\xff":
            i = 2
            while i + 9 < len(blob):
                if blob[i] != 0xFF:
                    i += 1
                    continue
                marker, size = blob[i + 1], struct.unpack(">H", blob[i + 2:i + 4])[0]
                # SOF0-SOF15, excluding the four that are not frame headers.
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">HH", blob[i + 5:i + 9])
                    return w, h
                i += 2 + size
        if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
            if blob[12:16] == b"VP8X":
                w = int.from_bytes(blob[24:27], "little") + 1
                h = int.from_bytes(blob[27:30], "little") + 1
                return w, h
            if blob[12:16] == b"VP8 ":
                w = struct.unpack("<H", blob[26:28])[0] & 0x3FFF
                h = struct.unpack("<H", blob[28:30])[0] & 0x3FFF
                return w, h
            if blob[12:16] == b"VP8L":
                bits = int.from_bytes(blob[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    except (struct.error, IndexError):
        return None
    return None


def mime_of(blob):
    """An image's media type from its MAGIC BYTES, never from its filename.

    Load-bearing rather than tidy. Every path in this project is named `.png` — the
    filenames are computed in `paths.py` and the epub is assembled from them — but
    **Gemini returns JPEG**, so a `.png` on disk routinely holds JPEG bytes. The epub
    manifest has to declare what a file actually *is*, and a manifest that says
    `image/png` over JPEG data is an invalid EPUB that a strict reader may refuse.

    Renaming the files was the alternative and it is worse: the path helpers, the
    binder's glob, the retry sidecars and the vision critic all agree on `.png` today,
    and a filename is not what EPUB validates against anyway."""
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if blob[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    if blob[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def looks_like_art(path):
    """Whether the downloaded file is worth keeping, or a sentence saying why not.

    Deliberately mechanical. This is not "is it a good picture" — that is Claude's
    job two steps later, with the reference art in front of it. This is the far
    dumber question the browser makes newly necessary: a page can hand you a spinner,
    a placeholder, or a 404 body, and all three are `<img>`-shaped."""
    try:
        blob = path.read_bytes()
    except OSError as exc:
        return f"unreadable: {exc}"
    if len(blob) < config.IMAGE_MIN_BYTES:
        return (f"only {len(blob)} bytes — too small to be a render "
                f"(floor is {config.IMAGE_MIN_BYTES})")
    size = dimensions(blob)
    if size is None:
        return "not a PNG, JPEG or WebP — the download was not an image"
    width, height = size
    if width < config.IMAGE_MIN_EDGE or height < config.IMAGE_MIN_EDGE:
        return (f"{width}x{height} — smaller than the {config.IMAGE_MIN_EDGE}px floor; "
                f"this is a thumbnail or a placeholder, not the render")
    return None


# --- The render --------------------------------------------------------------

def _instruction(aspect):
    """The lead line, which the API used to express as a parameter.

    `responseModalities: ["IMAGE"]` and `imageConfig.aspectRatio` do not exist in a
    chat window; both have to be asked for in words. Kept to one short line at the top
    so the prompt the art director wrote is still what the model mostly reads."""
    shape = f" Compose it in a {aspect} aspect ratio." if aspect else ""
    return ("Generate a single illustration for this description, as one image."
            f"{shape} Reply with the picture only — no commentary, no alternatives, "
            "no text inside the image.")


def generate(prompt, out_path, references=None, timeout=None, log_fn=None,
             aspect=None):
    """Draw one image by driving the browser, and write it to `out_path`.

    Raises `NotSignedIn` (a `RuntimeError`) when the profile needs a human,
    `QuotaExceeded` when Gemini says come back later, and `RuntimeError` for a render
    that will not come out this way. See the module docstring for what each does to
    the book."""
    def note(msg):
        if log_fn:
            log_fn(msg)

    problem = missing_prerequisite()
    if problem:
        raise NotSignedIn(f"image backend not ready: {problem}")

    timeout = timeout or config.IMAGE_RENDER_TIMEOUT_SEC
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()            # so "file present" means "this render produced it"

    refs = [str(r) for r in (references or []) if r and r.exists()]
    # The prompt travels as a FILE rather than as an argv string. A scene prompt is
    # ~2KB of staging, cast identity and style; putting that on a command line means it
    # is visible in `ps` to every process on the machine and one shell metacharacter
    # away from a quoting bug. It lands beside the render, which is always inside the
    # hidden staging directory, and is removed either way — see the `finally`.
    prompt_file = out_path.with_suffix(".prompt.txt")
    prompt_file.write_text(f"{_instruction(aspect)}\n\n{prompt}", encoding="utf-8")

    cmd = [config.NODE_BIN, str(driver_path()),
           "--out", str(out_path),
           "--prompt-file", str(prompt_file),
           "--timeout", str(int(timeout))]
    for ref in refs[:config.IMAGE_MAX_UPLOADS]:
        cmd += ["--ref", ref]

    try:
        _render_with_retry(cmd, prompt_file, prompt, aspect, refs, out_path, timeout,
                           note)
    finally:
        # Scratch, and it must go whatever happened. Splitting the driver call out of
        # this function once moved the cleanup into the success path alone, and a
        # failed render started leaving a `.prompt.txt` beside the image it did not
        # produce — inside the staging directory the binder reads.
        prompt_file.unlink(missing_ok=True)


def _render_with_retry(cmd, prompt_file, prompt, aspect, refs, out_path, timeout,
                       note):
    """One render, with the one retry that is worth making automatically."""
    result = _run(cmd, timeout, note)

    # A REJECTED UPLOAD IS NOT A REJECTED PROMPT, and treating them alike costs a
    # character their sheet. Gemini refuses some reference pictures outright — a
    # photoreal 3D promotional render reads to its classifier as a photograph of a
    # real person, which is how Satele Shan's wiki art was refused three times while
    # Orgus Din's stylised art went through. The prompt was never the problem, so
    # simplifying it (the generic ladder's answer) throws away a good composition to
    # fix something that is not broken.
    #
    # So: shed the references and ask again. The result is a prose-anchored render
    # rather than an anchored one, which is the documented fallback and is "merely
    # imprecise rather than actively depicting somebody else" — and it is a great deal
    # better than dropping to an empty-room rung.
    if refs and (result.get("kind") == "bad_reference"):
        note(f"Gemini refused {len(refs)} reference picture(s) — likely read as "
             f"photographs of real people. Redrawing from the description alone; the "
             f"result is anchored on prose, not on art.")
        prompt_file.write_text(f"{_instruction(aspect)}\n\n{prompt}", encoding="utf-8")
        bare = [c for c in cmd if c != "--ref"]
        bare = [c for c in bare if c not in refs]
        result = _run(bare, timeout, note)
        refs = []

    if not result.get("ok"):
        _raise_for(result, note)

    problem = looks_like_art(out_path)
    if problem:
        out_path.unlink(missing_ok=True)
        raise RuntimeError(f"the browser saved something that is not usable art — "
                           f"{problem}")

    note(f"drew {result.get('width')}x{result.get('height')} "
         f"{result.get('mime', 'image')} ({result.get('bytes', 0) // 1024} KB) "
         f"through the browser session"
         + (f", conditioned on {len(refs)} reference picture(s)" if refs else ""))


def _run(cmd, timeout, note):
    """One driver invocation. Returns its parsed result dict."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              # The driver kills its own Chrome on the way out; this
                              # is the outer stop for a browser that hung so hard it
                              # never got there.
                              timeout=timeout + config.IMAGE_DRIVER_GRACE_SEC,
                              env=_env(), cwd=str(config.PROJECT_ROOT))
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"the browser did not return within {timeout}s")
    except FileNotFoundError:
        raise NotSignedIn(f"node binary not found: {config.NODE_BIN}")
    return _result(proc)


def _result(proc):
    """The driver's last stdout line as JSON.

    Last line rather than the whole of stdout, because Chrome writes its own noise to
    the same stream on some machines and a leading warning would otherwise turn every
    successful render into a parse error."""
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    for line in reversed(lines):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    detail = ((proc.stderr or "").strip() or (proc.stdout or "").strip())[:400]
    return {"ok": False, "kind": "transient",
            "reason": f"the image driver said nothing usable (exit "
                      f"{proc.returncode}): {detail or 'no output'}"}


def _raise_for(result, note):
    """Turn the driver's `kind` into the exception the engine is written against."""
    kind = result.get("kind") or "transient"
    reason = result.get("reason") or "the browser could not produce a picture"
    if kind == "quota":
        note(f"Gemini is rate-limiting this session: {reason[:200]}")
        raise QuotaExceeded(f"gemini session limit: {reason[:300]}",
                            retry_after=config.IMAGE_QUOTA_BACKOFF_SEC)
    if kind in ("not_signed_in", "setup"):
        raise NotSignedIn(reason)
    if kind == "refused":
        # A refusal is about THIS wording, so the ladder in `illustration` has
        # somewhere to go: a plainer prompt, then a picture of the empty room.
        raise RuntimeError(f"Gemini declined to draw this prompt: {reason}")
    raise RuntimeError(reason)
