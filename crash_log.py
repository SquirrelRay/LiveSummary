# 當機紀錄：主執行緒、其他執行緒、Qt 裡沒被接住的錯誤，都寫進 %LOCALAPPDATA%\LiveSummary\logs\當機紀錄.txt
# （時間、版本號、完整錯誤內容），同時跳出中文提示（有「打開紀錄資料夾」按鈕）。
# 打包後的主程式是無視窗模式，沒有主控台可以看錯誤，所以一定要寫檔。
#
# - 寫進紀錄前一律先 遮金鑰()：API 金鑰（認證管理員、環境變數讀到的、以及任何看起來像金鑰的字串）絕不會出現在紀錄或提示裡。
#   api_key 每讀到一把金鑰就 記住金鑰() 一次，所以即使格式特殊（不像 sk-…）也會整串遮掉。
# - 這裡不放任何使用者能觸發的假出錯入口（按鈕、指令、隱藏參數都不行）；測試用的觸發方式只在 tests 裡。
# - 整個流程不丟例外（紀錄本身壞了也不能讓程式更糟）。
import contextlib
import faulthandler
import os
import re
import sys
import threading
import time
import traceback

import app_paths
import system_info
import version

遮蔽字 = "*****"
提示冷卻秒 = 30          # 跳過一次提示後這段時間內不再跳（紀錄照寫）：定時器裡的錯誤每秒一次，不能每秒一個視窗
紀錄上限位元組 = 2 * 1024 * 1024      # 超過就把舊的改名成 當機紀錄.舊.txt 重新開始

_金鑰們 = set()
_鎖 = threading.Lock()

# 看起來像金鑰的字串（保險；真正讀到的金鑰另外用 記住金鑰() 整串比對）
_樣式們 = (
    re.compile(r"(?i)(authorization|x-api-key|api[_-]?key|access[_-]?token|token|secret|password|passwd)"
               r"([\"']?\s*[:=]\s*[\"']?)(bearer\s+)?([^\s\"',;)}\]]{4,})"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"),                      # Claude（sk-ant-…）、OpenAI、DeepSeek、OpenRouter（sk-or-…）
    re.compile(r"\bAIza[0-9A-Za-z_\-]{10,}"),                    # Google
    # 32 字元以上、同時有英文字母和數字的連續字串（其他家的金鑰、token）
    re.compile(r"(?<![A-Za-z0-9_\-])(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{32,}(?![A-Za-z0-9_\-])"),
)


def 記住金鑰(金鑰):
    """api_key 讀到金鑰時呼叫：之後紀錄裡出現這串字一律遮掉（金鑰只存在記憶體，不寫檔）。"""
    金鑰 = (金鑰 or "").strip()
    if len(金鑰) >= 6:
        _金鑰們.add(金鑰)


def 遮金鑰(文字):
    """把文字裡的 API 金鑰換成 *****。"""
    文字 = str(文字)
    for 金鑰 in sorted(_金鑰們, key=len, reverse=True):
        文字 = 文字.replace(金鑰, 遮蔽字)

    def _關鍵字後(m):
        return f"{m.group(1)}{m.group(2)}{m.group(3) or ''}{遮蔽字}"

    文字 = _樣式們[0].sub(_關鍵字後, 文字)
    for 樣式 in _樣式們[1:]:
        文字 = 樣式.sub(遮蔽字, 文字)
    return 文字


def _環境():
    return (f"Python {system_info.Python版本()} | {system_info.平台字()} | "
            f"{'打包版' if app_paths.已打包() else '開發環境'}")


def _內容(三元, 執行緒名):
    標頭 = (f"==== {time.strftime('%Y-%m-%d %H:%M:%S')} | 版本 {version.版本} | "
          f"{'主執行緒' if 執行緒名 == threading.main_thread().name else '執行緒 ' + 執行緒名} ====")
    if isinstance(三元, str):
        完整 = 三元
    else:
        完整 = "".join(traceback.format_exception(*三元))
    return f"{標頭}\n{_環境()}\n{遮金鑰(完整)}\n"


def 寫紀錄(三元, 執行緒名=None):
    """寫一筆到當機紀錄.txt；三元 = (型別, 例外, traceback)，或直接給一段文字。回傳紀錄檔路徑，寫不進去回傳 None。"""
    try:
        路徑 = app_paths.當機紀錄檔()
        內容 = _內容(三元, 執行緒名 or threading.current_thread().name)
        with _鎖:
            os.makedirs(os.path.dirname(路徑), exist_ok=True)
            try:
                if os.path.getsize(路徑) > 紀錄上限位元組:
                    os.replace(路徑, 路徑.replace("當機紀錄.txt", "當機紀錄.舊.txt"))
            except OSError:
                pass
            with open(路徑, "a", encoding="utf-8") as f:
                f.write(內容 + "\n")
        return 路徑
    except Exception:          # noqa: BLE001  紀錄壞了不能讓程式更糟
        return None


def _摘要(三元):
    try:
        if isinstance(三元, str):
            return ""
        字 = "".join(traceback.format_exception_only(三元[0], 三元[1])).strip()
        字 = 遮金鑰(字)
        return 字 if len(字) <= 200 else 字[:200] + "…"
    except Exception:          # noqa: BLE001
        return ""


def 提示文字(路徑, 摘要=""):
    行 = ["直播摘要發生了未預期的錯誤。", ""]
    if 摘要:
        行 += [摘要, ""]
    if 路徑:
        行 += ["錯誤內容已記錄在：", 路徑, "", "要回報問題的話，請附上這個檔案（裡面不會有 API 金鑰）。"]
    else:
        行 += ["（錯誤紀錄寫不進去，請確認磁碟還有空間。）"]
    return "\n".join(行)


# ---- 跳出提示 ----
_提示中 = False
_上次提示 = 0.0
_橋 = None          # Qt 的訊號橋（接上Qt() 在主執行緒建立；其他執行緒的錯誤透過它排進主執行緒顯示）


def _打開資料夾(路徑):
    with contextlib.suppress(Exception):      # 紀錄、提示壞了不能讓程式更糟
        os.startfile(os.path.dirname(路徑) if 路徑 else app_paths.日誌資料夾())      # noqa: S606  程式自己的 logs 資料夾


def _訊息框Win32(文字):
    """還沒有 QApplication（啟動早期）或 Qt 自己出事時用 Windows 內建的訊息框。"""
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, 文字, "直播摘要", 0x10 | 0x40000)       # 錯誤圖示、最上層


def _訊息框Qt(文字, 路徑):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox
    框 = QMessageBox(QMessageBox.Critical, "直播摘要", 文字)
    框.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    開 = 框.addButton("打開紀錄資料夾", QMessageBox.ActionRole)
    框.addButton("關閉", QMessageBox.RejectRole)
    框.exec()
    if 框.clickedButton() is 開:
        _打開資料夾(路徑)


def _在主執行緒顯示(路徑, 摘要):
    """主執行緒上真的把提示顯示出來（有 QApplication 用 Qt 訊息框，沒有或出事就用 Windows 內建的）。顯示期間算「提示中」。"""
    global _提示中, _上次提示
    文字 = 提示文字(路徑, 摘要)
    _提示中 = True
    try:
        with contextlib.suppress(Exception):      # 紀錄、提示壞了不能讓程式更糟
            from PySide6.QtWidgets import QApplication
            if QApplication.instance() is not None:
                return _訊息框Qt(文字, 路徑)
        _訊息框Win32(文字)
    finally:
        _提示中 = False
        _上次提示 = time.monotonic()


def _預設提示(路徑, 摘要=""):
    with contextlib.suppress(Exception):
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None and QThread.currentThread() != app.thread() and _橋 is not None:
            return _橋.要提示.emit(路徑 or "", 摘要)         # 其他執行緒：排進主執行緒顯示（訊息框一定要在主執行緒）
    _在主執行緒顯示(路徑, 摘要)


提示 = _預設提示          # 測試換成假的（不跳真視窗）


def _跳提示(路徑, 摘要):
    global _提示中, _上次提示
    if _提示中 or (_上次提示 and time.monotonic() - _上次提示 < 提示冷卻秒):
        return
    _提示中 = True
    try:
        提示(路徑, 摘要)
    finally:
        _提示中 = False
        _上次提示 = time.monotonic()


def 接上Qt():
    """QApplication 建好之後在主執行緒呼叫一次：讓其他執行緒的錯誤也能在主執行緒跳出提示。"""
    global _橋
    try:
        from PySide6.QtCore import QObject, Signal, Slot

        class 提示橋(QObject):
            要提示 = Signal(str, str)

            def __init__(self):
                super().__init__()
                self.要提示.connect(self.顯示)         # 接到自己的方法（物件在主執行緒）：別的執行緒 emit 時會排進主執行緒執行

            @Slot(str, str)
            def 顯示(self, 路徑, 摘要):
                _在主執行緒顯示(路徑 or None, 摘要)

        _橋 = 提示橋()
    except Exception:          # noqa: BLE001
        _橋 = None


def _處理(三元, 執行緒名=None, 要提示=True):
    路徑 = 寫紀錄(三元, 執行緒名)
    if 要提示:
        _跳提示(路徑, _摘要(三元))
    return 路徑


# ---- 掛上去 ----
_原 = {}
_原生檔 = None


def _主執行緒錯誤(型別, 例外, tb):
    if issubclass(型別, KeyboardInterrupt):
        return sys.__excepthook__(型別, 例外, tb)
    _處理((型別, 例外, tb), threading.main_thread().name)


def _其他執行緒錯誤(args):
    if issubclass(args.exc_type, SystemExit):
        return
    名 = args.thread.name if args.thread else "未知"
    _處理((args.exc_type, args.exc_value, args.exc_traceback), 名)


def _Qt訊息(類型, 脈絡, 訊息):
    with contextlib.suppress(Exception):      # 紀錄、提示壞了不能讓程式更糟
        from PySide6.QtCore import QtMsgType
        if sys.stderr:
            print(訊息, file=sys.stderr)
        if 類型 == QtMsgType.QtFatalMsg:          # Qt 要中止程式：趁還來得及寫下來
            路徑 = 寫紀錄(f"Qt 嚴重錯誤（程式即將結束）：{訊息}")
            _訊息框Win32(提示文字(路徑, 遮金鑰(訊息)[:200]))


def 安裝(qt=True, 原生=True):
    """app.py 一開始呼叫：掛上主執行緒、其他執行緒的錯誤攔截；qt=True 另外攔 Qt 的嚴重錯誤；原生=True 讓原生層當機（DLL 掛掉）也寫 Python 堆疊。"""
    global _原生檔
    if "excepthook" not in _原:          # 可重複呼叫（app.py 最前面先裝一次，main() 再補 Qt 的）
        _原["excepthook"] = sys.excepthook
        _原["threading"] = threading.excepthook
        sys.excepthook = _主執行緒錯誤
        threading.excepthook = _其他執行緒錯誤
    if qt and "qt" not in _原:
        with contextlib.suppress(Exception):      # 紀錄、提示壞了不能讓程式更糟
            from PySide6.QtCore import qInstallMessageHandler
            _原["qt"] = qInstallMessageHandler(_Qt訊息)
    if 原生 and _原生檔 is None:
        try:
            路徑 = app_paths.當機紀錄檔()
            os.makedirs(os.path.dirname(路徑), exist_ok=True)
            _原生檔 = open(路徑, "a", encoding="utf-8")      # noqa: SIM115  要開到程式結束
            faulthandler.enable(_原生檔)
        except Exception:          # noqa: BLE001
            _原生檔 = None


def 解除():
    """把攔截還原（測試用）。"""
    global _原生檔
    if "excepthook" in _原:
        sys.excepthook = _原.pop("excepthook")
    if "threading" in _原:
        threading.excepthook = _原.pop("threading")
    if "qt" in _原:
        try:
            from PySide6.QtCore import qInstallMessageHandler
            qInstallMessageHandler(_原.pop("qt"))
        except Exception:          # noqa: BLE001
            _原.pop("qt", None)
    if _原生檔 is not None:
        with contextlib.suppress(Exception):      # 紀錄、提示壞了不能讓程式更糟
            faulthandler.disable()
            _原生檔.close()
        _原生檔 = None
