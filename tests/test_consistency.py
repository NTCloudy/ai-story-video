import unittest
from unittest import mock

from storyvideo import shorts

WRONG = {"youtube_title": "Why Animal Cruelty Laws Differ Worldwide #shorts", "hook_text": "LAWS VARY GLOBALLY",
         "youtube_description": "How animal cruelty laws vary between countries.",
         "scenes": [{"narration": "Laws concerning animal cruelty differ completely across the world."}]}
RIGHT = {"youtube_title": "This Frog Breaks Its Own Bones to Fight #shorts", "hook_text": "WOLVERINE FROG",
         "youtube_description": "The hairy frog pushes its toe bones through its skin.",
         "scenes": [{"narration": "The hairy frog breaks its own toe bones to make claws."}]}


def _no_gemini(*a, **k):
    raise RuntimeError("offline")


class ConsistencyTest(unittest.TestCase):
    def test_wrong_subject_is_rejected_without_gemini(self):
        with mock.patch.object(shorts.gemini, "call", _no_gemini):
            ok, reason = shorts.check_consistency(WRONG, "Why Does This Animal Break Its Own Bones?", "hairy frog claws")
        assert not ok and "concept" in reason

    def test_matching_script_passes_keyword_check(self):
        with mock.patch.object(shorts.gemini, "call", _no_gemini):
            ok, _ = shorts.check_consistency(RIGHT, "Why Does This Animal Break Its Own Bones?", "hairy frog claws")
        assert ok

    def test_gemini_title_mismatch_is_rejected(self):
        reply = '{"script_matches_topic": true, "title_matches_script": false, "reason": "title is about laws"}'
        with mock.patch.object(shorts.gemini, "call", return_value=(reply, "m")):
            ok, reason = shorts.check_consistency(RIGHT, "frog", "hairy frog claws")
        assert not ok and "laws" in reason

    def test_wikipedia_drops_articles_without_the_concept(self):
        notes = ["[Animal cruelty] (u)\nLaws about cruelty to animals.", "[Hairy frog] (u)\nThe hairy frog has claws."]
        with mock.patch.object(shorts.gemini, "call", _no_gemini), \
                mock.patch.object(shorts, "_wiki_search", return_value=notes):
            out = shorts.wikipedia_notes("Why does this animal break its bones?", concept="hairy frog claws")
        assert "Hairy frog" in out and "Animal cruelty" not in out
