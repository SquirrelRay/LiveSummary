"""按「停止」後的收尾（2026-10-15 打包版看日文直播 13 分鐘、延伸思考開，按停止後卡住超過 30 秒）：
- 按下停止畫面立刻有反應（介面執行緒不等任何模型呼叫），擷取、轉錄馬上停（引擎不等這一輪的話題判斷）；
- 最後一個話題的摘要在背景整理，有時間上限；超過上限照樣存檔，這一題留說明，結束訊息說哪部分沒完成；
- 收尾中按「結束程式」：先問；確定就不再等，已完成的內容都留著。
全部用假的慢回應（模型要 40 秒才回來），不呼叫真的 API、不連網。"""
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import test_介面冒煙 as 冒煙
from PySide6.QtCore import QTimer

import capsule
import events
import live_topics as lt
import llm
import summarize

qapp, 環境 = 冒煙.qapp, 冒煙.環境
等 = 冒煙.等
慢秒 = 40          # 假模型要這麼久才回來（測試結束時放行，不會真的等滿）


# ---------- 引擎（不開介面） ----------
@pytest.fixture
def 引擎環境(monkeypatch, tmp_path):
    class E:
        pass
    e = E()
    e.事件們, e.摘要們 = [], []
    e.放行 = threading.Event()
    e.判斷開始, e.摘要開始 = threading.Event(), threading.Event()
    e.卡判斷 = e.卡摘要 = False
    monkeypatch.setattr(events, "接收者們", [lambda 種類, 內容: e.事件們.append((種類, dict(內容)))])
    events.停止.clear()
    events.放棄收尾.clear()
    monkeypatch.setattr(lt, "統計", {"分鐘摘要": 0, "JSON失敗": 0})
    monkeypatch.setattr(lt, "存檔", {"摘要": True})
    monkeypatch.setattr(llm, "摘要_思考", True)

    def 假判斷(提示詞):
        e.判斷開始.set()
        if e.卡判斷:
            e.放行.wait(慢秒)
        return '{"decision": "same", "topic_brief": "簡述", "side_notes": []}'

    def 假摘要(文字, 類型=None, 聊天室紀錄=None, 格式=None):
        e.摘要開始.set()
        if e.卡摘要:
            e.放行.wait(慢秒)
        e.摘要們.append(文字)
        return "【話題標題】假話題\n【摘要】假的話題摘要"

    monkeypatch.setattr(summarize, "call_llm", 假判斷)
    monkeypatch.setattr(summarize, "summarize_chunk", 假摘要)
    e.檔 = str(tmp_path / "稿_話題摘要.md")
    yield e
    e.放行.set()               # 被丟下的那一次呼叫在背景自己結束
    events.停止.clear()
    events.放棄收尾.clear()


def 行(秒):
    return 秒, f"[{秒 // 60:02d}:{秒 % 60:02d}] 第{秒}秒的內容" + "很長的句子" * 10


class 直播來源:
    """像 live_capture 的產生器：吐完 吐到 秒之前的行後就一直等（直播還在進行），按停止才結束；關掉時記下來。"""

    def __init__(self, 秒們):
        self.秒們 = 秒們
        self.關掉了 = threading.Event()

    def __iter__(self):
        try:
            for 秒 in self.秒們:
                yield 行(秒)
            while not events.停止.is_set():
                time.sleep(0.01)
        finally:
            self.關掉了.set()


def 跑引擎(e, 來源):
    結果 = {}
    t = threading.Thread(target=lambda: 結果.update(話題數=lt.引擎(iter(來源), 1, e.檔)), daemon=True)
    t.start()
    return t, 結果


def test_按停止時不等這一輪的話題判斷_擷取先關掉再整理最後話題(引擎環境):
    e = 引擎環境
    e.卡判斷 = True                                   # 這一輪的話題判斷要 40 秒才回來
    來源 = 直播來源(range(0, 70, 5))
    t, 結果 = 跑引擎(e, 來源)
    assert e.判斷開始.wait(5)
    t0 = time.monotonic()
    events.停止.set()
    assert 來源.關掉了.wait(2), "按停止後音訊擷取沒有馬上關掉"
    t.join(5)
    assert not t.is_alive(), "引擎還在等那一輪的話題判斷"
    assert time.monotonic() - t0 < 2
    assert 結果["話題數"] == 1 and "第0秒" in e.摘要們[0] and "第60秒" in e.摘要們[0]    # 沒判斷到的那一輪也進了最後話題
    assert ("wrapup", {"階段": "話題摘要", "上限": lt.收尾上限秒}) in e.事件們
    assert lt.收尾["未完成"] == []


def test_最後話題摘要超過時間上限_照樣存檔並說明沒完成(引擎環境, monkeypatch):
    e = 引擎環境
    monkeypatch.setattr(lt, "收尾上限秒", 0.5)
    e.卡摘要 = True                                   # 最後的話題摘要要 40 秒
    t, _ = 跑引擎(e, 直播來源([0, 5, 10]))
    time.sleep(0.2)
    t0 = time.monotonic()
    events.停止.set()
    assert e.摘要開始.wait(2)
    t.join(5)
    花了 = time.monotonic() - t0
    assert not t.is_alive() and 0.4 < 花了 < 2, 花了
    內文們 = [內容["內文"] for 種類, 內容 in e.事件們 if 種類 == "topic_summary"]
    assert len(內文們) == 1 and "0.5 秒內沒有整理完" in 內文們[0] and "內容請看直播稿" in 內文們[0]
    assert lt.收尾["未完成"] == ["話題（00:00 - 00:10）的摘要"]
    with open(e.檔, encoding="utf-8") as f:
        存檔 = f.read()
    assert "內容請看直播稿" in 存檔
    e.放行.set()                                      # 40 秒的那一次晚回來：丟掉，不會再寫一次
    time.sleep(0.3)
    with open(e.檔, encoding="utf-8") as f:
        assert f.read() == 存檔


def test_收尾中放棄_不等最後話題摘要(引擎環境):
    e = 引擎環境
    e.卡摘要 = True                                   # 上限 90 秒，但使用者確定要直接結束程式
    t, _ = 跑引擎(e, 直播來源([0, 5, 10]))
    time.sleep(0.2)
    events.停止.set()
    assert e.摘要開始.wait(2)
    t0 = time.monotonic()
    events.放棄收尾.set()
    t.join(3)
    assert not t.is_alive() and time.monotonic() - t0 < 1
    內文 = next(內容["內文"] for 種類, 內容 in e.事件們 if 種類 == "topic_summary")
    assert "結束程式時這一段還沒整理完" in 內文
    assert lt.收尾["未完成"] == ["話題（00:00 - 00:10）的摘要"]


def test_沒按停止_直播自己結束時摘要不設時間上限(引擎環境, monkeypatch):
    e = 引擎環境
    monkeypatch.setattr(lt, "收尾上限秒", 0.1)

    def 慢一點(文字, 類型=None, 聊天室紀錄=None, 格式=None):
        time.sleep(0.4)
        e.摘要們.append(文字)
        return "【話題標題】假話題\n【摘要】假的話題摘要"
    monkeypatch.setattr(summarize, "summarize_chunk", 慢一點)
    assert lt.引擎(iter([行(0), 行(5)]), 1, e.檔) == 1
    assert len(e.摘要們) == 1 and lt.收尾["截止"] is None and lt.收尾["未完成"] == []
    assert not any(種類 == "wrapup" for 種類, _ in e.事件們)


def test_模型錯誤在背景呼叫裡也照樣丟出(引擎環境, monkeypatch):
    def 壞(提示詞):
        raise llm.金鑰錯誤("金鑰不對")
    monkeypatch.setattr(summarize, "call_llm", 壞)
    with pytest.raises(llm.金鑰錯誤):
        lt.引擎(iter([行(s) for s in range(0, 70, 5)]), 1, 引擎環境.檔)


# ---------- 介面（offscreen） ----------
class 慢模型:
    """第一輪話題判斷正常回來（有一則已完成的分鐘摘要）；第二輪判斷、話題摘要都要 40 秒才回來。"""

    def __init__(self):
        self.放行 = threading.Event()
        self.判斷次數 = 0
        self.卡住了 = threading.Event()

    def __call__(self, 提示詞, 模型=None, 類別="摘要"):
        if 類別 != "摘要":
            return "[]"
        if '"decision"' in 提示詞:
            self.判斷次數 += 1
            if self.判斷次數 == 1:
                return ('{"decision": "same", "topic_brief": "假話題", "side_notes": [], '
                        '"minute_summary": {"summary": "[00:30] 已完成的分鐘摘要", "audience": ""}}')
        self.卡住了.set()
        self.放行.wait(慢秒)
        return "【話題標題】晚回來的話題\n【摘要】晚回來的摘要"


@pytest.fixture
def 慢介面(環境, monkeypatch):
    模型 = 慢模型()
    monkeypatch.setattr(llm, "call_llm", 模型)
    events.放棄收尾.clear()
    台 = 環境["台"]
    稿 = 環境["暫存"] / "慢文字稿.txt"
    稿.write_text("\n".join(f"[{s // 60:02d}:{s % 60:02d}] テスト{s}です" + "長い文章" * 10 for s in range(0, 900, 5)),
                 encoding="utf-8")
    台.檔案鈕.setChecked(True)
    台._切換來源()
    台.檔案框.setText(str(稿))
    台.速度選.setCurrentIndex(台.速度選.findData(60))       # 60 倍速：第二輪話題判斷約在開始後 2 秒
    台.語言選.setCurrentIndex(台.語言選.findData("ja"))
    台.開始()
    assert 等(lambda: 模型.卡住了.is_set(), 15), "第二輪話題判斷沒有開始"
    assert 等(lambda: 台.分鐘頁.總數 == 1, 5)
    yield 台, 模型, 環境["暫存"] / "慢文字稿_話題摘要.md"
    模型.放行.set()
    events.放棄收尾.clear()


def 數心跳():
    """介面執行緒每 50 毫秒跳一次：凍住的話就不會跳。"""
    心跳 = {"次": 0}
    計 = QTimer()
    計.timeout.connect(lambda: 心跳.__setitem__("次", 心跳["次"] + 1))
    計.start(50)
    return 計, 心跳


def test_介面_按停止畫面立刻有反應_收尾超過上限照樣存檔(慢介面, monkeypatch):
    台, 模型, 摘要檔 = 慢介面
    monkeypatch.setattr(lt, "收尾上限秒", 1.5)
    計, 心跳 = 數心跳()
    稿數 = 台.稿頁.總數
    t0 = time.monotonic()
    台.膠囊.問停止()                                  # 膠囊選單「停止」（確認框在測試裡換成「確定」）
    反應 = time.monotonic() - t0
    assert 反應 < 0.5, 反應
    assert 台.結束中 and 台.停止鈕.text().startswith("整理中") and not 台.停止鈕.isEnabled()
    assert "正在整理最後的話題摘要" in 台.收尾字() and 台.膠囊.計算狀態() == "收尾"
    assert any("已停止擷取與轉錄" in l for l in 台.膠囊.提示文字().splitlines())
    assert 等(lambda: not 台.執行中() and 台.開始鈕.isEnabled(), 5), "收尾超過時間上限還在等"
    完成 = time.monotonic() - t0
    計.stop()
    assert 1.4 < 完成 < 4, 完成
    assert 心跳["次"] >= 完成 / 0.05 * 0.5, 心跳          # 整段收尾期間介面一直有在跑（沒有凍住）
    assert 台.稿頁.總數 == 稿數                           # 按停止後沒有再轉出新的行
    assert 台.分鐘頁.總數 == 1                            # 已完成的分鐘摘要還在
    assert 台.話題頁.總數 == 1 and 台.開始鈕.isEnabled()
    存檔 = 摘要檔.read_text(encoding="utf-8")
    assert "1.5 秒內沒有整理完" in 存檔 and "內容請看直播稿" in 存檔
    提示們 = list(台.提示層.條們)
    assert any("收尾來不及完成：話題（00:00 - " in 字 and "其他內容都已存檔" in 字 for 字 in 提示們), 提示們
    assert not any("正在整理最後的話題摘要" in 字 for 字 in 提示們)
    模型.放行.set()                                       # 40 秒的那一次晚回來：不會再寫進存檔
    time.sleep(0.3)
    等(lambda: False, 0.2)
    assert 摘要檔.read_text(encoding="utf-8") == 存檔 and 台.話題頁.總數 == 1


def test_介面_收尾中按結束程式_先問_取消就繼續等(慢介面, monkeypatch):
    台, _, _ = 慢介面
    台.膠囊.問停止()
    問過 = []
    monkeypatch.setattr(capsule, "確認", lambda 父, 標題, 文字: 問過.append(文字) or False)
    台.膠囊.結束程式()
    assert 問過 == [capsule.收尾中結束提示] and "摘要還在整理中，確定要結束嗎？" in 問過[0]
    等(lambda: False, 0.5)
    assert 台.執行中() and 台.結束中 and not 台.要結束 and not events.放棄收尾.is_set()


def test_介面_收尾中按結束程式_確定就不再等_已完成的內容留著(慢介面, monkeypatch):
    台, _, 摘要檔 = 慢介面
    台.膠囊.問停止()
    assert 等(lambda: 台._收尾階段 == "話題摘要", 2)
    monkeypatch.setattr(capsule, "確認", lambda *a: True)
    t0 = time.monotonic()
    台.膠囊.結束程式()                                    # 收尾上限 90 秒，但不用等它
    assert 等(lambda: not 台.執行中() and 台.開始鈕.isEnabled(), 3)
    assert time.monotonic() - t0 < 2
    存檔 = 摘要檔.read_text(encoding="utf-8")
    assert "結束程式時這一段還沒整理完" in 存檔
    assert 台.分鐘頁.總數 == 1
    assert 等(lambda: not 台.膠囊.膠囊.isVisible(), 3) and not 台.isVisible()     # 收尾完就照原本的流程關閉
