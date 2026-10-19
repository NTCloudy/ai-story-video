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


TREND_QUERIES = ["what if science", "human body facts", "space facts", "history mysteries", "animal facts",
                 "scary facts", "ocean facts", "science facts"]


def load_trends(cfg: dict) -> list[dict]:
    """Most-viewed niche Shorts on YouTube, cached for 3 days (search costs 100 quota units per query)."""
    path = CH / "trends.json"
    cache = _load(path, {})
    fresh = cache.get("fetched") and (datetime.now(TZ) - datetime.fromisoformat(cache["fetched"])).days < 3
    if fresh or not youtube.configured():
        return cache.get("items", [])
    try:
        items = youtube.trending_shorts(cfg.get("trend_queries", TREND_QUERIES))
        _save(path, {"fetched": datetime.now(TZ).isoformat(), "items": items[:150]})
        print(f"[Trends] {len(items)} trending Shorts collected")
        return items
    except Exception as e:
        print(f"[Trends] skipped: {e}")
        return cache.get("items", [])


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
    p.add_argument("--dry-run", action="store_true", help="test render: no upload, channel files untouched")
    p.add_argument("--out", default="out")
    args = p.parse_args(argv)
    if args.dry_run:
        args.no_upload = True

    cfg = _load(CH / "channel.yaml", {})
    history = _load(CH / "history.json", [])
    queue = _load(CH / "queue.json", [])
    today = datetime.now(TZ).date().isoformat()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    auto_publish = bool(cfg.get("auto_publish", False)) and youtube.configured() and not args.no_upload
    if auto_publish and publish_pending(history):
        _save(CH / "history.json", history)

    # refresh view counts for our previous Shorts (cheap: 1 quota unit)
    if youtube.configured() and history and not args.dry_run:
        try:
            stats = youtube.video_stats([h["video_id"] for h in history if h.get("video_id")])
            for h in history:
                if h.get("video_id") in stats:
                    h["views"] = stats[h["video_id"]]["views"]
                    h["likes"] = stats[h["video_id"]]["likes"]
            _save(CH / "history.json", history)
        except Exception as e:
            print(f"[Stats] skipped: {e}")

    per_day = int(cfg.get("shorts_per_day", 1))
    if not args.force and not args.topic and sum(1 for h in history if h.get("date") == today) >= per_day:
        print(f"今天（{today}）已經做過 {per_day} 支 Shorts，略過。")
        (out / "SKIPPED").write_text("already done today")
        return 0
    if cfg.get("paused") and not (args.force or args.topic):
        print("頻道已暫停自動產生（channel.yaml: paused: true）")
        (out / "SKIPPED").write_text("paused")
        return 0

    # 1. topic (never repeat a previous Short)
    series, concept, topic = "", "", ""
    if args.topic.strip():
        dup = shorts.find_duplicate(args.topic.strip(), "", history)
        if dup:
            print(f"::error title=主題重複::「{args.topic.strip()}」和先前的影片「{dup}」重複，請換一個主題")
            return 4
        topic = args.topic.strip()
    while not topic and queue:
        item = queue.pop(0)
        cand, ser = (item.get("topic", ""), item.get("series", "")) if isinstance(item, dict) else (str(item), "")
        dup = shorts.find_duplicate(cand, "", history)
        if dup:
            print(f"::warning title=排程主題重複，已略過::「{cand}」≈「{dup}」")
            continue
        topic, series = cand, ser
    if not topic:
        t = shorts.pick_topic(history, cfg.get("series"), trends=load_trends(cfg))
        topic, series, concept = t["topic"], t["series"], t.get("concept", "")
    print(f"== 主題：{topic}（{series or '自訂'}）==")

    # 2. research + script
    facts = shorts.research(topic)
    sb = shorts.write_short(topic, facts, series)
    (out / "script.json").write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"標題：{sb['youtube_title']}｜{len(sb['scenes'])} 個分鏡｜模型 {sb['model']}")

    # 3. images (vertical): two shots per scene so the picture changes every few seconds
    shots_per_scene = max(1, int(cfg.get("shots_per_scene", 2)))
    shot_list, owner, optional = [], [], set()
    for si, sc in enumerate(sb["scenes"]):
        prompts = [sc["image_prompt"]] + [p for p in [sc.get("image_prompt_2", "")] if p.strip()][:shots_per_scene - 1]
        for k, prompt in enumerate(prompts):
            if k:
                optional.add(len(shot_list))
            shot_list.append({"image_prompt": prompt, "characters": []})
            owner.append(si)
    try:
        # no character reference sheets for Shorts: they made every shot the same front-facing pose
        flat = images.generate_images(shot_list, cfg.get("style", shorts.SHORT_STYLE), [],
                                      out / "work" / "images", vertical=True, optional=optional)
    except Exception as e:
        print(f"::error title=插畫失敗::{e}")
        return 3
    imgs = [[p for p, o in zip(flat, owner) if o == si and p] for si in range(len(sb["scenes"]))]
    print(f"[插畫] {sum(len(x) for x in imgs)} 張（{len(sb['scenes'])} 個分鏡）")

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
    entry = {"date": today, "topic": topic, "concept": concept, "series": series or sb.get("series", ""),
             "title": sb["youtube_title"],
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

    if not args.dry_run:
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
