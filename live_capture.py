# Twitch 直播即時轉錄：把直播聲音一段一段轉成文字，一句一句吐給 live_topics.py
# 流程：streamlink（抓音訊）→ ffmpeg（轉 16kHz 單聲道）→ 每段 8～20 秒（依字幕速度段位）→ faster-whisper
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
import stream_info   # 開播時間、標題、分類、直播主（不需要金鑰）
import stream_clock  # 音訊秒數、收到時刻 → 直播實際進行時間

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


def 檢查直播(網址):
    """確認頻道有開播、能抓到音訊。有問題就丟出中文提示。回傳要用的串流名稱。"""
    events.送出("stage", 階段="連線直播、確認有開播")
    子 = subprocess.Popen([sys.executable, "-m", "streamlink_cli", "--json", 網址],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    while True:              # 等結果的同時每 0.2 秒看一次有沒有要結束，按「結束」時才不會卡住、也不留下背景程序
        try:
            輸出, _ = 子.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if events.停止.is_set():
                子.kill()
                子.communicate()
                raise 直播錯誤("已取消啟動。") from None
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


def 載入模型(語言):
    """GPU 優先，失敗退回 CPU。GPU 的錯誤要真的算一次才會出現，所以先試跑一段靜音。"""
    transcribe.找顯示卡函式庫()
    from faster_whisper import WhisperModel
    試音 = np.zeros(取樣率, dtype=np.float32)
    語言 = None if 語言 == "auto" else 語言
    try:
        model = WhisperModel(transcribe.GPU_MODEL, device="cuda", compute_type="float16")
        list(model.transcribe(試音, language=語言)[0])
        return model
    except Exception as e:
        events.送出("info", 印出=f"顯示卡（GPU）無法使用（{type(e).__name__}），改用 CPU，可能跟不上直播。")
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


def 取得時軸(查詢):
    """等背景查詢的結果，建立這一場的時軸並送出 stream_info 事件。按了「結束」就丟出 直播錯誤。"""
    資訊 = 查詢.等()
    if events.停止.is_set():
        raise 直播錯誤("已取消啟動。")
    軸 = stream_clock.時軸(開播=資訊["開播"] if 資訊 else None)
    stream_clock.設定目前(軸, 資訊)
    資訊 = 資訊 or {}
    events.送出("stream_info", 有開播=軸.有開播, 開播=軸.開播, 延遲=軸.延遲, 來源=資訊.get("來源"),
                直播主=資訊.get("直播主", ""), 標題=資訊.get("標題", ""), 遊戲=資訊.get("遊戲", ""),
                印出=None if 軸.有開播 else "抓不到開播時間，時間改為從開始擷取起算（前面加 +）。")
    return 軸


class live_session:
    """用法：s = live_session(網址)；s.稿路徑 是直播稿檔；for 秒, 行 in s: 一句一句吐出
    (直播秒數, "[h:mm:ss] 文字")，同時即時存成直播稿。秒數是直播實際進行時間（抓不到開播時間就從開始擷取起算，行首加 +）。"""

    時軸 = None      # 這一場的 stream_clock.時軸（__init__ 建立；測試可以直接指定）

    def __init__(self, 網址, 語言="zh", 稿目錄=".", 用聊天室=True, 存音訊=True, 存稿=True, 存聊天=True):
        self.網址 = 網址
        self.語言 = 語言
        查詢 = stream_info.背景查詢(頻道名稱(網址))     # 和 streamlink 的開播檢查並行
        串流名 = 檢查直播(網址)
        里程碑.標記(里程碑.直播檢查完成)
        self.時軸 = 取得時軸(查詢)
        events.送出("stage", 階段="尋找 ffmpeg")
        self.ffmpeg = 找ffmpeg()
        self.串流名 = 串流名
        時間字 = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.稿路徑 = os.path.join(稿目錄, f"{頻道名稱(網址)}_{時間字}_直播稿.txt")
        self.存稿 = 存稿          # False：直播稿只送到介面、不寫檔（稿路徑仍用來決定其他檔名）
        # 每段音訊存成 wav，之後轉錄有問題時可以用同一段音訊重現
        self.音訊資料夾 = os.path.join(稿目錄, f"{頻道名稱(網址)}_{時間字}_音訊") if 存音訊 else None
        self.存了段數 = 0
        self.存了位元組 = 0
        self._警告過 = False
        self.聊天 = None     # 有聊天室時，這裡是 chat_capture.聊天室 物件
        if 用聊天室:
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
        里程碑.標記(里程碑.模型載入完成)
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
