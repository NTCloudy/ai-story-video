"""YouTube Data API v3: OAuth (device flow) + resumable upload.

Setup (one time):
  1. Google Cloud console -> new project -> enable "YouTube Data API v3".
  2. OAuth consent screen: External, add yourself as test user, then "Publish app" (so tokens don't expire).
  3. Credentials -> Create OAuth client ID -> type "TVs and Limited Input devices".
  4. python -m storyvideo.youtube auth --client-id ... --client-secret ...   -> prints YT_REFRESH_TOKEN
Secrets used by the workflow: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN.

Note: uploads from an API project that has not passed Google's compliance audit are locked to PRIVATE.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

SCOPES = ("https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly "
          "https://www.googleapis.com/auth/youtube")  # youtube = manage channel branding (banner, description, watermark)
DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
API = "https://www.googleapis.com/youtube/v3"


def device_auth(client_id: str, client_secret: str) -> str:
    r = requests.post(DEVICE_URL, data={"client_id": client_id, "scope": SCOPES}, timeout=30)
    r.raise_for_status()
    d = r.json()
    print(f"\n請用手機或電腦打開：{d['verification_url']}\n輸入驗證碼：{d['user_code']}\n（用要上傳影片的 YouTube 帳號登入並按允許）\n",
          flush=True)
    interval = int(d.get("interval", 5))
    deadline = time.time() + int(d.get("expires_in", 1800))
    while time.time() < deadline:
        time.sleep(interval)
        t = requests.post(TOKEN_URL, data={
            "client_id": client_id, "client_secret": client_secret, "device_code": d["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}, timeout=30).json()
        if "refresh_token" in t:
            return t["refresh_token"]
        if t.get("error") == "slow_down":
            interval += 5
        elif t.get("error") not in ("authorization_pending",):
            raise RuntimeError(f"授權失敗：{t}")
    raise RuntimeError("授權逾時")


def access_token() -> str:
    r = requests.post(TOKEN_URL, data={
        "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"], "grant_type": "refresh_token"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"YouTube 授權失效，請重新授權：{r.text[:300]}")
    return r.json()["access_token"]


def configured() -> bool:
    return all(os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))


def upload(video: Path, title: str, description: str, tags: list[str], category: str = "27",
           privacy: str = "private", made_for_kids: bool = False, synthetic: bool = True,
           language: str = "en") -> dict:
    token = access_token()
    meta = {
        "snippet": {"title": title[:100], "description": description[:4900], "tags": tags[:30],
                    "categoryId": category, "defaultLanguage": language, "defaultAudioLanguage": language},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": made_for_kids,
                   "containsSyntheticMedia": synthetic, "embeddable": True, "license": "youtube"},
    }
    size = video.stat().st_size
    init = requests.post(UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"},
                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                  "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
                         data=json.dumps(meta), timeout=60)
    if init.status_code != 200:
        raise RuntimeError(f"YouTube 上傳初始化失敗：{init.status_code} {init.text[:500]}")
    loc = init.headers["Location"]
    for attempt in range(5):
        with open(video, "rb") as f:
            r = requests.put(loc, headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4"},
                             data=f, timeout=600)
        if r.status_code in (200, 201):
            v = r.json()
            print(f"[YouTube] 已上傳：https://youtube.com/shorts/{v['id']}（{v['status']['privacyStatus']}）")
            return v
        if r.status_code in (500, 502, 503, 504):
            time.sleep(10 * (attempt + 1))
            continue
        raise RuntimeError(f"YouTube 上傳失敗：{r.status_code} {r.text[:500]}")
    raise RuntimeError("YouTube 上傳多次失敗")


def set_privacy(video_id: str, privacy: str = "public") -> dict:
    token = access_token()
    auth = {"Authorization": f"Bearer {token}"}
    cur = requests.get(f"{API}/videos", params={"part": "status", "id": video_id}, headers=auth, timeout=30).json()
    if not cur.get("items"):
        raise RuntimeError(f"找不到影片 {video_id}")
    status = cur["items"][0]["status"]
    body = {"id": video_id, "status": {"privacyStatus": privacy,
                                       "selfDeclaredMadeForKids": status.get("madeForKids", False),
                                       "embeddable": status.get("embeddable", True),
                                       "license": status.get("license", "youtube"),
                                       "publicStatsViewable": status.get("publicStatsViewable", True),
                                       "containsSyntheticMedia": status.get("containsSyntheticMedia", True)}}
    r = requests.put(f"{API}/videos", params={"part": "status"}, headers={**auth, "Content-Type": "application/json"},
                     data=json.dumps(body), timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code} {r.text[:600]}")
    return r.json()["status"]


def video_stats(ids: list[str]) -> dict[str, dict]:
    """{video_id: {views, likes, comments}} for our own videos (1 quota unit per 50 ids)."""
    out = {}
    auth = {"Authorization": f"Bearer {access_token()}"}
    for i in range(0, len(ids), 50):
        r = requests.get(f"{API}/videos", params={"part": "statistics", "id": ",".join(ids[i:i + 50])},
                         headers=auth, timeout=30).json()
        for v in r.get("items", []):
            st = v.get("statistics", {})
            out[v["id"]] = {"views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                            "comments": int(st.get("commentCount", 0))}
    return out


ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
ANALYTICS_METRICS = ["views", "engagedViews", "averageViewPercentage", "averageViewDuration", "likes", "shares",
                     "subscribersGained"]


def video_analytics(ids: list[str], start: str = "2026-01-01", end: str = "") -> dict[str, dict]:
    """{video_id: {views, engagedViews, averageViewPercentage, averageViewDuration, likes, shares, subscribersGained}}
    from the YouTube Analytics API (data lags ~1-2 days). engagedViews / views ~ share of viewers who did not
    swipe away right away. Falls back to fewer metrics when a metric is not available."""
    from datetime import date
    end = end or date.today().isoformat()
    auth = {"Authorization": f"Bearer {access_token()}"}
    out: dict[str, dict] = {}
    metrics = list(ANALYTICS_METRICS)
    for i in range(0, len(ids), 200):
        while True:
            r = requests.get(ANALYTICS, headers=auth, timeout=60, params={
                "ids": "channel==MINE", "startDate": start, "endDate": end, "dimensions": "video",
                "metrics": ",".join(metrics), "filters": "video==" + ",".join(ids[i:i + 200]), "maxResults": 200})
            if r.status_code == 400 and "engagedViews" in metrics:
                metrics.remove("engagedViews")
                continue
            if r.status_code != 200:
                raise RuntimeError(f"YouTube Analytics {r.status_code}: {r.text[:400]}")
            break
        d = r.json()
        names = [h["name"] for h in d.get("columnHeaders", [])]
        for row in d.get("rows", []):
            rec = dict(zip(names, row))
            out[rec.pop("video")] = rec
    return out


def trending_shorts(queries: list[str], days: int = 30, per_query: int = 12) -> list[dict]:
    """Most-viewed recent English Shorts for niche keywords (search.list = 100 quota units per query)."""
    from datetime import datetime, timedelta, timezone
    auth = {"Authorization": f"Bearer {access_token()}"}
    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    found: dict[str, dict] = {}
    for q in queries:
        r = requests.get(f"{API}/search", headers=auth, timeout=30, params={
            "part": "snippet", "type": "video", "videoDuration": "short", "order": "viewCount", "q": q,
            "publishedAfter": after, "relevanceLanguage": "en", "maxResults": per_query, "safeSearch": "strict"})
        if r.status_code != 200:
            print(f"[Trends] search failed for {q!r}: {r.status_code} {r.text[:200]}")
            continue
        for it in r.json().get("items", []):
            vid = it["id"].get("videoId")
            if vid:
                found[vid] = {"id": vid, "title": it["snippet"]["title"], "channel": it["snippet"]["channelTitle"], "query": q}
    ids = list(found)
    for i in range(0, len(ids), 50):
        r = requests.get(f"{API}/videos", params={"part": "statistics", "id": ",".join(ids[i:i + 50])},
                         headers=auth, timeout=30).json()
        for v in r.get("items", []):
            found[v["id"]]["views"] = int(v.get("statistics", {}).get("viewCount", 0))
    return sorted((v for v in found.values() if v.get("views")), key=lambda v: -v["views"])


def channel_info() -> dict:
    r = requests.get(f"{API}/channels", params={"part": "snippet,statistics", "mine": "true"},
                     headers={"Authorization": f"Bearer {access_token()}"}, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    return items[0] if items else {}


def apply_branding(banner: Path | None, watermark: Path | None, description: str, keywords: list[str],
                   country: str = "TW", language: str = "en") -> None:
    """Set banner, description, keywords, country, default language and video watermark.
    (YouTube API cannot change the profile picture.)"""
    token = access_token()
    auth = {"Authorization": f"Bearer {token}"}
    ch = requests.get(f"{API}/channels", params={"part": "brandingSettings", "mine": "true"}, headers=auth, timeout=30)
    ch.raise_for_status()
    item = ch.json()["items"][0]
    cid, bs = item["id"], item.get("brandingSettings", {})
    channel = bs.get("channel", {})
    channel.update(description=description[:1000], country=country, defaultLanguage=language,
                   keywords=" ".join(f'"{k}"' if " " in k else k for k in keywords)[:500])
    body = {"id": cid, "brandingSettings": {"channel": channel}}
    if banner:
        r = requests.post("https://www.googleapis.com/upload/youtube/v3/channelBanners/insert",
                          params={"uploadType": "media"}, headers={**auth, "Content-Type": "image/png"},
                          data=banner.read_bytes(), timeout=120)
        if r.status_code != 200:
            raise RuntimeError(f"橫幅上傳失敗：{r.status_code} {r.text[:400]}")
        body["brandingSettings"]["image"] = {"bannerExternalUrl": r.json()["url"]}
        print("✅ 橫幅已上傳")
    r = requests.put(f"{API}/channels", params={"part": "brandingSettings"},
                     headers={**auth, "Content-Type": "application/json"}, data=json.dumps(body), timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"頻道設定失敗：{r.status_code} {r.text[:400]}")
    print("✅ 說明、關鍵字、國家、語言已更新")
    if watermark:
        boundary = "wmboundary7f3a"
        meta = json.dumps({"timing": {"type": "offsetFromStart", "offsetMs": 0},
                           "position": {"type": "corner", "cornerPosition": "bottomRight"}})
        payload = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
                   f"--{boundary}\r\nContent-Type: image/png\r\n\r\n").encode() + watermark.read_bytes() + \
                  f"\r\n--{boundary}--".encode()
        r = requests.post("https://www.googleapis.com/upload/youtube/v3/watermarks/set",
                          params={"channelId": cid, "uploadType": "multipart"},
                          headers={**auth, "Content-Type": f"multipart/related; boundary={boundary}"},
                          data=payload, timeout=120)
        print("✅ 影片浮水印已設定" if r.status_code in (200, 204) else f"⚠️ 浮水印設定失敗：{r.status_code} {r.text[:300]}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="storyvideo.youtube")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("auth")
    a.add_argument("--client-id", required=True)
    a.add_argument("--client-secret", required=True)
    sub.add_parser("whoami")
    sub.add_parser("check", help="verify auth + upload permission without uploading anything")
    sub.add_parser("branding", help="apply channel/branding.json (banner, description, keywords, watermark)")
    pub = sub.add_parser("publish", help="set a video's privacy (public/unlisted/private)")
    pub.add_argument("video_id")
    pub.add_argument("--privacy", default="public")
    args = p.parse_args(argv)
    if args.cmd == "auth":
        print("YT_REFRESH_TOKEN=" + device_auth(args.client_id, args.client_secret))
    elif args.cmd == "publish":
        st = set_privacy(args.video_id, args.privacy)
        print(f"PUBLISH {args.video_id} -> {st.get('privacyStatus')}")
    elif args.cmd == "branding":
        cfg = json.loads(Path("channel/branding.json").read_text(encoding="utf-8"))
        apply_branding(Path(cfg["banner"]) if cfg.get("banner") else None,
                       Path(cfg["watermark"]) if cfg.get("watermark") else None,
                       cfg["description"], cfg["keywords"], cfg.get("country", "TW"), cfg.get("language", "en"))
    elif args.cmd == "check":
        info = channel_info()
        print(f"頻道：{info.get('snippet', {}).get('title')}（{info.get('id')}）")
        token = access_token()
        meta = {"snippet": {"title": "preflight", "categoryId": "27"},
                "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}}
        r = requests.post(UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"},
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                   "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": "1000000"},
                          data=json.dumps(meta), timeout=60)
        ok = r.status_code == 200 and "Location" in r.headers
        print("上傳權限：" + ("✅ 正常（預檢通道已建立，未上傳任何影片）" if ok else f"❌ {r.status_code} {r.text[:300]}"))
        return 0 if ok else 1
    else:
        info = channel_info()
        print(json.dumps({"title": info.get("snippet", {}).get("title"), "stats": info.get("statistics")},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
