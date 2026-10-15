"""Assemble the video with ffmpeg: Ken Burns motion per scene, narration, burned-in subtitles, title card."""

from __future__ import annotations

import subprocess
from pathlib import Path

W, H, FPS = 1920, 1080, 30
LEAD, TAIL = 0.35, 0.45   # silence before / after each scene's narration
TITLE_DUR = 3.0
FONT = "Noto Sans CJK TC"


def _run(args: list[str]) -> None:
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 失敗：{' '.join(args[:6])}...\n{r.stderr[-1500:]}")


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out or 0)


def _motion(i: int, n: int) -> tuple[str, str, str]:
    """Return zoompan (z, x, y) expressions; cycle through 4 camera moves."""
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    kind = i % 4
    if kind == 0:   # slow zoom in
        return f"1+0.12*on/{n}", cx, cy
    if kind == 1:   # pan left -> right
        return "1.12", f"(iw-iw/zoom)*on/{n}", cy
    if kind == 2:   # slow zoom out
        return f"1.12-0.12*on/{n}", cx, cy
    return "1.12", f"(iw-iw/zoom)*(1-on/{n})", cy  # pan right -> left


def _fit(src: str = "0:v") -> str:
    return f"[{src}]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2}:(iw-ow)/2:(ih-oh)*0.35,setsar=1"


def scene_clip(img: Path, audio: Path, idx: int, out: Path) -> float:
    dur = LEAD + duration(audio) + TAIL
    frames = int(dur * FPS) + 1
    z, x, y = _motion(idx, frames)
    vf = (f"{_fit()},zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},"
          f"fade=t=in:st=0:d=0.35,fade=t=out:st={dur - 0.35:.3f}:d=0.35,format=yuv420p[v];"
          f"[1:a]adelay={int(LEAD * 1000)}:all=1,apad,atrim=0:{dur:.3f},aresample=44100[a]")
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(img), "-i", str(audio), "-filter_complex", vf,
          "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}", "-r", str(FPS),
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-ac", "2",
          str(out)])
    return dur


def title_clip(img: Path, out: Path) -> float:
    vf = (f"{_fit()},scale={W}:{H},boxblur=20:2,eq=brightness=-0.25,"
          f"fade=t=in:st=0:d=0.5,fade=t=out:st={TITLE_DUR - 0.4}:d=0.4,format=yuv420p[v]")
    _run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(img),
          "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-filter_complex", vf,
          "-map", "[v]", "-map", "1:a", "-t", f"{TITLE_DUR}", "-r", str(FPS),
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k", str(out)])
    return TITLE_DUR


# ---------------- subtitles ----------------
def _ass_time(t: float) -> str:
    cs = int(round(max(t, 0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _srt_time(t: float) -> str:
    ms = int(round(max(t, 0) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_text(s: str) -> str:
    return s.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", "\\N").strip()


def ass_header(w: int = W, h: int = H) -> str:
    sub = max(int(h * 0.068), 24)
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{FONT},{sub},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,1,0,1,{max(sub // 14, 3)},2,2,80,80,{int(h * 0.06)},1
Style: Title,{FONT},{int(h * 0.1)},&H00FFFFFF,&H00FFFFFF,&H00202020,&H80000000,1,0,0,0,100,100,4,0,1,{max(h // 180, 3)},4,5,100,100,0,1
Style: Thumb,{FONT},{int(h * 0.13)},&H0000E5FF,&H0000E5FF,&H00000000,&H90000000,1,0,0,0,100,100,2,0,1,{max(h // 90, 4)},6,2,60,60,{int(h * 0.08)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_subtitles(title: str, cue_groups: list[tuple[float, list]], ass_path: Path, srt_path: Path) -> None:
    lines = [ass_header(), f"Dialogue: 1,{_ass_time(0.3)},{_ass_time(TITLE_DUR - 0.3)},Title,,0,0,0,,"
                           f"{{\\fad(400,400)}}{_ass_text(title)}\n"]
    srt, n = [], 0
    for start, cues in cue_groups:
        for s, e, text in cues:
            if not text.strip():
                continue
            a, b = start + LEAD + s, start + LEAD + max(e, s + 0.5)
            lines.append(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Sub,,0,0,0,,{_ass_text(text)}\n")
            n += 1
            srt.append(f"{n}\n{_srt_time(a)} --> {_srt_time(b)}\n{text.strip()}\n")
    ass_path.write_text("".join(lines), encoding="utf-8")
    srt_path.write_text("\n".join(srt), encoding="utf-8")


def _esc_filter_path(p: Path) -> str:
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def thumbnail(img: Path, title: str, out: Path) -> None:
    ass = out.with_suffix(".ass")
    ass.write_text(ass_header(1280, 720) + f"Dialogue: 0,0:00:00.00,0:00:10.00,Thumb,,0,0,0,,{_ass_text(title)}\n",
                   encoding="utf-8")
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(img), "-vf",
          f"scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720:(iw-ow)/2:(ih-oh)*0.35,subtitles='{_esc_filter_path(ass)}'",
          "-frames:v", "1", "-q:v", "2", str(out)])
    ass.unlink(missing_ok=True)


def assemble(title: str, images: list[Path], narrations: list[dict], work: Path, out_dir: Path) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    clips, groups, t = [], [], 0.0
    c = work / "clip_title.mp4"
    t += title_clip(images[0], c)
    clips.append(c)
    for i, (img, nar) in enumerate(zip(images, narrations)):
        c = work / f"clip_{i:02d}.mp4"
        d = scene_clip(img, nar["audio"], i, c)
        groups.append((t, nar["cues"]))
        t += d
        clips.append(c)
        print(f"[合成] 分鏡 {i + 1}/{len(images)}")
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in clips), encoding="utf-8")
    body = work / "body.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(body)])

    ass, srt = work / "subs.ass", out_dir / "subtitles.srt"
    write_subtitles(title, groups, ass, srt)
    final = out_dir / "video.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(body), "-vf", f"subtitles='{_esc_filter_path(ass)}'",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
          "-c:a", "copy", "-movflags", "+faststart", str(final)])
    thumbnail(images[0], title, out_dir / "thumbnail.jpg")
    print(f"[合成] 完成，影片長度 {duration(final):.1f} 秒")
    return final
