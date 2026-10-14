# 檔案位置（唯一來源）：程式讀寫的每個檔案都從這裡拿路徑，其他 .py 不自己組資料或輸出的位置。
#   程式資料（config.json、介面設定、網址紀錄、版面配置、詞庫、logs、翻譯錯誤紀錄）→ %LOCALAPPDATA%\直播摘要
#   使用者看的輸出（直播稿、摘要、聊天室、逐句翻譯、音訊）                          →「文件」\直播摘要
# 直接跑 app.py 和打包成 .exe 用同一套位置，不往程式資料夾寫東西。
# 兩個根目錄都用 Windows 的 Known Folder API（SHGetKnownFolderPath）取得，不寫死 C:\Users\名字\Documents：
# 「文件」被 OneDrive 或其他磁碟接管時，拿到的就是接管後的位置。帳號名稱是中文也照常（全程用 Unicode 字串）。
#
# 搬家：第一次啟動時，新的資料位置還沒有資料、舊位置（專案資料夾）有 → 用「複製」搬過去（舊檔不動、不刪），
# 結果寫進 logs\搬家紀錄.txt 並回傳給介面說一聲。新位置已經有任何檔案就完全不碰（只有空資料夾不算）。舊的輸出檔不搬（使用者的決定）。
import os
import shutil
import sys
import time

程式名 = "直播摘要"

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
    """程式資料的根目錄：%LOCALAPPDATA%\\直播摘要。"""
    if "資料" in _覆寫:
        return _覆寫["資料"]
    根 = _known_folder(FOLDERID_LocalAppData) or os.environ.get("LOCALAPPDATA") \
        or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(根, 程式名)


def 輸出資料夾():
    """使用者看的輸出：「文件」\\直播摘要（文件被 OneDrive／其他磁碟接管時跟著走）。"""
    if "輸出" in _覆寫:
        return _覆寫["輸出"]
    根 = _known_folder(FOLDERID_Documents) or os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(根, 程式名)


def 舊資料位置():
    """搬家的來源：沒打包時是專案資料夾；打包版沒有舊位置（None）。"""
    if "舊" in _覆寫:
        return _覆寫["舊"]
    return None if 已打包() else os.path.dirname(os.path.abspath(__file__))


def 設定根目錄(資料=None, 輸出=None, 舊=None):
    """測試用：把資料／輸出／舊位置換成指定的資料夾（舊=None 表示沒有舊位置）。要在 import 其他模組前呼叫，
    因為 config、ui_state 等模組載入時就把路徑存成模組變數。"""
    _覆寫.clear()
    if 資料 is not None:
        _覆寫["資料"] = str(資料)
    if 輸出 is not None:
        _覆寫["輸出"] = str(輸出)
    _覆寫["舊"] = None if 舊 is None else str(舊)


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


def YouTube聊天室紀錄檔():
    return os.path.join(日誌資料夾(), "YouTube聊天室_紀錄.txt")


def 搬家紀錄檔():
    return os.path.join(日誌資料夾(), "搬家紀錄.txt")


# ---- 啟動準備與搬家 ----
def _有資料(資料夾):
    """資料夾裡（含子資料夾）有任何檔案。上次搬家失敗後留下的東西不算：啟動準備 建的空資料夾（詞庫、logs）、
    記錄失敗原因的 logs\\搬家紀錄.txt（下次啟動會再試）。"""
    for 路, _, 檔們 in os.walk(資料夾):
        if any(os.path.join(路, f) != os.path.join(資料夾, "logs", "搬家紀錄.txt") for f in 檔們):
            return True
    return False


def 搬舊資料(舊=None, 新=None):
    """新位置沒有資料、舊位置有 → 把 搬家項目 複製過去，回傳複製了哪些（名稱清單）；其他情況回傳 []。
    先複製到旁邊的暫存資料夾，全部成功才改名成正式位置：複製到一半失敗不會留下半套資料（下次啟動會再試）。
    舊位置的檔案一律不動。"""
    舊 = 舊資料位置() if 舊 is None else 舊
    新 = 資料資料夾() if 新 is None else 新
    if not 舊 or not os.path.isdir(舊) or _有資料(新):
        return []
    if os.path.normcase(os.path.abspath(舊)) == os.path.normcase(os.path.abspath(新)):
        return []
    要搬 = [名 for 名 in 搬家項目 if os.path.exists(os.path.join(舊, 名))]
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
    try:
        搬了 = 搬舊資料()
        if 搬了:
            訊息 = (f"已把舊資料從 {舊資料位置()} 複製到 {資料資料夾()}：" + "、".join(搬了)
                    + "（舊檔沒有刪除）")
    except Exception as e:      # noqa: BLE001  搬不成也要能開程式，用空白設定照常啟動
        訊息 = f"舊資料複製失敗（{type(e).__name__}：{e}），這次用新的空白資料啟動；舊檔都還在 {舊資料位置()}"
    for 資料夾 in (資料資料夾(), 詞庫資料夾(), 日誌資料夾(), 輸出資料夾()):
        os.makedirs(資料夾, exist_ok=True)
    if 訊息:
        try:
            with open(搬家紀錄檔(), "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + 訊息 + "\n")
        except OSError:
            pass
    return 訊息
