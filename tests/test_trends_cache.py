import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from storyvideo import daily

OLD = [{"theme": "Animals", "count": 5, "median_views": 5_000_000, "examples": []}]


class TrendsCacheTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        stale = (datetime.now(daily.TZ) - timedelta(days=4)).isoformat()
        (self.dir / "trends.json").write_text(json.dumps(
            {"fetched": stale, "queries": daily.TREND_QUERIES, "items": [{"title": "old", "views": 1}], "themes": OLD}))

    def run_load(self, label):
        with mock.patch.object(daily, "CH", self.dir), \
                mock.patch.object(daily.youtube, "configured", return_value=True), \
                mock.patch.object(daily.youtube, "trending_shorts", return_value=[{"title": "new", "views": 9}]), \
                mock.patch.object(daily.shorts, "label_themes", side_effect=label):
            return daily.load_trends({})

    def test_labelling_failure_keeps_previous_themes_and_new_items(self):
        items, themes = self.run_load(RuntimeError("HTTP 503"))
        self.assertEqual(themes, OLD)
        saved = json.loads((self.dir / "trends.json").read_text())
        self.assertEqual(saved["items"][0]["title"], "new")      # search result not thrown away
        self.assertTrue(saved["themes_pending"])

    def test_next_run_relabels(self):
        self.run_load(RuntimeError("HTTP 503"))
        new = [{"theme": "Space", "count": 3, "median_views": 1, "examples": []}]
        with mock.patch.object(daily, "CH", self.dir), \
                mock.patch.object(daily.youtube, "configured", return_value=True), \
                mock.patch.object(daily.youtube, "trending_shorts") as search, \
                mock.patch.object(daily.shorts, "label_themes", return_value=new):
            items, themes = daily.load_trends({})
            search.assert_not_called()                           # still fresh: no extra YouTube quota
        self.assertEqual(themes, new)
        self.assertNotIn("themes_pending", json.loads((self.dir / "trends.json").read_text()))


if __name__ == "__main__":
    unittest.main()
