"""Narration with Microsoft Edge neural voices (free) + subtitle cue timing."""

from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

import edge_tts

from .subtitles import build_cues, sentences

VOICES = {
    "female": "zh-TW-HsiaoChenNeural",
    "female2": "zh-TW-HsiaoYuNeural",
    "male": "zh-TW-YunJheNeural",
}

async def _tts(text: str, voice: str, rate: str, mp3: Path) -> list[tuple[float, float, str]]:
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="SentenceBoundary")
    cues = []
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("SentenceBoundary", "WordBoundary"):
                s = chunk["offset"] / 1e7
                e = s + chunk["duration"] / 1e7
                cues.extend(build_cues(chunk["text"], s, e))
    return cues


def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out or 0)


def _gtts(text: str, mp3: Path) -> list[tuple[float, float, str]]:
    """Fallback: Google Translate TTS (no timings -> proportional cues). Sped up 1.2x for natural pace."""
    from gtts import gTTS
    raw = mp3.with_suffix(".raw.mp3")
    gTTS(text, lang="zh-TW", timeout=30).save(str(raw))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-filter:a", "atempo=1.2", str(mp3)], check=True)
    raw.unlink(missing_ok=True)
    sents = sentences(text)
    total = sum(len(x) for x in sents) or 1
    dur, t, cues = _duration(mp3), 0.0, []
    for x in sents:
        d = dur * len(x) / total
        cues.extend(build_cues(x, t, t + d))
        t += d
    return cues


_EDGE_OK = True


def narrate(scenes: list[dict], out_dir: Path, voice: str = "female", rate: str = "+0%") -> list[dict]:
    global _EDGE_OK
    out_dir.mkdir(parents=True, exist_ok=True)
    v = VOICES.get(voice, voice)
    results = []
    for i, sc in enumerate(scenes):
        mp3 = out_dir / f"scene_{i:02d}.mp3"
        cues = None
        if _EDGE_OK:
            for attempt in range(3):
                try:
                    cues = asyncio.run(asyncio.wait_for(_tts(sc["narration"], v, rate, mp3), 90))
                    break
                except Exception as e:  # network hiccups / blocked
                    print(f"[配音] 微軟語音失敗（{attempt + 1}/3）：{type(e).__name__}: {str(e)[:120]}")
            if cues is None:
                print("[配音] 改用 Google 語音備援")
                _EDGE_OK = False
        if cues is None:
            cues = _gtts(sc["narration"], mp3)
        if not cues:
            cues = [(0.0, _duration(mp3), sc["narration"])]
        results.append({"audio": mp3, "cues": cues})
        print(f"[配音] {i + 1}/{len(scenes)} 完成")
    return results
