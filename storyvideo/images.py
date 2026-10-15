"""Scene illustrations via Cloudflare Workers AI (Flux, free daily allowance)."""

from __future__ import annotations

import base64
import os
import subprocess
import time
from pathlib import Path

import requests

CF_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
CF_MODEL = os.environ.get("CF_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell")


def _cf_image(prompt: str, seed: int) -> bytes:
    account = os.environ.get("CF_ACCOUNT_ID", "").strip()
    token = os.environ.get("CF_API_TOKEN", "").strip()
    if not (account and token):
        raise RuntimeError("沒有設定 CF_ACCOUNT_ID / CF_API_TOKEN")
    last = None
    for attempt in range(4):
        r = requests.post(
            CF_URL.format(account=account, model=CF_MODEL),
            headers={"Authorization": f"Bearer {token}"},
            json={"prompt": prompt[:2000], "steps": 8, "seed": seed},
            timeout=120,
        )
        if r.status_code == 200:
            ctype = r.headers.get("content-type", "")
            if ctype.startswith("image/"):
                return r.content
            data = r.json()
            img = (data.get("result") or {}).get("image")
            if img:
                return base64.b64decode(img)
            last = f"unexpected response: {str(data)[:200]}"
        else:
            last = f"HTTP {r.status_code}: {r.text[:300]}"
            if r.status_code in (400, 401, 403):
                break
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Cloudflare 插畫生成失敗：{last}")


def placeholder(path: Path, text: str, idx: int) -> None:
    """Gradient placeholder so the pipeline still produces a video without an image provider."""
    colors = ["0x2b5876:0x4e4376", "0xee9ca7:0xffdde1", "0x134e5e:0x71b280", "0xff512f:0xdd2476"]
    c1, c2 = colors[idx % len(colors)].split(":")
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"gradients=s=1920x1080:c0={c1}:c1={c2}:d=1", "-frames:v", "1", str(path),
    ], check=True)


def generate_images(scenes: list[dict], style: str, characters: str, out_dir: Path, seed: int = 42) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, sc in enumerate(scenes):
        path = out_dir / f"scene_{i:02d}.jpg"
        prompt = f"{sc['image_prompt']}. Style: {style}. No text, no letters, no watermark."
        if characters:
            prompt = f"{prompt} Characters: {characters}"
        try:
            path.write_bytes(_cf_image(prompt, seed + i))
            print(f"[插畫] {i + 1}/{len(scenes)} 完成")
        except Exception as e:
            print(f"[插畫] {i + 1}/{len(scenes)} 失敗，用預設背景代替：{e}")
            placeholder(path, sc["narration"], i)
        paths.append(path)
    return paths
