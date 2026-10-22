"""Cross-post Shorts to a Facebook Page and to Instagram as Reels (Meta Graph API).

One-time setup (Meta developer app "Cloud Auto Poster"):
  Graph API Explorer -> permissions pages_show_list, pages_read_engagement, pages_manage_posts,
  business_management, instagram_basic, instagram_content_publish -> Generate Access Token ->
  Access Token Debugger -> "Extend Access Token" (60-day user token) -> GET /me/accounts returns a
  Page token that never expires.
Secrets used by the workflows: META_PAGE_ID, META_PAGE_TOKEN, IG_USER_ID.
Meta still asks the person to re-authorise the app every 90 days ("data access expiration"):
`check` fails two weeks before that, so GitHub emails a reminder.

python -m storyvideo.meta post --video out/video.mp4 --meta out/meta.json [--thumb out/thumbnail.jpg] [--cover-url URL]
python -m storyvideo.meta catchup [--repo OWNER/REPO]   # cross-post Shorts in channel/history.json not yet on FB/IG
python -m storyvideo.meta check                         # token health
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import requests

GRAPH_VERSION = "v26.0"
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"
HISTORY = Path("channel/history.json")
PLATFORMS = {"fb": "Facebook", "ig": "Instagram"}
AI_NOTE = "🤖 Visuals and voice are AI-generated."
FOLLOW_CTA = "☁️ Follow for one mind-blowing fact every day!"
SERIES_EMOJI = {"space": "🚀", "psychology": "🧠", "brain": "🧠", "body": "🫀", "human body": "🫀",
                "history": "🏛️", "what if": "🤔", "animals": "🐾", "ocean": "🌊", "science": "🔬"}
EXTRA_TAGS = ["#didyouknow", "#sciencefacts", "#funfacts"]
MAX_TAGS = 8


def configured() -> bool:
    return all(os.environ.get(k) for k in ("META_PAGE_ID", "META_PAGE_TOKEN", "IG_USER_ID"))


def _token() -> str:
    return os.environ["META_PAGE_TOKEN"]


def _check(r: requests.Response) -> dict:
    try:
        data = r.json()
    except ValueError:
        data = {"raw": r.text[:300]}
    if r.status_code >= 400 or (isinstance(data, dict) and "error" in data):
        err = data.get("error", data) if isinstance(data, dict) else {"raw": str(data)}
        msg = (err.get("error_user_msg") or err.get("message") or "") if isinstance(err, dict) else str(err)
        raise RuntimeError(f"Meta API {r.status_code}: {msg} | {json.dumps(err, ensure_ascii=False)[:400]}")
    return data


def api(method: str, path: str, **params) -> dict:
    params["access_token"] = _token()
    url = f"{GRAPH}/{path.lstrip('/')}"
    if method == "GET":
        return _check(requests.get(url, params=params, timeout=60))
    return _check(requests.post(url, data=params, timeout=120))


def _upload_binary(url: str, video: Path) -> None:
    with open(video, "rb") as f:
        _check(requests.post(url, data=f, timeout=900, headers={
            "Authorization": f"OAuth {_token()}", "offset": "0", "file_size": str(video.stat().st_size)}))


# ---------------------------------------------------------------- caption

def clean_title(title: str) -> str:
    return re.sub(r"\s*#shorts\b", "", title or "", flags=re.I).strip()


def caption(meta: dict) -> str:
    """Reels caption from the YouTube metadata: title, summary, CTA, sources, AI disclosure, hashtags."""
    title = clean_title(meta.get("title", ""))
    emoji = SERIES_EMOJI.get((meta.get("series") or "").strip().lower(), "☁️")
    summary, sources = [], ""
    for para in (p.strip() for p in (meta.get("youtube_description") or "").split("\n\n")):
        if not para:
            continue
        if para.lower().startswith("sources:"):
            sources = para
        elif "ai-generated" not in para.lower():
            summary.append(para)
    text = "\n\n".join(summary)
    tags = [t for t in re.findall(r"#\w+", text) if t.lower() != "#shorts"]
    text = re.sub(r"[ \t]*#\w+", "", text).strip()
    seen, uniq = set(), []
    for t in tags + EXTRA_TAGS:
        if t.lower() not in seen:
            seen.add(t.lower())
            uniq.append(t)
    parts = [f"{title} {emoji}", text, FOLLOW_CTA, sources, AI_NOTE, " ".join(uniq[:MAX_TAGS])]
    return "\n\n".join(p for p in parts if p)[:2200]


# ---------------------------------------------------------------- publishing

def _wait_ig(container: str, timeout: int = 900) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = api("GET", container, fields="status_code,status")
        code = s.get("status_code", "")
        if code in ("FINISHED", "PUBLISHED", "ERROR", "EXPIRED"):
            if code in ("ERROR", "EXPIRED"):
                print(f"[IG] processing {code}: {s.get('status', '')}")
            return code
        time.sleep(6)
    return "TIMEOUT"


def publish_instagram(video: Path | None, text: str, cover_url: str = "", video_url: str = "") -> dict:
    """Instagram Reel. Preferred: Meta fetches `video_url` (the public GitHub Release asset; redirects are fine).
    Fallback: resumable binary upload. rupload answers 400 to Page tokens even when the upload worked, so the
    container status decides. A custom cover that fails processing is dropped and the Reel is retried without it."""
    ig = os.environ["IG_USER_ID"]
    status, container = "", ""
    for cover in ([cover_url, ""] if cover_url else [""]):
        params = dict(media_type="REELS", caption=text, share_to_feed="true")
        if cover:
            params["cover_url"] = cover
        if video_url:
            params["video_url"] = video_url
        else:
            params["upload_type"] = "resumable"
        c = api("POST", f"{ig}/media", **params)
        container = c["id"]
        if not video_url:
            if video is None:
                raise RuntimeError("Instagram needs a video file or a public video URL")
            try:
                _upload_binary(c.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{GRAPH_VERSION}/{container}",
                               video)
            except RuntimeError as e:
                print(f"[IG] upload response: {str(e)[:160]} (checking the container status anyway)")
        status = _wait_ig(container)
        if status == "FINISHED":
            break
        if cover:
            print("[IG] retrying without the custom cover")
    if status != "FINISHED":
        raise RuntimeError(f"Instagram processing failed ({status})")
    media = api("POST", f"{ig}/media_publish", creation_id=container)
    info = _get_soon(media["id"], fields="permalink")
    return {"id": media["id"], "url": info.get("permalink", "")}


def _get_soon(path: str, wait: int = 90, **params) -> dict:
    """GET an object that was just created: Meta can answer "does not exist" for a few seconds."""
    deadline = time.time() + wait
    while True:
        try:
            return api("GET", path, **params)
        except RuntimeError as e:
            if "does not exist" not in str(e) or time.time() > deadline:
                raise
            time.sleep(5)


def _wait_fb(video_id: str, timeout: int = 900) -> str:
    deadline, last = time.time() + timeout, ""
    while time.time() < deadline:
        st = _get_soon(video_id, fields="status").get("status", {})
        vs = st.get("video_status", "")
        pub = (st.get("publishing_phase") or {}).get("status", "")
        proc = (st.get("processing_phase") or {}).get("status", "")
        last = f"{vs}/{proc}/{pub}"
        if vs == "error" or proc == "error":
            raise RuntimeError(f"Facebook processing failed: {json.dumps(st, ensure_ascii=False)[:400]}")
        if pub == "complete" or (vs == "ready" and pub in ("", "complete")):
            return last
        time.sleep(6)
    return f"timeout {last}"


def publish_facebook(video: Path, text: str, thumb: Path | None = None) -> dict:
    """Facebook Page Reel: start -> binary upload -> finish (publish) -> wait for processing."""
    page = os.environ["META_PAGE_ID"]
    start = api("POST", f"{page}/video_reels", upload_phase="start")
    vid = start["video_id"]
    _upload_binary(start.get("upload_url") or f"https://rupload.facebook.com/video-upload/{GRAPH_VERSION}/{vid}", video)
    api("POST", f"{page}/video_reels", upload_phase="finish", video_id=vid, video_state="PUBLISHED", description=text)
    status = _wait_fb(vid)
    if thumb and thumb.exists():
        try:
            with open(thumb, "rb") as f:
                _check(requests.post(f"{GRAPH}/{vid}/thumbnails", timeout=120, files={"source": f},
                                     data={"is_preferred": "true", "access_token": _token()}))
        except Exception as e:
            print(f"[FB] custom cover not set: {str(e)[:200]}")
    link = _get_soon(vid, fields="permalink_url").get("permalink_url", "")
    url = link if link.startswith("http") else (f"https://www.facebook.com{link}" if link else
                                                 f"https://www.facebook.com/reel/{vid}")
    return {"id": vid, "url": url, "status": status}


def find_existing(platform: str, title: str) -> dict | None:
    """Guard against double posts when history.json was not saved: look for the title in recent posts."""
    needle = clean_title(title).lower()
    if not needle:
        return None
    try:
        if platform == "ig":
            items = api("GET", f"{os.environ['IG_USER_ID']}/media", fields="id,caption,permalink", limit=25)["data"]
            for m in items:
                if needle in (m.get("caption") or "").lower():
                    return {"id": m["id"], "url": m.get("permalink", "")}
        else:
            items = api("GET", f"{os.environ['META_PAGE_ID']}/video_reels", fields="id,description,permalink_url",
                        limit=25)["data"]
            for m in items:
                if needle in (m.get("description") or "").lower():
                    link = m.get("permalink_url", "")
                    return {"id": m["id"], "url": link if link.startswith("http") else f"https://www.facebook.com{link}"}
    except Exception as e:
        print(f"[{platform.upper()}] duplicate check skipped: {str(e)[:200]}")
    return None


# ---------------------------------------------------------------- history bookkeeping

def _load_history() -> list[dict]:
    return json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []


def _entry_for(history: list[dict], meta: dict) -> dict | None:
    for h in reversed(history):
        if meta.get("video_id") and h.get("video_id") == meta["video_id"]:
            return h
        if not meta.get("video_id") and h.get("date") == meta.get("date") and h.get("title") == meta.get("title"):
            return h
    return None


def _record(meta: dict, platform: str, result: dict) -> None:
    history = _load_history()
    h = _entry_for(history, meta)
    if h is None:
        return
    h[f"{platform}_id"], h[f"{platform}_url"] = result["id"], result.get("url", "")
    HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")


def crosspost(video: Path, meta: dict, thumb: Path | None = None, cover_url: str = "",
              only: tuple[str, ...] = ("fb", "ig"), video_url: str = "") -> list[str]:
    """Post one Short to the platforms it is not on yet. Returns the platforms that failed."""
    entry = _entry_for(_load_history(), meta) or {}
    text = caption(meta)
    failed = []
    for p in only:
        if entry.get(f"{p}_id"):
            print(f"[{PLATFORMS[p]}] already posted: {entry.get(f'{p}_url') or entry[f'{p}_id']}")
            continue
        try:
            res = find_existing(p, meta.get("title", ""))
            if res:
                print(f"[{PLATFORMS[p]}] found an earlier post, recording it: {res['url']}")
            else:
                res = (publish_facebook(video, text, thumb) if p == "fb"
                       else publish_instagram(video, text, cover_url, video_url))
                print(f"[{PLATFORMS[p]}] ✅ posted: {res['url']}")
            _record(meta, p, res)
        except Exception as e:
            failed.append(p)
            print(f"::warning title={PLATFORMS[p]} 發布失敗（下次排程會再試）::{clean_title(meta.get('title', ''))}: {e}")
    return failed


def release_index(repo: str) -> dict[str, dict]:
    """YouTube video id -> {tag, assets} parsed from the GitHub Release notes."""
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')}"
    r = requests.get(f"https://api.github.com/repos/{repo}/releases", params={"per_page": 100},
                     headers=headers, timeout=30)
    r.raise_for_status()
    idx = {}
    for rel in r.json():
        m = re.search(r"youtube\.com/shorts/([\w-]{6,})", rel.get("body") or "")
        if m and m.group(1) not in idx:
            idx[m.group(1)] = {"tag": rel["tag_name"],
                               "assets": {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}}
    return idx


def catchup(repo: str, limit: int = 3) -> int:
    """Cross-post earlier Shorts that are missing on FB/IG (oldest first, at most `limit` per run)."""
    todo = [h for h in _load_history()
            if h.get("video_id") and not h.get("keep_private") and h.get("crosspost", True)
            and not (h.get("fb_id") and h.get("ig_id"))]
    if not todo:
        print("[Meta] FB/IG are up to date")
        return 0
    idx = release_index(repo)
    failures = 0
    for h in todo[:limit]:
        rel = idx.get(h["video_id"])
        if not rel or "video.mp4" not in rel["assets"]:
            print(f"::warning title=找不到影片檔::{h.get('title')} ({h['video_id']}) has no GitHub Release with video.mp4")
            continue
        print(f"== Cross-posting {clean_title(h.get('title', ''))} ({rel['tag']})")
        with tempfile.TemporaryDirectory() as tmp:
            files = {}
            for name in ("video.mp4", "meta.json", "thumbnail.jpg"):
                if name in rel["assets"]:
                    dst = Path(tmp) / name
                    with requests.get(rel["assets"][name], stream=True, timeout=300) as r:
                        r.raise_for_status()
                        with open(dst, "wb") as f:
                            for chunk in r.iter_content(1 << 20):
                                f.write(chunk)
                    files[name] = dst
            meta = {**h, **(json.loads(files["meta.json"].read_text(encoding="utf-8")) if "meta.json" in files else {})}
            meta["video_id"], meta["title"] = h["video_id"], h.get("title", meta.get("title", ""))
            need = tuple(p for p in ("fb", "ig") if not h.get(f"{p}_id"))
            cover = rel["assets"].get("thumbnail.jpg", "")
            failures += len(crosspost(files["video.mp4"], meta, files.get("thumbnail.jpg"), cover, need,
                                      video_url=rel["assets"]["video.mp4"]))
    return 1 if failures else 0


def check(warn_days: int = 14) -> int:
    d = api("GET", "debug_token", input_token=_token()).get("data", {})
    if not d.get("is_valid"):
        print("::error title=FB/IG 授權失效::請重新產生權杖（Graph API 測試工具 → Generate Access Token）")
        return 1
    exp = d.get("data_access_expires_at") or 0
    left = (exp - time.time()) / 86400 if exp else None
    print(f"[Meta] Page token valid; expires: {'never' if not d.get('expires_at') else time.ctime(d['expires_at'])}; "
          f"data access: {'n/a' if left is None else f'{left:.0f} days left'}; scopes: {', '.join(d.get('scopes', []))}")
    try:
        reels = api("GET", f"{os.environ['META_PAGE_ID']}/video_reels",
                    fields="id,created_time,description,status,published,permalink_url", limit=8).get("data", [])
        print(f"[FB] latest {len(reels)} Reels on the Page:")
        for r in reels:
            st = r.get("status") or {}
            print(f"  {r.get('created_time', '')[:16]}  published={r.get('published')}  "
                  f"video={st.get('video_status')}  publish={(st.get('publishing_phase') or {}).get('status')}  "
                  f"{(r.get('description') or '').splitlines()[0][:50] if r.get('description') else ''}")
    except Exception as e:
        print(f"[FB] could not list Reels: {str(e)[:200]}")
    if left is not None and left < warn_days:
        print(f"::error title=FB/IG 需要重新授權（剩 {max(left, 0):.0f} 天）::打開 https://developers.facebook.com/tools/explorer/ ，"
              "右邊「Meta 應用程式」選 Cloud Auto Poster，按 Generate Access Token，一路按繼續、儲存即可")
        return 1
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="storyvideo.meta")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("post", help="cross-post one rendered Short")
    s.add_argument("--video", default="out/video.mp4")
    s.add_argument("--meta", default="out/meta.json")
    s.add_argument("--thumb", default="")
    s.add_argument("--cover-url", default="")
    s.add_argument("--video-url", default="", help="public URL of the same video (Instagram fetches it)")
    s.add_argument("--only", choices=["fb", "ig"], default=None)
    c = sub.add_parser("catchup", help="cross-post earlier Shorts that are missing on FB/IG")
    c.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "NTCloudy/ai-story-video"))
    c.add_argument("--limit", type=int, default=3)
    sub.add_parser("check", help="token health")
    args = p.parse_args(argv)

    if not configured():
        print("[Meta] META_PAGE_ID / META_PAGE_TOKEN / IG_USER_ID not set; skipping FB/IG")
        return 0
    if args.cmd == "check":
        return check()
    if args.cmd == "catchup":
        return catchup(args.repo, args.limit)
    meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    failed = crosspost(Path(args.video), meta, Path(args.thumb) if args.thumb else None, args.cover_url,
                       (args.only,) if args.only else ("fb", "ig"), video_url=args.video_url)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
