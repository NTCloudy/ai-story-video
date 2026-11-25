import contextlib
import io
import unittest
from unittest import mock

from storyvideo import shorts

# 11/25 (run 45510971066): three drafts about orange juice after brushing were rejected because the notes, the
# intros only, did not have the explanation. The Toothpaste article has it in its body.
TOPIC = "Why Does Orange Juice Taste Terrible Right After You Brush Your Teeth?"
CONCEPT = "orange juice toothpaste"
TOOTHPASTE_INTRO = ("Toothpaste is a paste or gel dentifrice that is used with a toothbrush to clean and maintain "
                    "the aesthetics of teeth. Toothpaste is used to promote oral hygiene: it is an abrasive that "
                    "aids in removing dental plaque and food from the teeth.")
JUICE = ("After using toothpaste, orange juice and other fruit juices are known to have an unpleasant taste if "
         "consumed shortly afterwards. Sodium lauryl sulfate, used as a surfactant in toothpaste, alters taste "
         "perception. It can break down phospholipids that inhibit taste receptors for sweetness, giving food a "
         "bitter taste. In contrast, apples are known to taste more pleasant after using toothpaste. "
         "Distinguishing between the hypotheses that the bitter taste of orange juice results from stannous "
         "fluoride or from sodium lauryl sulfate is still an unresolved issue and it is thought that the menthol "
         "added for flavor may also take part in the alteration of taste perception when binding to lingual cold "
         "receptors.")
TOOTHPASTE_BODY = "\n".join([
    TOOTHPASTE_INTRO, "", "", "== History ==",
    "The Greeks, and then the Romans, improved the recipes for toothpaste by adding abrasives such as crushed "
    "bones and oyster shells.",
    "", "", "== Other issues ==", "=== Alteration of taste perception ===", JUICE,
    "", "", "== See also ==", "Mouthwash"])
BRUSHING_INTRO = "Tooth brushing is the act of scrubbing teeth with a toothbrush equipped with toothpaste."
BRUSHING_BODY = "\n".join([
    BRUSHING_INTRO, "", "", "== Timing ==",
    "One study found that brushing immediately after an acidic meal (such as diet soda or common breakfast foods "
    "like orange juice, coffee, citrus fruit, dried fruit, bread, or pastries) caused more damage to enamel."])
SEARCH = [f"[Toothpaste] (https://en.wikipedia.org/wiki/Toothpaste)\n{TOOTHPASTE_INTRO}",
          "[Sodium dodecyl sulfate] (https://en.wikipedia.org/wiki/Sodium_dodecyl_sulfate)\n"
          "Sodium dodecyl sulfate is an organic compound and an anionic surfactant used in many cleaning products.",
          f"[Tooth brushing] (https://en.wikipedia.org/wiki/Tooth_brushing)\n{BRUSHING_INTRO}"]
BODIES = {"Toothpaste": TOOTHPASTE_BODY, "Tooth brushing": BRUSHING_BODY}


def _no_gemini(*a, **k):
    raise RuntimeError("offline")


def _notes(search=SEARCH, bodies=BODIES, topic=TOPIC, concept=CONCEPT):
    with mock.patch.object(shorts.gemini, "call", _no_gemini), \
            mock.patch.object(shorts, "_wiki_search", return_value=list(search)), \
            mock.patch.object(shorts, "_wiki_body", side_effect=lambda title: bodies[title]) as body, \
            contextlib.redirect_stdout(io.StringIO()):
        return shorts.wikipedia_notes(topic, concept=concept), body


class ConceptParagraphsTest(unittest.TestCase):
    KEYS = shorts.concept_keywords(CONCEPT)

    def test_finds_the_paragraph_about_the_concept(self):
        found = shorts.concept_paragraphs(TOOTHPASTE_BODY, self.KEYS, skip=TOOTHPASTE_INTRO)
        self.assertEqual(found, [JUICE])  # not the intro, the headings, the short line or the History paragraph

    def test_best_match_first_then_article_order_and_limit(self):
        two = "Orange trees and toothpaste factories were both common in the region during the nineteenth century."
        also_two = "A glass of juice next to a tube of toothpaste is a familiar sight on many bathroom shelves today."
        body = "\n".join([two, also_two, JUICE])
        self.assertEqual(shorts.concept_paragraphs(body, self.KEYS, limit=2), [JUICE, two])
        self.assertEqual(shorts.concept_paragraphs(body, self.KEYS, limit=3), [JUICE, two, also_two])

    def test_one_keyword_is_not_enough_unless_the_concept_has_one(self):
        only_one = "Toothpaste was sold in jars until collapsible tubes were introduced near the end of the century."
        self.assertEqual(shorts.concept_paragraphs(only_one, self.KEYS), [])
        self.assertEqual(shorts.concept_paragraphs(only_one, shorts.concept_keywords("toothpaste")), [only_one])
        self.assertEqual(shorts.concept_paragraphs(only_one, set()), [])

    def test_long_paragraph_is_cut_to_whole_sentences_from_the_first_mention(self):
        filler = "The town was founded by settlers who arrived from the coast in the early years of the colony. "
        hit = "The hairy frog breaks its own toe bones to push out claws. "
        tail = "Researchers described the claws of the frog in detail after studying preserved specimens. "
        keys = shorts.concept_keywords("hairy frog claws")
        out = shorts.concept_paragraphs((filler * 4 + hit + tail * 20).strip(), keys, chars=300)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("The hairy frog breaks"))
        self.assertTrue(out[0].endswith("specimens."))
        self.assertLessEqual(len(out[0]), 300)


class WikipediaNotesBodyTest(unittest.TestCase):
    def test_notes_carry_the_body_paragraph_the_intro_leaves_out(self):
        out, body = _notes()
        self.assertIn("Sodium lauryl sulfate, used as a surfactant in toothpaste, alters taste perception.", out)
        self.assertIn("is still an unresolved issue", out)  # the caveat comes along, not just the claim
        self.assertIn("caused more damage to enamel", out)
        # the paragraph follows its own article, and the note headers are unchanged
        self.assertLess(out.index("[Toothpaste]"), out.index("Sodium lauryl sulfate"))
        self.assertLess(out.index("Sodium lauryl sulfate"), out.index("[Tooth brushing]"))
        self.assertEqual(out.count(TOOTHPASTE_INTRO), 1)

    def test_only_articles_that_are_kept_are_read(self):
        out, body = _notes()
        self.assertNotIn("Sodium dodecyl sulfate", out)  # its intro never mentions the concept
        self.assertEqual([c.args[0] for c in body.call_args_list], ["Toothpaste", "Tooth brushing"])

    def test_no_concept_means_intros_only(self):
        out, body = _notes(concept="")
        body.assert_not_called()
        self.assertEqual(out, "\n\n".join(SEARCH))

    def test_unreadable_article_keeps_the_intro(self):
        with mock.patch.object(shorts.gemini, "call", _no_gemini), \
                mock.patch.object(shorts, "_wiki_search", return_value=list(SEARCH)), \
                mock.patch.object(shorts, "_wiki_body", side_effect=OSError("timed out")), \
                contextlib.redirect_stdout(io.StringIO()) as log:
            out = shorts.wikipedia_notes(TOPIC, concept=CONCEPT)
        self.assertEqual(out, "\n\n".join([SEARCH[0], SEARCH[2]]))
        self.assertIn("article body skipped", log.getvalue())

    def test_notes_stay_within_what_the_last_check_reads(self):
        para = ("Orange juice and toothpaste do not go well together, as many people notice at breakfast. " * 9)[:790]
        search = [f"[Article {i}] (https://en.wikipedia.org/wiki/Article_{i})\n"
                  + ("Toothpaste and orange juice. " * 100)[:2500] for i in range(3)]
        bodies = {f"Article {i}": "\n".join(f"Marker{n} {para}" for n in range(6)) for i in range(3)}
        out, _ = _notes(search=search, bodies=bodies)
        self.assertLessEqual(len(out), shorts.NOTES_LIMIT)
        self.assertEqual(out.count("Marker"), 5)  # 2 + 2 + 1: the last article only gets what still fits

    def test_article_count_in_the_log_ignores_brackets_in_the_text(self):
        notes = "[A] (u)\nAn intro with [sic] brackets.\nA body paragraph [1] too.\n\n[B] (u)\nAnother intro."
        with mock.patch.object(shorts, "wikipedia_notes", return_value=notes), \
                contextlib.redirect_stdout(io.StringIO()) as log:
            self.assertEqual(shorts.research("topic", "concept"), notes)
        self.assertIn("[Research] Wikipedia: 2 articles", log.getvalue())


if __name__ == "__main__":
    unittest.main()
