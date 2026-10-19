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

    def test_still_weird_extra_shot_is_dropped_required_is_kept(self):
        self.assertEqual(self._run([(False, "x"), (False, "x")], optional=True)[0], False)
        self.img.write_bytes(b"first")
        self.assertEqual(self._run([(False, "x"), (False, "x")], optional=False)[0], True)

    def test_redraw_error_keeps_required_and_drops_extra(self):
        self.assertTrue(self._run([(False, "x")], optional=False, redraw_error=RuntimeError("quota"))[0])
        self.assertFalse(self._run([(False, "x")], optional=True, redraw_error=RuntimeError("quota"))[0])
        self.assertEqual(self.img.read_bytes(), b"first")


if __name__ == "__main__":
    unittest.main()
