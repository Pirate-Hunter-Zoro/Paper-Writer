"""End to end: an inbox prompt to a delivered `.epub` through the REAL state machine.

Only the model seams are stubbed. Inbox admission, the journal and every transition,
the coverage and structure gates, the readability gate, the bible merge, atomic
staging, the epub build and its validator, and delivery all run for real. This is the
proof that the harness wiring is correct independent of the models — and it is the
smoke test to run on the mini before trusting a live overnight run.
"""

import unittest
import zipfile
from pathlib import Path

import support

from fanfic import config, paths, states                          # noqa: E402
from fanfic.infra import journal                                  # noqa: E402
from fanfic.stages import binding, illustration                   # noqa: E402


class FullPipelineTests(unittest.TestCase):
    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self._images = config.IMAGES_ENABLED
        config.IMAGES_ENABLED = True

    def tearDown(self):
        config.IMAGES_ENABLED = self._images

    def test_prompt_to_delivered_epub(self):
        sid = "vacuo-war"
        support.drop(sid)
        self.assertEqual(support.run_engine(sid), states.SERIES_COMPLETE)

        records = journal.load_records()
        book = records[journal.book_key(sid, 1)]
        self.assertEqual(book["status"], states.COMPLETED)

        for n in (1, 2):
            chapter = records[journal.chapter_key(sid, 1, n)]
            self.assertEqual(chapter["status"], states.BIBLE_MERGED)
            self.assertTrue(chapter["readability"]["passed"])

        delivered = Path(book["delivered_path"])
        self.assertTrue(delivered.exists())
        self.assertTrue(delivered.name.endswith(".epub"))
        with zipfile.ZipFile(delivered) as zf:
            names = zf.namelist()
        self.assertTrue([n for n in names if n.startswith("OEBPS/text/ch")])
        self.assertTrue([n for n in names if n.startswith("OEBPS/images/")])

        # The prompt was filed out of the inbox, so it is never re-scanned.
        self.assertFalse((config.INBOX_DIR / f"{sid}.md").exists())
        self.assertTrue((config.INBOX_FINISHED_DIR / f"{sid}.md").exists())

    def test_another_cycle_after_completion_changes_nothing(self):
        sid = "idempotent-run"
        support.drop(sid)
        self.assertEqual(support.run_engine(sid), states.SERIES_COMPLETE)

        before = journal.load_records()
        support.run_engine(sid, limit=1)
        after = journal.load_records()
        self.assertEqual(len(before), len(after))
        self.assertEqual(after[journal.series_key(sid)]["status"],
                         states.SERIES_COMPLETE)


class TextOnlyBuildTests(unittest.TestCase):
    """FANFIC_IMAGES_ENABLED=0 is an explicit, logged choice — not a failure — and it
    must still deliver a real book."""

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self._images = config.IMAGES_ENABLED

    def tearDown(self):
        config.IMAGES_ENABLED = self._images

    def test_no_image_call_happens_and_the_epub_is_still_valid(self):
        config.IMAGES_ENABLED = False

        def forbidden(*args, **kwargs):
            raise AssertionError("no image call may happen when images are disabled")
        illustration.render = forbidden

        sid = "text-only"
        support.drop(sid)
        self.assertEqual(support.run_engine(sid), states.SERIES_COMPLETE)

        book = journal.load_records()[journal.book_key(sid, 1)]
        with zipfile.ZipFile(Path(book["delivered_path"])) as zf:
            names = zf.namelist()
        self.assertFalse([n for n in names if n.startswith("OEBPS/images/")],
                         "a text-only epub must embed no images")
        self.assertTrue([n for n in names if n.startswith("OEBPS/text/ch")],
                        "it is still a real book")


class PromptPackTests(unittest.TestCase):
    """The image prompts are a reviewable artifact, and each one must carry the
    character's LOCKED identity — that is the whole visual-consistency mechanism."""

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self._images = config.IMAGES_ENABLED
        config.IMAGES_ENABLED = True

    def tearDown(self):
        config.IMAGES_ENABLED = self._images

    def test_pack_bakes_in_locked_identity_and_target_filenames(self):
        sid = "prompt-demo"
        support.drop(sid)
        self.assertEqual(support.run_engine(sid), states.SERIES_COMPLETE)

        pack = paths.prompt_pack_path(sid, 1)
        self.assertTrue(pack.exists(), "the reviewable prompt pack must be written")
        text = pack.read_text(encoding="utf-8")
        # The appearance PARAGRAPH is deliberately not here. A scene render carries
        # the character's real reference pictures, and a prose description sitting on
        # top of a photograph does not reinforce the face, it averages with it. What
        # survives is what a reference cannot carry: the age, and this chapter's
        # costume.
        self.assertNotIn("silver eyes", text)               # the appearance paragraph
        self.assertIn("Ruby (17)", text)                    # age survives the trim
        self.assertIn("huntress", text)                     # so does the costume
        self.assertIn("attached reference pictures", text)  # the identity instruction
        self.assertIn("cel-shaded", text)                   # the fixed style block
        self.assertIn("Save as:", text)                     # per-image target path

    def test_the_jobs_own_art_direction_reaches_every_prompt(self):
        """A job that asks for painterly key art must not be illustrated with the
        config default, which is a cel-shaded anime block."""
        sid = "styled-job"
        support.drop(sid, support.PROMPT + (
            "\n## Illustrations\nOne per chapter. Style: painterly digital "
            "illustration in the key-art style of a space opera, cinematic "
            "lighting.\n"))
        self.assertEqual(support.run_engine(sid), states.SERIES_COMPLETE)

        text = paths.prompt_pack_path(sid, 1).read_text(encoding="utf-8")
        self.assertIn("painterly digital illustration", text)
        self.assertNotIn("cel-shaded", text)
        self.assertIn("Ruby (17)", text)                        # still anchored

    def test_a_job_with_no_art_direction_falls_back_to_config(self):
        sid = "unstyled-job"
        support.drop(sid)                                # PROMPT has no Illustrations
        self.assertEqual(support.run_engine(sid), states.SERIES_COMPLETE)
        self.assertIn("cel-shaded",
                      paths.prompt_pack_path(sid, 1).read_text(encoding="utf-8"))

    def test_scene_prompt_is_a_pure_deterministic_builder(self):
        yang = ("Yang Xiao Long",
                {"appearance": "long golden-blonde hair, lilac eyes",
                 "costumes": ["tan jacket, Ember Celica gauntlets"],
                 "palette": ["gold", "amber", "brown"]})
        scene = "she throws a fire-wreathed punch on a cracked battlefield"
        prompt = illustration.build_scene_prompt(scene, [yang],
                                                 orientation="landscape")
        self.assertTrue(prompt.startswith("she throws a fire-wreathed punch"),
                        "the subject leads; an image model reads the front hardest")
        self.assertIn("lilac eyes", prompt)                 # locked, not re-guessed
        self.assertIn("Ember Celica", prompt)
        self.assertIn("Wide horizontal composition", prompt)
        self.assertIn("Do not include:", prompt)
        self.assertEqual(prompt, illustration.build_scene_prompt(
            scene, [yang], orientation="landscape"))

    def test_hex_palettes_stay_out_of_the_prompt(self):
        """An image model handed `#b30000` does not paint with it; it reads noise in
        the middle of a description and the sentence around it gets less attention.
        The reference sheet carries the colours, which is what a reference is for."""
        spec = ("Ruby", {"appearance": "red cloak, silver eyes",
                         "costumes": ["huntress"], "palette": ["#b30000", "#2b2b2b"]})
        prompt = illustration.build_scene_prompt("she runs", [spec])
        self.assertNotIn("#b30000", prompt)
        self.assertIn("silver eyes", prompt)

    def test_each_retry_asks_for_less(self):
        """A composition the model already failed at is not improved by asking for it
        again in the same words. Thirteen slots were skipped doing exactly that."""
        cast = [("A", {"appearance": "one"}), ("B", {"appearance": "two"}),
                ("C", {"appearance": "three"})]
        scene = "A shields B from a falling beam, sparks everywhere, crowd behind"
        full = illustration.build_scene_prompt(scene, cast, simplify=0)
        less = illustration.build_scene_prompt(scene, cast, simplify=1)
        least = illustration.build_scene_prompt(scene, cast, simplify=2)
        self.assertEqual(full.count("\n- "), 3)
        self.assertEqual(less.count("\n- "), 2)
        self.assertEqual(least.count("\n- "), 1)
        self.assertNotIn("crowd behind", less)



class TheEpubDeclaresWhatThePicturesActuallyAre(unittest.TestCase):
    """Gemini returns JPEG, and every path in this project is named `.png`.

    So a `.png` on disk routinely holds JPEG bytes, and the manifest has to declare the
    content rather than the filename. An epub saying `image/png` over JPEG data is
    invalid and a strict reader may refuse it — while building, validating and opening
    fine everywhere anyone would casually check, which is what makes it worth a test."""

    def test_a_jpeg_is_declared_as_a_jpeg(self):
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
        self.assertEqual(binding._media_type(jpeg), "image/jpeg")

    def test_a_png_is_declared_as_a_png(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        self.assertEqual(binding._media_type(png), "image/png")

    def test_an_unreadable_header_falls_back_rather_than_failing_the_book(self):
        """The sanity floor should stop this reaching disk. If it ever does, a book
        that binds with one questionable declaration beats a book that does not bind."""
        self.assertEqual(binding._media_type(b"not an image at all"), "image/png")

if __name__ == "__main__":
    unittest.main(verbosity=2)


class ChapterHeadingTests(unittest.TestCase):
    """The binder must actually use the title it is given — it used to discard it.

    `_chapter_heading` was `f"<h1>Chapter {n}</h1>"` with no reference to the outline's
    `title` at all, so fixing the prompt and the gate alone would have changed nothing
    in the finished book. Both halves are pinned here: the title is used when present,
    and a titleless outline (durable state generated before the fix) still binds."""

    def test_a_title_appears_in_the_heading_and_the_toc_label(self):
        heading, nav = binding._chapter_heading({"title": "The Carved Hand"}, 7)
        self.assertIn("The Carved Hand", heading)
        self.assertIn("Chapter 7", heading)
        self.assertEqual(nav, "Chapter 7: The Carved Hand")

    def test_a_missing_title_degrades_to_a_bare_number(self):
        """An outline written before titles were gated is durable state. A plainer
        book beats a binder that refuses to build."""
        heading, nav = binding._chapter_heading({}, 7)
        self.assertEqual(nav, "Chapter 7")
        self.assertIn("Chapter 7", heading)

    def test_a_title_is_html_escaped(self):
        heading, _ = binding._chapter_heading({"title": 'Fire & <Ash>'}, 1)
        self.assertIn("&amp;", heading)
        self.assertNotIn("<Ash>", heading)

    def test_the_built_epub_carries_the_title(self):
        """End to end: the fixture outline is titled, so the real zip must contain it."""
        support.wipe_state()
        support.stub_model_seams()
        support.drop("titled-book")
        self.assertEqual(support.run_engine("titled-book"), states.SERIES_COMPLETE)
        epub = next(paths.book_root("titled-book", 1).glob("*.epub"))
        with zipfile.ZipFile(epub) as zf:
            page = zf.read("OEBPS/text/ch01.xhtml").decode("utf-8")
            nav = zf.read("OEBPS/nav.xhtml").decode("utf-8")
        self.assertIn("The Ruined City", page)
        self.assertIn("The Ruined City", nav)



class TheEpubDeclaresWhatThePicturesActuallyAre(unittest.TestCase):
    """Gemini returns JPEG, and every path in this project is named `.png`.

    So a `.png` on disk routinely holds JPEG bytes, and the manifest has to declare the
    content rather than the filename. An epub saying `image/png` over JPEG data is
    invalid and a strict reader may refuse it — while building, validating and opening
    fine everywhere anyone would casually check, which is what makes it worth a test."""

    def test_a_jpeg_is_declared_as_a_jpeg(self):
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
        self.assertEqual(binding._media_type(jpeg), "image/jpeg")

    def test_a_png_is_declared_as_a_png(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        self.assertEqual(binding._media_type(png), "image/png")

    def test_an_unreadable_header_falls_back_rather_than_failing_the_book(self):
        """The sanity floor should stop this reaching disk. If it ever does, a book
        that binds with one questionable declaration beats a book that does not bind."""
        self.assertEqual(binding._media_type(b"not an image at all"), "image/png")

if __name__ == "__main__":
    unittest.main()
