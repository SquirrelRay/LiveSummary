"""話題摘要的空回應（乾淨電腦測試：「回傳 0 字」卻顯示「沒有照格式回覆」）：
llm 記下停止原因、拒絕類別、token、內容區塊；空回應自動重試一次（重試時關閉思考），拒絕不重試；
呼叫出錯只讓這一題顯示說明；給使用者的說明依原因分開；紀錄不含金鑰。
全部用假 client／假模型回覆，不呼叫真 API、不連網。"""
import os
import threading
from types import SimpleNamespace

import anthropic
import openai
import pytest

import app_paths
import live_topics as lt
import llm
import summarize

假金鑰 = "sk-ant-假的金鑰-不可以出現在紀錄裡"
正式 = "【話題標題】實況主在對戰中躲避夾擊\n【時間範圍】1:11:54 - 1:15:30\n【摘要】假摘要。\n【重點】\n- [1:12:00] 假重點\n【支線】無"


@pytest.fixture(autouse=True)
def 乾淨設定(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "BASE_URL", "")
    monkeypatch.setattr(llm, "API_KEY_ENV", "TEST_FAKE_KEY")
    monkeypatch.setattr(llm, "摘要_思考", True)
    monkeypatch.setattr(llm, "用量", {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0})
    monkeypatch.setattr(llm, "回應資訊們", {})
    monkeypatch.setattr(llm, "停止原因們", {})
    monkeypatch.setenv("TEST_FAKE_KEY", 假金鑰)
    monkeypatch.setattr(llm.api_key, "取得", lambda *a: 假金鑰)
    if os.path.exists(app_paths.摘要格式紀錄檔()):
        os.remove(app_paths.摘要格式紀錄檔())


def 紀錄():
    if not os.path.exists(app_paths.摘要格式紀錄檔()):
        return ""
    with open(app_paths.摘要格式紀錄檔(), encoding="utf-8") as f:
        return f.read()


# ---------- llm：真的照 anthropic／openai 的回應形狀，用假 client ----------
class 假Anthropic:
    回應們: list = None       # 甲() 每個測試重新放
    呼叫們: list = None

    def __init__(self, **kw):
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        假Anthropic.呼叫們.append(kw)
        回 = 假Anthropic.回應們.pop(0)
        if isinstance(回, Exception):
            raise 回
        return 回


def 回應(區塊們, 停止, 輸出=4000, 拒絕類別=None):
    細節 = SimpleNamespace(type="refusal", category=拒絕類別, explanation="假說明") if 停止 == "refusal" else None
    return SimpleNamespace(content=[SimpleNamespace(type=t, text=x) for t, x in 區塊們], stop_reason=停止,
                           stop_details=細節, usage=SimpleNamespace(input_tokens=3000, output_tokens=輸出))


只有思考 = [("thinking", "")]          # 思考內容預設不回傳（omitted），只剩空的思考區塊


@pytest.fixture
def 甲(monkeypatch):
    假Anthropic.回應們, 假Anthropic.呼叫們 = [], []
    monkeypatch.setattr(anthropic, "Anthropic", 假Anthropic)
    return 假Anthropic


def test_思考用光max_tokens_沒有文字_記下停止原因與區塊(甲):
    甲.回應們 = [回應(只有思考, "max_tokens")]
    assert llm.call_llm("問", "claude-haiku-5-5") == ""
    資 = llm.回應資訊們["摘要"]
    assert (資["停止原因"], 資["輸出"], 資["區塊"]) == ("max_tokens", 4000, "thinking")
    assert llm.停止種類(資["停止原因"]) == "截斷"
    字 = llm.回應紀錄("摘要")
    assert "stop_reason=max_tokens" in 字 and "輸出=4000" in 字 and "內容區塊=thinking" in 字
    assert 假金鑰 not in 字


def test_拒絕_記下拒絕類別(甲):
    甲.回應們 = [回應([], "refusal", 輸出=0, 拒絕類別="cyber")]
    assert llm.call_llm("問", "claude-haiku-5-5") == ""
    assert llm.停止種類(llm.回應資訊們["摘要"]["停止原因"]) == "拒絕"
    assert "拒絕類別=cyber" in llm.回應紀錄("摘要") and "內容區塊=（無）" in llm.回應紀錄("摘要")


@pytest.mark.parametrize("停止, 種類", [
    ("end_turn", "其他"), ("max_tokens", "截斷"), ("refusal", "拒絕"), ("stop_sequence", "其他"),
    ("pause_turn", "其他"), ("", "其他"), (None, "其他"),
    ("length", "截斷"), ("content_filter", "拒絕"), ("stop", "其他"),        # openai 相容服務的 finish_reason
])
def test_停止種類(停止, 種類):
    assert llm.停止種類(停止) == 種類


def test_關閉思考只影響這段期間與這條執行緒(甲):
    甲.回應們 = [回應([("text", "a")], "end_turn")] * 4
    llm.call_llm("問", "m")
    with llm.關閉思考():
        llm.call_llm("問", "m")
        別條 = threading.Thread(target=lambda: llm.call_llm("問", "m"))
        別條.start()
        別條.join()
    llm.call_llm("問", "m")
    思考們 = [p.get("thinking") for p in 甲.呼叫們]
    assert 思考們 == [None, {"type": "disabled"}, None, None]


def test_openai相容_length與content_filter也記下(monkeypatch):
    class 假OpenAI:
        def __init__(self, **kw):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=None), finish_reason="content_filter")],
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=0))))
    monkeypatch.setattr(openai, "OpenAI", 假OpenAI)
    monkeypatch.setattr(llm, "PROVIDER", "openai_compatible")
    assert llm.call_llm("問", "m") == ""
    assert llm.停止種類(llm.回應資訊們["摘要"]["停止原因"]) == "拒絕"
    assert "內容區塊=（無）" in llm.回應紀錄("摘要")


def test_服務錯誤與程式錯誤分得開():
    e = anthropic.InternalServerError.__new__(anthropic.InternalServerError)
    e.status_code = 529
    assert llm.是服務錯誤(e) and llm.錯誤描述(e) == "InternalServerError 529"
    assert not llm.是服務錯誤(TypeError("程式寫錯")) and not llm.是服務錯誤(OSError())


# ---------- 話題摘要：重試與說明（假的 summarize.call_llm，照劇本回答並填 llm.回應資訊們） ----------
class 劇本:
    """每次呼叫拿出下一步：(文字, 停止原因, 拒絕類別) 或例外。記下每次呼叫時有沒有關閉思考。"""

    def __init__(self, *步們):
        self.步們 = list(步們)
        self.關思考們 = []

    def __call__(self, 提示詞):
        self.關思考們.append(getattr(llm._本執行緒, "關思考", False))
        步 = self.步們.pop(0)
        if isinstance(步, BaseException):
            raise 步
        文字, 停止, 拒絕 = 步
        llm._記回應("摘要", 停止, 拒絕, 3000, 4000 if 停止 == "max_tokens" else 50,
                   (["thinking"] if 停止 == "max_tokens" else []) + (["text"] if 文字 else []))
        return 文字


@pytest.fixture
def 跑(monkeypatch, tmp_path):
    def 跑(模型):
        事件們 = []
        monkeypatch.setattr(summarize, "call_llm", 模型)
        monkeypatch.setattr(lt.events, "送出", lambda 種類, **k: 事件們.append((種類, k)))
        monkeypatch.setitem(lt.存檔, "摘要", True)
        話題 = lt.新話題()
        lt.加入(話題, [(4314, "[1:11:54] 実況主の発言"), (4530, "[1:15:30] 別の発言")])
        lt.輸出話題摘要(話題, 4530, str(tmp_path / "話題摘要.md"))
        return next(k["內文"] for 種類, k in 事件們 if 種類 == "topic_summary")
    return 跑


def 包(內容):
    return f"{lt.正式開頭}\n{內容}\n{lt.正式結尾}"


def test_思考用光額度_重試時關閉思考_第二次成功就正常顯示(跑):
    模型 = 劇本(("", "max_tokens", None), (包(正式), "end_turn", None))
    內文 = 跑(模型)
    assert 內文 == 正式
    assert 模型.關思考們 == [False, True]            # 第一次照設定，重試時關閉思考
    字 = 紀錄()
    assert "處理方式=空回應；回傳 0 字；stop_reason=max_tokens" in 字 and "內容區塊=thinking" in 字
    assert 字.count("===") == 2                       # 只記第一次的空回應，第二次成功不記


def test_重試也是空的_說明是長度上限並註明已重試(跑):
    模型 = 劇本(("", "max_tokens", None), ("", "max_tokens", None))
    內文 = 跑(模型)
    assert "用完了回覆長度上限" in 內文 and "已自動重試一次" in 內文 and "沒有照格式" not in 內文
    assert "【時間範圍】1:11:54 - 1:15:30" in 內文
    assert "空回應（重試仍是空的）" in 紀錄()


def test_拒絕_不重試_說明是拒絕(跑):
    模型 = 劇本(("", "refusal", "cyber"))
    內文 = 跑(模型)
    assert len(模型.關思考們) == 1                    # 只呼叫一次
    assert "拒絕回覆" in 內文 and "已自動重試" not in 內文 and "沒有照格式" not in 內文
    assert "stop_reason=refusal，拒絕類別=cyber" in 紀錄()


def test_沒有原因的空白回覆_重試一次_仍空白就說回傳空白(跑):
    模型 = 劇本(("", "end_turn", None), ("  \n ", "end_turn", None))
    內文 = 跑(模型)
    assert 模型.關思考們 == [False, True]
    assert "回傳空白" in 內文 and "已自動重試一次" in 內文


def test_重試後拿到文字但沒照格式_說沒照格式並記停止原因(跑):
    模型 = 劇本(("", "max_tokens", None), ("Wait, let me think.", "end_turn", None))
    內文 = 跑(模型)
    assert "沒有照格式回覆" in 內文 and "Wait" not in 內文
    assert "處理方式=無；回傳 19 字；stop_reason=end_turn" in 紀錄()


def test_有文字但沒照格式_不重試(跑):
    模型 = 劇本(("Wait, let me think.", "end_turn", None))
    內文 = 跑(模型)
    assert len(模型.關思考們) == 1 and "沒有照格式回覆" in 內文


def test_伺服器錯誤_這一題顯示錯誤類型_不中斷整場也不重試(跑):
    e = anthropic.InternalServerError.__new__(anthropic.InternalServerError)
    e.status_code = 529
    模型 = 劇本(e)
    內文 = 跑(模型)
    assert "呼叫模型時出錯（InternalServerError 529）" in 內文
    assert "處理方式=出錯；回傳 0 字；錯誤類型=InternalServerError 529" in 紀錄()


def test_金鑰或連線錯誤照舊往外丟_整場停下來(跑):
    with pytest.raises(llm.金鑰錯誤):
        跑(劇本(llm.金鑰錯誤("金鑰無效")))


def test_程式本身的錯誤不吞掉(跑):
    with pytest.raises(TypeError):
        跑(劇本(TypeError("程式寫錯")))


def test_真的client走完整條路_空回應重試_紀錄不含金鑰(跑, 甲):
    """不換掉 summarize.call_llm：從 輸出話題摘要 → summarize → llm → 假 anthropic client。"""
    甲.回應們 = [回應(只有思考, "max_tokens"), 回應([("thinking", ""), ("text", 包(正式))], "end_turn", 輸出=900)]
    內文 = 跑(summarize.call_llm)
    assert 內文 == 正式
    assert "thinking" not in 甲.呼叫們[0] and 甲.呼叫們[1]["thinking"] == {"type": "disabled"}
    assert llm.用量["次數"] == 2 and llm.用量["輸出"] == 4900          # 兩次都計費、都算進用量
    assert "stop_reason=max_tokens" in 紀錄() and 假金鑰 not in 紀錄()
