# PyInstaller 設定：建出 dist\LiveSummary\（資料夾形式 onedir）。不要直接跑，用 scripts\build_exe.py（會先檢查、清掉舊的、最後驗收與壓縮）。
# 決定與原因見 docs\打包調查.md：
#   - LiveSummary.exe：主程式（app.py），無視窗（console=False），不開黑色命令列視窗。
#   - exe 的檔案內容（版本、說明）從 version.py 產生；assets\icon.ico 存在就當作 exe 與視窗圖示，不存在用預設（打包不會失敗）。
#   - helper.exe：命令列版（helper.py），streamlink／yt_audio 模式給主程式另開程序用（console=True；主程式開它時加 CREATE_NO_WINDOW）。
#   - 兩個 exe 放同一個資料夾、共用 _internal（一個 COLLECT）。
#   - cuBLAS 只帶 cublas64_12.dll、cublasLt64_12.dll → _internal\nvidia\cublas\bin（不帶 cuDNN、nvrtc、nvblas）。
#   - ffmpeg 從 vendor\ffmpeg 帶 ffmpeg.exe＋DLL → _internal\ffmpeg\bin，授權檔 → _internal\ffmpeg\LICENSE.txt（ffplay、ffprobe 不帶）。
#   - 不用 UPX。
import glob
import os

import sys

from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

專案 = os.path.abspath(SPECPATH)          # noqa: F821  SPECPATH 由 PyInstaller 提供
sys.path.insert(0, 專案)
import app_paths  # noqa: E402
import version  # noqa: E402

主程式檔名 = "LiveSummary"
圖示 = os.path.join(專案, app_paths.圖示相對位置)
有圖示 = os.path.isfile(圖示)
print("圖示：" + (圖示 if 有圖示 else "沒有 assets/icon.ico，使用預設圖示"))


def 版本資源檔(原檔名, 說明):
    """exe 的檔案內容（右鍵 → 內容 → 詳細資料）：版本號從 version.py 來。寫成 PyInstaller 要的版本資訊檔，回傳路徑。"""
    四段 = version.版本們()
    資 = version.檔案資訊(原檔名, 說明)
    資訊 = VSVersionInfo(
        ffi=FixedFileInfo(filevers=四段, prodvers=四段, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[StringFileInfo([StringTable("040404B0", [StringStruct(k, v) for k, v in 資.items()])]),
              VarFileInfo([VarStruct("Translation", [0x0404, 1200])])])
    工作資料夾 = CONF["workpath"]                                  # PyInstaller 的 --workpath（build_exe.py 給 build\）
    os.makedirs(工作資料夾, exist_ok=True)
    路徑 = os.path.join(工作資料夾, f"version_{原檔名}.txt")
    with open(路徑, "w", encoding="utf-8") as f:
        f.write(str(資訊))
    return 路徑

site = os.path.join(專案, ".venv", "Lib", "site-packages")

# ---- 資料檔 ----
資料 = []
# faster-whisper 的 VAD 模型（不帶 vad_filter 會壞）
資料 += collect_data_files("faster_whisper", includes=["assets/*.onnx"])
# OpenCC 的字典與設定（*.ocd2、*.json）；clib\bin 的命令列工具、lib、include 不需要
資料 += collect_data_files("opencc", includes=["clib/share/opencc/*"])
# 視窗圖示（app.py 用 app_paths.圖示檔() 找 _internal/assets/icon.ico）；沒放圖示就不收
if 有圖示:
    資料 += [(圖示, "assets")]

# ---- 原樣複製的檔案（ffmpeg、cuBLAS）----
# 不放進 Analysis 的 datas／binaries：PyInstaller 6 會分析 datas 裡的 exe／dll 的相依，把 avcodec-63.dll 等
# 再複製一份到 _internal 最上層（第一次打包多了約 150 MB 重複檔）。改成 Analysis 之後直接加進 COLLECT 的清單，只複製不分析。
原樣 = []
# 隨附 ffmpeg：ffmpeg.exe＋同一個 bin 的 DLL（shared 版要放一起）→ _internal\ffmpeg\bin；授權 → _internal\ffmpeg
ffmpeg來源 = os.path.join(專案, "vendor", "ffmpeg")
for f in [os.path.join(ffmpeg來源, "bin", "ffmpeg.exe")] + sorted(glob.glob(os.path.join(ffmpeg來源, "bin", "*.dll"))):
    原樣.append((os.path.join("ffmpeg", "bin", os.path.basename(f)), f, "DATA"))
原樣.append((os.path.join("ffmpeg", "LICENSE.txt"), os.path.join(ffmpeg來源, "LICENSE.txt"), "DATA"))
# 顯示卡函式庫：只帶轉錄實際載入的 cuBLAS 兩個 DLL → _internal\nvidia\cublas\bin（transcribe 找顯示卡函式庫() 找這裡）
cublas來源 = os.path.join(site, "nvidia", "cublas", "bin")
for f in ("cublas64_12.dll", "cublasLt64_12.dll"):
    原樣.append((os.path.join("nvidia", "cublas", "bin", f), os.path.join(cublas來源, f), "DATA"))

# ---- 動態函式庫、隱藏模組 ----
函式庫 = collect_dynamic_libs("ctranslate2")          # ctranslate2.dll、libiomp5md.dll、它自帶的 cudnn64_9.dll 小檔
隱藏模組 = collect_submodules("streamlink.plugins")    # streamlink 用名稱動態載入外掛，靜態分析找不到

# yt_chat.檢查可中斷等待() 要讀這個模組的原始碼：除了 .pyc 也附 .py
原始碼模式 = {"yt_dlp.downloader.youtube_live_chat": "pyz+py"}

排除 = ["tkinter", "matplotlib", "IPython", "pytest", "_pytest", "pluggy", "iniconfig", "ruff"]   # _pytest 等是 numpy 等的選用匯入帶進來的開發工具


def 分析(腳本, 額外隱藏=()):
    return Analysis(                                  # noqa: F821
        [os.path.join(專案, 腳本)],
        pathex=[專案],
        binaries=函式庫,
        datas=資料,
        hiddenimports=[*隱藏模組, *額外隱藏],
        excludes=排除,
        module_collection_mode=原始碼模式,
        noarchive=False,
    )


主程式 = 分析("app.py")
helper = 分析("helper.py", 額外隱藏=["streamlink_cli.main", "yt_audio"])

主程式pyz = PYZ(主程式.pure)                          # noqa: F821
helperpyz = PYZ(helper.pure)                          # noqa: F821

主程式exe = EXE(                                       # noqa: F821
    主程式pyz, 主程式.scripts, [],
    exclude_binaries=True,
    name=主程式檔名,
    console=False,
    upx=False,
    contents_directory="_internal",
    icon=圖示 if 有圖示 else None,
    version=版本資源檔(主程式檔名 + ".exe", version.產品名),
)
helperexe = EXE(                                      # noqa: F821
    helperpyz, helper.scripts, [],
    exclude_binaries=True,
    name="helper",
    console=True,
    upx=False,
    contents_directory="_internal",
    icon=圖示 if 有圖示 else None,
    version=版本資源檔("helper.exe", version.產品名 + "（內部用的命令列程式）"),
)

COLLECT(                                              # noqa: F821
    主程式exe, 主程式.binaries, 主程式.datas, 原樣,
    helperexe, helper.binaries, helper.datas,
    name="LiveSummary",
    upx=False,
)
