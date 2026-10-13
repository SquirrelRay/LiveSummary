"""模型服務與模型的下拉選單、單價未知、設定框大小（offscreen，不開真的視窗、不連網、不呼叫真模型）。
認證管理員一律用 conftest 的假後端；「列出模型」用假的 openai／anthropic client。
1. 選每個服務時自動帶入的值；切換服務時網址與模型不殘留。
2. 「其他（自己輸入）」、清單外沒附價格的模型：設定框費用表、啟動面板、膠囊、狀態列、結束訊息都顯示「單價未知，無法估算」。
3. 上網查證只在直接連 Claude 時可用（透過 OpenRouter 用 Claude 也不行）。
4. 舊 config.json（provider＋base_url＋model）正確對應。
5. 各家金鑰互不影響（含 OpenRouter、Gemini）。
6. 載入可用模型：成功、失敗、篩選；Ollama 讀本機模型。
7. 設定框預設大小不截斷文字（Windows 縮放 100%／125%／150% 時的螢幕大小）、記住大小、超出螢幕縮回。"""
import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import anthropic
import openai
import pytest
import test_介面冒煙 as 冒煙
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton

import api_key
import chat_translate
import config
import cost_estimate
import live_topics
import llm
import model_catalog as mc
import subtitle
import ui_state

qapp, 環境 = 冒煙.qapp, 冒煙.環境
未知字 = "單價未知，無法估算"


def 造例外(類別):
    return 類別.__new__(類別)


# ---------- 假的「列出模型」 ----------
class 假清單:
    模型們 = ()
    例外 = None
    建立參數 = None

    def __init__(self, **kw):
        type(self).建立參數 = kw
        self.models = SimpleNamespace(list=self._列出)

    def _列出(self, **kw):
        if type(self).例外:
            raise type(self).例外
        return list(type(self).模型們)


class 假OpenAI(假清單):
    pass


class 假Anthropic(假清單):
    pass


def 模(代號, 輸入=None, 輸出=None, 名稱=""):
    pricing = {"prompt": str(輸入 / 1e6), "completion": str(輸出 / 1e6)} if 輸入 is not None else None
    return SimpleNamespace(id=代號, name=名稱, pricing=pricing)


@pytest.fixture
def 假服務(monkeypatch):
    for 類 in (假OpenAI, 假Anthropic):
        類.模型們, 類.例外, 類.建立參數 = [], None, None
    monkeypatch.setattr(openai, "OpenAI", 假OpenAI)
    monkeypatch.setattr(anthropic, "Anthropic", 假Anthropic)
    return SimpleNamespace(乙=假OpenAI, 甲=假Anthropic)


def _頁(台):
    台.開設定框()
    頁 = 台.設定框.頁
    頁.背景測試 = False
    return 頁


def _選服務(頁, 代號):
    頁.服務選.setCurrentIndex(頁.服務選.findData(代號))


def _選模型(頁, 值):
    i = 頁.模型選.findData(值)
    assert i >= 0, 值
    頁.模型選.setCurrentIndex(i)


def _模型們(頁):
    return [頁.模型選.itemData(i) for i in range(頁.模型選.count()) if 頁.模型選.itemData(i)]


def _寫設定(環境, **改):
    內容 = json.loads(環境["設定檔"].read_text(encoding="utf-8"))
    內容.update(改)
    環境["設定檔"].write_text(json.dumps(內容, ensure_ascii=False), encoding="utf-8")


# ================= 目錄（純函式） =================
def test_每個服務都有推薦模型與建議_單價都有():
    for s in mc.服務們:
        if s["代號"] in ("ollama", mc.其他):
            assert s["模型們"] == []
            continue
        assert 2 <= len(s["模型們"]) <= 4, s["代號"]
        assert sum(m["建議"] for m in s["模型們"]) == 1
        for m in s["模型們"]:
            assert m["輸入"] > 0 and m["輸出"] > 0
    assert [s["代號"] for s in mc.服務們 if not s["實驗性"]] == ["claude"]


@pytest.mark.parametrize("provider,網址,服務", [
    ("anthropic", "", "claude"),
    ("anthropic", "https://api.anthropic.com", "claude"),
    ("anthropic", "https://api.deepseek.com/anthropic", mc.其他),          # Claude 寫法接別家：當成其他相容服務
    ("openai_compatible", "", mc.其他),                                     # OpenAI 直連暫時不列在選單：設定框當成其他相容服務
    ("openai_compatible", "https://api.openai.com/v1", mc.其他),
    ("openai_compatible", "https://api.deepseek.com", "deepseek"),
    ("openai_compatible", "https://openrouter.ai/api/v1", "openrouter"),
    ("openai_compatible", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini"),
    ("openai_compatible", "http://localhost:11434/v1", "ollama"),
    ("openai_compatible", "http://127.0.0.1:1234/v1", mc.其他),            # 別的本機服務（例如 LM Studio）
    ("openai_compatible", "https://my.server/v1", mc.其他),
    ("openai_compatible", "亂打的網址", mc.其他),
])
def test_舊設定對應服務(provider, 網址, 服務):
    assert mc.對應服務(provider, 網址) == 服務


def test_單價規則():
    基本 = dict(config.出廠預設())
    assert mc.單價(基本) == (0.10, 0.50)
    assert mc.單價(基本 | {"model": "claude-sonnet-5-5"}) == (2.0, 10.0)                  # 舊單價不沿用到別的模型
    assert mc.單價(基本 | {"model": "自己的模型"}) is None
    assert mc.單價(基本 | {"model": "自己的模型", "price_model": "自己的模型", "price_input": 1, "price_output": 2}) == (1, 2)
    assert mc.單價(基本 | {"provider": "openai_compatible", "base_url": "http://localhost:11434/v1", "model": "x"}) == (0, 0)
    assert mc.解析單價({"prompt": "0.0000001", "completion": "0.0000005"}) == (0.1, 0.5)
    assert mc.解析單價({"prompt": "-1", "completion": "-1"}) == (None, None)                 # 浮動價
    assert mc.解析單價(None) == (None, None)


# ================= 1. 選每個服務時自動帶入 =================
@pytest.mark.parametrize("服務,provider,網址,建議,連結", [
    ("claude", "anthropic", "", "claude-haiku-5-5", "https://platform.claude.com/settings/keys"),
    ("openrouter", "openai_compatible", "https://openrouter.ai/api/v1", "anthropic/claude-haiku-5.5", "https://openrouter.ai/keys"),
    ("deepseek", "openai_compatible", "https://api.deepseek.com", "deepseek-flash", "https://platform.deepseek.com/api_keys"),
    ("gemini", "openai_compatible", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-3.5-flash-lite",
     "https://aistudio.google.com/apikey"),
])
def test_選服務自動帶入網址_建議模型_金鑰欄位_取得金鑰連結(環境, 服務, provider, 網址, 建議, 連結):
    _寫設定(環境, price_model="")                       # 冒煙測試的設定檔把 Haiku 的單價改成 1／5；這裡要看官方單價
    頁 = _頁(環境["台"])
    if 服務 == "claude":
        _選服務(頁, "gemini")
    _選服務(頁, 服務)
    全 = 頁.讀全部()
    assert (全["provider"], 全["base_url"], 全["model"]) == (provider, 網址, 建議)
    m = mc.找模型(服務, 建議)
    assert (全["price_input"], 全["price_output"], 全["price_model"]) == (m["輸入"], m["輸出"], 建議)
    assert 頁.模型選.currentText().endswith("（建議）")
    assert not 頁.網址欄.isVisibleTo(頁) and not 頁.自訂模型欄.isVisibleTo(頁)       # 只有其他相容服務才有網址欄
    assert 頁.實驗標.isVisibleTo(頁) == (服務 != "claude")
    assert 頁.金鑰字.text() == f"{api_key.服務名稱(api_key.服務代號(provider, 網址))}：尚未設定"
    assert 連結 in 頁.取得連結.text()
    assert "查官方定價" in 頁.單價字.text() and "2026-10-13" in 頁.模型選.toolTip()
    推薦 = [x["代號"] for x in mc.推薦(服務)]
    assert _模型們(頁) == [*推薦, mc.自訂]                            # 最後一項是「其他（自己輸入）」


def test_實驗性標示的滑鼠提示(環境):
    頁 = _頁(環境["台"])
    _選服務(頁, "deepseek")
    for 提示 in (頁.實驗標.toolTip(), 頁.服務選.toolTip(), 頁.服務選.itemData(頁.服務選.findData("openrouter"), 0x03)):
        assert "提示詞是用 Claude 調整的" in 提示 and "不穩定" in 提示


def test_其他相容服務_只有它顯示網址欄_要填網址與模型(環境):
    頁 = _頁(環境["台"])
    _選服務(頁, mc.其他)
    assert 頁.網址欄.isVisibleTo(頁) and 頁.網址欄.text() == ""
    assert 頁.模型選.currentData() == mc.自訂 and 頁.自訂模型欄.isVisibleTo(頁)
    頁.儲存()
    assert 頁.狀態字.text().startswith("請填「服務網址」")
    頁.網址欄.setText("https://my.server/v1")
    頁.儲存()
    assert 頁.狀態字.text() == "模型名稱不能空白。"
    頁.自訂模型欄.setText("my-model")
    頁.儲存()
    存 = config.目前設定()
    assert (存["provider"], 存["base_url"], 存["model"], 存["price_model"]) == ("openai_compatible", "https://my.server/v1", "my-model", "")
    assert 頁.金鑰字.text() == "OpenAI 相容服務（my.server/v1）：尚未設定"


# ================= 1b. 切換服務不殘留 =================
def test_切換服務時網址與模型不殘留_切回來還原記住的(環境):
    _寫設定(環境, provider="openai_compatible", base_url="https://api.deepseek.com", model="deepseek-v4-pro",
          api_key_env="MY_DEEPSEEK_KEY", price_model="deepseek-v4-pro", price_input=9.0, price_output=9.0)
    頁 = _頁(環境["台"])
    assert 頁.目前服務() == "deepseek" and 頁.目前模型() == "deepseek-v4-pro"
    _選服務(頁, "claude")
    全 = 頁.讀全部()
    assert (全["provider"], 全["base_url"], 全["model"]) == ("anthropic", "", "claude-haiku-5-5")
    assert 全["api_key_env"] == "ANTHROPIC_API_KEY"                    # 舊服務自訂的環境變數名稱不殘留
    assert (全["price_input"], 全["price_output"], 全["price_model"]) == (0.10, 0.50, "claude-haiku-5-5")
    _選服務(頁, mc.其他)
    頁.網址欄.setText("https://my.server/v1")
    頁.自訂模型欄.setText("my-model")
    _選服務(頁, "gemini")
    全 = 頁.讀全部()
    assert (全["base_url"], 全["model"]) == (mc.服務("gemini")["網址"], "gemini-3.5-flash-lite")
    assert 頁.自訂模型欄.text() == "" and not 頁.網址欄.isVisibleTo(頁)
    _選服務(頁, mc.其他)
    assert 頁.網址欄.text() == "" and 頁.自訂模型欄.text() == ""          # 剛才打的網址、模型不殘留
    _選服務(頁, "deepseek")                                               # 切回記住的服務：還原記住的模型與環境變數
    assert 頁.目前模型() == "deepseek-v4-pro" and "api_key_env" not in 頁.讀全部()
    _選服務(頁, "claude")
    頁.儲存()
    存 = config.目前設定()
    assert (存["provider"], 存["base_url"], 存["model"], 存["api_key_env"]) == ("anthropic", "", "claude-haiku-5-5", "ANTHROPIC_API_KEY")


# ================= 2. 單價未知：所有地方都顯示「無法估算」 =================
def _全部未知(頁):
    表 = 頁.費用表
    開的 = [列 for 列 in 表[1:-1] if not 列[1].startswith("未開啟")]
    assert 開的 and all(列[1] == 未知字 for 列 in 開的), 表
    assert 表[-1][1] == 未知字
    assert 未知字 in 頁.聊天註.text()
    assert 頁.單價字.text().startswith(未知字)


def test_選其他自己輸入_設定框_啟動面板_比較表都顯示無法估算_不沿用舊單價(環境):
    台 = 環境["台"]
    頁 = _頁(台)
    _選模型(頁, mc.自訂)
    頁.自訂模型欄.setText("claude-未來的模型")
    _全部未知(頁)
    頁.儲存()
    存 = config.目前設定()
    assert 存["model"] == "claude-未來的模型" and 存["price_model"] == ""       # 舊的 1／5 單價不會被拿來用
    assert mc.單價(存) is None
    啟 = 台.啟動面板
    assert 啟.總費用.text() == f"每小時費用：{未知字}"
    assert all(列["合計"] == 未知字 for 列 in cost_estimate.比較表列們(啟._費用設定(), "balanced", True))


def test_單價未知_狀態列_膠囊_結束訊息都顯示無法估算(環境):
    台 = 環境["台"]
    台.橋.收到.emit("status", {"次數": 3, "輸入": 100, "輸出": 50, "費用": mc.未知})
    台.橋.收到.emit("status", {"翻譯次數": 2, "翻譯輸入": 1, "翻譯輸出": 1, "翻譯費用": mc.未知, "翻譯延遲": None})
    QApplication.processEvents()
    assert 台.費用藥丸.text() == f"呼叫 3 次 · 估算 {未知字}"
    assert 未知字 in 台.翻譯藥丸.text()
    assert 台.膠囊.總費用() == mc.未知 and 台.膠囊.用量短字() == 未知字
    assert 未知字 in 台.膠囊.提示文字()
    # 結束訊息：摘要、上網查證、逐句翻譯、聊天室翻譯
    llm.用量.update(次數=2, 輸入=10, 輸出=5, 缺token=0)
    assert llm.用量文字(None, None).endswith(f"估算費用：{未知字}")
    llm.查證用量.update(次數=1, 輸入=10, 輸出=5, 缺token=0, 搜尋=2)
    assert 未知字 in llm.查證用量文字(None, None)
    字幕 = subtitle.字幕器()
    字幕.單價 = (None, None)
    llm.翻譯用量.update(次數=1, 輸入=10, 輸出=5, 缺token=0)
    assert 字幕.費用() == mc.未知 and 未知字 in 字幕.統計文字()
    聊 = chat_translate.聊天翻譯器()
    聊.單價 = (None, None)
    llm.聊天翻譯用量.update(次數=1, 輸入=10, 輸出=5, 缺token=0)
    assert 聊.費用() == mc.未知 and 未知字 in 聊.統計文字()
    for u in (llm.用量, llm.翻譯用量, llm.聊天翻譯用量):
        u.update(次數=0, 輸入=0, 輸出=0, 缺token=0)
    llm.查證用量.update(次數=0, 輸入=0, 輸出=0, 缺token=0, 搜尋=0)


def test_引擎用設定的單價_查不到就送出未知(monkeypatch):
    送出們 = []
    monkeypatch.setattr(live_topics.events, "送出", lambda 種類, **內容: 送出們.append((種類, 內容)))
    monkeypatch.setitem(live_topics.單價, "輸入", None)
    monkeypatch.setitem(live_topics.單價, "輸出", None)
    monkeypatch.setattr(llm, "用量", {"次數": 1, "輸入": 10, "輸出": 5, "缺token": 0})
    live_topics.送狀態()
    assert 送出們[-1][1]["費用"] == mc.未知
    monkeypatch.setitem(live_topics.單價, "輸入", 1.0)
    monkeypatch.setitem(live_topics.單價, "輸出", 5.0)
    live_topics.送狀態()
    assert 送出們[-1][1]["費用"] == pytest.approx(10 / 1e6 + 25 / 1e6)


# ================= 3. 上網查證只有直接連 Claude =================
def test_選非Claude時上網查證停用並寫原因_切回Claude還原(環境):
    _寫設定(環境, web_verify=True)
    頁 = _頁(環境["台"])
    w = 頁.欄["web_verify"]
    assert w.isChecked() and w.isEnabled() and not 頁.查證原因.isVisibleTo(頁)
    for 服務 in ("openrouter", "deepseek", "gemini", "ollama", mc.其他):
        _選服務(頁, 服務)
        assert not w.isEnabled() and not w.isChecked(), 服務
        assert 頁.查證原因.isVisibleTo(頁)
    assert "只有直接連 Claude" in 頁.查證原因.text() and "透過 OpenRouter 用 Claude 也不支援" in 頁.查證原因.text()
    上網 = next(列 for 列 in 頁.費用表 if 列[0] == "上網查證")
    assert 上網[1] == "未開啟 $0"
    _選服務(頁, "claude")
    assert w.isEnabled() and w.isChecked()


def test_透過OpenRouter或別家網址的Claude都不支援上網查證(monkeypatch):
    出廠 = config.出廠預設()
    assert mc.支援上網查證(出廠)
    assert not mc.支援上網查證(出廠 | {"provider": "openai_compatible", "base_url": "https://openrouter.ai/api/v1",
                                    "model": "anthropic/claude-haiku-5.5"})
    assert not mc.支援上網查證(出廠 | {"base_url": "https://api.deepseek.com/anthropic"})
    assert cost_estimate.查證狀態(出廠 | {"web_verify": True, "provider": "openai_compatible",
                                     "base_url": "https://openrouter.ai/api/v1"})[0] is False
    monkeypatch.setattr(llm, "PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "BASE_URL", "https://api.deepseek.com/anthropic")
    assert not llm.支援上網查證()
    monkeypatch.setattr(llm, "BASE_URL", "")
    assert llm.支援上網查證()


# ================= 4. 舊 config.json 對應 =================
@pytest.mark.parametrize("舊,服務,模型值,自訂字", [
    ({"provider": "anthropic", "base_url": "", "model": "claude-sonnet-5-5"}, "claude", "claude-sonnet-5-5", ""),
    ({"provider": "anthropic", "base_url": "", "model": "claude-haiku-4-5"}, "claude", mc.自訂, "claude-haiku-4-5"),
    ({"provider": "openai_compatible", "base_url": "https://api.deepseek.com", "model": "deepseek-flash"},
     "deepseek", "deepseek-flash", ""),
    ({"provider": "openai_compatible", "base_url": "https://api.openai.com/v1", "model": "gpt-4o"}, mc.其他, mc.自訂, "gpt-4o"),
    ({"provider": "openai_compatible", "base_url": "", "model": "gpt-6-luna"}, mc.其他, mc.自訂, "gpt-6-luna"),
    ({"provider": "openai_compatible", "base_url": "https://my.server/v1", "model": "foo"}, mc.其他, mc.自訂, "foo"),
    ({"provider": "anthropic", "base_url": "https://api.deepseek.com/anthropic", "model": "deepseek-flash"},
     mc.其他, mc.自訂, "deepseek-flash"),
])
def test_舊config對應到服務與模型_不在清單就顯示其他自己輸入(環境, 舊, 服務, 模型值, 自訂字):
    _寫設定(環境, **舊)
    頁 = _頁(環境["台"])
    assert 頁.目前服務() == 服務
    assert 頁.模型選.currentData() == 模型值
    assert 頁.自訂模型欄.text() == 自訂字 and 頁.自訂模型欄.isVisibleTo(頁) == bool(自訂字)
    assert 頁.目前模型() == 舊["model"]
    if 服務 == mc.其他:
        assert 頁.網址欄.text() == 舊["base_url"]
    頁.儲存()                                                     # 直接儲存：服務網址與模型照舊（其他相容服務一律用相容寫法）
    存 = config.目前設定()
    assert 存["model"] == 舊["model"] and 存["base_url"] == (舊["base_url"] or mc.服務(服務)["網址"])


def test_舊config_ollama_先顯示記住的模型_再讀本機清單(環境, 假服務, monkeypatch):
    _寫設定(環境, provider="openai_compatible", base_url="http://localhost:11434/v1", model="gpt-oss:20b", api_key_env="")
    假服務.乙.模型們 = [模("qwen3:8b"), 模("gpt-oss:20b")]
    monkeypatch.setattr(冒煙.app.settings_page.設定頁, "背景測試", False)       # 打開設定框時自動讀 Ollama 的模型：直接執行
    頁 = _頁(環境["台"])
    assert 頁.目前服務() == "ollama" and 頁.目前模型() == "gpt-oss:20b"
    assert _模型們(頁) == ["gpt-oss:20b", "qwen3:8b", mc.自訂]          # 讀到本機的兩個模型，排序後放在推薦區
    assert 頁.載入訊息.text() == "已讀到這台電腦裡的 2 個模型。"
    assert 頁.單價字.text() == "本機模型，不花 API 費用"
    assert 頁.金鑰字.text() == "本機模型服務：這個服務不需要金鑰" and not 頁.金鑰欄.isEnabled()
    assert 假服務.乙.建立參數["base_url"] == "http://localhost:11434/v1"


def test_設定檔裡的服務種類不認得_改用預設不出錯(環境):
    _寫設定(環境, provider="亂寫", model="x")
    頁 = _頁(環境["台"])
    assert 頁.目前服務() == "claude" and 頁.目前模型() == "x"


# ================= 5. 各家金鑰互不影響 =================
def test_各家金鑰互不影響_含OpenRouter與Gemini(環境):
    頁 = _頁(環境["台"])
    金鑰們 = {"claude": "k-claude", "openrouter": "k-or", "deepseek": "k-ds", "gemini": "k-gm"}
    for 服務, 金鑰 in 金鑰們.items():
        _選服務(頁, 服務)
        頁.金鑰欄.setText(金鑰)
        頁.儲存()
    for 服務, 金鑰 in 金鑰們.items():
        assert api_key.讀取已儲存(服務) == 金鑰
        _選服務(頁, 服務)
        assert 頁.金鑰字.text().endswith("：已儲存在這台電腦")
    _選服務(頁, "gemini")
    頁.清除金鑰()
    assert api_key.讀取已儲存("gemini") is None
    assert all(api_key.讀取已儲存(k) == v for k, v in 金鑰們.items() if k != "gemini")


# ================= 6. 載入可用模型 =================
def test_載入可用模型_成功_放進進階區塊_可篩選_OpenRouter單價自動帶入(環境, 假服務):
    頁 = _頁(環境["台"])
    _選服務(頁, "openrouter")
    api_key.儲存("openrouter", "k-or")
    假服務.乙.模型們 = ([模("anthropic/claude-haiku-5.5", 0.1, 0.5), 模("vendor/有價格", 0.2, 0.8, "Vendor: 有價格"),
                    模("vendor/浮動價"), 模("other/特別模型", 1.0, 2.0)]
                   + [模(f"bulk/m{i:03d}", 0.01, 0.02) for i in range(400)])
    頁.載入可用模型()
    assert 頁.載入訊息.text().startswith("已載入 404 個模型")
    assert 假服務.乙.建立參數["api_key"] == "k-or"
    assert 頁.篩選欄.isVisibleTo(頁)
    值們 = _模型們(頁)
    assert 值們[:4] == [m["代號"] for m in mc.推薦(頁.目前服務())]          # 推薦在前
    assert 值們.count("anthropic/claude-haiku-5.5") == 1                    # 推薦的不重複列
    assert len(值們) == 4 + mc_上限() + 1 and 值們[-1] == mc.自訂           # 最多放 300 個，其餘要篩選
    文字們 = [頁.模型選.itemText(i) for i in range(頁.模型選.count())]
    assert any(t.startswith("還有 ") for t in 文字們)
    頁.篩選欄.setText("特別")
    assert _模型們(頁) == [*[m["代號"] for m in mc.推薦("openrouter")], "other/特別模型", mc.自訂]
    _選模型(頁, "other/特別模型")
    assert "服務的模型清單附的單價" in 頁.單價字.text()
    全 = 頁.讀全部()
    assert (全["model"], 全["price_input"], 全["price_output"], 全["price_model"]) == ("other/特別模型", 1.0, 2.0, "other/特別模型")
    頁.篩選欄.setText("浮動")
    _選模型(頁, "vendor/浮動價")                                       # 清單沒附價格：單價未知
    _全部未知(頁)
    assert 頁.讀全部()["price_model"] == ""


def mc_上限():
    import settings_page
    return settings_page.清單上限


def test_載入可用模型_沒有金鑰_金鑰無效_連不上_白話說明(環境, 假服務):
    頁 = _頁(環境["台"])
    _選服務(頁, "deepseek")
    頁.載入可用模型()
    assert 頁.載入訊息.text() == "還沒有這個服務的 API 金鑰：請先在下面貼上金鑰，再按「載入可用模型」。"
    assert 假服務.乙.建立參數 is None                                    # 沒有金鑰就不連線
    api_key.儲存("deepseek", "k-ds")
    假服務.乙.例外 = 造例外(openai.AuthenticationError)
    頁.載入可用模型()
    assert 頁.載入訊息.text().startswith("金鑰無效或沒有權限")
    假服務.乙.例外 = 造例外(openai.APIConnectionError)
    頁.載入可用模型()
    assert 頁.載入訊息.text() == "連不上 DeepSeek。請確認網路連線，稍後再試一次。"
    assert _模型們(頁) == [*[m["代號"] for m in mc.推薦("deepseek")], mc.自訂]        # 失敗不動選單
    _選服務(頁, mc.其他)
    頁.載入可用模型()
    assert 頁.載入訊息.text() == "請先填「服務網址」，再按「載入可用模型」。"


def test_Claude也能載入可用模型(環境, 假服務):
    頁 = _頁(環境["台"])
    api_key.儲存("claude", "k-claude")
    假服務.甲.模型們 = [SimpleNamespace(id="claude-haiku-5-5", display_name="Claude Haiku 5.5"),
                    SimpleNamespace(id="claude-fable-5-1", display_name="Claude Fable 5.1")]
    頁.載入可用模型()
    assert "claude-fable-5-1" in _模型們(頁) and 頁.目前模型() == "claude-haiku-5-5"
    _選模型(頁, "claude-fable-5-1")
    assert 頁.單價字.text().startswith(未知字)                            # 不在推薦清單、Claude 清單也沒附價格


def test_Ollama_沒有下載模型_或沒開(環境, 假服務):
    頁 = _頁(環境["台"])
    _選服務(頁, "ollama")                                               # 選了就自動讀本機模型
    assert 頁.載入訊息.text().startswith("Ollama 裡還沒有下載任何模型") and "ollama pull" in 頁.載入訊息.text()
    assert 頁.模型選.currentData() == mc.自訂
    頁.儲存()
    assert 頁.狀態字.text() == "請先選擇模型（Ollama 要先下載模型）。"
    假服務.乙.例外 = 造例外(openai.APIConnectionError)
    頁.載入可用模型()
    assert 頁.載入訊息.text() == "連不上 Ollama。請先打開 Ollama，再按「載入可用模型」。"
    假服務.乙.例外 = None
    假服務.乙.模型們 = [模("llama:8b")]
    頁.載入可用模型()
    assert 頁.目前模型() == "llama:8b"                                   # 讀到後自動選第一個
    頁.儲存()
    存 = config.目前設定()
    assert (存["base_url"], 存["model"], mc.單價(存)) == ("http://localhost:11434/v1", "llama:8b", (0.0, 0.0))


def test_載入中換了服務_舊清單不套用(環境, 假服務):
    頁 = _頁(環境["台"])
    頁._載入模型完成(("deepseek", "https://api.deepseek.com", llm.測試成功, "", [{"代號": "x", "名稱": "", "輸入": None, "輸出": None}]))
    assert "x" not in _模型們(頁)


# ================= 7. 設定框大小 =================
螢幕們 = {"100%": QRect(0, 0, 1920, 1040), "125%": QRect(0, 0, 1536, 824), "150%": QRect(0, 0, 1280, 680)}


def _截斷的(框):
    """預設大小下被截斷的文字元件（勾選框、按鈕、不換行的標籤寬度小於它需要的寬度）。"""
    壞 = []
    for w in 框.findChildren(QCheckBox) + 框.findChildren(QPushButton) + 框.findChildren(QLabel):
        if not w.isVisibleTo(框) or (isinstance(w, QLabel) and w.wordWrap()) or not w.text():
            continue
        if w.width() < w.sizeHint().width() - 1:
            壞.append((w.text(), w.width(), w.sizeHint().width()))
    return 壞


@pytest.mark.parametrize("縮放", list(螢幕們))
def test_設定框預設大小_所有文字按鈕都不截斷(環境, 縮放):
    台 = 環境["台"]
    台.開設定框()
    框 = 台.設定框
    框.close()
    螢 = 螢幕們[縮放]
    框.打開(螢)
    QApplication.processEvents()
    assert 框.width() <= 螢.width() and 框.height() <= 螢.height()
    assert 框.頁.horizontalScrollBar().maximum() == 0                  # 不需要橫捲軸
    assert _截斷的(框) == []
    for 服務 in ("openrouter", mc.其他):                                # 換服務（多了實驗性標示、網址欄）也不截斷
        _選服務(框.頁, 服務)
        QApplication.processEvents()
        assert _截斷的(框) == [], 服務


def test_設定框記住使用者拉的大小_下次打開還是那個大小(環境):
    台 = 環境["台"]
    台.開設定框()
    框 = 台.設定框
    螢 = 螢幕們["100%"]
    框.close()
    框.打開(螢)
    框.resize(1000, 650)                                               # 使用者拉大／縮小
    QApplication.processEvents()
    框.close()
    assert ui_state.讀設定框大小() == (1000, 650)
    框.打開(螢)
    assert (框.width(), 框.height()) == (1000, 650)
    框.close()
    框.打開(螢)                                                         # 沒再拉：不覆蓋記住的大小
    框.close()
    assert ui_state.讀設定框大小() == (1000, 650)


def test_記住的大小超出目前螢幕_自動縮回螢幕內(環境):
    台 = 環境["台"]
    台.開設定框()
    框 = 台.設定框
    框.close()
    ui_state.存設定框大小(3000, 2000)
    螢 = 螢幕們["150%"]
    框.打開(螢)
    assert 框.width() <= 螢.width() - 2 * 框.螢幕邊距 and 框.height() <= 螢.height() - 2 * 框.螢幕邊距
    assert 螢.contains(框.geometry())


def test_記住的大小壞掉就用預設(環境):
    ui_state._更新介面設定(設定框大小=["寬", -1])
    assert ui_state.讀設定框大小() is None


# ================= 修正：OpenAI 直連暫時隱藏、OpenRouter 說明、DeepSeek 單價、Gemini 建議 =================
def test_模型服務選單不列OpenAI_目錄與開關保留(環境, monkeypatch):
    頁 = _頁(環境["台"])
    名們 = [頁.服務選.itemText(i) for i in range(頁.服務選.count())]
    assert not any("OpenAI" in 名 and "OpenRouter" not in 名 and "相容" not in 名 for 名 in 名們)
    assert 頁.服務選.findData("openai") < 0
    assert mc.服務("openai")["模型們"] and mc.服務("openai")["金鑰"] == "openai"           # 目錄資料保留
    assert mc.OpenAI直連顯示在選單 is False
    monkeypatch.setitem(mc.服務("openai"), "選單顯示", True)                              # 開關：改成 True 就恢復
    頁2 = type(頁)(頁.主)
    assert 頁2.服務選.findData("openai") >= 0
    頁2.deleteLater()


def test_OpenRouter說明提到可以透過它用GPT等其他家模型(環境):
    頁 = _頁(環境["台"])
    assert not 頁.服務說明.isVisibleTo(頁)
    _選服務(頁, "openrouter")
    assert 頁.服務說明.isVisibleTo(頁) and "想用 GPT 等其他家的模型，可以透過 OpenRouter" in 頁.服務說明.text()
    _選服務(頁, "deepseek")
    assert not 頁.服務說明.isVisibleTo(頁)


@pytest.mark.parametrize("網址", ["https://api.openai.com/v1", ""])
def test_舊設定已是OpenAI_照常能讀能用_設定框顯示其他相容服務並帶入原網址(環境, 網址):
    _寫設定(環境, provider="openai_compatible", base_url=網址, model="gpt-6-luna", api_key_env="OPENAI_API_KEY",
          price_model="", price_input=9.0, price_output=9.0)
    api_key.儲存("openai", "k-oa")
    設定 = config.目前設定()
    assert mc.對應服務(設定["provider"], 設定["base_url"]) == mc.其他                      # 設定框當成其他相容服務
    assert mc.對應服務(設定["provider"], 設定["base_url"], 含隱藏=True) == "openai"         # 但金鑰與單價還認得
    assert mc.單價(設定) == (0.10, 0.50)                                                   # 費用估算照常（官方單價，不是舊的 9／9）
    llm.套用設定(設定)
    assert llm._金鑰() == "k-oa" and llm.檢查金鑰() is None                                # 呼叫模型用的金鑰照常讀得到
    頁 = _頁(環境["台"])
    assert 頁.目前服務() == mc.其他 and 頁.網址欄.text() == 網址 and 頁.網址欄.isVisibleTo(頁)
    assert 頁.目前模型() == "gpt-6-luna" and 頁.金鑰字.text() == "OpenAI：已儲存在這台電腦"
    assert "0.1" in 頁.單價字.text() and 未知字 not in 頁.單價字.text()                      # 設定框的單價與實際估算一致
    assert not any(列[1] == 未知字 for 列 in 頁.費用表)
    頁.儲存()                                                                              # 儲存不出錯、網址與模型照舊
    存 = config.目前設定()
    assert (存["provider"], 存["base_url"], 存["model"]) == ("openai_compatible", 網址, "gpt-6-luna")
    assert mc.單價(存) == (0.10, 0.50)


def test_OpenRouter的DeepSeek單價不低估_備註說明供應商差異():
    m = mc.找模型("openrouter", "deepseek/deepseek-v4.1-flash")
    assert (m["輸入"], m["輸出"]) == (0.30, 1.20) and "三十幾家供應商" in m["備註"] and "0.0438" in m["備註"]
    直連 = mc.找模型("deepseek", "deepseek-flash")
    assert (直連["輸入"], 直連["輸出"]) == (0.30, 1.20)                                       # 尖峰價；離峰半價


def test_OpenRouter清單價格提示是最便宜供應商_實際可能較高(環境, 假服務):
    頁 = _頁(環境["台"])
    _選服務(頁, "openrouter")
    api_key.儲存("openrouter", "k-or")
    假服務.乙.模型們 = [模("vendor/某模型", 0.0438, 0.1752)]
    頁.載入可用模型()
    _選模型(頁, "vendor/某模型")
    assert "最便宜供應商的價格" in 頁.單價字.text() and "可能較高" in 頁.單價字.text()


def test_Gemini建議是3點5_FlashLite_舊的3點1標明停用日期():
    assert mc.建議模型("gemini") == "gemini-3.5-flash-lite"
    舊 = mc.找模型("gemini", "gemini-3.1-flash-lite")
    assert not 舊["建議"] and "2027-05" in 舊["說明"] and "2027-05-07" in 舊["備註"] and "gemini-3.5-flash-lite" in 舊["備註"]
