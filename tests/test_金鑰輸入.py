"""在工具裡輸入 API 金鑰（offscreen，不開真的視窗、不呼叫真 API、不連網）。
認證管理員一律用 conftest 的假後端（假金鑰庫），不讀寫真的 Windows 認證管理員；金鑰都是假的字串。
1. 存入後讀得到、清除後讀不到；讀取順序：認證管理員優先，沒有才用環境變數。
2. Claude、OpenAI、DeepSeek、其他相容服務各存一把，互不影響；本機服務不需要金鑰。
3. 設定框：切換服務後金鑰欄顯示對應狀態與「如何取得金鑰」；儲存、測試連線、清除。
4. 啟動面板：沒有金鑰時直接顯示提示與按鈕，按下去打開設定框並捲到金鑰欄；存好／清除後立刻更新。
5. 測試連線：成功、金鑰無效、連不上三種白話訊息；失敗絕不儲存。
6. 任何輸出、紀錄檔、錯誤訊息、設定檔都不含金鑰字串。"""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import anthropic
import openai
import pytest
import test_介面冒煙 as 冒煙
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

import api_key
import config
import llm

qapp, 環境 = 冒煙.qapp, 冒煙.環境          # fixture：和冒煙測試共用
真檢查金鑰 = llm.檢查金鑰                 # 冒煙測試的環境把它換成「永遠沒問題」，啟動面板的測試要換回真的

甲金鑰 = "sk-ant-假金鑰-CLAUDE-1111"
乙金鑰 = "sk-proj-假金鑰-OPENAI-2222"
丙金鑰 = "sk-假金鑰-DEEPSEEK-3333"
丁金鑰 = "sk-假金鑰-OTHER-4444"
環境金鑰 = "sk-ant-假金鑰-ENV-9999"
全部假金鑰 = (甲金鑰, 乙金鑰, 丙金鑰, 丁金鑰, 環境金鑰)


def 造例外(類別, 內容=""):
    e = 類別.__new__(類別)          # 真正的例外類別，但不必湊出 httpx 的 response／request
    e.args = (內容,)
    e.message = 內容
    return e


# ---------- 假的模型服務 client：只會「列出模型」 ----------
class 假Anthropic:
    建立參數 = None
    例外 = None

    def __init__(self, **kw):
        假Anthropic.建立參數 = kw
        self.models = SimpleNamespace(list=self._列出)

    def _列出(self, **kw):
        if 假Anthropic.例外:
            raise 假Anthropic.例外
        return SimpleNamespace(data=[SimpleNamespace(id="claude-haiku-5-5")])


class 假OpenAI:
    建立參數 = None
    例外 = None

    def __init__(self, **kw):
        假OpenAI.建立參數 = kw
        self.models = SimpleNamespace(list=self._列出)

    def _列出(self, **kw):
        if 假OpenAI.例外:
            raise 假OpenAI.例外
        return SimpleNamespace(data=[])


@pytest.fixture
def 假服務(monkeypatch):
    假Anthropic.建立參數 = 假Anthropic.例外 = None
    假OpenAI.建立參數 = 假OpenAI.例外 = None
    monkeypatch.setattr(anthropic, "Anthropic", 假Anthropic)
    monkeypatch.setattr(openai, "OpenAI", 假OpenAI)
    return SimpleNamespace(甲=假Anthropic, 乙=假OpenAI)


# ================= 1. 存取與讀取順序 =================
def test_存入後讀得到_清除後讀不到(假金鑰庫):
    assert api_key.取得("anthropic") is None
    api_key.儲存("claude", 甲金鑰)
    assert api_key.取得("anthropic") == 甲金鑰
    assert api_key.狀態("anthropic") == api_key.已儲存
    assert 假金鑰庫.資料 == {(api_key.認證服務名, "claude"): 甲金鑰}
    assert api_key.清除("claude") is True
    assert api_key.取得("anthropic") is None
    assert api_key.狀態("anthropic") == api_key.未設定
    assert api_key.清除("claude") is False           # 本來就沒有：不算錯


def test_空白金鑰不存():
    with pytest.raises(api_key.金鑰存取錯誤):
        api_key.儲存("claude", "   ")


def test_讀取順序_認證管理員優先_沒有才用環境變數(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", 環境金鑰)
    assert api_key.來源與金鑰("claude") == (api_key.環境變數中, 環境金鑰)
    api_key.儲存("claude", 甲金鑰)
    assert api_key.來源與金鑰("claude") == (api_key.已儲存, 甲金鑰)
    api_key.清除("claude")
    assert api_key.來源與金鑰("claude") == (api_key.環境變數中, 環境金鑰)


def test_舊設定改過環境變數名稱_照舊讀得到(monkeypatch):
    monkeypatch.setenv("MY_KEY", 環境金鑰)
    assert api_key.取得("anthropic", "", "MY_KEY") == 環境金鑰
    assert api_key.狀態("anthropic", "", "") == api_key.不需要        # 舊設定留空 = 不需要金鑰


def test_認證管理員壞掉_讀取當作沒存_存入給白話錯誤(假金鑰庫, monkeypatch):
    def 壞(*a):
        raise RuntimeError(甲金鑰)
    monkeypatch.setattr(假金鑰庫, "get_password", 壞)
    monkeypatch.setattr(假金鑰庫, "set_password", 壞)
    assert api_key.取得("anthropic") is None
    with pytest.raises(api_key.金鑰存取錯誤) as e:
        api_key.儲存("claude", 甲金鑰)
    assert 甲金鑰 not in str(e.value) and "認證管理員" in str(e.value)


# ================= 2. 每家服務各存一把 =================
@pytest.mark.parametrize("provider,網址,代號", [
    ("anthropic", "", "claude"),
    ("anthropic", "https://api.anthropic.com", "claude"),
    ("openai_compatible", "", "openai"),
    ("openai_compatible", "https://api.openai.com/v1", "openai"),
    ("openai_compatible", "https://API.DeepSeek.com", "deepseek"),
    ("openai_compatible", "https://api.deepseek.com/v1/", "deepseek"),
    ("openai_compatible", "http://localhost:11434/v1", "本機"),
    ("openai_compatible", "http://127.0.0.1:1234/v1", "本機"),
    ("openai_compatible", "https://openrouter.ai/api/v1", "openrouter"),
    ("openai_compatible", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini"),
    ("openai_compatible", "https://example.com/api/v1", "相容:example.com/api/v1"),
    ("openai_compatible", "https://example.com/api/v1/", "相容:example.com/api/v1"),
    ("openai_compatible", "https://example.com:8443/v1", "相容:example.com:8443/v1"),
])
def test_服務代號(provider, 網址, 代號):
    assert api_key.服務代號(provider, 網址) == 代號


def test_Claude_OpenAI_DeepSeek_其他相容服務各自存放互不影響():
    服務們 = [("anthropic", "", 甲金鑰), ("openai_compatible", "https://api.openai.com/v1", 乙金鑰),
           ("openai_compatible", "https://api.deepseek.com", 丙金鑰), ("openai_compatible", "https://example.com/api/v1", 丁金鑰)]
    for provider, 網址, 金鑰 in 服務們:
        api_key.儲存(api_key.服務代號(provider, 網址), 金鑰)
    for provider, 網址, 金鑰 in 服務們:                     # 每家讀到自己的
        assert api_key.取得(provider, 網址) == 金鑰
    api_key.清除("openai")                                  # 清掉一家，其他不受影響
    assert api_key.取得("openai_compatible", "https://api.openai.com/v1") is None
    assert api_key.取得("anthropic") == 甲金鑰
    assert api_key.取得("openai_compatible", "https://api.deepseek.com") == 丙金鑰
    assert api_key.取得("openai_compatible", "https://example.com/api/v1") == 丁金鑰
    assert api_key.取得("openai_compatible", "https://other.example.com/v1") is None    # 另一個相容服務是另一格


def test_各家預設環境變數不混用(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", 乙金鑰)
    assert api_key.取得("anthropic") is None                        # Claude 不會拿到 OpenAI 的金鑰
    assert api_key.取得("openai_compatible", "https://api.openai.com/v1") == 乙金鑰
    assert api_key.取得("openai_compatible", "https://api.deepseek.com") is None


def test_本機服務不需要金鑰():
    assert api_key.狀態("openai_compatible", "http://localhost:11434/v1") == api_key.不需要
    assert llm.檢查金鑰(dict(config.出廠預設(), provider="openai_compatible", base_url="http://localhost:11434/v1")) is None


def test_取得金鑰網址():
    assert api_key.取得網址("claude") == "https://platform.claude.com/settings/keys"
    assert api_key.取得網址("openai") == "https://platform.openai.com/api-keys"
    assert api_key.取得網址("deepseek") == "https://platform.deepseek.com/api_keys"
    assert api_key.取得網址("相容:example.com/v1") == ""


# ================= llm.py 改用新的讀取方式 =================
def test_llm呼叫模型用認證管理員的金鑰_優先於環境變數(假服務, monkeypatch):
    呼叫 = {}

    class 假訊息Anthropic(假Anthropic):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.messages = SimpleNamespace(create=lambda **k: SimpleNamespace(
                content=[SimpleNamespace(type="text", text="答")], usage=None, stop_reason="end_turn"))
            呼叫.update(kw)
    monkeypatch.setattr(anthropic, "Anthropic", 假訊息Anthropic)
    monkeypatch.setattr(llm, "PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "BASE_URL", "")
    monkeypatch.setattr(llm, "API_KEY_ENV", "ANTHROPIC_API_KEY")
    monkeypatch.setenv("ANTHROPIC_API_KEY", 環境金鑰)
    llm.call_llm("q", "m")
    assert 呼叫["api_key"] == 環境金鑰
    api_key.儲存("claude", 甲金鑰)
    llm.call_llm("q", "m")
    assert 呼叫["api_key"] == 甲金鑰
    assert llm.金鑰狀態() == "已儲存在這台電腦"


def test_llm檢查金鑰_白話_不含內部名詞(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "BASE_URL", "")
    monkeypatch.setattr(llm, "API_KEY_ENV", "ANTHROPIC_API_KEY")
    訊息 = llm.檢查金鑰()
    assert 訊息 == "尚未設定 API 金鑰：請到「設定」的「模型服務」貼上金鑰。"
    api_key.儲存("claude", 甲金鑰)
    assert llm.檢查金鑰() is None


# ================= 5. 測試連線（llm 層） =================
def test_測試連線_成功_只列出模型(假服務):
    結果, 說明 = llm.測試連線("anthropic", "", 甲金鑰)
    assert 結果 == llm.測試成功
    assert 說明 == "連線成功，Claude 的金鑰有效。（測試只列出模型清單，不會產生費用）"
    assert 假服務.甲.建立參數 == {"api_key": 甲金鑰, "max_retries": 0, "timeout": llm.測試逾時秒}
    結果, _ = llm.測試連線("openai_compatible", "https://api.deepseek.com", 丙金鑰)
    assert 結果 == llm.測試成功
    assert 假服務.乙.建立參數["base_url"] == "https://api.deepseek.com"


@pytest.mark.parametrize("provider,例外類別,結果,關鍵字", [
    ("anthropic", anthropic.AuthenticationError, "金鑰無效", "金鑰無效或沒有權限"),
    ("anthropic", anthropic.PermissionDeniedError, "金鑰無效", "金鑰無效或沒有權限"),
    ("anthropic", anthropic.APIConnectionError, "連不上", "連不上 Claude"),
    ("openai_compatible", openai.AuthenticationError, "金鑰無效", "金鑰無效或沒有權限"),
    ("openai_compatible", openai.APIConnectionError, "連不上", "連不上 OpenAI"),
])
def test_測試連線_金鑰無效與連不上_白話且不含金鑰(假服務, provider, 例外類別, 結果, 關鍵字):
    金鑰 = 甲金鑰 if provider == "anthropic" else 乙金鑰
    假 = 假服務.甲 if provider == "anthropic" else 假服務.乙
    假.例外 = 造例外(例外類別, f"invalid x-api-key {金鑰}")     # 伺服器的原文就算含金鑰也不能被帶出來
    得, 說明 = llm.測試連線(provider, "", 金鑰)
    assert 得 == 結果 and 關鍵字 in 說明
    assert 金鑰 not in 說明 and "invalid" not in 說明


# ================= 3. 設定框 =================
def _設定頁(台):
    台.開設定框()
    頁 = 台.設定框.頁
    頁.背景測試 = False
    return 頁


def _選服務(頁, 服務):
    w = 頁.服務選
    w.setCurrentIndex(w.findData(服務))


def test_設定框_金鑰欄遮蔽_眼睛暫時顯示(環境):
    頁 = _設定頁(環境["台"])
    from PySide6.QtWidgets import QLineEdit
    assert 頁.金鑰欄.echoMode() == QLineEdit.Password
    頁.眼睛鈕.setChecked(True)
    assert 頁.金鑰欄.echoMode() == QLineEdit.Normal
    頁.眼睛鈕.setChecked(False)
    assert 頁.金鑰欄.echoMode() == QLineEdit.Password
    assert 頁.金鑰欄.text() == ""                      # 已存的金鑰永遠不會放回輸入框


def test_設定框_切換服務後金鑰欄顯示對應狀態(環境, monkeypatch):
    頁 = _設定頁(環境["台"])
    assert 頁.金鑰字.text() == "Claude：尚未設定"
    assert "platform.claude.com/settings/keys" in 頁.取得連結.text() and 頁.取得連結.isVisibleTo(頁)
    assert "ANTHROPIC_API_KEY" in 頁.金鑰進階.text()
    assert not 頁.清除鈕.isEnabled()

    api_key.儲存("claude", 甲金鑰)
    monkeypatch.setenv("DEEPSEEK_API_KEY", 乙金鑰)
    頁.更新金鑰()
    assert 頁.金鑰字.text() == "Claude：已儲存在這台電腦"
    assert 頁.清除鈕.isEnabled() and "已儲存" in 頁.金鑰欄.placeholderText()

    _選服務(頁, "deepseek")                              # 換到 DeepSeek：顯示 DeepSeek 的狀態與連結
    assert 頁.金鑰字.text() == "DeepSeek：使用系統環境變數"
    assert "platform.deepseek.com/api_keys" in 頁.取得連結.text()
    assert "DEEPSEEK_API_KEY" in 頁.金鑰進階.text()
    assert not 頁.清除鈕.isEnabled()                      # 這台電腦沒存 DeepSeek 的金鑰，沒東西可清

    _選服務(頁, "claude")                                # 換回 Claude：原本存的還在
    assert 頁.金鑰字.text() == "Claude：已儲存在這台電腦"


def test_設定框_DeepSeek_其他相容服務_本機各自顯示(環境, 假服務):      # 假服務：本機網址會自動讀模型清單，不連真的 localhost
    台 = 環境["台"]
    for 網址, 預期字, 連結 in (("https://api.deepseek.com", "DeepSeek：尚未設定", "platform.deepseek.com/api_keys"),
                          ("https://example.com/api/v1", "OpenAI 相容服務（example.com/api/v1）：尚未設定", ""),
                          ("http://localhost:11434/v1", "本機模型服務：這個服務不需要金鑰", "")):
        config.寫入設定({"provider": "openai_compatible", "base_url": 網址})
        頁 = _設定頁(台)
        頁.載入()
        assert 頁.金鑰字.text() == 預期字
        assert (連結 in 頁.取得連結.text()) if 連結 else not 頁.取得連結.isVisibleTo(頁)
        assert 頁.金鑰欄.isEnabled() == ("不需要" not in 預期字)
    api_key.儲存("deepseek", 丙金鑰)
    config.寫入設定({"base_url": "https://api.deepseek.com"})
    頁.載入()
    assert 頁.金鑰字.text() == "DeepSeek：已儲存在這台電腦"


def test_設定框_按儲存才存金鑰_不按就不存(環境):
    台 = 環境["台"]
    頁 = _設定頁(台)
    頁.金鑰欄.setText(甲金鑰)
    台.設定框.close()                                     # 打了金鑰沒按儲存、沒按測試連線就關掉
    assert api_key.讀取已儲存("claude") is None
    頁 = _設定頁(台)
    assert 頁.金鑰欄.text() == ""                          # 重新打開：沒存的金鑰也清掉
    頁.金鑰欄.setText("  " + 甲金鑰 + "  ")
    頁.儲存()
    assert api_key.讀取已儲存("claude") == 甲金鑰         # 前後空白去掉
    assert 頁.狀態字.text() == "已儲存（舊的設定已備份）。金鑰已儲存在這台電腦。"
    assert 頁.金鑰欄.text() == "" and 頁.金鑰字.text() == "Claude：已儲存在這台電腦"
    assert 甲金鑰 not in 環境["設定檔"].read_text(encoding="utf-8")


def test_設定框_換服務後儲存_金鑰存到選的那一家(環境):
    頁 = _設定頁(環境["台"])
    _選服務(頁, "gemini")
    頁.金鑰欄.setText(乙金鑰)
    頁.儲存()
    assert api_key.讀取已儲存("gemini") == 乙金鑰 and api_key.讀取已儲存("claude") is None


def test_設定框_測試連線成功才存_失敗絕不存(環境, 假服務):
    頁 = _設定頁(環境["台"])
    頁.金鑰欄.setText(甲金鑰)
    假服務.甲.例外 = 造例外(anthropic.AuthenticationError)
    頁.測試連線()
    assert api_key.讀取已儲存("claude") is None
    assert 頁.金鑰訊息.text() == "金鑰無效或沒有權限。請確認金鑰有完整複製（前後沒有多空白）。（沒有儲存）"
    assert 頁.金鑰欄.text() == 甲金鑰                     # 留著讓使用者修改

    假服務.甲.例外 = 造例外(anthropic.APIConnectionError)
    頁.測試連線()
    assert api_key.讀取已儲存("claude") is None
    assert 頁.金鑰訊息.text() == "連不上 Claude。請確認網路連線，稍後再試一次。（沒有儲存）"

    假服務.甲.例外 = None
    頁.測試連線()
    assert api_key.讀取已儲存("claude") == 甲金鑰
    assert 頁.金鑰訊息.text() == "連線成功，Claude 的金鑰有效。（測試只列出模型清單，不會產生費用）已儲存在這台電腦。"
    assert 頁.金鑰欄.text() == "" and 頁.測試鈕.isEnabled()
    assert 頁.金鑰字.text() == "Claude：已儲存在這台電腦"


def test_設定框_空白時測試已存的金鑰_沒有就提示(環境, 假服務):
    頁 = _設定頁(環境["台"])
    頁.測試連線()
    assert 頁.金鑰訊息.text() == "請先貼上金鑰，再按「測試連線」。" and 假服務.甲.建立參數 is None
    api_key.儲存("claude", 甲金鑰)
    頁.測試連線()
    assert 假服務.甲.建立參數["api_key"] == 甲金鑰
    assert 頁.金鑰訊息.text().startswith("連線成功")


def test_設定框_背景執行緒測試連線(環境, 假服務):
    頁 = _設定頁(環境["台"])
    頁.背景測試 = True
    頁.金鑰欄.setText(甲金鑰)
    頁.測試連線()
    assert 冒煙.等(lambda: api_key.讀取已儲存("claude") == 甲金鑰, 5)
    assert 頁.金鑰訊息.text().startswith("連線成功")


def test_設定框_清除(環境, monkeypatch):
    頁 = _設定頁(環境["台"])
    api_key.儲存("claude", 甲金鑰)
    api_key.儲存("deepseek", 乙金鑰)
    頁.更新金鑰()
    頁.清除金鑰()
    assert api_key.讀取已儲存("claude") is None and api_key.讀取已儲存("deepseek") == 乙金鑰
    assert 頁.金鑰訊息.text() == "已清除這台電腦儲存的 Claude 金鑰。"
    assert 頁.金鑰字.text() == "Claude：尚未設定" and not 頁.清除鈕.isEnabled()
    monkeypatch.setenv("ANTHROPIC_API_KEY", 環境金鑰)
    api_key.儲存("claude", 甲金鑰)
    頁.更新金鑰()
    頁.清除金鑰()
    assert 頁.金鑰訊息.text() == "已清除這台電腦儲存的 Claude 金鑰。目前改用系統環境變數裡的金鑰。"
    assert 頁.金鑰字.text() == "Claude：使用系統環境變數"


# ================= 4. 啟動面板 =================
@pytest.fixture
def 真的檢查(monkeypatch):
    monkeypatch.setattr(llm, "檢查金鑰", 真檢查金鑰)


def _在視野內(頁, w):
    y = w.mapTo(頁.widget(), QPoint(0, 0)).y()
    上 = 頁.verticalScrollBar().value()
    return 上 <= y and y + w.height() <= 上 + 頁.viewport().height()


def test_啟動面板_沒有金鑰時顯示提示與按鈕_按下去打開設定框並捲到金鑰欄(環境, 真的檢查):
    台 = 環境["台"]
    啟 = 台.啟動面板
    啟.hide()
    啟.顯示()
    assert 啟.金鑰列.isVisible()
    assert 啟.金鑰字.text() == "尚未設定 API 金鑰" and 啟.金鑰鈕.text() == "設定金鑰"
    啟.金鑰鈕.click()
    QApplication.processEvents()
    頁 = 台.設定框.頁
    assert 台.設定框.isVisible()
    assert _在視野內(頁, 頁.金鑰列)


def test_啟動面板_有金鑰或本機服務就不顯示(環境, 真的檢查, monkeypatch):
    啟 = 環境["台"].啟動面板
    api_key.儲存("claude", 甲金鑰)
    啟.更新金鑰提示()
    assert not 啟.金鑰列.isVisible()
    api_key.清除("claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", 環境金鑰)       # 環境變數也算有
    啟.更新金鑰提示()
    assert not 啟.金鑰列.isVisible()
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    config.寫入設定({"provider": "openai_compatible", "base_url": "http://localhost:11434/v1"})
    啟.更新金鑰提示()
    assert not 啟.金鑰列.isVisible()


def test_啟動面板_儲存_測試連線成功_清除之後立刻更新(環境, 真的檢查, 假服務):
    台 = 環境["台"]
    啟 = 台.啟動面板
    啟.更新金鑰提示()
    assert 啟.金鑰列.isVisible()
    高 = 啟.height()
    頁 = _設定頁(台)
    頁.金鑰欄.setText(甲金鑰)
    頁.儲存()
    assert not 啟.金鑰列.isVisible() and 啟.height() < 高      # 提示收起，面板變矮
    頁.清除金鑰()
    assert 啟.金鑰列.isVisible()
    頁.金鑰欄.setText(甲金鑰)
    假服務.甲.例外 = 造例外(anthropic.AuthenticationError)
    頁.測試連線()
    assert 啟.金鑰列.isVisible()                               # 失敗：沒存，提示還在
    假服務.甲.例外 = None
    頁.測試連線()
    assert not 啟.金鑰列.isVisible()


# ================= 6. 金鑰不出現在任何輸出 =================
def test_任何輸出與檔案都不含金鑰(環境, 真的檢查, 假服務, capfd, monkeypatch):
    台 = 環境["台"]
    頁 = _設定頁(台)
    for 例外 in (造例外(anthropic.AuthenticationError, 甲金鑰), 造例外(anthropic.APIConnectionError, 甲金鑰), None):
        假服務.甲.例外 = 例外
        頁.金鑰欄.setText(甲金鑰)
        頁.測試連線()
    頁.金鑰欄.setText(甲金鑰)
    頁.儲存()
    頁.清除金鑰()
    api_key.儲存("claude", 甲金鑰)
    monkeypatch.setattr(llm, "PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "BASE_URL", "")
    monkeypatch.setattr(llm, "API_KEY_ENV", "ANTHROPIC_API_KEY")
    錯誤們 = [llm.金鑰狀態(), llm._金鑰訊息(), llm._連線訊息(), llm.未設定金鑰訊息]
    假服務.甲.例外 = 造例外(anthropic.AuthenticationError, 甲金鑰)
    錯誤們.append(llm.測試連線("anthropic", "", 甲金鑰)[1])
    config.印設定(*config.載入設定()[:2], llm.金鑰狀態())         # --show-config
    台.啟動面板.更新金鑰提示()

    介面字們 = [w.text() for w in 台.設定框.findChildren(QLabel) + 台.設定框.findChildren(QPushButton)]
    介面字們 += [w.toolTip() for w in 台.設定框.findChildren(QLabel)]
    介面字們 += [w.text() for w in 台.啟動面板.findChildren(QLabel)]
    輸出 = capfd.readouterr()
    檔案內容 = []
    for 路, _, 檔們 in os.walk(環境["暫存"]):              # 設定檔、備份、啟動紀錄（logs）等這次測試寫出的所有檔案
        for f in 檔們:
            with open(os.path.join(路, f), encoding="utf-8", errors="ignore") as 檔:
                檔案內容.append(檔.read())
    for 字 in [*錯誤們, *介面字們, 輸出.out, 輸出.err, *檔案內容]:
        for 金鑰 in 全部假金鑰:
            assert 金鑰 not in 字
    assert "API 金鑰：已儲存在這台電腦" in 輸出.out
