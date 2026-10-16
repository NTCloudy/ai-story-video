import unittest

from storyvideo.render import layout_cues
from storyvideo.subtitles import MAX_LINE, build_cues, clean, split_lines

SAMPLES = [
    "可是，每當唧唧看到眼前有點高的木頭，他大腦裡那隻叫小膽小的紫色心情怪獸就會跳出來。",
    "今天真是一個好天氣，我們一起去公園散步吧！",
    "從前在綠油油的大森林裡，住著一隻可愛的小兔子叫唧唧。",
    "呼的一聲，唧唧深吸了一大口氣，雙腳蹬地，輕輕一跳！",
    "唧唧停下了腳步深呼吸了一口氣然後輕輕拍拍自己的胸口對自己說沒關係我覺得害怕是很正常的",
]


class SubtitleTest(unittest.TestCase):
    def test_no_punctuation_and_length(self):
        for s in SAMPLES:
            for _, _, text in build_cues(s, 0, 10):
                self.assertLessEqual(len(text.replace(" ", "")), MAX_LINE, text)
                self.assertFalse(any(p in text for p in "，。！？、；："), text)

    def test_words_not_split(self):
        lines = [clean(x).replace(" ", "") for x in split_lines(SAMPLES[0])]
        joined = "|".join(lines)
        for word in ("怪獸", "唧唧", "木頭", "心情"):
            self.assertNotIn(word[0] + "|" + word[1], joined, joined)
        lines = [clean(x) for x in split_lines(SAMPLES[1])]
        self.assertNotIn("氣", [x.strip() for x in lines])

    def test_short_fragment_merged(self):
        lines = [clean(x) for x in split_lines(SAMPLES[0])]
        self.assertNotEqual(lines[0].strip(), "可是", lines)

    def test_timing_covers_sentence(self):
        cues = build_cues(SAMPLES[2], 1.0, 5.0)
        self.assertAlmostEqual(cues[0][0], 1.0)
        self.assertAlmostEqual(cues[-1][1], 5.0)

    def test_layout_no_overlap(self):
        groups = [(0.0, [(0.0, 2.05, "第一句"), (2.0, 4.0, "第二句")]), (4.0, [(0.0, 1.0, "第三句")])]
        cues = layout_cues(groups)
        for a, b in zip(cues, cues[1:]):
            self.assertLessEqual(a[1], b[0])


if __name__ == "__main__":
    unittest.main()
