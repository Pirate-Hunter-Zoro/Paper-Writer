"""Progressions, originals, antagonists — and the costume variant keyed by chapter.

That last one is the highest-risk item in this rebuild after the repair anchors, and it
gets the most tests here. It is the first time the visual anchor is not constant across
a book: a character who gains something in chapter 28 must be drawn without it in
chapter 3 and with it in chapter 40, and the mechanism that decides which is a
comparison against a number stored in the bible. Getting it wrong is silent — the
pictures simply come out inconsistent, which is the exact failure the whole reference
sheet apparatus exists to prevent.
"""

import unittest

import support                                                   # noqa: F401
from fanfic import paths
from fanfic.gates import structure
from fanfic.memory import bible
from fanfic.infra import storage
from fanfic.stages import illustration, outlining, planning, refart


class ACostumeCanStartPartWayThroughABook(unittest.TestCase):

    SPEC = {"name": "King", "appearance": "small skull-headed titan",
            "costumes": ["nothing at all",
                         {"from_chapter": 28, "text": "a mantle of titan light"}]}

    def test_before_the_chapter_it_starts_in_the_base_costume_holds(self):
        self.assertEqual(illustration.costume_for_chapter(self.SPEC, 3),
                         "nothing at all")

    def test_from_that_chapter_onwards_the_variant_wins(self):
        self.assertEqual(illustration.costume_for_chapter(self.SPEC, 28),
                         "a mantle of titan light")
        self.assertEqual(illustration.costume_for_chapter(self.SPEC, 40),
                         "a mantle of titan light")

    def test_the_latest_started_variant_wins_not_the_last_listed(self):
        spec = {"costumes": [{"from_chapter": 30, "text": "third"},
                             "base",
                             {"from_chapter": 12, "text": "second"}]}
        self.assertEqual(illustration.costume_for_chapter(spec, 20), "second")
        self.assertEqual(illustration.costume_for_chapter(spec, 31), "third")

    def test_with_no_chapter_the_base_costume_is_used(self):
        """Which is what a reference sheet wants: it exists to settle a face, not to
        catalogue a wardrobe."""
        self.assertEqual(illustration.costume_for_chapter(self.SPEC), "nothing at all")

    def test_plain_strings_still_work(self):
        """Every bible on disk holds plain strings, and they must keep working."""
        self.assertEqual(
            illustration.costume_for_chapter({"costumes": ["huntress gear"]}, 9),
            "huntress gear")

    def test_a_wardrobe_of_plain_strings_wears_the_first_one(self):
        """A plain string is a wardrobe entry, not a timeline entry, so it can never
        displace another one.

        Letting undated entries rank against each other dressed 51 of 55 characters in
        the LAST item of their own list for every chapter before their first dated
        variant: Eda in the hook Hunter has not carved yet, Hooty in his shed-skin
        skeleton form, Luz in the field kit of an organisation that does not exist on
        page one. All of it shipped."""
        spec = {"costumes": ["headmaster's coat over the old red dress",
                             "Owl Lady field gear, hair braided back",
                             "late-book: the carved palisman-wood hook"]}
        for chapter in (1, 9, 40, None):
            self.assertEqual(illustration.costume_for_chapter(spec, chapter),
                             "headmaster's coat over the old red dress")

    def test_a_dated_variant_still_displaces_the_base(self):
        """The one thing that IS a claim about when."""
        spec = {"costumes": ["everyday", "alternate", "another alternate",
                             {"from_chapter": 31, "text": "the wooden hook"}]}
        self.assertEqual(illustration.costume_for_chapter(spec, 30), "everyday")
        self.assertEqual(illustration.costume_for_chapter(spec, 31), "the wooden hook")

    def test_no_costume_at_all_is_not_an_error(self):
        self.assertEqual(illustration.costume_for_chapter({}, 4), "")
        self.assertEqual(illustration.costume_for_chapter(None, 4), "")

    def test_the_identity_clause_a_render_receives_moves_with_the_chapter(self):
        early = illustration.identity_block([("King", self.SPEC)], 3)
        late = illustration.identity_block([("King", self.SPEC)], 33)
        self.assertIn("wearing nothing at all", early)
        self.assertIn("wearing a mantle of titan light", late)


class TheVariantIsStampedWhereTheChapterIsKnown(unittest.TestCase):
    """The plan declares the appearance change; only the outliner knows which chapter
    it lands in. So the variant is written at outline time, keyed to that chapter."""

    def setUp(self):
        support.wipe_state()
        self.sid = "variant-series"
        storage.save_json(
            {"characters": {"King": {"name": "King", "costumes": ["nothing at all"]}}},
            paths.series_bible_path(self.sid))
        self.progressions = [
            {"id": "p.king", "who": "King", "starts": "a bit", "ends": "a lot",
             "costume": "a mantle of titan light"},
            {"id": "p.hop", "who": "Hop Pop", "starts": "defers", "ends": "does not"}]
        self.outline = {"chapters": [
            {"number": 12, "delivers_progression": ["p.hop"]},
            {"number": 28, "delivers_progression": ["p.king"]}]}

    def _bible(self):
        return storage.load_json(paths.series_bible_path(self.sid), {})

    def test_the_variant_carries_the_chapter_that_delivers_it(self):
        outlining._lock_costume_variants(self.sid, self.outline, self.progressions)
        costumes = self._bible()["characters"]["King"]["costumes"]
        self.assertIn({"from_chapter": 28, "text": "a mantle of titan light",
                       "because": "p.king"}, costumes)

    def test_a_progression_with_no_costume_changes_no_appearance(self):
        """Most progressions are not powers and change nothing an artist can draw."""
        outlining._lock_costume_variants(self.sid, self.outline, self.progressions)
        self.assertEqual(len(self._bible()["characters"]["King"]["costumes"]), 2)

    def test_re_outlining_does_not_stack_duplicates(self):
        for _ in range(3):
            outlining._lock_costume_variants(self.sid, self.outline, self.progressions)
        self.assertEqual(len(self._bible()["characters"]["King"]["costumes"]), 2)

    def test_a_progression_for_someone_not_in_the_bible_is_ignored(self):
        outlining._lock_costume_variants(self.sid, self.outline, self.progressions)
        self.assertNotIn("Hop Pop", self._bible()["characters"])


class EveryProgressionLandsSomewhere(unittest.TestCase):

    def _outline(self, placements):
        return {"chapters": [
            {"number": i, "title": f"T{i}", "timeline_index": i - 1,
             "delivers_progression": placements.get(i, [])}
            for i in range(1, 4)]}

    PROGRESSIONS = [{"id": "p.1", "who": "A", "ends": "x"},
                    {"id": "p.2", "who": "B", "ends": "y"}]

    def test_all_placed_passes(self):
        report = structure.check(self._outline({1: ["p.1"], 3: ["p.2"]}),
                                 progressions=self.PROGRESSIONS)
        self.assertTrue(report.passed, report.errors)

    def test_an_unplaced_progression_fails(self):
        report = structure.check(self._outline({1: ["p.1"]}),
                                 progressions=self.PROGRESSIONS)
        self.assertFalse(report.passed)
        self.assertTrue(any("delivered by no chapter" in e for e in report.errors))

    def test_the_same_progression_twice_fails(self):
        report = structure.check(self._outline({1: ["p.1", "p.2"], 2: ["p.1"]}),
                                 progressions=self.PROGRESSIONS)
        self.assertFalse(report.passed)
        self.assertTrue(any("already delivered" in e for e in report.errors))

    def test_an_unknown_progression_fails(self):
        report = structure.check(self._outline({1: ["p.1", "p.2"], 2: ["p.99"]}),
                                 progressions=self.PROGRESSIONS)
        self.assertFalse(report.passed)
        self.assertTrue(any("unknown progression" in e for e in report.errors))


class APlanWithNoProgressionsIsNotCheckedForThem(unittest.TestCase):
    """A plan written before progressions existed has no `progressions` key. Treating
    that as "there are zero valid ids" makes every `delivers_progression` the outline
    prompt still asks for an unknown-id error, which burns all the gate attempts and
    stalls the book on an outline that is fine."""

    OUTLINE = {"chapters": [{"number": 1, "title": "A", "timeline_index": 0,
                             "delivers_progression": ["p.legacy"]}]}

    def test_none_means_unchecked(self):
        self.assertTrue(structure.check(self.OUTLINE, progressions=None).passed)

    def test_an_empty_list_also_means_unchecked(self):
        """Because `outlining.run` normalises it — the two must not disagree."""
        self.assertTrue(structure.check(self.OUTLINE, progressions=[]).passed)


class EveryRenderIsBilled(unittest.TestCase):
    """The picture budget is the only real money this fleet moves, and it was counting
    slots rather than renders: once per image slot, after up to IMAGE_MAX_REGENERATIONS
    renders inside the retry loop had already been paid for. A run with a busy vision
    critic could bill several times the ceiling with every counter reading green."""

    def setUp(self):
        support.wipe_state()
        support.stub_model_seams()
        self.sid = "billing"

    def test_a_rejected_render_is_counted_too(self):
        from fanfic.infra import budget
        rejections = {"n": 0}

        def picky(image_path, spec_text, references=(), log_fn=None):
            rejections["n"] += 1
            return {"passed": rejections["n"] > 2, "issues": ["not yet"]}
        illustration.vision_verdict = picky

        dest = paths.sheet_path(self.sid, 1, "Ruby")
        illustration.generate_reference_sheet(
            {"series_id": self.sid}, 1,
            {"name": "Ruby", "appearance": "red cloak"}, log_fn=lambda _m: None)
        self.assertTrue(dest.exists())
        self.assertEqual(budget.images_generated(self.sid), 3,
                         "two rejected renders were billed as well as the keeper")

    def test_the_keep_rate_reflects_the_rejections(self):
        from fanfic.infra import budget
        for k in range(4):
            budget.record_image(self.sid, f"r{k}")
        paths.images_dir(self.sid, 1).mkdir(parents=True, exist_ok=True)
        (paths.images_dir(self.sid, 1) / "ch01_1.png").write_bytes(support.PNG)
        self.assertEqual(illustration.keep_rate(self.sid), 0.25)

    def test_nothing_measured_yet_assumes_the_best(self):
        self.assertEqual(illustration.keep_rate(self.sid), 1.0)


class TheOutlinerInheritsTheMetaPlan(unittest.TestCase):
    """Two documents that can both assign the same fact is the failure recorded three
    times in this project's stories. The meta plan owns chapter assignment."""

    META = [{"number": 1, "cast": ["Luz", "Eda"],
             "interactions": [{"id": "x.1", "who": ["Luz", "Eda"]}]},
            {"number": 2, "cast": ["Dipper"],
             "interactions": [{"id": "x.2", "who": ["Dipper", "Luz"]}]}]

    def test_a_different_chapter_count_is_rejected(self):
        outline = {"chapters": [{"number": 1, "title": "A", "timeline_index": 0}]}
        report = structure.check(outline, meta_chapters=self.META)
        self.assertFalse(report.passed)
        self.assertTrue(any("meta plan owns the chapter breakdown" in e
                            for e in report.errors))

    def test_dropping_someone_the_meta_plan_placed_is_rejected(self):
        outline = {"chapters": [
            {"number": 1, "title": "A", "timeline_index": 0, "characters": ["Luz"]},
            {"number": 2, "title": "B", "timeline_index": 1, "characters": ["Dipper"]}]}
        report = structure.check(outline, meta_chapters=self.META)
        self.assertFalse(report.passed)
        self.assertTrue(any("omits them" in e for e in report.errors))

    def test_the_assignment_is_stamped_over_whatever_the_outliner_said(self):
        """Overwritten, not merged — so a gate attempt is never spent on an argument
        the outliner was not entitled to have."""
        outline = {"chapters": [
            {"number": 1, "delivers": ["x.2", "x.99"]},
            {"number": 2, "delivers": []}]}
        outlining._stamp_interactions(outline, self.META)
        self.assertEqual(outline["chapters"][0]["delivers"], ["x.1"])
        self.assertEqual(outline["chapters"][1]["delivers"], ["x.2"])


class OriginalsAreHeldToAHigherStandard(unittest.TestCase):

    def _plan(self, character):
        return {"book_count": 1,
                "books": [{"num": 1, "title": "T", "premise": "p", "role": "r",
                           "exit_state": "e"}],
                "arc": {"beginning": "b", "end": "e"},
                "style_guide": "past tense",
                "characters": [character],
                "antagonists": [{"name": character["name"], "primary": True,
                                 "threat": "t"}],
                "progressions": [{"id": "p.1", "who": character["name"],
                                  "starts": "s", "ends": "e"}]}

    def _original(self, **overrides):
        spec = {"name": "The Hollow Marshal", "origin": "original", "voice": "flat",
                "age": 400,
                "palette": ["#8a8a8a"],
                "distinguishing_feature": "one orange band at the collar",
                "appearance": "x" * 220}
        spec.update(overrides)
        return spec

    def test_a_complete_original_passes(self):
        self.assertEqual(planning._validate(self._plan(self._original())), [])

    def test_a_thin_description_is_rejected(self):
        errors = planning._validate(self._plan(self._original(appearance="tall guy")))
        self.assertTrue(any("ONLY anchor" in e for e in errors))

    def test_a_missing_distinguishing_feature_is_rejected(self):
        errors = planning._validate(
            self._plan(self._original(distinguishing_feature="")))
        self.assertTrue(any("distinguishing_feature" in e for e in errors))

    def test_a_canon_character_is_not_held_to_it(self):
        """They have real reference art; the prose is not their only anchor."""
        canon = {"name": "Luz Noceda", "origin": "The Owl House", "voice": "fast",
                 "age": 18,
                 "appearance": "brown hair, purple hoodie"}
        self.assertEqual(planning._validate(self._plan(canon)),
                         ["plan: no antagonist is original. At least one villain must "
                          "be invented for this book — a crossover assembled entirely "
                          "out of other people's villains has nothing at stake that "
                          "the source shows have not already settled.",
                          "plan: the primary antagonist 'Luz Noceda' comes from 'The "
                          "Owl House'. The biggest bad must be original. An existing "
                          "villain may appear and may be as dangerous as the source "
                          "material makes them — they may not be the ceiling."])


class TheBiggestBadIsOriginal(unittest.TestCase):

    def _plan(self, antagonists):
        cast = [{"name": "Bill Cipher", "origin": "Gravity Falls", "voice": "v",
                 "age": 1000,
                 "appearance": "a triangle"},
                {"name": "The Hollow Marshal", "origin": "original", "voice": "v",
                 "age": 400,
                 "palette": ["#8a8a8a"],
                 "distinguishing_feature": "one orange band",
                 "appearance": "x" * 220}]
        return {"book_count": 1,
                "books": [{"num": 1, "title": "T", "premise": "p", "role": "r",
                           "exit_state": "e"}],
                "arc": {"beginning": "b", "end": "e"}, "style_guide": "past",
                "characters": cast, "antagonists": antagonists,
                "progressions": [{"id": f"p.{i}", "who": c["name"],
                                  "starts": "s", "ends": "e"}
                                 for i, c in enumerate(cast, 1)]}

    def test_an_original_primary_with_a_canon_villain_alongside_passes(self):
        errors = planning._validate(self._plan([
            {"name": "The Hollow Marshal", "primary": True, "threat": "t"},
            {"name": "Bill Cipher", "threat": "deals"}]))
        self.assertEqual(errors, [])

    def test_a_canon_villain_may_not_be_the_ceiling(self):
        errors = planning._validate(self._plan([
            {"name": "Bill Cipher", "primary": True, "threat": "deals"},
            {"name": "The Hollow Marshal", "threat": "t"}]))
        self.assertTrue(any("may not be the ceiling" in e for e in errors))

    def test_exactly_one_primary(self):
        errors = planning._validate(self._plan([
            {"name": "The Hollow Marshal", "primary": True, "threat": "t"},
            {"name": "Bill Cipher", "primary": True, "threat": "deals"}]))
        self.assertTrue(any("marked `primary`" in e for e in errors))

    def test_no_antagonists_at_all_is_rejected(self):
        errors = planning._validate(self._plan([]))
        self.assertTrue(any("no `antagonists`" in e for e in errors))


class ReferenceArtSkipsOriginals(unittest.TestCase):
    """`resolve_title` searches the wiki and takes the best hit. Handed an invented
    name it finds *something* — some other character, from some other show — and that
    art then anchors every render of the new villain. Silently."""

    def setUp(self):
        support.wipe_state()
        self.sid = "refart-series"
        storage.save_json({"characters": {
            "Luz Noceda": {"name": "Luz Noceda", "origin": "The Owl House"},
            "The Hollow Marshal": {"name": "The Hollow Marshal",
                                   "origin": "original"}}},
            paths.series_bible_path(self.sid))
        self.looked_up = []

        def fetch(host, name, dest_dir, limit=None, log_fn=None):
            self.looked_up.append(name)
            return []
        refart.fetch_for_character = fetch
        refart.resolve_host = lambda universe, log_fn=None: "owlhouse.fandom.com"
        # Another test in this process may have stubbed the gatherer offline. This one
        # is about what the gatherer decides, so it needs the real thing — with only
        # the network underneath it replaced.
        refart.ensure = support.real_seam(refart, "ensure")
        refart.gather = support.real_seam(refart, "gather")

    def test_a_canon_character_is_looked_up(self):
        refart.gather({"series_id": self.sid, "universes": ["The Owl House"]}, 1)
        self.assertIn("Luz Noceda", self.looked_up)

    def test_an_original_is_never_looked_up(self):
        refart.gather({"series_id": self.sid, "universes": ["The Owl House"]}, 1)
        self.assertNotIn("The Hollow Marshal", self.looked_up)


class AWikiSearchAlwaysAnswers(unittest.TestCase):
    """The failure that makes search-based lookup dangerous rather than merely
    imprecise: a wiki search never returns nothing.

    Asked for "Waddles", the Owl House wiki answers "Dee Bradley Baker" — the voice
    actor. Asked for "Perfuma" it answers "Luz Noceda". Taking the top hit anchors a
    pig to a photograph of a man and a flower princess to Luz, and nothing anywhere
    records that it happened; the pictures just come out wrong in a way that reads as
    the image model being bad."""

    def setUp(self):
        self.hits = []
        refart._api = lambda host, params: {
            "query": {"search": [{"title": t} for t in self.hits]}}

    def tearDown(self):
        refart._api = support.real_seam(refart, "_api")

    def test_an_unrelated_hit_is_refused(self):
        self.hits = ["Dee Bradley Baker", "List of guest stars"]
        self.assertIsNone(refart.resolve_title("theowlhouse.fandom.com", "Waddles"),
                          "no art beats another show's art")

    def test_a_hit_sharing_the_name_is_taken(self):
        self.hits = ["Old Man McGucket"]
        self.assertEqual(
            refart.resolve_title("gravityfalls.fandom.com", "Fiddleford McGucket"),
            "Old Man McGucket")

    def test_a_gallery_subpage_resolves_to_the_article(self):
        """The infobox portrait — the best single reference any wiki has — is on the
        article, not on the gallery."""
        self.hits = ["Waddles/Gallery", "Waddles"]
        self.assertEqual(
            refart.resolve_title("gravityfalls.fandom.com", "Waddles"), "Waddles")

    def test_an_exact_title_beats_an_earlier_fuzzy_hit(self):
        self.hits = ["The Owl House in popular culture", "Bessie"]
        self.assertEqual(refart.resolve_title("amphibia.fandom.com", "Bessie"),
                         "Bessie")


class ACharacterIsLookedUpOnTheirOwnWiki(unittest.TestCase):
    """A four-way crossover walked its universes in order and kept whichever wiki
    answered first — which, since a search always answers, is the same wiki for every
    character in the book. The bible records which show each person is from."""

    def setUp(self):
        self.asked = []
        refart.resolve_host = lambda universe, log_fn=None: (
            self.asked.append(universe) or f"{universe.split()[0].lower()}.example")

    def tearDown(self):
        refart.resolve_host = support.real_seam(refart, "resolve_host")

    def test_the_origin_wiki_is_asked_first(self):
        hosts = refart.hosts_for_character(
            "Gravity Falls", ["The Owl House", "Gravity Falls", "Amphibia"])
        self.assertEqual(self.asked[0], "Gravity Falls")
        self.assertEqual(hosts[0], "gravity.example")

    def test_an_unknown_origin_still_gets_every_wiki_in_the_series(self):
        """This book's bible has a canon Amphibia character with no origin recorded.
        Stopping at the first wiki that merely resolves left him with nothing."""
        hosts = refart.hosts_for_character(None, ["The Owl House", "Amphibia"])
        self.assertEqual(hosts, ["the.example", "amphibia.example"])


if __name__ == "__main__":
    unittest.main()


class ACostumeIsOneOutfitNotAnItinerary(unittest.TestCase):
    """The protagonist of the live SWTOR run wore three outfits at once for
    thirty-four chapters, and nothing noticed.

    Her p.1 read: "From the Forge onward a blue-bladed lightsaber hangs at her left
    hip ...; from Carrick Station onward the sandcloth Padawan tunic is replaced by
    ... Guardian robes; from Orgus Din's funeral onward a band of burnt orange cloth
    ...". Three changes, landing in chapters 9, 18 and 17 — not even in that order.
    The whole paragraph was stamped at chapter 9, and `costume_for_chapter` then handed
    it verbatim to every chapter from 9 to 42, so each render was told about robes and
    a forearm wrap she does not own yet while her reference sheet was attached.

    Nothing downstream looks for this. The picture just quietly shows wrong clothes,
    which is the same silent failure the dated-costume machinery exists to prevent."""

    ITINERARY = ("From the Forge onward a blue-bladed lightsaber hangs at her left hip "
                 "and the vibrosword is gone; from Carrick Station onward the sandcloth "
                 "Padawan tunic is replaced by layered brown and bone Guardian robes; "
                 "from Orgus Din's funeral onward a band of burnt orange cloth is "
                 "wrapped around her left forearm.")
    ONE_OUTFIT = ("From his surrender onward the head-covering bodysuit and crimson "
                  "lightsaber are gone, replaced by plain undyed Jedi robes.")

    def test_the_live_failure_is_recognised(self):
        self.assertTrue(bible.describes_multiple_transitions(self.ITINERARY))

    def test_the_normal_shape_is_left_alone(self):
        """One transition marker is the CORRECT shape and by far the commonest. A rule
        that fired on it would reject thirteen of the fifteen real progressions."""
        self.assertFalse(bible.describes_multiple_transitions(self.ONE_OUTFIT))
        self.assertFalse(bible.describes_multiple_transitions(
            "After the Knighting ceremony her Padawan armour is replaced by darker "
            "crimson-and-charcoal Knight's light armour with a half-cape."))
        self.assertFalse(bible.describes_multiple_transitions(
            "From the day he joins the crew, the blue-grey field coat is worn over a "
            "Republic-issue medic's rig with a hard shoulder plate."))

    def test_an_absent_or_empty_costume_is_not_an_itinerary(self):
        for value in (None, "", "   "):
            self.assertFalse(bible.describes_multiple_transitions(value))

    def test_the_plan_gate_rejects_it_at_source(self):
        plan = {"characters": [{"name": "Alyn"}],
                "progressions": [{"id": "p.1", "who": "Alyn", "starts": "a padawan",
                                  "ends": "a knight", "costume": self.ITINERARY}]}
        errors = planning._validate_progressions(plan)
        self.assertTrue(any("more than one change of look" in e for e in errors),
                        f"no error about the itinerary in {errors}")

    def test_the_plan_gate_passes_a_single_outfit(self):
        plan = {"characters": [{"name": "Alyn"}],
                "progressions": [{"id": "p.1", "who": "Alyn", "starts": "a padawan",
                                  "ends": "a knight", "costume": self.ONE_OUTFIT}]}
        self.assertEqual(planning._validate_progressions(plan), [])


class AnItineraryIsNeverStampedAsAnAnchor(unittest.TestCase):
    """The gate above stops new plans producing one. This stops the stamper writing an
    anchor from one that already exists on disk — which is what the live run had, and
    what a re-outline would otherwise put straight back after it was repaired."""

    def setUp(self):
        support.wipe_state()
        self.sid = "itinerary-series"
        storage.save_json(
            {"characters": {"Alyn": {"name": "Alyn", "costumes": ["sandcloth tunic"]}}},
            paths.series_bible_path(self.sid))
        self.progressions = [
            {"id": "p.1", "who": "Alyn", "starts": "a", "ends": "b",
             "costume": ACostumeIsOneOutfitNotAnItinerary.ITINERARY}]
        self.outline = {"chapters": [{"number": 9, "delivers_progression": ["p.1"]}]}

    def _costumes(self):
        bible_doc = storage.load_json(paths.series_bible_path(self.sid), {})
        return bible_doc["characters"]["Alyn"]["costumes"]

    def test_no_dated_entry_is_written(self):
        outlining._lock_costume_variants(self.sid, self.outline, self.progressions)
        self.assertEqual(self._costumes(), ["sandcloth tunic"])

    def test_the_refusal_is_logged_loudly(self):
        said = []
        outlining._lock_costume_variants(self.sid, self.outline, self.progressions,
                                         log_fn=said.append)
        self.assertTrue(any("more than one change of look" in m for m in said),
                        f"the refusal was silent: {said}")

    def test_a_repaired_wardrobe_survives_a_re_outline(self):
        """The exact regression: the live bible was repaired by hand into correct dated
        entries, and a re-outline must not append the itinerary alongside them."""
        path = paths.series_bible_path(self.sid)
        doc = storage.load_json(path, {})
        doc["characters"]["Alyn"]["costumes"] = [
            "sandcloth tunic",
            {"from_chapter": 9, "text": "sandcloth tunic, blue saber at the left hip",
             "because": "p.1"}]
        storage.save_json(doc, path)
        outlining._lock_costume_variants(self.sid, self.outline, self.progressions)
        self.assertEqual(len(self._costumes()), 2)
        self.assertEqual(illustration.costume_for_chapter(
            {"costumes": self._costumes()}, 12),
            "sandcloth tunic, blue saber at the left hip")

    def test_a_single_outfit_progression_is_still_stamped(self):
        self.progressions[0]["costume"] = ACostumeIsOneOutfitNotAnItinerary.ONE_OUTFIT
        outlining._lock_costume_variants(self.sid, self.outline, self.progressions)
        self.assertEqual(len(self._costumes()), 2)


class APromptMayNotSayWhatIsAbsent(unittest.TestCase):
    """The largest single cause of identity failure on the first real book.

    An image model has no reliable negation. "no side bangs" puts *side bangs* in the
    prompt and the noun is what gets drawn: **ten of twenty-one `[WRONG CHARACTER]`
    verdicts were Satele Shan's side bangs**, forbidden in her appearance in those
    exact words. Tarnis, described as having "no lightsaber anywhere on him", was drawn
    holding one.

    It misleads the vision critic too, which is worse because it is invisible. Jaric
    Kaedan's appearance said "dark throughout this entire book, never blonde and never
    grey"; the first verdict on him reported "the design states blonde throughout this
    entire book" and rejected the render for not being blonde."""

    def test_the_satele_case(self):
        self.assertEqual(bible.forbids_a_visible_thing(
            "brown-black hair in braids and no side bangs at any point"),
            ["no side bangs"])

    def test_the_kaedan_case(self):
        self.assertTrue(bible.forbids_a_visible_thing(
            "dark throughout this entire book, never blonde and never grey"))

    def test_a_verb_negation_is_not_a_forbidden_object(self):
        """`not` is excluded deliberately, and the noun must follow closely. Both of
        these forbid nothing, and an earlier draft of the rule fired on both."""
        self.assertEqual(bible.forbids_a_visible_thing(
            "his face does not move much, so the armour reads as the expression"), [])
        self.assertEqual(bible.forbids_a_visible_thing(
            "a runner's build, not a soldier's"), [])

    def test_lighting_and_anatomy_are_left_alone(self):
        """A shadow and a sclera are properties of something already in frame, not
        props a model can add. "Casting no shadow" is the whole point of a Force
        ghost."""
        self.assertEqual(bible.forbids_a_visible_thing(
            "translucent and lit from within, casting no shadow, his belt empty"), [])
        self.assertEqual(bible.forbids_a_visible_thing(
            "bright red eyes with no visible sclera"), [])

    def test_nothing_at_all_is_fine(self):
        for value in (None, "", "plain undyed Jedi robes, blue saber at the hip"):
            self.assertEqual(bible.forbids_a_visible_thing(value), [])

    def _plan(self, appearance, costumes=("plain robes",)):
        return {"characters": [{"name": "Satele", "appearance": appearance,
                                "age": "56", "voice": "clipped", "origin": "swtor",
                                "costumes": list(costumes)}],
                "progressions": [{"id": "p.1", "who": "Satele", "starts": "a",
                                  "ends": "b"}],
                "style_guide": "past tense"}

    def _errors(self, plan):
        return [e for e in planning._validate(plan, allow_canon_primary=True)
                if "NOT be in the picture" in e]

    def test_the_plan_gate_rejects_it(self):
        self.assertTrue(self._errors(self._plan(
            "Human female, hair in braids and no side bangs at any point.")))

    def test_the_gate_also_reads_the_costumes(self):
        """The surface my hand-sweeps kept missing: the same negation is written into
        the appearance, a plain wardrobe string and a dated entry, and fixing one is
        not fixing it."""
        self.assertTrue(self._errors(self._plan(
            "Human female, hair drawn back from a fully exposed hairline.",
            costumes=["plain robes, no lightsaber anywhere on her belt"])))
        self.assertTrue(self._errors(self._plan(
            "Human female, hair drawn back from a fully exposed hairline.",
            costumes=[{"from_chapter": 4, "text": "robes, No mask, no armour"}])))

    def test_a_positive_description_passes(self):
        self.assertEqual(self._errors(self._plan(
            "Human female, hair in braids drawn back from a fully exposed hairline.")),
            [])
