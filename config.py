# 設定檔 config.json：出廠預設、欄位檢查、欄位說明、已停用欄位、讀取、寫入、語言清單，全部只在這裡。
# 優先順序：命令列參數 > config.json > 出廠預設（訊息裡稱「內建預設」）
# 只用標準函式庫與純 Python 的 subtitle_speed，不 import 引擎或介面，任何模組都能放心 import。
# config.json 是本機檔案（不進 git）；git 只放範例 config.example.json（內容 = 出廠預設）。
# 沒有 config.json 時全部用出廠預設運作，不會自動建立；設定框按「儲存」時才會建立。
import json
import os
import shutil
import tempfile

import subtitle_speed

設定檔路徑 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
備份檔名 = "config.backup.json"      # 和 config.json 放在同一個資料夾

# ---- 語言（單一來源）----
語言名稱 = {"zh": "中文", "ja": "日文", "en": "英文", "ko": "韓文"}     # 支援的語言與顯示順序
自動 = "auto"                         # 自動偵測（第一段有人聲的音訊判斷後鎖定）
自動名稱 = "自動偵測"
外語們 = tuple(代碼 for 代碼 in 語言名稱 if 代碼 != "zh")
語言代碼們 = (*語言名稱, 自動)         # language 欄位可以填的值


def 語言選項(自動在前=False):
    """下拉選單用：[(顯示名稱, 代碼)]。自動偵測放最後（主控台）或最前（啟動面板）。"""
    選項 = [(名, 代碼) for 代碼, 名 in 語言名稱.items()]
    return [(自動名稱, 自動), *選項] if 自動在前 else [*選項, (自動名稱, 自動)]


# ---- 出廠預設：固定常數，不讀任何執行時會被改寫的全域值（「還原預設值」與不合法時的退回都用這份）----
_出廠預設 = {
    "chat": True, "minute_summary": True, "save_audio": False, "fix_with_chat": False,
    "save_summary": False, "save_transcript": False, "save_chat": False, "save_translation": False,
    "summary_thinking": True,
    "ui_max_transcript": 500, "ui_max_chat": 1000, "ui_max_translation": 500, "newest_on_top": False, "ui_max_summary": 300,
    "check_minutes": 1, "min_topic_min": 3, "max_topic_min": 15,
    "model": "claude-haiku-5-5", "whisper_model": "large-v3-turbo", "language": "zh",
    "minute_sentences": 2,
    "provider": "anthropic", "base_url": "", "api_key_env": "ANTHROPIC_API_KEY",
    "price_input": 1.0, "price_output": 5.0,
    "subtitle_mode": "auto", "subtitle_speed": subtitle_speed.預設,
    "capsule_show_usage": False,
}


def 出廠預設():
    """出廠預設值（每次回傳新的一份，改了也不會影響這裡）。"""
    return dict(_出廠預設)


設定說明 = {
    "chat": "抓聊天室（--live）",
    "minute_summary": "分鐘摘要",
    "save_audio": "存檔：音訊（--live）",
    "save_summary": "存檔：摘要（分鐘與話題）",
    "save_transcript": "存檔：直播稿（--live）",
    "save_chat": "存檔：聊天室（--live）",
    "save_translation": "存檔：逐句翻譯（介面才有）",
    "fix_with_chat": "聊天室參考詞修正",
    "summary_thinking": "摘要使用延伸思考（true 較準但較貴；false 關閉思考，較省）",
    "ui_max_transcript": "介面：直播稿分頁最多顯示幾行（較舊的從畫面移除，存檔不受影響）",
    "ui_max_chat": "介面：聊天室分頁最多顯示幾則",
    "capsule_show_usage": "介面：浮動膠囊旁顯示簡短用量（估算費用），預設關",
    "newest_on_top": "介面：內容分頁的最新內容放最上面（true）或最下面（false，預設）",
    "ui_max_translation": "介面：逐句翻譯分頁最多顯示幾則（較舊的從畫面移除，存檔不受影響）",
    "ui_max_summary": "介面：分鐘摘要與話題摘要分頁各最多顯示幾則",
    "check_minutes": "幾分鐘檢查一次話題",
    "min_topic_min": "話題最短分鐘數",
    "max_topic_min": "話題最長分鐘數",
    "model": "摘要用的模型",
    "whisper_model": "轉錄用的 Whisper 模型",
    "language": "直播語言（" + "、".join(語言代碼們) + "）",
    "minute_sentences": "分鐘摘要句數上限",
    "provider": "模型服務種類（anthropic 或 openai_compatible）",
    "base_url": "模型服務網址（空白 = 預設）",
    "api_key_env": "金鑰的環境變數名稱（空白 = 不需要金鑰）",
    "price_input": "輸入單價（每百萬 token 美元，未查證）",
    "price_output": "輸出單價（每百萬 token 美元，未查證）",
    "subtitle_mode": "逐句字幕（介面才有）：original 原文、translate 翻譯、auto 中文用原文其他翻譯",
    "subtitle_speed": "字幕速度段位：fast 速度、balanced 平衡（預設）、accurate 準度；決定分段秒數與翻譯批次，下次開始生效",
}

# 已停用的舊欄位（舊的摘要框／字幕框 overlay、精簡模式快捷鍵 hotkey_compact、
# 改由 subtitle_speed 段位決定的翻譯批次 translate_batch_seconds／translate_batch_lines）：舊的 config.json 裡還有也不警告、直接忽略，也不會被刪掉
已停用欄位 = {"overlay", "hotkey_compact", "translate_batch_seconds", "translate_batch_lines"}


# ---- 欄位檢查 ----
def _布林(v):
    return isinstance(v, bool)


def _正數(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def _字串(v):
    return isinstance(v, str) and v.strip() != ""


def _非負(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


def _文字(v):      # 可以是空字串
    return isinstance(v, str)


def _服務(v):
    return v in ("anthropic", "openai_compatible")


def _語言(v):
    return v in 語言代碼們


def _字幕模式(v):
    return v in ("original", "translate", "auto")


def _顯示上限(v):
    return isinstance(v, int) and not isinstance(v, bool) and 10 <= v <= 100000


def _句數(v):
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 3


檢查 = {
    "chat": _布林, "minute_summary": _布林, "save_audio": _布林, "fix_with_chat": _布林, "summary_thinking": _布林,
    "save_summary": _布林, "save_transcript": _布林, "save_chat": _布林, "save_translation": _布林,
    "ui_max_transcript": _顯示上限, "ui_max_chat": _顯示上限, "ui_max_translation": _顯示上限, "newest_on_top": _布林, "ui_max_summary": _顯示上限,
    "check_minutes": _正數, "min_topic_min": _正數, "max_topic_min": _正數,
    "model": _字串, "whisper_model": _字串, "language": _語言, "minute_sentences": _句數,
    "provider": _服務, "base_url": _文字, "api_key_env": _文字,
    "price_input": _非負, "price_output": _非負,
    "subtitle_mode": _字幕模式, "subtitle_speed": subtitle_speed.合法,
    "capsule_show_usage": _布林,
}


# ---- 讀取 ----
def 載入設定(命令列=None):
    """命令列：{設定名: 值或 None}（None 代表沒有在命令列指定）。
    回傳 (設定, 來源, 警告們)。config.json 不存在、欄位缺漏、值不合法都不會崩潰。"""
    預設 = 出廠預設()
    設定 = dict(預設)
    來源 = {k: "內建預設" for k in 預設}
    警告們 = []
    內容 = None
    if os.path.exists(設定檔路徑):
        try:
            with open(設定檔路徑, encoding="utf-8-sig") as f:
                內容 = json.load(f)
            if not isinstance(內容, dict):
                raise ValueError("最外層不是欄位清單")
        except Exception as e:
            警告們.append(f"設定檔 config.json 讀不懂（{e}），全部改用內建預設。")
            內容 = None
    for k, v in (內容 or {}).items():
        if k in 已停用欄位:
            continue
        if k not in 預設:
            警告們.append(f"設定檔裡有不認得的欄位「{k}」，已忽略。")
        elif 檢查[k](v):
            設定[k], 來源[k] = v, "config.json"
        else:
            警告們.append(f"設定檔的 {k} 值不合法（{v!r}），改用預設值 {預設[k]!r}。")
    if 設定["min_topic_min"] >= 設定["max_topic_min"]:
        警告們.append("設定檔的 min_topic_min 必須小於 max_topic_min，兩個都改用預設值。")
        for k in ("min_topic_min", "max_topic_min"):
            設定[k], 來源[k] = 預設[k], "內建預設"
    for k, v in (命令列 or {}).items():
        if v is None:
            continue
        if k in 檢查 and not 檢查[k](v):
            警告們.append(f"命令列的 {k} 值不合法（{v!r}），已忽略。")
            continue
        設定[k], 來源[k] = v, "命令列"
    return 設定, 來源, 警告們


def 目前設定():
    """只要設定、不要來源與警告時用（介面讀單一欄位）。"""
    return 載入設定()[0]


def 印設定(設定, 來源, 金鑰狀態):
    """--show-config：印出目前實際生效的設定與來源。金鑰狀態：「已設定／未設定」之類的字，不含金鑰內容。"""
    print(f"設定檔：{設定檔路徑}（{'存在' if os.path.exists(設定檔路徑) else '不存在，全部用內建預設'}）")
    print("目前實際生效的設定（優先順序：命令列 > config.json > 內建預設）：")
    for k in 設定說明:
        print(f"  {k:17} = {設定[k]!r:18} ← {來源[k]}　（{設定說明[k]}）")
    print(f"  API 金鑰：{金鑰狀態}（只從環境變數讀取，不顯示內容）")


# ---- 寫入（整個專案只有這裡會寫 config.json）----
def 備份檔路徑():
    return os.path.join(os.path.dirname(設定檔路徑), 備份檔名)


def 寫入設定(更新):
    """更新：{欄位: 值}，只改這些欄位；其他欄位（含已停用的舊欄位、表單上沒有的欄位）原樣保留。
    寫之前先把舊檔備份成 config.backup.json；先寫同資料夾的暫存檔再取代原檔，寫到一半失敗原本的 config.json 不會壞。
    config.json 不存在就建立新檔。讀不懂原檔、寫入失敗都會丟出例外（原檔不動），由呼叫的人決定怎麼提示。"""
    路徑 = 設定檔路徑
    原本 = {}
    if os.path.exists(路徑):
        shutil.copy2(路徑, 備份檔路徑())          # 寫之前先備份
        with open(路徑, encoding="utf-8-sig") as f:
            原本 = json.load(f)
        if not isinstance(原本, dict):
            原本 = {}
    原本.update(更新)
    暫存fd, 暫存 = tempfile.mkstemp(prefix="config.", suffix=".json.tmp", dir=os.path.dirname(路徑))
    try:
        with os.fdopen(暫存fd, "w", encoding="utf-8") as f:
            json.dump(原本, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(暫存, 路徑)
    except BaseException:
        if os.path.exists(暫存):
            os.remove(暫存)
        raise
