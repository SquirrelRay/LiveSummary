# 第一次使用：檢查這台電腦、轉錄模型的下載（純 Python，不碰介面，方便單獨測試）。
#
# 1. 檢查這台電腦（首次引導第 2 頁）：NVIDIA 顯示卡、ffmpeg、streamlink，各回傳一個 檢查結果（好／注意／錯 ＋ 一句短標籤）。
#    顯示卡只做輕量偵測：問顯示卡函式庫「有幾張可用的 NVIDIA 顯示卡」（不載入轉錄模型、不做運算），
#    看不到時再用 nvidia-smi 分辨「沒有顯示卡」與「有顯示卡但目前無法使用」；整個過程超過 逾時秒 就當作「無法確認」。
# 2. 轉錄模型：
#    已下載：faster-whisper 用 Hugging Face 的快取（%USERPROFILE%\.cache\huggingface\hub\models--組織--名稱），
#            快取裡找得到 model.bin、config.json、tokenizer.json 就算已下載（只查檔案，不連網）。
#    要用哪一個：有可用的 NVIDIA 顯示卡 → 顯示卡用的模型（config.json 的 whisper_model，出廠 large-v3-turbo）；沒有 → CPU 用的 small。
#    下載：自己先呼叫 faster-whisper 的 download_model（和 WhisperModel 內部用的是同一個函式、同樣的檔案），
#          下載中每 0.5 秒量一次快取資料夾裡這次寫入的檔案大小，送出 model 事件（已下載／總大小）；
#          總大小查不到（表裡沒有的模型）時 總 = None，介面改用會動的進度條＋已等時間。
#    失敗：連不上網路、硬碟空間不夠、其他，各用一句白話說明（模型下載錯誤）。
# model 事件的狀態：將下載（開始擷取前預告，啟動面板就不會先收起）→ 下載中 → 完成／失敗；模型載入好了送「就緒」。
import glob
import importlib.util
import os
import shutil
import subprocess
import threading
import time

import events

好, 注意, 錯 = "好", "注意", "錯"
符號 = {好: "✓", 注意: "⚠", 錯: "✕"}
逾時秒 = 4.0                 # 顯示卡偵測最多等幾秒

# 轉錄模型的檔案總大小（位元組，faster-whisper 會下載的那幾個檔加起來）。
# 2026-10-14 查：Hugging Face 模型頁的檔案清單（mobiuslabsgmbh/faster-whisper-large-v3-turbo：model.bin 1.62 GB；
# Systran/faster-whisper-small：model.bin 484 MB），並用這台電腦快取裡實際下載好的檔案逐一核對位元組數。
模型大小 = {
    "large-v3-turbo": 1_621_665_983,
    "turbo": 1_621_665_983,
    "small": 486_212_372,
    "medium": 1_530_571_735,
}
必要檔們 = ("model.bin", "config.json", "tokenizer.json")


class 模型下載錯誤(Exception):
    """轉錄模型下載失敗（訊息是白話）。"""


def 檢查結果(等級, 標籤):
    return {"等級": 等級, "標籤": 標籤}


def 結果字(結果):
    return f"{符號[結果['等級']]} {結果['標籤']}"


# ---------- 顯示卡 ----------
def 顯示卡數():
    """可用的 NVIDIA 顯示卡數量（只問函式庫，不載入模型）。"""
    import transcribe
    transcribe.找顯示卡函式庫()
    import ctranslate2
    return ctranslate2.get_cuda_device_count()


def 有NVIDIA驅動():
    """nvidia-smi 列得出顯示卡 = 這台電腦有 NVIDIA 顯示卡（驅動程式有裝）。"""
    路徑 = shutil.which("nvidia-smi")
    if not 路徑:
        return False
    try:
        r = subprocess.run([路徑, "-L"], check=False, capture_output=True, text=True, timeout=2,       # noqa: S603  固定的指令與參數
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and "GPU" in r.stdout


def 檢查顯示卡(逾時=None, 數卡=None, 查驅動=None):
    """回傳 (檢查結果, 可用)。可用：True／False；逾時或出錯是 None（開始後由程式自己判斷）。"""
    逾時 = 逾時秒 if 逾時 is None else 逾時
    數卡, 查驅動 = 數卡 or 顯示卡數, 查驅動 or 有NVIDIA驅動
    結果 = {}

    def 做():
        try:
            n = 數卡()
            結果["值"] = ("可用", n) if n > 0 else ("有卡不能用" if 查驅動() else "沒有", n)
        except Exception:                     # noqa: BLE001  偵測失敗就當作無法確認
            結果["值"] = ("不明", 0)
    t = threading.Thread(target=做, daemon=True, name="偵測顯示卡")
    t.start()
    t.join(逾時)
    狀況 = 結果.get("值", ("不明", 0))[0]
    if 狀況 == "可用":
        return 檢查結果(好, "NVIDIA 顯示卡：可即時轉錄"), True
    if 狀況 == "沒有":
        return 檢查結果(注意, "沒有 NVIDIA 顯示卡：轉錄會比較慢，可能跟不上直播"), False
    if 狀況 == "有卡不能用":
        return 檢查結果(注意, "NVIDIA 顯示卡目前無法使用：轉錄會比較慢"), False
    return 檢查結果(注意, "無法確認顯示卡：開始後會自動判斷"), None


# ---------- ffmpeg、streamlink ----------
def 找得到ffmpeg():
    import live_capture
    try:
        live_capture.找ffmpeg()
        return True
    except live_capture.直播錯誤:
        return False


def 找得到streamlink():
    return importlib.util.find_spec("streamlink_cli") is not None


def 檢查ffmpeg(找=None):
    if (找 or 找得到ffmpeg)():
        return 檢查結果(好, "ffmpeg：可以處理直播聲音")
    return 檢查結果(錯, "找不到 ffmpeg：安裝後重新開啟程式")


def 檢查streamlink(找=None):
    if (找 or 找得到streamlink)():
        return 檢查結果(好, "streamlink：可以連上直播")
    return 檢查結果(錯, "找不到 streamlink：安裝後重新開啟程式")


# ---------- 轉錄模型：在哪、下載過沒有、多大 ----------
def 倉庫(名稱):
    """模型名稱 → Hugging Face 的倉庫名（faster-whisper 的對照表）；本來就是「組織/名稱」就照用。"""
    if "/" in 名稱:
        return 名稱
    try:
        from faster_whisper.utils import _MODELS
        return _MODELS.get(名稱, 名稱)
    except ImportError:
        return 名稱


def 快取根():
    try:
        from huggingface_hub import constants
        return constants.HF_HUB_CACHE
    except ImportError:
        return os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")


def 快取資料夾(名稱):
    return os.path.join(快取根(), "models--" + 倉庫(名稱).replace("/", "--"))


def 已下載(名稱):
    """只看這台電腦的快取，不連網。本機資料夾路徑（自己放的模型）也算已下載。"""
    if os.path.isdir(名稱):
        return True
    快照們 = glob.glob(os.path.join(快取資料夾(名稱), "snapshots", "*"))
    return any(all(os.path.isfile(os.path.join(快照, 檔)) for 檔 in 必要檔們) for 快照 in 快照們)


def 大小(名稱):
    return 模型大小.get(名稱)


def 大小字(位元組):
    if 位元組 is None:
        return "大小不明"
    if 位元組 >= 1e9:
        return f"{位元組 / 1e9:.1f} GB"
    return f"{位元組 / 1e6:.0f} MB"


def 進度字(已, 總):
    """已下載 0.8／1.6 GB（單位跟著總大小）。"""
    if 總 is None:
        return f"已下載 {大小字(已)}"
    if 總 >= 1e9:
        return f"已下載 {已 / 1e9:.1f}／{總 / 1e9:.1f} GB"
    return f"已下載 {已 / 1e6:.0f}／{總 / 1e6:.0f} MB"


def 已等字(秒):
    秒 = max(0, int(秒))
    return f"已等 {秒 // 60}:{秒 % 60:02d}"


def 要用的模型(顯示卡可用, 顯示卡模型=None):
    """可用 = True／None（不確定時照舊先試顯示卡）→ 顯示卡用的模型；False → CPU 用的 small。
    顯示卡模型：不給就用引擎目前的設定（開始時已照 config.json 的 whisper_model 設好）。"""
    import transcribe
    return transcribe.CPU_MODEL if 顯示卡可用 is False else (顯示卡模型 or transcribe.GPU_MODEL)


_顯示卡快取 = {}


def 顯示卡可用():
    """開始時判斷要不要先試顯示卡（結果記住，這次開程式內不再重問）：有 → True；沒有 → False；問不出來 → None（照舊先試）。"""
    if "值" not in _顯示卡快取:
        try:
            _顯示卡快取["值"] = 顯示卡數() > 0
        except Exception:                     # noqa: BLE001
            _顯示卡快取["值"] = None
    return _顯示卡快取["值"]


# ---------- 下載 ----------
def 白話錯誤(e, 總=None):
    """把下載時的例外換成一句白話（不含技術名詞）。"""
    名們 = " ".join(c.__name__ for c in type(e).__mro__)
    字 = str(e).lower()
    if (isinstance(e, OSError) and (getattr(e, "errno", None) == 28 or getattr(e, "winerror", None) in (39, 112))) \
            or "no space left" in 字 or "not enough space" in 字 or "disk full" in 字:
        需要 = f"這個模型約需 {大小字(總)}，" if 總 else ""
        return f"轉錄模型下載失敗：硬碟空間不夠。{需要}請清出空間後再按一次「開始」。"
    if any(k in 名們 for k in ("Connection", "Connect", "Timeout", "Network", "LocalEntryNotFound", "Offline", "gaierror")) \
            or any(k in 字 for k in ("connection", "timed out", "name resolution", "getaddrinfo", "network")):
        return "轉錄模型下載失敗：連不上網路。請確認網路連線後，再按一次「開始」重新下載。"
    return "轉錄模型下載失敗，請稍後再按一次「開始」重試。"


def 這次寫入的大小(資料夾, 開始時刻):
    """快取資料夾裡、開始下載之後才寫入的檔案大小合計（下載中的 .incomplete 也算）；之前就有的檔案不算。"""
    合計 = 0
    for 路徑 in glob.glob(os.path.join(資料夾, "blobs", "*")):
        try:
            st = os.stat(路徑)
        except OSError:
            continue
        if st.st_mtime >= 開始時刻 - 1:
            合計 += st.st_size
    return 合計


def _下載(名稱):
    from faster_whisper.utils import download_model
    download_model(名稱)


def 預告(名稱):
    """開始擷取前：這次要用的模型還沒下載，先告訴介面（啟動面板等下載完才收起）。"""
    if not 已下載(名稱):
        events.送出("model", 狀態="將下載", 模型=名稱, 總=大小(名稱), 已=0)


def 準備模型(名稱, 下載=None, 間隔=0.5, 時鐘=time.time):
    """模型已下載就什麼都不做；還沒有就下載，下載中送出進度事件。失敗丟出 模型下載錯誤（白話）。"""
    if 已下載(名稱):
        return False
    總 = 大小(名稱)
    資料夾 = 快取資料夾(名稱)
    開始 = 時鐘()
    events.送出("model", 狀態="下載中", 模型=名稱, 總=總, 已=0,
                印出=f"第一次使用，正在下載轉錄模型（{大小字(總)}，只需一次）…")
    停 = threading.Event()

    def 回報():
        while not 停.wait(間隔):
            已 = 這次寫入的大小(資料夾, 開始)
            events.送出("model", 狀態="下載中", 模型=名稱, 總=總, 已=min(已, 總) if 總 else 已)
    監看 = threading.Thread(target=回報, daemon=True, name="模型下載進度")
    監看.start()
    try:
        (下載 or _下載)(名稱)
    except Exception as e:                   # 任何下載錯誤都換成白話
        訊息 = 白話錯誤(e, 總)
        events.送出("model", 狀態="失敗", 模型=名稱, 總=總, 訊息=訊息)
        raise 模型下載錯誤(訊息) from e
    finally:
        停.set()
        監看.join(2)
    events.送出("model", 狀態="完成", 模型=名稱, 總=總, 已=總, 印出="轉錄模型下載完成。")
    return True


class 下載進度:
    """啟動面板的下載畫面要顯示什麼（從 model 事件累積）。"""

    def __init__(self, 時鐘=time.time):
        self.時鐘 = 時鐘
        self.重設()

    def 重設(self):
        self.狀態, self.模型, self.總, self.已, self.訊息, self.開始 = "", "", None, 0, "", None

    def 收(self, 內容):
        狀態 = 內容.get("狀態", "")
        換模型 = 內容.get("模型", self.模型) != self.模型
        if 狀態 in ("將下載", "下載中") and (換模型 or self.狀態 not in ("將下載", "下載中")):
            self.開始 = self.時鐘()              # 「已等」從預告（或換成另一個模型）那一刻算起
        self.狀態 = 狀態
        self.模型 = 內容.get("模型", self.模型)
        if "總" in 內容:
            self.總 = 內容["總"]
        if 內容.get("已") is not None:
            self.已 = 內容["已"]
        self.訊息 = 內容.get("訊息", "")

    @property
    def 顯示中(self):
        return self.狀態 in ("將下載", "下載中", "失敗")

    def 標題(self):
        if self.狀態 == "失敗":
            return self.訊息 or "轉錄模型下載失敗，請稍後再按一次「開始」重試。"
        return f"第一次使用：正在下載轉錄模型（{大小字(self.總)}，只需一次）"

    def 百分比(self):
        """0～100；總大小不明時是 None（介面用會動的進度條）。"""
        if not self.總:
            return None
        return max(0, min(100, int(self.已 * 100 / self.總)))

    def 細節(self):
        已等 = 已等字(self.時鐘() - self.開始) if self.開始 else 已等字(0)
        if self.總:
            return f"{進度字(self.已, self.總)}　{已等}"
        return 已等
