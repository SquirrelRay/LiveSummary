第三方授權全文的補充資料（打包時 scripts\licenses.py 讀這裡，產生 dist\LiveSummary\licenses\；打包不連網）

套件自己有附授權全文的，licenses.py 直接從 .venv 收；這個資料夾只放套件沒附、要另外準備的：
  ctranslate2-版本\、tokenizers-版本\、intel-openmp-版本\、qt-版本\
      由 scripts\取得授權全文.py 從上游（該版本的 GitHub 標籤、Intel 在 PyPI 的 wheel）取得，每個資料夾的 來源.txt 有網址與日期。
      套件升級後重跑：.venv\Scripts\python.exe scripts\取得授權全文.py（版本從 .venv 讀；舊版本的資料夾手動刪）。
      licenses.py 找不到「目前版本」的資料夾時，打包會印警告。
  nvidia-cublas\聲明.txt   手寫：cuBLAS 隨附聲明（CUDA EULA 附件 A 的條件）
  vc-runtime\說明.txt      手寫：Microsoft Visual C++ 執行階段的散布說明（實際檔案與版本由 licenses.py 列出）
