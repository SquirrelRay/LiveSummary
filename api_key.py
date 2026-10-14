# API 金鑰：整個專案只有這裡會讀寫金鑰（llm.py 呼叫模型、設定框、啟動面板都透過這裡）。
# 存放：Windows 認證管理員（keyring 套件），每家服務各存一把，互不覆蓋：
#   Claude → "claude"、OpenAI → "openai"、DeepSeek → "deepseek"、OpenRouter → "openrouter"、Google Gemini → "gemini"、
#   其他 OpenAI 相容服務 → "相容:主機/路徑"（用服務網址區分）、本機服務（Ollama 等）→ 不需要金鑰。
# 讀取順序：認證管理員 → 環境變數（保留給進階使用者與舊設定）。
# 金鑰內容絕不印出、不寫 log、不寫進 config.json 或任何檔案；錯誤訊息只用白話。
# 只用標準函式庫；keyring 用到時才 import，測試一律換成假後端（設定 _後端），不碰真的認證管理員。
import os
from urllib.parse import urlsplit

import crash_log  # 讀到的金鑰交給它記住，當機紀錄才能整串遮掉（金鑰只在記憶體）

認證服務名 = "直播摘要"            # 認證管理員裡的名稱（使用者在「認證管理員 → 一般認證」看得到）
出廠環境變數 = "ANTHROPIC_API_KEY"   # 舊設定的預設環境變數名稱（= config 出廠預設）

# 已知服務：名稱、預設環境變數、官方「取得金鑰」頁面（2026-10-13 查官方文件）
服務資料 = {
    "claude": {"名稱": "Claude", "環境變數": "ANTHROPIC_API_KEY",
               "取得網址": "https://platform.claude.com/settings/keys"},
    "openai": {"名稱": "OpenAI", "環境變數": "OPENAI_API_KEY",
               "取得網址": "https://platform.openai.com/api-keys"},
    "deepseek": {"名稱": "DeepSeek", "環境變數": "DEEPSEEK_API_KEY",
                 "取得網址": "https://platform.deepseek.com/api_keys"},
    "openrouter": {"名稱": "OpenRouter", "環境變數": "OPENROUTER_API_KEY",            # openrouter.ai/docs/api-keys
                   "取得網址": "https://openrouter.ai/keys"},
    "gemini": {"名稱": "Google Gemini", "環境變數": "GEMINI_API_KEY",                 # ai.google.dev/gemini-api/docs/openai
               "取得網址": "https://aistudio.google.com/apikey"},
}
已知主機 = {"api.anthropic.com": "claude", "api.openai.com": "openai", "api.deepseek.com": "deepseek",
         "openrouter.ai": "openrouter", "generativelanguage.googleapis.com": "gemini"}
本機主機們 = ("localhost", "127.0.0.1", "::1", "0.0.0.0")       # noqa: S104  只是比對網址的主機，不是開伺服器
本機 = "本機"
相容前綴 = "相容:"

# 狀態（設定框顯示的白話）
已儲存, 環境變數中, 未設定, 不需要 = "已儲存", "環境變數", "未設定", "不需要"
狀態字們 = {已儲存: "已儲存在這台電腦", 環境變數中: "使用系統環境變數", 未設定: "尚未設定", 不需要: "這個服務不需要金鑰"}

_後端 = None          # 測試換成假後端；None = 用到時才載入 keyring（Windows 上就是認證管理員）


class 金鑰存取錯誤(Exception):
    """認證管理員讀寫失敗（訊息是白話，不含金鑰）。"""


def 後端():
    global _後端
    if _後端 is None:
        import keyring
        _後端 = keyring
    return _後端


# ---- 服務代號：(provider, base_url) → 存哪一格 ----
def 服務代號(provider, base_url=""):
    """claude／openai／deepseek／本機／相容:主機/路徑。網址空白 = 該家預設網址。"""
    網址 = (base_url or "").strip()
    if not 網址:
        return "openai" if provider == "openai_compatible" else "claude"
    p = urlsplit(網址 if "://" in 網址 else "https://" + 網址)
    主機 = (p.hostname or "").lower()
    if 主機 in 本機主機們:
        return 本機
    if 主機 in 已知主機:
        return 已知主機[主機]
    try:
        埠 = f":{p.port}" if p.port else ""
    except ValueError:
        埠 = ""
    return 相容前綴 + 主機 + 埠 + p.path.rstrip("/")


def 服務名稱(代號):
    if 代號 in 服務資料:
        return 服務資料[代號]["名稱"]
    if 代號 == 本機:
        return "本機模型服務"
    return "OpenAI 相容服務（" + 代號.removeprefix(相容前綴) + "）"


def 取得網址(代號):
    """官方「取得金鑰」頁面；其他相容服務、本機沒有固定網址，回傳空字串。"""
    return 服務資料.get(代號, {}).get("取得網址", "")


def 環境變數名(代號, api_key_env=出廠環境變數):
    """這個服務要看的環境變數名稱；None = 不看環境變數。
    舊設定改過名稱（不是出廠的 ANTHROPIC_API_KEY）就照舊設定；留空 = 舊設定的「不需要金鑰」；其他用該家預設名稱。"""
    自訂 = (api_key_env or "").strip()
    if not 自訂:
        return None
    if 自訂 != 出廠環境變數:
        return 自訂
    return 服務資料.get(代號, {}).get("環境變數")


def 需要金鑰(代號, api_key_env=出廠環境變數):
    """本機服務、舊設定把環境變數留空（= 不需要金鑰）時不需要。"""
    return 代號 != 本機 and bool((api_key_env or "").strip())


# ---- 認證管理員讀寫 ----
def 讀取已儲存(代號):
    try:
        return 後端().get_password(認證服務名, 代號) or None
    except Exception:          # noqa: BLE001  讀不到就當沒存（不讓錯誤訊息帶出任何內容）
        return None


def 儲存(代號, 金鑰):
    金鑰 = (金鑰 or "").strip()
    if not 金鑰:
        raise 金鑰存取錯誤("金鑰是空白的，沒有儲存。")
    crash_log.記住金鑰(金鑰)
    try:
        後端().set_password(認證服務名, 代號, 金鑰)
    except Exception:          # noqa: BLE001
        raise 金鑰存取錯誤("無法存進這台電腦的認證管理員，請再試一次。") from None


def 清除(代號):
    """刪掉這台電腦存的金鑰；本來就沒有也不算錯。回傳有沒有真的刪掉。"""
    if 讀取已儲存(代號) is None:
        return False
    try:
        後端().delete_password(認證服務名, 代號)
    except Exception:          # noqa: BLE001
        raise 金鑰存取錯誤("無法從這台電腦的認證管理員清除，請再試一次。") from None
    return True


# ---- 讀取（認證管理員 → 環境變數）----
def 來源與金鑰(代號, api_key_env=出廠環境變數):
    """回傳 (狀態, 金鑰)。狀態：已儲存／環境變數／未設定／不需要（不需要時若有存金鑰也照樣帶上）。"""
    金鑰 = 讀取已儲存(代號)
    if 金鑰:
        crash_log.記住金鑰(金鑰)
        return (已儲存 if 需要金鑰(代號, api_key_env) else 不需要), 金鑰
    名 = 環境變數名(代號, api_key_env)
    金鑰 = os.environ.get(名) if 名 else None
    if 金鑰:
        crash_log.記住金鑰(金鑰)
        return (環境變數中 if 需要金鑰(代號, api_key_env) else 不需要), 金鑰
    return (未設定 if 需要金鑰(代號, api_key_env) else 不需要), None


def 取得(provider, base_url="", api_key_env=出廠環境變數):
    """呼叫模型用的金鑰；沒有回傳 None。"""
    return 來源與金鑰(服務代號(provider, base_url), api_key_env)[1]


def 狀態(provider, base_url="", api_key_env=出廠環境變數):
    return 來源與金鑰(服務代號(provider, base_url), api_key_env)[0]


def 設定的狀態(設定):
    """設定：config.載入設定() 的設定 dict。"""
    return 狀態(設定["provider"], 設定["base_url"], 設定["api_key_env"])


def 遮掉(字, 金鑰):
    """保險：萬一某段文字含有金鑰，換成 *****（錯誤訊息、紀錄用）。"""
    if 金鑰 and 字:
        return str(字).replace(金鑰, "*****")
    return 字
