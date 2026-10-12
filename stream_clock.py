# 直播時鐘：把「音訊秒數」和「收到的時刻」換成直播實際進行時間（直播秒），對齊音訊內容（= Twitch 重播的時間軸）。
#   有開播時間：直播秒 = 收到時刻 − 開播時間 − 延遲秒（串流延遲：音訊內容比「現在 − 開播時間」晚多少）
#   抓不到開播時間：以收到第一段音訊的時刻當 0，時間字前面加「+」（例如 [+12:34]）
# 每句話：直播秒 = 第一段音訊的直播秒 + 音訊秒數 + 漂移補償；聊天室：直播秒 = 收到時刻 − 開播時間 − 延遲秒（和直播稿同一套）。
# 漂移校正：廣告被濾掉、斷線重連都會讓音訊少一段，句子的時間就會越來越落後；
#           每段收滿時比較「用時鐘推算」和「用音訊累計」的直播秒，連續兩段都落後超過門檻才往前補（只往前、不倒退）。
import threading
import time
from datetime import datetime

import timefmt

延遲秒 = 11.0          # 2026-10-12 量 13 個頻道（2 秒分段）的中位數約 10.9 秒；4 秒分段的頻道約 19 秒，誤差較大
漂移門檻秒 = 8.0        # 比第一段的落後量多出這麼多才算掉段（網路一時卡住、之後會補回的不算）
漂移確認次數 = 2        # 連續幾段都超過門檻才補（一時卡住通常下一段就追回來了）


class 時軸:
    def __init__(self, 開播=None, 時鐘=time.time, 延遲=延遲秒):
        """開播：開播時刻（epoch 秒），None = 抓不到開播時間。時鐘：測試可換成假時鐘。"""
        self.開播, self.時鐘, self.延遲 = 開播, 時鐘, 延遲
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

    def 音訊秒轉直播秒(self, 音訊秒):
        return self.偏移 + self.補償 + 音訊秒

    def 時刻轉直播秒(self, 時刻=None):
        """聊天室留言、「幾分鐘前」用：某個時刻對應的直播秒（抓不到開播時間又還沒收到音訊時當 0）。"""
        時刻 = self.時鐘() if 時刻 is None else 時刻
        with self._鎖:
            return 0.0 if self.基準 is None else max(0.0, 時刻 - self.基準)

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
        行們.append(f"# 開播：{開播字}（本機時間）；時間為直播實際進行時間（對齊音訊內容，已扣除約 {_目前.延遲:.0f} 秒串流延遲）")
    else:
        行們.append("# 抓不到開播時間：時間為從開始擷取起算（前面加 +）")
    return "\n".join(行們) + "\n\n"
