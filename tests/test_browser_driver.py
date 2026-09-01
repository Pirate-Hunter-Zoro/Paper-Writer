"""The browser picture driver, exercised against a real Chrome and a fake Gemini.

These spawn an actual headless Chrome per case, so they cost seconds rather than
milliseconds and are **opt-in**:

    FANFIC_BROWSER_TESTS=1 python3 -m unittest discover -s tests

Skipped otherwise, so the fast suite stays fast and a machine with no Chrome is not
failing tests about something it cannot run. That is a real trade — an opt-in test is
a test that does not run — so it is mitigated by `scripts/check-browser.sh`, which runs
exactly this file and is the documented thing to run after touching the driver.

## What these prove, and what they cannot

`tools/gemini_art.js` drives somebody else's web app over a session only a human can
create. Everything about it *except the selectors* is ordinary code: Chrome launch, the
CDP plumbing, the signed-in/signed-out state machine, prompt insertion into a
rich-text composer, reference upload through a hidden file input, waiting for
generation to finish, three download fallbacks, the `kind` contract, and the sanity
floor. `tests/fixtures/gemini_page.py` serves a page with the same *shape*, so all of
that is testable and repeatable.

**They cannot prove the selectors still match Google's markup.** That has exactly one
answer and it is a live render on a signed-in account. Nothing here should be mistaken
for it — see `scripts/check-browser.sh --live`.
"""

import support                                    # noqa: F401  (redirects state first)

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from gemini_page import serve                                     # noqa: E402

from fanfic import config                                         # noqa: E402
from fanfic.errors import QuotaExceeded                           # noqa: E402
from fanfic.models import images                                  # noqa: E402
from fanfic.providers import image_browser                        # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ENABLED = os.environ.get("FANFIC_BROWSER_TESTS", "").strip() not in ("", "0", "false")
CHROME = os.environ.get(
    "FANFIC_CHROME_BIN",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

reason = ("set FANFIC_BROWSER_TESTS=1 to run the browser driver tests"
          if not ENABLED else "Chrome not installed")


@unittest.skipUnless(ENABLED and os.path.exists(CHROME), reason)
class DriverAgainstAFakeGemini(unittest.TestCase):
    """One Chrome per case. Slow, and worth it: this is the only automated coverage the
    picture path has."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port = serve()
        cls.tmp = Path(tempfile.mkdtemp(prefix="fanfic-browser-"))
        cls.profile = cls.tmp / "profile"
        cls.profile.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def run_driver(self, scenario, out, refs=(), timeout=45, prompt="a red fox",
                   env_extra=None):
        """Run the driver against one fixture scenario. Returns its parsed JSON."""
        env = dict(os.environ)
        env.update(env_extra or {})
        env["GEMINI_PROFILE_DIR"] = str(self.profile)
        env["GEMINI_ART_URL"] = f"http://127.0.0.1:{self.port}/?scenario={scenario}"
        env.pop("GEMINI_ART_HEADFUL", None)
        cmd = [os.environ.get("FANFIC_NODE_BIN", "node"),
               str(ROOT / "tools" / "gemini_art.js"),
               "--out", str(out), "--prompt", prompt, "--timeout", str(timeout)]
        for ref in refs:
            cmd += ["--ref", str(ref)]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env,
                              timeout=timeout + 60)
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        self.assertTrue(lines, f"driver printed nothing; stderr: {proc.stderr[:400]}")
        return json.loads(lines[-1])

    # --- the happy path ------------------------------------------------------

    def test_a_render_is_found_and_saved(self):
        out = self.tmp / "ok.png"
        result = self.run_driver("ok", out)
        self.assertTrue(result["ok"], result)
        self.assertEqual((result["width"], result["height"]), (1024, 1536))
        self.assertEqual(result["mime"], "image/png")
        self.assertTrue(out.exists())
        self.assertEqual(len(out.read_bytes()), result["bytes"])

    def test_the_saved_file_clears_the_sanity_floor(self):
        """The floor and the fixture have to agree about what a real render looks like.
        An earlier fixture filled a flat colour, which compressed to under 8 KB at full
        dimensions — so this assertion passed against a file nothing like Gemini's
        output. The fixture is noisy now, and this is what would catch that drift."""
        out = self.tmp / "floor.png"
        self.run_driver("ok", out)
        self.assertIsNone(image_browser.looks_like_art(out))
        self.assertGreater(len(out.read_bytes()), config.IMAGE_MIN_BYTES)

    def test_the_prompt_actually_arrives_in_the_composer(self):
        """`Input.insertText` rather than setting `innerText`, because a rich-text
        composer tracks its own model and ignores a DOM write — the send button stays
        disabled and nothing is ever sent. A silently empty prompt would render
        *something*, which is the worst version of this bug."""
        out = self.tmp / "prompt.png"
        result = self.run_driver("ok", out, prompt="a heron on a wet rooftop")
        self.assertTrue(result["ok"], result)
        # The fixture echoes what it received into the response container, and the
        # driver reads that container back as `PROBE_TEXT` on failure — so a mismatch
        # would surface as a timeout rather than silently. Proven by the render landing.

    # --- the thing that makes it a driver rather than a scraper ---------------

    def test_it_waits_for_generation_to_finish(self):
        """The image is in the DOM while the model is still working. Grabbing the first
        big image that appears saves a half-drawn one, and a half-drawn picture passes
        every mechanical check there is — only a person notices."""
        out = self.tmp / "slow.png"
        result = self.run_driver("slow", out, timeout=45)
        self.assertTrue(result["ok"], result)
        self.assertEqual((result["width"], result["height"]), (1024, 1536))

    def test_the_biggest_candidate_wins(self):
        """Gemini shows a thumbnail strip beside the full render. The one worth keeping
        is the one with the most pixels in it."""
        out = self.tmp / "two.png"
        result = self.run_driver("two", out)
        self.assertTrue(result["ok"], result)
        self.assertEqual((result["width"], result["height"]), (1024, 1536))

    def test_a_blob_url_is_downloaded(self):
        """The first of the three download fallbacks. A `blob:` src cannot be fetched
        from outside the page at all, so this arm is the only one that can serve it."""
        out = self.tmp / "blob.png"
        result = self.run_driver("blob", out)
        self.assertTrue(result["ok"], result)
        self.assertTrue(out.exists())
        self.assertEqual(image_browser.dimensions(out.read_bytes()), (1024, 1536))

    def test_an_uploaded_reference_is_never_saved_as_the_render(self):
        """The nastiest bug this driver has had, pinned so it cannot come back.

        The real app renders an uploaded reference at full size inside
        `user-query-file-preview`, and answers a portrait reference with a portrait
        render — so the attachment and the render are routinely THE SAME DIMENSIONS,
        and the old "biggest candidate wins" rule chose between them at random. It lost
        the coin flip on the first live reference render and wrote the reference back
        to disk as though it were the picture.

        What makes it worth a dedicated test is that it is invisible: every scene in a
        book would silently be the character sheet again, `ok:true` every time, the
        sanity floor satisfied, and the vision critic would even PASS it for identity —
        it is, after all, exactly the right character. Two renders having the same md5
        was the only symptom."""
        sheet = self.tmp / "decoy-sheet.png"
        sheet.write_bytes(_fixture_png(1024, 1536))
        out = self.tmp / "decoy.png"
        result = self.run_driver("decoy", out, refs=[sheet])
        self.assertTrue(result["ok"], result)
        # Digests, not raw bytes: these are multi-megabyte images and a failed
        # assertEqual on the bytes themselves buries the run in 25 MB of repr.
        import hashlib
        saved = hashlib.md5(out.read_bytes()).hexdigest()
        uploaded = hashlib.md5(sheet.read_bytes()).hexdigest()
        self.assertEqual((result["width"], result["height"]), (1024, 1536))
        self.assertNotEqual(saved, uploaded,
                            "the driver saved the uploaded reference, not the render")

    def test_reference_pictures_are_uploaded(self):
        """The load-bearing half of visual consistency: the locked character sheets are
        attached to the chat so the render is conditioned on the real faces. A render
        that silently lost them looks fine and is wrong, which is why the driver treats
        a failed attach as a hard error rather than degrading."""
        sheets = []
        for name in ("ruby", "weiss"):
            path = self.tmp / f"{name}.png"
            path.write_bytes(_fixture_png(512, 512))
            sheets.append(path)
        out = self.tmp / "refs.png"
        result = self.run_driver("ok", out, refs=sheets)
        self.assertTrue(result["ok"], result)

    # --- the failure contract ------------------------------------------------

    def test_a_refusal_is_reported_as_a_refusal(self):
        result = self.run_driver("refused", self.tmp / "refused.png")
        self.assertFalse(result["ok"])
        self.assertEqual(result["kind"], "refused")

    def test_a_failed_upload_is_reported_as_a_failed_upload(self):
        """A chip that APPEARED is not a chip that UPLOADED, and the difference cost
        this book two multi-hour outages.

        When an upload fails Gemini still renders a chip — carrying an error icon — so
        a check that counts previews is satisfied and the driver sends. The send is
        then silently ignored, and the render burns its entire deadline before
        reporting `no image after Ns; last response text: ""`, which reads as "Gemini
        said nothing" and means "we were never able to ask". At 420s x 3 attempts that
        is 21 minutes per slot, producing nothing.

        Reported as `upload_failed` and NOT as `bad_reference`, because the two want
        different remedies. A rejected picture is permanent and should be shed; a
        failed transfer is transient and worth simply asking again with the references
        intact. Conflating them costs a character their locked face for the rest of
        the book on the strength of one bad second.

        The send button is NOT disabled during this, which is what made it hard: two
        earlier fixes retried a click against a control that was never disabled."""
        sheet = self.tmp / "sheet.png"
        sheet.write_bytes(_fixture_png(1024, 1536))
        result = self.run_driver("uploadfail", self.tmp / "nope.png",
                                 refs=[sheet], timeout=25)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["kind"], "upload_failed",
                         f"a failed upload must be named, not timed out on: {result}")

    def test_a_healthy_upload_is_not_mistaken_for_a_failed_one(self):
        """The other direction, and the one that would be invisible.

        A false positive here sheds every reference on a working page and returns a
        picture that looks fine and is of the wrong person — the one failure this
        project cannot see. So the error check is scoped inside the chips."""
        sheets = [self.tmp / "a.png", self.tmp / "b.png"]
        for sheet in sheets:
            sheet.write_bytes(_fixture_png(1024, 1536))
        out = self.tmp / "healthy.png"
        result = self.run_driver("ok", out, refs=sheets)
        self.assertTrue(result["ok"], f"references were shed on a healthy page: {result}")

    def test_a_usage_ceiling_is_reported_as_quota(self):
        result = self.run_driver("quota", self.tmp / "quota.png")
        self.assertFalse(result["ok"])
        self.assertEqual(result["kind"], "quota")

    def test_a_guest_session_is_not_mistaken_for_a_refusal(self):
        """THE trap this driver was built around. A signed-out visitor gets a working
        chat on a cut-down model that answers text and declines every picture, in the
        language of a policy refusal. Read as `refused`, the retry ladder burns every
        rung on it and the book quietly goes text-only with nothing saying why.

        The fixture's guest page has a composer and a "Sign in" link and no account
        chip — exactly what gemini.google.com serves — so this is the real case."""
        result = self.run_driver("signedout", self.tmp / "guest.png")
        self.assertFalse(result["ok"])
        self.assertEqual(result["kind"], "not_signed_in")
        self.assertIn("gemini-login.sh", result["reason"])

    def test_a_page_that_never_answers_times_out_as_transient(self):
        """Not `refused`: nothing was said about this prompt, so the slot should come
        back rather than dropping a rung."""
        result = self.run_driver("silent", self.tmp / "silent.png", timeout=12)
        self.assertFalse(result["ok"])
        self.assertEqual(result["kind"], "transient")

    def test_an_empty_reply_is_concluded_rather_than_waited_out(self):
        """Twice live, Gemini finished with a response bubble containing nothing —
        no picture, no words, no refusal. The wait loop had no exit condition for that
        state, so it burned the entire ten-minute budget on silence, twice.

        The assertion that matters is the CLOCK: it must give up in seconds."""
        import time
        started = time.monotonic()
        result = self.run_driver("empty", self.tmp / "empty.png", timeout=120)
        elapsed = time.monotonic() - started
        self.assertFalse(result["ok"])
        self.assertLess(elapsed, 60,
                        f"took {elapsed:.0f}s to conclude nothing was coming")

    def test_a_page_stuck_working_forever_is_given_up_on(self):
        """The mirror of the empty-reply hang, and the other one seen live: the page
        says "Creating your image" and simply never stops. A slow render and a stuck
        one look identical for the first thirty seconds, so the driver waits — but not
        for the entire ten-minute budget, which it did twice."""
        import time
        env_extra = {"GEMINI_ART_WORKING_MAX_MS": "4000"}
        started = time.monotonic()
        result = self.run_driver("stuck", self.tmp / "stuck.png", timeout=120,
                                 env_extra=env_extra)
        elapsed = time.monotonic() - started
        self.assertFalse(result["ok"])
        self.assertLess(elapsed, 60, f"waited {elapsed:.0f}s on a stuck page")

    def test_a_thumbnail_is_never_saved_as_the_render(self):
        """Belt and braces: the driver's own 256px floor should reject it before the
        Python floor ever sees it."""
        out = self.tmp / "tiny.png"
        result = self.run_driver("tiny", out, timeout=12)
        self.assertFalse(result["ok"], "a 64x64 image is not a render")
        self.assertFalse(out.exists())


@unittest.skipUnless(ENABLED and os.path.exists(CHROME), reason)
class ThePythonSideAgainstARealDriver(unittest.TestCase):
    """The full seam, with no mocks anywhere: `models.images.generate` -> the provider
    -> a real Node process -> a real Chrome -> a fake Gemini -> a file on disk.

    Everything else in the suite stubs one side or the other. This is the only test
    that proves the two languages actually agree."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.port = serve()
        cls.tmp = Path(tempfile.mkdtemp(prefix="fanfic-seam-"))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self._profile, self._url = config.GEMINI_PROFILE_DIR, os.environ.get(
            "GEMINI_ART_URL")
        config.GEMINI_PROFILE_DIR = self.tmp / "profile"
        config.GEMINI_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        config.GEMINI_PROFILE_DIR = self._profile
        if self._url is None:
            os.environ.pop("GEMINI_ART_URL", None)
        else:
            os.environ["GEMINI_ART_URL"] = self._url

    def _scenario(self, name):
        os.environ["GEMINI_ART_URL"] = (
            f"http://127.0.0.1:{self.port}/?scenario={name}")

    def test_a_picture_comes_back_through_the_whole_seam(self):
        self._scenario("ok")
        out = self.tmp / "seam.png"
        logged = []
        images.generate("a red fox in a snowy forest", out, aspect="2:3",
                        log_fn=logged.append)
        self.assertTrue(out.exists())
        self.assertEqual(image_browser.dimensions(out.read_bytes()), (1024, 1536))
        self.assertTrue(any("1024x1536" in line for line in logged), logged)

    def test_the_aspect_ratio_reaches_the_page_as_words(self):
        """A chat window has no aspect parameter, so it has to be asked for in the
        prompt. A silently dropped ratio produces a book of square pictures and no
        error anywhere — the failure with no symptom."""
        self._scenario("ok")
        out = self.tmp / "aspect.png"
        # The driver deletes its prompt file on the way out, so capture it in flight.
        seen = {}
        real = image_browser.subprocess.run

        def spy(cmd, **kwargs):
            seen["prompt"] = Path(cmd[cmd.index("--prompt-file") + 1]).read_text()
            return real(cmd, **kwargs)
        image_browser.subprocess.run = spy
        try:
            images.generate("a red fox", out, aspect="2:3")
        finally:
            image_browser.subprocess.run = real
        self.assertIn("2:3", seen["prompt"])
        self.assertIn("a red fox", seen["prompt"])

    def test_a_ceiling_becomes_QuotaExceeded_so_the_engine_defers(self):
        self._scenario("quota")
        with self.assertRaises(QuotaExceeded):
            images.generate("a red fox", self.tmp / "q.png")

    def test_a_guest_session_becomes_NotSignedIn_so_a_human_is_told(self):
        self._scenario("signedout")
        with self.assertRaises(images.NotSignedIn) as caught:
            images.generate("a red fox", self.tmp / "g.png")
        self.assertIn("gemini-login.sh", str(caught.exception))

    def test_a_refusal_becomes_a_plain_RuntimeError_so_the_ladder_steps_down(self):
        self._scenario("refused")
        with self.assertRaises(RuntimeError) as caught:
            images.generate("a red fox", self.tmp / "r.png")
        self.assertNotIsInstance(caught.exception, QuotaExceeded)
        self.assertNotIsInstance(caught.exception, images.NotSignedIn)

    def test_nothing_is_left_on_disk_when_a_render_fails(self):
        """`render_scene` checks `staged.exists()` to decide whether it has a picture.
        A leftover file is a picture as far as every later stage is concerned."""
        self._scenario("refused")
        out = self.tmp / "leftover.png"
        with self.assertRaises(RuntimeError):
            images.generate("a red fox", out)
        self.assertFalse(out.exists())
        self.assertFalse(out.with_suffix(".prompt.txt").exists(),
                         "the scratch prompt file must not survive either")


def _fixture_png(width, height):
    from gemini_page import png
    return png(width, height)


if __name__ == "__main__":
    unittest.main()
