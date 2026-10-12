"""安全網測試：llm.call_llm 兩種服務（anthropic／openai_compatible）的呼叫路徑與錯誤對應。
用假 client 取代 anthropic.Anthropic／openai.OpenAI，不真的呼叫 API、不連網。"""
import sys
from types import SimpleNamespace

import anthropic
import openai
import pytest

import llm


@pytest.fixture(autouse=True)
def 乾淨設定(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "BASE_URL", "")
    monkeypatch.setattr(llm, "API_KEY_ENV", "TEST_FAKE_KEY")
    monkeypatch.setattr(llm, "摘要_思考", True)
    monkeypatch.setattr(llm, "最後停止原因", "")
    monkeypatch.setattr(llm, "用量", {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0})
    monkeypatch.setattr(llm, "翻譯用量", {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0})
    monkeypatch.setenv("TEST_FAKE_KEY", "sk-fake")


def 造例外(類別):
    return 類別.__new__(類別)          # 真正的例外類別，但不必湊出 httpx 的 response／request


# ---------- anthropic ----------
class 假Anthropic:
    建立參數 = None
    呼叫參數 = None
    回應 = None
    例外 = None

    def __init__(self, **kw):
        假Anthropic.建立參數 = kw
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        假Anthropic.呼叫參數 = kw
        if 假Anthropic.例外:
            raise 假Anthropic.例外
        return 假Anthropic.回應


def anthropic回應(內容=None, 輸入=11, 輸出=7, 停止="end_turn"):
    區塊們 = 內容 or [SimpleNamespace(type="thinking", text="內心戲"), SimpleNamespace(type="text", text="答案")]
    用量 = SimpleNamespace(input_tokens=輸入, output_tokens=輸出) if 輸入 is not None else None
    return SimpleNamespace(content=區塊們, usage=用量, stop_reason=停止)


@pytest.fixture
def 甲(monkeypatch):
    假Anthropic.建立參數 = 假Anthropic.呼叫參數 = 假Anthropic.例外 = None
    假Anthropic.回應 = anthropic回應()
    monkeypatch.setattr(anthropic, "Anthropic", 假Anthropic)
    return 假Anthropic


def test_anthropic_只取文字區塊_記用量與停止原因(甲):
    assert llm.call_llm("問題", "模型甲") == "答案"
    assert (llm.用量["次數"], llm.用量["輸入"], llm.用量["輸出"]) == (1, 11, 7)
    assert llm.翻譯用量["次數"] == 0
    assert llm.最後停止原因 == "end_turn"
    p = 甲.呼叫參數
    assert p["model"] == "模型甲" and p["max_tokens"] == llm.MAX_TOKENS
    assert p["messages"] == [{"role": "user", "content": "問題"}]
    assert "thinking" not in p                    # 摘要且思考開著：維持原樣


def test_anthropic_摘要關閉思考(甲, monkeypatch):
    monkeypatch.setattr(llm, "摘要_思考", False)
    llm.call_llm("q", "m")
    assert 甲.呼叫參數["thinking"] == {"type": "disabled"}
    assert 甲.呼叫參數["max_tokens"] == llm.MAX_TOKENS


def test_anthropic_翻譯一律關思考_限制長度_用量分開記(甲):
    llm.call_llm("q", "m", "翻譯")
    assert 甲.呼叫參數["thinking"] == {"type": "disabled"}
    assert 甲.呼叫參數["max_tokens"] == llm.翻譯_MAX_TOKENS
    assert llm.翻譯用量["次數"] == 1 and llm.用量["次數"] == 0


def test_anthropic_金鑰與網址傳給client(甲, monkeypatch):
    monkeypatch.setattr(llm, "BASE_URL", "http://localhost:9/v1")
    llm.call_llm("q", "m")
    assert 甲.建立參數 == {"api_key": "sk-fake", "base_url": "http://localhost:9/v1"}


def test_anthropic_不需要金鑰時不傳api_key(甲, monkeypatch):
    monkeypatch.setattr(llm, "API_KEY_ENV", "")
    llm.call_llm("q", "m")
    assert 甲.建立參數 == {}


def test_anthropic_沒有用量就記缺token(甲):
    甲.回應 = anthropic回應(輸入=None)
    llm.call_llm("q", "m")
    assert llm.用量["缺token"] == 1 and llm.用量["輸入"] == 0 and llm.用量["次數"] == 1


@pytest.mark.parametrize("例外類別,預期", [
    (anthropic.AuthenticationError, llm.金鑰錯誤),
    (anthropic.PermissionDeniedError, llm.金鑰錯誤),
    (anthropic.APIConnectionError, llm.連線錯誤),
])
def test_anthropic_錯誤對應(甲, 例外類別, 預期):
    甲.例外 = 造例外(例外類別)
    with pytest.raises(預期) as e:
        llm.call_llm("q", "m")
    assert isinstance(e.value, llm.模型錯誤)
    assert "TEST_FAKE_KEY" in str(e.value) if 預期 is llm.金鑰錯誤 else "連不上" in str(e.value)


def test_anthropic_其他錯誤不被改寫(甲):
    甲.例外 = ValueError("別的問題")
    with pytest.raises(ValueError):
        llm.call_llm("q", "m")


# ---------- openai_compatible ----------
class 假OpenAI:
    建立參數 = None
    呼叫參數 = None
    回應 = None
    例外 = None

    def __init__(self, **kw):
        假OpenAI.建立參數 = kw
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        假OpenAI.呼叫參數 = kw
        if 假OpenAI.例外:
            raise 假OpenAI.例外
        return 假OpenAI.回應


def openai回應(文字="開放答案", 輸入=5, 輸出=3):
    用量 = SimpleNamespace(prompt_tokens=輸入, completion_tokens=輸出) if 輸入 is not None else None
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=文字))], usage=用量)


@pytest.fixture
def 乙(monkeypatch):
    假OpenAI.建立參數 = 假OpenAI.呼叫參數 = 假OpenAI.例外 = None
    假OpenAI.回應 = openai回應()
    monkeypatch.setattr(openai, "OpenAI", 假OpenAI)
    monkeypatch.setattr(llm, "PROVIDER", "openai_compatible")
    return 假OpenAI


def test_openai_正常回傳文字並記用量(乙):
    assert llm.call_llm("問", "gpt") == "開放答案"
    assert (llm.用量["次數"], llm.用量["輸入"], llm.用量["輸出"]) == (1, 5, 3)
    p = 乙.呼叫參數
    assert p["model"] == "gpt" and p["max_tokens"] == llm.MAX_TOKENS
    assert p["messages"] == [{"role": "user", "content": "問"}]
    assert 乙.建立參數 == {"api_key": "sk-fake", "base_url": None}


def test_openai_翻譯用較小的輸出上限且分開記用量(乙):
    llm.call_llm("q", "m", "翻譯")
    assert 乙.呼叫參數["max_tokens"] == llm.翻譯_MAX_TOKENS
    assert llm.翻譯用量["次數"] == 1 and llm.用量["次數"] == 0


def test_openai_沒有金鑰時填假字串_網址照傳(乙, monkeypatch):
    monkeypatch.setattr(llm, "API_KEY_ENV", "")
    monkeypatch.setattr(llm, "BASE_URL", "http://localhost:11434/v1")
    llm.call_llm("q", "m")
    assert 乙.建立參數 == {"api_key": "ollama", "base_url": "http://localhost:11434/v1"}


def test_openai_內容為空或結構壞掉回傳空字串(乙):
    乙.回應 = openai回應(文字=None)
    assert llm.call_llm("q", "m") == ""
    乙.回應 = SimpleNamespace(choices=[], usage=None)
    assert llm.call_llm("q", "m") == ""


def test_openai_沒有用量記缺token(乙):
    乙.回應 = openai回應(輸入=None)
    llm.call_llm("q", "m")
    assert llm.用量["缺token"] == 1


@pytest.mark.parametrize("例外類別,預期", [
    (openai.AuthenticationError, llm.金鑰錯誤),
    (openai.PermissionDeniedError, llm.金鑰錯誤),
    (openai.APIConnectionError, llm.連線錯誤),
])
def test_openai_錯誤對應(乙, 例外類別, 預期):
    乙.例外 = 造例外(例外類別)
    with pytest.raises(預期):
        llm.call_llm("q", "m")


def test_沒裝openai套件時給中文說明(乙, monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", None)       # import openai 會丟 ImportError
    with pytest.raises(llm.模型錯誤) as e:
        llm.call_llm("q", "m")
    assert "pip install openai" in str(e.value)


# ---------- 其他 ----------
def test_provider不認得就走anthropic(甲, monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "亂寫")
    assert llm.call_llm("q", "m") == "答案"


def test_檢查金鑰():
    assert llm.檢查金鑰() is None


def test_檢查金鑰_沒設定時給一句中文(monkeypatch):
    monkeypatch.delenv("TEST_FAKE_KEY")
    assert "TEST_FAKE_KEY" in llm.檢查金鑰()
    monkeypatch.setattr(llm, "API_KEY_ENV", "")
    assert llm.檢查金鑰() is None


def test_用量文字():
    llm.用量.update(次數=2, 輸入=1_000_000, 輸出=1_000_000)
    assert "共呼叫 2 次" in llm.用量文字(1.0, 5.0) and "6.000 美元" in llm.用量文字(1.0, 5.0)
    llm.用量["缺token"] = 1
    assert "無法計算" in llm.用量文字(1.0, 5.0)


# ---------- 聊天室翻譯：用量與停止原因分類別記、不自動重試、429 只對聊天翻譯改寫 ----------
@pytest.fixture
def 聊天用量(monkeypatch):
    monkeypatch.setattr(llm, "聊天翻譯用量", {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0})
    monkeypatch.setattr(llm, "停止原因們", {})


def test_聊天翻譯_用量分開記_關思考_不重試(甲, 聊天用量):
    甲.回應 = anthropic回應(停止="max_tokens")
    llm.call_llm("q", "m", "聊天翻譯")
    assert llm.聊天翻譯用量["次數"] == 1 and llm.翻譯用量["次數"] == 0 and llm.用量["次數"] == 0
    assert 甲.呼叫參數["thinking"] == {"type": "disabled"}
    assert 甲.呼叫參數["max_tokens"] == llm.聊天翻譯_MAX_TOKENS
    assert 甲.建立參數["max_retries"] == 0


def test_停止原因依類別分開_聊天翻譯不覆蓋逐句翻譯讀的那一格(甲, 聊天用量):
    甲.回應 = anthropic回應(停止="end_turn")
    llm.call_llm("q", "m", "翻譯")
    甲.回應 = anthropic回應(停止="max_tokens")
    llm.call_llm("q", "m", "聊天翻譯")
    assert llm.停止原因們 == {"翻譯": "end_turn", "聊天翻譯": "max_tokens"}
    assert llm.最後停止原因 == "end_turn"             # 逐句翻譯失敗紀錄讀的值沒有被聊天翻譯蓋掉


def test_用量表依類別(聊天用量):
    assert llm.用量表("摘要") is llm.用量
    assert llm.用量表("翻譯") is llm.翻譯用量
    assert llm.用量表("聊天翻譯") is llm.聊天翻譯用量


def test_429_聊天翻譯改寫成限速錯誤_其他類別維持原樣(甲, 聊天用量):
    甲.例外 = 造例外(anthropic.RateLimitError)
    with pytest.raises(llm.限速錯誤):
        llm.call_llm("q", "m", "聊天翻譯")
    for 類別 in ("摘要", "翻譯"):
        with pytest.raises(anthropic.RateLimitError):
            llm.call_llm("q", "m", 類別)
    assert "max_retries" not in 甲.建立參數            # 摘要與逐句翻譯照舊用 SDK 預設的重試


def test_openai_聊天翻譯不重試_429改寫(乙, 聊天用量):
    llm.call_llm("q", "m", "聊天翻譯")
    assert 乙.建立參數["max_retries"] == 0 and 乙.呼叫參數["max_tokens"] == llm.聊天翻譯_MAX_TOKENS
    assert llm.聊天翻譯用量["次數"] == 1
    乙.例外 = 造例外(openai.RateLimitError)
    with pytest.raises(llm.限速錯誤):
        llm.call_llm("q", "m", "聊天翻譯")
    with pytest.raises(openai.RateLimitError):
        llm.call_llm("q", "m", "翻譯")
