"""CLI: python -m storyvideo --story-file story.txt [--title ...] [--length short|medium|long] [--voice female|male]"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import images, render, storyboard, tts


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="storyvideo", description="把故事變成 AI 插畫旁白影片")
    p.add_argument("--story-file", required=True)
    p.add_argument("--title", default="")
    p.add_argument("--length", default="medium", choices=list(storyboard.LENGTHS))
    p.add_argument("--voice", default="female", choices=list(tts.VOICES))
    p.add_argument("--faithful", action="store_true", help="盡量保留原文，不改寫")
    p.add_argument("--style", default=os.environ.get("IMAGE_STYLE", storyboard.DEFAULT_STYLE))
    p.add_argument("--out", default="out")
    args = p.parse_args(argv)

    story = Path(args.story_file).read_text(encoding="utf-8").strip()
    if len(story) < 10:
        print("故事太短了，至少寫 10 個字喔")
        return 2
    out, work = Path(args.out), Path(args.out) / "work"
    out.mkdir(parents=True, exist_ok=True)

    print("== 1/4 AI 撰寫分鏡腳本 ==")
    sb = storyboard.generate_storyboard(story, args.title.strip(), args.length, args.faithful)
    (out / "script.json").write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"標題：{sb['title']}｜{len(sb['scenes'])} 個分鏡｜模型 {sb.get('model')}")

    print("== 2/4 AI 繪製插畫 ==")
    imgs = images.generate_images(sb["scenes"], args.style, sb.get("characters", ""), work / "images")

    print("== 3/4 旁白配音 ==")
    nars = tts.narrate(sb["scenes"], work / "audio", args.voice)

    print("== 4/4 合成影片 ==")
    render.assemble(sb["title"], imgs, nars, work, out)

    tags = ", ".join(sb.get("tags", []))
    (out / "youtube.txt").write_text(
        f"【標題】\n{sb.get('youtube_title') or sb['title']}\n\n【說明】\n{sb.get('youtube_description', '')}\n\n"
        f"【標籤】\n{tags}\n", encoding="utf-8")
    (out / "meta.json").write_text(json.dumps({
        "title": sb["title"], "youtube_title": sb.get("youtube_title", ""),
        "youtube_description": sb.get("youtube_description", ""), "tags": sb.get("tags", []),
        "scenes": len(sb["scenes"]), "duration": round(render.duration(out / "video.mp4"), 1),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("✅ 完成：", out / "video.mp4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
