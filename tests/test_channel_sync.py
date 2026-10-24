import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from storyvideo import channel_sync as cs


class MergeTest(unittest.TestCase):
    def test_history_keeps_both_sides(self):
        base = [{"date": "2026-10-23", "video_id": "A", "views": 10}]
        ours = [{"date": "2026-10-23", "video_id": "A", "views": 50},
                {"date": "2026-10-24", "video_id": "B", "views": 0}]
        theirs = [{"date": "2026-10-23", "video_id": "A", "views": 10, "fb_id": "F1"}]
        out = cs.merge_history(base, ours, theirs)
        self.assertEqual([h["video_id"] for h in out], ["A", "B"])
        self.assertEqual(out[0]["views"], 50)        # this run's update wins
        self.assertEqual(out[0]["fb_id"], "F1")      # the other writer's field is kept

    def test_history_other_side_change_not_overwritten_by_stale_value(self):
        base = [{"date": "d", "video_id": "A", "privacy": "private"}]
        ours = [{"date": "d", "video_id": "A", "privacy": "private"}]          # we did not touch it
        theirs = [{"date": "d", "video_id": "A", "privacy": "public"}]
        self.assertEqual(cs.merge_history(base, ours, theirs)[0]["privacy"], "public")

    def test_history_entry_removed_by_this_run_stays_removed(self):
        base = [{"date": "d1", "video_id": "A"}, {"date": "d2", "video_id": "B"}]
        ours = [{"date": "d1", "video_id": "A"}]
        theirs = [{"date": "d1", "video_id": "A"}, {"date": "d2", "video_id": "B", "views": 9}]
        self.assertEqual([h["video_id"] for h in cs.merge_history(base, ours, theirs)], ["A"])

    def test_queue_consumed_removed_new_from_console_kept(self):
        base = ["t1", "t2"]
        ours = ["t2"]                 # this run used t1
        theirs = ["t1", "t2", "t3"]   # the console added t3 meanwhile
        self.assertEqual(cs.merge_queue(base, ours, theirs), ["t2", "t3"])

    def test_attempts_max_and_trends_newest(self):
        self.assertEqual(cs.merge_attempts({"d": 2}, {"d": 1, "e": 3}), {"d": 2, "e": 3})
        self.assertEqual(cs.merge_trends({"fetched": "2026-10-24"}, {"fetched": "2026-10-21"})["fetched"], "2026-10-24")


class PushTest(unittest.TestCase):
    """End to end with a local bare 'origin': a concurrent push to the same file no longer loses our record."""

    def sh(self, *a, cwd):
        subprocess.run(a, cwd=cwd, check=True, capture_output=True)

    def test_concurrent_push_is_merged(self):
        tmp = Path(tempfile.mkdtemp())
        origin, a, b = tmp / "origin.git", tmp / "a", tmp / "b"
        self.sh("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp)
        self.sh("git", "clone", "-q", str(origin), str(a), cwd=tmp)
        for d in (a,):
            self.sh("git", "config", "user.email", "t@t", cwd=d)
            self.sh("git", "config", "user.name", "t", cwd=d)
        (a / "channel").mkdir()
        (a / "channel" / "history.json").write_text(json.dumps([{"date": "d1", "video_id": "A"}]))
        self.sh("git", "add", ".", cwd=a)
        self.sh("git", "commit", "-q", "-m", "init", cwd=a)
        self.sh("git", "push", "-q", "origin", "HEAD:main", cwd=a)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=a, capture_output=True, text=True).stdout.strip()
        # someone else records fb_id meanwhile
        self.sh("git", "clone", "-q", str(origin), str(b), cwd=tmp)
        self.sh("git", "config", "user.email", "t@t", cwd=b)
        self.sh("git", "config", "user.name", "t", cwd=b)
        (b / "channel" / "history.json").write_text(json.dumps([{"date": "d1", "video_id": "A", "fb_id": "F"}]))
        self.sh("git", "commit", "-qam", "fb", cwd=b)
        self.sh("git", "push", "-q", "origin", "HEAD:main", cwd=b)
        # this run adds today's Short on the stale checkout
        (a / "channel" / "history.json").write_text(json.dumps([{"date": "d1", "video_id": "A"},
                                                                {"date": "d2", "video_id": "B"}]))
        cwd = os.getcwd()
        try:
            os.chdir(a)
            self.assertEqual(cs.main(["--base", base, "--message", "update"]), 0)
        finally:
            os.chdir(cwd)
        final = json.loads(subprocess.run(["git", f"--git-dir={origin}", "show", "main:channel/history.json"],
                                          capture_output=True, text=True).stdout)
        self.assertEqual([h["video_id"] for h in final], ["A", "B"])
        self.assertEqual(final[0].get("fb_id"), "F")


if __name__ == "__main__":
    unittest.main()
