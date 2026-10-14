"""當機紀錄（打包第 5 步之一）：主執行緒、其他執行緒、Qt 槽函式裡沒被接住的錯誤，都寫進 logs\\當機紀錄.txt
（時間、版本號、完整錯誤）並跳提示；API 金鑰一定被遮掉。
觸發錯誤的方式只在這個測試檔裡（程式本體沒有「測試當機」的按鈕或指令）。提示一律換成假的，不跳真視窗。"""
import os
import re
import sys
import threading
import time
from pathlib import Path

import pytest

import api_key
import app_paths
import crash_log
import version

專案 = Path(__file__).resolve().parent.parent

假金鑰們 = [
    "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_AbCdEf",     # Claude
    "sk-proj-1234567890abcdefghijklmnop",                           # OpenAI
    "sk-or-v1-0123456789abcdef0123456789abcdef",                    # OpenRouter
    "AIzaSyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q",                      # Google
]


@pytest.fixture
def 紀錄(monkeypatch):
    """裝上攔截（不裝 Qt 訊息處理與原生層，不影響其他測試）；提示換成假的並記下參數。"""
    for 檔 in (app_paths.當機紀錄檔(), app_paths.當機紀錄檔().replace("當機紀錄.txt", "當機紀錄.舊.txt")):
        if os.path.exists(檔):
            os.remove(檔)
    提示們 = []
    monkeypatch.setattr(crash_log, "提示", lambda 路徑, 摘要="": 提示們.append((路徑, 摘要)))
    monkeypatch.setattr(crash_log, "_提示中", False)
    monkeypatch.setattr(crash_log, "_上次提示", 0.0)
    monkeypatch.setattr(crash_log, "_金鑰們", set())
    crash_log.安裝(qt=False, 原生=False)
    yield 提示們
    crash_log.解除()


def 讀():
    with open(app_paths.當機紀錄檔(), encoding="utf-8") as f:
        return f.read()


def 例外資訊(函式):
    """執行函式、回傳它丟出的例外的 sys.exc_info()（給 sys.excepthook 用）。"""
    try:
        函式()
    except Exception:       # noqa: BLE001  要接住任何型別的例外
        return sys.exc_info()
    raise AssertionError("函式沒有丟出例外")


def 出錯(訊息, 型別=RuntimeError):
    def 丟():
        raise 型別(訊息)
    return 例外資訊(丟)


# ---------- 寫檔、版本號 ----------
def test_當機紀錄放在logs資料夾(紀錄):
    assert app_paths.當機紀錄檔() == os.path.join(app_paths.日誌資料夾(), "當機紀錄.txt")
    assert app_paths.當機紀錄檔().startswith(app_paths.資料資料夾())


def test_主執行緒沒被接住的錯誤寫進紀錄且有版本號和完整錯誤(紀錄):
    sys.excepthook(*出錯("找不到這個設定", ValueError))
    內容 = 讀()
    assert version.版本 == "1.0.0" and f"版本 {version.版本}" in 內容
    assert re.search(r"==== \d{4}-\d\d-\d\d \d\d:\d\d:\d\d \| 版本 1\.0\.0 \| 主執行緒 ====", 內容)
    assert "Traceback (most recent call last)" in 內容
    assert "ValueError: 找不到這個設定" in 內容
    assert "test_當機紀錄.py" in 內容                 # 完整堆疊，不只最後一行
    assert "Python 3.13" in 內容 and "開發環境" in 內容


def test_跳出提示且提示裡有紀錄檔位置(紀錄):
    sys.excepthook(*出錯("壞了"))
    assert len(紀錄) == 1
    路徑, 摘要 = 紀錄[0]
    assert 路徑 == app_paths.當機紀錄檔()
    assert "RuntimeError: 壞了" in 摘要
    文字 = crash_log.提示文字(路徑, 摘要)
    assert "未預期的錯誤" in 文字 and 路徑 in 文字


def test_其他執行緒沒被接住的錯誤也寫進紀錄(紀錄):
    def 工作():
        raise KeyError("背景執行緒出事")
    t = threading.Thread(target=工作, name="轉錄執行緒")
    t.start()
    t.join()
    內容 = 讀()
    assert "執行緒 轉錄執行緒" in 內容 and "KeyError" in 內容 and "背景執行緒出事" in 內容
    assert len(紀錄) == 1


def test_Qt槽函式裡沒被接住的錯誤寫進紀錄(紀錄):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    class 物件(QObject):
        訊號 = Signal()

        def 槽(self):
            raise ZeroDivisionError("槽函式出事")

    o = 物件()
    o.訊號.connect(o.槽)
    o.訊號.emit()
    app.processEvents()
    assert "ZeroDivisionError: 槽函式出事" in 讀()
    assert len(紀錄) == 1


def test_KeyboardInterrupt和SystemExit不算當機(紀錄, monkeypatch):
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: None)       # 不要在測試輸出印 Traceback
    sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)

    def 結束():
        raise SystemExit(0)
    t = threading.Thread(target=結束)
    t.start()
    t.join()
    assert not os.path.exists(app_paths.當機紀錄檔())
    assert 紀錄 == []


def test_連續出錯每筆都寫但提示不洗版(紀錄):
    sys.excepthook(*出錯("第一個"))
    sys.excepthook(*出錯("第二個"))
    內容 = 讀()
    assert "第一個" in 內容 and "第二個" in 內容
    assert len(紀錄) == 1                              # 冷卻中不再跳第二個視窗


def test_提示冷卻過了可以再跳(紀錄, monkeypatch):
    sys.excepthook(*出錯("a"))
    monkeypatch.setattr(crash_log, "_上次提示", time.monotonic() - crash_log.提示冷卻秒 - 1)
    sys.excepthook(*出錯("b"))
    assert len(紀錄) == 2


def test_紀錄壞了不會讓程式更糟(紀錄, monkeypatch):
    monkeypatch.setattr(app_paths, "當機紀錄檔", lambda: os.path.join(app_paths.資料資料夾(), "不存在\0壞路徑", "x.txt"))
    sys.excepthook(*出錯("寫不進去"))            # 不丟例外
    assert 紀錄 and 紀錄[0][0] is None
    assert "寫不進去" in crash_log.提示文字(None)


def test_紀錄太大時舊的改名重新開始(紀錄, monkeypatch):
    monkeypatch.setattr(crash_log, "紀錄上限位元組", 50)
    sys.excepthook(*出錯("舊的"))
    sys.excepthook(*出錯("新的"))
    assert "新的" in 讀() and "舊的" not in 讀()
    assert os.path.exists(app_paths.當機紀錄檔().replace("當機紀錄.txt", "當機紀錄.舊.txt"))


# ---------- 金鑰一定被遮掉 ----------
@pytest.mark.parametrize("金鑰", 假金鑰們)
def test_像金鑰的字串寫進紀錄前被遮掉(紀錄, 金鑰):
    sys.excepthook(*出錯(f"呼叫失敗，金鑰 {金鑰} 無效"))
    內容 = 讀()
    assert 金鑰 not in 內容
    assert 金鑰[:12] not in 內容                       # 連前半段都不留
    assert "*****" in 內容 and "呼叫失敗" in 內容


@pytest.mark.parametrize("文字, 秘密", [
    ("Authorization: Bearer abc123DEF456ghi789", "abc123DEF456ghi789"),
    ("headers={'x-api-key': 'k_live_9f8e7d6c5b4a'}", "k_live_9f8e7d6c5b4a"),
    ('api_key="mySecretValue99"', "mySecretValue99"),
    ("ANTHROPIC_API_KEY=whatever-format-1234", "whatever-format-1234"),
    ("token: zxcvbnm98765", "zxcvbnm98765"),
    ("password=hunter2hunter2", "hunter2hunter2"),
    ("碰到 0123456789abcdef0123456789abcdef0123 這串", "0123456789abcdef0123456789abcdef0123"),     # 32 字元以上、有英數字的長字串
])
def test_各種格式的金鑰被遮掉(紀錄, 文字, 秘密):
    sys.excepthook(*出錯(文字))
    內容 = 讀()
    assert 秘密 not in 內容
    assert "*****" in 內容


def test_程式讀到的金鑰就算格式特殊也整串遮掉(紀錄, 假金鑰庫):
    特殊 = "Zq-的-weird_key.format/9"                  # 不像任何已知格式
    api_key.儲存("claude", 特殊)
    assert api_key.取得("claude") == 特殊
    sys.excepthook(*出錯(f"出錯了 {特殊} 結尾"))
    內容 = 讀()
    assert 特殊 not in 內容 and "出錯了 ***** 結尾" in 內容


def test_環境變數讀到的金鑰也遮掉(紀錄, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "abc.def_ghi-123")
    assert api_key.取得("claude") == "abc.def_ghi-123"
    sys.excepthook(*出錯("連線 abc.def_ghi-123 失敗"))
    assert "abc.def_ghi-123" not in 讀()


def test_提示和摘要裡也不會有金鑰(紀錄):
    金鑰 = 假金鑰們[0]
    sys.excepthook(*出錯(f"bad {金鑰}"))
    路徑, 摘要 = 紀錄[0]
    assert 金鑰 not in 摘要 and 金鑰 not in crash_log.提示文字(路徑, 摘要)


def test_串起來的例外和堆疊裡的金鑰也遮掉(紀錄):
    金鑰 = 假金鑰們[1]

    def 外層():
        try:
            raise ValueError(f"key={金鑰}")
        except ValueError as e:
            raise RuntimeError("包起來") from e

    sys.excepthook(*例外資訊(外層))
    內容 = 讀()
    assert 金鑰 not in 內容 and "The above exception was the direct cause" in 內容


def test_正常文字不會被誤遮(紀錄):
    路徑 = r"C:\Users\Ricky\AppData\Local\LiveSummary\logs\當機紀錄.txt"
    sys.excepthook(*出錯(f"讀不到 {路徑}，頻道 ren_kisaragi__ 直播中，使用 faster_whisper large-v3-turbo"))
    內容 = 讀()
    assert 路徑 in 內容 and "ren_kisaragi__" in 內容 and "large-v3-turbo" in 內容


def test_遮金鑰函式(紀錄):
    assert crash_log.遮金鑰("沒有金鑰的一般文字 12345") == "沒有金鑰的一般文字 12345"
    crash_log.記住金鑰("my-own-key-123")
    assert crash_log.遮金鑰("a my-own-key-123 b") == "a ***** b"
    crash_log.記住金鑰("")                                # 空字串、太短的不記（不然會把一般文字遮光）
    crash_log.記住金鑰("ab")
    assert crash_log.遮金鑰("ab cd") == "ab cd"


# ---------- 程式本體沒有「測試當機」----------
def test_程式本體沒有使用者能觸發的測試當機():
    樣式 = re.compile(r"測試當機|觸發當機|故意當機|crash[_ ]?test|trigger[_ ]?crash|simulate[_ ]?crash", re.IGNORECASE)
    for 檔 in 專案.glob("*.py"):
        for 行號, 行 in enumerate(檔.read_text(encoding="utf-8").splitlines(), 1):
            assert not 樣式.search(行), f"{檔.name}:{行號} 不該有使用者能觸發的測試當機：{行.strip()}"


def test_app有裝當機紀錄():
    原始碼 = (專案 / "app.py").read_text(encoding="utf-8")
    assert "crash_log.安裝(" in 原始碼 and "crash_log.接上Qt()" in 原始碼
