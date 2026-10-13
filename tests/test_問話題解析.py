"""安全網測試：live_topics.問話題（提示詞組裝、JSON 解析、side_notes／minute 解析、時間必須出現在新文字裡）。"""
import json

import pytest

import live_topics as lt
import llm
import summarize


@pytest.fixture
def 問(monkeypatch):
    """回傳 問(回答, **參數) -> (結果, 提示詞)。回答可以是 dict（轉成 JSON）或字串。"""
    monkeypatch.setattr(lt, "統計", {"分鐘摘要": 0, "JSON失敗": 0})
    monkeypatch.setattr(llm, "摘要_思考", True)

    def 呼叫(回答, 簡述="舊簡述", 最後=("[00:00] 舊行",), 新行=("[01:00] 新行甲", "[01:30] 新行乙"), **參數):
        提示們 = []

        def 假(提示詞):
            提示們.append(提示詞)
            if isinstance(回答, Exception):
                raise 回答
            return 回答 if isinstance(回答, str) else json.dumps(回答, ensure_ascii=False)
        monkeypatch.setattr(summarize, "call_llm", 假)
        return lt.問話題(簡述, list(最後), list(新行), **參數), 提示們[0] if 提示們 else None
    return 呼叫


# ---------- 提示詞組裝 ----------
def test_提示詞包含簡述_最後幾行_新文字(問):
    _, 提示 = 問({"decision": "same"}, 簡述="正在聊遊戲", 最後=("[00:10] 最後一行",))
    assert "正在聊遊戲" in 提示
    assert "[00:10] 最後一行" in 提示
    assert "[01:00] 新行甲" in 提示 and "[01:30] 新行乙" in 提示


def test_沒有主題時寫剛開始(問):
    _, 提示 = 問({"decision": "same"}, 簡述="", 最後=())
    assert "剛開始，還沒有定下" in 提示 and "（無）" in 提示


def test_沒聊天沒參考詞時提示詞沒有那兩段(問):
    _, 提示 = 問({"decision": "same"})
    assert "聊天室留言（" not in 提示 and "聊天室參考詞" not in 提示


def test_有聊天與參考詞時放進提示詞(問):
    _, 提示 = 問({"decision": "same"}, 聊天們=["[00:50] 小明: 好耶"], 參考詞=["爆雷", "新作"])
    assert "[00:50] 小明: 好耶" in 提示
    assert "爆雷、新作" in 提示


def test_要分鐘才有分鐘摘要欄位與規則(問):
    _, 沒要 = 問({"decision": "same"})
    _, 要 = 問({"decision": "same"}, 要分鐘=True)
    assert "minute_summary" not in 沒要
    assert "minute_summary" in 要


def test_分鐘摘要句數跟著設定(問, monkeypatch):
    monkeypatch.setattr(lt, "MINUTE_SENTENCES", 1)
    _, 一句 = 問({"decision": "same"}, 要分鐘=True)
    monkeypatch.setattr(lt, "MINUTE_SENTENCES", 3)
    _, 三句 = 問({"decision": "same"}, 要分鐘=True)
    assert "1 句" in 一句 and "1 到 3 句" in 三句 and "1 到 3 句" not in 一句


# ---------- decision／切點／簡述 ----------
def test_new_topic_回傳切點與新簡述(問):
    結果, _ = 問({"decision": "new_topic", "new_topic_start": "01:30", "topic_brief": "新話題"})
    assert 結果[:3] == ("new_topic", "01:30", "新話題")


def test_認不得的decision當作same(問):
    結果, _ = 問({"decision": "maybe", "topic_brief": "x"})
    assert 結果[0] == "same"


def test_缺少簡述時沿用舊簡述(問):
    結果, _ = 問({"decision": "same"}, 簡述="舊簡述")
    assert 結果[2] == "舊簡述"


def test_回答壞掉當作same並計入JSON失敗(問):
    結果, _ = 問("這不是 JSON")
    assert 結果 == ("same", "", "舊簡述", [], None, "舊簡述")
    assert lt.統計["JSON失敗"] == 1


def test_模型錯誤不吞掉(問):
    with pytest.raises(llm.連線錯誤):
        問(llm.連線錯誤("斷線"))


def test_關閉思考時回答前面有說明文字也讀得到(問, monkeypatch):
    monkeypatch.setattr(llm, "摘要_思考", False)
    結果, _ = 問('我想想……\n{"decision": "new_topic", "new_topic_start": "01:00", "topic_brief": "換了"}')
    assert 結果[:3] == ("new_topic", "01:00", "換了")


def test_取最後JSON優先挑有decision的最後一個():
    回答 = '{"decision": "same", "topic_brief": "a"} 然後 {"x": 1} 最後 {"decision": "new_topic"}'
    assert lt.取最後JSON(回答)["decision"] == "new_topic"
    assert lt.取最後JSON('{"x": 1}') == {"x": 1}
    with pytest.raises(ValueError):
        lt.取最後JSON("沒有json")


# ---------- side_notes：時間必須真的出現在新文字裡 ----------
def test_支線時間在新文字裡才收(問):
    結果, _ = 問({"decision": "same", "side_notes": [
        {"time": "01:00", "note": "有的"}, {"time": "09:99", "note": "沒有這個時間"},
        {"time": "01:30", "note": "   "}]})
    assert 結果[3] == [(60, "有的")]        # 不在新文字裡的、內容空白的都丟掉


def test_支線每輪最多收兩條(問):
    結果, _ = 問({"decision": "same", "side_notes": [
        {"time": "01:00", "note": "一"}, {"time": "01:30", "note": "二"}, {"time": "01:00", "note": "三"}]})
    assert [n for _, n in 結果[3]] == ["一", "二"]


def test_支線格式壞掉就當沒有(問):
    for 壞 in ("不是清單", [{"time": "01:00"}], [{"note": "缺時間"}], None):
        結果, _ = 問({"decision": "same", "side_notes": 壞})
        assert 結果[3] == []


# ---------- minute_summary ----------
def test_分鐘摘要有聊天才保留觀眾反應(問):
    資料 = {"decision": "same", "minute_summary": {"summary": "[01:00] 摘要", "audience": "聊天室在笑"}}
    有, _ = 問(資料, 要分鐘=True, 聊天們=["[00:50] a: w"])
    無, _ = 問(資料, 要分鐘=True)
    assert 有[4] == ("[01:00] 摘要", "聊天室在笑")
    assert 無[4] == ("[01:00] 摘要", "")


def test_沒要分鐘就不解析分鐘摘要(問):
    結果, _ = 問({"decision": "same", "minute_summary": {"summary": "x", "audience": ""}})
    assert 結果[4] is None


def test_分鐘摘要缺欄位或空白就略過(問):
    for 壞 in ({"audience": "x"}, {"summary": "   "}, "字串", None):
        結果, _ = 問({"decision": "same", "minute_summary": 壞}, 要分鐘=True)
        assert 結果[4] is None


# ---------- 換話題標準：一件事一題、跟固定的主題比對 ----------
def test_提示詞有粒度與new_topic條件_主題標明不會改寫(問):
    _, 提示 = 問({"decision": "same"}, 簡述="聊午餐吃什麼")
    assert "一個話題＝一件事" in 提示 and "「、」" in 提示 and "2 分鐘就是 2 分鐘一題" in 提示
    assert "【算 new_topic】" in 提示 and "【算 same】" in 提示 and "離題一兩句又回來" in 提示
    assert "目前話題（開始時定下的一件事，不會改寫）：聊午餐吃什麼" in 提示
    assert '"topic"' in 提示


def test_回傳模型認定的那一件事_沒給就用簡述頂替(問):
    結果, _ = 問({"decision": "new_topic", "new_topic_start": "01:30", "topic": "週末要看的電影", "topic_brief": "改聊電影"})
    assert 結果[5] == "週末要看的電影"
    結果, _ = 問({"decision": "same", "topic_brief": "還在聊午餐"})
    assert 結果[5] == "還在聊午餐"
