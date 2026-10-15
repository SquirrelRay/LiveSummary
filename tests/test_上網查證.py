"""上網查證詞庫的候選名詞（web_verify.py、glossary 的寫回、llm.上網搜尋、live_topics 的串接、設定與費用表）。
假模型、假搜尋結果、詞庫放 tmp_path；不呼叫真 API、不連網。"""
import json
import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import anthropic
import pytest

import config
import cost_estimate as ce
import events
import glossary
import live_topics as lt
import llm
import summarize
import web_verify as wv

網址 = "https://zh.wikipedia.org/zh-tw/閃電十一人"


@pytest.fixture(autouse=True)
def 乾淨(monkeypatch, tmp_path):
    monkeypatch.setattr(glossary, "資料夾", str(tmp_path / "詞庫"))
    monkeypatch.setattr(llm, "PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "BASE_URL", "")
    monkeypatch.setattr(llm, "API_KEY_ENV", "TEST_FAKE_KEY")
    monkeypatch.setattr(llm, "摘要_思考", True)
    monkeypatch.setenv("TEST_FAKE_KEY", "sk-fake")
    monkeypatch.setattr(llm, "用量", {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0})
    monkeypatch.setattr(llm, "查證用量", {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0, "搜尋": 0})
    monkeypatch.setattr(events, "接收者們", [])
    events.停止.clear()
    return tmp_path / "詞庫"


def 寫詞庫(資料夾, 文字, 名="某主"):
    os.makedirs(資料夾, exist_ok=True)
    路徑 = os.path.join(資料夾, 名 + ".txt")
    with open(路徑, "w", encoding="utf-8") as f:
        f.write(文字)
    return 路徑


def 讀(路徑):
    with open(路徑, encoding="utf-8") as f:
        return f.read()


def 回覆(結果, 網址們=(網址,), 成功=1, 錯誤=()):
    """llm.上網搜尋() 的假回覆。"""
    return {"文字": "查了一下。\n" + json.dumps(結果, ensure_ascii=False), "網址們": set(網址們),
            "搜尋成功": 成功, "搜尋錯誤": list(錯誤), "搜尋次數": 成功 + len(錯誤)}


找到 = {"result": "found", "written": "閃電十一人", "url": 網址, "original": "イナズマイレブン"}
查無 = {"result": "none", "reason": "找不到可靠來源"}


class 假搜尋:
    """取代 llm.上網搜尋：依名詞原文回覆（dict 或例外），記下問過哪些。"""

    def __init__(self, monkeypatch, 回覆們=None, 預設=None):
        self.問過 = []
        self.回覆們 = 回覆們 or {}
        self.預設 = 預設 if 預設 is not None else 回覆(查無)
        monkeypatch.setattr(llm, "上網搜尋", self)

    def __call__(self, 提示詞, 模型, 最多搜尋=3):
        原文 = 提示詞.split("名詞原文：", 1)[1].split("\n", 1)[0]
        self.問過.append(原文)
        r = self.回覆們.get(原文, self.預設)
        if isinstance(r, BaseException):
            raise r
        llm.查證用量["次數"] += 1
        llm.查證用量["搜尋"] += r["搜尋成功"]
        return r


# ---------- 詞庫格式：舊檔照常讀、第 4 欄 ----------
def test_舊格式三欄照常讀_新格式第四欄(乾淨):
    路徑 = 寫詞庫(乾淨, "# 說明\n艾倫｜エレン｜手動\n稻妻11｜稻妻イレブン｜自動\n台北\n"
                    "閃電十一人｜稻妻イレブン2｜上網｜https://a.example/x\n桃鉄｜桃太郎電鉄｜候選｜已查\n"
                    "壞｜的｜行｜有｜五欄\n")
    庫 = glossary.詞庫("某主")
    assert [(e.寫法, e.來源) for e in 庫.條目們] == [("艾倫", "手動"), ("稻妻11", "候選"), ("台北", "手動"),
                                                ("閃電十一人", "上網"), ("桃鉄", "候選")]
    assert 庫.格式錯 == 1
    assert 庫.條目們[3].網址() == "https://a.example/x"
    assert [e.寫法 for e in 庫.待查證們()] == ["稻妻11"]           # 上網、已查、手動都不查
    assert "閃電十一人（稻妻イレブン2）" in 庫.提示段()              # 上網的和手動一樣提供給摘要
    assert 讀(路徑).endswith("壞｜的｜行｜有｜五欄\n")


def test_存檔行_網址裡的分隔字元會編碼():
    e = glossary.條目("甲", "乙", "上網", "https://a.example/?q=1|2")
    assert e.存檔行() == "甲｜乙｜上網｜https://a.example/?q=1%7C2"
    assert glossary.解析行(e.存檔行()).網址() == "https://a.example/?q=1%7C2"
    assert glossary.條目("甲", "乙", "候選").存檔行() == "甲｜乙｜候選"          # 沒有備註就是原本的三欄


# ---------- 寫回：查到、查無、手動不動 ----------
def test_查到寫成上網並附網址_其他行原樣保留(乾淨):
    原本 = "# 說明\n艾倫｜エレン｜手動\n稻妻11｜稻妻イレブン｜自動\n格式｜不｜對｜的｜行\n"
    路徑 = 寫詞庫(乾淨, 原本)
    庫 = glossary.詞庫("某主")
    e = 庫.待查證們()[0]
    狀態, 字 = wv.寫回(庫, e, wv.判讀(回覆(找到)))
    assert 狀態 == "確認" and 網址 in 字
    assert 讀(路徑) == ("# 說明\n艾倫｜エレン｜手動\n"
                     f"閃電十一人｜稻妻イレブン｜上網｜{網址} 正式原文：イナズマイレブン\n格式｜不｜對｜的｜行\n")
    assert "閃電十一人（稻妻イレブン）" in 庫.提示段()                # 當場就用得到
    assert "閃電十一人（稻妻イレブン）" in glossary.詞庫("某主").提示段()   # 下一場也會用


def test_查無保持候選標已查_之後不再查(乾淨, monkeypatch):
    路徑 = 寫詞庫(乾淨, "桃鉄｜桃太郎電鉄｜候選\n")
    搜 = 假搜尋(monkeypatch, 預設=回覆(查無))
    計數 = 跑小工具(乾淨)
    assert 計數["查無"] == 1 and 搜.問過 == ["桃太郎電鉄"]
    assert 讀(路徑) == "桃鉄｜桃太郎電鉄｜候選｜已查\n"
    assert 跑小工具(乾淨)["查"] == 0 and 搜.問過 == ["桃太郎電鉄"]     # 第二次不再查、不花錢
    assert "桃鉄" not in glossary.詞庫("某主").提示段()                 # 仍是候選：下一場不提供給摘要


def test_手動詞條永遠不被改動(乾淨, monkeypatch):
    原本 = "艾倫｜エレン｜手動\n艾連｜エレン｜候選\n米卡莎｜ミカサ\n"
    路徑 = 寫詞庫(乾淨, 原本)
    庫 = glossary.詞庫("某主")
    assert 庫.套用查證("エレン", "艾連", 網址) == 0                 # 同一個名詞有手動：候選那行也不動
    assert 庫.套用查證("ミカサ", "米卡沙", 網址) == 0
    assert 庫.套用查證("ミカサ", None) == 0
    assert 讀(路徑) == 原本
    搜 = 假搜尋(monkeypatch, 預設=回覆(找到 | {"written": "艾連"}))
    跑小工具(乾淨)
    assert 讀(路徑) == 原本 and 搜.問過 == []                       # 有手動的名詞不會拿去查


def test_已經是上網的不再查(乾淨, monkeypatch):
    寫詞庫(乾淨, f"閃電十一人｜イナズマイレブン｜上網｜{網址}\n")
    搜 = 假搜尋(monkeypatch)
    assert 跑小工具(乾淨)["查"] == 0 and 搜.問過 == []


# ---------- 網址必須真的來自搜尋結果 ----------
def test_模型自己打的網址不在搜尋結果裡_一律查無():
    r = 回覆(找到 | {"url": "https://zh.wikipedia.org/wiki/編出來的"}, 網址們=["https://other.example/a"])
    assert wv.判讀(r)[0] == "查無"


def test_網址比對忽略結尾斜線與錨點_寫回用搜尋結果的原樣():
    r = 回覆(找到 | {"url": 網址 + "/#歷史"}, 網址們=[網址])
    assert wv.判讀(r)[:3] == ("確認", "閃電十一人", 網址)


@pytest.mark.parametrize("寫法", ["イナズマ11", "桃鉄", "", "閃電｜十一人", "長" * 40])
def test_寫法不合格當作查無(寫法):
    assert wv.判讀(回覆(找到 | {"written": 寫法}))[0] == "查無"


# ---------- 查證失敗（沒查成）和查無分開 ----------
@pytest.mark.parametrize("r", [
    回覆(找到, 成功=0, 錯誤=["too_many_requests"]),     # 搜尋全部出錯
    回覆(查無, 成功=0),                                 # 模型根本沒搜尋就說查無
    {"文字": "看不懂的回覆", "網址們": {網址}, "搜尋成功": 1, "搜尋錯誤": [], "搜尋次數": 1},
])
def test_沒有成功搜尋或回覆看不懂_算失敗(r):
    assert wv.判讀(r)[0] == "失敗"


@pytest.mark.parametrize("例外", [llm.查證失敗("APITimeoutError"), llm.查證失敗("RateLimitError"), RuntimeError("意外")])
def test_逾時錯誤速率限制_不標已查_下次還能查(乾淨, monkeypatch, 例外):
    原本 = "稻妻11｜稻妻イレブン｜候選\n"
    路徑 = 寫詞庫(乾淨, 原本)
    搜 = 假搜尋(monkeypatch, 預設=例外)
    計數 = 跑小工具(乾淨)
    assert 計數["失敗"] == 1 and 讀(路徑) == 原本
    搜.預設 = 回覆(找到)
    assert 跑小工具(乾淨)["確認"] == 1 and "上網" in 讀(路徑)          # 下次再查


# ---------- llm.上網搜尋：解析搜尋結果、引用、用量 ----------
class 假Anthropic:
    回應們 = 呼叫們 = 例外 = None          # 由 甲 fixture 填入

    def __init__(self, **kw):
        假Anthropic.建立參數 = kw
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        假Anthropic.呼叫們.append(kw)
        if 假Anthropic.例外:
            raise 假Anthropic.例外
        return 假Anthropic.回應們.pop(0)


def 搜尋回應(區塊們, 停止="end_turn", 搜尋=1):
    return SimpleNamespace(content=區塊們, stop_reason=停止, usage=SimpleNamespace(
        input_tokens=5000, output_tokens=200, server_tool_use=SimpleNamespace(web_search_requests=搜尋)))


def 結果區塊(*urls):
    return SimpleNamespace(type="web_search_tool_result", content=[SimpleNamespace(type="web_search_result", url=u)
                                                                   for u in urls])


@pytest.fixture
def 甲(monkeypatch):
    假Anthropic.回應們, 假Anthropic.呼叫們, 假Anthropic.例外 = [], [], None
    monkeypatch.setattr(anthropic, "Anthropic", 假Anthropic)
    return 假Anthropic


def test_上網搜尋_收集搜尋結果與引用網址_用量另外記(甲):
    引用 = SimpleNamespace(type="web_search_result_location", url="https://c.example/cite")
    甲.回應們 = [搜尋回應([
        SimpleNamespace(type="server_tool_use", name="web_search"),
        結果區塊("https://a.example/1", "https://b.example/2"),
        SimpleNamespace(type="server_tool_use", name="web_search"),
        SimpleNamespace(type="web_search_tool_result",
                        content=SimpleNamespace(type="web_search_tool_result_error", error_code="unavailable")),
        SimpleNamespace(type="text", text="答案", citations=[引用]),
    ], 搜尋=1)]
    r = llm.上網搜尋("問", "模型甲", 2)
    assert r["網址們"] == {"https://a.example/1", "https://b.example/2", "https://c.example/cite"}
    assert (r["搜尋成功"], r["搜尋錯誤"], r["搜尋次數"], r["文字"]) == (1, ["unavailable"], 2, "答案")
    assert llm.查證用量 == {"次數": 1, "輸入": 5000, "輸出": 200, "缺token": 0, "搜尋": 1}
    assert llm.用量["次數"] == 0                                   # 不混進摘要的用量
    p = 甲.呼叫們[0]
    assert p["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}]
    assert 甲.建立參數["timeout"] == llm.查證逾時秒


def test_上網搜尋_pause_turn_接著問(甲):
    甲.回應們 = [搜尋回應([結果區塊(網址)], 停止="pause_turn"),
               搜尋回應([SimpleNamespace(type="text", text="好了", citations=None)], 搜尋=0)]
    r = llm.上網搜尋("問", "m")
    assert len(甲.呼叫們) == 2 and 甲.呼叫們[1]["messages"][-1]["role"] == "assistant"
    assert r["網址們"] == {網址} and r["文字"] == "好了"


@pytest.mark.parametrize("例外類", [anthropic.APITimeoutError, anthropic.APIConnectionError, anthropic.RateLimitError,
                                  anthropic.InternalServerError])
def test_上網搜尋_逾時與API錯誤丟出查證失敗(甲, 例外類):
    甲.例外 = 例外類.__new__(例外類)
    with pytest.raises(llm.查證失敗):
        llm.上網搜尋("問", "m")


def test_上網搜尋_回答被截斷算失敗(甲):
    甲.回應們 = [搜尋回應([結果區塊(網址)], 停止="max_tokens")]
    with pytest.raises(llm.查證失敗):
        llm.上網搜尋("問", "m")


def test_openai相容不支援上網搜尋(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "openai_compatible")
    assert not llm.支援上網查證()
    with pytest.raises(llm.查證失敗):
        llm.上網搜尋("問", "m")


# ---------- 提示詞的脈絡 ----------
def test_提示詞附上原文寫法直播主分類與稿裡的句子():
    e = glossary.條目("稻妻11", "稻妻イレブン", "候選")
    行們 = ["[00:10] 今日は稻妻イレブンをやります", "[00:20] 関係ない話", "[01:00] 稻妻イレブン楽しい", "[02:00] 稻妻イレブン3回目"]
    p = wv.提示詞(e, {"直播主": "某主", "分類": "Inazuma Eleven", "標題": "初見"}, wv.句子們(e.原文, e.寫法, 行們))
    for 字 in ("名詞原文：稻妻イレブン", "稻妻11", "直播主：某主", "Inazuma Eleven", "直播標題：初見",
              "- 今日は稻妻イレブンをやります", "- 稻妻イレブン楽しい", "查無", "不可以自己翻譯"):
        assert 字 in p
    assert "3回目" not in p and "[00:10]" not in p


# ---------- 寫檔衝突：背景寫回與話題摘要同時寫 ----------
def test_兩邊同時寫入_內容都不會遺失(乾淨, monkeypatch):
    待查 = [f"候選{i}｜コウホ{i}｜候選" for i in range(15)]
    路徑 = 寫詞庫(乾淨, "艾倫｜エレン｜手動\n" + "\n".join(待查) + "\n")
    原寫入 = glossary.安全寫入

    def 慢寫入(p, 文字):          # 拉長「重讀→寫檔」之間的空檔，沒有鎖的話一定會互蓋
        time.sleep(0.005)
        原寫入(p, 文字)
    monkeypatch.setattr(glossary, "安全寫入", 慢寫入)
    主庫, 背景庫 = glossary.詞庫("某主"), glossary.詞庫("某主")    # 兩個物件（小工具和直播），同一個檔

    def 主():
        for i in range(15):
            主庫.自動加入([(f"新詞{i}", f"シンゴ{i}")])

    def 背景():
        for i in range(15):
            背景庫.套用查證(f"コウホ{i}".casefold(), f"確認{i}" if i % 2 else None, f"https://x.example/{i}")
    執行緒們 = [threading.Thread(target=主), threading.Thread(target=背景)]
    for t in 執行緒們:
        t.start()
    for t in 執行緒們:
        t.join()
    行們 = 讀(路徑).splitlines()
    assert "艾倫｜エレン｜手動" in 行們
    assert all(f"新詞{i}｜シンゴ{i}｜候選" in 行們 for i in range(15))
    assert all((f"確認{i}｜コウホ{i}｜上網｜https://x.example/{i}" if i % 2 else f"候選{i}｜コウホ{i}｜候選｜已查") in 行們
               for i in range(15))
    assert len(行們) == 31
    assert len(主庫.條目們) == 31 and len(背景庫.條目們) >= 16       # 記憶體裡的詞庫也是最新的


# ---------- 背景查證：上限、收尾 ----------
def test_每場上限生效_超過的保持未查(乾淨, monkeypatch):
    搜 = 假搜尋(monkeypatch, 預設=回覆(查無))
    路徑 = 寫詞庫(乾淨, "")
    庫 = glossary.詞庫("某主")
    新的 = 庫.自動加入([(f"詞{i}", f"ゴ{i}") for i in range(8)]) + 庫.自動加入([(f"詞{i}", f"ゴ{i}") for i in range(8, 13)])
    查 = wv.背景查證(庫, {}, "m")
    查.加入(新的[:8], [])
    查.加入(新的[8:], [])
    行 = 查.收尾(5)
    assert len(搜.問過) == wv.每場上限 == 10
    assert 行 == "上網查證：查 10 個，確認 0 個，查無 10 個，未完成 0 個（超過上限 10 個，另有 3 個沒查，保持未查）"
    assert sum(l.endswith("｜候選｜已查") for l in 讀(路徑).splitlines()) == 10


def test_小工具上限可用參數調整(乾淨, monkeypatch):
    寫詞庫(乾淨, "".join(f"詞{i}｜ゴ{i}｜候選\n" for i in range(5)))
    搜 = 假搜尋(monkeypatch)
    計數 = 跑小工具(乾淨, 上限=2)
    assert len(搜.問過) == 2 and 計數["略過"] == 3


def test_收尾逾時_沒查完的保持未查_晚回來的不寫回(乾淨, monkeypatch):
    放行 = threading.Event()
    開始了 = threading.Event()

    def 卡住(提示詞, 模型, 最多搜尋=3):
        開始了.set()
        放行.wait(5)
        return 回覆(找到)
    monkeypatch.setattr(llm, "上網搜尋", 卡住)
    路徑 = 寫詞庫(乾淨, "")
    庫 = glossary.詞庫("某主")
    新的 = 庫.自動加入([("稻妻11", "稻妻イレブン"), ("桃鉄電", "桃太郎電鉄")])
    原本 = 讀(路徑)
    查 = wv.背景查證(庫, {}, "m")
    查.加入(新的, [])
    assert 開始了.wait(5)
    t0 = time.monotonic()
    行 = 查.收尾(0.3)
    assert time.monotonic() - t0 < 2
    assert 行 == "上網查證：查 2 個，確認 0 個，查無 0 個，未完成 2 個"
    放行.set()
    time.sleep(0.2)
    assert 讀(路徑) == 原本                                      # 沒有標已查，也沒有寫成上網


def test_收尾中放棄_不再等背景查證(乾淨, monkeypatch):
    """按停止後收尾中使用者確定直接結束程式（events.放棄收尾）：收尾() 馬上回來，沒查完的保持未查。"""
    放行, 開始了 = threading.Event(), threading.Event()

    def 卡住(提示詞, 模型, 最多搜尋=3):
        開始了.set()
        放行.wait(40)
        return 回覆(找到)
    monkeypatch.setattr(llm, "上網搜尋", 卡住)
    寫詞庫(乾淨, "")
    庫 = glossary.詞庫("某主")
    查 = wv.背景查證(庫, {}, "m")
    查.加入(庫.自動加入([("稻妻11", "稻妻イレブン")]), [])
    assert 開始了.wait(5)
    放棄 = threading.Event()
    threading.Timer(0.2, 放棄.set).start()
    t0 = time.monotonic()
    行 = 查.收尾(30, 放棄=放棄)
    assert time.monotonic() - t0 < 1.5
    assert 行 == "上網查證：查 1 個，確認 0 個，查無 0 個，未完成 1 個"
    放行.set()


def test_收尾等待秒是30():
    assert wv.收尾等待秒 == 30 and wv.每場上限 == 10 and wv.每詞最多搜尋 == 2


def 跑小工具(資料夾, 上限=wv.每場上限):
    import importlib.util
    路徑 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "verify_glossary.py")
    規格 = importlib.util.spec_from_file_location("verify_glossary", 路徑)
    模組 = importlib.util.module_from_spec(規格)
    規格.loader.exec_module(模組)
    return 模組.跑("某主", [], {"直播主": "某主"}, "m", 上限, 印=lambda *a: None)


# ---------- 串接 live_topics.執行() ----------
摘要本體 = "【話題標題】聊遊戲\n【時間範圍】00:00 - 05:00\n【摘要】聊到閃電十一人。\n【重點】\n- [01:00] 重點\n【支線】無"


class 一場:
    def __init__(self, monkeypatch, tmp_path, 名詞="稻妻11（稻妻イレブン）"):
        self.事件們, self.判斷提示們 = [], []
        monkeypatch.setattr(events, "接收者們", [lambda 種類, 內容: self.事件們.append((種類, 內容))])
        monkeypatch.setattr(lt, "統計", {"分鐘摘要": 0, "JSON失敗": 0})
        monkeypatch.setattr(lt, "存檔", {"摘要": False})
        monkeypatch.setattr(lt, "單價", dict(lt.單價))
        for 名 in ("MIN_TOPIC_MIN", "MAX_TOPIC_MIN", "MINUTE_SENTENCES"):
            monkeypatch.setattr(lt, 名, getattr(lt, 名))
        monkeypatch.setattr(summarize, "MODEL", summarize.MODEL)
        monkeypatch.setattr(summarize, "語言說明", summarize.語言說明)
        monkeypatch.setattr(llm, "檢查金鑰", lambda *a: None)

        def 假模型(提示詞):
            self.判斷提示們.append(提示詞)
            return json.dumps({"decision": "same", "topic": "聊遊戲", "topic_brief": "簡述", "side_notes": []})
        monkeypatch.setattr(summarize, "call_llm", 假模型)
        monkeypatch.setattr(summarize, "summarize_chunk", lambda *a, **k: 摘要本體 + f"\n【名詞】{名詞}")
        self.稿 = tmp_path / "稿.txt"
        self.稿.write_text("\n".join(f"[{s // 60:02d}:00] 稻妻イレブンの話" + "字" * 110 for s in range(0, 301, 60)),
                          encoding="utf-8")

    def 跑(self, **改):
        設定 = config.出廠預設() | {"save_summary": False, "language": "ja"} | 改
        return lt.執行(設定, 檔案=str(self.稿), 直播主="某主")

    def 印出(self):
        return [c.get("印出") or "" for k, c in self.事件們 if k in ("info", "finished")]

    def 結束(self):
        return next(c["印出"] for k, c in self.事件們 if k == "finished")

    def 話題數(self):
        return sum(1 for k, _ in self.事件們 if k == "topic_summary")


def test_開關關閉時完全不查也不多花錢(乾淨, monkeypatch, tmp_path):
    搜 = 假搜尋(monkeypatch, 預設=回覆(找到))
    場 = 一場(monkeypatch, tmp_path)
    assert 場.跑() is True                                   # 出廠預設 web_verify = False
    assert 搜.問過 == [] and llm.查證用量["次數"] == 0 and llm.查證用量["搜尋"] == 0
    assert not any("上網查證" in x for x in 場.印出())
    assert "稻妻11｜稻妻イレブン｜候選\n" in 讀(os.path.join(乾淨, "某主.txt"))


def test_provider不支援時中文提示_其他功能照常(乾淨, monkeypatch, tmp_path):
    搜 = 假搜尋(monkeypatch)
    monkeypatch.setattr(llm, "PROVIDER", "openai_compatible")
    場 = 一場(monkeypatch, tmp_path)
    assert 場.跑(web_verify=True, provider="openai_compatible") is True
    assert any(x.startswith("上網查證無法使用") and "其他功能照常" in x for x in 場.印出())
    assert 場.話題數() == 1 and 搜.問過 == []
    assert any("詞庫新增：稻妻11（稻妻イレブン）" in x for x in 場.印出())


def test_開關打開_查到寫成上網_結束訊息分開列次數與費用(乾淨, monkeypatch, tmp_path):
    搜 = 假搜尋(monkeypatch, 預設=回覆(找到))
    場 = 一場(monkeypatch, tmp_path)
    assert 場.跑(web_verify=True) is True
    assert 搜.問過 == ["稻妻イレブン"]
    assert f"閃電十一人｜稻妻イレブン｜上網｜{網址} 正式原文：イナズマイレブン" in 讀(os.path.join(乾淨, "某主.txt"))
    結束 = 場.結束()
    assert "上網查證：查 1 個，確認 1 個，查無 0 個，未完成 0 個；呼叫 1 次，搜尋 1 次" in 結束
    assert "搜尋 0.010" in 結束
    assert 結束.splitlines()[1].startswith("完成：切出 1 個話題，共呼叫 ")     # 摘要的用量那一行不含查證


def test_直播中只查這一場新加入的候選_不查舊候選(乾淨, monkeypatch, tmp_path):
    寫詞庫(乾淨, "桃鉄｜桃太郎電鉄｜候選\n")
    搜 = 假搜尋(monkeypatch)
    一場(monkeypatch, tmp_path).跑(web_verify=True)
    assert 搜.問過 == ["稻妻イレブン"]


@pytest.mark.parametrize("例外", [llm.查證失敗("APITimeoutError"), RuntimeError("壞了")])
def test_查證失敗不影響摘要(乾淨, monkeypatch, tmp_path, 例外):
    假搜尋(monkeypatch, 預設=例外)
    場 = 一場(monkeypatch, tmp_path)
    assert 場.跑(web_verify=True) is True
    assert 場.話題數() == 1
    assert "上網查證：查 1 個，確認 0 個，查無 0 個，未完成 1 個" in 場.結束()
    assert 讀(os.path.join(乾淨, "某主.txt")).endswith("稻妻11｜稻妻イレブン｜候選\n")     # 沒有標已查


def test_查到之後的摘要提示詞用上網的寫法(乾淨):
    庫 = glossary.詞庫("某主")
    庫.自動加入([("稻妻11", "稻妻イレブン")])
    庫.套用查證("稻妻イレブン", "閃電十一人", 網址)
    段 = 庫.提示段("稻妻イレブン")
    assert "閃電十一人（稻妻イレブン）" in 段 and "稻妻11" not in 段


def test_載入詞庫訊息分開列手動與上網(乾淨, monkeypatch):
    印 = []
    monkeypatch.setattr(events, "接收者們", [lambda 種類, 內容: 印.append(內容.get("印出"))])
    寫詞庫(乾淨, f"艾倫｜エレン｜手動\n閃電十一人｜イナズマ｜上網｜{網址}\n桃鉄｜桃太郎電鉄｜候選｜已查\n")
    lt.載入詞庫("某主")
    assert 印[-1] == "已載入詞庫：某主，手動 1 個、上網 1 個（另有候選 1 個，這一場不使用）"


# ---------- 設定：欄位、命令列、--show-config、舊 config.json ----------
def test_設定欄位預設關_命令列可覆蓋_舊檔沒有欄位不警告(tmp_path, monkeypatch, capsys):
    路徑 = tmp_path / "config.json"
    monkeypatch.setattr(config, "設定檔路徑", str(路徑))
    路徑.write_text(json.dumps({"model": "m"}), encoding="utf-8")
    設定, 來源, 警告們 = config.載入設定()
    assert 設定["web_verify"] is False and 來源["web_verify"] == "內建預設" and 警告們 == []
    設定, 來源, _ = config.載入設定({"web_verify": True})
    assert 設定["web_verify"] is True and 來源["web_verify"] == "命令列"
    路徑.write_text(json.dumps({"web_verify": "yes"}), encoding="utf-8")
    assert any("web_verify" in w for w in config.載入設定()[2])
    config.印設定(*config.載入設定({"web_verify": True})[:2], "已設定")
    assert any(l.strip().startswith("web_verify") and "命令列" in l for l in capsys.readouterr().out.splitlines())


def test_命令列參數_web與no_web(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(config, "設定檔路徑", str(tmp_path / "沒有.json"))
    for 參數, 值 in (("--web", "True"), ("--no-web", "False")):
        monkeypatch.setattr("sys.argv", ["live_topics.py", 參數, "--show-config"])
        lt.main()
        行 = next(l for l in capsys.readouterr().out.splitlines() if l.strip().startswith("web_verify"))
        assert 值 in 行 and "命令列" in 行


# ---------- 費用表 ----------
def test_費用表多一項上網查證_開關與provider(monkeypatch):
    基本 = config.出廠預設() | {"language": "ja"}
    關 = next(x for x in ce.估算(基本, "balanced", True)["項目們"] if x["鍵"] == "上網")
    assert not 關["開啟"] and 關["每小時"] == 0 and ce.項目金額字(關) == "未開啟 $0"
    開結果 = ce.估算(基本 | {"web_verify": True}, "balanced", True)
    開 = next(x for x in 開結果["項目們"] if x["鍵"] == "上網")
    token, 搜尋 = ce.查證每小時(基本)
    assert 開["開啟"] and 開["每小時"] == round(token + 搜尋, 2) and 搜尋 == pytest.approx(10 * ce.查證每詞搜尋 * 0.01)
    assert 開結果["合計"] == pytest.approx(ce.估算(基本, "balanced", True)["合計"] + 開["每小時"], abs=1e-9)
    不支援 = next(x for x in ce.估算(基本 | {"web_verify": True, "provider": "openai_compatible"}, "balanced", True)
                ["項目們"] if x["鍵"] == "上網")
    assert not 不支援["開啟"] and "不支援" in 不支援["狀態"]
    assert ce.表格列們(開結果)[-2][0] == "上網查證"
    assert llm.每次搜尋美元 == 0.01


def test_設定框有勾選且會存進config(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import settings_page
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "設定檔路徑", str(tmp_path / "config.json"))
    主 = SimpleNamespace(面板=SimpleNamespace(翻譯將啟用=lambda: True, 聊天將開啟=lambda: False),
                        設方向=lambda 置頂: None, 執行中=lambda: False)
    頁 = settings_page.設定頁(主)
    頁.載入()
    勾 = 頁.欄["web_verify"]
    assert not 勾.isChecked() and "上網查證" in 勾.text() and "另外計費" in 勾.text()
    assert 頁.費用表[-2][:2] == ("上網查證", "未開啟 $0")
    勾.setChecked(True)
    assert 頁.費用表[-2][1].startswith("$") and 頁.讀全部()["web_verify"] is True
    頁.deleteLater()


# ---------- 收尾：官方單價與一般詞彙 ----------
def test_出廠預設與範例檔的單價是Haiku5點5官方單價():
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.example.json"),
              encoding="utf-8") as f:
        範例 = json.load(f)
    for 設定 in (config.出廠預設(), 範例):
        assert (設定["price_input"], 設定["price_output"]) == (0.10, 0.50)


def test_結束訊息的金額照目前單價算():
    llm.用量.update(次數=2, 輸入=1_000_000, 輸出=1_000_000)
    assert "0.600 美元" in llm.用量文字(0.10, 0.50)
    llm.查證用量.update(次數=1, 輸入=1_000_000, 輸出=1_000_000, 搜尋=3)
    assert "0.630 美元（token 0.600" in llm.查證用量文字(0.10, 0.50)


def test_提示詞要求只列專有名詞_一般詞彙回查無():
    for 字 in ("人名", "作品名", "遊戲名", "角色名", "團體名", "店名", "地名"):
        assert 字 in glossary.名詞格式
    assert "一般詞彙一律不要列" in glossary.名詞格式 and "蛋白粉" in glossary.名詞格式
    e = glossary.條目("蛋白粉", "プロテイン", "候選")
    p = wv.提示詞(e, {}, [])
    assert "一般詞彙" in p and "回答查無" in p


def test_背景查證進行中_主執行緒的交接不被擋住(乾淨, monkeypatch):
    放行 = threading.Event()
    monkeypatch.setattr(llm, "上網搜尋", lambda 提示詞, 模型, 最多搜尋=2: (放行.wait(5), 回覆(查無))[1])
    寫詞庫(乾淨, "")
    庫 = glossary.詞庫("某主")
    新的 = 庫.自動加入([(f"詞{i}", f"ゴ{i}") for i in range(3)])
    查 = wv.背景查證(庫, {}, "m")
    t0 = time.monotonic()
    查.加入(新的, [])
    庫.自動加入([("新詞", "シンゴ")])                      # 查證卡在搜尋時，主執行緒照樣能寫詞庫
    assert time.monotonic() - t0 < 0.5 and 查.進行中() == 3
    放行.set()
    assert "未完成 0 個" in 查.收尾(5)
