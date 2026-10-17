import unittest

from storyvideo.shorts import lexical_duplicate

HISTORY = [
    {"topic": "What If Earth Stopped Spinning for Just 1 Second?", "concept": "earth stops spinning"},
    {"topic": "Why Does Your Brain Make You Feel Phantom Phone Vibrations?", "concept": "phantom phone vibration"},
    {"topic": "Why do you feel like you're falling when you fall asleep?", "concept": "hypnic jerk"},
]


class TopicDedupTest(unittest.TestCase):
    def test_reworded_duplicates_caught(self):
        self.assertTrue(lexical_duplicate("What would happen if the Earth stopped spinning?", "earth stop spinning", HISTORY))
        self.assertTrue(lexical_duplicate("Phantom phone vibrations: why your brain fakes them", "", HISTORY))
        self.assertTrue(lexical_duplicate("What is a hypnic jerk?", "hypnic jerk", HISTORY))

    def test_new_topics_pass(self):
        self.assertFalse(lexical_duplicate("What if the Moon disappeared tonight?", "moon disappears", HISTORY))
        self.assertFalse(lexical_duplicate("How do octopuses taste with their arms?", "octopus arm taste", HISTORY))
        self.assertFalse(lexical_duplicate("What if Earth had rings like Saturn?", "earth rings", HISTORY))


if __name__ == "__main__":
    unittest.main()
