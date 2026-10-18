import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from storyvideo import render


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class ThumbnailFitTest(unittest.TestCase):
    """The cover title must never run off the frame (it did for long hooks before the fix)."""

    def setUp(self):
        render.configure("short")
        self.tmp = Path(tempfile.mkdtemp())
        self.img = self.tmp / "scene.png"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=0x203060:s=1080x1920:d=1",
                        "-frames:v", "1", str(self.img)], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        render.configure("landscape")

    def _fits(self, title: str) -> int:
        out = self.tmp / "thumbnail.jpg"
        size = render.thumbnail(self.img, title, out)
        self.assertTrue(out.exists())
        ass = self.tmp / "check.ass"
        ass.write_text(render._thumb_ass(title, 720, 1280, size), encoding="utf-8")
        self.assertFalse(render.text_touches_edges(ass, 720, 1280), f"{title!r} still touches the edges at {size}px")
        return size

    def test_normal_hook_keeps_default_size(self):
        self.assertEqual(self._fits("What does space smell like?"), int(720 * 0.12))

    def test_long_single_word_is_shrunk(self):
        self.assertLess(self._fits("Supercalifragilisticexpialidocious"), int(720 * 0.12))


if __name__ == "__main__":
    unittest.main()
