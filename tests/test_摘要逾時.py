"""摘要類呼叫（話題判斷、分鐘摘要、話題摘要）的逾時與重試上限：
timeout／max_retries 有傳進 SDK；逾時不被改寫成 連線錯誤（不讓整場停下），
話題判斷當作 same、話題摘要只讓這一題顯示說明，下一輪照常。
全部用假 client，不呼叫真 API、不連網。"""
import json
import os
from types import SimpleNamespace

import anthropic
import openai
import pytest

import app_paths
import live_topics as lt
import llm

正式 = "【話題標題】實況主在對戰中躲避夾擊\n【時間範圍】1:11:54 - 1:15:30\n【摘要】假摘要。\n【重點】\n- [1:12:00] 假重點\n【支線】無"


@pytest.fixture(autouse=True)
def 乾淨設定(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "BASE_URL", "")
    monkeypatch.setattr(llm, "API_KEY_ENV", "TEST_FAKE_KEY")
    monkeypatch.setattr(llm, "摘要_思考", True)
    monkeypatch.setattr(llm, "用量", {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0})
    monkeypatch.setattr(llm, "翻譯用量", {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0})
    monkeypatch.setattr(llm, "回應資訊們", {})
    monkeypatch.setattr(llm, "停止原因們", {})
    monkeypatch.setattr(llm.api_key, "取得", lambda *a: "sk-fake")
    monkeypatch.setattr(lt, "統計", {"分鐘摘要": 0, "JSON失敗": 0})
    if os.path.exists(app_paths.摘要格式紀錄檔()):
        os.remove(app_paths.摘要格式紀錄檔())


def 逾時(套件):
    return 套件.APITimeoutError.__new__(套件.APITimeoutError)     # 真正的例外類別，不必湊出 request


class 假Anthropic:
    建立們: list = None
    回應們: list = None

    def __init__(self, **kw):
        假Anthropic.建立們.append(kw)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        回 = 假Anthropic.回應們.pop(0)
        if isinstance(回, Exception):
            raise 回
        return 回


def 回應(文字):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=文字)], stop_reason="end_turn",
                           stop_details=None, usage=SimpleNamespace(input_tokens=3000, output_tokens=200))


@pytest.fixture
def 甲(monkeypatch):
    假Anthropic.建立們, 假Anthropic.回應們 = [], []
    monkeypatch.setattr(anthropic, "Anthropic", 假Anthropic)
    return 假Anthropic


class 假OpenAI:
    建立們: list = None
    例外 = None

    def __init__(self, **kw):
        假OpenAI.建立們.append(kw)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        if 假OpenAI.例外:
            raise 假OpenAI.例外
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="答"), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3))


@pytest.fixture
def 乙(monkeypatch):
    假OpenAI.建立們, 假OpenAI.例外 = [], None
    monkeypatch.setattr(openai, "OpenAI", 假OpenAI)
    monkeypatch.setattr(llm, "PROVIDER", "openai_compatible")
    return 假OpenAI


# ---------- 常數與傳進 SDK 的參數 ----------
def test_逾時與重試常數合理():
    assert 120 <= llm.摘要逾時秒 <= 180          # 延伸思考開、寫滿 8000 token 也不會誤殺
    assert llm.摘要最多重試 == 1
    assert llm.摘要逾時秒 * (1 + llm.摘要最多重試) <= 6 * 60      # 卡住時最久約 6 分鐘就放棄這一輪


def test_anthropic_摘要傳逾時與重試_翻譯類照舊(甲):
    假Anthropic.回應們 = [回應("a"), 回應("b"), 回應("c")]
    llm.call_llm("q", "m")
    assert 甲.建立們[0]["timeout"] == llm.摘要逾時秒 and 甲.建立們[0]["max_retries"] == llm.摘要最多重試
    llm.call_llm("q", "m", "翻譯")
    assert "timeout" not in 甲.建立們[1] and "max_retries" not in 甲.建立們[1]
    llm.call_llm("q", "m", "聊天翻譯")
    assert "timeout" not in 甲.建立們[2] and 甲.建立們[2]["max_retries"] == 0


def test_openai_摘要傳逾時與重試_翻譯類照舊(乙):
    llm.call_llm("q", "m")
    assert 乙.建立們[0]["timeout"] == llm.摘要逾時秒 and 乙.建立們[0]["max_retries"] == llm.摘要最多重試
    llm.call_llm("q", "m", "翻譯")
    assert "timeout" not in 乙.建立們[1] and "max_retries" not in 乙.建立們[1]
    llm.call_llm("q", "m", "聊天翻譯")
    assert "timeout" not in 乙.建立們[2] and 乙.建立們[2]["max_retries"] == 0


@pytest.mark.parametrize("套件,類名", [(anthropic, "Anthropic"), (openai, "OpenAI")])
def test_真的SDK收下這兩個值(monkeypatch, 套件, 類名):
    """參數名稱真的是 SDK 認得的：用真的 client 類別建立（不送出請求、不連網），看它記下的值。"""
    真類別, 建立們 = getattr(套件, 類名), []

    def 記下(**kw):
        c = 真類別(**kw)
        建立們.append(c)
        raise 逾時(套件)            # 建好就停，不送出請求
    monkeypatch.setattr(套件, 類名, 記下)
    if 套件 is openai:
        monkeypatch.setattr(llm, "PROVIDER", "openai_compatible")
    with pytest.raises(套件.APITimeoutError):
        llm.call_llm("q", "m")
    assert 建立們[0].timeout == llm.摘要逾時秒 and 建立們[0].max_retries == llm.摘要最多重試


# ---------- 逾時不是「連不上」 ----------
def test_anthropic_逾時照原樣丟出_不改寫成連線錯誤(甲):
    假Anthropic.回應們 = [逾時(anthropic)]
    with pytest.raises(anthropic.APITimeoutError) as e:
        llm.call_llm("q", "m")
    assert not isinstance(e.value, llm.模型錯誤) and llm.是服務錯誤(e.value)
    assert llm.錯誤描述(e.value) == "APITimeoutError"


def test_openai_逾時照原樣丟出_不改寫成連線錯誤(乙):
    乙.例外 = 逾時(openai)
    with pytest.raises(openai.APITimeoutError) as e:
        llm.call_llm("q", "m")
    assert not isinstance(e.value, llm.模型錯誤) and llm.是服務錯誤(e.value)


def test_真的連不上照舊是連線錯誤(甲):
    假Anthropic.回應們 = [anthropic.APIConnectionError.__new__(anthropic.APIConnectionError)]
    with pytest.raises(llm.連線錯誤):
        llm.call_llm("q", "m")


# ---------- 直播中：這一輪當作沒變／這一題顯示說明，下一輪照常 ----------
def test_話題判斷逾時_當作same_下一輪照常(甲):
    假Anthropic.回應們 = [逾時(anthropic), 回應(json.dumps(
        {"decision": "new_topic", "new_topic_start": "01:30", "topic": "新的一件事", "topic_brief": "新簡述"},
        ensure_ascii=False))]
    新行 = ["[01:00] 新行甲", "[01:30] 新行乙"]
    assert lt.問話題("舊簡述", ["[00:00] 舊行"], 新行) == ("same", "", "舊簡述", [], None, "舊簡述")
    assert lt.統計["JSON失敗"] == 1
    決定, 切點, 簡述, *_ = lt.問話題("舊簡述", ["[00:00] 舊行"], 新行)
    assert (決定, 切點, 簡述) == ("new_topic", "01:30", "新簡述")


def test_話題摘要逾時_這一題顯示說明_下一題照常(甲, monkeypatch, tmp_path):
    事件們 = []
    monkeypatch.setattr(lt.events, "送出", lambda 種類, **k: 事件們.append((種類, k)))
    monkeypatch.setitem(lt.存檔, "摘要", True)
    假Anthropic.回應們 = [逾時(anthropic), 回應(f"{lt.正式開頭}\n{正式}\n{lt.正式結尾}")]

    def 輸出一題(檔名):
        話題 = lt.新話題()
        lt.加入(話題, [(4314, "[1:11:54] 実況主の発言"), (4530, "[1:15:30] 別の発言")])
        lt.輸出話題摘要(話題, 4530, str(tmp_path / 檔名))
        return [k["內文"] for 種類, k in 事件們 if 種類 == "topic_summary"][-1]

    內文 = 輸出一題("一.md")
    assert "呼叫模型時出錯（APITimeoutError）" in 內文
    with open(app_paths.摘要格式紀錄檔(), encoding="utf-8") as f:
        assert "錯誤類型=APITimeoutError" in f.read()
    assert len(假Anthropic.建立們) == 1                 # 逾時不在程式裡再重試（SDK 已重試過）
    assert 輸出一題("二.md") == 正式
