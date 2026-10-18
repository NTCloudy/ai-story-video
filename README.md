# 🎬 AI 故事影片工作室

寫下你的故事，AI 自動幫你做成 **插畫 + 旁白 + 字幕** 的影片，可以直接下載上傳 YouTube。

👉 **網頁：https://ntcloudy.github.io/ai-story-video/**

## 流程
1. ✍️ **AI 分鏡**：Google Gemini 把故事拆成分鏡，寫出旁白和英文畫面描述，並固定角色外觀，讓每張圖的角色長得一樣。同時產生 YouTube 標題、說明和標籤。
2. 🎨 **AI 插畫**：Cloudflare Workers AI（Flux 模型）為每個分鏡畫一張插畫。
3. 🎙️ **旁白配音**：Microsoft Edge 的台灣中文語音（曉臻、曉雨、雲哲）。如果連不上，自動改用 Google 語音。
4. 🎞️ **合成影片**：每個分鏡加上鏡頭推移和淡入淡出，片頭有標題，並燒入字幕。輸出 1080p MP4、YouTube 縮圖和 SRT 字幕檔。

做好的影片會放在 GitHub Releases，網頁上可以直接播放、下載、複製 YouTube 標題和說明。

## 費用
全部使用免費額度：

| 服務 | 免費額度 |
|---|---|
| Gemini API | 每天數百次請求，寫分鏡綽綽有餘 |
| Cloudflare Workers AI | 每天 10,000 neurons，大約 200 張以上的 Flux 插畫 |
| Edge TTS / gTTS | 免費 |
| GitHub Actions（公開 repo） | 免費 |

## 第一次設定
在 repo 的 **Settings → Secrets and variables → Actions** 新增：

| Secret | 怎麼拿 |
|---|---|
| `GEMINI_API_KEY` | <https://aistudio.google.com/apikey> → Create API key |
| `CF_ACCOUNT_ID` | Cloudflare 儀表板右側的 Account ID |
| `CF_API_TOKEN` | Cloudflare → My Profile → API Tokens → Create Token → 範本「Workers AI」 |

## 在本機執行
```bash
sudo apt install ffmpeg fonts-noto-cjk
pip install -r requirements.txt
export GEMINI_API_KEY=... CF_ACCOUNT_ID=... CF_API_TOKEN=...
python -m storyvideo --story-file story.txt --title "我的故事" --length medium --voice female --out out
```

## 上傳 YouTube 注意
插畫是 AI 生成的、旁白是 AI 語音。上傳時請在 YouTube Studio 的「變造或合成內容」選擇「是」。

## 同步到 Facebook 粉專 / Instagram（Reels）
每天的 Short 上傳 YouTube 後，`daily-short.yml` 會用 `storyvideo/meta.py` 把同一支影片發成 **FB 粉專 Reels** 和 **IG Reels**
（文字 = 標題 + 說明 + 來源 + AI 生成聲明 + hashtag），結果記在 `channel/history.json` 的 `fb_url` / `ig_url`。
發布失敗的影片，之後每次排程都會自動補發；也可以手動執行 **Actions → FB / IG → catchup**。

| Secret | 內容 |
|---|---|
| `META_PAGE_ID` | 粉專 ID |
| `META_PAGE_TOKEN` | 粉專權杖（由 60 天使用者權杖換出，不會過期） |
| `IG_USER_ID` | 連結到粉專的 IG 專業帳號 ID |

Meta 規定每 90 天要重新授權一次：**FB / IG** workflow 每週檢查，快到期時會失敗並寄信提醒，
到時打開 <https://developers.facebook.com/tools/explorer/>，選 Cloud Auto Poster，按 Generate Access Token 即可。
