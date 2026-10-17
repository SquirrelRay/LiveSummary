# 回報問題的預覽視窗（設定框「關於」→「🐞 回報問題」）：
# 打開時在背景產生診斷文字（diagnostics.產生，會跑 nvidia-smi，最多幾秒），產生好才顯示在唯讀文字框、才能按確認。
# 「複製並開啟回報表單」：診斷文字放進剪貼簿 → 開 Google 表單，使用者在「診斷資訊」欄按 Ctrl+V 貼上。
# 「取消」或直接關視窗：不碰剪貼簿、不開網頁。
import threading

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

import diagnostics
import version

說明字 = "以下內容會複製到剪貼簿，不含 API 金鑰、網址或直播內容，你可以先看過"
貼上說明 = "按下後會開啟回報表單，請在表單的「診斷資訊」欄按 Ctrl+V 貼上。"
收集中字 = "正在收集診斷資訊…"


class 回報預覽框(QDialog):
    _產生完成 = Signal(str)          # 背景執行緒 → 介面執行緒

    def __init__(self, 父=None, 產生=None, 背景=True):
        """產生：產生診斷文字的函式（測試換成假的）；背景=False 直接在呼叫的執行緒產生（測試用）。"""
        super().__init__(父)
        self._產生 = 產生 or diagnostics.產生
        self.文字 = ""
        self.setWindowTitle(f"{version.產品名} 回報問題")
        self.setMinimumSize(520, 460)
        版 = QVBoxLayout(self)
        版.setContentsMargins(20, 18, 20, 16)
        版.setSpacing(10)
        self.說明 = QLabel(說明字)
        self.說明.setWordWrap(True)
        self.說明.setStyleSheet("font-weight: 700;")
        版.addWidget(self.說明)
        self.內容框 = QPlainTextEdit()
        self.內容框.setReadOnly(True)
        self.內容框.setPlainText(收集中字)
        版.addWidget(self.內容框, 1)
        註 = QLabel(貼上說明)
        註.setObjectName("小標")
        註.setWordWrap(True)
        版.addWidget(註)
        列 = QHBoxLayout()
        列.addStretch(1)
        self.取消鈕 = QPushButton("取消")
        self.確認鈕 = QPushButton("複製並開啟回報表單")
        self.確認鈕.setObjectName("開始")
        self.確認鈕.setEnabled(False)          # 診斷文字產生好才能按
        for 鈕 in (self.取消鈕, self.確認鈕):
            鈕.setCursor(Qt.PointingHandCursor)
            列.addWidget(鈕)
        版.addLayout(列)
        self.取消鈕.clicked.connect(self.reject)
        self.確認鈕.clicked.connect(self.複製並開啟)
        self._產生完成.connect(self._顯示)
        if 背景:
            threading.Thread(target=self._背景產生, name="產生診斷資訊", daemon=True).start()
        else:
            self._顯示(self._安全產生())

    def _安全產生(self):
        try:
            return self._產生()
        except Exception:          # noqa: BLE001  產生失敗也要給一段文字（diagnostics.產生 本身已經不丟例外）
            return diagnostics.組文字({})

    def _背景產生(self):
        文字 = self._安全產生()
        try:
            self._產生完成.emit(文字)
        except RuntimeError:          # 視窗已經被刪掉（例如程式正在結束）：不用顯示了
            pass

    def _顯示(self, 文字):
        self.文字 = 文字
        self.內容框.setPlainText(文字)
        self.確認鈕.setEnabled(True)

    def 複製並開啟(self):
        if not self.文字:
            return
        QApplication.clipboard().setText(self.文字)
        QDesktopServices.openUrl(QUrl(version.回報表單網址))
        self.accept()
