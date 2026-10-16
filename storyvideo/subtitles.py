"""Subtitle line building for Chinese narration.

- Never split inside a word (jieba word segmentation).
- Prefer breaking at punctuation; punctuation itself is not displayed.
- Merge very short fragments (e.g. 「可是，」) with the next clause.
- Timing is proportional to spoken characters within the sentence's [start, end].
"""

from __future__ import annotations

import math
import re
from pathlib import Path

_DICT = Path(__file__).with_name("data") / "dict.txt.big"   # jieba Traditional-Chinese dictionary (MIT)
_BAD_START = set("的了著過嗎呢吧啊呀喔哦嘛啦得地")

MAX_LINE = 16   # max displayed chars per subtitle line
MIN_LINE = 5    # fragments shorter than this get merged with a neighbour

PUNCT = "，。！？、；：,.!?;:「」『』“”‘’\"'（）()《》〈〉…—～~·．"
_PUNCT_RE = re.compile(f"[{re.escape(PUNCT)}]+")
_CLAUSE_RE = re.compile(f"(?<=[{re.escape('，。！？、；：,.!?;:…')}])")

_jieba = None


def _words(text: str) -> list[str]:
    global _jieba
    if _jieba is None:
        import jieba
        jieba.setLogLevel(60)
        if _DICT.exists():
            jieba.set_dictionary(str(_DICT))
        _jieba = jieba
    return [w for w in _jieba.cut(text) if w]


def clean(text: str) -> str:
    """Display form: punctuation removed (inner pauses become a space)."""
    return re.sub(r"\s+", " ", _PUNCT_RE.sub(" ", text)).strip()


def _spoken_len(text: str) -> int:
    return len(clean(text).replace(" ", ""))


def _split_long(clause: str) -> list[str]:
    """Split a clause longer than MAX_LINE at word boundaries into the most even pieces (DP)."""
    n = _spoken_len(clause)
    if n <= MAX_LINE:
        return [clause]
    words = []
    for w in _words(clause):  # hard-wrap any single word longer than a line
        while _spoken_len(w) > MAX_LINE:
            words.append(w[:MAX_LINE])
            w = w[MAX_LINE:]
        if w:
            words.append(w)
    lens = [_spoken_len(w) for w in words]
    k = math.ceil(n / MAX_LINE)
    target = n / k
    m = len(words)
    INF = float("inf")
    # best[i][j]: min cost splitting words[:i] into j pieces
    best = [[INF] * (k + 2) for _ in range(m + 1)]
    back = [[0] * (k + 2) for _ in range(m + 1)]
    best[0][0] = 0.0
    for i in range(1, m + 1):
        for j in range(1, k + 2):
            seg = 0
            for p in range(i - 1, -1, -1):
                seg += lens[p]
                if seg > MAX_LINE:
                    break
                if best[p][j - 1] == INF:
                    continue
                cost = best[p][j - 1] + (seg - target) ** 2
                if p > 0 and words[p][:1] in _BAD_START:
                    cost += 25  # avoid starting a line with a particle
                if cost < best[i][j]:
                    best[i][j], back[i][j] = cost, p
    j = min(range(1, k + 2), key=lambda x: best[m][x])
    pieces, i = [], m
    while i > 0:
        p = back[i][j]
        pieces.append("".join(words[p:i]))
        i, j = p, j - 1
    return pieces[::-1]


def split_lines(sentence: str) -> list[str]:
    """Sentence -> list of raw subtitle chunks (still containing punctuation)."""
    clauses = [c for c in _CLAUSE_RE.split(sentence.strip()) if _spoken_len(c)]
    chunks: list[str] = []
    for c in clauses:
        chunks.extend(_split_long(c))
    # merge short fragments forward/backward when the result still fits on one line
    merged: list[str] = []
    for c in chunks:
        if merged and (_spoken_len(merged[-1]) < MIN_LINE or _spoken_len(c) < MIN_LINE) \
                and _spoken_len(merged[-1]) + _spoken_len(c) <= MAX_LINE:
            merged[-1] += c
        else:
            merged.append(c)
    return merged


def build_cues(sentence: str, start: float, end: float) -> list[tuple[float, float, str]]:
    chunks = split_lines(sentence)
    total = sum(_spoken_len(c) for c in chunks) or 1
    out, t = [], start
    for c in chunks:
        d = (end - start) * _spoken_len(c) / total
        out.append((t, t + d, clean(c)))
        t += d
    return out


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[。！？!?])", text) if _spoken_len(s)]


# ---------------- English (Shorts word-by-word captions) ----------------
EN_MAX_WORDS = 3
EN_MAX_CHARS = 15
_EN_STRIP = re.compile(r"[^\w'%$&+\-./:]+", re.UNICODE)


def _en_clean(w: str) -> str:
    return _EN_STRIP.sub("", w).strip(".,:;!?-")


def build_cues_en(words: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    """Group timed words into 1-3 word captions; break on pauses/punctuation. Display uppercase, no punctuation."""
    cues, cur = [], []

    def flush():
        if cur:
            text = " ".join(_en_clean(w) for _, _, w in cur if _en_clean(w)).upper()
            if text:
                cues.append((cur[0][0], cur[-1][1], text))
            cur.clear()

    for i, (s, e, w) in enumerate(words):
        if cur:
            gap = s - cur[-1][1]
            chars = len(" ".join(x[2] for x in cur)) + 1 + len(w)
            if len(cur) >= EN_MAX_WORDS or chars > EN_MAX_CHARS or gap > 0.25 or re.search(r"[.,!?;:]$", cur[-1][2]):
                flush()
        cur.append((s, e, w))
    flush()
    return cues


def proportional_words(text: str, start: float, end: float) -> list[tuple[float, float, str]]:
    """Approximate per-word timing when the TTS engine gives no word boundaries."""
    words = text.split()
    total = sum(len(w) + 1 for w in words) or 1
    out, t = [], start
    for w in words:
        d = (end - start) * (len(w) + 1) / total
        out.append((t, t + d, w))
        t += d
    return out
