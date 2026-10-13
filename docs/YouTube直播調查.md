# YouTube 直播支援：調查報告與決定

> 每一步開新視窗時先讀這份。範圍只有 YouTube「直播」，錄好的影片（VOD）之後才做。
> 調查日期：2026-10-14（下面所有來源都是這天查的）。實測環境：streamlink 8.6.2、yt-dlp 2026.8.19、Python 3.10，
> 對象是 Lofi Girl 的 24 小時直播（https://www.youtube.com/@LofiGirl/live）。

## 使用者的決定（2026-10-14）

- 音訊：**streamlink**（沿用現在的寫法）。
- 聊天室：**yt-dlp 的 live_chat**（用每則留言的發送時刻對齊時間軸；剛連上時送來的舊留言要過濾）。
- 開播時間、頻道 ID、直播主、@帳號、標題、分類、是否直播中：**自己讀觀看頁**（stream_info.py，只用 Python 內建工具）。
- 詞庫用**頻道 ID** 當鍵：檔名 `YT_頻道ID.txt`，檔案開頭註明直播主名稱與 @帳號。
- **Super Chat** 當一般留言處理，內容前面加「【SC】」。
- 第一版**不做**：官方 API、yt-dlp 音訊備援、會員／年齡限制直播、抓遊戲名稱。

## 5 步計畫（一次一步，每步前後各建存檔點）

1. **存報告＋平台判斷＋YouTube 直播資訊**：本文件；平台判斷模組（platforms.py）；stream_info 加 YouTube 觀看頁讀法；
   啟動面板與名詞清單的網址驗證（YouTube 網址在背景查頻道 ID，詞庫檔名 YT_頻道ID）。
2. **音訊與直播資訊接上擷取**：live_capture 的平台判斷與錯誤訊息（要求登入／機器人檢查、還沒開始、會員限定、不支援 VOD）；
   開始擷取時用 stream_info 的 YouTube 讀法；stream_clock 依平台用不同的串流延遲（**要實測 YouTube 的延遲**）。
3. **聊天室**：新增 YouTube 聊天室模組（yt-dlp live_chat，邊寫邊讀 JSON；過濾連上前的舊留言；Super Chat 加「【SC】」）；
   chat_capture 抽出共同介面（開始／取出／關閉／訊息們／存檔路徑／收到／過濾）。
4. **詞庫與檔名**：引擎的詞庫改用 YT_頻道ID（live_topics.執行 目前用 頻道名稱(網址)）；直播稿等輸出檔名用 @帳號；
   查不到頻道 ID 時這一場不用詞庫並印一行說明（避免分裂出第二份詞庫）。
5. **文字**：首次引導、網址欄提示文字（launcher、app）、時間藥丸的「Twitch 公開資料」字樣、README；
   chat_translate 的 YouTube 表情與機器人規則。

會動到的檔案：live_capture、stream_info、stream_clock、chat_capture、chat_translate、live_topics、app、launcher、
names_page、onboarding、README，新增 platforms.py 與 YouTube 聊天室模組，加測試檔。

## 實測結果（2026-10-14）

| 項目 | 結果 |
|---|---|
| streamlink 抓 YouTube 直播 | ✓ 免登入。品質 144p～1080p，**沒有 audio_only**；現有程式退回 `worst`（144p），ffprobe 確認含 AAC 音軌，音訊部分可直接沿用 |
| streamlink 的 metadata | 有 author、title、category（如 "Music"）；**沒有開播時間、沒有頻道 ID** |
| 免金鑰開播時間 | ✓ 觀看頁 `ytInitialPlayerResponse.microformat.playerMicroformatRenderer.liveBroadcastDetails.startTimestamp`（例：2026-10-01T17:00:26+00:00），同頁有 videoDetails.channelId、author、category、ownerProfileUrl（@帳號） |
| yt-dlp live_chat | ✓ 免登入，30 秒收到 77 則，約每 10 秒一批；每則有 `timestampUsec`（發送時刻）與 `@帳號`；剛連上會先送一批舊留言 |
| yt-dlp 警告 | 沒有 JS 執行環境（deno）→「部分格式可能缺少」；Python 3.10 已不建議使用。聊天室照樣成功 |

## 1. 抓音訊

| 做法 | 優點 | 缺點 | 金鑰 | 維護風險 | 來源 |
|---|---|---|---|---|---|
| **streamlink** | 已安裝；不需 JS 執行環境；YouTube 壞掉修得快（2026-03-04 回報→當天修→03-05 發 8.2.1；01-18 的 8.1.2 也修過） | 官方註明不支援 VOD 與受保護影片；#6940（2026-06）某些 IP 被要求「登入確認不是機器人」，加 cookies 也無效，尚無維護者回應 | 不用 | 中低 | [外掛說明](https://streamlink.github.io/plugins.html)、[更新紀錄](https://streamlink.github.io/changelog.html)、[#6852](https://github.com/streamlink/streamlink/issues/6852)、[#6940](https://github.com/streamlink/streamlink/issues/6940) |
| yt-dlp | 維護最活躍 | **抓 YouTube 現在需要外部 JS 執行環境**（Deno ≥2.3 推薦，或 Node ≥22）＋ yt-dlp-ejs，否則「部分格式可能缺少」 | 不用 | 低（但多一個外部依賴） | [EJS wiki（2026-07-12 修訂）](https://github.com/yt-dlp/yt-dlp/wiki/EJS) |

## 2. 抓聊天室（標準：一般觀眾能不能自己設定）

| 做法 | 優點 | 缺點 | 金鑰 | 維護風險 | 來源 |
|---|---|---|---|---|---|
| 官方 API liveChatMessages.list | 官方、穩定 | 觀眾要自己開 Google Cloud 專案→啟用 YouTube Data API v3→建 API 金鑰（約 5～6 步、多為英文）；每日 10,000 單位、每次 5 單位＝約 2,000 次，每 5～10 秒一次只撐 **2.8～5.6 小時**；美西午夜重置；**文件沒寫 API 金鑰能不能讀聊天室** | 要 | 低 | [list](https://developers.google.com/youtube/v3/live/docs/liveChatMessages/list)、[額度表](https://developers.google.com/youtube/v3/determine_quota_cost)（2026-10-08 更新）、[入門](https://developers.google.com/youtube/v3/getting-started)、[額度申請](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits)（2026-09-14 更新） |
| 官方 streamList | 官方推薦省額度 | 每次 5 單位，文件沒說串流中每批要不要另算；可能要 gRPC；一樣要金鑰 | 要 | 低 | [streamList](https://developers.google.com/youtube/v3/live/docs/liveChatMessages/streamList) |
| pytchat | 免金鑰 | **已封存**，PyPI 最後 0.5.5（2021-07） | 不用 | 很高 | GitHub／PyPI |
| chat-downloader | 免金鑰 | 最後 0.2.8（2023-09）；2025-10 起「Unable to parse initial video data」未修；2026-06 起頻道網址找不到直播，原作者無回應 | 不用 | 很高 | [#287](https://github.com/xenova/chat-downloader/issues/287) |
| **yt-dlp live_chat** | 已在 requirements；最活躍；實測可用且不需 JS；有發送時刻 | 一樣是非官方介面；寫成 JSON 檔要邊寫邊讀；剛連上有舊留言 | 不用 | 中（壞了通常更新 yt-dlp 就好） | 實測、yt-dlp 原始碼 |
| 自己寫（讀 YouTube 內部介面） | 不新增套件、好測試 | YouTube 改版要自己修 | 不用 | 中高 | — |

官方 API 不適合當預設：一般觀眾不可能開 Google Cloud 專案；把我們的金鑰包進 .exe 會讓所有人共用額度、金鑰也會外流。

## 3. 開播時間

- **觀看頁 `liveBroadcastDetails.startTimestamp`**：免金鑰，實測可行，和 yt-dlp 的 release_timestamp 同一來源、值一致。
- 官方 videos.list 的 `actualStartTime`：要金鑰（1 單位）。[videos 文件](https://developers.google.com/youtube/v3/docs/videos)
- ⚠ stream_clock 的 11 秒串流延遲是 Twitch 量的；YouTube 有不同延遲模式，**要另外量**。

## 4. 網址與頻道

支援的格式（streamlink 的 YouTube 外掛都認得）：`watch?v=ID`、`/live/ID`、`youtu.be/ID`、`/@帳號`、`/@帳號/live`、
`/channel/UC…`（含 `/live`）、`/c/名稱`、`/user/名稱`（含 `/live`）、`/embed/ID`、`/embed/live_stream?channel=UC…`、`m.` 開頭。
`/shorts/` 擋掉。

- `watch?v=`、`youtu.be` 看不出頻道，一定要上網查；`@帳號` 不用上網就知道，但直播主可以改帳號、YouTube 也可能收回
  （[帳號說明](https://support.google.com/youtube/answer/11585688)）。
- 詞庫用**頻道 ID（UC…）**當鍵：不會變，所有網址格式都對得上同一份。檔名 `YT_UCxxxx.txt`（`YT_` 前綴避免和 Twitch 帳號撞名），
  檔案開頭寫直播主名稱與 @帳號。輸出檔名改用 @帳號。名詞清單按鈕遇到 YouTube 網址在背景查頻道 ID，查詢中顯示「查詢頻道中…」。

## 5. 直播主、標題、分類

免金鑰都拿得到（觀看頁、streamlink 都有）。YouTube 的分類很粗（Gaming、Music），不像 Twitch 給遊戲名，上網查證的背景資訊會少一點。

## 6. 對現有功能的影響

| 功能 | 要改？ | 說明 |
|---|---|---|
| 說話者規則 | 不用 | 和平台無關 |
| 詞庫 | 要 | live_topics.執行 用 `頻道名稱(網址)` 當直播主，YouTube 改用頻道 ID；查不到就這一場不用詞庫並印說明 |
| 上網查證 | 小 | 分類變粗，程式不用改 |
| 聊天室翻譯 | 小 | chat_translate 的 Twitch 表情規則；YouTube 表情是另外的 run，組文字時拿掉；補機器人名單；Super Chat 加「【SC】」 |
| 聊天室擷取 | 要 | chat_capture 是 Twitch IRC 專用，新增 YouTube 版、對外介面一樣 |
| 網址驗證 | 要 | names_page 的網址規則只認 Twitch；`watch?v=` 不上網看不出是直播或影片，等 streamlink 回報不支援 VOD 再轉白話 |
| 開播檢查錯誤訊息 | 要 | live_capture.檢查直播 補：要求登入（機器人檢查）、還沒開始、會員限定 |
| 首次引導與提示文字 | 要 | onboarding、app、launcher、README 寫死 Twitch |
| 網址紀錄 | 不用 | ui_state.頻道名 已處理 YouTube |

## 7. 打包成 .exe

- 專案目前沒有打包設定。
- **既有問題（Twitch 也受影響）**：`sys.executable -m streamlink_cli` 在 PyInstaller .exe 裡，sys.executable 是 .exe 本身，`-m` 失效；
  聊天室若用 yt-dlp 另開程序也一樣。打包時要讓 .exe 能用參數切換成 streamlink／yt-dlp 模式，或改在程序內呼叫。
- yt-dlp 官方本身用 PyInstaller 打包（EJS wiki）。Deno 是外部程式，不能當 Python 套件打包（所以第一版不依賴它）。
- 未驗證：streamlink 外掛動態載入，PyInstaller 可能要手動列出模組。
- yt-dlp 警告 Python 3.10 已不建議使用，打包前最好升到 3.11 以上。

## 失效時使用者會看到什麼

- **聊天室壞了**：重試 3 次後顯示「聊天室連不上…之後只用語音稿運作」，摘要與字幕照常；建議改成「YouTube 聊天室暫時抓不到（可能是 YouTube 改版），摘要照常；更新程式後會恢復」。
- **開播時間抓不到**：改「從開始擷取起算」，時間前加 +（現有機制）。
- **頻道 ID 抓不到**：這一場不用詞庫，印一行說明；名詞清單按鈕停用並寫白話原因。
- **streamlink 壞了或被判定是機器人**：按開始就失敗，啟動面板顯示白話說明。使用者自己無法排除。
