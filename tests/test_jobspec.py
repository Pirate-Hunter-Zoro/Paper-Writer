"""Parsing the dropped prompt file.

The universe list feeds one research call and one canon directory each, so getting
it wrong is expensive: on 2026-08-04 a prose-y section body was shredded into eight
junk universes and eight junk research calls.
"""

import unittest

import support                                                    # noqa: F401

from fanfic import jobspec                                        # noqa: E402


class UniverseParsingTests(unittest.TestCase):
    def _universes(self, section_body):
        return jobspec.universes(
            f"## Source universe(s)\n{section_body}\n\n## Premise\nx\n")

    def test_prose_paragraph_yields_one_clean_universe(self):
        body = ("Star Wars: The Old Republic\n\nSingle source universe, played as a "
                "Guardian; mine the wikis, its characters, planets and the era.")
        self.assertEqual(self._universes(body), ["Star Wars: The Old Republic"])

    def test_colon_is_kept_but_dash_qualifier_dropped(self):
        self.assertEqual(
            self._universes("Star Wars: The Old Republic — Sith Warrior class story"),
            ["Star Wars: The Old Republic"])

    def test_terse_single_and_crossover(self):
        self.assertEqual(self._universes("RWBY."), ["RWBY"])
        self.assertEqual(
            self._universes("The Owl House + Gravity Falls + Amphibia + She-Ra"),
            ["The Owl House", "Gravity Falls", "Amphibia", "She-Ra"])

    def test_no_universe_section_yields_nothing(self):
        self.assertEqual(jobspec.universes("# Job\n\n## Premise\nsomething\n"), [])


class ImpliedEntityTests(unittest.TestCase):
    """Every entity here is a denominator term in the canon-coverage gate, so an
    entity no fact could ever match is a free penalty against a good job."""

    def test_a_hyphenated_name_survives_intact(self):
        """Without hyphen support "She-Ra and the Princesses of Power" scanned as the
        word "She", then "Princesses", then "Power" — one correctly spelled show
        turned into three denominator terms no canon fact can match. Hyphenated names
        are ordinary in this domain, so the pattern has to admit them."""
        entities = jobspec.implied_entities(
            "## Main characters to feature\nAdora and She-Ra, plus Obi-Wan Kenobi\n")
        self.assertIn("She-Ra", entities)
        self.assertIn("Obi-Wan Kenobi", entities)
        self.assertNotIn("Princesses", entities)

    def test_a_list_header_is_stripped_down_to_the_name_it_carries(self):
        """"From Gravity Falls: Dipper Pines" is a heading plus a name. No wiki has a
        page for "From Gravity Falls", and the gate would count it as a miss."""
        entities = jobspec.implied_entities(
            "## Main characters to feature\n"
            "From Gravity Falls: Dipper Pines, Mabel Pines\n")
        self.assertNotIn("From Gravity Falls", entities)
        self.assertIn("Gravity Falls", entities)
        self.assertIn("Dipper Pines", entities)

    def test_stripping_a_header_does_not_discard_the_name_behind_it(self):
        """The lone-word-opening-a-line rule judges the SPAN as it appeared, not what
        is left after the scaffolding comes off — otherwise "From She-Ra" at the start
        of a line loses the name along with the preposition."""
        entities = jobspec.implied_entities(
            "## Main characters to feature\nFrom She-Ra: Adora and Catra\n")
        self.assertIn("She-Ra", entities)

    def test_names_come_from_characters_and_anchor_sections(self):
        entities = jobspec.implied_entities(
            "## Main characters to feature\nRuby Rose and Weiss Schnee\n\n"
            "## Canon anchor point\nAfter the fall of Atlas\n\n"
            "## Tone\nNothing here should be picked up\n")
        self.assertIn("Ruby Rose", entities)
        self.assertIn("Weiss Schnee", entities)
        self.assertIn("Atlas", entities)

    def test_stopwords_are_not_entities(self):
        self.assertEqual(jobspec.implied_entities("## Main characters\nThe And\n"), [])

    def test_a_name_split_across_a_wrapped_line_is_one_clean_entity(self):
        """"Jedi\\nOrder" could never match "Jedi Order" in a canon fact."""
        entities = jobspec.implied_entities(
            "## Main characters\nthe Jedi\nOrder stands on Tython\n")
        self.assertIn("Jedi Order", entities)
        self.assertFalse([e for e in entities if "\n" in e])

    def test_prose_opening_a_sentence_or_a_bold_run_is_not_an_entity(self):
        entities = jobspec.implied_entities(
            "## Main characters\nKira Carsen hides a secret. This is a central "
            "thread. Stay consistent with canon.\n\n"
            "## Canon anchor point\n**Act 1 — the vengeance.** Grim, patient.\n")
        self.assertIn("Kira Carsen", entities)
        for prose in ("This", "Stay", "Act", "Grim"):
            self.assertNotIn(prose, entities)

    def test_a_multiword_name_survives_the_same_position(self):
        """"Master Orgus Din" is a name wherever it appears, sentence-initial or not."""
        entities = jobspec.implied_entities(
            "## Main characters\nShe trains hard. Master Orgus Din guides her.\n")
        self.assertIn("Master Orgus Din", entities)


class ArtDirectionTests(unittest.TestCase):
    """The style block is stamped on every image prompt, so it has to come from the
    job — otherwise a Star Wars novelization gets the previous fic's anime styling."""

    def test_reads_from_the_style_label_onward(self):
        style = jobspec.art_direction(
            "## Illustrations\n**One illustration per chapter**, plus a cover. "
            "Style: **painterly digital illustration in the key-art\nstyle of "
            "*Star Wars: The Old Republic*** — cinematic lighting.\n")
        self.assertTrue(style.startswith("painterly digital illustration"))
        self.assertIn("Star Wars: The Old Republic", style)
        self.assertNotIn("*", style)                    # emphasis stripped
        self.assertNotIn("\n", style)                   # wrapped lines collapsed
        self.assertNotIn("per chapter", style)          # the count is not the style

    def test_absent_section_falls_back(self):
        self.assertEqual(jobspec.art_direction("# Job\n\n## Premise\nx\n"), "")


class RealPromptRegressionTests(unittest.TestCase):
    """Pin the actual SWTOR job. Guessing at its parsing cost a run once already.

    Found wherever it currently lives — the drop folder moves between iCloud, the
    repo, finished/, and failed/, and an earlier version of this class hard-coded one
    of those paths and silently skipped the moment the file moved."""

    def setUp(self):
        path = support.prompt_fixture("swtor-jedi-knight.md")
        if path is None:
            self.skipTest("no real SWTOR prompt on this machine")
        self.text = path.read_text(encoding="utf-8")

    def test_one_clean_universe(self):
        self.assertEqual(jobspec.universes(self.text),
                         ["Star Wars: The Old Republic"])

    def test_entities_are_real_names_and_the_gate_is_reachable(self):
        entities = jobspec.implied_entities(self.text)
        for name in ("Kira Carsen", "Master Orgus Din", "Lord Scourge",
                     "Darth Angral", "Grand Master Satele Shan", "Tython",
                     "Jedi Order"):
            self.assertIn(name, entities)
        for prose in ("This", "Stay", "Grim", "Treaty"):
            self.assertNotIn(prose, entities)
        self.assertFalse([e for e in entities if "\n" in e])
        # The floor must be clearable: at 85% over this many entities there has to be
        # room for the handful of genuinely uncoverable terms ("Act", "Rise", "BBY").
        tolerated = len(entities) - -(-int(len(entities) * 85) // 100)
        self.assertGreaterEqual(tolerated, 4, f"{len(entities)} entities is too tight")

    def test_art_direction_is_swtor_key_art_not_the_anime_default(self):
        style = jobspec.art_direction(self.text)
        self.assertIn("painterly", style)
        self.assertIn("key-art", style)
        self.assertNotIn("cel-shaded", style)


if __name__ == "__main__":
    unittest.main(verbosity=2)
