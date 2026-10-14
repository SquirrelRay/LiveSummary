"""摘要輸出不能混進模型的自言自語：話題摘要只取 <摘要輸出> 標記裡的內容；分鐘摘要、支線只取 JSON。
全部用假的模型回覆，不呼叫真 API。"""
import json
import os

import pytest

import app_paths
import live_topics as lt
import llm
import summarize

正式 = ("【話題標題】男子闖入老虎園區遭攻擊身亡\n【時間範圍】1:40:23 - 1:41:57\n【摘要】議會已展開健康與安全調查。\n"
      "【重點】\n- [1:41:05] 議會展開調查\n【支線】無")
自言自語 = "Wait, I must follow format strictly and avoid stray English. Let me write properly."


def 包(內容):
    return f"{lt.正式開頭}\n{內容}\n{lt.正式結尾}"


# ---------- 取正式內容 ----------
def test_正常回應_只有標記():
    assert lt.取正式內容(包(正式)) == (正式, "標記")


def test_標記前後夾了自言自語():
    回答 = "Let me think about the topic first.\n" + 包(正式) + "\n" + 自言自語 + "\n好，這樣應該可以了。"
    內文, 來源 = lt.取正式內容(回答)
    assert 內文 == 正式 and 來源 == "標記"
    assert "Wait" not in 內文 and "Let me" not in 內文 and "應該可以" not in 內文


def test_有好幾組標記用最後一組_前面是草稿():
    草稿 = 正式.replace("男子闖入老虎園區遭攻擊身亡", "一名男子翻越圍欄進入（Doncaster）老虎園區遭攻擊身亡、議會調查")
    回答 = 包(草稿) + "\n" + 自言自語 + "\n" + 包(正式)
    assert lt.取正式內容(回答) == (正式, "標記")


def test_找不到標記_上次SkyNews的回答_從最後一個話題標題開始():
    """修改前實際發生的情形：先寫一行草稿標題，接一句英文自言自語，再重寫正式內容，沒有標記。"""
    回答 = "【話題標題】一名男子在唐卡斯特（Doncaster）野生動物園翻越圍欄進入老虎園區。\n\n" + 自言自語 + "\n\n" + 正式
    內文, 來源 = lt.取正式內容(回答)
    assert 來源 == "格式" and 內文 == 正式
    assert "Wait" not in 內文 and 內文.count("【話題標題】") == 1


def test_找不到標記_正式內容後面的自言自語也丟掉():
    回答 = 正式 + "\n\nHmm, I think that covers everything. Double-check timestamps: ok."
    內文, 來源 = lt.取正式內容(回答)
    assert 來源 == "格式" and 內文 == 正式


def test_有開頭沒結尾_被截斷時只看開頭之後():
    回答 = "草稿想法 blah\n" + lt.正式開頭 + "\n" + 正式[:正式.index("【重點】")]
    內文, 來源 = lt.取正式內容(回答)
    assert 來源 == "格式"
    assert 內文.startswith("【話題標題】") and "草稿想法" not in 內文 and "【摘要】" in 內文


def test_連格式都沒有_回傳空字串不把原文帶出來():
    assert lt.取正式內容("Wait, I need to re-read the transcript before answering.") == ("", "無")


@pytest.mark.parametrize("回答", ["", None, "   \n  ", 包("   ")])
def test_空回應(回答):
    assert lt.取正式內容(回答) == ("", "無")


def test_條列與名詞行都保留():
    內容 = 正式 + "\n【名詞】唐卡斯特（Doncaster）"
    assert lt.取正式內容("先想一下。\n" + 內容)[0] == 內容


# ---------- 輸出話題摘要（整條流程） ----------
@pytest.fixture
def 跑摘要(monkeypatch, tmp_path):
    def 跑(回答):
        事件們 = []
        monkeypatch.setattr(summarize, "call_llm", lambda 提示詞: (事件們.append(("提示", 提示詞)), 回答)[1])
        monkeypatch.setattr(lt.events, "送出", lambda 種類, **k: 事件們.append((種類, k)))
        monkeypatch.setitem(lt.存檔, "摘要", True)
        if os.path.exists(app_paths.摘要格式紀錄檔()):
            os.remove(app_paths.摘要格式紀錄檔())
        話題 = lt.新話題()
        lt.加入(話題, [(6023, "[1:40:23] But with a lot of these people"), (6117, "[1:41:57] incident")])
        檔 = str(tmp_path / "話題摘要.md")
        lt.輸出話題摘要(話題, 6117, 檔)
        內文 = next(k["內文"] for 種類, k in 事件們 if 種類 == "topic_summary")
        with open(檔, encoding="utf-8") as f:
            存檔 = f.read()
        提示 = next(k for 種類, k in 事件們 if 種類 == "提示")
        return 內文, 存檔, 提示
    return 跑


def 紀錄():
    if not os.path.exists(app_paths.摘要格式紀錄檔()):
        return ""
    with open(app_paths.摘要格式紀錄檔(), encoding="utf-8") as f:
        return f.read()


def test_提示詞要求把正式內容放在標記裡(跑摘要):
    _, _, 提示 = 跑摘要(包(正式))
    assert lt.正式開頭 in 提示 and lt.正式結尾 in 提示 and "標記外面不要寫任何文字" in 提示


def test_流程_正常回應_顯示與存檔都沒有標記_不寫紀錄(跑摘要):
    內文, 存檔, _ = 跑摘要(包(正式))
    assert 內文 == 正式
    assert 正式 in 存檔 and lt.正式開頭 not in 存檔
    assert 紀錄() == ""


def test_流程_夾了自言自語_顯示與存檔都沒有(跑摘要):
    內文, 存檔, _ = 跑摘要(自言自語 + "\n" + 包(正式) + "\nDone.")
    assert "Wait" not in 內文 and "Wait" not in 存檔 and "Done" not in 存檔
    assert 內文 == 正式


def test_流程_找不到標記_用格式救回並記下原始回覆(跑摘要):
    原始 = "【話題標題】草稿\n" + 自言自語 + "\n" + 正式
    內文, 存檔, _ = 跑摘要(原始)
    assert 內文 == 正式 and "Wait" not in 存檔
    assert "處理方式=格式" in 紀錄() and 自言自語 in 紀錄()


@pytest.mark.parametrize("原始", ["", 自言自語])
def test_流程_空回應或全是自言自語_顯示說明不顯示原文(跑摘要, 原始):
    內文, 存檔, _ = 跑摘要(原始)
    assert "【時間範圍】1:40:23 - 1:41:57" in 內文
    assert "沒有照格式回覆" in 內文
    assert "Wait" not in 內文 and "Wait" not in 存檔
    assert "處理方式=無" in 紀錄()


def test_流程_標記裡的名詞行照樣拆掉(跑摘要, monkeypatch):
    內文, _, _ = 跑摘要(包(正式 + "\n【名詞】唐卡斯特（Doncaster）"))
    assert "【名詞】" not in 內文 and 內文 == 正式


# ---------- 分鐘摘要、支線：只取 JSON，外面的文字不用 ----------
@pytest.fixture
def 問(monkeypatch):
    monkeypatch.setattr(lt, "統計", {"分鐘摘要": 0, "JSON失敗": 0})

    def 呼叫(回答, 思考=False):
        monkeypatch.setattr(llm, "摘要_思考", 思考)
        monkeypatch.setattr(summarize, "call_llm", lambda 提示詞: 回答)
        return lt.問話題("舊主題", ["[00:00] 舊行"], ["[01:00] 新行甲", "[01:30] 新行乙"], 要分鐘=True)
    return 呼叫


資料 = {"decision": "same", "topic": "聊遊戲", "topic_brief": "在聊遊戲",
      "side_notes": [{"time": "01:30", "note": "提到晚餐"}],
      "minute_summary": {"summary": "[01:00] 實況主在聊遊戲。", "audience": ""}}


@pytest.mark.parametrize("思考", [False, True])
def test_分鐘摘要_JSON前後夾了自言自語(問, 思考):
    回答 = "Wait, let me re-check the format.\n" + json.dumps(資料, ensure_ascii=False) + "\nOK that should be fine."
    決定, _, _, 支線們, 分鐘, _ = 問(回答, 思考)
    assert 決定 == "same"
    assert 分鐘 == ("[01:00] 實況主在聊遊戲。", "")
    assert 支線們 == [(90, "提到晚餐")]


@pytest.mark.parametrize("思考", [False, True])
def test_分鐘摘要_先寫草稿JSON再重寫_用最後一個(問, 思考):
    草稿 = dict(資料, minute_summary={"summary": "[01:00] draft summary", "audience": ""})
    回答 = json.dumps(草稿, ensure_ascii=False) + "\nWait, it must be Chinese.\n" + json.dumps(資料, ensure_ascii=False)
    _, _, _, _, 分鐘, _ = 問(回答, 思考)
    assert 分鐘 == ("[01:00] 實況主在聊遊戲。", "")
    assert lt.統計["JSON失敗"] == 0


@pytest.mark.parametrize("回答", ["", "Wait, I am not sure what to write."])
def test_分鐘摘要_空回應或沒有JSON_這一輪略過不顯示原文(問, 回答):
    決定, _, _, 支線們, 分鐘, _ = 問(回答)
    assert (決定, 支線們, 分鐘) == ("same", [], None)
    assert lt.統計["JSON失敗"] == 1
