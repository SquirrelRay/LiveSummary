# 目前語言的狀態（純 Python，不碰介面，方便單獨測試）：給狀態列的「語言」藥丸與「重新偵測」按鈕用。
#   手動語言：      語言：日文（手動）
#   自動偵測中：    語言：偵測中…
#   偵測成功：      語言：日文（自動偵測）
#   第一次信心低／失敗，退回中文：  語言：中文（偵測不確定，可按重新偵測或手動選語言）
#   重新偵測信心低／失敗：保持原語言，並註明  語言：日文（重新偵測不確定，維持原語言）
語言名稱 = {"zh": "中文", "ja": "日文", "en": "英文", "ko": "韓文"}

閒置, 手動, 自動 = "閒置", "手動", "自動"


class 語言狀態:
    def __init__(self):
        self.模式 = 閒置
        self.語言 = None        # 目前實際使用的語言代碼（自動偵測完成前是 None）
        self.偵測中 = False
        self.備註 = ""          # 括號裡的說明；空字串 = 一般（手動／自動偵測）
        self.文字稿模式 = False

    def 開始(self, 語言設定, 直播=True):
        """按下開始。語言設定 = "auto" 或語言代碼。"""
        self.語言, self.備註, self.偵測中 = None, "", False
        self.文字稿模式 = not 直播
        if 語言設定 == "auto":
            self.模式 = 自動
            self.偵測中 = 直播        # 文字稿重播不會偵測語言
        else:
            self.模式, self.語言 = 手動, 語言設定

    def 結束(self):
        self.模式, self.偵測中 = 閒置, False

    def 可重新偵測(self):
        """只有自動模式、正在跑、而且目前不是偵測中，按鈕才可用。"""
        return self.模式 == 自動 and not self.文字稿模式 and not self.偵測中

    def 顯示按鈕(self):
        return self.模式 == 自動 and not self.文字稿模式

    def 要求重新偵測(self):
        """按了重新偵測。回傳 True = 接受（會通知引擎）。清掉目前的偵測結果，顯示偵測中。"""
        if not self.可重新偵測():
            return False
        self.偵測中, self.備註 = True, ""
        return True

    def 收偵測(self, 語言, 狀態="ok", 重新偵測=False):
        """引擎的 language_detected 事件。狀態：ok／低信心／失敗。
        重新偵測失敗時，引擎會把原語言傳回來（維持不變），這裡只加上說明。"""
        if self.模式 != 自動:
            return
        self.偵測中, self.語言 = False, 語言
        if 狀態 == "ok":
            self.備註 = ""
        else:
            原因 = "不確定" if 狀態 == "低信心" else "失敗"
            self.備註 = f"重新偵測{原因}，維持原語言" if 重新偵測 else f"偵測{原因}，可按重新偵測或手動選語言"

    def 有警示(self):
        return bool(self.備註)

    def 顯示中(self):
        return self.模式 != 閒置

    def 文字(self):
        if self.模式 == 閒置:
            return ""
        if self.文字稿模式 and self.模式 == 自動:
            return "語言：未偵測（文字稿模式）"
        if self.偵測中:
            return "語言：偵測中…"
        名 = 語言名稱.get(self.語言, self.語言 or "?")
        if self.模式 == 手動:
            return f"語言：{名}（手動）"
        return f"語言：{名}（{self.備註 or '自動偵測'}）"
