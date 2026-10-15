"""Story -> storyboard (scenes with narration + image prompts) using the Gemini API (free tier)."""

from __future__ import annotations

import json
import os
import re
import time

import requests

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODELS = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.0-flash"]

LENGTHS = {  # scenes, approx. narration chars per scene
    "short": (6, 45),
    "medium": (10, 55),
    "long": (16, 60),
}

DEFAULT_STYLE = (
    "warm cinematic storybook illustration, soft painterly lighting, rich colors, "
    "highly detailed, wide 16:9 composition"
)

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "characters": {"type": "STRING"},
        "scenes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "narration": {"type": "STRING"},
                    "image_prompt": {"type": "STRING"},
                },
                "required": ["narration", "image_prompt"],
            },
        },
        "youtube_title": {"type": "STRING"},
        "youtube_description": {"type": "STRING"},
        "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["title", "characters", "scenes", "youtube_title", "youtube_description", "tags"],
}


def _prompt(story: str, title: str, length: str, faithful: bool) -> str:
    n, chars = LENGTHS.get(length, LENGTHS["medium"])
    mode = ("盡量保留使用者原文的句子與用詞，只做必要的斷句與潤飾" if faithful
            else "可以改寫、潤飾成適合朗讀的旁白，但不能改變故事內容與結局")
    return f"""你是專業的動畫分鏡師與 YouTube 說故事頻道編劇。請把下面的故事改編成一支「插畫 + 旁白」影片的分鏡腳本。

規則：
1. 分成約 {n} 個分鏡（可依故事長短 ±3），每個分鏡的旁白約 {chars} 個中文字，使用台灣慣用的繁體中文、口語自然、適合朗讀。{mode}。
2. 每個分鏡的 image_prompt 用「英文」詳細描述畫面（場景、角色動作、表情、構圖、光線、鏡頭），不要出現任何文字或字幕。
3. 角色外觀要一致：先在 characters 欄位用英文定義每個主要角色的固定外觀（年齡、髮型、服裝、顏色、物種等），並在每個 image_prompt 裡重複寫出出場角色的完整外觀描述。
4. title：影片標題（繁體中文，15 字內）{f'，使用者指定的標題是「{title}」，請直接使用' if title else ''}。
5. youtube_title：吸引人的 YouTube 標題（繁體中文，60 字內）。youtube_description：YouTube 影片說明（繁體中文，含故事簡介 2～3 句與 3～5 個 hashtag）。tags：8～12 個 YouTube 標籤。

故事：
\"\"\"
{story.strip()}
\"\"\"
"""


def generate_storyboard(story: str, title: str = "", length: str = "medium", faithful: bool = False,
                        api_key: str | None = None) -> dict:
    api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("[警告] 沒有 GEMINI_API_KEY，改用簡易斷句模式（插畫提示詞品質會比較差）")
        return fallback_storyboard(story, title, length)

    models = [m for m in [os.environ.get("GEMINI_MODEL", "")] if m] + DEFAULT_MODELS
    body = {
        "contents": [{"role": "user", "parts": [{"text": _prompt(story, title, length, faithful)}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA,
                             "temperature": 0.8},
    }
    last_err = None
    for model in models:
        for attempt in range(3):
            try:
                r = requests.post(GEMINI_URL.format(model=model), params={"key": api_key}, json=body, timeout=180)
                if r.status_code in (429, 500, 503):
                    last_err = f"{model}: HTTP {r.status_code} {r.text[:200]}"
                    time.sleep(10 * (attempt + 1))
                    continue
                if r.status_code == 404:
                    last_err = f"{model}: not found"
                    break
                r.raise_for_status()
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                data = json.loads(text)
                if title:
                    data["title"] = title
                data["scenes"] = [s for s in data.get("scenes", []) if s.get("narration", "").strip()]
                if not data["scenes"]:
                    raise ValueError("Gemini 沒有產生任何分鏡")
                data["model"] = model
                return data
            except (requests.RequestException, KeyError, ValueError, json.JSONDecodeError) as e:
                last_err = f"{model}: {type(e).__name__}: {e}"
                time.sleep(3)
    raise RuntimeError(f"Gemini 產生分鏡失敗：{last_err}")


def fallback_storyboard(story: str, title: str = "", length: str = "medium") -> dict:
    """No-AI fallback: split text into scenes by sentence."""
    _, chars = LENGTHS.get(length, LENGTHS["medium"])
    sentences = [s for s in re.split(r"(?<=[。！？!?\n])", story) if s.strip()]
    scenes, buf = [], ""
    for s in sentences:
        if buf and len(buf) + len(s) > chars:
            scenes.append(buf.strip())
            buf = ""
        buf += s
    if buf.strip():
        scenes.append(buf.strip())
    t = title or (story.strip().splitlines()[0][:15] if story.strip() else "我的故事")
    return {
        "title": t, "characters": "",
        "scenes": [{"narration": s, "image_prompt": f"storybook illustration of: {s}"} for s in scenes],
        "youtube_title": t, "youtube_description": t, "tags": [], "model": "fallback",
    }
