# 打包成 .exe：一個指令建出 dist\LiveSummary\（LiveSummary.exe＋helper.exe＋_internal）和 dist\LiveSummary-v版本號.zip。
#   .venv\Scripts\python.exe scripts\build_exe.py
# 設定在專案根目錄的 LiveSummary.spec；決定與原因見 docs\打包調查.md。
# 步驟：檢查環境（.venv 的 Python 3.13、PyInstaller 版本、vendor\ffmpeg、cuBLAS）→ 清掉舊的 build\LiveSummary、dist\LiveSummary、zip
#   → PyInstaller → 放 LICENSE → 驗收（含 exe 的版本號）（該收的檔案都在、helper.exe 列得出 streamlink 外掛）→ 壓縮 → 印出花費時間與大小。
# 任何一步失敗就停下來並說明，不會留下看起來正常的 zip。
import glob
import os
import shutil
import sys
import time
import zipfile

專案 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, 專案)

import version

名稱 = "LiveSummary"
規格檔 = os.path.join(專案, f"{名稱}.spec")
建置 = os.path.join(專案, "build")
輸出根 = os.path.join(專案, "dist")
輸出 = os.path.join(輸出根, 名稱)
壓縮檔 = os.path.join(輸出根, version.壓縮檔名())          # LiveSummary-v1.0.0.zip（版本號從 version.py 來）
PyInstaller版本 = "6.22.3"            # 和 requirements-dev.txt、requirements-lock.txt 一致

# 打包結果裡一定要有的檔案（相對 dist\LiveSummary）；漏了打包版會在某個功能才壞，所以建完就檢查
必要檔案 = [
    "LiveSummary.exe",
    "helper.exe",
    "LICENSE.txt",                                                   # 本程式 GPLv3
    r"_internal\ffmpeg\bin\ffmpeg.exe",
    r"_internal\ffmpeg\LICENSE.txt",                                 # ffmpeg 的 LGPL v3
    r"_internal\nvidia\cublas\bin\cublas64_12.dll",
    r"_internal\nvidia\cublas\bin\cublasLt64_12.dll",
    r"_internal\faster_whisper\assets\silero_vad_v6.onnx",          # vad_filter 要用
    r"_internal\opencc\clib\share\opencc\s2tw.json",                 # 簡轉繁設定（traditional.py 用 s2tw）
    r"_internal\opencc\clib\share\opencc\STCharacters.ocd2",
    r"_internal\yt_dlp\downloader\youtube_live_chat.py",             # yt_chat.檢查可中斷等待() 讀原始碼
    r"_internal\ctranslate2\ctranslate2.dll",
]
# 不該出現的（決定不帶的大檔）
不該有 = ["cudnn_ops64_9.dll", "cudnn_cnn64_9.dll", "nvrtc64_120_0.dll", "nvblas64_12.dll", "ffplay.exe", "ffprobe.exe"]


def 停(訊息):
    print(f"\n打包失敗：{訊息}")
    sys.exit(1)


def 資料夾大小(路徑):
    return sum(os.path.getsize(os.path.join(路, f)) for 路, _, 檔們 in os.walk(路徑) for f in 檔們)


def MB(位元組):
    return f"{位元組 / 1024 / 1024:,.0f} MB"


def 檢查環境():
    if sys.version_info[:2] != (3, 13):
        停(f"要用 .venv 的 Python 3.13（現在是 {sys.version.split()[0]}）：.venv\\Scripts\\python.exe scripts\\build_exe.py")
    try:
        import PyInstaller
    except ImportError:
        停("沒有 PyInstaller：.venv\\Scripts\\python.exe -m pip install -r requirements-lock.txt")
    if PyInstaller.__version__ != PyInstaller版本:
        停(f"PyInstaller 版本是 {PyInstaller.__version__}，應該是 {PyInstaller版本}（用 requirements-lock.txt 安裝）")
    if not os.path.isfile(os.path.join(專案, "vendor", "ffmpeg", "bin", "ffmpeg.exe")):
        停("沒有隨附的 ffmpeg：先跑 .venv\\Scripts\\python.exe scripts\\下載ffmpeg.py")
    cublas = os.path.join(專案, ".venv", "Lib", "site-packages", "nvidia", "cublas", "bin", "cublas64_12.dll")
    if not os.path.isfile(cublas):
        停(f"找不到 cuBLAS（{cublas}）：用 requirements-lock.txt 安裝 .venv")


def 清掉舊的():
    try:
        for 路徑 in (os.path.join(建置, 名稱), 輸出):
            if os.path.isdir(路徑):
                shutil.rmtree(路徑)
        for 舊壓縮 in glob.glob(os.path.join(輸出根, f"{名稱}*.zip")):         # 含舊版本號、沒版本號的舊檔
            os.remove(舊壓縮)
    except OSError as e:
        停(f"刪不掉上次的打包結果（{e}）：LiveSummary.exe 還開著、或有視窗／終端機正開在 dist 裡面？關掉再跑一次")


def 打包():
    import PyInstaller.__main__
    PyInstaller.__main__.run([規格檔, "--noconfirm", "--clean",
                              "--distpath", 輸出根, "--workpath", 建置, "--log-level", "WARN"])


def 檢查版本(路徑, 期望檔名):
    """exe 的檔案內容（詳細資料）裡的版本號要等於 version.py。"""
    import pefile
    pe = pefile.PE(路徑, fast_load=False)
    try:
        表 = {}
        for 資訊 in getattr(pe, "FileInfo", []) or []:
            for 項 in 資訊:
                for 字串表 in getattr(項, "StringTable", []) or []:
                    表.update({k.decode(): v.decode() for k, v in 字串表.entries.items()})
    finally:
        pe.close()
    if 表.get("FileVersion") != version.版本 or 表.get("ProductVersion") != version.版本:
        停(f"{期望檔名} 的版本資訊不對（要 {version.版本}，實際 FileVersion={表.get('FileVersion')}、ProductVersion={表.get('ProductVersion')}）")


def 驗收():
    缺 = [f for f in 必要檔案 if not os.path.isfile(os.path.join(輸出, f))]
    if 缺:
        停("打包結果缺少：\n  " + "\n  ".join(缺))
    exe們 = sorted(f for f in os.listdir(輸出) if f.lower().endswith(".exe"))
    if exe們 != ["LiveSummary.exe", "helper.exe"]:
        停(f"dist 的 LiveSummary 資料夾裡應該只有 LiveSummary.exe 和 helper.exe 兩個 exe，實際是：{exe們}")
    多 = [os.path.relpath(os.path.join(路, f), 輸出) for 路, _, 檔們 in os.walk(輸出) for f in 檔們 if f in 不該有]
    # ffmpeg 的 DLL 只該在 _internal\ffmpeg\bin（spec 不讓 PyInstaller 分析它；出現在別處就是又被複製了一份）
    ffmpeg的dll = {f for f in os.listdir(os.path.join(輸出, "_internal", "ffmpeg", "bin")) if f.endswith(".dll")}
    多 += [os.path.join("_internal", f) for f in os.listdir(os.path.join(輸出, "_internal")) if f in ffmpeg的dll]
    if 多:
        停("打包結果有不該帶的檔案：\n  " + "\n  ".join(多))
    for 檔名 in ("LiveSummary.exe", "helper.exe"):
        檢查版本(os.path.join(輸出, 檔名), 檔名)
    # streamlink 外掛是用名稱動態載入的：helper.exe 實際列一次，確認收進去了（不連網）
    import external
    結果 = external.執行([os.path.join(輸出, "helper.exe"), "--streamlink", "--plugins"],
                       timeout=120, capture_output=True)
    文字 = (結果.stdout or b"").decode("utf-8", "replace")
    if 結果.returncode != 0 or "twitch" not in 文字 or "youtube" not in 文字:
        停(f"helper.exe 列不出 streamlink 的 twitch／youtube 外掛（結束碼 {結果.returncode}）：\n"
          + 文字[-500:] + (結果.stderr or b"").decode("utf-8", "replace")[-500:])
    外掛數 = len([x for x in 文字.split(":", 1)[-1].split(",") if x.strip()])
    print(f"驗收通過：必要檔案 {len(必要檔案)} 個都在、三個 exe 的版本都是 {version.版本}、沒有不該帶的檔案；helper.exe 列出 streamlink 外掛 {外掛數} 個")


def 壓縮():
    with zipfile.ZipFile(壓縮檔, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for 路, _, 檔們 in os.walk(輸出):
            for f in 檔們:
                完整 = os.path.join(路, f)
                z.write(完整, os.path.relpath(完整, 輸出根))      # 壓縮檔裡是 LiveSummary\…（解開就是一個資料夾）


def main():
    開始 = time.monotonic()
    檢查環境()
    清掉舊的()
    print("PyInstaller 打包中（約幾分鐘）…")
    打包()
    shutil.copyfile(os.path.join(專案, "LICENSE"), os.path.join(輸出, "LICENSE.txt"))
    驗收()
    打包秒 = time.monotonic() - 開始
    print("壓縮中…")
    壓縮()
    總秒 = time.monotonic() - 開始
    print(f"\n完成：{輸出}（{MB(資料夾大小(輸出))}）")
    print(f"      {壓縮檔}（{MB(os.path.getsize(壓縮檔))}）")
    print(f"花費：打包＋驗收 {打包秒:.0f} 秒，壓縮 {總秒 - 打包秒:.0f} 秒，共 {總秒:.0f} 秒")


if __name__ == "__main__":
    main()
