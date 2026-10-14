# 檔案位置（唯一來源）：程式讀寫的每個檔案都從這裡拿路徑，其他 .py 不自己組資料或輸出的位置。
#   程式資料（config.json、介面設定、網址紀錄、版面配置、詞庫、logs、翻譯錯誤紀錄）→ %LOCALAPPDATA%\LiveSummary
#   使用者看的輸出（直播稿、摘要、聊天室、逐句翻譯）                                →「文件」\直播摘要（給人看的，維持中文）
#   除錯用的音訊（每場一個資料夾，只留最近 5 場）                                   → %LOCALAPPDATA%\LiveSummary\音訊
#     不放「文件」：音訊很大，「文件」常被 OneDrive 接管會自動上傳。程式沒有任何功能會讀這些音訊（只供人工除錯）。
# 直接跑 app.py 和打包成 .exe 用同一套位置，不往程式資料夾寫東西。
# 程式自己帶的唯讀檔案（隨附的 ffmpeg、helper.exe、顯示卡函式庫）的位置也在這裡決定（見「程式自己帶的檔案」）。
# 兩個根目錄都用 Windows 的 Known Folder API（SHGetKnownFolderPath）取得，不寫死 C:\Users\名字\Documents：
# 「文件」被 OneDrive 或其他磁碟接管時，拿到的就是接管後的位置。帳號名稱是中文也照常（全程用 Unicode 字串）。
#
# 搬家：第一次啟動時，新的資料位置還沒有資料、舊位置有 → 用「複製」搬過去（舊檔不動、不刪），
# 結果寫進 logs\搬家紀錄.txt 並回傳給介面說一聲。新位置已經有任何檔案就完全不碰（只有空資料夾不算）。舊的輸出檔不搬（使用者的決定）。
# 舊位置依序找，第一個有程式資料的才搬（只搬一個來源，不混在一起）：
#   1. %LOCALAPPDATA%\直播摘要（2026-10-14 打包第4步改名前的資料位置；開發和打包版都看）
#   2. 專案資料夾（第2步以前的位置；只有開發時）——1 有資料時一定比 2 新（當初就是從 2 複製到 1），所以 1 優先。
#   舊位置的除錯用音訊（直播摘要\音訊）不搬：很大、只供人工除錯。
import glob
import os
import re
import shutil
import sys
import time

程式名 = "直播摘要"            # 「文件」裡輸出資料夾的名稱（給人看的，維持中文）；也是改名前的資料資料夾名
資料夾英文名 = "LiveSummary"    # %LOCALAPPDATA% 裡程式資料的資料夾名（和 LiveSummary.exe、打包資料夾同名）

# Known Folder ID（Microsoft Learn「KNOWNFOLDERID」）
FOLDERID_Documents = "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"
FOLDERID_LocalAppData = "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}"

# 舊位置（專案資料夾）要搬的程式資料；舊的輸出檔、overlay_位置.json（已經沒有程式讀）不搬
搬家項目 = ("config.json", "config.backup.json", "介面設定.json", "網址紀錄.json", "版面配置.json",
          "翻譯錯誤紀錄.txt", "詞庫", "logs")

_覆寫 = {}          # 測試用：設定根目錄() 指定的位置


def 已打包():
    return bool(getattr(sys, "frozen", False))


def _known_folder(folder_id):
    """SHGetKnownFolderPath → 路徑字串；拿不到回傳 None。"""
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        u = uuid.UUID(folder_id)
        g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        結果 = ctypes.c_wchar_p()
        函式 = ctypes.windll.shell32.SHGetKnownFolderPath
        函式.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
        函式.restype = ctypes.c_long
        if 函式(ctypes.byref(g), 0, None, ctypes.byref(結果)) != 0:
            return None
        try:
            return 結果.value
        finally:
            ctypes.windll.ole32.CoTaskMemFree(結果)
    except Exception:       # noqa: BLE001  不是 Windows 或 API 失敗：交給呼叫端用備援
        return None


def 資料資料夾():
    """程式資料的根目錄：%LOCALAPPDATA%\\LiveSummary。"""
    if "資料" in _覆寫:
        return _覆寫["資料"]
    return os.path.join(_LocalAppData(), 資料夾英文名)


def _LocalAppData():
    return _known_folder(FOLDERID_LocalAppData) or os.environ.get("LOCALAPPDATA") \
        or os.path.join(os.path.expanduser("~"), "AppData", "Local")


def 輸出資料夾():
    """使用者看的輸出：「文件」\\直播摘要（文件被 OneDrive／其他磁碟接管時跟著走）。"""
    if "輸出" in _覆寫:
        return _覆寫["輸出"]
    根 = _known_folder(FOLDERID_Documents) or os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(根, 程式名)


def 舊資料位置們():
    """搬家的來源，依優先順序：%LOCALAPPDATA%\\直播摘要（改名前的資料位置）、專案資料夾（只有沒打包時）。"""
    if "舊" in _覆寫:
        return _位置清單(_覆寫["舊"])
    位置們 = [os.path.join(_LocalAppData(), 程式名)]
    if not 已打包():
        位置們.append(os.path.dirname(os.path.abspath(__file__)))
    return 位置們


def _位置清單(舊):
    """None → []；一個路徑 → [路徑]；清單 → 原順序。"""
    if 舊 is None:
        return []
    if isinstance(舊, (str, os.PathLike)):
        return [str(舊)]
    return [str(x) for x in 舊]


def 設定根目錄(資料=None, 輸出=None, 舊=None):
    """測試用：把資料／輸出／舊位置換成指定的資料夾（舊=None 表示沒有舊位置；可給一個路徑或依優先順序的清單）。
    要在 import 其他模組前呼叫，因為 config、ui_state 等模組載入時就把路徑存成模組變數。"""
    _覆寫.clear()
    if 資料 is not None:
        _覆寫["資料"] = str(資料)
    if 輸出 is not None:
        _覆寫["輸出"] = str(輸出)
    _覆寫["舊"] = _位置清單(舊)


# ---- 各個檔案 ----
def 設定檔():
    return os.path.join(資料資料夾(), "config.json")


def 網址紀錄檔():
    return os.path.join(資料資料夾(), "網址紀錄.json")


def 介面設定檔():
    return os.path.join(資料資料夾(), "介面設定.json")


def 版面檔():
    return os.path.join(資料資料夾(), "版面配置.json")


def 翻譯錯誤紀錄檔():
    return os.path.join(資料資料夾(), "翻譯錯誤紀錄.txt")


def 詞庫資料夾():
    return os.path.join(資料資料夾(), "詞庫")


def 日誌資料夾():
    return os.path.join(資料資料夾(), "logs")


def 音訊資料夾():
    """除錯用音訊的根目錄（每場一個子資料夾，見 音訊場資料夾名）。"""
    return os.path.join(資料資料夾(), "音訊")


def YouTube聊天室紀錄檔():
    return os.path.join(日誌資料夾(), "YouTube聊天室_紀錄.txt")


def 搬家紀錄檔():
    return os.path.join(日誌資料夾(), "搬家紀錄.txt")


def 摘要格式紀錄檔():
    return os.path.join(日誌資料夾(), "摘要格式紀錄.txt")


def 當機紀錄檔():
    return os.path.join(日誌資料夾(), "當機紀錄.txt")


# ---- 程式自己帶的檔案：外部程式、顯示卡函式庫（唯讀；開發和打包版位置不同）----
# 開發（直接跑 app.py）：專案資料夾；隨附的 ffmpeg 放 vendor\ffmpeg（scripts\下載ffmpeg.py 下載，不進 git）。
# 打包版（PyInstaller 資料夾形式）：sys._MEIPASS（= exe 旁邊的 _internal）；helper.exe 和主程式 exe 在同一個資料夾。
# 怎麼呼叫這些程式（指令、不開黑色視窗）由 external.py 決定，這裡只管「在哪裡」。
隨附資料夾名 = "vendor"          # 開發時隨附外部程式的資料夾（.gitignore）
helper檔名 = "helper.exe"        # 打包版的命令列版 exe（streamlink、yt_audio 模式）


def 程式資料夾():
    """程式自己的檔案在哪：打包版 sys._MEIPASS；開發是專案資料夾。"""
    if 已打包():
        return getattr(sys, "_MEIPASS", None) or os.path.join(os.path.dirname(sys.executable), "_internal")
    return os.path.dirname(os.path.abspath(__file__))


圖示相對位置 = os.path.join("assets", "icon.ico")      # 程式圖示（Ray 提供）；沒有這個檔就用預設圖示，打包也不會失敗


def 圖示檔():
    """程式圖示 .ico 的位置（開發：專案\\assets\\icon.ico；打包版：_internal\\assets\\icon.ico）；沒有這個檔回傳 None。"""
    路徑 = os.path.join(程式資料夾(), 圖示相對位置)
    return 路徑 if os.path.isfile(路徑) else None


def 隨附ffmpeg資料夾():
    """隨附的 ffmpeg（BtbN 壓縮檔解開的內容：bin、LICENSE…）：打包版 _internal\\ffmpeg、開發 vendor\\ffmpeg。"""
    根 = 程式資料夾() if 已打包() else os.path.join(程式資料夾(), 隨附資料夾名)
    return os.path.join(根, "ffmpeg")


def 隨附ffmpeg():
    """隨附的 ffmpeg.exe 應該在的位置（不保證存在）。BtbN 的 shared 版 ffmpeg.exe 要和同一個 bin 裡的 av*.dll、sw*.dll 放一起。"""
    return os.path.join(隨附ffmpeg資料夾(), "bin", "ffmpeg.exe")


def _系統ffmpeg():
    路徑 = shutil.which("ffmpeg")
    if 路徑:
        return 路徑
    # 剛用 winget 裝好時，目前視窗可能還找不到，到安裝位置找
    候選 = glob.glob(os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\**\bin\ffmpeg.exe"), recursive=True)
    return 候選[0] if 候選 else None


def ffmpeg位置():
    """要用的 ffmpeg → (路徑, 來源)：隨附的優先（來源「隨附」），沒有才找系統上的（「系統」）；都沒有 (None, None)。"""
    隨附 = 隨附ffmpeg()
    if os.path.isfile(隨附):
        return 隨附, "隨附"
    系統 = _系統ffmpeg()
    return (系統, "系統") if 系統 else (None, None)


def helper執行檔():
    """打包版的 helper.exe（和主程式 exe 同一個資料夾）；開發時不用它。"""
    return os.path.join(os.path.dirname(sys.executable), helper檔名)


def yt_audio腳本():
    """開發時另開 python 執行的 yt_audio.py（打包版改用 helper.exe --yt-audio）。"""
    return os.path.join(程式資料夾(), "yt_audio.py")


def 顯示卡函式庫資料夾們():
    """CUDA 函式庫（cuBLAS 等）所在的 bin 資料夾們：打包版 _internal\\nvidia\\*\\bin；
    開發是 pip 裝的 site-packages\\nvidia\\*\\bin。找不到回傳空清單。"""
    if 已打包():
        根們 = [程式資料夾()]
    else:
        import site
        根們 = site.getsitepackages()
    結果 = []
    for 根 in 根們:
        nv = os.path.join(根, "nvidia")
        if not os.path.isdir(nv):
            continue
        for 子 in sorted(os.listdir(nv)):
            bin路徑 = os.path.join(nv, 子, "bin")
            if os.path.isdir(bin路徑):
                結果.append(bin路徑)
    return 結果


# ---- 除錯用音訊：命名與只留最近幾場 ----
音訊保留場數 = 5          # 含正在錄的這一場
_音訊場名格式 = re.compile(r"^.+_\d{8}_\d{6}_音訊$")       # 程式自己產生的格式：開頭_YYYYMMDD_HHMMSS_音訊


def 音訊場資料夾名(開頭, 時間字):
    """一場直播的音訊資料夾名（時間字 = YYYYMMDD_HHMMSS）。和直播稿同一個開頭與時間字。"""
    return f"{開頭}_{時間字}_音訊"


def _是程式的音訊資料夾(路徑):
    """名稱符合程式產生的格式、是真的資料夾（不是捷徑／連接點）、裡面只有 .wav 檔。其他東西一律不碰。"""
    名 = os.path.basename(路徑)
    if not _音訊場名格式.match(名) or os.path.islink(路徑) or not os.path.isdir(路徑):
        return False
    if hasattr(os.path, "isjunction") and os.path.isjunction(路徑):
        return False
    try:
        with os.scandir(路徑) as 項們:
            return all(e.is_file(follow_symlinks=False) and e.name.lower().endswith(".wav") for e in 項們)
    except OSError:
        return False


def 清理舊音訊(保留=音訊保留場數 - 1, 目錄=None):
    """音訊根目錄底下，名稱符合格式的資料夾只留最近 保留 個（依名稱裡的時間，同時間再看修改時間），其餘刪掉；回傳刪掉的名稱。
    開始新的一場時用預設值呼叫：留 4 個舊的，加上即將建立的這一場 = 5 場。
    只刪音訊根目錄底下、名稱符合格式的資料夾；其他檔案或資料夾一律不碰；目錄不存在或刪不掉都不出錯。"""
    目錄 = 音訊資料夾() if 目錄 is None else 目錄
    try:
        名們 = [n for n in os.listdir(目錄) if _是程式的音訊資料夾(os.path.join(目錄, n))]
    except OSError:
        return []

    def 排序鍵(名):
        時間字 = "_".join(名.split("_")[-3:-1])
        try:
            修改 = os.path.getmtime(os.path.join(目錄, 名))
        except OSError:
            修改 = 0
        return (時間字, 修改)
    名們.sort(key=排序鍵)
    刪掉 = []
    for 名 in 名們[:max(0, len(名們) - max(0, 保留))]:
        try:
            shutil.rmtree(os.path.join(目錄, 名))
            刪掉.append(名)
        except OSError:
            pass
    return 刪掉


# ---- 啟動準備與搬家 ----
def _有資料(資料夾):
    """資料夾裡（含子資料夾）有任何檔案。上次搬家失敗後留下的東西不算：啟動準備 建的空資料夾（詞庫、logs）、
    記錄失敗原因的 logs\\搬家紀錄.txt（下次啟動會再試）。"""
    for 路, _, 檔們 in os.walk(資料夾):
        if any(os.path.join(路, f) != os.path.join(資料夾, "logs", "搬家紀錄.txt") for f in 檔們):
            return True
    return False


def 搬家來源(舊=None, 新=None):
    """要從哪裡搬 → (來源, 要搬的名稱清單)；不用搬回傳 (None, [])。舊 = 一個路徑或依優先順序的清單（預設 舊資料位置們()）。
    新位置已有資料就不搬；舊位置依序看，第一個有 搬家項目 的就是來源（只搬一個來源，不混在一起）。"""
    舊們 = 舊資料位置們() if 舊 is None else _位置清單(舊)
    新 = 資料資料夾() if 新 is None else 新
    if _有資料(新):
        return None, []
    for 位置 in 舊們:
        if not os.path.isdir(位置):
            continue
        if os.path.normcase(os.path.abspath(位置)) == os.path.normcase(os.path.abspath(新)):
            continue
        要搬 = [名 for 名 in 搬家項目 if os.path.exists(os.path.join(位置, 名))]
        if 要搬:
            return 位置, 要搬
    return None, []


def 搬舊資料(舊=None, 新=None):
    """新位置沒有資料、舊位置有 → 把 搬家項目 從第一個有資料的舊位置（見 搬家來源）複製過去，
    回傳複製了哪些（名稱清單）；其他情況回傳 []。
    先複製到旁邊的暫存資料夾，全部成功才改名成正式位置：複製到一半失敗不會留下半套資料（下次啟動會再試）。
    舊位置的檔案一律不動。"""
    新 = 資料資料夾() if 新 is None else 新
    舊, 要搬 = 搬家來源(舊, 新)
    if not 要搬:
        return []
    暫存 = 新 + ".搬家中"
    if os.path.isdir(暫存):
        shutil.rmtree(暫存)          # 上次搬到一半失敗留下的（是複製品，舊檔還在）
    os.makedirs(暫存)
    try:
        for 名 in 要搬:
            來源 = os.path.join(舊, 名)
            if os.path.isdir(來源):
                shutil.copytree(來源, os.path.join(暫存, 名))
            else:
                shutil.copy2(來源, os.path.join(暫存, 名))
        if os.path.isdir(新):
            shutil.rmtree(新)            # 新位置只有空資料夾、沒有任何檔案（_有資料 已確認）
        os.replace(暫存, 新)
    except BaseException:
        shutil.rmtree(暫存, ignore_errors=True)
        raise
    return 要搬


def 啟動準備():
    """程式啟動時呼叫一次：需要時從舊位置複製資料，建好資料／輸出資料夾。
    回傳要告訴使用者的一句話（沒搬東西是空字串）；搬家失敗不擋啟動，原因寫在回傳的句子裡。"""
    訊息 = ""
    來源 = None
    try:
        來源 = 搬家來源()[0]
        搬了 = 搬舊資料(來源) if 來源 else []
        if 搬了:
            訊息 = (f"已把舊資料從 {來源} 複製到 {資料資料夾()}：" + "、".join(搬了)
                    + "（舊檔沒有刪除）")
    except Exception as e:      # noqa: BLE001  搬不成也要能開程式，用空白設定照常啟動
        訊息 = f"舊資料複製失敗（{type(e).__name__}：{e}），這次用新的空白資料啟動；舊檔都還在 {來源 or '舊位置'}"
    for 資料夾 in (資料資料夾(), 詞庫資料夾(), 日誌資料夾(), 輸出資料夾()):      # 音訊資料夾第一次存音訊時才建
        os.makedirs(資料夾, exist_ok=True)
    if 訊息:
        try:
            with open(搬家紀錄檔(), "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + 訊息 + "\n")
        except OSError:
            pass
    return 訊息
