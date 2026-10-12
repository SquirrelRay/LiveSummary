# 直播時鐘（stream_clock）與源頭換算：公式、漂移校正、聊天對齊、抓不到開播時間的退回、模型漏小時的補救。
# 全部用假時鐘、假音訊、假模型、假查詢結果；不連網、不花 API。
import io
import json

import numpy as np
import pytest

import chat_capture as cc
import events
import live_capture as lc
import live_topics as lt
import llm
import stream_clock as sc
import summarize
import timefmt


class 假鐘:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def 事件們(monkeypatch):
    收到 = []
    monkeypatch.setattr(events, "接收者們", [lambda 種類, 內容: 收到.append((種類, 內容))])
    events.停止.clear()
    yield 收到
    events.停止.clear()


@pytest.fixture(autouse=True)
def 不留時軸(monkeypatch):
    """每個測試結束都清掉這一場的時軸，不影響其他測試。"""
    monkeypatch.setattr(sc, "_目前", None)
    monkeypatch.setattr(sc, "_資訊", None)


# ---------- 換算公式 ----------
def test_每句話的直播時間公式():
    鐘 = 假鐘(5000.0)
    軸 = sc.時軸(開播=1000.0, 時鐘=鐘, 延遲=11.0)
    軸.開始()                                   # 收到第一個位元組：5000 − 1000 − 11 = 第 3989 秒
    assert 軸.偏移 == 3989.0
    assert 軸.音訊秒轉直播秒(12.5) == 4001.5        # 第一段音訊秒數 12.5 → 1:06:41.5
    assert 軸.標記(軸.音訊秒轉直播秒(12.5)) == "[1:06:41]"
    鐘.t = 5060.0
    assert 軸.現在直播秒() == 4049.0


def test_假流程_每句話用直播時間(流程, monkeypatch):
    """conftest 的假音訊流程，換成「一小時前開播、延遲 11 秒」的時軸：每句都是 h:mm:ss 的直播時間。"""
    原時軸 = sc.時軸
    monkeypatch.setattr(sc, "時軸", lambda 開播=None, 時鐘=None, 延遲=0.0: 原時軸(開播=-3600.0, 時鐘=時鐘, 延遲=11.0))
    次 = {"n": 0}
    monkeypatch.setattr(lc, "轉錄一段", lambda model, 音訊, 語言: (次.update(n=次["n"] + 1), [(0.5, f"第{次['n']}句")])[1])
    人聲 = np.full(4, 8000, dtype=np.int16).tobytes()
    _, _, s = 流程([人聲, 人聲, 人聲], 語言="ja")
    # 第一個位元組在時刻 0：偏移 = 0 − (−3600) − 11 = 3589；每段 lc.段秒數 秒、段內 0.5 秒
    預期 = [3589 + i * lc.段秒數 + 0.5 for i in range(3)]
    assert [秒 for 秒, _ in s.吐出] == 預期
    assert [行 for _, 行 in s.吐出] == [f"{timefmt.標記(秒)} 第{i + 1}句" for i, 秒 in enumerate(預期)]
    assert s.吐出[-1][1].startswith("[1:00:")


# ---------- 漂移校正 ----------
def 收段(軸, 段號, 時刻, 段秒=12):
    return 軸.段收滿((段號 + 1) * 段秒, 時刻)


def test_漂移校正_掉段後往前補_只往前不倒退():
    軸 = sc.時軸(開播=0.0, 時鐘=假鐘(100.0), 延遲=0.0)
    軸.開始(100.0)
    # 一開始串流一次送出 6 秒（第一段 12 秒在第 106 秒收滿），之後照真實時間每 12 秒一段
    assert 收段(軸, 0, 106.0) == 0          # 第一段：記下基線
    assert 收段(軸, 1, 118.0) == 0
    # 廣告被濾掉 60 秒：之後每段都晚 60 秒收滿
    assert 收段(軸, 2, 190.0) == 0          # 第一次超過門檻：先不補（可能只是一時卡住）
    assert 收段(軸, 3, 202.0) == 60.0       # 連續兩段都超過：往前補 60 秒
    assert 軸.補償 == 60.0
    assert 收段(軸, 4, 214.0) == 0          # 補完回到正常
    # 一時卡住又追回（之後一次收到好幾段）：比基線早 → 不倒退
    assert 收段(軸, 5, 220.0) == 0 and 收段(軸, 6, 221.0) == 0
    assert 軸.補償 == 60.0
    assert 軸.音訊秒轉直播秒(84) == 100.0 + 60 + 84


def test_漂移校正_一時卡住後追回不補():
    軸 = sc.時軸(開播=0.0, 時鐘=假鐘(), 延遲=0.0)
    軸.開始(0.0)
    收段(軸, 0, 6.0)
    assert 收段(軸, 1, 30.0) == 0           # 卡了 12 秒
    assert 收段(軸, 2, 31.0) == 0           # 下一段馬上補回來：不算掉段
    assert 軸.補償 == 0


def test_假流程_模擬掉段_後面的句子往前補_時間不倒退(流程, monkeypatch):
    """第 2 段轉錄時串流停了 60 秒（例如廣告被濾掉）：第 4 段起的句子時間往前補 60 秒，前面的不變、整體不倒退。"""
    段秒 = lc.段秒數
    次 = {"n": 0}
    鐘們 = []
    原時軸 = sc.時軸

    def 做時軸(開播=None, 時鐘=None, 延遲=0.0):
        鐘們.append(時鐘)
        return 原時軸(開播=開播, 時鐘=時鐘, 延遲=延遲)
    monkeypatch.setattr(sc, "時軸", 做時軸)

    def 轉錄(model, 音訊, 語言):
        次["n"] += 1
        if 次["n"] == 2:
            鐘們[0].t += 60        # 第 2 段處理時，串流停了 60 秒才送下一段
        return [(0.5, f"第{次['n']}段")]
    monkeypatch.setattr(lc, "轉錄一段", 轉錄)
    人聲 = np.full(4, 8000, dtype=np.int16).tobytes()
    _, _, s = 流程([人聲] * 6, 語言="ja")
    秒們 = [秒 for 秒, _ in s.吐出]
    assert 秒們[:3] == [i * 段秒 + 0.5 for i in range(3)]               # 掉段前、第一次超過門檻：不補
    assert 秒們[3:] == [i * 段秒 + 0.5 + 60 for i in range(3, 6)]        # 連續兩段落後：往前補 60 秒
    assert 秒們 == sorted(秒們)                                         # 不倒退


# ---------- 聊天室對齊 ----------
def test_同一時刻的直播稿與聊天留言時間一致(事件們):
    鐘 = 假鐘(5000.0)
    軸 = sc.時軸(開播=1000.0, 時鐘=鐘, 延遲=11.0)
    軸.開始()
    c = cc.聊天室("chan", None)
    c._起點, c._時軸 = 鐘(), 軸          # 等同 live_capture 呼叫 聊天.開始(時刻, 軸)
    # 音訊第 30 秒的內容在時刻 5030 收到；和我們延遲相同的觀眾也在這時看到、打字
    鐘.t = 5030.0
    檔 = io.StringIO()
    c._處理("alice", "好耶", 檔)
    稿秒 = 軸.音訊秒轉直播秒(30)
    留言秒 = c.訊息們[0][0]
    assert 留言秒 == 稿秒 == 4019.0
    assert 檔.getvalue() == f"{軸.標記(稿秒)} alice: 好耶\n" == "[1:06:59] alice: 好耶\n"
    assert 事件們[-1][1]["時間字"] == 軸.字(稿秒)


def test_沒有時軸時聊天室照舊從起點算():
    c = cc.聊天室("chan", None)
    c._起點 = 0.0
    秒, 字 = c._秒與字()
    assert 秒 > 1e9 and ":" in 字           # 舊的用法（測試直接設 _起點）仍可運作


# ---------- 抓不到開播時間：退回「從開始擷取起算」，時間加 + ----------
def test_退回_直播稿與聊天都從第一個位元組起算並加加號(事件們):
    鐘 = 假鐘(5000.0)
    軸 = sc.時軸(開播=None, 時鐘=鐘)
    assert 軸.加號 and not 軸.有開播
    c = cc.聊天室("chan", None)
    c._起點, c._時軸 = 鐘(), 軸
    c._處理("early", "還沒有音訊", io.StringIO())
    assert c.訊息們[0][0] == 0.0              # 第一個位元組之前的留言當 0
    軸.開始()
    鐘.t = 5754.0
    檔 = io.StringIO()
    c._處理("bob", "hi", 檔)
    assert 軸.音訊秒轉直播秒(754) == 754.0 == c.訊息們[-1][0]
    assert 檔.getvalue() == "[+12:34] bob: hi\n"
    assert 事件們[-1][1]["時間字"] == "+12:34"


def test_退回_事件與摘要存檔都帶加號(事件們, monkeypatch, tmp_path):
    sc.設定目前(sc.時軸(開播=None), None)
    monkeypatch.setattr(lt, "存檔", {"摘要": True})
    monkeypatch.setattr(lt, "統計", {"分鐘摘要": 0, "JSON失敗": 0})
    分鐘檔 = tmp_path / "分鐘.md"
    lt.輸出分鐘摘要(("在聊遊戲", ""), [(75, "支線")], 754, False, str(分鐘檔))
    內容 = 分鐘檔.read_text(encoding="utf-8")
    assert 內容.startswith("# 抓不到開播時間")
    assert "[+12:34] 在聊遊戲" in 內容 and "[+01:15] 支線" in 內容
    assert 事件們[-1][1]["摘要"] == "[+12:34] 在聊遊戲"
    assert lt.秒轉字(3725) == "+1:02:05"


def test_有開播時間_存檔開頭有直播資訊():
    sc.設定目前(sc.時軸(開播=1791797908.0), {"直播主": "たいじ", "標題": "ラーメン", "遊戲": "Ramen Sim"})
    頭 = sc.檔頭()
    assert "# 直播主：たいじ" in 頭 and "# 標題：ラーメン" in 頭 and "# 分類：Ramen Sim" in 頭
    assert "# 開播：2026-10-12" in 頭 and "直播實際進行時間" in 頭
    assert not sc.加號() and lt.秒轉字(3725) == "1:02:05"


def test_文字稿模式沒有檔頭也沒有加號():
    assert sc.檔頭() == "" and not sc.加號()


def test_重讀存檔會略過檔頭(tmp_path):
    稿 = tmp_path / "稿.txt"
    稿.write_text("# 直播主：x\n# 開播：…\n\n[1:00:00] 第一句\n[1:00:05] 第二句\n", encoding="utf-8")
    assert list(lt.stream_lines(str(稿))) == [(3600, "[1:00:00] 第一句"), (3605, "[1:00:05] 第二句")]


# ---------- 開播時間查詢結果 → 這一場的時軸與事件 ----------
class 假查詢:
    def __init__(self, 結果):
        self.結果 = 結果

    def 等(self):
        return self.結果


def test_取得時軸_有開播時間(事件們):
    軸 = lc.取得時軸(假查詢({"開播": 1000.0, "標題": "t", "遊戲": "g", "直播主": "n", "來源": "GQL"}))
    assert 軸.有開播 and 軸.延遲 == sc.延遲秒 and sc.目前() is 軸
    內容 = next(c for k, c in 事件們 if k == "stream_info")
    assert 內容["有開播"] and (內容["直播主"], 內容["標題"], 內容["遊戲"], 內容["來源"]) == ("n", "t", "g", "GQL")
    assert 內容["印出"] is None


def test_取得時軸_抓不到就退回並提示(事件們):
    軸 = lc.取得時軸(假查詢(None))
    assert 軸.加號 and sc.加號()
    內容 = next(c for k, c in 事件們 if k == "stream_info")
    assert not 內容["有開播"] and "抓不到開播時間" in 內容["印出"]


def test_取得時軸_按結束就取消啟動(事件們):
    events.停止.set()
    with pytest.raises(lc.直播錯誤):
        lc.取得時軸(假查詢(None))


# ---------- 模型漏了小時：補回 ----------
@pytest.fixture
def 引擎環境(monkeypatch, 事件們):
    monkeypatch.setattr(lt, "統計", {"分鐘摘要": 0, "JSON失敗": 0})
    monkeypatch.setattr(lt, "存檔", {"摘要": False})
    monkeypatch.setattr(llm, "摘要_思考", True)
    回覆們, 摘要們 = [], []
    monkeypatch.setattr(summarize, "call_llm", lambda 提示: json.dumps(回覆們.pop(0) if 回覆們 else {"decision": "same"}))

    def 假摘要(文字, 類型=None, 聊天室紀錄=None, 格式=None):
        摘要們.append(文字)
        return "【重點】\n- [23:30] 對不上的時間\n- [23:00] 漏了小時\n- [1:24:00] 正常的重點\n- [84:30] 舊格式"
    monkeypatch.setattr(summarize, "summarize_chunk", 假摘要)
    return 回覆們, 摘要們, 事件們


def 直播行(秒們):
    """直播秒是小數（例如 4980.5），行首只到整秒，和 live_capture 吐出的一樣。"""
    return [(s + 0.5, f"{timefmt.標記(s)} 第{s}秒" + "字" * 110) for s in 秒們]


def test_切點漏了小時也能切_小數秒也對得上(引擎環境):
    回覆們, 摘要們, _ = 引擎環境
    秒們 = range(4800, 5401, 60)                  # 1:20:00 ~ 1:30:00
    回覆們[:] = [{"decision": "same"}] * 4 + [{"decision": "new_topic", "new_topic_start": "25:00",   # 1:25:00 漏了小時
                                              "side_notes": [{"time": "1:25:00", "note": "切點那一秒的支線"}]}]
    assert lt.引擎(iter(直播行(秒們)), 1, "x") == 2
    assert "第5040秒" in 摘要們[0] and "第5100秒" not in 摘要們[0]
    assert "第5100秒" in 摘要們[1]
    assert "切點那一秒的支線" in 摘要們[1] and "切點那一秒的支線" not in 摘要們[0]    # 切點那一秒的支線歸新話題


def test_話題摘要內文的時間補回小時並統一格式(引擎環境):
    _, _, 事件們 = 引擎環境
    lt.引擎(iter(直播行(range(4800, 5101, 60))), 1, "x")       # 4800 = 1:20:00, 5040 = 1:24:00
    主題 = next(c for k, c in 事件們 if k == "topic_summary")
    內文 = 主題["內文"]
    assert "[23:30] 對不上的時間" in 內文     # 補一小時是 1:23:30，這一段沒有這個時間 → 原樣
    assert "[1:23:00] 漏了小時" in 內文      # 1:23:00 這一段真的有 → 補回小時
    assert "[1:24:00] 正常的重點" in 內文
    assert "[1:24:30] 舊格式" in 內文         # [84:30] → 統一成 h:mm:ss
    assert 主題["開始"] == "1:20:00" and 主題["開始秒"] == 4800.5


def test_支線與分鐘摘要漏了小時也補回(monkeypatch):
    monkeypatch.setattr(lt, "統計", {"分鐘摘要": 0, "JSON失敗": 0})
    monkeypatch.setattr(llm, "摘要_思考", True)
    回答 = {"decision": "same", "side_notes": [{"time": "23:45", "note": "漏小時的支線"}],
          "minute_summary": {"summary": "[23:45] 漏小時的摘要", "audience": ""}}
    monkeypatch.setattr(summarize, "call_llm", lambda 提示: json.dumps(回答, ensure_ascii=False))
    _, _, _, 支線們, 分鐘 = lt.問話題("", [], ["[1:23:45] 甲", "[1:24:00] 乙"], 要分鐘=True)
    assert 支線們 == [(5025, "漏小時的支線")]
    assert 分鐘[0] == "[1:23:45] 漏小時的摘要"


def test_提示詞要求照原樣抄時間戳(monkeypatch):
    monkeypatch.setattr(lt, "統計", {"分鐘摘要": 0, "JSON失敗": 0})
    提示們 = []
    monkeypatch.setattr(summarize, "call_llm", lambda 提示: 提示們.append(提示) or '{"decision": "same"}')
    lt.問話題("", [], ["[1:23:45] 甲"], 要分鐘=True)
    assert "不可省略小時" in 提示們[0] and "mm:ss" not in 提示們[0]
    assert "不可省略小時" in lt.話題格式 and "[mm:ss]" not in lt.話題格式
