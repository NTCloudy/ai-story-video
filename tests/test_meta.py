import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from storyvideo import meta

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


class TakedownTest(unittest.TestCase):
    def test_instagram_left_online_is_recorded_with_its_link(self):
        tmp = Path(tempfile.mkdtemp())
        hist = tmp / "history.json"
        hist.write_text(json.dumps([{"video_id": "8KSB1V6cEQU", "date": "2026-11-18", "title": "Cashews",
                                     "fb_id": "111", "ig_id": "222"}]))
        manual = tmp / "out" / "MANUAL_DELETE"

        def fake_delete(url, **k):
            r = mock.Mock(status_code=400 if url.endswith("/222") else 200)
            r.json.return_value = ({"error": {"message": "(#10) Insufficient permissions"}} if url.endswith("/222")
                                   else {"success": True})
            return r

        perm = mock.Mock()
        perm.json.return_value = {"permalink": "https://www.instagram.com/reel/Df3L0lglRC-/"}
        with mock.patch.object(meta, "HISTORY", hist), mock.patch.object(meta, "MANUAL_DELETE", manual), \
                mock.patch.dict(os.environ, {"META_PAGE_TOKEN": "t"}), \
                mock.patch("storyvideo.youtube.delete_video"), \
                mock.patch.object(meta.requests, "delete", side_effect=fake_delete), \
                mock.patch.object(meta.requests, "get", return_value=perm):
            self.assertEqual(meta.takedown("8KSB1V6cEQU"), 0)
        self.assertEqual(json.loads(hist.read_text()), [])
        text = manual.read_text()
        self.assertIn("Instagram: https://www.instagram.com/reel/Df3L0lglRC-/", text)
        self.assertNotIn("Facebook", text)

    def test_clean_takedown_writes_no_manual_file(self):
        tmp = Path(tempfile.mkdtemp())
        hist = tmp / "history.json"
        hist.write_text(json.dumps([{"video_id": "v1", "title": "T"}]))
        manual = tmp / "out" / "MANUAL_DELETE"
        with mock.patch.object(meta, "HISTORY", hist), mock.patch.object(meta, "MANUAL_DELETE", manual), \
                mock.patch("storyvideo.youtube.delete_video"):
            self.assertEqual(meta.takedown("v1"), 0)
        self.assertFalse(manual.exists())
