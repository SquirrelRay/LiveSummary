# 直播時鐘：把「音訊秒數」和「收到的時刻」換成直播實際進行時間（直播秒），對齊音訊內容（= Twitch 重播的時間軸）。
#   有開播時間：直播秒 = 收到時刻 − 開播時間 − 延遲秒（串流延遲：音訊內容比「現在 − 開播時間」晚多少）
#   抓不到開播時間：以收到第一段音訊的時刻當 0，時間字前面加「+」（例如 [+12:34]）
# 每句話：直播秒 = 第一段音訊的直播秒 + 音訊秒數 + 漂移補償；聊天室：直播秒 = 收到時刻 − 開播時間 − 延遲秒（和直播稿同一套）。
# YouTube：音訊第 0 秒的直播秒 = 第一個 HLS 片段的 PDT（直播端實際時刻）− 開播時間，不靠估計的延遲（對齊串流時刻）；
#          讀不到 PDT 才用下面的 YouTube 延遲秒（備援）。
#          聊天室給的是留言的「發送時刻」（直播端的實際時刻，和 PDT 同一種時間）：直播秒 = 發送時刻 − 開播，不扣延遲；
#          抓不到開播時間（+ 模式）時用 發送時刻 − 第一段PDT（音訊第 0 秒，和直播稿同一個零點）。見 發送時刻轉直播秒。
#          開播超過 24 小時（24 小時不停播的頻道）當作連續直播：不用開播時間，改從開始擷取起算（+ 模式），見 是連續直播。
# 漂移校正：廣告被濾掉、斷線重連都會讓音訊少一段，句子的時間就會越來越落後；
#           每段收滿時比較「用時鐘推算」和「用音訊累計」的直播秒，連續兩段都落後超過門檻才往前補（只往前、不倒退）。
import threading
import time
from datetime import datetime

import timefmt

延遲秒 = 11.0          # 2026-10-12 量 13 個頻道（2 秒分段）的中位數約 10.9 秒；4 秒分段的頻道約 19 秒，誤差較大
# YouTube（只在讀不到 PDT 時用）：2026-10-14 用 PDT 量 10 次（9 個新聞／節目直播），一般延遲模式 18.5～24.0 秒、
# 低延遲模式（2 秒分段）10.4 秒，中位數約 19.4 秒；直播主選的延遲模式不同就會差很多，所以只當備援。
YouTube延遲秒 = 20.0
平台延遲秒 = {"twitch": 延遲秒, "youtube": YouTube延遲秒}


def 平台延遲(平台):
    """平台（platforms.TWITCH／YOUTUBE）→ 串流延遲秒；認不出來用 Twitch 的。"""
    return 平台延遲秒.get(平台, 延遲秒)

連續直播秒 = 24 * 3600   # 開播超過這麼久就當作連續直播（24 小時不停播的頻道，開播時間可能是好幾年前）


def 是連續直播(開播, 現在=None):
    """開播時刻（epoch 秒）離現在超過 24 小時 → True（時間改從開始擷取起算，不然會顯示成好幾萬小時）。"""
    if 開播 is None:
        return False
    return (time.time() if 現在 is None else 現在) - 開播 > 連續直播秒


漂移門檻秒 = 8.0        # 比第一段的落後量多出這麼多才算掉段（網路一時卡住、之後會補回的不算）
漂移確認次數 = 2        # 連續幾段都超過門檻才補（一時卡住通常下一段就追回來了）


class 時軸:
    def __init__(self, 開播=None, 時鐘=time.time, 延遲=延遲秒, 說明=None):
        """開播：開播時刻（epoch 秒），None = 抓不到開播時間。時鐘：測試可換成假時鐘。
        說明：存檔開頭「時間怎麼對齊」那句（None = 「已扣除約 N 秒串流延遲」）。"""
        self.開播, self.時鐘, self.延遲, self.說明 = 開播, 時鐘, 延遲, 說明
        self.串流時刻對齊 = False     # True = 已用第一個片段的 PDT 對齊（YouTube）
        self.第一段PDT = None        # 音訊第 0 秒的 PDT（YouTube；抓不到開播時間時也記，聊天室用發送時刻換算時要用）
        self.對齊完成 = False        # YouTube：已經試過用 PDT 對齊（不管讀不讀得到），聊天室的發送時刻換算可以定下來
        self.連續直播開播 = None     # 連續直播（開播超過 24 小時）：原本的開播時刻，只寫在存檔開頭；時間照 + 模式
        self.基準 = 開播 + 延遲 if 開播 is not None else None    # 直播秒 = 時刻 − 基準
        self.偏移 = 0.0          # 音訊第 0 秒的直播秒
        self.補償 = 0.0          # 漂移校正累計往前補了幾秒
        self.已開始 = False
        self._基線 = None        # 第一段收滿時的落後量（串流一開始會一次送出幾段，所以不是 0）
        self._超過們 = []
        self._鎖 = threading.Lock()

    @property
    def 有開播(self):
        return self.開播 is not None

    @property
    def 加號(self):
        return self.開播 is None

    def 開始(self, 時刻=None):
        """收到第一個音訊位元組時呼叫一次。"""
        時刻 = self.時鐘() if 時刻 is None else 時刻
        with self._鎖:
            if self.基準 is None:
                self.基準 = 時刻
            self.偏移 = 時刻 - self.基準
            self.已開始 = True

    def 對齊串流時刻(self, 片段時刻):
        """YouTube：開始() 之後呼叫，片段時刻 = 第一個寫出的 HLS 片段的 PDT（epoch 秒）。
        音訊第 0 秒的直播秒改成 片段時刻 − 開播，延遲也換成這次實測的值（收到第一個位元組的時刻 − 片段時刻），
        聊天室與漂移校正跟著用同一個基準。沒有開播時間、還沒開始、或讀不懂就不動，回傳 False。"""
        with self._鎖:
            if self.已開始:
                self.對齊完成 = True
            if self.已開始 and 片段時刻 is not None:
                self.第一段PDT = 片段時刻
            if self.開播 is None or not self.已開始 or 片段時刻 is None:
                return False
            收到 = self.基準 + self.偏移
            self.延遲 = 收到 - 片段時刻
            self.基準 = self.開播 + self.延遲
            self.偏移 = 片段時刻 - self.開播
            self.串流時刻對齊 = True
            return True

    def 音訊秒轉直播秒(self, 音訊秒):
        return self.偏移 + self.補償 + 音訊秒

    def 時刻轉直播秒(self, 時刻=None):
        """聊天室留言、「幾分鐘前」用：某個時刻對應的直播秒（抓不到開播時間又還沒收到音訊時當 0）。"""
        時刻 = self.時鐘() if 時刻 is None else 時刻
        with self._鎖:
            return 0.0 if self.基準 is None else max(0.0, 時刻 - self.基準)

    def 發送時刻轉直播秒(self, 時刻):
        """YouTube 聊天室：留言的發送時刻（epoch 秒）→ 直播秒，不扣串流延遲（發送時刻本身就是直播端的時刻）。
        有開播：時刻 − 開播。抓不到開播（+ 模式，含連續直播）：時刻 − 第一段PDT（和直播稿同一個零點）。
        兩者都沒有（讀不到 PDT）：時刻 + 延遲 − 基準（用估計的延遲換成這台電腦收到的時刻，和直播稿同一套）。
        還不能定下來（+ 模式還沒收到音訊、或 PDT 還沒對齊）回傳 None，呼叫的人晚一點再換算。"""
        with self._鎖:
            if self.開播 is not None:
                return max(0.0, 時刻 - self.開播)
            if self.第一段PDT is not None:
                return max(0.0, 時刻 - self.第一段PDT)
            if self.基準 is None or not self.對齊完成:
                return None
            return max(0.0, 時刻 + self.延遲 - self.基準)

    def 現在直播秒(self):
        return self.時刻轉直播秒() if self.基準 is not None else None

    def 段收滿(self, 音訊結束秒, 時刻):
        """每段音訊收滿時呼叫（時刻 = 讀完這一段的時刻）。回傳這次往前補了幾秒（0 = 沒補）。"""
        if self.基準 is None:
            return 0.0
        落後 = (時刻 - self.基準) - self.音訊秒轉直播秒(音訊結束秒)
        if self._基線 is None:
            self._基線 = 落後
            return 0.0
        超過 = 落後 - self._基線
        if 超過 <= 漂移門檻秒:
            self._超過們 = []
            return 0.0
        self._超過們.append(超過)
        if len(self._超過們) < 漂移確認次數:
            return 0.0
        補 = min(self._超過們)       # 取比較小的那個，寧可少補不要多補
        self._超過們 = []
        self.補償 += 補
        return 補

    def 字(self, 直播秒):
        return timefmt.秒轉字(直播秒, self.加號)

    def 標記(self, 直播秒):
        return timefmt.標記(直播秒, self.加號)


# ---- 這一場的時軸（介面、摘要引擎、存檔共用；文字稿模式沒有時軸）----
_目前 = None
_資訊 = None


def 設定目前(軸, 資訊=None):
    global _目前, _資訊
    _目前, _資訊 = 軸, 資訊


def 清除():
    設定目前(None, None)


def 目前():
    return _目前


def 資訊():
    return _資訊


def 加號():
    """這一場抓不到開播時間（時間從開始擷取起算）→ 時間字前面加「+」。"""
    return bool(_目前 is not None and _目前.加號)


def 現在直播秒():
    return None if _目前 is None else _目前.現在直播秒()


def 檔頭():
    """存檔開頭的說明（直播主、標題、分類、開播時間或「從開始擷取起算」）；文字稿模式回傳空字串。
    每行以「# 」開頭：文字稿模式重讀直播稿時會略過。"""
    if _目前 is None:
        return ""
    行們 = []
    if _資訊:
        for 名, 鍵 in (("直播主", "直播主"), ("標題", "標題"), ("分類", "遊戲")):
            if _資訊.get(鍵):
                行們.append(f"# {名}：{_資訊[鍵]}")
    if _目前.有開播:
        開播字 = datetime.fromtimestamp(_目前.開播).strftime("%Y-%m-%d %H:%M:%S")
        對齊 = _目前.說明 or f"已扣除約 {_目前.延遲:.0f} 秒串流延遲"
        行們.append(f"# 開播：{開播字}（本機時間）；時間為直播實際進行時間（對齊音訊內容，{對齊}）")
    elif _目前.連續直播開播 is not None:
        開播字 = datetime.fromtimestamp(_目前.連續直播開播).strftime("%Y-%m-%d %H:%M:%S")
        行們.append(f"# 連續直播超過 24 小時（開播：{開播字}，本機時間）：時間為從開始擷取起算（前面加 +）")
    else:
        行們.append("# 抓不到開播時間：時間為從開始擷取起算（前面加 +）")
    return "\n".join(行們) + "\n\n"
