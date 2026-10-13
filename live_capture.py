# Twitch／YouTube 直播即時轉錄：把直播聲音一段一段轉成文字，一句一句吐給 live_topics.py
# 流程：streamlink（抓音訊）→ ffmpeg（轉 16kHz 單聲道）→ 每段 8～20 秒（依字幕速度段位）→ faster-whisper
# YouTube：streamlink 改經過 yt_audio.py（多回報第一個片段的 PDT，用來對齊時間）；直播資訊讀觀看頁；聊天室用 yt_chat（yt-dlp live_chat）。
#          開播超過 24 小時（24 小時不停播的頻道）當作連續直播，時間改從開始擷取起算（+ 模式）。
import os
import re
import sys
import json
import glob
import time
import queue
import shutil
import wave
import threading
import subprocess
from datetime import datetime

import numpy as np

import transcribe  # 沿用 GPU 優先的作法
import events      # 提示訊息改成送出事件
import config      # 語言清單（單一來源）
import startup_timeline as 里程碑   # 啟動時間里程碑紀錄
import first_run     # 轉錄模型下載過沒有、下載進度（第一次使用）
import stream_info   # 開播時間、標題、分類、直播主（不需要金鑰）
import stream_clock  # 音訊秒數、收到時刻 → 直播實際進行時間
import platforms     # 網址 → Twitch／YouTube
import yt_audio      # YouTube 音訊（streamlink ＋ 第一個片段的 PDT）

段秒數 = 20          # 每次開始時由字幕速度段位覆蓋（設定分段），一場直播中固定不變
取樣率 = 16000
每段位元組 = 段秒數 * 取樣率 * 2  # 16-bit 單聲道


def 設定分段(秒):
    """開始擷取前設定分段長度（整數秒；音訊檔名與時間戳都假設每段一樣長，所以直播中不能改）。"""
    global 段秒數, 每段位元組
    段秒數 = int(秒)
    每段位元組 = 段秒數 * 取樣率 * 2


# Whisper 在沒人講話時常「幻聽」出來的句子，看到就丟掉（可自行增加）
幻聽詞 = ["訂閱轉發打賞", "明鏡與點點", "字幕志願者", "謝謝觀看", "感謝觀看", "感谢观看", "Amara.org",
        "字幕志愿者", "李宗盛",
        # 日文
        "視聴ありがとうございました", "視聴ありがとうございます", "ご視聴いただきありがとうございました",   # 含缺「ご」的變體（例如「字幕視聴ありがとうございました」）
        # 英文
        "Thank you for watching", "Thanks for watching",
        # 韓文
        "시청해 주셔서 감사합니다", "시청해주셔서 감사합니다"]

中文提示 = "以下是繁體中文的直播逐字稿。"   # 中文轉錄的 initial_prompt
外洩詞 = ("繁體中文", "逐字稿")


def 提示詞外洩(文字):
    """Whisper 在沒人講話時會把 initial_prompt 改寫後吐出來（例如「我實在是繁體中文的」）。
    判斷：含「繁體中文」或「逐字稿」，而且這句的字有六成以上出現在提示詞裡。
    正常講到繁體中文的句子（例如「這個遊戲有繁體中文嗎」）提示詞以外的字比較多，不會被擋。"""
    if not any(詞 in 文字 for 詞 in 外洩詞):
        return False
    字們 = [c for c in 文字 if c.strip() and c not in "，。、！？,.!? "]
    return bool(字們) and sum(c in 中文提示 for c in 字們) / len(字們) >= 0.6


def 是幻聽(文字):
    return any(詞 in 文字 for 詞 in 幻聽詞) or 提示詞外洩(文字)


偵測句數 = 1          # auto 模式：累積幾段「有人聲」的音訊再判斷語言（原本是 3，改成 1 讓第一句字幕早約 40 秒出現）
最低信心 = 0.4        # 偵測出來的語言平均信心低於這個值，就當作失敗


class 直播錯誤(Exception):
    pass


def 找ffmpeg():
    路徑 = shutil.which("ffmpeg")
    if 路徑:
        return 路徑
    # 剛用 winget 裝好時，目前視窗可能還找不到，到安裝位置找
    候選 = glob.glob(os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\**\bin\ffmpeg.exe"), recursive=True)
    if 候選:
        return 候選[0]
    raise 直播錯誤("找不到 ffmpeg，請先安裝（winget install Gyan.FFmpeg）後重開視窗。")


def 頻道名稱(網址):
    return re.sub(r"[^\w\-]", "", 網址.rstrip("/").split("/")[-1]) or "頻道"


def _跑streamlink(參數):
    """跑一次 streamlink（不抓音訊），回傳 (stdout, stderr)。等的時候每 0.2 秒看一次有沒有按「結束」，
    按了就殺掉子程序、丟出「已取消啟動」，不會卡住、也不留下背景程序。"""
    子 = subprocess.Popen([sys.executable, "-m", "streamlink_cli", *參數],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    while True:
        try:
            return 子.communicate(timeout=0.2)
        except subprocess.TimeoutExpired:
            if events.停止.is_set():
                子.kill()
                子.communicate()
                raise 直播錯誤("已取消啟動。") from None


def 檢查直播(網址, 查詢=None):
    """確認頻道有開播、能抓到音訊。有問題就丟出中文提示。回傳要用的串流名稱。
    查詢：YouTube 用（stream_info.背景查詢 的觀看頁資訊），失敗時拿來寫預定開始時間、判斷是不是錄好的影片。"""
    events.送出("stage", 階段="連線直播、確認有開播")
    輸出, _ = _跑streamlink(["--json", 網址])
    if platforms.判斷(網址).平台 == platforms.YOUTUBE:
        return _檢查YouTube(網址, 輸出, 查詢)
    try:
        資料 = json.loads(輸出)
    except Exception:
        raise 直播錯誤("無法檢查直播，請確認網址正確（例如 https://www.twitch.tv/頻道名稱）。")
    錯誤 = str(資料.get("error", ""))
    小寫 = 錯誤.lower()
    if 錯誤:
        if any(k in 小寫 for k in ["subscriber", "sub-only", "auth", "login", "oauth"]):
            raise 直播錯誤("這個直播需要訂閱或登入才能看，這個工具只支援公開直播。")
        if "no plugin" in 小寫 or "unable to open url" in 小寫:
            raise 直播錯誤("網址看起來不對，請確認是 Twitch 頻道網址。")
        raise 直播錯誤("頻道目前沒有開播，或網址有誤。")
    串流 = 資料.get("streams") or {}
    if not 串流:
        raise 直播錯誤("頻道目前沒有開播。")
    return "audio_only" if "audio_only" in 串流 else "worst"


# ---------- YouTube 開播檢查的白話訊息 ----------
# streamlink 的 --json 只說「No playable streams」，真正的原因（YouTube 的 playabilityStatus）只寫在一般模式的錯誤紀錄：
#   [plugins.youtube][error] Could not get video info - LOGIN_REQUIRED: Sign in to confirm you're not a bot
# 所以失敗時再跑一次一般模式讀這一行；觀看頁（背景查詢）的狀態與原因當補充（中文介面，原因是中文）。
YouTube訊息 = {
    "機器人": "YouTube 要求登入驗證（把這台電腦的連線判定成機器人），這台電腦目前無法擷取 YouTube 直播。"
             "請稍後再試，或換一個網路（例如手機熱點）再試。",
    "還沒開始": "這場直播還沒開始，請等開播後再按開始。",
    "會員": "這是會員限定的直播。第一版只支援公開直播，無法擷取。",
    "年齡": "這個直播有年齡限制（要登入確認年齡）。第一版只支援公開直播，無法擷取。",
    "登入": "這個直播需要登入才能看（例如私人直播）。第一版只支援公開直播，無法擷取。",
    "影片": "這是錄好的影片，不是正在進行的直播。目前只支援直播，請改用正在直播的網址。",
    "沒開播": "這個頻道目前沒有在直播，或網址有誤。",
    "網址": "網址看起來不對，請確認是 YouTube 直播網址（例如 https://www.youtube.com/@帳號/live）。",
    "無法檢查": "無法檢查直播，請確認網址正確（例如 https://www.youtube.com/@帳號/live）。",
}
_原因行 = re.compile(r"Could not get video info - ([A-Z_]+):\s*(.*)")


def YouTube原因種類(狀態, 原因):
    """playabilityStatus 的狀態與原因（英文或中文）→ YouTube訊息 的鍵；看不出來回傳 None。"""
    小 = (原因 or "").lower()
    if "not a bot" in 小 or "機器人" in 小:
        return "機器人"
    if 狀態 == "LIVE_STREAM_OFFLINE" or "will begin" in 小 or "後開始" in 小:
        return "還沒開始"
    if "member" in 小 or "會員" in 小:
        return "會員"
    if 狀態 == "AGE_CHECK_REQUIRED" or any(k in 小 for k in ("your age", "age-restricted", "inappropriate", "年齡", "不適合")):
        return "年齡"
    if 狀態 == "LOGIN_REQUIRED" or any(k in 小 for k in ("sign in", "private", "登入", "私人")):
        return "登入"
    return None


def YouTube錯誤訊息(種類, 預定開始=None):
    """種類 → 白話訊息；還沒開始而且讀得到預定時間就附上（本機時間）。"""
    if 種類 == "還沒開始" and 預定開始:
        時間字 = datetime.fromtimestamp(預定開始).strftime("%Y-%m-%d %H:%M")
        return f"這場直播還沒開始（預定 {時間字} 開始，本機時間），請等開播後再按開始。"
    return YouTube訊息[種類]


def _頁資訊(查詢):
    try:
        return (查詢.等() if 查詢 is not None else None) or {}
    except Exception:      # noqa: BLE001  只是補充說明，讀不到就當沒有
        return {}


def _是錄好的影片(頁):
    """觀看頁看得出是一部影片，而且不是正在直播、也不是預定的直播。"""
    if not 頁.get("影片ID") or 頁.get("即將開始") or 頁.get("狀態") == "LIVE_STREAM_OFFLINE":
        return False
    return 頁.get("直播中") is False or (頁.get("直播中") is None and 頁.get("直播內容") is False)


def _檢查YouTube(網址, 輸出, 查詢):
    try:
        資料 = json.loads(輸出)
    except ValueError:
        raise 直播錯誤(YouTube訊息["無法檢查"]) from None
    錯誤 = str(資料.get("error", ""))
    小寫 = 錯誤.lower()
    if 錯誤:
        if "no plugin" in 小寫 or "unable to open url" in 小寫:
            raise 直播錯誤(YouTube訊息["網址"])
        if "vod" in 小寫:
            raise 直播錯誤(YouTube訊息["影片"])
        if "protected" in 小寫:
            raise 直播錯誤(YouTube訊息["登入"])
        _, 紀錄 = _跑streamlink(["--loglevel", "error", 網址])     # 一般模式才看得到 YouTube 給的原因
        m = _原因行.search(紀錄 or "")
        頁 = _頁資訊(查詢)
        種類 = (YouTube原因種類(*m.groups()) if m else None) or YouTube原因種類(頁.get("狀態"), 頁.get("原因"))
        if 種類 is None and 頁.get("即將開始"):
            種類 = "還沒開始"
        if 種類 is None and _是錄好的影片(頁):
            種類 = "影片"
        raise 直播錯誤(YouTube錯誤訊息(種類 or "沒開播", 頁.get("預定開始")))
    串流 = 資料.get("streams") or {}
    if not 串流:
        raise 直播錯誤(YouTube訊息["沒開播"])
    # 直播一定是 HLS；只有一般 http 檔（360p 等）就是錄好的影片（streamlink 對影片也會回傳串流）
    if not any((v or {}).get("type") == "hls" for v in 串流.values()) or _是錄好的影片(_頁資訊(查詢)):
        raise 直播錯誤(YouTube訊息["影片"])
    return "audio_only" if "audio_only" in 串流 else "worst"     # YouTube 沒有 audio_only：最低畫質（144p）也有音軌


def 載入模型(語言):
    """GPU 優先，失敗退回 CPU。GPU 的錯誤要真的算一次才會出現，所以先試跑一段靜音。
    模型還沒下載過就先下載（first_run.準備模型：送出下載進度，失敗丟出白話的 模型下載錯誤）。
    確定沒有可用的 NVIDIA 顯示卡時，直接用 CPU 的模型，不必先下載顯示卡用的大模型。"""
    transcribe.找顯示卡函式庫()
    from faster_whisper import WhisperModel
    試音 = np.zeros(取樣率, dtype=np.float32)
    語言 = None if 語言 == "auto" else 語言
    if first_run.顯示卡可用() is False:
        events.送出("info", 印出="顯示卡（GPU）無法使用（沒有偵測到可用的 NVIDIA 顯示卡），改用 CPU，可能跟不上直播。")
    else:
        try:
            first_run.準備模型(transcribe.GPU_MODEL)
            model = WhisperModel(transcribe.GPU_MODEL, device="cuda", compute_type="float16")
            list(model.transcribe(試音, language=語言)[0])
            return model
        except first_run.模型下載錯誤:
            raise
        except Exception as e:
            events.送出("info", 印出=f"顯示卡（GPU）無法使用（{type(e).__name__}），改用 CPU，可能跟不上直播。")
    first_run.準備模型(transcribe.CPU_MODEL)       # 退回 CPU 時另外要 small：沒下載過一樣會顯示下載進度
    return WhisperModel(transcribe.CPU_MODEL, device="cpu", compute_type="int8")


class 信心太低(ValueError):
    pass


def 偵測語言(model, 音訊們, 保持=None):
    """用前幾段有人聲的音訊判斷語言，回傳語言代碼；失敗就印警告並退回 zh。
    保持：重新偵測時傳入目前的語言，信心太低或失敗就維持它，不退回 zh。
    結果一律用 language_detected 事件送出（含信心與狀態 ok／低信心／失敗），介面才能清楚告訴使用者。"""
    重新 = 保持 is not None
    信心 = None
    try:
        總分, 次數 = {}, len(音訊們)
        for 音訊 in 音訊們:
            語, 信心, _ = model.detect_language(音訊, vad_filter=True)
            總分[語] = 總分.get(語, 0) + 信心
        最佳 = max(總分, key=總分.get)
        信心 = 總分[最佳] / 次數
        if 信心 < 最低信心:
            raise 信心太低("信心太低")
        events.送出("info", 印出=f"偵測到語言：{config.語言名稱.get(最佳, 最佳)}（已鎖定）")
        events.送出("language_detected", 語言=最佳, 信心=信心, 狀態="ok", 重新偵測=重新)   # 介面的逐句字幕跟著切換原文／翻譯
        return 最佳
    except Exception as e:
        退回 = 保持 or "zh"
        events.送出("info", 印出=f"警告：語言偵測失敗（{e}），" + (f"維持{config.語言名稱.get(退回, 退回)}。" if 重新 else "改用中文。"))
        events.送出("language_detected", 語言=退回, 信心=信心, 狀態="低信心" if isinstance(e, 信心太低) else "失敗", 重新偵測=重新)
        return 退回


def 轉錄一段(model, 音訊, 語言):
    """回傳這一段的 [(段內秒數, 文字)]。過濾靜音與亂猜的文字。"""
    if np.abs(音訊).max() < 0.005:      # 幾乎全靜音，直接跳過
        return []
    段們, _ = model.transcribe(
        音訊, language=語言, vad_filter=True,
        condition_on_previous_text=False,   # 避免前面的字影響後面，造成重複
        initial_prompt=中文提示 if 語言 == "zh" else None,
    )
    結果 = []
    for s in 段們:
        文字 = s.text.strip()
        if 是幻聽(文字):
            continue
        # 「沒人講話」的機率常常誤判，所以要同時信心很低才丟；重複度太高（亂猜迴圈）也丟
        if not 文字 or (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0) or s.compression_ratio > 2.4:
            continue
        結果.append((s.start, 文字))
    return 結果


def 含人聲(音訊):
    """這一段是不是真的有人在說話：音量夠大，而且 VAD（語音偵測）找得到說話的部分。
    只有音樂、只有環境音、靜音都算沒有人聲。VAD 載不起來就只看音量（和以前一樣）。"""
    if np.abs(音訊).max() < 0.005:
        return False
    try:
        from faster_whisper.vad import get_speech_timestamps
        return bool(get_speech_timestamps(音訊))
    except (ImportError, ValueError, RuntimeError, OSError):
        return True


class 偵測緩存:
    """auto 模式鎖定語言之前：把「有人聲」的段先存著，湊到 偵測句數 段就交出來給語言偵測；沒人聲的段不算、繼續等下一段。"""

    def __init__(self):
        self.段們 = []

    def 加入(self, 段號, 音訊):
        """回傳 None = 還要繼續等；回傳 [(段號, 音訊), ...] = 可以偵測了（緩存同時清空）。"""
        if 含人聲(音訊):
            self.段們.append((段號, 音訊))
        if len(self.段們) >= 偵測句數:
            交出, self.段們 = self.段們, []
            return 交出
        return None


def 取得時軸(查詢, 平台=platforms.TWITCH):
    """等背景查詢的結果，建立這一場的時軸並送出 stream_info 事件。按了「結束」就丟出 直播錯誤。
    YouTube：延遲先用備援值，收到第一個音訊片段時再用 PDT 對齊（live_session.__iter__）。"""
    資訊 = 查詢.等()
    if events.停止.is_set():
        raise 直播錯誤("已取消啟動。")
    開播 = 資訊["開播"] if 資訊 else None
    連續 = 平台 == platforms.YOUTUBE and stream_clock.是連續直播(開播, time.time())
    if 平台 == platforms.YOUTUBE:
        軸 = stream_clock.時軸(開播=None if 連續 else 開播, 延遲=stream_clock.平台延遲(平台),
                             說明="依 YouTube 串流片段的時間戳對齊；讀不到時間戳才扣除約 "
                                  f"{stream_clock.平台延遲(平台):.0f} 秒估計的串流延遲")
        if 連續:
            軸.連續直播開播 = 開播
    else:
        軸 = stream_clock.時軸(開播=開播)
    stream_clock.設定目前(軸, 資訊)
    資訊 = 資訊 or {}
    if 連續:
        開播字 = datetime.fromtimestamp(開播).strftime("%Y-%m-%d %H:%M")
        印出 = (f"這是連續播出的直播（{開播字} 開播，已超過 24 小時），時間改為從開始擷取起算（前面加 +），"
              "直播稿和聊天室從同一個時間點算起。")
    else:
        印出 = None if 軸.有開播 else "抓不到開播時間，時間改為從開始擷取起算（前面加 +）。"
    events.送出("stream_info", 有開播=軸.有開播, 開播=軸.開播, 延遲=軸.延遲, 來源=資訊.get("來源"),
                直播主=資訊.get("直播主", ""), 標題=資訊.get("標題", ""), 遊戲=資訊.get("遊戲", ""),
                印出=印出)
    return 軸


class 片段時刻讀取:
    """在背景一直讀 yt_audio 的 stderr（不讀完管線會塞住），記下第一個片段的 PDT。"""

    def __init__(self, 管線):
        self.值 = None
        self._有了 = threading.Event()
        threading.Thread(target=self._讀, args=(管線,), daemon=True).start()

    def _讀(self, 管線):
        try:
            for 位元組 in 管線:
                值 = yt_audio.解析PDT行(位元組.decode("utf-8", "replace").strip())
                if 值 is not None and self.值 is None:
                    self.值 = 值
                    self._有了.set()
        except (OSError, ValueError):
            pass
        finally:
            self._有了.set()      # 管線結束（串流斷了）也不要讓人一直等

    def 等(self, 最久=3.0):
        """第一個位元組已經出來時，PDT 通常早就印了；最多等 最久 秒，讀不到回傳 None。"""
        self._有了.wait(最久)
        return self.值


def 對齊YouTube(軸, 片段時刻):
    """用第一個片段的 PDT 對齊時間，並在主控台說一行用了哪一種算法。"""
    if 軸.對齊串流時刻(片段時刻):
        events.送出("info", 印出=f"YouTube：時間依串流片段的時間戳對齊（這次實際串流延遲約 {軸.延遲:.1f} 秒）。")
    elif 軸.有開播:
        events.送出("info", 印出=f"YouTube：讀不到串流片段的時間戳，改用估計的串流延遲（約 {軸.延遲:.0f} 秒），時間可能差幾秒。")


def YouTube聊天網址(網址):
    """觀看頁讀到影片 ID 就用 watch?v=（頻道網址 /@帳號/live 要 yt-dlp 再找一次直播，換了場次也不會抓錯）。"""
    影片 = (stream_clock.資訊() or {}).get("影片ID")
    return f"https://www.youtube.com/watch?v={影片}" if 影片 else 網址


class live_session:
    """用法：s = live_session(網址)；s.稿路徑 是直播稿檔；for 秒, 行 in s: 一句一句吐出
    (直播秒數, "[h:mm:ss] 文字")，同時即時存成直播稿。秒數是直播實際進行時間（抓不到開播時間就從開始擷取起算，行首加 +）。"""

    時軸 = None      # 這一場的 stream_clock.時軸（__init__ 建立；測試可以直接指定）
    平台 = platforms.TWITCH     # __init__ 依網址判斷；測試可以直接指定

    def __init__(self, 網址, 語言="zh", 稿目錄=".", 用聊天室=True, 存音訊=True, 存稿=True, 存聊天=True):
        self.網址 = 網址
        self.語言 = 語言
        self.平台 = platforms.判斷(網址).平台 or platforms.TWITCH
        if self.平台 == platforms.YOUTUBE:      # 讀觀看頁，和 streamlink 的開播檢查並行；失敗時也拿來寫白話原因
            查詢 = stream_info.背景查詢(網址, 查法=stream_info.查YouTube直播)
            串流名 = 檢查直播(網址, 查詢)
        else:
            查詢 = stream_info.背景查詢(頻道名稱(網址))     # 和 streamlink 的開播檢查並行
            串流名 = 檢查直播(網址)
        里程碑.標記(里程碑.直播檢查完成)
        self.時軸 = 取得時軸(查詢, self.平台)
        events.送出("stage", 階段="尋找 ffmpeg")
        self.ffmpeg = 找ffmpeg()
        try:                     # 這次要用的轉錄模型還沒下載：先告訴啟動面板（等下載完才收起）
            first_run.預告(first_run.要用的模型(first_run.顯示卡可用()))
        except Exception:        # noqa: BLE001, S110  只是預告，失敗不影響開始
            pass
        self.串流名 = 串流名
        時間字 = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.稿路徑 = os.path.join(稿目錄, f"{頻道名稱(網址)}_{時間字}_直播稿.txt")
        self.存稿 = 存稿          # False：直播稿只送到介面、不寫檔（稿路徑仍用來決定其他檔名）
        # 每段音訊存成 wav，之後轉錄有問題時可以用同一段音訊重現
        self.音訊資料夾 = os.path.join(稿目錄, f"{頻道名稱(網址)}_{時間字}_音訊") if 存音訊 else None
        self.存了段數 = 0
        self.存了位元組 = 0
        self._警告過 = False
        self.聊天 = None     # 有聊天室時，這裡是 chat_capture.聊天室 或 yt_chat.聊天室 物件（對外用法一樣）
        if 用聊天室 and self.平台 == platforms.YOUTUBE:
            import yt_chat
            events.送出("stage", 階段="準備聊天室")
            self.聊天 = yt_chat.聊天室(
                YouTube聊天網址(網址), os.path.join(稿目錄, f"{頻道名稱(網址)}_{時間字}_聊天室.txt") if 存聊天 else None)
        elif 用聊天室:
            import chat_capture
            events.送出("stage", 階段="準備聊天室")
            self.聊天 = chat_capture.聊天室(
                頻道名稱(網址), os.path.join(稿目錄, f"{頻道名稱(網址)}_{時間字}_聊天室.txt") if 存聊天 else None)

    def _存音訊(self, 資料, 序號, 起始秒):
        """把這一段音訊存成 wav，檔名像 0001_00-20.wav（序號_起始秒-結束秒）。失敗就停止存檔，不影響轉錄。"""
        if not self.音訊資料夾:
            return
        try:
            os.makedirs(self.音訊資料夾, exist_ok=True)
            結束秒 = 起始秒 + len(資料) // 2 // 取樣率
            路徑 = os.path.join(self.音訊資料夾, f"{序號:04d}_{起始秒:02d}-{結束秒:02d}.wav")
            with wave.open(路徑, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(取樣率)
                w.writeframes(資料[: len(資料) // 2 * 2])
            self.存了段數 += 1
            self.存了位元組 += os.path.getsize(路徑)
            if self.存了位元組 > 2 * 1024 ** 3 and not self._警告過:
                self._警告過 = True
                events.送出("info", 印出=f"\n警告：這場直播的音訊已超過 2 GB（{self.存了位元組 / 1024 ** 2:.0f} MB），不會自動刪除，請留意硬碟空間。")
        except Exception as e:
            events.送出("info", 印出=f"\n警告：音訊存檔失敗（{type(e).__name__}），之後不再存音訊，轉錄照常進行。")
            self.音訊資料夾 = None

    def 音訊統計(self):
        """結束時印的一行統計；沒有存音訊就回傳 None。"""
        if not self.存了段數:
            return None
        return f"音訊：存了 {self.存了段數} 段，共 {self.存了位元組 / 1024 ** 2:.1f} MB（{self.音訊資料夾}）"

    def __iter__(self):
        events.送出("info", 印出="載入轉錄模型中...")
        model = 載入模型(self.語言)
        events.送出("model", 狀態="就緒")
        里程碑.標記(里程碑.模型載入完成)
        片段時刻 = None
        if self.平台 == platforms.YOUTUBE:
            p1 = subprocess.Popen([sys.executable, yt_audio.__file__, self.網址, self.串流名],     # noqa: S603  自己的 yt_audio.py
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            片段時刻 = 片段時刻讀取(p1.stderr)
        else:
            p1 = subprocess.Popen(
                [sys.executable, "-m", "streamlink_cli", "--loglevel", "error", "--stdout",
                 self.網址, self.串流名],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        p2 = subprocess.Popen(
            [self.ffmpeg, "-loglevel", "error", "-i", "pipe:0", "-vn", "-ac", "1",
             "-ar", str(取樣率), "-f", "s16le", "pipe:1"],
            stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        p1.stdout.close()
        里程碑.標記(里程碑.擷取已啟動)
        if self.時軸 is None:
            self.時軸 = stream_clock.時軸()
        軸 = self.時軸
        if self.聊天:
            self.聊天.開始(軸.時鐘(), 軸)   # 聊天室和直播稿用同一個時軸（同一套直播秒）

        佇列 = queue.Queue()

        def 讀聲音():                      # 另開一條線一直讀，轉錄慢的時候聲音也不會漏掉
            if hasattr(p2.stdout, "peek"):
                p2.stdout.peek(1)          # 等到第一個位元組出現（不取走），這個時刻當作音訊第 0 秒
            軸.開始()
            if 片段時刻 is not None:
                對齊YouTube(軸, 片段時刻.等())
            while True:
                資料 = p2.stdout.read(每段位元組)
                if not 資料:
                    佇列.put(None)
                    return
                佇列.put((資料, 軸.時鐘()))     # 一起記下收滿的時刻，給漂移校正用

        threading.Thread(target=讀聲音, daemon=True).start()
        events.送出("info", 印出="開始擷取直播（Ctrl+C 結束）。" + (f"直播稿即時存到：{self.稿路徑}" if self.存稿 else "直播稿不存檔。"))

        第幾段, 上一句, 緩存 = 0, "", 偵測緩存()
        自動 = self.語言 == "auto"      # 一開始就是自動：才允許「重新偵測」
        重新前的語言 = None
        try:
            with open(self.稿路徑 if self.存稿 else os.devnull, "w", encoding="utf-8") as 稿:
                稿.write(stream_clock.檔頭())
                while True:
                    try:
                        資料 = 佇列.get(timeout=1)
                    except queue.Empty:
                        if events.停止.is_set():
                            return
                        continue            # 每秒醒來一次，讓 Ctrl+C 能生效
                    if events.停止.is_set():   # 介面按了停止
                        return
                    if 資料 is None:
                        events.送出("info", 印出="\n直播串流已結束。")
                        return
                    資料, 收滿時刻 = 資料
                    補 = 軸.段收滿((第幾段 + 1) * 段秒數, 收滿時刻)
                    if 補:
                        events.送出("info", 印出=f"\n直播音訊中斷約 {補:.0f} 秒（可能是廣告或斷線），時間已往前校正。")
                    開始 = time.time()
                    里程碑.標記(里程碑.第一段收滿, 分段設定秒=段秒數, 實際秒=round(len(資料) / 2 / 取樣率, 2))
                    self._存音訊(資料, 第幾段 + 1, 第幾段 * 段秒數)
                    音訊 = np.frombuffer(資料, dtype=np.int16).astype(np.float32) / 32768.0
                    待轉 = [(第幾段, 音訊)]
                    if 自動 and events.重新偵測.is_set():     # 按了「重新偵測」：清掉結果，這一段起重新湊有人聲的音訊（串流不中斷）
                        events.重新偵測.clear()
                        if self.語言 != "auto":
                            重新前的語言, self.語言, 緩存 = self.語言, "auto", 偵測緩存()
                    if self.語言 == "auto":      # 還沒鎖定：有人聲的段先存著，湊夠了再一起判斷
                        待轉 = []
                        湊好 = 緩存.加入(第幾段, 音訊)
                        if 湊好:
                            self.語言 = 偵測語言(model, [a for _, a in 湊好], **({"保持": 重新前的語言} if 重新前的語言 else {}))
                            重新前的語言 = None
                            里程碑.標記(里程碑.語言偵測完成, 語言=self.語言)
                            待轉 = 湊好
                    for 段號, 音訊 in 待轉:
                        里程碑.標記(里程碑.第一段送轉錄, 語言=self.語言)
                        結果們 = 轉錄一段(model, 音訊, self.語言)
                        里程碑.標記(里程碑.第一段轉錄完成, 句數=len(結果們))
                        for 段內秒, 文字 in 結果們:
                            if 文字 == 上一句:   # 跟上一句一模一樣，多半是亂猜
                                continue
                            上一句 = 文字
                            秒 = 軸.音訊秒轉直播秒(段號 * 段秒數 + 段內秒)
                            行 = f"{軸.標記(秒)} {文字}"
                            稿.write(行 + "\n")
                            稿.flush()
                            里程碑.標記(里程碑.第一句文字稿)
                            yield 秒, 行
                    花費 = time.time() - 開始
                    if 花費 > 段秒數:
                        events.送出("status", 跟上=False,
                                    印出=f"\n警告：轉錄跟不上直播（這一段 {段秒數} 秒的聲音花了 {花費:.0f} 秒轉錄）")
                    else:
                        events.送出("status", 跟上=True)
                    第幾段 += 1
        finally:
            if self.聊天:
                self.聊天.關閉()
            for p in (p2, p1):
                try:
                    p.kill()
                except Exception:
                    pass
