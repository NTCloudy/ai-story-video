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
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import images, render, shorts, tts, youtube

CH = Path("channel")


class CannotGenerate(RuntimeError):
    """A step could not be done properly; stop with a warning instead of publishing a worse Short."""

TZ = ZoneInfo("Asia/Taipei")


def _load(path: Path, default):
    if path.exists():
        text = path.read_text(encoding="utf-8")
        return (yaml.safe_load(text) if path.suffix in (".yaml", ".yml") else json.loads(text)) or default
    return default


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# Broad, theme-agnostic searches: we want whatever kind of fact Short is hot right now, not just our old niches.
TREND_QUERIES = ["facts", "did you know", "fun facts", "interesting facts", "mind blowing facts", "weird facts",
                 "animal facts", "science facts", "history facts", "psychology facts", "food facts",
                 "geography facts", "nature facts", "space facts", "human body facts", "how it works"]


def load_trends(cfg: dict) -> tuple[list[dict], list[dict]]:
    """(most-viewed recent fact Shorts on YouTube, their themes ranked by popularity), cached for 3 days
    (search costs 100 quota units per query; theme labelling is one Gemini call)."""
    path = CH / "trends.json"
    cache = _load(path, {})
    queries = cfg.get("trend_queries", TREND_QUERIES)
    fresh = (cache.get("fetched") and cache.get("queries") == queries
             and (datetime.now(TZ) - datetime.fromisoformat(cache["fetched"])).days < 3)
    items = cache.get("items", [])
    if not fresh and youtube.configured():
        try:
            items = youtube.trending_shorts(queries)[:150]
            cache = {"fetched": datetime.now(TZ).isoformat(), "queries": queries, "items": items}
            print(f"[Trends] {len(items)} trending Shorts collected")
        except Exception as e:
            print(f"[Trends] skipped: {e}")
    if items and not cache.get("themes"):
        try:
            cache["themes"] = shorts.label_themes(items)
            cache.setdefault("items", items)
            _save(path, cache)
            print("[Trends] hot themes: " + ", ".join(f"{t['theme']} ({t['median_views']:,})" for t in cache["themes"][:10]))
        except Exception as e:
            print(f"[Trends] theme labelling skipped: {e}")
    return items, cache.get("themes", [])


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


def save_assets(out: Path, imgs: list, nars: list[dict], sb: dict) -> None:
    """Raw materials (pictures, narration audio + word timings) so a Short can be re-rendered later
    without spending the daily illustration quota again."""
    import zipfile
    try:
        with zipfile.ZipFile(out / "assets.zip", "w", zipfile.ZIP_DEFLATED) as z:
            scenes = []
            for i, (shots, n) in enumerate(zip(imgs, nars)):
                names = []
                for p in shots if isinstance(shots, (list, tuple)) else [shots]:
                    z.write(p, f"images/{Path(p).name}")
                    names.append(Path(p).name)
                z.write(n["audio"], f"audio/{Path(n['audio']).name}")
                sc = sb["scenes"][i]
                prompts = [sc.get("image_prompt", "")] + ([sc["image_prompt_2"]] if sc.get("image_prompt_2") else [])
                scenes.append({"images": names, "prompts": prompts[:len(names)], "audio": Path(n["audio"]).name,
                               "cues": n["cues"],
                               "words": n.get("words") or [],
                               "switch_word": sb["scenes"][i].get("switch_word") or ""})
            z.writestr("render.json", json.dumps({"title": sb["title"], "hook": sb.get("hook_text", ""),
                                                  "scenes": scenes}, ensure_ascii=False, indent=1))
    except Exception as e:
        print(f"[素材] assets.zip skipped: {e}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="storyvideo.daily")
    p.add_argument("--topic", default="")
    p.add_argument("--concept", default="", help="1-4 words naming the exact phenomenon of --topic")
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

    # GitHub runs scheduled jobs hours late, so the workflow fires hourly and the job decides: automatic runs
    # only make the day's Short from `publish_after` (Taiwan time) on, never in the middle of the night.
    after = str(cfg.get("publish_after", "07:30"))
    if (os.environ.get("GITHUB_EVENT_NAME") == "schedule" and not (args.force or args.topic)
            and datetime.now(TZ).strftime("%H:%M") < after
            and not any(h.get("date") == today for h in history)):
        print(f"還沒到 {after}（台灣時間），等下一次排程。")
        (out / "SKIPPED").write_text("too early")
        return 0

    auto_publish = bool(cfg.get("auto_publish", False)) and youtube.configured() and not args.no_upload
    if auto_publish and publish_pending(history):
        _save(CH / "history.json", history)

    per_day = int(cfg.get("shorts_per_day", 1))
    done_today = not args.force and not args.topic and sum(1 for h in history if h.get("date") == today) >= per_day
    if done_today and datetime.now(TZ).hour % 4:
        # hourly schedule: refresh stats only every ~4 hours once today's Short exists (fewer bot commits)
        print(f"今天（{today}）已經做過 {per_day} 支 Shorts，略過。")
        (out / "SKIPPED").write_text("already done today")
        return 0

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
        # retention metrics for the monthly theme comparison (YouTube Analytics lags 1-2 days)
        try:
            an = youtube.video_analytics([h["video_id"] for h in history if h.get("video_id")])
            for h in history:
                a = an.get(h.get("video_id"))
                if a:
                    h.update(engaged_views=a.get("engagedViews"), avg_view_pct=round(a.get("averageViewPercentage", 0), 1),
                             avg_view_sec=a.get("averageViewDuration"), subs_gained=a.get("subscribersGained"),
                             shares=a.get("shares"))
            _save(CH / "history.json", history)
        except Exception as e:
            print(f"[Analytics] skipped: {e}")

    if done_today:
        print(f"今天（{today}）已經做過 {per_day} 支 Shorts，略過。")
        (out / "SKIPPED").write_text("already done today")
        return 0
    if cfg.get("paused") and not (args.force or args.topic):
        print("頻道已暫停自動產生（channel.yaml: paused: true）")
        (out / "SKIPPED").write_text("paused")
        return 0

    # never force a bad Short out: anything that cannot be done properly stops the run with a warning, and the
    # next hourly run tries again (at most `max_attempts_per_day` automatic tries)
    attempts = _load(CH / "attempts.json", {})
    tries = int(attempts.get(today, 0))
    max_tries = int(cfg.get("max_attempts_per_day", 3))
    automatic = not (args.force or args.topic)
    if automatic and tries >= max_tries:
        print(f"今天已經嘗試 {tries} 次都沒成功，今天不再自動重試。")
        (out / "SKIPPED").write_text("gave up today")
        return 0
    try:
        return make_short(args, cfg, history, queue, today, out, auto_publish)
    except Exception as e:
        reason = str(e) if isinstance(e, CannotGenerate) else f"{type(e).__name__}: {e}"
        if not args.dry_run:
            _save(CH / "attempts.json", {today: tries + 1})
        last = automatic and tries + 1 >= max_tries
        note = "今天不再自動重試，可以到 GitHub Actions 手動重跑" if last else "下一次排程會再試"
        print(f"::warning title=今天的 Short 沒做出來（{note}）::{reason[:900]}")
        (out / "GAVE_UP").write_text(f"{reason}\n\n（第 {tries + 1} 次嘗試；{note}）", encoding="utf-8")
        for f in ("video.mp4", "meta.json"):  # nothing half-made may be released or cross-posted
            (out / f).unlink(missing_ok=True)
        return 0


def make_short(args, cfg: dict, history: list, queue: list, today: str, out: Path, auto_publish: bool) -> int:
    """Topic -> research -> script -> check -> images -> voice -> render -> upload.
    Raises CannotGenerate instead of falling back to a worse result."""
    # 1. topic (never repeat a previous Short)
    series, concept, topic = "", "", ""
    if args.topic.strip():
        dup = shorts.find_duplicate(args.topic.strip(), "", history)
        if dup:
            print(f"::error title=主題重複::「{args.topic.strip()}」和先前的影片「{dup}」重複，請換一個主題")
            return 4
        topic = args.topic.strip()
        concept = args.concept.strip()
    while not topic and queue:
        item = queue.pop(0)
        cand, ser = (item.get("topic", ""), item.get("series", "")) if isinstance(item, dict) else (str(item), "")
        dup = shorts.find_duplicate(cand, "", history)
        if dup:
            print(f"::warning title=排程主題重複，已略過::「{cand}」≈「{dup}」")
            continue
        topic, series = cand, ser
    if not topic:
        trends, themes = load_trends(cfg)
        use_themes = cfg.get("topic_mode", "trends") == "trends"
        t = shorts.pick_topic(history, cfg.get("series"), trends=trends, themes=themes if use_themes else None,
                              cooldown=int(cfg.get("theme_cooldown_days", 7)))
        topic, series, concept = t["topic"], t["series"], t.get("concept", "")
    print(f"== 主題：{topic}（{series or '自訂'}）==")

    # 2. research + script, then make sure the script is about the topic and the title matches the script
    facts = shorts.research(topic, concept)
    if not facts:
        raise CannotGenerate("查不到這個主題的可靠資料，不憑空寫腳本")
    feedback = ""
    for attempt in range(3):
        sb = shorts.write_short(topic, facts, series, concept, feedback)
        ok, feedback = shorts.check_consistency(sb, topic, concept)
        if ok:
            break
        print(f"::warning title=標題或內容不符，重寫（第 {attempt + 1} 次）::{sb.get('youtube_title', '')}: {feedback}")
    else:
        raise CannotGenerate(f"重寫 3 次標題和內容還是對不上：{feedback}")
    (out / "script.json").write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"標題：{sb['youtube_title']}｜{len(sb['scenes'])} 個分鏡｜模型 {sb['model']}")

    # 3. images (vertical): one per scene, plus a second one only where the narration moves to something new
    max_shots = max(1, int(cfg.get("shots_per_scene", 2)))
    shot_list, owner, optional = [], [], set()
    for si, sc in enumerate(sb["scenes"]):
        prompts = [sc["image_prompt"]] + [p for p in [sc.get("image_prompt_2") or ""] if p.strip()][:max_shots - 1]
        for k, prompt in enumerate(prompts):
            if k:
                optional.add(len(shot_list))
            shot_list.append({"image_prompt": prompt, "characters": []})
            owner.append(si)
    try:
        # no character reference sheets for Shorts: they made every shot the same front-facing pose
        flat = images.generate_images(shot_list, cfg.get("style", shorts.SHORT_STYLE), [],
                                      out / "work" / "images", vertical=True, optional=optional,
                                      check=bool(cfg.get("image_check", True)))
    except Exception as e:
        raise CannotGenerate(f"插畫失敗：{e}") from e
    imgs = [[p for p, o in zip(flat, owner) if o == si and p] for si in range(len(sb["scenes"]))]
    print(f"[插畫] {sum(len(x) for x in imgs)} 張（{len(sb['scenes'])} 個分鏡）")

    # 4. voice
    nars = tts.narrate(sb["scenes"], out / "work" / "audio", cfg.get("voice", "en_male"),
                       cfg.get("voice_rate", "+8%"), lang="en", allow_backup=bool(cfg.get("allow_backup_voice", False)))

    # 5. render
    render.configure("short")
    render.assemble(sb["title"], imgs, nars, out / "work", out, hook=sb.get("hook_text", ""),
                    switch_words=[sc.get("switch_word") or "" for sc in sb["scenes"]])
    dur = render.duration(out / "video.mp4")
    save_assets(out, imgs, nars, sb)

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
            raise CannotGenerate(f"YouTube 上傳失敗：{e}") from e
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
