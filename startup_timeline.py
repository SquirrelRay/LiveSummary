# 啟動時間里程碑紀錄＋面板空狀態的階段（純 Python，不碰介面，方便單獨測試）。
#
# 1. 里程碑紀錄：從按下「開始」起算，各里程碑第一次發生時，把相對秒數寫進 logs/啟動里程碑_時間.txt。
#    每個里程碑只記第一次；同一件事的不同說法（第一句顯示：有字幕／沒開字幕以文字稿代替）算同一個，只記先發生的那個。
#    沒按過開始（例如命令列執行）時，標記不做任何事。
#    紀錄只含時間與設定數字，不含 API 金鑰。寫檔失敗不會影響程式。
# 2. 啟動階段：面板在「還沒有內容」時顯示哪一句提示（載入模型中 → 聆聽中 → 轉錄與翻譯中 → 第一句出現後消失）。
import os
import threading
import time

import app_paths
import events

日誌資料夾 = app_paths.日誌資料夾()      # %LOCALAPPDATA%\直播摘要\logs（位置見 app_paths）

# 里程碑名稱（引擎與介面共用同一份，避免打錯字）
直播檢查完成 = "直播檢查完成"
找到ffmpeg = "找到 ffmpeg"
模型載入完成 = "轉錄模型載入完成"
擷取已啟動 = "擷取程序已啟動"
第一段收滿 = "第一段音訊收滿"
語言偵測完成 = "語言偵測完成"
第一段送轉錄 = "第一段送去轉錄"
第一段轉錄完成 = "第一段轉錄完成"
第一句文字稿 = "第一句文字稿產生"
第一句進佇列 = "第一句進入翻譯佇列"
翻譯請求送出 = "第一句翻譯請求送出"
翻譯回來 = "第一句翻譯回來"
第一句顯示 = "第一句顯示到字幕面板"
第一句顯示_無字幕 = "第一句顯示（沒開字幕，以文字稿代替）"
聊天第一則 = "第一則聊天留言（聊天室翻譯開著）"
聊天第一批送出 = "第一批聊天翻譯送出"
聊天第一批回來 = "第一批聊天翻譯回來"
聊天第一則顯示 = "第一則聊天顯示（聊天室翻譯開著）"

# 同一組裡任一個記過，其他的就不再記（「第一句顯示」只會有一行）
同組們 = [{第一句顯示, 第一句顯示_無字幕}]
_同組 = {名: 組 for 組 in 同組們 for 名 in 組}


class 里程碑紀錄:
    def __init__(self, 資料夾=None, 時鐘=time.time):
        self.資料夾 = 資料夾 or 日誌資料夾
        self.時鐘 = 時鐘
        self.路徑 = None
        self._起點 = None
        self._記過 = set()
        self._鎖 = threading.Lock()

    def 開始(self, 設定說明=None, 起點=None):
        """按下開始時呼叫。設定說明 = {名稱: 值}，寫在檔案開頭。回傳紀錄檔路徑（寫不出來回傳 None）。"""
        with self._鎖:
            self._起點 = 起點 if 起點 is not None else self.時鐘()
            self._記過 = set()
            self.路徑 = None
            try:
                os.makedirs(self.資料夾, exist_ok=True)
                self.路徑 = os.path.join(self.資料夾, "啟動里程碑_" + time.strftime("%Y%m%d_%H%M%S", time.localtime(self._起點)) + ".txt")
                說明 = "".join(f"{k} = {v}\n" for k, v in (設定說明 or {}).items())
                self._寫("# 啟動里程碑（相對秒數 = 從按下「開始」起算）\n" + 說明 + "\n")
                self._寫_行(0.0, "按下開始", {})
            except OSError:
                self.路徑 = None
            return self.路徑

    def 標記(self, 名稱, **附註):
        """記下里程碑第一次發生的相對秒數並回傳；已記過或還沒按開始回傳 None。永遠不丟例外。"""
        try:
            with self._鎖:
                if self._起點 is None or 名稱 in self._記過 or _同組.get(名稱, set()) & self._記過:
                    return None
                self._記過.add(名稱)
                秒 = round(self.時鐘() - self._起點, 2)
                self._寫_行(秒, 名稱, 附註)
                return 秒
        except (OSError, ValueError, TypeError):
            return None

    def _寫_行(self, 秒, 名稱, 附註):
        附 = "  | " + "，".join(f"{k}={v}" for k, v in 附註.items()) if 附註 else ""
        self._寫(f"[+{秒:7.2f}s] {名稱}{附}\n")

    def _寫(self, 文字):
        if not self.路徑:
            return
        try:
            with open(self.路徑, "a", encoding="utf-8") as f:
                f.write(文字)
        except OSError:
            pass


紀錄 = 里程碑紀錄()


def 開始(設定說明=None, 起點=None):
    return 紀錄.開始(設定說明, 起點)


def 標記(名稱, **附註):
    """引擎與介面共用：記下里程碑，並送出 milestone 事件讓面板切換提示。"""
    秒 = 紀錄.標記(名稱, **附註)
    if 秒 is not None:
        events.送出("milestone", 名稱=名稱, 秒=秒)
    return 秒


# ---------- 面板空狀態的階段 ----------
載入中, 聆聽中, 轉錄中, 完成 = 0, 1, 2, 3
提示文字 = {載入中: "載入模型中…", 聆聽中: "聆聽中，等待第一段…", 轉錄中: "轉錄與翻譯中…", 完成: ""}
_到達階段 = {模型載入完成: 聆聽中, 第一段送轉錄: 轉錄中, 翻譯請求送出: 轉錄中,
           第一句顯示: 完成, 第一句顯示_無字幕: 完成}


class 啟動階段:
    """只會往前走（載入中 → 聆聽中 → 轉錄中 → 完成）；第一句出現後就是「完成」，提示消失。"""

    def __init__(self):
        self.階段 = 完成        # 沒按開始之前沒有提示

    def 重設(self, 有模型=True):
        """按下開始。文字稿重播不載入模型，也不顯示提示。"""
        self.階段 = 載入中 if 有模型 else 完成

    def 收里程碑(self, 名稱):
        目標 = _到達階段.get(名稱)
        if 目標 is not None and self.階段 != 完成 and 目標 > self.階段:
            self.階段 = 目標

    def 結束(self):
        """出錯或結束：不再顯示提示。"""
        self.階段 = 完成

    def 提示(self):
        return 提示文字[self.階段]
