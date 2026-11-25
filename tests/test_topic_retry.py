import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from storyvideo import daily, shorts

A = {"topic": "Why Does Melting Junk Food Trick Your Brain?", "series": "Health & Food Science",
     "concept": "vanishing caloric density", "mode": "trend"}
B = {"topic": "Why Do Octopuses Have Three Hearts?", "series": "Ocean Life", "concept": "octopus hearts",
     "mode": "trend"}
NOTES = "[Octopus] (u)\nAn octopus has three hearts."
NO_FACTS = "查不到這個主題的可靠資料"
REJECTED = "重寫 3 次"


def _script(topic, facts, series, concept, feedback):
    return {"youtube_title": f"{topic} #shorts", "title": "t", "model": "m", "topic": topic,
            "scenes": [{"narration": "n", "image_prompt": "p", "image_prompt_2": ""}]}


class TopicRetryTest(unittest.TestCase):
    """11/23 and 11/25: a topic that could not be researched, or whose drafts kept failing the check, used up one
    of the day's three automatic tries. Now the same run moves on to another topic."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        Path("out").mkdir()

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def _make(self, research, checks, picks=(A, B), cfg=None, topic="", queue=None):
        """Runs make_short up to the pictures (the first step after the script) with every service mocked.
        Returns (error text, mocks)."""
        args = argparse.Namespace(topic=topic, concept="", force=False, no_upload=True, dry_run=True)
        with mock.patch.object(daily, "load_trends", return_value=([], [])), \
                mock.patch.object(shorts, "find_duplicate", return_value=""), \
                mock.patch.object(shorts, "pick_topic", side_effect=[dict(p) for p in picks]) as pick, \
                mock.patch.object(shorts, "research", side_effect=research) as res, \
                mock.patch.object(shorts, "ground_topic", side_effect=lambda topic, concept, facts: topic), \
                mock.patch.object(shorts, "write_short", side_effect=_script), \
                mock.patch.object(shorts, "check_consistency", side_effect=checks) as check, \
                mock.patch.object(daily.images, "generate_images", side_effect=RuntimeError("stop here")), \
                contextlib.redirect_stdout(io.StringIO()) as log:
            with self.assertRaises(Exception) as err:
                daily.make_short(args, cfg or {}, [], queue if queue is not None else [], "2026-11-25",
                                 Path("out"), False)
        return str(err.exception), {"pick": pick, "research": res, "check": check, "log": log.getvalue(),
                                    "error": err.exception}

    def _script_topic(self):
        return json.loads(Path("out/script.json").read_text(encoding="utf-8"))["topic"]

    def test_topic_without_research_notes_is_replaced(self):
        error, m = self._make(research=lambda topic, concept: "" if topic == A["topic"] else NOTES,
                              checks=[(True, "")])
        self.assertIn("stop here", error)  # got past the script, with the second topic
        self.assertEqual(self._script_topic(), B["topic"])
        self.assertEqual(m["pick"].call_count, 2)
        self.assertEqual(m["pick"].call_args_list[1].kwargs["exclude"],
                         [{"topic": A["topic"], "concept": A["concept"], "series": A["series"]}])
        self.assertIn("換一個主題", m["log"])
        self.assertIn(NO_FACTS, m["log"])

    def test_topic_whose_drafts_keep_failing_is_replaced(self):
        error, m = self._make(research=lambda topic, concept: NOTES,
                              checks=[(False, "not in the notes")] * 3 + [(True, "")])
        self.assertIn("stop here", error)
        self.assertEqual(self._script_topic(), B["topic"])
        self.assertEqual(m["check"].call_count, 4)
        self.assertEqual(len(m["pick"].call_args_list[1].kwargs["exclude"]), 1)

    def test_gives_up_after_the_last_topic(self):
        error, m = self._make(research=lambda topic, concept: "", checks=[])
        self.assertIsInstance(m["error"], daily.CannotGenerate)
        self.assertIn(NO_FACTS, error)
        self.assertEqual(m["pick"].call_count, 2)  # topics_per_attempt defaults to 2
        self.assertFalse(Path("out/script.json").exists())

    def test_number_of_topics_comes_from_the_settings(self):
        error, m = self._make(research=lambda topic, concept: "", checks=[], cfg={"topics_per_attempt": 1})
        self.assertIn(NO_FACTS, error)
        self.assertEqual(m["pick"].call_count, 1)
        C = dict(B, topic="Why Is the Sky Dark at Night?", concept="olbers paradox")
        error, m = self._make(research=lambda topic, concept: NOTES if "Sky" in topic else "", checks=[(True, "")],
                              picks=(A, B, C), cfg={"topics_per_attempt": 3})
        self.assertEqual(self._script_topic(), C["topic"])
        self.assertEqual(len(m["pick"].call_args_list[2].kwargs["exclude"]), 2)

    def test_given_topic_is_never_replaced(self):
        error, m = self._make(research=lambda topic, concept: "", checks=[], topic="Why is the sky blue?")
        self.assertIsInstance(m["error"], daily.CannotGenerate)
        m["pick"].assert_not_called()
        self.assertEqual(m["research"].call_count, 1)
        error, m = self._make(research=lambda topic, concept: "", checks=[],
                              queue=[{"topic": "Why do cats purr?", "series": "Pets"}])
        self.assertIsInstance(m["error"], daily.CannotGenerate)
        m["pick"].assert_not_called()
        self.assertEqual(m["research"].call_count, 1)

    def test_service_outage_does_not_burn_a_second_topic(self):
        error, m = self._make(research=lambda topic, concept: NOTES, checks=RuntimeError("Gemini 無法使用"))
        self.assertNotIsInstance(m["error"], daily.CannotGenerate)
        self.assertIn("Gemini", error)
        self.assertEqual(m["pick"].call_count, 1)


class PickTopicExcludeTest(unittest.TestCase):
    THEMES = [{"theme": "Health & Food Science", "count": 9, "median_views": 10_000_000, "examples": ["e"]},
              {"theme": "Ocean Life", "count": 2, "median_views": 10, "examples": ["e"]}]
    DROPPED = [{"topic": A["topic"], "concept": A["concept"], "series": A["series"]}]

    def _pick(self, proposals, themes=None, exclude=None):
        with mock.patch.object(shorts, "_propose_in_theme", side_effect=proposals) as propose, \
                mock.patch.object(shorts, "semantic_duplicate", return_value=""), \
                contextlib.redirect_stdout(io.StringIO()):
            return shorts.pick_topic([], themes=themes or self.THEMES, proven_per_week=0, exclude=exclude), propose

    def test_dropped_topic_is_not_picked_again(self):
        same_again = {"topic": "Why Does Melting Junk Food Fool Your Brain?", "concept": A["concept"], "series": "x"}
        t, propose = self._pick([same_again, dict(B)], exclude=self.DROPPED)
        self.assertEqual(t["topic"], B["topic"])
        self.assertEqual(propose.call_count, 2)
        self.assertIn(A["topic"], propose.call_args_list[0].args[2][0])  # the proposer is told about it

    def test_trend_pick_moves_to_another_theme(self):
        t, propose = self._pick([dict(B)], exclude=self.DROPPED)
        self.assertEqual(propose.call_args.args[1]["theme"], "Ocean Life")

    def test_all_themes_dropped_falls_back_to_all_of_them(self):
        t, propose = self._pick([dict(B)], themes=self.THEMES[:1], exclude=self.DROPPED)
        self.assertEqual(propose.call_args.args[1]["theme"], "Health & Food Science")

    def test_without_dropped_topics_nothing_changes(self):
        t, propose = self._pick([dict(B)], themes=self.THEMES[:1])
        self.assertEqual(propose.call_args.args[2], [])
        self.assertEqual(t["mode"], "trend")


if __name__ == "__main__":
    unittest.main()
