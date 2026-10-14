@echo off
chcp 65001 >nul
rem 強制 CPU 測試：假裝這台電腦沒有 NVIDIA 顯示卡，程式會改用 CPU 和 small 模型。只給測試用，不在壓縮檔裡。
rem 用法：把這個檔案放在解壓縮出來的 LiveSummary 資料夾「旁邊」（或放進 LiveSummary 資料夾裡），雙擊執行。
rem 原理：環境變數 CUDA_VISIBLE_DEVICES=-1 讓 CUDA 看不到任何顯示卡，程式判斷「沒有顯示卡」。只影響這一次啟動。
set CUDA_VISIBLE_DEVICES=-1
if exist "%~dp0LiveSummary\LiveSummary.exe" (
    start "" "%~dp0LiveSummary\LiveSummary.exe"
) else if exist "%~dp0LiveSummary.exe" (
    start "" "%~dp0LiveSummary.exe"
) else (
    echo 找不到 LiveSummary.exe。請把這個檔案放在 LiveSummary 資料夾旁邊，再雙擊一次。
    pause
)
