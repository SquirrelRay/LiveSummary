# PyInstaller 執行期 hook（LiveSummary.spec 的 runtime_hooks；打包版在程式開始前執行，開發環境不會用到）。
# 打包版不帶 av（PyAV）：它附的 FFmpeg 含 GPL 的 x264／x265 編碼器，本程式只做聲音轉文字用不到（決定與理由見 docs\打包調查.md）。
# 但 faster-whisper 在模組最上層 `import av`（只有 decode_audio() 讀音訊檔時才真的用到），沒有 av 連 import faster_whisper 都會失敗，
# 所以這裡放一個替身 av 模組。本程式只傳 numpy 陣列給 faster-whisper（tests\test_打包不帶av.py 檢查），替身不會被用到；
# 萬一被用到（例如以後改成傳檔案路徑），任何屬性存取都丟出 沒有av錯誤（清楚的中文說明），不會默默失敗。
# 真的找得到 av（例如之後又改回帶 av）就不放替身。
import importlib.util
import sys
import types

訊息 = ("打包版沒有附 av（PyAV），不能讓 faster-whisper 直接讀音訊檔，只能傳 numpy 陣列。"
      "這是程式的錯誤（某處把檔案路徑傳給了 faster-whisper），請把 logs\\當機紀錄.txt 附上回報。")


class 沒有av錯誤(RuntimeError):
    pass


def 做替身():
    替身 = types.ModuleType("av", "打包版的 av 替身（見 pyi_rth_av替身.py）")

    def __getattr__(名):
        if 名.startswith("__") and 名.endswith("__"):       # 匯入機制、inspect 等查的 __path__、__file__ 之類：照一般模組回 AttributeError
            raise AttributeError(名)
        raise 沒有av錯誤(f"{訊息}（用到了 av.{名}）")

    替身.__getattr__ = __getattr__
    替身.替身 = True
    return 替身


def 安裝():
    """sys.modules 還沒有 av、也找不到真的 av 時，放入替身。回傳有沒有放。"""
    if "av" in sys.modules or importlib.util.find_spec("av") is not None:
        return False
    sys.modules["av"] = 做替身()
    return True


安裝()
