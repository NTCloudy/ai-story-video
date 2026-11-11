import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from storyvideo import daily


class GiveUpTest(unittest.TestCase):
    """A Short that cannot be made properly is not forced out: warning + GAVE_UP note, no video, retry later."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        Path("channel").mkdir()
        Path("channel/channel.yaml").write_text("max_attempts_per_day: 2\n")

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def _run(self):
        with mock.patch.object(daily, "make_short", side_effect=daily.CannotGenerate("no facts")), \
                mock.patch.object(daily.youtube, "configured", return_value=False), \
                mock.patch.dict(os.environ, {"GITHUB_EVENT_NAME": "workflow_dispatch"}):
            Path("out").mkdir(exist_ok=True)
            Path("out/video.mp4").write_bytes(b"half")
            return daily.main(["--out", "out"])

    def test_gives_up_with_note_then_stops_retrying(self):
        self.assertEqual(self._run(), 0)
        # first failure: no issue yet, just wait for the next try
        self.assertFalse(Path("out/GAVE_UP").exists())
        self.assertIn("no facts", Path("out/RETRY_LATER").read_text(encoding="utf-8"))
        self.assertFalse(Path("out/video.mp4").exists())
        self.assertEqual(list(json.loads(Path("channel/attempts.json").read_text()).values()), [1])
        self._run()  # last automatic try fails -> GAVE_UP (opens the issue)
        self.assertIn("no facts", Path("out/GAVE_UP").read_text(encoding="utf-8"))
        Path("out/GAVE_UP").unlink()
        self.assertEqual(self._run(), 0)  # third automatic try today is skipped
        self.assertEqual(Path("out/SKIPPED").read_text(), "gave up today")
        self.assertFalse(Path("out/GAVE_UP").exists())

    def test_manual_topic_failure_reports_right_away(self):
        with mock.patch.object(daily, "make_short", side_effect=daily.CannotGenerate("no facts")), \
                mock.patch.object(daily.youtube, "configured", return_value=False), \
                mock.patch.dict(os.environ, {"GITHUB_EVENT_NAME": "workflow_dispatch"}):
            Path("out").mkdir(exist_ok=True)
            daily.main(["--out", "out", "--topic", "Why is the sky blue?"])
        self.assertTrue(Path("out/GAVE_UP").exists())


if __name__ == "__main__":
    unittest.main()
