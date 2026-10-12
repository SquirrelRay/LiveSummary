# 呼叫語言模型：整個專案只有這個檔案會碰模型 API
# 支援兩種寫法（在 config.json 的 provider 切換）：
#   "anthropic"          ：Claude（預設）
#   "openai_compatible"  ：OpenAI、DeepSeek、Ollama 等，靠 base_url 與 model 區分
import os
import sys

import config

# 這幾個值由 套用設定() 依 config.json 填入；沒填就是 config.py 的出廠預設（= 原本只用 Claude 的行為）
PROVIDER = config.出廠預設()["provider"]
BASE_URL = config.出廠預設()["base_url"]           # 空字串 = 用該家的預設網址
API_KEY_ENV = config.出廠預設()["api_key_env"]     # 金鑰放在哪個環境變數；空字串 = 不需要金鑰（例如 Ollama）
MAX_TOKENS = 4000                 # 思考也會佔用額度，留大一點避免文字被截斷
翻譯_MAX_TOKENS = 600             # 逐句翻譯：關掉思考後只剩譯文，一批 4 到 8 句這樣就夠用
聊天翻譯_MAX_TOKENS = 1500        # 聊天室翻譯：一批最多 40 則短留言

# 累計 API 呼叫次數與 token（給 live_topics.py 統計用）
# 缺token：有幾次呼叫拿不到 token 數（有就無法計算總量與費用）
用量 = {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0}
# 逐句字幕翻譯另外算（app.py 的字幕疊加層才會用到），不和摘要的用量混在一起
翻譯用量 = {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0}
# 聊天室翻譯（chat_translate.py）也另外算
聊天翻譯用量 = {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0}
_用量名 = {"摘要": "用量", "翻譯": "翻譯用量", "聊天翻譯": "聊天翻譯用量"}     # 類別 → 用哪一份用量（用名字查，測試換掉整份也照樣記）
翻譯類 = ("翻譯", "聊天翻譯")       # 關閉延伸思考、限制輸出長度的類別
摘要_思考 = config.出廠預設()["summary_thinking"]      # False = 摘要相關呼叫關閉延伸思考（config.json 的 summary_thinking）
最後停止原因 = ""     # 最近一次摘要或逐句翻譯回答的停止原因（max_tokens = 被截斷），翻譯失敗時寫進紀錄；聊天室翻譯不寫這裡
停止原因們 = {}       # 類別 → 該類別最近一次回答的停止原因（兩條翻譯執行緒各記各的，不會互相覆蓋）


class 模型錯誤(Exception):
    """呼叫模型時遇到「繼續跑也沒用」的問題。收到這個就該立刻停下來。"""


class 金鑰錯誤(模型錯誤):
    """API 金鑰無效或沒有權限。"""


class 連線錯誤(模型錯誤):
    """連不上模型伺服器（網路斷了、base_url 打錯、Ollama 沒開）。"""


class 限速錯誤(Exception):
    """API 速率限制（429）。只有聊天室翻譯會收到（其他類別維持原本的錯誤），聊天室翻譯收到就暫停一陣子。"""


def 用量表(類別):
    """這個類別的用量 dict（摘要、翻譯、聊天翻譯各一份）。"""
    return globals()[_用量名.get(類別, "用量")]


def 套用設定(設定):
    """設定：config.載入設定() 讀好的設定（dict）。"""
    global PROVIDER, BASE_URL, API_KEY_ENV
    PROVIDER = 設定["provider"]
    BASE_URL = 設定["base_url"].strip()
    API_KEY_ENV = 設定["api_key_env"].strip()
    global 摘要_思考
    摘要_思考 = 設定.get("summary_thinking", config.出廠預設()["summary_thinking"])


def 金鑰狀態():
    """給 --show-config 用，不顯示金鑰內容。"""
    if not API_KEY_ENV:
        return "不需要（api_key_env 留空）"
    return "已設定" if os.environ.get(API_KEY_ENV) else "未設定"


def 檢查金鑰():
    """開始前檢查金鑰有沒有設定。沒問題回傳 None，有問題回傳一句中文說明。"""
    if API_KEY_ENV and not os.environ.get(API_KEY_ENV):
        return f"找不到 API 金鑰：請先設定環境變數 {API_KEY_ENV}（說明見 README.txt）。"
    return None


def _金鑰訊息():
    return f"API 金鑰無效或沒有權限，已停止。請確認環境變數 {API_KEY_ENV} 是有效的金鑰後重新執行。"


def _連線訊息():
    網址 = BASE_URL or "該服務的預設網址"
    return (f"連不上模型伺服器（{網址}），已停止。請確認網路與 config.json 的 base_url；"
            "用 Ollama 的話，請先把 Ollama 打開。")


def _記用量(輸入, 輸出, 類別="摘要"):
    u = 用量表(類別)
    標 = f"[{類別} token 用量]" if 類別 in 翻譯類 else "[token 用量]"
    u["次數"] += 1
    if 輸入 is None or 輸出 is None:
        u["缺token"] += 1
        print(f"{標} 這個服務沒有回報 token 數（無法計算）", file=sys.stderr)
        return
    u["輸入"] += 輸入
    u["輸出"] += 輸出
    print(f"{標} 輸入 {輸入}，輸出 {輸出}", file=sys.stderr)


def _金鑰():
    return os.environ.get(API_KEY_ENV) if API_KEY_ENV else None


def _最多token(類別):
    return {"翻譯": 翻譯_MAX_TOKENS, "聊天翻譯": 聊天翻譯_MAX_TOKENS}.get(類別, MAX_TOKENS)


def _記停止原因(類別, 原因):
    global 最後停止原因
    停止原因們[類別] = 原因
    if 類別 != "聊天翻譯":          # 聊天室翻譯在另一條執行緒：不覆蓋逐句翻譯與摘要讀的這一格
        最後停止原因 = 原因


def _問_anthropic(提示詞, 模型, 類別):
    # 翻譯、聊天翻譯：關閉延伸思考、限制輸出長度（省錢）；摘要維持原樣
    # 聊天翻譯：不自動重試（max_retries=0），碰到速率限制直接丟出 限速錯誤，由聊天室翻譯自己暫停
    import anthropic
    參數 = {}
    if API_KEY_ENV:
        參數["api_key"] = _金鑰()
    if BASE_URL:
        參數["base_url"] = BASE_URL
    if 類別 == "聊天翻譯":
        參數["max_retries"] = 0
    client = anthropic.Anthropic(**參數)
    try:
        額外 = {"thinking": {"type": "disabled"}} if (類別 in 翻譯類 or not 摘要_思考) else {}
        resp = client.messages.create(
            model=模型,
            max_tokens=_最多token(類別),
            messages=[{"role": "user", "content": 提示詞}],
            **額外,
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
        raise 金鑰錯誤(_金鑰訊息()) from None
    except anthropic.APIConnectionError:
        raise 連線錯誤(_連線訊息()) from None
    except anthropic.RateLimitError:
        if 類別 == "聊天翻譯":
            raise 限速錯誤("API 速率限制") from None
        raise
    _記停止原因(類別, str(getattr(resp, "stop_reason", "")))
    u = getattr(resp, "usage", None)
    _記用量(getattr(u, "input_tokens", None), getattr(u, "output_tokens", None), 類別)
    # 回應可能先有「思考」區塊，只取真正的文字區塊
    return "".join(b.text for b in resp.content if b.type == "text")


def _問_openai相容(提示詞, 模型, 類別):
    try:
        import openai
    except ImportError:
        raise 模型錯誤("provider 設成 openai_compatible，但還沒安裝 openai 套件，請先執行：pip install openai") from None
    # openai 套件一定要有金鑰字串；Ollama 不檢查金鑰，隨便填一個就好
    額外 = {"max_retries": 0} if 類別 == "聊天翻譯" else {}
    client = openai.OpenAI(api_key=_金鑰() or "ollama", base_url=BASE_URL or None, **額外)
    try:
        resp = client.chat.completions.create(
            model=模型,
            max_tokens=_最多token(類別),
            messages=[{"role": "user", "content": 提示詞}],
        )
    except (openai.AuthenticationError, openai.PermissionDeniedError):
        raise 金鑰錯誤(_金鑰訊息()) from None
    except openai.APIConnectionError:
        raise 連線錯誤(_連線訊息()) from None
    except openai.RateLimitError:
        if 類別 == "聊天翻譯":
            raise 限速錯誤("API 速率限制") from None
        raise
    選項們 = getattr(resp, "choices", None)
    if 選項們:                            # 只記在分類別的那一格（原本的 最後停止原因 維持只記 anthropic）
        停止原因們[類別] = str(getattr(選項們[0], "finish_reason", "") or "")
    u = getattr(resp, "usage", None)
    _記用量(getattr(u, "prompt_tokens", None), getattr(u, "completion_tokens", None), 類別)
    try:
        return resp.choices[0].message.content or ""
    except Exception:
        return ""


def call_llm(提示詞, 模型, 類別="摘要"):
    """問模型一句話，回傳文字。金鑰或連線有問題會丟出 模型錯誤。
    類別："摘要"（預設）、"翻譯"（逐句字幕）或 "聊天翻譯"（聊天室翻譯），用量分開記。"""
    if PROVIDER == "openai_compatible":
        return _問_openai相容(提示詞, 模型, 類別)
    return _問_anthropic(提示詞, 模型, 類別)


def 用量文字(單價_輸入, 單價_輸出):
    """結束時印的 token 與費用說明（單價：每百萬 token 美元）。"""
    u = 用量
    if u["缺token"]:
        return f"共呼叫 {u['次數']} 次，token：無法計算，估算費用：無法計算"
    費用 = u["輸入"] / 1e6 * 單價_輸入 + u["輸出"] / 1e6 * 單價_輸出
    return (f"共呼叫 {u['次數']} 次，輸入 {u['輸入']} / 輸出 {u['輸出']} token，"
            f"估算費用約 {費用:.3f} 美元（單價未查證，僅供參考）")
