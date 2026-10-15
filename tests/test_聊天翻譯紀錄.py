"""聊天室翻譯（乾淨電腦測試：日文直播看不到任何聊天翻譯）：
翻譯回來後正確顯示（含模型回答夾了程式碼框）、不翻的留言出現前先說明一次、失敗會說明並寫紀錄、
結束時寫一行統計（不翻原因、每批 API 秒數）。
說明行真的出現在聊天室面板與主控台的測試在 test_聊天翻譯介面.py。全部用假時鐘、假模型，不呼叫 API、不連網。"""
import json
import os
import re

import pytest

import app_paths
import chat_translate as ct
import events
import llm


class 假時鐘:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def 事件們(monkeypatch):
    收到 = []
    monkeypatch.setattr(events, "接收者們", [lambda 種類, 內容: 收到.append((種類, 內容))])
    return 收到


@pytest.fixture
def 器(monkeypatch, 事件們):
    monkeypatch.setattr(llm, "聊天翻譯用量", {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0})
    monkeypatch.setattr(llm, "停止原因們", {})
    if os.path.exists(app_paths.聊天翻譯紀錄檔()):
        os.remove(app_paths.聊天翻譯紀錄檔())
    鐘 = 假時鐘()
    d = ct.聊天翻譯器(時鐘=鐘)
    d.開始(True, "ja", "claude-haiku-5-5", 0.1, 0.5, 每分上限=30, 執行緒=False)
    d.面板開著 = True
    return d, 鐘


_號 = iter(range(1, 100000))


def 留言(d, 內容):
    號 = next(_號)
    d.接收("chat_line", {"秒": 0, "時間字": "00:00", "使用者": "u", "內容": 內容, "編號": 號})
    return 號


def 送一批(d, 鐘, 秒=8):
    鐘.t += 秒
    d.處理一次()
    d.放出一次()


def 畫面(事件們):
    """聊天室面板會出現的東西（照順序）：說明行是 ("說明", 文字)，留言是 (內容, 譯文)。"""
    return [("說明", c["說明"]) if 種 == "chat_status" else (c["內容"], c["譯文"])
            for 種, c in 事件們 if 種 in ("chat_status", "chat_show")]


def 紀錄():
    if not os.path.exists(app_paths.聊天翻譯紀錄檔()):
        return ""
    with open(app_paths.聊天翻譯紀錄檔(), encoding="utf-8") as f:
        return f.read()


def 回答者(回答, 秒=0.0, 鐘=None, 停止="end_turn"):
    def 呼叫(提示詞):
        if 鐘:
            鐘.t += 秒
        llm.停止原因們["聊天翻譯"] = 停止
        llm._記用量(100, 20, "聊天翻譯")
        return 回答(re.findall(r"^\d+\. (.*)$", 提示詞.split("留言：", 1)[1], re.MULTILINE)) if callable(回答) else 回答
    return 呼叫


@pytest.mark.parametrize("包法", [
    lambda 譯們: json.dumps(譯們, ensure_ascii=False),
    lambda 譯們: "```json\n" + json.dumps(譯們, ensure_ascii=False) + "\n```",       # 模型加了程式碼框
    lambda 譯們: "好的：\n" + json.dumps(譯們, ensure_ascii=False),                   # 前面多一句說明
])
def test_翻譯回來後原文與譯文一起出現(器, 事件們, 包法):
    d, 鐘 = 器
    d.呼叫 = 回答者(lambda 原們: 包法([f"譯{i}" for i in range(len(原們))]))
    留言(d, "今のは惜しかった")
    留言(d, "このキャラ強いね")
    送一批(d, 鐘)
    assert 畫面(事件們) == [("今のは惜しかった", "譯0"), ("このキャラ強いね", "譯1")]
    assert d.統計["已翻"] == 2 and d.統計["失敗"] == 0
    assert "翻譯失敗" not in 紀錄()
    assert not any(種 == "chat_status" for 種, _ in 事件們)          # 全部都有翻：不用說明


def test_不翻的留言出現前先說明一次_之後不再說明(器, 事件們):
    """乾淨電腦那場：前 28 秒的留言幾乎都是自訂表情（□）、草，看起來像翻譯壞掉。"""
    d, 鐘 = 器
    d.呼叫 = 回答者(lambda 原們: json.dumps([f"譯:{t}" for t in 原們], ensure_ascii=False))
    for t in ("□□□", "草", "ｗｗｗ", "かわいい"):
        留言(d, t)
    d.放出一次()
    留言(d, "今のは惜しかった")
    留言(d, "888")
    送一批(d, 鐘)
    結果 = 畫面(事件們)
    assert 結果[0] == ("說明", ct.不翻說明)
    assert 結果[1:] == [("□□□", None), ("草", None), ("ｗｗｗ", None), ("かわいい", None),
                       ("今のは惜しかった", "譯:今のは惜しかった"), ("888", None)]
    assert sum(1 for x in 結果 if x[0] == "說明") == 1
    assert d.不翻原因們 == {"純符號": 1, "草": 2, "固定短語": 1, "純數字": 1}


def test_讀不出譯文_寫紀錄附回答與停止原因_說明一次(器, 事件們):
    d, 鐘 = 器
    d.呼叫 = 回答者("抱歉，我無法翻譯。", 停止="end_turn")
    留言(d, "今のは惜しかった")
    送一批(d, 鐘)
    留言(d, "このキャラ強いね")
    送一批(d, 鐘)
    結果 = 畫面(事件們)
    說明們 = [x[1] for x in 結果 if x[0] == "說明"]
    assert 說明們 == [ct.失敗說明.format(原因="讀不出譯文")]
    assert ("今のは惜しかった", None) in 結果 and ("このキャラ強いね", None) in 結果
    字 = 紀錄()
    assert 字.count("翻譯失敗：讀不出譯文，stop_reason=end_turn") == 2 and "抱歉，我無法翻譯。" in 字


def test_則數對不上_對得上的照用_紀錄寫則數(器, 事件們):
    d, 鐘 = 器
    d.呼叫 = 回答者('["只有一則"]', 停止="max_tokens")
    留言(d, "今のは惜しかった")
    留言(d, "このキャラ強いね")
    送一批(d, 鐘)
    assert ("今のは惜しかった", "只有一則") in 畫面(事件們) and ("このキャラ強いね", None) in 畫面(事件們)
    assert "則數對不上：送 2 則、回 1 則，stop_reason=max_tokens" in 紀錄()


def test_呼叫出錯_紀錄錯誤類型不含訊息全文(器, 事件們):
    d, 鐘 = 器

    def 壞(提示詞):
        raise RuntimeError("帶著金鑰 sk-ant-秘密 的錯誤訊息")
    d.呼叫 = 壞
    留言(d, "今のは惜しかった")
    送一批(d, 鐘)
    assert "翻譯失敗：1 則，錯誤類型=RuntimeError" in 紀錄() and "sk-ant" not in 紀錄()
    assert ("說明", ct.失敗說明.format(原因="呼叫模型出錯")) in 畫面(事件們)


def test_結束時寫一行統計_含不翻原因與API秒數(器, 事件們):
    d, 鐘 = 器
    d.呼叫 = 回答者(lambda 原們: json.dumps(["譯"] * len(原們)), 秒=8.28, 鐘=鐘)
    留言(d, "□")
    留言(d, "草")
    留言(d, "今のは惜しかった")
    送一批(d, 鐘)
    d.結束()
    d.結束()                                      # 停止時可能呼叫兩次：只寫一行
    字 = 紀錄()
    assert 字.count("本場統計") == 1
    assert "送翻 1 則（1 批），已翻 1" in 字 and "不翻 2 則（純符號 1、草 1）" in 字
    assert "每批 API 秒數：平均 8.28、最大 8.28" in 字
    assert "2 則不需要翻（表情、草、常見短語等）" in d.統計文字()


def test_沒有任何留言就不寫統計(器):
    d, _ = 器
    d.結束()
    assert 紀錄() == ""


def test_新的一場重新說明一次(器, 事件們):
    d, _ = 器
    留言(d, "草")
    d.放出一次()
    d.開始(True, "ja", "m", 0.1, 0.5, 執行緒=False)
    d.面板開著 = True
    留言(d, "草")
    d.放出一次()
    assert sum(1 for x in 畫面(事件們) if x[0] == "說明") == 2
