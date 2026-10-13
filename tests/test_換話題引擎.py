"""安全網測試：live_topics._引擎（換話題核心邏輯）。
假模型依測試腳本回傳 same 或 new_topic；假的 summarize_chunk 只記下被呼叫時收到的內容。不花 API、不連網、不寫專案資料夾。"""
import json
import re

import pytest

import events
import live_topics as lt
import llm
import summarize


def 回(decision="same", start="", brief="簡述", side=None):
    return {"decision": decision, "new_topic_start": start, "topic_brief": brief, "side_notes": side or []}


def 行們(秒們):
    """每行約 120 字，保證每一輪都過 MIN_NEW_CHARS。"""
    return [(s, f"[{s // 60:02d}:{s % 60:02d}] 第{s}秒" + "字" * 110) for s in 秒們]


class 假聊天:
    def __init__(self, 留言們):
        self.留言們 = 留言們

    def 取出(self, 開始, 結束):
        return [m for m in self.留言們 if 開始 < m[0] <= 結束]


@pytest.fixture
def 環境(monkeypatch):
    class E:
        pass
    e = E()
    e.事件們, e.提示們, e.摘要們, e.回覆們 = [], [], [], []
    monkeypatch.setattr(events, "接收者們", [lambda 種類, 內容: e.事件們.append((種類, 內容))])
    events.停止.clear()
    monkeypatch.setattr(lt, "統計", {"分鐘摘要": 0, "JSON失敗": 0})
    monkeypatch.setattr(lt, "存檔", {"摘要": False})
    monkeypatch.setattr(llm, "摘要_思考", True)

    def 假模型(提示詞):
        e.提示們.append(提示詞)
        r = e.回覆們.pop(0) if e.回覆們 else 回()
        return r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)

    def 假摘要(文字, 類型=None, 聊天室紀錄=None, 格式=None):
        e.摘要們.append({"文字": 文字, "聊天": 聊天室紀錄})
        return "假摘要"

    monkeypatch.setattr(summarize, "call_llm", 假模型)
    monkeypatch.setattr(summarize, "summarize_chunk", 假摘要)

    def 跑(秒們, check_min=1, 聊天=None, 修正=True):
        return lt.引擎(iter(行們(秒們)), check_min, "不會寫的檔案", 聊天=聊天, 修正=修正)
    e.跑 = 跑
    return e


def 種類們(e, 名):
    return [c for k, c in e.事件們 if k == 名]


# ---------- 切出新話題 ----------
def test_new_topic_會在切點切出新話題(環境):
    環境.回覆們 = [回()] * 4 + [回("new_topic", "05:00", "新話題簡述")]
    n = 環境.跑(range(0, 601, 60))
    assert n == 2
    assert len(環境.摘要們) == 2
    舊, 新 = 環境.摘要們[0]["文字"], 環境.摘要們[1]["文字"]
    assert "第240秒" in 舊 and "第300秒" not in 舊       # 切點(05:00)之前歸舊話題
    assert "第300秒" in 新 and "第240秒" not in 新       # 切點起歸新話題
    assert len(種類們(環境, "topic_summary")) == 2


def test_new_topic_切點不在新文字裡就不切(環境):
    環境.回覆們 = [回()] * 4 + [回("new_topic", "05:30", "x")]    # 05:30 不是任何一行的時間
    assert 環境.跑(range(0, 601, 60)) == 1
    assert len(環境.摘要們) == 1


def test_話題太短不切(環境):
    環境.回覆們 = [回(), 回("new_topic", "02:00", "x")]    # 第二輪(batch=02:00)：話題才 2 分鐘 < MIN_TOPIC_MIN
    assert 環境.跑(range(0, 301, 60)) == 1


def test_剛好滿最短分鐘數就可以切(環境):
    環境.回覆們 = [回(), 回(), 回("new_topic", "03:00", "x")]   # 03:00 - 00:00 = 180 秒，不算太短
    assert 環境.跑(range(0, 301, 60)) == 2


def test_同話題不切(環境):
    assert 環境.跑(range(0, 601, 60)) == 1
    assert len(環境.摘要們) == 1


# ---------- 超過上限強制結束 ----------
def test_超過上限強制結束(環境):
    n = 環境.跑(range(0, 1021, 60))
    assert n == 2
    assert "第960秒" in 環境.摘要們[0]["文字"] and "第1020秒" not in 環境.摘要們[0]["文字"]
    assert "第1020秒" in 環境.摘要們[1]["文字"]
    assert any("強制結束" in (c.get("印出") or "") for c in 種類們(環境, "info"))


def test_剛好滿上限分鐘數還不強制結束(環境):
    # 到 900 秒（剛好 15 分鐘）為止：不是「超過」，所以整場只有 1 個話題
    assert 環境.跑(range(0, 901, 60)) == 1
    assert not any("強制結束" in (c.get("印出") or "") for c in 種類們(環境, "info"))


# ---------- 支線與聊天按切點分給新舊話題 ----------
def test_支線與聊天按切點分給新舊話題(環境):
    環境.回覆們 = [回(), 回(), 回("new_topic", "06:00", "新", side=[
        {"time": "05:00", "note": "舊支線內容甲"}, {"time": "06:00", "note": "新支線內容乙乙乙"}])]
    聊天 = 假聊天([(250, "a", "舊留言甲"), (360, "b", "新留言乙")])
    n = 環境.跑(range(0, 421, 60), check_min=2, 聊天=聊天)
    assert n == 2
    舊, 新 = 環境.摘要們
    assert "舊支線內容甲" in 舊["文字"] and "新支線內容乙乙乙" not in 舊["文字"]
    assert "舊留言甲" in "".join(舊["聊天"]) and "新留言乙" not in "".join(舊["聊天"])
    assert "新留言乙" in "".join(新["聊天"]) and "舊留言甲" not in "".join(新["聊天"])
    assert "新支線內容乙乙乙" in 新["文字"] and "舊支線內容甲" not in 新["文字"]


def test_沒切話題時支線與聊天留在同一個話題(環境):
    環境.回覆們 = [回(), 回(side=[{"time": "02:00", "note": "某個支線"}])]
    聊天 = 假聊天([(100, "a", "留言一")])
    環境.跑(range(0, 301, 60), 聊天=聊天)
    assert len(環境.摘要們) == 1
    assert "某個支線" in 環境.摘要們[0]["文字"]
    assert "留言一" in "".join(環境.摘要們[0]["聊天"])


# ---------- 其他引擎行為 ----------
def test_新文字太少就跳過判斷(環境):
    短 = [(s, f"[00:{s:02d}] 短") for s in (0, 60, 120)]
    assert lt.引擎(iter(短), 1, "x") == 1
    assert 環境.提示們 == []           # 字數不足 MIN_NEW_CHARS，一次模型都沒問


def test_按停止也會輸出最後一個話題(環境):
    來源 = iter(行們([0, 60]))

    def 吐():
        yield next(來源)
        events.停止.set()
        yield next(來源)
    n = lt.引擎(吐(), 1, "x")
    assert n == 1 and "第0秒" in 環境.摘要們[0]["文字"]
    events.停止.clear()


def test_模型錯誤會直接丟出而不是當成話題沒變(環境, monkeypatch):
    def 壞(提示詞):
        raise llm.金鑰錯誤("金鑰無效")
    monkeypatch.setattr(summarize, "call_llm", 壞)
    with pytest.raises(llm.金鑰錯誤):
        環境.跑(range(0, 301, 60))


# ---------- 判斷一律跟話題開始時定下的「那一件事」比對，不跟每輪改寫的簡述比 ----------
def 主題們(e):
    return [re.search(r"目前話題（開始時定下的一件事，不會改寫）：(.*)", p).group(1) for p in e.提示們]


def test_主題在話題開始時定下_之後不隨簡述漂移(環境):
    環境.回覆們 = [{"decision": "same", "topic": "午餐吃什麼", "topic_brief": "聊午餐"},
               {"decision": "same", "topic": "午餐與晚餐", "topic_brief": "聊到晚餐"},
               {"decision": "same", "topic": "晚餐與電影", "topic_brief": "又聊到電影"}]
    環境.跑(range(0, 241, 60))
    assert 主題們(環境) == ["（剛開始，還沒有定下；用最後幾行判斷）", "午餐吃什麼", "午餐吃什麼", "午餐吃什麼"]
    assert [c["簡述"] for c in 種類們(環境, "current_topic")][:3] == ["聊午餐", "聊到晚餐", "又聊到電影"]   # 介面的簡述照常更新


def test_換話題後換成新的那一件事(環境):
    環境.回覆們 = [{"decision": "same", "topic": "午餐吃什麼"}] * 4 + [
        {"decision": "new_topic", "new_topic_start": "05:00", "topic": "週末要看的電影", "topic_brief": "改聊電影"},
        {"decision": "same", "topic": "電影與爆米花"}]
    環境.跑(range(0, 421, 60))
    assert 主題們(環境)[1:5] == ["午餐吃什麼"] * 4 and 主題們(環境)[5:] == ["週末要看的電影"] * 2


def test_強制結束後下一輪重新定下主題(環境):
    環境.回覆們 = [{"decision": "same", "topic": "很長的一件事"}] * 16 + [{"decision": "same", "topic": "下一件事"}] * 3
    環境.跑(range(0, 1141, 60))
    主 = 主題們(環境)
    i = 主.index("（剛開始，還沒有定下；用最後幾行判斷）", 1)      # 強制結束後的第一輪
    assert set(主[1:i]) == {"很長的一件事"} and 主[i + 1:] and set(主[i + 1:]) == {"下一件事"}
