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
            if ("4006" in r.text or "daily free allocation" in r.text) and not os.environ.get("ALLOW_PLACEHOLDER"):
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


def scene_prompt(scene: dict, chars: list[dict], ref_names: list[str], style: str, vertical: bool = False) -> str:
    by_name = {c["name"]: c["appearance"] for c in chars}
    parts = [scene["image_prompt"].strip().rstrip(".") + "."]
    for k, n in enumerate(ref_names):
        parts.append(f"{n} is exactly the character in reference image {k + 1} ({by_name.get(n, '')}); "
                     f"keep the same face, proportions, colors and outfit.")
    for n in scene.get("characters") or []:
        if n not in ref_names and n in by_name:
            parts.append(f"{n}: {by_name[n]}.")
    comp = ("Vertical 9:16 composition, main subject centered in the upper two-thirds of the frame"
            if vertical else "Wide cinematic 16:9 composition, main subject in the upper-middle of the frame")
    parts.append(f"Art style: {style}. {comp}. No text, no letters, no watermark.")
    return " ".join(parts)


QA_SCHEMA = {"type": "OBJECT", "properties": {"ok": {"type": "BOOLEAN"}, "problem": {"type": "STRING"}},
             "required": ["ok", "problem"]}
SAFER = (" Clear, literal, easy-to-read composition with natural anatomy; no faces replaced by objects or planets,"
         " no reflections of other scenes inside helmets or eyes, no text.")


def check_image(path: Path, prompt: str) -> tuple[bool, str]:
    """Ask Gemini (vision) whether an illustration has an obvious AI mistake. Best effort: True on errors."""
    import json
    from . import gemini
    q = ("You check AI-generated illustrations for a family-friendly science YouTube Short before publishing.\n"
         f"The picture should show: {prompt[:600]}\n"
         "Answer ok=false ONLY for clear problems most viewers would find weird or wrong: a face replaced by an "
         "object or a planet, an empty or headless suit or helmet that looks like a creepy floating head, melted or "
         "distorted faces or bodies, extra or missing limbs, duplicated people, visible text or letters, or a "
         "picture that does not show the requested subject at all. Artistic style, dramatic lighting and small "
         "imperfections are fine. Put a short reason in problem (empty when ok).")
    try:
        time.sleep(4)  # stay under the free tier's requests-per-minute limit
        text, _ = gemini.call(q, QA_SCHEMA, temperature=0.0, max_models=3, images=[path], lite_first=True)
        d = json.loads(text)
        return bool(d.get("ok", True)), str(d.get("problem", ""))
    except Exception as e:
        print(f"[插畫檢查] 略過：{str(e)[:120]}")
        return True, ""


def generate_images(scenes: list[dict], style: str, characters, out_dir: Path, vertical: bool = False,
                    optional: set[int] | None = None, check: bool = False) -> list[Path | None]:
    """One image per entry. Entries listed in `optional` (extra shots) are drawn after all required ones,
    return None on failure (or once the daily quota runs out) instead of a placeholder background, and do not
    count towards the failure limit."""
    w, h = (SCENE_H, SCENE_W) if vertical else (SCENE_W, SCENE_H)
    out_dir.mkdir(parents=True, exist_ok=True)
    chars = normalize_characters(characters)
    refs = make_character_refs(chars, style, out_dir) if chars else {}
    optional = optional or set()
    order = [i for i in range(len(scenes)) if i not in optional] + [i for i in range(len(scenes)) if i in optional]
    paths: list[Path | None] = [None] * len(scenes)
    failed, quota_out = 0, False
    for i in order:
        sc = scenes[i]
        if i in optional and quota_out:
            continue
        path = out_dir / f"scene_{i:02d}.jpg"
        names = [n for n in (sc.get("characters") or []) if n in refs][:MAX_REFS]
        prompt = scene_prompt(sc, chars, names, style, vertical)
        drawn = True
        try:
            path.write_bytes(flux2(prompt, [refs[n] for n in names], w, h))
            print(f"[插畫] 分鏡 {i + 1}/{len(scenes)} 完成（參考 {len(names)} 個角色）")
        except QuotaExceeded:
            if i not in optional:
                raise
            print("[插畫] 今日額度用完，其餘額外鏡頭略過")
            quota_out = True
            continue
        except Exception as e1:
            print(f"[插畫] 分鏡 {i + 1} FLUX.2 失敗，改用 FLUX.1：{e1}")
            try:
                full = scene_prompt(sc, chars, [], style, vertical)
                path.write_bytes(flux1(full))
            except QuotaExceeded:
                if i not in optional:
                    raise
                quota_out = True
                continue
            except Exception as e2:
                if i in optional:
                    print(f"[插畫] 分鏡 {i + 1}（額外鏡頭）失敗，略過：{e2}")
                    continue
                print(f"[插畫] 分鏡 {i + 1} 失敗，用預設背景代替：{e2}")
                placeholder(path, i)
                failed += 1
                drawn = False
        if check and drawn and not _review(path, i, sc["image_prompt"], prompt, [refs[n] for n in names], w, h,
                                           i in optional):
            continue
        paths[i] = path
    required = len(scenes) - len(optional)
    if failed > max(1, required // 4) and not os.environ.get("ALLOW_PLACEHOLDER"):
        raise RuntimeError(f"有 {failed}/{required} 張插畫失敗，為避免產生品質不佳的影片已停止")
    return paths


def _review(path: Path, i: int, wanted: str, prompt: str, refs: list[Path], w: int, h: int, optional: bool) -> bool:
    """Gemini checks the picture; a weird one is redrawn once with safer wording.
    Returns False when an extra shot should be dropped (still wrong, or no quota left to redraw)."""
    ok, problem = check_image(path, wanted)
    if ok:
        return True
    print(f"[插畫檢查] 分鏡 {i + 1} 有問題：{problem}，重畫一次")
    try:
        data = flux2(prompt + SAFER, refs, w, h)
    except Exception as e:  # quota or API error: keep the first picture for required scenes
        print(f"[插畫檢查] 分鏡 {i + 1} 重畫失敗：{str(e)[:120]}")
        return not optional
    path.write_bytes(data)
    ok, problem = check_image(path, wanted)
    if not ok:
        print(f"[插畫檢查] 分鏡 {i + 1} 重畫後仍有問題：{problem}" + ("，拿掉這張額外鏡頭" if optional else ""))
        return not optional
    print(f"[插畫檢查] 分鏡 {i + 1} 重畫後通過")
    return True
