# 直播摘要 專案規則

## 完成前的固定檢查（強制）
每次修改完成前，必須在專案根目錄跑過：
1. `ruff check .`
2. `pytest`

沒通過不能說「完成」，並且要在回報中貼出兩者的執行結果。
- 開發工具安裝：`pip install -r requirements-dev.txt`
- 不要自行執行 `ruff --fix` 或 `ruff format` 去改現有程式碼，除非使用者明確要求。
- 既有的 ruff 警告（基準線）由使用者決定要不要修；新增的程式碼不應增加新的警告。
- 測試一律用假資料／假模型回覆，不呼叫真 API、不連網、不需要 ffmpeg 或 streamlink。
- 不加型別檢查（mypy／pyright）。

## 提交前檢查（由 git hook 強制執行）
- `.githooks/pre-commit` 會在每次 `git commit` 時跑 `scripts/check.py`：pytest 必須全過，ruff 警告數不得比 `.ruff-baseline` 多，否則 commit 被擋下。
- 禁止使用 `git commit --no-verify`（或 `-n`）、改 `core.hooksPath`、刪除或停用 hook，或任何其他跳過檢查的方式。
- `.ruff-baseline` 只能調低（修掉警告後），不能調高。若真的需要調高，必須先回報使用者並說明原因，得到同意才能改。
- 手動跑檢查：`python scripts/check.py`
- 新電腦 clone 後要先執行 `git config core.hooksPath .githooks` 才會啟用 hook。
