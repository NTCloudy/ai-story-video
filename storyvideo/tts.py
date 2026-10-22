"""Narration with Microsoft Edge neural voices (free) + subtitle cue timing."""

from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

import edge_tts

from .subtitles import build_cues, build_cues_en, proportional_words, sentences

VOICES = {
    "female": "zh-TW-HsiaoChenNeural",
    "female2": "zh-TW-HsiaoYuNeural",
    "male": "zh-TW-YunJheNeural",
    "en_male": "en-US-AndrewNeural",
    "en_male2": "en-US-ChristopherNeural",
    "en_female": "en-US-AvaNeural",
}

async def _tts(text: str, voice: str, rate: str, mp3: Path, lang: str = "zh"):
    """Returns (cues, words); words = per-word timings for English (used for the highlighted captions)."""
    boundary = "WordBoundary" if lang == "en" else "SentenceBoundary"
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary=boundary)
    cues, words = [], []
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("SentenceBoundary", "WordBoundary"):
                s = chunk["offset"] / 1e7
                e = s + chunk["duration"] / 1e7
                if lang == "en":
                    words.append((s, e, chunk["text"]))
                else:
                    cues.extend(build_cues(chunk["text"], s, e))
    if lang == "en":
        words = _attach_punct(text, words)
        cues = build_cues_en(words)
    return cues, words


def _attach_punct(text: str, words: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    """Edge word boundaries drop punctuation; re-attach it from the source text so captions break naturally."""
    toks, out, k = text.split(), [], 0
    for s, e, w in words:
        while k < len(toks) and w.lower().strip(".,!?;:\"'") not in toks[k].lower():
            k += 1
        out.append((s, e, toks[k] if k < len(toks) else w))
        k += 1
    return out


def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out or 0)


def _gtts(text: str, mp3: Path, lang: str = "zh"):
    """Fallback: Google Translate TTS (no timings -> proportional cues). Sped up 1.2x for natural pace.
    Returns (cues, words) like _tts."""
    from gtts import gTTS
    raw = mp3.with_suffix(".raw.mp3")
    gTTS(text, lang="en" if lang == "en" else "zh-TW", timeout=30).save(str(raw))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-filter:a", "atempo=1.2", str(mp3)], check=True)
    raw.unlink(missing_ok=True)
    if lang == "en":
        words = proportional_words(text, 0.0, _duration(mp3))
        return build_cues_en(words), words
    sents = sentences(text)
    total = sum(len(x) for x in sents) or 1
    dur, t, cues = _duration(mp3), 0.0, []
    for x in sents:
        d = dur * len(x) / total
        cues.extend(build_cues(x, t, t + d))
        t += d
    return cues, []


_EDGE_OK = True


def narrate(scenes: list[dict], out_dir: Path, voice: str = "female", rate: str = "+0%",
            lang: str = "zh", allow_backup: bool = True) -> list[dict]:
    """allow_backup=False: stop instead of switching to the robotic Google voice when the main voice fails."""
    global _EDGE_OK
    out_dir.mkdir(parents=True, exist_ok=True)
    v = VOICES.get(voice, voice)
    results = []
    for i, sc in enumerate(scenes):
        mp3 = out_dir / f"scene_{i:02d}.mp3"
        cues, words = None, []
        if _EDGE_OK:
            for attempt in range(3):
                try:
                    cues, words = asyncio.run(asyncio.wait_for(_tts(sc["narration"], v, rate, mp3, lang), 90))
                    break
                except Exception as e:  # network hiccups / blocked
                    print(f"[配音] 微軟語音失敗（{attempt + 1}/3）：{type(e).__name__}: {str(e)[:120]}")
            if cues is None and not allow_backup:
                raise RuntimeError("微軟語音連續失敗 3 次，不改用品質較差的備援語音")
            if cues is None:
                print("[配音] 改用 Google 語音備援")
                _EDGE_OK = False
        if cues is None:
            cues, words = _gtts(sc["narration"], mp3, lang)
        if not cues:
            cues = [(0.0, _duration(mp3), sc["narration"])]
        results.append({"audio": mp3, "cues": cues, "words": words})
        print(f"[配音] {i + 1}/{len(scenes)} 完成")
    return results
