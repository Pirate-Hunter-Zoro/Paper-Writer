"""The cost projection. Pure arithmetic, and the tests are about honesty rather than
accuracy: a number this module invents is worse than one it declines to give.
"""

import support                                                      # noqa: F401
import unittest                                                     # noqa: E402

from paperwriter import config, cost                                # noqa: E402


class CallCountTests(unittest.TestCase):

    def test_a_section_is_drafted_exactly_once(self):
        """Every later change is an anchored repair. Modelling it as a redraft per
        round overstates a paper several times over and points the optimisation at the
        wrong thing."""
        counts = cost.call_counts(10, passes=3)
        self.assertEqual(counts["drafting"], 10)

    def test_the_one_off_stages_run_once(self):
        counts = cost.call_counts(10, passes=3)
        for role in ("evidence", "grounding", "planning", "argument", "outlining"):
            self.assertEqual(counts[role], 1, role)

    def test_review_scales_with_passes_and_the_sweep(self):
        two = cost.call_counts(10, passes=2)["review"]
        four = cost.call_counts(10, passes=4)["review"]
        self.assertGreater(four, two)
        # The sweep is in there too, so review is never merely sections * passes.
        self.assertGreater(two, 10 * 2)

    def test_every_role_in_the_count_has_a_volume(self):
        """A role counted with no volume raises at projection time, which is a
        programming error rather than a runtime condition."""
        for role in cost.call_counts(5, passes=3):
            self.assertIn(role, cost.VOLUMES, role)

    def test_every_configured_role_is_counted(self):
        """The other direction. A role in the config table that the estimator does not
        know about is a call nobody is projecting."""
        counted = set(cost.call_counts(5, passes=3))
        self.assertEqual(set(config.TEXT_ROLES) - counted, set())


class EstimateTests(unittest.TestCase):

    def test_one_shot_is_the_largest_lever(self):
        """Bigger than any model choice, and it is a property of the role rather than
        of the provider."""
        agentic = cost.estimate(one_shot=False)["total"]
        oneshot = cost.estimate(one_shot=True)["total"]
        self.assertGreater(agentic, oneshot * 2)

    def test_an_unpriced_model_is_reported_rather_than_guessed(self):
        result = cost.estimate(model="some-model-nobody-priced")
        self.assertEqual(result["total"], 0.0)
        self.assertEqual(result["unpriced"], ["some-model-nobody-priced"])
        self.assertIn("price not set", cost.render(result))

    def test_a_modelled_row_is_flagged_as_modelled(self):
        """Token arithmetic cannot see the CLI's own system prompt or the model's
        reasoning tokens, so it runs light. A projection that did not say so would be
        believed."""
        text = cost.render(cost.estimate())
        self.assertIn("~", text)
        self.assertIn("modelled from token volumes", text)

    def test_the_total_is_a_meter_not_a_bill(self):
        self.assertIn("METER, NOT A BILL", cost.render(cost.estimate()))

    def test_levers_are_deltas_against_the_configured_baseline(self):
        rows = dict((name, delta) for name, _total, delta in cost.levers())
        self.assertAlmostEqual(rows["as configured"], 0.0, places=6)
        self.assertGreater(rows["forced agentic (the old way)"], 0)
        self.assertLess(rows["2 editorial passes"], 0)

    def test_the_cli_runs(self):
        self.assertEqual(cost.main([]), 0)
        self.assertEqual(cost.main(["--presets"]), 0)
        self.assertEqual(cost.main(["--measured"]), 0)


if __name__ == "__main__":
    unittest.main()
