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


class ProvenThemeTest(unittest.TestCase):
    H = [{"date": "2026-10-16", "series": "What If", "views": 800, "title": "A"},
         {"date": "2026-10-18", "series": "Space", "views": 1400, "title": "B"},
         {"date": "2026-10-20", "series": "Space", "views": 2600, "title": "C"},
         {"date": "2026-10-21", "series": "Earth & Geology", "views": 90, "title": "D"},
         {"date": "2026-10-22", "series": "Animals", "views": 990, "title": "E"},
         {"date": "2026-10-27", "series": "Pets", "views": 4, "title": "F"}]   # too new to judge

    def test_ranking_groups_old_series_names_and_skips_new_shorts(self):
        best = shorts.proven_themes(self.H, "2026-10-28")
        self.assertEqual([t["theme"] for t in best], ["Space", "Animals", "Physics & What-Ifs"])
        self.assertEqual(best[0]["avg_views"], 2000)

    def test_need_proven_counts_last_six(self):
        h = [{"mode": "trend"}] * 6
        self.assertTrue(shorts.need_proven(h, 2))
        h = [{"mode": "proven"}, {"mode": "trend"}, {"mode": "proven"}] + [{"mode": "trend"}] * 3
        self.assertFalse(shorts.need_proven(h, 2))
        self.assertFalse(shorts.need_proven(h, 0))

    def test_every_week_has_two_proven(self):
        modes = []
        for _ in range(28):
            modes.append("proven" if shorts.need_proven([{"mode": m} for m in modes], 2) else "trend")
        for i in range(len(modes) - 6):
            self.assertGreaterEqual(modes[i:i + 7].count("proven"), 2, modes)

    def test_proven_theme_not_same_as_yesterday(self):
        random.seed(3)
        h = self.H[:-1] + [{"date": "2026-10-27", "series": "Space", "views": 5, "title": "G"}]
        for _ in range(20):
            self.assertNotEqual(shorts.pick_proven_theme(h, "2026-10-28")["theme"], "Space")


if __name__ == "__main__":
    unittest.main()
