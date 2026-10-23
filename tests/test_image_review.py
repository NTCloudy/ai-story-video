import tempfile
import unittest
from pathlib import Path
from unittest import mock

from storyvideo import images


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.img = self.tmp / "scene_00.jpg"
        self.img.write_bytes(b"first")

    def _run(self, verdicts, optional=False, redraw=b"second", redraw_error=None):
        flux = mock.Mock(side_effect=redraw_error) if redraw_error else mock.Mock(return_value=redraw)
        with mock.patch.object(images, "check_image", side_effect=verdicts) as chk, \
                mock.patch.object(images, "flux2", flux):
            keep = images._review(self.img, 0, "a planet", "prompt", [], 768, 1344, optional)
        return keep, chk.call_count, flux.call_count

    def test_good_picture_is_kept_without_redraw(self):
        self.assertEqual(self._run([(True, "")]), (True, 1, 0))
        self.assertEqual(self.img.read_bytes(), b"first")

    def test_weird_picture_is_redrawn_once(self):
        self.assertEqual(self._run([(False, "face is a planet"), (True, "")]), (True, 2, 1))
        self.assertEqual(self.img.read_bytes(), b"second")

    def test_still_weird_extra_shot_is_dropped_required_stops(self):
        self.assertEqual(self._run([(False, "x"), (False, "x")], optional=True)[0], False)
        self.img.write_bytes(b"first")
        with self.assertRaises(RuntimeError):
            self._run([(False, "x"), (False, "x")], optional=False)

    def test_redraw_error_drops_extra_required_stops(self):
        with self.assertRaises(RuntimeError):
            self._run([(False, "x")], optional=False, redraw_error=RuntimeError("quota"))
        self.assertFalse(self._run([(False, "x")], optional=True, redraw_error=RuntimeError("quota"))[0])
        self.assertEqual(self.img.read_bytes(), b"first")

    def test_unverifiable_picture_drops_extra_required_stops(self):
        self.assertFalse(self._run([images.CheckUnavailable("busy")], optional=True)[0])
        with self.assertRaises(RuntimeError):
            self._run([images.CheckUnavailable("busy")], optional=False)

    def test_only_major_problems_block_a_picture(self):
        for sev, ok in (("none", True), ("minor", True), ("major", False)):
            reply = '{"severity": "%s", "problem": "dog is standing"}' % sev
            with mock.patch("storyvideo.gemini.call", return_value=(reply, "m")), \
                    mock.patch.object(images.time, "sleep"):
                self.assertEqual(images.check_image(self.img, "a sitting dog")[0], ok)


if __name__ == "__main__":
    unittest.main()
