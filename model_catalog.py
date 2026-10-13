# 模型服務與推薦模型的目錄（純 Python，不碰介面）：設定框的兩個下拉選單、舊設定的對應、估算費用用的單價都從這裡讀。
# 服務網址、模型代號、單價都是 2026-10-13 查各家官方文件（來源寫在每個服務旁邊）；換代時改這裡就好。
# 單價：每百萬 token 美元（標準價，不含批次、快取等折扣）。查不到的填 None → 費用一律顯示「單價未知，無法估算」。
import api_key

查證日期 = "2026-10-13"
未知 = "單價未知"                    # 費用的特別值：單價未知（和 None =「拿不到 token 數」分開）
未知字 = "單價未知，無法估算"
其他 = "其他"                        # 服務：其他相容服務（自己填網址）
自訂 = "__自訂__"                    # 模型選單：「其他（自己輸入）」那一項的值
實驗說明 = ("實驗性：本工具的提示詞是用 Claude 調整的，其他模型的摘要格式與翻譯品質可能不穩定"
          "（例如格式跑掉、漏翻）。")


def 模型項(代號, 名稱, 說明, 輸入, 輸出, 建議=False, 備註=""):
    return {"代號": 代號, "名稱": 名稱, "說明": 說明, "輸入": 輸入, "輸出": 輸出, "建議": 建議, "備註": 備註}


服務們 = [
    # 來源：platform.claude.com/docs/en/about-claude/models/overview、/about-claude/pricing
    {"代號": "claude", "名稱": "Claude", "說明": "", "provider": "anthropic", "網址": "", "金鑰": "claude",
     "實驗性": False, "模型們": [
         模型項("claude-haiku-5-5", "Claude Haiku 5.5", "便宜、快", 0.10, 0.50, 建議=True,
             備註="提示詞超過 10 萬 token 時較貴（本工具的提示詞遠低於此）"),
         模型項("claude-sonnet-5-5", "Claude Sonnet 5.5", "較準，約貴 20 倍", 2.0, 10.0),
         模型項("claude-opus-5-5", "Claude Opus 5.5", "最準，約貴 40 倍", 4.0, 20.0),
     ]},
    # 來源：openrouter.ai/docs/quickstart（網址）、openrouter.ai/docs/api-keys（金鑰）、
    #       openrouter.ai/api/v1/models（模型代號與單價；官方說明 pricing 是「每 token 美元」）
    {"代號": "openrouter", "名稱": "OpenRouter", "說明": "一把金鑰用多家模型", "provider": "openai_compatible",
     "網址": "https://openrouter.ai/api/v1", "金鑰": "openrouter", "實驗性": True, "模型們": [
         模型項("anthropic/claude-haiku-5.5", "Claude Haiku 5.5", "便宜、快", 0.10, 0.50, 建議=True),
         模型項("anthropic/claude-sonnet-5.5", "Claude Sonnet 5.5", "較準、較貴", 2.0, 10.0),
         模型項("google/gemini-3.8-flash", "Gemini 3.8 Flash", "Google 的模型", 0.75, 3.75),
         模型項("deepseek/deepseek-v4.1-flash", "DeepSeek V4.1 Flash", "非常便宜", 0.0438, 0.1752),
     ]},
    # 來源：developers.openai.com/api/docs/models、/api/docs/pricing（Standard、short context）
    {"代號": "openai", "名稱": "OpenAI", "說明": "", "provider": "openai_compatible",
     "網址": "https://api.openai.com/v1", "金鑰": "openai", "實驗性": True, "模型們": [
         模型項("gpt-6-luna", "GPT-6 Luna", "便宜、快", 0.10, 0.50, 建議=True),
         模型項("gpt-6.1-sol", "GPT-6.1 Sol", "較準、較貴", 2.0, 10.0),
         模型項("gpt-6-astra", "GPT-6 Astra", "最準、最貴", 10.0, 50.0),
     ]},
    # 來源：api-docs.deepseek.com、api-docs.deepseek.com/quick_start/pricing（尖峰價；離峰半價，這裡用較高的尖峰價估算）
    {"代號": "deepseek", "名稱": "DeepSeek", "說明": "", "provider": "openai_compatible",
     "網址": "https://api.deepseek.com", "金鑰": "deepseek", "實驗性": True, "模型們": [
         模型項("deepseek-flash", "DeepSeek V4.1 Flash", "便宜、快", 0.30, 1.20, 建議=True,
             備註="尖峰時段價；離峰（台灣時間晚上等）半價"),
         模型項("deepseek-v4-pro", "DeepSeek V4 Pro", "較準、較貴", 1.32, 3.96, 備註="尖峰時段價；離峰半價"),
     ]},
    # 來源：ai.google.dev/gemini-api/docs/openai（網址、金鑰）、/docs/models、/docs/pricing（付費方案標準價）
    {"代號": "gemini", "名稱": "Google Gemini", "說明": "", "provider": "openai_compatible",
     "網址": "https://generativelanguage.googleapis.com/v1beta/openai/", "金鑰": "gemini", "實驗性": True, "模型們": [
         模型項("gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite", "便宜、快", 0.30, 2.50, 建議=True),
         模型項("gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite", "最便宜", 0.25, 1.50),
         模型項("gemini-3.8-flash", "Gemini 3.8 Flash", "較準、較貴", 0.75, 3.75,
             備註="官方公告 2027-01-01 起漲為輸入 1.50／輸出 7.50"),
     ]},
    # 來源：docs.ollama.com/api/openai-compatibility；推薦清單 = 本機已下載的模型（列出模型讀出來），不花錢
    {"代號": "ollama", "名稱": "Ollama", "說明": "本機，不用金鑰", "provider": "openai_compatible",
     "網址": "http://localhost:11434/v1", "金鑰": api_key.本機, "實驗性": True, "模型們": []},
    {"代號": 其他, "名稱": "其他相容服務", "說明": "自己填網址", "provider": "openai_compatible",
     "網址": "", "金鑰": None, "實驗性": True, "模型們": []},
]
_依代號 = {s["代號"]: s for s in 服務們}


def 服務(代號):
    return _依代號[代號]


def 服務顯示名(代號):
    s = 服務(代號)
    return s["名稱"] + (f"（{s['說明']}）" if s["說明"] else "")


def 推薦(代號):
    return list(服務(代號)["模型們"])


def 建議模型(代號):
    return next((m["代號"] for m in 服務(代號)["模型們"] if m["建議"]), "")


def 找模型(服務代號, 模型):
    return next((m for m in 服務(服務代號)["模型們"] if m["代號"] == 模型), None)


def 模型顯示名(m):
    return f"{m['名稱']}：{m['說明']}" + ("（建議）" if m["建議"] else "")


def 單價字(輸入, 輸出, 日期=查證日期):
    if 輸入 is None or 輸出 is None:
        return "單價未知，無法估算費用"
    來源 = f"，{日期} 查官方定價" if 日期 else ""
    return f"單價：輸入 US${輸入:g}／輸出 US${輸出:g}（每百萬 token{來源}）"


# ---- 設定 ⇄ 服務 ----
def 對應服務(provider, base_url=""):
    """舊設定（provider＋base_url）→ 服務代號。對不到就是「其他相容服務」，不會出錯。"""
    網址 = (base_url or "").strip()
    鑰 = api_key.服務代號(provider, 網址)
    if provider != "openai_compatible":
        return "claude" if 鑰 == "claude" else 其他
    if 鑰 == api_key.本機:
        return "ollama" if ":11434" in 網址 else 其他
    if 鑰 in ("openai", "deepseek", "openrouter", "gemini"):
        return 鑰
    return 其他


def 設定的服務(設定):
    return 對應服務(設定.get("provider", ""), 設定.get("base_url", ""))


def 服務設定(代號, 網址=""):
    """選了這個服務要寫進設定的 provider 與 base_url（其他相容服務用使用者填的網址）。"""
    s = 服務(代號)
    return {"provider": s["provider"], "base_url": (網址 or "").strip() if 代號 == 其他 else s["網址"]}


def 支援上網查證(設定):
    """上網查證只有直接連 Claude 官方時可用（透過 OpenRouter 用 Claude 也不行）。"""
    return 設定.get("provider") == "anthropic" and api_key.服務代號("anthropic", 設定.get("base_url", "")) == "claude"


def _是數字(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


def 單價(設定):
    """估算費用用的 (輸入, 輸出) 單價；查不到回傳 None（費用顯示「單價未知，無法估算」，不沿用舊單價）。
    順序：設定裡的單價有註明是這個模型的（price_model）→ 推薦清單的官方單價 → 本機服務 0 → 查不到。"""
    模型 = 設定.get("model", "")
    if 設定.get("price_model") == 模型 and 模型 and _是數字(設定.get("price_input")) and _是數字(設定.get("price_output")):
        return float(設定["price_input"]), float(設定["price_output"])
    代號 = 設定的服務(設定)
    m = 找模型(代號, 模型)
    if m and m["輸入"] is not None and m["輸出"] is not None:
        return m["輸入"], m["輸出"]
    if api_key.服務代號(設定.get("provider", ""), 設定.get("base_url", "")) == api_key.本機:
        return 0.0, 0.0                       # 本機模型不花 API 費用
    return None


def 費用字(費用, 位數=3):
    """狀態列、膠囊用：None = 拿不到 token 數；未知 = 單價未知。"""
    if 費用 is None:
        return "無法計算"
    if 費用 == 未知:
        return 未知字
    return f"${費用:.{位數}f}"


def 算費用(輸入token, 輸出token, 單價們):
    """單價們：(輸入, 輸出) 或 None；None / 有 None → 未知。"""
    if not 單價們 or 單價們[0] is None or 單價們[1] is None:
        return 未知
    return 輸入token / 1e6 * 單價們[0] + 輸出token / 1e6 * 單價們[1]


def 解析單價(pricing):
    """OpenRouter 模型清單的 pricing（每 token 美元的字串）→ 每百萬 token 的 (輸入, 輸出)；沒有或負數（浮動價）→ (None, None)。"""
    try:
        取 = pricing.get if isinstance(pricing, dict) else (lambda k: getattr(pricing, k, None))
        輸入, 輸出 = float(取("prompt")) * 1e6, float(取("completion")) * 1e6
    except (TypeError, ValueError, AttributeError):
        return None, None
    if 輸入 < 0 or 輸出 < 0:
        return None, None
    return round(輸入, 6), round(輸出, 6)
