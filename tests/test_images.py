"""The image backend, and the promise that images never block a book.

Two halves:

  * `models.images.generate` against the BROWSER backend, with `subprocess.run`
    monkeypatched so no Chrome is launched. The driver's `kind` field is the whole
    contract between the two languages, and each value has to land on the exception
    the engine above is written against: a session limit becomes QuotaExceeded, a
    signed-out profile becomes NotSignedIn, a refusal becomes a plain RuntimeError.
    Plus the sanity floor, which is new and which the API path never needed — a web
    page can hand you a spinner, and a spinner is <img>-shaped.
  * the engine's behaviour when those things happen: a quota hit defers and the book
    completes once it clears; an image that will not render parks and the book waits
    for it rather than binding around a hole. Neither ever fails the book.
"""

import base64
import io
import json
import os
import re
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import support

from fanfic import config, paths, states                          # noqa: E402
from fanfic.errors import QuotaExceeded                           # noqa: E402
from fanfic.engine import illustrating                            # noqa: E402
from fanfic.infra import budget, journal                          # noqa: E402
from fanfic.models import images                                  # noqa: E402
from fanfic.providers import image_browser                        # noqa: E402
from fanfic.stages import illustration, refart                    # noqa: E402


def _png(width=1024, height=1536, padding=30000):
    """A PNG with real dimensions in its header, padded past the sanity floor.

    `support.PNG` is a 69-byte 1x1 fixture, which every other test wants and which the
    image provider now correctly rejects — that floor is exactly the thing standing
    between a book and a page of spinners. Only the header is parsed, so the padding
    does not have to be valid pixel data."""
    import struct, zlib
    ihdr = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    chunk = (struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr
             + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr)))
    return b"\x89PNG\r\n\x1a\n" + chunk + b"\x00" * padding


class _FakeProc:
    """What `subprocess.run` returns. The driver's contract is one JSON line on
    stdout, so that is all this carries."""

    def __init__(self, result, returncode=None, stderr="", extra_stdout=""):
        body = json.dumps(result) if isinstance(result, dict) else result
        self.stdout = (extra_stdout + body + "\n") if body is not None else extra_stdout
        self.stderr = stderr
        self.returncode = (returncode if returncode is not None
                           else (0 if isinstance(result, dict) and result.get("ok")
                                 else 1))


class BackendTests(unittest.TestCase):
    """The Python/Node seam. Every case here is a `kind` the driver can report, and
    the assertion is which exception it becomes — because the engine above dispatches
    on the exception and nothing else."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fanfic-img-"))
        # A profile directory that exists is the only prerequisite the tests can
        # satisfy; Chrome and node are checked against the real machine, so those two
        # checks are neutralised rather than faked into a lie.
        self._profile = config.GEMINI_PROFILE_DIR
        config.GEMINI_PROFILE_DIR = self.tmp / "profile"
        config.GEMINI_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._chrome = config.CHROME_BIN
        config.CHROME_BIN = str(self.tmp)          # exists, which is all that is asked
        self._which = image_browser._which
        image_browser._which = lambda _binary: True

    def tearDown(self):
        config.GEMINI_PROFILE_DIR = self._profile
        config.CHROME_BIN = self._chrome
        image_browser._which = self._which

    def _driver(self, proc, captured=None):
        """Stand in for the Node driver, optionally recording the command it was
        given and writing the file a successful render would have written."""
        def fake_run(cmd, **kwargs):
            if captured is not None:
                captured["cmd"] = cmd
                captured["env"] = kwargs.get("env", {})
                prompt_file = Path(cmd[cmd.index("--prompt-file") + 1])
                captured["prompt"] = prompt_file.read_text(encoding="utf-8")
            if getattr(proc, "returncode", 1) == 0:
                out = Path(cmd[cmd.index("--out") + 1])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(_png())
            return proc
        original = image_browser.subprocess.run
        image_browser.subprocess.run = fake_run
        self.addCleanup(lambda: setattr(image_browser.subprocess, "run", original))

    def test_a_missing_session_is_a_refusal_before_any_browser_starts(self):
        """The inert-until-the-session-exists contract, which replaced the old
        inert-until-the-key-file-exists one and does exactly the same job."""
        config.GEMINI_PROFILE_DIR = self.tmp / "never-signed-in"
        started = {"n": 0}

        def must_not_run(cmd, **kwargs):
            started["n"] += 1
            raise AssertionError("a browser must not be started without a session")
        original = image_browser.subprocess.run
        image_browser.subprocess.run = must_not_run
        self.addCleanup(lambda: setattr(image_browser.subprocess, "run", original))

        out = self.tmp / "x.png"
        with self.assertRaises(images.NotSignedIn) as ctx:
            images.generate("a fox knight", out, references=None)
        self.assertIn("gemini-login.sh", str(ctx.exception))
        self.assertEqual(started["n"], 0)
        self.assertFalse(out.exists())

    def test_success_writes_the_file_and_asks_for_the_aspect_ratio_in_words(self):
        """`imageConfig.aspectRatio` does not exist in a chat window, so the shape has
        to be asked for in the prompt. A silently-dropped aspect ratio would produce a
        book of square pictures and no error anywhere."""
        captured = {}
        self._driver(_FakeProc({"ok": True, "bytes": len(_png()),
                                "width": 1024, "height": 1536, "mime": "image/png"}),
                     captured)
        out = self.tmp / "scene.png"
        images.generate("a scene", out, references=None, aspect="2:3")

        self.assertEqual(out.read_bytes(), _png())
        self.assertIn("2:3", captured["prompt"])
        self.assertIn("a scene", captured["prompt"])
        self.assertIn("--out", captured["cmd"])
        # The session lives in the environment, never on a command line that shows up
        # in `ps` for every other process on the machine to read.
        self.assertEqual(captured["env"]["GEMINI_PROFILE_DIR"],
                         str(config.GEMINI_PROFILE_DIR))

    def test_reference_sheets_are_handed_to_the_driver_to_upload(self):
        """The load-bearing half of visual consistency. A render that silently lost
        its references would look fine and be wrong."""
        captured = {}
        self._driver(_FakeProc({"ok": True, "bytes": len(_png()),
                                "width": 1024, "height": 1536}), captured)
        sheet = self.tmp / "ruby-sheet.png"
        sheet.write_bytes(support.PNG)
        images.generate("a scene", self.tmp / "s.png", references=[sheet])
        self.assertIn("--ref", captured["cmd"])
        self.assertIn(str(sheet), captured["cmd"])

    def test_a_reference_that_is_not_on_disk_is_dropped_rather_than_passed(self):
        """Chrome fails the whole upload on one missing path, which would turn a
        stale bible entry into an unrenderable slot."""
        captured = {}
        self._driver(_FakeProc({"ok": True, "bytes": len(_png()),
                                "width": 1024, "height": 1536}), captured)
        images.generate("a scene", self.tmp / "s.png",
                        references=[self.tmp / "gone.png"])
        self.assertNotIn("--ref", captured["cmd"])

    def test_a_session_limit_defers_and_is_never_retried_in_process(self):
        """Same contract the 429 had: hammering a ceiling is what parked chapter 6 of
        the first real novel."""
        calls = {"n": 0}
        proc = _FakeProc({"ok": False, "kind": "quota",
                          "reason": "You've reached your limit for image generation."})

        def counting(cmd, **kwargs):
            calls["n"] += 1
            return proc
        original = image_browser.subprocess.run
        image_browser.subprocess.run = counting
        self.addCleanup(lambda: setattr(image_browser.subprocess, "run", original))

        with self.assertRaises(QuotaExceeded):
            images.generate("x", self.tmp / "q.png", references=None)
        self.assertEqual(calls["n"], 1, "a session limit must not be retried here")

    def test_a_refused_upload_is_retried_without_the_reference(self):
        """A rejected UPLOAD is not a rejected prompt, and conflating them costs a
        character their picture.

        Gemini refuses some reference images outright — a photoreal promotional render
        reads to its classifier as a photograph of a real person. Live, Satele Shan's
        wiki art was refused three times while Orgus Din's stylised art went straight
        through. The prompt was never the problem, so simplifying it (what the generic
        ladder does) discards a good composition to fix something that is not broken.

        The right remedy is to shed the references and ask again: a prose-anchored
        render is the documented fallback, and it beats dropping to an empty room."""
        calls = []
        good = _png()

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if "--ref" in cmd:
                return _FakeProc({"ok": False, "kind": "bad_reference",
                                  "reason": "Sorry I can't help with that image."})
            out = Path(cmd[cmd.index("--out") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(good)
            return _FakeProc({"ok": True, "bytes": len(good),
                              "width": 1024, "height": 1536})
        original = image_browser.subprocess.run
        image_browser.subprocess.run = fake_run
        self.addCleanup(lambda: setattr(image_browser.subprocess, "run", original))

        sheet = self.tmp / "photoreal.png"
        sheet.write_bytes(good)
        out = self.tmp / "retried.png"
        logged = []
        images.generate("a jedi master", out, references=[sheet], log_fn=logged.append)

        self.assertEqual(len(calls), 2, "should try with references, then without")
        self.assertIn("--ref", calls[0])
        self.assertNotIn("--ref", calls[1], "the retry must drop the reference")
        self.assertTrue(out.exists())
        self.assertTrue(any("prose, not on art" in m for m in logged), logged)

    def test_a_refused_upload_with_no_references_is_not_retried_forever(self):
        """Nothing to shed means nothing to retry — it is a plain failure."""
        self._driver(_FakeProc({"ok": False, "kind": "bad_reference",
                                "reason": "can't help with that image"}))
        with self.assertRaises(RuntimeError):
            images.generate("x", self.tmp / "none.png", references=None)

    def test_a_refusal_is_a_skippable_runtime_error(self):
        """It is about THIS wording, so the simplification ladder has somewhere to
        go — a plainer prompt, then a picture of the empty room."""
        self._driver(_FakeProc({"ok": False, "kind": "refused",
                                "reason": "I can't create that image."}))
        with self.assertRaises(RuntimeError) as ctx:
            images.generate("x", self.tmp / "s.png", references=None)
        self.assertNotIsInstance(ctx.exception, QuotaExceeded)
        self.assertNotIsInstance(ctx.exception, images.NotSignedIn)
        self.assertIn("declined", str(ctx.exception))

    def test_a_signed_out_profile_reported_mid_flight_is_still_actionable(self):
        """The session can expire between the check and the render. It must not be
        laundered into a generic failure that the retry ladder then burns rungs on."""
        self._driver(_FakeProc({"ok": False, "kind": "not_signed_in",
                                "reason": "run scripts/gemini-login.sh"}))
        with self.assertRaises(images.NotSignedIn):
            images.generate("x", self.tmp / "s.png", references=None)

    def test_a_driver_that_says_nothing_usable_is_a_failure_with_the_evidence(self):
        """A crashed Node process leaves no JSON. The message has to carry whatever it
        did say, because a headless failure at 3 a.m. leaves nothing else."""
        self._driver(_FakeProc(None, returncode=1,
                               stderr="SyntaxError: unexpected token"))
        with self.assertRaises(RuntimeError) as ctx:
            images.generate("x", self.tmp / "s.png", references=None)
        self.assertIn("SyntaxError", str(ctx.exception))

    def test_chrome_noise_before_the_json_does_not_break_the_result(self):
        """Chrome writes its own warnings to the same stream on some machines, and a
        leading line would otherwise turn every successful render into a parse error."""
        self._driver(_FakeProc({"ok": True, "bytes": len(_png()),
                                "width": 1024, "height": 1536},
                               extra_stdout="[WARNING] dbus not available\n"))
        out = self.tmp / "noisy.png"
        images.generate("x", out, references=None)
        self.assertTrue(out.exists())


class TheSanityFloor(unittest.TestCase):
    """"Download them if they look okay" — the mechanical half.

    Two questions, deliberately kept apart. Whether this is the RIGHT picture is
    `vision_verdict`'s job, with the reference art in front of it. Whether it is a
    picture AT ALL is this, and it is new: an API returned image bytes or an error,
    but a web page can hand you a spinner, a placeholder, or a 404 body, and all three
    are <img>-shaped. Cheap to check here; a Claude call is not."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fanfic-floor-"))
        self._profile = config.GEMINI_PROFILE_DIR
        config.GEMINI_PROFILE_DIR = self.tmp / "profile"
        config.GEMINI_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._chrome = config.CHROME_BIN
        config.CHROME_BIN = str(self.tmp)
        self._which = image_browser._which
        image_browser._which = lambda _binary: True

    def tearDown(self):
        config.GEMINI_PROFILE_DIR = self._profile
        config.CHROME_BIN = self._chrome
        image_browser._which = self._which

    def test_dimensions_are_read_from_the_file_itself(self):
        path = self.tmp / "a.png"
        path.write_bytes(_png(1024, 1536, padding=30000))
        self.assertEqual(image_browser.dimensions(path.read_bytes()), (1024, 1536))

    def test_a_real_render_passes(self):
        path = self.tmp / "good.png"
        path.write_bytes(_png(1024, 1536, padding=30000))
        self.assertIsNone(image_browser.looks_like_art(path))

    def test_a_thumbnail_is_rejected_by_its_dimensions(self):
        path = self.tmp / "thumb.png"
        path.write_bytes(_png(64, 64, padding=30000))
        problem = image_browser.looks_like_art(path)
        self.assertIn("64x64", problem)

    def test_a_tiny_file_is_rejected_before_anything_else(self):
        path = self.tmp / "spinner.png"
        path.write_bytes(_png(1024, 1536, padding=0))   # correct header, no pixels
        self.assertIn("too small", image_browser.looks_like_art(path))

    def test_a_404_body_is_not_an_image_however_it_arrived(self):
        path = self.tmp / "oops.png"
        path.write_bytes(b"<html><body>Not found</body></html>" + b" " * 30000)
        self.assertIn("not a PNG", image_browser.looks_like_art(path))

    def test_a_render_that_fails_the_floor_is_deleted_not_shipped(self):
        """A file left on disk is a picture as far as every later stage is concerned:
        `render_scene` checks `staged.exists()` and would place a spinner in the book."""
        bad = _png(64, 64, padding=30000)

        def fake_run(cmd, **kwargs):
            out = Path(cmd[cmd.index("--out") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(bad)
            return _FakeProc({"ok": True, "bytes": len(bad), "width": 64,
                              "height": 64})
        original = image_browser.subprocess.run
        image_browser.subprocess.run = fake_run
        self.addCleanup(lambda: setattr(image_browser.subprocess, "run", original))

        out = self.tmp / "reject.png"
        with self.assertRaises(RuntimeError) as ctx:
            images.generate("x", out, references=None)
        self.assertIn("not usable art", str(ctx.exception))
        self.assertFalse(out.exists(), "a rejected render must not be left on disk")


class BestEffortTests(unittest.TestCase):
    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self._images = config.IMAGES_ENABLED
        config.IMAGES_ENABLED = True

    def tearDown(self):
        config.IMAGES_ENABLED = self._images

    def test_a_quota_hit_defers_and_the_book_completes_once_it_clears(self):
        calls = {"n": 0}

        def flaky(prompt, out_path, references=None, log_fn=None, aspect=None):
            calls["n"] += 1
            if calls["n"] <= 2:                       # the first two are rate-limited
                raise QuotaExceeded("rate limit", retry_after=1)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(support.PNG)
        illustration.render = flaky

        sid = "quota-defer"
        support.drop(sid)
        self.assertEqual(support.run_engine(sid), states.SERIES_COMPLETE)
        book = journal.load_records()[journal.book_key(sid, 1)]
        self.assertEqual(book["status"], states.COMPLETED)
        self.assertGreater(calls["n"], 2, "the quota was hit and retried later")
        self.assertTrue(Path(book["delivered_path"]).exists())

    def test_a_failing_image_parks_the_book_rather_than_shipping_a_hole(self):
        """The rule the whole image half now runs on: a picture is never given up on.

        A book that cannot draw waits in ILLUSTRATING with its slots still queued. It
        does not bind around the gap, because a delivered book with holes in it is the
        one outcome nobody can undo — where waiting costs only time, and resolves
        itself the moment the vendor, the quota or the prompt stops being the problem.
        """
        def safety_blocked(prompt, out_path, references=None, log_fn=None,
                           aspect=None):
            raise RuntimeError("gemini produced no image (finishReason=SAFETY)")
        illustration.render = safety_blocked

        sid = "skip-imgs"
        support.drop(sid)
        support.run_engine(sid)
        book = journal.load_records()[journal.book_key(sid, 1)]
        self.assertEqual(book["status"], states.ILLUSTRATING,
                         "an undrawable picture holds the book, it does not skip")
        self.assertIsNone(book.get("delivered_path"),
                          "nothing ships while a slot is empty")
        self.assertTrue(illustration.pending_scene_entries(),
                        "the slot keeps its place in the queue")

    def test_the_parked_book_finishes_itself_once_the_render_works(self):
        """And the other half of it: waiting has to be a wait, not a wedge."""
        state = {"broken": True}

        def sometimes(prompt, out_path, references=None, log_fn=None, aspect=None):
            if state["broken"]:
                raise RuntimeError("gemini produced no image (finishReason=SAFETY)")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(support.PNG)
        illustration.render = sometimes

        sid = "heals-imgs"
        support.drop(sid)
        support.run_engine(sid)
        self.assertEqual(journal.load_records()[journal.book_key(sid, 1)]["status"],
                         states.ILLUSTRATING)

        # Whatever was wrong stops being wrong, and nobody has to re-drop anything.
        state["broken"] = False
        for dest in paths.series_root(sid).rglob("*.retry"):
            dest.unlink()                     # the backoff elapses
        self.assertEqual(support.run_engine(sid), states.SERIES_COMPLETE)
        book = journal.load_records()[journal.book_key(sid, 1)]
        self.assertEqual(book["status"], states.COMPLETED)
        with zipfile.ZipFile(Path(book["delivered_path"])) as zf:
            names = zf.namelist()
        self.assertTrue([n for n in names if n.startswith("OEBPS/images/")],
                        "the pictures the book waited for are in it")


class PictureRenderCeiling(unittest.TestCase):
    """The runaway stop, counted in RENDERS rather than dollars.

    It used to be a dollar figure, because pictures were the one thing this fleet
    genuinely paid for. They are drawn through a signed-in browser session now and
    cost nothing but wall-clock, so the ceiling counts the thing that is still
    finite. What it protects against is unchanged: a slot that keeps failing burns
    renders, a book has hundreds of slots, and an unbounded fleet on a bad night
    spends a day producing nothing.

    What the ceiling costs when it bites also stayed the same. It used to spend a
    picture to save the book; a missing picture is not an outcome any more, so it
    spends TIME — the book holds until somebody raises it, and then finishes by
    itself."""

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self._cap = config.IMAGE_RENDER_BUDGET

    def tearDown(self):
        config.IMAGE_RENDER_BUDGET = self._cap

    def test_an_exhausted_ceiling_waits_instead_of_buying_a_hole(self):
        config.IMAGE_RENDER_BUDGET = 1        # not enough for a book's worth

        sid = "broke-imgs"
        support.drop(sid)
        support.run_engine(sid)
        book = journal.load_records()[journal.book_key(sid, 1)]
        self.assertEqual(book["status"], states.ILLUSTRATING,
                         "a spent ceiling holds the book; it does not skip a picture")
        self.assertIsNone(book.get("delivered_path"))

    def test_raising_the_ceiling_resumes_the_run_by_itself(self):
        """No re-drop, no manual repair: the slots were never given up on, so lifting
        the thing that stopped them is the whole of the fix."""
        config.IMAGE_RENDER_BUDGET = 1

        sid = "raised-ceiling"
        support.drop(sid)
        support.run_engine(sid)
        self.assertEqual(journal.load_records()[journal.book_key(sid, 1)]["status"],
                         states.ILLUSTRATING)

        config.IMAGE_RENDER_BUDGET = 500
        self.assertEqual(support.run_engine(sid), states.SERIES_COMPLETE)
        book = journal.load_records()[journal.book_key(sid, 1)]
        with zipfile.ZipFile(Path(book["delivered_path"])) as zf:
            names = zf.namelist()
        self.assertTrue([n for n in names if n.startswith("OEBPS/images/")])

    def test_a_generous_ceiling_draws_the_pictures(self):
        config.IMAGE_RENDER_BUDGET = 500

        sid = "rich-imgs"
        support.drop(sid)
        self.assertEqual(support.run_engine(sid), states.SERIES_COMPLETE)
        book = journal.load_records()[journal.book_key(sid, 1)]
        with zipfile.ZipFile(Path(book["delivered_path"])) as zf:
            names = zf.namelist()
        self.assertTrue([n for n in names if n.startswith("OEBPS/images/")],
                        "with headroom, the pictures are drawn")

    def test_no_cap_configured_means_uncapped(self):
        config.IMAGE_RENDER_BUDGET = None
        self.assertEqual(budget.image_budget_remaining("anything"), float("inf"))

    def test_regenerations_are_counted_not_just_keepers(self):
        """A render the vision critic rejects still spent a render. A ceiling that
        counts only the accepted images overruns by exactly the reject rate — and it
        did, silently, while the counter was incremented once per SLOT after up to
        three renders had already happened inside it."""
        config.IMAGE_RENDER_BUDGET = 10
        self.assertEqual(budget.image_budget_remaining("s"), 10)
        for _ in range(4):
            budget.record_image("s", "rejected render")
        self.assertEqual(budget.image_budget_remaining("s"), 6)
        self.assertEqual(budget.images_generated("s"), 4)

    def test_the_ledger_is_per_series(self):
        """A second novel gets its own ceiling, not the first one's leftovers."""
        config.IMAGE_RENDER_BUDGET = 10
        for _ in range(10):
            budget.record_image("first-book", "x")
        self.assertEqual(budget.image_budget_remaining("first-book"), 0)
        self.assertEqual(budget.image_budget_remaining("second-book"), 10)


class EveryoneInFrameGetsADesign(unittest.TestCase):
    """A character described in the scene but absent from the `characters` list
    reaches the image model with no design at all, and the model fills the gap from
    whatever description is nearest — which is how "Luz and her mother in a diner"
    became two identical teenagers in matching hoodies."""

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()

    def test_a_name_in_the_description_is_attached_even_if_unlisted(self):
        from fanfic.infra import storage
        from fanfic.memory.bible import new_series_bible, new_character
        sid = "unlisted"
        bible = new_series_bible(sid)
        for who in ("Luz Noceda", "Camila Noceda"):
            bible["characters"][who] = new_character(who, appearance="a")
        storage.save_json(bible, paths.series_bible_path(sid))

        illustration.propose_scenes = lambda *a, **k: [{
            "description": "Luz Noceda and Camila Noceda sit across a diner booth",
            "characters": ["Luz Noceda"], "orientation": "landscape"}]
        scenes = illustration.scenes_for_chapter(
            {"series_id": sid}, 1, 1, "prose", 1, log_fn=lambda _m: None)
        self.assertIn("Camila Noceda", scenes[0]["characters"])


class ARefusalDoesNotCostARung(unittest.TestCase):
    """The ladder asks for LESS after each failure, and that is right for a rejection
    and wrong for a refusal.

    A rejection means the picture came out and the critic judged it wrong, so the
    composition is the thing to give ground on. A refusal means no picture came out at
    all — a classifier fired — and it is not even stable: Lord Praven's sheet was
    refused twice and then drawn from the identical prompt on the third try.

    Conflating them cost real pictures on the first live book. Two scene slots burned
    all three rungs on refusals alone and landed on the empty-room rung, so chapters
    with fights got pictures of empty yards, and nothing about those compositions was
    ever wrong."""

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self.rungs = []

    def _watch_rungs(self, fail_with):
        """Record the simplify level each render is asked at."""
        def render(prompt, out_path, references=None, log_fn=None, aspect=None):
            # The empty-room rungs are recognisable from the prompt itself.
            if "EMPTY room" in prompt or "nobody in it" in prompt:
                self.rungs.append(3)
            elif "a single clear portrait" in prompt:
                self.rungs.append(2)
            else:
                self.rungs.append(0 if "The setting:" in prompt or True else 1)
            raise fail_with
        illustration.render = render

    def test_a_refusal_keeps_asking_for_the_same_composition(self):
        self._watch_rungs(images.Refused("Gemini declined to draw this prompt: nope"))
        entry = {"series_id": "s", "book_num": 1, "chapter_num": 1, "k": 1,
                 "scene": "Ruby stands on a cliff at dusk", "characters": [],
                 "orientation": "portrait"}
        illustration.render_scene(entry, log_fn=lambda _m: None)
        self.assertEqual(self.rungs, [0, 0, 0],
                         f"a refusal must not advance the ladder; got {self.rungs}")

    def test_a_render_failure_still_advances_the_ladder(self):
        """The original behaviour, unchanged, for the failure it was designed for."""
        self._watch_rungs(RuntimeError("the browser did not return within 400s"))
        entry = {"series_id": "s", "book_num": 1, "chapter_num": 1, "k": 2,
                 "scene": "Ruby stands on a cliff at dusk", "characters": [],
                 "orientation": "portrait"}
        illustration.render_scene(entry, log_fn=lambda _m: None)
        self.assertNotEqual(self.rungs, [0, 0, 0],
                            "a genuine render failure should still simplify")

    def test_refused_is_a_runtime_error_so_nothing_downstream_leaks_it(self):
        self.assertTrue(issubclass(images.Refused, RuntimeError))


class SheetsCarryNoText(unittest.TestCase):
    """A sheet is a reference IMAGE on every scene the character appears in, so
    anything drawn on it conditions ~74 renders. The first pass produced sheets with
    the name across the top, section labels and a speech bubble — and a scene had
    already been rejected once for "stray garbled text in the image"."""

    def test_the_sheet_prompt_forbids_lettering_and_hex(self):
        spec = {"name": "Camila", "appearance": "adult woman, scrubs",
                "costumes": ["Clinic: teal scrubs and a lab coat"],
                "palette": ["#2aa198", "#111111"]}
        prompt = illustration._sheet_prompt(spec, style="painterly")
        self.assertIn("no text", prompt.lower())
        self.assertIn("no speech bubbles", prompt.lower())
        self.assertNotIn("#2aa198", prompt)
        self.assertIn("adult woman, scrubs", prompt)


class ADeferredSceneDoesNotStopTheQueue(unittest.TestCase):
    """One scene that can never render must not halt every scene behind it.

    An art director named "Ford Pines" where the bible says "Stanford Pines". No sheet
    for that name could ever exist, the sheets-first gate deferred it correctly, and
    the drainer — which only ever looked at `pending[0]` — sat on that one entry every
    five seconds while twenty-four later scenes waited."""

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()

    def test_a_name_the_bible_does_not_know_is_resolved(self):
        known = ["Stanford Pines", "Stanley Pines", "Eda Clawthorne", "King"]
        for raw, expected in (("Ford Pines", "Stanford Pines"),
                              ("Stan Pines", "Stanley Pines"),
                              ("Ford", "Stanford Pines"),
                              ("Stan", "Stanley Pines"),
                              ("Eda", "Eda Clawthorne"),
                              ("king", "King")):
            self.assertEqual(illustration.resolve_cast_name(known, raw), expected,
                             f"{raw!r} should resolve to {expected!r}")

    def test_an_unresolvable_name_is_dropped_rather_than_waited_on(self):
        """Dropping loses one character's anchor. Waiting loses the whole queue."""
        self.assertIsNone(illustration.resolve_cast_name(
            ["Luz Noceda"], "Somebody Entirely Else"))

        from fanfic.infra import storage
        from fanfic.memory.bible import new_series_bible, new_character
        sid = "unknown-name"
        bible = new_series_bible(sid)
        bible["characters"]["Stanford Pines"] = new_character("Stanford Pines",
                                                              appearance="a")
        storage.save_json(bible, paths.series_bible_path(sid))
        scenes = illustration.vet_scenes(
            {"series_id": sid}, 1,
            [{"description": "a room", "characters": ["Ford Pines", "Nobody Real"]}],
            log_fn=lambda _m: None)
        self.assertEqual(scenes[0]["characters"], ["Stanford Pines"])

    def test_the_worker_renders_past_an_entry_it_cannot_draw(self):
        from fanfic.daemons import illustrator
        drawn = []

        def render_scene(entry, log_fn=None):
            if entry["chapter_num"] == 1:
                return None                       # deferred forever
            drawn.append(entry["chapter_num"])
            return paths.scene_image_path(entry["series_id"], 1,
                                          entry["chapter_num"], 1)
        original = illustration.render_scene
        pending = illustration.pending_scene_entries
        illustration.render_scene = render_scene
        illustration.pending_scene_entries = lambda: [
            {"series_id": "q", "book_num": 1, "chapter_num": n, "k": 1,
             "characters": [], "scene": "s"} for n in (1, 2, 3)]
        try:
            illustrator.cycle(lambda _m: None)
        finally:
            illustration.render_scene = original
            illustration.pending_scene_entries = pending
        self.assertEqual(drawn, [2], "it must step over the stuck entry and draw")


class SheetsComeFirst(unittest.TestCase):
    """A scene rendered before its cast has reference sheets has nothing anchoring
    anyone, and the image model invents a face from whatever description is nearest.

    The live book has the receipt: chapter 1's diner scene was Luz and her mother,
    rendered with zero sheets on disk, and Camila came out as a second identical Luz
    in a matching hoodie. The hole was structural — sheets are the scribe's job and
    the illustrator daemon drains scenes independently, so two processes shared an
    ordering assumption that nothing enforced."""

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self._images = config.IMAGES_ENABLED
        config.IMAGES_ENABLED = True

    def tearDown(self):
        config.IMAGES_ENABLED = self._images

    def _entry(self):
        return {"series_id": "sheetless", "book_num": 1, "chapter_num": 1, "k": 1,
                "scene": "two people at a table", "characters": ["Ruby"],
                "orientation": "portrait", "prompt": "p", "identity": "Ruby: red"}

    def test_a_scene_defers_while_its_cast_has_no_sheet(self):
        calls = {"n": 0}

        def counted(*a, **k):
            calls["n"] += 1
        illustration.render = counted

        self.assertIsNone(illustration.render_scene(self._entry(),
                                                    log_fn=lambda _m: None))
        self.assertEqual(calls["n"], 0, "nothing may be drawn without an anchor")
        dest = paths.scene_image_path("sheetless", 1, 1, 1)
        self.assertTrue(illustration.due(dest),
                        "a missing sheet is 'not yet', and must not even cost the "
                        "slot a backoff — it is ready the instant the sheet lands")

    def test_it_renders_once_the_sheet_lands(self):
        sheet = paths.sheet_path("sheetless", 1, "Ruby")
        sheet.parent.mkdir(parents=True, exist_ok=True)
        sheet.write_bytes(support.PNG)
        seen = {}

        def capture(prompt, out_path, references=None, log_fn=None, aspect=None):
            seen["refs"] = list(references or [])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(support.PNG)
        illustration.render = capture
        illustration.vision_verdict = lambda *a, **k: {"passed": True, "issues": []}

        self.assertIsNotNone(illustration.render_scene(self._entry(),
                                                       log_fn=lambda _m: None))
        self.assertEqual(seen["refs"], [sheet],
                         "the locked sheet must reach the render as a reference")

    def test_a_scene_waits_for_a_parked_sheet_rather_than_drawing_without_one(self):
        """The sheet is the anchor. A parked one is a "not yet" like any other, and
        drawing the scene anyway is precisely the condition that put two identical
        Luzes in a diner — so the scene waits, and the sheet's own ladder is what
        guarantees the wait ends."""
        sheet = paths.sheet_path("sheetless", 1, "Ruby")
        illustration.defer(sheet, "safety blocked", 3)
        drawn = []
        illustration.render = lambda p, o, references=None, log_fn=None, aspect=None: \
            drawn.append(p)
        self.assertIsNone(illustration.render_scene(self._entry(),
                                                    log_fn=lambda _m: None))
        self.assertEqual(drawn, [], "nothing may be drawn without an anchor")


class TheWrongPersonIsWorseThanNobody(unittest.TestCase):
    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self._images = config.IMAGES_ENABLED
        config.IMAGES_ENABLED = True

    def tearDown(self):
        config.IMAGES_ENABLED = self._images

    def test_an_image_showing_the_wrong_character_is_not_kept(self):
        """"A slightly-off illustration beats a hole" holds for a hair shade. It does
        not hold for a picture of somebody else, which misinforms the reader about a
        face in a book whose whole visual promise is that faces stay put.

        Not kept and not abandoned either: the slot parks, and comes back a rung
        plainer until it is asking for something with no face to get wrong."""
        illustration.vision_verdict = lambda *a, **k: {
            "passed": False, "wrong_character": True,
            "issues": ["Camila is drawn as a second, identical Luz"]}
        sid = "wrong-person"
        support.drop(sid)
        support.run_engine(sid)
        img = paths.scene_image_path(sid, 1, 1, 1)
        self.assertFalse(img.exists(), "a picture of the wrong person must not ship")
        self.assertTrue(illustration.retry_marker(img).exists(),
                        "and the slot is owed, not written off")
        self.assertGreaterEqual(illustration.attempts_so_far(img), 3)

    def test_a_merely_disappointing_image_is_still_kept(self):
        illustration.vision_verdict = lambda *a, **k: {
            "passed": False, "wrong_character": False,
            "issues": ["the hoodie is a slightly different purple"]}
        sid = "good-enough"
        support.drop(sid)
        self.assertEqual(support.run_engine(sid), states.SERIES_COMPLETE)
        img = paths.scene_image_path(sid, 1, 1, 1)
        self.assertTrue(img.exists())
        self.assertTrue(img.with_name(img.name + ".note").exists())


class AnImperfectPictureBeatsNoPicture(unittest.TestCase):
    """The old loop threw away every image the critic would not pass. Thirteen slots
    in the live book ended empty over complaints about a mug, a fez and a tail."""

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self._images = config.IMAGES_ENABLED
        config.IMAGES_ENABLED = True

    def tearDown(self):
        config.IMAGES_ENABLED = self._images

    def test_a_render_the_critic_never_passes_is_kept_with_a_note(self):
        illustration.vision_verdict = lambda *a, **k: {
            "passed": False, "issues": ["the mug is not empty"]}
        sid = "kept-anyway"
        support.drop(sid)
        self.assertEqual(support.run_engine(sid), states.SERIES_COMPLETE)

        img = paths.scene_image_path(sid, 1, 1, 1)
        self.assertTrue(img.exists(), "an image that rendered must reach the book")
        note = img.with_name(img.name + ".note")
        self.assertTrue(note.exists(), "and the critic's complaint must be on record")
        self.assertIn("mug", note.read_text())

    def test_a_render_that_never_produced_bytes_is_parked_and_retried(self):
        """Keeping is only ever "keep what rendered". With nothing to keep, the slot
        waits — and the attempt count on it is what makes the next visit ask for
        something plainer instead of repeating the request that just failed."""
        def never_a_scene(prompt, out_path, references=None, log_fn=None, aspect=None):
            # Sheets land, so the scene gets past the sheets-first gate and it is the
            # scene's own loop being tested rather than its anchor's.
            if re.match(r"ch\d+_", out_path.name):
                raise RuntimeError("gemini produced no image (finishReason=SAFETY)")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(support.PNG)
        illustration.render = never_a_scene
        sid = "nothing-rendered"
        support.drop(sid)
        support.run_engine(sid)
        img = paths.scene_image_path(sid, 1, 1, 1)
        self.assertFalse(img.exists())
        self.assertTrue(illustration.retry_marker(img).exists())
        self.assertFalse(illustration.due(img), "and it is waiting, not spinning")

    def test_a_gap_in_the_slots_does_not_drop_the_images_after_it(self):
        """The binder used to stop at the first missing image, so a chapter whose
        slot 1 was skipped also lost slot 3 — which had rendered fine."""
        from fanfic.stages import binding
        sid = "gap-book"
        support.drop(sid)
        self.assertEqual(support.run_engine(sid), states.SERIES_COMPLETE)
        first = paths.scene_image_path(sid, 1, 1, 1)
        later = paths.scene_image_path(sid, 1, 1, 3)
        self.assertTrue(later.exists(), "fixture should render a later slot")
        first.unlink()

        files, manifest = {}, []
        body = binding._chapter_body(sid, 1, 1, support.PROSE, files, manifest)
        self.assertIn("ch01_3.png", body)
        self.assertNotIn("ch01_1.png", body)


class EnqueueingIsIdempotent(unittest.TestCase):
    """A book in ILLUSTRATING with an empty queue used to ship with no pictures.

    Seeding the queue happened once, on the transition into ILLUSTRATING. A crash
    between that status write and the seed left the drain nothing pending, so it
    concluded the images were complete and the `.epub` went out with a cover and no
    illustrations — silently, with every gate green."""

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self._images = config.IMAGES_ENABLED
        config.IMAGES_ENABLED = True

    def tearDown(self):
        config.IMAGES_ENABLED = self._images

    def test_a_second_pass_queues_nothing_extra(self):
        sid = "requeue"
        support.drop(sid)
        support.run_engine(sid)
        first = len(illustration.pending_scene_entries()), _queue_lines()

        records = journal.load_records()
        illustrating.enqueue_book(records, {"series_id": sid, "universes": ["RWBY"]},
                                  1, log_fn=lambda _m: None)
        self.assertEqual(_queue_lines(), first[1],
                         "re-running the seed must not pay for art direction twice")

    def test_an_empty_queue_is_seeded_by_the_drain_itself(self):
        sid = "lost-queue"
        support.drop(sid)
        support.run_engine(sid)
        self.assertTrue(_queue_lines(), "the run should have queued scenes")

        paths.img_queue().unlink()          # the crash: status written, queue lost
        records = journal.load_records()
        book_rec = dict(records[journal.book_key(sid, 1)],
                        status=states.ILLUSTRATING)
        illustrating.advance(records, {"series_id": sid, "universes": ["RWBY"]},
                             book_rec, log_fn=lambda _m: None)
        self.assertTrue(_queue_lines(),
                        "the drain has to re-seed rather than call the book done")


class ARaisedCeilingReachesChaptersAlreadyWritten(unittest.TestCase):
    """The defect this class exists for cost the live book eight chapters of pictures.

    Chapters 1-8 were directed while `IMAGES_PER_CHAPTER` was 2. The ceiling went to
    6. Every one of them stayed on two pictures against five and six settings, because
    the only question the enqueue path asked was "is this chapter in the queue at all",
    and the answer had been yes since the day it was written. Art direction is
    idempotent per SEGMENT now, so a raised ceiling reaches prose that already exists.
    """

    PROSE = "\n\n* * *\n\n".join(f"Scene {i} happened." for i in range(1, 7))

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self.directed = []
        illustration.propose_scenes = self._propose

    def _propose(self, series_rec, book_num, chapter_num, prose_text, n,
                 log_fn=None, scope="", must_show="", slot=0):
        self.directed.append(slot)
        return [{"description": f"segment {slot}", "characters": [],
                 "orientation": "portrait"}]

    def _scenes(self, cap, already=()):
        self.directed = []
        return illustration.scenes_for_chapter(
            {"series_id": "topup"}, 1, 1, self.PROSE, cap,
            log_fn=lambda _m: None, already=already)

    def test_the_shortfall_is_filled_and_nothing_else_is_re_directed(self):
        under_the_old_ceiling = self._scenes(2)
        chosen = {s["segment"] for s in under_the_old_ceiling}
        self.assertEqual(len(chosen), 2, "the old ceiling really did bite")

        topped_up = self._scenes(6, already=chosen)
        self.assertEqual({s["segment"] for s in topped_up} | chosen, {1, 2, 3, 4, 5, 6},
                         "every scene segment ends up with a picture")
        self.assertFalse({s["segment"] for s in topped_up} & chosen,
                         "and no segment is directed — or paid for — twice")

    def test_a_chapter_already_at_its_scene_count_asks_for_nothing(self):
        self.assertEqual(self._scenes(6, already={1, 2, 3, 4, 5, 6}), [])
        self.assertEqual(self.directed, [], "no model call for a finished chapter")

    def test_the_engine_finds_the_short_chapters_by_their_own_scene_count(self):
        from fanfic.infra import storage
        sid = "short-book"
        storage.save_json({"chapters": [{"number": 1, "characters": []},
                                        {"number": 2, "characters": []}]},
                          paths.outline_path(sid, 1))
        for n in (1, 2):
            path = paths.chapter_path(sid, 1, n)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.PROSE, encoding="utf-8")
        illustration.enqueue_chapter(
            {"series_id": sid}, 1, 1,
            [{"description": "d", "characters": [], "segment": k} for k in (1, 5)])
        illustration.enqueue_chapter(
            {"series_id": sid}, 1, 2,
            [{"description": "d", "characters": [], "segment": k}
             for k in range(1, 7)])

        short = illustrating.chapters_short_of_cap({"series_id": sid}, 1)
        self.assertEqual(short, [1],
                         "chapter 1 is two pictures short of its six scenes; "
                         "chapter 2 is complete and must not be re-directed")


class TheLadderCarriesOnAcrossVisits(unittest.TestCase):
    """Why "never give up" terminates instead of spinning.

    A retry loop that restarts at rung zero every visit re-asks forever for the
    composition it has already been refused. The rung is persisted with the slot, so
    each visit asks for something plainer than the last, and the bottom of the ladder
    is a picture of the room with nobody in it — which has no identity to get wrong."""

    def setUp(self):
        support.wipe_state()

    def test_a_parked_slot_resumes_at_the_rung_it_reached(self):
        dest = paths.scene_image_path("ladder", 1, 1, 1)
        self.assertEqual(illustration.attempts_so_far(dest), 0)
        illustration.defer(dest, "no", 3)
        self.assertEqual(illustration.attempts_so_far(dest), 3)
        self.assertFalse(illustration.due(dest))

    def test_the_wait_doubles_and_is_capped(self):
        dest = paths.scene_image_path("ladder", 1, 1, 2)
        waits = [illustration.defer(dest, "no", n) for n in (3, 4, 5, 40)]
        self.assertEqual(waits[0], config.IMAGE_RETRY_BACKOFF_BASE_SEC)
        self.assertEqual(waits[1], config.IMAGE_RETRY_BACKOFF_BASE_SEC * 2)
        self.assertEqual(waits[2], config.IMAGE_RETRY_BACKOFF_BASE_SEC * 4)
        self.assertEqual(waits[3], config.IMAGE_RETRY_BACKOFF_MAX_SEC)

    def test_a_reference_backed_prompt_drops_the_appearance_and_keeps_the_costume(self):
        """Prose and pictures always disagree, and a model handed both averages them.

        The founding argument for fetching real art is that there is no wording for a
        particular jaw; a paragraph sitting on top of a photograph therefore erodes the
        face rather than reinforcing it. Age survives because it is the one identity
        fact a reference can be actively wrong about — source art is drawn from a whole
        series, and a book starts after its epilogue."""
        cast = [("Luz Noceda", {"name": "Luz Noceda", "age": 18,
                                "appearance": "brown hair, broad shoulders",
                                "costumes": ["a battered field jacket"]})]
        anchored = illustration.build_scene_prompt(
            "Luz argues with her mother", cast, anchored=True)
        self.assertNotIn("brown hair", anchored)
        self.assertIn("Luz Noceda (18)", anchored)
        self.assertIn("battered field jacket", anchored)
        self.assertIn("attached reference pictures", anchored)

        # With nothing attached, the words are all there is and they all stay.
        unanchored = illustration.build_scene_prompt(
            "Luz argues with her mother", cast, anchored=False)
        self.assertIn("brown hair", unanchored)
        self.assertIn("18 years old", unanchored)

    def test_only_the_foreground_carries_source_art(self):
        """Fidelity per face falls as the reference count rises, so a crowded frame
        that attaches everything makes every face in it worse."""
        self.assertLessEqual(config.IMAGE_REFERENCE_CHARACTERS,
                             config.IMAGE_MAX_CHARACTERS)
        self.assertGreaterEqual(config.IMAGE_REFERENCE_CHARACTERS, 1)

    def test_the_bottom_rung_takes_the_people_out_entirely(self):
        cast = [("Luz Noceda", {"name": "Luz Noceda", "appearance": "brown hair"})]
        crowded = illustration.build_scene_prompt("Luz argues with her mother", cast,
                                                  simplify=0)
        self.assertIn("Luz Noceda", crowded)
        bare = illustration.build_scene_prompt("Luz argues with her mother", cast,
                                               simplify=3)
        self.assertNotIn("Luz Noceda", bare, "no locked design to draw wrong")
        self.assertIn("nobody in it", bare.lower())
        self.assertIn("any people or figures at all", bare.lower(),
                      "and the ban is repeated where the model reads exclusions")
        self.assertIn("must NOT appear", bare,
                      "the staging line still describes people, so the instruction "
                      "has to countermand it or the model draws them anyway")

    def test_a_legacy_skip_marker_is_a_slot_to_revive_not_a_verdict(self):
        """An older build wrote `.skipped` to abandon a slot. Nothing honours that any
        more — it reads as "tried, due now", so a run that gave up heals itself."""
        dest = paths.scene_image_path("legacy", 1, 1, 1)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.with_name(dest.name + ".skipped").write_text("gave up", encoding="utf-8")
        self.assertFalse(illustration.is_resolved(dest))
        self.assertTrue(illustration.due(dest), "a re-drop is not required")
        self.assertGreater(illustration.attempts_so_far(dest), 0,
                           "and it resumes down the ladder, not at the top")


class ABlindSheetIsRelockedAndItsPicturesRedrawn(unittest.TestCase):
    """A sheet drawn from prose when the show's own art existed is not merely
    lower-quality — it is the reference image on every render its character appears in,
    so one bad anchor is a whole book of pictures that look almost right. Twenty-three
    of the live cast were in that state, including a pig drawn from the words "a pink
    pig, originally billed at fifteen pounds"."""

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        from fanfic.infra import storage
        from fanfic.stages import refart
        self.sid = "blind-sheets"
        storage.save_json({"characters": {
            "Waddles": {"name": "Waddles", "origin": "Gravity Falls"},
            "Ossia Vane": {"name": "Ossia Vane", "origin": "original"}}},
            paths.series_bible_path(self.sid))

        for name in ("Waddles", "Ossia Vane"):
            sheet = paths.sheet_path(self.sid, 1, name)
            sheet.parent.mkdir(parents=True, exist_ok=True)
            sheet.write_bytes(support.PNG)          # locked, with no provenance
        illustration.enqueue_chapter(
            {"series_id": self.sid}, 1, 1,
            [{"description": "the pig", "characters": ["Waddles"], "segment": 1},
             {"description": "elsewhere", "characters": ["Luz"], "segment": 2}])
        for k in (1, 2):
            img = paths.scene_image_path(self.sid, 1, 1, k)
            img.parent.mkdir(parents=True, exist_ok=True)
            img.write_bytes(support.PNG)

        self.art = []
        def ensure(series_rec, book_num, name, origin=None, log_fn=None):
            if name in self.art:
                d = paths.refart_dir(series_rec["series_id"], book_num, name)
                d.mkdir(parents=True, exist_ok=True)
                (d / "ref1.png").write_bytes(support.PNG)
                return [d / "ref1.png"]
            return []
        refart.ensure = ensure
        refart.confirmed_missing = lambda *a, **k: True

    def _relock(self):
        return illustration.relock_blind_sheet({"series_id": self.sid,
                                                "universes": ["Gravity Falls"]}, 1,
                                               log_fn=lambda _m: None)

    def test_the_sheet_and_only_its_own_pictures_are_discarded(self):
        self.art = ["Waddles"]
        self.assertEqual(self._relock(), "Waddles")
        self.assertFalse(paths.sheet_path(self.sid, 1, "Waddles").exists(),
                         "the blind sheet is dropped so it redraws from the art")
        self.assertFalse(paths.scene_image_path(self.sid, 1, 1, 1).exists(),
                         "the picture it anchored redraws too, or the book is "
                         "unchanged where it matters")
        self.assertTrue(paths.scene_image_path(self.sid, 1, 1, 2).exists(),
                        "a picture this character is not in must survive")

    def test_a_sheet_already_drawn_from_art_is_left_alone(self):
        """The guard that keeps a repair from becoming a stampede. A sheet is only
        drawn after whatever art is present has been read, so a character who already
        has pictures has a sheet that used them — re-locking anyway would discard two
        dozen good sheets and every picture they anchor, to reproduce them."""
        from fanfic.stages import refart
        d = paths.refart_dir(self.sid, 1, "Waddles")
        d.mkdir(parents=True, exist_ok=True)
        (d / "ref1.png").write_bytes(support.PNG)
        refart.ensure = lambda *a, **k: self.fail("must not even look it up again")

        self.assertIsNone(self._relock())
        self.assertTrue(paths.sheet_path(self.sid, 1, "Waddles").exists())
        self.assertTrue(paths.scene_image_path(self.sid, 1, 1, 1).exists())
        self.assertEqual(
            illustration.sheet_source_count(paths.sheet_path(self.sid, 1, "Waddles")),
            1, "and the provenance is backfilled so it is never asked again")

    def test_a_character_with_no_source_art_keeps_the_sheet_it_has(self):
        """Prose is the best anchor available for them, and an unanchored redraw
        would be strictly worse than what is already there."""
        self.art = []
        self.assertIsNone(self._relock())
        self.assertTrue(paths.sheet_path(self.sid, 1, "Waddles").exists())
        self.assertTrue(paths.scene_image_path(self.sid, 1, 1, 1).exists())

    def test_an_original_is_settled_without_a_lookup(self):
        self.art = []
        self._relock()
        sheet = paths.sheet_path(self.sid, 1, "Ossia Vane")
        self.assertTrue(sheet.exists())
        self.assertEqual(illustration.sheet_source_count(sheet), 0,
                         "recorded as having no source, so it is never asked again")

    def test_it_settles_and_does_not_relock_the_same_sheet_twice(self):
        self.art = ["Waddles"]
        self.assertEqual(self._relock(), "Waddles")
        sheet = paths.sheet_path(self.sid, 1, "Waddles")
        sheet.write_bytes(support.PNG)                    # the redraw lands
        illustration.mark_sheet_sources(sheet, 1)
        self.assertIsNone(self._relock(), "a recorded sheet is never re-examined")

    def test_a_network_failure_does_not_settle_the_question(self):
        """One bad minute must not freeze a blind sheet for the life of the book."""
        from fanfic.stages import refart
        refart.confirmed_missing = lambda *a, **k: False
        self.art = []
        self.assertIsNone(self._relock())
        self.assertEqual(
            illustration.sheet_source_count(paths.sheet_path(self.sid, 1, "Waddles")),
            -1, "still unrecorded, so the next cycle asks again")


def _queue_lines():
    queue = paths.img_queue()
    if not queue.exists():
        return 0
    return len([l for l in queue.read_text().splitlines() if l.strip()])



class WikiLookupEarnsTheCharacter(unittest.TestCase):
    """A wiki search never returns nothing, so the danger is not a miss — it is a
    confident wrong answer that anchors a character to somebody, or something, else.

    Every case here is from the real Star Wars cast, checked against the live wiki
    during bring-up and then pinned offline."""

    def setUp(self):
        self._api = refart._api
        self.pages = {}      # exact-title lookups
        self.hits = []       # search results

        def fake_api(host, params):
            if params.get("action") == "query" and "titles" in params:
                title = params["titles"]
                if title in self.pages:
                    return {"query": {"pages": {"1": {"title": self.pages[title]}}}}
                return {"query": {"pages": {"-1": {"missing": ""}}}}
            return {"query": {"search": [{"title": t} for t in self.hits]}}
        refart._api = fake_api

    def tearDown(self):
        refart._api = self._api

    def test_a_droid_designation_resolves(self):
        """`_words` kept only alphabetic runs over two characters, so "T7-O1" reduced
        to {"T","O"}, both were dropped, and the lookup bailed on an empty set — no
        anchor for a companion in 48 scenes, and the same for every HK-51 and C2-N2 in
        the genre."""
        self.pages = {"T7-O1": "T7-O1"}
        self.assertEqual(refart.resolve_title("h", "T7-O1"), "T7-O1")

    def test_a_redirect_is_followed_to_the_real_article(self):
        """"Vitiate" is a redirect to "Tenebrae". A title lookup follows it; search
        does not, which is why search is no longer asked first."""
        self.pages = {"Vitiate": "Tenebrae"}
        self.assertEqual(refart.resolve_title("h", "Vitiate"), "Tenebrae")

    def test_a_page_about_the_character_is_not_the_character(self):
        """THE live failure. Asked for "Vitiate", search offered "Vitiate's palace" —
        which shares the word, passes the old overlap rule, and is a building. A
        character sheet anchored to architecture, with nothing anywhere saying so."""
        self.hits = ["Vitiate's palace", "Vitiate's throne room"]
        self.assertIsNone(refart.resolve_title("h", "Vitiate"))

    def test_a_disambiguation_page_is_refused(self):
        """It matches the name perfectly and carries only navigation icons. A sheet
        drawn from it is a sheet drawn from nothing, recorded as anchored."""
        self.pages = {"Tarnis": "Tarnis (disambiguation)"}
        self.hits = ["Tarnis (disambiguation)"]
        self.assertIsNone(refart.resolve_title("h", "Tarnis"))

    def test_a_qualified_article_still_wins(self):
        """"Scourge (Sith)" adds a word but is the article, not a page about him."""
        self.hits = ["Scourge (Sith)"]
        self.assertEqual(refart.resolve_title("h", "Lord Scourge"), "Scourge (Sith)")

    def test_the_least_embellished_plausible_hit_wins(self):
        self.hits = ["Scourge's lightsaber", "Scourge (Sith)"]
        self.assertEqual(refart.resolve_title("h", "Lord Scourge"), "Scourge (Sith)")

    def test_an_invented_protagonist_has_no_page_and_that_is_correct(self):
        """The player character is named by the reader, so no wiki has her. Falling
        back to the locked prose is right; guessing would anchor the book's lead to a
        stranger.

        Note what this does NOT assert. A hit sharing one word of a multi-word name is
        accepted — "Scourge (Sith)" is how "Lord Scourge" resolves, and the honorific
        never appears in the article title. So a page called "Alyn" would match, and
        deciding whether that is too loose is a separate question from this one. What
        is pinned here is the case that actually occurs: the wiki has no article and
        search offers nothing that shares a name word at all."""
        self.hits = ["Jedi Knight", "Galactic Republic"]
        self.assertIsNone(refart.resolve_title("h", "Alyn Tenar"))

    def test_an_unrelated_hit_is_refused(self):
        """The scar this module carries: asked for "Waddles" a wiki answered with the
        voice actor's page."""
        self.hits = ["Dee Bradley Baker"]
        self.assertIsNone(refart.resolve_title("h", "Waddles"))

if __name__ == "__main__":
    unittest.main(verbosity=2)
