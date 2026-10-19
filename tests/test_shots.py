import unittest

from storyvideo import render


class ShotCutTest(unittest.TestCase):
    def setUp(self):
        render.configure("short")

    def tearDown(self):
        render.configure("landscape")

    def test_two_shots_cut_on_a_word_near_the_middle(self):
        words = [(0.0, 0.3, "Your"), (0.4, 0.8, "brain"), (1.5, 1.9, "lies"), (3.3, 3.6, "every"), (4.6, 5.0, "day")]
        cuts = render.shot_cuts(2, 7.0, words)
        self.assertEqual(cuts[0], 0.0)
        self.assertEqual(cuts[-1], 7.0)
        self.assertAlmostEqual(cuts[1], render.LEAD + 3.3)   # the word start closest to 3.5 s

    def test_short_scene_keeps_one_shot(self):
        self.assertEqual(render.shot_cuts(2, 2.0, []), [0.0, 2.0])

    def test_without_words_splits_evenly_and_respects_min_length(self):
        cuts = render.shot_cuts(3, 6.0, [])
        self.assertEqual(len(cuts), 4)
        for a, b in zip(cuts, cuts[1:]):
            self.assertGreaterEqual(b - a, render.MIN_SHOT - 1e-9)


class HighlightTest(unittest.TestCase):
    def setUp(self):
        render.configure("short")

    def tearDown(self):
        render.configure("landscape")

    def test_one_event_per_word_contiguous(self):
        slots = render.word_slots([(10.0, [(0.0, 0.3, "Space"), (0.35, 0.7, "smells,"), (0.8, 1.1, "weird")])])
        self.assertEqual([s[2] for s in slots], ["SPACE", "SMELLS", "WEIRD"])
        self.assertAlmostEqual(slots[0][0], 10.0 + render.LEAD)
        a, b = slots[0][0], slots[1][1]
        events, nxt = render.highlight_events(a, b, "SPACE SMELLS", slots, 0)
        self.assertEqual(nxt, 2)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0][0], round(a, 2))
        self.assertEqual(events[0][1], events[1][0])          # no gap, no overlap
        self.assertEqual(events[1][1], round(b, 2))
        self.assertTrue(events[0][2].startswith(render.HIGHLIGHT + "SPACE"))
        self.assertIn(render.HIGHLIGHT + "SMELLS", events[1][2])
        self.assertNotIn(render.HIGHLIGHT + "SPACE", events[1][2])

    def test_mismatch_falls_back_to_plain_caption(self):
        slots = render.word_slots([(0.0, [(0.0, 0.3, "alpha"), (0.4, 0.7, "beta")])])
        events, nxt = render.highlight_events(0.0, 1.0, "GAMMA DELTA", slots, 0)
        self.assertEqual(events, [])
        self.assertEqual(nxt, 0)


if __name__ == "__main__":
    unittest.main()
