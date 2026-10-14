# PyInstaller 設定：建出 dist\LiveSummary\（資料夾形式 onedir）。不要直接跑，用 scripts\build_exe.py（會先檢查、清掉舊的、最後驗收與壓縮）。
# 決定與原因見 docs\打包調查.md：
#   - LiveSummary.exe：主程式（app.py），無視窗（console=False），不開黑色命令列視窗。
#   - helper.exe：命令列版（helper.py），streamlink／yt_audio 模式給主程式另開程序用（console=True；主程式開它時加 CREATE_NO_WINDOW）。
#   - 兩個 exe 放同一個資料夾、共用 _internal（一個 COLLECT）。
#   - cuBLAS 只帶 cublas64_12.dll、cublasLt64_12.dll → _internal\nvidia\cublas\bin（不帶 cuDNN、nvrtc、nvblas）。
#   - ffmpeg 從 vendor\ffmpeg 帶 ffmpeg.exe＋DLL → _internal\ffmpeg\bin，授權檔 → _internal\ffmpeg\LICENSE.txt（ffplay、ffprobe 不帶）。
#   - 不用 UPX。
import glob
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

專案 = os.path.abspath(SPECPATH)          # noqa: F821  SPECPATH 由 PyInstaller 提供
site = os.path.join(專案, ".venv", "Lib", "site-packages")

# ---- 資料檔 ----
資料 = []
# faster-whisper 的 VAD 模型（不帶 vad_filter 會壞）
資料 += collect_data_files("faster_whisper", includes=["assets/*.onnx"])
# OpenCC 的字典與設定（*.ocd2、*.json）；clib\bin 的命令列工具、lib、include 不需要
資料 += collect_data_files("opencc", includes=["clib/share/opencc/*"])

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

排除 = ["tkinter", "matplotlib", "IPython", "pytest", "ruff"]


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
    name="LiveSummary",
    console=False,
    upx=False,
    contents_directory="_internal",
)
helperexe = EXE(                                      # noqa: F821
    helperpyz, helper.scripts, [],
    exclude_binaries=True,
    name="helper",
    console=True,
    upx=False,
    contents_directory="_internal",
)

COLLECT(                                              # noqa: F821
    主程式exe, 主程式.binaries, 主程式.datas, 原樣,
    helperexe, helper.binaries, helper.datas,
    name="LiveSummary",
    upx=False,
)
