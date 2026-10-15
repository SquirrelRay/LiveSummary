# 呼叫語言模型：整個專案只有這個檔案會碰模型 API
# 支援兩種寫法（在 config.json 的 provider 切換）：
#   "anthropic"          ：Claude（預設）
#   "openai_compatible"  ：OpenAI、DeepSeek、Ollama 等，靠 base_url 與 model 區分
import sys
import threading
from contextlib import contextmanager

import api_key
import config

# 這幾個值由 套用設定() 依 config.json 填入；沒填就是 config.py 的出廠預設（= 原本只用 Claude 的行為）
PROVIDER = config.出廠預設()["provider"]
BASE_URL = config.出廠預設()["base_url"]           # 空字串 = 用該家的預設網址
API_KEY_ENV = config.出廠預設()["api_key_env"]     # 舊設定的環境變數名稱（金鑰先找認證管理員，見 api_key.py）；空字串 = 不需要金鑰
MAX_TOKENS = 8000                 # 摘要類呼叫：延伸思考也佔這個額度，4000 時偶爾被思考用光、沒寫出文字（2026-10-15 乾淨電腦測試）；只有真的用到才計費
翻譯_MAX_TOKENS = 600             # 逐句翻譯：關掉思考後只剩譯文，一批 4 到 8 句這樣就夠用
聊天翻譯_MAX_TOKENS = 1500        # 聊天室翻譯：一批最多 40 則短留言
# 摘要類呼叫（話題判斷、分鐘摘要、話題摘要）的逾時與重試。SDK 預設單次 600 秒、再自動重試 2 次，
# API 卡住時直播中的話題判斷最久會停將近 30 分鐘（2026-10-15 有一次話題判斷超過 4.5 分鐘沒回來）。
# 180 秒：延伸思考開著、寫滿 MAX_TOKENS 8000 也夠（Haiku 一題正常 10～30 秒；較慢的模型約 60～80 token/秒，寫滿 8000 token 約 100～130 秒）；
# 重試 1 次：伺服器過載（529）等一下就好的錯誤還能再試一次，卡住時最久約 6 分鐘就放棄這一輪，下一輪照常。
# 逾時不算「連線錯誤」（不會讓整場停下）：照一般呼叫出錯處理，話題判斷當作 same、話題摘要顯示說明。
摘要逾時秒 = 180
摘要最多重試 = 1

# 累計 API 呼叫次數與 token（給 live_topics.py 統計用）
# 缺token：有幾次呼叫拿不到 token 數（有就無法計算總量與費用）
用量 = {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0}
# 逐句字幕翻譯另外算（app.py 的字幕疊加層才會用到），不和摘要的用量混在一起
翻譯用量 = {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0}
# 聊天室翻譯（chat_translate.py）也另外算
聊天翻譯用量 = {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0}
# 上網查證詞庫（web_verify.py）也另外算；多記實際搜尋次數（搜尋另外計費）
查證用量 = {"次數": 0, "輸入": 0, "輸出": 0, "缺token": 0, "搜尋": 0}
_用量名 = {"摘要": "用量", "翻譯": "翻譯用量", "聊天翻譯": "聊天翻譯用量", "查證": "查證用量"}     # 類別 → 用哪一份用量（用名字查，測試換掉整份也照樣記）
翻譯類 = ("翻譯", "聊天翻譯")       # 關閉延伸思考、限制輸出長度的類別
摘要_思考 = config.出廠預設()["summary_thinking"]      # False = 摘要相關呼叫關閉延伸思考（config.json 的 summary_thinking）
最後停止原因 = ""     # 最近一次摘要或逐句翻譯回答的停止原因（max_tokens = 被截斷），翻譯失敗時寫進紀錄；聊天室翻譯不寫這裡
停止原因們 = {}       # 類別 → 該類別最近一次回答的停止原因（兩條翻譯執行緒各記各的，不會互相覆蓋）
# 類別 → 最近一次回答的資訊（寫紀錄找原因用）：停止原因、拒絕類別、輸入／輸出 token、內容區塊種類。不含金鑰、不含回答內容
回應資訊們 = {}
_本執行緒 = threading.local()    # 關閉思考() 的開關只影響目前這條執行緒


@contextmanager
def 關閉思考():
    """這段期間（只限目前這條執行緒）的摘要類呼叫關閉延伸思考。話題摘要空回應重試時用：
    思考把 max_tokens 用光時，同樣設定再問多半又是空的；關掉思考，額度就全部留給正式內容。"""
    舊 = getattr(_本執行緒, "關思考", False)
    _本執行緒.關思考 = True
    try:
        yield
    finally:
        _本執行緒.關思考 = 舊


def 停止種類(停止原因):
    """兩家服務的停止原因 → "截斷"（到了長度上限）、"拒絕"（安全機制擋下）或 "其他"。"""
    return {"max_tokens": "截斷", "length": "截斷", "refusal": "拒絕", "content_filter": "拒絕"}.get(停止原因 or "", "其他")


def 回應紀錄(類別):
    """這個類別最近一次回答的資訊，寫進紀錄檔的一段文字（沒有就回傳空字串）。"""
    資 = 回應資訊們.get(類別)
    if not 資:
        return ""
    字 = f"stop_reason={資['停止原因'] or '（無）'}"
    if 資.get("拒絕類別"):
        字 += f"，拒絕類別={資['拒絕類別']}"
    return 字 + f"，輸入={資['輸入']}，輸出={資['輸出']} token，內容區塊={資['區塊'] or '（無）'}"


def 是服務錯誤(e):
    """模型服務套件（anthropic、openai）丟出的錯誤：伺服器錯誤、逾時、請求被拒等。程式本身的錯誤不算。"""
    return type(e).__module__.split(".")[0] in ("anthropic", "openai")


def 錯誤描述(e):
    """錯誤類型（有 HTTP 狀態碼就附上），給紀錄與畫面用。只用類型名稱，不放錯誤訊息全文（避免帶出請求內容）。"""
    碼 = getattr(e, "status_code", None)
    return type(e).__name__ + (f" {碼}" if 碼 else "")


def _記回應(類別, 停止原因, 拒絕類別, 輸入, 輸出, 區塊們):
    回應資訊們[類別] = {"停止原因": 停止原因, "拒絕類別": 拒絕類別, "輸入": 輸入, "輸出": 輸出, "區塊": "、".join(區塊們)}


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


def 預先載入():
    """先 import 模型服務的套件（anthropic 約 2.5 秒），讓第一次呼叫不用等。失敗不丟例外（真的呼叫時才報錯）。"""
    try:
        if PROVIDER == "openai_compatible":
            import openai  # noqa: F401
        else:
            import anthropic  # noqa: F401
    except ImportError:
        pass


def _服務代號():
    return api_key.服務代號(PROVIDER, BASE_URL)


def 金鑰狀態():
    """給 --show-config 用，不顯示金鑰內容。"""
    return api_key.狀態字們[api_key.狀態(PROVIDER, BASE_URL, API_KEY_ENV)]


未設定金鑰訊息 = "尚未設定 API 金鑰：請到「設定」的「模型服務」貼上金鑰。"


def 檢查金鑰(設定=None):
    """開始前檢查金鑰有沒有設定（認證管理員或環境變數）。沒問題回傳 None，有問題回傳一句中文說明。
    設定：給了就照這份設定（config.載入設定 的 dict）檢查（啟動面板待命時用）；不給就用 套用設定() 套好的值。"""
    狀態 = api_key.設定的狀態(設定) if 設定 is not None else api_key.狀態(PROVIDER, BASE_URL, API_KEY_ENV)
    if 狀態 == api_key.未設定:
        return 未設定金鑰訊息
    return None


def _金鑰訊息():
    return "API 金鑰無效或沒有權限，已停止。請到「設定」重新貼上金鑰並按「測試連線」。"


def _連線訊息():
    網址 = BASE_URL or "該服務的預設網址"
    return (f"連不上模型伺服器（{網址}），已停止。請確認網路連線與模型伺服器網址設定；"
            "用 Ollama 的話，請先把 Ollama 打開。")


def _記用量(輸入, 輸出, 類別="摘要"):
    u = 用量表(類別)
    標 = f"[{類別} token 用量]" if 類別 in (*翻譯類, "查證") else "[token 用量]"
    u["次數"] += 1
    if 輸入 is None or 輸出 is None:
        u["缺token"] += 1
        print(f"{標} 這個服務沒有回報 token 數（無法計算）", file=sys.stderr)
        return
    u["輸入"] += 輸入
    u["輸出"] += 輸出
    print(f"{標} 輸入 {輸入}，輸出 {輸出}", file=sys.stderr)


def _金鑰():
    """認證管理員 → 環境變數；沒有回傳 None。"""
    return api_key.取得(PROVIDER, BASE_URL, API_KEY_ENV)


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
    # 摘要：逾時 摘要逾時秒、重試 摘要最多重試 次；逾時照原樣丟出（服務錯誤），不改寫成 連線錯誤
    import anthropic
    參數 = {}
    金鑰 = _金鑰()
    if 金鑰:
        參數["api_key"] = 金鑰
    if BASE_URL:
        參數["base_url"] = BASE_URL
    if 類別 == "聊天翻譯":
        參數["max_retries"] = 0
    elif 類別 == "摘要":
        參數.update(timeout=摘要逾時秒, max_retries=摘要最多重試)
    client = anthropic.Anthropic(**參數)
    try:
        關思考 = 類別 in 翻譯類 or not 摘要_思考 or getattr(_本執行緒, "關思考", False)
        額外 = {"thinking": {"type": "disabled"}} if 關思考 else {}
        resp = client.messages.create(
            model=模型,
            max_tokens=_最多token(類別),
            messages=[{"role": "user", "content": 提示詞}],
            **額外,
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
        raise 金鑰錯誤(_金鑰訊息()) from None
    except anthropic.APITimeoutError:     # 是 APIConnectionError 的子類別，要先接：逾時不是連不上，不讓整場停下
        raise
    except anthropic.APIConnectionError:
        raise 連線錯誤(_連線訊息()) from None
    except anthropic.RateLimitError:
        if 類別 == "聊天翻譯":
            raise 限速錯誤("API 速率限制") from None
        raise
    停止 = str(getattr(resp, "stop_reason", "") or "")
    _記停止原因(類別, 停止)
    u = getattr(resp, "usage", None)
    _記用量(getattr(u, "input_tokens", None), getattr(u, "output_tokens", None), 類別)
    細節 = getattr(resp, "stop_details", None)          # 只有 stop_reason=refusal 時才有（安全機制擋下的類別）
    _記回應(類別, 停止, getattr(細節, "category", None) if 細節 else None,
           getattr(u, "input_tokens", None), getattr(u, "output_tokens", None), [b.type for b in resp.content])
    # 回應可能先有「思考」區塊，只取真正的文字區塊
    return "".join(b.text for b in resp.content if b.type == "text")


def _問_openai相容(提示詞, 模型, 類別):
    try:
        import openai
    except ImportError:
        raise 模型錯誤("模型服務選了「OpenAI 相容服務」，但還沒安裝 openai 套件，請先執行：pip install openai") from None
    # openai 套件一定要有金鑰字串；Ollama 不檢查金鑰，隨便填一個就好
    額外 = {"max_retries": 0} if 類別 == "聊天翻譯" else {}
    if 類別 == "摘要":
        額外 = {"timeout": 摘要逾時秒, "max_retries": 摘要最多重試}
    client = openai.OpenAI(api_key=_金鑰() or "ollama", base_url=BASE_URL or None, **額外)
    try:
        resp = client.chat.completions.create(
            model=模型,
            max_tokens=_最多token(類別),
            messages=[{"role": "user", "content": 提示詞}],
        )
    except (openai.AuthenticationError, openai.PermissionDeniedError):
        raise 金鑰錯誤(_金鑰訊息()) from None
    except openai.APITimeoutError:        # 同上：逾時照原樣丟出，不改寫成 連線錯誤
        raise
    except openai.APIConnectionError:
        raise 連線錯誤(_連線訊息()) from None
    except openai.RateLimitError:
        if 類別 == "聊天翻譯":
            raise 限速錯誤("API 速率限制") from None
        raise
    選項們 = getattr(resp, "choices", None)
    停止 = ""
    if 選項們:                            # 只記在分類別的那一格（原本的 最後停止原因 維持只記 anthropic）
        停止 = 停止原因們[類別] = str(getattr(選項們[0], "finish_reason", "") or "")
    u = getattr(resp, "usage", None)
    _記用量(getattr(u, "prompt_tokens", None), getattr(u, "completion_tokens", None), 類別)
    try:
        文字 = resp.choices[0].message.content or ""
    except Exception:
        文字 = ""
    _記回應(類別, 停止, None, getattr(u, "prompt_tokens", None), getattr(u, "completion_tokens", None),
           ["text"] if 文字 else [])
    return 文字


# ---- 上網查證（只有 anthropic 有官方的上網搜尋工具）----
# 官方文件（2026-10-13 查證）：web_search 工具每 1,000 次搜尋 10 美元，另加 token（搜尋結果算輸入 token）；搜尋出錯不收費。
上網搜尋工具 = "web_search_20250305"      # 基本版（不需要 code execution，所有支援上網搜尋的模型都能用）
每次搜尋美元 = 10 / 1000
查證_MAX_TOKENS = 8000                    # 同樣會開延伸思考，和摘要類一樣放寬；只有真的用到才計費
查證逾時秒 = 60
最多續問 = 2                              # 回答被暫停（pause_turn）時最多再接著問幾次


class 查證失敗(Exception):
    """上網查證「沒查成」：逾時、API 錯誤、速率限制、回答被截斷等。不代表查無，之後可以再查。"""


def 支援上網查證():
    """只有直接連 Claude 官方時（透過 OpenRouter 等轉接的 Claude 不算）。"""
    return PROVIDER == "anthropic" and _服務代號() == "claude"


def 上網搜尋(提示詞, 模型, 最多搜尋=2):
    """帶上網搜尋工具問一次模型。回傳 {"文字", "網址們"(搜尋結果與引用裡真的出現過的網址), "搜尋成功", "搜尋錯誤"(錯誤碼清單), "搜尋次數", "查詢們"(實際搜尋的關鍵字)}。
    沒查成（逾時、連線、API 錯誤、截斷、拒答）丟出 查證失敗；金鑰錯誤照樣丟出 金鑰錯誤。用量記在 查證用量。"""
    if not 支援上網查證():
        raise 查證失敗("目前的模型服務沒有支援的上網搜尋工具")
    import anthropic
    參數 = {"timeout": 查證逾時秒, "max_retries": 1}
    金鑰 = _金鑰()
    if 金鑰:
        參數["api_key"] = 金鑰
    if BASE_URL:
        參數["base_url"] = BASE_URL
    client = anthropic.Anthropic(**參數)
    訊息們 = [{"role": "user", "content": 提示詞}]
    額外 = {} if 摘要_思考 else {"thinking": {"type": "disabled"}}
    區塊們 = []
    u = 查證用量
    for _ in range(1 + 最多續問):
        try:
            resp = client.messages.create(
                model=模型, max_tokens=查證_MAX_TOKENS, messages=訊息們,
                tools=[{"type": 上網搜尋工具, "name": "web_search", "max_uses": 最多搜尋}], **額外)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            raise 金鑰錯誤(_金鑰訊息()) from None
        except anthropic.APIError as e:            # 逾時、連線、速率限制、伺服器錯誤：沒查成
            raise 查證失敗(f"{type(e).__name__}") from None
        用 = getattr(resp, "usage", None)
        _記用量(getattr(用, "input_tokens", None), getattr(用, "output_tokens", None), "查證")
        u["搜尋"] += int(getattr(getattr(用, "server_tool_use", None), "web_search_requests", 0) or 0)
        區塊們 += list(resp.content)
        停止 = str(getattr(resp, "stop_reason", ""))
        if 停止 != "pause_turn":
            break
        訊息們 = 訊息們 + [{"role": "assistant", "content": resp.content}]
    if 停止 != "end_turn":
        raise 查證失敗(f"回答沒有正常結束（{停止}）")
    網址們, 成功, 錯誤們, 文字們 = set(), 0, [], []
    for b in 區塊們:
        類 = getattr(b, "type", "")
        if 類 == "web_search_tool_result":
            內容 = getattr(b, "content", None)
            if isinstance(內容, list):          # 成功是結果清單（可能是空的）；出錯是一個錯誤物件
                成功 += 1
                網址們 |= {r.url for r in 內容 if getattr(r, "url", "")}
            else:
                錯誤們.append(str(getattr(內容, "error_code", "unknown")))
        elif 類 == "text":
            文字們.append(b.text)
            for c in getattr(b, "citations", None) or []:
                if getattr(c, "url", ""):
                    網址們.add(c.url)
    return {"文字": "".join(文字們), "網址們": 網址們, "搜尋成功": 成功, "搜尋錯誤": 錯誤們,
            "搜尋次數": sum(1 for b in 區塊們 if getattr(b, "type", "") == "server_tool_use"),
            "查詢們": [str((getattr(b, "input", None) or {}).get("query", "")) for b in 區塊們
                    if getattr(b, "type", "") == "server_tool_use"]}


def 查證用量文字(單價_輸入, 單價_輸出):
    """結束時「上網查證」那一行後面的用量與費用（token 和搜尋費分開列）。"""
    u = 查證用量
    搜尋費 = u["搜尋"] * 每次搜尋美元
    if u["缺token"]:
        return f"呼叫 {u['次數']} 次，搜尋 {u['搜尋']} 次，token：無法計算；搜尋費約 {搜尋費:.3f} 美元"
    if 單價_輸入 is None or 單價_輸出 is None:           # 單價查不到：不估算，不沿用別的模型的單價
        return (f"呼叫 {u['次數']} 次，搜尋 {u['搜尋']} 次，輸入 {u['輸入']} / 輸出 {u['輸出']} token；"
                f"估算費用：單價未知，無法估算（搜尋費另計約 {搜尋費:.3f} 美元）")
    token費 = u["輸入"] / 1e6 * 單價_輸入 + u["輸出"] / 1e6 * 單價_輸出
    return (f"呼叫 {u['次數']} 次，搜尋 {u['搜尋']} 次，輸入 {u['輸入']} / 輸出 {u['輸出']} token；"
            f"估算費用約 {token費 + 搜尋費:.3f} 美元（token {token費:.3f}，搜尋 {搜尋費:.3f}，每次 0.01 美元；金額為估算，實際以 API 帳單為準）")


# ---- 設定框的「測試連線」：只列出模型清單（不用 token、不產生費用），不印、不記錄金鑰 ----
測試逾時秒 = 15
測試成功, 測試金鑰無效, 測試連不上, 測試其他 = "成功", "金鑰無效", "連不上", "其他"


def _模型資料(m):
    """列出模型的一筆 → {"代號", "名稱", "輸入", "輸出"}（單價：OpenRouter 這類清單附價格的才有，每百萬 token 美元）。"""
    import model_catalog
    額外 = getattr(m, "model_extra", None) or {}
    pricing = getattr(m, "pricing", None) or 額外.get("pricing")
    輸入, 輸出 = model_catalog.解析單價(pricing) if pricing else (None, None)
    名稱 = getattr(m, "display_name", None) or getattr(m, "name", None) or 額外.get("name") or ""
    return {"代號": str(getattr(m, "id", "")), "名稱": str(名稱), "輸入": 輸入, "輸出": 輸出}


def 列出模型(provider, base_url, 金鑰, 全部=True):
    """「列出模型」（不用 token、不產生費用）。回傳 (結果, 白話說明, 模型們)；結果：成功／金鑰無效／連不上／其他。
    全部=False 只拿一筆（測試連線用）。說明不含金鑰、也不含伺服器回傳的原文（避免任何內容被帶出來）。"""
    名稱 = api_key.服務名稱(api_key.服務代號(provider, base_url))
    網址 = (base_url or "").strip() or None
    try:
        if provider == "openai_compatible":
            try:
                import openai as 套件
            except ImportError:
                return 測試其他, "還沒安裝 OpenAI 相容服務需要的套件（openai），無法連線。", []
            client = 套件.OpenAI(api_key=金鑰 or "ollama", base_url=網址, max_retries=0, timeout=測試逾時秒)
            頁 = client.models.list()
        else:
            import anthropic as 套件
            參數 = {"max_retries": 0, "timeout": 測試逾時秒}
            if 金鑰:
                參數["api_key"] = 金鑰
            if 網址:
                參數["base_url"] = 網址
            頁 = 套件.Anthropic(**參數).models.list(limit=1000 if 全部 else 1)
        模型們 = []
        try:
            迭代 = iter(頁)          # 官方套件的清單會自動翻頁
        except TypeError:
            迭代 = iter(getattr(頁, "data", None) or [])
        for m in 迭代:
            模型們.append(_模型資料(m))
            if not 全部:
                break
    except Exception as e:       # noqa: BLE001  任何錯誤都只回白話，不帶原文
        if isinstance(e, (套件.AuthenticationError, 套件.PermissionDeniedError)):
            return 測試金鑰無效, "金鑰無效或沒有權限。請確認金鑰有完整複製（前後沒有多空白）。", []
        if isinstance(e, 套件.APIConnectionError):          # 含逾時
            return 測試連不上, f"連不上 {名稱}。請確認網路連線，稍後再試一次。", []
        if isinstance(e, 套件.APIStatusError):
            return 測試其他, f"{名稱} 回覆錯誤（代碼 {getattr(e, 'status_code', '?')}），請稍後再試一次。", []
        return 測試其他, "連線時發生問題，請再試一次。", []
    return 測試成功, "", [m for m in 模型們 if m["代號"]]


def 測試連線(provider, base_url, 金鑰):
    """用這把金鑰試著「列出模型」（只拿一筆）。回傳 (結果, 白話說明)；結果：成功／金鑰無效／連不上／其他。"""
    結果, 說明, _ = 列出模型(provider, base_url, 金鑰, 全部=False)
    if 結果 != 測試成功:
        return 結果, 說明.replace("連線時發生問題", "測試時發生問題")
    名稱 = api_key.服務名稱(api_key.服務代號(provider, base_url))
    return 測試成功, f"連線成功，{名稱} 的金鑰有效。（測試只列出模型清單，不會產生費用）"


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
    if 單價_輸入 is None or 單價_輸出 is None:           # 單價查不到：不估算，不沿用別的模型的單價
        return f"共呼叫 {u['次數']} 次，輸入 {u['輸入']} / 輸出 {u['輸出']} token，估算費用：單價未知，無法估算"
    費用 = u["輸入"] / 1e6 * 單價_輸入 + u["輸出"] / 1e6 * 單價_輸出
    return (f"共呼叫 {u['次數']} 次，輸入 {u['輸入']} / 輸出 {u['輸出']} token，"
            f"估算費用約 {費用:.3f} 美元（金額為估算，實際以 API 帳單為準）")
