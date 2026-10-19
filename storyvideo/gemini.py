"""Shared Gemini API caller with automatic model selection and fallback."""

from __future__ import annotations

import base64
import json
import os
import time

import requests

from .storyboard import GEMINI_URL, discover_models


def call(prompt: str, schema: dict | None = None, search: bool = False, temperature: float = 0.8,
         api_key: str | None = None, max_models: int | None = None, images: list | None = None,
         lite_first: bool = False) -> tuple[str, str]:
    """Returns (text, model). With `schema` the text is JSON. `search` enables Google Search grounding.
    `images`: optional JPEG/PNG file paths sent along with the prompt (vision).
    `lite_first`: try the cheaper "lite" models first (simple checks; keeps the main models' free quota)."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("沒有設定 GEMINI_API_KEY")
    cfg: dict = {"temperature": temperature}
    if schema:
        cfg.update(responseMimeType="application/json", responseSchema=schema)
    parts: list[dict] = [{"text": prompt}]
    for img in images or []:
        data = open(img, "rb").read()
        mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}})
    body: dict = {"contents": [{"role": "user", "parts": parts}], "generationConfig": cfg}
    if search:
        body["tools"] = [{"google_search": {}}]
    models = discover_models(api_key)
    if lite_first:
        models = list(dict.fromkeys([m for m in models if "lite" in m] + models))
    if max_models:
        models = models[:max_models]
    last = None
    for n, model in enumerate(models):
        if n and n % max(len(models) // 2, 1) == 0:
            time.sleep(20)
        try:
            r = requests.post(GEMINI_URL.format(model=model), headers={"x-goog-api-key": api_key},
                              json=body, timeout=240)
            if r.status_code in (429, 500, 503):
                last = f"{model}: HTTP {r.status_code}"
                print(f"[Gemini] {model} busy ({r.status_code}), trying next model")
                time.sleep(5)
                continue
            if r.status_code in (400, 403, 404):
                last = f"{model}: HTTP {r.status_code} {r.text[:200]}"
                continue
            r.raise_for_status()
            parts = r.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
            if schema:
                json.loads(text)  # validate
            if not text:
                raise ValueError("empty response")
            return text, model
        except (requests.RequestException, KeyError, ValueError) as e:
            last = f"{model}: {type(e).__name__}: {e}"
            time.sleep(3)
    raise RuntimeError(f"Gemini 呼叫失敗：{last}")
