# 啟動面板的「啟動中」狀態邏輯（純 Python，不碰介面，方便單獨測試）。
# 狀態：待命 → 啟動中（可多次換階段）→ 成功／失敗（失敗後回到待命，可重新操作）。
通用文字 = "啟動中…"


class 啟動狀態:
    def __init__(self):
        self.啟動中 = False
        self.階段 = ""
        self.錯誤 = ""

    def 開始(self, 階段=""):
        """按下開始。已經在啟動中就不重複進入，回傳 False。"""
        if self.啟動中:
            return False
        self.啟動中, self.階段, self.錯誤 = True, 階段, ""
        return True

    def 換階段(self, 階段):
        if self.啟動中 and 階段:
            self.階段 = 階段

    def 成功(self):
        self.啟動中, self.階段, self.錯誤 = False, "", ""

    def 失敗(self, 訊息=""):
        self.啟動中, self.階段 = False, ""
        self.錯誤 = 訊息 or "啟動失敗，請再試一次。"

    # ---- 給介面用的顯示內容 ----
    def 文字(self):
        if self.啟動中:
            return f"{通用文字}（{self.階段}）" if self.階段 else 通用文字
        return self.錯誤

    def 開始鈕可用(self):
        return not self.啟動中

    def 顯示進度條(self):
        return self.啟動中

    def 是錯誤(self):
        return bool(self.錯誤) and not self.啟動中
