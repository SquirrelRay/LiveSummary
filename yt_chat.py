# YouTube 聊天室擷取（yt-dlp 的 live_chat，免登入、免金鑰）：對外用法和 chat_capture.聊天室 一樣
# （開始／取出／關閉／訊息們／收到／過濾／存檔路徑），引擎、面板、存檔、聊天室翻譯不用知道是哪個平台。
# 在程式內呼叫 yt-dlp（同一個程序、背景執行緒），不另開 python 程序：打包成 .exe 後 sys.executable 是 .exe 本身，
#   `python -m yt_dlp` 會失效（streamlink 已經有這個問題）。
# yt-dlp 把聊天室一批一批寫進系統暫存資料夾的 .live_chat.json.part（每行一個 JSON），這裡每 讀取間隔秒 讀一次「新增的部分」
#   （記住讀到哪裡，不從頭讀）；這一輪結束（包含出錯、按停止）後整個暫存資料夾刪掉。
# 時間：每則留言的發送時刻（timestampUsec）→ 時軸.發送時刻轉直播秒（發送 − 開播；抓不到開播用第一段 PDT），不扣串流延遲。
# 舊留言：剛連上時 YouTube 會先送一批之前的留言，發送時刻早於開始擷取的丟掉（算在 過濾，另外記在 舊留言）。
# 內容：表情（runs 裡另外分開的 emoji）組文字時拿掉；只剩表情的留言用表情本身（標準表情字元，自訂表情用 □）表示，
#       沒有字母數字，聊天室翻譯照現有規則當純表情、不翻。Super Chat／Super Sticker 前面加「【SC】」
#       （Super Sticker 沒有文字寫「【SC】貼圖」）。會員加入、置頂、系統通知、刪除留言等不是留言，不算進 收到。
# 停止：關閉() 後讀取執行緒最多 停止等待秒 內結束（關存檔、不再送事件）。yt-dlp 在兩批之間的等待（time.sleep）換成
#       收到停止就中斷的版本，下載中的進度回呼也會中斷；網路卡住時 yt-dlp 的執行緒是背景執行緒、不擋程式結束，
#       之後不會再寫我們的存檔，暫存資料夾等它結束時再刪。
# 失效：一輪下來一則都沒收到算失敗，重試 3 次後在主控台與膠囊提示說明，摘要和字幕照常。
import gc
import json
import os
import shutil
import tempfile
import threading
import time

import chat_capture  # 只用 是洗版（和 Twitch 同一套洗版規則）
import events
import stream_clock  # 存檔開頭的說明
import timefmt

# YouTube 上常見的聊天機器人（2026-10-14 查證有支援 YouTube 的：Nightbot、Fossabot、StreamElements、Streamlabs Cloudbot）；
# 和 Twitch 的名單分開，Twitch 的過濾不受影響。名稱比對前去掉 @、不分大小寫；名字以 bot 結尾的也當機器人（和 Twitch 一樣）。
機器人 = {"nightbot", "fossabot", "streamelements", "streamlabs", "streamlabsbot", "cloudbot"}
重試次數 = 3
重試間隔秒 = 5
讀取間隔秒 = 0.5
停止等待秒 = 4.0          # 關閉() 後最多等 yt-dlp 這麼久（加上讀取間隔，5 秒內收尾）
等基準秒 = 30             # + 模式還沒收到音訊（不知道零點）時，留言最多先等這麼久，之後用收到時刻換算
失效訊息 = "YouTube 聊天室暫時抓不到（可能是 YouTube 改版），摘要和字幕照常；更新程式後可能會恢復。"
暫存前綴 = "直播摘要_YT聊天室_"
舊暫存秒 = 600            # 超過這麼久沒動過的暫存資料夾當作上次留下的
檔名 = "chat"             # yt-dlp 寫成 chat.live_chat.json.part（結束時改名成 chat.live_chat.json）

留言種類 = ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer", "liveChatPaidStickerRenderer")


def 是機器人(名稱):
    名稱 = 名稱.lstrip("@").lower()
    return 名稱.endswith("bot") or 名稱 in 機器人


def 組文字(runs):
    """message.runs → (文字, 純表情)。表情拿掉；只剩表情時回傳表情本身（標準表情字元、自訂表情 □）與 純表情=True。"""
    字們, 表情們 = [], []
    for r in runs or []:
        if "text" in r:
            字們.append(r["text"])
        elif "emoji" in r:
            e = r["emoji"] or {}
            表情們.append("□" if e.get("isCustomEmoji") or len(e.get("emojiId", "")) > 8 else e.get("emojiId", "□"))
    文字 = " ".join("".join(字們).split())
    if 文字:
        return 文字, False
    return ("".join(表情們), True) if 表情們 else ("", False)


def _簡單字(物件):
    物件 = 物件 or {}
    return 物件.get("simpleText") or "".join(r.get("text", "") for r in 物件.get("runs", []))


def 解析動作(行):
    """yt-dlp 寫的一行 JSON → ("留言", 發送時刻(epoch 秒), 使用者, 內容, 純表情)、("系統",) 或 None（看不懂、不是聊天項目）。"""
    try:
        資料 = json.loads(行)
    except ValueError:
        return None
    動作們 = ((資料.get("replayChatItemAction") or {}).get("actions")) or []
    if not 動作們:
        return None
    動作 = 動作們[0]
    項目 = (動作.get("addChatItemAction") or {}).get("item")
    if not isinstance(項目, dict):
        return ("系統",)        # 置頂（addBannerToLiveChatCommand）、上方橫條、刪除留言、投票等
    種類 = next((k for k in 留言種類 if k in 項目), None)
    if 種類 is None:
        return ("系統",)        # 會員加入（liveChatMembershipItemRenderer）、系統通知、贈送會員等
    r = 項目[種類]
    try:
        發送 = int(r["timestampUsec"]) / 1e6
    except (KeyError, TypeError, ValueError):
        return None
    使用者 = _簡單字(r.get("authorName")) or "（匿名）"
    文字, 純表情 = 組文字((r.get("message") or {}).get("runs"))
    if 種類 == "liveChatPaidStickerRenderer":
        文字, 純表情 = "【SC】" + (文字 or "貼圖"), False
    elif 種類 == "liveChatPaidMessageRenderer":
        文字, 純表情 = "【SC】" + (文字 or "（沒有留言）"), False
    if not 文字:
        return None
    return ("留言", 發送, 使用者, 文字, 純表情)


# ---------- yt-dlp 的等待改成可中斷 ----------
class 已停止(Exception):       # 從 yt-dlp 裡面丟出來，讓它停下
    pass


_停們 = {}                     # 執行緒 id → 這一輪的停止旗標（只有我們開的下載執行緒會在裡面）


class _可中斷時間:
    """取代 yt_dlp.downloader.youtube_live_chat 裡的 time 模組：sleep 收到停止就中斷，其他照原本的 time。
    不是我們的下載執行緒呼叫時，sleep 就是原本的 time.sleep。"""

    def __getattr__(self, 名稱):
        return getattr(time, 名稱)

    @staticmethod
    def sleep(秒):
        停 = _停們.get(threading.get_ident())
        if 停 is None:
            return time.sleep(秒)
        if 停.wait(秒):
            raise 已停止()
        return None


def _裝上可中斷等待():
    """yt-dlp 改版、找不到這個模組時就不裝（停止時改靠背景執行緒，不會卡住程式結束）。"""
    try:
        import yt_dlp.downloader.youtube_live_chat as 模組
    except ImportError:
        return False
    if not isinstance(getattr(模組, "time", None), _可中斷時間):
        模組.time = _可中斷時間()
    return True


class _安靜紀錄:
    """yt-dlp 的輸出不印到主控台，只記最後一個錯誤（除錯用）。"""

    def __init__(self):
        self.最後錯誤 = ""

    def debug(self, 訊息):
        pass

    def info(self, 訊息):
        pass

    def warning(self, 訊息):
        pass

    def error(self, 訊息):
        if "Deprecated Feature" not in 訊息:
            self.最後錯誤 = 訊息


def yt_dlp下載(網址, 資料夾, 停, 紀錄):
    """在目前的執行緒裡跑 yt-dlp，只下載 live_chat，寫到 資料夾/chat.live_chat.json.part；直播結束或出錯才回來。"""
    import yt_dlp
    _裝上可中斷等待()

    def 進度(_):
        if 停.is_set():
            raise 已停止()

    選項 = {"skip_download": True, "writesubtitles": True, "subtitleslangs": ["live_chat"],
          "outtmpl": os.path.join(資料夾, 檔名 + ".%(ext)s"), "quiet": True, "noprogress": True,
          "logger": 紀錄, "progress_hooks": [進度], "socket_timeout": 10, "retries": 3, "fragment_retries": 3}
    with yt_dlp.YoutubeDL(選項) as ydl:
        ydl.download([網址])


def 刪資料夾(資料夾):
    """刪暫存資料夾。yt-dlp 被中斷時檔案可能還沒關（等垃圾回收才關），先回收再刪，刪不掉就重試幾次。"""
    for _ in range(10):
        gc.collect()
        shutil.rmtree(資料夾, ignore_errors=True)
        if not os.path.exists(資料夾):
            return True
        time.sleep(0.2)
    return False


def 清舊暫存(現在=None):
    """上次程式結束時 yt-dlp 還沒停下（背景執行緒來不及刪）留下的暫存資料夾：超過 舊暫存秒 沒動過的刪掉。
    正在用的資料夾 yt-dlp 每一輪都會新增、刪除片段檔，修改時間一直在更新，不會被刪到。"""
    現在 = time.time() if 現在 is None else 現在
    try:
        名們 = [n for n in os.listdir(tempfile.gettempdir()) if n.startswith(暫存前綴)]
    except OSError:
        return
    for 名 in 名們:
        路徑 = os.path.join(tempfile.gettempdir(), 名)
        try:
            if 現在 - os.path.getmtime(路徑) > 舊暫存秒:
                shutil.rmtree(路徑, ignore_errors=True)
        except OSError:
            pass


class 下載工作:
    """一輪 yt-dlp 下載（背景執行緒）＋它的暫存資料夾。"""

    def __init__(self, 網址, 下載=yt_dlp下載):
        清舊暫存()
        self.資料夾 = tempfile.mkdtemp(prefix=暫存前綴)
        self.紀錄 = _安靜紀錄()
        self.錯誤 = None
        self.停 = threading.Event()
        self.完 = threading.Event()
        self._鎖 = threading.Lock()
        self._自己刪 = False
        self.執行緒 = threading.Thread(target=self._跑, args=(網址, 下載), daemon=True)
        self.執行緒.start()

    def _跑(self, 網址, 下載):
        _停們[threading.get_ident()] = self.停
        try:
            下載(網址, self.資料夾, self.停, self.紀錄)
        except BaseException as e:      # noqa: BLE001  任何錯誤都交給讀取端重試，不能讓例外跑出背景執行緒
            self.錯誤 = f"{type(e).__name__}: {e}"     # 只留文字：留著例外物件，它的 traceback 會讓 yt-dlp 的 .part 一直開著、刪不掉
        finally:
            _停們.pop(threading.get_ident(), None)
            with self._鎖:
                self.完.set()
                刪 = self._自己刪
            if 刪:
                刪資料夾(self.資料夾)

    def 收尾(self, 等秒):
        """叫它停下並刪暫存資料夾。等秒內結束就馬上刪；沒結束就交給下載執行緒結束時自己刪。回傳是否已結束。"""
        self.停.set()
        self.完.wait(等秒)
        with self._鎖:
            if not self.完.is_set():
                self._自己刪 = True
                return False
        刪資料夾(self.資料夾)
        return True


class 增量讀取:
    """讀 yt-dlp 寫的 JSON 行檔：記住讀到哪裡，每次只讀新增的部分；最後一行沒寫完的留到下次。"""

    def __init__(self, 資料夾):
        self.資料夾 = 資料夾
        self.位置 = 0
        self._殘 = b""

    def _路徑(self):
        for 名 in (檔名 + ".live_chat.json.part", 檔名 + ".live_chat.json"):     # 下載結束時 yt-dlp 會改名
            路徑 = os.path.join(self.資料夾, 名)
            if os.path.exists(路徑):
                return 路徑
        return None

    def 新行(self):
        路徑 = self._路徑()
        if 路徑 is None:
            return []
        try:
            with open(路徑, "rb") as 檔:      # 每次開了馬上關，不擋 yt-dlp 改名
                檔.seek(self.位置)
                新 = 檔.read()
        except OSError:
            return []
        self.位置 += len(新)
        *行們, self._殘 = (self._殘 + 新).split(b"\n")
        return [x.decode("utf-8", "replace") for x in 行們 if x.strip()]


class 聊天室:
    def __init__(self, 網址, 存檔路徑, 下載=yt_dlp下載):
        """網址：YouTube 直播網址（最好是 watch?v=影片ID）。下載：測試可換成假的（不連網）。"""
        self.網址 = 網址
        self.存檔路徑 = 存檔路徑
        self.訊息們 = []        # 通過過濾的留言：(秒, 使用者, 內容)
        self.收到 = 0           # 收到的留言（含舊留言、機器人；不含系統訊息）
        self.過濾 = 0
        self.舊留言 = 0         # 開始擷取前送的（過濾 的一部分）
        self.系統訊息 = 0       # 會員加入、置頂等（不算留言）
        self.連線中 = False
        self.失效 = False
        self._下載 = 下載
        self._鎖 = threading.Lock()
        self._停 = threading.Event()
        self._起點 = None
        self._時軸 = None
        self._待換算 = []       # 還不能換算時間的留言：(發送時刻, 使用者, 內容, 收到時刻)
        self.執行緒 = None

    def 開始(self, 起點, 時軸=None):
        """起點：開始擷取的時刻（time.time() 的值），早於這個時刻送的留言當作舊留言。時軸：這一場的 stream_clock.時軸。"""
        self._起點 = 起點
        self._時軸 = 時軸
        self.執行緒 = threading.Thread(target=self._跑, daemon=True)
        self.執行緒.start()

    def 關閉(self):
        self._停.set()

    def 取出(self, 開始秒, 結束秒):
        with self._鎖:
            return [m for m in self.訊息們 if 開始秒 < m[0] <= 結束秒]

    # ---------- 時間 ----------
    def _換算(self, 發送, 收到時刻, 強制=False):
        """發送時刻 → (秒, 時間字)；還不能定下來回傳 None（強制=True 時用收到時刻換算）。"""
        軸 = self._時軸
        if 軸 is None:
            秒 = max(0.0, 發送 - self._起點)
            return 秒, timefmt.秒轉字(秒)
        秒 = 軸.發送時刻轉直播秒(發送)
        if 秒 is None:
            if not 強制:
                return None
            秒 = 軸.時刻轉直播秒(收到時刻)
        return 秒, 軸.字(秒)

    def _放出(self, 檔, 強制=False):
        現在 = time.time()
        while self._待換算:
            發送, 使用者, 內容, 收到時刻 = self._待換算[0]
            結果 = self._換算(發送, 收到時刻, 強制 or 現在 - 收到時刻 >= 等基準秒)
            if 結果 is None:
                return
            self._待換算.pop(0)
            秒, 時間字 = 結果
            with self._鎖:
                self.訊息們.append((秒, 使用者, 內容))
            檔.write(f"[{時間字}] {使用者}: {內容}\n")
            檔.flush()
            events.送出("chat_line", 秒=秒, 時間字=時間字, 使用者=使用者, 內容=內容, 編號=events.新留言編號())

    # ---------- 讀取 ----------
    def 處理行(self, 行, 檔):
        結果 = 解析動作(行)
        if 結果 is None:
            return
        if 結果[0] == "系統":
            self.系統訊息 += 1
            return
        _, 發送, 使用者, 內容, 純表情 = 結果
        self.收到 += 1
        if 發送 < self._起點:
            self.舊留言 += 1
            self.過濾 += 1
            return
        if 是機器人(使用者) or 內容.startswith("!") or (not 純表情 and chat_capture.是洗版(內容)):
            self.過濾 += 1
            return
        self._待換算.append((發送, 使用者, 內容, time.time()))
        self._放出(檔)

    def _一輪(self, 檔):
        """跑一輪 yt-dlp，邊寫邊讀；回傳這一輪有沒有讀到任何資料。"""
        工作 = 下載工作(self.網址, self._下載)
        讀 = 增量讀取(工作.資料夾)
        有資料 = False
        try:
            while not self._停.is_set():
                完 = 工作.完.is_set()
                for 行 in 讀.新行():
                    if self._停.is_set():
                        break
                    有資料 = self.連線中 = True
                    self.處理行(行, 檔)
                self._放出(檔)
                if 完:
                    break
                self._停.wait(讀取間隔秒)
        finally:
            工作.收尾(停止等待秒 if self._停.is_set() else 1.0)
        return 有資料

    def _跑(self):
        失敗 = 0
        with open(self.存檔路徑 or os.devnull, "w", encoding="utf-8") as 檔:      # 存檔路徑 None = 不存聊天室
            檔.write(stream_clock.檔頭())
            while not self._停.is_set():
                try:
                    有資料 = self._一輪(檔)
                except Exception:      # noqa: BLE001  讀取端出錯也只算這一輪失敗
                    有資料 = False
                self.連線中 = False
                if self._停.is_set():
                    break
                失敗 = 0 if 有資料 else 失敗 + 1
                if 失敗 > 重試次數:
                    self.失效 = True
                    events.送出("info", 印出="\n" + 失效訊息, 膠囊=失效訊息)
                    break
                self._停.wait(重試間隔秒)
            if not self._停.is_set():
                self._放出(檔, 強制=True)
