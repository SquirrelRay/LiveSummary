# 直播摘要（LiveSummary）

一邊看 Twitch 或 YouTube 直播，一邊幫你把直播內容轉成文字、整理成摘要的 Windows 小工具。
外語直播也能即時翻成中文字幕。適合追直播主、但沒辦法每一分鐘都盯著畫面的人：
晚來、離開一下、或是看不懂日文，回來看一眼摘要就知道剛剛在聊什麼。

<!-- 截圖：之後補上（例如主畫面＋浮動字幕的樣子）
![直播摘要畫面](docs/images/screenshot.png)
-->

## 能做什麼

- **即時轉錄**：把直播的聲音轉成文字稿（在你自己的電腦上轉，不另外收費）。
- **分鐘摘要**：每分鐘用一兩句話整理剛剛講了什麼，也會簡單整理聊天室的反應。
- **話題摘要**：自動判斷什麼時候換了話題，每個話題結束時整理成標題＋重點。
- **外語翻譯**：日文、英文等外語直播可以顯示中文字幕，聊天室留言也可以翻成中文。
- **支援 Twitch 和 YouTube**：貼上頻道或直播網址就能開始（YouTube 只支援公開的直播）。
- 浮動字幕與摘要可以疊在直播畫面上，直播稿和摘要會自動存檔在「文件\直播摘要」。

## 下載

到 [Releases](https://github.com/SquirrelRay/LiveSummary/releases) 下載最新版的 `LiveSummary-v版本號.zip`。

> [!IMPORTANT]
> **下載後請先把整個壓縮檔解壓縮，再執行！**
>
> 在 zip 上按右鍵 →「全部解壓縮」→「解壓縮」，再打開解壓縮出來的 `LiveSummary` 資料夾，雙擊 `LiveSummary.exe`。
> 不要在壓縮檔裡直接點開 `LiveSummary.exe`，那樣一定打不開（會出現英文的「Failed to load Python DLL」錯誤）。

`LiveSummary` 資料夾裡的其他檔案都是程式需要的，請整個資料夾放在一起；想搬到別的地方就整個資料夾一起搬。
這個程式不用安裝，詳細的使用方式在壓縮檔裡的「使用說明.txt」，第一次打開時程式也會帶你走一遍。

## 系統需求

- Windows 10 或 Windows 11（64 位元）
- 網路連線
- **NVIDIA 顯示卡可以加速**（比較快、比較準）：驅動程式最低 527.41 版，建議更新到最新版。
  驅動太舊或沒有 NVIDIA 顯示卡也能用，會自動改用處理器（CPU）轉錄，只是比較慢。
- 硬碟空間：程式約 1.3 GB，加上第一次使用時下載的轉錄模型 0.5～1.6 GB

## 需要自己的 AI 服務金鑰

摘要和翻譯要用線上的 AI 服務，需要**你自己的 API 金鑰**（程式本身免費，不經過任何中間服務）。
預設用 Claude，也可以改用 OpenAI、Google Gemini、DeepSeek、OpenRouter 等。
金鑰只存在你這台電腦的 Windows 認證管理員。

**大概的費用**（以預設的 Claude Haiku 模型估算，實際以服務的帳單為準）：

- 外語直播，開著逐句翻譯和聊天室翻譯：一小時約 **0.1 美元**
- 中文直播不需要翻譯，會更少
- 打開「上網查證」時每小時約多 0.2 美元

程式的啟動面板和設定裡，會依你目前的設定顯示估算的每小時費用。服務的價格可能調整，請以程式內顯示的估算和帳單為準。

## 第一次執行時跳出藍色的「Windows 已保護您的電腦」

按畫面上的「**其他資訊**」，再按「**仍要執行**」。

這是因為本程式是個人開發的開放原始碼程式，沒有購買付費的數位簽章，Windows 會對這類新程式擋一次，不代表有病毒。
如果不放心，可以先把檔案上傳到 [VirusTotal](https://www.virustotal.com) 檢查，或者選擇不要執行。
防毒軟體誤判、把檔案刪掉的處理方式請看「使用說明.txt」的常見問題。

## 授權

本程式以 [GNU GPLv3](LICENSE) 授權開放原始碼，著作權人 **SquirrelRay**。
另依 GPLv3 第 7 條加上額外許可，允許與 NVIDIA、Intel 的函式庫一起使用，條文見 [LICENSE-ADDITIONAL-PERMISSION.txt](LICENSE-ADDITIONAL-PERMISSION.txt)。
程式附帶的 FFmpeg（LGPL v3）等第三方元件，授權全文在程式資料夾的 `licenses` 資料夾；FFmpeg 的原始碼附在 Releases 頁面。

## 喜歡的話

- ⭐ 到 GitHub 給個星星：<https://github.com/SquirrelRay/LiveSummary>
- ☕ 請我喝杯咖啡：<https://ko-fi.com/squirrelray>

---

## English

**LiveSummary** is a Windows tool for people who follow Twitch and YouTube streamers. While a stream is running it
transcribes the audio locally, writes one-minute summaries and per-topic summaries, and can translate
foreign-language streams (and their chat) into Traditional Chinese subtitles. The interface is in Traditional Chinese.

- **Download** the zip from [Releases](https://github.com/SquirrelRay/LiveSummary/releases). **Extract the whole zip first**,
  then run `LiveSummary.exe` from the extracted `LiveSummary` folder — running it from inside the zip will not work.
- **Requirements:** Windows 10/11 64-bit. An NVIDIA GPU speeds things up (driver 527.41 or newer; the latest is recommended);
  without one it falls back to the CPU.
- **API key:** summaries and translation use your own AI service API key (Claude by default; OpenAI, Gemini, DeepSeek,
  OpenRouter and others also work). With the default Claude Haiku model, a foreign-language stream costs roughly
  US$0.10 per hour.
- **"Windows protected your PC":** click "More info" → "Run anyway". The app is not code-signed.
- **License:** GPLv3 with an additional permission (section 7) for the NVIDIA and Intel libraries. Copyright © SquirrelRay.
