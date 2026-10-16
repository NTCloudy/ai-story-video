"""Scene illustrations via Cloudflare Workers AI.

Consistency strategy:
1. Draw one reference sheet per main character (FLUX.2 klein).
2. Every scene is generated with those reference images attached (multi-reference editing),
   plus one fixed global style string, so characters keep the same look across the video.
Falls back to FLUX.1 schnell (text only) and finally a gradient placeholder.
"""

from __future__ import annotations

import base64
import os
import subprocess
import time
from pathlib import Path

import requests

CF_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
REF_MODEL = os.environ.get("CF_REF_MODEL", "@cf/black-forest-labs/flux-2-klein-4b")  # ~150 neurons/image
FALLBACK_MODEL = os.environ.get("CF_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell")
SCENE_W, SCENE_H = 1344, 768   # ~16:9
MAX_REFS = 4


class QuotaExceeded(RuntimeError):
    """Cloudflare daily free allocation used up (resets 00:00 UTC = 08:00 Taiwan)."""


def _creds() -> tuple[str, str]:
    account = os.environ.get("CF_ACCOUNT_ID", "").strip()
    token = os.environ.get("CF_API_TOKEN", "").strip()
    if not (account and token):
        raise RuntimeError("沒有設定 CF_ACCOUNT_ID / CF_API_TOKEN")
    return account, token


def _decode(r: requests.Response) -> bytes:
    if r.headers.get("content-type", "").startswith("image/"):
        return r.content
    img = (r.json().get("result") or {}).get("image")
    if not img:
        raise RuntimeError(f"unexpected response: {r.text[:200]}")
    return base64.b64decode(img)


def _post(model: str, **kwargs) -> bytes:
    account, token = _creds()
    last = None
    for attempt in range(3):
        try:
            r = requests.post(CF_URL.format(account=account, model=model),
                              headers={"Authorization": f"Bearer {token}"}, timeout=180, **kwargs)
            if r.status_code == 200:
                return _decode(r)
            last = f"HTTP {r.status_code}: {r.text[:300]}"
            if "4006" in r.text or "daily free allocation" in r.text:
                raise QuotaExceeded("Cloudflare 今日免費插畫額度已用完（每天早上 8 點重置）")
            if r.status_code in (400, 401, 403, 413):
                break
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"{model} 失敗：{last}")


def flux2(prompt: str, refs: list[Path] | None = None, w: int = SCENE_W, h: int = SCENE_H) -> bytes:
    files = {"prompt": (None, prompt[:2500]), "width": (None, str(w)), "height": (None, str(h))}
    for i, p in enumerate((refs or [])[:MAX_REFS]):
        files[f"input_image_{i}"] = (p.name, p.read_bytes(), "image/jpeg")
    return _post(REF_MODEL, files=files)


def flux1(prompt: str) -> bytes:
    return _post(FALLBACK_MODEL, json={"prompt": prompt[:2000], "steps": 8})


def placeholder(path: Path, idx: int) -> None:
    colors = ["0x2b5876:0x4e4376", "0xee9ca7:0xffdde1", "0x134e5e:0x71b280", "0xff512f:0xdd2476"]
    c1, c2 = colors[idx % len(colors)].split(":")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"gradients=s=1920x1080:c0={c1}:c1={c2}:d=1",
                    "-frames:v", "1", str(path)], check=True)


def normalize_characters(characters) -> list[dict]:
    if isinstance(characters, list):
        return [c for c in characters if isinstance(c, dict) and c.get("name") and c.get("appearance")][:MAX_REFS]
    return []


def make_character_refs(characters: list[dict], style: str, out_dir: Path) -> dict[str, Path]:
    refs = {}
    for c in characters:
        path = out_dir / f"ref_{len(refs)}.jpg"
        prompt = (f"Character design reference sheet of {c['name']}: {c['appearance']}. Single character only, "
                  f"full body, front view, standing, neutral friendly expression, plain light background. "
                  f"Style: {style}. No text, no letters.")
        try:
            path.write_bytes(flux2(prompt, w=1024, h=1024))
            refs[c["name"]] = path
            print(f"[插畫] 角色定裝照：{c['name']} 完成")
        except QuotaExceeded:
            raise
        except Exception as e:
            print(f"[插畫] 角色定裝照：{c['name']} 失敗：{e}")
    return refs


def scene_prompt(scene: dict, chars: list[dict], ref_names: list[str], style: str) -> str:
    by_name = {c["name"]: c["appearance"] for c in chars}
    parts = [scene["image_prompt"].strip().rstrip(".") + "."]
    for k, n in enumerate(ref_names):
        parts.append(f"{n} is exactly the character in reference image {k + 1} ({by_name.get(n, '')}); "
                     f"keep the same face, proportions, colors and outfit.")
    for n in scene.get("characters") or []:
        if n not in ref_names and n in by_name:
            parts.append(f"{n}: {by_name[n]}.")
    parts.append(f"Art style: {style}. Wide cinematic 16:9 composition, main subject in the upper-middle "
                 f"of the frame. No text, no letters, no watermark.")
    return " ".join(parts)


def generate_images(scenes: list[dict], style: str, characters, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    chars = normalize_characters(characters)
    refs = make_character_refs(chars, style, out_dir) if chars else {}
    paths, failed = [], 0
    for i, sc in enumerate(scenes):
        path = out_dir / f"scene_{i:02d}.jpg"
        names = [n for n in (sc.get("characters") or []) if n in refs][:MAX_REFS]
        prompt = scene_prompt(sc, chars, names, style)
        try:
            path.write_bytes(flux2(prompt, [refs[n] for n in names]))
            print(f"[插畫] 分鏡 {i + 1}/{len(scenes)} 完成（參考 {len(names)} 個角色）")
        except QuotaExceeded:
            raise
        except Exception as e1:
            print(f"[插畫] 分鏡 {i + 1} FLUX.2 失敗，改用 FLUX.1：{e1}")
            try:
                full = scene_prompt(sc, chars, [], style)
                path.write_bytes(flux1(full))
            except QuotaExceeded:
                raise
            except Exception as e2:
                print(f"[插畫] 分鏡 {i + 1} 失敗，用預設背景代替：{e2}")
                placeholder(path, i)
                failed += 1
        paths.append(path)
    if failed > max(1, len(scenes) // 4):
        raise RuntimeError(f"有 {failed}/{len(scenes)} 張插畫失敗，為避免產生品質不佳的影片已停止")
    return paths
