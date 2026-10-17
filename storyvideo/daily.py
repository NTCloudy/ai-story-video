"""Daily YouTube Shorts job: pick topic -> research -> script -> images -> voice -> render -> upload.

python -m storyvideo.daily [--topic "..."] [--force] [--no-upload] [--out out]
Channel files (committed back by the workflow):
  channel/channel.yaml   settings (series, voice, privacy, ...)
  channel/queue.json     topics you queued from the web console (first one is used next)
  channel/history.json   every produced Short
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import images, render, shorts, tts, youtube

CH = Path("channel")
TZ = ZoneInfo("Asia/Taipei")


def _load(path: Path, default):
    if path.exists():
        text = path.read_text(encoding="utf-8")
        return (yaml.safe_load(text) if path.suffix in (".yaml", ".yml") else json.loads(text)) or default
    return default


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def publish_video(video_id: str, attempts: int = 6, wait: int = 20) -> str:
    """Make an uploaded video public (uploads from unaudited API projects start as private)."""
    import time
    last = ""
    for i in range(attempts):
        try:
            st = youtube.set_privacy(video_id, "public")
            if st.get("privacyStatus") == "public":
                print(f"[YouTube] 🌐 已公開：https://youtube.com/shorts/{video_id}")
                return "public"
            last = st.get("privacyStatus", "")
        except Exception as e:
            last = str(e)[:200]
        time.sleep(wait)
    print(f"::warning title=自動公開失敗，下次排程會再試::{video_id} {last}")
    return "private"


def publish_pending(history: list[dict]) -> bool:
    """Catch-up: publish any earlier Shorts that are still private (e.g. publishing failed last time)."""
    changed = False
    for h in history:
        if h.get("video_id") and h.get("privacy") != "public" and not h.get("keep_private"):
            print(f"[YouTube] 補公開先前的影片：{h['title']}")
            if publish_video(h["video_id"], attempts=2, wait=10) == "public":
                h["privacy"] = "public"
                changed = True
    return changed


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="storyvideo.daily")
    p.add_argument("--topic", default="")
    p.add_argument("--force", action="store_true", help="make another Short even if one was made today")
    p.add_argument("--no-upload", action="store_true")
    p.add_argument("--out", default="out")
    args = p.parse_args(argv)

    cfg = _load(CH / "channel.yaml", {})
    history = _load(CH / "history.json", [])
    queue = _load(CH / "queue.json", [])
    today = datetime.now(TZ).date().isoformat()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    auto_publish = bool(cfg.get("auto_publish", False)) and youtube.configured() and not args.no_upload
    if auto_publish and publish_pending(history):
        _save(CH / "history.json", history)

    per_day = int(cfg.get("shorts_per_day", 1))
    if not args.force and not args.topic and sum(1 for h in history if h.get("date") == today) >= per_day:
        print(f"今天（{today}）已經做過 {per_day} 支 Shorts，略過。")
        (out / "SKIPPED").write_text("already done today")
        return 0
    if cfg.get("paused") and not (args.force or args.topic):
        print("頻道已暫停自動產生（channel.yaml: paused: true）")
        (out / "SKIPPED").write_text("paused")
        return 0

    # 1. topic
    series = ""
    if args.topic.strip():
        topic = args.topic.strip()
    elif queue:
        item = queue.pop(0)
        topic, series = (item.get("topic", ""), item.get("series", "")) if isinstance(item, dict) else (str(item), "")
    else:
        t = shorts.pick_topic([h["topic"] for h in history], cfg.get("series"))
        topic, series = t["topic"], t["series"]
    print(f"== 主題：{topic}（{series or '自訂'}）==")

    # 2. research + script
    facts = shorts.research(topic)
    sb = shorts.write_short(topic, facts, series)
    (out / "script.json").write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"標題：{sb['youtube_title']}｜{len(sb['scenes'])} 個分鏡｜模型 {sb['model']}")

    # 3. images (vertical)
    try:
        imgs = images.generate_images(sb["scenes"], cfg.get("style", shorts.SHORT_STYLE), sb.get("characters", []),
                                      out / "work" / "images", vertical=True)
    except Exception as e:
        print(f"::error title=插畫失敗::{e}")
        return 3

    # 4. voice
    nars = tts.narrate(sb["scenes"], out / "work" / "audio", cfg.get("voice", "en_male"),
                       cfg.get("voice_rate", "+8%"), lang="en")

    # 5. render
    render.configure("short")
    render.assemble(sb["title"], imgs, nars, out / "work", out, hook=sb.get("hook_text", ""))
    dur = render.duration(out / "video.mp4")

    # 6. upload
    desc = sb.get("youtube_description", "").strip()
    if facts and sb.get("sources"):
        desc += "\n\nSources:\n" + "\n".join(f"- {s}" for s in sb["sources"][:3])
    desc += "\n\nVisuals and voice are AI-generated."
    entry = {"date": today, "topic": topic, "series": series or sb.get("series", ""), "title": sb["youtube_title"],
             "duration": round(dur, 1), "video_id": "", "privacy": ""}
    if not args.no_upload and cfg.get("upload", True) and youtube.configured():
        try:
            v = youtube.upload(out / "video.mp4", sb["youtube_title"], desc, sb.get("tags", []),
                               category=str(cfg.get("category", "27")), privacy=cfg.get("privacy", "private"),
                               made_for_kids=bool(cfg.get("made_for_kids", False)))
            entry.update(video_id=v["id"], privacy=v["status"]["privacyStatus"])
            if auto_publish and entry["privacy"] != "public":
                time_mod = __import__("time")
                time_mod.sleep(15)  # give YouTube a moment to register the upload
                entry["privacy"] = publish_video(v["id"])
        except Exception as e:
            print(f"::warning title=YouTube 上傳失敗::{e}")
    else:
        print("[YouTube] 未設定授權或已關閉上傳，只產生影片")

    history.append(entry)
    _save(CH / "history.json", history)
    _save(CH / "queue.json", queue)
    (out / "youtube.txt").write_text(f"{sb['youtube_title']}\n\n{desc}\n\nTags: {', '.join(sb.get('tags', []))}\n",
                                     encoding="utf-8")
    (out / "meta.json").write_text(json.dumps({**entry, "youtube_description": desc, "tags": sb.get("tags", []),
                                               "hook": sb.get("hook_text", ""), "scenes": len(sb["scenes"])},
                                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 完成：{sb['youtube_title']}（{dur:.1f} 秒）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
