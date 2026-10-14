# 另開程序（外部程式）：程式裡所有另開的程序都經過這裡的 開啟()，由它統一加上 CREATE_NO_WINDOW，
# 主程式是無視窗模式（打包後的 .exe、或用 pythonw 開），沒加的話每開一個 streamlink／ffmpeg 就閃一個黑色命令列視窗。
# 其他 .py 不直接用 subprocess.Popen／run；要新增外部程式呼叫也一律用 開啟() 或 執行()。
#
# 「開發還是打包後」的判斷與各程式的位置在 app_paths（已打包、隨附ffmpeg、helper執行檔…），這裡只決定指令怎麼組：
#   streamlink：開發 python -m streamlink_cli …；打包後 helper.exe --streamlink …
#   yt_audio  ：開發 python yt_audio.py 網址 串流名；打包後 helper.exe --yt-audio 網址 串流名
#   （打包後 sys.executable 是主程式 exe 本身，不能 -m；helper.exe 是同一個打包資料夾裡的命令列版 exe，進入點 helper.py）
import subprocess
import sys

import app_paths

不開視窗 = getattr(subprocess, "CREATE_NO_WINDOW", 0)       # 不是 Windows 時是 0（不影響）


def 開啟(指令, **選項):
    """另開程序（subprocess.Popen）並一律加上 CREATE_NO_WINDOW；選項照 Popen。"""
    選項["creationflags"] = 選項.get("creationflags", 0) | 不開視窗
    return subprocess.Popen(list(指令), **選項)        # noqa: S603  指令都是程式自己組的（見下面各函式）


def 執行(指令, timeout=None, capture_output=False, **選項):
    """跑完一個程式再回來（像 subprocess.run，但經過 開啟()）。逾時會殺掉子程序再丟出 TimeoutExpired。"""
    if capture_output:
        選項["stdout"] = 選項["stderr"] = subprocess.PIPE
    with 開啟(指令, **選項) as 子:
        try:
            輸出, 錯誤 = 子.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            子.kill()
            子.communicate()
            raise
    return subprocess.CompletedProcess(子.args, 子.returncode, 輸出, 錯誤)


def streamlink指令(*參數):
    """跑 streamlink 命令列的指令（參數照 streamlink 命令列）。"""
    if app_paths.已打包():
        return [app_paths.helper執行檔(), "--streamlink", *參數]
    return [sys.executable, "-m", "streamlink_cli", *參數]


def yt_audio指令(網址, 串流名):
    """YouTube 音訊擷取（yt_audio：streamlink --stdout ＋ 第一個片段的 PDT）的指令。"""
    if app_paths.已打包():
        return [app_paths.helper執行檔(), "--yt-audio", 網址, 串流名]
    return [sys.executable, app_paths.yt_audio腳本(), 網址, 串流名]
