"""介面小修（offscreen，不開真的視窗、不呼叫真模型）：
1. 啟動面板的每小時總費用：設定框儲存、膠囊選單切換聊天室翻譯、面板開關後立刻重算。
2. 一般使用者看得到的文字不出現 config.json、欄位名等內部名詞。
3. 膠囊滑鼠提示的直播時間：提示開著時每秒更新，關掉就停。
4. 膠囊與面板重疊時不互搶最上層（用假的視窗前後順序重現）：膠囊永遠在面板之上、沒被蓋就不動、全螢幕與截圖工具的規則不變。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import test_介面冒煙 as 冒煙
from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QMenu,
    QPushButton,
)
from test_介面冒煙 import 假引擎, 停止並等完, 從啟動面板開始

import capsule
import chat_translate
import config
import cost_estimate
import llm
import overlay
import panel
import stream_clock
import subtitle

qapp, 環境 = 冒煙.qapp, 冒煙.環境          # fixture：和冒煙測試共用

內部字們 = ("config", ".json", "api_key", "base_url", "anthropic", "openai_compatible", "web_verify", "chat_translate")


def _總額(啟):
    字 = 啟.總費用.text()
    assert 字.startswith("每小時約 US$") and 字.endswith("（估算）"), 字
    return float(字[len("每小時約 US$"):-len("（估算）")])


def _應有總額(啟):
    return cost_estimate.估算(啟._費用設定(), 啟.段位(), 啟.台.面板.翻譯將啟用(), 啟.台.面板.聊天將開啟())["合計"]


def _選單動作(台, 開頭):
    m = QMenu()
    台.膠囊.填選單(m)
    return next(a for a in m.actions() if a.text().startswith(開頭)), m


# ---------- 1. 啟動面板總費用即時重算 ----------
def test_設定框儲存後_啟動面板總費用立刻重算(環境):
    台 = 環境["台"]
    啟 = 台.啟動面板
    assert 啟.isVisible()
    前 = _總額(啟)
    台.開設定框()
    頁 = 台.設定框.頁
    頁.欄["web_verify"].setChecked(True)                  # 上網查證：每小時多一筆費用
    assert _總額(啟) == 前                                 # 還沒按儲存：不變
    頁.儲存()
    assert _總額(啟) > 前 and _總額(啟) == _應有總額(啟)
    頁.欄["web_verify"].setChecked(False)
    頁.欄["summary_thinking"].setChecked(False)            # 關延伸思考：變便宜
    頁.儲存()
    assert _總額(啟) < 前 and _總額(啟) == _應有總額(啟)


def test_膠囊選單切換聊天室翻譯_啟動面板總費用立刻重算(環境):
    台 = 環境["台"]
    啟 = 台.啟動面板
    啟.語言選.setCurrentIndex(啟.語言選.findData("ja"))   # 外語直播才翻聊天室
    台.面板.存檔["目前"] = [{"種類": "聊天室"}]             # 開始後會開聊天室面板
    啟._更新段位註()
    前 = _總額(啟)
    a, _m = _選單動作(台, "聊天室翻譯")
    a.trigger()                                           # 關 → 開
    assert 台.聊天翻譯器.開啟 and _總額(啟) > 前 and _總額(啟) == _應有總額(啟)
    a, _m = _選單動作(台, "聊天室翻譯")
    a.trigger()                                           # 開 → 關
    assert not 台.聊天翻譯器.開啟 and _總額(啟) == 前


def test_面板開關後_啟動面板總費用立刻重算(環境):
    台 = 環境["台"]
    啟 = 台.啟動面板
    啟.語言選.setCurrentIndex(啟.語言選.findData("ja"))
    台.面板.存檔["目前"] = [{"種類": "分鐘摘要"}]           # 預測的版面沒有逐句翻譯：字幕翻譯不計
    啟._更新段位註()
    前 = _總額(啟)
    台.面板.開關("逐句翻譯", True)                          # 膠囊選單「面板 → 逐句翻譯 面板」
    assert _總額(啟) > 前 and _總額(啟) == _應有總額(啟)
    台.面板.開關("逐句翻譯", False)
    assert _總額(啟) == _應有總額(啟)


def test_啟動面板收著時儲存設定_不出錯_打開時是新的金額(環境):
    台 = 環境["台"]
    啟 = 台.啟動面板
    啟.hide()
    台.開設定框()
    台.設定框.頁.欄["web_verify"].setChecked(True)
    台.設定框.頁.儲存()
    啟.顯示()
    assert _總額(啟) == _應有總額(啟)


# ---------- 2. 介面文字不出現內部名詞 ----------
def _介面文字們(w):
    字們 = [w.toolTip(), w.windowTitle()]
    for c in w.findChildren(QLabel) + w.findChildren(QPushButton) + w.findChildren(QCheckBox):
        字們 += [c.text(), c.toolTip()]
    for c in w.findChildren(QComboBox):
        字們 += [c.itemText(i) for i in range(c.count())] + [c.toolTip()]
    return [字 for 字 in 字們 if 字]


def _沒有內部字(字們):
    壞 = [字 for 字 in 字們 for k in 內部字們 if k in 字]
    assert 壞 == [], 壞


def test_設定框_啟動面板_狀態列_膠囊提示_系統匣_沒有內部名詞(環境, monkeypatch):
    台 = 環境["台"]
    台.開設定框()
    頁 = 台.設定框.頁
    _沒有內部字(_介面文字們(台.設定框) + _介面文字們(台.啟動面板))
    頁.儲存()
    assert 頁.狀態字.text() == "已儲存（舊的設定已備份）。"
    頁.還原預設()
    _沒有內部字([頁.狀態字.text()])
    assert [頁.服務選.itemText(i) for i in range(頁.服務選.count())] == [
        "Claude", "OpenRouter（一把金鑰用多家模型）", "DeepSeek", "Google Gemini", "Ollama（本機，不用金鑰）",
        "其他相容服務（自己填網址）"]           # OpenAI 直連暫時不列（呼叫方式未驗證）
    monkeypatch.setattr(config, "目前設定", lambda: dict(config.出廠預設(), api_key_env=""))
    頁.更新金鑰()
    assert 頁.金鑰字.text() == "Claude：這個服務不需要金鑰"

    藥丸們 = (台.時間藥丸, 台.轉錄藥丸, 台.費用藥丸, 台.翻譯藥丸, 台.聊天翻譯藥丸)
    _沒有內部字([w.toolTip() for w in 藥丸們] + [w.text() for w in 藥丸們])
    台.膠囊.更新()
    提示 = 台.膠囊.膠囊.toolTip()
    assert 提示.splitlines()[-1] == "（金額為估算，實際以 API 帳單為準）"
    _沒有內部字([提示, 台.膠囊.系統匣.toolTip()])


def test_設定警告_用設定框的中文名稱_不出現欄位名():
    assert config.介面警告字([]) == ""
    assert config.介面警告字([("不合法", "chat")]) == "設定有問題：「抓聊天室」的值不正確，已改用預設值。請到設定檢查。"
    assert config.介面警告字([("不合法", "web_verify"), ("不合法", "subtitle_mode")]) == (
        "設定有問題：「上網查證詞庫的候選名詞」的值不正確，已改用預設值；「逐句字幕」的值不正確，已改用預設值。請到設定檢查。")
    assert config.介面警告字([("不認得", "xyz"), ("不認得", "abc")]) == "設定有問題：有一項設定的值不正確，已改用預設值。請到設定檢查。"
    assert "話題最短分鐘數" in config.介面警告字([("話題長度", None)])
    assert config.介面警告字([("讀不懂", None)]) == "設定有問題：設定檔讀不懂，全部改用預設值。請到設定檢查。"
    for k in config.設定說明:                                  # 每個欄位都有中文名稱，而且不含內部寫法
        名 = config.中文名稱(k)
        assert 名 and k not in 名 and "--" not in 名 and "true" not in 名 and "（" not in 名, (k, 名)


def test_載入設定_仍回傳三項_命令列與show_config的文字不變(tmp_path, monkeypatch):
    設定檔 = tmp_path / "config.json"
    設定檔.write_text('{"chat": "要", "xyz": 1}', encoding="utf-8")
    monkeypatch.setattr(config, "設定檔路徑", str(設定檔))
    _, _, 警告們 = config.載入設定({})
    assert 警告們 == ["設定檔的 chat 值不合法（'要'），改用預設值 True。", "設定檔裡有不認得的欄位「xyz」，已忽略。"]
    assert config.載入設定詳細({})[3] == [("不合法", "chat"), ("不認得", "xyz")]


def test_結束統計與連線錯誤_沒有內部名詞(monkeypatch):
    for 名, 值 in (("用量", {"次數": 2, "輸入": 1000, "輸出": 100, "缺token": 0}),
                  ("翻譯用量", {"次數": 2, "輸入": 1000, "輸出": 100, "缺token": 0}),
                  ("聊天翻譯用量", {"次數": 2, "輸入": 1000, "輸出": 100, "缺token": 0}),
                  ("查證用量", {"次數": 1, "輸入": 1000, "輸出": 100, "缺token": 0, "搜尋": 2})):
        monkeypatch.setattr(llm, 名, 值)
    字幕 = object.__new__(subtitle.字幕器)
    字幕.單價, 字幕.延遲們 = (1.0, 5.0), []
    聊天 = object.__new__(chat_translate.聊天翻譯器)
    聊天.單價, 聊天.統計 = (1.0, 5.0), {"已翻": 3}
    字們 = [llm.用量文字(1.0, 5.0), llm.查證用量文字(1.0, 5.0), 字幕.統計文字(), 聊天.統計文字(), llm._連線訊息()]
    _沒有內部字(字們)
    assert all("金額為估算，實際以 API 帳單為準" in 字 for 字 in 字們[:4])


# ---------- 3. 膠囊滑鼠提示的直播時間每秒更新 ----------
class 假提示框:
    """代替 QToolTip：記下顯示的文字；可見與否由測試決定。"""
    def __init__(self):
        self.可見, self.文字們 = False, []

    def showText(self, 點, 字, w=None):
        self.可見 = True
        self.文字們.append(字)

    def isVisible(self):
        return self.可見


def test_膠囊提示_直播時間每秒更新_關掉就停(環境, monkeypatch):
    台 = 環境["台"]
    從啟動面板開始(台, monkeypatch, 假引擎())
    時刻 = [1000.0]
    軸 = stream_clock.時軸(開播=1000.0 - 3600 - 125, 時鐘=lambda: 時刻[0], 延遲=0.0)   # 已開播 1:02:05
    monkeypatch.setattr(stream_clock, "_目前", 軸)
    框 = 假提示框()
    monkeypatch.setattr(capsule, "QToolTip", 框)
    管, 膠 = 台.膠囊, 台.膠囊.膠囊
    monkeypatch.setattr(膠, "游標位置", lambda: 膠.frameGeometry().center())   # 滑鼠停在膠囊上

    QApplication.sendEvent(膠, QHelpEvent(QEvent.ToolTip, QPoint(5, 5), 膠.mapToGlobal(QPoint(5, 5))))
    assert 框.可見 and "直播時間 1:02:05" in 框.文字們[-1] and 管.提示計時.isActive()
    assert 管.提示計時.interval() == 1000
    時刻[0] += 1
    管._刷新提示()                                         # 計時器每秒呼叫一次
    assert "直播時間 1:02:06" in 框.文字們[-1]
    時刻[0] += 1
    管._刷新提示()
    assert "直播時間 1:02:07" in 框.文字們[-1]

    框.可見 = False                                        # 提示框關了：計時器停掉，不在背景空跑
    管._刷新提示()
    assert not 管.提示計時.isActive()
    n = len(框.文字們)
    QApplication.sendEvent(膠, QHelpEvent(QEvent.ToolTip, QPoint(5, 5), 膠.mapToGlobal(QPoint(5, 5))))
    assert 管.提示計時.isActive()
    monkeypatch.setattr(膠, "游標位置", lambda: 膠.frameGeometry().topLeft() - QPoint(50, 50))   # 滑鼠離開
    管._刷新提示()
    assert not 管.提示計時.isActive() and len(框.文字們) == n + 1

    停止並等完(台)                                          # 停止後：時間不再跳（用狀態列藥丸的字）
    時刻[0] += 100
    assert 管.時間字() == 台.時間藥丸.text()


def test_膠囊收掉時提示計時器也停(環境, monkeypatch):
    管 = 環境["台"].膠囊
    monkeypatch.setattr(capsule, "QToolTip", 假提示框())
    管.顯示提示(QPoint(0, 0))
    assert 管.提示計時.isActive()
    管.收掉()
    assert not 管.提示計時.isActive()


# ---------- 4. 膠囊與面板的前後順序 ----------
class 假視窗順序:
    """代替 user32：一份由上到下的視窗清單。SetWindowPos 依 Windows 規則插入；記下真的改變順序的次數（= 會閃的次數）。"""
    def __init__(self, 由上到下, 置頂們):
        self.順序 = list(由上到下)
        self.置頂 = set(置頂們)
        self.樣式 = {}
        self.呼叫 = 0
        self.換位 = 0

    @staticmethod
    def _v(h):
        h = getattr(h, "value", h)
        return h - 2 ** 64 if h and h >= 2 ** 63 else h      # HWND(-1) 讀回來是無號數

    def SetWindowPos(self, h, 在後, *_):
        h, 在後 = self._v(h), self._v(在後)
        self.呼叫 += 1
        舊 = list(self.順序)
        if h in self.順序:                               # 新開的視窗還不在清單裡
            self.順序.remove(h)
        if 在後 == -1:                                    # HWND_TOPMOST
            self.置頂.add(h)
            self.順序.insert(0, h)
        elif 在後 == -2:                                  # HWND_NOTOPMOST：放到非置頂的最上面
            self.置頂.discard(h)
            i = next((i for i, x in enumerate(self.順序) if x not in self.置頂), len(self.順序))
            self.順序.insert(i, h)
        else:                                            # 放在 在後 的正下方，置頂與否跟著它
            (self.置頂.add if 在後 in self.置頂 else self.置頂.discard)(h)
            self.順序.insert(self.順序.index(在後) + 1, h)
        if self.順序 != 舊:
            self.換位 += 1
        return 1

    def GetWindow(self, h, 方向):
        h = self._v(h)
        i = self.順序.index(h) if h in self.順序 else 0
        return self.順序[i - 1] if i > 0 else None

    def GetWindowLongPtrW(self, h, _):
        h = self._v(h)
        return self.樣式.get(h, 0) | (panel.WS_EX_TOPMOST if h in self.置頂 else 0)

    def SetWindowLongPtrW(self, h, _, 值):
        self.樣式[self._v(h)] = 值 & ~panel.WS_EX_TOPMOST
        return 0

    def 在上面(self, 甲, 乙):
        return self.順序.index(甲) < self.順序.index(乙)


@pytest.fixture
def 前後(環境, monkeypatch):
    """開始一場（預設版面三個面板），換成假的視窗前後順序。回傳 (台, 膠囊代號, 面板代號們, 造順序)。"""
    台 = 環境["台"]
    從啟動面板開始(台, monkeypatch, 假引擎())
    膠 = int(台.膠囊.膠囊.winId())
    面們 = [int(面.winId()) for 面 in 台.面板.面板們.values()]
    全螢幕 = [False]
    monkeypatch.setattr(overlay, "前景是全螢幕程式", lambda hwnd=None: 全螢幕[0])

    def 造順序(由上到下, 置頂們):
        假 = 假視窗順序(由上到下, 置頂們)
        monkeypatch.setattr(overlay, "user32", 假)
        return 假
    yield 台, 膠, 面們, 造順序, 全螢幕
    停止並等完(台)


def _跑幾輪(台, 輪=6):
    """膠囊與每個面板的 0.5 秒計時器輪流觸發（模擬兩邊的計時器時間點錯開）。"""
    for i in range(輪):
        面們 = list(台.面板.面板們.values())
        if i % 2:
            面們.reverse()
        台.膠囊.膠囊._保持置頂()
        for 面 in 面們:
            面._保持置頂()


def test_全螢幕時_膠囊在最上_面板緊接在下_之後不再換位(前後):
    台, 膠, 面們, 造順序, 全螢幕 = 前後
    全螢幕[0] = True
    假 = 造順序([*面們, 膠, 9999], {*面們, 膠})          # 9999 = 前景的全螢幕程式（不是置頂）
    台.膠囊.膠囊._保持置頂()
    for 面 in 台.面板.面板們.values():
        面._保持置頂()
    assert 假.順序[0] == 膠 and set(假.順序[1:4]) == set(面們) and 假.順序[-1] == 9999   # 面板仍蓋在全螢幕程式上
    換位 = 假.換位
    _跑幾輪(台, 10)
    assert 假.換位 == 換位                                  # 之後每 0.5 秒都放回同一個位置：不互搶、不閃
    assert 假.順序[0] == 膠


def test_全螢幕程式蓋過來時_膠囊與面板都回到它上面(前後):
    台, 膠, 面們, 造順序, 全螢幕 = 前後
    全螢幕[0] = True
    假 = 造順序([9999, 膠, *面們], {膠, *面們, 9999})     # 全螢幕程式跑到最上層
    _跑幾輪(台, 2)
    assert 假.順序[0] == 膠 and 假.順序[-1] == 9999 and set(假.順序[1:4]) == set(面們)


def test_點過面板蓋住膠囊_下一次檢查膠囊回到面板上面_不跳過截圖畫面(前後):
    台, 膠, 面們, 造順序, _ = 前後
    假 = 造順序([8888, 面們[0], 膠, 面們[1], 面們[2], 9999], {8888, 膠, *面們})   # 8888 = 截圖工具的畫面（置頂）
    台.膠囊.膠囊._保持置頂()
    assert 假.順序[:3] == [8888, 膠, 面們[0]]               # 膠囊只移到面板正上方，截圖畫面仍在最上面
    呼叫 = 假.呼叫
    _跑幾輪(台, 10)
    assert 假.呼叫 == 呼叫                                  # 沒被蓋：完全不動前後順序


def test_沒有重疊也沒全螢幕_完全不動前後順序(前後):
    台, 膠, 面們, 造順序, _ = 前後
    假 = 造順序([膠, *面們, 9999], {膠, *面們})
    _跑幾輪(台, 10)
    assert 假.呼叫 == 0 and 假.換位 == 0


def test_截圖工具在前景時_面板與膠囊不蓋過截圖畫面(前後):
    台, 膠, 面們, 造順序, 全螢幕 = 前後
    全螢幕[0] = False                                      # 截圖工具是系統程式：前景是全螢幕程式() 回傳 False
    假 = 造順序([8888, 膠, *面們, 9999], {8888, 膠, *面們})
    _跑幾輪(台, 10)
    assert 假.順序[0] == 8888 and 假.呼叫 == 0


def test_面板新開或切換置頂_排在膠囊下面(前後):
    台, 膠, 面們, 造順序, _ = 前後
    假 = 造順序([膠, *面們, 9999], {膠, *面們})
    台.面板.開關("聊天室", True)
    新 = int(台.面板.面板們["聊天室"].winId())
    assert 假.順序[0] == 膠 and 假.在上面(膠, 新)
    面 = next(iter(台.面板.面板們.values()))
    面.設置頂(False)
    面.設置頂(True)
    assert 假.順序[0] == 膠


# ---------- 5. 點過面板之後，滑鼠停在膠囊上仍要出現提示（Qt 的提示事件可能不再產生）----------
def test_沒有Qt提示事件_滑鼠停在膠囊上也會顯示提示_直播時間照跳_離開就收起(環境, monkeypatch):
    台 = 環境["台"]
    從啟動面板開始(台, monkeypatch, 假引擎())
    時刻 = [1000.0]
    monkeypatch.setattr(stream_clock, "_目前", stream_clock.時軸(開播=1000.0 - 65, 時鐘=lambda: 時刻[0], 延遲=0.0))
    框 = 假提示框()
    框.hideText = lambda: setattr(框, "可見", False)
    monkeypatch.setattr(capsule, "QToolTip", 框)
    管, 膠 = 台.膠囊, 台.膠囊.膠囊
    位置 = [膠.frameGeometry().topLeft() - QPoint(80, 80)]          # 先在膠囊外面
    monkeypatch.setattr(膠, "游標位置", lambda: 位置[0])
    for _ in range(10):
        膠._看懸停()
    assert not 框.可見                                          # 沒在膠囊上：不顯示

    位置[0] = 膠.frameGeometry().center()                        # 移到膠囊上；整個過程沒有任何 Qt 的 ToolTip 事件
    for _ in range(capsule.提示等待輪數 - 1):
        膠._看懸停()
    assert not 框.可見                                          # 還沒停夠久
    膠._看懸停()
    assert 框.可見 and "直播時間 01:05" in 框.文字們[-1] and 管.提示計時.isActive()
    時刻[0] += 1
    管._刷新提示()
    assert "直播時間 01:06" in 框.文字們[-1]
    n = len(框.文字們)
    for _ in range(20):                                         # 停久了不會一直重複彈出
        膠._看懸停()
    assert len(框.文字們) == n

    位置[0] = 膠.frameGeometry().topLeft() - QPoint(80, 80)      # 離開：收起提示、停掉每秒更新
    膠._看懸停()
    assert not 框.可見 and not 管.提示計時.isActive()
    位置[0] = 膠.frameGeometry().center()                        # 再移進來：又會顯示
    for _ in range(capsule.提示等待輪數):
        膠._看懸停()
    assert 框.可見 and len(框.文字們) == n + 1
    停止並等完(台)


def test_滑鼠按著拖曳時不顯示提示(環境, monkeypatch):
    台 = 環境["台"]
    框 = 假提示框()
    框.hideText = lambda: setattr(框, "可見", False)
    monkeypatch.setattr(capsule, "QToolTip", 框)
    膠 = 台.膠囊.膠囊
    monkeypatch.setattr(膠, "游標位置", lambda: 膠.frameGeometry().center())
    膠._按下 = (QPoint(0, 0), 膠.pos())
    for _ in range(20):
        膠._看懸停()
    assert not 框.可見
    膠._按下 = None


def test_點過面板之後_膠囊仍會變清楚_點膠囊仍開選單(環境, monkeypatch):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    台 = 環境["台"]
    從啟動面板開始(台, monkeypatch, 假引擎())
    管, 膠 = 台.膠囊, 台.膠囊.膠囊
    monkeypatch.setattr(膠, "游標位置", lambda: 膠.frameGeometry().center())     # 滑鼠停在膠囊上
    膠.setWindowOpacity(capsule.半透明)
    膠.動畫.stop()
    膠._看懸停()
    assert 膠.懸停 and 膠.動畫.endValue() == capsule.不透明           # 移上去：開始變清楚
    開過 = []
    monkeypatch.setattr(管, "開選單", lambda: 開過.append(1))
    點 = QPointF(10, 10)
    for 種類 in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        QApplication.sendEvent(膠, QMouseEvent(種類, 點, 膠.mapToGlobal(點), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert 開過 == [1]
    停止並等完(台)
