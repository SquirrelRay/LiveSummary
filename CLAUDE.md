# 直播摘要 專案規則

## 開發環境（Python 3.13）
- 一律用專案資料夾的 `.venv`（Python 3.13）：`.venv\Scripts\python.exe`。系統上的 `python`（3.10）不再用於開發，不要用它跑程式、測試或檢查。
- 套件一律用鎖定檔安裝：`.venv\Scripts\python.exe -m pip install -r requirements-lock.txt`；`requirements.txt` 是給人看的主要套件與說明。
- 不要在 `.venv` 裡單獨升級或另裝套件；要升級照 README「開發環境」的步驟重新產生鎖定檔。av 維持 17.1.0（原因見 requirements.txt）。
- 打包 .exe 的調查、決定與步驟在 `docs/打包調查.md`，做打包相關工作前先讀。

## 檔案位置（開發和打包版相同）
- 程式資料（config.json、介面設定、網址紀錄、版面配置、詞庫\、logs\、翻譯錯誤紀錄）在 `%LOCALAPPDATA%\直播摘要`；輸出（直播稿、摘要、聊天室、逐句翻譯、音訊）在「文件」`\直播摘要`（Known Folder 取得，OneDrive 接管也對）。
- 所有路徑只由 `app_paths.py` 決定，其他 .py 不准自己用 `__file__`、`os.chdir`、相對路徑組資料或輸出的位置。
- 第一次啟動時（新位置沒有任何檔案）從專案資料夾「複製」程式資料過去，舊檔不動；舊的輸出檔不搬。
- 測試：`tests/conftest.py` 在 import 其他模組前就把 app_paths 換成暫存資料夾，測試絕不碰真的 %LOCALAPPDATA%、「文件」。新的模組變數路徑一律從 app_paths 拿，才會被換掉。
- 除錯用音訊放 `%LOCALAPPDATA%\直播摘要\音訊`（`app_paths.音訊資料夾()`，不放「文件」避免 OneDrive 上傳），開始新的一場時自動只留最近 5 場；只准刪該位置底下、名稱符合 `開頭_YYYYMMDD_HHMMSS_音訊` 且只含 wav 的資料夾。
- **實機 UI 測試要從檔案總管啟動 app.py（例如雙擊 .bat），不能從 Claude 桌面版裡啟動**：從 Claude 裡啟動時，寫進 %LOCALAPPDATA% 的檔案會被 Windows 轉到 Claude 的套件資料夾（`AppData\Local\Packages\Claude_…\LocalCache\Local\直播摘要`），真正的位置不會有東西。

## 完成前的固定檢查（強制）
每次修改完成前，必須在專案根目錄跑過：
1. `.venv\Scripts\ruff.exe check .`
2. `.venv\Scripts\python.exe -m pytest`

沒通過不能說「完成」，並且要在回報中貼出兩者的執行結果。
- 開發工具（ruff、pytest）已包含在 `requirements-lock.txt`。
- 不要自行執行 `ruff --fix` 或 `ruff format` 去改現有程式碼，除非使用者明確要求。
- 既有的 ruff 警告（基準線）由使用者決定要不要修；新增的程式碼不應增加新的警告。
- 測試一律用假資料／假模型回覆，不呼叫真 API、不連網、不需要 ffmpeg 或 streamlink。
- 不加型別檢查（mypy／pyright）。

## 提交前檢查（由 git hook 強制執行）
- `.githooks/pre-commit` 會在每次 `git commit` 時用 `.venv\Scripts\python.exe` 跑 `scripts/check.py`：pytest 必須全過，ruff 警告數不得比 `.ruff-baseline` 多，否則 commit 被擋下。
- 禁止使用 `git commit --no-verify`（或 `-n`）、改 `core.hooksPath`、刪除或停用 hook，或任何其他跳過檢查的方式。
- `.ruff-baseline` 只能調低（修掉警告後），不能調高。若真的需要調高，必須先回報使用者並說明原因，得到同意才能改。
- 手動跑檢查：`.venv\Scripts\python.exe scripts/check.py`（一般檢查，git hook 跑的就是這個，不含 `@pytest.mark.slow` 的慢測試；約 1.5～2 分鐘）。
- 完整檢查：`.venv\Scripts\python.exe scripts/check.py --all`（連慢測試一起跑）。**改到置頂、滑鼠提示、膠囊或面板的視窗樣式與前後順序、視窗層級相關程式（panel.py、capsule.py、overlay.py、提示置頂）時必須跑**，打包 .exe 前、發版前也要跑；報告「完成」時要貼 `--all` 的結果。
- 慢測試（真的 Windows 視窗、子程序、固定等待）用 `@pytest.mark.slow` 標記；不可以為了加速刪測試或降低涵蓋範圍，`--all` 一定要全過。新增測試時避免重複掛 QApplication 的事件過濾器（每個過濾器都會讓全程式每個事件多經過一次 Python，測試會越跑越慢）。
- 新電腦 clone 後要先執行 `git config core.hooksPath .githooks` 才會啟用 hook。
