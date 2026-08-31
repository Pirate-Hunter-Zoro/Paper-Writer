"""The cost model: does it reproduce the measurement it was built from?

A cost model that cannot recover the number actually observed is decoration. So the
configured estimate must land near the ~$300-500 of list-price-equivalent usage the
meter recorded for a real book, and the forced-agentic estimate must show the order of
magnitude the one-shot transport actually buys.

This file used to also test a budget solver — "what model do I have to buy to bring a
book in under $5" — and a preset table spanning five vendors. Both are gone with the
thing they were for. Text is Claude at one model and pictures are drawn through a
browser session for nothing, so there is no bill left to shop for, and a solver that
answered a question nobody can act on is a maintained decoration.

What is tested instead is the honesty of what remains: the levers that still exist,
and the model's refusal to flatter itself when a measurement is stale.
"""

import support                                    # noqa: F401  (redirects state first)

import unittest

from fanfic import config, cost


class Reproduction(unittest.TestCase):
    """Pinned against the metered run, not against itself."""

    def test_the_configured_estimate_is_in_the_measured_range(self):
        """Measured on the live run: $1.50 an editorial pass, $1.30 a plan, $2.18 an
        outline. Anything far off means the measurements went stale — re-measure after
        any prompt or role change."""
        total = cost.estimate()["total"]
        self.assertGreater(total, 200)
        self.assertLess(total, 600)

    def test_the_forced_agentic_estimate_is_still_far_worse(self):
        """`one_shot=False` forces the old transport for every role. It uses the token
        arithmetic rather than the measurements, so it is a LOWER BOUND on how bad
        things were — and it is still worse than the measured configuration.

        This is the largest lever left in the project, and the reason it is worth a
        test: with vendor-shopping gone, transport is the only thing that moves the
        number by an order of magnitude."""
        agentic = cost.estimate(one_shot=False)["total"]
        self.assertGreater(agentic, cost.estimate()["total"])

    def test_editing_is_the_bill_and_the_pass_count_is_the_lever(self):
        """This claim has now flipped twice, which is the thing worth pinning.

        First it was "judgment is ~70%", derived from token arithmetic that counted
        only the artifact and its digest. Then measurement said writing was the larger
        half, because every one of ~7 rounds bought a draft AND a continuation AND a
        critique. Now a chapter is drafted **once** and edited two or three times, so
        writing is a fixed cost per chapter and editing scales with the pass count —
        and editing is the bill again.

        The reason that is not a regression: the old loop's judging was re-judging the
        same chapter eleven times, and this loop's is buying repairs. The lever moved
        with it, and it is `EDIT_MAX_PASSES` — not a model choice, because there is no
        model choice."""
        result = cost.estimate()
        by_role = {line["role"]: line["cost"] for line in result["lines"]}
        writing = by_role["drafting"] + by_role["continuation"]
        self.assertGreater(by_role["editing"], writing)

        # And it is the pass count that moves it, not the chapter count.
        cheaper = cost.estimate(passes=2)
        self.assertLess(cheaper["total"], result["total"])

    def test_a_chapter_is_drafted_once_however_many_passes_it_takes(self):
        """The single most important line in the model. Costing drafting as
        `chapters x rounds` was right for the loop that redrafted and overstates this
        one by about 4x — and worse, it points the optimisation at drafting when the
        lever is the number of editorial passes."""
        chapters = 37
        for passes in (1, 3, 6):
            counts, _pictures = cost.call_counts(chapters, passes)
            self.assertEqual(counts["drafting"], chapters)

    def test_a_measurement_beats_the_arithmetic(self):
        """Where a real per-call figure exists for the model actually configured, it
        must win — the arithmetic is wrong by ~5x and wrong for a reason it cannot
        see: the CLI's own system prompt, tool definitions and reasoning tokens are
        invisible to a model that counts the digest and the artifact."""
        result = cost.estimate(model="claude-opus-5")
        editing = next(l for l in result["lines"] if l["role"] == "editing")
        self.assertTrue(editing["measured"])
        self.assertAlmostEqual(
            editing["cost"],
            editing["calls"] * cost.MEASURED_USD[("editing", "claude-opus-5")],
            places=4)

    def test_a_measurement_taken_at_another_model_is_not_reused(self):
        """The trap this refactor walked straight into: `drafting` was measured at
        $0.82 on Sonnet, and every role is Opus now at 2.5x the rate. Silently reusing
        that figure would understate a book by exactly the amount the tier change
        cost, and it would do it in the direction that flatters the decision.

        So the line falls back to arithmetic and is FLAGGED as modelled. The
        arithmetic runs light, which is why the flag matters more than the number."""
        result = cost.estimate(model="claude-opus-5")
        drafting = next(l for l in result["lines"] if l["role"] == "drafting")
        self.assertFalse(drafting["measured"])
        self.assertNotAlmostEqual(
            drafting["cost"],
            drafting["calls"] * cost.MEASURED_USD[("drafting", "claude-sonnet-5")],
            places=2)

    def test_the_breakdown_says_which_rows_are_only_modelled(self):
        text = cost.render(cost.estimate())
        self.assertIn("modelled from token volumes", text)
        self.assertIn("METER, NOT A BILL", text)


class PicturesAreNotABill(unittest.TestCase):
    """The other half of the refactor, and the half a stale cost model would hide.

    Pictures used to be the only genuine money this fleet spent, and the estimator
    carried a per-image price, an `__image__` unpriced marker, and an image row in
    every total. They are drawn through a signed-in browser now. A model still
    charging for them would keep pointing the reader at a saving that no longer
    exists."""

    def test_there_is_no_per_image_price_left_to_set(self):
        self.assertFalse(hasattr(config, "IMAGE_UNIT_PRICE"))
        self.assertFalse(hasattr(config, "IMAGE_BUDGET_USD"))

    def test_drawing_pictures_adds_nothing_to_the_total_but_judging_them_does(self):
        """The honest accounting: the render is free and the vision critique is a
        Claude call, so turning pictures off saves exactly the critiques."""
        with_pictures = cost.estimate()
        without = cost.estimate(images_per_chapter=0)
        vision = next(l for l in with_pictures["lines"] if l["role"] == "vision")
        self.assertAlmostEqual(with_pictures["total"] - without["total"],
                               vision["cost"], places=2)

    def test_the_picture_count_is_still_reported_so_the_time_cost_is_visible(self):
        """Free is not the same as costless — 277 renders is hours of browser
        wall-clock, and a reader deciding whether to draw them needs the number."""
        result = cost.estimate()
        self.assertGreater(result["pictures"], 0)
        self.assertIn("drawn through the browser session", cost.render(result))

    def test_a_text_only_book_reports_no_pictures_at_all(self):
        result = cost.estimate(images_per_chapter=0)
        self.assertEqual(result["pictures"], 0)


class HonestAboutUnknowns(unittest.TestCase):
    """A cost model that invents a price is worse than one that admits ignorance.

    The lesson outlived the table it was learned on: this module once shipped with
    only the Anthropic prices filled in and concluded, from that gap, that a cheap
    book required local inference. The arithmetic was right and the conclusion was
    wrong, because the comparison had never been made. Refusing to invent a number is
    right; declining to go and look one up is not the same thing."""

    def test_an_unpriced_model_is_reported_not_guessed(self):
        result = cost.estimate(model="some-model-nobody-priced")
        self.assertIn("some-model-nobody-priced", result["unpriced"])
        for line in result["lines"]:
            self.assertIsNone(line["cost"])

    def test_render_says_price_not_set_rather_than_a_number(self):
        text = cost.render(cost.estimate(model="unpriced-thing"))
        self.assertIn("price not set", text)

    def test_the_model_this_fleet_actually_runs_is_priced(self):
        """The one that would matter. An unpriced default means every projection the
        estimator has ever printed was blank, which is a thing nobody notices until
        they need the number."""
        self.assertIsNotNone(cost.price(config.MODEL))


class TheLeversThatAreLeft(unittest.TestCase):
    """`levers()` replaced the budget solver. The old question — which model do I buy
    to hit $5 — has no answer any more, because the model is decided and the pictures
    are free. The useful question became which of the remaining knobs actually moves
    the number, and it is answered by running them rather than by arguing."""

    def test_every_preset_is_priced_and_named(self):
        results = cost.levers()
        self.assertTrue(results)
        for name, total, _delta in results:
            self.assertIsInstance(name, str)
            self.assertGreater(total, 0, name)

    def test_the_baseline_lever_is_the_baseline(self):
        by_name = {name: (total, delta) for name, total, delta in cost.levers()}
        _total, delta = by_name["as configured"]
        self.assertAlmostEqual(delta, 0.0, places=2)

    def test_fewer_editorial_passes_is_a_real_saving_and_the_deltas_say_so(self):
        by_name = {name: (total, delta) for name, total, delta in cost.levers()}
        self.assertLess(by_name["2 editorial passes"][1], 0)
        self.assertGreater(by_name["4 editorial passes"][1], 0)

    def test_no_preset_names_a_vendor(self):
        """The presets used to be a shopping list — DeepSeek, Luna, Haiku judges. A
        preset naming a model this fleet cannot be configured to use is a suggestion
        the reader cannot act on."""
        for name, _total, _delta in cost.levers():
            for vendor in ("deepseek", "gpt", "luna", "local", "haiku", "sonnet"):
                self.assertNotIn(vendor, name.lower())


if __name__ == "__main__":
    unittest.main()
