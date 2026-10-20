import json
import random
import unittest
from unittest import mock

from storyvideo import shorts

TRENDS = [{"title": f"Animal fact {i}", "views": 5_000_000 + i} for i in range(4)] + \
         [{"title": f"Space fact {i}", "views": 1_000_000 + i} for i in range(3)] + \
         [{"title": "Animal Fact Time! #kids", "views": 99_000_000},
          {"title": "Lonely food fact", "views": 50_000_000}]


class ThemeTest(unittest.TestCase):
    def test_label_themes_groups_ranks_and_skips_kids_and_singletons(self):
        def fake_call(prompt, schema, **kw):
            self.assertNotIn("#kids", prompt)
            rows = [{"i": i, "theme": "Animals"} for i in range(4)] + [{"i": i, "theme": "Space"} for i in range(4, 7)]
            rows.append({"i": 7, "theme": "Food Facts"})
            return json.dumps(rows), "m"
        with mock.patch.object(shorts.gemini, "call", side_effect=fake_call):
            themes = shorts.label_themes(TRENDS)
        self.assertEqual([t["theme"] for t in themes], ["Animals", "Space"])   # food: only 1 example
        self.assertEqual(themes[0]["count"], 4)
        self.assertGreater(themes[0]["median_views"], themes[1]["median_views"])

    def test_pick_theme_never_repeats_recent_themes(self):
        themes = [{"theme": "Animals", "count": 5, "median_views": 5_000_000, "examples": []},
                  {"theme": "Space", "count": 5, "median_views": 1_600_000, "examples": []},
                  {"theme": "History", "count": 3, "median_views": 1_300_000, "examples": []}]
        random.seed(1)
        history = [{"series": "Space"}, {"series": "Animals"}]
        for _ in range(20):
            self.assertEqual(shorts.pick_theme(themes, history, cooldown=7)["theme"], "History")
        self.assertIsNone(shorts.pick_theme(themes, [{"series": t["theme"]} for t in themes], cooldown=7))
        picked = {shorts.pick_theme(themes, [{"series": "Space"}], cooldown=1)["theme"] for _ in range(50)}
        self.assertEqual(picked, {"Animals", "History"})


if __name__ == "__main__":
    unittest.main()
