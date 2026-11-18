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


class FigureParserTest(unittest.TestCase):
    """Follow-up 11/17: spelled-out compound numbers and vague magnitudes with modifiers / unit abbreviations."""

    def test_spelled_out_compound_numbers(self):
        for said, notes in (("two hundred fifty million light-years", "150–250 million light-years"),
                            ("one point two billion years", "1.248 billion years"),
                            ("five hundred million years", "at least 500 million years"),
                            ("sixty-six million years ago", "about 66 million years ago"),
                            ("three hundred thousand kilometers per second", "roughly 300,000 kilometres per second"),
                            ("sixty million stars", "60 million stars"),
                            ("fifteen thousand feet", "15,000 ft"),
                            ("half a million people", "500,000 people"),
                            ("forty percent", "40%")):
            self.assertEqual(shorts.unsupported_figures(said, notes), [], said)
        # a different fact no longer passes by accident
        self.assertEqual(shorts.unsupported_figures("three hundred million years", "100 million years ago"),
                         ["three hundred million"])
        self.assertEqual(shorts.unsupported_figures("fifty meters", "30 m"), ["fifty meters"])

    def test_vague_magnitude_matches_the_thing_counted(self):
        for said, notes in (("thousands of potassium nuclei", "about 4,300 nuclei of 40K decay per second"),
                            ("thousands of feet", "up to 60,000 ft (18,288 m) ... 6,000 ft"),
                            ("thousands of tiny zooids", "a colony of about 5,000 zooids")):
            self.assertEqual(shorts.unsupported_figures(said, notes), [], said)
        self.assertEqual(shorts.unsupported_figures("millions of gallons", "spans 520 million light-years"),
                         ["millions of gallons"])

    def test_what_if_premise_is_not_a_claim(self):
        topic = "What If You Pitched a Baseball at 90% Light Speed?"
        sb = {"youtube_title": "A Baseball at 90% Light Speed #shorts", "hook_text": "90% LIGHT SPEED",
              "youtube_description": "What a near-light-speed pitch would do.",
              "scenes": [{"narration": "A baseball thrown at 90% of light speed would fuse with the air."}]}
        notes = "[Baseball] (u)\nA baseball is a ball used in the sport of the same name."
        with mock.patch.object(shorts.gemini, "call", return_value=(PASS, "lite")):
            ok, _ = shorts.check_consistency(sb, topic, "baseball", notes)
        assert ok
        with mock.patch.object(shorts.gemini, "call", _no_gemini):
            assert shorts.ground_topic(topic, "baseball", notes) == topic
        # outside a what-if the same figure still needs the notes
        assert shorts.unsupported_figures("90% light speed", notes, premise="Why Do Baseballs Curve?") == ["90%"]
        real = "What Would Actually Happen If a Pitcher Threw a Baseball at 90% the Speed of Light?"  # 11/11
        assert shorts.unsupported_figures("ninety percent of light speed", notes, premise=real) == []


class GraphicPictureTest(unittest.TestCase):
    def test_skin_lesion_picture_prompt_is_rewritten(self):
        sb = {"youtube_title": "Why Cashews Are Never Sold in Shells #shorts", "hook_text": "TOXIC SHELL",
              "youtube_description": "Cashew shells contain urushiol.",
              "scenes": [{"narration": "Cashew shells contain urushiol, the same oil as poison ivy.",
                          "image_prompt": "cashew apples hanging on a tree",
                          "image_prompt_2": "Clinical close-up shot showing raised, reddened skin irritation and "
                                            "dermatitis welts on a forearm against a neutral background."}]}
        with mock.patch.object(shorts.gemini, "call", return_value=(PASS, "lite")):
            ok, reason = shorts.check_consistency(sb, "Why are cashews never sold in shells?", "cashew shells",
                                                  "[Cashew] (u)\nCashew shells contain urushiol.")
        assert not ok and "scene 1 image_prompt_2" in reason and "cause instead" in reason

    def test_harmless_prompts_pass(self):
        sb = {"scenes": [{"image_prompt": "red blood cells flowing through a vessel, microscope view",
                          "image_prompt_2": "a rocket engine burn seen from far away"}]}
        assert shorts.graphic_prompts(sb) == []
