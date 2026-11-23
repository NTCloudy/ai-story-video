import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from storyvideo import tts


class NoAudio(Exception):
    """Stands in for edge_tts.exceptions.NoAudioReceived."""


def fake_tts(fail_first: int):
    """An async stand-in for tts._tts: every scene fails `fail_first` times, then returns cues and words."""
    calls = {"n": 0, "per_text": {}}

    async def fake(text, voice, rate, mp3, lang="zh"):
        calls["n"] += 1
        seen = calls["per_text"].get(text, 0)
        calls["per_text"][text] = seen + 1
        if seen < fail_first:
            raise NoAudio("No audio was received.")
        Path(mp3).write_bytes(b"audio")
        return [(0.0, 1.0, text.upper())], [(0.0, 1.0, text)]

    return fake, calls


class VoiceRetryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        tts._EDGE_OK = True

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        tts._EDGE_OK = True

    def test_three_failures_in_a_row_no_longer_drop_the_short(self):
        fake, calls = fake_tts(fail_first=3)
        with mock.patch.object(tts, "_tts", fake), mock.patch("time.sleep") as sleep, \
                mock.patch("builtins.print"):
            out = tts.narrate([{"narration": "one"}, {"narration": "two"}], self.tmp, "en_male", "+8%", lang="en",
                              allow_backup=False)
        self.assertEqual([r["words"][0][2] for r in out], ["one", "two"])
        self.assertEqual(calls["n"], 8)  # 3 failures + 1 success per scene
        # it waits before every further try, longer each time
        self.assertEqual([c.args[0] for c in sleep.call_args_list], list(tts.RETRY_WAITS[:3]) * 2)
        self.assertEqual(sorted(tts.RETRY_WAITS), list(tts.RETRY_WAITS))

    def test_gives_up_after_the_last_try_without_backup_voice(self):
        fake, calls = fake_tts(fail_first=99)
        with mock.patch.object(tts, "_tts", fake), mock.patch("time.sleep") as sleep, \
                mock.patch.object(tts, "_gtts") as backup, mock.patch("builtins.print"):
            with self.assertRaises(RuntimeError):
                tts.narrate([{"narration": "one"}], self.tmp, "en_male", "+8%", lang="en", allow_backup=False)
        self.assertEqual(calls["n"], len(tts.RETRY_WAITS) + 1)
        self.assertEqual(sleep.call_count, len(tts.RETRY_WAITS))  # no wait after the last try
        backup.assert_not_called()

    def test_backup_voice_is_still_used_when_allowed(self):
        fake, calls = fake_tts(fail_first=99)
        with mock.patch.object(tts, "_tts", fake), mock.patch("time.sleep"), \
                mock.patch.object(tts, "_gtts", return_value=([(0.0, 1.0, "x")], [])) as backup, \
                mock.patch("builtins.print"):
            out = tts.narrate([{"narration": "one"}, {"narration": "two"}], self.tmp, "female", "+0%", lang="zh")
        self.assertEqual(len(out), 2)
        self.assertEqual(backup.call_count, 2)
        # the second scene goes straight to the backup voice, as before
        self.assertEqual(calls["n"], len(tts.RETRY_WAITS) + 1)

    def test_no_wait_when_the_first_try_works(self):
        fake, calls = fake_tts(fail_first=0)
        with mock.patch.object(tts, "_tts", fake), mock.patch("time.sleep") as sleep, \
                mock.patch("builtins.print"):
            tts.narrate([{"narration": "one"}], self.tmp, "en_male", "+8%", lang="en", allow_backup=False)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
