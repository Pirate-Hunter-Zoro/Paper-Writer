"""The provider layer: one text source, one image source, and one role table.

This file used to test a registry — five text backends, per-role routing, capability
declarations so a webless provider could refuse research, and a contract that differed
by transport. All of that is gone, and it went for reasons written down in
`fanfic/providers/__init__.py`: the swappability was never exercised on a real book,
every prompt in `prompts/` is written against Claude's habits, and the two-tier model
split gave every quality problem a second suspect in a project whose entire product is
prose quality.

What remains worth pinning is what remains load-bearing:

  * **one model, everywhere** — a role that quietly resolves to something else is the
    exact regression this refactor exists to prevent,
  * **the role table** — the numbers that stop a stage hand-tuning its own budget,
  * **the delivery contract** — the instruction that keeps the propose/dispose spine
    intact,
  * **the image session gate** — a browser profile that is not signed in must be a
    named, actionable refusal rather than a mysterious render failure.
"""

import support                                    # noqa: F401  (redirects state first)

import unittest

from fanfic import config, providers
from fanfic.models import text as textgen
from fanfic.providers import base, image_browser, text_cli


class OneModelEverywhere(unittest.TestCase):
    """The whole point of the refactor, asserted directly.

    The regression this guards against is subtle and was live for weeks: roles drift
    onto different models one env override at a time, each defensible on its own, and
    the fleet ends up with three models nobody chose. Every role resolving to the same
    string is what makes a chapter's quality attributable to something."""

    def test_every_role_resolves_to_the_configured_model(self):
        for name in config.TEXT_ROLES:
            self.assertEqual(providers.role(name).model, config.MODEL, name)

    def test_the_configured_model_is_an_opus(self):
        """Not a style preference: the roles this fleet runs are long-form prose and
        canon judgement, and the cheap tier was measured choosing image moments that
        could not be drawn and drafts that had to be redone."""
        self.assertIn("opus", config.MODEL)

    def test_no_role_carries_a_tier_or_a_provider_of_its_own(self):
        """The columns are gone from the table, not merely unused. A spec that still
        carried one would resolve to nothing and fail silently."""
        for name, spec in config.TEXT_ROLES.items():
            self.assertNotIn("tier", spec, name)
            self.assertNotIn("provider", spec, name)

    def test_the_role_object_has_no_routing_surface_left(self):
        role = providers.role("editing")
        for attribute in ("tier", "provider_name", "needs_web"):
            self.assertFalse(hasattr(role, attribute), attribute)


class Registry(unittest.TestCase):
    """There are two providers and they are named, not looked up."""

    def test_text_is_the_claude_cli(self):
        self.assertIs(providers.text(), text_cli)

    def test_images_are_the_browser_driver(self):
        self.assertIs(providers.image(), image_browser)

    def test_both_satisfy_their_contracts(self):
        self.assertTrue(hasattr(providers.text(), "produce"))
        self.assertTrue(hasattr(providers.text(), "contract"))
        self.assertTrue(hasattr(providers.image(), "generate"))
        self.assertIsInstance(providers.text().CAPABILITY, base.Capability)
        self.assertIsInstance(providers.image().CAPABILITY, base.Capability)

    def test_the_image_provider_can_still_take_reference_pictures(self):
        """Load-bearing rather than decorative: visual consistency across a series is
        solved by feeding the locked sheets back on every render, and a driver that
        could not upload them would have been a downgrade, not a change."""
        self.assertTrue(providers.image().CAPABILITY.supports_references)

    def test_an_unknown_role_names_the_valid_ones(self):
        with self.assertRaises(KeyError) as caught:
            providers.role("interpretive-dance")
        self.assertIn("editing", str(caught.exception))

    def test_describe_reports_both_services_for_the_startup_log(self):
        line = providers.describe()
        self.assertIn(config.MODEL, line)
        self.assertIn("Gemini", line)

    def test_describe_says_so_when_the_browser_session_is_missing(self):
        """A misconfiguration must be visible in the first two lines of a daemon log
        rather than inferred much later from a stage that keeps failing."""
        original = config.GEMINI_PROFILE_DIR
        try:
            config.GEMINI_PROFILE_DIR = config.STATE_DIR / "no-such-profile"
            self.assertIn("NOT READY", providers.describe())
        finally:
            config.GEMINI_PROFILE_DIR = original


class Roles(unittest.TestCase):
    """One table instead of eight stages each hand-tuning turns and timeouts."""

    def test_every_role_a_stage_names_exists(self):
        """A typo in a `role=` string must not wait until that stage runs at 3 a.m."""
        import re, pathlib
        # Anchored to this file, not to the cwd. A relative "fanfic/stages" resolves
        # to nothing unless the suite is run from the repo root, and a scan that finds
        # no call sites cannot tell "the grep broke" from "the cwd moved" — it just
        # stops checking anything.
        stages = pathlib.Path(__file__).resolve().parent.parent / "fanfic" / "stages"
        used = set()
        for path in stages.glob("*.py"):
            used |= set(re.findall(r'role="([a-z_]+)"', path.read_text()))
        self.assertTrue(used, f"found no role= call sites under {stages}")
        self.assertEqual(used - set(config.TEXT_ROLES), set())

    def test_wall_clock_scales_with_the_size_of_the_artifact(self):
        """Turn count stopped being the right measure of a stage's size once the roles
        went one-shot: every artifact is a single Write, so a turn budget is thinking
        headroom, not length allowance. Wall clock still scales with the artifact, and
        it is the limit that would actually cut one off.

        Drafting used to be the largest artifact in the pipeline and this test used to
        say so. It is not any more, and the correction was paid for: a 52-character
        plan — an appearance, a voice, costumes, a palette and a progression each, plus
        the antagonists — came back truncated mid-array at 114,090 characters, which is
        not a proposal a gate can reject usefully. The once-per-series planning and
        outlining documents are now the big ones, and a book's worth of them is written
        exactly once, so they are also the cheapest place to be generous."""
        drafting = providers.role("drafting").timeout
        # The per-chapter writing roles, where drafting is still the biggest.
        for name in ("editing", "bible_merge", "art_direction"):
            self.assertGreaterEqual(drafting, providers.role(name).timeout, name)
        # And the whole-book documents, which are larger than any single chapter.
        for name in ("planning", "outlining"):
            self.assertGreaterEqual(providers.role(name).timeout, drafting, name)

    def test_one_shot_roles_cannot_read(self):
        """A one-shot role is told its whole input is in the prompt. Granting Read to
        a model told not to read is an invitation to spend the tokens anyway, and the
        grant is the only part of that instruction the harness can enforce."""
        for name, spec in config.TEXT_ROLES.items():
            if spec.get("oneshot"):
                self.assertEqual(set(providers.role(name).tools), {"Write"}, name)

    def test_every_high_volume_role_is_one_shot_except_research(self):
        """Research has to go and find its input; nothing else does. A high-volume
        role left agentic is a ~10x input-token bill for the same artifact, which is
        now the largest lever in the project by a wide margin — there is no vendor
        swap left to compare it against."""
        for name in ("anchoring", "planning", "outlining", "drafting",
                     "continuation", "editing"):
            self.assertTrue(config.TEXT_ROLES[name].get("oneshot"), name)

    def test_only_research_reaches_the_network(self):
        """This runs unattended with permissions skipped, so a grant is a blast
        radius."""
        for name in config.TEXT_ROLES:
            tools = set(providers.role(name).tools)
            if name != "research":
                self.assertEqual(tools & {"WebSearch", "WebFetch", "Bash"}, set(), name)

    def test_research_keeps_the_web_tools_it_needs(self):
        tools = set(providers.role("research").tools)
        self.assertIn("WebSearch", tools)
        self.assertIn("WebFetch", tools)

    def test_vision_is_the_one_role_allowed_to_read(self):
        """It must open the image it is judging and the references the generator was
        given, which is precisely why it is not one-shot."""
        self.assertIn("Read", providers.role("vision").tools)
        self.assertFalse(config.TEXT_ROLES["vision"].get("oneshot"))


class DeliveryContract(unittest.TestCase):
    """One contract now, because there is one transport. The propose/dispose spine
    does not bend, so the instruction that expresses it is pinned."""

    def test_the_model_is_told_to_write_exactly_the_path(self):
        contract = text_cli.contract(config.STATE_DIR / "tmp" / "a.json", "the plan")
        self.assertIn("EXACTLY this path", contract)
        self.assertIn("a.json", contract)

    def test_a_one_shot_role_is_told_to_read_nothing_and_write_once(self):
        """The single largest lever in the project. A writer that opens the previous
        draft and appends eight times pays for the whole accumulating transcript eight
        times over — ~227,000 input tokens for a 7,200-token chapter."""
        contract = text_cli.contract(config.STATE_DIR / "tmp" / "a.md", "the chapter",
                                     oneshot=True)
        self.assertIn("Do NOT read", contract)
        self.assertIn("ONE Write tool call", contract)

    def test_the_one_shot_instruction_follows_the_role(self):
        out = config.STATE_DIR / "tmp" / "contract-probe.md"
        oneshot = textgen.compose("", ["f"], out, artifact="prose",
                                  role_name="drafting")
        agentic = textgen.compose("", ["f"], out, artifact="prose",
                                  role_name="research")
        self.assertIn("ONE Write tool call", oneshot)
        self.assertNotIn("ONE Write tool call", agentic)
        # Both still name the path: the spine is the same either way.
        self.assertIn("EXACTLY this path", oneshot)
        self.assertIn("EXACTLY this path", agentic)

    def test_there_is_no_reply_contract_left_to_hand_to_anyone(self):
        """It existed for providers with no filesystem. Handing it to Claude would
        produce a chapter in a chat reply and an empty file, which is the failure the
        two-contract split existed to prevent and the reason it is gone."""
        self.assertFalse(hasattr(base, "reply_contract"))


class TheSessionIsCheckedBeforeARenderIsSpent(unittest.TestCase):
    """A signed-out browser profile is a human errand, not a render failure.

    This replaces the old "is the API key on disk" check and does the same job it did:
    give a precise reason BEFORE burning an attempt. Getting it wrong costs more here
    than it did there, because a headless browser failure at 3 a.m. leaves no trace
    anyone can read the next morning."""

    def setUp(self):
        self._profile = config.GEMINI_PROFILE_DIR

    def tearDown(self):
        config.GEMINI_PROFILE_DIR = self._profile

    def test_a_missing_profile_is_named_along_with_its_fix(self):
        config.GEMINI_PROFILE_DIR = config.STATE_DIR / "nothing-here"
        reason = image_browser.missing_prerequisite()
        self.assertIsNotNone(reason)
        self.assertIn("gemini-login.sh", reason)
        self.assertFalse(image_browser.is_configured())

    def test_generating_without_a_session_raises_the_actionable_error(self):
        config.GEMINI_PROFILE_DIR = config.STATE_DIR / "nothing-here"
        out = config.STATE_DIR / "tmp" / "no-session.png"
        with self.assertRaises(image_browser.NotSignedIn) as caught:
            image_browser.generate("a red circle", out)
        self.assertIn("gemini-login.sh", str(caught.exception))

    def test_not_signed_in_is_a_runtime_error_so_nothing_downstream_leaks_it(self):
        """The engine's handlers are written against RuntimeError and QuotaExceeded.
        A brand-new exception type escaping to `daemons.loop` would be counted as a
        cycle crash rather than a wait."""
        self.assertTrue(issubclass(image_browser.NotSignedIn, RuntimeError))

    def test_the_driver_ships_with_the_repo(self):
        """The Python half is useless without it, and a missing driver would look
        exactly like a browser that would not start."""
        self.assertTrue(image_browser.driver_path().exists())


class NoCredentialsAnywhere(unittest.TestCase):
    """The refactor's other promise: there is no API key in this project at all.

    Worth a test rather than a comment, because a key file creeps back in one
    convenience at a time and nothing else would notice."""

    def test_config_holds_no_key_file_paths(self):
        for name in dir(config):
            self.assertFalse(name.endswith("_KEY_FILE"), name)

    def test_no_module_reads_an_api_key_from_the_environment(self):
        import pathlib
        package = pathlib.Path(__file__).resolve().parent.parent / "fanfic"
        needles = ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                   "DEEPSEEK_API_KEY")
        offenders = []
        for path in package.rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(),
                                          1):
                # A key name in a comment or docstring is fine — `image_browser` says
                # in prose that there is no such key, which is the point. A key name
                # next to an environment read is not.
                if "os.environ" in line and any(n in line for n in needles):
                    offenders.append(f"{path.name}:{number}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
