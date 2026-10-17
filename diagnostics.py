# 回報問題的診斷資訊（設定框「關於」→「🐞 回報問題」）：產生一段給人看、也給開發者看的純文字。
# 一律用白名單：下面 組文字() 的每一行都是程式自己逐欄取值、拼出來的字串；不讀任何 log 檔的原文、不整包輸出 config。
# 絕不放：API 金鑰、base_url、api_key_env、任何檔案路徑、Windows 使用者名稱、直播網址、網址紀錄、詞庫、
#   逐字稿、摘要、聊天內容、traceback 內文。
# 任何一項取不到（例外、逾時、沒有 NVIDIA 顯示卡）都只寫「無法取得」，整段文字照樣產生。
# 只用標準函式庫與專案裡不碰介面的模組（Qt 的預覽視窗在 report_dialog.py）。
import contextlib
import json
import os
import re
import shutil
import subprocess
import time

import app_paths
import config
import crash_log
import external
import model_catalog
import system_info
import version

無法取得 = "無法取得"
自填上限 = 60                   # 使用者可以自己輸入的字串（模型名稱）最多放幾個字
顯示卡逾時秒 = 3.0
顯示卡指令參數 = ("--query-gpu=name,memory.total,driver_version", "--format=csv,noheader")


def _取(函式, *參數):
    """跑一項；出任何錯都回傳「無法取得」，不讓整段診斷失敗。"""
    try:
        值 = 函式(*參數)
    except Exception:          # noqa: BLE001  單項失敗不影響其他項
        return 無法取得
    return 無法取得 if 值 is None or 值 == "" else 值


def 截斷(字, 上限=自填上限):
    """使用者自填的字串：合併空白與換行、遮掉看起來像金鑰的部分，超過上限截斷。"""
    字 = crash_log.遮金鑰(" ".join(str(字).split()))
    return 字 if len(字) <= 上限 else 字[:上限] + "…"


def 開關(值):
    if not isinstance(值, bool):
        return 無法取得
    return "開" if 值 else "關"


# ---------- 顯示卡（nvidia-smi）----------
def _乾淨(字, 上限=80):
    """顯示卡名稱、驅動版本：只留可列印的字，限制長度。"""
    字 = "".join(c for c in str(字) if c.isprintable()).strip()
    return 字[:上限]


def 解析顯示卡(輸出):
    """nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 的輸出 →
    「NVIDIA GeForce RTX 4060（8 GB），驅動 560.94」；多張卡用「；」接起來。讀不懂回傳 None。"""
    結果 = []
    for 行 in (輸出 or "").splitlines():
        欄 = [x.strip() for x in 行.split(",")]
        if len(欄) != 3 or not 欄[0]:
            continue
        名稱, 記憶體, 驅動 = 欄
        m = re.match(r"^(\d+)\s*MiB$", 記憶體)
        if m:
            mib = int(m.group(1))
            記憶體字 = f"{round(mib / 1024)} GB" if mib >= 1024 else f"{mib} MiB"
        else:
            記憶體字 = 無法取得
        驅動字 = 驅動 if re.fullmatch(r"[\d.]{1,20}", 驅動) else 無法取得
        結果.append(f"{_乾淨(名稱)}（{記憶體字}），驅動 {驅動字}")
    return "；".join(結果) or None


def 顯示卡資訊(執行=None, 找程式=None):
    """問 nvidia-smi 顯示卡名稱、VRAM、驅動版本（最多等 顯示卡逾時秒）；沒有 NVIDIA 或失敗回傳「無法取得」。"""
    執行 = 執行 or external.執行
    找程式 = 找程式 or shutil.which
    try:
        路徑 = 找程式("nvidia-smi")
        if not 路徑:
            return 無法取得
        r = 執行([路徑, *顯示卡指令參數], capture_output=True, text=True, timeout=顯示卡逾時秒)
    except (OSError, subprocess.SubprocessError, ValueError):
        return 無法取得
    if r.returncode != 0:
        return 無法取得
    return 解析顯示卡(r.stdout) or 無法取得


def CUDA裝置數():
    import first_run
    return str(first_run.顯示卡數())


# ---------- 上次載入轉錄模型時實際用的裝置與模型 ----------
def 記錄轉錄模型(裝置, 模型):
    """轉錄模型載入完成時呼叫：記下實際的裝置（cuda／cpu）與模型名稱。只有這兩項和時間，不含路徑；寫不進去不影響程式。"""
    with contextlib.suppress(Exception):          # 紀錄失敗不能影響轉錄
        資料 = {"裝置": 裝置 if 裝置 in ("cuda", "cpu") else "其他",
              "模型": 截斷(模型),
              "時間": time.strftime("%Y-%m-%d %H:%M")}
        路徑 = app_paths.上次轉錄模型檔()
        os.makedirs(os.path.dirname(路徑), exist_ok=True)
        with open(路徑, "w", encoding="utf-8") as f:
            json.dump(資料, f, ensure_ascii=False)


def 讀上次轉錄模型():
    """回傳 {"裝置", "模型", "時間"}；沒有執行過或讀不懂回傳 None。"""
    try:
        with open(app_paths.上次轉錄模型檔(), encoding="utf-8") as f:
            資料 = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(資料, dict):
        return None
    裝置 = 資料.get("裝置")
    return {"裝置": 裝置 if 裝置 in ("cuda", "cpu") else "其他",
            "模型": 截斷(資料.get("模型", "")) or 無法取得,
            "時間": 資料.get("時間") if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", str(資料.get("時間", ""))) else ""}


# ---------- 最近一次錯誤（只取時間與例外型別名稱）----------
_標頭 = re.compile(r"^==== (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| 版本 ")
_型別 = re.compile(r"^([A-Za-z_][\w.]{0,79})(?::|$)")
_原生 = re.compile(r"^(?:Windows fatal exception|Fatal Python error): ?([A-Za-z][A-Za-z ]{0,39})?")


def 解析最近錯誤(文字, 修改時間=None):
    """當機紀錄.txt 的內容 → 「2026-10-15 16:16:57 ValueError」之類；沒有任何一筆回傳 None。
    只看最後一筆：時間取自標頭、型別取自最後一段 traceback 下面的第一行（冒號前面）；其餘內容一概不輸出。
    最後一筆標頭之後出現原生層當機（faulthandler，沒有時間）時，回報原生層當機與檔案修改時間。"""
    行們 = (文字 or "").splitlines()
    最後標頭 = None
    for i, 行 in enumerate(行們):
        if _標頭.match(行):
            最後標頭 = i
    原生 = None
    for i in range(最後標頭 + 1 if 最後標頭 is not None else 0, len(行們)):
        m = _原生.match(行們[i])
        if m:
            原生 = (m.group(1) or "").strip()
    if 原生 is not None:
        時 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(修改時間)) if 修改時間 else "時間不明"
        return f"{時} 原生層當機" + (f"（{原生}）" if 原生 else "")
    if 最後標頭 is None:
        return None
    時間 = _標頭.match(行們[最後標頭]).group(1)
    段 = 行們[最後標頭 + 1:]
    tb = [i for i, 行 in enumerate(段) if 行.startswith("Traceback (most recent call last):")]
    型別 = None
    if tb:
        for 行 in 段[tb[-1] + 1:]:
            if 行 and not 行[0].isspace():
                m = _型別.match(行)
                型別 = m.group(1) if m else None
                break
    elif any(行.startswith("Qt 嚴重錯誤") for 行 in 段):
        型別 = "Qt 嚴重錯誤"
    return f"{時間} {型別 or '其他錯誤'}"


def 最近錯誤(路徑們=None):
    """先看 當機紀錄.txt，沒有任何一筆再看 當機紀錄.舊.txt；都沒有回傳「沒有紀錄」。"""
    if 路徑們 is None:
        主 = app_paths.當機紀錄檔()
        路徑們 = (主, 主.replace("當機紀錄.txt", "當機紀錄.舊.txt"))
    for 路徑 in 路徑們:
        try:
            with open(路徑, encoding="utf-8", errors="replace") as f:
                文字 = f.read()
            結果 = 解析最近錯誤(文字, os.path.getmtime(路徑))
        except OSError:
            continue
        if 結果:
            return 結果
    return "沒有紀錄"


# ---------- 設定（逐欄白名單）----------
def 設定檔狀態():
    if not os.path.exists(config.設定檔路徑):
        return "不存在（使用內建預設）"
    問題們 = config.載入設定詳細()[3]
    if any(種類 == "讀不懂" for 種類, _ in 問題們):
        return "讀不懂（已改用內建預設）"
    if 問題們:
        return f"存在，有 {len(問題們)} 項有問題已改用預設"
    return "存在且可讀"


def 外部程式狀態():
    來源 = app_paths.ffmpeg位置()[1]
    ffmpeg = {"隨附": "隨附", "系統": "系統上的"}.get(來源, "找不到")
    if app_paths.已打包():
        helper = "有" if os.path.isfile(app_paths.helper執行檔()) else "沒有"
    else:
        helper = "開發環境不需要"
    return f"ffmpeg：{ffmpeg}；helper.exe：{helper}"


def 收集(設定=None):
    """取得每一項的值（每項各自保護，失敗是「無法取得」）。回傳 {名稱: 字串}，交給 組文字()。"""
    if 設定 is None:
        設定 = _取(config.目前設定)
    if not isinstance(設定, dict):
        設定 = {}

    def 設(k):
        return 設定.get(k)

    上次 = _取(讀上次轉錄模型)
    上次 = 上次 if isinstance(上次, dict) else None
    服務 = _取(lambda: model_catalog.服務(model_catalog.設定的服務(設定))["名稱"])
    provider = 設("provider") if 設("provider") in ("anthropic", "openai_compatible") else 無法取得
    return {
        "程式版本": _取(version.版本字),
        "打包版": _取(lambda: "是" if app_paths.已打包() else "否（開發環境）"),
        "Windows": _取(system_info.平台字),
        "Python": _取(system_info.Python版本),
        "CPU 核心數": _取(lambda: str(os.cpu_count())),
        "顯示卡": _取(顯示卡資訊),
        "可用 CUDA 裝置數": _取(CUDA裝置數),
        "運算裝置（上次載入模型）": (f"{上次['裝置']}" + (f"（{上次['時間']}）" if 上次["時間"] else "")) if 上次 else "尚未執行過",
        "轉錄模型（設定／實際）": f"{_取(截斷, 設('whisper_model')) if 設('whisper_model') else 無法取得}／"
                           f"{上次['模型'] if 上次 else '尚未執行過'}",
        "摘要服務": f"{服務}（{provider}）",
        "摘要模型": _取(截斷, 設("model")) if 設("model") else 無法取得,
        "直播語言設定": 設("language") if 設("language") in config.語言代碼們 else 無法取得,
        "字幕模式／速度": f"{設('subtitle_mode') if 設('subtitle_mode') in ('original', 'translate', 'auto') else 無法取得}／"
                     f"{設('subtitle_speed') if _取(config.檢查['subtitle_speed'], 設('subtitle_speed')) is True else 無法取得}",
        "功能": " ".join(f"{名}={開關(設(k))}" for 名, k in (
            ("聊天室", "chat"), ("分鐘摘要", "minute_summary"), ("聊天室翻譯", "chat_translate"),
            ("上網查證", "web_verify"), ("延伸思考", "summary_thinking"), ("聊天室參考詞修正", "fix_with_chat"))),
        "存檔": " ".join(f"{名}={開關(設(k))}" for 名, k in (
            ("摘要", "save_summary"), ("直播稿", "save_transcript"), ("聊天室", "save_chat"),
            ("逐句翻譯", "save_translation"), ("音訊", "save_audio"))),
        "外部程式": _取(外部程式狀態),
        "設定檔": _取(設定檔狀態),
        "最近一次錯誤": _取(最近錯誤),
    }


順序 = ("程式版本", "打包版", "Windows", "Python", "CPU 核心數", "顯示卡", "可用 CUDA 裝置數",
      "運算裝置（上次載入模型）", "轉錄模型（設定／實際）", "摘要服務", "摘要模型", "直播語言設定", "字幕模式／速度",
      "功能", "存檔", "外部程式", "設定檔", "最近一次錯誤")


def 組文字(資料):
    """{名稱: 值} → 診斷文字。只輸出 順序 裡的名稱（多給的一律不放），缺的寫「無法取得」。"""
    行們 = [f"【{version.產品名} 診斷資訊】"]
    for 名 in 順序:
        值 = 資料.get(名)
        行們.append(f"{名}：{值 if isinstance(值, str) and 值 else 無法取得}")
    return "\n".join(行們)


def 產生():
    """完整的診斷文字（會跑 nvidia-smi、問顯示卡函式庫，最多幾秒；介面要在背景執行緒呼叫）。"""
    try:
        return 組文字(收集())
    except Exception:          # noqa: BLE001  保險：無論如何都給一段文字
        return 組文字({"程式版本": _取(version.版本字)})
