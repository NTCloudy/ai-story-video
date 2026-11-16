import unittest
from unittest import mock

from storyvideo import shorts

WRONG = {"youtube_title": "Why Animal Cruelty Laws Differ Worldwide #shorts", "hook_text": "LAWS VARY GLOBALLY",
         "youtube_description": "How animal cruelty laws vary between countries.",
         "scenes": [{"narration": "Laws concerning animal cruelty differ completely across the world."}]}
RIGHT = {"youtube_title": "This Frog Breaks Its Own Bones to Fight #shorts", "hook_text": "WOLVERINE FROG",
         "youtube_description": "The hairy frog pushes its toe bones through its skin.",
         "scenes": [{"narration": "The hairy frog breaks its own toe bones to make claws."}]}


def _no_gemini(*a, **k):
    raise RuntimeError("offline")


class ConsistencyTest(unittest.TestCase):
    def test_wrong_subject_is_rejected_without_gemini(self):
        with mock.patch.object(shorts.gemini, "call", _no_gemini):
            ok, reason = shorts.check_consistency(WRONG, "Why Does This Animal Break Its Own Bones?", "hairy frog claws")
        assert not ok and "concept" in reason

    def test_unverifiable_script_stops_instead_of_passing(self):
        with mock.patch.object(shorts.gemini, "call", _no_gemini):
            with self.assertRaises(RuntimeError):
                shorts.check_consistency(RIGHT, "Why Does This Animal Break Its Own Bones?", "hairy frog claws")

    def test_matching_script_passes(self):
        reply = '{"script_matches_topic": true, "title_matches_script": true, "reason": ""}'
        with mock.patch.object(shorts.gemini, "call", return_value=(reply, "m")):
            ok, _ = shorts.check_consistency(RIGHT, "Why Does This Animal Break Its Own Bones?", "hairy frog claws")
        assert ok

    def test_gemini_title_mismatch_is_rejected(self):
        reply = '{"script_matches_topic": true, "title_matches_script": false, "reason": "title is about laws"}'
        with mock.patch.object(shorts.gemini, "call", return_value=(reply, "m")):
            ok, reason = shorts.check_consistency(RIGHT, "frog", "hairy frog claws")
        assert not ok and "laws" in reason

    def test_unsupported_claim_is_rejected(self):
        reply = ('{"script_matches_topic": true, "title_matches_script": true, "claims_supported": false, '
                 '"reason": "\'40% of your strength\' is not in the notes"}')
        with mock.patch.object(shorts.gemini, "call", return_value=(reply, "m")) as call:
            ok, reason = shorts.check_consistency(RIGHT, "frog", "hairy frog claws",
                                                  facts="[Hairy frog] (u)\nThe hairy frog breaks its toe bones.")
        assert not ok and "40%" in reason
        assert "Research notes" in call.call_args[0][0]

    def test_wikipedia_drops_articles_without_the_concept(self):
        notes = ["[Animal cruelty] (u)\nLaws about cruelty to animals.", "[Hairy frog] (u)\nThe hairy frog has claws."]
        with mock.patch.object(shorts.gemini, "call", _no_gemini), \
                mock.patch.object(shorts, "_wiki_search", return_value=notes):
            out = shorts.wikipedia_notes("Why does this animal break its bones?", concept="hairy frog claws")
        assert "Hairy frog" in out and "Animal cruelty" not in out


PASS = '{"script_matches_topic": true, "title_matches_script": true, "claims_supported": true, "reason": ""}'

# 11/14 (U9gyYhy5EbY): the cited intros only say "huge volumes of water"
LAUNCH_NOTES = ("[Sound suppression system] (u)\nLaunch pads release huge volumes of water to absorb acoustic energy "
                "during liftoff. It was first used on the Space Shuttle in 1981.\n\n[Mobile launcher platform] (u)\n"
                "A mobile launcher platform carries the rocket to the pad.")
LAUNCH = {"youtube_title": "Why Launch Pads Dump Millions of Gallons of Water #shorts", "hook_text": "WATER WALL",
          "youtube_description": "The sound suppression system protects the rocket.",
          "scenes": [{"narration": "Launch pads dump millions of gallons of water in seconds."},
                     {"narration": "The sound suppression system soaks up the roar."}]}
# 11/15 (run 43631361432): neither figure is in the notes
HOLE_TOPIC = "Why Can a 2-Inch Hole Underwater Instantly Pin You with Over 1,000 Pounds of Force?"
HOLE_NOTES = ("[Differential pressure] (u)\nA pressure difference across an opening produces a force that grows "
              "with depth and with the area of the opening. Divers call this hazard delta P.")
# 11/16 (EAtc4v8T7No): the notes say "approximately 100,000"
LANIAKEA_NOTES = ("[Laniakea Supercluster] (u)\nThe Laniakea Supercluster contains approximately 100,000 galaxies "
                  "and spans about 520 million light-years. It was defined in 2014.")


def _galaxies(n: str) -> dict:
    return {"youtube_title": "The Invisible Force Pulling Our Galaxy #shorts", "hook_text": "WE ARE MOVING",
            "youtube_description": "The Laniakea Supercluster and the Great Attractor.",
            "scenes": [{"narration": f"Our galaxy is one of {n} galaxies in the Laniakea Supercluster."}]}


class FigureCheckTest(unittest.TestCase):
    def test_millions_of_gallons_rejected_even_if_gemini_passes(self):
        with mock.patch.object(shorts.gemini, "call", return_value=(PASS, "lite")):
            ok, reason = shorts.check_consistency(LAUNCH, "Why Do Rocket Launch Pads Dump Water?",
                                                  "sound suppression system", LAUNCH_NOTES)
        assert not ok and "Millions of Gallons" in reason

    def test_hundreds_of_thousands_needs_more_than_100000(self):
        with mock.patch.object(shorts.gemini, "call", return_value=(PASS, "lite")):
            ok, reason = shorts.check_consistency(_galaxies("hundreds of thousands of"), "galaxy",
                                                  "laniakea supercluster", LANIAKEA_NOTES)
            assert not ok and "hundreds of thousands" in reason and "100,000" in reason
            ok, _ = shorts.check_consistency(_galaxies("about 100,000"), "galaxy", "laniakea supercluster",
                                             LANIAKEA_NOTES)
            assert ok

    def test_topic_figures_rejected_in_script(self):
        sb = {"youtube_title": "A 2-Inch Hole Can Pin You #shorts", "hook_text": "DELTA P",
              "youtube_description": "Differential pressure explained.",
              "scenes": [{"narration": "A tiny hole can hold you with over 1,000 pounds of differential pressure."}]}
        with mock.patch.object(shorts.gemini, "call", return_value=(PASS, "lite")):
            ok, reason = shorts.check_consistency(sb, HOLE_TOPIC, "differential pressure", HOLE_NOTES)
        assert not ok and "2-Inch" in reason and "1,000 pounds" in reason

    def test_topic_check_judges_concept_not_topic_numbers(self):
        sb = {"youtube_title": "Why a Tiny Hole Underwater Can Pin You #shorts", "hook_text": "DELTA P",
              "youtube_description": "Differential pressure explained.",
              "scenes": [{"narration": "Differential pressure grows with depth and the size of the opening."}]}
        with mock.patch.object(shorts.gemini, "call", return_value=(PASS, "lite")) as call:
            ok, _ = shorts.check_consistency(sb, HOLE_TOPIC, "differential pressure", HOLE_NOTES)
        assert ok and "may leave out or correct numbers" in call.call_args[0][0]

    def test_ground_topic_removes_unverified_figures(self):
        clean = "Why Can a Small Hole Underwater Pin a Diver in Place?"
        with mock.patch.object(shorts.gemini, "call", return_value=(clean, "m")) as call:
            assert shorts.ground_topic(HOLE_TOPIC, "differential pressure", HOLE_NOTES) == clean
        assert "2-Inch" in call.call_args[0][0]
        galaxy = "Why Is an Invisible Force Dragging Our Galaxy at 1.3 Million Miles Per Hour?"
        with mock.patch.object(shorts.gemini, "call", return_value=("Why Is an Invisible Force Dragging Our "
                                                                    "Galaxy?", "m")):
            assert "1.3" not in shorts.ground_topic(galaxy, "great attractor", LANIAKEA_NOTES)

    def test_ground_topic_keeps_supported_topic_and_bad_rewrites(self):
        with mock.patch.object(shorts.gemini, "call", _no_gemini):
            assert shorts.ground_topic("Why Do 100,000 Galaxies Move Together?", "laniakea", LANIAKEA_NOTES) \
                == "Why Do 100,000 Galaxies Move Together?"
            assert shorts.ground_topic(HOLE_TOPIC, "differential pressure", HOLE_NOTES) == HOLE_TOPIC
        with mock.patch.object(shorts.gemini, "call", return_value=("Why Can a 3-Inch Hole Pin You?", "m")):
            assert shorts.ground_topic(HOLE_TOPIC, "differential pressure", HOLE_NOTES) == HOLE_TOPIC

    def test_small_counts_years_and_supported_figures_pass(self):
        notes = "Octopuses have 3 hearts. Discovered in 1998, it can reach 40 kilometres per hour."
        assert shorts.unsupported_figures("5 animals with 3 hearts, found in 1998, hitting 40 km/h", notes) == []
        assert shorts.unsupported_figures("found in 1997", notes) == ["1997"]
        assert shorts.unsupported_figures("it lasts 10 seconds", notes) == ["10 seconds"]

    def test_wikipedia_fallback_searches_content_words(self):
        with mock.patch.object(shorts.gemini, "call", _no_gemini), \
                mock.patch.object(shorts, "_wiki_search", return_value=["[Launch pad] (u)\nwater"]) as ws:
            shorts.wikipedia_notes("Why Do Rocket Launch Pads Dump Water in Seconds?")
        assert ws.call_args[0][0] == "rocket OR launch OR pads OR dump OR water"
