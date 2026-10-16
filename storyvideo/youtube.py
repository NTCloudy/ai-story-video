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

SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
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


def channel_info() -> dict:
    r = requests.get(f"{API}/channels", params={"part": "snippet,statistics", "mine": "true"},
                     headers={"Authorization": f"Bearer {access_token()}"}, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    return items[0] if items else {}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="storyvideo.youtube")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("auth")
    a.add_argument("--client-id", required=True)
    a.add_argument("--client-secret", required=True)
    sub.add_parser("whoami")
    sub.add_parser("check", help="verify auth + upload permission without uploading anything")
    args = p.parse_args(argv)
    if args.cmd == "auth":
        print("YT_REFRESH_TOKEN=" + device_auth(args.client_id, args.client_secret))
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
