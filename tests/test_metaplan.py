"""The meta plan, built in chunks.

The engine fixture is a two-chapter book, so it exercises the stage but never the thing
the stage exists for: assembling ~180 interactions across ~45 chapters, ten chapters at
a time, with each call shown what is already committed. That is the production path and
it gets tested here at production scale.
"""

import unittest
from itertools import combinations

import support                                                   # noqa: F401
from fanfic import config, paths
from fanfic.gates import interactions as ledger_gate
from fanfic.infra import journal, storage
from fanfic.stages import metaplan

CAST = ([(f"OH{i}", "The Owl House") for i in range(1, 5)]
        + [(f"GF{i}", "Gravity Falls") for i in range(1, 5)]
        + [(f"AM{i}", "Amphibia") for i in range(1, 5)]
        + [(f"SR{i}", "She-Ra") for i in range(1, 5)]
        + [("The Hollow Marshal", "original")])

PLAN = {"per_book_words": 150000,
        "books": [{"num": 1, "title": "T", "premise": "p", "exit_state": "e"}],
        "characters": [{"name": n, "origin": o} for n, o in CAST]}


def _cycling_chunks(chapter_count=45):
    """A stub that behaves like a competently steered model.

    The groups have to be genuinely varied and genuinely cross-universe, because the
    gate this test is checking rejects a monotonous ledger — which is the whole point of
    it. The first version of this stub took contiguous windows over a sorted cast and
    was correctly refused: repeated subsets, and two of the six world pairings never
    occurring at all.

    So members are picked by striding with a step coprime to the cast size, and the
    cast is laid out four-per-universe, so a stride of 3 lands in a different world each
    time. Deterministic, and no clock or RNG in a test fixture.

    Registers are assigned by position for the same reason the groups are: the gate
    rejects a ledger that talks for the first half and fights for the second, so a stub
    that assigned one register throughout would only ever prove the gate can reject.
    One interaction in four is physical in the front half and one in two in the back,
    which clears all three floors with room and stays under the per-register ceiling."""
    names = [n for n, _ in CAST]
    size_cycle = (2, 3, 2, 4, 5, 3, 2, 6, 3, 4)
    quiet = ("conflict", "investigation", "comic", "tender")
    mid = (chapter_count + 1) // 2
    # Every possible group of each size, walked with a stride coprime to the count, so
    # consecutive picks are far apart in the cast rather than adjacent. Taking them in
    # plain order would put the first four names in almost every early scene and starve
    # the rest, which the appearance floor would then correctly reject.
    pools = {size: list(combinations(names, size)) for size in set(size_cycle)}

    def propose(series_rec, book_num, meta, first, last, out_path, log_fn=None,
                feedback=""):
        # What is already committed is quoted to a real model for exactly this reason:
        # so it does not repeat a grouping the book has already had. The stub reads it
        # off `meta` the same way, which also keeps it stateless across calls.
        used = {frozenset(e["who"]) for e in metaplan.ledger(meta)}
        chapters = []
        for n in range(first, min(last, chapter_count) + 1):
            groups, cast = [], set()
            for k in range(config.META_INTERACTIONS_MIN):
                index = n * config.META_INTERACTIONS_MIN + k
                size = size_cycle[index % len(size_cycle)]
                pool = pools[size]
                for bump in range(len(pool)):
                    who = list(pool[(index * 37 + bump) % len(pool)])
                    if frozenset(who) not in used:
                        break
                used.add(frozenset(who))
                every = 4 if n <= mid else 2
                register = ("physical" if k % every == 0
                            else quiet[index % len(quiet)])
                groups.append({"who": who, "promise": f"ch{n} scene {k}",
                               "register": register})
                cast.update(who)
            chapters.append({"number": n, "premise": f"chapter {n}",
                             "cast": sorted(cast), "interactions": groups})
        storage.save_json({"chapter_count": chapter_count, "chapters": chapters},
                          out_path)
    return propose


class ItIsBuiltTenChaptersAtATime(unittest.TestCase):

    def setUp(self):
        support.wipe_state()
        self.sid = "meta-scale"
        self.rec = journal.new_series(self.sid, f"/inbox/{self.sid}.md", "p")
        self.rec["universes"] = ["The Owl House", "Gravity Falls", "Amphibia",
                                 "She-Ra"]
        storage.save_json(PLAN, paths.plan_path(self.sid))
        storage.save_json({"characters": {}}, paths.series_bible_path(self.sid))
        self.calls = []
        base = _cycling_chunks()

        def counting(series_rec, book_num, meta, first, last, out_path, log_fn=None,
                     feedback=""):
            self.calls.append((first, last, len(meta.get("chapters") or [])))
            return base(series_rec, book_num, meta, first, last, out_path,
                        log_fn=log_fn, feedback=feedback)
        metaplan.propose_chunk = counting

    def test_a_full_length_book_is_assembled_across_several_calls(self):
        meta = metaplan.run(self.rec, 1, log_fn=lambda _m: None)
        self.assertEqual(meta["chapter_count"], 45)
        self.assertEqual(len(meta["chapters"]), 45)
        self.assertEqual(len(self.calls), 5, "45 chapters at 10 a call")

    def test_each_call_sees_everything_already_committed(self):
        """Which is what lets a chunk steer toward the coverage the gate will check."""
        metaplan.run(self.rec, 1, log_fn=lambda _m: None)
        self.assertEqual([seen for _f, _l, seen in self.calls], [0, 10, 20, 30, 40])

    def test_the_ledger_comes_out_at_the_intended_scale(self):
        meta = metaplan.run(self.rec, 1, log_fn=lambda _m: None)
        self.assertEqual(len(metaplan.ledger(meta)),
                         45 * config.META_INTERACTIONS_MIN)

    def test_every_interaction_id_is_unique_across_chunks(self):
        """A chunk cannot know what the previous ones used, so two will eventually both
        say `x.7`. Colliding ids would merge two scenes into one ledger entry, and the
        outline would then deliver one twice and the other never."""
        meta = metaplan.run(self.rec, 1, log_fn=lambda _m: None)
        ids = [e["id"] for e in metaplan.ledger(meta)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_ledger_lands_in_the_series_bible_with_its_chapters(self):
        metaplan.run(self.rec, 1, log_fn=lambda _m: None)
        bible = storage.load_json(paths.series_bible_path(self.sid), {})
        entries = bible["interactions"]
        self.assertEqual(len(entries), 45 * config.META_INTERACTIONS_MIN)
        self.assertTrue(all(e["chapters"] for e in entries))
        self.assertEqual(entries[0]["status"], "owed")

    def test_it_resumes_from_disk_instead_of_rebuilding(self):
        """Each accepted chunk is persisted before the next is asked for, so an
        interrupted run picks up at the next chunk rather than paying for a 180-entry
        ledger twice."""
        metaplan.run(self.rec, 1, log_fn=lambda _m: None)
        self.calls.clear()
        metaplan.run(self.rec, 1, log_fn=lambda _m: None)
        self.assertEqual(self.calls, [], "a complete meta plan asks for nothing")

    def test_a_partial_meta_plan_continues_where_it_stopped(self):
        meta = metaplan.run(self.rec, 1, log_fn=lambda _m: None)
        meta["chapters"] = meta["chapters"][:20]
        storage.save_json(meta, paths.metaplan_path(self.sid, 1))
        self.calls.clear()
        metaplan.run(self.rec, 1, log_fn=lambda _m: None)
        self.assertEqual([first for first, _l, _s in self.calls], [21, 31, 41])


class TheFinishedLedgerIsGated(unittest.TestCase):

    def setUp(self):
        support.wipe_state()
        self.sid = "meta-gate"
        self.rec = journal.new_series(self.sid, f"/inbox/{self.sid}.md", "p")
        self.rec["universes"] = ["The Owl House", "Gravity Falls", "Amphibia",
                                 "She-Ra"]
        storage.save_json(PLAN, paths.plan_path(self.sid))
        storage.save_json({"characters": {}}, paths.series_bible_path(self.sid))

    def test_a_well_formed_ledger_clears_every_coverage_rule(self):
        metaplan.propose_chunk = _cycling_chunks()
        meta = metaplan.run(self.rec, 1, log_fn=lambda _m: None)
        report = ledger_gate.check(
            metaplan.ledger(meta), metaplan.cast_origins(PLAN),
            self.rec["universes"],
            min_appearances=config.PLAN_MIN_APPEARANCES,
            cross_share=config.META_CROSS_UNIVERSE_SHARE,
            pairing_share=config.META_MIN_PAIRING_SHARE)
        self.assertTrue(report.passed, report.errors)

    def test_a_chapter_owing_nobody_anything_is_rejected(self):
        """The defect the whole stage exists for: 23 entries across 37 chapters left
        fourteen chapters owing nothing, and chapter 1 was one of them."""
        def barren(series_rec, book_num, meta, first, last, out_path, log_fn=None,
                   feedback=""):
            storage.save_json({"chapter_count": 33, "chapters": [
                {"number": n, "premise": "p", "cast": ["OH1"], "interactions": []}
                for n in range(first, min(last, 33) + 1)]}, out_path)
        metaplan.propose_chunk = barren
        with self.assertRaises(RuntimeError) as caught:
            metaplan.run(self.rec, 1, log_fn=lambda _m: None)
        self.assertIn("interaction(s); every chapter needs", str(caught.exception))

    def test_a_book_shorter_than_the_floor_is_rejected(self):
        def novella(series_rec, book_num, meta, first, last, out_path, log_fn=None,
                    feedback=""):
            storage.save_json({"chapter_count": 9, "chapters": []}, out_path)
        metaplan.propose_chunk = novella
        with self.assertRaises(RuntimeError) as caught:
            metaplan.run(self.rec, 1, log_fn=lambda _m: None)
        self.assertIn("the floor is", str(caught.exception))


class ARepeatedGroupIsCaughtWhereItCanStillBeFixed(unittest.TestCase):
    """The one whole-book rule a late repair cannot close.

    Under-use and a thin world pairing are both fixable by writing more scenes later. A
    group of people already used in chapter 4 is a duplicate that no amount of
    re-planning chapter 40 will remove — so caught only at the end, every repair round
    fails identically and the book stalls forever on a state nothing can reach."""

    def setUp(self):
        support.wipe_state()
        self.sid = "meta-dupes"
        self.rec = journal.new_series(self.sid, f"/inbox/{self.sid}.md", "p")
        self.rec["universes"] = ["The Owl House", "Gravity Falls"]
        storage.save_json(PLAN, paths.plan_path(self.sid))
        storage.save_json({"characters": {}}, paths.series_bible_path(self.sid))

    def test_a_repeat_within_one_chunk_is_rejected(self):
        errors = metaplan._validate_chunk(
            {"chapters": [{"number": 1, "premise": "p", "cast": ["OH1", "GF1"],
                           "interactions": [
                               {"who": ["OH1", "GF1"], "promise": "a"},
                               {"who": ["GF1", "OH1"], "promise": "b"},
                               {"who": ["OH1", "GF1"], "promise": "c"},
                               {"who": ["OH1", "GF1"], "promise": "d"}]}]},
            1, {"OH1", "GF1"}, 33)
        self.assertTrue(any("already had a scene together" in e for e in errors))

    def test_a_repeat_of_something_already_committed_is_rejected(self):
        errors = metaplan._validate_chunk(
            {"chapters": [{"number": 5, "premise": "p", "cast": ["OH1", "GF1"],
                           "interactions": [{"who": ["OH1", "GF1"], "promise": "a"}]
                           * 1 + [{"who": ["OH1", "GF2"], "promise": "b"},
                                  {"who": ["OH2", "GF1"], "promise": "c"},
                                  {"who": ["OH2", "GF2"], "promise": "d"}]}]},
            5, {"OH1", "OH2", "GF1", "GF2"}, 33,
            used_subsets={frozenset(["OH1", "GF1"])})
        self.assertTrue(any("already had a scene together" in e for e in errors))

    def test_the_brief_lists_the_groups_already_used(self):
        brief = ledger_gate.shortfall_brief(
            [{"id": "x.1", "who": ["OH1", "GF1"], "chapter": 1}],
            {"OH1": "The Owl House", "GF1": "Gravity Falls"},
            ["The Owl House", "Gravity Falls"], 6, 0.6, 0.04)
        self.assertIn("GROUPS ALREADY USED", brief)
        self.assertIn("GF1 + OH1", brief)


class ARepairRoundWidensUntilItCanReachTheDefect(unittest.TestCase):

    def setUp(self):
        support.wipe_state()
        self.sid = "meta-repair"
        self.rec = journal.new_series(self.sid, f"/inbox/{self.sid}.md", "p")
        self.rec["universes"] = ["The Owl House", "Gravity Falls", "Amphibia",
                                 "She-Ra"]
        storage.save_json(PLAN, paths.plan_path(self.sid))
        storage.save_json({"characters": {}}, paths.series_bible_path(self.sid))

    def test_the_window_grows_each_round(self):
        meta = {"chapter_count": 45,
                "chapters": [{"number": n} for n in range(1, 46)]}
        first = metaplan._discard_tail(meta, 10)
        self.assertEqual(len(first["chapters"]), 35)
        second = metaplan._discard_tail(meta, 20)
        self.assertEqual(len(second["chapters"]), 25)

    def test_it_never_discards_the_whole_book(self):
        """Rebuilding from nothing would spend the whole ledger's calls again."""
        meta = {"chapter_count": 45,
                "chapters": [{"number": n} for n in range(1, 46)]}
        self.assertEqual(len(metaplan._discard_tail(meta, 999)["chapters"]), 1)

    def test_a_repair_refills_to_the_declared_chapter_count(self):
        """The repair used to append one chunk and hand straight back to the gate, so a
        re-proposal returning six chapters where ten were discarded left chapter_count
        at 45 against 41 actual chapters — journalled as the book's count, four
        chapters silently missing."""
        metaplan.propose_chunk = _cycling_chunks()
        meta = metaplan.run(self.rec, 1, log_fn=lambda _m: None)
        self.assertEqual(len(meta["chapters"]), meta["chapter_count"])
        self.assertEqual([c["number"] for c in meta["chapters"]],
                         list(range(1, meta["chapter_count"] + 1)))


class TheLedgerBelongsToTheSeriesNotOneBook(unittest.TestCase):
    """The bible spans a series; a meta plan covers one book. Assigning the whole list
    erased every collision book 1 promised, leaving the editor judging book 2 against a
    ledger saying none of book 1's scenes ever happened."""

    def setUp(self):
        support.wipe_state()
        self.sid = "meta-twobook"
        storage.save_json({"characters": {}, "interactions": [
            {"id": "x.1", "who": ["A", "B"], "promise": "book one scene",
             "book": 1, "chapters": [3], "status": "delivered"}]},
            paths.series_bible_path(self.sid))

    def test_an_earlier_books_entries_survive(self):
        meta = {"chapters": [{"number": 1, "interactions": [
            {"id": "x.1", "who": ["C", "D"], "promise": "book two scene"}]}]}
        metaplan._seed_bible(self.sid, meta, 2)
        entries = storage.load_json(paths.series_bible_path(self.sid))["interactions"]
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["promise"], "book one scene")
        self.assertEqual(entries[0]["status"], "delivered")

    def test_re_running_the_same_book_replaces_only_its_own(self):
        meta = {"chapters": [{"number": 1, "interactions": [
            {"id": "x.1", "who": ["C", "D"], "promise": "first try"}]}]}
        metaplan._seed_bible(self.sid, meta, 2)
        meta["chapters"][0]["interactions"][0]["promise"] = "second try"
        metaplan._seed_bible(self.sid, meta, 2)
        entries = storage.load_json(paths.series_bible_path(self.sid))["interactions"]
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[1]["promise"], "second try")


class TheShortfallBriefSteersTheNextChunk(unittest.TestCase):
    """A coverage gate that can only speak at the end is a gate that can only reject a
    180-entry artifact. Each chunk is told where it currently stands."""

    ORIGINS = {"OH1": "The Owl House", "OH2": "The Owl House",
               "GF1": "Gravity Falls", "GF2": "Gravity Falls"}

    def test_it_names_the_under_used_characters(self):
        entries = [{"id": "x.1", "who": ["OH1", "OH2"], "chapter": 1}]
        brief = ledger_gate.shortfall_brief(
            entries, self.ORIGINS, ["The Owl House", "Gravity Falls"], 6, 0.6, 0.04)
        self.assertIn("UNDER-USED", brief)
        self.assertIn("GF1 [0]", brief)

    def test_it_reports_the_cross_universe_share_so_far(self):
        entries = [{"id": "x.1", "who": ["OH1", "OH2"], "chapter": 1},
                   {"id": "x.2", "who": ["OH1", "GF1"], "chapter": 2}]
        brief = ledger_gate.shortfall_brief(
            entries, self.ORIGINS, ["The Owl House", "Gravity Falls"], 6, 0.6, 0.04)
        self.assertIn("50%", brief)

    def test_it_names_the_thin_world_pairings(self):
        entries = [{"id": "x.1", "who": ["OH1", "OH2"], "chapter": 1}]
        brief = ledger_gate.shortfall_brief(
            entries, self.ORIGINS, ["The Owl House", "Gravity Falls"], 6, 0.6, 0.04)
        self.assertIn("Gravity Falls x The Owl House [0]", brief)

    def test_an_empty_ledger_produces_a_usable_brief(self):
        brief = ledger_gate.shortfall_brief(
            [], self.ORIGINS, ["The Owl House"], 6, 0.6, 0.04)
        self.assertIn("UNDER-USED", brief)

    def test_it_reports_where_the_physical_share_stands(self):
        entries = [{"who": ["OH1", "GF1"], "chapter": 1, "register": "physical"},
                   {"who": ["OH2", "GF2"], "chapter": 2, "register": "comic"}]
        brief = ledger_gate.shortfall_brief(
            entries, self.ORIGINS, ["The Owl House", "Gravity Falls"], 6, 0.6, 0.04,
            physical_share=0.30, front_physical_share=0.20, back_physical_share=0.45)
        self.assertIn("PHYSICAL SHARE SO FAR: 50%", brief)
        self.assertIn("physical x1", brief)
        self.assertIn("comic x1", brief)


class WhatTheScenesDoIsCounted(unittest.TestCase):
    """Five coverage rules that count who is in a room are five rules a book of pure
    conversation passes. The previous book cleared every one of them and delivered
    forty chapters averaging two physical verbs each."""

    ORIGINS = {f"{world}{i}": name
               for world, name in (("OH", "The Owl House"), ("GF", "Gravity Falls"))
               for i in range(1, 4)}
    UNIVERSES = ["The Owl House", "Gravity Falls"]

    def _ledger(self, registers):
        """One interaction per chapter, register taken from `registers` in order.

        The groups have to be distinct and varied in size even though neither is what
        these tests are about, because the rest of the gate is still running and would
        otherwise reject the fixture for repeats — which would make a register test
        pass or fail for reasons that have nothing to do with registers."""
        names = sorted(self.ORIGINS)
        pool = [list(group) for size in (2, 3, 4)
                for group in combinations(names, size)]
        return [{"id": f"x.{i}", "who": pool[(i * 7) % len(pool)], "chapter": i,
                 "register": register}
                for i, register in enumerate(registers, 1)]

    def _check(self, registers, **kwargs):
        # The rules under test are the register ones, so the appearance floor is
        # dropped to zero — otherwise a two-name fixture fails for a reason that has
        # nothing to do with what is being asserted.
        options = {"min_appearances": 0, "cross_share": 0.0, "pairing_share": 0.0}
        options.update(kwargs)
        return ledger_gate.check(
            self._ledger(registers), self.ORIGINS, self.UNIVERSES, **options)

    def test_a_ledger_of_pure_conversation_is_rejected(self):
        report = self._check(["conflict", "investigation", "comic", "tender"] * 3)
        self.assertFalse(report.passed)
        self.assertTrue(any("are `physical`" in e for e in report.errors),
                        report.errors)

    def test_an_interaction_with_no_register_is_rejected(self):
        report = self._check(["physical", "", "physical", "comic"])
        self.assertTrue(any("no valid `register`" in e for e in report.errors),
                        report.errors)

    def test_an_unknown_register_is_not_quietly_accepted(self):
        report = self._check(["physical", "banter", "physical", "comic"])
        self.assertTrue(any("no valid `register`" in e for e in report.errors),
                        report.errors)

    def test_saving_the_action_for_the_back_half_is_rejected(self):
        """The failure a single whole-book floor cannot see, and the reason there are
        three numbers instead of one: forty chapters of talking and eight of fighting
        satisfies any share you like when averaged over the book."""
        registers = ["comic"] * 8 + ["physical"] * 4
        report = self._check(registers, physical_share=0.30)
        self.assertTrue(report.passed is False)
        self.assertTrue(any("front half" in e for e in report.errors), report.errors)

    def test_a_back_half_that_levels_off_is_rejected(self):
        """Front half 50% physical, back half 17%, whole book 33% — so the whole-book
        floor is satisfied and only the escalation rule can catch it. A book that
        front-loads its action and then stops is as broken as one that back-loads it,
        and averaging over the book sees neither."""
        registers = (["physical", "comic"] * 3) + ["physical"] + ["comic"] * 5
        report = self._check(registers, physical_share=0.30,
                             front_physical_share=0.20, back_physical_share=0.45)
        self.assertFalse(report.passed)
        self.assertTrue(any("back half" in e for e in report.errors), report.errors)
        self.assertFalse(any("the floor is 30%" in e for e in report.errors),
                         report.errors)

    def test_escalating_action_clears_the_floors(self):
        front = ["physical", "comic", "conflict", "investigation"]
        back = ["physical", "tender", "physical", "comic"]
        report = self._check(front + back)
        self.assertTrue(report.passed, report.errors)

    def test_a_ledger_of_nothing_but_fighting_is_also_rejected(self):
        """The mirror failure. Two hundred fights is one note played two hundred
        times, exactly as two hundred conversations was."""
        report = self._check(["physical"] * 12)
        self.assertFalse(report.passed)
        self.assertTrue(any("no single register" in e for e in report.errors),
                        report.errors)

    def test_the_halfway_point_comes_from_the_ledger(self):
        entries = [{"who": ["OH1"], "chapter": c} for c in range(1, 10)]
        self.assertEqual(ledger_gate.halfway(entries), 5)
        self.assertEqual(ledger_gate.halfway([]), 0)


if __name__ == "__main__":
    unittest.main()
