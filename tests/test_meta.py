import unittest

from storyvideo.meta import caption, clean_title


class CaptionTest(unittest.TestCase):
    META = {
        "title": "Why Outer Space Smells Like Burnt Steak #shorts",
        "series": "Space",
        "youtube_description": (
            "Astronauts report a bizarre odor after spacewalks. #space #science #shorts\n\n"
            "Sources:\n- https://en.wikipedia.org/wiki/Outer_space\n\n"
            "Visuals and voice are AI-generated."),
    }

    def test_clean_title(self):
        self.assertEqual(clean_title("What If Earth Stopped? #shorts"), "What If Earth Stopped?")
        self.assertEqual(clean_title("No tag here"), "No tag here")

    def test_caption_layout(self):
        c = caption(self.META)
        self.assertTrue(c.startswith("Why Outer Space Smells Like Burnt Steak 🚀\n\n"))
        self.assertIn("Astronauts report a bizarre odor after spacewalks.", c)
        self.assertIn("Sources:\n- https://en.wikipedia.org/wiki/Outer_space", c)
        self.assertIn("🤖 Visuals and voice are AI-generated.", c)
        self.assertEqual(c.count("AI-generated"), 1)
        self.assertNotIn("#shorts", c.lower())
        self.assertTrue(c.rstrip().endswith("#space #science #didyouknow #sciencefacts #funfacts"))

    def test_hashtags_deduplicated_and_capped(self):
        tags = " ".join(f"#tag{i}" for i in range(20)) + " #SCIENCEFACTS"
        c = caption({"title": "T", "youtube_description": f"Body. {tags}"})
        last = c.splitlines()[-1].split()
        self.assertLessEqual(len(last), 8)
        self.assertEqual(len({t.lower() for t in last}), len(last))

    def test_unknown_series_uses_cloud(self):
        self.assertTrue(caption({"title": "Hello", "series": "Mystery"}).startswith("Hello ☁️"))


if __name__ == "__main__":
    unittest.main()
