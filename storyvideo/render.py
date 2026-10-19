"""Assemble the video with ffmpeg: Ken Burns motion per scene, narration, burned-in subtitles, title card."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import motion

W, H, FPS = 1920, 1080, 30
LEAD, TAIL = 0.35, 0.45   # silence before / after each scene's narration
TITLE_DUR = 3.0
FONT = "Noto Sans CJK TC"
SHORT = False             # vertical YouTube Shorts mode
FADE = 0.35
ZOOM = 0.12


def configure(fmt: str = "landscape") -> None:
    """landscape = 1920x1080 story video; short = 1080x1920 YouTube Shorts (no title card, hook overlay,
    hard cuts between shots instead of fades)."""
    global W, H, LEAD, TAIL, SHORT, FADE, ZOOM
    if fmt == "short":
        W, H, LEAD, TAIL, SHORT, FADE, ZOOM = 1080, 1920, 0.1, 0.2, True, 0.0, 0.14
    else:
        W, H, LEAD, TAIL, SHORT, FADE, ZOOM = 1920, 1080, 0.35, 0.45, False, 0.35, 0.12


def _run(args: list[str]) -> None:
    r = subprocess.run(args, capture_output=True, text=True, stdin=subprocess.DEVNULL)  # ffmpeg must not read a TTY
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
    z0 = 1 + ZOOM
    if kind == 0:   # slow zoom in
        return f"1+{ZOOM}*on/{n}", cx, cy
    if kind == 1:   # pan left -> right
        return f"{z0}", f"(iw-iw/zoom)*on/{n}", cy
    if kind == 2:   # slow zoom out
        return f"{z0}-{ZOOM}*on/{n}", cx, cy
    return f"{z0}", f"(iw-iw/zoom)*(1-on/{n})", cy  # pan right -> left


def _fit(src: str = "0:v") -> str:
    return f"[{src}]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2}:(iw-ow)/2:(ih-oh)*0.35,setsar=1"


MIN_SHOT = 2.0   # seconds; never flash a picture shorter than this


def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", w.lower())


def shot_cuts(n: int, dur: float, words: list | None = None, switch_word: str = "") -> list[float]:
    """Boundaries [0, ..., dur] for n shots in one scene clip. The picture changes exactly when the narration
    reaches `switch_word` (clip time = LEAD + word start); without it, on the word closest to an even split."""
    n = max(1, min(n, int(dur // MIN_SHOT) or 1))
    cuts = [0.0]
    timed = sorted((LEAD + w[0], _norm(w[2])) for w in (words or []))
    key = _norm(switch_word.split()[0]) if switch_word.strip() else ""
    for k in range(1, n):
        ok = [(s, w) for s, w in timed if s - cuts[-1] >= MIN_SHOT and dur - s >= MIN_SHOT * (n - k)]
        hit = [s for s, w in ok if key and w == key]
        target = dur * k / n
        cuts.append(hit[0] if hit else (min((s for s, _ in ok), key=lambda s: abs(s - target)) if ok else target))
    return cuts + [dur]


def scene_clip(img, audio: Path, idx: int, out: Path, words: list | None = None, switch_word: str = "") -> float:
    """One narrated scene. `img` is a path or a list of shot paths shown one after another (hard cuts).
    Shorts use the free depth-parallax "living photo" motion when available, else ffmpeg zoompan."""
    shots = [p for p in (img if isinstance(img, (list, tuple)) else [img]) if p]
    dur = LEAD + duration(audio) + TAIL
    cuts = shot_cuts(len(shots), dur, words, switch_word)
    shots = shots[:len(cuts) - 1]
    total = int(dur * FPS) + 1
    counts, used = [], 0
    for k, (a, b) in enumerate(zip(cuts, cuts[1:])):
        counts.append(total - used if k == len(shots) - 1 else max(int(round((b - a) * FPS)), 1))
        used += counts[-1]
    inputs, chains = list(shots), []
    if SHORT and motion.available():
        inputs = [motion.render_shot(p, frames, W, H, FPS, idx * 2 + k, out.with_name(f"{out.stem}_shot{k}.mp4"),
                                     seed=idx) for k, (p, frames) in enumerate(zip(shots, counts))]
        chains = [f"[{k}:v]setpts=PTS-STARTPTS[s{k}]" for k in range(len(inputs))]
    else:
        for k, frames in enumerate(counts):
            z, x, y = _motion(idx * 2 + k, frames)
            chains.append(f"{_fit(f'{k}:v')},zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},"
                          f"trim=end_frame={frames},setpts=PTS-STARTPTS[s{k}]")
    n = len(inputs)
    fades = f",fade=t=in:st=0:d={FADE},fade=t=out:st={dur - FADE:.3f}:d={FADE}" if FADE > 0 else ""
    vf = (";".join(chains) + ";" + "".join(f"[s{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0{fades},"
          f"format=yuv420p[v];[{n}:a]adelay={int(LEAD * 1000)}:all=1,apad,atrim=0:{dur:.3f},aresample=44100[a]")
    args = ["ffmpeg", "-y", "-v", "error"]
    for p in inputs:
        args += ["-i", str(p)]
    _run(args + ["-i", str(audio), "-filter_complex", vf,
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


def ass_header(w: int | None = None, h: int | None = None) -> str:
    w, h = w or W, h or H
    sub = max(int(h * 0.068), 24)
    cap = int(w * 0.095)  # Shorts caption size relative to width
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{FONT},{sub},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,1,0,1,{max(sub // 14, 3)},2,2,80,80,{int(h * 0.06)},1
Style: Title,{FONT},{int(h * 0.1)},&H00FFFFFF,&H00FFFFFF,&H00202020,&H80000000,1,0,0,0,100,100,4,0,1,{max(h // 180, 3)},4,5,100,100,0,1
Style: Thumb,{FONT},{int(h * 0.13)},&H0000E5FF,&H0000E5FF,&H00000000,&H90000000,1,0,0,0,100,100,2,0,1,{max(h // 90, 4)},6,2,60,60,{int(h * 0.08)},1
Style: Cap,{FONT},{cap},&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,1,0,0,0,100,100,1,0,1,{max(cap // 9, 4)},3,5,40,40,0,1
Style: Hook,{FONT},{int(w * 0.082)},&H0000E5FF,&H0000E5FF,&H00000000,&HAA000000,1,0,0,0,100,100,1,0,1,{max(w // 120, 5)},4,5,50,50,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def layout_cues(cue_groups: list[tuple[float, list]]) -> list[tuple[float, float, str]]:
    """Absolute, non-overlapping subtitle cues (overlap makes libass stack lines -> jumping text)."""
    cues = []
    for start, group in cue_groups:
        for s, e, text in group:
            if text.strip():
                cues.append([start + LEAD + s, start + LEAD + max(e, s + 0.5), text.strip()])
    cues.sort(key=lambda c: c[0])
    for a, b in zip(cues, cues[1:]):
        if a[1] > b[0] - 0.02:
            a[1] = max(a[0] + 0.2, b[0] - 0.02)
    return [tuple(c) for c in cues]


HIGHLIGHT, NORMAL = "{\\c&H00E5FF&}", "{\\c&HFFFFFF&}"   # spoken word in yellow, the rest white


def word_slots(word_groups: list[tuple[float, list]] | None) -> list[tuple[float, float, str]]:
    """Absolute (start, end, CAPTION WORD) for every displayed English word, in caption order."""
    from .subtitles import _en_clean
    out = []
    for start, words in word_groups or []:
        for s, e, w in words or []:
            c = _en_clean(w).upper()
            if c:
                out.append((start + LEAD + s, start + LEAD + e, c))
    return out


def highlight_events(a: float, b: float, text: str, slots: list, j: int) -> tuple[list[tuple[float, float, str]], int]:
    """Split caption [a, b) into one event per spoken word with that word highlighted.
    Returns (events, next slot index); no events if the words cannot be matched to the caption."""
    toks = text.split()
    k = len(toks)
    for start in range(j, min(j + 4, len(slots) - k + 1)):  # small window to resync after dropped words
        if [s[2] for s in slots[start:start + k]] == toks:
            cand = slots[start:start + k]
            bounds = [a] + [min(max(cand[m][0], a), b) for m in range(1, k)] + [b]
            bounds = [round(x, 2) for x in bounds]
            for m in range(1, len(bounds)):
                bounds[m] = max(bounds[m], bounds[m - 1])
            events = []
            for m in range(k):
                if bounds[m + 1] - bounds[m] >= 0.01:
                    words = " ".join(f"{HIGHLIGHT}{_ass_text(t)}{NORMAL}" if q == m else _ass_text(t)
                                     for q, t in enumerate(toks))
                    events.append((bounds[m], bounds[m + 1], words))
            return events, start + k
    return [], j


def write_subtitles(title: str, cue_groups: list[tuple[float, list]], ass_path: Path, srt_path: Path,
                    hook: str = "", word_groups: list[tuple[float, list]] | None = None) -> None:
    slots = word_slots(word_groups) if SHORT else []
    if SHORT:
        anchor = f"{{\\an5\\pos({W // 2},{int(H * 0.70)})"
        style, pos = "Cap", f"{anchor}\\fscx92\\fscy92\\t(0,90,\\fscx100\\fscy100)}}"
        lines = [ass_header()]
        if hook:
            lines.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(2.6)},Hook,,0,0,0,,"
                         f"{{\\an5\\q0\\pos({W // 2},{int(H * 0.17)})\\fad(0,300)}}{_wrap(hook.upper(), 14)}\n")
    else:
        style, pos = "Sub", f"{{\\an2\\pos({W // 2},{H - int(H * 0.06)})}}"  # fixed baseline: never moves
        lines = [ass_header(), f"Dialogue: 1,{_ass_time(0.3)},{_ass_time(TITLE_DUR - 0.3)},Title,,0,0,0,,"
                               f"{{\\fad(400,400)}}{_ass_text(title)}\n"]
    srt, j = [], 0
    for n, (a, b, text) in enumerate(layout_cues(cue_groups), 1):
        events, j = highlight_events(a, b, text, slots, j) if slots else ([], j)
        if events:
            for m, (ea, eb, words) in enumerate(events):
                lead = pos if m == 0 else anchor + "}"   # pop-in only when the caption first appears
                lines.append(f"Dialogue: 0,{_ass_time(ea)},{_ass_time(eb)},{style},,0,0,0,,{lead}{words}\n")
        else:
            lines.append(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},{style},,0,0,0,,{pos}{_ass_text(text)}\n")
        srt.append(f"{n}\n{_srt_time(a)} --> {_srt_time(b)}\n{text}\n")
    ass_path.write_text("".join(lines), encoding="utf-8")
    srt_path.write_text("\n".join(srt), encoding="utf-8")


def _wrap(text: str, width: int) -> str:
    """Balanced manual line breaks for the hook title (libass wrapping is disabled globally)."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\\N".join(_ass_text(l) for l in lines)


def _esc_filter_path(p: Path) -> str:
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _thumb_ass(title: str, tw: int, th: int, size: int) -> str:
    # libass wrapping is disabled (WrapStyle 2), so break the vertical cover title by hand
    text = _wrap(title.upper(), 11) if SHORT else _ass_text(title)
    return ass_header(tw, th) + f"Dialogue: 0,0:00:00.00,0:00:10.00,Thumb,,0,0,0,,{{\\fs{size}}}{text}\n"


def text_touches_edges(ass: Path, w: int, h: int, edge: int = 16) -> bool:
    """Render only the subtitle on a black canvas; lit pixels near the frame edges mean the title is cut off."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=black:s={w}x{h}:d=1",
                          "-vf", f"subtitles='{_esc_filter_path(ass)}'", "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True,
                         stdin=subprocess.DEVNULL).stdout
    if len(raw) < w * h:
        return False
    if max(raw[:w * edge]) > 60:  # top rows
        return True
    return any(max(raw[y * w:y * w + edge]) > 60 or max(raw[(y + 1) * w - edge:(y + 1) * w]) > 60 for y in range(h))


def thumbnail(img: Path, title: str, out: Path) -> int:
    """Cover image with the hook title; shrinks the title until it fits inside the frame. Returns the font size."""
    tw, th = (720, 1280) if SHORT else (1280, 720)
    size = int(tw * 0.12) if SHORT else int(th * 0.13)
    ass = out.with_suffix(".ass")
    for attempt in range(10):
        ass.write_text(_thumb_ass(title, tw, th, size), encoding="utf-8")
        if not text_touches_edges(ass, tw, th):
            break
        if attempt == 9:
            print(f"::warning title=縮圖標題太長::「{title}」縮到最小字還是超出畫面")
            break
        size = int(size * 0.88)
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(img), "-vf",
          f"scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th}:(iw-ow)/2:(ih-oh)*0.35,subtitles='{_esc_filter_path(ass)}'",
          "-frames:v", "1", "-q:v", "2", str(out)])
    ass.unlink(missing_ok=True)
    return size


def assemble(title: str, images: list, narrations: list[dict], work: Path, out_dir: Path,
             hook: str = "", switch_words: list[str] | None = None) -> Path:
    """images[i] is one path or a list of shot paths for scene i; switch_words[i] = narration word where the
    second shot starts."""
    work.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    clips, groups, word_groups, t = [], [], [], 0.0
    first = images[0][0] if isinstance(images[0], (list, tuple)) else images[0]
    if not SHORT:
        c = work / "clip_title.mp4"
        t += title_clip(first, c)
        clips.append(c)
    for i, (img, nar) in enumerate(zip(images, narrations)):
        c = work / f"clip_{i:02d}.mp4"
        sw = (switch_words or [])[i] if i < len(switch_words or []) else ""
        d = scene_clip(img, nar["audio"], i, c, nar.get("words"), sw or "")
        groups.append((t, nar["cues"]))
        word_groups.append((t, nar.get("words") or []))
        t += d
        clips.append(c)
        print(f"[合成] 分鏡 {i + 1}/{len(images)}")
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in clips), encoding="utf-8")
    body = work / "body.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(body)])

    ass, srt = work / "subs.ass", out_dir / "subtitles.srt"
    write_subtitles(title, groups, ass, srt, hook, word_groups)
    final = out_dir / "video.mp4"
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(body), "-vf", f"subtitles='{_esc_filter_path(ass)}'",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
          "-c:a", "copy", "-movflags", "+faststart", str(final)])
    thumbnail(first, hook or title, out_dir / "thumbnail.jpg")
    print(f"[合成] 完成，影片長度 {duration(final):.1f} 秒")
    return final
