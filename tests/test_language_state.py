"""自動偵測語言的保護：狀態列語言顯示、低信心提示、重新偵測。假模型、假音訊、假時鐘，不連網、不呼叫 API。
介面本身（狀態列藥丸、按鈕）沒寫成 pytest：要整個主控台視窗；顯示文字與按鈕可用與否都來自 language_state，已在這裡測。
"""
import numpy as np
import pytest
from conftest import 人聲, 靜音

import events
import language_state as ls
import live_capture as lc

原偵測語言 = lc.偵測語言


# ---------------- 語言狀態（純邏輯）----------------
def test_手動語言_顯示手動_不能重新偵測():
    s = ls.語言狀態()
    s.開始("ja")
    assert s.文字() == "語言：日文（手動）"
    assert not s.顯示按鈕() and not s.可重新偵測() and not s.要求重新偵測()


def test_自動_先偵測中_再顯示日文自動偵測():
    s = ls.語言狀態()
    s.開始("auto")
    assert s.文字() == "語言：偵測中…" and s.顯示按鈕() and not s.可重新偵測()
    s.收偵測("ja", "ok")
    assert s.文字() == "語言：日文（自動偵測）" and s.可重新偵測() and not s.有警示()


def test_第一次低信心退回中文_明確提示():
    s = ls.語言狀態()
    s.開始("auto")
    s.收偵測("zh", "低信心")
    assert s.文字() == "語言：中文（偵測不確定，可按重新偵測或手動選語言）"
    assert s.有警示() and s.可重新偵測()


def test_偵測例外失敗_也有明確提示():
    s = ls.語言狀態()
    s.開始("auto")
    s.收偵測("zh", "失敗")
    assert "偵測失敗" in s.文字() and "重新偵測" in s.文字()


def test_重新偵測_清掉結果回到偵測中_成功後更新():
    s = ls.語言狀態()
    s.開始("auto")
    s.收偵測("zh", "低信心")
    assert s.要求重新偵測()
    assert s.文字() == "語言：偵測中…" and not s.有警示()
    s.收偵測("ja", "ok", 重新偵測=True)
    assert s.文字() == "語言：日文（自動偵測）"


def test_重新偵測低信心_維持原語言並提示():
    s = ls.語言狀態()
    s.開始("auto")
    s.收偵測("ja", "ok")
    s.要求重新偵測()
    s.收偵測("ja", "低信心", 重新偵測=True)       # 引擎傳回原語言
    assert s.文字() == "語言：日文（重新偵測不確定，維持原語言）"
    s.要求重新偵測()
    s.收偵測("ja", "失敗", 重新偵測=True)
    assert s.文字() == "語言：日文（重新偵測失敗，維持原語言）"


def test_偵測中不能重複按重新偵測():
    s = ls.語言狀態()
    s.開始("auto")
    assert not s.要求重新偵測()


def test_文字稿模式不偵測_按鈕隱藏():
    s = ls.語言狀態()
    s.開始("auto", 直播=False)
    assert "文字稿模式" in s.文字() and not s.顯示按鈕()


def test_結束後不顯示():
    s = ls.語言狀態()
    s.開始("ja")
    s.結束()
    assert not s.顯示中() and s.文字() == ""


# ---------------- 偵測語言本身（假模型）----------------
class 假模型:
    def __init__(self, 結果們):
        self.結果們 = list(結果們)

    def detect_language(self, 音訊, vad_filter=False):
        r = self.結果們.pop(0)
        if isinstance(r, Exception):
            raise r
        return r[0], r[1], []


@pytest.fixture
def 收事件():
    收到 = []
    events.接收者們.clear()
    events.接收者們.append(lambda 種類, 內容: 收到.append((種類, 內容)) if 種類 == "language_detected" else None)
    yield 收到
    events.接收者們.clear()


A = [np.zeros(2, dtype=np.float32)]


def test_偵測成功送出信心與ok(收事件):
    assert lc.偵測語言(假模型([("ja", 0.9)]), A) == "ja"
    assert 收事件[0][1] == {"語言": "ja", "信心": 0.9, "狀態": "ok", "重新偵測": False}


def test_第一次低信心退回中文_事件標明低信心(收事件):
    assert lc.偵測語言(假模型([("ja", 0.3)]), A) == "zh"
    assert 收事件[0][1]["狀態"] == "低信心" and 收事件[0][1]["語言"] == "zh"


def test_第一次例外退回中文_事件標明失敗(收事件):
    assert lc.偵測語言(假模型([ValueError("沒有人聲")]), A) == "zh"
    assert 收事件[0][1]["狀態"] == "失敗"


def test_重新偵測低信心_維持原語言不退回中文(收事件):
    assert lc.偵測語言(假模型([("ko", 0.39)]), A, 保持="ja") == "ja"
    assert 收事件[0][1] == {"語言": "ja", "信心": pytest.approx(0.39), "狀態": "低信心", "重新偵測": True}


def test_重新偵測例外_維持原語言(收事件):
    assert lc.偵測語言(假模型([RuntimeError("x")]), A, 保持="ja") == "ja"
    assert 收事件[0][1]["狀態"] == "失敗" and 收事件[0][1]["重新偵測"]


def test_信心剛好等於門檻算成功(收事件):
    assert lc.偵測語言(假模型([("en", lc.最低信心)]), A) == "en"


# ---------------- 整個假流程：狀態列依序變化、重新偵測不中斷串流 ----------------
def 記事件():
    收到 = []
    events.接收者們.append(lambda 種類, 內容: 收到.append((種類, 內容)) if 種類 == "language_detected" else None)
    return 收到


def test_假流程_偵測中到日文自動偵測(流程, monkeypatch):
    monkeypatch.setattr(lc, "偵測語言", 原偵測語言)
    monkeypatch.setattr(lc, "載入模型", lambda 語言: 假模型([("ja", 0.95)]))
    收到 = 記事件()
    s = ls.語言狀態()
    s.開始("auto")
    assert s.文字() == "語言：偵測中…"
    流程([人聲, 人聲])
    for _, 內容 in 收到:
        s.收偵測(內容["語言"], 內容["狀態"], 內容["重新偵測"])
    assert s.文字() == "語言：日文（自動偵測）"


def test_假流程_第一次低信心_狀態列顯示不確定且用中文(流程, monkeypatch):
    monkeypatch.setattr(lc, "偵測語言", 原偵測語言)
    monkeypatch.setattr(lc, "載入模型", lambda 語言: 假模型([("ja", 0.2)]))
    收到 = 記事件()
    s = ls.語言狀態()
    s.開始("auto")
    流程([人聲, 人聲])
    for _, 內容 in 收到:
        s.收偵測(內容["語言"], 內容["狀態"], 內容["重新偵測"])
    assert s.文字() == "語言：中文（偵測不確定，可按重新偵測或手動選語言）"


def 流程中按重新偵測(流程, monkeypatch, 結果們, 段們):
    """第一段轉錄時按下重新偵測（模擬使用者）。回傳 (偵測呼叫記錄, 轉錄過的段數, 事件們)。"""
    monkeypatch.setattr(lc, "偵測語言", 原偵測語言)
    monkeypatch.setattr(lc, "載入模型", lambda 語言: 假模型(結果們))
    轉錄次數 = []

    def 轉錄(model, 音訊, 語言):
        轉錄次數.append(語言)
        if len(轉錄次數) == 1:
            events.重新偵測.set()
        return [(0.5, "字")]
    monkeypatch.setattr(lc, "轉錄一段", 轉錄)
    收到 = 記事件()
    流程(段們)
    return 轉錄次數, 收到


def test_重新偵測_不中斷串流_下一段有人聲就套用新語言(流程, monkeypatch):
    轉錄次數, 收到 = 流程中按重新偵測(流程, monkeypatch, [("ja", 0.9), ("en", 0.9)], [人聲, 人聲, 人聲])
    assert 轉錄次數 == ["ja", "en", "en"]              # 3 段都有轉錄（串流沒中斷），第 2 段起換成新語言
    assert [(c["語言"], c["重新偵測"]) for _, c in 收到] == [("ja", False), ("en", True)]


def test_重新偵測_下一段沒人聲就繼續等(流程, monkeypatch):
    轉錄次數, 收到 = 流程中按重新偵測(流程, monkeypatch, [("ja", 0.9), ("en", 0.9)], [人聲, 靜音, 人聲])
    assert 轉錄次數 == ["ja", "en"]                    # 靜音那段沒有轉錄，第 3 段才重新偵測
    assert [c["語言"] for _, c in 收到] == ["ja", "en"]


def test_重新偵測低信心_保持日文不退回中文(流程, monkeypatch):
    轉錄次數, 收到 = 流程中按重新偵測(流程, monkeypatch, [("ja", 0.9), ("en", 0.1)], [人聲, 人聲, 人聲])
    assert 轉錄次數 == ["ja", "ja", "ja"]
    assert 收到[1][1]["狀態"] == "低信心" and 收到[1][1]["語言"] == "ja" and 收到[1][1]["重新偵測"]
    s = ls.語言狀態()
    s.開始("auto")
    s.收偵測(收到[0][1]["語言"], "ok")
    s.要求重新偵測()
    s.收偵測(收到[1][1]["語言"], 收到[1][1]["狀態"], 收到[1][1]["重新偵測"])
    assert s.文字() == "語言：日文（重新偵測不確定，維持原語言）"


def test_手動語言按重新偵測沒有作用(流程, monkeypatch):
    monkeypatch.setattr(lc, "偵測語言", 原偵測語言)
    monkeypatch.setattr(lc, "載入模型", lambda 語言: 假模型([]))
    events.重新偵測.set()
    收到 = 記事件()
    流程([人聲, 人聲], 語言="ja")
    assert 收到 == []                                  # 手動語言：不會偵測
