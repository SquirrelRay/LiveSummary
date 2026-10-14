"""給使用者看的輸出裡的簡體字轉繁體（traditional.py）：簡體轉繁體、本來是繁體的不動、詞庫顯示寫法不改、日文漢字名字不誤轉。
用假的模型回覆，不呼叫真 API。"""
import json

import pytest

import glossary
import live_topics as lt
import llm
import subtitle
import summarize
import traditional as tr


@pytest.fixture(autouse=True)
def 沒有詞庫(monkeypatch):
    monkeypatch.setattr(glossary, "本場詞庫", None)


def 詞庫有(monkeypatch, tmp_path, *條目們):
    詞庫 = glossary.詞庫("測試台", 資料夾路徑=str(tmp_path))
    詞庫.條目們 = [glossary.條目(*e) for e in 條目們]
    monkeypatch.setattr(glossary, "本場詞庫", 詞庫)
    return 詞庫


# ---------- 簡體轉繁體 ----------
def test_簡體轉成台灣繁體():
    assert tr.轉繁體("萨奇说烤鸡很好吃。") == "薩奇說烤雞很好吃。"
    assert tr.轉繁體("[14:44] 实况主说这次没有烤鸡") == "[14:44] 實況主說這次沒有烤雞"


def test_簡體子句裡的兼用字照上下文轉():
    assert tr.轉繁體("他们后来去面包店") == "他們後來去麵包店"


def test_本來就是繁體的一字不動():
    原文 = "皇后在公里外的這裡乾杯，干擾于先生；頭髮、麵包、面對一隻貓，只有台灣有颱風。後來的歷史系統。"
    assert tr.轉繁體(原文) == 原文


def test_只轉有簡體字的子句_同一段其他繁體子句不動():
    assert tr.轉繁體("實況主說萨奇很可愛，台灣的干擾很多。") == "實況主說薩奇很可愛，台灣的干擾很多。"


def test_英文數字時間戳記與空字串照原樣():
    for 字 in ("", None, "[1:23:45] OK 123", "Doncaster"):
        assert tr.轉繁體(字) == 字


def test_沒裝opencc時照原樣不出錯(monkeypatch):
    monkeypatch.setattr(tr, "_轉換器", False)
    tr.是簡體字.cache_clear()
    try:
        assert tr.轉繁體("萨奇说") == "萨奇说"
    finally:
        tr.是簡體字.cache_clear()


# ---------- 詞庫顯示寫法不被改 ----------
def test_詞庫手動與上網的顯示寫法不轉_候選照轉(monkeypatch, tmp_path):
    詞庫有(monkeypatch, tmp_path, ("萨奇", "", "手動"), ("小鸟", "", "上網"), ("烤鸡", "", "候選"))
    assert tr.轉繁體("萨奇和小鸟说烤鸡好吃") == "萨奇和小鸟說烤雞好吃"


def test_詞庫原文也不轉(monkeypatch, tmp_path):
    詞庫有(monkeypatch, tmp_path, ("國木田", "国木田", "手動"))
    assert tr.轉繁體("说到国木田") == "說到国木田"


def test_忽略的詞庫條目不保護(monkeypatch, tmp_path):
    詞庫有(monkeypatch, tmp_path, ("萨奇", "", "忽略"))
    assert tr.轉繁體("萨奇") == "薩奇"


# ---------- 日文漢字名字不誤轉 ----------
def test_外語直播_括號裡的日文原文不轉():
    原文 = "主持人介紹國木田獨步（国木田独歩），學生會長（生徒会長）也來了"
    assert tr.轉繁體(原文, 保護括號=True) == 原文


def test_外語直播_括號外的簡體照轉_括號裡不動():
    assert tr.轉繁體("实况主（国木田）说", 保護括號=True) == "實況主（国木田）說"


def test_中文直播_含假名的括號也不轉():
    原文 = "艾連（エレン・学園）"
    assert tr.轉繁體(原文) == 原文


def test_中文直播_沒假名的括號裡的簡體照轉():
    assert tr.轉繁體("薩奇（萨奇）") == "薩奇（薩奇）"


def test_日文新字體本來就不是簡體_不會被轉():
    assert tr.轉繁體("広瀬、桜井、沢村、気持ち") == "広瀬、桜井、沢村、気持ち"


# ---------- 接到輸出流程 ----------
@pytest.fixture
def 問(monkeypatch):
    monkeypatch.setattr(lt, "統計", {"分鐘摘要": 0, "JSON失敗": 0})
    monkeypatch.setattr(llm, "摘要_思考", False)

    def 呼叫(資料, 外語=False):
        monkeypatch.setattr(summarize, "語言說明", summarize.外語提示 if 外語 else "")
        monkeypatch.setattr(summarize, "call_llm", lambda 提示詞: json.dumps(資料, ensure_ascii=False))
        return lt.問話題("舊主題", ["[00:00] 舊行"], ["[01:00] 新行甲", "[01:30] 新行乙"], 聊天們=["[00:50] a: b"], 要分鐘=True)
    return 呼叫


def test_分鐘摘要_支線_簡述都轉繁體(問):
    _, _, 簡述, 支線們, 分鐘, _ = 問({
        "decision": "same", "topic": "聊天", "topic_brief": "实况主在聊烤鸡",
        "side_notes": [{"time": "01:30", "note": "感谢萨奇的订阅"}],
        "minute_summary": {"summary": "[01:00] 实况主说这次没有烤鸡。", "audience": "聊天室说想吃烤鸡"}})
    assert 簡述 == "實況主在聊烤雞"
    assert 支線們 == [(90, "感謝薩奇的訂閱")]
    assert 分鐘 == ("[01:00] 實況主說這次沒有烤雞。", "聊天室說想吃烤雞")


def test_外語直播_分鐘摘要括號裡的日文不轉(問):
    _, _, _, _, 分鐘, _ = 問({"decision": "same", "minute_summary": {
        "summary": "[01:00] 實況主提到國木田（国木田）。", "audience": ""}}, 外語=True)
    assert 分鐘[0] == "[01:00] 實況主提到國木田（国木田）。"


def test_話題摘要轉繁體_名詞照原樣給詞庫(monkeypatch, tmp_path):
    事件們, 給詞庫 = [], []
    詞庫 = 詞庫有(monkeypatch, tmp_path)
    monkeypatch.setattr(詞庫, "自動加入", lambda 名詞們, 原稿=None: (給詞庫.extend(名詞們), [])[1])
    monkeypatch.setattr(summarize, "語言說明", "")
    monkeypatch.setattr(summarize, "call_llm", lambda 提示詞: (
        "<摘要輸出>\n【話題標題】实况主聊烤鸡\n【時間範圍】00:00 - 01:00\n【摘要】萨奇说想吃烤鸡。\n"
        "【重點】\n- [00:30] 萨奇说想吃\n【支線】無\n【名詞】萨奇\n</摘要輸出>"))
    monkeypatch.setattr(lt.events, "送出", lambda 種類, **k: 事件們.append((種類, k)))
    monkeypatch.setitem(lt.存檔, "摘要", False)
    話題 = lt.新話題()
    lt.加入(話題, [(0, "[00:00] 萨奇说想吃烤鸡"), (60, "[01:00] 好")])
    lt.輸出話題摘要(話題, 60, "不會寫入.md", 詞庫=詞庫)
    內文 = next(k["內文"] for 種類, k in 事件們 if 種類 == "topic_summary")
    assert "【話題標題】實況主聊烤雞" in 內文 and "薩奇說想吃烤雞" in 內文 and "- [00:30] 薩奇說想吃" in 內文
    assert not any(tr.是簡體字(c) for c in 內文)
    assert 給詞庫 == [("萨奇", "")]          # 詞庫要拿原樣和語音稿比對，不轉


def test_逐句翻譯與聊天室翻譯的譯文轉繁體_括號裡的日文不轉():
    回答 = json.dumps(["这个很好吃", "國木田（国木田）说早安", "謝謝大家"], ensure_ascii=False)
    assert subtitle.讀譯文(回答) == ["這個很好吃", "國木田（国木田）說早安", "謝謝大家"]


def test_譯文裡的詞庫寫法不轉(monkeypatch, tmp_path):
    詞庫有(monkeypatch, tmp_path, ("小鸟", "ことり", "手動"))
    assert subtitle.讀譯文('["小鸟说早安"]') == ["小鸟說早安"]
